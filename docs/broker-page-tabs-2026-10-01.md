# Broker page: one summary, three sections

This change is local to broker request pages. It does not reclassify existing replies,
change campaign authorization, or send requests as part of development checks.

- Persistent header: broker name, database category, visual status and a short explanation.
- Overview: one selected next step, with a form/confirmation button or editable reply.
  Additional pending steps remain accessible in Details; sender review comes first by default.
- Conversation: newest-first sent requests, received mail (including held replies), follow-ups
  and recorded manual steps. Bodies are visible without toggles or nested scrolling.
- Details: disclosed field lists from recorded sends, verification evidence, removal instructions,
  source evidence, review controls and the full event history. Prepared drafts are labelled unsent.

Navigation uses ordinary links styled as tabs: direct URLs, refresh, browser Back, keyboard
activation and operation without JavaScript. Older reply-composer anchors have a small
JavaScript compatibility redirect. Edited replies warn before navigation; they are not copied
into browser storage. Failed sends retain their text.

The conversation projection combines IncomingMessage, approval payloads and events without
changing those records. Provider/RFC IDs deduplicate identified messages; content fingerprints
only deduplicate legacy records without IDs. A send is paired with its preceding prepared
message, never a newer unsent draft. Raw sender authentication remains inspectable separately.

Limitations: this presentation change cannot reconstruct missing email bodies. It says content
is unavailable and directs the user to Gmail, rather than claiming no reply exists. It does not
implement retrieval retries or the separate acknowledgement-classification improvements.

Regression coverage includes held/empty/nested mail, duplicate copies vs distinct identical
replies, multiple sends, unsent drafts, preserved failed edits, and Chromium/WebKit desktop/mobile
navigation with JavaScript disabled. Existing synthetic workflow tests exercise form completion
and reply sending without sending real broker emails.

Verified after the local deployment: 628 tests passed; Ruff clean. Authenticated read-only
checks passed for all three sections on 65 live cases (195 pages), including Redmob's missing
body. All 834 case IDs, 18 completed outcomes and the campaign/consent checksum were unchanged;
SQLite integrity check returned `ok`. Encrypted pre-deployment backup:
`backups/pre-broker-tabs-20261001.erasurebak`.
