from __future__ import annotations

from fastapi.testclient import TestClient

from admin_api import create_admin_app


def test_dashboard_exposes_unified_runtime_activity_page(tmp_path) -> None:
    with TestClient(
        create_admin_app(runtime_audit_root=tmp_path / "audit")
    ) as client:
        response = client.get("/admin/dashboard")

    assert response.status_code == 200
    html = response.text
    assert 'data-route="runtime-audit"' in html
    assert "Runtime Activity" in html
    assert '"runtime-audit": Object.freeze' in html
    assert 'runtime_audit: ["runtime-audit"]' in html
    assert "function renderRuntimeAuditPage()" in html
    assert "function loadRuntimeAuditData(" in html
    assert "/admin/runtime-audit" in html
    assert "統一運行紀錄" in html
    assert "沒有紀錄不代表沒有執行" in html
    assert "功能覆蓋率" in html
    assert "Writer health" in html
    assert "Hash chain 只能檢查損壞與順序" in html
    assert "summary.internal_api_calls" in html
    assert "event.record_count != null" in html
    assert "telemetry only" in html.lower()
