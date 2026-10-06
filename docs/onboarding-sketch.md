# Onboarding: first workflow sketch

Historical design sketch, 2026-10-02. The app now has five steps including
appearance. The table below records the old friction, not the current UI.
See the implementation status and [release review](release-readiness-2026-10-04.md)
for current behavior and remaining work.
Existing users keep their profiles, permissions, messages and progress. No forced
re-onboarding.

Update, 2026-10-03: an Appearance step now precedes the four steps in this original
sketch. The same four themes are available in Settings; see [Appearance](appearance.md).

## Definition of success

A person who knows nothing about data brokers can start appropriate requests,
understand which information leaves their computer, and know whether the app is
actually working. They do not need to choose brokers, classify routes, understand
OAuth, hire an AI agent or repeatedly approve batches.

Simplicity means removing unnecessary decisions, not concealing limitations.
One focused screen, one main action, a visible Back button, saved progress, and
short explanations beside the relevant control. No sidebar or settings tabs during
first-run setup. No completion-time claim until tested with new users.

## Actual current journey and friction

| Stage | What is required today | What the user actually needs to understand |
| --- | --- | --- |
| Install and protect local data | Source checkout, uv, Docker Desktop, FileVault, `.env`, Keychain initialization and dashboard password | This runs on their computer; they need to unlock their local data. No hosted app account exists. |
| Configure Gmail integration | A personal Google Cloud project, enabled Gmail API, OAuth Web client, consent/test-user configuration and exact callback URL; credentials in `.env` | They are allowing this app to send and check removal mail. This developer setup is currently a substantial prerequisite, not a normal sign-in. |
| Launch | Keychain launcher starts the local web app and embedded worker | The app must be running for requests and reply checks to happen. Sleep/offline pauses work; durable jobs resume later. |
| Choose country | Separate country form within Profile | Where they live determines supported requests, not where brokers are headquartered. Automatic email currently supports EU/EEA only. |
| Enter identity | Long Profile form: legal name, manually entered request mailbox, matching emails, numerous optional fields and typed signature | Brokers need identifiers they might already hold. A newly created request mailbox usually will not find old records. |
| Connect mailbox | Google consent; callback returns to Home rather than advancing setup | Which mailbox is connected and what access is granted. Tokens alone are not proof that it matches the entered request address. |
| Enable actual sending | Installation `ERASURE_LIVE_SUBMISSIONS` flag plus campaign authorization, profile signature and matching consent hashes | Nothing should be sent before an explicit Start. A permission saved while installation sending is disabled is not a running plan. |
| Operate | Campaign controller, daily limits, Gmail polling, supported follow-ups and manual tasks | Routine eligible emails run automatically. Forms, unsupported replies and ID/authorization requests can still require them. Results are not guaranteed. |
| Optional AI | TypeSafe key and explicit Jev opt-in in local configuration; restart | Optional external reply interpretation can reduce review work; minimized message text leaves the computer. It is not required to send requests. |

Source of truth: `README.md`, `src/erasure/keychain_cli.py`,
`src/erasure/config.py`, `src/erasure/app.py`, `templates/onboarding.html`,
`templates/campaign.html` and `docs/PRIVACY.md`. This is a code/setup audit, not a
fresh verification of Google's publishing requirements.

## Proposed flow

Install/open → 1. Country → 2. Your details → 3. Request mailbox →
4. Review and start → Home, with actual startup progress.

### Before the wizard: make opening the app boring

Target: one launcher prepares storage, generates encryption keys, starts the
background process and opens the local UI. Ask the user to choose a local app
password; do not ask them to invent keys or edit configuration files.

The current Docker/uv/Keychain setup is developer installation, not this finished
experience. A tested launcher/package is separate implementation work. If a
dependency or OS security setting is missing, explain that one issue and give a
direct fix. Never show a raw traceback. Do not silently lower security.

### 1 of 4 — Let's get started

**Send removal requests. Keep track of what comes back.**

“We handle supported email requests and replies. Some brokers will ask you to
complete a form. You stay in control.”

- Field: **Where do you live?** Country picker, no default inferred from location.
- Inline explanation: “We use this to choose requests available where you live.”
- Main button: **Continue**.

If automatic email is unsupported, say so immediately: “Automatic emails aren't
available for [country] yet. You can still use the removal forms we support.”
Offer **Explore removal forms**. Do not collect a full automatic-email profile or
connect Gmail for a manual-only experience. UK/Switzerland must not silently take
the EU/EEA path. Do not promise worldwide automatic coverage.

