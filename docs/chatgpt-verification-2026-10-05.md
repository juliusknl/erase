# ChatGPT integration verification, 5 October 2026

Implemented and deployed locally to `http://127.0.0.1:8787`.
Current result: the user's authorized ChatGPT connection is enabled with
`gpt-6-luna`. The four connection samples and all 49 labelled evaluation examples
passed on the real account. Earlier evidence below records the implementation and
failures chronologically; those failures are not the current connection status.

## Current live result: finalized stream items

- The new encrypted diagnostic identified sample 1 failing with
  `unexpected_message_count_or_role`. Read-only probes using the verified candidate
  sign-in reproduced the cause: `response.output_item.done` carried a completed
  assistant message, but `response.completed` contained `output: []`.
- The reader now retains finalized items and uses them when the terminal output
  is empty. It still requires `response.completed`; partial deltas, an item marked
  done without response completion, failed/incomplete responses, duplicate or
  missing item indexes, refusals and unsupported evidence remain rejected.
- A second live probe found Luna wrapping a verbatim evidence excerpt in curly
  quotation marks. The prompt now explicitly requests an unchanged contiguous
  substring. The validator may remove one matching outer quote pair only when
  the entire inner text appears verbatim in the input. It never fuzzily matches
  or accepts a paraphrase. Prompt/cache version is `chatgpt-broker-replies-v2`.
- The four real samples passed before activating the user's pending sign-in.
  No further OAuth sign-in was needed. Candidate credentials and the old
  connection diagnostic were cleared after activation.
- The full real evaluation completed: **49 evaluated, 49 correct, zero false done**.
  It used only the existing synthetic/paraphrased fixtures, not inbox contents,
  and did not change requests or send emails. This is one observed evaluation
  run, not a guarantee for all future correspondence.
- Both local containers were rebuilt without resetting data. A post-deployment
  probe repeated all four real samples successfully against the deployed reader.
  An authenticated popup check returned 200, displayed `Currently using ChatGPT`,
  offered disconnection and showed no stale connection error or retry prompt.
- The authorized background worker subsequently reported 20 successful ChatGPT
  reply checks and no current provider error. The account remains selected and
  enabled. Ordinary campaign work continues under its existing authorization.
- Final lint passed. Focused nonvisual integration/setup suite: **248 passed**.
  Full nonvisual suite: **1,056 passed, 1 skipped, 71 visual deselected**. The skipped
  test remains the opt-in macOS lifecycle test. Added 22 regression cases across
  stream reconstruction and exact-quote formatting. A focused simplification
  review retained existing validation, credential and workflow boundaries.
- Encrypted pre-deployment backup:
  `backups/before-chatgpt-finalized-items-2026-10-05.enc`.

Everything remains local. No repository was pushed. The classifier fix changes
neither the non-AI partial-deletion behavior requested by the user nor the
separate catalog readiness gate at the end of this document.

## Initial implementation evidence

- `uv run --locked ruff check src/erasure tests`: passed.
- `uv run --locked pytest -m 'not visual' -q`: **991 passed, 1 skipped**;
  69 visual tests excluded. The skipped test is the opt-in real macOS lifecycle test.
- `uv run --locked pytest tests/test_chatgpt.py tests/test_chatgpt_workflow.py tests/test_reply_assistance.py -q`:
  **135 passed**, including six Chromium/WebKit cases. Screenshots cover all four
  appearances at 320, 790 and 1440 pixels; representative desktop/mobile images
  were also inspected visually.
- Mocked OAuth includes signed synthetic JWTs; malformed signatures, issuer,
  audience, nonce, expiration, subject and email claims are rejected.
- Two independent worker sessions refresh once, and a separate process holding
  the file lock prevents competing refresh. Rotated credentials persist together.
- Runtime tests cover every actionable status, confirmations, deletion/no-match,
  unverified senders, malformed/failed/partial streams, quota errors, cached
  decisions, provider switching, disabling and isolated demo behavior.
- All 49 existing labelled examples round-trip through the mocked protocol.
  This is integration coverage, not evidence of model accuracy.
- Official live OpenID discovery confirmed the configured authorization, token,
  JWKS and revocation endpoints, issuer, and RS256 signing algorithm.
- Hash-locked Python dependencies installed successfully in the local Docker build.
- Encrypted backup created before deployment. The real app's health endpoint
  reports `ok:true`, `configured:true`, `live_submissions:true`, `demo_mode:false`.
