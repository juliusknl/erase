from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from erasure import campaign
from erasure.config import Settings
from erasure.knowledge import guides
from erasure.models import AutomaticDelivery, Broker, Case, Job, RouteResearch
from erasure.store import Store
from erasure.workflow import Workflow


def setup_campaign(db, vault, count=5, limit=2, verified=True):
    store = Store(db, vault)
    store.save_profile(
        {
            "full_name": "Test Person",
            "email": "requests@example.test",
            "other_emails": ["work@example.test"],
            "postal_address": "NEVER DISCLOSE",
            "phone": "NEVER DISCLOSE",
            "birth_date": "NEVER DISCLOSE",
        },
        "Test Person",
    )
    store.set_setting("gmail_token", {"access_token": "synthetic"}, encrypted=True)
    for i in range(count):
        db.add(
            Broker(
                slug=f"auto-{i}",
                name=f"Auto {i}",
                domain=f"broker{i}.test",
                contact=f"privacy@broker{i}.test",
                policy_url=f"https://broker{i}.test/privacy",
                last_validated_at=datetime.now(UTC) if verified else None,
            )
        )
    db.commit()
    catalog_dir = Path(db.bind.url.database).parent / "campaign-catalog"
    catalog_dir.mkdir(exist_ok=True)
    base = next(g for g in guides(Settings(catalog_dir=Path(__file__).parents[1] / "catalog"))
                if g.id == "cognism")
    synthetic_guides, synthetic_routes = [], []
    for broker in db.scalars(select(Broker)):
        guide = base.model_copy(deep=True)
        guide.id, guide.name = broker.slug, broker.name
        guide.match_domains = guide.identity.official_domains = [broker.domain]
        guide.removal.destination = broker.contact
        guide.evidence[0].checked_on = datetime.now(UTC).date()
        synthetic_guides.append(guide.model_dump(mode="json"))
        synthetic_routes.append(dict(
            guide_id=broker.slug, destination=broker.contact, countries=["EEA"],
            fields=["full_name", "email", "other_emails"], effect="deletion_request",
            request="Please remove my synthetic professional profile from your database.",
            why="Synthetic professional contact database for integration verification.",
            follow_up="Review subsequent requests for additional verification.",
            evidence=[dict(url=broker.policy_url, checked_on=datetime.now(UTC).date().isoformat(),
                           excerpt="Email the privacy team for removal", supports=["email_route"])],
        ))
    (catalog_dir / "broker-knowledge.yml").write_text(yaml.safe_dump(
        dict(schema_version=1, brokers=synthetic_guides)))
    (catalog_dir / "email-routes.yml").write_text(yaml.safe_dump(
        dict(schema_version=1, routes=synthetic_routes)))
    workflow = Workflow(
        db,
        store,
        Settings(live_submissions=True, catalog_dir=catalog_dir),
    )
    campaign.enable(workflow, limit, campaign.preview_hash(workflow))
    return workflow


def test_research_only_checks_unfinished_unverified_approved_plans(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=4, verified=False)
    brokers = list(db.scalars(select(Broker).order_by(Broker.id)))
    brokers[0].last_validated_at = datetime.now(UTC)
    db.scalar(select(Case).where(Case.broker_id == brokers[1].id)).state = 'done'
    saved = campaign.consent(workflow.store)
    # Catalog scope can contain hundreds of brokers without an approved email plan.
    for i in range(300):
        broker = Broker(slug=f'candidate-{i}', name=f'Candidate {i}',
                        domain=f'candidate{i}.test', contact=f'privacy@candidate{i}.test')
        db.add(broker)
        db.flush()
        saved['scope'][str(broker.id)] = campaign.scope_key(broker)
    workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    original = campaign.route_problem
    checked = []

    def record_check(workflow, broker):
        checked.append(broker.id)
        return original(workflow, broker)

    monkeypatch.setattr(campaign, 'route_problem', record_check)
    expected = [b.id for b in brokers[2:]]
    assert [b.id for b in campaign.research_candidates(workflow)] == expected
    assert checked == expected
    # A changed recipient must still be rejected on the next check, not cached.
    brokers[2].contact = 'changed@example.test'
    db.commit()
    assert [b.id for b in campaign.research_candidates(workflow)] == [brokers[3].id]


