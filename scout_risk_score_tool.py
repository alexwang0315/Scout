from __future__ import annotations

from bisect import bisect_right
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
    _attach_nearest_route_context(filtered, root, project)
    segment_source_ref = _attach_candidate_route_segments(filtered, root, project)
    segment_risk_summary = _segment_risk_summary(filtered)
    filtered.sort(key=_sort_key(resolved_sort))
    results = filtered[:resolved_limit]
    compact_results = [_compact_result(item) for item in results]
    source_refs = [
        str(report["source_path"])
        for report in load_report
        if report.get("source_path")
    ]
    if segment_source_ref:
        source_refs.append(segment_source_ref)
    answerability = (
        "risk_score_decision_available"
        if compact_results
        else "risk_score_missing_evidence"
    )
    decision = _risk_decision(compact_results)
    query_field_answer, query_source_refs = _risk_query_field_answer(
        root=root,
        project=project,
        query=query,
        results=compact_results,
        all_items=filtered,
        summaries=summaries,
        segment_risk_summary=segment_risk_summary,
        score_source_refs=source_refs,
    )
    source_refs = list(dict.fromkeys([*query_source_refs, *source_refs]))
    field_answer = query_field_answer or _field_answer(
        decision=decision,
        results=compact_results,
        answerability=answerability,
        segment_risk_summary=segment_risk_summary,
    )
    decision_output = _decision_output(
        decision=decision,
        results=compact_results,
        summaries=summaries,
        filters={
            "min_score": resolved_min_score,
            "risk_bucket": resolved_bucket,
            "distance_km_min": resolved_distance_min,
            "distance_km_max": resolved_distance_max,
            "cp": resolved_cp,
            "lat": resolved_lat,
            "lon": resolved_lon,
            "radius_m": resolved_radius_m,
            "sort": resolved_sort,
        },
        answerability=answerability,
        field_answer=field_answer,
    )

    return {
        "tool_id": RISK_SCORE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "source_status": "candidate_only",
        "answerability": answerability,
        "decision": decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "field_answer_priority": 100 if query_field_answer else 0,
        "field_answer_source_ref": source_refs[0] if query_field_answer and source_refs else None,
        "field_answer_source_refs": query_source_refs,
        "source_ref": source_refs[0] if query_field_answer and source_refs else None,
        "risk_decision": {
            "role": "Risk Score / Route Hazard Decision",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision,
            "decision_output": decision_output,
            "highest_risk_result": compact_results[0] if compact_results else None,
            "next_action": decision_output["nextAction"],
        },
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
        "source_refs": list(dict.fromkeys(source_refs)),
        "summaries": summaries,
        "segment_risk_summary": segment_risk_summary,
        "searched_score_count": len(loaded_items),
        "matched_score_count": len(filtered),
        "result_count": len(results),
        "results": compact_results,
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 data confidence",
        ],
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
        "nearest_checkpoint",
        "nearest_mileage_anchor",
        "readable_location",
        "candidate_route_segment",
        "segment_candidate_id",
        "segment_label",
        "segment_join_distance_m",
        "segment_join_method",
        "segment_join_status",
        "human_review_required",
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


def _risk_decision(results: list[dict[str, Any]]) -> str:
    if not results:
        return "DELAY"
    top = results[0]
    rank = _bucket_rank(top.get("risk_bucket")) or 0
    score = _score_100(top.get("score"))
    if rank >= 4 or score >= 90.0:
        return "NO_GO"
    if rank >= 3 or score >= 70.0:
        return "CHANGE_PLAN"
    if rank >= 2 or score >= 40.0:
        return "CONDITIONAL_GO"
    return "GO"


