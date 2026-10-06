from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import Approval, Broker, Case, IncomingMessage
from erasure.store import Store

ROOT = Path(__file__).parents[1]


def test_home_and_requests_offer_independent_actions_and_one_navigation(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'simple.db'}")
    settings = Settings(
        _env_file=None,
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            store = Store(session, Vault(master_key))
            store.set_setting("recommendation_country", "DE")
            store.set_setting("gmail_last_sync", datetime.now(UTC).isoformat())
            for i in range(5):
                broker = Broker(
                    slug=f"queue-{i}", name=f"Queue Broker {i}", domain=f"queue{i}.test"
                )
                session.add(broker)
                session.flush()
                case = Case(broker_id=broker.id, state="needs_action" if i < 4 else "submitted")
                session.add(case)
                session.flush()
                if i < 4:
                    session.add(
                        Approval(
                            case_id=case.id,
                            kind="form_required",
                            summary="Complete form",
                            encrypted_payload=store.vault.encrypt(
                                {
                                    "body": "Please use our form",
                                    "action_url": f"https://queue{i}.test/remove",
                                }
                            ),
                        )
                    )
            session.commit()
            before = list(session.execute(select(Case.id, Case.state)))
        home = client.get("/dashboard").text
        assert "4 requests need you" in home
        assert home.count('class="quick-win"') == 3
        assert "Email activity and controls" not in home
        assert 'class="quick-check"' not in home
        assert home.count('class="quick-win-buttons"') == 3
        assert 'aria-label="About quick wins"' in home
        assert "Some routes suppress marketing rather than delete a record" not in home
        assert "Done records your completed step—not a broker’s deletion confirmation" not in home
        assert "Work contact details" not in home
        assert "Last successful mailbox check" not in home
        assert 'id="gmail-connection"' in home
        assert home.index('id="completion-trend-title"') < home.index('aria-label="Request progress"') < home.index('aria-label="Broker showcase"') < home.index('id="quick-wins"')
        assert client.get('/api/status').json()['attention_count'] == 4
        assert "Finish these before starting optional" not in home
        waiting = client.get("/cases?state=waiting").text
        assert "Queue Broker 4" in waiting and "Queue Broker 0" not in waiting
        searched = client.get("/cases?q=Queue%20Broker%202").text
        assert "Queue Broker 2" in searched and "Queue Broker 1" not in searched
        assert (
            client.get("/actions", follow_redirects=False).headers["location"]
            == "/cases?view=attention"
        )
        assert (
            client.get("/inbox", follow_redirects=False).headers["location"] == "/cases?view=mail"
        )
        with Session(engine) as session:
            assert list(session.execute(select(Case.id, Case.state))) == before
    engine.dispose()


def test_linking_unmatched_mail_does_not_certify_sender(db, vault):
    from erasure.inbox import review_message
    from erasure.workflow import Workflow

    broker = Broker(
        slug="linked", name="Linked", domain="linked.test", contact="privacy@linked.test"
    )
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id, state="submitted")
    db.add(case)
    db.flush()
    message = IncomingMessage(
        id="unknown",
        encrypted_payload=vault.encrypt(
            {
                "id": "unknown",
                "body": "Your data has been deleted.",
                "subject": "Deletion",
                "from": "someone@different.test",
            }
        ),
    )
    db.add(message)
    db.commit()
    review_message(Workflow(db, Store(db, vault), Settings()), message, case.id, "link")
    assert message.case_id == case.id and case.state == "submitted"
    assert case.completed_at is None


def test_automation_status_exposes_stale_checks_and_specific_recovery(db, vault):
    from datetime import timedelta

    from erasure.attention import automation_summary

    store = Store(db, vault)
    pipeline = {"automatic": {"enabled": True}}
    assert automation_summary(store, pipeline, True)["control"] == "connect"
    store.set_setting("gmail_token", {"access_token": "synthetic"}, encrypted=True)
    store.set_setting("gmail_last_sync", (datetime.now(UTC) - timedelta(hours=4)).isoformat())
    assert automation_summary(store, pipeline, True)["control"] == "check"
    store.set_setting("paused", "true")
    assert automation_summary(store, pipeline, True)["control"] == "resume"
    store.set_setting("paused", "false")
    store.set_setting("gmail_last_sync", datetime.now(UTC).isoformat())
    assert automation_summary(store, pipeline, True)["state"] == "starting"
    pipeline['automatic']['last_tick'] = datetime.now(UTC).isoformat()
    assert automation_summary(store, pipeline, True)["state"] == "running"
    assert automation_summary(store, pipeline, False)["control"] == "plan"
    pipeline['automatic']['problem'] = 'Identity or request template changed'
    assert automation_summary(store, pipeline, True)['control'] == 'review'
    pipeline['automatic']['problem'] = 'Campaign checks delayed; check that the local app is running'
    assert automation_summary(store, pipeline, True)['control'] == 'check'
    pipeline['automatic']['enabled'] = False
    store.set_setting('paused', 'true')
    assert automation_summary(store, pipeline, True)['state'] == 'stopped'
    assert automation_summary(store, pipeline, True)['can_stop'] is False
