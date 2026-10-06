# Local reliability milestone · 2026-10-05

Implemented and tested locally. No live campaign restart, mailbox access, test
broker emails, consent changes, hosting, uploads or repository pushes.

## What changed

- `uv run --locked erase` starts a supervised Mac background process, waits for
  local health, opens the dashboard and returns. Closing the browser/terminal no
  longer ends that process. `--foreground` remains available for debugging;
  `--stop` quits only this installation's managed background job.
- Optional **Start erase when I log in** is available at the final onboarding step
  and in **Settings → Automatic emails**. It defaults off and requires an explicit
  authenticated, CSRF-protected save. Disabling it removes only this installation's
  login manifest, not data, permissions or the current running process.
- Uses user-scoped launchd supervision, not a privileged daemon. User agents run
  while their user is logged in. [Apple's launchd documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).
  No credentials enter the plist or process arguments. Unexpected process exit
  is retried with throttling; an already-running process is never killed by reopening.
- Startup and wake restore one schedule per recurring task, respect active job
  leases, and prioritize mailbox polling. Missed controller ticks are not replayed.
- Outgoing worker jobs wait for a successful recent mailbox check and are paced
  one minute apart. Existing consent, daily limits and durable delivery reservations
  remain in place. An interrupted send with no reliable receipt is flagged rather
  than blindly resent.
- Invalid URLs in broker replies no longer crash form extraction. Classification
  failures are isolated per message with three bounded attempts; the original
  encrypted mail remains available. AI reprocessing also has bounded isolation.
- A Gmail 404/410 between listing and reading creates a recoverable placeholder
  without blocking other messages. Authentication, rate-limit and service errors
  preserve the last successful sync checkpoint. Polling HTTP clients are closed.
- Partial-deletion classification behavior is unchanged, as requested.

## Verification

- 888 non-visual-file tests passed, one opt-in OS test skipped in the default run.
- 55 Chromium/WebKit browser tests passed, including the new startup setting in
  all four themes on narrow screens. This is 943 default tests passed overall.
- The opt-in macOS test was separately run successfully: an isolated, no-network,
  no-Keychain dummy job survived launcher return, deliberately exited with failure,
  and was restarted by real launchd. Its temporary job was unloaded afterward.
  No login item was installed and no real erase process was touched.
- Ruff passed. An upstream Starlette/httpx test-client deprecation warning remains.

`tests/test_campaign_month.py` advances a synthetic clock through 30 days using
the real scheduler, consent logic, database, reply handling and delivery ledger.
Gmail transport and AI are test doubles; external HTTP is prohibited in tests.

| Scenario | Observed result |
| --- | --- |
| Five days asleep/off; wake/restart recovery | Persistent work resumed; no missed-tick burst |
| Three days disconnected from Gmail | No sends on those days; polling and sending recovered |
| Daily limit of three, 30 synthetic brokers | 30 distinct initial sends, no duplicates, no daily-limit overrun |
| Twenty-day delayed deletion; routine receipts | 59 replies retained; 29 broker-reported deletions and one processing request |
| AI balance exhausted throughout reply handling | Rules continued; requests still sent and ordinary outcomes recorded |
| Poison classifier input plus malformed form URL | Other mail processed; poison stopped retrying after three attempts |
| Deletion waiting while a follow-up was overdue | Inbox processed first; unnecessary follow-up cancelled |
| Crash after reserving a delivery | Uncertain delivery held for review, never blindly resent |
| Message deleted / Gmail 401, 429 or 503 | Deleted message isolated; provider failures did not advance the sync checkpoint |

## What this does not promise

Nothing local runs while the Mac is asleep, logged out or off. Brokers can keep
processing requests already sent, and Gmail retains arriving mail; erase checks it
when it resumes. Gmail revocation or expired testing access still needs reconnection.
Moving/deleting the source folder or its Python environment can break a login item;
keep the install in place. Background startup does not grant permission to send.

The friends/source path is ready for a small reliability trial, not certified for
every Mac or for broker deletion success. Test installation, Keychain access,
actual sleep/wake, logout/login and reboot on clean Macs. The independent native
app artifacts from earlier work have not been rebuilt for this change.

Use the two-week, 3–5-person trial in [friends-preview.md](friends-preview.md).
Measure setup assistance, missed/duplicate sends, clarity of reconnection, and
weekly minutes of user effort. No friends were contacted as part of this work.

The existing running installation still needs its normal restart/rebuild to load
the changes. Do not point the desktop launcher at a legacy Docker database or
replace either installation's keys as an upgrade shortcut.
