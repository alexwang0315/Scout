"""Deterministic candidate projection for Scout Route Architecture Intelligence.

The projection intentionally separates observed historical mobility patterns from
reviewed route topology.  It is a planning/read-only artifact: it never calls a
safety API and it cannot mutate runtime safety truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "scout_route_architecture_intelligence.v0"
MAX_SPINE_NODES = 40
MAX_GRAPH_EDGES = 160
MAX_PRESSURE_ANCHORS = 10
DIFFICULTY_CP_MIN_COMPOSITE_PRESSURE = 55.0
DIFFICULTY_CP_CLUSTER_GAP_M = 500.0
DIFFICULTY_CP_MAX_COUNT = 10
DIFFICULTY_CP_MAX_MATCH_DISTANCE_M = 1_000.0


def build_route_architecture_intelligence(
    *,
    project_id: str,
    route: Mapping[str, Any] | None,
    checkpoints: Sequence[Mapping[str, Any]] | None,
    segments: Sequence[Mapping[str, Any]] | None,
    retreat_routes: Sequence[Mapping[str, Any]] | None,
    reference_pace_energy_analysis: Mapping[str, Any] | None = None,
    route_pressure_profile: Mapping[str, Any] | None = None,
    boss_points: Mapping[str, Any] | None = None,
    normalized_route_architecture: Mapping[str, Any] | None = None,
    compiled_mission_graph: Mapping[str, Any] | None = None,
    candidate_mission_graph: Mapping[str, Any] | None = None,
    eta: Mapping[str, Any] | None = None,
    weather_daylight: Mapping[str, Any] | None = None,
    source_refs: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a bounded, provider-neutral Architecture dashboard projection."""

    route_value = dict(route or {})
    checkpoint_values = [dict(item) for item in checkpoints or []]
    segment_values = [dict(item) for item in segments or []]
    retreat_values = [dict(item) for item in retreat_routes or []]
    reference_value = dict(reference_pace_energy_analysis or {})
    passage_timing_value = (
        dict(reference_value.get("checkpoint_passage_timing"))
        if isinstance(reference_value.get("checkpoint_passage_timing"), Mapping)
        else {}
    )
    normalized_value = dict(normalized_route_architecture or {})
    mission_graph_value = dict(compiled_mission_graph or {})
    candidate_graph_value = dict(candidate_mission_graph or {})
    topology_graph_value = mission_graph_value or candidate_graph_value
    source_ref_values = {str(key): str(value) for key, value in (source_refs or {}).items()}
    crowd_axis = (
        dict(reference_value.get("crowd_axis"))
        if isinstance(reference_value.get("crowd_axis"), Mapping)
        else {}
    )
    golden_route_elevation_profile = _golden_route_elevation_profile_projection(
        reference_value.get("golden_route_elevation_profile")
    )

    raw_bins = [
        dict(item)
        for item in reference_value.get("route_bins", [])
        if isinstance(item, Mapping)
    ]
    source_vectors = _demand_vectors(
        raw_bins,
        source_provider=str(
            reference_value.get("source_provider")
            or "historical_gpx_reference_corpus"
        ),
        source_path=str(
            reference_value.get("source_path")
            or source_ref_values.get("reference_pace_energy_analysis")
            or "outputs/reference_pace_energy_analysis.json"
        ),
        source_sha256=str(reference_value.get("sha256") or ""),
        crowd_axis=crowd_axis,
    )
    source_route_distance_m = (
        _number(crowd_axis.get("source_route_distance_m"))
        or _number(route_value.get("distance_m"))
        or max(
            (
                _number(item.get("source_end_distance_m"))
                or _number(item.get("end_distance_m"))
                or 0.0
                for item in source_vectors
            ),
            default=0.0,
        )
    )
    route_axis_transform = _golden_route_axis_transform(
        source_route_distance_m=source_route_distance_m,
        golden_route_elevation_profile=golden_route_elevation_profile,
    )
    vectors = _normalize_vectors_to_golden_axis(
        source_vectors,
        route_axis_transform=route_axis_transform,
    )
    route_distance_m = (
        _number(route_axis_transform.get("golden_distance_m"))
        or _route_distance(route_value, vectors, crowd_axis=crowd_axis)
    )
    crowd_analysis_origin_m = 0.0
    route_axis_basis = (
        "golden_gpx_distance"
        if route_axis_transform.get("status") in {"aligned", "progress_normalized"}
        else "golden_route_scope"
    )
    architecture_available = bool(normalized_value)
    mission_graph_available = bool(mission_graph_value)
    candidate_graph_available = bool(candidate_graph_value)
    missing_artifacts = []
    if not architecture_available:
        missing_artifacts.append("normalized_route_architecture")
    if not mission_graph_available:
        missing_artifacts.append(
            "reviewed_compiled_mission_graph"
            if candidate_graph_available
            else "compiled_mission_graph"
        )
    status = (
        "ready"
        if vectors and architecture_available and mission_graph_available
        else "partial"
        if vectors or checkpoint_values or segment_values
        else "unavailable"
    )
    route_type_analysis = _route_type_analysis(
        normalized_value,
        topology_graph_value,
        checkpoint_values,
        route_distance_m,
    )
    route_type = route_type_analysis["route_type"]
    demand_shape = _demand_shape(vectors, route_distance_m)
    reversibility = (
        "graph_available"
        if mission_graph_available
        else "candidate_graph_unverified"
        if candidate_graph_available
        else "unverified"
    )
    reference_source_ref = (
        source_ref_values.get("reference_pace_energy_analysis")
        or "outputs/reference_pace_energy_analysis.json"
    )
    pressure_anchors = _pressure_anchors(
        vectors,
        source_ref=reference_source_ref,
    )
    checkpoint_passage_timing = _checkpoint_passage_timing_projection(
        passage_timing_value,
        route_distance_m=route_distance_m,
        distance_scale=_route_axis_scale(route_axis_transform),
        default_source_ref=reference_source_ref,
        demand_vectors=vectors,
    )
    evidence_quality = _evidence_quality(
        status=status,
        reference=reference_value,
        vectors=vectors,
        source_refs=source_ref_values,
        architecture_available=architecture_available,
        mission_graph_available=mission_graph_available,
        candidate_graph_available=candidate_graph_available,
        route_pressure=dict(route_pressure_profile or {}),
        boss_points=dict(boss_points or {}),
        topology_graph=topology_graph_value,
        checkpoint_count=len(checkpoint_values),
        segment_count=len(segment_values),
        retreat_count=len(retreat_values),
        missing_artifacts=missing_artifacts,
    )

    payload: dict[str, Any] = {
        "artifact_kind": "route_architecture_intelligence_projection",
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "status": status,
        "source_provider": "pretrip_workspace_projection",
        "source_path": "project.json#route_architecture_intelligence",
        "source_refs": evidence_quality["source_refs"],
        "data_quality": {
            "band": status if status in {"partial", "unavailable"} else evidence_quality["band"],
            "guidance_eligible_bin_count": evidence_quality["counts"][
                "guidance_eligible_bin_count"
            ],
            "observed_bin_count": evidence_quality["counts"]["observed_bin_count"],
            "distinct_reference_track_count": evidence_quality["counts"][
                "distinct_reference_track_count"
            ],
            "missing_artifacts": list(missing_artifacts),
        },
        "architecture_summary": {
            "question": "Where does route pressure accumulate, and where do choices begin to disappear?",
            "route_name": str(route_value.get("route_name") or project_id),
            "route_type": route_type,
            "route_type_basis": route_type_analysis["route_type_basis"],
            "start_finish_gap_m": route_type_analysis["start_finish_gap_m"],
            "demand_shape": demand_shape,
            "reversibility": reversibility,
            "evidence_state": status,
            "route_distance_m": route_distance_m,
            "source_route_distance_m": round(source_route_distance_m, 3),
            "crowd_analysis_origin_m": round(crowd_analysis_origin_m, 3),
            "route_axis_basis": route_axis_basis,
            "route_axis_transform": route_axis_transform,
            "route_axis_requires_human_review": bool(
                False
            ),
            "leading_span_interpretability": str(
                "not_applicable"
            ),
            "headline": _headline(
                demand_shape=demand_shape,
                reversibility=reversibility,
                pressure_anchors=pressure_anchors,
            ),
        },
        "route_spine": {
            "distance_m": route_distance_m,
            "source_distance_m": round(source_route_distance_m, 3),
            "analysis_origin_m": round(crowd_analysis_origin_m, 3),
            "axis_basis": route_axis_basis,
            "axis_transform": route_axis_transform,
            "axis_requires_human_review": bool(
                False
            ),
            "nodes": _route_spine_nodes(
                checkpoint_values,
                route_distance_m,
                distance_origin_m=crowd_analysis_origin_m,
                distance_scale=_route_axis_scale(route_axis_transform),
                passage_nodes=checkpoint_passage_timing["nodes"],
                source_ref=(
                    source_ref_values.get("checkpoints")
                    or "candidates/checkpoints.json"
                ),
            ),
            "pressure_anchors": pressure_anchors,
            "source_checkpoint_count": len(checkpoint_values),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "crowd_axis": {
            **crowd_axis,
            "status": "golden_route_axis_retained",
            "route_axis_basis": route_axis_basis,
            "analysis_origin_m": 0.0,
            "analysis_distance_m": round(route_distance_m, 3),
            "source_analysis_distance_m": round(
                _number(crowd_axis.get("analysis_distance_m"))
                or source_route_distance_m,
                3,
            ),
            "axis_transform": route_axis_transform,
            "axis_rebased": False,
            "leading_span_m": 0.0,
            "leading_span_interpretability": "not_applicable",
            "requires_human_review": False,
            "crowd_support_role": "coverage_and_confidence_diagnostic_only",
            "source_path": reference_source_ref,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "golden_route_elevation_profile": {
            **golden_route_elevation_profile,
            "axis_alignment": route_axis_transform,
        },
        "segment_demand_vectors": vectors,
        "checkpoint_passage_timing": checkpoint_passage_timing,
        "checkpoint_graph": _checkpoint_graph(
            checkpoint_values,
            segment_values,
            normalized_value,
            mission_graph_value,
            candidate_graph_value,
            source_ref=(
                source_ref_values.get("segments") or "candidates/segments.json"
            ),
        ),
        "retreat_dependencies": _retreat_dependencies(
            retreat_values,
            source_ref=(
                source_ref_values.get("retreat_routes")
                or "candidates/retreat_routes.json"
            ),
        ),
        "alternatives": _alternatives(
            normalized_value,
            topology_graph_value,
            source_ref=(
                source_ref_values.get("route_architecture")
                or source_ref_values.get("compiled_mission_graph")
                or source_ref_values.get("compiled_mission_graph_candidate")
                or "normalized/architecture/route_architecture.json"
            ),
        ),
        "time_dependencies": _time_dependencies(
            eta,
            weather_daylight,
            mission_graph=topology_graph_value,
            mission_graph_role=(
                "reviewed"
                if mission_graph_available
                else "candidate"
                if candidate_graph_available
                else "missing"
            ),
        ),
        "evidence_quality": evidence_quality,
        "metric_definitions": {
            "terrain_demand": "Relative grade and gravitational/dissipation proxy; not metabolic power.",
            "slow_passage_impedance": "Within-route percentile of grade-adjusted historical viscosity.",
            "risk_passage_pressure": "Candidate route risk source value; not Scout runtime truth.",
            "endurance_exposure": "Relative continuous-moving duration and route progress.",
            "pace_variability": "Relative spread between historical conservative and fast envelopes.",
            "composite_pressure_index": "Candidate visualization index, not a difficulty grade or success probability.",
            "route_axis": "Golden-route start-to-finish scope; crowd coverage changes confidence, never the axis origin or extent.",
            "golden_route_elevation": "Coordinate-free golden GPX elevation profile on the shared Architecture distance axis.",
            "route_axis_transform": "Source metric distances are preserved, then normalized by route progress when the source axis differs from golden GPX distance.",
            "checkpoint_passage_duration": "Historical aggregate duration for a fixed 500 m route window centered on each CP/MCP; mode is rounded to 5-minute buckets.",
            "difficulty_cp_selection": "Route-progress nodes default to MCP; only guidance-eligible high-pressure cluster peaks at composite pressure >=55 are promoted to Architecture CP, capped at 10.",
        },
        "limitations": [
            "Reference GPX reflects uploader behavior and selection bias, not the current user's capacity.",
            "Positive gravitational power is a per-kilogram mechanical proxy, not measured human energy expenditure.",
            "Candidate topology can describe route structure, but reversibility and alternatives remain unverified without reviewed architecture and mission graph evidence.",
            "Architecture difficulty CP is a de-cluttered pretrip pressure anchor, not a Boss Point, route-safety verdict, or runtime command.",
            "Weather, physiologic state, darkness, and environment threats remain separate decision dimensions.",
            "Sparse crowd coverage lowers evidence quality for affected bins; it never rebases or truncates the golden-route scope.",
            "When source route-distance products disagree with golden GPX length, Architecture compares them by normalized route progress and preserves every original source distance.",
            "CP/MCP passage timing describes historical route demand and does not predict personal completion or runtime safety.",
        ],
        "privacy": {
            "raw_gpx_embedded": False,
            "raw_health_payload_embedded": False,
            "precise_activity_timestamps_embedded": False,
            "home_work_traces_embedded": False,
            "projection_contains_aggregate_route_metrics_only": True,
        },
        "boundary": {
            "candidate_only": True,
            "medical_diagnosis": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
            "outbound_send_allowed": False,
            "hardware_control_allowed": False,
        },
    }
    payload["sha256"] = _payload_sha256(payload)
    return payload


def _golden_route_elevation_profile_projection(value: Any) -> dict[str, Any]:
    profile = dict(value) if isinstance(value, Mapping) else {}
    samples = []
    for raw in profile.get("samples", []):
        if not isinstance(raw, Mapping):
            continue
        distance_m = _number(raw.get("route_distance_m"))
        elevation_m = _number(raw.get("elevation_m"))
        if distance_m is None or elevation_m is None:
            continue
        samples.append(
            {
                "route_distance_m": round(max(0.0, distance_m), 3),
                "route_progress_ratio": round(
                    _clamp(
                        _number(raw.get("route_progress_ratio")) or 0.0,
                        0.0,
                        1.0,
                    ),
                    6,
                ),
                "elevation_m": round(elevation_m, 2),
                "minimum_elevation_m": _rounded(
                    _number(raw.get("minimum_elevation_m"))
                ),
                "maximum_elevation_m": _rounded(
                    _number(raw.get("maximum_elevation_m"))
                ),
                "source_trackpoint_count": max(
                    0,
                    int(raw.get("source_trackpoint_count") or 0),
                ),
            }
        )
    samples.sort(key=lambda item: item["route_distance_m"])

    data_quality = (
        dict(profile.get("data_quality"))
        if isinstance(profile.get("data_quality"), Mapping)
        else {}
    )
    status = (
        "available"
        if profile.get("status") == "available" and samples
        else str(profile.get("status") or "missing")
    )
    return {
        "artifact_kind": str(
            profile.get("artifact_kind")
            or "pretrip_golden_route_elevation_profile"
        ),
        "schema_version": str(
            profile.get("schema_version")
            or "golden_route_elevation_profile.v0"
        ),
        "status": status,
        "source_provider": str(
            profile.get("source_provider") or "workspace_golden_gpx"
        ),
        "source_path": (
            str(profile.get("source_path"))
            if profile.get("source_path")
            else None
        ),
        "source_kind": str(profile.get("source_kind") or "unknown"),
        "sha256": str(profile.get("sha256") or ""),
        "distance_m": _rounded(_number(profile.get("distance_m"))),
        "minimum_elevation_m": _rounded(
            _number(profile.get("minimum_elevation_m"))
        ),
        "maximum_elevation_m": _rounded(
            _number(profile.get("maximum_elevation_m"))
        ),
        "source_trackpoint_count": max(
            0,
            int(profile.get("source_trackpoint_count") or 0),
        ),
        "elevation_trackpoint_count": max(
            0,
            int(profile.get("elevation_trackpoint_count") or 0),
        ),
        "sample_count": len(samples),
        "samples": samples,
        "data_quality": {
            "status": str(data_quality.get("status") or "unavailable"),
            "elevation_coverage": _rounded(
                _number(data_quality.get("elevation_coverage"))
            ),
            "track_segment_count": max(
                0,
                int(data_quality.get("track_segment_count") or 0),
            ),
            "sampling_policy": str(
                data_quality.get("sampling_policy")
                or "distance_bucketed_coordinate_free_profile"
            ),
        },
        "privacy": {
            "coordinates_embedded": False,
            "precise_timestamps_embedded": False,
            "raw_gpx_embedded": False,
            "source_original_path_embedded": False,
        },
        "boundary": {
            "candidate_only": True,
            "medical_diagnosis": False,
            "runtime_safety_truth": False,
            "phase1_runtime_safety_truth": False,
            "safety_api_called": False,
        },
    }


def _golden_route_axis_transform(
    *,
    source_route_distance_m: float,
    golden_route_elevation_profile: Mapping[str, Any],
) -> dict[str, Any]:
    source_distance_m = max(0.0, float(source_route_distance_m))
    golden_distance_m = _number(
        golden_route_elevation_profile.get("distance_m")
    )
    profile_available = (
        golden_route_elevation_profile.get("status") == "available"
        and golden_distance_m is not None
        and golden_distance_m > 0.0
    )
    if not profile_available:
        return {
            "status": "unavailable",
            "source_distance_m": round(source_distance_m, 3),
            "golden_distance_m": None,
            "source_to_golden_scale": 1.0,
            "source_distances_preserved": True,
        }

    safe_golden_distance_m = float(golden_distance_m)
    if source_distance_m <= 0.0:
        return {
            "status": "golden_only",
            "source_distance_m": 0.0,
            "golden_distance_m": round(safe_golden_distance_m, 3),
            "source_to_golden_scale": 1.0,
            "source_distances_preserved": True,
        }

    scale = safe_golden_distance_m / source_distance_m
    relative_gap = abs(safe_golden_distance_m - source_distance_m) / max(
        safe_golden_distance_m,
        source_distance_m,
    )
    return {
        "status": "aligned" if relative_gap <= 0.02 else "progress_normalized",
        "source_distance_m": round(source_distance_m, 3),
        "golden_distance_m": round(safe_golden_distance_m, 3),
        "source_to_golden_scale": round(scale, 6),
        "source_distances_preserved": True,
    }


def _normalize_vectors_to_golden_axis(
    vectors: Sequence[Mapping[str, Any]],
    *,
    route_axis_transform: Mapping[str, Any],
) -> list[dict[str, Any]]:
    scale = _route_axis_scale(route_axis_transform)
    golden_distance_m = _number(route_axis_transform.get("golden_distance_m"))
    normalized = []
    for raw in vectors:
        source_start_m = (
            _number(raw.get("source_start_distance_m"))
            if raw.get("source_start_distance_m") is not None
            else _number(raw.get("start_distance_m"))
        ) or 0.0
        source_end_m = (
            _number(raw.get("source_end_distance_m"))
            if raw.get("source_end_distance_m") is not None
            else _number(raw.get("end_distance_m"))
        ) or source_start_m
        start_m = max(0.0, source_start_m * scale)
        end_m = max(start_m, source_end_m * scale)
        midpoint_m = (start_m + end_m) / 2.0
        normalized.append(
            {
                **dict(raw),
                "start_distance_m": round(start_m, 3),
                "end_distance_m": round(end_m, 3),
                "source_start_distance_m": round(source_start_m, 3),
                "source_end_distance_m": round(source_end_m, 3),
                "distance_label": _distance_range_label(start_m, end_m),
                "route_progress": (
                    round(
                        _clamp(midpoint_m / golden_distance_m, 0.0, 1.0),
                        6,
                    )
                    if golden_distance_m
                    else None
                ),
                "axis_transform_status": str(
                    route_axis_transform.get("status") or "unavailable"
                ),
            }
        )
    return normalized


def _route_axis_scale(route_axis_transform: Mapping[str, Any]) -> float:
    source_distance_m = _number(route_axis_transform.get("source_distance_m"))
    golden_distance_m = _number(route_axis_transform.get("golden_distance_m"))
    if (
        source_distance_m is not None
        and source_distance_m > 0.0
        and golden_distance_m is not None
        and golden_distance_m > 0.0
    ):
        return golden_distance_m / source_distance_m
    return _number(route_axis_transform.get("source_to_golden_scale")) or 1.0


def _demand_vectors(
    raw_bins: Sequence[Mapping[str, Any]],
    *,
    source_provider: str,
    source_path: str,
    source_sha256: str,
    crowd_axis: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    viscosity_values = [_number(item.get("grade_adjusted_viscosity_index")) for item in raw_bins]
    duration_values = [_number(item.get("continuous_moving_minutes_p50")) for item in raw_bins]
    viscosity_population = [value for value in viscosity_values if value is not None]
    duration_population = [value for value in duration_values if value is not None]
    max_end_distance = max(
        (
            _number(item.get("source_end_distance_m"))
            if item.get("source_end_distance_m") is not None
            else _number(item.get("end_distance_m"))
        )
        or 0.0
        for item in raw_bins
    ) if raw_bins else 0.0

    vectors: list[dict[str, Any]] = []
    for index, item in enumerate(raw_bins):
        source_start_m = (
            _number(item.get("source_start_distance_m"))
            if item.get("source_start_distance_m") is not None
            else _number(item.get("start_distance_m"))
        ) or 0.0
        source_end_m = (
            _number(item.get("source_end_distance_m"))
            if item.get("source_end_distance_m") is not None
            else _number(item.get("end_distance_m"))
        ) or source_start_m
        start_m = source_start_m
        end_m = source_end_m
        grade = _number(item.get("signed_grade_ratio_p50")) or 0.0
        risk = _clamp(_number(item.get("risk_score_p50")) or 0.0, 0.0, 100.0)
        viscosity = _number(item.get("grade_adjusted_viscosity_index"))
        duration = _number(item.get("continuous_moving_minutes_p50"))
        positive_power = _number(item.get("positive_gravity_power_w_per_kg_p50")) or 0.0
        descent_power = _number(item.get("descent_dissipation_power_w_per_kg_p50")) or 0.0
        terrain_demand = _clamp(
            max(
                abs(grade) / 0.45 * 100.0,
                positive_power / 0.50 * 100.0,
                descent_power / 0.50 * 100.0,
            ),
            0.0,
            100.0,
        )
        slow_passage = _percentile_rank(viscosity, viscosity_population)
        duration_rank = _percentile_rank(duration, duration_population)
        progress = ((start_m + end_m) / 2.0 / max_end_distance) if max_end_distance else 0.0
        endurance_exposure = _clamp(duration_rank * 0.7 + progress * 100.0 * 0.3, 0.0, 100.0)
        speeds = item.get("reference_speed_mps") if isinstance(item.get("reference_speed_mps"), Mapping) else {}
        p25_mps = _number(speeds.get("p25_conservative"))
        p50_mps = _number(speeds.get("p50"))
        p75_mps = _number(speeds.get("p75_fast_envelope"))
        pace_variability = _pace_variability(p25_mps, p50_mps, p75_mps)
        composite = _clamp(
            terrain_demand * 0.30
            + slow_passage * 0.30
            + risk * 0.25
            + endurance_exposure * 0.10
            + pace_variability * 0.05,
            0.0,
            100.0,
        )
        quality = str(item.get("data_quality") or "unknown")
        vector = {
            "route_bin_id": str(item.get("route_bin_id") or f"route_architecture.bin.{index:04d}"),
            "route_bin_index": int(item.get("route_bin_index", index)),
            "start_distance_m": round(start_m, 3),
            "end_distance_m": round(end_m, 3),
            "source_start_distance_m": round(source_start_m, 3),
            "source_end_distance_m": round(source_end_m, 3),
            "distance_label": _distance_range_label(start_m, end_m),
            "grade_band": str(item.get("grade_band") or "unknown"),
            "signed_grade_ratio_p50": round(grade, 4),
            "reference_speed_kmh": {
                "p25_conservative": _kmh(p25_mps),
                "p50": _kmh(p50_mps),
                "p75_fast_envelope": _kmh(p75_mps),
            },
            "reference_pace_seconds_per_100m": _numeric_mapping(
                item.get("reference_pace_seconds_per_100m"),
                ("p50", "p75_conservative"),
            ),
            "risk_score_p50": round(risk, 3),
            "grade_adjusted_viscosity_index": _rounded(viscosity),
            "continuous_moving_minutes_p50": _rounded(duration),
            "positive_gravity_power_w_per_kg_p50": round(positive_power, 4),
            "descent_dissipation_power_w_per_kg_p50": round(descent_power, 4),
            "traversal_count": int(item.get("traversal_count") or 0),
            "distinct_track_count": int(item.get("distinct_track_count") or 0),
            "data_quality": quality,
            "guidance_eligible": bool(item.get("guidance_eligible")),
            "association_flags": [str(flag) for flag in item.get("association_flags", [])],
            "historical_mobility_demand_vector": {
                "terrain_demand": round(terrain_demand, 2),
                "slow_passage_impedance": round(slow_passage, 2),
                "risk_passage_pressure": round(risk, 2),
                "stop_go_burden": None,
                "pace_variability": round(pace_variability, 2),
                "endurance_exposure": round(endurance_exposure, 2),
                "evidence_quality": round(_quality_score(quality, int(item.get("distinct_track_count") or 0)), 2),
                "composite_pressure_index": round(composite, 2),
            },
            "why_demanding": _demand_reasons(
                grade=grade,
                risk=risk,
                slow_passage=slow_passage,
                duration_rank=duration_rank,
                quality=quality,
            ),
            "source_path": source_path,
            "source_provider": source_provider,
            "source_sha256": source_sha256,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        vectors.append(
            _with_candidate_metadata(
                vector,
                source_ref=source_path,
                confidence=_quality_confidence(quality),
                stale_risk="medium",
                review_state="proposed",
                method="pretrip_route_architecture_intelligence.mobility_vector",
                summary=(
                    "Deterministic aggregate historical mobility-demand vector; "
                    "candidate-only planning evidence, not runtime safety truth."
                ),
            )
        )
    return vectors


def _route_spine_nodes(
    checkpoints: Sequence[Mapping[str, Any]],
    route_distance_m: float,
    *,
    distance_origin_m: float = 0.0,
    distance_scale: float = 1.0,
    passage_nodes: Sequence[Mapping[str, Any]] = (),
    source_ref: str,
) -> list[dict[str, Any]]:
    nodes = []
    passage_by_id = {
        str(item.get("node_id")): item
        for item in passage_nodes
        if item.get("node_id")
    }
    for index, item in enumerate(checkpoints):
        distance_m = _checkpoint_distance(item)
        if distance_m is None:
            continue
        node_id = str(item.get("candidate_id") or item.get("checkpoint_id") or f"cp.{index + 1}")
        checkpoint_type = str(item.get("checkpoint_type") or "checkpoint")
        passage_node = passage_by_id.get(node_id, {})
        is_route_anchor = checkpoint_type in {"start", "finish"}
        node_kind = str(
            passage_node.get("node_kind")
            or ("route_anchor" if is_route_anchor else "mcp")
        )
        selection_role = str(
            passage_node.get("selection_role")
            or ("route_anchor" if is_route_anchor else "route_micro_checkpoint")
        )
        display_priority = str(
            passage_node.get("display_priority")
            or ("primary" if is_route_anchor else "context")
        )
        source_distance_m = distance_m
        analysis_distance_m = (
            source_distance_m - distance_origin_m
        ) * distance_scale
        if analysis_distance_m < 0:
            continue
        node = {
                "node_id": node_id,
                "label": str(item.get("label") or node_id),
                "node_type": checkpoint_type,
                "node_kind": node_kind,
                "source_node_kind": str(
                    passage_node.get("source_node_kind") or "cp"
                ),
                "selection_role": selection_role,
                "display_priority": display_priority,
                "difficulty": (
                    dict(passage_node.get("difficulty"))
                    if isinstance(passage_node.get("difficulty"), Mapping)
                    else None
                ),
                "route_distance_m": round(analysis_distance_m, 3),
                "source_route_distance_m": round(source_distance_m, 3),
                "route_progress": round(analysis_distance_m / route_distance_m, 5) if route_distance_m else 0.0,
                "review_state": str(item.get("review_state") or "proposed"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        nodes.append(
            _with_candidate_metadata(
                node,
                source_ref=source_ref,
                confidence=str(item.get("confidence") or "medium"),
                stale_risk=str(item.get("stale_risk") or "medium"),
                review_state=str(item.get("review_state") or "proposed"),
                method="pretrip_route_architecture_intelligence.route_spine",
                summary=(
                    "Checkpoint projected onto the route architecture spine; "
                    "candidate-only planning evidence, not runtime safety truth."
                ),
            )
        )
    nodes.sort(key=lambda item: (item["route_distance_m"], item["node_id"]))
    featured = [
        item
        for item in nodes
        if item["display_priority"] in {"primary", "secondary"}
    ]
    context = [
        item
        for item in nodes
        if item["display_priority"] not in {"primary", "secondary"}
    ]
    sampled_context = _sample_evenly(
        context,
        max(0, MAX_SPINE_NODES - len(featured)),
    )
    selected_ids = {
        str(item["node_id"])
        for item in [*featured, *sampled_context]
    }
    return [
        item
        for item in nodes
        if str(item["node_id"]) in selected_ids
    ][:MAX_SPINE_NODES]


def _difficulty_cp_anchors(
    demand_vectors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    candidates = []
    for item in demand_vectors:
        vector = (
            item.get("historical_mobility_demand_vector")
            if isinstance(
                item.get("historical_mobility_demand_vector"),
                Mapping,
            )
            else {}
        )
        score = _number(vector.get("composite_pressure_index"))
        start_distance_m = _number(item.get("start_distance_m"))
        end_distance_m = _number(item.get("end_distance_m"))
        if (
            score is None
            or score < DIFFICULTY_CP_MIN_COMPOSITE_PRESSURE
            or not bool(item.get("guidance_eligible"))
            or start_distance_m is None
            or end_distance_m is None
        ):
            continue
        candidates.append(
            {
                "route_bin_id": str(item.get("route_bin_id") or ""),
                "start_distance_m": float(start_distance_m),
                "end_distance_m": float(end_distance_m),
                "route_distance_m": (
                    float(start_distance_m) + float(end_distance_m)
                )
                / 2.0,
                "composite_pressure_index": round(float(score), 2),
                "why_demanding": [
                    str(reason)
                    for reason in item.get("why_demanding", [])
                    if reason
                ],
                "data_quality": str(
                    item.get("data_quality") or "unknown"
                ),
            }
        )

    clusters: list[list[dict[str, Any]]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item["start_distance_m"],
            item["end_distance_m"],
            item["route_bin_id"],
        ),
    ):
        if (
            clusters
            and candidate["start_distance_m"]
            <= max(item["end_distance_m"] for item in clusters[-1])
            + DIFFICULTY_CP_CLUSTER_GAP_M
        ):
            clusters[-1] = [*clusters[-1], candidate]
        else:
            clusters.append([candidate])

    peaks = []
    for cluster in clusters:
        peak = max(
            cluster,
            key=lambda item: (
                item["composite_pressure_index"],
                item["route_distance_m"],
            ),
        )
        peaks.append(
            {
                **peak,
                "cluster_start_distance_m": round(
                    min(item["start_distance_m"] for item in cluster),
                    3,
                ),
                "cluster_end_distance_m": round(
                    max(item["end_distance_m"] for item in cluster),
                    3,
                ),
                "cluster_bin_count": len(cluster),
            }
        )

    selected = sorted(
        peaks,
        key=lambda item: (
            item["composite_pressure_index"],
            item["cluster_bin_count"],
            -item["route_distance_m"],
        ),
        reverse=True,
    )[:DIFFICULTY_CP_MAX_COUNT]
    return sorted(
        selected,
        key=lambda item: (
            item["route_distance_m"],
            item["route_bin_id"],
        ),
    )


def _difficulty_cp_detail(
    anchor: Mapping[str, Any],
    *,
    matched_node_offset_m: float | None,
) -> dict[str, Any]:
    score = float(anchor["composite_pressure_index"])
    return {
        "composite_pressure_index": round(score, 2),
        "pressure_band": "very_high" if score >= 78.0 else "high",
        "route_bin_id": str(anchor["route_bin_id"]),
        "cluster_start_distance_m": round(
            float(anchor["cluster_start_distance_m"]),
            3,
        ),
        "cluster_end_distance_m": round(
            float(anchor["cluster_end_distance_m"]),
            3,
        ),
        "cluster_bin_count": int(anchor["cluster_bin_count"]),
        "why_demanding": list(anchor.get("why_demanding") or []),
        "matched_node_offset_m": _rounded(matched_node_offset_m),
    }


def _synthetic_difficulty_cp(
    anchor: Mapping[str, Any],
    *,
    route_distance_m: float,
) -> dict[str, Any]:
    distance_m = _clamp(
        float(anchor["route_distance_m"]),
        0.0,
        route_distance_m,
    )
    safe_bin_id = re.sub(
        r"[^a-zA-Z0-9_.-]+",
        "-",
        str(anchor["route_bin_id"]),
    ).strip("-")
    return {
        "node_id": f"difficulty_cp.{safe_bin_id or 'pressure_peak'}",
        "source_node_kind": "pressure_anchor",
        "node_kind": "cp",
        "selection_role": "difficulty_cp",
        "display_priority": "primary",
        "label": f"Difficulty CP {distance_m / 1000.0:.2f}K",
        "named_places": [],
        "checkpoint_type": "difficulty_pressure_peak",
        "source_route_distance_m": None,
        "route_distance_m": round(distance_m, 3),
        "route_progress": round(
            distance_m / route_distance_m if route_distance_m else 0.0,
            5,
        ),
        "passage_window": {
            "start_distance_m": None,
            "end_distance_m": None,
            "distance_m": None,
            "semantics": "pressure_peak_without_source_passage_window",
        },
        "source_passage_window": {
            "start_distance_m": None,
            "end_distance_m": None,
            "distance_m": None,
        },
        "duration_minutes": {
            "min": None,
            "max": None,
            "average": None,
            "mode_5min": None,
            "mode_5min_tied_buckets": [],
        },
        "sample_count": 0,
        "distinct_track_count": 0,
        "direction_counts": {},
        "coverage_ratio": {},
        "data_quality": str(anchor.get("data_quality") or "unknown"),
        "difficulty": _difficulty_cp_detail(
            anchor,
            matched_node_offset_m=None,
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _promote_difficulty_cp_nodes(
    nodes: Sequence[Mapping[str, Any]],
    *,
    anchors: Sequence[Mapping[str, Any]],
    route_distance_m: float,
) -> list[dict[str, Any]]:
    nodes_by_id = {
        str(item["node_id"]): dict(item)
        for item in nodes
    }
    assigned_ids: set[str] = set()
    synthetic_nodes = []
    for anchor in anchors:
        candidates = [
            item
            for item in nodes_by_id.values()
            if item["selection_role"] == "route_micro_checkpoint"
            and str(item["node_id"]) not in assigned_ids
        ]
        nearest = min(
            candidates,
            key=lambda item: (
                abs(
                    float(item["route_distance_m"])
                    - float(anchor["route_distance_m"])
                ),
                str(item["node_id"]),
            ),
            default=None,
        )
        offset_m = (
            abs(
                float(nearest["route_distance_m"])
                - float(anchor["route_distance_m"])
            )
            if nearest
            else None
        )
        if nearest is None or (
            offset_m is not None
            and offset_m > DIFFICULTY_CP_MAX_MATCH_DISTANCE_M
        ):
            synthetic_nodes.append(
                _synthetic_difficulty_cp(
                    anchor,
                    route_distance_m=route_distance_m,
                )
            )
            continue
        node_id = str(nearest["node_id"])
        assigned_ids.add(node_id)
        nodes_by_id = {
            **nodes_by_id,
            node_id: {
                **nearest,
                "node_kind": "cp",
                "selection_role": "difficulty_cp",
                "display_priority": "primary",
                "difficulty": _difficulty_cp_detail(
                    anchor,
                    matched_node_offset_m=offset_m,
                ),
            },
        }

    return sorted(
        [*nodes_by_id.values(), *synthetic_nodes],
        key=lambda item: (
            float(item["route_distance_m"]),
            0 if item["node_kind"] == "cp" else 1,
            str(item["node_id"]),
        ),
    )


def _checkpoint_passage_timing_projection(
    value: Mapping[str, Any],
    *,
    route_distance_m: float,
    distance_scale: float = 1.0,
    default_source_ref: str,
    demand_vectors: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    nodes = []
    for raw in value.get("nodes", []):
        if not isinstance(raw, Mapping):
            continue
        distance_m = _number(raw.get("route_distance_m"))
        if distance_m is None:
            continue
        duration = (
            dict(raw.get("duration_minutes"))
            if isinstance(raw.get("duration_minutes"), Mapping)
            else {}
        )
        window = (
            dict(raw.get("passage_window"))
            if isinstance(raw.get("passage_window"), Mapping)
            else {}
        )
        tied_modes = [
            int(item)
            for item in duration.get("mode_5min_tied_buckets", [])
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
        analysis_distance_m = distance_m * distance_scale
        source_window = {
            "start_distance_m": _rounded(
                _number(window.get("start_distance_m"))
            ),
            "end_distance_m": _rounded(
                _number(window.get("end_distance_m"))
            ),
            "distance_m": _rounded(_number(window.get("distance_m"))),
        }
        source_node_kind = (
            "mcp" if str(raw.get("node_kind")) == "mcp" else "cp"
        )
        checkpoint_type = str(
            raw.get("checkpoint_type") or "route_progress"
        )
        is_route_anchor = checkpoint_type in {"start", "finish"}
        if is_route_anchor:
            node_kind = "route_anchor"
            selection_role = "route_anchor"
            display_priority = "primary"
        elif source_node_kind == "mcp":
            node_kind = "mcp"
            selection_role = "authored_mcp"
            display_priority = "secondary"
        else:
            node_kind = "mcp"
            selection_role = "route_micro_checkpoint"
            display_priority = "context"
        node = {
                "node_id": str(raw.get("node_id") or f"passage.{len(nodes) + 1}"),
                "source_node_kind": source_node_kind,
                "node_kind": node_kind,
                "selection_role": selection_role,
                "display_priority": display_priority,
                "label": str(raw.get("label") or raw.get("node_id") or "MCP"),
                "named_places": [
                    str(item)
                    for item in raw.get("named_places", [])
                    if isinstance(item, str) and item
                ],
                "checkpoint_type": checkpoint_type,
                "source_route_distance_m": round(distance_m, 3),
                "route_distance_m": round(
                    _clamp(analysis_distance_m, 0.0, route_distance_m),
                    3,
                ),
                "route_progress": round(
                    _clamp(
                        analysis_distance_m / route_distance_m,
                        0.0,
                        1.0,
                    )
                    if route_distance_m
                    else 0.0,
                    5,
                ),
                "passage_window": {
                    "start_distance_m": _rounded(
                        _number(window.get("start_distance_m"))
                        * distance_scale
                        if _number(window.get("start_distance_m")) is not None
                        else None
                    ),
                    "end_distance_m": _rounded(
                        _number(window.get("end_distance_m"))
                        * distance_scale
                        if _number(window.get("end_distance_m")) is not None
                        else None
                    ),
                    "distance_m": _rounded(
                        _number(window.get("distance_m"))
                        * distance_scale
                        if _number(window.get("distance_m")) is not None
                        else None
                    ),
                    "semantics": str(
                        window.get("semantics")
                        or "fixed_500m_route_window_centered_on_cp_or_mcp"
                    ),
                },
                "source_passage_window": source_window,
                "duration_minutes": {
                    "min": _rounded(_number(duration.get("min"))),
                    "max": _rounded(_number(duration.get("max"))),
                    "average": _rounded(_number(duration.get("average"))),
                    "mode_5min": (
                        int(duration["mode_5min"])
                        if isinstance(duration.get("mode_5min"), (int, float))
                        and not isinstance(duration.get("mode_5min"), bool)
                        else None
                    ),
                    "mode_5min_tied_buckets": tied_modes,
                },
                "sample_count": int(raw.get("sample_count") or 0),
                "distinct_track_count": int(raw.get("distinct_track_count") or 0),
                "direction_counts": (
                    dict(raw.get("direction_counts"))
                    if isinstance(raw.get("direction_counts"), Mapping)
                    else {}
                ),
                "coverage_ratio": (
                    dict(raw.get("coverage_ratio"))
                    if isinstance(raw.get("coverage_ratio"), Mapping)
                    else {}
                ),
                "data_quality": str(raw.get("data_quality") or "unavailable"),
                "difficulty": None,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        nodes.append(
            _with_candidate_metadata(
                node,
                source_ref=default_source_ref,
                confidence=_quality_confidence(str(node["data_quality"])),
                stale_risk="medium",
                review_state="candidate",
                method=(
                    "pretrip_route_architecture_intelligence."
                    "checkpoint_passage_timing"
                ),
                summary=(
                    "Historical checkpoint passage timing projection; candidate-only "
                    "planning evidence, not runtime safety truth."
                ),
            )
        )
    nodes = _promote_difficulty_cp_nodes(
        nodes,
        anchors=_difficulty_cp_anchors(demand_vectors),
        route_distance_m=route_distance_m,
    )
    timed_node_count = sum(item["sample_count"] > 0 for item in nodes)
    difficulty_cp_count = sum(
        item["node_kind"] == "cp"
        and item["selection_role"] == "difficulty_cp"
        for item in nodes
    )
    mcp_count = sum(item["node_kind"] == "mcp" for item in nodes)
    context_mcp_count = sum(
        item["node_kind"] == "mcp"
        and item["display_priority"] == "context"
        for item in nodes
    )
    card_node_count = sum(
        item["node_kind"] in {"cp", "mcp"}
        and item["display_priority"] in {"primary", "secondary"}
        for item in nodes
    )
    data_quality = (
        dict(value.get("data_quality"))
        if isinstance(value.get("data_quality"), Mapping)
        else {}
    )
    privacy = (
        dict(value.get("privacy"))
        if isinstance(value.get("privacy"), Mapping)
        else {}
    )
    boundary = (
        dict(value.get("boundary"))
        if isinstance(value.get("boundary"), Mapping)
        else {}
    )
    return {
        "status": "available" if nodes else "unavailable",
        "source_provider": str(
            value.get("source_provider") or "historical_gpx_reference_corpus"
        ),
        "source_path": str(value.get("source_path") or default_source_ref),
        "sha256": str(value.get("sha256") or ""),
        "policy": (
            dict(value.get("policy"))
            if isinstance(value.get("policy"), Mapping)
            else {}
        ),
        "selection_policy": {
            "default_node_kind": "mcp",
            "difficulty_cp_minimum_composite_pressure": (
                DIFFICULTY_CP_MIN_COMPOSITE_PRESSURE
            ),
            "difficulty_cp_requires_guidance_eligible": True,
            "difficulty_cp_cluster_gap_m": DIFFICULTY_CP_CLUSTER_GAP_M,
            "maximum_difficulty_cp_count": DIFFICULTY_CP_MAX_COUNT,
            "card_display_priorities": ["primary", "secondary"],
        },
        "data_quality": {
            **data_quality,
            "node_count": len(nodes),
            "timed_node_count": timed_node_count,
        },
        "node_count": len(nodes),
        "timed_node_count": timed_node_count,
        "difficulty_cp_count": difficulty_cp_count,
        "mcp_count": mcp_count,
        "card_node_count": card_node_count,
        "context_mcp_count": context_mcp_count,
        "nodes": nodes,
        "privacy": {
            **privacy,
            "raw_gpx_embedded": False,
            "precise_timestamps_embedded": False,
        },
        "boundary": {
            **boundary,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _checkpoint_graph(
    checkpoints: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    normalized_architecture: Mapping[str, Any],
    mission_graph: Mapping[str, Any],
    candidate_mission_graph: Mapping[str, Any],
    *,
    source_ref: str,
) -> dict[str, Any]:
    edges = []
    for index, item in enumerate(segments[:MAX_GRAPH_EDGES]):
        edge_id = str(item.get("candidate_id") or item.get("segment_id") or f"seg.{index + 1}")
        edge = {
                "edge_id": edge_id,
                "from_node_id": item.get("from_candidate_id") or item.get("from_checkpoint_id"),
                "to_node_id": item.get("to_candidate_id") or item.get("to_checkpoint_id"),
                "distance_m": _rounded(_number(item.get("distance_m"))),
                "review_state": str(item.get("review_state") or "proposed"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        edges.append(
            _with_candidate_metadata(
                edge,
                source_ref=source_ref,
                confidence=str(item.get("confidence") or "medium"),
                stale_risk=str(item.get("stale_risk") or "medium"),
                review_state=str(item.get("review_state") or "proposed"),
                method="pretrip_route_architecture_intelligence.checkpoint_edge",
                summary=(
                    "Segment projected as a checkpoint-graph edge; candidate-only "
                    "planning evidence, not runtime safety truth."
                ),
            )
        )
    selected_graph = mission_graph or candidate_mission_graph
    graph_nodes = _graph_collection(selected_graph, "nodes", "checkpoints")
    graph_edges = _graph_collection(selected_graph, "edges", "segments")
    graph_role = (
        "reviewed"
        if mission_graph
        else "candidate"
        if candidate_mission_graph
        else "projected_segments"
    )
    return {
        "status": (
            "compiled_reviewed"
            if mission_graph
            else "compiled_candidate"
            if candidate_mission_graph
            else "candidate_projection"
        ),
        "checkpoint_count": len(checkpoints),
        "segment_count": len(segments),
        "projected_edges": edges,
        "projected_edges_truncated": len(segments) > len(edges),
        "mission_graph_node_count": len(graph_nodes),
        "mission_graph_edge_count": len(graph_edges),
        "compiled_node_count": len(graph_nodes) if mission_graph else 0,
        "compiled_edge_count": len(graph_edges) if mission_graph else 0,
        "graph_source_role": graph_role,
        "normalized_architecture_available": bool(normalized_architecture),
        "compiled_mission_graph_available": bool(mission_graph),
        "candidate_mission_graph_available": bool(candidate_mission_graph),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _retreat_dependencies(
    retreat_routes: Sequence[Mapping[str, Any]], *, source_ref: str
) -> list[dict[str, Any]]:
    dependencies = []
    for index, item in enumerate(retreat_routes):
        candidate_id = str(item.get("candidate_id") or item.get("retreat_route_id") or f"retreat.{index + 1}")
        dependency = {
                "candidate_id": candidate_id,
                "label": str(item.get("label") or candidate_id),
                "retreat_type": str(item.get("retreat_type") or "unknown"),
                "trigger_checkpoint_candidate_id": item.get("trigger_checkpoint_candidate_id"),
                "entry_checkpoint_candidate_id": item.get("entry_checkpoint_candidate_id"),
                "distance_m": _rounded(_number(item.get("distance_m"))),
                "review_state": str(item.get("review_state") or "needs_review"),
                "field_verified": bool(item.get("field_verified", False)),
                "dependency": "reviewed route graph" if item.get("field_verified") else "candidate route assumption",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        dependencies.append(
            _with_candidate_metadata(
                dependency,
                source_ref=source_ref,
                confidence=str(item.get("confidence") or "medium"),
                stale_risk=str(item.get("stale_risk") or "medium"),
                review_state=str(item.get("review_state") or "needs_review"),
                method="pretrip_route_architecture_intelligence.retreat_dependency",
                summary=(
                    "Recorded retreat-route dependency; candidate-only and not a "
                    "field-verified evacuation route or runtime safety truth."
                ),
            )
        )
    return dependencies


def _alternatives(
    normalized_architecture: Mapping[str, Any],
    mission_graph: Mapping[str, Any],
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    candidates = normalized_architecture.get("alternatives")
    if not isinstance(candidates, list):
        candidates = mission_graph.get("alternatives")
    if not isinstance(candidates, list):
        return []
    alternatives = []
    for index, item in enumerate(candidates):
        if not isinstance(item, Mapping):
            continue
        alternative = {
            "alternative_id": str(
                item.get("alternative_id")
                or item.get("id")
                or f"alternative.{index + 1}"
            ),
            "label": str(
                item.get("label") or item.get("name") or f"Alternative {index + 1}"
            ),
            "review_state": str(item.get("review_state") or "proposed"),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        alternatives.append(
            _with_candidate_metadata(
                alternative,
                source_ref=source_ref,
                confidence=str(item.get("confidence") or "medium"),
                stale_risk=str(item.get("stale_risk") or "medium"),
                review_state=str(item.get("review_state") or "proposed"),
                method="pretrip_route_architecture_intelligence.alternative",
                summary=(
                    "Recorded route alternative; candidate-only planning evidence, "
                    "not runtime safety truth."
                ),
            )
        )
    return alternatives


def _time_dependencies(
    eta: Mapping[str, Any] | None,
    weather_daylight: Mapping[str, Any] | None,
    *,
    mission_graph: Mapping[str, Any],
    mission_graph_role: str,
) -> dict[str, Any]:
    eta_value = dict(eta or {})
    assumption = eta_value.get("assumption") if isinstance(eta_value.get("assumption"), Mapping) else {}
    daylight_value = dict(weather_daylight or {})
    graph_segments = _graph_collection(mission_graph, "edges", "segments")
    graph_durations = []
    for segment in graph_segments:
        requirement = segment.get("requirement")
        if not isinstance(requirement, Mapping):
            continue
        duration = _number(requirement.get("expected_duration_seconds"))
        if duration is not None and duration >= 0:
            graph_durations.append(duration)
    graph_duration_seconds = round(sum(graph_durations), 3)
    graph_duration_hours = round(graph_duration_seconds / 3_600.0, 3)
    return {
        "planned_start_clock": _clock_label(assumption.get("planned_start_time")),
        "target_arrival_clock": _clock_label(assumption.get("target_eta")),
        "turn_back_clock": _clock_label(assumption.get("turn_back_checkpoint_eta")),
        "eta_estimate_count": len(eta_value.get("estimates", [])) if isinstance(eta_value.get("estimates"), list) else 0,
        "daylight_evidence_status": str(daylight_value.get("status") or "unavailable"),
        "mission_graph_role": mission_graph_role,
        "mission_graph_segment_count": len(graph_segments),
        "mission_graph_duration_seconds": graph_duration_seconds,
        "mission_graph_duration_hours": graph_duration_hours,
        "candidate_graph_segment_count": (
            len(graph_segments) if mission_graph_role == "candidate" else 0
        ),
        "candidate_graph_duration_seconds": (
            graph_duration_seconds if mission_graph_role == "candidate" else 0.0
        ),
        "candidate_graph_duration_hours": (
            graph_duration_hours if mission_graph_role == "candidate" else 0.0
        ),
        "time_evidence_available": bool(
            eta_value.get("estimates") or graph_durations
        ),
        "precision": "minute_clock_only",
        "precise_timestamps_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _evidence_quality(
    *,
    status: str,
    reference: Mapping[str, Any],
    vectors: Sequence[Mapping[str, Any]],
    source_refs: Mapping[str, str],
    architecture_available: bool,
    mission_graph_available: bool,
    candidate_graph_available: bool,
    route_pressure: Mapping[str, Any],
    boss_points: Mapping[str, Any],
    topology_graph: Mapping[str, Any],
    checkpoint_count: int,
    segment_count: int,
    retreat_count: int,
    missing_artifacts: Sequence[str],
) -> dict[str, Any]:
    reference_counts = reference.get("counts") if isinstance(reference.get("counts"), Mapping) else {}
    distinct_tracks = max((int(item.get("distinct_track_count") or 0) for item in vectors), default=0)
    guidance_count = sum(bool(item.get("guidance_eligible")) for item in vectors)
    route_pressure_counts = (
        route_pressure.get("counts")
        if isinstance(route_pressure.get("counts"), Mapping)
        else {}
    )
    boss_point_items = _graph_collection(boss_points, "boss_points", "candidates")
    topology_nodes = _graph_collection(topology_graph, "nodes", "checkpoints")
    topology_edges = _graph_collection(topology_graph, "edges", "segments")
    sources = [
        ("reference_pace_energy_analysis", bool(reference), "historical mobility demand"),
        ("route_pressure_profile", bool(route_pressure), "route pressure peaks"),
        ("boss_points", bool(boss_points), "named pressure anchors"),
        ("route_architecture", architecture_available, "reviewed route topology"),
        (
            "compiled_mission_graph_candidate",
            candidate_graph_available,
            "candidate dependency graph",
        ),
        ("compiled_mission_graph", mission_graph_available, "reviewed dependency graph"),
        ("retreat_routes", retreat_count > 0, "candidate retreat routes"),
    ]
    source_items = [
        {
            "source_key": key,
            "source_path": source_refs.get(key) or _default_source_path(key),
            "status": "available" if available else "missing",
            "role": role,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for key, available, role in sources
    ]
    if status == "ready" and guidance_count >= max(1, len(vectors) // 2):
        band = "high"
    elif vectors:
        band = "partial"
    else:
        band = "unavailable"
    return {
        "band": band,
        "counts": {
            "reference_track_count": int(reference_counts.get("reference_track_count") or 0),
            "scope_reference_track_count": int(
                reference_counts.get("scope_reference_track_count") or 0
            ),
            "crowd_track_count": int(
                reference_counts.get("crowd_track_count")
                or reference_counts.get("reference_track_count")
                or 0
            ),
            "usable_reference_track_count": int(reference_counts.get("usable_candidate_track_count") or 0),
            "usable_crowd_track_count": int(
                reference_counts.get("usable_crowd_track_count")
                or reference_counts.get("usable_candidate_track_count")
                or 0
            ),
            "distinct_reference_track_count": distinct_tracks,
            "observed_bin_count": len(vectors),
            "guidance_eligible_bin_count": guidance_count,
            "checkpoint_count": checkpoint_count,
            "segment_count": segment_count,
            "retreat_candidate_count": retreat_count,
            "route_pressure_sample_count": int(
                route_pressure_counts.get("sample_count") or 0
            ),
            "route_pressure_peak_count": int(
                route_pressure_counts.get("peak_count") or 0
            ),
            "boss_point_count": len(boss_point_items),
            "mission_graph_node_count": len(topology_nodes),
            "mission_graph_edge_count": len(topology_edges),
        },
        "missing_artifacts": list(missing_artifacts),
        "source_refs": source_items,
        "selection_bias_warning": "Public reference GPX may overrepresent successful or above-average trips.",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _pressure_anchors(
    vectors: Sequence[Mapping[str, Any]], *, source_ref: str
) -> list[dict[str, Any]]:
    ranked = sorted(
        vectors,
        key=lambda item: (
            _number(
                (item.get("historical_mobility_demand_vector") or {}).get(
                    "composite_pressure_index"
                )
            )
            or 0.0,
            _number(item.get("start_distance_m")) or 0.0,
        ),
        reverse=True,
    )[:MAX_PRESSURE_ANCHORS]
    anchors = []
    for item in ranked:
        anchor = {
            "route_bin_id": str(item.get("route_bin_id")),
            "distance_label": str(item.get("distance_label")),
            "start_distance_m": item.get("start_distance_m"),
            "end_distance_m": item.get("end_distance_m"),
            "composite_pressure_index": (item.get("historical_mobility_demand_vector") or {}).get(
                "composite_pressure_index"
            ),
            "guidance_eligible": bool(item.get("guidance_eligible")),
            "why_demanding": list(item.get("why_demanding") or []),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        anchors.append(
            _with_candidate_metadata(
                anchor,
                source_ref=source_ref,
                confidence=str(item.get("confidence") or "medium"),
                stale_risk=str(item.get("stale_risk") or "medium"),
                review_state="proposed",
                method="pretrip_route_architecture_intelligence.pressure_anchor",
                summary=(
                    "Ranked historical mobility-pressure anchor; candidate-only "
                    "planning evidence, not runtime safety truth."
                ),
            )
        )
    return anchors


def _route_type_analysis(
    normalized_architecture: Mapping[str, Any],
    mission_graph: Mapping[str, Any],
    checkpoints: Sequence[Mapping[str, Any]],
    route_distance_m: float,
) -> dict[str, Any]:
    summary = normalized_architecture.get("architecture_summary")
    if isinstance(summary, Mapping) and summary.get("route_type"):
        return {
            "route_type": str(summary["route_type"]),
            "route_type_basis": "normalized_route_architecture",
            "start_finish_gap_m": None,
        }
    value = normalized_architecture.get("route_type")
    if value:
        return {
            "route_type": str(value),
            "route_type_basis": "normalized_route_architecture",
            "start_finish_gap_m": None,
        }

    graph_checkpoints = _graph_collection(mission_graph, "nodes", "checkpoints")
    route_checkpoints = graph_checkpoints or [dict(item) for item in checkpoints]
    if route_checkpoints:
        start = next(
            (
                item
                for item in route_checkpoints
                if str(item.get("checkpoint_type") or item.get("node_type"))
                == "start"
            ),
            route_checkpoints[0],
        )
        finish = next(
            (
                item
                for item in reversed(route_checkpoints)
                if str(item.get("checkpoint_type") or item.get("node_type"))
                == "finish"
            ),
            route_checkpoints[-1],
        )
        gap_m = _coordinate_gap_m(start, finish)
        if gap_m is not None:
            closure_threshold_m = max(
                100.0,
                min(250.0, route_distance_m * 0.01),
            )
            return {
                "route_type": (
                    "closed_route_candidate"
                    if route_distance_m >= 1_000.0 and gap_m <= closure_threshold_m
                    else "point_to_point_candidate"
                ),
                "route_type_basis": "candidate_graph_start_finish_proximity",
                "start_finish_gap_m": round(gap_m, 3),
            }

    if _graph_collection(mission_graph, "edges", "segments"):
        return {
            "route_type": "linear_sequence_candidate",
            "route_type_basis": "candidate_graph_segment_sequence",
            "start_finish_gap_m": None,
        }
    return {
        "route_type": "unclassified",
        "route_type_basis": "insufficient_topology_evidence",
        "start_finish_gap_m": None,
    }


def _demand_shape(vectors: Sequence[Mapping[str, Any]], route_distance_m: float) -> str:
    if not vectors or route_distance_m <= 0:
        return "unknown"
    ranked = sorted(
        vectors,
        key=lambda item: _number(
            (item.get("historical_mobility_demand_vector") or {}).get(
                "composite_pressure_index"
            )
        )
        or 0.0,
        reverse=True,
    )
    top_count = max(1, math.ceil(len(ranked) * 0.20))
    progress_values = [
        ((_number(item.get("start_distance_m")) or 0.0) + (_number(item.get("end_distance_m")) or 0.0))
        / 2.0
        / route_distance_m
        for item in ranked[:top_count]
    ]
    center = sum(progress_values) / len(progress_values)
    spread = max(progress_values) - min(progress_values) if len(progress_values) > 1 else 0.0
    if spread > 0.55:
        return "distributed_pressure"
    if center < 0.35:
        return "front_loaded_pressure"
    if center > 0.65:
        return "late_route_pressure"
    return "mid_route_pressure"


def _headline(
    *, demand_shape: str, reversibility: str, pressure_anchors: Sequence[Mapping[str, Any]]
) -> str:
    shape_labels = {
        "front_loaded_pressure": "Historical mobility pressure is front-loaded",
        "mid_route_pressure": "Historical mobility pressure concentrates near the middle",
        "late_route_pressure": "Historical mobility pressure accumulates late",
        "distributed_pressure": "Historical mobility pressure is distributed across the route",
        "unknown": "Historical mobility pressure is not yet available",
    }
    pressure = shape_labels.get(demand_shape, "Historical mobility pressure is partially observed")
    if pressure_anchors:
        pressure = f"{pressure}; strongest observed bin {pressure_anchors[0]['distance_label']}"
    topology = {
        "graph_available": "reviewed mission graph available for reversibility review",
        "candidate_graph_unverified": (
            "candidate mission graph is connected, but reversibility remains unverified pending review"
        ),
    }.get(
        reversibility,
        "reversibility remains unverified until the mission graph is compiled",
    )
    return f"{pressure}; {topology}."


def _coordinate_gap_m(
    start: Mapping[str, Any], finish: Mapping[str, Any]
) -> float | None:
    start_lat = _number(start.get("lat"))
    start_lon = _number(start.get("lon"))
    finish_lat = _number(finish.get("lat"))
    finish_lon = _number(finish.get("lon"))
    if None in {start_lat, start_lon, finish_lat, finish_lon}:
        return None
    lat1 = math.radians(start_lat)
    lat2 = math.radians(finish_lat)
    delta_lat = math.radians(finish_lat - start_lat)
    delta_lon = math.radians(finish_lon - start_lon)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 6_371_000.0 * 2.0 * math.atan2(
        math.sqrt(haversine), math.sqrt(max(0.0, 1.0 - haversine))
    )


def _route_distance(
    route: Mapping[str, Any],
    vectors: Sequence[Mapping[str, Any]],
    *,
    crowd_axis: Mapping[str, Any] | None = None,
) -> float:
    del crowd_axis
    route_distance = _number(route.get("distance_m")) or 0.0
    if route_distance > 0.0:
        return round(route_distance, 3)
    observed_distance = max(
        (_number(item.get("end_distance_m")) or 0.0 for item in vectors),
        default=0.0,
    )
    return round(observed_distance, 3)


def _checkpoint_distance(item: Mapping[str, Any]) -> float | None:
    direct = _number(item.get("route_distance_m"))
    if direct is not None:
        return direct
    projection = item.get("overpass_projection")
    if isinstance(projection, Mapping):
        return _number(projection.get("route_distance_m"))
    return None


def _demand_reasons(
    *, grade: float, risk: float, slow_passage: float, duration_rank: float, quality: str
) -> list[str]:
    reasons = []
    if grade >= 0.20:
        reasons.append("sustained_uphill_grade")
    elif grade <= -0.20:
        reasons.append("steep_descent_dissipation")
    if risk >= 65.0:
        reasons.append("elevated_route_risk_source_value")
    if slow_passage >= 75.0:
        reasons.append("historical_slow_passage_impedance")
    if duration_rank >= 75.0:
        reasons.append("late_continuous_movement_exposure")
    if quality in {"low", "unknown"}:
        reasons.append("low_evidence_quality")
    return reasons or ["no_single_dominant_factor"]


def _quality_score(quality: str, track_count: int) -> float:
    base = {"high": 85.0, "medium": 62.0, "low": 35.0}.get(quality, 20.0)
    return _clamp(base + min(max(track_count - 1, 0), 5) * 3.0, 0.0, 100.0)


def _quality_confidence(quality: str) -> str:
    return {
        "high": "high",
        "medium": "medium",
        "low": "low",
    }.get(quality, "low")


def _with_candidate_metadata(
    payload: Mapping[str, Any],
    *,
    source_ref: str,
    confidence: str,
    stale_risk: str,
    review_state: str,
    method: str,
    summary: str,
) -> dict[str, Any]:
    base = dict(payload)
    deterministic_sha256 = _payload_sha256(base)
    return {
        **base,
        "source_refs": [source_ref],
        "source_attribution": [
            {
                "source_kind": "pretrip_workspace_projection",
                "source_ref": source_ref,
                "method": method,
                "confidence": confidence,
                "stale_risk": stale_risk,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "confidence": confidence,
        "stale_risk": stale_risk,
        "review_state": review_state,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "model_output_sha256": deterministic_sha256,
        "model_output_summary": summary,
        "extractor_version": "pretrip_route_architecture_intelligence.v0",
        "pydantic_ai_prompt_version": (
            "not_applicable_deterministic_route_architecture_projection"
        ),
    }


def _pace_variability(
    p25_mps: float | None, p50_mps: float | None, p75_mps: float | None
) -> float:
    if p25_mps is None or p50_mps in {None, 0.0} or p75_mps is None:
        return 0.0
    return _clamp((p75_mps - p25_mps) / p50_mps * 100.0, 0.0, 100.0)


def _percentile_rank(value: float | None, population: Sequence[float]) -> float:
    if value is None or not population:
        return 0.0
    if len(population) == 1:
        return 50.0
    lower = sum(candidate < value for candidate in population)
    equal = sum(candidate == value for candidate in population)
    rank = (lower + max(0, equal - 1) * 0.5) / (len(population) - 1)
    return _clamp(rank * 100.0, 0.0, 100.0)


def _sample_evenly(items: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(items) <= limit:
        return [dict(item) for item in items]
    indexes = {
        round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)
    }
    return [dict(items[index]) for index in sorted(indexes)]


def _numeric_mapping(value: Any, keys: Iterable[str]) -> dict[str, float | None]:
    mapping = value if isinstance(value, Mapping) else {}
    return {key: _rounded(_number(mapping.get(key))) for key in keys}


def _graph_collection(
    payload: Mapping[str, Any], primary_key: str, fallback_key: str
) -> list[dict[str, Any]]:
    items = payload.get(primary_key)
    if not isinstance(items, list):
        items = payload.get(fallback_key)
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _clock_label(value: Any) -> str | None:
    if value in (None, ""):
        return None
    match = re.search(r"(?:T|\s|^)([01]\d|2[0-3]):([0-5]\d)", str(value))
    return f"{match.group(1)}:{match.group(2)}" if match else None


def _default_source_path(key: str) -> str:
    return {
        "reference_pace_energy_analysis": "outputs/reference_pace_energy_analysis.json",
        "route_pressure_profile": "outputs/route_pressure_profile.json",
        "boss_points": "outputs/boss_points.json",
        "route_architecture": "normalized/architecture/route_architecture.json",
        "compiled_mission_graph_candidate": (
            "outputs/compiled_mission_graph.candidate.json"
        ),
        "compiled_mission_graph": "outputs/compiled_mission_graph.json",
        "retreat_routes": "candidates/retreat_routes.json",
    }.get(key, "project.json")


def _distance_range_label(start_m: float, end_m: float) -> str:
    return f"{start_m / 1000.0:.2f}–{end_m / 1000.0:.2f}K"


def _kmh(value: float | None) -> float | None:
    return round(value * 3.6, 3) if value is not None else None


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
