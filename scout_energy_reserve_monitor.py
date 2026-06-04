from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scout_energy_models import ScoutEnergyBoundary, ScoutEnergyPrivacy
from scout_energy_reserve import ENERGY_BASELINE_FILENAME


ENERGY_RESERVE_MONITOR_KIND = "scout_energy_reserve_monitor"
ENERGY_RESERVE_MONITOR_VERSION = "energy_reserve_monitor.v1"


def build_energy_reserve_monitor_from_view(
    view: dict[str, Any],
    *,
    inventory_root: Path | None = None,
    surface: str = "admin",
) -> dict[str, Any]:
    baseline_path = (
        inventory_root / "outputs" / ENERGY_BASELINE_FILENAME
        if inventory_root is not None
        else None
    )
    baseline = _load_optional_json(baseline_path)
    inventory = _inventory_summary(inventory_root, baseline=baseline)
    capability = _capability_from_view(view)
    energy_projection = _energy_projection_from_view(view)
    feedback = _energy_feedback_from_view(view)

    return build_energy_reserve_monitor(
        baseline=baseline,
        baseline_source_path=str(baseline_path) if baseline_path is not None else "",
        inventory=inventory,
        energy_projection=energy_projection,
        post_analysis_energy_feedback=feedback,
        capability_timeline=capability,
        surface=surface,
    )


def build_energy_reserve_monitor(
    *,
    baseline: dict[str, Any] | None = None,
    baseline_source_path: str = "",
    inventory: dict[str, Any] | None = None,
    energy_projection: dict[str, Any] | None = None,
    post_analysis_energy_feedback: dict[str, Any] | None = None,
    capability_timeline: dict[str, Any] | None = None,
    surface: str = "admin",
) -> dict[str, Any]:
    health = _health_summary(
        baseline=baseline,
        baseline_source_path=baseline_source_path,
        inventory=inventory,
    )
    projection = _projection_summary(energy_projection)
    capability = _capability_summary(capability_timeline)
    feedback = _feedback_summary(post_analysis_energy_feedback)
    candidate = _candidate_change_summary(
        health=health,
        projection=projection,
        capability=capability,
        feedback=feedback,
    )
    status = _monitor_status(health, projection, capability, feedback)
    return {
        "artifact_kind": ENERGY_RESERVE_MONITOR_KIND,
        "artifact_version": ENERGY_RESERVE_MONITOR_VERSION,
        "surface": surface,
        "status": status,
        "health_data": health,
        "pretrip_projection": projection,
        "trip_capability": capability,
        "post_analysis_feedback": feedback,
        "candidate_change": candidate,
        "display": _display_summary(health, capability, candidate),
        "boundary": {
            **ScoutEnergyBoundary().model_dump(mode="json"),
            "workspace_mutation_allowed": False,
            "baseline_artifact_mutation_allowed": False,
            "pretrip_eta_autocalibration_allowed": False,
            "runtime_safety_truth": False,
        },
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "mutation": {
            "baseline_artifact_mutated": False,
            "workspace_file_written": False,
            "mission_graph_mutated": False,
            "runtime_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
        },
    }


def _health_summary(
    *,
    baseline: dict[str, Any] | None,
    baseline_source_path: str,
    inventory: dict[str, Any] | None,
) -> dict[str, Any]:
    reserve_trend = baseline.get("reserve_trend", {}) if isinstance(baseline, dict) else {}
    data_quality = baseline.get("data_quality", {}) if isinstance(baseline, dict) else {}
    inventory_count = int((inventory or {}).get("activity_count") or 0)
    baseline_count = int(baseline.get("activity_count") or 0) if isinstance(baseline, dict) else 0
    activity_count = max(inventory_count, baseline_count)
    baseline_loaded = isinstance(baseline, dict)
    imported = activity_count > 0 or bool((inventory or {}).get("latest_refresh"))
    return {
        "loaded": imported or baseline_loaded,
        "baseline_loaded": baseline_loaded,
        "activity_count": activity_count,
        "source_provider": baseline.get("source_provider") if isinstance(baseline, dict) else None,
        "source_path": baseline.get("source_path") if isinstance(baseline, dict) else None,
        "baseline_source_path": baseline_source_path if baseline_loaded else "",
        "sha256": baseline.get("sha256") if isinstance(baseline, dict) else None,
        "reference_date": baseline.get("reference_date") if isinstance(baseline, dict) else None,
        "reserve_score": reserve_trend.get("reserve_score"),
        "reserve_band": reserve_trend.get("current_band"),
        "acute_load_ratio": reserve_trend.get("acute_load_ratio"),
        "confidence": reserve_trend.get("confidence") or data_quality.get("heart_rate_confidence") or "low",
        "latest_refresh": (inventory or {}).get("latest_refresh"),
        "status": _health_status(imported=imported, baseline_loaded=baseline_loaded),
    }


