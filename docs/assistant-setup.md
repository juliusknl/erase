# Set up erase for a friend

Instructions for Codex, Claude Code or another local coding assistant. This is an
installation task, not permission to operate a mailbox or modify the product.
Keep explanations short. Do the mechanical work; leave account approval to the user.

## Install and open

1. Find the erase project: `pyproject.toml` must name `personal-erasure` and the
   folder must contain `src/erasure`, `templates`, `static` and `catalog`. In a
   development checkout it may be under `tools/erasure`; a release ZIP starts here.
   Do not use or publish an unrelated parent repository.
2. Check the OS. This friends path is macOS-only. On Windows/Linux, explain the
   current limit instead of pretending the Keychain launcher works. The isolated
   demo can be tried separately; unattended real operation there is not validated.
3. Keep the source folder somewhere permanent before first launch, preferably
   outside a Downloads folder that gets cleaned automatically. Never move an
   existing running installation or overwrite another erase folder silently.
   Check for uv. If missing, use its official installation instructions at
   https://docs.astral.sh/uv/getting-started/installation/. No Docker, Homebrew,
   Xcode or manually installed Python is required for this route. uv installs
   Python if needed and resolves the locked environment. If uv just installed
   but isn't on PATH yet, use the path reported by its installer; don't keep
   reinstalling it. Do not change unrelated settings or install extra tooling.
4. Check `fdesetup status`. If FileVault is off, show System Settings → Privacy &
   Security → FileVault and let the user enable it. Never weaken the storage gate.
5. In the erase directory run `uv run --locked erase`. It starts a user-scoped
   macOS background process and returns; the terminal need not stay open. Do not claim it is running
   until `http://127.0.0.1:8787/health` identifies `application: erase` and `ok: true`.
6. Open `http://127.0.0.1:8787`. The native password dialogs are for the user, not
   you. Guide them only when stuck: appearance, country, matching details, mailbox,
   then their own review/signature/Start. Do not click Start or enter consent for them.
   Explain that this is a new local erase password (12+ characters), not a Google
   password, and leave FileVault/Keychain approval to them.

The launcher obtains its keys from macOS Keychain and keeps private data in
`~/Library/Application Support/erase`. It ignores the checkout's `.env` and
inherited provider keys. Existing Docker data/keys are separate; do not migrate or
replace them. If erase is already running, open it rather than starting a duplicate.
If another program owns port 8787, identify it and ask before stopping anything.

## Google connection

Use the app's Gmail helper, guiding just one screen at a time. Recommend a personal
Gmail inbox dedicated to requests; work/school policies can block access and must
not be bypassed. Their usual email addresses still belong in Your info for matching.
The user creates their own project, enables Gmail API, chooses **External** in the
consent screen, adds the request inbox as a test user and downloads a
**Web application** OAuth client JSON, not a Desktop client.
The exact redirect is `http://127.0.0.1:8787/gmail/callback`. They import that file
directly in the app and sign in with their request mailbox. Do not print its contents
or ask them to paste credentials into chat. Do not reuse the author's project.
No Docker or cloud server is involved. Standard Gmail API usage is available at
no additional cost within Google's limits; see
https://developers.google.com/workspace/gmail/api/reference/quota.
Do not enable billing, buy credits or add paid cloud products for this setup.

The scopes cover reading/managing the mailbox and sending, not just broker mail;
a dedicated mailbox is recommended. Google Testing-mode access for these scopes
normally expires after seven days. Explain reconnection when relevant; do not
promise permanent access or claim Google has approved this project. Do not tell
users to bypass warnings for an OAuth project they do not own or trust.
Show the in-app reconnect path if it expires; preserve the same inbox and private
history.

AI is not required to install, start or keep sending. Leave reply assistance off
unless the user chooses Jev or ChatGPT in its optional setup popup. The user
approves ChatGPT account access themselves. Never obtain or buy credits for them.

## Boundaries and handoff

- Never read/decrypt private databases, Keychain values, `.env`, email or tokens
  into the conversation. The app manages those. No uploads, pushes or telemetry.
- Do not patch code, relax validation, change consent, submit forms or send test
  broker mail to make setup appear successful. Report a reproducible blocker.
- Do not delete data, regenerate keys, reset an existing installation, or kill a
  process without the user's specific approval. Losing keys loses their history.
- Use `--locked`; don't upgrade dependencies while troubleshooting installation.
- Use `erase`, not the legacy `erasure-keychain setup` or `docker compose` path.
  Don't run maintainer tests or build a native app just to install the friends release.
- Finish with the local link, the command to reopen, and one sentence: the app
  runs without the terminal or assistant, pauses during sleep, and resumes on wake.
  Offer the optional **Start erase when I log in** setting; don't enable it yourself.
  Keep the source folder in place. Use `uv run --locked erase --stop` to quit the
  managed background process, never broad process-killing commands. A health response
  proves the server is up, not that Gmail is connected or that a request was delivered.

If asked for a demo instead, run `uv run --locked erase-demo` from this directory.
Open http://127.0.0.1:8788, use password `try-erasure-demo` and synthetic details.
Never reset or reuse the real database for a demonstration.