def test_campaign_continues_next_day_without_batch_approval(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault)
    sent = []

    def send(_self, plan):
        sent.append(plan)
        return f"gmail-thread:test-{len(sent)}"

    monkeypatch.setattr("erasure.gmail.GmailClient.send", send)
    campaign.tick(workflow)
    rows = list(db.scalars(select(AutomaticDelivery)))
    assert len(rows) == 2
    for row in rows:
        campaign.dispatch(workflow, row.id)
        campaign.dispatch(workflow, row.id)
    campaign.tick(workflow)
    assert len(sent) == 2
    assert campaign.attempted_today(db) == 2
    for row in rows:
        row.started_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    campaign.tick(workflow)
    for row in db.scalars(select(AutomaticDelivery).where(AutomaticDelivery.status == "queued")):
        campaign.dispatch(workflow, row.id)
    assert len(sent) == 4
    assert len({p.destination for p in sent}) == 4
    assert all("NEVER DISCLOSE" not in p.body and not p.attachments for p in sent)
    assert all(set(p.disclosed_fields) <= {"full_name", "email", "other_emails", "country"} for p in sent)
    assert all("work@example.test" in p.body for p in sent)


def test_new_campaign_makes_progress_over_multiple_days_without_ai_or_agent(db, vault, monkeypatch):
    from erasure.inbox import capture_message
    from erasure.models import IncomingMessage
    workflow = setup_campaign(db, vault, count=8, limit=3)
    assert not workflow.settings.jev_enabled
    sent = []
    monkeypatch.setattr('erasure.gmail.GmailClient.send',
                        lambda _, plan: sent.append(plan) or f'gmail-thread:synthetic-{len(sent)}')
    for day in range(3):
        if day:
            # Advance the delivery-budget clock; no new consent or per-broker action.
            for row in db.scalars(select(AutomaticDelivery).where(AutomaticDelivery.started_at.is_not(None))):
                row.started_at = datetime.now(UTC) - timedelta(days=1)
            db.commit()
        campaign.tick(workflow)
        for row in db.scalars(select(AutomaticDelivery).where(AutomaticDelivery.status == 'queued')):
            campaign.dispatch(workflow, row.id)
            campaign.dispatch(workflow, row.id)  # restart/retry must not duplicate a send
    assert len(sent) == len({plan.destination for plan in sent}) == 8
    cases = list(db.scalars(select(Case).order_by(Case.id)))
    replies = [
        ('We received your request. Your request will be processed within 30 days.', 'processing'),
        ('Your personal data has been deleted.', 'removed'),
        ('Please use our privacy request form: https://broker2.test/data-request-form', 'needs_action'),
        ('We have no personal data matching your details.', 'not_found'),
        ('Please provide your work email address.', 'needs_action'),
        ('Your message was not delivered. Address not found.', 'delivery_failed'),
    ]
    for i, (body, expected) in enumerate(replies):
        case = cases[i]
        domain = 'googlemail.com' if expected == 'delivery_failed' else case.broker.domain
        mail = {'id': f'reply-{i}', 'subject': f'Re: ER-{case.id:06X}', 'body': body,
                'from': f'mailer-daemon@{domain}' if expected == 'delivery_failed' else f'privacy@{domain}',
                'authentication_results': f'mx.google.com; dmarc=pass header.from={domain}'}
        capture_message(workflow, mail)
        capture_message(workflow, mail)
        assert case.state == expected
    campaign.tick(workflow)
    assert len(sent) == 8
    assert len(list(db.scalars(select(IncomingMessage)))) == 6
    assert cases[6].state == cases[7].state == 'submitted'


