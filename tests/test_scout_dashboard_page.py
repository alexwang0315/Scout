from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"
DOC = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.md"


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


def test_scout_dashboard_documentation_records_active_change_log() -> None:
    doc = DOC.read_text(encoding="utf-8")

    assert "# Scout Dashboard v0.1" in doc
    assert "## Active Recording Rule" in doc
    assert "Status: active." in doc
    assert "continue recording until the user explicitly says to stop" in doc
    assert "## Implementation Record" in doc
    assert "Import New Trip Tab Added" in doc
    assert "GPX Import and Map Preparation Parameters Exposed" in doc
    assert "Reference GPX Inputs Merged" in doc
    assert "Documentation Recording Rule Added" in doc
    assert "Template Project Root and Material Root Clarified" in doc
    assert "Material Root Overlap With DTM and MCP Clarified" in doc
    assert "Optional Import Parameters Marked" in doc
    assert "Workspace Root and BBox Derivation Clarified" in doc
    assert "Workspace Root and Target Name Consolidated" in doc
    assert "Optional Parameters Collapsed Into Advanced Frame" in doc
    assert "Low-value Import Panels Condensed" in doc
    assert "Country Material Pool Tab Added" in doc
    assert "Route Context Briefing Regeneration And Product Copy Cleanup" in doc
    assert "Route Context Intelligence Spec-Aligned Briefing Generation" in doc
    assert "Route Briefing Trip-Only Product Copy Guard" in doc


def test_scout_dashboard_contains_requested_navigation_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for expected in (
        "Home",
        "Features",
        "LBS",
        "Workspace",
        "Import New Trip",
        "Trip Intake",
        "Country Material Pool",
        "Admin Surfaces",
        "Pre-trip",
        "Admin",
        "Debug",
        "Agent",
        "Map",
        "Timeline Evidence",
        "Safety / Emergency",
        "Exploring for Six Axis",
        "Debug Message",
        "MQTT / Observer Message",
        "Settings / Configure",
    ):
        assert expected in html

    assert 'data-route="features-lbs"' in html
    assert 'data-route="features-workspace"' in html
    assert 'data-route="features-import-new-trip"' in html
    assert 'data-route="features-country-material-pool"' in html
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
    assert 'return route === "agent" || route === "debug" || route === "outdoor-route-context";' in html
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


def test_scout_dashboard_workspace_tab_summarizes_project_stats() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "function workspaceStats()" in html
    assert "function renderWorkspaceStatsPanels(stats)" in html
    assert 'data-workspace-stats="true"' in html
    for label in (
        "Route Statistics",
        "Project Counts",
        "Lifecycle Times",
        "Route length",
        "Route points",
        "Elevation range",
        "Reference tracks",
        "Checkpoints",
        "Segments",
        "Terrain tiles",
        "Review queue",
        "Evidence refs",
        "Imported",
        "Layers prepared",
        "Runtime exported",
        "Runtime loaded",
        "Data source",
    ):
        assert label in html

    assert "formatDistanceKm(numberValue(route.distance_m" in html
    assert 'if (value === null || value === undefined || value === "") return "--";' in html
    assert "formatDateTime(" in html
    assert "latestDebugEventTime" in html
    assert "workspaceEvidenceRefCount(project)" in html
    assert "project.import_manifest?.imported_at" in html
    assert "project.layer_preparation?.prepared_at" in html
    assert "state.pretripDataProjectId || projectId()" in html


def test_scout_dashboard_workspace_tab_exposes_structure_cache_and_operations() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderWorkspaceStructurePanels",
        "workspaceStructureRows",
        "renderWorkspaceCachePanels",
        "workspaceCacheRows",
        "renderWorkspaceOperationConsole",
        "bindWorkspaceControls",
        "formatTtl",
        "formatBoolean",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Workspace Structure",
        "Material Index",
        "Workspace Health",
        "Cached Material",
        "Cached TTL",
        "Cache Refs",
        "Workspace Operations",
        "Project root",
        "Source inbox",
        "Normalized route",
        "Import manifest",
        "Layer manifest",
        "Review queue",
        "Runtime handoff",
        "Imagery tiles",
        "Raster OCR",
        "OSM PBF",
        "OSM PBF TTL",
        "CWA TTL",
        "GEE TTL",
        "Weather cacheable",
    ):
        assert label in html

    for action in ("clone", "transfer", "pack", "restore", "delete"):
        assert f'data-workspace-action="{action}"' in html

    assert 'data-workspace-structure="true"' in html
    assert 'data-workspace-cache="true"' in html
    assert 'data-workspace-operations="true"' in html
    assert 'id="workspaceOperationStatus"' in html
    assert 'id="workspaceRedirectProjectInput"' in html
    assert 'id="workspaceSwitchProject"' in html
    assert "operator intent only" in html
    assert "No filesystem mutation is performed by this dashboard." in html
    assert "Delete requires an explicit destructive approval outside this dashboard." in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "Workspace id must use letters, numbers, underscore, dash or dot only." in html


