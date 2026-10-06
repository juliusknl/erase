"""Official public-client OAuth. Tokens live only in the existing encrypted vault."""

import base64
import hashlib
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from filelock import FileLock, Timeout

from erasure.chatgpt import MODEL, RESOURCE, ChatGPTClassifier, ChatGPTError, check_connection
from erasure.crypto import digest
from erasure.models import AppSetting

ISSUER = 'https://auth.openai.com'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
JWKS = ISSUER + '/.well-known/jwks.json'
DISCOVERY = ISSUER + '/.well-known/openid-configuration'
SCOPES = 'openid profile email offline_access resource.invoke chatgpt.tokens.use.direct'
SETTING = 'chatgpt_accounts'
CHECK_SETTING = 'chatgpt_connection_check'
DIAGNOSTIC_SETTING = 'chatgpt_connection_diagnostic'
PROVIDER = 'reply_assistance_provider'
_lock = RLock()


@contextmanager
def locked(store):
    """Serialize rotating credentials across UI/worker threads AND local processes."""
    database = store.session.get_bind().url.database
    if not _lock.acquire(timeout=2):
        raise ChatGPTError('chatgpt_busy')
    try:
        if database and database != ':memory:':
            with FileLock(str(Path(database).resolve()) + '.chatgpt.lock', timeout=2, mode=0o600):
                yield
        else:
            yield
    except Timeout:
        raise ChatGPTError('chatgpt_busy') from None
    finally:
        _lock.release()


def read(store, key, default=None):
    # A long-lived worker session must not overwrite a newer UI token rotation.
    row = store.session.get(AppSetting, key, populate_existing=True)
    if row is None:
        return default
    return store.vault.decrypt(row.value) if row.encrypted else row.value


def http_client():
    return httpx.Client(timeout=20, follow_redirects=False, trust_env=False)


def json_request(client, method, url, **kwargs):
    try:
        response = client.request(method, url, **kwargs)
        if response.status_code != 200:
            raise ChatGPTError('chatgpt_reconnect' if response.status_code in {400, 401, 403} else 'chatgpt_unavailable')
        if len(response.content) > 128_000:
            raise ChatGPTError('chatgpt_invalid_response')
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError
        return value
    except httpx.RequestError:
        raise ChatGPTError('chatgpt_unavailable') from None
    except ValueError:
        raise ChatGPTError('chatgpt_invalid_response') from None


def _pending_key(browser_session):
    return 'chatgpt_oauth:' + digest(browser_session)


def begin(store, browser_session, base_url, *, account='', return_to='campaign'):
    parts = urlsplit(base_url)
    if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or parts.path not in {'', '/'} or parts.username or parts.query or parts.fragment:
        raise ChatGPTError('chatgpt_loopback')
    with locked(store):
        store.set_setting(CHECK_SETTING, {}, encrypted=True)
        store.set_setting(DIAGNOSTIC_SETTING, {}, encrypted=True)
        host = read(store, 'chatgpt_host')
        if not host:
            host = 'urn:uuid:' + str(uuid.uuid4())
            store.set_setting('chatgpt_host', host, encrypted=True)
        accounts = read(store, SETTING, {})
        if account and account not in accounts:
            raise ChatGPTError('chatgpt_reconnect')
        verifier = secrets.token_urlsafe(48)
        pending = {'state': secrets.token_urlsafe(32), 'nonce': secrets.token_urlsafe(32),
                   'verifier': verifier, 'expires': time.time() + 600, 'account': account,
                   'redirect_uri': base_url.rstrip('/') + '/chatgpt/callback',
                   'return_to': 'setup' if return_to == 'setup' else 'campaign',
                   'selection': read(store, PROVIDER)}
        store.set_setting(_pending_key(browser_session), pending, encrypted=True)
        params = {'client_id': account or 'dynamic_agent_client', 'ext_agent_host_id': host,
                  'response_type': 'code', 'scope': SCOPES, 'resource': RESOURCE,
                  'state': pending['state'], 'nonce': pending['nonce'],
                  'redirect_uri': pending['redirect_uri'], 'code_challenge_method': 'S256',
                  'code_challenge': base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')}
        if not account:
            params['agent_name_hint'] = 'erase'
        # Deliberately omit optional id_token_hint: no credential goes into a URL.
        return AUTHORIZE + '?' + urlencode(params)


def consume(store, browser_session, state):
    with locked(store):
        key = _pending_key(browser_session)
        pending = read(store, key, {})
        if not state.isascii() or not pending or not secrets.compare_digest(pending['state'], state) or pending['expires'] < time.time():
            raise ChatGPTError('chatgpt_state')
        store.set_setting(key, {}, encrypted=True)
        return pending


def validate_identity(client, tokens, client_id, nonce):
    try:
        encoded = tokens['id_token']
        header = jwt.get_unverified_header(encoded)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
            raise ValueError
        keys = json_request(client, 'GET', JWKS)['keys']
        candidates = [key for key in keys if key.get('kid') == header['kid'] and key.get('kty') == 'RSA'
                      and key.get('use', 'sig') == 'sig' and key.get('alg', 'RS256') == 'RS256']
        if len(candidates) != 1:
            raise ValueError
        key = jwt.PyJWK.from_dict(candidates[0], algorithm='RS256').key
        claims = jwt.decode(encoded, key, algorithms=['RS256'], issuer=ISSUER,
                            audience=client_id, leeway=5,
                            options={'require': ['sub', 'exp', 'iat', 'nonce', 'iss', 'aud']})
        if not isinstance(claims['sub'], str) or not claims['sub'] or claims['nonce'] != nonce:
            raise ValueError
        if claims.get('azp', client_id) != client_id:
            raise ValueError
        if 'email' in claims and (not isinstance(claims['email'], str) or len(claims['email']) > 320):
            raise ValueError
        return claims
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError):
        raise ChatGPTError('chatgpt_identity') from None


