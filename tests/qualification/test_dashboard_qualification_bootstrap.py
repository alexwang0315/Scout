from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "qualification" / "dashboard-capability-manifest.yaml"
MANIFEST_SCHEMA = (
    ROOT
    / "qualification"
    / "schemas"
    / "dashboard-capability-manifest.schema.json"
)
POLICY = ROOT / "qualification" / "policies" / "qualification-gates.yaml"
STATE_MATRIX = (
    ROOT
    / "tests"
    / "e2e"
    / "qualification"
    / "fixtures"
    / "dashboard-state-matrix.json"
)
BROWSER_RUNNER = ROOT / "scripts" / "qualification" / "run_browser_qualification.js"
ACTION_CONTRACT = ROOT / "qualification" / "dashboard-browser-action-contract.json"
ACTION_CONTRACT_SCHEMA = (
    ROOT
    / "qualification"
    / "schemas"
    / "dashboard-browser-action-contract.schema.json"
)
DASHBOARD_HTML = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"
QUALIFICATION_RUNNER = ROOT / "scripts" / "qualification" / "run_qualification.py"
REVIEW_GATE = ROOT / "scripts" / "qualification" / "enforce_review.py"
WORKFLOW = ROOT / ".github" / "workflows" / "dashboard-qualification.yml"
PACKAGE_JSON = ROOT / "package.json"
QUALIFICATION_SKILL = (
    ROOT / ".agents" / "skills" / "scout-dashboard-qualification" / "SKILL.md"
)
MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_dashboard_capability_manifest_is_canonical_and_schema_valid() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(manifest)

    capabilities = {
        capability["id"]: capability
        for surface in manifest["surfaces"]
        for capability in surface["capabilities"]
    }
    assert manifest["version"] == 2
    assert manifest["baseline_policy"] == (
        "maplibre_pre_migration_regression_guard_only"
    )
    for capability_id in (
        "dashboard.browser.maplibre_pre_migration_regression_guard",
        "dashboard.diagnostic.read_only",
        "dashboard.shell.runtime_route_navigation",
        "dashboard.browser.complete_control_coverage",
        "dashboard.visual.complete_live_rendering",
        "dashboard.maps.all_surface_interactions",
        "dashboard.layers.all_visible_toggle_integrity",
        "dashboard.layers.weather_hydrology_required_na",
        "dashboard.navigation.partial_data_shell",
        "dashboard.weather.optional_rainfall_overlay",
        "dashboard.maps.dynamic_rudy_tiles",
        "dashboard.route_context.regeneration_api",
        "dashboard.debug.hardware_readiness",
        "dashboard.permission.fail_closed",
        "qualification.evidence.integrity",
    ):
        assert capability_id in capabilities

    integrity = capabilities["qualification.evidence.integrity"]
    assert any(
        "host-level operator lease" in statement
        for statement in integrity["expected_behavior"]
    )
    assert any(
        "Two worktrees" in statement
        for statement in integrity["forbidden_behavior"]
    )
    for capability in capabilities.values():
        assert capability["expected_behavior"]
        assert capability["forbidden_behavior"]
        assert capability["required_tests"]
        assert capability["required_evidence"]
        assert capability["authority_boundary"]["runtime_authority"] is False
    regression_guard = capabilities[
        "dashboard.browser.maplibre_pre_migration_regression_guard"
    ]
    assert regression_guard["status"] == "operational"
    assert regression_guard["qualification_state"] == "active"
    assert regression_guard["required_tests"] == [
        "maplibre_pre_migration_guard_desktop",
        "maplibre_pre_migration_guard_large_mobile",
    ]
    for paused_capability_id in (
        "dashboard.browser.complete_control_coverage",
        "dashboard.visual.complete_live_rendering",
        "dashboard.maps.all_surface_interactions",
        "dashboard.layers.all_visible_toggle_integrity",
        "dashboard.maps.dynamic_rudy_tiles",
    ):
        assert capabilities[paused_capability_id]["qualification_state"] == "paused"
    diagnostic_controls = capabilities["dashboard.diagnostic.controls"]
    assert any(
        "typed expected zero" in requirement
        for requirement in diagnostic_controls["expected_behavior"]
    )
    assert "typed_zero_warning" in diagnostic_controls["required_tests"]
    assert any(
        "startup_connection_status=not_checked" in requirement
        and "yellow" in requirement
        for requirement in diagnostic_controls["expected_behavior"]
    )
    assert "assistant_not_checked_warning" in diagnostic_controls["required_tests"]
    assert capabilities["qualification.fixture.active_p0_matrix"]["status"] == "sandbox"
    assert capabilities["dashboard.route_context.regeneration_api"]["status"] == (
        "not_implemented"
    )
    assert capabilities["dashboard.debug.hardware_readiness"]["status"] == (
        "not_implemented"
    )


def test_browser_action_contract_freezes_maplibre_pre_migration_guard() -> None:
    contract = json.loads(ACTION_CONTRACT.read_text(encoding="utf-8"))
    schema = json.loads(ACTION_CONTRACT_SCHEMA.read_text(encoding="utf-8"))
    html = DASHBOARD_HTML.read_text(encoding="utf-8")

    Draft202012Validator(schema).validate(contract)

    navigation_routes = set(
        re.findall(
            r'<button class="nav-item"[^>]+data-route="([^"]+)"',
            html,
        )
    )
    contracted_routes = {route["id"] for route in contract["routes"]}
    assert contracted_routes == navigation_routes
    assert len(contracted_routes) == 23

    assert contract["schema"] == "scout.dashboardBrowserActionContract.v2"
    assert contract["version"] == 2
    assert contract["official_mode"]["qualification_boundary"] == (
        "maplibre_pre_migration_regression_guard"
    )
    assert contract["official_mode"]["productization"] is False
    assert contract["official_mode"]["zero_unmapped_controls_required"] is False
    assert contract["official_mode"]["zero_unreviewed_visual_states_required"] is False

    guard = contract["regression_guard"]
    assert guard["active"] is True
    assert guard["major_routes"] == [
        "home",
        "map",
        "timeline",
        "outdoor-navigation",
        "diagnostic",
    ]
    assert {
        route["id"] for route in contract["routes"] if route["guard_state"] == "required"
    } == set(guard["major_routes"])
    assert set(guard["required_checks"]) == {
        "dashboard_load",
        "major_route_entry",
        "fallback_map_usable",
        "layer_contract_present",
        "evidence_identity_retained",
        "no_browser_console_fatal_errors",
        "no_horizontal_overflow",
        "no_new_operational_or_safety_authority",
    }
    assert set(guard["failure_classifications"]) == {
        "existing_regression",
        "maplibre_migration_blocker",
        "old_svg_implementation_detail",
        "unrelated_dirty_worktree_issue",
        "environment_limitation",
    }
    assert {
        "map_feature",
        "layer_id",
        "artifact_id",
        "bbox",
        "highlight_state",
        "selected_evidence",
    }.issubset(set(guard["renderer_neutral_terms"]))

    paused_legacy = contract["paused_legacy_map_contract"]
    assert paused_legacy["active"] is False
    map_surface_ids = {surface["id"] for surface in paused_legacy["map_surfaces"]}
    assert map_surface_ids == {
        "overview-map",
        "lbs-map",
        "permission-map",
        "emergency-review-map",
        "map",
        "weather-map",
        "navigation-map",
        "architecture-map",
        "pace-fit-map",
    }
    assert set(paused_legacy["required_map_gestures"]) == {
        "fit",
        "zoom_in",
        "zoom_out",
        "mouse_pan",
        "keyboard_pan",
        "rectangle_zoom",
    }
    assert contract["official_mode"]["contract_tests_are_dashboard_evidence"] is False
    assert contract["control_coverage"]["include_embedded_frames"] is True
    assert contract["control_coverage"]["all_visible_controls_required"] is False
    assert contract["control_coverage"][
        "representative_layer_control_required"
    ] is True
    assert paused_legacy["required_map_content"][
        "all_exposed_layer_controls_must_be_toggled"
    ] is True
    assert "map_surfaces" not in contract
    assert "required_map_gestures" not in contract
    assert "required_map_content" not in contract
    assert contract["visual_quality"]["max_occluded_controls"] == 0
    assert contract["visual_quality"]["max_blurred_elements"] == 0
    assert contract["visual_quality"]["max_low_resolution_rasters"] == 0
    assert contract["visual_quality"]["full_route_scroll_evidence_required"] is False


def test_default_qualification_runs_renderer_neutral_guard_not_legacy_maps() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))

    assert 'const scope = legacyFull ? "legacy-full"' in source
    assert 'preMapLibreGuard: true' in source
    assert 'pausedLegacyMapCheck: true' in source
    assert "inspectMapLibrePreMigrationRegressionGuard" in source
    assert "ensureRegressionGuardNavigationVisible" in source
    assert "ensureMapEvidenceGroupExpanded" in source
    assert "MAP_EVIDENCE_GROUP_EXPANSION_ATTEMPTS" in source
    assert "resolveRendererNeutralMapAdapter" in source
    assert 'renderer: "same_document_renderer"' in source
    assert "fallback_map_frame_unavailable" not in source
    assert "input[data-layer-id]" in source
    assert "observations.expectedLayerIds.pretrip" in source
    guard_source = source.split(
        "async function inspectMapLibrePreMigrationRegressionGuard", 1
    )[1].split("async function inspectAllDashboardMapSurfaces", 1)[0]
    for renderer_neutral_term in (
        "map_feature",
        "layer_id",
        "artifact_id",
        "bbox",
        "highlight_state",
        "selected_evidence",
    ):
        assert renderer_neutral_term in guard_source
    for old_svg_detail in (
        "data-layer-group",
        "svg.querySelector",
        "path.getTotalLength",
    ):
        assert old_svg_detail not in guard_source

    assert package["scripts"]["qualification:check"].endswith("--scope guard")
    assert package["scripts"]["qualification:check:full"].endswith("--scope guard")
    assert "npm run qualification:check\n" in workflow
    assert policy["qualification_boundary"] == (
        "maplibre_pre_migration_regression_guard"
    )
    assert "live_map_gesture_incomplete" in policy["paused_global_blocks"]
    assert "live_layer_toggle_incomplete" in policy["paused_global_blocks"]
    assert "fallback_map_unusable" in policy["global_blocks"]
    assert "new_operational_or_safety_authority" in policy["global_blocks"]


def test_live_browser_runner_has_exhaustive_operation_and_visual_gates() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    for required_symbol in (
        "loadBrowserActionContract",
        "auditAllRouteVisualStates",
        "auditAllVisibleControls",
        "discoverVisibleControlsInFrame",
        "inspectAllDashboardMapSurfaces",
        "inspectNavigationDynamicRudyTiles",
        "prepareMapSurfaceForBrowserOperation",
        "captureMapFailureCheckpoint",
        "inspectCanonicalLayerToggles",
        "inspectEmbeddedCwaControls",
        "captureVisualCheckpoint",
        "analyzeScreenshotPixels",
        "assertVisualQuality",
    ):
        assert required_symbol in source
    for evidence_ref in (
        "browser-control-inventory.json",
        "browser-control-state-traces.json",
        "browser-layer-availability-evidence.json",
        "browser-visual-audit.json",
        "browser-map-interactions.json",
        "browser-layer-interactions.json",
    ):
        assert evidence_ref in source
    assert "EFFECT_AUTHORIZATION_REQUIRED" in source
    assert "panButtonInteractions" in source
    assert "canonical-layer-preset" in source
    assert "NO_VISUAL_CHANGE" in source
    assert "contract_tests_are_dashboard_evidence" in source


