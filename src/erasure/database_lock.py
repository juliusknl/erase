"""Coordinate app connections and offline database maintenance on macOS/Linux."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def database_lock(database: Path, *, exclusive=False):
    path = database.resolve().with_suffix(database.suffix + '.lock')
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        try:
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Database is in use. Quit erase and stop its worker before restoring.') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
