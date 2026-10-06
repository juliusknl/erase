from __future__ import annotations

import base64
import json
from email.message import EmailMessage

import httpx
import pytest

from erasure.config import Settings
from erasure.connectors.base import RequestPlan
from erasure.gmail import GmailClient, GmailError, UncertainSubmission
from erasure.store import Store


def test_refresh_keeps_verified_setup_mailbox(db, vault):
    from erasure import setup_flow
    store = Store(db, vault)
    store.set_setting('gmail_token', {'access_token': 'old', 'refresh_token': 'refresh'}, encrypted=True)
    setup_flow.remember_mailbox(store, 'requests@example.test')
    client = GmailClient(Settings(_env_file=None), store, client=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={'access_token': 'new'}))))
    client._refresh()
    assert setup_flow.mailbox(store) == 'requests@example.test'
    assert store.get_setting('gmail_token')['access_token'] == 'new'  # noqa: S105 - synthetic token


def test_send_blocks_changed_profile_mailbox_before_http(db, vault):
    from erasure import setup_flow
    from erasure.gmail import GmailPreflightError
    store = Store(db, vault)
    store.set_setting('gmail_token', {'access_token': 'token'}, encrypted=True)
    setup_flow.remember_mailbox(store, 'original@example.test')
    store.save_profile({'email': 'changed@example.test'})
    client = GmailClient(Settings(_env_file=None), store, client=httpx.Client(transport=httpx.MockTransport(
        lambda req: pytest.fail('A mismatched identity must not send HTTP'))))
    with pytest.raises(GmailPreflightError):
        client.send(RequestPlan(channel='email', destination='privacy@example.test',
                                subject='Synthetic', body='Synthetic', disclosed_fields=()))
    assert 'request mailbox' in store.get_setting('gmail_error')


@pytest.mark.parametrize('body', [b'not json', b'{}', b'[]'])
def test_success_without_delivery_receipt_is_uncertain_and_not_retried(db, vault, body):
    store = Store(db, vault)
    store.set_setting('gmail_token', {'access_token': 'token'}, encrypted=True)
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(200, content=body)
    client = GmailClient(Settings(_env_file=None), store, client=httpx.Client(transport=httpx.MockTransport(response)))
    with pytest.raises(UncertainSubmission):
        client.send(RequestPlan(channel='email', destination='privacy@example.test',
                                subject='Synthetic', body='Synthetic', disclosed_fields=()))
    assert len(calls) == 1


def test_send_timeout_does_not_retry(db, vault):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("response lost", request=request)

    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "fake"}, encrypted=True)
    gmail = GmailClient(
        Settings(), store, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(UncertainSubmission):
        gmail.send(
            RequestPlan(
                channel="email",
                destination="privacy@example.test",
                subject="test",
                body="test",
                disclosed_fields=(),
            )
        )
    assert len(calls) == 1


def test_html_only_reply_preserves_text_links_and_omits_styles(db, vault):
    mail = EmailMessage()
    mail["Subject"] = "Privacy reply"
    mail.set_content(
        '<style>hidden</style><p>Please use <a href="https://broker.test/form">our form</a>.</p>',
        subtype="html",
    )
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "fake"}, encrypted=True)
    gmail = GmailClient(
        Settings(),
        store,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"raw": raw}))
        ),
    )
    body = gmail.read_message("one")["body"]
    assert "Please use" in body and "https://broker.test/form" in body
    assert "hidden" not in body and "<p>" not in body


@pytest.mark.parametrize("quote", ["<blockquote>{}</blockquote>", '<div class="gmail_quote">{}</div>'])
def test_html_history_cannot_supply_a_new_deletion_confirmation(db, vault, quote):
    from erasure.replies import ReplyKind, classify_reply

    mail = EmailMessage()
    mail.set_content("<p>We are reviewing your request.</p>" +
                     quote.format("<p>Your data has been deleted.</p>"), subtype="html")
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "fake"}, encrypted=True)
    gmail = GmailClient(Settings(), store, client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"raw": raw}))))
    body = gmail.read_message("quoted")["body"]
    assert "Your data has been deleted" in body  # History remains visible.
    assert classify_reply("Re: Privacy request", body).kind != ReplyKind.COMPLETED


def test_revoked_refresh_token_sets_actionable_error(db, vault):
    store = Store(db, vault)
    store.set_setting(
        "gmail_token", {"access_token": "fake", "refresh_token": "fake"}, encrypted=True
    )
    gmail = GmailClient(
        Settings(),
        store,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(400, json={"error": "invalid_grant"})
            )
        ),
    )
    with pytest.raises(GmailError):
        gmail._refresh()
    assert "Reconnect Gmail" in store.get_setting("gmail_error")