def test_scout_dashboard_import_new_trip_tab_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderImportNewTripPage",
        "renderImportTripPreflight",
        "renderImportTripPipeline",
        "renderImportSelectField",
        "importTripProjectId",
        "importTripDefaultLayerIds",
        "setImportTripStatus",
        "bindImportTripControls",
        "splitImportReferenceGpxSources",
        "classifyImportReferenceGpxSources",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Features / Import New Trip",
        "Import New Trip",
        "Optional Parameters",
        "GPX Import Defaults",
        "Map Preparation Defaults",
        "Defaults are used when this frame stays collapsed.",
        "Import Pipeline",
        "Validate Intake",
        "Stage Import",
        "Open Workspace",
        "operator-triggered",
        "no live safety",
        "boundary metadata",
        "derived routing",
        "GPX required",
        "32 layers",
        "candidate export",
        "no outbound",
        "GIS repro-only",
        "Target name",
        "Project root",
        "Country material pool",
        "Material Pool",
        "material pool",
    ):
        assert label in html

    for marker in (
        'data-import-new-trip="true"',
        'data-import-trip-parameters="true"',
        'data-map-preparation-parameters="true"',
        'data-import-trip-preflight="true"',
        'data-import-trip-pipeline="true"',
        'class="import-context-panel"',
        'class="import-guard-strip"',
        'id="importTripIdInput"',
        'id="importGoldenRouteGpxPath"',
        'id="importWorkspaceRoot"',
        'id="importTargetNameInput"',
        'id="importTripStatus"',
        'data-import-trip-action="validate"',
        'data-import-trip-action="stage"',
        'data-import-trip-action="open"',
        'class="panel optional-parameters-frame"',
    ):
        assert marker in html

    for field_id in (
        "importReferenceGpxSources",
        "importWorkspaceRoot",
        "importTargetNameInput",
        "importTemplateProjectRoot",
        "importMaterialRoot",
        "importDtmDirs",
        "importMcpNamedPointEvidence",
        "importProfile",
        "importStage",
        "importCheckpointSpacingM",
        "importMaxReferenceDisplayPoints",
        "importMaxReasonableGpxSpeedKmh",
        "importMaxPreviousGpxSpeedRatio",
        "importOverwriteWorkspace",
        "prepareLayersList",
        "prepareBBox",
        "prepareRouteEvidenceBundle",
        "prepareRouteCorridorM",
        "prepareReferenceTrackCorridorM",
        "prepareLayersProfile",
        "prepareLayersNetworkMode",
        "prepareAllowNetworkFetch",
        "prepareAiMode",
        "prepareAiOutputPolicy",
        "prepareImageryMinZoom",
        "prepareImageryMaxZoom",
        "prepareSeedImageryCache",
        "prepareImageryProviderAllowsOfflinePrefetch",
        "prepareImagerySeedMaxTiles",
        "prepareImageryCacheFallbackProjectIds",
        "prepareOsmPbfPath",
        "prepareOsmPbfSourceUrl",
        "prepareOsmPbfCacheTtlDays",
        "prepareOsmiumBin",
        "preparePreparedAt",
    ):
        assert field_id in html

    for parameter_label in (
        "Golden route GPX path",
        "Reference GPX directory or paths",
        "Checkpoint spacing (m)",
        "Max reference display points",
        "Max reasonable GPX speed (km/h)",
        "Max previous speed ratio",
        "Layer ids",
        "Route evidence bundle",
        "Route corridor (m)",
        "Reference track corridor (m)",
        "Network mode",
        "AI mode",
        "Imagery min zoom",
        "Imagery max zoom",
        "OSM PBF cache TTL days",
    ):
        assert parameter_label in html

    assert "(optional)" not in html
    assert "Golden route GPX path (optional)" not in html
    assert "Target workspace (optional)" not in html
    assert "Project root (optional)" not in html
    assert "Import Boundary" not in html
    assert "Workspace Routing" not in html
    assert "Preflight Checklist" not in html
    assert "Layer Preparation Target" not in html
    assert "Runtime Handoff Guard" not in html
    assert "Evidence Drawer" not in html
    assert '<details class="panel optional-parameters-frame" data-import-trip-parameters="true">' in html
    assert '<details class="panel optional-parameters-frame" data-import-trip-parameters="true" open>' not in html
    assert 'id="importTripWorkspaceInput"' not in html
    assert 'id="prepareLayersWorkspaceRoot"' not in html
    assert 'id="prepareProjectRoot"' not in html

    assert 'if (route === "features-import-new-trip") return renderImportNewTripPage();' in html
    assert "importTripDraft" in html
    assert "goldenRouteGpx: goldenRouteInput.value.trim()" in html
    assert "countryMaterialPool: countryPoolInput.value || \"TW\"" in html
    assert "referenceGpxSources: fieldValue(\"importReferenceGpxSources\")" in html
    assert "targetName: targetNameValue()" in html
    assert "workspaceRoot: workspaceRootValue()" in html
    assert "prepareWorkspaceRoot: workspaceRootValue()" in html
    assert "prepareProjectRoot: derivedProjectRoot()" in html
    assert "importTripProjectRoot(workspaceRoot, targetName)" in html
    assert "prepareLayers: fieldValue(\"prepareLayersList\") || importTripDefaultLayerIds()" in html
    assert "fieldValue(\"prepareLayersList\") || importTripDefaultLayerIds()" in html
    assert 'value="${escapeHtml(draft.goldenRouteGpx || "")}"' in html
    assert "Reference GPX sources must be absolute paths." in html
    assert "Use either one directory path or a list of .gpx absolute paths." in html
    assert "1 reference GPX directory" in html
    assert "explicit GPX paths" in html
    assert "At least one map preparation layer id is required." in html
    assert "GPX import numeric parameters must be greater than 0." in html
    assert "Map preparation corridor parameters must be greater than 0." in html
    assert 'bindImportTripControls();' in html
    assert 'bindCountryMaterialPoolControls();' in html
    assert 'localStorage.setItem("scout.dashboardProjectId", nextProjectId)' in html
    assert 'url.searchParams.set("projectId", nextProjectId)' in html
    assert 'url.hash = "features-workspace";' in html
    assert "Trip id must use letters, numbers, underscore, dash or dot only." in html
    assert "Target name must use letters, numbers, underscore, dash or dot only." in html
    assert "importReferenceDirectory" not in html
    assert "importReferenceGpxPaths" not in html


