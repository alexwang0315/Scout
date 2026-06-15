from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_route_architecture_collection import (
    ROUTE_ARCHITECTURE_REF,
    collect_pretrip_route_architecture,
)
from tools.verify_pretrip_workspace_spec_alignment import _check_route_architecture_refs


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_route_architecture_collection_dry_run_plans_sec9_ref(tmp_path: Path) -> None:
    project_root = _copy_project(tmp_path)

    result = collect_pretrip_route_architecture(
        project_root,
        dry_run=True,
        limit=8,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["artifact_kind"] == "pretrip_route_architecture_collection"
    assert result["dry_run"] is True
    assert result["writes_performed"] is False
    assert result["outputs"]["route_architecture_ref"] == ROUTE_ARCHITECTURE_REF
    assert result["answerability"] == "route_architecture_available"
    assert result["hard_point_count"] >= 1
    assert result["retreat_option_count"] == 1
    assert result["boundary"]["runtime_safety_truth"] is False
    assert not (project_root / ROUTE_ARCHITECTURE_REF).exists()


def test_route_architecture_collection_writes_candidate_artifact_and_project_ref(
    tmp_path: Path,
) -> None:
    project_root = _copy_project(tmp_path)

    result = collect_pretrip_route_architecture(
        project_root,
        current_time="2013-10-08T15:05:00+08:00",
        limit=10,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is True
    assert result["decision"] == "CHANGE_PLAN"
    artifact = json.loads(
        (project_root / ROUTE_ARCHITECTURE_REF).read_text(encoding="utf-8")
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert artifact["artifact_kind"] == "pretrip_route_architecture"
    assert artifact["answerability"] == "route_architecture_available"
    assert artifact["decision"] == "CHANGE_PLAN"
    assert artifact["human_review_required"] is True
    assert artifact["counts"]["checkpoint_count"] == 124
    assert artifact["counts"]["segment_count"] == 123
    assert artifact["counts"]["hard_point_count"] >= 1
    assert artifact["counts"]["retreat_option_count"] == 1
    assert artifact["route_architecture"]["turn_back"][
        "turn_back_checkpoint_name"
    ] == "雲海保線所"
    assert artifact["route_structure_checks"]["retreat_points_checked"] is True
    assert artifact["route_structure_checks"]["alternative_plan_checked"] is True
    assert artifact["cp_graph"]["raw_route_geometry_embedded"] is False
    assert artifact["boundary"]["runtime_safety_truth"] is False
    assert artifact["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert project["route_architecture_ref"] == ROUTE_ARCHITECTURE_REF
    assert project["route_architecture_decision"] == "CHANGE_PLAN"
    assert project["route_architecture_hard_point_count"] == (
        artifact["counts"]["hard_point_count"]
    )

    errors: list[str] = []
    summary = _check_route_architecture_refs(project_root, project, errors)
    assert errors == []
    assert summary["available"] is True
    assert summary["decision"] == "CHANGE_PLAN"
    assert summary["checkpoint_count"] == 124
    assert summary["segment_count"] == 123
    assert summary["runtime_safety_truth"] is False

    artifact_manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    by_kind = {
        artifact["artifact_kind"]: artifact
        for artifact in artifact_manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert by_kind["route_architecture"]["decision"] == "CHANGE_PLAN"
    assert by_kind["route_architecture"]["hard_point_count"] >= 1
    assert by_kind["route_architecture"]["raw_route_geometry_embedded"] is False


def _copy_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_FIXTURE, project_root)
    return project_root
