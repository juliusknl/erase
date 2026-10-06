from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from erasure.models import Broker, Case
from erasure.store import Store


def test_sensitive_values_are_encrypted_and_jobs_are_durable(db, vault) -> None:  # type: ignore[no-untyped-def]
    store = Store(db, vault)
    store.save_profile({"full_name": "Very Secret Name", "email": "secret@example.test"}, "Signed")
    raw = db.execute(text("select encrypted_data from profiles")).scalar_one()
    assert "Very Secret Name" not in raw
    assert store.get_profile()["full_name"] == "Very Secret Name"

    job = store.enqueue("test", {"secret": "payload"}, run_at=datetime.now(UTC))
    claimed, payload = store.claim_job()  # type: ignore[misc]
    assert claimed.id == job.id
    assert payload == {"secret": "payload"}
    store.finish_job(claimed)
    assert claimed.status == "done"


def test_events_encrypt_payload(db, vault) -> None:  # type: ignore[no-untyped-def]
    broker = Broker(slug="test", name="Test")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id)
    db.add(case)
    db.commit()
    event = Store(db, vault).add_event(case.id, "reply", "Reply stored", {"body": "private"})
    assert "private" not in (event.encrypted_payload or "")
