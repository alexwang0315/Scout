from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_contextual_permission_collection import (
    CONTEXTUAL_PERMISSION_MODEL_REF,
    CONTEXTUAL_PERMISSION_RULES_REF,
    collect_pretrip_contextual_permission,
)
from tools.verify_pretrip_workspace_spec_alignment import (
    _check_contextual_permission_refs,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_contextual_permission_collection_dry_run_plans_sec8_refs(
    tmp_path: Path,
) -> None:
    project_root = _copy_project(tmp_path)

    result = collect_pretrip_contextual_permission(
        project_root,
        dry_run=True,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["artifact_kind"] == "pretrip_contextual_permission_collection"
    assert result["dry_run"] is True
    assert result["writes_performed"] is False
    assert result["outputs"]["contextual_permission_model_ref"] == (
        CONTEXTUAL_PERMISSION_MODEL_REF
    )
    assert result["outputs"]["contextual_permission_rules_ref"] == (
        CONTEXTUAL_PERMISSION_RULES_REF
    )
    assert result["rule_count"] >= 5
    assert result["boundary"]["runtime_safety_truth"] is False
    assert not (project_root / CONTEXTUAL_PERMISSION_MODEL_REF).exists()
    assert not (project_root / CONTEXTUAL_PERMISSION_RULES_REF).exists()


def test_contextual_permission_collection_writes_candidate_rules_and_project_refs(
    tmp_path: Path,
) -> None:
    project_root = _copy_project(tmp_path)

    result = collect_pretrip_contextual_permission(
        project_root,
        current_time="2026-06-07T13:36:00+08:00",
        current_cp_id="CP3",
        next_cp_id="CP4",
        remaining_safety_buffer_minutes=90,
        current_delay_minutes=9,
        next_segment_uncertainty_minutes=3,
        weather_reserve_minutes=2,
        communication_status="ok",
        equipment_status="ok",
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is True
    model = json.loads(
        (project_root / CONTEXTUAL_PERMISSION_MODEL_REF).read_text(encoding="utf-8")
    )
    rules = json.loads(
        (project_root / CONTEXTUAL_PERMISSION_RULES_REF).read_text(encoding="utf-8")
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert model["artifact_kind"] == "pretrip_contextual_permission_model"
    assert model["decision_object_schema"] == "ContextualPermission"
    assert "film" in model["supported_actions"]
    assert model["boundary"]["runtime_safety_truth"] is False
    assert rules["artifact_kind"] == "pretrip_contextual_permission_rules"
    assert rules["human_review_required"] is True
    assert rules["counts"]["rule_count"] >= 5
    assert rules["counts"]["bounded_permission_count"] >= 4
    assert rules["counts"]["escalate_count"] == 1
    assert rules["boundary"]["runtime_safety_truth"] is False
    assert project["contextual_permission_model_ref"] == CONTEXTUAL_PERMISSION_MODEL_REF
    assert project["contextual_permission_rules_ref"] == CONTEXTUAL_PERMISSION_RULES_REF
    assert project["contextual_permission_rule_count"] == rules["counts"]["rule_count"]

    by_action = {rule["action"]: rule for rule in rules["rules"]}
    assert {"film", "lunch", "summit", "wait", "cross_stream"} <= set(by_action)
    assert by_action["film"]["decision"] == "CONDITIONAL_GO"
    assert by_action["film"]["allowed"] is True
    assert by_action["film"]["maxDurationMinutes"] == 6
    assert by_action["film"]["leaveBy"] == "2026-06-07T13:42:00+08:00"
    assert "最多 6 分鐘" in by_action["film"]["field_answer"]
    assert by_action["cross_stream"]["decision"] == "ESCALATE"
    assert by_action["cross_stream"]["runtime_safety_truth"] is False
    assert all(rule["candidate_only"] is True for rule in rules["rules"])
    assert all(rule["phase1_runtime_mutation_allowed"] is False for rule in rules["rules"])

    errors: list[str] = []
    summary = _check_contextual_permission_refs(project_root, project, errors)
    assert errors == []
    assert summary["available"] is True
    assert summary["rule_count"] == rules["counts"]["rule_count"]
    assert summary["bounded_permission_count"] >= 4
    assert summary["runtime_safety_truth"] is False

    artifact_manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    by_kind = {
        artifact["artifact_kind"]: artifact
        for artifact in artifact_manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert by_kind["contextual_permission_model"]["supported_action_count"] >= 10
    assert by_kind["contextual_permission_rules"]["bounded_permission_count"] >= 4
    assert by_kind["contextual_permission_rules"]["runtime_safety_truth"] is False


def _copy_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_FIXTURE, project_root)
    return project_root
