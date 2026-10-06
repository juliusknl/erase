from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erasure.app import create_app
from erasure.catalog_cli import audit
from erasure.config import Settings
from erasure.crypto import generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.knowledge import (
    KnowledgeCatalog,
    email_blocker,
    guide_index,
    guides,
    install_missing,
    registry_context,
)
from erasure.models import Approval, Broker, Case
from erasure.preparation import email_eligible, playbook
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


def test_reviewed_forms_use_public_catalog_and_include_audited_missing_routes():
    from erasure.knowledge import reviewed_form
    from erasure.quick_wins import resources
    config = settings()
    assert reviewed_form(config, 'grin.co') == 'https://grin.co/data-privacy-form/'
    assert reviewed_form(config, 'dstillery.com').startswith('https://privacyportal-eu-cdn.onetrust.com/')
    assert reviewed_form(config, 'attacker.test') == ''
    ids = {item['id'] for item in resources(config)['items']}
    assert {'matchbook-device-data', 'fraiser-consumer-data', 'registry-grin-technologies-inc',
            'hireez-talent-database', 'mediavine-reader-advertising', 'registry-intent-iq-llc'} <= ids


def settings():
    return Settings(catalog_dir=ROOT / "catalog")


def document():
    return yaml.safe_load((ROOT / "catalog/broker-knowledge.yml").read_text())


def test_split_catalog_is_cached_as_a_snapshot_and_invalidates_on_changes(tmp_path, monkeypatch):
    import erasure.knowledge as knowledge

    base = deepcopy(document()["brokers"][0])
    directory = tmp_path / "research"
    directory.mkdir()
    (tmp_path / "broker-knowledge.yml").write_text("schema_version: 1\nbrokers: []\n")
    rows = []
    for i in range(12):
        row = deepcopy(base)
        row.update(id=f"cache-{i}", name=f"Cache {i}", match_domains=[f"cache-{i}.example"])
        row["identity"]["official_domains"] = row["match_domains"]
        rows.append(row)
        (directory / f"{i:02}.yml").write_text(yaml.safe_dump({"schema_version": 1, "brokers": [row]}))
    original_load = knowledge.yaml.safe_load
    loads = []

    def counted_load(value):
        loads.append(1)
        return original_load(value)

    monkeypatch.setattr(knowledge.yaml, "safe_load", counted_load)
    config = Settings(catalog_dir=tmp_path)
    assert len(guides(config)) == 12
    first_count = len(loads)
    assert first_count == 13
    assert len(guides(config)) == 12
    assert len(loads) == first_count  # More files must not cause LRU thrashing.
    rows[0]["name"] = "Changed route title"
    (directory / "00.yml").write_text(yaml.safe_dump({"schema_version": 1, "brokers": [rows[0]]}))
    assert guides(config)[0].name == "Changed route title"
    extra = deepcopy(rows[0])
    extra.update(id="cache-extra", match_domains=["cache-extra.example"])
    extra["identity"]["official_domains"] = extra["match_domains"]
    extra_path = directory / "extra.yml"
    extra_path.write_text(yaml.safe_dump({"schema_version": 1, "brokers": [extra]}))
    assert len(guides(config)) == 13
    extra_path.unlink()
    assert len(guides(config)) == 12
    # Cached success must not hide newly introduced cross-file ambiguity.
    rows[0]["match_domains"] = rows[1]["match_domains"]
    (directory / "00.yml").write_text(yaml.safe_dump({"schema_version": 1, "brokers": [rows[0]]}))
    with pytest.raises(ValidationError, match="ambiguous"):
        guides(config)


def test_public_catalog_is_typed_and_honest_about_coverage():
    report = audit(settings())
    assert report["guides"] >= 14
    assert report["end_to_end_tested"] == 0
    assert report["regions"]["DE"] >= 4
    assert report["regions"]["UK"] >= 4
    assert report["registry_domains"] > 500
    # Coverage grows: assert the exact unmatched set, not a minimum backlog size.
    assert report["registry_domains_without_guide"] == sorted(
        set(registry_context(settings())) - set(guide_index(settings()))
    )
    assert "az-direct-de" in report["guides_not_in_current_registry"]
    assert guide_index(settings())["az-direct.com"].scale.unit == "people represented in AZ DIAS"
    assert all(g.unknowns for g in guides(settings()))


