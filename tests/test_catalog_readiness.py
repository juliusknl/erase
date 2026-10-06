from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from erasure import catalog_readiness
from erasure.catalog_cli import audit
from erasure.config import Settings
from erasure.email_routes import routes
from erasure.knowledge import guides


@pytest.fixture
def settings():
    return Settings(catalog_dir=Path(__file__).parents[1] / "catalog")


def test_crif_individual_checklist_is_not_automatic_credit_erasure(settings):
    guide = next(g for g in guides(settings) if g.id == "crif-italy")
    assert guide.review_status == "instructions_reviewed"
    assert guide.coverage.effect == "access_then_review"
    assert guide.automation.mode == "manual"
    assert {"italian_tax_code", "identity_document_copy", "tax_code_card_copy", "signed_request"} <= set(guide.required_information.fields)
    assert "email" not in guide.required_information.fields
    assert "generating a form is not submitting a complete request" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert guide.id not in {w.get("guide_id") for w in catalog_readiness.resources(settings)["items"]}


@pytest.mark.parametrize("guide_id,destination", [
    ("aventura-post-marketing", "info@de.aventurapost.com"),
])
def test_partner_marketing_recipes_keep_retention_and_matching_explicit(settings, guide_id, destination):
    recipe, guide = next((r, g) for r, g in routes(settings).values() if r.guide_id == guide_id)
    assert recipe.destination == destination
    assert recipe.requires_matching_email
    assert recipe.effect == guide.coverage.effect == "suppression"
    assert set(recipe.fields) == {"full_name", "email", "other_emails"}
    assert "retained" in recipe.request.lower()
    assert "unrelated contracts" in recipe.request
    assert guide.required_information.certainty == "not_fully_specified"


@pytest.mark.parametrize("guide_id,field", [
    ("adagio", "existing_adagio_cookie_identifier"),
    ("kupona-retargeting", "relevant_browser"),
    ("mintegral-mobile", "device_identifier"),
])
def test_device_preferences_are_guided_suppression_not_generic_emails(settings, guide_id, field):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    assert guide.coverage.effect == "suppression"
    assert guide.automation.mode == "manual"
    assert field in guide.required_information.fields
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide_id)
    assert not win["requirements_complete"]


def test_adagio_access_template_is_not_mistaken_for_deletion(settings):
    guide = next(g for g in guides(settings) if g.id == "adagio")
    steps = " ".join(guide.removal.steps)
    assert "for access, not deletion" in steps
    assert "must actually be sent" in steps
    assert "do not enable tracking" in steps
    assert "400-day" in steps


def test_bundled_pilot_is_ready_without_claiming_complete_coverage(settings):
    report = catalog_readiness.readiness(settings)
    assert report["initial_routes_ready"], report["problems"]
    assert report["email_workflows"] == len({r.guide_id for r, _ in routes(settings).values()})
    assert report["email_workflows"] >= 44
    assert report["guided_forms"] >= 18
    assert "does not prove live completion" in report["limit"]


def test_missing_email_workflow_fails_pilot(settings, monkeypatch):
    monkeypatch.setattr(catalog_readiness, "routes", lambda _: {})
    report = catalog_readiness.readiness(settings)
    assert not report["initial_routes_ready"]
    assert any("Missing or stale email workflow" in p for p in report["problems"])


def test_documented_email_and_form_alternatives_count_as_one_guide(settings):
    report = catalog_readiness.readiness(settings)
    scope = yaml.safe_load((settings.catalog_dir / "mvp-cohort.yml").read_text())
    emails = set(scope["email_guides"])
    forms = {row["guide_id"] for row in scope["guided_forms"]}
    assert "amazinghiring" in emails & forms
    assert report["initial_routes_ready"], report["problems"]
    assert report["distinct_guides"] == len(emails | forms)
    assert report["distinct_guides"] < report["email_workflows"] + report["guided_forms"]


@pytest.mark.parametrize("route_list", ["email_guides", "guided_forms"])
def test_duplicate_within_a_route_list_still_fails(settings, tmp_path, monkeypatch, route_list):
    scope = yaml.safe_load((settings.catalog_dir / "mvp-cohort.yml").read_text())
    scope[route_list].append(deepcopy(scope[route_list][0]))
    (tmp_path / "mvp-cohort.yml").write_text(yaml.safe_dump(scope))
    records = guides(settings)
    email_routes = routes(settings)
    wins = catalog_readiness.resources(settings)
    monkeypatch.setattr(catalog_readiness, "guides", lambda _: records)
    monkeypatch.setattr(catalog_readiness, "routes", lambda _: email_routes)
    monkeypatch.setattr(catalog_readiness, "resources", lambda _: wins)
    report = catalog_readiness.readiness(Settings(catalog_dir=tmp_path))
    assert not report["initial_routes_ready"]
    assert "Pilot scope is empty or repeats a route" in report["problems"]


def test_mvp_gate_cannot_be_satisfied_by_a_small_green_pilot(settings, monkeypatch):
    real = catalog_readiness.coverage_audit
    report = real(settings.catalog_dir, guides(settings))
    assert report["pending_assessment"]
    monkeypatch.setattr(catalog_readiness, "readiness", lambda _: {
        "initial_routes_ready": True, "problems": [],
    })
    result = catalog_readiness.mvp_readiness(settings)
    assert not result["ready"]
    assert result["pending_assessment"] == len(report["pending_assessment"])
    assert result["unresolved_guides"] == len(report["unresolved_guides"])


def test_mvp_gate_requires_every_reviewed_automatic_decision_to_be_implemented(settings, monkeypatch):
    monkeypatch.setattr(catalog_readiness, "coverage_audit", lambda *args: {
        "inventory_records": 1, "assessed_records": 1, "pending_assessment": [],
        "unresolved_assessments": [], "unresolved_guides": [], "stale_guides": [],
        "integrity_problems": [],
    })
    monkeypatch.setattr(catalog_readiness, "readiness", lambda _: {
        "initial_routes_ready": True, "problems": [],
    })
    monkeypatch.setattr(catalog_readiness, "routes", lambda _: {})
    result = catalog_readiness.mvp_readiness(settings)
    assert not result["ready"]
    assert result["missing_email_workflows"]


def test_email_backlog_accounts_for_every_unimplemented_primary_email_guide(settings):
    executable = {r.guide_id for r, _ in routes(settings).values()}
    expected = {g.id for g in guides(settings) if g.removal.method == "email"} - executable
    report = audit(settings)
    backlog = report["execution"]["email_workflow_backlog"]
    assert {row["id"] for row in backlog} == expected
    numberly = next(row for row in backlog if row["id"] == "numberly")
    assert "identity_proof" in numberly["required_fields"]
    assert numberly["next_steps"]
    assert numberly["official_sources"]
    assert all(row["field_certainty"] for row in backlog)
    placeholders = (
        "Review the region, identifiers and request scope before submission.",
        "Identifiers and verification must be reviewed before using this regional route.",
    )
    assert not [row["id"] for row in backlog if row["remaining_review"] in placeholders]


@pytest.mark.parametrize("guide_id", ["branch-saas", "appsflyer-services", "adikteev-app-users"])
def test_app_processor_guides_require_the_relevant_controller(settings, guide_id):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    assert guide.review_status == "instructions_reviewed"
    assert guide.removal.method == "manual"
    assert guide.automation.mode == "manual"
    assert guide.required_information.certainty == "not_fully_specified"
    assert any("app" in field for field in guide.required_information.fields)
    assert guide_id not in {route.guide_id for route, _ in routes(settings).values()}


