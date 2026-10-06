"""Priority coverage means country-specific app routes, never proven deletion."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure import knowledge, major_brokers, quick_wins, recommendations
from erasure.app import create_app
from erasure.broker_library import library_rows
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import Broker, Case, Event, Job
from erasure.store import Store
from erasure.workflow import Workflow

ROOT = Path(__file__).parents[1]


@pytest.fixture
def settings():
    return Settings(_env_file=None, catalog_dir=ROOT / "catalog")


def test_fixed_checklist_keeps_unknown_and_country_gaps(settings):
    report = major_brokers.coverage(settings)
    assert report["family_count"] == 34
    assert report["families_with_any_route"] == 31
    assert report["families_with_all_declared_routes"] == 28
    assert not report["all_routes_wired"]
    families = {f["id"]: f for f in report["families"]}
    assert {f["id"] for f in families.values() if f["status"] == "gap"} == {
        "nuwber",
        "radaris",
        "peekyou",
    }
    for name in ("beenverified", "data-axle", "circana"):
        assert families[name]["status"] == "partial"
        checks = {c["country"]: c for c in families[name]["checks"]}
        assert checks["DE"]["mode"] == "automatic_email"
        assert checks["US"]["mode"] is None
        assert checks["GB"]["mode"] is None
    assert "not live form completion" in report["limit"]


def test_missing_checklist_is_not_complete(tmp_path):
    report = major_brokers.coverage(Settings(_env_file=None, catalog_dir=tmp_path))
    assert not report["declared"] and not report["all_routes_wired"]


@pytest.mark.parametrize("duplicate", ["family", "country"])
def test_checklist_rejects_double_counting(settings, duplicate):
    raw = major_brokers.checklist(settings).model_dump()
    if duplicate == "family":
        raw["families"].append(raw["families"][0])
    else:
        raw["families"][0]["routes"][0]["countries"].append("DE")
    with pytest.raises(ValidationError, match="repeats"):
        major_brokers.Checklist.model_validate(raw)


@pytest.mark.parametrize("failure", ["missing_action", "stale_guide", "wrong_country"])
def test_audit_checks_real_wiring_and_freshness(settings, monkeypatch, failure):
    original_resources = quick_wins.resources
    original_guides = knowledge.guides
    if failure == "stale_guide":

        def stale(s):
            result = [g.model_copy(deep=True) for g in original_guides(s)]
            for guide in result:
                if guide.id == "whitepages":
                    guide.evidence[0].checked_on = date(2020, 1, 1)
            return result

        monkeypatch.setattr(knowledge, "guides", stale)
    else:

        def changed(s):
            result = original_resources(s)
            if failure == "missing_action":
                result["items"] = [i for i in result["items"] if i.get("guide_id") != "whitepages"]
            else:
                for item in result["items"]:
                    if item.get("guide_id") == "whitepages":
                        item["regions"] = ["GB"]
            return result

        monkeypatch.setattr(quick_wins, "resources", changed)
    row = next(f for f in major_brokers.coverage(settings)["families"] if f["id"] == "whitepages")
    assert row["status"] == "gap"
    assert row["checks"][0]["mode"] is None


def test_personal_email_actions_use_exact_mailboxes_and_placeholder_drafts(settings):
    guides = {g.id: g for g in knowledge.guides(settings)}
    items = {i["id"]: i for i in quick_wins.resources(settings)["items"]}
    for key in (
        "caci-uk",
        "numberly-personal-request",
        "weborama-identifiers",
        "zeotap-data-identifiers",
    ):
        item = items[key]
        url = urlsplit(item["url"])
        assert url.scheme == "mailto"
        assert url.path == guides[item["guide_id"]].removal.destination
        query = parse_qs(url.query)
        assert set(query) == {"subject", "body"}
        assert "[" in query["body"][0] and "]" in query["body"][0]
        assert item["link_label"] == "Open email"
    encoded = quick_wins.action_url("privacy@example.test", "Text & recipient?\nNext line")
    assert "\n" not in encoded
    assert parse_qs(urlsplit(encoded).query)["body"] == ["Text & recipient?\nNext line"]


def test_shared_optout_only_completes_exact_ten_sites(settings, db, vault):
    item = next(
        i for i in quick_wins.resources(settings)["items"] if i["id"] == "fastpeoplesearch-family"
    )
    assert len(set(item["domains"])) == 10
    for domain in [*item["domains"], "unrelated.example"]:
        db.add(Broker(slug=domain, name=domain, domain=domain))
    db.commit()
    workflow = Workflow(db, Store(db, vault), settings)
    quick_wins.mark_done(workflow, item)
    quick_wins.mark_done(workflow, item)
    cases = list(db.scalars(select(Case)))
    assert {c.broker.domain for c in cases} == set(item["domains"])
    assert all(c.state == "done" for c in cases)
    events = list(db.scalars(select(Event)))
    assert len(events) == 10 and all(e.kind == "user_completed" for e in events)
    assert not list(db.scalars(select(Job)))


def test_manual_steps_reachable_only_when_curated_fresh_and_unblocked(settings):
    guide = next(g for g in knowledge.guides(settings) if g.id == "truepeoplesearch-public")
    domain = guide.match_domains[0]
    broker = SimpleNamespace(id=1, name=guide.name, domain=domain)

    def row(g, domains):
        return library_rows([broker], {domain: g}, {}, manual_domains=domains)[0]

    assert not row(guide, [])["reachable"]
    assert row(guide, [domain])["reachable"]
    stale = guide.model_copy(deep=True)
    stale.evidence[0].checked_on = date(2020, 1, 1)
    assert not row(stale, [domain])["reachable"]
    blocked = guide.model_copy(deep=True)
    blocked.automation.mode = "blocked"
    assert not row(blocked, [domain])["reachable"]


def test_country_matching_and_major_priority(settings, db, vault):
    items = {i["id"]: i for i in quick_wins.resources(settings)["items"]}
    for key in ("whitepages", "claritas-us", "experian-us-marketing", "transunion-us-privacy"):
        assert recommendations.region_matches(items[key]["regions"], "US")
        assert not recommendations.region_matches(items[key]["regions"], "DE")
    assert items["directory-192-uk"]["category"] == "people_search"
    assert recommendations.region_matches(items["acxiom-germany"]["regions"], "DE")
    assert recommendations.region_matches(items["liveramp-uk"]["regions"], "GB")
    workflow = Workflow(db, Store(db, vault), settings)
    workflow.store.set_setting("recommendation_country", "US")
    rows = recommendations.action_items(workflow)
    major = major_brokers.priority_guides(settings)
    for category in recommendations.CATEGORIES:
        selected = [r for r in rows if r["selectable"] and r["category"] == category]
        flags = [r["guide_id"] in major for r in selected]
        assert flags == sorted(flags, reverse=True)


def test_broker_page_manual_step_and_done_redirect_without_sending(tmp_path, master_key, settings):
    settings = settings.model_copy(
        update=dict(
            master_key=master_key,
            password_hash=hash_password("major route test"),
            session_secret=generate_session_secret(),
            templates_dir=ROOT / "templates",
            static_dir=ROOT / "static",
        )
    )
    engine = create_db_engine(f"sqlite:///{tmp_path / 'major.db'}")
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "major route test"})
        with Session(engine) as session:
            Store(session, Vault(master_key)).set_setting("recommendation_country", "GB")
            broker = session.scalar(select(Broker).where(Broker.domain == "caci.co.uk"))
            bid = broker.id
        url = f"/cases/broker/{bid}"
        page = client.get(url)
        assert page.status_code == 200
        assert "Open email creates a draft" in page.text
        assert "mailto:compliance@caci.co.uk" in page.text
        with Session(engine) as session:
            assert not list(session.scalars(select(Case)))
            assert not list(session.scalars(select(Job)))
        response = client.post(
            "/quick-wins/caci-uk",
            data={
                "csrf": page.context["csrf"],
                "done": "true",
                "return_to": url,
            },
            follow_redirects=False,
        )
        assert response.status_code == 303 and response.headers["location"] == url
        assert "Request complete" in client.get(url).text
        with Session(engine) as session:
            cases = list(session.scalars(select(Case)))
            assert len(cases) == 1 and cases[0].state == "done"
            assert not list(session.scalars(select(Job)))
        malicious = client.post(
            "/quick-wins/caci-uk",
            data={
                "csrf": page.context["csrf"],
                "done": "true",
                "return_to": "//example.test",
            },
            follow_redirects=False,
        )
        assert malicious.headers["location"] == "/quick-wins"
    engine.dispose()
