from __future__ import annotations

import getpass

from erasure.crypto import generate_master_key, generate_session_secret, hash_password


def main() -> None:
    password = getpass.getpass("Dashboard password (12+ characters): ")
    confirmation = getpass.getpass("Repeat password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match")
    print(f"ERASURE_MASTER_KEY={generate_master_key()}")  # noqa: T201
    print(f"ERASURE_PASSWORD_HASH={hash_password(password)}")  # noqa: T201
    print(f"ERASURE_SESSION_SECRET={generate_session_secret()}")  # noqa: T201


if __name__ == "__main__":
    main()
