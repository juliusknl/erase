"""Executable, evidence-backed initial requests. Public guides remain the source of scope."""

import re
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Literal

import yaml
from pydantic import Field, model_validator

from erasure.connectors.base import RequestPlan
from erasure.knowledge import Evidence, StrictModel, guides

COUNTRIES = {
    "EEA": "EU/EEA — country not selected", "AT": "Austria", "BE": "Belgium",
    "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia",
    "DK": "Denmark", "EE": "Estonia", "FI": "Finland", "FR": "France",
    "DE": "Germany", "GR": "Greece", "HU": "Hungary", "IS": "Iceland",
    "IE": "Ireland", "IT": "Italy", "LV": "Latvia", "LI": "Liechtenstein",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands",
    "NO": "Norway", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SK": "Slovakia", "SI": "Slovenia", "ES": "Spain", "SE": "Sweden",
}


class EmailRoute(StrictModel):
    guide_id: str
    destination: str
    countries: list[str] = Field(min_length=1)
    fields: list[Literal["full_name", "email", "other_emails", "postal_address", "work_email", "employer"]]
    optional_fields: list[Literal['work_email']] = Field(default_factory=list)
    requires_matching_email: bool = False
    effect: Literal["deletion_request", "suppression"]
    subject: str = "Privacy request"
    request: str = Field(min_length=30)
    why: str = Field(min_length=20)
    follow_up: str = Field(min_length=20)
    evidence: list[Evidence] = Field(min_length=1)

    @model_validator(mode="after")
    def valid(self):
        if not {"full_name", "email"} <= set(self.fields):
            raise ValueError("Requests need a name and reply address")
        if len(set(self.fields + self.optional_fields)) != len(self.fields + self.optional_fields):
            raise ValueError("Duplicate disclosure field")
        if any(country not in COUNTRIES for country in self.countries):
            raise ValueError("Unsupported residence route")
        if "\n" in self.subject or "\r" in self.subject:
            raise ValueError("Invalid subject")
        return self

    @property
    def checked_on(self) -> date:
        return min(source.checked_on for source in self.evidence)

    @property
    def fresh(self):
        return 0 <= (datetime.now(UTC).date() - self.checked_on).days <= 90


class RouteFile(StrictModel):
    schema_version: Literal[1]
    routes: list[EmailRoute]


@lru_cache(maxsize=4)
def _read(path, modified):
    return RouteFile.model_validate(yaml.safe_load(path.read_text())).routes


def routes(settings):
    path = settings.catalog_dir / "email-routes.yml"
    if not path.exists():
        return {}
    by_id = {g.id: g for g in guides(settings)}
    result, ids = {}, set()
    for route in _read(path, path.stat().st_mtime_ns):
        guide = by_id.get(route.guide_id)
        if guide is None or route.guide_id in ids:
            raise ValueError("Unknown or duplicate email workflow guide")
        ids.add(route.guide_id)
        if guide.review_status != "instructions_reviewed" or guide.regional_routes:
            raise ValueError("Email workflow needs a reviewed, unambiguous controller")
        if route.destination not in [guide.removal.destination, *guide.removal.alternatives]:
            raise ValueError("Email destination is not documented in the guide")
        if "@" not in route.destination or any(c.isspace() for c in route.destination):
            raise ValueError("Invalid email destination")
        # The recipe's explicit request supplies the requested right, not an identity field.
        if not set(guide.required_information.fields) <= set(route.fields) | {"requested_right"}:
            raise ValueError("Email workflow omits a documented matching field")
        if guide.coverage.effect != route.effect:
            raise ValueError("Email workflow changes the documented request effect")
        if guide.relevance.category in {"credit_reference", "identity_risk"}:
            raise ValueError("Credit and identity records need a dedicated workflow")
        for domain in guide.match_domains:
            result[domain] = (route, guide)
    return result


def problem(route, guide, broker, profile, country, allow_postal):
    if not guide.fresh or not route.fresh:
        return "Request instructions need rechecking"
    if broker.contact.strip().lower() != route.destination.lower():
        return "Saved recipient differs from the reviewed email route"
    if country not in COUNTRIES:
        return "Choose your country of residence"
    if country not in route.countries and "EEA" not in route.countries:
        return "This request route is documented for " + ", ".join(
            COUNTRIES[c] for c in route.countries
        )
    if not profile.get("full_name") or not profile.get("email"):
        return "Complete your name and request email"
    if "postal_address" in route.fields:
        if not allow_postal:
            return "Needs permission to include your saved postal address"
        if not profile.get("postal_address", "").strip():
            return "Add your postal address in Identity"
    if "work_email" in route.fields and not re.fullmatch(
        r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", profile.get("work_email", "").strip()
    ):
        return "Add your work email in Identity for this professional database"
    if "employer" in route.fields and not profile.get("employer", "").strip():
        return "Add your current or most recent employer in Identity"
    matching_email = (
        "other_emails" in route.fields and profile.get("other_emails")
    ) or ("work_email" in route.fields + route.optional_fields and profile.get("work_email"))
    if route.requires_matching_email and not matching_email:
        return "Add an email used outside this app in Identity so the broker can match you"
    return ""


def prepare(route, guide, broker, profile, token, country, allow_postal):
    if reason := problem(route, guide, broker, profile, country, allow_postal):
        raise ValueError(reason)
    lines = [f"Full name: {profile['full_name']}"]
    disclosed = ["full_name", "email", "country"]
    for field, label in (("work_email", "Work email to match"),
                         ("employer", "Current or most recent employer")):
        if field in route.fields or (field in route.optional_fields and profile.get(field, '').strip()):
            lines.append(f"{label}: {profile[field].strip()}")
            disclosed.append(field)
    if "other_emails" in route.fields and profile.get("other_emails"):
        lines.append("Email identifiers to search (separate from my reply mailbox):")
        lines.extend(f"- {address}" for address in profile["other_emails"])
        disclosed.append("other_emails")
    if "postal_address" in route.fields:
        lines.append(f"Current postal address: {profile['postal_address']}")
        disclosed.append("postal_address")
    residence = "the European Economic Area" if country == "EEA" else COUNTRIES[country]
    body = f"""Hello {guide.name} Privacy Team,

{route.request}

I reside in {residence}. My reply address is {profile['email']}.

Information supplied to locate my existing records:
{chr(10).join(lines)}

Please search the supplied matching identifiers, not only my reply mailbox. Please tell me which identifiers and datasets you checked and whether a match was found. Confirm the action taken and explain any data you must retain. If further verification is necessary, please tell me the specific information required and a suitable way to provide it. Please use this information only to process this request.

Reference: {token}

Sincerely,
{profile.get('_signature') or profile['full_name']}
"""
    return RequestPlan(channel="email", destination=route.destination,
                       subject=f"{route.subject} [{token}]", body=body,
                       disclosed_fields=tuple(disclosed))
