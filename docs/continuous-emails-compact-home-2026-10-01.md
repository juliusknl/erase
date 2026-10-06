# Continuous email routes and compact Quick wins

Local-only implementation requested on 2026-10-01. Nothing published or pushed.

## Automatic email work

The recurring approval prompt came from a frozen `plans` map. A newly reviewed
recipe was ineligible until the user saved a new preview, even if it matched the
existing residence and disclosure settings.

The campaign setup now explicitly authorizes ongoing reviewed routes (`include_new`).
Every controller tick can add a new, fresh, applicable initial email route before
normal validation, preparation and guarded dispatch. It excludes specialist
categories, missing required identifiers and unapproved postal disclosure. Existing
templates are not silently replaced, submitted requests are not redirected,
completed requests stay completed, and guide aliases do not create duplicate work.
Legacy consent without `include_new` remains fixed until the user authorizes it.

For this installation, the user's request authorized enabling that one flag on the
existing plan; the country, daily limit (20) and postal permission (off) were kept.
The worker added 43 eligible routes and sent 20 requests automatically. Of the
remaining 23, ten were already prepared at verification. Sending resumes on the
next UTC day while the local worker is running. The two other workflows previously
advertised as new already had submitted requests and were not resent.

## Home and Quick wins

- Removed the duplicate email-activity/controls panel from Home. Settings retains
  authorization, stop controls and diagnostic information.
- Three compact rows with broker name, instruction and adjacent Open / Done controls.
- Removed circular tick controls and repeated category labels, including in the library.
- Shared completion controls keep the same CSRF-protected endpoint and preserve the
  distinction between user completion and broker-reported deletion.
- Positive heading; info available on hover, focus or tap, with full scope/requirements
  still reachable. The tooltip uses native controls and works without JavaScript.
- Status polling no longer depends on the removed panel being present.

## Verification

The regression failed before the controller change and passes afterward. The full
suite passed 656 tests; ten targeted continuous-plan/API regressions passed after
adding one additional new-catalog/alias test. Browser tests cover completion,
undo, a three-action session that does not refill, live polling and tooltip access.
Read-only live Chrome and WebKit checks passed at widths 1440 and 390 with no
horizontal overflow. Desktop Quick wins height: 538 / 537 CSS pixels respectively.
Ruff checks passed. All 18 preexisting completed outcomes (including completion
timestamps) remained unchanged, and SQLite integrity check returned `ok`.

Encrypted backup: `backups/pre-continuous-emails-20261001.erasurebak`.

## Progress visualization proposal (not implemented)

A compact broker grid, one mark per started request, grouped into Waiting, Needs
you and Done. Hover/focus reveals broker and precise outcome; click opens its
history. Within Done, distinguish deletion reported, no match and user-completed
steps. Keep the existing sent/completed counters and large-broker showcase.
Do not represent the entire catalog as personal exposure or claim a percentage of
personal data deleted. Inspiration: Edward Tufte's discussion of well-labelled
process displays and data quality:
https://www.edwardtufte.com/notebook/executive-dashboards/
