from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from erasure.attention import needs_person
from erasure.config import get_settings
from erasure.connectors.base import RequestPlan
from erasure.crypto import Vault
from erasure.db import SessionLocal, init_db
from erasure.gmail import GmailClient, GmailError
from erasure.inbox import poll_mailbox
from erasure.models import Approval, Case, Job
from erasure.store import Store
from erasure.workflow import Workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("erasure.worker")
RECURRING = {"poll_gmail": 5, "prepare_backlog": 5, "campaign_tick": 1}
OUTGOING = {"submit_case", "automatic_send", "follow_up", "recheck_case"}


def defer_job(store, job, until, reason):
    job.status, job.run_at, job.last_error = 'pending', until, reason
    job.lease_until, job.attempts = None, 0
    store.session.commit()


def recover_schedules(store):
    """Restart/wake recovery; one recurring schedule and no replay of missed ticks."""
    now = datetime.now(UTC)
    for kind in RECURRING:
        jobs = list(store.session.scalars(select(Job).where(
            Job.kind == kind, Job.status.in_(['pending', 'running', 'failed'])
        ).order_by(Job.id.desc())))
        active = next((job for job in jobs if job.status == 'running' and job.lease_until
                       and job.lease_until.replace(tzinfo=UTC) > now), None)
        if active:
            keeper = active
        elif jobs:
            keeper = jobs[0]
            defer_job(store, keeper, now, '')
        elif kind != 'poll_gmail' or store.get_setting('gmail_token'):
            keeper = store.enqueue(kind, {})
        else:
            continue
        for duplicate in jobs:
            if duplicate.id != keeper.id:
                duplicate.status = 'cancelled'
        store.session.commit()


def ready_to_send(store, job, *, demo=False):
    """Fresh inbox first; pace overdue work instead of bursting after downtime."""
    if demo:
        return True
    now = datetime.now(UTC)
    last_sync = store.get_setting('gmail_last_sync', '')
    try:
        fresh = now - datetime.fromisoformat(last_sync).replace(tzinfo=UTC) < timedelta(minutes=15)
    except ValueError:
        fresh = False
    if not fresh or store.get_setting('gmail_error'):
        defer_job(store, job, now + timedelta(minutes=1), 'Waiting for a successful mailbox check')
        store.enqueue_if_missing('poll_gmail', {})
        return False
    next_send = store.get_setting('worker_next_send', '')
    if next_send and next_send > now.isoformat():
        defer_job(store, job, datetime.fromisoformat(next_send), 'Scheduled between automatic emails')
        return False
    store.set_setting('worker_next_send', (now + timedelta(minutes=1)).isoformat())
    return True


def handle_job(kind: str, payload: dict, workflow: Workflow, store: Store) -> None:
    if kind == "submit_case":
        workflow.submit_case(int(payload["case_id"]))
    elif kind == "recheck_case":
        workflow.recheck_case(int(payload["case_id"]))
    elif kind == "follow_up":
        workflow.follow_up(int(payload["case_id"]))
    elif kind == "follow_confirmation":
        case = workflow.session.get(Case, int(payload["case_id"]))
        # Legacy jobs lack a broker-specific verification recipe. Never treat
        # fetching a generic page as completed verification or revive done cases.
        if case is not None:
            workflow.require_email_confirmation(case, {
                "body": "A previously queued link needs review. Check the broker's latest reply "
                        "before confirming your request.\n" + str(payload.get("url", "")),
            })
    elif kind == "send_alert":
        approval = workflow.session.get(Approval, int(payload["approval_id"]))
        alert_email = store.get_setting("alert_email", "")
        action_payload = store.vault.decrypt(approval.encrypted_payload) if approval and approval.encrypted_payload else {}
        if approval is not None and approval.status == "pending" and alert_email and needs_person(approval, action_payload):
            GmailClient(workflow.settings, store).send(
                RequestPlan(
                    channel="email",
                    destination=alert_email,
                    subject=f"erase action required: {approval.kind.replace('_', ' ')}",
                    body=(
                        f"{approval.summary}\n\nOpen {workflow.settings.base_url.rstrip('/')}/cases/{approval.case_id}?step={approval.id} "
                        "from this Mac to review it. No sensitive identity data is included in this alert."
                    ),
                    disclosed_fields=(),
                )
            )
    elif kind == "poll_gmail":
        gmail = GmailClient(workflow.settings, store)
        try:
            poll_mailbox(workflow, gmail)
        finally:
            gmail.client.close()
    elif kind == "prepare_backlog":
        from erasure.preparation import prepare_backlog

        prepare_backlog(workflow)
    elif kind == "campaign_tick":
        from erasure.campaign import tick

        tick(workflow)
    elif kind == "research_broker":
        from erasure.campaign import research_broker

        research_broker(workflow, int(payload["broker_id"]))
    elif kind == "automatic_send":
        from erasure.campaign import dispatch

        dispatch(workflow, int(payload["delivery_id"]))
    else:
        raise ValueError(f"Unknown job kind: {kind}")


