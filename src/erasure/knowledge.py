"""Reviewed public broker knowledge. Never imports personal outcomes or grants consent."""

from __future__ import annotations

import csv
import re
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from erasure.models import Broker


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def public_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("Public evidence and routes must use HTTPS without credentials")
    return value


class Evidence(StrictModel):
    url: str
    checked_on: date
    published: str = "Not specified"
    excerpt: str
    supports: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source(self):
        public_url(self.url)
        if self.checked_on > datetime.now(UTC).date():
            raise ValueError("Evidence cannot be checked in the future")
        if not self.excerpt or len(self.excerpt.split()) > 25:
            raise ValueError("Use a short supporting excerpt, at most 25 words")
        return self


class Identity(StrictModel):
    legal_name: str
    brands: list[str]
    parent: str | None
    official_domains: list[str] = Field(min_length=1)


class Relevance(StrictModel):
    regions: list[str] = Field(min_length=1)
    category: Literal[
        "professional", "postal_marketing", "advertising", "credit_reference",
        "people_search", "consumer_marketing", "identity_risk", "recruitment",
        "aggregate_business", "other",
    ]
    data_categories: list[str] = Field(min_length=1)
    note: str


class Removal(StrictModel):
    method: Literal["email", "form", "manual", "investigate"]
    destination: str
    alternatives: list[str]
    steps: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_destination(self):
        for value in [self.destination, *self.alternatives]:
            if not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", value):
                public_url(value)
        if self.method == "email" and "@" not in self.destination:
            raise ValueError("Email route requires an email destination")
        return self


class RequiredInformation(StrictModel):
    fields: list[str]
    certainty: Literal["documented", "not_fully_specified"]
    verification: str


class Coverage(StrictModel):
    effect: Literal["deletion_request", "suppression", "access_then_review", "needs_review"]
    includes: str
    excludes: str


class Automation(StrictModel):
    mode: Literal["email_minimal", "manual", "blocked"]
    reason: str


class Scale(StrictModel):
    claim: str
    unit: str
    scope: str
    source: Evidence


class RegionalRoute(StrictModel):
    regions: list[str] = Field(min_length=1)
    legal_entity: str
    removal: Removal
    required_information: RequiredInformation
    coverage: Coverage
    automation: Automation
    evidence: list[Evidence] = Field(min_length=1)
    unknowns: list[str]

    @model_validator(mode="after")
    def requires_region_selection(self):
        if self.automation.mode == "email_minimal":
            raise ValueError("Regional routes require manual region selection before automation")
        return self


class BrokerGuide(StrictModel):
    id: str
    name: str
    # Exact, explicitly reviewed catalog associations; never suffix/parent matching.
    match_domains: list[str] = Field(min_length=1)
    identity: Identity
    relevance: Relevance
    removal: Removal
    required_information: RequiredInformation
    coverage: Coverage
    automation: Automation
    evidence: list[Evidence] = Field(min_length=1)
    scale: Scale | None
    review_status: Literal["instructions_reviewed", "needs_research"]
    tested_outcome: Literal["not_tested"]
    unknowns: list[str]
    regional_routes: list[RegionalRoute] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_automation(self):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.id):
            raise ValueError("Guide requires a stable slug")
        for domain in [*self.match_domains, *self.identity.official_domains]:
            if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
                raise ValueError("Expected a lowercase domain, not a URL")
        if self.regional_routes and self.automation.mode == "email_minimal":
            raise ValueError("Multi-region controller routing requires manual region selection")
        if self.automation.mode == "email_minimal":
            if (
                self.review_status != "instructions_reviewed"
                or self.removal.method != "email"
                or self.coverage.effect != "deletion_request"
                or self.relevance.category in {"credit_reference", "identity_risk"}
                or not set(self.required_information.fields)
                <= {"full_name", "email", "other_emails"}
            ):
                raise ValueError("Minimal email automation requires reviewed matching instructions")
        return self

    @property
    def checked_on(self):
        sources = [*self.evidence, *(source for route in self.regional_routes for source in route.evidence)]
        return min(source.checked_on for source in sources)

    @property
    def fresh(self):
        return 0 <= (datetime.now(UTC).date() - self.checked_on).days <= 90


