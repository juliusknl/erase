# Privacy architecture

erase is designed as a local, single-user application. The project maintainers do not receive an installation's identity profile, Gmail authorization, correspondence, case history, or broker evidence merely because someone downloads and runs the software.

## Data stored locally

The application stores:

- identity and contact details entered by the user;
- the user's typed signature and mandate timestamp;
- Gmail OAuth tokens;
- an optional TypeSafe API key saved through Reply assistance;
- optional ChatGPT account registrations and encrypted OAuth credentials;
- request and reply evidence;
- case states, job scheduling data, and broker metadata.

Identity data, signatures, OAuth tokens, correspondence payloads, job payloads, and evidence are encrypted before being placed in SQLite. Operational metadata such as broker names, case states, and timestamps is not necessarily encrypted field-by-field. Encrypted backups use the installation's master key, so losing that key makes the backup unrecoverable.

On macOS, the launcher stores the master key, password hash, and session secret in Keychain. FileVault is required for unattended operation. These controls reduce exposure from copied files or a powered-off stolen Mac; they do not protect an unlocked, compromised operating-system account.

The desktop preview uses `~/Library/Application Support/erase` and one
`erase.desktop.<installation-path-hash>` Keychain entry. It does not read a developer
checkout's `.env` or reuse its three legacy Keychain entries. See
[desktop recovery and removal](desktop-preview.md). The instructions below using
Docker and `personal-erasure.*` apply only to the developer checkout.

## Data sent elsewhere

When the user enables live submissions, information is sent to:

- Google, for Gmail OAuth and email operations;
- the recipient data broker, through an approved email request or an interactive official form;
- any infrastructure inherently involved in delivering the user's mail.

The application has no analytics, crash-reporting service, advertising SDK, or maintainer-operated backend. Public broker-registry data is bundled for discovery.

If the user enables **Reply assistance**, minimized broker-reply text is sent to
the selected provider (TypeSafe for Jev, or OpenAI for ChatGPT) to classify replies. Known saved personal details, email addresses and
links are removed where possible; this is not guaranteed anonymization. The
connection test uses fixed synthetic messages, not mailbox contents. Keys saved
in Settings are encrypted locally. Turning assistance off stops new AI calls
without stopping ordinary email sending; a call already in flight may finish.
The selected provider's processing and retention terms apply. ChatGPT requests
use `store:false`; this is not a claim of zero retention or anonymization. Tokens
are not copied from Codex or another application. Turning off preserves the saved
connection; disconnecting removes the selected local credentials and attempts to
revoke the ChatGPT renewable session. Failed remote revocation is reported with a
link to ChatGPT Settings. Account identity/registration and the installation host
ID remain so reconnecting does not register a new app each time. See
[Jev](jev-reply-classifier.md) and [ChatGPT](chatgpt-reply-assistance.md).

## Gmail access

The application requests `gmail.modify` and `gmail.send`. It checks recent incoming mail in the dedicated mailbox, including already-read mail and spam, without changing read status. It stores tokens and incoming correspondence encrypted locally; unmatched messages remain reviewable. A dedicated mailbox limits accidental exposure and remains strongly recommended.

Users can revoke access from their Google Account security settings. Revocation stops future mailbox access but does not erase local encrypted records; remove the installation's data and backups separately when appropriate.

## Deletion and retention

There is no in-app wipe button. To remove an installation deliberately:

1. Stop automation and revoke the app's Google authorization. Mail already sent cannot be recalled.
2. In this project's directory, run `docker compose down`. Verify that its container stopped. This does not delete the database or affect other Compose projects.
3. In Finder, locate **this installation's** `data` directory, `backups` directory and `.env` file. Move them to Trash only after deciding whether to keep a recoverable backup. Include any exports or correspondence saved elsewhere. Do not remove a parent workspace directory.
4. When you no longer need encrypted backups, use Keychain Access to delete this installation's three entries: `personal-erasure.master-key`, `personal-erasure.password-hash`, and `personal-erasure.session-secret`. Losing the master key makes retained encrypted data unrecoverable. These service names are shared by installations using the same OS account, so check before deleting them.
5. Delete the dedicated Gmail messages/account and Google OAuth project separately if desired. Local deletion does not erase Google's copies, broker copies, Time Machine snapshots or other backups. Emptying Trash is not a guarantee of physical erasure on an SSD.

Backup/restore is covered by automated temporary-database tests. The destructive whole-installation procedure above has not been run against the personal experiment. Operational job retention still needs a bounded cleanup policy before a stable release.

## User responsibilities

Users control the identity supplied, the legal basis asserted, the selected brokers, and whether live submissions are enabled. They should disclose only accurate information and should not use the software to impersonate another person or claim rights they do not have.
