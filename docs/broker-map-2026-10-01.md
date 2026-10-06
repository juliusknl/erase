# Optional broker progress map

**Superseded:** the user rejected this design. The map, its controls, filters,
configuration flag, assets and helper were removed. Home now uses a small static
completion-over-time graph, keeping the original counters and showcase placement.
The remainder of this document is the implementation history of the removed map.

The Home progress card keeps the existing Sent and Completed counters, adds one
equally-sized mark per non-candidate request, and retains the sourced broker
showcase directly underneath. It never uses the research catalog as a denominator
or weights marks by database-size claims. It makes no estimate of exposure or
records deleted. Bare candidates are excluded; prepared and queued requests are
included as work in progress, with their exact state available on selection.

Categories use the reviewed guide where available, otherwise the stored category.
Names sort alphabetically within fixed category groups; a status change doesn't
reorder existing marks. Done combines personal completion, broker-reported
deletion and no match; selection distinguishes those outcomes. Only genuine
attention tasks receive Needs you. Internal holds, failed delivery, rejection
and unknown states appear Paused rather than silently counting as active work.

Hover/focus/tap shows the name, recorded outcome/state and meaningful update time.
Open request navigates to the canonical request page. Without JavaScript, marks
are ordinary request links. Category and status links filter the same request
history using the same classification functions. Data reflects the page load;
the existing automation-status poll is unchanged.

## Reversibility

- **Hide map / Show map** is a browser-local display preference. Counts, outcomes,
  consent, schedules, emails and existing requests are untouched.
- Set **ERASURE_BROKER_MAP_ENABLED=false** in local configuration and restart to
  restore the exact earlier counters/showcase layout, without map assets or its
  additional request query. For Docker, rebuild/restart with the usual
  `uv run erasure-keychain up` command.
- Implementation is isolated in `broker_map.py`, `broker_map.html`,
  `broker-map.css` and `broker-map.js`, with small guarded Home integration and
  two optional request-history filter parameters. No migration, dependency or
  external chart/font service was added.

The 320px browser test also exposed a pre-existing Home grid minimum-width issue;
the dashboard cards now shrink correctly and the country form stacks at narrow
widths. It does not hide page overflow.

## Verification

Unit/API tests cover candidate exclusion, mutually exclusive states, completion
evidence distinctions, stable ordering, guide-based categories, filtered history,
empty state, configuration rollback, and no Case/Event/Job mutations. Browser
tests cover Chromium/WebKit at 320/390/1440px, keyboard selection, request links,
category/status navigation, persistent hide/show, and the no-JavaScript fallback.

Final validation: 672 tests passed; touched Python files pass Ruff. The deployed
local app passed read-only Chromium/WebKit checks at 390/1440px with 101 tracked
brokers and 18 Done at verification. Confirmed working drill-downs, filters,
persistent hide/show, no horizontal overflow, no script errors and no POSTs from
map interaction. Screenshots were visually reviewed. No request records were
created by the live checks; nothing was pushed or published.
