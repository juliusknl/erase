from types import SimpleNamespace

from erasure.broker_library import library_rows, select_rows, sort_rows


def row_fixture(method="form", reviewed=True, fresh=True, email=False, blocked=False):
    broker = SimpleNamespace(id=1, name="Example", domain="example.test")
    guide = SimpleNamespace(
        name="Example Brand", identity=SimpleNamespace(legal_name="Example Legal", brands=["Alias"]),
        relevance=SimpleNamespace(category="professional", regions=["US", "other_regions_not_established"]),
        review_status="instructions_reviewed" if reviewed else "research_incomplete",
        fresh=fresh, removal=SimpleNamespace(method=method),
        automation=SimpleNamespace(mode="blocked" if blocked else "manual"),
    )
    return library_rows([broker], {broker.domain: guide},
                        {broker.domain: SimpleNamespace(fresh=fresh)} if email else {})


def test_routes_distinguish_forms_from_research_and_contact_checks():
    assert row_fixture()[0]["route"] == "form"
    assert row_fixture(method="email")[0]["route"] == "manual"
    assert row_fixture(method="email", email=True)[0]["route"] == "email"
    assert row_fixture(reviewed=False)[0]["route"] == "research"
    assert row_fixture(fresh=False)[0]["route"] == "stale"
    assert "_" not in row_fixture()[0]["regions"]


def test_combined_filters_and_literal_search():
    rows = row_fixture()
    assert len(select_rows(rows, q="example.test", category="professional", region="US")) == 1
    assert not select_rows(rows, q="%")
    assert not select_rows(rows, category="advertising")
    assert not select_rows(rows, region="DE")
    assert len(select_rows(rows, q="Alias")) == 1


def test_reachable_requires_current_supported_email_or_reviewed_form():
    assert row_fixture()[0]['reachable']
    assert row_fixture(method='email', email=True)[0]['reachable']
    for options in [dict(method='email'), dict(method='manual'), dict(method='investigate'),
                    dict(reviewed=False), dict(fresh=False), dict(blocked=True)]:
        assert not row_fixture(**options)[0]['reachable']
    rows = row_fixture(email=True)
    assert rows[0]['reachable']


def test_unknown_profiles_are_research_not_automatically_available():
    rows = library_rows([SimpleNamespace(id=2,name="Unknown",domain="unknown.test")], {}, {})
    assert rows[0]["route"] == "research"
    assert rows[0]["category_label"] == "Not classified"
    assert rows[0]["regions"] == "Not established"
    assert not rows[0]['reachable']


def test_sort_by_name_and_category_in_both_directions():
    rows = [dict(broker=SimpleNamespace(id=i, name=name), category_label=category)
            for i, name, category in [(1, 'Zulu', 'Advertising'), (2, 'alpha', 'Sales'), (3, 'Beta', 'Advertising')]]
    assert [r['broker'].id for r in sort_rows(rows)] == [2, 3, 1]
    assert [r['broker'].id for r in sort_rows(rows, direction='desc')] == [1, 3, 2]
    assert [r['broker'].id for r in sort_rows(rows, 'category')] == [3, 1, 2]
    assert [r['broker'].id for r in sort_rows(rows, 'category', 'desc')] == [2, 1, 3]


