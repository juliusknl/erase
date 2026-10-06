# Major marketing and people-search coverage

Checked 4 October 2026. This follows the separate [reply reliability audit](release-reply-audit-2026-10-04.md).

## What we can honestly say

Erase includes reviewed request routes for many major marketing and public
people-search providers. It is not an exhaustive service, and support depends on
the product, country and matching information available. A reviewed route is not
proof that a form was successfully submitted or that a broker deleted anything.

The fixed [priority checklist](../catalog/major-brokers.yml) contains **34 families**:

- **28** have app routes for all the country/product examples declared in the checklist.
- **3** have partial coverage: Data Axle, Circana and BeenVerified have EEA initial
  email workflows, but their UK/US paths are not yet wired into guided actions.
- **3** have no current usable route in this checklist: Nuwber, Radaris and PeekYou.

Thus **31 families have at least one supported country-specific path**. This does
not mean 31 are fully automated or that 91% of anyone's data is covered. These are
editorial priorities, not an independently established market-share ranking.
Professional databases are already elsewhere in the catalog and outside this audit.

## The actual shortlist

| Area | Reviewed routes wired for declared countries/products |
| --- | --- |
| Marketing suppliers and audience platforms | Acxiom, Epsilon, LiveRamp, Experian Marketing, TransUnion/Neustar, Merkle, Claritas, Eyeota, Nielsen Marketing Cloud, Quantcast, Criteo, The Trade Desk |
| European marketing and postal-data providers | AZ Direct, Deutsche Post Direkt, Capaneo/Schober, CACI, Numberly, Weborama, Zeotap Data/Roqad |
| Public people search | Whitepages, Spokeo, PeopleConnect, TruePeopleSearch, FastPeopleSearch family, PeopleFinders, FamilyTreeNow, ThatsThem, 192.com |
| Partial regional integration | Data Axle, Circana, BeenVerified |
| Unresolved | Nuwber, Radaris, PeekYou |

PeopleConnect covers the four named services Intelius, TruthFinder, Instant Checkmate
and US Search through its shared suppression tool. Its non-US permission limitation
remains documented. FastPeopleSearch's operator declares one record opt-out across
ten named sites. Count this as one family, not ten independently proven deletions.
Its cookie preferences still require separate per-site choices.

## What changed in the app

- Added **22 manual resources**, including four personal-email steps with public
  placeholder drafts. Those drafts open in the user's mail app; they do not send
  or disclose profile details automatically. Users must fill, review and send.
- Added five reviewed people-search guides and one blocked historical-domain guide.
- Fixed country tags that kept some US forms out of US recommendations; classified
  192.com as people search instead of postal marketing.
- Updated Acxiom's German and US/international instructions and LiveRamp's UK portal.
- Curated manual routes now appear in the broker library and on the single broker
  page, with the relevant instructions and Open/Done controls.
- Major checklist entries take priority within each existing category. Three-item
  sessions, existing completions and automatic-email deduplication remain intact.
- Done records a user-completed step, not confirmed deletion. Existing confirmed
  deletion/no-match outcomes are preserved.

Catalog totals after this change: **645 guides, 80 distinct initial-email workflows,
147 manual resources**. These are different measures, not 645 working automations.
No new automatic email recipes or consent scopes were added in this change.

## Evidence and limitations

The people-search additions use current operator declarations in the
[California registry export](https://cppa.ca.gov/data_broker_registry/registry.csv).
Those filings are broker statements, not regulator certification. Interactive
TruePeopleSearch, FastPeopleSearch, PeopleFinders, FamilyTreeNow and ThatsThem
pages blocked inspection; unknown fields and untested confirmation steps remain
explicit. PeekYou's former opt-out now displays a domain-transfer notice, as does
the reviewed Radaris route. Neither is evidence that historical data was deleted.
Nuwber's domain failed resolution during this check; no working route was inferred.

Other checks included [Acxiom Germany](https://www.acxiom.de/datenschutzanfragen/),
[Acxiom US/international instructions](https://www.acxiom.com/privacy/us/consumer-instructions/),
[Epsilon's regional request center](https://legal.epsilon.com/dsr),
[LiveRamp UK rights](https://liveramp.com/uk/privacy/your-rights),
[CACI's policy](https://www.caci.co.uk/data-privacy/privacy-policy/),
[Weborama's policy](https://www.weborama.com/privacy),
[Numberly's policy](https://numberly.com/en/privacy/),
and [Zeotap Data's policy](https://zeotapdata.net/privacy-policy/).
Individual guides retain source dates, scope, requirements and unresolved questions.

“Country and product scope” means, for example, that removing Experian marketing
data is not deleting a credit report, and a German Acxiom action is not a promise
to erase every subsidiary or customer copy worldwide. US-based brokers can still
be relevant to Europeans; company headquarters do not determine residence eligibility.

## Repeatable checks

Run from `tools/erasure`:

```sh
uv run erasure-catalog audit --require-major-routes
uv run pytest -q tests/test_major_brokers.py
```

The audit intentionally exits **1** while the regional and unresolved gaps remain.
Missing resources, stale evidence and wrong-country actions must not turn green.
The tests cover those failures, exact shared-site scope, safe placeholder drafts,
priority ordering, read-only broker navigation and manual completion without sending.

Verification: 823 non-browser tests and 51 Chromium/WebKit browser tests passed;
lint passed. The local real app and isolated demo were rebuilt and reported healthy.
Authenticated read-only checks confirmed the main pages load, new manual brokers
are discoverable, and personal-email actions render. Existing sending permissions
were preserved. No test submitted a broker form or sent a broker email.

Before claiming universal major-broker coverage, wire and validate the remaining
UK/US routes and resolve the historical/domain gaps. Before claiming hands-off
results, obtain live request outcomes; a catalog or passing software test cannot
substitute for them. No private replies or credentials are included in this report.