- An authenticated HTTP check confirms the real campaign page renders the ChatGPT
  button/tab. The server exposes connect, callback and disconnect routes. The
  previous Jev provider still reports enabled with its saved key present.
- The supplied Docker launcher now disables access logging to keep OAuth callback
  codes out of URL logs. CSP remains `form-action 'self'`; browser sign-in starts
  through a CSRF-checked fetch followed by navigation.

## Initially outstanding live evidence

No real ChatGPT connection or full model comparison has been claimed. The user
must authorize the account in the browser. Four synthetic classifications are
checked automatically before activation; the separate full-fixture evaluator is
ready to run after that. Email sending continues independently of assistance.
See [connection details and evaluation command](chatgpt-reply-assistance.md).

Everything remains local. No repository was pushed and no test sent broker email.
The existing authorized campaign resumed normally after the local update.

## Follow-up: Luna access check

The first real sign-in was rejected by the model-catalog gate before any sample
inference. `gpt-6-luna` was already the configured model. Catalog `visibility`
describes model-picker entries; it is not a successful inference test. The gate
has been removed and the four sample requests now test Luna directly. OpenAI
access denial, wrong classifications and usage limits still prevent activation
and leave the existing provider unchanged. No larger-model fallback was added.

- Focused nonvisual ChatGPT, workflow and assistance tests: **133 passed**.
- Onboarding tests: **21 passed**, including both provider tabs and a simulated
  ChatGPT connection returning to the unfinished setup without starting emails.
- Provider-popup browser tests: **6 passed** across Chromium and WebKit.
- Lint passed. A focused code-simplifier review removed the redundant catalog
  request; credential validation, sample checks and workflow safeguards remain.
- Encrypted backup: `backups/before-luna-access-fix-2026-10-05.enc`.
- Live health probe passed. The deployed classifier reports `gpt-6-luna`, four
  connection samples and no catalog gate. Existing sending permission was retained.

These are mocked integration checks. The rejected sign-in retained no usable
ChatGPT credentials. A fresh user-authorized connection is still needed to
establish whether this account can actually run Luna, and to run the 49-example
live evaluation. The rejection does not prove inference itself would be denied.

## Follow-up: opaque stream failure

A later real attempt returned `chatgpt_invalid_response`. The previous build
discarded the error details and candidate credentials, so its exact cause cannot
be recovered from that message. This is not evidence that live ChatGPT assistance
works or that the provider failure has been fixed.

- Error handling now distinguishes documented eligibility, usage, unsupported
  capability, route, signed-permission and model errors in HTTP and SSE responses,
  including top-level SSE error events. It stores sanitized structural diagnostics
  encrypted locally, never provider messages or response content.
- A verified candidate sign-in is retained separately for a ten-minute test-retry
  window. Retry is CSRF protected; expiry, a changed provider and disconnection
  prevent activation. No OAuth exchange repeats on retry. All four sample checks
  must still pass before replacing Jev; no automatic model fallback was added.
- Disconnect revokes the candidate credential too. Tests verify that unsuccessful
  reconnection does not replace the existing working credentials.
- Fixed a WebKit popup close-event race that was clearing the query URL during
  initial modal opening.
- Latest complete nonvisual suite: **1,034 passed, 1 skipped, 71 visual deselected**.
- Focused suite including setup: **192 passed**; popup Chromium/WebKit checks:
  **8 passed**. Lint passed. These remain mocked provider tests, not live accuracy.
- A code-simplifier review retained the existing security boundaries and shared
  four-sample check, with diagnostics separated from user-facing error messages.
- Both local containers were rebuilt without resetting their data. An authenticated
  live popup probe returned HTTP 200; both health probes passed. Jev is still enabled.
- Encrypted backup: `backups/before-chatgpt-stream-diagnostics-2026-10-05.enc`.

At handoff no fresh attempt had populated the new diagnostic record. A user sign-in
is required once more to capture the real failure. The 49-sample live evaluation
is still pending. No test sent broker emails, and nothing was pushed.

## Separate catalog release gate

Source packaging checks do not prove that the full broker inventory is complete.
The current `mvp_readiness` result is `ready:false`: 1,205 inventory records,
776 assessed, 429 awaiting assessment, 116 unresolved assessments, and 66
unresolved guides. Reviewed email workflows have no missing executable recipes.
These are separate catalog work items, not failures of this ChatGPT integration;
the full public-catalog objective remains unfinished.
