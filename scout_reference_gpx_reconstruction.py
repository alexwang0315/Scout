"""Reconstruct one recorded reference itinerary without writing or granting authority."""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from geo_utils import haversine_m
from pretrip_historical_daily_departures import (
    _parse_points,
    build_historical_daily_departures,
)


REST_RADIUS_M = 80.0
REST_MIN_POINTS = 16
REST_MIN_MINUTES = 20.0
REST_MAX_NET_SPEED_M_PER_MINUTE = 5.0
REST_MAX_OBSERVATION_GAP_SECONDS = 600.0
ROUTE_POINT_LIMIT = 480
CP_AXIS_TOLERANCE_M = 0.1


def _read_source(root: Path, ref: str, name: str) -> bytes:
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError(f"reference_gpx_{name}_ref_missing")
    path = Path(ref)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"reference_gpx_{name}_outside_project")
    try:
        source = (root / path).resolve()
        if not source.is_relative_to(root):
            raise ValueError(f"reference_gpx_{name}_outside_project")
        return source.read_bytes()
    except (OSError, RuntimeError):
        raise ValueError(f"reference_gpx_{name}_unreadable") from None


def _read_json(payload: bytes, name: str) -> dict:
    try:
        result = json.loads(payload)
    except (UnicodeError, ValueError):
        raise ValueError(f"reference_gpx_{name}_invalid_json") from None
    if not isinstance(result, dict):
        raise ValueError(f"reference_gpx_{name}_invalid_object")
    return result


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _timestamp(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError("timezone_missing")
        return stamp.astimezone(datetime_timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValueError("reference_gpx_checkpoint_timestamp_invalid") from None


def _clock(stamp: datetime | None, zone: ZoneInfo) -> str | None:
    return stamp.astimezone(zone).strftime("%H:%M:%S") if stamp is not None else None


def _anchor(day_id: str, day_index: int, kind: str, index: int, points, axis) -> dict:
    point = points[index]
    return {
        "anchor_id": f"{day_id}.{kind}",
        "label": f"Historical D{day_index} {kind}",
        "route_order_m": axis[index],
        "point_index": index,
        "lat": point.lat,
        "lon": point.lon,
    }


def _checkpoint_records(events: list, points, axis) -> list[dict]:
    records = []
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("reference_gpx_checkpoint_event_invalid")
        anchor_id = event.get("checkpoint_candidate_id")
        if not isinstance(anchor_id, str) or not anchor_id.strip() or anchor_id in seen:
            raise ValueError("reference_gpx_checkpoint_id_invalid_or_duplicate")
        seen.add(anchor_id)
        index = event.get("route_point_index")
        if type(index) is not int or not 0 <= index < len(points):
            raise ValueError(f"reference_gpx_checkpoint_index_mismatch:{anchor_id}")
        point = points[index]
        try:
            progress = float(event["progress_m"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError(f"reference_gpx_checkpoint_axis_invalid:{anchor_id}") from None
        if not math.isfinite(progress) or abs(progress - axis[index]) > CP_AXIS_TOLERANCE_M:
            raise ValueError(f"reference_gpx_checkpoint_axis_mismatch:{anchor_id}")
        if "lat" in event or "lon" in event:
            try:
                lat, lon = float(event["lat"]), float(event["lon"])
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ValueError(f"reference_gpx_checkpoint_coordinates_invalid:{anchor_id}") from None
            if not (
                math.isfinite(lat) and math.isfinite(lon)
                and abs(lat - point.lat) <= 0.000001
                and abs(lon - point.lon) <= 0.000001
            ):
                raise ValueError(f"reference_gpx_checkpoint_coordinates_mismatch:{anchor_id}")
        if _timestamp(event.get("observed_at")) != point.observed_at:
            raise ValueError(f"reference_gpx_checkpoint_timestamp_mismatch:{anchor_id}")
        records.append({
            "anchor_id": anchor_id,
            "label": str(event.get("label") or anchor_id),
            "route_order_m": axis[index],
            "point_index": index,
        })
    return sorted(records, key=lambda item: (item["point_index"], item["anchor_id"]))


def _checkpoint_window(record: dict, points, axis, zone, previous=None, day_end=None) -> dict:
    index = record["point_index"]
    stamp = points[index].observed_at
    previous_stamp = points[previous].observed_at if previous is not None else None
    minutes = (
        (stamp - previous_stamp).total_seconds() / 60
        if stamp is not None and previous_stamp is not None else None
    )
    distance = axis[index] - axis[previous] if previous is not None else None
    end_stamp = points[day_end].observed_at if day_end is not None else None
    return {
        **record,
        "arrival_clock": _clock(stamp, zone),
        "status": "exact" if stamp is not None else "unknown",
        "basis": "filtered_primary_checkpoint_point_timestamp" if stamp is not None
        else "filtered_primary_checkpoint_timestamp_missing",
        "from_previous_minutes": minutes,
        "from_previous_distance_m": distance,
        "from_previous_speed_kmh": distance / 1000 / (minutes / 60)
        if minutes is not None and minutes > 0 and distance is not None else None,
        "remaining_to_day_end_minutes": (end_stamp - stamp).total_seconds() / 60
        if stamp is not None and end_stamp is not None else None,
    }


def _rest_stops(day: dict, points, axis, zone: ZoneInfo) -> list[dict]:
    """A derived stay needs observations, not a long unobserved timestamp jump."""
    stops = []
    index, last = day["start_point_index"], day["end_point_index"]
    run_ends = [-1] * len(points)
    observed_seconds = [None] * len(points)
    cursor = index
    while cursor <= last:
        point = points[cursor]
        if point.observed_at is None:
            cursor += 1
            continue
        observed_seconds[cursor] = point.observed_at.timestamp()
        run_start = cursor
        run_end = cursor
        while run_end < last:
            current = points[run_end]
            following = points[run_end + 1]
            if following.observed_at is None:
                break
            observed_seconds[run_end + 1] = following.observed_at.timestamp()
            gap = (following.observed_at - current.observed_at).total_seconds()
            if not 0 < gap <= REST_MAX_OBSERVATION_GAP_SECONDS:
                break
            run_end += 1
        for position in range(run_start, run_end + 1):
            run_ends[position] = run_end
        cursor = run_end + 1
    while index < last:
        first = points[index]
        if first.observed_at is None:
            index += 1
            continue
        run_end = run_ends[index]
        if run_end < index or index + REST_MIN_POINTS - 1 > run_end:
            index += 1
            continue
        first_seconds = observed_seconds[index]
        if first_seconds is None:
            index += 1
            continue
        minimum_duration_index = bisect_left(
            observed_seconds,
            first_seconds + (REST_MIN_MINUTES * 60),
            lo=index,
            hi=run_end + 1,
        )
        if minimum_duration_index > run_end:
            index += 1
            continue
        if (
            haversine_m(
                first.lat,
                first.lon,
                points[minimum_duration_index].lat,
                points[minimum_duration_index].lon,
            )
            > REST_RADIUS_M
        ):
            index += 1
            continue
        end = index
        while end < last:
            following = points[end + 1]
            if following.observed_at is None:
                break
            gap = (following.observed_at - points[end].observed_at).total_seconds()
            if not 0 < gap <= REST_MAX_OBSERVATION_GAP_SECONDS:
                break
            if haversine_m(first.lat, first.lon, following.lat, following.lon) > REST_RADIUS_M:
                break
            end += 1
        minutes = (points[end].observed_at - first.observed_at).total_seconds() / 60
        net_distance = haversine_m(first.lat, first.lon, points[end].lat, points[end].lon)
        if (end - index + 1 >= REST_MIN_POINTS and minutes >= REST_MIN_MINUTES
                and net_distance / minutes <= REST_MAX_NET_SPEED_M_PER_MINUTE):
            cluster = points[index : end + 1]
            lat = sum(point.lat for point in cluster) / len(cluster)
            lon = sum(point.lon for point in cluster) / len(cluster)
            representative = min(
                range(index, end + 1),
                key=lambda pos: haversine_m(lat, lon, points[pos].lat, points[pos].lon),
            )
            stops.append({
                "stop_id": f"{day['day_id']}.stay.{index}.{end}",
                "label": f"Derived stay {len(stops) + 1}",
                "start_clock": _clock(first.observed_at, zone),
                "end_clock": _clock(points[end].observed_at, zone),
                "duration_minutes": minutes,
                "route_order_m": axis[representative],
                "point_index": representative,
                "start_point_index": index,
                "end_point_index": end,
                "point_count": end - index + 1,
                "lat": points[representative].lat,
                "lon": points[representative].lon,
                "status": "derived",
                "basis": "monotonic_filtered_primary_short_distance_observations",
                "semantic_rest_verified": False,
            })
            index = end + 1
        else:
            index += 1
    return stops


def _unknown_ranges(schedule: dict, axis: list[float]) -> list[dict]:
    spans = []
    seen = set()
    for item in [*schedule["quality_issues"], *schedule["unknown_ranges"]]:
        # Continuous midnight and other chronology annotations are not missing data.
        if item["reason"] in {"continuous_midnight_retained", "same_day_long_stop_retained"}:
            continue
        key = (item["reason"], item["start_point_index"], item["end_point_index"])
        if key in seen:
            continue
        seen.add(key)
        spans.append({
            **item,
            "start_route_order_m": axis[item["start_point_index"]],
            "end_route_order_m": axis[item["end_point_index"]],
            "point_count": item["end_point_index"] - item["start_point_index"] + 1,
        })
    return spans


def _route_points(points, axis, days: list[dict]) -> list[dict]:
    required = {0, len(points) - 1}
    required.update(day[kind]["point_index"] for day in days for kind in ("start", "end"))
    if len(required) > ROUTE_POINT_LIMIT:
        raise ValueError("reference_gpx_too_many_day_boundaries_for_route_display")
    slots = ROUTE_POINT_LIMIT - len(required)
    if len(points) <= ROUTE_POINT_LIMIT:
        selected = set(range(len(points)))
    elif slots > 1:
        selected = required | {
            round(index * (len(points) - 1) / (slots - 1)) for index in range(slots)
        }
    else:
        selected = required
    return [{"route_order_m": axis[i], "lat": points[i].lat, "lon": points[i].lon}
            for i in sorted(selected)]


def build_reference_gpx_reconstruction(project_root: Path, project: dict) -> dict | None:
    """Return hash-bound recorded evidence; a declared broken source fails closed."""
    if "reference_pace_energy_analysis_ref" not in project:
        return None
    root = project_root.resolve()
    pace_ref = project["reference_pace_energy_analysis_ref"]
    pace_bytes = _read_source(root, pace_ref, "pace_analysis")
    pace = _read_json(pace_bytes, "pace_analysis")
    historical = pace.get("historical_route_timing")
    cached = historical.get("daily_departures") if isinstance(historical, dict) else None
    if not isinstance(cached, dict):
        raise ValueError("reference_gpx_daily_departures_missing")
    try:
        zone = ZoneInfo(cached["timezone"])
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValueError("reference_gpx_timezone_invalid") from None
    schedule = build_historical_daily_departures(
        project_root=root, timezone=zone,
        timezone_source=str(cached.get("timezone_source") or "reference_pace_energy_analysis#timezone"),
    )
    if schedule["status"] != "ready":
        reason = schedule.get("reason") or "unknown"
        flags = ",".join(schedule.get("quality_flags", []))
        raise ValueError(f"reference_gpx_schedule_unavailable:{reason}:{flags}")
    if cached.get("source_ref") != schedule["source_ref"] or cached.get("source_sha256") != schedule["source_sha256"]:
        raise ValueError("reference_gpx_cached_schedule_source_mismatch")
    cached_days = cached.get("days")
    fields = ("day_id", "day_index", "start_point_index", "end_point_index", "start_distance_m", "end_distance_m")
    if not isinstance(cached_days, list) or [
        tuple(day.get(field) for field in fields) if isinstance(day, dict) else None for day in cached_days
    ] != [tuple(day[field] for field in fields) for day in schedule["days"]]:
        raise ValueError("reference_gpx_cached_day_boundaries_mismatch")
    source_ref = schedule["source_ref"]
    primary_bytes = _read_source(root, source_ref, "primary")
    if _sha256(primary_bytes) != schedule["source_sha256"]:
        raise ValueError("reference_gpx_primary_changed_during_read")
    points, _ = _parse_points(primary_bytes)
    axis = [0.0]
    for first, second in zip(points, points[1:]):
        axis.append(axis[-1] + haversine_m(first.lat, first.lon, second.lat, second.lon))
    cp_ref = project.get("checkpoint_events_ref")
    cp_bytes = _read_source(root, cp_ref, "checkpoint_events")
    events = _read_json(cp_bytes, "checkpoint_events").get("events")
    if not isinstance(events, list):
        raise ValueError("reference_gpx_checkpoint_events_missing")
    records = _checkpoint_records(events, points, axis)
    unknown = _unknown_ranges(schedule, axis)
    days, assigned = [], set()
    for day in schedule["days"]:
        start, end = day["start_point_index"], day["end_point_index"]
        checkpoints, previous = [], start
        for record in records:
            index = record["point_index"]
            if not start <= index <= end:
                continue
            checkpoints.append(_checkpoint_window(record, points, axis, zone, previous, end))
            assigned.add(record["anchor_id"])
            previous = index
        days.append({
            "day_index": day["day_index"],
            "source_day_id": day["day_id"],
            "start": _anchor(day["day_id"], day["day_index"], "start", start, points, axis),
            "end": _anchor(day["day_id"], day["day_index"], "end", end, points, axis),
            "departure_clock": _clock(points[start].observed_at, zone),
            "arrival_clock": _clock(points[end].observed_at, zone),
            "elapsed_minutes": (points[end].observed_at - points[start].observed_at).total_seconds() / 60,
            "rest_stops": _rest_stops(day, points, axis, zone),
            "checkpoint_windows": checkpoints,
            "unknown_ranges": [span for span in unknown
                               if span["reason"] != "overnight_recording_gap"
                               and span["start_point_index"] <= end
                               and span["end_point_index"] >= start],
            "candidate_only": True,
            "runtime_safety_truth": False,
        })
    overnight_gaps = []
    for gap in schedule["overnight_breaks"]:
        start, end = gap["start_point_index"], gap["end_point_index"]
        overnight_gaps.append({
            **gap,
            "start_clock": _clock(points[start].observed_at, zone),
            "end_clock": _clock(points[end].observed_at, zone),
            "duration_minutes": gap["preceding_gap_hours"] * 60,
            "recording_gap_distance_m": axis[end] - axis[start],
            "from_day_index": next((d["day_index"] for d in days if d["end"]["point_index"] == start), None),
            "to_day_index": next((d["day_index"] for d in days if d["start"]["point_index"] == end), None),
            "basis": "recorded_overnight_time_and_distance_gap",
        })
    source_refs = [source_ref, pace_ref, cp_ref]
    return {
        "schema_version": "reference_gpx_reconstruction.v1",
        "policy_version": "1",
        "source_ref": source_ref,
        "source_sha256": schedule["source_sha256"],
        "source_refs": source_refs,
        "source_hashes": dict(zip(source_refs, map(_sha256, (primary_bytes, pace_bytes, cp_bytes)))),
        "timezone": zone.key,
        "route_length_m": axis[-1],
        "source_point_count": len(points),
        "timed_point_count": schedule["counts"]["timed_point_count"],
        "route_points": _route_points(points, axis, days),
        "days": days,
        "overnight_gaps": overnight_gaps,
        "unknown_ranges": unknown,
        "unassigned_checkpoint_windows": [
            _checkpoint_window(record, points, axis, zone)
            for record in records if record["anchor_id"] not in assigned
        ],
        "policy": {
            "source_selection": "single_filtered_primary_no_expedition_pooling",
            "day_partition": "recomputed_historical_daily_departures",
            "daily_departures_policy": schedule["policy"],
            "route_axis": schedule["route_axis"],
            "point_index_basis": "zero_based_flattened_trackpoints_in_document_order",
            "checkpoint_timing": "exact_filtered_point_no_interpolation",
            "pace_basis": "elapsed_between_adjacent_recorded_checkpoints_including_stays",
            "unknown_checkpoint_timing": "null_and_interrupt_adjacent_timing_chain",
            "day_end_selection_origin": "reference_evidence",
            "overnight_recording_gaps": "preserve_exact_endpoints_without_filling",
            "rest_detection": {
                "status": "derived_stay_not_verified_rest",
                "radius_from_first_point_m": REST_RADIUS_M,
                "minimum_point_count": REST_MIN_POINTS,
                "minimum_duration_minutes": REST_MIN_MINUTES,
                "maximum_net_speed_m_per_minute": REST_MAX_NET_SPEED_M_PER_MINUTE,
                "maximum_adjacent_observation_gap_seconds": REST_MAX_OBSERVATION_GAP_SECONDS,
                "strictly_increasing_timestamps_required": True,
                "missing_timestamp_breaks_cluster": True,
                "single_historical_day_only": True,
            },
            "route_display_point_limit": ROUTE_POINT_LIMIT,
            "route_display_preserves_day_boundary_points": True,
            "authority": "candidate_recorded_evidence_only",
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
        "writes_performed": False,
    }