def _field_answer(
    *,
    decision: str,
    results: list[dict[str, Any]],
    answerability: str,
    segment_risk_summary: dict[str, Any],
) -> str:
    if not results:
        return (
            "風險分數判斷：建議 DELAY。沒有匹配到可追溯的風險分數結果；"
            "Scout 不能用空資料推論路段安全。"
        )
    top = results[0]
    location = _result_location(top)
    segment_candidates = segment_risk_summary.get("segments")
    segment_clause = ""
    if isinstance(segment_candidates, list) and segment_candidates:
        labels = [
            str(item.get("candidate_id") or item.get("label"))
            for item in segment_candidates
            if isinstance(item, dict)
            and (item.get("candidate_id") or item.get("label"))
        ]
        total = int(segment_risk_summary.get("matched_segment_count") or len(labels))
        qualifier = "前" if segment_risk_summary.get("truncated") else ""
        segment_clause = (
            f" 匹配到 {total} 個候選路段；{qualifier}{len(labels)} 個為："
            f"{', '.join(labels)}。"
        )
    explicit_location = _explicit_location_fields(top)
    return (
        f"風險分數判斷：建議 {decision}。{explicit_location} "
        f"最高候選風險位於 {location}，"
        f"score={top.get('score')}、bucket={top.get('risk_bucket') or 'unknown'}。"
        f"{segment_clause}"
        f"下一步：{_next_action(decision=decision)} "
        f"answerability={answerability}；此為候選風險證據，不是 runtime safety truth。"
    )


