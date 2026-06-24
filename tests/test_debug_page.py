import re
import unittest
from pathlib import Path


PAGE_PATH = Path("docs/admin/phase-3-5-runtime-debug.html")
ASSISTANT_UI_SCRIPT = Path("docs/admin/scout-assistant-ui.js")
MUTATION_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
ALLOWED_DEBUG_ENDPOINTS = {
    "/admin/hardware-readiness/context",
    "/assistant/status",
    "/debug/events",
    "/debug/messages",
    "/debug/mobile-wearable/ingress",
    "/debug/monitoring",
    "/debug/state",
}


class DebugPageTests(unittest.TestCase):
    def test_static_debug_page_renders_required_debug_panels(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("Scout Phase 3.5 Runtime Debug", html)
        self.assertIn("Read-only engineering console", html)
        self.assertIn("Runtime closed", html)
        self.assertIn("No writeback", html)
        self.assertIn("Mock only", html)
        self.assertIn("Current L0-L4 State", html)
        self.assertIn("Provider Degraded Status", html)
        self.assertIn("Hardware Readiness", html)
        self.assertIn("Mobile/Wearable Ingress", html)
        self.assertIn("Ln And Skill Runs", html)
        self.assertIn("Agent tool calls", html)
        self.assertIn("Spatial imprint events", html)
        self.assertIn("agent_tool_invocation", html)
        self.assertIn("spatial_imprint_trigger_event", html)
        self.assertIn("Outbound Queue", html)
        self.assertIn("Incident And Bridge Status", html)
        self.assertIn("Debug Evidence Map", html)
        self.assertIn("Runtime Details", html)
        self.assertIn("Timeline", html)

    def test_static_debug_page_collapses_debug_panels_into_tabs(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('role="tablist"', html)
        self.assertIn('role="tab"', html)
        self.assertIn('role="tabpanel"', html)
        self.assertIn("data-tab-target", html)
        self.assertIn("switchDebugTab", html)
        self.assertIn("bindDebugTabs", html)
        self.assertIn('id="panel-state"', html)
        self.assertIn('id="panel-provider"', html)
        self.assertIn('id="panel-hardware"', html)
        self.assertIn('id="panel-ingress"', html)
        self.assertIn('id="panel-incident"', html)
        self.assertIn('id="panel-skill"', html)
        self.assertIn('id="panel-outbound"', html)
        self.assertIn('id="panel-boundary"', html)
        self.assertIn('id="panel-api"', html)

    def test_static_debug_page_renders_debug_endpoint_payload_windows(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("Debug Endpoint Payloads", html)
        self.assertIn("/debug/events、/debug/state、/debug/messages", html)
        self.assertIn('id="debugEventsPayload"', html)
        self.assertIn('id="debugStatePayload"', html)
        self.assertIn('id="debugMessagesPayload"', html)
        self.assertIn("endpointPayloadText", html)
        self.assertIn("renderEndpointPayloads", html)
        self.assertIn("JSON.stringify(payload || {}, null, 2)", html)
        self.assertIn("Debug endpoint payload windows", html)

    def test_static_debug_page_reads_mobile_wearable_ingress_status(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="tab-ingress"', html)
        self.assertIn('id="panel-ingress"', html)
        self.assertIn("/debug/mobile-wearable/ingress", html)
        self.assertIn("loadMobileWearableIngressContext", html)
        self.assertIn("debugPageState.mobileWearableIngress", html)
        self.assertIn("renderMobileWearableIngress", html)
        self.assertIn('id="mobileIngressSummary"', html)
        self.assertIn('id="mobileIngressSummary">listening</span>', html)
        self.assertIn("const activityCount = Math.max(recordCount, messageCount);", html)
        self.assertIn('activityCount ? `${activityCount} ingress` : "listening"', html)
        self.assertIn('id="mobileIngressRecordCount"', html)
        self.assertIn('id="mobileIngressMessageCount"', html)
        self.assertIn('id="mobileIngressInvalidCount"', html)
        self.assertIn('id="mobileIngressSensorCount"', html)
        self.assertIn('id="mobileIngressLatestStatus"', html)
        self.assertIn('id="mobileIngressResetButton"', html)
        self.assertIn('id="mobileIngressMemo"', html)
        self.assertIn('id="mobileIngressBoundaryMemo"', html)
        self.assertIn("mobileIngressBoundaryMemo(boundary)", html)
        self.assertIn("/debug/stream", html)
        self.assertIn("/debug/mobile-wearable/ingress/reset", html)
        self.assertIn("EventSource", html)
        self.assertIn("startDebugEventStream", html)
        self.assertIn("applyDebugStreamSnapshot", html)
        self.assertIn("resetMobileWearableIngressProjection", html)
        self.assertIn("confirm_mobile_wearable_ingress_debug_reset: true", html)
        self.assertIn("renderMobileWearableIngress(selectedMapEvent())", html)
        self.assertNotIn(
            'await loadDebugSurface();\n        setText("loadStatus", "Mobile/wearable ingress counters reset',
            html,
        )
        self.assertIn("mergeDebugEvents(debugPageState.chronologicalEvents || [], streamEvents)", html)
        self.assertIn("stateWithProjectedEvents(state || {}, timelinePayload)", html)
        self.assertIn("if (streamEvents.length)", html)
        self.assertIn("renderEvents(timelineEvents)", html)
        self.assertNotIn("mobileIngressRefreshButton", html)
        self.assertNotIn("mobileIngressRecordList", html)
        self.assertNotIn("function ingressRecordItem", html)
        self.assertNotIn("records.slice().reverse().map", html)
        self.assertNotIn("window.setInterval", html)
        self.assertIn("raw payload stays in evidence JSONL", html)
        self.assertIn("不顯示 raw sensor values", html)
        self.assertIn("credential_value_exposed", html)

    def test_static_debug_page_has_debug_projection_clear_button(self):
        html = PAGE_PATH.read_text(encoding="utf-8")
        top_header = html[
            html.index("<header>") : html.index("</header>") + len("</header>")
        ]
        timeline_header = html[
            html.index('<article class="panel timeline-panel">') :
            html.index('<div class="panel-body" aria-label="Runtime event timeline">')
        ]

        self.assertIn('id="debugClearButton"', html)
        self.assertNotIn('id="debugClearButton"', top_header)
        self.assertIn('id="debugClearButton"', timeline_header)
        self.assertIn(">清 Timeline</button>", timeline_header)
        self.assertIn(".panel-head .debug-button", html)
        self.assertIn("Clear projected debug events only", html)
        self.assertIn("clearDebugProjection", html)
        self.assertIn("bindDebugControls", html)
        self.assertIn('postJson("/debug/clear"', html)
        self.assertIn("confirm_debug_projection_clear: true", html)
        self.assertIn("Runtime, safety, incidents, outbound, Brain, and hardware state will not be changed.", html)
        self.assertIn("Debug projection cleared. Awaiting incoming replay events.", html)

    def test_static_debug_page_links_timeline_selection_to_runtime_map(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="runtimeMap"', html)
        self.assertIn("mapTargetsForEvent", html)
        self.assertIn("highlightMapForEvent", html)
        self.assertIn("selectTimelineNode", html)
        self.assertIn("data-map-ref", html)
        self.assertIn('data-map-hover", "true"', html)
        self.assertIn("data-map-hover-title", html)
        self.assertIn("data-map-hover-summary", html)
        self.assertIn("data-map-feature-kind", html)
        self.assertIn("function mapFeatureKind", html)
        self.assertIn("function mapFeatureTitle", html)
        self.assertIn("function mapFeatureSummary", html)
        self.assertIn("function mapHoverTooltip", html)
        self.assertIn("function handleMapHoverPointerMove", html)
        self.assertIn('runtimeMap.addEventListener("pointermove", handleMapHoverPointerMove)', html)
        self.assertIn('runtimeMap.addEventListener("pointerleave", hideMapHoverTooltip)', html)
        self.assertIn("const MAP_LAYER_RANKS", html)
        self.assertIn("function orderMapLayerGroups()", html)
        self.assertIn(".map-label-overlay {\n      position: absolute;\n      inset: 0;\n      pointer-events: none;\n      overflow: hidden;\n      z-index: 40;", html)
        self.assertIn("function handleMapKeyboardPan(event)", html)
        self.assertIn("mapKeyboardActive: false", html)
        self.assertIn("function activateMapKeyboardPan()", html)
        self.assertIn('document.addEventListener("keydown", handleMapKeyboardPan)', html)
        self.assertIn('document.addEventListener("pointerdown", deactivateMapKeyboardPanOutside)', html)
        self.assertIn('runtimeMap.setAttribute("tabindex", "0")', html)
        self.assertIn(
            "focusMapBox(mapBoxForEvent(event), event, {preserveZoom: options.preserveZoom !== false})",
            html,
        )
        self.assertIn("if (options.preserveZoom === false)", html)
        self.assertIn("clickTarget", html)
        self.assertIn("function eventForMapTarget(target)", html)
        self.assertIn('const genericRefs = new Set(["runtime", "imagery", "osm", "terrain"]);', html)
        self.assertIn("const preferredRefs = rawRefs.filter(ref => !genericRefs.has(ref));", html)
        self.assertIn("function selectTimelineForMapTarget(target)", html)
        self.assertIn('node.closest("details.timeline-group-details")?.setAttribute("open", "")', html)
        self.assertIn("document.querySelector(`.timeline-group-details ${eventSelector}`) || document.querySelector(eventSelector)", html)
        self.assertIn("selectTimelineNode(event, index, {node, focus: true, expandGroup: true})", html)
        self.assertIn("selectTimelineForMapTarget(selection.clickTarget)", html)
        self.assertIn(".map-hover-tooltip", html)
        self.assertIn(".map-hover-tooltip.is-visible", html)
        self.assertIn(".map-hover-tooltip {\n      position: absolute;\n      z-index: 10000;", html)
        self.assertIn("debugPageState.hoveredMapTarget !== target", html)
        self.assertIn("${kind}: ${title}", html)
        self.assertIn("pointer-events: visiblePainted", html)
        self.assertIn("map-highlight", html)
        self.assertIn("map-panel", html)
        self.assertIn('aria-label="Split runtime map panel"', html)
        self.assertIn("details-column", html)
        self.assertIn("timeline-column", html)
        self.assertIn("height: 100vh", html)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", html)
        self.assertIn("grid-template-columns: minmax(300px, 360px) minmax(640px, 1fr) minmax(360px, 460px)", html)
        self.assertIn('"timeline map details"', html)
        self.assertIn('"timeline map assistant"', html)
        self.assertIn("grid-area: timeline", html)
        self.assertIn("grid-area: map", html)
        self.assertIn("grid-area: details", html)
        self.assertIn("grid-area: assistant", html)
        self.assertIn("position: relative;\n      z-index: 1;", html)
        self.assertIn("position: relative;\n      z-index: 20;", html)
        self.assertIn("position: fixed", html)
        self.assertIn("max-height: calc(100vh - 140px)", html)
        self.assertNotIn("map-dock", html)
        self.assertIn('role="button"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('aria-label="chilai_nanhua_day1 debug evidence map"', html)
        self.assertIn("background: #111820;", html)
        self.assertIn("renderDebugEvidenceMap", html)
        self.assertIn("reference-track", html)
        self.assertIn("overpass-corridor", html)
        self.assertIn('aria-label="Map view controls"', html)
        self.assertIn('id="zoomIn"', html)
        self.assertIn('id="zoomOut"', html)
        self.assertIn('id="fitRoute"', html)
        self.assertIn('id="boxZoomMode"', html)
        self.assertIn('id="zoomLevel"', html)
        self.assertIn('aria-label="Rectangle drag zoom"', html)
        self.assertIn("function updateMapZoomIndicator", html)
        self.assertIn('id="panUp"', html)
        self.assertIn('id="panDown"', html)
        self.assertIn('id="panLeft"', html)
        self.assertIn('id="panRight"', html)
        self.assertIn('id="layerControl" title="Show layer controls" aria-label="Layer controls"', html)
        self.assertIn('id="layerEnabledCount"', html)
        self.assertIn('class="layer-preset-row" aria-label="Layer presets"', html)
        self.assertIn('data-layer-preset="risk-review"', html)
        self.assertIn('data-layer-preset="mcp-review"', html)
        self.assertIn('data-layer-preset="route-clean"', html)
        self.assertIn('data-layer-preset="debug-replay"', html)
        self.assertIn('data-layer-preset="raster-check"', html)
        self.assertIn('<input type="checkbox" data-layer="imagery"> Imagery', html)
        self.assertIn('<input type="checkbox" data-layer="rudy-twmap" checked> Rudy+TW', html)
        self.assertIn('class="layer-advanced"', html)
        self.assertIn("Advanced layers", html)
        self.assertIn('data-layer="boss-points" checked> Boss</label>', html)
        self.assertIn(".boss-point", html)
        self.assertIn("projection.boss_points?.boss_points", html)
        self.assertIn("item?.boss_point_id || item?.source_mcp_id || item?.source_candidate_id", html)
        self.assertIn("function isBossPoint(item)", html)
        self.assertIn("function bossDisplayText(item)", html)
        self.assertIn("function bossSummaryText(item)", html)
        self.assertIn("bossDisplayText(item)", html)
        self.assertIn("if (isBossPoint(item)) return bossSummaryText(item);", html)
        self.assertIn('"boss-points",', html)
        self.assertIn('String(point.challenge_fit?.band || "").includes("not_ready")', html)
        self.assertIn("function mapStrokeWidthPx(node, scale)", html)
        self.assertIn("function mapMarkerRadiusPx(circle, scale, baseRadius)", html)
        self.assertIn(
            'circle.classList.contains("mcp-candidate") || circle.classList.contains("boss-point")',
            html,
        )
        self.assertIn(
            'node.style.setProperty("stroke-width", `${strokeWidth.toFixed(2)}px`, priority)',
            html,
        )
        self.assertIn(".tool-button {\n      min-height: 28px;", html)
        self.assertIn(".tool-button.compact {\n      min-width: 28px;", html)
        self.assertIn("background: #111827;\n      color: #f8fafc;", html)
        self.assertIn(".filters label {\n      display: inline-flex;\n      align-items: center;\n      gap: 3px;\n      min-height: 28px;", html)
        self.assertIn(".layer-menu summary {\n      min-height: 28px;", html)
        self.assertIn("z-index: 80;", html)
        self.assertIn("z-index: 90;", html)
        self.assertIn("function bindLayerMenuDismiss()", html)
        self.assertIn("function closeLayerMenus(exceptMenu = null)", html)
        self.assertIn("function layerMenuFromEvent(event)", html)
        self.assertIn("event.composedPath()", html)
        self.assertIn('window.__scoutLayerMenuDismissVersion === "v2"', html)
        self.assertNotIn("window.__scoutLayerMenuDismissBound", html)
        self.assertIn('["pointerdown", "mousedown", "touchstart", "click"].forEach(eventName =>', html)
        self.assertIn("[window, document, document.documentElement, document.body]", html)
        self.assertIn("target.addEventListener(eventName, dismissLayerMenusForEvent, {capture: true, passive: true});", html)
        self.assertIn('document.addEventListener("focusin", dismissLayerMenusForEvent, {capture: true});', html)
        self.assertIn('menu.addEventListener("toggle", () =>', html)
        self.assertIn("if (menu.open) closeLayerMenus(menu);", html)
        self.assertIn('if (event.key === "Escape") closeLayerMenus();', html)
        self.assertIn('document.querySelectorAll(".layer-menu[open]")', html)
        self.assertIn(".layer-preset-button {\n      min-height: 28px;\n      display: flex;\n      align-items: center;", html)
        self.assertIn(".layer-advanced summary {\n      border: 0;\n      background: transparent;\n      padding: 4px 0 6px;\n      min-height: 28px;", html)
        self.assertIn("width: max-content;\n      max-width: 100%;\n      box-sizing: border-box;", html)
        self.assertIn(".layer-menu-panel {\n        position: fixed;\n        top: 120px;\n        left: 12px;\n        right: 12px;\n        width: auto;", html)
        self.assertIn(".map-pan-controls .tool-button {\n      min-height: 28px;\n      min-width: 28px;", html)
        self.assertIn(".tab {\n      min-height: 28px;", html)
        self.assertIn("body {\n        height: auto;\n        min-height: 100vh;\n        overflow: auto;", html)
        self.assertIn(".shell {\n        grid-template-rows: auto auto;\n        height: auto;\n        min-height: 100vh;", html)
        responsive_main_css = html.split("@media (max-width: 1120px)", 1)[1].split(".column", 1)[0]
        self.assertIn('"map"\n          "details"\n          "timeline"\n          "assistant";', responsive_main_css)
        self.assertNotIn('"map"\n          "timeline"\n          "details"\n          "assistant";', responsive_main_css)
        self.assertNotIn('"timeline"\n          "map"\n          "details"\n          "assistant";', responsive_main_css)
        self.assertIn(".details-panel,\n      .map-panel {\n        display: block;", html)
        self.assertIn(".map-panel {\n        min-height: 0;", html)
        self.assertIn(".map-panel #runtimeMap {\n        height: auto;\n        min-height: 0;\n        aspect-ratio: 1000 / 720;", html)
        self.assertNotIn("height: clamp(260px, 60vh, 520px);", html)
        self.assertIn("display: block;\n        height: auto;", html)
        self.assertIn(".details-panel .panel-head,\n      .map-panel .panel-head", html)
        self.assertIn(".panel-head > .pill {\n      flex: 0 1 auto;\n      min-width: 0;", html)
        self.assertIn(".panel-title {\n      display: grid;\n      gap: 1px;\n      flex: 1 1 auto;\n      min-width: 0;", html)
        self.assertIn("align-items: flex-start;\n        flex-wrap: wrap;\n        gap: 8px;", html)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(92px, 1fr));", html)
        self.assertIn("#runtimeProfile,\n      #selectedMapTarget", html)
        self.assertIn(".map-panel .panel-body {\n        display: block;\n        overflow: visible;", html)
        self.assertEqual(html.count('id="safetyLevel"'), 1)
        self.assertIn("function applyLayerPreset", html)
        self.assertIn("function syncLayerPresetButtons", html)
        self.assertIn("availablePresetLayerSet", html)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", html)
        self.assertIn(".map-pan-controls", html)
        self.assertIn("display: inline-flex;", html)
        self.assertIn(".pan-left { order: 1; }", html)
        self.assertIn(".pan-right { order: 4; }", html)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto auto", html)
        self.assertIn(".tab-panel-head .hint", html)
        tab_hint_css = html.split(".tab-panel-head .hint", 1)[1].split("}", 1)[0]
        self.assertIn("white-space: normal;", tab_hint_css)
        self.assertIn("text-overflow: clip;", tab_hint_css)
        self.assertIn("overflow-wrap: anywhere;", tab_hint_css)
        self.assertIn(".map-toolbar", html)
        self.assertIn("display: flex;", html)
        self.assertIn(".control-group-header", html)
        self.assertIn("display: none;", html)
        self.assertIn("function mapViewBox", html)
        self.assertIn("function updateLayers", html)
        self.assertIn("function panMap", html)
        self.assertIn("function zoomMap", html)
        self.assertIn("MAP_ZOOM_STEP_FACTOR = 1.25", html)
        self.assertIn(
            "Math.max(1, Math.min(MAP_MAX_ZOOM, debugPageState.zoom / factor))",
            html,
        )
        self.assertIn("function resetMapView", html)
        self.assertIn("OSM_TILE_URL_TEMPLATE", html)
        self.assertIn("OSM_PUBLIC_TILE_URL_TEMPLATE", html)
        self.assertIn("OSM_LOCAL_TILE_URL_TEMPLATE", html)
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", html)
        self.assertIn("/admin/tiles/osm/{z}/{x}/{y}.png", html)
        self.assertIn("/admin/tiles/osm/{z}/{x}/{y}.png?fallback=transparent", html)
        self.assertIn("const OSM_TARGET_ZOOM = 17", html)
        self.assertIn("const OSM_MAX_TILES = 64", html)
        self.assertIn("const RASTER_MAX_TILES = 64", html)
        self.assertIn("RASTER_TILE_CACHE_BUST", html)
        self.assertIn("function rasterTileCacheBustedUrl", html)
        self.assertIn("function osmTileTemplate", html)
        self.assertIn("function isLocalOsmTileMode", html)
        self.assertIn('params.get("osmSource")', html)
        self.assertIn('params.get("tiles")', html)
        self.assertIn(
            'return requested === "public" ? OSM_PUBLIC_TILE_URL_TEMPLATE : OSM_LOCAL_TILE_URL_TEMPLATE',
            html,
        )
        self.assertIn("function rasterZoomRangeFor", html)
        self.assertIn("function chooseRasterZoom", html)
        self.assertIn("function rasterTileCoverage", html)
        self.assertIn('data-layer="terrain" checked> Terrain', html)
        self.assertIn('data-layer="cwa-qpf"', html)
        self.assertIn('data-layer="cwa-weather"', html)
        self.assertIn(".environment-extent", html)
        self.assertIn("function renderEnvironmentExtent", html)
        self.assertIn("function environmentEvidenceSummary", html)
        self.assertIn("SMAP L4 route bbox mean", html)
        self.assertIn("candidate-only context; not runtime safety truth", html)
        self.assertIn("renderEnvironmentExtent(cwaQpfGroup", html)
        self.assertIn(".terrain-raster-overlay", html)
        self.assertIn("const RASTER_BASEMAP_LAYER_IDS", html)
        self.assertIn("function layerInputChecked(layerId)", html)
        self.assertIn("function syncRasterBasemapLayers", html)
        self.assertIn("syncRasterBasemapLayers();", html)
        self.assertIn("if (!layerInputChecked(kind)) return;", html)
        self.assertIn("RASTER_BASEMAP_LAYER_IDS.has(input.dataset.layer)", html)
        self.assertIn("function visibleBoundsForProjection", html)
        self.assertIn("function mapViewportBox", html)
        self.assertIn("const coverageBounds = visibleBoundsForProjection(projection) || bounds", html)
        self.assertIn("function attachTileFallback", html)
        self.assertIn("function terrainRasterOverlays", html)
        self.assertIn("function renderTerrainBitmapOverlays", html)
        self.assertIn("pretrip_terrain_visualization_bitmap_overlay", html)
        self.assertIn("const tiles = isOsm ? tileCoverage(coverageBounds) : rasterTileCoverage(projection, coverageBounds, null, kind)", html)
        self.assertIn("if (isOsm && !isLocalOsmTileMode())", html)
        self.assertIn("const pad = MAP_VISUAL_PADDING;", html)
        self.assertNotIn("const pad = MAP_VISUAL_PADDING / debugPageState.zoom", html)
        self.assertLess(
            html.index('data-layer-group": "imagery"'),
            html.index('data-layer-group": "osm"'),
        )
        self.assertLess(
            html.index('data-layer-group": "osm"'),
            html.index('data-layer-group": "terrain"'),
        )
        self.assertLess(
            html.index('data-layer-group": "terrain"'),
            html.index('data-layer-group": "overpass"'),
        )
        self.assertIn('"data-risk-layer": "baseline"', html)
        self.assertIn('"data-risk-layer": "calibrated"', html)
        self.assertIn('"data-risk-layer": "delta"', html)

    def test_static_debug_page_makes_timeline_body_touchpad_scrollable(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("timeline-panel", html)
        self.assertIn(".timeline-panel .panel-body", html)
        self.assertIn("overflow-y: auto", html)
        self.assertIn("-webkit-overflow-scrolling: touch", html)
        self.assertIn("overscroll-behavior: contain", html)
        self.assertIn('aria-label="Runtime event timeline"', html)

    def test_static_debug_page_has_short_human_hints(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("先看這裡：預設是最新狀態；點 timeline 後切到該點。", html)
        self.assertIn("runtime event 的發生順序；右上 L0->L2 表示安全等級變化。", html)
        self.assertIn("Phase 1 判出需要注意的安全事件。", html)
        self.assertIn("Scout 準備送出的 mock 訊息，可看狀態但不會真的發送。", html)
        self.assertIn("LABEL_HINTS", html)
        self.assertIn("EVENT_HINTS", html)

    def test_static_debug_page_keeps_assistant_question_buttons_compact(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("assistant-drawer", html)
        self.assertIn('<details class="panel assistant-drawer" open>', html)
        self.assertIn('aria-label="Open read-only debug assistant"', html)
        self.assertIn('id="assistantQuestionInput"', html)
        self.assertIn('id="assistantAskButton"', html)
        self.assertIn(">Why L2?</button>", html)
        self.assertIn(">Sources?</button>", html)
        self.assertIn(">Missing?</button>", html)
        assistant_panel_css = html.split(".assistant-drawer .assistant-panel", 1)[1].split(".assistant-body", 1)[0]
        self.assertIn("height: 100%;", assistant_panel_css)
        self.assertIn("min-height: 0;", assistant_panel_css)
        self.assertIn("overflow: hidden;", assistant_panel_css)
        assistant_body_css = html.split(".assistant-body", 1)[1].split(".assistant-grid", 1)[0]
        self.assertIn("max-height: none;", assistant_body_css)
        self.assertIn("overflow-y: auto;", assistant_body_css)
        self.assertIn("function assistantQuestionLabel", html)
        self.assertIn('title="${escapeHtml(question)}"', html)

    def test_static_debug_page_links_timeline_selection_to_l0_l4_snapshot(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="stateSelectionContext"', html)
        self.assertIn("timelineSnapshotForEvent", html)
        self.assertIn("renderSafetySnapshot", html)
        self.assertIn("safetyLevelForEvent", html)
        self.assertIn("function readableStateToken", html)
        self.assertIn('raw.replace(/^(L[0-4])_/, "$1 · ").replace(/_/g, " ")', html)
        self.assertIn('setReadableStateToken("safetyLevel", snapshot.safetyLevel, "unknown")', html)
        self.assertIn('setReadableStateToken("latestTransition", snapshot.latestTransition, "none")', html)
        self.assertIn("node.title = raw;", html)
        metric_strong_css = html.split(".metric strong", 1)[1].split(".levels", 1)[0]
        self.assertIn("line-height: 1.22;", metric_strong_css)
        self.assertIn("overflow-wrap: break-word;", metric_strong_css)
        self.assertIn("word-break: normal;", metric_strong_css)
        self.assertIn("debugPageState.chronologicalEvents", html)
        self.assertIn("debugPageState.timelineGroups", html)
        self.assertIn("顯示 timeline #", html)
        self.assertIn("selectTimelineNode(event, index, {node})", html)

    def test_static_debug_page_scopes_runtime_detail_tabs_to_selected_timeline_node(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("timelineWindowForEvent", html)
        self.assertIn("renderSelectedDetails", html)
        self.assertIn("renderProviderDetails", html)
        self.assertIn("renderHardwareReadiness", html)
        self.assertIn("renderIncidentDetails", html)
        self.assertIn("renderSkillDetails", html)
        self.assertIn("renderMessageDetails", html)
        self.assertIn('id="providerSelectionContext"', html)
        self.assertIn('id="hardwareSelectionContext"', html)
        self.assertIn('id="incidentSelectionContext"', html)
        self.assertIn('id="skillSelectionContext"', html)
        self.assertIn('id="messageSelectionContext"', html)
        self.assertIn('id="boundarySelectionContext"', html)
        self.assertIn("No incident or bridge events reached at this timeline node.", html)
        self.assertIn("No outbound mock messages reached at this timeline node.", html)

    def test_static_debug_page_reads_hardware_readiness_context_for_hardware_tab(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="tab-hardware"', html)
        self.assertIn('id="panel-hardware"', html)
        self.assertIn('const HARDWARE_READINESS_CONTEXT_PATH = "/admin/hardware-readiness/context"', html)
        self.assertIn("loadHardwareReadinessContext", html)
        self.assertIn("debugPageState.hardwareReadiness", html)
        self.assertIn('id="hardwareProviderCount"', html)
        self.assertIn('id="hardwareInterfaceCount"', html)
        self.assertIn('id="hardwareDegradedCount"', html)
        self.assertIn('id="hardwareDebugEventCount"', html)
        self.assertIn('id="hardwareMockQueueCount"', html)
        self.assertIn('id="hardwareInterfaceList"', html)
        self.assertIn('id="hardwareProviderList"', html)
        self.assertIn('id="hardwareBoundaryList"', html)
        self.assertIn("hardwareInterfaceItem", html)
        self.assertIn("hardwareDetailGrid", html)
        self.assertIn("hardwareLineChips", html)
        self.assertIn("hardware-line-chip-row", html)
        self.assertIn("Object.entries(interfaceItem.details || {}).slice(0, 5)", html)
        self.assertIn('["device", text(device.id || device.label || "usb")]', html)
        self.assertIn('["rw lines", writable.length]', html)
        self.assertIn('["advanced", advanced.map', html)
        self.assertIn('["gpioset", boundary.gpioset_command_enabled ? "enabled" : "disabled"]', html)
        self.assertIn('["wiring", boundary.wiring_manifest_confirmed ? "confirmed" : "not confirmed"]', html)
        self.assertIn('["drive gate", "wiring manifest required"]', html)
        self.assertIn("GPIO 腳位狀態", html)
        self.assertIn("GPIO/I2C/I2S/TTS/Bluetooth/UART/power/GNSS/IMU/USB/SSD inventory", html)
        self.assertIn("debug 頁不應該直接拉 GPIO high/low 或控制硬體", html)
        self.assertIn("read_only: true", html)
        self.assertIn("provider_control_allowed: false", html)

    def test_static_debug_page_renders_l_state_badge_on_timeline_nodes(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("timeline-meta", html)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto;", html)
        self.assertIn(".timeline-node > .hint,\n    .timeline-node > .summary", html)
        self.assertIn("-webkit-line-clamp: 2;", html)
        self.assertIn(".timeline-node > .summary.mono", html)
        self.assertIn("text-overflow: ellipsis;", html)
        self.assertIn(".timeline-node.timeline-child > .hint", html)
        self.assertIn("-webkit-line-clamp: 1;", html)
        self.assertIn(".timeline-node.is-selected > .summary:not(.mono)", html)
        self.assertIn("-webkit-line-clamp: 3;", html)
        self.assertIn(".gis-perception-cp", html)
        self.assertIn("specificMapTargets", html)
        self.assertIn("if (!isPointFocusEvent(event)) clampMapPan();", html)
        self.assertIn("function zoomMap(direction)", html)
        zoom_body = html.split("function zoomMap(direction)", 1)[1].split("function resetMapView", 1)[0]
        self.assertNotIn("centerX - MAP_WIDTH / 2", zoom_body)
        self.assertNotIn("centerY - MAP_HEIGHT / 2", zoom_body)
        self.assertIn("FOCUS_POINT_VIEWPORT_M = 50", html)
        self.assertIn("const widthZoom = widthMeters / FOCUS_POINT_VIEWPORT_M;", html)
        self.assertIn("const heightZoom = heightMeters / FOCUS_POINT_VIEWPORT_M;", html)
        self.assertIn("POINT_LABEL_VIEWPORT_M = 50", html)
        self.assertIn("POINT_LABEL_FONT_PX = 4", html)
        self.assertIn("POINT_LABEL_STROKE_PX = 0.6", html)
        self.assertIn("POINT_LABEL_OFFSET_PX = 3", html)
        self.assertIn("function updateScaleBar", html)
        self.assertIn('"data-ui-overlay": "scale-bar"', html)
        self.assertIn('aria-label": "Map scale bar"', html)
        self.assertIn("niceScaleMeters", html)
        self.assertIn("formatScaleMeters", html)
        self.assertIn("function readablePointLabel", html)
        self.assertIn('if (text.includes("/"))', html)
        self.assertIn("function compactPointLabel", html)
        self.assertIn("function pointLabelUnitsPerScreenPixel", html)
        self.assertIn(".map-label-overlay", html)
        self.assertIn("function appendMapOverlayLabel", html)
        self.assertIn('node.appendChild(document.createTextNode("\\n"));', html)
        self.assertIn("function placeMapOverlayNode", html)
        self.assertIn("overlay?.replaceChildren();", html)
        self.assertIn('label.classList.add("is-hidden");', html)
        self.assertIn('"data-label-title": pointLabelTitle(item, label)', html)
        self.assertIn('"data-label-summary": pointLabelSummary(item)', html)
        self.assertIn("item?.map_label", html)
        self.assertIn("item?.display_label", html)
        self.assertIn("gis_cp_cluster\\.", html)
        self.assertIn("function updatePointLabels", html)
        self.assertIn('"data-label-layer"', html)
        self.assertIn('"data-label-anchor-x"', html)
        self.assertIn('"data-label-anchor-y"', html)
        self.assertIn('label.setAttribute("font-size", (POINT_LABEL_FONT_PX * unitsPerPx).toFixed(3));', html)
        self.assertIn('label.setAttribute("stroke-width", (POINT_LABEL_STROKE_PX * unitsPerPx).toFixed(3));', html)
        self.assertIn("anchorX + POINT_LABEL_OFFSET_PX * unitsPerPx", html)
        self.assertIn("anchorY - POINT_LABEL_OFFSET_PX * unitsPerPx", html)
        self.assertIn("currentViewportRangeM() <= POINT_LABEL_VIEWPORT_M", html)
        self.assertIn("layerEnabled && (focused || showByZoom)", html)
        self.assertIn("function zoomMapOutFromBox", html)
        zoom_out_body = html.split("function zoomMapOutFromBox", 1)[1].split("function isZoomOutDrag", 1)[0]
        self.assertNotIn("box.x + box.width / 2 - MAP_WIDTH / 2", zoom_out_body)
        self.assertNotIn("box.y + box.height / 2 - MAP_HEIGHT / 2", zoom_out_body)
        self.assertIn('node.addEventListener("click", () => {\n          selectTimelineNode(event, index, {node});\n          focusMapForEvent(event, {label: false});', html)
        self.assertIn('node.addEventListener("dblclick", (mouseEvent) => {\n          mouseEvent.preventDefault();\n          selectTimelineNode(event, index, {node});\n          focusMapForEvent(event, {label: true});', html)
        self.assertIn("selectTimelineNode(event, index, {node});\n            focusMapForEvent(event, {label: false});\n            return;", html)
        self.assertIn('title="${escapeHtml(title)}"', html)
        self.assertIn('<p class="hint" title="${escapeHtml(hintForEvent(event))}">', html)
        self.assertIn('<p class="summary" title="${escapeHtml(summary)}">', html)
        self.assertIn('<p class="summary mono" title="${escapeHtml(event.timestamp)} ${escapeHtml(event.subject_ref || "")}">', html)
        self.assertIn("level-badge", html)
        self.assertIn("levelBadgeForEvent", html)
        self.assertIn("levelBadgeClassForEvent", html)
        self.assertIn("levelToken", html)
        self.assertIn("L0->L2", html)
        self.assertIn('aria-label="L state at this timeline node"', html)

    def test_static_debug_page_groups_dense_timeline_events_but_keeps_child_targets(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("function timelineGroupKey", html)
        self.assertIn("DENSE_TIMELINE_GROUP_KINDS", html)
        self.assertIn('"checkpoint_detected", "route_progress_evaluated", "gis_perception_checkpoint_projected"', html)
        self.assertIn('route_progress_evaluated: ["route-progress", "route", "segment"]', html)
        self.assertIn('subject.includes("segment") && !payload.segment_id && !specificMapTargets.length', html)
        self.assertIn("if (DENSE_TIMELINE_GROUP_KINDS.has(kind)) return kind;", html)
        self.assertIn("function buildTimelineGroups", html)
        self.assertIn("function renderTimelineGroup", html)
        self.assertIn("function renderTimelineEventNode", html)
        self.assertIn("timeline-group", html)
        self.assertIn("timeline-group-summary", html)
        self.assertIn("timeline-group-summary timeline-group-node", html)
        self.assertIn(".timeline-group-summary .item-line {\n      grid-template-columns: minmax(0, 1fr);", html)
        self.assertIn(".timeline-group-summary h3 {\n      white-space: nowrap;", html)
        self.assertIn(".timeline-group-summary .timeline-meta {\n      display: flex;", html)
        self.assertIn(".timeline-group-summary > .hint,\n    .timeline-group-summary > .summary.mono {\n      display: none;", html)
        self.assertIn(".timeline-group-summary > .summary:not(.mono) {\n      -webkit-line-clamp: 1;", html)
        mobile_css = html.split("@media (max-width: 1120px)", 1)[1].split("</style>", 1)[0]
        self.assertIn(".timeline-node > .hint,\n      .timeline-node > .summary,", mobile_css)
        self.assertIn("white-space: normal;\n        overflow: visible;\n        text-overflow: clip;", mobile_css)
        self.assertIn("-webkit-line-clamp: unset;\n        overflow-wrap: anywhere;", mobile_css)
        self.assertIn(".timeline-group-summary h3 {\n        white-space: normal;", mobile_css)
        self.assertIn(".assistant-list,\n      .assistant-list li {\n        min-width: 0;", mobile_css)
        self.assertIn(".assistant-list li {\n        word-break: break-word;", mobile_css)
        self.assertIn(".assistant-body {\n        overflow-x: hidden;", mobile_css)
        self.assertIn(".pill,\n      .assistant-body .pill {\n        white-space: normal;", mobile_css)
        self.assertIn("timeline-group-count", html)
        self.assertIn("timeline-group-details", html)
        self.assertIn(".timeline-group-details summary {\n      cursor: pointer;\n      display: inline-flex;\n      align-items: center;\n      min-height: 24px;", html)
        self.assertIn(".timeline-group-details:not([open]) > .timeline-group-children {\n      display: none;", html)
        self.assertIn("timeline-child", html)
        self.assertIn('data-event-id="${escapeHtml(event.event_id || "")}"', html)
        self.assertIn('document.getElementById("eventCount").textContent = `${events.length} events / ${timelineGroups.length} groups`;', html)
        self.assertIn("debugPageState.timelineGroups = timelineGroups", html)
        self.assertIn("if (group.count > 1) return [group];", html)

    def test_static_debug_page_renders_physio_timeline_projection_contract(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "<title>Scout Phase 3.5 Runtime Debug | 2026-06-23 12:13:54 CST</title>",
            html,
        )
        self.assertIn(
            '<h1>Runtime Debug <span class="title-timestamp">2026-06-23 12:13:54 CST</span></h1>',
            html,
        )
        self.assertIn(
            'physiologic_gate_window: ["skill", "route-progress", "segment"]',
            html,
        )
        self.assertIn(
            'physiologic_gate_safety_event: ["skill", "safety", "route-progress", "segment"]',
            html,
        )
        self.assertIn(
            'runtime_safety_reducer_dry_run: ["skill", "safety", "route-progress", "segment"]',
            html,
        )
        self.assertIn(
            'runtime_safety_phase1_adapter_result: ["skill", "safety"]',
            html,
        )
        self.assertIn(
            'physiologic_gate_window: "生理壓力 gate 的 15 分鐘窗口 projection；不是醫療診斷或 safety truth。"',
            html,
        )
        self.assertIn(
            'runtime_safety_reducer_dry_run: "多 gate safety reducer dry-run；顯示候選 L_n，不直接改 Phase 1。"',
            html,
        )
        self.assertIn(
            'runtime_safety_phase1_adapter_result: "Phase 1 adapter candidate；需 feature flag 與 review，這裡不呼叫 safety mutation endpoint。"',
            html,
        )
        self.assertIn(
            'const projectedMapRefs = Array.isArray(event?.map_refs) ? event.map_refs.filter(Boolean) : [];',
            html,
        )
        self.assertIn('projectedMapRefs.forEach(ref => refs.add(ref));', html)
        self.assertIn('"physiologic_gate_window"', html)
        self.assertIn('(event.kind || "").startsWith("physiologic_")', html)
        self.assertIn('(event.kind || "").startsWith("runtime_safety_")', html)
        self.assertIn('id="physiologicGateCount"', html)
        self.assertIn('id="runtimeSafetyReducerCount"', html)
        self.assertIn('document.getElementById("physiologicGateCount").textContent = String(physiologicEvents.length);', html)
        self.assertIn('document.getElementById("runtimeSafetyReducerCount").textContent = String(runtimeSafetyReducerEvents.length);', html)
        self.assertIn("Show ${escapeHtml(group.count)} events", html)
        self.assertIn("function selectorValue", html)
        self.assertIn("function eventByTimelineNode", html)
        self.assertIn("function eventIndexByTimelineNode", html)
        self.assertIn("node?.dataset?.eventId", html)
        self.assertIn("options.node", html)

    def test_static_debug_page_has_visible_focus_and_roving_keyboard_navigation(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn(".tab:focus-visible", html)
        self.assertIn(".timeline-node:focus-visible", html)
        self.assertIn("outline: 2px solid var(--info)", html)
        self.assertIn('aria-orientation="horizontal"', html)
        self.assertIn("moveTimelineFocus", html)
        self.assertIn('"ArrowRight"', html)
        self.assertIn('"ArrowLeft"', html)
        self.assertIn('"ArrowDown"', html)
        self.assertIn('"ArrowUp"', html)
        self.assertIn('"Home"', html)
        self.assertIn('"End"', html)
        self.assertIn('aria-current="false"', html)
        self.assertIn('candidate.setAttribute("aria-current"', html)
        self.assertIn("candidate.tabIndex = isSelected ? 0 : -1", html)

    def test_static_debug_page_deep_links_selected_tab_and_event_state(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("DEBUG_TAB_IDS", html)
        self.assertIn("readUrlSelection", html)
        self.assertIn("writeUrlSelection", html)
        self.assertIn("URLSearchParams(window.location.search)", html)
        self.assertIn('params.get("tab")', html)
        self.assertIn('params.get("event")', html)
        self.assertIn('url.searchParams.set("tab"', html)
        self.assertIn('url.searchParams.set("event"', html)
        self.assertIn("window.history.replaceState", html)
        self.assertIn("initialUrlSelection", html)
        self.assertIn("debugPageState.selectedTabId", html)
        self.assertIn("debugPageState.selectedEventId", html)

    def test_static_debug_page_fetches_only_get_debug_read_endpoints(self):
        html = PAGE_PATH.read_text(encoding="utf-8")
        shared_script = ASSISTANT_UI_SCRIPT.read_text(encoding="utf-8")
        fetch_targets = set(re.findall(r'fetchJson\("([^"]+)"\)', html))

        self.assertIn(
            "/admin/pretrip/projects/chilai_nanhua_day1/debug-projection",
            html,
        )
        self.assertIn(
            "/admin/pretrip/projects/chilai_nanhua_day1/debug-projection-events",
            html,
        )
        self.assertIn('const PRETRIP_PROJECT_ID = "chilai_nanhua_day1"', html)
        self.assertIn("PRETRIP_DEBUG_PROJECTION_PATH", html)
        self.assertIn("PRETRIP_DEBUG_PROJECTION_EVENTS_PATH", html)
        self.assertIn("loadProjectedDebugEventPayload", html)
        self.assertIn("stateWithProjectedEvents", html)
        self.assertIn("loadRuntimeDebugEventsPayload", html)
        self.assertIn("mergeDebugEvents", html)
        self.assertIn("agent_tool_count", html)
        self.assertEqual(
            {target.split("?", 1)[0] for target in fetch_targets},
            ALLOWED_DEBUG_ENDPOINTS,
        )
        self.assertNotIn("/safety/", html)
        post_targets = set(re.findall(r'postJson\("([^"]+)"', html))
        self.assertEqual(
            post_targets,
            {
                "/assistant/query",
                "/debug/clear",
                "/debug/mobile-wearable/ingress/reset",
            },
        )
        self.assertIn("scout-assistant-ui.js", html)
        self.assertEqual(shared_script.count('method: "POST"'), 1)
        self.assertIn("body: JSON.stringify(payload)", shared_script)

    def test_static_debug_page_has_no_mutation_methods_or_controls(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        for method in MUTATION_METHODS - {"POST"}:
            self.assertIsNone(
                re.search(rf"\b{method}\b", html),
                msg=f"Static debug page must not reference {method}.",
            )

        self.assertIn('id="assistantAskButton"', html)
        self.assertIn('id="assistantQuestionInput"', html)
        for tag in ("form", "select"):
            self.assertIsNone(
                re.search(rf"<\s*{tag}\b", html, flags=re.IGNORECASE),
                msg=f"Static debug page must not render <{tag}> controls.",
            )
        layer_inputs = re.findall(r"<\s*input\b[^>]*>", html, flags=re.IGNORECASE)
        self.assertTrue(layer_inputs)
        for layer_input in layer_inputs:
            self.assertIn('type="checkbox"', layer_input)
            self.assertIn("data-layer=", layer_input)


if __name__ == "__main__":
    unittest.main()
