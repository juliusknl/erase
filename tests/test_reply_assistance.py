import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure import reply_assistance
from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.jev import MODEL, JevError, JevReply
from erasure.models import AppSetting, Case, Event
from erasure.replies import ReplyKind
from erasure.reply_interpretation import enabled, interpret
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


@pytest.fixture
def assistance_app(tmp_path, master_key, monkeypatch):
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('assistance password'), session_secret=generate_session_secret(),
        TYPESAFE_API_KEY='', jev_enabled=False, templates_dir=ROOT / 'templates',
        static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f'sqlite:///{tmp_path}/assistance.db')
    calls = []

    class FakeClassifier:
        error = None

        def __init__(self, key):
            self.key = key

        def classify(self, subject, body, **kwargs):
            calls.append((self.key, subject, body))
            if self.error:
                raise JevError(self.error)
            return JevReply(ReplyKind.CONFIRMATION, .99, {'confirmation': .99}, MODEL, 100)

        def close(self):
            pass

    monkeypatch.setattr(reply_assistance, 'JevClassifier', FakeClassifier)
    monkeypatch.setattr('erasure.reply_interpretation.JevClassifier', FakeClassifier)
    monkeypatch.setattr('erasure.gmail.GmailClient.send', lambda *a, **k: pytest.fail('Setup must never send email'))
    with TestClient(create_app(settings, engine)) as client:
        yield client, engine, settings, calls, FakeClassifier
    engine.dispose()


def login(client):
    client.post('/login', data={'password': 'assistance password'})
    return re.search(r'name="csrf" value="([^"]+)"', client.get('/campaign').text)[1]


def test_popup_copy_explains_privacy_and_optional_reply_help(assistance_app):
    client, _, _, _, _ = assistance_app
    login(client)
    html = client.get('/campaign?reply_assistance=1').text
    popup = html.split('<dialog id="reply-assistance-dialog"', 1)[1].split('</dialog>', 1)[0]
    assert 'does not use it to train AI' in popup
    assert 'https://typesafe.ai/legal/privacy-policy' in popup
    assert 'optional and can significantly speed up handling replies' in popup
    for removed in ['like those in our test', '—', 'Check TypeSafe’s checkout',
                    'expire after 12 months', 'some may remain', 'email sending works without it']:
        assert removed not in popup


def test_connect_is_encrypted_and_runtime_uses_saved_key_immediately(assistance_app, master_key):
    client, engine, settings, calls, _ = assistance_app
    csrf = login(client)
    key = 'synthetic-private-key'
    response = client.post('/reply-assistance/connect', data={'csrf': csrf, 'api_key': key})
    assert response.status_code == 200 and 'Connected. Reply assistance is on.' in response.text
    assert calls == [(key, 'Test removal request', 'We received your request and will process it within 30 days.')]
    assert key not in response.text and key not in client.get('/api/status').text
    assert 'value="synthetic-private-key"' not in response.text
    with Session(engine) as session:
        setting = session.get(AppSetting, reply_assistance.SETTING)
        assert setting.encrypted and key not in setting.value
        store = Store(session, Vault(master_key))
        assert enabled(settings, store)
        assert not list(session.scalars(select(Case)))
        assert not list(session.scalars(select(Event)))
        classified, _ = interpret(Workflow(session, store, settings), 123, {'id': 'example',
            'subject': 'A real workflow reply', 'body': 'Your request is being processed.'})
        assert classified.kind == ReplyKind.CONFIRMATION
        assert calls[-1][0] == key
    # Fresh app instance reads the same saved configuration, not process-local settings.
    with TestClient(create_app(settings, engine)) as restarted:
        login(restarted)
        assert 'On ·' in restarted.get('/campaign').text


def test_auth_csrf_and_redirects(assistance_app):
    client, _, _, calls, _ = assistance_app
    assert client.post('/reply-assistance/connect', data={'api_key': 'secret'}).status_code == 401
    csrf = login(client)
    for action in ['connect', 'disable', 'disconnect']:
        assert client.post('/reply-assistance/' + action, data={'csrf': 'bad', 'api_key': 'secret'}).status_code == 403
    assert calls == []
    response = client.post('/reply-assistance/connect', data={'csrf': csrf,
        'api_key': 'valid-test', 'return_to': 'https://evil.example'}, follow_redirects=False)
    assert response.headers['location'].startswith('/campaign?')


