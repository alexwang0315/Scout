from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_utils import haversine_m
from pretrip_source_ingest import sha256_file


DEFAULT_MAX_REASONABLE_SPEED_KMH = 120.0
DEFAULT_MAX_PREVIOUS_SPEED_RATIO = 8.0
DEFAULT_MIN_PREVIOUS_SPEED_FOR_RELATIVE_FILTER_KMH = 0.5
DEFAULT_RESUME_SEGMENT_GAP_M = 1000.0
DEFAULT_ROUTE_NOTE_PROTECTION_RADIUS_M = 30.0


@dataclass(frozen=True)
class GpxSpeedFilterReport:
    source_path: str
    output_path: str
    max_reasonable_speed_kmh: float
    max_previous_speed_ratio: float
    original_track_point_count: int
    filtered_track_point_count: int
    removed_track_point_count: int
    removed_points: tuple[dict[str, Any], ...]
    exempted_track_point_count: int
    exempted_points: tuple[dict[str, Any], ...]
    source_sha256: str
    output_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": "gpx_speed_filter_report",
            "source_path": self.source_path,
            "output_path": self.output_path,
            "max_reasonable_speed_kmh": self.max_reasonable_speed_kmh,
            "max_previous_speed_ratio": self.max_previous_speed_ratio,
            "min_previous_speed_for_relative_filter_kmh": (
                DEFAULT_MIN_PREVIOUS_SPEED_FOR_RELATIVE_FILTER_KMH
            ),
            "original_track_point_count": self.original_track_point_count,
            "filtered_track_point_count": self.filtered_track_point_count,
            "removed_track_point_count": self.removed_track_point_count,
            "removed_points": list(self.removed_points),
            "exempted_track_point_count": self.exempted_track_point_count,
            "exempted_points": list(self.exempted_points),
            "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "filter_rule": (
                "Remove a track point when the distance from the previous kept "
                "track point divided by elapsed time would require speed greater "
                "than max_reasonable_speed_kmh, or when it would require speed "
                "greater than max_previous_speed_ratio times the previous kept "
                "segment speed when the previous kept segment is moving faster "
                "than min_previous_speed_for_relative_filter_kmh. Long distance "
                "GPS resume gaps are preserved and annotated downstream as resume "
                "segments instead of being pruned. Track points protected by nearby "
                "GPX route notes are retained and reported as route_note_protected "
                "exemptions."
            ),
            "route_note_protection_radius_m": DEFAULT_ROUTE_NOTE_PROTECTION_RADIUS_M,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }


@dataclass(frozen=True)
class _TrackPoint:
    element: ET.Element
    segment: ET.Element
    source_index: int
    lat: float
    lon: float
    timestamp: datetime | None


def write_speed_filtered_gpx(
    source_path: Path | str,
    output_path: Path | str,
    *,
    max_reasonable_speed_kmh: float = DEFAULT_MAX_REASONABLE_SPEED_KMH,
    max_previous_speed_ratio: float = DEFAULT_MAX_PREVIOUS_SPEED_RATIO,
) -> GpxSpeedFilterReport:
    if max_reasonable_speed_kmh <= 0:
        raise ValueError("max_reasonable_speed_kmh must be greater than 0")
    if max_previous_speed_ratio <= 0:
        raise ValueError("max_previous_speed_ratio must be greater than 0")
    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser()
    tree = ET.parse(source)
    root = tree.getroot()
    namespace = _namespace(root)
    track_points = _track_points(root, namespace=namespace)
    protected_points = _route_note_protected_point_index(track_points, root, namespace=namespace)
    keep_ids, removed, exempted = _kept_track_point_ids(
        track_points,
        max_reasonable_speed_kmh=max_reasonable_speed_kmh,
        max_previous_speed_ratio=max_previous_speed_ratio,
        protected_points=protected_points,
    )
    filtered_root = copy.deepcopy(root)
    filtered_track_points = _track_points(filtered_root, namespace=namespace)
    for point in filtered_track_points:
        if point.source_index not in keep_ids:
            point.segment.remove(point.element)
    if namespace:
        ET.register_namespace("", namespace)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(filtered_root).write(output, encoding="utf-8", xml_declaration=True)
    filtered_count = len(keep_ids)
    return GpxSpeedFilterReport(
        source_path=source.as_posix(),
        output_path=output.resolve().as_posix(),
        max_reasonable_speed_kmh=max_reasonable_speed_kmh,
        max_previous_speed_ratio=max_previous_speed_ratio,
        original_track_point_count=len(track_points),
        filtered_track_point_count=filtered_count,
        removed_track_point_count=len(track_points) - filtered_count,
        removed_points=tuple(removed),
        exempted_track_point_count=len(exempted),
        exempted_points=tuple(exempted),
        source_sha256=sha256_file(source),
        output_sha256=sha256_file(output),
    )


