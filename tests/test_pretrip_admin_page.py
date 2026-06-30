import json
import subprocess
from pathlib import Path

from pretrip_admin_view import build_pretrip_admin_view, load_pretrip_debug_projection_view


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"


def test_pretrip_admin_page_contains_expected_layout_contract():
    html = PAGE.read_text(encoding="utf-8")

    assert "Scout Phase 4 Pre-Trip Planning" in html
    assert "html { height: 100%; }" in html
    assert "height: 100vh;" in html
    assert "max-width: 100vw;" in html
    assert 'src="/admin/scout-assistant-ui.js"' in html
    assert 'id="readinessStrip"' in html
    assert 'id="energyReserveMonitor"' in html
    assert 'id="energyReserveHeadline"' in html
    assert 'id="energyReserveSubline"' in html
    assert "renderEnergyReserveMonitor" in html
    assert "view.energy_reserve_monitor" in html
    assert "map frame" not in html.lower()
    assert 'id="map"' in html
    assert "background: #e9eff4;" in html
    assert 'id="evidenceTree"' in html
    assert 'id="jsonPane"' in html
    assert 'id="sectionList"' in html
    assert "grid-template-rows: auto minmax(180px, .95fr) minmax(260px, 1.05fr);" in html
    assert "grid-template-columns: minmax(290px, 360px) minmax(640px, 1fr) minmax(340px, 420px);" in html
    assert 'grid-template-areas: "features map detail";' in html
    assert "overflow: visible;\n      z-index: 20;" in html
    assert "z-index: 80;" in html
    assert "z-index: 90;" in html
    assert "grid-template-rows: auto minmax(0, 1fr);" in html
    assert "grid-template-rows: auto auto minmax(0, 1fr);" in html
    assert "feature-header-row" in html
    assert 'class="metric-grid" aria-label="Feature summary"' in html
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in html
    assert '.list-controls input[type="search"] { grid-column: 1 / -1; }' in html
    assert ".list-controls .control-group-header { display: none; }" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html


def test_pretrip_admin_latest_ui_surfaces_reference_segment_timing():
    html = PAGE.read_text(encoding="utf-8")

    assert "Reference Segment Timing" in html
    assert "view.reference_segment_timing?.segments" in html
    assert "route_timing" in html
    assert '["Route Timing", `${view.reference_segment_timing?.counts?.usable_segment_count || 0} segments / ${view.reference_segment_timing?.counts?.measurement_count || 0} samples`]' in html
    assert 'type.includes("reference_segment_timing")' in html
    assert 'item?.evidence_type === "pretrip_reference_segment_timing_segment"' in html
    assert "preserveZoom: false" in html
    assert "scrollbar-gutter: stable;" in html
    assert "min-height: 0;" in html
    assistant_drawer_open_css = html.split(".assistant-drawer[open]", 1)[1].split(".assistant-drawer summary", 1)[0]
    assert "min-height: 0;" in assistant_drawer_open_css
    assistant_panel_css = html.split(".assistant-drawer .assistant-panel", 1)[1].split(".assistant-head", 1)[0]
    assert "height: 100%;" in assistant_panel_css
    assert "min-height: 0;" in assistant_panel_css
    assert "overflow-y: auto;" in assistant_panel_css
    assert "grid-template-columns: 1fr;" in html
    assert '"map"\n          "features"\n          "detail";' in html
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in html
    assert "grid-template-columns: repeat(3, 24px);" in html
    assert "grid-template-rows: repeat(3, 24px);" in html
    responsive_map_css = html.split("@media (max-width: 1120px)", 1)[1].split(".toolbar-grid", 1)[0]
    assert "#map {\n        height: auto;\n        min-height: 0;\n        aspect-ratio: 1000 / 720;" in responsive_map_css
    assert "#map { min-height: 420px; }" not in html
    assert ".detail-body > *," in html
    assert ".tree > *," in html
    assert ".assistant-panel > *" in html
    assert "overflow-wrap: anywhere;" in html
    assert ".assistant-panel" in html
    assert "overflow-y: auto;" in html
    assert "overscroll-behavior: contain;" in html
    assert "CP / Segment Frame" in html
    assert "Pre-trip planning" in html
    assert "Post-analysis" in html
    assert "Review , Workspace" in html
    assert "Import GPX" in html
    assert "Wearables" in html
    assert "Scout Agent Skills" in html
    assert 'id="reviewWorkspacePanel"' in html


def test_pretrip_admin_map_segments_render_from_display_geometry_first():
    html = PAGE.read_text(encoding="utf-8")

    assert "let segmentCoordSegments = coordinateSegments(" in html
    assert "segment.display_geometry?.coordinates || []" in html
    assert "if (!segmentCoordSegments.length) {" in html
    assert "segmentCoordSegments = [[from, to]];" in html
    assert "d: pathFromCoordSegments(bounds, segmentCoordSegments)" in html
    assert 'id="reviewWorkspaceTree"' in html
    assert 'id="importGpxPanel"' in html
    assert 'id="wearablesPanel"' in html
    assert 'id="agentSkillsPanel"' in html
    assert 'id="agentSkillsList"' in html
    assert "segment-overlay" in html
    assert "reference-track" in html
    assert "gis-perception-cp" in html
    assert "gis-nearby-group" in html
    assert "risk-score-point" in html
    assert "risk-ribbon" in html
    assert "riskLevelClass" in html
    assert "riskRibbonClass" in html
    assert "is-stale" in html
    assert "map-highlight" in html
    assert "drop-shadow(0 0 7px rgba(15, 74, 84, .74))" in html
    assert "stroke: #0f4a54 !important;" in html
    assert "Math.max(base, 4.4)" in html
    assert "mapTargetsFor" in html
    assert "map_target_ids" in html
    assert "selectEvidence" in html
    assert "highlightMapFor" in html
    assert "data-source-id" in html
    assert "data-tree-category" in html
    assert "data-tree-status" in html
    assert ".route-note" in html
    assert ".mcp-candidate" in html
    assert ".boss-point" in html
    assert "AI GIS CP" in html
    assert "GIS CP Areas" in html
    assert "Major Critical Points" in html
    assert "Boss Points" in html
    assert "Evidence Timeline" in html
    assert "view.evidence_timeline?.categories" in html
    assert "view.major_critical_points?.candidates" in html
    assert "view.boss_points?.boss_points" in html
    assert "item?.boss_point_id || item?.source_mcp_id || item?.source_candidate_id" in html
    assert "item.boss_point_id" in html
    assert "item.source_mcp_id" in html
    assert "item.source_candidate_id" in html
    assert "function isBossPoint(item)" in html
    assert "function bossDisplayText(item)" in html
    assert "function bossSummaryText(item)" in html
    assert "function bossDetailPayload(item)" in html
    assert 'canonical_centerline: "overpass_risk_ribbon"' in html
    assert 'gpx_evidence_axis: "projected_to_overpass_risk_ribbon"' in html
    assert "label: bossDisplayText(item)" in html
    assert "sublabel: bossSummaryText(item)" in html
    assert 'String(point.challenge_fit?.band || "").includes("not_ready")' in html
    assert "item.cp_support_reconciliation?.support_status" in html
    assert "item.accepted_evidence_page_count" in html
    assert "item.source_family_coverage?.present" in html
    assert "item.nearby_points_suppressed_by_spacing" in html
    assert "Risk Score" in html
    assert "view.risk_score?.points" in html
    assert "Baseline Risk" in html
    assert "Calibrated Heat" in html
    assert "Risk Delta" in html
    assert "view.risk_ribbon?.segments" in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Baseline Risk", view.risk_ribbon?.segments || []' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Calibrated Heat", view.risk_heatmap?.segments || []' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Risk Heat"' not in html
    assert 'appendEvidenceTreeGroup(tree, "default", "Boss Points", view.boss_points?.boss_points || []' in html
    assert "Capability Timeline Import" in html
    assert "Capability Timeline" in html
    assert "view.capability_timeline_import?.edges" in html
    assert "capability_timeline_import" in html
    assert "focusMapFor" in html
    assert "FOCUS_POINT_VIEWPORT_M = 50" in html
    assert "const widthZoom = widthMeters / FOCUS_POINT_VIEWPORT_M;" in html
    assert "const heightZoom = heightMeters / FOCUS_POINT_VIEWPORT_M;" in html
    assert "POINT_LABEL_VIEWPORT_M = 50" in html
    assert "POINT_LABEL_FONT_PX = 4" in html
    assert "POINT_LABEL_STROKE_PX = 0.6" in html
    assert "POINT_LABEL_OFFSET_PX = 3" in html
    assert "function updateScaleBar" in html
    assert '"data-ui-overlay": "scale-bar"' in html
    assert "aria-label\": \"Map scale bar\"" in html
    assert "niceScaleMeters" in html
    assert "formatScaleMeters" in html
    assert "function readablePointLabel" in html
    assert "function compactPointLabel" in html
    assert "function pointLabelUnitsPerScreenPixel" in html
    assert ".map-label-overlay" in html
    assert "function appendMapOverlayLabel" in html
    assert "function placeMapOverlayNode" in html
    assert "function pointLabelCalloutTitle" in html
    assert "function pointLabelCalloutSummary" in html
    assert 'overlay?.replaceChildren();' in html
    assert 'label.classList.add("is-hidden");' in html
    assert '"data-label-title": pointLabelCalloutTitle(item, label)' in html
    assert '"data-label-summary": pointLabelCalloutSummary(item, pointLabelCalloutTitle(item, label))' in html
    assert "item?.map_label" in html
    assert "item?.display_label" in html
    assert "bossDisplayText(item)" in html
    assert "if (isBossPoint(item)) return bossSummaryText(item);" in html
    assert "gis_cp_cluster\\." in html
    assert "function updatePointLabels" in html
    assert '"data-label-layer"' in html
    assert '"data-label-anchor-x"' in html
    assert '"data-label-anchor-y"' in html
    assert 'label.setAttribute("font-size", (POINT_LABEL_FONT_PX * unitsPerPx).toFixed(3));' in html
    assert 'label.setAttribute("stroke-width", (POINT_LABEL_STROKE_PX * unitsPerPx).toFixed(3));' in html
    assert "anchorX + POINT_LABEL_OFFSET_PX * unitsPerPx" in html
    assert "anchorY - POINT_LABEL_OFFSET_PX * unitsPerPx" in html
    assert "currentViewportRangeM() <= POINT_LABEL_VIEWPORT_M" in html
    assert "layerEnabled && (focused || showByZoom)" in html
    assert "pointFocusItemFor" in html
    assert "findPointFocusEvidenceByRef" in html
    assert "review_focus" in html
    assert "const pad = MAP_VISUAL_PADDING / state.zoom;" not in html
    assert "MAP_ZOOM_STEP_FACTOR = 1.25" in html
    assert "zoom-selection" in html
    assert "beginMapRectangleZoom" in html
    assert "zoomMapToBox" in html
    assert "zoomMapOutFromBox" in html
    assert "Math.max(1, Math.min(MAP_MAX_ZOOM, state.zoom / factor))" in html
    assert "isZoomOutDrag" in html
    assert "let treeClickFocusTimer = null;" in html
    assert "function scheduleTreeClickFocus(item)" in html
    assert "window.clearTimeout(treeClickFocusTimer);" in html
    assert 'item?.evidence_type === "pretrip_reference_segment_timing_segment"' in html
    assert "focusMapFor(item, focusOptions);" in html
    assert "function focusTreeItemImmediately(item, options = {})" in html
    assert 'button.addEventListener("click", () => scheduleTreeClickFocus(item));' in html
    assert 'button.addEventListener("dblclick", event => {\n        event.preventDefault();\n        focusTreeItemImmediately(item, {label: true});' in html
    assert 'addEventListener("dblclick"' in html
    assert "nearby_group_id" in html
    assert "route_note_freshness" in html
    assert "view.gis_perception_timeline?.checkpoint_candidates" in html
    assert "item.display_label || item.map_label || item.route_note_summary" in html
    assert "item.display_label || item.map_label || item.nearby_group_id" in html


