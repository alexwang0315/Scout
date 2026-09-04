"""Historical directional timing and moving-day capacity, never live deadlines."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def historical_timezone(project: dict, daylight: dict) -> tuple[ZoneInfo, str]:
    for value, source in (
        (project.get("timezone"), "project.json#timezone"),
        (daylight.get("timezone"), "weather_daylight_evidence#timezone"),
        ((daylight.get("daylight") or {}).get("timezone"), "weather_daylight_evidence#daylight.timezone"),
    ):
        if isinstance(value, str):
            try:
                return ZoneInfo(value), source
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return ZoneInfo("UTC"), "utc_fallback"


def moving_interval_days(
    start: datetime, end: datetime, local_timezone: ZoneInfo
) -> dict[str, float]:
    """Split an already eligible movement interval at local midnight."""
    result: dict[str, float] = {}
    cursor = start.astimezone(local_timezone)
    end = end.astimezone(local_timezone)
    while cursor.timestamp() < end.timestamp():
        midnight = datetime.combine(
            cursor.date() + timedelta(days=1), time.min, tzinfo=local_timezone
        )
        boundary = min(midnight, end)
        result[cursor.date().isoformat()] = boundary.timestamp() - cursor.timestamp()
        cursor = boundary
    return result


def build_historical_day_budget(
    tracks: list[dict], *, timezone_name: str, timezone_source: str
) -> dict[str, Any]:
    seen: set[str] = set()
    samples: list[float] = []
    sources: list[str] = []
    duplicate_count = 0
    for track in tracks:
        source_id = str(track.get("source_id") or "")
        analysis = track.get("analysis_source") or {}
        digest = str(analysis.get("sha256") or track.get("sha256") or source_id)
        if digest in seen:
            duplicate_count += 1
            continue
        seen.add(digest)
        values = [
            value for item in track.get("daily_moving_minutes", [])
            if (value := _positive_number(item)) is not None
        ]
        if values:
            samples.extend(values)
            sources.append(source_id)
    return {
        "status": "available" if samples else "unavailable",
        "basis": "median_historical_local_day_eligible_moving_minutes",
        "minutes": round(statistics.median(samples), 3) if samples else None,
        "mean_minutes": round(statistics.fmean(samples), 3) if samples else None,
        "minimum_minutes": round(min(samples), 3) if samples else None,
        "maximum_minutes": round(max(samples), 3) if samples else None,
        "sample_day_count": len(samples),
        "distinct_source_count": len(sources),
        "duplicate_source_count": duplicate_count,
        "source_ids": sources,
        "timezone": timezone_name,
        "timezone_source": timezone_source,
        "movement_scope": "complete_source_gpx_speed_eligible_adjacent_pairs",
        "live_remaining_day_budget": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def build_directional_route_timing(
    traversals: list[dict], *, route_distance_m: float, route_bin_m: float,
    bin_grades: list[float | None], grade_band: Callable[[dict], str],
) -> dict[str, Any]:
    """Prefer local directional observations, then other-bin signed-grade cohorts."""
    by_bin: dict[tuple[int, str], list[dict]] = defaultdict(list)
    cohorts: dict[str, list[dict]] = defaultdict(list)
    source_for_hash: dict[str, str] = {}
    for item in traversals:
        source = str(item.get("source_id") or "")
        digest = str(item.get("source_sha256") or source)
        if source_for_hash.setdefault(digest, source) != source:
            continue
        index = int(item["route_bin_index"])
        direction = item.get("direction")
        duration = _positive_number(item.get("duration_seconds"))
        distance = _positive_number(item.get("route_progress_distance_m"))
        if duration is None or distance is None or direction not in {"forward", "reverse"}:
            continue
        sample = {
            "bin_index": index, "source_id": source,
            "seconds_per_m": duration / distance,
        }
        by_bin[index, direction].append(sample)
        if 0 <= index < len(bin_grades) and bin_grades[index] is not None:
            signed_grade = bin_grades[index] * (1 if direction == "forward" else -1)
            cohorts[grade_band({"signed_grade_ratio": signed_grade})].append(sample)
    bins = []
    for index in range(math.ceil(route_distance_m / route_bin_m)):
        start = index * route_bin_m
        end = min(route_distance_m, start + route_bin_m)
        canonical_grade = bin_grades[index] if index < len(bin_grades) else None
        timings = {}
        for direction, sign in (("forward", 1), ("reverse", -1)):
            target_grade = canonical_grade * sign if canonical_grade is not None else None
            band = grade_band({"signed_grade_ratio": target_grade}) if target_grade is not None else None
            samples = by_bin[index, direction]
            observed = bool(samples)
            if not samples and band is not None:
                samples = [sample for sample in cohorts[band] if sample["bin_index"] != index]
            status = "observed" if observed else "estimated" if samples else "unavailable"
            timings[direction] = {
                "status": status,
                "average_minutes": round(
                    statistics.fmean(sample["seconds_per_m"] for sample in samples)
                    * (end - start) / 60.0, 6
                ) if samples else None,
                "sample_count": len(samples),
                "distinct_source_count": len({sample["source_id"] for sample in samples}),
                "source_ids": sorted({sample["source_id"] for sample in samples}),
                "signed_grade_ratio": target_grade,
                "grade_band": band,
                "method": "directional_bin_mean_pace" if observed else (
                    "other_bin_same_signed_grade_mean_pace" if samples else "missing_directional_evidence"
                ),
            }
        bins.append({
            "start_distance_m": start, "end_distance_m": end, **timings,
        })
    return {
        "schema_version": "historical_directional_timing.v1",
        "route_distance_m": route_distance_m,
        "bins": bins,
        "counts": {
            f"{direction}_{status}_bin_count": sum(item[direction]["status"] == status for item in bins)
            for direction in ("forward", "reverse")
            for status in ("observed", "estimated", "unavailable")
        },
        "policy": {
            "direct_directional_samples_first": True,
            "estimate_basis": "other_route_bins_matching_reversed_signed_grade_band",
            "grade_band_boundaries": [-0.15, -0.05, 0.05, 0.15],
            "missing_terrain_is_not_flat": True,
            "outbound_duration_reused_for_return": False,
            "duplicate_source_sha256_counted_once": True,
            "duration_estimator": "arithmetic_mean_seconds_per_route_meter_times_bin_length",
            "partial_bin_cost": "proportional_to_interval_overlap",
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None