class KnowledgeCatalog(StrictModel):
    schema_version: Literal[1]
    brokers: list[BrokerGuide]

    @model_validator(mode="after")
    def unique_records(self):
        ids, domains = set(), set()
        for guide in self.brokers:
            if guide.id in ids or domains.intersection(guide.match_domains):
                raise ValueError("Duplicate guide identity or ambiguous domain association")
            ids.add(guide.id)
            domains.update(guide.match_domains)
        return self


@lru_cache(maxsize=4)
def _read_catalog(files: tuple[tuple[str, int, int], ...]):
    # Cache whole validated snapshots, not a fixed number of individual files.
    # A catalog larger than a per-file LRU otherwise evicts itself on every read.
    records = []
    for path, _modified, _size in files:
        document = yaml.safe_load(Path(path).read_text())
        records.extend(KnowledgeCatalog.model_validate(document).brokers)
    return tuple(KnowledgeCatalog(schema_version=1, brokers=records).brokers)


def guides(settings):
    paths = [settings.catalog_dir / "broker-knowledge.yml"]
    paths.extend(sorted((settings.catalog_dir / "research").glob("*.yml")))
    files = []
    for path in paths:
        if path.exists():
            stat = path.stat()
            files.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    # Validate across files as well: a regional record must never silently replace
    # a different entity just because it shares a multinational website.
    return list(_read_catalog(tuple(files)))


def guide_index(settings):
    return {domain: guide for guide in guides(settings) for domain in guide.match_domains}


def reviewed_form(settings, domain):
    """Use the exact reviewed public destination, including third-party portals."""
    guide = guide_index(settings).get(domain)
    if (guide and guide.fresh and guide.review_status == 'instructions_reviewed'
            and guide.removal.method == 'form'):
        return guide.removal.destination
    return ''


def email_blocker(guide, destination):
    if not guide.fresh:
        return "Broker instructions need rechecking"
    if guide.automation.mode != "email_minimal":
        return guide.automation.reason
    if destination.strip().lower() != guide.removal.destination.lower():
        return "Catalog contact differs from the reviewed route; review the destination first"
    return ""


def install_missing(session, settings):
    """Add missing discoveries only. No validation, case creation, or contact replacement."""
    existing = set(session.scalars(select(Broker.domain)))
    added = 0
    for guide in guides(settings):
        if existing.intersection(guide.match_domains):
            continue
        slug = f"guide-{guide.id}"
        if session.scalar(select(Broker.id).where(Broker.slug == slug)):
            continue
        session.add(
            Broker(
                slug=slug,
                name=guide.name,
                domain=guide.match_domains[0],
                category=guide.relevance.category,
                connector_type="email" if guide.removal.method == "email" else "browser",
                contact=guide.removal.destination,
                policy_url=guide.evidence[0].url,
                source=guide.evidence[0].url,
                jurisdiction="region_review_required",
                active=True,
            )
        )
        existing.add(guide.match_domains[0])
        added += 1
    session.commit()
    return added


@lru_cache(maxsize=4)
def _registry_context(path: str, modified: int):
    from erasure.catalog import domain_from_url

    result = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {" ".join(k.split()).rstrip(":"): v for k, v in raw.items() if k}
            domain = domain_from_url(row.get("Data broker primary website", ""))
            if not domain:
                continue
            disclosures = [
                {"label": key.removeprefix("Data broker "), "value": value}
                for key, value in row.items()
                if value.strip() and key.startswith(("Data broker collects", "Data broker shared"))
            ]
            result.setdefault(domain, []).append(
                {"name": row.get("Data broker name", ""), "disclosures": disclosures}
            )
    return result


def registry_context(settings):
    path = settings.catalog_dir / "registry2026.csv"
    return _registry_context(str(path.resolve()), path.stat().st_mtime_ns) if path.exists() else {}