@pytest.mark.parametrize('failure', ['http_401', 'http_402', 'http_429', 'provider_unavailable', 'unsafe-secret-error'])
def test_failed_replacement_preserves_previous_connection(assistance_app, master_key, failure):
    client, engine, settings, calls, fake = assistance_app
    csrf = login(client)
    client.post('/reply-assistance/connect', data={'csrf': csrf, 'api_key': 'good-key'})
    fake.error = failure
    response = client.post('/reply-assistance/connect', data={'csrf': csrf, 'api_key': 'bad-key'})
    assert 'previous connection settings haven’t changed' in response.text
    assert 'bad-key' not in response.text and 'unsafe-secret-error' not in response.text
    with Session(engine) as session:
        assert reply_assistance.configuration(settings, Store(session, Vault(master_key))) == (True, 'good-key')


def test_disable_disconnect_override_environment_and_do_not_send(assistance_app, master_key):
    client, engine, settings, calls, _ = assistance_app
    settings.jev_enabled = True
    from pydantic import SecretStr
    settings.typesafe_api_key = SecretStr('existing-env-key')
    csrf = login(client)
    assert 'On ·' in client.get('/campaign').text
    client.post('/reply-assistance/disable', data={'csrf': csrf})
    with Session(engine) as session:
        assert reply_assistance.configuration(settings, Store(session, Vault(master_key))) == (False, 'existing-env-key')
    assert calls == []
    client.post('/reply-assistance/connect', data={'csrf': csrf})
    assert calls[-1][0] == 'existing-env-key'
    client.post('/reply-assistance/disconnect', data={'csrf': csrf})
    with Session(engine) as session:
        assert reply_assistance.configuration(settings, Store(session, Vault(master_key))) == (False, '')


@pytest.mark.parametrize('key', ['', 'bad\nkey', '☃', 'a' * 513])
def test_invalid_key_never_calls_provider(assistance_app, key):
    client, _, _, calls, _ = assistance_app
    csrf = login(client)
    response = client.post('/reply-assistance/connect', data={'csrf': csrf, 'api_key': key})
    assert 'assistance_error=' in str(response.url)
    assert calls == []


def test_demo_is_simulated_and_never_stores_real_keys(db, vault, monkeypatch):
    settings = Settings(_env_file=None, demo_mode=True, database_url='sqlite:////tmp/demo.db')
    store = Store(db, vault)
    monkeypatch.setattr(reply_assistance, 'check_connection', lambda *a: pytest.fail('Demo called provider'))
    reply_assistance.connect(settings, store, 'do-not-save-this')
    assert reply_assistance.public_status(settings, store)['label'] == 'Demo connected'
    assert reply_assistance.configuration(settings, store) == (False, '')
    assert store.get_setting(reply_assistance.SETTING) is None
    reply_assistance.turn_off(settings, store)
    assert reply_assistance.public_status(settings, store)['label'] == 'Off'


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
@pytest.mark.parametrize('javascript', [True, False])
def test_popup_connect_disable_and_reconnect(assistance_app, live_app_server, tmp_path, browser_name, javascript):
    client, _, _, calls, _ = assistance_app
    login(client)
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(java_script_enabled=javascript, viewport={'width': 1440, 'height': 1000})
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        page.goto(url + '/campaign')
        page.locator('#reply-assistance').get_by_role('link', name='Set up reply assistance', exact=True).click()
        dialog = page.get_by_role('dialog', name='Let erase handle more replies')
        expect(dialog).to_be_visible()
        for theme in ['porcelain', 'conservatory', 'atelier', 'midnight']:
            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for width in [320, 790, 1440]:
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
                page.screenshot(path=str(tmp_path / f'assistance-{theme}-{width}.png'), animations='disabled')
        page.get_by_label('TypeSafe API key', exact=True).fill('browser-synthetic-key')
        page.get_by_role('button', name='Connect and enable', exact=True).click()
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role('status')).to_have_text('Connected. Reply assistance is on.')
        expect(page.get_by_label('Replace API key (optional)')).to_have_value('')
        page.get_by_role('button', name='Turn off', exact=True).click()
        expect(dialog.get_by_role('status')).to_contain_text('Reply assistance is off')
        page.get_by_role('button', name='Connect and enable', exact=True).click()
        expect(dialog.get_by_role('status')).to_have_text('Connected. Reply assistance is on.')
        dialog.get_by_role('link', name='Done', exact=True).click()
        expect(dialog).not_to_be_visible()
        assert len(calls) == 2
        if javascript:
            page.locator('#reply-assistance').get_by_role('link', name='Manage reply assistance', exact=True).click()
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
        browser.close()


