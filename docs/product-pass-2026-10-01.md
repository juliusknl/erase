# Expert workflows, simple experience — implementation checkpoint

## Delivered locally

- Requests for matching details no longer become a no-match completion or a
  receipt. They pause follow-ups and create a specific information task. Identity
  documents retain their dedicated review boundary.
- Existing deterministic draft preparation is connected to this task. Requested
  saved fields and explicitly selected country can be filled; unknown fields and
  conditional email-fallback explanations remain placeholders. No model or new
  sending consent is required to prepare a draft. Sending remains explicit.
- Sending a reply resolves its information task. Validation or mailbox errors
  preserve edited reply text and recipient on the request page, not a JSON page.
- Home attention cards lead to the request's own message/action controls. Shared
  controls also preserve legacy action URLs; there are not two implementations.
- Request messages appear before expandable full history. Unlinked mail and the
  broker reference remain accessible from a secondary section of Requests.
- Requests and Settings labels navigate; their chevrons independently expand
  submenus. Redundant parent-page and mailbox sidebar entries were removed.
- Home retains sent/completed counters and the People Data Labs, LeadIQ, Lusha and
  Apollo.io showcase, now near the top. Outcomes and sourced size claims remain
  distinct; the numbers do not measure a person's exposure.
- Recommended cards show category and an instruction, with scope, fields and
  evidence expandable. The existing three-action session and Later/Skip/Do more
  behavior remain. No repetitive "what this achieves" text on the main card.

## Performance mechanism

A read-only profile in the old container found 797 catalog-guide lookups in one
Home status/recommendation calculation. Preview generation loaded route data
once per broker; unapproved catalog entries also rebuilt routes during status
checks. Preview generation now reuses its already-validated entries and profile;
unapproved plans fail before expensive lookup. GET preview hashing reuses the
displayed rows. Consent POSTs and dispatch continue to recompute/check authority.
No time-based permission or personal-data cache was introduced.

Authenticated local checks immediately before/after deployment:

| Page | Before | After |
| --- | --- | --- |
| Home, first check | 1.671 s | 0.689 s |
| Email plan | 1.999 s | 0.703 s |
| Home, repeated check | 1.602 s | 0.732 s |

These are local observations, not a cross-machine performance guarantee.

## Verification

- Regression-first diagnosis/bug-fix checks reproduced incorrect classification,
  unnecessary route reloads and reply-form data loss before changing them.
- Focused code-simplifier review extracted shared action cards/data, preserving
  the existing trust, disclosure and decision boundaries.
- Final full suite: **622 passed**; Ruff clean. Chromium and WebKit cover label
  navigation, independent chevrons, keyboard toggles and finite task sessions.
- Public-catalog pilot audit passed: 87 email workflows, 112 guided forms,
  195 distinct guides. This validates declared initial routes, not fulfilment.
- All seven authenticated local smoke URLs returned 200 after deployment.
- Fresh-container smoke passed five pages with networking disabled, synthetic
  credentials and no private mounts. An initial in-memory SQLite harness failed
  across TestClient threads; rerunning with an isolated file database, matching
  the app's normal storage, passed. This is not independent onboarding validation.
- Encrypted pre-deployment backup:
  `backups/pre-unified-workflows-20261001.erasurebak`.
- Exact comparison preserved 834 case IDs, 18 completed outcomes and the encrypted
  campaign/consent checksum. SQLite integrity is OK. Historical replies were not
  bulk-reclassified. No broker mail was sent to exercise these changes.
- Local only: no commit publication, remote push or Pheiron repository operation.

## Still required before release

- Independent, nontechnical setup/usability testing, including Google OAuth.
- Real broker outcome and user-time measurement; broader response-fixture coverage
  and broker-specific confirmation connectors rather than generic URL fetching.
- Additional-country automatic email routes. Current email recipes remain EEA-only;
  manual country recommendations do not silently expand email eligibility.
- Continued catalog research. The inventory-wide gate is still incomplete:
  429 unassessed records, 116 unresolved assessments and 65 research-needed guides.
  The 637-guide directory is not a claim of 637 automatic integrations.
- Publication/license, clean-repository secret/security review and installation
  packaging remain separate release work. This checkpoint is not Incogni parity.
