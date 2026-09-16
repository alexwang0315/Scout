"""Bounded stdio transport tests: no real SSH, .env, sockets or hardware."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tools import hardware_monitor_proxy as proxy
from tools import hardware_monitor_ssh as ssh

STATUS = "/api/v1/hardware-monitor/status"
PREFIX = "/admin/dashboard/scout-monitor"
POPEN = subprocess.Popen


def wire(payload, code=200, *, chunked=False):
    body = json.dumps(payload).encode()
    framing = b"Transfer-Encoding: chunked" if chunked else f"Content-Length: {len(body)}".encode()
    if chunked:
        body = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    return f"HTTP/1.1 {code} Test\r\nContent-Type: application/json\r\n".encode() + framing + b"\r\n\r\n" + body


def fake_process(monkeypatch, scripts):
    children, calls = [], []

    def launch(command, **kwargs):
        calls.append((command, kwargs))
        assert command == ssh.SSH_COMMAND
        assert kwargs["shell"] is False
        # Real OS pipes exercise EOF, blocking, cleanup and concurrent stderr.
        process = POPEN([sys.executable, "-c", scripts[len(children)]], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(ssh.subprocess, "Popen", launch)
    return children, calls


def reply_script(raw, *, noisy=False):
    return (
        "import sys, os, select\n"
        "request = bytearray()\n"
        "while not request.endswith(b'\\r\\n\\r\\n'):\n"
        "    request.extend(os.read(0, 1))\n"
        # Detect the regression: stdin EOF before the response was delivered.
        "if select.select([0], [], [], 0)[0]: sys.exit(71)\n"
        + ("sys.stderr.buffer.write(b'x' * 150000); sys.stderr.flush()\n" if noisy else "")
        + f"sys.stdout.buffer.write({raw!r}); sys.stdout.flush()\n"
    )


@pytest.mark.parametrize("code,chunked", [(200, False), (503, False), (200, True), (503, True)])
def test_stdio_keeps_stdin_open_drains_both_pipes_and_preserves_503(monkeypatch, code, chunked):
    payload = {"status": "stale" if code == 503 else "warning", "data": {"status": "ok", "power": None}}
    children, _ = fake_process(monkeypatch, [reply_script(wire(payload, code, chunked=chunked), noisy=True)])
    status, decoded = proxy.fetch_hardware_monitor_via_ssh(STATUS, {})
    assert (status, decoded) == (code, payload)
    assert children[0].returncode == 0
    assert all(pipe.closed for pipe in (children[0].stdin, children[0].stdout, children[0].stderr))


def test_each_request_reconnects_after_ssh_failure_without_local_forward(monkeypatch):
    payload = {"status": "warning", "freshness": {"state": "fresh"}, "data": {"power": None}}
    children, calls = fake_process(monkeypatch, [
        "import sys; sys.stderr.write('private-error-do-not-publish'); sys.exit(255)",
        reply_script(wire(payload)),
        reply_script(wire(payload)),
    ])
    monkeypatch.setattr(proxy.sys, "platform", "darwin")
    app = FastAPI(); app.include_router(proxy.create_hardware_monitor_proxy_router())
    with TestClient(app) as client, patch.object(proxy, "fetch_hardware_monitor_json") as local_http:
        failed = client.get(PREFIX + STATUS)
        recovered = client.get(PREFIX + STATUS)
        refreshed = client.get(PREFIX + STATUS)
    assert failed.status_code == 503 and failed.json()["data"] is None
    assert failed.json()["connection"]["error_code"] == "ssh_unavailable"
    assert "private-error" not in failed.text
    assert "不需要開啟 Mac 9151" in failed.text
    assert "每 60 秒自動重試" in failed.text
    assert recovered.status_code == refreshed.status_code == 200
    assert recovered.json() == refreshed.json() == payload
    assert recovered.headers["x-scout-monitor-transport"] == "ssh"
    local_http.assert_not_called()
    assert len({child.pid for child in children}) == len(calls) == 3
    assert all(child.poll() is not None for child in children)
    assert not ({"-L", "-R", "-D", "-N"} & set(ssh.SSH_COMMAND))
    assert ssh.SSH_COMMAND[-3:] == ("-W", "127.0.0.1:9151", "scout")
    assert {"StrictHostKeyChecking=yes", "BatchMode=yes", "ClearAllForwardings=yes",
            "ControlPath=none", "PermitLocalCommand=no", "RemoteCommand=none"} <= set(ssh.SSH_COMMAND)


def test_scout_api_connection_refusal_is_not_misreported_as_ssh_down(monkeypatch):
    fake_process(monkeypatch, ["import sys; sys.stderr.write('channel 0: open failed: connect failed: Connection refused'); sys.exit(255)"])
    with pytest.raises(proxy.HardwareMonitorUpstreamError) as error:
        proxy.fetch_hardware_monitor_via_ssh(STATUS, {})
    assert error.value.code == "scout_api_unavailable"


def test_timeout_kills_and_reaps_owned_child_and_next_call_works(monkeypatch):
    children, _ = fake_process(monkeypatch, ["import time; time.sleep(30)", reply_script(wire({"data": None}))])
    start = time.monotonic()
    with pytest.raises(ssh.HardwareMonitorSSHError, match="ssh_timeout"):
        ssh.read_scout_http(STATUS, timeout=0.2)
    assert time.monotonic() - start < 3
    assert children[0].poll() is not None
    assert ssh.read_scout_http(STATUS, timeout=3)[0] == 200
    assert all(pipe.closed for child in children for pipe in (child.stdin, child.stdout, child.stderr))


def test_response_limit_reaps_child(monkeypatch):
    children, _ = fake_process(monkeypatch, ["import sys,time; sys.stdout.buffer.write(b'x' * 2400000); sys.stdout.flush(); time.sleep(30)"])
    with pytest.raises(ssh.HardwareMonitorSSHError, match="response_too_large"):
        ssh.read_scout_http(STATUS, timeout=3)
    assert children[0].poll() is not None


@pytest.mark.parametrize("raw", [
    b"not HTTP", b"HTTP/1.1 200 OK\r\n\r\n{}",
    b"HTTP/1.1 302 Found\r\nLocation: http://example.com\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 50\r\n\r\n{}",
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 9999999999\r\n\r\n{}",
    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n4\r\n{}",
])
def test_invalid_truncated_oversize_redirect_http_is_rejected(raw):
    with pytest.raises(ssh.HardwareMonitorSSHError):
        ssh._parse_response(raw)


@pytest.mark.parametrize("endpoint,params", [
    ("/healthz", {}), (STATUS, {"url": "http://other-host"}), (STATUS, {"limit": "1"}),
    (STATUS + "\r\nHost: other", {}), ("/api/v1/hardware-monitor/events", {"limit": "201"}),
    ("/api/v1/hardware-monitor/history", {"limit": "0"}),
    ("/api/v1/hardware-monitor/history", {"limit": "1441"}),
    ("/api/v1/hardware-monitor/history", {"limit": "60\r\nX: bad"}),
])
def test_fixed_endpoint_and_query_before_process(endpoint, params):
    with patch.object(ssh.subprocess, "Popen") as launch:
        with pytest.raises(proxy.HardwareMonitorUpstreamError):
            proxy.fetch_hardware_monitor_via_ssh(endpoint, params)
        launch.assert_not_called()


@pytest.mark.parametrize("kind,limit,timeout", [("status", None, 8), ("history", 60, 25), ("events", 50, 8)])
def test_all_three_routes_choose_ssh_on_mac(monkeypatch, kind, limit, timeout):
    monkeypatch.setattr(proxy.sys, "platform", "darwin")
    body = {"status": "partial", "items": []} if limit else {"status": "unavailable", "data": None}
    with patch.object(proxy, "read_scout_http", return_value=(503, json.dumps(body).encode())) as read:
        app = FastAPI(); app.include_router(proxy.create_hardware_monitor_proxy_router())
        with TestClient(app) as client:
            response = client.get(f"{PREFIX}/api/v1/hardware-monitor/{kind}" + (f"?limit={limit}" if limit else ""))
        assert response.status_code == 503 and response.json() == body
        read.assert_called_once_with(f"/api/v1/hardware-monitor/{kind}" + (f"?limit={limit}" if limit else ""), timeout=timeout)


def test_linux_keeps_fixed_http_and_mac_rejects_alternate_host(monkeypatch):
    monkeypatch.setattr(proxy.sys, "platform", "linux")
    with patch.object(proxy, "fetch_hardware_monitor_json", return_value=(200, {"data": None})) as read:
        app = FastAPI(); app.include_router(proxy.create_hardware_monitor_proxy_router())
        with TestClient(app) as client:
            assert client.get(PREFIX + STATUS).headers["x-scout-monitor-transport"] == "http"
        read.assert_called_once_with(STATUS, {}, upstream_base_url="http://127.0.0.1:9151")
    monkeypatch.setattr(proxy.sys, "platform", "darwin")
    with pytest.raises(ValueError):
        proxy.create_hardware_monitor_proxy_router(upstream_base_url="http://other-host")
