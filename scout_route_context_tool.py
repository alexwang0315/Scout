from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


ROUTE_CONTEXT_TOOL_ID = "scout.ai.route_context.assess.v0"
ROUTE_CONTEXT_OUTPUT_KIND = "scout_ai_route_context_tool_output"
ROUTE_CONTEXT_REQUIRED_FIELDS = ("project_root",)
ROUTE_CONTEXT_OPTIONAL_FIELDS = (
    "context_types",
    "cp",
    "distance_m_min",
    "distance_m_max",
    "route_context_path",
    "spatial_imprints_path",
    "rest_area_candidates_path",
    "mcp_candidates_path",
    "named_point_evidence_path",
)

DEFAULT_ROUTE_CONTEXT_LIMIT = 6
MAX_ROUTE_CONTEXT_LIMIT = 16


def assess_scout_route_context(
    project_root: Path | str,
    *,
    query: str = "",
    context_types: list[str] | None = None,
    cp: str | None = None,
    distance_m_min: float | int | str | None = None,
    distance_m_max: float | int | str | None = None,
    route_context_path: str | None = None,
    spatial_imprints_path: str | None = None,
    rest_area_candidates_path: str | None = None,
    mcp_candidates_path: str | None = None,
    named_point_evidence_path: str | None = None,
    limit: int = DEFAULT_ROUTE_CONTEXT_LIMIT,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    resolved_limit = _bounded_limit(limit)
    resolved_context_types = _normalize_context_types(context_types)
    query_terms = _query_terms(query)
    hints = _context_hints(query)
    distance_min = _float_or_none(distance_m_min)
    distance_max = _float_or_none(distance_m_max)

    items: list[dict[str, Any]] = []
    source_report: list[dict[str, Any]] = []
    route_context_items = _route_context_point_items(
        root,
        project,
        explicit_path=route_context_path,
        source_report=source_report,
    )
    items.extend(route_context_items)
    mcp_explicit_path = mcp_candidates_path
    if mcp_explicit_path is None and route_context_path and not route_context_items:
        mcp_explicit_path = route_context_path
    if not route_context_items or mcp_candidates_path:
        items.extend(
            _mcp_items(
                root,
                project,
                explicit_path=mcp_explicit_path,
                source_report=source_report,
            )
        )
    if not route_context_items or named_point_evidence_path:
        items.extend(
            _named_point_items(
                root,
                project,
                explicit_path=named_point_evidence_path,
                source_report=source_report,
            )
        )
    items.extend(
        _spatial_imprint_items(
            root,
            project,
            explicit_path=spatial_imprints_path,
            source_report=source_report,
        )
    )
    items.extend(
        _rest_area_items(
            root,
            project,
            explicit_path=rest_area_candidates_path,
            source_report=source_report,
        )
    )

    filtered: list[dict[str, Any]] = []
    generic_route_context_query = _looks_like_generic_route_context_query(query)
    for item in items:
        if resolved_context_types and str(item["context_kind"]) not in resolved_context_types:
            continue
        if cp and not _item_references_cp(item, cp):
            continue
        distance = _float_or_none(item.get("distance_m"))
        if distance_min is not None and (distance is None or distance < distance_min):
            continue
        if distance_max is not None and (distance is None or distance > distance_max):
            continue
        score = _score_item(item, query_terms=query_terms, hints=hints)
        if query_terms and score <= 0 and not generic_route_context_query:
            continue
        filtered.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"search_text", "class_terms"}
            }
            | {"match_score": round(score, 3)}
        )

    filtered.sort(
        key=lambda item: (
            -float(item.get("match_score") or 0.0),
            -float(item.get("experience_score") or 0.0),
            float(item.get("distance_m") or math.inf),
            str(item.get("label") or item.get("candidate_id")),
        )
    )
    results = filtered[:resolved_limit]
    answerability = (
        "route_context_available" if results else "route_context_missing_evidence"
    )
    return {
        "tool_id": ROUTE_CONTEXT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_route_context",
        "answerability": answerability,
        "source_status": "candidate_only",
        "filters": {
            "context_types": sorted(resolved_context_types) if resolved_context_types else None,
            "cp": cp,
            "distance_m_min": distance_min,
            "distance_m_max": distance_max,
            "query_terms": sorted(query_terms),
            "context_hints": sorted(hints),
        },
        "field_answer": _field_answer(results, answerability=answerability),
        "route_context": {
            "role": "Experience Guide",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "top_context_points": results[:3],
            "stop_permission_required": True,
            "stop_permission_tool_id": "scout.ai.contextual_permission.assess.v0",
        },
        "summaries": _summaries(items, filtered),
        "source_report": source_report,
        "searched_context_count": len(items),
        "matched_context_count": len(filtered),
        "result_count": len(results),
        "results": results,
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 6 Route Context Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.3 Experience Guide",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.2 suggested stop points",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 20.2 Route Context Intelligence updates",
        ],
        "boundary": _closed_boundary(),
    }


