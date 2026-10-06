"""Fresh-user journey through the real UI and controller, with synthetic Gmail only."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure import campaign
from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.inbox import capture_message
from erasure.models import AutomaticDelivery, Broker, Case, IncomingMessage
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


def hidden(html, name):
    return re.search(rf'name="{name}" value="([^"]+)"', html).group(1)


def test_new_user_can_approve_progress_review_complete_and_restart(tmp_path, master_key, monkeypatch):
    settings = Settings(
        _env_file=None, master_key=master_key, password_hash=hash_password("synthetic password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog", live_submissions=True,
    )
    engine = create_db_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    sent = []

    def send(_client, plan):
        sent.append(plan)
        return f"gmail-thread:synthetic-{len(sent)}"

    monkeypatch.setattr("erasure.gmail.GmailClient.send", send)
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "synthetic password"})
        setup = client.get("/onboarding").text
        assert 'name="postal_address" required' not in setup
        response = client.post("/onboarding", data={
            "csrf": hidden(setup, "csrf"), "full_name": "Synthetic Person",
            "email": "request@example.test", "other_emails": "matching@example.test",
            "work_email": "work@example.test", "employer": "Synthetic Company",
            "signature": "Synthetic Person", "alert_email": "alerts@example.test",
        })
        assert response.status_code == 200 and response.url.path == "/dashboard"
        with Session(engine) as session:
            store = Store(session, Vault(master_key))
            assert store.get_profile()["postal_address"] == ""
            assert store.get_profile()["employer"] == "Synthetic Company"
            store.set_setting("gmail_token", {"access_token": "synthetic"}, encrypted=True)
            expected = sum(bool(row["plan"]) for row in campaign.preview_rows(
                Workflow(session, store, settings), "DE", False))
        assert expected >= 25
        page = client.get("/campaign?country=DE").text
        assert "What runs automatically" in page
        assert "Forms you can finish yourself" not in page
        assert "Synthetic Company" in page
        response = client.post("/campaign/automatic", data={
            "csrf": hidden(page, "csrf"), "preview_hash": hidden(page, "preview_hash"),
            "authorize": "true", "country": "DE", "daily_limit": "20",
        })
        assert response.status_code == 200
        with Session(engine, expire_on_commit=False) as session:
            workflow = Workflow(session, Store(session, Vault(master_key)), settings)
            # Cover the whole approved catalog, not a fixed number of ten-item
            # preparation cycles. Simulate midnight when the daily budget is used.
            for _ in range(expected + 1):
                campaign.tick(workflow)
                for delivery in session.scalars(select(AutomaticDelivery)):
                    campaign.dispatch(workflow, delivery.id)
                assert campaign.attempted_today(session) <= 20
                if len(sent) == expected:
                    break
                if campaign.attempted_today(session) == 20:
                    for delivery in session.scalars(select(AutomaticDelivery)):
                        if delivery.started_at:
                            delivery.started_at = datetime.now(UTC) - timedelta(days=1)
                    session.commit()
            assert len(sent) == expected
            assert len({plan.destination for plan in sent}) == expected
            case = session.scalar(select(Case).where(Case.state == "submitted"))
            completed_id = case.id
            capture_message(workflow, {
                "id": "synthetic-deleted", "from": case.broker.contact,
                "subject": "Deletion complete", "body": "Your personal data has been deleted.",
                "thread_id": case.external_reference.removeprefix("gmail-thread:"),
                "authentication_results": f"mx.google.com; dmarc=pass header.from={case.broker.domain}",
            })
            assert case.state == "removed"
            assert session.get(IncomingMessage, "synthetic-deleted") is not None
        wins = client.get("/quick-wins?view=all").text
        assert "Steps and what you’ll need" in wins
        assert "complete live form has not been tested" in wins
        client.post("/quick-wins/bookyourdata", data={"csrf": hidden(wins, "csrf")})
        with Session(engine) as session:
            case = session.scalar(select(Case).join(Broker).where(Broker.domain == "bookyourdata.com"))
            assert case.state == "done"
            form_id = case.id
        assert f'href="/cases/{form_id}"' in client.get("/cases?state=done").text

    # Reloading catalog and app state must not reopen outcomes or resend initials.
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "synthetic password"})
        with Session(engine, expire_on_commit=False) as session:
            workflow = Workflow(session, Store(session, Vault(master_key)), settings)
            campaign.tick(workflow)
            for delivery in session.scalars(select(AutomaticDelivery)):
                campaign.dispatch(workflow, delivery.id)
            assert len(sent) == expected
            assert session.get(Case, completed_id).state == "removed"
            assert session.get(Case, form_id).state == "done"
        for url in ("/dashboard", "/campaign", "/actions", "/inbox", "/quick-wins", "/brokers"):
            assert client.get(url).status_code == 200
    engine.dispose()
