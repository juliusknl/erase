from pathlib import Path
from urllib.parse import urlsplit

from erasure.broker_scale import load_scale, scale_progress
from erasure.config import Settings
from erasure.models import Broker, Case


def test_scale_preserves_outcome_evidence_and_excludes_unknown_brokers(db):
    scale = load_scale(Settings(catalog_dir=Path(__file__).parents[1] / "catalog"))
    states = ["removed", "done", "not_found", "processing"]
    for (domain, evidence), state in zip(scale.items(), states, strict=True):
        broker = Broker(slug=domain, domain=domain, name=evidence["name"])
        db.add(broker)
        db.flush()
        db.add(Case(broker_id=broker.id, state=state))
    unknown = Broker(slug="unknown", domain="unknown.test", name="Unknown size")
    db.add(unknown)
    db.flush()
    db.add(Case(broker_id=unknown.id, state="removed"))
    db.commit()
    items = scale_progress(db, scale)
    assert len(items) == 4
    assert sum(item["done"] for item in items) == 3
    assert [item["state"] for item in items] == states
    assert [item["outcome"] for item in items] == [
        "Broker reported deletion",
        "You marked this done",
        "Broker reported no match",
        "",
    ]
    assert all(item["case_id"] for item in items)
    for domain, evidence in scale.items():
        source = urlsplit(evidence["source"])
        assert source.scheme == "https"
        assert source.hostname in {domain, f"www.{domain}"}
        assert evidence["checked_at"] and evidence["source_note"]


def test_no_cases_is_not_progress_and_missing_scale_is_unknown(db, tmp_path):
    assert load_scale(Settings(catalog_dir=tmp_path)) == {}
    assert scale_progress(db, {}) == []
    scale = load_scale(Settings(catalog_dir=Path(__file__).parents[1] / "catalog"))
    items = scale_progress(db, scale)
    assert len(items) == 4
    assert all(not item["done"] and not item["case_id"] for item in items)
    assert all(item["state"] == "candidate" and not item["outcome"] for item in items)
