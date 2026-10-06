from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from erasure.config import Settings
from erasure.inbox import capture_message
from erasure.models import Approval, Broker, Case, Job
from erasure.replies import classify_reply
from erasure.reply_drafts import prepare_reply
from erasure.store import Store
from erasure.workflow import Workflow, case_token


@pytest.mark.parametrize("body", [
    "We found no matching records. Please provide your business email address or LinkedIn profile URL.",
    "We are unable to locate your profile. Please send your RocketReach URL.",
    "We received your request. We need your Mobile Advertising ID to locate your data.",
    "Please provide your country and city of residence so we can process the request.",
])
def test_requested_identifiers_are_not_completion_or_generic_receipts(body):
    assert classify_reply("Your privacy request", body).kind == "information_requested"


def test_no_match_with_more_identifiers_pauses_followups_and_prepares_reply(db, vault, monkeypatch):
    broker = Broker(slug="info-fixture", name="Info fixture", domain="broker.example.test",
                    contact="privacy@broker.example.test")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="submitted", submitted_at=datetime.now(UTC))
    db.add(case)
    db.commit()
    store = Store(db, vault)
    store.save_profile({"full_name": "Synthetic", "work_email": "work@example.test",
                        "postal_address": "DO NOT DISCLOSE"}, "Synthetic")
    workflow = Workflow(db, store, Settings(live_submissions=True))
    job = store.enqueue("follow_up", {"case_id": case.id})
    body = "No matching records. Please provide your business email address."
    capture_message(workflow, {"id": "info", "subject": case_token(case.id), "body": body,
        "from": broker.contact, "authentication_results": "mx.google.com; dmarc=pass header.from=broker.example.test"})
    assert case.state == "needs_action"
    assert case.completed_at is None and case.next_action_at is None
    assert job.status == "cancelled"
    action = db.scalar(select(Approval).where(Approval.status == "pending"))
    assert action.kind == "information_requested"
    draft = prepare_reply(body, store.get_profile())
    assert "work@example.test" in draft["body"] and "DO NOT DISCLOSE" not in draft["body"]
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send", lambda _, plan: sent.append(plan) or "gmail-thread:reply")
    workflow.send_reply(case.id, broker.contact, draft["body"])
    assert len(sent) == 1 and action.status == "approved"
    assert case.state == "processing" and case.completed_at is None
    assert db.scalar(select(Job).where(Job.kind == "follow_up", Job.status == "pending"))


def test_quoted_or_footer_field_mentions_do_not_create_identifier_request():
    assert classify_reply("Reply", "No matching records.\nOn Monday you wrote:\n"
                          "Please provide your phone number.").kind == "not_found"
    assert prepare_reply("Your data has been deleted. Our policy explains use of mobile advertising IDs.", {}) == {}


def test_identity_documents_keep_the_dedicated_review_boundary():
    assert classify_reply("Reply", "No matching records. Please provide proof of identity "
                          "and your email address.").kind == "identity_requested"
