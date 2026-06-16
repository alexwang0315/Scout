from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_boss_point_synthesis import (
    BOSS_POINTS_GEOJSON_REF,
    BOSS_POINTS_REF,
    synthesize_pretrip_boss_points,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_synthesize_pretrip_boss_points_dry_run_keeps_workspace_clean(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)

    result = synthesize_pretrip_boss_points(
        project_root,
        dry_run=True,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["artifact_kind"] == "pretrip_boss_point_synthesis"
    assert result["status"] == "completed"
    assert result["boss_point_count"] == 5
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["workspace_file_mutation_allowed"] is False
    assert result["challenge_fit_summary"]["decision"] == "CHANGE_PLAN_OR_ADD_BUFFER"
    assert not (project_root / BOSS_POINTS_REF).exists()
    assert not (project_root / BOSS_POINTS_GEOJSON_REF).exists()


def test_synthesize_pretrip_boss_points_writes_challenge_fit_artifacts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)

    result = synthesize_pretrip_boss_points(
        project_root,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["boundary"]["workspace_file_mutation_allowed"] is True
    assert result["boss_points"][0]["label"] == "大崩壁"
    assert result["boss_points"][0]["display_theme"]["alias"] == "呂布關"
    assert result["boss_points"][0]["display_theme"]["decorative_only"] is True
    assert result["boss_points"][0]["route_boss_demand"]["score"] > 60
    assert result["boss_points"][0]["challenge_fit"]["score"] == 100
    assert result["boss_points"][0]["challenge_fit"]["user_basis"] == (
        "slowest_member_or_private_energy_reserve"
    )
    assert result["boss_points"][0]["challenge_fit"]["slowest_member_id"] == (
        "person.teammate_placeholder"
    )
    assert result["boss_points"][0]["challenge_fit"]["energy_factors"][
        "reserve_band"
    ] == "rest_suggested"
    assert result["boss_points"][0]["candidate_only"] is True
    assert result["boss_points"][0]["runtime_safety_truth"] is False

    payload = _load_json(project_root / BOSS_POINTS_REF)
    geojson = _load_json(project_root / BOSS_POINTS_GEOJSON_REF)
    project = _load_json(project_root / "project.json")
    assert payload["boss_point_count"] == 5
    assert [point["display_theme"]["alias"] for point in payload["boss_points"]] == [
        "呂布關",
        "關羽門",
        "張飛坡",
        "趙雲稜",
        "馬超壁",
    ]
    assert geojson["metadata"]["candidate_only"] is True
    assert len(geojson["features"]) == 5
    assert project["boss_points_ref"] == BOSS_POINTS_REF
    assert project["boss_points_geojson_ref"] == BOSS_POINTS_GEOJSON_REF
    assert project["boss_point_count"] == 5

    manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    artifacts = {
        artifact["artifact_kind"]: artifact
        for artifact in manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert artifacts["boss_points"]["boss_point_count"] == 5
    assert artifacts["boss_points"]["decision"] == "CHANGE_PLAN_OR_ADD_BUFFER"
    assert artifacts["boss_points"]["runtime_safety_truth"] is False
    assert artifacts["boss_points_geojson"]["feature_count"] == 5


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
