"""Read-only, versioned route evidence for the Dashboard trip notebook.

Browser drafts never enter the mission baseline, recording registry or workspace.
All route matching and reference timing here remain candidate evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from geo_utils import haversine_m
from post_analysis_capability_models import RestDetectionPolicy
from post_analysis_rest_detection import detect_rest_intervals
from pretrip_reference_segment_timing import ReferenceTimingNode, build_reference_segment_timing
from route_matching import RoutePoint, load_gpx_route

BOUNDARY = {
    "candidate_only": True, "runtime_safety_truth": False,
    "phase1_runtime_mutation_allowed": False, "workspace_write_allowed": False,
    "outbound_sync_allowed": False, "departure_approval_granted": False,
}


def safe_ref(root: Path, ref: str) -> Path:
    path = (root / ref).resolve()
    if not ref or Path(ref).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Workspace reference must stay inside the selected workspace")
    return path


def build_notebook_snapshot(root: Path) -> dict[str, Any]:
    """No caches, writes, remote refresh, baseline migration or worker launch."""
    root = root.resolve()
    receipts: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []

    def read(ref: str, default: Any = None) -> Any:
        try:
            if Path(ref).suffix.lower() != ".json":
                raise ValueError("Notebook evidence must be JSON")
            path = safe_ref(root, ref)
            raw = path.read_bytes()
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError("Evidence exceeds notebook input size")
            value = json.loads(raw)
            receipts.append({"ref": ref, "sha256": hashlib.sha256(raw).hexdigest(), "status": "read"})
            return value
        except (OSError, ValueError) as exc:
            receipts.append({"ref": ref, "status": "unavailable", "reason": type(exc).__name__})
            issues.append({"code": "unavailable_evidence", "ref": ref, "message": "來源不可讀；保留缺值。"})
            return {} if default is None else default

    project = read("project.json")
    if not isinstance(project, dict) or not project.get("project_id"):
        raise ValueError("Project manifest is missing its identity")
    # The existing timing builder reads these refs. Reject traversal before calling it.
    for key in ("checkpoint_candidates_ref", "overpass_aligned_checkpoint_candidates_ref",
                "mcp_candidates_ref", "route_summary_ref"):
        if project.get(key):
            safe_ref(root, str(project[key]))
    summary = read(str(project.get("route_summary_ref") or "normalized/routes/route_summary.json"))
    bundle = read(str(project.get("route_evidence_bundle_ref") or "normalized/routes/route_evidence_bundle.json"))
    golden = bundle.get("golden_route", {})
    geometry_ref = str(golden.get("filtered_geometry_ref") or "")
    geometry: list[list[float]] = []
    route_points: list[RoutePoint] = []
    if geometry_ref:
        try:
            if Path(geometry_ref).suffix.lower() != ".gpx":
                raise ValueError("Notebook geometry must be a GPX reference")
            path = safe_ref(root, geometry_ref)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if golden.get("filtered_geometry_sha256") not in (None, digest):
                raise ValueError("Geometry hash mismatch")
            route_points = load_gpx_route(path).points
            receipts.append({"ref": geometry_ref, "sha256": digest, "status": "read"})
            geometry = [[p.lon, p.lat, round(p.progress_m, 1), p.elevation_m] for p in route_points]
        except (OSError, ValueError) as exc:
            issues.append({"code": "invalid_geometry", "ref": geometry_ref, "message": str(exc)})

    cp_ref = str(project.get("overpass_aligned_checkpoint_candidates_ref") or project.get("checkpoint_candidates_ref") or "candidates/checkpoints.json")
    checkpoints = read(cp_ref, [])
    if isinstance(checkpoints, dict):
        checkpoints = checkpoints.get("checkpoint_candidates", [])
    mcp_ref = str(project.get("mcp_candidates_ref") or "outputs/mcp/mcp_candidates.json")
    mcps = read(mcp_ref).get("mcp_candidates", [])
    points: list[dict[str, Any]] = []
    for row, ref, kind in [(p, cp_ref, "cp") for p in checkpoints] + [(p, mcp_ref, "mcp") for p in mcps]:
        lat, lon = row.get("lat"), row.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
            continue
        nearest = min(route_points, key=lambda p: (p.lat - lat) ** 2 + ((p.lon - lon) * math.cos(math.radians(lat))) ** 2) if route_points else None
        offset = haversine_m(lat, lon, nearest.lat, nearest.lon) if nearest else None
        declared = row.get("route_distance_m", row.get("distance_m"))
        projected = round(nearest.progress_m, 1) if nearest and offset <= 200 else None
        mismatch = projected is not None and isinstance(declared, (int, float)) and abs(projected - declared) > 1000
        point_id = str(row.get("candidate_id") or row.get("mcp_id") or "")
        points.append({
            "id": point_id, "label": str(row.get("label") or point_id), "kind": kind,
            "classes": row.get("mcp_classes") or [row.get("checkpoint_type", "checkpoint")],
            "lat": lat, "lon": lon, "elevation_m": nearest.elevation_m if nearest else None,
            "route_distance_m": projected, "declared_distance_m": declared,
            "projection_offset_m": round(offset, 1) if offset is not None else None,
            "position_mismatch": mismatch, "source_ref": ref,
            "review_state": row.get("review_state", "unknown"),
            "notes": str(row.get("notes") or ""),
            "resource_status": "unverified", "live_arrival": None,
        })
    points.sort(key=lambda p: (p["route_distance_m"] is None, p["route_distance_m"] or 0, p["id"]))
    positioned = [p for p in points if p["route_distance_m"] is not None]
    selected = [p for p in positioned if p["kind"] == "mcp"]
    if positioned:
        selected.extend([positioned[0], positioned[-1]])
        for distance in range(5000, int(positioned[-1]["route_distance_m"]), 5000):
            selected.append(min(positioned, key=lambda p: abs(p["route_distance_m"] - distance)))
    selected = sorted({p["id"]: p for p in selected}.values(), key=lambda p: p["route_distance_m"])
    nodes: list[dict[str, Any]] = []
    for point in selected:
        if nodes and point["route_distance_m"] - nodes[-1]["route_distance_m"] < 100:
            if point["kind"] == "mcp":
                nodes[-1] = point
        else:
            nodes.append(point)
    timing_nodes = [ReferenceTimingNode(p["id"], p["label"], p["lat"], p["lon"], p["route_distance_m"], p["kind"], p["id"], 2) for p in nodes]
    source_ref = str(project.get("historical_gpx_source_index_ref") or "sources/historical_gpx_source_index.json")
    safe_ref(root, source_ref)
    read(source_ref)
    guide_ref = str(project.get("route_guide_timing_ref") or "candidates/route_guide_timing.json")
    safe_ref(root, guide_ref)
    if (root / guide_ref).is_file():
        read(guide_ref)
    timing = build_reference_segment_timing(root, source_index_ref=source_ref, route_guide_timing_ref=guide_ref,
                                             timing_nodes=timing_nodes, allow_external_sources=False) if len(nodes) >= 2 else {"segments": [], "source_resolution": [], "counts": {}}
    segments = []
    for start, end, item in zip(nodes, nodes[1:], timing["segments"]):
        segments.append({"id": f'{start["id"]}>{end["id"]}', "from_id": start["id"], "to_id": end["id"],
                         "distance_m": round(end["route_distance_m"] - start["route_distance_m"], 1),
                         "duration_minutes": item["duration_minutes"], "sample_count": item["sample_count"],
                         "source_count": item["source_count"], "direction": "reference_forward",
                         "duration_basis": "historical_elapsed_including_unknown_stops",
                         "rejected_summary": item["rejected_summary"]})
    # These diagnostics describe saved artifacts; none is refreshed or promoted here.
    saved_eta = read(str(project.get("planned_eta_ref") or "outputs/planned_eta.json"))
    terrain = read("outputs/navigation/navigation_terrain_intelligence.json")
    weather_ref = str(project.get("cwa_weather_evidence_ref") or "outputs/environment/cwa/cwa_weather_evidence.json")
    weather = read(weather_ref)
    forecasts = [{k: p.get(k) for k in ("lat", "lon", "label", "areaName", "tempC", "rainProbability", "validFrom", "validTo", "source")} for p in weather.get("weather_points", []) if isinstance(p, dict) and p.get("lat") is not None and p.get("lon") is not None]
    for receipt in timing.get("source_resolution", []):
        if receipt.get("workspace_ref") and receipt.get("sha256"):
            receipts.append({"ref": receipt["workspace_ref"], "sha256": receipt["sha256"], "status": receipt["status"]})
    version_basis = {"schema": "trip-notebook.v1", "sources": sorted(receipts, key=lambda r: r["ref"]), "nodes": [p["id"] for p in nodes], "segments": segments}
    version = hashlib.sha256(json.dumps(version_basis, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    for receipt in receipts:
        if receipt.get("sha256") and hashlib.sha256(safe_ref(root, receipt["ref"]).read_bytes()).hexdigest() != receipt["sha256"]:
            raise ValueError("讀取期間來源已更新，請重試；不混用不同版本。")
    return {
        "schema_version": "trip-notebook.v1", "project_id": project["project_id"], "version": version,
        "captured_at": datetime.now(timezone.utc).isoformat(), "route_name": summary.get("route_name") or project.get("route_name"),
        "route_summary": summary, "geometry": geometry, "points": points,
        "planning_node_ids": [p["id"] for p in nodes], "segments": segments,
        "source_resolution": timing.get("source_resolution", []), "timing_counts": timing.get("counts", {}),
        "position_mismatch_count": sum(p["position_mismatch"] for p in points),
        "weather": {"source_ref": weather_ref, "fetched_at": weather.get("fetched_at"),
                    "valid_until": weather.get("forecast_valid_until"), "forecasts": forecasts},
        "diagnostics": {"saved_eta_status": saved_eta.get("status", "missing"), "saved_eta_generated_at": saved_eta.get("generated_at"),
                        "saved_eta_gaps": saved_eta.get("unresolved_gaps", []),
                        "reviewed_baseline_ref": project.get("reviewed_mission_baseline_ref"),
                        "reviewed_baseline_status": "not_activated_by_notebook",
                        "terrain_status": terrain.get("status", "unverified"),
                        "terrain_runtime_usable": False, "terrain_note": "保留既有投影檢查；手冊不啟用地形或安全基準。"},
        "sources": receipts, "issues": issues, "boundary": BOUNDARY,
    }


class NotebookTrackPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elevation_m: float | None = None
    timestamp: datetime
    part: int = Field(default=0, ge=0)

    @field_validator("timestamp")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Track timestamps require a timezone")
        return value


class NotebookAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    origin: Literal["simulation", "user_import"]
    points: list[NotebookTrackPoint] = Field(min_length=2, max_length=20000)


def analyze_notebook_track(request: NotebookAnalysisRequest) -> dict[str, Any]:
    """Use the existing rest detector in memory, separating gaps and GPX parts."""
    policy = RestDetectionPolicy()
    blocks: list[list[RoutePoint]] = [[]]
    distance = ascent = descent = unknown = 0.0
    for i, p in enumerate(request.points):
        if i:
            prev = request.points[i - 1]
            dt = (p.timestamp - prev.timestamp).total_seconds()
            if dt <= 0:
                raise ValueError("紀錄時間必須遞增；請先檢查來源，不會自動修正軌跡。")
            if p.part != prev.part or dt > policy.max_sample_gap_s:
                unknown += dt
                blocks.append([])
            else:
                step = haversine_m(prev.lat, prev.lon, p.lat, p.lon)
                if step / dt * 3.6 > 120:
                    unknown += dt
                    blocks.append([])
                else:
                    distance += step
                    if p.elevation_m is not None and prev.elevation_m is not None:
                        delta = p.elevation_m - prev.elevation_m
                        ascent += max(delta, 0)
                        descent += max(-delta, 0)
        blocks[-1].append(RoutePoint(p.lat, p.lon, p.elevation_m, p.timestamp.isoformat(), distance))
    rests = [r for block in blocks if len(block) > 1 for r in detect_rest_intervals(block, policy=policy, source_ref=f"browser-draft:{request.draft_id}")]
    elapsed = (request.points[-1].timestamp - request.points[0].timestamp).total_seconds()
    resting = sum(r.duration_s for r in rests)
    receipt = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
    return {"schema_version": "trip-notebook-analysis.v1", "draft_id": request.draft_id,
            "receipt_id": receipt, "origin": request.origin, "point_count": len(request.points),
            "elapsed_s": elapsed, "rest_s": resting, "moving_s": max(0, elapsed - resting - unknown),
            "unclassified_gap_s": unknown, "distance_m": round(distance, 1),
            "ascent_m": round(ascent, 1), "descent_m": round(descent, 1),
            "rest_policy": policy.model_dump(mode="json"), "algorithm": "post_analysis_rest_detection.detect_rest_intervals",
            "saved_to_workspace": False, "sent": False, "boundary": BOUNDARY}