def _risk_query_field_answer(
    *,
    root: Path,
    project: dict[str, Any],
    query: str,
    results: list[dict[str, Any]],
    all_items: list[dict[str, Any]],
    summaries: dict[str, Any],
    segment_risk_summary: dict[str, Any],
    score_source_refs: list[str],
) -> tuple[str, list[str]]:
    lowered = query.casefold()

    if re.search(r"route\s*note|路線註記|路線備註", lowered) and re.search(
        r"calibrat|校準|高風險|high\s*risk", lowered
    ):
        answer, route_note_ref = _route_notes_near_calibrated_high_risk(
            root,
            project,
            all_items,
        )
        if answer:
            refs = [route_note_ref] if route_note_ref else []
            return answer, [*refs, *score_source_refs]

    if "attribution" in lowered or "歸因" in lowered:
        ref = str(
            project.get("risk_attribution_diagnostic_ref")
            or "outputs/risk/risk_attribution_diagnostic.json"
        )
        payload = _load_optional_json_object(root, ref)
        factor_analysis = payload.get("factor_analysis")
        formula = (
            factor_analysis.get("formula_candidate")
            if isinstance(factor_analysis, dict)
            else None
        )
        dimensions = formula.get("selected_dimensions") if isinstance(formula, dict) else []
        expression = formula.get("expression") if isinstance(formula, dict) else None
        if isinstance(dimensions, list) and dimensions:
            answer = f"最高風險的候選歸因維度是 {'、'.join(map(str, dimensions))}"
            if expression:
                answer += f"；候選公式為 {expression}"
            return answer + "。這是 workspace 診斷，不會覆寫正式 risk score。", [ref]

    if "excluded" in lowered and ("proposal" in lowered or "排除" in lowered):
        ref = str(
            project.get("excluded_extreme_warning_cp_proposals_ref")
            or "outputs/risk/excluded_extreme_warning_cp_proposals.json"
        )
        payload = _load_optional_json_object(root, ref)
        dimensions = payload.get("excluded_dimensions")
        counts = payload.get("counts")
        proposals = payload.get("proposals")
        proposal_count = counts.get("proposal_count") if isinstance(counts, dict) else None
        first_reason = (
            proposals[0].get("reason_zh")
            if isinstance(proposals, list) and proposals and isinstance(proposals[0], dict)
            else None
        )
        if isinstance(dimensions, list) and dimensions:
            dimension_text = "、".join(map(str, dimensions))
            reason = str(first_reason or f"{dimension_text} 未納入正式公式")
            return (
                f"excluded extreme warning CP proposals 共 {proposal_count} 筆 proposal；"
                f"排除維度為 {dimension_text}。原因：{reason}",
                [ref],
            )

    if "risk ribbon" in lowered and ("heatmap" in lowered or "heat map" in lowered):
        ribbon_ref = str(
            project.get("risk_ribbon_metadata_ref")
            or "outputs/risk/risk_ribbon.metadata.json"
        )
        heatmap_ref = str(
            project.get("calibrated_risk_heatmap_metadata_ref")
            or "outputs/risk/calibrated_risk_heatmap.metadata.json"
        )
        ribbon = _load_optional_json_object(root, ribbon_ref)
        heatmap = _load_optional_json_object(root, heatmap_ref)
        ribbon_count = ribbon.get("segment_count", project.get("risk_ribbon_segment_count"))
        heatmap_count = heatmap.get(
            "segment_count",
            project.get("calibrated_risk_heatmap_segment_count"),
        )
        if ribbon_count is not None or heatmap_count is not None:
            equality = "一致" if ribbon_count == heatmap_count else "不一致"
            return (
                f"資料點數：risk ribbon={ribbon_count}；calibrated heatmap={heatmap_count}；"
                f"兩者{equality}。",
                [ribbon_ref, heatmap_ref],
            )

    if "bucket" in lowered and any(token in lowered for token in ("各", "分別", "多少", "count")):
        clauses: list[str] = []
        for surface in ("baseline", "calibration"):
            summary = summaries.get(surface)
            if not isinstance(summary, dict) or not summary.get("available"):
                continue
            counts = summary.get("bucket_counts")
            if not isinstance(counts, dict):
                continue
            ordered = [
                f"{bucket}={counts[bucket]}"
                for bucket in ("low", "moderate", "high", "very_high", "extreme", "unknown")
                if bucket in counts
            ]
            clauses.append(f"{surface}：{'、'.join(ordered)}")
        if clauses:
            return "risk score bucket 點數為：" + "；".join(clauses) + "。", score_source_refs

    if (
        "baseline" in lowered
        and ("calibrat" in lowered or "校準" in lowered)
        and any(token in lowered for token in ("最大", "最高", " max"))
    ):
        baseline = summaries.get("baseline")
        calibration = summaries.get("calibration")
        if isinstance(baseline, dict) and isinstance(calibration, dict):
            return (
                f"baseline max={baseline.get('max_score')}；"
                f"calibrated max={calibration.get('max_score')}。",
                score_source_refs,
            )

    if "delta" in lowered or "差值" in lowered:
        delta_items = [
            item for item in all_items if _optional_float(item.get("calibration_delta")) is not None
        ]
        if delta_items:
            top = max(delta_items, key=lambda item: float(item["calibration_delta"]))
            return (
                "最大 risk delta 位於 "
                f"{top.get('distance_km')} km（{top.get('lat')},{top.get('lon')}），"
                f"baseline={top.get('paired_baseline_score')}、calibrated={top.get('score')}、"
                f"delta={top.get('calibration_delta')}。",
                score_source_refs,
            )

    if (
        "calibrat" in lowered
        and "最高" in lowered
        and re.search(r"(?:五|5)\s*(?:個|筆)?(?:位置|點)", lowered)
    ):
        top_five = results[:5]
        if top_five:
            locations = [
                (
                    f"{index}. {item.get('distance_km')} km / "
                    f"{item.get('lat')},{item.get('lon')} / score={item.get('score')} / "
                    f"{item.get('risk_bucket')}"
                )
                for index, item in enumerate(top_five, 1)
            ]
            return "calibrated risk 最高五個位置：" + "；".join(locations) + "。", score_source_refs

    if (
        "calibrat" in lowered
        and "最高" in lowered
        and "cp" in lowered
        and "座標" in lowered
    ):
        if results:
            top = results[0]
            checkpoint = top.get("nearest_checkpoint")
            mileage = top.get("nearest_mileage_anchor")
            return (
                "最高 calibrated risk 點："
                f"CP={_nested_value(checkpoint, 'label')}（距離 {_nested_value(checkpoint, 'distance_m')} m）；"
                f"K={_nested_value(mileage, 'label')}（距離 {_nested_value(mileage, 'distance_m')} m）；"
                f"座標={top.get('lat')},{top.get('lon')}；score={top.get('score')}、"
                f"bucket={top.get('risk_bucket')}。",
                score_source_refs,
            )

    if re.search(r"\b15\s*k\b", lowered) and "risk" in lowered and results:
        top = results[0]
        return (
            f"15K 附近最高匹配 risk score={top.get('score')}、bucket={top.get('risk_bucket')}；"
            f"GPX 累積={top.get('distance_km')} km，座標={top.get('lat')},{top.get('lon')}。",
            score_source_refs,
        )

    if "segment" in lowered and ("extreme" in lowered or "very_high" in lowered):
        segments = segment_risk_summary.get("segments")
        if isinstance(segments, list) and segments:
            labels = [
                f"{item.get('candidate_id')}({item.get('highest_risk_bucket')}, max={item.get('max_score')})"
                for item in segments
                if isinstance(item, dict)
            ]
            return (
                f"含 extreme 或 very_high 點的候選 route segments 共 "
                f"{segment_risk_summary.get('matched_segment_count')} 個；"
                f"前 {len(labels)} 個為：{', '.join(labels)}。",
                score_source_refs,
            )

    return "", []


