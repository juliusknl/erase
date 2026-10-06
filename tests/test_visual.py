from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from erasure.models import Approval, AppSetting, Broker, Case, Event, IncomingMessage, Job
from erasure.quick_wins import resources
from erasure.store import Store

ROOT = Path(__file__).parents[1]


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
@pytest.mark.parametrize('theme', ['porcelain', 'conservatory', 'atelier', 'midnight'])
def test_background_preference_fits_and_saves(tmp_path, master_key, live_app_server,
                                            monkeypatch, browser_name, theme):
    from erasure import background

    changed = []
    monkeypatch.setattr(background, 'status', lambda _: {'enabled': bool(changed and changed[-1]), 'error': ''})
    monkeypatch.setattr(background, 'settings_paths', lambda _: (ROOT, tmp_path))
    monkeypatch.setattr(background, 'set_login', lambda root, data, enabled: changed.append(enabled))
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('background browser password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=tmp_path)
    engine = create_db_engine(f'sqlite:///{tmp_path}/background-ui.db')
    url = live_app_server(create_app(settings, engine))
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 375, 'height': 812})
        page.context.add_cookies([{'name': 'erasure_appearance', 'value': theme, 'url': url}])
        page.goto(url + '/login')
        page.get_by_label('Dashboard password').fill('background browser password')
        page.get_by_role('button', name='Unlock').click()
        page.goto(url + '/campaign')
        section = page.get_by_role('region', name='Keep things moving')
        expect(section).to_be_visible()
        expect(section.get_by_role('checkbox')).not_to_be_checked()
        assert not changed
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        section.get_by_role('checkbox').check()
        section.get_by_role('button', name='Save', exact=True).click()
        expect(page.get_by_text('Startup preference saved.', exact=True)).to_be_visible()
        expect(section.get_by_role('checkbox')).to_be_checked()
        assert changed == [True]
        section.get_by_role('checkbox').uncheck()
        section.get_by_role('button', name='Save', exact=True).click()
        expect(section.get_by_role('checkbox')).not_to_be_checked()
        assert changed == [True, False]
        browser.close()


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
@pytest.mark.parametrize('theme', ['porcelain', 'conservatory', 'atelier', 'midnight'])
def test_recovery_page_has_visible_keyboard_exit(tmp_path, master_key, live_app_server, browser_name, theme):
    settings = Settings(_env_file=None, master_key=master_key,
        password_hash=hash_password('synthetic recovery password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f'sqlite:///{tmp_path}/recovery.db')
    url = live_app_server(create_app(settings, engine))
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 320, 'height': 800})
        page.context.add_cookies([{'name': 'erasure_appearance', 'value': theme, 'url': url}])
        assert page.goto(url + '/missing-page').status == 404
        expect(page.locator('html')).to_have_attribute('data-theme', theme)
        expect(page.get_by_role('alert')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        # macOS WebKit uses Option-Tab for links when full keyboard access is off.
        page.keyboard.press('Alt+Tab' if browser_name == 'webkit' else 'Tab')
        expect(page.get_by_role('link', name='Back to dashboard')).to_be_focused()
        page.keyboard.press('Enter')
        expect(page.get_by_label('Dashboard password')).to_be_visible()
        browser.close()


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
@pytest.mark.parametrize('javascript', [True, False])
def test_guided_setup_full_journey_and_responsive_layout(tmp_path, master_key, live_app_server,
                                                        browser_name, javascript):
    from types import SimpleNamespace

    settings = Settings(_env_file=None, demo_mode=True, live_submissions=True,
        database_url=f'sqlite:///{tmp_path}/demo.db', master_key=master_key,
        password_hash=hash_password('setup browser password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(settings.database_url)
    app = create_app(settings, engine)
    url = live_app_server(app)
    app.state.worker_thread = SimpleNamespace(is_alive=lambda: True)
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, java_script_enabled=javascript)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def fits(step):
            expect(page.locator('.setup-progress')).to_contain_text(f'Step {step + 1} of 5')
            expect(page.locator('.primary-nav')).to_have_count(0)
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                for field in page.locator('input:not([type=hidden]):visible, select:visible, button:visible').all():
                    box = field.bounding_box()
                    assert box and box['x'] >= 0 and box['x'] + box['width'] <= width
                if step == 3:
                    buttons = page.locator('.mailbox-actions .button')
                    expect(buttons).to_have_count(2)
                    first, second = buttons.nth(0).bounding_box(), buttons.nth(1).bounding_box()
                    assert abs(first['x'] - second['x']) < 1
                    assert abs(first['width'] - second['width']) < 1
                    assert abs(first['height'] - second['height']) < 1
                    assert second['y'] >= first['y'] + first['height'] + 10
                page.screenshot(path=str(tmp_path / f'setup-{step}-{browser_name}-{javascript}-{width}.png'), full_page=True)

        page.goto(url + '/login')
        page.get_by_label('Dashboard password').fill('setup browser password')
        page.get_by_role('button', name='Unlock').click()
        fits(0)
        page.get_by_role('radio', name='Midnight').check()
        expect(page.locator('html')).to_have_attribute('data-theme', 'midnight' if javascript else 'porcelain')
        expect(page.locator('meta[name="color-scheme"]')).to_have_attribute('content', 'dark' if javascript else 'light')
        # A preview is not a saved preference. Reload restores the saved look.
        page.reload()
        expect(page.locator('html')).to_have_attribute('data-theme', 'porcelain')
        page.get_by_role('radio', name='Conservatory').check()
        expect(page.locator('html')).to_have_attribute('data-theme', 'conservatory' if javascript else 'porcelain')
        page.get_by_role('radio', name='Midnight').check()
        page.get_by_role('button', name='Continue', exact=True).click()
        expect(page.locator('html')).to_have_attribute('data-theme', 'midnight')
        fits(1)
        page.get_by_label('Where do you live?').select_option('DE')
        page.get_by_role('button', name='Continue', exact=True).click()
        fits(2)
        page.get_by_label('Full name', exact=True).fill('Alex Example')
        page.get_by_label('Email address 1', exact=True).fill('alex@example.test')
        page.get_by_role('button', name='Add another email').click()
        page.get_by_label('Email address 2', exact=True).fill('work@example.test')
        page.get_by_role('button', name='Save and exit').click()
        expect(page.get_by_role('link', name='Continue setup')).to_be_visible()
        page.get_by_role('link', name='Continue setup').click()
        fits(3)
        page.get_by_role('link', name='Connect demo mailbox', exact=True).click()
        page.get_by_role('button', name='Connect demo mailbox', exact=True).click()
        fits(4)
        page.get_by_role('link', name='Optional: let AI handle more replies', exact=True).click()
        assistance = page.get_by_role('dialog', name='Let erase handle more replies')
        expect(assistance).to_be_visible()
        expect(assistance.locator('input[type=password]')).to_have_count(0)
        assistance.get_by_role('button', name='Try demo connection').click()
        expect(assistance.get_by_role('status')).to_contain_text('No external service was contacted')
        assistance.get_by_role('link', name='Done', exact=True).click()
        expect(assistance).not_to_be_visible()
        expect(page.get_by_role('link', name='Reply assistance: Demo connected', exact=True)).to_be_visible()
        page.goto(url + '/setup?step=3')
        expect(page.get_by_role('link', name='Change Gmail account', exact=True)).to_be_visible()
        fits(3)
        page.get_by_role('link', name='Continue', exact=True).click()
        expect(page.locator('.setup-review')).to_contain_text('work@example.test')
        page.get_by_label('I authorize ongoing requests', exact=False).check()
        page.get_by_label('Type your full name to sign').fill('Alex Example')
        page.get_by_role('button', name='Start automatic requests').click()
        expect(page).to_have_url(url + '/dashboard')
        expect(page.locator('#automation-title')).to_have_text('Starting your requests…')
        assert not errors
        browser.close()
    with Session(engine) as session:
        assert session.scalar(select(Job.id).where(Job.kind == 'campaign_tick')) is not None
        assert Store(session, Vault(master_key)).get_profile()['email'] == 'requests@example.test'


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
@pytest.mark.parametrize('javascript', [True, False])
def test_automation_controls_and_single_step_permissions(tmp_path, master_key, live_app_server, browser_name, javascript, monkeypatch):
    from erasure import campaign

    settings = Settings(_env_file=None, live_submissions=True, master_key=master_key,
        password_hash=hash_password('test password'), session_secret=generate_session_secret(),
        templates_dir=ROOT / 'templates', static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f"sqlite:///{tmp_path / 'automation-ui.db'}")
    monkeypatch.setattr('erasure.gmail.GmailClient.send', lambda *args: pytest.fail('UI test must never send mail'))
    with TestClient(create_app(settings, engine)) as client:
        client.post('/login', data={'password': 'test password'})
        with Session(engine) as session:
            store = Store(session, Vault(master_key))
            store.save_profile({'full_name': 'Example Person', 'email': 'requests@example.test',
                'other_emails': ['matching@example.test'], 'work_email': 'work@example.test',
                'employer': 'Example Company', 'postal_address': '1 Example Street'}, 'Example Person')
            store.set_setting('recommendation_country', 'DE', encrypted=True)
            store.set_setting('gmail_token', {'access_token': 'synthetic'}, encrypted=True)
            store.set_setting('gmail_last_sync', datetime.now(UTC).isoformat())
            store.set_setting('campaign_last_tick', datetime.now(UTC).isoformat())
        url = live_app_server(client.app)
        with sync_playwright() as pw:
            browser = getattr(pw, browser_name).launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, java_script_enabled=javascript)
            page.context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
            page.goto(url + '/campaign')
            for width in (320, 390, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                expect(page.get_by_role('heading', name='Information shared', exact=True)).to_be_visible()
                expect(page.locator('main details')).to_have_count(0)
                expect(page.get_by_label('Maximum automatic emails per day', exact=True)).to_be_visible()
                assert page.locator('#mailbox-heading').evaluate('el => getComputedStyle(el).fontFamily') == page.locator('#sharing-heading').evaluate('el => getComputedStyle(el).fontFamily')
                assert page.locator('#mailbox-heading').evaluate('el => getComputedStyle(el).fontSize') == page.locator('#sharing-heading').evaluate('el => getComputedStyle(el).fontSize')
                assert 'Earlier contact checks' not in page.locator('main').inner_text()
                assert 'Update request previews' not in page.locator('main').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(tmp_path / f'automation-{browser_name}-{width}.png'), full_page=True)
            page.get_by_label('I authorize ongoing automatic requests', exact=False).check()
            page.get_by_role('button', name='Start automatic emails', exact=True).click()
            expect(page.get_by_role('button', name='Save permissions', exact=True)).to_be_visible()
            page.goto(url + '/dashboard')
            expect(page.locator('#automation-title')).to_have_text('Running')
            expect(page.locator('.campaign-card details')).to_have_count(0)
            expect(page.get_by_role('button', name='Stop automatic emails', exact=True)).to_have_count(0)
            for width in (320, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('.campaign-card').screenshot(path=str(tmp_path / f'controls-{browser_name}-{width}.png'))
            page.get_by_role('button', name='Pause', exact=True).click()
            confirmation = page.get_by_role('dialog') if javascript else page.locator('section.pause-confirmation')
            expect(confirmation).to_be_visible()
            expect(confirmation).to_contain_text('Requests and follow-ups will pause until you resume; we’ll keep checking replies.')
            with Session(engine) as session:
                assert Store(session, Vault(master_key)).get_setting('paused') != 'true'
            if javascript:
                page.keyboard.press('Escape')
                expect(confirmation).not_to_be_visible()
                expect(page.get_by_role('button', name='Pause', exact=True)).to_be_focused()
                page.get_by_role('button', name='Pause', exact=True).click()
            confirmation.get_by_role('link', name='Cancel', exact=True).click()
            expect(page.locator('#automation-title')).to_have_text('Running')
            page.get_by_role('button', name='Pause', exact=True).click()
            if javascript:
                page.set_viewport_size({'width': 320, 'height': 1000})
                assert confirmation.bounding_box()['width'] <= 320
                page.screenshot(path=str(tmp_path / f'pause-popup-{browser_name}.png'))
            confirmation.get_by_role('button', name='Pause', exact=True).click()
            expect(page.locator('#automation-title')).to_have_text('Paused')
            page.goto(url + '/campaign')
            page.get_by_label('Allow my saved postal address only when required.', exact=True).check()
            page.get_by_label('I authorize ongoing automatic requests', exact=False).check()
            page.get_by_role('button', name='Save permissions', exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('Outgoing emails remain paused.')
            with Session(engine) as session:
                store = Store(session, Vault(master_key))
                assert campaign.consent(store)['allow_postal'] is True
                assert campaign.consent(store)['include_new'] is True
                assert store.get_setting('paused') == 'true'
            page.get_by_role('link', name='See covered brokers and exact emails →').click()
            expect(page.get_by_role('heading', name='Exact email previews')).to_be_visible()
            page.get_by_role('link', name='Without postal address', exact=True).click()
            page.get_by_role('link', name='View email', exact=True).first.click()
            expect(page.locator('.email-preview .email-body')).to_be_visible()
            expect(page.locator('.email-preview .email-body')).to_contain_text('Example Person')
            assert '1 Example Street' not in page.locator('.email-preview .email-body').inner_text()
            assert page.locator('.email-preview a[href^="/brokers/"]').count() == 1
            page.goto(url + '/dashboard')
            page.get_by_role('button', name='Resume', exact=True).click()
            expect(page.locator('#automation-title')).to_have_text('Running')
            expect(page.get_by_role('button', name='Resume', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='Pause', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
        with Session(engine) as session:
            assert campaign.consent(Store(session, Vault(master_key)))['enabled']
            assert Store(session, Vault(master_key)).get_setting('paused') == 'false'
            assert not list(session.scalars(select(Event).where(Event.kind == 'submitted')))
    engine.dispose()


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
@pytest.mark.parametrize('theme', ['porcelain', 'conservatory', 'atelier', 'midnight'])
def test_simple_completion_graph_fits_without_javascript(tmp_path, master_key, live_app_server, browser_name, theme):
    settings = Settings(_env_file=None, master_key=master_key, password_hash=hash_password('test password'),
                        session_secret=generate_session_secret(), templates_dir=ROOT / 'templates',
                        static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f"sqlite:///{tmp_path / 'graph.db'}")
    with TestClient(create_app(settings, engine)) as client:
        client.post('/login', data={'password': 'test password'})
        with Session(engine) as session:
            for i in range(18):
                broker = Broker(slug=f'graph-{i}', name=f'Example {i}', domain=f'graph-{i}.test')
                session.add(broker)
                session.flush()
                case = Case(broker_id=broker.id, state=['done', 'removed', 'not_found'][i % 3],
                            completed_at=datetime.now(UTC) - timedelta(days=i))
                session.add(case)
                session.flush()
                session.add(Event(case_id=case.id, kind='submitted', summary='Request sent',
                                  created_at=datetime.now(UTC) - timedelta(days=i + 4)))
            session.commit()
        url = live_app_server(client.app)
        with sync_playwright() as pw:
            browser = getattr(pw, browser_name).launch()
            for width in [320, 390, 1440]:
                context = browser.new_context(viewport={'width': width, 'height': 950}, java_script_enabled=False)
                context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
                context.add_cookies([{'name': 'erasure_appearance', 'value': theme, 'url': url}])
                page = context.new_page()
                page.goto(url + '/dashboard')
                expect(page.get_by_role('img', name='Sent and completed requests over time')).to_be_visible()
                expect(page.locator('.completion-line')).to_have_count(1)
                expect(page.locator('.sent-line')).to_have_count(1)
                assert page.locator('.sent-line').evaluate('e => getComputedStyle(e).stroke') != page.locator('.completion-line').evaluate('e => getComputedStyle(e).stroke')
                assert page.locator('.sent-line').get_attribute('d') != page.locator('.completion-line').get_attribute('d')
                assert page.locator('.completion-trend').bounding_box()['y'] < page.locator('.progress-metrics').bounding_box()['y']
                expect(page.locator('.completion-axis')).to_contain_text('18')
                expect(page.locator('.broker-map')).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert float(page.locator('.completion-dates').evaluate('e => getComputedStyle(e).fontSize').replace('px', '')) >= 12
                page.locator('.completion-trend').screenshot(path=tmp_path / f'graph-{browser_name}-{width}.png')
                context.close()
            browser.close()
    engine.dispose()


@pytest.mark.visual
@pytest.mark.parametrize('browser_name', ['chromium', 'webkit'])
def test_sortable_tables_and_settings_tabs(tmp_path, master_key, live_app_server, browser_name):
    settings = Settings(_env_file=None, master_key=master_key, password_hash=hash_password('test password'),
                        session_secret=generate_session_secret(), templates_dir=ROOT / 'templates',
                        static_dir=ROOT / 'static', catalog_dir=ROOT / 'catalog')
    engine = create_db_engine(f"sqlite:///{tmp_path / 'sorting.db'}")
    with TestClient(create_app(settings, engine)) as client:
        client.post('/login', data={'password': 'test password'})
        with Session(engine) as session:
            for i, name in enumerate(['Zulu', 'alpha', 'Beta', 'Echo', 'Delta']):
                stamp = datetime.now(UTC) - timedelta(hours=[50, 3, 300, 40, 2][i])
                broker = Broker(slug=f'sort-{i}', name=name, domain=f'sort-{i}.test',
                                contact=f'privacy@sort-{i}.test', last_validated_at=stamp)
                session.add(broker)
                session.flush()
                case = Case(broker_id=broker.id, state=['prepared', 'prepared', 'prepared', 'submitted', 'done'][i],
                            updated_at=stamp)
                session.add(case)
                session.flush()
                if i < 3:
                    session.add(Approval(case_id=case.id, kind='form_required', summary='Complete the form',
                        encrypted_payload=Vault(master_key).encrypt({'body': 'Please complete our removal form.'})))
            session.commit()
        url = live_app_server(client.app)
        with sync_playwright() as pw:
            browser = getattr(pw, browser_name).launch()
            context = browser.new_context(viewport={'width': 390, 'height': 950})
            context.add_cookies([{'name': 'erasure_session', 'value': client.cookies['erasure_session'], 'url': url}])
            page = context.new_page()
            mutations = []
            page.on('request', lambda req: mutations.append(req.url) if req.method == 'POST' else None)
            for route in ['/cases', '/cases?view=attention', '/batch', '/campaign?tab=messages']:
                page.goto(url + route)
                table = page.locator('table[data-sortable]')
                expect(table).to_be_visible()
                checked_value = None
                if route == '/batch':
                    box = table.locator('input[type=checkbox]').first
                    box.check()
                    checked_value = box.get_attribute('value')
                for header in table.locator('th[data-sort]').all():
                    index = header.evaluate('e => e.cellIndex')
                    for _ in range(2):
                        header.get_by_role('button').click()
                        direction = header.get_attribute('aria-sort')
                        assert direction in ['ascending', 'descending']
                        assert table.locator('th[aria-sort="ascending"], th[aria-sort="descending"]').count() == 1
                        assert table.evaluate('''(table, options) => {
                            const {index, numeric, descending} = options;
                            const values = Array.from(table.tBodies[0].rows, row => row.cells[index].dataset.sortValue ?? row.cells[index].textContent.trim());
                            const collator = new Intl.Collator(undefined, {numeric: true, sensitivity: 'base'});
                            return values.every((v, i) => !i || (numeric ? Number(values[i-1])-Number(v) : collator.compare(values[i-1], v)) * (descending ? -1 : 1) <= 0);
                        }''', {'index': index, 'numeric': header.get_attribute('data-sort') == 'number', 'descending': direction == 'descending'})
                if checked_value:
                    expect(table.locator(f'input[value="{checked_value}"]')).to_be_checked()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert mutations == []
            page.goto(url + '/dashboard')
            expect(page.locator('table')).to_have_count(0)
            expect(page.locator('.recent-request')).to_have_count(5)
            page.goto(url + '/brokers?category=professional')
            page.get_by_role('link', name='Sort by Broker, descending', exact=True).click()
            expect(page.locator('.library-table th').first).to_have_attribute('aria-sort', 'descending')
            page.get_by_role('link', name='Next →', exact=True).click()
            assert 'direction=desc' in page.url and 'category=professional' in page.url
            page.get_by_role('link', name='Sort by Database type, ascending', exact=True).click()
            assert 'page=1' in page.url and 'category=professional' in page.url
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            for route, label in [('/onboarding', 'Profile'), ('/campaign', 'Automatic emails')]:
                page.goto(url + route)
                tabs = page.get_by_role('navigation', name='Settings sections')
                expect(tabs.get_by_role('link', name=label, exact=True)).to_have_attribute('aria-current', 'page')
                expect(page.get_by_text('Country and suggested actions', exact=True)).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.goto(url + '/cases?state=done')
            expect(page.get_by_role('navigation', name='Filter requests').get_by_role('link', name='Done', exact=True)).to_have_attribute('aria-current', 'page')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.goto(url + '/quick-wins?view=saved')
            expect(page.get_by_role('navigation', name='Action views').get_by_role('link', name='Later & skipped', exact=True)).to_have_attribute('aria-current', 'page')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            browser.close()
    engine.dispose()


@pytest.mark.visual
@pytest.mark.parametrize("browser_name", ["chromium", "webkit"])
def test_broker_tabs_navigation_and_form_completion(tmp_path, master_key, live_app_server, browser_name):
    settings = Settings(_env_file=None, master_key=master_key, password_hash=hash_password("test password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog")
    engine = create_db_engine(f"sqlite:///{tmp_path / 'tabs.db'}")
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            broker = Broker(slug="visual-tabs", name="Example People Search", domain="broker.test",
                            category="people_search", contact="privacy@broker.test")
            session.add(broker)
            session.flush()
            case = Case(broker_id=broker.id, state="needs_action", submitted_at=datetime.now(UTC))
            session.add(case)
            session.flush()
            cid = case.id
            store = Store(session, Vault(master_key))
            store.add_event(cid, "request_prepared", "Draft", {"body": "Please delete my records.", "destination": broker.contact})
            store.add_event(cid, "submitted", "Deletion request sent")
            mail = {"id": "visual-reply", "from": broker.contact, "subject": "Please use our form",
                    "body": "Complete our removal form at https://broker.test/remove", "sender_trust": "Authenticated official sender"}
            store.add_event(cid, "reply_received", "Reply received", mail)
            session.add(Approval(case_id=cid, kind="form_required", summary="Complete the removal form",
                                 encrypted_payload=store.vault.encrypt(mail)))
            session.commit()
        url = live_app_server(client.app)
        with sync_playwright() as pw:
            browser = getattr(pw, browser_name).launch()
            for width, javascript in [(1440, True), (390, True), (390, False)]:
                context = browser.new_context(viewport={"width": width, "height": 950}, java_script_enabled=javascript)
                context.add_cookies([{"name": "erasure_session", "value": client.cookies["erasure_session"], "url": url}])
                page = context.new_page()
                page.goto(f"{url}/cases/{cid}")
                expect(page.get_by_role("heading", name="Complete the broker’s form")).to_be_visible()
                expect(page.locator("main details")).to_have_count(0)
                tabs = page.get_by_role("navigation", name="Request sections")
                tabs.get_by_role("link", name="Conversation", exact=True).click()
                expect(page.get_by_text("Complete our removal form at", exact=False)).to_have_count(1)
                expect(page.get_by_text("Please delete my records.", exact=True)).to_be_visible()
                expect(page.locator(".conversation-entry").first).to_contain_text("Broker reply")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.reload()
                expect(tabs.get_by_role("link", name="Conversation")).to_have_attribute("aria-current", "page")
                tabs.get_by_role("link", name="Details", exact=True).click()
                expect(page.get_by_role("heading", name="Full audit history")).to_be_visible()
                expect(page.locator("main details")).to_have_count(0)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.go_back()
                expect(tabs.get_by_role("link", name="Conversation")).to_have_attribute("aria-current", "page")
                tabs.get_by_role("link", name="Overview", exact=True).focus()
                page.keyboard.press("Enter")
                expect(page.get_by_role("button", name="I submitted the form")).to_be_visible()
                page.screenshot(path=tmp_path / f"broker-overview-{browser_name}-{width}-{javascript}.png", full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                context.close()
            # Completing a step stays with this broker and updates its visible status.
            page = browser.new_page()
            page.context.add_cookies([{"name": "erasure_session", "value": client.cookies["erasure_session"], "url": url}])
            page.goto(f"{url}/cases/{cid}")
            page.get_by_role("button", name="I submitted the form").click()
            page.wait_for_url(f"**/cases/{cid}")
            expect(page.locator(".broker-status")).to_contain_text("Broker processing")
            expect(page.locator(".broker-next-step")).to_have_count(0)
            browser.close()
    engine.dispose()


@pytest.mark.visual
@pytest.mark.parametrize("browser_name", ["chromium", "webkit"])
def test_three_action_session_can_end_without_refilling(tmp_path, master_key, live_app_server, browser_name):
    settings = Settings(
        _env_file=None, master_key=master_key, password_hash=hash_password("test password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog",
    )
    engine = create_db_engine(f"sqlite:///{tmp_path / 'simple-home.db'}")
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            Store(session, Vault(master_key)).set_setting("recommendation_country", "DE")
            for index in range(6):
                broker = Broker(slug=f'recent-{index}', name=f'Recent broker with a longer name {index}',
                                domain=f'recent-{index}.invalid')
                session.add(broker)
                session.flush()
                session.add(Case(broker_id=broker.id, state='submitted'))
            session.commit()
        url = live_app_server(client.app)
        with sync_playwright() as pw:
            browser_type = getattr(pw, browser_name)
            if not Path(browser_type.executable_path).exists():
                pytest.skip(f"Install the test browser with: uv run playwright install {browser_name}")
            browser = browser_type.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            page.context.add_cookies([{"name": "erasure_session", "value": client.cookies["erasure_session"], "url": url}])
            page.goto(url + "/dashboard")
            expect(page.locator(".quick-win")).to_have_count(3)
            expect(page.locator('.dashboard-requests table')).to_have_count(0)
            expect(page.locator('.recent-request')).to_have_count(6)
            assert page.locator('.dashboard-requests').bounding_box()['height'] < 600
            assert page.locator('.recent-request').first.get_attribute('href').startswith('/cases/')
            expect(page.locator('.quick-win-copy p:not(.quick-win-instruction)')).to_have_count(3)
            expect(page.locator('#gmail-connection')).to_have_attribute('href', '/gmail/connect')
            for width in (390, 760, 1440):
                page.set_viewport_size({'width': width, 'height': 1050})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.locator('.recent-request').first.click()
            page.wait_for_url('**/cases/*')
            page.goto(url + '/dashboard')
            expect(page.locator('.primary-nav > a')).to_have_count(3)
            expect(page.locator('.nav-group')).to_have_count(0)
            # The compact controls now share this panel with the requested send feed.
            controls_height = (page.locator('.automation-strip').bounding_box()['height']
                               - page.locator('.sending-activity').bounding_box()['height'])
            assert controls_height < 100
            assert page.locator('.navigation-pill').evaluate('el => getComputedStyle(el).borderRadius') == '999px'
            page.locator('.primary-nav').get_by_role('link', name='Requests', exact=True).click()
            page.wait_for_url('**/cases')
            filters = page.get_by_role('navigation', name='Filter requests')
            expect(filters.get_by_role('link')).to_have_count(4)
            page.get_by_role('link', name='Browse brokers', exact=True).click()
            page.wait_for_url('**/brokers')
            page.get_by_role('link', name='← Back to requests', exact=True).click()
            page.wait_for_url('**/cases')
            page.locator('.primary-nav').get_by_role('link', name='Home', exact=True).click()
            page.wait_for_url('**/dashboard')
            page.locator('.primary-nav').get_by_role('link', name='Settings', exact=True).click()
            page.wait_for_url('**/onboarding')
            page.get_by_role('navigation', name='Settings sections').get_by_role('link', name='Automatic emails', exact=True).click()
            page.wait_for_url('**/campaign')
            page.locator('.primary-nav').get_by_role('link', name='Home', exact=True).click()
            page.wait_for_url('**/dashboard')
            expect(page.get_by_role('region', name='Request progress')).to_be_visible()
            info = page.get_by_label('About quick wins')
            tip = page.locator('.info-tip-content')
            expect(tip).not_to_be_visible()
            info.hover()
            expect(tip).to_be_visible()
            page.locator('h1').hover()
            info.focus()
            expect(tip).to_be_visible()
            page.locator('h1').click()
            expect(tip).not_to_be_visible()
            assert page.locator('.dashboard-quick-wins').bounding_box()['height'] < 650
            for row in page.locator('.quick-win').all():
                controls = row.locator('.quick-win-buttons')
                expect(controls.get_by_role('button', name='Mark done:', exact=False)).to_have_text('Done')
                assert controls.locator('a').bounding_box()['y'] == controls.locator('button').bounding_box()['y']
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=tmp_path / f"simple-home-{browser_name}.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            info.click()
            expect(tip).to_be_visible()
            info.click()
            for remaining in (2, 1, 0):
                page.locator('.quick-win').first.get_by_role('button', name='Later', exact=True).click()
                expect(page.locator('.quick-win')).to_have_count(remaining)
            page.reload()
            expect(page.locator('.quick-win')).to_have_count(0)
            expect(page.get_by_role('button', name='Do more', exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role('button', name='Do more', exact=True).click()
            expect(page.locator('.quick-win')).to_have_count(3)
            page.get_by_role('link', name='Later & skipped', exact=True).click()
            expect(page.locator('.quick-win')).to_have_count(3)
            page.locator('.quick-win').first.get_by_role('button', name='Show again', exact=True).click()
            page.get_by_role('link', name='Later & skipped', exact=True).click()
            expect(page.locator('.quick-win')).to_have_count(2)
            browser.close()
        with Session(engine) as session:
            assert session.get(AppSetting, "automatic_campaign") is None
            unchanged = list(session.scalars(select(Case)))
            assert len(unchanged) == 6 and all(case.state == 'submitted' for case in unchanged)
    engine.dispose()


@pytest.mark.visual
@pytest.mark.parametrize("browser_name", ["chromium", "webkit"])
@pytest.mark.parametrize("width", [390, 1440])
def test_identity_and_guided_steps_fit_browsers(tmp_path, master_key, live_app_server, browser_name, width):
    settings = Settings(
        _env_file=None, master_key=master_key, password_hash=hash_password("test password"),
        session_secret=generate_session_secret(), templates_dir=ROOT / "templates",
        static_dir=ROOT / "static", catalog_dir=ROOT / "catalog",
    )
    engine = create_db_engine(f"sqlite:///{tmp_path / 'setup-visual.db'}")
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "test password"})
        url = live_app_server(client.app)
        with sync_playwright() as pw:
            browser_type = getattr(pw, browser_name)
            if not Path(browser_type.executable_path).exists():
                pytest.skip(f"Install the test browser with: uv run playwright install {browser_name}")
            browser = browser_type.launch()
            page = browser.new_page(viewport={"width": width, "height": 1000}, java_script_enabled=False)
            page.context.add_cookies([{"name": "erasure_session",
                                      "value": client.cookies["erasure_session"], "url": url}])
            page.goto(url + "/onboarding")
            expect(page.get_by_role('heading', name='Profile', exact=True)).to_be_visible()
            expect(page.locator('.profile-form details')).to_have_count(0)
            expect(page.locator('[name="work_email"]')).to_be_visible()
            expect(page.locator('[name="postal_address"]')).to_be_visible()
            country_help = page.get_by_label('Why we ask for your country', exact=True)
            country_help.focus()
            expect(page.get_by_role('tooltip')).to_be_visible()
            country_help.click()
            expect(page.get_by_role('tooltip')).to_be_visible()
            assert page.get_by_role('tooltip').bounding_box()['x'] >= 0
            assert not page.locator('[name="postal_address"]').get_attribute("required")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role('heading', name='Profile', exact=True).click()
            page.screenshot(path=str(tmp_path / f'profile-{browser_name}-{width}.png'), full_page=True)
            page.goto(url + "/quick-wins?view=all#bookyourdata")
            page.locator("#bookyourdata").get_by_text("Steps and what you’ll need", exact=True).click()
            expect(page.locator("#bookyourdata ol")).to_be_visible()
            assert "Turnstile" in page.locator("#bookyourdata").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            browser.close()


@pytest.mark.visual
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("browser_name", ["chromium", "webkit"])
def test_regional_guides_expand_without_overflow(tmp_path, master_key, live_app_server, width, browser_name):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'guides-visual.db'}")
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
            creditsafe_id = session.scalar(select(Broker.id).where(Broker.domain == 'creditsafe.com'))
        with sync_playwright() as pw:
            browser = getattr(pw, browser_name).launch()
            page = browser.new_page(viewport={"width": width, "height": 900})
            base_url = live_app_server(client.app)
            page.context.add_cookies(
                [
                    {
                        "name": "erasure_session",
                        "value": client.cookies["erasure_session"],
                        "url": base_url,
                    }
                ]
            )
            page.goto(base_url + "/brokers?view=guides")
            expect(page.get_by_role('form', name='Filter brokers')).to_be_visible()
            assert page.locator('.library-table tbody tr').count() == 50
            if width > 760:
                xs = [el.bounding_box()['x'] for el in page.locator('.library-row-action a').all()]
                assert max(xs) - min(xs) < 1
                controls = page.locator('.library-filters input[type=search], .library-filters select').all()
                ys = [el.bounding_box()['y'] for el in controls]
                assert max(ys) - min(ys) < 1
            page.get_by_label('Search brokers').fill('AZ Direct')
            page.get_by_role('button', name='Apply filters').click()
            page.get_by_role('link', name='Details for AZ Direct', exact=False).first.click()
            assert '/cases/' in page.url
            expect(page.locator('.library-table')).to_have_count(0)
            expect(page.locator('.broker-status')).to_contain_text('Not started')
            listing_url = base_url + '/brokers?view=guides&q=AZ+Direct'
            page.get_by_role('navigation', name='Request sections').get_by_role('link', name='Details', exact=True).click()
            guide = page.locator(".broker-guide").filter(has_text="AZ DIAS").first
            expect(guide.get_by_role("heading", name="What to do")).to_be_visible()
            expect(guide.get_by_text("70 million", exact=False)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert guide.evaluate("e => e.scrollWidth <= e.clientWidth")
            for broker_name in ("Creditsafe", "Dun & Bradstreet"):
                page.goto(listing_url)
                page.get_by_label('Search brokers').fill(broker_name)
                page.get_by_role('button', name='Apply filters').click()
                if broker_name == 'Creditsafe':
                    # Research stays accessible via existing history, not in the usable library.
                    expect(page.get_by_role('heading', name='No matching brokers')).to_be_visible()
                    page.goto(f'{base_url}/cases/broker/{creditsafe_id}')
                else:
                    page.locator('.library-row-action a').first.click()
                page.get_by_role('navigation', name='Request sections').get_by_role('link', name='Details', exact=True).click()
                regional_guide = page.locator(".broker-guide").filter(
                    has=page.get_by_role(
                        "heading", name="Choose the relevant country and controller", include_hidden=True
                    )
                ).filter(has_text=broker_name).first
                routes = regional_guide.locator("section").filter(
                    has=page.get_by_role("link", name="Regional source", include_hidden=True)
                )
                assert routes.count() >= 2
                for route in routes.all():
                    expect(route.get_by_text("Information needed", exact=True)).to_be_visible()
                    expect(route.get_by_role("link", name="Regional source").first).to_be_visible()
                    assert route.evaluate("e => e.scrollWidth <= e.clientWidth")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.evaluate("Array.from(document.querySelectorAll('main *')).filter(e => e.scrollWidth > e.clientWidth).map(e => [e.tagName, e.className, e.textContent.slice(0, 120)])")
            page.goto(base_url + '/brokers')
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role('link', name='Reset', exact=True).click()
            expect(page.get_by_label('Removal route', exact=True)).to_have_count(0)
            page.get_by_label('Database type', exact=True).select_option('professional')
            page.get_by_role('button', name='Apply filters').click()
            assert page.locator('.library-table tbody tr').count() > 0
            assert all(text == 'Sales databases' for text in page.locator('td[data-label="Database type"]').all_text_contents())
            page.get_by_role('link', name='Details for', exact=False).first.click()
            assert '/cases/' in page.url
            expect(page.locator('.library-filters')).to_have_count(0)
            page.go_back()
            expect(page.get_by_label('Database type', exact=True)).to_have_value('professional')
            page.get_by_label('Search brokers').fill('not-a-real-broker-0000')
            page.get_by_role('button', name='Apply filters').click()
            expect(page.get_by_role('heading', name='No matching brokers')).to_be_visible()
            page.get_by_role('link', name='Reset', exact=True).click()
            page.screenshot(path=tmp_path / f'broker-library-{browser_name}-{width}.png', full_page=True)
            browser.close()


@pytest.mark.visual
@pytest.mark.parametrize("entry", ["/quick-wins?view=all", "/dashboard"])
def test_quick_wins_click_persists_and_undo_works(tmp_path, master_key, live_app_server, entry):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'quick-wins.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    app = create_app(settings, engine)
    with TestClient(app) as client:
        assert client.get("/quick-wins", follow_redirects=False).status_code in {302, 303}
        client.post("/login", data={"password": "test password"})
        assert client.post("/quick-wins/ddv-robinson", data={"csrf": "invalid"}).status_code == 403
        with Session(engine) as session:
            Store(session, Vault(master_key)).set_setting("recommendation_country", "DE")
        with sync_playwright() as pw:
            base_url = live_app_server(app)
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.context.add_cookies(
                [
                    {
                        "name": "erasure_session",
                        "value": client.cookies["erasure_session"],
                        "url": base_url,
                    }
                ]
            )
            page.goto(base_url + entry)
            assert "Request pipeline" not in page.content()
            total = len(resources(settings)["items"])
            assert page.locator(".quick-win").count() == (3 if entry == "/dashboard" else total)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            # Use a visible suggestion; ranking is driven by country and reviewed context.
            target_name = (page.locator('.quick-win button.quick-done').first.get_attribute('aria-label').removeprefix('Mark done: ')
                           if entry == "/dashboard" else "DDV Robinsonliste")
            page.get_by_role("button", name=f"Mark done: {target_name}", exact=True).click()
            assert page.url.split("#")[0] == base_url + entry
            page.reload()
            if entry == "/dashboard":
                assert (
                    page.get_by_role("button", name=f"Undo: {target_name}", exact=True).count()
                    == 0
                )
                assert page.locator('.quick-win').count() == 2
                page.goto(base_url + '/quick-wins?view=all')
            assert (
                page.get_by_role(
                    "button", name=f"Undo: {target_name}", exact=True
                ).get_attribute("aria-pressed")
                == "true"
            )
            page.get_by_role("button", name=f"Undo: {target_name}", exact=True).click()
            page.reload()
            assert page.get_by_role(
                "button", name=f"Mark done: {target_name}", exact=True
            ).count() == (0 if entry == "/dashboard" else 1)
            page.set_viewport_size({"width": 1440, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.get_by_role(
                "button", name="Mark done: Seamless.AI privacy form", exact=True
            ).click()
            page.goto(base_url + "/cases?state=done")
            assert page.locator(".status-done").count() >= 1
            assert page.locator(".status-done").first.inner_text() == "Done"
            browser.close()


@pytest.mark.visual
@pytest.mark.parametrize("width", [390, 1440])
def test_completed_quick_wins_use_explicit_controls(tmp_path, master_key, live_app_server, width):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'completed-icons.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    app = create_app(settings, engine)
    with TestClient(app) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            broker = session.scalar(select(Broker).where(Broker.domain == "peopledatalabs.com"))
            session.add(Case(broker_id=broker.id, state="removed"))
            session.add(AppSetting(key="quick_win:leadiq", value="2026-09-28"))
            session.commit()
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 1000})
            url = live_app_server(app)
            page.context.add_cookies(
                [
                    {
                        "name": "erasure_session",
                        "value": client.cookies["erasure_session"],
                        "url": url,
                    }
                ]
            )
            page.goto(url + "/quick-wins?view=all")
            assert page.locator(".quick-check").count() == 0
            expect(page.locator("#people-data-labs .quick-win-buttons .status")).to_have_text("Done")
            assert page.locator("#people-data-labs button.quick-done").count() == 0
            assert page.get_by_role("button", name="Undo: LeadIQ removal form").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#people-data-labs").get_by_text("Evidence and coverage", exact=True).click()
            note = page.locator("#people-data-labs .scale-note")
            assert "Nearly 3B person records" in note.inner_text()
            note.locator("summary").click()
            assert "not proof they hold your data" in note.inner_text()
            assert note.get_by_role("link", name="Size source").is_visible()
            page.goto(url + "/dashboard")
            showcase = page.get_by_role("region", name="Broker showcase")
            assert showcase.locator(".scale-item").count() == 4
            assert showcase.get_by_role("heading").count() == 0
            assert "A few requests can reach" not in showcase.inner_text()
            # A standalone checklist tick without a linked request is not counted.
            assert page.locator(".scale-item.is-done").count() == 1
            assert page.locator(".scale-outcome").inner_text() == "Broker reported deletion"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            browser.close()
    engine.dispose()


@pytest.mark.visual
def test_dashboard_draft_status_updates_without_reload(tmp_path, master_key, live_app_server):
    from erasure import campaign
    from erasure.workflow import Workflow

    engine = create_db_engine(f"sqlite:///{tmp_path / 'live-status.db'}")
    settings = Settings(
        _env_file=None, live_submissions=True,
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
    )
    app = create_app(settings, engine)
    with TestClient(app) as client:
        assert client.get("/api/status").status_code == 401
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            store = Store(session, Vault(master_key))
            profile = store.save_profile(
                {"full_name": "Test Person", "email": "p@example.test"}, "Test Person"
            )
            profile.started_at = datetime.now(UTC)
            store.set_setting("preparation_last_check", datetime.now(UTC).isoformat())
            store.enqueue("prepare_backlog", {}, run_at=datetime.now(UTC) + timedelta(minutes=3))
            workflow = Workflow(session, store, settings)
            campaign.enable(workflow, 20, campaign.preview_hash(workflow), include_new=True)
            store.set_setting('gmail_token', {'access_token': 'synthetic'}, encrypted=True)
            store.set_setting('gmail_last_sync', datetime.now(UTC).isoformat())
            store.set_setting('campaign_last_tick', datetime.now(UTC).isoformat())
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            url = live_app_server(app)
            page.context.add_cookies(
                [
                    {
                        "name": "erasure_session",
                        "value": client.cookies["erasure_session"],
                        "url": url,
                    }
                ]
            )
            page.clock.install()
            page.goto(url + "/dashboard")
            assert "Prepare Backlog" not in page.inner_text("main")
            expect(page.locator('#gmail-connection-label')).to_have_text('Gmail connected')
            expect(page.locator('#gmail-connection')).to_have_attribute('href', '/campaign#mailbox-heading')
            expect(page.locator('#automation-title')).to_have_text('Running')
            expect(page.locator('#automation-instruction')).to_be_hidden()
            expect(page.locator('#sending-empty')).to_be_visible()
            expect(page.locator('#sending-feed li')).to_have_count(0)
            expect(page.locator('.sending-activity a, .sending-activity button, .sending-activity input')).to_have_count(0)
            assert not page.locator("#status-refresh-error").is_visible()
            expect(page.locator('#progress-plot')).to_be_hidden()
            with Session(engine) as session:
                broker = Broker(slug='refresh-graph', name='Chart refresh')
                session.add(broker)
                session.flush()
                case = Case(broker_id=broker.id, state='removed', completed_at=datetime.now(UTC))
                session.add(case)
                session.flush()
                session.add(Event(case_id=case.id, kind='submitted', summary='Sent', created_at=datetime.now(UTC) - timedelta(days=1)))
                session.commit()
                Store(session, Vault(master_key)).set_setting(
                    "campaign_last_tick",
                    (datetime.now(UTC) - timedelta(minutes=20)).isoformat(),
                )
            with page.expect_response("**/api/status"):
                page.clock.fast_forward(4 * 60 * 60 * 1000)
            expect(page.locator('#automation-instruction')).to_be_visible()
            expect(page.locator('#progress-plot')).to_be_visible()
            expect(page.locator('#progress-maximum')).to_have_text('1')
            expect(page.locator('#completion-graph-desc')).to_contain_text('1 sent and 1 currently completed')
            expect(page.locator('#sent-request-count')).to_have_text('1')
            expect(page.locator('#sending-empty')).to_be_hidden()
            expect(page.locator('#sending-feed li')).to_have_count(1)
            expect(page.locator('#sending-feed')).to_contain_text('Chart refresh')
            expect(page.locator('#sending-feed')).to_contain_text('Request sent')
            # New receipts arrive at the bottom, capped at three; broker text is not HTML.
            with Session(engine) as session:
                broker = session.scalar(select(Broker).where(Broker.slug == 'refresh-graph'))
                broker.name = '<img src=x onerror=alert(1)> Example Broker'
                case_id = session.scalar(select(Case.id).where(Case.broker_id == broker.id))
                session.add_all([Event(case_id=case_id, kind='reply_sent', summary='Sent follow-up') for _ in range(3)])
                session.commit()
            with page.expect_response('**/api/status'):
                page.clock.fast_forward(30_000)
            expect(page.locator('#sending-feed li')).to_have_count(3)
            expect(page.locator('#sending-feed li').last).to_contain_text('Follow-up sent')
            expect(page.locator('#sending-feed img')).to_have_count(0)
            page.clock.fast_forward(500)
            for width in (320, 790, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('.campaign-card').screenshot(path=str(tmp_path / 'sending-feed.png'), animations='disabled')
            ids = page.locator('#sending-feed li').evaluate_all('rows => rows.map(row => row.dataset.eventId)')
            with page.expect_response('**/api/status'):
                page.clock.fast_forward(30_000)
            assert page.locator('#sending-feed li').evaluate_all('rows => rows.map(row => row.dataset.eventId)') == ids
            expect(page.locator('#sending-next')).to_contain_text('Background checks need attention')
            expect(page.locator('#completed-request-count')).to_have_text('1')
            expect(page.locator('#automation-instruction')).to_contain_text('Background checks are delayed')
            expect(page.locator('#automation-title')).to_have_text('Needs attention')
            expect(page.get_by_role('button', name='Retry checks', exact=True)).to_be_visible()
            assert page.get_by_text("Email activity and controls", exact=True).count() == 0
            page.route("**/api/status", lambda route: route.abort())
            page.clock.fast_forward(30_000)
            expect(page.locator("#status-refresh-error")).to_be_visible()
            assert "out of date" in page.locator("#status-refresh-error").inner_text()
            expect(page.locator('#automation-title')).to_have_text('Status unavailable')
            expect(page.locator('#sending-next')).to_have_text('Live sending status is unavailable.')
            expect(page.locator('#sending-feed')).to_contain_text('Example Broker')
            assert page.locator("#status-refresh-error").is_visible()
            expect(page.locator('#gmail-connection')).to_have_attribute('data-connected', 'unknown')
            expect(page.locator('#gmail-connection-label')).to_have_text('Gmail status unavailable')
            page.unroute("**/api/status")
            with Session(engine) as session:
                Store(session, Vault(master_key)).set_setting(
                    "campaign_last_tick", datetime.now(UTC).isoformat()
                )
            with page.expect_response("**/api/status"):
                page.clock.fast_forward(30_000)
            expect(page.locator('#automation-title')).to_have_text('Running')
            expect(page.locator('#automation-instruction')).to_be_hidden()
            expect(page.get_by_role('button', name='Pause', exact=True)).to_be_visible()
            expect(page.locator('#gmail-connection-label')).to_have_text('Gmail connected')
            with Session(engine) as session:
                Store(session, Vault(master_key)).set_setting('gmail_error', 'synthetic expired grant')
            with page.expect_response('**/api/status'):
                page.clock.fast_forward(30_000)
            expect(page.locator('#gmail-connection-label')).to_have_text('Reconnect Gmail')
            expect(page.locator('#sending-next')).to_have_text('Gmail needs reconnection.')
            expect(page.locator('#gmail-connection')).to_have_attribute('href', '/gmail/connect')
            expect(page.locator('#gmail-connection')).to_have_attribute('data-connected', 'false')
            assert not page.locator("#status-refresh-error").is_visible()
            browser.close()
    engine.dispose()


@pytest.mark.visual
def test_empty_batch_stays_on_review_page(tmp_path, master_key, live_app_server):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'empty-batch.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
        live_submissions=True,
    )
    app = create_app(settings, engine)
    with TestClient(app) as client:
        client.post("/login", data={"password": "test password"})
        with Session(engine) as session:
            broker = Broker(
                slug="batch-canary",
                name="Batch Canary",
                domain="canary.test",
                contact="privacy@canary.test",
                last_validated_at=datetime.now(UTC),
            )
            session.add(broker)
            session.flush()
            case = Case(broker_id=broker.id, state="prepared")
            session.add(case)
            session.commit()
            cid = case.id
        with sync_playwright() as pw:
            url = live_app_server(app)
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.context.add_cookies(
                [
                    {
                        "name": "erasure_session",
                        "value": client.cookies["erasure_session"],
                        "url": url,
                    }
                ]
            )
            page.goto(url + "/batch")
            page.get_by_role("button", name="Queue selected", exact=False).click()
            assert page.get_by_role("alert").inner_text() == "Select at least one request."
            assert "/batch?error=empty" in page.url
            browser.close()
        with Session(engine) as session:
            assert session.get(Case, cid).state == "prepared"
            assert not list(session.scalars(select(Job).where(Job.kind == "submit_case")))


@pytest.mark.visual
@pytest.mark.parametrize("has_form", [False, True])
def test_next_step_browser_flow_opens_reply_and_closes_task_after_sending(
    tmp_path, master_key, monkeypatch, has_form, live_app_server
):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'next-step.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("browser flow password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
        live_submissions=True,
    )
    sent = []

    def fake_send(client, plan):
        sent.append(plan)
        return "gmail-thread:synthetic-reply"

    monkeypatch.setattr("erasure.workflow.GmailClient.send", fake_send)
    app = create_app(settings, engine)
    with TestClient(app, follow_redirects=False) as client:
        client.post("/login", data={"password": "browser flow password"})
        with Session(engine) as session:
            broker = Broker(
                slug="flow-test",
                name="Flow Test",
                domain="broker.test",
                contact="privacy@broker.test",
            )
            session.add(broker)
            session.flush()
            case = Case(broker_id=broker.id, state="needs_action", submitted_at=datetime.now(UTC))
            session.add(case)
            session.flush()
            action = Approval(
                case_id=case.id,
                kind="ambiguous_reply",
                summary="Reply needs classification",
                encrypted_payload=Vault(master_key).encrypt(
                    {
                        "body": "Please provide your full name and email address."
                        + (" https://broker.test/remove" if has_form else "")
                    }
                ),
            )
            session.add(action)
            session.commit()
            cid, aid = case.id, action.id
        with sync_playwright() as pw:
            base_url = live_app_server(app)
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.context.add_cookies(
                [
                    {
                        "name": "erasure_session",
                        "value": client.cookies["erasure_session"],
                        "url": base_url,
                    }
                ]
            )
            page.goto(f"{base_url}/cases/{cid}?tab=details&correct=1&step={aid}")
            page.get_by_label("What happened?").select_option("needs_action")
            page.get_by_role("button", name="Save outcome").click()
            page.wait_for_url(f"**/cases/{cid}?step_saved=1#next-step")
            assert (
                page.locator("#next-step").get_by_role("status").filter(has_text="Saved:").inner_text()
                == "Saved: this request needs another step. Nothing has been sent."
            )
            assert page.locator("#next-step").is_visible()
            assert page.get_by_label("Message", exact=True).is_visible(), page.locator(
                "#reply-composer"
            ).evaluate("el => el.outerHTML")
            assert (
                "Thank you for your response"
                in page.get_by_label("Message", exact=True).input_value()
            )
            assert "Needs your input:" in page.locator("#reply-composer").inner_text()
            assert not sent
            page.get_by_role("button", name="Send follow-up", exact=True).click()
            assert page.get_by_label("Message", exact=True).evaluate("el => !el.validity.valid")
            assert not sent
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.goto(f"{base_url}/actions")
            assert page.get_by_role("button", name="Approve", exact=True).count() == 0
            expect(page).to_have_url(base_url + '/cases?view=attention')
            page.get_by_role("link", name="Flow Test →", exact=True).click()
            if has_form:
                assert (
                    page.get_by_role("link", name="Open broker form ↗").get_attribute("href")
                    == "https://broker.test/remove"
                )
                page.get_by_role("button", name="I submitted the form").click()
                page.wait_for_url(f"**/cases/{cid}")
                assert not sent
            else:
                page.get_by_label("Message", exact=True).fill("Please check my existing record.")
                page.get_by_role("button", name="Send follow-up", exact=True).click()
                page.wait_for_url(f"**/cases/{cid}")
                assert len(sent) == 1
                assert sent[0].body == "Please check my existing record."
            page.goto(f"{base_url}/actions")
            assert page.get_by_role('cell', name='No requests need your attention.', exact=True).is_visible()
            browser.close()
        with Session(engine) as session:
            assert session.get(Approval, aid).status == "approved"
            assert session.get(Case, cid).state == "processing"
    engine.dispose()


@pytest.mark.visual
def test_dashboard_and_actions_render_without_horizontal_overflow(
    tmp_path: Path, master_key: str
) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'visual.db'}")
    settings = Settings(
        master_key=master_key,
        password_hash=hash_password("this is a visual test password"),
        session_secret=generate_session_secret(),
        templates_dir=ROOT / "templates",
        static_dir=ROOT / "static",
        catalog_dir=ROOT / "catalog",
        live_submissions=True,
    )
    with TestClient(create_app(settings, engine)) as client:
        client.post("/login", data={"password": "this is a visual test password"})
        with Session(engine) as session:
            store = Store(session, Vault(master_key))
            store.save_profile(
                {
                    "full_name": "Synthetic Person",
                    "email": "privacy@example.test",
                    "other_emails": ["professional@example.test"],
                    "postal_address": "1 Example Street",
                },
                "Synthetic Person",
            )
            store.set_setting("gmail_token", {"access_token": "synthetic"}, encrypted=True)
            brokers = session.scalars(select(Broker).limit(4)).all()
            states = ("submitted", "prepared", "needs_action", "candidate")
            cases: list[Case] = []
            for broker, state in zip(brokers, states, strict=True):
                broker.last_validated_at = datetime.now(UTC)
                case = Case(
                    broker_id=broker.id,
                    state=state,
                    submitted_at=datetime.now(UTC) if state == "submitted" else None,
                    next_action_at=(
                        datetime.now(UTC) + timedelta(days=28) if state == "submitted" else None
                    ),
                )
                session.add(case)
                cases.append(case)
            session.flush()
            session.add(
                IncomingMessage(
                    id="synthetic-reply",
                    encrypted_payload=Vault(master_key).encrypt(
                        {
                            "subject": "A readable reply",
                            "from": "privacy@example.test",
                            "date": "Today",
                            "body": "Your request was received.\n\nhttps://example.test/"
                            + "a" * 1000
                            + "\n<script>alert('unsafe')</script>\n"
                            + "More details.\n" * 80,
                        }
                    ),
                )
            )
            session.add(
                Event(
                    case_id=cases[0].id,
                    kind="submitted",
                    summary="Deletion request sent by email",
                )
            )
            session.add(
                Approval(
                    case_id=cases[2].id,
                    kind="browser_challenge",
                    summary="Complete the verified broker removal form",
                    encrypted_payload=Vault(master_key).encrypt(
                        {"action_url": "https://example.test/privacy"}
                    ),
                )
            )
            session.add(
                Job(
                    kind="poll_gmail",
                    encrypted_payload=Vault(master_key).encrypt({}),
                    status="done",
                    updated_at=datetime.now(UTC),
                )
            )
            session.add(
                Job(
                    kind="follow_up",
                    encrypted_payload=Vault(master_key).encrypt({"case_id": cases[0].id}),
                    run_at=datetime.now(UTC) + timedelta(days=28),
                )
            )
            session.commit()

        pages = {
            "dashboard-desktop": (client.get("/dashboard").text, {"width": 1440, "height": 1000}),
            "actions-mobile": (client.get("/actions").text, {"width": 390, "height": 844}),
            "dashboard-mobile": (client.get("/dashboard").text, {"width": 390, "height": 844}),
            "inbox-mobile": (client.get("/inbox").text, {"width": 390, "height": 844}),
            "campaign-mobile": (client.get("/campaign").text, {"width": 390, "height": 844}),
            "campaign-desktop": (client.get("/campaign").text, {"width": 1440, "height": 1000}),
        }

    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    css += (ROOT / "static" / "editorial.css").read_text(encoding="utf-8")
    css += (ROOT / "static" / "app-layout.css").read_text(encoding="utf-8")
    css += (ROOT / "static" / "themes.css").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name, (html, viewport) in pages.items():
                page = browser.new_page(viewport=viewport)
                page.emulate_media(reduced_motion="reduce")

                # Exercise the actual stylesheet URLs rather than injecting CSS;
                # an unversioned request simulates Chrome's stale legacy cache.
                def serve(route, request, rendered_html=html):
                    url = route.request.url
                    if "/static/" in url:
                        route.fulfill(content_type="text/css", body=css if "?v=" in url else "")
                    else:
                        route.fulfill(content_type="text/html", body=rendered_html)

                page.route("http://erasure.test/**", serve)
                page.goto("http://erasure.test/", wait_until="networkidle")
                assert page.locator("main").is_visible()
                if name == "dashboard-desktop":
                    quick_wins = page.locator(".dashboard-quick-wins").bounding_box()
                    requests = page.locator(".dashboard-requests").bounding_box()
                    assert abs(quick_wins["y"] - requests["y"]) < 1
                if name == "inbox-mobile":
                    body = page.locator(".email-body")
                    assert body.is_visible()
                    assert body.locator("script").count() == 0
                    assert (
                        body.locator("a").first.get_attribute("href")
                        == "https://example.test/" + "a" * 1000
                    )
                    assert body.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
                    assert body.evaluate("el => getComputedStyle(el).whiteSpace") == "pre-wrap"
                if name.startswith("campaign"):
                    checkbox = page.get_by_role("checkbox", name="I authorize ongoing automatic requests")
                    assert not checkbox.is_checked()
                    assert checkbox.bounding_box()["width"] == 20
                    assert page.get_by_role('link', name='See covered brokers and exact emails →').is_visible()
                    assert page.locator('.campaign-routes').count() == 0
                if "desktop" in name:
                    assert (
                        page.locator(".navigation-pill").evaluate("el => getComputedStyle(el).borderRadius")
                        == "999px"
                    )
                    assert not page.locator(".mobile-header").is_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                if name == "actions-mobile":
                    assert page.locator(".mobile-nav").is_visible()
                    assert page.locator(".mobile-nav a").count() == 3
                    # /actions now intentionally uses the same Requests table,
                    # filtered to Needs you; it is no longer a second card view.
                    primary = page.locator("table .broker-link").first
                    assert primary.get_attribute('href').startswith('/cases/')
                    primary_style = primary.evaluate(
                        """element => ({
                            background: getComputedStyle(element).backgroundColor,
                            color: getComputedStyle(element).color,
                            opacity: getComputedStyle(element).opacity,
                            classes: element.className
                        })"""
                    )
                    assert primary_style["background"] != primary_style["color"], primary_style
                screenshot = page.screenshot(path=tmp_path / f"{name}.png", full_page=True)
                assert screenshot.startswith(b"\x89PNG")
                assert len(screenshot) > 20_000
                page.close()
        finally:
            browser.close()
    engine.dispose()
