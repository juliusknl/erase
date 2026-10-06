from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from erasure.config import Settings
from erasure.inbox import capture_message, poll_mailbox, review_message
from erasure.models import Broker, Case, Event, IncomingMessage, Job
from erasure.store import Store
from erasure.workflow import Workflow


@pytest.mark.parametrize('body', ['', 'An unfamiliar sentence.', 'We received your request.', 'Your ticket has been resolved.'])
def test_uncertainty_and_routine_updates_do_not_pause_request(db, vault, body):
    from erasure import recommendations
    case, workflow = make_case(db, vault)
    capture_message(workflow, {'id': 'quiet', 'subject': f'ER-{case.id:06X}', 'body': body,
                              'from': 'privacy@sample.test', 'authentication_results': ''})
    assert case.state == 'submitted'
    assert recommendations.attention_items(workflow) == []
    assert db.get(IncomingMessage, 'quiet') is not None


def test_missing_body_retries_are_bounded_and_can_recover(db, vault):
    case, workflow = make_case(db, vault)
    capture_message(workflow, {'id': 'empty', 'subject': f'ER-{case.id:06X}', 'body': '', 'from': 'privacy@sample.test'})
    class Mailbox:
        calls = 0
        def list_recent(self):
            return []
        def read_message(self, mid):
            self.calls += 1
            return {'id': mid, 'subject': f'ER-{case.id:06X}', 'body': 'We received your request.',
                    'from': 'privacy@sample.test', 'authentication_results': 'mx.google.com; dmarc=pass header.from=sample.test'}
    mailbox = Mailbox()
    poll_mailbox(workflow, mailbox)
    poll_mailbox(workflow, mailbox)
    assert mailbox.calls == 1
    assert vault.decrypt(db.get(IncomingMessage, 'empty').encrypted_payload)['body']
    assert case.state == 'processing'


def test_missing_body_stops_after_three_attempts_and_auth_errors_do_not_use_budget(db, vault):
    from erasure.gmail import GmailError
    from erasure.inbox import recover_missing_bodies
    _, workflow = make_case(db, vault)
    db.add(IncomingMessage(id='empty', encrypted_payload=vault.encrypt({'id': 'empty', 'body': ''})))
    db.commit()
    class Mailbox:
        calls = 0
        fails = True
        def read_message(self, mid):
            self.calls += 1
            if self.fails:
                raise GmailError('Reconnect')
            return {'id': mid, 'body': ''}
    mailbox = Mailbox()
    with pytest.raises(GmailError):
        recover_missing_bodies(workflow, mailbox)
    assert workflow.store.get_setting('mail_recovery:empty').get('attempts', 0) == 0
    mailbox.fails = False
    for expected in range(1, 4):
        saved = workflow.store.get_setting('mail_recovery:empty', {})
        saved['next_try'] = ''
        workflow.store.set_setting('mail_recovery:empty', saved, encrypted=True)
        recover_missing_bodies(workflow, mailbox)
        assert workflow.store.get_setting('mail_recovery:empty')['attempts'] == expected
    recover_missing_bodies(workflow, mailbox)
    assert mailbox.calls == 4
    assert workflow.store.get_setting('mail_recovery:empty')['status'] == 'unavailable'


def test_reconciliation_keeps_real_steps_and_completed_outcomes(db, vault):
    from erasure.inbox import reconcile_attention
    from erasure.models import Approval
    case, workflow = make_case(db, vault)
    case.state = 'needs_action'
    workflow._create_approval(case.id, 'ambiguous_reply', 'Unknown', {'body': 'We received your request.'})
    db.commit()
    reconcile_attention(workflow)
    assert case.state == 'processing'
    assert case.completed_at is None
    assert db.scalar(select(Approval)).status == 'recorded'
    count = db.scalar(select(func.count()).select_from(Event))
    reconcile_attention(workflow)
    assert db.scalar(select(func.count()).select_from(Event)) == count
    case.state = 'needs_action'
    workflow._create_approval(case.id, 'unverified_sender', 'Unknown', {'message': {'body': 'Please provide your work email.'}})
    db.commit()
    reconcile_attention(workflow)
    assert case.state == 'needs_action'
    case.state = 'removed'
    case.completed_at = datetime.now(UTC)
    db.commit()
    completed_at = case.completed_at
    reconcile_attention(workflow)
    assert case.state == 'removed' and case.completed_at == completed_at


