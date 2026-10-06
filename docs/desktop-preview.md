# macOS desktop preview

This is a local development preview, not a notarized public download. It bundles
Python and locked dependencies; the user does not install Python, uv or Docker.
The current build was tested on Apple Silicon. Intel builds and a fresh Mac have
not been verified. Do not bypass Gatekeeper as a substitute for release signing.

## Build and check (maintainer only)

Use a uv-managed standalone Python on the target macOS architecture, with Xcode
command-line tools installed. From the app source directory:

```sh
uv run python scripts/build_macos.py --output dist/erase.app
uv run python scripts/smoke_macos.py dist/erase.app
codesign --verify --deep --strict dist/erase.app
```

The build refuses an existing output path and refuses missing license approval.
For a strictly local preview, `--allow-unlicensed-preview` makes that outstanding
decision explicit. This flag does not grant a distribution license. Builds include
only the release allowlist, never `.env`, personal databases, backups or parent
repository history. The runtime is isolated from shell Python settings and never
writes bytecode into the signed bundle. Ad-hoc signing is for local integrity
checks only, not publisher identity or notarization.

## Opening and running

1. Open erase. FileVault must be enabled. Choose a local dashboard password twice.
2. The browser opens the five-step setup: appearance, country, matching details,
   request mailbox, then one review and authorization.
3. Nothing sends before Start. Google setup is still required; AI is optional.
4. The launcher starts erase in the background and exits. Closing the browser or
   terminal is fine. Open erase again to return to the dashboard. Sleep pauses
   work; wake resumes it. Optional **Start erase when I log in** lives in Automatic
   emails. Disable it there to remove the login entry without touching your data.
   `uv run --locked erase --stop` quits a source install's background process.

If port 8787 is occupied by an older developer installation, the launcher refuses
to start a second server. Stop that installation deliberately or keep using it.
It never kills an existing process. A recognized running erase opens in the browser.
There is no automatic migration between developer and desktop data.

## Data and recovery

Private data: `~/Library/Application Support/erase/data/erasure.db`.
Keys: one login Keychain item named `erase.desktop.<installation-path-hash>`.
The item contains the master key, dashboard password hash and session secret.
Never delete it to reset a forgotten password. A database without its master key
is unrecoverable; retain a protected backup of both the data and the login Keychain.
The app cannot recover keys through an online account.

Maintenance commands below assume the app was placed in `/Applications/erase.app`.
They use the bundled interpreter, do not require developer tools, and never print
keys. Advanced support may be needed; a graphical recovery workflow is not included.

Create an encrypted, consistent backup at a **new** path (the app may keep running):

```sh
/Applications/erase.app/Contents/Resources/python/bin/python3 -I -B \
  /Applications/erase.app/Contents/Resources/app/scripts/desktop_entry.py \
  --backup /path/to/new-backup.erasurebak
```

If you forget the dashboard password, quit erase, then run:

```sh
/Applications/erase.app/Contents/Resources/python/bin/python3 -I -B \
  /Applications/erase.app/Contents/Resources/app/scripts/desktop_entry.py \
  --reset-password
```

Your unlocked login Keychain is the authority for this reset. The native dialog
asks for a new password; encryption stays unchanged and old browser sessions are
invalidated. Keychain denial or cancellation makes no changes.

For restoration, quit erase and preserve the existing data folder first. Restore
the private data folder and its matching Keychain entry together from your
protected system backup. Encrypted `.erasurebak` files use the existing backup
format, but the developer `erasure-keychain restore` command uses **different**
Keychain entries: do not run it against a desktop installation. A cross-Mac desktop
restore procedure still needs a clean-machine drill before public release.

## Removal

Disable **Start erase when I log in** before quitting, then revoke its Google
authorization. A source install quits with `uv run --locked erase --stop`.
Move the app and its specific
Application Support folder to Trash if no longer needed. Remove the matching
`erase.desktop.*` Keychain item only when you also no longer need its encrypted
backups. Other installations, exports, Time Machine copies, Google mail and broker
copies are separate. Do not delete a workspace, home folder or unrelated keys.