def test_device_quick_win_does_not_claim_global_deletion_or_automatic_sending(settings):
    guide = next(g for g in guides(settings) if g.id == "adjust-device")
    assert guide.coverage.effect == "suppression"
    assert guide.automation.mode == "manual"
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "adjust-device")
    assert item["fields"] == ["device_platform", "device_identifier"]
    assert not item["requirements_complete"]
    assert "Other devices" in item["scope"]
    assert "historical-data deletion" in item["scope"]


def test_attribits_requires_separate_matching_emails_not_a_generic_batch(settings):
    guide = next(g for g in guides(settings) if g.id == "attribits")
    assert guide.removal.method == "form"
    assert guide.automation.mode == "manual"
    assert "separately" in guide.removal.steps[0]
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "attribits")
    assert "every intended address" in item["steps"][-1]


def test_bdex_optout_is_not_promoted_to_european_deletion(settings):
    guide = next(g for g in guides(settings) if g.id == "bdex")
    assert guide.coverage.effect == "suppression"
    assert guide.automation.mode == "manual"
    assert "European fulfilment is unproven" in guide.coverage.excludes
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_dataxtrade_cannot_use_name_email_as_device_matching(settings):
    guide = next(g for g in guides(settings) if g.id == "dataxtrade-advertising")
    assert guide.required_information.fields == ["device_or_cookie_identifier"]
    assert guide.automation.mode == "manual"
    assert "HTTP" in guide.removal.steps[-1]
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


@pytest.mark.parametrize("guide_id,win_id", [
    ("acxiom-llc-international", "acxiom-international"),
    ("catalina-consumer", "catalina"),
])
def test_consumer_portals_preserve_controller_and_verification_limits(settings, guide_id, win_id):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == win_id)
    assert item["url"] == guide.removal.destination
    if guide_id == 'acxiom-llc-international':
        assert item['url'] == 'https://www.acxiom.com/privacy/us/consumer-instructions/'
        assert {'US', 'EEA', 'UK'} <= set(item['regions'])
        assert 'US Privacy Rights Portal' in item['steps'][0]
        assert 'International Requests' in item['steps'][0]
    else:
        assert "onetrust.com" in item["url"]
    assert not item["requirements_complete"]
    assert guide_id not in {r.guide_id for r, _ in routes(settings).values()}
    assert len(item["domains"]) == 1  # not blanket affiliate coverage


@pytest.mark.parametrize("guide_id,win_id", [
    ("trade-desk-platform", "trade-desk"),
    ("liveintent-services", "liveintent"),
    ("nextroll-services", "nextroll"),
])
def test_advertising_portals_keep_deletion_separate_from_optout(settings, guide_id, win_id):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == win_id)
    assert item["url"] == guide.removal.destination
    assert not item["requirements_complete"]
    assert guide.coverage.effect == "deletion_request"
    assert "opt-out" in " ".join(item["steps"])
    assert guide.tested_outcome == "not_tested"
    assert guide_id not in {r.guide_id for r, _ in routes(settings).values()}


def test_beeswax_requires_device_matching_not_generic_contact_details(settings):
    guide = next(g for g in guides(settings) if g.id == "beeswax-services")
    assert guide.required_information.fields == ["device_or_cookie_identifier"]
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_rocketreach_handoff_preserves_unverified_matching_boundary(settings):
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "rocketreach")
    assert item["fields"] == ["email"]
    assert not item["requirements_complete"]
    assert "subsequent screens were not accessed" in item["verification"]
    assert "rocketreach-professional" not in {r.guide_id for r, _ in routes(settings).values()}


def test_location_forms_preserve_device_scope_and_distinct_outcomes(settings):
    by_id = {g.id: g for g in guides(settings)}
    wins = {w["id"]: w for w in catalog_readiness.resources(settings)["items"]}
    assert by_id["foursquare"].coverage.effect == "suppression"
    assert "Not account deletion" in wins["foursquare"]["scope"]
    assert by_id["unacast"].identity.legal_name == "Gravy Analytics, Inc. dba Unacast"
    assert wins["unacast"]["domains"] == ["unacast.com", "gravyanalytics.com"]
    assert "Venntel" in wins["unacast"]["scope"]
    for key in ["unacast", "foursquare"]:
        assert "mobile_advertising_id" in wins[key]["fields"]
        assert by_id[key].automation.mode == "manual"
        assert key not in {r.guide_id for r, _ in routes(settings).values()}


def test_nordic_optout_does_not_erase_unlinked_device_data(settings):
    guide = next(g for g in guides(settings) if g.id == "nordic-data-resources")
    assert guide.coverage.effect == "suppression"
    assert "unlinked identifiers" in guide.coverage.excludes
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_signalhire_form_retains_profile_and_work_email_requirements(settings):
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "signalhire")
    assert item["fields"] == ["work_email", "profile_url"]
    assert not item["requirements_complete"]
    assert "not automatic account closure" in item["scope"]


def test_cuebiq_requires_device_matching_and_separate_optout(settings):
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "cuebiq")
    assert "mobile_advertising_id" in item["fields"]
    assert "Deletion alone does not prevent recollection" in " ".join(item["steps"])
    assert not item["requirements_complete"]
    assert "cuebiq-location" not in {r.guide_id for r, _ in routes(settings).values()}


def test_advanced_store_quick_win_is_browser_suppression_not_erasure(settings):
    guide = next(g for g in guides(settings) if g.id == "advanced-store-ad4mat")
    assert guide.coverage.effect == "suppression"
    assert "Historical erasure" in guide.coverage.excludes
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "advanced-store")
    assert "relevant_browser_context" in item["fields"]
    assert not item["requirements_complete"]


def test_dstillery_current_european_scope_does_not_guess_form_fields(settings):
    guide = next(g for g in guides(settings) if g.id == "dstillery-advertising")
    assert "EEA" in guide.relevance.regions
    assert guide.required_information.fields == []
    assert guide.required_information.certainty == "not_fully_specified"
    assert guide.automation.mode == "manual"
    assert guide.tested_outcome == "not_tested"


def test_innovid_preference_does_not_claim_customer_database_deletion(settings):
    guide = next(g for g in guides(settings) if g.id == "innovid-flashtalking")
    assert guide.coverage.effect == "suppression"
    assert "customer-controlled" in guide.coverage.excludes
    assert guide.required_information.certainty == "not_fully_specified"


def test_peopleconnect_keeps_suppression_record_and_non_us_permission_explicit(settings):
    guide = next(g for g in guides(settings) if g.id == "peopleconnect-suppression")
    assert guide.coverage.effect == "suppression"
    assert "Deleting it also removes its suppressions" in " ".join(guide.removal.steps)
    assert "outside the US" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    item = next(w for w in catalog_readiness.resources(settings)['items']
                if w.get('guide_id') == guide.id)
    assert item['regions'] == ['US']
    assert item['domains'] == guide.match_domains
    assert not item['requirements_complete']


def test_lexisnexis_uses_current_international_route_and_separate_us_identifiers(settings):
    guide = next(g for g in guides(settings) if g.id == "lexisnexis-risk-uk")
    assert guide.removal.destination == "https://reedelsevierinc3.my.site.com/webform/s/"
    assert guide.required_information.fields == []
    assert guide.regional_routes[0].regions == ["US"]
    assert "SSN_or_drivers_license_for_deletion" in guide.regional_routes[0].required_information.fields
    assert "DPO@lexisnexisrisk.com" not in guide.removal.alternatives
    assert guide.automation.mode == "manual"


