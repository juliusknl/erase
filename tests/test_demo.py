import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure import campaign
from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault
from erasure.db import create_db_engine
from erasure.demo import DEMO_PASSWORD, demo_environment, deny_outbound_connections, localize_links
from erasure.gmail import GmailClient
from erasure.inbox import poll_mailbox
from erasure.models import AppSetting, AutomaticDelivery, Case, IncomingMessage, Profile
from erasure.reply_interpretation import enabled
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


def hidden(page, name):
    return re.search(r'name="' + name + r'" value="([^"]*)"', page).group(1)


@pytest.fixture
def demo(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError('Demo must never reach a real HTTP transport')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', no_network)
    for key, value in demo_environment(tmp_path, 8788).items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None, catalog_dir=ROOT / 'catalog',
                        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static')
    engine = create_db_engine(settings.database_url)
    with TestClient(create_app(settings, engine)) as client:
        yield client, settings, engine
    engine.dispose()


def test_fresh_demo_full_journey_and_synthetic_mail(demo):
    client, settings, engine = demo
    page = client.get('/login')
    assert DEMO_PASSWORD in page.text
    client.post('/login', data={'password': DEMO_PASSWORD})
    setup = client.get('/setup').text
    assert 'Make it yours.' in setup
    assert 'class="demo-note"' not in setup
    assert 'Demo · nothing is sent' not in setup
    assert 'erasure_demo_session' in client.cookies
    assert 'erasure_session' not in client.cookies
    assert client.get('/health').json()['demo_mode'] is True
    with Session(engine) as db:
        assert db.get(Profile, 1) is None
        assert db.scalar(select(Case)) is None
    page = client.get('/onboarding').text
    csrf = hidden(page, 'csrf')
    client.post('/recommendations/country', data={'csrf': csrf, 'country': 'DE', 'return_to': '/onboarding'})
    client.post('/onboarding', data={'csrf': csrf, 'full_name': 'Alex Example',
        'email': 'requests@example.test', 'other_emails': 'alex@example.test', 'signature': 'Alex Example'})
    assert client.get('/gmail/connect').url.path == '/demo/mailbox'
    client.post('/demo/mailbox', data={'csrf': csrf})
    page = client.get('/campaign').text
    result = client.post('/campaign/automatic', data={'csrf': csrf, 'country': 'DE',
        'preview_hash': hidden(page, 'preview_hash'), 'authorize': 'true',
        'include_new': 'true', 'daily_limit': 6})
    assert 'saved=1' in str(result.url)
    with Session(engine, expire_on_commit=False) as db:
        store = Store(db, Vault(settings.master_key))
        workflow = Workflow(db, store, settings)
        campaign.tick(workflow)
        deliveries = list(db.scalars(select(AutomaticDelivery)))
        assert len(deliveries) == 6
        for delivery in deliveries:
            campaign.dispatch(workflow, delivery.id)
        assert all(d.status == 'sent' for d in deliveries)
        assert store.get_setting('demo_send_count') == '6'
        # Receipts/outcomes are delayed, not injected before the user sends.
        poll_mailbox(workflow, GmailClient(settings, store))
        assert db.scalar(select(IncomingMessage)) is None
        for key in list(db.scalars(select(AppSetting.key).where(AppSetting.key.like('demo_mail:%')))):
            mail = store.get_setting(key)
            mail['available_at'] = (datetime.now(UTC) - timedelta(seconds=2 if key.endswith('receipt') else 1)).isoformat()
            store.set_setting(key, mail, encrypted=True)
        poll_mailbox(workflow, GmailClient(settings, store))
        states = [db.get(Case, d.case_id).state for d in deliveries]
        assert states == ['removed', 'not_found', 'needs_action', 'needs_action', 'needs_action', 'needs_action']
        assert len(list(db.scalars(select(IncomingMessage)))) == 12
        poll_mailbox(workflow, GmailClient(settings, store))
        assert len(list(db.scalars(select(IncomingMessage)))) == 12
        form_case = deliveries[2].case_id
    page = client.get(f'/cases/{form_case}').text
    assert '/demo/external?' in page
    assert not re.search(r'href=[\"\']https?://', page)
    page = client.get('/demo/external?destination=https://broker.invalid/form').text
    assert 'No external site was contacted' in page
    assert 'Demo · nothing is sent' not in page
    assert '<h1>Demo step</h1>' in page
    assert not enabled(settings.model_copy(update={'jev_enabled': True}))


def test_demo_connection_requires_login_and_csrf(demo):
    client, _, _ = demo
    assert client.post('/demo/mailbox', data={'csrf': 'bad'}).status_code == 401
    client.post('/login', data={'password': DEMO_PASSWORD})
    assert client.post('/demo/mailbox', data={'csrf': 'bad'}).status_code == 403


def test_demo_credentials_persist_and_do_not_use_existing_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('ERASURE_MASTER_KEY', 'real-key-must-not-be-used')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'real-provider-key')
    first = demo_environment(tmp_path, 8788)
    second = demo_environment(tmp_path, 8788)
    assert first == second
    assert first['ERASURE_MASTER_KEY'] != 'real-key-must-not-be-used'
    assert first['TYPESAFE_API_KEY'] == ''
    assert first['ERASURE_DATABASE_URL'].endswith('/demo.db')
    assert (tmp_path / 'demo-secrets.json').stat().st_mode & 0o777 == 0o600


def test_demo_external_links_are_replaced_not_just_click_intercepted():
    markup = '<a href="https://broker.test/form?a=1&amp;b=2">Form</a><a href=\'https://mail.google.com/\'>Mail</a><a href="/dashboard">Home</a>'
    result = localize_links(markup)
    assert 'href="/dashboard"' in result
    assert result.count('/demo/external?') == 2
    assert 'href="https://' not in result and "href='https://" not in result


def test_demo_allows_only_exact_google_signup_link():
    signup = '<a href="https://accounts.google.com/signup" target="_blank" rel="noopener noreferrer">Create Gmail</a>'
    assert localize_links(signup) == signup
    for destination in ('https://accounts.google.com/signup?continue=https://broker.test',
                        'https://accounts.google.com.evil.test/signup',
                        'https://broker.test/form', 'https://accounts.google.com/other'):
        assert '/demo/external?' in localize_links(f'<a href="{destination}">Open</a>')


def test_demo_flag_cannot_target_normal_database():
    with pytest.raises(ValueError, match='own SQLite demo.db'):
        Settings(_env_file=None, demo_mode=True, database_url='sqlite:///data/erasure.db')


@pytest.mark.parametrize('event', ['socket.connect', 'socket.getaddrinfo', 'socket.sendto'])
def test_demo_network_guard_blocks_outbound_connections(event):
    with pytest.raises(PermissionError, match='Outbound networking is disabled'):
        deny_outbound_connections(event, ())
    deny_outbound_connections('socket.__new__', ())