def test_preview_loads_routes_once_not_once_per_broker(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=5)
    original = campaign.email_routes.routes
    calls = []
    def counted(settings):
        calls.append(1)
        return original(settings)
    monkeypatch.setattr(campaign.email_routes, "routes", counted)
    assert len(campaign.preview_rows(workflow)) == 5
    assert len(calls) == 1


def test_research_to_submission_needs_no_agent(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=1, verified=False)
    sent = []
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send", lambda _, plan: sent.append(plan) or "gmail-thread:test"
    )
    campaign.tick(workflow)
    assert not db.scalar(select(Job.id).where(Job.kind == "research_broker"))
    row = db.scalar(select(AutomaticDelivery))
    assert row
    assert db.get(RouteResearch, db.get(Case, row.case_id).broker_id).status == "verified"
    campaign.dispatch(workflow, row.id)
    assert len(sent) == 1
    assert db.get(Case, row.case_id).state == "submitted"


@pytest.mark.parametrize(
    "change", ["pause", "disable", "profile", "recipient", "stale", "closed", "gmail", "dry"]
)
def test_dispatch_rechecks_authority_and_eligibility(db, vault, monkeypatch, change):
    workflow = setup_campaign(db, vault, count=1)
    campaign.tick(workflow)
    row = db.scalar(select(AutomaticDelivery))
    case = db.get(Case, row.case_id)
    if change == "pause":
        workflow.store.set_setting("paused", "true")
    elif change == "disable":
        saved = campaign.consent(workflow.store)
        saved["enabled"] = False
        workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    elif change == "profile":
        profile = workflow.store.get_profile()
        profile["other_emails"] = ["new@example.test"]
        workflow.store.save_profile(profile)
    elif change == "recipient":
        case.broker.contact = "new@broker0.test"
    elif change == "stale":
        case.broker.last_validated_at = datetime.now(UTC) - timedelta(days=100)
    elif change == "closed":
        case.state = "done"
    elif change == "gmail":
        workflow.store.set_setting("gmail_error", "Reconnect")
    else:
        workflow.settings.live_submissions = False
    db.commit()
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send", lambda *a: pytest.fail("Unauthorized send")
    )
    campaign.dispatch(workflow, row.id)
    assert row.started_at is None


def test_crash_and_uncertain_delivery_are_not_retried(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=2)
    campaign.tick(workflow)
    first, second = list(db.scalars(select(AutomaticDelivery).order_by(AutomaticDelivery.id)))
    first.status = "sending"
    first.started_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()
    campaign.dispatch(workflow, first.id)
    assert first.status == "uncertain"
    sent = []

    def disconnect(*args):
        sent.append(True)
        raise RuntimeError("Connection disappeared after Gmail accepted message")

    monkeypatch.setattr("erasure.gmail.GmailClient.send", disconnect)
    campaign.dispatch(workflow, second.id)
    assert second.status == "uncertain"
    campaign.tick(workflow)
    campaign.dispatch(workflow, first.id)
    campaign.dispatch(workflow, second.id)
    assert len(sent) == 1
    assert all(c.state == "needs_action" for c in db.scalars(select(Case)))


def test_preflight_failure_keeps_queue_without_false_uncertain_delivery(db, vault, monkeypatch):
    from erasure.gmail import GmailPreflightError
    from erasure.models import Approval
    workflow = setup_campaign(db, vault, count=1)
    campaign.tick(workflow)
    row = db.scalar(select(AutomaticDelivery))
    def preflight(*args):
        raise GmailPreflightError('Identity check failed before any send')
    monkeypatch.setattr('erasure.gmail.GmailClient.send', preflight)
    campaign.dispatch(workflow, row.id)
    assert row.status == 'queued' and row.started_at is None
    assert campaign.attempted_today(db) == 0
    assert not list(db.scalars(select(Approval).where(Approval.kind == 'delivery_uncertain')))
    monkeypatch.setattr('erasure.gmail.GmailClient.send', lambda *args: 'gmail-thread:verified')
    campaign.dispatch(workflow, row.id)
    assert row.status == 'sent'
    assert campaign.attempted_today(db) == 1


