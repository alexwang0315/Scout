"""Candidate-only Body Index analysis for local HealthExport archives.

The module deliberately keeps the HealthExport time series local.  It exports
aggregate observations and model estimates, never raw timestamps, coordinates,
provider identifiers, or the original payload.  The output is a reference for
the Body Index UI; it is not medical advice, route authority, or runtime safety
truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import zipfile
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "scout_body_index.v1"
DEFAULT_BODY_MASS_KG = 70.0
GRADE_FRACTION = 0.0
MAX_SAMPLE_GAP_SECONDS = 180.0
MIN_SEGMENT_SECONDS = 10.0
ENERGY_COVERAGE_THRESHOLD = 0.80
GAP_MULTIPLIER = 3.0
MIN_GAP_SECONDS = 10.0
SUSTAINED_WINDOWS_SECONDS = (300, 600, 900, 1200)
KJ_PER_KCAL = 4.184
WALKING_MIN_MPS = 50.0 / 60.0
WALKING_MAX_MPS = 100.0 / 60.0
RUNNING_ACCURATE_MPS = 134.0 / 60.0


@dataclass(frozen=True)
class _Point:
    timestamp: datetime
    value: float
    units: str


@dataclass(frozen=True)
class _Interval:
    start: float
    end: float
    value: float


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _parse_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        text = value.strip().replace("\u00a0", " ")
        result = None
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                result = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if result is None:
            try:
                result = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result


def _local_date(value: datetime) -> str:
    return value.date().isoformat()


def _unit_factor_to_kj(units: str) -> float | None:
    normalized = units.strip().lower().replace(" ", "")
    if normalized in {"kj", "kilojoule", "kilojoules"}:
        return 1.0
    if normalized in {"kcal", "kilocalorie", "kilocalories"}:
        return KJ_PER_KCAL
    if normalized in {"j", "joule", "joules"}:
        return 0.001
    if normalized in {"wh", "watt-hour", "watthour", "watt_hours"}:
        return 3.6
    return None


def _unit_factor_to_km(units: str) -> float | None:
    normalized = units.strip().lower().replace(" ", "")
    if normalized in {"km", "kilometer", "kilometers"}:
        return 1.0
    if normalized in {"m", "meter", "meters"}:
        return 0.001
    if normalized in {"mi", "mile", "miles"}:
        return 1.609344
    return None


def _points(value: Any) -> list[_Point]:
    if not isinstance(value, list):
        return []
    result: list[_Point] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        timestamp = _parse_date(item.get("date") or item.get("startDate"))
        raw_number = item.get("qty")
        if raw_number is None:
            raw_number = item.get("value")
        if raw_number is None:
            raw_number = item.get("Avg")
        if raw_number is None:
            raw_number = item.get("average")
        if raw_number is None:
            raw_number = item.get("mean")
        number = _finite(raw_number)
        if timestamp is None or number is None:
            continue
        result.append(_Point(timestamp, number, str(item.get("units") or "")))
    result.sort(key=lambda point: point.timestamp)
    # A duplicate point can appear when an export contains both a summary and
    # an interval record.  Identical records are the same observation.
    deduped: list[_Point] = []
    seen: set[tuple[datetime, float, str]] = set()
    for point in result:
        key = (point.timestamp, round(point.value, 12), point.units.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(point)
    return deduped


def _scalar(value: Any) -> tuple[float, str] | None:
    if not isinstance(value, Mapping):
        return None
    number = _finite(value.get("qty", value.get("value")))
    if number is None:
        return None
    return number, str(value.get("units") or "")


def _json_members(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".json")]
        payloads: list[dict[str, Any]] = []
        for name in members:
            raw = json.loads(archive.read(name).decode("utf-8"))
            if isinstance(raw, Mapping):
                data = raw.get("data", raw)
                if isinstance(data, Mapping):
                    payloads.append(dict(data))
        return payloads


def _activity_kind(name: Any) -> str:
    text = str(name or "").strip().lower()
    if any(token in text for token in ("跑", "run", "jog")):
        return "running"
    if any(token in text for token in ("步", "walk", "hike", "trek", "健行", "登山")):
        return "walking"
    if any(token in text for token in ("皮拉提斯", "pilates")):
        return "other"
    return "other"


def _series_intervals(
    points: Sequence[_Point],
    origin: datetime,
    finish: datetime,
    *,
    factor: float = 1.0,
    minimum_interval: float = 0.25,
) -> list[_Interval]:
    if not points:
        return []
    offsets = [max(0.0, (point.timestamp - origin).total_seconds()) for point in points]
    positive_deltas = [b - a for a, b in zip(offsets, offsets[1:]) if b > a]
    nominal = statistics.median(positive_deltas) if positive_deltas else 1.0
    nominal = max(minimum_interval, min(nominal, MAX_SAMPLE_GAP_SECONDS))
    end_offset = max(0.0, (finish - origin).total_seconds())
    intervals: list[_Interval] = []
    for index, point in enumerate(points):
        start = offsets[index]
        if index + 1 < len(offsets) and offsets[index + 1] > start:
            observed_delta = offsets[index + 1] - start
        else:
            observed_delta = nominal
        # A missing sample gap is not evidence that the preceding interval
        # lasted until the next record.  Keep the interval quantity but only
        # assign nominal coverage across such a gap.
        gap_threshold = max(MIN_GAP_SECONDS, nominal * GAP_MULTIPLIER)
        duration = observed_delta if observed_delta <= gap_threshold else nominal
        stop = min(end_offset, start + max(minimum_interval, duration))
        if stop <= start:
            continue
        intervals.append(_Interval(start, stop, point.value * factor))
    return intervals


def _lookup_interval(intervals: Sequence[_Interval], position: float) -> _Interval | None:
    if not intervals:
        return None
    starts = [item.start for item in intervals]
    index = bisect_right(starts, position) - 1
    if index < 0:
        return None
    item = intervals[index]
    return item if item.start <= position < item.end + 1e-9 else None


def _overlap_value(intervals: Sequence[_Interval], start: float, end: float) -> tuple[float, float]:
    """Return interval energy and covered seconds without multiplying energy by time.

    Energy samples are interval quantities.  When another series splits one
    interval, the already reported interval quantity is apportioned by overlap
    solely to preserve the original sum; it is never treated as a rate.
    """
    if not intervals or end <= start:
        return 0.0, 0.0
    total = 0.0
    covered = 0.0
    for item in intervals:
        left = max(start, item.start)
        right = min(end, item.end)
        if right <= left:
            continue
        duration = item.end - item.start
        if duration <= 0:
            continue
        fraction = (right - left) / duration
        total += item.value * fraction
        covered += right - left
    return total, covered


def _calendar_boundary_offsets(origin: datetime, finish: datetime) -> list[float]:
    """Return local-midnight offsets inside an activity without exposing timestamps."""
    boundaries: list[float] = []
    current_date = origin.date() + timedelta(days=1)
    while True:
        midnight = datetime.combine(current_date, datetime.min.time(), tzinfo=origin.tzinfo)
        offset = (midnight - origin).total_seconds()
        if offset >= (finish - origin).total_seconds():
            break
        if offset > 0:
            boundaries.append(offset)
        current_date += timedelta(days=1)
    return boundaries


def _energy_by_local_date(
    intervals: Sequence[_Interval],
    origin: datetime,
    finish: datetime,
    *,
    scalar_kj: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Split interval energy at local midnight; never multiply an interval value by time."""
    output: dict[str, dict[str, Any]] = {}
    if not intervals:
        if scalar_kj is not None:
            output[_local_date(origin)] = {
                "all_active_energy_kj": _round(scalar_kj, 5),
                "energy_coverage_s": 0.0,
                "allocation_status": "scalar_activity_start_date_fallback",
            }
        return output
    for item in intervals:
        cursor = item.start
        while cursor < item.end - 1e-9:
            current = origin + timedelta(seconds=cursor)
            next_midnight = datetime.combine(
                current.date() + timedelta(days=1),
                datetime.min.time(),
                tzinfo=origin.tzinfo,
            )
            midnight_offset = (next_midnight - origin).total_seconds()
            right = min(item.end, midnight_offset)
            if right <= cursor:
                right = item.end
            fraction = (right - cursor) / (item.end - item.start)
            day = _local_date(current)
            bucket = output.setdefault(
                day,
                {
                    "all_active_energy_kj": 0.0,
                    "energy_coverage_s": 0.0,
                    "allocation_status": "interval_time_aligned",
                },
            )
            bucket["all_active_energy_kj"] += item.value * fraction
            bucket["energy_coverage_s"] += right - cursor
            cursor = right
    for bucket in output.values():
        bucket["all_active_energy_kj"] = _round(float(bucket["all_active_energy_kj"]), 5)
        bucket["energy_coverage_s"] = _round(float(bucket["energy_coverage_s"]), 1)
    return output


