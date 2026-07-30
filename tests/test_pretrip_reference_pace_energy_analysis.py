from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pretrip_architecture_preparation import (
    inspect_architecture_readiness,
    prepare_route_architecture_intelligence,
)
from pretrip_reference_pace_energy_analysis import (
    _crowd_supported_axis,
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
    assert report["crowd_axis"]["analysis_distance_m"] == 600.0
    assert max(item["end_distance_m"] for item in report["route_bins"]) == 600.0

    passage_timing = report["checkpoint_passage_timing"]
    assert passage_timing["artifact_kind"] == "pretrip_checkpoint_passage_timing"
    assert passage_timing["schema_version"] == "checkpoint_passage_timing.v0"
    assert passage_timing["source_provider"] == "historical_gpx_reference_corpus"
    assert passage_timing["source_path"].endswith("#checkpoint_passage_timing")
    assert len(passage_timing["sha256"]) == 64
    assert passage_timing["policy"] == {
        "passage_window_distance_m": 500.0,
        "window_alignment": "centered_on_cp_or_mcp_clipped_to_route_extent",
        "minimum_window_coverage_ratio": 0.6,
        "mode_bucket_minutes": 5,
        "mode_bucket_rounding": "nearest_5_minutes_half_up_minimum_5",
        "sample_unit": "one_contiguous_track_bout_direction_window_passage",
    }
    assert passage_timing["data_quality"]["node_count"] == 4
    assert passage_timing["data_quality"]["timed_node_count"] == 4
    assert {item["node_kind"] for item in passage_timing["nodes"]} == {"cp", "mcp"}
    named_mcp = next(
        item
        for item in passage_timing["nodes"]
        if item["node_id"] == "mcp.yunhai"
    )
    assert named_mcp["label"] == "雲海保線所"
    assert named_mcp["named_places"] == ["雲海保線所"]
    assert named_mcp["route_distance_m"] == 300.0
    assert named_mcp["passage_window"]["distance_m"] == 500.0
    assert named_mcp["sample_count"] >= 3
    assert named_mcp["distinct_track_count"] >= 3
    assert set(named_mcp["duration_minutes"]) == {
        "min",
        "max",
        "average",
        "mode_5min",
        "mode_5min_tied_buckets",
    }
    assert named_mcp["duration_minutes"]["min"] <= named_mcp["duration_minutes"][
        "average"
    ] <= named_mcp["duration_minutes"]["max"]
    assert named_mcp["duration_minutes"]["mode_5min"] % 5 == 0
    assert named_mcp["candidate_only"] is True
    assert named_mcp["runtime_safety_truth"] is False
    assert passage_timing["privacy"]["raw_gpx_embedded"] is False
    assert passage_timing["privacy"]["precise_timestamps_embedded"] is False
    assert passage_timing["boundary"]["phase1_runtime_safety_truth"] is False

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


def test_reference_analysis_emits_coordinate_free_golden_route_elevation_profile(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)

    report, _ = build_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-17T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )

    profile = report["golden_route_elevation_profile"]
    assert profile["artifact_kind"] == "pretrip_golden_route_elevation_profile"
    assert profile["schema_version"] == "golden_route_elevation_profile.v0"
    assert profile["status"] == "available"
    assert profile["source_provider"] == "workspace_golden_gpx"
    assert profile["source_path"].endswith(
        "normalized/routes/filtered/primary.demo.speed_filtered.gpx"
    )
    assert len(profile["sha256"]) == 64
    assert 550.0 < profile["distance_m"] < 650.0
    assert profile["minimum_elevation_m"] == 1000.0
    assert profile["maximum_elevation_m"] == 1048.0
    assert profile["source_trackpoint_count"] == 13
    assert profile["elevation_trackpoint_count"] == 13
    assert profile["sample_count"] == len(profile["samples"])
    assert profile["sample_count"] <= 800
    assert profile["samples"][0]["route_distance_m"] == 0.0
    assert profile["samples"][-1]["route_progress_ratio"] == 1.0
    assert all(
        set(sample)
        == {
            "route_distance_m",
            "route_progress_ratio",
            "elevation_m",
            "minimum_elevation_m",
            "maximum_elevation_m",
            "source_trackpoint_count",
        }
        for sample in profile["samples"]
    )
    assert profile["privacy"] == {
        "coordinates_embedded": False,
        "precise_timestamps_embedded": False,
        "raw_gpx_embedded": False,
        "source_original_path_embedded": False,
    }
    assert profile["boundary"]["candidate_only"] is True
    assert profile["boundary"]["runtime_safety_truth"] is False
    serialized = json.dumps(profile, ensure_ascii=False)
    assert "lat" not in serialized
    assert "lon" not in serialized
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


