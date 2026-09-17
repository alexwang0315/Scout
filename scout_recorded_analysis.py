"""Versioned Recorded observation sets and Golden / Planned / Recorded review.

A selected set becomes the analysis route without replacing the original
Golden, Planned bundle, raw recordings, or any runtime mission. Member/device
tracks remain separate; only explicitly selected primary files form the axis.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import uuid
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from post_analysis_capability import build_capability_timeline
from post_analysis_capability_models import RestDetectionPolicy
from post_analysis_completed_trip_recordings import list_completed_trip_recordings
from post_analysis_rest_detection import detect_rest_intervals
from post_analysis_route_slicing import CapabilityCheckpoint, CapabilitySegmentDefinition
from route_matching import GpxRoute, RoutePoint
from scout_planned_analysis_inputs import digest, distance_m, parse_time, safe_path
from scout_planned_route_models import PlannedRouteConflict

STORE_REF = "outputs/recorded_analysis"
SCHEMA = "recorded-analysis.v1"
VERSION_RE = re.compile(r"recorded\.[a-f0-9]{24}")
GPX_NS = "http://www.topografix.com/GPX/1/1"
BOUNDARY = {
    "candidate_only": True, "runtime_safety_truth": False,
    "post_analysis_only": True, "departure_approval_granted": False,
    "recorded_track": True, "runtime_mutated": False,
}
TIME_ROLE = "device_recorded_time"


class RecordedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str = Field(min_length=1)
    expected_sha256: str | None = None
    member_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    role: Literal["primary", "backup", "member_context"] = "primary"
    observation_kind: Literal["device_observation", "historical_recording", "fixture_replay"]
    start_point_index: int = Field(default=0, ge=0)
    end_point_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_point_index is not None and self.end_point_index < self.start_point_index:
            raise ValueError("The end point must follow the start point.")
        return self


class RecordedCampConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str = Field(min_length=1)
    start_point_index: int = Field(ge=0)
    end_point_index: int = Field(gt=0)
    observer_alias: str = Field(min_length=1)
    explicit_confirmation: Literal[True]
    note: str = ""

    @model_validator(mode="after")
    def positive_interval(self):
        if self.end_point_index <= self.start_point_index:
            raise ValueError("A camp confirmation requires a positive recorded point interval.")
        return self


class RecordedSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    recordings: list[RecordedInput] = Field(min_length=1)
    primary_member_id: str = Field(min_length=1)
    golden_source_ref: str | None = None
    planned_version_id: str | None = None
    timezone: str = "Asia/Taipei"
    idempotency_key: str | None = Field(default=None, min_length=1)
    label: str = "Recorded review"
    checkpoint_match_radius_m: float = Field(default=50, gt=0, le=500)
    max_sample_gap_seconds: int = Field(default=900, gt=0)
    max_spatial_step_m: float = Field(default=500, gt=0)
    camp_minimum_seconds: int = Field(default=14400, ge=3600)
    camp_confirmations: list[RecordedCampConfirmation] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_members(self):
        ZoneInfo(self.timezone)
        primaries = [r for r in self.recordings if r.role == "primary"]
        if not primaries or any(r.member_id != self.primary_member_id for r in primaries):
            raise ValueError("Primary recordings must belong to the selected primary member.")
        refs = [r.source_ref for r in self.recordings]
        if len(set(refs)) != len(refs):
            raise ValueError("A source file can appear only once; use a single explicit point range.")
        if len({r.observation_kind for r in primaries}) != 1:
            raise ValueError("Fixture, historical and personal observations cannot mix on one primary axis.")
        return self


def _bytes(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bytes(root: Path, ref: str) -> bytes:
    path = safe_path(root, ref)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PlannedRouteConflict("recorded_artifact_missing", f"Recorded artifact is unavailable: {ref}") from exc


def _read(root: Path, ref: str) -> Any:
    raw = _read_bytes(root, ref)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise PlannedRouteConflict("invalid_recorded_artifact", f"Recorded artifact is not valid JSON: {ref}") from exc


def _project(root: Path) -> tuple[Path, str]:
    root = Path(root).resolve()
    value = _read(root, "project.json")
    project_id = str(value.get("project_id") or value.get("id") or "")
    if not project_id:
        raise PlannedRouteConflict("recorded_project_missing", "Recorded sets require an identified workspace.")
    return root, project_id


def _write_immutable(root: Path, ref: str, raw: bytes) -> None:
    path = safe_path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise PlannedRouteConflict("recorded_output_conflict", f"Immutable Recorded output changed: {ref}")
        return
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic(root: Path, ref: str, value: dict) -> None:
    path = safe_path(root, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def _writer(root: Path):
    path = safe_path(root, STORE_REF + "/writer.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _version_ref(version_id: str) -> str:
    if not isinstance(version_id, str) or not VERSION_RE.fullmatch(version_id):
        raise PlannedRouteConflict("invalid_recorded_version", "Invalid Recorded version identifier.")
    return f"{STORE_REF}/versions/{version_id}"


def _signed(value: dict, field: str) -> dict:
    return {**value, field: digest(value)}


def _verify(value: dict, field: str) -> None:
    if not isinstance(value, dict) or value.get(field) != digest({k: v for k, v in value.items() if k != field}):
        raise PlannedRouteConflict("recorded_signature_mismatch", "Recorded artifact content no longer matches its signature.")


def _parse_recording(raw: bytes, ref: str, *, require_observation: bool = True) -> list[list[dict]]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise PlannedRouteConflict("invalid_recorded_xml", "Recorded GPX must not declare XML entities.")
    try:
        tree = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PlannedRouteConflict("invalid_recorded_xml", "Recorded input must be well-formed GPX.") from exc
    if tree.tag.rsplit("}", 1)[-1] != "gpx":
        raise PlannedRouteConflict("invalid_recorded_xml", "Recorded input is not a GPX document.")
    if require_observation:
        for node in tree.iter():
            tag = node.tag.lower()
            local = tag.rsplit("}", 1)[-1]
            attributes = {k.rsplit("}", 1)[-1].lower(): str(v).lower() for k, v in node.attrib.items()}
            values = list(attributes.values())
            if (
                "planned-route" in tag
                or "planned" in attributes.get("creator", "")
                or any(v in {"planned", "planned_estimate", "synthetic", "synthetic_time", "planned_gpx_reference", "planned_gpx", "planned_candidate", "synthetic_recording"} for v in values)
                or local in {"time_role", "source_role", "role", "provenance"} and
                (node.text or "").strip().lower() in {"planned", "planned_estimate", "synthetic"}
                or local in {"synthetic", "synthetic_timestamp", "synthetic_time"} and
                ((node.text or "").strip().lower() not in {"false", "0"} or "true" in values)
            ):
                raise PlannedRouteConflict("planned_is_not_recorded", "Planned or synthetic GPX cannot become an actual Recorded observation.")
    parts, source_index = [], 0
    for segment_index, segment in enumerate(n for n in tree.iter() if n.tag.rsplit("}", 1)[-1] == "trkseg"):
        points = []
        previous_stamp = None
        for node in segment:
            if node.tag.rsplit("}", 1)[-1] != "trkpt":
                continue
            try:
                lat, lon = float(node.attrib["lat"]), float(node.attrib["lon"])
                values = {n.tag.rsplit("}", 1)[-1]: n.text for n in node}
                ele = float(values["ele"]) if values.get("ele") else None
                stamp = parse_time(values.get("time"))
                if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
                    raise ValueError("coordinate")
                if ele is not None and not math.isfinite(ele):
                    raise ValueError("elevation")
                if values.get("time") and stamp is None:
                    raise ValueError("timestamp requires a timezone")
                if stamp is not None and previous_stamp is not None and stamp < previous_stamp:
                    raise ValueError("timestamps run backwards")
            except (ValueError, KeyError, TypeError) as exc:
                raise PlannedRouteConflict("invalid_recorded_point", f"Invalid coordinate or observation time in {ref}.") from exc
            if stamp is not None:
                previous_stamp = stamp
            points.append({
                "lat": lat, "lon": lon, "ele": ele, "timestamp": values.get("time"),
                "source_ref": ref, "source_point_index": source_index,
                "source_segment_index": segment_index, "time_role": TIME_ROLE,
            })
            source_index += 1
        if points:
            parts.append(points)
    all_points = [p for part in parts for p in part]
    if len(all_points) < 2 or require_observation and sum(parse_time(p["timestamp"]) is not None for p in all_points) < 2:
        raise PlannedRouteConflict("recorded_observation_time_required", "Recorded GPX requires at least two actual timezone-aware track-point times.")
    return parts


def list_recorded_sources(project_root: Path) -> dict:
    """Use the established CompletedTripRecordingSet catalog; no broad scan."""
    root, project_id = _project(project_root)
    value = list_completed_trip_recordings(data_root=root, project_root=root, project_id=project_id)
    for row in value["recordings"]:
        try:
            path = Path(row["absolute_path"])
            ref = path.relative_to(root).as_posix()
            _parse_recording(safe_path(root, ref).read_bytes(), ref)
            row["recorded_analysis_eligible"] = True
        except (ValueError, OSError, PlannedRouteConflict) as exc:
            row["recorded_analysis_eligible"] = False
            row["recorded_analysis_reason"] = str(exc)
        row.pop("absolute_path", None)
    value["personal_observations_available"] = any(r.get("recorded_analysis_eligible") for r in value["recordings"])
    value.update(BOUNDARY)
    return value


def _source_status(root: Path, hashes: dict) -> dict:
    changed, missing = [], []
    for ref, expected in hashes.items():
        path = safe_path(root, ref)
        if not path.is_file():
            missing.append(ref)
        elif _sha(path.read_bytes()) != expected:
            changed.append(ref)
    return {"status": "current" if not changed and not missing else "stale", "changed_refs": changed, "missing_refs": missing}


def _route_points(points: list[dict]) -> list[RoutePoint]:
    progress, result = 0.0, []
    for i, p in enumerate(points):
        if i:
            progress += distance_m(points[i - 1], p)
        result.append(RoutePoint(lat=p["lat"], lon=p["lon"], elevation_m=p.get("ele"),
                                 timestamp=p.get("timestamp"), progress_m=progress))
    return result


def _parts_for_axis(recordings: list[dict], request: RecordedSetRequest) -> tuple[list[dict], list[dict]]:
    primary_parts = []
    for record in recordings:
        if record["role"] != "primary":
            continue
        for part in record["parts"]:
            selected = [p for p in part if record["start_point_index"] <= p["source_point_index"] <= record["end_point_index"]]
            if selected:
                primary_parts.append((record, selected))
    primary_parts.sort(key=lambda item: next((parse_time(p["timestamp"]) for p in item[1] if p["timestamp"]), datetime.max.replace(tzinfo=timezone.utc)))
    axis, gaps, progress, previous_end = [], [], 0.0, None
    for record, source_part in primary_parts:
        start = next((parse_time(p["timestamp"]) for p in source_part if p["timestamp"]), None)
        end = next((parse_time(p["timestamp"]) for p in reversed(source_part) if p["timestamp"]), None)
        if previous_end is not None and start is not None and start < previous_end:
            raise PlannedRouteConflict("overlapping_primary_recordings", "Primary recording intervals overlap; classify the redundant device as backup or trim the selected ranges.")
        previous_end = end or previous_end
        for local_index, point in enumerate(source_part):
            point = copy.deepcopy(point)
            point.update({"point_index": len(axis), "member_id": record["member_id"],
                          "device_id": record["device_id"], "recording_id": record["recording_id"],
                          "observation_kind": record["observation_kind"], "route_role": "recorded",
                          "break_before": bool(axis and local_index == 0)})
            if axis and local_index:
                prev_time, this_time = parse_time(axis[-1]["timestamp"]), parse_time(point["timestamp"])
                if distance_m(axis[-1], point) > request.max_spatial_step_m:
                    point["break_before"] = True
                    reason = "recorded_geometry_gap"
                elif prev_time is None or this_time is None:
                    point["break_before"] = True
                    reason = "missing_observation_time"
                elif (this_time - prev_time).total_seconds() > request.max_sample_gap_seconds:
                    point["break_before"] = True
                    reason = "sampling_time_gap"
                else:
                    reason = None
            else:
                reason = "source_file_or_track_segment_boundary"
            if axis and point["break_before"]:
                a, b = parse_time(axis[-1]["timestamp"]), parse_time(point["timestamp"])
                gaps.append({"code": reason, "from_point_index": len(axis) - 1, "to_point_index": len(axis),
                             "separation_m": round(distance_m(axis[-1], point), 3),
                             "unobserved_duration_seconds": (b - a).total_seconds() if a and b else None,
                             "source_refs": list(dict.fromkeys([axis[-1]["source_ref"], point["source_ref"]])),
                             "connector_created": False, "moving_or_camp_inferred": False})
            elif axis:
                progress += distance_m(axis[-1], point)
            point["route_order_m"] = round(progress, 6)
            axis.append(point)
    if len(axis) < 2:
        raise PlannedRouteConflict("recorded_primary_axis_empty", "The primary member requires at least two selected recorded points.")
    return axis, gaps


def _chunks(axis: list[dict]) -> list[list[dict]]:
    result = []
    for point in axis:
        if not result or point.get("break_before"):
            result.append([])
        result[-1].append(point)
    return result


def _metrics(axis: list[dict], request: RecordedSetRequest) -> tuple[dict, list[dict]]:
    rests, intervals, sampled = [], [], 0.0
    policy = RestDetectionPolicy(max_sample_gap_s=request.max_sample_gap_seconds)
    for chunk in _chunks(axis):
        detected = detect_rest_intervals(_route_points(chunk), policy=policy, source_ref=chunk[0]["source_ref"])
        for rest in detected:
            start, end = chunk[rest.start_index], chunk[rest.end_index]
            row = rest.model_dump(mode="json")
            row.update({"event_id": f"recorded.rest.{start['point_index']:06d}",
                        "kind": "camp" if rest.duration_s >= request.camp_minimum_seconds else "source_rest",
                        "classification": "inferred_camp_candidate" if rest.duration_s >= request.camp_minimum_seconds else "detected_rest",
                        "camp_confirmed": False,
                        "start_point_index": start["point_index"], "end_point_index": end["point_index"],
                        "point_index": start["point_index"], "arrival_at": start["timestamp"],
                        "departure_at": end["timestamp"], "duration_minutes": rest.duration_s / 60,
                        "time_role": TIME_ROLE, "observation_kind": start["observation_kind"]})
            rests.append(row)
        for a, b in zip(chunk, chunk[1:]):
            t1, t2 = parse_time(a["timestamp"]), parse_time(b["timestamp"])
            seconds = (t2 - t1).total_seconds() if t1 and t2 else None
            if seconds is not None:
                sampled += max(0, seconds)
            rest = next((r for r in rests if r["start_point_index"] <= a["point_index"] and r["end_point_index"] >= b["point_index"]), None)
            intervals.append({"start_point_index": a["point_index"], "end_point_index": b["point_index"],
                              "seconds": seconds, "kind": rest["kind"] if rest else "move",
                              "distance_m": round(distance_m(a, b), 3), "time_role": TIME_ROLE})
    stamps = [parse_time(p["timestamp"]) for p in axis if parse_time(p["timestamp"])]
    elapsed = (max(stamps) - min(stamps)).total_seconds() if stamps else None
    rest_seconds = sum(r["duration_s"] for r in rests)
    camp_seconds = sum(r["duration_s"] for r in rests if r["kind"] == "camp")
    return {
        "distance_m": axis[-1]["route_order_m"], "elapsed_seconds": elapsed,
        "observed_interval_seconds": sampled, "moving_seconds": max(0, sampled - rest_seconds),
        "rest_seconds": rest_seconds, "camp_candidate_seconds": camp_seconds,
        "camp_confirmed_seconds": None, "unobserved_seconds": max(0, elapsed - sampled) if elapsed is not None else None,
        "started_at": stamps[0].isoformat() if stamps else None, "ended_at": stamps[-1].isoformat() if stamps else None,
        "missing_timestamp_count": sum(not p.get("timestamp") for p in axis),
        "time_role": TIME_ROLE, "inference_policy": policy.model_dump(mode="json"),
        "camp_policy": {"minimum_seconds": request.camp_minimum_seconds, "actual_intent_requires_human_confirmation": True},
        "intervals": intervals,
    }, rests


def _confirmed_camps(axis: list[dict], rests: list[dict], request: RecordedSetRequest) -> list[dict]:
    result = []
    index = {(point["source_ref"], point["source_point_index"]): point for point in axis}
    for confirmation in request.camp_confirmations:
        start = index.get((confirmation.source_ref, confirmation.start_point_index))
        end = index.get((confirmation.source_ref, confirmation.end_point_index))
        if not start or not end or start["point_index"] >= end["point_index"]:
            raise PlannedRouteConflict("recorded_camp_source_mismatch", "Camp confirmation must identify an ordered primary recording interval.")
        points = axis[start["point_index"]:end["point_index"] + 1]
        if any(p.get("break_before") for p in points[1:]):
            raise PlannedRouteConflict("recorded_camp_observation_gap", "A recording gap cannot be converted into observed camp time.")
        rest = next((r for r in rests if r["start_point_index"] <= start["point_index"]
                     and r["end_point_index"] >= end["point_index"]), None)
        if rest is None:
            raise PlannedRouteConflict("recorded_camp_stationarity_missing", "Confirmed camp time requires a continuous stationary recorded interval.")
        if any(start["point_index"] < r["end_point_index"] and end["point_index"] > r["start_point_index"] for r in result):
            raise PlannedRouteConflict("recorded_camp_overlap", "Camp confirmations may not double-count the same observed interval.")
        seconds = (parse_time(end["timestamp"]) - parse_time(start["timestamp"])).total_seconds()
        row = {
            **confirmation.model_dump(mode="json"),
            "confirmation_id": "camp." + digest(confirmation.model_dump(mode="json"))[:24],
            "kind": "camp", "classification": "operator_confirmed_recorded_camp", "camp_confirmed": True,
            "source_start_point_index": confirmation.start_point_index, "source_end_point_index": confirmation.end_point_index,
            "point_index": start["point_index"], "start_point_index": start["point_index"], "end_point_index": end["point_index"],
            "arrival_at": start["timestamp"], "departure_at": end["timestamp"],
            "duration_seconds": seconds, "duration_minutes": seconds / 60,
            "time_role": start["time_role"], "evidence_role": "operator_statement_bound_to_device_stationarity",
            "contained_rest_id": rest["event_id"], "included_in_rest_seconds": True, **BOUNDARY,
        }
        rest.setdefault("camp_confirmation_ids", []).append(row["confirmation_id"])
        result.append(row)
    return result


def _golden_ref(root: Path, project: dict, requested: str | None) -> str | None:
    if requested:
        safe_path(root, requested)
        return requested
    report_ref = project.get("gpx_speed_filter_report_ref", "outputs/gpx_speed_filter_report.json")
    path = safe_path(root, report_ref)
    if path.is_file():
        report = _read(root, report_ref)
        primary = report.get("primary") or {}
        ref = primary.get("output_path")
        if isinstance(ref, str):
            if not Path(ref).is_absolute():
                return ref
            # Existing portable filtered-GPX resolver validates project + SHA.
            from scout_planned_route import _filtered_gpx_ref
            return _filtered_gpx_ref(root, project["project_id"], primary)
    ref = project.get("golden_gpx_ref")
    return ref if isinstance(ref, str) else None


def _geo(axis: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"part_index": i, "source_role": "recorded",
                                           "start_point_index": c[0]["point_index"], "end_point_index": c[-1]["point_index"]},
         "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] + ([p["ele"]] if p.get("ele") is not None else []) for p in c]}}
        for i, c in enumerate(_chunks(axis)) if len(c) >= 2], **BOUNDARY}


def _recorded_gpx(axis: list[dict], project_id: str, kind: str) -> bytes:
    tree = ET.Element("gpx", {"xmlns": GPX_NS, "version": "1.1", "creator": "Scout Recorded Observation Set"})
    metadata = ET.SubElement(tree, "metadata")
    ET.SubElement(metadata, "name").text = project_id + " Recorded review"
    ET.SubElement(metadata, "desc").text = "Derived union of original recorded point occurrences; all device timestamps retained. Observation kind: " + kind
    for part in _chunks(axis):
        track = ET.SubElement(tree, "trk")
        ET.SubElement(track, "name").text = part[0]["recording_id"]
        segment = ET.SubElement(track, "trkseg")
        for point in part:
            node = ET.SubElement(segment, "trkpt", lat=str(point["lat"]), lon=str(point["lon"]))
            if point.get("ele") is not None:
                ET.SubElement(node, "ele").text = str(point["ele"])
            if point.get("timestamp"):
                ET.SubElement(node, "time").text = point["timestamp"]
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True)


def _fixture_time_roles(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("time_role") == TIME_ROLE:
            value["time_role"] = "fixture_replay_time"
        for item in value.values():
            _fixture_time_roles(item)
    elif isinstance(value, list):
        for item in value:
            _fixture_time_roles(item)


def _projection_matches(axis: list[dict], baseline: list[dict], radius_m: float) -> list[dict]:
    """Project onto nearby polyline edges, excluding every baseline gap."""
    cell = max(.0005, radius_m / 110000)
    grid: dict[tuple[int, int], list[tuple[dict, dict]]] = {}
    for a, b in zip(baseline, baseline[1:]):
        if b.get("break_before"):
            continue
        x1, x2 = sorted((int(math.floor(a["lon"] / cell)), int(math.floor(b["lon"] / cell))))
        y1, y2 = sorted((int(math.floor(a["lat"] / cell)), int(math.floor(b["lat"] / cell))))
        if (x2 - x1 + 1) * (y2 - y1 + 1) > 100000:
            continue
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                grid.setdefault((x, y), []).append((a, b))
    results = []
    for p in axis:
        x, y = int(math.floor(p["lon"] / cell)), int(math.floor(p["lat"] / cell))
        choices = []
        sx, sy = 111195 * math.cos(math.radians(p["lat"])), 111195
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                for a, b in grid.get((x + dx, y + dy), []):
                    ax, ay = (a["lon"] - p["lon"]) * sx, (a["lat"] - p["lat"]) * sy
                    bx, by = (b["lon"] - p["lon"]) * sx, (b["lat"] - p["lat"]) * sy
                    vx, vy = bx - ax, by - ay
                    q = min(1.0, max(0.0, -(ax * vx + ay * vy) / (vx * vx + vy * vy))) if vx or vy else 0.0
                    separation = math.hypot(ax + vx * q, ay + vy * q)
                    if separation <= radius_m:
                        progress = a["route_order_m"] + q * (b["route_order_m"] - a["route_order_m"])
                        choices.append((separation, progress, a["point_index"]))
        if choices:
            minimum = min(c[0] for c in choices)
            near = [c for c in choices if c[0] <= minimum + .05]
            # A loop may have several equally near baseline occurrences. Keep
            # every occurrence; never silently collapse them to the first visit.
            matches = sorted({round(c[1], 3): c[2] for c in near}.items())
            results.append({"point_index": p["point_index"], "matched": True,
                            "distance_m": round(minimum, 3), "baseline_occurrences": [{"progress_m": c[0], "edge_start_index": c[1]} for c in matches],
                            "ambiguous_visit": len(matches) > 1})
        else:
            results.append({"point_index": p["point_index"], "matched": False,
                            "distance_m": None, "minimum_distance_m": radius_m,
                            "baseline_occurrences": [], "ambiguous_visit": False})
    return results


def _runs(indices: list[int]) -> list[dict]:
    result = []
    for index in indices:
        if result and result[-1]["end_point_index"] == index - 1:
            result[-1]["end_point_index"] = index
        else:
            result.append({"start_point_index": index, "end_point_index": index})
    return result


def _baseline_comparison(axis: list[dict], stats: dict, baseline: dict, radius: float) -> dict:
    if not baseline:
        return {"status": "missing", "reason": "No version-bound comparison source was supplied."}
    base_axis = baseline["route_axis"]
    matches = _projection_matches(axis, base_axis, radius)
    previous = None
    reverse = []
    for match in matches:
        if not match["matched"] or match["ambiguous_visit"] or axis[match["point_index"]].get("break_before"):
            previous = None
            continue
        progress = match["baseline_occurrences"][0]["progress_m"]
        if previous is not None and previous - progress > radius:
            reverse.append(match["point_index"])
        previous = progress
    timed = baseline.get("metrics") or {}
    timing = {}
    for name in ("elapsed_seconds", "moving_seconds", "rest_seconds", "camp_candidate_seconds"):
        expected = timed.get(name)
        actual = stats.get(name)
        timing[name] = {"recorded": actual, "baseline": expected,
                        "difference": actual - expected if actual is not None and expected is not None else None}
    visits = []
    for cp in baseline.get("checkpoints", []):
        close = [p["point_index"] for p in axis if distance_m(p, cp) <= radius]
        for visit_number, span in enumerate(_runs(close), 1):
            a, b = axis[span["start_point_index"]], axis[span["end_point_index"]]
            visits.append({"baseline_checkpoint_id": cp.get("candidate_id") or cp.get("checkpoint_id"),
                           "label": cp.get("label") or cp.get("name"), "visit_number": visit_number,
                           **span, "arrival_at": a.get("timestamp"), "departure_at": b.get("timestamp"),
                           "source_ref": a["source_ref"], "time_role": TIME_ROLE})
    missing_visits = [c.get("candidate_id") or c.get("checkpoint_id") for c in baseline.get("checkpoints", [])
                      if not any(v["baseline_checkpoint_id"] == (c.get("candidate_id") or c.get("checkpoint_id")) for v in visits)]
    deviation_indices = [m["point_index"] for m in matches if not m["matched"]]
    return {
        "status": "compared", "source_binding": baseline["source_binding"],
        "baseline_time_role": baseline["time_role"], "recorded_time_role": TIME_ROLE,
        "geometry_policy": "ordered_point_occurrences_projected_to_gap_preserving_polyline.v1",
        "corridor_radius_m": radius, "matches": matches,
        "matched_point_count": len(matches) - len(deviation_indices), "deviation_point_count": len(deviation_indices),
        "deviations": _runs(deviation_indices), "reverse_progress_ranges": _runs(reverse),
        "turnback_detected": bool(reverse), "ambiguous_visit_count": sum(m["ambiguous_visit"] for m in matches),
        "checkpoint_visits": visits, "unreached_checkpoint_ids": missing_visits,
        "recorded_distance_m": stats["distance_m"], "baseline_distance_m": base_axis[-1]["route_order_m"],
        "distance_difference_m": stats["distance_m"] - base_axis[-1]["route_order_m"],
        "timing": timing, "camp_time_comparison": {
            "recorded_confirmed_seconds": stats.get("camp_confirmed_seconds"),
            "recorded_candidate_seconds": stats.get("camp_candidate_seconds"),
            "baseline_scheduled_or_detected_seconds": timed.get("camp_candidate_seconds"),
            "difference_seconds": stats["camp_confirmed_seconds"] - timed["camp_candidate_seconds"]
                if stats.get("camp_confirmed_seconds") is not None and timed.get("camp_candidate_seconds") is not None else None,
            "intent_inferred_for_unconfirmed_intervals": False,
        }, "baseline_gap_count": sum(p.get("break_before", False) for p in base_axis),
        "prior_geometry_mutated": False, **BOUNDARY,
    }


def _baseline_axis(parts: list[list[dict]]) -> list[dict]:
    axis, progress = [], 0.0
    for part in parts:
        for i, raw in enumerate(part):
            p = copy.deepcopy(raw)
            if axis and i:
                progress += distance_m(axis[-1], p)
            p.update({"point_index": len(axis), "route_order_m": progress, "break_before": bool(axis and i == 0)})
            axis.append(p)
    return axis


def _planned_metrics(itinerary: dict) -> dict:
    summary = itinerary.get("summary", {})
    days = itinerary.get("days", [])
    elapsed = summary.get("elapsed_minutes")
    if elapsed is None:
        starts = [parse_time(d.get("departure_at")) for d in days]
        ends = [parse_time(d.get("arrival_at")) for d in days]
        elapsed = (ends[-1] - starts[0]).total_seconds() / 60 if starts and ends and starts[0] and ends[-1] else None
    timeline = itinerary.get("timeline", [])
    known = [e for e in timeline if isinstance(e.get("duration_minutes"), (int, float))]
    moving = sum(e["duration_minutes"] for e in known if e.get("kind") == "move")
    rests = sum(e["duration_minutes"] for e in known if e.get("kind") in {"source_rest", "fixed_stop", "camp"})
    camp = sum(e["duration_minutes"] for e in known if e.get("kind") == "camp")
    return {"elapsed_seconds": elapsed * 60 if elapsed is not None else None,
            "moving_seconds": moving * 60 if timeline and not itinerary.get("unknowns") else None,
            "rest_seconds": rests * 60 if timeline else None, "camp_candidate_seconds": camp * 60 if timeline else None}


def _build_graph(axis: list[dict], rests: list[dict], gaps: list[dict], comparisons: dict, request: RecordedSetRequest, confirmed_camps: list[dict] | None = None) -> tuple[dict, dict]:
    needed = {0, len(axis) - 1}
    labels = {}
    for chunk in _chunks(axis):
        needed.update((chunk[0]["point_index"], chunk[-1]["point_index"]))
    for rest in rests:
        needed.update((rest["start_point_index"], rest["end_point_index"]))
        labels[rest["start_point_index"]] = "紮營候選" if rest["kind"] == "camp" else "實錄休息"
    for camp in confirmed_camps or []:
        needed.update((camp["start_point_index"], camp["end_point_index"]))
        labels[camp["start_point_index"]] = "已確認紮營"
    for comparison in comparisons.values():
        for visit in comparison.get("checkpoint_visits", []):
            needed.update((visit["start_point_index"], visit["end_point_index"]))
            labels.setdefault(visit["start_point_index"], visit["label"])
    zone = ZoneInfo(request.timezone)
    for a, b in zip(axis, axis[1:]):
        ta, tb = parse_time(a["timestamp"]), parse_time(b["timestamp"])
        if ta and tb and ta.astimezone(zone).date() != tb.astimezone(zone).date():
            needed.update((a["point_index"], b["point_index"]))
    nodes = []
    for index in sorted(needed):
        p = axis[index]
        nodes.append({"candidate_id": f"recorded.cp.{index:06d}", "checkpoint_id": f"recorded.cp.{index:06d}",
                      "point_index": index, "label": labels.get(index) or f"Recorded point {index}",
                      "lat": p["lat"], "lon": p["lon"], "ele": p.get("ele"), "route_distance_m": p["route_order_m"],
                      "source_role": "recorded", "arrival_at": p["timestamp"], "departure_at": p["timestamp"],
                      "time_role": TIME_ROLE, "source_refs": [p["source_ref"]], **BOUNDARY})
    edges = []
    for a, b in zip(nodes, nodes[1:]):
        points = axis[a["point_index"]:b["point_index"] + 1]
        if any(p.get("break_before") for p in points[1:]):
            continue
        t1, t2 = parse_time(points[0]["timestamp"]), parse_time(points[-1]["timestamp"])
        seconds = (t2 - t1).total_seconds() if t1 and t2 else None
        rest_seconds = None
        if t1 and t2:
            rest_seconds = 0.0
            for rest in rests:
                if rest["start_point_index"] < b["point_index"] and rest["end_point_index"] > a["point_index"]:
                    rest_seconds += max(0, (min(parse_time(rest["departure_at"]), t2)
                                            - max(parse_time(rest["arrival_at"]), t1)).total_seconds())
        elevations = all(p.get("ele") is not None for p in points)
        edge_id = f"recorded.seg.{len(edges):06d}"
        edges.append({"candidate_id": edge_id, "segment_id": edge_id,
                      "from_candidate_id": a["candidate_id"], "to_candidate_id": b["candidate_id"],
                      "start_point_index": a["point_index"], "end_point_index": b["point_index"],
                      "from_m": a["route_distance_m"], "to_m": b["route_distance_m"],
                      "distance_m": b["route_distance_m"] - a["route_distance_m"],
                      "elevation_gain_m": sum(max(0, q["ele"] - p["ele"]) for p, q in zip(points, points[1:])) if elevations else None,
                      "elevation_loss_m": sum(max(0, p["ele"] - q["ele"]) for p, q in zip(points, points[1:])) if elevations else None,
                      "eta_from": points[0]["timestamp"], "eta_to": points[-1]["timestamp"],
                      "expected_duration_minutes": seconds / 60 if seconds is not None else None,
                      "actual_duration_seconds": seconds, "actual_rest_seconds": rest_seconds,
                      "actual_moving_seconds": max(0, seconds - rest_seconds) if seconds is not None and rest_seconds is not None else None,
                      "lat": points[len(points) // 2]["lat"], "lon": points[len(points) // 2]["lon"],
                      "time_role": TIME_ROLE, "source_refs": list(dict.fromkeys(p["source_ref"] for p in points)), **BOUNDARY})
    day_rows: dict[str, dict] = {}
    for p in axis:
        stamp = parse_time(p["timestamp"])
        if stamp is None:
            continue
        day = stamp.astimezone(zone).date().isoformat()
        row = day_rows.setdefault(day, {"day_id": day, "mission_day_id": day, "date": day,
                                       "start_point_index": p["point_index"], "departure_at": p["timestamp"]})
        row.update({"end_point_index": p["point_index"], "arrival_at": p["timestamp"], "time_role": TIME_ROLE})
    graph = {"nodes": nodes, "edges": edges, "gaps": gaps, "topology_role": "recorded_observation_cp_edges",
             "reviewed_mission_graph": False, **BOUNDARY}
    itinerary = {"schema_version": "recordedItinerary.v1", "time_role": TIME_ROLE, "timezone": request.timezone,
                 "days": list(day_rows.values()), "timeline": rests, "unknowns": gaps,
                 "weather_evaluation_mode": "historical_at_observation_time", "forecast_requested": False, **BOUNDARY}
    return graph, itinerary


def save_recorded_version(project_root: Path, request: RecordedSetRequest | dict) -> dict:
    root, project_id = _project(project_root)
    request = RecordedSetRequest.model_validate(request)
    if request.project_id != project_id:
        raise PlannedRouteConflict("recorded_project_mismatch", "Recorded request belongs to another project.")
    with _writer(root):
        project = _read(root, "project.json")
        hashes, raw_sources, recordings = {}, {}, []
        for entry in request.recordings:
            path = safe_path(root, entry.source_ref)
            raw = path.read_bytes()
            sha = _sha(raw)
            if entry.expected_sha256 and entry.expected_sha256 != sha:
                raise PlannedRouteConflict("recorded_source_changed", "Recording source changed before import.")
            parts = _parse_recording(raw, entry.source_ref)
            count = sum(len(p) for p in parts)
            end = entry.end_point_index if entry.end_point_index is not None else count - 1
            if entry.start_point_index >= count or end >= count:
                raise PlannedRouteConflict("recorded_range_invalid", "Selected recorded point range exceeds the source file.")
            hashes[entry.source_ref], raw_sources[entry.source_ref] = sha, raw
            recordings.append({**entry.model_dump(mode="json"), "end_point_index": end, "sha256": sha,
                               "bytes": len(raw), "point_count": count, "parts": parts,
                               "recording_id": "recording." + digest({"source_ref": entry.source_ref, "sha256": sha})[:24]})
        axis, gaps = _parts_for_axis(recordings, request)
        metrics, rests = _metrics(axis, request)
        confirmed_camps = _confirmed_camps(axis, rests, request)
        if confirmed_camps:
            metrics["camp_confirmed_seconds"] = sum(event["duration_seconds"] for event in confirmed_camps)
        baselines = {}
        golden_ref = _golden_ref(root, project, request.golden_source_ref)
        if golden_ref:
            raw = safe_path(root, golden_ref).read_bytes()
            golden_parts = _parse_recording(raw, golden_ref, require_observation=False)
            golden_count = sum(len(part) for part in golden_parts)
            golden_axis, _ = _parts_for_axis([{
                "parts": golden_parts, "role": "primary", "start_point_index": 0, "end_point_index": golden_count - 1,
                "member_id": "historical_reference", "device_id": "unknown",
                "recording_id": "original_golden", "observation_kind": "historical_recording",
            }], request)
            golden_metrics, _ = _metrics(golden_axis, request)
            hashes[golden_ref], raw_sources[golden_ref] = _sha(raw), raw
            cps_path = safe_path(root, project.get("checkpoint_candidates_ref", "candidates/checkpoints.json"))
            cps = json.loads(cps_path.read_bytes()) if cps_path.is_file() else []
            if cps_path.is_file():
                hashes[cps_path.relative_to(root).as_posix()] = _sha(cps_path.read_bytes())
            if isinstance(cps, dict):
                cps = cps.get("checkpoints", [])
            hydrated = []
            for cp in cps:
                if not isinstance(cp, dict):
                    continue
                if isinstance(cp.get("lat"), (int, float)) and isinstance(cp.get("lon"), (int, float)):
                    hydrated.append(cp)
                    continue
                index = cp.get("route_point_index", cp.get("point_index"))
                if isinstance(index, int) and 0 <= index < len(golden_axis):
                    hydrated.append({**cp, "lat": golden_axis[index]["lat"], "lon": golden_axis[index]["lon"]})
            cps = hydrated
            baselines["golden"] = {"route_axis": golden_axis, "metrics": golden_metrics, "checkpoints": cps,
                                  "source_binding": {"source_ref": golden_ref, "sha256": _sha(raw), "role": "original_golden"},
                                  "time_role": "historical_source_observation"}
        if request.planned_version_id:
            from scout_planned_route_artifacts import get_planned_version
            planned = get_planned_version(root, request.planned_version_id)
            if planned["source_status"]["status"] != "current":
                raise PlannedRouteConflict("recorded_planned_source_stale", "Planned comparison must use a verified current bundle.")
            preview, manifest = planned["preview"], planned["manifest"]
            # The store constant is authoritative; no private reimplementation.
            from scout_planned_route_artifacts import STORE_REF as PLANNED_STORE
            manifest_ref = f"{PLANNED_STORE}/versions/{manifest['version_id']}/manifest.json"
            hashes[manifest_ref] = _sha(safe_path(root, manifest_ref).read_bytes())
            hashes.update(manifest.get("source_hashes", {}))
            baselines["planned"] = {"route_axis": preview["route_axis"], "metrics": _planned_metrics(preview["itinerary"]),
                                   "checkpoints": preview["checkpoints"],
                                   "source_binding": {"version_id": manifest["version_id"], "manifest_sha256": manifest["manifest_sha256"],
                                                      "geometry_sha256": manifest["geometry_sha256"], "itinerary_sha256": manifest["itinerary_sha256"]},
                                   "time_role": "planned_estimate"}
        comparisons = {role: _baseline_comparison(axis, metrics, baselines.get(role, {}), request.checkpoint_match_radius_m)
                       for role in ("golden", "planned")}
        graph, itinerary = _build_graph(axis, rests, gaps, comparisons, request, confirmed_camps)
        itinerary["camp_confirmations"] = confirmed_camps
        # Confirmations are annotations of stationary intervals already counted
        # in the timeline, never a second batch of elapsed/rest minutes.
        metrics_public = {k: v for k, v in metrics.items() if k != "intervals"}
        itinerary["summary"] = metrics_public
        geometry_sha = digest([[(p["lon"], p["lat"], p.get("ele")) for p in part] for part in _chunks(axis)])
        itinerary_sha = digest(itinerary)
        command = {"request": request.model_dump(mode="json", exclude={"idempotency_key"}), "source_hashes": hashes, "schema_version": SCHEMA}
        command_sha = digest(command)
        version_id = "recorded." + command_sha[:24]
        base = _version_ref(version_id)
        idem_ref = f"{STORE_REF}/idempotency/{digest(request.idempotency_key)}.json" if request.idempotency_key else None
        if idem_ref and safe_path(root, idem_ref).is_file():
            previous = _read(root, idem_ref)
            if previous.get("command_sha256") != command_sha:
                raise PlannedRouteConflict("recorded_idempotency_conflict", "This idempotency key belongs to different input bytes or a different recording set.")
        if safe_path(root, base + "/manifest.json").is_file():
            bundle = get_recorded_version(root, version_id)
            if idem_ref and not safe_path(root, idem_ref).exists():
                _atomic(root, idem_ref, {"project_id": project_id, "command_sha256": command_sha, "version_id": version_id})
            return {**bundle, "replayed": True}
        selection_kind = next(r["observation_kind"] for r in recordings if r["role"] == "primary")
        source_descriptions = [{k: v for k, v in r.items() if k != "parts"} for r in recordings]
        preview = {
            "schema_version": SCHEMA, "project_id": project_id, "version_id": version_id, "request": command["request"],
            "source_hashes": hashes, "recordings": source_descriptions, "primary_member_id": request.primary_member_id,
            "observation_kind": selection_kind, "actual_user_recorded_activity": selection_kind == "device_observation",
            "source_times_role": "fixture_replay_time" if selection_kind == "fixture_replay" else TIME_ROLE,
            "route_axis": axis, "route_geojson": _geo(axis), "checkpoints": graph["nodes"], "segments": graph["edges"],
            "graph": graph, "itinerary": itinerary, "comparison": comparisons,
            "geometry_sha256": geometry_sha, "itinerary_sha256": itinerary_sha,
            "metrics": metrics_public, "intervals": metrics["intervals"], "coverage": {
                "status": "requires_recorded_terrain_preparation", "dem_coverage_verified": False},
            "original_golden_preserved": True, "original_planned_preserved": True, **BOUNDARY,
        }
        if selection_kind == "fixture_replay":
            _fixture_time_roles(preview)
            itinerary_sha = digest(preview["itinerary"])
            preview["itinerary_sha256"] = itinerary_sha
        preview["observation_origin"] = "operator_declared_source_kind"
        preview["physical_activity_authenticity_verified"] = False
        preview = _signed(preview, "preview_sha256")
        documents: dict[str, bytes] = {
            "preview.json": _bytes(preview), "request.json": _bytes(command["request"]),
            "recorded.gpx": _recorded_gpx(axis, project_id, selection_kind),
            "route_axis.json": _bytes(axis), "route.geojson": _bytes(preview["route_geojson"]),
            "checkpoints.json": _bytes({"checkpoints": graph["nodes"], **BOUNDARY}),
            "segments.json": _bytes({"segments": graph["edges"], **BOUNDARY}),
            "graph.json": _bytes(graph), "itinerary.json": _bytes(itinerary), "comparison.json": _bytes(comparisons),
        }
        for i, (ref, raw) in enumerate(raw_sources.items()):
            documents[f"sources/{i:04d}.gpx"] = raw
        source_copies = {ref: {"ref": f"sources/{i:04d}.gpx", "sha256": _sha(raw)} for i, (ref, raw) in enumerate(raw_sources.items())}
        documents["source_copies.json"] = _bytes(source_copies)
        # Capability Timeline is run per continuous source part, so the legacy
        # GPX parser never invents a connecting edge across files or dropouts.
        capability = []
        for i, chunk in enumerate(_chunks(axis)):
            if len(chunk) < 2:
                continue
            nodes = [c for c in graph["nodes"] if chunk[0]["point_index"] <= c["point_index"] <= chunk[-1]["point_index"]]
            edges = [e for e in graph["edges"] if chunk[0]["point_index"] <= e["start_point_index"] and e["end_point_index"] <= chunk[-1]["point_index"]]
            cps = [CapabilityCheckpoint(c["candidate_id"], c["label"], c["lat"], c["lon"], c["source_refs"][0], 1) for c in nodes]
            segs = [CapabilitySegmentDefinition(e["candidate_id"], e["from_candidate_id"], e["to_candidate_id"], "graph.json", distance_m=e["distance_m"]) for e in edges]
            timeline = build_capability_timeline(
                case_id=version_id + f".part.{i}", route_family=project_id,
                route=GpxRoute(safe_path(root, chunk[0]["source_ref"]), _route_points(chunk)),
                track_source_path=safe_path(root, chunk[0]["source_ref"]), checkpoints=cps, segments=segs,
                checkpoint_source_path=safe_path(root, base + "/graph.json"),
                rest_policy=RestDetectionPolicy(max_sample_gap_s=request.max_sample_gap_seconds),
                analysis_context={"subject_kind": "recorded_gpx", "source_times_role": preview["source_times_role"],
                                  "observation_kind": selection_kind, "geometry_sha256": geometry_sha}, root=root,
            ).model_dump(mode="json")
            timeline.update({"recorded_version_id": version_id, "source_point_indices": [p["source_point_index"] for p in chunk],
                             "canonical_graph_ref": "graph.json", "canonical_intervals_ref": "preview.json", **BOUNDARY})
            ref = f"capability/part-{i:04d}.json"
            documents[ref] = _bytes(timeline)
            capability.append({"ref": ref, "sha256": _sha(documents[ref]), "source_ref": chunk[0]["source_ref"]})
        documents["capability_timeline_index.json"] = _bytes({"parts": capability, "source_times_role": preview["source_times_role"], **BOUNDARY})
        state = _source_status(root, hashes)
        if state["status"] != "current":
            raise PlannedRouteConflict("recorded_source_changed_during_save", "Recording or baseline changed while constructing the version.")
        manifest = _signed({
            "schema_version": SCHEMA, "kind": "recorded_gpx", "subject_kind": "recorded_gpx",
            "project_id": project_id, "version_id": version_id, "command_sha256": command_sha,
            "geometry_sha256": geometry_sha, "itinerary_sha256": itinerary_sha,
            "preview_sha256": preview["preview_sha256"], "source_hashes": hashes,
            "source_times_role": preview["source_times_role"], "observation_kind": selection_kind,
            "weather_evaluation_mode": "historical_at_observation_time",
            "actual_user_recorded_activity": preview["actual_user_recorded_activity"],
            "files": {name: {"sha256": _sha(raw), "bytes": len(raw)} for name, raw in documents.items()},
            "created_at": datetime.now(timezone.utc).isoformat(), **BOUNDARY,
        }, "manifest_sha256")
        for filename, raw in documents.items():
            _write_immutable(root, f"{base}/{filename}", raw)
        _write_immutable(root, base + "/manifest.json", _bytes(manifest))
        if idem_ref:
            _atomic(root, idem_ref, {"project_id": project_id, "command_sha256": command_sha, "version_id": version_id})
        return {**get_recorded_version(root, version_id), "replayed": False}


def get_recorded_version(project_root: Path, version_id: str, expected_manifest_sha256: str | None = None) -> dict:
    root, project_id = _project(project_root)
    base = _version_ref(version_id)
    manifest = _read(root, base + "/manifest.json")
    _verify(manifest, "manifest_sha256")
    if (manifest.get("project_id") != project_id or manifest.get("version_id") != version_id
            or manifest.get("kind") != "recorded_gpx"
            or version_id != "recorded." + manifest.get("command_sha256", "")[:24]
            or expected_manifest_sha256 and expected_manifest_sha256 != manifest["manifest_sha256"]
            or manifest.get("candidate_only") is not True or manifest.get("runtime_safety_truth") is not False):
        raise PlannedRouteConflict("recorded_binding_mismatch", "Recorded version, role or project binding differs.")
    required = {"preview.json", "request.json", "route_axis.json", "route.geojson", "checkpoints.json",
                "segments.json", "graph.json", "itinerary.json", "comparison.json", "source_copies.json", "capability_timeline_index.json", "recorded.gpx"}
    if not required.issubset(manifest.get("files", {})):
        raise PlannedRouteConflict("recorded_bundle_incomplete", "Recorded bundle is incomplete.")
    contents = {}
    for name, binding in manifest["files"].items():
        raw = _read_bytes(root, f"{base}/{name}")
        if _sha(raw) != binding.get("sha256") or len(raw) != binding.get("bytes"):
            raise PlannedRouteConflict("recorded_bundle_changed", f"Immutable Recorded file changed: {name}")
        contents[name] = raw
    preview = json.loads(contents["preview.json"])
    _verify(preview, "preview_sha256")
    for key in ("project_id", "version_id", "geometry_sha256", "itinerary_sha256", "preview_sha256", "source_hashes", "source_times_role"):
        if preview.get(key) != manifest.get(key):
            raise PlannedRouteConflict("recorded_binding_mismatch", "Recorded geometry, time, provenance and manifest differ.")
    for filename, value in (("route_axis.json", preview["route_axis"]), ("route.geojson", preview["route_geojson"]),
                            ("graph.json", preview["graph"]), ("itinerary.json", preview["itinerary"]),
                            ("comparison.json", preview["comparison"]), ("request.json", preview["request"]),
                            ("checkpoints.json", {"checkpoints": preview["checkpoints"], **BOUNDARY}),
                            ("segments.json", {"segments": preview["segments"], **BOUNDARY})):
        if contents[filename] != _bytes(value):
            raise PlannedRouteConflict("recorded_binding_mismatch", "Recorded derived input disagrees with its canonical preview.")
    if digest({"request": preview["request"], "source_hashes": manifest["source_hashes"], "schema_version": SCHEMA}) != manifest["command_sha256"]:
        raise PlannedRouteConflict("recorded_command_mismatch", "Recorded command is not bound to the version identifier.")
    expected_geometry = digest([[(p["lon"], p["lat"], p.get("ele")) for p in part] for part in _chunks(preview["route_axis"])])
    if (expected_geometry != manifest["geometry_sha256"] or digest(preview["itinerary"]) != manifest["itinerary_sha256"]
            or contents["recorded.gpx"] != _recorded_gpx(preview["route_axis"], project_id, manifest["observation_kind"])):
        raise PlannedRouteConflict("recorded_binding_mismatch", "Recorded geometry, itinerary or exported device times are inconsistent.")
    copies = json.loads(contents["source_copies.json"])
    for source_ref, copy_binding in copies.items():
        if (copy_binding.get("sha256") != manifest["source_hashes"].get(source_ref)
                or copy_binding.get("ref") not in contents
                or _sha(contents[copy_binding["ref"]]) != copy_binding["sha256"]):
            raise PlannedRouteConflict("recorded_source_copy_mismatch", "Recorded source copy differs from its original SHA.")
    source_points = {}
    for recording in preview["recordings"]:
        source_ref = recording["source_ref"]
        if source_ref not in copies:
            raise PlannedRouteConflict("recorded_source_copy_missing", "The complete original recording is required.")
        source_points[source_ref] = [point for part in _parse_recording(contents[copies[source_ref]["ref"]], source_ref) for point in part]
    for point in preview["route_axis"]:
        try:
            original = source_points[point["source_ref"]][point["source_point_index"]]
        except (KeyError, IndexError, TypeError) as exc:
            raise PlannedRouteConflict("recorded_point_provenance_mismatch", "Recorded point is not present in the copied source.") from exc
        if any(point.get(key) != original.get(key) for key in ("lat", "lon", "ele", "timestamp", "source_segment_index")):
            raise PlannedRouteConflict("recorded_point_provenance_mismatch", "Recorded coordinates and times must equal their original source occurrence.")
    return {"manifest": manifest, "preview": preview, "source_status": _source_status(root, manifest["source_hashes"]),
            "bundle_ref": base, "status": "saved", **BOUNDARY}


def list_recorded_versions(project_root: Path) -> dict:
    root, project_id = _project(project_root)
    directory = safe_path(root, STORE_REF + "/versions")
    rows = []
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if VERSION_RE.fullmatch(path.name) and (path / "manifest.json").is_file():
                value = get_recorded_version(root, path.name)
                rows.append({"manifest": value["manifest"], "source_status": value["source_status"],
                             "metrics": value["preview"]["metrics"], "label": value["preview"]["request"]["label"]})
    return {"project_id": project_id, "versions": rows, "selection": get_recorded_selection(root), **BOUNDARY}


def get_recorded_selection(project_root: Path) -> dict:
    root, project_id = _project(project_root)
    path = safe_path(root, STORE_REF + "/selection.json")
    if not path.is_file():
        return {"project_id": project_id, "status": "not_selected", **BOUNDARY}
    selection = json.loads(path.read_bytes())
    _verify(selection, "selection_sha256")
    if selection.get("project_id") != project_id or selection.get("subject_kind") != "recorded_gpx":
        raise PlannedRouteConflict("recorded_selection_mismatch", "Recorded selection belongs to another project.")
    bundle = get_recorded_version(root, selection["version_id"], selection["manifest_sha256"])
    return {**selection, "status": "selected" if bundle["source_status"]["status"] == "current" else "stale",
            "source_status": bundle["source_status"]}


def select_recorded_version(project_root: Path, version_id: str, expected_manifest_sha256: str | None = None) -> dict:
    root, project_id = _project(project_root)
    with _writer(root):
        bundle = get_recorded_version(root, version_id, expected_manifest_sha256)
        if bundle["source_status"]["status"] != "current":
            raise PlannedRouteConflict("recorded_source_stale", "Recorded inputs changed; save a new version before selecting it.")
        manifest = bundle["manifest"]
        selection = _signed({"project_id": project_id, "subject_kind": "recorded_gpx", "version_id": version_id,
                             "manifest_sha256": manifest["manifest_sha256"], "geometry_sha256": manifest["geometry_sha256"],
                             "itinerary_sha256": manifest["itinerary_sha256"], "source_times_role": manifest["source_times_role"],
                             "selected_at": datetime.now(timezone.utc).isoformat(),
                             "analysis_golden_role": "selected_recorded_observation", "original_golden_replaced": False, **BOUNDARY},
                            "selection_sha256")
        _atomic(root, STORE_REF + "/selection.json", selection)
        return {**selection, "status": "selected"}


def build_recorded_analysis_inputs(owner_root: Path, bundle: dict, run_root: Path, preparation: dict | None = None) -> dict:
    """Legacy assessor schema, explicitly carrying actual Recorded time roles."""
    owner_root, project_id = _project(owner_root)
    run_root = Path(run_root).resolve()
    if run_root == owner_root:
        raise PlannedRouteConflict("recorded_analysis_owner_write", "Recorded derived inputs require a separate run workspace.")
    manifest = bundle["manifest"]
    current = get_recorded_version(owner_root, manifest["version_id"], manifest["manifest_sha256"])
    if current["source_status"]["status"] != "current":
        raise PlannedRouteConflict("recorded_source_stale", "Recorded six-force inputs require unchanged sources.")
    preview = current["preview"]
    binding = {k: manifest[k] for k in ("project_id", "version_id", "manifest_sha256", "geometry_sha256", "itinerary_sha256", "source_times_role")}
    binding.update({"kind": "recorded_gpx", "subject_kind": "recorded_gpx", "input_adapter_version": SCHEMA,
                    "observation_kind": manifest["observation_kind"], "weather_evaluation_mode": "historical_at_observation_time", **BOUNDARY})
    for key, value in (preparation or {}).get("subject_binding", {}).items():
        if key in binding and value != binding[key]:
            raise PlannedRouteConflict("recorded_analysis_subject_mismatch", "Terrain preparation belongs to another Recorded subject.")
    graph, itinerary, axis = copy.deepcopy(preview["graph"]), copy.deepcopy(preview["itinerary"]), copy.deepcopy(preview["route_axis"])
    graph["input_binding"] = binding
    itinerary["input_binding"] = binding
    eta = {"artifact_kind": "recorded_observation_timing", "schema_version": SCHEMA,
           "project_id": project_id, "time_role": preview["source_times_role"], "input_binding": binding,
           "estimates": [{"estimate_id": c["candidate_id"], "to_node_id": c["candidate_id"], "to_node_name": c["label"],
                         "eta": c["arrival_at"], "departure_at": c["departure_at"], "point_index": c["point_index"],
                         "time_role": preview["source_times_role"]} for c in graph["nodes"]],
           "days": itinerary["days"], "timeline": itinerary["timeline"], "unknowns": itinerary["unknowns"],
           "assumption": {"target_eta": itinerary["days"][-1].get("arrival_at") if itinerary["days"] else None},
           "weather_evaluation_mode": "historical_at_observation_time", **BOUNDARY}
    summary = {"project_id": project_id, "artifact_id": manifest["version_id"], "route_name": preview["request"]["label"],
               "route_role": "recorded", "distance_m": preview["metrics"]["distance_m"], "point_count": len(axis),
               "checkpoint_count": len(graph["nodes"]), "segment_count": len(graph["edges"]),
               "elevation_gain_m": sum(e["elevation_gain_m"] or 0 for e in graph["edges"]),
               "elevation_loss_m": sum(e["elevation_loss_m"] or 0 for e in graph["edges"]),
               "elevation_incomplete": any(p.get("ele") is None for p in axis),
               "bbox_wgs84": {"min_lat": min(p["lat"] for p in axis), "max_lat": max(p["lat"] for p in axis),
                             "min_lon": min(p["lon"] for p in axis), "max_lon": max(p["lon"] for p in axis)},
               "input_binding": binding, **BOUNDARY}
    geometry = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": edge, "geometry": {"type": "LineString", "coordinates": [
            [p["lon"], p["lat"]] for p in axis[edge["start_point_index"]:edge["end_point_index"] + 1]]}}
        for edge in graph["edges"] if edge["distance_m"] > 0]}
    payloads = {
        "route_summary_ref": ("normalized/routes/route_summary.json", summary),
        "checkpoint_candidates_ref": ("candidates/checkpoints.json", graph["nodes"]),
        "segment_candidates_ref": ("candidates/segments.json", graph["edges"]),
        "segment_policy_candidates_ref": ("outputs/segment_policy_candidates.json", [
            {"segment_candidate_id": edge["candidate_id"], "requirement": {"expected_duration_seconds": edge["actual_duration_seconds"]},
             "unknown_requirements": ["requires_daylight", "retreat_available", "water_available", "signal_expected"], **BOUNDARY}
            for edge in graph["edges"]]),
        "planned_eta_ref": ("outputs/planned_eta.json", eta),
        "segment_display_geometry_ref": ("outputs/segment_display_geometry.json", geometry),
        "recorded_route_geometry_ref": ("inputs/recorded_route.geojson", preview["route_geojson"]),
        "planned_route_axis_ref": ("inputs/route_axis.json", axis),
        "recorded_cp_graph_ref": ("outputs/recorded_cp_graph.json", graph),
        "recorded_comparison_ref": ("outputs/recorded_comparison.json", preview["comparison"]),
        "reference_tracks_ref": ("inputs/recorded_tracks.json", {"tracks": preview["recordings"],
            "primary_member_id": preview["primary_member_id"], "input_binding": binding, **BOUNDARY}),
    }
    workspace_ref = "workspaces/analysis"
    root = safe_path(run_root, workspace_ref)
    project = {"project_id": project_id, "name": summary["route_name"], "analysis_subject_kind": "recorded_gpx",
               "recorded_analysis_binding": binding, "planned_analysis_binding": binding,
               "weather_evaluation_mode": "historical_at_observation_time",
               "mission_day_ids": [d["day_id"] for d in itinerary["days"]], **BOUNDARY}
    hashes, refs = {}, {}
    for key, (ref, payload) in payloads.items():
        raw = _bytes(payload)
        _write_immutable(root, ref, raw)
        hashes[ref] = _sha(raw)
        refs[key] = f"{workspace_ref}/{ref}"
        project[key] = ref
    _write_immutable(root, "project.json", _bytes(project))
    # A canonical alias is required by shared terrain/evidence readers. Its
    # content explicitly labels actual observations; no timestamps are invented.
    return {"status": "partial" if graph["gaps"] else "ready", "workspace_ref": workspace_ref,
            "graph_ref": refs["recorded_cp_graph_ref"], "subject_binding": binding, "canonical_refs": refs,
            "input_hashes": hashes, "graph": graph, "route_axis": axis, "itinerary": itinerary,
            "route_summary": summary, "planned_eta": eta, "gaps": graph["gaps"],
            "comparison": preview["comparison"], "weather_evaluation_mode": "historical_at_observation_time", **BOUNDARY}
