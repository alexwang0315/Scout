from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from pretrip_route_architecture_intelligence import (
    build_route_architecture_intelligence,
    _historical_return_cost_projection,
    _historical_time_window_projection,
)
from pretrip_admin_view import build_pretrip_admin_view


ROOT = Path(__file__).resolve().parents[1]


def _historical_timing_fixture(distance=1000):
    return {
        "route_distance_m": distance,
        "bins": [{
            "start_distance_m": 0,
            "end_distance_m": distance,
            "forward": {"average_minutes": 60, "status": "observed"},
            "reverse": {"average_minutes": 120, "status": "estimated"},
        }],
        "checkpoints": [
            {"node_id": name, "label": name, "route_distance_m": position}
            for name, position in (("start", 0), ("middle", distance / 2), ("finish", distance))
        ],
        "daily_budget": {"minutes": 180},
        "daily_departures": {"status": "ready", "days": [{
            "day_id": "d1", "day_index": 1,
            "start_distance_m": 0, "end_distance_m": distance,
            "departure_minute_of_day": 360, "departure_status": "estimated",
        }]},
    }


def _project_historical_fixture(timing, target=1000):
    returns = _historical_return_cost_projection(
        timing, route_distance_m=target, distance_scale=1, source_ref="fixture.json"
    )
    window = _historical_time_window_projection(
        timing, return_projection=returns, route_distance_m=target,
        source_ref="fixture.json",
    )
    json.dumps((returns, window), allow_nan=False)
    return returns, window


@pytest.mark.parametrize("source, target", [(3, 3.006), (1000.3, 1007.3021)])
def test_historical_projection_snaps_only_exact_source_endpoint(source, target):
    assert source * (target / source) > target
    timing = _historical_timing_fixture(source)
    before = deepcopy(timing)
    returns, window = _project_historical_fixture(timing, target)
    assert returns["status"] == window["status"] == "ready"
    assert returns["checkpoints"][-1]["route_distance_m"] == target
    assert returns["checkpoints"][-1]["return_cost_minutes"] == 120
    assert window["days"][0]["end_distance_m"] == target
    assert window["checkpoints"][-1]["consumed_minutes"] == 60
    assert window["checkpoints"][-1]["remaining_minutes"] == 660
    assert window["checkpoints"][1]["remaining_minutes"] == pytest.approx(690)
    assert timing == before


@pytest.mark.parametrize("field", ["checkpoint", "camp", "bin", "day"])
def test_historical_projection_rejects_source_out_of_bounds_before_scaling(field):
    timing = _historical_timing_fixture(1000.3)
    outside = math.nextafter(1000.3, math.inf)
    if field == "checkpoint":
        timing["checkpoints"][-1]["route_distance_m"] = outside
    elif field == "camp":
        timing["camp_evidence"] = {"camps": [{"node_id": "outside", "route_distance_m": outside}]}
    elif field == "bin":
        timing["bins"][0]["end_distance_m"] = outside
    else:
        timing["daily_departures"]["days"][0]["end_distance_m"] = outside
    returns, window = _project_historical_fixture(timing, 1007.3021)
    if field == "checkpoint":
        assert returns["checkpoints"][-1]["route_distance_m"] is None
        assert returns["checkpoints"][-1]["return_cost_minutes"] is None
    elif field == "camp":
        assert returns["camps"] == []
        assert window["safe_points"][-1]["node_id"] == "finish"
    elif field == "bin":
        assert returns["stats"]["bin_geometry_valid"] is False
        assert window["checkpoints"][-1]["remaining_minutes"] is None
    else:
        assert window["status"] == "unavailable"
        assert window["stats"]["schedule_valid"] is False


def test_historical_projection_zero_source_does_not_move_start_to_display_finish():
    returns, window = _project_historical_fixture(_historical_timing_fixture(0))
    assert {row["route_distance_m"] for row in returns["checkpoints"]} == {0}
    assert window["status"] == "unavailable"
    assert window["safe_points"] == []