def token_fields(tokens, previous=None):
    try:
        for name in ('access_token', 'refresh_token'):
            if not isinstance(tokens[name], str) or not tokens[name] or len(tokens[name]) > 32_000:
                raise ValueError
        if tokens['token_type'].lower() != 'bearer' or type(tokens['expires_in']) is not int or not 0 < tokens['expires_in'] <= 86400:
            raise ValueError
        scope = tokens.get('scope', (previous or {}).get('scope', ''))
        if not isinstance(scope, str) or not {'chatgpt.tokens.use.direct', 'resource.invoke', 'offline_access'} <= set(scope.split()):
            raise ChatGPTError('chatgpt_permission')
        return {'access_token': tokens['access_token'], 'refresh_token': tokens['refresh_token'],
                'expires_at': time.time() + tokens['expires_in'], 'scope': scope}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ChatGPTError('chatgpt_invalid_response') from None


def finish(store, pending, params):
    if params.get('error'):
        raise ChatGPTError('chatgpt_cancelled')
    client_id = params.get('client_id', pending['account'])
    if not re.fullmatch(r'oaiapp_[A-Za-z0-9_-]{1,200}', client_id or '') or (
            pending['account'] and pending['account'] != client_id):
        raise ChatGPTError('chatgpt_identity')
    code = params.get('code', '')
    if not code or len(code) > 8192:
        raise ChatGPTError('chatgpt_state')
    with locked(store):
        accounts = read(store, SETTING, {})
        previous = accounts.get(client_id, {})
        # Retain the issued registration even if code exchange fails; never activate it yet.
        if not previous:
            accounts[client_id] = {'label': f'Account {len(accounts) + 1}', 'client_id': client_id}
            store.set_setting(SETTING, accounts, encrypted=True)
        with http_client() as client:
            tokens = json_request(client, 'POST', TOKEN, data={
                'grant_type': 'authorization_code', 'client_id': client_id, 'code': code,
                'code_verifier': pending['verifier'], 'redirect_uri': pending['redirect_uri'], 'resource': RESOURCE})
            claims = validate_identity(client, tokens, client_id, pending['nonce'])
            if previous.get('subject') and claims['sub'] != previous['subject']:
                raise ChatGPTError('chatgpt_identity')
            credentials = token_fields(tokens)
        # A failed sample must not discard a verified sign-in or replace the
        # working account. Keep it separately for a short, explicit test retry.
        check = {'account': client_id, 'selection': pending['selection'],
                 'expires': min(time.time() + 600, credentials['expires_at'] - 30),
                 'record': {**credentials, 'subject': claims['sub'],
                            'email': claims.get('email', ''), 'id_token': tokens['id_token']}}
        store.set_setting(CHECK_SETTING, check, encrypted=True)
        return _test_connection(store, check)


