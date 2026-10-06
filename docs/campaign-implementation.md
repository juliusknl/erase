# Autonomous campaign implementation

The product must progress without a coding assistant or repeated batch approval.
This work stays local and preserves all existing case outcomes.

## Contract (version 2)

- One explicit opt-in authorizes ongoing reviewed requests, residence, saved
  matching identifiers and a daily sending limit. The `include_new` permission
  adds newly reviewed routes for default broker categories automatically. Legacy
  plans without that permission remain fixed; they are not silently opted in.
  Postal-address sharing remains separately controlled.
- A durable campaign controller checks maintained workflow evidence, prepares eligible
  requests, and schedules sends each day. Limits reset with UTC days; exhaustion is
  a wait until tomorrow, not the end of a campaign. No LLM or paid API is needed.
- Every executable route is tied to a reviewed guide and dated official evidence.
  It names the exact recipient, required fields, applicability and intended effect.
  Public research is shared maintenance, not repeated on every user's computer.
  Sources expire after 90 days; installing the catalog does not renew that date.
- Postal address is included only with explicit permission and only for workflows
  requiring it. Other personal fields are not silently added. An approved preview
  may update an unsent request's recipient, never an already-submitted request's.
- Version 1 campaigns pause until the user reviews the new messages once. For
  continuous plans, each tick adds eligible new routes before research/preparation.
  It does not replace existing approved templates, redirect submitted requests,
  reopen completed requests or enroll duplicate aliases. Changed existing routes
  still fail closed; unchanged approved workflows continue.
- Automatic email delivery uses a durable per-case/attempt ledger, exact payload
  hashes, dispatch-time consent checks, and an atomic daily budget. An interrupted
  send is held as uncertain, never blindly replayed. This is at-most-once safety,
  not a claim that Gmail supports exactly-once delivery.
- Forms, CAPTCHA, missing identifiers, credentials and complaints remain human
  steps. No arbitrary browser automation or identity-document sending is added.
- Existing follow-ups and recurrence join the guarded dispatcher for managed cases;
  pause/disable must also stop already queued automatic work.

## Acceptance tests

Fresh signed account → opt in → source verification → preparation → send → reply
processing, without a chat agent; next-day continuation beyond the first batch;
restarts and repeated ticks do not duplicate sends; paused/changed consent, changed
recipient, stale contact, uncertain Gmail outcome and daily limits all fail closed;
private/network targets and cross-domain redirects are blocked; dashboard shows the
plan, progress, next work and review exceptions. Use synthetic mail transports for
send tests, not the real mailbox.

## Honest boundary

Rules-based source verification will not resolve every site. A registry is still
not hundreds of proven deletion integrations. Report researched, verified, sent,
blocked and completed counts separately. This controller closes the manual-trigger
gap; unsupported forms and ongoing route maintenance remain release work.

## Implementation

The controller is `campaign_tick` (every minute). It checks up to 25 approved
workflows locally, prepares eligible requests and queues guarded `automatic_send`
jobs. These checks use bundled public evidence, not new website requests or
personal-data lookups. They have no daily research quota and ignore old research
cooldowns once a fresh exact workflow is approved. Existing personal action-needed
and completed cases still stay out of initial preparation. The legacy
`research_broker` job handler remains safe for already queued jobs.
Sending limits remain local UTC-day budgets, not Gmail quota guarantees.
New tables are additive; existing
cases and outcomes are not migrated or reset.

`/campaign` is the Automatic emails permission screen: mailbox, shared identifiers,
optional postal-address permission and Start/Save. Exact broker-specific previews
live at `/campaign?tab=messages`; they remain read-only and link into the canonical
broker request history. Both postal-sharing choices have server-generated hashes,
so changing that checkbox needs no separate preview-regeneration step. The selected
hash is still verified against current data at save time. The daily limit is a
secondary setting. Research exceptions and the candidate catalog are not user
setup tasks. Initial automatic opt-in and ongoing additions both exclude specialist
credit, insurance and fraud categories.

Home shows Running, Starting, Paused, Stopped or Needs attention, with specific
controls and last successful mailbox check. Missing/stale controller or mailbox
checks cannot be represented as healthy Running. An unavailable live-status API
replaces Running with Status unavailable. Legacy fixed-list consent is not silently
expanded; a one-time Review permissions control offers ongoing broker additions.

Home exposes only Pause and Resume. Pause opens a one-sentence confirmation dialog;
Cancel and Escape do not submit. A server-rendered confirmation provides the same
gate without JavaScript. The old disable endpoint remains for compatibility, but
Stop is no longer a user-facing control. Previously revoked permission is not
silently restored by this UI change.

Pause holds outgoing automatic jobs without changing case states. Legacy Stop additionally
disables consent and records when it was stopped; a stale Resume submission cannot
reenable it. The worker postpones the same pending submit, delivery, follow-up or
recheck job, instead of consuming it or producing duplicate jobs. Polling continues.
Resume wakes held jobs only after checking existing authority, and Start requires
fresh opt-in. Saving permissions while paused leaves the pause in place. A changed
Profile country also invalidates the previously approved sending country until
reviewed. No existing user permission is expanded during deployment.
An uncertain automatic send requires human reconciliation; it is deliberately
not restarted by re-enabling the campaign. The ledger cannot recall in-flight
messages or guarantee exactly-once external delivery.
