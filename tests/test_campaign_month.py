"""A synthetic month through the real scheduler, inbox, consent and delivery ledger.

Only the clock, Gmail transport and optional AI provider are replaced. No live
mailbox, keys, OS services or network are used.
"""

import sys
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from test_campaign import setup_campaign
from test_inbox import make_case

from erasure import campaign, worker
from erasure.gmail import GmailClient, GmailError
from erasure.inbox import poll_mailbox
from erasure.jev import JevError
from erasure.models import AutomaticDelivery, Case, IncomingMessage, Job
from erasure.store import Store


@pytest.fixture
def clock(monkeypatch):
    class Clock(datetime):
        current = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    for name, module in list(sys.modules.items()):
        if name.startswith('erasure.') and getattr(module, 'datetime', None) is datetime:
            monkeypatch.setattr(module, 'datetime', Clock)
    return Clock


def test_malformed_link_and_poison_message_do_not_block_other_mail(db, vault, monkeypatch, clock):
    case, workflow = make_case(db, vault)
    original = workflow.process_message
    calls = Counter()
    def processing(message, **kwargs):
        calls[message['id']] += 1
        if message['id'] == 'poison':
            raise ValueError('private contents must not appear in diagnostics')
        return original(message, **kwargs)
    monkeypatch.setattr(workflow, 'process_message', processing)
    class Mailbox:
        def list_recent(self):
            return ['good', 'malformed', 'poison']

        def read_message(self, mid):
            return {'id': mid, 'subject': f'ER-{case.id:06X}',
                    'from': 'privacy@sample.test',
                    'authentication_results': 'mx.google.com; dmarc=pass header.from=sample.test',
                    'body': ('Please complete our privacy request form: https://[broken/privacy-request'
                             if mid == 'malformed' else 'We received your request.')}
    for _ in range(5):
        poll_mailbox(workflow, Mailbox())
        clock.current += timedelta(hours=1)
    assert calls['poison'] == 3
    assert calls['good'] == calls['malformed'] == 1
    assert db.get(IncomingMessage, 'good').status == 'processed'
    assert db.get(IncomingMessage, 'malformed').status == 'processed'
    assert db.get(IncomingMessage, 'poison').status == 'review'
    assert workflow.store.get_setting('gmail_last_sync')
    assert workflow.store.get_setting('mail_processing:poison')['error'] == 'ValueError'


def test_wake_preserves_live_lease_and_deduplicates_recurring_jobs(db, vault, clock):
    store = Store(db, vault)
    store.set_setting('gmail_token', {'synthetic': True}, encrypted=True)
    active = store.enqueue('poll_gmail', {})
    active.status = 'running'
    active.lease_until = clock.current + timedelta(minutes=2)
    store.enqueue('poll_gmail', {})
    worker.recover_schedules(store)
    assert active.status == 'running'
    assert len(list(db.scalars(select(Job).where(Job.kind == 'poll_gmail', Job.status != 'cancelled')))) == 1
    clock.current += timedelta(days=2)
    worker.recover_schedules(store)
    assert active.status == 'pending'
    assert store.claim_job()[0].id == active.id


def test_thirty_day_campaign(db, vault, master_key, monkeypatch, clock):
    workflow = setup_campaign(db, vault, count=30, limit=3)
    settings = workflow.settings.model_copy(update={
        'master_key': master_key, 'password_hash': 'synthetic', 'session_secret': 'synthetic'})
    workflow.settings = settings
    sessions = sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(worker, 'SessionLocal', sessions)
    monkeypatch.setattr(worker, 'get_settings', lambda: settings)
    origin = clock.current
    sent, mail = [], {}
    disconnected = False
    ai_attempts = []

    class ExhaustedAI:
        def __init__(self, *args):
            pass

        def classify(self, *args, **kwargs):
            ai_attempts.append(clock.current)
            raise JevError('http_402')

        def close(self):
            pass

    monkeypatch.setattr('erasure.reply_interpretation.JevClassifier', ExhaustedAI)
    workflow.store.set_setting('reply_assistance', {'enabled': True, 'api_key': 'synthetic'}, encrypted=True)

    def send(_client, plan):
        assert not disconnected
        sent.append((clock.current, plan.destination))
        index = len(sent)
        domain = plan.destination.split('@')[1]
        base = {'subject': plan.subject, 'from': plan.destination,
                'authentication_results': f'mx.google.com; dmarc=pass header.from={domain}'}
        # Receipts during sleep, a delayed deletion and a still-pending broker.
        mail[f'receipt-{index}'] = (clock.current + timedelta(hours=1), {
            **base, 'id': f'receipt-{index}', 'body': 'We received your request and will process it within 30 days.'})
        if index != 1:
            delay = 20 if index == 2 else 3
            mail[f'outcome-{index}'] = (clock.current + timedelta(days=delay), {
                **base, 'id': f'outcome-{index}', 'body': 'Your data has been deleted.'})
        return f'gmail-thread:synthetic-{index}'

    def list_recent(_client):
        if disconnected:
            raise GmailError('Synthetic disconnected Gmail')
        return list(reversed([mid for mid, (at, _) in mail.items() if at <= clock.current]))

    monkeypatch.setattr(GmailClient, 'send', send)
    monkeypatch.setattr(GmailClient, 'list_recent', list_recent)
    monkeypatch.setattr(GmailClient, 'read_message', lambda _, mid: dict(mail[mid][1]))

    for day in range(30):
        if day in {1, 2, 12, 13, 14}:
            continue  # Sleeping/off: no jobs execute.
        disconnected = day in {5, 6, 7}
        clock.current = origin + timedelta(days=day)
        with sessions() as session:
            worker.recover_schedules(Store(session, vault))
        for minute in range(7):
            clock.current = origin + timedelta(days=day, minutes=minute)
            for _ in range(18):
                if not worker.run_once():
                    break
        with sessions() as session:
            deliveries = list(session.scalars(select(AutomaticDelivery)))
            counts = Counter(row.started_at.date() for row in deliveries if row.started_at)
            assert all(count <= 3 for count in counts.values())

    db.expire_all()
    assert len(sent) == 30
    assert len({destination for _, destination in sent}) == 30
    assert all((b[0] - a[0]).total_seconds() >= 60 for a, b in zip(sent, sent[1:], strict=False))
    assert not any((at - origin).days in {1, 2, 5, 6, 7, 12, 13, 14} for at, _ in sent)
    states = Counter(case.state for case in db.scalars(select(Case)))
    assert states == {'removed': 29, 'processing': 1}
    assert len(list(db.scalars(select(IncomingMessage)))) == 59
    assert all(record.status == 'processed' for record in db.scalars(select(IncomingMessage)))
    assert ai_attempts and workflow.store.get_setting('jev_health')['error'] == 'http_402'
    assert workflow.store.get_setting('gmail_error') == ''
    assert not list(db.scalars(select(Job).where(Job.status == 'failed')))
    assert all(row.status == 'sent' for row in db.scalars(select(AutomaticDelivery)))


