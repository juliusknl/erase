import time

import pytest
from test_reply_interpretation import pending, setup  # noqa: F401 - shared workflow fixture

from erasure import chatgpt, chatgpt_auth
from erasure.inbox import capture_message
from erasure.replies import ReplyKind
from erasure.reply_assistance import turn_off
from erasure.reply_interpretation import backfill_replies, cache_key, interpret


@pytest.fixture
def chat_setup(request, monkeypatch):
    workflow, case, message, jev = request.getfixturevalue('setup')
    selection = {'provider': 'chatgpt', 'enabled': True, 'account': 'oaiapp_test'}
    workflow.store.set_setting(chatgpt_auth.PROVIDER, selection, encrypted=True)
    workflow.store.set_setting(chatgpt_auth.SETTING, {'oaiapp_test': {
        'access_token': 'mock-access', 'refresh_token': 'mock-refresh', 'expires_at': time.time() + 3600}}, encrypted=True)

    class Classifier:
        kind = ReplyKind.CONFIRMATION
        calls = 0
        error = None

        def __init__(self, token):
            pass

        def classify(self, subject, body, **kwargs):
            self.__class__.calls += 1
            if self.error:
                raise chatgpt.ChatGPTError(self.error)
            return chatgpt.ChatGPTReply(self.kind, body, chatgpt.MODEL, 100)

        def close(self):
            pass

    monkeypatch.setattr(chatgpt, 'ChatGPTClassifier', Classifier)
    return workflow, case, message, Classifier, jev, selection


@pytest.mark.parametrize('kind,state,action', [
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
def test_mail_pipeline_status_actions_audit_and_cache(chat_setup, kind, state, action):
    workflow, case, message, classifier, jev, selection = chat_setup
    classifier.kind = kind
    capture_message(workflow, message)
    assert case.state == state
    assert [item.kind for item in pending(workflow)] == ([action] if action else [])
    decision = workflow.store.get_setting(cache_key(case.id, message, selection))
    assert decision['applied'] and decision['source'] == 'chatgpt'
    assert decision['confidence'] is None and decision['evidence'] == message['body']
    assert classifier.calls == 1 and jev.calls == 0
    assert backfill_replies(workflow) == 0


def test_unverified_sender_cannot_become_confirmed_deletion(chat_setup):
    workflow, case, message, classifier, _, _ = chat_setup
    classifier.kind = ReplyKind.COMPLETED
    message['authentication_results'] = ''
    capture_message(workflow, message)
    assert case.state not in {'done', 'removed', 'not_found'}
    assert [item.kind for item in pending(workflow)] == ['unverified_sender']


@pytest.mark.parametrize('error', ['chatgpt_limit', 'chatgpt_reconnect', 'chatgpt_invalid_response', 'chatgpt_unavailable'])
def test_provider_failure_keeps_rules_and_never_switches_to_jev(chat_setup, error):
    workflow, case, message, classifier, jev, _ = chat_setup
    classifier.error = error
    capture_message(workflow, message)
    assert case.state == 'processing'
    assert not pending(workflow)
    assert jev.calls == 0
    assert workflow.store.get_setting('chatgpt_health')['error'] == error
    message['id'] = 'different-reply'
    interpret(workflow, case.id, message)
    assert classifier.calls == 1  # cooldown, no retry storm


def test_disabling_and_demo_make_no_calls(chat_setup):
    workflow, case, message, classifier, jev, _ = chat_setup
    turn_off(workflow.settings, workflow.store)
    assert interpret(workflow, case.id, message)[1] == {}
    assert classifier.calls == 0 and jev.calls == 0
    workflow.settings.demo_mode = True
    workflow.store.set_setting(chatgpt_auth.PROVIDER, {'provider': 'chatgpt', 'enabled': True}, encrypted=True)
    assert interpret(workflow, case.id, message)[1] == {}
    assert classifier.calls == 0


def test_cache_namespaces_provider_and_account(chat_setup):
    _, case, message, _, _, selected = chat_setup
    assert len({cache_key(case.id, message), cache_key(case.id, message, selected),
                cache_key(case.id, message, {**selected, 'account': 'oaiapp_second'})}) == 3


def test_existing_form_safety_guard_still_applies(chat_setup):
    workflow, case, message, classifier, _, selection = chat_setup
    classifier.kind = ReplyKind.CONFIRMATION
    message['body'] = ('We received your request. Please submit your request via one of our designated methods: '
                       'Web Intake Form Access: https://sample.test/data-request-form')
    capture_message(workflow, message)
    assert case.state == 'needs_action'
    assert [item.kind for item in pending(workflow)] == ['form_required']
    assert workflow.store.get_setting(cache_key(case.id, message, selection))['guard']


def test_switching_provider_while_inflight_does_not_apply_result(chat_setup, monkeypatch):
    workflow, case, message, classifier, jev, _ = chat_setup

    def classify(self, subject, body, **kwargs):
        turn_off(workflow.settings, workflow.store)
        return chatgpt.ChatGPTReply(ReplyKind.COMPLETED, 'fake', chatgpt.MODEL, 123)

    monkeypatch.setattr(classifier, 'classify', classify)
    result, metadata = interpret(workflow, case.id, message)
    assert result.kind == ReplyKind.CONFIRMATION
    assert metadata['source'] == 'rules' and jev.calls == 0
