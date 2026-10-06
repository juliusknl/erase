from __future__ import annotations

import base64
import email
import re
import secrets
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser
from urllib.parse import urlencode

import httpx

from erasure.config import Settings
from erasure.connectors.base import RequestPlan
from erasure.crypto import digest
from erasure.models import Profile
from erasure.store import Store

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - OAuth endpoint, not a credential
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/gmail.send"


class GmailError(RuntimeError):
    pass


class UncertainSubmission(GmailError):
    """Gmail may have accepted the message; never blindly send it again."""


class GmailPreflightError(GmailError):
    """The send endpoint was never called; reconnecting can safely resume work."""


class _MailText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "tr"}:
            self.parts.append("\n")
        classes = dict(attrs).get("class", "") or ""
        if tag == "blockquote" or "gmail_quote" in classes.split():
            # Preserve history for display while giving the classifier a quote boundary.
            self.parts.append("\n> ")
        if tag == "a" and not self.hidden:
            for key, value in attrs:
                if key == "href" and value and value.startswith("https://"):
                    self.parts.append(f" {value} ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class GmailClient:
    def __init__(self, settings: Settings, store: Store, *, client: httpx.Client | None = None):
        credentials = store.get_setting('gmail_client_config', {})
        self.settings = settings.model_copy(update={
            'google_client_id': credentials['client_id'],
            'google_client_secret': credentials['client_secret'],
        }) if credentials else settings
        self.store = store
        if settings.demo_mode:
            from erasure.demo_mailbox import DemoTransport

            client = httpx.Client(transport=httpx.MockTransport(DemoTransport(store)), trust_env=False)
        self.client = client or httpx.Client(timeout=30)

    @property
    def redirect_uri(self) -> str:
        return f"{self.settings.base_url.rstrip('/')}/gmail/callback"

    def authorization_url(self) -> str:
        if not self.settings.demo_mode and (not self.settings.google_client_id or not self.settings.google_client_secret):
            raise GmailError("Google OAuth client is not configured")
        state = secrets.token_urlsafe(32)
        self.store.set_setting("gmail_oauth_state", state, encrypted=True)
        if self.settings.demo_mode:
            return '/demo/mailbox?setup=true' if self.store.get_setting('gmail_setup_session') else '/demo/mailbox'
        query = urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str, state: str, *, persist: bool = True) -> dict:
        expected = self.store.get_setting("gmail_oauth_state")
        if not expected or not secrets.compare_digest(expected, state):
            raise GmailError("OAuth state did not match")
        response = self.client.post(
            TOKEN_URL,
            data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
        )
        response.raise_for_status()
        token = response.json()
        self.store.set_setting("gmail_oauth_state", "", encrypted=True)
        if persist:
            self.store.set_setting("gmail_token", token, encrypted=True)
            self.store.set_setting("gmail_error", "")
        return token

    def _access_token(self) -> str:
        token = self.store.get_setting("gmail_token")
        if not token:
            raise GmailError("Dedicated Gmail account is not connected")
        if token.get("access_token"):
            return str(token["access_token"])
        raise GmailError("Gmail token has no access token; reconnect the account")

    def mailbox_address(self, *, _retried: bool = False, access_token: str | None = None) -> str:
        """Confirm the actual connected account, without sending or reading messages."""
        response = self.client.get(f'{GMAIL_API}/profile',
            headers={'Authorization': f'Bearer {access_token or self._access_token()}'})
        if response.status_code == 401 and not _retried and access_token is None:
            self._refresh()
            return self.mailbox_address(_retried=True)
        response.raise_for_status()
        address = response.json().get('emailAddress', '')
        if not isinstance(address, str) or '@' not in address or '\n' in address or '\r' in address:
            raise GmailError('Google did not return a mailbox address')
        return address

    def send(self, plan: RequestPlan, *, _retried: bool = False) -> str:
        try:
            self.check_sender_identity()
        except (GmailError, httpx.HTTPError, ValueError) as exc:
            raise GmailPreflightError('Mailbox identity could not be verified before sending') from exc
        message = EmailMessage()
        message["To"] = plan.destination
        message["Subject"] = plan.subject
        message["X-Personal-Erasure-Case"] = plan.subject.rsplit("[", 1)[-1].rstrip("]")
        message.set_content(plan.body)
        for attachment in plan.attachments:
            maintype, _, subtype = attachment.content_type.partition("/")
            message.add_attachment(
                attachment.content,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename,
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        try:
            response = self.client.post(
                f"{GMAIL_API}/messages/send",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                json={"raw": raw},
            )
        except httpx.TransportError as exc:
            raise UncertainSubmission("Check Gmail Sent before retrying this request") from exc
        if response.status_code >= 500:
            raise UncertainSubmission("Gmail returned a server error; check Sent before retrying")
        if response.status_code == 401 and not _retried:
            self._refresh()
            return self.send(plan, _retried=True)
        response.raise_for_status()
        try:
            sent = response.json()
            if isinstance(sent, dict) and sent.get('threadId'):
                return f"gmail-thread:{sent['threadId']}"
            if isinstance(sent, dict) and sent.get('id'):
                return f"gmail-message:{sent['id']}"
        except ValueError:
            pass
        raise UncertainSubmission('Gmail accepted the request but returned no usable receipt; check Sent before retrying')

    def check_sender_identity(self) -> None:
        """Profile edits/reconnections must not silently send from another inbox."""
        profile = self.store.get_profile() or {}
        if not profile.get('email'):
            return
        token = self.store.get_setting('gmail_token')
        saved = self.store.get_setting('setup_mailbox', {})
        if saved.get('token_hash') != digest(token):
            address = self.mailbox_address()
            saved = {'email': address, 'token_hash': digest(self.store.get_setting('gmail_token'))}
            self.store.set_setting('setup_mailbox', saved, encrypted=True)
        if saved.get('email', '').casefold() != profile['email'].casefold():
            self.store.set_setting('gmail_error', 'Connect the request mailbox shown in Profile before sending.')
            raise GmailError('Connected Gmail account does not match the approved request mailbox')

    def _refresh(self) -> None:
        token = self.store.get_setting("gmail_token") or {}
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            self.store.set_setting("gmail_error", "Reconnect Gmail: authorization expired")
            raise GmailError("Gmail authorization expired; reconnect the account")
        response = self.client.post(
            TOKEN_URL,
            data={
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code == 400 and response.json().get("error") == "invalid_grant":
            self.store.set_setting(
                "gmail_error", "Reconnect Gmail: Google expired or revoked access"
            )
            raise GmailError("Gmail authorization expired; reconnect the account")
        response.raise_for_status()
        updated = response.json()
        updated["refresh_token"] = refresh_token
        self.store.set_setting("gmail_token", updated, encrypted=True)
        # Refresh preserves the account. Carry forward only identity evidence
        # bound to the exact old token; never bless an unrelated replacement.
        saved = self.store.get_setting('setup_mailbox', {})
        if saved.get('token_hash') == digest(token):
            self.store.set_setting('setup_mailbox', {**saved, 'token_hash': digest(updated)}, encrypted=True)

    def list_recent(self) -> list[str]:
        """Read and unread incoming mail, including spam, with complete pagination."""
        ids = []
        page = None
        last_sync = self.store.get_setting("gmail_last_sync")
        profile = self.store.session.get(Profile, 1)
        if last_sync:
            since = datetime.fromisoformat(last_sync) - timedelta(days=2)
        elif profile and profile.started_at:
            since = profile.started_at.replace(tzinfo=UTC) - timedelta(days=1)
        else:
            since = datetime.now(UTC) - timedelta(days=30)
        while True:
            params = {
                "q": f"after:{int(since.timestamp())} -in:sent -in:drafts",
                "maxResults": 100,
                "includeSpamTrash": "true",
            }
            if page:
                params["pageToken"] = page
            response = self.client.get(
                f"{GMAIL_API}/messages",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                params=params,
            )
            if response.status_code == 401:
                self._refresh()
                response = self.client.get(
                    f"{GMAIL_API}/messages",
                    headers={"Authorization": f"Bearer {self._access_token()}"},
                    params=params,
                )
            response.raise_for_status()
            data = response.json()
            ids.extend(item["id"] for item in data.get("messages", []))
            page = data.get("nextPageToken")
            if not page:
                return ids

    def list_unread(self, *, _retried: bool = False) -> list[str]:
        response = self.client.get(
            f"{GMAIL_API}/messages",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            params={"q": "is:unread newer_than:30d", "maxResults": 50},
        )
        if response.status_code == 401 and not _retried:
            self._refresh()
            return self.list_unread(_retried=True)
        response.raise_for_status()
        return [item["id"] for item in response.json().get("messages", [])]

    def read_message(self, message_id: str, *, _retried: bool = False) -> dict[str, str]:
        response = self.client.get(
            f"{GMAIL_API}/messages/{message_id}",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            params={"format": "raw"},
        )
        if response.status_code == 401 and not _retried:
            self._refresh()
            return self.read_message(message_id, _retried=True)
        response.raise_for_status()
        payload = response.json()
        raw = payload["raw"]
        raw += "=" * (-len(raw) % 4)
        parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=policy.default)
        plain, html = [], []
        for part in parsed.walk():
            if part.is_multipart() or part.get_filename():
                continue
            content = part.get_payload(decode=True) or b""
            try:
                decoded = content.decode(part.get_content_charset() or "utf-8", errors="replace")
            except LookupError:
                decoded = content.decode("utf-8", errors="replace")
            if part.get_content_type() == "text/plain":
                plain.append(decoded)
            elif part.get_content_type() == "text/html":
                parser = _MailText()
                parser.feed(decoded)
                html.append("".join(parser.parts))
        # Some privacy platforms supply only a preheader in text/plain.
        # Read the full HTML alternative as safe text; never execute email HTML.
        body = "\n".join(html if any(s.strip() for s in html) else plain)
        body = body.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
        body = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in body.splitlines())
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        return {
            "id": message_id,
            "thread_id": str(payload.get("threadId", "")),
            "from": str(parsed.get("From", "")),
            "subject": str(parsed.get("Subject", "")),
            "body": body,
            "message_id": str(parsed.get("Message-ID", message_id)),
            "date": str(parsed.get("Date", "")),
            "authentication_results": "\n".join(
                value
                for value in parsed.get_all("Authentication-Results", [])
                if value.lower().lstrip().startswith("mx.google.com;")
            ),
        }

    def message_thread_id(self, message_id: str, *, _retried: bool = False) -> str:
        """Resolve a Gmail message ID to its stable conversation thread ID."""
        response = self.client.get(
            f"{GMAIL_API}/messages/{message_id}",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            params={"format": "metadata", "metadataHeaders": []},
        )
        if response.status_code == 401 and not _retried:
            self._refresh()
            return self.message_thread_id(message_id, _retried=True)
        response.raise_for_status()
        thread_id = response.json().get("threadId")
        if not thread_id:
            raise GmailError("Gmail message has no thread ID")
        return str(thread_id)

    def mark_read(self, message_id: str, *, _retried: bool = False) -> None:
        response = self.client.post(
            f"{GMAIL_API}/messages/{message_id}/modify",
            headers={"Authorization": f"Bearer {self._access_token()}"},
            json={"removeLabelIds": ["UNREAD"]},
        )
        if response.status_code == 401 and not _retried:
            self._refresh()
            return self.mark_read(message_id, _retried=True)
        response.raise_for_status()
