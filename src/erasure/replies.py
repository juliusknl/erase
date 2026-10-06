from __future__ import annotations

import json
import re
from dataclasses import dataclass
from email.utils import parseaddr
from enum import StrEnum
from urllib.parse import urlsplit


class ReplyKind(StrEnum):
    FORM_REQUIRED = "form_required"
    BOUNCED = "bounced"
    CONFIRMATION = "confirmation"
    EMAIL_VERIFICATION = "email_verification"
    COMPLETED = "completed"
    NOT_FOUND = "not_found"
    IDENTITY_REQUESTED = "identity_requested"
    INFORMATION_REQUESTED = "information_requested"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"
    INFORMATIONAL = "informational"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True)
class ClassifiedReply:
    kind: ReplyKind
    confidence: int
    reason: str


@dataclass(frozen=True)
class SenderTrust:
    trusted: bool
    reason: str


PATTERNS: list[tuple[ReplyKind, int, tuple[str, ...]]] = [
    (
        ReplyKind.FORM_REQUIRED,
        90,
        (
            r"please (?:use|complete|submit|fill (?:in|out)) (?:our|the|this) (?:privacy request (?:center|form)|(?:online |removal |opt-out )?form)",
            r"does not respond to initial access, correction, deletion, or opt-out at this email address",
            r"please submit your request via (?:one of )?our designated methods?\b.{0,120}\bform\b",
            r"data subject privacy request\b.{0,100}\b(?:see or delete|delete)\b.{0,80}\bplease visit\b",
        ),
    ),
    (
        ReplyKind.BOUNCED,
        99,
        (
            r"delivery status notification \(failure\)",
            r"(?:message|email) (?:was not|wasn't|could not be) delivered",
            r"address not found",
            r"recipient address rejected",
            r"undeliverable",
        ),
    ),
    (
        ReplyKind.COMPLETED,
        95,
        (r"(?:has|have) been (?:deleted|removed)", r"deletion (?:is )?complete",
         r"we have (?:deleted|removed) your (?:personal )?(?:data|information|records?|profile)\b"),
    ),
    (
        ReplyKind.NOT_FOUND,
        90,
        (
            r"no (?:matching )?(?:record|data)",
            r"unable to (?:locate|find)",
            r"\bwe (?:hold|have) no personal data\b",
            r"\bdid not find any (?:matching )?profiles\b",
            r"\bdoes not contain any details associated with\b",
        ),
    ),
    (
        ReplyKind.IDENTITY_REQUESTED,
        90,
        (r"proof of identity", r"government[- ]issued id", r"verify your identity"),
    ),
    (
        ReplyKind.REJECTED,
        85,
        (r"(?:deny|denied|decline) your request", r"not (?:required|obligated) to"),
    ),
    (
        ReplyKind.EMAIL_VERIFICATION,
        90,
        (
            r"(?:^|[.!?]\s+|\bplease\s+|\bkindly\s+)(?:confirm|verify) your (?:e-?mail(?: address)?|(?:privacy |deletion |removal )?request)\b",
            r"\b(?:click|use|follow)\b[^.!?]{0,100}\b(?:to confirm|to verify) your (?:e-?mail|request)\b",
            r"\b(?:bestätigen|verifizieren) sie (?:bitte )?ihre (?:e-mail(?:-adresse)?|anfrage)\b",
        ),
    ),
    (
        ReplyKind.CONFIRMATION,
        80,
        (
            r"received your request",
            r"request (?:has been )?submitted",
            r"thank you for submitting your (?:privacy |deletion |removal )?request",
            r"(?:we are|we're) (?:processing|reviewing) your request",
            r"your request (?:is being|will be) processed",
            r"we (?:acknowledge receipt of|will process) your request",
            r"(?:have )?added your information to the removal queue",
            r"submitted your request for processing",
            r"bestätigen wir ihnen den eingang ihrer datenschutzanfrage",
        ),
    ),
    (
        ReplyKind.INFORMATIONAL, 80,
        (r"your (?:support )?ticket\b.{0,250}\b(?:has been|is) (?:resolved|closed)",),
    ),
]


def new_reply_text(body: str) -> str:
    """Use new message text, not quoted requests, old outcomes or boilerplate."""
    body = re.split(
        r"(?im)^\s*(?:On .+wrote:|Am .+schrieb.*:|From:|Von:|"
        r"_{3,}\s*From:|-{2,}\s*(?:Original Message|Forwarded message|Ursprüngliche Nachricht|Message d'origine)|"
        r"[^\n]{0,200}\bnapisał\(a\):\s*$|>).*|"
        r"(?i:confidentiality notice|this message contains information which is confidential|this message contains confidential information)",
        body,
        maxsplit=1,
    )[0]
    # Some helpdesks flatten our original request without quote headers.
    body = re.split(r"(?im)\n\s*Hello [^\n]{1,160} Privacy Team,\s*\n", body, maxsplit=1)[0]
    return body.strip()