def test_pretrip_admin_page_has_top_level_readiness_strip_boundary_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "readinessStrip",
        "readinessStripStatus",
        "readinessStripBoundary",
        "readinessBlockerCount",
        "readinessWarningCount",
        "readinessFieldReviewCount",
        "readinessReviewedPackageStatus",
        "readinessDepartureGateBoundary",
        "readinessRuntimeHandoffBoundary",
    ):
        assert f'id="{control_id}"' in html

    assert "function updateReadinessStrip" in html
    assert "view.readiness?.status" in html
    assert "view.review_queue?.counts" in html
    assert "view.route_note_reviewed_assumptions?.counts?.field_verification_request_count" in html
    assert "view.departure_bundle?.package?.status" in html
    assert "view.departure_bundle?.boundary" in html
    assert "view.tabs?.post_analysis?.runtime_handoff?.boundary" in html
    assert "Reviewed planning package only; runtime activation remains closed." in html
    assert "Human review required; not departure approval." in html
    assert "Phase 4.5 owns handoff; no /safety calls or runtime writes." in html


def test_pretrip_admin_page_has_read_only_toolbar_and_summary_raw_sample_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "zoomIn",
        "zoomOut",
        "fitRoute",
        "boxZoomMode",
        "zoomLevel",
        "panUp",
        "panDown",
        "panLeft",
        "panRight",
        "layerControl",
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
        "externalDataImport",
    ):
        assert f'id="{control_id}"' in html

    for enabled_control in (
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
    ):
        assert f'id="{enabled_control}" class="tool-button" type="button" disabled' not in html
        assert f'id="{enabled_control}" class="tool-button" type="button"' in html
    assert 'id="externalDataImport" class="tool-button" type="button" title="Open Import GPX reference route flow" aria-label="Open Import GPX reference route flow">Import GPX</button>' in html
    assert 'id="externalDataImport" class="tool-button" type="button" disabled' not in html
    assert "summary only" in html
    assert "raw_samples" not in html


def test_pretrip_admin_page_groups_dense_controls_and_uses_short_labels():
    html = PAGE.read_text(encoding="utf-8")
    assistant_script = ASSISTANT_UI_SCRIPT.read_text(encoding="utf-8")

    assert "toolbar-grid" in html
    assert "assistant-drawer" in html
    assert '<details class="assistant-drawer" open>' in html
    assert '<summary aria-label="Open read-only assistant panel">Assistant</summary>' in html
    assert 'id="assistantQuestionInput"' in html
    assert 'id="assistantAskButton"' in html
    assert 'id="readinessStripStatus">Loading…</strong>' in html
    assert 'class="sr-only">Reviewed planning is not runtime activation.</small>' in html
    assert 'aria-label="Map view controls"' in html
    assert 'aria-label="Rectangle drag zoom"' in html
    assert 'id="zoomLevel" class="zoom-level"' in html
    assert "function updateMapZoomIndicator" in html
    assert "function mapStrokeWidthPx(node, scale)" in html
    assert "function mapMarkerRadiusPx(circle, scale, baseRadius)" in html
    assert ".hover-hint {\n      position: fixed;\n      z-index: 10000;" in html
    assert 'circle.classList.contains("mcp-candidate") || circle.classList.contains("boss-point")' in html
    assert 'node.style.setProperty("stroke-width", `${strokeWidth.toFixed(2)}px`, priority)' in html
    assert "selectionZoomFactor(selection).toFixed(2)" in html
    assert 'aria-label="Map layer controls"' in html
    assert 'class="layer-menu"' in html
    assert 'id="layerControl" title="Show layer controls" aria-label="Layer controls"' in html
    assert 'id="layerEnabledCount"' in html
    assert "layer-menu-panel" in html
    assert 'class="layer-preset-row" aria-label="Layer presets"' in html
    assert 'data-layer-preset="risk-review"' in html
    assert 'data-layer-preset="mcp-review"' in html
    assert 'data-layer-preset="route-clean"' in html
    assert 'data-layer-preset="debug-replay"' in html
    assert 'data-layer-preset="raster-check"' in html
    assert 'class="layer-advanced"' in html
    assert "Advanced layers" in html
    assert 'data-layer="boss-points" checked> Boss</label>' in html
    assert ".filters label {\n      display: inline-flex;\n      align-items: center;\n      gap: 4px;\n      min-height: 28px;" in html
    assert ".layer-menu summary {\n      min-height: 28px;" in html
    assert ".layer-preset-button {\n      min-height: 28px;\n      display: flex;\n      align-items: center;" in html
    assert ".layer-advanced summary {\n      border: 0;\n      background: transparent;\n      padding: 4px 0 6px;\n      min-height: 28px;" in html
    assert "width: max-content;\n      max-width: 100%;\n      box-sizing: border-box;" in html
    assert "@media (max-width: 1120px)" in html
    mobile_readiness_css = html.split("@media (max-width: 640px)", 1)[1].split(".layer-menu-panel", 1)[0]
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_readiness_css
    assert 'data-readiness-kind="energy"' in html
    assert "white-space: nowrap;" in mobile_readiness_css
    assert "text-overflow: ellipsis;" in mobile_readiness_css
    assert "#energyReserveSubline {\n        white-space: normal;" in mobile_readiness_css
    assert "text-overflow: clip;\n        line-height: 1.25;" in mobile_readiness_css
    assert ".route-pane .metric-grid {\n        grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_readiness_css
    assert ".route-pane .metric span,\n      .route-pane .metric strong {\n        overflow: visible;" in mobile_readiness_css
    assert "text-overflow: clip;\n        white-space: normal;" in mobile_readiness_css
    assert "grid-column: 1 / -1;" not in mobile_readiness_css
    assert ".readiness-strip { grid-template-columns: 1fr; }" not in mobile_readiness_css
    assert ".layer-menu-panel {\n        position: fixed;\n        top: 120px;\n        left: 12px;\n        right: 12px;\n        width: auto;" in html
    assert "function applyLayerPreset" in html
    assert "function syncLayerPresetButtons" in html
    assert "function bindLayerMenuDismiss()" in html
    assert "function closeLayerMenus(exceptMenu = null)" in html
    assert "function layerMenuFromEvent(event)" in html
    assert "event.composedPath()" in html
    assert 'window.__scoutLayerMenuDismissVersion === "v2"' in html
    assert "window.__scoutLayerMenuDismissBound" not in html
    assert html.index("bindLayerMenuDismiss();") < html.index("bindAssistantControls();")
    assert '["pointerdown", "mousedown", "touchstart", "click"].forEach(eventName =>' in html
    assert "[window, document, document.documentElement, document.body]" in html
    assert "target.addEventListener(eventName, dismissLayerMenusForEvent, {capture: true, passive: true});" in html
    assert 'document.addEventListener("focusin", dismissLayerMenusForEvent, {capture: true});' in html
    assert 'menu.addEventListener("toggle", () =>' in html
    assert "if (menu.open) closeLayerMenus(menu);" in html
    assert 'if (event.key === "Escape") closeLayerMenus();' in html
    assert 'document.querySelectorAll(".layer-menu[open]")' in html
    assert "availablePresetLayerSet" in html
    assert "summary.textContent = `${enabled}/${layerInputs.length}`;" in html
    assert "Workspace edit tools" in html
    assert 'aria-label="Workspace edit tools">Edit</summary>' in html
    assert "Planned edit tools" not in html
    assert "<span>Features</span>" in html
    assert "<span>Review</span>" in html
    assert "<span>Workspace</span>" in html
    assert 'class="action-menu workspace-menu"' in html
    assert "Workspace actions" in html
    assert 'aria-label="Local workspace menu actions"' in html
    assert 'title="Add retreat route to workspace edit log" aria-label="Add retreat route to workspace edit log">Add retreat</button>' in html
    assert 'title="Open Import GPX reference route flow" aria-label="Open Import GPX reference route flow">Import GPX</button>' in html
    assert 'title="Route note layer"><input type="checkbox" data-layer="route-notes"> Notes</label>' in html
    assert 'title="Scout Risk Engine pretrip risk score point layer"><input type="checkbox" data-layer="risk-score"> Risk pts</label>' in html
    assert 'title="Route-aligned baseline terrain risk layer"><input type="checkbox" data-layer="risk-ribbon" checked> Baseline</label>' in html
    assert 'title="Route-specific calibrated heat map"><input type="checkbox" data-layer="risk-heatmap" checked> Calibrated</label>' in html
    assert 'title="Difference between baseline risk and calibrated heat"><input type="checkbox" data-layer="risk-delta"> Delta</label>' in html
    assert 'title="CWA quantitative precipitation forecast grid"><input type="checkbox" data-layer="cwa-qpf"> QPF</label>' in html
    assert 'title="SMAP L4 soil moisture hydrology context"><input type="checkbox" data-layer="soil-moisture"> Soil H2O</label>' in html
    assert 'title="GPM IMERG antecedent rain context"><input type="checkbox" data-layer="antecedent-rain"> Rain</label>' in html
    assert 'title="CWA warnings observations and forecast evidence"><input type="checkbox" data-layer="cwa-weather"> CWA</label>' in html
    assert ".environment-extent" in html
    assert "function renderEnvironmentExtent" in html
    assert "function environmentEvidenceSummary" in html
    assert "function environmentRiskDerivativeItemSummary" in html
    assert "function environmentRiskCandidateTreeSummary" in html
    assert "function renderEnvironmentRiskDerivativeCandidates" in html
    assert 'evidenceType.includes("environment_risk_derivative")' in html
    assert "route_revalidation_status" in html
    assert "SMAP L4 route bbox mean" in html
    assert "candidate-only context; not runtime safety truth" in html
    assert "SMAP surface" in html
    assert "GPM 72h" in html
    assert 'title="Weather API layer"><input type="checkbox" data-layer="weather-api"> Weather</label>' in html
    assert 'aria-label="Move to next review item">Next</button>' in html
    assert 'aria-label="Accept selected review">Accept</button>' in html
    assert 'aria-label="Route-note reviewed assumptions">Assumptions</button>' in html
    assert "function assistantQuestionLabel" in html
    assert 'aria-label="Scout standard gap audit"' in html
    assert 'id="assistantStandardGapAuditList"' in html
    assert "Standard gaps?" in html
    assert "SCOUT_OUTDOOR_AI_AGENT_STANDARD" in html
    assert "window.ScoutAssistantUI.renderStandardGapAudit(payload)" in html
    assert "window.ScoutAssistantUI.renderStandardGapAudit({})" in html
    assert "function standardGapAudit" in assistant_script
    assert "function standardGapAuditItems" in assistant_script
    assert "function renderStandardGapAudit" in assistant_script
    assert "assistantStandardGapAuditList" in assistant_script
    assert "implementation_gap_tools" in assistant_script
    assert "context_review_gap_tools" in assistant_script
    assert "ui_validation:" in assistant_script