def test_daily_limit_is_enforced_at_dispatch_not_only_scheduling(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=2, limit=1)
    campaign.prepare_backlog(workflow)
    for case in db.scalars(select(Case)):
        assert campaign.queue_delivery(workflow, case)
    sent = []
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send", lambda *a: sent.append(True) or "gmail-thread:test"
    )
    for row in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, row.id)
    assert len(sent) == 1
    assert campaign.attempted_today(db) == 1


def test_disable_blocks_legacy_submit_and_follow_up_for_managed_cases(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=1)
    campaign.tick(workflow)
    case = db.scalar(select(Case))
    saved = campaign.consent(workflow.store)
    saved["enabled"] = False
    workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send", lambda *a: pytest.fail("Bypassed consent")
    )
    workflow.submit_case(case.id)
    workflow.follow_up(case.id)
    workflow.submit_case(case.id)
    assert case.submitted_at is None


@pytest.mark.parametrize('permission', ['absent', 'disabled', 'out_of_scope'])
def test_legacy_email_jobs_cannot_escape_campaign_permissions(db, vault, monkeypatch, permission):
    workflow = setup_campaign(db, vault, count=1)
    broker = db.scalar(select(Broker))
    # Reproduce a pre-controller job, including the old default to disclose addresses.
    broker.required_fields = '{"default_confidence": 60}'
    saved = campaign.consent(workflow.store)
    if permission == 'absent':
        saved = {}
    elif permission == 'disabled':
        saved['enabled'] = False
        saved['scope'] = {}
    else:
        saved['scope'] = {}
    workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    case = db.scalar(select(Case))
    case.state = 'queued'
    db.commit()
    monkeypatch.setattr('erasure.gmail.GmailClient.send', lambda *args: pytest.fail('Bypassed permission'))
    workflow.submit_case(case.id)
    assert case.submitted_at is None
    assert case.attempt_count == 0
    assert case.last_error
    assert not list(db.scalars(select(AutomaticDelivery)))


def test_legacy_job_enters_dispatch_ledger_and_respects_minimal_disclosure(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=1)
    case = db.scalar(select(Case))
    case.state = 'queued'
    case.broker.required_fields = '{"include_postal": true}'
    db.commit()
    sent = []
    monkeypatch.setattr('erasure.gmail.GmailClient.send', lambda self, plan: sent.append(plan) or 'synthetic')
    workflow.submit_case(case.id)
    workflow.submit_case(case.id)
    assert not sent
    deliveries = list(db.scalars(select(AutomaticDelivery)))
    assert len(deliveries) == 1
    campaign.dispatch(workflow, deliveries[0].id)
    campaign.dispatch(workflow, deliveries[0].id)
    assert len(sent) == 1
    assert 'postal_address' not in sent[0].disclosed_fields
    assert 'NEVER DISCLOSE' not in sent[0].body
    assert deliveries[0].status == 'sent'


def test_pause_resume_stop_preserve_cases_and_revoke_restart_authority(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=3)
    campaign.tick(workflow)
    cases = list(db.scalars(select(Case).order_by(Case.id)))
    cases[1].state = 'submitted'
    cases[2].state = 'removed'
    cases[2].completed_at = datetime.now(UTC)
    db.commit()
    before = [(c.id, c.state, c.completed_at, c.attempt_count) for c in cases]
    sent = []
    monkeypatch.setattr('erasure.gmail.GmailClient.send', lambda *a: sent.append(True) or 'gmail-thread:test')
    campaign.pause(workflow)
    workflow.submit_case(cases[0].id)
    workflow.follow_up(cases[1].id)
    workflow.recheck_case(cases[2].id)
    assert [(c.id, c.state, c.completed_at, c.attempt_count) for c in cases] == before
    assert not sent
    campaign.resume(workflow)
    assert workflow.store.get_setting('paused') == 'false'
    campaign.stop(workflow)
    assert not campaign.consent(workflow.store)['enabled']
    assert workflow.store.get_setting('paused') == 'true'
    with pytest.raises(ValueError, match='permission again'):
        campaign.resume(workflow)
    campaign.tick(workflow)
    workflow.submit_case(cases[0].id)
    assert not sent
    assert [(c.id, c.state, c.completed_at, c.attempt_count) for c in cases] == before
    campaign.enable(workflow, 20, campaign.preview_hash(workflow))
    assert workflow.store.get_setting('paused') == 'false'
    assert 'stopped_at' not in campaign.consent(workflow.store)
    assert cases[2].state == 'removed'