def _kept_track_point_ids(
    points: list[_TrackPoint],
    *,
    max_reasonable_speed_kmh: float,
    max_previous_speed_ratio: float,
    protected_points: dict[int, dict[str, Any]],
) -> tuple[set[int], list[dict[str, Any]], list[dict[str, Any]]]:
    kept: set[int] = set()
    removed: list[dict[str, Any]] = []
    exempted: list[dict[str, Any]] = []
    previous_kept: _TrackPoint | None = None
    previous_kept_speed_kmh: float | None = None
    for point in points:
        if previous_kept is None:
            kept.add(point.source_index)
            previous_kept = point
            continue
        evaluation = _speed_evaluation(previous_kept, point)
        removal_reason = _removal_reason(
            evaluation,
            max_reasonable_speed_kmh=max_reasonable_speed_kmh,
            max_previous_speed_ratio=max_previous_speed_ratio,
            previous_kept_speed_kmh=previous_kept_speed_kmh,
        )
        if removal_reason:
            serializable_evaluation = _serializable_evaluation(
                evaluation,
                max_previous_speed_ratio=max_previous_speed_ratio,
                previous_kept_speed_kmh=previous_kept_speed_kmh,
            )
            protected_note = protected_points.get(point.source_index)
            if protected_note is not None:
                exempted.append(
                    {
                        "source_index": point.source_index,
                        "lat": round(point.lat, 7),
                        "lon": round(point.lon, 7),
                        "time": point.timestamp.isoformat().replace("+00:00", "Z")
                        if point.timestamp
                        else None,
                        **serializable_evaluation,
                        "would_remove_reason": removal_reason,
                        "exemption_reason": "route_note_protected",
                        "route_note": protected_note,
                    }
                )
                kept.add(point.source_index)
                previous_kept = point
                previous_kept_speed_kmh = (
                    None if _is_resume_gap(evaluation) else _numeric_speed(evaluation)
                )
                continue
            removed.append(
                {
                    "source_index": point.source_index,
                    "lat": round(point.lat, 7),
                    "lon": round(point.lon, 7),
                    "time": point.timestamp.isoformat().replace("+00:00", "Z")
                    if point.timestamp
                    else None,
                    **serializable_evaluation,
                    "reason": removal_reason,
                }
            )
            continue
        kept.add(point.source_index)
        previous_kept = point
        previous_kept_speed_kmh = (
            None if _is_resume_gap(evaluation) else _numeric_speed(evaluation)
        )
    return kept, removed, exempted


def _removal_reason(
    evaluation: dict[str, Any] | None,
    *,
    max_reasonable_speed_kmh: float,
    max_previous_speed_ratio: float,
    previous_kept_speed_kmh: float | None,
) -> str | None:
    required_speed = _numeric_speed(evaluation)
    if required_speed is None:
        return None
    if required_speed > max_reasonable_speed_kmh:
        return "required_speed_exceeds_absolute_threshold"
    if previous_kept_speed_kmh is None or previous_kept_speed_kmh <= 0:
        return None
    if previous_kept_speed_kmh < DEFAULT_MIN_PREVIOUS_SPEED_FOR_RELATIVE_FILTER_KMH:
        return None
    if required_speed > previous_kept_speed_kmh * max_previous_speed_ratio:
        return "required_speed_exceeds_previous_speed_ratio"
    return None


def _serializable_evaluation(
    evaluation: dict[str, Any] | None,
    *,
    max_previous_speed_ratio: float,
    previous_kept_speed_kmh: float | None,
) -> dict[str, Any]:
    if evaluation is None:
        return {}
    serializable = dict(evaluation)
    required_speed = _numeric_speed(evaluation)
    if serializable["required_speed_kmh"] == float("inf"):
        serializable["required_speed_kmh"] = "Infinity"
    if previous_kept_speed_kmh is not None:
        serializable["previous_kept_speed_kmh"] = round(previous_kept_speed_kmh, 3)
        serializable["max_relative_speed_kmh"] = round(
            previous_kept_speed_kmh * max_previous_speed_ratio,
            3,
        )
        if required_speed is not None and previous_kept_speed_kmh > 0:
            serializable["speed_ratio_to_previous_kept"] = round(
                required_speed / previous_kept_speed_kmh,
                3,
            )
    return serializable