def test_standard_gap_audit_items_render_zero_gap_ui_validation_contract():
    payload = {
        "sources": [
            {
                "source_id": "assistant_skill.pretrip.full_workflow.v0",
                "context_summary": {
                    "decision_output": {
                        "standardGapAudit": {
                            "schema": "scout_standard_gap_audit.v0",
                            "runtimeSafetyTruth": False,
                            "summary": {
                                "standardGroupCount": 10,
                                "coveredStandardGroupCount": 10,
                                "implementationGapToolCount": 0,
                                "contextOrReviewEvidenceGapToolCount": 0,
                                "uiUxValidationNeeded": False,
                            },
                            "uiUxValidation": {
                                "validated": True,
                                "status": "validated_static_admin_ui",
                                "surface": "pretrip_admin",
                            },
                            "groups": [
                                {
                                    "label": "六力動態決策",
                                    "sections": "5-11",
                                    "status": "implemented_evidence_available",
                                    "missingFieldCount": 0,
                                }
                            ],
                            "inputOrEvidenceGaps": [],
                            "nextSlices": [
                                "用真實專案資料重跑 Route Readiness 與 Contextual Permission。"
                            ],
                            "nonGoals": [
                                "此 audit 不批准出發、不寫入 runtime safety truth。"
                            ],
                        }
                    }
                },
            }
        ]
    }
    script = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({json.dumps(str(ASSISTANT_UI_SCRIPT))}, "utf8");
const payload = {json.dumps(payload, ensure_ascii=False)};
const context = {{ window: {{}}, console }};
vm.createContext(context);
vm.runInContext(code, context);
console.log(JSON.stringify(context.window.ScoutAssistantUI.standardGapAuditItems(payload)));
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    items = json.loads(result.stdout)
    assert "schema: scout_standard_gap_audit.v0 | runtime_safety_truth=false" in items
    assert (
        "coverage: 10/10 groups | implementation_gap_tools=0 | "
        "context_review_gap_tools=0 | ui_ux_validation_needed=false"
    ) in items
    assert (
        "ui_validation: status=validated_static_admin_ui | "
        "surface=pretrip_admin | validated=true"
    ) in items
    assert any(
        "group: 六力動態決策" in item
        and "implemented_evidence_available" in item
        for item in items
    )
    assert any(item.startswith("boundary: 此 audit 不批准出發") for item in items)


def test_pretrip_admin_page_has_import_gpx_reference_route_panel():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "importGpxTab",
        "importGpxPanel",
        "importGpxForm",
        "importGoldenRouteGpxPath",
        "importReferenceDirectory",
        "importWorkspaceRoot",
        "importTemplateRoot",
        "importCheckpointSpacingM",
        "importMaxReferenceDisplayPoints",
        "importOverwriteWorkspace",
        "importGpxPreview",
        "importGpxRun",
        "importGpxStatus",
        "importGpxResult",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "importGpxInputValue",
        "optionalImportGpxInputValue",
        "importGpxPositiveNumber",
        "importGpxPayload",
        "importGpxValidationErrors",
        "setImportGpxStatus",
        "setImportGpxBusy",
        "setImportGpxResult",
        "previewImportGpx",
        "runImportGpx",
        "prepareLayersPayload",
        "prepareLayersValidationErrors",
        "setPrepareLayersStatus",
        "setPrepareLayersBusy",
        "setPrepareLayersResult",
        "previewPrepareLayers",
        "runPrepareLayers",
    ):
        assert f"function {function_name}" in html

    assert "Golden route GPX is a pre-trip reference route, not an actual walked user track." in html
    assert "Actual walked track belongs to post-analysis after return." in html
    assert "Golden route GPX path" in html
    assert "Reference GPX directory" in html
    assert "Workspace root" in html
    assert "Optional when the admin runtime already has SCOUT_PRETRIP_WORKSPACE_ROOT." in html
    assert "Template project root" in html
    assert "Checkpoint spacing (m)" in html
    assert "Max reference display points" in html
    assert "Overwrite existing project workspace" in html
    assert "Prepare Layers" in html
    assert "LayerPreparationJob（圖層準備工作）" in html
    assert "Layer ids" in html
    assert "Route corridor (m)" in html
    assert "Allow explicit network fetch" in html
    assert "golden_route_gpx: importGpxInputValue" in html
    assert "reference_dir: optionalImportGpxInputValue" in html
    assert "workspace_root: optionalImportGpxInputValue" in html
    assert "template_project_root: optionalImportGpxInputValue" in html
    assert "checkpoint_spacing_m: importGpxPositiveNumber" in html
    assert "max_reference_display_points: importGpxPositiveNumber" in html
    assert "overwrite: document.getElementById(\"importOverwriteWorkspace\").checked" in html
    assert "confirm_import: true" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/import-gpx-preview" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/import-gpx" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/prepare-layers-preview" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/prepare-layers" in html
    assert "confirm_prepare: true" in html
    assert "const DETAIL_TAB_IDS = new Set" in html
    assert 'state.activeTab: initialActiveTab()' not in html
    assert "activeTab: initialActiveTab()" in html
    assert "function initialActiveTab" in html
    assert 'params.get("tab")' in html
    assert 'DETAIL_TAB_IDS.has(requested)' in html
    assert "function syncActiveTabChrome" in html
    assert "function syncActiveTabPanels" in html
    assert 'document.getElementById("externalDataImport").addEventListener("click", () => setActiveTab("import_gpx"))' in html
    assert 'document.getElementById("importGpxPreview").addEventListener("click", previewImportGpx)' in html
    assert 'document.getElementById("importGpxRun").addEventListener("click", runImportGpx)' in html
    assert 'document.getElementById("prepareLayersPreview").addEventListener("click", previewPrepareLayers)' in html
    assert 'document.getElementById("prepareLayersRun").addEventListener("click", runPrepareLayers)' in html
    assert 'document.getElementById("importGpxPanel").classList.toggle("is-active", tab === "import_gpx")' in html
    assert "golden_route_role: \"pretrip reference route\"" in html
    assert "actual_walked_track_surface: \"post-analysis\"" in html
    assert "phase1_runtime_mutation_allowed: false" in html
    assert "final MissionGraph" in html


