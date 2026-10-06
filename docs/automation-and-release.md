# Automation and a credible free release

## Product decision

Use a deterministic local application as the primary product, with optional LLM help for unfamiliar replies and maintaining broker playbooks. Users should not need an agent subscription, repeated prompts, or a shared third-party mailbox. A model must not be the authority for recipient trust, jurisdiction, disclosing identifiers, sending, or claiming deletion.

## Implemented foundation

- Encrypted local profile/mail storage, authenticated Gmail access and durable monitoring.
- Bounded draft replenishment every five minutes while the app runs: signed, started, unpaused campaigns only; up to ten ready email drafts; recently verified active contacts only.
- Optional one-time campaign approval enables automatic sending, limited by a daily budget and an immutable preview/scope check. Manual batch mode remains available. No duplicate drafting for already queued/sent/closed requests.
- A one-minute campaign controller checks up to 25 explicitly approved workflows per tick against bundled reviewed evidence, without a daily research quota. This is not a fresh website audit. Exact consent, recipient and evidence-age checks still apply; unsupported routes remain outside automatic sending.
- An automatic delivery ledger guards managed sends, follow-ups and rechecks against duplicate dispatch, changed identifiers/recipients/consent and exhausted daily budgets. Crashes with uncertain outcomes stop for review.
- Known form/manual routes bypass generic email. Broker instructions travel with the repo.
- Reply drafts can request existing aliases and leave explicit placeholders for missing location/profile/device identifiers. Home addresses are not silently inserted.
- Reconciliation restores missing actions for requests already marked needs_action.
- Quick wins link to reusable public forms; completed linked requests stay Done. Case-specific signed URLs remain private.
- The overview distinguishes ready drafts, waiting requests and contacts needing research. Empty does not mean complete.

## Next steps, in order

1. **Broader tested playbook coverage.** Each broker needs entity identity, applicable region, accepted identifiers, verified destination, route, matching/verification steps, response fixtures, last-check date and failure policy. A registry row is a lead, not a deletion integration. Start with a measurable 25–50 end-to-end routes, then expand toward hundreds.
2. **Broaden contact research and maintain playbooks.** Conservative first-party contact verification and user review now exist. Still needed: signed/versioned catalog updates, better entity/region matching, reviewed alternate-domain contacts, and more tested form connectors. Arbitrary email addresses extracted from pages are never automatically promoted.
3. **Validate automatic campaigns with real users.** Snapshot-bound opt-in, preview hashes, a delivery ledger, daily limits and stop controls now exist. Test diverse accounts, recovery and real removal outcomes; improve broker/category selection before broad release. Existing installations are not silently opted in.
4. **Verified browser connectors.** Automate stable public forms and safe confirmation steps where permitted. CAPTCHA, ambiguous matching, sensitive identifiers, residency attestations and identity proof go into one exception queue. Never bypass these protections or sign false declarations.
5. **Optional local/BYO model.** Parse unfamiliar replies into a constrained schema: intent, cited evidence span, candidate link, requested fields, confidence. Treat email content as untrusted input. Validate candidates against reviewed routes and sender authentication; retain human review for uncertainty. No arbitrary tools, forwarding, new recipients or credential access from model output. Remote models need explicit privacy consent.
6. **One weekly review.** A concise digest: confirmed outcomes, forms needing a click, missing identifiers, expired contacts, failures and proposed new brokers. Batch approve low-risk drafts; one place to handle exceptions. Measure actual user time instead of promising ten minutes before testing.
7. **Portable onboarding and release hardening.** Document Gmail OAuth testing/expiry and per-user setup, packaging for nontechnical users, backup/restore, migrations, fresh-install tests, Gmail outage recovery, security review and license. Do not ship private correspondence, personal tokens, credentials or local state.

## Evidence required for the launch claim

Track eligible brokers, submitted requests, unique identifiers searched, explicit broker-confirmed outcomes, no-match scope, manual completions, unresolved cases, failed deliveries, user minutes/week and recurrence. Test on multiple independent users and fresh installations. Do not count a ticket closure, future promise, registry entry, or user tick as proof of deletion.

“A free, open-source, self-hosted alternative for managing data-broker removal” is a defensible description of the current direction. “Incogni-equivalent, reliably deletes from hundreds of brokers in ten minutes a week” is not yet demonstrated. Hundreds of supported routes require ongoing maintenance; self-hosted software can be free to use without claiming that maintenance or optional model usage has zero cost.