def test_work_number_freeze_is_sensitive_manual_suppression_not_deletion(settings):
    guide = next(g for g in guides(settings) if g.id == "equifax-work-number")
    assert guide.coverage.effect == "suppression"
    assert "SSN" in guide.required_information.fields
    assert "not deletion" in " ".join(guide.removal.steps)
    assert "Remove Freeze" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_quantyoo_does_not_create_account_or_claim_all_partner_deletion(settings):
    guide = next(g for g in guides(settings) if g.id == "quantyoo-media")
    assert "do not create an account" in " ".join(guide.removal.steps)
    assert "Independent partner retention" in guide.coverage.excludes
    assert "privacy@quantyoo.de" in guide.removal.alternatives
    assert guide.automation.mode == "manual"


def test_cifas_access_is_not_a_completed_removal_quick_win(settings):
    guide = next(g for g in guides(settings) if g.id == "cifas-fraud-records")
    assert guide.coverage.effect == "access_then_review"
    assert "six_year_address_history" in guide.required_information.fields
    assert "first complain" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert not any(w.get("guide_id") == guide.id
                   for w in catalog_readiness.resources(settings)["items"])


def test_uk_marketing_routes_keep_joint_dataset_and_suppression_boundaries(settings):
    by_id = {g.id: g for g in guides(settings)}
    ml = by_id["market-location-uk"]
    info = by_id["information-118-uk"]
    offers = by_id["myoffers-uk"]
    assert "joint" in ml.coverage.includes
    assert "Independent 118" in ml.coverage.excludes
    assert "06325712" in info.identity.legal_name
    assert "duplicating" in " ".join(info.removal.steps)
    assert offers.removal.destination == "compliance@myoffersltd.co.uk"
    assert "suppression" in " ".join(offers.removal.steps)
    assert "DLG/PDV/DM Data" in offers.coverage.excludes
    assert info.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_datacentric_business_notice_does_not_close_consumer_research_gap(settings):
    guide = next(g for g in guides(settings) if g.id == "datacentric-es")
    assert "Accumin Intelligence" in guide.identity.legal_name
    assert "privacidad.datacentric@accumin.com" in guide.removal.alternatives
    assert guide.review_status == "needs_research"
    assert "consumer" in " ".join(guide.unknowns).lower()
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_advertising_handoffs_keep_identifier_and_controller_limits(settings):
    by_id = {g.id: g for g in guides(settings)}
    criteo = by_id["criteo"]
    across = by_id["33across"]
    assert "Criteo SA" in criteo.identity.legal_name
    assert "US audiences" in criteo.identity.legal_name
    assert any("2026/05" in e.url for e in criteo.evidence)
    assert "email_for_erasure_request" in across.required_information.fields
    assert "separate verified erasure" in across.coverage.includes
    assert "proof of no personal records" in across.relevance.note
    assert "WealthStage" in across.identity.brands
    for guide in (criteo, across):
        assert guide.review_status == "instructions_reviewed"
        assert guide.automation.mode == "manual"
        assert guide.tested_outcome == "not_tested"
        assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_pdl_handoff_keeps_optional_phone_and_unproven_outcome(settings):
    guide = next(g for g in guides(settings) if g.id == "people-data-labs")
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "people-data-labs")
    assert item["url"] == "https://privacy.peopledatalabs.com/"
    assert item["source"] == item["url"]
    assert guide.coverage.effect == "deletion_request"
    assert "phone" not in guide.required_information.fields
    assert "Consumer" in " ".join(guide.removal.steps)
    assert "not mandatory" in " ".join(guide.removal.steps)
    assert "delay setting is null" in " ".join(guide.unknowns)
    assert not item["requirements_complete"]
    assert guide.tested_outcome == "not_tested"


def test_measurement_handoffs_do_not_submit_server_cookies_or_sign_declarations(settings):
    by_id = {g.id: g for g in guides(settings)}
    magnite = by_id["magnite-advertising"]
    comscore = by_id["comscore-tagging"]
    assert "digital_identifier_for_deletion" in magnite.required_information.fields
    assert magnite.coverage.effect == "suppression"
    assert "Never send all browser cookies" in " ".join(magnite.removal.steps)
    assert "Comscore B.V." in comscore.identity.legal_name
    assert "sole_user_device_authority_declaration" in comscore.required_information.fields
    assert "shared device" in " ".join(comscore.removal.steps)
    assert "panel" in comscore.coverage.excludes
    for guide in (magnite, comscore):
        assert guide.automation.mode == "manual"
        assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
        assert guide.tested_outcome == "not_tested"


def test_merkle_us_products_are_not_a_blanket_dentsu_removal(settings):
    by_id = {g.id: g for g in guides(settings)}
    us = by_id["merkle-us-data-products"]
    dentsu = by_id["dentsu-identity-product"]
    assert us.relevance.regions == ["US"]
    assert "US address" in " ".join(us.removal.steps)
    assert "Separate UK products" in us.coverage.excludes
    assert "later" in dentsu.coverage.excludes
    assert us.id not in {r.guide_id for r, _ in routes(settings).values()}
    audit_result = catalog_readiness.coverage_audit(settings.catalog_dir, guides(settings))
    assert "community:merkleinc" in audit_result["unresolved_assessments"]


def test_identity_service_routes_require_personal_review(settings):
    by_id = {g.id: g for g in guides(settings)}
    mm = by_id["maxmind-services"]
    ekata = by_id["mastercard-ekata-identity"]
    fideo = by_id["fideo-identity"]
    assert "Repeat separately" in " ".join(mm.removal.steps)
    assert "IP" not in mm.required_information.fields
    assert ekata.removal.destination == "ekataprivacyanddataprotection@mastercard.com"
    assert "Mastercard Europe SA" in ekata.identity.legal_name
    assert "privacysupport@ekata.com" not in ekata.removal.alternatives
    assert fideo.removal.destination == "privacy@fideo.ai"
    for guide in (mm, ekata, fideo):
        assert guide.relevance.category == "identity_risk"
        assert guide.automation.mode == "manual"
        assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
        assert guide.tested_outcome == "not_tested"


def test_public_record_forms_do_not_claim_cross_brand_or_automatic_matching(settings):
    by_id = {g.id: g for g in guides(settings)}
    for guide_id in ("infotracer-records", "recordsfinder-records",
                     "kids-live-safe-records", "quick-public-records"):
        guide = by_id[guide_id]
        assert guide.automation.mode == "manual"
        assert guide.required_information.certainty == "not_fully_specified"
        assert guide.tested_outcome == "not_tested"
        assert len(guide.match_domains) == 1
        assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    for guide_id in ("kids-live-safe-records", "quick-public-records"):
        guide = by_id[guide_id]
        assert "age" in guide.required_information.fields
        assert "postal_code" in guide.required_information.fields
        assert "Customer ID" in guide.required_information.verification
        assert guide.coverage.effect == "suppression"
    assert "Quick Public Records" in by_id["kids-live-safe-records"].coverage.excludes
    assert "Kids Live Safe" in by_id["quick-public-records"].coverage.excludes
    assert "dynamic" in by_id["infotracer-records"].automation.reason
    radaris = by_id["radaris-domain-transfer"]
    assert radaris.review_status == "needs_research"
    assert radaris.automation.mode == "blocked"
    assert radaris.coverage.effect == "needs_review"
    assert "not proof" in radaris.relevance.note


