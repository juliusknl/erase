"""Resumable first-run setup. Drafts never grant sending permission."""

import json
import logging
import re
from datetime import UTC, datetime

import httpx
from fastapi import Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from erasure import appearance, background, campaign, recommendations, reply_assistance
from erasure.gmail import GmailClient, GmailError
from erasure.store import Store
from erasure.workflow import Workflow

DRAFT_KEY = 'setup_draft'
MAILBOX_KEY = 'setup_mailbox'
EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")


def draft(store):
    return store.get_setting(DRAFT_KEY, {})


def needs_setup(store):
    return not store.get_profile() and store.get_setting('setup_manual_complete') != 'true'


def email_address(value):
    return isinstance(value, str) and len(value) <= 254 and bool(EMAIL.fullmatch(value))


def mailbox(store):
    saved = store.get_setting(MAILBOX_KEY, {})
    token = store.get_setting('gmail_token')
    if (token and saved.get('token_hash') == campaign.digest(token)
            and email_address(saved.get('email')) and not store.get_setting('gmail_error')):
        return saved['email']
    return ''


def remember_mailbox(store, address):
    if not email_address(address):
        raise GmailError('Google did not return a valid mailbox address')
    store.set_setting(MAILBOX_KEY, {'email': address,
        'token_hash': campaign.digest(store.get_setting('gmail_token'))}, encrypted=True)


def next_step(store):
    data = draft(store)
    # Keep existing step IDs stable for OAuth callbacks and bookmarked setup pages.
    if data.get('appearance') not in appearance.THEMES:
        return 0
    if data.get('country') not in recommendations.COUNTRIES:
        return 1
    if data['country'] not in recommendations.EEA:
        return 1
    if (not 2 <= len(data.get('full_name', '')) <= 150
            or not (data.get('emails') or data.get('no_matching_email'))
            or len(data.get('emails', [])) > 20
            or any(not email_address(x) for x in data.get('emails', []))):
        return 2
    if not mailbox(store):
        return 3
    return 4


class DraftStore(Store):
    """Read-only profile projection for real request previews, before signing."""

    def get_profile(self):
        data = draft(self)
        return {'full_name': data.get('full_name', ''), 'email': mailbox(self),
                'other_emails': data.get('emails', []), 'residency': 'EU/EEA'}

    def get_signature(self):
        return self.get_profile()['full_name']


def preview(store, settings):
    projected = DraftStore(store.session, store.vault)
    workflow = Workflow(store.session, projected, settings)
    country = draft(store)['country']
    rows = campaign.preview_rows(workflow, country, False)
    available = [r for r in rows if r['plan'] and r['guide'].relevance.category in campaign.DEFAULT_CATEGORIES]
    digest = campaign.preview_hash(workflow, country, False, rows=rows)
    return available, digest


