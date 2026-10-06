# Email-first, small manual sessions

The primary user is busy and nontechnical. The broker catalog is supporting
knowledge, not a task list. No AI is required for the existing email controller.

## Implemented experience

- Home, Requests and Settings are the only primary navigation destinations.
  Requests and Settings are clickable destinations; their separate chevrons expand
  keyboard-accessible sidebar submenus. Home retains the sourced broker showcase.
- Prominent Requests sent / Requests completed counters stay on Home. Sent counts
  distinct cases with a successful submission event, not follow-ups or checklist
  ticks, and includes requests that have since completed. Completed combines user
  completion, reported deletion and no matching data; it is not a deletion claim.
- Home puts the approved email plan first, then at most three outstanding or
  optional actions. Internal research counters and batch controls are expandable.
- Requests includes a unified "Needs you" list. Outstanding approvals link into
  the broker's request, with shared decision controls, messages and prepared replies
  in one place. The full mailbox (including unlinked mail) and broker library are
  available as secondary references. Legacy action URLs still work.
- Action cards show category and instructions, with requirements, scope and
  evidence expandable. Repeated benefit/outcome paragraphs are no longer mandatory
  reading on each recommended card.
- Explicit requests for matching identifiers take precedence over a no-match
  result. Follow-ups stop pending the user's response; submitted replies resolve
  the information task. Failed reply validation preserves the edited text inline.
- Known email workflows take priority: optional form suggestions exclude routes
  with a fresh email recipe for the selected country. A user can still browse all
  forms, with an email-plan link where an email option exists.
- Open/sent requests and completed cases are not suggested as new form tasks.
- A session contains three suggestions. Its membership freezes on the first
  completion, postponement or skip; finishing one doesn't refill the list. "Do more"
  explicitly starts another selection. Browse all is always available.
- Later hides a suggestion for seven days. Not interested hides it until restored.
  Neither grants/revokes sending consent, stops an existing request, or records a
  deletion. Those controls only manage optional suggestions.
- Email alerts are optional and off for new profiles unless an address is supplied.
  Existing installations' alert choices remain unchanged. No weekly reminder was added.

## Explainable recommendation order

1. Outstanding decisions, with dated approvals first. Deduplicate by request.
2. Exclude unreviewed/stale, uncertain-region and specialist credit/identity-risk
   routes from new suggestions. Keep them available in the full reference library.
3. Match explicit positive geography tags to the selected residence. Never treat
   a headquarters, a mention of GDPR, or "EEA scope unconfirmed" as eligibility.
4. Prioritize public people search, then professional/recruitment distribution,
   then marketing lists, then advertising controls. This is an editorial default,
   not a measured ranking of harmful companies or individual exposure.
5. Within a category, fresh sourced database-scale context can raise a suggestion;
   documented requirements and fewer matching fields break ties. No estimated
   minutes, personal-exposure percentages or combined database-size claims.

Every card explains its category and intended effect. Exact steps, fields,
verification requirements, caveats and evidence remain expandable. The public
sources establish possible relevance, not that the company holds this user's data.

## Country boundary

Manual recommendation filters include EEA countries, UK, Switzerland, US, Canada,
Australia and New Zealand. Positive global scope may be recommended across these
countries; detailed route conditions still require review. Uncertain or state-only
scope is excluded rather than guessed. This conservative matcher is not exhaustive.

Automatic email recipes remain EU/EEA-only. Selecting another country does not
expand their eligibility. The campaign and setup screens explicitly show this
limit rather than defaulting an international user into European email consent.
Changing only the recommendations country never changes an existing approved plan.

## Preserved boundaries and remaining work

No new broker recipients, automatic form submission, AI access, reminder opt-in,
or live sending authority are introduced. GET views do not write recommendation
state. State changes use authenticated, CSRF-protected POSTs. Existing case IDs,
completed outcomes and the encrypted campaign consent are preserved at deployment.

This is the first usability implementation, not a finished Incogni replacement.
Still needed: validated additional-country email recipes, broker-specific priority
review beyond category defaults, richer context within the request-detail screen,
clean-machine installation and independent real-user outcome/time testing.

## Local verification — 2026-10-01

- Full suite: 591 passed; Ruff clean. Chromium and WebKit cover the small-session
  journey, with mobile/desktop layout and real authenticated form submissions
  against temporary databases. No live broker submissions are used by these tests.
- Repeated the full suite after restoring the progress counters and expandable
  sidebar: 591 passed. Local authenticated checks confirmed the counters, submenus
  and linked request views after redeployment. The campaign page initially timed
  out at 30 seconds; a retry returned 200 in 12.51 seconds. Its latency still needs
  improvement; the dashboard returned 200 in 1.64 seconds on that retry.
- Public-catalog pilot audit passes; the whole-inventory gate still has the
  previously documented research gaps. This UI work does not reclassify them.
- Local deployment rebuilt after an encrypted backup at
  `backups/pre-simple-home-20261001.erasurebak`.
- Exact private-state comparison preserved all 834 case IDs, all 18 completed
  outcomes and the encrypted campaign/consent checksum; SQLite integrity is OK.
- This is local-only work. No publication or repository push was performed.
