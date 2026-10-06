from datetime import UTC, date, datetime, timedelta

from erasure.progress_chart import completion_chart


def test_completion_dates_are_aggregated_not_interpolated():
    first = datetime(2026, 9, 10, tzinfo=UTC)
    result = completion_chart([first, first, first + timedelta(days=3)], today=date(2026, 9, 20))
    assert result['total'] == 3
    assert result['points'] == [{'date': '2026-09-10', 'count': 2}, {'date': '2026-09-13', 'count': 3}]
    assert result['path'].startswith('M 0 108 H ') and result['path'].endswith('V 12.00 H 1000')
    assert result['start'] == '9 Sep' and result['end'] == '20 Sep'


def test_empty_undated_and_future_completions_do_not_invent_history():
    assert completion_chart([])['points'] == []
    result = completion_chart([None, datetime(2027, 1, 1)], today=date(2026, 10, 1))
    assert result['total'] == result['maximum'] == 0
    assert result['undated'] == 2 and result['points'] == []


def test_first_day_and_cross_year_dates_have_valid_scales():
    stamp = datetime(2026, 1, 1)
    result = completion_chart([stamp], started_at=stamp, today=stamp.date())
    assert result['total'] == 1
    assert result['start'] == '31 Dec 2025' and result['end'] == '1 Jan 2026'
    assert result['path'] == 'M 0 108 H 1000.00 V 12.00 H 1000'


def test_sent_and_completed_use_the_same_axes():
    start = datetime(2026, 9, 10, tzinfo=UTC)
    result = completion_chart([start + timedelta(days=2)], sent_dates=[start, start], today=date(2026, 9, 20))
    assert result['sent_total'] == result['maximum'] == 2
    assert result['total'] == 1
    assert result['sent_path'].endswith('V 12.00 H 1000')
    assert result['path'].endswith('V 60.00 H 1000')
    assert result['start'] == '9 Sep'
    assert result['sent_points'] == [{'date': '2026-09-10', 'count': 2}]


def test_sent_only_and_manual_only_progress():
    stamp = datetime(2026, 9, 10)
    result = completion_chart([], sent_dates=[stamp], today=stamp.date())
    assert result['maximum'] == 1 and result['path'] == 'M 0 108 H 1000'
    result = completion_chart([stamp, stamp], sent_dates=[stamp], today=stamp.date())
    assert result['maximum'] == 2 and result['sent_path'].endswith('V 60.00 H 1000')


def test_invalid_send_dates_are_not_plotted():
    result = completion_chart([], sent_dates=[None, datetime(2027, 1, 1)], today=date(2026, 10, 1))
    assert result['maximum'] == 0 and result['sent_undated'] == 2
    assert result['sent_points'] == []


def test_dashboard_counts_first_send_once_and_only_current_completions(db):
    from erasure.app import request_progress
    from erasure.models import Broker, Case, Event

    first = datetime.now(UTC) - timedelta(days=5)
    for index, state in enumerate(['removed', 'submitted', 'needs_action']):
        broker = Broker(slug=f'chart-{index}', name=f'Chart {index}')
        db.add(broker)
        db.flush()
        case = Case(broker_id=broker.id, state=state, created_at=first,
                    completed_at=first + timedelta(days=2))
        db.add(case)
        db.flush()
        for day in (0, 1):
            db.add(Event(case_id=case.id, kind='submitted', summary='Sent', created_at=first + timedelta(days=day)))
        db.add(Event(case_id=case.id, kind='request_prepared', summary='Draft'))
    db.commit()
    chart = request_progress(db)
    assert chart['sent_total'] == chart['maximum'] == 3
    assert chart['sent_points'] == [{'date': first.date().isoformat(), 'count': 3}]
    assert chart['total'] == 1  # Reopened/non-completed requests must not count as done.
