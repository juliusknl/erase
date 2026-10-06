# Release review · 2026-10-04

**Status: local preview, not cleared for a general-public desktop launch.**
Latest source snapshot: see the [2026-10-06 friends alpha checks](friends-alpha-2026-10-06.md).
The artifact names and counts below are historical, not the current download.
Update 2026-10-05: the owner approved MIT. `LICENSE`, package metadata and release
export tests now include it. This clears the license-choice gate only; the older
preview artifacts below predate this change and have not been rebuilt.

The owner selected **GitHub/source distribution for friends first**, not a signed
desktop download or shared public Google integration. The recommended command is
now `uv run --locked erase`; the README includes a short Codex/Claude Code prompt.
Apple signing and public Google OAuth are future distribution options, **not
blockers for this explicitly self-configured source preview**. Each friend still
needs their own Google setup and must approve sending themselves. See
[friends instructions](friends-preview.md) and [rollout plan](distribution-plan.md).

Friends-path verification on 2026-10-05: both locked `erase --help` and
`erase-demo --help` commands work; 28 focused launcher/demo/export tests pass;
lint passes. The normal licensed source gate passes for 485 allowlisted files,
without the unlicensed-preview override. Export tests check the exact MIT text
inside the copied tree and ZIP; installed package metadata includes MIT and LICENSE.
This review concerns the actual release payload and fresh-user paths, not a claim
that every catalog entry is automated or that every broker will delete data.

## Implemented in this pass

- Self-contained macOS preview with a native launcher, bundled locked runtime,
  private Application Support storage and one atomic, installation-specific
  Keychain item. No Docker, user-installed Python, shell profile or `.env` required.
- Safe failure paths for missing/denied keys, existing data without its key,
  port conflicts, password mismatch and cancelled setup. Existing installations
  are not migrated, stopped or overwritten implicitly.
- Staged Gmail reconnection: validate scopes, offline access and actual mailbox
  identity before replacing a working token. A wrong account or cancellation
  preserves the previous connection. Token refresh preserves verified setup state.
- Sending verifies the account matches the authorized request address. A failed
  preflight remains queued, without a false uncertain-delivery task or used daily
  budget. A missing/malformed Gmail send receipt is uncertain and never blindly retried.
- Friendly browser errors instead of JSON dead ends; localhost Host validation;
  generic validation errors do not echo submitted credentials.
- Native password reset preserves encryption and invalidates old sessions;
  encrypted backups refuse existing destinations. Tests use temporary data and keys.
- Allowlisted source export and credential-pattern checks. Source export excludes
  `.env`, personal databases, mail, backups, caches, build output and parent Git
  history. No repository has been pushed or published.
- Test HTTP transports reject accidental nonlocal requests. Tests use explicit
  provider doubles, never the real user's mailbox for test sends.

## Verification

Previous 2026-10-04 local verification results (before the friends-path update):

- Full suite: **907 passed**, including **59 browser cases**. One upstream Starlette
  test-client deprecation warning remains; no test failed.
- Independently extracted allowlisted source: **848 non-browser tests passed** in
  a newly created environment. No working-checkout `.env` or private database was used.
- After the final OAuth HTTP-client lifetime cleanup: **80 focused Gmail, setup and
  campaign tests passed**. `ruff check src tests scripts` passed.
- Latest runtime preview: `dist/erase-preview-5.app`, Apple Silicon. Its relocated
  smoke and post-run signature integrity verification passed. This is a private,
  unlicensed, ad-hoc-signed artifact, not a distribution candidate.
- Source payload: **481 allowlisted files** checked; explicit local-preview gate
  passed. The normal gate fails with `A maintainer-approved license is missing`.
- Existing real and demo containers were rebuilt and are healthy. Authenticated
  Home, Requests, Settings, Quick wins and library returned 200; nine broker-tab
  requests returned 200. Observed page response times were 0.00–0.31 seconds in
  this local sample, not a performance guarantee. Live SQLite read-only integrity
  check returned `ok`. No experiment reset, permission change or test broker send.

The existing tests cover fresh setup, saved drafts, double Start, unsupported
countries, consent rollback, paused plans, day boundaries, worker restart,
uncertain sends, broker outcomes, Jev failures and misleading messages. Browser
tests cover Chromium/WebKit, four themes, narrow layouts and JavaScript fallback.
Passing fixture tests is not measured field accuracy or proof of broker deletion.

- Dependency advisory audit: `uvx pip-audit -r requirements.lock --disable-pip --no-deps`
  reported no known vulnerabilities on this date. This is not an independent audit.
- A relocated preview, in a path containing spaces, ran with synthetic private
  state and the actual embedded worker. Login, setup, major pages, assets and
  localhost rejection worked with zero sends. The bundle retained a valid ad-hoc
  integrity signature after running. This is not a clean-Mac/Gatekeeper test.

## Release gates that remain outside automated code tests

1. **License decision: cleared on 2026-10-05.** MIT was approved and added.
   Third-party runtime redistribution notices still require a release review.
2. **Google onboarding.** Current users create their own project. This is workable
   for a technical source preview, not frictionless consumer sign-in. A maintained
   public integration needs the appropriate project ownership, OAuth client design
   and Google's review. Testing-mode refresh tokens for these scopes normally
   expire after seven days. Personal-use exceptions are not general launch approval.
   Sources: [OAuth policies](https://developers.google.com/identity/protocols/oauth2/policies),
   [production readiness](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview),
   [restricted-scope review](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification).
3. **Desktop distribution.** The preview has an ad-hoc local signature only. Public
   frictionless downloads need publisher signing, notarization and a quarantined
   fresh-Mac launch test. No signing account or identity has been supplied.
   Sources: [Developer ID](https://developer.apple.com/developer-id/),
   [notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
4. **Fresh-person acceptance.** A nontechnical first-time user must complete setup
   without developer coaching, recognize running/paused/needs-you states and
   recover from disconnection. A clean-machine backup/restore drill and keyboard/
   screen-reader review are still needed. Maintenance commands are not yet a
   polished graphical recovery journey.
5. **Scope and field reliability.** Automatic email recipes currently support EU/EEA
   residents; manual routes have broader recorded country scopes. The priority
   coverage checklist has partial and missing routes. The full-inventory gate is
   intentionally stricter than the passing pilot gate. Review
   [major-broker coverage](major-broker-coverage-2026-10-04.md); do not claim 90% of
   personal exposure, all major brokers worldwide, or an Incogni-equivalent service.

## Reproducible maintainer checks

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/release_check.py
uv run python scripts/build_macos.py --output dist/erase.app
uv run python scripts/smoke_macos.py dist/erase.app
codesign --verify --deep --strict dist/erase.app
```

The explicit `--allow-unlicensed-preview` option exists only for local preview
checks. It must not be presented as clearing the missing-license release gate.
Build into a new path. Do not publish the unrelated parent working tree or history.
