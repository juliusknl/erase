from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erasure.attention import ACTIONABLE_REPLY_KINDS, email_only_identity, needs_person
from erasure.config import Settings
from erasure.connectors import BrowserConnector, EmailConnector
from erasure.connectors.base import Outcome, RequestPlan
from erasure.gmail import GmailClient, UncertainSubmission
from erasure.knowledge import reviewed_form
from erasure.models import Approval, Broker, Case, Job, Profile, case_token
from erasure.replies import (
    ReplyKind,
    actionable_reply,
    assess_sender,
    classify_reply,
    extract_case_token,
    new_reply_text,
    request_form_url,
)
from erasure.reply_interpretation import has_later_user_action, interpret, mark_applied
from erasure.store import Store

TERMINAL_STATES = {"done", "removed", "not_found", "rejected", "delivery_failed"}


class Workflow:
    def __init__(self, session: Session, store: Store, settings: Settings):
        self.session = session
        self.store = store
        self.settings = settings

    def start_campaign(self) -> dict[str, int]:
        profile_record = self.session.get(Profile, 1)
        if profile_record is None or not profile_record.mandate_signed_at:
            raise ValueError("Complete the profile and sign the mandate first")
        profile_record.started_at = datetime.now(UTC)
        created = scheduled = 0
        for broker in self.session.scalars(select(Broker).where(Broker.active.is_(True))):
            case = self.session.scalar(select(Case).where(Case.broker_id == broker.id))
            metadata = json.loads(broker.required_fields or "{}")
            confidence = (
                int(metadata.get("default_confidence", 35)) if isinstance(metadata, dict) else 35
            )
            if case is None:
                case = Case(broker_id=broker.id, confidence=confidence)
                self.session.add(case)
                self.session.flush()
                created += 1
            if confidence >= 60 and case.state == "candidate":
                case.state = "queued"
                self.store.enqueue("submit_case", {"case_id": case.id})
                scheduled += 1
        self.session.commit()
        return {"created": created, "scheduled": scheduled}

    def submit_case(self, case_id: int, *, approved_plan: RequestPlan | None = None) -> None:
        if self.store.get_setting("paused", "false") == "true":
            return
        case = self.session.get(Case, case_id)
        if case is None:
            raise ValueError(f"Unknown case {case_id}")
        # A repeated click or duplicate durable job must never submit the same case twice.
        if case.state not in {"queued", "prepared"}:
            return
        from erasure import campaign
        from erasure.knowledge import email_blocker, guide_index
        from erasure.preparation import playbook

        owned = campaign.managed(self, case)
        if not owned:
            # Staging a manual step does not send anything or require email consent.
            route = playbook(self.settings, case.broker.domain)
            guide = guide_index(self.settings).get(case.broker.domain)
            if guide and (problem := email_blocker(guide, case.broker.contact)):
                route = {"route": "manual", "note": problem + " " + " ".join(guide.removal.steps)}
            if route.get("route") in {"form", "manual"}:
                case.state = "needs_action"
                case.next_action_at = None
                self.cancel_case_jobs(case.id)
                self._create_approval(case.id, "next_step", route["note"], {"body": route["note"]})
                self.session.commit()
                return

        # Every live email uses the consent/recipe/dispatch ledger, including old
        # submit_case jobs and brokers not present in a saved campaign snapshot.
        managed = case.broker.connector_type == "email" and (
            self.settings.live_submissions or approved_plan is not None or owned
        )
        if managed:
            if approved_plan is None:
                if not campaign.queue_delivery(self, case):
                    case.last_error = (campaign.consent_problem(self)
                        or campaign.route_problem(self, case.broker)
                        or 'Broker contact needs validation before sending')
                    self.session.commit()
                return
            if campaign.consent_problem(self) or not campaign.eligible(self, case.broker):
                return
            expected = campaign.make_plan(
                self.store, case.broker, case_token(case.id), self.settings
            )
            if approved_plan != expected:
                raise ValueError("Request differs from the approved workflow")

        profile = self.store.get_profile()
        if profile is None:
            raise ValueError("Profile is missing")
        profile["_signature"] = self.store.get_signature()
        sender = GmailClient(self.settings, self.store)
        connector = (
            EmailConnector(sender) if case.broker.connector_type == "email" else BrowserConnector()
        )
        plan = approved_plan or connector.prepare(
            broker=case.broker, profile=profile, case_token=case_token(case.id)
        )
        case.disclosed_fields = json.dumps(plan.disclosed_fields)
        self.store.add_event(
            case.id,
            "request_prepared",
            "Request payload prepared",
            {
                "destination": plan.destination,
                "subject": plan.subject,
                "body": plan.body,
                "disclosed_fields": plan.disclosed_fields,
            },
        )
        case.last_error = ""
        if not self.settings.live_submissions and case.broker.connector_type == "email":
            case.state = "prepared"
            case.last_error = "Live submissions are disabled by ERASURE_LIVE_SUBMISSIONS=false"
            self.session.commit()
            return
        try:
            result = connector.submit(plan)
        except UncertainSubmission:
            case.state = "needs_action"
            case.last_error = "Delivery uncertain. Check Gmail Sent before sending again."
            self._create_approval(
                case.id,
                "delivery_uncertain",
                case.last_error,
                {"destination": plan.destination, "subject": plan.subject},
            )
            self.session.commit()
            return
        case.external_reference = result.external_reference
        if result.outcome == Outcome.SUBMITTED:
            case.attempt_count += 1
            case.state = "submitted"
            case.submitted_at = datetime.now(UTC)
            case.next_action_at = datetime.now(UTC) + timedelta(days=30)
            self.store.add_event(case.id, "submitted", result.summary, result.payload)
            self.store.enqueue("follow_up", {"case_id": case.id}, run_at=case.next_action_at)
        elif result.outcome == Outcome.NEEDS_ACTION:
            case.state = "needs_action"
            self._create_approval(
                case.id,
                "browser_challenge",
                result.summary,
                {
                    "action_url": result.action_url,
                },
            )
        self.session.commit()

    def process_message(self, message: dict[str, str], *, sender_verified: bool = False, linked_case_id: int | None = None, reclassifying: bool = False) -> bool:
        # Never consume classification metadata supplied by an incoming payload.
        message.pop('_interpretation', None)
        token = extract_case_token(message["subject"], message["body"])
        case = self.session.get(Case, linked_case_id) if linked_case_id else None
        if case is None and token is not None:
            try:
                case_id = int(token.removeprefix("ER-"), 16)
            except ValueError:
                case_id = 0
            if case_id:
                case = self.session.get(Case, case_id)
        if case is None and message.get("thread_id"):
            case = self.session.scalar(
                select(Case).where(
                    Case.external_reference == f"gmail-thread:{message['thread_id']}"
                )
            )
        if case is None:
            # Brokers often reply in a fresh thread. Only a unique authenticated
            # official sender may link automatically; vendor domains go to review.
            matches = [
                candidate
                for candidate in self.session.scalars(
                    select(Case).where(Case.submitted_at.is_not(None))
                )
                if assess_sender(
                    message.get("from", ""),
                    message.get("authentication_results", ""),
                    broker_domain=candidate.broker.domain,
                    broker_contact=candidate.broker.contact,
                ).trusted
            ]
            if len(matches) != 1:
                return False
            case = matches[0]
        classification = classify_reply(message["subject"], message["body"])
        message["_case_id"] = case.id
        trust = assess_sender(
            message.get("from", ""),
            message.get("authentication_results", ""),
            broker_domain=case.broker.domain,
            broker_contact=case.broker.contact,
            bounce=classification.kind == ReplyKind.BOUNCED,
        )
        interpretation = {}
        interpretation_started = datetime.now(UTC)
        if case.state not in {'removed', 'not_found'}:
            classification, interpretation = interpret(self, case.id, message)
        if interpretation:
            # The person may act while the external classifier is responding.
            self.session.refresh(case)
            if has_later_user_action(self, case.id, interpretation_started):
                mark_applied(self, interpretation)
                return True
        if reclassifying and interpretation.get('source') not in {'jev', 'jev_uncertain', 'chatgpt', 'chatgpt_uncertain'}:
            return True
        if interpretation:
            message['_interpretation'] = {k: v for k, v in interpretation.items() if k != '_cache_key'}
        if interpretation.get('source') in {'jev', 'jev_uncertain', 'chatgpt', 'chatgpt_uncertain'}:
            self.store.add_event(case.id, 'reply_reclassified' if reclassifying else 'reply_interpreted',
                f'AI interpreted broker reply: {classification.kind.value}',
                {**message['_interpretation'], 'message_id': message.get('message_id', '')})
        if reclassifying and interpretation.get('source') in {'jev_uncertain', 'chatgpt_uncertain'}:
            # An uncertain second opinion must not disturb an existing workflow.
            mark_applied(self, interpretation)
            return True
        if interpretation.get('source') in {'jev', 'chatgpt'}:
            self._supersede_message_actions(case, message, classification.kind,
                                            trusted=sender_verified or trust.trusted)
        if not sender_verified and not trust.trusted:
            previous_state = case.state
            actionable = (classification.kind.value in ACTIONABLE_REPLY_KINDS
                if interpretation.get('source') in {'jev', 'chatgpt'} else actionable_reply(message['body']))
            if case.state not in {"done", "removed", "not_found"} and actionable:
                case.state = "needs_action"
            if not reclassifying:
                self.store.add_event(case.id, "reply_held", "Reply held for sender review",
                    {"message_id": message.get("message_id", ""), "reason": trust.reason})
            if case.state in {'done', 'removed', 'not_found'}:
                mark_applied(self, interpretation)
                return True
            # A routine interpretation can remove bookkeeping, never establish
            # deletion or trust an unverified sender. Keep the original mail.
            if interpretation.get('source') in {'jev', 'chatgpt'} and classification.kind in {
                    ReplyKind.CONFIRMATION, ReplyKind.INFORMATIONAL}:
                mark_applied(self, interpretation)
                self.session.commit()
                return True
            payload = {"message": message, "proposed_kind": classification.kind.value,
                       "reason": trust.reason, "previous_state": previous_state}
            existing = next((a for a in self.session.scalars(select(Approval).where(
                Approval.case_id == case.id, Approval.kind == 'unverified_sender',
                Approval.status == 'pending')) if self._action_matches_message(a, message)), None)
            if existing:
                old_payload = self.store.vault.decrypt(existing.encrypted_payload)
                payload['previous_state'] = old_payload.get('previous_state', previous_state)
                existing.encrypted_payload = self.store.vault.encrypt(payload)
            else:
                self._create_approval(case.id, 'unverified_sender',
                    'Review a reply from an unverified sender', payload)
            self.session.commit()
            mark_applied(self, interpretation)
            return True
        if not reclassifying:
            self.store.add_event(case.id, "reply_received", f"Reply classified as {classification.kind}",
                {**message, "sender_trust": "manually approved" if sender_verified else trust.reason})
        if case.state in {"removed", "not_found"}:
            # A delayed acknowledgement must not undo a recorded completion.
            return True
        if case.state == "done":
            # Continue logging mail, but only authenticated outcomes can upgrade
            # user completion. Delayed form replies must not reopen the task.
            if classification.kind in {ReplyKind.COMPLETED, ReplyKind.NOT_FOUND}:
                case.state = (
                    "removed" if classification.kind == ReplyKind.COMPLETED else "not_found"
                )
                case.completed_at = datetime.now(UTC)
                self.close_obsolete_actions(case)
                self.session.commit()
            mark_applied(self, interpretation)
            return True
        if classification.kind == ReplyKind.BOUNCED:
            case.state = "delivery_failed"
            case.last_error = "Gmail reported that the request could not be delivered"
            self._create_approval(
                case.id,
                "delivery_failure",
                "Request email was not delivered; validate a replacement broker contact",
                message,
            )
        elif classification.kind == ReplyKind.FORM_REQUIRED:
            case.state = "needs_action"
            self.cancel_case_jobs(case.id)
            case.next_action_at = None
            form_url = reviewed_form(self.settings, case.broker.domain) or request_form_url(case.broker, message["body"])
            self._create_approval(
                case.id,
                "form_required",
                "Submit the broker’s privacy form",
                {**message, "action_url": form_url},
            )
        elif classification.kind == ReplyKind.COMPLETED:
            self._complete(case, "removed")
        elif classification.kind == ReplyKind.NOT_FOUND:
            self._complete(case, "not_found")
        elif classification.kind == ReplyKind.INFORMATION_REQUESTED:
            case.state = "needs_action"
            self.cancel_case_jobs(case.id)
            case.next_action_at = None
            self._create_approval(case.id, "information_requested",
                                  "Review the reply prepared with the requested information", message)
        elif classification.kind == ReplyKind.IDENTITY_REQUESTED:
            case.state = "needs_action"
            self._create_approval(
                case.id, "identity_proof", "Broker requested identity proof", message
            )
        elif classification.kind == ReplyKind.REJECTED:
            case.state = "rejected"
            self._create_approval(
                case.id,
                "complaint",
                "Review drafted escalation for rejected request",
                {"draft": self._complaint_draft(case, message), "reply": message},
            )
        elif classification.kind == ReplyKind.EMAIL_VERIFICATION:
            self.require_email_confirmation(case, message)
        elif classification.kind == ReplyKind.ACTION_REQUIRED:
            case.state = 'needs_action'
            self.cancel_case_jobs(case.id)
            case.next_action_at = None
            self._create_approval(case.id, 'next_step', 'Follow the broker’s instructions', message)
        elif classification.kind == ReplyKind.CONFIRMATION:
            # An automated receipt is not evidence that an outstanding form,
            # identity check or failed delivery has been resolved.
            pending_action = any(needs_person(a, self.store.vault.decrypt(a.encrypted_payload) if a.encrypted_payload else {})
                for a in self.session.scalars(select(Approval).where(Approval.case_id == case.id, Approval.status == 'pending')))
            if case.state in {"submitted", "processing"} and not pending_action:
                case.state = "processing"
                followups = list(self.session.scalars(select(Job).where(
                    Job.kind == "follow_up", Job.status.in_(["pending", "running"]))))
                has_followup = any(self.store.vault.decrypt(job.encrypted_payload).get("case_id")
                                   == case.id for job in followups)
                if not has_followup:
                    case.next_action_at = case.next_action_at or (
                        datetime.now(UTC) + timedelta(days=30))
                    self.store.enqueue("follow_up", {"case_id": case.id}, run_at=case.next_action_at)
        # Unknown wording and ticket closures stay in the conversation. They do
        # not establish deletion, authorize a reply, or invent a human task.
        self.session.commit()
        mark_applied(self, interpretation)
        return True

    def _action_matches_message(self, action, message):
        payload = self.store.vault.decrypt(action.encrypted_payload) if action.encrypted_payload else {}
        old = payload.get('message', payload.get('reply', payload))
        return bool((message.get('id') and old.get('id') == message['id']) or (
            not old.get('id') and old.get('subject') == message.get('subject')
            and old.get('body') == message.get('body') and bool(old.get('body'))))

    def _supersede_message_actions(self, case, message, kind, *, trusted):
        """Replace only this message's old interpretation, not unrelated real tasks."""
        routine = kind in {ReplyKind.CONFIRMATION, ReplyKind.INFORMATIONAL}
        if not trusted and not routine:
            return
        replaced = False
        for action in self.session.scalars(select(Approval).where(
            Approval.case_id == case.id, Approval.status == 'pending')):
            if self._action_matches_message(action, message) and action.kind in {'ambiguous_reply', 'unverified_sender', 'form_required',
                    'confirmation_link', 'information_requested', 'identity_proof', 'next_step', 'complaint'}:
                action.status = 'superseded'
                action.resolved_at = datetime.now(UTC)
                replaced = True
        self.session.flush()
        if replaced and routine and case.state == 'needs_action':
            pending = self.session.scalars(select(Approval).where(
                Approval.case_id == case.id, Approval.status == 'pending'))
            if not any(needs_person(a, self.store.vault.decrypt(a.encrypted_payload) if a.encrypted_payload else {}) for a in pending):
                case.state = 'processing' if trusted and kind == ReplyKind.CONFIRMATION else 'submitted'
                self.ensure_follow_up(case)

    def require_email_confirmation(self, case: Case, message: dict) -> None:
        """Generic HTTP success cannot prove verification. Keep it a clear step.

        A future automatic connector must verify the specific broker's outcome,
        not just visit the first same-domain URL and accept an HTTP 200.
        """
        if case.state in {"done", "removed", "not_found"}:
            return
        case.state = "needs_action"
        self.cancel_case_jobs(case.id)
        case.next_action_at = None
        pending = self.session.scalar(select(Approval).where(
            Approval.case_id == case.id, Approval.kind == "confirmation_link",
            Approval.status == "pending"))
        payload = {**message, "action_url": self._safe_confirmation_url(
            case.broker.domain, message.get("body", "")) or ""}
        if pending is None:
            self._create_approval(case.id, "confirmation_link",
                                  "Confirm your request with the broker", payload)
        else:
            # Reissued verification links can replace expired ones. Keep one task.
            pending.encrypted_payload = self.store.vault.encrypt(payload)
            pending.expires_at = None
        self.session.commit()

    def _complete(self, case: Case, state: str) -> None:
        case.state = state
        case.completed_at = datetime.now(UTC)
        self.close_obsolete_actions(case)
        self.cancel_case_jobs(case.id)
        case.next_action_at = datetime.now(UTC) + timedelta(days=case.broker.cadence_days)
        self.store.enqueue("recheck_case", {"case_id": case.id}, run_at=case.next_action_at)

    def close_obsolete_actions(self, case: Case) -> None:
        if case.state not in {"done", "removed", "not_found"}:
            return
        for action in self.session.scalars(
            select(Approval).where(Approval.case_id == case.id, Approval.status == "pending")
        ):
            action.status = "superseded"
            action.resolved_at = datetime.now(UTC)

    def cancel_case_jobs(self, case_id: int) -> None:
        for job in self.session.scalars(select(Job).where(Job.status == "pending")):
            if job.kind in {"follow_up", "submit_case", "recheck_case", "follow_confirmation"}:
                if self.store.vault.decrypt(job.encrypted_payload).get("case_id") == case_id:
                    job.status = "cancelled"

    def send_reply(self, case_id: int, destination: str, body: str) -> str:
        if re.search(r"\[ADD\b[^\]]*\]", body):
            raise ValueError("Complete or remove the draft’s [ADD …] placeholders before sending")
        if (
            not self.settings.live_submissions
            or self.store.get_setting("paused", "false") == "true"
        ):
            raise ValueError("Sending is disabled or paused")
        case = self.session.get(Case, case_id)
        if case is None or not case.submitted_at:
            raise ValueError("Send the original request first")
        for action in self.session.scalars(select(Approval).where(
            Approval.case_id == case_id, Approval.status == 'pending')):
            payload = self.store.vault.decrypt(action.encrypted_payload) if action.encrypted_payload else {}
            if email_only_identity(action, payload):
                raise ValueError('Handle this identity or authorization request directly in your email. The app does not support it yet.')
        if (
            not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", destination)
            or not body.strip()
            or len(body) > 20000
        ):
            raise ValueError("Provide a valid recipient and a message under 20,000 characters")
        subject = f"Re: Privacy Request [{case_token(case.id)}]"
        reference = GmailClient(self.settings, self.store).send(
            RequestPlan(
                channel="email",
                destination=destination,
                subject=subject,
                body=body.strip(),
                disclosed_fields=(),
            )
        )
        self.store.add_event(
            case.id,
            "reply_sent",
            "Follow-up email sent",
            {
                "destination": destination,
                "subject": subject,
                "body": body,
                "gmail_reference": reference,
            },
        )
        if case.state not in {"done", "removed", "not_found"}:
            self.cancel_case_jobs(case.id)
            case.state = "processing"
            case.last_error = ""
            case.next_action_at = datetime.now(UTC) + timedelta(days=30)
            self.store.enqueue("follow_up", {"case_id": case.id}, run_at=case.next_action_at)
        for approval in self.session.scalars(
            select(Approval).where(
                Approval.case_id == case.id,
                Approval.kind.in_(["ambiguous_reply", "next_step", "information_requested"]),
                Approval.status == "pending",
            )
        ):
            approval.status = "approved"
            approval.resolved_at = datetime.now(UTC)
        self.session.commit()
        return reference

    def _create_approval(self, case_id: int, kind: str, summary: str, payload: dict) -> Approval:
        approval = Approval(
            case_id=case_id,
            kind=kind,
            summary=summary,
            encrypted_payload=self.store.vault.encrypt(payload),
            expires_at=None,
        )
        self.session.add(approval)
        self.session.flush()
        if needs_person(approval, payload):
            self.store.enqueue("send_alert", {"approval_id": approval.id})
        return approval

    def follow_up(self, case_id: int) -> None:
        if self.store.get_setting("paused", "false") == "true":
            return
        case = self.session.get(Case, case_id)
        if case is None or case.state in TERMINAL_STATES or case.state == "needs_action":
            return
        if case.attempt_count >= 2:
            case.state = "escalation_ready"
            self._create_approval(
                case.id,
                "complaint",
                "Broker did not answer after two requests; review the complaint draft",
                {"draft": self._complaint_draft(case, None)},
            )
        else:
            case.state = "prepared"
            self.store.enqueue("submit_case", {"case_id": case.id})
        self.session.commit()

    def ensure_follow_up(self, case):
        jobs = self.session.scalars(select(Job).where(Job.kind == 'follow_up', Job.status.in_(['pending', 'running'])))
        if any(self.store.vault.decrypt(job.encrypted_payload).get('case_id') == case.id for job in jobs):
            return
        case.next_action_at = case.next_action_at or datetime.now(UTC) + timedelta(days=30)
        self.store.enqueue('follow_up', {'case_id': case.id}, run_at=case.next_action_at)

    @staticmethod
    def _safe_confirmation_url(domain: str, body: str) -> str | None:
        domain = domain.lower().strip(". ")
        if not domain:
            return None
        candidates = set()
        for url in re.findall(r"https://[^\s<>\"]+", new_reply_text(body)):
            url = url.rstrip(".,);]")
            try:
                parsed = urlsplit(url)
                hostname = parsed.hostname or ""
                if parsed.username or parsed.password or parsed.port not in {None, 443}:
                    continue
            except ValueError:
                continue
            if not (hostname == domain or hostname.endswith(f".{domain}")):
                continue
            if re.search(r"(?:^|[/_-])(?:confirm|verify|verification|confirmation)(?:$|[/_.-])",
                         parsed.path, re.I):
                candidates.add(url)
        return next(iter(candidates)) if len(candidates) == 1 else None

    @staticmethod
    def _complaint_draft(case: Case, reply: dict[str, str] | None) -> str:
        reply_note = reply.get("body", "")[:1000] if reply else "No substantive response received."
        return (
            f"Draft complaint concerning {case.broker.name}\n\n"
            f"A personal-data deletion and objection request was submitted on {case.submitted_at}. "
            f"The request clearly identified the requester as an EU/EEA resident and did not claim "
            f"California residency. Attempts recorded: {case.attempt_count}.\n\n"
            f"Broker response or status: {reply_note}\n\n"
            "Please review the broker's GDPR territorial scope and all evidence before filing this "
            "draft with the competent data-protection authority."
        )

    def recheck_case(self, case_id: int) -> None:
        if self.store.get_setting("paused", "false") == "true":
            return
        case = self.session.get(Case, case_id)
        if case is None or case.state == "done":
            return
        case.state = "queued"
        case.next_action_at = datetime.now(UTC)
        self.store.add_event(case.id, "recheck_due", "Scheduled recurrence check is due")
        # Private databases receive a fresh minimal request. Public sites pause at the safe browser boundary.
        self.store.enqueue("submit_case", {"case_id": case.id})
        self.session.commit()

    def dashboard_counts(self) -> dict[str, int]:
        counts = dict(
            self.session.execute(select(Case.state, func.count()).group_by(Case.state)).all()
        )
        counts["brokers"] = self.session.scalar(select(func.count()).select_from(Broker)) or 0
        counts["actions"] = (
            self.session.scalar(
                select(func.count()).select_from(Approval).where(Approval.status == "pending")
            )
            or 0
        )
        return counts
