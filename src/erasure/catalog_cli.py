"""Read-only public-knowledge audit; no user database, mailbox, or network access."""

import argparse
import json
from collections import Counter
from pathlib import Path

from erasure.catalog_readiness import mvp_readiness, readiness
from erasure.config import Settings
from erasure.email_routes import routes
from erasure.inventory import coverage_audit
from erasure.knowledge import guides, registry_context
from erasure.major_brokers import coverage as major_coverage


def audit(settings):
    records = guides(settings)
    registry = registry_context(settings)
    associated = {domain for guide in records for domain in guide.match_domains}
    executable = {route.guide_id: route for route, guide in routes(settings).values()}
    return {
        "guides": len(records),
        "review_status": dict(Counter(g.review_status for g in records)),
        "automation": dict(Counter(g.automation.mode for g in records)),
        "execution": {
            "reviewed_initial_email_workflows": len(executable),
            "primary_email_guides": sum(g.removal.method == "email" for g in records),
            "email_workflow_backlog": [
                {"id": g.id, "name": g.name, "review_status": g.review_status,
                 "required_fields": g.required_information.fields,
                 "field_certainty": g.required_information.certainty,
                 "verification": g.required_information.verification,
                 "remaining_review": g.automation.reason,
                 "next_steps": g.removal.steps,
                 "official_sources": [
                     {"url": source.url, "checked_on": source.checked_on.isoformat()}
                     for source in g.evidence
                 ]}
                for g in records if g.removal.method == "email" and g.id not in executable
            ],
            "postal_workflows": [r.guide_id for r in executable.values() if "postal_address" in r.fields],
            "stale_workflows": [r.guide_id for r in executable.values() if not r.fresh],
            "live_outcomes": "Personal outcomes remain in each user's private database",
        },
        "regions": dict(Counter(region for g in records for region in g.relevance.regions)),
        "registry_domains": len(registry),
        "registry_domains_without_guide": sorted(set(registry) - associated),
        "guides_not_in_current_registry": [
            g.id for g in records if not set(g.match_domains).intersection(registry)
        ],
        "stale_guides": [g.id for g in records if not g.fresh],
        "remaining_gaps": {g.id: g.unknowns for g in records if g.unknowns},
        "end_to_end_tested": 0,
        "coverage_audit": coverage_audit(settings.catalog_dir, records),
        "pilot": readiness(settings),
        "major_brokers": major_coverage(settings),
        "mvp": mvp_readiness(settings),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit"])
    parser.add_argument("--catalog-dir", type=Path, default=Path("catalog"))
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--require-pilot", action="store_true")
    parser.add_argument("--require-mvp", action="store_true")
    parser.add_argument("--require-major-routes", action="store_true")
    args = parser.parse_args()
    report = audit(Settings(catalog_dir=args.catalog_dir))
    print(json.dumps(report, indent=2))  # noqa: T201
    if args.require_complete and not report["coverage_audit"]["complete"]:
        raise SystemExit(1)
    if args.require_pilot and not report["pilot"]["initial_routes_ready"]:
        raise SystemExit(1)
    if args.require_mvp and not report["mvp"]["ready"]:
        raise SystemExit(1)
    if args.require_major_routes and not report['major_brokers']['all_routes_wired']:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