def test_pretrip_admin_page_has_wearable_inventory_energy_controls():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "wearablesTab",
        "wearablesPanel",
        "wearablesForm",
        "wearableSourcePath",
        "wearableDeleteActivityId",
        "wearableReferenceDate",
        "wearableCompanionCandidatePath",
        "wearableOverwriteImport",
        "wearableInventoryRefresh",
        "wearableValidateRun",
        "wearableImportRun",
        "wearableDeleteRun",
        "wearableEnergyRefreshRun",
        "wearableDailyHomePreviewRun",
        "wearablePretripProjectionRun",
        "wearableCompanionMatchRun",
        "wearableEnergyFeedbackRun",
        "wearableStatus",
        "wearableResult",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "wearableInputValue",
        "wearableReferenceDatePayload",
        "setWearableStatus",
        "setWearableBusy",
        "setWearableResult",
        "loadWearableInventory",
        "validateWearableSummary",
        "importWearableSummary",
        "deleteWearableSummary",
        "refreshWearableEnergy",
        "refreshDailyHomePreview",
        "refreshPretripEnergyProjection",
        "refreshCompanionMatchReview",
        "refreshPostAnalysisEnergyFeedback",
    ):
        assert f"function {function_name}" in html

    assert 'DETAIL_TAB_IDS = new Set(["pre_trip_planning", "post_analysis", "review_workspace", "import_gpx", "wearables", "agent_skills"])' in html
    assert 'document.getElementById("wearablesPanel").classList.toggle("is-active", tab === "wearables")' in html
    assert 'document.getElementById("agentSkillsPanel").classList.toggle("is-active", tab === "agent_skills")' in html
    assert "/admin/wearables" in html
    assert "/admin/wearables/validate" in html
    assert "/admin/wearables/import" in html
    assert "/admin/wearables/refresh-energy" in html
    assert "/admin/wearables/daily-home-preview" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/refresh-energy-projection" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/refresh-companion-match" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/refresh-energy-feedback" in html
    assert 'id="routeContextBriefingLink"' in html
    assert "/admin/pretrip/projects/chilai_nanhua_day1/briefings/route-context" in html
    assert "candidate_capsule_paths" in html
    assert "medical_diagnosis: false" in html
    assert "phase1_runtime_safety_truth: false" in html
    assert "raw_health_payload_shared: false" in html


