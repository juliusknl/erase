from datetime import UTC, datetime, timedelta

import pytest

from erasure.app import sending_activity
from erasure.models import Broker, Case, Event


def plan():
    return dict(today=0, daily_limit=20, planned_count=1, include_new=True,
                queued_count=0, sending_count=0)


def test_last_send_uses_success_events_not_current_case_state(db):
    broker = Broker(slug='receipt', name='Example Broker')
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state='needs_action')
    db.add(case)
    db.flush()
    now = datetime.now(UTC)
    db.add_all([
        Event(case_id=case.id, kind='submitted', summary='Sent', created_at=now - timedelta(days=1)),
        Event(case_id=case.id, kind='reply_sent', summary='Follow-up', created_at=now - timedelta(minutes=5)),
        Event(case_id=case.id, kind='request_prepared', summary='Not sent', created_at=now),
        Event(case_id=case.id, kind='form_submitted', summary='Manual step', created_at=now),
    ])
    db.flush()
    result = sending_activity(db, plan(), {'state': 'running'})
    assert result['last_sent'] == 'Last sent: follow-up to Example Broker · 5 minutes ago.'
    assert result['next_step'] == ''
    assert 'Last simulated send:' in sending_activity(db, plan(), {'state': 'running'}, demo=True)['last_sent']
    assert [entry['message'] for entry in result['entries']] == ['Request sent', 'Follow-up sent']
    assert result['entries'][-1]['sent_at'].endswith('+00:00')


def test_feed_is_bounded_chronological_and_stable_for_same_timestamp(db):
    broker = Broker(slug='feed', name='<b>A long broker name</b>')
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state='submitted')
    db.add(case)
    db.flush()
    now = datetime.now(UTC)
    events = [Event(case_id=case.id, kind='submitted', summary='Sent', created_at=now) for _ in range(5)]
    db.add_all(events)
    db.flush()
    result = sending_activity(db, plan(), {'state': 'running'})
    assert [entry['id'] for entry in result['entries']] == [event.id for event in events[-3:]]
    assert result['entries'][0]['broker'] == broker.name
    assert sending_activity(db, plan(), {'state': 'running'}) == result


@pytest.mark.parametrize('state,changes,expected', [
    ('paused', {'queued_count': 3}, 'Sending paused.'),
    ('stopped', {}, 'Automatic sending is off.'),
    ('blocked', {'queued_count': 3}, 'Gmail needs reconnection.'),
    ('running', {'today': 20, 'queued_count': 3}, 'Daily sending limit reached.'),
    ('running', {'today': 20, 'sending_count': 1}, 'An email is being sent;'),
    ('running', {'queued_count': 3}, 'More requests are queued'),
    ('running', {'research_due': 2}, 'Preparing more eligible'),
    ('running', {'new_workflows': 2, 'include_new': False}, 'New email requests are waiting for your permission.'),
    ('running', {'route_issues': [{}]}, 'Remaining email routes need review'),
    ('running', {'planned_count': 0}, 'No email requests currently match'),
])
def test_accurate_idle_reasons_and_empty_history(db, state, changes, expected):
    automatic = plan() | changes
    result = sending_activity(db, automatic, {'state': state, 'detail': 'Gmail needs reconnection'})
    assert result['last_sent'] == 'No emails sent yet.'
    assert result['entries'] == []
    assert result['next_step'].startswith(expected)