def removal_reply_text(body: str) -> str:
    """Ignore an explicitly separate access-only appendix, not the removal branch.

    The complete original remains stored and displayed in the conversation.
    Do not strip ordinary verification instructions or infer a deletion outcome.
    """
    current = new_reply_text(body)
    parts = re.split(r"(?im)^\s*If you(?:'ve| have) (?:sent|submitted) a right to know request,\s*"
                     r"please read and do the following:\s*$", current, maxsplit=1)
    if len(parts) > 1 and re.search(r'\b(?:delete|deletion|erasure|opt-out)\b', parts[0], re.I):
        return parts[0].strip()
    return current


def classify_reply(subject: str, body: str) -> ClassifiedReply:
    current = removal_reply_text(body)
    current_text = re.sub(r"\s+", " ", current).lower()
    text = re.sub(r"\s+", " ", f"{subject}\n{current}").lower()
    # Subjects are frequently inherited from a request or an earlier outcome.
    # Questions and conditional/future statements are not completion evidence.
    statements = re.split(r"[.!?\n]+", current.lower())
    outcome_statements = []
    if "?" not in current:
        outcome_statements = [
            sentence for sentence in statements
            if not re.search(
                r"\b(?:if|when|once|whether|will|would|could|should)\b|"
                r"please (?:confirm|ensure)|\b(?:not yet|cannot confirm|unable to confirm)\b",
                sentence,
            )
        ]
    outcome_text = ' '.join(outcome_statements)
    # A cancelled request or mailing-list opt-out is not database deletion.
    deletion_text = ' '.join(sentence for sentence in outcome_statements
                            if not re.search(r'\b(?:queue|ticket|mailing list|marketing list)\b|'
                                             r'request.{0,60}(?:deleted|removed)', sentence))
    for kind, confidence, patterns in PATTERNS:
        if kind in {ReplyKind.CONFIRMATION, ReplyKind.INFORMATIONAL} and explicit_next_step(current):
            return ClassifiedReply(ReplyKind.ACTION_REQUIRED, 80, "Broker gives an explicit next step")
        if kind == ReplyKind.NOT_FOUND and requests_information(current):
            if re.search(r"proof of identity|government[- ]issued id|verify your identity", current_text):
                return ClassifiedReply(ReplyKind.IDENTITY_REQUESTED, 90,
                                       "Broker requests identity verification before continuing")
            return ClassifiedReply(ReplyKind.INFORMATION_REQUESTED, 90,
                                   "Broker asks for matching details before the request can continue")
        for pattern in patterns:
            if kind in {ReplyKind.COMPLETED, ReplyKind.NOT_FOUND}:
                candidate = outcome_text
                if kind == ReplyKind.COMPLETED:
                    candidate = deletion_text
            elif kind in {ReplyKind.EMAIL_VERIFICATION, ReplyKind.FORM_REQUIRED}:
                candidate = current_text
            elif kind in {ReplyKind.CONFIRMATION, ReplyKind.INFORMATIONAL}:
                candidate = current_text
            else:
                candidate = text
            if re.search(pattern, candidate):
                return ClassifiedReply(kind, confidence, f"Matched {kind.value} language")
    return ClassifiedReply(ReplyKind.AMBIGUOUS, 20, "No high-confidence response pattern matched")


def required_reply_text(body: str) -> str:
    """Remove optional support/error-correction sentences, not privacy instructions."""
    text = new_reply_text(body)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return ' '.join(s for s in sentences if not re.match(
        r"\s*(?:if (?:not\b|you (?:have (?:any |further |additional )*(?:questions|comments)|are not (?:the )?(?:named|intended) recipient))|"
        r"if you believe (?:this (?:is|response)|there are (?:any )?other)\b|"
        r"should you have (?:any )?questions|for (?:more information|questions)\b)", s, re.I))


def explicit_next_step(body: str) -> bool:
    """A concrete instruction, not unfamiliar wording or an optional support footer."""
    required = required_reply_text(body)
    return bool(requests_information(required) or re.search(
        r"\bplease\s+(?:do\s+|kindly\s+)?(?:use|complete|submit|fill|confirm|verify|provide|send|log in|log into|sign in|visit|contact|reply|respond|click|follow|select|choose)\b|"
        r"\byou (?:must|need to|are required to)\b|\b(?:to proceed|to continue),?\s+(?:please\s+)?(?:provide|complete|visit|log|confirm|verify)\b",
        required, re.I))


def actionable_reply(body: str, subject: str = '') -> bool:
    if not body.strip():
        return False
    kind = classify_reply(subject, body).kind
    return kind in {ReplyKind.FORM_REQUIRED, ReplyKind.EMAIL_VERIFICATION,
                    ReplyKind.IDENTITY_REQUESTED, ReplyKind.INFORMATION_REQUESTED,
                    ReplyKind.ACTION_REQUIRED, ReplyKind.BOUNCED, ReplyKind.REJECTED}


