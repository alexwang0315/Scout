from __future__ import annotations

from pathlib import Path

from pretrip_route_architecture_intelligence import (
    build_route_architecture_intelligence,
)
from pretrip_admin_view import build_pretrip_admin_view


ROOT = Path(__file__).resolve().parents[1]


def _reference_pace_payload() -> dict:
    return {
        "artifact_kind": "pretrip_reference_pace_energy_analysis",
        "status": "completed",
        "source_provider": "historical_gpx_reference_corpus",
        "source_path": "outputs/reference_pace_energy_analysis.json",
        "sha256": "a" * 64,
        "counts": {
            "reference_track_count": 6,
            "usable_candidate_track_count": 5,
            "route_traversal_count": 40,
            "observed_route_bin_count": 3,
            "guidance_eligible_route_bin_count": 2,
        },
        "route_bins": [
            {
                "route_bin_id": "reference_pace.bin.0000",
                "route_bin_index": 0,
                "start_distance_m": 0.0,
                "end_distance_m": 250.0,
                "signed_grade_ratio_p50": 0.04,
                "grade_band": "04_moderate_uphill",
                "risk_score_p50": 22.0,
                "grade_adjusted_viscosity_index": 78.0,
                "continuous_moving_minutes_p50": 18.0,
                "positive_gravity_power_w_per_kg_p50": 0.12,
                "descent_dissipation_power_w_per_kg_p50": 0.0,
                "reference_speed_mps": {
                    "p25_conservative": 0.65,
                    "p50": 0.82,
                    "p75_fast_envelope": 1.04,
                },
                "reference_pace_seconds_per_100m": {
                    "p50": 122.0,
                    "p75_conservative": 154.0,
                },
                "traversal_count": 14,
                "distinct_track_count": 5,
                "data_quality": "high",
                "guidance_eligible": True,
                "association_flags": [],
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "route_bin_id": "reference_pace.bin.0001",
                "route_bin_index": 1,
                "start_distance_m": 250.0,
                "end_distance_m": 500.0,
                "signed_grade_ratio_p50": 0.31,
                "grade_band": "06_steep_uphill",
                "risk_score_p50": 76.0,
                "grade_adjusted_viscosity_index": 166.0,
                "continuous_moving_minutes_p50": 95.0,
                "positive_gravity_power_w_per_kg_p50": 0.42,
                "descent_dissipation_power_w_per_kg_p50": 0.0,
                "reference_speed_mps": {
                    "p25_conservative": 0.31,
                    "p50": 0.48,
                    "p75_fast_envelope": 0.69,
                },
                "reference_pace_seconds_per_100m": {
                    "p50": 208.0,
                    "p75_conservative": 322.0,
                },
                "traversal_count": 18,
                "distinct_track_count": 5,
                "data_quality": "high",
                "guidance_eligible": True,
                "association_flags": ["risk_associated", "continuous_duration_associated"],
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "route_bin_id": "reference_pace.bin.0002",
                "route_bin_index": 2,
                "start_distance_m": 500.0,
                "end_distance_m": 750.0,
                "signed_grade_ratio_p50": -0.18,
                "grade_band": "01_steep_downhill",
                "risk_score_p50": 48.0,
                "grade_adjusted_viscosity_index": 118.0,
                "continuous_moving_minutes_p50": 132.0,
                "positive_gravity_power_w_per_kg_p50": 0.0,
                "descent_dissipation_power_w_per_kg_p50": 0.37,
                "reference_speed_mps": {
                    "p25_conservative": 0.42,
                    "p50": 0.61,
                    "p75_fast_envelope": 0.77,
                },
                "reference_pace_seconds_per_100m": {
                    "p50": 164.0,
                    "p75_conservative": 238.0,
                },
                "traversal_count": 8,
                "distinct_track_count": 2,
                "data_quality": "low",
                "guidance_eligible": False,
                "association_flags": [],
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ],
        "privacy": {"raw_gpx_embedded": False, "precise_timestamps_embedded": False},
        "boundary": {"runtime_safety_truth": False},
    }


def test_route_architecture_projection_builds_candidate_only_mobility_vectors() -> None:
    projection = build_route_architecture_intelligence(
        project_id="demo_route",
        route={"route_name": "Demo ridge", "distance_m": 750.0},
        checkpoints=[
            {
                "candidate_id": "cp.start",
                "label": "Start",
                "checkpoint_type": "start",
                "route_distance_m": 0.0,
            },
            {
                "candidate_id": "cp.finish",
                "label": "Finish",
                "checkpoint_type": "finish",
                "route_distance_m": 750.0,
            },
        ],
        segments=[
            {
                "candidate_id": "seg.001",
                "from_candidate_id": "cp.start",
                "to_candidate_id": "cp.finish",
                "distance_m": 750.0,
            }
        ],
        retreat_routes=[
            {
                "candidate_id": "retreat.return",
                "label": "Return to entry",
                "retreat_type": "return_to_entry",
                "entry_checkpoint_candidate_id": "cp.start",
                "trigger_checkpoint_candidate_id": "cp.finish",
                "distance_m": 750.0,
                "review_state": "needs_review",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        reference_pace_energy_analysis=_reference_pace_payload(),
        route_pressure_profile={
            "counts": {"peak_count": 2},
            "summary": {"highest_route_pressure_score": 76.0},
            "boundary": {"runtime_safety_truth": False},
        },
        boss_points={"boss_points": []},
        normalized_route_architecture=None,
        compiled_mission_graph=None,
        source_refs={
            "project": "project.json",
            "reference_pace_energy_analysis": "outputs/reference_pace_energy_analysis.json",
            "route_architecture": "normalized/architecture/route_architecture.json",
            "compiled_mission_graph": "outputs/compiled_mission_graph.json",
            "retreat_routes": "candidates/retreat_routes.json",
        },
    )

    assert projection["schema_version"] == "scout_route_architecture_intelligence.v0"
    assert projection["status"] == "partial"
    assert projection["source_provider"] == "pretrip_workspace_projection"
    assert projection["source_path"] == "project.json#route_architecture_intelligence"
    assert len(projection["sha256"]) == 64
    assert projection["data_quality"]["band"] == "partial"
    assert projection["architecture_summary"]["route_type"] == "unclassified"
    assert projection["architecture_summary"]["demand_shape"] == "mid_route_pressure"
    assert projection["architecture_summary"]["reversibility"] == "unverified"

    vectors = projection["segment_demand_vectors"]
    assert len(vectors) == 3
    hard = vectors[1]
    assert hard["route_bin_id"] == "reference_pace.bin.0001"
    assert hard["historical_mobility_demand_vector"]["terrain_demand"] > 60
    assert hard["historical_mobility_demand_vector"]["risk_passage_pressure"] == 76.0
    assert hard["historical_mobility_demand_vector"]["slow_passage_impedance"] > 90
    assert hard["reference_speed_kmh"]["p50"] == 1.728
    assert hard["reference_pace_seconds_per_100m"]["p75_conservative"] == 322.0
    assert hard["candidate_only"] is True
    assert hard["runtime_safety_truth"] is False

    retreat = projection["retreat_dependencies"][0]
    assert retreat["candidate_id"] == "retreat.return"
    assert retreat["review_state"] == "needs_review"
    assert retreat["field_verified"] is False
    assert projection["alternatives"] == []
    assert projection["evidence_quality"]["missing_artifacts"] == [
        "normalized_route_architecture",
        "compiled_mission_graph",
    ]
    assert projection["privacy"] == {
        "raw_gpx_embedded": False,
        "raw_health_payload_embedded": False,
        "precise_activity_timestamps_embedded": False,
        "home_work_traces_embedded": False,
        "projection_contains_aggregate_route_metrics_only": True,
    }
    assert projection["boundary"] == {
        "candidate_only": True,
        "medical_diagnosis": False,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


def test_route_architecture_retains_golden_scope_axis_when_crowd_support_is_sparse() -> None:
    reference = _reference_pace_payload()
    reference["crowd_axis"] = {
        "status": "golden_route_axis_retained",
        "route_axis_basis": "golden_route_scope",
        "source_route_distance_m": 112_250.0,
        "analysis_origin_m": 0.0,
        "analysis_distance_m": 112_250.0,
        "axis_rebased": False,
        "first_sustained_crowd_support_m": 43_000.0,
        "leading_span_interpretability": "not_applicable",
        "locomotion_inference": "unknown",
        "requires_human_review": False,
    }

    projection = build_route_architecture_intelligence(
        project_id="golden_scope_demo",
        route={"route_name": "Golden scope route", "distance_m": 112_250.0},
        checkpoints=[
            {
                "candidate_id": "cp.scope.start",
                "label": "Crowd-supported start",
                "route_distance_m": 43_000.0,
            },
            {
                "candidate_id": "cp.scope.finish",
                "label": "Finish",
                "route_distance_m": 112_250.0,
            },
        ],
        segments=[],
        retreat_routes=[],
        reference_pace_energy_analysis=reference,
    )

    summary = projection["architecture_summary"]
    assert summary["route_distance_m"] == 112_250.0
    assert summary["source_route_distance_m"] == 112_250.0
    assert summary["crowd_analysis_origin_m"] == 0.0
    assert summary["route_axis_basis"] == "golden_route_scope"
    assert summary["route_axis_requires_human_review"] is False
    assert projection["route_spine"]["distance_m"] == 112_250.0
    assert projection["route_spine"]["source_distance_m"] == 112_250.0
    assert [item["route_distance_m"] for item in projection["route_spine"]["nodes"]] == [
        43_000.0,
        112_250.0,
    ]
    first = projection["segment_demand_vectors"][0]
    assert first["start_distance_m"] == 0.0
    assert first["source_start_distance_m"] == 0.0
    assert first["distance_label"] == "0.00–0.25K"


def test_route_architecture_normalizes_all_metrics_to_golden_gpx_distance_axis() -> None:
    reference = _reference_pace_payload()
    reference["crowd_axis"] = {
        "status": "golden_route_axis_retained",
        "route_axis_basis": "source_analysis_axis",
        "source_route_distance_m": 750.0,
        "analysis_distance_m": 750.0,
        "analysis_origin_m": 0.0,
        "axis_rebased": False,
    }
    reference["golden_route_elevation_profile"] = {
        "artifact_kind": "pretrip_golden_route_elevation_profile",
        "schema_version": "golden_route_elevation_profile.v0",
        "status": "available",
        "source_provider": "workspace_golden_gpx",
        "source_path": "inbox/gpx/golden.gpx",
        "sha256": "e" * 64,
        "distance_m": 500.0,
        "minimum_elevation_m": 1000.0,
        "maximum_elevation_m": 1250.0,
        "sample_count": 3,
        "samples": [
            {
                "route_distance_m": 0.0,
                "route_progress_ratio": 0.0,
                "elevation_m": 1000.0,
                "minimum_elevation_m": 1000.0,
                "maximum_elevation_m": 1000.0,
                "source_trackpoint_count": 1,
            },
            {
                "route_distance_m": 250.0,
                "route_progress_ratio": 0.5,
                "elevation_m": 1250.0,
                "minimum_elevation_m": 1240.0,
                "maximum_elevation_m": 1260.0,
                "source_trackpoint_count": 3,
            },
            {
                "route_distance_m": 500.0,
                "route_progress_ratio": 1.0,
                "elevation_m": 1100.0,
                "minimum_elevation_m": 1100.0,
                "maximum_elevation_m": 1100.0,
                "source_trackpoint_count": 1,
            },
        ],
        "data_quality": {"status": "high"},
        "privacy": {
            "coordinates_embedded": False,
            "precise_timestamps_embedded": False,
            "raw_gpx_embedded": False,
            "source_original_path_embedded": False,
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }

    projection = build_route_architecture_intelligence(
        project_id="golden_profile_demo",
        route={"route_name": "Golden profile route", "distance_m": 750.0},
        checkpoints=[
            {
                "candidate_id": "cp.start",
                "label": "Start",
                "route_distance_m": 0.0,
            },
            {
                "candidate_id": "cp.finish",
                "label": "Finish",
                "route_distance_m": 750.0,
            },
        ],
        segments=[],
        retreat_routes=[],
        reference_pace_energy_analysis=reference,
    )

    summary = projection["architecture_summary"]
    assert summary["route_distance_m"] == 500.0
    assert summary["source_route_distance_m"] == 750.0
    assert summary["route_axis_basis"] == "golden_gpx_distance"
    assert summary["route_axis_transform"] == {
        "status": "progress_normalized",
        "source_distance_m": 750.0,
        "golden_distance_m": 500.0,
        "source_to_golden_scale": 0.666667,
        "source_distances_preserved": True,
    }
    assert projection["route_spine"]["distance_m"] == 500.0
    assert projection["route_spine"]["source_distance_m"] == 750.0
    assert [node["route_distance_m"] for node in projection["route_spine"]["nodes"]] == [
        0.0,
        500.0,
    ]
    vectors = projection["segment_demand_vectors"]
    assert vectors[1]["source_start_distance_m"] == 250.0
    assert vectors[1]["source_end_distance_m"] == 500.0
    assert vectors[1]["start_distance_m"] == 166.667
    assert vectors[1]["end_distance_m"] == 333.333
    assert vectors[1]["distance_label"] == "0.17–0.33K"
    profile = projection["golden_route_elevation_profile"]
    assert profile["distance_m"] == 500.0
    assert profile["sample_count"] == 3
    assert profile["samples"][1]["elevation_m"] == 1250.0
    assert profile["privacy"]["coordinates_embedded"] is False
    assert profile["boundary"]["runtime_safety_truth"] is False
    assert projection["crowd_axis"]["analysis_distance_m"] == 500.0
    assert projection["crowd_axis"]["source_analysis_distance_m"] == 750.0


def test_route_architecture_projects_every_cp_mcp_passage_timing_node() -> None:
    reference = _reference_pace_payload()
    reference["checkpoint_passage_timing"] = {
        "artifact_kind": "pretrip_checkpoint_passage_timing",
        "schema_version": "checkpoint_passage_timing.v0",
        "source_provider": "historical_gpx_reference_corpus",
        "source_path": (
            "outputs/reference_pace_energy_analysis.json#checkpoint_passage_timing"
        ),
        "sha256": "b" * 64,
        "policy": {
            "passage_window_distance_m": 500.0,
            "mode_bucket_minutes": 5,
        },
        "data_quality": {"status": "medium", "node_count": 2, "timed_node_count": 2},
        "nodes": [
            {
                "node_id": "cp.001",
                "node_kind": "cp",
                "label": "CP 001",
                "named_places": [],
                "route_distance_m": 250.0,
                "passage_window": {
                    "start_distance_m": 0.0,
                    "end_distance_m": 500.0,
                    "distance_m": 500.0,
                },
                "duration_minutes": {
                    "min": 7.5,
                    "max": 11.0,
                    "average": 9.2,
                    "mode_5min": 10,
                    "mode_5min_tied_buckets": [10],
                },
                "sample_count": 6,
                "distinct_track_count": 5,
                "data_quality": "high",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            {
                "node_id": "mcp.yunhai",
                "node_kind": "mcp",
                "label": "雲海保線所",
                "named_places": ["雲海保線所"],
                "route_distance_m": 500.0,
                "passage_window": {
                    "start_distance_m": 250.0,
                    "end_distance_m": 750.0,
                    "distance_m": 500.0,
                },
                "duration_minutes": {
                    "min": 9.0,
                    "max": 15.5,
                    "average": 11.8,
                    "mode_5min": 10,
                    "mode_5min_tied_buckets": [10],
                },
                "sample_count": 5,
                "distinct_track_count": 4,
                "data_quality": "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ],
        "privacy": {"raw_gpx_embedded": False, "precise_timestamps_embedded": False},
        "boundary": {"candidate_only": True, "runtime_safety_truth": False},
    }

    projection = build_route_architecture_intelligence(
        project_id="timed_route",
        route={"route_name": "Timed route", "distance_m": 750.0},
        checkpoints=[],
        segments=[],
        retreat_routes=[],
        reference_pace_energy_analysis=reference,
    )

    timing = projection["checkpoint_passage_timing"]
    assert timing["node_count"] == 2
    assert timing["timed_node_count"] == 2
    assert [item["node_id"] for item in timing["nodes"]] == [
        "cp.001",
        "mcp.yunhai",
    ]
    named = timing["nodes"][1]
    assert named["label"] == "雲海保線所"
    assert named["named_places"] == ["雲海保線所"]
    assert named["duration_minutes"] == {
        "min": 9.0,
        "max": 15.5,
        "average": 11.8,
        "mode_5min": 10,
        "mode_5min_tied_buckets": [10],
    }
    assert timing["privacy"]["raw_gpx_embedded"] is False
    assert timing["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_projection_uses_reviewed_structure_without_inventing_branches() -> None:
    projection = build_route_architecture_intelligence(
        project_id="reviewed_route",
        route={"route_name": "Reviewed traverse", "distance_m": 750.0},
        checkpoints=[],
        segments=[],
        retreat_routes=[],
        reference_pace_energy_analysis=_reference_pace_payload(),
        normalized_route_architecture={
            "route_type": "A_to_B_traverse",
            "alternatives": [
                {
                    "alternative_id": "alt.short",
                    "label": "Short route",
                    "review_state": "reviewed",
                }
            ],
        },
        compiled_mission_graph={"nodes": [{"id": "start"}], "edges": []},
        source_refs={"project": "project.json"},
    )

    assert projection["status"] == "ready"
    assert projection["architecture_summary"]["route_type"] == "A_to_B_traverse"
    assert projection["architecture_summary"]["reversibility"] == "graph_available"
    assert [
        {
            key: item[key]
            for key in (
                "alternative_id",
                "label",
                "review_state",
                "candidate_only",
                "runtime_safety_truth",
            )
        }
        for item in projection["alternatives"]
    ] == [
        {
            "alternative_id": "alt.short",
            "label": "Short route",
            "review_state": "reviewed",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    assert len(projection["alternatives"][0]["model_output_sha256"]) == 64
    assert projection["alternatives"][0]["source_refs"] == [
        "normalized/architecture/route_architecture.json"
    ]
    assert projection["retreat_dependencies"] == []


def test_route_architecture_projection_derives_candidate_topology_and_time_demand() -> None:
    projection = build_route_architecture_intelligence(
        project_id="workspace_route",
        route={"route_name": "Workspace route", "distance_m": 12_000.0},
        checkpoints=[
            {
                "candidate_id": "cp.start",
                "label": "Start",
                "checkpoint_type": "start",
                "route_distance_m": 0.0,
            },
            {
                "candidate_id": "cp.finish",
                "label": "Finish",
                "checkpoint_type": "finish",
                "route_distance_m": 12_000.0,
            },
        ],
        segments=[
            {
                "candidate_id": "seg.001",
                "from_candidate_id": "cp.start",
                "to_candidate_id": "cp.mid",
                "distance_m": 6_000.0,
            },
            {
                "candidate_id": "seg.002",
                "from_candidate_id": "cp.mid",
                "to_candidate_id": "cp.finish",
                "distance_m": 6_000.0,
            },
        ],
        retreat_routes=[],
        reference_pace_energy_analysis=_reference_pace_payload(),
        candidate_mission_graph={
            "name": "Workspace candidate graph",
            "checkpoints": [
                {
                    "checkpoint_id": "cp.start",
                    "checkpoint_type": "start",
                    "lat": 23.95000,
                    "lon": 121.17000,
                },
                {
                    "checkpoint_id": "cp.finish",
                    "checkpoint_type": "finish",
                    "lat": 23.95035,
                    "lon": 121.17045,
                },
            ],
            "segments": [
                {
                    "segment_id": "seg.001",
                    "from_checkpoint_id": "cp.start",
                    "to_checkpoint_id": "cp.mid",
                    "requirement": {"expected_duration_seconds": 900},
                },
                {
                    "segment_id": "seg.002",
                    "from_checkpoint_id": "cp.mid",
                    "to_checkpoint_id": "cp.finish",
                    "requirement": {"expected_duration_seconds": 1_200},
                },
            ],
            "diversion_points": [],
        },
        source_refs={
            "compiled_mission_graph_candidate": (
                "outputs/compiled_mission_graph.candidate.json"
            )
        },
    )

    summary = projection["architecture_summary"]
    assert summary["route_type"] == "closed_route_candidate"
    assert summary["route_type_basis"] == "candidate_graph_start_finish_proximity"
    assert summary["start_finish_gap_m"] < 100
    assert summary["reversibility"] == "candidate_graph_unverified"

    graph = projection["checkpoint_graph"]
    assert graph["status"] == "compiled_candidate"
    assert graph["candidate_mission_graph_available"] is True
    assert graph["compiled_mission_graph_available"] is False
    assert graph["mission_graph_node_count"] == 2
    assert graph["mission_graph_edge_count"] == 2

    time_dependencies = projection["time_dependencies"]
    assert time_dependencies["candidate_graph_duration_seconds"] == 2_100
    assert time_dependencies["candidate_graph_duration_hours"] == 0.583
    assert time_dependencies["candidate_graph_segment_count"] == 2

    assert projection["evidence_quality"]["missing_artifacts"] == [
        "normalized_route_architecture",
        "reviewed_compiled_mission_graph",
    ]
    source_status = {
        item["source_key"]: item["status"]
        for item in projection["evidence_quality"]["source_refs"]
    }
    assert source_status["compiled_mission_graph_candidate"] == "available"
    assert source_status["compiled_mission_graph"] == "missing"
    assert projection["boundary"]["runtime_safety_truth"] is False


def test_pretrip_admin_view_exposes_route_architecture_projection() -> None:
    view = build_pretrip_admin_view("chilai_nanhua_day1")

    projection = view["route_architecture_intelligence"]
    assert projection["schema_version"] == "scout_route_architecture_intelligence.v0"
    assert projection["status"] in {"partial", "ready"}
    assert projection["boundary"]["runtime_safety_truth"] is False
    assert projection["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert (
        view["tabs"]["pre_trip_planning"]["route_architecture_intelligence"]
        == projection
    )


def test_outdoor_standard_documents_route_architecture_page_contract() -> None:
    standard = (
        ROOT / "docs" / "specs" / "SCOUT_OUTDOOR_AI_AGENT_STANDARD.md"
    ).read_text(encoding="utf-8")

    for marker in (
        "Architecture / Route Architecture Intelligence 功能頁",
        "Route Fingerprint",
        "historical_mobility_demand_vector",
        "crowd_axis",
        "scope_reference",
        "low_interpretability",
        "segment_demand_vectors[]",
        "project-selected compiled mission graph",
        "privacy.raw_gpx_embedded=false",
        "runtime_safety_truth=false",
        "Spine / Map / Segment",
    ):
        assert marker in standard
