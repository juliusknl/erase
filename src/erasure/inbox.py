"""Durable incoming correspondence. Unknown mail remains visible for review."""

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import select

from erasure.attention import needs_person
from erasure.gmail import GmailError
from erasure.models import Approval, Case, IncomingMessage
from erasure.replies import ReplyKind, classify_reply
from erasure.reply_interpretation import backfill_replies


def gmail_link(message):
    """Search by the exact RFC Message-ID, never by an email-supplied URL."""
    message_id = message.get("message_id", "")
    if message_id and message_id != message.get('id'):
        return "https://mail.google.com/mail/u/0/#search/" + quote(
            "rfc822msgid:" + message_id, safe=""
        )
    provider_id = message.get('id', '')
    if re.fullmatch(r'[a-fA-F0-9]{8,64}', provider_id):
        return 'https://mail.google.com/mail/u/0/#all/' + provider_id
    return "https://mail.google.com/"


def reconcile_attention(workflow):
    """Release old uncertainty-only holds, never close or reopen a completed case."""
    for case in workflow.session.scalars(
        select(Case).where(Case.state == "needs_action", Case.submitted_at.is_not(None))
    ):
        pending = list(
            workflow.session.scalars(
                select(Approval).where(Approval.case_id == case.id, Approval.status == "pending")
            )
        )
        if not pending or any(
            a.kind not in {"ambiguous_reply", "unverified_sender"} for a in pending
        ):
            continue
        payloads = [
            workflow.store.vault.decrypt(a.encrypted_payload) if a.encrypted_payload else {}
            for a in pending
        ]
        if any(needs_person(a, p) for a, p in zip(pending, payloads, strict=True)):
            continue
        case.state = "submitted"
        if any(p.get("previous_state") == "processing" for p in payloads):
            case.state = "processing"
        for action, payload in zip(pending, payloads, strict=True):
            message = payload.get("message", payload)
            kind = classify_reply(message.get("subject", ""), message.get("body", "")).kind
            if action.kind == "ambiguous_reply" and kind in {
                ReplyKind.CONFIRMATION,
                ReplyKind.INFORMATIONAL,
            }:
                action.status = "recorded"
                action.resolved_at = datetime.now(UTC)
                if kind == ReplyKind.CONFIRMATION:
                    case.state = "processing"
        workflow.ensure_follow_up(case)
        workflow.store.add_event(
            case.id,
            "reply_triage_updated",
            "Routine or uncertain reply recorded without a required user task; no deletion inferred",
        )
    workflow.session.commit()


def recover_missing_bodies(workflow, gmail):
    """Three durable attempts, at most ten messages per poll; no external links."""
    now = datetime.now(UTC)
    checked = 0
    for record in workflow.session.scalars(
        select(IncomingMessage).order_by(IncomingMessage.created_at)
    ):
        message = workflow.store.vault.decrypt(record.encrypted_payload)
        if message.get("body", "").strip():
            continue
        key = f"mail_recovery:{record.id}"
        state = workflow.store.get_setting(key, {})
        if state.get("attempts", 0) >= 3 or state.get("next_try", "") > now.isoformat():
            continue
        if checked >= 10:
            break
        checked += 1
        attempts = state.get("attempts", 0) + 1
        workflow.store.set_setting(
            key,
            {
                "attempts": attempts,
                "status": "retrying",
                "next_try": (now + timedelta(minutes=5 * attempts)).isoformat(),
            },
            encrypted=True,
        )
        try:
            recovered = gmail.read_message(record.id)
        except GmailError:
            workflow.store.set_setting(key, state, encrypted=True)
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403, 429} or exc.response.status_code >= 500:
                workflow.store.set_setting(key, state, encrypted=True)
                raise
            recovered = {}
        except httpx.RequestError:
            workflow.store.set_setting(key, state, encrypted=True)
            raise
        except httpx.HTTPError:
            recovered = {}
        except (ValueError, KeyError):
            recovered = {}
        if recovered.get("body", "").strip():
            record.encrypted_payload = workflow.store.vault.encrypt(recovered)
            record.status = "pending_processing"
            # Replace only the empty copy of this exact message. Never erase a
            # substantive reply or discard an approval for a different email.
            for action in workflow.session.scalars(
                select(Approval).where(
                    Approval.case_id == record.case_id, Approval.status == "pending"
                )
            ):
                payload = (
                    workflow.store.vault.decrypt(action.encrypted_payload)
                    if action.encrypted_payload
                    else {}
                )
                original = payload.get("message", payload)
                if original.get("id") == record.id and not original.get("body", "").strip():
                    action.status = "superseded"
            workflow.session.commit()
            apply_message(workflow, record)
            workflow.store.set_setting(
                key, {"attempts": attempts, "status": "recovered"}, encrypted=True
            )
        else:
            workflow.store.set_setting(
                key,
                {
                    "attempts": attempts,
                    "status": "unavailable" if attempts >= 3 else "retrying",
                    "next_try": (now + timedelta(minutes=5 * attempts)).isoformat(),
                },
                encrypted=True,
            )


