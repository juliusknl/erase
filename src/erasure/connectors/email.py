from __future__ import annotations

import json

from erasure.connectors.base import ConnectorResult, Outcome, RequestPlan


class EmailConnector:
    def __init__(self, sender) -> None:  # type: ignore[no-untyped-def]
        self.sender = sender

    def prepare(self, *, broker, profile: dict, case_token: str) -> RequestPlan:  # type: ignore[no-untyped-def]
        metadata = json.loads(broker.required_fields or "{}")
        include_postal = not isinstance(metadata, dict) or metadata.get("include_postal", True)
        fields = ["full_name", "email"]
        identity = [f"Full legal name: {profile['full_name']}"]
        if include_postal and profile.get("postal_address"):
            fields.append("postal_address")
            identity.append(f"Current postal address: {profile['postal_address']}")
        other_emails = profile.get("other_emails") or []
        if other_emails:
            fields.append("other_emails")
            identity.append("Email addresses that may be associated with my records:")
            identity.extend(f"- {address}" for address in other_emails)
        body = f"""Hello {broker.name} Privacy Team,

I am requesting that you identify and delete personal data concerning me from your data-broker products and suppress its future sale or sharing where possible.

I reside in the European Economic Area. Where your processing falls within GDPR's territorial scope, please treat this as an erasure and objection request under Articles 17 and 21. Otherwise, please treat it as a direct voluntary deletion and opt-out request. I am not claiming California residency.

Contact email for this request: {profile["email"]}

Information supplied only to locate my existing records:
{chr(10).join(identity)}

Please search every identifier listed above, not only the contact mailbox used to send this request. Please state which identifiers you searched, whether a matching record was found, and when deletion or suppression is complete. If a different identifier or request channel is necessary, please specify it. Do not use this information for any purpose other than processing this request.

Reference: {case_token}

Sincerely,
{profile.get("_signature") or profile.get("full_name", "")}
"""
        return RequestPlan(
            channel="email",
            destination=broker.contact,
            subject=f"Privacy Request: personal data deletion and opt-out [{case_token}]",
            body=body,
            disclosed_fields=tuple(fields),
        )

    def submit(self, plan: RequestPlan) -> ConnectorResult:
        message_id = self.sender.send(plan)
        return ConnectorResult(
            outcome=Outcome.SUBMITTED,
            summary="Deletion request sent by email",
            external_reference=message_id,
        )

    def verify(self, *, broker, profile: dict) -> ConnectorResult:  # type: ignore[no-untyped-def]
        return ConnectorResult(
            outcome=Outcome.NEEDS_ACTION,
            summary="Private database deletion cannot be independently verified",
        )
