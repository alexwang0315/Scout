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
    normalized_value = dict(normalized_route_architecture or {})
    mission_graph_value = dict(compiled_mission_graph or {})
    source_ref_values = {str(key): str(value) for key, value in (source_refs or {}).items()}

    raw_bins = [
        dict(item)
        for item in reference_value.get("route_bins", [])
        if isinstance(item, Mapping)
    ]
    vectors = _demand_vectors(
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
    )
    route_distance_m = _route_distance(route_value, vectors)
    architecture_available = bool(normalized_value)
    mission_graph_available = bool(mission_graph_value)
    missing_artifacts = [
        name
        for name, available in (
            ("normalized_route_architecture", architecture_available),
            ("compiled_mission_graph", mission_graph_available),
        )
        if not available
    ]
    status = (
        "ready"
        if vectors and architecture_available and mission_graph_available
        else "partial"
        if vectors or checkpoint_values or segment_values
        else "unavailable"
    )
    route_type = _route_type(normalized_value)
    demand_shape = _demand_shape(vectors, route_distance_m)
    reversibility = "graph_available" if mission_graph_available else "unverified"
    reference_source_ref = (
        source_ref_values.get("reference_pace_energy_analysis")
        or "outputs/reference_pace_energy_analysis.json"
    )
    pressure_anchors = _pressure_anchors(
        vectors,
        source_ref=reference_source_ref,
    )
    evidence_quality = _evidence_quality(
        status=status,
        reference=reference_value,
        vectors=vectors,
        source_refs=source_ref_values,
        architecture_available=architecture_available,
        mission_graph_available=mission_graph_available,
        route_pressure_available=bool(route_pressure_profile),
        boss_points_available=bool(boss_points),
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
            "demand_shape": demand_shape,
            "reversibility": reversibility,
            "evidence_state": status,
            "route_distance_m": route_distance_m,
            "headline": _headline(
                demand_shape=demand_shape,
                reversibility=reversibility,
                pressure_anchors=pressure_anchors,
            ),
        },
        "route_spine": {
            "distance_m": route_distance_m,
            "nodes": _route_spine_nodes(
                checkpoint_values,
                route_distance_m,
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
        "segment_demand_vectors": vectors,
        "checkpoint_graph": _checkpoint_graph(
            checkpoint_values,
            segment_values,
            normalized_value,
            mission_graph_value,
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
            mission_graph_value,
            source_ref=(
                source_ref_values.get("route_architecture")
                or source_ref_values.get("compiled_mission_graph")
                or "normalized/architecture/route_architecture.json"
            ),
        ),
        "time_dependencies": _time_dependencies(eta, weather_daylight),
        "evidence_quality": evidence_quality,
        "metric_definitions": {
            "terrain_demand": "Relative grade and gravitational/dissipation proxy; not metabolic power.",
            "slow_passage_impedance": "Within-route percentile of grade-adjusted historical viscosity.",
            "risk_passage_pressure": "Candidate route risk source value; not Scout runtime truth.",
            "endurance_exposure": "Relative continuous-moving duration and route progress.",
            "pace_variability": "Relative spread between historical conservative and fast envelopes.",
            "composite_pressure_index": "Candidate visualization index, not a difficulty grade or success probability.",
        },
        "limitations": [
            "Reference GPX reflects uploader behavior and selection bias, not the current user's capacity.",
            "Positive gravitational power is a per-kilogram mechanical proxy, not measured human energy expenditure.",
            "Missing normalized architecture or mission graph leaves reversibility and alternatives unverified.",
            "Weather, physiologic state, darkness, and environment threats remain separate decision dimensions.",
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


def _demand_vectors(
    raw_bins: Sequence[Mapping[str, Any]],
    *,
    source_provider: str,
    source_path: str,
    source_sha256: str,
) -> list[dict[str, Any]]:
    viscosity_values = [_number(item.get("grade_adjusted_viscosity_index")) for item in raw_bins]
    duration_values = [_number(item.get("continuous_moving_minutes_p50")) for item in raw_bins]
    viscosity_population = [value for value in viscosity_values if value is not None]
    duration_population = [value for value in duration_values if value is not None]
    max_end_distance = max(
        (_number(item.get("end_distance_m")) or 0.0 for item in raw_bins),
        default=0.0,
    )

    vectors: list[dict[str, Any]] = []
    for index, item in enumerate(raw_bins):
        start_m = _number(item.get("start_distance_m")) or 0.0
        end_m = _number(item.get("end_distance_m")) or start_m
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
    source_ref: str,
) -> list[dict[str, Any]]:
    nodes = []
    for index, item in enumerate(checkpoints):
        distance_m = _checkpoint_distance(item)
        if distance_m is None:
            continue
        node_id = str(item.get("candidate_id") or item.get("checkpoint_id") or f"cp.{index + 1}")
        checkpoint_type = str(item.get("checkpoint_type") or "checkpoint")
        node = {
                "node_id": node_id,
                "label": str(item.get("label") or node_id),
                "node_type": checkpoint_type,
                "route_distance_m": round(distance_m, 3),
                "route_progress": round(distance_m / route_distance_m, 5) if route_distance_m else 0.0,
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
    return _sample_evenly(nodes, MAX_SPINE_NODES)


def _checkpoint_graph(
    checkpoints: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    normalized_architecture: Mapping[str, Any],
    mission_graph: Mapping[str, Any],
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
    graph_nodes = mission_graph.get("nodes") if isinstance(mission_graph.get("nodes"), list) else []
    graph_edges = mission_graph.get("edges") if isinstance(mission_graph.get("edges"), list) else []
    return {
        "status": "compiled" if mission_graph else "candidate_projection",
        "checkpoint_count": len(checkpoints),
        "segment_count": len(segments),
        "projected_edges": edges,
        "projected_edges_truncated": len(segments) > len(edges),
        "compiled_node_count": len(graph_nodes),
        "compiled_edge_count": len(graph_edges),
        "normalized_architecture_available": bool(normalized_architecture),
        "compiled_mission_graph_available": bool(mission_graph),
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
    eta: Mapping[str, Any] | None, weather_daylight: Mapping[str, Any] | None
) -> dict[str, Any]:
    eta_value = dict(eta or {})
    assumption = eta_value.get("assumption") if isinstance(eta_value.get("assumption"), Mapping) else {}
    daylight_value = dict(weather_daylight or {})
    return {
        "planned_start_clock": _clock_label(assumption.get("planned_start_time")),
        "target_arrival_clock": _clock_label(assumption.get("target_eta")),
        "turn_back_clock": _clock_label(assumption.get("turn_back_checkpoint_eta")),
        "eta_estimate_count": len(eta_value.get("estimates", [])) if isinstance(eta_value.get("estimates"), list) else 0,
        "daylight_evidence_status": str(daylight_value.get("status") or "unavailable"),
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
    route_pressure_available: bool,
    boss_points_available: bool,
    checkpoint_count: int,
    segment_count: int,
    retreat_count: int,
    missing_artifacts: Sequence[str],
) -> dict[str, Any]:
    reference_counts = reference.get("counts") if isinstance(reference.get("counts"), Mapping) else {}
    distinct_tracks = max((int(item.get("distinct_track_count") or 0) for item in vectors), default=0)
    guidance_count = sum(bool(item.get("guidance_eligible")) for item in vectors)
    sources = [
        ("reference_pace_energy_analysis", bool(reference), "historical mobility demand"),
        ("route_pressure_profile", route_pressure_available, "route pressure peaks"),
        ("boss_points", boss_points_available, "named pressure anchors"),
        ("route_architecture", architecture_available, "reviewed route topology"),
        ("compiled_mission_graph", mission_graph_available, "dependency graph"),
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
            "usable_reference_track_count": int(reference_counts.get("usable_candidate_track_count") or 0),
            "distinct_reference_track_count": distinct_tracks,
            "observed_bin_count": len(vectors),
            "guidance_eligible_bin_count": guidance_count,
            "checkpoint_count": checkpoint_count,
            "segment_count": segment_count,
            "retreat_candidate_count": retreat_count,
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


def _route_type(normalized_architecture: Mapping[str, Any]) -> str:
    summary = normalized_architecture.get("architecture_summary")
    if isinstance(summary, Mapping) and summary.get("route_type"):
        return str(summary["route_type"])
    value = normalized_architecture.get("route_type")
    return str(value) if value else "unclassified"


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
    topology = (
        "mission graph available for reversibility review"
        if reversibility == "graph_available"
        else "reversibility remains unverified until the mission graph is compiled"
    )
    return f"{pressure}; {topology}."


def _route_distance(
    route: Mapping[str, Any], vectors: Sequence[Mapping[str, Any]]
) -> float:
    route_distance = _number(route.get("distance_m")) or 0.0
    observed_distance = max(
        (_number(item.get("end_distance_m")) or 0.0 for item in vectors),
        default=0.0,
    )
    return round(max(route_distance, observed_distance), 3)


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
