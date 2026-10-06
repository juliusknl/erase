"""Reproducible checks for a declared pilot scope, separate from market completeness."""

from datetime import UTC, date, datetime
from typing import Literal

import yaml

from erasure.email_routes import routes
from erasure.inventory import coverage_audit
from erasure.knowledge import StrictModel, guides, public_url
from erasure.quick_wins import action_url, resources


class GuidedForm(StrictModel):
    guide_id: str
    quick_win: str


class Frontier(StrictModel):
    area: str
    examples: list[str]
    reason: str
    remaining: str


class PilotScope(StrictModel):
    schema_version: Literal[1]
    email_guides: list[str]
    guided_forms: list[GuidedForm]
    priority_frontiers: list[Frontier]


def readiness(settings):
    path = settings.catalog_dir / "mvp-cohort.yml"
    if not path.exists():
        return {"declared": False, "initial_routes_ready": False, "problems": ["No pilot scope"]}
    scope = PilotScope.model_validate(yaml.safe_load(path.read_text()))
    by_id = {g.id: g for g in guides(settings)}
    executable = {r.guide_id: r for r, _ in routes(settings).values()}
    wins = resources(settings)
    by_win = {w["id"]: w for w in wins["items"]}
    problems = []
    form_ids = [r.guide_id for r in scope.guided_forms]
    win_ids = [r.quick_win for r in scope.guided_forms]
    ids = set(scope.email_guides) | set(form_ids)
    # A broker may publish both routes. Reject duplicates within each route list,
    # not a documented alternative; count the underlying guide only once.
    if not ids or any(len(values) != len(set(values))
                      for values in (scope.email_guides, form_ids, win_ids)):
        problems.append("Pilot scope is empty or repeats a route")
    for guide_id in ids:
        guide = by_id.get(guide_id)
        if not guide or guide.review_status != "instructions_reviewed" or not guide.fresh:
            problems.append(f"Unreviewed, missing or stale guide: {guide_id}")
    for guide_id in scope.email_guides:
        route = executable.get(guide_id)
        if not route or not route.fresh:
            problems.append(f"Missing or stale email workflow: {guide_id}")
    for item in scope.guided_forms:
        guide, win = by_id.get(item.guide_id), by_win.get(item.quick_win)
        if not guide or not win:
            problems.append(f"Missing guided form: {item.quick_win}")
            continue
        expected_email_url = action_url(guide.removal.destination, win.get('email_draft', ''))
        if not win['url'].startswith('mailto:'):
            public_url(win['url'])
        public_url(win["source"])
        if win["url"] not in [guide.removal.destination, *guide.removal.alternatives, expected_email_url]:
            problems.append(f"Form differs from reviewed guide: {item.quick_win}")
        if not set(win["domains"]) <= set(guide.match_domains) or not win["domains"]:
            problems.append(f"Form claims unsupported broker coverage: {item.quick_win}")
        checked = date.fromisoformat(str(win.get("checked_at", wins["checked_at"])))
        if not 0 <= (datetime.now(UTC).date() - checked).days <= 90:
            problems.append(f"Stale guided form: {item.quick_win}")
    return {
        "declared": True, "initial_routes_ready": not problems,
        "email_workflows": len(scope.email_guides), "guided_forms": len(scope.guided_forms),
        "distinct_guides": len(ids),
        "problems": problems,
        "priority_frontiers": [f.model_dump() for f in scope.priority_frontiers],
        "limit": "Checks initial public routes and references; does not prove live completion, personal exposure or exhaustive coverage.",
    }


def mvp_readiness(settings):
    """Whole-foundation gate; a green small pilot cannot stand in for coverage."""
    records = guides(settings)
    inventory = coverage_audit(settings.catalog_dir, records)
    pilot = readiness(settings)
    executable = {route.guide_id for route, _ in routes(settings).values()}
    # Minimal-email is an explicit reviewed automation decision, not an inference
    # from finding an inbox. All such decisions must have a working recipe.
    missing_email_workflows = sorted(
        guide.id for guide in records
        if guide.automation.mode == "email_minimal" and guide.id not in executable
    )
    problems = []
    if inventory["pending_assessment"]:
        problems.append(f"{len(inventory['pending_assessment'])} inventory records lack an assessment")
    if inventory["unresolved_assessments"]:
        problems.append(f"{len(inventory['unresolved_assessments'])} inventory assessments remain unresolved")
    if inventory["unresolved_guides"]:
        problems.append(f"{len(inventory['unresolved_guides'])} broker guides still need research")
    if inventory["stale_guides"] or inventory["integrity_problems"]:
        problems.append("Inventory has stale evidence or integrity errors")
    if not inventory["inventory_records"]:
        problems.append("No declared inventory")
    if not pilot["initial_routes_ready"]:
        problems.extend(pilot["problems"])
    if missing_email_workflows:
        problems.append("Reviewed automatic email decisions lack executable workflows")
    return {
        "ready": not problems,
        "inventory_records": inventory["inventory_records"],
        "assessed_records": inventory["assessed_records"],
        "pending_assessment": len(inventory["pending_assessment"]),
        "unresolved_assessments": len(inventory["unresolved_assessments"]),
        "unresolved_guides": len(inventory["unresolved_guides"]),
        "missing_email_workflows": missing_email_workflows,
        "problems": problems,
        "limit": "Coverage and implementation gate, not measured personal exposure, live fulfilment or complete market coverage.",
    }
