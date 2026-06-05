from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


WORKSPACE_CATALOG_TOOL_ID = "pydantic_ai.tool.search_scout_workspace_catalog.v0"
ROUTE_STRUCTURE_TOOL_ID = "pydantic_ai.tool.search_scout_route_structure.v0"
MAJOR_POINT_TOOL_ID = "pydantic_ai.tool.search_scout_major_points.v0"
EVIDENCE_FULLTEXT_TOOL_ID = "pydantic_ai.tool.search_scout_evidence_fulltext.v0"

DEFAULT_WORKSPACE_SEARCH_LIMIT = 6
MAX_WORKSPACE_SEARCH_LIMIT = 16

_GENERIC_TERMS = {
    "cp",
    "route",
    "routes",
    "workspace",
    "artifact",
    "artifacts",
    "data",
    "layer",
    "layers",
    "source",
    "sources",
    "summary",
    "search",
    "near",
    "nearby",
    "scout",
    "ai",
    "資料",
    "有哪些",
    "有多少",
    "幾個",
    "在哪",
    "附近",
    "經過",
    "查詢",
    "來源",
    "圖層",
    "工作區",
    "規劃",
}

_DOMAIN_HINTS = {
    "route": ("route", "routes", "checkpoint", "segment", "cp", "路線", "檢查點"),
    "map": ("map", "overpass", "tile", "imagery", "ocr", "地圖", "圖磚", "標註"),
    "terrain": ("terrain", "dtm", "dem", "slope", "contour", "地形", "坡度", "等高線"),
    "risk": ("risk", "hazard", "ribbon", "heatmap", "風險", "危險"),
    "mcp": ("mcp", "major", "named", "critical", "黑水塘", "重要點"),
    "timing": ("eta", "timing", "daylight", "weather", "時間", "天氣", "摸黑"),
    "resource": ("resource", "energy", "battery", "vitals", "資源", "體力", "電力"),
    "review": ("review", "human", "decision", "審查", "人工", "決策"),
    "runtime": ("runtime", "debug", "handoff", "admin", "執行", "除錯"),
    "tool": ("tool", "skill", "manifest", "agent", "工具", "技能"),
}


