from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pretrip_reference_pace_energy_analysis import (
    build_reference_pace_energy_analysis,
    write_reference_pace_energy_analysis,
)


def test_reference_pace_energy_analysis_rejects_fixed_interval_assumption_and_builds_map(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)

    report, pace_map = build_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-17T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )

    assert report["artifact_kind"] == "pretrip_reference_pace_energy_analysis"
    assert report["schema_version"] == "reference_pace_energy_analysis.v0"
    assert report["source_provider"] == "historical_gpx_reference_corpus"
    assert report["source_path"] == "sources/historical_gpx_source_index.json"
    assert len(report["sha256"]) == 64
    assert report["hypothesis_assessment"]["fixed_interval_assumption"] == "rejected"
    assert report["hypothesis_assessment"]["absolute_power_identifiable"] is False
    assert report["hypothesis_assessment"]["self_selected_comfort_identifiable"] is False
    assert report["sampling_interval_seconds"]["p50"] != 60.0
    assert report["counts"]["reference_track_count"] == 4
    assert report["counts"]["timed_reference_track_count"] == 3
    assert report["counts"]["missing_time_reference_track_count"] == 1
    assert report["counts"]["route_traversal_count"] > 0

    absolute_grade = report["relationships"]["by_absolute_grade_strata"]
    assert [item["band"] for item in absolute_grade] == [
        "00_to_10_percent",
        "10_to_30_percent",
        "30_to_60_percent",
        "60_percent_plus",
    ]
    assert sum(item["traversal_count"] for item in absolute_grade) == report["counts"][
        "route_traversal_count"
    ]
    assert all(
        [direction["direction"] for direction in item["by_direction"]]
        == ["ascent", "descent", "near_level"]
        for item in absolute_grade
    )
    terrain_relief = report["relationships"]["by_terrain_relief_strata"]
    assert [item["band"] for item in terrain_relief] == [
        "00_to_10_percent",
        "10_to_30_percent",
        "30_to_60_percent",
        "60_percent_plus",
    ]
    assert sum(item["traversal_count"] for item in terrain_relief) == report["counts"][
        "route_traversal_count"
    ]

    normal_walking = report["relationships"]["normal_walking_speed_subset"]
    assert normal_walking["filter"] == {
        "speed_field": "traversal_route_progress_speed",
        "minimum_speed_kmh_exclusive": 1.0,
        "maximum_speed_kmh_exclusive": 10.0,
        "strict_bounds": True,
        "stationary_and_long_gap_intervals_already_excluded": True,
    }
    assert 0 < normal_walking["sample_count"] <= report["counts"][
        "route_traversal_count"
    ]
    assert normal_walking["sample_count"] + normal_walking[
        "excluded_traversal_count"
    ] == report["counts"]["route_traversal_count"]
    assert normal_walking["speed_kmh"]["min"] > 1.0
    assert normal_walking["speed_kmh"]["max"] < 10.0
    assert normal_walking["spearman_correlations"][
        "speed_vs_risk_score"
    ]["sample_count"] <= normal_walking["sample_count"]
    assert normal_walking["spearman_correlations"][
        "speed_vs_continuous_moving_minutes"
    ]["sample_count"] == normal_walking["sample_count"]
    assert normal_walking["by_risk_score"]
    assert normal_walking["by_continuous_moving_time"]
    controlled = normal_walking[
        "risk_and_duration_correlations_by_absolute_grade_strata"
    ]
    assert [item["band"] for item in controlled] == [
        "00_to_10_percent",
        "10_to_30_percent",
        "30_to_60_percent",
        "60_percent_plus",
    ]
    assert sum(item["sample_count"] for item in controlled) == normal_walking[
        "sample_count"
    ]
    assert all(
        [direction["direction"] for direction in item["by_direction"]]
        == ["ascent", "descent", "near_level"]
        for item in controlled
    )
    raw_interval = normal_walking["raw_interval_diagnostic"]
    assert raw_interval["unit_of_analysis"] == "matched_adjacent_trackpoint_interval"
    assert raw_interval["primary_comparison"] is False
    assert raw_interval["sampling_frequency_weighted"] is True
    assert raw_interval["sample_count"] > 0
    assert raw_interval["speed_kmh"]["min"] > 1.0
    assert raw_interval["speed_kmh"]["max"] < 10.0
    assert raw_interval["spearman_correlations"]["speed_vs_risk_score"]
    assert raw_interval["spearman_correlations"][
        "speed_vs_continuous_moving_minutes"
    ]

    tracks = {item["source_id"]: item for item in report["tracks"]}
    assert tracks["gpx.source.demo.reference.004"]["status"] == "missing_trackpoint_time"
    assert tracks["gpx.source.demo.reference.003"]["pause_reset_count"] == 1
    assert all("precise_timestamps" not in item for item in report["tracks"])

    assert pace_map["type"] == "FeatureCollection"
    assert pace_map["features"]
    guidance_features = [
        feature
        for feature in pace_map["features"]
        if feature["properties"]["data_quality"] in {"medium", "high"}
    ]
    assert guidance_features
    assert any(feature["properties"]["distinct_track_count"] >= 3 for feature in guidance_features)
    assert any(
        feature["properties"]["positive_gravity_power_w_per_kg_p50"] > 0
        for feature in guidance_features
    )
    assert all(
        feature["properties"]["runtime_safety_truth"] is False
        for feature in pace_map["features"]
    )

    assert report["privacy"] == {
        "aggregate_only": True,
        "coordinates_embedded_in_geojson_only": True,
        "precise_timestamps_embedded": False,
        "raw_gpx_embedded": False,
        "source_original_paths_embedded": False,
    }
    assert report["boundary"]["candidate_only"] is True
    assert report["boundary"]["medical_diagnosis"] is False
    assert report["boundary"]["phase1_runtime_safety_truth"] is False
    assert report["boundary"]["safety_api_called"] is False

    serialized = json.dumps(report, ensure_ascii=False)
    assert "<trkpt" not in serialized
    assert "2026-01-01T" not in serialized


