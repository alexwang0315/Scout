from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any


TERRAIN_SCORE_TOOL_ID = "pydantic_ai.tool.search_scout_terrain_scores.v0"

DEFAULT_TERRAIN_SCORE_LIMIT = 6
MAX_TERRAIN_SCORE_LIMIT = 12

_DIRECT_SLOPE_FIELDS = (
    "slope_degrees",
    "slope_degree",
    "slope_deg",
    "slope_angle_degrees",
    "slope_angle_deg",
    "slope_angle",
    "slope_macro",
    "slope_score",
)
_TERRAIN_SCORE_FIELDS = (
    "teii_20m",
    "tri",
    "sri",
    "lec",
    "pretrip_risk",
    "scp",
)


def search_project_terrain_scores(
    project_root: Path | str,
    *,
    query: str = "",
    metric: str = "auto",
    limit: int = DEFAULT_TERRAIN_SCORE_LIMIT,
    min_score: float | None = None,
    min_slope_degrees: float | None = None,
    distance_km_min: float | None = None,
    distance_km_max: float | None = None,
    cp: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float | None = None,
    sort: str = "auto",
) -> dict[str, Any]:
    """Search route-aligned terrain/slope model evidence.

    Scout's current route terrain samples may not contain direct slope degrees.
    When direct slope fields are missing, slope-oriented queries fall back to
    TEII_20m as a terrain-slope proxy and report that choice explicitly.
    """

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or root.name)
    parsed = _parse_query_filters(query)
    resolved_metric = _normalize_metric(metric, parsed.get("metric"))
    resolved_limit = _bounded_limit(limit)
    resolved_min_score = min_score if min_score is not None else parsed.get("min_score")
    resolved_min_slope = (
        min_slope_degrees
        if min_slope_degrees is not None
        else parsed.get("min_slope_degrees")
    )
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

    loaded_items, load_report = _load_terrain_items(root, project)
    metric_items = [_attach_metric(item, resolved_metric) for item in loaded_items]
    metric_items = [item for item in metric_items if item is not None]
    if resolved_metric == "slope" and any(
        item.get("slope_measurement_status") == "direct" for item in metric_items
    ):
        metric_items = [
            item
            for item in metric_items
            if item.get("slope_measurement_status") == "direct"
        ]
    summaries = _terrain_summaries(metric_items)
    filtered = [
        item
        for item in metric_items
        if _item_matches_filters(
            item,
            min_score=resolved_min_score,
            min_slope_degrees=resolved_min_slope,
            distance_km_min=resolved_distance_min,
            distance_km_max=resolved_distance_max,
            cp_anchor=cp_anchor,
            coordinate_anchor=coordinate_anchor,
            radius_m=resolved_radius_m,
        )
    ]
    filtered.sort(key=_sort_key(resolved_sort))
    results = filtered[:resolved_limit]
    compact_results = [_compact_result(item) for item in results]
    missing_fields = [] if compact_results else ["terrain_score_results"]
    answerability = (
        "terrain_score_decision_available"
        if compact_results
        else "terrain_score_missing_evidence"
    )
    decision = _terrain_decision(compact_results)
    field_answer = _field_answer(
        decision=decision,
        results=compact_results,
        answerability=answerability,
        metric=resolved_metric,
    )
    decision_output = _decision_output(
        decision=decision,
        results=compact_results,
        summaries=summaries,
        filters={
            "min_score": resolved_min_score,
            "min_slope_degrees": resolved_min_slope,
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
        metric=resolved_metric,
        missing_fields=missing_fields,
    )

    return {
        "tool_id": TERRAIN_SCORE_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "source_status": "candidate_only",
        "answerability": answerability,
        "decision": decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "terrain_decision": {
            "role": "Terrain / Slope Hazard Decision",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision,
            "decision_output": decision_output,
            "highest_terrain_result": compact_results[0] if compact_results else None,
            "next_action": decision_output["nextAction"],
        },
        "metric": resolved_metric,
        "filters": {
            "min_score": resolved_min_score,
            "min_slope_degrees": resolved_min_slope,
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
        "searched_sample_count": len(loaded_items),
        "matched_sample_count": len(filtered),
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


def _load_terrain_items(
    root: Path,
    project: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    for source in (
        {
            "refs": (("terrain_route_samples_ref", "terrain_route_samples"),),
            "fallbacks": (
                (
                    "outputs/layers/normalized/terrain_route_samples.geojson",
                    "terrain_route_samples",
                ),
                ("outputs/risk/route_risk.geojson", "risk_route_profile"),
            ),
            "feature_key": "features",
        },
        {
            "refs": (("terrain_risk_candidates_ref", "terrain_risk_candidates"),),
            "fallbacks": (
                (
                    "outputs/layers/candidates/terrain_risk_candidates.json",
                    "terrain_risk_candidates",
                ),
            ),
            "feature_key": "candidates",
        },
    ):
        source_path = None
        source_ref = None
        source_kind = None
        for key, kind in source["refs"]:
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
            for ref, kind in source["fallbacks"]:
                candidate = _project_path(root, ref)
                if candidate.exists():
                    source_path = candidate
                    source_ref = ref
                    source_kind = kind
                    break
        if source_path is None or source_kind is None:
            report.append(
                {
                    "source_kind": source["feature_key"],
                    "status": "missing",
                    "source_path": None,
                    "loaded_count": 0,
                }
            )
            continue
        payload = _load_json_object(source_path)
        raw_features = payload.get(source["feature_key"])
        if not isinstance(raw_features, list):
            raw_features = []
        loaded = []
        for index, raw in enumerate(raw_features):
            if not isinstance(raw, dict):
                continue
            item = _raw_to_terrain_item(
                raw,
                source_kind=str(source_kind),
                source_path=str(source_ref),
                index=index,
            )
            if item is not None:
                loaded.append(item)
        items.extend(loaded)
        report.append(
            {
                "source_kind": source_kind,
                "status": "loaded",
                "source_path": str(source_ref),
                "loaded_count": len(loaded),
                "artifact_kind": payload.get("artifact_kind")
                or (
                    payload.get("metadata", {}).get("artifact_kind")
                    if isinstance(payload.get("metadata"), dict)
                    else None
                ),
            }
        )
    return items, report


def _raw_to_terrain_item(
    raw: dict[str, Any],
    *,
    source_kind: str,
    source_path: str,
    index: int,
) -> dict[str, Any] | None:
    if source_kind == "terrain_risk_candidates":
        return _candidate_to_terrain_item(
            raw,
            source_kind=source_kind,
            source_path=source_path,
            index=index,
        )
    geometry = raw.get("geometry") if isinstance(raw.get("geometry"), dict) else {}
    properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    lat_lon = _representative_lat_lon(geometry.get("type"), geometry.get("coordinates"))
    if lat_lon is None:
        return None
    lat, lon = lat_lon
    distance = _optional_float(properties.get("distance_m"))
    start_distance = _optional_float(properties.get("start_distance_m"))
    end_distance = _optional_float(properties.get("end_distance_m"))
    if distance is None and start_distance is not None and end_distance is not None:
        distance = (start_distance + end_distance) / 2.0
    direct_slope_field, direct_slope_value = _first_numeric_field(
        properties,
        _DIRECT_SLOPE_FIELDS,
    )
    metrics = {
        field: _optional_float(properties.get(field))
        for field in (*_DIRECT_SLOPE_FIELDS, *_TERRAIN_SCORE_FIELDS)
        if _optional_float(properties.get(field)) is not None
    }
    if not metrics:
        return None
    return {
        "source_kind": source_kind,
        "source_path": source_path,
        "index": index,
        "lat": round(float(lat), 7),
        "lon": round(float(lon), 7),
        "distance_m": round(distance, 2) if distance is not None else None,
        "distance_km": round(distance / 1000.0, 3) if distance is not None else None,
        "start_distance_m": round(start_distance, 2) if start_distance is not None else None,
        "end_distance_m": round(end_distance, 2) if end_distance is not None else None,
        "route_id": properties.get("route_id"),
        "sample_id": properties.get("sample_id") or properties.get("terrain_sample_id"),
        "candidate_id": properties.get("candidate_id"),
        "terrain_sample_id": properties.get("terrain_sample_id"),
        "elevation_m": _optional_float(properties.get("elevation_m")),
        "risk_level": _optional_int(properties.get("risk_level")),
        "hazard_types": properties.get("hazard_types"),
        "explanation": properties.get("explanation"),
        "metrics": metrics,
        "direct_slope_field": direct_slope_field,
        "direct_slope_degrees": (
            round(direct_slope_value, 3) if direct_slope_value is not None else None
        ),
        "candidate_only": bool(properties.get("candidate_only", True)),
        "runtime_safety_truth": bool(properties.get("runtime_safety_truth", False)),
        "requires_human_review": bool(properties.get("requires_human_review", True)),
    }


def _candidate_to_terrain_item(
    raw: dict[str, Any],
    *,
    source_kind: str,
    source_path: str,
    index: int,
) -> dict[str, Any] | None:
    lat = _optional_float(raw.get("lat"))
    lon = _optional_float(raw.get("lon"))
    if lat is None or lon is None:
        return None
    risk_dimensions = (
        raw.get("risk_dimensions")
        if isinstance(raw.get("risk_dimensions"), dict)
        else {}
    )
    metrics = {
        field: _optional_float(risk_dimensions.get(field))
        for field in _TERRAIN_SCORE_FIELDS
        if _optional_float(risk_dimensions.get(field)) is not None
    }
    if not metrics:
        return None
    return {
        "source_kind": source_kind,
        "source_path": source_path,
        "index": index,
        "lat": round(float(lat), 7),
        "lon": round(float(lon), 7),
        "distance_m": _optional_float(raw.get("distance_m")),
        "distance_km": (
            round(float(raw["distance_m"]) / 1000.0, 3)
            if _optional_float(raw.get("distance_m")) is not None
            else None
        ),
        "candidate_id": raw.get("candidate_id"),
        "candidate_kind": raw.get("candidate_kind"),
        "reason": raw.get("reason"),
        "metrics": metrics,
        "direct_slope_field": None,
        "direct_slope_degrees": None,
        "candidate_only": bool(raw.get("candidate_only", True)),
        "runtime_safety_truth": bool(raw.get("runtime_safety_truth", False)),
        "requires_human_review": bool(raw.get("requires_human_review", True)),
    }


def _attach_metric(item: dict[str, Any], metric: str) -> dict[str, Any] | None:
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    metric_field = _metric_field(metric, metrics)
    if metric_field is None:
        return None
    score = _optional_float(metrics.get(metric_field))
    if score is None:
        return None
    attached = dict(item)
    attached["metric"] = metric
    attached["score"] = round(score, 3)
    attached["score_field"] = metric_field
    if metric == "slope" and metric_field not in _DIRECT_SLOPE_FIELDS:
        attached["slope_measurement_status"] = (
            "proxy_from_teii_no_direct_slope_degrees"
        )
    elif metric_field in _DIRECT_SLOPE_FIELDS:
        attached["slope_measurement_status"] = "direct"
    else:
        attached["slope_measurement_status"] = "not_slope_query"
    return attached


def _metric_field(metric: str, metrics: dict[str, Any]) -> str | None:
    if metric == "slope":
        for field in _DIRECT_SLOPE_FIELDS:
            if field in metrics:
                return field
        return "teii_20m" if "teii_20m" in metrics else None
    if metric in {"terrain", "teii"}:
        return "teii_20m" if "teii_20m" in metrics else _first_key(metrics, _TERRAIN_SCORE_FIELDS)
    if metric in metrics:
        return metric
    if metric == "pretrip_risk":
        return "pretrip_risk" if "pretrip_risk" in metrics else None
    return "teii_20m" if "teii_20m" in metrics else _first_key(metrics, _TERRAIN_SCORE_FIELDS)


def _item_matches_filters(
    item: dict[str, Any],
    *,
    min_score: float | None,
    min_slope_degrees: float | None,
    distance_km_min: float | None,
    distance_km_max: float | None,
    cp_anchor: dict[str, Any] | None,
    coordinate_anchor: dict[str, float] | None,
    radius_m: float | None,
) -> bool:
    if min_score is not None and float(item["score"]) < float(min_score):
        return False
    direct_slope = item.get("direct_slope_degrees")
    if min_slope_degrees is not None and (
        direct_slope is None or float(direct_slope) < float(min_slope_degrees)
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


def _compact_result(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "metric",
        "source_kind",
        "source_path",
        "score",
        "score_field",
        "slope_measurement_status",
        "direct_slope_field",
        "direct_slope_degrees",
        "distance_km",
        "distance_m",
        "start_distance_m",
        "end_distance_m",
        "lat",
        "lon",
        "elevation_m",
        "risk_level",
        "route_id",
        "sample_id",
        "candidate_id",
        "candidate_kind",
        "terrain_sample_id",
        "hazard_types",
        "explanation",
        "reason",
        "anchor_distance_m",
        "candidate_only",
        "runtime_safety_truth",
        "requires_human_review",
    )
    compact = {key: item.get(key) for key in keys if item.get(key) is not None}
    metrics = item.get("metrics")
    if isinstance(metrics, dict):
        compact["terrain_dimensions"] = {
            key: round(value, 3) if isinstance(value, float) else value
            for key, value in metrics.items()
            if key in _TERRAIN_SCORE_FIELDS
        }
    return compact


def _terrain_summaries(items: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for field in (*_DIRECT_SLOPE_FIELDS, *_TERRAIN_SCORE_FIELDS):
        values = []
        for item in items:
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            value = _optional_float(metrics.get(field))
            if value is not None:
                values.append(value)
        if not values:
            continue
        summaries[field] = {
            "available": True,
            "count": len(values),
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "mean": round(mean(values), 3),
        }
    summaries["direct_slope_degrees_available"] = any(
        item.get("direct_slope_degrees") is not None for item in items
    )
    return summaries


def _terrain_decision(results: list[dict[str, Any]]) -> str:
    if not results:
        return "DELAY"
    top = results[0]
    score = _score_100(top.get("score"))
    direct_slope = _optional_float(top.get("direct_slope_degrees"))
    if direct_slope is not None and direct_slope >= 35.0:
        return "NO_GO"
    if score >= 90.0:
        return "NO_GO"
    if direct_slope is not None and direct_slope >= 25.0:
        return "CHANGE_PLAN"
    if score >= 70.0:
        return "CHANGE_PLAN"
    if direct_slope is not None and direct_slope >= 15.0:
        return "CONDITIONAL_GO"
    if score >= 40.0:
        return "CONDITIONAL_GO"
    return "GO"


def _field_answer(
    *,
    decision: str,
    results: list[dict[str, Any]],
    answerability: str,
    metric: str,
) -> str:
    if not results:
        return (
            f"地形分數判斷：建議 DELAY。metric={metric} 沒有匹配到可追溯的地形/坡度樣本；"
            "Scout 不能用空資料推論地形可通過性。"
        )
    top = results[0]
    return (
        f"地形分數判斷：建議 {decision}。最高候選地形點位於 {_result_location(top)}，"
        f"metric={metric}、score={top.get('score')}、"
        f"slope={top.get('direct_slope_degrees') or 'not_available'}。"
        f"下一步：{_next_action(decision=decision)} "
        f"answerability={answerability}；此為候選地形證據，不是 runtime safety truth。"
    )


def _decision_output(
    *,
    decision: str,
    results: list[dict[str, Any]],
    summaries: dict[str, Any],
    filters: dict[str, Any],
    answerability: str,
    field_answer: str,
    metric: str,
    missing_fields: list[str],
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    top = results[0] if results else {}
    reasons = _decision_reasons(decision=decision, results=results, metric=metric)
    uncertainty_notes = _uncertainty_notes(
        results=results,
        summaries=summaries,
        missing_fields=missing_fields,
        metric=metric,
    )
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision, top=top),
        "reason": " / ".join(reasons[:2]),
        "nextStep": _next_action(decision=decision),
    }
    residual_risk = [
        "Terrain scores are candidate planning evidence only.",
        (
            "Slope and terrain proxy scores must be reconciled with weather, pace, "
            "route readiness, and live observations."
        ),
        "No /safety, SOS, outbound send, runtime mutation, or hardware control was performed.",
    ]
    second_layer = {
        "details": _decision_details(
            top=top,
            results=results,
            filters=filters,
            field_answer=field_answer,
            metric=metric,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": _required_conditions(decision=decision),
        "alternativeActions": _alternative_actions(decision=decision),
    }
    return {
        "role": "Terrain Hazard Sentinel",
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
        "action": "terrain_score_hazard_review",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "highestScore": top.get("score"),
            "highestScore100": _score_100(top.get("score")) if top else None,
            "highestMetric": metric,
            "highestDistanceKm": top.get("distance_km"),
            "directSlopeDegrees": top.get("direct_slope_degrees"),
            "matchedSampleCount": len(results),
            "timeBufferChangeMinutes": 0 if not allowed else None,
            "bufferPolicy": (
                "Unplanned stops, photo goals, and summit pushes are not granted "
                "by terrain scores."
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
    metric: str,
) -> list[str]:
    if not results:
        return [f"沒有匹配到 metric={metric} 的可追溯地形/坡度樣本。"]
    top = results[0]
    reasons = [
        f"最高候選地形 score={top.get('score')} metric={metric}。",
        f"位置：{_result_location(top)}。",
    ]
    direct_slope = top.get("direct_slope_degrees")
    if direct_slope is not None:
        reasons.append(f"direct_slope_degrees={direct_slope}。")
    elif top.get("slope_measurement_status"):
        reasons.append(f"slope_measurement_status={top.get('slope_measurement_status')}。")
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        reasons.append("地形分數或坡度已達需要改變路線/通過策略的保守門檻。")
    elif decision == "CONDITIONAL_GO":
        reasons.append("地形分數或坡度顯示需要條件式通過與重查。")
    else:
        reasons.append("目前匹配結果未達高地形風險門檻。")
    return _dedupe(reasons)


def _uncertainty_notes(
    *,
    results: list[dict[str, Any]],
    summaries: dict[str, Any],
    missing_fields: list[str],
    metric: str,
) -> list[str]:
    notes = [f"Missing field: {field}" for field in missing_fields]
    if not results:
        notes.append(f"No matching terrain score result was available for metric={metric}.")
    if not summaries.get("direct_slope_degrees_available"):
        notes.append("Direct slope degrees are not available; terrain scores may be proxies.")
    if results and results[0].get("slope_measurement_status") == (
        "proxy_from_teii_no_direct_slope_degrees"
    ):
        notes.append("Top slope result uses TEII proxy instead of direct slope degrees.")
    return _dedupe(notes)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "NO_GO":
        return "不建議進入最高地形風險路段。"
    if decision == "CHANGE_PLAN":
        return "建議改變地形通過策略。"
    if decision == "CONDITIONAL_GO":
        return "可有條件通過，但必須快速通過並重查。"
    if decision == "GO" and allowed:
        return "可作為低地形風險候選路段通過。"
    return "暫緩地形分數判斷。"


def _decision_limit_phrase(*, decision: str, top: dict[str, Any]) -> str:
    location = _result_location(top) if top else "目前查詢範圍"
    if decision == "NO_GO":
        return f"{location} 不得作為原計畫通過或停留目標；先改線、撤退或人工複核。"
    if decision == "CHANGE_PLAN":
        return f"{location} 不得直接照原節奏通過；先改線、縮短目標或設定人工確認點。"
    if decision == "CONDITIONAL_GO":
        return f"{location} 只能快速通過，不得為拍照、休息或攻頂增加停留；下一 CP 前重查。"
    if decision == "GO":
        return "仍需依風險分數、天氣、日照、隊伍與 CP Graph 重查；此回答不是停留授權。"
    return "補齊可追溯地形/坡度樣本前，不得把此回答當成路線 permission。"


def _next_action(*, decision: str) -> str:
    if decision == "NO_GO":
        return "改線、撤退到上一個安全 CP，或交由人工複核後重新規劃。"
    if decision == "CHANGE_PLAN":
        return "改短版/替代路線，並用 risk score、weather、pace 與 route readiness 重新評估。"
    if decision == "CONDITIONAL_GO":
        return "快速通過並在下一 CP 前重查地形、天氣與隊伍狀態。"
    if decision == "GO":
        return "維持保守節奏，下一 CP 或條件改變時重查。"
    return "補齊 terrain route samples、坡度或候選地形證據後再判斷。"


def _required_conditions(*, decision: str) -> list[str]:
    conditions = [
        "不得將地形分數升格為 runtime safety truth。",
        "通過前仍需核對 risk score、weather/daylight、pace、team status 與 route readiness。",
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
        return ["改短版。", "避開最高地形風險段。", "改由更保守 CP Graph 重新排程。"]
    if decision == "CONDITIONAL_GO":
        return ["快速通過。", "降低速度與隊伍間距。", "在下一 CP 重查後再決定。"]
    if decision == "GO":
        return ["維持原路線但保守通過。", "若天氣或隊伍狀態改變則重新評估。"]
    return ["補齊 terrain route samples 或坡度證據。", "改問具體 CP 或里程範圍。"]


def _decision_details(
    *,
    top: dict[str, Any],
    results: list[dict[str, Any]],
    filters: dict[str, Any],
    field_answer: str,
    metric: str,
) -> list[str]:
    details = [field_answer, f"metric={metric}", f"matched_result_count={len(results)}"]
    if top:
        details.extend(
            [
                f"top_score={top.get('score')}",
                f"top_distance_km={top.get('distance_km')}",
                f"top_slope={top.get('direct_slope_degrees')}",
                f"top_source_kind={top.get('source_kind')}",
            ]
        )
    details.append("filters=" + json.dumps(filters, ensure_ascii=False, sort_keys=True))
    return details


def _result_location(item: dict[str, Any]) -> str:
    if item.get("distance_km") is not None:
        return f"{item.get('distance_km')} km"
    if item.get("candidate_id"):
        return f"candidate {item.get('candidate_id')}"
    if item.get("sample_id"):
        return f"sample {item.get('sample_id')}"
    if item.get("lat") is not None and item.get("lon") is not None:
        return f"{item.get('lat')},{item.get('lon')}"
    return "查詢範圍內"


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
    if re.search(r"slope|坡度|斜率|陡坡|坡|slope[-_ ]?macro", lowered):
        parsed["metric"] = "slope"
    if re.search(r"\bteii\b|地形容錯|低容錯|terrain error", lowered):
        parsed["metric"] = "teii"
    if re.search(r"\btri\b|terrain risk index|群聚", lowered):
        parsed["metric"] = "tri"
    if re.search(r"\bsri\b|sudden|突然|突增", lowered):
        parsed["metric"] = "sri"
    if re.search(r"\blec\b|local exposure|暴露", lowered):
        parsed["metric"] = "lec"
    if re.search(r"pretrip|整體|風險", lowered) and not parsed.get("metric"):
        parsed["metric"] = "pretrip_risk"
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
    threshold_match = re.search(r"(?:score|分數)\s*(?:>=|大於|超過)\s*(\d+(?:\.\d+)?)", lowered)
    if threshold_match:
        parsed["min_score"] = float(threshold_match.group(1))
    slope_threshold_match = re.search(
        r"(?:slope|坡度|陡坡|坡)\s*(?:>=|大於|超過)?\s*"
        r"(\d+(?:\.\d+)?)\s*(?:deg|degree|度)",
        lowered,
    )
    if slope_threshold_match:
        parsed["min_slope_degrees"] = float(slope_threshold_match.group(1))
    if re.search(r"最高|最陡|top|highest|max|最大|危險", lowered):
        parsed["sort"] = "score_desc"
    if re.search(r"附近|near|周邊", lowered):
        parsed["sort"] = "anchor_distance_asc"
    return parsed


def _normalize_metric(value: str, parsed_metric: Any) -> str:
    candidate = str(value or "").strip().lower() or str(parsed_metric or "terrain")
    if candidate == "auto" and parsed_metric:
        candidate = str(parsed_metric).strip().lower()
    aliases = {
        "terrain": "terrain",
        "all": "terrain",
        "teii_20m": "teii",
        "teii": "teii",
        "slope": "slope",
        "slope_degrees": "slope",
        "slope_macro": "slope",
        "tri": "tri",
        "sri": "sri",
        "lec": "lec",
        "pretrip_risk": "pretrip_risk",
        "risk": "pretrip_risk",
        "scp": "scp",
    }
    return aliases.get(candidate, "terrain")


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


def _first_numeric_field(
    values: dict[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, float | None]:
    for key in keys:
        value = _optional_float(values.get(key))
        if value is not None:
            return key, value
    return None, None


def _first_key(values: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in values:
            return key
    return None


def _bounded_limit(value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_TERRAIN_SCORE_LIMIT
    return max(1, min(parsed, MAX_TERRAIN_SCORE_LIMIT))


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