def test_pretrip_admin_page_fetches_fixture_backed_read_only_project_api():
    html = PAGE.read_text(encoding="utf-8")

    assert 'const DEFAULT_PROJECT_ID = "chilai_nanhua_day1"' in html
    assert "new URLSearchParams(window.location.search).get(\"projectId\")" in html
    assert "const PROJECT_ID = /^[A-Za-z0-9_.-]+$/.test(PROJECT_ID_PARAM)" in html
    assert "encodeURIComponent(PROJECT_ID)" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}" in html
    assert "apiBase()" in html
    assert 'data-layer="imagery"' in html
    assert '<input type="checkbox" data-layer="imagery"> Imagery' in html
    assert 'data-layer="rudy"' in html
    assert 'data-layer="rudy-twmap"' in html
    assert '<input type="checkbox" data-layer="rudy-twmap" checked> Rudy+TW' in html
    assert 'data-layer="relief"' in html
    assert 'data-layer="geology"' in html
    assert 'data-layer="topo-5k"' in html
    assert 'data-layer="forest"' in html
    assert 'data-layer="osm"' in html
    assert 'data-layer="terrain"' in html
    assert 'data-layer="terrain" checked' in html
    assert 'data-layer="corridors"' in html
    assert 'data-layer="route"' in html
    assert 'data-layer="segments"' in html
    assert 'data-layer="retreat"' in html
    assert 'data-layer="hazards"' in html
    assert 'data-layer="overpass"' in html
    assert 'data-layer="risk-ribbon"' in html
    assert 'data-layer="cwa-qpf"' in html
    assert 'data-layer="soil-moisture"' in html
    assert 'data-layer="antecedent-rain"' in html
    assert 'data-layer="route-notes"' in html
    assert 'data-layer="cwa-weather"' in html
    assert 'data-layer="weather-api"' in html
    assert "OSM_TILE_URL_TEMPLATE" in html
    assert "OSM_PUBLIC_TILE_URL_TEMPLATE" in html
    assert "OSM_LOCAL_TILE_URL_TEMPLATE" in html
    assert "const OSM_TARGET_ZOOM = 17" in html
    assert "const OSM_MAX_TILES = 64" in html
    assert "const RASTER_MAX_TILES = 64" in html
    assert "const MAP_VISUAL_PADDING = 56" in html
    assert "RASTER_TILE_CACHE_BUST" in html
    assert "function rasterTileCacheBustedUrl" in html
    assert "/admin/tiles/osm/{z}/{x}/{y}.png" in html
    assert "/admin/tiles/osm/{z}/{x}/{y}.png?fallback=offline" in html
    assert "function osmTileTemplate" in html
    assert "function isLocalOsmTileMode" in html
    assert 'return requested === "public" ? OSM_PUBLIC_TILE_URL_TEMPLATE : OSM_LOCAL_TILE_URL_TEMPLATE' in html
    assert "function tileRangeForZoom" in html
    assert "function tileCountForZoom" in html
    assert "tileCountForZoom(bounds, zoom) > maxTiles" in html
    assert "function rasterTileTemplate" in html
    assert "function rasterLayerFor" in html
    assert "RASTER_SOURCE_LAYER_DEFINITIONS" in html
    assert "RASTER_OVERLAY_LAYER_DEFINITIONS" in html
    assert "https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/EPSG:3857/{z}/{y}/{x}" in html
    assert "const HAPPYMAN_WMTS_ENDPOINT" in html
    assert "function wmtsTileUrl" in html
    assert "function wmtsTileMatrixId" in html
    assert 'sourceId: "happyman_rudy"' in html
    assert 'sourceId: "happyman_geo2016"' in html
    assert 'sourceId: "happyman_forest"' in html
    assert "function rasterZoomRangeFor" in html
    assert "function chooseRasterZoom" in html
    assert "const preferredZoom = zoom ?? chooseRasterZoom(view, bounds, RASTER_MAX_TILES, layerId)" in html
    assert "for (let z = preferredZoom; z >= range.min; z -= 1)" in html
    assert "function parentTileFor" in html
    assert "function positionTileImage" in html
    assert "function attachTileFallback" in html
    assert 'params.get("osmSource")' in html
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html
    assert "function renderRasterLayer" in html
    assert "const b = view.route.display_bounds || view.route.bounds" in html
    assert "const normalized = b.south !== undefined" in html
    assert "return fitBoundsToMapAspect(normalized)" in html
    assert "function lonToMercatorXValue" in html
    assert "function latToMercatorYValue" in html
    assert "function mercatorYValueToLat" in html
    assert "function fitBoundsToMapAspect" in html
    assert "const targetAspect = usableWidth / usableHeight" in html
    assert "function mercatorFrameForBounds" in html
    assert "scale: Math.min(usableWidth / xSpan, usableHeight / ySpan)" in html
    assert "function coordinateFromMapPointForBounds" in html
    assert "function visibleBoundsFor" in html
    assert "function mapViewportBox" in html
    assert "function renderRasterBasemapLayers" in html
    assert "renderRasterBasemapLayers(state.view)" in html
    assert "const RASTER_BASEMAP_LAYER_IDS" in html
    assert "function layerInputChecked(layerId)" in html
    assert 'if (layerInputChecked("imagery")) renderRasterLayer' in html
    assert "if (layerInputChecked(layer.layerId)) renderRasterLayer" in html
    assert 'if (layerInputChecked("osm")) renderOsmBasemap' in html
    assert "RASTER_BASEMAP_LAYER_IDS.has(input.dataset.layer)" in html
    assert "const coverageBounds = bounds" in html
    assert "const coverageBounds = visibleBoundsFor(view) || bounds" in html
    assert ".layer-advanced summary {\n      border: 0;\n      background: transparent;\n      padding: 4px 0 6px;\n      min-height: 28px;" in html
    assert "width: max-content;\n      max-width: 100%;\n      box-sizing: border-box;" in html
    assert "renderRasterLayer(imageryGroup, view, bounds, MAP_WIDTH, MAP_HEIGHT, \"imagery\", coverageBounds)" in html
    assert "renderRasterLayer(rasterGroup, view, bounds, MAP_WIDTH, MAP_HEIGHT, layer.layerId, coverageBounds)" in html
    assert "renderOsmBasemap(osmGroup, view, bounds, MAP_WIDTH, MAP_HEIGHT, coverageBounds)" in html
    assert '<input type="checkbox" data-layer="overpass" checked> Overpass' in html
    assert "function rasterTileCoverage" in html
    assert "function rasterBoundsFor" in html
    assert "function isDirectRuntimeRasterLayer" in html
    assert 'layer?.raster_tile_delivery === "direct_wmts_runtime"' in html
    assert '["wmts_tile", "wmts_kvp_tile", "xyz_tile"].includes(sourceKind)' in html
    assert "function boundsIntersect" in html
    assert "class: \"raster-tile\"" in html
    assert "data-raster-tile" in html
    assert "function renderOsmBasemap" in html
    assert "function localOsmPbfVectorUrl" in html
    assert "/osm-pbf-vector.geojson" in html
    assert "/admin/pretrip/osm-carto-palette" in html
    assert "function applyOsmCartoPalette" in html
    assert "function loadOsmCartoPalette" in html
    assert "--osm-carto-track-fill: #996600;" in html
    assert "var(--osm-carto-track-fill)" in html
    assert ".osm-pbf-line-core.primary" in html
    assert "var(--osm-carto-primary-fill)" in html
    assert "function osmPbfZoomMin" in html
    assert "data-osm-pbf-zoom-min" in html
    assert "function renderOsmPbfVector" in html
    assert "function osmPbfFeatureTags" in html
    assert "props.tags && typeof props.tags === \"object\"" in html
    assert "state.osmPbfVector?.features" in html
    assert "function appendOsmPbfLine" in html
    assert "function appendOsmPbfLineLabel" in html
    assert "osm-pbf-line osm-pbf-line-casing" in html
    assert "osm-pbf-line osm-pbf-line-core" in html
    assert "osm-pbf-line-label" in html
    assert '"data-osm-pbf-line-label": "true"' in html
    assert "class: `osm-pbf-area ${category}`" in html
    assert "function osmPbfDrawOrder" in html
    assert '"data-osm-pbf-kind": "line-casings"' in html
    assert '"data-osm-pbf-kind": "line-fills"' in html
    assert "lineCasingGroup" in html
    assert "lineCoreGroup" in html
    assert ".osm-pbf-area.building" in html
    assert "var(--osm-carto-water-fill)" in html
    assert 'return isArea ? "water"' in html
    assert ".osm-pbf-point { fill: #5a5f63;" in html
    assert ".osm-pbf-point.shelter" in html
    assert '"data-osm-pbf-label": "true"' in html
    assert "function syncOsmPbfLabelScale" in html
    assert "syncOsmPbfLabelScale(scale);" in html
    update_layers_body = html.split("function updateLayers()", 1)[1].split("function checkedLayerIds()", 1)[0]
    assert "syncMapMarkerScale();" in update_layers_body
    assert update_layers_body.index("syncMapMarkerScale();") < update_layers_body.index("updatePointLabels();")
    assert ".osm-pbf-line-core.path" in html
    assert ".osm-pbf-line-core.track" in html
    assert ".osm-pbf-line-core.road" in html
    assert ".osm-pbf-line-core.terrain" in html
    assert ".osm-pbf-area.forest" in html
    assert "const hasLocalVector = Boolean(localOsmPbfVectorUrl(state.view));" in html
    assert "if (isLocalOsmTileMode() && hasLocalVector) return false;" in html
    assert 'group.appendChild(el("rect", {x: 0, y: 0, width, height, class: "layer-osm"}));' in html
    assert "function osmTileCoverage" in html
    assert 'el("image"' in html
    assert "class: \"osm-tile\"" in html
    assert "function renderTerrainMetadata" in html
    assert "function terrainVisualization" in html
    assert "function terrainRasterOverlays" in html
    assert "function renderTerrainBitmapOverlays" in html
    assert "class: \"terrain-raster-overlay\"" in html
    assert "const TERRAIN_FALLBACK_CELL_WIDTH_M = 20" in html
    assert "TERRAIN_CELL_WIDTH_M = 500" not in html
    assert "function renderTerrainSquareCells" in html
    assert "function terrainCellPlacement" in html
    assert "function boxesOverlap" in html
    assert "terrain-slope-cell" in html
    assert '"data-terrain-cell-resolution-m": overlay.cell_resolution_m' in html
    assert '"data-terrain-cell-resolution-m": sample.cell_resolution_m || TERRAIN_FALLBACK_CELL_WIDTH_M' in html
    assert '"data-terrain-corridor-half-width-m": overlay.corridor_half_width_m' in html
    assert '"data-elevation-m": sample.elevation_m' in html
    assert '"data-hillshade-value": sample.hillshade_value' in html
    assert "terrain-contour-marker" in html
    assert "segmentTerrainMetadata(view)" in html
    assert "post_analysis_capability_segment" in html
    assert "pretrip_capability_timeline_import" in html
    assert "auto_applies_to_eta" in html
    assert "raw_track_shared" in html
    assert "function renderWeatherOverlay" in html
    assert "function weatherOverlayLabel" in html
    assert "weatherOverlayLabel(cards[0]?.summary || \"Weather evidence pending.\")" in html
    assert "/admin/pretrip/projects/${PROJECT_ID}/weather-overlay" in html
    assert "state.weatherOverlay" in html
    reload_body = html.split("async function reloadProjectView()", 1)[1].split("async function loadOsmPbfVectorLayer", 1)[0]
    assert "const osmPbfVectorPromise = loadOsmPbfVectorLayer(view);" in reload_body
    assert reload_body.index("const osmPbfVectorPromise = loadOsmPbfVectorLayer(view);") < reload_body.index(
        "/admin/pretrip/projects/${PROJECT_ID}/weather-overlay"
    )
    assert "await osmPbfVectorPromise;" in reload_body
    assert "Weather API overlay" in html
    assert html.index('"Risk Score", view.risk_score?.points') < html.index(
        '"Baseline Risk", view.risk_ribbon?.segments'
    )
    assert html.index('"Baseline Risk", view.risk_ribbon?.segments') < html.index(
        '"Calibrated Heat", view.risk_heatmap?.segments'
    )
    assert html.index('"Calibrated Heat", view.risk_heatmap?.segments') < html.index(
        '"Risk Delta", view.risk_delta?.segments'
    )
    assert html.index('data-layer-group": "imagery"') < html.index(
        'data-layer-group": "osm"'
    )
    assert html.index("renderRasterLayer(imageryGroup") < html.index(
        "RASTER_OVERLAY_LAYER_DEFINITIONS.forEach"
    )
    assert html.index("RASTER_OVERLAY_LAYER_DEFINITIONS.forEach") < html.index(
        "renderOsmBasemap(osmGroup"
    )
    assert html.index('data-layer-group": "reference-tracks"') < html.index(
        'data-layer-group": "risk-ribbon"'
    )
    assert html.index('data-layer-group": "risk-ribbon"') < html.index(
        'data-layer-group": "risk-heatmap"'
    )
    assert html.index('data-layer-group": "risk-heatmap"') < html.index(
        'data-layer-group": "risk-delta"'
    )
    assert html.index('data-layer-group": "risk-delta"') < html.index(
        'data-layer-group": "cwa-qpf"'
    )
    assert html.index('data-layer-group": "cwa-qpf"') < html.index(
        'data-layer-group": "soil-moisture"'
    )
    assert html.index('data-layer-group": "soil-moisture"') < html.index(
        'data-layer-group": "antecedent-rain"'
    )
    assert html.index('data-layer-group": "antecedent-rain"') < html.index(
        'data-layer-group": "cwa-weather"'
    )
    assert html.index('data-layer-group": "cwa-weather"') < html.index(
        'data-layer-group": "terrain"'
    )
    assert html.index('data-layer-group": "terrain"') < html.index(
        'data-layer-group": "risk-score"'
    )
    assert '"data-risk-layer": "baseline"' in html
    assert '"data-risk-layer": "calibrated"' in html
    assert '"data-risk-layer": "delta"' in html
    assert html.index('data-layer-group": "overpass"') < html.index(
        'data-layer-group": "weather-api"'
    )
    assert html.index('data-layer-group": "cwa-weather"') < html.index(
        'data-layer-group": "weather-api"'
    )
    assert 'class: "soil-moisture-point"' in html
    assert "antecedent-rain-point" in html
    assert "renderEnvironmentExtent(cwaQpfGroup" in html
    assert "renderEnvironmentExtent(soilMoistureGroup" in html
    assert "renderEnvironmentExtent(antecedentRainGroup" in html
    assert "renderEnvironmentExtent(cwaWeatherGroup" in html
    assert "const environmentRiskDerivativeItems" in html
    assert "const environmentRiskDerivativeLayers" in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Environmental Risk Derivatives"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Wetness / Flash Flood Candidates"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Practical Darkness Candidates"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Environment Values"' in html
    assert "baseEnvironmentValueItems" in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Soil Moisture"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Antecedent Rain"' in html
    assert "function environmentValueTreeSummary" in html
    assert "function environmentRiskMetricGapText" in html
    assert "function environmentRiskEmptyNote" in html
    assert "tree-summary-note" in html
    assert "options.emptyNote" in html
    assert "options.headerNote" in html
    assert 'type.includes("environment_risk_derivative")' in html
    assert "new_landslide_candidate_count" in html
    assert "data gaps:" in html
    assert "environment_risk_derivative_layers" in html
    assert "environment-risk-derivative" in html
    assert 'type.includes("environment") || type.includes("gee_") || type.includes("cwa_")' in html


