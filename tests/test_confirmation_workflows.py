"""Reply-to-job transitions use synthetic mail and never contact a real broker."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from erasure.config import Settings
from erasure.inbox import capture_message
from erasure.models import Approval, Broker, Case, Event, Job
from erasure.store import Store
from erasure.workflow import Workflow, case_token


@pytest.fixture
def request_workflow(db, vault):
    broker = Broker(slug="confirmation-fixture", name="Confirmation fixture",
                    domain="broker.example.test", contact="privacy@broker.example.test")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="submitted", submitted_at=datetime.now(UTC))
    db.add(case)
    db.commit()
    workflow = Workflow(db, Store(db, vault), Settings(live_submissions=False))
    return workflow, case


def receive(workflow, case, body, message_id="synthetic-reply"):
    capture_message(workflow, {
        "id": message_id, "subject": f"Your request [{case_token(case.id)}]",
        "body": body, "from": case.broker.contact,
        "authentication_results": "mx.google.com; dmarc=pass header.from=broker.example.test",
    })


@pytest.mark.parametrize("body", [
    "We have received your request. Our privacy policy: https://broker.example.test/privacy",
    "We confirm that we received your request. No action is required.",
])
def test_receipt_never_visits_footer_links_or_creates_confirmation_task(request_workflow, body):
    workflow, case = request_workflow
    receive(workflow, case, body)
    assert case.state == "processing"
    assert not list(workflow.session.scalars(select(Job).where(Job.kind == "follow_confirmation")))
    assert not list(workflow.session.scalars(select(Approval).where(Approval.status == "pending")))


def test_email_verification_is_a_real_user_step_not_assumed_processing(request_workflow):
    workflow, case = request_workflow
    receive(workflow, case, "We received your request. Please confirm your email using "
            "https://broker.example.test/confirm?token=synthetic")
    assert case.state == "needs_action"
    assert case.next_action_at is None
    assert not list(workflow.session.scalars(select(Job).where(Job.kind == "follow_confirmation")))
    approval = workflow.session.scalar(select(Approval).where(Approval.status == "pending"))
    assert approval.kind == "confirmation_link"
    assert workflow.store.vault.decrypt(approval.encrypted_payload)["action_url"] == (
        "https://broker.example.test/confirm?token=synthetic"
    )


def test_receipt_does_not_override_an_unresolved_form_or_reset_its_wait(request_workflow):
    workflow, case = request_workflow
    receive(workflow, case, "Please use our Privacy Request Center.", "form")
    assert case.state == "needs_action"
    receive(workflow, case, "We received your request.", "receipt")
    assert case.state == "needs_action"
    assert case.next_action_at is None
    assert not list(workflow.session.scalars(select(Job).where(
        Job.kind == "follow_up", Job.status == "pending")))


def test_repeat_receipts_do_not_push_the_follow_up_further_away(request_workflow):
    workflow, case = request_workflow
    deadline = datetime.now(UTC) + timedelta(days=2)
    case.next_action_at = deadline
    followup = workflow.store.enqueue("follow_up", {"case_id": case.id}, run_at=deadline)
    receive(workflow, case, "We received your request.")
    assert case.next_action_at == deadline
    assert followup.status == "pending"


def test_reissued_verification_keeps_one_task_and_replaces_the_old_link(request_workflow):
    workflow, case = request_workflow
    for token in ("first", "second"):
        receive(workflow, case, "Please confirm your email at "
                f"https://broker.example.test/confirm?token={token}", token)
    actions = list(workflow.session.scalars(select(Approval).where(Approval.status == "pending")))
    assert len(actions) == 1
    assert workflow.store.vault.decrypt(actions[0].encrypted_payload)["action_url"].endswith("=second")
    assert case.state == "needs_action"


@pytest.mark.parametrize("body", [
    "Please confirm your email. https://broker.example.test/privacy-policy",
    "Please confirm your email. https://broker.example.test@attacker.test/confirm",
    "Please confirm your email. https://broker.example.test/confirm?a=1 "
    "https://broker.example.test/confirm?a=2",
    "Please confirm your email.\nOn Monday we wrote:\nhttps://broker.example.test/confirm?old=1",
])
def test_ambiguous_or_quoted_links_are_not_selected(body):
    assert Workflow._safe_confirmation_url("broker.example.test", body) is None


def test_confirmation_link_selection_skips_policy_footer_and_keeps_token():
    assert Workflow._safe_confirmation_url("broker.example.test",
        "Privacy: https://broker.example.test/privacy\n"
        "Confirm your email: https://broker.example.test/confirm?token=synthetic&request=1") == (
            "https://broker.example.test/confirm?token=synthetic&request=1")


@pytest.mark.parametrize("state", ["submitted", "removed", "not_found", "done"])
def test_legacy_confirmation_job_does_not_fetch_or_claim_success(request_workflow, monkeypatch, state):
    from erasure.worker import handle_job

    workflow, case = request_workflow
    case.state = state
    workflow.session.commit()

    def no_http(*args, **kwargs):
        pytest.fail("Generic confirmation jobs must not open unreviewed links")

    monkeypatch.setattr("httpx.Client.get", no_http)
    payload = {"case_id": case.id, "url": "https://broker.example.test/confirm?token=synthetic",
               "domain": case.broker.domain}
    handle_job("follow_confirmation", payload, workflow, workflow.store)
    handle_job("follow_confirmation", payload, workflow, workflow.store)
    assert not list(workflow.session.scalars(select(Event).where(Event.kind == "confirmation_followed")))
    if state == "submitted":
        assert case.state == "needs_action"
        assert len(list(workflow.session.scalars(select(Approval).where(Approval.status == "pending")))) == 1
    else:
        assert case.state == state