def test_sensitive_german_access_preserves_optional_ids_and_exact_controller(settings):
    by_id = {g.id: g for g in guides(settings)}
    email_guides = {r.guide_id for r, _ in routes(settings).values()}
    ids = ["demda-tenant-records", "ihd-business-credit",
           "besurance-his-insurance", "intrum-information-services-de"]
    for guide_id in ids:
        guide = by_id[guide_id]
        assert guide.coverage.effect == "access_then_review"
        assert guide.automation.mode == "manual"
        assert guide_id not in email_guides
        assert "identity_document" not in guide.required_information.fields
    for guide_id in ("demda-tenant-records", "besurance-his-insurance"):
        assert "date_of_birth" in by_id[guide_id].required_information.fields
    his = by_id["besurance-his-insurance"]
    assert "email" not in his.required_information.fields
    assert "optional" in his.required_information.verification
    intrum = by_id["intrum-information-services-de"]
    assert "exact_company" in intrum.required_information.fields
    assert "case reference is optional" in " ".join(intrum.removal.steps)
    assert "Hanseatische" in intrum.coverage.excludes


def test_marketing_forms_preserve_suppression_matching_and_residence_limits(settings):
    by_id = {g.id: g for g in guides(settings)}
    email_guides = {r.guide_id for r, _ in routes(settings).values()}
    belardi = by_id["belardiwong-regional-request"]
    assert {"phone", "postal_address", "country"} <= set(belardi.required_information.fields)
    assert "only website data" in " ".join(belardi.removal.steps)
    crosspixel = by_id["crosspixel-browser-preferences"]
    assert crosspixel.coverage.effect == "suppression"
    assert crosspixel.removal.destination == "https://privacy.crsspxl.com/"
    dataline = by_id["dataline-consumer-marketing"]
    assert dataline.coverage.effect == "suppression"
    assert "historical deletion rather than suppression" in " ".join(dataline.removal.steps)
    datafy = by_id["datafy-device-location"]
    assert "mobile_advertising_id" in datafy.required_information.fields
    assert "conflict" in datafy.required_information.verification
    assert "never fabricate" in " ".join(datafy.removal.steps)
    civis = by_id["civis-analytics-consumer"]
    assert "not to submit rights requests" in " ".join(civis.removal.steps)
    assert "non-US eligibility untested" in civis.required_information.verification
    dataman = by_id["dataman-consumer-marketing"]
    assert "postal_address" in dataman.required_information.fields
    assert "email" not in dataman.required_information.fields
    agr = by_id["agr-consumer-marketing"]
    assert "phone" in agr.required_information.fields
    assert agr.coverage.effect == "suppression"
    datasys = by_id["datasys-consumer-records"]
    assert "initial action-selection step" in datasys.required_information.verification
    cybba = by_id["cybba-marketing-services"]
    assert "full_name" not in cybba.required_information.fields
    assert cybba.removal.destination.endswith("81d37a05-cc75-4c12-924c-56c5c45bf269")
    for guide in (dataline, datafy, civis, dataman, agr, datasys, cybba, belardi, crosspixel):
        assert guide.required_information.certainty == "not_fully_specified"
        assert guide.id not in email_guides
        assert guide.tested_outcome == "not_tested"


def test_consumer_platform_actions_preserve_service_and_account_boundaries(settings):
    by_id = {g.id: g for g in guides(settings)}
    email_guides = {r.guide_id for r, _ in routes(settings).values()}
    unity = by_id["unity-player-advertising"]
    assert "unredeemed-reward deletion" in " ".join(unity.removal.steps)
    assert "actual ad" in " ".join(unity.removal.steps)
    assert "Developer-controlled" in unity.coverage.excludes
    skimlinks = by_id["skimlinks-commerce-cookies"]
    assert skimlinks.coverage.effect == "suppression"
    assert skimlinks.removal.destination != "https://optout.skimlinks.com/"
    assert "independent affiliate-network" in skimlinks.coverage.excludes
    roku = by_id["roku-europe-consumer"]
    assert roku.identity.legal_name == "Roku International BV"
    assert "HTTP 403" in roku.required_information.verification
    assert "Frndly TV" in roku.coverage.excludes
    for guide in (unity, skimlinks, roku):
        assert guide.automation.mode == "manual"
        assert guide.tested_outcome == "not_tested"
        assert guide.id not in email_guides


def test_advertising_context_keeps_optional_ids_and_preferences_distinct(settings):
    by_id = {g.id: g for g in guides(settings)}
    email_guides = {r.guide_id for r, _ in routes(settings).values()}
    ids = ["miq-advertising-context", "knorex-advertising-context",
           "iqm-advertising-identifiers", "yoc-visx-browser"]
    for guide_id in ids:
        guide = by_id[guide_id]
        assert guide.automation.mode == "manual"
        assert guide.required_information.certainty == "not_fully_specified"
        assert guide.tested_outcome == "not_tested"
        assert guide_id not in email_guides
    iqm = by_id["iqm-advertising-identifiers"]
    assert "Cookie/MAIDs optional" in " ".join(iqm.removal.steps)
    assert "account-loss warning" in " ".join(iqm.removal.steps)
    assert iqm.coverage.effect == "deletion_request"
    yoc = by_id["yoc-visx-browser"]
    assert yoc.coverage.effect == "suppression"
    assert yoc.removal.destination == "https://ads-privacy.yoc.com/dsa.html"
    assert "not proof of erasure" in " ".join(yoc.removal.steps)
    for guide_id in ids[:2]:
        assert by_id[guide_id].coverage.effect == "access_then_review"


def test_german_specialist_routes_keep_dates_cookies_and_credit_context(settings):
    by_id = {g.id: g for g in guides(settings)}
    geno = by_id["geno-media-consumer-marketing"]
    assert geno.removal.destination == "info@geno-media-circle.de"
    assert {"request_date", "postal_address"} <= set(geno.required_information.fields)
    assert "AUSÜBUNG DER RECHTE" in " ".join(geno.removal.steps)
    qdivision = by_id["qdivision-browser-advertising"]
    assert qdivision.required_information.fields == ["actual_browser_context"]
    assert qdivision.coverage.effect == "suppression"
    assert "before withdrawal" in " ".join(qdivision.removal.steps)
    cs = by_id["cs-connect-business-credit"]
    assert cs.identity.parent == "SCHUFA Holding AG"
    assert cs.coverage.effect == "access_then_review"
    assert "consumer" in cs.coverage.excludes
    windaten = by_id["windaten-marketing-information"]
    assert windaten.coverage.effect == "access_then_review"
    for guide in (geno, qdivision, cs, windaten):
        assert guide.automation.mode == "manual"
        assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    rbi, guide = routes(settings)["rbinformationservices.de"]
    assert rbi.requires_matching_email
    assert rbi.destination == guide.removal.destination
    assert "postal_address" not in rbi.fields


def test_liveramp_global_preferences_do_not_replace_regional_or_measurement_rights(settings):
    guide = next(g for g in guides(settings) if g.id == "liveramp-global-controls")
    assert guide.coverage.effect == "suppression"
    assert "not separate companies" in " ".join(guide.removal.steps)
    assert "Data Plus Math" in guide.coverage.excludes
    assert guide.match_domains == ["liveramp.com"]
    report = catalog_readiness.coverage_audit(settings.catalog_dir, guides(settings))
    assert "community:dataplusmath" in report["unresolved_assessments"]


