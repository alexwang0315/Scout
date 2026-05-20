import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_expert_contribution_apply_plan
from pretrip_expert_contribution_apply_plan import (
    ExpertContributionApplyPlan,
    apply_expert_contributions_to_workspace,
    build_expert_contribution_apply_plan_from_workspace,
    load_expert_contribution_apply_plan,
    load_expert_contribution_workspace_apply_result,
    write_expert_contribution_apply_plan,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
LOG_PATH = FIXTURE_ROOT / "outputs" / "expert_contribution_log.json"
APPLY_PLAN_REF = "outputs/expert_contribution_apply_plan.json"


def test_writes_expert_contribution_apply_plan_only_to_copied_workspace(tmp_path):
    workspace_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, workspace_root)
    protected_paths = [
        LOG_PATH,
        FIXTURE_ROOT / "outputs" / "pretrip_package.json",
        FIXTURE_ROOT / "outputs" / "compiled_mission_graph.candidate.json",
        FIXTURE_ROOT / "outputs" / "external_import_queue.json",
        FIXTURE_ROOT / "candidates" / "checkpoints.json",
        FIXTURE_ROOT / "candidates" / "retreat_routes.json",
    ]
    before = _file_fingerprints(protected_paths)

    plan = write_expert_contribution_apply_plan(workspace_root)
    output_path = workspace_root / APPLY_PLAN_REF

    assert output_path.exists()
    assert load_expert_contribution_apply_plan(output_path) == plan
    assert json.loads(output_path.read_text(encoding="utf-8")) == plan.model_dump(mode="json")
    assert _file_fingerprints(protected_paths) == before
    assert not (FIXTURE_ROOT / APPLY_PLAN_REF).exists()

    assert plan.plan_id == "expert_contribution_apply_plan.chilai_nanhua_day1.v0"
    assert plan.artifact_kind == "pretrip_expert_contribution_apply_plan"
    assert plan.project_id == "chilai_nanhua_day1"
    assert plan.expert_contribution_log_ref == "outputs/expert_contribution_log.json"
    assert plan.counts.model_dump(mode="json") == {
        "accepted_count": 0,
        "candidate_set_operation_count": 2,
        "contribution_count": 3,
        "external_import_operation_count": 1,
        "intended_count": 3,
        "mission_graph_mutation_count": 0,
        "package_mutation_count": 0,
        "phase2_brain_writeback_count": 0,
        "planned_operation_count": 3,
        "raw_payload_count": 0,
        "runtime_mutation_count": 0,
        "skipped_count": 0,
        "source_artifact_mutation_count": 0,
    }


def test_expert_contribution_apply_plan_records_metadata_only_operations(tmp_path):
    workspace_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, workspace_root)

    plan = build_expert_contribution_apply_plan_from_workspace(workspace_root)
    operations_by_contribution = {
        operation.contribution_id: operation for operation in plan.planned_operations
    }

    assert set(operations_by_contribution) == {
        "expert_contribution.chilai_nanhua_day1.add_checkpoint.trail_condition_reference.v0",
        "expert_contribution.chilai_nanhua_day1.update_retreat.return_to_entry.v0",
        "expert_contribution.chilai_nanhua_day1.add_import.recent_hiker_report.v0",
    }
    assert {operation.target_scope for operation in plan.planned_operations} == {
        "candidate_set",
        "external_import_queue",
    }
    assert all(operation.review_state == "needs_human_review" for operation in plan.planned_operations)
    assert all(operation.mutates_target_artifact is False for operation in plan.planned_operations)
    assert all(operation.embeds_raw_payload is False for operation in plan.planned_operations)

    candidate_operations = [
        operation
        for operation in plan.planned_operations
        if operation.target_scope == "candidate_set"
    ]
    import_operations = [
        operation
        for operation in plan.planned_operations
        if operation.target_scope == "external_import_queue"
    ]
    assert {operation.target_artifact_ref for operation in candidate_operations} == {
        "candidates/checkpoints.json",
        "candidates/retreat_routes.json",
    }
    assert [operation.target_artifact_ref for operation in import_operations] == [
        "outputs/external_import_queue.json"
    ]
    assert all(operation.would_apply_to_candidate_set for operation in candidate_operations)
    assert all(
        not operation.would_apply_to_external_import_queue
        for operation in candidate_operations
    )
    assert import_operations[0].would_apply_to_external_import_queue is True
    assert import_operations[0].would_apply_to_candidate_set is False


def test_expert_contribution_apply_plan_boundary_blocks_runtime_package_and_raw_payloads(tmp_path):
    workspace_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, workspace_root)

    plan = build_expert_contribution_apply_plan_from_workspace(workspace_root)

    assert plan.boundary.model_dump(mode="json") == {
        "candidate_artifact_mutation_allowed": False,
        "compiles_mission_graph": False,
        "external_api_calls_made": False,
        "external_import_queue_mutation_allowed": False,
        "mission_graph_mutation_allowed": False,
        "notes": [
            "Apply plan is a copied workspace metadata artifact only.",
            "Planned operations point at accepted or review-gated intended expert contributions without mutating source artifacts, candidate files, import queues, PreTripPackage, MissionGraph outputs, runtime state, or Phase 2 Brain state.",
            "Records with proposed or rejected review state are skipped and retained only as metadata pointers.",
        ],
        "package_mutation_allowed": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "raw_payloads_embedded": False,
        "repo_fixture_write_allowed": False,
        "runtime_mutation_allowed": False,
        "source_artifact_mutation_allowed": False,
        "workspace_only": True,
        "would_apply_only": True,
    }

    payload_without_allowed_flags = plan.model_dump(mode="json")
    payload_without_allowed_flags["boundary"].pop("raw_payloads_embedded")
    payload_without_allowed_flags["counts"].pop("raw_payload_count")
    for operation in payload_without_allowed_flags["planned_operations"]:
        operation.pop("embeds_raw_payload")
    serialized = json.dumps(
        payload_without_allowed_flags,
        ensure_ascii=False,
        sort_keys=True,
    )
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "ObservedFact",
        "<trkpt",
        '"coordinates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".tif",
        "source_payload",
        "raw_payload",
        "raw_html",
        "snapshot_body",
        "raw_dtm",
        "elevation_grid",
        "terrain_tile",
    ]:
        assert fragment not in serialized

    source = inspect.getsource(pretrip_expert_contribution_apply_plan)
    for forbidden_source in [
        "import admin_api",
        "from admin_api",
        "from pretrip_mission_compiler",
        "build_chilai_mission",
        "compile_pretrip",
        "MissionGraph(",
        "Phase2Brain(",
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "urllib.request",
        "urlopen",
    ]:
        assert forbidden_source not in source