def test_reference_analysis_core_stage_uses_primary_route_without_enrichments(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)
    (project_root / "outputs/risk/risk_score_points.geojson").unlink()
    (project_root / "outputs/route_pressure_profile.json").unlink()

    report, pace_map = build_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-29T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )

    assert report["status"] == "completed"
    assert report["preparation_stage"] == "core"
    assert report["policy"]["route_centerline"] == "primary_speed_filtered_gpx"
    assert report["policy"]["slope_source"] == "unavailable_in_core_stage"
    assert report["source_refs"]["risk_score_points"]["status"] == "missing"
    assert report["source_refs"]["route_pressure_profile"]["status"] == "missing"
    assert report["source_refs"]["route_axis"]["status"] == "available"
    assert report["counts"]["canonical_route_sample_count"] == 13
    assert report["counts"]["observed_route_bin_count"] > 0
    assert report["data_quality"]["risk_enrichment_available"] is False
    assert report["data_quality"]["terrain_enrichment_available"] is False
    assert pace_map["features"]


def test_architecture_preparation_writes_readiness_refs_and_reuses_fresh_outputs(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)

    first = prepare_route_architecture_intelligence(
        project_root,
        generated_at="2026-07-29T00:00:00+00:00",
    )
    second = prepare_route_architecture_intelligence(
        project_root,
        generated_at="2026-07-29T00:05:00+00:00",
    )

    assert first["status"] == "ready"
    assert first["preparation_stage"] == "enriched"
    assert first["reused"] is False
    assert first["observed_route_bin_count"] > 0
    assert second["status"] == "ready"
    assert second["reused"] is True
    assert second["input_sha256"] == first["input_sha256"]

    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert project["reference_pace_energy_analysis_ref"] == (
        "outputs/reference_pace_energy_analysis.json"
    )
    assert project["reference_pace_energy_map_geojson_ref"] == (
        "outputs/reference_pace_energy_map.geojson"
    )
    assert project["architecture_preparation_manifest_ref"] == (
        "outputs/architecture_preparation_manifest.json"
    )
    assert project["architecture_preparation_status"] == "ready"
    assert project["architecture_preparation_stage"] == "enriched"
    assert project["architecture_preparation_input_sha256"] == first["input_sha256"]

    readiness = inspect_architecture_readiness(project_root)
    assert readiness["status"] == "ready"
    assert readiness["fresh"] is True
    assert readiness["browseable"] is True


def test_architecture_readiness_detects_changed_historical_source_index(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)
    prepared = prepare_route_architecture_intelligence(
        project_root,
        generated_at="2026-07-29T00:00:00+00:00",
    )
    source_index_path = project_root / "sources/historical_gpx_source_index.json"
    source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
    source_index["preparation_test_revision"] = 2
    _write_json(source_index_path, source_index)

    readiness = inspect_architecture_readiness(project_root)

    assert prepared["status"] == "ready"
    assert readiness["status"] == "stale"
    assert readiness["fresh"] is False
    assert readiness["browseable"] is True
    assert readiness["input_sha256"] != prepared["input_sha256"]


