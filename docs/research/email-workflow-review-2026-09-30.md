# Complete primary-email backlog assessment — 30 September 2026

## Scope and result

This pass assessed all **125 primary-email guides without an executable recipe at
the start of the pass**. It added **23 initial workflows**, taking the published
cohort from 21 to **44 email workflows**, alongside seven existing guided forms.
**102 primary-email guides remain outside automatic dispatch.**

This is a routing assessment, not 125 newly completed end-to-end validations.
The table distinguishes a current public-page check from review of the already
dated dossier and from incomplete retrieval. A source check does not test delivery,
identity verification or deletion. No private forms were submitted or personal
messages sent by this research pass; an independently running, previously
authorized campaign is separate.

The count is not market coverage or personal exposure. The 471 structured guides
and the larger discovery inventory remain broader than the executable cohort.
No unsupported route or existing case was relabelled completed to increase coverage.

## What changed

- Exact, scoped email requests use the existing deterministic campaign controller.
  No paid model, extra dashboard tab or separate automation framework was introduced.
- Form-only fields were separated from email requirements at Adapt and Nomination.
  SMARTe's extension-account subject is not used for its master database.
- Anteriad's device identifier is required for device records, not contact records.
  Its email workflow explicitly excludes any claim of device-only removal.
- Stirista requires a current postal address; historical addresses are optional.
  Postal disclosure still requires explicit campaign permission.
- QUADRESS publishes a direct suppression route to info@quadress.de. Its access
  token is not a prerequisite for suppression.
- Remaining guides now explain concrete next steps instead of generic review
  placeholders. The catalog audit exports those steps, requirement certainty,
  dated official sources and verification caveats for every remaining email guide.

## Added initial workflows

Exact message text, residence limits, disclosure fields and evidence live in
[catalog/email-routes.yml](../../catalog/email-routes.yml). These are first-contact
workflows, not a promise that subsequent verification will be automatic.