def _projection_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "loaded": False,
            "status": "not_projected",
            "reserve_start_score": None,
            "route_energy_multiplier": None,
            "possible_depletion_checkpoint_name": None,
            "checkpoint_count": 0,
        }
    return {
        "loaded": True,
        "status": payload.get("status") or "projected",
        "source_path": payload.get("source_path"),
        "reserve_start_score": payload.get("reserve_start_score"),
        "route_energy_multiplier": payload.get("route_energy_multiplier"),
        "projected_target_eta": payload.get("projected_target_eta"),
        "possible_depletion_checkpoint_name": payload.get(
            "possible_depletion_checkpoint_name"
        ),
        "checkpoint_count": int(payload.get("checkpoint_count") or len(payload.get("checkpoints", []))),
        "auto_applies_to_eta": False,
    }


def _capability_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "loaded": False,
            "status": "not_loaded",
            "completion_status": None,
            "planned_segment_count": 0,
            "completed_segment_count": 0,
            "unreached_segment_count": 0,
            "moving_time_s": None,
            "elapsed_time_s": None,
            "rest_time_s": None,
        }
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    traversed = int(summary.get("traversed_segment_count") or 0)
    partial = int(summary.get("partial_segment_count") or 0)
    planned = int(summary.get("planned_segment_count") or payload.get("edge_count") or len(payload.get("edges", [])))
    unreached = int(summary.get("unreached_segment_count") or payload.get("unreached_segment_count") or 0)
    return {
        "loaded": True,
        "status": payload.get("status") or "loaded",
        "source_path": payload.get("source_path"),
        "completion_status": summary.get("completion_status") or payload.get("completion_status"),
        "planned_segment_count": planned,
        "completed_segment_count": traversed + partial,
        "traversed_segment_count": traversed,
        "partial_segment_count": partial,
        "unreached_segment_count": unreached,
        "moving_time_s": summary.get("moving_time_s"),
        "elapsed_time_s": summary.get("elapsed_time_s"),
        "rest_time_s": summary.get("rest_time_s"),
        "turnaround_edge_id": summary.get("turnaround_edge_id"),
        "auto_applies_to_eta": False,
    }


def _feedback_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "loaded": False,
            "status": "not_loaded",
            "actual_vs_projected_elapsed_delta_minutes": None,
            "actual_rest_time_minutes": None,
        }
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else payload
    return {
        "loaded": True,
        "status": payload.get("status") or "read_only_post_analysis_feedback",
        "source_path": payload.get("source_path"),
        "predicted_target_duration_minutes": summary.get("predicted_target_duration_minutes"),
        "actual_elapsed_duration_minutes": summary.get("actual_elapsed_duration_minutes"),
        "actual_moving_duration_minutes": summary.get("actual_moving_duration_minutes"),
        "actual_vs_projected_elapsed_delta_minutes": summary.get(
            "actual_vs_projected_elapsed_delta_minutes"
        ),
        "predicted_depletion_checkpoint_name": summary.get(
            "predicted_depletion_checkpoint_name"
        ),
        "actual_rest_time_minutes": summary.get("actual_rest_time_minutes"),
        "auto_applies_to_eta": False,
    }


def _candidate_change_summary(
    *,
    health: dict[str, Any],
    projection: dict[str, Any],
    capability: dict[str, Any],
    feedback: dict[str, Any],
) -> dict[str, Any]:
    delta = 0
    reasons: list[str] = []
    if capability.get("loaded"):
        completion = capability.get("completion_status")
        if completion == "partial":
            delta -= 8
            reasons.append("completed trip was partial")
        elif completion == "abandoned":
            delta -= 12
            reasons.append("completed trip was abandoned")
        elif completion in {"complete", "completed"}:
            reasons.append("completed trip reached planned route")
        unreached = int(capability.get("unreached_segment_count") or 0)
        planned = int(capability.get("planned_segment_count") or 0)
        if planned and unreached / planned >= 0.25:
            delta -= 4
            reasons.append("large unreached route share")
        rest_time_s = capability.get("rest_time_s")
        elapsed_time_s = capability.get("elapsed_time_s")
        if completion and _number(elapsed_time_s) and _number(rest_time_s):
            rest_ratio = float(rest_time_s) / max(float(elapsed_time_s), 1.0)
            if rest_ratio >= 0.35:
                delta -= 4
                reasons.append("high rest-time share")
            elif rest_ratio <= 0.08 and completion in {"complete", "completed"}:
                delta += 2
                reasons.append("low rest-time share on completed route")
    elapsed_delta = feedback.get("actual_vs_projected_elapsed_delta_minutes")
    if _number(elapsed_delta):
        elapsed_delta_float = float(elapsed_delta)
        if elapsed_delta_float >= 90:
            penalty = min(10, max(2, round(elapsed_delta_float / 90) * 2))
            delta -= penalty
            reasons.append("actual trip was slower than pretrip projection")
        elif elapsed_delta_float <= -90:
            boost = min(8, max(2, round(abs(elapsed_delta_float) / 90) * 2))
            delta += boost
            reasons.append("actual trip was faster than pretrip projection")
    delta = max(-25, min(15, int(delta)))
    current_score = health.get("reserve_score")
    candidate_score = None
    if _number(current_score):
        candidate_score = max(0, min(100, int(current_score) + delta))
    if delta < 0:
        direction = "lower_reserve_candidate"
    elif delta > 0:
        direction = "higher_reserve_candidate"
    else:
        direction = "unchanged"
    return {
        "score_delta_candidate": delta,
        "candidate_reserve_score": candidate_score,
        "direction": direction,
        "reasons": reasons or ["no baseline-affecting trip capability signal loaded"],
        "health_data_can_update_baseline": bool(health.get("baseline_loaded")),
        "trip_capability_can_update_baseline": bool(capability.get("loaded")),
        "applied_to_baseline": False,
        "applied_to_pretrip_projection": False,
        "requires_human_review": delta != 0,
        "status": "candidate_delta_ready" if delta else "no_candidate_delta",
    }


