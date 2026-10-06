"""Explicit synthetic-fixture evaluation. Never loads mail, changes requests or sends email."""

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from erasure import chatgpt, chatgpt_auth
from erasure.config import Settings
from erasure.crypto import Vault
from erasure.db import create_db_engine
from erasure.store import Store


def evaluate(samples, classifier):
    results = []
    for sample in samples:
        try:
            reply = classifier.classify(sample.get('subject', ''), sample['body'])
            results.append({'id': sample['id'], 'expected': sample['expected'], 'actual': reply.kind.value})
        except chatgpt.JevError as exc:
            results.append({'id': sample['id'], 'error': str(exc)})
            break  # quota/network failure: no retry storm
    return {'model': chatgpt.MODEL, 'prompt_version': chatgpt.PROMPT_VERSION,
        'samples': len(samples), 'evaluated': sum('actual' in row for row in results),
        'correct': sum(row.get('actual') == row.get('expected') for row in results if 'actual' in row),
        'false_done': sum(row.get('actual') in {'completed', 'not_found'} and row['expected'] not in {'completed', 'not_found'} for row in results if 'actual' in row),
        'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path, help='Existing installation database with connected ChatGPT')
    parser.add_argument('--fixtures', type=Path, default=Path('tests/fixtures/jev_replies.json'))
    parser.add_argument('--live', action='store_true', help='Explicitly use ChatGPT allowance for the synthetic fixtures')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--keychain', action='store_true', help='Legacy Docker installation Keychain')
    source.add_argument('--desktop-data', type=Path, help='Desktop installation data directory (existing Keychain only)')
    args = parser.parse_args()
    if not args.live:
        parser.error('Add --live to authorize fixture calls using your ChatGPT allowance. No calls made.')
    if not args.database.is_file():
        parser.error('The existing database was not found. Nothing was created.')
    master = Settings().master_key
    if args.keychain:
        from erasure.keychain_cli import SERVICES, _read

        master = _read(SERVICES['ERASURE_MASTER_KEY'])
    elif args.desktop_data:
        from erasure.desktop import desktop_secrets

        master = desktop_secrets(args.desktop_data.resolve(), existing_only=True)['ERASURE_MASTER_KEY']
    if not master:
        parser.error('Provide the existing installation key through Keychain or ERASURE_MASTER_KEY. Never paste it into chat.')
    samples = json.loads(args.fixtures.read_text())
    if not isinstance(samples, list) or not 1 <= len(samples) <= 200:
        parser.error('Use between 1 and 200 synthetic fixtures.')
    engine = create_db_engine('sqlite:///' + str(args.database.resolve()))
    classifier = None
    try:
        with Session(engine) as session:
            store = Store(session, Vault(master))
            selected = chatgpt_auth.read(store, chatgpt_auth.PROVIDER, {})
            if selected.get('provider') != 'chatgpt' or not selected.get('enabled'):
                parser.error('Connect and enable ChatGPT in Reply assistance first.')
            classifier = chatgpt.ChatGPTClassifier(chatgpt_auth.access_token(store, selected['account']))
            report = evaluate(samples, classifier)
            print(json.dumps(report, indent=2))
            if report['evaluated'] != report['samples'] or report['correct'] != report['samples']:
                raise SystemExit(1)
    except chatgpt.ChatGPTError as exc:
        parser.exit(1, f'ChatGPT evaluation stopped: {exc}\n')
    finally:
        if classifier:
            classifier.close()
        engine.dispose()


if __name__ == '__main__':
    main()
