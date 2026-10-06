"""Recommendations are presentation, never sending consent or deletion evidence."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure import campaign
from erasure import recommendations as rec
from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import Approval, AppSetting, Broker, Case, IncomingMessage, Job
from erasure.quick_wins import mark_done
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


@pytest.fixture
def workflow(db, vault):
    w = Workflow(db, Store(db, vault), Settings(_env_file=None, catalog_dir=ROOT / "catalog"))
    w.store.set_setting("recommendation_country", "DE")
    return w


@pytest.mark.parametrize(
    "regions,country,expected",
    [
        (["EEA"], "DE", True),
        (["EEA"], "US", False),
        (["EU"], "NO", False),
        (["Germany"], "DE", True),
        (["UK"], "GB", True),
        (["Canada"], "CA", True),
        (["EEA scope unconfirmed"], "DE", False),
        (["California"], "US", False),
        (["United States; European scope unresolved"], "DE", False),
        (["Global"], "FR", True),
        (["Global"], "", False),
    ],
)
def test_country_matching_never_guesses_rights(regions, country, expected):
    assert rec.region_matches(regions, country) is expected


def test_default_recommendations_exclude_specialists_and_available_emails(workflow):
    rows = rec.action_items(workflow)
    selected = rec.session_items(workflow, rows)
    assert len(selected) == 3
    assert all(i["recommended"] and i["region_ok"] and not i["email_possible"] for i in selected)
    for item in rows:
        if item.get("category") in {"credit_reference", "identity_risk"}:
            assert not item["selectable"]
    leadiq = next(i for i in rows if i["id"] == "leadiq")
    assert leadiq["email_possible"] and not leadiq["selectable"]
    assert any(i["id"] == "besurance-his-insurance" for i in rows)  # still in the library


def test_three_actions_stay_stable_and_completion_does_not_refill(workflow):
    original = rec.session_items(workflow)
    rec.remember_session(workflow)
    mark_done(workflow, original[0])
    after = rec.session_items(workflow)
    assert [i["id"] for i in after] == [i["id"] for i in original[1:]]
    for item in after:
        rec.set_preference(workflow, item["id"], "skip")
    assert rec.session_items(workflow) == []
    # Restarting the view does not create another batch.
    again = Workflow(
        workflow.session, Store(workflow.session, workflow.store.vault), workflow.settings
    )
    assert rec.session_items(again) == []
    workflow.store.set_setting(rec.SESSION_KEY, {}, encrypted=True)
    assert len(rec.session_items(workflow)) == 3
    assert not {i["id"] for i in original} & {i["id"] for i in rec.session_items(workflow)}


def test_postponing_or_skipping_never_changes_cases_jobs_or_consent(workflow):
    db = workflow.session
    item = rec.session_items(workflow)[0]
    broker = Broker(slug="recommend-test", name="Synthetic", domain=item["domains"][0])
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="prepared")
    job = Job(kind="synthetic", encrypted_payload=workflow.store.vault.encrypt({}))
    db.add_all([case, job])
    db.commit()
    workflow.store.set_setting(
        "automatic_campaign", {"enabled": False, "plans": {}}, encrypted=True
    )
    consent = db.get(AppSetting, "automatic_campaign").value
    rec.set_preference(workflow, item["id"], "later")
    assert rec.preference(workflow.store, item["id"]) == "later"
    assert rec.preference(workflow.store, item["id"], datetime.now(UTC) + timedelta(days=8)) == ""
    assert case.state == "prepared" and job.status == "pending" and not case.completed_at
    assert db.get(AppSetting, "automatic_campaign").value == consent
    rec.set_preference(workflow, item["id"], "skip")
    assert (
        rec.preference(workflow.store, item["id"], datetime.now(UTC) + timedelta(days=100))
        == "skip"
    )
    rec.set_preference(workflow, item["id"], "restore")
    assert rec.preference(workflow.store, item["id"]) == ""


def test_outstanding_work_deduplicated_without_artificial_deadline_priority(workflow):
    db = workflow.session
    cases = []
    for index in range(3):
        broker = Broker(
            slug=f"attention-{index}", name=f"Synthetic {index}", domain=f"{index}.test"
        )
        db.add(broker)
        db.flush()
        case = Case(broker_id=broker.id, state="done" if index == 2 else "needs_action")
        db.add(case)
        db.flush()
        cases.append(case)
        db.add(
            Approval(
                case_id=case.id,
                kind="form_required",
                summary="Complete verification",
                encrypted_payload=workflow.store.vault.encrypt({'body': 'Please use our form.'}),
                expires_at=datetime.now(UTC) + timedelta(hours=3 - index),
            )
        )
    db.add(
        IncomingMessage(
            id="synthetic-reply",
            case_id=cases[0].id,
            status="review",
            encrypted_payload=workflow.store.vault.encrypt({}),
        )
    )
    db.commit()
    rows = rec.attention_items(workflow)
    assert len(rows) == 2
    assert [r["name"] for r in rows] == ["Synthetic 0", "Synthetic 1"]


def test_read_only_views_and_country_changes_preserve_sending_authority(tmp_path, master_key):
    import re

    engine = create_db_engine(f"sqlite:///{tmp_path / 'recommendations.db'}")
    settings = Settings(
        _env_file=None,
        master_key=master_key,
        password_hash=hash_password("synthetic password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        assert (
            client.post(
                "/recommendations/country", data={"csrf": "bad", "country": "US"}
            ).status_code
            == 401
        )
        client.post("/login", data={"password": "synthetic password"})
        with Session(engine) as db:
            before = list(db.execute(select(AppSetting.key, AppSetting.value)))
        html = client.get("/dashboard").text
        csrf = re.search(r'name="csrf" value="([^"]+)"', html)[1]
        assert "Add your country in Profile" in html
        assert 'id="action-country"' not in html
        profile = client.get('/onboarding').text
        assert '<h1>Profile</h1>' in profile
        assert 'id="action-country"' in profile
        assert 'Why we ask for your country' in profile
        assert 'Optional professional details — unlock more business databases' not in profile
        assert 'Optional address and other matching details' not in profile
        client.get("/quick-wins")
        client.get("/cases?view=attention")
        with Session(engine) as db:
            assert list(db.execute(select(AppSetting.key, AppSetting.value))) == before
        assert (
            client.post(
                "/recommendations/country", data={"csrf": "bad", "country": "US"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/recommendations/country", data={"csrf": csrf, "country": "not-country"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/recommendations/country", data={"csrf": csrf, "country": "US"}
            ).status_code
            == 200
        )
        with Session(engine) as db:
            assert db.get(AppSetting, "automatic_campaign") is None
            assert not list(db.scalars(select(Job).where(Job.kind == "submit_case")))
        international_setup = client.get("/onboarding").text
        assert "Manual actions are available for United States" in international_setup
        assert 'name="signature"' not in international_setup
        international_plan = client.get("/campaign").text
        assert "Automatic emails are not yet supported for United States" in international_plan
        assert 'action="/campaign/automatic"' not in international_plan
        assert (
            client.post(
                "/onboarding",
                data={
                    "csrf": csrf,
                    "full_name": "Synthetic",
                    "email": "test@example.test",
                    "signature": "Synthetic",
                },
            ).status_code
            == 422
        )
        assert (
            client.post("/recommendations/no-such-item/skip", data={"csrf": csrf}).status_code
            == 404
        )
        assert client.post("/recommendations/leadiq/bogus", data={"csrf": csrf}).status_code == 422
        # Country lives in Profile, including for existing users. It updates previews,
        # never the authorization for an already approved email campaign.
        with Session(engine) as db:
            store = Store(db, Vault(master_key))
            store.set_setting('automatic_campaign', {'enabled': True, 'country': 'FR'}, encrypted=True)
        response = client.post('/recommendations/country', data={
            'csrf': csrf, 'country': 'DE', 'return_to': '/onboarding',
        })
        assert response.url.path == '/onboarding'
        assert 'value="DE" selected' in response.text
        plan = client.get('/campaign').text
        assert '<dt>Country</dt><dd>Germany' in plan
        assert '<select name="country">' not in plan
        with Session(engine) as db:
            assert campaign.consent(Store(db, Vault(master_key))) == {'enabled': True, 'country': 'FR'}
    engine.dispose()


def test_in_progress_forms_and_stale_evidence_are_not_new_tasks(workflow, monkeypatch):
    first = rec.session_items(workflow)[0]
    broker = Broker(slug="already-sent", name="Synthetic", domain=first["domains"][0])
    workflow.session.add(broker)
    workflow.session.flush()
    workflow.session.add(Case(broker_id=broker.id, state="submitted"))
    workflow.session.commit()
    assert not next(i for i in rec.action_items(workflow) if i["id"] == first["id"])["selectable"]
    from erasure.quick_wins import checklist

    rows = checklist(workflow.settings, workflow.store)
    for row in rows:
        row["fresh"] = False
        row["checked_at"] = "2000-01-01"
    monkeypatch.setattr(rec, "checklist", lambda *_: rows)
    assert rec.session_items(workflow) == []
