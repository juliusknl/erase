# Home, attention and request workflow completion

Local-only implementation; no publishing or new sending authorization.

## User-facing behavior

- Home shows automation health, its specific recovery control and the last successful mailbox
  check. Status refresh updates these values without replacing open forms.
- Quick wins remain an independent session of up to three, including while other requests need
  attention. The large-broker showcase follows the useful actions instead of preceding them.
- Requests provides search, All / Needs you / Waiting / Done, and unmatched mail in the same
  location. Legacy `/actions` and `/inbox` URLs redirect here; their POST endpoints remain for
  compatible, authenticated actions.
- Normal broker pages show instructions and the relevant message, not classification dropdowns.
  Manual outcome correction is explicitly accessed through Details. No arbitrary approval expiry
  appears as a user deadline. The underlying verification boundary still applies.
- Request recency uses correspondence and workflow milestones rather than background bookkeeping.

## Handling replies

One shared `needs_person` rule drives Home, Requests, broker panels and optional alert emails.
Concrete steps include forms, confirmation, identifying information, identity proof and escalation
drafts. A missing body, authentication result or classification is not by itself a human task.

Known receipts and processing updates retain waiting/follow-up behavior. A resolved support ticket
is informational, not proof of deletion. Unknown language remains in the conversation without
inventing a task or deletion outcome. Conditional privacy instructions remain actionable; optional
support footers do not. The shared rules are deterministic and do not require an AI account.

Unverified instructions still require explicit sender review before being applied. Merely linking
unmatched mail never certifies its sender. Unverified completion claims are retained but do not
automatically count as deletion.

Existing ambiguity-only holds are reconciled at startup and on mailbox checks. Genuine steps and
terminal cases are untouched. Reconciliation records an audit event and preserves/reinstates a
follow-up; it never claims deletion or changes campaign consent.

Missing bodies get up to three retrieval attempts, with durable backoff and a ten-message-per-poll
cap. Authentication/transient network failures do not consume the content-attempt budget. After
exhaustion the page offers a Gmail message lookup where an ID exists. Durable pending-processing
records allow processing to retry after a crash without requiring another download. A malformed
individual email does not stop the rest of the mailbox from being downloaded.

## Verification

Regression-first fixes and a simplification pass consolidated task eligibility and retained ordinary
link navigation. The final full suite passed 648 tests, including browser checks. After local
deployment, 202 authenticated page checks passed: three quick wins remained available, ten requests
needed attention, legacy routes redirected correctly, and normal pages had no classification
dropdowns. Automation reported Running with a successful mailbox check just now. A read-only
before/after comparison confirmed unchanged case IDs, completed outcomes and campaign consent;
SQLite integrity check returned `ok`. The live read-only audit
found 17 pending records across active requests: 11 actionable records in 10 requests, and six
informational/uncertain records. Audit examples specifically protect Dstillery, Intent IQ and Fraiser
instructions from being mistaken for optional footer text.

Pre-deployment encrypted backup: `backups/pre-simple-workflows-20261001.erasurebak`.

Limits: recognition is conservative and not comprehensive natural-language understanding; the
conversation remains the source of evidence. Form completion does not imply confirmed deletion,
and database size is not exposure coverage. Some catalog routes still require research or a person.
