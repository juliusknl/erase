import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erasure import campaign, setup_flow
from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.gmail import GmailClient, GmailError
from erasure.models import AppSetting, AutomaticDelivery, Case, Job, Profile
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


def hidden(page, key):
    return re.search(r'name="' + key + r'" value="([^"]*)"', page).group(1)


@pytest.fixture
def setup_app(tmp_path, master_key, monkeypatch):
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request',
                        lambda *a, **k: pytest.fail('Setup tests must not use real HTTP'))
    settings = Settings(_env_file=None, demo_mode=True, database_url=f'sqlite:///{tmp_path}/demo.db',
        live_submissions=True, master_key=master_key, password_hash=hash_password('setup test password'),
        session_secret=generate_session_secret(), catalog_dir=ROOT / 'catalog',
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static')
    engine = create_db_engine(settings.database_url)
    app = create_app(settings, engine)
    with TestClient(app) as client:
        app.state.worker_thread = SimpleNamespace(is_alive=lambda: True)
        response = client.post('/login', data={'password': 'setup test password'})
        assert response.url.path == '/setup'
        yield client, settings, engine
    engine.dispose()


def details(client):
    csrf = hidden(client.get('/setup').text, 'csrf')
    client.post('/setup/appearance', data={'csrf': csrf, 'theme': 'porcelain'})
    response = client.post('/setup/country', data={'csrf': csrf, 'country': 'DE'})
    assert '<h1>Your info</h1>' in response.text
    assert 'Enter emails you use most' in response.text
    response = client.post('/setup/details', data={'csrf': csrf, 'full_name': 'Alex Example',
                           'emails': ['alex@example.test', 'work@example.test']})
    assert 'Choose your request mailbox' in response.text
    assert 'href="https://accounts.google.com/signup"' in response.text
    assert 'I recommend a dedicated inbox' in response.text
    assert 'stopstealingmydatafuckers@gmail.com' in response.text
    return csrf


def ready(client):
    csrf = details(client)
    response = client.get('/gmail/connect?return_to=setup')
    assert response.url.path == '/demo/mailbox'
    assert 'primary-nav' not in response.text
    response = client.post('/demo/mailbox', data={'csrf': csrf})
    assert response.url.path == '/setup' and response.url.query == b'step=4'
    assert 'requests@example.test' in response.text
    return {'csrf': csrf, 'authorize': 'true', 'signature': 'Alex Example',
            'preview_hash': hidden(response.text, 'preview_hash')}


def test_onboarding_reply_assistance_includes_chatgpt_and_returns_to_setup(setup_app):
    client, settings, engine = setup_app
    payload = ready(client)
    page = client.get('/setup?step=4&reply_assistance=1&assistance_provider=chatgpt')
    assert 'id="assistance-jev-tab"' in page.text
    assert 'id="assistance-chatgpt-tab"' in page.text
    assert 'Try ChatGPT demo' in page.text
    assert 'name="return_to" value="setup"' in page.text
    response = client.post('/chatgpt/connect', data={'csrf': payload['csrf'], 'return_to': 'setup'})
    assert response.status_code == 200
    page = client.get(response.json()['url'])
    assert page.url.path == '/setup' and 'Ready when you are.' in page.text
    assert 'Currently using ChatGPT' in page.text
    assert hidden(page.text, 'preview_hash') == payload['preview_hash']
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_profile() is None and not campaign.consent(store)
        assert not store.get_setting('chatgpt_accounts')


def test_full_setup_one_permission_and_idempotent_start(setup_app):
    client, settings, engine = setup_app
    introduction = client.get('/setup').text
    assert 'Step 1 of 5' in introduction
    assert 'Make it yours.' in introduction
    assert introduction.count('class="appearance-option"') == 4
    csrf = hidden(introduction, 'csrf')
    introduction = client.post('/setup/appearance', data={'csrf': csrf, 'theme': 'porcelain'}).text
    assert 'A little less out there' not in introduction
    assert 'The app uses your country to choose relevant requests.' in introduction
    assert 'intro intro-strong' in introduction
    payload = ready(client)
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_profile() is None
        assert not campaign.consent(store)
        assert session.scalar(select(Case)) is None
        assert session.get(AppSetting, setup_flow.DRAFT_KEY).encrypted
        assert 'Alex Example' not in session.get(AppSetting, setup_flow.DRAFT_KEY).value
    previews = client.get('/setup?step=4&preview=1').text
    assert 'Your request previews' in previews and 'ER-PREVIEW' in previews
    mailbox_page = client.get('/setup?step=3').text
    assert 'The app uses it for removal requests and replies' in mailbox_page
    assert 'for mine:)' in mailbox_page
    assert 'class="mailbox-actions"' in mailbox_page
    response = client.post('/setup/start', data=payload)
    assert response.status_code == 200 and response.url.path == '/dashboard', response.text
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        profile = store.get_profile()
        assert profile['email'] == 'requests@example.test'
        assert profile['other_emails'] == ['alex@example.test', 'work@example.test']
        assert store.get_signature() == 'Alex Example'
        assert not setup_flow.draft(store)
        saved = campaign.consent(store)
        assert saved['enabled'] and saved['include_new'] and saved['daily_limit'] == 20
        assert not saved['allow_postal'] and saved['country'] == 'DE'
        assert saved['plans']
        signature_version = session.get(Profile, 1).signature_version
        approved_at = saved['approved_at']
        assert session.scalar(select(AutomaticDelivery)) is None
    client.post('/setup/start', data=payload)
    assert client.get('/setup').url.path == '/dashboard'
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert session.get(Profile, 1).signature_version == signature_version
        assert campaign.consent(store)['approved_at'] == approved_at
        assert session.scalar(select(func.count()).select_from(Job).where(Job.kind == 'campaign_tick')) == 1
        workflow = Workflow(session, store, settings)
        campaign.tick(workflow)
        delivery = session.scalar(select(AutomaticDelivery))
        assert delivery is not None
        campaign.dispatch(workflow, delivery.id)
        assert delivery.status == 'sent'  # fake transport, same production dispatch path


def test_country_manual_exit_resume_and_field_errors(setup_app):
    client, settings, engine = setup_app
    csrf = hidden(client.get('/setup').text, 'csrf')
    assert 'Step 1 of 5' in client.get('/setup?step=4').text
    client.post('/setup/appearance', data={'csrf': csrf, 'theme': 'atelier'})
    invalid = client.post('/setup/country', data={'csrf': csrf, 'country': 'EEA'})
    assert invalid.status_code == 422 and 'Choose where you live' in invalid.text
    response = client.post('/setup/country', data={'csrf': csrf, 'country': 'GB'})
    assert 'Automatic emails aren’t available for United Kingdom' in response.text
    assert client.post('/setup/manual', data={'csrf': csrf}).url.path == '/quick-wins'
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_profile() is None and not store.get_setting('gmail_token')
        assert store.get_setting('recommendation_country') == 'GB'
    assert client.post('/login', data={'password': 'setup test password'}).url.path == '/dashboard'
    csrf = hidden(client.get('/dashboard').text, 'csrf')
    # Country remains editable, allowing a manual-only user to later start emails.
    response = client.post('/setup/country', data={'csrf': csrf, 'country': 'DE'})
    assert 'Step 3 of 5' in response.text
    result = client.post('/setup/details', data={'csrf': csrf, 'full_name': 'Alex Example', 'emails': 'not-email'})
    assert result.status_code == 422 and 'value="not-email"' in result.text
    result = client.post('/setup/details', data={'csrf': csrf, 'full_name': 'Alex', 'intent': 'exit'})
    assert result.url.path == '/dashboard'
    assert 'value="Alex"' in client.get('/setup').text
    assert 'Step 3 of 5' in client.get('/setup?step=4').text
    result = client.post('/setup/details', data={'csrf': csrf, 'full_name': 'Alex Example', 'no_matching_email': 'true'})
    assert 'Step 4 of 5' in result.text


def test_start_is_atomic_even_if_enable_fails_after_its_commits(setup_app, monkeypatch):
    client, settings, engine = setup_app
    payload = ready(client)
    original = campaign.enable
    def fail_after_enable(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic failure after internal commits')
    monkeypatch.setattr(campaign, 'enable', fail_after_enable)
    response = client.post('/setup/start', data=payload)
    assert response.status_code == 503 and 'nothing was authorized' in response.text
    assert 'synthetic failure' not in response.text
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_profile() is None
        assert not campaign.consent(store)
        assert setup_flow.draft(store)['full_name'] == 'Alex Example'
        assert session.scalar(select(Case)) is None
        assert session.scalar(select(Job)) is None
    monkeypatch.setattr(campaign, 'enable', original)
    assert client.post('/setup/start', data=payload).url.path == '/dashboard'


@pytest.mark.parametrize('problem', ['csrf', 'permission', 'signature', 'changed', 'worker', 'preview_mode', 'mailbox', 'no_routes'])
def test_start_failures_do_not_create_profile_or_grant_consent(setup_app, monkeypatch, problem):
    client, settings, engine = setup_app
    payload = ready(client)
    if problem == 'csrf':
        payload['csrf'] = 'incorrect'
    elif problem == 'permission':
        payload.pop('authorize')
    elif problem == 'signature':
        payload['signature'] = 'Someone else'
    elif problem == 'changed':
        client.post('/setup/details', data={'csrf': payload['csrf'], 'full_name': 'Alex Changed', 'emails': 'new@example.test'})
    elif problem == 'worker':
        client.app.state.worker_thread = None
    elif problem == 'preview_mode':
        settings.live_submissions = False
    elif problem == 'mailbox':
        monkeypatch.setattr(GmailClient, 'mailbox_address', lambda *a: 'different@example.test')
    else:
        original = setup_flow.preview
        monkeypatch.setattr(setup_flow, 'preview', lambda *args: ([], original(*args)[1]))
    result = client.post('/setup/start', data=payload)
    assert result.status_code in {403, 422}
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_profile() is None
        assert not campaign.consent(store)
        assert session.scalar(select(AutomaticDelivery)) is None


def test_mailbox_cancel_wrong_state_and_expired_local_session(setup_app):
    client, settings, engine = setup_app
    details(client)
    client.get('/gmail/connect?return_to=setup')
    response = client.get('/gmail/callback?error=access_denied')
    assert 'Gmail was not connected' in response.text
    response = client.get('/gmail/callback?code=fake&state=wrong')
    assert 'Gmail was not connected' in response.text
    client.cookies.clear()
    assert client.get('/gmail/callback?code=fake&state=wrong').url.path == '/login'
    result = client.post('/login', data={'password': 'setup test password'})
    assert 'Step 4 of 5' in result.text
    with Session(engine) as session:
        assert Store(session, Vault(settings.master_key)).get_profile() is None


def test_expired_setup_post_returns_to_unlock_without_writing(setup_app):
    client, settings, engine = setup_app
    csrf = details(client)
    client.cookies.clear()
    response = client.post('/setup/details', data={'csrf': csrf, 'full_name': 'Replacement', 'emails': 'new@example.test'})
    assert response.url.path == '/login'
    with Session(engine) as session:
        assert setup_flow.draft(Store(session, Vault(settings.master_key)))['full_name'] == 'Alex Example'


def test_google_file_import_is_validated_encrypted_and_never_echoed(setup_app):
    client, settings, engine = setup_app
    csrf = details(client)
    settings.demo_mode = False
    assert 'One-time Google setup' in client.get('/setup').text
    config = {'web': {'client_id': 'synthetic.apps.googleusercontent.com',
              'client_secret': 'synthetic-secret-not-a-real-key',
              'redirect_uris': [settings.base_url + '/gmail/callback']}}
    response = client.post('/setup/google-client', data={'csrf': csrf},
                           files={'client_file': ('client.json', json.dumps(config), 'application/json')})
    assert response.status_code == 200 and 'href="/gmail/connect?return_to=setup"' in response.text
    assert 'synthetic-secret' not in response.text
    with Session(engine) as session:
        record = session.get(AppSetting, 'gmail_client_config')
        assert record.encrypted and 'synthetic-secret' not in record.value
        store = Store(session, Vault(settings.master_key))
        assert GmailClient(settings, store).settings.google_client_id == config['web']['client_id']
    for bad in [{'installed': config['web']}, {'web': {**config['web'], 'redirect_uris': ['https://wrong.invalid']}}]:
        response = client.post('/setup/google-client', data={'csrf': csrf},
            files={'client_file': ('client.json', json.dumps(bad), 'application/json')})
        assert response.status_code == 422 and 'No credentials were changed' in response.text


def test_existing_profile_cannot_be_overwritten_by_wizard(setup_app):
    client, settings, engine = setup_app
    payload = ready(client)
    client.post('/setup/start', data=payload)
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        original = store.get_profile()
        approved = campaign.consent(store)
        store.set_setting('paused', 'true')
    for route, data in [('/setup/details', {'full_name': 'Replacement', 'emails': 'bad@example.test'}),
                        ('/setup/country', {'country': 'US'}), ('/setup/manual', {}), ('/setup/start', payload)]:
        assert client.post(route, data={**data, 'csrf': payload['csrf']}).url.path == '/dashboard'
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_profile() == original
        assert campaign.consent(store) == approved
        assert store.get_setting('paused') == 'true'


def test_token_refresh_at_start_preserves_verified_mailbox(setup_app, monkeypatch):
    client, settings, engine = setup_app
    payload = ready(client)
    def refresh_then_identity(self):
        self.store.set_setting('gmail_token', {'access_token': 'refreshed', 'refresh_token': 'same'}, encrypted=True)
        return 'requests@example.test'
    monkeypatch.setattr(GmailClient, 'mailbox_address', refresh_then_identity)
    response = client.post('/setup/start', data=payload)
    assert response.url.path == '/dashboard', response.text


def test_missing_offline_grant_does_not_finish_mailbox_step(setup_app, monkeypatch):
    client, _, _ = setup_app
    csrf = details(client)
    client.get('/gmail/connect?return_to=setup')
    def incomplete(self, *args, **kwargs):
        return {'access_token': 'no-refresh'}
    monkeypatch.setattr(GmailClient, 'exchange_code', incomplete)
    result = client.post('/demo/mailbox', data={'csrf': csrf})
    assert 'Gmail was not connected' in result.text and 'Step 4 of 5' in result.text


def test_mailbox_connection_failure_during_start_is_actionable(setup_app, monkeypatch):
    client, _, _ = setup_app
    payload = ready(client)
    def fail(self):
        raise GmailError('synthetic connection failure')
    monkeypatch.setattr(GmailClient, 'mailbox_address', fail)
    result = client.post('/setup/start', data=payload)
    assert result.status_code == 422 and 'Reconnect Gmail' in result.text
    assert 'synthetic connection failure' not in result.text


def test_reconnect_wrong_account_keeps_previous_token_and_profile(setup_app, monkeypatch):
    client, settings, engine = setup_app
    payload = ready(client)
    client.post('/setup/start', data=payload)
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        old_token = store.get_setting('gmail_token')
        old_profile = store.get_profile()
    client.get('/gmail/connect')
    def wrong_account(self, **kwargs):
        assert kwargs['access_token']
        # The background worker still sees the original token during verification.
        assert self.store.get_setting('gmail_token') == old_token
        return 'wrong-account@example.test'
    monkeypatch.setattr(GmailClient, 'mailbox_address', wrong_account)
    response = client.post('/demo/mailbox', data={'csrf': hidden(client.get('/campaign').text, 'csrf')})
    assert 'different Gmail account' in response.text
    with Session(engine) as session:
        store = Store(session, Vault(settings.master_key))
        assert store.get_setting('gmail_token') == old_token
        assert store.get_profile() == old_profile


def test_reconnect_cancel_keeps_previous_connection(setup_app):
    client, settings, engine = setup_app
    payload = ready(client)
    client.post('/setup/start', data=payload)
    with Session(engine) as session:
        previous = Store(session, Vault(settings.master_key)).get_setting('gmail_token')
    response = client.get('/gmail/callback?error=access_denied')
    assert response.url.path == '/campaign'
    assert 'previous connection and saved requests were kept' in response.text
    with Session(engine) as session:
        assert Store(session, Vault(settings.master_key)).get_setting('gmail_token') == previous