def test_experian_uk_marketing_keeps_credit_and_browser_context_separate(settings):
    guide = next(g for g in guides(settings) if g.id == "experian-uk-marketing")
    assert guide.identity.legal_name == "Experian Limited (company 00653331)"
    assert guide.coverage.effect == "suppression"
    assert "Credit-reference records" in guide.coverage.excludes
    assert "IP address" in " ".join(guide.removal.steps)
    item = next(w for w in catalog_readiness.resources(settings)["items"]
                if w["id"] == "experian-uk-marketing")
    assert "postcode" in item["fields"]
    assert "email" not in item["fields"]
    assert not item["requirements_complete"]


def test_platform_matching_and_doubleverify_contact_are_product_specific(settings):
    by_id = {g.id: g for g in guides(settings)}
    dv = by_id["doubleverify-solutions"]
    assert "privacy@doubleverify.com" in dv.removal.alternatives
    assert "privacy-policy@doubleverify.com" not in dv.removal.alternatives
    for guide_id in ["freewheel-platform", "doubleverify-solutions", "innovid-flashtalking"]:
        assert by_id[guide_id].automation.mode == "manual"
        assert guide_id not in {r.guide_id for r, _ in routes(settings).values()}


def test_alikeaudience_uses_published_portal_without_assuming_sender_ownership(settings):
    guide = next(g for g in guides(settings) if g.id == "alikeaudience-route-review")
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == "alikeaudience")
    assert item["url"] == "https://privacy-optout.alikeaudience.com/"
    assert guide.coverage.effect == "suppression"
    assert not item["requirements_complete"]
    assert "not an unrelated dedicated inbox" in " ".join(guide.removal.steps)
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_identity_products_keep_controller_and_sensitive_matching_boundaries(settings):
    by_id = {g.id: g for g in guides(settings)}
    appscience = by_id["appscience-platform"]
    assert appscience.removal.destination == "privacy@appscience.inc"
    assert by_id["sabio"].removal.destination == "privacy@sabio.inc"
    assert set(appscience.match_domains).isdisjoint(by_id["sabio"].match_domains)
    assert "last_four_SSN" in by_id["aristotle-political-consumer"].required_information.fields
    assert "do not invent" in " ".join(by_id["aristotle-political-consumer"].removal.steps)
    assert by_id["babel-street-intelligence"].coverage.effect == "access_then_review"
    automatic = {r.guide_id for r, _ in routes(settings).values()}
    for guide_id in ["appscience-platform", "aristotle-political-consumer", "babel-street-intelligence"]:
        assert by_id[guide_id].automation.mode == "manual"
        assert guide_id not in automatic


def test_professional_routes_do_not_confuse_unsubscribe_or_job_applications(settings):
    by_id = {g.id: g for g in guides(settings)}
    recipes = {r.guide_id: r for r, _ in routes(settings).values()}
    melissa = by_id["melissa-consumer-databases"]
    assert melissa.removal.destination == "ConsumerRequest@melissa.com"
    assert "postal_address" in recipes[melissa.id].fields
    assert "Do not invent US details" in " ".join(melissa.removal.steps)
    hireez = by_id["hireez-talent-database"]
    assert hireez.removal.destination == "https://app.hireez.com/ownyourdata"
    assert hireez.id not in recipes
    assert 'candidate profile' in ' '.join(hireez.removal.steps)
    assert 'datarequests@hireez.com' in hireez.removal.alternatives
    pitchbook = by_id["pitchbook-professionals"]
    assert pitchbook.removal.destination == "https://www.morningstar.com/request-data"
    assert pitchbook.id not in recipes
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == "pitchbook")
    assert not item["requirements_complete"]
    assert pitchbook.tested_outcome == "not_tested"


def test_advertising_routes_keep_email_device_and_residency_limits(settings):
    by_id = {g.id: g for g in guides(settings)}
    recipes = {r.guide_id: r for r, _ in routes(settings).values()}
    datonics = by_id['datonics-advertising']
    assert datonics.id not in recipes
    assert datonics.removal.method == 'form'
    assert "sender's hash" in ' '.join(datonics.removal.steps)
    assert 'postal_address' not in datonics.required_information.fields
    assert by_id["cadent-household-platform"].relevance.regions == ["US"]
    for guide_id in ["media-net-platform", "mobilefuse-platform", "cadent-household-platform"]:
        assert guide_id not in recipes
        assert by_id[guide_id].tested_outcome == "not_tested"
    assert "do-not-sell" in " ".join(by_id["media-net-platform"].removal.steps)
    mf = by_id["mobilefuse-platform"]
    assert mf.required_information.fields == ["email"]
    assert "delay setting is null" in " ".join(mf.removal.steps)
    assert "compliance@mobilefuse.com" in mf.removal.alternatives
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == "datonics")
    assert "personal_accuracy_declaration" in win["fields"]
    assert not win["requirements_complete"]


def test_shared_brand_portals_and_professional_email_preserve_product_scope(settings):
    by_id = {g.id: g for g in guides(settings)}
    recipes = {r.guide_id: r for r, _ in routes(settings).values()}
    retention = by_id["retention-rb2b-network"]
    assert set(retention.match_domains) == {"retention.com", "rb2b.com"}
    assert retention.coverage.effect == "suppression"
    assert "independent customers" in " ".join(retention.removal.steps)
    enformion = by_id["enformion-data-products"]
    assert set(enformion.match_domains) == {"enformion.com", "tracers.com", "endato.com"}
    assert "24 hours" in " ".join(enformion.removal.steps)
    assert "not a submitted deletion request" in " ".join(enformion.removal.steps)
    assert enformion.id not in recipes
    assert not enformion.required_information.certainty == "documented"
    cbi = recipes["cbinsights-professional"]
    assert {"work_email", "employer"} <= set(cbi.fields)
    assert "postal_address" not in cbi.fields
    assert "entire company profile" in cbi.request


def test_member_marketing_and_directory_proof_are_not_automatic_account_closure(settings):
    by_id = {g.id: g for g in guides(settings)}
    recipes = {r.guide_id: r for r, _ in routes(settings).values()}
    for guide_id in ["payback-member-privacy", "deutschlandcard-member-privacy"]:
        assert guide_id not in recipes
        assert by_id[guide_id].coverage.effect == "suppression"
        assert by_id[guide_id].automation.mode == "manual"
    # Member-only settings are documented without cluttering the general broker checklist.
    wins = catalog_readiness.resources(settings)["items"]
    assert not {"payback-member-privacy", "deutschlandcard-member-privacy"} & {
        w.get("guide_id") for w in wins
    }
    dtm = by_id["dtm-private-directory"]
    assert "identity_proof_or_provider_authentication" in dtm.required_information.fields
    assert "telephone provider" in " ".join(dtm.removal.steps)
    assert dtm.id not in recipes
    burda = recipes["burda-direkt-marketing"]
    assert "postal_address" in burda.fields
    assert burda.effect == "suppression"
    assert "Do not cancel any paid subscriptions" in burda.request


def test_sovrn_email_and_gumgum_browser_preserve_identifier_scope(settings):
    by_id = {g.id: g for g in guides(settings)}
    recipes = {r.guide_id: r for r, _ in routes(settings).values()}
    sovrn = recipes["sovrn-advertising"]
    assert sovrn.requires_matching_email
    assert "hashed forms" in sovrn.request
    assert "not closure of any publisher account" in sovrn.request
    assert "postal_address" not in sovrn.fields
    gumgum = by_id["gumgum-advertising"]
    assert gumgum.id not in recipes
    assert gumgum.coverage.effect == "suppression"
    assert "California residents only" in " ".join(gumgum.removal.steps)
    assert "Clearing cookies" in " ".join(gumgum.removal.steps)