def test_chatgpt_routes_require_auth_csrf_and_keep_pending_encrypted(assistance_app, master_key):
    from urllib.parse import parse_qs, urlsplit

    from erasure import chatgpt_auth

    client, engine, settings, calls, _ = assistance_app
    assert client.post('/chatgpt/connect').status_code == 401
    csrf = login(client)
    for route in ['/chatgpt/connect', '/chatgpt/disconnect', '/chatgpt/retry']:
        assert client.post(route, data={'csrf': 'invalid'}).status_code == 403
    response = client.post('/chatgpt/connect', data={'csrf': csrf, 'return_to': 'https://evil.test'})
    assert response.status_code == 200
    query = parse_qs(urlsplit(response.json()['url']).query)
    assert query['redirect_uri'] == ['http://127.0.0.1:8787/chatgpt/callback']
    with Session(engine) as session:
        store = Store(session, Vault(master_key))
        pending = store.get_setting(chatgpt_auth._pending_key(client.cookies['erasure_session']))
        assert pending['return_to'] == 'campaign'
        assert store.get_setting(chatgpt_auth.PROVIDER) is None
        assert pending['verifier'] not in response.text
    result = client.get('/chatgpt/callback', params={'state': query['state'][0], 'error': 'access_denied'})
    assert 'ChatGPT connection was cancelled' in result.text and calls == []
    replay = client.get('/chatgpt/callback', params={'state': query['state'][0], 'error': 'access_denied'})
    assert 'sign-in expired' in replay.text


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_chatgpt_failed_check_can_retry_without_oauth(assistance_app, live_app_server, master_key, monkeypatch, browser_name):
    from erasure import chatgpt, chatgpt_auth

    client, engine, _, _, _ = assistance_app
    login(client)
    with Session(engine) as session:
        store = Store(session, Vault(master_key))
        store.set_setting(chatgpt_auth.SETTING, {'oaiapp_test': {'client_id': 'oaiapp_test', 'label': 'Account 1'}}, encrypted=True)
        store.set_setting(chatgpt_auth.CHECK_SETTING, {'account': 'oaiapp_test', 'expires': time.time() + 600,
            'selection': None, 'record': {'access_token': 'synthetic-private-access', 'refresh_token': 'synthetic-private-refresh'}}, encrypted=True)
    calls = []

    class FakeClassifier:
        def __init__(self, token):
            assert token == 'synthetic-private-access'  # noqa: S105 - synthetic fixture

        def classify(self, subject, body):
            calls.append(body)
            return chatgpt.ChatGPTReply(dict(chatgpt.CANARIES)[body], body, chatgpt.MODEL, 10)

        def close(self):
            pass

    monkeypatch.setattr(chatgpt_auth, 'ChatGPTClassifier', FakeClassifier)
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 320, 'height': 1000})
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        page.goto(url + '/campaign?reply_assistance=1&assistance_provider=chatgpt&assistance_error=chatgpt_invalid_response')
        dialog = page.get_by_role('dialog')
        expect(page.get_by_role('button', name='Retry connection test', exact=True)).to_be_visible()
        assert 'synthetic-private' not in page.content()
        assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
        page.get_by_role('button', name='Retry connection test', exact=True).click()
        expect(dialog).to_contain_text('Connected. Reply assistance is on.')
        expect(page.get_by_role('button', name='Retry connection test', exact=True)).not_to_be_visible()
        assert page.url.startswith(url + '/campaign?') and len(calls) == 4
        browser.close()


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_chatgpt_popup_tabs_connect_and_errors(assistance_app, live_app_server, tmp_path, browser_name):
    client, _, _, calls, _ = assistance_app
    login(client)
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        page.goto(url + '/campaign?reply_assistance=1')
        dialog = page.get_by_role('dialog')
        page.get_by_role('tab', name='ChatGPT', exact=True).click()
        expect(page.get_by_role('button', name='Continue with ChatGPT', exact=True)).to_be_visible()
        expect(page.get_by_label('TypeSafe API key', exact=True)).not_to_be_visible()
        for theme in ['porcelain', 'conservatory', 'atelier', 'midnight']:
            page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            for width in [320, 790, 1440]:
                page.set_viewport_size({'width': width, 'height': 1000})
                assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
                page.screenshot(path=str(tmp_path / f'chatgpt-{theme}-{width}.png'), animations='disabled')
        # Failure remains inside the popup, reenables the button, exposes no provider payload.
        page.route('**/chatgpt/connect', lambda route: route.fulfill(status=400, json={'error': 'Please try again.'}))
        page.get_by_role('button', name='Continue with ChatGPT', exact=True).click()
        expect(dialog.locator('[data-chatgpt-status]')).to_have_text('Please try again.')
        expect(page.get_by_role('button', name='Continue with ChatGPT', exact=True)).to_be_enabled()
        # A server-supplied external auth URL is navigated, not form-posted (CSP remains self-only).
        page.unroute('**/chatgpt/connect')
        page.route('https://auth.openai.com/**', lambda route: route.fulfill(body='<h1>Mock ChatGPT consent</h1>', content_type='text/html'))
        page.get_by_role('button', name='Continue with ChatGPT', exact=True).click()
        expect(page.get_by_role('heading', name='Mock ChatGPT consent')).to_be_visible()
        assert calls == []
        browser.close()