def test_mail_survives_processing_failure_and_is_retried(db, vault, monkeypatch):
    case, workflow = make_case(db, vault)
    original = workflow.process_message
    def fail(*args, **kwargs):
        raise RuntimeError('Parser unavailable')
    monkeypatch.setattr(workflow, 'process_message', fail)
    capture_message(workflow, {'id': 'durable', 'subject': f'ER-{case.id:06X}',
        'from': 'privacy@sample.test', 'body': 'We received your request.',
        'authentication_results': 'mx.google.com; dmarc=pass header.from=sample.test'})
    assert db.get(IncomingMessage, 'durable').status == 'pending_processing'
    monkeypatch.setattr(workflow, 'process_message', original)
    workflow.store.set_setting('mail_processing:durable', {'attempts': 1}, encrypted=True)
    class Mailbox:
        def list_recent(self):
            return ['durable']
        def read_message(self, mid):
            raise AssertionError('Already stored mail should not be downloaded again')
    poll_mailbox(workflow, Mailbox())
    assert db.get(IncomingMessage, 'durable').status == 'processed'
    assert case.state == 'processing'


def make_case(db, vault):
    broker = Broker(
        slug="sample", name="Sample", domain="sample.test", contact="privacy@sample.test"
    )
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="submitted", submitted_at=datetime.now(UTC))
    db.add(case)
    db.commit()
    return case, Workflow(db, Store(db, vault), Settings())


def test_vendor_reply_is_visible_once_and_review_cancels_followup(db, vault):
    case, workflow = make_case(db, vault)
    workflow.store.enqueue("follow_up", {"case_id": case.id})
    mail = {
        "id": "vendor-1",
        "subject": "Your deletion is complete",
        "body": "Deleted",
        "from": "privacy@vendor.test",
        "thread_id": "new-thread",
    }
    capture_message(workflow, mail)
    capture_message(workflow, mail)
    assert db.scalar(select(func.count()).select_from(IncomingMessage)) == 1
    record = db.get(IncomingMessage, "vendor-1")
    assert record.status == "review"
    assert case.state == "submitted"
    review_message(workflow, record, case.id, "removed")
    assert case.state == "removed"
    assert db.scalar(select(Job).where(Job.kind == "follow_up")).status == "cancelled"
    assert db.scalar(select(Job).where(Job.kind == "recheck_case")).status == "pending"
    assert db.scalar(select(Event).where(Event.kind == "reply_reviewed")) is not None
    with pytest.raises(ValueError):
        review_message(workflow, record, case.id, "processing")


def test_authenticated_new_thread_matches_and_late_ack_does_not_undo_completion(db, vault):
    case, workflow = make_case(db, vault)
    mail = {
        "id": "official-1",
        "subject": "Deletion complete",
        "body": "Deletion complete",
        "from": "privacy@sample.test",
        "thread_id": "new-thread",
        "authentication_results": "mx.google.com; dmarc=pass header.from=sample.test",
    }
    capture_message(workflow, mail)
    assert case.state == "removed"
    capture_message(
        workflow,
        {**mail, "id": "official-2", "subject": "Request", "body": "received your request"},
    )
    assert case.state == "removed"


