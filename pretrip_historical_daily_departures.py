"""Candidate departure clocks from one filtered primary GPX, never live daylight."""

from __future__ import annotations

import hashlib
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from geo_utils import haversine_m


MIN_OVERNIGHT_HOURS = 6.0
MAX_OVERNIGHT_HOURS = 36.0
MAX_OVERNIGHT_SEPARATION_M = 150.0


@dataclass(frozen=True)
class _Point:
    lat: float
    lon: float
    observed_at: datetime | None
    time_issue: str | None


class _NoDeclarations(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str | None, system: str | None) -> None:
        raise ValueError("unsupported_xml_declaration")


def build_historical_daily_departures(
    *,
    project_root: Path,
    timezone: ZoneInfo,
    timezone_source: str,
) -> dict:
    """Read without mutation; broken chronology publishes no usable days."""
    result = _empty_result(timezone, timezone_source)
    try:
        root = project_root.resolve()
        directory = root / "normalized/routes/filtered"
        if not directory.resolve().is_relative_to(root):
            return {**result, "reason": "source_outside_project_root"}
        matches = sorted(directory.glob("primary.*.speed_filtered.gpx"))
        if len(matches) != 1:
            return {
                **result,
                "reason": "primary_missing" if not matches else "ambiguous_primary",
            }
        path = matches[0]
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(root):
            return {**result, "reason": "source_outside_project_root"}
        if not resolved_path.is_file():
            return {**result, "reason": "source_not_file"}
        payload = resolved_path.read_bytes()
        ref = path.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return {**result, "reason": "primary_unreadable"}

    result = {
        **result,
        "source_ref": ref,
        "source_refs": [ref],
        "source_sha256": hashlib.sha256(payload).hexdigest(),
    }
    try:
        points, segment_count = _parse_points(payload)
    except ET.ParseError:
        return {
            **result,
            "reason": "invalid_gpx_xml",
            "quality_flags": ["invalid_gpx_xml"],
        }
    except ValueError as error:
        return {**result, "reason": str(error), "quality_flags": [str(error)]}

    # Include untimed points and segment connectors exactly as _primary_route_progress.
    axis = [0.0] if points else []
    try:
        for first, second in zip(points, points[1:]):
            axis.append(
                axis[-1] + haversine_m(first.lat, first.lon, second.lat, second.lon)
            )
    except (ValueError, OverflowError):
        return {
            **result,
            "reason": "invalid_route_axis",
            "quality_flags": ["invalid_route_axis"],
        }
    timed = [
        index for index, point in enumerate(points) if point.observed_at is not None
    ]
    counts = {
        "source_count": 1,
        "track_point_count": len(points),
        "timed_point_count": len(timed),
        "untimed_point_count": len(points) - len(timed),
        "track_segment_count": segment_count,
        "day_count": 0,
        "overnight_break_count": 0,
    }
    result = {**result, "route_distance_m": axis[-1] if axis else 0.0, "counts": counts}
    if len(points) < 2:
        return {**result, "reason": "insufficient_track_points"}
    if not axis[-1] > 0:
        return {**result, "reason": "zero_length_route_axis"}
    return _extract_schedule(result, points, axis, timed, timezone)


