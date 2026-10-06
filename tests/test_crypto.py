from __future__ import annotations

import pytest

from erasure.crypto import VaultError, hash_password, verify_password


def test_vault_round_trip_and_authentication(vault) -> None:  # type: ignore[no-untyped-def]
    token = vault.encrypt({"name": "Sensitive Person", "items": [1, 2]})
    assert "Sensitive Person" not in token
    assert vault.decrypt(token) == {"items": [1, 2], "name": "Sensitive Person"}
    with pytest.raises(VaultError):
        vault.decrypt(token[:-2] + "AA")


def test_password_hash() -> None:
    encoded = hash_password("a sufficiently long passphrase")
    assert verify_password("a sufficiently long passphrase", encoded)
    assert not verify_password("wrong password", encoded)
    assert "sufficiently" not in encoded
