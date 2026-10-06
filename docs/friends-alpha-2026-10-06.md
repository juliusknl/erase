# Friends source alpha · 2026-10-06

**Scope: a small Mac friends trial, not a general-public release certification.**
Automatic email workflows currently support EU/EEA residents. Other supported
countries can use the reviewed manual forms. The catalog is not a measure of
anyone's exposure or a guarantee of deletion.

## What to share

Use the clean `erase-friends-alpha-2026-10-06.zip` source snapshot, not an old ZIP,
an unsigned desktop preview or the author's working directory. It includes MIT,
third-party notices, the current ChatGPT reader fixes, the broker catalog and
GitHub CI. Private state, `.env`, caches, build output and parent Git history are
excluded. The companion standalone export has no inherited repository history.

The source launcher needs no Docker, Homebrew, Xcode, manual Python installation,
paid server or `.env` editing. The coding assistant installs uv and the locked
dependencies; the user approves their Mac and Google account prompts themselves.
Use the short prompt in [Try erase](friends-preview.md), which routes assistants
to the bounded [setup instructions](assistant-setup.md).

## Checked for this snapshot

- Exported the allowlisted source outside the working repository and installed
  it in a fresh virtual environment using `uv sync --locked --dev`.
- The clean export passed **1,063 non-browser tests**; one test was skipped.
  One existing upstream Starlette test-client deprecation warning remains.
- **71 browser tests** passed in Chromium/WebKit, covering responsive layouts,
  themes and interactive flows.
- After the README refresh, **1,067 non-browser tests** passed locally. New checks
  cover README links, stated route counts and the explicitly allowlisted images.
  The dashboard image uses temporary fictional state, not personal correspondence.
- Lint, the licensed source-payload gate and both launcher help commands passed
  in that clean export. Tests use temporary or synthetic data, not the real mailbox.
- The declared pilot catalog gate passed. The full-inventory gate remains
  incomplete; this is not a claim that every catalog entry is ready.
- Export/ZIP regressions check current ChatGPT code, exact MIT text and GitHub CI.
  Export refuses symlinks and reports credential-pattern findings by path only.
- CI now installs both Chromium and WebKit. Compose validation uses only the
  non-secret `.env.example` and synthetic keys; its clean-export regression passed
  without starting a container. The first GitHub CI run passed on the personal
  `juliusknl/erase` repository: Python 3.11–3.13, Chromium/WebKit and the actual
  container build. The repository was created private, with one initial commit
  and no inherited history.
- The existing real app remained healthy; no experiment reset, permission change,
  OAuth replacement, deployment or test broker send was performed.

## What friends still need to prove

A first-time person on a clean Mac must finish setup, observe a real first send,
recover from Gmail expiry, and try sleep/reboot with background operation. No
automated fixture proves broker deletion or a ten-minute weekly workload.

Each friend still creates their own Google project and connects a personal Gmail
inbox. Testing-mode tokens for the required scopes normally expire after seven
days; reconnect in the app with the same inbox. See
[Google's expiry guidance](https://developers.google.com/identity/protocols/oauth2#expiration).
The app cannot work while the Mac is asleep or off. Start-on-login is optional.
Jev/ChatGPT reply assistance is optional and uses the chosen provider's allowance.

Keep the source folder in place. Try 3–5 friends for two weeks before expanding.
Record friction and redacted failures, never private messages or credentials.
Apple notarization and a shared public Google integration are not part of this
self-configured source trial. See the earlier
[release review](release-readiness-2026-10-04.md) and
[distribution plan](distribution-plan.md) for broader release limits.