def _is_resume_gap(evaluation: dict[str, Any] | None) -> bool:
    if evaluation is None:
        return False
    distance_m = evaluation.get("distance_m")
    return isinstance(distance_m, (int, float)) and distance_m > DEFAULT_RESUME_SEGMENT_GAP_M


def _numeric_speed(evaluation: dict[str, Any] | None) -> float | None:
    if evaluation is None:
        return None
    value = evaluation.get("required_speed_kmh")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _speed_evaluation(previous: _TrackPoint, current: _TrackPoint) -> dict[str, Any] | None:
    if previous.timestamp is None or current.timestamp is None:
        return None
    distance_m = haversine_m(previous.lat, previous.lon, current.lat, current.lon)
    elapsed_seconds = (current.timestamp - previous.timestamp).total_seconds()
    if elapsed_seconds <= 0:
        required_speed_kmh = float("inf") if distance_m > 0 else 0.0
    else:
        required_speed_kmh = (distance_m / elapsed_seconds) * 3.6
    return {
        "previous_kept_source_index": previous.source_index,
        "distance_m": round(distance_m, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "required_speed_kmh": required_speed_kmh
        if required_speed_kmh == float("inf")
        else round(required_speed_kmh, 3),
    }


def _track_points(root: ET.Element, *, namespace: str | None) -> list[_TrackPoint]:
    trkpt_tag = _tag(namespace, "trkpt")
    time_tag = _tag(namespace, "time")
    points: list[_TrackPoint] = []
    for segment in root.findall(f".//{_tag(namespace, 'trkseg')}"):
        for element in segment.findall(trkpt_tag):
            points.append(
                _TrackPoint(
                    element=element,
                    segment=segment,
                    source_index=len(points),
                    lat=float(element.attrib["lat"]),
                    lon=float(element.attrib["lon"]),
                    timestamp=_parse_gpx_time(element.findtext(time_tag)),
                )
            )
    return points


def _route_note_protected_point_index(
    points: list[_TrackPoint],
    root: ET.Element,
    *,
    namespace: str | None,
) -> dict[int, dict[str, Any]]:
    protected: dict[int, dict[str, Any]] = {}
    waypoint_tag = _tag(namespace, "wpt")
    for waypoint_index, waypoint in enumerate(root.findall(f".//{waypoint_tag}")):
        note = _waypoint_note(waypoint, namespace=namespace)
        if not note:
            continue
        lat = float(waypoint.attrib["lat"])
        lon = float(waypoint.attrib["lon"])
        nearest_index: int | None = None
        nearest_distance_m: float | None = None
        for point in points:
            distance_m = haversine_m(lat, lon, point.lat, point.lon)
            if nearest_distance_m is None or distance_m < nearest_distance_m:
                nearest_distance_m = distance_m
                nearest_index = point.source_index
        if (
            nearest_index is None
            or nearest_distance_m is None
            or nearest_distance_m > DEFAULT_ROUTE_NOTE_PROTECTION_RADIUS_M
        ):
            continue
        protected[nearest_index] = {
            "source_waypoint_index": waypoint_index,
            "distance_m": round(nearest_distance_m, 3),
            "note": note,
            "protection_radius_m": DEFAULT_ROUTE_NOTE_PROTECTION_RADIUS_M,
        }
    return protected


def _waypoint_note(waypoint: ET.Element, *, namespace: str | None) -> str:
    values = []
    for child in ("name", "cmt", "desc"):
        value = waypoint.findtext(_tag(namespace, child))
        if value and value.strip():
            cleaned = " ".join(value.split())
            if cleaned not in values:
                values.append(cleaned)
    return " | ".join(values)


def _parse_gpx_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _namespace(root: ET.Element) -> str | None:
    if root.tag.startswith("{"):
        return root.tag[1:].split("}", 1)[0]
    return None


def _tag(namespace: str | None, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name