@pytest.mark.parametrize("state", ["done", "removed", "not_found"])
def test_late_untrusted_reply_does_not_reopen_outcome(db, vault, state):
    case, workflow = make_case(db, vault)
    case.state = state
    case.external_reference = "gmail-thread:synthetic"
    db.commit()
    capture_message(workflow, {
        "id": "untrusted-late", "subject": "Request", "body": "Please use our form",
        "from": "unknown@example.test", "thread_id": "synthetic",
    })
    assert case.state == state
    assert db.get(IncomingMessage, "untrusted-late") is not None


def test_poll_backfills_read_mail_and_records_real_sync(db, vault):
    _, workflow = make_case(db, vault)

    class Mailbox:
        def list_recent(self):
            return ["read-message"]

        def read_message(self, mid):
            return {
                "id": mid,
                "subject": "New thread",
                "body": "Please use our form",
                "from": "vendor@test.invalid",
            }

    poll_mailbox(workflow, Mailbox())
    assert db.get(IncomingMessage, "read-message").status == "review"
    assert workflow.store.get_setting("gmail_last_sync")


def test_folded_authenticated_no_data_reply_updates_case(db, vault):
    case, workflow = make_case(db, vault)
    capture_message(
        workflow,
        {
            "id": "no-data",
            "subject": f"Re: ER-{case.id:06X}",
            "body": "We checked our records and confirm we hold no personal data on the data subject.",
            "from": "privacy@sample.test",
            "authentication_results": "mx.google.com;\r\n dkim=pass header.i=@sample.test;\r\n dmarc=pass header.from=sample.test",
        },
    )
    assert case.state == "not_found"
    assert db.get(IncomingMessage, "no-data").status == "processed"


def test_completion_closes_old_tasks_without_deleting_history(db, vault):
    from erasure.models import Approval

    case, workflow = make_case(db, vault)
    old = workflow._create_approval(
        case.id, "ambiguous_reply", "Please use the form", {"body": "Original reply"}
    )
    workflow._complete(case, "not_found")
    db.commit()
    assert db.get(Approval, old.id).status == "superseded"
    assert vault.decrypt(old.encrypted_payload)["body"] == "Original reply"
    assert case.state == "not_found"


def test_reply_records_evidence_and_reschedules_without_profile_disclosure(db, vault, monkeypatch):
    case, workflow = make_case(db, vault)
    workflow.settings.live_submissions = True
    workflow.store.enqueue("follow_up", {"case_id": case.id})
    sent = []

    def send(_client, plan):
        sent.append(plan)
        return "gmail-thread:new"

    monkeypatch.setattr("erasure.workflow.GmailClient.send", send)
    workflow.send_reply(case.id, "privacy@sample.test", "Please provide an EEA process.")
    assert sent[0].body == "Please provide an EEA process."
    assert sent[0].disclosed_fields == ()
    assert "ER-" in sent[0].subject
    assert case.state == "processing"
    assert (
        db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.kind == "follow_up", Job.status == "pending")
        )
        == 1
    )
    assert db.scalar(select(Event).where(Event.kind == "reply_sent"))
    workflow.store.set_setting("paused", "true")
    with pytest.raises(ValueError):
        workflow.send_reply(case.id, "privacy@sample.test", "test")
    assert len(sent) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_poll_job_reuses_one_schedule_on_success_or_failure(
    db, vault, master_key, monkeypatch, fails
):
    from erasure import worker
    from erasure.gmail import GmailError

    store = Store(db, vault)
    job = store.enqueue("poll_gmail", {})
    job_id = job.id
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: Settings(
            master_key=master_key, password_hash="configured", session_secret="configured"
        ),
    )

    def handle(*args):
        if fails:
            raise GmailError("Reconnect Gmail")

    monkeypatch.setattr(worker, "handle_job", handle)
    assert worker.run_once()
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "poll_gmail")) == 1
    assert db.get(Job, job_id).status == "pending"
    assert db.get(Job, job_id).run_at > datetime.now(UTC).replace(tzinfo=None)
    if fails:
        assert store.get_setting("gmail_error")
