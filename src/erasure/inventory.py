"""Public research coverage, separate from personal exposure and sending consent."""

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from erasure.knowledge import Evidence, StrictModel


class Assessment(StrictModel):
    record: str
    disposition: Literal["guide", "duplicate", "out_of_scope", "unresolved"]
    guide_id: str | None = None
    duplicate_of: str | None = None
    checked_on: date
    rationale: str = Field(min_length=30)
    evidence: list[Evidence] = Field(min_length=1)
    unresolved: list[str]

    @model_validator(mode="after")
    def coherent(self):
        if self.checked_on > datetime.now(UTC).date():
            raise ValueError("Assessment cannot be dated in the future")
        if (self.disposition == "guide") != bool(self.guide_id):
            raise ValueError("Guide assessment requires exactly one guide ID")
        if (self.disposition == "duplicate") != bool(self.duplicate_of):
            raise ValueError("Duplicate assessment requires a canonical record")
        if self.disposition == "unresolved" and not self.unresolved:
            raise ValueError("Unresolved assessment must explain outstanding work")
        return self


class AssessmentFile(StrictModel):
    schema_version: Literal[1]
    assessments: list[Assessment]


class GuideAssociation(StrictModel):
    guide_id: str
    records: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=30)


class GuideAssociations(StrictModel):
    schema_version: Literal[1]
    associations: list[GuideAssociation]


class DiscoveryCandidate(StrictModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=2)


class DiscoveryBatch(StrictModel):
    """A source-led research queue, never a verified guide or sending target."""

    schema_version: Literal[1]
    regions: list[str] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    rationale: str = Field(min_length=30)
    candidates: list[DiscoveryCandidate] = Field(min_length=1)


def inventory(catalog_dir: Path):
    result = {}

    def add(key, row):
        if key in result:
            raise ValueError(f"Duplicate inventory identity: {key}")
        result[key] = row

    snapshot = catalog_dir / "inventory/live-catalog.json"
    if snapshot.exists():
        for row in json.loads(snapshot.read_text())["brokers"]:
            add("live:" + row["slug"], row)
    discoveries = catalog_dir / "inventory/europe-discovery.json"
    if discoveries.exists():
        for row in json.loads(discoveries.read_text())["records"]:
            add("community:" + row["slug"], row)
    for path in sorted((catalog_dir / "inventory/discoveries").glob("*.yml")):
        batch = DiscoveryBatch.model_validate(yaml.safe_load(path.read_text()))
        for candidate in batch.candidates:
            add("discovery:" + candidate.slug, {
                **candidate.model_dump(), "regions": batch.regions,
                "evidence": [source.model_dump(mode="json") for source in batch.evidence],
                "rationale": batch.rationale,
            })
    return result


def coverage_audit(catalog_dir, guides):
    rows = inventory(catalog_dir)
    assessed, problems = {}, []
    guide_ids = {guide.id for guide in guides}
    by_id = {guide.id: guide for guide in guides}
    association_files = [catalog_dir / "inventory/reviewed-associations.yml"]
    association_files.extend(sorted((catalog_dir / "inventory/associations").glob("*.yml")))
    for associations in association_files:
        if not associations.exists():
            continue
        mappings = GuideAssociations.model_validate(yaml.safe_load(associations.read_text()))
        for mapping in mappings.associations:
            guide = by_id.get(mapping.guide_id)
            if guide is None:
                problems.append(f"Missing associated guide: {mapping.guide_id}")
                continue
            for record in mapping.records:
                if record in assessed:
                    raise ValueError(f"Duplicate inventory assessment: {record}")
                if record not in rows:
                    problems.append(f"Unknown associated record: {record}")
                assessed[record] = Assessment(
                    record=record,
                    disposition="guide" if guide.review_status == "instructions_reviewed" else "unresolved",
                    guide_id=guide.id if guide.review_status == "instructions_reviewed" else None,
                    checked_on=guide.checked_on, rationale=mapping.rationale,
                    evidence=guide.evidence,
                    unresolved=guide.unknowns if guide.review_status == "needs_research" else [],
                )
                if not guide.fresh:
                    problems.append(f"Stale associated guide: {guide.id}")
    for path in sorted((catalog_dir / "assessments").glob("*.yml")):
        document = AssessmentFile.model_validate(yaml.safe_load(path.read_text()))
        for assessment in document.assessments:
            if assessment.record in assessed:
                raise ValueError(f"Duplicate inventory assessment: {assessment.record}")
            assessed[assessment.record] = assessment
            if assessment.record not in rows:
                problems.append(f"Unknown inventory record: {assessment.record}")
            if assessment.guide_id and assessment.guide_id not in guide_ids:
                problems.append(f"Missing guide: {assessment.guide_id}")
            elif assessment.guide_id:
                guide = by_id[assessment.guide_id]
                if guide.review_status != "instructions_reviewed":
                    problems.append(f"Unreviewed assessed guide: {guide.id}")
                if not guide.fresh:
                    problems.append(f"Stale assessed guide: {guide.id}")
            if assessment.duplicate_of and assessment.duplicate_of not in rows:
                problems.append(f"Missing duplicate target: {assessment.duplicate_of}")
            if (datetime.now(UTC).date() - assessment.checked_on).days > 90:
                problems.append(f"Stale assessment: {assessment.record}")
    # Duplicates cannot close a cycle or point to an unassessed/unresolved record.
    for key, assessment in assessed.items():
        visited = {key}
        target = assessment.duplicate_of
        while target:
            if target in visited or target not in assessed:
                problems.append(f"Unresolved duplicate chain: {key}")
                break
            visited.add(target)
            next_row = assessed[target]
            if next_row.disposition == "unresolved":
                problems.append(f"Duplicate points to unresolved record: {key}")
            target = next_row.duplicate_of
    pending = sorted(set(rows) - set(assessed))
    unresolved = sorted(key for key, row in assessed.items() if row.disposition == "unresolved")
    unresolved_guides = sorted(guide.id for guide in guides if guide.review_status == "needs_research")
    stale_guides = sorted(guide.id for guide in guides if not guide.fresh)
    source_counts = {prefix: sum(key.startswith(prefix + ":") for key in rows)
                     for prefix in ("live", "community", "discovery")}
    return {
        "inventory_records": len(rows), "inventory_sources": source_counts,
        "assessed_records": len(set(rows) & set(assessed)),
        "pending_assessment": pending, "unresolved_assessments": unresolved,
        "unresolved_guides": unresolved_guides, "stale_guides": stale_guides,
        "integrity_problems": problems,
        # A public-source assessment can have explicitly unknown details. A whole
        # unresolved entry is NOT converted into a completed workflow to hit a target.
        "complete": bool(rows) and not any((pending, unresolved, unresolved_guides, stale_guides, problems)),
    }
