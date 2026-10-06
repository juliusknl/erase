from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from erasure.catalog import load_curated
from erasure.config import Settings
from erasure.models import Approval, Broker, Case, Event, Job
from erasure.store import Store
from erasure.workflow import Workflow, case_token

ROOT = Path(__file__).parents[1]


def authenticated_sender(case: Case) -> dict[str, str]:
    domain = case.broker.domain
    return {
        "from": f"privacy@{domain}",
        "authentication_results": f"mx.google.com; dmarc=pass header.from={domain}",
    }


def test_campaign_schedules_only_risk_threshold_and_stays_dry(db, vault) -> None:  # type: ignore[no-untyped-def]
    # Generic delivery behavior must not depend on a real broker's changing policy.
    broker = Broker(
        slug="email-fixture",
        name="Email fixture",
        domain="email.example.test",
        contact="privacy@email.example.test",
        required_fields='{"default_confidence": 60}',
    )
    below_threshold = Broker(
        slug="below-threshold",
        name="Below threshold",
        domain="candidate.example.test",
        required_fields='{"default_confidence": 59}',
    )
    inactive = Broker(
        slug="inactive-fixture",
        name="Inactive fixture",
        domain="inactive.example.test",
        active=False,
        required_fields='{"default_confidence": 99}',
    )
    db.add_all([broker, below_threshold, inactive])
    db.commit()
    store = Store(db, vault)
    store.save_profile(
        {
            "full_name": "Test Person",
            "email": "privacy@example.test",
            "postal_address": "Test Street",
            "other_emails": ["existing@example.test"],
        },
        "Test Person",
    )
    settings = Settings(master_key="ignored", live_submissions=False)
    workflow = Workflow(db, store, settings)
    result = workflow.start_campaign()
    assert result == {"created": 2, "scheduled": 1}
    assert (
        db.scalar(select(func.count()).select_from(Job).where(Job.kind == "submit_case"))
        == 1
    )
    assert db.scalar(select(Case).where(Case.broker_id == below_threshold.id)).state == "candidate"
    assert db.scalar(select(Case).where(Case.broker_id == inactive.id)) is None

    case = db.scalar(select(Case).where(Case.broker_id == broker.id))
    assert case is not None
    workflow.submit_case(case.id)
    assert case.state == "prepared"
    assert "Live submissions are disabled" in case.last_error
    event = db.scalar(
        select(Event).where(Event.case_id == case.id, Event.kind == "request_prepared")
    )
    assert event is not None
    decrypted = vault.decrypt(event.encrypted_payload)
    assert decrypted["disclosed_fields"] == [
        "full_name",
        "email",
        "postal_address",
        "other_emails",
    ]
    assert "Contact email for this request: privacy@example.test" in decrypted["body"]
    assert "- existing@example.test" in decrypted["body"]


def test_browser_case_stages_action_while_email_live_mode_is_off(db, vault) -> None:  # type: ignore[no-untyped-def]
    # Exercise the generic browser connector independently of changing broker guides.
    broker = Broker(
        slug="browser-fixture",
        name="Browser fixture",
        domain="browser.example.test",
        connector_type="browser",
        contact="https://browser.example.test/privacy",
    )
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="queued")
    db.add(case)
    db.commit()
    store = Store(db, vault)
    store.save_profile({"full_name": "Test Person", "email": "privacy@example.test"}, "Test Person")
    workflow = Workflow(db, store, Settings(live_submissions=False))
    workflow.submit_case(case.id)

    assert case.state == "needs_action"
    assert case.attempt_count == 0
    assert (
        db.scalar(
            select(func.count()).select_from(Approval).where(Approval.kind == "browser_challenge")
        )
        == 1
    )


def test_duplicate_job_does_not_resubmit_completed_case(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    broker = db.scalar(select(Broker).limit(1))
    assert broker is not None
    case = Case(broker_id=broker.id, state="submitted")
    db.add(case)
    db.commit()

    Workflow(db, Store(db, vault), Settings(live_submissions=True)).submit_case(case.id)

    assert case.state == "submitted"
    assert case.attempt_count == 0


def test_live_email_job_fails_closed_when_contact_is_unvalidated(db, vault) -> None:  # type: ignore[no-untyped-def]
    broker = Broker(
        slug="unvalidated-email",
        name="Unvalidated email fixture",
        domain="unvalidated.example.test",
        contact="privacy@unvalidated.example.test",
    )
    db.add(broker)
    db.flush()
    store = Store(db, vault)
    store.save_profile(
        {
            "full_name": "Test Person",
            "email": "privacy@example.test",
            "postal_address": "Test Street",
        },
        "Signed",
    )
    case = Case(broker_id=broker.id, state="prepared")
    db.add(case)
    db.commit()

    Workflow(db, store, Settings(live_submissions=True)).submit_case(case.id)

    # No campaign permission: hold the draft before considering validation or
    # disclosing anything. Do not turn missing internal permission into a task.
    assert case.state == "prepared"
    assert case.last_error == "Automatic campaign is off"
    assert case.attempt_count == 0
    assert db.scalar(select(func.count()).select_from(Approval)) == 0


def test_completed_reply_schedules_recheck(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    store = Store(db, vault)
    store.save_profile({"full_name": "Test Person", "email": "privacy@example.test"}, "Signed")
    workflow = Workflow(db, store, Settings(live_submissions=False))
    workflow.start_campaign()
    case = db.scalar(select(Case).order_by(Case.id))
    assert case is not None
    case.state = "submitted"
    case.submitted_at = datetime.now(UTC)
    db.commit()

    matched = workflow.process_message(
        {
            "subject": f"Re: request [{case_token(case.id)}]",
            "body": "Your personal information has been removed.",
            "id": "gmail-id",
            "message_id": "message-id",
            **authenticated_sender(case),
        }
    )
    assert matched
    assert case.state == "removed"
    assert case.next_action_at is not None
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "recheck_case")) == 1


