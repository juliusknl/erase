# Distribution: friends first, public later

Agreed 2026-10-05: GitHub/source distribution with short coding-assistant prompts.
Do not wait for an Apple Developer account or package the unsigned Mac preview as
the recommended download. Do not publish or push until the owner explicitly asks.

## First: a small friends round

- Pick a few Mac users, including people who are not developers. Prefer EU/EEA
  residents for testing the current automatic-email path; label manual-only scope.
- Supply one clean source snapshot, one README and the one setup prompt. A friend
  can download a ZIP without learning Git. Never share the author's workspace,
  personal Google project, mailbox, `.env`, data or Keychain entries.
- Let friends attempt setup before coaching. Record where they needed help,
  time to dashboard, Google connection and first actual send. Do not substitute a
  fake/demo send for delivery evidence. They keep their private evidence locally.
- Check back after a week: did work continue, were replies understandable, did
  Gmail reconnect cleanly if needed, and could they handle the next action?
- Fix repeated friction before inviting more people. No claim of a ten-minute
  setup or weekly effort until friends' experience supports it.

Private sharing is still distribution: license and third-party notices stay in
the archive. A repo is not created by this document. When approved, create a clean
standalone repository from the allowlisted export, not this parent repository or
its history. Do not silently broaden a private test into a public launch.

## Later: make it easy to understand and share

- One obvious README action: download/open in Codex or Claude Code, paste the short
  prompt. Keep the manual one-command route next to it. Put technical reference
  below the fold. Don't make AI access a requirement to use erase.
- Release a tagged, tested source snapshot with a matching ZIP/checksum and short
  change notes. Preserve user data across updates; no installer that resets state.
- Make a brief screen recording using synthetic data: start, automatic progress,
  a broker reply, then one manual action. Never show the personal mailbox.
- Publish an honest build story with the repo and demo clip. Suggested framing:
  “I built a free, open-source app for data-broker removal requests. It handles
  supported emails; some brokers still need a form.” Explain current country/OS
  scope and the Google setup step. Do not claim complete Incogni parity.
- Share first with the existing audience, then relevant privacy/open-source
  communities where their current rules allow it. Choose channels and timing at
  launch, not months in advance. No unsolicited bulk messages or automated posting.
- Measure success through voluntary feedback: people reaching a verified first
  send and understanding replies, not catalog size or GitHub stars alone.

Public launch remains gated on the friends results, reproducible source checks,
privacy/security review and honest coverage documentation. Google public OAuth
and signed desktop downloads can be future improvements, not prerequisites for
this explicitly self-configured source preview.
