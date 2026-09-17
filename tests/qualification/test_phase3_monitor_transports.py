"""Current Monitor transport contracts; all positive external reads use memory fixtures.

The production SSH process is exercised only as a denied operation inside
EffectAudit. OS pipe/child lifetime tests stay in test_hardware_monitor_ssh.py;
that module's captured native POPEN is never imported by these audited replays.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.qualification.effects import EffectAudit
from tests.test_hardware_monitor_proxy import _status_payload
from tools import hardware_monitor_proxy as proxy
from tools import hardware_monitor_ssh as ssh

PREFIX = "/admin/dashboard/scout-monitor"
STATUS = "/api/v1/hardware-monitor/status"


def test_monitor_platform_dispatch_keeps_fixed_ssh_and_http_scope(monkeypatch) -> None:
    for platform, transport in (("darwin", "ssh"), ("linux", "http")):
        ssh_calls, http_calls = [], []
        payload = {"status": "stale", "read_only": True, "data": None}
        def fixture_ssh(target, *, timeout):
            ssh_calls.append((target, timeout))
            return 503, json.dumps(payload).encode()
        def fixture_http(endpoint, params, *, upstream_base_url):
            http_calls.append((endpoint, params, upstream_base_url))
            return 503, payload
        with monkeypatch.context() as fixture:
            fixture.setattr(proxy.sys, "platform", platform)
            fixture.setattr(proxy, "read_scout_http", fixture_ssh)
            fixture.setattr(proxy, "fetch_hardware_monitor_json", fixture_http)
            app = FastAPI()
            app.include_router(proxy.create_hardware_monitor_proxy_router())
            targets = (STATUS, "/api/v1/hardware-monitor/history?limit=60",
                       "/api/v1/hardware-monitor/events?limit=50")
            with TestClient(app) as client:
                responses = [client.get(PREFIX + target) for target in targets]
                assert all(response.status_code == 503 and response.json() == payload for response in responses)
                assert all(response.headers["x-scout-monitor-transport"] == transport for response in responses)
                assert all(response.headers["cache-control"] == "no-store" for response in responses)
                assert client.post(PREFIX + STATUS).status_code == 405
                assert client.get(PREFIX + "/api/v1/hardware-monitor/history?limit=1441").status_code == 422
                assert client.get(PREFIX + "/api/v1/hardware-monitor/events?limit=201").status_code == 422
            if transport == "ssh":
                assert ssh_calls == [(targets[0], 8), (targets[1], 25), (targets[2], 8)]
                assert http_calls == []
                try:
                    proxy.create_hardware_monitor_proxy_router(upstream_base_url="http://other-host")
                except ValueError as error:
                    assert "destination is fixed" in str(error)
                else:
                    raise AssertionError("Darwin alternate upstream must be rejected")
            else:
                assert ssh_calls == []
                assert http_calls == [
                    (STATUS, {}, "http://127.0.0.1:9151"),
                    ("/api/v1/hardware-monitor/history", {"limit": "60"}, "http://127.0.0.1:9151"),
                    ("/api/v1/hardware-monitor/events", {"limit": "50"}, "http://127.0.0.1:9151"),
                ]


def test_monitor_ssh_disconnect_stale_recovery_preserves_currentness(monkeypatch) -> None:
    stale = _status_payload(status="stale", data={"captured_at": "2026-09-11T01:59:00Z"})
    stale["freshness"].update({"state": "stale", "age_seconds": 360})
    fresh = _status_payload(status="ok", data={"captured_at": "2026-09-11T02:05:00Z"})
    fresh["freshness"].update({"state": "fresh", "captured_at": fresh["data"]["captured_at"], "age_seconds": 0})
    def wire(payload, code, *, chunked=False):
        body = json.dumps(payload).encode()
        if chunked:
            framing = b"Transfer-Encoding: chunked"
            body = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        else:
            framing = f"Content-Length: {len(body)}".encode()
        return f"HTTP/1.1 {code} Test\r\nContent-Type: application/json\r\n".encode() + framing + b"\r\n\r\n" + body
    calls = []
    outcomes = (
        ssh.HardwareMonitorSSHError("ssh_unavailable"),
        ssh.HardwareMonitorSSHError("scout_api_unavailable"),
        wire(stale, 503), wire(fresh, 200, chunked=True),
    )
    def fixture_read(target, *, timeout):
        calls.append((target, timeout))
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return ssh._parse_response(outcome)
    monkeypatch.setattr(proxy.sys, "platform", "darwin")
    monkeypatch.setattr(proxy, "read_scout_http", fixture_read)
    app = FastAPI()
    app.include_router(proxy.create_hardware_monitor_proxy_router())
    with patch.object(proxy, "fetch_hardware_monitor_json") as forbidden_http, TestClient(app) as client:
        disconnected, api_down, old, recovered = [client.get(PREFIX + STATUS) for _ in outcomes]
    assert disconnected.status_code == api_down.status_code == old.status_code == 503
    assert disconnected.json()["connection"]["error_code"] == "ssh_unavailable"
    assert api_down.json()["connection"]["error_code"] == "scout_api_unavailable"
    for response in (disconnected, api_down):
        assert response.json()["data"] is None and response.json()["read_only"] is True
        assert response.json()["connection"] == {
            "transport": "ssh", "error_code": response.json()["connection"]["error_code"],
            "retry_interval_seconds": 60, "local_forward_required": False,
        }
    assert "不需要開啟 Mac 9151" in disconnected.text
    assert "SSH 已連通，但 Scout 的 9151 API 無法連線" in api_down.text
    assert old.json() == stale and old.json()["freshness"]["state"] == "stale"
    assert recovered.status_code == 200 and recovered.json() == fresh
    assert all(response.headers["x-scout-monitor-transport"] == "ssh" for response in (disconnected, api_down, old, recovered))
    assert calls == [(STATUS, 8)] * 4
    forbidden_http.assert_not_called()


def test_monitor_ssh_native_process_is_blocked_before_invocation(tmp_path: Path, monkeypatch) -> None:
    native_calls, proofs = [], []
    def forbidden_native_popen(*args, **kwargs):
        native_calls.append((args, kwargs))
        raise AssertionError("the real subprocess primitive must never be reached")
    monkeypatch.setattr(subprocess, "Popen", forbidden_native_popen)
    for entrypoint in ("direct-reader", "darwin-default-router"):
        transition_id = "phase3.monitor.ssh-deny." + entrypoint
        with EffectAudit(transition_id=transition_id, roots=(("execution", tmp_path),)) as audit:
            if entrypoint == "direct-reader":
                try:
                    proxy.fetch_hardware_monitor_via_ssh(STATUS, {})
                except proxy.HardwareMonitorUpstreamError as error:
                    assert error.code == "ssh_unavailable"
                else:
                    raise AssertionError("real SSH must not run inside qualification")
            else:
                with patch.object(proxy.sys, "platform", "darwin"):
                    app = FastAPI()
                    app.include_router(proxy.create_hardware_monitor_proxy_router())
                    with TestClient(app) as client:
                        response = client.get(PREFIX + STATUS)
                    assert response.status_code == 503
                    assert response.json()["connection"]["error_code"] == "ssh_unavailable"
        attempts = [
            {"operation": item.operation, "effect_class": item.effect_class, "outcome": item.outcome}
            for item in audit.attempts if item.effect_class == "subprocess"
        ]
        assert len(attempts) == 1 and attempts[0]["outcome"] == "blocked_before_invocation"
        proofs.append({"transition_id": transition_id, "attempts": attempts})
    assert native_calls == []
    (tmp_path / "native-ssh-denial.json").write_text(json.dumps({
        "native_popen_invocations": 0, "proofs": proofs,
        "source_path": "tools/hardware_monitor_ssh.py",
    }, sort_keys=True) + "\n")