def test_multipart_reply_uses_full_html_not_plain_preheader(db, vault):
    mail = EmailMessage()
    mail["Subject"] = "Your request — completed"
    mail.set_content("Your request")
    mail.add_alternative(
        "<style>hidden</style><p>Your data has been deleted.</p>\n\n\n\n"
        '<p>Details: <a href="https://broker.test/result">view result</a></p>',
        subtype="html",
    )
    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "fake"}, encrypted=True)
    gmail = GmailClient(
        Settings(),
        store,
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"raw": raw}))
        ),
    )
    result = gmail.read_message("multipart")
    assert result["subject"] == "Your request — completed"
    assert "Your data has been deleted." in result["body"]
    assert "https://broker.test/result" in result["body"]
    assert "hidden" not in result["body"]
    assert "\n\n\n" not in result["body"]


def test_recent_mail_paginates_and_does_not_require_unread(db, vault):
    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "fake"}, encrypted=True)

    def handler(request):
        assert "is:unread" not in request.url.params["q"]
        assert request.url.params["includeSpamTrash"] == "true"
        if request.url.params.get("pageToken") == "next":
            return httpx.Response(200, json={"messages": [{"id": "two"}]})
        return httpx.Response(200, json={"messages": [{"id": "one"}], "nextPageToken": "next"})

    gmail = GmailClient(
        Settings(), store, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert gmail.list_recent() == ["one", "two"]


def test_gmail_authorization_and_send(db, vault) -> None:  # type: ignore[no-untyped-def]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/messages/send"):
            payload = json.loads(request.content)
            raw = payload["raw"] + "=" * (-len(payload["raw"]) % 4)
            message = base64.urlsafe_b64decode(raw).decode()
            assert "To: privacy@broker.test" in message
            assert "ER-000001" in message
            return httpx.Response(200, json={"id": "gmail-123", "threadId": "thread-123"})
        return httpx.Response(404)

    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "token"}, encrypted=True)
    settings = Settings(
        google_client_id="client", google_client_secret="secret", base_url="http://127.0.0.1:8787"
    )
    client = GmailClient(
        settings, store, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    url = client.authorization_url()
    assert "accounts.google.com" in url
    assert store.get_setting("gmail_oauth_state")
    message_id = client.send(
        RequestPlan(
            channel="email",
            destination="privacy@broker.test",
            subject="Request [ER-000001]",
            body="Delete my data",
            disclosed_fields=("full_name",),
        )
    )
    assert message_id == "gmail-thread:thread-123"
    assert requests[-1].headers["authorization"] == "Bearer token"


def test_gmail_reads_plain_text_message(db, vault) -> None:  # type: ignore[no-untyped-def]
    raw_message = (
        base64.urlsafe_b64encode(
            b"From: privacy@broker.test\r\n"
            b"Subject: Re: ER-000001\r\n"
            b"Authentication-Results: mx.google.com; dmarc=pass header.from=broker.test\r\n"
            b"\r\nDeletion complete"
        )
        .decode()
        .rstrip("=")
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"raw": raw_message, "threadId": "thread-123"})

    store = Store(db, vault)
    store.set_setting("gmail_token", {"access_token": "token"}, encrypted=True)
    client = GmailClient(
        Settings(), store, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    message = client.read_message("abc")
    assert message["subject"] == "Re: ER-000001"
    assert message["body"] == "Deletion complete"
    assert message["thread_id"] == "thread-123"
    assert "dmarc=pass" in message["authentication_results"]


def test_gmail_refreshes_expired_token_when_listing_inbox(db, vault) -> None:  # type: ignore[no-untyped-def]
    access_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fresh-token"})
        access_tokens.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer expired-token":
            return httpx.Response(401)
        return httpx.Response(200, json={"messages": [{"id": "message-1"}]})

    store = Store(db, vault)
    store.set_setting(
        "gmail_token",
        {"access_token": "expired-token", "refresh_token": "refresh-token"},
        encrypted=True,
    )
    client = GmailClient(
        Settings(google_client_id="client", google_client_secret="secret"),
        store,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_unread() == ["message-1"]
    assert access_tokens == ["Bearer expired-token", "Bearer fresh-token"]
    assert store.get_setting("gmail_token")["refresh_token"] == "refresh-token"  # noqa: S105
