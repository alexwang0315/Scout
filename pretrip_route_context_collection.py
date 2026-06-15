from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROUTE_CONTEXT_COLLECTION_ARTIFACT_KIND = "pretrip_route_context_collection"
ROUTE_CONTEXT_EVIDENCE_ARTIFACT_KIND = "pretrip_route_context_evidence"
ROUTE_CONTEXT_POINTS_ARTIFACT_KIND = "pretrip_route_context_points"
ROUTE_CONTEXT_EVIDENCE_REF = "normalized/context/route_context/route_context_evidence.json"
ROUTE_CONTEXT_POINTS_REF = "candidates/route_context_points.json"
ROUTE_CONTEXT_SCHEMA_VERSION = "route_context_collection.v1"
DEFAULT_ROUTE_NOTE_LIMIT = 80


SEC6_ALIGNMENT = {
    "standard": "SCOUT_OUTDOOR_AI_AGENT_STANDARD",
    "section": "Sec. 6 Route Context Intelligence",
    "workspace_layout_section": "Outdoor AI Agent Data Placement",
    "canonical_refs": [
        "normalized/context/route_context/*.json",
        ROUTE_CONTEXT_POINTS_REF,
        "outputs/mcp/named_point_evidence.json",
        "outputs/layers/normalized/web_case_evidence.json",
        "outputs/layers/normalized/raster_label_evidence.geojson",
    ],
}


SOURCE_DEFAULTS: dict[str, dict[str, Any]] = {
    "mcp_candidates": {
        "project_ref_key": "mcp_candidates_ref",
        "default_ref": "outputs/mcp/mcp_candidates.json",
        "required_by_standard_sec6": True,
    },
    "named_point_evidence": {
        "project_ref_key": "mcp_named_point_evidence_ref",
        "default_ref": "outputs/mcp/named_point_evidence.json",
        "required_by_standard_sec6": True,
    },
    "route_note_candidates": {
        "project_ref_key": "route_note_candidates_ref",
        "default_ref": "candidates/route_note_candidates.json",
        "required_by_standard_sec6": False,
    },
    "ocr_label_evidence": {
        "project_ref_key": "mcp_ocr_labels_ref",
        "default_ref": "outputs/mcp/mcp_ocr_labels.json",
        "required_by_standard_sec6": False,
    },
    "web_case_evidence": {
        "project_ref_key": "web_case_evidence_ref",
        "default_ref": "outputs/layers/normalized/web_case_evidence.json",
        "required_by_standard_sec6": False,
    },
    "raster_label_evidence": {
        "project_ref_key": "raster_label_evidence_ref",
        "default_ref": "outputs/layers/normalized/raster_label_evidence.geojson",
        "required_by_standard_sec6": False,
    },
    "import_manifest": {
        "project_ref_key": "import_manifest_ref",
        "default_ref": "outputs/import_manifest.json",
        "required_by_standard_sec6": False,
    },
    "route_summary": {
        "project_ref_key": "route_summary_ref",
        "default_ref": "normalized/routes/route_summary.json",
        "required_by_standard_sec6": False,
    },
}


