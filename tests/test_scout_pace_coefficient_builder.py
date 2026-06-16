from __future__ import annotations

import shutil
from pathlib import Path

from scout_pace_coefficient_builder import build_scout_pace_coefficients_from_project


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
POST_ANALYSIS_OUTPUTS = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "outputs"
)


def test_build_scout_pace_coefficients_from_capability_timeline(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_ROOT, project_root)
    _copy_post_analysis_outputs(project_root)

    result = build_scout_pace_coefficients_from_project(
        project_root,
        member_id="alex",
        display_label="Alex",
        pack_weight_kg=12,
        weather_impact_ratio=0.18,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["artifact_kind"] == "scout_pace_coefficient_builder"
    assert result["status"] == "completed"
    assert result["counts"]["edge_count"] > 0
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["raw_health_payload_embedded"] is False
    assert result["boundary"]["medical_diagnosis"] is False
    assert result["boundary"]["average_pace_used"] is False

    member = result["team_members"][0]
    coefficient = member["scout_pace_coefficient"]
    assert member["member_id"] == "alex"
    assert member["pace_mps"] == coefficient["flat_speed_mps"]
    assert coefficient["flat_speed_mps"] > 0
    assert coefficient["uphill_speed_mps"] > 0
    assert coefficient["downhill_speed_mps"] > 0
    assert coefficient["technical_terrain_slowdown_ratio"] is not None
    assert coefficient["rest_frequency_minutes"] > 0
    assert coefficient["late_trip_speed_decay_ratio"] is not None
    assert coefficient["load_slowdown_ratio"] == 0.09
    assert coefficient["weather_slowdown_ratio"] == 0.18
    assert coefficient["experience_credibility"] == "unreviewed"

    provenance = result["indicator_provenance"]
    assert provenance["flat_speed_mps"]["source"] == "post_analysis_capability_timeline"
    assert provenance["load_impact_ratio"]["method"] == "pack_weight_heuristic"
    assert provenance["weather_impact_ratio"]["method"] == "provided_weather_impact_ratio"
    assert provenance["experience_credibility"]["confidence"] == "low"


def _copy_post_analysis_outputs(project_root: Path) -> None:
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    for filename in (
        "capability_timeline.json",
        "capability_route_time_comparison.json",
    ):
        shutil.copy2(POST_ANALYSIS_OUTPUTS / filename, outputs / filename)