def test_nielsen_form_has_official_provenance_without_blanket_product_coverage(settings):
    guide = next(g for g in guides(settings) if g.id == "nielsen-marketing-cloud")
    assert "Nielsen Media Germany GmbH" in guide.identity.legal_name
    assert "Nielsen Media Research Limited" in guide.identity.legal_name
    assert guide.removal.method == "form"
    assert guide.removal.destination.endswith("85c00ce0-85a5-4c1c-bb29-2967224c1b83")
    assert "NielsenIQ" in guide.coverage.excludes
    assert guide.required_information.fields == ["full_name", "email", "country", "requested_right"]
    assert "US citizens only" in guide.required_information.verification
    assert "do not invent a US state" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert any("official_rights_form_link" in e.supports for e in guide.evidence)
    assert not any("provenance was not recovered" in unknown for unknown in guide.unknowns)
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert not win["requirements_complete"]


def test_neustar_european_portal_is_not_the_us_credit_route(settings):
    guide = next(g for g in guides(settings) if g.id == "neustar-european-privacy")
    assert guide.match_domains == ["home.neustar"]
    assert guide.removal.destination == "https://privacychoices.home.neustar/"
    assert "privacy@transunion.com" in guide.removal.alternatives
    assert "conditional" in guide.automation.reason
    assert "EEA IP address" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert not win["requirements_complete"]


def test_saz_suppression_keeps_postal_reply_and_controller_boundaries(settings):
    guide = next(g for g in guides(settings) if g.id == "saz-swiss-addresses")
    assert guide.coverage.effect == "suppression"
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert "postal_address" in guide.required_information.fields
    assert "email" not in guide.required_information.fields
    assert "exclusively by post" in " ".join(guide.removal.steps)
    assert "Germany, Austria and Switzerland" in " ".join(guide.removal.steps)
    assert "German SAZ Services GmbH" in guide.coverage.excludes
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert win["requirements_complete"]
    assert win["url"] == "https://www.saz.com/de/datenschutz"


def test_clickagy_quick_win_uses_actual_browser_without_extra_personal_identifiers(settings):
    guide = next(g for g in guides(settings) if g.id == "clickagy-browser")
    assert guide.required_information.fields == ["relevant_browser", "california_residence_answer"]
    assert guide.required_information.certainty == "documented"
    assert guide.tested_outcome == "not_tested"
    assert "before deletion" in " ".join(guide.removal.steps)
    assert "every relevant browser" in " ".join(guide.removal.steps)
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert win["requirements_complete"]
    assert win["url"] == "https://www.clickagy.com/privacy-center/delete/"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_nexxen_uses_replacement_form_without_promoting_employee_identity_fields(settings):
    guide = next(g for g in guides(settings) if g.id == "nexxen-advertising")
    assert guide.review_status == "instructions_reviewed"
    assert guide.automation.mode == "manual"
    assert guide.removal.alternatives == [
        "https://privacyportal.onetrust.com/webform/76394770-3c6c-4d28-a57b-18817b0a8e3f/"
        "2bbd01a5-983c-440b-9fd5-fd341c9326a1"
    ]
    assert "national_id" not in guide.required_information.fields
    assert "full_name" not in guide.required_information.fields
    assert "personal_affirmation" in guide.required_information.fields
    assert "authentication cookies" in " ".join(guide.removal.steps)
    assert "conditional employee-access" in " ".join(guide.removal.steps)
    win = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert not win["requirements_complete"]
    assert guide.tested_outcome == "not_tested"


@pytest.mark.parametrize("guide_id", ["bazaarvoice-network", "choozle-platform-preferences"])
def test_multi_party_preferences_are_not_generic_email_or_single_completion_shortcuts(settings, guide_id):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    assert guide.removal.method == "manual"
    assert guide.coverage.effect == "suppression"
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert guide.id not in {w["id"] for w in catalog_readiness.resources(settings)["items"]}


@pytest.mark.parametrize("guide_id", [
    "hybrid-theory-platform", "delta-projects-platform", "emerse-advertising", "adux-advertising",
])
def test_device_adtech_routes_do_not_imply_email_matching_or_live_verification(settings, guide_id):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    assert guide.automation.mode == "manual"
    assert guide.tested_outcome == "not_tested"
    assert guide.required_information.certainty == "not_fully_specified"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert "browser" in " ".join(guide.removal.steps).lower()
    assert guide.id not in {w["id"] for w in catalog_readiness.resources(settings)["items"]}
    if guide_id == "emerse-advertising":
        assert guide.coverage.effect == "suppression"
    else:
        assert "matching_identifier" in guide.required_information.fields


def test_german_sponsor_recipes_minimize_disclosure_and_do_not_invent_participation(settings):
    by_id = {r.guide_id: r for r, _ in routes(settings).values()}
    inside = by_id["inside-lead-consumer"]
    assert "postal_address" in inside.fields
    assert "do not assert" in inside.request
    assert "end that participation" in inside.request
    for guide_id in ["leadspot-consumer-marketing", "smash-sponsor-marketing", "inside-lead-consumer", "all-travel-sponsor-marketing",
                     "best-relations-sponsor-marketing"]:
        recipe = by_id[guide_id]
        assert recipe.requires_matching_email
        assert "sponsor" in recipe.request.lower()
        assert "phone" not in recipe.fields
        if guide_id != "inside-lead-consumer":
            assert "postal_address" not in recipe.fields
    assert "blueleads-newsletter" not in by_id


def test_catalist_retains_suppression_and_personal_declaration_boundaries(settings):
    guide = next(g for g in guides(settings) if g.id == "catalist-political")
    assert guide.coverage.effect == "suppression"
    assert "perjury" in guide.required_information.verification
    assert "birthdate" in guide.required_information.fields
    assert "directly from you" in " ".join(guide.removal.steps)
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_careerbuilder_does_not_turn_account_deletion_into_universal_quick_win(settings):
    guide = next(g for g in guides(settings) if g.id == "careerbuilder-job-board")
    assert guide.match_domains == ["careerbuilder.com"]
    assert guide.removal.destination == "https://www.careerbuilder.com/privacy/"
    assert "postal_address" not in guide.required_information.fields
    assert "unverified requests are not processed" in " ".join(guide.removal.steps)
    assert "Independent employer" in guide.coverage.excludes
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    assert guide.id not in {w["id"] for w in catalog_readiness.resources(settings)["items"]}


def test_costar_initial_email_keeps_brand_and_identity_boundaries(settings):
    recipe, guide = routes(settings)["costar.com"]
    assert recipe.destination == "support@costar.com"
    assert "all CoStar Group brands" in recipe.request
    assert "close a customer account" in recipe.request
    assert "postal_address" not in recipe.fields
    assert guide.automation.mode == "manual"
    assert "one request type" in " ".join(guide.removal.steps)


