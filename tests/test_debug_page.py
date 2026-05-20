import re
import unittest
from pathlib import Path


PAGE_PATH = Path("docs/admin/phase-3-5-runtime-debug.html")
ASSISTANT_UI_SCRIPT = Path("docs/admin/scout-assistant-ui.js")
MUTATION_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
ALLOWED_DEBUG_ENDPOINTS = {
    "/assistant/status",
    "/debug/events",
    "/debug/messages",
    "/debug/state",
}


class DebugPageTests(unittest.TestCase):
    def test_static_debug_page_renders_required_debug_panels(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("Scout Phase 3.5 Runtime Debug", html)
        self.assertIn("Engineering read-only surface", html)
        self.assertIn("Current L0-L4 State", html)
        self.assertIn("Provider Degraded Status", html)
        self.assertIn("Ln And Skill Runs", html)
        self.assertIn("Outbound Queue", html)
        self.assertIn("Incident And Bridge Status", html)
        self.assertIn("Runtime Map", html)
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
        self.assertIn('id="panel-incident"', html)
        self.assertIn('id="panel-skill"', html)
        self.assertIn('id="panel-outbound"', html)
        self.assertIn('id="panel-boundary"', html)

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
        self.assertIn("grid-template-rows: minmax(0, 1fr) minmax(0, 1fr)", html)
        self.assertNotIn("position: fixed", html)
        self.assertNotIn("map-dock", html)
        self.assertIn('role="button"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('aria-label="Runtime event schematic map"', html)

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
        self.assertIn("renderIncidentDetails", html)
        self.assertIn("renderSkillDetails", html)
        self.assertIn("renderMessageDetails", html)
        self.assertIn('id="providerSelectionContext"', html)
        self.assertIn('id="incidentSelectionContext"', html)
        self.assertIn('id="skillSelectionContext"', html)
        self.assertIn('id="messageSelectionContext"', html)
        self.assertIn('id="boundarySelectionContext"', html)
        self.assertIn("No incident or bridge events reached at this timeline node.", html)
        self.assertIn("No outbound mock messages reached at this timeline node.", html)

    def test_static_debug_page_renders_l_state_badge_on_timeline_nodes(self):
        html = PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn("timeline-meta", html)
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

        self.assertEqual(
            {target.split("?", 1)[0] for target in fetch_targets},
            ALLOWED_DEBUG_ENDPOINTS,
        )
        self.assertNotIn("/safety/", html)
        post_targets = set(re.findall(r'postJson\("([^"]+)"', html))
        self.assertEqual(post_targets, {"/assistant/query"})
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
        for tag in ("form", "input", "select"):
            self.assertIsNone(
                re.search(rf"<\s*{tag}\b", html, flags=re.IGNORECASE),
                msg=f"Static debug page must not render <{tag}> controls.",
            )


if __name__ == "__main__":
    unittest.main()
