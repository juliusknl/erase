import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
import yaml
from pydantic import ValidationError

from erasure.config import Settings
from erasure.inventory import Assessment, coverage_audit, inventory
from erasure.knowledge import guides


def fixture_inventory(tmp_path):
    path = tmp_path / "inventory"
    path.mkdir()
    (path / "live-catalog.json").write_text(json.dumps({"brokers": [
        {"slug": "one", "name": "One", "domain": "one.example"},
        {"slug": "two", "name": "Two", "domain": "two.example"},
    ]}))
    (tmp_path / "assessments").mkdir()


def assessment(record="live:one", disposition="out_of_scope", **kwargs):
    return {
        "record": record, "disposition": disposition,
        "checked_on": datetime.now(UTC).date().isoformat(),
        "rationale": "Official product documentation establishes an ordinary retailer, not a broker.",
        "evidence": [{"url": "https://one.example/privacy", "checked_on": datetime.now(UTC).date().isoformat(),
                      "excerpt": "We sell shoes.", "supports": ["relevance"]}],
        "unresolved": [], **kwargs,
    }


def write_assessments(tmp_path, rows):
    (tmp_path / "assessments/test.yml").write_text(yaml.safe_dump({
        "schema_version": 1, "assessments": rows,
    }))


def test_nothing_and_fetched_material_do_not_pass_completion_gate(tmp_path):
    assert not coverage_audit(tmp_path, [])["complete"]
    fixture_inventory(tmp_path)
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages/one.json").write_text('{"assessment":"pending","pages":["fetched"]}')
    report = coverage_audit(tmp_path, [])
    assert report["pending_assessment"] == ["live:one", "live:two"]
    assert report["assessed_records"] == 0
    assert not report["complete"]


def test_every_entry_requires_a_valid_assessment(tmp_path):
    fixture_inventory(tmp_path)
    write_assessments(tmp_path, [assessment()])
    assert not coverage_audit(tmp_path, [])["complete"]
    write_assessments(tmp_path, [assessment(), assessment("live:two")])
    assert coverage_audit(tmp_path, [])["complete"]


def test_regional_discovery_requires_assessment_not_just_a_source(tmp_path):
    fixture_inventory(tmp_path)
    write_assessments(tmp_path, [assessment(), assessment("live:two")])
    directory = tmp_path / "inventory/discoveries"
    directory.mkdir()
    batch = {
        "schema_version": 1, "regions": ["IT"],
        "evidence": assessment()["evidence"],
        "rationale": "A public association directory identifies a candidate for individual review.",
        "candidates": [{"slug": "italian-candidate", "name": "Candidate Srl"}],
    }
    (directory / "italy.yml").write_text(yaml.safe_dump(batch))
    report = coverage_audit(tmp_path, [])
    assert not report["complete"]
    assert report["pending_assessment"] == ["discovery:italian-candidate"]
    assert report["inventory_sources"]["discovery"] == 1
    assert "destination" not in inventory(tmp_path)["discovery:italian-candidate"]
    write_assessments(tmp_path, [assessment(), assessment("live:two"),
                                 assessment("discovery:italian-candidate")])
    assert coverage_audit(tmp_path, [])["complete"]
    (directory / "duplicate.yml").write_text(yaml.safe_dump(batch))
    with pytest.raises(ValueError, match="Duplicate inventory identity"):
        inventory(tmp_path)


def test_duplicate_snapshot_rows_cannot_silently_disappear(tmp_path):
    fixture_inventory(tmp_path)
    snapshot = tmp_path / "inventory/live-catalog.json"
    snapshot.write_text(json.dumps({"brokers": [{"slug": "one"}, {"slug": "one"}]}))
    with pytest.raises(ValueError, match="Duplicate inventory identity"):
        inventory(tmp_path)


def test_unresolved_and_invalid_guides_fail_gate(tmp_path):
    fixture_inventory(tmp_path)
    write_assessments(tmp_path, [assessment(disposition="unresolved", unresolved=["Cannot establish entity"]),
                                 assessment("live:two", "guide", guide_id="missing")])
    report = coverage_audit(tmp_path, [])
    assert not report["complete"]
    assert report["unresolved_assessments"] == ["live:one"]
    assert "Missing guide: missing" in report["integrity_problems"]


def test_duplicate_cycles_cannot_manufacture_coverage(tmp_path):
    fixture_inventory(tmp_path)
    write_assessments(tmp_path, [assessment(disposition="duplicate", duplicate_of="live:two"),
                                 assessment("live:two", "duplicate", duplicate_of="live:one")])
    assert not coverage_audit(tmp_path, [])["complete"]
    write_assessments(tmp_path, [assessment(disposition="duplicate", duplicate_of="live:two"),
                                 assessment("live:two")])
    assert coverage_audit(tmp_path, [])["complete"]


