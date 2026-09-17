from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scout.nextgen.intelligence_mcp import (
    IntelligenceMcpClientConfig,
    IntelligenceMcpProtocolError,
    IntelligenceMcpStdioClient,
    IntelligenceMcpTimeout,
    IntelligenceMcpUnavailable,
)


SERVER = r'''
import json, signal, sys, time
mode = sys.argv[1]
if mode == 'exit':
    sys.exit(4)
if mode == 'timeout':
    time.sleep(30)
if mode == 'ignore-terminate':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    if mode == 'invalid':
        print('not a protocol response', flush=True)
        time.sleep(30)
    if mode == 'oversize':
        print('x' * 512, flush=True)
        time.sleep(30)
    print(json.dumps({'id': request['id'], 'result': {'serverInfo': {'name': 'fixture'}}}), flush=True)
    print('fixture diagnostic output', file=sys.stderr, flush=True)
    if mode == 'ignore-terminate':
        while True:
            time.sleep(1)
'''


def _client(mode: str, tmp_path: Path) -> IntelligenceMcpStdioClient:
    script = tmp_path / 'stdio_fixture.py'
    script.write_text(SERVER)
    return IntelligenceMcpStdioClient(IntelligenceMcpClientConfig(
        command=(sys.executable, str(script), mode),
        startup_timeout_seconds=0.25 if mode == 'timeout' else 5,
    ))


def _assert_released(process: subprocess.Popen[str], readers: tuple[threading.Thread, ...]) -> None:
    assert process.poll() is not None
    assert all(stream is not None and stream.closed for stream in (process.stdin, process.stdout, process.stderr))
    assert all(not reader.is_alive() for reader in readers)


def _close_fixture_handles(process: subprocess.Popen[str]) -> None:
    # Preserve the assertion failure against the preimage without making the
    # negative proof leak its own fixture descriptors into another test.
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


@pytest.mark.parametrize('mode', ['normal', 'ignore-terminate'])
def test_close_releases_process_streams_and_joins_readers(mode: str, tmp_path: Path) -> None:
    client = _client(mode, tmp_path)
    client.initialize()
    process = client._process
    readers = (client._reader, client._stderr_reader)
    assert process is not None and all(reader is not None for reader in readers)
    try:
        client.close()
        _assert_released(process, readers)
        client.close()
        _assert_released(process, readers)
        if mode == 'ignore-terminate':
            assert process.returncode == -9
    finally:
        _close_fixture_handles(process)


@pytest.mark.parametrize('mode, error', [
    ('exit', IntelligenceMcpUnavailable),
    ('timeout', IntelligenceMcpTimeout),
    ('invalid', IntelligenceMcpProtocolError),
    ('oversize', IntelligenceMcpProtocolError),
])
def test_failed_initialization_still_releases_every_owned_resource(mode, error, monkeypatch, tmp_path: Path) -> None:
    if mode == 'oversize':
        monkeypatch.setattr('scout.nextgen.intelligence_mcp.MAX_RESPONSE_BYTES', 128)
    client = _client(mode, tmp_path)
    with pytest.raises(error):
        client.initialize()
    process = client._process
    readers = (client._reader, client._stderr_reader)
    assert process is not None and all(reader is not None for reader in readers)
    try:
        client.close()
        _assert_released(process, readers)
    finally:
        _close_fixture_handles(process)


def test_closed_client_can_restart_without_reusing_dead_readers(tmp_path: Path) -> None:
    client = _client('normal', tmp_path)
    processes = []
    try:
        for _ in range(3):
            client.initialize()
            process = client._process
            readers = (client._reader, client._stderr_reader)
            assert process is not None and all(reader is not None for reader in readers)
            assert process not in processes
            processes.append(process)
            client.close()
            _assert_released(process, readers)
    finally:
        client.close()
        for process in processes:
            _close_fixture_handles(process)
