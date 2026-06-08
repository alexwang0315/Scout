from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any


RISK_SCORE_TOOL_ID = "pydantic_ai.tool.search_scout_risk_scores.v0"

DEFAULT_RISK_SCORE_LIMIT = 6
MAX_RISK_SCORE_LIMIT = 12

_BASELINE_SURFACES = {"baseline", "risk_score", "risk-score", "risk_ribbon", "risk-ribbon"}
_CALIBRATION_SURFACES = {
    "calibration",
    "calibrated",
    "calibrated_heatmap",
    "risk_heatmap",
    "risk-heatmap",
    "heatmap",
}
_ALL_SURFACES = {"all", "*", "both", "baseline_and_calibration"}


def search_project_risk_scores(
    project_root: Path | str,
    *,
    query: str = "",
    surface: str = "all",
    limit: int = DEFAULT_RISK_SCORE_LIMIT,
    min_score: float | None = None,
    risk_bucket: str | None = None,
    distance_km_min: float | None = None,
    distance_km_max: float | None = None,
    cp: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float | None = None,
    sort: str = "auto",
) -> dict[str, Any]:
    """Search route-aligned baseline/calibrated risk score artifacts.

    This is intentionally read-only and returns compact evidence summaries, not
    raw GeoJSON payloads. Scores remain pretrip candidate evidence and are not
    promoted to runtime safety truth.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    parsed = _parse_query_filters(query)
    resolved_surface = _normalize_surface(surface, parsed.get("surface"))
    resolved_limit = _bounded_limit(limit)
    resolved_min_score = min_score if min_score is not None else parsed.get("min_score")
    resolved_bucket = risk_bucket or parsed.get("risk_bucket")
    resolved_bucket_rank = _bucket_rank(resolved_bucket)
    resolved_distance_min = (
        distance_km_min
        if distance_km_min is not None
        else parsed.get("distance_km_min")
    )
    resolved_distance_max = (
        distance_km_max
        if distance_km_max is not None
        else parsed.get("distance_km_max")
    )
    resolved_cp = cp or parsed.get("cp")
    resolved_lat = lat if lat is not None else parsed.get("lat")
    resolved_lon = lon if lon is not None else parsed.get("lon")
    resolved_radius_m = radius_m if radius_m is not None else parsed.get("radius_m")
    resolved_sort = sort if sort != "auto" else str(parsed.get("sort") or "score_desc")

    cp_anchor = _resolve_cp_anchor(root, project, resolved_cp) if resolved_cp else None
    coordinate_anchor = (
        {"lat": float(resolved_lat), "lon": float(resolved_lon)}
        if resolved_lat is not None and resolved_lon is not None
        else None
    )
    if (cp_anchor or coordinate_anchor) and resolved_radius_m is None:
        resolved_radius_m = 350.0

    load_report: list[dict[str, Any]] = []
    loaded_items: list[dict[str, Any]] = []
    for item_surface in _surfaces_to_load(resolved_surface):
        surface_items, report = _load_surface_items(root, project, item_surface)
        load_report.extend(report)
        loaded_items.extend(surface_items)

    summaries = _surface_summaries(loaded_items)
    filtered = [
        item
        for item in loaded_items
        if _item_matches_filters(
            item,
            min_score=resolved_min_score,
            bucket_rank=resolved_bucket_rank,
            distance_km_min=resolved_distance_min,
            distance_km_max=resolved_distance_max,
            cp_anchor=cp_anchor,
            coordinate_anchor=coordinate_anchor,
            radius_m=resolved_radius_m,
        )
    ]
    _attach_baseline_calibration_pairs(filtered, loaded_items)
    filtered.sort(key=_sort_key(resolved_sort))
    results = filtered[:resolved_limit]

    return {
        "tool_id": RISK_SCORE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "surface": resolved_surface,
        "filters": {
            "min_score": resolved_min_score,
            "risk_bucket": resolved_bucket,
            "distance_km_min": resolved_distance_min,
            "distance_km_max": resolved_distance_max,
            "cp": resolved_cp,
            "cp_anchor": cp_anchor,
            "lat": resolved_lat,
            "lon": resolved_lon,
            "radius_m": resolved_radius_m,
            "sort": resolved_sort,
        },
        "source_report": load_report,
        "summaries": summaries,
        "searched_score_count": len(loaded_items),
        "matched_score_count": len(filtered),
        "result_count": len(results),
        "results": [_compact_result(item) for item in results],
        "boundary": _closed_boundary(),
    }


def _load_surface_items(
    root: Path,
    project: dict[str, Any],
    surface: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if surface == "baseline":
        refs = (
            ("risk_score_points_ref", "baseline_score_points"),
            ("risk_ribbon_ref", "baseline_ribbon"),
        )
        fallbacks = (
            ("outputs/risk/risk_score_points.geojson", "baseline_score_points"),
            ("outputs/risk_score_points.geojson", "baseline_score_points"),
            ("outputs/risk/risk_ribbon.geojson", "baseline_ribbon"),
            ("outputs/risk_ribbon.geojson", "baseline_ribbon"),
        )
    elif surface == "calibration":
        refs = (("calibrated_risk_heatmap_ref", "calibrated_heatmap"),)
        fallbacks = (
            ("outputs/risk/calibrated_risk_heatmap.geojson", "calibrated_heatmap"),
            ("outputs/calibrated_risk_heatmap.geojson", "calibrated_heatmap"),
        )
    else:
        raise ValueError(f"unsupported risk score surface: {surface}")

    source_path: Path | None = None
    source_ref: str | None = None
    source_kind: str | None = None
    for key, kind in refs:
        ref = project.get(key)
        if not ref:
            continue
        candidate = _project_path(root, str(ref))
        if candidate.exists():
            source_path = candidate
            source_ref = str(ref)
            source_kind = kind
            break
    if source_path is None:
        for ref, kind in fallbacks:
            candidate = _project_path(root, ref)
            if candidate.exists():
                source_path = candidate
                source_ref = ref
                source_kind = kind
                break
    if source_path is None or source_kind is None:
        return [], [
            {
                "surface": surface,
                "status": "missing",
                "source_path": None,
                "loaded_count": 0,
            }
        ]

    payload = _load_json_object(source_path)
    features = payload.get("features", [])
    if not isinstance(features, list):
        features = []
    items: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        item = _feature_to_score_item(
            feature,
            surface=surface,
            source_kind=source_kind,
            source_path=str(source_ref),
            index=index,
        )
        if item is not None:
            items.append(item)
    return items, [
        {
            "surface": surface,
            "status": "loaded",
            "source_path": str(source_ref),
            "source_kind": source_kind,
            "loaded_count": len(items),
            "artifact_kind": payload.get("metadata", {}).get("artifact_kind")
            if isinstance(payload.get("metadata"), dict)
            else None,
        }
    ]


def _feature_to_score_item(
    feature: dict[str, Any],
    *,
    surface: str,
    source_kind: str,
    source_path: str,
    index: int,
) -> dict[str, Any] | None:
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    properties = (
        feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    )
    coords = geometry.get("coordinates")
    lat_lon = _representative_lat_lon(geometry.get("type"), coords)
    if lat_lon is None:
        return None
    lat, lon = lat_lon
    score = _score_from_properties(properties, surface=surface)
    if score is None:
        return None
    start_distance = _optional_float(properties.get("start_distance_m"))
    end_distance = _optional_float(properties.get("end_distance_m"))
    distance = _optional_float(properties.get("distance_m"))
    if distance is None and start_distance is not None and end_distance is not None:
        distance = (start_distance + end_distance) / 2.0
    bucket = (
        properties.get("risk_bucket")
        or properties.get("relative_bucket")
        or _bucket_from_score(score)
    )
    return {
        "surface": surface,
        "source_kind": source_kind,
        "source_path": source_path,
        "index": index,
        "score": round(score, 3),
        "score_field": properties.get("score_field"),
        "risk_bucket": str(bucket) if bucket is not None else None,
        "risk_level": _optional_int(properties.get("risk_level")),
        "relative_heat": _optional_float(properties.get("relative_heat")),
        "lat": round(float(lat), 7),
        "lon": round(float(lon), 7),
        "distance_m": round(distance, 2) if distance is not None else None,
        "distance_km": round(distance / 1000.0, 3) if distance is not None else None,
        "start_distance_m": round(start_distance, 2) if start_distance is not None else None,
        "end_distance_m": round(end_distance, 2) if end_distance is not None else None,
        "route_id": properties.get("route_id"),
        "sample_id": properties.get("sample_id"),
        "segment_id": properties.get("segment_id"),
        "from_sample_id": properties.get("from_sample_id"),
        "to_sample_id": properties.get("to_sample_id"),
        "selected_dimensions": properties.get("selected_dimensions"),
        "candidate_only": bool(properties.get("candidate_only", True)),
        "runtime_safety_truth": bool(properties.get("runtime_safety_truth", False)),
    }


def _representative_lat_lon(
    geometry_type: Any,
    coords: Any,
) -> tuple[float, float] | None:
    if geometry_type == "Point" and isinstance(coords, list) and len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    if geometry_type == "LineString" and isinstance(coords, list) and coords:
        first = coords[0]
        last = coords[-1]
        if (
            isinstance(first, list)
            and isinstance(last, list)
            and len(first) >= 2
            and len(last) >= 2
        ):
            return (float(first[1]) + float(last[1])) / 2.0, (
                float(first[0]) + float(last[0])
            ) / 2.0
    return None


def _score_from_properties(properties: dict[str, Any], *, surface: str) -> float | None:
    preferred = (
        ("calibrated_risk_candidate", "rs", "pretrip_risk")
        if surface == "calibration"
        else ("rs", "pretrip_risk", "calibrated_risk_candidate")
    )
    for key in preferred:
        value = _optional_float(properties.get(key))
        if value is not None:
            return value
    return None


def _item_matches_filters(
    item: dict[str, Any],
    *,
    min_score: float | None,
    bucket_rank: int | None,
    distance_km_min: float | None,
    distance_km_max: float | None,
    cp_anchor: dict[str, Any] | None,
    coordinate_anchor: dict[str, float] | None,
    radius_m: float | None,
) -> bool:
    score = float(item["score"])
    if min_score is not None and score < float(min_score):
        return False
    item_bucket_rank = _bucket_rank(item.get("risk_bucket"))
    if bucket_rank is not None and (
        item_bucket_rank is None or item_bucket_rank < bucket_rank
    ):
        return False
    distance_km = item.get("distance_km")
    if distance_km_min is not None and (
        distance_km is None or float(distance_km) < float(distance_km_min)
    ):
        return False
    if distance_km_max is not None and (
        distance_km is None or float(distance_km) > float(distance_km_max)
    ):
        return False
    anchor = cp_anchor or coordinate_anchor
    if anchor and radius_m is not None:
        item["anchor_distance_m"] = round(
            _haversine_m(
                float(anchor["lat"]),
                float(anchor["lon"]),
                float(item["lat"]),
                float(item["lon"]),
            ),
            2,
        )
        if item["anchor_distance_m"] > float(radius_m):
            return False
    return True


def _attach_baseline_calibration_pairs(
    results: list[dict[str, Any]],
    all_items: list[dict[str, Any]],
) -> None:
    by_surface: dict[str, list[dict[str, Any]]] = {
        "baseline": [item for item in all_items if item.get("surface") == "baseline"],
        "calibration": [
            item for item in all_items if item.get("surface") == "calibration"
        ],
    }
    for item in results:
        distance_m = item.get("distance_m")
        if distance_m is None:
            continue
        other_surface = "calibration" if item.get("surface") == "baseline" else "baseline"
        candidates = [
            other
            for other in by_surface.get(other_surface, [])
            if other.get("distance_m") is not None
        ]
        if not candidates:
            continue
        nearest = min(
            candidates,
            key=lambda other: abs(float(other["distance_m"]) - float(distance_m)),
        )
        gap = abs(float(nearest["distance_m"]) - float(distance_m))
        if gap > 120.0:
            continue
        item[f"paired_{other_surface}_score"] = nearest.get("score")
        item[f"paired_{other_surface}_distance_km"] = nearest.get("distance_km")
        if item.get("surface") == "baseline":
            item["calibration_delta"] = round(
                float(nearest["score"]) - float(item["score"]),
                3,
            )
        else:
            item["calibration_delta"] = round(
                float(item["score"]) - float(nearest["score"]),
                3,
            )


def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "surface",
        "source_kind",
        "source_path",
        "score",
        "score_field",
        "risk_bucket",
        "risk_level",
        "relative_heat",
        "distance_km",
        "distance_m",
        "start_distance_m",
        "end_distance_m",
        "lat",
        "lon",
        "route_id",
        "sample_id",
        "segment_id",
        "from_sample_id",
        "to_sample_id",
        "selected_dimensions",
        "anchor_distance_m",
        "paired_baseline_score",
        "paired_baseline_distance_km",
        "paired_calibration_score",
        "paired_calibration_distance_km",
        "calibration_delta",
        "candidate_only",
        "runtime_safety_truth",
    )
    return {key: item.get(key) for key in keys if item.get(key) is not None}


def _surface_summaries(items: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for surface in ("baseline", "calibration"):
        surface_items = [item for item in items if item.get("surface") == surface]
        scores = [float(item["score"]) for item in surface_items]
        if not scores:
            summaries[surface] = {"available": False, "count": 0}
            continue
        bucket_counts: dict[str, int] = {}
        source_paths = sorted({str(item.get("source_path")) for item in surface_items})
        for item in surface_items:
            bucket = str(item.get("risk_bucket") or "unknown")
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        summaries[surface] = {
            "available": True,
            "count": len(surface_items),
            "source_paths": source_paths,
            "min_score": round(min(scores), 3),
            "max_score": round(max(scores), 3),
            "mean_score": round(mean(scores), 3),
            "bucket_counts": bucket_counts,
        }
    return summaries


def _parse_query_filters(query: str) -> dict[str, Any]:
    text = str(query or "").strip()
    lowered = text.lower()
    parsed: dict[str, Any] = {}
    if re.search(r"\bbaseline\b|基線|原始|risk[-_ ]?score", lowered):
        parsed["surface"] = "baseline"
    if re.search(r"calibrat|heatmap|校準|校正|熱區", lowered):
        parsed["surface"] = "calibration"
    if re.search(r"baseline.*calibrat|calibrat.*baseline|基線.*校|校.*基線|兩種|全部|all", lowered):
        parsed["surface"] = "all"
    cp_match = re.search(r"\bcp[\s._-]*0*(\d{1,3})\b", lowered, flags=re.IGNORECASE)
    if cp_match:
        parsed["cp"] = f"cp.{int(cp_match.group(1)):03d}"
    elif re.search(r"\bstart\b|起點", lowered):
        parsed["cp"] = "cp.start"
    elif re.search(r"\bfinish\b|終點", lowered):
        parsed["cp"] = "cp.finish"
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:km|公里|k)?\s*(?:-|~|到|至)\s*(\d+(?:\.\d+)?)\s*(?:km|公里|k)?",
        lowered,
    )
    if range_match:
        first = float(range_match.group(1))
        second = float(range_match.group(2))
        parsed["distance_km_min"] = min(first, second)
        parsed["distance_km_max"] = max(first, second)
    else:
        km_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里|k)\b", lowered)
        if km_match:
            km = float(km_match.group(1))
            parsed["distance_km_min"] = max(0.0, km - 0.35)
            parsed["distance_km_max"] = km + 0.35
    coordinate_match = re.search(
        r"(-?\d{1,2}\.\d+)\s*[,，]\s*(-?\d{2,3}\.\d+)",
        lowered,
    )
    if coordinate_match:
        parsed["lat"] = float(coordinate_match.group(1))
        parsed["lon"] = float(coordinate_match.group(2))
    threshold_match = re.search(r"(?:score|分數|rs)\s*(?:>=|大於|超過)\s*(\d+(?:\.\d+)?)", lowered)
    if threshold_match:
        parsed["min_score"] = float(threshold_match.group(1))
    if re.search(r"最高|top|highest|max|最大|高風險|危險", lowered):
        parsed["sort"] = "score_desc"
    if re.search(r"極高|extreme|very high|very_high|非常高", lowered):
        parsed["risk_bucket"] = "very_high"
        parsed["sort"] = "score_desc"
    elif re.search(r"高風險|high", lowered):
        parsed["risk_bucket"] = "high"
        parsed["sort"] = "score_desc"
    elif re.search(r"中風險|moderate|medium", lowered):
        parsed["risk_bucket"] = "moderate"
    elif re.search(r"低風險|low", lowered):
        parsed["risk_bucket"] = "low"
    return parsed


def _normalize_surface(value: str, parsed_surface: Any) -> str:
    candidate = str(value or "").strip().lower() or str(parsed_surface or "all")
    if candidate == "all" and parsed_surface:
        candidate = str(parsed_surface).strip().lower()
    if candidate in _ALL_SURFACES:
        return "all"
    if candidate in _BASELINE_SURFACES:
        return "baseline"
    if candidate in _CALIBRATION_SURFACES:
        return "calibration"
    return "all"


def _surfaces_to_load(surface: str) -> tuple[str, ...]:
    if surface == "baseline":
        return ("baseline",)
    if surface == "calibration":
        return ("calibration",)
    return ("baseline", "calibration")


def _resolve_cp_anchor(
    root: Path,
    project: dict[str, Any],
    cp: str,
) -> dict[str, Any] | None:
    ref = project.get("checkpoint_candidates_ref") or "candidates/checkpoints.json"
    path = _project_path(root, str(ref))
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("items", [])
    wanted = _normalize_cp_id(cp)
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or item.get("checkpoint_id") or "")
        label = str(item.get("label") or "")
        if _normalize_cp_id(candidate_id) == wanted or _normalize_cp_id(label) == wanted:
            lat = _optional_float(item.get("lat"))
            lon = _optional_float(item.get("lon"))
            if lat is None or lon is None:
                return None
            return {
                "candidate_id": candidate_id,
                "label": label,
                "lat": lat,
                "lon": lon,
            }
    return None


def _normalize_cp_id(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"cp.start", "start", "起點"}:
        return "cp.start"
    if lowered in {"cp.finish", "finish", "終點"}:
        return "cp.finish"
    match = re.search(r"cp[\s._-]*0*(\d{1,3})", lowered, flags=re.IGNORECASE)
    if match:
        return f"cp.{int(match.group(1)):03d}"
    match = re.search(r"\b0*(\d{1,3})\b", lowered)
    if match:
        return f"cp.{int(match.group(1)):03d}"
    return lowered


def _sort_key(sort: str):
    if sort == "distance_asc":
        return lambda item: (
            item.get("distance_m") is None,
            item.get("distance_m") or 0.0,
            -float(item["score"]),
        )
    if sort == "anchor_distance_asc":
        return lambda item: (
            item.get("anchor_distance_m") is None,
            item.get("anchor_distance_m") or 0.0,
            -float(item["score"]),
        )
    return lambda item: (
        -float(item["score"]),
        item.get("distance_m") is None,
        item.get("distance_m") or 0.0,
    )


def _bucket_from_score(score: float) -> str:
    if score >= 80:
        return "extreme"
    if score >= 60:
        return "high"
    if score >= 40:
        return "moderate"
    return "low"


def _bucket_rank(bucket: Any) -> int | None:
    if bucket is None:
        return None
    normalized = str(bucket).strip().lower().replace("-", "_")
    return {
        "low": 1,
        "moderate": 2,
        "medium": 2,
        "high": 3,
        "very_high": 3,
        "extreme": 4,
    }.get(normalized, None)


def _bounded_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_RISK_SCORE_LIMIT
    return max(1, min(parsed, MAX_RISK_SCORE_LIMIT))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _project_path(root: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "offline_only": True,
        "local_evidence_only": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
    }
