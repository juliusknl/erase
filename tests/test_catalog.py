from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from erasure.catalog import import_cppa_registry, load_curated
from erasure.models import Broker

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]


def test_import_cppa_registry(db) -> None:  # type: ignore[no-untyped-def]
    assert import_cppa_registry(db, FIXTURES / "registry.csv") == 2
    assert db.scalar(select(func.count()).select_from(Broker)) == 2
    example = db.scalar(select(Broker).where(Broker.domain == "example-data.test"))
    assert example is not None
    assert example.contact == "privacy@example-data.test"
    assert example.jurisdiction == "general_opt_out"


def test_curated_data_overrides_registry(db) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    assert db.scalar(select(func.count()).select_from(Broker)) >= 10
    whitepages = db.scalar(select(Broker).where(Broker.domain == "whitepages.com"))
    assert whitepages is not None
    assert whitepages.cadence_days == 60


def test_import_current_one_header_registry(db) -> None:  # type: ignore[no-untyped-def]
    assert import_cppa_registry(db, FIXTURES / "registry2026.csv") == 1
    broker = db.scalar(select(Broker))
    assert broker is not None
    assert broker.name == "Current Data LLC"
    assert broker.contact == "privacy@current.test"
    assert broker.policy_url == "https://current.test/privacy-request"
    assert broker.source.endswith("/registry.csv")
