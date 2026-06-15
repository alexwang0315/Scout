from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_navigation_terrain_collection import (
    INS_DR_READINESS_REF,
    OFFLINE_MAP_MANIFEST_REF,
    collect_pretrip_navigation_terrain,
)
from tools.verify_pretrip_workspace_spec_alignment import (
    _check_navigation_terrain_refs,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_collect_navigation_terrain_dry_run_reports_missing_readiness() -> None:
    result = collect_pretrip_navigation_terrain(
        PROJECT_ROOT,
        dry_run=True,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is False
    assert result["planned_refs"] == [OFFLINE_MAP_MANIFEST_REF, INS_DR_READINESS_REF]
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["answerability"] == "navigation_terrain_missing_user_readiness"
    assert result["navigation_demand_level"] == "high"
    assert "offline_map_downloaded" in result["missing_fields"]
    assert result["required_action_count"] >= 6
    assert result["boundary"]["runtime_safety_truth"] is False


def test_collect_navigation_terrain_writes_guided_only_artifacts(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)

    result = collect_pretrip_navigation_terrain(
        project_root,
        offline_map_downloaded=False,
        gpx_loaded_on_device=False,
        contour_skill_confirmed=False,
        terrain_feature_skill_confirmed=False,
        retreat_direction_understood=False,
        backup_positioning_available=False,
        team_map_user_count=1,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is True
    assert result["decision"] == "GUIDED_ONLY"
    offline = _load_json(project_root / OFFLINE_MAP_MANIFEST_REF)
    ins_dr = _load_json(project_root / INS_DR_READINESS_REF)
    project = _load_json(project_root / "project.json")

    assert offline["artifact_kind"] == "pretrip_offline_map_manifest"
    assert offline["decision"] == "GUIDED_ONLY"
    assert offline["navigation_demand"]["demand_level"] == "high"
    assert offline["map_readiness"]["offline_map_downloaded"] is False
    assert offline["map_readiness"]["gpx_loaded_on_device"] is False
    assert offline["map_readiness"]["risk_layers_available"] is True
    assert offline["map_readiness"]["terrain_layers_available"] is True
    assert offline["terrain_readiness"]["risk_ribbon_segment_count"] > 0
    assert offline["boundary"]["runtime_safety_truth"] is False
    assert offline["boundary"]["live_sensor_read_allowed"] is False
    assert ins_dr["artifact_kind"] == "pretrip_ins_dr_readiness"
    assert ins_dr["positioning_readiness"]["live_sensor_probe_performed"] is False
    assert ins_dr["positioning_readiness"]["hardware_control_performed"] is False
    assert ins_dr["map_skill_readiness"]["contour_skill_confirmed"] is False
    assert project["offline_map_manifest_ref"] == OFFLINE_MAP_MANIFEST_REF
    assert project["ins_dr_readiness_ref"] == INS_DR_READINESS_REF
    assert project["navigation_terrain_decision"] == "GUIDED_ONLY"

    errors: list[str] = []
    summary = _check_navigation_terrain_refs(project_root, project, errors)
    assert errors == []
    assert summary["available"] is True
    assert summary["decision"] == "GUIDED_ONLY"
    assert summary["risk_layers_available"] is True
    assert summary["terrain_layers_available"] is True
    assert summary["live_sensor_probe_performed"] is False

    manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    artifacts = {
        artifact["artifact_kind"]: artifact
        for artifact in manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert artifacts["offline_map_manifest"]["decision"] == "GUIDED_ONLY"
    assert artifacts["offline_map_manifest"]["risk_layers_available"] is True
    assert artifacts["ins_dr_readiness"]["backup_positioning_available"] is False
    assert artifacts["ins_dr_readiness"]["live_sensor_probe_performed"] is False


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