def test_reference_analysis_treats_golden_route_as_equal_crowd_evidence(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)
    source_index_path = project_root / "sources/historical_gpx_source_index.json"
    source_index = json.loads(source_index_path.read_text(encoding="utf-8"))
    primary_path = (
        project_root
        / "normalized/routes/filtered/primary.demo.speed_filtered.gpx"
    )
    raw_primary_path = project_root / "inbox/gpx/primary-demo.gpx"
    raw_primary_path.parent.mkdir(parents=True)
    route_points = [(23.95, 121.0 + index * 0.00049) for index in range(13)]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fast_timestamps = [base_time + timedelta(seconds=index) for index in range(13)]
    walking_timestamps = [
        base_time + timedelta(hours=1, seconds=index * 50)
        for index in range(13)
    ]
    _write_multisegment_gpx(
        raw_primary_path,
        [route_points, route_points],
        [fast_timestamps, walking_timestamps],
    )
    _write_gpx(primary_path, route_points, walking_timestamps)
    source_index["sources"].insert(
        0,
        {
            "source_id": "gpx.source.demo",
            "provider": "operator_supplied_local_file",
            "role": "golden_route_reference",
            "route_role": "golden_route",
            "original_filename": "primary-demo.gpx",
            "original_path": "/private/source/primary-demo.gpx",
            "workspace_ref": "inbox/gpx/primary-demo.gpx",
            "sha256": _sha256(raw_primary_path),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    )
    source_index["source_file_count"] = len(source_index["sources"])
    _write_json(source_index_path, source_index)

    report, _ = build_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-21T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )

    assert report["counts"]["reference_track_count"] == 4
    assert report["counts"]["scope_reference_track_count"] == 1
    assert report["counts"]["crowd_track_count"] == 5
    golden = next(
        item for item in report["tracks"] if item["source_id"] == "gpx.source.demo"
    )
    assert golden["source_role"] == "scope_reference"
    assert golden["statistical_weight"] == "equal_track_route_bin_traversal"
    assert golden["analysis_source"]["kind"] == "workspace_raw_gpx"
    assert golden["trackpoint_count"] == 26
    assert golden["adjacent_pair_speed_filter"]["accepted_pair_count"] == 12
    assert golden["excluded_segment_counts"][
        "above_or_equal_maximum_speed"
    ] == 12
    assert golden["route_traversal_count"] > 0
    assert golden["segment_diagnostics"][0]["interpretability"] == (
        "low_interpretability"
    )
    assert golden["segment_diagnostics"][0]["locomotion_class"] == "unknown"
    assert golden["segment_diagnostics"][1]["interpretability"] == "usable"
    assert report["policy"]["source_role_policy"] == (
        "golden_route_is_scope_reference_and_equal_weight_crowd_observation"
    )


def test_primary_statistics_filter_each_adjacent_pair_without_dropping_track(
    tmp_path: Path,
) -> None:
    project_root = _write_workspace(tmp_path)
    reference_path = (
        project_root
        / "normalized/routes/filtered/reference_001.demo.speed_filtered.gpx"
    )
    route_points = [(23.95, 121.0 + index * 0.00049) for index in range(5)]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [base_time]
    for delta_seconds in (36, 200, 15, 36):
        timestamps.append(timestamps[-1] + timedelta(seconds=delta_seconds))
    _write_gpx(reference_path, route_points, timestamps)

    report, _ = build_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-21T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=1,
    )

    track = next(
        item
        for item in report["tracks"]
        if item["source_id"] == "gpx.source.demo.reference.001"
    )
    pair_filter = track["adjacent_pair_speed_filter"]
    assert pair_filter == {
        "unit_of_analysis": "adjacent_trackpoint_pair",
        "minimum_speed_kmh_exclusive": 1.0,
        "maximum_speed_kmh_exclusive": 10.0,
        "strict_bounds": True,
        "whole_track_or_segment_average_used_for_filtering": False,
        "positive_timed_pair_count": 4,
        "accepted_pair_count": 2,
    }
    assert track["excluded_segment_counts"]["at_or_below_minimum_speed"] == 1
    assert track["excluded_segment_counts"]["above_or_equal_maximum_speed"] == 1
    assert track["route_traversal_count"] == 2
    assert track["segment_diagnostics"][0]["accepted_pair_count"] == 2
    assert track["segment_diagnostics"][0][
        "whole_segment_average_used_for_filtering"
    ] is False
    assert report["counts"]["route_traversal_count"] > track[
        "route_traversal_count"
    ]
    assert all(
        1.0 < item["reference_speed_mps"]["p50"] * 3.6 < 10.0
        for item in report["route_bins"]
    )


