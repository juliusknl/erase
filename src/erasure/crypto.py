from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox


def digest(value: Any) -> str:
    """Stable fingerprint shared by consent and mailbox identity checks."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class VaultError(ValueError):
    """Raised when encrypted data cannot be safely read."""


class Vault:
    def __init__(self, encoded_key: str):
        if not encoded_key:
            raise VaultError("ERASURE_MASTER_KEY is not configured")
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as exc:  # pragma: no cover - defensive boundary
            raise VaultError("ERASURE_MASTER_KEY is not valid base64") from exc
        if len(key) != SecretBox.KEY_SIZE:
            raise VaultError("ERASURE_MASTER_KEY must decode to 32 bytes")
        self._box = SecretBox(key)

    def encrypt(self, value: Any) -> str:
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return self.encrypt_bytes(payload)

    def decrypt(self, token: str) -> Any:
        try:
            payload = self.decrypt_bytes(token)
            return json.loads(payload)
        except (CryptoError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise VaultError("Encrypted value failed authentication") from exc

    def encrypt_bytes(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(self._box.encrypt(payload)).decode()

    def decrypt_bytes(self, token: str) -> bytes:
        try:
            return self._box.decrypt(base64.urlsafe_b64decode(token.encode()))
        except (CryptoError, ValueError, TypeError) as exc:
            raise VaultError("Encrypted value failed authentication") from exc


def generate_master_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(SecretBox.KEY_SIZE)).decode()


def generate_session_secret() -> str:
    return secrets.token_urlsafe(48)


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return (
        "scrypt$16384$8$1$"
        + base64.urlsafe_b64encode(salt).decode()
        + "$"
        + base64.urlsafe_b64encode(digest).decode()
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode(),
            salt=base64.urlsafe_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False
