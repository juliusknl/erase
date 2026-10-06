from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure.models import Broker

REGISTRY_2025_URL = "https://cppa.ca.gov/data_broker_registry/registry2025.csv"
REGISTRY_CURRENT_URL = "https://cppa.ca.gov/data_broker_registry/registry.csv"


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:150] or "unnamed-broker"


def domain_from_url(value: str) -> str:
    if not value:
        return ""
    candidate = value if "://" in value else f"https://{value}"
    return urlparse(candidate).netloc.lower().removeprefix("www.")


def _unique_slug(session: Session, base: str, domain: str) -> str:
    candidate = base
    counter = 2
    while session.scalar(select(Broker.id).where(Broker.slug == candidate)) is not None:
        existing = session.scalar(select(Broker).where(Broker.slug == candidate))
        if existing and domain and existing.domain == domain:
            return candidate
        candidate = f"{base[:145]}-{counter}"
        counter += 1
    return candidate


def upsert_broker(session: Session, data: dict[str, object]) -> Broker:
    name = str(data["name"]).strip()
    domain = str(data.get("domain", "")).strip().lower()
    existing = None
    if domain:
        existing = session.scalar(select(Broker).where(Broker.domain == domain))
    if existing is None:
        existing = session.scalar(select(Broker).where(Broker.name == name))
    if existing is None:
        existing = Broker(slug=_unique_slug(session, slugify(name), domain), name=name)
        session.add(existing)
    for field in (
        "domain",
        "category",
        "connector_type",
        "contact",
        "policy_url",
        "jurisdiction",
        "source",
        "cadence_days",
        "active",
    ):
        if field in data and data[field] not in (None, ""):
            setattr(existing, field, data[field])
    if "required_fields" in data:
        existing.required_fields = json.dumps(data["required_fields"])
    return existing


def load_curated(session: Session, path: Path) -> int:
    document = yaml.safe_load(path.read_text()) or {}
    count = 0
    for item in document.get("brokers", []):
        item = dict(item)
        item.setdefault("source", str(path))
        broker = upsert_broker(session, item)
        # Curated confidence is applied when cases are created, not persisted on the broker.
        broker.required_fields = json.dumps(
            {
                "fields": ["full_name", "email", "postal_address"],
                "default_confidence": int(item.get("confidence", 70)),
            }
        )
        count += 1
    session.commit()
    return count


def load_verified_email(session: Session, path: Path) -> None:
    document = yaml.safe_load(path.read_text())
    checked = datetime.fromisoformat(document["verified_at"])
    for item in document["brokers"]:
        existing = session.scalar(select(Broker).where(Broker.domain == item["domain"]))
        if (
            existing
            and existing.last_validated_at
            and existing.last_validated_at.replace(tzinfo=checked.tzinfo) > checked
        ):
            continue
        broker = upsert_broker(
            session,
            {
                **item,
                "connector_type": "browser" if item.get("preferred_form") else "email",
                "contact": item.get("preferred_form", item["contact"]),
                "source": item["policy_url"],
                "jurisdiction": "eea_or_voluntary",
                "required_fields": {
                    "fields": ["full_name", "email", "other_emails"],
                    "include_postal": False,
                    "default_confidence": 35,
                    "request_form": item.get("request_form", ""),
                },
            },
        )
        broker.last_validated_at = checked
    session.commit()


def _header_index(headers: list[str], *needles: str, exclude: tuple[str, ...] = ()) -> int:
    for index, header in enumerate(headers):
        normalized = " ".join(header.replace("\xa0", " ").lower().split())
        if all(needle in normalized for needle in needles) and not any(
            blocked in normalized for blocked in exclude
        ):
            return index
    raise ValueError(f"CPPA registry is missing expected column: {' / '.join(needles)}")


def import_cppa_registry(session: Session, path: Path) -> int:
    """Import either the historical two-header or current one-header CPPA export."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        first_row = next(rows, None)
        if first_row and first_row[0].strip().lower().startswith("data broker"):
            headers = first_row
        else:
            headers = next(rows, None)  # 2025 includes a grouping/visibility metadata row.
        if not headers or not headers[0].lower().startswith("data broker"):
            raise ValueError("Unrecognized CPPA registry format")
        name_index = _header_index(headers, "data broker", "name")
        website_index = _header_index(
            headers,
            "primary website",
            exclude=("contains details", "exercise", "rights"),
        )
        email_index = _header_index(headers, "primary contact email")
        try:
            policy_index = _header_index(headers, "primary website", "exercise")
        except ValueError:
            policy_index = _header_index(headers, "rights", "url")
        source_url = REGISTRY_CURRENT_URL if path.name == "registry2026.csv" else REGISTRY_2025_URL
        count = 0
        for row in rows:
            if not row or not row[name_index].strip():
                continue
            row += [""] * (len(headers) - len(row))
            name = row[name_index].strip()
            website = row[website_index].strip()
            email = row[email_index].strip()
            policy_url = row[policy_index].strip()
            upsert_broker(
                session,
                {
                    "name": name,
                    "domain": domain_from_url(website),
                    "category": "private_database",
                    "connector_type": "email" if email else "browser",
                    "contact": email or policy_url or website,
                    "policy_url": policy_url,
                    "jurisdiction": "general_opt_out",
                    "required_fields": {
                        "fields": ["full_name", "email", "postal_address"],
                        "default_confidence": 35,
                    },
                    "cadence_days": 90,
                    "active": True,
                    "source": source_url,
                },
            )
            count += 1
        session.commit()
        return count
