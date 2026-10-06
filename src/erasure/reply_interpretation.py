"""Cached optional AI interpretation; existing workflow still owns every action."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from erasure import chatgpt, chatgpt_auth
from erasure.case_view import MANUAL_EVENTS
from erasure.jev import MODEL, PROMPT_VERSION, JevClassifier, JevError, saved_private_values
from erasure.models import Case, Event, IncomingMessage
from erasure.replies import ClassifiedReply, ReplyKind, classify_reply
from erasure.reply_assistance import configuration, selection


def enabled(settings, store=None):
    return selection(settings, store)['enabled']


def cache_key(case_id, message, selected=None):
    is_chatgpt = selected and selected['provider'] == 'chatgpt'
    content = [chatgpt.MODEL if is_chatgpt else MODEL,
               (chatgpt.PROMPT_VERSION + selected.get('account', '')) if is_chatgpt else PROMPT_VERSION, case_id,
               *[message.get(k, '') for k in ('id', 'message_id', 'subject', 'body')]]
    return ('chatgpt_decision:' if is_chatgpt else 'jev_decision:') + hashlib.sha256(json.dumps(content).encode()).hexdigest()


def interpret(workflow, case_id, message):
    rules = classify_reply(message['subject'], message['body'])
    selected_provider = selection(workflow.settings, workflow.store)
    if not selected_provider['enabled']:
        return rules, {}
    store = workflow.store
    provider = selected_provider['provider']
    key = cache_key(case_id, message, selected_provider)
    cached = store.get_setting(key, {})
    now = datetime.now(UTC)
    health_key = provider + '_health'
    health = store.get_setting(health_key, {})
    if not cached:
        if health.get('retry_after', '') > now.isoformat():
            return rules, {'source': 'rules', 'reason': 'AI temporarily unavailable'}
        client = None
        try:
            client = (chatgpt.ChatGPTClassifier(chatgpt_auth.access_token(store, selected_provider.get('account', '')))
                      if provider == 'chatgpt' else JevClassifier(configuration(workflow.settings, store)[1]))
            if selection(workflow.settings, store) != selected_provider:
                return rules, {'source': 'rules', 'reason': 'Reply assistance changed before classification'}
            reply = client.classify(message['subject'], message['body'],
                                    private_values=saved_private_values(store.get_profile() or {}))
        except JevError as exc:
            if str(exc) in {'empty_reply', 'reply_too_long'}:
                store.set_setting(key, {'skipped': str(exc), 'applied': True}, encrypted=True)
            else:
                store.set_setting(health_key, {
                    **health, 'error': str(exc),
                    'diagnostic': getattr(exc, 'diagnostic', {}),
                    'retry_after': (now + timedelta(minutes=15)).isoformat(),
                }, encrypted=True)
            return rules, {'source': 'rules', 'reason': str(exc)}
        finally:
            if client is not None:
                client.close()
        if selection(workflow.settings, store) != selected_provider:
            return rules, {'source': 'rules', 'reason': 'Reply assistance changed during classification'}
        # Jev's confidence is a distribution statistic, not a measured accuracy.
        # Higher threshold for closing a request than for categorizing a next step.
        threshold = 0.85 if reply.kind in {ReplyKind.COMPLETED, ReplyKind.NOT_FOUND} else 0.5
        accepted = reply.kind != ReplyKind.AMBIGUOUS and (provider == 'chatgpt' or reply.confidence >= threshold)
        selected = reply.kind if accepted else (
            ReplyKind.AMBIGUOUS if rules.kind in {ReplyKind.COMPLETED, ReplyKind.NOT_FOUND} else rules.kind)
        guard = ''
        if rules.kind == ReplyKind.FORM_REQUIRED and selected in {
                ReplyKind.CONFIRMATION, ReplyKind.INFORMATIONAL, ReplyKind.COMPLETED, ReplyKind.NOT_FOUND}:
            # A generic receipt must not erase an explicit designated-form step.
            selected = ReplyKind.FORM_REQUIRED
            guard = 'Explicit form instruction preserved'
        cached = {'source': provider if accepted else provider + '_uncertain', 'kind': selected.value,
                  'proposed_kind': reply.kind.value, 'confidence': getattr(reply, 'confidence', None),
                  'probabilities': getattr(reply, 'probabilities', {}), 'model': reply.model,
                  'prompt_version': chatgpt.PROMPT_VERSION if provider == 'chatgpt' else PROMPT_VERSION, 'input_tokens': reply.input_tokens,
                  'classified_at': now.isoformat(), 'applied': False}
        if provider == 'chatgpt':
            cached['evidence'] = reply.evidence
        if guard:
            cached['guard'] = guard
        store.set_setting(key, cached, encrypted=True)
        store.set_setting(health_key, {'last_success': now.isoformat(), 'error': '',
                          'retry_after': '', 'evaluated': health.get('evaluated', 0) + 1,
                          'input_tokens': health.get('input_tokens', 0) + reply.input_tokens}, encrypted=True)
    if cached.get('skipped'):
        return rules, {'source': 'rules', 'reason': cached['skipped']}
    # ChatGPT does not supply a calibrated probability. 50 is the legacy neutral
    # workflow value, not model confidence; the audit explicitly records null.
    return ClassifiedReply(ReplyKind(cached['kind']), round(cached['confidence'] * 100) if cached['confidence'] is not None else 50,
                           'AI interpreted reply' if cached['source'] in {'jev', 'chatgpt'} else 'AI uncertain; conservative fallback'), {
        **cached, '_cache_key': key,
    }


def mark_applied(workflow, metadata):
    key = metadata.get('_cache_key')
    if key:
        cached = workflow.store.get_setting(key, {})
        cached['applied'] = True
        workflow.store.set_setting(key, cached, encrypted=True)


def has_later_user_action(workflow, case_id, since):
    return bool(workflow.session.scalar(select(Event.id).where(
        Event.case_id == case_id, Event.created_at >= since,
        Event.kind.in_(MANUAL_EVENTS | {'reply_sent', 'approval_resolved', 'submitted'})).limit(1)))


def backfill_replies(workflow, limit=10):
    """Reinterpret only the latest unreviewed reply per open request, in bounded batches."""
    if not enabled(workflow.settings, workflow.store):
        return 0
    selected = selection(workflow.settings, workflow.store)
    health_key = selected['provider'] + '_health'
    health = workflow.store.get_setting(health_key, {})
    if health.get('retry_after', '') > datetime.now(UTC).isoformat():
        return 0
    latest = {}
    for record in workflow.session.scalars(select(IncomingMessage).where(
        IncomingMessage.case_id.is_not(None)).order_by(IncomingMessage.created_at.desc(), IncomingMessage.id.desc())):
        latest.setdefault(record.case_id, record)
    checked = 0
    for case_id, record in latest.items():
        case = workflow.session.get(Case, case_id)
        if not case or case.state in {'done', 'removed', 'not_found'} or record.status != 'processed':
            continue
        # Do not replay old instructions after the person submitted a form,
        # replied, dismissed an action or corrected an outcome themselves.
        if has_later_user_action(workflow, case_id, record.created_at):
            continue
        message = workflow.store.vault.decrypt(record.encrypted_payload)
        cached = workflow.store.get_setting(cache_key(case_id, message, selected), {})
        if cached.get('applied'):
            continue
        recovery_key = f'mail_reinterpretation:{record.id}'
        recovery = workflow.store.get_setting(recovery_key, {})
        if recovery.get('attempts', 0) >= 3 or recovery.get('next_try', '') > datetime.now(UTC).isoformat():
            continue
        try:
            workflow.process_message(message, linked_case_id=case_id, reclassifying=True)
        except Exception as exc:
            workflow.session.rollback()
            workflow.store.set_setting(recovery_key, {
                'attempts': recovery.get('attempts', 0) + 1,
                'next_try': (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
                'error': type(exc).__name__,
            }, encrypted=True)
        checked += 1
        if checked >= limit or workflow.store.get_setting(health_key, {}).get('error'):
            break
    return checked