def test_expert_contribution_apply_plan_rejects_repo_fixture_root():
    with pytest.raises(ValueError, match="copied workspace"):
        write_expert_contribution_apply_plan(FIXTURE_ROOT)

    assert not (FIXTURE_ROOT / APPLY_PLAN_REF).exists()


def test_expert_contribution_apply_plan_schema_rejects_mutation_claims(tmp_path):
    workspace_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, workspace_root)

    payload = build_expert_contribution_apply_plan_from_workspace(workspace_root).model_dump(
        mode="json"
    )
    payload["counts"]["runtime_mutation_count"] = 1
    with pytest.raises(ValidationError):
        ExpertContributionApplyPlan.model_validate(payload)

    payload = build_expert_contribution_apply_plan_from_workspace(workspace_root).model_dump(
        mode="json"
    )
    payload["boundary"]["compiles_mission_graph"] = True
    with pytest.raises(ValidationError):
        ExpertContributionApplyPlan.model_validate(payload)

    payload = build_expert_contribution_apply_plan_from_workspace(workspace_root).model_dump(
        mode="json"
    )
    payload["planned_operations"][0]["summary"] = "Attach raw GPX source_payload for apply"
    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        ExpertContributionApplyPlan.model_validate(payload)


def test_applies_expert_contributions_to_workspace_candidate_and_import_files_only(
    tmp_path,
):
    workspace_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, workspace_root)
    protected_paths = [
        LOG_PATH,
        FIXTURE_ROOT / "outputs" / "pretrip_package.json",
        FIXTURE_ROOT / "outputs" / "compiled_mission_graph.candidate.json",
        FIXTURE_ROOT / "outputs" / "external_import_queue.json",
        FIXTURE_ROOT / "candidates" / "checkpoints.json",
        FIXTURE_ROOT / "candidates" / "retreat_routes.json",
    ]
    before = _file_fingerprints(protected_paths)

    result = apply_expert_contributions_to_workspace(workspace_root)
    persisted = load_expert_contribution_workspace_apply_result(
        workspace_root / "outputs" / "expert_contribution_workspace_apply_result.json"
    )
    checkpoints = json.loads(
        (workspace_root / "candidates" / "checkpoints.json").read_text(
            encoding="utf-8"
        )
    )
    retreat_routes = json.loads(
        (workspace_root / "candidates" / "retreat_routes.json").read_text(
            encoding="utf-8"
        )
    )
    import_queue = json.loads(
        (workspace_root / "outputs" / "external_import_queue.json").read_text(
            encoding="utf-8"
        )
    )

    assert persisted == result
    assert result.counts.planned_operation_count == 3
    assert result.counts.applied_operation_count == 3
    assert result.counts.checkpoint_candidate_append_count == 1
    assert result.counts.retreat_route_update_count == 1
    assert result.counts.external_import_request_append_count == 1
    assert result.boundary.workspace_candidate_artifact_mutation_allowed is True
    assert result.boundary.workspace_external_import_queue_mutation_allowed is True
    assert result.boundary.repo_fixture_write_allowed is False
    assert result.boundary.package_mutation_allowed is False
    assert result.boundary.mission_graph_mutation_allowed is False
    assert result.boundary.runtime_mutation_allowed is False
    assert result.boundary.phase1_runtime_mutation_allowed is False
    assert result.boundary.phase2_brain_writeback_allowed is False

    assert checkpoints[-1]["candidate_id"] == (
        "admin_added_checkpoint.chilai_nanhua_day1.trail_condition_reference.v0"
    )
    assert checkpoints[-1]["review_state"] == "needs_human_review"
    assert checkpoints[-1]["lat"] is None
    assert checkpoints[-1]["lon"] is None
    assert checkpoints[-1]["source_refs"] == [
        "expert_contribution.chilai_nanhua_day1.add_checkpoint.trail_condition_reference.v0"
    ]
    assert retreat_routes[0]["candidate_id"] == "retreat.chilai_nanhua_day1.return_to_entry"
    assert retreat_routes[0]["review_state"] == "needs_human_review"
    assert "Expert update" in retreat_routes[0]["notes"]
    assert import_queue["counts"]["request_count"] == 4
    assert import_queue["counts"]["pending_count"] == 4
    assert import_queue["requests"][-1]["request_id"] == (
        "external_import.chilai_nanhua_day1.recent_hiker_report.placeholder"
    )
    assert import_queue["requests"][-1]["crawler_enabled"] is False
    assert import_queue["requests"][-1]["network_call_count"] == 0
    assert import_queue["requests"][-1]["observed_fact_candidate"] is False
    assert import_queue["requests"][-1]["raw_payload_embedded"] is False
    assert _file_fingerprints(protected_paths) == before


def _file_fingerprints(paths: list[Path]) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(FIXTURE_ROOT)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    }