def test_reference_pace_energy_writer_emits_dashboard_ready_artifacts(tmp_path: Path) -> None:
    project_root = _write_workspace(tmp_path)

    result = write_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-17T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )

    report_path = project_root / "outputs/reference_pace_energy_analysis.json"
    map_path = project_root / "outputs/reference_pace_energy_map.geojson"
    assert result["status"] == "completed"
    assert result["report_path"] == report_path
    assert result["geojson_path"] == map_path
    assert report_path.is_file()
    assert map_path.is_file()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    pace_map = json.loads(map_path.read_text(encoding="utf-8"))
    assert report["output_refs"]["pace_map_geojson_ref"] == (
        "outputs/reference_pace_energy_map.geojson"
    )
    assert pace_map["metadata"]["source_path"] == (
        "outputs/reference_pace_energy_analysis.json"
    )
    assert pace_map["metadata"]["privacy"]["precise_timestamps_embedded"] is False


def _write_workspace(tmp_path: Path) -> Path:
    project_root = tmp_path / "demo"
    filtered_root = project_root / "normalized/routes/filtered"
    risk_root = project_root / "outputs/risk"
    source_root = project_root / "sources"
    filtered_root.mkdir(parents=True)
    risk_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    project = {
        "project_id": "demo",
        "historical_gpx_source_index_ref": "sources/historical_gpx_source_index.json",
        "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
        "route_pressure_profile_ref": "outputs/route_pressure_profile.json",
    }
    _write_json(project_root / "project.json", project)

    route_points = [
        (23.95, 121.0 + index * 0.00049)
        for index in range(13)
    ]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sources = []
    interval_sets = [
        [45, 50, 55, 45, 50, 55, 45, 50, 55, 45, 50, 55],
        [50] * 12,
        [50, 50, 50, 180, 180, 50, 50, 50, 50, 50, 50, 50, 50, 50],
    ]

    for source_number, intervals in enumerate(interval_sets, start=1):
        source_id = f"gpx.source.demo.reference.{source_number:03d}"
        source_name = f"reference_{source_number:03d}.demo.speed_filtered.gpx"
        source_path = filtered_root / source_name
        if source_number == 3:
            points = route_points[:4] + [route_points[3], route_points[3]] + route_points[4:]
        else:
            points = route_points
        timestamps = [base_time]
        for seconds in intervals[: len(points) - 1]:
            timestamps.append(timestamps[-1] + timedelta(seconds=seconds))
        _write_gpx(source_path, points, timestamps)
        sources.append(_source_record(source_id, source_number, source_path))

    missing_time_path = filtered_root / "reference_004.demo.speed_filtered.gpx"
    _write_gpx(missing_time_path, route_points, None)
    sources.append(
        _source_record(
            "gpx.source.demo.reference.004",
            4,
            missing_time_path,
        )
    )
    _write_json(
        source_root / "historical_gpx_source_index.json",
        {
            "artifact_kind": "pretrip_historical_gpx_source_index",
            "project_id": "demo",
            "source_file_count": 4,
            "sources": sources,
        },
    )

    risk_features = []
    for index, (lat, lon) in enumerate(route_points):
        risk_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "distance_m": index * 50.0,
                    "rs": 35.0 + index * 3.0,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    _write_json(
        risk_root / "risk_score_points.geojson",
        {"type": "FeatureCollection", "features": risk_features},
    )

    pressure_samples = []
    for index in range(3):
        start_m = index * 250.0
        end_m = min(600.0, start_m + 250.0)
        pressure_samples.append(
            {
                "sample_id": f"route_pressure.demo.sample.{index:04d}",
                "start_distance_m": start_m,
                "end_distance_m": end_m,
                "mid_distance_m": (start_m + end_m) / 2.0,
                "route_pressure_score": 35.0 + index * 20.0,
                "terrain": {
                    "distance_m": end_m - start_m,
                    "elevation_gain_m": 25.0 if index < 2 else 0.0,
                    "elevation_loss_m": 0.0 if index < 2 else 15.0,
                },
            }
        )
    _write_json(
        project_root / "outputs/route_pressure_profile.json",
        {
            "artifact_kind": "pretrip_route_pressure_profile",
            "schema_version": "route_pressure_profile.v1",
            "project_id": "demo",
            "policy": {"bin_m": 250.0, "centerline": "overpass_risk_ribbon"},
            "samples": pressure_samples,
        },
    )
    return project_root


def _source_record(
    source_id: str,
    source_number: int,
    filtered_path: Path,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "provider": "operator_supplied_local_file",
        "role": "reference_track",
        "route_role": "reference_track",
        "original_filename": f"reference-{source_number:03d}.gpx",
        "original_path": f"/private/source/reference-{source_number:03d}.gpx",
        "workspace_ref": f"inbox/gpx/reference_{source_number:03d}.gpx",
        "sha256": _sha256(filtered_path),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _write_gpx(
    path: Path,
    points: list[tuple[float, float]],
    timestamps: list[datetime] | None,
) -> None:
    rows = ["<?xml version='1.0' encoding='utf-8'?>", '<gpx version="1.1">', "<trk><trkseg>"]
    for index, (lat, lon) in enumerate(points):
        rows.append(f'<trkpt lat="{lat}" lon="{lon}">')
        rows.append(f"<ele>{1000 + index * 4}</ele>")
        if timestamps is not None:
            rows.append(
                f"<time>{timestamps[index].isoformat().replace('+00:00', 'Z')}</time>"
            )
        rows.append("</trkpt>")
    rows.extend(["</trkseg></trk>", "</gpx>"])
    path.write_text("\n".join(rows), encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