def _route_context_point_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(project.get("route_context_points_ref") or "candidates/route_context_points.json")
    payload, source_path = _load_project_json(root, ref)
    points = payload.get("points") if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    source_report.append(
        _source_report("route_context_points", source_path, len(points))
    )
    items = []
    for raw in points:
        if not isinstance(raw, dict):
            continue
        sec6_layers = _str_list(raw.get("sec6_layers"))
        evidence_families = _str_list(raw.get("evidence_families"))
        classes = sec6_layers + evidence_families
        context_kind = str(raw.get("context_kind") or _context_kind(classes, label=raw.get("label")))
        label = str(raw.get("display_label") or raw.get("label") or raw.get("candidate_id") or "")
        items.append(
            {
                "evidence_type": raw.get("evidence_type") or "route_context_point",
                "context_kind": context_kind,
                "candidate_id": raw.get("candidate_id"),
                "label": label,
                "distance_m": _float_or_none(raw.get("distance_m")),
                "lat": _float_or_none(raw.get("lat")),
                "lon": _float_or_none(raw.get("lon")),
                "nearest_cp_candidate_id": raw.get("nearest_cp_candidate_id"),
                "point_classes": classes,
                "review_state": raw.get("review_state"),
                "confidence": raw.get("confidence"),
                "experience_score": _experience_score(context_kind, classes, raw),
                "guidance": _guidance_for(context_kind, label),
                "stop_guidance": _stop_guidance_for(context_kind),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": source_path,
                "source_gaps": raw.get("reference_gaps", []),
                "source_refs": _source_refs(raw),
                "class_terms": classes,
                "search_text": _search_text(
                    label,
                    raw.get("candidate_id"),
                    raw.get("source_candidate_id"),
                    raw.get("context_kind"),
                    sec6_layers,
                    evidence_families,
                    raw.get("reference_gaps"),
                ),
            }
        )
    return items


def _mcp_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(project.get("mcp_candidates_ref") or "outputs/mcp/mcp_candidates.json")
    payload, source_path = _load_project_json(root, ref)
    candidates = payload.get("mcp_candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    source_report.append(
        _source_report("mcp_candidates", source_path, len(candidates))
    )
    items = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        classes = _str_list(raw.get("mcp_classes"))
        context_kind = _context_kind(classes, label=raw.get("label"))
        nearest_cp = raw.get("nearest_scout_cp")
        nearest_cp = nearest_cp if isinstance(nearest_cp, dict) else {}
        label = str(raw.get("label") or raw.get("mcp_id") or "")
        items.append(
            {
                "evidence_type": "major_critical_point",
                "context_kind": context_kind,
                "candidate_id": raw.get("mcp_id"),
                "label": label,
                "distance_m": _float_or_none(raw.get("distance_m")),
                "lat": _float_or_none(raw.get("lat")),
                "lon": _float_or_none(raw.get("lon")),
                "nearest_cp_candidate_id": nearest_cp.get("candidate_id"),
                "point_classes": classes,
                "review_state": raw.get("review_state"),
                "confidence": raw.get("confidence"),
                "experience_score": _experience_score(context_kind, classes, raw),
                "guidance": _guidance_for(context_kind, label),
                "stop_guidance": _stop_guidance_for(context_kind),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": source_path,
                "source_gaps": raw.get("missing_source_gaps", []),
                "source_refs": _source_refs(raw),
                "class_terms": classes,
                "search_text": _search_text(
                    label,
                    raw.get("mcp_id"),
                    classes,
                    raw.get("promotion_reasons"),
                    raw.get("missing_source_gaps"),
                ),
            }
        )
    return items


