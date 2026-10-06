"""Opt-in campaign controller. No LLM; all sends pass a durable dispatch guard."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select, update

from erasure import email_routes
from erasure.connectors.email import EmailConnector
from erasure.crypto import digest
from erasure.gmail import GmailPreflightError
from erasure.models import (
    AutomaticDelivery,
    Broker,
    Case,
    Event,
    Job,
    Profile,
    RouteResearch,
    case_token,
)
from erasure.preparation import prepare_backlog
from erasure.validation import is_recently_validated

CONSENT_KEY = "automatic_campaign"
LOCAL_CHECKS_PER_TICK = 25
CONTRACT_VERSION = 2
DEFAULT_CATEGORIES = {
    "people_search", "professional", "recruitment", "consumer_marketing",
    "postal_marketing", "advertising",
}


def minimal_profile(store):
    profile = store.get_profile() or {}
    return {
        **{key: profile.get(key) for key in ("full_name", "email", "other_emails")},
        "_signature": store.get_signature(),
    }


def make_plan(store, broker, token, settings=None, *, country=None, allow_postal=None):
    if settings is not None:
        entry = email_routes.routes(settings).get(broker.domain)
        if not entry:
            raise ValueError("No reviewed email workflow for this broker")
        saved = consent(store)
        profile = store.get_profile() or {}
        profile["_signature"] = store.get_signature()
        return email_routes.prepare(
            *entry, broker, profile, token,
            country if country is not None else saved.get("country", "EEA"),
            allow_postal if allow_postal is not None else saved.get("allow_postal", False),
        )
    minimal = SimpleNamespace(
        name=broker.name, contact=broker.contact, required_fields='{"include_postal": false}'
    )
    return EmailConnector(None).prepare(
        broker=minimal, profile=minimal_profile(store), case_token=token
    )


def identity_template_hash(store):
    return digest(asdict(preview_plan(store)))


def preview_plan(store):
    return make_plan(
        store, SimpleNamespace(name="Example broker", contact="privacy@example.test"), "ER-PREVIEW"
    )


def consent(store):
    return store.get_setting(CONSENT_KEY, {})


def pause(workflow):
    workflow.store.set_setting("paused", "true")


def stop(workflow):
    # Hold legacy sends too, not just deliveries owned by the new controller.
    pause(workflow)
    saved = consent(workflow.store)
    saved.update(enabled=False, stopped_at=datetime.now(UTC).isoformat())
    workflow.store.set_setting(CONSENT_KEY, saved, encrypted=True)


def wake_jobs(workflow):
    now = datetime.now(UTC)
    for job in workflow.session.scalars(select(Job).where(Job.status == "pending")):
        if job.kind in {"campaign_tick", "poll_gmail"} or job.last_error == "Held while automatic sending is paused":
            job.run_at = now
            job.last_error = ""
    workflow.session.commit()


def resume(workflow):
    saved = consent(workflow.store)
    if not saved.get("enabled"):
        raise ValueError("Start automatic emails to give permission again")
    problem = consent_problem(workflow, ignore_pause=True)
    if problem:
        raise ValueError(problem)
    workflow.store.set_setting("paused", "false")
    wake_jobs(workflow)


def preview_rows(workflow, country="EEA", allow_postal=False):
    entries = email_routes.routes(workflow.settings)
    profile = workflow.store.get_profile() or {}
    profile["_signature"] = workflow.store.get_signature()
    cases = {c.broker_id: c for c in workflow.session.scalars(select(Case))}
    brokers = list(workflow.session.scalars(select(Broker).where(Broker.active.is_(True))))
    # An existing case takes precedence over an alias of the same reviewed workflow.
    def existing_first(broker):
        case = cases.get(broker.id)
        if case and case.state in {"done", "removed", "not_found", "rejected"}:
            return (0, broker.id)
        return (1 if case and case.submitted_at else 2, broker.id)

    brokers.sort(key=existing_first)
    seen, rows = set(), []
    for broker in brokers:
        entry = entries.get(broker.domain)
        if not entry:
            continue
        route, guide = entry
        case = cases.get(broker.id)
        if guide.id in seen:
            continue
        seen.add(guide.id)
        # The user approves the displayed reviewed recipient. Existing sent cases
        # keep their original route and cannot silently be redirected.
        destination = broker.contact if case and case.submitted_at else route.destination
        try:
            plan = email_routes.prepare(route, guide, target_for_plan(broker, destination),
                                        profile, "ER-PREVIEW", country, allow_postal)
            reason = ""
        except ValueError as exc:
            plan, reason = None, str(exc)
        if case and case.state in {"done", "removed", "not_found", "rejected"}:
            reason = "Already completed — no new initial request"
            plan = None
        rows.append(dict(broker=broker, guide=guide, route=route, plan=plan, reason=reason,
                         state=case.state if case else "candidate"))
    return rows


def target_for_plan(broker, destination):
    return SimpleNamespace(name=broker.name, domain=broker.domain, contact=destination)


def preview_hash(workflow, country="EEA", allow_postal=False, *, rows=None):
    scope = {
        str(b.id): scope_key(b)
        for b in workflow.session.scalars(select(Broker).where(Broker.active.is_(True)))
    }
    if rows is None:
        rows = preview_rows(workflow, country, allow_postal)
    plans = {str(r["broker"].id): asdict(r["plan"]) for r in rows if r["plan"]}
    return digest({"identity": identity_template_hash(workflow.store), "scope": scope,
                   "plans": plans, "country": country, "allow_postal": allow_postal,
                   "postal": postal_hash(workflow.store) if allow_postal else ""})


def postal_hash(store):
    return digest((store.get_profile() or {}).get("postal_address", ""))


def scope_key(broker):
    return [broker.domain.lower(), broker.contact.strip().lower()]


def consent_problem(workflow, *, ignore_pause=False):
    saved = consent(workflow.store)
    profile = workflow.session.get(Profile, 1)
    if not saved.get("enabled"):
        return "Automatic campaign is off"
    if saved.get("version") != CONTRACT_VERSION:
        return "Review the updated campaign plan to resume automatic requests"
    if not ignore_pause and workflow.store.get_setting("paused", "false") == "true":
        return "Campaign paused"
    if not profile or not profile.mandate_signed_at or not profile.started_at:
        return "Complete and sign your profile first"
    if saved.get("identity_template_hash") != identity_template_hash(workflow.store):
        return "Identity or request template changed; review and enable again"
    residence = workflow.store.get_setting('recommendation_country', '')
    if residence and residence != saved.get('country'):
        return "Country changed; review your email permissions again"
    if saved.get("allow_postal") and saved.get("postal_hash") != postal_hash(workflow.store):
        return "Postal address changed; review your campaign plan again"
    return ""


def enable(workflow, daily_limit, approved_preview_hash, country="EEA", allow_postal=False,
           *, include_new=False, keep_paused=False):
    if not 1 <= daily_limit <= 50:
        raise ValueError("Choose a daily limit between 1 and 50")
    profile = workflow.session.get(Profile, 1)
    identity = minimal_profile(workflow.store)
    if (
        not profile
        or not profile.mandate_signed_at
        or not identity.get("full_name")
        or not identity.get("email")
    ):
        raise ValueError("Complete and sign your profile first")
    if identity.get("_signature") is None:
        raise ValueError("A signed mandate is required")
    if country not in email_routes.COUNTRIES:
        raise ValueError("Choose a supported residence")
    if approved_preview_hash != preview_hash(workflow, country, allow_postal):
        raise ValueError(
            "Your profile, catalog or template changed. Reload the preview before enabling"
        )
    rows = preview_rows(workflow, country, allow_postal)
    plans = {}
    for row in rows:
        if row["plan"] is None:
            continue
        if row['guide'].relevance.category not in DEFAULT_CATEGORIES:
            continue
        broker = row["broker"]
        if broker.contact != row["plan"].destination:
            broker.contact = row["plan"].destination
            broker.last_validated_at = None
        broker.connector_type = "email"
        plans[str(broker.id)] = digest(asdict(row["plan"]))
    profile.started_at = profile.started_at or datetime.now(UTC)
    scope = {
        str(b.id): scope_key(b)
        for b in workflow.session.scalars(select(Broker).where(Broker.active.is_(True)))
    }
    for broker_id in scope:
        if workflow.session.scalar(select(Case.id).where(Case.broker_id == int(broker_id))) is None:
            workflow.session.add(Case(broker_id=int(broker_id)))
    workflow.store.set_setting(
        CONSENT_KEY,
        {
            "enabled": True,
            "include_new": include_new,
            "version": CONTRACT_VERSION,
            "country": country,
            "allow_postal": allow_postal,
            "postal_hash": postal_hash(workflow.store) if allow_postal else "",
            "plans": plans,
            "daily_limit": daily_limit,
            "scope": scope,
            "identity_template_hash": identity_template_hash(workflow.store),
            "approved_at": datetime.now(UTC).isoformat(),
        },
        encrypted=True,
    )
    workflow.store.set_setting("paused", "true" if keep_paused else "false")
    if not keep_paused:
        wake_jobs(workflow)
    # The recurring controller already exists; wake it without adding another copy.
    job = workflow.session.scalar(
        select(Job).where(Job.kind == "campaign_tick", Job.status.in_(["pending", "running"]))
    )
    if job:
        if job.status == "pending":
            job.run_at = datetime.now(UTC)
        workflow.session.commit()
    else:
        workflow.store.enqueue_if_missing("campaign_tick", {})


def include_new_routes(workflow):
    """Extend a continuous plan with reviewed initial requests, never reset existing work."""
    saved = consent(workflow.store)
    if not saved.get("include_new") or consent_problem(workflow):
        return 0
    cases = {c.broker_id: c for c in workflow.session.scalars(select(Case))}
    added = 0
    for row in preview_rows(workflow, saved["country"], saved.get("allow_postal", False)):
        broker, plan = row["broker"], row["plan"]
        key, case = str(broker.id), cases.get(broker.id)
        if (plan is None or key in saved.get("plans", {})
                or row["guide"].relevance.category not in DEFAULT_CATEGORIES
                or (case and (case.state != "candidate" or case.submitted_at))):
            continue
        # The dated official recipe, not an arbitrary catalog edit, chooses the recipient.
        if broker.contact != plan.destination:
            broker.contact = plan.destination
            broker.last_validated_at = None
        broker.connector_type = "email"
        if case is None:
            case = Case(broker_id=broker.id)
            workflow.session.add(case)
            workflow.session.flush()
        saved.setdefault("scope", {})[key] = scope_key(broker)
        saved.setdefault("plans", {})[key] = digest(asdict(plan))
        workflow.session.add(Event(
            case_id=case.id, kind="campaign_route_added",
            summary="Reviewed email route added to automatic plan",
            encrypted_payload=workflow.store.vault.encrypt({
                "destination": plan.destination, "disclosed_fields": plan.disclosed_fields,
            }),
        ))
        added += 1
    if added:
        workflow.store.set_setting(CONSENT_KEY, saved, encrypted=True)
    return added


def managed(workflow, case):
    # Disabled consent still owns old work: queued jobs cannot revert to unguarded sends.
    saved = consent(workflow.store)
    return (
        str(case.broker_id) in saved.get("scope", {})
        or workflow.session.scalar(
            select(AutomaticDelivery.id).where(AutomaticDelivery.case_id == case.id).limit(1)
        )
        is not None
    )


def eligible(workflow, broker):
    return not route_problem(workflow, broker) and is_recently_validated(broker)


def route_problem(workflow, broker):
    saved = consent(workflow.store)
    if not broker.active or broker.connector_type != "email":
        return "Broker is not an active email route"
    if saved.get("scope", {}).get(str(broker.id)) != scope_key(broker):
        return "Recipient is outside the approved campaign"
    if str(broker.id) not in saved.get("plans", {}):
        return "Review this new or changed request in your campaign plan"
    try:
        plan = make_plan(workflow.store, broker, "ER-PREVIEW", workflow.settings)
    except ValueError as exc:
        return str(exc)
    if saved.get("plans", {}).get(str(broker.id)) != digest(asdict(plan)):
        return "Review this new or changed request in your campaign plan"
    return ""


def day_start():
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def attempted_today(session):
    return (
        session.scalar(
            select(func.count())
            .select_from(AutomaticDelivery)
            .where(AutomaticDelivery.started_at >= day_start())
        )
        or 0
    )


def queue_delivery(workflow, case):
    if consent_problem(workflow) or not eligible(workflow, case.broker):
        return False
    if case.state not in {"prepared", "queued"}:
        return False
    sequence = case.attempt_count + 1
    plan = make_plan(workflow.store, case.broker, case_token(case.id), workflow.settings)
    row = workflow.session.scalar(
        select(AutomaticDelivery).where(
            AutomaticDelivery.case_id == case.id, AutomaticDelivery.sequence == sequence
        )
    )
    if row is None:
        row = AutomaticDelivery(
            case_id=case.id,
            sequence=sequence,
            payload_hash=digest(asdict(plan)),
            encrypted_plan=workflow.store.vault.encrypt(asdict(plan)),
            consent_hash=digest(consent(workflow.store)),
        )
        workflow.session.add(row)
        workflow.session.flush()
    if row.status == "cancelled" and row.started_at is None:
        row.status = "queued"
    if row.status != "queued":
        return False
    row.payload_hash = digest(asdict(plan))
    row.encrypted_plan = workflow.store.vault.encrypt(asdict(plan))
    row.consent_hash = digest(consent(workflow.store))
    # Only this controller schedules deliveries; the DB ledger remains the final guard.
    pending_ids = {
        workflow.store.vault.decrypt(j.encrypted_payload).get("delivery_id")
        for j in workflow.session.scalars(
            select(Job).where(Job.kind == "automatic_send", Job.status.in_(["pending", "running"]))
        )
    }
    if row.id not in pending_ids:
        workflow.session.add(
            Job(
                kind="automatic_send",
                encrypted_payload=workflow.store.vault.encrypt({"delivery_id": row.id}),
            )
        )
    case.state = "queued"
    workflow.session.commit()
    return True


def dispatch(workflow, delivery_id):
    session, store = workflow.session, workflow.store
    row = session.get(AutomaticDelivery, delivery_id)
    if row is None or row.status in {"sent", "uncertain", "cancelled"}:
        return
    case = session.get(Case, row.case_id)
    if row.status == "sending":
        if row.started_at and datetime.now(UTC) - row.started_at.replace(tzinfo=UTC) < timedelta(
            minutes=5
        ):
            return
        # A worker died after reserving delivery. Local committed evidence can resolve it;
        # otherwise we must not guess whether Gmail accepted the message.
        if case.attempt_count >= row.sequence and case.external_reference:
            row.status, row.reference = "sent", case.external_reference
        else:
            row.status, row.reason = (
                "uncertain",
                "Worker interrupted during delivery; check Gmail Sent",
            )
            case.state, case.last_error = "needs_action", row.reason
            workflow._create_approval(case.id, "delivery_uncertain", row.reason, {})
        session.commit()
        return
    problem = consent_problem(workflow)
    if not problem and not workflow.settings.live_submissions:
        problem = "Live sending is disabled"
    if not problem and (not store.get_setting("gmail_token") or store.get_setting("gmail_error")):
        problem = "Gmail needs connection or reconnection"
    if problem:
        row.reason = problem
        session.commit()
        return
    if case.state not in {"prepared", "queued"} or not eligible(workflow, case.broker):
        row.status, row.reason = "cancelled", "Request or recipient is no longer eligible"
        session.commit()
        return
    plan = make_plan(store, case.broker, case_token(case.id), workflow.settings)
    if row.payload_hash != digest(asdict(plan)) or row.consent_hash != digest(consent(store)):
        row.status, row.reason = (
            "cancelled",
            "Payload or permission changed; this queued send was cancelled",
        )
        case.state = "prepared"
        session.commit()
        return
    # One atomic SQL statement checks the daily budget and claims this delivery.
    today_count = (
        select(func.count())
        .select_from(AutomaticDelivery)
        .where(AutomaticDelivery.started_at >= day_start())
        .scalar_subquery()
    )
    claimed = session.execute(
        update(AutomaticDelivery)
        .where(
            AutomaticDelivery.id == row.id,
            AutomaticDelivery.status == "queued",
            today_count < consent(store)["daily_limit"],
        )
        .values(status="sending", started_at=datetime.now(UTC), reason=""),
        execution_options={"synchronize_session": False},
    ).rowcount
    session.commit()
    if not claimed:
        return
    session.refresh(row)
    try:
        workflow.submit_case(case.id, approved_plan=plan)
    except GmailPreflightError:
        # Identity verification happens before any send HTTP request. Preserve
        # the queued work without inventing an uncertain delivery or using budget.
        row.status, row.started_at = 'queued', None
        row.reason = 'Mailbox identity needs checking before sending'
    except Exception:
        # Even unexpected exceptions after an HTTP send may mean delivery happened.
        row.status, row.reason = (
            "uncertain",
            "Delivery interrupted; check Gmail Sent before retrying",
        )
        case.state, case.last_error = "needs_action", row.reason
        workflow._create_approval(case.id, "delivery_uncertain", row.reason, {})
    else:
        if case.state == "submitted":
            row.status, row.reference = "sent", case.external_reference
        elif case.state == "needs_action":
            row.status, row.reason = "uncertain", case.last_error or "Delivery needs review"
        else:
            row.status, row.reason = "cancelled", "Submission did not proceed"
    session.commit()


def research_broker(workflow, broker_id):
    broker = workflow.session.get(Broker, broker_id)
    saved = consent(workflow.store)
    if (
        consent_problem(workflow)
        or not broker
        or saved.get("scope", {}).get(str(broker.id)) != scope_key(broker)
    ):
        return
    entry = email_routes.routes(workflow.settings).get(broker.domain)
    if not entry or route_problem(workflow, broker):
        return
    row = workflow.session.get(RouteResearch, broker.id)
    if row is None:
        row = RouteResearch(broker_id=broker.id)
        workflow.session.add(row)
    # The maintainer has already reviewed the exact contact in dated official
    # sources. Users do not need to repeat that public research on every install.
    source = entry[0].evidence[0]
    row.status, row.reason = "verified", "Reviewed email workflow and official evidence"
    row.source_url, row.evidence = source.url, source.excerpt
    row.checked_at = datetime.now(UTC)
    row.next_check_at = datetime.now(UTC) + timedelta(days=60)
    broker.last_validated_at = datetime.combine(entry[0].checked_on, datetime.min.time(), UTC)
    broker.source = broker.policy_url = source.url
    workflow.session.commit()


def tick(workflow):
    session, store = workflow.session, workflow.store
    store.set_setting("campaign_last_tick", datetime.now(UTC).isoformat())
    if consent_problem(workflow):
        return
    include_new_routes(workflow)
    # These are local checks of already reviewed, explicitly approved recipes.
    # Bound work per tick for responsiveness, not per day as if fetching websites.
    for broker in research_candidates(workflow)[:LOCAL_CHECKS_PER_TICK]:
        research_broker(workflow, broker.id)
    prepare_backlog(workflow)
    saved = consent(store)
    remaining = max(0, saved["daily_limit"] - attempted_today(session))
    for case in session.scalars(
        select(Case).where(Case.state.in_(["prepared", "queued"])).order_by(Case.id)
    ):
        if not remaining:
            break
        if queue_delivery(workflow, case):
            remaining -= 1


def research_candidates(workflow):
    saved = consent(workflow.store)
    result = []
    for broker, case in workflow.session.execute(
        select(Broker, Case)
        .outerjoin(Case)
        .where(Broker.active.is_(True))
        .order_by(Broker.id)
    ):
        # Filter known exclusions before decrypting consent and rebuilding a plan
        # for each broker. The catalog scope is much larger than the email plan.
        if is_recently_validated(broker):
            continue
        if case and case.state in {"done", "removed", "not_found", "needs_action", "rejected"}:
            continue
        if (
            saved.get("scope", {}).get(str(broker.id)) != scope_key(broker)
            or str(broker.id) not in saved.get("plans", {})
            or route_problem(workflow, broker)
        ):
            continue
        # An old failed website check must not delay a newly approved recipe.
        # route_problem above still checks evidence age and the exact permission.
        result.append(broker)
    return result


def summary(workflow):
    session, store = workflow.session, workflow.store
    saved = consent(store)
    problem = consent_problem(workflow) or store.get_setting("campaign_error", "")
    last_tick = store.get_setting("campaign_last_tick", "")
    heartbeat = last_tick or saved.get("approved_at", "")
    if (
        not problem
        and heartbeat
        and datetime.now(UTC) - datetime.fromisoformat(heartbeat) > timedelta(minutes=5)
    ):
        problem = "Campaign checks delayed; check that the local app is running"
    today = attempted_today(session)
    limit = saved.get("daily_limit", 20)
    due_research = len(research_candidates(workflow)) if saved.get("enabled") else 0
    checked_today = (
        session.scalar(
            select(func.count())
            .select_from(RouteResearch)
            .where(RouteResearch.checked_at >= day_start())
        )
        or 0
    )
    queued = (
        session.scalar(
            select(func.count())
            .select_from(AutomaticDelivery)
            .where(AutomaticDelivery.status == "queued")
        )
        or 0
    )
    research_counts = dict(
        session.execute(
            select(RouteResearch.status, func.count()).group_by(RouteResearch.status)
        ).all()
    )
    scope_changes = (
        sum(
            saved.get("scope", {}).get(str(b.id)) != scope_key(b)
            for b in session.scalars(select(Broker).where(Broker.active.is_(True)))
        )
        if saved
        else 0
    )
    route_issues = []
    new_workflows = 0
    if saved.get("enabled") and saved.get("version") == CONTRACT_VERSION:
        new_workflows = sum(
            row["plan"] is not None and row["state"] == "candidate"
            and str(row["broker"].id) not in saved.get("plans", {})
            and (not saved.get("include_new")
                 or row["guide"].relevance.category in DEFAULT_CATEGORIES)
            for row in preview_rows(workflow, saved.get("country", "EEA"),
                                    saved.get("allow_postal", False))
        )
    for broker, case in session.execute(select(Broker, Case).join(Case)):
        if str(broker.id) not in saved.get("plans", {}) or case.state not in {"candidate", "prepared", "queued"}:
            continue
        if reason := route_problem(workflow, broker):
            route_issues.append({"name": broker.name, "reason": reason})
    if problem:
        label = problem
    elif not workflow.settings.live_submissions:
        label = "Preparation active · sending disabled"
    elif not store.get_setting("gmail_token") or store.get_setting("gmail_error"):
        label = "Preparation active · connect Gmail to send"
    elif today >= limit:
        label = "Daily sending limit reached · resumes tomorrow (UTC)"
    elif queued:
        label = "Sending eligible requests"
    elif due_research:
        label = "Checking reviewed workflows"
    elif route_issues:
        label = "Some workflows changed · review your campaign plan"
    elif new_workflows:
        label = ("Adding reviewed email routes automatically" if saved.get("include_new")
                 else "New email workflows available · review your campaign plan")
    elif saved.get("enabled") and not saved.get("plans"):
        label = "No email workflows match this plan · review the requirements below"
    else:
        label = "Monitoring replies and scheduled rechecks"
    return {
        "enabled": bool(saved.get("enabled")),
        "include_new": bool(saved.get("include_new")),
        "problem": problem,
        "label": label,
        "daily_limit": limit,
        "queued_count": queued,
        "sending_count": session.scalar(select(func.count()).select_from(AutomaticDelivery)
                                        .where(AutomaticDelivery.status == "sending")) or 0,
        "planned_count": len(saved.get("plans", {})),
        "today": today,
        'sent_count': session.scalar(select(func.count(func.distinct(Event.case_id))).where(Event.kind == 'submitted')) or 0,
        "scope_count": len(saved.get("scope", {})),
        "scope_changes": scope_changes,
        "route_issues": route_issues,
        "new_workflows": new_workflows,
        "research": research_counts,
        "research_due": due_research,
        "checked_today": checked_today,
        "last_tick": last_tick,
        "gmail_ready": bool(store.get_setting("gmail_token"))
        and not store.get_setting("gmail_error"),
        "live": workflow.settings.live_submissions,
    }
