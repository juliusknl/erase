# Workflow reliability — 1 October 2026

Priority: correct broker workflows before another dashboard redesign. No broker
contacts, disclosure fields, approval scope or email templates were expanded.

## Reproduced and fixed

Synthetic incoming mail went through the real capture, classification and workflow
code. Before the fix, the tests reproduced these defects:

- A receipt containing a privacy-policy link queued an automatic visit to that link.
- "We confirm that we received your request" created an unnecessary confirmation action.
- "Please confirm your email" put the case into processing before verification.
- A later receipt changed an unresolved form request back to processing.
- Repeated receipts restarted the follow-up clock instead of retaining its deadline.
- A legacy confirmation job treated any successful HTTP fetch as confirmation.

The root causes were conflating receipt and verification intent, selecting links
by domain alone, and unconditionally resetting processing state on receipt.

## New behavior

- Receipts and email-verification instructions are distinct classifications.
- Receipts do not open links, resolve outstanding tasks or extend scheduled waits.
- Verification creates one visible task. Reissued links update that task.
- A candidate verification link must be unique, HTTPS, same-domain, have an
  explicit confirmation/verification path and come from the new reply, not quoted
  history. Other links stay in the broker message for manual review.
- Generic confirmation jobs no longer fetch a URL or infer success from HTTP 200.
  Existing queued jobs are handed off for review; completed cases remain closed.
- "I confirmed my request" explicitly records the user step and resumes a
  follow-up timer. It does not record deletion. A later authenticated deletion
  reply records the separate outcome.
- Sender authentication, encrypted correspondence and CSRF protections remain.

Tests use synthetic domains, tokens and databases. They do not send broker mail,
visit real verification links, or establish real-world deletion outcomes.

## Verification and local deployment

- Full test suite: 613 passed, including 22 added regression cases. Ruff passed.
- Regression-first diagnosis and bug-fix checks reproduced failures before the
  changes; the focused simplification pass reused normalized reply text without
  changing the tested behavior.
- Encrypted backup: `backups/pre-confirmation-workflows-20261001.erasurebak`.
- Local Docker deployment rebuilt. Authenticated GETs for health, actions,
  requests needing attention and correspondence returned HTTP 200.
- Exact before/after comparison preserved all 834 case IDs, 18 completed outcomes
  and the campaign/consent checksum. SQLite integrity check passed.
- No private request was submitted to exercise these changes, and no historical
  messages or outcomes were bulk-reclassified. Nothing was pushed or published.

## Next workflow work

1. Broker-specific reply fixtures: distinguish no-match results that request more
   identifiers, conditional email fallbacks, form requirements and ticket closure.
2. Measure stalled requests across the actual approved campaign; keep a concrete
   next step for each exception without reopening completed outcomes.
3. Add automatic confirmation only for reviewed broker-specific routes with a
   tested success signal, expiry/error handling and replay protection. Same-domain
   links and HTTP success alone are insufficient.

## Deferred user interface work

The user explicitly deferred another redesign: Home responsiveness; independently
clickable Requests/Settings destinations with tidy submenus; restore the earlier
Home arrangement including the People Data Labs, LeadIQ, Lusha and Apollo.io size
and outcome showcase. Preserve sourced size claims and their evidence labels.
