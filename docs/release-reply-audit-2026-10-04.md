# Release reliability audit — 4 October 2026

## Verdict

The software can run a bounded email campaign without an agent. The audit found
real routing and interpretation defects and corrected them. It does **not**
establish that hundreds of brokers reliably delete records, that all forms have
been submitted successfully, or that a nontechnical person needs only ten minutes
per week. A limited beta is a defensible next milestone; a hands-off, universal
Incogni-equivalent claim is not yet supported.

This document records reusable lessons, not private email contents, addresses,
request identifiers or signed links. Account-specific repairs and the encrypted
pre-repair backup remain in ignored local `data/` storage.

## What was checked

- Read all 83 stored incoming messages, including old messages and quoted history.
- Reconciled current Gmail message IDs, including spam/trash: 78 returned, none
  absent from local storage. Five additional local records remain archived; they
  were not deleted just because Gmail no longer returned them.
- The initial snapshot associated messages with 54 cases. One association was
  incorrect: a Lead411 reply predating the Lead Spot case had been linked there.
  It was moved to Lead411 without changing either case's outcome.
- Re-fetched selected original messages to check missing bodies, vendor senders
  and delivery failures. Redmob's message still had no body in Gmail's response.
- Tested the revised Jev prompt against 49 independently labelled synthetic or
  paraphrased examples: 49 matching labels, zero false-Done predictions in this
  set. This small selected set is not a production accuracy estimate.
- Ran a read-only Jev comparison on all 77 linked stored replies: 76 evaluated,
  one empty reply skipped. Real messages still exposed uncertainty and errors.
  Evaluation neither changed statuses nor sent broker emails.
- Added a multi-day, no-AI/no-agent campaign regression: one permission, eight
  distinct deliveries across daily budgets, duplicate-dispatch protection, then
  receipts, deletion, no-match, form, information and bounce handling.
- Existing onboarding tests exercise the real setup-to-dispatch path with a fake
  mailbox. Simulated delivery proves application behavior, not broker fulfilment.

## Changes

### Better routes instead of repeated dead-end emails

The catalog contains **639 guides, 80 distinct executable email workflows and
125 guided manual resources** after this audit. These are different measures;
the guide count must never be presented as proven automated removal coverage.

Seven former email recipes were removed from the automatic pilot:

| Broker | What the observed reply taught us | Current path |
| --- | --- | --- |
| GRIN | Initial inbox directs individuals to its privacy form | Official form first; matching/confirmation steps documented |
| hireEZ | Routing inbox points to Own Your Data or a separate manual inbox | Portal guidance; `datarequests@hireez.com` recorded as observed, untested alternative; no agent API agreement for self-use |
| Mediavine | Old privacy inbox is not monitored | Official portal with relationship selection; publisher-browser choices kept separate |
| Datonics | Reply promises processing of the sender's hash, not every alias listed | Form for the actual email/device identities; dedicated-mailbox receipt not counted as broad deletion |
| HealthLink | Requires a new request from each matching email address | Explicit manual sender-address step; do not resend from the dedicated mailbox |
| Goava | Published mailbox rejected external delivery | Automatic route disabled pending a working replacement |
| MyGimi | Published recipient domain failed resolution | Automatic route disabled pending a working replacement |

Additional matching changes:

- ProspectBase requires the saved work email rather than a personal-email-only
  request unlikely to match its professional records.
- Vendelux includes a saved work email if provided, without requiring everyone
  to add one or disclosing unrelated profile details.
- Capaneo requires postal matching under the existing explicit address-sharing
  permission; it is not silently added to requests.
- Matchbook and Fraiser now have guides and manual resources. Matchbook needs a
  device identifier. Fraiser's public rights instructions are California-focused;
  European eligibility and interactive form operation remain unestablished.
- Intent IQ and Lead411's existing reviewed forms are now discoverable as manual
  resources. Optional sessions still show three actions, not the entire list.