def _route_notes_near_calibrated_high_risk(
    root: Path,
    project: dict[str, Any],
    risk_items: list[dict[str, Any]],
    *,
    radius_m: float = 250.0,
) -> tuple[str, str | None]:
    ref = str(
        project.get("route_note_candidates_ref")
        or "candidates/route_note_candidates.json"
    )
    payload = _load_optional_json_object(root, ref)
    raw_notes = payload.get("candidates") if isinstance(payload, dict) else []
    notes = [item for item in raw_notes if isinstance(item, dict)]
    calibrated = [
        item
        for item in risk_items
        if item.get("surface") == "calibration"
        and _bucket_rank(str(item.get("risk_bucket") or "")) >= _bucket_rank("high")
        and _optional_float(item.get("lat")) is not None
        and _optional_float(item.get("lon")) is not None
    ]
    calibrated.sort(key=lambda item: -float(item.get("score") or 0.0))
    matches: list[dict[str, Any]] = []
    for note in notes:
        note_lat = _optional_float(note.get("lat"))
        note_lon = _optional_float(note.get("lon"))
        if note_lat is None or note_lon is None:
            continue
        nearest: tuple[float, dict[str, Any]] | None = None
        for risk in calibrated[:120]:
            distance = _haversine_m(
                note_lat,
                note_lon,
                float(risk["lat"]),
                float(risk["lon"]),
            )
            if nearest is None or distance < nearest[0]:
                nearest = (distance, risk)
        if nearest is None or nearest[0] > radius_m:
            continue
        matches.append(
            {
                "name": note.get("name") or note.get("normalized_note") or note.get("candidate_id"),
                "category": note.get("note_category") or "uncategorized_note",
                "distance_m": round(nearest[0]),
                "score": nearest[1].get("score"),
                "bucket": nearest[1].get("risk_bucket"),
            }
        )
    matches.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            int(item.get("distance_m") or 0),
            str(item.get("name") or ""),
        )
    )
    if not matches:
        return (
            f"在 {radius_m:.0f} m 空間門檻內，沒有 route note 靠近 "
            "calibrated high/very_high/extreme risk 候選點。",
            ref,
        )
    bounded = matches[:8]
    details = "；".join(
        f"{item['name']}({item['category']}, 距高風險點 {item['distance_m']} m, "
        f"score={item['score']}, {item['bucket']})"
        for item in bounded
    )
    remainder = len(matches) - len(bounded)
    suffix = f"；其餘 {remainder} 筆見 artifact" if remainder else ""
    return (
        f"{radius_m:.0f} m 內共有 {len(matches)} 筆 route note 靠近 calibrated "
        f"high/very_high/extreme risk 候選點；前 {len(bounded)} 筆："
        f"{details}{suffix}。",
        ref,
    )


def _load_optional_json_object(root: Path, ref: str) -> dict[str, Any]:
    path = _project_path(root, ref)
    if not path.exists():
        return {}
    try:
        return _load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _nested_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else "unavailable"


def _explicit_location_fields(item: dict[str, Any]) -> str:
    checkpoint = item.get("nearest_checkpoint")
    mileage = item.get("nearest_mileage_anchor")
    fields = [
        (
            f"nearest_cp_label={checkpoint.get('label')}"
            if isinstance(checkpoint, dict) and checkpoint.get("label")
            else "nearest_cp_label=unavailable"
        ),
        (
            f"distance_to_cp_m={checkpoint.get('distance_m')}"
            if isinstance(checkpoint, dict) and checkpoint.get("distance_m") is not None
            else "distance_to_cp_m=unavailable"
        ),
        (
            f"nearest_mileage_label={mileage.get('label')}"
            if isinstance(mileage, dict) and mileage.get("label")
            else "nearest_mileage_label=unavailable"
        ),
        (
            f"distance_to_mileage_m={mileage.get('distance_m')}"
            if isinstance(mileage, dict) and mileage.get("distance_m") is not None
            else "distance_to_mileage_m=unavailable"
        ),
        f"gpx_cumulative_km={item.get('distance_km')}",
        f"lat={item.get('lat')}",
        f"lon={item.get('lon')}",
    ]
    return "最高候選定位欄位：" + "; ".join(fields) + "。"


