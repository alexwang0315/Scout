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
        self.assertIn('id="mobileIngressRecordCount"', html)
        self.assertIn('id="mobileIngressMessageCount"', html)
        self.assertIn('id="mobileIngressInvalidCount"', html)
        self.assertIn('id="mobileIngressSensorCount"', html)
        self.assertIn('id="mobileIngressLatestStatus"', html)
        self.assertIn('id="mobileIngressRecordList"', html)
        self.assertIn("raw payload stays in evidence JSONL", html)
        self.assertIn("不顯示 raw sensor values", html)
        self.assertIn("credential_value_exposed", html)

    def test_static_debug_page_has_debug_projection_clear_button(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="debugClearButton"', html)
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
        self.assertNotIn("position: fixed", html)
        self.assertNotIn("map-dock", html)
        self.assertIn('role="button"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('aria-label="chilai_nanhua_day1 debug evidence map"', html)
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
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", html)
        self.assertIn("grid-template-columns: repeat(3, 24px)", html)
        self.assertIn("grid-template-rows: repeat(3, 24px)", html)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto auto", html)
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
        self.assertIn(".terrain-raster-overlay", html)
        self.assertIn("function terrainRasterOverlays", html)
        self.assertIn("function renderTerrainBitmapOverlays", html)
        self.assertIn("pretrip_terrain_visualization_bitmap_overlay", html)
        self.assertIn("const tiles = isOsm ? tileCoverage(bounds) : rasterTileCoverage(projection, bounds, null, kind)", html)
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
        self.assertIn("function assistantQuestionLabel", html)
        self.assertIn('title="${escapeHtml(question)}"', html)

    def test_static_debug_page_links_timeline_selection_to_l0_l4_snapshot(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('id="stateSelectionContext"', html)
        self.assertIn("timelineSnapshotForEvent", html)
        self.assertIn("renderSafetySnapshot", html)
        self.assertIn("safetyLevelForEvent", html)
        self.assertIn("debugPageState.chronologicalEvents", html)
        self.assertIn("顯示 timeline #", html)
        self.assertIn("selectTimelineNode(event, index)", html)

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
        self.assertIn("Object.entries(interfaceItem.details || {}).slice(0, 5)", html)
        self.assertIn("device=${text(device.id || device.label || \"usb\")}", html)
        self.assertIn("rw_lines=${writable.length}", html)
        self.assertIn("advanced=${advanced.map", html)
        self.assertIn("gpioset_enabled=${boundary.gpioset_command_enabled", html)
        self.assertIn("wiring_confirmed=${boundary.wiring_manifest_confirmed", html)
        self.assertIn("drive_gate=wiring_manifest_required", html)
        self.assertIn("GPIO 腳位狀態", html)
        self.assertIn("GPIO/I2C/I2S/TTS/Bluetooth/UART/power/GNSS/IMU/USB/SSD inventory", html)
        self.assertIn("debug 頁不應該直接拉 GPIO high/low 或控制硬體", html)
        self.assertIn("read_only: true", html)
        self.assertIn("provider_control_allowed: false", html)

    def test_static_debug_page_renders_l_state_badge_on_timeline_nodes(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("timeline-meta", html)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto;", html)
        self.assertIn(".gis-perception-cp", html)
        self.assertIn("specificMapTargets", html)
        self.assertIn("if (!isPointFocusEvent(event)) clampMapPan();", html)
        self.assertIn("FOCUS_POINT_VIEWPORT_M = 1000", html)
        self.assertIn("const widthZoom = widthMeters / FOCUS_POINT_VIEWPORT_M;", html)
        self.assertIn("const heightZoom = heightMeters / FOCUS_POINT_VIEWPORT_M;", html)
        self.assertIn("POINT_LABEL_VIEWPORT_M = 30", html)
        self.assertIn("POINT_LABEL_FONT_PX = 4", html)
        self.assertIn("POINT_LABEL_STROKE_PX = 0.6", html)
        self.assertIn("POINT_LABEL_OFFSET_PX = 3", html)
        self.assertIn("function updateScaleBar", html)
        self.assertIn('"data-ui-overlay": "scale-bar"', html)
        self.assertIn('aria-label": "Map scale bar"', html)
        self.assertIn("niceScaleMeters", html)
        self.assertIn("formatScaleMeters", html)
        self.assertIn("function readablePointLabel", html)
        self.assertIn("function compactPointLabel", html)
        self.assertIn("function pointLabelUnitsPerScreenPixel", html)
        self.assertIn(".map-label-overlay", html)
        self.assertIn("function appendMapOverlayLabel", html)
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
        self.assertIn('node.addEventListener("click", () => {\n          selectTimelineNode(event, index);\n          focusMapForEvent(event, {label: false});', html)
        self.assertIn('node.addEventListener("dblclick", (mouseEvent) => {\n          mouseEvent.preventDefault();\n          selectTimelineNode(event, index);\n          focusMapForEvent(event, {label: true});', html)
        self.assertIn("focusMapForEvent(event, {label: false});\n            return;", html)
        self.assertIn("level-badge", html)
        self.assertIn("levelBadgeForEvent", html)
        self.assertIn("levelBadgeClassForEvent", html)
        self.assertIn("levelToken", html)
        self.assertIn("L0->L2", html)
        self.assertIn('aria-label="L state at this timeline node"', html)

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
        self.assertEqual(post_targets, {"/assistant/query", "/debug/clear"})
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
