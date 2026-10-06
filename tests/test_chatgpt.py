"""Protocol/security tests with synthetic tokens and mocked HTTP, NOT accuracy evals."""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from erasure import chatgpt, reply_assistance
from erasure import chatgpt_auth as auth
from erasure.config import Settings
from erasure.jev import reply_state
from erasure.models import AppSetting
from erasure.replies import ReplyKind
from erasure.store import Store


def completion(kind='confirmation', evidence='We are processing your request.', **overrides):
    return {'type': 'response.completed', 'response': {'status': 'completed',
        'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
            'text': json.dumps({'kind': kind, 'evidence': evidence})}]}],
        'usage': {'input_tokens': 123}, **overrides}}


def streamed(*events, status=200):
    return httpx.Response(status, content=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))


def classifier(handler):
    return chatgpt.ChatGPTClassifier('synthetic-access', transport=httpx.MockTransport(handler))


def test_request_is_readonly_minimized_and_schema_constrained():
    def handler(request):
        assert request.url == chatgpt.RESOURCE + '/responses'
        assert request.headers['authorization'] == 'Bearer synthetic-access'
        payload = json.loads(request.content)
        assert payload['model'] == chatgpt.MODEL
        assert payload['store'] is False and payload['stream'] is True
        assert set(payload) == {'model', 'store', 'stream', 'reasoning', 'instructions', 'input', 'text'}
        assert payload['text']['format']['strict'] is True
        assert 'secret@example.test' not in request.content.decode()
        assert 'Joe Smith' not in request.content.decode()
        return streamed(completion())
    client = classifier(handler)
    try:
        result = client.classify('Joe Smith secret@example.test', 'We are processing your request.', private_values=('Joe Smith',))
        assert result.kind == ReplyKind.CONFIRMATION and result.input_tokens == 123
        assert not hasattr(result, 'confidence')
    finally:
        client.close()