def test_resume_requires_current_identity_and_country(db, vault):
    workflow = setup_campaign(db, vault, count=1)
    campaign.pause(workflow)
    workflow.store.set_setting('recommendation_country', 'US', encrypted=True)
    with pytest.raises(ValueError, match='Country changed'):
        campaign.resume(workflow)
    assert workflow.store.get_setting('paused') == 'true'


@pytest.mark.parametrize('action', ['pause', 'stop'])
@pytest.mark.parametrize('kind', ['submit_case', 'automatic_send', 'follow_up', 'recheck_case'])
def test_worker_holds_same_outgoing_job_but_continues_polling(db, vault, master_key, monkeypatch, action, kind):
    from erasure import worker

    store = Store(db, vault)
    settings = Settings(_env_file=None, master_key=master_key, password_hash='configured', session_secret='configured')
    workflow = Workflow(db, store, settings)
    getattr(campaign, action)(workflow)
    held = store.enqueue(kind, {'case_id': 123, 'delivery_id': 123})
    held_id = held.id
    store.enqueue('poll_gmail', {})
    monkeypatch.setattr(worker, 'SessionLocal', lambda: db)
    monkeypatch.setattr(worker, 'get_settings', lambda: settings)
    handled = []
    monkeypatch.setattr(worker, 'handle_job', lambda kind, *args: handled.append(kind))
    assert worker.run_once()
    assert handled == ['poll_gmail']
    assert worker.run_once()
    assert handled == ['poll_gmail']
    jobs = list(db.scalars(select(Job).where(Job.kind == kind)))
    assert len(jobs) == 1
    assert jobs[0].id == held_id and jobs[0].status == 'pending'
    assert jobs[0].last_error == 'Held while automatic sending is paused'
    assert not list(db.scalars(select(AutomaticDelivery)))


def test_new_catalog_targets_require_renewed_consent(db, vault):
    workflow = setup_campaign(db, vault, count=1)
    old_preview = campaign.preview_hash(workflow)
    broker = Broker(
        slug="later",
        name="Later",
        domain="later.test",
        contact="privacy@later.test",
        last_validated_at=datetime.now(UTC),
    )
    db.add(broker)
    db.commit()
    with pytest.raises(ValueError, match="catalog"):
        campaign.enable(workflow, 20, old_preview)
    assert not campaign.eligible(workflow, broker)


def test_research_exception_does_not_starve_next_broker(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=2, verified=False)
    first, second = list(db.scalars(select(Broker).order_by(Broker.id)))
    first_id = first.id
    workflow.store.enqueue("research_broker", {"broker_id": first_id})
    # An invalid route and its legacy queued job cannot starve another valid route.
    first.contact = "changed@example.test"
    db.commit()
    campaign.research_broker(workflow, first_id)
    assert db.get(RouteResearch, first_id) is None
    campaign.tick(workflow)
    assert db.get(RouteResearch, first_id) is None
    assert db.get(RouteResearch, second.id).status == "verified"
    delivery = db.scalar(select(AutomaticDelivery))
    assert db.get(Case, delivery.case_id).broker_id == second.id


