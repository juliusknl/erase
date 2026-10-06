# Reply audit — 28 September 2026

Read-only Gmail reconciliation: all 38 incoming messages since campaign start were present locally. All bodies were reviewed, including dismissed messages and replies preserved in the event history. 35 broker messages cover 18 brokers; three messages concern Google account setup. No additional unique reply bodies existed only in the event history. No new requests or replies were sent for this audit.

This document contains public routes and generalized lessons only. Personal identifiers, signed links, ticket identifiers, email bodies and authentication data remain in the encrypted local database.

## Every broker that replied

| Broker | What the replies actually say | Product action |
|---|---|---|
| People Data Labs | Offers a privacy center; later confirms deletion/suppression processing completed, without asserting it previously held a record. | Add center to Quick wins; preserve completion. |
| Apollo Interactive | Use its data-rights form, or legal@apollointeractive.com if unable to use it. | Form explicitly requires US-state residency and can require ID. Not a general quick win for an EEA user. Keep manual fallback; do not confuse with Apollo.io. |
| Kaspr | Privacy Center and email verification required. Later cannot match supplied details; asks for business email, phone or public LinkedIn profile. | Keep form-first; offer a reviewed additional-identifier draft. User's Done is not evidence that every alias was searched. |
| LeadIQ | Removal form; a personal Typeform link; processing notice and later support completion survey. | Public removal form only in shared catalog. A support survey alone is not independent proof of deletion. |
| Hunter | No match for supplied identifiers; specifically excludes consumer mailbox addresses from its professional-email database. | Add claim tool. Offer professional email aliases for a broader search. |
| Lusha | First promises removal; later explicitly confirms completion and suppression. | Preserve final confirmation; no additional form link in its replies. |
| HubSpot | Commercial-dataset preferences, general privacy portal, and separate customer-support portal. | Keep commercial-dataset route in Quick wins. Do not treat help portal as deletion. |
| Seamless.AI | Form first. Email fallback only when unable to complete it; requires name, country/state, city, target email and phone. | Keep form-first. Draft fallback condition and missing fields explicitly; never invent inability to use the form. |
| RocketReach | Offers removal tool; later cannot match and requests RocketReach or LinkedIn profile URL/alternate information. | Add tool; missing-profile-URL placeholders in suggested reply. |
| Apollo.io | Removal form, separate information-access form; later cannot match and asks for alternate professional identifiers. | Add deletion route, not access route, to Quick wins. |
| Acxiom Germany | First requests postal address for geographic scope; later says no matching household/business record and offers internal suppression upon affirmative reply. Also recommends DDV Robinsonliste. | Keep postal disclosure manual. Draft acceptance of offered suppression separately; do not equate Robinsonliste with deletion. Other Acxiom entities use the regional portal below. |
| SalesIntel | Acknowledges request; resolved support ticket says request submitted for processing and data will be removed. | Ticket closure is not an explicit completed deletion. Preserve evidence and watch for a substantive result. No generic deletion dashboard found in reply. |
| Pipl | No profiles match supplied data points. | Preserve no-match result, limited to supplied identifiers. |
| Lead411 | Confirms receipt; says information will be reviewed and removed. | Future-tense promise is not confirmed deletion. Retain underlying evidence even if user marked work Done. |
| Azira | Cannot match by name/email; needs Mobile Advertising ID. Supplies TrustArc form or privacy@azira.com. | Add device-ID form and a draft with an unfilled MAID placeholder. Restore missing action. No generic email retries. |
| OnAudience | Does not ordinarily use names/addresses/phone for its advertising records; cannot match supplied information. | Stop generic name/email retries. Manual clarification of browser/device identifier needed. |
| StackAdapt | Two receipt messages, advertising opt-out completion, then separate deletion completion. | Add Privacy Center. Link the three previously dismissed related messages to its history, without reopening completed work. |
| Snov.io | No details associated with the email address. | Offer saved email aliases for a broader search. Do not reinterpret this as all identifiers searched. |

## Extracted privacy/request/dashboard links

| Public link | Treatment |
|---|---|
| https://privacy.peopledatalabs.com/ | Quick win: choose deletion; status center. |
| https://privacy.peopledatalabs.com/policies | Same center, policy/status landing. |
| https://www.peopledatalabs.com/do-not-sell-or-share | Suppression alternative, not the same request as deletion. |
| https://www.apollointeractive.com/data-rights.php | Manual/applicability check; US-state declaration. |
| https://kaspr.privacy.saymine.io/kaspr | Existing Quick win, finish verification email. |
| https://leadiq.com/request-removal | Existing Quick win. |
| https://privacy-central.typeform.com/to/A1GuN95a | Personal signed link in reply; never publish/reuse its email_token fragment. Public LeadIQ route is preferred. |
| https://leadiq.com/privacy-center | Privacy center/unsubscribe footer, use removal route above. |
| https://hunter.io/claim | Quick win for company-domain email. |
| https://www.hubspot.com/hubspot-privacy-preferences | Existing Quick win for commercial dataset. |
| https://preferences.hubspot.com/privacy | General privacy requests; distinct scope. |
| https://help.hubspot.com/ | Customer support, not a deletion quick win. |
| https://preferences.seamless.ai/ | Existing verified Quick win; email refers to center by name. |
| https://rocketreach.co/remove-profile | Quick win supplied by broker; crawler access blocked during audit. |
| https://www.apollo.io/privacy-policy/remove | Quick win for removal. |
| https://www.apollo.io/privacy-policy/information-claim | Access request, not removal. |
| https://www.apollo.io/company/privacy-center | Privacy information, use removal route for deletion. |
| https://privacyportal.onetrust.com/webform/342ca6ac-4177-4827-b61e-19070296cbd3/6896cf25-6953-4500-9c69-5a8fb6f6f932 | Broker-supplied routing to other Acxiom entities; do not close Acxiom Germany from it. |
| https://www.ichhabediewahl.de/ | Existing DDV Robinsonliste suppression resource. |
| https://submit-irm.trustarc.com/services/validation/0a80503b-1d56-4d50-a898-4377a0227dab | Azira Quick win; MAID needed. |
| https://privacy.stackadapt.com/ | Quick win, separate deletion and advertising opt-out requests. |
| https://support.salesintel.io/hc/requests | A personal support-ticket link was supplied; keep exact ticket in encrypted correspondence only. |

Other extracted links were privacy-policy documents, GDPR FAQs, corporate/social footers, Google account security notices, email tracking redirects, Zendesk vendor branding and a LeadIQ satisfaction survey. They are not deletion dashboards. Tracking redirects are not reusable resources and were not followed. OneTrust branding in Lusha's reply is not its removal form.

## Important limits

- “Done” in the overview aggregates user completion, reported deletion and no-match results. The request's evidence retains the distinction.
- The initial dedicated inbox was not a useful match identifier for several B2B brokers. Later saved aliases do not retroactively change old requests.
- No new addresses, phone numbers, LinkedIn URLs, MAIDs, residency claims or identity documents were invented or sent.
- Added public forms can still have CAPTCHA, identity checks or changed requirements. A link's existence is not a tested end-to-end deletion integration.