@pytest.mark.parametrize("mutation", ["duplicate", "extra", "javascript", "future", "unsafe"])
def test_invalid_or_unsafe_public_knowledge_is_rejected(mutation):
    data = deepcopy(document())
    row = data["brokers"][0]
    if mutation == "duplicate":
        data["brokers"].append(deepcopy(row))
    elif mutation == "extra":
        row["personal_email"] = "private@example.test"
    elif mutation == "javascript":
        row["evidence"][0]["url"] = "javascript:alert(1)"
    elif mutation == "future":
        row["evidence"][0]["checked_on"] = (datetime.now(UTC) + timedelta(days=1)).date()
    else:
        row["automation"]["mode"] = "email_minimal"
        row["required_information"]["fields"] = ["postal_address"]
    with pytest.raises(ValidationError):
        KnowledgeCatalog.model_validate(data)


def test_install_is_additive_and_never_grants_sending_authority(db):
    broker = Broker(
        slug="existing", name="Existing Cognism", domain="cognism.com", contact="old@example.test"
    )
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="removed")
    db.add(case)
    db.commit()
    count = install_missing(db, settings())
    assert count == len(guides(settings())) - 1
    assert install_missing(db, settings()) == 0
    assert broker.contact == "old@example.test"
    assert case.state == "removed"
    assert db.scalar(select(func.count()).select_from(Case)) == 1
    assert all(b.last_validated_at is None for b in db.scalars(select(Broker)))


def test_minimal_email_guard_checks_exact_destination_and_freshness():
    guide = guide_index(settings())["cognism.com"]
    assert email_blocker(guide, "privacy@cognism.com") == ""
    assert "differs" in email_blocker(guide, "old@cognism.com")
    stale = guide.model_copy(deep=True)
    stale.evidence[0].checked_on = (datetime.now(UTC) - timedelta(days=91)).date()
    assert "rechecking" in email_blocker(stale, guide.removal.destination)
    for domain in ["az-direct.com", "adsquare.com", "crif.de", "experian.co.uk"]:
        row = guide_index(settings())[domain]
        assert email_blocker(row, row.removal.destination)


def test_guides_restrict_real_preparation_and_dispatch(db, vault, monkeypatch):
    def unexpected_send(*args, **kwargs):
        raise AssertionError("No broker should be sent a generic request in this test")

    monkeypatch.setattr("erasure.gmail.GmailClient.send", unexpected_send)
    store = Store(db, vault)
    workflow = Workflow(db, store, settings())
    for domain in [
        "az-direct.com", "adsquare.com", "crif.de", "experian.co.uk", "cognism.com", "datanyze.com"
    ]:
        broker = Broker(
            slug=domain,
            name=domain,
            domain=domain,
            contact="wrong@example.test",
            connector_type="email",
            last_validated_at=datetime.now(UTC),
        )
        db.add(broker)
        db.flush()
        case = Case(broker_id=broker.id, state="queued")
        db.add(case)
        db.commit()
        assert not email_eligible(broker, settings())
        workflow.submit_case(case.id)
        assert case.state == "needs_action"
        assert db.scalar(select(Approval).where(Approval.case_id == case.id)) is not None


def test_known_form_gates_are_not_relaxed():
    assert playbook(settings(), "kaspr.io")["route"] == "form"
    assert playbook(settings(), "seamless.ai")["route"] == "form"
    assert playbook(settings(), "crif.de")["route"] == "form"