def test_scout_dashboard_country_material_pool_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "countryMaterialPools",
        "countryMaterialPoolByCode",
        "countryMaterialPoolDefaults",
        "renderCountryMaterialPoolPage",
        "materialPoolCell",
        "renderMaterialResourceCard",
        "renderMaterialProviderRow",
        "bindCountryMaterialPoolControls",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Features / Country Material Pool",
        "country-scoped material and API provider defaults",
        "Country Material Pool",
        "Material Classes",
        "Route Context References",
        "API / Provider Matrix",
        "Import Defaults",
        "Map Preparation Uses",
        "Taiwan",
        "Japan",
        "Global Fallback",
        "DTM",
        "Base Maps",
        "Government Sites",
        "Weather API",
        "Geology API",
        "Marine API",
        "Open Data Entry",
        "CWA",
        "JMA",
        "GSI Maps",
        "NLSC EMAP",
        "Central Geological Survey",
        "林業及自然保育署自然步道資料",
        "台灣山林悠遊網開放資料",
        "臺灣登山申請一站式服務網",
        "國家公園路線開放狀態",
        "內政部國土測繪中心 DEM / DTM / 地形圖",
        "中央氣象署 CODiS / 開放資料",
        "NCDR 災害潛勢資料",
        "消防署山域事故救援案件",
        "TBN 台灣生物多樣性網絡",
        "中研院臺灣百年歷史地圖",
        "尋路・循路－臺灣原住民族古道空間資訊網",
        "國家文化記憶庫",
        "臺灣記憶",
        "地質雲",
        "魯地圖",
        "健行筆記",
        "Hikingbook",
        "PTT Hiking",
        "登山補給站",
        "rescue_training_reference",
        "community_media_evidence",
        "country-specific Geofabrik extract",
        "material_root",
        "dtm_dirs",
        "osm_pbf_source_url",
        "weather_provider",
        "candidate evidence only",
        "no live safety",
    ):
        assert label in html

    for marker in (
        "const COUNTRY_MATERIAL_POOLS = [",
        'data-country-material-pool="true"',
        'data-country-material-code="${escapeHtml(candidate.code)}"',
        'role="tablist"',
        'class="material-pool-layout"',
        'class="material-resource-grid"',
        'data-route-context-references="true"',
        'class="material-provider-table"',
        'if (route === "features-country-material-pool") return renderCountryMaterialPoolPage();',
        "state.activeCountryMaterialPool = code;",
        "countryMaterialPoolDefaults(countryPoolInput.value)",
        "materialRoot: \"\"",
        "dtmDirs: \"\"",
        "osmPbfSourceUrl: \"\"",
    ):
        assert marker in html

    assert "Japan providers; no CWA" in html
    assert "routeContextSources" in html
    assert "These P0/P1 entries come from specs/scout-route-context-layer and source-catalog.md." in html
    assert "catalog entries are not evidence by themselves" in html
    assert "This page sets default hints for import and layer preparation." in html
    assert "It does not fetch, mutate workspace files, load runtime packages, or change safety truth." in html


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