def test_q0057_main_map_weather_layers_enforce_required_visible_na_contract() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "async function inspectMainMapWeatherLayerAvailability" in source
    evidence_source = source.split(
        "async function inspectMainMapWeatherLayerAvailability", 1
    )[1].split("async function waitForCanonicalEmbeddedMapReady", 1)[0]
    assert '"antecedent-rain"' in evidence_source
    assert '"cwa-qpf"' in evidence_source
    assert '"cwa-weather"' in evidence_source
    assert '"soil-moisture"' in evidence_source
    assert '"weather-api"' in evidence_source
    assert "canonicalLayerRenderState" in evidence_source
    assert '"REQUIRED_AVAILABLE"' in evidence_source
    assert '"REQUIRED_NA"' in evidence_source
    assert "waitForCanonicalEmbeddedMapReady" not in evidence_source
    assert "const mapFrameBoundaryRaw = await frameHost.evaluate" in evidence_source
    assert "source: evidenceSafeUrl(mapFrameBoundaryRaw.source)" in evidence_source
    assert (
        'await openDashboard(page, observations.baseUrl, readyProjectId, "outdoor-weather");'
        in evidence_source
    )
    assert "paired_weather_embedded_state" in evidence_source
    assert 'required_contract: "weather_hydrology_layer_required"' in evidence_source
    assert 'normalized_unavailable_state: mainMapAvailability' in evidence_source
    assert 'unavailable_semantics: "NA"' in evidence_source
    assert "dashboard_weather_layer_required" in evidence_source
    assert "dashboard_weather_layer_availability" in evidence_source
    assert "dashboard_weather_layer_state_text" in evidence_source
    assert 'frame.locator("#map [data-layer-group]")' in evidence_source
    assert "record.settled = settled" in evidence_source
    assert "settledAvailability" in evidence_source
    assert 'assert(initial.control_visible' in evidence_source
    assert 'assert(initial.dashboard_weather_layer_required === "true"' in evidence_source
    assert 'assert(["AVAILABLE", "NA"].includes(mainMapAvailability)' in evidence_source
    assert "product_behavior_changed: true" in evidence_source
    assert (
        'evidence_semantics: "weather_hydrology_required_unavailable_normalized_to_na"'
        in evidence_source
    )
    assert 'id: "runtime-main-map-weather-layer-availability-evidence"' in source
    count_source = source.split("blocking_layer_gaps:", 1)[1].split(", 0),", 1)[0]
    assert '"REQUIRED_AVAILABLE"' in count_source
    assert '"REQUIRED_NA"' in count_source


def test_q0063_control_state_evidence_has_a_dedicated_read_only_runtime_case() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "async function waitForIssue0063TerminalState" in source
    assert "async function captureIssue0063RouteControlInventory" in source
    assert "async function inspectIssue0063ControlStateEvidence" in source
    evidence_source = source.split(
        "async function inspectIssue0063ControlStateEvidence", 1
    )[1].split("async function operateVisibleControl", 1)[0]
    for route in (
        "outdoor-permission",
        "runtime-audit",
        "outdoor-weather",
        "emergency",
    ):
        assert f'"{route}"' in evidence_source
    assert '"before_reload"' in evidence_source
    assert '"after_reload"' in evidence_source
    assert "captureIssue0063RouteControlInventory" in evidence_source
    assert "runVisibleControlDiscoveryWithTimeout" not in evidence_source
    assert "recordBrowserAction" in evidence_source
    assert "beforeReloadWait" in evidence_source
    assert "afterReloadWait" in evidence_source
    assert 'kind: "terminal_state_wait"' in source
    assert 'id: "runtime-q0063-control-state-evidence"' in source
    assert "product_behavior_changed: false" in evidence_source


def test_runtime_audit_request_timing_has_a_dedicated_live_read_only_case() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "async function inspectRuntimeAuditRequestTimingEvidence" in source
    evidence_source = source.split(
        "async function inspectRuntimeAuditRequestTimingEvidence", 1
    )[1].split("async function inspectApprovedMoreEvidenceControls", 1)[0]
    assert '"/admin/runtime-audit"' in evidence_source
    assert 'kind: "runtime_audit_request_timing"' in evidence_source
    assert '"before_reload"' in evidence_source
    assert '"after_reload"' in evidence_source
    assert "performance.now()" in evidence_source
    assert 'params.set("include_all", "true")' in evidence_source
    assert "captureVisualCheckpoint" in evidence_source
    assert "product_behavior_changed: false" in evidence_source
    case_source = source.split(
        'id: "runtime-audit-request-timing-evidence"', 1
    )[1].split('id: "runtime-all-visible-controls"', 1)[0]
    assert "readOnly: true" in case_source
    assert "liveRuntime: true" in case_source
    assert "fixtureEligible: false" in case_source
    assert "recordVideo: false" in case_source


def test_diagnostic_control_case_uses_real_batch_then_bounded_individual_retests() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    diagnostic_case = source.split(
        'id: "diagnostic-controls"', 1
    )[1].split(
        'id: "runtime-diagnostic-ux-more-evidence"', 1
    )[0]

    assert "recordVideo: false" in diagnostic_case
    assert 'recordBrowserAction(observations, "click", "diagnostic-diag-all")' in diagnostic_case
    assert 'const representativeRetestIds = ["DASH-001", "DASH-003", "DASH-012", "DASH-018", "DASH-033", "DASH-037"]' in diagnostic_case
    assert "uniqueRetestIds.size === cases" in diagnostic_case
    assert "batchSnapshot.summary.failed === 0" in diagnostic_case
    assert "window.scrollTo(0, 0)" in diagnostic_case
    assert 'workspace.scrollTop = 0' in diagnostic_case
    assert '{fullPage: false, domRoot: diagnostic}' in diagnostic_case
    assert "for (let index = 0; index < retries; index += 1)" not in diagnostic_case


def test_control_audit_waits_for_dynamic_runtime_routes_to_settle() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  audit: runner.controlRouteRequiresTerminalWait("runtime-audit"),
  permission: runner.controlRouteRequiresTerminalWait("outdoor-permission"),
  navigation: runner.controlRouteRequiresTerminalWait("outdoor-navigation"),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "audit": True,
        "permission": True,
        "navigation": False,
    }
    assert '"before_control_discovery"' in source
    assert '"after_control_operation"' in source


def test_approved_q0056_q0061_repairs_have_targeted_live_browser_evidence() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "async function inspectApprovedTargetedRepairEvidence" in source
    evidence_source = source.split(
        "async function inspectApprovedTargetedRepairEvidence", 1
    )[1].split("function attachQualificationPageObservers", 1)[0]
    assert '"outdoor-navigation"' in evidence_source
    assert '"outdoor-weather"' in evidence_source
    assert '"outdoor-permission"' in evidence_source
    assert '"runtime-audit"' in evidence_source
    assert "hoverSelectedEvidence" in evidence_source
    assert "dashboardMapHoverHint" in evidence_source
    assert 'weatherFrame.locator("#hoverHint")' in evidence_source
    assert "weatherCwaHintDocument === frame.contentDocument" in evidence_source
    assert 'rect[data-evidence-type="cwa_weather_environment_evidence"]' in evidence_source
    assert "headless_hint_observation" in evidence_source
    assert '"EVIDENCE_TARGET_NOT_VISIBLE_IN_HEADLESS_BROWSER"' in evidence_source
    assert 'weatherEvidence.first().waitFor({state: "visible", timeout: 30_000})' in evidence_source
    assert "product_verdict_allowed: false" in evidence_source
    assert "navigation_fit_control_non_overlap" in evidence_source
    assert "font_size_px" in evidence_source
    assert "permission_compact_readability" in evidence_source
    assert "async function auditPermissionCompactReadability" in source
    assert "function assertPermissionCompactReadability" in source
    assert "async function inspectPermissionCompactReadabilityEvidence" in source
    assert '".permission-node small"' in source
    assert '".permission-eyebrow"' in source
    assert '".permission-simulation-form label"' in source
    assert "below_10_count === 0" in source
    assert "not_rendered_selectors" in source
    assert 'id: "runtime-approved-targeted-repair-evidence"' in source
    targeted_case = source.split(
        'id: "runtime-approved-targeted-repair-evidence"', 1
    )[1].split('id: "runtime-permission-compact-readability-evidence"', 1)[0]
    assert "evidenceOnly: true" in targeted_case
    permission_case = source.split(
        'id: "runtime-permission-compact-readability-evidence"', 1
    )[1].split('id: "runtime-approved-more-evidence-controls"', 1)[0]
    assert "evidenceOnly: true" in permission_case
    assert "inspectPermissionCompactReadabilityEvidence" in permission_case


def test_approved_more_evidence_controls_have_targeted_live_browser_proof() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "async function inspectApprovedMoreEvidenceControls" in source
    evidence_source = source.split(
        "async function inspectApprovedMoreEvidenceControls", 1
    )[1].split("function attachQualificationPageObservers", 1)[0]
    assert '"outdoor-navigation"' in evidence_source
    assert 'data-navigation-terrain-event-id' in evidence_source
    assert '"outdoor-permission"' in evidence_source
    assert "data-permission-refresh" in evidence_source
    assert "permissionRefreshCount" in evidence_source
    assert "degraded_typed_unavailable" in evidence_source
    assert 'availability_status: "TYPED_UNAVAILABLE"' in evidence_source
    assert "An unavailable Permission Refresh must not be awaited." in evidence_source
    assert '"emergency"' in evidence_source
    assert 'for (const label of ["Pace Fit", "System"])' in evidence_source
    assert "captureVisualCheckpoint" in evidence_source
    assert "before" in evidence_source
    assert "after" in evidence_source
    assert 'id: "runtime-approved-more-evidence-controls"' in source
    targeted_case = source.split(
        'id: "runtime-approved-more-evidence-controls"', 1
    )[1].split('id: "debug-live-runtime-read-evidence"', 1)[0]
    assert "evidenceOnly: true" in targeted_case
    assert "recordVideo: false" in targeted_case


def test_q0063_reload_evidence_has_before_and_after_screenshots() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    evidence_source = source.split(
        "async function inspectIssue0063ControlStateEvidence", 1
    )[1].split("async function operateVisibleControl", 1)[0]

    assert '"before-reload"' in evidence_source
    assert '"after-reload"' in evidence_source
    assert "captureVisualCheckpoint" in evidence_source


def test_diagnostic_diag_all_disables_video_before_packet_sealing() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    diagnostic_case = source.split(
        'id: "diagnostic-diag-all-read-only"', 1
    )[1].split(
        'id: "navigation-dynamic-rudy-tiles"', 1
    )[0]

    assert "recordVideo: false" in diagnostic_case

    mobile_case = source.split(
        'id: "runtime-approved-mobile-layouts"', 1
    )[1].split('id: "debug-live-runtime-read-evidence"', 1)[0]
    assert "living_containment" in mobile_case
    assert 'page.locator(".living-event").first().waitFor' in mobile_case
    assert "body_scroll_width" in mobile_case
    assert "event_overflow_count" in mobile_case