@pytest.mark.parametrize("domain,contact", [
    ("bik.pl", "kontakt@bik.pl"),
    ("cbcb.cz", "klient@crif.com"),
    ("cncb.cz", "klient@crif.com"),
    ("repi.cz", "klient@crif.com"),
    ("crif.cz", "klient@crif.com"),
    ("adform.com", "dpo@adform.com"),
    ("smartclip.tv", "privacy@smartclip.tv"),
    ("at.az-direct.com", "datenschutz@bertelsmann.at"),
    ("sovendus.com", "service@sovendus.com"),
    ("utiq.com", "privacy@utiq.com"),
    ("virtualminds.com", "data.privacy@virtualminds.com"),
    ("apollo.io", "privacy@apollo.io"),
    ("zoominfo.com", "privacy@zoominfo.com"),
    ("emea.epsilon.com", "privacy@epsilon.com"),
    ("experian.it", "stc.italy@experian.com"),
    ("weborama.com", "privacy@weborama.com"),
    ("numberly.com", "dpo@numberly.com"),
    ("isoskele.fr", "droits@isoskele.fr"),
    ("mediaposte.fr", "exercicedesdroits@mediaposte.fr"),
    ("quantcast.com", "privacy.qil@quantcast.com"),
])
def test_reviewed_manual_routes_reject_generic_mail_even_to_official_contact(domain, contact):
    guide = guide_index(settings())[domain]
    assert guide.review_status == "instructions_reviewed"
    assert email_blocker(guide, contact)
    broker = Broker(
        slug=guide.id, name=guide.name, domain=domain, contact=contact,
        connector_type="email", last_validated_at=datetime.now(UTC),
    )
    assert not email_eligible(broker, settings())


def test_shared_czech_request_centre_does_not_merge_register_guides():
    index = guide_index(settings())
    registers = [index[domain] for domain in ["cbcb.cz", "cncb.cz", "repi.cz", "crif.cz"]]
    assert len({guide.id for guide in registers}) == 4
    assert {guide.removal.destination for guide in registers} == {"https://kolikmam.cz/gdpr"}
    assert all(guide.coverage.effect == "access_then_review" for guide in registers)
    assert index["registrporadcu.cz"].id == index["crif.cz"].id


def test_epsilon_digital_abacus_and_north_america_have_separate_scope():
    index = guide_index(settings())
    routes = [index[domain] for domain in ["epsilon.com", "legal.epsilon.com", "emea.epsilon.com"]]
    assert len({guide.id for guide in routes}) == 3
    assert index["emea.epsilon.com"].coverage.effect == "deletion_request"
    assert index["legal.epsilon.com"].coverage.effect == "suppression"
    assert all(guide.tested_outcome == "not_tested" for guide in routes)


def test_sensitive_or_device_matching_fields_remain_explicit():
    index = guide_index(settings())
    assert "identity_document_copy" in index["experian.it"].required_information.fields
    assert "weborama_advertising_identifier" in index["weborama.com"].required_information.fields
    assert "supported_internet_connection" in index["utiq.com"].required_information.fields
    assert index["crif.it"].automation.mode == "manual"
    assert {"signed_request", "identity_document_copy", "tax_code_card_copy"} <= set(
        index["crif.it"].required_information.fields
    )
    assert index["crif.it"].coverage.effect == "access_then_review"
    assert index["crif.it"].review_status == "instructions_reviewed"
    assert any(source.url.endswith("/Messages/InstructionsPF") for source in index["crif.it"].evidence)
    assert "sole_browser_user_attestation" in index["quantcast.com"].required_information.fields


def test_directory_suppression_does_not_require_credit_style_identity_uploads():
    index = guide_index(settings())
    whooz = index["whooz.nl"]
    editus = index["editus.lu"]
    asnef = index["equifax.es"]
    assert whooz.coverage.effect == "suppression"
    assert whooz.required_information.fields == ["postal_address"]
    assert "identity_document_copy" not in editus.required_information.fields
    assert {"main_phone", "listing_details"} <= set(editus.required_information.fields)
    assert "identity_document_copy" in asnef.required_information.fields
    assert asnef.coverage.effect == "access_then_review"
    assert "ASNEF-EQUIFAX" in asnef.identity.legal_name
    assert all(guide.automation.mode == "manual" for guide in [whooz, editus, asnef])


def test_informa_routes_distinguish_database_subjects_and_conditional_verification():
    index = guide_index(settings())
    spanish = index["informa.es"]
    portuguese = index["informadb.pt"]
    assert spanish.removal.destination == "clientes@informa.es"
    assert "clientes@einforma.com" in spanish.removal.alternatives
    assert "sole traders" in " ".join(spanish.removal.steps)
    assert spanish.required_information.fields == []
    assert portuguese.required_information.certainty == "not_fully_specified"
    assert email_blocker(spanish, spanish.removal.destination)
    assert email_blocker(portuguese, portuguese.removal.destination)