def test_completed_reply_is_processed_before_overdue_followup(db, vault, master_key, monkeypatch, clock):
    case, workflow = make_case(db, vault)
    workflow.store.set_setting('gmail_token', {'synthetic': True}, encrypted=True)
    overdue = workflow.store.enqueue('follow_up', {'case_id': case.id}, run_at=clock.current - timedelta(days=10))
    worker.recover_schedules(workflow.store)
    settings = workflow.settings.model_copy(update={
        'master_key': master_key, 'password_hash': 'synthetic', 'session_secret': 'synthetic'})
    monkeypatch.setattr(worker, 'get_settings', lambda: settings)
    monkeypatch.setattr(worker, 'SessionLocal', sessionmaker(db.bind, expire_on_commit=False))
    monkeypatch.setattr(GmailClient, 'list_recent', lambda _: ['complete'])
    monkeypatch.setattr(GmailClient, 'read_message', lambda _, mid: {
        'id': mid, 'subject': f'ER-{case.id:06X}', 'body': 'Your data has been deleted.',
        'from': 'privacy@sample.test', 'authentication_results': 'mx.google.com; dmarc=pass header.from=sample.test'})
    monkeypatch.setattr(GmailClient, 'send', lambda *args: pytest.fail('Unnecessary follow-up'))
    assert worker.run_once()
    db.expire_all()
    assert case.state == 'removed'
    assert overdue.status == 'cancelled'


def test_uncertain_delivery_after_crash_never_blindly_resends(db, vault, monkeypatch, clock):
    workflow = setup_campaign(db, vault, count=1)
    campaign.tick(workflow)
    delivery = db.scalar(select(AutomaticDelivery))
    delivery.status, delivery.started_at = 'sending', clock.current
    db.commit()
    clock.current += timedelta(days=3)
    monkeypatch.setattr(GmailClient, 'send', lambda *args: pytest.fail('Duplicate send'))
    campaign.dispatch(workflow, delivery.id)
    campaign.dispatch(workflow, delivery.id)
    assert delivery.status == 'uncertain'
    assert db.get(Case, delivery.case_id).state == 'needs_action'


@pytest.mark.parametrize('status', [404, 410, 401, 429, 503])
def test_deleted_message_isolated_but_provider_errors_preserve_checkpoint(db, vault, status):
    case, workflow = make_case(db, vault)
    workflow.store.set_setting('gmail_last_sync', '2026-01-01T00:00:00+00:00')
    class Mailbox:
        def list_recent(self):
            return ['good', 'missing']

        def read_message(self, mid):
            if mid == 'missing':
                response = httpx.Response(status, request=httpx.Request('GET', 'https://mail.example.test'))
                response.raise_for_status()
            return {'id': mid, 'subject': f'ER-{case.id:06X}', 'body': 'We received your request.',
                    'from': 'privacy@sample.test', 'authentication_results': 'mx.google.com; dmarc=pass header.from=sample.test'}
    if status in {404, 410}:
        poll_mailbox(workflow, Mailbox())
        assert db.get(IncomingMessage, 'good').status == 'processed'
        assert db.get(IncomingMessage, 'missing') is not None
        assert workflow.store.get_setting('gmail_last_sync') != '2026-01-01T00:00:00+00:00'
    else:
        with pytest.raises(httpx.HTTPStatusError):
            poll_mailbox(workflow, Mailbox())
        assert workflow.store.get_setting('gmail_last_sync') == '2026-01-01T00:00:00+00:00'
