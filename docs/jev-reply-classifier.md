# Optional AI reply interpretation

The mailbox worker can use Jev to interpret broker replies, reusing the existing
status and next-step workflow. The app still works without an AI key.
No SDK, new database table or additional service is needed.

## Enable automatic interpretation

Open **Settings → Automatic emails → Reply assistance**. The same optional popup
is available on onboarding's final review step. Paste a TypeSafe key and choose
**Connect and enable**. The connection test sends only a fixed synthetic message;
the key is saved in the encrypted `reply_assistance` setting only after success.
Failed replacement attempts preserve the previous working configuration. Keys
are never included in page HTML or status responses. No restart is required.

Enabling this consents to sending minimized broker-reply text to TypeSafe;
see the privacy boundaries below. Use **Turn off** to stop new classification
calls; an in-flight call may finish. **Disconnect** removes the app's saved key
and leaves assistance off. Neither action changes email permissions or outcomes.

Existing `.env` settings (`TYPESAFE_API_KEY`, `ERASURE_JEV_ENABLED=true`) remain
supported until the user configures assistance in the UI. The saved UI setting
takes precedence, including Off, so an environment key cannot silently reactivate
assistance. Disconnect does not edit the environment file; its key is ignored.
The standalone evaluator continues to use its explicitly supplied environment key.
The demo uses a simulated connection, never stores an entered key, and never
calls TypeSafe.

- Receipts and processing updates stay out of Needs you; authenticated deletion
  and no-match reports update outcomes. Forms, verification and information requests
  use the existing next-step panels. AI never authorizes a new disclosure or recipient.
- Accepted classifications replace obsolete tasks for **that message only**.
  A receipt does not erase a separate outstanding form or verification request.
- Each mailbox poll also checks up to ten previously processed latest replies on
  open requests. Completed requests and later manual decisions are preserved.
- Decisions are encrypted and cached by message content, request and prompt/model
  version. Restarts and repeat polls do not repeat successful API calls. Decisions
  and their confidence are retained in the request's audit history.
- Thresholds are 0.85 for deletion/no-match, 0.50 for other non-ambiguous labels.
  These are conservative starting thresholds, not calibrated accuracy guarantees.
  Uncertain historical interpretations leave existing workflows unchanged; new
  uncertain replies use the existing rules but cannot produce a terminal outcome.
- API failures fall back to existing rules and pause AI calls for 15 minutes;
  eligible open requests are retried later. A failed classifier does not break Gmail
  sync. Empty and overlong replies are skipped, with existing rules retained.
- Sender checks remain independent. Unverified mail cannot establish deletion;
  routine unverified messages can stop generating unnecessary human tasks.
- Turning assistance off in Settings stops new external classification calls.
  It does not undo recorded outcomes. Existing manual outcome correction remains available.

The popup's estimate uses the recorded 84,296 input tokens / 69 replies below and
the provider's $0.042 / million input-token price checked October 3, 2026. At that
rate, $5 is about 97,000 similar replies, rounded to roughly 100,000. This is not
a lifetime or accuracy guarantee. TypeSafe's checkout minimum was not verified;
the popup links to current pricing without claiming a minimum. Standard purchased credits expire after 12 months
under https://typesafe.ai/legal/mca, unless their order states otherwise. No signup
credit is promised.

The encrypted `jev_health` setting records last success, safe error codes, cooldown
and cumulative token usage. No API response body or secret is logged.

## Run the comparison

From `tools/erasure`, run the local rules baseline (no network):

```sh
uv run python -m erasure.jev_eval --fixtures tests/fixtures/jev_replies.json
```

For real Jev evaluation, put `TYPESAFE_API_KEY=...` in the ignored `.env` file,
or set it in your environment. Do not put it in code or paste it into chat.

```sh
uv run python -m erasure.jev_eval --fixtures tests/fixtures/jev_replies.json --live
uv run python -m erasure.jev_eval --inbox data/erasure.db --keychain --live
```

The second command reads the Mac's existing master key from Keychain; elsewhere,
set `ERASURE_MASTER_KEY` and omit `--keychain`. SQLite is opened in `mode=ro` with
`query_only=ON`; no application worker is started. Only incoming messages already
linked to requests are evaluated, oldest first, up to `--limit` (default 100).
No automatic retries. Provider/authentication/schema failures stop the run.

