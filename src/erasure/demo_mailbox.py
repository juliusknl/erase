"""Local synthetic mail transport. Never opens a network socket."""

import base64
import email
import json
import re
from datetime import UTC, datetime, timedelta
from email import policy
from email.message import EmailMessage

import httpx
from sqlalchemy import select

from erasure.models import AppSetting, Case


class DemoTransport:
    def __init__(self, store):
        self.store = store

    def __call__(self, request):
        path = request.url.path
        if request.url.host == 'oauth2.googleapis.com' and path == '/token' and request.method == 'POST':
            return httpx.Response(200, json={'access_token': 'demo-local-only', 'refresh_token': 'demo-local-only'})
        if request.url.host != 'gmail.googleapis.com':
            return httpx.Response(403, json={'error': 'Demo has no external transport'})
        if path == '/gmail/v1/users/me/profile' and request.method == 'GET':
            return httpx.Response(200, json={'emailAddress': 'requests@example.test'})
        prefix = '/gmail/v1/users/me/messages'
        if path == prefix + '/send' and request.method == 'POST':
            raw = json.loads(request.content)['raw']
            sent = email.message_from_bytes(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)), policy=policy.default)
            match = re.search(r'\bER-([A-Fa-f0-9]{6,16})\b', str(sent.get('Subject', '')))
            case = self.store.session.get(Case, int(match[1], 16)) if match else None
            sequence = int(self.store.get_setting('demo_send_count', '0')) + 1
            self.store.set_setting('demo_send_count', sequence)
            if case:
                token = f'ER-{case.id:06X}'
                self._reply(case, sequence, 'receipt', token, 'We received your request. We are reviewing your request.', 10)
                outcomes = [
                    'Your personal information has been deleted. Deletion is complete.',
                    'We found no matching records for the email addresses you supplied.',
                    f'Please complete our privacy request form: https://{case.broker.domain}/demo-privacy-form',
                    'Please provide your work email address and employer so we can locate your record.',
                    f'Please confirm your email address: https://{case.broker.domain}/demo-confirmation',
                    'Please provide proof of identity. You may ask us about alternative verification methods.',
                ]
                outcome = outcomes[0] if case.attempt_count else outcomes[(sequence - 1) % len(outcomes)]
                self._reply(case, sequence, 'outcome', token, outcome, 35)
            return httpx.Response(200, json={'id': f'demo-sent-{sequence}', 'threadId': f'demo-case-{case.id if case else sequence}'})
        if path == prefix and request.method == 'GET':
            now = datetime.now(UTC).isoformat()
            messages = [self.store.get_setting(key) for key in self.store.session.scalars(
                select(AppSetting.key).where(AppSetting.key.like('demo_mail:%')).order_by(AppSetting.key))]
            messages.sort(key=lambda message: (message['available_at'], message['id']))
            return httpx.Response(200, json={'messages': [{'id': m['id']} for m in reversed(messages) if m['available_at'] <= now]})
        if path.startswith(prefix + '/') and request.method == 'GET':
            record = self.store.get_setting('demo_mail:' + path.removeprefix(prefix + '/'))
            if record and record['available_at'] <= datetime.now(UTC).isoformat():
                return httpx.Response(200, json=record)
            return httpx.Response(404, json={'error': 'Demo message not available'})
        return httpx.Response(403, json={'error': 'Unsupported demo operation'})

    def _reply(self, case, sequence, stage, token, body, delay):
        mid = f'demo-{sequence:06d}-{stage}'
        message = EmailMessage()
        message['From'] = f'privacy@{case.broker.domain}'
        message['Subject'] = f'Simulated reply: privacy request [{token}]'
        message['Message-ID'] = f'<{mid}@demo.invalid>'
        message['Authentication-Results'] = f'mx.google.com; dmarc=pass header.from={case.broker.domain}'
        message.set_content(body + '\n\nSIMULATION: generated locally for testing; not an actual reply from this broker.')
        self.store.set_setting('demo_mail:' + mid, {
            'id': mid, 'threadId': f'demo-case-{case.id}',
            'raw': base64.urlsafe_b64encode(message.as_bytes()).decode(),
            'available_at': (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(),
        }, encrypted=True)
