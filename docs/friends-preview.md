# Try erase

For now, this is a small friends preview on Mac, distributed as source. No Apple
Developer account or signed app download is part of this route. Google setup is
still required for real email. A coding assistant helps install it; it is not
needed to keep the campaign going.

## Before you start

Unzip the download and keep the **erase** folder somewhere permanent, such as
Documents. Open that folder in Codex or Claude Code, with local terminal access.
The assistant can install uv and the locked dependencies. **No Docker, Homebrew,
Xcode, manual Python installation, `.env` editing or paid server is needed.**
FileVault must be on; the app checks it. You choose a local dashboard password and
approve your Mac's Keychain prompts yourself.

Use a personal Gmail account, ideally a separate inbox just for broker requests.
Your everyday personal/work email addresses go in **Your info** so brokers can find
existing records. They needn't be the inbox connected for sending. A work/school
administrator may block Google access; the assistant must not bypass that restriction.

## Three short prompts

Open the downloaded erase folder in Codex or Claude Code.

**Set it up**

> Read `docs/assistant-setup.md`, install and open erase, then guide me through Gmail
> setup one step at a time. Keep my data private; I'll enter secrets and click Start.

**Help with Google**

> Help me through erase's Gmail setup, one step at a time. Follow
> `docs/assistant-setup.md`; I'll sign in and import the JSON directly in the app.
> Don't ask me to paste any secrets here.

**Something isn't working**

> Diagnose my erase setup using `docs/assistant-setup.md`. Don't read private mail,
> expose secrets, send requests, change permissions or reset anything. Give me the
> simplest fix, or a redacted error I can report.

## The Google step

Each friend creates their own Google project using the app's short helper. Enable
Gmail API, choose **External**, add the request inbox as a test user, and create a
**Web application** client, not a Desktop client. Copy the callback address from
the app exactly, download the client JSON and import it directly into erase.
Never send that file or any secrets to the assistant or a project maintainer.

This setup needs no paid cloud server. Google's
[standard Gmail API usage is available at no additional cost](https://developers.google.com/workspace/gmail/api/reference/quota)
within its limits. Do not enable paid products just to connect Gmail.
An unverified-app warning may appear: continue only for your own project whose
permissions you understand, never someone else's project or a managed-account block.
In **Testing**, Google normally expires this connection after seven days. Use the
app's reconnect button with the same inbox; your history stays intact. See
[Google's token-expiry guidance](https://developers.google.com/identity/protocols/oauth2#expiration).
Publishing a shared public Google integration is not part of this friends setup.

## What happens after Start?

The app sends eligible emails, reads replies and schedules supported follow-ups.
The default limit is 20 automatic emails per day. Home shows progress and anything
that needs you. Forms remain manual; identity documents are never sent automatically.
No AI subscription/key is required to run the campaign. Optional reply assistance
can use Jev or an eligible ChatGPT account to sort replies. The selected provider
receives minimized reply text and uses its own credits or account allowance.

You can close the terminal and browser. The app runs in the background, pauses
while the Mac sleeps, and catches up when it wakes. Optionally enable **Start erase
when I log in** in Automatic emails so restarting the Mac needs no extra step.
It cannot work while the Mac is asleep or off.
To reopen, run `uv run --locked erase` from the same source folder. Your data lives
outside that folder. Don't delete Keychain items to fix a login problem.

## If you're stuck

| What you see | What to do |
| --- | --- |
| `uv: command not found` | Use the setup prompt, or follow [uv's install instructions](https://docs.astral.sh/uv/getting-started/installation/). |
| FileVault or Keychain access is required | Follow the Mac's prompts yourself. Do not disable encryption or delete keys to get past them. |
| The password dialog is asking for a password | Choose a new local erase password of at least 12 characters, not your Google password. |
| Google says access is blocked or redirect doesn't match | Follow the app's Google helper; verify your own project, test user and exact callback URL. |
| Gmail needs reconnecting | Reconnect in the app with the same request mailbox. Testing-mode Google access can expire after seven days. |
| Another app uses port 8787 | Don't kill it blindly. Ask the assistant to identify what's running. |
| I forgot the dashboard password | Run `uv run --locked erase --stop`, then `uv run --locked erase --reset-password`. Unlock your own login Keychain if asked. |
| My country has no automatic email plan | Use the available forms. Do not choose another country to bypass this. |
| Requests haven't sent yet | Check Home's status. Confirm you've selected Start and connected Gmail; sends are spaced out and capped at 20/day by default. The assistant must not click Start for you. |

## Tell me what got in your way

Send the step you reached, what you expected, what happened and your macOS version.
Redact screenshots before sharing. Never send your database, keys, Google JSON,
mail contents or full logs. For this round, direct feedback is enough; no analytics
or long survey. Especially tell me when you needed help or couldn't tell whether
the app was working.

For a small trial, use 3–5 friends for two weeks. Ask only: could you finish setup
without help, did requests go out after reopening/waking, and how many minutes did
you spend handling tasks this week? Success means no lost/duplicate sends, clear
reconnection instructions, and routine weeks under ten minutes. Track failures and
assistance needed, not private message contents. A clean-Mac installation and real
sleep/reboot trial are still necessary; simulated time cannot prove those work on
every Mac or that brokers actually delete data.