def _named_point_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(project.get("mcp_named_point_evidence_ref") or "outputs/mcp/named_point_evidence.json")
    payload, source_path = _load_project_json(root, ref)
    points = payload.get("named_points") if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    source_report.append(
        _source_report("named_point_evidence", source_path, len(points))
    )
    items = []
    for raw in points:
        if not isinstance(raw, dict):
            continue
        classes = _str_list(raw.get("point_class"))
        context_kind = _context_kind(classes, label=raw.get("canonical_name"))
        route_position = raw.get("route_position")
        route_position = route_position if isinstance(route_position, dict) else {}
        label = str(raw.get("canonical_name") or raw.get("named_point_id") or "")
        aliases = _str_list(raw.get("aliases"))
        items.append(
            {
                "evidence_type": "named_point",
                "context_kind": context_kind,
                "candidate_id": raw.get("named_point_id"),
                "label": label,
                "aliases": aliases,
                "distance_m": _float_or_none(route_position.get("distance_m")),
                "lat": _float_or_none(route_position.get("lat")),
                "lon": _float_or_none(route_position.get("lon")),
                "nearest_cp_candidate_id": raw.get("nearest_cp_candidate_id"),
                "point_classes": classes,
                "confidence": route_position.get("coordinate_confidence"),
                "experience_score": _experience_score(context_kind, classes, raw),
                "guidance": _guidance_for(context_kind, label),
                "stop_guidance": _stop_guidance_for(context_kind),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": source_path,
                "source_gaps": raw.get("missing_source_families", []),
                "source_refs": _source_refs(raw),
                "class_terms": classes + aliases,
                "search_text": _search_text(
                    label,
                    raw.get("named_point_id"),
                    aliases,
                    classes,
                    raw.get("source_families"),
                ),
            }
        )
    return items


def _spatial_imprint_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(project.get("spatial_imprint_candidates_ref") or project.get("spatial_imprint_set_ref") or "candidates/spatial_imprints.json")
    payload, source_path = _load_project_json(root, ref)
    imprints = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(imprints, list):
        imprints = payload.get("imprints") if isinstance(payload, dict) else []
    if not isinstance(imprints, list):
        imprints = []
    source_report.append(
        _source_report("spatial_imprints", source_path, len(imprints))
    )
    items = []
    for raw in imprints:
        if not isinstance(raw, dict):
            continue
        payload_obj = raw.get("payload")
        payload_obj = payload_obj if isinstance(payload_obj, dict) else {}
        anchor = raw.get("anchor")
        anchor = anchor if isinstance(anchor, dict) else {}
        coordinate = anchor.get("coordinate")
        coordinate = coordinate if isinstance(coordinate, dict) else {}
        kind = str(raw.get("kind") or "")
        context_kind = _context_kind([kind, str(raw.get("severity") or "")], label=raw.get("label"))
        label = str(raw.get("label") or raw.get("imprint_id") or "")
        text = str(payload_obj.get("text_zh") or payload_obj.get("text") or "")
        items.append(
            {
                "evidence_type": "spatial_imprint",
                "context_kind": context_kind,
                "candidate_id": raw.get("imprint_id"),
                "label": label,
                "distance_m": _float_or_none(anchor.get("distance_m")),
                "lat": _float_or_none(coordinate.get("lat")),
                "lon": _float_or_none(coordinate.get("lon")),
                "nearest_cp_candidate_id": anchor.get("cp_ref"),
                "segment_ref": anchor.get("segment_ref"),
                "point_classes": [kind],
                "severity": raw.get("severity"),
                "experience_score": _experience_score(context_kind, [kind], raw),
                "guidance": text or _guidance_for(context_kind, label),
                "stop_guidance": _stop_guidance_for(context_kind),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": source_path,
                "source_refs": _source_refs(raw),
                "class_terms": [kind, str(raw.get("severity") or "")],
                "search_text": _search_text(label, raw.get("imprint_id"), kind, text),
            }
        )
    return items


def _rest_area_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(project.get("rest_area_candidates_ref") or "outputs/rest_area_candidates.json")
    payload, source_path = _load_project_json(root, ref)
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    source_report.append(
        _source_report("rest_area_candidates", source_path, len(candidates))
    )
    items = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("candidate_id") or "")
        items.append(
            {
                "evidence_type": "rest_area_candidate",
                "context_kind": "rest_area",
                "candidate_id": raw.get("candidate_id"),
                "label": label,
                "distance_m": None,
                "route_point_index": raw.get("route_point_index"),
                "lat": _float_or_none(raw.get("lat")),
                "lon": _float_or_none(raw.get("lon")),
                "nearest_cp_candidate_id": raw.get("checkpoint_candidate_id"),
                "point_classes": ["rest_area"],
                "review_state": raw.get("review_state"),
                "confidence": raw.get("confidence"),
                "duration_seconds": _float_or_none(raw.get("duration_seconds")),
                "experience_score": 8.0,
                "guidance": "候選休息或停留區；只作行前脈絡，不代表現場可停留。",
                "stop_guidance": "若要實際停留，仍需用 contextual permission 計算可停多久與何時離開。",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "source_path": source_path,
                "source_refs": _source_refs(raw),
                "class_terms": ["rest_area", "stop", "lunch", "休息", "停留"],
                "search_text": _search_text(
                    label,
                    raw.get("candidate_id"),
                    raw.get("checkpoint_candidate_id"),
                    "rest area stop lunch 休息 停留 午餐",
                ),
            }
        )
    return items