The fixtures contain reviewed paraphrases of the September 28 broker-reply audit,
plus synthetic counterexamples: future and negated deletion, stale subjects,
quoted messages, partial deletion, required steps after acknowledgements,
conditional email fallback, multilingual replies and injected instructions.
They are **not a raw private-mail dump**. Inbox results have no ground-truth label:
agreement with the old rules is not proof of accuracy. Reports contain only IDs,
labels, probabilities, model version and token usage, not message contents.

## Boundaries

- Fixed endpoint and pinned `jev-1.13.0`; no redirects, tools or action permissions.
- `broker-replies-v1` identifies the prompt. All reply labels have explicit criteria.
- Required steps take precedence over receipts and provisional no-match statements.
- Suppression-only and ticket closure are informational, not reported deletion.
- Confidence is Jev's distribution statistic, **not a measured accuracy percentage**.
- Sender authentication remains a separate local check; this classifier cannot verify it.
- Quoted prior messages are removed with the existing reply parser. Known profile
  values, email addresses, URLs (including signed links), long numbers and tokens
  are redacted before transmission. No headers, attachments, full profile or unrelated
  mailbox contents are sent. Redaction is best-effort, not guaranteed anonymization.
- Empty and overlong replies are skipped rather than guessed or silently truncated.
- TypeSafe receives minimized text only when runtime interpretation is enabled,
  or when the separate evaluator is run with `--live`.
  Its policy says inputs are not used for training, but describes US hosting and
  does not promise zero retention. Use requires consent to this external processing.

## What counts as tested

Unit tests use an HTTP mock to check transport, response validation, failure handling,
redaction and read-only evaluation. **They do not measure Jev's semantic accuracy.**
Only an actual `--live` run tests the model. Check `false_done` and inspect disagreements;
don't tune and report performance on the same examples as if they were held-out evidence.
Real-inbox labels must be reviewed independently before quoting an accuracy figure.

The evaluator remains **read-only**, independent of the runtime enable flag.
Integration tests separately check persisted messages, state changes, task cleanup,
manual-decision preservation, sender checks, caching, API failure and recovery.

## Initial live results — 2026-10-02

With `jev-1.13.0` and `broker-replies-v1`, before any prompt tuning:

| Dataset | Result | Input tokens | Estimated API cost |
| --- | --- | --- | --- |
| 42 reviewed audit paraphrases and synthetic edge cases | Jev 42/42 expected labels; existing rules 21/42; zero false Done labels | 40,905 | $0.00171801 |
| 70 stored, linked broker messages | 69 evaluated; 1 missing body skipped; 50 labels differ from existing rules | 84,296 | $0.00354043 |

These are separate measurements: **there is no 69/69 accuracy claim for the inbox**.
The fixture set was deliberately challenging for phrase matching, not a representative
random sample. The model saw texts and criteria, never the expected labels.
Actual-inbox disagreements include finer routing (generic action → form), clear
receipts/completions missed by the rules, and uncertain interpretations of optional
routes. A spot-check of the actual deletion-completion predictions found supporting
statements, but this does not validate every next-step prediction or sender.
PDL's optional self-service response, HubSpot's mixed routing and Acxiom's optional
suppression offer deserve review before integrating automatic state changes.

Known limitation: one status label cannot retain both a no-match result and a separate
optional suppression offer. This pilot classifies the primary outcome only; it must
not be treated as a complete extraction of every useful step in a reply.
No broker emails were sent and no request records were modified by the evaluator.
Subsequent redaction hardening strips localized quoted-message delimiters and ticket
tokens; rerun counts should be recorded separately from these initial measurements.

## Runtime verification — 2026-10-02

Enabled on the local installation after an encrypted backup. The normal mailbox
worker reinterpreted all eligible historical replies: 28 model decisions, one empty
reply skipped, 34,527 input tokens. One low-confidence decision retained the previous
workflow. No completed requests were reopened; the database integrity check passed.
One unnecessary attention item cleared and one new required step surfaced, leaving
21 requests needing a person. Classification does not itself fill forms or provide
identity documents, and this is **not evidence of a 99% reduction in user work**.

Verification: 725 nonvisual tests passed, lint passed, and authenticated HTTP checks
returned 200 for the live dashboard, request list and broker-page tabs. The worker
had no classifier error and no eligible historical replies awaiting interpretation.

Sources: [API](https://docs.typesafe.ai/api),
[models and pricing](https://docs.typesafe.ai/models),
[confidence](https://docs.typesafe.ai/confidence),
[known limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13),
[privacy](https://typesafe.ai/legal/privacy-policy). Checked 2026-10-02.
