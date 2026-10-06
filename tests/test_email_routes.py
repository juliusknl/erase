from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from erasure import campaign, email_routes
from erasure.config import Settings
from erasure.models import AutomaticDelivery, Broker, Case, Job
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]

ALL_ROUTES = {r.guide_id: r for r, _ in email_routes.routes(
    Settings(catalog_dir=ROOT / "catalog")
).values()}


def setup(db, vault, ids):
    settings = Settings(catalog_dir=ROOT / "catalog", live_submissions=True)
    store = Store(db, vault)
    store.save_profile(dict(full_name="Synthetic Person", email="request@example.test",
                            other_emails=["professional@example.test"],
                            work_email="work@example.test", employer="Synthetic Employer",
                            postal_address="1 Synthetic Street", phone="DO NOT SEND"),
                       "Synthetic Person")
    store.set_setting("gmail_token", {"access_token": "fake"}, encrypted=True)
    added = set()
    for domain, (route, guide) in email_routes.routes(settings).items():
        if guide.id not in ids or guide.id in added:
            continue
        added.add(guide.id)
        db.add(Broker(slug=guide.id, name=guide.name, domain=domain,
                      contact=route.destination, connector_type="email"))
    db.commit()
    return Workflow(db, store, settings)


def approve(workflow, country="DE", postal=False):
    campaign.enable(workflow, 20, campaign.preview_hash(workflow, country, postal), country, postal)


def run_controller(workflow):
    # Exercise the real controller and research-to-preparation handoff.
    for _ in range(10):
        campaign.tick(workflow)
        for job in workflow.session.scalars(select(Job).where(
                Job.kind == "research_broker", Job.status == "pending")):
            payload = workflow.store.vault.decrypt(job.encrypted_payload)
            campaign.research_broker(workflow, payload["broker_id"])
            job.status = "done"
        workflow.session.commit()


def test_real_postal_and_professional_workflows_disclose_only_approved_fields(db, vault, monkeypatch):
    workflow = setup(db, vault, {"az-direct-de", "draup", "registry-leadgenius-com"})
    approve(workflow, postal=True)
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:synthetic")
    run_controller(workflow)
    for delivery in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, delivery.id)
        campaign.dispatch(workflow, delivery.id)
    assert len(sent) == 3
    for plan in sent:
        assert "DO NOT SEND" not in plan.body
        if plan.destination == "datenschutz@az-direct.com":
            assert "1 Synthetic Street" in plan.body
            assert "professional@example.test" not in plan.body
            assert "suppression" in plan.body
        else:
            assert "1 Synthetic Street" not in plan.body
            assert "professional@example.test" in plan.body
    assert next(p for p in sent if p.destination == "privacy@draup.com").subject.startswith("Opt-Out")
    assert all(c.state == "submitted" for c in db.scalars(select(Case)))


@pytest.mark.parametrize("country,postal,expected", [("DE", False, 0), ("FR", True, 0), ("DE", True, 1)])
def test_address_and_residence_gates(db, vault, country, postal, expected):
    workflow = setup(db, vault, {"az-direct-de"})
    approve(workflow, country, postal)
    run_controller(workflow)
    assert len(list(db.scalars(select(AutomaticDelivery)))) == expected


@pytest.mark.parametrize("guide_id,country,postal,expected", [
    ("data-axle", "DE", True, 1),
    ("data-axle", "NO", True, 0),
    ("data-axle", "EEA", True, 0),
    ("data-axle", "DE", False, 0),
    ("liveramp-de", "DE", True, 1),
    ("liveramp-de", "FR", True, 0),
    ("liveramp-de", "DE", False, 0),
    ("vendelux", "NO", False, 1),
    ("adpublisher-consumer", "DE", True, 1),
    ("adpublisher-consumer", "DE", False, 0),
    ("add-conti", "DE", False, 1),
    ("add-conti", "FR", False, 0),
    ("circana-marketing", "FR", False, 1),
    ("myoffers-uk", "DE", True, 1),
    ("myoffers-uk", "DE", False, 0),
    ("market-location-uk", "FR", False, 1),
    ("melissa-consumer-databases", "DE", True, 1),
    ("melissa-consumer-databases", "DE", False, 0),
    ("burda-direkt-marketing", "DE", True, 1),
    ("burda-direkt-marketing", "DE", False, 0),
])
def test_new_major_routes_enforce_documented_residence_and_postal_consent(
    db, vault, guide_id, country, postal, expected,
):
    workflow = setup(db, vault, {guide_id})
    approve(workflow, country, postal)
    run_controller(workflow)
    assert len(list(db.scalars(select(AutomaticDelivery)))) == expected


