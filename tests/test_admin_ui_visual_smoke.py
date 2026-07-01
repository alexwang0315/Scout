from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tools.admin_ui_smoke_app import create_smoke_app


SCRIPT = Path("tools/admin_ui_visual_smoke.js")


def test_admin_ui_smoke_app_serves_all_admin_surfaces():
    client = TestClient(create_smoke_app())

    expected_pages = {
        "/admin": "Scout Phase 1 Admin",
        "/admin/debug": "Scout Phase 3.5 Runtime Debug",
        "/admin/pretrip": "Scout Phase 4 Pre-Trip Planning",
        "/admin/hardware-readiness": "Scout Hardware Readiness",
        "/admin/dashboard": "Scout Dashboard v0.1",
    }
    for route, expected_text in expected_pages.items():
        response = client.get(route)
        assert response.status_code == 200
        assert expected_text in response.text

    debug_events = client.get("/debug/events")
    assert debug_events.status_code == 200
    assert debug_events.json()["events"]

    pretrip_view = client.get("/admin/pretrip/projects/chilai_nanhua_day1")
    assert pretrip_view.status_code == 200
    assert pretrip_view.json()["readiness"]["status"]

    hardware_view = client.get("/admin/hardware-readiness/context")
    assert hardware_view.status_code == 200
    assert hardware_view.json()["boundary"]["provider_control_allowed"] is False


def test_admin_ui_visual_smoke_script_covers_routes_viewports_and_boundaries():
    script = SCRIPT.read_text(encoding="utf-8")

    for route in ("/admin/debug", "/admin/pretrip", "/admin/hardware-readiness", "/admin", "/admin/dashboard"):
        assert route in script
    assert "/admin/dashboard?projectId=chilai_nanhua_day1#map" in script

    for selector in (
        "#runtimeMap",
        "#narrativePanel",
        "#readinessStrip",
        "#assistantPanel",
        "#dashboardShell",
        "#dashboardMap",
        "#dashboardMapStatus",
        "#dashboardMapEvidence",
        "#pretripMapFrame",
        "#dashboardEvidence",
        "#providerGrid .provider-card",
        ".timeline-node.is-selected",
    ):
        assert selector in script

    assert "desktop" in script
    assert "mobile" in script
    assert "consoleErrors" in script
    assert "noHorizontalOverflow" in script
    assert "tinyTargets" in script
    assert "ready" in script
    assert "missingText" in script
    assert "fallback geometry" in script
    assert "frameSelector" in script
    assert 'frameSurfaceId: "dashboard-map-only"' in script
    assert "frameSelectors" in script
    assert "frameVisibleSelectors" in script
    assert "frameHiddenSelectors" in script
    assert "frameMustFitViewport" in script
    assert "collectDashboardFrameReuseChecks" in script
    assert "smokeLoadCount" in script
    assert "sameSrc" in script
    assert "verticalOverflowPx" in script
    assert "frameBottomOverflowPx" in script
    assert "Scout Phase 4 Pre-Trip Planning" in script
    assert ".map-pane" in script
    assert ".toolbar-title" in script
    assert ".tool-disclosure" in script
    assert ".route-pane" in script
    assert ".detail-pane" in script
    assert "#jsonPane" in script
    assert "#routeMeta" in script
    assert "mapOnly" in script
    assert "mapIsLargest" in script
    assert "centeredMapLayout" in script
    assert "--screenshots-dir" in script
