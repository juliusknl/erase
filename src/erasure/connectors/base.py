from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Outcome(StrEnum):
    SUBMITTED = "submitted"
    NEEDS_ACTION = "needs_action"
    REMOVED = "removed"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    RETRY = "retry"


@dataclass(frozen=True)
class Attachment:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class RequestPlan:
    channel: str
    destination: str
    subject: str
    body: str
    disclosed_fields: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class ConnectorResult:
    outcome: Outcome
    summary: str
    external_reference: str = ""
    action_url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


class BrokerConnector(Protocol):
    def prepare(self, *, broker: Any, profile: dict[str, Any], case_token: str) -> RequestPlan: ...

    def submit(self, plan: RequestPlan) -> ConnectorResult: ...

    def verify(self, *, broker: Any, profile: dict[str, Any]) -> ConnectorResult: ...
