from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import Approval, Broker, Case, Event, IncomingMessage, Job, Profile
from erasure.store import Store
from erasure.workflow import Workflow, case_token

ROOT = Path(__file__).parents[1]


def test_erase_brand_on_login_setup_and_app_pages(tmp_path, master_key):
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('branding password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f'sqlite:///{tmp_path}/branding.db')
    with TestClient(create_app(settings, engine)) as client:
        assert client.app.title == 'erase'
        assert '<h1>erase</h1>' in client.get('/login').text
        client.post('/login', data={'password': 'branding password'})
        with Session(engine) as session:
            broker = Broker(slug='branding-example', name='Example Broker', domain='example.test')
            session.add(broker)
            session.flush()
            case = Case(broker_id=broker.id, state='candidate')
            session.add(case)
            session.commit()
            case_id = case.id
        for route in ['/login', '/setup', '/dashboard', '/cases', '/brokers',
                      '/onboarding', '/campaign', '/appearance', '/quick-wins',
                      '/design-preview', f'/cases/{case_id}']:
            response = client.get(route)
            assert response.status_code == 200, route
            title = re.search(r'<title>(.*?)</title>', response.text)[1]
            assert 'erase' in title, (route, title)
            assert 'Personal Erasure' not in response.text, route
        dashboard = client.get('/dashboard').text
        assert 'aria-label="erase overview"' in dashboard
        assert '<span>erase</span>' in dashboard
        assert '>erase</a>' in client.get('/setup').text
    engine.dispose()


def test_simplified_overview_groups_done_and_separates_candidates(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'overview.db'}")
    settings = Settings(
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
            for index, state in enumerate(["done", "removed", "candidate", "not_found"]):
                broker = Broker(
                    slug=f"overview-{index}",
                    name=f"Overview Test {index}",
                    domain=f"test{index}.invalid",
                )
                session.add(broker)
                session.flush()
                session.add(Case(broker_id=broker.id, state=state))
            session.flush()
            sent_case = session.scalar(select(Case).join(Broker).where(Broker.domain == 'test0.invalid'))
            manual_case = session.scalar(select(Case).join(Broker).where(Broker.domain == 'test1.invalid'))
            session.add_all([
                Event(case_id=sent_case.id, kind='submitted', summary='Initial request'),
                Event(case_id=sent_case.id, kind='submitted', summary='Scheduled recheck'),
                Event(case_id=manual_case.id, kind='form_submitted', summary='User completed a form'),
            ])
            session.commit()
            sent_case_id = sent_case.id
        html = client.get("/cases?state=done").text
        assert "Overview Test 0" in html and "Overview Test 1" in html
        assert "Overview Test 3" in html
        assert "Overview Test 2" not in client.get("/cases").text
        # Research-only records are retained, but not offered in the usable library.
        assert "Overview Test 2" not in client.get("/brokers?q=Overview").text
        assert "No matching brokers" in client.get("/brokers?q=Overview").text
        assert 'value="removed"' not in html
        dashboard = client.get("/dashboard").text
        assert '<h1>Dashboard</h1>' in dashboard
        assert 'Leave less behind.' not in dashboard
        assert 'Your privacy, in progress' not in dashboard
        assert 'Emails handled for you.' not in dashboard
        assert dashboard.index('aria-label="Campaign status"') < dashboard.index('aria-label="Request progress"')
        assert dashboard.index('aria-label="Request progress"') < dashboard.index('aria-label="Broker showcase"')
        assert dashboard.index('aria-label="Campaign status"') < dashboard.index('class="completion-trend"')
        assert dashboard.index('class="completion-trend"') < dashboard.index('aria-label="Request progress"')
        assert dashboard.index('aria-label="Broker showcase"') < dashboard.index('class="dashboard-columns"')
        assert dashboard.count('aria-label="Broker showcase"') == 1
        assert dashboard.count('class="completion-trend"') == 1
        assert 'What happened recently' not in dashboard
        assert 'What these numbers mean' not in dashboard
        assert 'Last successful mailbox check' not in dashboard
        assert 'Right now' not in dashboard
        assert 'class="nav-group"' not in dashboard
        assert 'href="/quick-wins"' not in dashboard.split("<main")[0]
        assert "<th>Attempts</th>" not in dashboard
        assert "Deletion reported" not in dashboard
        assert 'class="result-summary"' not in dashboard
        assert 'aria-label="Recently updated requests"' in dashboard
        assert '<table' not in dashboard
        assert f'class="recent-request" href="/cases/{sent_case_id}"' in dashboard
        assert 'id="gmail-connection"' in dashboard
        assert 'data-connected="false" href="/gmail/connect"' in dashboard
        assert 'href="/batch">Review a batch manually</a>' not in dashboard
        assert 'href="/setup">Continue setup</a>' in dashboard
        assert '>Home</a>' in dashboard and '>Replies</a>' not in dashboard.split('<main')[0]
        assert '<strong id="sent-request-count">1</strong>' in dashboard
        assert '<strong id="completed-request-count">3</strong>' in dashboard
        sent = client.get('/cases?view=sent').text
        assert 'Overview Test 0' in sent
        assert 'Overview Test 1' not in sent and 'Overview Test 3' not in sent
        assert ">No record found<" not in dashboard
        batch = client.get("/batch").text
        empty = client.post("/batch", data={"csrf": csrf_from(batch)})
        assert empty.status_code == 200
        assert "Select at least one request." in empty.text
        assert empty.url.path == "/batch"
        assert "No chat agent or repeated batch selection" in batch
        assert "Opening this page sends nothing" in batch


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf" value="([a-f0-9]+)"', html)
    match = match or re.search(r'name="csrf-token" content="([a-f0-9]+)"', html)
    assert match
    return match.group(1)


def test_broker_tabs_include_held_mail_without_duplicate_messages(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'broker-tabs.db'}")
    settings = Settings(_env_file=None, master_key=master_key, password_hash=hash_password("test password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog")
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            broker = Broker(slug="tabs-test", name="Tabs Broker", domain="tabs.test", category="people_search")
            session.add(broker)
            session.flush()
            case = Case(broker_id=broker.id, state="needs_action", submitted_at=datetime.now(UTC))
            session.add(case)
            session.flush()
            cid = case.id
            store = Store(session, Vault(master_key))
            store.add_event(cid, "request_prepared", "Draft", {"body": "Original sent request", "destination": "privacy@tabs.test"})
            store.add_event(cid, "submitted", "Request sent")
            message = {"id": "held-123", "message_id": "<held@tabs.test>", "from": "privacy@tabs.test",
                       "subject": "Your request", "body": "A visible held message", "authentication_results": "missing"}
            session.add(IncomingMessage(id=message["id"], case_id=cid, status="processed", encrypted_payload=store.vault.encrypt(message)))
            store.add_event(cid, "reply_held", "Held", {"message_id": message["message_id"], "reason": "Authentication missing"})
            session.add(Approval(case_id=cid, kind="unverified_sender", summary="Sender review",
                                 encrypted_payload=store.vault.encrypt({"message": message, "reason": "Authentication missing"})))
            store.add_event(cid, "form_submitted", "You submitted the broker form", {"message": message})
            session.commit()
        overview = client.get(f"/cases/{cid}").text
        assert 'aria-label="Request sections"' in overview
        assert "Public people search" in overview
        assert '<summary>' not in overview.split('<main', 1)[1]
        assert "Choose an outcome" not in overview
        conversation = client.get(f"/cases/{cid}?tab=conversation").text
        assert conversation.count("A visible held message") == 1
        assert "Original sent request" in conversation
        assert "You submitted the broker form" in conversation
        assert "Sender not verified" in conversation
        assert "No replies recorded yet" not in conversation
        details = client.get(f"/cases/{cid}?tab=details").text
        assert "Information disclosed" in details and "Full audit history" in details
        assert "Authentication missing" in details
        assert client.get(f"/cases/{cid}?tab=unknown").status_code == 200
        with Session(engine) as session:
            incoming = session.get(IncomingMessage, "held-123")
            message["body"] = ""
            incoming.encrypted_payload = Vault(master_key).encrypt(message)
            approval = session.scalar(select(Approval).where(Approval.case_id == cid))
            approval.encrypted_payload = Vault(master_key).encrypt({"message": message})
            session.commit()
        missing = client.get(f"/cases/{cid}?tab=conversation").text
        assert "Message content is unavailable" in missing
        assert "No replies recorded yet" not in missing
        assert "Choose an outcome" not in client.get(f"/cases/{cid}").text
    engine.dispose()


def test_request_filters_share_table_and_filter_actionable_cases(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'request-filters.db'}")
    settings = Settings(_env_file=None, master_key=master_key, password_hash=hash_password('test password'),
        session_secret=generate_session_secret(), templates_dir=ROOT / 'templates',
        static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    with TestClient(create_app(settings, engine)) as client:
        client.post('/login', data={'password': 'test password'})
        with Session(engine) as session:
            for index, (name, state, body) in enumerate([
                ('Action Alpha', 'needs_action', 'Complete our form.'),
                ('Action Beta', 'needs_action', 'Complete our form.'),
                ('Hidden internal issue', 'needs_action', ''),
                ('Waiting broker', 'submitted', ''),
                ('Completed broker', 'done', 'Complete our form.'),
            ]):
                broker = Broker(slug=f'filter-{index}', name=name, domain=f'filter-{index}.test')
                session.add(broker)
                session.flush()
                case = Case(broker_id=broker.id, state=state)
                session.add(case)
                session.flush()
                session.add(Approval(case_id=case.id, kind='form_required', summary='Complete the form',
                    encrypted_payload=Vault(master_key).encrypt({'body': body})))
            session.commit()
        all_page = client.get('/cases').text
        attention = client.get('/cases?view=attention').text
        for route in ['/cases?view=attention', '/cases?state=waiting', '/cases?state=done']:
            page = client.get(route).text
            assert page.split('<thead>')[1].split('</thead>')[0] == all_page.split('<thead>')[1].split('</thead>')[0]
            assert '<section class="card table-card"><div class="table-wrap"><table data-sortable>' in page
            assert 'Continue request →' not in page
        assert '2 requests</span>' in attention
        assert 'Action Alpha →' in attention and 'Action Beta →' in attention
        for name in ['Hidden internal issue', 'Waiting broker', 'Completed broker']:
            assert f'{name} →' not in attention
        assert '1 request</span>' in client.get('/cases?view=attention&q=ALPHA').text
        assert 'Action Beta →' not in client.get('/cases?view=attention&q=ALPHA').text
        assert 'No requests match this filter.' in client.get('/cases?view=attention&q=unknown').text
        assert '2 requests</span>' in client.get('/cases?view=attention&state=done').text
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Approval).where(Approval.status == 'pending')) == 5
            assert session.scalar(select(func.count()).select_from(Event)) == 0
    engine.dispose()


def test_request_page_contains_action_message_and_preserves_failed_reply(tmp_path, master_key):
    from erasure.inbox import capture_message

    engine = create_db_engine(f"sqlite:///{tmp_path / 'unified-request.db'}")
    settings = Settings(_env_file=None, master_key=master_key, password_hash=hash_password("test password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog")
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            broker = session.scalar(select(Broker))
            case = Case(broker_id=broker.id, state="submitted", submitted_at=datetime.now(UTC))
            session.add(case)
            session.flush()
            store = Store(session, Vault(master_key))
            store.save_profile({"full_name": "Test", "work_email": "work@example.test"}, "Test")
            store.set_setting("recommendation_country", "DE")
            capture_message(Workflow(session, store, settings), {
                "id": "needs-work-email", "subject": case_token(case.id),
                "body": "No matching records. Please provide your work email address and country of residence.",
                "from": broker.contact,
                "authentication_results": f"mx.google.com; dmarc=pass header.from={broker.domain}",
            })
            cid = case.id
            aid = session.scalar(select(Approval.id).where(Approval.case_id == cid))
        page = client.get(f"/cases/{cid}").text
        assert f'id="action-{aid}"' in page
        assert 'Review prepared reply' in page and 'work@example.test' in page
        assert 'Country of residence: Germany' in page
        assert f'href="/cases/{cid}?step={aid}#next-step"' in client.get('/cases?view=attention').text
        edited = "My edited reply, with [ADD city] still unfinished."
        error = client.post(f"/cases/{cid}/reply", data={"csrf": csrf_from(page),
                            "destination": "privacy@example.test", "body": edited})
        assert error.status_code == 409
        assert "text/html" in error.headers["content-type"]
        assert edited in error.text and 'name="destination" value="privacy@example.test"' in error.text
        with Session(engine) as session:
            assert session.get(Case, cid).state == 'needs_action'
            assert session.get(Approval, aid).status == 'pending'
    engine.dispose()


def test_automatic_campaign_requires_explicit_current_preview_and_can_be_stopped(
    tmp_path, master_key
):
    from erasure import campaign
    from erasure.models import RouteResearch

    engine = create_db_engine(f"sqlite:///{tmp_path / 'campaign.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/campaign", follow_redirects=False).status_code == 303
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            Store(session, Vault(master_key)).save_profile(
                {"full_name": "Test", "email": "p@example.test"}, "Test"
            )
            broker = Broker(
                slug="campaign-test",
                name="Campaign test",
                domain="example.test",
                contact="contact@example.test",
            )
            session.add(broker)
            session.flush()
            bid = broker.id
            session.add(Case(broker_id=bid, state="done"))
            session.add(RouteResearch(broker_id=bid, status="needs_review", reason="Generic inbox"))
            session.commit()
        page = client.get("/campaign").text
        assert 'name="include_new" value="true"' in page
        assert "I authorize ongoing automatic requests" in page
        csrf = csrf_from(page)
        preview = re.search(r'name="preview_hash" value="([a-f0-9]+)"', page).group(1)
        assert client.post("/campaign/automatic", data={"csrf": "bad"}).status_code == 403
        for path in ('/campaign/pause', '/campaign/resume', '/campaign/automatic/disable', '/campaign/check'):
            assert client.post(path, data={'csrf': 'bad'}).status_code == 403
        response = client.post("/campaign/automatic", data={"csrf": csrf, "preview_hash": preview})
        assert "Confirm the authorization checkbox" in response.text
        response = client.post(
            "/campaign/automatic", data={"csrf": csrf, "authorize": "true", "preview_hash": "old"}
        )
        assert "preview changed" in response.text
        client.post(
            "/campaign/automatic",
            data={"csrf": csrf, "authorize": "true", "preview_hash": preview, "daily_limit": 12,
                  "include_new": "true"},
        )
        with Session(engine) as session:
            saved = campaign.consent(Store(session, Vault(master_key)))
            assert saved["enabled"] and saved["daily_limit"] == 12
            assert saved["include_new"]
            assert session.scalar(select(Case).where(Case.broker_id == bid)).state == "done"
        assert (
            client.post(
                f"/campaign/research/{bid}/approve",
                data={"csrf": csrf, "confirmed": "true", "source_url": "http://127.0.0.1/"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"/campaign/research/{bid}/approve",
                data={
                    "csrf": csrf,
                    "confirmed": "true",
                    "source_url": "https://example.test/privacy",
                },
            ).status_code
            == 200
        )
        client.post("/campaign/automatic/disable", data={"csrf": csrf})
        stopped_resume = client.post('/campaign/resume', data={'csrf': csrf})
        assert 'Nothing has resumed.' in stopped_resume.text
        with Session(engine) as session:
            store = Store(session, Vault(master_key))
            assert not campaign.consent(store)["enabled"]
            assert store.get_setting('paused') == 'true'
            assert session.get(RouteResearch, bid).status == "manually_verified"
            store.enqueue_if_missing('poll_gmail', {})
            for job in session.scalars(select(Job).where(Job.kind.in_(['campaign_tick', 'poll_gmail']))):
                job.status = 'running'
            session.commit()
            before_jobs = list(session.scalars(select(Job.id).where(Job.kind.in_(['campaign_tick', 'poll_gmail']))))
        for _ in range(2):
            assert client.post('/campaign/check', data={'csrf': csrf}).status_code == 200
        with Session(engine) as session:
            assert list(session.scalars(select(Job.id).where(Job.kind.in_(['campaign_tick', 'poll_gmail'])))) == before_jobs
            assert not campaign.consent(Store(session, Vault(master_key)))['enabled']
        assert (
            client.post(f"/campaign/research/{bid}/complete", data={"csrf": "invalid"}).status_code
            == 403
        )
        assert (
            client.post(f"/campaign/research/{bid}/complete", data={"csrf": csrf}).status_code
            == 200
        )
        assert (
            client.post(f"/campaign/research/{bid}/complete", data={"csrf": csrf}).status_code
            == 200
        )
        with Session(engine) as session:
            assert session.scalar(select(Case).where(Case.broker_id == bid)).state == "done"
            assert session.get(RouteResearch, bid).status == "user_completed"
            assert (
                session.scalar(
                    select(func.count()).select_from(Event).where(Event.kind == "user_completed")
                )
                == 1
            )


def test_reply_action_requires_an_outcome_and_records_form_submission(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'reply-outcome.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("test reply password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test reply password"})
        with Session(engine) as session:
            broker = session.scalar(select(Broker))
            case = Case(broker_id=broker.id, state="needs_action")
            session.add(case)
            session.flush()
            action = Approval(
                case_id=case.id,
                kind="ambiguous_reply",
                summary="Review reply",
                encrypted_payload=Vault(master_key).encrypt({"body": "Please use our form"}),
            )
            session.add(action)
            session.commit()
            aid, cid = action.id, case.id
        assert 'Save outcome' not in client.get(f'/cases/{cid}').text
        html = client.get(f"/cases/{cid}?tab=details&correct=1&step={aid}").text
        assert "Save outcome" in html
        csrf = csrf_from(html)
        url = f"/actions/{aid}/resolve/approve"
        assert client.post(url, data={"csrf": csrf}).status_code == 422
        with Session(engine) as session:
            assert session.get(Case, cid).state == "needs_action"
            assert session.get(Approval, aid).status == "pending"
        assert client.post(url, data={"csrf": csrf, "outcome": "form_submitted"}).status_code == 200
        with Session(engine) as session:
            assert session.get(Case, cid).state == "processing"
            assert session.get(Case, cid).completed_at is None
            assert session.get(Approval, aid).status == "approved"
            assert session.scalar(select(Event).where(Event.kind == "form_submitted"))
            assert session.scalar(
                select(Job).where(Job.kind == "follow_up", Job.status == "pending")
            )
        assert client.post(url, data={"csrf": csrf, "outcome": "form_submitted"}).status_code == 404
        with Session(engine) as session:
            case = session.get(Case, cid)
            case.state = "not_found"
            case.completed_at = datetime.now(UTC)
            session.get(Approval, aid).status = "pending"
            session.commit()
            before = (case.state, case.completed_at, case.next_action_at)
        # A stale browser tab must not reopen a completed request or show JSON errors.
        for _ in range(2):
            response = client.post(url, data={"csrf": csrf, "outcome": "form_submitted"})
            assert response.status_code == 200
            assert response.url.path == f"/cases/{cid}"
        with Session(engine) as session:
            case = session.get(Case, cid)
            assert (case.state, case.completed_at, case.next_action_at) == before
            assert session.get(Approval, aid).status == "superseded"
    engine.dispose()


def test_email_confirmation_completion_is_explicit_and_does_not_claim_deletion(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'confirmation.db'}")
    settings = Settings(
        _env_file=None, master_key=master_key, password_hash=hash_password("test password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            broker = session.scalar(select(Broker))
            case = Case(broker_id=broker.id, state="submitted", submitted_at=datetime.now(UTC))
            session.add(case)
            session.flush()
            workflow = Workflow(session, Store(session, Vault(master_key)), settings)
            workflow.require_email_confirmation(case, {"body": "Please confirm your email."})
            aid = session.scalar(select(Approval.id).where(Approval.case_id == case.id))
            cid = case.id
        html = client.get(f"/cases/{cid}").text
        assert "I confirmed my request" in html
        csrf = csrf_from(html)
        url = f"/actions/{aid}/resolve/approve"
        assert client.post(url, data={"csrf": csrf}).status_code == 422
        with Session(engine) as session:
            assert session.get(Case, cid).state == "needs_action"
            assert session.get(Approval, aid).status == "pending"
        assert client.post(url, data={"csrf": csrf, "outcome": "email_confirmed"}).status_code == 200
        with Session(engine) as session:
            assert session.get(Case, cid).state == "processing"
            assert session.get(Case, cid).completed_at is None
            assert session.get(Approval, aid).status == "approved"
            assert session.scalar(select(Job).where(Job.kind == "follow_up", Job.status == "pending"))
            assert session.scalar(select(Event).where(Event.kind == "email_confirmation_recorded"))
        # A stale confirmation must never reopen an already-completed request.
        with Session(engine) as session:
            from erasure.inbox import capture_message

            case = session.get(Case, cid)
            workflow = Workflow(session, Store(session, Vault(master_key)), settings)
            capture_message(workflow, {
                "id": "confirmed-deletion", "subject": f"Request {case_token(cid)}",
                "body": "Your personal data has been deleted.",
                "from": case.broker.contact,
                "authentication_results": f"mx.google.com; dmarc=pass header.from={case.broker.domain}",
            })
            assert case.state == "removed"
            assert case.completed_at is not None
            session.get(Approval, aid).status = "pending"
            session.commit()
        assert client.post(url, data={"csrf": csrf, "outcome": "email_confirmed"}).status_code == 200
        with Session(engine) as session:
            assert session.get(Case, cid).state == "removed"
    engine.dispose()


def test_session_cookie_supports_google_oauth_callback(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'oauth-cookie.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is an oauth test password"),
        session_secret=generate_session_secret(),
        google_client_id="client-id",
        google_client_secret="client-secret",
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine), follow_redirects=False) as client:
        assert client.get("/gmail/connect").headers["location"] == "/login"
        assert client.get("/api/status").status_code == 401
        login = client.post("/login", data={"password": "this is an oauth test password"})
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "samesite=lax" in login.headers["set-cookie"].lower()

        connect = client.get("/gmail/connect")
        assert connect.status_code == 303
        assert connect.headers["location"].startswith("https://accounts.google.com/")
        assert "samesite=lax" in connect.headers["set-cookie"].lower()

    engine.dispose()


def test_unverified_ticket_can_be_marked_done_without_inventing_deletion(tmp_path, master_key):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'message-done.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("message done password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "message done password"})
        with Session(engine) as session:
            broker = session.scalar(select(Broker))
            case = Case(broker_id=broker.id, state="submitted")
            session.add(case)
            session.flush()
            action = Approval(
                case_id=case.id,
                kind="unverified_sender",
                summary="Ticket closed",
                encrypted_payload=Vault(master_key).encrypt(
                    {
                        "message": {"body": "Your ticket has been resolved."},
                        "previous_state": "submitted",
                    }
                ),
            )
            session.add(action)
            session.commit()
            aid, cid = action.id, case.id
        html = client.get(f"/cases/{cid}?tab=details&correct=1&step={aid}").text
        assert "Mark message done" in html and "Trust and apply reply" not in html
        response = client.post(
            f"/actions/{aid}/resolve/approve",
            data={"csrf": csrf_from(html), "outcome": "close_message"},
        )
        assert response.status_code == 200
        with Session(engine) as session:
            assert session.get(Approval, aid).status == "approved"
            assert session.get(Case, cid).state == "submitted"
            assert session.get(Case, cid).completed_at is None
    engine.dispose()


def test_responses_include_local_security_headers(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'headers.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is a header test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        response = client.get("/login")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "strict-transport-security" not in response.headers
    engine.dispose()


def test_approving_unverified_sender_applies_held_reply(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'held-reply.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is a held reply password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "this is a held reply password"})
        with Session(engine, expire_on_commit=False) as session:
            broker = session.scalar(select(Broker).where(Broker.domain != ""))
            assert broker is not None
            case = Case(broker_id=broker.id, state="submitted", submitted_at=datetime.now(UTC))
            session.add(case)
            session.commit()
            workflow = Workflow(session, Store(session, Vault(master_key)), settings)
            assert workflow.process_message(
                {
                    "subject": f"Removal complete [{case_token(case.id)}]",
                    "body": "Your personal information has been removed.",
                    "from": "privacy@lookalike.test",
                    "authentication_results": (
                        "mx.google.com; dmarc=pass header.from=lookalike.test"
                    ),
                    "message_id": "held-message",
                    "id": "gmail-held",
                }
            )
            approval = session.scalar(select(Approval).where(Approval.kind == "unverified_sender"))
            assert approval is not None
            approval_id = approval.id
            case_id = case.id

        actions = client.get("/actions")
        response = client.post(
            f"/actions/{approval_id}/resolve/approve",
            data={"csrf": csrf_from(actions.text)},
        )
        assert response.status_code == 200

        with Session(engine) as session:
            assert session.get(Approval, approval_id).status == "approved"
            assert session.get(Case, case_id).state == "removed"
            assert (
                session.scalar(
                    select(func.count()).select_from(Job).where(Job.kind == "recheck_case")
                )
                == 1
            )
    engine.dispose()


def test_approving_browser_step_schedules_follow_up(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'browser-follow-up.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is a browser action password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "this is a browser action password"})
        with Session(engine, expire_on_commit=False) as session:
            broker = session.scalar(select(Broker).where(Broker.connector_type == "browser"))
            assert broker is not None
            case = Case(broker_id=broker.id, state="needs_action")
            session.add(case)
            session.flush()
            approval = Approval(
                case_id=case.id,
                kind="browser_challenge",
                summary="Complete the broker form",
                encrypted_payload=Vault(master_key).encrypt(
                    {"action_url": "https://example.test/privacy"}
                ),
            )
            session.add(approval)
            session.commit()
            approval_id = approval.id
            case_id = case.id

        actions = client.get("/actions")
        response = client.post(
            f"/actions/{approval_id}/resolve/approve",
            data={"csrf": csrf_from(actions.text)},
        )
        assert response.status_code == 200

        with Session(engine) as session:
            case = session.get(Case, case_id)
            assert case.state == "processing"
            assert case.attempt_count == 1
            assert case.submitted_at is not None
            assert case.next_action_at is not None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.kind == "follow_up", Job.status == "pending")
                )
                == 1
            )
    engine.dispose()


def test_onboarding_and_dry_run_campaign(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'web.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is a long local password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
        live_submissions=False,
    )
    app = create_app(settings, engine)
    with TestClient(app) as client:
        assert client.get("/health").json()["configured"] is True
        response = client.post("/login", data={"password": "this is a long local password"})
        assert response.url.path == "/setup"
        onboarding = client.get("/onboarding")
        csrf = csrf_from(onboarding.text)
        response = client.post(
            "/onboarding",
            data={
                "csrf": csrf,
                "full_name": "Private Test",
                "email": "privacy@example.test",
                "postal_address": "Secret Street 1",
                "signature": "Private Test",
                "alert_email": "alerts@example.test",
            },
        )
        assert response.url.path == "/dashboard"
        dashboard = client.get("/dashboard")
        assert "Private Test" not in dashboard.text
        with Session(engine) as session:
            eligible_ids = set()
            for broker in session.scalars(select(Broker)):
                metadata = json.loads(broker.required_fields or "{}")
                if broker.active and isinstance(metadata, dict) and metadata.get("default_confidence", 35) >= 60:
                    eligible_ids.add(broker.id)
            radaris = session.scalar(select(Broker).where(Broker.domain == "radaris.com"))
            assert radaris is not None and not radaris.active
            assert radaris.id not in eligible_ids
        assert eligible_ids
        response = client.post("/campaign/start", data={"csrf": csrf_from(dashboard.text)})
        assert response.url.path == "/dashboard"
        status = client.get("/api/status").json()
        assert status["counts"]["brokers"] >= 10
        assert status["counts"]["queued"] == len(eligible_ids)
        assert status["live_submissions"] is False

        with Session(engine, expire_on_commit=False) as session:
            assert set(session.scalars(select(Case.broker_id).where(Case.state == "queued"))) == eligible_ids
            assert session.scalar(select(Case).where(Case.broker_id == radaris.id)) is None
            case = session.scalar(select(Case).order_by(Case.id))
            approval = Approval(
                case_id=case.id,
                kind="identity_proof",
                summary="Broker requested identity proof",
                encrypted_payload=Vault(master_key).encrypt(
                    {"from": "privacy@broker.test", "subject": "Verify request", "body": "Please provide proof of identity."}
                ),
            )
            session.add(approval)
            session.commit()
            approval_id = approval.id
            identity_case_id = case.id

        actions = client.get(f"/cases/{identity_case_id}")
        assert "Handle this in email" in actions.text
        assert 'type="file"' not in actions.text
        response = client.post(
            f"/actions/{approval_id}/identity",
            data={"csrf": csrf_from(actions.text)},
            files={"document": ("redacted-id.pdf", b"%PDF-redacted", "application/pdf")},
        )
        assert response.status_code == 409, response.text
        actions = client.get(f"/cases/{identity_case_id}")
        assert "Send redacted identity document" not in actions.text
        assert (
            client.post(
                f"/actions/{approval_id}/resolve/approve",
                data={"csrf": csrf_from(actions.text)},
            ).status_code
            == 409
        )

        with Session(engine) as session:
            stored = session.get(Approval, approval_id)
            assert b"%PDF-redacted" not in stored.encrypted_payload.encode()
            payload = Store(session, Vault(master_key)).vault.decrypt(stored.encrypted_payload)
            assert "artifact" not in payload

    with Session(engine) as session:
        assert session.get(Profile, 1).encrypted_data.find("Private Test") == -1
        assert session.scalar(select(func.count()).select_from(Case)) >= 420
    engine.dispose()


def test_csrf_rejects_mutation(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'csrf.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is another long password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "this is another long password"})
        assert client.post("/campaign/pause", data={"csrf": "wrong"}).status_code == 403
    engine.dispose()


def test_prepared_case_can_be_queued_once_only_in_live_mode(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'prepared-case.db'}")
    common = {
        "master_key": master_key,
        "password_hash": hash_password("this is a canary test password"),
        "session_secret": generate_session_secret(),
        "templates_dir": ROOT / "templates",
        "static_dir": ROOT / "static",
        "catalog_dir": ROOT / "catalog",
    }
    with TestClient(create_app(Settings(**common, live_submissions=False), engine)) as client:
        client.post("/login", data={"password": "this is a canary test password"})
        with Session(engine) as session:
            broker = session.scalar(select(Broker).limit(1))
            assert broker is not None
            broker.last_validated_at = datetime.now(UTC)
            case = Case(broker_id=broker.id, state="prepared")
            session.add(case)
            session.flush()
            session.add(
                Event(
                    case_id=case.id,
                    kind="request_prepared",
                    summary="Request payload prepared",
                    encrypted_payload=Vault(master_key).encrypt(
                        {
                            "destination": "privacy@example.test",
                            "subject": "Deletion request",
                            "body": "Hello local preview",
                            "disclosed_fields": ["full_name", "email"],
                        }
                    ),
                )
            )
            session.commit()
            case_id = case.id
        cases = client.get("/cases?state=prepared")
        assert ">Send<" not in cases.text
        detail = client.get(f"/cases/{case_id}?tab=details")
        assert "Hello local preview" in detail.text
        assert "full name" in detail.text
        assert (
            client.post(
                f"/cases/{case_id}/schedule", data={"csrf": csrf_from(cases.text)}
            ).status_code
            == 409
        )

    with TestClient(create_app(Settings(**common, live_submissions=True), engine)) as client:
        client.post("/login", data={"password": "this is a canary test password"})
        cases = client.get("/cases?state=prepared")
        assert ">Send<" not in cases.text
        assert ">Send request<" in client.get(f"/cases/{case_id}").text
        csrf = csrf_from(cases.text)
        assert client.post(f"/cases/{case_id}/schedule", data={"csrf": csrf}).status_code == 200
        assert client.post(f"/cases/{case_id}/schedule", data={"csrf": csrf}).status_code == 200
        with Session(engine) as session:
            assert session.get(Case, case_id).state == "queued"
            assert (
                session.scalar(
                    select(func.count()).select_from(Job).where(Job.kind == "submit_case")
                )
                == 1
            )

    engine.dispose()


def test_batch_only_queues_recently_validated_prepared_email_cases(tmp_path, master_key) -> None:  # type: ignore[no-untyped-def]
    engine = create_db_engine(f"sqlite:///{tmp_path / 'batch.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is a batch test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
        live_submissions=True,
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "this is a batch test password"})
        with Session(engine) as session:
            # Do not assume real catalog routes remain email-sendable as research
            # establishes mandatory forms or regional restrictions.
            brokers = [
                Broker(slug=f"batch-fixture-{i}", name=f"Batch fixture {i}",
                       domain=f"batch-{i}.example.test", connector_type="email",
                       contact=f"privacy@batch-{i}.example.test")
                for i in range(2)
            ]
            session.add_all(brokers)
            session.flush()
            brokers[0].last_validated_at = datetime.now(UTC)
            cases = [Case(broker_id=broker.id, state="prepared") for broker in brokers]
            session.add_all(cases)
            session.commit()
            valid_id, stale_id = (case.id for case in cases)

        page = client.get("/batch")
        assert str(valid_id) in page.text
        assert f'value="{stale_id}"' not in page.text
        csrf = csrf_from(page.text)
        rejected = client.post(
            "/batch",
            data={"csrf": csrf, "case_ids": [valid_id, stale_id]},
        )
        assert rejected.status_code == 409
        with Session(engine) as session:
            assert session.get(Case, valid_id).state == "prepared"
            assert session.scalar(select(func.count()).select_from(Job)) == 0

        queued = client.post("/batch", data={"csrf": csrf, "case_ids": [valid_id]})
        assert queued.status_code == 200
        with Session(engine) as session:
            assert session.get(Case, valid_id).state == "queued"
            assert session.scalar(select(func.count()).select_from(Job)) == 1

    engine.dispose()