def test_ctc_spid_and_signed_request_are_alternatives_not_automatic_uploads():
    guide = guide_index(settings())["ctconline.it"]
    assert "identity_document_or_spid" in guide.required_information.fields
    assert "signed_request_without_spid" in guide.required_information.fields
    assert guide.required_information.certainty == "not_fully_specified"
    assert guide.automation.mode == "manual"
    assert guide.coverage.effect == "access_then_review"
    assert guide.tested_outcome == "not_tested"


def test_postadress_uses_signed_postal_access_without_assuming_id_upload():
    guide = guide_index(settings())["postadress.de"]
    assert guide.required_information.certainty == "documented"
    assert {"date_of_birth", "signature"} <= set(guide.required_information.fields)
    assert "identity_document_copy" not in guide.required_information.fields
    assert email_blocker(guide, "datenschutz@postadress.de")


def test_commercial_database_routes_do_not_assume_unconditional_or_automatic_erasure():
    index = guide_index(settings())
    cerved = index["cerved.com"]
    ellisphere = index["ellisphere.com"]
    iberinform = index["iberinform.es"]
    assert cerved.removal.destination == "cerved@cerved.com"
    assert cerved.coverage.effect == "access_then_review"
    assert "dpo@cerved.com" in cerved.removal.alternatives
    assert ellisphere.scale.unit == "businesses"
    assert "not people" in ellisphere.scale.scope
    assert iberinform.removal.destination == "infoprotecciondatosiber@iberinform.es"
    assert "https://www.iberinform.es/gdpr-data-request-form" in iberinform.removal.alternatives
    for guide in [cerved, ellisphere, iberinform]:
        assert guide.review_status == "instructions_reviewed"
        assert guide.automation.mode == "manual"
        assert guide.required_information.certainty == "not_fully_specified"
        assert guide.required_information.fields == []
        assert guide.tested_outcome == "not_tested"
        assert email_blocker(guide, guide.removal.destination)


def test_norwegian_credit_blocks_and_business_records_stay_manual_and_distinct():
    index = guide_index(settings())
    experian = index["experian.no"]
    infotorg = index["infotorg.no"]
    assert experian.coverage.effect == "access_then_review"
    assert "bankid" in experian.required_information.fields
    assert "Gjeldsregister" in experian.identity.legal_name
    assert infotorg.coverage.effect == "suppression"
    assert "Not erasure" in infotorg.coverage.excludes
    assert index["proff.no"] is index["forvalt.no"]
    assert index["proff.no"].removal.destination == "support@proff.no"
    for domain in ["experian.no", "infotorg.no", "proff.no", "enin.ai"]:
        guide = index[domain]
        assert guide.relevance.regions == ["NO"]
        assert guide.automation.mode == "manual"
        assert guide.tested_outcome == "not_tested"
        for contact in [guide.removal.destination, *guide.removal.alternatives]:
            if "@" in contact:
                assert email_blocker(guide, contact)
    for domain in ["kredittreform.no", "kredittopplysningen.no"]:
        guide = index[domain]
        assert guide.review_status == "needs_research"
        assert guide.automation.mode == "blocked"


def test_creditsafe_norwegian_marketing_does_not_inherit_credit_freeze_id_requirements():
    routes = [route for route in guide_index(settings())["creditsafe.com"].regional_routes
              if route.regions == ["NO"]]
    assert len(routes) == 2
    marketing = next(route for route in routes if route.removal.method == "email")
    freeze = next(route for route in routes if route.removal.method == "manual")
    assert marketing.required_information.fields == []
    assert "bankid_or_identity_document_copy" in freeze.required_information.fields
    assert marketing.coverage.effect == freeze.coverage.effect == "suppression"
    assert marketing.automation.mode == freeze.automation.mode == "manual"


def test_dnb_norway_marketing_suppression_is_not_credit_erasure():
    routes = [route for route in guide_index(settings())["dnb.com"].regional_routes
              if route.regions == ["NO"]]
    assert len(routes) == 2
    marketing = next(route for route in routes if route.coverage.effect == "suppression")
    credit = next(route for route in routes if route.coverage.effect == "access_then_review")
    assert marketing.removal.destination == "ksp.no@dnb.com"
    assert marketing.required_information.fields == []
    assert "bankid_or_signed_identity_document_copy" in credit.required_information.fields
    assert marketing.automation.mode == credit.automation.mode == "manual"


