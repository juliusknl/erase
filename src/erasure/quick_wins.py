"""User-completed privacy steps, distinct from broker-confirmed deletion."""

from datetime import UTC, date, datetime
from urllib.parse import quote, urlencode

import yaml
from sqlalchemy import select

from erasure.knowledge import guides, public_url
from erasure.models import AppSetting, Broker, Case, Event

# Plain-language fallbacks use the reviewed category, not inferred personal exposure.
BROKER_DESCRIPTIONS = {
    "professional": "A business-contact database used for sales and outreach.",
    "recruitment": "A professional-profile database used for recruitment.",
    "people_search": "A people-search service that makes personal records searchable.",
    "consumer_marketing": "A consumer-data business used for marketing and audience targeting.",
    "postal_marketing": "A mailing-list business used for advertising by post.",
    "advertising": "An advertising business that uses data to target or measure ads.",
    "credit_reference": "A credit-information service used to assess financial risk.",
    "identity_risk": "An identity and risk-information service used for verification or fraud checks.",
    "aggregate_business": "A business-information service that compiles company data.",
}


def action_url(destination, draft=''):
    """A reviewed mailbox opens a local draft; it never authorizes a send."""
    if '@' in destination and not destination.startswith('https://'):
        return 'mailto:' + quote(destination, safe='@.') + '?' + urlencode({
            'subject': 'Privacy request', 'body': draft,
        })
    return public_url(destination)


def resources(settings):
    catalog = yaml.safe_load((settings.catalog_dir / "quick-wins.yml").read_text())
    by_id = {guide.id: guide for guide in guides(settings)}
    by_domain = {domain: guide for guide in by_id.values() for domain in guide.match_domains}
    for item in catalog["items"]:
        # Curated selection, not automatic promotion of every discovered form.
        # Reuse the reviewed dossier so instructions cannot drift between pages.
        if guide_id := item.get("guide_id"):
            guide = by_id[guide_id]
            if (guide.review_status != "instructions_reviewed"
                    or guide.removal.method not in {"form", "manual", "email"}
                    or guide.automation.mode == "blocked"):
                raise ValueError(f"Quick win needs a reviewed manual action: {guide_id}")
            # Some official tools start at a footer or a shared suppression center.
            # Email-only steps use the published mailbox, without profile details.
            url = action_url(guide.removal.destination, item.get('email_draft', ''))
            item.update(
                name=guide.name,
                description=guide.removal.steps[0],
                url=url,
                link_label='Open email' if url.startswith('mailto:') else 'Open ↗',
                source=guide.evidence[0].url,
                checked_at=min(source.checked_on for source in guide.evidence).isoformat(),
                domains=guide.match_domains,
                scope=guide.coverage.includes + " " + guide.coverage.excludes,
                steps=guide.removal.steps,
                fields=guide.required_information.fields,
                verification=guide.required_information.verification,
                requirements_complete=guide.required_information.certainty == "documented",
                regions=guide.relevance.regions,
                fresh=guide.fresh,
            )
        # Older hand-written checklists share the same researched identity.
        guide = by_id.get(item.get("guide_id")) or next(
            (by_domain[d] for d in item.get("domains", []) if d in by_domain), None
        )
        if guide:
            item.update(guide_id=guide.id, category=guide.relevance.category,
                        effect=guide.coverage.effect, relevance=guide.relevance.note,
                        fresh=guide.fresh, reviewed=guide.review_status == "instructions_reviewed")
            item.setdefault("regions", guide.relevance.regions)
            item.setdefault("fields", guide.required_information.fields)
        item.setdefault("about", BROKER_DESCRIPTIONS.get(item.get("category"), ""))
        item.setdefault("checked_at", catalog["checked_at"])
        item["fresh"] = item.get("fresh", False) and 0 <= (
            datetime.now(UTC).date() - date.fromisoformat(str(item["checked_at"]))
        ).days <= 90
    return catalog


def checklist(settings, store):
    items = []
    for item in resources(settings)["items"]:
        checked = store.get_setting(f"quick_win:{item['id']}", "")
        cases = list(
            store.session.scalars(
                select(Case).join(Broker).where(Broker.domain.in_(item["domains"]))
            )
        )
        completed = bool(cases) and all(c.state in {"done", "removed", "not_found"} for c in cases)
        items.append(
            {
                **item,
                "done": bool(checked or completed),
                "checked": bool(checked),
                "completed": completed,
                "case_ids": [case.id for case in cases],
            }
        )
    return items


def mark_done(workflow, item):
    session, vault = workflow.session, workflow.store.vault
    key = f"quick_win:{item['id']}"
    saved = session.get(AppSetting, key)
    if saved and saved.value:
        return
    now = datetime.now(UTC)
    for broker in session.scalars(select(Broker).where(Broker.domain.in_(item["domains"]))):
        case = session.scalar(select(Case).where(Case.broker_id == broker.id))
        if case is None:
            case = Case(broker_id=broker.id)
            session.add(case)
            session.flush()
        # Keep already-established deletion/no-data outcomes and their rechecks.
        if case.state not in {"removed", "not_found"}:
            workflow.cancel_case_jobs(case.id)
            case.state = "done"
            case.completed_at = now
            case.submitted_at = case.submitted_at or now
            case.attempt_count = max(case.attempt_count or 0, 1)
            case.next_action_at = None
            case.last_error = ""
        workflow.close_obsolete_actions(case)
        session.add(
            Event(
                case_id=case.id,
                kind="user_completed",
                summary=f"Quick win completed: {item['name']} (user confirmed)",
                encrypted_payload=vault.encrypt({"resource": item["id"], "url": item["url"]}),
            )
        )
    if saved:
        saved.value = now.isoformat()
    else:
        session.add(AppSetting(key=key, value=now.isoformat()))
    session.commit()
