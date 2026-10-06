from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, or_, select
from sqlalchemy.orm import Session

from erasure.crypto import Vault
from erasure.models import AppSetting, Event, Job, Profile


class Store:
    def __init__(self, session: Session, vault: Vault):
        self.session = session
        self.vault = vault

    def get_profile(self) -> dict[str, Any] | None:
        profile = self.session.get(Profile, 1)
        return self.vault.decrypt(profile.encrypted_data) if profile else None

    def get_signature(self) -> str | None:
        profile = self.session.get(Profile, 1)
        if profile is None or not profile.encrypted_signature:
            return None
        return str(self.vault.decrypt(profile.encrypted_signature)["signature"])

    def save_profile(self, data: dict[str, Any], signature: str | None = None) -> Profile:
        profile = self.session.get(Profile, 1)
        if profile is None:
            profile = Profile(id=1, encrypted_data=self.vault.encrypt(data))
            self.session.add(profile)
        else:
            profile.encrypted_data = self.vault.encrypt(data)
        if signature is not None:
            profile.encrypted_signature = self.vault.encrypt({"signature": signature})
            profile.signature_version = (profile.signature_version or 0) + 1
            profile.mandate_signed_at = datetime.now(UTC)
        self.session.commit()
        return profile

    def get_setting(self, key: str, default: Any = None) -> Any:
        setting = self.session.get(AppSetting, key)
        if setting is None:
            return default
        return self.vault.decrypt(setting.value) if setting.encrypted else setting.value

    def set_setting(self, key: str, value: Any, *, encrypted: bool = False) -> None:
        setting = self.session.get(AppSetting, key)
        stored = self.vault.encrypt(value) if encrypted else str(value)
        if setting is None:
            setting = AppSetting(key=key, value=stored, encrypted=encrypted)
            self.session.add(setting)
        else:
            setting.value = stored
            setting.encrypted = encrypted
        self.session.commit()

    def add_event(
        self,
        case_id: int,
        kind: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> Event:
        event = Event(
            case_id=case_id,
            kind=kind,
            summary=summary,
            encrypted_payload=self.vault.encrypt(payload) if payload is not None else None,
        )
        self.session.add(event)
        self.session.commit()
        return event

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        run_at: datetime | None = None,
        max_attempts: int = 5,
    ) -> Job:
        job = Job(
            kind=kind,
            encrypted_payload=self.vault.encrypt(payload),
            run_at=run_at or datetime.now(UTC),
            max_attempts=max_attempts,
        )
        self.session.add(job)
        self.session.commit()
        return job

    def enqueue_many(
        self,
        kind: str,
        payloads: list[dict[str, Any]],
        *,
        run_at: datetime | None = None,
        max_attempts: int = 5,
    ) -> list[Job]:
        """Persist a group of same-kind jobs in one transaction."""
        jobs = [
            Job(
                kind=kind,
                encrypted_payload=self.vault.encrypt(payload),
                run_at=run_at or datetime.now(UTC),
                max_attempts=max_attempts,
            )
            for payload in payloads
        ]
        self.session.add_all(jobs)
        self.session.commit()
        return jobs

    def enqueue_if_missing(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        run_at: datetime | None = None,
        max_attempts: int = 5,
    ) -> Job | None:
        """Enqueue only when no pending job of this kind already exists."""
        existing = self.session.scalar(
            select(Job.id).where(Job.kind == kind, Job.status == "pending").limit(1)
        )
        if existing is not None:
            return None
        return self.enqueue(kind, payload, run_at=run_at, max_attempts=max_attempts)

    def claim_job(self, *, lease_seconds: int = 120) -> tuple[Job, dict[str, Any]] | None:
        now = datetime.now(UTC)
        job = self.session.scalar(
            select(Job)
            .where(
                Job.run_at <= now,
                or_(Job.status == "pending", and_(Job.status == "running", Job.lease_until < now)),
            )
            # Read accumulated replies before sending overdue follow-ups.
            .order_by(case((Job.kind == 'poll_gmail', 0), else_=1), Job.run_at, Job.id)
            .limit(1)
        )
        if job is None:
            return None
        # Compare-and-swap prevents concurrent workers from claiming the same job.
        from sqlalchemy import update

        claimed = self.session.execute(
            update(Job)
            .where(
                Job.id == job.id,
                Job.run_at <= now,
                or_(Job.status == "pending", and_(Job.status == "running", Job.lease_until < now)),
            )
            .values(
                status="running",
                lease_until=now + timedelta(seconds=lease_seconds),
                attempts=Job.attempts + 1,
            ),
            execution_options={"synchronize_session": False},
        ).rowcount
        self.session.commit()
        if not claimed:
            return None
        self.session.refresh(job)
        return job, self.vault.decrypt(job.encrypted_payload)

    def finish_job(self, job: Job) -> None:
        job.status = "done"
        job.lease_until = None
        self.session.commit()

    def fail_job(self, job: Job, error: str) -> None:
        job.last_error = error[:1000]
        job.lease_until = None
        if job.attempts >= job.max_attempts:
            job.status = "failed"
        else:
            job.status = "pending"
            job.run_at = datetime.now(UTC) + timedelta(minutes=min(2**job.attempts, 60))
        self.session.commit()