@pytest.mark.parametrize("key, value", [
    ("bins", None), ("bins", "invalid"), ("bins", [None, {}]),
    ("checkpoints", None), ("checkpoints", {"invalid": True}),
    ("checkpoints", [None, {}]), ("camp_evidence", None),
    ("camp_evidence", 12), ("camp_evidence", {"camps": None}),
    ("camp_evidence", {"camps": [None, 12, {}]}),
    ("daily_budget", 12), ("counts", "invalid"), ("policy", [None]),
    ("daily_departures", 12), ("daily_departures", {"days": None}),
    ("daily_departures", {"status": "ready", "days": [None, {}]}),
])
def test_historical_projection_malformed_containers_degrade_without_exception(key, value):
    timing = {**_historical_timing_fixture(), key: value}
    returns, window = _project_historical_fixture(timing)
    if key == "bins":
        assert returns["checkpoints"][-1]["return_cost_minutes"] is None
        assert window["checkpoints"][-1]["remaining_minutes"] is None
    if key == "daily_departures":
        assert window["status"] == "unavailable"
        assert all(row["remaining_minutes"] is None for row in window["checkpoints"])
    if key == "daily_budget":
        assert returns["daily_budget_minutes"] is None


def test_historical_projection_malformed_day_record_cannot_be_silently_removed():
    timing = _historical_timing_fixture()
    timing["daily_departures"]["days"].append(None)
    _, window = _project_historical_fixture(timing)
    assert window["stats"]["schedule_valid"] is False
    assert all(row["remaining_minutes"] is None for row in window["checkpoints"])


@pytest.mark.parametrize("status, reason", [
    ("unavailable", "invalid_schedule"), ("invalid_schedule", None),
    (None, None), ("ready", "invalid_schedule"),
])
def test_historical_projection_explicit_invalid_departures_never_publish_balance(status, reason):
    timing = _historical_timing_fixture()
    timing["daily_departures"].update(status=status, reason=reason)
    returns, window = _project_historical_fixture(timing)
    assert window["status"] == "unavailable"
    assert all(row["remaining_minutes"] is None for row in window["checkpoints"])
    assert window["departure_evidence"]["status"] == status
    assert returns["checkpoints"][-1]["return_cost_minutes"] == 120


def test_historical_projection_legacy_missing_departure_status_remains_compatible():
    timing = _historical_timing_fixture()
    del timing["daily_departures"]["status"]
    _, window = _project_historical_fixture(timing)
    assert window["status"] == "ready"
    assert window["checkpoints"][-1]["remaining_minutes"] == 660


def test_historical_return_projection_scales_distance_not_directional_time():
    from pretrip_route_architecture_intelligence import _historical_return_cost_projection

    result = _historical_return_cost_projection({
        "bins": [{"start_distance_m": 0, "end_distance_m": 1000,
                  "forward": {"average_minutes": 60, "status": "observed"},
                  "reverse": {"average_minutes": 30, "status": "estimated"}}],
        "checkpoints": [
            {"node_id": "start", "label": "Start", "route_distance_m": 0},
            {"node_id": "end", "label": "End", "route_distance_m": 1000},
        ],
        "camp_evidence": {"camps": [{"node_id": "camp", "label": "Camp", "route_distance_m": 500}]},
        "daily_budget": {"minutes": 20, "sample_day_count": 3},
    }, route_distance_m=2000, distance_scale=2, source_ref="outputs/timing.json")
    finish = result["checkpoints"][-1]
    assert finish["route_distance_m"] == 2000
    assert finish["return_to_entry_minutes"] == 30
    assert finish["return_cost_minutes"] == 15
    assert finish["return_target_distance_m"] == 1000
    assert finish["return_cost_status"] == "estimated"
    assert result["daily_budget"]["minutes"] == 20
    assert result["duration_scaled"] is False
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False