### 2 of 4 — Help brokers find your information

- **Full name**.
- **Email addresses you use**, a normal email input with **Add another**.
- Explanation: “Use addresses brokers may already know, such as your personal or
  work email. These are included in requests where needed to find your records.”
- Main button: **Continue**.

No request-mailbox field here. Distinguish identity from delivery. At least one
matching address is recommended; offer **I don't want to add one** with a short
explanation that fewer requests may be usable, rather than forcing invented data.
Do not claim the provided address or name establishes actual exposure.

Do not ask for phone, birth date, aliases, address history, employer, reminders or
a signature here. Keep optional details in Profile; request a particular missing
field later only if it unlocks an actual broker workflow. Work email entered as
a matching identifier must be shared only under the reviewed permissions, never
silently expanded to unrelated uses.

### 3 of 4 — Choose your request mailbox

“This is where removal requests are sent and broker replies arrive. We recommend
a separate Gmail mailbox so this app doesn't need access to your everyday inbox.”

- Main button: **Connect Gmail**.
- Secondary: **Create a separate Gmail account**, opening Google's account flow.
- Small explanation before consent: “You'll approve Gmail access on Google's
  screen. We use it to send requests and check replies.” Clearly disclose actual
  requested access; do not imply Google scopes are technically limited to broker
  messages. Link a concise permissions explanation.
- After return: **Connected: [actual Gmail address]**, with **Change**.
- Continue automatically to review once connection health and identity are verified.

Derive the request address from the connected Google account, not a duplicate
manual text field. This requires adding a mailbox identity check to the backend;
the existing callback stores tokens but does not perform that check.

Cancel/failure stays on this step, preserves everything and offers **Try again**.
OAuth session recovery returns here, not a generic dashboard/login error page.

**Unresolved release prerequisite:** a single Connect Gmail button cannot remove
Google project setup on its own. Current repo users supply their own OAuth client.
For the near-term self-hosted edition, use a guided one-time connection helper:
one external action at a time, exact links/instructions, import a downloaded client
configuration, validate it, then resume. This is still extra work, not frictionless.
For a general-user release, investigate a maintained application OAuth integration
with the appropriate Google review, client type and privacy/security obligations.
Do not ship a shared personal secret or promise verification will be simple/free.
Provider requirements need current official-source review before implementation.

### 4 of 4 — Ready to start

Show a compact, personalized review, not another settings form:

    Your requests
    Name                 Alex Example                  Edit
    Matching addresses   alex@example.com              Edit
    Request mailbox      removal-mailbox@gmail.com     Change
    Country              Germany                       Edit

    We'll send eligible requests, check replies and handle supported follow-ups.
    New reviewed brokers in these categories are included automatically:
    people-search, work-contact and marketing databases.

    You handle forms and identity checks when needed.
    ID documents are never sent automatically.

    Up to 20 automatic emails/day. Remaining requests continue on later days.
    Keep the app running. You can pause sending from Home.

    [ ] I authorize these ongoing requests using the details shown above.
    Signature [                         ]

                       [ Start automatic requests ]

Keep one typed signature here for the existing mandate and a single informed
start authorization. Do not make users sign Profile then authorize the same setup
again on a separate campaign page. Whether a signature should be removed entirely
is a separate decision; this sketch preserves it, once.

**View request details** offers recipients and exact messages without requiring
everyone to read them. Sending limit is stated plainly with changes in Settings,
not an obligatory choice. Postal sharing defaults off; enabling it later requires
clear permission. Do not force users through optional AI configuration here.

If zero eligible email workflows exist, explain why with a specific fix or offer
manual forms. Never present a successful automatic start that can do no work.
Counts, if shown, come from actual eligible plans, not total catalog size.

### Landing — show real work, not a congratulations screen

Start persists identity permission and campaign consent consistently, schedules
work once, then opens Home. Clicking twice/reloading must not duplicate requests.

Home status transitions from **Starting your requests…** to actual controller/
mailbox activity. Display **First request sent** only after a confirmed send.
Show waiting-for-daily-limit, disconnected mailbox and failed startup honestly,
with one relevant recovery action. A saved boolean is not proof the worker works.

