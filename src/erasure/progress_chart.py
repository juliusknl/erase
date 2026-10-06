"""Read-only cumulative request history, with shared time and count scales."""

from collections import Counter
from datetime import UTC, datetime, timedelta


def utc_day(stamp):
    return (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)).date()


def dated_counts(stamps, today):
    days = Counter()
    undated = 0
    for stamp in stamps:
        if stamp is None or utc_day(stamp) > today:
            undated += 1
        else:
            days[utc_day(stamp)] += 1
    return days, undated


def series(days, start, span, maximum):
    path = ['M 0 108']
    count = 0
    points = []
    for day, amount in sorted(days.items()):
        count += amount
        x, y = 1000 * (day - start).days / span, 108 - 96 * count / maximum
        path.append(f'H {x:.2f} V {y:.2f}')
        points.append(dict(date=day.isoformat(), count=count))
    path.append('H 1000')
    return ' '.join(path), points


def completion_chart(completed_dates, *, sent_dates=(), started_at=None, today=None):
    today = today or datetime.now(UTC).date()
    completed, undated = dated_counts(completed_dates, today)
    sent, sent_undated = dated_counts(sent_dates, today)
    total, sent_total = sum(completed.values()), sum(sent.values())
    maximum = max(total, sent_total)
    missing = []
    if undated:
        missing.append(f'{undated} completed')
    if sent_undated:
        missing.append(f'{sent_undated} sent')
    missing_note = ''
    if missing:
        noun, verb = ('request', 'is') if undated + sent_undated == 1 else ('requests', 'are')
        missing_note = f'{" and ".join(missing)} {noun} without usable dates {verb} not plotted.'
    result = dict(total=total, sent_total=sent_total, maximum=maximum,
                  undated=undated, sent_undated=sent_undated,
                  path='M 0 108 H 1000', sent_path='M 0 108 H 1000', points=[], sent_points=[],
                  start='', end='', description='',
                  missing_note=missing_note)
    if not maximum:
        return result
    start = min([*completed, *sent]) - timedelta(days=1)
    if started_at:
        start = min(start, utc_day(started_at))
    span = max(1, (today - start).days)
    result['path'], result['points'] = series(completed, start, span, maximum)
    result['sent_path'], result['sent_points'] = series(sent, start, span, maximum)
    fmt = '%d %b %Y' if start.year != today.year else '%d %b'
    result.update(start=start.strftime(fmt).lstrip('0'), end=today.strftime(fmt).lstrip('0'))
    result['description'] = (f'{sent_total} sent and {total} currently completed requests with recorded dates, '
                             f'from {result["start"]} to {result["end"]}. '
                             'Completed includes manual steps and no-match replies, not only confirmed deletions.')
    return result
