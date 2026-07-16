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
    "route_briefing_path",
    "spatial_imprints_path",
    "rest_area_candidates_path",
    "mcp_candidates_path",
    "named_point_evidence_path",
    "route_mileage_k_anchors_path",
    "mileage_tag_alignment_path",
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
    route_briefing_path: str | None = None,
    spatial_imprints_path: str | None = None,
    rest_area_candidates_path: str | None = None,
    mcp_candidates_path: str | None = None,
    named_point_evidence_path: str | None = None,
    route_mileage_k_anchors_path: str | None = None,
    mileage_tag_alignment_path: str | None = None,
    limit: int = DEFAULT_ROUTE_CONTEXT_LIMIT,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    resolved_limit = _bounded_limit(limit)
    resolved_context_types = _normalize_context_types(context_types)
    query_terms = _query_terms(query)
    hints = _context_hints(query)
    requested_mileage_anchors = _mileage_anchor_keys(query)
    distance_min = _float_or_none(distance_m_min)
    distance_max = _float_or_none(distance_m_max)

    items: list[dict[str, Any]] = []
    source_report: list[dict[str, Any]] = []
    route_briefing_payload, route_briefing_source_path = _route_briefing_payload(
        root,
        project,
        explicit_path=route_briefing_path,
        source_report=source_report,
    )
    route_briefing = _route_briefing_summary(
        route_briefing_payload,
        route_briefing_source_path,
    )
    media_manifest = _route_context_media_manifest_summary(root, project)
    items.extend(
        _route_briefing_items(
            route_briefing_payload,
            source_path=route_briefing_source_path,
        )
    )
    route_context_items = _route_context_point_items(
        root,
        project,
        explicit_path=route_context_path,
        source_report=source_report,
    )
    items.extend(route_context_items)
    existing_candidate_ids = {
        str(item.get("candidate_id"))
        for item in route_context_items
        if item.get("candidate_id")
    }
    items.extend(
        _route_mileage_anchor_items(
            root,
            project,
            explicit_path=route_mileage_k_anchors_path,
            existing_candidate_ids=existing_candidate_ids,
            source_report=source_report,
        )
    )
    if requested_mileage_anchors or _looks_like_mileage_tag_query(query):
        items.extend(
            _mileage_tag_alignment_items(
                root,
                project,
                explicit_path=mileage_tag_alignment_path,
                requested_mileage_anchors=requested_mileage_anchors,
                source_report=source_report,
            )
        )
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
        if requested_mileage_anchors and not _item_matches_mileage_anchor(
            item,
            requested_mileage_anchors,
        ):
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
    media_answer = _route_context_media_field_answer(media_manifest, query=query)
    briefing_answer = _route_briefing_field_answer(route_briefing, query=query)
    project_answer, project_answer_source_ref = _route_context_project_field_answer(
        root,
        project,
        route_briefing=route_briefing,
        query=query,
    )
    mileage_answer, mileage_source_ref, mileage_source_refs = (
        _route_mileage_query_field_answer(
            root,
            project,
            query=query,
            requested_mileage_anchors=requested_mileage_anchors,
        )
    )
    answerability = (
        "route_context_available"
        if results or briefing_answer or media_answer or mileage_answer
        else "route_context_missing_evidence"
    )
    field_answer = project_answer or media_answer or briefing_answer or mileage_answer or _field_answer(
        results,
        answerability=answerability,
        requested_mileage_anchors=requested_mileage_anchors,
    )
    field_answer_source_ref = (
        project_answer_source_ref
        if project_answer
        else media_manifest.get("source_ref")
        if media_answer
        else route_briefing.get("source_path")
        if briefing_answer
        else mileage_source_ref
        if mileage_answer
        else results[0].get("source_path")
        if results
        else None
    )
    decision_output = _decision_output(
        results=results,
        answerability=answerability,
        field_answer=field_answer,
    )
    return {
        "tool_id": ROUTE_CONTEXT_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_route_context",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision_output["decision"],
        "decision_output": decision_output,
        "filters": {
            "context_types": sorted(resolved_context_types) if resolved_context_types else None,
            "cp": cp,
            "distance_m_min": distance_min,
            "distance_m_max": distance_max,
            "query_terms": sorted(query_terms),
            "context_hints": sorted(hints),
            "requested_mileage_anchors": sorted(requested_mileage_anchors),
        },
        "field_answer": field_answer,
        "field_answer_priority": 100
        if project_answer or media_answer or briefing_answer or mileage_answer
        else 0,
        "field_answer_source_ref": field_answer_source_ref,
        "field_answer_source_refs": mileage_source_refs
        or ([field_answer_source_ref] if field_answer_source_ref else []),
        "source_ref": field_answer_source_ref,
        "route_briefing": route_briefing,
        "media_manifest": media_manifest,
        "route_context": {
            "role": "Experience Guide",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "route_briefing": route_briefing,
            "decision_output": decision_output,
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


def _route_context_media_manifest_summary(
    root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    ref = str(
        project.get("route_context_media_manifest_ref")
        or "normalized/context/route_context/media_manifest.json"
    )
    payload, source_path = _load_project_json(root, ref)
    raw_images = payload.get("images") if isinstance(payload, dict) else []
    images = raw_images if isinstance(raw_images, list) else []
    license_keys = (
        "license",
        "license_name",
        "license_note",
        "license_url",
        "rights",
        "copyright",
    )
    license_complete = [
        item
        for item in images
        if isinstance(item, dict)
        and any(str(item.get(key) or "").strip() for key in license_keys)
    ]
    available_count = int(payload.get("available_media_count") or len(images))
    missing_count = max(0, available_count - len(license_complete))
    return {
        "available": bool(payload),
        "available_media_count": available_count,
        "anchored_media_count": int(payload.get("anchored_media_count") or 0),
        "selected_media_count": int(
            (
                payload.get("image_curation", {}).get("selected_media_count")
                if isinstance(payload.get("image_curation"), dict)
                else 0
            )
            or 0
        ),
        "license_complete_count": len(license_complete),
        "license_missing_count": missing_count,
        "license_information_complete": available_count > 0 and missing_count == 0,
        "source_ref": source_path,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _route_context_media_field_answer(
    media_manifest: dict[str, Any],
    *,
    query: str,
) -> str | None:
    normalized = _normalize(query)
    if not _has_any(
        normalized,
        ("media manifest", "影像", "圖片", "授權", "license"),
    ):
        return None
    if not media_manifest.get("available"):
        return "Route context media manifest 不存在，無法確認影像與授權資訊。"
    available = media_manifest.get("available_media_count")
    missing = media_manifest.get("license_missing_count")
    anchored = media_manifest.get("anchored_media_count")
    if not available:
        return (
            "Route context media manifest 目前可用影像 0 張、路線錨定影像 0 張；"
            "沒有影像可供授權完整度審查。"
        )
    license_text = (
        "所有可用影像都有明確授權欄位"
        if media_manifest.get("license_information_complete")
        else f"{missing} 張缺少明確授權欄位，授權資訊不完整"
    )
    return (
        f"Route context media manifest 可用影像 {available} 張、"
        f"路線錨定 {anchored} 張；{license_text}。"
    )


def _route_context_project_field_answer(
    root: Path,
    project: dict[str, Any],
    *,
    route_briefing: dict[str, Any],
    query: str,
) -> tuple[str | None, str | None]:
    normalized = _normalize(query)
    if _has_any(
        normalized,
        (
            "briefingartifact",
            "briefing artifact",
            "簡報artifact",
            "簡報檔案",
            "最後產生時間",
        ),
    ):
        ref = str(
            project.get("route_context_briefing_ref")
            or "outputs/briefings/route_context_briefing.html"
        )
        exists = _project_path(root, ref).is_file()
        generated_at = (
            project.get("route_context_briefing_regenerated_at")
            or project.get("route_context_collection_updated_at")
            or route_briefing.get("generated_at")
        )
        return (
            f"Route context briefing artifact {'存在' if exists else '不存在'}："
            f"{ref}；最後產生時間={generated_at or 'unavailable'}。",
            "project.json",
        )
    if _has_any(
        normalized,
        ("source manifest", "來源網域", "抓取時間", "來源domain"),
    ):
        ref = str(
            project.get("route_context_source_manifest_ref")
            or "normalized/context/route_context/source_manifest.json"
        )
        manifest, _ = _load_project_json(root, ref)
        generated_at = manifest.get("generated_at")
        refresh = manifest.get("live_source_refresh_evidence")
        refresh = refresh if isinstance(refresh, dict) else {}
        tiers = manifest.get("source_tiers")
        tiers = tiers if isinstance(tiers, list) else []
        source_ids = [
            str(item.get("source_id"))
            for item in tiers
            if isinstance(item, dict) and item.get("source_id")
        ]
        return (
            f"Source manifest 有 {len(source_ids)} 個 source IDs，但未保存 "
            "URL/domain 或個別 fetched_at；"
            f"generated_at={generated_at or 'unavailable'}；"
            f"live refresh={refresh.get('status') or 'unavailable'}，"
            f"checked_at={refresh.get('checked_at') or 'unavailable'}。",
            ref,
        )
    return None, None


def _route_briefing_payload(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    refs = _route_briefing_refs(project, explicit_path=explicit_path)
    for ref in refs:
        payload, source_path = _load_project_json(root, ref)
        loaded_count = 1 if payload else 0
        if loaded_count:
            payload = _normalize_route_briefing_payload(
                root,
                payload,
                source_path=source_path,
            )
            source_report.append(
                _source_report(
                    _route_briefing_source_kind(payload),
                    source_path,
                    loaded_count,
                )
            )
            return payload, source_path
    source_path = refs[0] if refs else "route_briefing_research_ref"
    source_report.append(_source_report("route_briefing_compose", source_path, 0))
    return {}, source_path


def _route_briefing_refs(
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> list[str]:
    refs: list[str] = []
    for value in (
        explicit_path,
        project.get("route_briefing_research_ref"),
        project.get("route_briefing_compose_ref"),
        project.get("route_briefing_candidate_ref"),
        project.get("pretrip_route_briefing_ref"),
        project.get("route_briefing_ref"),
        project.get("route_context_pack_ref"),
        project.get("route_context_evidence_ref"),
        "normalized/context/route_context/route_briefing_research.json",
        "normalized/context/route_context/route_context_pack.json",
        "normalized/context/route_context/route_context_evidence.json",
        "outputs/briefings/route_briefing_research.json",
    ):
        if not isinstance(value, str) or not value.strip():
            continue
        if value.strip().lower().endswith((".html", ".htm")):
            continue
        if value not in refs:
            refs.append(value)
    return refs


def _normalize_route_briefing_payload(
    root: Path,
    payload: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    artifact_kind = str(payload.get("artifact_kind") or "")
    if artifact_kind == "pretrip_route_context_pack":
        return _route_context_pack_as_briefing_payload(
            root,
            payload,
            source_path=source_path,
        )
    if artifact_kind == "pretrip_route_context_evidence":
        pack_ref = payload.get("route_context_pack_ref")
        if isinstance(pack_ref, str) and pack_ref.strip():
            pack_payload, pack_source_path = _load_project_json(root, pack_ref)
            if pack_payload:
                return _route_context_pack_as_briefing_payload(
                    root,
                    pack_payload,
                    source_path=pack_source_path,
                )
    return payload


def _route_briefing_source_kind(payload: dict[str, Any]) -> str:
    artifact_kind = str(payload.get("artifact_kind") or "")
    if artifact_kind == "scout_route_context_pack_briefing_view":
        return "route_context_pack"
    return "route_briefing_compose"


def _route_context_pack_as_briefing_payload(
    root: Path,
    payload: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    route_summary = payload.get("route_summary")
    route_summary = route_summary if isinstance(route_summary, dict) else {}
    points_ref = str(payload.get("route_context_points_ref") or "candidates/route_context_points.json")
    points_payload, _ = _load_project_json(root, points_ref)
    points = points_payload.get("points") if isinstance(points_payload, dict) else []
    points = [point for point in points if isinstance(point, dict)]
    distance_m = _float_or_none(route_summary.get("distance_m"))
    distance_km = distance_m / 1000 if distance_m is not None else None
    route_name = str(
        route_summary.get("display_name")
        or route_summary.get("route_name")
        or payload.get("project_id")
        or "workspace route"
    )
    briefing_summary = _route_context_pack_summary(route_summary)
    return {
        "artifact_kind": "scout_route_context_pack_briefing_view",
        "project_id": payload.get("project_id"),
        "route_id": route_summary.get("route_id"),
        "title": f"{route_name} route context briefing",
        "generated_at": payload.get("generated_at"),
        "route_summary": {
            "recommended_days": _route_context_recommended_days(distance_km),
            "summary": briefing_summary,
            "current_status": "candidate-only pretrip route context pack",
            "season_note": "季節、天候與山屋狀態必須另以最新來源人工審查。",
            "risk_note": "這是行前 route-context 候選證據，不是 runtime safety truth。",
        },
        "context_layers": _route_context_layers_from_points(points),
        "route_points": _route_points_from_context_points(points),
        "observation_stops": _observation_stops_from_context_points(points),
        "itinerary_options": _itinerary_options_from_route_summary(distance_km),
        "source_refs": _source_refs_from_route_context_pack(root, payload),
        "source_path": source_path,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _route_context_pack_summary(route_summary: dict[str, Any]) -> str:
    distance_m = _float_or_none(route_summary.get("distance_m"))
    elevation_min = _float_or_none(route_summary.get("elevation_min_m"))
    elevation_max = _float_or_none(route_summary.get("elevation_max_m"))
    point_count = route_summary.get("point_count")
    parts = []
    if distance_m is not None:
        parts.append(f"workspace route distance is about {distance_m / 1000:.1f} km")
    if elevation_min is not None and elevation_max is not None:
        parts.append(f"elevation spans about {elevation_min:.0f}-{elevation_max:.0f} m")
    if point_count is not None:
        parts.append(f"{point_count} route samples are represented without embedding raw points")
    return "; ".join(parts) or "workspace route context pack is available"


def _route_context_recommended_days(distance_km: float | None) -> str:
    if distance_km is None:
        return "缺少路線距離，需由領隊審查天數"
    if distance_km >= 45:
        return "2 天 1 夜或 3 天 2 夜；較保守版本優先留給天候、隊伍與拍照停留 buffer"
    if distance_km >= 25:
        return "1 天長程或 2 天 1 夜；需視隊伍腳程與天候審查"
    return "1 天或短程版本；仍需檢查天候、日照與撤退點"


def _itinerary_options_from_route_summary(distance_km: float | None) -> list[dict[str, Any]]:
    if distance_km is None:
        return [
            {
                "label": "待審查版本",
                "schedule": "缺少 route distance，不能自動給天數。",
                "best_for": "補齊路線距離、山屋、天候與隊伍腳程後再決定。",
                "tradeoff": "目前只能作行前討論，不是出發建議。",
            }
        ]
    if distance_km >= 45:
        return [
            {
                "label": "2 天 1 夜",
                "schedule": "常見壓縮版本；需確認天氣、山屋、日照與隊伍腳程都足夠。",
                "best_for": "腳程穩定、裝備完整且不打算長時間停留觀察的隊伍。",
                "tradeoff": "buffer 較少，遇到午後天氣或延誤時要提早啟動撤退條件。",
            },
            {
                "label": "3 天 2 夜",
                "schedule": "較保守版本；把拍照、文化自然觀察與天候 buffer 留在行程內。",
                "best_for": "想做行前簡報式觀察、隊伍腳程差異較大或希望降低摸黑壓力。",
                "tradeoff": "需要更多糧食、住宿與天氣窗口確認。",
            },
            {
                "label": "壓縮版本",
                "schedule": "只應作為人工審查比較項，不應自動採用。",
                "best_for": "已確認所有高風險段、撤退點、天氣與體能條件後才討論。",
                "tradeoff": "對延誤、迷霧、雨後地形與體能下降容錯最低。",
            },
        ]
    return [
        {
            "label": "標準版本",
            "schedule": f"約 {distance_km:.1f} km route，按隊伍腳程安排。",
            "best_for": "一般行前規劃。",
            "tradeoff": "仍需把天候、日照、撤退點與隊伍狀態納入審查。",
        }
    ]


def _route_context_layers_from_points(points: list[dict[str, Any]]) -> dict[str, list[str]]:
    layer_names = {
        "historical": "歷史層",
        "cultural": "文化層",
        "natural": "自然層",
        "terrain": "地形層",
        "seasonal": "季節層",
        "observation_point": "觀察點",
        "route_context": "路線脈絡",
    }
    layers: dict[str, list[str]] = {}
    for point in points:
        label = str(point.get("display_label") or point.get("label") or "").strip()
        if not label:
            continue
        context_kind = str(point.get("context_kind") or "route_context")
        for raw_layer in _str_list(point.get("sec6_layers")):
            layer = layer_names.get(raw_layer, raw_layer)
            lines = layers.setdefault(layer, [])
            if len(lines) >= 5:
                continue
            line = f"{label} ({context_kind})"
            if line not in lines:
                lines.append(line)
    return layers


def _route_points_from_context_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    route_points = []
    for point in points[:12]:
        label = str(point.get("display_label") or point.get("label") or "").strip()
        if not label:
            continue
        context_kind = str(point.get("context_kind") or "route_context")
        route_points.append(
            {
                "name": label,
                "why_it_matters": _guidance_for(context_kind, label),
                "observation_prompt": "行前簡報候選點；現場停留需重新檢查時間、天候、地形與隊伍狀態。",
                "safety_note": _stop_guidance_for(context_kind),
            }
        )
    return route_points


def _observation_stops_from_context_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stops = []
    for point in points:
        context_kind = str(point.get("context_kind") or "route_context")
        sec6_layers = _str_list(point.get("sec6_layers"))
        if context_kind not in {"viewpoint", "natural_context", "route_context"} and "observation_point" not in sec6_layers:
            continue
        label = str(point.get("display_label") or point.get("label") or "").strip()
        if not label:
            continue
        stops.append(
            {
                "name": label,
                "minutes": 3,
                "observe": _guidance_for(context_kind, label),
                "do_not_stop_if": _stop_guidance_for("risk_context")
                if context_kind == "risk_context"
                else "天氣轉壞、能見度差、隊伍拉開、疲勞或撤退時間不足時不要停留。",
            }
        )
        if len(stops) >= 8:
            break
    return stops


def _source_refs_from_route_context_pack(
    root: Path,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    manifest_ref = str(payload.get("source_manifest_ref") or "")
    manifest, _ = _load_project_json(root, manifest_ref) if manifest_ref else ({}, "")
    source_report = manifest.get("source_report") if isinstance(manifest, dict) else []
    if not isinstance(source_report, list):
        return []
    refs = []
    for source in source_report[:8]:
        if not isinstance(source, dict):
            continue
        refs.append(
            {
                "title": source.get("source_kind"),
                "usage": source.get("conclusion_role") or source.get("status"),
                "source_tier": source.get("source_tier"),
                "source_family": source.get("source_kind"),
            }
        )
    return refs


def _route_briefing_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    if not payload:
        return {
            "available": False,
            "source_path": source_path,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "network_calls_made": False,
            "requires_operator_source_review": True,
        }
    route_summary = payload.get("route_summary")
    route_summary = route_summary if isinstance(route_summary, dict) else {}
    return {
        "available": True,
        "title": payload.get("title"),
        "route_id": payload.get("route_id"),
        "project_id": payload.get("project_id"),
        "generated_at": payload.get("generated_at"),
        "recommended_days": route_summary.get("recommended_days"),
        "summary": route_summary.get("summary"),
        "current_status": route_summary.get("current_status"),
        "season_note": route_summary.get("season_note"),
        "risk_note": route_summary.get("risk_note"),
        "context_layers": _bounded_context_layers(payload.get("context_layers")),
        "observation_stops": _bounded_observation_stops(
            payload.get("observation_stops")
        ),
        "itinerary_options": _bounded_itinerary_options(
            payload.get("itinerary_options")
        ),
        "source_refs": _bounded_source_refs(payload.get("source_refs")),
        "source_path": source_path,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "model_output_is_runtime_truth": False,
        "network_calls_made": False,
        "requires_operator_source_review": True,
    }


def _route_briefing_items(
    payload: dict[str, Any],
    *,
    source_path: str,
) -> list[dict[str, Any]]:
    if not payload:
        return []
    if payload.get("artifact_kind") == "scout_route_context_pack_briefing_view":
        return []
    items: list[dict[str, Any]] = []
    source_refs = _bounded_source_refs(payload.get("source_refs"))
    route_points = payload.get("route_points")
    if isinstance(route_points, list):
        for index, raw in enumerate(route_points):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("name") or f"route briefing point {index + 1}")
            guidance = _join_text(
                raw.get("why_it_matters"),
                raw.get("observation_prompt"),
            )
            safety_note = str(raw.get("safety_note") or "")
            classes = [
                "route_briefing",
                "route_point",
                "briefing",
                "行前簡報",
                "路線脈絡",
            ]
            items.append(
                _route_briefing_item(
                    evidence_type="route_briefing_route_point",
                    context_kind=_context_kind(classes, label=label),
                    candidate_id=f"route_briefing_point:{index + 1}",
                    label=label,
                    classes=classes,
                    guidance=guidance or _guidance_for("route_context", label),
                    stop_guidance=safety_note
                    or "這是行前候選路線脈絡，不是現場停留授權。",
                    source_path=source_path,
                    source_refs=source_refs,
                    search_parts=[
                        label,
                        guidance,
                        safety_note,
                        "沿途 歷史 文化 自然 地形 季節觀察 活動簡報",
                    ],
                    experience_score=18.0,
                )
            )

    observation_stops = payload.get("observation_stops")
    if isinstance(observation_stops, list):
        for index, raw in enumerate(observation_stops):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("name") or f"observation stop {index + 1}")
            minutes = _float_or_none(raw.get("minutes"))
            observe = str(raw.get("observe") or "")
            do_not_stop_if = str(raw.get("do_not_stop_if") or "")
            classes = [
                "route_briefing",
                "observation_stop",
                "viewpoint",
                "停3分鐘",
                "停 3 分鐘",
                "三分鐘",
                "值得停",
                "briefing",
            ]
            items.append(
                _route_briefing_item(
                    evidence_type="route_briefing_observation_stop",
                    context_kind="viewpoint",
                    candidate_id=f"route_briefing_stop:{index + 1}",
                    label=label,
                    classes=classes,
                    guidance=observe or f"{label} 是候選 3 分鐘觀察點。",
                    stop_guidance=(
                        f"候選停留 {minutes:g} 分鐘；{do_not_stop_if}"
                        if minutes is not None
                        else do_not_stop_if
                    )
                    or "這是行前候選停留點，不是現場停留授權。",
                    source_path=source_path,
                    source_refs=source_refs,
                    search_parts=[
                        label,
                        observe,
                        do_not_stop_if,
                        "哪些點值得停3分鐘 停三分鐘 observation stop",
                    ],
                    experience_score=26.0,
                )
            )

    context_layers = payload.get("context_layers")
    if isinstance(context_layers, dict):
        for index, (layer_name, layer_items) in enumerate(context_layers.items()):
            lines = _str_list(layer_items)
            classes = [
                "route_briefing",
                "context_layer",
                str(layer_name),
                "歷史",
                "文化",
                "自然",
                "地形",
                "季節",
            ]
            label = str(layer_name)
            items.append(
                _route_briefing_item(
                    evidence_type="route_briefing_context_layer",
                    context_kind=_context_kind(classes, label=label),
                    candidate_id=f"route_briefing_layer:{index + 1}",
                    label=label,
                    classes=classes,
                    guidance="；".join(lines[:3]),
                    stop_guidance="這是行前脈絡層，不是現場停留授權。",
                    source_path=source_path,
                    source_refs=source_refs,
                    search_parts=[
                        label,
                        lines,
                        "沿途有哪些歷史文化自然地形季節觀察",
                    ],
                    experience_score=15.0,
                )
            )

    itinerary_options = payload.get("itinerary_options")
    if isinstance(itinerary_options, list):
        for index, raw in enumerate(itinerary_options):
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or f"itinerary option {index + 1}")
            classes = [
                "route_briefing",
                "itinerary",
                "建議幾天",
                "幾天幾夜",
                "行程版本",
                "briefing",
            ]
            items.append(
                _route_briefing_item(
                    evidence_type="route_briefing_itinerary_option",
                    context_kind="route_context",
                    candidate_id=f"route_briefing_itinerary:{index + 1}",
                    label=label,
                    classes=classes,
                    guidance=_join_text(
                        raw.get("schedule"),
                        raw.get("best_for"),
                        raw.get("tradeoff"),
                    ),
                    stop_guidance="這是行前行程版本建議，不是出發許可或安全結論。",
                    source_path=source_path,
                    source_refs=source_refs,
                    search_parts=[
                        label,
                        raw.get("schedule"),
                        raw.get("best_for"),
                        raw.get("tradeoff"),
                        "奇萊南華建議幾天 行程版本 2天1夜 3天2夜",
                    ],
                    experience_score=20.0,
                )
            )
    return items


def _route_briefing_item(
    *,
    evidence_type: str,
    context_kind: str,
    candidate_id: str,
    label: str,
    classes: list[str],
    guidance: str,
    stop_guidance: str,
    source_path: str,
    source_refs: list[dict[str, Any]],
    search_parts: list[Any],
    experience_score: float,
) -> dict[str, Any]:
    return {
        "evidence_type": evidence_type,
        "context_kind": context_kind,
        "candidate_id": candidate_id,
        "label": label,
        "distance_m": None,
        "lat": None,
        "lon": None,
        "nearest_cp_candidate_id": None,
        "point_classes": classes,
        "review_state": "operator_reviewed_candidate",
        "confidence": "source_manifest_bounded",
        "experience_score": experience_score,
        "guidance": guidance,
        "stop_guidance": stop_guidance,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "source_path": source_path,
        "source_gaps": [],
        "source_refs": source_refs,
        "class_terms": classes,
        "search_text": _search_text(*search_parts, classes),
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
                "label_role": raw.get("label_role"),
                "mileage_anchor_kind": raw.get("mileage_anchor_kind"),
                "mileage_k": _float_or_none(raw.get("mileage_k")),
                "mileage_m": _float_or_none(raw.get("mileage_m")),
                "normalized_mileage_k": raw.get("normalized_mileage_k"),
                "raw_mileage_text": raw.get("raw_mileage_text"),
                "route_mileage_m": _float_or_none(raw.get("route_mileage_m")),
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
                    raw.get("label_role"),
                    raw.get("mileage_anchor_kind"),
                    raw.get("normalized_mileage_k"),
                    raw.get("raw_mileage_text"),
                    raw.get("mileage_k"),
                    raw.get("mileage_m"),
                    raw.get("route_mileage_m"),
                    sec6_layers,
                    evidence_families,
                    raw.get("reference_gaps"),
                ),
            }
        )
    return items


def _route_mileage_anchor_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    existing_candidate_ids: set[str],
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(
        project.get("route_mileage_k_anchors_ref")
        or "candidates/route_mileage_k_anchors.json"
    )
    payload, source_path = _load_project_json(root, ref)
    anchors = payload.get("anchors") if isinstance(payload, dict) else []
    if not isinstance(anchors, list):
        anchors = []
    source_report.append(
        _source_report("route_mileage_k_anchors", source_path, len(anchors))
    )
    items: list[dict[str, Any]] = []
    for raw in anchors:
        if not isinstance(raw, dict):
            continue
        candidate_id = str(raw.get("candidate_id") or "")
        if candidate_id and candidate_id in existing_candidate_ids:
            continue
        label = str(
            raw.get("display_label")
            or raw.get("normalized_mileage_k")
            or raw.get("raw_mileage_text")
            or candidate_id
        )
        source_refs = raw.get("source_refs")
        source_refs = source_refs if isinstance(source_refs, list) else []
        raw_label_examples = raw.get("raw_label_examples")
        raw_label_examples = raw_label_examples if isinstance(raw_label_examples, list) else []
        supporting_candidate_ids = raw.get("supporting_candidate_ids")
        supporting_candidate_ids = (
            supporting_candidate_ids if isinstance(supporting_candidate_ids, list) else []
        )
        items.append(
            {
                "evidence_type": raw.get("label_role")
                or raw.get("mileage_anchor_kind")
                or "trail_mileage_k_anchor",
                "context_kind": "route_context",
                "candidate_id": candidate_id or raw.get("normalized_mileage_k"),
                "label": label,
                "distance_m": _float_or_none(raw.get("mileage_m")),
                "lat": _float_or_none(raw.get("lat")),
                "lon": _float_or_none(raw.get("lon")),
                "nearest_cp_candidate_id": raw.get("nearest_cp_candidate_id"),
                "label_role": raw.get("label_role"),
                "mileage_anchor_kind": raw.get("mileage_anchor_kind"),
                "mileage_k": _float_or_none(raw.get("mileage_k")),
                "mileage_m": _float_or_none(raw.get("mileage_m")),
                "normalized_mileage_k": raw.get("normalized_mileage_k"),
                "raw_mileage_text": raw.get("raw_mileage_text"),
                "route_mileage_m": _float_or_none(
                    raw.get("route_mileage_m") or raw.get("mileage_m")
                ),
                "point_classes": ["route_mileage_k_anchor", "trail_mileage_k_anchor"],
                "review_state": raw.get("review_state"),
                "review_required": bool(raw.get("review_required", True)),
                "confidence": raw.get("confidence"),
                "experience_score": 0.0,
                "guidance": "candidate route mileage anchor",
                "stop_guidance": "mileage anchor is for route reference, not stop permission",
                "candidate_only": bool(raw.get("candidate_only", True)),
                "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
                "source_path": source_path,
                "source_gaps": raw.get("review_reasons", []),
                "source_refs": source_refs,
                "class_terms": ["route_mileage_k_anchor", "trail_mileage_k_anchor"],
                "search_text": _search_text(
                    label,
                    candidate_id,
                    raw.get("label_role"),
                    raw.get("mileage_anchor_kind"),
                    raw.get("normalized_mileage_k"),
                    raw.get("raw_mileage_text"),
                    raw.get("mileage_k"),
                    raw.get("mileage_m"),
                    raw.get("route_mileage_m"),
                    raw_label_examples,
                    supporting_candidate_ids,
                ),
            }
        )
    return items


def _mileage_tag_alignment_items(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    requested_mileage_anchors: set[str],
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = explicit_path or str(
        project.get("mileage_tag_alignment_ref")
        or "outputs/mileage_tag_alignment.json"
    )
    payload, source_path = _load_project_json(root, ref)
    tags = payload.get("mileage_tags") if isinstance(payload, dict) else []
    if not isinstance(tags, list):
        tags = []
    source_report.append(
        _source_report("mileage_tag_alignment", source_path, len(tags))
    )
    if not tags:
        return []

    items: list[dict[str, Any]] = []
    for raw in tags:
        if not isinstance(raw, dict):
            continue
        if requested_mileage_anchors and not _mileage_tag_matches_anchor(
            raw,
            requested_mileage_anchors,
        ):
            continue
        if not requested_mileage_anchors and len(items) >= 64:
            break
        label = str(
            raw.get("display_label")
            or raw.get("source_label")
            or raw.get("display_mileage_label")
            or raw.get("mileage_tag_id")
            or ""
        )
        display_mileage = raw.get("display_mileage")
        display_mileage = display_mileage if isinstance(display_mileage, dict) else {}
        items.append(
            {
                "evidence_type": "mileage_tag_alignment",
                "context_kind": "route_context",
                "candidate_id": raw.get("mileage_tag_id"),
                "label": label,
                "distance_m": _float_or_none(
                    display_mileage.get("mileage_m")
                    or raw.get("route_distance_m")
                    or raw.get("route_mileage_m")
                ),
                "lat": _float_or_none(raw.get("lat")),
                "lon": _float_or_none(raw.get("lon")),
                "label_role": "mileage_tag_alignment",
                "mileage_anchor_kind": "trail_mileage_k_anchor",
                "normalized_mileage_k": raw.get("display_mileage_label"),
                "raw_mileage_text": raw.get("display_label"),
                "route_mileage_m": _float_or_none(
                    display_mileage.get("mileage_m")
                    or raw.get("route_distance_m")
                    or raw.get("route_mileage_m")
                ),
                "point_classes": ["mileage_tag_alignment"],
                "review_state": raw.get("review_state"),
                "confidence": raw.get("confidence"),
                "experience_score": 0.0,
                "guidance": "workspace mileage tag alignment",
                "stop_guidance": "mileage tags are route-display references only",
                "candidate_only": bool(raw.get("candidate_only", True)),
                "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
                "source_path": source_path,
                "source_gaps": [],
                "source_refs": [{"source_path": raw.get("source_ref")}]
                if raw.get("source_ref")
                else [],
                "class_terms": ["mileage_tag_alignment"],
                "search_text": _search_text(
                    label,
                    raw.get("mileage_tag_id"),
                    raw.get("display_mileage_label"),
                    raw.get("display_mileage_span_label"),
                    raw.get("source_id"),
                    raw.get("source_kind"),
                    raw.get("source_label"),
                    raw.get("source_ref"),
                ),
            }
        )
    return items[:256]


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
    if _has_any(
        text,
        (
            "文化",
            "歷史",
            "故事",
            "地名",
            "遺構",
            "原住民族",
            "原住民",
            "舊社",
            "獵徑",
            "警備道",
            "隘勇線",
            "地方傳說",
            "土地使用",
            "context",
        ),
    ):
        hints.add("route_context")
        hints.add("resource_context")
    if _has_any(
        text,
        (
            "自然",
            "林相",
            "林相變化",
            "植被",
            "植群",
            "植物",
            "鳥類",
            "溪流觀察",
            "地質",
            "岩層",
            "季節",
            "地形",
        ),
    ):
        hints.add("route_context")
    if _has_any(text, ("岔路", "方向", "轉彎", "導航")):
        hints.add("navigation_context")
    if _has_any(text, ("建議幾天", "幾天幾夜", "活動簡報", "briefing")):
        hints.add("route_context")
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
            "建議幾天",
            "幾天幾夜",
            "活動簡報",
            "沿途有哪些",
            "自然觀察",
            "林相",
            "林相變化",
            "植被",
            "植群",
            "植物",
            "鳥類",
            "溪流觀察",
            "地質",
            "岩層",
            "原住民族",
            "原住民",
            "舊社",
            "獵徑",
            "警備道",
            "隘勇線",
            "地方傳說",
            "土地使用",
            "停3分鐘",
            "停三分鐘",
            "值得停",
            "routecontext",
            "experienceguide",
            "routebriefing",
            "briefing",
        ),
    )


def _route_briefing_field_answer(
    route_briefing: dict[str, Any],
    *,
    query: str,
) -> str | None:
    if not route_briefing.get("available"):
        return None
    text = _normalize(query)
    boundary = (
        "這是 operator-reviewed pretrip candidate briefing，不是即時安全結論"
        "或 runtime safety truth；出發前仍需重查官方公告、天氣、道路、"
        "入園/山屋與現場風險。"
    )
    if _has_any(text, ("建議幾天", "幾天", "幾天幾夜", "行程版本", "itinerary")):
        recommended = route_briefing.get("recommended_days") or "未提供建議天數"
        options = _itinerary_option_lines(route_briefing.get("itinerary_options"))
        return (
            f"奇萊南華行程建議：{recommended}。"
            + (f" 可選版本：{'；'.join(options)}。" if options else "")
            + f" {boundary}"
        )
    if _has_any(
        text,
        ("停3分鐘", "停三分鐘", "3分鐘", "三分鐘", "值得停"),
    ):
        stops = _observation_stop_lines(route_briefing.get("observation_stops"))
        return (
            "候選 3 分鐘觀察點："
            + ("；".join(stops) if stops else "目前簡報沒有列出觀察點")
            + "。這些不是現場停留授權。"
        )
    requested_layers: list[str] = []
    if _has_any(text, ("歷史脈絡", "歷史點", "歷史層")):
        requested_layers.append("歷史層")
    if _has_any(text, ("文化", "地名", "舊社", "原住民族")):
        requested_layers.append("文化層")
    if _has_any(text, ("自然", "林相", "植被", "植物")):
        requested_layers.append("自然層")
    if _has_any(text, ("地形", "崩壁", "稜線", "鞍部")):
        requested_layers.append("地形層")
    if requested_layers:
        layers = _selected_context_layer_lines(
            route_briefing.get("context_layers"),
            requested_layers,
        )
        return (
            "Route context pack 的 Experience Guide 候選指定脈絡："
            + ("；".join(layers) if layers else "沒有對應脈絡點")
            + "。"
        )
    if _has_any(
        text,
        (
            "沿途有哪些",
            "沿途有什麼",
            "沿途有那些",
            "有哪些歷史",
            "有哪些文化",
            "有哪些自然",
            "有哪些地形",
            "有哪些季節",
            "歷史文化自然地形季節",
            "活動簡報",
            "行前簡報",
            "routecontext",
        ),
    ):
        layers = _context_layer_lines(route_briefing.get("context_layers"))
        summary = route_briefing.get("summary")
        return (
            "候選路線脈絡（Experience Guide 候選）："
            + (f"{summary} " if summary else "")
            + "；".join(layers)
            + f"。{boundary}"
        )
    return None


def _route_mileage_query_field_answer(
    root: Path,
    project: dict[str, Any],
    *,
    query: str,
    requested_mileage_anchors: set[str],
) -> tuple[str | None, str | None, list[str]]:
    if not requested_mileage_anchors:
        return None, None, []
    parsed_targets = [
        _float_or_none(value[:-1])
        for value in requested_mileage_anchors
        if value.endswith("k")
    ]
    target_k = next((value for value in parsed_targets if value is not None), None)
    if target_k is None:
        return None, None, []
    display_label = _format_mileage_anchor_key(target_k).upper()

    if re.search(r"route\s*segment|哪個\s*segment|對應.*segment", query, re.IGNORECASE):
        segment_ref = str(
            project.get("segment_candidates_ref") or "candidates/segments.json"
        )
        segments = _load_json_list(_project_path(root, segment_ref))
        target_m = target_k * 1000.0
        cumulative_m = 0.0
        for item in segments:
            if not isinstance(item, dict):
                continue
            distance_m = _float_or_none(item.get("distance_m"))
            if distance_m is None:
                continue
            end_m = cumulative_m + distance_m
            if cumulative_m <= target_m <= end_m:
                return (
                    f"{display_label} 對應 {item.get('candidate_id')}，"
                    f"區間 {item.get('from_candidate_id')}→"
                    f"{item.get('to_candidate_id')}，primary GPX 累積里程約 "
                    f"{cumulative_m / 1000.0:.3f}-{end_m / 1000.0:.3f} km。",
                    segment_ref,
                    [segment_ref],
                )
            cumulative_m = end_m
        return (
            f"{display_label} 超出目前 segment 累積距離，沒有可對應的 route segment。",
            segment_ref,
            [segment_ref],
        )

    anchors_ref = str(
        project.get("route_mileage_k_anchors_ref")
        or "candidates/route_mileage_k_anchors.json"
    )
    anchors_payload = _load_json_object(_project_path(root, anchors_ref))
    raw_anchors = anchors_payload.get("anchors")
    anchors = [
        item for item in raw_anchors if isinstance(item, dict)
    ] if isinstance(raw_anchors, list) else []
    anchor = next(
        (
            item
            for item in anchors
            if _format_mileage_anchor_key(
                _float_or_none(item.get("mileage_k")) or -1.0
            )
            in requested_mileage_anchors
        ),
        None,
    )
    if anchor is None:
        return None, None, []
    lat = _float_or_none(anchor.get("lat"))
    lon = _float_or_none(anchor.get("lon"))
    distance_m = _float_or_none(anchor.get("mileage_m"))
    distance_text = (
        f"約 {distance_m / 1000.0:.1f} km" if distance_m is not None else "距離未知"
    )
    coordinate_text = (
        f"，候選座標 lat {lat:.9f}, lon {lon:.9f}"
        if lat is not None and lon is not None
        else ""
    )
    source_refs = [anchors_ref]
    nearest_text = ""
    if re.search(r"最近\s*CP|nearest\s*(?:CP|checkpoint)", query, re.IGNORECASE):
        checkpoint_ref = str(
            project.get("checkpoint_candidates_ref")
            or "candidates/checkpoints.json"
        )
        checkpoints = _load_json_list(_project_path(root, checkpoint_ref))
        nearest = _nearest_checkpoint(lat, lon, checkpoints)
        source_refs.append(checkpoint_ref)
        if nearest is not None:
            nearest_text = (
                f"；最近 CP 是 {nearest.get('candidate_id')}/"
                f"{nearest.get('label')}，約 {nearest.get('distance_m')} m"
            )
        else:
            nearest_text = "；目前 checkpoint artifact 無法完成最近 CP join"
    return (
        f"{display_label} 在本次路徑{distance_text} 處{coordinate_text}"
        f"{nearest_text}。此里程錨點 review_required="
        f"{str(bool(anchor.get('review_required', True))).lower()}，"
        "runtime_safety_truth=false。",
        anchors_ref,
        source_refs,
    )


def _nearest_checkpoint(
    lat: float | None,
    lon: float | None,
    checkpoints: list[Any],
) -> dict[str, Any] | None:
    if lat is None or lon is None:
        return None
    candidates = [
        item
        for item in checkpoints
        if isinstance(item, dict)
        and _float_or_none(item.get("lat")) is not None
        and _float_or_none(item.get("lon")) is not None
    ]
    if not candidates:
        return None
    checkpoint = min(
        candidates,
        key=lambda item: _haversine_m(
            lat,
            lon,
            float(item["lat"]),
            float(item["lon"]),
        ),
    )
    distance_m = _haversine_m(
        lat,
        lon,
        float(checkpoint["lat"]),
        float(checkpoint["lon"]),
    )
    return {
        "candidate_id": checkpoint.get("candidate_id"),
        "label": checkpoint.get("label"),
        "distance_m": round(distance_m),
    }


def _haversine_m(
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
) -> float:
    lat_a_rad = math.radians(lat_a)
    lat_b_rad = math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lon = math.radians(lon_b - lon_a)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a_rad)
        * math.cos(lat_b_rad)
        * math.sin(delta_lon / 2.0) ** 2
    )
    return 12_742_000.0 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(max(0.0, 1.0 - haversine)),
    )


def _field_answer(
    results: list[dict[str, Any]],
    *,
    answerability: str,
    requested_mileage_anchors: set[str] | None = None,
) -> str:
    if not results:
        return (
            "目前缺少可用的路線脈絡候選資料。不要為拍攝或觀察臨時改線；"
            "請先查明 CP、風險預算與路線資料。"
        )
    if requested_mileage_anchors:
        mileage_answer = _mileage_anchor_field_answer(results[0])
        if mileage_answer:
            return mileage_answer
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


def _mileage_anchor_field_answer(item: dict[str, Any]) -> str | None:
    if not _is_mileage_anchor_item(item):
        return None
    label = str(
        item.get("normalized_mileage_k")
        or item.get("raw_mileage_text")
        or item.get("label")
        or "里程錨點"
    )
    distance = (
        _float_or_none(item.get("route_mileage_m"))
        or _float_or_none(item.get("mileage_m"))
        or _float_or_none(item.get("distance_m"))
    )
    distance_text = f"約 {distance / 1000:.1f} km" if distance is not None else "距離未知"
    lat = _float_or_none(item.get("lat"))
    lon = _float_or_none(item.get("lon"))
    coord_text = (
        f"，候選座標 lat {lat:.9f}, lon {lon:.9f}"
        if lat is not None and lon is not None
        else ""
    )
    source_path = str(item.get("source_path") or "unknown source")
    return (
        f"{label} 在本次路徑{distance_text} 處{coord_text}。"
        f"來源：{source_path}；這是行前 candidate-only 里程錨點，"
        "runtime_safety_truth=false，現地仍需用 GPX/離線地圖與人工 review 交叉確認。"
    )


def _decision_output(
    *,
    results: list[dict[str, Any]],
    answerability: str,
    field_answer: str,
) -> dict[str, Any]:
    decision = _route_context_decision(results)
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(results=results, answerability=answerability)
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": _decision_next_step(decision=decision),
    }
    second_layer = {
        "details": _decision_details(results=results, field_answer=field_answer),
        "uncertaintyNotes": []
        if results
        else ["Route Context evidence was not available."],
        "residualRisk": [
            "Route context evidence is candidate-only.",
            "Stop, wait, filming, or detour duration still requires contextual permission.",
            "No runtime safety truth was created.",
        ],
        "requiredConditions": [
            "Use contextual permission before any stop, wait, filming, or detour.",
            "Keep weather, daylight, pace, and risk budget checks separate.",
        ],
        "alternativeActions": _decision_alternatives(decision=decision),
    }
    return {
        "role": "Micro-Decision Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {first_layer['decision']}",
                f"[限制] {first_layer['limit']}",
                f"[原因] {first_layer['reason']}",
                f"[下一步] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": second_layer,
        "action": "route_context_observation",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "stopPermissionRequired": True,
            "contextPointCount": len(results),
            "topContextKinds": [
                str(item.get("context_kind") or "route_context") for item in results[:3]
            ],
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "medium" if results else "low",
        "uncertaintyNotes": second_layer["uncertaintyNotes"],
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": second_layer["requiredConditions"],
        "alternativeActions": second_layer["alternativeActions"],
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 6 Route Context Intelligence",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.3 Experience Guide",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _route_context_decision(results: list[dict[str, Any]]) -> str:
    if not results:
        return "DELAY"
    top = results[0]
    stop_guidance = str(top.get("stop_guidance") or "")
    if top.get("context_kind") == "risk_context" or "不建議" in stop_guidance:
        return "NO_GO"
    return "CONDITIONAL_GO"


def _decision_reasons(
    *, results: list[dict[str, Any]], answerability: str
) -> list[str]:
    if not results:
        return [f"answerability={answerability}", "缺少可用路線脈絡候選資料。"]
    reasons = []
    for item in results[:3]:
        label = str(item.get("label") or item.get("candidate_id") or "context point")
        kind = str(item.get("context_kind") or "route_context")
        reasons.append(f"{label} 是 {kind} 候選點。")
        guidance = str(item.get("stop_guidance") or "")
        if guidance:
            reasons.append(guidance)
    return _dedupe(reasons)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "NO_GO":
        return "不建議為觀察或拍攝停留。"
    if decision == "DELAY":
        return "暫緩觀察點判斷。"
    if decision == "CONDITIONAL_GO" and allowed:
        return "可作為候選觀察點。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str) -> str:
    if decision == "NO_GO":
        return "不得為觀察、拍攝或社群打卡停留或繞行；若必須通過，縮短暴露時間。"
    if decision == "DELAY":
        return "不得因缺少脈絡證據臨時改線或停留。"
    return "這不是停留授權；停多久、是否等待或繞行必須另用 contextual permission。"


def _decision_next_step(*, decision: str) -> str:
    if decision == "NO_GO":
        return "保持原安全路線通過，改找下一個低風險觀察點。"
    if decision == "DELAY":
        return "補齊 route context、CP、weather/daylight 與 risk budget 後再判斷。"
    return "若要停留、拍攝或等待，先重跑 contextual permission。"


def _decision_alternatives(*, decision: str) -> list[str]:
    if decision == "NO_GO":
        return ["不停留直接通過。", "改到下一個安全 CP 或低暴露觀察點。"]
    if decision == "DELAY":
        return ["不要臨時改線。", "先用行前候選點做下一次 pretrip 規劃。"]
    return ["短暫觀察後直接前往下一個 CP。", "放棄拍攝，保留天氣與回程 buffer。"]


def _decision_details(
    *, results: list[dict[str, Any]], field_answer: str
) -> list[str]:
    details = [field_answer]
    for item in results[:3]:
        label = str(item.get("label") or item.get("candidate_id") or "context point")
        details.append(
            f"{label}: context_kind={item.get('context_kind')}, "
            f"distance_m={item.get('distance_m')}, stop_guidance={item.get('stop_guidance')}"
        )
    return details


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


def _load_json_list(path: Path) -> list[Any]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


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


def _bounded_source_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs = []
    for raw in value[:8]:
        if not isinstance(raw, dict):
            continue
        refs.append(
            {
                key: raw.get(key)
                for key in ("title", "url", "usage", "source_tier", "source_family")
                if raw.get(key) is not None
            }
        )
    return refs


def _bounded_context_layers(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    layers: dict[str, list[str]] = {}
    for key, raw_lines in list(value.items())[:8]:
        lines = _str_list(raw_lines)
        layers[str(key)] = lines[:5]
    return layers


def _bounded_observation_stops(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    stops = []
    for raw in value[:8]:
        if not isinstance(raw, dict):
            continue
        stops.append(
            {
                key: raw.get(key)
                for key in ("name", "minutes", "observe", "do_not_stop_if")
                if raw.get(key) is not None
            }
        )
    return stops


def _bounded_itinerary_options(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    options = []
    for raw in value[:6]:
        if not isinstance(raw, dict):
            continue
        options.append(
            {
                key: raw.get(key)
                for key in ("label", "schedule", "best_for", "tradeoff")
                if raw.get(key) is not None
            }
        )
    return options


def _itinerary_option_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines = []
    for option in value[:4]:
        if not isinstance(option, dict):
            continue
        label = str(option.get("label") or "")
        best_for = str(option.get("best_for") or "")
        tradeoff = str(option.get("tradeoff") or "")
        line = _join_text(label, best_for, tradeoff)
        if line:
            lines.append(line)
    return lines


def _context_layer_lines(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    lines = []
    for layer_name, raw_lines in value.items():
        text = "、".join(_str_list(raw_lines)[:2])
        if text:
            lines.append(f"{layer_name}: {text}")
    return lines


def _selected_context_layer_lines(
    value: Any,
    layer_names: list[str],
) -> list[str]:
    if not isinstance(value, dict):
        return []
    requested = set(layer_names)
    lines = []
    for layer_name, raw_lines in value.items():
        if str(layer_name) not in requested:
            continue
        text = "、".join(_str_list(raw_lines)[:4])
        if text:
            lines.append(f"{layer_name}: {text}")
    return lines


def _observation_stop_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines = []
    for stop in value[:6]:
        if not isinstance(stop, dict):
            continue
        name = str(stop.get("name") or "")
        minutes = stop.get("minutes")
        observe = str(stop.get("observe") or "")
        blocked = str(stop.get("do_not_stop_if") or "")
        minute_text = f"{minutes} 分鐘" if minutes is not None else "短暫"
        line = f"{name}（{minute_text}，看 {observe}"
        if blocked:
            line += f"；不要停留條件：{blocked}"
        line += "）"
        if name:
            lines.append(line)
    return lines


def _join_text(*parts: Any) -> str:
    values = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return "；".join(values)


def _item_references_cp(item: dict[str, Any], cp: str) -> bool:
    normalized = _normalize(cp)
    return normalized in {
        _normalize(item.get("nearest_cp_candidate_id")),
        _normalize(item.get("segment_ref")),
        _normalize(item.get("candidate_id")),
    } or normalized in _normalize(item.get("search_text"))


def _normalize_context_types(values: list[str] | None) -> set[str]:
    return {_normalize(value) for value in (values or []) if str(value).strip()}


def _mileage_anchor_keys(query: str) -> set[str]:
    text = _normalize_mileage_text(query)
    keys: set[str] = set()
    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)(?:k|公里|km)(?![a-z0-9])", text):
        keys.add(_format_mileage_anchor_key(float(match.group(1))))
    return keys


def _looks_like_mileage_tag_query(query: str) -> bool:
    lowered = str(query or "").lower()
    return bool(
        re.search(
            r"mileage|里程|公里樁|樁號|k點|k\s*tag|display mileage|mileage tag",
            lowered,
        )
    )


def _mileage_tag_matches_anchor(
    item: dict[str, Any],
    requested_keys: set[str],
) -> bool:
    keys: set[str] = set()
    display_mileage = item.get("display_mileage")
    display_mileage = display_mileage if isinstance(display_mileage, dict) else {}
    for value in (
        item.get("display_mileage_label"),
        item.get("display_mileage_span_label"),
        item.get("display_label"),
        item.get("source_label"),
        item.get("mileage_tag_id"),
        display_mileage.get("label"),
    ):
        keys.update(_mileage_anchor_keys(str(value or "")))
    for value in (
        display_mileage.get("mileage_m"),
        item.get("route_distance_m"),
        item.get("route_mileage_m"),
    ):
        parsed_m = _float_or_none(value)
        if parsed_m is not None:
            keys.add(_format_mileage_anchor_key(parsed_m / 1000.0))
    return bool(keys & requested_keys)


def _item_matches_mileage_anchor(
    item: dict[str, Any],
    requested_keys: set[str],
) -> bool:
    item_keys = _item_mileage_anchor_keys(item)
    return bool(item_keys & requested_keys)


def _item_mileage_anchor_keys(item: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    anchor_kind = _explicit_mileage_anchor_kind(item)
    for value in (
        item.get("normalized_mileage_k"),
        item.get("raw_mileage_text"),
        item.get("label"),
        item.get("candidate_id"),
    ):
        keys.update(_mileage_anchor_keys(str(value or "")))
    if not anchor_kind and not keys:
        return keys
    parsed_k = _float_or_none(item.get("mileage_k"))
    if parsed_k is not None:
        keys.add(_format_mileage_anchor_key(parsed_k))
    for value in (
        item.get("route_mileage_m"),
        item.get("mileage_m"),
        item.get("distance_m"),
    ):
        parsed_m = _float_or_none(value)
        if parsed_m is not None:
            keys.add(_format_mileage_anchor_key(parsed_m / 1000.0))
    return keys


def _is_mileage_anchor_item(item: dict[str, Any]) -> bool:
    return bool(_explicit_mileage_anchor_kind(item)) or bool(
        _item_mileage_anchor_keys(item)
    )


def _explicit_mileage_anchor_kind(item: dict[str, Any]) -> str | None:
    evidence_type = str(item.get("evidence_type") or "")
    label_role = str(item.get("label_role") or "")
    kind = str(item.get("mileage_anchor_kind") or "")
    matches = {"trail_mileage_k_anchor", "road_mileage_stone"}.intersection(
        {evidence_type, label_role, kind}
    )
    return next(iter(matches), None)


def _format_mileage_anchor_key(value: float) -> str:
    rounded = round(value, 3)
    if rounded.is_integer():
        return f"{int(rounded)}k"
    return f"{rounded:g}k"


def _normalize_mileage_text(value: Any) -> str:
    fullwidth = str.maketrans(
        "０１２３４５６７８９Ｋｋ．。",
        "0123456789kk..",
    )
    return str(value or "").translate(fullwidth).strip().lower().replace(" ", "")


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


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
