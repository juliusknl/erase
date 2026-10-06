from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from erasure.crypto import verify_password


@dataclass(frozen=True)
class SessionData:
    issued_at: int
    nonce: str


class LoginThrottle:
    """Small in-memory throttle for the localhost password boundary."""

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_failures < 1 or window_seconds < 1:
            raise ValueError("Login throttle limits must be positive")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, identity: str, now: float) -> deque[float]:
        failures = self._failures.setdefault(identity, deque())
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def retry_after(self, identity: str) -> int:
        with self._lock:
            now = self.clock()
            failures = self._recent(identity, now)
            if len(failures) < self.max_failures:
                if not failures:
                    self._failures.pop(identity, None)
                return 0
            return max(1, ceil(self.window_seconds - (now - failures[0])))

    def record_failure(self, identity: str) -> None:
        with self._lock:
            now = self.clock()
            self._recent(identity, now).append(now)

    def record_success(self, identity: str) -> None:
        with self._lock:
            self._failures.pop(identity, None)


class SessionManager:
    def __init__(self, secret: str, password_hash: str, *, lifetime_hours: int = 12):
        self.secret = secret.encode()
        self.password_hash = password_hash
        self.lifetime_seconds = lifetime_hours * 3600

    def authenticate(self, password: str) -> bool:
        return bool(self.password_hash) and verify_password(password, self.password_hash)

    def create(self) -> str:
        payload = json.dumps(
            {"iat": int(time.time()), "nonce": secrets.token_urlsafe(18)},
            separators=(",", ":"),
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(self.secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def verify(self, token: str | None) -> SessionData | None:
        if not token or "." not in token or not self.secret:
            return None
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(self.secret, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded))
            issued_at = int(data["iat"])
            if issued_at > time.time() + 60 or time.time() - issued_at > self.lifetime_seconds:
                return None
            return SessionData(issued_at=issued_at, nonce=str(data["nonce"]))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def csrf(self, session_token: str) -> str:
        return hmac.new(self.secret, f"csrf:{session_token}".encode(), hashlib.sha256).hexdigest()

    def verify_csrf(self, session_token: str, value: str) -> bool:
        return hmac.compare_digest(self.csrf(session_token), value)