def _decision_output(
    *,
    decision: str,
    results: list[dict[str, Any]],
    summaries: dict[str, Any],
    filters: dict[str, Any],
    answerability: str,
    field_answer: str,
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    top = results[0] if results else {}
    reasons = _decision_reasons(decision=decision, results=results)
    uncertainty_notes = _uncertainty_notes(results=results, summaries=summaries)
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision, top=top),
        "reason": " / ".join(reasons[:2]),
        "nextStep": _next_action(decision=decision),
    }
    residual_risk = [
        "Risk scores are candidate planning evidence only.",
        (
            "Terrain, weather, pace, team status, and runtime observations can "
            "change the final decision."
        ),
        "No /safety, SOS, outbound send, runtime mutation, or hardware control was performed.",
    ]
    second_layer = {
        "details": _decision_details(
            top=top,
            results=results,
            filters=filters,
            field_answer=field_answer,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": _required_conditions(decision=decision),
        "alternativeActions": _alternative_actions(decision=decision),
    }
    return {
        "role": "Risk Sentinel",
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
        "action": "risk_score_route_hazard_review",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "highestScore": top.get("score"),
            "highestScore100": _score_100(top.get("score")) if top else None,
            "highestRiskBucket": top.get("risk_bucket"),
            "highestDistanceKm": top.get("distance_km"),
            "matchedScoreCount": len(results),
            "timeBufferChangeMinutes": 0 if not allowed else None,
            "bufferPolicy": (
                "Unplanned stops, photo goals, and summit pushes are not granted "
                "by risk scores."
            ),
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": second_layer["requiredConditions"],
        "alternativeActions": second_layer["alternativeActions"],
        "answerability": answerability,
        "runtimeSafetyTruth": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
    }


def _decision_reasons(
    *,
    decision: str,
    results: list[dict[str, Any]],
) -> list[str]:
    if not results:
        return ["沒有匹配到可追溯的風險分數結果。"]
    top = results[0]
    reasons = [
        (
            f"最高候選風險 score={top.get('score')} "
            f"bucket={top.get('risk_bucket') or 'unknown'}。"
        ),
        f"位置：{_result_location(top)}。",
    ]
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        reasons.append("分數或 bucket 已達需要改變路線/通過策略的保守門檻。")
    elif decision == "CONDITIONAL_GO":
        reasons.append("分數或 bucket 顯示需要條件式通過與重查。")
    else:
        reasons.append("目前匹配結果未達高風險門檻。")
    return _dedupe(reasons)


def _uncertainty_notes(
    *,
    results: list[dict[str, Any]],
    summaries: dict[str, Any],
) -> list[str]:
    notes = []
    if not results:
        notes.append("No matching risk score result was available.")
    baseline = summaries.get("baseline") if isinstance(summaries, dict) else None
    calibration = summaries.get("calibration") if isinstance(summaries, dict) else None
    if not isinstance(baseline, dict) or not baseline.get("available"):
        notes.append("Baseline risk scores are not available.")
    if not isinstance(calibration, dict) or not calibration.get("available"):
        notes.append("Calibrated risk heatmap is not available.")
    if results and results[0].get("paired_calibration_score") is None:
        notes.append("Top result may not have paired calibration evidence.")
    return _dedupe(notes)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "NO_GO":
        return "不建議進入最高風險路段。"
    if decision == "CHANGE_PLAN":
        return "建議改變路線或通過策略。"
    if decision == "CONDITIONAL_GO":
        return "可有條件通過，但必須縮短停留並重查。"
    if decision == "GO" and allowed:
        return "可作為低風險候選路段通過。"
    return "暫緩風險分數判斷。"


def _decision_limit_phrase(*, decision: str, top: dict[str, Any]) -> str:
    location = _result_location(top) if top else "目前查詢範圍"
    if decision == "NO_GO":
        return f"{location} 不得作為原計畫通過或停留目標；先改線、撤退或人工複核。"
    if decision == "CHANGE_PLAN":
        return f"{location} 不得直接照原節奏通過；先改線、縮短目標或設定人工確認點。"
    if decision == "CONDITIONAL_GO":
        return f"{location} 只能快速通過，不得為拍照、休息或攻頂增加停留；下一 CP 前重查。"
    if decision == "GO":
        return "仍需依天氣、日照、隊伍與 CP Graph 重查；此回答不是停留授權。"
    return "補齊可追溯風險分數前，不得把此回答當成路線 permission。"


def _next_action(*, decision: str) -> str:
    if decision == "NO_GO":
        return "改線、撤退到上一個安全 CP，或交由人工複核後重新規劃。"
    if decision == "CHANGE_PLAN":
        return "改短版/替代路線，並用 terrain、weather、pace 與 route readiness 重新評估。"
    if decision == "CONDITIONAL_GO":
        return "快速通過並在下一 CP 前重查風險、天氣與隊伍狀態。"
    if decision == "GO":
        return "維持保守節奏，下一 CP 或條件改變時重查。"
    return "補齊風險分數與校準證據後再判斷。"


def _required_conditions(*, decision: str) -> list[str]:
    conditions = [
        "不得將風險分數升格為 runtime safety truth。",
        "通過前仍需核對 terrain、weather/daylight、pace、team status 與 route readiness。",
    ]
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        conditions.append("必須提出改線、撤退或人工複核方案。")
    if decision == "CONDITIONAL_GO":
        conditions.append("不得增加非必要停留；下一 CP 前必須重查。")
    return conditions


def _alternative_actions(*, decision: str) -> list[str]:
    if decision == "NO_GO":
        return ["改線。", "撤回上一個安全 CP。", "延期或交由人工複核。"]
    if decision == "CHANGE_PLAN":
        return ["改短版。", "避開最高風險段。", "改由更保守 CP Graph 重新排程。"]
    if decision == "CONDITIONAL_GO":
        return ["快速通過。", "降低速度與隊伍間距。", "在下一 CP 重查後再決定。"]
    if decision == "GO":
        return ["維持原路線但保守通過。", "若天氣或隊伍狀態改變則重新評估。"]
    return ["補齊 baseline/calibration 風險證據。", "改問具體 CP 或里程範圍。"]


def _decision_details(
    *,
    top: dict[str, Any],
    results: list[dict[str, Any]],
    filters: dict[str, Any],
    field_answer: str,
) -> list[str]:
    details = [field_answer, f"matched_result_count={len(results)}"]
    if top:
        details.extend(
            [
                f"top_score={top.get('score')}",
                f"top_bucket={top.get('risk_bucket')}",
                f"top_distance_km={top.get('distance_km')}",
                f"top_surface={top.get('surface')}",
            ]
        )
    details.append("filters=" + json.dumps(filters, ensure_ascii=False, sort_keys=True))
    return details


def _result_location(item: dict[str, Any]) -> str:
    if item.get("readable_location"):
        return str(item["readable_location"])
    checkpoint = item.get("nearest_checkpoint")
    if isinstance(checkpoint, dict) and checkpoint.get("label"):
        label = checkpoint["label"]
        gap = checkpoint.get("distance_m")
        if gap is not None:
            return f"{label} 附近（約 {round(float(gap))} m）"
        return f"{label} 附近"
    if item.get("distance_km") is not None:
        return f"{item.get('distance_km')} km"
    if item.get("segment_id"):
        return f"segment {item.get('segment_id')}"
    if item.get("sample_id"):
        return f"sample {item.get('sample_id')}"
    if item.get("lat") is not None and item.get("lon") is not None:
        return f"{item.get('lat')},{item.get('lon')}"
    return "查詢範圍內"


def _attach_nearest_route_context(
    items: list[dict[str, Any]],
    root: Path,
    project: dict[str, Any],
) -> None:
    checkpoints = _load_anchor_records(
        root,
        str(project.get("checkpoint_candidates_ref") or "candidates/checkpoints.json"),
        list_keys=("items", "checkpoints", "candidates"),
    )
    mileage_anchors = _load_anchor_records(
        root,
        str(project.get("route_mileage_k_anchors_ref") or "candidates/route_mileage_k_anchors.json"),
        list_keys=("anchors", "items", "candidates"),
    )
    for item in items:
        lat = _optional_float(item.get("lat"))
        lon = _optional_float(item.get("lon"))
        if lat is None or lon is None:
            continue
        nearest_cp = _nearest_geo_anchor(
            lat=lat,
            lon=lon,
            anchors=checkpoints,
            label_keys=("label", "candidate_id", "checkpoint_id"),
        )
        nearest_mileage = _nearest_geo_anchor(
            lat=lat,
            lon=lon,
            anchors=mileage_anchors,
            label_keys=("display_label", "normalized_mileage_k", "raw_label"),
        )
        if nearest_cp is not None:
            item["nearest_checkpoint"] = nearest_cp
        if nearest_mileage is not None:
            item["nearest_mileage_anchor"] = nearest_mileage
        item["readable_location"] = _readable_route_anchor(item)


def _attach_candidate_route_segments(
    items: list[dict[str, Any]],
    root: Path,
    project: dict[str, Any],
) -> str | None:
    """Join route-distance risk evidence to adjacent candidate segments."""

    source_ref = str(
        project.get("segment_candidates_ref") or "candidates/segments.json"
    )
    segments = _load_anchor_records(
        root,
        source_ref,
        list_keys=("segments", "items", "candidates"),
    )
    ranges: list[tuple[float, float, dict[str, Any]]] = []
    cursor_m = 0.0
    for segment in segments:
        distance_m = _optional_float(segment.get("distance_m"))
        if distance_m is None or distance_m <= 0:
            continue
        start_m = cursor_m
        cursor_m += distance_m
        ranges.append((start_m, cursor_m, segment))
    if not ranges:
        return None
    end_distances = [end_m for _, end_m, _ in ranges]

    for item in items:
        join_distance_m = _optional_float(item.get("distance_m"))
        if join_distance_m is None:
            item["segment_join_status"] = "missing_route_distance"
            continue
        range_index = bisect_right(end_distances, join_distance_m)
        if range_index == len(ranges) and math.isclose(
            join_distance_m,
            end_distances[-1],
        ):
            range_index -= 1
        if range_index >= len(ranges) or join_distance_m < 0:
            item["segment_join_status"] = "route_distance_out_of_range"
            continue
        matched = ranges[range_index]
        start_m, end_m, segment = matched
        candidate_id = str(segment.get("candidate_id") or "").strip()
        if not candidate_id:
            item["segment_join_status"] = "segment_candidate_id_missing"
            continue
        label = str(segment.get("label") or candidate_id)
        joined = {
            "candidate_id": candidate_id,
            "label": label,
            "from_candidate_id": segment.get("from_candidate_id"),
            "to_candidate_id": segment.get("to_candidate_id"),
            "segment_distance_m": round(end_m - start_m, 2),
            "cumulative_start_distance_m": round(start_m, 2),
            "cumulative_end_distance_m": round(end_m, 2),
            "join_distance_m": round(join_distance_m, 2),
            "join_method": "cumulative_route_distance_candidate",
            "source_path": source_ref,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "human_review_required": True,
        }
        item.update(
            {
                "candidate_route_segment": joined,
                "segment_candidate_id": candidate_id,
                "segment_label": label,
                "segment_join_distance_m": round(join_distance_m, 2),
                "segment_join_method": "cumulative_route_distance_candidate",
                "segment_join_status": "matched_candidate",
                "human_review_required": True,
            }
        )
    return source_ref


def _segment_risk_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_segment: dict[str, dict[str, Any]] = {}
    for item in items:
        segment = item.get("candidate_route_segment")
        if not isinstance(segment, dict):
            continue
        candidate_id = str(segment.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        score = _optional_float(item.get("score"))
        current = by_segment.get(candidate_id)
        if current is None:
            current = {
                "candidate_id": candidate_id,
                "label": segment.get("label") or candidate_id,
                "from_candidate_id": segment.get("from_candidate_id"),
                "to_candidate_id": segment.get("to_candidate_id"),
                "cumulative_start_distance_m": segment.get(
                    "cumulative_start_distance_m"
                ),
                "cumulative_end_distance_m": segment.get(
                    "cumulative_end_distance_m"
                ),
                "max_score": score,
                "highest_risk_bucket": item.get("risk_bucket"),
                "matching_risk_point_count": 0,
                "surfaces": [],
                "source_path": segment.get("source_path"),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "human_review_required": True,
            }
            by_segment[candidate_id] = current
        current["matching_risk_point_count"] += 1
        surface = str(item.get("surface") or "").strip()
        if surface and surface not in current["surfaces"]:
            current["surfaces"].append(surface)
        current_score = _optional_float(current.get("max_score"))
        if score is not None and (current_score is None or score > current_score):
            current["max_score"] = score
            current["highest_risk_bucket"] = item.get("risk_bucket")
    ranked = sorted(
        by_segment.values(),
        key=lambda item: (
            -float(item.get("max_score") or 0.0),
            str(item.get("candidate_id") or ""),
        ),
    )
    visible = ranked[:MAX_RISK_SCORE_LIMIT]
    return {
        "join_method": "cumulative_route_distance_candidate",
        "matched_segment_count": len(ranked),
        "returned_segment_count": len(visible),
        "truncated": len(ranked) > len(visible),
        "segments": visible,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
    }


def _load_anchor_records(
    root: Path,
    ref: str,
    *,
    list_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    path = _project_path(root, ref)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = []
        for key in list_keys:
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _nearest_geo_anchor(
    *,
    lat: float,
    lon: float,
    anchors: list[dict[str, Any]],
    label_keys: tuple[str, ...],
) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for anchor in anchors:
        anchor_lat = _optional_float(anchor.get("lat"))
        anchor_lon = _optional_float(anchor.get("lon"))
        if anchor_lat is None or anchor_lon is None:
            continue
        distance_m = _haversine_m(lat, lon, anchor_lat, anchor_lon)
        candidates.append((distance_m, anchor))
    if not candidates:
        return None
    distance_m, anchor = min(candidates, key=lambda value: value[0])
    label = None
    for key in label_keys:
        value = anchor.get(key)
        if value:
            label = str(value)
            break
    result: dict[str, Any] = {
        "label": label,
        "distance_m": round(distance_m, 1),
        "lat": _optional_float(anchor.get("lat")),
        "lon": _optional_float(anchor.get("lon")),
    }
    for key in (
        "candidate_id",
        "checkpoint_id",
        "checkpoint_type",
        "display_label",
        "normalized_mileage_k",
        "mileage_k",
        "mileage_m",
        "review_required",
        "candidate_only",
        "runtime_safety_truth",
    ):
        if key in anchor:
            result[key] = anchor.get(key)
    return result


def _readable_route_anchor(item: dict[str, Any]) -> str:
    parts: list[str] = []
    checkpoint = item.get("nearest_checkpoint")
    if isinstance(checkpoint, dict) and checkpoint.get("label"):
        gap = checkpoint.get("distance_m")
        if gap is not None:
            parts.append(f"最近 {checkpoint['label']} 約 {round(float(gap))} m")
        else:
            parts.append(f"最近 {checkpoint['label']}")
    mileage = item.get("nearest_mileage_anchor")
    if isinstance(mileage, dict) and mileage.get("label"):
        gap = mileage.get("distance_m")
        if gap is not None:
            parts.append(f"近 {mileage['label']} 標註約 {round(float(gap))} m")
        else:
            parts.append(f"近 {mileage['label']} 標註")
    if item.get("distance_km") is not None:
        parts.append(f"GPX 累積約 {item['distance_km']} km")
    if item.get("lat") is not None and item.get("lon") is not None:
        parts.append(f"座標 {item['lat']},{item['lon']}")
    return "；".join(parts) if parts else "查詢範圍內"


def _score_100(value: Any) -> float:
    score = _optional_float(value)
    if score is None:
        return 0.0
    if 0.0 <= score <= 1.0:
        return score * 100.0
    return score


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
    if (
        re.search(r"各.*bucket|bucket.*(?:各|分別|多少|count)", lowered)
        or ("risk ribbon" in lowered and ("heatmap" in lowered or "heat map" in lowered))
        or "delta" in lowered
        or "差值" in lowered
    ):
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
        "very_high": 4,
        "extreme": 5,
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