def test_blackbaud_sensitive_fields_remain_conditional_and_manual(settings):
    guide = next(g for g in guides(settings) if g.id == "blackbaud-target-analytics")
    assert guide.relevance.regions == ["United States"]
    assert guide.automation.mode == "manual"
    assert "conditional" in guide.required_information.verification
    assert "Social Security" in " ".join(guide.removal.steps)
    assert "national_id" not in guide.required_information.fields
    assert "JustGiving" in guide.coverage.excludes
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_mediawallah_and_bridg_do_not_invent_european_email_coverage(settings):
    by_id = {g.id: g for g in guides(settings)}
    recipes = {r.guide_id for r, _ in routes(settings).values()}
    for guide_id in ["mediawallah-identity", "bridg-shopper-data"]:
        guide = by_id[guide_id]
        assert guide.automation.mode == "manual"
        assert guide.required_information.certainty == "not_fully_specified"
        assert guide_id not in recipes
        assert "European" in guide.coverage.excludes
    assert by_id["bridg-shopper-data"].identity.legal_name == "DB Sub, LLC"
    assert "client-directed" in by_id["bridg-shopper-data"].coverage.includes
    assert "website-specific" in by_id["mediawallah-identity"].automation.reason


def test_inmobi_declaration_is_not_a_generic_automatic_email(settings):
    guide = next(g for g in guides(settings) if g.id == "inmobi-advertising")
    assert {"signed_affidavit", "identifier_screenshots"} <= set(guide.required_information.fields)
    assert "never sign an inaccurate statement" in " ".join(guide.removal.steps)
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_publisher_routes_preserve_accounts_and_require_context_where_needed(settings):
    guide = next(g for g in guides(settings) if g.id == 'mediavine-reader-advertising')
    assert 'mediavine.com' not in routes(settings)
    assert guide.removal.destination == 'https://privacy.mediavine.com/'
    assert 'relationship' in guide.required_information.fields
    assert 'not a universal browser-data deletion request' in ' '.join(guide.removal.steps)
    ezoic = next(g for g in guides(settings) if g.id == "ezoic-publisher-context")
    assert "publisher_site_or_direct_relationship" in ezoic.required_information.fields
    assert ezoic.coverage.effect == "needs_review"
    assert "ezoic.com" not in routes(settings)


@pytest.mark.parametrize("domain,guide_id", [
    ("listkit.io", "listkit-professional"),
    ("recruitbot.com", "recruitbot-candidates"),
])
def test_new_candidate_routes_match_existing_emails_without_closing_accounts(settings, domain, guide_id):
    route, guide = routes(settings)[domain]
    assert guide.id == guide_id
    assert route.requires_matching_email
    assert route.fields == ["full_name", "email", "other_emails"]
    assert route.effect == "deletion_request"
    assert "account" in route.request
    assert guide.required_information.certainty == "not_fully_specified"
    assert guide.tested_outcome == "not_tested"


def test_lightcast_form_keeps_per_email_matching_and_no_generic_email(settings):
    guide = next(g for g in guides(settings) if g.id == "lightcast-professional")
    assert guide.match_domains == ["lightcast.io"]
    assert "one form per matching email" in " ".join(guide.removal.steps)
    assert "Rhetorik" in guide.coverage.includes
    assert "CAPTCHA" in guide.required_information.verification
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert not item["requirements_complete"]


def test_foundry_uses_current_recipient_and_meltwater_requires_product_context(settings):
    route, guide = routes(settings)["foundryco.com"]
    assert route.destination == "dataprotection@foundryco.com"
    assert "formerly IDG Communications" in guide.identity.legal_name
    assert "Do not cancel" in route.request
    meltwater = next(g for g in guides(settings) if g.id == "meltwater-product-context")
    assert "product_or_record_context" in meltwater.required_information.fields
    assert "journalists@meltwater.com" in meltwater.removal.alternatives
    assert "12 April 2018" in " ".join(meltwater.removal.steps)
    assert "meltwater.com" not in routes(settings)


def test_intent_forms_keep_mobile_confirmations_and_regional_scope(settings):
    by_id = {g.id: g for g in guides(settings)}
    blackpearl = by_id["blackpearl-intent-data"]
    assert "personal_confirmation" in blackpearl.required_information.fields
    modigie = by_id["modigie-professional-validation"]
    assert "mobile_phone" in modigie.required_information.fields
    assert "account-loss warning" in " ".join(modigie.removal.steps)
    redidata = by_id["redidata-marketing-lists"]
    assert "European product coverage must be confirmed" in redidata.coverage.includes
    mailing = by_id["complete-mailing-lists"]
    assert "completemedicallists.com" not in mailing.match_domains
    assert "not proof of an individual's absence" in mailing.relevance.note
    recipes = {r.guide_id for r, _ in routes(settings).values()}
    assert not {blackpearl.id, modigie.id, redidata.id, mailing.id} & recipes


def test_biscred_and_prospectbase_email_scope_is_not_group_account_closure(settings):
    available = routes(settings)
    biscred, guide = available["biscred.com"]
    assert biscred.destination == "privacy@biscred.com"
    assert guide.identity.legal_name == "Bisnow, LLC"
    assert "not a request to cancel" in biscred.request
    prospect, guide = available["prospectbase.com"]
    assert "15492457" in guide.identity.legal_name
    assert "ProspectBase UK Limited" in prospect.request
    assert "Ireland" in guide.coverage.excludes
    assert {"flashintel.ai", "flashlabs.ai", "heartbeat.ai"}.isdisjoint(available)


def test_research_and_expert_routes_keep_declarations_and_source_boundaries(settings):
    by_id = {g.id: g for g in guides(settings)}
    power = by_id["jdpower-consumer-research"]
    assert "personal_declaration" in power.required_information.fields
    assert "must not accept it for you" in " ".join(power.removal.steps)
    infutor = by_id["infutor-lead-intelligence"]
    assert infutor.match_domains == ["infutor.com"]
    assert "Lead Intelligence" in infutor.identity.legal_name
    assert "European applicability is not established" in " ".join(infutor.removal.steps)
    monocl = by_id["monocl-expert-profiles"]
    assert monocl.match_domains == ["monocl.com"]
    assert monocl.coverage.effect == "access_then_review"
    assert "not an independent legal conclusion" in " ".join(monocl.removal.steps)
    recipes = {r.guide_id for r, _ in routes(settings).values()}
    assert not {power.id, infutor.id, monocl.id} & recipes


def test_specialist_forms_preserve_residence_and_sensitive_scope(settings):
    by_id = {g.id: g for g in guides(settings)}
    iqvia = by_id["iqvia-digital-advertising"]
    assert iqvia.match_domains == ["iqviadigital.com"]
    assert "postal_address" in iqvia.required_information.fields
    assert "Phone is optional" in " ".join(iqvia.removal.steps)
    assert "withdrawal from a study" in " ".join(iqvia.removal.steps)
    i360 = by_id["i360-consumer-political"]
    assert "supported_us_state" in i360.required_information.fields
    assert "never invent a US state" in " ".join(i360.removal.steps)
    assert "not the ordinary deletion branch" in " ".join(i360.removal.steps)
    lightbox = by_id["lightbox-property-professional"]
    assert "California" in lightbox.coverage.includes
    assert "not field instructions" in " ".join(lightbox.removal.steps)
    recipes = {r.guide_id for r, _ in routes(settings).values()}
    assert not {iqvia.id, i360.id, lightbox.id} & recipes


def test_nativo_and_tradedoubler_keep_current_controller_and_manual_scope(settings):
    by_id = {g.id: g for g in guides(settings)}
    nativo = by_id["nativo-advertising"]
    assert nativo.match_domains == ["nativo.com"]
    assert nativo.coverage.effect == "suppression"
    assert "Life360/Tile/Jiobit" in nativo.coverage.excludes
    assert "privacy-nativo@life360.com" in nativo.removal.alternatives
    tradedoubler = by_id["tradedoubler-nyorda"]
    assert "Nyorda AB" in tradedoubler.identity.legal_name
    assert "signup_country_if_applicable" in tradedoubler.required_information.fields
    recipes = {r.guide_id for r, _ in routes(settings).values()}
    assert not {nativo.id, tradedoubler.id} & recipes


