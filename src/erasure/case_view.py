"""Read-only presentation of a request's mail and manual milestones."""

import hashlib
import json
from datetime import UTC

from sqlalchemy import select

from erasure.models import Approval, Event, IncomingMessage

MANUAL_EVENTS = {
    "form_submitted",
    "user_completed",
    "email_confirmation_recorded",
    "identity_proof_sent",
    "quick_win_completed",
    "reply_reviewed",
}


def conversation(session, vault, case_id):
    events = list(
        session.scalars(
            select(Event).where(Event.case_id == case_id).order_by(Event.created_at, Event.id)
        )
    )
    entries = []
    messages = {}
    aliases = {}
    fingerprints = {}

    def add_message(record, mail, *, held=False):
        if not isinstance(mail, dict):
            return
        # Provider IDs and RFC message IDs bridge incoming records, approval
        # payloads and legacy events. Do not merge distinct identified emails
        # merely because two automated replies contain the same words.
        keys = [str(mail[k]) for k in ("id", "message_id") if mail.get(k)]
        fingerprint = json.dumps(
            {k: mail.get(k, "") for k in ("from", "subject", "body")}, sort_keys=True
        )
        legacy_key = "legacy:" + hashlib.sha256(fingerprint.encode()).hexdigest()
        if keys:
            key = next((aliases[k] for k in keys if k in aliases), keys[0])
        else:
            candidates = fingerprints.get(legacy_key, set())
            key = next(iter(candidates)) if len(candidates) == 1 else legacy_key
        fingerprints.setdefault(legacy_key, set()).add(key)
        for alias in keys:
            aliases[alias] = key
        if key not in messages:
            messages[key] = dict(record=record, mail=dict(mail), kind="received", held=held)
            entries.append(messages[key])
        else:
            entry = messages[key]
            entry["mail"].update({k: v for k, v in mail.items() if v})
            entry["held"] = entry["held"] or held

    for record in session.scalars(
        select(IncomingMessage)
        .where(IncomingMessage.case_id == case_id)
        .order_by(IncomingMessage.created_at, IncomingMessage.id)
    ):
        add_message(record, vault.decrypt(record.encrypted_payload))
    for approval in session.scalars(
        select(Approval)
        .where(Approval.case_id == case_id)
        .order_by(Approval.created_at, Approval.id)
    ):
        payload = vault.decrypt(approval.encrypted_payload) if approval.encrypted_payload else {}
        mail = payload.get("message", payload)
        if approval.kind in {
            "unverified_sender",
            "ambiguous_reply",
            "form_required",
            "identity_proof",
            "information_requested",
            "confirmation_link",
        } and ("body" in mail or "subject" in mail):
            add_message(approval, mail, held=approval.kind == "unverified_sender")

    prepared = None
    for event in events:
        payload = vault.decrypt(event.encrypted_payload) if event.encrypted_payload else {}
        mail = payload.get("message", payload)
        if event.kind == "request_prepared":
            prepared = payload
        elif event.kind == "submitted":
            # Pair with the draft preceding THIS send, never a later recheck.
            entries.append(dict(record=event, mail=prepared or {}, kind="sent", held=False))
            prepared = None
        elif event.kind == "reply_sent":
            entries.append(dict(record=event, mail=mail, kind="sent", held=False))
        elif event.kind in {"reply_received", "reply_reviewed"}:
            if any(k in mail for k in ("body", "subject", "from")):
                add_message(event, mail)
            if event.kind == "reply_reviewed":
                entries.append(dict(record=event, mail={}, kind="step", held=False))
        elif event.kind in MANUAL_EVENTS:
            entries.append(dict(record=event, mail={}, kind="step", held=False))
        elif event.kind == "approval_resolved" and event.summary == "Browser Challenge approved":
            entries.append(
                dict(
                    record=event,
                    mail={},
                    kind="step",
                    held=False,
                    summary="You recorded completing the broker’s browser step",
                )
            )
        elif event.kind == "reply_held":
            key = aliases.get(str(payload.get("message_id", "")))
            if key:
                messages[key]["held"] = True
                messages[key]["mail"]["hold_reason"] = payload.get("reason", "")
            elif not any(item["held"] for item in messages.values()):
                # Legacy records can know a reply exists without storing its body.
                add_message(event, payload, held=True)

    # A later explicit sender approval is preserved; merely reading or reviewing
    # an outcome must not silently certify a sender.
    for entry in messages.values():
        if entry["mail"].get("sender_trust"):
            entry["held"] = False
    return sorted(
        entries, key=lambda item: item["record"].created_at.replace(tzinfo=UTC), reverse=True
    )
