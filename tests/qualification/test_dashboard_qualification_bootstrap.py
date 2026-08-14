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
    for capability_id in (
        "dashboard.diagnostic.read_only",
        "dashboard.shell.runtime_route_navigation",
        "dashboard.browser.complete_control_coverage",
        "dashboard.visual.complete_live_rendering",
        "dashboard.maps.all_surface_interactions",
        "dashboard.layers.all_visible_toggle_integrity",
        "dashboard.navigation.partial_data_shell",
        "dashboard.weather.optional_rainfall_overlay",
        "dashboard.maps.dynamic_rudy_tiles",
        "dashboard.permission.fail_closed",
        "qualification.evidence.integrity",
    ):
        assert capability_id in capabilities
    for capability in capabilities.values():
        assert capability["expected_behavior"]
        assert capability["forbidden_behavior"]
        assert capability["required_tests"]
        assert capability["required_evidence"]
        assert capability["authority_boundary"]["runtime_authority"] is False
    diagnostic_controls = capabilities["dashboard.diagnostic.controls"]
    assert any(
        "typed expected zero" in requirement
        for requirement in diagnostic_controls["expected_behavior"]
    )
    assert "typed_zero_warning" in diagnostic_controls["required_tests"]
    assert capabilities["qualification.fixture.active_p0_matrix"]["status"] == "sandbox"


def test_browser_action_contract_covers_every_dashboard_route_and_map() -> None:
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

    map_surface_ids = {surface["id"] for surface in contract["map_surfaces"]}
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
    assert set(contract["required_map_gestures"]) == {
        "fit",
        "zoom_in",
        "zoom_out",
        "mouse_pan",
        "keyboard_pan",
        "rectangle_zoom",
    }
    assert contract["official_mode"]["contract_tests_are_dashboard_evidence"] is False
    assert contract["official_mode"]["zero_unmapped_controls_required"] is True
    assert contract["control_coverage"]["include_embedded_frames"] is True
    assert contract["control_coverage"]["disabled_controls_require_executable_state"] is True
    assert contract["control_coverage"][
        "delegated_controls_require_passing_specialist_case"
    ] is True
    assert contract["required_map_content"][
        "all_exposed_layer_controls_must_be_toggled"
    ] is True
    assert contract["visual_quality"]["max_occluded_controls"] == 0
    assert contract["visual_quality"]["max_blurred_elements"] == 0
    assert contract["visual_quality"]["max_low_resolution_rasters"] == 0
    assert contract["visual_quality"][
        "screenshot_before_after_each_operation"
    ] is True


def test_live_browser_runner_has_exhaustive_operation_and_visual_gates() -> None:
    source = BROWSER_RUNNER.read_text(encoding="utf-8")

    for required_symbol in (
        "loadBrowserActionContract",
        "auditAllRouteVisualStates",
        "auditAllVisibleControls",
        "discoverVisibleControlsInFrame",
        "inspectAllDashboardMapSurfaces",
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
    assert "async function runCaseFinalizerWithTimeout(" in source
    assert 'error.code = "CASE_FINALIZATION_TIMEOUT"' in source
    assert '"trace-stop"' in source
    assert '"context-close"' in source
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
    assert source.count("observations.controlInventory = inventory;") >= 2
    assert 'locator(":scope > summary")' in source
    assert "fit-before" in source
    assert "evidence-hint-before" in source
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

    results["dashboard.diagnostic.read_only"] = "FAIL"
    regression = evaluate_results(manifest, results, policy)
    assert regression["merge_permitted"] is False
    assert regression["machine_verdict"] == "FAIL"
    assert regression["blockers"][0]["capability_id"] == (
        "dashboard.diagnostic.read_only"
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
    assert "for (const definition of caseDefinitions)" in source
    assert "results.push(await runIsolatedCase(" in source
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
