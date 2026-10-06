"""Maintain a fixed priority checklist without turning catalog size into exposure."""

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import Field, model_validator

from erasure.knowledge import StrictModel


class Target(StrictModel):
    guide_id: str
    countries: list[str] = Field(min_length=1)


class Family(StrictModel):
    id: str
    name: str
    category: Literal["marketing", "people_search"]
    routes: list[Target] = Field(min_length=1)
    limit: str


class Checklist(StrictModel):
    schema_version: Literal[1]
    selection: str
    families: list[Family] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_families(self):
        if len({f.id for f in self.families}) != len(self.families):
            raise ValueError("Major-broker checklist repeats a family")
        for family in self.families:
            targets = [(r.guide_id, c) for r in family.routes for c in r.countries]
            if len(set(targets)) != len(targets):
                raise ValueError("Major-broker checklist repeats a country route")
        return self


@lru_cache(maxsize=4)
def _read(path, modified):
    return Checklist.model_validate(yaml.safe_load(path.read_text()))


def checklist(settings):
    path = settings.catalog_dir / "major-brokers.yml"
    return _read(path, path.stat().st_mtime_ns) if path.exists() else None


def priority_guides(settings):
    declared = checklist(settings)
    return {r.guide_id for f in declared.families for r in f.routes} if declared else set()


def coverage(settings):
    # Local imports keep presentation priority independent from the audit helpers.
    from erasure.email_routes import COUNTRIES, routes
    from erasure.knowledge import guides
    from erasure.quick_wins import resources
    from erasure.recommendations import EEA, region_matches

    declared = checklist(settings)
    if not declared:
        return {"declared": False, "all_routes_wired": False, "families": []}
    by_id = {g.id: g for g in guides(settings)}
    emails = {r.guide_id: r for r, _ in routes(settings).values()}
    manual = {w.get("guide_id"): w for w in resources(settings)["items"]}
    families = []
    for family in declared.families:
        checks = []
        for target in family.routes:
            guide = by_id.get(target.guide_id)
            email, action = emails.get(target.guide_id), manual.get(target.guide_id)
            for country in target.countries:
                mode, reason = None, ""
                if not guide:
                    reason = "No reviewed guide"
                elif (
                    guide.review_status != "instructions_reviewed"
                    or guide.automation.mode == "blocked"
                ):
                    reason = "Route still needs research"
                elif not guide.fresh:
                    reason = "Evidence needs rechecking"
                elif (
                    email
                    and email.fresh
                    and country in COUNTRIES
                    and (country in email.countries or country in EEA and "EEA" in email.countries)
                ):
                    mode = "automatic_email"
                elif (
                    action
                    and action.get("fresh")
                    and action.get("reviewed")
                    and region_matches(action.get("regions", []), country)
                    and guide.coverage.effect in {"deletion_request", "suppression"}
                ):
                    mode = "guided_manual"
                else:
                    reason = "No in-app removal action for this country"
                checks.append(
                    {"guide_id": target.guide_id, "country": country, "mode": mode, "gap": reason}
                )
        ready = sum(c["mode"] is not None for c in checks)
        status = "gap"
        if ready == len(checks):
            status = "routes_wired"
        elif ready:
            status = "partial"
        families.append(
            {
                "id": family.id,
                "name": family.name,
                "category": family.category,
                "status": status,
                "checks": checks,
                "limit": family.limit,
            }
        )
    return {
        "declared": True,
        "selection": declared.selection,
        "family_count": len(families),
        "families_with_any_route": sum(f["status"] != "gap" for f in families),
        "families_with_all_declared_routes": sum(f["status"] == "routes_wired" for f in families),
        "all_routes_wired": all(f["status"] == "routes_wired" for f in families),
        "families": families,
        "limit": "Checks reviewed routes are wired into the app for declared countries, not live form completion, market share, personal exposure or deletion success.",
    }