def requests_information(body: str) -> bool:
    """Explicit requests for identifiers, not incidental mentions in policies/history."""
    text = re.sub(r"\s+", " ", required_reply_text(body)).lower()
    asks = re.search(
        r"\b(?:please|kindly|could you)\s+(?:kindly\s+)?(?:provide|send|reply|respond)|"
        r"\bwe (?:need|require|must know)\b|\bfollowing information\b|\bbitten wir sie\b|"
        r"\bbenötigen wir\b|\bpourriez-vous nous confirmer\b", text)
    fields = re.search(
        r"\b(?:full name|legal name|email|e-mail|phone|telephone|country|city|state/province|"
        r"postal address|postadresse|postanschrift|linkedin|rocketreach|employer|company name|maid|idfa|"
        r"mobile ad(?:vertising)? (?:ids?|identifiers?)|aaids?|telefonnummer|proof of identity|government[- ]issued id)\b", text)
    return bool(asks and fields)


def matching_mailbox_required(body: str) -> bool:
    text = re.sub(r'\s+', ' ', new_reply_text(body)).lower()
    return bool(re.search(
        r'send (?:us )?(?:a new |a )?(?:email(?:/ticket)?|deletion request|request) from (?:each|the|your) (?:email|business|work)|'
        r'send us your request via either email.{0,100}business email', text))


def extract_case_token(subject: str, body: str) -> str | None:
    match = re.search(r"\bER-[A-Z0-9]{6,16}\b", f"{subject}\n{body}", re.IGNORECASE)
    return match.group(0).upper() if match else None


def request_form_url(broker, body: str) -> str:
    """Expose a reviewed form or an explicit same-domain removal link, never visit it."""
    metadata = json.loads(broker.required_fields or "{}")
    configured = metadata.get("request_form", "") if isinstance(metadata, dict) else ""
    candidates = [configured] if configured else re.findall(r"https://[^\s<>]+", body)
    for candidate in candidates:
        url = candidate.rstrip(".,)")
        try:
            parsed = urlsplit(url)
        except ValueError:
            # Email is untrusted input, including malformed IPv6/host syntax.
            continue
        if parsed.scheme != "https" or parsed.username or parsed.password:
            continue
        if not _aligned(parsed.hostname or "", broker.domain):
            continue
        if configured or re.search(
            r"remove|opt-out|optout|privacy-request|data-request|do-not-sell|preferences", parsed.path, re.I
        ):
            return url
    return ""


def _aligned(actual: str, expected: str) -> bool:
    actual = actual.lower().strip(". ")
    expected = expected.lower().strip(". ")
    return bool(actual and expected) and (actual == expected or actual.endswith(f".{expected}"))


def _authenticated_domain(sender_domain: str, authentication_results: str) -> bool:
    # Continuation lines belong to the same header; do not discard its verdicts.
    authentication_results = re.sub(r"\r?\n[ \t]+", " ", authentication_results)
    results = "\n".join(
        line
        for line in authentication_results.lower().splitlines()
        if re.match(r"^\s*mx\.google\.com\s*;", line)
    )
    dmarc_domains = re.findall(
        r"\bdmarc=pass\b[^;]*header\.from=([a-z0-9.-]+)",
        results,
    )
    if any(_aligned(domain, sender_domain) for domain in dmarc_domains):
        return True
    for mechanism, field in (("dkim", r"header\.(?:i|d)"), ("spf", r"smtp\.mailfrom")):
        matches = re.findall(
            rf"\b{mechanism}=pass\b[^;]*{field}=@?([a-z0-9.-]+)",
            results,
        )
        if any(_aligned(domain, sender_domain) for domain in matches):
            return True
    return False


def assess_sender(
    from_header: str,
    authentication_results: str,
    *,
    broker_domain: str,
    broker_contact: str,
    bounce: bool = False,
) -> SenderTrust:
    address = parseaddr(from_header)[1].lower()
    if "@" not in address:
        return SenderTrust(False, "Reply has no valid sender address")
    local_part, sender_domain = address.rsplit("@", 1)
    if not _authenticated_domain(sender_domain, authentication_results):
        return SenderTrust(False, "Gmail did not provide aligned SPF, DKIM, or DMARC evidence")
    if bounce:
        trusted_daemon = local_part in {"mailer-daemon", "postmaster"}
        return SenderTrust(
            trusted_daemon,
            "Authenticated delivery-status sender"
            if trusted_daemon
            else "Bounce language came from a non-system sender",
        )
    contact_address = parseaddr(broker_contact)[1].lower()
    contact_domain = contact_address.rsplit("@", 1)[1] if "@" in contact_address else ""
    expected_domains = {domain for domain in (broker_domain, contact_domain) if domain}
    if not any(_aligned(sender_domain, expected) for expected in expected_domains):
        return SenderTrust(False, "Authenticated sender is not aligned with the broker domain")
    return SenderTrust(True, "Authenticated sender is aligned with the broker domain")
