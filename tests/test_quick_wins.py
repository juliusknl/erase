from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from erasure.config import Settings
from erasure.models import Approval, AppSetting, Broker, Case, Event, Job
from erasure.quick_wins import checklist, mark_done, resources
from erasure.store import Store
from erasure.workflow import Workflow


def test_broker_descriptions_are_separate_from_form_instructions():
    settings = Settings(_env_file=None, catalog_dir=Path(__file__).parents[1] / "catalog")
    items = {item['id']: item for item in resources(settings)['items']}
    assert 'sales teams' in items['enlyft']['about']
    assert 'business contact lists' in items['bookyourdata']['about']
    assert 'employment history' in items['relpro']['about']
    for broker_id in ('enlyft', 'bookyourdata', 'relpro'):
        item = items[broker_id]
        assert item['about'] != item['description']
        assert item['description'] == item['steps'][0]
        assert item['source'].startswith('https://')
    assert all(item['about'] for item in items.values() if item.get('category') == 'professional')


def test_checklist_updates_form_not_deletion_and_is_idempotent(db, vault):
    settings = Settings(catalog_dir=Path(__file__).parents[1] / "catalog")
    workflow = Workflow(db, Store(db, vault), settings)
    broker = Broker(slug="seamless-test", name="Seamless", domain="seamless.ai")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="queued")
    db.add(case)
    db.flush()
    job = Job(kind="submit_case", encrypted_payload=vault.encrypt({"case_id": case.id}))
    action = Approval(case_id=case.id, kind="form_required", summary="Use form")
    db.add_all([job, action])
    db.commit()
    items = resources(settings)["items"]
    mark_done(workflow, next(i for i in items if i["id"] == "ddv-robinson"))
    assert case.state == "queued"
    assert job.status == "pending"
    item = next(i for i in items if i["id"] == "seamless")
    mark_done(workflow, item)
    mark_done(workflow, item)
    assert case.state == "done"
    assert case.completed_at is not None
    assert case.next_action_at is None
    assert job.status == "cancelled"
    assert action.status == "superseded"
    assert len(list(db.scalars(select(Event)))) == 1
    workflow.follow_up(case.id)
    workflow.recheck_case(case.id)
    assert case.state == "done"
    assert not list(db.scalars(select(Job).where(Job.status == "pending")))
    message = {
        "subject": "Your privacy request",
        "body": "Please use our privacy request form.",
        "from": "privacy@seamless.ai",
        "thread_id": "test-thread",
    }
    case.external_reference = "gmail-thread:test-thread"
    db.commit()
    assert workflow.process_message(message, sender_verified=True)
    assert case.state == "done"
    assert case.next_action_at is None
    assert not list(db.scalars(select(Job).where(Job.status == "pending")))
    assert db.get(AppSetting, "quick_win:seamless").value
    message["body"] = "Your personal data has been deleted."
    assert workflow.process_message(message, sender_verified=True)
    assert case.state == "removed"
    assert case.next_action_at is None
    # A checklist tick cannot reopen a confirmed deletion.
    db.get(AppSetting, "quick_win:seamless").value = ""
    case.state = "removed"
    case.completed_at = datetime.now(UTC)
    completed_at = case.completed_at
    next_action_at = case.next_action_at
    db.commit()
    mark_done(workflow, item)
    assert case.state == "removed"
    assert case.completed_at == completed_at
    assert case.next_action_at == next_action_at
    db.get(AppSetting, "quick_win:seamless").value = ""
    db.commit()
    item = next(i for i in checklist(settings, workflow.store) if i["id"] == "seamless")
    assert item["done"] and item["completed"] and not item["checked"]


def test_guide_backed_forms_preserve_requirements_and_link_all_exact_aliases(db, vault):
    settings = Settings(catalog_dir=Path(__file__).parents[1] / "catalog")
    workflow = Workflow(db, Store(db, vault), settings)
    items = resources(settings)["items"]
    assert len({item["id"] for item in items}) == len(items)
    wiza = next(item for item in items if item["id"] == "wiza")
    assert wiza["requirements_complete"]
    assert "confirmation" in wiza["verification"]
    assert "Not evidence of historical erasure" in wiza["scope"]
    amplemarket = next(item for item in items if item["id"] == "amplemarket")
    assert not amplemarket["requirements_complete"]
    assert "not the initial rights route" in amplemarket["verification"]
    assert amplemarket["checked_at"] == "2026-09-29"
    for domain in wiza["domains"]:
        db.add(Broker(slug=domain, name="Synthetic Wiza", domain=domain))
    db.commit()
    mark_done(workflow, wiza)
    cases = list(db.scalars(select(Case)))
    assert len(cases) == len(wiza["domains"])
    assert all(case.state == "done" for case in cases)
    item = next(item for item in checklist(settings, workflow.store) if item["id"] == "wiza")
    assert item["done"]
    assert set(item["case_ids"]) == {case.id for case in cases}
