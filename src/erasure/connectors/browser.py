from __future__ import annotations

from erasure.connectors.base import ConnectorResult, Outcome, RequestPlan


class BrowserConnector:
    """Safe boundary for broker flows that require a real browser session.

    Unknown pages are never filled speculatively. A broker-specific, tested adapter can
    subclass this connector; otherwise the case becomes a resumable user action.
    """

    def prepare(self, *, broker, profile: dict, case_token: str) -> RequestPlan:  # type: ignore[no-untyped-def]
        return RequestPlan(
            channel="browser",
            destination=broker.contact,
            subject=f"Interactive deletion request [{case_token}]",
            body="",
            disclosed_fields=(),
        )

    def submit(self, plan: RequestPlan) -> ConnectorResult:
        return ConnectorResult(
            outcome=Outcome.NEEDS_ACTION,
            summary="Broker requires an interactive browser flow",
            action_url=plan.destination,
        )

    def verify(self, *, broker, profile: dict) -> ConnectorResult:  # type: ignore[no-untyped-def]
        return ConnectorResult(
            outcome=Outcome.NEEDS_ACTION,
            summary="Public record needs a broker-specific verification adapter",
            action_url=broker.contact,
        )