def test_pretrip_admin_page_renders_overpass_evidence_layer_and_tree():
    html = PAGE.read_text(encoding="utf-8")
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)

    assert view["overpass_evidence"]["counts"]["candidates"] == 219
    assert view["overpass_evidence"]["counts"]["skipped"] == 0
    assert view["overpass_evidence"]["boundary"]["runtime_truth"] is False
    assert view["overpass_evidence"]["boundary"]["live_network_required"] is False
    assert "Overpass Vector Evidence" in {
        section["title"]
        for section in view["tabs"]["pre_trip_planning"]["sections"]
    }
    assert "overpass-corridor" in html
    assert "overpass-hazard" in html
    assert "overpass-poi" in html
    assert "const overpassGroups = view.overpass_evidence?.category_groups" in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Overpass Trail Corridors"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Overpass Shelters"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Overpass Water Sources"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Overpass Peaks"' in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Overpass Terrain Risk"' in html
    assert "view.overpass_evidence?.corridor_candidates" in html
    assert "view.overpass_evidence?.hazard_candidates" in html
    assert "view.overpass_evidence?.poi_candidates" in html
    assert 'appendEvidenceTreeGroup(tree, "map_risk", "Reference GPX"' in html
    assert 'id="evidenceTreeTabs"' in html
    assert "EVIDENCE_TREE_TABS" in html
    assert "button.dataset.evidenceTreeTab = tab.id" in html
    assert "function setActiveEvidenceTreeTab(tabId, options = {})" in html
    assert "function handleEvidenceTreeTabClick(event)" in html
    assert "setActiveEvidenceTreeTab(button.dataset.evidenceTreeTab, {suppressAutoSwitch: true})" in html
    assert 'document.getElementById("evidenceTreeTabs").addEventListener("click", handleEvidenceTreeTabClick)' in html
    assert "details.open = Boolean(open || state.evidenceTreeOpenGroups.has(groupKey));" in html
    assert "details.open = open;" not in html
    assert 'appendEvidenceTreeGroup(tree, "default", "Checkpoints", view.checkpoints, item => ({' in html
    assert '}), true, "checkpoint");' not in html
    assert '}), true, "segment");' not in html
    assert '}), true, "mcp");' not in html
    assert '}), true, "retreat");' not in html
    assert '}), true, "review_group");' not in html
    assert 'label: "CP / Timeline"' in html
    assert 'label: "Map / Risk"' in html
    assert 'label: "Completed GPX"' in html
    assert 'label: "Review / Queue"' in html
    assert 'label: "Info / Other"' in html
    assert "candidate.corridor.coordinates" in html
    assert "candidate.hazard.polygon" in html
    assert "candidate.poi.coordinate" in html
    assert "view.overpass_evidence?.counts?.candidates" in html
    assert "fetch(`${apiBase()}/safety" not in html


def test_pretrip_admin_page_has_round1_map_interaction_contract():
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "mapViewBox",
        "applyMapViewport",
        "clampMapPan",
        "panMap",
        "zoomMap",
        "resetMapView",
    ):
        assert f"function {function_name}" in html

    assert "pointerdown" in html
    assert "pointermove" in html
    assert "pointerup" in html
    assert "setPointerCapture" in html
    assert "is-selecting" in html
    assert "finishMapRectangleZoom" in html
    assert "highlightMapFor(state.selected)" in html
    assert "highlightTreeNode(state.selected)" in html
    assert "function evidenceTreeTabForItem(item)" in html
    assert "const tabId = evidenceTreeTabForItem(item)" in html
    assert "state.activeEvidenceTreeTab = tabId" in html
    assert "suppressEvidenceTreeAutoSwitch" in html
    assert "const previousSuppress = state.suppressEvidenceTreeAutoSwitch" in html
    assert "if (options.suppressAutoSwitch === true) state.suppressEvidenceTreeAutoSwitch = true;" in html
    assert "state.suppressEvidenceTreeAutoSwitch = previousSuppress;" in html
    assert "function evidenceTimelineCategoryForItem(item)" in html
    assert "function highlightEvidenceTimelineFor(item, options = {})" in html
    assert 'data-evidence-timeline-category' in html
    assert "evidenceTreeOpenGroups: new Set()" in html
    assert "function openEvidenceGroupForMatch(match, options = {})" in html
    assert "function trackEvidenceGroupToggle(details)" in html
    assert "openEvidenceGroupForMatch(match, {expand: options.expand === true})" in html
    assert "details.open = Boolean(open || state.evidenceTreeOpenGroups.has(groupKey));" in html
    assert 'appendEvidenceTreeGroup(tree, "default", "Evidence Timeline", view.evidence_timeline?.categories || [], item => ({' in html
    assert 'selectEvidence(item, {timeline: true, expandEvidenceGroup: true})' in html
    assert "const MAP_LAYER_RANKS" in html
    assert "events: 72" in html
    assert "function orderMapLayerGroups()" in html
    assert ".map-label-overlay {\n      position: absolute;\n      inset: 10px;\n      pointer-events: none;\n      overflow: hidden;\n      z-index: 40;" in html
    assert "function handleMapKeyboardPan(event)" in html
    assert "mapKeyboardActive: false" in html
    assert "function activateMapKeyboardPan()" in html
    assert 'document.addEventListener("keydown", handleMapKeyboardPan)' in html
    assert 'document.addEventListener("pointerdown", deactivateMapKeyboardPanOutside)' in html
    assert 'svg.setAttribute("tabindex", "0")' in html
    assert "focusMapBox(mapBoxFor(item), item, {preserveZoom: options.preserveZoom !== false})" in html
    assert "if (options.preserveZoom === false)" in html


def test_pretrip_admin_page_has_round1_cp_segment_panel_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "cpSegmentSearch",
        "featureCategoryFilter",
        "featureStatusFilter",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "statusFor",
        "sourceLabelFor",
        "compactTreeSourceLabel",
        "itemSearchText",
        "updateStatusFilterOptions",
        "applyTreeFilters",
    ):
        assert f"function {function_name}" in html

    assert "badge badge-status" in html
    assert "badge badge-category" in html
    assert "badge badge-source" in html
    assert ".badge-status {\n      flex: 0 0 auto;" in html
    assert ".badge-source {\n      flex: 1 1 9rem;" in html
    assert "data-tree-source-label" in html
    assert "sourceLabelFor(item)" in html
    assert "sourceBadge.textContent = compactTreeSourceLabel(fullSourceLabel);" in html
    assert "sourceBadge.title = fullSourceLabel" in html
    assert 'node.appendChild(document.createTextNode("\\n"));' in html
    assert "tree-label" in html
    assert "data-filter-empty" in html
    assert "scrollIntoView" in html


def test_pretrip_admin_page_has_review_queue_navigation_and_filter_contract():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "reviewCategoryFilter",
        "reviewSeverityFilter",
        "reviewBlockerQuick",
        "reviewWarningQuick",
        "reviewReviewQuick",
        "reviewBlockerCount",
        "reviewWarningCount",
        "reviewReviewCount",
        "reviewScaleSummary",
        "reviewSelectVisible",
        "reviewSelectViewport",
        "reviewClearSelection",
        "reviewNextItem",
        "routeNoteDraftDisposition",
        "routeNoteDraftPreview",
        "routeNoteDraftSave",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "reviewCategoryFor",
        "reviewSeverityFor",
        "updateReviewCategoryFilterOptions",
        "updateReviewQueueControls",
        "updateReviewQuickButtons",
        "setReviewSeverityFilter",
        "decidedCandidateRefs",
        "isCandidateRefDecided",
        "reviewDecisionStateFor",
        "reviewItemByCandidateRef",
        "isBulkReviewEligible",
        "selectedBulkReviewItems",
        "visibleBulkReviewItems",
        "syncBulkReviewSelectionStyles",
        "updateReviewSelectionSummary",
        "selectVisibleReviewItems",
        "clearReviewSelection",
        "currentMapViewportRect",
        "nodeIntersectsViewport",
        "reviewItemInCurrentViewport",
        "selectViewportReviewItems",
        "findEvidenceBySourceId",
        "routeNoteReviewOptionFor",
        "selectedRouteNoteDraftOption",
        "saveRouteNoteDraftDispositionToWorkspace",
        "visibleReviewButtons",
        "jumpToNextReviewItem",
        "previewRouteNoteDraftDisposition",
    ):
        assert f"function {function_name}" in html

    assert 'data-review-severity="blocker"' in html
    assert 'data-review-severity="warning"' in html
    assert 'data-review-severity="review"' in html
    assert 'data-review-category' in html
    assert 'data-review-decision-state' in html
    assert 'data-candidate-ref' in html
    assert "view?.review_decision_log?.decisions" in html
    assert "decision?.candidate_ref" in html
    assert "const selectedSourceId = evidenceSourceId(state.selected)" in html
    assert "findEvidenceBySourceId(view, selectedSourceId) || view.summary" in html
    assert 'button.dataset.reviewDecisionState === "undecided"' in html
    assert "return undecidedButtons.length ? undecidedButtons : buttons;" in html
    assert 'data-map-target-ids' in html
    assert "state.reviewQueueCursor" in html
    assert "selectedReviewCandidateRefs: new Set()" in html
    assert "Bulk actions apply only to undecided review-severity items." in html
    assert "Warning, blocker, departure, and runtime handoff items remain single-review." in html
    assert "button.dataset.bulkSelected" in html
    assert ".is-bulk-selected" in html
    assert 'appendEvidenceTreeGroup(tree, "review", "Review Groups", view.review_workbench?.category_groups || []' in html
    assert "state.selectedReviewCandidateRefs = new Set(item.bulk_candidate_refs)" in html
    assert "Selected review group" in html
    assert "Selected ${items.length} map-visible review-only items from the current viewport." in html
    assert "mapTargetsFor(item).some(node => nodeIntersectsViewport(node))" in html
    assert "state.routeNoteDraftDisposition" in html
    assert 'value="promote_hint"' in html
    assert 'value="promote_warning"' in html
    assert 'value="ignore"' in html
    assert 'value="field_verify"' in html
    assert "draft_preview_only" in html


