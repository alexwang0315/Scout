from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


EARTH_RADIUS_M = 6_371_000.0


def build_shelter_direction(
    *,
    project_root: str | Path,
    position: dict[str, Any],
    query: str = "",
    limit: int = 3,
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    root = Path(project_root)
    lat = float(position["lat"])
    lon = float(position["lon"])
    route_context = _route_context(root, origin_lat=lat, origin_lon=lon)
    risk_index = _risk_ribbon_index(root)
    weather = _weather_context(root)
    candidates = _shelter_candidates(root)
    ranked = sorted(
        (
            _rank_candidate(
                candidate,
                origin_lat=lat,
                origin_lon=lon,
                route_context=route_context,
                risk_index=risk_index,
            )
            for candidate in candidates
        ),
        key=lambda item: (item["rank_score"], item["distance_m"], item["target_id"]),
    )
    selected = ranked[: max(1, int(limit))]
    recommended = selected[0] if selected else None
    uncertainty = [
        "Output is candidate-only decision support, not runtime safety truth.",
        "No live /safety/* endpoint or live sensor stream was called.",
    ]
    if weather["validation_status"] != "reviewed":
        uncertainty.append("Weather/daylight evidence is placeholder or requires human review.")
    if not any(item["target_type"] == "reviewed_spatial_imprint" for item in selected):
        uncertainty.append("No reviewed shelter-specific spatial imprint was available in the selected candidates.")
    if recommended and recommended["risk_context"]["risk_level"] >= 4:
        uncertainty.append("Recommended target is near high-risk ribbon evidence; operator should confirm before moving.")
    if recommended and not recommended["route_context"]["target_inside_route_bbox"]:
        uncertainty.append("Recommended target is outside the local route bounding box.")
    return {
        "artifact_kind": "scout_safety_action_shelter_direction",
        "status": "completed" if recommended else "blocked",
        "query": query,
        "origin": {
            "lat": lat,
            "lon": lon,
            "source": position.get("source", "operator_or_client_position"),
        },
        "recommended_target": recommended,
        "alternatives": selected[1:],
        "candidate_count": len(candidates),
        "ttl_seconds": max(1, int(ttl_seconds)),
        "evidence_summary": {
            "weather": weather,
            "route": route_context["summary"],
            "risk_ribbon": {
                "available": bool(risk_index),
                "segment_count": len(risk_index),
                "source_ref": "outputs/risk_ribbon.geojson" if risk_index else None,
            },
        },
        "uncertainty_reasons": uncertainty,
        "text_zh": _brief_zh(recommended),
        "source_refs": sorted(
            {
                source_ref
                for item in selected
                for source_ref in item.get("source_refs", [])
            }
            | {
                ref
                for ref in (
                    "outputs/weather_daylight_evidence.json" if weather["available"] else None,
                    "normalized/routes/route_summary.json" if route_context["summary"]["available"] else None,
                    "outputs/risk_ribbon.geojson" if risk_index else None,
                )
                if ref is not None
            }
        ),
        "boundary": {
            "runtime_safety_truth": False,
            "candidate_only": True,
            "advisory_decision_support": True,
            "live_safety_api_calls_allowed": False,
            "phase1_safety_mutation_allowed": False,
            "remote_outbound_send_allowed": False,
            "hardware_control_allowed": False,
        },
    }


def _shelter_candidates(project_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(_trailhead_candidates(project_root))
    candidates.extend(_retreat_route_candidates(project_root))
    candidates.extend(_spatial_imprint_candidates(project_root))
    return _dedupe_candidates(candidates)


def _trailhead_candidates(project_root: Path) -> list[dict[str, Any]]:
    payload = _load_json_if_exists(project_root / "candidates" / "map_candidates.json")
    results = []
    for item in payload.get("poi_candidates", []) or []:
        poi = item.get("poi", {})
        coordinate = poi.get("coordinate") or {}
        if coordinate.get("lat") is None or coordinate.get("lon") is None:
            continue
        poi_type = str(poi.get("poi_type") or "").lower()
        label = str(item.get("label") or poi.get("name") or item.get("candidate_id"))
        if poi_type not in {"trailhead", "shelter", "hut", "water", "camp"}:
            continue
        results.append(
            {
                "target_id": item.get("candidate_id") or poi.get("poi_id") or label,
                "label": label,
                "target_type": poi_type,
                "lat": float(coordinate["lat"]),
                "lon": float(coordinate["lon"]),
                "confidence": "medium",
                "reason": "Map POI candidate from local pretrip evidence.",
                "source_refs": list(item.get("source_refs") or ["candidates/map_candidates.json"]),
                "rank_penalty_m": 800.0 if poi_type == "trailhead" else 300.0,
            }
        )
    return results


def _retreat_route_candidates(project_root: Path) -> list[dict[str, Any]]:
    routes = _load_json_if_exists(project_root / "candidates" / "retreat_routes.json")
    checkpoints = {
        item.get("candidate_id"): item
        for item in _load_json_if_exists(project_root / "candidates" / "checkpoints.json")
        if isinstance(item, dict)
    }
    if not isinstance(routes, list):
        return []
    results = []
    for route in routes:
        cp_ref = route.get("entry_checkpoint_candidate_id") or route.get("trigger_checkpoint_candidate_id")
        checkpoint = checkpoints.get(cp_ref)
        if not checkpoint or checkpoint.get("lat") is None or checkpoint.get("lon") is None:
            continue
        results.append(
            {
                "target_id": route.get("candidate_id") or f"retreat.{cp_ref}",
                "label": route.get("label") or f"Retreat route via {cp_ref}",
                "target_type": "retreat_route",
                "lat": float(checkpoint["lat"]),
                "lon": float(checkpoint["lon"]),
                "confidence": route.get("confidence", "medium"),
                "reason": route.get("notes") or "Local retreat route candidate.",
                "source_refs": list(route.get("source_refs") or ["candidates/retreat_routes.json"]),
                "rank_penalty_m": 400.0,
            }
        )
    return results


def _spatial_imprint_candidates(project_root: Path) -> list[dict[str, Any]]:
    results = []
    for path, reviewed in (
        (project_root / "outputs" / "spatial_imprint_set.json", True),
        (project_root / "candidates" / "spatial_imprints.json", False),
    ):
        payload = _load_json_if_exists(path)
        imprints = payload.get("imprints") if reviewed else payload.get("candidates")
        for item in imprints or []:
            anchor = item.get("anchor", {})
            coordinate = anchor.get("coordinate") or {}
            if coordinate.get("lat") is None or coordinate.get("lon") is None:
                continue
            label = str(item.get("label") or item.get("imprint_id"))
            kind = str(item.get("kind") or "")
            payload_text = str((item.get("payload") or {}).get("text_zh") or "")
            searchable = f"{label} {kind} {payload_text}".lower()
            if not _is_shelter_like(searchable):
                continue
            results.append(
                {
                    "target_id": item.get("imprint_id"),
                    "label": label,
                    "target_type": "reviewed_spatial_imprint" if reviewed else "spatial_imprint_candidate",
                    "lat": float(coordinate["lat"]),
                    "lon": float(coordinate["lon"]),
                    "confidence": "high" if reviewed else "low",
                    "reason": "Spatial Imprint cue with shelter/rest semantics.",
                    "source_refs": [
                        source.get("source_id") or source.get("source_path")
                        for source in item.get("source_refs", [])
                        if isinstance(source, dict)
                    ]
                    or [str(path.relative_to(project_root))],
                    "rank_penalty_m": 0.0 if reviewed else 1200.0,
                }
            )
    return results


def _rank_candidate(
    candidate: dict[str, Any],
    *,
    origin_lat: float,
    origin_lon: float,
    route_context: dict[str, Any],
    risk_index: list[dict[str, Any]],
) -> dict[str, Any]:
    distance = haversine_m(origin_lat, origin_lon, candidate["lat"], candidate["lon"])
    bearing = bearing_degrees(origin_lat, origin_lon, candidate["lat"], candidate["lon"])
    risk_context = _nearest_risk_context(candidate["lat"], candidate["lon"], risk_index)
    candidate_route_context = _candidate_route_context(
        candidate["lat"],
        candidate["lon"],
        route_context,
    )
    risk_penalty = _risk_penalty_m(risk_context)
    route_penalty = 0.0 if candidate_route_context["target_inside_route_bbox"] else 2000.0
    ranked = {
        key: value
        for key, value in candidate.items()
        if key not in {"lat", "lon", "rank_penalty_m"}
    }
    ranked.update(
        {
            "coordinate": {"lat": candidate["lat"], "lon": candidate["lon"]},
            "distance_m": round(distance, 2),
            "bearing_degrees": round(bearing, 1),
            "relative_direction": cardinal_zh(bearing),
            "risk_context": risk_context,
            "route_context": candidate_route_context,
            "rank_components": {
                "distance_m": round(distance, 2),
                "type_penalty_m": round(float(candidate.get("rank_penalty_m", 0.0)), 2),
                "risk_penalty_m": round(risk_penalty, 2),
                "route_penalty_m": round(route_penalty, 2),
            },
            "rank_score": round(
                distance
                + float(candidate.get("rank_penalty_m", 0.0))
                + risk_penalty
                + route_penalty,
                2,
            ),
        }
    )
    return ranked


def _weather_context(project_root: Path) -> dict[str, Any]:
    payload = _load_json_if_exists(project_root / "outputs" / "weather_daylight_evidence.json")
    if not isinstance(payload, dict) or not payload:
        return {
            "available": False,
            "source_ref": None,
            "status": "missing",
            "validation_status": "missing",
            "external_api_calls_made": False,
            "human_review_required": True,
        }
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    weather_window = payload.get("weather_window") if isinstance(payload.get("weather_window"), dict) else {}
    return {
        "available": True,
        "source_ref": "outputs/weather_daylight_evidence.json",
        "status": payload.get("status"),
        "validation_status": validation.get("validation_status", "unknown"),
        "external_api_calls_made": bool(payload.get("external_api_calls_made", False)),
        "human_review_required": bool(payload.get("human_review_required", True)),
        "precipitation_probability": weather_window.get("precipitation_probability"),
        "wind_speed_kph": weather_window.get("wind_speed_kph"),
    }


def _route_context(
    project_root: Path,
    *,
    origin_lat: float,
    origin_lon: float,
) -> dict[str, Any]:
    payload = _load_json_if_exists(project_root / "normalized" / "routes" / "route_summary.json")
    if not isinstance(payload, dict) or not payload:
        return {
            "bbox": None,
            "summary": {
                "available": False,
                "source_ref": None,
                "origin_inside_route_bbox": None,
            },
        }
    bbox = payload.get("bbox_wgs84") if isinstance(payload.get("bbox_wgs84"), dict) else None
    return {
        "bbox": bbox,
        "summary": {
            "available": True,
            "source_ref": "normalized/routes/route_summary.json",
            "route_name": payload.get("route_name"),
            "distance_m": payload.get("distance_m"),
            "origin_inside_route_bbox": _inside_bbox(origin_lat, origin_lon, bbox),
        },
    }


def _candidate_route_context(
    lat: float,
    lon: float,
    route_context: dict[str, Any],
) -> dict[str, Any]:
    bbox = route_context.get("bbox")
    return {
        "route_source_ref": route_context.get("summary", {}).get("source_ref"),
        "origin_inside_route_bbox": route_context.get("summary", {}).get("origin_inside_route_bbox"),
        "target_inside_route_bbox": _inside_bbox(lat, lon, bbox),
    }


def _risk_ribbon_index(project_root: Path) -> list[dict[str, Any]]:
    payload = _load_json_if_exists(project_root / "outputs" / "risk_ribbon.geojson")
    features = payload.get("features") if isinstance(payload, dict) else []
    index = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coordinates = geometry.get("coordinates") if geometry.get("type") == "LineString" else None
        if not isinstance(coordinates, list) or not coordinates:
            continue
        lon_values = [float(point[0]) for point in coordinates if isinstance(point, list) and len(point) >= 2]
        lat_values = [float(point[1]) for point in coordinates if isinstance(point, list) and len(point) >= 2]
        if not lat_values or not lon_values:
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        index.append(
            {
                "lat": sum(lat_values) / len(lat_values),
                "lon": sum(lon_values) / len(lon_values),
                "segment_id": properties.get("segment_id"),
                "risk_level": int(properties.get("risk_level", 0) or 0),
                "risk_bucket": properties.get("risk_bucket"),
                "pretrip_risk": properties.get("rs"),
                "candidate_only": bool(properties.get("candidate_only", True)),
                "runtime_safety_truth": bool(properties.get("runtime_safety_truth", False)),
            }
        )
    return index


def _nearest_risk_context(lat: float, lon: float, risk_index: list[dict[str, Any]]) -> dict[str, Any]:
    if not risk_index:
        return {
            "available": False,
            "source_ref": None,
            "nearest_segment_id": None,
            "distance_m": None,
            "risk_level": 0,
            "risk_bucket": None,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    nearest = min(
        risk_index,
        key=lambda item: haversine_m(lat, lon, item["lat"], item["lon"]),
    )
    return {
        "available": True,
        "source_ref": "outputs/risk_ribbon.geojson",
        "nearest_segment_id": nearest.get("segment_id"),
        "distance_m": round(haversine_m(lat, lon, nearest["lat"], nearest["lon"]), 2),
        "risk_level": int(nearest.get("risk_level", 0) or 0),
        "risk_bucket": nearest.get("risk_bucket"),
        "pretrip_risk": nearest.get("pretrip_risk"),
        "candidate_only": bool(nearest.get("candidate_only", True)),
        "runtime_safety_truth": bool(nearest.get("runtime_safety_truth", False)),
    }


def _risk_penalty_m(risk_context: dict[str, Any]) -> float:
    if not risk_context.get("available"):
        return 250.0
    risk_level = int(risk_context.get("risk_level", 0) or 0)
    distance_m = risk_context.get("distance_m")
    proximity_factor = 1.0 if distance_m is None else max(0.0, 1.0 - min(float(distance_m), 500.0) / 500.0)
    return risk_level * 250.0 * proximity_factor


def _inside_bbox(lat: float, lon: float, bbox: dict[str, Any] | None) -> bool | None:
    if not bbox:
        return None
    min_lat = bbox.get("min_lat")
    max_lat = bbox.get("max_lat")
    min_lon = bbox.get("min_lon")
    max_lon = bbox.get("max_lon")
    if None in (min_lat, max_lat, min_lon, max_lon):
        return None
    return float(min_lat) <= lat <= float(max_lat) and float(min_lon) <= lon <= float(max_lon)


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in candidates:
        target_id = str(item.get("target_id"))
        current = by_id.get(target_id)
        if current is None or float(item.get("rank_penalty_m", 0.0)) < float(
            current.get("rank_penalty_m", 0.0)
        ):
            by_id[target_id] = item
    return list(by_id.values())


def _is_shelter_like(text: str) -> bool:
    return any(
        token in text
        for token in (
            "shelter",
            "hut",
            "camp",
            "rest",
            "water",
            "避雨",
            "隱蔽",
            "休息",
            "山屋",
            "營地",
            "集合",
        )
    )


def _brief_zh(target: dict[str, Any] | None) -> str:
    if not target:
        return "目前本地資料沒有足夠候選點，請停下並由領隊確認。"
    return (
        f"建議往{target['relative_direction']}方向約{int(round(target['distance_m']))}公尺，"
        f"目標是{target['label']}。這是本地候選資料的臨時建議，請由人員確認。"
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def cardinal_zh(bearing: float) -> str:
    labels = ["北", "東北", "東", "東南", "南", "西南", "西", "西北"]
    index = int((bearing + 22.5) // 45) % 8
    return labels[index]


def _load_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return {} if path.suffix == ".json" else []
    return json.loads(path.read_text(encoding="utf-8"))