@pytest.mark.parametrize("country,recipient", [
    ("DE", "privacy.de@liveramp.com"),
    ("FR", "cil@liveramp.com"),
    ("IT", "privacy.it@liveramp.com"),
    ("ES", "privacy.es@liveramp.com"),
    ("EEA", None),
])
def test_liveramp_selects_only_the_residents_route(db, vault, monkeypatch, country, recipient):
    workflow = setup(db, vault, {"liveramp-de", "liveramp-fr", "liveramp-it", "liveramp-es"})
    approve(workflow, country=country, postal=True)
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:synthetic")
    run_controller(workflow)
    for delivery in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, delivery.id)
        campaign.dispatch(workflow, delivery.id)
    assert [plan.destination for plan in sent] == ([recipient] if recipient else [])
    if sent:
        assert ("1 Synthetic Street" in sent[0].body) is (country == "DE")
        assert "DO NOT SEND" not in sent[0].body


def test_country_or_postal_option_cannot_be_changed_after_preview(db, vault):
    workflow = setup(db, vault, {"az-direct-de"})
    old = campaign.preview_hash(workflow, "DE", False)
    with pytest.raises(ValueError, match="preview"):
        campaign.enable(workflow, 20, old, "DE", True)


def test_postal_change_and_disabled_consent_block_queued_work(db, vault, monkeypatch):
    workflow = setup(db, vault, {"az-direct-de"})
    approve(workflow, postal=True)
    run_controller(workflow)
    delivery = db.scalar(select(AutomaticDelivery))
    profile = workflow.store.get_profile()
    profile["postal_address"] = "Different address"
    workflow.store.save_profile(profile)
    monkeypatch.setattr("erasure.gmail.GmailClient.send", lambda *a: pytest.fail("Leaked address"))
    campaign.dispatch(workflow, delivery.id)
    assert delivery.started_at is None
    assert "Postal address changed" in delivery.reason


def test_recipe_changes_do_not_inherit_old_approval(db, vault, monkeypatch):
    workflow = setup(db, vault, {"draup"})
    approve(workflow)
    run_controller(workflow)
    delivery = db.scalar(select(AutomaticDelivery))
    index = email_routes.routes(workflow.settings)
    route, guide = index["draup.com"]
    replacement = route.model_copy(update={"request": "A different request with new scope and purpose."})
    monkeypatch.setattr(email_routes, "routes", lambda _: {"draup.com": (replacement, guide)})
    monkeypatch.setattr("erasure.gmail.GmailClient.send", lambda *a: pytest.fail("Unapproved text"))
    campaign.dispatch(workflow, delivery.id)
    assert delivery.status == "cancelled"
    assert delivery.started_at is None


@pytest.mark.parametrize("field", ["work_email", "employer"])
def test_professional_identity_changes_block_only_affected_approved_messages(db, vault, monkeypatch, field):
    workflow = setup(db, vault, {"salesintel", "revenuebase", "draup"})
    approve(workflow)
    run_controller(workflow)
    assert len(list(db.scalars(select(AutomaticDelivery)))) == 3
    profile = workflow.store.get_profile()
    profile[field] = "changed@example.test" if field == "work_email" else "Changed Employer"
    workflow.store.save_profile(profile)
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:synthetic")
    for delivery in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, delivery.id)
    assert len(sent) == 1
    assert sent[0].destination == "privacy@draup.com"
    assert "Changed Employer" not in sent[0].body
    assert "changed@example.test" not in sent[0].body
    assert all(d.started_at is None for d in db.scalars(select(AutomaticDelivery))
               if d.status == "cancelled")


@pytest.mark.parametrize("field,value", [("work_email", ""), ("work_email", "bad email"),
                                        ("employer", "")])
def test_professional_routes_require_explicit_usable_matching_fields(db, vault, field, value):
    workflow = setup(db, vault, {"salesintel", "revenuebase"})
    profile = workflow.store.get_profile()
    profile[field] = value
    workflow.store.save_profile(profile)
    assert not any(row["plan"] for row in campaign.preview_rows(workflow))
    approve(workflow)
    run_controller(workflow)
    assert not list(db.scalars(select(AutomaticDelivery)))