def mount_setup(app, settings, engine, templates, context, require_user, require_csrf,
                require_configured, db_session):
    def redirect(path='/setup'):
        return RedirectResponse(path, status_code=303)

    def render(request, store, step, *, errors=None, values=None, status_code=200):
        token = require_user(request)
        data = values if values is not None else draft(store)
        rows, digest = preview(store, settings) if step == 4 and next_step(store) == 4 else ([], '')
        credentials = store.get_setting('gmail_client_config', {})
        worker = getattr(app.state, 'worker_thread', None)
        return templates.TemplateResponse(request, 'setup.html', context(request, token,
            step=step, draft=data, errors=errors or {}, countries=recommendations.COUNTRIES,
            reply_assistance=reply_assistance.public_status(settings, store),
            background_status=background.status(settings),
            assistance_error=reply_assistance.ERRORS.get(request.query_params.get('assistance_error'), ''),
            email_supported=data.get('country') in recommendations.EEA,
            mailbox=mailbox(store), ready_rows=rows, preview_hash=digest,
            worker_ready=bool(worker and worker.is_alive()),
            google_ready=settings.demo_mode or bool(credentials or (settings.google_client_id and settings.google_client_secret)),
            helper=int(request.query_params['helper']) if request.query_params.get('helper') in {'1', '2', '3', '4'} else 1,
            callback_uri=settings.base_url.rstrip('/') + '/gmail/callback',
        ), status_code=status_code)

    @app.get('/setup')
    def setup_page(request: Request, step: int | None = None, session: Session = Depends(db_session)):
        require_user(request)
        store = Store(session, require_configured())
        if not needs_setup(store):
            return redirect('/dashboard')
        reached = next_step(store)
        current = min(reached, max(0, step)) if step is not None else reached
        errors = {}
        if request.query_params.get('connection') == 'failed':
            errors['mailbox'] = 'Gmail was not connected. Your details are saved. Try again when you’re ready.'
        if request.query_params.get('connection') == 'expired':
            errors['mailbox'] = 'Your local session expired. Please connect Gmail again; your setup is saved.'
        return render(request, store, current, errors=errors)

    @app.post('/setup/appearance')
    def setup_appearance(request: Request, csrf: str = Form(''), theme: str = Form(''),
                         session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        if not needs_setup(store):
            return redirect('/appearance')
        if theme not in appearance.THEMES:
            return render(request, store, 0, errors={'appearance': 'Choose one of the four appearances.'}, status_code=422)
        data = draft(store)
        data['appearance'] = theme
        store.set_setting(DRAFT_KEY, data, encrypted=True)
        return appearance.remember(redirect('/setup?step=1'), theme, settings)

    @app.post('/setup/country')
    def setup_country(request: Request, csrf: str = Form(''), country: str = Form(''),
                      intent: str = Form('continue'), session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        if store.get_profile():
            return redirect('/dashboard')
        if needs_setup(store) and next_step(store) == 0:
            return redirect()
        data = draft(store)
        if not country and intent == 'exit':
            return redirect('/dashboard')
        if country not in recommendations.COUNTRIES:
            return render(request, store, 1, errors={'country': 'Choose where you live.'}, status_code=422)
        data['country'] = country
        store.set_setting(DRAFT_KEY, data, encrypted=True)
        store.set_setting('setup_manual_complete', 'false')
        if intent == 'exit':
            return redirect('/dashboard')
        return redirect('/setup?step=2' if country in recommendations.EEA else '/setup?step=1')

    @app.post('/setup/manual')
    def manual_setup(request: Request, csrf: str = Form(''), session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        if store.get_profile():
            return redirect('/dashboard')
        if next_step(store) == 0:
            return redirect()
        country = draft(store).get('country')
        if country not in recommendations.COUNTRIES:
            return redirect('/setup?step=1')
        store.set_setting('recommendation_country', country, encrypted=True)
        store.set_setting('setup_manual_complete', 'true')
        return redirect('/quick-wins')

    @app.post('/setup/details')
    def setup_details(request: Request, csrf: str = Form(''), full_name: str = Form(''),
                      emails: list[str] = Form([]), no_matching_email: bool = Form(False),
                      intent: str = Form('continue'), session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        if not needs_setup(store):
            return redirect('/dashboard')
        if next_step(store) < 2:
            return redirect()
        data = draft(store)
        name = ' '.join(full_name.split())
        addresses = list(dict.fromkeys(x.strip() for x in emails if x.strip()))
        data.update(full_name=name, emails=addresses, no_matching_email=no_matching_email)
        if intent in {'exit', 'add'} and len(name) <= 150 and len(addresses) <= 20 and all(len(x) <= 254 for x in addresses):
            store.set_setting(DRAFT_KEY, data, encrypted=True)
            if intent == 'exit':
                return redirect('/dashboard')
            return render(request, store, 2, values={**data, 'emails': addresses + ['']})
        errors = {}
        if not 2 <= len(name) <= 150:
            errors['full_name'] = 'Enter your full name (2–150 characters).'
        if len(addresses) > 20 or any(not email_address(x) for x in addresses):
            errors['emails'] = 'Enter valid email addresses, with no more than 20 in total.'
        elif not addresses and not no_matching_email:
            errors['emails'] = 'Add an email you use, or choose to continue without matching emails.'
        # Save valid draft fields even when leaving or another field needs correction.
        saved = draft(store)
        if 'full_name' not in errors:
            saved['full_name'] = name
        if 'emails' not in errors:
            saved.update(emails=addresses, no_matching_email=no_matching_email)
        store.set_setting(DRAFT_KEY, saved, encrypted=True)
        if errors:
            return render(request, store, 2, errors=errors, values=data, status_code=422)
        if intent == 'add':
            return render(request, store, 2, values={**data, 'emails': addresses + ['']})
        return redirect('/dashboard' if intent == 'exit' else '/setup?step=3')

    @app.post('/setup/google-client')
    async def import_google_client(request: Request, csrf: str = Form(''),
                                   client_file: UploadFile | None = None,
                                   session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        if not needs_setup(store) or next_step(store) < 3:
            return redirect()
        try:
            raw = await client_file.read(32_769) if client_file else b''
            if len(raw) > 32_768:
                raise ValueError
            config = json.loads(raw)['web']
            if (not isinstance(config, dict)
                    or not isinstance(config.get('client_id'), str)
                    or not config['client_id'].endswith('.apps.googleusercontent.com')
                    or not isinstance(config.get('client_secret'), str)
                    or not 10 <= len(config['client_secret']) <= 500
                    or settings.base_url.rstrip('/') + '/gmail/callback' not in config.get('redirect_uris', [])):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return render(request, store, 3, errors={'mailbox':
                'Choose the downloaded Google Web application JSON with the callback address shown below. No credentials were changed.'}, status_code=422)
        store.set_setting('gmail_client_config', {k: config[k] for k in ('client_id', 'client_secret')}, encrypted=True)
        # A changed OAuth client cannot reuse the old client's refresh token.
        store.set_setting('gmail_token', {}, encrypted=True)
        store.set_setting(MAILBOX_KEY, {}, encrypted=True)
        return redirect('/setup?step=3')

    @app.post('/setup/start')
    def start_setup(request: Request, csrf: str = Form(''), authorize: bool = Form(False),
                    signature: str = Form(''), preview_hash: str = Form('')):
        require_csrf(request, csrf)
        vault = require_configured()
        with Session(engine) as session:
            store = Store(session, vault)
            if store.get_profile():
                return redirect('/dashboard')
            if next_step(store) != 4:
                return redirect()
            errors = {}
            if not authorize:
                errors['authorize'] = 'Please confirm permission before starting.'
            if ' '.join(signature.split()) != draft(store).get('full_name'):
                errors['signature'] = 'Type your full name exactly as shown above.'
            if not settings.live_submissions:
                errors['start'] = 'This installation is in preview mode. Enable sending with the launcher command below, then return here.'
            worker = getattr(app.state, 'worker_thread', None)
            if not worker or not worker.is_alive():
                errors['start'] = 'The background worker is not running. Restart the local app, then try again. Nothing was sent.'
            rows, expected = preview(store, settings)
            if not rows:
                errors['start'] = 'No automatic requests are available for these details. Add a matching email or explore removal forms.'
            if preview_hash != expected:
                errors['start'] = 'Your details or available requests changed. Review this updated summary and start again.'
            if not errors:
                client = GmailClient(settings, store)
                expected_address = mailbox(store)
                try:
                    address = client.mailbox_address()
                    if address.casefold() != expected_address.casefold():
                        errors['mailbox'] = 'The connected mailbox changed. Reconnect it before continuing.'
                    else:
                        remember_mailbox(store, address)
                except (GmailError, httpx.HTTPError, ValueError):
                    errors['mailbox'] = 'The app could not check your Gmail connection. Reconnect it and try again. Nothing was sent.'
                finally:
                    client.client.close()
            if errors:
                return render(request, store, 4, errors=errors, status_code=422)
            checked_token = campaign.digest(store.get_setting('gmail_token'))

        # Existing Store/campaign methods commit frequently. Binding to an explicit
        # outer transaction with rollback_only makes those commits flush-only.
        # SQLite's write lock serializes double-clicks and competing setup requests.
        with engine.connect() as connection:
            if engine.dialect.name == 'sqlite':
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode='rollback_only') as session:
                    store = Store(session, vault)
                    if store.get_profile():
                        connection.rollback()
                        return redirect('/dashboard')
                    if (next_step(store) != 4 or campaign.digest(store.get_setting('gmail_token')) != checked_token
                            or preview(store, settings)[1] != preview_hash):
                        connection.rollback()
                        return redirect('/setup?step=4')
                    data = DraftStore(session, vault).get_profile()
                    country = draft(store)['country']
                    store.save_profile(data, data['full_name'])
                    store.set_setting('recommendation_country', country, encrypted=True)
                    workflow = Workflow(session, store, settings)
                    campaign.enable(workflow, 20, preview_hash, country, False, include_new=True)
                    store.enqueue_if_missing('poll_gmail', {})
                    store.set_setting('setup_completed_at', datetime.now(UTC).isoformat())
                    store.set_setting(DRAFT_KEY, {}, encrypted=True)
                    session.commit()
                    connection.commit()
            except Exception as exc:
                connection.rollback()
                logging.getLogger(__name__).warning('Setup start rolled back (%s)', type(exc).__name__)
                with Session(engine) as session:
                    return render(request, Store(session, vault), 4, errors={'start':
                        'The app couldn’t start your requests. Your setup is saved and nothing was authorized. Please try again.'}, status_code=503)
        return redirect('/dashboard')