Official route checks: [GRIN portal](https://grin.co/data-privacy-form/),
[GRIN EU/UK notice](https://grin.co/privacy-uk/),
[Mediavine's legal center](https://www.mediavine.com/legal-and-privacy-center/),
[hireEZ GDPR information](https://hireez.com/gdpr/),
[ProspectBase's UK-controller policy](https://www.prospectbase.com/legal/privacy-policy-uk),
[Matchbook's privacy choices](https://www.matchbookdata.com/your-privacy-choices/),
[Fraiser's form instructions](https://www.fraiser.org/ccpa).
Research fetches are not end-to-end form tests.

### Less avoidable homework

- Shared quote extraction handles German/French/Polish reply boundaries and
  flattened original erase requests, so the app does not treat its own original
  request as a new instruction from a broker.
- An explicitly separate right-to-know appendix is not treated as an ID demand
  for the user's own deletion request. The full email remains visible.
- Jev distinguishes search identifiers from identity documents, optional error
  resubmission from mandatory next steps, and reply-to-confirm from link verification.
- A deterministic guard preserves an explicit designated-form instruction when
  AI would otherwise call the reply a receipt or outcome.
- Advertising-ID drafts recognize plural identifiers/AAIDs. Reply-to-confirm
  messages get a short prepared confirmation, not an empty clarification template.
- Cancellation of a request or mailing-list removal cannot count as deletion
  merely because the text says something “has been removed.”
- Form actions use the reviewed public destination, including official third-party
  portals, and show the guide's steps. A generic next step is no longer silently
  replaced by an unrelated catalog form.
- Sender-address verification gets a specific email-only instruction and a way to
  record an externally sent request. Replies arriving in that other mailbox must
  be checked there; erase cannot claim to monitor an unconnected account.

Nine existing next-step records were corrected after review: Datonics, Intent IQ,
hireEZ, Dstillery, BH Marketing/US Marketing Group, GRIN, Sovrn, Fraiser and Mediavine.
No deletion was inferred from these corrections. No broker email was sent by the
audit or repair scripts; ordinary previously approved automation remains separate.

## All reply groups accounted for

| Broker(s) | Interpretation / reusable handling |
| --- | --- |
| People Data Labs | Separate portal receipt from explicit completed deletion/suppression |
| Apollo Interactive | Required form; distinct company from Apollo.io; country eligibility matters |
| Kaspr | Form and email verification; later matching request does not reopen user completion |
| LeadIQ | Removal form; survey/ticket closure alone is not deletion evidence |
| Hunter | No match for searched emails is limited in scope; optional professional lookup is not universal exposure |
| Lusha | Future promise is processing; later completed-removal message is different |
| HubSpot | Commercial dataset form differs from general account preferences |
| Seamless.AI | Form first, conditional email fallback, requested identifiers documented |
| RocketReach | Optional tool versus further profile matching; preserve existing manual outcomes |
| Apollo.io | No-match/matching instructions and removal form, not Apollo Interactive |
| Acxiom | Country/postal matching, limited no-match and separate suppression/Robinsonliste choice |
| SalesIntel | Out-of-office/queue/ticket closure is not completed deletion; ignore quoted request |
| Pipl | No matching profile, not deletion of an established record |
| Lead411 | Receipt versus later removal statement; incorrect cross-broker association repaired |
| Azira | Device-ID request; do not automatically provide unrelated name/address details |
| OnAudience | Pseudonymous dataset scope; ordinary names/emails may not be searchable |
| StackAdapt | Receipts, opt-out completion and deletion completion are separate events |
| Snov.io | No match for the supplied email, not proof about all identities |
| Redmob | Empty original body; bounded recovery and Gmail fallback, never invisible-message classification |
| Warmly | Routine processing receipt |
| Matchbook | Repeated request for mobile/device identifiers, now specific guided instructions |
| Outlogic | Device identifiers; opt-out differs from historical deletion; no generic automatic email route |
| Dstillery | Dedicated third-party privacy form, not general privacy-policy reading |
| Intent IQ | Browser/device/email choices; names alone are insufficient |
| Datanyze | Removal queue receipt; still not a deletion confirmation |
| Beeswax/FreeWheel | Routine support receipt; possible later ID request is not a current document demand |
| Trestle | Phone needed to locate records, not automatically a government-ID requirement |
| Disco | Support receipt with optional help links; no task solely from boilerplate |
| RevOptimal | Suppression and erasure messages differ; vendor sender requires independent trust evidence |
| Fraiser | Designated intake form; generic receipt must not hide the instruction |
| MarketOps / DealerX | No matching records; resubmission if the person believes it is an error is optional |
| BH Marketing / US Marketing Group | Access-only ID branch does not apply to self-deletion |
| Quadrant | Advertising-ID matching; don't republish inaccurate device-setting instructions |
| SignalHire | Send from a matching/business mailbox and identify the profile; form guide already exists |
| Datonics | Sender-only email-hash processing; further identifiers require privacy choices |
| hireEZ | Individual portal/manual route; agent API terms are not relevant to self-use |
| GRIN | Dedicated privacy form; employee-address bounces are not evidence the official privacy inbox failed |
| HealthLink | Requests from each matching mailbox, not a generic “I clicked confirmation” action |
| Vendelux | Provisional no-match with requested additional professional identifiers |
| Biscred | ID/representative authorization remains email-only; never auto-attach documents |
| Global Source Data Solutions | Restriction and erasure differ; vendor sender trust remains separate from AI interpretation |
| Goava | Delivery failure, automatic route disabled |
| Planet49 / Toleadoo / Aventura Post | Actual email-confirmation steps; signed links remain private |
| Capaneo / Schober | Postal matching under explicit address permission |
| ProspectBase | Corporate/work email is necessary for the professional search |
| SLS Data | French matching request; don't confuse quoted request text with the current response |
| Preqin | Processing receipt, not deletion |
| Sovrn | Simple confirmation reply prepared; optional form does not imply identity proof |
| MyGimi | Domain-resolution bounce, automatic route disabled |
| Mediavine | Unmonitored mailbox; relationship-scoped portal, not universal advertising deletion |
| Lead Spot | No received reply after removing the mislinked Lead411 message |
| Unmatched AdeptID-related message | Form notice through a vendor; public destination/association needs verification before reuse |
| Other unmatched messages | Three unrelated Google notices and two GRIN employee-address bounces; neither is a broker deletion outcome |

## Final verification

- Final core suite: **811 passed**, 51 visual tests deselected. The **51 browser
  checks passed across verification runs**, including Chromium and WebKit.
- Targeted lint checks passed. The catalog's initial-route consistency check
  passed; this does not substitute for end-to-end broker testing.
- Real and demo containers were rebuilt and reported healthy. The real health
  endpoint confirms live submissions remain enabled under existing permissions.
- Checked repaired broker pages and form/confirmation actions in the running
  app, database integrity, and Gmail/Jev health. The repair's second dry run
  proposed no further changes.
- Saved an encrypted backup before repairing live records. The audit sent no
  broker emails; previously authorized background automation remains independent.

## Remaining release gates

1. **Vendor sender trust:** authenticated vendor mail is not automatically proof
   of authority for every broker. Some Superset, Zendesk and Jira replies still
   require a person to recognize the sender. Add only independently evidenced,
   broker-scoped associations, not a blanket vendor allowlist.
2. **Interactive forms:** public links and instructions are checked, but JS forms,
   CAPTCHA, country branches and confirmation completion still need real testing.
   Do not call every `instructions_reviewed` guide a tested integration.
3. **Outcome evidence:** audit the provenance of historical manual Done/deletion
   choices before quoting a deletion success rate. Ticket surveys, no-match and
   manually finished forms must not inflate confirmed-deletion claims.
4. **Nontechnical pilot:** a fresh user must finish mailbox/optional-AI setup and
   run for 7–14 days without an agent intervening. Measure sent/delivered requests,
   actual outcomes and minutes of human work, not just tests or catalog size.
5. **Operational limitations:** the app must run locally; Gmail consent/token
   failures, country availability, stale instructions and unconnected matching
   inboxes remain real limits. Surface problems rather than calling idle work done.

No public push or publication was performed.
