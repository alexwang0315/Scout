from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_boss_point_synthesis import (
    BOSS_POINTS_GEOJSON_REF,
    BOSS_POINTS_REF,
    ROUTE_PRESSURE_PROFILE_GEOJSON_REF,
    ROUTE_PRESSURE_PROFILE_REF,
    _route_boss_demand,
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
    assert result["policy"]["slow_passage_min_span_m"] == 500.0
    assert result["policy"]["pressure_profile_bin_m"] == 500.0
    assert result["policy"]["centerline"] == "overpass_risk_ribbon"
    assert result["policy"]["gpx_evidence_axis"] == (
        "projected_to_overpass_risk_ribbon"
    )
    assert result["policy"]["boss_coordinate_source"] == (
        "overpass_risk_ribbon_route_distance_interpolation"
    )
    assert result["route_pressure_profile_summary"]["sample_count"] > 0
    assert result["route_pressure_profile_summary"]["peak_count"] > 0
    assert result["challenge_fit_summary"]["decision"] == "CHANGE_PLAN_OR_ADD_BUFFER"
    assert not (project_root / BOSS_POINTS_REF).exists()
    assert not (project_root / BOSS_POINTS_GEOJSON_REF).exists()
    assert not (project_root / ROUTE_PRESSURE_PROFILE_REF).exists()
    assert not (project_root / ROUTE_PRESSURE_PROFILE_GEOJSON_REF).exists()


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
    assert result["boss_points"][0]["source_candidate_id"].startswith(
        "route_pressure_peak."
    )
    assert result["boss_points"][0]["label"].startswith("高壓路段")
    assert result["boss_points"][0]["display_theme"]["alias"] == "呂布關"
    assert result["boss_points"][0]["display_theme"]["decorative_only"] is True
    assert result["boss_points"][0]["route_boss_demand"]["score"] > 80
    assert result["route_pressure_profile_summary"]["sample_count"] > 0
    assert result["route_pressure_profile_summary"]["peak_count"] > 0
    assert result["boss_points"][0]["route_boss_demand"]["components"][
        "route_pressure_profile"
    ] > 0
    assert result["boss_points"][0]["evidence_summary"]["route_pressure_profile"][
        "pressure_peak_id"
    ].startswith("route_pressure_peak.")
    assert result["boss_points"][0]["route_boss_demand"]["route_pressure_profile"][
        "coordinate_source"
    ] == "overpass_risk_ribbon_route_distance_interpolation"
    assert result["boss_points"][0]["coordinate_source"] == (
        "overpass_risk_ribbon_route_distance_interpolation"
    )
    assert result["boss_points"][0]["route_boss_demand"]["slow_passage"][
        "min_span_m"
    ] == 500.0
    assert result["boss_points"][0]["evidence_summary"]["slow_passage"][
        "min_span_m"
    ] == 500.0
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
    pressure_profile = _load_json(project_root / ROUTE_PRESSURE_PROFILE_REF)
    pressure_geojson = _load_json(project_root / ROUTE_PRESSURE_PROFILE_GEOJSON_REF)
    project = _load_json(project_root / "project.json")
    assert payload["boss_point_count"] == 5
    assert payload["policy"]["centerline"] == "overpass_risk_ribbon"
    assert payload["policy"]["gpx_evidence_axis"] == (
        "projected_to_overpass_risk_ribbon"
    )
    assert payload["policy"]["boss_coordinate_source"] == (
        "overpass_risk_ribbon_route_distance_interpolation"
    )
    assert [point["display_theme"]["alias"] for point in payload["boss_points"]] == [
        "呂布關",
        "關羽門",
        "張飛坡",
        "趙雲稜",
        "馬超壁",
    ]
    machao = next(
        point
        for point in payload["boss_points"]
        if point["display_theme"]["alias"] == "馬超壁"
    )
    assert machao["label"] == "高壓路段 69.8K（高壓）"
    assert machao["lat"] == 23.89207000180547
    assert machao["lon"] == 121.22026385047626
    assert machao["coordinate_source"] == (
        "overpass_risk_ribbon_route_distance_interpolation"
    )
    assert geojson["metadata"]["candidate_only"] is True
    assert len(geojson["features"]) == 5
    machao_feature = next(
        feature
        for feature in geojson["features"]
        if feature["properties"]["display_alias"] == "馬超壁"
    )
    assert machao_feature["properties"]["coordinate_source"] == (
        "overpass_risk_ribbon_route_distance_interpolation"
    )
    assert pressure_profile["artifact_kind"] == "pretrip_route_pressure_profile"
    assert pressure_profile["counts"]["sample_count"] > 0
    assert pressure_profile["counts"]["peak_count"] > 0
    assert {
        sample["coordinate_source"] for sample in pressure_profile["samples"][:5]
    } == {"overpass_risk_ribbon_route_distance_interpolation"}
    assert pressure_profile["policy"]["centerline"] == "overpass_risk_ribbon"
    assert pressure_profile["policy"]["gpx_evidence_axis"] == (
        "projected_to_overpass_risk_ribbon"
    )
    assert pressure_geojson["metadata"]["candidate_only"] is True
    assert len(pressure_geojson["features"]) > 0
    assert project["boss_points_ref"] == BOSS_POINTS_REF
    assert project["boss_points_geojson_ref"] == BOSS_POINTS_GEOJSON_REF
    assert project["route_pressure_profile_ref"] == ROUTE_PRESSURE_PROFILE_REF
    assert (
        project["route_pressure_profile_geojson_ref"]
        == ROUTE_PRESSURE_PROFILE_GEOJSON_REF
    )
    assert project["boss_point_count"] == 5

    manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    artifacts = {
        artifact["artifact_kind"]: artifact
        for artifact in manifest["artifacts"]
        if artifact["source"] == "project"
    }
    assert artifacts["boss_points"]["boss_point_count"] == 5
    assert artifacts["boss_points"]["route_pressure_sample_count"] > 0
    assert artifacts["boss_points"]["route_pressure_peak_count"] > 0
    assert artifacts["boss_points"]["decision"] == "CHANGE_PLAN_OR_ADD_BUFFER"
    assert artifacts["boss_points"]["runtime_safety_truth"] is False
    assert artifacts["boss_points_geojson"]["feature_count"] == 5
    assert artifacts["route_pressure_profile"]["sample_count"] > 0
    assert artifacts["route_pressure_profile"]["peak_count"] > 0
    assert artifacts["route_pressure_profile_geojson"]["feature_count"] > 0


def test_slow_passage_requires_500m_span_and_does_not_promote_rest_stop() -> None:
    rest_stop = _route_boss_demand(
        candidate={
            "label": "雲海保線所",
            "distance_m": 1000.0,
            "mcp_classes": ["camp_hut_structure"],
            "mention_ratio": 0.167,
            "mcp_score_components": {"total": 45.0},
            "named_point_evidence": [],
        },
        nearby_notes=[
            {
                "candidate_id": "note.rest.001",
                "route_distance_m": 950.0,
                "normalized_note": "大家在保線所慢下來休息午餐",
            },
            {
                "candidate_id": "note.rest.002",
                "route_distance_m": 1100.0,
                "normalized_note": "保線所休息慢慢等隊友",
            },
        ],
        nearby_rest=[{"candidate_id": "rest.yunhai", "route_distance_m": 1000.0}],
        nearby_resume=[],
        risk_summary={"feature_count": 1, "max_risk_score": 20.0},
        incident_context={},
        weather_daylight={},
        route_extent_m=5000.0,
        local_extent_m=5000.0,
        slow_passage_min_span_m=500.0,
    )

    assert rest_stop["slow_passage"]["qualified"] is False
    assert rest_stop["slow_passage"]["span_m"] == 0.0
    assert rest_stop["slow_passage"]["suppressed_rest_stop_slow_note_count"] == 2
    assert rest_stop["components"]["observed_impedance"] == 0
    assert rest_stop["components"]["rest_cluster"] == 0.0
    assert rest_stop["rest_stop_context"]["rest_stop_likely"] is True
    assert rest_stop["rest_stop_context"]["rest_stop_deemphasis_multiplier"] == 0.72

    passage = _route_boss_demand(
        candidate={
            "label": "長距離耗力通過段",
            "distance_m": 1000.0,
            "mcp_classes": [],
            "mention_ratio": 0.0,
            "mcp_score_components": {"total": 0.0},
            "named_point_evidence": [],
        },
        nearby_notes=[
            {
                "candidate_id": "note.slow.001",
                "route_distance_m": 700.0,
                "normalized_note": "慢速通過濕滑路面",
            },
            {
                "candidate_id": "note.slow.002",
                "route_distance_m": 1300.0,
                "normalized_note": "隊伍持續很慢才通過",
            },
        ],
        nearby_rest=[],
        nearby_resume=[],
        risk_summary={"feature_count": 1, "max_risk_score": 20.0},
        incident_context={},
        weather_daylight={},
        route_extent_m=5000.0,
        local_extent_m=5000.0,
        slow_passage_min_span_m=500.0,
    )

    assert passage["slow_passage"]["qualified"] is True
    assert passage["slow_passage"]["span_m"] == 600.0
    assert passage["slow_passage"]["effective_note_count"] == 2
    assert passage["components"]["observed_impedance"] == 10
    assert passage["rest_stop_context"]["rest_stop_likely"] is False


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
