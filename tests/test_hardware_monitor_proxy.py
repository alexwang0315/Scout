from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from admin_api import create_dashboard_app
from tools.hardware_monitor_proxy import (
    HardwareMonitorUpstreamError,
    fetch_hardware_monitor_json,
)


def _status_payload(*, status: str = "ok", data: Any = None) -> dict[str, Any]:
    return {
        "schema_version": "scout.hardware-monitor.api.v1",
        "server_time": "2026-09-11T02:00:00Z",
        "status": status,
        "summary": "硬體資料測試回應",
        "freshness": {
            "state": "fresh" if status == "ok" else "stale",
            "captured_at": "2026-09-11T01:59:00Z",
            "age_seconds": 60,
            "sample_interval_seconds": 60,
            "stale_after_seconds": 150,
        },
        "data": data,
        "next_steps": [],
        "read_only": True,
    }


def _inventory() -> dict[str, Any]:
    return {
        "captured_at": "2026-09-11T01:59:00Z",
        "status": "partial",
        "read_only": True,
        "active_scan_performed": False,
        "gpio_value_sampling_performed": False,
        "sections": {
            "gpio": {
                "status": "partial",
                "summary": "部分線路資訊",
                "items": [
                    {
                        "id": "gpiochip-test",
                        "name": "測試控制器",
                        "state": "present",
                        "driver": None,
                        "properties": {"line_count": 1},
                        "lines": [
                            {
                                "offset": 0,
                                "name": "測試",
                                "direction": "input",
                                "consumer": "<img src=x>",
                                "active_low": False,
                                "value": None,
                            }
                        ],
                    }
                ],
                "notes": ["未讀取電位"],
                "errors": ["部分資訊無法讀取"],
            },
        },
    }


def test_dashboard_proxy_keeps_hardware_api_same_origin_and_forwards_limits(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Mapping[str, str]]] = []
    status_data = {
        "status": "ok",
        "alerts": {},
        "thresholds": {},
        "inventory": _inventory(),
    }

    def fetcher(endpoint: str, params: Mapping[str, str]) -> tuple[int, Any]:
        calls.append((endpoint, params))
        if endpoint.endswith("/status"):
            return 200, _status_payload(data=status_data)
        return 200, {
            "schema_version": "scout.hardware-monitor.api.v1",
            "server_time": "2026-09-11T02:00:00Z",
            "status": "ok",
            "summary": "測試列表",
            "items": [],
            "meta": {"limit": int(params["limit"]), "count": 0},
        }

    app = create_dashboard_app(
        assistant_enabled=False,
        assistant_environ={},
        runtime_audit_root=tmp_path / "runtime-audit",
        hardware_monitor_fetcher=fetcher,
    )

    with TestClient(app) as client:
        status = client.get(
            "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status"
        )
        history = client.get(
            "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/history?limit=60"
        )
        events = client.get(
            "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/events?limit=50"
        )
        mutation = client.post(
            "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status"
        )

    assert status.status_code == 200
    assert status.json()["data"] == status_data
    assert history.status_code == 200
    assert events.status_code == 200
    assert mutation.status_code == 405
    assert calls == [
        ("/api/v1/hardware-monitor/status", {}),
        ("/api/v1/hardware-monitor/history", {"limit": "60"}),
        ("/api/v1/hardware-monitor/events", {"limit": "50"}),
    ]


def test_dashboard_proxy_preserves_stale_503_and_old_data_is_not_reclassified(
    tmp_path: Path,
) -> None:
    stale_data = {
        "status": "ok",
        "alerts": {},
        "thresholds": {},
        "inventory": _inventory(),
    }
    stale_payload = _status_payload(status="stale", data=stale_data)

    def fetcher(endpoint: str, params: Mapping[str, str]) -> tuple[int, Any]:
        assert endpoint == "/api/v1/hardware-monitor/status"
        assert params == {}
        return 503, stale_payload

    app = create_dashboard_app(
        assistant_enabled=False,
        assistant_environ={},
        runtime_audit_root=tmp_path / "runtime-audit",
        hardware_monitor_fetcher=fetcher,
    )

    with TestClient(app) as client:
        response = client.get(
            "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status"
        )

    assert response.status_code == 503
    assert response.json() == stale_payload
    assert response.json()["status"] == "stale"
    assert response.json()["data"]["status"] == "ok"
    assert response.headers["cache-control"] == "no-store"


def test_dashboard_proxy_returns_typed_unavailable_payload_on_disconnect(
    tmp_path: Path,
) -> None:
    def fetcher(endpoint: str, params: Mapping[str, str]) -> tuple[int, Any]:
        raise HardwareMonitorUpstreamError("test disconnect")

    app = create_dashboard_app(
        assistant_enabled=False,
        assistant_environ={},
        runtime_audit_root=tmp_path / "runtime-audit",
        hardware_monitor_fetcher=fetcher,
    )

    with TestClient(app) as client:
        response = client.get(
            "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status"
        )

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "unavailable"
    assert body["data"] is None
    assert body["freshness"]["state"] == "unreadable"


def test_fetcher_parses_json_body_from_upstream_stale_503() -> None:
    payload = _status_payload(status="stale", data={"status": "ok"})
    error = HTTPError(
        "http://127.0.0.1:9151/api/v1/hardware-monitor/status",
        503,
        "stale",
        hdrs=None,
        fp=BytesIO(json.dumps(payload).encode("utf-8")),
    )

    with patch("urllib.request.OpenerDirector.open", side_effect=error):
        status_code, decoded = fetch_hardware_monitor_json(
            "/api/v1/hardware-monitor/status",
            {},
        )

    assert status_code == 503
    assert decoded == payload
    assert decoded["status"] == "stale"
    assert decoded["data"]["status"] == "ok"


def test_fetcher_refuses_non_allowlisted_endpoints_before_network() -> None:
    with patch("urllib.request.OpenerDirector.open") as request:
        with pytest.raises(HardwareMonitorUpstreamError):
            fetch_hardware_monitor_json("/api/v1/hardware-control/reboot", {})
        request.assert_not_called()


@pytest.mark.parametrize("body", [b"null", b"[]", b'{"value":NaN}', b"not JSON"])
def test_fetcher_rejects_invalid_envelopes(body: bytes) -> None:
    with patch("urllib.request.OpenerDirector.open") as request:
        request.return_value.__enter__.return_value.read.return_value = body
        with pytest.raises(HardwareMonitorUpstreamError):
            fetch_hardware_monitor_json("/api/v1/hardware-monitor/status", {})
