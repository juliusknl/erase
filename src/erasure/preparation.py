"""Bounded, local draft replenishment. This module has no mail sender."""

import json
from datetime import UTC, datetime, timedelta

import yaml
from sqlalchemy import select

from erasure.connectors.email import EmailConnector
from erasure.knowledge import email_blocker, guide_index, guides
from erasure.models import Approval, Broker, Case, Event, Job, Profile, case_token
from erasure.validation import MAX_BATCH_SIZE, is_recently_validated


def playbooks(settings):
    path = settings.catalog_dir / "broker-playbooks.yml"
    result = yaml.safe_load(path.read_text())["brokers"] if path.exists() else {}
    for guide in guides(settings):
        for domain in guide.match_domains:
            # A richer guide may add constraints, never relax a known manual/form gate.
            previous = result.get(domain, {})
            route = "email" if guide.automation.mode == "email_minimal" else "manual"
            if guide.removal.method == "form":
                route = "form"
            if previous.get("route") in {"form", "manual"}:
                route = previous["route"]
            result[domain] = {
                **previous,
                "route": route,
                "note": " ".join([guide.automation.reason, *guide.removal.steps]),
                "guide_id": guide.id,
            }
    return result


def playbook(settings, domain):
    return playbooks(settings).get(domain, {})


def email_eligible(broker, settings):
    guide = guide_index(settings).get(broker.domain)
    return (
        broker.active
        and broker.connector_type == "email"
        and "@" in broker.contact
        and is_recently_validated(broker)
        and playbook(settings, broker.domain).get("route", "email") == "email"
        and (guide is None or not email_blocker(guide, broker.contact))
    )


def prepare_backlog(workflow):
    from erasure import campaign

    session, store = workflow.session, workflow.store
    # Unfinished requests must not silently disappear from the action queue.
    for case in session.scalars(select(Case).where(Case.state == "needs_action")):
        if (
            session.scalar(
                select(Approval.id).where(Approval.case_id == case.id, Approval.status == "pending")
            )
            is None
        ):
            route = playbook(workflow.settings, case.broker.domain)
            message = (
                route.get("note")
                or case.last_error
                or "Read the latest reply and choose the next step."
            )
            session.add(
                Approval(
                    case_id=case.id,
                    kind="next_step",
                    summary=message[:500],
                    encrypted_payload=store.vault.encrypt({"body": message}),
                )
            )
    session.commit()
    profile_record = session.get(Profile, 1)
    if (
        not profile_record
        or not profile_record.mandate_signed_at
        or not profile_record.started_at
        or store.get_setting("paused", "false") == "true"
    ):
        return 0
    profile = store.get_profile()
    if not profile or not profile.get("full_name") or not profile.get("email"):
        return 0
    profile["_signature"] = store.get_signature()
    automatic = campaign.consent(store).get("enabled", False)
    if automatic and campaign.consent_problem(workflow):
        return 0

    def eligible(broker):
        return campaign.eligible(workflow, broker) if automatic else email_eligible(
            broker, workflow.settings
        )

    ready = sum(
        eligible(c.broker)
        for c in session.scalars(select(Case).where(Case.state == "prepared"))
    )
    capacity = max(0, MAX_BATCH_SIZE - ready)
    busy = {
        store.vault.decrypt(j.encrypted_payload).get("case_id")
        for j in session.scalars(select(Job).where(Job.status.in_(["pending", "running"])))
    }
    prepared = 0
    for broker in session.scalars(
        select(Broker).where(Broker.active.is_(True)).order_by(Broker.id)
    ):
        if prepared >= capacity:
            break
        if not eligible(broker):
            continue
        case = session.scalar(select(Case).where(Case.broker_id == broker.id))
        if case and (case.state != "candidate" or case.id in busy or case.submitted_at):
            continue
        if case is None:
            case = Case(broker_id=broker.id)
            session.add(case)
            session.flush()
        if automatic:
            plan = campaign.make_plan(store, broker, case_token(case.id), workflow.settings)
        else:
            metadata = json.loads(broker.required_fields or "{}")
            metadata = metadata if isinstance(metadata, dict) else {}
            metadata["include_postal"] = False
            broker.required_fields = json.dumps(metadata)
            minimal = {k: v for k, v in profile.items() if k != "postal_address"}
            plan = EmailConnector(None).prepare(
                broker=broker, profile=minimal, case_token=case_token(case.id)
            )
        case.state = "prepared"
        case.last_error = ""
        case.next_action_at = None
        case.disclosed_fields = json.dumps(plan.disclosed_fields)
        session.add(
            Event(
                case_id=case.id,
                kind="request_prepared",
                summary="Automatically prepared for review; not sent",
                encrypted_payload=store.vault.encrypt(
                    {
                        "destination": plan.destination,
                        "subject": plan.subject,
                        "body": plan.body,
                        "disclosed_fields": plan.disclosed_fields,
                    }
                ),
            )
        )
        prepared += 1
    store.set_setting("preparation_last_check", datetime.now(UTC).isoformat())
    session.commit()
    return prepared


def pipeline_status(session, store, settings):
    from erasure.campaign import summary
    from erasure.workflow import Workflow

    ready = waiting = research = 0
    for broker, case in session.execute(
        select(Broker, Case).outerjoin(Case).where(Broker.active.is_(True))
    ):
        if case and case.state == "prepared" and email_eligible(broker, settings):
            ready += 1
        elif case and case.state in {"queued", "submitted", "processing"}:
            waiting += 1
        elif (case is None or case.state == "candidate") and not is_recently_validated(broker):
            research += 1
    last_value = store.get_setting("preparation_last_check")
    last_check = datetime.fromisoformat(last_value) if last_value else None
    if last_check and last_check.tzinfo is None:
        last_check = last_check.replace(tzinfo=UTC)
    profile = session.get(Profile, 1)
    enabled = bool(profile and profile.mandate_signed_at and profile.started_at)
    paused = store.get_setting("paused", "false") == "true"
    error = store.get_setting("preparation_error", "")
    stale = bool(
        enabled
        and not paused
        and last_check
        and datetime.now(UTC) - last_check > timedelta(minutes=15)
    )
    if error:
        label = "Preparation needs attention"
    elif paused:
        label = "Automation paused"
    elif not enabled:
        label = "Setup needed"
    elif stale:
        label = "Draft checks delayed"
    elif not last_check:
        label = "Waiting for first draft check"
    elif ready:
        label = f"{ready} email draft{'s' if ready != 1 else ''} ready"
    else:
        label = "No drafts ready"
    return {
        "automatic": summary(Workflow(session, store, settings)),
        "ready": ready,
        "waiting": waiting,
        "research": research,
        "last_check": last_check,
        "error": error,
        "paused": paused,
        "enabled": enabled,
        "stale": stale,
        "label": label,
    }