def test_historical_time_window_projection_scales_axis_not_clock_or_cost():
    from pretrip_route_architecture_intelligence import (
        _historical_return_cost_projection,
        _historical_time_window_projection,
    )

    timing = {
        "route_distance_m": 1000,
        "bins": [
            {
                "start_distance_m": 0,
                "end_distance_m": 1000,
                "forward": {"average_minutes": 60, "status": "observed"},
                "reverse": {"average_minutes": 120, "status": "estimated"},
            }
        ],
        "checkpoints": [
            {"node_id": "start", "label": "Start", "route_distance_m": 0},
            {"node_id": "end", "label": "End", "route_distance_m": 1000},
        ],
        "camp_evidence": {
            "camps": [{"node_id": "camp", "label": "Camp", "route_distance_m": 500}]
        },
        "daily_budget": {"minutes": 20},
        "daily_departures": {
            "timezone": "Asia/Taipei",
            "days": [
                {
                    "day_id": "d1",
                    "day_index": 1,
                    "start_distance_m": 0,
                    "end_distance_m": 1000,
                    "departure_minute_of_day": 360,
                    "departure_status": "estimated",
                }
            ],
        },
    }
    returns = _historical_return_cost_projection(
        timing, route_distance_m=2000, distance_scale=0.2, source_ref="timing.json"
    )
    result = _historical_time_window_projection(
        timing,
        return_projection=returns,
        route_distance_m=2000,
        source_ref="timing.json",
    )
    start, camp, finish = result["checkpoints"]
    assert start["initial_window_minutes"] == 720
    assert start["remaining_minutes"] == 720
    assert start["forward_to_safe_minutes"] == 30
    assert start["arrival_margin_minutes"] == 690
    assert camp["route_distance_m"] == 1000
    assert camp["remaining_minutes"] == 690
    assert camp["day_reset"] is False
    assert finish["consumed_minutes"] == 60
    assert finish["remaining_minutes"] == 660
    assert finish["remaining_status"] == "estimated"
    assert result["days"][0]["end_distance_m"] == 2000
    assert result["departure_evidence"]["days"][0]["end_distance_m"] == 1000
    assert result["duration_scaled"] is False
    assert result["candidate_only"] is True
    assert result["runtime_safety_truth"] is False


def test_historical_overnight_candidates_are_shared_without_filling_schedule_gaps():
    from pretrip_route_architecture_intelligence import (
        _historical_return_cost_projection,
        _historical_time_window_projection,
    )

    timing = {
        "bins": [
            {
                "start_distance_m": 0,
                "end_distance_m": 300,
                "forward": {"average_minutes": 30, "status": "observed"},
                "reverse": {"average_minutes": 60, "status": "observed"},
            }
        ],
        "checkpoints": [
            {"node_id": str(d), "label": str(d), "route_distance_m": d}
            for d in (0, 110, 300)
        ],
        "daily_budget": {"minutes": 5},
        "daily_departures": {
            "status": "ready",
            "days": [
                {
                    "day_id": "d1",
                    "day_index": 1,
                    "start_distance_m": 0,
                    "end_distance_m": 100,
                    "departure_minute_of_day": 360,
                    "departure_status": "estimated",
                },
                {
                    "day_id": "d2",
                    "day_index": 2,
                    "start_distance_m": 120,
                    "end_distance_m": 300,
                    "departure_minute_of_day": 420,
                    "departure_status": "estimated",
                    "preceding_gap_hours": 12,
                },
            ],
        },
    }
    returns = _historical_return_cost_projection(
        timing, route_distance_m=300, distance_scale=1, source_ref="timing.json"
    )
    window = _historical_time_window_projection(
        timing,
        return_projection=returns,
        route_distance_m=300,
        source_ref="timing.json",
    )
    assert returns["camp_evidence"]["overnight_candidate_count"] == 1
    assert returns["checkpoints"][0]["next_cp_id"] == "110"
    camp = returns["checkpoints"][1]
    assert camp["return_cost_minutes"] == 0
    assert camp["return_target_id"] == "historical_overnight.d1"
    assert window["checkpoints"][0]["next_safe_point_id"] == camp["return_target_id"]
    assert (
        next(node for node in window["checkpoints"] if node["node_id"] == "110")[
            "remaining_minutes"
        ]
        is None
    )
    reset = next(
        node
        for node in window["checkpoints"]
        if node["day_index"] == 2 and node["day_reset"]
    )
    assert reset["remaining_minutes"] == 660
    assert reset["route_distance_m"] == 120


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


