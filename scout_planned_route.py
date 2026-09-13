"""Source-bound GPX composition and explicit planned time, with no writes.

Geometry is taken from complete source segments. Neither map display samples
nor invented straight lines can fill a missing trail. Historical observations
remain in provenance; generated GPX never claims to be a recorded activity.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scout_planned_route_models import (
    ItineraryOperation, PlannedRouteConflict, PlannedRouteRequest, RouteSegmentSelection,
)

JOIN_TOLERANCE_M = 30.0
SOURCE_GAP_M = 500.0
GPX_NS = "http://www.topografix.com/GPX/1/1"
PLAN_NS = "https://scout.local/schemas/planned-route/v1"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def distance(a: dict, b: dict) -> float:
    p, q = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = q - p, math.radians(b["lon"] - a["lon"])
    h = math.sin(dlat / 2) ** 2 + math.cos(p) * math.cos(q) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def _path(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    if root not in path.parents or not path.is_file():
        raise PlannedRouteConflict("source_missing_or_outside_project", f"Unavailable project source: {ref}")
    return path


def _read(root: Path, ref: str, hashes: dict) -> bytes:
    path = _path(root, ref)
    raw = path.read_bytes()
    hashes[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return raw


def _json(root: Path, ref: str, hashes: dict) -> Any:
    return json.loads(_read(root, ref, hashes))


def _filtered_gpx_ref(root: Path, project_id: str, record: dict) -> str:
    ref = record["output_path"]
    path = Path(ref)
    if not path.is_absolute() or root in path.parents:
        return ref
    # Imported workspaces may retain a former host's absolute output path.
    # Only this hash-bound filtered-route layout has a portable interpretation.
    expected_sha = record.get("output_sha256")
    suffix = (project_id, "normalized", "routes", "filtered", path.name)
    if (not isinstance(project_id, str) or not project_id or
            Path(project_id).parts != (project_id,) or project_id in {".", ".."} or
            ".." in path.parts or path.parts[-5:] != suffix or
            not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha)):
        raise PlannedRouteConflict("source_missing_or_outside_project", f"Unavailable project source: {ref}")
    return Path(*suffix[1:]).as_posix()


def _stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _issue(code: str, message: str, *, severity: str = "warning", **context: Any) -> dict:
    return {"issue_id": code + "." + digest(context or message)[:12], "code": code,
            "severity": severity, "message": message, **context}


def _point(element: ET.Element) -> dict:
    lat, lon = float(element.attrib["lat"]), float(element.attrib["lon"])
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise PlannedRouteConflict("invalid_coordinate", "GPX coordinate is outside WGS84.")
    fields = {child.tag.split("}")[-1]: child.text for child in element}
    ele = float(fields["ele"]) if fields.get("ele") else None
    if ele is not None and not math.isfinite(ele):
        raise PlannedRouteConflict("invalid_elevation", "GPX elevation is not finite.")
    return {"lat": lat, "lon": lon, "ele": ele, "time": fields.get("time"),
            **({"label": fields["name"]} if fields.get("name") else {})}


def _gpx(raw: bytes) -> tuple[list[list[dict]], list[dict], bool]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise PlannedRouteConflict("unsafe_xml", "GPX document declarations are not allowed.")
    tree = ET.fromstring(raw)
    parts = [[_point(p) for p in element if p.tag.split("}")[-1] == point_tag]
             for tag, point_tag in (("trkseg", "trkpt"), ("rte", "rtept"))
             for element in tree.iter() if element.tag.split("}")[-1] == tag]
    parts = [part for part in parts if part]
    waypoints = [_point(e) for e in tree if e.tag.split("}")[-1] == "wpt"]
    planned = any(e.tag == f"{{{PLAN_NS}}}provenance" and e.get("role") == "planned"
                  for e in tree.iter())
    return parts, waypoints, planned


def _anchor(source: dict, part: int, index: int, label: str, aliases: list | None = None) -> dict:
    point = source["parts"][part][index]
    return {"anchor_id": f"{source['source_id']}.p{part}.i{index}", "label": label,
            "aliases": aliases or [], "source_id": source["source_id"], "part_index": part,
            "point_index": index, "lat": point["lat"], "lon": point["lon"]}


def load_planned_catalog(project_root: Path) -> dict:
    root = Path(project_root).resolve()
    hashes: dict[str, str] = {}
    project = _json(root, "project.json", hashes)
    if project.get("workspace_kind") == "exploration":
        from scout_exploration_workspace import load_exploration_catalog
        return load_exploration_catalog(root)
    report = _json(root, project.get("gpx_speed_filter_report_ref", "outputs/gpx_speed_filter_report.json"), hashes)
    sources, anchors, issues = [], [], []
    for number, record in enumerate([report.get("primary") or {}, *report.get("references", [])]):
        ref = record.get("output_path")
        if not ref:
            if number == 0:
                raise PlannedRouteConflict("golden_source_missing", "Choose and prepare a Golden GPX first.")
            continue
        local_ref = _filtered_gpx_ref(root, project.get("project_id", root.name), record)
        raw = _read(root, local_ref, hashes)
        relative = _path(root, local_ref).relative_to(root).as_posix()
        sha = hashes[relative]
        if record.get("output_sha256") and record["output_sha256"] != sha:
            raise PlannedRouteConflict("source_hash_changed", f"Filtered GPX changed: {relative}")
        parts, waypoints, planned = _gpx(raw)
        if not parts:
            raise PlannedRouteConflict("empty_source_geometry", f"GPX has no route geometry: {relative}")
        source = {"source_id": "golden" if number == 0 else "ref." + digest(relative)[:16],
                  "label": Path(ref).name, "kind": "golden" if number == 0 else "reference_gpx",
                  "ref": relative, "sha256": sha, "parts": parts,
                  "provenance": {"recorded_source_sha256": record.get("source_sha256"),
                                 "imported_role": "planned" if planned else "reference_observation",
                                 "candidate_only": True, "runtime_safety_truth": False}}
        sources.append(source)
        for part_index, part in enumerate(parts):
            anchors.extend([_anchor(source, part_index, 0, f"{source['label']} · 段 {part_index + 1} 起點"),
                            _anchor(source, part_index, len(part) - 1, f"{source['label']} · 段 {part_index + 1} 終點")])
            for index, point in enumerate(part):
                if point.get("label"):
                    anchors.append(_anchor(source, part_index, index, point["label"]))
        for waypoint in waypoints:
            matches = [(distance(waypoint, p), pi, i) for pi, part in enumerate(parts) for i, p in enumerate(part)]
            matches.sort()
            if not matches or matches[0][0] > JOIN_TOLERANCE_M:
                issues.append(_issue("unlocated_waypoint", "GPX waypoint is not on a source segment.",
                                     label=waypoint.get("label"), source_id=source["source_id"]))
                continue
            # Keep separate visits to a place; never collapse repeated route progress.
            groups: list[list[tuple]] = []
            for row in sorted((r for r in matches if r[0] <= min(JOIN_TOLERANCE_M, matches[0][0] + 3)), key=lambda r: (r[1], r[2])):
                if not groups or row[1] != groups[-1][-1][1] or row[2] > groups[-1][-1][2] + 10:
                    groups.append([])
                groups[-1].append(row)
            for group in groups:
                _, pi, index = min(group)
                anchors.append(_anchor(source, pi, index, waypoint.get("label", "Waypoint")))
    golden = sources[0]
    cp_ref = project.get("checkpoint_candidates_ref", "candidates/checkpoints.json")
    if (root / cp_ref).is_file():
        payload = _json(root, cp_ref, hashes)
        checkpoints = payload if isinstance(payload, list) else payload.get("checkpoints", payload.get("candidates", []))
        for cp in checkpoints:
            index = cp.get("route_point_index")
            if not isinstance(index, int):
                continue
            for pi, part in enumerate(golden["parts"]):
                if index < len(part):
                    anchors.append(_anchor(golden, pi, index, cp.get("label") or cp.get("candidate_id", "CP"),
                                           [cp.get("candidate_id", "")]))
                    break
                index -= len(part)
    from scout_planned_route_sources import load_map_route_sources
    maps = load_map_route_sources(root, project)
    sources.extend(maps.get("sources", [])); anchors.extend(maps.get("anchors", []))
    hashes.update(maps.get("source_hashes", {})); issues.extend(maps.get("issues", []))
    merged = {}
    for anchor in anchors:
        key = anchor["anchor_id"]
        if key in merged:
            previous = merged[key]
            anchor["aliases"] = sorted(set(previous.get("aliases", []) + anchor.get("aliases", []) + [previous["label"]]))
        merged[key] = anchor
    for ref in (project.get("layer_preparation_manifest_ref", "outputs/layers/layer_preparation_manifest.json"),):
        if (root / ref).is_file():
            _read(root, ref, hashes)
    return {"schema_version": "plannedRouteCatalog.v1", "project_id": project.get("project_id", root.name),
            "golden_source_id": "golden", "sources": sources, "anchors": list(merged.values()),
            "source_hashes": hashes, "source_snapshot_sha256": digest(hashes), "issues": issues,
            "candidate_only": True, "runtime_safety_truth": False}


def _resolve(name: str | None, catalog: dict, request: PlannedRouteRequest, issues: list) -> dict | None:
    name = (name or "").strip()
    explicit = request.name_resolutions.get(name, name)
    matches = [a for a in catalog["anchors"] if explicit == a["anchor_id"]]
    if not matches:
        matches = [a for a in catalog["anchors"] if explicit in [a["label"], *a.get("aliases", [])]]
    if len(matches) != 1:
        issues.append(_issue("ambiguous_place" if matches else "unlocated_place",
                             f"請確認地名「{name}」對應的來源與位置。", severity="error", name=name,
                             choices=[{"anchor_id": a["anchor_id"], "label": a["label"], "source_id": a["source_id"]} for a in matches]))
        return None
    return matches[0]


def _text_intent(request: PlannedRouteRequest, catalog: dict, issues: list) -> tuple:
    from scout_planned_intent import golden_day_windows, parse_planned_intent
    if request.intent_input_sha256 and request.intent_input_sha256 != hashlib.sha256(request.human_text.encode()).hexdigest():
        raise PlannedRouteConflict("intent_text_changed", "Human itinerary changed; regenerate its grounded draft.")
    planner = None
    if request.intent_draft is not None:
        class SavedDraft:
            def run(self, prompt, *, timeout_seconds=None):
                return request.intent_draft.model_dump_json()
        planner = SavedDraft()
    intent = parse_planned_intent(request.human_text, catalog, departure_at=request.departure_at,
                                  name_resolutions=request.name_resolutions, planner=planner)
    operations = list(request.operations)
    for operation in operations:
        if operation.source_span is not None:
            span = operation.source_span
            if span.end <= span.start or request.human_text[span.start:span.end] != operation.source_text:
                issues.append(_issue("operation_source_span_mismatch", "明確操作的原文位置與實際文字不一致。", severity="error",
                                     source_span=span.model_dump(), source_text=operation.source_text))
    represented = {op.source_text.strip() for op in operations if op.source_text}
    represented_ids = {c["clause_id"] for c in intent["clauses"] if c["source_text"] in represented}
    for clause in intent["clauses"]:
        if clause["clause_id"] in represented_ids:
            clause["status"] = "resolved_by_explicit_operation"
            clause["explicit_operation_indices"] = [i for i, op in enumerate(operations) if op.source_text and op.source_text.strip() == clause["source_text"]]
    intent["issues"] = [issue for issue in intent["issues"] if issue.get("clause_id") not in represented_ids]
    intent["unresolved_clause_ids"] = [key for key in intent["unresolved_clause_ids"] if key not in represented_ids]
    intent["status"] = "needs_clarification" if intent["issues"] or intent["unresolved_clause_ids"] else "resolved"
    for problem in intent["issues"]:
        # Keep the stable old error category used by callers of the simple form.
        problem = copy.deepcopy(problem)
        if problem["code"] == "unsupported_itinerary_clause":
            problem["reason_code"] = problem["code"]
            problem["code"] = "unresolved_itinerary_clause"
        issues.append(problem)
    for raw in intent["operations"]:
        if raw["clause_id"] in represented_ids:
            continue
        payload = {key: value for key, value in raw.items() if key in ItineraryOperation.model_fields}
        if not raw.get("day_context_explicit") and raw["kind"] not in ("depart",):
            payload["day_index"] = None
            payload["calendar_date"] = None
        operations.append(ItineraryOperation.model_validate(payload))
    for operation in operations:
        for condition in operation.preconditions:
            issues.append(_issue("itinerary_precondition_unverified", "出發前置條件仍需人工確認。",
                                 precondition=condition, source_text=operation.source_text, at=operation.at))
    route_intents = [row for row in intent["route_intents"] if row["clause_id"] not in represented_ids]
    follow = [row for row in route_intents if row["kind"] == "follow_golden"]
    effective = request
    start_day = 1
    if follow:
        requested = []
        windows = golden_day_windows(catalog)
        for row in follow:
            for selection in row["selections"]:
                days = [w["day_index"] for w in windows if all(w[k] == selection[k] for k in ("source_id", "part_index", "start_index", "end_index"))]
                requested.append(RouteSegmentSelection(**selection, day_index=days[0] if len(days) == 1 else None))
        explicit_follow = any(row.get("day_context_explicit") for row in follow)
        if explicit_follow and requested:
            start_day = min(row.day_index or 1 for row in requested)
            end_day = max([start_day] + [op.location_day_index or op.day_index or start_day for op in operations if op.kind != "depart" or op.at])
            for day in range(start_day, end_day + 1):
                if not any(row.day_index == day for row in requested):
                    available = [w for w in windows if w["day_index"] == day]
                    if not available:
                        issues.append(_issue("golden_day_geometry_missing", "此行程日沒有可核對的 Golden 來源範圍。", severity="error", day_index=day))
                    requested.extend(RouteSegmentSelection(**{k: w[k] for k in ("source_id", "part_index", "start_index", "end_index", "day_index")}) for w in available)
            requested.sort(key=lambda row: (row.day_index or 1, row.part_index, row.start_index))
        if request.route_selections:
            def bare(rows):
                return [r.model_dump(exclude={"day_index"}) for r in rows]
            if bare(request.route_selections) != bare(requested):
                issues.append(_issue("text_route_selection_conflict", "文字指定的 Golden 日段與明確路段選擇不一致。", severity="error"))
        else:
            effective = request.model_copy(update={"route_selections": requested})
    for route in route_intents:
        if route["kind"] != "replace_path":
            continue
        op = next((op for op in operations if op.clause_id == route["clause_id"] and op.kind in ("replace", "trim")), None)
        if op is None or op.selection is not None or op.kind == "trim":
            continue
        at = _resolve(op.at, catalog, request, issues)
        to = _resolve(op.to, catalog, request, issues)
        if not at or not to:
            continue
        if route.get("source_id"):
            source = next((row for row in catalog["sources"] if row["source_id"] == route["source_id"]), None)
            matches = []
            if source:
                for pi, points in enumerate(source["parts"]):
                    if not points:
                        continue
                    start = min(range(len(points)), key=lambda i: distance(points[i], at))
                    end = min(range(len(points)), key=lambda i: distance(points[i], to))
                    if distance(points[start], at) > JOIN_TOLERANCE_M or distance(points[end], to) > JOIN_TOLERANCE_M or start == end:
                        continue
                    if any(abs(i - selected) > 10 and distance(point, anchor) <= 3
                           for anchor, selected in ((at, start), (to, end)) for i, point in enumerate(points)):
                        continue
                    matches.append(RouteSegmentSelection(source_id=source["source_id"], part_index=pi, start_index=start, end_index=end))
            if len(matches) == 1:
                op.selection = matches[0]
            else:
                issues.append(_issue("replacement_source_endpoints_ambiguous", "替代來源沒有唯一可核對的起迄點，請選擇明確索引。", severity="error"))
        else:
            from scout_planned_route_models import TrailPathSelection
            op.selection = RouteSegmentSelection(trail_search=TrailPathSelection(start_anchor_id=op.at,
                end_anchor_id=op.to, via_anchor_ids=route.get("via_anchor_ids", [])))
    departure = request.departure_at + timedelta(days=start_day - 1) if request.departure_at else None
    for op in operations:
        if op.kind == "depart" and not op.at and op.departure_at:
            departure = op.departure_at
            break
    return operations, departure, intent, effective, start_day


def _tag_source_days(nodes: list, catalog: dict) -> None:
    from scout_planned_intent import golden_day_windows
    windows = golden_day_windows(catalog)
    for node in nodes:
        if node.get("day_index") is not None:
            continue
        days = {w["day_index"] for w in windows if node["source_id"] == w["source_id"] and
                node["part_index"] == w["part_index"] and w["start_index"] <= node["source_point_index"] <= w["end_index"]}
        if len(days) == 1:
            node["day_index"] = next(iter(days))


def _operation_location(nodes: list, anchor: dict | None, operation: ItineraryOperation,
                        issues: list, *, to: bool = False) -> int | None:
    day = operation.location_day_index or operation.day_index
    if day is None:
        return _location(nodes, anchor, operation.to_visit if to else operation.visit, issues)
    visible = [(i, node) for i, node in enumerate(nodes) if node.get("day_index") == day]
    if not visible:
        # Planned days may differ from recorded Golden days. A unique route
        # occurrence is still grounded; the scheduler checks its requested date.
        # Multiple occurrences remain unresolved rather than borrowing another day.
        return _location(nodes, anchor, operation.to_visit if to else operation.visit, issues)
    result = _location([node for _, node in visible], anchor, operation.to_visit if to else operation.visit, issues)
    return visible[result][0] if result is not None else None


def _nodes(source: dict, part: int, first: int, last: int) -> list[dict]:
    points = source["parts"][part]
    if first >= len(points) or last >= len(points):
        raise PlannedRouteConflict("source_point_range_invalid", "Source point range is outside its track segment.")
    step = 1 if last >= first else -1
    return [{**copy.deepcopy(points[i]), "source_id": source["source_id"], "part_index": part,
             "source_point_index": i, "break_before": i == first, "direction": "forward" if step == 1 else "reverse"}
            for i in range(first, last + step, step)]


def _selection(selection: RouteSegmentSelection, catalog: dict, request: PlannedRouteRequest, issues: list) -> list[dict]:
    if selection.trail_search:
        from scout_planned_route_sources import find_trail_path
        search = selection.trail_search
        points = [_resolve(name, catalog, request, issues) for name in
                  [search.start_anchor_id, *search.via_anchor_ids, search.end_anchor_id]]
        if not all(points):
            return []
        result = find_trail_path(catalog["sources"], points[0], points[-1], points[1:-1])
        if result.get("status") != "ready" or not result.get("parts"):
            issues.extend(result.get("issues", []))
            issues.append(_issue("trail_path_unavailable", "找不到有來源拓樸的接續山徑。", severity="error"))
            return []
        legs = [("outbound", result)]
        if selection.round_trip:
            returning = find_trail_path(catalog["sources"], points[-1], points[0], list(reversed(points[1:-1])))
            if returning.get("status") != "ready" or not returning.get("parts"):
                issues.extend(returning.get("issues", []))
                issues.append(_issue("trail_return_path_unavailable", "去程可定位，但找不到符合山徑方向限制的返回路段。", severity="error"))
                return []
            legs.append(("return", returning))
        nodes = []
        for leg, path in legs:
            source = {"source_id": "trail." + digest({"search": search.model_dump(), "leg": leg})[:16],
                      "label": f"Overpass trail search · {leg}", "kind": "overpass", "parts": path["parts"],
                      "provenance": {**path.get("provenance", {}), "round_trip_leg": leg}}
            catalog["sources"].append(source)
            nodes.extend(point for pi, part in enumerate(source["parts"])
                         for point in _nodes(source, pi, 0, len(part) - 1))
            if leg == "outbound" and selection.round_trip:
                nodes[-1]["round_trip_turnaround"] = True
        return nodes
    else:
        source = next((s for s in catalog["sources"] if s["source_id"] == selection.source_id), None)
    if source is None or selection.part_index >= len(source["parts"]):
        raise PlannedRouteConflict("source_selection_missing", "Selected route source/track segment no longer exists.")
    first, last = selection.start_index, selection.end_index
    if last is None:
        last = len(source["parts"][selection.part_index]) - 1
    if first == last:
        raise PlannedRouteConflict("source_segment_too_short", "A route segment needs two distinct source point indices.")
    if source["kind"] == "overpass":
        tags = source.get("provenance", {}).get("osm_tags", {})
        restricted = tags.get("foot") in {"no", "private"} or (
            tags.get("access") in {"no", "private"} and tags.get("foot") not in {"yes", "designated", "permissive"})
        oneway = str(tags.get("oneway:foot", "no")).lower()
        wrong_direction = ((oneway in {"yes", "1", "true"} and last < first)
                           or (oneway == "-1" and last > first)
                           or (selection.round_trip and oneway in {"yes", "1", "true", "-1"}))
        if restricted or wrong_direction:
            issues.append(_issue("trail_access_restricted" if restricted else "trail_direction_restricted",
                                 "所選來源有步行權限或方向限制；請改選可接續的來源。", severity="error", source_id=source["source_id"]))
            return []
    nodes = _nodes(source, selection.part_index, first, last)
    if selection.day_index is not None:
        for node in nodes:
            node["day_index"] = selection.day_index
    if selection.round_trip:
        nodes[-1]["round_trip_turnaround"] = True
        returning = _nodes(source, selection.part_index, last, first)
        if selection.day_index is not None:
            for node in returning:
                node["day_index"] = selection.day_index
        nodes.extend(returning)
    return nodes


def _location(nodes: list, anchor: dict | None, visit: int | None, issues: list) -> int | None:
    if anchor is None:
        return None
    exact = [i for i, p in enumerate(nodes) if p["source_id"] == anchor["source_id"]
             and p["part_index"] == anchor["part_index"] and p["source_point_index"] == anchor["point_index"]]
    if not exact:
        nearby = [i for i, p in enumerate(nodes) if distance(p, anchor) <= JOIN_TOLERANCE_M]
        groups = []
        for i in nearby:
            if not groups or i > groups[-1][-1] + 1:
                groups.append([])
            groups[-1].append(i)
        exact = [min(group, key=lambda i: distance(nodes[i], anchor)) for group in groups]
    # Duplicate endpoints at an explicit segment join are one visit.
    matches = [i for j, i in enumerate(exact) if j == 0 or i > exact[j - 1] + 1]
    if (visit is None and len(matches) != 1) or (visit is not None and len(matches) < visit):
        issues.append(_issue("route_visit_ambiguous" if matches else "anchor_not_on_planned_route",
                             "請指定這個位置在行程中的第幾次到訪。", severity="error",
                             anchor_id=anchor["anchor_id"], visit_count=len(matches)))
        return None
    return matches[(visit or 1) - 1]


def _infer_branch(at: dict, target: dict, catalog: dict, issues: list) -> RouteSegmentSelection | None:
    matches = []
    for source in catalog["sources"]:
        if source["kind"] == "golden":
            continue
        for pi, points in enumerate(source["parts"]):
            start = min(range(len(points)), key=lambda i: distance(points[i], at))
            end = min(range(len(points)), key=lambda i: distance(points[i], target))
            if distance(points[start], at) <= JOIN_TOLERANCE_M and distance(points[end], target) <= JOIN_TOLERANCE_M and start != end:
                # Sequence ambiguity inside a looping Ref remains an explicit choice.
                for endpoint, chosen in ((at, start), (target, end)):
                    other = [i for i, p in enumerate(points) if abs(i - chosen) > 10 and distance(p, endpoint) <= 3]
                    if other:
                        break
                else:
                    matches.append(RouteSegmentSelection(source_id=source["source_id"], part_index=pi,
                                                         start_index=start, end_index=end, round_trip=True))
    if len(matches) != 1:
        issues.append(_issue("branch_source_ambiguous" if matches else "branch_source_missing",
                             "支線需要明確的 Ref. 路段或地圖候選來源。", severity="error",
                             choices=[m.model_dump() for m in matches]))
        return None
    return matches[0]


def _compose(catalog: dict, request: PlannedRouteRequest, operations: list, issues: list) -> list:
    if request.route_selections:
        nodes = [p for s in request.route_selections for p in _selection(s, catalog, request, issues)]
    else:
        golden = next((source for source in catalog["sources"] if source["source_id"] == catalog.get("golden_source_id")), None)
        if golden is None:
            issues.append(_issue("exploration_route_selection_required", "無 Golden 的探索工作區需要明確選擇候選路段。", severity="error"))
            return []
        nodes = [p for pi, part in enumerate(golden["parts"]) for p in _nodes(golden, pi, 0, len(part) - 1)]
    _tag_source_days(nodes, catalog)
    for op in operations:
        if op.kind not in ("branch", "replace", "trim"):
            continue
        at = _resolve(op.at, catalog, request, issues)
        first = _operation_location(nodes, at, op, issues)
        if first is None:
            continue
        if op.kind == "branch":
            selection = op.selection
            if selection is None:
                target = _resolve(op.to, catalog, request, issues)
                selection = _infer_branch(at, target, catalog, issues) if target else None
            if selection is None:
                continue
            selection = selection.model_copy(update={"round_trip": True})
            branch = _selection(selection, catalog, request, issues)
            for point in branch:
                point["day_index"] = nodes[first].get("day_index", op.day_index)
            if not branch:
                continue
            if distance(nodes[first], branch[0]) > JOIN_TOLERANCE_M:
                issues.append(_issue("branch_does_not_join", "支線起點不在所選主線接點的容差內。", severity="error", at=op.at))
                continue
            if op.to:
                target = _resolve(op.to, catalog, request, issues)
                if target is None:
                    continue
                turnaround = next(p for p in branch if p.get("round_trip_turnaround"))
                if distance(turnaround, target) > JOIN_TOLERANCE_M:
                    issues.append(_issue("branch_target_mismatch", "所選支線的折返點不符合指定目的地。", severity="error", target=op.to))
                    continue
            suffix = copy.deepcopy(nodes[first:])
            suffix[0]["break_before"] = True
            nodes = nodes[:first + 1] + branch + suffix
        else:
            to = _resolve(op.to, catalog, request, issues)
            last = _operation_location(nodes, to, op, issues, to=True)
            if last is None:
                continue
            if last <= first:
                issues.append(_issue("itinerary_order_invalid", "取代或裁切終點必須在起點之後；反向請明確選反向來源段。", severity="error"))
                continue
            if op.kind == "trim":
                nodes = copy.deepcopy(nodes[first:last + 1]); nodes[0]["break_before"] = True
            elif op.selection:
                middle = _selection(op.selection, catalog, request, issues)
                for point in middle:
                    point["day_index"] = nodes[first].get("day_index", op.day_index)
                suffix = copy.deepcopy(nodes[last:]); suffix[0]["break_before"] = True
                nodes = nodes[:first + 1] + middle + suffix
            else:
                issues.append(_issue("replacement_geometry_required", "刪除主線段需要可接續的替代幾何；不能補一條直線。", severity="error"))
    return nodes


def _geometry(nodes: list, catalog: dict, issues: list) -> tuple[dict, list, list, list]:
    parts: list[list] = []
    cumulative = 0.0
    axis = []
    for i, point in enumerate(nodes):
        previous = nodes[i - 1] if i else None
        gap = distance(previous, point) if previous else 0.0
        if i and point["break_before"] and gap > JOIN_TOLERANCE_M:
            issues.append(_issue("disconnected_geometry", "來源段之間未連通；不產生補接直線。", severity="error",
                                 point_index=i, distance_m=round(gap, 3)))
        elif i and not point["break_before"] and gap > SOURCE_GAP_M:
            issues.append(_issue("source_geometry_gap", "來源內有大跨度記錄缺口，分段保留且耗時未知；未補路段。",
                                 point_index=i, distance_m=round(gap, 3)))
            point["break_before"] = True
        if not parts or point["break_before"]:
            parts.append([])
        if previous and not point["break_before"]:
            cumulative += gap
        item = {"point_index": i, "route_order_m": round(cumulative, 3),
                "lat": point["lat"], "lon": point["lon"], "ele": point.get("ele"),
                "source_id": point["source_id"], "source_part_index": point["part_index"],
                "source_point_index": point["source_point_index"], "break_before": point["break_before"],
                "source_day_index": point.get("day_index")}
        axis.append(item); parts[-1].append(item)
    features, segments = [], []
    by_id = {s["source_id"]: s for s in catalog["sources"]}
    for index, part in enumerate(parts):
        source = by_id[part[0]["source_id"]]
        segment = {"segment_id": f"planned.seg.{index:03d}", "source_id": source["source_id"],
                   "source_ref": source.get("ref"), "source_sha256": source.get("sha256"),
                   "source_kind": source["kind"], "part_index": part[0]["source_part_index"],
                   "source_start_index": part[0]["source_point_index"], "source_end_index": part[-1]["source_point_index"],
                   "direction": "forward" if part[-1]["source_point_index"] >= part[0]["source_point_index"] else "reverse",
                   "start_point_index": part[0]["point_index"], "end_point_index": part[-1]["point_index"],
                   "length_m": round(part[-1]["route_order_m"] - part[0]["route_order_m"], 3),
                   "ascent_m": round(sum(max(0, b["ele"] - a["ele"]) for a, b in zip(part, part[1:]) if a["ele"] is not None and b["ele"] is not None), 3),
                   "descent_m": round(sum(max(0, a["ele"] - b["ele"]) for a, b in zip(part, part[1:]) if a["ele"] is not None and b["ele"] is not None), 3),
                   "provenance": source.get("provenance", {}), "candidate_only": True, "runtime_safety_truth": False}
        segments.append(segment)
        if len(part) > 1:
            features.append({"type": "Feature", "properties": segment,
                             "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in part]}})
    return {"type": "FeatureCollection", "features": features}, axis, segments, parts


def _timing(nodes: list, operations: list, catalog: dict, request: PlannedRouteRequest,
            departure: datetime | None, issues: list, start_day_index: int = 1) -> tuple[dict, list]:
    events: dict[int, list] = {}
    for op in operations:
        if op.kind in ("stop", "camp", "depart", "deadline", "arrival"):
            anchor = _resolve(op.at, catalog, request, issues) if op.at else None
            index = _operation_location(nodes, anchor, op, issues) if anchor else (0 if op.kind == "depart" else None)
            if index is None:
                if not op.at and op.kind != "depart":
                    issues.append(_issue("event_location_required", "停留、营地或到達限制需要明確位置。", severity="error", operation=op.kind))
                continue
            events.setdefault(index, []).append(op)
    if departure is None:
        issues.append(_issue("planned_departure_required", "請輸入規劃出發日期、時間與時區；不沿用來源的舊日期。"))
    clock = departure
    replaced_stay_anchor = None
    timeline, unknowns, conflicts, days, checkpoints = [], [], [], [], []
    day = {"day_id": f"D{start_day_index}", "mission_day_id": f"D{start_day_index}", "departure_at": clock.isoformat() if clock else None,
           "start_point_index": 0, "moving_minutes": 0.0, "rest_minutes": 0.0, "unknown_count": 0,
           "source_rest_minutes": 0.0, "fixed_rest_minutes": 0.0}
    by_id = {s["source_id"]: s for s in catalog["sources"]}
    mandatory_cp = set(events) | {0, len(nodes) - 1}
    for i in range(1, len(nodes)):
        if nodes[i]["break_before"]:
            mandatory_cp.update((i - 1, i))
    def finish(index: int, label: str | None, camp: bool = False) -> None:
        day.update({"end_point_index": index, "arrival_at": clock.isoformat() if clock else None,
                    "end_label": label, "camp": camp})
        for key in ("moving_minutes", "rest_minutes", "source_rest_minutes", "fixed_rest_minutes"):
            day[key] = round(day[key], 3)
        days.append(copy.deepcopy(day))
    for i, point in enumerate(nodes):
        if i:
            previous = nodes[i - 1]
            span = distance(previous, point)
            duration, method, rest = None, "unknown", False
            if point["break_before"]:
                if span <= JOIN_TOLERANCE_M:
                    duration, method = 0.0, "source_join_within_30m_no_invented_connector"
            else:
                source = by_id[point["source_id"]]
                a, b = _stamp(previous.get("time")), _stamp(point.get("time"))
                forward = point["source_point_index"] == previous["source_point_index"] + 1
                observed = (b - a).total_seconds() / 60 if a and b and b > a and forward else None
                speed = span / (observed * 60) * 3.6 if observed else None
                if observed is not None and source.get("provenance", {}).get("imported_role") != "planned":
                    rest = speed < 0.3
                    if rest:
                        duration, method = observed, "source_stationary_estimate"
                    elif request.pace_mode != "fixed_speed":
                        duration, method = observed, "direction_compatible_source_elapsed_estimate"
                if duration is None and request.default_speed_kmh:
                    duration, method = span / (request.default_speed_kmh * 1000 / 60), "explicit_fixed_speed_assumption"
                if replaced_stay_anchor is not None:
                    if rest and distance(point, replaced_stay_anchor) <= JOIN_TOLERANCE_M:
                        duration, method = 0.0, "source_stay_replaced_by_explicit_departure"
                    else:
                        replaced_stay_anchor = None
            before = clock
            if duration is None:
                clock = None; day["unknown_count"] += 1
                unknowns.append({"point_index": i, "source_id": point["source_id"],
                                 "reason": "missing_or_reversed_source_time_without_speed_assumption"})
            else:
                day["rest_minutes" if rest else "moving_minutes"] += duration
                if rest:
                    day["source_rest_minutes"] += duration
                if clock:
                    clock += timedelta(minutes=duration)
            timeline.append({"kind": "source_rest" if rest else "move", "from_point_index": i - 1,
                             "point_index": i, "duration_minutes": round(duration, 6) if duration is not None else None,
                             "method": method, "arrival_at": clock.isoformat() if clock else None,
                             "departure_at": before.isoformat() if before else None, "time_role": "planned_estimate"})
        arrival = clock
        for op in sorted(events.get(i, []), key=lambda item: {"deadline": 0, "arrival": 0, "stop": 1, "camp": 2, "depart": 3}[item.kind]):
            if op.calendar_date and arrival and arrival.date() != op.calendar_date and op.kind != "depart":
                conflicts.append({"code": "event_date_constraint_mismatch", "point_index": i, "calendar_date": op.calendar_date.isoformat(), "arrival_at": arrival.isoformat()})
            if op.kind in ("deadline", "arrival"):
                target = op.latest_arrival_at or op.arrival_at
                if target is None:
                    conflicts.append({"code": "arrival_limit_missing", "point_index": i})
                elif arrival is None:
                    conflicts.append({"code": "arrival_constraint_unverifiable", "point_index": i,
                                      "latest_arrival_at": target.isoformat()})
                elif arrival > target:
                    conflicts.append({"code": "arrival_constraint_unsatisfied", "point_index": i,
                                      "arrival_at": arrival.isoformat(), "latest_arrival_at": target.isoformat()})
                elif op.arrival_at is not None and arrival != op.arrival_at:
                    conflicts.append({"code": "exact_arrival_requires_review", "point_index": i,
                                      "arrival_at": arrival.isoformat(), "requested_arrival_at": op.arrival_at.isoformat()})
            elif op.kind == "stop":
                if op.duration_minutes is None:
                    conflicts.append({"code": "fixed_stop_duration_missing", "point_index": i}); continue
                stop_start = clock
                day["rest_minutes"] += op.duration_minutes; day["fixed_rest_minutes"] += op.duration_minutes
                if clock:
                    clock += timedelta(minutes=op.duration_minutes)
                timeline.append({"kind": "fixed_stop", "point_index": i, "duration_minutes": op.duration_minutes,
                                 "start_at": stop_start.isoformat() if stop_start else None,
                                 "end_at": clock.isoformat() if clock else None,
                                 "arrival_at": stop_start.isoformat() if stop_start else None,
                                 "departure_at": clock.isoformat() if clock else None,
                                 "label": op.label or op.at, "time_role": "explicit_planning_constraint"})
            elif op.kind == "camp":
                finish(i, op.label or op.at, True)
                next_clock = op.departure_at
                if next_clock is None and clock is not None and op.duration_minutes is not None:
                    next_clock = clock + timedelta(minutes=op.duration_minutes)
                if next_clock is None:
                    unknowns.append({"point_index": i, "reason": "camp_departure_unknown"})
                if clock and next_clock and next_clock < clock:
                    conflicts.append({"code": "camp_departure_before_arrival", "point_index": i})
                timeline.append({"kind": "camp", "point_index": i, "arrival_at": clock.isoformat() if clock else None,
                                 "departure_at": next_clock.isoformat() if next_clock else None, "label": op.label or op.at,
                                 "duration_minutes": (next_clock - clock).total_seconds() / 60 if next_clock and clock and next_clock >= clock else None,
                                 "time_role": "explicit_planning_constraint"})
                clock = next_clock
                replaced_stay_anchor = point
                day = {"day_id": f"D{start_day_index + len(days)}", "mission_day_id": f"D{start_day_index + len(days)}",
                       "departure_at": clock.isoformat() if clock else None, "start_point_index": i,
                       "moving_minutes": 0.0, "rest_minutes": 0.0, "unknown_count": 0,
                       "source_rest_minutes": 0.0, "fixed_rest_minutes": 0.0}
            elif op.kind == "depart":
                if op.departure_at is None:
                    conflicts.append({"code": "departure_time_missing", "point_index": i})
                else:
                    if clock and op.departure_at < clock:
                        conflicts.append({"code": "departure_before_arrival", "point_index": i})
                    clock = op.departure_at
                    replaced_stay_anchor = point
                    if i == day["start_point_index"]:
                        day["departure_at"] = clock.isoformat()
        if i in mandatory_cp:
            checkpoints.append({"candidate_id": f"planned.cp.{len(checkpoints):03d}", "point_index": i,
                                "label": next((op.label or op.at for op in events.get(i, []) if op.label or op.at), f"Plan point {i}"),
                                "lat": point["lat"], "lon": point["lon"], "mission_day_id": day["day_id"],
                                "arrival_at": arrival.isoformat() if arrival else None,
                                "departure_at": clock.isoformat() if clock else None,
                                "candidate_only": True, "runtime_safety_truth": False})
    if nodes and (not days or day["start_point_index"] < len(nodes) - 1):
        finish(len(nodes) - 1, "Finish")
    if unknowns:
        issues.append(_issue("planned_time_unknown", "未有足夠來源或腳程的路段保持未知；後續 ETA 不補值。", count=len(unknowns)))
    if conflicts:
        issues.append(_issue("itinerary_constraints_conflict", "時間約束不相容或無法核對；不會自動加速或縮短休息。", severity="error", conflicts=conflicts))
    return {"schema_version": "plannedItinerary.v1", "time_role": "planned_estimate",
            "timezone": departure.isoformat()[-6:] if departure else None, "days": days,
            "timeline": timeline, "unknowns": unknowns, "conflicts": conflicts,
            "assumptions": {"pace_mode": request.pace_mode, "default_speed_kmh": request.default_speed_kmh,
                            "stationary_threshold_kmh": 0.3, "fixed_stops_are_additional": True,
                            "historical_dates_reused": False}}, checkpoints


def _export(parts: list, project_id: str, geometry_sha: str, itinerary_sha: str) -> str:
    ET.register_namespace("", GPX_NS); ET.register_namespace("scout", PLAN_NS)
    tree = ET.Element(f"{{{GPX_NS}}}gpx", {"version": "1.1", "creator": "Scout Planned Route"})
    metadata = ET.SubElement(tree, f"{{{GPX_NS}}}metadata")
    ET.SubElement(metadata, f"{{{GPX_NS}}}name").text = f"Planned · {project_id}"
    ET.SubElement(metadata, f"{{{GPX_NS}}}desc").text = "Planned geometry; not a recorded activity. Timing, constraints and sources are in the companion manifest."
    ext = ET.SubElement(metadata, f"{{{GPX_NS}}}extensions")
    ET.SubElement(ext, f"{{{PLAN_NS}}}provenance", {"role": "planned", "candidate_only": "true", "runtime_safety_truth": "false",
                                                 "geometry_sha256": geometry_sha, "itinerary_sha256": itinerary_sha})
    track = ET.SubElement(tree, f"{{{GPX_NS}}}trk")
    ET.SubElement(track, f"{{{GPX_NS}}}name").text = "Planned GPX"
    for part in parts:
        seg = ET.SubElement(track, f"{{{GPX_NS}}}trkseg")
        for point in part:
            node = ET.SubElement(seg, f"{{{GPX_NS}}}trkpt", {"lat": str(point["lat"]), "lon": str(point["lon"])})
            if point.get("ele") is not None:
                ET.SubElement(node, f"{{{GPX_NS}}}ele").text = str(point["ele"])
    return ET.tostring(tree, encoding="unicode", xml_declaration=True)


def _terrain_timing(nodes: list, operations: list, catalog: dict, request: PlannedRouteRequest,
                    departure: datetime | None, issues: list, start_day: int) -> tuple[dict, list]:
    from scout_planned_timing import TimingEvent, plan_terrain_schedule
    if len(nodes) < 2:
        return _timing(nodes, operations, catalog, request, departure, issues, start_day)
    events, labels = [], {}
    for op in operations:
        if op.kind not in ("stop", "camp", "depart", "deadline", "arrival"):
            continue
        anchor = _resolve(op.at, catalog, request, issues) if op.at else None
        index = _operation_location(nodes, anchor, op, issues) if anchor else (0 if op.kind == "depart" else None)
        if index is None:
            if not op.at and op.kind != "depart":
                issues.append(_issue("event_location_required", "時間約束需要明確位置。", severity="error", operation=op.kind))
            continue
        data = {key: value for key, value in op.model_dump(mode="json").items() if key in TimingEvent.model_fields}
        data.update(point_index=index, kind="deadline" if op.kind == "arrival" else op.kind,
                    candidate_id=f"planned.cp.event.{index:03d}", label=op.label or (anchor or {}).get("label"))
        events.append(data)
        labels[index] = data["label"]
    schedule = plan_terrain_schedule(nodes, options=request.terrain_timing, departure_at=departure,
                                     events=events, start_day_index=start_day)
    schedule.update(schema_version="plannedItinerary.v1", timing_schema_version="plannedTerrainTiming.v1",
                    timezone=departure.isoformat()[-6:] if departure else None)
    schedule.setdefault("assumptions", {}).update(pace_mode="terrain_team_model", historical_dates_reused=False,
                                                  fixed_stops_are_additional=True)
    if schedule["unknowns"] or schedule.get("campsite_missing_inputs"):
        issues.append(_issue("planned_time_unknown", "地形、隊伍或營地資料不足的項目保留未知，不補完整行程 ETA。",
                             count=len(schedule["unknowns"]), missing_campsite_inputs=schedule.get("campsite_missing_inputs", [])))
    if schedule["conflicts"]:
        issues.append(_issue("itinerary_constraints_conflict", "時間、日照或營地約束不相容；不會自動加速。",
                             severity="error", conflicts=schedule["conflicts"]))
    required = {0, len(nodes) - 1, *[event["point_index"] for event in events],
                *[event["point_index"] for event in schedule.get("generated_camp_events", [])]}
    for index, node in enumerate(nodes):
        if index and node.get("break_before"):
            required.update((index - 1, index))
    arrivals = {row["point_index"]: row for row in schedule.get("point_arrivals", [])}
    departure_rows = {}
    for row in schedule["timeline"]:
        if row.get("kind") != "move" and row.get("departure_at") is not None:
            departure_rows[row["point_index"]] = row
    checkpoints = []
    for index in sorted(required):
        node = nodes[index]
        arrival = arrivals.get(index, {})
        post_event = departure_rows.get(index, arrival)
        conditional = arrival.get("conditional_on_prior_unknown", False)
        point = {"candidate_id": f"planned.cp.{len(checkpoints):03d}", "point_index": index,
                 "label": labels.get(index) or f"Plan point {index}", "lat": node["lat"], "lon": node["lon"],
                 "mission_day_id": arrival.get("day_id", f"D{start_day}"),
                 "arrival_at": None if conditional else arrival.get("arrival_at"),
                 "departure_at": None if conditional else post_event.get("departure_at", arrival.get("arrival_at")),
                 "arrival_at_lower": None if conditional else arrival.get("arrival_at_lower"),
                 "arrival_at_upper": None if conditional else arrival.get("arrival_at_upper"),
                 "conditional_arrival_at": arrival.get("arrival_at") if conditional else None,
                 "conditional_departure_at": post_event.get("departure_at", arrival.get("arrival_at")) if conditional else None,
                 "candidate_only": True, "runtime_safety_truth": False}
        checkpoints.append(point)
    return schedule, checkpoints


def compile_planned_route(project_root: Path, request: PlannedRouteRequest | dict) -> dict:
    request = PlannedRouteRequest.model_validate(request)
    root = Path(project_root).resolve()
    catalog = load_planned_catalog(root)
    if request.source_snapshot_sha256 and request.source_snapshot_sha256 != catalog["source_snapshot_sha256"]:
        raise PlannedRouteConflict("source_snapshot_changed", "Sources changed; regenerate the Planned preview.")
    issues: list[dict] = []
    operations, departure, intent, effective_request, start_day = _text_intent(request, catalog, issues)
    nodes = _compose(catalog, effective_request, operations, issues)
    route_geojson, axis, segments, parts = _geometry(nodes, catalog, issues)
    if request.terrain_timing is not None:
        itinerary, checkpoints = _terrain_timing(nodes, operations, catalog, request, departure, issues, start_day)
    else:
        itinerary, checkpoints = _timing(nodes, operations, catalog, request, departure, issues, start_day)
    for point in axis:
        point["planned_day_ids"] = [day["day_id"] for day in itinerary["days"]
                                    if day["start_point_index"] <= point["point_index"] <= day["end_point_index"]]
    golden = next((source for source in catalog["sources"] if source["source_id"] == catalog.get("golden_source_id")), None)
    golden_coordinates, golden_parts, golden_length = None, None, None
    golden_geojson = None
    if golden:
        golden_nodes = [p for pi, part in enumerate(golden["parts"]) for p in _nodes(golden, pi, 0, len(part) - 1)]
        golden_geojson, _, _, golden_parts = _geometry(golden_nodes, catalog, [])
        golden_coordinates = [[[p["lon"], p["lat"], p.get("ele")] for p in part] for part in golden_parts]
        golden_length = sum(distance(a, b) for part in golden["parts"] for a, b in zip(part, part[1:]) if distance(a, b) <= SOURCE_GAP_M)
    planned_coordinates = [[[p["lon"], p["lat"], p.get("ele")] for p in part] for part in parts]
    geometry_sha = digest(planned_coordinates)
    itinerary_sha = digest(itinerary)
    geometry_changed = planned_coordinates != golden_coordinates if golden is not None else None
    planned_length = axis[-1]["route_order_m"] if axis else 0
    if golden:
        bbox = {"min_lat": min(p["lat"] for part in golden["parts"] for p in part),
                "max_lat": max(p["lat"] for part in golden["parts"] for p in part),
                "min_lon": min(p["lon"] for part in golden["parts"] for p in part),
                "max_lon": max(p["lon"] for part in golden["parts"] for p in part)}
        outside = [segment["segment_id"] for segment in segments if any(
            not (bbox["min_lat"] <= point["lat"] <= bbox["max_lat"] and bbox["min_lon"] <= point["lon"] <= bbox["max_lon"])
            for point in axis[segment["start_point_index"]:segment["end_point_index"] + 1])]
    else:
        outside = [segment["segment_id"] for segment in segments]
    coverage = {"status": "coverage_needed" if outside else "unverified" if geometry_changed else "existing_golden_scope" if golden else "coverage_needed",
                "reason": "No Golden reference exists; candidate route needs independent map/DEM verification." if golden is None else
                          "New route needs map/DEM coverage verification; Golden bounds alone do not prove terrain coverage." if geometry_changed else
                          "Original Golden geometry retained; producer freshness is checked separately.",
                "affected_segments": outside, "dem_coverage_verified": False}
    if geometry_changed or golden is None:
        issues.append(_issue("coverage_needed" if outside or golden is None else "map_coverage_unverified", coverage["reason"], affected_segments=outside))
    source_lookup = {source["source_id"]: source for source in catalog["sources"]}
    for segment in segments:
        if source_lookup[segment["source_id"]]["kind"].startswith("trh"):
            issues.append(_issue("terrain_candidate_non_operational", "Terrain hypothesis remains candidate-only; review/export do not prove walkability.", source_id=segment["source_id"]))
    for ref, expected in catalog["source_hashes"].items():
        h = hashlib.sha256()
        with _path(root, ref).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            raise PlannedRouteConflict("source_changed_during_preview", f"Source changed during composition: {ref}")
    result = {"schema_version": "plannedRoutePreview.v1", "project_id": catalog["project_id"],
              "request": request.model_dump(mode="json"), "intent_operations": [op.model_dump(mode="json") for op in operations],
              "intent_report": intent, "effective_route_selections": [row.model_dump(mode="json") for row in effective_request.route_selections],
              "source_snapshot_sha256": catalog["source_snapshot_sha256"], "source_hashes": catalog["source_hashes"],
              "geometry_sha256": geometry_sha, "itinerary_sha256": itinerary_sha,
              "planned_gpx": _export(parts, catalog["project_id"], geometry_sha, itinerary_sha),
              "route_geojson": route_geojson, "golden_geojson": golden_geojson,
              "route_axis": axis, "checkpoints": checkpoints, "segments": segments, "itinerary": itinerary,
              "comparison": {"status": "available" if golden else "unavailable", "golden_available": golden is not None,
                             "geometry_changed": geometry_changed,
                             "golden_geometry_sha256": digest(golden_coordinates) if golden else None,
                             "golden_length_m": round(golden_length, 3) if golden else None, "planned_length_m": planned_length,
                             "added_distance_m": round(planned_length - golden_length, 3) if golden else None,
                             "geometry_comparison_policy": "full_source_points_in_order_with_recording_gaps_split.v1",
                             "golden_original_segment_count": len(golden["parts"]) if golden else None,
                             "golden_gap_preserving_segment_count": len(golden_parts) if golden else None,
                             "golden_source_sha256": golden["sha256"] if golden else None, "original_timestamps_preserved": True},
              "coverage": coverage, "issues": issues,
              "status": "blocked" if any(i.get("severity") == "error" for i in issues) else "needs_review" if issues else "ready",
              "candidate_only": True, "runtime_safety_truth": False, "departure_approval_granted": False,
              "recorded_track": False, "writes_performed": False}
    result["preview_sha256"] = digest(result)
    return result