| Broker / guide ID | Intended effect | Residence scope | Official evidence |
| --- | --- | --- | --- |
| Adapt.io business directory (`adapt-directory`) | Scoped deletion request | EEA | [Workflow source](https://www.adapt.io/privacy.htm) |
| Anteriad (`anteriad`) | Scoped deletion request | EEA | [Workflow source](https://anteriad.com/privacy-policy) |
| AudiencePoint (`audiencepoint`) | Scoped deletion request | EEA | [Workflow source](https://audiencepoint.com/privacy-policy/) |
| Critère Direct (`critere-direct-fr`) | Marketing suppression | FR | [Workflow source](https://www.criteredirect.com/rgpd-et-cookies/) |
| Deutsche Post Direkt (`deutsche-post-direkt`) | Marketing suppression | DE | [Workflow source](https://www.deutschepost.de/dam/jcr:d2c20ba5-1b40-45c3-ab68-5ab2373b4119/dp-ddp-informationen-zur-dv-fuer-av-und-adressabgleich.pdf) |
| GEMINI DIRECT (`gemini-direct-de`) | Scoped deletion request | DE | [Workflow source](https://www.geminidirect.de/datensicherheit/) |
| Global Source Data Solutions (`registry-global-source-data-solutions-inc`) | Scoped deletion request | EEA | [Workflow source](https://www.gsdsi.com/privacy-policy) |
| GRIN (`registry-grin-technologies-inc`) | Scoped deletion request | EEA | [Workflow source](https://grin.co/privacy/) |
| GrowthCode (`registry-growthcode-llc`) | Scoped deletion request | EEA | [Workflow source](https://www.growthcode.io/privacy) |
| HealthLink Dimensions (`registry-healthlink-dimensions-llc`) | Scoped deletion request | EEA | [Workflow source](https://healthlinkdimensions.com/privacy-policy) |
| Hunt Club / Atlas (`registry-hunt-club-inc`) | Scoped deletion request | EEA | [Workflow source](https://www.huntclub.com/privacy) |
| Nomination (`nomination-fr`) | Scoped deletion request | EEA | [Workflow source](https://www.nomination.fr/protection-des-donnees-personnelles/) |
| Planet49 (`planet49-consumer`) | Marketing suppression | EEA | [Workflow source](https://www.planet49.com/sc/todo=cp_planet49) |
| QUADRESS (`quadress`) | Marketing suppression | DE | [Workflow source](https://quadress.de/daten-sperren.html) |
| RevOptimal (`revoptimal`) | Scoped deletion request | EEA | [Workflow source](https://revoptimal.com/eea-uk-privacy/) |
| SemantIQ (`semantiq`) | Scoped deletion request | EEA | [Workflow source](https://www.semantiqhealth.com/privacy-policy) |
| SLS Data (`sls-data-fr`) | Scoped deletion request | EEA | [Workflow source](https://www.sls-data.com/politique) |
| SMARTe (`smarte`) | Scoped deletion request | EEA | [Workflow source](https://www.smarte.pro/privacy-policy) |
| Sports Innovation Lab (`sports-innovation-lab`) | Scoped deletion request | EEA | [Workflow source](https://www.sportsilab.com/privacy-policy) |
| Stirista / Andrews Wharton routing (`stirista`) | Marketing suppression | EEA | [Workflow source](https://www.stirista.com/privacy-policy/) |
| toleadoo (`toleadoo-consumer`) | Marketing suppression | EEA | [Workflow source](https://www.toleadoo.com/sc/todo=cp_toleadoo) |
| Whooz / Whize / TDA Analytics (`whooz-whize`) | Marketing suppression | NL | [Workflow source](https://www.whize.nl/privacy-en-voorwaarden) |
| ZS Opinion Leader Intelligence (`zs-opinion-leader`) | Scoped deletion request | EEA | [Workflow source](https://www.zs.com/compliance/opinion-leader-privacy-notice) |

EEA in a workflow means the published request is available to that resident, not
that every European is in the database. Professional, creator and healthcare
datasets are relevant to particular groups. No name/email route should be read as
coverage of all a provider's location, device or customer-controlled records.

## Every remaining primary-email guide

“Dossier reviewed” means its existing dated instructions were reviewed in this
pass; it does **not** claim a new website verification. “Public page checked” means
relevant published instructions were read again, not that a form or mailbox was
tested. Source dates below belong to the maintained guide and are not reset merely
because this report was written. A failed fetch does not prove a broker is defunct.

| Broker / guide ID | Review basis this pass | Concrete next step or limitation | Maintained official sources |
| --- | --- | --- | --- |
| ABIS (`abis-de`) | Public page checked | This is an access-first address-reference workflow: name and current postal address are required, prior addresses are optional, and a postal reply is the default. Review the returned records before erasure. | [1](https://www.abis-online.de/betroffenenanfrage/) (2026-09-29); [2](https://www.abis-online.de/impressum/) (2026-09-29); [3](https://www.abis-online.de/ueber-uns/datenschutz/) (2026-09-29) |
| Adttribution (`adttribution`) | Dossier reviewed | Device identifier must be supplied deliberately and coverage checked per identifier. | [1](https://adttribution.com/privacy-policy/) (2026-09-29) |
| Agile Education Marketing (`agile-education`) | Dossier reviewed | Known-record versus lookup routing and school-specific identifiers need review. | [1](https://agile-ed.com/privacy-policy/) (2026-09-29); [2](https://agile-ed.com/california-privacy-rights/) (2026-09-29); [3](https://personalinforequest.agile-ed.com/) (2026-09-29) |
| Attribits / All Good Media (`attribits`) | Public page checked | Email matching is documented, but the reviewed rights notice is jurisdiction-dependent; EEA database-erasure applicability remains unresolved. | [1](https://www.attribits.com/privacy-policy) (2026-09-29); [2](https://www.attribits.com/do-not-sell) (2026-09-29) |
| Audigent (`audigent`) | Dossier reviewed | Device/browser matching prevents minimal email automation. | [1](https://audigent.com/platform-privacy-policy/) (2026-09-28) |
| AZ Direct Switzerland (`az-direct-ch`) | Dossier reviewed | The Swiss route requires identity proof and separate Swiss applicability; the EEA email sender does not implement this. | [1](https://www.az-direct.ch/datenschutz/) (2026-09-28) |
| Azerion advertising routes (`azerion-advertising-routes`) | Dossier reviewed | Product/controller selection and pseudonymous matching must precede automation. | [1](https://www.azerion.com/azerion-fms-platform-privacy-notice/) (2026-09-29); [2](https://www.hybridtheory.com/privacy-notice/) (2026-09-29); [3](https://www.azerion.com/azerion-native-privacy-notice/) (2026-09-29); [4](https://www.azerion.com/azerion-expands-into-north-america-merging-three-adtech-acquisitions/) (2026-09-29); [5](https://www.azerion.com/azerion-global-corporate-privacy-notice/) (2026-09-29) |
| BDEX (`bdex`) | Public page checked | Email matching is documented, but the current linked rights notice enumerates US-state routes; EEA applicability still needs confirmation. | [1](https://www.bdex.com/privacy-policy-old/) (2026-09-29); [2](https://policies.termageddon.com/api/policy/VlcxYVpsSmxXa2RLTkUxQ1JXYzlQUT09) (2026-09-29) |
| Black Tiger Belgium (`black-tiger-belgium`) | Dossier reviewed | Unresolved controller, product scope or request requirements; resolve the recorded blockers first. | [1](https://www.blacktiger.tech/privacy-notice) (2026-09-29); [2](https://www.gegevensbeschermingsautoriteit.be/burger/gba-sanctioneert-gegevensbeheerder-black-tiger-belgium-wegens-gebrek-aan-transparantie) (2026-09-28) |
| Blis (`blis`) | Dossier reviewed | No name/email matching; device identifiers and verification require review. | [1](https://blis.com/blis-privacy-policy-for-online-advertising-and-related-uses/) (2026-09-29) |
| Brandwatch online author database (`brandwatch-authors`) | Public page checked | Author-handle matching and verification are not fully specified. | [1](https://www.brandwatch.com/legal/author-privacy-policy/) (2026-09-29) |
| Cerved Group (`cerved-italy`) | Dossier reviewed | Commercial-risk scope and case-specific grounds require review; no minimal automatic matching checklist is established. | [1](https://www.cerved.com/privacy) (2026-09-29); [2](https://backoffice.cerved.com/uploads/Informativa_BI_Cerved_Group_S_p_A_v6_1_06fffbea97.pdf) (2026-09-29) |
| Cloud Technologies — Polish advertising controller (`cloud-technologies-pl`) | Dossier reviewed | Technical matching, purpose and jurisdiction require review. | [1](https://www.cloudtechnologies.pl/en/internet-advertising-privacy-policy) (2026-09-29); [2](https://www.cloudtechnologies.pl/en/opt-out) (2026-09-29); [3](https://www.cloudtechnologies.pl/en/do-not-sell-my-personal-info) (2026-09-29) |
| CRIBIS (`cribis-it`) | Dossier reviewed | Identify the commercial-information record through access before deciding correction or erasure grounds; do not automatically delete credit records. | [1](https://www.cribis.com/it/informativa-privacy/) (2026-09-28) |
| CRIF Austria (`crif-at`) | Dossier reviewed | Start with the Austrian credit-data access process and personally review identity proof; correction or erasure depends on the returned records. | [1](https://www.crif.at/fuer-privatpersonen/faqs-zur-selbsauskunft/fragen-fuer-konsumentinnen/) (2026-09-28); [2](https://www.crif.at/konsumenten/datenschutzerklaerung-auskunftei-und-adressverlag) (2026-09-28) |
| CRIF Switzerland (`crif-ch`) | Dossier reviewed | Swiss credit-data access requires birth date, current address and identity proof, with a postal response; this is not a generic erasure email. | [1](https://www.crif.ch/privatpersonen/selbstauskunft/selbstauskunft-beantragen/) (2026-09-28) |
| Dataventure / Cardata (`dataventure-fr`) | Dossier reviewed | Unresolved controller, product scope or request requirements; resolve the recorded blockers first. | [1](https://www.dataventure.com/wp-content/uploads/2023/07/cardata_charte_protection-des-donnees.pdf) (2026-09-28) |
| Ellisphere (`ellisphere-fr`) | Public page checked | Business-credit records need a scoped request and a retention decision; commercial scoring is not unconditional marketing-list deletion. | [1](https://www.ellisphere.com/uploads/documents/rgpd/Politique_RGPD_Ellisphere.pdf) (2026-09-29) |
| Email Industries / BlackBox (`registry-indiemark-llc`) | Dossier reviewed | Risk-data scope and required postal/mobile identifiers need explicit user review; EEA applicability is not established. | [1](https://blackbox.email/privacy-policy) (2026-09-29) |
| Endgame (`endgame`) | Dossier reviewed | Controller/customer scope and matching information need resolution. | [1](https://www.endgame.io/privacy) (2026-09-29) |
| Enigma (`enigma`) | Dossier reviewed | Associated-email authentication and risk-product exceptions require review. | [1](https://www.enigma.com/legal/privacy-policy) (2026-09-29); [2](https://www.enigma.com/legal/do-not-sell) (2026-09-29) |
| Enin (`enin-no`) | Dossier reviewed | Record identification and case-specific grounds need review. | [1](https://www.enin.ai/privacy) (2026-09-29) |
| Experian Italy (`experian-italy`) | Dossier reviewed | Signed identity evidence and credit-specific grounds require personal review; do not automatically email documents. | [1](https://www.experian.it/consumatori/come-contattare-il-servizio-consumatori-di-experian) (2026-09-29); [2](https://www.experian.it/content/dam/noindex/emea/italy/Nuovo-modulo-SIC.pdf) (2026-09-29) |
| FCR Media Belgium (`fcr-media-be`) | Dossier reviewed | The notice requests name, postal address, phone and email; the current sender does not authorize phone disclosure. | [1](https://fcrmedia.be/privacyverklaring-fcr-media/) (2026-09-28) |
| Freedelity (`freedelity-be`) | Dossier reviewed | Identify the retailer, then use the authenticated portal or personally reviewed identity proof. Retailer forwarding is not confirmed retailer deletion. | [1](https://www.myfreedelity.com/fr/vie-privee) (2026-09-28) |
| Giant Partners / ListGiant (`registry-giant-partners-inc`) | Public page checked | Confirm applicable regional rights and contact matching before sending; the reviewed notice does not establish an EEA database-erasure workflow. | [1](https://giantpartners.com/privacy-policy/) (2026-09-28) |
| GrayHair Software (`registry-grayhair-software-llc`) | Retrieval incomplete; dossier reviewed | Name and email are documented, but this pass could not retrieve the official policy to resolve product scope and European applicability. | [1](https://grayhairsoftware.com/privacy-policy/) (2026-09-28) |
| Graze (`registry-graze-social-pbc`) | Public page checked | Identify the affected Bluesky profile or content first. Email alone does not locate public posts; curator-controlled copies require a separate request. | [1](https://www.graze.social/privacy-policy) (2026-09-28) |
| GroundTruth (`groundtruth`) | Dossier reviewed | Device identifiers, certification and regional proof require review. | [1](https://www.groundtruth.com/privacy-policy/) (2026-09-29); [2](https://www.groundtruth.com/privacy-rights/) (2026-09-29) |
| Health Union (`registry-health-union-llc`) | Retrieval incomplete; dossier reviewed | Separate healthcare-professional profiling from a community account and identify the relevant service; this pass could not retrieve the full notice. | [1](https://health-union.com/privacy-notice/) (2026-09-29); [2](https://health-union.com/consumer-health-notice/) (2026-09-29) |
| HealthWise Data (`registry-healthwise-data`) | Public page checked | Commercial-database removal uses name/current-address suppression, not the separate direct-customer deletion route. Confirm regional applicability before postal disclosure. | [1](https://healthwisedata.com/privacy-policy/) (2026-09-29) |
| Helix Campaigns (`registry-helix-campaigns-llc`) | Public page checked | Identify relevant donor-database exposure and regional eligibility; client-controlled donor records need the client, not a blanket email to Helix. | [1](https://www.helixcampaigns.com/privacy) (2026-09-29) |
| HEROLD (`herold-at`) | Dossier reviewed | The published route requires identity proof. Review the specific directory record and send proof personally through a suitable channel. | [1](https://www.herold.at/datenschutzerklaerung/) (2026-09-28); [2](https://datasolutions.herold.at/faq/) (2026-09-28) |
| HOSPIMEDIA Nominations (`hospimedia-nominations-fr`) | Dossier reviewed | Review professional matching information and the documented additional DPO recipient; generic single-recipient dispatch does not implement that instruction. | [1](https://nominations.hospimedia.fr/mentions-legales/) (2026-09-29); [2](https://nominations.hospimedia.fr/politique-de-confidentialite/) (2026-09-29); [3](https://nominations.hospimedia.fr/faq-decideurs/) (2026-09-29) |
| Iberinform Spain (`iberinform-spain`) | Retrieval incomplete; dossier reviewed | Professional-record scope and unspecified email matching requirements need review before submission. | [1](https://www.iberinform.es/gdpr-data-request-form) (2026-09-29); [2](https://www.iberinform.es/gdpr) (2026-09-29) |
| Informa D&B Portugal (`informa-portugal`) | Dossier reviewed | The database notice asks for identity-number or equivalent proof; review the separate sole-trader notice and record scope before disclosure. | [1](https://www.informadb.pt/pt/quem-somos/governance/privacidade/informacao-aos-titulares-de-dados-pessoais-que-constam-na-base-de-dados-informa-db/) (2026-09-29); [2](https://www.informadb.pt/pt/quem-somos/governance/privacidade/informacao-aos-empresarios-em-nome-individual/) (2026-09-29) |
| Informa D&B Spain / eInforma (`informa-spain`) | Dossier reviewed | Choose the person type first: other individuals and sole traders have different recipients. Include the relevant business record and the required subject. | [1](https://www.informa.es/textos-legales) (2026-09-29) |
| Innovative Database Solutions (`registry-innovative-database-solutions-inc`) | Public page checked | Suppression and provider coordination differ from direct database erasure; matching fields and source scope need review. | [1](https://idatabasesolutions.com/privacy/) (2026-09-29); [2](https://idatabasesolutions.com/personal-information-request-all-other-states/) (2026-09-29) |
| ipapi / Kloudend (`registry-kloudend-inc`) | Dossier reviewed | IP/device versus account identity and exact scope need review. | [1](https://ipapi.co/privacy/) (2026-09-29) |
| iSpot (`registry-ispot-tv-inc`) | Dossier reviewed | Device matching and two-step deletion confirmation remain untested. | [1](https://www.ispot.tv/hub/agreements/privacy/) (2026-09-29); [2](https://www.ispot.tv/privacy/opt-out) (2026-09-29) |
| ISS Inc. (`registry-institutional-shareholder-services-inc`) | Public page checked | Controller/product and professional identifiers require selection. | [1](https://www.iss-stoxx.com/legal/iss-inc-privacy-notice/) (2026-09-29); [2](https://www.iss-stoxx.com/legal/ccpa/) (2026-09-29) |
| JDM List Services (`registry-jdm-list-services-llc`) | Public page checked | JDM says it does not maintain a consumer database. Identify the campaign and originating list provider rather than assuming JDM can erase the source. | [1](https://jdmlistservices.com/privacy-policy) (2026-09-29) |
| Kalibrate / Intalytics (`registry-kalibrate-intalytics`) | Public page checked | Product controller selection and matching information remain request-specific; not a minimal-name/email automation route. | [1](https://kalibrate.com/privacy-policy/) (2026-09-29) |
| Kargo (`registry-kargo-global-llc`) | Dossier reviewed | Browser/device identification and possible screenshots require user participation. | [1](https://www.kargo.com/privacy) (2026-09-29); [2](https://www.kargo.com/privacy-portal) (2026-09-29) |
| Keyword Connects (`registry-keyword-connects-llc`) | Public page checked | Identify the lead or affiliate and the applicable rights route; the marketing-unsubscribe inbox is not evidence of database deletion. | [1](https://keywordconnects.com/privacy-policy/) (2026-09-29) |
| Koddi (`registry-koddi-inc`) | Dossier reviewed | Identify the retailer/product controller and provide its matching data; the policy may require at least two matching data points. | [1](https://koddi.com/privacy-policy/) (2026-09-29) |
| Kompass (`kompass`) | Dossier reviewed | Policy requests postal address and phone; these are outside minimal-email campaign consent. | [1](https://se.kompass.com/l/general-data-use-policy) (2026-09-28) |
| Kontext Data (`registry-kontext-data`) | Dossier reviewed | The notice requires individually structured name/address fields and country; the app's free-text postal address does not validate this checklist. | [1](https://kontextdata.com/privacy) (2026-09-29) |
| L2 / Labels & Lists (`registry-labels-lists-inc`) | Dossier reviewed | US voter/consumer-list relevance needs confirmation before disclosing a postal identity; address-based opt-out does not establish EEA exposure. | [1](https://www.l2-data.com/wp-content/uploads/2024/07/L2-Privacy-Notice.pdf) (2026-09-29); [2](https://www.l2-data.com/wp-content/uploads/2025/11/L2-State-Specific-Privacy-Addendum-Multi-State-08-01-2025129830437.2.pdf) (2026-09-29) |
| Live Data Technologies (`registry-live-data-technologies-inc`) | Public page checked | Reconcile differing official instructions: the legals page asks for employer, while the opt-out page asks for work email and postal address. Do not omit these by guessing. | [1](https://www.livedatatechnologies.com/legals) (2026-09-29); [2](https://www.livedatatechnologies.com/opt-out) (2026-09-29) |
| LiveRamp UK (`liveramp-uk`) | Dossier reviewed | Confirm regional applicability and identifiers; the current email template assumes EEA residence, not UK residence. | [1](https://liveramp.com/uk/privacy) (2026-09-28) |
| LoopMe (`registry-loopme-limited`) | Dossier reviewed | Device identifiers and controller selection cannot be inferred from ordinary email identity. | [1](https://legal.loopme.com/privacy-center/loopme-privacy-notice) (2026-09-29); [2](https://legal.loopme.com/privacy-center/loopme-opt-out) (2026-09-29) |
| MedPro Systems (`registry-medpro-systems`) | Dossier reviewed | Confirm relevant estate-planning or partner-sharing exposure and regional applicability; do not erase estate documents or an account to obtain advertising suppression. | [1](https://www.medprosystems.com/data-privacy-and-security-rationale-statement/) (2026-09-28) |
| Numberly (`numberly`) | Dossier reviewed | Identity-proof requirements, browser context and controller/processor distinctions require personal review. | [1](https://numberly.com/en/privacy/) (2026-09-29); [2](https://numberly.com/en/legal-notices/) (2026-09-29) |
| Online Advertising Network (`oan`) | Dossier reviewed | Obtain the relevant cookie/device identifier for email erasure; the separate browser opt-out is suppression and must keep its cookie. | [1](https://oan.pl/internet-advertising-privacy-policy/) (2026-09-28) |
| Opensend (`opensend`) | Public page checked | EEA website-visitor tracking is customer-processor data. Identify the client controller; own website/account erasure is not removal of that customer's data. | [1](https://www.opensend.com:443/privacy-policy) (2026-09-28) |
| Österreichische Post marketing data (`post-at-marketing`) | Dossier reviewed | The Austrian marketing request needs birth date as well as name and postal address; the current sender does not collect or authorize birth-date disclosure. | [1](https://www.post.at/i/c/datenschutz) (2026-09-28) |
| Outbrain — legacy technology under Teads (`outbrain`) | Dossier reviewed | Technical identifiers, device-specific preferences and regional-controller selection required. | [1](https://www.outbrain.com/privacy/) (2026-09-29) |
| Outlogic (`outlogic`) | Dossier reviewed | The location-data request requires the user's device ID; name and email cannot stand in for it. | [1](https://outlogic.io/privacy-policy/) (2026-09-28); [2](https://outlogic.io/opt-out-form/) (2026-09-28) |
| Outward Media (`outward-media`) | Public page checked | Confirm applicable regional rights and matching scope; the reviewed notice's California-and-other-residents wording does not establish a tested EEA workflow. | [1](https://outwardmedia.com/privacypolicy) (2026-09-28) |
| Place Exchange (`place-exchange`) | Dossier reviewed | The request requires a mobile advertising identifier and ownership review; do not substitute a contact email. | [1](https://www.placeexchange.com/privacy) (2026-09-28) |
| Plunge Digital (`plunge-digital`) | Public page checked | The reviewed notice offers US-state rights and a portal; EEA eligibility and matching requirements are not established. | [1](https://www.plungedigital.com/privacy-policy/) (2026-09-28) |
| PMG (`pmg`) | Dossier reviewed | Identify the service/client controller and at least two matching data points where requested; a generic email does not resolve that scope. | [1](https://www.pmg.com/privacy-policy) (2026-09-28) |
| Podscribe (`podscribe`) | Dossier reviewed | Matching requires technical identifiers beyond a name and email. | [1](https://podscribe.com/privacy) (2026-09-28); [2](https://podscribe.com/terms) (2026-09-29) |
| Postie (`postie`) | Public page checked | Postal matching and possible email/telephone verification are documented, but the reviewed sources do not establish a European consumer-database route. | [1](https://postie.com/privacy-policy/) (2026-09-28); [2](https://postie.com/your-privacy-choices/) (2026-09-28) |
| ProdPro (`prodpro`) | Public page checked | Email route supports suppression, not confirmed blanket deletion of researched professional records. | [1](https://prodpro.com/privacy-policy/) (2026-09-28); [2](https://prodpro.com/privacy-policy/) (2026-09-28) |
| Proff Norway / Proff Forvalt (`proff-no`) | Dossier reviewed | Public-register and credit-processing exceptions require individual review. | [1](https://www.proff.no/info/privacy-notice-business/) (2026-09-29); [2](https://www.proff.no/info/hjelp-og-kontakt/) (2026-09-29) |
| Proxima (`registry-innovation-brands-corp`) | Dossier reviewed | Requires requests from affected email addresses and ownership verification; sending from the dedicated mailbox alone may not satisfy the workflow. | [1](https://www.proxima.ai/privacy) (2026-09-29) |
| PulsePoint (`pulsepoint`) | Dossier reviewed | Device identifiers or professional NPI matching prevent minimal email automation. | [1](https://www.pulsepoint.com/legal/platform-privacy-policy) (2026-09-28) |
| Quadrant (`quadrant`) | Dossier reviewed | Location-dataset matching and verification requirements are not minimal-email instructions. | [1](https://www.quadrant.io/privacy-policy) (2026-09-28) |
| Quorum Data (`quorum`) | Public page checked | The consumer household/measurement database is explicitly US-only. EU business-contact and client-processor data are different scopes; select the matching identifier accordingly. | [1](https://app.quorum.live/privacy) (2026-09-29) |
| RealSource Data (`realsource`) | Dossier reviewed | Mandatory matching and verification requirements are not sufficiently specified for automatic personal-data transmission. | [1](https://www.realsourcedata.com/about-us) (2026-09-29); [2](https://www.realsourcedata.com/privacy-policy) (2026-09-29) |
| Reklaim — data brokerage (`reklaim`) | Public page checked | The brokerage notice expressly covers US-resident records; distinguish that scope from the rewards account before choosing a request. | [1](https://reklaimyou.com/data-broker-privacy-notice) (2026-09-29); [2](https://reklaimyou.com/do-not-sell) (2026-09-29); [3](https://reklaimyou.com/privacy) (2026-09-29) |
| Reveal Mobile (`reveal-mobile`) | Dossier reviewed | Device identifier collection and verification require user participation. | [1](https://revealmobile.com/privacy) (2026-09-29); [2](https://revealmobile.com/privacy-form) (2026-09-29) |
| RevenueBase (`revenuebase`) | Public page checked | Employer and work-email matching exceed minimal personal-email automation. | [1](https://revenuebase.ai/privacy-policy) (2026-09-29) |
| Risika (`risika-dk`) | Dossier reviewed | Identify the business-linked risk record through access first, then review correction or erasure grounds. | [1](https://risika.com/privacy/) (2026-09-28) |
| ROQAD — European identity graph (`roqad`) | Dossier reviewed | Technical identifier matching and region/controller selection cannot be replaced by a generic name-and-email request. | [1](https://roq.ad/privacy-policy-roqad) (2026-09-29); [2](https://roq.ad/opt-out) (2026-09-29) |
| Sabio / App Science (`sabio`) | Dossier reviewed | Device matching and signed declaration require user input; privacy email alone does not establish minimal automation. | [1](https://www.sabioctv.com/privacypolicy) (2026-09-29); [2](https://www.sabioctv.com/do-not-sell-my-info) (2026-09-29) |
| SalesIntel (`salesintel`) | Public page checked | Work email and employer are required matching information beyond minimal personal-email automation. | [1](https://salesintel.io/data-gathering-privacy/) (2026-09-29) |
| Selectivv (`selectivv-pl`) | Dossier reviewed | Mobile matching and actual profile scope need review; ordinary name/email matching is not established. | [1](https://selectivv.com/polityka-prywatnosci/) (2026-09-29); [2](https://selectivv.com/en/privacy-policy/) (2026-09-29); [3](https://selectivv.com/oferta/marketing-cyfrowy/reklama-w-aplikacjach-mobilnych/) (2026-09-29) |
| Semcasting / PrivacyChoice (`semcasting`) | Public page checked | Residential-address disclosure and follow-up matching require review, not a minimal-email route. | [1](https://www.semcasting.com/privacy_policy_v1) (2026-09-29); [2](https://www.semcasting.com/privacy_choice) (2026-09-29) |
| SheerID Audience Services (`sheerid`) | Public page checked | Controller/product selection and variable verification needed; linked privacy form did not render. | [1](https://www.sheerid.com/global-privacy-policy/) (2026-09-29); [2](https://www.sheerid.com/privacy-notice-for-audience-development-products-services/) (2026-09-29) |
| Similarweb (`similarweb`) | Dossier reviewed | Partner-sourced contacts and product-specific verification must be resolved; generic account erasure is not proof of database removal. | [1](https://www.similarweb.com/corp/legal/privacy-policy/) (2026-09-29); [2](https://support.similarweb.com/hc/en-us/articles/16304260922013-Contact-Data-FAQs) (2026-09-29) |
| Skydeo (`skydeo`) | Public page checked | Broken portal, unspecified matching, and controller/processor scope need review. | [1](https://skydeo.com/privacy-policy/) (2026-09-29) |
| Start.io (`start-io`) | Dossier reviewed | Requires an advertising ID and verification; name/email-only delivery is insufficient. | [1](https://www.start.io/policy/privacy-policy/) (2026-09-29); [2](https://www.start.io/do-not-sell-or-sharemy-personal-information/) (2026-09-29) |
| Sterling Data Company (`sterling-data`) | Public page checked | Variable identity/residency requirements and uninspected embedded form. | [1](https://sterling.ai/privacy-policy/) (2026-09-29); [2](https://sterling.ai/privacy-policy/trust-center-page/) (2026-09-29) |
| Tie (formerly Revenue Roll) (`tie-revenue-roll`) | Public page checked | No fixed initial matching checklist or verified non-US applicability. | [1](https://meettie.com/privacy-policy) (2026-09-29) |
| TL1MKT (`tl1mkt`) | Dossier reviewed | Correct device identifier, scope-specific branches and unknown ownership verification require review. | [1](https://www.tl1mkt.com/privacy/) (2026-09-29); [2](https://www.tl1mkt.com/opt-out/) (2026-09-29) |
| Trestle (`trestle`) | Dossier reviewed | Identity-risk context and unspecified verification prevent minimal-email automation. | [1](https://trestleiq.com/privacy-policy/) (2026-09-29) |
| Trust & Will (`registry-huge-legal-technology-company-inc`) | Public page checked | Confirm relevant estate-planning or partner-sharing exposure and regional applicability; do not erase estate documents or an account to obtain advertising suppression. | [1](https://trustandwill.com/security/privacy-policy) (2026-09-29) |
| Urban Science (`urban-science`) | Public page checked | Product/jurisdiction and conditional identity matching need review; opt-out fields unrendered. | [1](https://www.urbanscience.com/privacy/) (2026-09-29); [2](https://www.urbanscience.com/opt-out/) (2026-09-29) |
| USADATA (`usadata`) | Public page checked | The opt-out can forward requests to Acxiom and Data Axle; confirm regional eligibility and matching, and do not count forwarded requests as source deletion. | [1](https://www.usadata.com/donotsellmyinformation) (2026-09-29); [2](https://www.usadata.com/ccpa) (2026-09-29) |
| Vendelux (`vendelux`) | Retrieval incomplete; dossier reviewed | The policy expressly permits email instead of its portal; the current fetch masks the recipient, so reconfirm the previously recorded address and profile matching. | [1](https://vendelux.com/privacy) (2026-09-29) |
| Venntel (`venntel`) | Dossier reviewed | Sensitive location/security context and verification require human review. | [1](https://www.venntel.com/privacy-policy) (2026-09-29); [2](https://www.venntel.com/opt-out) (2026-09-29) |
| Veraset (`veraset`) | Dossier reviewed | Technical ID matching and possession checks require review. | [1](https://www.veraset.com/legal/privacy-policy) (2026-09-29); [2](https://www.veraset.com/legal/gdpr-privacy-addendum) (2026-09-29); [3](https://www.veraset.com/legal/do-not-sell-request) (2026-09-29) |
| VRTCAL (`vrtcal`) | Dossier reviewed | Technical identifiers, proof and sworn EEA assertion need personal review; old policy instructions need current-device validation. | [1](https://www.vrtcal.com/wp-content/uploads/2022/09/PrivacyPolicy-Advertising.pdf) (2026-09-29); [2](https://vrtcal.com/docs/subject-access-request-policy.pdf) (2026-09-29) |
| WealthFeed (`wealthfeed`) | Dossier reviewed | Regional limits and conflicting phone requirements need review. | [1](https://www.wealthfeed.com/do-not-sell-my-data/) (2026-09-29); [2](https://www.wealthfeed.com/privacy-policy/) (2026-09-29); [3](https://www.wealthfeed.com/wealthfeed-prospecting-platform-selected-by-the-mather-group/) (2026-09-29) |
| Weborama (`weborama`) | Dossier reviewed | Obtain the Weborama identifiers from its two official cookie-info pages in the affected browser; a new reply mailbox cannot locate cookie-only records. | [1](https://www.weborama.com/privacy) (2026-09-29) |
| Wunderkind (`wunderkind`) | Dossier reviewed | Digital identifiers and missing affidavit require user review, not generic mail. | [1](https://www.wunderkind.co/privacy/data-request-instructions/) (2026-09-29); [2](https://www.wunderkind.co/privacy/) (2026-09-29) |
| Wurl advertising and media services (`wurl`) | Dossier reviewed | Device-data authentication limitation prevents dependable generic email erasure. | [1](https://www.wurl.com/wurl-advertising-and-media-services-privacy-notice/) (2026-09-29) |
| Zeotap Data — Roqad audience data (`zeotap-data`) | Dossier reviewed | Device identifiers and browser-specific choices require user involvement. | [1](https://zeotapdata.net/privacy-policy/) (2026-09-29); [2](https://roq.ad/opt-out) (2026-09-29); [3](https://zeotapdata.net/zeotap-data-powered-contextual-expansion/) (2026-09-29); [4](https://zeotapdata.net/) (2026-09-29) |
| ZeroToOne.AI (`zerotoone-ai`) | Dossier reviewed | Sworn declaration, account reauthentication or device-ownership checks cannot be silently completed. | [1](https://www.zerotoone.ai/privacy-policy) (2026-09-29); [2](https://www.zerotoone.ai/do-not-sell-my-personal-information) (2026-09-29) |

## Practical next development work

1. Matching identifiers: explicitly approved professional email/employer fields
   would support the SalesIntel/RevenueBase branch. Live Data's conflicting
   published checklists need resolution first. Do not infer an employer or silently
   transmit extra identifiers.
2. Public-profile matching: Brandwatch/Graze need the affected public profile;
   location/adtech records need deliberately supplied device/browser identifiers.
   These are different workflows, not more name/email templates.
3. Identity and credit records: keep documents, signed declarations, access-first
   requests and case-specific objections as personal steps. Do not invent facts,
   signatures or erasure grounds.
4. Forms and regional routes: inspect actual fields and verification before counting
   integrations; restore blocked official-source checks and confirm regional scope.
   An American headquarters is neither an exclusion nor proof of European exposure.
5. Outcome learning: run authorized real requests, preserve no-match scope and
   follow-up burden, and incorporate verified replies without sharing private data.

New workflows require review of the updated campaign preview; old permission does
not silently authorize new recipients or postal disclosure. Existing completed
requests stay complete and are excluded from repeat initial sends. Unchanged,
already approved workflows can continue under the existing daily budget.

## Reproduce

The live post-deploy check also revealed an obsolete research throttle: more than
100 old research rows recorded today stopped newly approved, already-reviewed local
workflows. Old future research retry dates could block them too. A synthetic
positive control passed before the fix; all three limit/cooldown variants failed.
The controller now checks at most 25 approved recipes per minute before preparation,
without a daily research quota. No website requests are made by these checks.
Legacy queued research jobs remain supported, but do not block the local batch.
Personal action-needed cases, expired evidence, changed consent and the atomic
daily sending budget still gate work.

Run `uv run erasure-catalog audit --require-pilot` for structural readiness of the
declared cohort, and `uv run pytest -q` for synthetic workflow/dispatch regression
tests. The audit's `execution.email_workflow_backlog` is the current machine-readable
backlog; this report records the dated assessment. Whole-inventory
`--require-complete` remains a separate, stricter check.

Verification for this revision: 312 tests passed, Ruff passed, and the pilot audit
passed. Tests include every published route, negative disclosure gates, legacy
research-limit/cooldown recovery, bounded local checks, and unchanged daily-send
and repeat-dispatch safeguards. One upstream Starlette/httpx deprecation warning
remains. An encrypted backup was made before each local deployment.