def test_live_browser_runner_preserves_failures_and_target_specific_visual_proof() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert '[data-dashboard-map-hint-title]' in source.split(
        "async function discoverVisibleControlsInFrame", 1
    )[1].split("async function discoverVisibleControls", 1)[0]
    assert 'delegatedTo = "runtime-all-map-surface-interactions"' in source
    assert 'terminal_state: "OPERATION_ERROR"' in source
    assert "const CONTROL_OPERATION_TIMEOUT_MS = 90_000;" in source
    assert "const CONTROL_DISCOVERY_TIMEOUT_MS = 90_000;" in source
    assert "const CONTROL_ROUTE_TIMEOUT_MS = 10 * 60_000;" in source
    assert "const CONTROL_ROUTE_STATE_RESET_LIMIT = 32;" in source
    assert "async function runVisibleControlOperationWithTimeout(" in source
    assert "async function runVisibleControlDiscoveryWithTimeout(" in source
    assert 'error.code = "CONTROL_OPERATION_TIMEOUT"' in source
    assert 'error.code = "CONTROL_DISCOVERY_TIMEOUT"' in source
    assert 'error.code = "CONTROL_ROUTE_TIMEOUT"' in source
    assert "const stableIdentityText = hasStableIdentityAttributes ? \"\" : text;" in source
    assert "const passiveControls = controls.filter(control => (" in source
    assert "for (const control of passiveControls)" in source
    assert "const segmentedTraceByRoute = definition.segmentedTraceByRoute === true;" in source
    assert 'Object.defineProperty(observations, "_browserContext"' in source
    assert 'const routeTraceDirectory = path.join(observations.caseDirectory, "traces");' in source
    assert "observations.segmentedTraces.push(" in source
    assert "selfManagedPages: true" in source
    assert "segmentedTraceByRoute: true" in source
    assert "const routePage = await browserContext.newPage();" in source
    assert "attachQualificationPageObservers(routePage, observations);" in source
    assert "route_aborted_after_operation_error" in source
    assert "routePage.close({runBeforeUnload: false})" in source
    assert "const CASE_FINALIZATION_TIMEOUT_MS = 90_000;" in source
    assert "const VIDEO_CASE_FINALIZATION_TIMEOUT_MS = 5 * 60_000;" in source
    assert "function caseFinalizationTimeoutMs(definition = {})" in source
    assert "function collectRecordedPagesBeforeContext(" in source
    assert "async function finalizeRecordedVideosAfterContext(" in source
    assert "const ROUTE_TRACE_FINALIZATION_TIMEOUT_MS = 30_000;" in source
    assert "async function runCaseFinalizerWithTimeout(" in source
    assert 'error.code = "CASE_FINALIZATION_TIMEOUT"' in source
    assert "const CASE_EXECUTION_TIMEOUT_MS = 30 * 60_000;" in source
    assert "async function runCaseExecutionWithTimeout(" in source
    assert 'error.code = "CASE_EXECUTION_TIMEOUT"' in source
    assert "await runCaseExecutionWithTimeout(" in source
    assert 'status = executionTimedOut ? "BLOCKED" : "FAIL";' in source
    assert '"case-progress.jsonl"' in source
    assert '"route_started"' in source
    assert '"route_completed"' in source
    assert '"route_failed"' in source
    assert '"route_trace_stop_started"' in source
    assert '"route_trace_finalized"' in source
    assert '"route_trace_finalization_failed"' in source
    assert "browserContext.tracing.start({screenshots: false, snapshots: false, sources: false})" in source
    assert '"control_operation_started"' in source
    assert '"control_operation_completed"' in source
    assert '"control_refresh_reload_started"' in source
    assert '"control_state_reset_started"' in source
    assert "descriptor.tag === \"summary\"" in source
    assert "[data-navigation-maplibre-fit]" in source
    assert "visual_quality_status: visualQualityStatus" in source
    assert "snapshots: false" in source
    assert "sources: false" in source
    assert "if (routeTraceError) throw routeTraceError;" not in source
    assert '"trace-stop"' in source
    assert '"context-close"' in source
    assert '"recorded-page-close-delegated"' in source
    assert '"recorded-video-finalized"' in source
    assert 'runCaseFinalizerWithTimeout("browser-close"' in source
    assert "const finalizationTimeoutMs = caseFinalizationTimeoutMs(definition);" in source
    layer_toggle_source = source.split(
        "async function inspectCanonicalLayerToggles", 1
    )[1].split("function attachQualificationPageObservers", 1)[0]
    assert (
        layer_toggle_source.count(
            'await openDashboard(page, observations.baseUrl, readyProjectId, "map");'
        )
        == 1
    )
    assert (
        "const individualLayerPage = await observations._browserContext.newPage();"
        in layer_toggle_source
    )
    assert "attachQualificationPageObservers(individualLayerPage, observations);" in layer_toggle_source
    assert "presetPage.close({runBeforeUnload: false})" in layer_toggle_source
    assert layer_toggle_source.index(
        "presetPage.close({runBeforeUnload: false})"
    ) < layer_toggle_source.index(
        "const individualLayerPage = await observations._browserContext.newPage();"
    )
    visual_checkpoint_source = source.split(
        "async function captureVisualCheckpoint", 1
    )[1].split("function workspaceDigest", 1)[0]
    assert visual_checkpoint_source.count("timeout: 60_000") >= 3
    assert '"visual_checkpoint_screenshot_retry"' in visual_checkpoint_source
    assert "isTransientControlLocatorError(error)" in visual_checkpoint_source
    assert source.count("observations.controlInventory = inventory;") >= 2
    assert 'locator(":scope > summary")' in source
    assert "fit-before" in source
    assert "evidence-hint-before" in source
    assert "selectHoverableEvidenceCandidate" in source
    assert "inspectNavigationMapLibreGestures" in source
    assert 'surface.id === "navigation-map"' in source
    assert 'page.keyboard.down("Shift")' in source


def test_video_finalization_closes_context_before_waiting_for_video_paths() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "function collectRecordedPagesBeforeContext(" in source
    assert "async function finalizeRecordedVideosAfterContext(" in source
    collection_source = source.split(
        "function collectRecordedPagesBeforeContext", 1
    )[1].split("async function finalizeRecordedVideosAfterContext", 1)[0]
    finalization_source = source.split(
        "async function runIsolatedCase", 1
    )[1].split("async function main", 1)[0]
    assert '"recorded-page-close-delegated"' in collection_source
    assert "recording.page.close({runBeforeUnload: false})" not in finalization_source
    assert finalization_source.index('"context-close"') < finalization_source.index(
        "finalizeRecordedVideosAfterContext("
    )


def test_junit_xml_escape_removes_ansi_and_xml_illegal_controls() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(runner.xmlEscape("\\u001b[31mFAIL\\u001b[0m\\u0000<&"));
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout
    assert completed.stdout == "FAIL&lt;&amp;"


def test_live_browser_runner_scales_visual_and_control_audits() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    dom_metrics = source.split(
        "async function collectDomVisualMetrics", 1
    )[1].split("function visualQualityIssues", 1)[0]
    checkpoint = source.split(
        "async function captureVisualCheckpoint", 1
    )[1].split("function workspaceDigest", 1)[0]
    discovery = source.split(
        "async function discoverVisibleControlsInFrame", 1
    )[1].split("async function discoverVisibleControls", 1)[0]

    assert "viewportInteractive" in dom_metrics
    assert "overlapGrid" in dom_metrics
    assert "analysis_duration_ms" in dom_metrics
    assert "effectiveTextPixelSize" in dom_metrics
    assert "HTMLCanvasElement" in dom_metrics
    assert '"visual_checkpoint_started"' in checkpoint
    assert '"visual_checkpoint_completed"' in checkpoint
    assert '"visual_checkpoint_dom_completed"' in checkpoint
    assert "scoutQualificationCompleted" in discovery
    assert "isMapLibraryControl" in discovery


def test_live_browser_runner_accepts_only_browser_observed_raster_provenance() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    native_map = source.split(
        "async function inspectNativeMapGestures", 1
    )[1].split("async function inspectNavigationMapLibreGestures", 1)[0]

    assert "browserObservedRasterProvenance" in source
    assert "resource_entries" in native_map
    assert "tile_load_state" in native_map
    assert "browser_observed_raster_provenance_count" in native_map


def test_live_browser_runner_handles_dynamic_controls_and_effect_oracles() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    operation = source.split(
        "async function operateVisibleControl", 1
    )[1].split("async function runVisibleControlOperationWithTimeout", 1)[0]
    aggregate = source.split(
        "const browserCoverageFindings = [", 1
    )[1].split("const findings = [", 1)[0]

    assert "refreshControlDescriptor" in operation
    assert "new_visual_issues" in operation
    assert "baseline_visual_issues" in operation
    assert "popup_loaded" in operation
    assert "effect_oracle" in operation
    assert 'descriptor.tag === "svg"' in operation
    assert "groupControlCoverageFindings(controlInventory)" in aggregate
    assert '"OPERATION_ERROR"' in source.split(
        "function groupControlCoverageFindings", 1
    )[1].split("function normalizedTelemetryTarget", 1)[0]
    assert "groupVisualQualityFindings" in source
    assert 'if (finalizationErrors.length && status === "PASS")' in source
    assert "captureAvailableCaseScreenshot" in source
    assert 'item.terminal_state === "OPERATION_ERROR"' in source.split(
        "blocking_control_gaps:", 1
    )[1].split("map_surface_results:", 1)[0]
    assert "classifyUncompletedControl" in source
    assert "controlCoverageGapRecord" in source
    assert "product_defect_claimed: false" in source
    assert "controlStateTraces" in source
    assert "frame_lifecycle" in source
    assert "control_discovery_timing" in source


