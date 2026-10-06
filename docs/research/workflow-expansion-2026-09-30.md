# Workflow expansion — 30 September 2026

This pass converts published instructions into reviewed initial requests. It does
not establish that the broker holds an individual's data or that deletion succeeds.
No live personal requests or form submissions were made during source review.

## Email workflows added

All 13 use the existing sender, consent checks, campaign controller and daily budget.
The actual request, matching fields, residence limits, follow-up caveats and dated
short evidence excerpts live in `catalog/email-routes.yml`, not a second runtime system.

| Provider | Scope and important limit | Official source |
| --- | --- | --- |
| Vainu | Professional database records; public-register exceptions and source records remain distinct. | [Database statement](https://www.vainu.com/legal-stuff/database-privacy-statement/) |
| Goava | B2B contacts, not its separately treated news content. | [Privacy policy](https://www.goava.com/help-center/privacy-and-information-security-policy) |
| BizMachine | Personal business-contact records; retention and source-register questions may follow. | [Processing policy](https://www.bizmachine.com/en/personal-data-processing) |
| Capaneo / Schober | Name/email-matched marketing records only; no claim of complete device or household coverage. | [Data notice](https://capaneo.de/datenschutz/) |
| beDirect | Business-contact marketing suppression; blocking records and independent sources remain. | [beAddress notice](https://beaddress.de/info/Datenschutz) |
| AZ Direct Austria | Austrian name/address suppression and identifiable-supplier forwarding; separate from Germany. | [Address notice](https://at.az-direct.com/links/datenschutz-adressverlag), [rights handling](https://at.az-direct.com/links/betroffenenrechte) |
| MEDIAPOSTE | French postal suppression; processor-side deletion requests may instead be forwarded to source controllers. | [Information charter](https://www.mediaposte.fr/charte-dinformation/) |
| Sovendus Germany | Email advertising objection; browser-analysis switch and retailer records are separate. | [German notice](https://web.sovendus.com/de/privacy) |
| Cision | Media and influencer databases, explicitly excluding Brandwatch and source publications. | [Influencer notice](https://privacy.cision.com/dataprivacynotice_influencers) |
| AdeptID | People Search candidate data and profiling; verification and retention limits apply. | [Current linked PDF](https://www.adept-id.com/wp-content/uploads/2025/06/AdeptID-Privacy-Policy_Updated-June-13-2025.pdf) |
| Preqin | Professional subscription-database records routed to group privacy; not financial-account deletion. | [Policy](https://www.preqin.com/policies/privacy-policy) |
| Vector | Unrestricted public initial removal route; this is not evidence of European exposure. | [Removal page](https://www.vector.co/opt-out) |
| LeadIQ | Directory Database removal; email alternative and required subject verified against July 2026 policy. | [Policy](https://leadiq.com/legal/privacy-policy) |

Professional/name-email routes need an identifier used outside the request mailbox.
This is a matching precaution, not evidence that every supplied email is relevant.
Where the notice does not define a complete checklist, a subsequent request for
identifiers remains a user action. We do not invent mandatory fields or send ID.
The Austrian and French postal workflows require address permission and their
respective residence selection. Other countries are not silently treated as matches.

## Corrections and guided routes

- [Growbots](https://www.growbots.com/privacy/) distinguishes its opt-out form from
  email requests for other rights. Its [official form page](https://www.growbots.com/do-not-sell-my-info/)
  embeds a Google form requiring a professional email followed by confirmation.
  The guide now prefers the form and Quick Wins includes it. It is not an automatic email workflow.
- [Numberly](https://numberly.com/en/privacy/) requires identity proof with a rights
  request. That requirement was previously prose-only; it is now a structured
  required field too, preventing accidental promotion to the minimal sender.
- [HubSpot](https://www.hubspot.com/hubspot-privacy-preferences) exposes a distinct
  commercial-dataset deletion checkbox and advertising opt-out. The Quick Win now
  names the correct checkbox and joins the finite reviewed-form cohort.
- People Data Labs had a Quick Win but no structured guide. The added guide records
  the visible [sale-suppression form](https://www.peopledatalabs.com/do-not-sell-or-share)
  and separates it from its JavaScript-only Privacy Center. It remains `needs_research`.

No interactive browser was available in this session. PDL's full deletion flow,
Kaspr's embedded portal and Seamless's DataGrail fields were not inspected and are
not newly counted as field-validated forms. LeadIQ's privacy-subdomain form failed
retrieval; its independently verified email alternative is usable for initial requests.
Enin was inspected but not promoted: its mixture of news, business-risk and other
processing needs a more specific matching/scope review.

## Verification and remaining scope

The cohort now contains 21 email workflows and seven guided forms. Automated tests
exercise **every email workflow** through the real controller into a fake Gmail
sender, including exact recipient/text, address limits, residence limits and repeat
dispatch protection. These are software tests, not live deletions.

The broader inventory remains unfinished. `erasure-catalog audit` now includes
`execution.email_workflow_backlog`: the remaining primary-email guides and their
recorded requirements. No outstanding assessment was relabelled complete to improve
the headline count. Location/device and identity-graph workflows remain important;
name/email requests cannot honestly stand in for advertising-ID matching.
