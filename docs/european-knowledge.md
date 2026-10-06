# Europe-first broker knowledge

## Product contract

Research is shared product maintenance, not work every user repeats. The app reads
`catalog/broker-knowledge.yml` and `catalog/research/*.yml` locally, validates their
combined identities and domains, displays the guides, and applies
its restrictions before preparation or dispatch. No model API or runtime model call
is needed to read or execute these rules. Personal replies and results stay in the
encrypted user database and are never exported into this public catalog.

The catalog is under active full-inventory review, including regional European
providers and the original registry imports. Use the audit command for current
counts rather than a fixed number in this document. It is **not yet a completed
audit**, a ranking of Europe's biggest brokers, or comprehensive coverage of every
European country. UK, EEA and Switzerland are not interchangeable.

## Record contract

All eight areas are mandatory: identity, relevance, removal, required information,
coverage, automation, evidence and scale. `null` or an explicit unknown is preferable
to an invented parent, size, form field or coverage claim. Quotes are short and
sources have retrieval dates; an old document's publication date stays visible even
when it remains linked by the current official website.

- Stable guide IDs identify reviewed workflows. `match_domains` are explicit
  associations to catalog records; `official_domains` are documentary. Neither
  suffix matching nor shared ownership grants shared deletion coverage.
- Country/region tags describe the guide's scope, not a determination that the user
  is exposed or eligible. Campaign plan selects residence for reviewed executable
  routes; it is not a comprehensive global eligibility engine. The current email
  cohort supports EEA residence, with German-only postal suppression routes.
  UK-only guides remain manual.
- `regional_routes` preserve separate controllers and purposes on shared domains
  (for example German versus UK Creditsafe, or German D&B access versus marketing
  suppression). These require manual selection; no variant grants global authority.
- `instructions_reviewed` means the published instructions were reviewed, not that
  every field or an end-to-end submission was tested. Every guide currently records
  `tested_outcome: not_tested`; personal experiment outcomes remain separate.
- `email_minimal` permits an **initial** approved name/email request only where an
  email rights route is published and no documented extra required field is known.
  Unspecified verification steps stay explicit unknowns. It does not promise full
  automation. Existing contact validation, consent, budget and uncertain-send guards
  still apply; known legacy form gates are never relaxed.
- `catalog/email-routes.yml` defines the broker-specific automatic campaign path.
  It checks guide requirements, exact recipient and effect, then binds the actual
  message to the user's approval. Postal workflows require a matching residence
  and explicit address permission. Phone, mobile-advertising-ID, identity-document,
  regional and access-first workflows still stop for review. A fresh guide alone
  never authorizes extra profile disclosure.
- A contact mismatch or guide older than 90 days blocks email use. Evidence does
  not silently replace a recipient, renew its contact validation, or grant consent.
- Startup adds missing broker discoveries only. Existing contacts, states and
  completed requests are not rewritten. New entries are outside the previously
  approved campaign snapshot until the user reviews a new plan.
- Marketing suppression, erasure and credit-record access/correction remain
  distinct effects, even if the user's task is later marked Done.
- Scale is an optional dated company claim, never a personal-exposure percentage,
  combined total or sending-priority input.

## Registry context

The full catalog also displays existing 2026 registry disclosures about categories
collected or recipients of data. These are broker-reported, dated discovery facts,
not independently verified facts about the user. Matching is by the imported
website domain; ambiguous/multiple legal entities are not merged by this feature.
Historical rows are retained. The importer still needs a separate entity-resolution
and provenance migration before any historical entries can be safely retired.

## Repeatable audit

```sh
uv run erasure-catalog audit
uv run erasure-catalog audit --require-pilot
uv run erasure-catalog audit --require-mvp
uv run erasure-catalog audit --require-complete
uv run pytest -q tests/test_knowledge.py tests/test_inventory.py
```

The audit reads bundled public files only. It lists regional coverage, guide status,
automation boundaries, remaining gaps, stale sources and registry domains without
guides. It never reads a user's profile or mailbox and makes no network calls.

The reproducible inventory has three distinct sources:

- `inventory/live-catalog.json`: read-only allowlisted snapshot of existing public
  broker identities; no profile, mail, request status or credentials.
- `inventory/europe-discovery.json`: pinned CC0 community candidates, not verified
  brokers or current contacts.
- `inventory/discoveries/*.yml`: source-led regional queues, including association
  members and newly found separate entities. These are candidates, not workflows.

Every inventory record requires a substantive assessment or an explicit reviewed
guide association. Member-list presence and successfully fetched pages never close
an item. Source queues do not install brokers or grant sending permissions. Keep
duplicates until evidence establishes identity; duplicate chains must end in a
reviewed assessment. Shared websites do not establish identical legal entities.

`--require-mvp` combines whole-inventory checks with the declared pilot and missing
automatic-email implementation checks. It stays red even when the small pilot is
green. `--require-complete` checks research completeness alone and deliberately
exits nonzero while records await assessment,
substantive unresolved entries remain, evidence is stale, references are broken,
or duplicate chains are invalid. Explicit guide assessments cannot hide an
unreviewed or stale guide. The gate is necessary but not sufficient for release:
independent source checks, broad regional discovery and tested workflows are still
required. Do not shrink the inventory or relabel unknowns just to pass it.

The bounded public-source collector in `scripts/research_catalog.py` writes only
ignored `.research-cache` material. A page fetch is research input, not validation.
The full research ledger and remaining source frontiers are in `docs/research/`.

## Next curation work (not done)

1. Resolve all historical/current registry identities, shared domains, rebrands and
   duplicate entities, retaining original source rows and migration evidence.
2. Expand country-specific marketing coverage beyond this German/UK-heavy first
   cohort: France, Benelux, Nordics, Austria, Switzerland, Spain and Italy. Include
   globally headquartered companies based on European processing, not HQ alone.
3. Resolve the recorded form-field and controller gaps, then test representative
   workflows end to end with consenting users. Prioritize identifier-rich sources
   and short, reliable workflows rather than raw catalog size.
4. Extend the approved, field-specific previews beyond the initial email/postal
   cohort. Device workflows still need dedicated matching and consent. Shared
   knowledge must not become blanket permission to upload personal identifiers.
5. Add maintained form integrations and reviewed versioned catalog updates. Keep
   the normal scheduler deterministic; optional generative assistance can propose
   new knowledge but must not directly edit authority or destinations.

Success is an assessed catalog with actionable, tested coverage and honest gaps—not
600 email addresses or 600 unchecked deletion claims.
