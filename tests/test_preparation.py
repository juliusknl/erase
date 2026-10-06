from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from erasure.config import Settings
from erasure.models import Approval, Broker, Case, Event, Job
from erasure.preparation import pipeline_status, prepare_backlog
from erasure.store import Store
from erasure.workflow import Workflow


def test_draft_replenishment_is_bounded_idempotent_and_never_sends(db, vault, monkeypatch):
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send",
        lambda *a: (_ for _ in ()).throw(AssertionError("Unexpected email")),
    )
    store = Store(db, vault)
    profile = store.save_profile(
        {
            "full_name": "Test Person",
            "email": "requests@example.test",
            "other_emails": ["work@example.test"],
            "postal_address": "DO NOT SHARE",
        },
        "Test Person",
    )
    profile.started_at = datetime.now(UTC)
    for i in range(13):
        db.add(
            Broker(
                slug=f"ready-{i}",
                name=f"Ready {i}",
                domain=f"broker{i}.test",
                contact=f"privacy@broker{i}.test",
                last_validated_at=datetime.now(UTC),
            )
        )
    db.add(
        Broker(
            slug="stale",
            name="Stale",
            domain="stale.test",
            contact="privacy@stale.test",
            last_validated_at=datetime.now(UTC) - timedelta(days=100),
        )
    )
    db.commit()
    workflow = Workflow(db, store, Settings(catalog_dir=Path(__file__).parents[1] / "catalog"))
    assert prepare_backlog(workflow) == 10
    assert prepare_backlog(workflow) == 0
    assert not list(db.scalars(select(Job)))
    for event in db.scalars(select(Event).where(Event.kind == "request_prepared")):
        draft = vault.decrypt(event.encrypted_payload)
        assert "DO NOT SHARE" not in draft["body"]
        assert "work@example.test" in draft["body"]
    case = db.scalar(select(Case))
    case.state = "done"
    db.commit()
    assert prepare_backlog(workflow) == 1
    assert case.state == "done"
    store.set_setting("paused", "true")
    assert prepare_backlog(workflow) == 0


def test_form_routes_do_not_send_and_orphan_actions_are_restored(db, vault, monkeypatch):
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send",
        lambda *a: (_ for _ in ()).throw(AssertionError("Unexpected email")),
    )
    broker = Broker(
        slug="azira",
        name="Azira",
        domain="azira.com",
        contact="privacy@azira.com",
        last_validated_at=datetime.now(UTC),
    )
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="prepared")
    db.add(case)
    db.commit()
    workflow = Workflow(
        db,
        Store(db, vault),
        Settings(catalog_dir=Path(__file__).parents[1] / "catalog", live_submissions=True),
    )
    workflow.submit_case(case.id)
    assert case.state == "needs_action"
    assert db.scalar(select(Approval)).kind == "next_step"
    db.scalar(select(Approval)).status = "superseded"
    db.commit()
    prepare_backlog(workflow)
    assert len(list(db.scalars(select(Approval).where(Approval.status == "pending")))) == 1
    prepare_backlog(workflow)
    assert len(list(db.scalars(select(Approval).where(Approval.status == "pending")))) == 1


def test_draft_status_distinguishes_checks_from_progress(db, vault, tmp_path):
    settings = Settings(catalog_dir=tmp_path)
    store = Store(db, vault)
    assert pipeline_status(db, store, settings)["label"] == "Setup needed"
    profile = store.save_profile({"full_name": "Test", "email": "p@example.test"}, "Test")
    profile.started_at = datetime.now(UTC)
    db.commit()
    assert pipeline_status(db, store, settings)["label"] == "Waiting for first draft check"
    store.set_setting("preparation_last_check", datetime.now(UTC).isoformat())
    assert pipeline_status(db, store, settings)["label"] == "No drafts ready"
    broker = Broker(
        slug="valid",
        name="Valid",
        contact="privacy@broker.test",
        last_validated_at=datetime.now(UTC),
    )
    db.add(broker)
    db.flush()
    db.add(Case(broker_id=broker.id, state="prepared"))
    db.commit()
    assert pipeline_status(db, store, settings)["label"] == "1 email draft ready"
    store.set_setting(
        "preparation_last_check", (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    )
    result = pipeline_status(db, store, settings)
    assert result["label"] == "Draft checks delayed" and result["stale"]
    store.set_setting("paused", "true")
    result = pipeline_status(db, store, settings)
    assert result["label"] == "Automation paused" and not result["stale"]
    store.set_setting("preparation_error", "Synthetic worker failure")
    assert pipeline_status(db, store, settings)["label"] == "Preparation needs attention"
