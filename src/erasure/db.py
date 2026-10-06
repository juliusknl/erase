from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from erasure.config import Settings, get_settings
from erasure.database_lock import database_lock
from erasure.models import Base


def create_db_engine(database_url: str) -> Engine:
    kwargs = (
        {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def hold_database_lock(dbapi_connection, connection_record) -> None:
            database = engine.url.database
            if database and database != ':memory:':
                lock = database_lock(Path(database))
                lock.__enter__()
                connection_record.info['maintenance_lock'] = lock

        @event.listens_for(engine, "close")
        def release_database_lock(dbapi_connection, connection_record) -> None:
            lock = connection_record.info.pop('maintenance_lock', None)
            if lock is not None:
                lock.__exit__(None, None, None)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


settings: Settings = get_settings()
engine = create_db_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(db_engine: Engine | None = None) -> None:
    Base.metadata.create_all(db_engine or engine)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