def test_pretrip_admin_page_review_items_stay_map_target_backed_and_read_only():
    html = PAGE.read_text(encoding="utf-8")

    assert 'appendEvidenceTreeGroup(tree, "review", "Review Queue"' in html
    assert 'data-tree-category="review"' in html
    assert "mapTargetsFor(item)" in html
    assert "item?.map_target_ids" in html
    assert "view?.route_notes?.candidates || []" in html
    assert 'el("g", {"data-layer-group": "route-notes"})' in html
    assert 'class: "route-note"' in html
    assert 'button.addEventListener("click", () => scheduleTreeClickFocus(item));' in html
    assert 'button.addEventListener("dblclick", event => {\n        event.preventDefault();\n        focusTreeItemImmediately(item, {label: true});' in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}?compact=1`)" in html
    assert "fetch(`${apiBase()}/safety" not in html


def test_pretrip_admin_page_has_local_workspace_write_controls_and_status():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "localWorkspaceCreate",
        "workspaceAcceptReview",
        "workspaceRejectReview",
        "workspaceRefreshApplyPlan",
        "workspaceAcceptSelectedReviews",
        "workspaceRejectSelectedReviews",
        "departureReviewedCandidates",
        "routeNoteReviewedAssumptions",
        "expertContributionApplyResult",
        "workspaceWriteStatus",
    ):
        assert f'id="{control_id}"' in html

    for function_name in (
        "setWorkspaceStatus",
        "isSelectedReviewQueueItem",
        "parseWriteResponse",
        "createLocalWorkspace",
        "postReviewDecisionToWorkspace",
        "reviewDecisionPayload",
        "postBulkReviewDecision",
        "acceptSelectedReviewsToWorkspace",
        "rejectSelectedReviewsToWorkspace",
        "acceptSelectedReviewToWorkspace",
        "rejectSelectedReviewToWorkspace",
        "refreshWorkspaceApplyPlan",
        "generateDepartureReviewedCandidatesForWorkspace",
        "generateRouteNoteReviewedAssumptionsForWorkspace",
        "applyExpertContributionWorkspaceResult",
        "reloadProjectView",
    ):
        assert f"function {function_name}" in html

    assert "Workspace-only controls are closed to final handoff and runtime writes." in html
    assert '<details class="action-menu workspace-menu">' in html
    assert '<summary aria-label="Open local workspace action menu">Workspace actions</summary>' in html
    assert 'role="status" aria-live="polite"' in html
    for enabled_control in (
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
    ):
        assert f'id="{enabled_control}" class="tool-button" type="button" disabled' not in html
    assert 'id="externalDataImport" class="tool-button" type="button" title="Open Import GPX reference route flow" aria-label="Open Import GPX reference route flow">Import GPX</button>' in html


def test_pretrip_admin_page_has_enabled_workspace_edit_tools():
    html = PAGE.read_text(encoding="utf-8")

    for control_id in (
        "featureEdit",
        "addCheckpoint",
        "removeCheckpoint",
        "addRetreatRoute",
        "removeRetreatRoute",
    ):
        assert f'id="{control_id}" class="tool-button" type="button" disabled' not in html
        assert f'document.getElementById("{control_id}").addEventListener("click",' in html

    for function_name in (
        "coordinateFromMapPointerEvent",
        "setSelectedMapCoordinate",
        "selectedOrPromptCoordinate",
        "promptRectangleSelection",
        "workspaceEditPayload",
        "postWorkspaceEditLogOperation",
        "addCheckpointToWorkspace",
        "removeSelectedCheckpointFromWorkspace",
        "addRetreatRouteToWorkspace",
        "removeSelectedRetreatRouteFromWorkspace",
        "featureEditToWorkspace",
    ):
        assert f"function {function_name}" in html

    assert "selectedMapCoordinate" in html
    assert "Add CP coordinate as lat, lon. Uses selected map coordinate when available." in html
    assert "Select a checkpoint before Remove CP." in html
    assert "Select a checkpoint before Add retreat." in html
    assert "finishCheckpointCandidate" in html
    assert "Select a retreat route before Remove retreat." in html
    assert "select_trail_generate_waypoint" in html
    assert "rectangle_group_selection" in html
    assert "manualCandidateId" in html
    assert "selectedTargetRefs" in html
    assert "persist_to_workspace: true" in html
    assert "operation," in html
    assert "candidate_id: manualCandidateId" in html
    assert "target_ref: checkpoint.candidate_id" in html
    assert "target_ref: retreat.candidate_id" in html
    assert "bbox_wgs84" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace-edits`, {" in html
    assert "fetch(`${apiBase()}/safety" not in html