def test_short_or_unsupported_assessment_rejected():
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment(rationale="Looks fine"))
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment(evidence=[]))
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment(disposition="unresolved"))


def test_explicit_assessment_cannot_hide_an_unreviewed_or_stale_guide(tmp_path):
    from pathlib import Path

    from erasure.knowledge import BrokerGuide

    fixture_inventory(tmp_path)
    document = yaml.safe_load((Path(__file__).parents[1] / "catalog/broker-knowledge.yml").read_text())
    row = deepcopy(document["brokers"][0])
    row["review_status"] = "needs_research"
    row["automation"]["mode"] = "blocked"
    guide = BrokerGuide.model_validate(row)
    write_assessments(tmp_path, [assessment(disposition="guide", guide_id=guide.id), assessment("live:two")])
    report = coverage_audit(tmp_path, [guide])
    assert not report["complete"]
    assert f"Unreviewed assessed guide: {guide.id}" in report["integrity_problems"]
    row["review_status"] = "instructions_reviewed"
    row["evidence"][0]["checked_on"] = "2020-01-01"
    guide = BrokerGuide.model_validate(row)
    report = coverage_audit(tmp_path, [guide])
    assert not report["complete"]
    assert f"Stale assessed guide: {guide.id}" in report["integrity_problems"]
    # An unassociated discovery guide also cannot disappear from the release gate.
    write_assessments(tmp_path, [assessment(), assessment("live:two")])
    report = coverage_audit(tmp_path, [guide])
    assert not report["complete"]
    assert report["stale_guides"] == [guide.id]
    row["evidence"][0]["checked_on"] = datetime.now(UTC).date().isoformat()
    row["review_status"] = "needs_research"
    guide = BrokerGuide.model_validate(row)
    report = coverage_audit(tmp_path, [guide])
    assert not report["complete"]
    assert report["unresolved_guides"] == [guide.id]


def test_duplicate_guide_associations_across_files_are_rejected(tmp_path):
    from pathlib import Path

    document = yaml.safe_load((Path(__file__).parents[1] / "catalog/broker-knowledge.yml").read_text())
    one = {"schema_version": 1, "brokers": document["brokers"][:1]}
    (tmp_path / "broker-knowledge.yml").write_text(yaml.safe_dump(one))
    (tmp_path / "research").mkdir()
    other = deepcopy(one)
    other["brokers"][0]["id"] = "another-entity"
    (tmp_path / "research/other.yml").write_text(yaml.safe_dump(other))
    with pytest.raises(ValidationError, match="ambiguous"):
        guides(Settings(catalog_dir=tmp_path))


def test_regional_routes_cannot_enable_unspecified_region_sending():
    from pathlib import Path

    from erasure.knowledge import BrokerGuide

    document = yaml.safe_load((Path(__file__).parents[1] / "catalog/broker-knowledge.yml").read_text())
    guide = deepcopy(next(row for row in document["brokers"] if row["id"] == "cognism"))
    regional = {"regions": ["UK"], "legal_entity": "Regional controller", "unknowns": []}
    for key in ("removal", "required_information", "coverage", "automation", "evidence"):
        regional[key] = deepcopy(guide[key])
    regional["automation"] = {"mode": "manual", "reason": "Country-specific route"}
    guide["regional_routes"] = [regional]
    with pytest.raises(ValidationError, match="region selection"):
        BrokerGuide.model_validate(guide)
    guide["automation"] = {"mode": "manual", "reason": "Choose regional controller"}
    assert BrokerGuide.model_validate(guide).regional_routes[0].regions == ["UK"]


def test_relationship_services_are_exclusions_not_completed_broker_workflows():
    settings = Settings()
    document = yaml.safe_load(
        (settings.catalog_dir / "assessments/europe-relationship-services.yml").read_text()
    )
    rows = {row["record"]: Assessment.model_validate(row)
            for row in document["assessments"]}
    assert len(rows) == 10
    for row in rows.values():
        assert row.disposition == "out_of_scope"
        assert "default independent-broker outreach" in row.rationale
        assert "not declared data-free" in row.rationale
        assert row.guide_id is None
        assert row.duplicate_of is None
    assert "Gameforge 4D GmbH" in rows["community:gameforge"].rationale
    assert "separate responsible companies" in rows["community:check24"].rationale
    assert "privacy.de.cmt@atolls.com" in rows["community:mydealz"].rationale
    assert "deleting the account and associated reviews" in rows["community:trustpilot"].rationale
    report = coverage_audit(settings.catalog_dir, guides(settings))
    assert not set(rows) & set(report["pending_assessment"])
    assert not report["integrity_problems"]
