from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import AppSetting, Case, IncomingMessage, Job
from erasure.store import Store

ROOT = Path(__file__).parents[1]


@pytest.fixture
def design_app(tmp_path, master_key):
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('test password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f"sqlite:///{tmp_path / 'design.db'}")
    with TestClient(create_app(settings, engine)) as client:
        yield client, engine
    engine.dispose()


def test_design_preview_is_authenticated_synthetic_and_read_only(design_app, master_key):
    client, engine = design_app
    assert client.get('/design-preview', follow_redirects=False).status_code in (302, 303)
    client.post('/login', data={'password': 'test password'})
    with Session(engine) as session:
        store = Store(session, Vault(master_key))
        store.save_profile({'full_name': 'Private Not For Gallery', 'email': 'private@example.test'}, 'Private')
        before = [(s.key, s.value) for s in session.scalars(select(AppSetting))]
        jobs_before = [j.id for j in session.scalars(select(Job))]
    response = client.get('/design-preview')
    assert response.status_code == 200
    assert 'Private Not For Gallery' not in response.text
    assert 'private@example.test' not in response.text
    assert '<form' not in response.text
    assert response.text.count('data-design=') == 4
    assert 'data-design="grove"' not in response.text
    assert 'data-design="clay"' not in response.text
    assert 'sample-ornament' not in response.text
    assert 'Illustrative data' in response.text
    for size in ('Nearly 3B', '749M+', '290M+', '210M+'):
        assert size in response.text
    assert response.text.count('company-reported') == 4
    assert response.text.count('Size source ↗') == 4
    with Session(engine) as session:
        assert [(s.key, s.value) for s in session.scalars(select(AppSetting))] == before
        assert [j.id for j in session.scalars(select(Job))] == jobs_before
        assert not list(session.scalars(select(Case)))


def test_unmatched_mail_is_conditional_not_a_permanent_filter(design_app, master_key):
    client, engine = design_app
    client.post('/login', data={'password': 'test password'})
    page = client.get('/cases').text
    assert 'Browse brokers' in page
    assert 'href="/cases?view=mail"' not in page
    with Session(engine) as session:
        session.add(IncomingMessage(id='gallery-test-unmatched', status='review',
            encrypted_payload=Vault(master_key).encrypt({'body': 'Synthetic unlinked mail'})))
        session.commit()
    page = client.get('/cases').text
    assert '1 message needs matching to a broker' in page
    assert 'Unmatched mail' not in page
    assert 'Synthetic unlinked mail' in client.get('/cases?view=mail').text


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_design_choices_are_isolated_and_responsive(design_app, live_app_server, browser_name, tmp_path):
    client, engine = design_app
    client.post('/login', data={'password': 'test password'})
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1050})
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        page.goto(url + '/design-preview')
        showcase_text = page.locator('.sample-showcase').inner_text()
        requests = []
        page.on('request', lambda request: requests.append(request))
        for design in ('conservatory', 'porcelain', 'atelier', 'midnight'):
            page.locator(f'[data-design="{design}"]').click()
            expect(page.locator('.design-sample')).to_have_attribute('data-theme', design)
            expect(page.locator('[aria-pressed="true"]')).to_have_count(1)
            assert page.locator('.sample-showcase').inner_text() == showcase_text
            expect(page.locator('.sample-showcase a')).to_have_count(4)
            if design in ('conservatory', 'atelier'):
                assert page.locator('.sample-pill').evaluate('e => getComputedStyle(e).outlineStyle') == 'none'
                assert page.locator('.sample-pill').evaluate('e => getComputedStyle(e).borderTopWidth') == '1px'
                assert page.locator('.sample-pill .selected').evaluate('e => getComputedStyle(e).boxShadow') == 'none'
                assert page.locator('.sample-nav').evaluate('e => getComputedStyle(e).borderBottomWidth') == '0px'
            if design == 'conservatory':
                selected_style = page.locator('.sample-pill .selected').evaluate('''e => {
                    const style = getComputedStyle(e);
                    return {background: style.backgroundColor, radius: style.borderRadius,
                            decoration: style.textDecorationLine};
                }''')
                assert selected_style == {'background': 'rgb(220, 215, 176)', 'radius': '999px', 'decoration': 'none'}
                expect(page.locator('.sample-local')).to_be_hidden()
                assert page.locator('.sample-pill').bounding_box()['width'] < page.locator('.sample-nav').bounding_box()['width'] / 2
                assert page.locator('.sample-nav').evaluate('e => getComputedStyle(e).borderTopWidth') == '0px'
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 1050})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('.design-sample').screenshot(path=str(tmp_path / f'{design}-{browser_name}.png'))
        page.get_by_role('button', name='Choose this direction').click()
        expect(page.locator('#design-saved')).to_contain_text('Chosen: Midnight')
        assert not requests  # Theme selection is entirely local; no settings writes or network.
        page.reload()
        expect(page.locator('.design-sample')).to_have_attribute('data-theme', 'midnight')
        page.evaluate("localStorage.setItem('erasure-design-preview-choice', 'grove')")
        page.reload()
        expect(page.locator('.design-sample')).to_have_attribute('data-theme', 'conservatory')
        expect(page.locator('#design-saved')).to_contain_text('previous direction was retired')
        page.get_by_role('link', name='← Back to the app').click()
        page.wait_for_url('**/dashboard')
        expect(page.locator('body')).not_to_have_attribute('data-theme', 'midnight')
        expect(page.locator('#automation-title')).to_have_text('Stopped')
        browser.close()
