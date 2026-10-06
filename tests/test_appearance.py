import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from erasure import appearance, campaign, setup_flow
from erasure.app import create_app
from erasure.config import Settings
from erasure.crypto import Vault, generate_session_secret, hash_password
from erasure.db import create_db_engine
from erasure.models import AppSetting, Broker, Case, Event, Job
from erasure.store import Store

ROOT = Path(__file__).parents[1]


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_page_titles_use_one_shared_single_line_style(theme_app, live_app_server, browser_name):
    client, engine = theme_app
    client.post('/login', data={'password': 'appearance password'})
    with Session(engine) as session:
        broker = Broker(slug='long-title', name='Example International Professional Contact Database',
                        domain='title.example.test', contact='privacy@title.example.test')
        session.add(broker)
        session.flush()
        case = Case(broker_id=broker.id)
        session.add(case)
        session.commit()
        case_id = case.id
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page()
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        for theme in appearance.THEMES:
            page.context.add_cookies([{'name': appearance.cookie_name(), 'value': theme, 'url': url}])
            for width in [320, 1440]:
                page.set_viewport_size({'width': width, 'height': 1000})
                styles = []
                for route in ['/cases', '/dashboard', '/onboarding', '/campaign', '/appearance',
                              '/brokers', '/quick-wins', f'/cases/{case_id}']:
                    page.goto(url + route)
                    title = page.locator('main h1')
                    expect(title).to_have_count(1)
                    styles.append(title.evaluate('''el => {
                        const s = getComputedStyle(el);
                        return [s.fontFamily, s.fontSize, s.fontWeight, s.lineHeight];
                    }'''))
                    assert title.bounding_box()['height'] == pytest.approx(float(styles[-1][3][:-2]), abs=1)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    expect(page.locator('main > header .eyebrow, .settings-head .eyebrow')).to_have_count(0)
                assert all(style == styles[0] for style in styles)
        browser.close()


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_settings_tabs_share_layout_and_typography(theme_app, live_app_server, browser_name, tmp_path):
    client, _ = theme_app
    client.post('/login', data={'password': 'appearance password'})
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page()
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        for theme in appearance.THEMES:
            page.context.add_cookies([{'name': appearance.cookie_name(), 'value': theme, 'url': url}])
            for width in [320, 790, 1440]:
                page.set_viewport_size({'width': width, 'height': 1000})
                layouts = []
                for route in ['/onboarding', '/campaign', '/appearance']:
                    if route == '/onboarding':
                        page.goto(url + route)
                    else:
                        page.get_by_role('navigation', name='Settings sections').locator(f'[href="{route}"]').click()
                    expect(page).to_have_url(url + route)
                    page.wait_for_load_state('load')
                    layouts.append(page.evaluate('''() => {
                        const heading = document.querySelector('main h1');
                        const tabs = document.querySelector('[aria-label="Settings sections"]');
                        const style = getComputedStyle(heading);
                        const box = tabs.getBoundingClientRect();
                        const body = getComputedStyle(document.querySelector('.settings-page'));
                        return {font: style.fontFamily, size: style.fontSize, weight: style.fontWeight,
                            bodyFont: body.fontFamily, bodySize: body.fontSize, bodyLineHeight: body.lineHeight,
                            tabsFont: getComputedStyle(tabs).fontSize,
                            x: box.x, y: box.y, width: box.width, height: box.height};
                    }'''))
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    if route == '/onboarding':
                        assert page.locator('.profile-country .footnote').evaluate(
                            "el => getComputedStyle(el).borderTopWidth") == '0px'
                    expect(page.get_by_role('navigation', name='Settings sections').locator('[aria-current=page]')).to_have_count(1)
                    page.screenshot(path=str(tmp_path / f'{theme}-{width}-{route[1:]}.png'), animations='disabled')
                assert layouts[0] == layouts[1] == layouts[2], layouts
        browser.close()


@pytest.fixture
def theme_app(tmp_path, master_key):
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('appearance password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f'sqlite:///{tmp_path}/appearance.db')
    with TestClient(create_app(settings, engine)) as client:
        yield client, engine
    engine.dispose()


def csrf(client, route='/appearance'):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(route).text)[1]


def snapshot(engine):
    with Session(engine) as session:
        return {
            'settings': [(s.key, s.value) for s in session.scalars(select(AppSetting))],
            'cases': [(c.id, c.state) for c in session.scalars(select(Case))],
            'jobs': [(j.id, j.kind) for j in session.scalars(select(Job))],
        }


