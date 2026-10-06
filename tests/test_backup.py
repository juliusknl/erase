from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from erasure.backup_cli import MAGIC, create_backup, restore_backup
from erasure.crypto import VaultError
from erasure.database_lock import database_lock
from erasure.db import create_db_engine


def test_encrypted_backup_round_trip(tmp_path, vault) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("create table secret (value text)")
        connection.execute("insert into secret values (?)", ("private value",))
    backup = tmp_path / "backup.erasurebak"
    create_backup(database, backup, vault)
    assert b"private value" not in backup.read_bytes()

    restored = tmp_path / "restored.db"
    restore_backup(backup, restored, vault)
    with sqlite3.connect(restored) as connection:
        assert connection.execute("select value from secret").fetchone()[0] == "private value"


def test_tampered_backup_is_rejected(tmp_path, vault) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("create table item (value text)")
    backup = tmp_path / "backup.erasurebak"
    create_backup(database, backup, vault)
    payload = backup.read_bytes()
    backup.write_bytes(payload[:-2] + b"AA")
    with pytest.raises(VaultError):
        restore_backup(backup, tmp_path / "restored.db", vault)


def make_backup(tmp_path, vault):
    source, backup = tmp_path / 'source.db', tmp_path / 'snapshot.enc'
    with closing(sqlite3.connect(source)) as db:
        db.execute('CREATE TABLE marker(value TEXT)')
        db.execute("INSERT INTO marker VALUES ('backup contents')")
        db.commit()
    create_backup(source, backup, vault)
    return source, backup


def test_backup_never_overwrites_source_or_existing_backup(tmp_path, vault):
    source, backup = make_backup(tmp_path, vault)
    for destination in (source, backup):
        original = destination.read_bytes()
        with pytest.raises(FileExistsError):
            create_backup(source, destination, vault)
        assert destination.read_bytes() == original


def test_restore_refuses_open_app_pool_then_succeeds_after_shutdown(tmp_path, vault):
    source, backup = make_backup(tmp_path, vault)
    engine = create_db_engine('sqlite:///' + str(source))
    with engine.connect() as db:
        db.exec_driver_sql("UPDATE marker SET value='live contents'")
        db.commit()
    # Even idle pooled connections mean the app is still running.
    with pytest.raises(RuntimeError, match='in use'):
        restore_backup(backup, source, vault)
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT value FROM marker').scalar() == 'live contents'
    engine.dispose()
    restore_backup(backup, source, vault)
    with closing(sqlite3.connect(source)) as db:
        assert db.execute('SELECT value FROM marker').fetchone() == ('backup contents',)


def test_app_cannot_connect_during_restore(tmp_path):
    path = tmp_path / 'target.db'
    engine = create_db_engine('sqlite:///' + str(path))
    with database_lock(path, exclusive=True), pytest.raises(RuntimeError, match='in use'):
        engine.connect()
    with engine.connect() as db:
        assert db.exec_driver_sql('SELECT 1').scalar() == 1
    engine.dispose()


def test_restore_refuses_legacy_wal_database_without_replacing_it(tmp_path, vault):
    _, backup = make_backup(tmp_path, vault)
    target = tmp_path / 'live.db'
    with closing(sqlite3.connect(target)) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA wal_autocheckpoint=0')
        db.execute('CREATE TABLE marker(value TEXT)')
        db.execute("INSERT INTO marker VALUES ('live contents')")
        db.commit()
        with pytest.raises(RuntimeError, match='journal'):
            restore_backup(backup, target, vault)
        assert db.execute('SELECT value FROM marker').fetchone() == ('live contents',)


def test_restore_refuses_busy_legacy_database_without_hanging(tmp_path, vault):
    target, backup = make_backup(tmp_path, vault)
    with closing(sqlite3.connect(target)) as db:
        db.execute('BEGIN EXCLUSIVE')
        with pytest.raises(RuntimeError, match='in use'):
            restore_backup(backup, target, vault)
        db.rollback()
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)


def test_restore_validates_entire_database_before_overwriting(tmp_path, vault):
    target, backup = make_backup(tmp_path, vault)
    before = target.read_bytes()
    backup.write_bytes(MAGIC + vault.encrypt_bytes(b'SQLite format 3\x00' + b'bad' * 100).encode())
    with pytest.raises(ValueError, match='integrity'):
        restore_backup(backup, target, vault)
    assert target.read_bytes() == before


def test_restore_rejects_symlink_and_backup_as_target(tmp_path, vault):
    source, backup = make_backup(tmp_path, vault)
    link = tmp_path / 'alias.db'
    link.symlink_to(source)
    for destination in (link, backup):
        with pytest.raises(ValueError, match='destination'):
            restore_backup(backup, destination, vault)