def test_golden_route_axis_is_not_rebased_by_sparse_crowd_support() -> None:
    route_bins = [
        {
            "route_bin_index": 0,
            "start_distance_m": 0.0,
            "end_distance_m": 250.0,
            "distinct_track_count": 1,
            "guidance_eligible": False,
        },
        {
            "route_bin_index": 160,
            "start_distance_m": 40_000.0,
            "end_distance_m": 40_250.0,
            "distinct_track_count": 1,
            "guidance_eligible": False,
        },
        *[
            {
                "route_bin_index": index,
                "start_distance_m": index * 250.0,
                "end_distance_m": (index + 1) * 250.0,
                "distinct_track_count": 4,
                "guidance_eligible": True,
            }
            for index in range(172, 180)
        ],
    ]

    axis = _crowd_supported_axis(
        route_bins,
        source_route_distance_m=112_250.0,
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )

    assert axis["status"] == "golden_route_axis_retained"
    assert axis["route_axis_basis"] == "golden_route_scope"
    assert axis["analysis_origin_m"] == 0.0
    assert axis["analysis_distance_m"] == 112_250.0
    assert axis["axis_rebased"] is False
    assert axis["first_sustained_crowd_support_m"] == 43_000.0
    assert axis["leading_span_interpretability"] == "not_applicable"
    assert axis["requires_human_review"] is False
    assert axis["locomotion_inference"] == "unknown"

    ordinary_axis = _crowd_supported_axis(
        route_bins[2:],
        source_route_distance_m=45_000.0,
        route_bin_m=250.0,
        min_tracks_for_guidance=3,
    )
    assert ordinary_axis["status"] == "golden_route_axis_retained"
    assert ordinary_axis["analysis_origin_m"] == 0.0
    assert ordinary_axis["requires_human_review"] is False


