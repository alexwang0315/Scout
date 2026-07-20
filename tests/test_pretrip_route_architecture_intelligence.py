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
        "segment_demand_vectors[]",
        "project-selected compiled mission graph",
        "privacy.raw_gpx_embedded=false",
        "runtime_safety_truth=false",
        "Spine / Map / Segment",
    ):
        assert marker in standard