def test_appearance_is_cookie_only_authenticated_and_validated(theme_app):
    client, engine = theme_app
    assert client.get('/appearance', follow_redirects=False).headers['location'] == '/login'
    assert client.post('/appearance', data={'theme': 'midnight'}).status_code == 401
    client.post('/login', data={'password': 'appearance password'})
    token = csrf(client)
    before = snapshot(engine)
    assert client.post('/appearance', data={'theme': 'midnight'}).status_code == 403
    assert client.post('/appearance', data={'csrf': token, 'theme': 'unknown'}).status_code == 422
    for theme in appearance.THEMES:
        response = client.post('/appearance', data={'csrf': token, 'theme': theme}, follow_redirects=False)
        assert response.status_code == 303
        assert 'HttpOnly' in response.headers['set-cookie']
        assert 'SameSite=lax' in response.headers['set-cookie']
        for route in ['/appearance', '/setup', '/login', '/onboarding', '/campaign']:
            html = client.get(route).text
            assert f'<html lang="en" data-theme="{theme}">' in html
            assert '/static/themes.css?v=' in html
        assert client.get('/appearance').headers['cache-control'] == 'no-store'
    assert snapshot(engine) == before
    client.post('/logout', data={'csrf': token})
    assert 'data-theme="midnight"' in client.get('/login').text
    client.cookies.clear()
    client.cookies.set(appearance.cookie_name(), 'not-a-theme')
    assert 'data-theme="porcelain"' in client.get('/login').text
    assert appearance.cookie_name(True) != appearance.cookie_name(False)


def test_setup_choice_is_resumable_and_cannot_authorize_sending(theme_app, master_key):
    client, engine = theme_app
    client.post('/login', data={'password': 'appearance password'})
    token = csrf(client, '/setup')
    before = snapshot(engine)
    assert 'Step 1 of 5' in client.get('/setup?step=4').text
    assert client.post('/setup/appearance', data={'csrf': token, 'theme': 'bad'}).status_code == 422
    assert client.post('/setup/appearance', data={'theme': 'midnight'}).status_code == 403
    assert snapshot(engine) == before
    page = client.post('/setup/appearance', data={'csrf': token, 'theme': 'conservatory'})
    assert 'Step 2 of 5' in page.text
    assert 'data-theme="conservatory"' in page.text
    client.post('/setup/country', data={'csrf': token, 'country': 'DE'})
    client.post('/setup/details', data={'csrf': token, 'full_name': 'Alex Example', 'emails': 'alex@example.test'})
    client.post('/setup/appearance', data={'csrf': token, 'theme': 'atelier'})
    assert 'Step 4 of 5' in client.get('/setup').text
    with Session(engine) as session:
        store = Store(session, Vault(master_key))
        assert setup_flow.draft(store)['appearance'] == 'atelier'
        assert setup_flow.draft(store)['full_name'] == 'Alex Example'
        assert store.get_profile() is None
        assert not campaign.consent(store)
        assert not list(session.scalars(select(Job)))
        assert not list(session.scalars(select(Case)))