def test_competing_dispatchers_share_one_atomic_daily_budget(db, vault, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.orm import Session

    workflow = setup_campaign(db, vault, count=2, limit=1)
    campaign.prepare_backlog(workflow)
    for case in db.scalars(select(Case)):
        campaign.queue_delivery(workflow, case)
    ids = list(db.scalars(select(AutomaticDelivery.id)))
    sent = []
    monkeypatch.setattr(
        "erasure.gmail.GmailClient.send", lambda *a: sent.append(True) or "gmail-thread:atomic"
    )

    def dispatch(delivery_id):
        with Session(db.bind, expire_on_commit=False) as session:
            campaign.dispatch(
                Workflow(session, Store(session, vault), workflow.settings), delivery_id
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(dispatch, ids))
    assert len(sent) == 1


@pytest.mark.parametrize("legacy_checks,cooldown", [(0, False), (100, False), (0, True), (100, True)])
def test_reviewed_workflows_do_not_wait_for_legacy_research_limits(
    db, vault, monkeypatch, legacy_checks, cooldown
):
    workflow = setup_campaign(db, vault, count=1, verified=False)
    target = db.scalar(select(Broker))
    for i in range(legacy_checks):
        old = Broker(slug=f"old-research-{i}", name="Unapproved old candidate",
                     domain=f"old{i}.test", contact=f"privacy@old{i}.test")
        db.add(old)
        db.flush()
        db.add(RouteResearch(broker_id=old.id, status="needs_review",
                             checked_at=datetime.now(UTC)))
    if cooldown:
        db.add(RouteResearch(broker_id=target.id, status="needs_review",
                             checked_at=datetime.now(UTC) - timedelta(days=1),
                             next_check_at=datetime.now(UTC) + timedelta(days=30)))
    db.commit()
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:reviewed")
    # Drain the old job path too, so the positive control passes before the fix.
    for _ in range(2):
        campaign.tick(workflow)
        for job in db.scalars(select(Job).where(
            Job.kind == "research_broker", Job.status == "pending"
        )):
            campaign.research_broker(
                workflow, workflow.store.vault.decrypt(job.encrypted_payload)["broker_id"]
            )
            job.status = "done"
        db.commit()
    delivery = db.scalar(select(AutomaticDelivery))
    assert delivery is not None
    assert db.get(Case, delivery.case_id).broker_id == target.id
    campaign.dispatch(workflow, delivery.id)
    campaign.dispatch(workflow, delivery.id)
    assert len(sent) == 1
    assert sent[0].destination == target.contact


def test_status_reports_research_wait_and_review_instead_of_fake_progress(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=1, verified=False)
    assert campaign.summary(workflow)["label"] == "Checking reviewed workflows"
    broker = db.scalar(select(Broker))
    db.add(
        RouteResearch(
            broker_id=broker.id,
            status="needs_review",
            checked_at=datetime.now(UTC),
            next_check_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    db.commit()
    assert campaign.summary(workflow)["label"] == "Checking reviewed workflows"
    db.scalar(select(Case)).state = "needs_action"
    db.commit()
    assert campaign.summary(workflow)["label"] == "Monitoring replies and scheduled rechecks"
    workflow.store.set_setting(
        "campaign_last_tick", (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    )
    assert "checks delayed" in campaign.summary(workflow)["label"]


def test_local_checks_are_bounded_per_tick_without_changing_the_sending_budget(db, vault):
    count = campaign.LOCAL_CHECKS_PER_TICK + 1
    workflow = setup_campaign(db, vault, count=count, limit=2, verified=False)
    campaign.tick(workflow)
    assert len(list(db.scalars(select(RouteResearch)))) == campaign.LOCAL_CHECKS_PER_TICK
    assert len(list(db.scalars(select(AutomaticDelivery)))) == 2
    assert campaign.attempted_today(db) == 0
    campaign.tick(workflow)
    assert len(list(db.scalars(select(RouteResearch)))) == count
    assert len(list(db.scalars(select(AutomaticDelivery)))) == 2
    assert not db.scalar(select(Job.id).where(Job.kind == "research_broker"))


def test_continuous_plan_adds_new_reviewed_routes_and_sends_without_reapproval(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=3, limit=2, verified=False)
    saved = campaign.consent(workflow.store)
    saved["include_new"] = True
    brokers = list(db.scalars(select(Broker).order_by(Broker.id)))
    # Simulate two recipes arriving after the original plan, one already done manually.
    for broker in brokers[1:]:
        saved["plans"].pop(str(broker.id))
    done = db.scalar(select(Case).where(Case.broker_id == brokers[2].id))
    done.state = "done"
    done.completed_at = datetime.now(UTC)
    workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    sent = []
    monkeypatch.setattr("erasure.gmail.GmailClient.send",
                        lambda _, plan: sent.append(plan) or "gmail-thread:continuous")
    campaign.tick(workflow)
    assert str(brokers[1].id) in campaign.consent(workflow.store)["plans"]
    for delivery in db.scalars(select(AutomaticDelivery)):
        campaign.dispatch(workflow, delivery.id)
    campaign.tick(workflow)
    assert len(sent) == 2
    assert done.state == "done"
    assert "review your campaign" not in campaign.summary(workflow)["label"].lower()


@pytest.mark.parametrize("block", ["legacy", "paused", "postal", "country", "stale", "changed", "specialist"])
def test_continuous_plan_preserves_permission_and_route_boundaries(db, vault, monkeypatch, block):
    workflow = setup_campaign(db, vault, count=1, verified=False)
    saved = campaign.consent(workflow.store)
    saved["include_new"] = block != "legacy"
    if block != "changed":
        saved["plans"] = {}
    workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    if block == "paused":
        workflow.store.set_setting("paused", "true")
    entries = campaign.email_routes.routes(workflow.settings)
    route, guide = entries["broker0.test"]
    route, guide = route.model_copy(deep=True), guide.model_copy(deep=True)
    if block == "postal":
        route.fields.append("postal_address")
    elif block == "country":
        route.countries = ["FR"]
    elif block == "stale":
        route.evidence[0].checked_on = (datetime.now(UTC) - timedelta(days=100)).date()
    elif block == "changed":
        route.request += " Also share a different request."
    elif block == "specialist":
        guide.relevance.category = "aggregate_business"
    monkeypatch.setattr(campaign.email_routes, "routes", lambda _: {"broker0.test": (route, guide)})
    monkeypatch.setattr("erasure.gmail.GmailClient.send", lambda *a: pytest.fail("Unsafe send"))
    campaign.tick(workflow)
    assert not db.scalar(select(AutomaticDelivery))
    assert campaign.consent(workflow.store)["plans"] == saved["plans"]


def test_continuous_plan_can_add_a_new_catalog_entry_but_not_its_alias(db, vault, monkeypatch):
    workflow = setup_campaign(db, vault, count=1, verified=False)
    broker = db.scalar(select(Broker))
    case = db.scalar(select(Case))
    db.delete(case)
    db.commit()
    saved = campaign.consent(workflow.store)
    saved.update(include_new=True, plans={}, scope={})
    workflow.store.set_setting(campaign.CONSENT_KEY, saved, encrypted=True)
    route, guide = campaign.email_routes.routes(workflow.settings)[broker.domain]
    db.add(Broker(slug="alias", name="Same database", domain="alias.test", contact=route.destination))
    db.commit()
    monkeypatch.setattr(campaign.email_routes, "routes",
                        lambda _: {broker.domain: (route, guide), "alias.test": (route, guide)})
    campaign.tick(workflow)
    assert len(campaign.consent(workflow.store)["plans"]) == 1
    assert len(list(db.scalars(select(Case)))) == 1
    assert len(list(db.scalars(select(AutomaticDelivery)))) == 1
    campaign.tick(workflow)
    assert len(list(db.scalars(select(AutomaticDelivery)))) == 1
