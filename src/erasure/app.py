from __future__ import annotations

import csv
import hashlib
import io
import re
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from erasure import (
    appearance,
    background,
    broker_library,
    campaign,
    recommendations,
    reply_assistance,
    setup_flow,
)
from erasure.attention import automation_summary, email_only_identity, needs_person
from erasure.auth import LoginThrottle, SessionManager
from erasure.broker_scale import load_scale, scale_progress
from erasure.case_view import conversation
from erasure.catalog import import_cppa_registry, load_curated, load_verified_email
from erasure.config import Settings, get_settings
from erasure.crypto import Vault, VaultError
from erasure.db import engine as default_engine
from erasure.db import init_db
from erasure.email_routes import routes as reviewed_email_routes
from erasure.gmail import SCOPES, GmailClient, GmailError
from erasure.inbox import gmail_link, reconcile_attention, review_message
from erasure.jev import JevError
from erasure.knowledge import guide_index, install_missing, registry_context
from erasure.models import (
    Approval,
    Broker,
    Case,
    Event,
    IncomingMessage,
    Job,
    Profile,
    RouteResearch,
)
from erasure.preparation import email_eligible, pipeline_status, playbook
from erasure.progress_chart import completion_chart
from erasure.quick_wins import mark_done as mark_quick_win_done
from erasure.quick_wins import resources as quick_win_resources
from erasure.replies import request_form_url
from erasure.reply_drafts import prepare_reply
from erasure.store import Store
from erasure.validation import MAX_BATCH_SIZE, is_recently_validated
from erasure.workflow import Workflow

COOKIE = "erasure_session"

STATE_LABELS = {
    "done": "Done",
    "candidate": "Not started",
    "queued": "Queued",
    "prepared": "Ready to send",
    "submitted": "Request sent",
    "processing": "Broker processing",
    "needs_action": "Needs your action",
    "delivery_failed": "Delivery failed",
    "removed": "Done",
    "not_found": "No record found",
    "rejected": "Request rejected",
    "recheck_due": "Recheck due",
    "escalation_ready": "Escalation ready",
    "complaint_approved": "Complaint approved",
}

STATE_HELP = {
    "done": "You marked this request done. Follow-ups are stopped; this is not broker-confirmed deletion.",
    "candidate": "This broker is catalogued but its workflow has not been selected.",
    "queued": "The worker will prepare or send this request shortly.",
    "prepared": "The request is ready and waiting for sending approval.",
    "submitted": "The request was delivered and is waiting for a response.",
    "processing": "The broker acknowledged the request or is working on it.",
    "needs_action": "Automation stopped safely because you need to complete a step.",
    "delivery_failed": "The request could not be delivered and needs review.",
    "removed": "The broker reported that the personal data was removed.",
    "not_found": "The broker reported that it could not find a matching record.",
    "rejected": "The broker declined the request; escalation may be available.",
    "recheck_due": "A scheduled check is ready to run.",
    "escalation_ready": "The broker did not respond after follow-ups.",
    "complaint_approved": "The escalation was reviewed and approved.",
}


def state_label(value: str) -> str:
    return STATE_LABELS.get(value, value.replace("_", " ").title())


def state_help(value: str) -> str:
    return STATE_HELP.get(value, "The latest recorded state for this request.")


def request_history():
    """Sort by correspondence/workflow milestones, not background bookkeeping."""
    activity = select(Event.case_id, func.max(Event.created_at).label('updated')).where(Event.kind.in_([
        'request_prepared', 'submitted', 'reply_received', 'reply_held', 'reply_sent', 'reply_reviewed',
        'reply_reclassified',
        'form_submitted', 'user_completed', 'identity_proof_sent', 'email_confirmation_recorded',
    ])).group_by(Event.case_id).subquery()
    updated = func.coalesce(activity.c.updated, Case.updated_at)
    return select(Case, updated.label('updated')).outerjoin(activity, activity.c.case_id == Case.id).order_by(updated.desc(), Case.id.desc())


def request_progress(session):
    return completion_chart(
        session.scalars(select(Case.completed_at).where(Case.state.in_(['done', 'removed', 'not_found']))),
        sent_dates=session.scalars(select(func.min(Event.created_at)).where(Event.kind == 'submitted').group_by(Event.case_id)),
        started_at=session.scalar(select(func.min(Case.created_at)).where(Case.state != 'candidate')))


def relative_time(value: datetime | None) -> str:
    if value is None:
        return "Not yet"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    seconds = int((value - datetime.now(UTC)).total_seconds())
    future = seconds > 0
    distance = abs(seconds)
    if distance < 60:
        return "in under a minute" if future else "just now"
    if distance < 3600:
        amount, unit = distance // 60, "minute"
    elif distance < 86_400:
        amount, unit = distance // 3600, "hour"
    else:
        amount, unit = distance // 86_400, "day"
    suffix = "" if amount == 1 else "s"
    return f"in {amount} {unit}{suffix}" if future else f"{amount} {unit}{suffix} ago"


def sending_activity(session, automatic, automation, *, demo=False):
    """Read-only receipt and next step; never infer a send from a queued job."""
    recent = session.execute(select(Event.id, Event.kind, Event.created_at, Broker.name)
        .join(Case, Case.id == Event.case_id).join(Broker, Broker.id == Case.broker_id)
        .where(Event.kind.in_(['submitted', 'reply_sent']))
        .order_by(Event.created_at.desc(), Event.id.desc()).limit(3)).all()
    entries = [{'id': event_id, 'broker': name,
                'message': 'Follow-up sent' if kind == 'reply_sent' else 'Request sent',
                'time': relative_time(sent_at),
                'sent_at': (sent_at if sent_at.tzinfo else sent_at.replace(tzinfo=UTC)).isoformat()}
               for event_id, kind, sent_at, name in reversed(recent)]
    last_sent = 'No emails sent yet.'
    if recent:
        _, kind, sent_at, name = recent[0]
        label = 'Last simulated send' if demo else 'Last sent'
        message = 'follow-up' if kind == 'reply_sent' else 'request'
        last_sent = f'{label}: {message} to {name} · {relative_time(sent_at)}.'
    if automation['state'] == 'paused':
        next_step = 'Sending paused. Resume when you’re ready.'
    elif automation['state'] == 'stopped':
        next_step = 'Automatic sending is off.'
    elif automation['state'] != 'running':
        next_step = automation['detail'] + '.'
    elif automatic.get('sending_count'):
        next_step = 'An email is being sent; waiting for Gmail’s response.'
    elif automatic['today'] >= automatic['daily_limit']:
        next_step = 'Daily sending limit reached. Sending can resume after midnight UTC; reply checks continue.'
    elif automatic.get('queued_count'):
        next_step = 'More requests are queued to send automatically, one minute apart.'
    elif automatic.get('research_due') or automatic.get('new_workflows'):
        next_step = ('Preparing more eligible email requests.' if automatic.get('include_new')
                     else 'New email requests are waiting for your permission.')
    elif automatic.get('route_issues'):
        next_step = 'Remaining email routes need review before sending.'
    elif not automatic.get('planned_count'):
        next_step = 'No email requests currently match your profile and permissions.'
    else:
        next_step = ''
    return {'last_sent': last_sent, 'next_step': next_step, 'entries': entries,
            'label': 'Recent simulated sends' if demo else 'Recent sends'}