def test_older_manual_only_setup_can_still_start_email_setup(theme_app, master_key):
    client, engine = theme_app
    client.post('/login', data={'password': 'appearance password'})
    token = csrf(client)
    with Session(engine) as session:
        store = Store(session, Vault(master_key))
        store.set_setting(setup_flow.DRAFT_KEY, {'country': 'GB'}, encrypted=True)
        store.set_setting('setup_manual_complete', 'true')
    result = client.post('/setup/country', data={'csrf': token, 'country': 'DE'})
    assert 'Make it yours.' in result.text
    client.post('/setup/appearance', data={'csrf': token, 'theme': 'midnight'})
    assert 'Your info' in client.get('/setup').text


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_themes_across_app_and_saved_without_javascript(theme_app, master_key, live_app_server,
                                                       browser_name, tmp_path):
    client, engine = theme_app
    client.post('/login', data={'password': 'appearance password'})
    vault = Vault(master_key)
    with Session(engine) as session:
        Store(session, vault).save_profile({'full_name': 'Alex Example', 'email': 'alex@example.test'}, 'Alex')
        broker = session.scalar(select(Broker).where(Broker.domain == 'apollo.io'))
        case = Case(broker_id=broker.id, state='not_found')
        session.add(case)
        session.flush()
        case_id = case.id
        session.add_all([Event(case_id=case.id, kind='submitted', summary='Request sent') for _ in range(3)])
        session.add(Event(case_id=case.id, kind='reply_received', summary='Broker reported no match', encrypted_payload=vault.encrypt({
            'body': 'We could not find matching records. No further action is needed.',
            'from': 'privacy@example.test', 'subject': 'Your removal request',
        })))
        session.commit()
    url = live_app_server(client.app)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        showcase = None
        for theme in appearance.THEMES:
            page.goto(url + '/appearance')
            saved_theme = page.locator('html').get_attribute('data-theme')
            radio = page.get_by_role('radio', name=appearance.THEMES[theme]['name'], exact=False)
            radio.click()
            expect(radio).to_be_checked()
            expect(page.locator('html')).to_have_attribute('data-theme', saved_theme)
            assert radio.evaluate('el => getComputedStyle(el).outlineStyle') == 'none'
            assert 'Less, but better.' not in page.locator('main').inner_text()
            expect(page.locator('.appearance-description')).to_have_count(0)
            page.keyboard.press('Tab')
            radio.focus()
            page.keyboard.press('Space')
            focused = page.locator('.appearance-choices input:focus-visible')
            assert focused.count() == 1, page.evaluate('({active:document.activeElement.outerHTML, radio:[...document.querySelectorAll(".appearance-choices input")].map(e=>[e.value,e.matches(":focus"),e.matches(":focus-visible"),e.checked])})')
            assert focused.locator('xpath=ancestor::label').evaluate('el => getComputedStyle(el).outlineWidth') == '3px'
            expect(page.locator('html')).to_have_attribute('data-theme', saved_theme)
            page.reload()
            expect(page.locator('html')).to_have_attribute('data-theme', saved_theme)
            expect(page.locator(f'input[name=theme][value={saved_theme}]')).to_be_checked()
            radio.click()
            page.get_by_role('button', name='Save appearance').click()
            expect(page.get_by_role('status')).to_have_text('Appearance saved.')
            for route in ['/dashboard', '/cases', f'/cases/{case_id}', f'/cases/{case_id}?tab=conversation',
                          f'/cases/{case_id}?tab=details', '/onboarding', '/campaign', '/appearance', '/quick-wins', '/brokers']:
                page.goto(url + route)
                expect(page.locator('html')).to_have_attribute('data-theme', theme)
                assert page.locator('meta[name=color-scheme]').get_attribute('content') == appearance.THEMES[theme]['scheme']
                if route == '/dashboard':
                    for card in page.locator('.dashboard-columns > .card').all():
                        assert card.evaluate('el => getComputedStyle(el).borderTopStyle') == 'solid'
                    content = page.locator('.scale-grid').inner_text()
                    if showcase is None:
                        showcase = content
                    assert content == showcase
                    for value in ['Nearly 3B', '749M+', '290M+', '210M+', 'Broker reported no match']:
                        assert value in content
                    # Render the existing dialog without changing any campaign state.
                    dialog = page.locator('#pause-confirmation')
                    dialog.evaluate('el => el.showModal()')
                    expect(dialog).to_be_visible()
                    assert dialog.evaluate('el => getComputedStyle(el).color') == page.locator('body').evaluate('el => getComputedStyle(el).color')
                    page.set_viewport_size({'width': 320, 'height': 1000})
                    assert dialog.bounding_box()['width'] <= 320
                    dialog.evaluate('el => el.close()')
                if 'tab=conversation' in route:
                    expect(page.locator('.email-body')).to_contain_text('No further action is needed.')
                    assert page.locator('.email-body').evaluate('el => getComputedStyle(el).color') == page.locator('body').evaluate('el => getComputedStyle(el).color')
                # Check semantic text/background pairs, including warning/error and controls.
                contrasts = page.evaluate('''() => {
                    const style = getComputedStyle(document.documentElement);
                    const luminance = hex => {
                        const rgb = hex.trim().slice(1).match(/../g).map(x => parseInt(x, 16)/255)
                            .map(x => x <= .04045 ? x/12.92 : ((x+.055)/1.055)**2.4);
                        return rgb[0]*.2126 + rgb[1]*.7152 + rgb[2]*.0722;
                    };
                    return [['ink', 'bg'], ['muted', 'surface'], ['accent', 'surface'],
                        ['on-accent', 'accent'], ['green', 'green-soft'], ['amber', 'amber-soft'],
                        ['red', 'red-soft'], ['processing', 'processing-soft'], ['nav-ink', 'nav']]
                        .map(pair => {
                            const [a,b] = pair.map(key => luminance(style.getPropertyValue('--'+key)));
                            return {pair, ratio: (Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
                        });
                }''')
                assert all(item['ratio'] >= 4.5 for item in contrasts), (theme, contrasts)
                for width in (320, 790, 1440):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, route, width)
                    assert page.locator('.primary-nav:visible, .mobile-nav:visible').count() == 1
                    if width == 1440:
                        nav = page.locator('.navigation-pill')
                        assert nav.evaluate('e => getComputedStyle(e).borderTopWidth') == '1px'
                        assert page.locator('.primary-nav a.active').evaluate('e => getComputedStyle(e).boxShadow') == 'none'
                if route in ['/dashboard', '/appearance', f'/cases/{case_id}?tab=conversation']:
                    page.screenshot(path=str(tmp_path / f'{theme}-{browser_name}-{route.split("?")[-1].split("/")[-1]}.png'), full_page=True)
        assert not errors
        # Saving still works if JavaScript is unavailable, and the first HTML is themed.
        no_js = browser.new_context(java_script_enabled=False)
        no_js.add_cookies(page.context.cookies())
        other = no_js.new_page()
        other.goto(url + '/appearance')
        other.get_by_role('radio', name='Atelier', exact=False).check()
        other.get_by_role('button', name='Save appearance').click()
        expect(other.locator('html')).to_have_attribute('data-theme', 'atelier')
        other.goto(url + '/dashboard')
        expect(other.locator('html')).to_have_attribute('data-theme', 'atelier')
        browser.close()
