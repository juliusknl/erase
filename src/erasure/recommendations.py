"""Small, explainable action sessions. Never authorizes or sends a request."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from erasure import campaign
from erasure.attention import needs_person
from erasure.broker_scale import load_scale
from erasure.email_routes import COUNTRIES as EMAIL_COUNTRIES
from erasure.email_routes import routes
from erasure.major_brokers import priority_guides
from erasure.models import Approval, Case
from erasure.quick_wins import checklist

COUNTRIES = {k: v for k, v in EMAIL_COUNTRIES.items() if k != "EEA"} | {
    "GB": "United Kingdom",
    "CH": "Switzerland",
    "US": "United States",
    "CA": "Canada",
    "AU": "Australia",
    "NZ": "New Zealand",
}
EEA = set(EMAIL_COUNTRIES) - {"EEA"}
EU = EEA - {"IS", "LI", "NO"}
SESSION_KEY = "recommended_action_session"
CATEGORIES = {
    "people_search": (
        0,
        "Public people search",
        "Reduce details available through people-search sites.",
    ),
    "professional": (
        1,
        "Work contact details",
        "Reduce distribution of your professional contact details.",
    ),
    "recruitment": (
        1,
        "Recruitment profiles",
        "Limit use of your details in recruitment databases.",
    ),
    "consumer_marketing": (
        2,
        "Marketing lists",
        "Limit use or sharing of your details for marketing.",
    ),
    "postal_marketing": (2, "Postal marketing", "Reduce use of your details for advertising mail."),
    "advertising": (3, "Advertising profiles", "Limit use of your information for advertising."),
}
EFFECTS = {
    "deletion_request": "Request deletion",
    "suppression": "Stop specified marketing or sharing; some records may remain",
    "access_then_review": "Get a copy of your data first",
    "needs_review": "Review the scope before proceeding",
}


def country(store):
    return store.get_setting("recommendation_country", "") or campaign.consent(store).get(
        "country", ""
    )


def region_matches(regions, residence):
    """Exact positive scope only. 'EEA scope unconfirmed' must never match EEA."""
    tags = {r.strip().casefold() for r in regions}
    if not residence:
        return False
    accepted = {
        residence.casefold(),
        COUNTRIES.get(residence, residence).casefold(),
        "global",
        "worldwide request eligibility",
        "worldwide opt-out",
    }
    if residence in EEA or residence == "EEA":
        accepted |= {"eea", "european economic area"}
    if residence in EU:
        accepted |= {"eu", "european union"}
    if residence == "GB":
        accepted.add("uk")
    return bool(tags & accepted)


def preference(store, item_id, now=None):
    saved = store.get_setting(f"action_preference:{item_id}", {})
    if (
        saved.get("status") == "later"
        and saved.get("until", "") <= (now or datetime.now(UTC)).isoformat()
    ):
        return ""
    return saved.get("status", "")


def action_items(workflow):
    """Explain each manual resource without inventing personal exposure or risk scores."""
    residence = country(workflow.store)
    email_routes = routes(workflow.settings)
    major_guides = priority_guides(workflow.settings)
    scale = {
        domain: claim
        for domain, claim in load_scale(workflow.settings).items()
        if 0 <= (datetime.now(UTC).date() - date.fromisoformat(str(claim["checked_at"]))).days <= 90
    }
    saved = campaign.consent(workflow.store)
    cases = {c.id: c for c in workflow.session.scalars(select(Case))}
    rows = []
    for item in checklist(workflow.settings, workflow.store):
        category = item.get("category", "")
        if item["id"] == "ddv-robinson":
            category = "postal_marketing"
            fresh = (
                0
                <= (datetime.now(UTC).date() - date.fromisoformat(str(item["checked_at"]))).days
                <= 90
            )
            item = dict(item, regions=["DE"], fresh=fresh, reviewed=True, effect="suppression")
        priority, label, why = CATEGORIES.get(
            category,
            (9, "Specialist request", "Review this service's scope before making a request."),
        )
        linked = [cases[c] for c in item["case_ids"]]
        # Do not invite a second initial request while a broker is already responding.
        active = any(c.state in {"submitted", "processing", "queued"} for c in linked)
        needs_attention = any(c.state == "needs_action" for c in linked)
        email_possible = False
        email_approved = False
        for domain in item["domains"]:
            entry = email_routes.get(domain)
            if not entry:
                continue
            route, guide = entry
            email_possible |= (
                guide.fresh
                and route.fresh
                and (
                    residence in route.countries
                    or ((residence in EEA or residence == "EEA") and "EEA" in route.countries)
                )
            )
        if email_possible and saved.get("enabled"):
            email_approved = any(str(c.broker_id) in saved.get("plans", {}) for c in linked)
            # Approved workflows can exist before their first case is created.
            approved_domains = {
                v[0] for k, v in saved.get("scope", {}).items() if k in saved.get("plans", {}) and v
            }
            email_approved |= bool(set(item["domains"]) & approved_domains)
        deferred = preference(workflow.store, item["id"])
        region_ok = region_matches(item.get("regions", []), residence)
        eligible = (
            category in CATEGORIES
            and region_ok
            and item.get("fresh", False)
            and item.get("reviewed", False)
            and item.get("effect") in {"deletion_request", "suppression"}
        )
        rows.append(
            dict(
                item,
                category_label=label,
                why=why,
                outcome=EFFECTS.get(item.get("effect"), "Review the official instructions"),
                preference=deferred,
                region_ok=region_ok,
                recommended=eligible,
                email_possible=email_possible,
                email_approved=email_approved,
                already_running=active,
                selectable=eligible
                and not item["done"]
                and not deferred
                and not active
                and not email_possible
                and not needs_attention,
                priority=(
                    priority,
                    0 if item.get('guide_id') in major_guides else 1,
                    0 if any(d in scale for d in item["domains"]) else 1,
                    0 if item.get("requirements_complete") else 1,
                    len(item.get("fields", [])),
                    item["name"].casefold(),
                ),
            )
        )
    return sorted(rows, key=lambda r: r["priority"])


def session_items(workflow, items=None):
    items = action_items(workflow) if items is None else items
    saved = workflow.store.get_setting(SESSION_KEY, {})
    if saved.get("country") == country(workflow.store) and "ids" in saved:
        ids = saved["ids"]
        return [i for i in items if i["id"] in ids and i["selectable"]]
    return [i for i in items if i["selectable"]][:3]


def remember_session(workflow):
    """Freeze the current three before a tick/skip, so completion doesn't refill it."""
    saved = workflow.store.get_setting(SESSION_KEY, {})
    if saved.get("country") != country(workflow.store) or "ids" not in saved:
        workflow.store.set_setting(
            SESSION_KEY,
            {
                "country": country(workflow.store),
                "ids": [i["id"] for i in session_items(workflow)],
            },
            encrypted=True,
        )


