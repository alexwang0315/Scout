"""Execute real deterministic assessors against a version-bound Planned view."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scout_planned_analysis_inputs import (
    BOUNDARY, build_planned_analysis_inputs, distance_m, items,
    parse_time, read_json, safe_path, write_json,
)
from scout_planned_route_models import PlannedRouteConflict


PRODUCER_VERSION = "planned-analysis-producers.v2"
ROLES = ("architecture", "weather", "pace_fit", "permission", "navigation", "route_context")
# These are source inputs, never old Golden route assessments or review receipts.
OWNER_SOURCE_REFS = {
    "team_status_ref": "outputs/team_status.json",
    "resource_plan_ref": "outputs/resource_plan.json",
    "energy_vitals_ref": "outputs/energy_vitals.json",
    "readiness_report_ref": "outputs/readiness_report.json",
    "weather_points_ref": "normalized/weather/forecast_snapshots.json",
    "forecast_snapshots_ref": "normalized/weather/forecast_snapshots.jsonl",
    "cwa_forecast_timeline_ref": "outputs/environment/cwa/forecast_timeline.json",
    "weather_warnings_ref": "normalized/weather/warnings.json",
    "mcp_candidates_ref": "outputs/mcp/mcp_candidates.json",
    "mcp_named_point_evidence_ref": "outputs/mcp/named_point_evidence.json",
    "mcp_ocr_labels_ref": "outputs/mcp/mcp_ocr_labels.json",
    "web_case_evidence_ref": "outputs/layers/normalized/web_case_evidence.json",
    "raster_label_evidence_ref": "outputs/layers/normalized/raster_label_evidence.geojson",
    "route_note_candidates_ref": "candidates/route_note_candidates.json",
}


def _missing(code: str, reason: str, **extra: Any) -> dict:
    return {"code": code, "reason": reason, **extra}


def _unique_missing(values: list[dict]) -> list[dict]:
    keys = ("code", "segment_id", "day_id", "point_index", "member_id", "item")
    return list({tuple(str(v.get(key, "")) for key in keys): v for v in values}.values())


def _review_missing(inputs: dict, *prefixes: str) -> list[dict]:
    return [v for v in inputs.get("review_context", {}).get("missing_inputs", [])
            if v["code"] == "planned_review_context" or any(v["code"].startswith(p) for p in prefixes)]


def _materialize_review(owner_root: Path, bundle: dict, root: Path, inputs: dict,
                        source_report: list[dict]) -> None:
    from scout_planned_review_context import STORE_REF, materialize_planned_review_inputs
    if (owner_root / STORE_REF).is_dir() or bundle.get("analysis_review_context"):
        context = materialize_planned_review_inputs(owner_root, bundle, root, inputs["graph"],
                                                     context=bundle.get("analysis_review_context"))
    else:
        # Pure preview replays may not have a persisted version. No declaration
        # is consumable until the separately validated context store exists.
        context = {"status": "missing", "project_refs": {}, "source_report": [],
                   "input_hashes": {}, "segment_policy_updates": [], "checkpoint_reviews": [],
                   "assessor_kwargs": {}, "narrative": None,
                   "missing_inputs": [_missing("planned_review_context", "No same-version supplement has been saved.")]}

    inputs["review_context"] = context
    project = read_json(root, "project.json")
    project.update(context["project_refs"])
    write_json(root, "project.json", project)
    source_report.extend(context["source_report"])
    inputs["input_hashes"].update(context["input_hashes"])
    policies = {p["segment_id"]: p for p in context["segment_policy_updates"]}
    rows = read_json(root, project["segment_policy_candidates_ref"])
    for row in rows:
        review = policies.get(row["segment_candidate_id"])
        if review:
            row["requirement"].update(review["requirement"])
            row.update(unknown_requirements=review["unknown_requirements"], review=review["review"],
                       evidence_role=review["evidence_role"])
    inputs["input_hashes"][project["segment_policy_candidates_ref"]] = write_json(root, project["segment_policy_candidates_ref"], rows)
    for edge in inputs["graph"]["edges"]:
        policy = policies.get(edge["candidate_id"])
        for key in ("requires_daylight", "water_available", "retreat_available", "signal_expected"):
            edge[key] = (policy or {}).get("requirement", {}).get(key)
        if policy:
            edge["policy_review"] = policy["review"]
    for node in inputs["graph"]["nodes"]:
        review = next((v for v in context["checkpoint_reviews"] if v["point_index"] == node["point_index"]), None)
        if review:
            node["checkpoint_review"] = review
    write_json(root, "outputs/planned_cp_graph.json", inputs["graph"])


def _copy_sources(owner_root: Path, root: Path, source_report: list[dict]) -> None:
    """Copy an explicit allowlist; no links, directory scans, .env or old outputs."""
    owner = read_json(owner_root, "project.json")
    project = read_json(root, "project.json")
    for key, fallback in OWNER_SOURCE_REFS.items():
        ref = owner.get(key) or fallback
        if not isinstance(ref, str):
            continue
        path = safe_path(owner_root, ref)
        if not path.is_file():
            continue
        raw = path.read_bytes()
        suffix = path.suffix if path.suffix in {".json", ".jsonl", ".geojson"} else ".json"
        target_ref = f"inputs/sources/{key}{suffix}"
        target = safe_path(root, target_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        project[key] = target_ref
        source_report.append({"scope": "owner", "ref": ref, "sha256": hashlib.sha256(raw).hexdigest(),
                              "input_ref": target_ref, "ref_key": key, "role": "source_evidence"})
    write_json(root, "project.json", project)


def _field_missing(result: dict) -> list[dict]:
    return [_missing(str(code), "The deterministic assessor requires this input.")
            for code in result.get("missing_fields", []) if isinstance(code, str)]


def _architecture(root: Path, inputs: dict, preparation: dict) -> tuple[dict, list[dict]]:
    from scout_route_architecture_tool import assess_scout_route_architecture

    result = assess_scout_route_architecture(root, query="路線結構、CP 邊與候選行程時間分析", limit=16)
    result["full_route_graph"] = inputs["graph"]
    result["route_axis"] = inputs["route_axis"]
    result["planned_timetable"] = inputs["planned_eta"]
    result["route_distance_m"] = inputs["route_summary"]["distance_m"]
    result["analysis_axis_role"] = "recorded_original_order" if inputs.get("is_recorded") else "planned_original_order"
    result["historical_observations_created"] = False
    result["reference_segment_timing"] = inputs["historical_passages"]
    result["route_terrain_analysis"] = inputs["terrain_analysis"]
    # The legacy CP graph defaults absent policy booleans to False. Make their
    # absence explicit rather than reporting them as measured terrain facts.
    by_id = {e["candidate_id"]: e for e in inputs["graph"]["edges"]}
    for edge in result.get("cp_graph", {}).get("edges", []):
        reviewed = by_id.get(edge.get("segment_candidate_id") or edge.get("candidate_id") or edge.get("segment_id"), {})
        for field in ("requires_daylight", "retreat_available", "water_available", "signal_expected"):
            edge[field] = reviewed.get(field)
    missing = _field_missing(result)
    missing.extend(_missing(g.get("code", "recording_gap"), g.get("reason", "Source recording has a preserved gap.")) for g in inputs["gaps"])
    missing.extend(_review_missing(inputs, "planned_segment", "planned_route_condition"))
    for segment_id in inputs["historical_passages"]["unmatched_segment_ids"]:
        missing.append(_missing("historical_passage_unmatched", "Historical GPX matching ran but found no qualifying passage for this Planned edge.", segment_id=segment_id))
    if inputs["terrain_analysis"]["coverage"]["unsupported_point_indices"]:
        missing.append(_missing("planned_terrain_nodata", "Some new route points have no supported DEM sample."))
    return result, missing


def _pace(root: Path, inputs: dict, preparation: dict) -> tuple[dict, list[dict]]:
    from scout_pace_guardian_tool import assess_scout_pace_guardian

    edges = inputs["graph"]["edges"]
    contexts = []
    for day in items(inputs["itinerary"], "days"):
        day_edges = [s for s in edges if s["start_point_index"] >= day.get("start_point_index", 0)
                     and s["end_point_index"] <= day.get("end_point_index", len(inputs["route_axis"])) and s["distance_m"] > .01]
        contexts.extend((day, edge) for edge in day_edges)
    if not contexts:
        contexts = [({}, edges[0] if edges else None)]
    assessments, missing = [], []
    for day, edge in contexts:
        assessment = assess_scout_pace_guardian(
            root, query="Planned 每日首段與隊伍腳程適配分析",
            current_time=edge.get("eta_from") if edge else day.get("departure_at"),
            next_cp_id=edge.get("to_candidate_id") if edge else None,
            planned_eta_path="outputs/planned_eta.json",
            **inputs.get("review_context", {}).get("assessor_kwargs", {}).get("pace_fit", {}),
        )
        assessments.append({"day_id": day.get("day_id"), "segment_id": edge.get("candidate_id") if edge else None,
                            "assessment": assessment})
        missing.extend(_field_missing(assessment))
    missing.extend(_review_missing(inputs, "planned_team", "planned_member", "planned_equipment"))
    if any(s.get("expected_duration_minutes") is None for s in edges):
        missing.append(_missing("planned_segment_time", "Some Planned segments have unknown duration; no pace was invented."))
    day_assessments = list({a["day_id"]: a for a in reversed(assessments)}.values())
    result = {**assessments[0]["assessment"], "day_assessments": day_assessments, "segment_assessments": assessments,
              "planned_days": inputs["itinerary"].get("days", []), "planned_segments": edges,
              "planned_timetable": inputs["planned_eta"], "historical_observations_created": False,
              "reference_segment_timing": inputs["historical_passages"]}
    return result, missing


def _permission(root: Path, inputs: dict, preparation: dict) -> tuple[dict, list[dict]]:
    from scout_contextual_permission_tool import assess_scout_contextual_permission

    events = [{**e, "point_index": e.get("point_index", e.get("start_point_index")),
               "duration_minutes": e.get("duration_minutes", e.get("duration_seconds", 0) / 60)}
              for e in items(inputs["itinerary"], "timeline") if e.get("kind") in {"fixed_stop", "camp", "rest", "stop"}]
    if not events:
        events = [{"kind": "planned_route_review", "duration_minutes": None, "point_index": 0}]
    reviews = {v["point_index"]: v for v in inputs.get("review_context", {}).get("assessor_kwargs", {}).get("permission", [])}
    existing = {e.get("point_index") for e in events}
    events.extend({"kind": "planned_checkpoint_review", "duration_minutes": None, "point_index": i}
                  for i in reviews if i not in existing)
    assessments, missing = [], []
    for event in events:
        cp = next((c for c in inputs["graph"]["nodes"] if c["point_index"] == event.get("point_index")), None)
        result = assess_scout_contextual_permission(
            root, query="人工規劃的停留時間是否具备足夠證據可供後分析", action="stop",
            current_cp_id=cp["candidate_id"] if cp else None,
            requested_duration_minutes=event.get("duration_minutes"),
            planned_eta_path="outputs/planned_eta.json",
            **reviews.get(event.get("point_index"), {}).get("kwargs", {}),
            # Scheduled travel time is not spare safety buffer. Do not activate
            # the legacy ETA-to-buffer fallback with a simulated current_time.
        )
        assessments.append({"event": event, "checkpoint_id": cp["candidate_id"] if cp else None, "assessment": result})
        missing.extend(_field_missing(result))
    missing.extend(_review_missing(inputs, "planned_permission"))
    if any(e.get("point_index") not in reviews for e in events):
        missing.append(_missing("planned_permission_review_evidence", "Some planned stops have no same-version buffer and condition review."))
    return {**assessments[0]["assessment"], "assessments": assessments, "rules": [a["assessment"].get("contextual_permission") for a in assessments],
            "planned_timetable": inputs["planned_eta"], "planned_stops": events,
            "safety_buffer_derived_from_travel_time": False}, missing


def _weather_records(root: Path, project: dict) -> list[dict]:
    values = []
    for key in ("weather_points_ref", "forecast_snapshots_ref", "cwa_forecast_timeline_ref"):
        ref = project.get(key)
        if not ref:
            continue
        path = safe_path(root, ref)
        if path.suffix == ".jsonl":
            import json
            payload = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        else:
            payload = read_json(root, ref)
        values.extend(items(payload, "weather_points", "forecast_snapshots", "points", "records", "timeline"))
    return values


def _weather(root: Path, inputs: dict, preparation: dict) -> tuple[dict, list[dict]]:
    from scout_weather_integration import build_route_weather_package, compact_wx_alerts
    from scout_weather_window_tool import assess_scout_weather_window

    project = read_json(root, "project.json")
    raw_points = _weather_records(root, project)
    points = raw_points
    if inputs.get("is_recorded"):
        # Future/current forecasts are never observations of a completed trip.
        points = [p for p in raw_points if (p.get("evidence_role") or p.get("observation_kind"))
                  in {"historical_weather_observation", "weather_observation"}]
    matched, package_segments, missing = [], [], []
    for segment in inputs["graph"]["edges"]:
        start, end = parse_time(segment.get("eta_from")), parse_time(segment.get("eta_to"))
        if start is None or end is None:
            missing.append(_missing("planned_weather_eta", "Weather cannot be joined to a segment with unknown ETA.", segment_id=segment["candidate_id"]))
            continue
        candidates = []
        for point in points:
            valid_from = parse_time(point.get("validFrom") or point.get("valid_from"))
            valid_to = parse_time(point.get("validTo") or point.get("valid_to"))
            if not valid_from or not valid_to or valid_from > start or valid_to < end:
                continue
            try:
                separation = distance_m(segment, point)
            except (TypeError, ValueError, KeyError):
                continue
            # A nearby geolocated forecast is a candidate association, not a
            # claim that a township name alone covers a newly added branch.
            if separation <= 10000:
                candidates.append((separation, point))
        if not candidates:
            missing.append(_missing("forecast_spatiotemporal_coverage", "No geolocated forecast covers this Planned segment and its full time interval.", segment_id=segment["candidate_id"]))
            continue
        separation, raw = min(candidates, key=lambda value: value[0])
        point = {**raw, "validFrom": raw.get("validFrom") or raw.get("valid_from"),
                 "validTo": raw.get("validTo") or raw.get("valid_to")}
        issued_at = point.get("issued_at") or point.get("generatedAt")
        if parse_time(issued_at) is None:
            missing.append(_missing("forecast_issue_time", "Forecast issue time is unknown; recomputation time is not source freshness.", segment_id=segment["candidate_id"]))
        weather_segment = {"segmentId": segment["candidate_id"], "fromM": segment["from_m"], "toM": segment["to_m"],
                           "etaFrom": segment["eta_from"], "etaTo": segment["eta_to"], "township": point.get("areaName")}
        package = build_route_weather_package(route_id=inputs["subject_binding"]["version_id"], route_segments=[weather_segment],
                                              weather_points=[point], generated_at=issued_at)
        package_segments.extend(package["segments"])
        matched.append({"segment_id": segment["candidate_id"], "forecast_distance_m": round(separation, 3),
                        "valid_from": point["validFrom"], "valid_to": point["validTo"],
                        "method": "full_time_interval_and_geolocated_point_within_10km_candidate"})
    if package_segments:
        # Retain only successfully matched segments; legacy fallback selection
        # never sees an unrelated or out-of-date forecast.
        package["segments"] = package_segments
        package["wx_alerts"] = compact_wx_alerts(package_segments)
        package["input_binding"] = inputs["subject_binding"]
        package["terrain_interaction_status"] = "unknown_without_planned_terrain_risk"
        package["valid_from"] = min(m["valid_from"] for m in matched)
        package["valid_to"] = package["validUntil"] = max(m["valid_to"] for m in matched)
        write_json(root, "outputs/route_weather_package.json", package)
        project["route_weather_package_ref"] = "outputs/route_weather_package.json"
        write_json(root, "project.json", project)
    result = assess_scout_weather_window(root, query="Planned 路段天氣與日照 buffer 後分析",
                                         planned_eta_path="outputs/planned_eta.json",
                                         current_time=next((d.get("departure_at") for d in items(inputs["itinerary"], "days") if d.get("departure_at")), None), limit=24)
    missing.extend(_field_missing(result))
    if inputs.get("is_recorded") and not matched:
        missing.append(_missing("historical_weather_observations", "No genuine weather observation covers this recorded interval; current forecasts were excluded."))
    missing.append(_missing("planned_terrain_weather_interaction", "Terrain-weather interaction must use verified risk samples on this Planned axis; no Golden risk was reused."))
    return {**result, "segment_matches": matched, "planned_segments": inputs["graph"]["edges"],
            "matched_segment_count": len(matched), "source_forecast_point_count": len(points),
            "historical_weather_status": "observations_matched" if inputs.get("is_recorded") and matched else "unknown",
            "current_forecasts_excluded": len(raw_points) - len(points) if inputs.get("is_recorded") else 0,
            "new_package_built": bool(package_segments)}, missing


def _navigation(root: Path, inputs: dict, preparation: dict) -> tuple[dict, list[dict]]:
    from pretrip_navigation_terrain_collection import collect_pretrip_navigation_terrain

    result = collect_pretrip_navigation_terrain(root, dry_run=True,
        **inputs.get("review_context", {}).get("assessor_kwargs", {}).get("navigation", {}))
    result["planned_route_axis"] = inputs["route_axis"]
    result["planned_route_graph"] = inputs["graph"]
    result["route_terrain_analysis"] = inputs["terrain_analysis"]
    result["terrain_parts"] = inputs["terrain_analysis"]["source_parts"]
    result["map_sources"] = preparation.get("map_sources", [])
    result["coverage"] = preparation.get("coverage", {})
    missing = _field_missing(result)
    missing.extend(_review_missing(inputs, "planned_navigation", "planned_equipment"))
    missing.extend(_missing(g.get("code") or "terrain_preparation_gap", g.get("reason") or str(g))
                   for g in preparation.get("gaps", []) if isinstance(g, dict))
    if not preparation.get("terrain_parts"):
        missing.append(_missing("planned_terrain_projection", "No terrain part outputs have been prepared for this Planned route."))
    if inputs["terrain_analysis"]["coverage"]["unsupported_point_indices"]:
        missing.append(_missing("planned_terrain_coverage", "Native DEM matching ran; some Planned points have no supported terrain sample."))
    return result, missing


def _project_context_point(point: dict, axis: list[dict]) -> dict | None:
    try:
        separations = [(distance_m(point, p), p) for p in axis]
    except (KeyError, TypeError, ValueError):
        return None
    nearest, vertex = min(separations, key=lambda item: item[0])
    if nearest > 500:
        return None
    visits = sorted({round(float(p["route_order_m"]), 3) for gap, p in separations if gap <= nearest + 2})
    value = {**point, "route_distance_m": visits[0] if len(visits) == 1 else None,
             "planned_route_visit_distances_m": visits, "planned_point_index": vertex["point_index"],
             "planned_route_off_axis_m": round(nearest, 3),
             "projection_method": "nearest_planned_axis_vertex_with_repeated_visits_preserved", **BOUNDARY}
    return value


def _context(root: Path, inputs: dict, preparation: dict) -> tuple[dict, list[dict]]:
    from pretrip_route_context_collection import collect_pretrip_route_context

    collection = collect_pretrip_route_context(root, write_briefing=False, route_note_point_policy="seed_only")
    points_ref = collection["outputs"]["route_context_points_ref"]
    raw = read_json(root, points_ref)
    records = items(raw, "points", "route_context_points", "candidates")
    projected = [value for p in records if (value := _project_context_point(p, inputs["route_axis"])) is not None]
    payload = {"artifact_kind": "planned_route_context_points", "project_id": inputs["subject_binding"]["project_id"],
               "points": projected, "input_binding": inputs["subject_binding"], **BOUNDARY}
    write_json(root, points_ref, payload)
    missing = [_missing(f"route_context_{s['source_kind']}", "This route-context input is missing or empty.")
               for s in collection.get("source_report", []) if s.get("required_by_standard_sec6") and s.get("status") != "loaded"]
    if not projected:
        missing.append(_missing("planned_context_points", "No sourced context point could be projected within 500 m of the Planned route."))
    narrative = inputs.get("review_context", {}).get("narrative") or {}
    reviewed = narrative.get("binding_valid") is True and narrative.get("review", {}).get("status") == "reviewed"
    if not reviewed:
        missing.append(_missing("planned_briefing_review", "A reviewed narrative briefing with this exact Planned binding is still required."))
    missing.extend(_review_missing(inputs, "planned_narrative", "planned_route_condition"))
    return {"collection": collection, "points": projected, "planned_route_axis": inputs["route_axis"],
            "point_count": len(projected), "excluded_unlocated_or_outside_route_count": len(records) - len(projected),
            "briefing_ref": narrative.get("briefing_ref") if reviewed else None,
            "narrative_input": narrative, "r4_review_promoted": False}, missing


def _summary(role: str, result: dict, missing: list[dict]) -> str:
    if role == "architecture":
        graph = result.get("full_route_graph", {})
        detail = f"新路線 {len(graph.get('nodes', []))} 個 CP、{len(graph.get('edges', []))} 條 CP 邊；{len(graph.get('gaps', []))} 處幾何缺口"
    elif role == "pace_fit":
        detail = f"已評估 {len(result.get('segment_assessments', []))} 條 CP 邊腳程，保留完整 Planned 日程"
    elif role == "permission":
        detail = f"已評估 {len(result.get('assessments', []))} 個規劃停留；移動時間未當成安全餘裕"
    elif role == "weather":
        detail = f"{result.get('matched_segment_count', 0)} 段具相符時空預報；歷史天氣未知"
    elif role == "navigation":
        coverage = result.get("route_terrain_analysis", {}).get("coverage", {})
        detail = f"已重算新路線地圖需求；{coverage.get('sampled_point_count', 0)}/{coverage.get('point_count', 0)} 點具原生 DEM 取樣"
    else:
        detail = f"已重新收集並投影 {result.get('point_count', 0)} 個有來源的路線脈絡點"
    return f"{detail}；尚缺 {len(missing)} 類必要資料" if missing else detail


def _public_result(role: str, result: dict) -> dict:
    """Keep complete raw evidence in the artifact, not every polling response."""
    common = {k: result[k] for k in ("decision", "answerability", "field_answer", "tool_id", "error_type") if k in result}
    if role == "architecture":
        graph, history = result.get("full_route_graph", {}), result.get("reference_segment_timing", {})
        common.update(cp_graph=result.get("cp_graph"), route_architecture=result.get("route_architecture"),
                      route_distance_m=result.get("route_distance_m"),
                      graph_counts={"nodes": len(graph.get("nodes", [])), "edges": len(graph.get("edges", [])), "gaps": len(graph.get("gaps", []))},
                      historical_coverage=history.get("coverage"), historical_counts=history.get("counts"))
    elif role == "pace_fit":
        common.update(schedule_pressure=result.get("schedule_pressure"), team_pace_fit=result.get("team_pace_fit"),
                      planned_days=result.get("planned_days"), segment_assessment_count=len(result.get("segment_assessments", [])),
                      day_assessments=[{"day_id": a["day_id"], "segment_id": a["segment_id"],
                          "decision": a["assessment"].get("decision"), "schedule_pressure": a["assessment"].get("schedule_pressure")}
                          for a in result.get("day_assessments", [])])
    elif role == "permission":
        common.update(planned_stops=result.get("planned_stops"), assessment_count=len(result.get("assessments", [])),
                      safety_buffer_derived_from_travel_time=False)
    elif role == "weather":
        common.update({k: result.get(k) for k in ("matched_segment_count", "source_forecast_point_count", "new_package_built",
                                                "historical_weather_status", "daylight_buffer_status", "segment_matches")})
    elif role == "navigation":
        common.update({k: result.get(k) for k in ("map_readiness", "terrain_readiness", "navigation_demand", "coverage")})
        common["route_terrain_coverage"] = result.get("route_terrain_analysis", {}).get("coverage")
    else:
        common.update(point_count=result.get("point_count"), points=result.get("points", []), briefing_ref=result.get("briefing_ref"),
                      excluded_unlocated_or_outside_route_count=result.get("excluded_unlocated_or_outside_route_count"))
    return common


def run_planned_analyses(owner_root: Path, bundle: dict, run_root: Path, preparation: dict,
                         *, progress: Callable | None = None) -> dict:
    """Return hash-bound projections after executing each actual assessor.

    A partial result is useful newly computed evidence with specific missing
    inputs. It must not be promoted to full coverage or runtime authority.
    """
    owner_root, run_root = Path(owner_root).resolve(), Path(run_root).resolve()
    is_recorded = bundle["manifest"].get("kind") == "recorded_gpx"
    if is_recorded:
        from scout_recorded_analysis import build_recorded_analysis_inputs
        inputs = build_recorded_analysis_inputs(owner_root, bundle, run_root, preparation)
    else:
        inputs = build_planned_analysis_inputs(owner_root, bundle, run_root, preparation)
    inputs["is_recorded"] = is_recorded
    root = safe_path(run_root, inputs["workspace_ref"])
    source_report: list[dict] = []
    _copy_sources(owner_root, root, source_report)
    if is_recorded:
        inputs["review_context"] = {"status": "not_applicable_to_recorded", "assessor_kwargs": {},
            "missing_inputs": [_missing("recorded_review_evidence", "Post-trip judgement still needs condition/team evidence from that trip.")]}
    else:
        _materialize_review(owner_root, bundle, root, inputs, source_report)
    from scout_planned_analysis_evidence import match_planned_historical_passages, join_planned_terrain
    if progress:
        progress({"stage": "analysis:historical_passage_matching", "status": "running", "role": "architecture"})
    inputs["historical_passages"] = match_planned_historical_passages(owner_root, root, inputs, bundle, source_report)
    if progress:
        progress({"stage": "analysis:canonical_terrain_join", "status": "running", "role": "navigation"})
    inputs["terrain_analysis"] = join_planned_terrain(run_root, root, inputs, preparation, source_report)
    binding = {**inputs["subject_binding"],
               **{k: inputs["review_context"][key] for k, key in (("review_context_revision_id", "context_revision_id"), ("review_context_sha256", "context_sha256")) if key in inputs["review_context"]},
               "producer_version": PRODUCER_VERSION,
               "source_hashes": {f"{s['scope']}:{s['ref']}": s["sha256"] for s in source_report},
               "derived_input_hashes": inputs["input_hashes"]}
    producers = {"architecture": _architecture, "weather": _weather, "pace_fit": _pace,
                 "permission": _permission, "navigation": _navigation, "route_context": _context}
    projections = {}
    for role in ROLES:
        if progress:
            progress({"stage": f"analysis:{role}", "status": "running", "role": role})
        try:
            result, missing = producers[role](root, inputs, preparation)
            if is_recorded:
                missing.extend(inputs["review_context"]["missing_inputs"])
                result.update(analysis_subject_kind="recorded_gpx", source_times_role=inputs["subject_binding"]["source_times_role"],
                              comparison=inputs.get("comparison"), planned_timetable_role="recorded_observation_alias")
            missing = _unique_missing(missing)
            status = "partial" if missing else "ready"
            summary = _summary(role, result, missing)
            if is_recorded:
                summary = "Recorded 復盤：" + summary.replace("Planned", "Recorded")
        except PlannedRouteConflict:
            raise
        except Exception as exc:
            # One broken producer is not permission to substitute a Golden
            # report or discard the other independently computed projections.
            status, result = "blocked", {"error_type": type(exc).__name__}
            missing = [_missing("producer_failed", f"{role} deterministic producer failed ({type(exc).__name__}).")]
            summary = missing[0]["reason"]
        ref = f"projections/{role}.json"
        artifact = {"artifact_kind": "recorded_analysis_projection" if is_recorded else "planned_analysis_projection", "schema_version": PRODUCER_VERSION,
                    "role": role, "status": status, "summary": summary, "input_binding": binding,
                    "missing_inputs": missing, "coverage": preparation.get("coverage", {}),
                    "result": result, "source_report": source_report,
                    "review_context": {k: inputs["review_context"][k] for k in ("status", "context_revision_id", "context_sha256") if k in inputs["review_context"]},
                    "generated_at": datetime.now(timezone.utc).isoformat(), **BOUNDARY,
                    "recorded_track": is_recorded, "analysis_subject_kind": "recorded_gpx" if is_recorded else "planned_gpx"}
        sha = write_json(run_root, ref, artifact)
        projections[role] = {k: artifact[k] for k in ("role", "status", "summary", "input_binding", "missing_inputs", "coverage", "candidate_only", "runtime_safety_truth", "recorded_track")}
        projections[role].update(artifact_ref=ref, artifact_sha256=sha, result=_public_result(role, result))
        if progress:
            progress({"stage": f"analysis:{role}", "status": status, "role": role,
                      "artifact_ref": ref, "artifact_sha256": sha})
    pretrip_report = None
    if not is_recorded:
        from scout_planned_pretrip_report import build_planned_pretrip_report
        if progress:
            progress({"stage": "analysis:pretrip_report", "status": "running"})
        pretrip_report = build_planned_pretrip_report(root, inputs, projections, binding=binding, run_root=run_root)
    for source in source_report:
        path = safe_path(owner_root if source["scope"] == "owner" else run_root, source["ref"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise PlannedRouteConflict("analysis_input_changed", "An analysis source changed while assessors were running.")
    return {"status": "blocked" if all(p["status"] == "blocked" for p in projections.values())
            else "ready" if all(p["status"] == "ready" for p in projections.values()) else "partial",
            "subject_binding": binding, "workspace_ref": inputs["workspace_ref"],
            "graph_ref": inputs["graph_ref"], "canonical_refs": inputs["canonical_refs"],
            "projections": projections, "pretrip_report": pretrip_report, **BOUNDARY, "recorded_track": is_recorded}
