from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"


def test_scout_dashboard_page_serves_static_shell() -> None:
    client = TestClient(create_admin_app())

    response = client.get("/admin/dashboard")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Scout Dashboard v0.1" in response.text
    assert 'id="dashboardShell"' in response.text
    assert 'id="dashboardMap"' in response.text
    assert 'id="dashboardAgent"' in response.text
    assert 'id="dashboardEvidence"' in response.text


def test_scout_dashboard_contains_requested_navigation_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for expected in (
        "Home",
        "Features",
        "LBS",
        "Workspace",
        "Admin Surfaces",
        "Pre-trip",
        "Admin",
        "Debug",
        "Agent",
        "Map",
        "Timeline Evidence",
        "Safety / Emergency",
        "戶外六力",
        "Debug Message",
        "MQTT / Observer Message",
        "Settings / Configure",
    ):
        assert expected in html

    assert 'data-route="features-lbs"' in html
    assert 'data-route="features-workspace"' in html
    assert 'data-route="surface-pretrip"' in html
    assert 'data-route="surface-admin"' in html
    assert 'data-route="surface-debug"' in html


def test_scout_dashboard_points_to_current_chilai_workspace() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PROJECT_ID = "chilai_nanhua_day1_scoutAI";' in html
    assert 'new URLSearchParams(window.location.search).get("projectId")' in html
    assert "^[A-Za-z0-9_.-]+$" in html
    assert (
        'const WORKSPACE_ROOT = "/Users/alexwang0315/workspace/'
        'chilai_nanhua_day1_scoutAI";'
    ) in html
    assert "chilai_nanhua_day1 route map" not in html
    assert "chilai_nanhua_day1_scoutAI route map" in html


def test_scout_dashboard_embeds_existing_admin_surfaces() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "renderSurfaceFrame" in html
    assert 'id="surfaceFrame"' in html
    assert 'class="surface-frame"' in html
    assert 'src: surfaceSrc("/admin/pretrip")' in html
    assert 'src: surfaceSrc("/admin")' in html
    assert 'src: surfaceSrc("/admin/debug")' in html
    assert "projectId=${encodeURIComponent(projectId())}" in html
    assert "Current Admin Surfaces" in html
    assert "Open full page" in html


def test_scout_dashboard_data_fetches_have_timeout_fallback() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "const FETCH_TIMEOUT_MS = 20000;" in html
    assert "new AbortController()" in html
    assert "signal: controller.signal" in html
    assert "window.clearTimeout(timer)" in html
    assert "setRoute(routeFromHash());" in html
    assert "loadData().finally(() =>" in html
    assert "routeUsesEmbeddedFrame(state.route)" in html
    assert 'return route === "map" || route === "agent" || route.startsWith("surface-");' in html
    assert "routeUsesWideFrame(route)" in html
    assert 'return route === "agent";' in html
    assert "routeUsesFullFrame(route)" in html
    assert 'return route === "map";' in html
    assert "/debug-projection`" not in html


def test_scout_dashboard_agent_tab_embeds_local_mac_chat_without_reload() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const AGENT_APP_URL = "http://127.0.0.1:8765/?embed=dashboard&ui=compact-20260701";' in html
    assert 'id="dashboardAgent"' in html
    assert 'data-agent-source="http://127.0.0.1:8765/?embed=dashboard&ui=compact-20260701"' in html
    assert 'id="agentAppFrame"' in html
    assert 'class="agent-app-frame"' in html
    assert 'title="Scout AI Mac Chat"' in html
    assert "function ensureAgentAppFrame()" in html
    assert "frame.dataset.agentSource === AGENT_APP_URL" in html
    assert "frame.src = AGENT_APP_URL;" in html
    assert 'href="http://127.0.0.1:8765/"' in html
    assert "no live safety automation" in html
    assert "Local chat from 127.0.0.1:8765" in html
    assert "No live safety" in html
    assert "Local frame" in html
    assert "local Scout AI Mac Chat embedded" in html
    assert 'contentGrid?.classList.toggle("is-frame-wide", frameWide);' in html
    assert ".content-grid.is-frame-wide .evidence-drawer" in html
    assert "dashboardAgent.hidden = false;" in html
    assert "dashboardAgent.focus?.({ preventScroll: true });" in html


def test_scout_dashboard_timeline_evidence_uses_pretrip_tree_categories() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'const PRETRIP_DATA_PROJECT_ID = "chilai_nanhua_day1";' in html
    assert "function pretripDataProjectIds()" in html
    assert "fetchFirstPretripJson" in html
    assert "renderPretripEvidencePanel" in html
    assert "pretripEvidenceGroups" in html
    assert 'data-pretrip-evidence-source="${escapeHtml(sourceProject)}"' in html
    for tab_id, label in (
        ("default", "CP / Timeline"),
        ("map_risk", "Map / Risk"),
        ("completed", "Completed GPX"),
        ("review", "Review / Queue"),
        ("info", "Info / Other"),
    ):
        assert f'id: "{tab_id}"' in html
        assert label in html

    for group_name in (
        "Evidence Timeline",
        "Reference Segment Timing",
        "Checkpoints",
        "AI GIS CP",
        "GIS CP Areas",
        "Major Critical Points",
        "Boss Points",
        "Mileage Tags",
        "Overpass Trail Corridors",
        "Overpass Terrain Risk",
        "OSM Trail Network",
        "Risk Score",
        "Baseline Risk",
        "Calibrated Heat",
        "Risk Delta",
        "Environmental Risk Derivatives",
        "CWA QPF",
        "CWA Weather",
        "Soil Moisture",
        "Antecedent Rain",
        "Segments",
        "Retreat Routes",
        "Reference GPX",
        "Capability Timeline",
        "Info Sections",
        "Review Groups",
        "Review Queue",
    ):
        assert group_name in html

    assert 'data-evidence-tab="${escapeHtml(tab.id)}"' in html
    assert "state.activeEvidenceTab = selectedTab;" in html
    assert "state.activeMapEvidenceTab = selectedTab;" in html