def test_pretrip_admin_page_posts_only_local_workspace_routes():
    html = PAGE.read_text(encoding="utf-8")
    shared_script = ASSISTANT_UI_SCRIPT.read_text(encoding="utf-8")

    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decisions`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decisions-batch`, {" in html
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/route-note-dispositions`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decision-apply-plan`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/departure-reviewed-candidates`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/route-note-reviewed-assumptions`, {"
        in html
    )
    assert (
        "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/expert-contribution-workspace-apply-result`, {"
        in html
    )
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace-edits`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/import-gpx-preview`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/import-gpx`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/prepare-layers-preview`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/prepare-layers`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/mcp-review-actions`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/refresh-companion-match`, {" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/refresh-energy-feedback`, {" in html
    assert html.count('method: "POST"') == 20
    assert shared_script.count('method: "POST"') == 1
    assert html.count("body: JSON.stringify({") == 4
    assert html.count("body: JSON.stringify(payload)") == 10
    assert html.count("body: JSON.stringify({...payload, confirm_import: true})") == 1
    assert html.count("body: JSON.stringify({...payload, confirm_prepare: true})") == 1
    assert html.count("body: JSON.stringify(") == 15
    assert html.count('headers: {"Content-Type": "application/json"}') == 15
    assert shared_script.count('headers: {"Content-Type": "application/json"}') == 1
    assert 'headers: {"Content-Type": "application/json"}' in html
    assert "body: JSON.stringify({" in html
    assert "body: JSON.stringify(payload)" in html
    assert "candidate_ref: item.candidate_ref" in html
    assert 'reviewDecisionPayload(item, "accepted", "Accepted")' in html
    assert 'postBulkReviewDecision("accepted")' in html
    assert "decisions: items.map(item => reviewDecisionPayload(" in html
    assert 'decision: "corrected"' in html
    assert "Rejected from Phase 4 admin local workspace" in html
    assert 'postBulkReviewDecision("rejected")' in html
    assert "correctionSummaryFor(item)" in html
    assert "correction: {" in html
    assert "field_updates: {}" in html
    assert "replacement_ref_ids: []" in html
    assert "persist_to_workspace: true" in html
    assert "persist_to_workspace: true" in html
    assert "mcpReviewPayload" in html
    assert "Final MissionGraph and runtime remain closed." in html
    assert 'document.getElementById("mcpAccept").addEventListener("click", acceptSelectedMcpToWorkspace)' in html
    assert 'document.getElementById("mcpReject").addEventListener("click", rejectSelectedMcpToWorkspace)' in html
    assert "operation," in html
    assert "route_note_ref: option.source_route_note_candidate_id" in html
    assert "disposition: state.routeNoteDraftDisposition" in html
    assert "Select a route-note review item before saving a draft option." in html
    assert "Select a route-note draft disposition before saving." in html
    assert "Saved route-note draft option" in html
    assert "Departure reviewed candidates written to local workspace only." in html
    assert "Departure Gate and runtime handoff remain closed." in html
    assert "Departure Reviewed Candidates" in html
    assert "view.departure_reviewed_candidates?.candidates || []" in html
    assert "view.departure_reviewed_candidates?.counts?.promoted_candidate_count ?? 0" in html
    assert "Route-note reviewed assumptions written to local workspace only." in html
    assert "Runtime and final handoff remain closed." in html
    assert "Expert contribution workspace apply result written locally." in html
    assert "No final package, MissionGraph, runtime, or Brain writeback was opened." in html
    assert "summaryPrefix} from Phase 4 admin local workspace" in html
    assert "Corrected from Phase 4 admin local workspace" in html
    assert "Accepted via scale-assisted review" in html
    assert "Rejected via scale-assisted review" in html
    assert "window.confirm" in html
    assert "Warning, blocker, departure, and runtime handoff items are skipped." in html
    assert "Select a review queue item with candidate_ref before accepting to workspace." in html
    assert "Select a review queue item with candidate_ref before correcting to workspace." in html
    assert "Select a review queue item with candidate_ref before rejecting to workspace." in html
    assert "isCandidateRefDecided(item.candidate_ref)" in html
    assert (
        "already has a decision. Select an undecided review queue item before accepting to workspace."
        in html
    )
    assert (
        "already has a decision. Select an undecided review queue item before correcting to workspace."
        in html
    )
    assert (
        "already has a decision. Select an undecided review queue item before rejecting to workspace."
        in html
    )
    assert "Correct selected review canceled: correction summary is required." in html
    assert (
        'document.getElementById("workspaceCorrectReview").addEventListener("click", correctSelectedReviewToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("workspaceRejectReview").addEventListener("click", rejectSelectedReviewToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("workspaceAcceptSelectedReviews").addEventListener("click", acceptSelectedReviewsToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("workspaceRejectSelectedReviews").addEventListener("click", rejectSelectedReviewsToWorkspace)'
        in html
    )
    assert 'document.getElementById("reviewSelectVisible").addEventListener("click", selectVisibleReviewItems)' in html
    assert 'document.getElementById("reviewSelectViewport").addEventListener("click", selectViewportReviewItems)' in html
    assert 'document.getElementById("reviewClearSelection").addEventListener("click", clearReviewSelection)' in html
    assert (
        'document.getElementById("routeNoteDraftSave").addEventListener("click", saveRouteNoteDraftDispositionToWorkspace)'
        in html
    )
    assert (
        'document.getElementById("departureReviewedCandidates").addEventListener("click", generateDepartureReviewedCandidatesForWorkspace)'
        in html
    )
    assert (
        'document.getElementById("routeNoteReviewedAssumptions").addEventListener("click", generateRouteNoteReviewedAssumptionsForWorkspace)'
        in html
    )
    assert (
        'document.getElementById("expertContributionApplyResult").addEventListener("click", applyExpertContributionWorkspaceResult)'
        in html
    )
    assert "evidenceCategory(state.selected) === \"review\"" in html
    assert 'method: "PUT"' not in html
    assert 'method: "PATCH"' not in html
    assert 'method: "DELETE"' not in html
    assert "fetch(`${apiBase()}/safety" not in html
    assert "Boolean(state.selected?.candidate_ref)" in html
    assert "await reloadProjectView();" in html
    assert html.count("await reloadProjectView();") >= 5
    assert "fetch(`${apiBase()}/safety" not in html
    assert "PUT" not in html
    assert "PATCH" not in html
    assert "DELETE" not in html


def test_pretrip_admin_page_renders_active_tab_sections_as_read_only_navigation():
    html = PAGE.read_text(encoding="utf-8")

    for function_name in (
        "sectionCountSummary",
        "sectionBoundarySummary",
        "setSectionDetail",
        "activeTabLabel",
        "activeTabSource",
        "tabOverviewPayload",
        "setActiveTabDetail",
        "highlightSectionCard",
        "renderSectionList",
    ):
        assert f"function {function_name}" in html

    assert 'id="sectionList" class="section-list" aria-label="Active tab sections"' in html
    assert "view.tabs[state.activeTab]" in html
    assert "tab?.sections || []" in html
    assert 'button.setAttribute("data-section-id", section.id)' in html
    assert "section.title" in html
    assert "section.status || \"traceable\"" in html
    assert "section.source_path || \"no source path\"" in html
    assert "sectionCountSummary(section)" in html
    assert "sectionBoundarySummary(section)" in html
    assert "section-boundary" in html
    assert 'button.addEventListener("click", () => setSectionDetail(section))' in html
    assert "JSON.stringify(section || {}, null, 2)" in html
    assert 'document.getElementById("detailTitle").textContent = `${activeTabLabel()} overview`;' in html
    assert "pre_trip_planning | fixture-backed planning workspace" in html
    assert "post_analysis | read-only post-planning artifacts" in html
    assert "active_tab: tabId" in html
    assert "section_count: sections.length" in html
    assert "sections.map(section => ({" in html
    assert "setActiveTabDetail(state.view)" in html


def test_pretrip_admin_page_section_click_handler_does_not_add_write_calls():
    html = PAGE.read_text(encoding="utf-8")

    assert "setSectionDetail(section)" in html
    assert "state.selectedSectionId = section?.id || \"\"" in html
    assert "renderSectionList(state.view)" in html
    assert ".section-card.is-selected" in html
    assert "fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}?compact=1`)" in html
    assert "fetch(`${apiBase()}/safety" not in html
    assert "PUT" not in html
    assert "PATCH" not in html
    assert "DELETE" not in html


def test_pretrip_admin_view_exposes_fixture_fields_used_by_readiness_strip():
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)

    assert view["readiness"]["status"] == "ready"
    assert view["review_queue"]["counts"]["blocker_count"] == 0
    assert view["review_queue"]["counts"]["warning_count"] == 33
    assert view["review_queue"]["counts"]["review_count"] == 221
    assert view["departure_bundle"]["package"]["status"] == "reviewed"
    assert view["departure_bundle"]["boundary"]["human_review_required_before_departure"] is True
    assert view["departure_bundle"]["boundary"]["not_departure_approval"] is True
    runtime_boundary = view["tabs"]["post_analysis"]["runtime_handoff"]["boundary"]
    assert runtime_boundary["safety_api_calls_allowed"] is False
    assert runtime_boundary["final_runtime_write_allowed"] is False


def test_pretrip_admin_page_exposes_reference_segment_timing_in_latest_ui_model():
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)
    timing = view["reference_segment_timing"]
    planning_sections = {
        section["id"]: section
        for section in view["tabs"]["pre_trip_planning"]["sections"]
    }
    timeline_categories = {
        category["category_id"]: category
        for category in view["evidence_timeline"]["categories"]
    }

    assert timing["status"] == "ready"
    assert timing["counts"]["usable_segment_count"] == 8
    assert timing["counts"]["measurement_count"] == 48
    assert timing["privacy"]["raw_gpx_embedded_in_json"] is False
    assert timing["privacy"]["coordinates_embedded"] is False
    assert timing["privacy"]["precise_timestamps_embedded"] is False
    assert timing["boundary"]["phase1_runtime_safety_truth"] is False
    assert timing["segments"][0]["duration_minutes"]["p50"] is not None
    assert timing["segments"][0]["route_guide_comparison"]["guide_duration_minutes"] == 120
    assert timing["segments"][0]["map_focus_basis"] == "route_segment_distance_projection"
    assert timing["segments"][0]["map_target_ids"]
    assert all(
        target.startswith("seg.") for target in timing["segments"][0]["map_target_ids"]
    )
    assert "reference_segment_timing" in planning_sections
    assert planning_sections["reference_segment_timing"]["counts"][
        "usable_segment_count"
    ] == 8
    assert timeline_categories["route_timing"]["available"] is True
    assert timeline_categories["route_timing"]["count"] == 8


def test_pretrip_debug_projection_includes_reference_segment_timing_events():
    projection = load_pretrip_debug_projection_view("chilai_nanhua_day1", root=ROOT)
    events = [
        event
        for event in projection["timeline_events"]
        if event["kind"] == "reference_segment_timing_projected"
    ]

    assert projection["counts"]["reference_segment_timing_segment_count"] == 8
    assert projection["counts"]["reference_segment_timing_measurement_count"] == 48
    assert len(events) == 8
    first_payload = events[0]["payload"]
    assert first_payload["projection_event_type"] == "reference_segment_timing"
    assert first_payload["duration_minutes"]["p50"] is not None
    assert first_payload["distance_filter_km"]["min"] is not None
    assert first_payload["route_guide_comparison"]["guide_duration_minutes"] == 120
    assert first_payload["map_target_ids"]
    assert all(target.startswith("seg.") for target in first_payload["map_target_ids"])
    assert first_payload["raw_gpx_embedded_in_json"] is False
    assert first_payload["coordinates_embedded"] is False
    assert first_payload["precise_timestamps_embedded"] is False


def test_pretrip_admin_page_fixture_sections_include_decision_log_and_import_queue():
    view = build_pretrip_admin_view("chilai_nanhua_day1", root=ROOT)
    planning_sections = view["tabs"]["pre_trip_planning"]["sections"]
    review_sections = view["tabs"]["review_workspace"]["sections"]
    section_ids = {section["id"] for section in planning_sections}
    section_titles = {section["title"] for section in planning_sections}
    review_section_ids = {section["id"] for section in review_sections}
    review_section_titles = {section["title"] for section in review_sections}

    assert "review_decision_log" in review_section_ids
    assert "review_workbench" in review_section_ids
    assert "external_import_queue" in review_section_ids
    assert "overpass_evidence" in section_ids
    assert "route_note_review_options" in review_section_ids
    assert "Review Decision Log" in review_section_titles
    assert "Review Workbench" in review_section_titles
    assert "External Import Queue" in review_section_titles
    assert "Overpass Vector Evidence" in section_titles
    assert "Route Note Review Options" in review_section_titles
