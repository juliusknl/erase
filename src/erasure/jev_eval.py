"""Compare Jev and existing rules without changing requests or sending broker emails."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from dotenv import dotenv_values

from erasure.crypto import Vault
from erasure.jev import MODEL, PROMPT_VERSION, JevClassifier, JevError, saved_private_values
from erasure.replies import classify_reply


def inbox_samples(path: Path, vault: Vault, limit: int) -> tuple[list[dict], tuple[str, ...]]:
    """Use SQLite read-only mode, not the application/session/worker startup."""
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        profile_row = db.execute('SELECT encrypted_data FROM profiles WHERE id = 1').fetchone()
        private = saved_private_values(vault.decrypt(profile_row[0])) if profile_row else ()
        rows = db.execute('''SELECT m.case_id, m.encrypted_payload
            FROM incoming_messages m JOIN cases c ON c.id = m.case_id
            ORDER BY m.created_at, m.id LIMIT ?''', (limit,)).fetchall()
        samples = []
        for index, (case_id, payload) in enumerate(rows, 1):
            message = vault.decrypt(payload)
            samples.append({'id': f'inbox-{index}', 'case_id': case_id,
                            'subject': message.get('subject', ''), 'body': message.get('body', '')})
    return samples, private


def evaluate(samples: list[dict], classifier: JevClassifier | None = None,
             private_values: tuple[str, ...] = ()) -> dict:
    """Unlabelled inbox agreement is NOT accuracy; label fixtures independently."""
    rows = []
    counts = Counter()
    total_tokens = 0
    for sample in samples:
        rules = classify_reply(sample.get('subject', ''), sample['body']).kind.value
        expected = sample.get('expected')
        row = {'id': sample['id'], 'rules': rules}
        if 'case_id' in sample:
            row['case_id'] = sample['case_id']
        if expected:
            row['expected'] = expected
            counts['labelled'] += 1
            counts['rules_correct'] += rules == expected
        if classifier:
            try:
                reply = classifier.classify(sample.get('subject', ''), sample['body'], private_values=private_values)
                row.update(jev=reply.kind.value, confidence=reply.confidence,
                           probabilities=reply.probabilities, model=reply.model)
                total_tokens += reply.input_tokens
                counts['jev_evaluated'] += 1
                counts['disagreements_with_rules'] += reply.kind.value != rules
                if expected:
                    counts['jev_correct'] += reply.kind.value == expected
                    counts['false_done'] += (reply.kind.value in {'completed', 'not_found'}
                                            and expected not in {'completed', 'not_found'})
            except JevError as exc:
                if str(exc) in {'empty_reply', 'reply_too_long'}:
                    row['skipped'] = str(exc)
                    counts['skipped'] += 1
                    rows.append(row)
                    continue
                row['error'] = str(exc)
                counts['errors'] += 1
                rows.append(row)
                # Stop on service/schema failures; never burn through a backlog retrying.
                break
        rows.append(row)
    return {
        'mode': 'jev_read_only' if classifier else 'rules_only',
        'prompt_version': PROMPT_VERSION, 'requested_model': MODEL,
        'samples_available': len(samples), 'samples_processed': len(rows),
        'counts': dict(counts), 'input_tokens': total_tokens,
        'estimated_cost_usd': round(total_tokens * 0.042 / 1_000_000, 8),
        'note': 'Inbox predictions are unlabelled; agreement with rules is not accuracy. No statuses or emails changed.',
        'results': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--fixtures', type=Path, help='JSON examples with independently reviewed expected labels')
    source.add_argument('--inbox', type=Path, help='Existing local SQLite database, opened read-only')
    parser.add_argument('--live', action='store_true', help='Send minimized reply text to TypeSafe (otherwise rules only)')
    parser.add_argument('--keychain', action='store_true', help='Read the local master key from macOS Keychain for inbox evaluation')
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error('--limit must be between 1 and 1000')
    values = {**dotenv_values('.env'), **os.environ}
    key = values.get('TYPESAFE_API_KEY', '')
    if args.live and not key:
        parser.error('Set TYPESAFE_API_KEY in the environment or the ignored .env file; no API calls made.')
    private = ()
    if args.inbox:
        master = values.get('ERASURE_MASTER_KEY', '')
        if args.keychain:
            from erasure.keychain_cli import SERVICES, _read
            master = _read(SERVICES['ERASURE_MASTER_KEY'])
        if not master:
            parser.error('Inbox evaluation requires ERASURE_MASTER_KEY or --keychain.')
        samples, private = inbox_samples(args.inbox, Vault(master), args.limit)
    else:
        samples = json.loads(args.fixtures.read_text())[:args.limit]
    classifier = JevClassifier(key) if args.live else None
    try:
        report = evaluate(samples, classifier, private)
    finally:
        if classifier:
            classifier.close()
    print(json.dumps(report, indent=2))
    if report['counts'].get('errors'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
