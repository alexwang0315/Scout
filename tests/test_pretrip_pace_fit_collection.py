from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_pace_fit_collection import (
    PACE_COEFFICIENTS_REF,
    TEAM_PACE_FIT_REF,
    collect_pretrip_pace_fit,
)
from tools.verify_pretrip_workspace_spec_alignment import _check_pace_fit_refs


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


TEAM_MEMBERS = [
    {
        "member_id": "leader",
        "display_label": "Leader",
        "pace_mps": 1.15,
        "reserve_minutes": 55,
        "fatigue_band": "normal",
        "review_state": "reviewed",
    },
    {
        "member_id": "teammate",
        "display_label": "New teammate",
        "pace_mps": 0.58,
        "reserve_minutes": 8,
        "fatigue_band": "tired",
        "rest_need_minutes": 12,
        "first_time_similar_route": True,
        "conditions": ["sleep_debt", "knee_pain"],
    },
]


def test_collect_pretrip_pace_fit_dry_run_does_not_write(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)

    result = collect_pretrip_pace_fit(
        project_root,
        dry_run=True,
        team_members=TEAM_MEMBERS,
        minutes_to_next_cp=24,
        current_delay_minutes=22,
        leader_accepts_slowest_basis=False,
        team_rest_sync="mismatched",
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is False
    assert result["planned_refs"] == [PACE_COEFFICIENTS_REF, TEAM_PACE_FIT_REF]
    assert result["decision"] == "CHANGE_PLAN"
    assert result["member_count"] == 2
    assert result["vulnerable_member_count"] == 1
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["average_pace_used"] is False
    assert not (project_root / PACE_COEFFICIENTS_REF).exists()
    assert not (project_root / TEAM_PACE_FIT_REF).exists()


def test_collect_pretrip_pace_fit_writes_verifiable_artifacts(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)

    result = collect_pretrip_pace_fit(
        project_root,
        team_members=TEAM_MEMBERS,
        minutes_to_next_cp=24,
        current_delay_minutes=22,
        leader_accepts_slowest_basis=False,
        team_rest_sync="mismatched",
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is True
    assert result["written_refs"] == [PACE_COEFFICIENTS_REF, TEAM_PACE_FIT_REF]
    coefficients = _load_json(project_root / PACE_COEFFICIENTS_REF)
    team_fit = _load_json(project_root / TEAM_PACE_FIT_REF)
    project = _load_json(project_root / "project.json")

    assert coefficients["artifact_kind"] == "pretrip_pace_coefficients"
    assert team_fit["artifact_kind"] == "pretrip_team_pace_fit"
    assert coefficients["coefficient_schema_count"] == 9
    assert {
        item["indicator_id"] for item in coefficients["coefficient_schema"]
    } == {
        "flat_speed_mps",
        "ascent_speed_vertical_m_per_hour",
        "descent_speed_mps",
        "technical_terrain_slowdown_ratio",
        "rest_frequency_minutes",
        "late_trip_decay_ratio",
        "load_impact_ratio",
        "weather_impact_ratio",
        "experience_credibility",
    }
    assert coefficients["member_coefficients"][1]["label"] == "New teammate"
    assert coefficients["member_coefficients"][1]["raw_health_payload_embedded"] is False
    assert coefficients["boundary"]["medical_diagnosis"] is False
    assert team_fit["decision"] == "CHANGE_PLAN"
    assert team_fit["team_pace_fit"]["slowest_member"]["label"] == "New teammate"
    assert team_fit["team_pace_fit"]["pace_gap_ratio"] == 1.98
    assert team_fit["pace_guardian"]["average_pace_used"] is False
    assert team_fit["human_review_required"] is True
    assert project["pace_coefficients_ref"] == PACE_COEFFICIENTS_REF
    assert project["team_pace_fit_ref"] == TEAM_PACE_FIT_REF
    assert project["team_pace_fit_member_count"] == 2
    assert project["team_pace_fit_vulnerable_member_count"] == 1

    errors: list[str] = []
    summary = _check_pace_fit_refs(project_root, project, errors)
    assert errors == []
    assert summary["available"] is True
    assert summary["decision"] == "CHANGE_PLAN"
    assert summary["coefficient_schema_count"] == 9
    assert summary["average_pace_used"] is False

    manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    artifacts = {
        artifact["artifact_kind"]: artifact
        for artifact in manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert artifacts["pace_coefficients"]["member_coefficient_count"] == 2
    assert artifacts["pace_coefficients"]["average_pace_used"] is False
    assert artifacts["team_pace_fit"]["pace_gap_ratio"] == 1.98
    assert artifacts["team_pace_fit"]["human_review_required"] is True


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