def _context_kind(classes: list[str], *, label: Any) -> str:
    text = _normalize(" ".join(classes + [str(label or "")]))
    if _has_any(text, ("viewpoint", "view", "pass", "景", "啞口", "拍")):
        return "viewpoint"
    if _has_any(text, ("water", "camp", "hut", "保線所", "水塘", "營地", "山屋")):
        return "resource_context"
    if _has_any(text, ("fork", "junction", "turn", "guidance", "叉路", "轉彎")):
        return "navigation_context"
    if _has_any(text, ("hazard", "risk", "warning", "collapse", "exposure", "崩", "裸露")):
        return "risk_context"
    if _has_any(text, ("forest", "林", "自然", "植被", "溪")):
        return "natural_context"
    if _has_any(text, ("communication", "通訊")):
        return "communication_context"
    return "route_context"


def _guidance_for(context_kind: str, label: str) -> str:
    if context_kind == "viewpoint":
        return f"{label} 是候選觀景或拍攝脈絡點；是否停留仍需看時間、天氣與風險預算。"
    if context_kind == "resource_context":
        return f"{label} 提供水源、營地、山屋或保線所等路線資源脈絡，需以審核資料確認。"
    if context_kind == "navigation_context":
        return f"{label} 是路線辨識脈絡點，通過前應確認方向與隊伍位置。"
    if context_kind == "risk_context":
        return f"{label} 是風險脈絡點，不應被當作打卡或長時間停留點。"
    return f"{label} 是候選路線脈絡點，適合行前理解，不是現場安全保證。"


def _stop_guidance_for(context_kind: str) -> str:
    if context_kind == "risk_context":
        return "不建議為觀察或拍攝停留；若必須通過，應縮短暴露時間。"
    if context_kind == "viewpoint":
        return "可能適合短暫觀察或拍攝，但必須另行計算停留風險預算。"
    if context_kind == "rest_area":
        return "候選可休息點；現場是否可停留仍需 contextual permission。"
    return "可作行前脈絡參考；現場停留需另行授權。"


def _experience_score(context_kind: str, classes: list[str], raw: dict[str, Any]) -> float:
    base = {
        "viewpoint": 25.0,
        "resource_context": 22.0,
        "navigation_context": 18.0,
        "natural_context": 16.0,
        "communication_context": 12.0,
        "risk_context": 10.0,
        "rest_area": 8.0,
        "route_context": 6.0,
    }.get(context_kind, 0.0)
    score_components = raw.get("score_components")
    if isinstance(score_components, dict):
        total = _float_or_none(score_components.get("total"))
        if total is not None:
            base += min(total, 100.0) / 10.0
    if _has_any(_normalize(" ".join(classes)), ("viewpoint", "water", "camp", "hut")):
        base += 3.0
    return round(base, 3)


def _score_item(
    item: dict[str, Any],
    *,
    query_terms: set[str],
    hints: set[str],
) -> float:
    text = _normalize(str(item.get("search_text") or ""))
    query_blob = _normalize("".join(sorted(query_terms)))
    score = 0.0
    for term in query_terms:
        if _normalize(term) in text:
            score += 4.0
    label = _normalize(item.get("label"))
    if label and label in query_blob:
        score += 10.0
    candidate_id = _normalize(item.get("candidate_id"))
    if candidate_id and candidate_id in query_blob:
        score += 6.0
    context_kind = str(item.get("context_kind") or "")
    class_terms = {_normalize(term) for term in _str_list(item.get("class_terms"))}
    if hints:
        if context_kind in hints:
            score += 8.0
        if class_terms & hints:
            score += 4.0
    if not query_terms and not hints:
        score += 1.0
    score += min(float(item.get("experience_score") or 0.0), 30.0) / 10.0
    return score