def test_scout_dashboard_debug_message_runtime_details_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "renderDebugRuntimeDetails",
        "renderDebugRuntimeSummary",
        "renderDebugActiveDetail",
        "renderDebugStateDetail",
        "renderDebugMonitorDetail",
        "renderDebugSoftwareDetail",
        "renderDebugHardwareDetail",
        "renderDebugIngressDetail",
        "renderDebugIncidentDetail",
        "renderDebugSkillToolDetail",
        "renderDebugOutboundDetail",
        "renderDebugBoundaryDetail",
        "renderDebugApiDetail",
        "renderDebugVisualPanel",
        "renderDebugHardwareInterfaceNode",
        "renderDebugBoundaryGateGrid",
        "renderDebugApiTile",
        "debugRuntimeMatrix",
        "activeDebugRuntimeRecord",
        "debugEventMatchesCategory",
        "bindDebugDetailControls",
        "debugEndpointText",
        "debugAllEvents",
        "debugProviderEntries",
    ):
        assert f"function {function_name}" in html

    for label in (
        "Runtime Details",
        "L0-L4",
        "Events",
        "Hardware",
        "Software",
        "Monitor",
        "Provider",
        "Ingress",
        "Incident",
        "Ln / Skill",
        "Skills",
        "Tools",
        "Outbound",
        "Boundary",
        "API",
        "Current L0-L4 State",
        "Monitoring Center",
        "Provider Degraded Status",
        "Runtime Software State",
        "Hardware Readiness",
        "Hardware Interface Bus",
        "Hardware Providers",
        "Hardware Boundary Gates",
        "Mobile/Wearable Ingress",
        "Ingress Boundary",
        "Incident And Bridge Status",
        "Ln And Skill Runs",
        "Agent Tool Trace",
        "Scout Skills",
        "Outbound Queue",
        "Boundary Snapshot",
        "API Payloads",
        "Runtime Sources",
        "Boundary Notes",
        "Debug Message Stream",
        "API Payload Matrix",
    ):
        assert label in html

    for source in (
        "/debug/events?limit=200",
        "/debug/state",
        "/debug/messages",
        "/debug/mobile-wearable/ingress",
        "/debug/monitoring",
        "/admin/hardware-readiness/context",
        "GPIO/I2C/I2S/TTS/Bluetooth/UART/power/GNSS/IMU/USB/SSD inventory",
    ):
        assert source in html

    assert "DEBUG_DETAIL_CATEGORIES" in html
    assert 'activeDebugDetail: "state"' in html
    for state_field in (
        "runtimeDebugEvents",
        "runtimeDebugEventPayload",
        "debugRuntimeState",
        "debugMessages",
        "debugMessagesPayload",
        "mobileWearableIngress",
        "monitoringCenter",
        "hardwareReadiness",
    ):
        assert state_field in html

    assert 'data-debug-runtime-details="true"' in html
    assert 'data-debug-message-details="true"' in html
    assert 'data-debug-message-sources="true"' in html
    assert 'data-debug-console="true"' in html
    assert 'data-debug-stream-tables="true"' in html
    assert 'data-debug-detail="${escapeHtml(record.id)}"' in html
    assert "debug-telemetry-bar" in html
    assert "debug-tab-shell" in html
    assert "debug-console-grid" in html
    assert "debug-drawer-stack" in html
    assert "debug-table-grid" in html
    assert "debug-slim-row" in html
    assert "debug-node-grid" in html
    assert "debug-flow" in html
    assert "debug-bus" in html
    assert "debug-level-strip" in html
    assert "debug-api-tile" in html
    assert "debug-pin-grid" in html
    assert "/admin/debug" in html
    assert "/admin/hardware-readiness/context" in html
    assert "debug-projection-events" in html
    assert "debug-projection" in html
    assert "not triggered from dashboard" in html
    assert "readiness metadata only" in html
    assert "mock / dry-run message evidence only" in html
    assert "state.activeDebugDetail = button.dataset.debugDetail || \"state\";" in html


