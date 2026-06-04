from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from post_analysis_capability import build_capability_artifacts, summarize_capability_artifacts
from post_analysis_scout_reaction_simulation import (
    NOTE_PREFIX,
    build_scout_reaction_simulation_from_gpx,
)
from pretrip_source_ingest import sha256_file
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parent
CASE_ID = "chilai_nanhua_day1"
ROUTE_FAMILY = "nenggao_andongjun"
RECORDING_SET_RELATIVE_DIR = Path("post_analysis/completed_trips/chilai_nanhua_day1")
RECORDED_RELATIVE_DIR = RECORDING_SET_RELATIVE_DIR / "recorded"
ACTIVE_RELATIVE_DIR = RECORDING_SET_RELATIVE_DIR / "active"
OUTPUTS_RELATIVE_DIR = RECORDING_SET_RELATIVE_DIR / "outputs"
CHECKPOINT_DEFINITIONS_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "checkpoints.json"
)
ROUTE_TIME_ENTRIES_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "route_time_entries.json"
)


def list_completed_trip_recordings(
    *,
    data_root: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    recording_root = data_root / RECORDED_RELATIVE_DIR
    inbox_dir = data_root / "post_analysis" / "inbox"
    recordings = _scan_recordings(
        data_root=data_root,
        roots=[recording_root],
        root=root,
    )
    if not recordings:
        recordings = _scan_recordings(
            data_root=data_root,
            roots=[inbox_dir],
            root=root,
        )
    active = load_active_completed_trip_recording_projection(data_root=data_root, root=root)
    return {
        "artifact_kind": "completed_trip_recording_set",
        "artifact_version": "completed_trip_recording_set.v1",
        "case_id": CASE_ID,
        "route_family": ROUTE_FAMILY,
        "recording_count": len(recordings),
        "recording_set_root": str(recording_root),
        "recording_set_root_exists": recording_root.exists(),
        "recording_set_manifest_path": str(recording_root / "recording_set_manifest.json"),
        "active_recording": active.get("recording") if active else None,
        "recordings": recordings,
        "boundary": _boundary(),
    }


def select_completed_trip_recording_for_post_analysis(
    recording_id: str,
    *,
    data_root: Path,
    root: Path = ROOT,
) -> dict[str, Any]:
    catalog = list_completed_trip_recordings(data_root=data_root, root=root)
    recording = _find_recording(catalog, recording_id)
    if not recording.get("loadable", False):
        raise ValueError(f"completed trip recording is not loadable: {recording_id}")

    source_gpx = Path(recording["absolute_path"])
    if not source_gpx.exists():
        raise FileNotFoundError(f"completed trip GPX not found: {source_gpx}")

    inbox_dir = data_root / "post_analysis" / "inbox"
    active_dir = data_root / ACTIVE_RELATIVE_DIR
    outputs_dir = data_root / OUTPUTS_RELATIVE_DIR / recording_id
    inbox_dir.mkdir(parents=True, exist_ok=True)
    active_dir.mkdir(parents=True, exist_ok=True)
    active_gpx = inbox_dir / "latest_completed_trip.gpx"
    if source_gpx.resolve() != active_gpx.resolve():
        shutil.copy2(source_gpx, active_gpx)

    manifest = _recording_set_manifest(catalog)
    _write_json(Path(catalog["recording_set_manifest_path"]), manifest)

    activated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    active_record = {
        "artifact_kind": "active_completed_trip_recording",
        "case_id": CASE_ID,
        "recording": _public_recording(recording),
        "recording_set_manifest_path": catalog["recording_set_manifest_path"],
        "activated_at": activated_at,
        "source_gpx": recording["source_path"],
        "active_completed_track_gpx": str(active_gpx),
        "outputs_dir": str(outputs_dir),
        "boundary": _boundary(),
        "mutation": _mutation(),
    }
    _write_json(active_dir / "active_completed_trip_recording.json", active_record)
    _write_json(inbox_dir / "latest_completed_trip_recording.json", active_record)

    files = build_capability_artifacts(
        case_id=f"{CASE_ID}.{recording_id}",
        completed_track_gpx=active_gpx,
        checkpoint_definitions_path=CHECKPOINT_DEFINITIONS_PATH,
        route_family=ROUTE_FAMILY,
        output_dir=outputs_dir,
        route_time_entries_path=ROUTE_TIME_ENTRIES_PATH,
        root=root,
    )
    reaction_simulation_path = outputs_dir / "scout_reaction_simulation.json"
    reaction_simulation = build_scout_reaction_simulation_from_gpx(
        active_gpx,
        scenario_id=recording_id,
        case_id=CASE_ID,
        output_path=reaction_simulation_path,
        root=root,
    )
    completed_trip_track = build_completed_trip_track_projection(
        active_gpx,
        recording=_public_recording(recording),
        source_path=recording["source_path"],
    )
    capability = summarize_capability_artifacts(
        timeline_path=Path(files.timeline_path),
        capsule_path=Path(files.capsule_path),
        root=root,
    )
    active_record["capability_timeline"] = capability
    active_record["scout_reaction_simulation"] = reaction_simulation
    active_record["completed_trip_track"] = completed_trip_track
    _write_json(active_dir / "active_completed_trip_recording.json", active_record)
    _write_json(inbox_dir / "latest_completed_trip_recording.json", active_record)
    return {
        "artifact_kind": "completed_trip_recording_post_analysis_result",
        "case_id": CASE_ID,
        "recording": _public_recording(recording),
        "capability_timeline": capability,
        "scout_reaction_simulation": reaction_simulation,
        "completed_trip_track": completed_trip_track,
        "paths": {
            "active_completed_track_gpx": str(active_gpx),
            "active_recording_record": str(active_dir / "active_completed_trip_recording.json"),
            "recording_set_manifest": catalog["recording_set_manifest_path"],
            "outputs_dir": str(outputs_dir),
            "capability_timeline": files.timeline_path,
            "capability_capsule": files.capsule_path,
            "capability_segments_csv": files.csv_summary_path,
            "scout_reaction_simulation": str(reaction_simulation_path),
        },
        "boundary": _boundary(),
        "mutation": _mutation(),
    }


def load_active_completed_trip_recording_projection(
    *,
    data_root: Path,
    root: Path = ROOT,
) -> dict[str, Any] | None:
    active_path = (
        data_root
        / ACTIVE_RELATIVE_DIR
        / "active_completed_trip_recording.json"
    )
    if not active_path.exists():
        return None
    active = _load_json(active_path)
    outputs_dir = Path(active.get("outputs_dir", ""))
    timeline_path = outputs_dir / "capability_timeline.json"
    capsule_path = outputs_dir / "capability_capsule.json"
    if timeline_path.exists() and capsule_path.exists():
        active["capability_timeline"] = summarize_capability_artifacts(
            timeline_path=timeline_path,
            capsule_path=capsule_path,
            root=root,
        )
    simulation_path = outputs_dir / "scout_reaction_simulation.json"
    if simulation_path.exists():
        active["scout_reaction_simulation"] = _load_json(simulation_path)
    if active.get("active_completed_track_gpx") and not active.get("completed_trip_track"):
        active_gpx = Path(active["active_completed_track_gpx"])
        if active_gpx.exists() and active.get("recording"):
            active["completed_trip_track"] = build_completed_trip_track_projection(
                active_gpx,
                recording=active["recording"],
                source_path=active.get("source_gpx") or active["recording"].get("source_path"),
            )
    return active


def build_completed_trip_track_projection(
    gpx_path: Path,
    *,
    recording: dict[str, Any],
    source_path: str | None,
    max_display_points: int = 8000,
) -> dict[str, Any]:
    route = load_gpx_route(gpx_path)
    raw_segments = _gpx_coordinate_segments(gpx_path)
    coordinate_segments = _thin_coordinate_segments(
        raw_segments,
        max_display_points=max_display_points,
    )
    display_point_count = sum(len(segment) for segment in coordinate_segments)
    coordinates = [
        coordinate
        for segment in coordinate_segments
        for coordinate in segment
    ]
    bounds = (
        {
            "south": min(point.lat for point in route.points),
            "north": max(point.lat for point in route.points),
            "west": min(point.lon for point in route.points),
            "east": max(point.lon for point in route.points),
        }
        if route.points
        else None
    )
    return {
        "evidence_type": "completed_trip_track",
        "source_id": f"completed_trip_track.{recording.get('recording_id')}",
        "recording_id": recording.get("recording_id"),
        "filename": recording.get("filename"),
        "display_name": recording.get("display_name") or recording.get("filename"),
        "source_path": source_path or recording.get("source_path") or str(gpx_path),
        "active_completed_track_gpx": str(gpx_path),
        "point_count": len(route.points),
        "display_point_count": display_point_count,
        "trkseg_count": len(raw_segments),
        "distance_m": round(route.points[-1].progress_m, 2) if route.points else 0,
        "bounds": bounds,
        "display_geometry": {
            "geometry_kind": "completed_trip_track_display_geometry",
            "coordinate_segments": coordinate_segments,
            "coordinates": coordinates,
            "point_count": len(route.points),
            "display_point_count": display_point_count,
            "trkseg_count": len(raw_segments),
            "downsampled": display_point_count < len(route.points),
            "max_display_points": max_display_points,
            "preserves_trkseg_boundary": True,
        },
        "boundary": _boundary(),
    }


def _scan_recordings(
    *,
    data_root: Path,
    roots: list[Path],
    root: Path,
) -> list[dict[str, Any]]:
    recordings: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for source_root in roots:
        if not source_root.exists():
            continue
        for gpx_path in sorted(source_root.rglob("*.gpx")):
            resolved = gpx_path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            recordings.append(_recording_projection(gpx_path, data_root=data_root, root=root))
    recordings.sort(key=lambda item: (item.get("role") or "", item["source_path"]))
    return recordings


def _gpx_coordinate_segments(gpx_path: Path) -> list[list[dict[str, float]]]:
    doc = ET.parse(gpx_path)
    root = doc.getroot()
    namespace = _namespace(root)
    segments: list[list[dict[str, float]]] = []
    for trkseg in root.findall(".//g:trkseg", namespace):
        segment: list[dict[str, float]] = []
        for trkpt in trkseg.findall("g:trkpt", namespace):
            segment.append(
                {
                    "lat": float(trkpt.attrib["lat"]),
                    "lon": float(trkpt.attrib["lon"]),
                }
            )
        if len(segment) >= 2:
            segments.append(segment)
    if segments:
        return segments
    route = load_gpx_route(gpx_path)
    return [
        [
            {"lat": point.lat, "lon": point.lon}
            for point in route.points
        ]
    ]


def _thin_coordinate_segments(
    segments: list[list[dict[str, float]]],
    *,
    max_display_points: int,
) -> list[list[dict[str, float]]]:
    total = sum(len(segment) for segment in segments)
    if total <= max_display_points or max_display_points <= 0:
        return segments
    stride = max(1, (total + max_display_points - 1) // max_display_points)
    thinned: list[list[dict[str, float]]] = []
    for segment in segments:
        if len(segment) <= 2:
            thinned.append(segment)
            continue
        reduced = [segment[0]]
        reduced.extend(segment[index] for index in range(stride, len(segment) - 1, stride))
        if reduced[-1] != segment[-1]:
            reduced.append(segment[-1])
        if len(reduced) >= 2:
            thinned.append(reduced)
    return thinned


def _recording_projection(path: Path, *, data_root: Path, root: Path) -> dict[str, Any]:
    rel_to_data_root = _relpath_or_abs(path, data_root)
    recording_id = _recording_id(path, data_root=data_root)
    base: dict[str, Any] = {
        "evidence_type": "completed_trip_recording",
        "recording_id": recording_id,
        "source_id": recording_id,
        "source_path": rel_to_data_root,
        "absolute_path": str(path),
        "filename": path.name,
        "role": _recording_role(path),
        "source_device": _source_device_from_path(path),
        "participant_id": _participant_id_from_path(path),
        "sha256": sha256_file(path),
        "loadable": False,
        "quality_flags": [],
        "boundary": _boundary(),
    }
    try:
        route = load_gpx_route(path)
        metadata = _gpx_metadata(path)
        elevations = [point.elevation_m for point in route.points if point.elevation_m is not None]
        base.update(
            {
                "loadable": True,
                "display_name": metadata.get("name") or path.stem,
                "description": metadata.get("desc") or "",
                "point_count": len(route.points),
                "distance_m": round(route.points[-1].progress_m, 2),
                "started_at": route.points[0].timestamp,
                "ended_at": route.points[-1].timestamp,
                "bbox_wgs84": {
                    "min_lat": min(point.lat for point in route.points),
                    "min_lon": min(point.lon for point in route.points),
                    "max_lat": max(point.lat for point in route.points),
                    "max_lon": max(point.lon for point in route.points),
                },
                "elevation_min_m": round(min(elevations), 2) if elevations else None,
                "elevation_max_m": round(max(elevations), 2) if elevations else None,
                "trk_count": metadata.get("trk_count", 0),
                "trkseg_count": metadata.get("trkseg_count", 0),
                "waypoint_count": metadata.get("waypoint_count", 0),
                "scout_note_waypoint_count": metadata.get("scout_note_waypoint_count", 0),
            }
        )
        if not route.points[0].timestamp or not route.points[-1].timestamp:
            base["quality_flags"].append("missing_track_time")
    except Exception as exc:  # list invalid GPX instead of hiding it from admin.
        base["display_name"] = path.stem
        base["parse_error"] = str(exc)
        base["quality_flags"].append("parse_error")
    return base


def _recording_set_manifest(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "completed_trip_recording_set_manifest",
        "artifact_version": "completed_trip_recording_set_manifest.v1",
        "case_id": catalog["case_id"],
        "route_family": catalog["route_family"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "recording_count": catalog["recording_count"],
        "recordings": [_public_recording(recording) for recording in catalog["recordings"]],
        "boundary": _boundary(),
    }


def _find_recording(catalog: dict[str, Any], recording_id: str) -> dict[str, Any]:
    for recording in catalog.get("recordings", []):
        if recording.get("recording_id") == recording_id:
            return recording
    raise KeyError(recording_id)


def _public_recording(recording: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in recording.items()
        if key not in {"absolute_path", "parse_error"}
    }


def _gpx_metadata(path: Path) -> dict[str, Any]:
    doc = ET.parse(path)
    root = doc.getroot()
    namespace = _namespace(root)
    waypoints = root.findall("g:wpt", namespace)
    return {
        "name": root.findtext("g:metadata/g:name", namespaces=namespace)
        or root.findtext("g:trk/g:name", namespaces=namespace),
        "desc": root.findtext("g:metadata/g:desc", namespaces=namespace)
        or root.findtext("g:trk/g:desc", namespaces=namespace),
        "trk_count": len(root.findall("g:trk", namespace)),
        "trkseg_count": len(root.findall(".//g:trkseg", namespace)),
        "waypoint_count": len(waypoints),
        "scout_note_waypoint_count": sum(
            1 for waypoint in waypoints if _has_scout_note(waypoint, namespace)
        ),
    }


def _has_scout_note(waypoint: ET.Element, namespace: dict[str, str]) -> bool:
    extension = waypoint.find("g:extensions/g:scout_note", namespace)
    if extension is not None and extension.text:
        return True
    comment = waypoint.findtext("g:cmt", namespaces=namespace)
    return bool(comment and comment.startswith(NOTE_PREFIX))


def _namespace(root: ET.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": "http://www.topografix.com/GPX/1/1"}


def _recording_id(path: Path, *, data_root: Path) -> str:
    rel = _relpath_or_abs(path, data_root)
    stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(rel).stem).strip("_").lower()
    if not stem:
        stem = "completed_trip_gpx"
    digest = sha256_file(path)[:10]
    return f"{stem}.{digest}"


def _recording_role(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "participants" in parts or "teammates" in parts:
        return "teammate_context"
    if "scout_runtime" in parts or "runtime" in parts:
        return "scout_runtime_primary"
    if "backup" in parts:
        return "self_backup"
    return "primary_self"


def _source_device_from_path(path: Path) -> str:
    lower = " ".join(part.lower() for part in path.parts)
    if "watch" in lower:
        return "watch"
    if "phone" in lower or "iphone" in lower:
        return "phone"
    if "scout" in lower:
        return "scout"
    return "unknown"


def _participant_id_from_path(path: Path) -> str:
    parts = list(path.parts)
    for marker in ("participants", "teammates", "primary_user"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts):
                return parts[index + 1]
            return marker
    return "primary_user"


def _boundary() -> dict[str, bool]:
    return {
        "fixture_only": False,
        "post_analysis_only": True,
        "recording_set_storage_allows_multiple_gpx": True,
        "active_view_single_subject": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
        "operator_trigger_required": True,
    }


def _mutation() -> dict[str, bool]:
    return {
        "active_completed_trip_inbox_written": True,
        "recording_set_manifest_written": True,
        "post_analysis_artifacts_written": True,
        "runtime_mutated": False,
        "phase1_runtime_mutated": False,
        "safety_api_called": False,
        "brain_fact_written": False,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relpath_or_abs(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