@pytest.mark.parametrize('event', [
    {'type': 'response.output_text.delta', 'delta': '{"kind":"completed"}'},
    {'type': 'response.incomplete', 'response': {}},
    {'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}},
    completion('not_a_category'), completion('completed', 'invented quotation'),
    completion(status='incomplete'), completion(output=[]),
    completion(output=[{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal', 'refusal': 'No'}]}]),
])
def test_partial_malformed_refused_or_unsubstantiated_output_is_not_applied(event):
    client = classifier(lambda request: streamed(event))
    try:
        with pytest.raises(chatgpt.ChatGPTError):
            client.classify('', 'We are processing your request.')
    finally:
        client.close()


def test_late_usage_error_ignores_earlier_complete_json():
    client = classifier(lambda request: streamed(
        {'type': 'response.output_text.delta', 'delta': json.dumps({'kind': 'completed', 'evidence': 'deleted'})},
        {'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_unavailable'}}}))
    try:
        with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_limit'):
            client.classify('', 'deleted')
    finally:
        client.close()


def output_done(item=None, index=0):
    return {'type': 'response.output_item.done', 'output_index': index,
            'item': item if item is not None else {**completion()['response']['output'][0], 'status': 'completed'}}


def test_completed_stream_reconstructs_finalized_items_when_terminal_output_is_empty():
    # Observed on the real Luna sign-in: the answer is in output_item.done,
    # while response.completed contains output: []. Deltas alone aren't enough.
    client = classifier(lambda request: streamed(output_done(), completion(output=[])))
    try:
        result = client.classify('', 'We are processing your request.')
        assert result.kind == ReplyKind.CONFIRMATION and result.input_tokens == 123
    finally:
        client.close()


@pytest.mark.parametrize('terminal', [None, {'type': 'response.incomplete', 'response': {}},
    {'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}}])
def test_finalized_item_is_not_success_without_completed_response(terminal):
    events = [output_done()] + ([terminal] if terminal else [])
    client = classifier(lambda request: streamed(*events))
    try:
        with pytest.raises(chatgpt.ChatGPTError):
            client.classify('', 'We are processing your request.')
    finally:
        client.close()


@pytest.mark.parametrize('events', [
    [output_done(), output_done()],
    [output_done(index=-1)], [output_done(index=True)], [output_done(index=1)],
    [output_done({**completion()['response']['output'][0], 'status': 'in_progress'})],
    [output_done({**completion()['response']['output'][0], 'role': 'user', 'status': 'completed'})],
    [output_done({'type': 'message', 'role': 'assistant', 'status': 'completed',
                  'content': [{'type': 'refusal', 'refusal': 'No'}]})],
    [output_done({**completion('completed', 'invented quote')['response']['output'][0], 'status': 'completed'})],
])
def test_empty_terminal_output_does_not_bypass_stream_or_result_validation(events):
    client = classifier(lambda request: streamed(*events, completion(output=[])))
    try:
        with pytest.raises(chatgpt.ChatGPTError):
            client.classify('', 'We are processing your request.')
    finally:
        client.close()


def test_streamed_item_does_not_override_invalid_nonempty_terminal_output():
    client = classifier(lambda request: streamed(output_done(), completion(output=[
        {'type': 'message', 'role': 'user', 'content': []}])))
    try:
        with pytest.raises(chatgpt.ChatGPTError):
            client.classify('', 'We are processing your request.')
    finally:
        client.close()


@pytest.mark.parametrize('opening,closing', [('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’')])
def test_added_quote_delimiters_are_removed_only_around_verbatim_evidence(opening, closing):
    body = 'Please reply to confirm that you want us to proceed with your deletion request.'
    client = classifier(lambda request: streamed(completion('action_required', opening + body + closing)))
    try:
        result = client.classify('', body)
        assert result.kind == ReplyKind.ACTION_REQUIRED and result.evidence == body
    finally:
        client.close()


@pytest.mark.parametrize('evidence', ['“We are processing your request."',
    '“We have deleted your personal records.”', 'We are processing ... your request.', '""'])
def test_quote_normalization_does_not_accept_unmatched_invented_or_edited_evidence(evidence):
    client = classifier(lambda request: streamed(completion('completed', evidence)))
    try:
        with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_invalid_response'):
            client.classify('', 'We are processing your request.')
    finally:
        client.close()


def test_quotes_already_in_body_are_preserved():
    body = '“We are processing your request.”'
    client = classifier(lambda request: streamed(completion(evidence=body)))
    try:
        assert client.classify('', body).evidence == body
    finally:
        client.close()


@pytest.mark.parametrize('status,expected', [(401, 'chatgpt_reconnect'), (403, 'chatgpt_permission'), (404, 'chatgpt_model_unavailable'), (429, 'chatgpt_limit'), (500, 'chatgpt_unavailable')])
def test_http_failures_never_expose_remote_body(status, expected):
    client = classifier(lambda request: httpx.Response(status, text='private token or email'))
    try:
        with pytest.raises(chatgpt.ChatGPTError, match='^' + expected + '$'):
            client.classify('', 'hello')
    finally:
        client.close()


@pytest.mark.parametrize('code,param,expected', [
    ('subscription_sharing_user_not_eligible', '', 'chatgpt_ineligible'),
    ('subscription_sharing_usage_limit_exceeded', '', 'chatgpt_limit'),
    ('subscription_sharing_usage_unavailable', '', 'chatgpt_limit'),
    ('subscription_sharing_unsupported_capability', 'text.format', 'chatgpt_unsupported_request'),
    ('subscription_sharing_unsupported_capability', 'model', 'chatgpt_model_unavailable'),
    ('subscription_sharing_route_not_supported', '', 'chatgpt_integration_error'),
    ('chatpass_v2_scope_not_authorized', '', 'chatgpt_integration_error'),
    ('subscription_sharing_invalid_user', '', 'chatgpt_reconnect'),
    ('subscription_sharing_user_unavailable', '', 'chatgpt_unavailable'),
    ('model_not_found', 'model', 'chatgpt_model_unavailable'),
])
@pytest.mark.parametrize('transport', ['http', 'sse_nested', 'sse_top_level'])
def test_provider_errors_are_distinguished_without_exposing_private_text(code, param, expected, transport):
    error = {'code': code, 'param': param, 'message': 'private token and person@example.test'}
    if transport == 'http':
        response = httpx.Response(400, json={'error': error}, headers={'x-request-id': 'req_synthetic'})
    else:
        response = streamed({'type': 'response.failed', 'response': {'error': error}} if transport == 'sse_nested'
                            else {'type': 'error', **error})
    client = classifier(lambda request: response)
    try:
        with pytest.raises(chatgpt.ChatGPTError, match='^' + expected + '$') as caught:
            client.classify('', 'Synthetic reply')
        diagnostic = caught.value.diagnostic
        assert diagnostic['provider_code'] == code and diagnostic['param'] == param
        assert 'private token' not in json.dumps(diagnostic) and 'person@example.test' not in json.dumps(diagnostic)
        if transport == 'http':
            assert diagnostic['http_status'] == 400 and diagnostic['request_id'] == 'req_synthetic'
    finally:
        client.close()


@pytest.mark.parametrize('value', [{'detail': 'secret-token'}, {'error': {'code': 'secret-token', 'param': {'bad': 'secret-token'}}}, 'secret-token'])
def test_unstructured_admission_errors_do_not_leak_or_crash(value):
    client = classifier(lambda request: httpx.Response(503, json=value))
    try:
        with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_unavailable') as caught:
            client.classify('', 'Synthetic reply')
        assert 'secret-token' not in json.dumps(caught.value.diagnostic)
    finally:
        client.close()


SAMPLES = json.loads((Path(__file__).parent / 'fixtures/jev_replies.json').read_text())


@pytest.mark.parametrize('sample', SAMPLES, ids=lambda row: row['id'])
def test_existing_fixture_vocabulary_round_trips_protocol_not_model_accuracy(sample):
    state = reply_state(sample.get('subject', ''), sample['body'])
    client = classifier(lambda request: streamed(completion(sample['expected'], state['body'][:900])))
    try:
        assert client.classify(sample.get('subject', ''), sample['body']).kind.value == sample['expected']
    finally:
        client.close()


@pytest.fixture
def oauth(db, vault, monkeypatch):
    store = Store(db, vault)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())), 'kid': 'test', 'alg': 'RS256'}
    state = {'requests': [], 'claims': {}, 'token_overrides': {}, 'token_status': 200, 'canary_fail': False}

    def handler(request):
        state['requests'].append(request)
        if str(request.url) == auth.JWKS:
            return httpx.Response(200, json={'keys': [jwk]})
        if str(request.url) == auth.DISCOVERY:
            return httpx.Response(200, json={'issuer': auth.ISSUER, 'revocation_endpoint': auth.ISSUER + '/revoke'})
        if str(request.url) == auth.ISSUER + '/revoke':
            return httpx.Response(state.get('revoke_status', 200))
        assert str(request.url) == auth.TOKEN
        fields = parse_qs(request.content.decode())
        claims = {'iss': auth.ISSUER, 'aud': fields['client_id'][0], 'sub': 'person-1',
                  'iat': int(time.time()), 'exp': int(time.time()) + 3600, 'nonce': state['nonce'],
                  'email': 'synthetic@example.test', **state['claims']}
        encoded = jwt.encode(claims, private, algorithm='RS256', headers={'kid': 'test'})
        return httpx.Response(state['token_status'], json={'access_token': 'synthetic-access',
            'refresh_token': 'synthetic-refresh-' + str(len(state['requests'])), 'id_token': encoded,
            'expires_in': 3600, 'token_type': 'Bearer', 'scope': auth.SCOPES, **state['token_overrides']})

    monkeypatch.setattr(auth, 'http_client', lambda: httpx.Client(transport=httpx.MockTransport(handler)))

    class FakeClassifier:
        def __init__(self, token):
            assert token == 'synthetic-access'  # noqa: S105 - synthetic fixture

        def classify(self, subject, body):
            if state['canary_fail']:
                raise chatgpt.ChatGPTError('chatgpt_check_failed')
            expected = dict(chatgpt.CANARIES)[body]
            return chatgpt.ChatGPTReply(expected, body, chatgpt.MODEL, 100)

        def close(self):
            pass

    monkeypatch.setattr(auth, 'ChatGPTClassifier', FakeClassifier)
    return store, state


def pending_attempt(oauth, *, account='', browser='browser-one'):
    store, state = oauth
    url = auth.begin(store, browser, 'http://127.0.0.1:8787', account=account)
    query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
    state['nonce'] = query['nonce']
    return auth.consume(store, browser, query['state']), query


def connect(oauth, account=''):
    pending, query = pending_attempt(oauth, account=account)
    auth.finish(oauth[0], pending, {'state': query['state'], 'code': 'synthetic-code', 'client_id': account or 'oaiapp_test'})
    return pending, query


def test_oauth_pkce_storage_reconnect_and_stable_host(oauth):
    store, state = oauth
    pending, query = connect(oauth)
    assert query['client_id'] == 'dynamic_agent_client' and query['agent_name_hint'] == 'erase'
    assert query['code_challenge_method'] == 'S256'
    assert len(query['code_challenge']) == 43
    fields = parse_qs(state['requests'][0].content.decode())
    assert fields['client_id'] == ['oaiapp_test']
    assert fields['code_verifier'] == [pending['verifier']]
    assert fields['redirect_uri'] == [pending['redirect_uri']]
    assert 'client_secret' not in fields
    row = store.session.get(AppSetting, auth.SETTING)
    assert row.encrypted and 'synthetic-access' not in row.value
    assert reply_assistance.selection(Settings(_env_file=None), store)['provider'] == 'chatgpt'
    _, returning = connect(oauth, 'oaiapp_test')
    assert returning['ext_agent_host_id'] == query['ext_agent_host_id']
    assert returning['client_id'] == 'oaiapp_test'
    assert 'agent_name_hint' not in returning and 'id_token_hint' not in returning
    assert returning['nonce'] != query['nonce'] and returning['state'] != query['state']
    assert store.get_setting('chatgpt_welcomed') is True


@pytest.mark.parametrize('error', ['wrong_state', 'wrong_browser', 'expired', 'replay'])
def test_state_is_expiring_session_bound_and_one_time(oauth, error):
    store, _ = oauth
    _, query = pending_attempt(oauth) if error == 'replay' else (None, parse_qs(urlsplit(auth.begin(store, 'browser-one', 'http://127.0.0.1:8787')).query))
    state = query['state'] if error == 'replay' else query['state'][0]
    if error == 'expired':
        key = auth._pending_key('browser-one')
        saved = store.get_setting(key)
        store.set_setting(key, {**saved, 'expires': 0}, encrypted=True)
    with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_state'):
        auth.consume(store, 'wrong-browser' if error == 'wrong_browser' else 'browser-one', 'bad' if error == 'wrong_state' else state)


@pytest.mark.parametrize('claims', [{'iss': 'https://evil.test'}, {'aud': 'other'}, {'nonce': 'other'},
    {'exp': 1}, {'iat': 9999999999}, {'sub': ''}, {'azp': 'different'}, {'email': {'invalid': 'claim'}}])
def test_invalid_id_claims_cannot_replace_working_provider(oauth, claims):
    store, state = oauth
    store.set_setting(auth.PROVIDER, {'provider': 'jev', 'enabled': True}, encrypted=True)
    state['claims'] = claims
    with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_identity'):
        connect(oauth)
    assert store.get_setting(auth.PROVIDER)['provider'] == 'jev'
    assert not store.get_setting(auth.SETTING)['oaiapp_test'].get('access_token')


def test_invalid_signature_is_rejected(oauth, monkeypatch):
    store, state = oauth
    pending, _ = pending_attempt(oauth)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = jwt.encode({'sub': 'x'}, other, algorithm='RS256', headers={'kid': 'test'})
    with auth.http_client() as client, pytest.raises(chatgpt.ChatGPTError, match='chatgpt_identity'):
        auth.validate_identity(client, {'id_token': encoded}, 'oaiapp_test', pending['nonce'])


@pytest.mark.parametrize('failure', ['client_mismatch', 'identity_mismatch', 'missing_scope', 'canary', 'cancelled', 'missing_client'])
def test_failed_reconnection_preserves_working_credentials(oauth, failure):
    store, state = oauth
    connect(oauth)
    before = store.get_setting(auth.SETTING)
    pending, query = pending_attempt(oauth, account='oaiapp_test' if failure != 'missing_client' else '')
    params = {'code': 'code', 'client_id': 'oaiapp_test'}
    if failure == 'client_mismatch':
        params['client_id'] = 'oaiapp_other'
    elif failure == 'identity_mismatch':
        state['claims'] = {'sub': 'other-person'}
    elif failure == 'missing_scope':
        state['token_overrides'] = {'scope': 'openid email'}
    elif failure == 'canary':
        state['canary_fail'] = True
    elif failure == 'cancelled':
        params = {'error': 'access_denied'}
    else:
        params.pop('client_id')
    with pytest.raises(chatgpt.ChatGPTError):
        auth.finish(store, pending, params)
    assert store.get_setting(auth.SETTING) == before


def test_failed_exchange_retains_issued_registration(oauth):
    store, state = oauth
    state['token_status'] = 400
    with pytest.raises(chatgpt.ChatGPTError):
        connect(oauth)
    assert store.get_setting(auth.SETTING)['oaiapp_test']['client_id'] == 'oaiapp_test'
    assert store.get_setting(auth.PROVIDER) is None


def test_failed_sample_retains_encrypted_signin_for_retry_but_not_activation(oauth):
    store, state = oauth
    store.set_setting(auth.PROVIDER, {'provider': 'jev', 'enabled': True}, encrypted=True)
    state['canary_fail'] = True
    with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_check_failed'):
        connect(oauth)
    assert auth.can_retry(store)
    row = store.session.get(AppSetting, auth.CHECK_SETTING)
    assert row.encrypted and 'synthetic-access' not in row.value
    assert store.get_setting(auth.SETTING)['oaiapp_test'].get('access_token') is None
    assert store.get_setting(auth.PROVIDER) == {'provider': 'jev', 'enabled': True}
    assert store.get_setting(auth.DIAGNOSTIC_SETTING)['sample'] == 1
    calls = len(state['requests'])
    state['canary_fail'] = False
    assert auth.retry_connection(store) is True
    assert len(state['requests']) == calls  # no second OAuth exchange
    assert store.get_setting(auth.PROVIDER)['provider'] == 'chatgpt'
    assert not store.get_setting(auth.CHECK_SETTING) and not store.get_setting(auth.DIAGNOSTIC_SETTING)


@pytest.mark.parametrize('failure', ['expired', 'changed_provider', 'disconnected'])
def test_failed_sample_retry_is_expiring_and_cannot_restore_revoked_choice(oauth, failure):
    store, state = oauth
    state['canary_fail'] = True
    with pytest.raises(chatgpt.ChatGPTError):
        connect(oauth)
    check = store.get_setting(auth.CHECK_SETTING)
    if failure == 'expired':
        store.set_setting(auth.CHECK_SETTING, {**check, 'expires': 0}, encrypted=True)
    elif failure == 'changed_provider':
        store.set_setting(auth.PROVIDER, {'provider': 'jev', 'enabled': False}, encrypted=True)
    else:
        auth.disconnect(store, 'oaiapp_test')
    state['canary_fail'] = False
    assert not auth.can_retry(store)
    with pytest.raises(chatgpt.ChatGPTError):
        auth.retry_connection(store)
    assert not store.get_setting(auth.CHECK_SETTING)
    assert (store.get_setting(auth.PROVIDER) or {}).get('provider') != 'chatgpt'


def test_disconnecting_failed_sample_revokes_temporary_credentials(oauth):
    store, state = oauth
    state['canary_fail'] = True
    with pytest.raises(chatgpt.ChatGPTError):
        connect(oauth)
    refresh = store.get_setting(auth.CHECK_SETTING)['record']['refresh_token']
    assert auth.disconnect(store, 'oaiapp_test')
    assert parse_qs(state['requests'][-1].content.decode())['token'] == [refresh]
    assert not store.get_setting(auth.CHECK_SETTING)


def test_rotation_persists_and_reuses_latest_tokens(oauth):
    store, state = oauth
    connect(oauth)
    accounts = store.get_setting(auth.SETTING)
    old_refresh = accounts['oaiapp_test']['refresh_token']
    accounts['oaiapp_test']['expires_at'] = 0
    store.set_setting(auth.SETTING, accounts, encrypted=True)
    assert auth.access_token(store, 'oaiapp_test') == 'synthetic-access'
    fields = parse_qs(state['requests'][-1].content.decode())
    assert fields['grant_type'] == ['refresh_token'] and fields['refresh_token'] == [old_refresh]
    new_refresh = store.get_setting(auth.SETTING)['oaiapp_test']['refresh_token']
    assert new_refresh != old_refresh
    calls = len(state['requests'])
    auth.access_token(store, 'oaiapp_test')
    assert len(state['requests']) == calls


@pytest.mark.parametrize('revoke_status', [200, 500])
def test_disconnect_clears_tokens_retains_identity_and_reports_revocation(oauth, revoke_status):
    store, state = oauth
    connect(oauth)
    state['revoke_status'] = revoke_status
    assert auth.disconnect(store, 'oaiapp_test') is (revoke_status == 200)
    record = store.get_setting(auth.SETTING)['oaiapp_test']
    assert set(record) == {'client_id', 'label', 'email', 'subject'}
    assert not store.get_setting(auth.PROVIDER)['enabled']
    assert store.get_setting('chatgpt_host')


def test_same_email_accounts_stay_separate(oauth):
    store, state = oauth
    connect(oauth)
    pending, _ = pending_attempt(oauth)
    auth.finish(store, pending, {'code': 'code', 'client_id': 'oaiapp_second'})
    accounts = store.get_setting(auth.SETTING)
    assert len(accounts) == 2
    assert accounts['oaiapp_test']['email'] == accounts['oaiapp_second']['email']
    assert accounts['oaiapp_test']['label'] != accounts['oaiapp_second']['label']
    auth.disconnect(store, 'oaiapp_test')
    assert store.get_setting(auth.PROVIDER)['enabled']
    assert store.get_setting(auth.SETTING)['oaiapp_second']['access_token']


@pytest.mark.parametrize('url', ['https://127.0.0.1:8787', 'http://localhost:8787', 'http://evil.test', 'http://127.0.0.1/a'])
def test_non_loopback_registration_rejected(oauth, url):
    with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_loopback'):
        auth.begin(oauth[0], 'browser', url)


def test_non_ascii_state_is_a_safe_signin_error(oauth):
    store, _ = oauth
    auth.begin(store, 'browser-one', 'http://127.0.0.1:8787')
    with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_state'):
        auth.consume(store, 'browser-one', 'malformed-🙂')


def test_connection_checks_luna_inference_without_model_picker_gate():
    requests = []

    def handler(request):
        # A hidden/absent picker entry must not block working Luna inference.
        if request.url.path == '/v1/models':
            pytest.fail('Connection must test inference, not model-picker visibility')
        assert request.url.path == '/v1/responses' and request.method == 'POST'
        payload = json.loads(request.content)
        assert payload['model'] == 'gpt-6-luna'
        state = json.loads(payload['input'][0]['content'])
        requests.append(request)
        expected = dict(chatgpt.CANARIES)[state['body']]
        return streamed(completion(expected.value, state['body']))

    client = classifier(handler)
    try:
        chatgpt.check_connection(client)
    finally:
        client.close()
    assert len(requests) == len(chatgpt.CANARIES)


@pytest.mark.parametrize('failure', ['wrong_answer', 'model_denied', 'usage_limit'])
def test_connection_rejects_failed_inference_without_model_fallback(failure):
    requests = []

    def handler(request):
        assert json.loads(request.content)['model'] == 'gpt-6-luna'
        requests.append(request)
        if failure == 'wrong_answer':
            return streamed(completion('ambiguous', ''))
        return httpx.Response(404 if failure == 'model_denied' else 429, text='private provider error')

    client = classifier(handler)
    expected = {'wrong_answer': 'chatgpt_check_failed', 'model_denied': 'chatgpt_model_unavailable', 'usage_limit': 'chatgpt_limit'}[failure]
    try:
        with pytest.raises(chatgpt.ChatGPTError, match='^' + expected + '$'):
            chatgpt.check_connection(client)
    finally:
        client.close()
    assert len(requests) == 1


def test_two_worker_sessions_refresh_once_and_read_rotated_credentials(oauth):
    store, state = oauth
    connect(oauth)
    accounts = store.get_setting(auth.SETTING)
    accounts['oaiapp_test']['expires_at'] = 0
    store.set_setting(auth.SETTING, accounts, encrypted=True)
    before = len(state['requests'])

    def use_token():
        with Session(store.session.get_bind()) as session:
            return auth.access_token(Store(session, store.vault), 'oaiapp_test')

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: use_token(), range(2))) == ['synthetic-access'] * 2
    assert len(state['requests']) == before + 1


def test_refresh_honors_lock_held_by_another_process(oauth):
    store, _ = oauth
    connect(oauth)
    path = str(Path(store.session.get_bind().url.database).resolve()) + '.chatgpt.lock'
    script = ('import sys; from filelock import FileLock; '
              'lock=FileLock(sys.argv[1]); lock.acquire(); '
              'print("locked",flush=True); sys.stdin.read(1); lock.release()')
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter/script, validated temporary lock path
        [sys.executable, '-c', script, path], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        with pytest.raises(chatgpt.ChatGPTError, match='chatgpt_busy'):
            auth.access_token(store, 'oaiapp_test')
    finally:
        process.communicate('x', timeout=5)
    assert process.returncode == 0