def collect_pretrip_route_context(
    project_root: Path | str,
    *,
    dry_run: bool = False,
    include_route_notes: bool = True,
    limit_route_notes: int = DEFAULT_ROUTE_NOTE_LIMIT,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """Collect Sec. 6 route-context evidence after GPX import.

    The collector materializes candidate-only evidence into the workspace layout.
    It does not fetch live network sources, call safety APIs, or promote evidence
    into runtime truth.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    collected_at = collected_at or _utc_now()
    route_bbox = _route_bbox(root, project)

    source_report: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []

    mcp_payload, mcp_ref, _ = _load_source(root, project, "mcp_candidates", source_report)
    points.extend(_points_from_mcp_candidates(mcp_payload, mcp_ref))

    named_payload, named_ref, _ = _load_source(root, project, "named_point_evidence", source_report)
    points.extend(_points_from_named_point_evidence(named_payload, named_ref))

    ocr_payload, ocr_ref, _ = _load_source(root, project, "ocr_label_evidence", source_report)
    points.extend(_points_from_ocr_labels(ocr_payload, ocr_ref))

    web_payload, web_ref, _ = _load_source(root, project, "web_case_evidence", source_report)
    points.extend(_points_from_web_case_evidence(web_payload, web_ref))

    raster_payload, raster_ref, _ = _load_source(root, project, "raster_label_evidence", source_report)
    points.extend(_points_from_raster_label_evidence(raster_payload, raster_ref))

    route_note_payload, route_note_ref, _ = _load_source(
        root,
        project,
        "route_note_candidates",
        source_report,
    )
    if include_route_notes:
        points.extend(
            _points_from_route_notes(
                route_note_payload,
                route_note_ref,
                route_bbox=route_bbox,
                limit=max(0, int(limit_route_notes)),
            )
        )

    import_manifest_payload, import_manifest_ref, _ = _load_source(
        root,
        project,
        "import_manifest",
        source_report,
    )
    _load_source(root, project, "route_summary", source_report)

    points = _dedupe_points(points)
    counts = _counts(points)
    evidence_ref = str(project.get("route_context_evidence_ref") or ROUTE_CONTEXT_EVIDENCE_REF)
    points_ref = str(project.get("route_context_points_ref") or ROUTE_CONTEXT_POINTS_REF)
    planned_writes = [evidence_ref, points_ref]

    boundary = _closed_boundary(
        candidate_only=True,
        workspace_file_mutation_allowed=not dry_run,
        raw_payloads_embedded=False,
        source_fulltext_embedded=False,
    )
    points_payload = {
        "artifact_kind": ROUTE_CONTEXT_POINTS_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "source_evidence_ref": evidence_ref,
        "point_count": len(points),
        "counts": counts,
        "points": points,
        "boundary": boundary,
    }
    evidence_payload = {
        "artifact_kind": ROUTE_CONTEXT_EVIDENCE_ARTIFACT_KIND,
        "schema_version": ROUTE_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "source_status": "candidate_only",
        "standard_alignment": SEC6_ALIGNMENT,
        "source_report": source_report,
        "counts": counts,
        "route_context_points_ref": points_ref,
        "import_manifest_ref": import_manifest_ref,
        "import_manifest_summary": _import_manifest_summary(import_manifest_payload),
        "project_update_suggestions": {
            "route_context_evidence_ref": evidence_ref,
            "route_context_points_ref": points_ref,
            "route_context_point_count": len(points),
        },
        "boundary": boundary,
    }
    collection_payload = {
        "artifact_kind": ROUTE_CONTEXT_COLLECTION_ARTIFACT_KIND,
        "status": "completed",
        "dry_run": dry_run,
        "project_id": project_id,
        "writes_performed": False,
        "planned_refs": planned_writes,
        "route_context_point_count": len(points),
        "counts": counts,
        "source_report": source_report,
        "outputs": {
            "route_context_evidence_ref": evidence_ref,
            "route_context_points_ref": points_ref,
        },
        "standard_alignment": SEC6_ALIGNMENT,
        "boundary": boundary,
    }

    if not dry_run:
        _write_json(root / evidence_ref, evidence_payload)
        _write_json(root / points_ref, points_payload)
        collection_payload["writes_performed"] = True
        collection_payload["written_refs"] = planned_writes

    return collection_payload


def _points_from_mcp_candidates(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    candidates = payload.get("mcp_candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        return []
    points = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("label"), raw.get("mcp_id"))
        classes = _str_list(raw.get("mcp_classes"))
        nearest_cp = raw.get("nearest_scout_cp")
        nearest_cp = nearest_cp if isinstance(nearest_cp, dict) else {}
        text_fields = [label, raw.get("mcp_id"), *classes, *(_str_list(raw.get("promotion_reasons")))]
        point = _base_point(
            source_kind="mcp_candidates",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("mcp_id"), label),
            label=label,
            lat=_float_or_none(raw.get("lat")),
            lon=_float_or_none(raw.get("lon")),
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=text_fields,
        )
        point.update(
            {
                "evidence_type": "major_critical_point",
                "mcp_classes": classes,
                "nearest_cp_candidate_id": nearest_cp.get("candidate_id"),
                "linked_cp_candidates": _str_list(raw.get("linked_cp_candidates")),
                "linked_named_points": _str_list(raw.get("linked_named_points")),
                "review_state": raw.get("review_state") or "needs_human_review",
                "confidence": raw.get("confidence"),
                "mention_ratio": _float_or_none(raw.get("mention_ratio")),
                "accepted_evidence_page_count": raw.get("accepted_evidence_page_count"),
                "reference_gaps": _str_list(raw.get("missing_source_gaps")),
                "source_refs": _source_refs_for(source_ref, "mcp_candidates", raw),
            }
        )
        points.append(point)
    return points


def _points_from_named_point_evidence(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    named_points = payload.get("named_points") if isinstance(payload, dict) else []
    if not isinstance(named_points, list):
        return []
    points = []
    for raw in named_points:
        if not isinstance(raw, dict):
            continue
        position = raw.get("route_position")
        position = position if isinstance(position, dict) else {}
        label = _first_text(raw.get("canonical_name"), raw.get("named_point_id"))
        aliases = _str_list(raw.get("aliases"))
        classes = _str_list(raw.get("point_class"))
        text_fields = [
            label,
            raw.get("named_point_id"),
            *aliases,
            *classes,
            *(_str_list(raw.get("source_families"))),
        ]
        point = _base_point(
            source_kind="named_point_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("named_point_id"), label),
            label=label,
            lat=_float_or_none(position.get("lat")),
            lon=_float_or_none(position.get("lon")),
            distance_m=_float_or_none(position.get("distance_m")),
            text_fields=text_fields,
            extra_evidence_families=["named_point", "article"],
        )
        point.update(
            {
                "evidence_type": "named_point",
                "aliases": aliases,
                "point_classes": classes,
                "confidence": position.get("coordinate_confidence"),
                "mention_ratio": _float_or_none(raw.get("mention_ratio")),
                "mention_page_count": raw.get("mention_page_count"),
                "source_families": _str_list(raw.get("source_families")),
                "reference_gaps": _str_list(raw.get("missing_source_families")),
                "source_refs": _source_refs_for(source_ref, "named_point_evidence", raw),
            }
        )
        points.append(point)
    return points


def _points_from_ocr_labels(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    labels = payload.get("labels") if isinstance(payload, dict) else []
    if not isinstance(labels, list):
        return []
    points = []
    for raw in labels:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("label_text"), raw.get("ocr_label_id"))
        point = _base_point(
            source_kind="ocr_label_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("ocr_label_id"), label),
            label=label,
            lat=None,
            lon=None,
            distance_m=None,
            text_fields=[label, raw.get("named_point_id"), raw.get("source_ref")],
            extra_evidence_families=["ocr", "map_label"],
        )
        point.update(
            {
                "evidence_type": "ocr_map_label",
                "named_point_id": raw.get("named_point_id"),
                "confidence": raw.get("confidence"),
                "review_state": "needs_human_review" if raw.get("review_required", True) else "candidate",
                "source_refs": _source_refs_for(source_ref, "ocr_label_evidence", raw),
            }
        )
        points.append(point)
    return points


def _points_from_web_case_evidence(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    records = _list_from_any(payload, ("points", "candidates", "evidence", "cases"))
    points = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("label"), raw.get("title"), raw.get("name"), raw.get("id"))
        lat, lon = _lat_lon_from(raw)
        point = _base_point(
            source_kind="web_case_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("candidate_id"), raw.get("id"), label),
            label=label,
            lat=lat,
            lon=lon,
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=[label, raw.get("summary"), raw.get("source_family"), raw.get("url")],
            extra_evidence_families=["article"],
        )
        point.update(
            {
                "evidence_type": "web_case_evidence",
                "source_families": _str_list(raw.get("source_families") or raw.get("source_family")),
                "source_refs": _source_refs_for(source_ref, "web_case_evidence", raw),
            }
        )
        points.append(point)
    return points


def _points_from_raster_label_evidence(payload: dict[str, Any], source_ref: str) -> list[dict[str, Any]]:
    records = _geojson_features(payload) or _list_from_any(payload, ("features", "labels", "points"))
    points = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else raw
        label = _first_text(
            props.get("label"),
            props.get("label_text"),
            props.get("name"),
            props.get("id"),
        )
        lat, lon = _lat_lon_from(raw)
        if lat is None or lon is None:
            lat, lon = _lat_lon_from(props)
        point = _base_point(
            source_kind="raster_label_evidence",
            source_ref=source_ref,
            source_candidate_id=_first_text(props.get("candidate_id"), props.get("id"), label),
            label=label,
            lat=lat,
            lon=lon,
            distance_m=_float_or_none(props.get("distance_m")),
            text_fields=[label, props.get("class"), props.get("source_ref")],
            extra_evidence_families=["map_label", "ocr"],
        )
        point.update(
            {
                "evidence_type": "raster_map_label",
                "confidence": props.get("confidence"),
                "source_refs": _source_refs_for(source_ref, "raster_label_evidence", props),
            }
        )
        points.append(point)
    return points


def _points_from_route_notes(
    payload: dict[str, Any],
    source_ref: str,
    *,
    route_bbox: dict[str, float] | None,
    limit: int,
) -> list[dict[str, Any]]:
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list) or limit <= 0:
        return []

    ranked: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("candidate_id"))
        category = str(raw.get("note_category") or "")
        lat = _float_or_none(raw.get("lat"))
        lon = _float_or_none(raw.get("lon"))
        if not _is_meaningful_route_note(label, category):
            continue
        if route_bbox and lat is not None and lon is not None and not _within_bbox(
            lat,
            lon,
            route_bbox,
            padding_degrees=0.03,
        ):
            continue
        rank = _route_note_rank(label, category)
        ranked.append((rank, raw))

    ranked.sort(key=lambda item: item[0])
    points = []
    for _, raw in ranked[:limit]:
        label = _first_text(raw.get("normalized_note"), raw.get("name"), raw.get("candidate_id"))
        category = str(raw.get("note_category") or "")
        text_fields = [
            label,
            category,
            raw.get("model_output_summary"),
            raw.get("desc"),
            raw.get("cmt"),
        ]
        point = _base_point(
            source_kind="route_note_candidates",
            source_ref=source_ref,
            source_candidate_id=_first_text(raw.get("candidate_id"), label),
            label=label,
            lat=_float_or_none(raw.get("lat")),
            lon=_float_or_none(raw.get("lon")),
            distance_m=_float_or_none(raw.get("distance_m")),
            text_fields=text_fields,
            extra_evidence_families=["route_note"],
        )
        point.update(
            {
                "evidence_type": "route_note_candidate",
                "route_note_category": category,
                "confidence": raw.get("confidence"),
                "review_state": raw.get("review_state") or "needs_review",
                "route_note_freshness": raw.get("route_note_freshness"),
                "potential_ln_signal": bool(raw.get("potential_ln_signal", False)),
                "source_refs": _source_refs_for(source_ref, "route_note_candidates", raw),
            }
        )
        points.append(point)
    return points


def _base_point(
    *,
    source_kind: str,
    source_ref: str,
    source_candidate_id: str,
    label: str,
    lat: float | None,
    lon: float | None,
    distance_m: float | None,
    text_fields: list[Any],
    extra_evidence_families: list[str] | None = None,
) -> dict[str, Any]:
    sec6_layers = _sec6_layers(text_fields)
    evidence_families = sorted({source_kind, *(extra_evidence_families or [])})
    context_kind = _context_kind(sec6_layers, text_fields)
    return {
        "candidate_id": _candidate_id("route_context", source_kind, source_candidate_id),
        "source_candidate_id": source_candidate_id,
        "label": label,
        "display_label": _display_label(label, source_candidate_id),
        "context_kind": context_kind,
        "sec6_layers": sec6_layers,
        "evidence_families": evidence_families,
        "lat": lat,
        "lon": lon,
        "distance_m": distance_m,
        "candidate_only": True,
        "requires_human_review": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "safety_api_called": False,
        "source_path": source_ref,
    }


def _sec6_layers(values: list[Any]) -> list[str]:
    text = _normalize(" ".join(str(value or "") for value in values))
    layers = []
    if _has_any(
        text,
        (
            "old",
            "historic",
            "history",
            "trail",
            "police",
            "station",
            "古道",
            "舊",
            "警備",
            "駐在",
            "保線",
            "產業道路",
        ),
    ):
        layers.append("historical")
    if _has_any(text, ("indigenous", "tribe", "culture", "地名", "舊社", "獵徑", "文化", "傳說")):
        layers.append("cultural")
    if _has_any(
        text,
        (
            "forest",
            "plant",
            "creek",
            "vegetation",
            "geology",
            "bird",
            "林",
            "溪",
            "植被",
            "自然",
            "地質",
            "鳥",
        ),
    ):
        layers.append("natural")
    if _has_any(
        text,
        (
            "ridge",
            "saddle",
            "valley",
            "collapse",
            "cliff",
            "slope",
            "rope",
            "fork",
            "junction",
            "pass",
            "peak",
            "崩",
            "稜",
            "谷",
            "啞口",
            "鞍",
            "峰",
            "坡",
            "崖",
            "叉路",
            "吊橋",
        ),
    ):
        layers.append("terrain")
    if _has_any(text, ("flower", "cloud", "maple", "rain", "season", "芒草", "花", "楓", "雲海", "雨季", "雪")):
        layers.append("seasonal")
    if _has_any(text, ("viewpoint", "view", "photo", "observation", "大景", "觀景", "展望", "拍", "看")):
        layers.append("observation_point")
    return layers or ["route_context"]


def _context_kind(sec6_layers: list[str], values: list[Any]) -> str:
    text = _normalize(" ".join(str(value or "") for value in values))
    if "observation_point" in sec6_layers:
        return "viewpoint"
    if _has_any(text, ("water", "camp", "hut", "保線所", "水塘", "營地", "山屋", "取水")):
        return "resource_context"
    if _has_any(text, ("fork", "junction", "turn", "叉路", "轉彎", "路口", "岔")):
        return "navigation_context"
    if _has_any(text, ("hazard", "risk", "warning", "collapse", "崩", "危險", "裸露", "斷崖")):
        return "risk_context"
    if "natural" in sec6_layers:
        return "natural_context"
    if "historical" in sec6_layers or "cultural" in sec6_layers:
        return "route_context"
    return "route_context"


def _load_source(
    root: Path,
    project: dict[str, Any],
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, Path]:
    spec = SOURCE_DEFAULTS[source_kind]
    ref = str(project.get(spec["project_ref_key"]) or spec["default_ref"])
    path = _project_path(root, ref)
    payload = _load_json_object(path)
    count = _source_count(source_kind, payload)
    status = "loaded" if count > 0 else "empty"
    if not path.exists():
        status = "missing"
    source_report.append(
        {
            "source_kind": source_kind,
            "status": status,
            "source_path": ref,
            "loaded_count": count,
            "required_by_standard_sec6": bool(spec["required_by_standard_sec6"]),
            "sha256": _sha256(path) if path.exists() and path.is_file() else None,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    return payload, ref, path


def _source_count(source_kind: str, payload: dict[str, Any]) -> int:
    if not payload:
        return 0
    if source_kind == "mcp_candidates":
        return len(payload.get("mcp_candidates") or [])
    if source_kind == "named_point_evidence":
        return len(payload.get("named_points") or [])
    if source_kind == "route_note_candidates":
        return len(payload.get("candidates") or [])
    if source_kind == "ocr_label_evidence":
        return len(payload.get("labels") or [])
    if source_kind == "web_case_evidence":
        return len(_list_from_any(payload, ("points", "candidates", "evidence", "cases")))
    if source_kind == "raster_label_evidence":
        return len(_geojson_features(payload) or _list_from_any(payload, ("features", "labels", "points")))
    return 1


def _route_bbox(root: Path, project: dict[str, Any]) -> dict[str, float] | None:
    ref = str(project.get("route_summary_ref") or SOURCE_DEFAULTS["route_summary"]["default_ref"])
    route_summary = _load_json_object(_project_path(root, ref))
    bbox = route_summary.get("bbox_wgs84")
    if not isinstance(bbox, dict):
        return None
    try:
        return {
            "min_lat": float(bbox["min_lat"]),
            "min_lon": float(bbox["min_lon"]),
            "max_lat": float(bbox["max_lat"]),
            "max_lon": float(bbox["max_lon"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _within_bbox(
    lat: float,
    lon: float,
    bbox: dict[str, float],
    *,
    padding_degrees: float,
) -> bool:
    return (
        bbox["min_lat"] - padding_degrees
        <= lat
        <= bbox["max_lat"] + padding_degrees
        and bbox["min_lon"] - padding_degrees
        <= lon
        <= bbox["max_lon"] + padding_degrees
    )


def _is_meaningful_route_note(label: str, category: str) -> bool:
    if not label:
        return False
    normalized = label.strip()
    if re.fullmatch(r"\d+(\.\d+)?\s*[Kk]", normalized):
        return False
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*", normalized):
        return False
    if normalized.lower().startswith("garmin_") or "birdseye demo" in normalized.lower():
        return False
    if category in {"landmark_hint", "camp_or_water_hint", "route_condition_hint", "hazard_hint"}:
        return True
    return _has_any(
        _normalize(normalized),
        (
            "山",
            "峰",
            "營地",
            "叉路",
            "溪",
            "橋",
            "崩",
            "保線",
            "水",
            "池",
            "啞口",
            "鞍",
            "林",
            "崖",
            "瀑",
            "吊橋",
        ),
    )


def _route_note_rank(label: str, category: str) -> tuple[int, int, str]:
    priority = {
        "hazard_hint": 0,
        "camp_or_water_hint": 1,
        "landmark_hint": 2,
        "route_condition_hint": 3,
    }.get(category, 4)
    return (priority, len(label), label)


def _dedupe_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, float | None, float | None], int] = {}
    deduped = []
    for point in points:
        key = (
            _normalize(point.get("label")),
            str(point.get("context_kind") or ""),
            _rounded_coord(point.get("lat")),
            _rounded_coord(point.get("lon")),
        )
        if key in seen:
            existing = deduped[seen[key]]
            _merge_point_provenance(existing, point)
            continue
        seen[key] = len(deduped)
        deduped.append(point)
    return deduped


def _merge_point_provenance(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["sec6_layers"] = sorted(
        {*_str_list(existing.get("sec6_layers")), *_str_list(incoming.get("sec6_layers"))}
    )
    existing["evidence_families"] = sorted(
        {
            *_str_list(existing.get("evidence_families")),
            *_str_list(incoming.get("evidence_families")),
        }
    )
    evidence_types = {
        *_str_list(existing.get("merged_evidence_types")),
        str(existing.get("evidence_type") or ""),
        str(incoming.get("evidence_type") or ""),
    }
    existing["merged_evidence_types"] = sorted(item for item in evidence_types if item)
    existing["source_refs"] = _merge_source_refs(
        existing.get("source_refs"),
        incoming.get("source_refs"),
    )
    gaps = {
        *_str_list(existing.get("reference_gaps")),
        *_str_list(incoming.get("reference_gaps")),
    }
    if gaps:
        existing["reference_gaps"] = sorted(gaps)
    if existing.get("lat") is None and incoming.get("lat") is not None:
        existing["lat"] = incoming.get("lat")
    if existing.get("lon") is None and incoming.get("lon") is not None:
        existing["lon"] = incoming.get("lon")
    if existing.get("distance_m") is None and incoming.get("distance_m") is not None:
        existing["distance_m"] = incoming.get("distance_m")
    for key in (
        "mention_page_count",
        "mention_ratio",
        "source_families",
        "aliases",
    ):
        if key not in existing and incoming.get(key) is not None:
            existing[key] = incoming.get(key)


def _merge_source_refs(*values: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for ref in value:
            if not isinstance(ref, dict):
                continue
            key = json.dumps(ref, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs[:12]


def _counts(points: list[dict[str, Any]]) -> dict[str, Any]:
    by_layer: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for point in points:
        for layer in point.get("sec6_layers", []):
            by_layer[str(layer)] = by_layer.get(str(layer), 0) + 1
        for family in point.get("evidence_families", []):
            by_family[str(family)] = by_family.get(str(family), 0) + 1
        by_kind[str(point.get("context_kind") or "unknown")] = by_kind.get(
            str(point.get("context_kind") or "unknown"),
            0,
        ) + 1
        by_source[str(point.get("evidence_type") or "unknown")] = by_source.get(
            str(point.get("evidence_type") or "unknown"),
            0,
        ) + 1
    return {
        "route_context_point_count": len(points),
        "by_sec6_layer": dict(sorted(by_layer.items())),
        "by_context_kind": dict(sorted(by_kind.items())),
        "by_evidence_type": dict(sorted(by_source.items())),
        "by_evidence_family": dict(sorted(by_family.items())),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _import_manifest_summary(payload: dict[str, Any]) -> dict[str, Any]:
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    gpx_filter = payload.get("gpx_speed_filter") if isinstance(payload.get("gpx_speed_filter"), dict) else {}
    boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
    return {
        "artifact_kind": payload.get("artifact_kind"),
        "import_stage": payload.get("import_stage"),
        "counts": {
            key: counts.get(key)
            for key in (
                "checkpoint_candidate_count",
                "segment_candidate_count",
                "route_point_count",
                "gis_perception_checkpoint_candidate_count",
            )
            if key in counts
        },
        "gpx_speed_filter_applied": boundary.get("gpx_speed_filter_applied")
        or gpx_filter.get("applied"),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _source_refs_for(source_ref: str, source_kind: str, raw: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = [
        {
            "source_kind": source_kind,
            "source_path": source_ref,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    source_refs = raw.get("source_refs")
    if isinstance(source_refs, list):
        refs.extend(ref for ref in source_refs if isinstance(ref, dict))
    source_ref_value = raw.get("source_ref")
    if source_ref_value:
        refs.append(
            {
                "source_kind": "source_ref",
                "source_ref": str(source_ref_value),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return refs[:8]


def _list_from_any(payload: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _geojson_features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        return [feature for feature in payload["features"] if isinstance(feature, dict)]
    return []


def _lat_lon_from(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _float_or_none(raw.get("lat"))
    lon = _float_or_none(raw.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon
    geometry = raw.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") == "Point":
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, list) and len(coordinates) >= 2:
            return _float_or_none(coordinates[1]), _float_or_none(coordinates[0])
    return None, None


def _display_label(label: str, source_candidate_id: str) -> str:
    value = label.strip()
    if value and not value.startswith(("gis_cp_cluster.", "pretrip_gis_perception_")):
        return value[:48]
    return source_candidate_id.rsplit(".", 1)[-1][:48] or value[:48]


def _candidate_id(prefix: str, source_kind: str, source_candidate_id: str) -> str:
    raw = f"{prefix}.{source_kind}.{source_candidate_id}"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return slug[:180] or f"{prefix}.{source_kind}"


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _rounded_coord(value: Any) -> float | None:
    number = _float_or_none(value)
    return None if number is None else round(number, 6)


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(_normalize(needle) in text for needle in needles)


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _closed_boundary(**overrides: Any) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "compile_allowed": False,
    }
    boundary.update(overrides)
    return boundary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Scout pretrip Route Context Intelligence evidence.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-route-notes", action="store_true", default=True)
    parser.add_argument("--no-route-notes", dest="include_route_notes", action="store_false")
    parser.add_argument("--limit-route-notes", type=int, default=DEFAULT_ROUTE_NOTE_LIMIT)
    parser.add_argument("--collected-at", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    payload = collect_pretrip_route_context(
        args.project_root,
        dry_run=args.dry_run,
        include_route_notes=args.include_route_notes,
        limit_route_notes=args.limit_route_notes,
        collected_at=args.collected_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