def _context_hints(query: str) -> set[str]:
    text = _normalize(query)
    hints: set[str] = set()
    if _has_any(text, ("拍", "景", "觀察", "view", "photo", "video")):
        hints.add("viewpoint")
    if _has_any(text, ("休息", "停留", "午餐", "rest", "lunch", "stop")):
        hints.add("rest_area")
    if _has_any(text, ("水", "山屋", "營地", "保線所", "resource", "hut", "camp")):
        hints.add("resource_context")
    if _has_any(text, ("文化", "歷史", "故事", "地名", "遺構", "context")):
        hints.add("route_context")
        hints.add("resource_context")
    if _has_any(text, ("岔路", "方向", "轉彎", "導航")):
        hints.add("navigation_context")
    return hints


def _looks_like_generic_route_context_query(query: str) -> bool:
    text = _normalize(query)
    return _has_any(
        text,
        (
            "值得看",
            "看什麼",
            "觀察點",
            "適合拍",
            "哪裡拍",
            "下一個觀察",
            "地名故事",
            "路線脈絡",
            "routecontext",
            "experienceguide",
        ),
    )


def _field_answer(results: list[dict[str, Any]], *, answerability: str) -> str:
    if not results:
        return (
            "目前缺少可用的路線脈絡候選資料。不要為拍攝或觀察臨時改線；"
            "請先查明 CP、風險預算與路線資料。"
        )
    top = results[:3]
    parts = []
    for item in top:
        label = str(item.get("label") or item.get("candidate_id"))
        kind = str(item.get("context_kind") or "route_context")
        distance = _float_or_none(item.get("distance_m"))
        distance_text = f"，約 {distance / 1000:.1f} km" if distance and distance > 1000 else ""
        parts.append(f"{label}（{kind}{distance_text}）")
    return (
        "候選路線脈絡："
        + "、".join(parts)
        + "。這些只代表行前 Experience Guide 候選，不是現場停留授權；"
        "若要停留或拍攝，仍需用 contextual permission 判斷最多多久與何時離開。"
    )


def _summaries(items: list[dict[str, Any]], filtered: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_evidence_type: dict[str, int] = {}
    for item in items:
        by_kind[str(item.get("context_kind") or "unknown")] = (
            by_kind.get(str(item.get("context_kind") or "unknown"), 0) + 1
        )
        by_evidence_type[str(item.get("evidence_type") or "unknown")] = (
            by_evidence_type.get(str(item.get("evidence_type") or "unknown"), 0) + 1
        )
    return {
        "context_kind_counts": dict(sorted(by_kind.items())),
        "evidence_type_counts": dict(sorted(by_evidence_type.items())),
        "matched_context_count": len(filtered),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _load_project_json(root: Path, ref: str) -> tuple[dict[str, Any], str]:
    path = _project_path(root, ref)
    payload = _load_json_object(path)
    return payload, ref


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _source_report(source_kind: str, source_path: str, count: int) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "status": "loaded" if count else "missing_or_empty",
        "source_path": source_path,
        "loaded_count": count,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _source_refs(raw: dict[str, Any]) -> list[dict[str, Any]]:
    refs = raw.get("source_refs")
    if not isinstance(refs, list):
        return []
    return [ref for ref in refs if isinstance(ref, dict)][:5]


def _item_references_cp(item: dict[str, Any], cp: str) -> bool:
    normalized = _normalize(cp)
    return normalized in {
        _normalize(item.get("nearest_cp_candidate_id")),
        _normalize(item.get("segment_ref")),
        _normalize(item.get("candidate_id")),
    } or normalized in _normalize(item.get("search_text"))


def _normalize_context_types(values: list[str] | None) -> set[str]:
    return {_normalize(value) for value in (values or []) if str(value).strip()}


def _query_terms(query: str) -> set[str]:
    terms = {
        term
        for term in re.split(r"[\s,，。？?、/()（）:：]+", str(query or "").lower())
        if len(term.strip()) >= 2
    }
    return {term for term in terms if term not in {"哪裡", "可以", "這裡", "什麼"}}


def _search_text(*parts: Any) -> str:
    text_parts: list[str] = []
    for part in parts:
        if isinstance(part, list):
            text_parts.extend(str(item) for item in part)
        elif part is not None:
            text_parts.append(str(part))
    return " ".join(text_parts)


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _bounded_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_ROUTE_CONTEXT_LIMIT
    return max(1, min(parsed, MAX_ROUTE_CONTEXT_LIMIT))


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _has_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment.lower().replace(" ", "") in text for fragment in fragments)


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "candidate_only": True,
        "model_output_is_runtime_truth": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "hardware_control_performed": False,
        "workspace_file_write_allowed": False,
        "raw_payloads_embedded": False,
    }