def test_sequence_map_matching_preserves_out_and_back_route_progress(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "out-and-back"
    raw_root = project_root / "inbox/gpx"
    source_root = project_root / "sources"
    risk_root = project_root / "outputs/risk"
    raw_root.mkdir(parents=True)
    source_root.mkdir()
    risk_root.mkdir(parents=True)

    route_points = [
        (23.95, 121.00000),
        (23.95, 121.00245),
        (23.95, 121.00490),
        (23.95, 121.00245),
        (23.95, 121.00000),
    ]
    route_distances_m = [0.0, 250.0, 500.0, 750.0, 1_000.0]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [
        base_time + timedelta(seconds=index * 180)
        for index in range(len(route_points))
    ]
    raw_path = raw_root / "golden.gpx"
    _write_gpx(raw_path, route_points, timestamps)
    _write_json(
        project_root / "project.json",
        {
            "project_id": "out-and-back",
            "historical_gpx_source_index_ref": (
                "sources/historical_gpx_source_index.json"
            ),
            "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
            "route_pressure_profile_ref": "outputs/route_pressure_profile.json",
        },
    )
    _write_json(
        source_root / "historical_gpx_source_index.json",
        {
            "artifact_kind": "pretrip_historical_gpx_source_index",
            "project_id": "out-and-back",
            "source_file_count": 1,
            "sources": [
                {
                    "source_id": "gpx.source.out-and-back.primary",
                    "provider": "operator_supplied_local_file",
                    "role": "golden_route_reference",
                    "route_role": "golden_route",
                    "original_filename": "golden.gpx",
                    "original_path": "/private/source/golden.gpx",
                    "workspace_ref": "inbox/gpx/golden.gpx",
                    "sha256": _sha256(raw_path),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            ],
        },
    )
    _write_json(
        risk_root / "risk_score_points.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lon, lat],
                    },
                    "properties": {
                        "distance_m": distance_m,
                        "rs": 40.0,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    },
                }
                for (lat, lon), distance_m in zip(
                    route_points,
                    route_distances_m,
                    strict=True,
                )
            ],
        },
    )
    _write_json(
        project_root / "outputs/route_pressure_profile.json",
        {
            "artifact_kind": "pretrip_route_pressure_profile",
            "schema_version": "route_pressure_profile.v1",
            "project_id": "out-and-back",
            "samples": [
                {
                    "sample_id": f"sample.{index}",
                    "start_distance_m": index * 250.0,
                    "end_distance_m": (index + 1) * 250.0,
                    "terrain": {
                        "distance_m": 250.0,
                        "elevation_gain_m": 0.0,
                        "elevation_loss_m": 0.0,
                    },
                }
                for index in range(4)
            ],
        },
    )

    report, _ = build_reference_pace_energy_analysis(
        project_root,
        generated_at="2026-07-21T00:00:00+00:00",
        route_bin_m=250.0,
        min_tracks_for_guidance=1,
    )

    assert [item["route_bin_index"] for item in report["route_bins"]] == [0, 1, 2, 3]
    assert report["crowd_axis"]["analysis_distance_m"] == 1_000.0
    assert report["tracks"][0]["excluded_segment_counts"] == {}


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
        "checkpoint_candidates_ref": "candidates/checkpoints.json",
        "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
        "mcp_named_point_evidence_ref": "outputs/mcp/named_point_evidence.json",
    }
    _write_json(project_root / "project.json", project)

    route_points = [
        (23.95, 121.0 + index * 0.00049)
        for index in range(13)
    ]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _write_gpx(
        filtered_root / "primary.demo.speed_filtered.gpx",
        route_points,
        [base_time + timedelta(seconds=index * 50) for index in range(13)],
    )
    _write_json(
        project_root / "candidates/checkpoints.json",
        [
            {
                "candidate_id": "cp.start",
                "label": "Start",
                "checkpoint_type": "start",
                "route_point_index": 0,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "candidate_id": "cp.001",
                "label": "CP 001",
                "checkpoint_type": "route_progress",
                "route_point_index": 6,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "candidate_id": "cp.finish",
                "label": "Finish",
                "checkpoint_type": "finish",
                "route_point_index": 12,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ],
    )
    _write_json(
        project_root / "outputs/mcp/mcp_candidates.json",
        {
            "mcp_candidates": [
                {
                    "mcp_id": "mcp.yunhai",
                    "label": "雲海保線所",
                    "distance_m": 300.0,
                    "linked_named_points": ["np.yunhai"],
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                }
            ]
        },
    )
    _write_json(
        project_root / "outputs/mcp/named_point_evidence.json",
        {
            "named_points": [
                {
                    "named_point_id": "np.yunhai",
                    "canonical_name": "雲海保線所",
                    "route_position": {"distance_m": 300.0},
                }
            ]
        },
    )
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


def _write_multisegment_gpx(
    path: Path,
    segments: list[list[tuple[float, float]]],
    timestamps: list[list[datetime]],
) -> None:
    rows = ["<?xml version='1.0' encoding='utf-8'?>", '<gpx version="1.1">', "<trk>"]
    for points, segment_timestamps in zip(segments, timestamps, strict=True):
        rows.append("<trkseg>")
        for index, (lat, lon) in enumerate(points):
            rows.append(f'<trkpt lat="{lat}" lon="{lon}">')
            rows.append(f"<ele>{1000 + index * 4}</ele>")
            rows.append(
                f"<time>{segment_timestamps[index].isoformat().replace('+00:00', 'Z')}</time>"
            )
            rows.append("</trkpt>")
        rows.append("</trkseg>")
    rows.extend(["</trk>", "</gpx>"])
    path.write_text("\n".join(rows), encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