def _empty_result(timezone: ZoneInfo, timezone_source: str) -> dict[str, Any]:
    return {
        "schema_version": "historical_daily_departures.v1",
        "status": "unavailable",
        "reason": None,
        "days": [],
        "source_ref": None,
        "source_refs": [],
        "source_sha256": None,
        "timezone": timezone.key,
        "timezone_source": timezone_source,
        "route_axis": "filtered_primary_cumulative_haversine_all_points",
        "route_distance_m": None,
        "cutoff_policy": "fixed_18_00_not_astronomical_sunset",
        "cutoff_minute_of_day": 1080,
        "policy": {
            "minimum_overnight_gap_hours": MIN_OVERNIGHT_HOURS,
            "maximum_overnight_gap_hours": MAX_OVERNIGHT_HOURS,
            "maximum_overnight_separation_m": MAX_OVERNIGHT_SEPARATION_M,
            "overnight_requires_local_date_change": True,
            "midnight_alone_resets_day": False,
            "camp_label_alone_resets_day": False,
            "source_selection": "single_filtered_primary_no_expedition_pooling",
            "point_index_basis": "zero_based_flattened_trackpoints_in_document_order",
            "invalid_schedule_policy": "unavailable_no_usable_days",
        },
        "quality_flags": [],
        "quality_issues": [],
        "schedule_breaks": [],
        "overnight_breaks": [],
        "unknown_ranges": [],
        "counts": {},
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_points(payload: bytes) -> tuple[list[_Point], int]:
    root = ET.fromstring(payload, parser=ET.XMLParser(target=_NoDeclarations()))
    if _local_name(root.tag) != "gpx":
        raise ValueError("invalid_gpx_root")
    segments = [
        [child for child in segment if _local_name(child.tag) == "trkpt"]
        for segment in root.iter()
        if _local_name(segment.tag) == "trkseg"
    ]
    segments = [segment for segment in segments if segment]
    if not segments:
        fallback = [
            element for element in root.iter() if _local_name(element.tag) == "trkpt"
        ]
        segments = [fallback] if fallback else []
    return [_parse_point(element) for segment in segments for element in segment], len(
        segments
    )


def _parse_point(element: ET.Element) -> _Point:
    try:
        lat, lon = float(element.attrib["lat"]), float(element.attrib["lon"])
    except (KeyError, ValueError, TypeError, OverflowError):
        raise ValueError("invalid_coordinates") from None
    if not (
        math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    ):
        raise ValueError("invalid_coordinates")
    clocks = [child.text for child in element if _local_name(child.tag) == "time"]
    if len(clocks) > 1:
        return _Point(lat, lon, None, "ambiguous_timestamp")
    value = clocks[0].strip() if clocks and clocks[0] else ""
    if not value:
        return _Point(lat, lon, None, "missing_timestamps")
    try:
        observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if observed_at.utcoffset() is None:
            return _Point(lat, lon, None, "timestamp_timezone_missing")
        return _Point(lat, lon, observed_at.astimezone(datetime_timezone.utc), None)
    except (ValueError, OverflowError):
        return _Point(lat, lon, None, "invalid_timestamp")


def _span(axis: list[float], start: int, end: int, reason: str, **extra) -> dict:
    return {
        "reason": reason,
        "start_point_index": start,
        "end_point_index": end,
        "start_distance_m": axis[start],
        "end_distance_m": axis[end],
        **extra,
    }


def _point_issues(points: list[_Point], axis: list[float]) -> list[dict]:
    issues = []
    index = 0
    while index < len(points):
        reason = points[index].time_issue
        if reason is None:
            index += 1
            continue
        end = index
        while end + 1 < len(points) and points[end + 1].time_issue == reason:
            end += 1
        issues.append(_span(axis, index, end, reason))
        index = end + 1
    return issues


def _timed_pair(
    points: list[_Point],
    axis: list[float],
    start: int,
    end: int,
    timezone: ZoneInfo,
) -> tuple[str, dict] | None:
    first, second = points[start], points[end]
    gap_hours = (second.observed_at - first.observed_at).total_seconds() / 3600
    distance = haversine_m(first.lat, first.lon, second.lat, second.lon)
    extra = {"preceding_gap_hours": gap_hours, "physical_separation_m": distance}
    if gap_hours <= 0:
        return "invalid", _span(axis, start, end, "non_increasing_timestamp", **extra)
    if gap_hours > MAX_OVERNIGHT_HOURS:
        return "invalid", _span(axis, start, end, "temporal_gap_exceeds_36h", **extra)
    try:
        different_day = (
            first.observed_at.astimezone(timezone).date()
            != second.observed_at.astimezone(timezone).date()
        )
    except (ValueError, OverflowError):
        return "invalid", _span(axis, start, end, "timestamp_out_of_range")
    if gap_hours >= MIN_OVERNIGHT_HOURS and different_day:
        if distance > MAX_OVERNIGHT_SEPARATION_M:
            return "invalid", _span(
                axis, start, end, "overnight_gap_spatial_discontinuity", **extra
            )
        return "overnight", _span(
            axis,
            start,
            end,
            "overnight_gap_candidate",
            **extra,
            quality_flags=["untimed_points_in_gap"] if end > start + 1 else [],
            candidate_only=True,
            overnight_assignment_verified=False,
            runtime_safety_truth=False,
        )
    reason = (
        "continuous_midnight_retained"
        if different_day
        else (
            "same_day_long_stop_retained" if gap_hours >= MIN_OVERNIGHT_HOURS else None
        )
    )
    return ("warning", _span(axis, start, end, reason, **extra)) if reason else None


def _extract_schedule(
    result: dict,
    points: list[_Point],
    axis: list[float],
    timed: list[int],
    timezone: ZoneInfo,
) -> dict:
    issues = _point_issues(points, axis)
    invalid = [issue for issue in issues if issue["reason"] != "missing_timestamps"]
    overnights = []
    for start, end in zip(timed, timed[1:]):
        pair = _timed_pair(points, axis, start, end, timezone)
        if pair is None:
            continue
        kind, detail = pair
        if kind == "overnight":
            overnights.append(detail)
        else:
            issues.append(detail)
            if kind == "invalid":
                invalid.append(detail)
    flags = {issue["reason"] for issue in issues}
    if result["counts"]["track_segment_count"] > 1:
        flags.add("multiple_track_segments")
    result = {**result, "quality_flags": sorted(flags), "quality_issues": issues}
    if invalid:
        return {
            **result,
            "reason": "invalid_schedule",
            "schedule_breaks": invalid,
            "unknown_ranges": [_span(axis, 0, len(points) - 1, "invalid_schedule")],
        }
    if len(timed) < 2:
        return {
            **result,
            "reason": "insufficient_timed_records",
            "unknown_ranges": [
                _span(axis, 0, len(points) - 1, "insufficient_timed_records")
            ],
        }
    return _ready_schedule(result, points, axis, timed, overnights, timezone)


def _ready_schedule(
    result: dict,
    points: list[_Point],
    axis: list[float],
    timed: list[int],
    overnights: list[dict],
    timezone: ZoneInfo,
) -> dict:
    starts = [timed[0], *(item["end_point_index"] for item in overnights)]
    ends = [*(item["start_point_index"] for item in overnights), timed[-1]]
    gaps = [None, *(item["preceding_gap_hours"] for item in overnights)]
    records = [
        _day_record(result, points, axis, index, start, end, gap, timezone)
        for index, (start, end, gap) in enumerate(zip(starts, ends, gaps), 1)
    ]
    days = [day for day in records if day["end_distance_m"] > day["start_distance_m"]]
    empty_spans = [
        _span(
            axis, day["start_point_index"], day["end_point_index"], "zero_span_day",
            day_index=day["day_index"],
        )
        for day in records
        if day["end_distance_m"] <= day["start_distance_m"]
    ]
    unknown = list(empty_spans)
    if timed[0] > 0:
        unknown.append(_span(axis, 0, timed[0], "missing_boundary_timestamp"))
    unknown.extend(
        _span(
            axis,
            item["start_point_index"],
            item["end_point_index"],
            "overnight_recording_gap",
        )
        for item in overnights
        if item["end_distance_m"] > item["start_distance_m"]
    )
    if timed[-1] < len(points) - 1:
        unknown.append(
            _span(axis, timed[-1], len(points) - 1, "missing_boundary_timestamp")
        )
    return {
        **result,
        "status": "ready" if days else "unavailable",
        "reason": result.get("reason") if days else "no_positive_length_days",
        "days": days,
        "overnight_breaks": overnights,
        "unknown_ranges": unknown,
        "quality_issues": [*result["quality_issues"], *empty_spans],
        "quality_flags": sorted(
            {
                *result["quality_flags"],
                *(span["reason"] for span in empty_spans),
                *(flag for day in days for flag in day["quality_flags"]),
            }
        ),
        "counts": {
            **result["counts"],
            "day_count": len(days),
            "overnight_break_count": len(overnights),
        },
    }


def _day_record(
    result: dict,
    points: list[_Point],
    axis: list[float],
    index: int,
    start: int,
    end: int,
    gap: float | None,
    timezone: ZoneInfo,
) -> dict:
    local_clock = points[start].observed_at.astimezone(timezone)
    flags = {
        issue["reason"]
        for issue in result["quality_issues"]
        if issue["start_point_index"] <= end and issue["end_point_index"] >= start
    }
    if index == 1 and start > 0:
        flags.add("leading_untimed_points")
    if end < len(points) - 1 and all(
        point.observed_at is None for point in points[end + 1 :]
    ):
        flags.add("trailing_untimed_points")
    if gap is not None:
        flags.add("overnight_departure_candidate")
    if result["counts"]["track_segment_count"] > 1:
        flags.add("multiple_track_segments")
    return {
        "day_id": f"historical_day.{result['source_sha256'][:16]}.{index:03d}",
        "day_index": index,
        "start_point_index": start,
        "end_point_index": end,
        "start_distance_m": axis[start],
        "end_distance_m": axis[end],
        "departure_minute_of_day": local_clock.hour * 60
        + local_clock.minute
        + (local_clock.second + local_clock.microsecond / 1_000_000) / 60,
        "departure_status": "estimated",
        "departure_basis": "first_record_after_overnight_gap"
        if gap is not None
        else "initial_record",
        "preceding_gap_hours": gap,
        "source_refs": list(result["source_refs"]),
        "source_ref": result["source_ref"],
        "source_sha256": result["source_sha256"],
        "quality_flags": sorted(flags),
        "candidate_only": True,
        "overnight_assignment_verified": False,
        "runtime_safety_truth": False,
    }