def _median(values: Iterable[float]) -> float | None:
    population = [value for value in values if math.isfinite(value)]
    return statistics.median(population) if population else None


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _activity_fingerprint(workout: Mapping[str, Any], kind: str) -> str:
    start = _parse_date(workout.get("start"))
    end = _parse_date(workout.get("end"))
    distance = _scalar(workout.get("distance"))
    identifier = str(
        workout.get("id")
        or workout.get("uuid")
        or workout.get("workout_id")
        or ""
    ).strip()
    if identifier:
        # A provider may revise the scalar summary between exports.  The
        # stable workout identifier is the stronger duplicate key, so energy
        # must not make the same activity appear twice.
        payload = {"kind": kind, "id": identifier}
    else:
        payload = {
            "kind": kind,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "duration": _round(_finite(workout.get("duration")), 3),
            "distance": (_round(distance[0], 6), distance[1]) if distance else None,
        }
    # The fallback fields keep old exports deduplicable when IDs were omitted.
    return _sha(payload)


def _normalize_energy_points(points: Sequence[_Point]) -> tuple[list[_Point], str]:
    normalized: list[_Point] = []
    unknown_units = False
    for point in points:
        factor = _unit_factor_to_kj(point.units)
        if factor is None:
            unknown_units = True
            continue
        if point.value < 0:
            continue
        normalized.append(_Point(point.timestamp, point.value * factor, "kJ"))
    return normalized, "unknown" if unknown_units and not normalized else "validated"


def _normalize_distance_points(points: Sequence[_Point]) -> list[_Point]:
    normalized: list[_Point] = []
    for point in points:
        factor = _unit_factor_to_km(point.units)
        if factor is not None and point.value >= 0:
            normalized.append(_Point(point.timestamp, point.value * factor, "km"))
    return normalized


def _normalize_hr_points(points: Sequence[_Point]) -> list[_Point]:
    return [point for point in points if 20 <= point.value <= 260]


def _safe_body_mass(value: float | int | None) -> float:
    mass = _finite(value)
    if mass is None or mass <= 0 or mass > 500:
        raise ValueError("body_mass_kg must be a finite value between 0 and 500")
    return mass


