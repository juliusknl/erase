# Contributing

erase is intentionally conservative: a failed request is inconvenient, but disclosing a person's identity to the wrong destination can cause lasting harm.

## Development setup

```sh
uv sync --locked --dev
uv run --locked pytest -q
uv run --locked ruff check src tests scripts
uv run --locked python scripts/release_check.py
```

Tests must use synthetic identities, fake mailbox responses, and mocked broker endpoints. Automated tests must never contact Gmail, a broker, or any other live service.

Docker is only needed when working on the container build, not the normal Mac
launcher. CI validates Compose with the non-secret example and synthetic keys.

## Broker changes

Every broker-specific contribution should include:

- the broker's legal name and authoritative source;
- the exact official privacy or removal URL;
- the applicable geography or legal basis;
- the minimum fields required by the broker;
- the date the workflow was last checked;
- a test covering the request plan or adapter behavior.

Do not label a catalog entry as supported merely because an address or form was discovered. Use the levels in [docs/BROKER_SUPPORT.md](docs/BROKER_SUPPORT.md).

Adapters must stop for human action when they encounter CAPTCHA, identity uploads, legal attestations, ambiguous consent, an unexpected redirect, or a form that no longer matches its validated structure. Do not add CAPTCHA solvers, anti-bot bypasses, forged residency claims, automated signatures on new legal documents, or scraping that violates an access control.

## Privacy in issues and tests

- Never commit `.env`, database files, backups, identity files, tokens, emails, or screenshots containing personal data.
- Redact names, addresses, account identifiers, message IDs, and request tokens from logs and bug reports.
- Use addresses in reserved example domains such as `example.com`.
- Treat broker replies as private correspondence even when the body looks generic.

## Pull requests

Keep changes focused, explain their privacy impact, and include tests for behavioral changes. A pull request should pass the same lint, test, container-build, and Compose checks as CI.