Home order: automation and Needs you → sent/completed counts → large-broker
showcase → progress graph → optional Quick wins and recent requests.
Keep forms available while emails run. Do not ask users to start another batch.

## Optional AI: outside the critical path

Offer **Reduce manual reply reviews** after basic setup or when review work first
appears. Explain its benefit without requiring familiarity with Jev. Say that
TypeSafe processes minimized reply text, show an optional API-key connection and
test it without showing the key. Include **Not now**. Provider cost/credit claims
must be current and verified before display; don't promise free forever.

AI off or unavailable must not block the controller. Rules still handle supported
messages, and genuine unresolved tasks remain visible. Enabling AI requires its
own explicit data-sharing choice, not bundled consent to all removal requests.

## Behavior required for a quality release

- Persist draft progress encrypted before final permission; reopening resumes the
  incomplete step. This needs draft storage separate from a signed live profile.
- Back and Edit preserve entered values; edits after approval invalidate only the
  affected permissions and never silently broaden sending.
- Provide Save and exit. Nothing is sent until Start. Existing accounts bypass
  first-run setup and go to Home.
- Validate errors beside fields with focus and plain text; don't discard inputs.
- Test keyboard operation, labels, focus after navigation, mobile layout, readable
  contrast and connection status without relying on color or hover alone.
- Before Start, verify country, exact disclosure scope, Gmail identity/health,
  worker readiness and installation sending capability. No user-facing `.env`
  switch as the last surprise. Keep deployment safety gates; provide a controlled
  setup/launcher path rather than globally enabling live sending by default.
- Prove first request, reply ingestion, restart recovery, expired/revoked Gmail,
  interrupted onboarding, double clicks, paused existing accounts and manual-only
  countries with isolated fixtures. Never send test mail to real brokers.
- Real-user acceptance: a first-time nontechnical tester completes supported
  setup without developer help and can answer: Is it running? Which details get
  shared? What needs me? What happens when I close the laptop?

## Suggested implementation sequence

1. Implement the four-step shell, encrypted drafts and recovery; exercise the same
   screens in the isolated demo. Keep current accounts and Settings unchanged.
2. Add verified mailbox identity and one final permission/start transaction, then
   genuine startup status. Keep existing safety gates enforced server-side.
3. Build guided installation/Gmail setup and test on a clean machine. This is a
   release blocker for nontechnical users, not optional polish.
4. Add optional in-app AI setup and refine copy/layout from first-time-user tests.

## Implementation status

Implemented locally:

- `/setup`: appearance, country, matching details, mailbox and one final permission step;
  isolated encrypted drafts, Save and exit, validation, Back and no sidebar.
- New logins go to setup; existing profiles keep the original Home/Settings journey.
- Manual-only countries can open supported forms without supplying identity or Gmail.
- Real request previews from draft data, zero-route handling, signature validation,
  mailbox identity checks, OAuth cancellation recovery and offline-access checks.
- Explicit outer database transaction around existing campaign enable logic:
  a failed Start rolls everything back; a repeated Start does not sign/enable twice.
- Google project helper with encrypted client-JSON import (existing environment
  credentials remain supported). It uses the documented
  [Gmail profile endpoint](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile)
  to identify the connected mailbox. Google project/API/consent prerequisites follow
  the [official setup guidance](https://developers.google.com/workspace/gmail/api/quickstart/python),
  using a Web client for this app's existing localhost callback, not the quickstart's
  desktop-client flow.
- `erasure-keychain setup --enable-sending` prepares missing local configuration,
  initializes only absent keys, waits for the container to be healthy and opens
  setup. Existing configuration and keys are not overwritten. The flag grants
  installation capability, never substitutes for in-app consent.
- Genuine startup status, periodically refreshed sent/completed counts and a
  first-request notification based on a recorded send, not a saved permission.
- Desktop/mobile Chromium and WebKit journeys, with and without JavaScript;
  isolated fake mailbox and rollback/failure tests. No real broker test emails.

Since this sketch, optional in-app AI-key setup, verified existing-account Gmail
reconnection and a self-contained macOS preview have been implemented. The preview
bundles its runtime; its source allowlist excludes personal state. It still needs
release signing/notarization and clean-machine testing. A maintained/reviewed Google
integration replacing personal-project creation and nontechnical-user acceptance
remain open. Completed steps and Save and exit persist drafts; unsaved keystrokes
are not continuously autosaved. No claim of Google approval or worldwide email support.