def set_preference(workflow, item_id, choice):
    remember_session(workflow)
    value = {} if choice == "restore" else {"status": choice}
    if choice == "later":
        value["until"] = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    workflow.store.set_setting(f"action_preference:{item_id}", value, encrypted=True)


def attention_items(workflow):
    """One entry per request, with real outstanding decisions before optional forms."""
    cases = {c.id: c for c in workflow.session.scalars(select(Case))}
    items = {}
    approvals = workflow.session.scalars(
        select(Approval)
        .where(Approval.status == "pending")
        .order_by(Approval.created_at, Approval.id)
    )
    for a in approvals:
        payload = workflow.store.vault.decrypt(a.encrypted_payload) if a.encrypted_payload else {}
        if not needs_person(a, payload):
            continue
        case = cases.get(a.case_id)
        if case is None or case.state in {"done", "removed", "not_found"}:
            continue
        key = f"case:{a.case_id}" if case else f"approval:{a.id}"
        items.setdefault(
            key,
            dict(
                name=case.broker.name if case else "Request needs attention",
                reason={
                    "confirmation_link": "Confirm your request so the broker can continue.",
                    "form_required": "This broker needs you to complete its form.",
                    "information_requested": "Review the reply prepared with the requested details.",
                    "ambiguous_reply": "Read the broker’s instructions and respond.",
                    "unverified_sender": "Check who sent this reply before trusting its instructions.",
                    "identity_proof": "The broker is asking you to verify your identity.",
                    "delivery_uncertain": "Check whether this email was sent before trying again.",
                    "next_step": "Review the next step for this request.",
                }.get(a.kind, a.summary),
                case_id=case.id if case else None,
                url=f"/cases/{case.id}?step={a.id}#next-step" if case else '/campaign',
            ),
        )
    return list(items.values())
