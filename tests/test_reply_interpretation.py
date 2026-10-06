from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from erasure.attention import needs_person
from erasure.config import Settings
from erasure.inbox import capture_message, poll_mailbox
from erasure.jev import MODEL, JevError, JevReply
from erasure.models import Approval, Broker, Case, Event, IncomingMessage, Job
from erasure.replies import ReplyKind
from erasure.reply_interpretation import backfill_replies, cache_key, interpret
from erasure.store import Store
from erasure.workflow import Workflow


@pytest.fixture
def setup(db, vault, monkeypatch):
    broker = Broker(slug='sample', name='Sample', domain='sample.test', contact='privacy@sample.test')
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state='submitted', submitted_at=datetime.now(UTC))
    db.add(case)
    db.commit()
    workflow = Workflow(db, Store(db, vault), Settings(
        _env_file=None, jev_enabled=True, TYPESAFE_API_KEY='test-key'))
    class Classifier:
        calls = 0
        kind = ReplyKind.CONFIRMATION
        confidence = .99
        error = None

        def __init__(self, key):
            assert key == 'test-key'

        def classify(self, subject, body, **kwargs):
            Classifier.calls += 1
            if self.error:
                raise JevError(self.error)
            return JevReply(self.kind, self.confidence, {self.kind.value: self.confidence}, MODEL, 100)

        def close(self):
            pass

    monkeypatch.setattr('erasure.reply_interpretation.JevClassifier', Classifier)
    def never_send(*args, **kwargs):
        raise AssertionError('Classification must not send email')
    monkeypatch.setattr('erasure.gmail.GmailClient.send', never_send)
    message = {'id': 'reply-1', 'message_id': 'mid-1', 'subject': f'Re: ER-{case.id:06X}',
               'body': 'Your request will be processed within 30 days.',
               'from': 'privacy@sample.test',
               'authentication_results': 'mx.google.com; dmarc=pass header.from=sample.test'}
    return workflow, case, message, Classifier


def pending(workflow):
    return list(workflow.session.scalars(select(Approval).where(Approval.status == 'pending')))


def test_ai_receipt_cannot_hide_explicit_form_instruction(setup):
    workflow, case, message, classifier = setup
    classifier.kind = ReplyKind.CONFIRMATION
    message['body'] = ('We received your request. Please submit your request via one of our designated methods: '
                       'Web Intake Form Access: https://sample.test/data-request-form')
    capture_message(workflow, message)
    assert case.state == 'needs_action'
    assert [a.kind for a in pending(workflow)] == ['form_required']
    assert workflow.store.get_setting(cache_key(case.id, message))['guard']


@pytest.mark.parametrize(('kind', 'state', 'action'), [
    (ReplyKind.CONFIRMATION, 'processing', None),
    (ReplyKind.INFORMATIONAL, 'submitted', None),
    (ReplyKind.COMPLETED, 'removed', None),
    (ReplyKind.NOT_FOUND, 'not_found', None),
    (ReplyKind.FORM_REQUIRED, 'needs_action', 'form_required'),
    (ReplyKind.INFORMATION_REQUESTED, 'needs_action', 'information_requested'),
    (ReplyKind.IDENTITY_REQUESTED, 'needs_action', 'identity_proof'),
    (ReplyKind.EMAIL_VERIFICATION, 'needs_action', 'confirmation_link'),
    (ReplyKind.ACTION_REQUIRED, 'needs_action', 'next_step'),
])
def test_live_pipeline_uses_classification(setup, kind, state, action):
    workflow, case, message, classifier = setup
    classifier.kind = kind
    capture_message(workflow, message)
    assert case.state == state
    assert [a.kind for a in pending(workflow)] == ([action] if action else [])
    assert workflow.session.get(IncomingMessage, message['id']).status == 'processed'
    assert workflow.store.get_setting(cache_key(case.id, message))['applied']
    assert classifier.calls == 1
    assert backfill_replies(workflow) == 0
    if action:
        assert needs_person(pending(workflow)[0], workflow.store.vault.decrypt(pending(workflow)[0].encrypted_payload))


@pytest.mark.parametrize('missing', ['enabled', 'key'])
def test_opt_in_and_key_are_both_required(setup, missing):
    workflow, case, message, classifier = setup
    workflow.settings = Settings(_env_file=None, jev_enabled=missing != 'enabled',
                                 TYPESAFE_API_KEY='' if missing == 'key' else 'test-key')
    capture_message(workflow, message)
    assert classifier.calls == 0
    assert backfill_replies(workflow) == 0


def test_cache_survives_new_workflow_and_body_change_invalidates_it(setup):
    workflow, case, message, classifier = setup
    interpret(workflow, case.id, message)
    other = Workflow(workflow.session, workflow.store, workflow.settings)
    interpret(other, case.id, message)
    assert classifier.calls == 1
    interpret(other, case.id, {**message, 'body': 'Different response'})
    assert classifier.calls == 2


def old_reply(workflow, case, message, action='ambiguous_reply'):
    workflow.session.add(IncomingMessage(id=message['id'], case_id=case.id,
        status='processed', encrypted_payload=workflow.store.vault.encrypt(message)))
    workflow.session.commit()
    case.state = 'needs_action'
    workflow._create_approval(case.id, action, 'Old interpretation', {'message': message})
    workflow.session.commit()