def test_current_planet49_is_not_merged_with_historical_egentic_brand():
    index = guide_index(settings())
    planet49, toleadoo, egentic = [
        index[domain] for domain in ["planet49.com", "toleadoo.com", "egentic.com"]
    ]
    assert len({guide.id for guide in [planet49, toleadoo, egentic]}) == 3
    assert planet49.coverage.effect == toleadoo.coverage.effect == "suppression"
    assert planet49.removal.destination == "info@de.planet49.com"
    assert egentic.review_status == "needs_research"
    assert egentic.automation.mode == "blocked"
    assert email_blocker(egentic, "info@egentic.com")


@pytest.mark.parametrize("domain", ["nextroll.com", "pubmatic.com", "rocketreach.co"])
def test_personal_platform_forms_cannot_be_emailed_automatically(domain):
    guide = guide_index(settings())[domain]
    assert guide.automation.mode in {"manual", "blocked"}
    assert guide.required_information.certainty == "not_fully_specified"
    assert guide.tested_outcome == "not_tested"
    for contact in guide.removal.alternatives:
        if "@" in contact:
            assert email_blocker(guide, contact)


def test_dnb_country_access_does_not_share_identity_document_requirements():
    routes = guide_index(settings())["dnb.com"].regional_routes
    austrian = next(route for route in routes if route.regions == ["AT"])
    german = next(route for route in routes
                  if route.regions == ["DE"] and route.coverage.effect == "access_then_review")
    assert "identity_document_copy" in austrian.required_information.fields
    assert "identity_document_copy" not in german.required_information.fields
    assert austrian.removal.destination != german.removal.destination
    assert austrian.automation.mode == german.automation.mode == "manual"


def test_registry_disclosures_are_public_metadata_not_eligibility():
    rows = registry_context(settings())
    assert sum(len(v) for v in rows.values()) > 550
    assert any(item["disclosures"] for records in rows.values() for item in records)
    assert all("email" not in item for records in rows.values() for item in records)


def test_guide_pages_require_login_and_show_sources_without_changing_cases(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'guides.db'}")
    config = Settings(
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        catalog_dir=ROOT / "catalog",
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
    )
    with TestClient(create_app(config, engine)) as client:
        assert client.get("/brokers?view=guides", follow_redirects=False).status_code == 303
        client.post("/login", data={"password": "test password"})
        response = client.get("/brokers?view=guides&q=AZ%20Direct")
        assert response.status_code == 200
        assert "Broker library" in response.text
        assert "Removal route" not in response.text
        assert "AZ Direct" in response.text and "Source evidence" not in response.text
        with Session(engine) as session:
            ids = {broker.domain: broker.id for broker in session.scalars(select(Broker))}
        guide = client.get(f"/cases/broker/{ids['az-direct.com']}?tab=details").text
        assert "Source evidence" in guide
        assert "No end-to-end test recorded" in guide
        assert "70 million" in guide
        draup = client.get("/brokers?q=Draup").text
        assert "Automatable email" not in draup
        assert "Human step needed" not in draup
        draup = client.get(f"/cases/broker/{ids['draup.com']}?tab=details").text
        assert "Automatable email" in draup
        assert "View exact email previews" in draup
        numberly = client.get(f"/cases/broker/{ids['numberly.com']}?tab=details").text
        assert "Reviewed email workflow" not in numberly
        assert "identity proof" in numberly
        with Session(engine) as session:
            broker = session.scalar(select(Broker).where(Broker.domain == "az-direct.com"))
            case = Case(broker_id=broker.id, state="done")
            session.add(case)
            session.commit()
            case_id = case.id
        detail = client.get(f"/cases/{case_id}?tab=details")
        assert detail.status_code == 200
        assert "Sources and removal instructions" in detail.text
        assert "Reviewed initial email workflow" in detail.text
        with Session(engine) as session:
            assert session.get(Case, case_id).state == "done"