def capture_message(workflow, message):
    session, store = workflow.session, workflow.store
    if session.get(IncomingMessage, message["id"]):
        return
    record = IncomingMessage(
        id=message["id"],
        encrypted_payload=store.vault.encrypt(message),
        status="pending_processing",
    )
    session.add(record)
    # Persist before classification; failed processing remains reviewable on retry.
    session.commit()
    apply_message(workflow, record)


def apply_message(workflow, record):
    """Isolate parser failures without losing mail or repeatedly blocking sync."""
    key = f"mail_processing:{record.id}"
    state = workflow.store.get_setting(key, {})
    if state.get('next_try', '') > datetime.now(UTC).isoformat():
        return
    try:
        _apply_message(workflow, record)
    except Exception as exc:
        # process_message has durable intermediate commits. Roll back only the
        # current transaction; never discard already stored correspondence.
        workflow.session.rollback()
        attempts = state.get('attempts', 0) + 1
        record.status = 'review' if attempts >= 3 else 'pending_processing'
        workflow.store.set_setting(key, {
            'attempts': attempts, 'error': type(exc).__name__,
            'next_try': (datetime.now(UTC) + timedelta(minutes=5 * attempts)).isoformat(),
        }, encrypted=True)
    else:
        if state:
            workflow.store.set_setting(key, {'status': 'recovered'}, encrypted=True)


def _apply_message(workflow, record):
    message = workflow.store.vault.decrypt(record.encrypted_payload)
    if workflow.process_message(message, linked_case_id=record.case_id):
        record.status = "processed"
        record.case_id = message.get("_case_id")
    else:
        record.status = "review"
    workflow.session.commit()


def review_message(workflow, record, case_id, outcome):
    """Explicit user review may link third-party senders; never infer their trust."""
    if record.status != "review":
        raise ValueError("Message was already reviewed")
    if outcome == "link":
        case = workflow.session.get(Case, case_id)
        if case is None:
            raise ValueError("Choose a broker to link this message")
        message = workflow.store.vault.decrypt(record.encrypted_payload)
        workflow.process_message(message, linked_case_id=case.id)
        record.case_id = case.id
        record.status = "processed"
    elif outcome == "dismiss":
        record.status = "dismissed"
    else:
        case = workflow.session.get(Case, case_id)
        if case is None or outcome not in {"removed", "not_found", "processing", "needs_action"}:
            raise ValueError("Choose a case and a valid outcome")
        if case.state in {"removed", "not_found"} and outcome in {"processing", "needs_action"}:
            raise ValueError("A completed case cannot be reopened by an older acknowledgement")
        message = workflow.store.vault.decrypt(record.encrypted_payload)
        workflow.store.add_event(case.id, "reply_reviewed", f"Reply reviewed: {outcome}", message)
        if outcome in {"removed", "not_found"}:
            workflow._complete(case, outcome)
        else:
            case.state = outcome
            if outcome == "needs_action":
                workflow.cancel_case_jobs(case.id)
                case.next_action_at = None
                pending = workflow.session.scalar(
                    select(Approval).where(
                        Approval.case_id == case.id,
                        Approval.kind == "ambiguous_reply",
                        Approval.status == "pending",
                    )
                )
                if pending is None:
                    workflow._create_approval(
                        case.id,
                        "ambiguous_reply",
                        "Broker requested another step — read the reply and respond",
                        message,
                    )
        record.case_id = case.id
        record.status = "reviewed"
    workflow.session.commit()


def poll_mailbox(workflow, gmail):
    reconcile_attention(workflow)
    for record in workflow.session.scalars(
        select(IncomingMessage).where(IncomingMessage.status == "pending_processing")
    ):
        apply_message(workflow, record)
    recover_missing_bodies(workflow, gmail)
    for message_id in reversed(gmail.list_recent()):
        if workflow.session.get(IncomingMessage, message_id) is None:
            try:
                message = gmail.read_message(message_id)
            except httpx.HTTPStatusError as exc:
                # Mail can be deleted between listing and download. Retain a
                # recoverable placeholder; authentication/network errors still
                # stop the poll without advancing its success checkpoint.
                if exc.response.status_code not in {404, 410}:
                    raise
                message = {'id': message_id, 'subject': '', 'body': '', 'from': ''}
            except (ValueError, KeyError, TypeError):
                # A malformed email must not prevent the rest of the mailbox
                # from syncing. Recover its content using the same bounded path.
                message = {'id': message_id, 'subject': '', 'body': '', 'from': ''}
            capture_message(workflow, message)
    backfill_replies(workflow)
    workflow.store.set_setting("gmail_error", "")
    workflow.store.set_setting("gmail_last_sync", datetime.now(UTC).isoformat())