def test_route_architecture_keeps_reference_schedule_and_defers_correction_to_calibration() -> None:
    projection = build_route_architecture_intelligence(
        project_id="explicit_pace_mapping",
        route={"route_name": "Explicit mapping route", "distance_m": 750.0},
        checkpoints=[],
        segments=[],
        retreat_routes=[],
        reference_pace_energy_analysis=_reference_pace_payload(),
        normalized_route_architecture={
            "pace_speed_correction_vectors": [
                {
                    "route_bin_id": "reference_pace.bin.0001",
                    "pace_speed_correction_ratio": 0.5,
                    "source_ref": (
                        "normalized/architecture/route_architecture.json"
                        "#pace_speed_correction_vectors"
                    ),
                    "review_state": "reviewed",
                }
            ]
        },
    )

    vectors = projection["segment_demand_vectors"]
    scheduled = next(
        vector
        for vector in vectors
        if vector["route_bin_id"] == "reference_pace.bin.0001"
    )
    assert "pace_speed_correction_ratio" not in scheduled
    assert "pace_speed_correction_ratio" not in vectors[0]
    pace_mapping = projection["pace_fit_mapping"]
    assert pace_mapping["status"] == "available"
    assert pace_mapping["reference_schedule_vector_count"] > 0
    assert pace_mapping["correction_default_ratio"] == 1.0
    assert pace_mapping["correction_default_status"] == "prior_uninformed"
    assert pace_mapping["correction_owner"] == "Scout Dashboard adaptive calibration"
    assert pace_mapping["schedule_is_not_corrected"] is True
    assert projection["route_power_model"]["power_domain"] == "pandolf_metabolic_power_w_estimate"
    assert projection["route_power_model"]["status"] == "available"


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
        "data_quality": {"status": "medium", "node_count": 3, "timed_node_count": 3},
        "nodes": [
            {
                "node_id": "cp.easy",
                "node_kind": "cp",
                "label": "Easy route detail",
                "named_places": [],
                "route_distance_m": 50.0,
                "passage_window": {
                    "start_distance_m": 0.0,
                    "end_distance_m": 300.0,
                    "distance_m": 300.0,
                },
                "duration_minutes": {
                    "min": 4.5,
                    "max": 8.0,
                    "average": 6.2,
                    "mode_5min": 5,
                    "mode_5min_tied_buckets": [5],
                },
                "sample_count": 6,
                "distinct_track_count": 5,
                "data_quality": "high",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
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
    assert timing["node_count"] == 3
    assert timing["timed_node_count"] == 3
    assert [item["node_id"] for item in timing["nodes"]] == [
        "cp.easy",
        "cp.001",
        "mcp.yunhai",
    ]
    easy, difficulty_cp, named = timing["nodes"]
    assert easy["source_node_kind"] == "cp"
    assert easy["node_kind"] == "mcp"
    assert easy["selection_role"] == "route_micro_checkpoint"
    assert easy["display_priority"] == "context"
    assert difficulty_cp["source_node_kind"] == "cp"
    assert difficulty_cp["node_kind"] == "cp"
    assert difficulty_cp["selection_role"] == "difficulty_cp"
    assert difficulty_cp["display_priority"] == "primary"
    assert difficulty_cp["difficulty"]["composite_pressure_index"] >= 55.0
    assert difficulty_cp["difficulty"]["route_bin_id"] == "reference_pace.bin.0001"
    assert named["source_node_kind"] == "mcp"
    assert named["node_kind"] == "mcp"
    assert named["selection_role"] == "authored_mcp"
    assert named["display_priority"] == "secondary"
    assert named["label"] == "雲海保線所"
    assert named["named_places"] == ["雲海保線所"]
    assert named["duration_minutes"] == {
        "min": 9.0,
        "max": 15.5,
        "average": 11.8,
        "mode_5min": 10,
        "mode_5min_tied_buckets": [10],
    }
    assert timing["selection_policy"] == {
        "default_node_kind": "mcp",
        "difficulty_cp_minimum_composite_pressure": 55.0,
        "difficulty_cp_requires_guidance_eligible": True,
        "difficulty_cp_cluster_gap_m": 500.0,
        "maximum_difficulty_cp_count": 10,
        "card_display_priorities": ["primary", "secondary"],
    }
    assert timing["difficulty_cp_count"] == 1
    assert timing["mcp_count"] == 2
    assert timing["card_node_count"] == 2
    assert timing["context_mcp_count"] == 1
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
        "所有自動對齊的 route-progress checkpoint 預設投影為 `MCP`",
        "`composite_pressure_index >= 55`",
        "每條 route 最多顯示 10 個 difficulty CP",
        "`display_priority=primary/secondary`",
    ):
        assert marker in standard
