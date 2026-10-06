# ChatGPT reply assistance

Settings → Automatic emails → Reply assistance → ChatGPT → **Continue with ChatGPT**.
The same popup is available in the last onboarding step. Jev remains available;
selecting a tab never switches a working provider. A completed connection does.

This uses the official [local/open-source ChatGPT plan flow](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
not an API key, a Codex subprocess, copied subscription credentials, browser
automation, or an undocumented ChatGPT endpoint. Eligible account plans, models
and allowances are controlled by OpenAI. No unlimited-use promise is made.
Use [ChatGPT Settings](https://chatgpt.com/settings/usage) to manage access and limits.

## What it does

One request per uncached broker reply classifies the existing status vocabulary.
Known profile details, emails, links and identifiers are minimized before sending;
this does not guarantee anonymization. No tools, attachments, profile database,
mailbox access or email-sending authority are supplied to the model.

The app uses `gpt-6-luna` and tests actual inference with four synthetic replies
before enabling it. Model-picker visibility is not used as an access gate. It never
silently selects a larger model or switches to another paid provider. The public
Responses API uses `store:false`, `stream:true`, a strict JSON schema and no chat
history. A completed stream, a valid category and a supporting quote are required.
ChatGPT's output is not represented as a calibrated probability. The existing
sender-authentication, disclosure, manual-action and workflow safeguards still apply.

Off, disconnected, usage-limited or failed assistance falls back to built-in rules.
Errors are visible in Reply assistance and provider retries have a 15-minute
cooldown. Existing completed requests are not reopened by backfill. A model can
still misinterpret text; schema checks and quotations do not prove accuracy.

## Connection and security

- Dynamic public-client registration, PKCE S256, session-bound ten-minute state,
  one-time callback consumption, nonce and signed ID-token validation.
- Exact issued-client audience and issuer checks; returning subject must match.
- A stable installation host ID and separate account/workspace registrations.
- Access/refresh/ID tokens encrypted in the existing local vault, never browser
  storage. Credentials are not placed in URLs. OAuth callback access logging is
  disabled in the supplied desktop/Docker launchers.
- Cross-process file locking serializes token refresh and account changes;
  rotating access/refresh credentials are saved together.
- A failed connection leaves the prior provider selected. Four synthetic samples
  check receipt, deletion, additional-information and misleading identity wording
  before ChatGPT is enabled. These checks use account allowance, not inbox text.
- A verified sign-in whose sample check fails is held separately and encrypted
  for a ten-minute test-retry window. **Retry connection test** does not repeat
  OAuth. No reply processing starts unless all four samples pass. Expired test
  credentials are cleared on the next settings view, retry or sign-in; disconnect
  also clears and revokes them. Changes to the selected provider invalidate a retry.
- Failure diagnostics retain HTTP status, allowlisted provider error code/parameter,
  request ID, sample number and structural parsing reason. Provider messages,
  model output, broker correspondence and credentials are not put in diagnostics.
- Disconnect clears credentials even if remote revocation fails, and explicitly
  tells the user to revoke in ChatGPT Settings when unconfirmed. Registration
  identity is retained for reconnecting. A request already in flight may finish.

Open the local app using its configured `http://127.0.0.1:<port>` address. This
flow is not designed for a hosted erase service or a non-loopback callback.

## Verification and repeatable live evaluation

Automated tests use synthetic signed identity tokens and mock provider responses.
They cover protocol validation, invalid callbacks, wrong identities, expired
tokens, rotation, account separation, refusals, malformed streams, late usage
errors, status updates, encrypted caching, disabled/demo behavior and browser UI.
Mocked fixture round-trips test integration, **not model accuracy**.

After connecting a real account, the full existing 49 labelled, synthetic or
paraphrased reply examples can be evaluated without sending broker emails or
changing requests. For the legacy Docker/Keychain installation:

```sh
uv run --locked python -m erasure.chatgpt_eval --live --keychain --database data/erasure.db
```

For the desktop installation, use `--desktop-data` with that installation's data
directory instead of `--keychain`, and pass its `data/erasure.db` as `--database`.
This explicitly uses ChatGPT allowance and may refresh saved credentials. Output
contains sample IDs and labels, not email bodies or credentials. It stops on the
first provider failure and exits nonzero for any wrong or incomplete result.
The real authorized connection and this 49-example evaluation passed on
5 October 2026. See [the dated verification record](chatgpt-verification-2026-10-05.md)
for the stream-reader corrections, exact results and limitations. A successful
sample evaluation does not guarantee every future broker reply is classified
correctly. These commands let another installation repeat the check.
