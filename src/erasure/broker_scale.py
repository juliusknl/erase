"""Sourced database context. Never a personal-exposure score or an automation input."""

import yaml
from sqlalchemy import select

from erasure.models import Broker, Case


def load_scale(settings):
    path = settings.catalog_dir / "broker-scale.yml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def scale_progress(session, scale):
    cases = {
        domain: case
        for domain, case in session.execute(
            select(Broker.domain, Case).join(Case).where(Broker.domain.in_(scale))
        )
    }
    items = []
    for domain, evidence in scale.items():
        case = cases.get(domain)
        state = case.state if case else "candidate"
        items.append(
            {
                **evidence,
                "domain": domain,
                "case_id": case.id if case else None,
                "state": state,
                "done": state in {"done", "removed", "not_found"},
                "outcome": {
                    "removed": "Broker reported deletion",
                    "not_found": "Broker reported no match",
                    "done": "You marked this done",
                }.get(state, ""),
            }
        )
    return items