def test_pgm_general_suppression_does_not_claim_us_deletion_eligibility(settings):
    route, guide = routes(settings)["porchgroupmedia.com"]
    assert route.effect == guide.coverage.effect == "suppression"
    assert "postal_address" in route.fields
    assert "not asserting US residence" in route.request
    assert "limited to its listed US states" in " ".join(guide.removal.steps)
    assert guide.required_information.certainty == "not_fully_specified"
    assert guide.identity.legal_name.startswith("DataMentors")


def test_altair_manual_only_form_never_becomes_an_automatic_email_route(settings):
    guide = next(g for g in guides(settings) if g.id == "altair-consumer-marketing")
    assert "manual submissions only" in " ".join(guide.removal.steps)
    assert "never invent a US address" in " ".join(guide.removal.steps)
    assert "personal_declarations" in guide.required_information.fields
    assert "access/household" in guide.required_information.verification
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


@pytest.mark.parametrize("guide_id,entity", [
    ("exact-data-consumer-base", "Consumer Base"),
    ("donorbase-marketing", "DonorBase"),
])
def test_named_data_axle_affiliates_require_postal_approval_and_specific_scope(settings, guide_id, entity):
    by_id = {r.guide_id: (r, g) for r, g in routes(settings).values()}
    route, guide = by_id[guide_id]
    assert entity in route.request
    assert "postal_address" in route.fields
    assert "DE" in route.countries and "NO" not in route.countries
    assert route.destination == "privacyteam@data-axle.com"
    assert guide.automation.mode == "manual"
    assert guide.match_domains != ["data-axle.com"]


def test_perion_device_matching_and_declarations_remain_manual(settings):
    guide = next(g for g in guides(settings) if g.id == "perion-high-impact")
    assert guide.match_domains == ["undertone.com"]
    assert "matching_mobile_or_cookie_id" in guide.required_information.fields
    assert "not marked mandatory" in " ".join(guide.removal.steps)
    assert "Only affirm it if true" in " ".join(guide.removal.steps)
    assert "Canadian DOOH" in guide.coverage.excludes
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_rakuten_form_verification_does_not_cover_rewards_or_customer_copies(settings):
    guide = next(g for g in guides(settings) if g.id == "rakuten-advertising-identifiers")
    assert "Rakuten Rewards" in guide.coverage.excludes
    assert "anti-spam Name field blank" in " ".join(guide.removal.steps)
    assert "not actioned before verification" in " ".join(guide.removal.steps)
    assert "relevant_cookie_identifier" in guide.required_information.fields
    assert not guide.required_information.certainty == "documented"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_simplifi_consumer_email_is_not_a_matching_identifier(settings):
    guide = next(g for g in guides(settings) if g.id == "simplifi-advertising")
    assert "matching_ip_or_mobile_or_cookie_id" in guide.required_information.fields
    assert "Email is only for communication" in " ".join(guide.removal.steps)
    assert "Agent consent uploads concern representatives" in " ".join(guide.removal.steps)
    assert guide.coverage.effect == "deletion_request"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == guide.id)
    assert not item["requirements_complete"]


def test_moneyhouse_distinguishes_private_listing_removal_and_credit_access(settings):
    guide = next(g for g in guides(settings) if g.id == "moneyhouse-ch")
    assert "Neue Zürcher Zeitung AG" in guide.identity.legal_name
    assert guide.review_status == "instructions_reviewed"
    assert guide.coverage.effect == "access_then_review"
    assert "CRIF" in guide.coverage.excludes
    assert "commercial register" in " ".join(guide.removal.steps)
    assert "Never attach identity documents automatically" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_bislab_rights_mailbox_does_not_make_credit_freeze_deletion(settings):
    guide = next(g for g in guides(settings) if g.id == "bislab-no")
    assert "personvern@bislab.no" in guide.removal.alternatives
    assert guide.review_status == "needs_research"
    assert "Do not activate a credit freeze" in " ".join(guide.removal.steps)
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


def test_jwx_form_keeps_cookie_context_and_verification_distinct(settings):
    item = next(w for w in catalog_readiness.resources(settings)["items"] if w["id"] == "jwx")
    assert "relevant_browser_cookie" in item["fields"]
    assert "Verification initiates the request" in " ".join(item["steps"])
    assert "clearing cookies first can prevent matching" in " ".join(item["steps"])
    assert not item["requirements_complete"]


def test_niq_and_samsung_routes_do_not_imply_account_closure(settings):
    by_id = {g.id: g for g in guides(settings)}
    niq = by_id["niq-gfk-research"]
    assert "also require account deletion" in " ".join(niq.removal.steps)
    assert "separate Nielsen" in niq.coverage.excludes
    assert "Samsung Account" in by_id["adgear-samsung-ads"].coverage.excludes
    for guide_id in ["niq-gfk-research", "adgear-samsung-ads", "jwx-advertising"]:
        assert by_id[guide_id].automation.mode == "manual"
        assert guide_id not in {r.guide_id for r, _ in routes(settings).values()}


def test_alphonso_tv_matching_cannot_be_replaced_with_name_and_email(settings):
    guide = next(g for g in guides(settings) if g.id == "alphonso-tv")
    assert guide.required_information.fields == ["relevant_tv_or_device_identifier"]
    assert guide.automation.mode == "manual"
    assert guide.id not in {r.guide_id for r, _ in routes(settings).values()}


@pytest.mark.parametrize("guide_id,expected,unrelated", [
    ("whooz-whize", "postal", "sole-trader"),
    ("editus-lu", "listing", "sole traders"),
    ("equifax-asnef-spain", "credit", "retailer"),
    ("ctc-italy", "spid", "commercial-information"),
    ("registry-getvector-inc", "email", "bluesky"),
    ("registry-hunter-web-services-inc", "claim", "does not establish an eea"),
    ("registry-lead411-corporation", "verification", "could not retrieve"),
    ("registry-leadiq-inc", "professional", "healthcare"),
    ("registry-lotame-solutions-inc", "device", "postal disclosure"),
    ("registry-lusha-systems-inc", "suppression", "donor"),
    ("registry-medpro-systems", "healthcare", "estate"),
])
def test_workflow_notes_describe_the_correct_broker(settings, guide_id, expected, unrelated):
    guide = next(g for g in guides(settings) if g.id == guide_id)
    reason = guide.automation.reason.lower()
    assert expected in reason
    assert unrelated not in reason


@pytest.mark.parametrize("change", ["url", "domains", "checked_at"])
def test_form_changes_cannot_silently_inherit_readiness(settings, monkeypatch, change):
    wins = deepcopy(catalog_readiness.resources(settings))
    form = next(w for w in wins["items"] if w["id"] == "contactout")
    form[change] = {
        "url": "https://example.test/unreviewed-form",
        "domains": ["unrelated.example.test"],
        "checked_at": (datetime.now(UTC).date() - timedelta(days=91)).isoformat(),
    }[change]
    monkeypatch.setattr(catalog_readiness, "resources", lambda _: wins)
    report = catalog_readiness.readiness(settings)
    assert not report["initial_routes_ready"]
    assert any("contactout" in p for p in report["problems"])
