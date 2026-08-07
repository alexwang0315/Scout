from __future__ import annotations

import hashlib
import json
import shutil
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
QUALIFICATION_RUNNER = ROOT / "scripts" / "qualification" / "run_qualification.py"
WORKFLOW = ROOT / ".github" / "workflows" / "dashboard-qualification.yml"


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
        "dashboard.navigation.partial_data_shell",
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


def test_qualification_policy_blocks_intentional_p0_regression() -> None:
    from scripts.qualification.evaluate_qualification import evaluate_results

    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    results = {
        capability["id"]: "PASS"
        for surface in manifest["surfaces"]
        for capability in surface["capabilities"]
    }

    clean = evaluate_results(manifest, results, policy)
    assert clean["merge_permitted"] is True

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
            }
        ),
        encoding="utf-8",
    )
    (evidence_root / "machine-verdict.json").write_text(
        json.dumps({"machine_verdict": "PASS", "merge_permitted": True}),
        encoding="utf-8",
    )
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
    assert all(
        binding["content_included"] is False
        for binding in payload["change_evidence"]["source_bindings"]
    )


def test_independent_review_requires_explicit_external_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from scripts.qualification.run_independent_review import run_review

    monkeypatch.setenv("OPENAI_API_KEY", "qualification-test-placeholder")
    monkeypatch.delenv("SCOUT_QUALIFICATION_ALLOW_EXTERNAL_REVIEW", raising=False)

    with pytest.raises(RuntimeError, match="explicitly enabled"):
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
    assert "failedCases: Object.entries(snapshot.results)" in source
    assert "scripts.qualification.dashboard_fixture_server:create_app" in source
    assert "disabledBaseUrl" in source
    assert "function writeAggregateEvidence(" in source
    assert "mapZoomText" in source
    assert "zeroCountCategories" in source
    assert "unexplainedZeroCount" in source
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


def test_regression_delta_states_do_not_hide_prior_pass_failures() -> None:
    from scripts.qualification.run_qualification import _delta_state

    assert _delta_state("PASS", "FAIL") == "NEW_REGRESSION"
    assert _delta_state("PASS", "INSUFFICIENT_EVIDENCE") == "NEW_REGRESSION"
    assert _delta_state("PASS", "FLAKY") == "NEW_FLAKY"
    assert _delta_state("FAIL", "PASS") == "RESOLVED_SINCE_BASELINE"
    assert _delta_state(None, "PASS") == "NEW_CAPABILITY"


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
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert 'SCOUT_QUALIFICATION_ALLOW_EXTERNAL_REVIEW: "1"' in workflow