def flat_ground_metabolic_cost(
    speed_mps: float,
    mode: str,
    *,
    body_mass_kg: float = DEFAULT_BODY_MASS_KG,
    grade: float = GRADE_FRACTION,
) -> dict[str, Any]:
    """Estimate active metabolic energy cost using the ACSM equations.

    The equations produce gross VO2.  Body Index compares their net active
    component with Apple activeEnergy, so the 3.5 mL/kg/min resting component
    is explicitly removed.  This is a model cross-check, not a replacement for
    the provider estimate and not mechanical output.
    """
    mass = _safe_body_mass(body_mass_kg)
    speed = _finite(speed_mps)
    if speed is None or speed <= 0:
        return {"status": "unavailable", "reason": "speed_unavailable"}
    normalized_mode = "running" if mode == "running" else "walking"
    speed_mpm = speed * 60.0
    if normalized_mode == "walking":
        applicable = WALKING_MIN_MPS <= speed <= WALKING_MAX_MPS
        horizontal_coefficient = 0.1
        grade_coefficient = 1.8
        applicability = "ACSM walking equation most accurate at 50-100 m/min"
    else:
        applicable = speed >= RUNNING_ACCURATE_MPS
        horizontal_coefficient = 0.2
        grade_coefficient = 0.9
        applicability = (
            "ACSM running equation is most accurate above 134 m/min; "
            "running observations below that speed remain outside the validated range"
        )
    gross_vo2 = horizontal_coefficient * speed_mpm + grade_coefficient * speed_mpm * grade + 3.5
    net_vo2 = max(0.0, gross_vo2 - 3.5)
    kcal_min = (net_vo2 * mass / 1000.0) * 5.0
    watts = kcal_min * 4184.0 / 60.0
    return {
        "status": "available" if applicable else "outside_validated_speed_range",
        "mode": normalized_mode,
        "speed_mps": _round(speed, 4),
        "speed_m_per_min": _round(speed_mpm, 2),
        "grade_fraction": grade,
        "body_mass_kg": mass,
        "body_mass_basis": "user_assumption",
        "gross_vo2_ml_kg_min": _round(gross_vo2, 3),
        "net_active_vo2_ml_kg_min": _round(net_vo2, 3),
        "estimated_active_energy_kcal_min": _round(kcal_min, 4),
        "estimated_active_energy_w": _round(watts, 2),
        "resting_component_excluded": True,
        "formula": (
            "walking: VO2=0.1*S+1.8*S*grade+3.5; "
            "running: VO2=0.2*S+0.9*S*grade+3.5; "
            "S=m/min; kcal/min=VO2_net*mass/1000*5"
        ),
        "source": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12419060/",
        "applicability": applicability,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _classify_frame(
    *,
    speed_mps: float | None,
    cadence_spm: float | None,
    heart_rate: float | None,
    heart_rate_change: float | None,
    activity_kind: str,
    previous_state: str | None,
) -> tuple[str, float, list[str]]:
    if speed_mps is None and cadence_spm is None:
        return "unknown", 0.15, ["speed_and_cadence_missing"]
    basis: list[str] = []
    run_enter_speed = 2.10
    run_exit_speed = 1.80
    run_enter_cadence = 150.0
    run_exit_cadence = 135.0
    speed_is_zero = speed_mps is not None and speed_mps <= 0.12
    cadence_is_zero = cadence_spm is not None and cadence_spm <= 30.0
    if speed_is_zero and (cadence_spm is None or cadence_is_zero):
        basis.append("speed_zero" if speed_is_zero else "cadence_low")
        if cadence_spm is not None:
            basis.append("cadence_low")
        return "stop", 0.78, basis
    run_threshold_speed = run_exit_speed if previous_state == "running" else run_enter_speed
    run_threshold_cadence = run_exit_cadence if previous_state == "running" else run_enter_cadence
    speed_run = speed_mps is not None and speed_mps >= run_threshold_speed
    cadence_run = cadence_spm is not None and cadence_spm >= run_threshold_cadence
    if speed_run or cadence_run:
        if speed_run:
            basis.append("speed_run_threshold")
        if cadence_run:
            basis.append("cadence_run_threshold")
        if activity_kind == "running":
            basis.append("activity_name_prior_only")
        if heart_rate is not None:
            basis.append("heart_rate_support" if heart_rate >= 110 else "heart_rate_observed")
        if heart_rate_change is not None and abs(heart_rate_change) >= 3:
            basis.append("heart_rate_change_support")
        confidence = 0.86 if speed_run and cadence_run else 0.72
        if heart_rate is not None and heart_rate >= 110:
            confidence += 0.04
        if heart_rate_change is not None and abs(heart_rate_change) >= 3:
            confidence += 0.02
        return "running", min(0.95, confidence), basis
    walk_speed = speed_mps is not None and speed_mps >= 0.12
    walk_cadence = cadence_spm is not None and cadence_spm >= 30.0
    if walk_speed or walk_cadence:
        if walk_speed:
            basis.append("speed_walk_threshold")
        if walk_cadence:
            basis.append("cadence_walk_threshold")
        if activity_kind == "walking":
            basis.append("activity_name_prior_only")
        if heart_rate is not None:
            basis.append("heart_rate_observed")
        if heart_rate_change is not None and heart_rate_change <= -3:
            basis.append("heart_rate_recovery_observed")
        return "walking", 0.78 if walk_speed and walk_cadence else 0.65, basis
    if speed_mps is not None or cadence_spm is not None:
        basis.append("low_speed_or_cadence")
        return "stop", 0.68, basis
    return "unknown", 0.20, ["classification_insufficient"]


def _merge_short_labels(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not labels:
        return labels
    result = labels[:]
    changed = True
    while changed:
        changed = False
        runs: list[tuple[int, int, str]] = []
        start = 0
        for index in range(1, len(result) + 1):
            if index == len(result) or result[index]["state"] != result[start]["state"]:
                runs.append((start, index, result[start]["state"]))
                start = index
        for run_index, (left, right, state) in enumerate(runs):
            duration = sum(result[item]["duration_s"] for item in range(left, right))
            if state == "unknown" or duration >= MIN_SEGMENT_SECONDS:
                continue
            previous = runs[run_index - 1][2] if run_index else None
            following = runs[run_index + 1][2] if run_index + 1 < len(runs) else None
            replacement = previous if previous and previous != "unknown" else following
            if replacement is None or replacement == "unknown":
                continue
            for item in range(left, right):
                result[item]["state"] = replacement
                result[item]["basis"].append("minimum_duration_smoothing")
                result[item]["confidence"] = min(result[item]["confidence"], 0.62)
            changed = True
            break
    return result


def _activity_analysis(workout: Mapping[str, Any], body_mass_kg: float) -> dict[str, Any]:
    kind = _activity_kind(workout.get("name"))
    start = _parse_date(workout.get("start"))
    end = _parse_date(workout.get("end"))
    duration = _finite(workout.get("duration"))
    if start is None:
        raise ValueError("workout start is unavailable")
    if end is None and duration is not None and duration > 0:
        end = start + timedelta(seconds=duration)
    if end is None or end <= start:
        raise ValueError("workout end is unavailable")
    duration = max(0.0, (end - start).total_seconds())
    activity_key = _activity_fingerprint(workout, kind)
    energy_points, energy_unit_status = _normalize_energy_points(_points(workout.get("activeEnergy")))
    scalar_energy = _scalar(workout.get("activeEnergyBurned"))
    scalar_kj = None
    if scalar_energy:
        factor = _unit_factor_to_kj(scalar_energy[1])
        if factor is not None and scalar_energy[0] >= 0:
            scalar_kj = scalar_energy[0] * factor
    distance_points = _normalize_distance_points(
        _points(workout.get("walkingAndRunningDistance"))
        or _points(workout.get("distanceData"))
    )
    step_points = _points(workout.get("stepCount"))
    heart_points = _normalize_hr_points(
        _points(workout.get("heartRateData"))
        or _points(workout.get("heartRate"))
    )
    origin = start
    finish = end
    distance_intervals = _series_intervals(distance_points, origin, finish, factor=1000.0)
    step_intervals = _series_intervals(step_points, origin, finish)
    energy_intervals = _series_intervals(energy_points, origin, finish)
    distance_speed_intervals = [
        _Interval(item.start, item.end, item.value / max(0.001, item.end - item.start))
        for item in distance_intervals
    ]
    cadence_intervals = [
        _Interval(item.start, item.end, item.value * 60.0 / max(0.001, item.end - item.start))
        for item in step_intervals
    ]
    hr_values = [(max(0.0, (point.timestamp - origin).total_seconds()), point.value) for point in heart_points]
    hr_positions = [item[0] for item in hr_values]
    energy_total_kj = sum(item.value for item in energy_intervals)
    energy_coverage_seconds = sum(item.end - item.start for item in energy_intervals)
    if not energy_intervals and scalar_kj is not None:
        energy_total_kj = scalar_kj
        energy_coverage_seconds = 0.0
        energy_unit_status = "validated_scalar_fallback"

    if kind == "other":
        daily_energy_by_date = _energy_by_local_date(
            energy_intervals,
            origin,
            finish,
            scalar_kj=scalar_kj if not energy_intervals else None,
        )
        return {
            "activity_ref": activity_key[:16],
            "activity_key": activity_key,
            "activity_kind": kind,
            "date": _local_date(start),
            "duration_s": _round(duration, 1),
            "active_energy_kj": _round(energy_total_kj, 5),
            "active_energy_kcal": _round(energy_total_kj / KJ_PER_KCAL, 5),
            "active_energy_coverage_s": _round(energy_coverage_seconds, 1),
            "active_energy_allocation_status": (
                "interval_time_aligned"
                if energy_intervals
                else "scalar_activity_start_date_fallback"
                if scalar_kj is not None
                else "unavailable"
            ),
            "energy_unit_status": energy_unit_status,
            "segments": [],
            "transition_events": [],
            "sustained_windows": [],
            "daily_energy_by_date": daily_energy_by_date,
            "data_coverage": {"speed": 0.0, "cadence": 0.0, "heart_rate": 0.0, "energy": _round(energy_coverage_seconds / duration if duration else 0.0, 4)},
            "classification_status": "not_applicable",
            "note": "Non-running/walking workout retained for daily all-activity denominator; no gait classification inferred.",
        }

    boundaries = {0.0, duration}
    for intervals in (distance_intervals, step_intervals, energy_intervals):
        for item in intervals:
            boundaries.add(max(0.0, min(duration, item.start)))
    for position, _ in hr_values:
        boundaries.add(max(0.0, min(duration, position)))
    boundaries.update(_calendar_boundary_offsets(origin, finish))
    ordered = sorted(boundaries)
    frame_labels: list[dict[str, Any]] = []
    frames: list[dict[str, Any]] = []
    previous_state: str | None = None
    previous_heart_rate: float | None = None
    for left, right in zip(ordered, ordered[1:]):
        frame_duration = right - left
        if frame_duration <= 0:
            continue
        distance_interval = _lookup_interval(distance_speed_intervals, left + 1e-8)
        cadence_interval = _lookup_interval(cadence_intervals, left + 1e-8)
        speed = distance_interval.value if distance_interval else None
        cadence = cadence_interval.value if cadence_interval else None
        if hr_positions:
            hr_index = min(len(hr_positions) - 1, max(0, bisect_left(hr_positions, (left + right) / 2.0)))
            candidates = [hr_index]
            if hr_index > 0:
                candidates.append(hr_index - 1)
            nearest_index = min(candidates, key=lambda index: abs(hr_positions[index] - (left + right) / 2.0))
            nearest_distance = abs(hr_positions[nearest_index] - (left + right) / 2.0)
            hr = hr_values[nearest_index][1] if nearest_distance <= 90.0 else None
        else:
            hr = None
        heart_rate_change = (
            hr - previous_heart_rate
            if hr is not None and previous_heart_rate is not None
            else None
        )
        energy_kj, energy_seconds = _overlap_value(energy_intervals, left, right)
        gap = frame_duration > MAX_SAMPLE_GAP_SECONDS
        if gap:
            state, confidence, basis = "unknown", 0.10, ["data_gap_not_stop"]
        else:
            state, confidence, basis = _classify_frame(
                speed_mps=speed,
                cadence_spm=cadence,
                heart_rate=hr,
                heart_rate_change=heart_rate_change,
                activity_kind=kind,
                previous_state=previous_state,
            )
        frame = {
            "start": left,
            "end": right,
            "duration_s": frame_duration,
            "state": state,
            "confidence": confidence,
            "basis": basis,
            "speed_mps": speed,
            "cadence_spm": cadence,
            "heart_rate": hr,
            "energy_kj": energy_kj,
            "energy_covered_s": energy_seconds,
        }
        frames.append(frame)
        frame_labels.append(frame)
        if state != "unknown":
            previous_state = state
        if hr is not None:
            previous_heart_rate = hr
    _merge_short_labels(frame_labels)
    frames = frame_labels

    segments: list[dict[str, Any]] = []
    index = 0
    while index < len(frames):
        state = frames[index]["state"]
        end_index = index + 1
        while end_index < len(frames) and frames[end_index]["state"] == state:
            end_index += 1
        group = frames[index:end_index]
        segment_duration = sum(item["duration_s"] for item in group)
        speed_values = [item["speed_mps"] for item in group if item["speed_mps"] is not None]
        cadence_values = [item["cadence_spm"] for item in group if item["cadence_spm"] is not None]
        heart_values = [item["heart_rate"] for item in group if item["heart_rate"] is not None]
        energy_kj = sum(item["energy_kj"] for item in group)
        energy_seconds = sum(item["energy_covered_s"] for item in group)
        coverage_speed = sum(item["duration_s"] for item in group if item["speed_mps"] is not None) / segment_duration if segment_duration else 0.0
        coverage_cadence = sum(item["duration_s"] for item in group if item["cadence_spm"] is not None) / segment_duration if segment_duration else 0.0
        coverage_hr = sum(item["duration_s"] for item in group if item["heart_rate"] is not None) / segment_duration if segment_duration else 0.0
        basis = sorted({part for item in group for part in item["basis"]})
        segment_ref = _sha([activity_key, index, state, round(segment_duration, 2)])[:16]
        speed_median = _median(speed_values)
        theoretical = (
            flat_ground_metabolic_cost(speed_median, state, body_mass_kg=body_mass_kg)
            if state in {"running", "walking"} and speed_median is not None
            else {"status": "unavailable", "reason": "state_or_speed_unavailable"}
        )
        segments.append(
            {
                "segment_ref": segment_ref,
                "state": state,
                "start_offset_min": _round(frames[index]["start"] / 60.0, 2),
                "end_offset_min": _round(frames[end_index - 1]["end"] / 60.0, 2),
                "duration_s": _round(segment_duration, 1),
                "confidence": _round(statistics.mean(item["confidence"] for item in group), 3),
                "classification_basis": basis,
                "speed_mps_median": _round(speed_median, 4),
                "cadence_spm_median": _round(_median(cadence_values), 2),
                "heart_rate_bpm_median": _round(_median(heart_values), 1),
                "active_energy_kj": _round(energy_kj, 5),
                "active_energy_kcal": _round(energy_kj / KJ_PER_KCAL, 5),
                "active_energy_rate_w": _round(energy_kj * 1000.0 / energy_seconds, 2) if energy_seconds else None,
                "data_coverage": {
                    "speed": _round(coverage_speed, 4),
                    "cadence": _round(coverage_cadence, 4),
                    "heart_rate": _round(coverage_hr, 4),
                    "active_energy": _round(energy_seconds / segment_duration if segment_duration else 0.0, 4),
                },
                "theoretical_flat_energy_cost": theoretical,
                "_frame_start": index,
                "_frame_end": end_index,
            }
        )
        index = end_index

    transition_events: list[dict[str, Any]] = []
    comparable_watch_energy_kj = 0.0
    comparable_model_energy_kj = 0.0
    comparable_watch_coverage_s = 0.0
    comparable_duration_s = 0.0
    comparable_segment_refs: list[str] = []
    for segment in segments:
        if segment["state"] not in {"running", "walking"}:
            continue
        theoretical = segment.get("theoretical_flat_energy_cost") or {}
        if theoretical.get("status") != "available":
            continue
        estimated_w = _finite(theoretical.get("estimated_active_energy_w"))
        segment_duration = _finite(segment.get("duration_s"))
        if estimated_w is None or segment_duration is None or segment_duration <= 0:
            continue
        comparable_segment_refs.append(str(segment["segment_ref"]))
        comparable_model_energy_kj += estimated_w * segment_duration / 1000.0
        comparable_watch_energy_kj += float(segment.get("active_energy_kj") or 0.0)
        comparable_watch_coverage_s += float(
            segment.get("data_coverage", {}).get("active_energy") or 0.0
        ) * segment_duration
        comparable_duration_s += segment_duration
    cross_check_status = (
        "available"
        if energy_intervals and comparable_segment_refs and comparable_model_energy_kj > 0
        else "unavailable"
    )
    energy_cross_check = {
        "status": cross_check_status,
        "watch_interval_active_energy_kj_on_comparable_segments": _round(
            comparable_watch_energy_kj, 5
        )
        if cross_check_status == "available"
        else None,
        "flat_ground_model_active_energy_kj": _round(comparable_model_energy_kj, 5)
        if cross_check_status == "available"
        else None,
        "difference_watch_minus_model_kj": _round(
            comparable_watch_energy_kj - comparable_model_energy_kj, 5
        )
        if cross_check_status == "available"
        else None,
        "difference_percent_of_model": _round(
            (comparable_watch_energy_kj - comparable_model_energy_kj)
            / comparable_model_energy_kj
            * 100.0,
            2,
        )
        if cross_check_status == "available"
        else None,
        "watch_energy_coverage": _round(
            comparable_watch_coverage_s / comparable_duration_s, 4
        )
        if comparable_duration_s
        else None,
        "comparable_segment_count": len(comparable_segment_refs),
        "source_segment_refs": sorted(set(comparable_segment_refs))[:12],
        "watch_source": "HealthExport interval activeEnergy; summed once and converted to kJ",
        "model_source": "ACSM flat-ground walking/running cost at configured body mass, grade 0, zero load",
        "interpretation": "cross-check difference only; watch W is active-energy rate, not mechanical power",
        "body_mass_kg": body_mass_kg,
        "body_mass_basis": "user_assumption",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    cumulative_energy_prefix = [0.0]
    for segment in segments:
        cumulative_energy_prefix.append(
            cumulative_energy_prefix[-1] + float(segment.get("active_energy_kj") or 0.0)
        )
    for segment_index, segment in enumerate(segments[:-1]):
        following = segments[segment_index + 1]
        if segment["state"] != "running" or following["state"] not in {"walking", "stop"}:
            continue
        recovery_index = segment_index + 1
        recovery_states: list[str] = []
        recovery_energy = 0.0
        while recovery_index < len(segments) and segments[recovery_index]["state"] in {"walking", "stop"}:
            recovery_states.append(segments[recovery_index]["state"])
            recovery_energy += float(segments[recovery_index].get("active_energy_kj") or 0.0)
            recovery_index += 1
        resumed = segments[recovery_index] if recovery_index < len(segments) and segments[recovery_index]["state"] == "running" else None
        recovery_duration = sum(float(segments[item].get("duration_s") or 0.0) for item in range(segment_index + 1, recovery_index))
        transition_events.append(
            {
                "from_segment_ref": segment["segment_ref"],
                "to_state": following["state"],
                "pre_transition_active_energy_kj": segment["active_energy_kj"],
                "cumulative_active_energy_before_transition_kj": _round(
                    cumulative_energy_prefix[segment_index + 1], 5
                ),
                "pre_transition_duration_s": segment["duration_s"],
                "transition_confidence": min(float(segment["confidence"]), float(following["confidence"])),
                "recovery_states": recovery_states,
                "recovery_duration_s": _round(recovery_duration, 1),
                "recovery_active_energy_kj": _round(recovery_energy, 5),
                "recovered_to_running": resumed is not None,
                "recovery_run_segment_ref": resumed["segment_ref"] if resumed else None,
                "cumulative_energy_basis": (
                    "sum of interval activeEnergy through the pre-transition run segment; "
                    "scalar-only energy cannot be allocated to classified segments"
                ),
                "interpretation": "transition observation; not failure, exhaustion, or physiological maximum",
            }
        )

    sustained_windows = _sustained_windows(frames, segments, activity_key)
    for segment in segments:
        segment.pop("_frame_start", None)
        segment.pop("_frame_end", None)
    daily_energy_by_date: dict[str, dict[str, Any]] = {}
    for frame in frames:
        day = _local_date(origin + timedelta(seconds=float(frame["start"])))
        bucket = daily_energy_by_date.setdefault(
            day,
            {
                "all_active_energy_kj": 0.0,
                "running_active_energy_kj": 0.0,
                "walking_active_energy_kj": 0.0,
                "energy_coverage_s": 0.0,
                "allocation_status": (
                    "interval_time_aligned"
                    if energy_intervals
                    else "scalar_activity_start_date_fallback"
                ),
            },
        )
        energy_kj = float(frame.get("energy_kj") or 0.0)
        bucket["all_active_energy_kj"] += energy_kj
        if frame["state"] == "running":
            bucket["running_active_energy_kj"] += energy_kj
        elif frame["state"] == "walking":
            bucket["walking_active_energy_kj"] += energy_kj
        bucket["energy_coverage_s"] += float(frame.get("energy_covered_s") or 0.0)
    for bucket in daily_energy_by_date.values():
        for key in ("all_active_energy_kj", "running_active_energy_kj", "walking_active_energy_kj"):
            bucket[key] = _round(float(bucket[key]), 5)
        bucket["energy_coverage_s"] = _round(float(bucket["energy_coverage_s"]), 1)
    speed_coverage = sum(frame["duration_s"] for frame in frames if frame["speed_mps"] is not None) / duration if duration else 0.0
    cadence_coverage = sum(frame["duration_s"] for frame in frames if frame["cadence_spm"] is not None) / duration if duration else 0.0
    hr_coverage = sum(frame["duration_s"] for frame in frames if frame["heart_rate"] is not None) / duration if duration else 0.0
    return {
        "activity_ref": activity_key[:16],
        "activity_key": activity_key,
        "activity_kind": kind,
        "date": _local_date(start),
        "duration_s": _round(duration, 1),
        "active_energy_kj": _round(energy_total_kj, 5),
        "active_energy_kcal": _round(energy_total_kj / KJ_PER_KCAL, 5),
        "active_energy_coverage_s": _round(energy_coverage_seconds, 1),
        "active_energy_rate_w": _round(energy_total_kj * 1000.0 / energy_coverage_seconds, 2) if energy_coverage_seconds else None,
        "active_energy_unit_basis": "sum_interval_activeEnergy_kJ; activeEnergyBurned scalar is cross-check only when interval series exists",
        "active_energy_allocation_status": (
            "interval_time_aligned"
            if energy_intervals
            else "scalar_activity_start_date_fallback"
            if scalar_kj is not None
            else "unavailable"
        ),
        "energy_cross_check": energy_cross_check,
        "energy_unit_status": energy_unit_status,
        "scalar_energy_cross_check_kj": _round(scalar_kj, 5),
        "scalar_energy_added": not bool(energy_intervals) and scalar_kj is not None,
        "segments": segments,
        "transition_events": transition_events,
        "sustained_windows": sustained_windows,
        "daily_energy_by_date": daily_energy_by_date,
        "data_coverage": {
            "speed": _round(speed_coverage, 4),
            "cadence": _round(cadence_coverage, 4),
            "heart_rate": _round(hr_coverage, 4),
            "active_energy": _round(energy_coverage_seconds / duration if duration else 0.0, 4),
        },
        "classification_status": "estimated_from_time_series",
        "classification_policy": {
            "primary": "distance/time speed and step-count/time cadence",
            "secondary": "heart-rate proximity/change as auxiliary evidence",
            "minimum_segment_seconds": MIN_SEGMENT_SECONDS,
            "hysteresis": {"running_enter_speed_mps": 2.10, "running_exit_speed_mps": 1.80, "running_enter_cadence_spm": 150, "running_exit_cadence_spm": 135},
            "unknown_gap_seconds": MAX_SAMPLE_GAP_SECONDS,
            "missing_data_is_not_stop": True,
            "inferred": True,
        },
    }


def _sustained_windows(
    frames: Sequence[Mapping[str, Any]],
    segments: Sequence[Mapping[str, Any]],
    activity_key: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    # Reconstruct segment frame ranges from their order; segment summaries have
    # already been stripped of internal indexes, so walk the frame labels.
    cursor = 0
    ranges: list[tuple[Mapping[str, Any], int, int]] = []
    for segment in segments:
        state = segment["state"]
        start = cursor
        while cursor < len(frames) and frames[cursor]["state"] == state:
            cursor += 1
        ranges.append((segment, start, cursor))
    for window_seconds in SUSTAINED_WINDOWS_SECONDS:
        best: dict[str, Any] | None = None
        sample_count = 0
        covered_window_count = 0
        source_refs: list[str] = []
        for segment, left, right in ranges:
            if segment["state"] != "running" or right <= left:
                continue
            start_values = [float(frames[index]["start"]) for index in range(left, right)]
            ends = [float(frames[index]["end"]) for index in range(left, right)]
            if not ends or ends[-1] - start_values[0] < window_seconds:
                continue
            energy_prefix = [0.0]
            coverage_prefix = [0.0]
            for index in range(left, right):
                energy_prefix.append(energy_prefix[-1] + float(frames[index]["energy_kj"] or 0.0))
                coverage_prefix.append(coverage_prefix[-1] + float(frames[index]["energy_covered_s"] or 0.0))
            for local_start, start in enumerate(start_values):
                target = start + window_seconds
                if target > ends[-1] + 1e-6:
                    break
                local_end = bisect_left(ends, target)
                full_count = local_end
                energy = energy_prefix[full_count] - energy_prefix[local_start]
                coverage = coverage_prefix[full_count] - coverage_prefix[local_start]
                if local_end < len(ends) and ends[local_end] > target:
                    frame = frames[left + local_end]
                    partial_duration = target - float(frame["start"])
                    frame_duration = float(frame["duration_s"])
                    if frame_duration > 0:
                        energy += float(frame["energy_kj"] or 0.0) * partial_duration / frame_duration
                        coverage += float(frame["energy_covered_s"] or 0.0) * partial_duration / frame_duration
                sample_count += 1
                if coverage / window_seconds < ENERGY_COVERAGE_THRESHOLD:
                    continue
                covered_window_count += 1
                rate = energy * 1000.0 / coverage if coverage > 0 else 0.0
                candidate = {
                    "window_seconds": window_seconds,
                    "average_active_energy_w": _round(rate, 2),
                    "coverage": _round(coverage / window_seconds, 4),
                    "active_energy_kj": _round(energy, 5),
                    "source_segment_ref": segment["segment_ref"],
                    "source_activity_ref": activity_key[:16],
                }
                source_refs.append(segment["segment_ref"])
                if best is None or rate > float(best["average_active_energy_w"]):
                    best = candidate
        if best is None:
            output.append(
                {
                    "window_seconds": window_seconds,
                    "status": "unavailable",
                    "average_active_energy_w": None,
                    "sample_count": sample_count,
                    "covered_window_count": covered_window_count,
                    "coverage": None,
                    "source_segment_refs": sorted(set(source_refs))[:8],
                    "unavailable_reason": "no qualifying continuous run segment with required duration and energy coverage",
                }
            )
        else:
            output.append(
                {
                    **best,
                    "status": "available",
                    "sample_count": sample_count,
                    "covered_window_count": covered_window_count,
                    "source_segment_refs": sorted(set(source_refs))[:8],
                }
            )
    return output


def _metric_records(payloads: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for payload in payloads:
        metrics = payload.get("metrics", [])
        if not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, Mapping):
                continue
            name = str(metric.get("name") or "")
            if name not in {"active_energy", "basal_energy_burned"}:
                continue
            metric_units = str(metric.get("units") or "")
            points = _points(metric.get("data"))
            for point in points:
                units = point.units or metric_units
                factor = _unit_factor_to_kj(units)
                if factor is None or point.value < 0:
                    continue
                result.append(
                    {
                        "metric_name": name,
                        "date": _local_date(point.timestamp),
                        "timestamp": point.timestamp,
                        "value_kj": point.value * factor,
                        "units": units,
                    }
                )
    return result


def _daily_metric_records(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault((record["metric_name"], record["date"]), []).append(record)
    output: list[dict[str, Any]] = []
    for (name, day), rows in sorted(grouped.items()):
        dedup: dict[tuple[str, float], dict[str, Any]] = {}
        for row in rows:
            dedup[(row["timestamp"].isoformat(), round(float(row["value_kj"]), 8))] = row
        values = [float(row["value_kj"]) for row in dedup.values()]
        unique_values = sorted({round(value, 8) for value in values})
        # Metric rows can be interval samples or daily totals.  Either way,
        # sum values within a date once.  Duplicate exports are removed by the
        # timestamp/value key above; conflicting same-date daily candidates are
        # retained as ambiguous instead of being added.
        timestamps = sorted(row["timestamp"] for row in dedup.values())
        deltas = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:]) if b > a]
        granularity = "daily" if not deltas or statistics.median(deltas) >= 12 * 3600 else "interval"
        if granularity == "daily":
            value = values[0] if len(unique_values) == 1 else None
            status = "available" if value is not None else "ambiguous_duplicate"
            selection = "deduplicated_daily_snapshot" if value is not None else "conflicting_daily_candidates_not_summed"
        else:
            value = sum(values)
            status = "available"
            selection = "sum_distinct_interval_energy_within_local_date"
        output.append(
            {
                "metric_name": name,
                "date": day,
                "value_kj": _round(value, 5),
                "sample_count": len(dedup),
                "granularity": granularity,
                "status": status,
                "selection": selection,
                "unit": "kJ",
            }
        )
    return output


def build_body_index_source_analysis(
    path: str | Path,
    *,
    body_mass_kg: float = DEFAULT_BODY_MASS_KG,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Parse one local HealthExport ZIP into sanitized, mergeable evidence."""
    path = Path(path)
    mass = _safe_body_mass(body_mass_kg)
    payloads = _json_members(path)
    workouts: list[Mapping[str, Any]] = []
    for payload in payloads:
        raw_workouts = payload.get("workouts", [])
        if isinstance(raw_workouts, list):
            workouts.extend(item for item in raw_workouts if isinstance(item, Mapping))
    activity_records: list[dict[str, Any]] = []
    seen_activities: set[str] = set()
    errors: list[str] = []
    for workout in workouts:
        kind = _activity_kind(workout.get("name"))
        key = _activity_fingerprint(workout, kind)
        if key in seen_activities:
            continue
        seen_activities.add(key)
        try:
            activity_records.append(_activity_analysis(workout, mass))
        except (TypeError, ValueError, OverflowError) as exc:
            errors.append(type(exc).__name__)
    metric_records = _daily_metric_records(_metric_records(payloads))
    source_sha = source_sha256 or hashlib.sha256(path.read_bytes()).hexdigest()
    mode_counts: dict[str, int] = {}
    for activity in activity_records:
        mode = str(activity["activity_kind"])
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
    dates = [activity["date"] for activity in activity_records] + [row["date"] for row in metric_records]
    return {
        "schema_version": SCHEMA_VERSION,
        "source_ref": source_sha[:16],
        "source_sha256": source_sha,
        "body_mass_kg": mass,
        "body_mass_basis": "user_assumption",
        "activities": activity_records,
        "daily_metric_records": metric_records,
        "coverage": {
            "activity_count": len(activity_records),
            "activity_count_by_mode": mode_counts,
            "date_start": min(dates) if dates else None,
            "date_end": max(dates) if dates else None,
            "parse_error_count": len(errors),
            "parse_errors_by_type": sorted(set(errors)),
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_health_payload_shared": False,
            "raw_gpx_shared": False,
            "exact_timestamps_shared": False,
            "source_original_path_shared": False,
        },
    }


def _empty_metric(metric_id: str, label: str, owner: str, reason: str) -> dict[str, Any]:
    return {
        "id": metric_id,
        "label": label,
        "value": "unavailable",
        "coeff": "--",
        "score": None,
        "status": "unavailable",
        "source": reason,
        "owner": owner,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _coefficient_metrics(
    *,
    mode_speeds: Mapping[str, Sequence[float]],
    segments: Sequence[Mapping[str, Any]],
    transition_count: int,
    body_mass_kg: float,
) -> list[dict[str, Any]]:
    walking_speed = _median(mode_speeds.get("walking", []))
    running_speed = _median(mode_speeds.get("running", []))
    metrics: list[dict[str, Any]] = []
    if walking_speed is not None or running_speed is not None:
        metrics.append(
            {
                "id": "flat_ground_speed",
                "label": "Flat Ground Speed",
                "spec": "平地標準速度（個人觀察）",
                "effect": "Body Index personal speed reference",
                "source": "HealthExport speed/time and cadence/time classified segments",
                "value": f"walk {_round(walking_speed, 2) or '--'} m/s · run {_round(running_speed, 2) or '--'} m/s",
                "coeff": "observed",
                "score": None,
                "status": "available",
                "owner": "Body Index",
                "body_mass_kg": body_mass_kg,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    else:
        metrics.append(_empty_metric("flat_ground_speed", "Flat Ground Speed", "Body Index", "no speed/time or cadence/time coverage"))
    metrics.extend(
        [
            _empty_metric("ascent_speed", "Ascent Speed", "Architecture", "flat grade model excludes ascent evidence"),
            _empty_metric("descent_speed", "Descent Speed", "Architecture", "flat grade model excludes descent evidence"),
            _empty_metric("technical_slowdown", "Technical Terrain Slowdown", "Architecture", "no terrain/technical mapping in Body Index"),
            {
                "id": "rest_frequency",
                "label": "Run-to-Walk/Stop Transitions",
                "spec": "跑→走／停轉換觀察",
                "effect": "observed transition and recovery rhythm",
                "source": "classified activity segments",
                "value": f"{transition_count} transitions",
                "coeff": "observed",
                "score": None,
                "status": "available" if segments else "unavailable",
                "owner": "Body Index",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            _empty_metric("late_trip_decay", "Late-trip Decay", "Body Index", "no validated within-activity late-trip mapping"),
            _empty_metric("load_impact", "Load Impact", "Architecture", "no load series; flat light-clothing assumption only"),
            _empty_metric("weather_impact", "Weather Impact", "Architecture", "weather is outside HealthExport Body Index input"),
            {
                "id": "experience_confidence",
                "label": "Evidence Coverage",
                "spec": "資料覆蓋可信度",
                "effect": "coverage quality, not body ability",
                "source": "time-series coverage and classification evidence",
                "value": "see data coverage",
                "coeff": "observed",
                "score": None,
                "status": "available" if segments else "unavailable",
                "owner": "Body Index",
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        ]
    )
    return metrics


def _merge_daily_metrics(analyses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for analysis in analyses:
        for row in analysis.get("daily_metric_records", []):
            if isinstance(row, Mapping):
                grouped.setdefault((str(row.get("metric_name")), str(row.get("date"))), []).append(dict(row))
    output: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        values = [float(row["value_kj"]) for row in rows if row.get("status") == "available" and row.get("value_kj") is not None]
        unique = sorted({round(value, 5) for value in values})
        if len(unique) == 1:
            value = unique[0]
            status = "available"
            selection = "same_daily_value_deduplicated_across_exports"
        elif len(unique) == 0:
            value = None
            status = "unavailable"
            selection = "no_valid_daily_value"
        else:
            value = None
            status = "ambiguous_duplicate"
            selection = "conflicting_daily_values_not_summed"
        output.append(
            {
                "metric_name": key[0],
                "date": key[1],
                "value_kj": value,
                "status": status,
                "selection": selection,
                "candidate_count": len(rows),
                "unit": "kJ",
            }
        )
    return output


def _activity_segment_energy(activity: Mapping[str, Any], state: str) -> float:
    return sum(
        float(segment.get("active_energy_kj") or 0.0)
        for segment in activity.get("segments", [])
        if isinstance(segment, Mapping) and segment.get("state") == state
    )


def _daily_energy_summary(
    activities: Sequence[Mapping[str, Any]],
    metric_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    workout_all: dict[str, float] = {}
    workout_run: dict[str, float] = {}
    for activity in activities:
        daily_rows = activity.get("daily_energy_by_date", [])
        if isinstance(daily_rows, Mapping):
            daily_rows = [
                {"date": day, **row}
                for day, row in daily_rows.items()
                if isinstance(row, Mapping)
            ]
        if isinstance(daily_rows, list) and daily_rows:
            for row in daily_rows:
                if not isinstance(row, Mapping):
                    continue
                day = str(row.get("date") or "")
                if not day:
                    continue
                workout_all[day] = workout_all.get(day, 0.0) + float(
                    row.get("all_active_energy_kj") or 0.0
                )
                workout_run[day] = workout_run.get(day, 0.0) + float(
                    row.get("running_active_energy_kj") or 0.0
                )
            continue
        day = str(activity.get("date") or "")
        if not day:
            continue
        workout_all[day] = workout_all.get(day, 0.0) + float(
            activity.get("active_energy_kj") or 0.0
        )
        workout_run[day] = workout_run.get(day, 0.0) + _activity_segment_energy(
            activity, "running"
        )
    metric_active = {
        str(row["date"]): float(row["value_kj"])
        for row in metric_rows
        if row.get("metric_name") == "active_energy" and row.get("status") == "available" and row.get("value_kj") is not None
    }
    metric_static = {
        str(row["date"]): float(row["value_kj"])
        for row in metric_rows
        if row.get("metric_name") == "basal_energy_burned" and row.get("status") == "available" and row.get("value_kj") is not None
    }
    metric_active_rows = {
        str(row["date"]): row
        for row in metric_rows
        if row.get("metric_name") == "active_energy"
    }
    ambiguous_active_days = {
        day
        for day, row in metric_active_rows.items()
        if row.get("status") == "ambiguous_duplicate"
    }
    if ambiguous_active_days:
        active_source = "HealthExport active_energy metric contains conflicting daily candidates"
    elif metric_active and workout_all:
        active_source = "HealthExport active_energy metric with deduplicated workout fallback"
    elif metric_active:
        active_source = "HealthExport active_energy metric"
    else:
        active_source = "deduplicated workout activeEnergy"
    all_days = sorted(
        set(workout_all)
        | set(metric_active_rows)
        | set(metric_active)
        | set(metric_static)
    )
    days: list[dict[str, Any]] = []
    run_fractions: list[float] = []
    multipliers: list[float] = []
    for day in all_days:
        if day in ambiguous_active_days:
            active = None
        else:
            active = metric_active.get(day, workout_all.get(day))
        static = metric_static.get(day)
        total = active + static if active is not None and static is not None else None
        run = workout_run.get(day, 0.0)
        fraction = run / active if active and run <= active + 1e-8 else None
        active_basis = (
            "HealthExport active_energy metric"
            if day in metric_active
            else "unavailable: conflicting HealthExport active_energy candidates"
            if day in ambiguous_active_days
            else "deduplicated workout activeEnergy"
            if day in workout_all
            else "unavailable"
        )
        days.append(
            {
                "date": day,
                "run_active_energy_kj": _round(run, 5),
                "all_activity_energy_kj": _round(active, 5) if active is not None else None,
                "static_energy_kj": _round(static, 5) if static is not None else None,
                "total_energy_kj": _round(total, 5) if total is not None else None,
                "same_day_run_fraction": _round(fraction, 5),
                "same_day_fraction_status": "available" if fraction is not None else "unavailable_inconsistent_or_missing_denominator",
                "active_energy_basis": active_basis,
                "source": active_basis,
            }
        )
        if fraction is not None:
            run_fractions.append(fraction)
    baseline_values = [float(value) for value in metric_active.values()]
    if not baseline_values and not metric_active_rows:
        baseline_values = list(workout_all.values())
    baseline = statistics.mean(baseline_values) if baseline_values else None
    for day in days:
        run = float(day["run_active_energy_kj"] or 0.0)
        if baseline and run > 0:
            multiplier = run / baseline
            day["run_energy_vs_mean_active_baseline"] = _round(multiplier, 5)
            multipliers.append(multiplier)
        else:
            day["run_energy_vs_mean_active_baseline"] = None
    dates = [day["date"] for day in days]
    baseline_dates = (
        sorted(metric_active)
        if metric_active
        else sorted(workout_all)
        if not metric_active_rows
        else []
    )
    return {
        "date_range": {"start": min(dates) if dates else None, "end": max(dates) if dates else None},
        "baseline_date_range": {
            "start": baseline_dates[0] if baseline_dates else None,
            "end": baseline_dates[-1] if baseline_dates else None,
        },
        "days": days,
        "active_energy_source": active_source,
        "static_energy_source": "HealthExport basal_energy_burned metric only",
        "mean_daily_active_energy_kj": _round(baseline, 5),
        "mean_daily_active_energy_kcal": _round(baseline / KJ_PER_KCAL, 5) if baseline is not None else None,
        "run_fraction_mean": _round(statistics.mean(run_fractions), 5) if run_fractions else None,
        "run_baseline_multiplier_mean": _round(statistics.mean(multipliers), 5) if multipliers else None,
        "complete_active_day_count": sum(day["all_activity_energy_kj"] is not None for day in days),
        "complete_static_day_count": sum(day["static_energy_kj"] is not None for day in days),
        "complete_total_day_count": sum(day["total_energy_kj"] is not None for day in days),
        "completeness": {
            "date_range": {"start": min(dates) if dates else None, "end": max(dates) if dates else None},
            "active_days": sum(day["all_activity_energy_kj"] is not None for day in days),
            "static_days": sum(day["static_energy_kj"] is not None for day in days),
            "total_days": sum(day["total_energy_kj"] is not None for day in days),
            "baseline_days": len(baseline_values),
        },
        "exclusions": [
            "conflicting duplicate daily values are unavailable and are not summed",
            "a missing active/static metric is not imputed",
            "run energy is not interpreted as aerobic-only metabolism or physiological maximum",
        ],
        "ratio_definitions": {
            "same_day_fraction": "run-segment active energy / same-day all-activity active energy; only emitted when denominator is consistent",
            "baseline_multiplier": "run-segment active energy / mean daily active-energy baseline; may exceed 1 and is not a maximum daily capacity",
        },
    }


def aggregate_body_index_sources(
    analyses: Sequence[Mapping[str, Any]],
    *,
    body_mass_kg: float = DEFAULT_BODY_MASS_KG,
) -> dict[str, Any]:
    """Merge already parsed sources while deduplicating activities and dates."""
    mass = _safe_body_mass(body_mass_kg)
    unique_activities: dict[str, Mapping[str, Any]] = {}
    for analysis in analyses:
        for activity in analysis.get("activities", []):
            if not isinstance(activity, Mapping):
                continue
            key = str(activity.get("activity_key") or activity.get("activity_ref") or _sha(activity))
            unique_activities.setdefault(key, activity)
    activities = list(unique_activities.values())
    eligible = [activity for activity in activities if activity.get("activity_kind") in {"running", "walking"}]
    segments = [segment for activity in eligible for segment in activity.get("segments", []) if isinstance(segment, Mapping)]
    transitions = [event for activity in eligible for event in activity.get("transition_events", []) if isinstance(event, Mapping)]
    mode_speeds: dict[str, list[float]] = {"running": [], "walking": []}
    for segment in segments:
        if segment.get("state") in mode_speeds and segment.get("speed_mps_median") is not None:
            mode_speeds[str(segment["state"])].append(float(segment["speed_mps_median"]))
    sustained: dict[str, dict[str, Any]] = {}
    for window_seconds in SUSTAINED_WINDOWS_SECONDS:
        candidates = [
            window
            for activity in eligible
            for window in activity.get("sustained_windows", [])
            if isinstance(window, Mapping) and int(window.get("window_seconds") or 0) == window_seconds
        ]
        available = [window for window in candidates if window.get("status") == "available" and window.get("average_active_energy_w") is not None]
        best = max(available, key=lambda item: float(item["average_active_energy_w"])) if available else None
        sustained[str(window_seconds)] = {
            "window_seconds": window_seconds,
            "status": "available" if best else "unavailable",
            "average_active_energy_w": best.get("average_active_energy_w") if best else None,
            "active_energy_kj": best.get("active_energy_kj") if best else None,
            "coverage": best.get("coverage") if best else None,
            "sample_count": sum(int(window.get("sample_count") or 0) for window in candidates),
            "covered_window_count": sum(int(window.get("covered_window_count") or 0) for window in candidates),
            "source_segment_refs": sorted({str(ref) for window in candidates for ref in window.get("source_segment_refs", [])})[:12],
            "unavailable_reason": None if best else "no qualifying continuous run segment; no extrapolation to uncovered duration",
        }
    total_energy = sum(float(activity.get("active_energy_kj") or 0.0) for activity in activities)
    run_energy = sum(_activity_segment_energy(activity, "running") for activity in eligible)
    walk_energy = sum(_activity_segment_energy(activity, "walking") for activity in eligible)
    stop_energy = sum(_activity_segment_energy(activity, "stop") for activity in eligible)
    unknown_energy = sum(_activity_segment_energy(activity, "unknown") for activity in eligible)
    energy_coverage = sum(float(activity.get("active_energy_coverage_s") or 0.0) for activity in activities)
    total_duration = sum(float(activity.get("duration_s") or 0.0) for activity in activities)
    metric_rows = _merge_daily_metrics(analyses)
    daily_energy = _daily_energy_summary(activities, metric_rows)
    cross_checks = [
        activity.get("energy_cross_check")
        for activity in eligible
        if isinstance(activity.get("energy_cross_check"), Mapping)
        and activity.get("energy_cross_check", {}).get("status") == "available"
    ]
    comparable_watch_energy_kj = sum(
        float(item.get("watch_interval_active_energy_kj_on_comparable_segments") or 0.0)
        for item in cross_checks
    )
    comparable_model_energy_kj = sum(
        float(item.get("flat_ground_model_active_energy_kj") or 0.0)
        for item in cross_checks
    )
    cross_check = {
        "status": "available" if cross_checks and comparable_model_energy_kj > 0 else "unavailable",
        "watch_interval_active_energy_kj_on_comparable_segments": _round(
            comparable_watch_energy_kj, 5
        )
        if cross_checks and comparable_model_energy_kj > 0
        else None,
        "flat_ground_model_active_energy_kj": _round(comparable_model_energy_kj, 5)
        if cross_checks and comparable_model_energy_kj > 0
        else None,
        "difference_watch_minus_model_kj": _round(
            comparable_watch_energy_kj - comparable_model_energy_kj, 5
        )
        if cross_checks and comparable_model_energy_kj > 0
        else None,
        "difference_percent_of_model": _round(
            (comparable_watch_energy_kj - comparable_model_energy_kj)
            / comparable_model_energy_kj
            * 100.0,
            2,
        )
        if cross_checks and comparable_model_energy_kj > 0
        else None,
        "comparable_activity_count": len(cross_checks),
        "source_segment_refs": sorted(
            {
                str(ref)
                for item in cross_checks
                for ref in item.get("source_segment_refs", [])
            }
        )[:12],
        "watch_source": "HealthExport interval activeEnergy; summed once and converted to kJ",
        "model_source": "ACSM flat-ground walking/running cost at configured body mass, grade 0, zero load",
        "interpretation": "cross-check difference only; watch W is active-energy rate, not mechanical power",
        "body_mass_kg": mass,
        "body_mass_basis": "user_assumption",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    date_values = [str(activity.get("date")) for activity in activities if activity.get("date")] + [str(row.get("date")) for row in metric_rows if row.get("date")]
    classification_coverage = statistics.mean(float(activity.get("data_coverage", {}).get("speed") or 0.0) for activity in eligible) if eligible else 0.0
    coefficient_metrics = _coefficient_metrics(mode_speeds=mode_speeds, segments=segments, transition_count=len(transitions), body_mass_kg=mass)
    mode_summary = {
        mode: {
            "median_speed_mps": _round(_median(values), 4),
            "sample_count": len(values),
            "speed_observation_basis": "classified segment median; count is coverage metadata, not ability score",
        }
        for mode, values in mode_speeds.items()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "available" if eligible and total_energy > 0 else "partial" if eligible else "unavailable",
        "body_mass_kg": mass,
        "body_mass_basis": "user_assumption",
        "standardized_scenario": {
            "grade_fraction": GRADE_FRACTION,
            "grade_degrees": 0,
            "load_kg": 0,
            "clothing": "light clothing assumption",
            "meaning": "model scenario only; it does not prove historical activities were flat or unloaded",
        },
        "summary": {
            "scout_pace_coefficient": "unavailable",
            "pace_coefficient_semantics": "not calculated from activity counts or energy alone",
            "pace_fit_time_ratio": "unavailable",
            "pace_fit_time_percent": "unavailable",
            "pace_fit_semantics": "requires traceable speed/time mapping with Architecture route demand; energy or W is not a Pace Fit percentage",
            "energy_reserve": "unavailable",
            "vulnerability": "unavailable",
            "experience_trust": "unavailable",
            "score_percent": 0,
            "evidence_status": "available" if eligible else "unavailable",
            "total_distance_km": None,
            "total_duration_min": _round(total_duration / 60.0, 2),
        },
        "observations": {
            "activity_count": len(activities),
            "eligible_activity_count": len(eligible),
            "activity_count_by_mode": {
                mode: sum(1 for activity in activities if activity.get("activity_kind") == mode)
                for mode in sorted({str(activity.get("activity_kind")) for activity in activities})
            },
            "run_active_energy_kj": _round(run_energy, 5),
            "run_active_energy_kcal": _round(run_energy / KJ_PER_KCAL, 5),
            "walk_active_energy_kj": _round(walk_energy, 5),
            "stop_active_energy_kj": _round(stop_energy, 5),
            "unknown_segment_active_energy_kj": _round(unknown_energy, 5),
            "all_activity_active_energy_kj": _round(total_energy, 5),
            "all_activity_active_energy_kcal": _round(total_energy / KJ_PER_KCAL, 5),
            "active_energy_covered_seconds": _round(energy_coverage, 1),
            "energy_rate_w": _round(total_energy * 1000.0 / energy_coverage, 2) if energy_coverage else None,
            "energy_rate_definition": "sum of interval activeEnergy kJ x 1000 / covered interval seconds; not mechanical power",
            "run_energy_definition": "sum of activeEnergy assigned to inferred running segments only; activity name is not used as segment energy",
            "classification_speed_coverage": _round(classification_coverage, 4),
        },
        "flat_speed_by_mode": mode_summary,
        "segments": [dict(segment) for segment in segments],
        "transition_events": [dict(event) for event in transitions],
        "sustained_output": {
            "label": "historical highest sustained output estimate",
            "windows": sustained,
            "units": "average Apple active-energy estimate W",
            "not_mechanical_power": True,
            "not_extrapolated": True,
        },
        "daily_energy": daily_energy,
        "energy_cross_check": cross_check,
        "daily_metric_records": metric_rows,
        "coefficient_metrics": coefficient_metrics,
        "model_assumptions": [
            f"body mass is {mass:g} kg for this run; it is a user assumption, not a HealthExport observation",
            "flat grade 0 degrees, zero load, and light clothing are standardized model conditions",
            "activity name initializes mode only; speed/time and cadence/time classify run, walk, stop, or unknown",
            "heart rate is auxiliary evidence; no IMU or explicit pause event is available",
            "all transitions are inferred observations and do not represent fatigue, failure, or physiological maximum",
        ],
        "unknowns": [
            "historical grade, terrain, load, weather, and clothing are not identified by this Body Index model",
            "uncovered 5/10/15/20 minute windows remain unavailable and are not extrapolated",
            "active-energy W is a provider estimate, not external mechanical power",
            "pure aerobic metabolism is not separated from the active-energy estimate",
            "Pace Fit remains unavailable until Architecture supplies a traceable route speed correction",
        ],
        "source_date_range": {"start": min(date_values) if date_values else None, "end": max(date_values) if date_values else None},
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_health_payload_shared": False,
            "raw_gpx_shared": False,
            "exact_timestamps_shared": False,
            "precise_location_shared": False,
            "external_network_calls": False,
        },
    }


def attach_pace_fit_mappings(
    payload: Mapping[str, Any],
    body_index: Mapping[str, Any],
    architecture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach only an explicit Architecture speed correction to CP pairs.

    A historical reference average remains useful without Body Index.  A
    personal percentage is emitted only when a pair has distance, Body Index
    flat speed, and a reviewed Architecture `pace_speed_correction_ratio`.
    """
    result = dict(payload)
    pairs: list[dict[str, Any]] = []
    vectors = [
        item for item in (architecture or {}).get("segment_demand_vectors", [])
        if isinstance(item, Mapping)
    ]
    walking_speed = ((body_index.get("flat_speed_by_mode") or {}).get("walking") or {}).get("median_speed_mps")
    speed = _finite(walking_speed)
    mapping_available = 0
    for raw_pair in payload.get("pairs", []):
        pair = dict(raw_pair)
        mapping: dict[str, Any] = {
            "status": "unavailable",
            "reason": "architecture_speed_time_mapping_unavailable",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        distance = _finite(pair.get("distance_m"))
        midpoint = None
        if distance is not None:
            start = _finite(pair.get("from_route_distance_m"))
            end = _finite(pair.get("to_route_distance_m"))
            if start is not None and end is not None:
                midpoint = (start + end) / 2.0
        vector = None
        if midpoint is not None:
            vector = next(
                (
                    item
                    for item in vectors
                    if (_finite(item.get("start_distance_m")) is not None)
                    and (_finite(item.get("end_distance_m")) is not None)
                    and _finite(item.get("start_distance_m")) <= midpoint <= _finite(item.get("end_distance_m"))
                ),
                None,
            )
        correction = _finite(vector.get("pace_speed_correction_ratio")) if vector else None
        reference = _finite((pair.get("duration_minutes") or {}).get("average"))
        if speed is not None and speed > 0 and distance is not None and distance > 0 and correction is not None and correction > 0 and reference is not None and reference > 0:
            expected = distance / (speed * correction) / 60.0
            ratio = expected / reference
            mapping = {
                "status": "available",
                "flat_speed_mps": _round(speed, 4),
                "route_speed_correction_ratio": _round(correction, 5),
                "route_distance_m": _round(distance, 2),
                "expected_minutes": _round(expected, 3),
                "reference_average_minutes": _round(reference, 3),
                "pace_fit_percent": round(ratio * 100),
                "basis": "Body Index walking flat speed x explicit Architecture route speed correction; reference is same CP pair average",
                "energy_not_used_as_time_ratio": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
            mapping_available += 1
        pair["personal_mapping"] = mapping
        pairs.append(pair)
    result["pairs"] = pairs
    result["pace_fit_mapping"] = {
        "status": "available" if mapping_available else "unavailable",
        "mapped_pair_count": mapping_available,
        "pair_count": len(pairs),
        "method": "personal flat speed -> explicit Architecture route speed correction -> expected elapsed time -> same-pair historical average",
        "energy_or_w_not_converted_directly": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return result


__all__ = [
    "DEFAULT_BODY_MASS_KG",
    "SCHEMA_VERSION",
    "SUSTAINED_WINDOWS_SECONDS",
    "aggregate_body_index_sources",
    "attach_pace_fit_mappings",
    "build_body_index_source_analysis",
    "flat_ground_metabolic_cost",
]
