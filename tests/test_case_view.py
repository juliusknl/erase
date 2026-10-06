from datetime import UTC, datetime, timedelta

from erasure.case_view import conversation
from erasure.models import Approval, Broker, Case, IncomingMessage
from erasure.store import Store


def test_conversation_keeps_distinct_replies_and_pairs_each_send_with_its_draft(db, vault):
    broker = Broker(slug="history", name="History", domain="history.test")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id)
    db.add(case)
    db.flush()
    store = Store(db, vault)
    store.add_event(case.id, "request_prepared", "Draft", {"body": "First request"})
    store.add_event(case.id, "submitted", "Sent first")
    store.add_event(case.id, "request_prepared", "Draft", {"body": "Second request"})
    store.add_event(case.id, "submitted", "Sent second")
    store.add_event(case.id, "request_prepared", "Not sent", {"body": "Unsent draft"})
    for i in range(2):
        mail = {
            "id": f"gmail-{i}",
            "message_id": f"<mail-{i}>",
            "body": "Identical automated response",
        }
        db.add(
            IncomingMessage(id=mail["id"], case_id=case.id, encrypted_payload=vault.encrypt(mail))
        )
        db.add(
            Approval(
                case_id=case.id,
                kind="unverified_sender",
                summary="Held",
                encrypted_payload=vault.encrypt({"message": mail}),
            )
        )
        store.add_event(
            case.id,
            "reply_held",
            "Held",
            {"message_id": mail["message_id"], "reason": "Missing evidence"},
        )
    # An authenticated reprocessing logs the same reply, not a third email.
    store.add_event(
        case.id,
        "reply_received",
        "Verified",
        {
            "id": "gmail-1",
            "body": "Identical automated response",
            "sender_trust": "manually approved",
        },
    )
    store.add_event(case.id, "user_completed", "Quick win completed")
    db.commit()
    items = conversation(db, vault, case.id)
    assert {item["mail"]["body"] for item in items if item["kind"] == "sent"} == {
        "First request",
        "Second request",
    }
    replies = [item for item in items if item["kind"] == "received"]
    assert len(replies) == 2
    assert sum(item["held"] for item in replies) == 1
    assert items[0]["kind"] == "step"
    assert all(item["mail"].get("body") != "Unsent draft" for item in items)


def test_conversation_includes_legacy_nested_messages_not_internal_guidance(db, vault):
    broker = Broker(slug="legacy", name="Legacy")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id)
    db.add(case)
    db.flush()
    store = Store(db, vault)
    db.add(
        Approval(
            case_id=case.id,
            kind="next_step",
            summary="Internal instruction",
            encrypted_payload=vault.encrypt({"body": "Use the official website"}),
        )
    )
    old = store.add_event(
        case.id,
        "reply_reviewed",
        "Manual review",
        {"message": {"body": "Legacy body", "subject": "Legacy subject"}},
    )
    old.created_at = datetime.now(UTC) - timedelta(days=1)
    store.add_event(case.id, "reply_sent", "Follow-up", {"body": "A follow-up"})
    db.commit()
    items = conversation(db, vault, case.id)
    assert len(items) == 3  # A received email, its manual review, a sent reply.
    assert items[0]["kind"] == "sent"
    assert (
        next(item for item in items if item["kind"] == "received")["mail"]["body"] == "Legacy body"
    )


def test_legacy_copy_merges_with_one_identified_message(db, vault):
    broker = Broker(slug="mixed", name="Mixed")
    db.add(broker)
    db.flush()
    case = Case(broker_id=broker.id)
    db.add(case)
    db.flush()
    mail = {"body": "Same email", "subject": "My reply", "from": "privacy@broker.test"}
    db.add(
        IncomingMessage(
            id="known-id",
            case_id=case.id,
            encrypted_payload=vault.encrypt({**mail, "id": "known-id"}),
        )
    )
    db.add(
        Approval(
            case_id=case.id,
            kind="ambiguous_reply",
            summary="Legacy copy",
            encrypted_payload=vault.encrypt(mail),
        )
    )
    db.commit()
    assert len(conversation(db, vault, case.id)) == 1
