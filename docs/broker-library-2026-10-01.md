# Broker library cleanup

## Usable library and navigation correction

The user subsequently narrowed the library to brokers reachable through the app:
current, reviewed email workflows or reviewed removal forms, excluding blocked
automation routes. Published email addresses without executable workflows,
manual research instructions, stale guides and research-only discoveries are
not listed. This yields 348 current live entries (87 email and 261 form routes).
Counts and visible filters use that same usable set, not the 921-record research
catalog. Existing request histories and underlying research records stay intact.

Removed “View broker details” and “Prepare request” buttons from request overview
panels. Existing tabs retain access to instructions and conversation.

Added ascending/descending column sorting to the library, requests, recent
requests, prepared batches and the advanced catalog snapshot. Library sorting
happens before pagination and preserves filters; non-paginated tables sort their
full rendered data locally. Date cells carry numeric timestamps. Sorting headers
have accessible direction indicators, work with keyboards, and never submit the
batch form or replace checked inputs. Action-only columns are not sortable.

Replaced the settings shortcut row with shared Your details / Automatic emails
tabs. Requests and Quick wins use the same tab styling and indicate the current
view. Removed the always-present Gmail shortcut from the sidebar; contextual
connection controls remain when the mailbox needs attention. Narrow-screen tabs
scroll within their own row rather than overflowing the page.

Validation: 667 tests passed. Targeted Chromium/WebKit tests sort every data
column both ways, check numeric dates, pagination/filter preservation, retained
batch checkbox selections, zero sorting-triggered POSTs, and active settings/
request/action tabs. Read-only live checks passed at 390px and 1440px in both
engines: 348 of 348, no page overflow or script errors, removed overview buttons,
and no requests created by browsing. Changes are deployed locally only.

## Follow-up simplification

At the user's request, Removal route is no longer a list column or filter. Search,
database type and documented region remain. The separate broker detail page has
been deleted: broker names and Details open the existing request page directly.
Untouched brokers use the same Overview / Conversation / Details renderer with a
read-only "Not started" state; browsing creates no case or job. Once a request
exists, the broker URL redirects to its existing case ID, preserving the tab.
All reference information, including registry disclosures and removal routes,
lives in the request's Details tab. Old broker-detail links also redirect there.
The hidden researched-profiles view has been removed. With no visible filters,
the count includes the entire catalog (921 of 921 in the live database).
Quick wins' info popup now ends after “then select Done”; the two requested
qualifying sentences were removed without changing outcome handling.

Regression checks cover the absent filter/column, shared authenticated request
page, old-link redirects, all tabs, preserved filters, unchanged data, full counts,
and the shortened popup. Desktop/mobile Chrome and WebKit tests exercise library
navigation and regional evidence, including wrapping long registry URLs.

Validation of this correction: 663 tests passed; touched Python files pass Ruff.
Deployed locally and checked Chromium/WebKit at 390px and 1440px with JavaScript
disabled. Live results show 921 of 921, old broker links resolve to existing
requests, and all three tabs work for untouched and completed brokers. Browsing
created no requests; the 18 completed outcomes stayed unchanged.

## Original pass

Replaced the two-column table of expandable guides with a compact, read-only
library. Columns are broker, database type, removal route and a consistently
aligned Details control. Small-screen rows use labelled blocks without horizontal
scrolling. Mobile controls have scroll clearance for the fixed navigation.

Search matches broker name, website, reviewed guide name, legal entity and brands.
Filters combine removal route, database type and explicitly documented region.
Results show counts, 50-row pages, reset and empty states. Search/filter context
survives pagination and opening/closing details through ordinary GET links/forms.

Route labels distinguish automatable email, form/portal, manual steps, research
needed and stale instructions. They are shared between filters and rows; they
describe reviewed catalog information, not personal sending eligibility or a
deletion outcome. A reviewed form no longer appears simply as “Not verified”
because a separate email-contact validation timestamp is absent. Region filters
match documented tags, not inferred personal exposure.

Only the selected guide is rendered in a full-width details panel. Sources,
regional routes, unknowns and registry disclosures remain available. If an actual
request exists, the panel links to its existing canonical request page. Catalog
records, consent and workflows are not changed by browsing.

Validation: unit/API tests cover combined filters, literal search, stale/unknown
routes, pagination, details, authentication and read-only state. Browser tests
cover Chrome/WebKit at 390/1440 pixels, keyboard-accessible labelled filters,
aligned controls, regional evidence, empty results and retained filters. Read-only
live checks passed on both engines and widths, with JavaScript disabled.
Existing guide tests now open the selected guide rather than expecting every
guide's evidence to be embedded in the catalog overview. Ruff passed.

Deployed locally with `erasure-keychain up`. No publishing, new consent or manual
email submissions. Existing automatic work continues under the prior plan.
