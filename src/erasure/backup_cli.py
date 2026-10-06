from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from erasure.config import get_settings
from erasure.crypto import Vault
from erasure.database_lock import database_lock

MAGIC = b"PERSONAL-ERASURE-BACKUP-V1\n"


def sqlite_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Backup currently supports SQLite only")
    return Path(database_url.removeprefix(prefix))


def create_backup(source: Path, destination: Path, vault: Vault) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with database_lock(source), tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / "snapshot.db"
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as source_db, closing(sqlite3.connect(snapshot)) as target_db:
            source_db.backup(target_db)
        encrypted = MAGIC + vault.encrypt_bytes(snapshot.read_bytes()).encode()
        # Never replace another backup (or the source database) by accident.
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(encrypted)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            destination.unlink()  # Only the file exclusively created above.
            raise


def restore_backup(source: Path, destination: Path, vault: Vault) -> None:
    payload = source.read_bytes()
    if not payload.startswith(MAGIC):
        raise ValueError("Unrecognized backup format")
    plaintext = vault.decrypt_bytes(payload[len(MAGIC) :].decode())
    if not plaintext.startswith(b"SQLite format 3\x00"):
        raise ValueError("Decrypted backup is not a SQLite database")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or source.resolve() == destination.resolve():
        raise ValueError('Restore destination must be a database file, not the backup or a symbolic link')
    with database_lock(destination, exclusive=True), tempfile.TemporaryDirectory() as directory:
        # Validate before touching the destination. A valid header alone proves nothing.
        snapshot = Path(directory) / 'restore.db'
        snapshot.write_bytes(plaintext)
        snapshot.chmod(0o600)
        with closing(sqlite3.connect(snapshot)) as restored:
            try:
                if restored.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise ValueError('Backup database failed its integrity check')
            except sqlite3.DatabaseError:
                raise ValueError('Backup database failed its integrity check') from None
            # Also refuse WAL/journal remnants from older, non-cooperating app versions.
            if any(Path(str(destination) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
                raise RuntimeError('Database has an active or unfinished journal. Quit erase and recover it before restoring; no files were replaced.')
            created = not destination.exists()
            if created:
                descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
            try:
                with closing(sqlite3.connect(destination, timeout=0)) as target:
                    def progress(status, remaining, total):
                        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                            raise RuntimeError('Database is in use. Quit erase before restoring.')
                    # SQLite applies the restore transactionally, without replacing an
                    # inode underneath another connection or leaving stale WAL contents.
                    restored.backup(target, pages=128, progress=progress, sleep=0)
            except BaseException:
                if created:
                    destination.unlink()
                raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or restore an encrypted local backup")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("destination", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("--confirm-overwrite", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    vault = Vault(settings.master_key)
    database = sqlite_path(settings.database_url)
    if args.command == "create":
        create_backup(database, args.destination, vault)
        print(f"Encrypted backup created at {args.destination}")  # noqa: T201
    elif not args.confirm_overwrite:
        raise SystemExit("Restore requires --confirm-overwrite. Quit erase and stop its worker first.")
    else:
        restore_backup(args.source, database, vault)
        print(f"Encrypted backup restored to {database}")  # noqa: T201


if __name__ == "__main__":
    main()
