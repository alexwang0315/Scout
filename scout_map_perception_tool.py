from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


MAP_PERCEPTION_TOOL_ID = "pydantic_ai.tool.search_scout_map_perception.v0"

DEFAULT_MAP_PERCEPTION_LIMIT = 6
MAX_MAP_PERCEPTION_LIMIT = 12

_GENERIC_QUERY_TERMS = {
    "cp",
    "near",
    "nearby",
    "annotation",
    "annotations",
    "label",
    "labels",
    "ocr",
    "review",
    "map",
    "tile",
    "tiles",
    "layer",
    "layers",
    "material",
    "materials",
    "附近",
    "周邊",
    "標註",
    "註記",
    "文字",
    "來源",
    "需要",
    "是否",
    "請列出",
    "圖上",
    "圖磚",
    "圖層",
    "地圖",
    "材料",
    "判讀",
    "辨識",
    "有沒有",
    "什麼",
}


def search_project_map_perception(
    project_root: Path | str,
    *,
    query: str = "",
    limit: int = DEFAULT_MAP_PERCEPTION_LIMIT,
    evidence_types: list[str] | None = None,
    cp: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float | None = None,
    sort: str = "auto",
) -> dict[str, Any]:
    """Search existing map/tile perception materials in a pretrip workspace.

    This tool does not run OCR or a vision model. It reads already-normalized
    workspace materials, such as OCR labels, contour interpretation candidates,
    named-point OCR associations, and map layer refs.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    parsed = _parse_query_filters(query)
    resolved_limit = _bounded_limit(limit)
    resolved_evidence_types = _normalize_evidence_types(
        evidence_types if evidence_types is not None else parsed.get("evidence_types")
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
        resolved_radius_m = 1000.0

    source_report: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    named_points = _load_named_points(root, project, source_report)
    items.extend(_load_ocr_label_items(root, project, named_points, source_report))
    items.extend(_load_contour_interpretation_items(root, project, source_report))
    items.extend(_load_map_layer_material_items(project, source_report))

    terms = _query_terms(query)
    filtered: list[dict[str, Any]] = []
    for item in items:
        if resolved_evidence_types and item.get("evidence_type") not in resolved_evidence_types:
            continue
        score = _match_score(item, terms, query)
        if terms and score <= 0:
            continue
        if not _item_matches_anchor(
            item,
            cp_anchor=cp_anchor,
            coordinate_anchor=coordinate_anchor,
            radius_m=resolved_radius_m,
            resolved_cp=resolved_cp,
        ):
            continue
        item = dict(item)
        item["match_score"] = round(score, 3)
        filtered.append(item)

    if not terms and not (cp_anchor or coordinate_anchor or resolved_evidence_types):
        filtered = [dict(item, match_score=0.0) for item in items]

    filtered.sort(key=_sort_key(resolved_sort))
    results = filtered[:resolved_limit]
    summaries = _summaries(items)

    return {
        "tool_id": MAP_PERCEPTION_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "filters": {
            "evidence_types": sorted(resolved_evidence_types) if resolved_evidence_types else None,
            "cp": resolved_cp,
            "cp_anchor": cp_anchor,
            "lat": resolved_lat,
            "lon": resolved_lon,
            "radius_m": resolved_radius_m,
            "sort": resolved_sort,
            "query_terms": sorted(terms),
        },
        "source_report": source_report,
        "summaries": summaries,
        "searched_material_count": len(items),
        "matched_material_count": len(filtered),
        "result_count": len(results),
        "results": [_compact_result(item) for item in results],
        "boundary": _closed_boundary(),
    }


def _load_named_points(
    root: Path,
    project: dict[str, Any],
    source_report: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    ref = project.get("mcp_named_point_evidence_ref") or "outputs/mcp/named_point_evidence.json"
    path = _project_path(root, str(ref))
    if not path.exists():
        source_report.append(
            {
                "source_kind": "named_point_evidence",
                "status": "missing",
                "source_path": str(ref),
                "loaded_count": 0,
            }
        )
        return {}
    payload = _load_json_object(path)
    named_points = payload.get("named_points")
    if not isinstance(named_points, list):
        named_points = []
    by_id = {
        str(item.get("named_point_id")): item
        for item in named_points
        if isinstance(item, dict) and item.get("named_point_id")
    }
    source_report.append(
        {
            "source_kind": "named_point_evidence",
            "status": "loaded",
            "source_path": str(ref),
            "loaded_count": len(by_id),
            "artifact_kind": payload.get("artifact_kind"),
        }
    )
    return by_id


def _load_ocr_label_items(
    root: Path,
    project: dict[str, Any],
    named_points: dict[str, dict[str, Any]],
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = project.get("mcp_ocr_labels_ref") or "outputs/mcp/mcp_ocr_labels.json"
    path = _project_path(root, str(ref))
    if not path.exists():
        source_report.append(
            {
                "source_kind": "ocr_labels",
                "status": "missing",
                "source_path": str(ref),
                "loaded_count": 0,
            }
        )
        return []
    payload = _load_json_object(path)
    labels = payload.get("labels")
    if not isinstance(labels, list):
        labels = []
    items = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        named_point = named_points.get(str(label.get("named_point_id") or ""))
        route_position = (
            named_point.get("route_position")
            if isinstance(named_point, dict) and isinstance(named_point.get("route_position"), dict)
            else {}
        )
        lat = _optional_float(route_position.get("lat"))
        lon = _optional_float(route_position.get("lon"))
        distance_m = _optional_float(route_position.get("distance_m"))
        items.append(
            {
                "evidence_type": "ocr_label",
                "candidate_id": label.get("ocr_label_id"),
                "label_text": label.get("label_text"),
                "source_ref": label.get("source_ref"),
                "source_path": str(ref),
                "bbox": label.get("bbox"),
                "confidence": _optional_float(label.get("confidence")),
                "named_point_id": label.get("named_point_id"),
                "named_point_name": named_point.get("canonical_name") if isinstance(named_point, dict) else None,
                "aliases": named_point.get("aliases", []) if isinstance(named_point, dict) else [],
                "point_class": named_point.get("point_class", []) if isinstance(named_point, dict) else [],
                "lat": lat,
                "lon": lon,
                "distance_m": distance_m,
                "distance_km": round(distance_m / 1000.0, 3) if distance_m is not None else None,
                "review_required": bool(label.get("review_required", True)),
                "candidate_only": bool(label.get("candidate_only", True)),
                "runtime_safety_truth": False,
                "full_source_image_embedded": bool(label.get("full_source_image_embedded", False)),
                "search_text": " ".join(
                    str(part)
                    for part in (
                        label.get("label_text"),
                        label.get("source_ref"),
                        label.get("named_point_id"),
                        named_point.get("canonical_name") if isinstance(named_point, dict) else None,
                        " ".join(named_point.get("aliases", [])) if isinstance(named_point, dict) else None,
                        " ".join(named_point.get("point_class", [])) if isinstance(named_point, dict) else None,
                    )
                    if part
                ),
            }
        )
    source_report.append(
        {
            "source_kind": "ocr_labels",
            "status": "loaded",
            "source_path": str(ref),
            "loaded_count": len(items),
            "artifact_kind": payload.get("artifact_kind"),
        }
    )
    return items


def _load_contour_interpretation_items(
    root: Path,
    project: dict[str, Any],
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = project.get("contour_interpretation_candidates_ref") or "outputs/contour_interpretation_candidates.json"
    path = _project_path(root, str(ref))
    if not path.exists():
        source_report.append(
            {
                "source_kind": "contour_interpretation_candidates",
                "status": "missing",
                "source_path": str(ref),
                "loaded_count": 0,
            }
        )
        return []
    payload = _load_json_object(path)
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    items = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        target_refs = candidate.get("target_refs") if isinstance(candidate.get("target_refs"), dict) else {}
        source_refs = (
            candidate.get("source_artifact_refs")
            if isinstance(candidate.get("source_artifact_refs"), dict)
            else {}
        )
        contour_notes = candidate.get("contour_density_notes")
        terrain_notes = candidate.get("terrain_shape_notes")
        contour_notes = contour_notes if isinstance(contour_notes, list) else []
        terrain_notes = terrain_notes if isinstance(terrain_notes, list) else []
        checkpoint_refs = target_refs.get("checkpoint_candidate_refs", [])
        segment_refs = target_refs.get("segment_candidate_refs", [])
        checkpoint_refs = checkpoint_refs if isinstance(checkpoint_refs, list) else []
        segment_refs = segment_refs if isinstance(segment_refs, list) else []
        items.append(
            {
                "evidence_type": "contour_interpretation",
                "candidate_id": candidate.get("candidate_id"),
                "source_path": str(ref),
                "interpretation_mode": candidate.get("interpretation_mode"),
                "candidate_origin": candidate.get("candidate_origin"),
                "confidence": candidate.get("confidence"),
                "checkpoint_refs": checkpoint_refs,
                "segment_refs": segment_refs,
                "contour_density_notes": contour_notes[:4],
                "terrain_shape_notes": terrain_notes[:4],
                "source_artifact_refs": source_refs,
                "review_required": bool(candidate.get("human_review_required", True)),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "not_observed_fact": bool(candidate.get("not_observed_fact", True)),
                "search_text": " ".join(
                    str(part)
                    for part in (
                        candidate.get("candidate_id"),
                        candidate.get("interpretation_mode"),
                        candidate.get("candidate_origin"),
                        candidate.get("notes"),
                        " ".join(str(item) for item in contour_notes),
                        " ".join(str(item) for item in terrain_notes),
                        " ".join(str(item) for item in checkpoint_refs),
                        " ".join(str(item) for item in segment_refs),
                    )
                    if part
                ),
            }
        )
    source_report.append(
        {
            "source_kind": "contour_interpretation_candidates",
            "status": "loaded",
            "source_path": str(ref),
            "loaded_count": len(items),
            "artifact_kind": payload.get("artifact_id"),
        }
    )
    return items


def _load_map_layer_material_items(
    project: dict[str, Any],
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        from admin_map_layers import build_pretrip_map_layers
    except Exception:
        source_report.append(
            {
                "source_kind": "map_layer_materials",
                "status": "unavailable",
                "source_path": "admin_map_layers.build_pretrip_map_layers",
                "loaded_count": 0,
            }
        )
        return []
    source_refs = {
        key.removesuffix("_ref"): value
        for key, value in project.items()
        if key.endswith("_ref") and isinstance(value, str)
    }
    layers = build_pretrip_map_layers(source_refs=source_refs, weather={})
    items = []
    for layer in layers:
        layer_id = str(layer.get("layer_id") or "")
        searchable = " ".join(
            str(part)
            for part in (
                layer_id,
                layer.get("label"),
                layer.get("label_zh"),
                layer.get("layer_kind"),
                layer.get("source_kind"),
                layer.get("source_path"),
                layer.get("render_mode"),
            )
            if part
        )
        items.append(
            {
                "evidence_type": "map_layer_material",
                "candidate_id": f"map_layer.{layer_id}",
                "layer_id": layer_id,
                "label": layer.get("label"),
                "label_zh": layer.get("label_zh"),
                "layer_kind": layer.get("layer_kind"),
                "render_mode": layer.get("render_mode"),
                "source_kind": layer.get("source_kind"),
                "source_id": layer.get("source_id"),
                "source_path": layer.get("source_path"),
                "available": bool(layer.get("available", False)),
                "candidate_only": True,
                "runtime_safety_truth": bool(layer.get("runtime_safety_truth", False)),
                "review_required": False,
                "search_text": searchable,
            }
        )
    source_report.append(
        {
            "source_kind": "map_layer_materials",
            "status": "loaded",
            "source_path": "admin_map_layers.build_pretrip_map_layers",
            "loaded_count": len(items),
        }
    )
    return items


def _item_matches_anchor(
    item: dict[str, Any],
    *,
    cp_anchor: dict[str, Any] | None,
    coordinate_anchor: dict[str, float] | None,
    radius_m: float | None,
    resolved_cp: str | None,
) -> bool:
    normalized_cp = _normalize_cp_id(resolved_cp or "")
    if normalized_cp:
        checkpoint_refs = item.get("checkpoint_refs")
        if isinstance(checkpoint_refs, list) and any(
            _normalize_cp_id(str(ref)) == normalized_cp for ref in checkpoint_refs
        ):
            return True
    anchor = cp_anchor or coordinate_anchor
    if anchor and radius_m is not None:
        lat = _optional_float(item.get("lat"))
        lon = _optional_float(item.get("lon"))
        if lat is None or lon is None:
            return False if item.get("evidence_type") != "map_layer_material" else True
        item["anchor_distance_m"] = round(
            _haversine_m(float(anchor["lat"]), float(anchor["lon"]), lat, lon),
            2,
        )
        return item["anchor_distance_m"] <= float(radius_m)
    return True


def _match_score(item: dict[str, Any], terms: set[str], query: str) -> float:
    if not terms:
        return 0.0
    haystack = str(item.get("search_text") or "").lower()
    score = 0.0
    for term in terms:
        if term in haystack:
            score += 2.0 if len(term) >= 4 else 1.0
    evidence_type = str(item.get("evidence_type") or "")
    lowered_query = query.lower()
    if evidence_type == "ocr_label" and re.search(r"ocr|annotation|label|標註|註記|文字", lowered_query):
        score += 1.5
    if evidence_type == "contour_interpretation" and re.search(r"contour|等高線|地形判讀|地形", lowered_query):
        score += 1.5
    if evidence_type == "map_layer_material" and re.search(r"layer|圖層|material|材料|forest|草原|森林", lowered_query):
        score += 1.0
    confidence = _optional_float(item.get("confidence"))
    if confidence is not None:
        score += min(confidence, 1.0)
    return score


def _query_terms(query: str) -> set[str]:
    lowered = str(query or "").lower()
    terms = set(re.findall(r"[a-z0-9_.-]{3,}|[\u4e00-\u9fff]{2,}", lowered))
    normalized = set()
    for term in terms:
        if term in _GENERIC_QUERY_TERMS:
            continue
        if any(fragment in term for fragment in _GENERIC_QUERY_TERMS):
            continue
        if re.fullmatch(r"cp[\s._-]*0*\d{1,3}", term):
            continue
        normalized.add(term)
    return normalized


def _parse_query_filters(query: str) -> dict[str, Any]:
    lowered = str(query or "").lower()
    parsed: dict[str, Any] = {}
    cp_match = re.search(r"\bcp[\s._-]*0*(\d{1,3})\b", lowered, flags=re.IGNORECASE)
    if cp_match:
        parsed["cp"] = f"cp.{int(cp_match.group(1)):03d}"
    elif re.search(r"\bstart\b|起點", lowered):
        parsed["cp"] = "cp.start"
    elif re.search(r"\bfinish\b|終點", lowered):
        parsed["cp"] = "cp.finish"
    coordinate_match = re.search(
        r"(-?\d{1,2}\.\d+)\s*[,，]\s*(-?\d{2,3}\.\d+)",
        lowered,
    )
    if coordinate_match:
        parsed["lat"] = float(coordinate_match.group(1))
        parsed["lon"] = float(coordinate_match.group(2))
    if re.search(r"ocr|文字|標註|annotation|label", lowered):
        parsed["evidence_types"] = ["ocr_label"]
    if re.search(r"contour|等高線|地形判讀", lowered):
        parsed["evidence_types"] = ["contour_interpretation"]
    if re.search(r"layer|圖層|material|材料|forest|森林|草原", lowered):
        existing = parsed.get("evidence_types") or []
        parsed["evidence_types"] = [*existing, "map_layer_material"]
    if re.search(r"附近|周邊|near", lowered):
        parsed["sort"] = "anchor_distance_asc"
    return parsed


def _normalize_evidence_types(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        values = [value]
    else:
        values = list(value) if isinstance(value, list) else []
    allowed = {"ocr_label", "contour_interpretation", "map_layer_material"}
    return {
        str(item).strip()
        for item in values
        if str(item).strip() in allowed
    }


def _summaries(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    review_required = 0
    runtime_truth = 0
    for item in items:
        key = str(item.get("evidence_type") or "unknown")
        counts[key] = counts.get(key, 0) + 1
        if item.get("review_required"):
            review_required += 1
        if item.get("runtime_safety_truth"):
            runtime_truth += 1
    return {
        "counts_by_evidence_type": counts,
        "review_required_count": review_required,
        "runtime_safety_truth_count": runtime_truth,
    }


def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "evidence_type",
        "candidate_id",
        "match_score",
        "label_text",
        "named_point_id",
        "named_point_name",
        "aliases",
        "point_class",
        "source_ref",
        "source_path",
        "bbox",
        "confidence",
        "lat",
        "lon",
        "distance_km",
        "anchor_distance_m",
        "checkpoint_refs",
        "segment_refs",
        "contour_density_notes",
        "terrain_shape_notes",
        "interpretation_mode",
        "candidate_origin",
        "source_artifact_refs",
        "layer_id",
        "label",
        "label_zh",
        "layer_kind",
        "render_mode",
        "source_kind",
        "source_id",
        "available",
        "review_required",
        "candidate_only",
        "not_observed_fact",
        "runtime_safety_truth",
        "full_source_image_embedded",
    )
    return {key: item.get(key) for key in keys if item.get(key) is not None}


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
    if not lowered:
        return ""
    if lowered in {"cp.start", "start", "起點"}:
        return "cp.start"
    if lowered in {"cp.finish", "finish", "終點"}:
        return "cp.finish"
    match = re.search(r"cp[\s._-]*0*(\d{1,3})", lowered, flags=re.IGNORECASE)
    if match:
        return f"cp.{int(match.group(1)):03d}"
    return lowered


def _sort_key(sort: str):
    if sort == "anchor_distance_asc":
        return lambda item: (
            item.get("anchor_distance_m") is None,
            item.get("anchor_distance_m") or 0.0,
            -float(item.get("match_score") or 0.0),
        )
    return lambda item: (
        -float(item.get("match_score") or 0.0),
        item.get("anchor_distance_m") is None,
        item.get("anchor_distance_m") or 0.0,
    )


def _bounded_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MAP_PERCEPTION_LIMIT
    return max(1, min(parsed, MAX_MAP_PERCEPTION_LIMIT))


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
        "full_source_image_embedded": False,
    }