def create_app(settings: Settings | None = None, db_engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    cookie_name = 'erasure_demo_session' if settings.demo_mode else COOKIE
    embedded_worker = db_engine is None
    db_engine = db_engine or default_engine
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    templates = Jinja2Templates(directory=str(settings.templates_dir))
    broker_scale = load_scale(settings)
    # A prior browser cache can retain CSS from before no-store was introduced.
    # Version browser assets together so cached layout and status code cannot drift.
    stylesheet_bytes = b"".join(
        path.read_bytes()
        for path in sorted([*settings.static_dir.glob('*.css'), *settings.static_dir.glob('*.js')])
    )
    templates.env.globals["css_version"] = hashlib.sha256(stylesheet_bytes).hexdigest()[:16]
    templates.env.globals['demo_mode'] = settings.demo_mode
    templates.env.globals['appearance_themes'] = appearance.THEMES
    templates.env.globals['current_appearance'] = lambda request: appearance.current(request, settings.demo_mode)
    templates.env.filters["state_label"] = state_label
    templates.env.filters["state_help"] = state_help
    templates.env.filters["relative_time"] = relative_time
    templates.env.filters["contact_verified"] = is_recently_validated
    sessions = SessionManager(
        settings.session_secret, settings.password_hash, lifetime_hours=settings.session_hours
    )
    login_throttle = LoginThrottle()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker_stop = threading.Event()
        worker_thread = None
        init_db(db_engine)
        if settings.configured:
            with session_factory() as session:
                current_registry = settings.catalog_dir / "registry2026.csv"
                registry = (
                    current_registry
                    if current_registry.exists()
                    else settings.catalog_dir / "registry2025.csv"
                )
                if (
                    registry.exists()
                    and session.scalar(select(func.count()).select_from(Broker)) < 600
                ):
                    import_cppa_registry(session, registry)
                # Curated definitions load last and are never downgraded by bulk registry metadata.
                curated = settings.catalog_dir / "curated.yml"
                if curated.exists():
                    load_curated(session, curated)
                verified = settings.catalog_dir / "verified-email.yml"
                if verified.exists():
                    load_verified_email(session, verified)
                for supplement in sorted(settings.catalog_dir.glob("verified-20*.yml")):
                    load_verified_email(session, supplement)
                install_missing(session, settings)
                reconcile_attention(Workflow(session, Store(session, require_configured()), settings))
            if embedded_worker:
                from erasure.worker import work_until_stopped

                worker_thread = threading.Thread(
                    target=work_until_stopped,
                    args=(worker_stop,),
                    name="erasure-worker",
                    daemon=True,
                )
                worker_thread.start()
        _app.state.worker_thread = worker_thread
        try:
            yield
        finally:
            worker_stop.set()
            if worker_thread is not None:
                worker_thread.join(timeout=10)

    app = FastAPI(title="erase", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware,
                       allowed_hosts=['127.0.0.1', 'localhost', '[::1]']
                       + (['testserver'] if not embedded_worker else []))

    def browser_error(request, code, message, headers=None):
        return templates.TemplateResponse(request, 'error.html',
            {'code': code, 'message': message}, status_code=code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if 'text/html' in request.headers.get('accept', ''):
            return browser_error(request, 422, 'Some information is missing or invalid. Go back to the previous page, check your entries and try again.')
        # Do not echo submitted passwords, tokens, identity or request bodies.
        return JSONResponse({'detail': 'Some information is missing or invalid'}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def app_error(request: Request, exc: StarletteHTTPException):
        if (
            exc.status_code == 401
            and (request.method == "GET" or request.url.path.startswith('/setup'))
            and not request.url.path.startswith("/api/")
        ):
            return RedirectResponse("/login", status_code=303)
        if 'text/html' in request.headers.get('accept', '') and not request.url.path.startswith('/api/'):
            messages = {401: 'Your dashboard has locked. Unlock it to continue.',
                        403: 'This page has expired. Open the dashboard again and retry your action.',
                        404: 'This page is no longer available. Your request history is still in the dashboard.'}
            return browser_error(request, exc.status_code, messages.get(exc.status_code, str(exc.detail)), exc.headers)
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if settings.demo_mode and response.headers.get('content-type', '').startswith('text/html'):
            from erasure.demo import localize_links

            body = b''.join([chunk async for chunk in response.body_iterator])
            headers = dict(response.headers)
            headers.pop('content-length', None)
            response = HTMLResponse(localize_links(body.decode()), status_code=response.status_code,
                                    headers=headers)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'",
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if settings.base_url.startswith("https://"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    if settings.static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    def db_session():  # type: ignore[no-untyped-def]
        with session_factory() as session:
            yield session

    def require_configured() -> Vault:
        if not settings.configured:
            raise HTTPException(status_code=503, detail="Application secrets are not configured")
        try:
            return Vault(settings.master_key)
        except VaultError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def require_user(request: Request) -> str:
        token = request.cookies.get(cookie_name)
        if sessions.verify(token) is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
        return token or ""

    def require_csrf(request: Request, csrf: str) -> str:
        token = require_user(request)
        if not sessions.verify_csrf(token, csrf):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        return token

    def context(request: Request, token: str, **extra):  # type: ignore[no-untyped-def]
        return {
            "request": request,
            "csrf": sessions.csrf(token),
            "live": settings.live_submissions,
            "broker_scale": broker_scale,
            **extra,
        }

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            cookie_name,
            token,
            httponly=True,
            secure=settings.base_url.startswith("https://"),
            # OAuth returns from accounts.google.com as a cross-site top-level GET.
            # Lax sends the session cookie on that safe navigation; Strict does not.
            samesite="lax",
            max_age=settings.session_hours * 3600,
        )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "application": "erase",
            "configured": settings.configured,
            "live_submissions": settings.live_submissions,
            "demo_mode": settings.demo_mode,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):  # type: ignore[no-untyped-def]
        if sessions.verify(request.cookies.get(cookie_name)) is None:
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/dashboard", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):  # type: ignore[no-untyped-def]
        return templates.TemplateResponse(
            request, "login.html", {"configured": settings.configured}
        )

    @app.post("/login")
    def login(request: Request, password: str = Form(...), session: Session = Depends(db_session)):  # type: ignore[no-untyped-def]
        identity = request.client.host if request.client else "local"
        retry_after = login_throttle.retry_after(identity)
        if retry_after:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "configured": settings.configured,
                    "error": "Too many login attempts. Try again shortly.",
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
        if not settings.configured or not sessions.authenticate(password):
            login_throttle.record_failure(identity)
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "configured": settings.configured,
                    "error": "Invalid password or incomplete setup",
                },
                status_code=401,
            )
        login_throttle.record_success(identity)
        token = sessions.create()
        destination = '/setup' if setup_flow.needs_setup(Store(session, require_configured())) else '/dashboard'
        response = RedirectResponse(destination, status_code=303)
        set_session_cookie(response, token)
        return response

    @app.post("/logout")
    def logout(request: Request, csrf: str = Form(...)):  # type: ignore[no-untyped-def]
        require_csrf(request, csrf)
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(cookie_name)
        return response

    @app.get("/design-preview", response_class=HTMLResponse)
    def design_preview(request: Request):
        token = require_user(request)
        # Temporary, synthetic-only design gallery. No account queries or writes.
        return templates.TemplateResponse(request, "design_preview.html", context(request, token))

    @app.get('/appearance', response_class=HTMLResponse)
    def appearance_page(request: Request):
        token = require_user(request)
        return templates.TemplateResponse(request, 'appearance.html', context(request, token))

    @app.post('/appearance')
    def save_appearance(request: Request, csrf: str = Form(''), theme: str = Form('')):
        require_csrf(request, csrf)
        if theme not in appearance.THEMES:
            raise HTTPException(status_code=422, detail='Choose one of the four appearances.')
        return appearance.remember(RedirectResponse('/appearance?saved=1', status_code=303), theme, settings)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request, session: Session = Depends(db_session)):  # type: ignore[no-untyped-def]
        token = require_user(request)
        vault = require_configured()
        store = Store(session, vault)
        workflow = Workflow(session, store, settings)
        profile = session.get(Profile, 1)
        counts = workflow.dashboard_counts()
        recent_rows = session.execute(request_history().where(Case.state != 'candidate').limit(6)).all()
        recent_cases = [row[0] for row in recent_rows]
        recent_events = session.scalars(
            select(Event).order_by(Event.created_at.desc(), Event.id.desc()).limit(8)
        ).all()
        pending_actions = session.scalars(
            select(Approval)
            .where(Approval.status == "pending")
            .order_by(Approval.created_at)
            .limit(3)
        ).all()
        failed_jobs = (
            session.scalar(select(func.count()).select_from(Job).where(Job.status == "failed")) or 0
        )
        validated_brokers = (
            session.scalar(
                select(func.count())
                .select_from(Broker)
                .where(Broker.last_validated_at >= datetime.now(UTC) - timedelta(days=90))
            )
            or 0
        )
        sync_value = store.get_setting("gmail_last_sync")
        last_gmail_sync = datetime.fromisoformat(sync_value) if sync_value else None
        active_requests = sum(counts.get(item, 0) for item in ("queued", "submitted", "processing"))
        next_actions = recommendations.attention_items(workflow)
        recommended_items = recommendations.session_items(workflow)
        pipeline = pipeline_status(session, store, settings)
        automation = automation_summary(store, pipeline, settings.live_submissions)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            context(
                request,
                token,
                counts=counts,
                progress_chart=request_progress(session),
                sent_requests=session.scalar(select(func.count(func.distinct(Event.case_id)))
                                             .where(Event.kind == "submitted")) or 0,
                pipeline=pipeline,
                automation=automation,
                sending_activity=sending_activity(session, pipeline['automatic'], automation, demo=settings.demo_mode),
                profile=profile,
                setup_pending=setup_flow.needs_setup(store),
                cases=recent_cases,
                request_updated={row[0].id: row[1] for row in recent_rows},
                recent_events=recent_events,
                pending_actions=pending_actions,
                failed_jobs=failed_jobs,
                gmail_connected=bool(store.get_setting("gmail_token")),
                gmail_error=store.get_setting("gmail_error", ""),
                inbox_count=session.scalar(
                    select(func.count())
                    .select_from(IncomingMessage)
                    .where(IncomingMessage.status == "review")
                ),
                last_gmail_sync=last_gmail_sync,
                active_requests=active_requests,
                validated_brokers=validated_brokers,
                quick_wins=recommended_items[:3],
                attention_items=next_actions,
                attention_case_ids={item['case_id'] for item in next_actions},
                action_country=recommendations.country(store),
                action_countries=recommendations.COUNTRIES,
                scale_items=scale_progress(session, broker_scale),
                paused=store.get_setting("paused", "false") == "true",
            ),
        )

    @app.get("/onboarding", response_class=HTMLResponse)
    def onboarding(request: Request, session: Session = Depends(db_session)):  # type: ignore[no-untyped-def]
        token = require_user(request)
        store = Store(session, require_configured())
        return templates.TemplateResponse(
            request,
            "onboarding.html",
            context(
                request,
                token,
                profile=store.get_profile() or {},
                alert_email=store.get_setting("alert_email", ""),
                action_country=recommendations.country(store),
                action_countries=recommendations.COUNTRIES,
                email_supported=recommendations.country(store) in recommendations.EEA | {"", "EEA"},
            ),
        )

    @app.get("/campaign", response_class=HTMLResponse)
    def campaign_page(request: Request, session: Session = Depends(db_session)):
        from erasure.email_routes import COUNTRIES

        token = require_user(request)
        store = Store(session, require_configured())
        workflow = Workflow(session, store, settings)
        profile = store.get_profile() or {}
        preview = campaign.preview_plan(store) if profile else None
        saved = campaign.consent(store)
        country = request.query_params.get("country", recommendations.country(store) or "EEA")
        if country not in COUNTRIES and country not in recommendations.COUNTRIES:
            country = "EEA"
        allow_postal = (
            request.query_params.get("allow_postal") == "true"
            if "allow_postal" in request.query_params else saved.get("allow_postal", False)
        )
        rows_without_postal = campaign.preview_rows(workflow, country, False) if country in COUNTRIES else []
        rows_with_postal = campaign.preview_rows(workflow, country, True) if country in COUNTRIES else []
        route_rows = rows_with_postal if allow_postal else rows_without_postal
        route_rows = [row for row in route_rows if row['guide'].relevance.category in campaign.DEFAULT_CATEGORIES]
        automatic = campaign.summary(workflow)
        tab = 'messages' if request.query_params.get('tab') == 'messages' else 'settings'
        selected_preview = next((row for row in route_rows if str(row['broker'].id) == request.query_params.get('broker')), None)
        return templates.TemplateResponse(
            request,
            "campaign.html",
            context(
                request,
                token,
                automation=automatic,
                status=automation_summary(store, {'automatic': automatic}, settings.live_submissions),
                reply_assistance=reply_assistance.public_status(settings, store),
                background_status=background.status(settings),
                assistance_error=reply_assistance.ERRORS.get(request.query_params.get('assistance_error'), ''),
                profile=profile,
                tab=tab,
                selected_preview=selected_preview,
                paused=store.get_setting('paused', 'false') == 'true',
                preview=preview,
                preview_hash=campaign.preview_hash(workflow, country, False, rows=rows_without_postal) if preview else "",
                postal_preview_hash=campaign.preview_hash(workflow, country, True, rows=rows_with_postal) if preview else "",
                route_rows=route_rows,
                country_options=COUNTRIES | recommendations.COUNTRIES,
                email_supported=country in COUNTRIES,
                selected_country=country,
                allow_postal=allow_postal,
                error=request.query_params.get("error", ""),
            ),
        )

    @app.post('/background/login')
    def configure_background(request: Request, csrf: str = Form(''),
                             enabled: bool = Form(False), return_to: str = Form('campaign')):
        require_csrf(request, csrf)
        paths = background.settings_paths(settings)
        if not paths:
            raise HTTPException(status_code=400, detail='Available only in the Mac desktop installation')
        destination = '/setup?step=4&' if return_to == 'setup' else '/campaign?'
        try:
            background.set_login(*paths, enabled)
        except (background.BackgroundError, OSError):
            return RedirectResponse(destination + 'background_error=1', status_code=303)
        return RedirectResponse(destination + 'background_saved=1', status_code=303)

    @app.post('/reply-assistance/{action}')
    def configure_reply_assistance(request: Request, action: str, csrf: str = Form(''),
                                   api_key: str = Form(''), return_to: str = Form('campaign'),
                                   session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        if action not in {'connect', 'disable', 'disconnect'}:
            raise HTTPException(status_code=404, detail='Unknown reply assistance action')
        store = Store(session, require_configured())
        destination = '/setup?step=4&' if return_to == 'setup' else '/campaign?'
        try:
            if action == 'connect':
                reply_assistance.connect(settings, store, api_key)
            else:
                selected = reply_assistance.selection(settings, store)
                confirmed = reply_assistance.turn_off(settings, store, forget=action == 'disconnect')
                if action == 'disconnect' and selected['provider'] == 'chatgpt':
                    return RedirectResponse(destination + 'reply_assistance=1&assistance_provider=chatgpt&chatgpt_disconnected=' + ('1' if confirmed else 'unconfirmed'), status_code=303)
        except JevError as exc:
            code = str(exc) if str(exc) in reply_assistance.ERRORS else 'provider_unavailable'
            return RedirectResponse(destination + 'reply_assistance=1&assistance_error=' + code, status_code=303)
        return RedirectResponse(destination + 'reply_assistance=1&assistance_saved=' + action, status_code=303)

    @app.post("/campaign/automatic")
    def configure_automatic_campaign(
        request: Request,
        csrf: str = Form(...),
        daily_limit: int = Form(20),
        preview_hash: str = Form(""),
        postal_preview_hash: str = Form(""),
        authorize: bool = Form(False),
        country: str = Form("EEA"),
        allow_postal: bool = Form(False),
        include_new: bool = Form(False),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        if not authorize:
            return RedirectResponse("/campaign?error=approval", status_code=303)
        workflow = Workflow(session, Store(session, require_configured()), settings)
        keep_paused = bool(campaign.consent(workflow.store).get('enabled')) and workflow.store.get_setting('paused', 'false') == 'true'
        try:
            campaign.enable(workflow, daily_limit,
                            postal_preview_hash if allow_postal and postal_preview_hash else preview_hash,
                            country, allow_postal, include_new=include_new, keep_paused=keep_paused)
        except ValueError:
            return RedirectResponse("/campaign?error=changed", status_code=303)
        workflow.store.set_setting("recommendation_country", country, encrypted=True)
        workflow.store.set_setting(recommendations.SESSION_KEY, {}, encrypted=True)
        return RedirectResponse("/campaign?saved=1", status_code=303)

    @app.post("/campaign/automatic/disable")
    def disable_automatic_campaign(
        request: Request, csrf: str = Form(...), return_to: str = Form('/dashboard'),
        session: Session = Depends(db_session)
    ):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        campaign.stop(Workflow(session, store, settings))
        return RedirectResponse('/campaign' if return_to == '/campaign' else '/dashboard', status_code=303)

    @app.post("/campaign/research/{broker_id}/approve")
    def approve_researched_contact(
        broker_id: int,
        request: Request,
        csrf: str = Form(...),
        source_url: str = Form(...),
        confirmed: bool = Form(False),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        from erasure.research import official_url

        broker = session.get(Broker, broker_id)
        if (
            not confirmed
            or not broker
            or broker.connector_type != "email"
            or "@" not in broker.contact
            or playbook(settings, broker.domain).get("route", "email") != "email"
        ):
            raise HTTPException(
                422, "An eligible email route and explicit verification are required"
            )
        try:
            official_url(source_url, broker.domain)
        except ValueError as exc:
            raise HTTPException(
                422, "Use a public HTTPS privacy page on the broker's domain"
            ) from exc
        row = session.get(RouteResearch, broker_id) or RouteResearch(broker_id=broker_id)
        row.status, row.reason = "manually_verified", "Official email route verified by the user"
        row.source_url, row.evidence = source_url, ""
        broker.source = broker.policy_url = source_url
        row.checked_at = broker.last_validated_at = datetime.now(UTC)
        row.next_check_at = datetime.now(UTC) + timedelta(days=60)
        session.add(row)
        session.commit()
        return RedirectResponse("/campaign#exceptions", status_code=303)

    @app.post("/campaign/research/{broker_id}/complete")
    def complete_research_step(
        broker_id: int,
        request: Request,
        csrf: str = Form(...),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        row = session.get(RouteResearch, broker_id)
        case = session.scalar(select(Case).where(Case.broker_id == broker_id))
        if not row or not case:
            raise HTTPException(404, "Research case not found")
        if row.status == "user_completed":
            return RedirectResponse("/campaign#exceptions", status_code=303)
        workflow = Workflow(session, Store(session, require_configured()), settings)
        if case.state not in {"done", "removed", "not_found"}:
            case.state = "done"
            case.completed_at = datetime.now(UTC)
            case.next_action_at = None
            case.last_error = ""
            workflow.cancel_case_jobs(case.id)
        workflow.close_obsolete_actions(case)
        row.status = "user_completed"
        row.reason = "You completed the broker's privacy steps; not confirmed deletion"
        workflow.store.add_event(
            case.id, "user_completed", row.reason, {"source_url": row.source_url}
        )
        session.commit()
        return RedirectResponse("/campaign#exceptions", status_code=303)

    @app.post("/onboarding")
    def save_onboarding(
        request: Request,
        csrf: str = Form(...),
        full_name: str = Form(...),
        email: str = Form(...),
        other_emails: str = Form(""),
        work_email: str = Form(""),
        employer: str = Form(""),
        aliases: str = Form(""),
        phone: str = Form(""),
        postal_address: str = Form(""),
        previous_addresses: str = Form(""),
        birth_date: str = Form(""),
        signature: str = Form(...),
        alert_email: str = Form(""),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        if len(signature.strip()) < 2:
            raise HTTPException(422, "Signature is required")
        data = {
            "full_name": full_name.strip(),
            "email": email.strip(),
            "other_emails": [x.strip() for x in other_emails.splitlines() if x.strip()],
            "work_email": work_email.strip(),
            "employer": employer.strip(),
            "aliases": [x.strip() for x in aliases.splitlines() if x.strip()],
            "phone": phone.strip(),
            "postal_address": postal_address.strip(),
            "previous_addresses": [x.strip() for x in previous_addresses.splitlines() if x.strip()],
            "birth_date": birth_date.strip(),
            "residency": "EU/EEA",
        }
        store = Store(session, require_configured())
        if recommendations.country(store) not in recommendations.EEA | {"", "EEA"}:
            raise HTTPException(422, "Email setup currently supports EU/EEA residents. Manual actions remain available.")
        store.save_profile(data, signature.strip())
        store.set_setting("alert_email", alert_email.strip(), encrypted=True)
        return RedirectResponse("/dashboard", status_code=303)

    @app.post("/campaign/start")
    def start_campaign(
        request: Request, csrf: str = Form(...), session: Session = Depends(db_session)
    ):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        result = Workflow(session, store, settings).start_campaign()
        store.add_event(  # attach campaign audit to the first scheduled case when available
            session.scalar(select(Case.id).order_by(Case.id)) or 0,
            "campaign_started",
            f"Campaign created {result['created']} cases and scheduled {result['scheduled']}",
        ) if session.scalar(select(Case.id).limit(1)) else None
        return RedirectResponse("/dashboard", status_code=303)

    @app.post("/campaign/pause")
    def pause_campaign(
        request: Request, csrf: str = Form(...), return_to: str = Form('/dashboard'),
        confirmed: bool = Form(False),
        session: Session = Depends(db_session)
    ):
        token = require_csrf(request, csrf)
        if not confirmed:
            return templates.TemplateResponse(request, 'pause_confirmation.html', context(
                request, token, return_to='/campaign' if return_to == '/campaign' else '/dashboard',
            ))
        campaign.pause(Workflow(session, Store(session, require_configured()), settings))
        return RedirectResponse('/campaign' if return_to == '/campaign' else '/dashboard', status_code=303)

    @app.post("/campaign/resume")
    def resume_campaign(
        request: Request, csrf: str = Form(...), return_to: str = Form('/dashboard'),
        session: Session = Depends(db_session)
    ):
        require_csrf(request, csrf)
        try:
            campaign.resume(Workflow(session, Store(session, require_configured()), settings))
        except ValueError:
            return RedirectResponse('/campaign?error=resume', status_code=303)
        return RedirectResponse('/campaign' if return_to == '/campaign' else '/dashboard', status_code=303)

    @app.post('/campaign/check')
    def retry_automation(request: Request, csrf: str = Form(...), session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        workflow = Workflow(session, Store(session, require_configured()), settings)
        for kind in ('campaign_tick', 'poll_gmail'):
            if session.scalar(select(Job.id).where(Job.kind == kind, Job.status.in_(['pending', 'running']))) is None:
                workflow.store.enqueue(kind, {})
        campaign.wake_jobs(workflow)
        return RedirectResponse('/dashboard', status_code=303)

    @app.get("/brokers", response_class=HTMLResponse)
    def brokers(
        request: Request, session: Session = Depends(db_session), q: str = "",
        category: str = "", region: str = "", page: int = 1, detail: int = 0,
        sort: str = "broker", direction: str = "asc",
    ):
        token = require_user(request)
        knowledge = guide_index(settings)
        email_workflows = {domain: route for domain, (route, _) in reviewed_email_routes(settings).items()}
        manual_domains = {domain for item in quick_win_resources(settings)['items']
                          if item.get('fresh') and item.get('reviewed') for domain in item['domains']}
        rows = broker_library.library_rows(session.scalars(select(Broker)), knowledge, email_workflows,
                                           manual_domains=manual_domains)
        rows = [row for row in rows if row["reachable"]]
        category = category if category in broker_library.CATEGORY_LABELS else ""
        region = region if region in broker_library.REGION_LABELS else ""
        filters = dict(q=q.strip(), category=category, region=region)
        sort = sort if sort in {"broker", "category"} else "broker"
        direction = direction if direction in {"asc", "desc"} else "asc"
        filtered = broker_library.sort_rows(broker_library.select_rows(rows, **filters), sort, direction)
        pages = max(1, (len(filtered) + 49) // 50)
        page = min(max(1, page), pages)
        def library_url(**changes):
            values = {**filters, "page": page, "sort": sort, "direction": direction, **changes}
            return "/brokers?" + urlencode({k: v for k, v in values.items() if v})
        case_ids = dict(session.execute(select(Case.broker_id, Case.id)).all())
        def broker_url(broker_id):
            return f"/cases/{case_ids[broker_id]}" if broker_id in case_ids else f"/cases/broker/{broker_id}"
        if detail:
            return RedirectResponse(broker_url(detail), status_code=303)
        return templates.TemplateResponse(
            request,
            "brokers.html",
            context(
                request,
                token,
                rows=filtered[(page - 1) * 50:page * 50], filters=filters,
                sort=sort, direction=direction,
                total=len(rows), matched=len(filtered), page=page, pages=pages,
                first=(page - 1) * 50 + 1 if filtered else 0, last=min(page * 50, len(filtered)),
                library_url=library_url, broker_url=broker_url,
                categories=broker_library.CATEGORY_LABELS,
                regions={code: label for code, label in broker_library.REGION_LABELS.items()
                         if any(code in row['region_tags'] for row in rows)},
            ),
        )

    @app.get("/brokers/{broker_id}", response_class=HTMLResponse)
    def broker_detail(broker_id: int, request: Request, session: Session = Depends(db_session)):
        require_user(request)
        if session.get(Broker, broker_id) is None:
            raise HTTPException(404, "Broker not found")
        return RedirectResponse(f"/cases/broker/{broker_id}", status_code=303)

    @app.get("/cases", response_class=HTMLResponse)
    def cases_page(request: Request, session: Session = Depends(db_session), state: str = "", q: str = ""):
        token = require_user(request)
        attention_items = recommendations.attention_items(Workflow(session, Store(session, require_configured()), settings))
        attention_case_ids = {item['case_id'] for item in attention_items}
        view = request.query_params.get("view", "all")
        if view == 'attention':
            state = ''
        query = request_history().join(Broker)
        if q.strip():
            query = query.where(Broker.name.icontains(q.strip(), autoescape=True))
        if view == 'attention':
            query = query.where(Case.id.in_(attention_case_ids))
        elif state in {"done", "removed"}:
            query = query.where(Case.state.in_(["done", "removed", "not_found"]))
        elif state == 'waiting':
            query = query.where(Case.state.in_(['queued', 'prepared', 'submitted', 'processing', 'recheck_due'])
                | (Case.state.in_(['needs_action', 'delivery_failed']) & Case.id.not_in(attention_case_ids)))
        elif state:
            query = query.where(Case.state == state)
        else:
            query = query.where(Case.state != "candidate")
        if view == "sent":
            query = query.where(Case.id.in_(select(Event.case_id).where(Event.kind == "submitted")))
        case_rows = session.execute(query).all()
        cases = [row[0] for row in case_rows]
        return templates.TemplateResponse(
            request,
            "cases.html",
            context(
                request,
                token,
                cases=cases,
                request_updated={row[0].id: row[1] for row in case_rows},
                sendable_case_ids={case.id for case in cases if is_recently_validated(case.broker)},
                state=state,
                q=q,
                attention_items=attention_items,
                attention_case_ids=attention_case_ids,
                attention_urls={item['case_id']: item['url'] for item in attention_items},
                view=view,
                unmatched_count=session.scalar(select(func.count()).select_from(IncomingMessage).where(IncomingMessage.status == 'review', IncomingMessage.case_id.is_(None))) or 0,
                messages=[{'record': m, 'mail': require_configured().decrypt(m.encrypted_payload),
                           'gmail_url': gmail_link(require_configured().decrypt(m.encrypted_payload))}
                          for m in session.scalars(select(IncomingMessage).where(IncomingMessage.status == 'review', IncomingMessage.case_id.is_(None)).order_by(IncomingMessage.created_at.desc()))]
                         if view == 'mail' else [],
            ),
        )

    @app.get("/cases/{case_id}", response_class=HTMLResponse)
    def case_detail(case_id: int, request: Request, session: Session = Depends(db_session)):
        require_user(request)
        case = session.get(Case, case_id)
        if case is None:
            raise HTTPException(404, "Case not found")
        return render_case(request, session, case)

    @app.get("/cases/broker/{broker_id}", response_class=HTMLResponse)
    def unstarted_case(broker_id: int, request: Request, session: Session = Depends(db_session)):
        require_user(request)
        broker = session.get(Broker, broker_id)
        if broker is None:
            raise HTTPException(404, "Broker not found")
        case = session.scalar(select(Case).where(Case.broker_id == broker_id))
        if case:
            tab = request.query_params.get("tab", "overview")
            tab = tab if tab in {"overview", "conversation", "details"} else "overview"
            return RedirectResponse(f"/cases/{case.id}?tab={tab}", status_code=303)
        # A read-only placeholder uses the same request UI without creating a case or job.
        case = SimpleNamespace(id=f"broker/{broker_id}", broker=broker, state="candidate",
                               submitted_at=None, next_action_at=None)
        return render_case(request, session, case, persisted=False)

    def render_case(request, session, case, *, persisted=True):
        token = require_user(request)
        prepared_event = session.scalar(
            select(Event)
            .where(Event.case_id == case.id, Event.kind == "request_prepared")
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(1)
        ) if persisted else None
        draft = (
            require_configured().decrypt(prepared_event.encrypted_payload)
            if prepared_event and prepared_event.encrypted_payload
            else None
        )
        correspondence = conversation(session, require_configured(), case.id) if persisted else []
        latest_correspondence = next((item for item in correspondence if item["kind"] != "step"), None)
        all_pending = pending_action_details(session, case.id) if persisted and case.state not in {"done", "removed", "not_found"} else []
        pending = [item for item in all_pending if item['needs_person']]
        email_only_action = next((item for item in pending if item['email_only']), None)
        priority = {"unverified_sender": 0, "identity_proof": 1, "confirmation_link": 2}
        pending.sort(key=lambda item: priority.get(item["record"].kind, 3))
        selectable = all_pending if request.query_params.get('correct') == '1' else pending
        selected_action = next((item for item in selectable if str(item["record"].id) == request.query_params.get("step")),
                               pending[0] if pending else None)
        guide = guide_index(settings).get(case.broker.domain)
        email_workflows = {domain: route for domain, (route, _) in reviewed_email_routes(settings).items()}
        manual_resources = quick_win_resources(settings)['items']
        residence = recommendations.country(Store(session, require_configured()))
        manual_resource = next((item for item in manual_resources
            if case.broker.domain in item['domains'] and item.get('fresh') and item.get('reviewed')
            and recommendations.region_matches(item.get('regions', []), residence)), None)
        category = guide.relevance.category if guide else case.broker.category
        category_label = recommendations.CATEGORIES.get(category, (0, category.replace("_", " ").title()))[1]
        tab = request.query_params.get("tab", "overview")
        if tab not in {"overview", "conversation", "details"}:
            tab = "overview"
        reply_draft = {}
        reply_body = ""
        if (
            case.state in {"needs_action", "not_found", "done", "removed", "processing"}
            and latest_correspondence
            and latest_correspondence["kind"] == "received"
            and not latest_correspondence["held"]
        ):
            reply_body = latest_correspondence["mail"].get("body", "")
        overview_composer = bool(not email_only_action and selected_action and not selected_action['matching_mailbox'] and (
            selected_action["record"].kind in {"information_requested", "next_step", "ambiguous_reply"}
            or (selected_action['record'].kind == 'form_required' and not selected_action['action_url'])))
        if overview_composer:
            reply_body = selected_action["message_body"]
        if reply_body:
            reply_store = Store(session, require_configured())
            reply_profile = reply_store.get_profile() or {}
            selected_country = recommendations.country(reply_store)
            if selected_country in recommendations.COUNTRIES:
                reply_profile["country"] = recommendations.COUNTRIES[selected_country]
            reply_draft = prepare_reply(reply_body, reply_profile)
        disclosed_fields = {field for item in correspondence if item["kind"] == "sent"
                            for field in item["mail"].get("disclosed_fields", [])}
        if any(item["kind"] == "step" and item["record"].kind == "identity_proof_sent"
               for item in correspondence):
            disclosed_fields.add("redacted_identity_document")
        return templates.TemplateResponse(
            request,
            "case_detail.html",
            context(
                request,
                token,
                case=case,
                persisted=persisted,
                broker_guidance=playbook(settings, case.broker.domain),
                guide=guide,
                library_info=broker_library.library_rows([case.broker], {case.broker.domain: guide} if guide else {},
                    email_workflows, manual_domains={d for item in manual_resources
                        if item.get('fresh') and item.get('reviewed') for d in item['domains']})[0],
                manual_resource=manual_resource,
                registry_rows=registry_context(settings).get(case.broker.domain, []) if tab == "details" else [],
                category_label=category_label,
                tab=tab,
                email_workflows=email_workflows,
                draft=draft,
                selected_action=selected_action,
                pending_actions=pending,
                all_pending=all_pending,
                manual_correction=request.query_params.get('correct') == '1',
                recovery_messages=[{'mail': item['mail'], 'gmail_url': gmail_link(item['mail']),
                    'status': Store(session, require_configured()).get_setting(f"mail_recovery:{item['mail'].get('id', '')}", {}).get('status', 'retrying')}
                    for item in correspondence if item['kind'] == 'received' and not item['mail'].get('body', '').strip()],
                overview_composer=overview_composer,
                email_only_action=email_only_action,
                disclosed_fields=sorted(disclosed_fields),
                action_return=f"/cases/{case.id}",
                reply_draft=reply_draft,
                correspondence=correspondence,
                events=session.scalars(
                    select(Event)
                    .where(Event.case_id == case.id)
                    .order_by(Event.created_at.desc(), Event.id.desc())
                ).all() if persisted else [],
            ),
        )

    @app.post("/cases/{case_id}/reply")
    def reply_to_case(
        case_id: int,
        request: Request,
        csrf: str = Form(...),
        destination: str = Form(...),
        body: str = Form(...),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        try:
            Workflow(session, Store(session, require_configured()), settings).send_reply(
                case_id, destination, body
            )
        except (ValueError, GmailError) as exc:
            detail = case_detail(case_id, request, session)
            reply_context = dict(detail.context, reply_error=str(exc),
                                 tab="overview" if detail.context["overview_composer"] else "conversation",
                                 submitted_reply={"body": body, "destination": destination})
            return templates.TemplateResponse(request, "case_detail.html", reply_context, status_code=409)
        return RedirectResponse(f"/cases/{case_id}", status_code=303)

    @app.get("/batch", response_class=HTMLResponse)
    def batch_page(request: Request, session: Session = Depends(db_session)):
        token = require_user(request)
        prepared = session.scalars(
            select(Case)
            .join(Case.broker)
            .where(
                Case.state == "prepared",
                Broker.active.is_(True),
                Broker.connector_type == "email",
            )
            .order_by(Broker.name)
        ).all()
        eligible = [case for case in prepared if email_eligible(case.broker, settings)]
        return templates.TemplateResponse(
            request,
            "batch.html",
            context(
                request,
                token,
                cases=eligible,
                max_batch_size=MAX_BATCH_SIZE,
                batch_error={
                    "empty": "Select at least one request.",
                    "limit": f"Select at most {MAX_BATCH_SIZE} requests.",
                }.get(request.query_params.get("error"), ""),
                pipeline=pipeline_status(session, Store(session, require_configured()), settings),
            ),
        )

    @app.post("/batch")
    def send_batch(
        request: Request,
        csrf: str = Form(...),
        case_ids: list[int] = Form([]),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        if not case_ids:
            return RedirectResponse("/batch?error=empty", status_code=303)
        if not settings.live_submissions:
            raise HTTPException(409, "Batch sending requires live submissions")
        unique_ids = list(dict.fromkeys(case_ids))
        if len(unique_ids) > MAX_BATCH_SIZE:
            return RedirectResponse("/batch?error=limit", status_code=303)
        selected = session.scalars(select(Case).where(Case.id.in_(unique_ids))).all()
        by_id = {case.id: case for case in selected}
        if len(by_id) != len(unique_ids):
            raise HTTPException(404, "One or more cases were not found")
        cases = [by_id[case_id] for case_id in unique_ids]
        if any(
            case.state != "prepared"
            or not case.broker.active
            or case.broker.connector_type != "email"
            or not email_eligible(case.broker, settings)
            for case in cases
        ):
            raise HTTPException(
                409,
                "Every request must be prepared and have an official email address checked within 90 days",
            )
        for case in cases:
            case.state = "queued"
        Store(session, require_configured()).enqueue_many(
            "submit_case", [{"case_id": case.id} for case in cases]
        )
        return RedirectResponse("/cases?state=queued", status_code=303)

    @app.get("/quick-wins", response_class=HTMLResponse)
    def quick_wins(request: Request, session: Session = Depends(db_session)):
        token = require_user(request)
        store = Store(session, require_configured())
        catalog = quick_win_resources(settings)
        workflow = Workflow(session, store, settings)
        all_items = recommendations.action_items(workflow)
        view = request.query_params.get("view", "recommended")
        if view == "all":
            items = all_items
        elif view == "done":
            items = [i for i in all_items if i["done"]]
        elif view == "saved":
            items = [i for i in all_items if i["preference"] and not i["done"]]
        else:
            view = "recommended"
            items = recommendations.session_items(workflow, all_items)
        return templates.TemplateResponse(
            request,
            "quick_wins.html",
            context(
                request,
                token,
                items=items,
                checked_at=catalog["checked_at"],
                done_count=sum(bool(item["done"]) for item in all_items),
                view=view,
                action_country=recommendations.country(store),
                action_countries=recommendations.COUNTRIES,
            ),
        )

    @app.post("/recommendations/country")
    def recommendation_country(request: Request, csrf: str = Form(...), country: str = Form(...),
                               return_to: str = Form("/dashboard"),
                               session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        if country not in recommendations.COUNTRIES:
            raise HTTPException(422, "Choose a listed country")
        store = Store(session, require_configured())
        store.set_setting("recommendation_country", country, encrypted=True)
        store.set_setting(recommendations.SESSION_KEY, {}, encrypted=True)
        destination = return_to if return_to in {"/onboarding", "/quick-wins"} else "/dashboard#quick-wins"
        return RedirectResponse(destination, status_code=303)

    @app.post("/recommendations/more")
    def more_recommendations(request: Request, csrf: str = Form(...),
                             session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        store.set_setting(recommendations.SESSION_KEY, {}, encrypted=True)
        return RedirectResponse("/quick-wins", status_code=303)

    @app.post("/recommendations/{resource_id}/{choice}")
    def defer_recommendation(resource_id: str, choice: str, request: Request,
                            csrf: str = Form(...), return_to: str = Form("/quick-wins"),
                            session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        if choice not in {"later", "skip", "restore"}:
            raise HTTPException(422, "Unknown action")
        if resource_id not in {i["id"] for i in quick_win_resources(settings)["items"]}:
            raise HTTPException(404, "Resource not found")
        store = Store(session, require_configured())
        recommendations.set_preference(Workflow(session, store, settings), resource_id, choice)
        destination = "/dashboard#quick-wins" if return_to == "/dashboard" else "/quick-wins"
        return RedirectResponse(destination, status_code=303)

    @app.post("/quick-wins/{resource_id}")
    def update_quick_win(
        resource_id: str,
        request: Request,
        csrf: str = Form(...),
        done: bool = Form(True),
        return_to: str = Form("/quick-wins"),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        item = next(
            (item for item in quick_win_resources(settings)["items"] if item["id"] == resource_id),
            None,
        )
        if item is None:
            raise HTTPException(404, "Resource not found")
        store = Store(session, require_configured())
        if done:
            recommendations.remember_session(Workflow(session, store, settings))
            mark_quick_win_done(Workflow(session, store, settings), item)
        else:
            store.set_setting(f"quick_win:{resource_id}", "")
        destination = {"/dashboard": "/dashboard#quick-wins", "/quick-wins?view=all": "/quick-wins?view=all"}.get(return_to, "/quick-wins")
        if re.fullmatch(r'/cases/(?:broker/)?[0-9]+', return_to):
            destination = return_to
        return RedirectResponse(destination, status_code=303)

    def pending_action_details(session, case_id=None):
        query = select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)
        if case_id is not None:
            query = query.where(Approval.case_id == case_id)
        pending = session.scalars(query).all()
        vault = require_configured()
        # These destinations come from the reviewed catalog, never from a
        # vendor-domain link guessed from an incoming email.
        form_routes = {domain: item["url"] for item in quick_win_resources(settings)["items"]
                       if item.get("fresh") and item.get("reviewed") and item['url'].startswith('https://')
                       for domain in item["domains"]}
        from erasure.knowledge import guides
        from erasure.replies import matching_mailbox_required
        form_guides = {domain: guide for guide in guides(settings)
                       if guide.fresh and guide.review_status == 'instructions_reviewed'
                       and guide.removal.method == 'form' for domain in guide.match_domains}
        form_routes.update({domain: guide.removal.destination for domain, guide in form_guides.items()})
        actions_with_details = []
        for action in pending:
            payload = vault.decrypt(action.encrypted_payload) if action.encrypted_payload else {}
            case = session.get(Case, action.case_id) if action.case_id else None
            actions_with_details.append(
                {
                    "record": action,
                    "case": case,
                    "has_artifact": bool(payload.get("artifact")),
                    "email_only": email_only_identity(action, payload),
                    "matching_mailbox": matching_mailbox_required(payload.get('message', payload).get('body', '')),
                    "has_draft": bool(payload.get("draft")),
                    "action_url": payload.get("action_url", "")
                    or (
                        request_form_url(
                            case.broker, payload.get("message", payload).get("body", "")
                        ) or (form_routes.get(case.broker.domain, "") if action.kind == 'form_required' else '')
                        if case and action.kind in {"ambiguous_reply", "form_required", "next_step"}
                        else ""
                    ),
                    "form_steps": (form_guides[case.broker.domain].removal.steps
                                   if case and case.broker.domain in form_guides and action.kind == 'form_required' else []),
                    "reason": payload.get("reason", ""),
                    "proposed_kind": payload.get("proposed_kind", ""),
                    "message_body": payload.get("message", payload).get("body", ""),
                    "needs_person": needs_person(action, payload),
                    "gmail_url": gmail_link(payload.get('message', payload)),
                }
            )
        return actions_with_details

    @app.get("/actions", response_class=HTMLResponse)
    def actions(request: Request, session: Session = Depends(db_session)):
        require_user(request)
        return RedirectResponse('/cases?view=attention', status_code=303)

    @app.post("/actions/{approval_id}/resolve/{decision}")
    def resolve_action(
        approval_id: int,
        decision: str,
        request: Request,
        csrf: str = Form(...),
        outcome: str = Form(""),
        return_to: str = Form(""),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        if decision not in {"approve", "reject"}:
            raise HTTPException(400, "Unknown decision")
        approval = session.get(Approval, approval_id)
        if approval is not None and approval.case_id:
            case = session.get(Case, approval.case_id)
            if case and case.state in {"done", "removed", "not_found"}:
                Workflow(
                    session, Store(session, require_configured()), settings
                ).close_obsolete_actions(case)
                session.commit()
                return RedirectResponse(f"/cases/{case.id}", status_code=303)
        if approval is None or approval.status != "pending":
            raise HTTPException(404, "Pending action not found")
        vault = require_configured()
        payload = vault.decrypt(approval.encrypted_payload) if approval.encrypted_payload else {}
        if decision == 'approve' and email_only_identity(approval, payload) and (
            approval.kind != 'unverified_sender' or not outcome
        ):
            raise HTTPException(409, 'Handle this identity or authorization request directly in your email. The app does not support it yet.')
        if approval.kind == "confirmation_link" and decision == "approve" and outcome != "email_confirmed":
            raise HTTPException(422, "Complete the broker’s confirmation step, then record it here")
        if approval.kind == "next_step" and decision == "approve" and outcome == "needs_action":
            # A double click/back-button submission should reopen the panel, not fail validation.
            return RedirectResponse(f"/cases/{approval.case_id}#next-step", status_code=303)
        if (
            approval.kind in {"ambiguous_reply", "form_required", "next_step", "unverified_sender"}
            and decision == "approve"
            and (approval.kind != "unverified_sender" or outcome)
        ):
            allowed = (
                {"form_submitted"}
                if approval.kind in {"form_required", "next_step"}
                else {
                    "form_submitted",
                    "processing",
                    "removed",
                    "not_found",
                    "needs_action",
                    "close_message",
                }
            )
            if approval.kind == 'next_step':
                from erasure.replies import matching_mailbox_required
                if matching_mailbox_required(payload.get('message', payload).get('body', '')):
                    allowed.add('external_email_sent')
            if outcome not in allowed:
                raise HTTPException(
                    422, "Choose what happened; approval alone cannot update a request"
                )
            case = session.get(Case, approval.case_id) if approval.case_id else None
            if case is None:
                raise HTTPException(409, "Request not found")
            workflow = Workflow(session, Store(session, vault), settings)
            if outcome == "close_message":
                if approval.kind == "unverified_sender" and case.state == "needs_action":
                    previous = payload.get("previous_state", "submitted")
                    if previous in {"submitted", "processing"}:
                        case.state = previous
            elif outcome in {"removed", "not_found"}:
                workflow._complete(case, outcome)
            elif outcome == "needs_action":
                case.state = "needs_action"
                workflow.cancel_case_jobs(case.id)
                case.next_action_at = None
                approval.summary = "Another step is needed — open the request and respond"
                approval.kind = "next_step"
                approval.expires_at = None
                Store(session, vault).add_event(
                    case.id,
                    "reply_reviewed",
                    "Reply reviewed: another step is still needed",
                    payload,
                )
                session.commit()
                return RedirectResponse(f"/cases/{case.id}?step_saved=1#next-step", status_code=303)
            else:
                case.state = "processing"
                workflow.cancel_case_jobs(case.id)
                case.next_action_at = datetime.now(UTC) + timedelta(days=30)
                Store(session, vault).enqueue(
                    "follow_up", {"case_id": case.id}, run_at=case.next_action_at
                )
            Store(session, vault).add_event(
                case.id,
                "form_submitted" if outcome == "form_submitted" else "reply_reviewed",
                "You confirmed submitting the broker form; awaiting their response"
                if outcome == "form_submitted"
                else (
                    "Message marked done; no deletion outcome inferred"
                    if outcome == "close_message"
                    else ('You recorded sending from the matching email address; awaiting the broker response'
                          if outcome == 'external_email_sent' else f"Reply reviewed: {outcome}")
                ),
                payload,
            )
        if decision == "approve" and approval.kind == "unverified_sender" and not outcome:
            message = payload.get("message")
            if not isinstance(message, dict) or not approval.case_id:
                raise HTTPException(409, "The held reply is incomplete")
            Workflow(session, Store(session, vault), settings).process_message(
                {str(key): str(value) for key, value in message.items()}, sender_verified=True,
                linked_case_id=approval.case_id,
            )
        approval.status = "approved" if decision == "approve" else "rejected"
        approval.resolved_at = datetime.now(UTC)
        if approval.case_id:
            case = session.get(Case, approval.case_id)
            if (
                case
                and decision == "approve"
                and approval.kind
                in {
                    "browser_challenge",
                    "confirmation_link",
                }
            ):
                case.state = "processing"
                if approval.kind == "browser_challenge":
                    now = datetime.now(UTC)
                    case.attempt_count += 1
                    case.submitted_at = case.submitted_at or now
                else:
                    Store(session, vault).add_event(
                        case.id, "email_confirmation_recorded",
                        "You confirmed the broker’s email-verification step; awaiting their response",
                    )
                Workflow(session, Store(session, vault), settings).cancel_case_jobs(case.id)
                case.next_action_at = datetime.now(UTC) + timedelta(days=30)
                Store(session, vault).enqueue(
                    "follow_up", {"case_id": case.id}, run_at=case.next_action_at
                )
            elif case and decision == "approve" and approval.kind == "complaint":
                case.state = "complaint_approved"
            elif case and decision == "reject" and approval.kind == "unverified_sender":
                previous_state = str(payload.get("previous_state", "submitted"))
                case.state = (
                    previous_state
                    if previous_state in {"queued", "prepared", "submitted", "processing"}
                    else "submitted"
                )
            Store(session, vault).add_event(
                approval.case_id,
                "approval_resolved",
                f"{approval.kind.replace('_', ' ').title()} {approval.status}",
            )
        session.commit()
        destination = f"/cases/{approval.case_id}"
        return RedirectResponse(destination, status_code=303)

    @app.post("/cases/{case_id}/schedule")
    def schedule_case(
        case_id: int,
        request: Request,
        csrf: str = Form(...),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        case = session.get(Case, case_id)
        if case is None or not case.broker.active:
            raise HTTPException(404, "Active case not found")
        if (
            case.state == "prepared"
            and case.broker.connector_type == "email"
            and not settings.live_submissions
        ):
            raise HTTPException(409, "Enable live submissions before sending a prepared case")
        if case.state == "prepared" and not is_recently_validated(case.broker):
            raise HTTPException(409, "Validate the broker contact before sending this case")
        if case.state in {"candidate", "prepared", "recheck_due", "rejected"}:
            if case.state != "prepared":
                case.confidence = 100
            case.state = "queued"
            Store(session, require_configured()).enqueue("submit_case", {"case_id": case.id})
            session.commit()
        return RedirectResponse("/cases", status_code=303)

    @app.post("/actions/{approval_id}/identity")
    async def upload_identity(
        approval_id: int,
        request: Request,
        csrf: str = Form(...),
        return_to: str = Form(""),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        approval = session.get(Approval, approval_id)
        if approval is None or approval.status != "pending" or approval.kind != "identity_proof":
            raise HTTPException(404, "Pending identity action not found")
        raise HTTPException(409, 'Identity-document uploads are not supported. Handle this request directly in your email.')

    @app.get("/actions/{approval_id}/draft")
    def download_draft(
        approval_id: int,
        request: Request,
        session: Session = Depends(db_session),
    ):
        require_user(request)
        approval = session.get(Approval, approval_id)
        if approval is None or not approval.encrypted_payload:
            raise HTTPException(404, "Draft not found")
        payload = require_configured().decrypt(approval.encrypted_payload)
        if not payload.get("draft"):
            raise HTTPException(404, "Draft not found")
        return Response(
            payload["draft"],
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=complaint-{approval.id}.txt"},
        )

    @app.get("/inbox", response_class=HTMLResponse)
    def inbox_page(request: Request, session: Session = Depends(db_session), view: str = "review"):
        require_user(request)
        return RedirectResponse('/cases?view=mail', status_code=303)

    @app.post("/inbox/{message_id}/review")
    def inbox_review(
        message_id: str,
        request: Request,
        csrf: str = Form(...),
        outcome: str = Form(...),
        case_id: int = Form(0),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        record = session.get(IncomingMessage, message_id)
        if record is None:
            raise HTTPException(404, "Message not found")
        try:
            review_message(
                Workflow(session, Store(session, require_configured()), settings),
                record,
                case_id,
                outcome,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return RedirectResponse(f'/cases/{record.case_id}?tab=conversation' if record.case_id else '/cases?view=mail', status_code=303)

    @app.post('/gmail/check')
    def check_mailbox(request: Request, csrf: str = Form(...), session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        job = session.scalar(select(Job).where(Job.kind == 'poll_gmail', Job.status.in_(['pending', 'running'])))
        if job is None:
            Store(session, require_configured()).enqueue('poll_gmail', {})
        elif job.status == 'pending':
            job.run_at = datetime.now(UTC)
            session.commit()
        return RedirectResponse('/dashboard', status_code=303)

    @app.get("/gmail/connect")
    def gmail_connect(request: Request, session: Session = Depends(db_session)):
        token = require_user(request)
        client = GmailClient(settings, Store(session, require_configured()))
        setup = request.query_params.get('return_to') == 'setup' and setup_flow.needs_setup(client.store)
        if setup and setup_flow.next_step(client.store) < 3:
            return RedirectResponse('/setup', status_code=303)
        client.store.set_setting('gmail_setup_session', campaign.digest(token) if setup else '', encrypted=True)
        try:
            response = RedirectResponse(client.authorization_url(), status_code=303)
            # Upgrade cookies issued by versions that used SameSite=Strict before
            # navigating away, otherwise Google cannot return the authenticated session.
            set_session_cookie(response, token)
            return response
        except GmailError as exc:
            if setup:
                return RedirectResponse('/setup?step=3&connection=failed', status_code=303)
            raise HTTPException(400, str(exc)) from exc

    @app.get('/demo/mailbox', response_class=HTMLResponse)
    def demo_mailbox_page(request: Request):
        if not settings.demo_mode:
            raise HTTPException(404, 'Not found')
        token = require_user(request)
        return templates.TemplateResponse(request, 'demo_mailbox.html', context(request, token,
            setup_mode=request.query_params.get('setup') == 'true'))

    @app.post('/demo/mailbox')
    def demo_connect(request: Request, csrf: str = Form(...), session: Session = Depends(db_session)):
        if not settings.demo_mode:
            raise HTTPException(404, 'Not found')
        require_csrf(request, csrf)
        client = GmailClient(settings, Store(session, require_configured()))
        client.authorization_url()
        return gmail_callback(request, 'demo', client.store.get_setting('gmail_oauth_state'), session=session)

    @app.get('/demo/external', response_class=HTMLResponse)
    def demo_external(request: Request, destination: str = ''):
        if not settings.demo_mode:
            raise HTTPException(404, 'Not found')
        token = require_user(request)
        return templates.TemplateResponse(request, 'demo_external.html',
            context(request, token, destination=destination[:2000]))

    @app.get("/gmail/callback")
    def gmail_callback(
        request: Request,
        code: str = '',
        state: str = '',
        error: str = '',
        session: Session = Depends(db_session),
    ):
        store = Store(session, require_configured())
        setup_session = store.get_setting('gmail_setup_session', '')
        setup = bool(setup_session) and setup_flow.needs_setup(store)
        try:
            token = require_user(request)
        except HTTPException:
            if setup:
                return RedirectResponse('/login', status_code=303)
            raise
        if error or not code or (setup and setup_session != campaign.digest(token)):
            return RedirectResponse('/setup?step=3&connection=failed' if setup else '/campaign?gmail_connection=failed', status_code=303)
        client = GmailClient(settings, store)
        try:
            # Workers must never observe an unchecked replacement mailbox.
            credentials = client.exchange_code(code, state, persist=False)
            if not credentials.get('access_token') or not credentials.get('refresh_token'):
                raise GmailError('Offline mailbox access was not granted')
            if credentials.get('scope') and not set(SCOPES.split()) <= set(credentials['scope'].split()):
                raise GmailError('Required Gmail permissions were not granted')
            address = client.mailbox_address(access_token=credentials['access_token'])
            session.expire_all()
            profile = client.store.get_profile() or {}
            if profile.get('email') and address.casefold() != profile['email'].casefold():
                return RedirectResponse('/campaign?gmail_connection=wrong_account', status_code=303)
            client.store.set_setting('gmail_token', credentials, encrypted=True)
            client.store.set_setting('gmail_error', '')
            setup_flow.remember_mailbox(client.store, address)
        except Exception:  # OAuth transport and validation failures are intentionally opaque
            if setup:
                return RedirectResponse('/setup?step=3&connection=failed', status_code=303)
            return RedirectResponse('/campaign?gmail_connection=failed', status_code=303)
        finally:
            client.client.close()
        if setup:
            client.store.set_setting('gmail_setup_session', '', encrypted=True)
            return RedirectResponse('/setup?step=4', status_code=303)
        jobs = session.scalars(
            select(Job)
            .where(Job.kind == "poll_gmail", Job.status.in_(["pending", "failed"]))
            .order_by(Job.id.desc())
        ).all()
        if jobs:
            jobs[0].status = "pending"
            jobs[0].run_at = datetime.now(UTC)
            jobs[0].last_error = ""
            jobs[0].attempts = 0
            for duplicate in jobs[1:]:
                duplicate.status = "cancelled"
            session.commit()
        else:
            Store(session, require_configured()).enqueue_if_missing("poll_gmail", {})
        return RedirectResponse("/dashboard", status_code=303)

    @app.post("/catalog/import")
    async def catalog_import(
        request: Request,
        registry: UploadFile,
        csrf: str = Form(...),
        session: Session = Depends(db_session),
    ):
        require_csrf(request, csrf)
        if registry.size and registry.size > 5_000_000:
            raise HTTPException(413, "Registry file is too large")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as temporary:
            temporary.write(await registry.read())
            destination = Path(temporary.name)
        try:
            import_cppa_registry(session, destination)
        finally:
            destination.unlink(missing_ok=True)
        return RedirectResponse("/brokers", status_code=303)

    @app.get("/export.csv")
    def export_csv(request: Request, session: Session = Depends(db_session)):
        require_user(request)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["broker", "state", "attempts", "submitted_at", "completed_at", "next_action_at"]
        )
        for case in session.scalars(select(Case).order_by(Case.id)):
            writer.writerow(
                [
                    case.broker.name,
                    case.state,
                    case.attempt_count,
                    case.submitted_at or "",
                    case.completed_at or "",
                    case.next_action_at or "",
                ]
            )
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=erasure-audit.csv"},
        )

    @app.get("/api/status")
    def api_status(request: Request, session: Session = Depends(db_session)):
        require_user(request)
        store = Store(session, require_configured())
        workflow = Workflow(session, store, settings)
        pipeline = pipeline_status(session, store, settings)
        automation = automation_summary(store, pipeline, settings.live_submissions)
        return {
            "counts": workflow.dashboard_counts(),
            "attention_count": len(recommendations.attention_items(workflow)),
            'sent_requests': pipeline['automatic']['sent_count'],
            'progress_chart': request_progress(session),
            'sending_activity': sending_activity(session, pipeline['automatic'], automation, demo=settings.demo_mode),
            "live_submissions": settings.live_submissions,
            "draft_status": automation['detail'],
            "pipeline_html": templates.get_template("pipeline_status.html").render(
                pipeline=pipeline
            ),
            'automation': {**automation, 'last_sync': relative_time(automation['last_sync']) if automation['last_sync'] else 'Not yet'},
        }

    setup_flow.mount_setup(app, settings, db_engine, templates, context, require_user,
                           require_csrf, require_configured, db_session)
    from erasure import chatgpt_routes

    chatgpt_routes.mount(app, settings, require_user, require_csrf, require_configured, db_session)
    return app


app = create_app()