def test_scout_dashboard_outdoor_six_forces_subtree_contract() -> None:
    html = PAGE.read_text(encoding="utf-8")

    for route, label, system_name in (
        ("outdoor-route-context", "Route Context", "Route Context Intelligence"),
        ("outdoor-pace-fit", "Pace Fit", "Readiness & Pace Fit"),
        ("outdoor-permission", "Permission", "Contextual Permissioning"),
        ("outdoor-architecture", "Architecture", "Route Architecture Intelligence"),
        ("outdoor-weather", "Weather", "Weather-to-Decision Intelligence"),
        ("outdoor-navigation", "Navigation", "Navigation & Terrain Intelligence"),
    ):
        assert f'data-route="{route}"' in html
        assert label in html
        assert system_name in html

    for removed_label in ("戶外六力", "探索力", "自信力", "勇氣力", "路線力", "天氣力", "地圖力"):
        assert removed_label not in html

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


def test_scout_dashboard_route_context_embeds_skill_trip_briefing() -> None:
    html = PAGE.read_text(encoding="utf-8")

    assert "function routeContextBriefingProjectId()" in html
    assert "function routeContextBriefingSrc()" in html
    assert "function renderRouteBriefingMetaBlock" in html
    assert "return candidate || PRETRIP_DATA_PROJECT_ID;" in html
    assert 'return route === "agent" || route === "debug" || route === "outdoor-route-context";' in html
    assert 'decisionBand(force.decision, "Scout AI route-context trip briefing loaded"' not in html
    assert "/admin/pretrip/projects/${project}/briefings/route-context" in html
    assert "data-route-context-briefing=\"true\"" in html
    assert 'class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed"' in html
    assert '<details class="route-briefing-meta-drawer" data-route-briefing-metadata="collapsed" open>' not in html
    assert "Briefing metadata" in html
    assert "route-briefing-meta-grid" in html
    assert "route-briefing-meta-block" in html
    assert "Scout AI Trip Briefing" not in html
    assert "route-briefing-ops" in html
    assert "data-route-context-briefing-regenerate" in html
    assert "Regenerate with Scout AI" in html
    assert "/briefings/route-context/regenerate" in html
    assert "Calling Scout AI via OpenRouter" in html
    assert "Open briefing" in html
    assert "outputs/briefings/route_context_briefing.html" in html
    assert "scout-route-context-briefing skill" in html
    assert "pretrip_route_context_collection" in html
    assert "candidate-only" in html
    assert "runtime_safety_truth=false" in html
    assert "stop permission, route open/closed decision" in html
    assert "no Phase 1 mutation, no safety endpoint write" in html
    assert "no live safety automation" in html
    assert '<div class="debug-main-stack">\n            ${renderMetricPanel("Briefing Source"' not in html


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
    assert 'method: "POST"' in html
    assert "/briefings/route-context/regenerate" in html
    assert "confirm_regenerate: true" in html


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