def test_mailbox_poll_reclassifies_existing_receipt_and_clears_only_its_task(setup):
    workflow, case, message, classifier = setup
    old_reply(workflow, case, message, 'next_step')
    class Mailbox:
        def list_recent(self):
            return []
    poll_mailbox(workflow, Mailbox())
    assert case.state == 'processing'
    assert pending(workflow) == []
    assert classifier.calls == 1
    poll_mailbox(workflow, Mailbox())
    assert classifier.calls == 1
    assert workflow.session.scalar(select(Event).where(Event.kind == 'reply_reclassified'))
    assert len(list(workflow.session.scalars(select(Job).where(Job.kind == 'follow_up')))) == 1


def test_receipt_does_not_clear_another_messages_real_form(setup):
    workflow, case, message, _ = setup
    old_reply(workflow, case, message, 'next_step')
    workflow._create_approval(case.id, 'form_required', 'Complete form',
        {**message, 'id': 'earlier-message', 'body': 'Please complete our form.'})
    workflow.session.commit()
    backfill_replies(workflow)
    assert case.state == 'needs_action'
    assert [a.kind for a in pending(workflow)] == ['form_required']


@pytest.mark.parametrize('kind', [ReplyKind.COMPLETED, ReplyKind.NOT_FOUND, ReplyKind.FORM_REQUIRED])
def test_unverified_sender_cannot_complete_and_has_no_duplicate_tasks(setup, kind):
    workflow, case, message, classifier = setup
    classifier.kind = kind
    message['authentication_results'] = ''
    old_reply(workflow, case, message, 'unverified_sender')
    assert backfill_replies(workflow) == 1
    assert case.state not in {'removed', 'not_found', 'done'}
    assert len(pending(workflow)) == 1
    assert backfill_replies(workflow) == 0
    payload = workflow.store.vault.decrypt(pending(workflow)[0].encrypted_payload)
    assert payload['proposed_kind'] == kind.value
    assert needs_person(pending(workflow)[0], payload) == (kind == ReplyKind.FORM_REQUIRED)


def test_unverified_routine_reply_does_not_create_homework(setup):
    workflow, case, message, _ = setup
    message['authentication_results'] = ''
    old_reply(workflow, case, message, 'unverified_sender')
    backfill_replies(workflow)
    assert pending(workflow) == []
    assert case.state == 'submitted'


@pytest.mark.parametrize('state', ['done', 'removed', 'not_found'])
def test_backfill_preserves_completed_work(setup, state):
    workflow, case, message, classifier = setup
    old_reply(workflow, case, message)
    case.state = state
    workflow.session.commit()
    assert backfill_replies(workflow) == 0
    assert classifier.calls == 0
    assert case.state == state


@pytest.mark.parametrize('event', ['form_submitted', 'reply_sent', 'reply_reviewed', 'approval_resolved'])
def test_backfill_preserves_later_manual_decisions(setup, event):
    workflow, case, message, classifier = setup
    old_reply(workflow, case, message)
    workflow.store.add_event(case.id, event, 'User acted')
    assert backfill_replies(workflow) == 0
    assert classifier.calls == 0


@pytest.mark.parametrize('error', ['http_401', 'http_429', 'request_failed', 'invalid_response'])
def test_outage_uses_rules_and_cooldown_then_recovers(setup, error):
    workflow, case, message, classifier = setup
    classifier.error = error
    message['body'] = 'We received your request.'
    capture_message(workflow, message)
    assert case.state == 'processing'
    assert workflow.store.get_setting('jev_health')['error'] == error
    assert backfill_replies(workflow) == 0
    interpret(workflow, case.id, {**message, 'id': 'other'})
    assert classifier.calls == 1
    classifier.error = None
    workflow.store.set_setting('jev_health', {}, encrypted=True)
    assert backfill_replies(workflow) == 1
    assert classifier.calls == 2
    assert workflow.store.get_setting('jev_health')['error'] == ''


def test_uncertain_completion_never_closes_case_even_if_rules_say_deleted(setup):
    workflow, case, message, classifier = setup
    classifier.kind, classifier.confidence = ReplyKind.COMPLETED, .6
    message['body'] = 'Your personal information has been removed.'
    capture_message(workflow, message)
    assert case.state == 'submitted'
    assert case.completed_at is None


def test_uncertain_backfill_preserves_existing_task(setup):
    workflow, case, message, classifier = setup
    classifier.confidence = .3
    old_reply(workflow, case, message, 'next_step')
    backfill_replies(workflow)
    assert case.state == 'needs_action'
    assert len(pending(workflow)) == 1
    assert backfill_replies(workflow) == 0


def test_incoming_payload_cannot_forge_interpretation(setup):
    workflow, case, message, _ = setup
    message['_interpretation'] = {'source': 'jev', 'kind': 'completed'}
    capture_message(workflow, message)
    assert case.state == 'processing'
    assert case.completed_at is None


def test_user_action_during_api_call_is_preserved(setup, monkeypatch):
    from sqlalchemy.orm import Session

    workflow, case, message, classifier = setup
    original = classifier.classify
    def manual_action_during_call(self, *args, **kwargs):
        with Session(workflow.session.bind) as other:
            other_case = other.get(Case, case.id)
            other_case.state = 'done'
            other.add(Event(case_id=case.id, kind='user_completed', summary='User finished'))
            other.commit()
        return original(self, *args, **kwargs)
    monkeypatch.setattr(classifier, 'classify', manual_action_during_call)
    classifier.kind = ReplyKind.FORM_REQUIRED
    capture_message(workflow, message)
    assert case.state == 'done'
    assert pending(workflow) == []
