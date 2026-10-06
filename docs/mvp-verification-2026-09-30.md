# Local pilot verification — 30 September 2026

This records an earlier, limited technical milestone. It is **not** acceptance of
the coverage-led MVP now being pursued. Use `erasure-catalog audit --require-mvp`
for the whole-inventory gate; the small pilot gate can pass while hundreds of
inventory assessments and workflows remain unfinished. Counts below describe
that earlier deployment, not the latest working catalog.

## Delivered scope

- 47 evidence-backed initial email workflows and 18 declared guided-form routes.
  This is the finite executable cohort, not a count of successful deletions or
  personal exposure. The larger research directory remains incomplete.
- Optional work email and employer unlock SalesIntel and RevenueBase. SciLeads
  uses its documented email alternative. Home address is no longer required for
  setup. Exact message approval still binds every disclosed field.
- Eleven additional guided forms reuse the existing reviewed dossiers. They show
  matching requirements, steps, verification, scope and incomplete-field caveats.
  Campaign links to the checklist; the overview shows only five unfinished steps.
- Changed professional identifiers block affected approved messages without
  adding them to unrelated requests. Missing details remain explicit handoffs.
- Reply interpretation excludes recognizable quoted history and inherited
  outcome subjects. Questions and future/conditional statements cannot by
  themselves close a request. HTML quote boundaries survive mail parsing.
- Late untrusted messages remain reviewable without reopening completed outcomes.
  Requested professional details can be prepared in a reply draft; drafts still
  need review and are never automatically sent with new disclosures.
- Keychain initialization refuses to overwrite existing or unreadable keys.
  Existing encryption keys must be recovered rather than regenerated casually.

The deterministic controller requires no LLM or agent. It checks approved
workflows, prepares eligible requests and sends under the saved daily limit while
the app runs. New destinations, changed messages and extra disclosures still need
explicit review. A form, challenge or missing identifier is not disguised as an
automatic route.

## Verification performed

- `uv run pytest -q`: **353 passed**, no skipped tests. One dependency deprecation
  warning remains in FastAPI's test-client import; it does not fail the suite.
- `uv run ruff check src tests`: passed.
- `uv run erasure-catalog audit --require-pilot`: passed, no pilot problems.
- Fresh temporary-database HTTP journey: optional-address setup, exact campaign
  approval, controller delivery through fake Gmail, authenticated reply, manual
  form completion and restart. No repeated initial sends after restart.
- Chromium and WebKit: setup and expanded form instructions fit 390px and 1440px
  viewports. Existing responsive and interaction regression tests also pass.
- Built the Docker image and ran a separate fresh-container smoke test with
  `--network none`, synthetic credentials, no mounted personal data and sending
  disabled. Login and the five primary setup/coverage pages rendered successfully.
- Encrypted backup before deployment; local Docker update; authenticated live
  checks of health, overview, campaign, identity, checklist, requests, inbox,
  actions and brokers. Database integrity check passed; previous case IDs and
  completed outcomes were preserved. Recurring controller, preparation and Gmail
  checks resumed, with no failed jobs or controller/preparation errors observed.
- Application source, tests, templates and documentation were checked for common
  OAuth/private-key credential patterns; none found in the scanned files. Private
  state, environment configuration, backups and goal notes are ignored by Git.
  This limited pattern check is not a full secret-history/security audit.

## Still not demonstrated

This is a **local, single-user pilot**, not the coverage-complete MVP or Incogni parity. The tests simulate
mail; they do not prove live removal at 65 brokers. Some guided forms have untested
dynamic fields, every guide still records its actual public-source evidence level,
and third-party fulfilment can require more work. Hundreds of reliable removals,
complete market coverage and ten minutes of weekly effort are not established.

Before public release: select a license, prepare an independent repository, scan
its actual publication contents/history, test OAuth onboarding with independent
users, and measure real outcomes and time spent. Keep platform claims limited to
the setup actually tested. Nothing was pushed or published during this work.