def run_once() -> bool:
    settings = get_settings()
    if not settings.configured:
        raise RuntimeError("Application secrets are not configured")
    with SessionLocal() as session:
        store = Store(session, Vault(settings.master_key))
        claimed = store.claim_job(lease_seconds=300)
        if claimed is None:
            return False
        job, payload = claimed
        workflow = Workflow(session, store, settings)
        if job.kind in OUTGOING and store.get_setting("paused", "false") == "true":
            # Keep the same durable job, and do not change the request's outcome.
            # Mailbox polling remains active while outgoing automation is held.
            job.status = "pending"
            job.run_at = datetime.now(UTC) + timedelta(minutes=5)
            job.lease_until = None
            job.attempts = 0
            job.last_error = "Held while automatic sending is paused"
            session.commit()
            return True
        if job.kind in OUTGOING and not ready_to_send(store, job, demo=settings.demo_mode):
            return True
        try:
            handle_job(job.kind, payload, workflow, store)
            if job.kind == "prepare_backlog":
                store.set_setting("preparation_error", "")
            if job.kind == "campaign_tick":
                store.set_setting("campaign_error", "")
            if job.kind in RECURRING:
                # Reuse one durable recurring job, including across auth failures.
                job.status = "pending"
                job.run_at = datetime.now(UTC) + (
                    timedelta(seconds=5) if settings.demo_mode else timedelta(minutes=RECURRING[job.kind]))
                job.lease_until = None
                job.attempts = 0
                job.last_error = ""
                session.commit()
            else:
                store.finish_job(job)
        except GmailError as exc:
            logger.warning("Gmail job paused: %s", type(exc).__name__)
            store.fail_job(job, "Gmail is unavailable or needs reconnection")
        except Exception as exc:  # pragma: no cover - worker safety boundary
            # Tracebacks can contain message bodies, SQL parameters or signed URLs.
            logger.warning("Job %s failed (%s)", job.id, type(exc).__name__)
            store.fail_job(job, type(exc).__name__)
        if job.kind in RECURRING and job.last_error:
            if job.kind == "campaign_tick":
                store.set_setting(
                    "campaign_error", "Campaign controller failed; retrying in 15 minutes"
                )
            if job.kind == "prepare_backlog":
                store.set_setting(
                    "preparation_error",
                    "Automatic preparation failed. Retrying in 15 minutes; inspect local worker logs if this persists.",
                )
            if job.kind == "poll_gmail" and not store.get_setting("gmail_error"):
                store.set_setting(
                    "gmail_error",
                    "Mailbox check failed. Retrying automatically; reconnect if access expired.",
                )
            job.status = "pending"
            job.run_at = datetime.now(UTC) + timedelta(minutes=15)
            job.lease_until = None
            session.commit()
        return True


def work_until_stopped(stop_event: threading.Event) -> None:
    settings = get_settings()
    init_db()
    last_iteration = None
    logger.info("erase worker started; live_submissions=%s", settings.live_submissions)
    while not stop_event.is_set():
        try:
            now = datetime.now(UTC)
            if last_iteration is None or now - last_iteration > timedelta(minutes=2):
                with SessionLocal() as session:
                    recover_schedules(Store(session, Vault(settings.master_key)))
            last_iteration = now
            worked = run_once()
        except Exception as exc:
            logger.warning("Worker iteration failed (%s); retrying", type(exc).__name__)
            worked = False
        if not worked:
            stop_event.wait(settings.worker_poll_seconds)


def main() -> None:
    work_until_stopped(threading.Event())


if __name__ == "__main__":
    main()
