import copy
import json
import sqlite3
from pathlib import Path

import httpx
import pytest

from erasure.jev import (
    CRITERIA,
    ENDPOINT,
    MAX_TEXT_CHARS,
    MODEL,
    JevClassifier,
    JevError,
    parse_reply,
    reply_state,
    saved_private_values,
)
from erasure.jev_eval import evaluate, inbox_samples, main
from erasure.replies import ReplyKind

FIXTURES = Path(__file__).parent / 'fixtures' / 'jev_replies.json'


def response_data(kind='confirmation'):
    return {'model': MODEL, 'usage': {'input_tokens': 1000, 'output_tokens': 100},
            'answers': {'reply_kind': {'type': 'choice', 'choice': kind,
                'confidence': 1, 'probabilities': {k: int(k == kind) for k in CRITERIA}}}}


def test_request_uses_pinned_model_and_existing_labels_with_minimized_data():
    calls = []

    def send(request):
        calls.append(request)
        assert str(request.url) == ENDPOINT
        payload = json.loads(request.content)
        assert payload['model'] == MODEL
        assert set(payload['questions']['reply_kind']['criteria']) == {k.value for k in ReplyKind}
        assert set(payload['state']) == {'subject', 'body'}
        assert payload['state']['body'] == 'Dear [saved detail], we received your request for [email]. Confirm at [link]'
        assert 'secret-token' not in request.content.decode()
        return httpx.Response(200, json=response_data())

    client = JevClassifier('test-key', transport=httpx.MockTransport(send))
    try:
        reply = client.classify('Request ER-123456',
            'Dear Example Person, we received your request for private@example.test. '
            'Confirm at https://broker.test/confirm?secret-token=123\nOn Monday you wrote:\nOld data',
            private_values=('Example Person',))
        assert reply.kind == ReplyKind.CONFIRMATION
        assert reply.input_tokens == 1000
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize('mutate', [
    lambda d: d.update(answers={}),
    lambda d: d['answers']['reply_kind'].update(choice='send_passport'),
    lambda d: d['answers']['reply_kind'].update(type='noul'),
    lambda d: d['answers']['reply_kind'].update(confidence=float('nan')),
    lambda d: d['answers']['reply_kind'].update(confidence=True),
    lambda d: d['answers']['reply_kind'].update(confidence=1.1),
    lambda d: d['answers']['reply_kind']['probabilities'].update(completed=-1),
    lambda d: d['answers']['reply_kind']['probabilities'].update(completed=float('inf')),
    lambda d: d['answers']['reply_kind']['probabilities'].update(completed=0.5),
    lambda d: d['answers']['reply_kind']['probabilities'].pop('ambiguous'),
    lambda d: d['answers']['reply_kind'].update(choice='completed'),
    lambda d: d['usage'].update(input_tokens=-1),
    lambda d: d['usage'].update(input_tokens=True),
    lambda d: d.update(model='private@email.test'),
])
def test_malformed_provider_results_are_rejected(mutate):
    data = response_data()
    mutate(data)
    with pytest.raises(JevError, match='^invalid_response$'):
        parse_reply(data)


@pytest.mark.parametrize('status', [301, 401, 403, 429, 500, 503])
def test_provider_errors_are_safe_and_never_retry_or_redirect(status):
    calls = []

    def send(request):
        calls.append(request)
        return httpx.Response(status, text='SECRET_PRIVATE_CONTENT', headers={'Location': 'https://other.test'})

    client = JevClassifier('secret-key', transport=httpx.MockTransport(send))
    try:
        with pytest.raises(JevError, match=f'^http_{status}$'):
            client.classify('', 'Received your request')
        assert len(calls) == 1
    finally:
        client.close()


def test_timeout_is_safe():
    def send(request):
        raise httpx.ReadTimeout('private body and key', request=request)

    client = JevClassifier('test-key', transport=httpx.MockTransport(send))
    try:
        with pytest.raises(JevError, match='^provider_unavailable$'):
            client.classify('', 'Received')
    finally:
        client.close()


def test_bad_json_is_safe():
    client = JevClassifier('test-key', transport=httpx.MockTransport(lambda _: httpx.Response(200, text='private')))
    try:
        with pytest.raises(JevError, match='^invalid_response$'):
            client.classify('', 'Received')
    finally:
        client.close()


def test_empty_overlong_and_missing_key_do_not_call_provider():
    with pytest.raises(JevError, match='missing_api_key'):
        JevClassifier('')
    client = JevClassifier('test-key', transport=httpx.MockTransport(lambda _: pytest.fail('No network expected')))
    try:
        with pytest.raises(JevError, match='empty_reply'):
            client.classify('Deletion complete', '')
        with pytest.raises(JevError, match='reply_too_long'):
            client.classify('', 'x' * (MAX_TEXT_CHARS + 1))
    finally:
        client.close()