def search_project_workspace_catalog(
    project_root: Path | str,
    *,
    query: str = "",
    domains: list[str] | None = None,
    include_missing: bool = True,
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    resolved_limit = _bounded_limit(limit)
    requested_domains = _normalize_domains(domains) or _domains_from_query(query)
    terms = _query_terms(query)

    items = _catalog_items(root, project)
    filtered: list[dict[str, Any]] = []
    for item in items:
        if requested_domains and item["domain"] not in requested_domains:
            continue
        if not include_missing and not item["exists"]:
            continue
        score = _catalog_match_score(item, terms, query)
        if terms and score <= 0:
            continue
        filtered.append({**item, "match_score": round(score, 3)})

    if not terms and not requested_domains:
        filtered = [{**item, "match_score": 0.0} for item in items if include_missing or item["exists"]]

    filtered.sort(key=lambda item: (-item["match_score"], item["domain"], item["ref_key"]))
    return {
        "tool_id": WORKSPACE_CATALOG_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "filters": {
            "domains": sorted(requested_domains) if requested_domains else None,
            "include_missing": include_missing,
            "query_terms": sorted(terms),
        },
        "summaries": _catalog_summaries(items),
        "searched_artifact_count": len(items),
        "matched_artifact_count": len(filtered),
        "result_count": len(filtered[:resolved_limit]),
        "results": filtered[:resolved_limit],
        "boundary": _closed_boundary(),
    }


def search_project_route_structure(
    project_root: Path | str,
    *,
    query: str = "",
    cp: str | None = None,
    segment: str | None = None,
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    route = _load_json_object(_project_path(root, str(project.get("route_summary_ref", ""))))
    checkpoints, checkpoint_source = _load_project_list(root, project, "checkpoint_candidates_ref")
    segments, segment_source = _load_project_list(root, project, "segment_candidates_ref")
    resolved_limit = _bounded_limit(limit)
    resolved_cp = cp or _parse_cp(query)
    resolved_segment = segment or _parse_segment(query)
    terms = _query_terms(query)

    items: list[dict[str, Any]] = []
    cp_by_id = {str(item.get("candidate_id")): item for item in checkpoints if isinstance(item, dict)}
    for index, raw in enumerate(checkpoints):
        if not isinstance(raw, dict):
            continue
        items.append(_checkpoint_item(raw, source_path=checkpoint_source, index=index))
    for index, raw in enumerate(segments):
        if not isinstance(raw, dict):
            continue
        items.append(
            _segment_item(
                raw,
                source_path=segment_source,
                index=index,
                from_cp=cp_by_id.get(str(raw.get("from_candidate_id"))),
                to_cp=cp_by_id.get(str(raw.get("to_candidate_id"))),
            )
        )

    filtered: list[dict[str, Any]] = []
    for item in items:
        if resolved_cp and not _item_references_cp(item, resolved_cp):
            continue
        if resolved_segment and str(item.get("candidate_id", "")).lower() != resolved_segment.lower():
            continue
        score = _text_match_score(item.get("search_text", ""), terms, query)
        if terms and score <= 0 and not (resolved_cp or resolved_segment):
            continue
        filtered.append({k: v for k, v in item.items() if k != "search_text"} | {"match_score": round(score, 3)})

    if not terms and not (resolved_cp or resolved_segment):
        filtered = [
            {k: v for k, v in item.items() if k != "search_text"} | {"match_score": 0.0}
            for item in items
        ]

    filtered.sort(
        key=lambda item: (
            0 if item.get("evidence_type") == "checkpoint" else 1,
            str(item.get("candidate_id")),
        )
    )
    return {
        "tool_id": ROUTE_STRUCTURE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "filters": {"cp": resolved_cp, "segment": resolved_segment, "query_terms": sorted(terms)},
        "route_summary": _compact_route_summary(route),
        "summaries": {
            "checkpoint_count": len(checkpoints),
            "segment_count": len(segments),
            "source_paths": {
                "route_summary": project.get("route_summary_ref"),
                "checkpoints": checkpoint_source,
                "segments": segment_source,
            },
        },
        "searched_route_item_count": len(items),
        "matched_route_item_count": len(filtered),
        "result_count": len(filtered[:resolved_limit]),
        "results": filtered[:resolved_limit],
        "boundary": _closed_boundary(),
    }


def search_project_major_points(
    project_root: Path | str,
    *,
    query: str = "",
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
    cp: str | None = None,
    point_kinds: list[str] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    resolved_limit = _bounded_limit(limit)
    resolved_cp = cp or _parse_cp(query)
    resolved_kinds = {str(kind).lower() for kind in (point_kinds or []) if str(kind).strip()}
    terms = _query_terms(query)
    items, source_report = _major_point_items(root, project)

    filtered: list[dict[str, Any]] = []
    for item in items:
        if resolved_cp and not _item_references_cp(item, resolved_cp):
            continue
        if resolved_kinds and not (set(str(kind).lower() for kind in item.get("point_classes", [])) & resolved_kinds):
            continue
        score = _text_match_score(item.get("search_text", ""), terms, query)
        if terms and score <= 0 and not resolved_cp:
            continue
        compact = {k: v for k, v in item.items() if k != "search_text"}
        compact["match_score"] = round(score, 3)
        filtered.append(compact)

    if not terms and not resolved_cp and not resolved_kinds:
        filtered = [
            {k: v for k, v in item.items() if k != "search_text"} | {"match_score": 0.0}
            for item in items
        ]

    filtered.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            str(item.get("label") or item.get("candidate_id")),
        )
    )
    return {
        "tool_id": MAJOR_POINT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "filters": {
            "cp": resolved_cp,
            "point_kinds": sorted(resolved_kinds) if resolved_kinds else None,
            "query_terms": sorted(terms),
        },
        "source_report": source_report,
        "summaries": {
            "major_point_count": sum(1 for item in items if item["evidence_type"] == "major_point"),
            "named_point_count": sum(1 for item in items if item["evidence_type"] == "named_point"),
            "support_row_count": sum(1 for item in items if item["evidence_type"] == "major_point_cp_support"),
            "ocr_label_count": sum(1 for item in items if item["evidence_type"] == "ocr_label"),
        },
        "searched_point_count": len(items),
        "matched_point_count": len(filtered),
        "result_count": len(filtered[:resolved_limit]),
        "results": filtered[:resolved_limit],
        "boundary": _closed_boundary(),
    }


def search_project_evidence_fulltext(
    project_root: Path | str,
    *,
    query: str,
    limit: int = DEFAULT_WORKSPACE_SEARCH_LIMIT,
    evidence_types: list[str] | None = None,
) -> dict[str, Any]:
    from scout_agent_kb import query_project_local_evidence

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    result = query_project_local_evidence(
        root,
        query=query,
        limit=_bounded_limit(limit),
        evidence_types=set(evidence_types) if evidence_types else None,
    )
    return {
        "tool_id": EVIDENCE_FULLTEXT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": result.query,
        "retrieval_engine": result.retrieval_engine,
        "result_count": result.result_count,
        "searched_record_count": result.searched_record_count,
        "results": result.results,
        "boundary": {
            **result.boundary.model_dump(mode="json"),
            "read_only": True,
            "runtime_safety_truth": False,
            "raw_payloads_embedded": False,
        },
    }


def _catalog_items(root: Path, project: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, value in sorted(project.items()):
        if not key.endswith("_ref") or not isinstance(value, str):
            continue
        domain = _domain_for_ref(key, value)
        path = _project_path(root, value)
        count_keys = _related_count_keys(project, key)
        artifact_kind = None
        top_level_keys: list[str] = []
        if path.exists() and path.suffix.lower() in {".json", ".geojson"}:
            payload = _load_json_object(path)
            artifact_kind = payload.get("artifact_kind") if isinstance(payload, dict) else None
            top_level_keys = sorted(payload.keys())[:12] if isinstance(payload, dict) else []
        items.append(
            {
                "evidence_type": "workspace_artifact_ref",
                "domain": domain,
                "ref_key": key,
                "source_path": value,
                "exists": path.exists(),
                "count_keys": count_keys,
                "artifact_kind": artifact_kind,
                "top_level_keys": top_level_keys,
                "candidate_only": _looks_candidate_key(key, value),
                "runtime_safety_truth": False,
                "search_text": " ".join(
                    [
                        key,
                        value,
                        domain,
                        artifact_kind or "",
                        " ".join(count_keys.keys()),
                        " ".join(str(v) for v in count_keys.values()),
                    ]
                ),
            }
        )
    return items


def _catalog_summaries(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_domain: dict[str, dict[str, int]] = {}
    for item in items:
        domain = str(item["domain"])
        by_domain.setdefault(domain, {"total": 0, "existing": 0, "missing": 0})
        by_domain[domain]["total"] += 1
        by_domain[domain]["existing" if item["exists"] else "missing"] += 1
    return {
        "artifact_ref_count": len(items),
        "existing_ref_count": sum(1 for item in items if item["exists"]),
        "missing_ref_count": sum(1 for item in items if not item["exists"]),
        "domains": by_domain,
    }


def _checkpoint_item(raw: dict[str, Any], *, source_path: str, index: int) -> dict[str, Any]:
    candidate_id = str(raw.get("candidate_id") or f"checkpoint.{index}")
    label = str(raw.get("label") or candidate_id)
    return {
        "evidence_type": "checkpoint",
        "candidate_id": candidate_id,
        "label": label,
        "checkpoint_type": raw.get("checkpoint_type"),
        "lat": _optional_float(raw.get("lat")),
        "lon": _optional_float(raw.get("lon")),
        "route_point_index": raw.get("route_point_index"),
        "arrival_radius_m": raw.get("arrival_radius_m"),
        "review_state": raw.get("review_state"),
        "candidate_only": bool(raw.get("candidate_only", True)),
        "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
        "source_path": source_path,
        "search_text": " ".join(str(part) for part in (candidate_id, label, raw.get("notes"), raw.get("checkpoint_type")) if part),
    }


def _segment_item(
    raw: dict[str, Any],
    *,
    source_path: str,
    index: int,
    from_cp: dict[str, Any] | None,
    to_cp: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_id = str(raw.get("candidate_id") or f"segment.{index}")
    label = str(raw.get("label") or candidate_id)
    return {
        "evidence_type": "segment",
        "candidate_id": candidate_id,
        "label": label,
        "from_candidate_id": raw.get("from_candidate_id"),
        "to_candidate_id": raw.get("to_candidate_id"),
        "from_label": from_cp.get("label") if isinstance(from_cp, dict) else None,
        "to_label": to_cp.get("label") if isinstance(to_cp, dict) else None,
        "distance_m": _optional_float(raw.get("distance_m")),
        "elevation_gain_m": _optional_float(raw.get("elevation_gain_m")),
        "elevation_loss_m": _optional_float(raw.get("elevation_loss_m")),
        "review_state": raw.get("review_state"),
        "candidate_only": bool(raw.get("candidate_only", True)),
        "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
        "source_path": source_path,
        "search_text": " ".join(
            str(part)
            for part in (
                candidate_id,
                label,
                raw.get("from_candidate_id"),
                raw.get("to_candidate_id"),
                raw.get("notes"),
            )
            if part
        ),
    }


def _major_point_items(
    root: Path,
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    named_points = _load_named_points(root, project, report)
    support_rows = _load_support_rows(root, project, report)
    support_by_id = {str(row.get("mcp_id")): row for row in support_rows if row.get("mcp_id")}

    ref = str(project.get("mcp_candidates_ref") or "outputs/mcp/mcp_candidates.json")
    payload = _load_json_object(_project_path(root, ref))
    candidates = payload.get("mcp_candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        mcp_id = str(raw.get("mcp_id") or "")
        support = support_by_id.get(mcp_id, {})
        nearest_cp = raw.get("nearest_scout_cp")
        if not isinstance(nearest_cp, dict):
            nearest_cp = support.get("nearest_scout_cp") if isinstance(support, dict) else {}
        score_components = raw.get("score_components") if isinstance(raw.get("score_components"), dict) else {}
        linked_named_points = [
            named_points.get(str(point_id), {})
            for point_id in raw.get("linked_named_points", [])
            if str(point_id) in named_points
        ]
        aliases = []
        for point in linked_named_points:
            aliases.extend(point.get("aliases", []) if isinstance(point.get("aliases"), list) else [])
        label = str(raw.get("label") or mcp_id)
        items.append(
            {
                "evidence_type": "major_point",
                "candidate_id": mcp_id,
                "label": label,
                "point_classes": raw.get("mcp_classes", []),
                "aliases": aliases,
                "lat": _optional_float(raw.get("lat")),
                "lon": _optional_float(raw.get("lon")),
                "distance_m": _optional_float(raw.get("distance_m")),
                "distance_km": _km(raw.get("distance_m")),
                "nearest_cp_candidate_id": nearest_cp.get("candidate_id") if isinstance(nearest_cp, dict) else None,
                "nearest_cp_distance_m": _optional_float(nearest_cp.get("distance_m")) if isinstance(nearest_cp, dict) else None,
                "linked_cp_candidates": raw.get("linked_cp_candidates", []),
                "linked_named_points": raw.get("linked_named_points", []),
                "support_status": support.get("support_status") if isinstance(support, dict) else None,
                "review_state": raw.get("review_state"),
                "review_required": bool(support.get("review_required", True)) if isinstance(support, dict) else True,
                "score": _optional_float(score_components.get("total")),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": ref,
                "search_text": " ".join(
                    str(part)
                    for part in (
                        mcp_id,
                        label,
                        " ".join(raw.get("mcp_classes", [])),
                        " ".join(raw.get("linked_cp_candidates", [])),
                        " ".join(aliases),
                        support.get("recommendation") if isinstance(support, dict) else None,
                    )
                    if part
                ),
            }
        )

    for row in support_rows:
        label = str(row.get("label") or row.get("mcp_id") or "")
        items.append(
            {
                "evidence_type": "major_point_cp_support",
                "candidate_id": row.get("mcp_id"),
                "label": label,
                "point_classes": [],
                "distance_m": _optional_float(row.get("distance_m")),
                "distance_km": _km(row.get("distance_m")),
                "nearest_cp_candidate_id": (row.get("nearest_scout_cp") or {}).get("candidate_id")
                if isinstance(row.get("nearest_scout_cp"), dict)
                else None,
                "linked_cp_candidates": row.get("linked_cp_candidates", []),
                "support_status": row.get("support_status"),
                "review_required": bool(row.get("review_required", True)),
                "candidate_only": bool(row.get("candidate_only", True)),
                "runtime_safety_truth": bool(row.get("runtime_safety_truth", False)),
                "source_path": str(project.get("mcp_cp_support_reconciliation_ref") or "outputs/mcp/mcp_cp_support_reconciliation.json"),
                "search_text": " ".join(
                    str(part)
                    for part in (
                        row.get("mcp_id"),
                        label,
                        " ".join(row.get("linked_cp_candidates", [])),
                        row.get("recommendation"),
                    )
                    if part
                ),
            }
        )

    for point in named_points.values():
        route_position = point.get("route_position") if isinstance(point.get("route_position"), dict) else {}
        label = str(point.get("canonical_name") or point.get("named_point_id") or "")
        items.append(
            {
                "evidence_type": "named_point",
                "candidate_id": point.get("named_point_id"),
                "label": label,
                "point_classes": point.get("point_class", []),
                "aliases": point.get("aliases", []),
                "lat": _optional_float(route_position.get("lat")),
                "lon": _optional_float(route_position.get("lon")),
                "distance_m": _optional_float(route_position.get("distance_m")),
                "distance_km": _km(route_position.get("distance_m")),
                "nearest_cp_candidate_id": point.get("nearest_cp_candidate_id"),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": str(project.get("mcp_named_point_evidence_ref") or "outputs/mcp/named_point_evidence.json"),
                "search_text": " ".join(
                    str(part)
                    for part in (
                        point.get("named_point_id"),
                        label,
                        " ".join(point.get("aliases", [])),
                        " ".join(point.get("point_class", [])),
                    )
                    if part
                ),
            }
        )

    items.extend(_ocr_label_point_items(root, project, named_points, report))
    report.append(
        {
            "source_kind": "mcp_candidates",
            "status": "loaded" if candidates else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(candidates),
        }
    )
    return items, report


def _load_named_points(
    root: Path,
    project: dict[str, Any],
    report: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    ref = str(project.get("mcp_named_point_evidence_ref") or "outputs/mcp/named_point_evidence.json")
    payload = _load_json_object(_project_path(root, ref))
    points = payload.get("named_points") if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    report.append(
        {
            "source_kind": "named_point_evidence",
            "status": "loaded" if points else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(points),
        }
    )
    return {
        str(point.get("named_point_id")): point
        for point in points
        if isinstance(point, dict) and point.get("named_point_id")
    }


def _load_support_rows(
    root: Path,
    project: dict[str, Any],
    report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = str(project.get("mcp_cp_support_reconciliation_ref") or "outputs/mcp/mcp_cp_support_reconciliation.json")
    payload = _load_json_object(_project_path(root, ref))
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    report.append(
        {
            "source_kind": "mcp_cp_support_reconciliation",
            "status": "loaded" if rows else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(rows),
        }
    )
    return [row for row in rows if isinstance(row, dict)]


def _ocr_label_point_items(
    root: Path,
    project: dict[str, Any],
    named_points: dict[str, dict[str, Any]],
    report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = str(project.get("mcp_ocr_labels_ref") or "outputs/mcp/mcp_ocr_labels.json")
    payload = _load_json_object(_project_path(root, ref))
    labels = payload.get("labels") if isinstance(payload, dict) else []
    if not isinstance(labels, list):
        labels = []
    items = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        named_point = named_points.get(str(label.get("named_point_id") or ""), {})
        route_position = named_point.get("route_position") if isinstance(named_point.get("route_position"), dict) else {}
        text = str(label.get("label_text") or label.get("ocr_label_id") or "")
        items.append(
            {
                "evidence_type": "ocr_label",
                "candidate_id": label.get("ocr_label_id"),
                "label": text,
                "label_text": text,
                "point_classes": ["ocr_label"],
                "lat": _optional_float(route_position.get("lat")),
                "lon": _optional_float(route_position.get("lon")),
                "distance_m": _optional_float(route_position.get("distance_m")),
                "distance_km": _km(route_position.get("distance_m")),
                "named_point_id": label.get("named_point_id"),
                "source_ref": label.get("source_ref"),
                "confidence": _optional_float(label.get("confidence")),
                "review_required": bool(label.get("review_required", True)),
                "candidate_only": bool(label.get("candidate_only", True)),
                "runtime_safety_truth": False,
                "source_path": ref,
                "search_text": " ".join(
                    str(part)
                    for part in (
                        text,
                        label.get("ocr_label_id"),
                        label.get("source_ref"),
                        label.get("named_point_id"),
                        named_point.get("canonical_name") if isinstance(named_point, dict) else None,
                    )
                    if part
                ),
            }
        )
    report.append(
        {
            "source_kind": "mcp_ocr_labels",
            "status": "loaded" if labels else "missing_or_empty",
            "source_path": ref,
            "loaded_count": len(labels),
        }
    )
    return items


def _load_project_list(
    root: Path,
    project: dict[str, Any],
    ref_key: str,
) -> tuple[list[Any], str]:
    ref = str(project.get(ref_key) or "")
    payload = _load_json_object(_project_path(root, ref))
    if isinstance(payload, list):
        return payload, ref
    if isinstance(payload, dict):
        for key in ("candidates", "items", "segments", "checkpoints", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value, ref
    return [], ref


def _compact_route_summary(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "route_name": route.get("route_name"),
        "artifact_id": route.get("artifact_id"),
        "distance_m": _optional_float(route.get("distance_m")),
        "distance_km": _km(route.get("distance_m")),
        "elevation_min_m": _optional_float(route.get("elevation_min_m")),
        "elevation_max_m": _optional_float(route.get("elevation_max_m")),
        "point_count": route.get("point_count"),
        "started_at": route.get("started_at"),
        "ended_at": route.get("ended_at"),
        "bbox_wgs84": route.get("bbox_wgs84"),
    }


def _related_count_keys(project: dict[str, Any], ref_key: str) -> dict[str, Any]:
    prefix = ref_key.removesuffix("_ref")
    related: dict[str, Any] = {}
    for key, value in project.items():
        if key.endswith("_count") and (key.startswith(prefix) or prefix.startswith(key.removesuffix("_count"))):
            related[key] = value
    if not related:
        compact = prefix.replace("_candidates", "").replace("_candidate", "")
        for key, value in project.items():
            if key.endswith("_count") and compact and compact in key:
                related[key] = value
    return related


def _domain_for_ref(key: str, value: str) -> str:
    text = f"{key} {value}".lower()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(hint.lower() in text for hint in hints):
            return domain
    if "review" in text:
        return "review"
    if "runtime" in text or "debug" in text:
        return "runtime"
    return "workspace"


def _normalize_domains(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _domains_from_query(query: str) -> set[str]:
    lowered = query.lower()
    domains = set()
    for domain, hints in _DOMAIN_HINTS.items():
        if any(hint.lower() in lowered for hint in hints):
            domains.add(domain)
    return domains


def _looks_candidate_key(key: str, value: str) -> bool:
    lowered = f"{key} {value}".lower()
    return any(fragment in lowered for fragment in ("candidate", "proposal", "draft", "review_queue"))


def _catalog_match_score(item: dict[str, Any], terms: set[str], raw_query: str) -> float:
    score = _text_match_score(str(item.get("search_text") or ""), terms, raw_query)
    if item["exists"]:
        score += 0.25
    return score


def _item_references_cp(item: dict[str, Any], cp: str) -> bool:
    normalized = _normalize_cp_id(cp)
    values = {
        _normalize_cp_id(str(item.get("candidate_id") or "")),
        _normalize_cp_id(str(item.get("from_candidate_id") or "")),
        _normalize_cp_id(str(item.get("to_candidate_id") or "")),
        _normalize_cp_id(str(item.get("nearest_cp_candidate_id") or "")),
    }
    linked = item.get("linked_cp_candidates")
    if isinstance(linked, list):
        values.update(_normalize_cp_id(str(value)) for value in linked)
    return normalized in values


def _parse_cp(query: str) -> str | None:
    match = re.search(r"\bcp[ ._-]*(start|\d{1,3})\b", query, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"CP\s*(start|\d{1,3})", query, flags=re.IGNORECASE)
    if not match:
        return None
    return _normalize_cp_id(f"cp.{match.group(1)}")


def _parse_segment(query: str) -> str | None:
    match = re.search(r"\bseg(?:ment)?[ ._-]*(\d{1,3})\b", query, flags=re.IGNORECASE)
    if not match:
        return None
    return f"seg.{int(match.group(1)):03d}"


def _normalize_cp_id(value: str) -> str:
    lowered = value.strip().lower().replace("_", ".").replace("-", ".").replace(" ", "")
    if lowered in {"start", "cpstart", "cp.start"}:
        return "cp.start"
    match = re.search(r"cp\.?(\d{1,3})", lowered)
    if match:
        return f"cp.{int(match.group(1)):03d}"
    return lowered


def _query_terms(query: str) -> set[str]:
    lowered = query.lower()
    raw_terms = re.findall(r"[a-z0-9_./-]+|[\u4e00-\u9fff]{2,}", lowered)
    terms = set()
    for term in raw_terms:
        stripped = term.strip(" ?!,:;，。！？：；()[]{}")
        if not stripped or stripped in _GENERIC_TERMS:
            continue
        if stripped.startswith("cp") or stripped.startswith("seg"):
            continue
        terms.add(stripped)
        if re.search(r"[\u4e00-\u9fff]", stripped) and len(stripped) > 2:
            for size in range(2, min(4, len(stripped)) + 1):
                for start in range(0, len(stripped) - size + 1):
                    ngram = stripped[start : start + size]
                    if ngram not in _GENERIC_TERMS:
                        terms.add(ngram)
    return terms


def _text_match_score(text: str, terms: set[str], raw_query: str) -> float:
    lowered = text.lower()
    score = 0.0
    if raw_query and raw_query.lower().strip() in lowered:
        score += 8.0
    for term in terms:
        if term in lowered:
            score += 4.0 if re.search(r"[\u4e00-\u9fff]", term) else 2.0
    return score


def _project_path(root: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return root / path


def _load_json_object(path: Path) -> Any:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _km(value: Any) -> float | None:
    number = _optional_float(value)
    if number is None:
        return None
    return round(number / 1000.0, 3)


def _bounded_limit(value: int | None) -> int:
    if not isinstance(value, int):
        return DEFAULT_WORKSPACE_SEARCH_LIMIT
    return max(1, min(value, MAX_WORKSPACE_SEARCH_LIMIT))


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "offline_only": True,
        "local_evidence_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
    }
