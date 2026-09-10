"""Build a separate, candidate-only input view for Planned route assessors.

This is an adapter, not another import. It never creates an observed track or a
reviewed MissionGraph, and never writes the owner project or immutable bundle.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scout_planned_route_models import PlannedRouteConflict


INPUT_VERSION = "planned-analysis-inputs.v1"
BOUNDARY = {"candidate_only": True, "runtime_safety_truth": False, "recorded_track": False}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def safe_path(root: Path, ref: str) -> Path:
    value = Path(ref)
    if value.is_absolute() or not ref or ".." in value.parts or any(p.startswith(".env") for p in value.parts):
        raise PlannedRouteConflict("invalid_analysis_ref", "Analysis references must remain inside their workspace.")
    path = root.resolve() / value
    current = root.resolve()
    for part in value.parts:
        current = current / part
        if current.is_symlink():
            raise PlannedRouteConflict("invalid_analysis_ref", "Analysis references must not traverse symbolic links.")
    if not path.resolve().is_relative_to(root.resolve()):
        raise PlannedRouteConflict("invalid_analysis_ref", "An analysis reference escapes its workspace.")
    return path


def write_json(root: Path, ref: str, payload: Any) -> str:
    path = safe_path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def read_json(root: Path, ref: str) -> Any:
    return json.loads(safe_path(root, ref).read_text(encoding="utf-8"))


def items(payload: Any, *keys: str) -> list[dict]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return items(payload[key])
    return []


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def distance_m(a: dict, b: dict) -> float:
    lat1, lat2 = math.radians(float(a["lat"])), math.radians(float(b["lat"]))
    dlat, dlon = lat2 - lat1, math.radians(float(b["lon"]) - float(a["lon"]))
    return 6371000 * 2 * math.asin(min(1.0, math.sqrt(
        math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)))


def subject_binding(bundle: dict, run_root: Path) -> dict:
    manifest = bundle["manifest"]
    return {"project_id": manifest["project_id"], "version_id": manifest["version_id"],
            "manifest_sha256": manifest["manifest_sha256"], "geometry_sha256": manifest["geometry_sha256"],
            "itinerary_sha256": manifest["itinerary_sha256"],
            "input_adapter_version": INPUT_VERSION, **BOUNDARY}


def _canonical(bundle: dict, run_root: Path, preparation: dict, key: str, filename: str) -> Any:
    ref = preparation.get("canonical_refs", {}).get(key)
    if not ref:
        return copy.deepcopy(bundle["preview"].get(key))
    path = safe_path(run_root, ref)
    expected = bundle["manifest"].get("files", {}).get(filename, {}).get("sha256")
    if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise PlannedRouteConflict("analysis_input_changed", f"Prepared {key} no longer matches the saved Planned bundle.")
    return read_json(run_root, ref)


def build_planned_analysis_inputs(owner_root: Path, bundle: dict, run_root: Path,
                                  preparation: dict) -> dict:
    """Materialize legacy-schema inputs on the original Planned ordered axis."""
    owner_root, run_root = Path(owner_root).resolve(), Path(run_root).resolve()
    if run_root == owner_root:
        raise PlannedRouteConflict("invalid_analysis_workspace", "The analysis run must be separate from the owner workspace.")
    binding = subject_binding(bundle, run_root)
    expected_binding = preparation.get("subject_binding") or {}
    for key in ("project_id", "version_id", "manifest_sha256", "geometry_sha256", "itinerary_sha256"):
        if expected_binding.get(key) not in (None, binding[key]):
            raise PlannedRouteConflict("analysis_subject_mismatch", f"Preparation belongs to another {key}.")
    axis = items(_canonical(bundle, run_root, preparation, "route_axis", "route_axis.json"), "points", "route_axis")
    original_cp = items(_canonical(bundle, run_root, preparation, "checkpoints", "checkpoints.json"), "checkpoints")
    itinerary = _canonical(bundle, run_root, preparation, "itinerary", "itinerary.json") or {}
    route_geojson = _canonical(bundle, run_root, preparation, "route_geojson", "route.geojson") or bundle["preview"].get("route_geojson", {})
    if len(axis) < 2 or [p.get("point_index") for p in axis] != list(range(len(axis))):
        raise PlannedRouteConflict("invalid_analysis_axis", "Planned axis requires ordered, consecutive point indices.")
    for point in axis:
        for key, bound in (("lat", 90), ("lon", 180)):
            number = point.get(key)
            if not isinstance(number, (float, int)) or isinstance(number, bool) or not math.isfinite(number) or abs(number) > bound:
                raise PlannedRouteConflict("invalid_analysis_axis", "Planned axis has an invalid coordinate.")
    days = items(itinerary, "days")
    timeline = items(itinerary, "timeline")
    cp_by_index = {cp["point_index"]: copy.deepcopy(cp) for cp in original_cp
                   if isinstance(cp.get("point_index"), int) and 0 <= cp["point_index"] < len(axis)}
    required = {0, len(axis) - 1, *cp_by_index}
    gap_indices = set()
    for index, point in enumerate(axis[1:], 1):
        if point.get("break_before"):
            required.update((index - 1, index))
            if distance_m(axis[index - 1], point) > .01:
                gap_indices.add(index)
    for day in days:
        required.update(int(day[k]) for k in ("start_point_index", "end_point_index")
                        if isinstance(day.get(k), int) and 0 <= day[k] < len(axis))
    point_times: dict[int, dict] = {}
    for event in timeline:
        index = event.get("point_index")
        if not isinstance(index, int):
            continue
        values = point_times.setdefault(index, {})
        if event.get("arrival_at") and "arrival_at" not in values:
            values["arrival_at"] = event["arrival_at"]
        if event.get("departure_at") and event.get("kind") not in {"move", "source_rest"}:
            values["departure_at"] = event["departure_at"]
    for day in days:
        start, end = day.get("start_point_index"), day.get("end_point_index")
        if isinstance(start, int):
            point_times.setdefault(start, {}).setdefault("departure_at", day.get("departure_at"))
        if isinstance(end, int):
            point_times.setdefault(end, {}).setdefault("arrival_at", day.get("arrival_at"))
    cp_values = []
    label_counts = Counter(cp.get("label") for cp in original_cp)
    for index in sorted(required):
        point, original = axis[index], cp_by_index.get(index, {})
        cp_id = original.get("candidate_id") or f"planned.analysis.cp.{index:06d}"
        label = original.get("label") or ("起點" if index == 0 else "終點" if index == len(axis) - 1 else f"Plan point {index}")
        unique_label = f"{label} [{cp_id}]" if label_counts[label] > 1 else label
        times = {**point_times.get(index, {}), **{k: original[k] for k in ("arrival_at", "departure_at") if original.get(k)}}
        arrival = times.get("arrival_at") or (times.get("departure_at") if index == 0 else None)
        departure = times.get("departure_at") or arrival
        cp_values.append({**original, "candidate_id": cp_id, "label": unique_label, "display_label": label,
                          "route_point_index": index, "point_index": index,
                          "distance_from_start_m": point["route_order_m"], "route_distance_m": point["route_order_m"],
                          "lat": point["lat"], "lon": point["lon"], "ele": point.get("ele"),
                          "checkpoint_type": "start" if index == 0 else "finish" if index == len(axis) - 1 else "planned_checkpoint",
                          "arrival_at": arrival, "departure_at": departure,
                          "source_role": "planned", "time_role": "planned_estimate", "review_state": "candidate", **BOUNDARY})
    segments, policies, features, gaps = [], [], [], []
    for first, last in zip(cp_values, cp_values[1:]):
        a, b = first["point_index"], last["point_index"]
        breaks = sorted(i for i in gap_indices if a < i <= b)
        if breaks:
            gaps.append({"code": "route_geometry_gap", "from_cp_id": first["candidate_id"], "to_cp_id": last["candidate_id"],
                         "from_point_index": a, "to_point_index": b, "break_point_indices": breaks,
                         "reason": "No CP edge or straight connector was created across a recorded geometry gap."})
            continue
        points = axis[a:b + 1]
        arrivals, departures = parse_time(last.get("arrival_at")), parse_time(first.get("departure_at"))
        minutes = (arrivals - departures).total_seconds() / 60 if arrivals and departures else None
        if minutes is not None and minutes < 0:
            minutes = None
        def elevation_delta(sign: int) -> float | None:
            if any(p.get("ele") is None for p in points):
                return None
            return round(sum(max(0, sign * (q["ele"] - p["ele"])) for p, q in zip(points, points[1:])), 3)
        segment_id = f"planned.analysis.seg.{len(segments):05d}"
        segment = {"candidate_id": segment_id, "segment_id": segment_id,
                   "from_candidate_id": first["candidate_id"], "to_candidate_id": last["candidate_id"],
                   "start_point_index": a, "end_point_index": b,
                   "distance_m": round(max(0, last["route_distance_m"] - first["route_distance_m"]), 3),
                   "from_m": first["route_distance_m"], "to_m": last["route_distance_m"],
                   "elevation_gain_m": elevation_delta(1), "elevation_loss_m": elevation_delta(-1),
                   "eta_from": first.get("departure_at"), "eta_to": last.get("arrival_at"),
                   "expected_duration_minutes": minutes, "lat": points[len(points) // 2]["lat"],
                   "lon": points[len(points) // 2]["lon"], "time_role": "planned_estimate",
                   "source_refs": ["inputs/route_axis.json", "inputs/itinerary.json"], **BOUNDARY}
        segments.append(segment)
        policies.append({"segment_candidate_id": segment_id, "requirement": {
            "expected_duration_seconds": minutes * 60 if minutes is not None else None},
            "unknown_requirements": ["requires_daylight", "retreat_available", "water_available", "signal_expected"], **BOUNDARY})
        if segment["distance_m"] > 0:
            features.append({"type": "Feature", "properties": segment,
                             "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in points]}})
    estimates = [{"estimate_id": cp["candidate_id"], "to_node_id": cp["candidate_id"], "to_node_name": cp["label"],
                  "eta": cp.get("arrival_at"), "departure_at": cp.get("departure_at"), "point_index": cp["point_index"],
                  "mission_day_id": cp.get("mission_day_id"), "time_role": "planned_estimate", **BOUNDARY} for cp in cp_values]
    eta = {"artifact_kind": "pretrip_planned_eta", "schema_version": INPUT_VERSION,
           "project_id": binding["project_id"], "estimates": estimates, "days": days, "timeline": timeline,
           "assumption": {"target_eta": days[-1].get("arrival_at") if days else None},
           "unknowns": itinerary.get("unknowns", []), "input_binding": binding, **BOUNDARY}
    bbox = {"min_lat": min(p["lat"] for p in axis), "max_lat": max(p["lat"] for p in axis),
            "min_lon": min(p["lon"] for p in axis), "max_lon": max(p["lon"] for p in axis)}
    summary = {"project_id": binding["project_id"], "artifact_id": binding["version_id"],
               "route_name": f"Planned {binding['version_id']}", "route_role": "planned",
               "distance_m": axis[-1]["route_order_m"], "bbox_wgs84": bbox,
               "point_count": len(axis), "checkpoint_count": len(cp_values), "segment_count": len(segments),
               "elevation_gain_m": sum(s["elevation_gain_m"] or 0 for s in segments),
               "elevation_loss_m": sum(s["elevation_loss_m"] or 0 for s in segments),
               "elevation_incomplete": any(p.get("ele") is None for p in axis), "input_binding": binding, **BOUNDARY}
    workspace_ref = "workspaces/analysis"
    root = safe_path(run_root, workspace_ref)
    payloads = {"route_summary_ref": ("normalized/routes/route_summary.json", summary),
                "checkpoint_candidates_ref": ("candidates/checkpoints.json", cp_values),
                "segment_candidates_ref": ("candidates/segments.json", segments),
                "segment_policy_candidates_ref": ("outputs/segment_policy_candidates.json", policies),
                "planned_eta_ref": ("outputs/planned_eta.json", eta),
                "segment_display_geometry_ref": ("outputs/segment_display_geometry.json", {"type": "FeatureCollection", "features": features}),
                "planned_route_geometry_ref": ("inputs/planned_route.geojson", route_geojson),
                "reference_tracks_ref": ("inputs/planned_route_track.json", {"tracks": [{
                    "track_id": binding["version_id"], "route_role": "planned_gpx_reference", "point_count": len(axis),
                    "geometry_ref": "inputs/planned_route.geojson", **BOUNDARY}], **BOUNDARY}),
                "planned_route_axis_ref": ("inputs/route_axis.json", axis)}
    project = {"project_id": binding["project_id"], "name": summary["route_name"], "analysis_subject_kind": "planned_gpx",
               "planned_analysis_binding": binding, "mission_day_ids": [d.get("mission_day_id") or d.get("day_id") for d in days], **BOUNDARY}
    hashes = {}
    for key, (ref, payload) in payloads.items():
        hashes[ref] = write_json(root, ref, payload)
        project[key] = ref
    write_json(root, "project.json", project)
    graph = {"nodes": cp_values, "edges": segments, "gaps": gaps, "input_binding": binding,
             "topology_role": "planned_candidate_cp_edges", "reviewed_mission_graph": False, **BOUNDARY}
    graph_ref = f"{workspace_ref}/outputs/planned_cp_graph.json"
    write_json(run_root, graph_ref, graph)
    return {"status": "partial" if gaps else "ready", "workspace_ref": workspace_ref, "graph_ref": graph_ref,
            "subject_binding": binding, "canonical_refs": {k: f"{workspace_ref}/{v[0]}" for k, v in payloads.items()},
            "input_hashes": hashes, "graph": graph, "route_axis": axis, "itinerary": itinerary,
            "route_summary": summary, "planned_eta": eta, "gaps": gaps, **BOUNDARY}