def test_profile_redaction_and_quotes_leave_status_evidence():
    private = saved_private_values({'full_name': 'Example Person', 'postal_address': '123 Private Street',
                                   'other_emails': ['alias@example.test'], 'country': 'DE'})
    state = reply_state('Re: ER-000001', 'Hello Person,\nYour information will be deleted in 30 days. '
        '123\nPrivate Street. +49 123 456789. alias@example.test\n> Already deleted', private)
    body = state['body']
    assert '30 days' in body
    for value in ['Person', 'Private', 'alias@example.test', '+49 123', 'Already deleted']:
        assert value not in body
    assert 'ER-000001' not in state['subject']


@pytest.mark.parametrize('separator', [
    "-----Ursprüngliche Nachricht-----", "-----Message d'origine-----",
    'czw., 10 wrz 2026 o 11:27 Example Person <person@example.test> napisał(a):',
])
def test_localized_quoted_messages_are_not_sent(separator):
    state = reply_state('Ticket #1234567 [L52R39-6PL4J]',
                        f'We are processing your request.\n{separator}\nYour data has been deleted.')
    assert state['body'] == 'We are processing your request.'
    assert '1234567' not in state['subject'] and 'L52R39' not in state['subject']


def test_read_only_inbox_excludes_unmatched_mail_and_does_not_create_database(tmp_path, vault):
    path = tmp_path / 'inbox.db'
    with pytest.raises(sqlite3.OperationalError):
        inbox_samples(path, vault, 10)
    assert not path.exists()
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE profiles(id INTEGER, encrypted_data TEXT);
            CREATE TABLE cases(id INTEGER);
            CREATE TABLE incoming_messages(id TEXT, case_id INTEGER, encrypted_payload TEXT, created_at TEXT);''')
        db.execute('INSERT INTO profiles VALUES (?, ?)', (1, vault.encrypt({'full_name': 'Example Person'})))
        db.execute('INSERT INTO cases VALUES (1)')
        for mid, cid in [('linked', 1), ('unmatched', None)]:
            db.execute('INSERT INTO incoming_messages VALUES (?, ?, ?, ?)',
                       (mid, cid, vault.encrypt({'subject': 'Hello', 'body': 'Private body'}), '2026-10-01'))
    before = path.read_bytes()
    samples, private = inbox_samples(path, vault, 10)
    assert len(samples) == 1 and samples[0]['case_id'] == 1
    assert 'Example Person' in private
    assert path.read_bytes() == before


def test_evaluation_reports_accuracy_only_for_reviewed_labels_and_no_text():
    samples = [{'id': 'one', 'body': 'We are processing your request.', 'expected': 'confirmation'},
               {'id': 'two', 'body': 'Private body', 'case_id': 1}]
    original = copy.deepcopy(samples)
    client = JevClassifier('test-key', transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_data('completed'))))
    try:
        report = evaluate(samples, client)
    finally:
        client.close()
    assert samples == original
    assert report['counts']['labelled'] == 1
    assert report['counts']['false_done'] == 1
    assert report['counts']['jev_correct'] == 0
    assert report['counts']['jev_evaluated'] == 2
    assert report['estimated_cost_usd'] == 0.000084
    assert 'Private body' not in json.dumps(report)
    assert 'body' not in report['results'][0]


def test_evaluation_stops_after_provider_failure():
    client = JevClassifier('test-key', transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    try:
        report = evaluate([{'id': str(i), 'body': 'Received'} for i in range(5)], client)
    finally:
        client.close()
    assert report['samples_processed'] == 1
    assert report['counts']['errors'] == 1


def test_missing_body_is_skipped_without_blocking_the_next_reply():
    client = JevClassifier('test-key', transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_data())))
    try:
        report = evaluate([{'id': 'empty', 'body': ''}, {'id': 'next', 'body': 'Received'}], client)
    finally:
        client.close()
    assert report['counts']['skipped'] == 1
    assert report['counts']['jev_evaluated'] == 1
    assert 'errors' not in report['counts']
    assert report['results'][0]['skipped'] == 'empty_reply'


def test_fixture_corpus_is_labelled_and_baseline_is_offline():
    fixtures = json.loads(FIXTURES.read_text())
    assert len(fixtures) >= 40
    assert len({f['id'] for f in fixtures}) == len(fixtures)
    assert all(f['expected'] in CRITERIA for f in fixtures)
    assert sum('source' in f for f in fixtures) >= 16
    report = evaluate(fixtures)
    assert report['mode'] == 'rules_only'
    assert report['counts']['labelled'] == len(fixtures)
    assert 'jev_evaluated' not in report['counts']


def test_cli_requires_key_only_for_explicit_live_run(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.setattr('sys.argv', ['jev_eval', '--fixtures', str(FIXTURES), '--live'])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert 'no API calls made' in capsys.readouterr().err
    monkeypatch.setattr('sys.argv', ['jev_eval', '--fixtures', str(FIXTURES), '--limit', '1'])
    main()
    assert json.loads(capsys.readouterr().out)['mode'] == 'rules_only'
