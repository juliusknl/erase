import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from erasure.app import create_app
from erasure.attention import email_only_identity
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import Approval, Broker, Case

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(('kind', 'payload'), [
    ('identity_proof', {'body': 'Please verify your identity.'}),
    ('unverified_sender', {'proposed_kind': 'identity_requested',
                           'message': {'body': 'Complete identity verification.'}}),
    ('information_requested', {'body': 'Please provide signed authorization to act on their behalf.'}),
])
def test_email_only_ui_and_server_reject_documents_and_replies(tmp_path, master_key, monkeypatch, kind, payload):
    def never_send(*args, **kwargs):
        raise AssertionError('Identity handling must not send through the app')
    monkeypatch.setattr('erasure.gmail.GmailClient.send', never_send)
    engine = create_db_engine(f'sqlite:///{tmp_path / "identity.db"}')
    settings = Settings(_env_file=None, master_key=master_key, live_submissions=True,
                        password_hash=hash_password('test password'),
                        session_secret=generate_session_secret(), templates_dir=ROOT / 'templates',
                        static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    vault = Vault(master_key)
    with TestClient(create_app(settings, engine)) as client:
        client.post('/login', data={'password': 'test password'})
        with Session(engine, expire_on_commit=False) as db:
            broker = Broker(slug='identity-test', name='Identity Test', domain='identity.test',
                            contact='privacy@identity.test')
            db.add(broker)
            db.flush()
            case = Case(broker_id=broker.id, state='needs_action', submitted_at=datetime.now(UTC))
            db.add(case)
            db.flush()
            # Even a previously stored attachment must not be sendable.
            payload['artifact'] = {'data': 'old-artifact', 'filename': 'old.pdf'}
            action = Approval(case_id=case.id, kind=kind, summary='Verification needed',
                              encrypted_payload=vault.encrypt(payload))
            db.add(action)
            db.commit()
            cid, aid, original = case.id, action.id, action.encrypted_payload
        for tab in ['overview', 'conversation', 'details&correct=1']:
            page = client.get(f'/cases/{cid}?tab={tab}')
            assert page.status_code == 200
            assert 'Open message in Gmail' in page.text
            assert 'type="file"' not in page.text
            assert 'Send redacted identity document' not in page.text
            assert f'action="/cases/{cid}/reply"' not in page.text
        csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', page.text).group(1)
        upload = client.post(f'/actions/{aid}/identity', data={'csrf': csrf},
                             files={'document': ('id.pdf', b'%PDF-DO-NOT-STORE', 'application/pdf')})
        assert upload.status_code == (409 if kind == 'identity_proof' else 404)
        assert client.post(f'/actions/{aid}/resolve/approve', data={'csrf': csrf}).status_code == 409
        assert client.post(f'/cases/{cid}/reply', data={
            'csrf': csrf, 'destination': 'privacy@identity.test', 'body': 'Sensitive response',
        }).status_code == 409
        with Session(engine) as db:
            assert db.get(Approval, aid).encrypted_payload == original
            assert db.get(Approval, aid).status == 'pending'
            assert db.get(Case, cid).state == 'needs_action'
    engine.dispose()


def test_normal_confirmation_and_quoted_authorization_do_not_use_email_only_handoff():
    action = SimpleNamespace(kind='confirmation_link')
    assert not email_only_identity(action, {'body': 'Please confirm your email address.'})
    assert not email_only_identity(action, {'body':
        'We received your request.\nOn Monday someone wrote:\nPlease provide signed authorization.'})
    assert not email_only_identity(action, {'body': 'Please do not send government-issued identification.'})
    assert not email_only_identity(action, {'body': 'We do not require proof of identity.'})
    assert email_only_identity(action, {'body': 'Please provide:\n(1) signed authorization.'})
