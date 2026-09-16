from __future__ import annotations

import socket
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from scout.nextgen.intelligence_mcp import IntelligenceMcpUnavailable
from scout.nextgen.intelligence_mcp_http import probe_intelligence_mcp_http_health


@pytest.fixture
def socket_path():
    path = Path('/tmp') / f'scout-health-{uuid4().hex}.sock'
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture
def sockets(monkeypatch):
    original = socket.socket
    created = []

    class TrackedSocket(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(socket, 'socket', TrackedSocket)
    return created


@pytest.mark.parametrize('failure', ['absent', 'refused'])
def test_repeated_failed_health_connections_release_sockets(socket_path, sockets, failure):
    owner = None
    if failure == 'refused':
        owner = socket.socket(socket.AF_UNIX)
        owner.bind(str(socket_path))
    try:
        for _ in range(3):
            with pytest.raises(IntelligenceMcpUnavailable):
                probe_intelligence_mcp_http_health(socket_path)
        requests = [s for s in sockets if s is not owner]
        assert requests and all(s.fileno() == -1 for s in requests)
    finally:
        if owner is not None:
            owner.close()


@contextmanager
def serve_once(path, status, body, *, delayed=False):
    release = threading.Event()
    errors = []
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        listener.listen(1)
        listener.settimeout(5)

        def serve():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(5)
                    request = connection.recv(4096)
                    assert request.startswith(b'GET /health HTTP/1.1\r\n')
                    if delayed:
                        assert release.wait(5)
                        return
                    response = f'HTTP/1.1 {status} Fixture\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body
                    connection.sendall(response)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            yield
        finally:
            release.set()
            thread.join(timeout=6)
            assert not thread.is_alive()
            assert not errors


@pytest.mark.parametrize('status, body', [(200, b'{"status":"ok"}'), (503, b'{"status":"unavailable"}'), (200, b'not-json')])
def test_health_recovers_and_preserves_status_and_body(socket_path, sockets, status, body):
    with pytest.raises(IntelligenceMcpUnavailable):
        probe_intelligence_mcp_http_health(socket_path)
    with serve_once(socket_path, status, body):
        assert probe_intelligence_mcp_http_health(socket_path) == (status, body)
    assert sockets and all(s.fileno() == -1 for s in sockets)


def test_health_timeout_releases_connection(socket_path, sockets):
    with serve_once(socket_path, 200, b'', delayed=True):
        with pytest.raises(IntelligenceMcpUnavailable):
            probe_intelligence_mcp_http_health(socket_path, timeout_seconds=0.1)
    assert sockets and all(s.fileno() == -1 for s in sockets)


def test_health_rejects_relative_socket_without_connection(sockets):
    with pytest.raises(ValueError, match='absolute'):
        probe_intelligence_mcp_http_health(Path('relative.sock'))
    assert sockets == []