def test_identity_reply_creates_approval(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    store = Store(db, vault)
    store.save_profile({"full_name": "Test Person", "email": "privacy@example.test"}, "Signed")
    workflow = Workflow(db, store, Settings())
    workflow.start_campaign()
    case = db.scalar(select(Case).order_by(Case.id))
    assert case is not None
    assert workflow.process_message(
        {
            "subject": f"Verify {case_token(case.id)}",
            "body": "Please provide proof of identity.",
            "id": "id",
            "message_id": "mid",
            **authenticated_sender(case),
        }
    )
    assert case.state == "needs_action"
    assert workflow.dashboard_counts()["actions"] == 1
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "send_alert")) == 1


def test_reply_without_token_matches_gmail_thread(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    store = Store(db, vault)
    store.save_profile({"full_name": "Test", "email": "privacy@example.test"}, "Signed")
    workflow = Workflow(db, store, Settings())
    workflow.start_campaign()
    case = db.scalar(select(Case).order_by(Case.id))
    assert case is not None
    case.state = "submitted"
    case.external_reference = "gmail-thread:thread-123"
    db.commit()

    assert workflow.process_message(
        {
            "subject": "Your privacy request is complete",
            "body": "Your personal information has been removed.",
            "id": "id",
            "message_id": "mid",
            "thread_id": "thread-123",
            **authenticated_sender(case),
        }
    )
    assert case.state == "removed"


def test_bounce_stops_followups_and_creates_action(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    store = Store(db, vault)
    store.save_profile({"full_name": "Test", "email": "privacy@example.test"}, "Signed")
    workflow = Workflow(db, store, Settings())
    workflow.start_campaign()
    case = db.scalar(select(Case).order_by(Case.id))
    assert case is not None
    case.state = "submitted"
    db.commit()

    assert workflow.process_message(
        {
            "subject": f"Delivery Status Notification (Failure) {case_token(case.id)}",
            "body": "Address not found. Your message wasn't delivered.",
            "from": "mailer-daemon@googlemail.com",
            "authentication_results": "mx.google.com; dmarc=pass header.from=googlemail.com",
            "id": "id",
            "message_id": "mid",
            "thread_id": "bounce-thread",
        }
    )
    assert case.state == "delivery_failed"
    assert (
        db.scalar(
            select(func.count()).select_from(Approval).where(Approval.kind == "delivery_failure")
        )
        == 1
    )

    workflow.follow_up(case.id)
    assert case.state == "delivery_failed"


def test_unverified_sender_requires_approval_before_completion(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    store = Store(db, vault)
    store.save_profile({"full_name": "Test", "email": "privacy@example.test"}, "Signed")
    workflow = Workflow(db, store, Settings())
    workflow.start_campaign()
    case = db.scalar(select(Case).order_by(Case.id))
    assert case is not None
    case.state = "submitted"
    db.commit()

    assert workflow.process_message(
        {
            "subject": f"Re: request [{case_token(case.id)}]",
            "body": "Your personal information has been removed.",
            "from": "privacy@lookalike.test",
            "authentication_results": "mx.google.com; dmarc=pass header.from=lookalike.test",
            "id": "id",
            "message_id": "mid",
        }
    )

    assert case.state == "submitted"  # Unknown sender cannot complete OR invent a user task.
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "recheck_case")) == 0
    approval = db.scalar(
        select(Approval).where(Approval.kind == "unverified_sender", Approval.status == "pending")
    )
    assert approval is not None
    payload = vault.decrypt(approval.encrypted_payload)
    assert payload["proposed_kind"] == "completed"
    assert payload["previous_state"] == "submitted"


def test_unanswered_second_attempt_creates_complaint(db, vault) -> None:  # type: ignore[no-untyped-def]
    load_curated(db, ROOT / "catalog" / "curated.yml")
    store = Store(db, vault)
    store.save_profile({"full_name": "Test", "email": "privacy@example.test"}, "Test")
    workflow = Workflow(db, store, Settings())
    workflow.start_campaign()
    case = db.scalar(select(Case).order_by(Case.id))
    assert case is not None
    case.state = "processing"
    case.attempt_count = 2
    db.commit()
    workflow.follow_up(case.id)
    assert case.state == "escalation_ready"
    assert workflow.dashboard_counts()["actions"] == 1


def test_confirmation_url_is_broker_allowlisted() -> None:
    body = "Confirm at https://privacy.example.test/confirm?id=1"
    assert Workflow._safe_confirmation_url("example.test", body) == (
        "https://privacy.example.test/confirm?id=1"
    )
    assert (
        Workflow._safe_confirmation_url("example.test", "https://example.test.evil.test/collect")
        is None
    )


def test_unique_job_does_not_duplicate_pending_kind(db, vault) -> None:  # type: ignore[no-untyped-def]
    store = Store(db, vault)
    assert store.enqueue_if_missing("poll_gmail", {}) is not None
    assert store.enqueue_if_missing("poll_gmail", {}) is None
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "poll_gmail")) == 1