def test_professional_recipe_preview_minimizes_disclosure(db, vault):
    workflow = setup(db, vault, {"salesintel", "revenuebase"})
    for row in campaign.preview_rows(workflow):
        plan = row["plan"]
        assert plan
        assert "work@example.test" in plan.body
        assert "Synthetic Employer" in plan.body
        assert "professional@example.test" not in plan.body
        assert "1 Synthetic Street" not in plan.body
        assert "DO NOT SEND" not in plan.body


def test_approved_recipient_migration_is_explicit_and_completed_aliases_stay_done(db, vault):
    workflow = setup(db, vault, {"dealfront-leadfeeder"})
    broker = db.scalar(select(Broker))
    broker.contact = "old@example.test"
    db.commit()
    rows = campaign.preview_rows(workflow)
    assert rows[0]["plan"].destination == "privacy@leadfeeder.com"
    assert broker.contact == "old@example.test"  # GET is read-only.
    approve(workflow)
    assert broker.contact == "privacy@leadfeeder.com"
    case = db.scalar(select(Case))
    case.state, case.submitted_at = "done", datetime.now(UTC)
    other = "leadfeeder.com" if broker.domain != "leadfeeder.com" else "dealfront.com"
    db.add(Broker(slug="alias", name="Alias", domain=other,
                  contact="privacy@leadfeeder.com", connector_type="email"))
    db.commit()
    assert not any(row["plan"] for row in campaign.preview_rows(workflow))
    approve(workflow)
    run_controller(workflow)
    assert not list(db.scalars(select(AutomaticDelivery)))
    assert case.state == "done"


def test_work_email_is_needed_and_no_arbitrary_plan_can_bypass_a_recipe(db, vault, monkeypatch):
    workflow = setup(db, vault, {"draup"})
    profile = workflow.store.get_profile()
    profile["other_emails"] = []
    workflow.store.save_profile(profile)
    assert "email used outside" in campaign.preview_rows(workflow)[0]["reason"]
    profile["other_emails"] = ["professional@example.test"]
    workflow.store.save_profile(profile)
    approve(workflow)
    run_controller(workflow)
    case = db.scalar(select(Case))
    plan = campaign.make_plan(workflow.store, case.broker, "ER-000001", workflow.settings)
    forged = type(plan)(**{**asdict(plan), "body": "Different unauthorized content"})
    monkeypatch.setattr("erasure.gmail.GmailClient.send", lambda *a: pytest.fail("Forged plan"))
    with pytest.raises(ValueError, match="approved workflow"):
        workflow.submit_case(case.id, approved_plan=forged)


@pytest.mark.parametrize("guide_id", sorted(ALL_ROUTES))
def test_every_route_blocks_missing_matching_identifier_or_postal_permission(db, vault, guide_id):
    route = ALL_ROUTES[guide_id]
    workflow = setup(db, vault, {guide_id})
    country = "DE" if "EEA" in route.countries else route.countries[0]
    profile = workflow.store.get_profile()
    profile["other_emails"] = []
    workflow.store.save_profile(profile)
    broker = db.scalar(select(Broker))
    profile["work_email"] = ""
    _, guide = email_routes.routes(workflow.settings)[broker.domain]
    reason = email_routes.problem(route, guide, broker, profile, country, False)
    assert reason  # A fresh dedicated mailbox alone never represents a useful match.
    if "postal_address" in route.fields:
        assert "permission" in reason
    elif "work_email" in route.fields:
        assert "work email" in reason
    else:
        assert "email used outside" in reason


def test_expansion_keeps_sensitive_or_unsupported_routes_out_of_automatic_dispatch():
    assert not {
        "numberly", "herold-at", "experian-italy", "registry-live-data-technologies-inc",
        "start-io", "wunderkind", "quorum",
        "registry-innovation-brands-corp",
    }.intersection(ALL_ROUTES)
    assert ALL_ROUTES["quadress"].destination == "info@quadress.de"
    assert ALL_ROUTES["quadress"].effect == "suppression"
    assert ALL_ROUTES["stirista"].effect == "suppression"
    assert "postal_address" in ALL_ROUTES["stirista"].fields
    assert "device-only records" in ALL_ROUTES["anteriad"].request
    assert "Extension Data Request" in ALL_ROUTES["smarte"].request


