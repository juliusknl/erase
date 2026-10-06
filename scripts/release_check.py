"""Check the source payload, not personal data or a parent repository's history."""

import argparse
from pathlib import Path

from erasure.catalog_readiness import readiness
from erasure.config import Settings
from erasure.release import inspect_source, source_archive

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--allow-unlicensed-preview', action='store_true')
parser.add_argument('--source-zip', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
files, issues = inspect_source(root, require_license=not args.allow_unlicensed_preview)
pilot = readiness(Settings(_env_file=None, catalog_dir=root / 'catalog'))
issues.extend(pilot['problems'])
print(f'{len(files)} allowlisted source files checked; private data, .env, caches and parent git history excluded.')
if issues:
    for issue in issues:
        print('FAIL:', issue)
    raise SystemExit(1)
if args.source_zip:
    digest = source_archive(root, args.source_zip, require_license=not args.allow_unlicensed_preview)
    print('Source archive SHA-256:', digest)
print('Source payload checks passed. This does not certify Google approval, Apple notarization or user acceptance.')