def can_retry(store):
    check = read(store, CHECK_SETTING, {})
    if check and check['expires'] <= time.time():
        try:
            with locked(store):
                current = read(store, CHECK_SETTING, {})
                if current and current['expires'] <= time.time():
                    store.set_setting(CHECK_SETTING, {}, encrypted=True)
        except ChatGPTError:
            pass  # Cleanup can retry on the next view; expired credentials are unusable.
        return False
    return bool(check and check['expires'] > time.time() and check['selection'] == read(store, PROVIDER))


def retry_connection(store):
    with locked(store):
        check = read(store, CHECK_SETTING, {})
        if not check or check['expires'] <= time.time():
            store.set_setting(CHECK_SETTING, {}, encrypted=True)
            raise ChatGPTError('chatgpt_reconnect')
        return _test_connection(store, check)


def record_failure(store, exc):
    store.set_setting(DIAGNOSTIC_SETTING, {
        'error': str(exc), 'model': MODEL, 'recorded_at': time.time(),
        'phase': 'sample' if exc.diagnostic.get('sample') else 'sign_in',
        **exc.diagnostic}, encrypted=True)


def _test_connection(store, check):
    if read(store, PROVIDER) != check['selection']:
        store.set_setting(CHECK_SETTING, {}, encrypted=True)
        raise ChatGPTError('chatgpt_settings_changed')
    classifier = ChatGPTClassifier(check['record']['access_token'])
    try:
        check_connection(classifier)
    except ChatGPTError as exc:
        record_failure(store, exc)
        raise
    finally:
        classifier.close()
    if read(store, PROVIDER) != check['selection']:
        store.set_setting(CHECK_SETTING, {}, encrypted=True)
        raise ChatGPTError('chatgpt_settings_changed')
    accounts = read(store, SETTING, {})
    client_id = check['account']
    accounts[client_id] = {**accounts[client_id], **check['record']}
    store.set_setting(SETTING, accounts, encrypted=True)
    store.set_setting(CHECK_SETTING, {}, encrypted=True)
    store.set_setting(DIAGNOSTIC_SETTING, {}, encrypted=True)
    store.set_setting('chatgpt_health', {}, encrypted=True)
    store.set_setting(PROVIDER, {'provider': 'chatgpt', 'enabled': True, 'account': client_id}, encrypted=True)
    first_connection = not read(store, 'chatgpt_welcomed', False)
    if first_connection:
        store.set_setting('chatgpt_welcomed', True, encrypted=True)
    return first_connection


def access_token(store, account):
    with locked(store):
        accounts = read(store, SETTING, {})
        record = accounts.get(account, {})
        if not record.get('refresh_token'):
            raise ChatGPTError('chatgpt_reconnect')
        if record.get('expires_at', 0) <= time.time() + 30:
            with http_client() as client:
                tokens = json_request(client, 'POST', TOKEN, data={'grant_type': 'refresh_token',
                    'client_id': account, 'refresh_token': record['refresh_token'], 'resource': RESOURCE})
            record = {**record, **token_fields(tokens, record)}
            accounts[account] = record
            store.set_setting(SETTING, accounts, encrypted=True)
        return record['access_token']


def disconnect(store, account):
    confirmed = True
    with locked(store):
        check = read(store, CHECK_SETTING, {})
        if check.get('account') == account:
            store.set_setting(CHECK_SETTING, {}, encrypted=True)
        selection = read(store, PROVIDER, {})
        if selection.get('account') == account:
            store.set_setting(PROVIDER, {**selection, 'enabled': False}, encrypted=True)
        accounts = read(store, SETTING, {})
        record = accounts.get(account, {})
        refresh_token = (check['record'].get('refresh_token') if check.get('account') == account
                         else record.get('refresh_token'))
        if refresh_token:
            try:
                with http_client() as client:
                    discovery = json_request(client, 'GET', DISCOVERY)
                    endpoint = discovery.get('revocation_endpoint', '')
                    parsed = urlsplit(endpoint)
                    if discovery.get('issuer') != ISSUER or parsed.scheme != 'https' or parsed.netloc != 'auth.openai.com' or parsed.query or parsed.fragment:
                        raise ChatGPTError('chatgpt_invalid_response')
                    response = client.post(endpoint, data={'token': refresh_token,
                        'token_type_hint': 'refresh_token', 'client_id': account})
                    confirmed = response.status_code == 200
            except (ChatGPTError, httpx.RequestError):
                confirmed = False
        if record:
            accounts[account] = {key: record[key] for key in ('client_id', 'label', 'email', 'subject') if key in record}
            store.set_setting(SETTING, accounts, encrypted=True)
    return confirmed
