from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACE_COEFFICIENT_BUILDER_ARTIFACT_KIND = "scout_pace_coefficient_builder"
PACE_COEFFICIENT_BUILDER_VERSION = "pace_coefficient_builder.v1"

DEFAULT_CAPABILITY_TIMELINE_REF = "outputs/capability_timeline.json"
DEFAULT_ROUTE_TIME_COMPARISON_REF = "outputs/capability_route_time_comparison.json"
DEFAULT_ROUTE_WEATHER_PACKAGE_REF = "outputs/route_weather_package.json"
DEFAULT_WEATHER_DECISION_CANDIDATES_REF = "candidates/weather_decision_candidates.json"

TECHNICAL_TERRAIN_BANDS = {"watch", "strained", "severe"}


def build_scout_pace_coefficients_from_project(
    project_root: Path | str,
    *,
    capability_timeline_path: Path | str | None = None,
    route_time_comparison_path: Path | str | None = None,
    route_weather_package_path: Path | str | None = None,
    weather_decision_candidates_path: Path | str | None = None,
    member_id: str | None = None,
    display_label: str | None = None,
    pack_weight_kg: float | int | str | None = None,
    load_impact_ratio: float | int | str | None = None,
    weather_impact_ratio: float | int | str | None = None,
    self_report_gap_ratio: float | int | str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a reviewable Scout Pace Coefficient from post-analysis evidence.

    This builder is deliberately pretrip/post-analysis evidence only. It turns
    completed-trip capability artifacts into one member profile that the
    deterministic Pace Guardian can assess; it does not diagnose health, use
    live safety APIs, or promote model output into runtime safety truth.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = generated_at or _utc_now()

    timeline_ref = _project_ref(
        project,
        "capability_timeline_ref",
        DEFAULT_CAPABILITY_TIMELINE_REF,
    )
    route_time_ref = _project_ref(
        project,
        "capability_route_time_comparison_ref",
        DEFAULT_ROUTE_TIME_COMPARISON_REF,
    )
    route_weather_ref = _project_ref(
        project,
        "route_weather_package_ref",
        DEFAULT_ROUTE_WEATHER_PACKAGE_REF,
    )
    weather_candidates_ref = _project_ref(
        project,
        "weather_decision_candidates_ref",
        DEFAULT_WEATHER_DECISION_CANDIDATES_REF,
    )

    timeline_path = _resolve_workspace_path(
        root,
        capability_timeline_path,
        default_ref=timeline_ref,
    )
    route_time_path = _resolve_workspace_path(
        root,
        route_time_comparison_path,
        default_ref=route_time_ref,
    )
    route_weather_path = _resolve_workspace_path(
        root,
        route_weather_package_path,
        default_ref=route_weather_ref,
    )
    weather_candidates_path = _resolve_workspace_path(
        root,
        weather_decision_candidates_path,
        default_ref=weather_candidates_ref,
    )

    timeline = _load_json_object(timeline_path)
    route_time = _load_json_object(route_time_path)
    route_weather = _load_json_object(route_weather_path)
    weather_candidates = _load_json_object(weather_candidates_path)

    edges = _timeline_edges(timeline)
    summary = timeline.get("summary") if isinstance(timeline.get("summary"), dict) else {}

    flat_speed = _derive_flat_speed(edges, summary)
    ascent_speed = _derive_ascent_speed(edges, summary)
    descent_speed = _derive_descent_speed(edges)
    technical_slowdown = _derive_technical_slowdown(edges)
    rest_frequency = _derive_rest_frequency(timeline, edges, summary)
    late_trip_decay = _derive_late_trip_decay(edges)
    resolved_load = _derive_load_impact(
        pack_weight_kg=pack_weight_kg,
        load_impact_ratio=load_impact_ratio,
    )
    resolved_weather = _derive_weather_impact(
        weather_impact_ratio=weather_impact_ratio,
        route_weather=route_weather,
        weather_candidates=weather_candidates,
    )
    experience = _derive_experience_credibility(
        route_time=route_time,
        timeline=timeline,
        self_report_gap_ratio=self_report_gap_ratio,
    )

    coefficient = {
        "flat_speed_mps": flat_speed["value"],
        "uphill_speed_mps": _derive_uphill_horizontal_speed(edges),
        "downhill_speed_mps": descent_speed["value"],
        "technical_terrain_slowdown_ratio": technical_slowdown["value"],
        "rest_frequency_minutes": rest_frequency["value"],
        "late_trip_speed_decay_ratio": late_trip_decay["value"],
        "pack_weight_kg": _float_or_none(pack_weight_kg),
        "load_slowdown_ratio": resolved_load["value"],
        "weather_slowdown_ratio": resolved_weather["value"],
        "experience_credibility": experience["value"],
        "self_report_gap_ratio": _float_or_none(self_report_gap_ratio),
    }
    public_coefficients = {
        "member_id": member_id or "completed_trip_subject",
        "label": display_label or "Completed trip subject",
        "role": "completed_trip_subject",
        "flat_speed_mps": coefficient["flat_speed_mps"],
        "ascent_speed_vertical_m_per_hour": ascent_speed["value"],
        "descent_speed_mps": coefficient["downhill_speed_mps"],
        "technical_terrain_slowdown_ratio": coefficient[
            "technical_terrain_slowdown_ratio"
        ],
        "rest_frequency_minutes": coefficient["rest_frequency_minutes"],
        "late_trip_decay_ratio": coefficient["late_trip_speed_decay_ratio"],
        "load_impact_ratio": coefficient["load_slowdown_ratio"],
        "weather_impact_ratio": coefficient["weather_slowdown_ratio"],
        "experience_credibility": coefficient["experience_credibility"],
        "self_report_gap_ratio": coefficient["self_report_gap_ratio"],
        "pack_weight_kg": coefficient["pack_weight_kg"],
        "raw_health_payload_embedded": False,
        "medical_diagnosis": False,
    }
    team_member = {
        **public_coefficients,
        "display_label": public_coefficients["label"],
        "pace_mps": coefficient["flat_speed_mps"],
        "moving_speed_mps": coefficient["flat_speed_mps"],
        "uphill_speed_mps": coefficient["uphill_speed_mps"],
        "downhill_speed_mps": coefficient["downhill_speed_mps"],
        "late_trip_speed_decay_ratio": coefficient["late_trip_speed_decay_ratio"],
        "load_slowdown_ratio": coefficient["load_slowdown_ratio"],
        "weather_slowdown_ratio": coefficient["weather_slowdown_ratio"],
        "review_state": "candidate_derived",
        "first_time_similar_route": None,
        "scout_pace_coefficient": coefficient,
    }

    indicator_provenance = {
        "flat_speed_mps": flat_speed,
        "ascent_speed_vertical_m_per_hour": ascent_speed,
        "descent_speed_mps": descent_speed,
        "technical_terrain_slowdown_ratio": technical_slowdown,
        "rest_frequency_minutes": rest_frequency,
        "late_trip_decay_ratio": late_trip_decay,
        "load_impact_ratio": resolved_load,
        "weather_impact_ratio": resolved_weather,
        "experience_credibility": experience,
    }
    source_report = _source_report(
        timeline_path=timeline_path,
        route_time_path=route_time_path,
        route_weather_path=route_weather_path,
        weather_candidates_path=weather_candidates_path,
        timeline=timeline,
        route_time=route_time,
        route_weather=route_weather,
        weather_candidates=weather_candidates,
    )
    missing = [
        indicator_id
        for indicator_id, provenance in indicator_provenance.items()
        if provenance.get("value") is None
    ]

    return {
        "artifact_kind": PACE_COEFFICIENT_BUILDER_ARTIFACT_KIND,
        "schema_version": PACE_COEFFICIENT_BUILDER_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "status": "completed" if edges else "missing_capability_timeline",
        "team_members": [team_member] if edges else [],
        "member_coefficients": [public_coefficients] if edges else [],
        "indicator_provenance": indicator_provenance,
        "counts": {
            "edge_count": len(edges),
            "member_count": 1 if edges else 0,
            "available_indicator_count": len(indicator_provenance) - len(missing),
            "missing_indicator_count": len(missing),
        },
        "missing_indicators": missing,
        "source_report": source_report,
        "limitations": _limitations(missing),
        "boundary": _closed_boundary(),
    }


def _derive_flat_speed(
    edges: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    flat_edges = [
        edge
        for edge in edges
        if _edge_speed(edge) is not None
        and _terrain_band(edge) == "normal"
        and _vertical_ratio(edge) <= 0.05
    ]
    speed = _weighted_speed(flat_edges)
    method = "normal_low_relief_edges"
    confidence = "medium"
    limitations: list[str] = []
    if speed is None:
        distance = _float_or_none(summary.get("distance_m"))
        moving = _float_or_none(summary.get("moving_time_s"))
        speed = _safe_ratio(distance, moving)
        method = "overall_moving_speed_proxy"
        confidence = "low"
        limitations.append("flat-specific segments unavailable; used overall moving speed proxy")
    return _provenance(
        value=speed,
        source="post_analysis_capability_timeline",
        method=method,
        confidence=confidence if speed is not None else "missing",
        limitations=limitations,
    )


def _derive_ascent_speed(
    edges: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    ascent_edges = [
        edge
        for edge in edges
        if _float_or_none(edge.get("ascent_m")) is not None
        and _float_or_none(edge.get("moving_time_s")) is not None
        and _float_or_none(edge.get("ascent_m")) > _float_or_none(edge.get("descent_m") or 0)
    ]
    ascent_m = sum(_float_or_none(edge.get("ascent_m")) or 0.0 for edge in ascent_edges)
    moving_s = sum(_float_or_none(edge.get("moving_time_s")) or 0.0 for edge in ascent_edges)
    value = _safe_ratio(ascent_m, moving_s / 3600.0) if moving_s else None
    method = "ascent_dominant_edges"
    confidence = "medium"
    if value is None:
        value = _float_or_none(summary.get("ascent_m_per_hour_moving"))
        method = "summary_ascent_m_per_hour_moving"
        confidence = "low" if value is not None else "missing"
    return _provenance(
        value=value,
        source="post_analysis_capability_timeline",
        method=method,
        confidence=confidence,
    )


def _derive_uphill_horizontal_speed(edges: list[dict[str, Any]]) -> float | None:
    ascent_edges = [
        edge
        for edge in edges
        if (_float_or_none(edge.get("ascent_m")) or 0.0)
        > (_float_or_none(edge.get("descent_m")) or 0.0)
    ]
    return _weighted_speed(ascent_edges)


def _derive_descent_speed(edges: list[dict[str, Any]]) -> dict[str, Any]:
    descent_edges = [
        edge
        for edge in edges
        if _edge_speed(edge) is not None
        and (_float_or_none(edge.get("descent_m")) or 0.0)
        > (_float_or_none(edge.get("ascent_m")) or 0.0)
    ]
    value = _weighted_speed(descent_edges)
    return _provenance(
        value=value,
        source="post_analysis_capability_timeline",
        method="descent_dominant_edges",
        confidence="medium" if value is not None else "missing",
    )


def _derive_technical_slowdown(edges: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_edges = [
        edge
        for edge in edges
        if _edge_speed(edge) is not None and _terrain_band(edge) == "normal"
    ]
    technical_edges = [
        edge
        for edge in edges
        if _edge_speed(edge) is not None and _is_technical_edge(edge)
    ]
    baseline = _median_speed(baseline_edges)
    technical = _median_speed(technical_edges)
    value = None
    if baseline and technical is not None:
        value = _clamp(1.0 - technical / baseline, 0.0, 0.8)
    return _provenance(
        value=value,
        source="post_analysis_capability_timeline.terrain_profile",
        method="technical_edge_speed_vs_normal_edge_speed",
        confidence="medium" if value is not None else "missing",
        limitations=[]
        if technical_edges
        else ["no technical terrain edge identified in capability timeline"],
    )


def _derive_rest_frequency(
    timeline: dict[str, Any],
    edges: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    rest_ids = set()
    for item in timeline.get("rest_intervals") or []:
        if isinstance(item, dict) and item.get("rest_id"):
            rest_ids.add(str(item.get("rest_id")))
        elif isinstance(item, str):
            rest_ids.add(item)
    for edge in edges:
        for rest_id in edge.get("rest_intervals") or []:
            rest_ids.add(str(rest_id))
    elapsed_s = _float_or_none(summary.get("elapsed_time_s"))
    moving_s = _float_or_none(summary.get("moving_time_s"))
    basis_s = elapsed_s or moving_s
    value = None
    if basis_s and rest_ids:
        value = basis_s / len(rest_ids) / 60.0
    return _provenance(
        value=value,
        source="post_analysis_capability_timeline.rest_intervals",
        method="elapsed_minutes_per_detected_rest_interval",
        confidence="medium" if value is not None else "missing",
        limitations=[] if rest_ids else ["rest interval ids unavailable"],
    )


def _derive_late_trip_decay(edges: list[dict[str, Any]]) -> dict[str, Any]:
    first, second = _split_edges_by_distance(edges)
    first_speed = _weighted_speed(first)
    second_speed = _weighted_speed(second)
    value = None
    if first_speed and second_speed is not None:
        value = _clamp(1.0 - second_speed / first_speed, 0.0, 0.8)
    return _provenance(
        value=value,
        source="post_analysis_capability_timeline",
        method="second_half_moving_speed_vs_first_half",
        confidence="medium" if value is not None else "missing",
    )


def _derive_load_impact(
    *,
    pack_weight_kg: float | int | str | None,
    load_impact_ratio: float | int | str | None,
) -> dict[str, Any]:
    explicit = _float_or_none(load_impact_ratio)
    if explicit is not None:
        return _provenance(
            value=_clamp(explicit, 0.0, 0.6),
            source="operator_hint",
            method="provided_load_impact_ratio",
            confidence="review_required",
        )
    pack_weight = _float_or_none(pack_weight_kg)
    value = None
    limitations = ["pack weight unavailable"]
    method = "missing_pack_weight"
    if pack_weight is not None:
        value = _clamp(max(0.0, pack_weight - 6.0) * 0.015, 0.0, 0.35)
        limitations = ["heuristic load estimate; calibrate with repeated completed trips"]
        method = "pack_weight_heuristic"
    return _provenance(
        value=value,
        source="operator_hint",
        method=method,
        confidence="low" if value is not None else "missing",
        limitations=limitations,
    )


def _derive_weather_impact(
    *,
    weather_impact_ratio: float | int | str | None,
    route_weather: dict[str, Any],
    weather_candidates: dict[str, Any],
) -> dict[str, Any]:
    explicit = _float_or_none(weather_impact_ratio)
    if explicit is not None:
        return _provenance(
            value=_clamp(explicit, 0.0, 0.6),
            source="operator_hint",
            method="provided_weather_impact_ratio",
            confidence="review_required",
        )
    payloads = [payload for payload in (route_weather, weather_candidates) if payload]
    if not payloads:
        return _provenance(
            value=None,
            source="weather_decision_evidence",
            method="missing_weather_evidence",
            confidence="missing",
            limitations=["weather evidence unavailable"],
        )
    joined = json.dumps(payloads, ensure_ascii=False).lower()
    score = 0.0
    if any(term in joined for term in ("rain", "雨", "wet", "泥", "降雨")):
        score += 0.12
    if any(term in joined for term in ("heat", "高溫", "暑", "炎熱")):
        score += 0.08
    if any(term in joined for term in ("cold", "低溫", "寒", "wind", "風")):
        score += 0.08
    if any(term in joined for term in ("delay", "change_plan", "cancel", "撤退", "延後")):
        score += 0.08
    value = _clamp(score, 0.0, 0.35) if score else None
    return _provenance(
        value=value,
        source="weather_decision_evidence",
        method="route_weather_keyword_slowdown_proxy",
        confidence="low" if value is not None else "missing",
        limitations=["keyword proxy only; use route-specific observed weather for calibration"],
    )


def _derive_experience_credibility(
    *,
    route_time: dict[str, Any],
    timeline: dict[str, Any],
    self_report_gap_ratio: float | int | str | None,
) -> dict[str, Any]:
    gap = _float_or_none(self_report_gap_ratio)
    if gap is not None:
        if gap >= 0.2:
            value = "low"
        elif gap <= 0.1:
            value = "reviewed"
        else:
            value = "medium"
        return _provenance(
            value=value,
            source="operator_hint",
            method="self_report_gap_ratio",
            confidence="review_required",
        )
    summary = route_time.get("summary") if isinstance(route_time.get("summary"), dict) else {}
    comparison_count = int(_float_or_none(summary.get("comparison_count")) or 0)
    if comparison_count > 0:
        slowest = _float_or_none(summary.get("slowest_relative_delta_min"))
        fastest = _float_or_none(summary.get("fastest_relative_delta_min"))
        worst_abs = max(abs(slowest or 0.0), abs(fastest or 0.0))
        value = "reviewed" if worst_abs <= 20 else "medium" if worst_abs <= 60 else "low"
        return _provenance(
            value=value,
            source="post_analysis_route_time_comparison",
            method="guide_time_delta_review",
            confidence="medium",
        )
    if timeline:
        return _provenance(
            value="unreviewed",
            source="post_analysis_capability_timeline",
            method="completed_track_without_route_time_or_self_report_comparison",
            confidence="low",
            limitations=["no guide-time or self-report comparison available"],
        )
    return _provenance(
        value=None,
        source="post_analysis_route_time_comparison",
        method="missing_experience_comparison",
        confidence="missing",
    )


def _timeline_edges(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    edges = timeline.get("edges")
    if not isinstance(edges, list):
        return []
    return [edge for edge in edges if isinstance(edge, dict)]


def _edge_speed(edge: dict[str, Any]) -> float | None:
    return _safe_ratio(
        _float_or_none(edge.get("distance_m")),
        _float_or_none(edge.get("moving_time_s")),
    )


def _weighted_speed(edges: list[dict[str, Any]]) -> float | None:
    distance = sum(_float_or_none(edge.get("distance_m")) or 0.0 for edge in edges)
    moving = sum(_float_or_none(edge.get("moving_time_s")) or 0.0 for edge in edges)
    return _safe_ratio(distance, moving)


def _median_speed(edges: list[dict[str, Any]]) -> float | None:
    speeds = [_edge_speed(edge) for edge in edges]
    speeds = [speed for speed in speeds if speed is not None]
    if not speeds:
        return None
    return float(statistics.median(speeds))


def _split_edges_by_distance(
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    total = sum(_float_or_none(edge.get("distance_m")) or 0.0 for edge in edges)
    if total <= 0:
        half = len(edges) // 2
        return edges[:half], edges[half:]
    first: list[dict[str, Any]] = []
    second: list[dict[str, Any]] = []
    cumulative = 0.0
    for edge in edges:
        distance = _float_or_none(edge.get("distance_m")) or 0.0
        target = first if cumulative < total / 2.0 else second
        target.append(edge)
        cumulative += distance
    return first, second


def _terrain_band(edge: dict[str, Any]) -> str:
    profile = edge.get("terrain_profile") if isinstance(edge.get("terrain_profile"), dict) else {}
    summary = profile.get("summary") if isinstance(profile.get("summary"), dict) else {}
    return str(summary.get("terrain_difficulty_band") or "unknown").lower()


def _is_technical_edge(edge: dict[str, Any]) -> bool:
    if _terrain_band(edge) in TECHNICAL_TERRAIN_BANDS:
        return True
    profile = edge.get("terrain_profile") if isinstance(edge.get("terrain_profile"), dict) else {}
    summary = profile.get("summary") if isinstance(profile.get("summary"), dict) else {}
    max_slope = _float_or_none(summary.get("max_slope_deg"))
    if max_slope is not None and max_slope >= 20:
        return True
    counts = summary.get("slope_band_counts")
    if isinstance(counts, dict):
        steep_keys = ("20_30", "30_40", "40_50", "50_plus")
        return any((int(counts.get(key) or 0) > 0) for key in steep_keys)
    return False


def _vertical_ratio(edge: dict[str, Any]) -> float:
    ascent = _float_or_none(edge.get("ascent_m")) or 0.0
    descent = _float_or_none(edge.get("descent_m")) or 0.0
    distance = _float_or_none(edge.get("distance_m")) or 0.0
    if distance <= 0:
        return 1.0
    return (ascent + descent) / distance


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _provenance(
    *,
    value: Any,
    source: str,
    method: str,
    confidence: str,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "value": _round_float(value),
        "source": source,
        "method": method,
        "confidence": confidence,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "limitations": limitations or [],
    }


def _source_report(
    *,
    timeline_path: Path,
    route_time_path: Path,
    route_weather_path: Path,
    weather_candidates_path: Path,
    timeline: dict[str, Any],
    route_time: dict[str, Any],
    route_weather: dict[str, Any],
    weather_candidates: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _one_source_report("capability_timeline", timeline_path, bool(timeline), required=True),
        _one_source_report(
            "route_time_comparison", route_time_path, bool(route_time), required=False
        ),
        _one_source_report(
            "route_weather_package", route_weather_path, bool(route_weather), required=False
        ),
        _one_source_report(
            "weather_decision_candidates",
            weather_candidates_path,
            bool(weather_candidates),
            required=False,
        ),
    ]


def _one_source_report(
    source_id: str,
    path: Path,
    loaded: bool,
    *,
    required: bool,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": "loaded" if loaded else "missing",
        "path": str(path),
        "required": required,
    }


def _limitations(missing: list[str]) -> list[str]:
    limitations = [
        "Pace coefficients are pretrip/post-analysis candidate evidence only.",
        "No raw health payload is embedded and no medical diagnosis is made.",
        "Team decisions must still use the slowest or most vulnerable member basis.",
    ]
    if missing:
        limitations.append("Missing indicators require manual review: " + ", ".join(missing))
    return limitations


def _resolve_workspace_path(
    root: Path,
    path: Path | str | None,
    *,
    default_ref: str,
) -> Path:
    value = Path(path) if path is not None else Path(default_ref)
    if value.is_absolute():
        return value
    return root / value


def _project_ref(project: dict[str, Any], key: str, default: str) -> str:
    value = project.get(key)
    return str(value) if value else default


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_float(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    return value


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _closed_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "external_api_calls_made": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "workspace_file_mutation_allowed": False,
        "raw_payloads_embedded": False,
        "raw_health_payload_embedded": False,
        "medical_diagnosis": False,
        "average_pace_used": False,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
