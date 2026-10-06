"""One shared boundary between a human decision and internal bookkeeping."""

import re
from datetime import UTC, datetime

from erasure.replies import actionable_reply, removal_reply_text

ACTIONABLE_REPLY_KINDS = {
    'form_required', 'email_verification', 'identity_requested',
    'information_requested', 'action_required', 'bounced', 'rejected',
}


def email_only_identity(action, payload):
    """Documents and representative authorization are handled outside the app."""
    message = payload.get('message', payload)
    if action.kind == 'identity_proof' or payload.get('proposed_kind') == 'identity_requested':
        return True
    interpretation = message.get('_interpretation', {})
    if isinstance(interpretation, dict) and interpretation.get('kind') == 'identity_requested':
        return True
    for sentence in re.split(r'(?<=[.!?])\s+', removal_reply_text(message.get('body', ''))):
        if re.search(r"(?:do not|don't|not required to|no need to) (?:provide|submit|send)|"
                     r"(?:do not|don't) (?:need|require)", sentence, flags=re.I):
            continue
        if re.search(
            r'(?:please|must|required|need|request|provide|submit|send).{0,140}'
            r'(?:signed authori[sz]ation|power of attorney|authori[sz]ation (?:document|letter|form)|'
            r'proof of identity|government[- ]issued (?:id|identification)|copy of (?:your |a )?passport)',
            sentence, flags=re.I | re.S):
            return True
    return False


def automation_summary(store, pipeline, live):
    synced = store.get_setting("gmail_last_sync")
    last_sync = datetime.fromisoformat(synced).replace(tzinfo=UTC) if synced else None
    stale = last_sync is None or (datetime.now(UTC) - last_sync).total_seconds() > 900
    automatic = pipeline['automatic']
    enabled = automatic['enabled']
    paused = store.get_setting('paused', 'false') == 'true'
    mailbox_ready = bool(store.get_setting('gmail_token')) and not store.get_setting('gmail_error')
    result = dict(
        title="Running",
        state="running",
        instruction="Requests, reply checks and supported follow-ups run automatically. Keep the local app running.",
        detail="Monitoring replies and preparing eligible requests",
        control="pause",
        can_stop=enabled,
        last_sync=last_sync,
        mailbox="Connected" if mailbox_ready else "Needs connection",
    )
    if not enabled:
        result.update(title='Stopped', state='stopped', control='plan',
                      instruction='No automatic broker emails will be sent. Start when you’re ready.',
                      detail='Your history is kept; connected Gmail replies are still checked')
    elif paused:
        result.update(title='Paused', state='paused', control='resume',
                      instruction='Requests and follow-ups are on hold. Reply tracking continues while Gmail is connected.',
                      detail='Resume whenever you’re ready')
    elif not mailbox_ready:
        result.update(
            title="Needs attention",
            state="blocked",
            instruction="Connect or reconnect Gmail to send requests and check replies.",
            control="connect",
            detail="Gmail needs reconnection",
        )
    elif not live:
        result.update(title='Needs attention', state='blocked', control='plan',
                      instruction='Sending is disabled in this installation. No emails are being sent.',
                      detail='Live sending must be enabled in the local app configuration')
    elif automatic.get('problem'):
        retryable = bool(store.get_setting('campaign_error')) or 'checks delayed' in automatic['problem']
        result.update(title='Needs attention', state='blocked', control='check' if retryable else 'review',
                      instruction=('Background checks are delayed. Retry; if this persists, restart the local app.'
                                   if retryable else 'Your profile or email permissions changed. Review them before sending resumes.'),
                      detail='Background checks need attention' if retryable else 'Review your sending permission')
    elif stale:
        result.update(
            title="Needs attention" if last_sync else "Starting",
            state="blocked",
            instruction="Waiting for a successful mailbox check. Retry; if this persists, restart the local app.",
            control="check",
            detail="Mailbox check overdue" if last_sync else "Waiting for the first mailbox check",
        )
        if last_sync is None and store.get_setting('setup_completed_at'):
            result.update(title='Starting your requests…', state='starting',
                          instruction='Your permission is saved. Checking the mailbox and preparing your first eligible requests.',
                          detail='Waiting for the first successful mailbox check')
    elif not automatic.get('last_tick'):
        result.update(title='Starting', state='starting',
                      detail='Waiting for the first automation check')
    elif automatic.get('include_new') is False:
        result.update(control='review',
                      instruction='Your existing requests are running. Review permissions once to include newly validated brokers automatically.',
                      detail='Your current permission covers a fixed broker list')
    elif automatic.get('today', 0) >= automatic.get('daily_limit', 20):
        result['detail'] = 'Today’s sending limit reached; emails continue tomorrow. Reply checks continue.'
    elif store.get_setting('setup_completed_at') and automatic.get('sent_count') == 1:
        result['detail'] = 'Your first request was sent. Preparing more and watching for replies.'
    return result


def needs_person(action, payload):
    message = payload.get("message", payload)
    body = message.get("body", "")
    if email_only_identity(action, payload):
        return bool(body.strip())
    if action.kind in {"ambiguous_reply", "unverified_sender"}:
        interpretation = message.get('_interpretation', {})
        if isinstance(interpretation, dict) and interpretation.get('source') == 'jev':
            return interpretation.get('kind') in ACTIONABLE_REPLY_KINDS
        return actionable_reply(body, message.get("subject", ""))
    if action.kind in {"identity_proof", "information_requested"}:
        return bool(body.strip())
    if action.kind in {"form_required", "confirmation_link", "browser_challenge", "next_step"}:
        return bool(body.strip() or payload.get("action_url"))
    if action.kind == "complaint":
        return bool(payload.get("draft"))
    # Contact research, missing data and internal failures belong to automation
    # status, not a count of decisions the person can supposedly complete.
    return False