def test_browser_runner_preserves_typed_control_coverage_causes() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const base = {{route: "outdoor-permission", identity: "stable-control"}};
const causes = [
  "disabled_in_runtime_state",
  "disappeared_before_operation",
  "nonvisible_after_discovery",
  "single_runtime_value",
  "route_aborted_after_operation_error",
];
process.stdout.write(JSON.stringify(Object.fromEntries(
  causes.map(cause => [cause, runner.controlCoverageGapRecord(base, cause)])
)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert {
        key: value["terminal_state"] for key, value in payload.items()
    } == {
        "disabled_in_runtime_state": "DISABLED_IN_RUNTIME_STATE",
        "disappeared_before_operation": "DISAPPEARED_BEFORE_OPERATION",
        "nonvisible_after_discovery": "NONVISIBLE_AFTER_DISCOVERY",
        "single_runtime_value": "SINGLE_RUNTIME_VALUE",
        "route_aborted_after_operation_error": "ROUTE_ABORTED_AFTER_OPERATION_ERROR",
    }
    assert all(value["product_defect_claimed"] is False for value in payload.values())
    assert all(value["coverage_gap_kind"] for value in payload.values())


def test_live_browser_runner_records_typed_layer_availability_and_runtime_evidence() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    layer_state = source.split(
        "async function canonicalLayerRenderState", 1
    )[1].split("async function inspectEmbeddedCwaControls", 1)[0]
    layer_audit = source.split(
        "async function inspectCanonicalLayerToggles", 1
    )[1].split("function attachQualificationPageObservers", 1)[0]
    permission_case = source.split(
        'id: "permission-live-runtime-boundary"', 1
    )[1].split('id: "permission-degraded-candidate-boundary"', 1)[0]

    assert "control_disabled" in layer_state
    assert "control_visible" in layer_state
    assert "availability_reason" in layer_state
    assert 'terminal_state: "NOT_EXERCISED"' in layer_audit
    assert "render_provenance" in layer_audit
    assert "resource_entries" in layer_audit
    assert "waitForCanonicalEmbeddedMapReady" in source
    assert layer_audit.count("await waitForCanonicalEmbeddedMapReady(") >= 3
    readiness = source.split(
        "async function waitForCanonicalEmbeddedMapReady", 1
    )[1].split("async function inspectEmbeddedCwaControls", 1)[0]
    assert "#dashboardMapLoading" in readiness
    assert "scoutPretripProjectBridge" in readiness
    assert "expectedProjectId" in readiness
    assert source.count('(await menu.getAttribute("open")) === null') >= 3
    assert '(await advanced.getAttribute("open")) === null' in source
    assert '!(await menu.getAttribute("open"))' not in source
    assert '!(await advanced.getAttribute("open"))' not in source
    assert "embedded_duplicate_layer_menu_not_exposed" in source
    assert 'terminal_state: "NOT_EXPOSED"' in source
    assert 'delegated_to: "runtime-all-visible-controls"' in source
    assert '"OPERATED",\n            "NOT_EXPOSED",\n            "REQUIRED_AVAILABLE",\n            "REQUIRED_NA",' in source
    assert "waitForFunction" in permission_case
    assert "observedStateTransitions" in permission_case
    assert 'fetch("/assistant/status")' in permission_case
    assert "assistantReadiness" in permission_case


def test_live_browser_runner_collects_debug_read_evidence_without_hardware_probe() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")
    debug_case = source.split(
        'id: "debug-live-runtime-read-evidence"', 1
    )[1].split('id: "runtime-all-visible-controls"', 1)[0]

    for endpoint in (
        "/debug/events?limit=200",
        "/debug/state",
        "/debug/messages",
        "/debug/mobile-wearable/ingress",
        "/debug/monitoring",
        "/debug/stream",
    ):
        assert endpoint in debug_case
    assert "/admin/hardware-readiness/context" not in debug_case
    assert "first_chunk_observed" in debug_case
    assert "availability_state" in debug_case
    assert "evidenceOnly: true" in debug_case
    assert "!definition.evidenceOnly" in source.split(
        "function buildCapabilityResults", 1
    )[1].split("function writeJson", 1)[0]
    assert "target_hint_source" in source
    assert 'const captureRoot = page.locator("body")' in source
    assert "assert(layerInteractions.length > 0" in source

    diagnostic_case = source.split(
        'id: "diagnostic-diag-all-read-only"', 1
    )[1].split('id: "navigation-dynamic-rudy-tiles"', 1)[0]
    assert "failedCases.length === 0" not in diagnostic_case
    assert "diagnostic_content_status" in diagnostic_case

    assert 'id: "runtime-approved-mobile-layouts"' in source
    assert 'page.locator("#dashboardNavToggle").click()' in source
    assert "mobile-sidebar-open" in source
    assert "mobile-sidebar-diagnostic-visible" in source
    assert "result.sidebar.scroll_top > 0" in source
    assert "living-mobile-header" in source
    assert "architecture-mobile-sticky" in source
    assert "debug-mobile-table" in source
    assert "debug-mobile-table-after-horizontal-scroll" in source
    assert "result.debug_pills.length > 0" in source
    assert "mobile_map_primary_workspace" in source
    assert 'waitForRouteVisualReadiness(page, "map", readyProjectId, observations)' in source
    assert "map_nav_layer_non_overlap" in source
    assert "map_evidence_collapsed" in source
    assert "layer_menu_open" in source

    assert 'id: "runtime-diagnostic-ux-more-evidence"' in source
    assert "diagnosticUxEvidence" in source
    assert "layerReadinessTimelines" in source
    assert '"browser-layer-readiness-evidence.json"' in source
    assert '"browser-diagnostic-ux-evidence.json"' in source

    map_case = source.split(
        'id: "runtime-all-map-surface-interactions"', 1
    )[1].split('id: "runtime-main-map-weather-layer-availability-evidence"', 1)[0]
    assert "recordVideo: false" in map_case
    assert "finalizationTimeoutMs: 5 * 60_000" in map_case
    assert 'evidenceProfile: "trace-plus-per-interaction-visual-checkpoints"' in map_case

    layer_case = source.split(
        'id: "runtime-all-layer-toggle-integrity"', 1
    )[1].split('id: "diagnostic-controls"', 1)[0]
    assert "recordVideo: false" in layer_case
    assert 'evidenceProfile: "trace-plus-per-layer-visual-checkpoints"' in layer_case

    capability_builder = source.split(
        "function buildCapabilityResults", 1
    )[1].split("function writeJson", 1)[0]
    assert "caseFinalizationErrors" in capability_builder
    assert 'output["qualification.evidence.integrity"] = evidenceFinalizationFailed ? "FAIL" : "PASS";' in capability_builder
    assert "recorderFinalizedBeforeSeal" in source
    assert "recorder_finalized_before_seal: recorderFinalizedBeforeSeal" in source
    assert (
        "video_directory: definition.recordVideo !== false && fs.existsSync(videoDirectory)"
        in source
    )
    assert "const restoreCurrentControl = async action =>" in source
    assert "restore = async () => restoreCurrentControl" in source

    route_navigation_case = source.split(
        'id: "runtime-route-navigation"', 1
    )[1].split('id: "runtime-all-route-visual-states-desktop"', 1)[0]
    assert "revealThroughClosedDetails" in route_navigation_case
    assert "scrollIntoViewIfNeeded" in route_navigation_case

    navigation_tiles_case = source.split(
        'id: "navigation-dynamic-rudy-tiles"', 1
    )[1].split('id: "architecture-dynamic-rudy-tiles"', 1)[0]
    assert "inspectNavigationDynamicRudyTiles" in navigation_tiles_case

    navigation_tiles_helper = source.split(
        "async function inspectNavigationDynamicRudyTiles", 1
    )[1].split("async function inspectWeatherDynamicMap", 1)[0]
    assert navigation_tiles_helper.index(
        "const requestStart = observations.requests.length;"
    ) < navigation_tiles_helper.index("await openDashboard(")


def test_browser_runner_times_out_a_never_resolving_case_body() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
(async () => {{
  const startedAt = Date.now();
  try {{
    await runner.runCaseExecutionWithTimeout(
      {{ id: "qualification-hanging-test", executionTimeoutMs: 50 }},
      () => new Promise(() => {{}}),
    );
    process.exitCode = 2;
  }} catch (error) {{
    process.stdout.write(JSON.stringify({{
      code: error.code,
      caseId: error.caseId,
      timeoutMs: error.timeoutMs,
      elapsedMs: Date.now() - startedAt,
    }}));
  }}
}})();
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload == {
        "code": "CASE_EXECUTION_TIMEOUT",
        "caseId": "qualification-hanging-test",
        "timeoutMs": 50,
        "elapsedMs": payload["elapsedMs"],
    }
    assert 40 <= payload["elapsedMs"] < 1_000


def test_browser_runner_times_out_a_never_resolving_route_trace_stop() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
(async () => {{
  const startedAt = Date.now();
  try {{
    await runner.runCaseFinalizerWithTimeout(
      "route-trace-stop:test",
      () => new Promise(() => {{}}),
      50,
    );
    process.exitCode = 2;
  }} catch (error) {{
    process.stdout.write(JSON.stringify({{
      code: error.code,
      timeoutMs: error.timeoutMs,
      elapsedMs: Date.now() - startedAt,
    }}));
  }}
}})();
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["code"] == "CASE_FINALIZATION_TIMEOUT"
    assert payload["timeoutMs"] == 50
    assert 40 <= payload["elapsedMs"] < 1_000


def test_browser_runner_gives_recorded_video_a_longer_bounded_finalization_window() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  noVideo: runner.caseFinalizationTimeoutMs({{recordVideo: false}}),
  video: runner.caseFinalizationTimeoutMs({{}}),
  configured: runner.caseFinalizationTimeoutMs({{recordVideo: true, finalizationTimeoutMs: 1234}}),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "noVideo": 90_000,
        "video": 300_000,
        "configured": 1_234,
    }


def test_browser_runner_marks_evidence_integrity_failed_when_recorder_did_not_finalize() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const failed = runner.buildCapabilityResults([], [{{
  observations: {{caseFinalizationErrors: ["context-close timeout"]}},
}}]);
const clean = runner.buildCapabilityResults([], [{{observations: {{}}}}]);
process.stdout.write(JSON.stringify({{
  failed: failed["qualification.evidence.integrity"],
  clean: clean["qualification.evidence.integrity"],
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {"failed": "FAIL", "clean": "PASS"}


def test_browser_runner_aggregates_repeated_delegated_map_evidence_targets() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const controls = [
  {{route: "map", context_id: "frame:map", tag: "path", delegated_to: "runtime-all-map-surface-interactions", data_attributes: {{evidenceType: "trail", sourceId: "source-a"}}, identity: "source-a", key: "a", text: ""}},
  {{route: "map", context_id: "frame:map", tag: "path", delegated_to: "runtime-all-map-surface-interactions", data_attributes: {{evidenceType: "trail", sourceId: "source-b"}}, identity: "source-b", key: "b", text: ""}},
  {{route: "map", context_id: "frame:map", tag: "circle", delegated_to: "runtime-all-map-surface-interactions", data_attributes: {{evidenceType: "trail", sourceId: "source-c"}}, identity: "source-c", key: "c", text: ""}},
  {{route: "map", context_id: "frame:map", tag: "button", delegated_to: "runtime-all-map-surface-interactions", data_attributes: {{}}, identity: "zoom", key: "zoom", text: "Zoom"}},
];
process.stdout.write(JSON.stringify(runner.aggregateDelegatedMapEvidenceControls(controls)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert len(payload) == 3
    path_group = next(item for item in payload if item.get("tag") == "path")
    assert path_group["aggregate_member_count"] == 2
    assert path_group["aggregate_source_samples"] == ["source-a", "source-b"]
    assert "source-a" not in path_group["identity"]
    assert "sourceId" not in path_group["data_attributes"]
    assert sum(item.get("aggregate_member_count", 1) for item in payload) == 4


def test_browser_runner_samples_dense_repeated_selection_controls() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const controls = Array.from({{length: 9}}, (_unused, index) => ({{
  route: "outdoor-architecture",
  context_id: "main",
  tag: "g",
  role: "button",
  aria_label: `bin-${{index}}`,
  delegated_to: null,
  disabled: false,
  data_attributes: {{architectureSelectionSurface: "fingerprint-bin", architectureBinId: `bin-${{index}}`}},
  identity: `bin-${{index}}`,
  key: `key-${{index}}`,
  text: "",
}}));
process.stdout.write(JSON.stringify(runner.sampleRepeatedSelectionControls(controls)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert len(payload) == 3
    assert [item["aggregate_representative_position"] for item in payload] == [
        "first",
        "middle",
        "last",
    ]
    assert all(item["aggregate_member_count"] == 9 for item in payload)
    assert all(item["aggregate_sampling_policy"] == "first-middle-last" for item in payload)
    assert payload[0]["aggregate_member_samples"] == ["bin-0", "bin-4", "bin-8"]
    assert all("architectureBinId" not in item["identity"] for item in payload)


def test_browser_runner_samples_dense_navigation_terrain_event_controls() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const controls = Array.from({{length: 80}}, (_unused, index) => ({{
  route: "outdoor-navigation",
  context_id: "main",
  tag: "button",
  role: "",
  aria_label: `terrain-event-${{index}}`,
  delegated_to: null,
  disabled: false,
  data_attributes: {{navigationTerrainEventId: `event-${{index}}`}},
  identity: `event-${{index}}`,
  key: `event-key-${{index}}`,
  text: "",
}}));
process.stdout.write(JSON.stringify(runner.sampleRepeatedSelectionControls(controls)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert len(payload) == 3
    assert [item["aggregate_representative_position"] for item in payload] == [
        "first",
        "middle",
        "last",
    ]
    assert all(item["aggregate_member_count"] == 80 for item in payload)
    assert payload[0]["aggregate_member_samples"] == ["event-0", "event-39", "event-79"]
    assert all("navigationTerrainEventId" not in item["identity"] for item in payload)


def test_browser_runner_samples_dense_debug_event_and_runtime_audit_selectors() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const debugEvents = Array.from({{length: 12}}, (_unused, index) => ({{
  route: "surface-debug",
  context_id: "frame:debug",
  tag: "div",
  role: "button",
  aria_label: `debug-event-${{index}}`,
  delegated_to: null,
  disabled: false,
  data_attributes: {{eventId: `event-${{index}}`, eventIndex: String(index), mapRef: "runtime route"}},
  identity: `debug-event-${{index}}`,
  key: `debug-event-key-${{index}}`,
  text: "",
}}));
const assistantQuestions = Array.from({{length: 9}}, (_unused, index) => ({{
  route: "surface-debug",
  context_id: "frame:debug",
  tag: "button",
  role: "",
  aria_label: `Why did cp.${{index}} become L0?`,
  delegated_to: null,
  disabled: false,
  data_attributes: {{assistantQuestion: `Why did cp.${{index}} become L0?`}},
  identity: `assistant-question-${{index}}`,
  key: `assistant-question-key-${{index}}`,
  text: "Why L2?",
}}));
const auditDays = Array.from({{length: 15}}, (_unused, index) => ({{
  route: "runtime-audit",
  context_id: "main",
  tag: "button",
  role: "",
  aria_label: "",
  delegated_to: null,
  disabled: false,
  data_attributes: {{runtimeAuditDay: `2026-08-${{String(index + 1).padStart(2, "0")}}`}},
  identity: `audit-day-${{index}}`,
  key: `audit-day-key-${{index}}`,
  text: "",
}}));
process.stdout.write(JSON.stringify({{
  debugEvents: runner.sampleRepeatedSelectionControls(debugEvents),
  assistantQuestions: runner.sampleRepeatedSelectionControls(assistantQuestions),
  auditDays: runner.sampleRepeatedSelectionControls(auditDays),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert len(payload["debugEvents"]) == 3
    assert len(payload["assistantQuestions"]) == 3
    assert len(payload["auditDays"]) == 3
    assert payload["debugEvents"][0]["aggregate_member_samples"] == [
        "event-0",
        "event-5",
        "event-11",
    ]
    assert payload["auditDays"][0]["aggregate_member_samples"] == [
        "2026-08-01",
        "2026-08-08",
        "2026-08-15",
    ]
    assert all("eventId" not in item["identity"] for item in payload["debugEvents"])
    assert all("2026-08-" not in item["identity"] for item in payload["auditDays"])


def test_browser_runner_canonicalizes_ephemeral_debug_assistant_questions_by_intent() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const makeControl = question => ({{
  route: "surface-debug",
  context_id: "frame:debug",
  tag: "button",
  id: "",
  name: "",
  type: "button",
  role: "",
  aria_label: question,
  data_attributes: {{assistantQuestion: question}},
  text: question,
  identity: question,
  key: `raw-${{question}}`,
}});
const values = [
  runner.canonicalizeEphemeralControlIdentity(makeControl("Why did CP2 become an L2 event?")),
  runner.canonicalizeEphemeralControlIdentity(makeControl("Why did cp.014 become an L0 event?")),
  runner.canonicalizeEphemeralControlIdentity(makeControl("Which sources support this timeline state?")),
];
process.stdout.write(JSON.stringify(values));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    values = json.loads(completed.stdout)
    assert values[0]["identity"] == values[1]["identity"]
    assert values[0]["identity"] != values[2]["identity"]
    assert values[0]["ephemeral_control_family"] == "debug-assistant:level-rationale"
    assert values[2]["ephemeral_control_family"] == "debug-assistant:source-support"
    assert values[0]["key"].startswith("raw-")


def test_browser_runner_canonicalizes_navigation_review_controls_by_decision() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const makeControl = (decision, target) => ({{
  route: "outdoor-navigation",
  context_id: "main",
  tag: "button",
  id: "",
  name: "",
  type: "button",
  role: "",
  aria_label: "",
  data_attributes: {{navigationReviewDecision: decision, navigationReviewTarget: target}},
  text: decision,
  identity: `${{decision}}:${{target}}`,
  key: `raw-${{decision}}-${{target}}`,
}});
const supportA = runner.canonicalizeEphemeralControlIdentity(makeControl("support", "ridge.001"));
const supportB = runner.canonicalizeEphemeralControlIdentity(makeControl("support", "event.002"));
const reject = runner.canonicalizeEphemeralControlIdentity(makeControl("reject", "ridge.001"));
process.stdout.write(JSON.stringify({{
  sameSupportIdentity: supportA.identity === supportB.identity,
  differentDecisionIdentity: supportA.identity !== reject.identity,
  family: reject.ephemeral_control_family,
  rejectIsEffectful: runner.controlIdentityIsEffectful(reject),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "sameSupportIdentity": True,
        "differentDecisionIdentity": True,
        "family": "navigation-review:reject",
        "rejectIsEffectful": False,
    }


def test_browser_runner_recognizes_aria_current_as_an_active_control_state() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  current: runner.controlIsAlreadyActive({{role: "button"}}, {{aria_current: "true"}}),
  pressed: runner.controlIsAlreadyActive({{role: "button"}}, {{aria_pressed: "true"}}),
  selectedTab: runner.controlIsAlreadyActive({{role: "tab"}}, {{aria_selected: "true"}}),
  inactive: runner.controlIsAlreadyActive({{role: "button"}}, {{aria_current: "false"}}),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "current": True,
        "pressed": True,
        "selectedTab": True,
        "inactive": False,
    }


def test_browser_runner_delegates_generic_map_interaction_surfaces_to_map_qualification() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "[data-map-interaction-mode]" in source
    assert 'delegatedTo = "runtime-all-map-surface-interactions"' in source


def test_browser_runner_operates_current_state_content_before_switching_state_selector() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const controls = [
  {{identity: "tab-map", role: "tab", aria_selected: "false", data_attributes: {{evidenceTab: "map_risk"}}}},
  {{identity: "group-map", role: "", aria_selected: null, data_attributes: {{evidenceGroupTab: "map_risk", evidenceGroupToggle: "true"}}}},
  {{identity: "terrain-event", role: "", aria_selected: null, data_attributes: {{navigationTerrainEventId: "event-1"}}}},
];
const first = runner.selectNextVisibleControlCandidate(controls, new Set());
const second = runner.selectNextVisibleControlCandidate(controls, new Set(["group-map"]));
const modalFirst = runner.selectNextVisibleControlCandidate([
  {{identity: "underlay", role: "", aria_selected: null, within_modal: false, data_attributes: {{}}}},
  {{identity: "modal-cancel", role: "", aria_selected: null, within_modal: true, data_attributes: {{emergencyFieldConfirmCancel: "true"}}}},
], new Set());
const embeddedFirst = runner.selectNextVisibleControlCandidate([
  {{identity: "main-control", context_id: "main", role: "", aria_selected: null, within_modal: false, data_attributes: {{}}}},
  {{identity: "frame-tab", context_id: "frame:approval", role: "tab", aria_selected: "false", within_modal: false, data_attributes: {{evidenceTab: "approval"}}}},
], new Set());
const assistantBeforeEvent = runner.selectNextVisibleControlCandidate([
  {{identity: "event", context_id: "frame:debug", role: "button", aria_selected: null, within_modal: false, data_attributes: {{eventId: "event-1"}}}},
  {{identity: "question", context_id: "frame:debug", role: "", aria_selected: null, within_modal: false, data_attributes: {{assistantQuestion: "What is missing?"}}}},
], new Set());
const terrainEventBeforeOuterSelector = runner.selectNextVisibleControlCandidate([
  {{identity: "outer-selector", context_id: "main", role: "", aria_selected: null, within_modal: false, data_attributes: {{navigationTerrainEvidenceDomain: "prior"}}}},
  {{identity: "terrain-item", context_id: "main", role: "", aria_selected: null, within_modal: false, data_attributes: {{navigationTerrainEventId: "event-1"}}}},
], new Set());
process.stdout.write(JSON.stringify({{
  first: first.identity,
  second: second.identity,
  modalFirst: modalFirst.identity,
  embeddedFirst: embeddedFirst.identity,
  assistantBeforeEvent: assistantBeforeEvent.identity,
  terrainEventBeforeOuterSelector: terrainEventBeforeOuterSelector.identity,
  repeatableCancel: runner.controlIsRepeatableModalDismissal({{
    within_modal: true,
    data_attributes: {{emergencyFieldConfirmCancel: "true"}},
    text: "Cancel",
  }}),
  repeatableSubmit: runner.controlIsRepeatableModalDismissal({{
    within_modal: true,
    data_attributes: {{emergencyFieldConfirmSubmit: "true"}},
    text: "Confirm",
  }}),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "first": "group-map",
        "second": "terrain-event",
        "modalFirst": "modal-cancel",
        "embeddedFirst": "frame-tab",
        "assistantBeforeEvent": "question",
        "terrainEventBeforeOuterSelector": "terrain-item",
        "repeatableCancel": True,
        "repeatableSubmit": False,
    }


def test_browser_runner_semantic_signature_tracks_live_form_values_without_harness_markers() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert 'replace(/\\sdata-scout-qualification-' in source
    assert "form_state" in source
    assert 'value: "value" in element ? String(element.value)' in source


def test_browser_runner_treats_reset_controls_as_effectful() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  reset: runner.controlIdentityIsEffectful({{
    id: "mobileIngressResetButton",
    text: "歸零",
    aria_label: "",
    data_attributes: {{}},
  }}),
  refresh: runner.controlIdentityIsEffectful({{
    id: "refreshButton",
    text: "Refresh",
    aria_label: "",
    data_attributes: {{}},
  }}),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {"reset": True, "refresh": False}


def test_browser_runner_discovers_embedded_frames_with_one_shared_time_window() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
(async () => {{
  const startedAt = Date.now();
  const values = await runner.mapControlFramesConcurrently([40, 40, 40], async (delay, index) => {{
    await new Promise(resolve => setTimeout(resolve, delay));
    return index;
  }});
  process.stdout.write(JSON.stringify({{values, elapsedMs: Date.now() - startedAt}}));
}})();
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["values"] == [0, 1, 2]
    assert 30 <= payload["elapsedMs"] < 110


def test_browser_runner_does_not_locate_a_synthetic_frame_discovery_error() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
(async () => {{
  const page = {{frames() {{ throw new Error("must not inspect frames"); }}}};
  const marked = await runner.markControlCompleted(page, {{
    key: "q-frame-error-deadbeef",
    discovery_error: "control-frame-context timed out",
  }});
  process.stdout.write(JSON.stringify({{marked}}));
}})();
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {"marked": False}


def test_browser_runner_can_bound_control_debugging_to_one_contracted_route() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const routes = ["home", "emergency", "settings"];
process.stdout.write(JSON.stringify({{
  full: runner.selectControlAuditRoutes(routes, null),
  targeted: runner.selectControlAuditRoutes(routes, "emergency"),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "full": ["home", "emergency", "settings"],
        "targeted": ["emergency"],
    }


def test_browser_runner_accepts_permission_controls_as_typed_unavailable_only_when_degraded() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  degraded: runner.permissionControlIsTypedUnavailable("outdoor-permission", {{
    permission_data_status: "degraded",
    projection_status: "degraded",
  }}),
  ready: runner.permissionControlIsTypedUnavailable("outdoor-permission", {{
    permission_data_status: "ready",
    projection_status: "ready",
  }}),
  otherRoute: runner.permissionControlIsTypedUnavailable("outdoor-weather", {{
    permission_data_status: "degraded",
    projection_status: "degraded",
  }}),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "degraded": True,
        "ready": False,
        "otherRoute": False,
    }
    action_contract = json.loads(
        (ROOT / "qualification/dashboard-browser-action-contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert "TYPED_UNAVAILABLE" in action_contract["paused_legacy_map_contract"][
        "control_coverage"
    ]["allowed_terminal_states"]


def test_browser_runner_separates_delegation_and_visual_warnings_from_operation_state() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const delegated = runner.classifyPassiveControl({{
  delegated_to: "runtime-all-map-surface-interactions",
  disabled: true,
  data_attributes: {{}},
}});
const operated = runner.controlOperationTerminalState({{
  semantic_changed: true,
  visual_changed: true,
  popup_loaded: false,
}});
const unchanged = runner.controlOperationTerminalState({{
  semantic_changed: false,
  visual_changed: false,
  popup_loaded: false,
}});
process.stdout.write(JSON.stringify({{delegated, operated, unchanged}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["delegated"]["terminal_state"] == "DELEGATED"
    assert payload["operated"] == "OPERATED"
    assert payload["unchanged"] == "NO_STATE_CHANGE"


def test_browser_runner_classifies_only_known_transient_dom_failures_for_one_retry() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  detachedFrame: runner.isTransientFrameDiscoveryError("frame.evaluate: Frame was detached"),
  detachedElement: runner.isTransientControlLocatorError("Element is not attached to the DOM"),
  staleLocator: runner.isTransientControlLocatorError(
    "locator.click: Timeout 30000ms exceeded while waiting for locator('[data-scout-qualification-control-key=key]')"
  ),
  detachedFrameLocator: runner.isTransientControlLocatorError("locator.count: Frame was detached"),
  ordinaryTimeout: runner.isTransientControlLocatorError("page.goto: Timeout 60000ms exceeded"),
  productFailure: runner.isTransientFrameDiscoveryError("HTTP 500")
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload == {
        "detachedFrame": True,
        "detachedElement": True,
        "staleLocator": True,
        "detachedFrameLocator": True,
        "ordinaryTimeout": False,
        "productFailure": False,
    }


def test_browser_runner_waits_for_a_real_popup_url_before_claiming_success() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  empty: runner.isLoadedPopupUrl(""),
  blank: runner.isLoadedPopupUrl("about:blank"),
  dashboardDebug: runner.isLoadedPopupUrl("http://127.0.0.1:9099/admin/debug?projectId=project")
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "empty": False,
        "blank": False,
        "dashboardDebug": True,
    }


def test_browser_runner_uses_the_visible_root_for_special_dashboard_routes() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(JSON.stringify({{
  home: runner.dashboardRouteRootSelector("home"),
  map: runner.dashboardRouteRootSelector("map"),
  agent: runner.dashboardRouteRootSelector("agent")
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "home": "#workspace",
        "map": "#dashboardMap",
        "agent": "#dashboardAgent",
    }


def test_browser_runner_bounds_embedded_visual_audits_and_avoids_duplicate_video() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "frame.frameElement()" in source
    assert '"route-frame-visibility"' in source
    assert "ROUTE_FRAME_VISIBILITY_TIMEOUT_MS" in source
    assert "const visibleInViewport = element =>" in source
    assert "const centerInsideClippingAncestors = element =>" in source
    assert ".filter(visibleInViewport)" in source
    assert 'element.closest("details:not([open])")' in source
    assert "const insideStickyLayer = element =>" in source
    assert "const isMapInteractionSurface = element =>" in source
    assert "waitForRouteVisualReadiness(page, route" in source
    assert source.count("recordVideo: false") >= 4


def test_browser_runner_bounds_route_visual_failure_summary() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const audits = Array.from({{length: 30}}, (_unused, index) => ({{
  route: `route-${{index}}`,
  error: `route error ${{index}}`,
  frames: [{{error: `frame error ${{index}}`}}]
}}));
const groups = Array.from({{length: 40}}, (_unused, index) => ({{
  observed_behavior: `visual-${{index}}`,
  occurrence_count: index + 1,
  evidence_refs: ["a.png", "b.png", "c.png", "d.png"]
}}));
process.stdout.write(JSON.stringify(runner.summarizeRouteVisualAuditFailure(audits, groups)));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["failed_route_count"] == 30
    assert payload["operational_issue_count"] == 60
    assert len(payload["operational_issue_samples"]) == 12
    assert payload["visual_issue_group_count"] == 40
    assert len(payload["visual_issue_groups"]) == 24
    assert all(len(item["evidence_refs"]) == 3 for item in payload["visual_issue_groups"])


def test_browser_runner_bounds_control_coverage_failure_summary() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const blocking = Array.from({{length: 40}}, (_unused, index) => ({{
  route: index < 20 ? "map" : "navigation",
  terminal_state: index % 2 ? "NOT_EXERCISED" : "OPERATION_ERROR",
  identity: `control-${{index}}`,
  detail: "bounded-detail",
}}));
const summary = runner.summarizeControlCoverageFailure(blocking, [{{
  observed_behavior: "occluded_controls",
  occurrence_count: 12,
  evidence_refs: ["a.png", "b.png", "c.png", "d.png"],
}}]);
process.stdout.write(JSON.stringify(summary));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["blocking_control_count"] == 40
    assert payload["blocking_control_states"] == {
        "OPERATION_ERROR": 20,
        "NOT_EXERCISED": 20,
    }
    assert len(payload["blocking_control_samples"]) == 12
    assert payload["visual_issue_group_count"] == 1
    assert payload["visual_issue_groups"][0]["evidence_refs"] == [
        "a.png",
        "b.png",
        "c.png",
    ]


def test_browser_runner_groups_visual_warnings_by_semantic_root() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const checkpoints = [
  {{case_id: "controls", id: "a", screenshot: "a.png", issues: ['x:a: low_readability_text=["span:Surface","small:Alpha","label:One","span:Data","small:Beta","label:Two"]']}},
  {{case_id: "controls", id: "b", screenshot: "b.png", issues: ['x:b: low_readability_text=["span:Changed","small:Gamma","label:Three","span:Other","small:Delta","label:Four"]']}},
];
process.stdout.write(JSON.stringify({{
  roots: checkpoints.map(item => runner.visualIssueRootSignature(item.issues[0])),
  groups: runner.groupVisualQualityFindings(checkpoints),
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["roots"][0] == payload["roots"][1]
    assert len(payload["groups"]) == 1
    assert payload["groups"][0]["occurrence_count"] == 2
    assert payload["groups"][0]["evidence_refs"] == ["a.png", "b.png"]
    assert len(payload["groups"][0]["example_observed_behaviors"]) == 2


def test_browser_runner_groups_control_gaps_and_deduplicates_resource_console_errors() -> None:
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const controls = Array.from({{length: 12}}, (_unused, index) => ({{
  case_id: "controls",
  route: index < 6 ? "map" : "navigation",
  terminal_state: "NOT_EXERCISED",
  identity: `control-${{index}}`,
  detail: "This control was disabled in the selected live runtime state; an executable real state is required before the function can qualify.",
  before_screenshot: `before-${{index}}.png`,
  after_screenshot: `after-${{index}}.png`,
}}));
const controlGroups = runner.groupControlCoverageFindings(controls);
const telemetryGroups = runner.groupBrowserTelemetryFindings(
  [{{case_id: "controls", detail: "Failed to load resource: the server responded with a status of 404 (Not Found) @ http://127.0.0.1:9099/debug/state:0:0"}}],
  [],
  [{{case_id: "controls", status: 404, url: "http://127.0.0.1:9099/debug/state"}}],
);
process.stdout.write(JSON.stringify({{controlGroups, telemetryGroups}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stdout
    payload = json.loads(completed.stdout)
    assert len(payload["controlGroups"]) == 2
    assert sorted(item["occurrence_count"] for item in payload["controlGroups"]) == [6, 6]
    assert all(len(item["control_identity_samples"]) == 5 for item in payload["controlGroups"])
    assert len(payload["telemetryGroups"]) == 1
    assert payload["telemetryGroups"][0]["network_occurrence_count"] == 1
    assert payload["telemetryGroups"][0]["console_occurrence_count"] == 1


def test_qualification_policy_blocks_intentional_p0_regression() -> None:
    from scripts.qualification.evaluate_qualification import evaluate_results

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    results = {
        capability["id"]: "PASS"
        for surface in manifest["surfaces"]
        for capability in surface["capabilities"]
    }
    results["qualification.fixture.active_p0_matrix"] = "INSUFFICIENT_EVIDENCE"

    clean = evaluate_results(manifest, results, policy)
    assert clean["merge_permitted"] is True
    assert any(
        item["capability_id"] == "qualification.fixture.active_p0_matrix"
        for item in clean["excluded_capabilities"]
    )
    assert {
        item["capability_id"] for item in clean["excluded_capabilities"]
    }.issuperset(
        {
            "dashboard.route_context.regeneration_api",
            "dashboard.debug.hardware_readiness",
        }
    )

    results["dashboard.diagnostic.read_only"] = "FAIL"
    outside_boundary = evaluate_results(manifest, results, policy)
    assert outside_boundary["merge_permitted"] is True
    assert any(
        item["capability_id"] == "dashboard.diagnostic.read_only"
        and item["reason"] == "outside_maplibre_boundary_freeze"
        for item in outside_boundary["excluded_capabilities"]
    )

    results["dashboard.browser.maplibre_pre_migration_regression_guard"] = "FAIL"
    regression = evaluate_results(manifest, results, policy)
    assert regression["merge_permitted"] is False
    assert regression["machine_verdict"] == "FAIL"
    assert regression["blockers"][0]["capability_id"] == (
        "dashboard.browser.maplibre_pre_migration_regression_guard"
    )

    results["dashboard.browser.maplibre_pre_migration_regression_guard"] = "PASS"
    results["dashboard.maps.all_surface_interactions"] = "FAIL"
    legacy_regression = evaluate_results(
        manifest,
        results,
        policy,
        qualification_scope="legacy-full",
    )
    assert legacy_regression["merge_permitted"] is False
    assert legacy_regression["blockers"][0]["capability_id"] == (
        "dashboard.maps.all_surface_interactions"
    )


def test_evidence_index_rejects_tampering(tmp_path: Path) -> None:
    from scripts.qualification.verify_evidence import build_index, verify_index

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "results.json").write_text(
        json.dumps({"ok": True}),
        encoding="utf-8",
    )
    index = build_index(evidence_root)
    index_path = evidence_root / "evidence-index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    verified = verify_index(evidence_root, index_path)
    assert verified["valid"] is True
    assert verified["mismatches"] == []

    (evidence_root / "results.json").write_text(
        json.dumps({"ok": False}),
        encoding="utf-8",
    )
    tampered = verify_index(evidence_root, index_path)
    assert tampered["valid"] is False
    assert tampered["mismatches"] == ["results.json"]


def test_evidence_index_declares_path_sort_canonicalization(tmp_path: Path) -> None:
    from scripts.qualification.verify_evidence import _root_hash, build_index

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "z-last.json").write_text("{}", encoding="utf-8")
    (evidence_root / "a-first.json").write_text("{}", encoding="utf-8")

    index = build_index(evidence_root)

    assert index["root_canonicalization"] == {
        "digest_algorithm": "sha256",
        "encoding": "utf-8",
        "line_format": "{sha256}  {path}\n",
        "sort_key": "path",
        "sort_order": "lexicographic_posix_relative_path",
    }
    assert _root_hash(list(reversed(index["files"]))) == index[
        "evidence_root_sha256"
    ]


def test_evidence_index_rejects_mislabeled_screenshot_bytes(tmp_path: Path) -> None:
    from scripts.qualification.verify_evidence import build_index, verify_index

    evidence_root = tmp_path / "evidence"
    screenshots = evidence_root / "screenshots"
    screenshots.mkdir(parents=True)
    screenshot = screenshots / "route-home.png"
    screenshot.write_bytes(MINIMAL_PNG)
    index = build_index(evidence_root)
    assert index["files"][0]["media_type"] == "image/png"

    index_path = evidence_root / "evidence-index.json"
    index["files"][0]["media_type"] = "image/jpeg"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    declared_mismatch = verify_index(evidence_root, index_path)
    assert declared_mismatch["valid"] is False
    assert declared_mismatch["declared_media_type_mismatches"] == [
        {
            "actual_media_type": "image/png",
            "declared_media_type": "image/jpeg",
            "path": "screenshots/route-home.png",
        }
    ]

    index["files"][0]["media_type"] = "image/png"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    screenshot.write_bytes(b"\xff\xd8\xff\xe0JFIF-mislabeled-as-png")

    verified = verify_index(evidence_root, index_path)
    assert verified["valid"] is False
    assert verified["media_type_mismatches"] == [
        {
            "detected_media_type": "image/jpeg",
            "expected_media_type": "image/png",
            "path": "screenshots/route-home.png",
        }
    ]

    with pytest.raises(ValueError, match="screenshot media type mismatch"):
        build_index(evidence_root)


def test_browser_runner_seals_explicit_canonicalization_and_media_types(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    assert node is not None
    evidence_root = tmp_path / "evidence"
    screenshots = evidence_root / "screenshots"
    screenshots.mkdir(parents=True)
    (screenshots / "route-home.png").write_bytes(MINIMAL_PNG)
    (evidence_root / "results.json").write_text("{}", encoding="utf-8")
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const index = runner.writeEvidenceIndex({json.dumps(str(evidence_root))});
process.stdout.write(JSON.stringify(index));
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout
    index = json.loads(completed.stdout)
    assert index["root_canonicalization"] == {
        "digest_algorithm": "sha256",
        "encoding": "utf-8",
        "line_format": "{sha256}  {path}\n",
        "sort_key": "path",
        "sort_order": "lexicographic_posix_relative_path",
    }
    image_entry = next(
        item for item in index["files"] if item["path"].endswith(".png")
    )
    assert image_entry["media_type"] == "image/png"


def test_reviewer_input_excludes_raw_worktree_patch_and_source_contents(
    tmp_path: Path,
) -> None:
    from scripts.qualification.prepare_reviewer_input import build_reviewer_input
    from scripts.qualification.verify_evidence import build_index

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    shutil.copyfile(MANIFEST, evidence_root / "manifest.snapshot.yaml")
    (evidence_root / "results.json").write_text(
        json.dumps(
            {
                "commit_sha": "a" * 40,
                "capability_results": {},
                "results": [],
                "runtime_provenance": "live_operational_dashboard",
                "runtime_continuity_verified": True,
                "runner_started_runtime": False,
                "official_qualification_eligible": True,
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / "machine-verdict.json").write_text(
        json.dumps({"machine_verdict": "PASS", "merge_permitted": True}),
        encoding="utf-8",
    )
    (evidence_root / "runtime-attestation.json").write_text(
        json.dumps(
            {
                "runtime_provenance": "live_operational_dashboard",
                "continuity_verified": True,
                "runner_started_runtime": False,
                "initial": {"runtime_port": 9099},
                "final": {"runtime_port": 9099},
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / "candidate-findings.json").write_text(
        json.dumps(
            {
                "findings": [],
                "canonical_review_items_written": False,
            }
        ),
        encoding="utf-8",
    )
    for relative in (
        "browser-action-contract.snapshot.json",
        "browser-control-inventory.json",
        "browser-control-state-traces.json",
        "browser-layer-availability-evidence.json",
        "browser-visual-audit.json",
        "browser-map-interactions.json",
        "browser-layer-interactions.json",
    ):
        (evidence_root / relative).write_text("{}", encoding="utf-8")
    screenshots = evidence_root / "screenshots"
    screenshots.mkdir()
    (screenshots / "route-home.png").write_bytes(MINIMAL_PNG)
    private_marker = "PRIVATE_DIRTY_VALUE_SHOULD_NOT_LEAVE"
    (evidence_root / "git-diff.patch").write_text(
        f"+{private_marker}\n",
        encoding="utf-8",
    )
    index = build_index(evidence_root)
    (evidence_root / "evidence-index.json").write_text(
        json.dumps(index),
        encoding="utf-8",
    )

    payload = build_reviewer_input(evidence_root)
    encoded = json.dumps(payload)

    assert private_marker not in encoded
    assert "git_diff" not in payload
    assert "test_sources" not in payload
    assert payload["change_evidence"]["git_diff"]["content_included"] is False
    assert payload["change_evidence"]["git_diff"]["sha256"]
    assert payload["runtime_attestation_sha256"]
    assert set(payload["browser_operation_evidence"]) == {
        "browser-action-contract.snapshot.json",
        "browser-control-inventory.json",
        "browser-control-state-traces.json",
        "browser-layer-availability-evidence.json",
        "browser-visual-audit.json",
        "browser-map-interactions.json",
        "browser-layer-interactions.json",
    }
    assert payload["screenshots"] == ["screenshots/route-home.png"]
    assert payload["screenshot_bindings"] == [
        {
            "media_type": "image/png",
            "path": "screenshots/route-home.png",
            "sha256": index["files"][
                next(
                    offset
                    for offset, entry in enumerate(index["files"])
                    if entry["path"] == "screenshots/route-home.png"
                )
            ]["sha256"],
        }
    ]
    assert payload["visual_review_contract"][
        "reviewer_must_inspect_the_bound_images"
    ] is True
    assert payload["visual_review_contract"][
        "screenshot_media_type_must_match_bytes"
    ] is True
    assert payload["review_boundary"]["required_channel"] == (
        "gpt-pro-collaboration-in-app-browser"
    )
    assert all(
        binding["content_included"] is False
        for binding in payload["change_evidence"]["source_bindings"]
    )


def test_reviewer_input_rejects_fixture_packet(tmp_path: Path) -> None:
    from scripts.qualification.prepare_reviewer_input import build_reviewer_input
    from scripts.qualification.verify_evidence import build_index

    evidence_root = tmp_path / "fixture-evidence"
    evidence_root.mkdir()
    shutil.copyfile(MANIFEST, evidence_root / "manifest.snapshot.yaml")
    (evidence_root / "results.json").write_text(
        json.dumps(
            {
                "commit_sha": "a" * 40,
                "runtime_provenance": None,
                "fixture_provenance": "bounded_synthetic_workspace",
                "capability_results": {},
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / "machine-verdict.json").write_text(
        json.dumps({"machine_verdict": "PASS", "merge_permitted": True}),
        encoding="utf-8",
    )
    (evidence_root / "candidate-findings.json").write_text(
        json.dumps({"findings": []}),
        encoding="utf-8",
    )
    (evidence_root / "evidence-index.json").write_text(
        json.dumps(build_index(evidence_root)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="live runtime provenance"):
        build_reviewer_input(evidence_root)


def test_direct_api_review_cannot_satisfy_gpt_pro_collaboration_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts.qualification.run_independent_review import run_review

    monkeypatch.setenv("OPENAI_API_KEY", "qualification-test-placeholder")

    with pytest.raises(RuntimeError, match="gpt-pro-collaboration"):
        run_review(tmp_path, model="gpt-5")


def test_independent_review_rejects_sensitive_reviewer_payload() -> None:
    from scripts.qualification.run_independent_review import (
        _assert_reviewer_input_safe,
    )

    with pytest.raises(RuntimeError, match="sensitive material"):
        _assert_reviewer_input_safe(
            {"request": {"access_token": "qualification-test-secret-value"}}
        )


def test_fixture_matrix_covers_active_p0_state_transitions() -> None:
    matrix = json.loads(STATE_MATRIX.read_text(encoding="utf-8"))
    states = {fixture["state"] for fixture in matrix["fixtures"]}

    assert {
        "ready",
        "degraded",
        "blocked",
        "stale",
        "partial",
        "zero_evidence",
        "assistant_enabled",
        "assistant_disabled",
    }.issubset(states)
    for fixture in matrix["fixtures"]:
        assert fixture["candidate_only"] is True
        assert fixture["runtime_safety_truth"] is False
        assert fixture["writes_allowed_during_qualification"] is False


def test_native_tile_fixture_expands_a_bounded_viewport_halo() -> None:
    from scripts.qualification.seed_dashboard_fixture import (
        QUALIFICATION_TILE_HALO,
        _tile_coordinates_with_halo,
    )

    coordinates = _tile_coordinates_with_halo(
        [{"z": 12, "x": 3500, "y": 1700}],
        halo=QUALIFICATION_TILE_HALO,
    )

    assert QUALIFICATION_TILE_HALO == 5
    assert len(coordinates) == 121
    assert (12, 3500, 1700) in coordinates
    assert (12, 3495, 1695) in coordinates
    assert (12, 3505, 1705) in coordinates
    assert _tile_coordinates_with_halo(
        [{"z": 0, "x": 0, "y": 0}],
        halo=QUALIFICATION_TILE_HALO,
    ) == {(0, 0, 0)}


def test_seeded_permission_state_fixtures_are_executable(tmp_path: Path) -> None:
    from scripts.qualification.seed_dashboard_fixture import seed_fixture
    from scout_contextual_permission_workbench import (
        ContextualPermissionConflict,
        ContextualPermissionWorkbench,
    )

    seed_fixture(tmp_path)
    store_root = tmp_path / ".qualification-read-store"
    degraded = ContextualPermissionWorkbench(
        project_root=tmp_path / "qualification_degraded",
        store_root=store_root,
    ).projection()
    assert degraded.status == "degraded"
    assert degraded.candidate_only is True
    assert degraded.runtime_safety_truth is False

    with pytest.raises(ContextualPermissionConflict) as stale_error:
        ContextualPermissionWorkbench(
            project_root=tmp_path / "qualification_stale",
            store_root=store_root,
        ).projection()
    assert stale_error.value.code == "contextual_permission_projection_stale"

    admission = ContextualPermissionWorkbench(
        project_root=tmp_path / "qualification_stale",
        store_root=store_root,
        allow_stale_projection=True,
    ).projection_rebuild_admission()
    assert admission.eligible is False
    assert admission.baseline_capability == "legacy_sparse.v1"
    assert store_root.exists() is False


def test_assistant_fixture_server_exposes_enabled_and_disabled_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from scripts.qualification.dashboard_fixture_server import create_app

    monkeypatch.setenv("SCOUT_QUALIFICATION_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("SCOUT_QUALIFICATION_ASSISTANT_MODE", "enabled")
    enabled = TestClient(create_app()).get("/assistant/status")
    assert enabled.status_code == 200
    assert enabled.json()["provider_class"] == "QualificationAssistantProvider"

    monkeypatch.setenv("SCOUT_QUALIFICATION_ASSISTANT_MODE", "disabled")
    disabled = TestClient(create_app()).get("/assistant/status")
    assert disabled.status_code == 404


def test_ready_fixture_seeds_bounded_candidate_evidence_and_variants(
    tmp_path: Path,
) -> None:
    from scripts.qualification.seed_dashboard_fixture import (
        SOURCE_PROJECT,
        _seed_ready_evidence,
        _seed_route_context_variants,
    )

    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(SOURCE_PROJECT, project_root)
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    project = _seed_ready_evidence(project_root, project)
    variants = _seed_route_context_variants(project_root)

    assert project["boss_point_count"] > 0
    assert project["mileage_tag_alignment_count"] > 0
    for ref_key in (
        "risk_score_points_ref",
        "calibrated_risk_heatmap_ref",
        "cwa_qpf_grid_ref",
        "cwa_weather_evidence_ref",
        "soil_moisture_grid_ref",
        "antecedent_rain_grid_ref",
    ):
        assert (project_root / project[ref_key]).is_file()
    assert variants["variant_count"] == 5
    comparison = json.loads(
        (project_root / variants["comparison_ref"]).read_text(encoding="utf-8")
    )
    assert len(comparison["variants"]) == 5
    assert comparison["synthetic_fixture"] is True
    assert comparison["one_model_call_complete"] is False
    assert comparison["boundary"]["candidate_only"] is True
    assert comparison["boundary"]["runtime_safety_truth"] is False
    assert all(
        (project_root / variants["output_dir_ref"] / item["relative_ref"]).is_file()
        for item in comparison["variants"]
    )


def test_zero_evidence_fixture_endpoints_fail_gracefully(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from scripts.qualification.dashboard_fixture_server import create_app

    project_id = "qualification_zero_evidence"
    project_root = tmp_path / project_id
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "artifact_kind": "qualification_synthetic_project",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SCOUT_QUALIFICATION_WORKSPACE_ROOT", str(tmp_path))
    client = TestClient(create_app())

    compact = client.get(f"/admin/pretrip/projects/{project_id}?compact=1")
    admin_projection = client.get(
        f"/admin/pretrip/projects/{project_id}/admin-projection"
    )
    debug_events = client.get(
        f"/admin/pretrip/projects/{project_id}/debug-projection-events"
    )

    assert compact.status_code == 200
    assert compact.json()["qualification_fixture_state"] == "zero_evidence"
    assert compact.json()["evidence_timeline"]["counts"]["total_evidence_count"] == 0
    assert admin_projection.status_code == 200
    assert debug_events.status_code == 200
    assert debug_events.json()["events"] == []
    assert all(
        response.json()["boundary"]["runtime_safety_truth"] is False
        for response in (compact, admin_projection, debug_events)
    )


def test_browser_runner_isolates_cases_and_captures_failure_evidence() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    assert "async function runIsolatedCase(" in source
    assert "context.tracing.start(" in source
    assert "context.tracing.stop({ path: tracePath })" in source
    assert "recordVideo" in source
    assert "fs.mkdirSync(caseDirectory, { recursive: true });" in source
    assert "definition.recordVideo !== false" in source
    assert 'id: "runtime-all-visible-controls"' in source
    assert "recordVideo: false" in source
    assert (
        'if (element.matches("[data-route]")) '
        'delegatedTo = "runtime-route-navigation";'
    ) in source
    assert "for (const definition of caseDefinitions)" in source
    assert "results.push(await runIsolatedCase(" in source
    assert "acquireQualificationLease(" in source
    assert "qualificationRuntimeLeasePath(" in source
    assert 'leaseError.code = "QUALIFICATION_LEASE_HELD"' in source
    assert 'error.code = "QUALIFICATION_OUTPUT_ROOT_NOT_EMPTY"' in source
    assert 'process.argv.includes("--prepared-output-root")' in source
    assert "PREPARED_OUTPUT_ROOT_ALLOWED_FILES" in source
    assert "PREPARED_OUTPUT_ROOT_REQUIRED_FILES" in source
    assert "workspaceDigest" in source
    assert "unexpected_workspace_mutation" in source
    assert 'parsed.searchParams.has("TILEMATRIX")' in source
    assert 'const quiet = process.argv.includes("--quiet")' in source
    assert "const failedCases = Object.entries(snapshot.results)" in source
    assert "scripts.qualification.dashboard_fixture_server:create_app" in source
    assert 'process.argv.includes("--fixture-harness")' in source
    assert "SCOUT_QUALIFICATION_RUNTIME_URL" in source
    assert "SCOUT_QUALIFICATION_PROJECT_ID" in source
    assert 'runtime_provenance: "live_operational_dashboard"' in source
    assert "runner_started_runtime: false" in source
    assert "definition.liveRuntime === true" in source
    assert 'writeJson(outputRoot, "runtime-attestation.json"' in source
    assert 'writeJson(outputRoot, "browser-action-log.json"' in source
    assert 'writeJson(outputRoot, "candidate-findings.json"' in source
    assert "AWAITING_GPT_PRO_REVIEW" in source
    assert "runtime-route-navigation" in source
    assert "diagnostic-retest:" in source
    assert "disabledBaseUrl" in source
    assert "function writeAggregateEvidence(" in source


def test_qualification_wrapper_explicitly_authorizes_its_prepared_output_root() -> None:
    source = QUALIFICATION_RUNNER.read_text(encoding="utf-8")

    assert 'browser_command.append("--prepared-output-root")' in source


def test_qualification_guard_runs_only_boundary_contract_and_layer_contract() -> None:
    from scripts.qualification.run_qualification import _qualification_test_paths

    guard = _qualification_test_paths("guard")
    legacy = _qualification_test_paths("legacy-full")

    assert guard == {
        "focused": ("tests/qualification/test_dashboard_qualification_bootstrap.py",),
        "package": ("tests/test_scout_layer_contract.py",),
    }
    assert "tests/test_scout_dashboard_page.py" not in guard["focused"]
    assert "tests/test_pretrip_admin_page.py" not in guard["focused"]
    assert "tests/test_pretrip_admin_api.py" not in guard["focused"]
    assert "tests/test_scout_dashboard_page.py" in legacy["focused"]
    assert "tests/test_pretrip_admin_page.py" in legacy["focused"]
    assert "tests/test_pretrip_admin_api.py" in legacy["focused"]


def test_browser_runner_accepts_only_exact_wrapper_prepared_files(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    assert node is not None
    output_root = tmp_path / "prepared"
    (output_root / "commands").mkdir(parents=True)
    prepared_files = (
        "commands/focused-pytest.log",
        "commands/repository-package-pytest.log",
        "environment.json",
        "git-diff.patch",
        "junit-focused.xml",
        "junit-package.xml",
        "manifest-validation.json",
        "manifest.snapshot.yaml",
    )
    for relative_path in prepared_files:
        (output_root / relative_path).write_text("prepared\n", encoding="utf-8")
    script = f"""
const fs = require("fs");
const path = require("path");
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const outputRoot = {json.dumps(str(output_root))};
runner.assertQualificationOutputRootAvailable(outputRoot, {{prepared: true}});
fs.writeFileSync(path.join(outputRoot, "results.json"), "{{}}\\n");
let blocked = null;
try {{
  runner.assertQualificationOutputRootAvailable(outputRoot, {{prepared: true}});
}} catch (error) {{
  blocked = error.code;
}}
process.stdout.write(JSON.stringify({{blocked}}));
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "blocked": "QUALIFICATION_OUTPUT_ROOT_NOT_EMPTY"
    }


def test_browser_runner_exclusive_lease_blocks_overlapping_operators(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    assert node is not None
    lock_path = tmp_path / "runtime.lock"
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const lockPath = {json.dumps(str(lock_path))};
const first = runner.acquireQualificationLease(lockPath, {{scope: "first"}});
let blocked = null;
try {{
  runner.acquireQualificationLease(lockPath, {{scope: "second"}});
}} catch (error) {{
  blocked = error.code;
}}
runner.releaseQualificationLease(first);
const afterRelease = runner.acquireQualificationLease(lockPath, {{scope: "third"}});
runner.releaseQualificationLease(afterRelease);
process.stdout.write(JSON.stringify({{blocked, released: !require("fs").existsSync(lockPath)}}));
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "blocked": "QUALIFICATION_LEASE_HELD",
        "released": True,
    }


def test_browser_runner_host_lease_path_is_shared_across_worktrees(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    assert node is not None
    first_worktree = tmp_path / "first-worktree"
    second_worktree = tmp_path / "second-worktree"
    first_worktree.mkdir()
    second_worktree.mkdir()
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
process.stdout.write(runner.qualificationHostLeasePath());
"""

    paths = []
    for worktree in (first_worktree, second_worktree):
        completed = subprocess.run(
            [node, "-e", script],
            cwd=worktree,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=10,
        )
        assert completed.returncode == 0, completed.stdout
        paths.append(completed.stdout)

    assert paths[0] == paths[1]
    assert "scout-dashboard-qualification" in paths[0]
    assert "artifacts/qualification" not in paths[0]


def test_browser_runner_recovers_a_dead_process_lease(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node is not None
    lock_path = tmp_path / "stale.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema": "scout.dashboardQualificationLease.v1",
                "token": "stale-token",
                "pid": 999_999_999,
                "hostname": "test-host",
                "started_at": "2000-01-01T00:00:00.000Z",
                "scope": "host-operator",
            }
        ),
        encoding="utf-8",
    )
    script = f"""
const runner = require({json.dumps(str(BROWSER_RUNNER))});
const lockPath = {json.dumps(str(lock_path))};
const lease = runner.acquireQualificationLease(lockPath, {{scope: "fresh"}});
const stored = JSON.parse(require("fs").readFileSync(lockPath, "utf8"));
runner.releaseQualificationLease(lease);
process.stdout.write(JSON.stringify({{
  recovered: stored.token === lease.token,
  recovery: lease.recovered_stale_lease === true,
  released: !require("fs").existsSync(lockPath),
}}));
"""
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout) == {
        "recovered": True,
        "recovery": True,
        "released": True,
    }


def test_browser_runner_finalizes_recorders_before_evidence_seal() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    finalization = source.index('"browser-recorder-finalization"')
    seal = source.index("const index = writeEvidenceIndex(outputRoot);")
    assert finalization < seal
    assert "browser = null;" in source[finalization:seal]
    assert "mapZoomText" in source
    assert "zeroCountCategories" in source
    assert "unexplainedZeroCount" in source
    assert "warningCases" in source
    assert "snapshot.summary.warning" in source
    assert 'id: "weather-optional-rainfall-overlay-empty"' in source
    assert "grid_overlay_empty_reason" in source
    assert "message.location()" in source
    for evidence_ref in (
        "console-errors.json",
        "page-errors.json",
        "failed-requests.json",
        "network/responses.json",
        "coverage-map.json",
        "exploratory-findings.json",
        "junit.xml",
        "playwright-report/summary.json",
    ):
        assert evidence_ref in source


def test_browser_runner_does_not_start_fixture_without_explicit_opt_in(
    tmp_path: Path,
) -> None:
    env = dict(os.environ)
    env.pop("SCOUT_QUALIFICATION_RUNTIME_URL", None)
    env.pop("SCOUT_QUALIFICATION_PROJECT_ID", None)
    completed = subprocess.run(
        ["node", str(BROWSER_RUNNER), f"--output={tmp_path}"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 1
    assert "SCOUT_QUALIFICATION_RUNTIME_URL" in completed.stdout
    assert not (tmp_path / "fixture-seed.json").exists()
    assert not (tmp_path / "results.json").exists()


def test_manifest_hash_is_stable_for_evidence_binding() -> None:
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()

    assert len(digest) == 64
    assert digest == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()


def test_qualification_patch_binds_new_untracked_harness_files() -> None:
    source = QUALIFICATION_RUNNER.read_text(encoding="utf-8")

    assert '"ls-files"' in source
    assert '"--others"' in source
    assert '"--exclude-standard"' in source
    assert '"--no-index"' in source
    assert '"scripts/qualification"' in source
    assert '"tests/e2e"' in source
    assert '"regression-delta.json"' in source
    assert '"NO_TRUSTED_BASELINE"' in source
    assert "SCOUT_QUALIFICATION_RUNTIME_URL" in source
    assert "SCOUT_QUALIFICATION_PROJECT_ID" in source
    assert "AWAITING_GPT_PRO_COLLABORATION" in source
    assert "gpt-pro-collaboration-in-app-browser" in source
    assert "run_review(" not in source
    assert "SCOUT_QUALIFICATION_SKIP_REVIEW" not in source


def test_qualification_skill_requires_live_runtime_gpt_pro_and_human_gate() -> None:
    source = QUALIFICATION_SKILL.read_text(encoding="utf-8")

    assert "Mandatory live-runtime browser gate" in source
    assert "Finding, review, and human-confirmation lifecycle" in source
    assert "$gpt-pro-collaboration" in source
    assert "$browser:control-in-app-browser" in source
    assert "SCOUT-CANDIDATE-*" in source
    assert "APPROVE_FIX" in source
    assert "SPEC_CHANGE" in source
    assert "Synthetic, fixture, replay-only" in source
    assert "Qualification contract tests validate the qualification machinery only" in source
    assert "Every Dashboard map surface must receive real Fit" in source
    assert "Every exposed map layer must be switched off and on" in source
    assert "Visual acceptance is blocking" in source
    assert "GPT Pro must inspect every hash-bound" in source

    review_gate = REVIEW_GATE.read_text(encoding="utf-8")
    assert "gpt_pro_collaboration_review_missing" in review_gate
    assert "candidate_finding_review_coverage_mismatch" in review_gate
    assert "review_items_missing_for_actionable_findings" in review_gate
    assert "human_disposition_missing_before_remediation" in review_gate
    assert "independent_visual_review_screenshot_coverage_mismatch" in review_gate

    review_schema = json.loads(
        (
            ROOT
            / "qualification"
            / "schemas"
            / "qualification-review.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert "visual_review" in review_schema["required"]
    assert review_schema["properties"]["visual_review"]["properties"][
        "all_bound_screenshots_inspected"
    ]["const"] is True


def test_regression_delta_states_do_not_hide_prior_pass_failures() -> None:
    from scripts.qualification.run_qualification import _delta_state

    assert _delta_state("PASS", "FAIL") == "NEW_REGRESSION"
    assert _delta_state("PASS", "INSUFFICIENT_EVIDENCE") == "NEW_REGRESSION"
    assert _delta_state("PASS", "FLAKY") == "NEW_FLAKY"
    assert _delta_state("FAIL", "PASS") == "RESOLVED_SINCE_BASELINE"
    assert _delta_state(None, "PASS") == "NEW_CAPABILITY"


def test_official_qualification_requires_explicit_runtime_and_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    from scripts.qualification.run_qualification import _runtime_inputs

    monkeypatch.delenv("SCOUT_QUALIFICATION_RUNTIME_URL", raising=False)
    monkeypatch.delenv("SCOUT_QUALIFICATION_PROJECT_ID", raising=False)
    with pytest.raises(RuntimeError, match="explicit http"):
        _runtime_inputs(argparse.Namespace(runtime_url=None, project_id=None))

    runtime_url, project_id = _runtime_inputs(
        argparse.Namespace(
            runtime_url="http://127.0.0.1:9099",
            project_id="real_project",
        )
    )
    assert runtime_url == "http://127.0.0.1:9099"
    assert project_id == "real_project"


def test_post_review_files_do_not_change_bound_machine_evidence_root(
    tmp_path: Path,
) -> None:
    from scripts.qualification.verify_evidence import build_index, verify_index

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    (evidence_root / "results.json").write_text("{}", encoding="utf-8")
    original = build_index(evidence_root)
    (evidence_root / "evidence-index.json").write_text(
        json.dumps(original),
        encoding="utf-8",
    )

    (evidence_root / "reviewer-input.json").write_text("{}", encoding="utf-8")
    (evidence_root / "gpt-pro-review-status.json").write_text("{}", encoding="utf-8")
    (evidence_root / "gpt-pro-review-reference.json").write_text("{}", encoding="utf-8")
    (evidence_root / "reviewer-verdict.json").write_text("{}", encoding="utf-8")
    (evidence_root / "merge-gate.json").write_text("{}", encoding="utf-8")

    verified = verify_index(
        evidence_root,
        evidence_root / "evidence-index.json",
    )
    assert verified["valid"] is True
    assert verified["evidence_root_sha256"] == original["evidence_root_sha256"]


def test_ci_declares_separate_machine_and_independent_review_gates() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "name: Scout Deterministic Qualification" in workflow
    assert "name: Scout Independent Evidence Review" in workflow
    assert "continue-on-error: true" in workflow
    assert "scripts.qualification.verify_evidence" in workflow
    assert "scripts.qualification.enforce_review" in workflow
    assert "SCOUT_QUALIFICATION_RUNTIME_URL" in workflow
    assert "SCOUT_QUALIFICATION_PROJECT_ID" in workflow
    assert "gpt-pro-collaboration in the Codex in-app browser" in workflow
    assert "gpt-pro-review-reference.json" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert "SCOUT_QUALIFICATION_ALLOW_EXTERNAL_REVIEW" not in workflow
    assert "SCOUT_QUALIFICATION_SKIP_REVIEW" not in workflow