def test_scout_dashboard_map_tab_uses_pretrip_map_only_surface() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert 'if (route === "map") {' in html
    assert "ensurePretripMapFrame()" in html
    assert "function ensurePretripMapFrame()" in html
    assert "bindPretripMapOnlyFrame" in html
    assert "applyPretripMapOnlyFrame" in html
    assert "scout-dashboard-map-only-style" in html
    assert 'id="dashboardMap"' in html
    assert 'id="pretripMapFrame"' in html
    assert 'data-map-mode="pretrip-map-only"' in html
    assert 'data-map-source="/admin/pretrip"' in html
    assert 'hidden aria-hidden="true" tabindex="-1"' in html
    assert 'frame.dataset.projectId === currentProjectId' in html
    assert 'frame.dataset.mapOnlyBound' in html
    assert "is-frame-full" in html
    assert 'surfaceSrc("/admin/pretrip")' in html
    assert "data-map-connected" in html
    assert "pre-trip map only" in html
    assert 'id="dashboardMapEvidence"' in html
    assert "renderMapEvidenceRail" in html
    assert "Map Evidence" in html
    assert "mapEvidenceCollapsed" in html
    assert "data-map-evidence-toggle" in html
    assert 'aria-label="${collapsed ? "Expand Map Evidence" : "Collapse Map Evidence"}"' in html
    assert 'rail.classList.toggle("is-collapsed", collapsed);' in html
    assert "map-evidence-rail.is-collapsed" in html
    assert "focusDashboardMapEvidence" in html
    assert "pretripEvidenceGroupOpen" in html
    assert "renderPretripEvidenceGroup(group, index, {defaultOpen: false})" in html
    assert "scheduleMapEvidenceFocusRetry" in html
    assert "pretripMapHasRenderedTargets" in html
    assert "Loading pre-trip timeline evidence for map focus." in html
    assert '["Checkpoints", "AI GIS CP", "Major Critical Points"].includes(group.title)' in html
    assert "mapWindow.focusMapFor" in html
    assert "mapWindow.selectEvidence" in html
    assert "data-map-evidence-source" in html
    assert "data-map-target-ids" in html
    assert 'const mapToolRight = state.mapEvidenceCollapsed ? "14px" : "418px";' in html
    assert "right: ${mapToolRight} !important;" in html
    assert "dashboardMapOnly" in html
    assert "mapOnlyReady" in html
    assert "grid-template-rows: minmax(0, 1fr);" in html
    assert ".dashboard-frame" in html
    assert 'dashboardShell?.classList.toggle("is-frame-full", frameFull);' in html
    assert 'document.body.classList.toggle("is-frame-full", frameFull);' in html
    assert "body.is-frame-full" in html
    assert ".dashboard-shell.is-frame-full .dashboard-sidebar" in html
    assert "height: 100%;" in html
    assert "min-height: 0;" in html
    assert "#readinessStrip" in html
    assert ".route-pane" in html
    assert ".detail-pane" in html


def test_scout_dashboard_outdoor_six_forces_subtree_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for route, label, system_name in (
        ("outdoor-route-context", "探索力", "Route Context Intelligence"),
        ("outdoor-pace-fit", "自信力", "Readiness & Pace Fit"),
        ("outdoor-permission", "勇氣力", "Contextual Permissioning"),
        ("outdoor-architecture", "路線力", "Route Architecture Intelligence"),
        ("outdoor-weather", "天氣力", "Weather-to-Decision Intelligence"),
        ("outdoor-navigation", "地圖力", "Navigation & Terrain Intelligence"),
    ):
        assert f'data-route="{route}"' in html
        assert label in html
        assert system_name in html

    for decision in (
        "GO",
        "CONDITIONAL_GO",
        "GUIDED_ONLY",
        "CHANGE_PLAN",
        "DELAY",
        "NO_GO",
        "ESCALATE",
    ):
        assert decision in html


def test_scout_dashboard_emergency_boundary_and_mobile_independence_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "Emergency Package Draft only" in html
    assert "mobile approval UI remains independent" in html
    assert "sent=false" in html
    assert "external_send_performed=false" in html
    assert "no live safety automation" in html
    assert "mobile remains independent" in html
    assert "/safety/" not in html
    assert "fetch(`${apiBase()}${path}`" in html
    assert "method:" not in html
    assert "POST" not in html


def test_scout_dashboard_layer_contract_ids_are_present() -> None:
    html = PAGE.read_text(encoding="utf-8")

    expected_layers = (
        "imagery",
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
        "osm",
        "terrain",
        "corridors",
        "overpass",
        "route",
        "completed-track",
        "reference-tracks",
        "retreat",
        "segments",
        "risk-ribbon",
        "risk-heatmap",
        "risk-delta",
        "soil-moisture",
        "antecedent-rain",
        "cwa-qpf",
        "risk-score",
        "checkpoints",
        "pois",
        "hazards",
        "route-notes",
        "cwa-weather",
        "mcp",
        "boss-points",
        "events",
        "weather-api",
    )
    for layer_id in expected_layers:
        assert f'"{layer_id}"' in html
    assert "SCOUT_LAYER_IDS" in html
    assert "input type=\"checkbox\" data-layer" in html
    assert "data-layer-group" in html
