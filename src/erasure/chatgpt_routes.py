"""Small authenticated local UI boundary for optional ChatGPT plan usage."""

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from erasure import chatgpt_auth, reply_assistance
from erasure.chatgpt import ChatGPTError
from erasure.store import Store


def destination(return_to):
    return ('/setup?step=4&' if return_to == 'setup' else '/campaign?') + 'reply_assistance=1&assistance_provider=chatgpt&'


def mount(app, settings, require_user, require_csrf, require_configured, db_session):
    @app.post('/chatgpt/connect')
    def connect(request: Request, csrf: str = Form(''), account: str = Form(''),
                return_to: str = Form('campaign'), session: Session = Depends(db_session)):
        token = require_csrf(request, csrf)
        store = Store(session, require_configured())
        if settings.demo_mode:
            store.set_setting('demo_reply_assistance', True, encrypted=True)
            store.set_setting('demo_reply_assistance_provider', 'chatgpt', encrypted=True)
            return {'url': destination(return_to) + 'assistance_saved=connect'}
        try:
            url = chatgpt_auth.begin(store, token, settings.base_url, account=account, return_to=return_to)
        except ChatGPTError as exc:
            return JSONResponse({'error': reply_assistance.ERRORS.get(str(exc), 'Could not connect. Try again.')}, status_code=400)
        return {'url': url}

    @app.get('/chatgpt/callback')
    def callback(request: Request, session: Session = Depends(db_session)):
        token = require_user(request)
        if settings.demo_mode:
            raise HTTPException(400, 'Real account connections are disabled in the demo')
        store = Store(session, require_configured())
        return_to = 'campaign'
        try:
            if any(len(request.query_params.getlist(key)) > 1 for key in ('state', 'code', 'client_id', 'error')):
                raise ChatGPTError('chatgpt_state')
            pending = chatgpt_auth.consume(store, token, request.query_params.get('state', ''))
            return_to = pending['return_to']
            first_connection = chatgpt_auth.finish(store, pending, request.query_params)
        except ChatGPTError as exc:
            chatgpt_auth.record_failure(store, exc)
            code = str(exc) if str(exc) in reply_assistance.ERRORS else 'chatgpt_unavailable'
            return RedirectResponse(destination(return_to) + 'assistance_error=' + code, status_code=303)
        return RedirectResponse(destination(return_to) + 'assistance_saved=connect' + ('&chatgpt_first=1' if first_connection else ''), status_code=303)

    @app.post('/chatgpt/disconnect')
    def disconnect(request: Request, csrf: str = Form(''), account: str = Form(''),
                   return_to: str = Form('campaign'), session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        store = Store(session, require_configured())
        if settings.demo_mode:
            store.set_setting('demo_reply_assistance', False, encrypted=True)
            confirmed = True
        else:
            try:
                confirmed = chatgpt_auth.disconnect(store, account)
            except ChatGPTError as exc:
                code = str(exc) if str(exc) in reply_assistance.ERRORS else 'chatgpt_unavailable'
                return RedirectResponse(destination(return_to) + 'assistance_error=' + code, status_code=303)
        return RedirectResponse(destination(return_to) + ('chatgpt_disconnected=1' if confirmed else 'chatgpt_disconnected=unconfirmed'), status_code=303)

    @app.post('/chatgpt/retry')
    def retry(request: Request, csrf: str = Form(''), return_to: str = Form('campaign'),
              session: Session = Depends(db_session)):
        require_csrf(request, csrf)
        if settings.demo_mode:
            raise HTTPException(400, 'Real account connections are disabled in the demo')
        store = Store(session, require_configured())
        try:
            first_connection = chatgpt_auth.retry_connection(store)
        except ChatGPTError as exc:
            code = str(exc) if str(exc) in reply_assistance.ERRORS else 'chatgpt_unavailable'
            return RedirectResponse(destination(return_to) + 'assistance_error=' + code, status_code=303)
        return RedirectResponse(destination(return_to) + 'assistance_saved=connect' + ('&chatgpt_first=1' if first_connection else ''), status_code=303)
