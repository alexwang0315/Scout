from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geo_utils import haversine_m
from route_matching import load_gpx_route, match_point_to_route


LIVE_NAVIGATION_ROUTE_MATCH_ENRICHER_ID = (
    "scout.ai.live_navigation_snapshot.route_match_enrich.v0"
)


def enrich_live_navigation_snapshot_with_route_match(
    snapshot: dict[str, Any],
    *,
    route_path: Path | str | None,
    project_root: Path | str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add deterministic route-match fields to a caller-provided snapshot."""

    enriched = dict(snapshot)
    lat = _float_or_none(snapshot.get("lat"))
    lon = _float_or_none(snapshot.get("lon"))
    if lat is None or lon is None:
        return enriched, _report("missing_position", route_path=route_path)
    if route_path is None:
        return enriched, _report("missing_route_path", route_path=route_path)

    resolved_route_path = Path(route_path)
    if not resolved_route_path.exists():
        return enriched, _report("route_path_missing", route_path=resolved_route_path)

    route = load_gpx_route(resolved_route_path)
    match = match_point_to_route(lat, lon, route)
    _set_if_missing(enriched, "nearest_route_distance_m", round(match.distance_m, 3))
    _set_if_missing(enriched, "route_progress_m", round(match.point.progress_m, 3))

    checkpoint_report = _enrich_nearest_checkpoint(
        enriched,
        lat=lat,
        lon=lon,
        project_root=Path(project_root) if project_root is not None else None,
    )
    return (
        enriched,
        {
            **_report("enriched", route_path=resolved_route_path),
            "enricher_id": LIVE_NAVIGATION_ROUTE_MATCH_ENRICHER_ID,
            "route_index": match.route_index,
            "matched_route_progress_m": round(match.point.progress_m, 3),
            "nearest_route_distance_m": round(match.distance_m, 3),
            "route_match_confidence": round(match.confidence, 3),
            "checkpoint_match": checkpoint_report,
            "read_only": True,
            "runtime_safety_truth": False,
            "safety_api_called": False,
            "phase1_l0_l4_state_mutated": False,
            "outbound_send_performed": False,
            "hardware_control_performed": False,
        },
    )


def _enrich_nearest_checkpoint(
    snapshot: dict[str, Any],
    *,
    lat: float,
    lon: float,
    project_root: Path | None,
) -> dict[str, Any]:
    if project_root is None:
        return {"status": "missing_project_root", "loaded_count": 0}
    checkpoints, source_path = _load_checkpoint_candidates(project_root)
    best_checkpoint: dict[str, Any] | None = None
    best_distance_m = float("inf")
    for checkpoint in checkpoints:
        cp_lat = _float_or_none(checkpoint.get("lat"))
        cp_lon = _float_or_none(checkpoint.get("lon"))
        if cp_lat is None or cp_lon is None:
            continue
        distance_m = haversine_m(lat, lon, cp_lat, cp_lon)
        if distance_m < best_distance_m:
            best_distance_m = distance_m
            best_checkpoint = checkpoint
    if best_checkpoint is None:
        return {
            "status": "no_checkpoint_with_position",
            "source_path": source_path,
            "loaded_count": len(checkpoints),
        }
    candidate_id = best_checkpoint.get("candidate_id")
    if candidate_id is not None:
        _set_if_missing(snapshot, "nearest_cp_id", str(candidate_id))
    return {
        "status": "matched",
        "source_path": source_path,
        "loaded_count": len(checkpoints),
        "nearest_cp_id": str(candidate_id) if candidate_id is not None else None,
        "nearest_cp_distance_m": round(best_distance_m, 3),
        "candidate_only": bool(best_checkpoint.get("candidate_only", True)),
        "runtime_safety_truth": bool(best_checkpoint.get("runtime_safety_truth", False)),
    }


def _load_checkpoint_candidates(project_root: Path) -> tuple[list[dict[str, Any]], str | None]:
    project_path = project_root / "project.json"
    if not project_path.exists():
        return [], None
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], None
    if not isinstance(project, dict):
        return [], None
    checkpoint_ref = project.get("checkpoint_candidates_ref")
    if not isinstance(checkpoint_ref, str) or not checkpoint_ref:
        return [], None
    checkpoint_path = project_root / checkpoint_ref
    if not checkpoint_path.exists():
        return [], str(checkpoint_path)
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [], str(checkpoint_path)
    if not isinstance(payload, list):
        return [], str(checkpoint_path)
    return [item for item in payload if isinstance(item, dict)], str(checkpoint_path)


def _set_if_missing(snapshot: dict[str, Any], field: str, value: Any) -> None:
    if _missing(snapshot.get(field)) and not _missing(value):
        snapshot[field] = value


def _report(status: str, *, route_path: Path | str | None) -> dict[str, Any]:
    return {
        "status": status,
        "source_path": str(route_path) if route_path is not None else None,
        "read_only": True,
        "runtime_safety_truth": False,
    }


def _float_or_none(value: Any) -> float | None:
    if _missing(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False