def test_library_pagination_details_and_filters_are_read_only(tmp_path, master_key):
    import re
    from pathlib import Path

    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from erasure.app import create_app
    from erasure.config import Settings
    from erasure.crypto import generate_session_secret, hash_password
    from erasure.db import create_db_engine
    from erasure.models import AppSetting, Broker, Case

    root = Path(__file__).parents[1]
    settings = Settings(_env_file=None, master_key=master_key,
                        password_hash=hash_password("test password"),
                        session_secret=generate_session_secret(),
                        templates_dir=root / "templates", static_dir=root / "static",
                        catalog_dir=root / "catalog")
    engine = create_db_engine(f"sqlite:///{tmp_path / 'library.db'}")
    with TestClient(create_app(settings, engine)) as client:
        assert client.get('/brokers/1', follow_redirects=False).status_code == 303
        client.post('/login', data={'password': 'test password'})
        with Session(engine) as session:
            before = list(session.execute(select(AppSetting.key, AppSetting.value)))
            research_only = Broker(slug='research-only-test', name='Research Only Test', domain='research-only.test')
            session.add(research_only)
            session.commit()
            research_id = research_only.id
        url = '/brokers?category=professional'
        first = client.get(url).text
        assert all(f'name="{field}"' in first for field in ('q', 'category', 'region'))
        assert 'Removal route' not in first and 'name="route"' not in first
        ids = set(re.findall(r'/cases/broker/(\d+)', first))
        assert len(ids) == 50
        second = client.get(url + '&page=2').text
        assert ids.isdisjoint(set(re.findall(r'/cases/broker/(\d+)', second)))
        assert 'category=professional' in second
        bid = next(iter(ids))
        response = client.get(url + '&detail=' + bid)
        detail = response.text
        assert response.url.path == f'/cases/broker/{bid}'
        assert 'Not started' in detail and 'Nothing has been sent or completed' in detail
        assert 'View broker details' not in detail and 'Prepare request' not in detail
        assert 'aria-label="Request sections"' in detail
        assert 'library-table' not in detail and 'Filter brokers' not in detail
        assert set(re.findall(r'/cases/broker/(\d+)', client.get(url + '&route=email').text)) == ids
        for tab in ('overview', 'conversation', 'details'):
            assert client.get(f'/cases/broker/{bid}?tab={tab}').status_code == 200
        assert 'Catalog and registry information' in client.get(f'/cases/broker/{bid}?tab=details').text
        for entry in ('/brokers', '/brokers?view=guides'):
            html = client.get(entry).text
            count = re.search(r'<strong>(\d+)</strong> of (\d+) brokers', html)
            assert count[1] == count[2]
            assert 'name="view"' not in html
            with Session(engine) as session:
                assert int(count[2]) < len(list(session.scalars(select(Broker))))
        assert 'No matching brokers' in client.get('/brokers?q=Research+Only+Test').text
        assert client.get(f'/cases/broker/{research_id}').status_code == 200
        ascending = client.get(url + '&sort=broker&direction=asc')
        descending = client.get(url + '&sort=broker&direction=desc')
        assert ascending.context['rows'][0]['broker'].name.casefold() < descending.context['rows'][0]['broker'].name.casefold()
        assert ascending.context['rows'][0]['broker'].id not in {r['broker'].id for r in descending.context['rows']}
        page2 = client.get(url + '&sort=category&direction=desc&page=2')
        assert 'direction=desc' in page2.text and 'sort=category' in page2.text
        invalid = client.get('/brokers?sort=unknown&direction=bad')
        assert invalid.context['sort'] == 'broker' and invalid.context['direction'] == 'asc'
        assert client.get('/brokers?detail=999999').status_code == 404
        assert client.get('/brokers?page=-3').status_code == 200
        assert client.get('/brokers?page=999999').status_code == 200
        assert 'No matching brokers' in client.get('/brokers?q=%25').text
        with Session(engine) as session:
            assert not list(session.scalars(select(Case)))
            assert list(session.execute(select(AppSetting.key, AppSetting.value))) == before
            case = Case(broker_id=int(bid), state='candidate')
            session.add(case)
            session.commit()
            cid = case.id
        candidate = client.get(f'/cases/broker/{bid}').text
        assert 'View broker details' not in candidate and 'Prepare request' not in candidate
        with Session(engine) as session:
            session.get(Case, cid).state = 'done'
            session.commit()
        # When work exists, every old link and the library converge on its existing ID.
        assert f'href="/cases/{cid}"' in client.get(url).text
        assert client.get(f'/brokers/{bid}').url.path == f'/cases/{cid}'
        redirect = client.get(f'/cases/broker/{bid}?tab=details', follow_redirects=False)
        assert redirect.headers['location'] == f'/cases/{cid}?tab=details'
        assert 'Catalog and registry information' in client.get(f'/cases/{cid}?tab=details').text
        with Session(engine) as session:
            assert session.get(Case, cid).state == 'done'
            assert len(list(session.scalars(select(Case)))) == 1
    engine.dispose()
