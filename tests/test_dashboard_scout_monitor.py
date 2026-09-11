from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from admin_api import create_dashboard_app


class StubResourceCollector:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict[str, Any]:
        self.calls += 1
        return {
            "schema_version": "scout.macos_resource_snapshot.v0.1",
            "captured_at": "2026-09-11T00:00:00Z",
            "host": {"name": "Test MacBook", "scout_scope": "scout-fusion"},
            "overall": {
                "status": "nominal",
                "observation_count": 0,
                "observations": [],
                "summary": "目前沒有資源注意事項",
            },
            "boundary": {
                "read_only": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "external_effects": False,
                "scope": "local macOS resource observation",
            },
        }


def test_dashboard_mounts_scout_monitor_system_page_and_read_only_api(
    tmp_path: Path,
) -> None:
    collector = StubResourceCollector()
    app = create_dashboard_app(
        assistant_enabled=False,
        assistant_environ={},
        runtime_audit_root=tmp_path / "runtime-audit",
        resource_monitor_collector=collector,
    )

    with TestClient(app) as client:
        dashboard = client.get("/admin/dashboard")
        monitor_page = client.get("/admin/dashboard/scout-monitor")
        health = client.get("/admin/dashboard/scout-monitor/api/health")
        snapshot = client.get("/admin/dashboard/scout-monitor/api/snapshot")
        mutation = client.post("/admin/dashboard/scout-monitor/api/snapshot")

    assert dashboard.status_code == 200
    assert 'data-route="scout-monitor"' in dashboard.text
    assert '<span>scout monitor</span>' in dashboard.text
    assert '"scout-monitor": ["scout monitor"' in dashboard.text
    assert 'src: "/admin/dashboard/scout-monitor"' in dashboard.text

    assert monitor_page.status_code == 200
    assert "Scout / Mac Resource Observatory" in monitor_page.text
    assert "硬體監控" in monitor_page.text
    assert "v1/hardware-monitor/${endpoint}" in monitor_page.text
    assert 'fetchHardwareEndpoint("status"' in monitor_page.text
    assert "HARDWARE_REFRESH_INTERVAL_MS = 60 * 1000" in monitor_page.text
    assert 'signal: controller.signal' in monitor_page.text
    assert 'window.addEventListener("pagehide", stopAllPolling' in monitor_page.text
    assert "資料已過期" in monitor_page.text
    assert "1024 ** 3" in monitor_page.text
    assert 'fetch(monitorApiPath("snapshot")' in monitor_page.text
    assert 'fetch("/api/snapshot"' not in monitor_page.text

    assert health.status_code == 200
    assert health.json()["service"] == "scout-macos-resource-monitor"
    assert health.json()["read_only"] is True
    assert snapshot.status_code == 200
    assert snapshot.json()["boundary"]["runtime_safety_truth"] is False
    assert collector.calls == 1
    assert mutation.status_code == 405
