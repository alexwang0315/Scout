from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from geo_utils import haversine_m
from route_matching import RoutePoint, load_gpx_route


NOTE_PREFIX = "SCOUT_NOTE_JSON:"


def build_scout_reaction_simulation_from_gpx(
    gpx_path: Path,
    *,
    scenario_id: str,
    case_id: str,
    output_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    route = load_gpx_route(gpx_path)
    waypoint_notes = _load_waypoint_notes(gpx_path)
    events: list[dict[str, Any]] = []
    for note_index, note in enumerate(waypoint_notes, start=1):
        timestamp = note.get("timestamp") or _nearest_track_timestamp(route.points, note)
        records = note.get("reaction_records") or []
        for record_index, record in enumerate(records, start=1):
            event = _event_from_reaction_record(
                record,
                note=note,
                scenario_id=scenario_id,
                case_id=case_id,
                sequence=len(events),
                note_index=note_index,
                record_index=record_index,
                timestamp=timestamp,
            )
            events.append(event)

    artifact = {
        "artifact_kind": "completed_trip_scout_reaction_replay",
        "artifact_version": "scout_reaction_replay.v1",
        "case_id": case_id,
        "scenario_id": scenario_id,
        "source_gpx": _relpath_or_abs(gpx_path, root) if root else str(gpx_path),
        "waypoint_note_count": len(waypoint_notes),
        "reaction_record_count": sum(len(note.get("reaction_records") or []) for note in waypoint_notes),
        "event_count": len(events),
        "waypoint_notes": waypoint_notes,
        "events": events,
        "boundary": _boundary(),
    }
    if output_path is not None:
        _write_json(output_path, artifact)
    return artifact


def _load_waypoint_notes(gpx_path: Path) -> list[dict[str, Any]]:
    root = ET.parse(gpx_path).getroot()
    namespace = _namespace(root)
    waypoints = root.findall("g:wpt", namespace)
    notes: list[dict[str, Any]] = []
    for index, waypoint in enumerate(waypoints, start=1):
        note_payload = _scout_note_payload(waypoint, namespace)
        if not note_payload:
            continue
        note_payload.setdefault("waypoint_index", index)
        note_payload.setdefault("waypoint_name", _child_text(waypoint, namespace, "name"))
        note_payload.setdefault("waypoint_type", _child_text(waypoint, namespace, "type"))
        note_payload["lat"] = float(waypoint.attrib["lat"])
        note_payload["lon"] = float(waypoint.attrib["lon"])
        waypoint_time = _child_text(waypoint, namespace, "time")
        if waypoint_time:
            note_payload["timestamp"] = waypoint_time
        notes.append(note_payload)
    return notes


def _scout_note_payload(
    waypoint: ET.Element,
    namespace: dict[str, str],
) -> dict[str, Any] | None:
    extension = waypoint.find("g:extensions/g:scout_note", namespace)
    if extension is not None and extension.text:
        return json.loads(extension.text)
    comment = _child_text(waypoint, namespace, "cmt")
    if comment and comment.startswith(NOTE_PREFIX):
        return json.loads(comment[len(NOTE_PREFIX) :])
    return None


def _event_from_reaction_record(
    record: dict[str, Any],
    *,
    note: dict[str, Any],
    scenario_id: str,
    case_id: str,
    sequence: int,
    note_index: int,
    record_index: int,
    timestamp: str | None,
) -> dict[str, Any]:
    event_kind = record["event_kind"]
    event_id = f"{scenario_id}.note{note_index:03d}.record{record_index:02d}.{event_kind}"
    payload = dict(record.get("payload") or {})
    payload.update(
        {
            "scenario_id": scenario_id,
            "waypoint_note_id": note.get("note_id"),
            "waypoint_name": note.get("waypoint_name"),
            "waypoint_type": note.get("waypoint_type"),
            "lat": note.get("lat"),
            "lon": note.get("lon"),
            "replayed_from_waypoint_note": True,
            "runtime_safety_truth": False,
        }
    )
    return {
        "evidence_type": "completed_trip_scout_reaction_record",
        "source_id": event_id,
        "event_id": event_id,
        "session_id": f"completed-trip-scenario.{scenario_id}",
        "mission_id": case_id,
        "timestamp": timestamp or "",
        "sequence": sequence,
        "kind": event_kind,
        "source": "completed_trip_gpx_waypoint_note",
        "phase": record.get("phase", "phase35"),
        "severity": record.get("severity", "info"),
        "subject_ref": note.get("note_id") or note.get("waypoint_name"),
        "scenario_id": scenario_id,
        "waypoint_note_id": note.get("note_id"),
        "waypoint_name": note.get("waypoint_name"),
        "waypoint_type": note.get("waypoint_type"),
        "lat": note.get("lat"),
        "lon": note.get("lon"),
        "correlation_refs": [
            scenario_id,
            note.get("waypoint_name") or "",
            *(record.get("correlation_refs") or []),
        ],
        "summary": record.get("summary") or note.get("summary") or event_kind,
        "payload": payload,
    }


def _nearest_track_timestamp(points: list[RoutePoint], note: dict[str, Any]) -> str | None:
    if not points:
        return None
    lat = float(note["lat"])
    lon = float(note["lon"])
    best = min(points, key=lambda point: haversine_m(lat, lon, point.lat, point.lon))
    return best.timestamp


def _namespace(root: ET.Element) -> dict[str, str]:
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": "http://www.topografix.com/GPX/1/1"}


def _child_text(
    node: ET.Element,
    namespace: dict[str, str],
    name: str,
) -> str | None:
    child = node.find(f"g:{name}", namespace)
    if child is None or child.text is None:
        return None
    return child.text


def _boundary() -> dict[str, bool]:
    return {
        "replay_only": True,
        "post_analysis_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
        "safety_result_replayed_from_note": True,
        "skill_execution_allowed": False,
        "skill_result_replayed_from_note": True,
        "pydantic_ai_model_called": False,
        "pydantic_ai_prompt_replayed_from_note": True,
        "outbound_message_sent": False,
        "brain_fact_written": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relpath_or_abs(path: Path, root: Path | None) -> str:
    if root is None:
        return str(path)
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
