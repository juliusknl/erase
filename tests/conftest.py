from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy.orm import Session

from erasure.crypto import Vault, generate_master_key
from erasure.db import create_db_engine
from erasure.models import Base


@pytest.fixture(autouse=True)
def no_external_http_in_tests(monkeypatch):
    """Tests may use local UI servers or mock transports, never real mail/providers."""
    original = httpx.HTTPTransport.handle_request
    async_original = httpx.AsyncHTTPTransport.handle_async_request
    def guarded(transport, request):
        if request.url.host not in {'localhost', '127.0.0.1', '::1'}:
            pytest.fail('A test attempted external HTTP; use an explicit mock transport')
        return original(transport, request)
    async def async_guarded(transport, request):
        if request.url.host not in {'localhost', '127.0.0.1', '::1'}:
            pytest.fail('A test attempted external HTTP; use an explicit mock transport')
        return await async_original(transport, request)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', guarded)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_guarded)


@pytest.fixture
def live_app_server():
    servers = []

    def start(app):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        servers.append((server, thread, sock))
        thread.start()
        for _ in range(100):
            if server.started:
                return f"http://127.0.0.1:{sock.getsockname()[1]}"
            time.sleep(0.02)
        raise AssertionError("Test server did not start")

    yield start
    for server, thread, sock in servers:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.fixture(autouse=True)
def no_live_jev_by_default(monkeypatch):
    # A developer's opted-in .env must never send test messages to a real provider.
    monkeypatch.setenv('ERASURE_JEV_ENABLED', 'false')
    monkeypatch.setenv('TYPESAFE_API_KEY', '')
    # Also protect module-level settings cached before fixtures run. Tests that
    # exercise the runtime replace this class with an explicit test double.
    def no_provider(*args, **kwargs):
        raise AssertionError('Runtime AI tests must provide a mock classifier')
    monkeypatch.setattr('erasure.reply_interpretation.JevClassifier', no_provider)
    monkeypatch.setattr('erasure.reply_assistance.JevClassifier', no_provider)


@pytest.fixture
def master_key() -> str:
    return generate_master_key()


@pytest.fixture
def vault(master_key: str) -> Vault:
    return Vault(master_key)


@pytest.fixture
def db(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()
