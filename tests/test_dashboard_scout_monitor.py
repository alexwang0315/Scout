from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_dashboard_app


def test_dashboard_mounts_scout_monitor_system_page_and_read_only_api(
    tmp_path: Path,
) -> None:
    app = create_dashboard_app(
        assistant_enabled=False,
        assistant_environ={},
        runtime_audit_root=tmp_path / "runtime-audit",
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
    assert "Scout Monitor · 硬體監控" in monitor_page.text
    assert "硬體監控" in monitor_page.text
    assert "v1/hardware-monitor/${endpoint}" in monitor_page.text
    assert 'fetchHardwareEndpoint("status"' in monitor_page.text
    assert "HARDWARE_REFRESH_INTERVAL_MS = 60 * 1000" in monitor_page.text
    assert 'signal: controller.signal' in monitor_page.text
    assert 'window.addEventListener("pagehide", stopHardwarePolling' in monitor_page.text
    assert "資料已過期" in monitor_page.text
    assert "1024 ** 3" in monitor_page.text
    assert "refreshSnapshot" not in monitor_page.text
    assert "MacBook" not in monitor_page.text
    assert 'id="processTable"' not in monitor_page.text
    assert 'id="intervalSelect"' not in monitor_page.text
    assert 'id="hardwareInventoryPanel"' in monitor_page.text
    assert 'id="hardwareInventoryGrid"' in monitor_page.text
    assert 'renderHardwareInventory(data, effectiveState)' in monitor_page.text
    assert 'inventoryExpansion' in monitor_page.text
    assert '未採樣' in monitor_page.text
    assert '已讀取 ≠ 設備功能正常' in monitor_page.text

    assert health.status_code == 404
    assert snapshot.status_code == 404
    assert mutation.status_code == 404
