# erase

Send data-broker removal requests. Keep track of what comes back. On your computer.

**Friends preview · macOS first · MIT licensed.** Automatic email requests currently
support EU/EEA residents; reviewed forms cover additional countries. This is not a
deletion guarantee or a finished replacement for a paid removal service.

## Start with your coding assistant

Download and unzip the source ZIP, or clone the standalone erase repository.
Keep the erase folder somewhere permanent, such as Documents, and open it in
Codex or Claude Code. Paste:

> Read `docs/assistant-setup.md`, install and open erase, then guide me through Gmail
> setup one step at a time. Keep my data private; I'll enter secrets and click Start.

The assistant handles installation, not your removal campaign. Once you finish
setup, the app sends eligible requests and checks replies without an AI agent.
You handle the forms and identity checks it flags. Reply assistance through Jev or
your eligible ChatGPT account is optional.

## Or start it yourself

On a Mac with FileVault enabled, install [uv](https://docs.astral.sh/uv/getting-started/installation/)
if needed. In the folder containing `pyproject.toml`, run:

```sh
uv run --locked erase
```

No Docker, Homebrew, Xcode, manual Python installation or `.env` editing. uv installs
the locked dependencies and, if needed, Python. The browser opens a guided setup:
**appearance → country → your info → Gmail → review and start**.
You can close the terminal and browser. erase runs locally in the background and
macOS restarts it if it crashes. Sleep pauses work; waking resumes it, checking
replies before sending overdue requests. Automatic emails are spaced one minute
apart within your daily limit. In **Settings → Automatic emails**, optionally enable
**Start erase when I log in**. Otherwise use the same command after a Mac restart.
To quit the background process completely: `uv run --locked erase --stop`.
This is not hosting: nothing runs while your Mac is asleep, logged out, or off.

**Optional reply assistance:** In Settings → Automatic emails → Set up reply
assistance, choose Jev (TypeSafe API key) or ChatGPT (Continue with ChatGPT).
ChatGPT uses an eligible Plus/Pro account's shared allowance, not an API key or a
separate erase subscription. Four synthetic reply checks run before activation.
The selected provider receives minimized reply text; ordinary email sending never
depends on AI. [Connection details and limitations](docs/chatgpt-reply-assistance.md).

**The fiddly part:** Gmail still requires your own Google Cloud project. The app
guides you through it and imports the downloaded configuration. Your assistant can
explain each step, but you sign in and approve access yourself. Never paste passwords,
client secrets or API keys into chat. No requests send before you select Start.
Use a personal Gmail account, preferably a dedicated one. Work/school administrators
may block mailbox access. You choose a separate local dashboard password and approve
Keychain access on your Mac. Google **Testing** connections normally need reconnecting
after seven days; this is explained in the setup guide. Standard Gmail API usage is
[available at no additional cost](https://developers.google.com/workspace/gmail/api/reference/quota),
within Google's limits. The friends setup does not need a paid cloud server.

Want to look around without connecting anything?

```sh
uv run --locked erase-demo
```

Open **http://127.0.0.1:8788**, password **try-erasure-demo**. Use made-up details.
This isolated simulator sends no real mail and uses no AI credits.

[Quick help and short prompts](docs/friends-preview.md) ·
[Privacy](docs/PRIVACY.md) · [License](LICENSE) ·
[Release checks and limitations](docs/friends-alpha-2026-10-06.md)

<details>
<summary>Technical details, coverage and alternative installation</summary>

A local-only, single-user data-broker removal assistant. It maintains an encrypted identity profile, prepares minimal-disclosure requests, sends supported email requests through a dedicated Gmail account, classifies replies, tracks evidence, schedules follow-ups and 60/90-day rechecks, and stops at explicit human approval gates.

This is personal automation, not a law firm or an authorized-agent business. Requests are written in the first person and never claim California residency. No request is sent until both the campaign is started and `ERASURE_LIVE_SUBMISSIONS=true`.

## What “support” means

The public CPPA registry is a discovery source, not a list of tested integrations. A broker counts as supported only after its recipient or official form, required fields, jurisdiction, and failure behavior have been validated. Sent, acknowledged, confirmed, and rechecked removals are reported separately. See [docs/BROKER_SUPPORT.md](docs/BROKER_SUPPORT.md).

Counts change as the catalog is reviewed. The dashboard separates ready drafts, requests awaiting replies and contacts needing research; registry size is not supported coverage. The overview's “Done” combines user completion, reported deletion and no-match results, while request details retain their evidence.

## Europe-first broker knowledge

The Brokers page opens curated regional guides with official evidence, required
identifiers, scope limits and next steps. The executable cohort is declared in
`catalog/mvp-cohort.yml`; the audit reports its current email and guided-form counts.
The much larger research
directory is not a list of tested integrations. Priorities follow likely exposure
and sensitive data, not a provider's headquarters. Adding a guide never authorizes
more disclosure. See the [pilot scope](docs/mvp-broker-foundation.md) and the
[knowledge contract and remaining work](docs/european-knowledge.md).
Run `uv run erasure-catalog audit` to inspect the public curation backlog without
accessing a mailbox or user database.

## Weekly workflow

Set your residence in **Settings → Profile**, then open **Automatic emails** (`/campaign`). Connect Gmail, choose whether to allow your saved postal address when required, and authorize **Start automatic emails** once. Exact email previews are available through **See covered brokers and exact emails**; no preview-regeneration or batch-approval step is needed. The daily sending limit defaults to 20 and is directly editable. The local worker checks maintained workflow evidence, replenishes eligible drafts, and sends them without an LLM. Unsent work continues the next day when the daily budget is exhausted. Keep the local app running; **Home** shows meaningful status and Pause/Resume controls, while **Requests → Needs you** groups genuine decisions by request.

Pause asks for confirmation before holding outgoing automatic requests and follow-ups; connected Gmail keeps checking replies. Cancel or Escape makes no change. Resume uses the existing permission only if it is still valid. Saving permissions while paused does not resume sending. Changing country or approved identity information stops automatic sending until reviewed. A message already in flight cannot be recalled.

Home shows up to three actions, prioritizing outstanding requests before optional
forms. Suggested forms use explicit country scope and researched categories;
available email workflows take priority. Completing or postponing a suggestion
does not refill the session automatically. Choose **Do more** or **Browse all**
when you want more. **Later** hides a suggestion for seven days; **Not interested**
hides it until restored. Neither stops existing requests or counts as deletion.
Credit/insurance/identity-risk routes stay outside default suggestions.
See the [simple experience](docs/simple-experience.md) for the ranking and limits.

Country-aware manual suggestions include the EU/EEA, UK, Switzerland, US, Canada,
Australia and New Zealand where the catalog establishes scope. Automated email
recipes currently support EU/EEA residents only; selecting another country never
enables European requests. Email alerts are optional and blank by default.

Public-source research is maintained in the shared catalog, rather than repeated on every installation. Only reviewed workflows can send automatically; an email address alone is not enough. Forms and unclear requirements stay manual. This does not establish hundreds of successful integrations or guarantee ten minutes of weekly work. See the [campaign contract](docs/campaign-implementation.md) and [release roadmap](docs/automation-and-release.md).

Campaign permission binds the residence, disclosure limits and supported workflow
categories. Newly reviewed workflows can join automatically within that permission;
changing identity or disclosure scope requires review. Postal address is optional
and used only where a reviewed workflow requires it; phone, birth date and
attachments are never included automatically. Add an email you actually use so
brokers can match you beyond the dedicated request mailbox. Pausing blocks queued
automatic sends; a request already in flight cannot be recalled. Sending requires
connected Gmail, valid in-app permission and installation sending capability.

Work email and employer are optional Identity fields for workflows that explicitly
require them. They are not added to other messages. Quick wins reuse the reviewed
broker instructions and show matching fields, verification, scope and untested
parts. Home shows a small selection; the full checklist includes completed and skipped steps.

## What works

Optional [AI reply interpretation](docs/jev-reply-classifier.md) sorts broker replies
automatically and clears obsolete review tasks. Open **Settings → Automatic emails →
Reply assistance**, paste a TypeSafe key and choose **Connect and enable**. The app
tests a synthetic reply, encrypts the key locally, and applies the setting without
a restart. Minimized reply text is sent to TypeSafe;
sender checks and disclosure permissions remain local. Without it, existing rules
still run. The separate comparison evaluator remains read-only.

- Encrypted identity, signature, OAuth tokens, correspondence, job payloads, and evidence using libsodium SecretBox.
- Password-protected localhost dashboard with CSRF protection.
- Durable SQLite case state, audit events, approvals, retrying jobs, and recurrence schedules.
- Import of the current official 2026 CPPA registry as a discovery catalog, without using DROP or claiming CCPA rights.
- Risk-based scheduling: broad registry entries remain candidates; curated likely brokers start at higher confidence.
- Gmail OAuth, bounded token refresh, thread-aware and authenticated-sender reply correlation, HTML mail parsing, and a durable encrypted reply inbox.
- Unmatched replies stay visible for review. Reviewed deletion reports retain their evidence and cancel obsolete follow-ups. Case pages include correspondence and a follow-up email composer.
- One recurring polling job retries connection failures; a visible error and reconnect link replace silent expired authorization. Checks include read mail and spam with pagination and catch up from the last successful sync.
- Validated batch sending capped at 10 cases, with the same 90-day contact gate enforced on background follow-ups and rechecks.
- Opt-in continuous campaigns: one-minute controller, maintained workflow checks, and configurable 1–50 automatic broker emails/day (UTC).
- Automatic dispatch ledger with payload hashes, atomic daily reservation and at-most-once retry safety. Interrupted or uncertain sends stop for review rather than being replayed. Daily budgets cover managed requests, follow-ups and rechecks, not mailbox polling or user-requested manual replies.
- Safe browser boundary: unknown forms and CAPTCHAs create resumable actions instead of bypass attempts.
- CSV audit export and a global pause switch.

## Setup on this Mac

### Self-contained desktop preview

The maintainer can build a local macOS app using the
[desktop build instructions](docs/desktop-preview.md). Open the resulting app,
choose a dashboard password, then follow the browser setup. The app keeps its
own private data and Keychain entry, separate from a developer checkout.
Closing the browser does not stop work; quitting erase or sleeping the Mac does.
This preview is not notarized and has not passed fresh-Mac acceptance. It is a
separate experiment, not the friends distribution route. Use the source instructions
above; do not disable Gatekeeper to distribute an unsigned app.

### Developer checkout

To try a fresh account without real mail or credentials, use the separate
[isolated demo](docs/demo.md) at `http://localhost:8789`. It does not reset an
existing installation.

Requirements for this route: macOS, uv, Docker Desktop running, FileVault enabled,
and a Gmail mailbox (a separate request mailbox is recommended).

From `tools/erasure`, run:

```sh
uv run erasure-keychain setup --enable-sending
```

The launcher asks for a local dashboard password on first use, creates missing
configuration, stores encryption/session keys in Keychain, starts the app and
opens `http://127.0.0.1:8787/setup` once healthy. Existing files and keys are kept.
`--enable-sending` allows this launch to send, but **does not give campaign
permission**. Omit it for a preview-only installation.

Unlock and follow five steps:

1. Pick an appearance: Porcelain, Conservatory, Atelier or Midnight. Change it
   anytime in Settings → Appearance; it only changes how the app looks.
2. Choose where you live. Countries without automatic email support go directly
   to available removal forms, without collecting an email profile.
3. Add your name and email addresses brokers may already know. These are separate
   from the mailbox used to send requests.
4. Connect your request Gmail. If Google credentials aren't configured, the app
   guides you through creating a Google project and importing its Web-client JSON.
   The file is encrypted locally; no `.env` editing is needed. The connected
   mailbox address is checked with Google rather than typed manually.
5. Review shared details, sign and authorize once. **Start automatic requests**
   starts the eligible email plan at 20/day; exact previews are optional. Forms
   and extra information remain manual. Change the limit later in Settings.

Continue or Save and exit saves draft progress encrypted, without granting any
permission. Existing profiles skip first-run setup. The app refuses to start a
new plan without sending capability, an active worker, a valid mailbox and at
least one eligible email workflow. AI is optional and not part of setup.

To rebuild/relaunch with sending capability later:

```sh
uv run erasure-keychain up --enable-sending
```

Without that flag, `up` uses the sending setting in `.env` (false by default).
The read-only diagnostic remains `uv run erasure-keychain doctor`. Manual
`init` and environment-based Google credentials remain supported.

Docker Desktop must start at login and the Mac must remain awake for continuous monitoring. Jobs survive restarts and resume later if the Mac sleeps.

Create an encrypted, transactionally consistent backup while the app is running:

```sh
uv run erasure-keychain backup backups/erasure-$(date +%Y%m%d).erasurebak
```

Restore only with Docker services stopped: `uv run erasure-keychain restore backups/FILE.erasurebak`.
Restore refuses active app connections or unfinished SQLite journals and checks the
backup's integrity before applying it. Backup creation never overwrites an existing file.
The lower-level restoration command deliberately requires `--confirm-overwrite`.

### Google OAuth

Create a Google Cloud OAuth client of type **Web application**, enable the Gmail API, and add the exact authorized redirect URI `http://127.0.0.1:8787/gmail/callback`. The requested scopes are `gmail.modify` and `gmail.send`. Use a new mailbox only for removal correspondence.

Google may require the OAuth consent screen to be in testing mode with the dedicated mailbox added as a test user. Tokens and incoming correspondence are encrypted locally. The app checks incoming mail, including already-read messages and spam, without changing read status. Messages are deduplicated by Gmail ID. A unique authenticated official sender can be linked even in a new thread; unknown senders and privacy platforms remain visible in Replies for explicit review.

Contact verification is evidence of a current request destination, not a guarantee of removal. Personal experiment results and correspondence are not part of the public catalog.

For personal installations, each user should create their own OAuth project rather than sharing credentials committed to this repository. An External project left in **Testing** normally receives refresh tokens that expire after seven days for these scopes. Before relying on unattended monitoring, follow Google's current personal-use guidance and understand the warning and publishing state shown in the Cloud Console. Never commit a client secret.

## Official broker catalog

The included `catalog/registry2026.csv` is the public current CPPA export downloaded on September 2, 2026; the historical 2025 export is retained for provenance. Refresh the current file from the official registry page when needed. Registry inclusion is discovery evidence, not proof that a broker holds this EU resident's data or that California law applies.

Curated broker URLs change frequently. Browser connectors therefore fail closed and require a validated broker-specific adapter before unattended form submission. This is intentional: blindly filling a redesigned page risks disclosing data to the wrong field or accepting new terms.

The [major-broker checklist](catalog/major-brokers.yml) separately tracks priority marketing and people-search families by country and product. See the [coverage review](docs/major-broker-coverage-2026-10-04.md) for supported routes and gaps. `uv run erasure-catalog audit --require-major-routes` fails while any declared priority route is missing; it is not a market-share or deletion-success measure.

## Development and verification

```sh
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts/release_check.py
uv run erasure-catalog audit --require-pilot
uv run erasure-catalog audit --require-mvp
docker compose config --quiet
```

Tests use temporary databases, fake Gmail HTTP responses, and mock broker messages. They never contact brokers, Gmail, or any other external system.

The small pilot gate currently passes; the whole-inventory MVP gate deliberately
fails while research or implementation gaps remain. Passing tests or the pilot
gate alone does not mean the coverage-led MVP is finished.

## Security and recovery

- Enable FileVault and keep `.env`, `data/`, `backups/`, `.eml`, and identity files out of version control.
- Back up the encrypted database with Time Machine. The Keychain master key is required to restore it.
- Identity-proof and representative-authorization requests are shown with an email handoff. Document upload and sending are not supported in the app. Review the original sender and handle these requests directly in your mailbox. Complaints remain review-gated.
- Rotate the OAuth authorization and master key if the Mac or dedicated mailbox is compromised.
- The app deliberately avoids CAPTCHA solvers, anti-bot bypasses, automated legal attestations, and California DROP.

Read [SECURITY.md](SECURITY.md), [docs/PRIVACY.md](docs/PRIVACY.md), and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) before using real identity data. Contributions must follow [CONTRIBUTING.md](CONTRIBUTING.md).

## Public-release status

This working tree is not ready to publish yet. Before the first GitHub release it needs an independent repository and secret-history scan, clean-machine installation tests, a tested deletion procedure, and initial external beta feedback. It is not affiliated with Incogni, Surfshark, the CPPA, Google, or any data broker.

## License

erase is licensed under the [MIT License](LICENSE). Third-party software retains
its respective licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

</details>