def _display_summary(
    health: dict[str, Any],
    capability: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    score = health.get("reserve_score")
    band = health.get("reserve_band") or "no baseline"
    activity_count = int(health.get("activity_count") or 0)
    delta = int(candidate.get("score_delta_candidate") or 0)
    completion = capability.get("completion_status") or "no completed trip"
    if _number(score):
        headline = f"{int(score)} / {band}"
    else:
        headline = band
    if delta:
        change_text = f"{delta:+d} candidate"
    else:
        change_text = "no candidate change"
    return {
        "label": "Energy Reserve",
        "headline": headline,
        "health_text": f"{activity_count} health activities" if activity_count else "health data not loaded",
        "trip_text": f"{completion} capability",
        "change_text": change_text,
        "badge": _badge_for_band(band),
    }


def _monitor_status(
    health: dict[str, Any],
    projection: dict[str, Any],
    capability: dict[str, Any],
    feedback: dict[str, Any],
) -> str:
    if not health.get("loaded"):
        return "missing_health_data"
    if not health.get("baseline_loaded"):
        return "health_data_imported_baseline_missing"
    if feedback.get("loaded") or capability.get("loaded"):
        return "baseline_with_trip_capability_evidence"
    if projection.get("loaded"):
        return "baseline_with_pretrip_projection"
    return "baseline_loaded"


def _health_status(*, imported: bool, baseline_loaded: bool) -> str:
    if baseline_loaded:
        return "baseline_loaded"
    if imported:
        return "health_data_imported_baseline_missing"
    return "missing_health_data"


def _badge_for_band(band: str) -> str:
    return {
        "normal": "normal",
        "watch": "watch",
        "rest_suggested": "rest",
        "stop_and_check": "check",
    }.get(str(band), "missing")


def _energy_projection_from_view(view: dict[str, Any]) -> dict[str, Any] | None:
    eta = view.get("eta", {}) if isinstance(view.get("eta"), dict) else {}
    projection = eta.get("energy_reserve_projection")
    if projection is None:
        projection = (
            view.get("tabs", {})
            .get("pre_trip_planning", {})
            .get("eta", {})
            .get("energy_reserve_projection")
            if isinstance(view.get("tabs"), dict)
            else None
        )
    return projection if isinstance(projection, dict) else None


def _energy_feedback_from_view(view: dict[str, Any]) -> dict[str, Any] | None:
    payload = view.get("post_analysis_energy_feedback")
    if payload is None and isinstance(view.get("tabs"), dict):
        payload = view["tabs"].get("post_analysis", {}).get("post_analysis_energy_feedback")
    return payload if isinstance(payload, dict) else None


def _capability_from_view(view: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("capability_timeline", "capability_timeline_import"):
        payload = view.get(key)
        if isinstance(payload, dict):
            return payload
    if isinstance(view.get("tabs"), dict):
        payload = view["tabs"].get("post_analysis", {}).get("capability_timeline_import")
        if isinstance(payload, dict):
            return payload
    return None


def _inventory_summary(
    inventory_root: Path | None,
    *,
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    if inventory_root is None:
        return {"activity_count": 0, "latest_refresh": None}
    activities_dir = inventory_root / "activities"
    activity_count = len(list(activities_dir.glob("*.json"))) if activities_dir.exists() else 0
    if isinstance(baseline, dict):
        activity_count = max(activity_count, int(baseline.get("activity_count") or 0))
    return {
        "inventory_root": str(inventory_root),
        "activity_count": activity_count,
        "latest_refresh": _load_optional_json(inventory_root / "outputs" / "refresh_result.json"),
    }


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True