@pytest.mark.parametrize("guide_id", sorted(ALL_ROUTES))
def test_every_published_workflow_reaches_fake_sender_once(db, vault, monkeypatch, guide_id):
    route = ALL_ROUTES[guide_id]
    workflow = setup(db, vault, {guide_id})
    country = "DE" if "EEA" in route.countries else route.countries[0]
    postal = "postal_address" in route.fields
    approve(workflow, country=country, postal=postal)
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:synthetic")
    run_controller(workflow)
    delivery = db.scalar(select(AutomaticDelivery))
    assert delivery is not None
    campaign.dispatch(workflow, delivery.id)
    campaign.dispatch(workflow, delivery.id)
    assert len(sent) == 1
    plan = sent[0]
    assert plan.destination == route.destination
    assert route.request in plan.body
    assert ("1 Synthetic Street" in plan.body) is postal
    assert "DO NOT SEND" not in plan.body
    assert db.scalar(select(Case)).state == "submitted"


@pytest.mark.parametrize("guide_id,country", [
    ("az-direct-at", "DE"), ("mediaposte-fr", "AT"), ("sovendus-de", "FR"),
])
def test_regional_expansion_does_not_cross_residence_scope(db, vault, guide_id, country):
    workflow = setup(db, vault, {guide_id})
    approve(workflow, country=country, postal=True)
    run_controller(workflow)
    assert not list(db.scalars(select(AutomaticDelivery)))


def test_proof_and_form_requirements_are_not_promoted_to_email():
    from erasure.knowledge import guides

    knowledge = {g.id: g for g in guides(Settings(catalog_dir=ROOT / "catalog"))}
    assert "identity_proof" in knowledge["numberly"].required_information.fields
    assert knowledge["registry-growbots-inc"].removal.method == "form"
    assert not {"numberly", "registry-growbots-inc"}.intersection(ALL_ROUTES)


def test_new_workflows_are_visible_but_never_inherit_approval(db, vault, monkeypatch):
    workflow = setup(db, vault, {"draup", "bizmachine"})
    index = email_routes.routes(workflow.settings)
    with monkeypatch.context() as old_catalog:
        old_catalog.setattr(email_routes, "routes", lambda _: {
            domain: entry for domain, entry in index.items() if entry[0].guide_id != "bizmachine"
        })
        approve(workflow)
    assert campaign.summary(workflow)["new_workflows"] == 1
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:synthetic")
    run_controller(workflow)
    for delivery in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, delivery.id)
    assert [p.destination for p in sent] == ["privacy@draup.com"]
    assert "New email workflows available" in campaign.summary(workflow)["label"]
    approve(workflow)
    assert campaign.summary(workflow)["new_workflows"] == 0
    run_controller(workflow)
    for delivery in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, delivery.id)
    assert [p.destination for p in sent] == ["privacy@draup.com", "osobniudaje@bizmachine.com"]


def test_reply_audit_disables_failed_and_form_first_email_routes():
    assert not {'goava', 'mygimi-marketing', 'registry-grin-technologies-inc',
                'hireez-talent-database', 'mediavine-reader-advertising', 'datonics-advertising',
                'registry-healthlink-dimensions-llc'}.intersection(ALL_ROUTES)
    route = next(r for r, _ in email_routes.routes(Settings(catalog_dir=ROOT / 'catalog')).values()
                 if r.guide_id == 'prospectbase-uk-professional')
    assert 'work_email' in route.fields


def test_optional_work_email_improves_matching_without_blocking_others(db, vault):
    workflow = setup(db, vault, {'vendelux'})
    broker = db.scalar(select(Broker))
    route, guide = email_routes.routes(workflow.settings)[broker.domain]
    profile = workflow.store.get_profile()
    plan = email_routes.prepare(route, guide, broker, profile, 'ER-TEST123', 'DE', False)
    assert 'work@example.test' in plan.body and 'work_email' in plan.disclosed_fields
    profile.pop('work_email')
    plan = email_routes.prepare(route, guide, broker, profile, 'ER-TEST123', 'DE', False)
    assert 'work_email' not in plan.disclosed_fields
    assert 'professional@example.test' in plan.body
