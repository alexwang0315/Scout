"""Explicit terrain/team timing and candidate overnight planning for Planned GPX.

Rates are supplied assumptions or Scout Pace Coefficient values, never inferred
from a user's age, health, desired arrival, or a TRH cost raster. Scout's vertical
rate is gain / *whole moving time* (scout_pace_coefficient_builder.py), so adding
horizontal time again double-counts that time. Per ordered edge/member we use::

    minutes = max(horizontal_minutes, ascent_minutes + descent_minutes)
              * surface_time_multiplier / product(1 - supplied_slowdown_ratio)

A supplied observed downhill horizontal rate can bound descent instead of an
unavailable vertical descent rate. A direction-specific rate is never borrowed
from the opposite direction. Terrain edges, member bottlenecks, and uncertainty
bounds are summed. The declared +/- uncertainty is a scenario envelope, NOT a
statistical confidence interval. Source refs are retained for caller verification.
Missing geometry/elevation/member rates remain unknown. Fixed stops, recurring
rest allowances, and overnight stays are separate from moving time. This module
has no filesystem, network, runtime permission, or route-promotion effects.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TIMING_VERSION = "plannedTerrainTiming.v1"
BOUNDARY = {"candidate_only": True, "runtime_safety_truth": False,
            "operational": False, "promotion_allowed": False}


class TimingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DaylightWindow(TimingModel):
    sunrise_at: datetime
    sunset_at: datetime
    source_ref: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_window(self):
        for stamp in (self.sunrise_at, self.sunset_at):
            if stamp.utcoffset() is None:
                raise ValueError("Daylight timestamps require an explicit timezone.")
        if self.sunset_at <= self.sunrise_at:
            raise ValueError("Sunset must be later than sunrise.")
        return self


class CampsiteCandidate(TimingModel):
    candidate_id: str = Field(min_length=1)
    point_index: int = Field(ge=0)
    label: str = ""
    water_available: bool | None = None
    capacity_persons: int | None = Field(default=None, ge=0)
    legal_use: bool | None = None
    overnight_suitable: bool | None = None
    slope_degrees: float | None = Field(default=None, ge=0, le=90)
    reservation_required: bool | None = None
    source_refs: list[str] = Field(default_factory=list)


class TerrainTimingOptions(TimingModel):
    assumed_flat_speed_kmh: float | None = Field(default=None, gt=0, le=20)
    assumed_ascent_m_per_hour: float | None = Field(default=None, gt=0)
    assumed_descent_m_per_hour: float | None = Field(default=None, gt=0)
    assumption_label: str = "Explicit planning scenario; personal capability unverified"
    source_refs: list[str] = Field(default_factory=list)
    team_members: list[dict[str, Any]] = Field(default_factory=list)
    use_assumptions_for_missing_members: bool = False
    uncertainty_fraction: float = Field(default=.25, ge=0, lt=1)
    default_surface: str = "unspecified"
    surface_time_multipliers: dict[str, float] = Field(default_factory=lambda: {"unspecified": 1.0})
    max_daily_moving_minutes: float | None = Field(default=None, gt=0)
    max_daily_elapsed_minutes: float | None = Field(default=None, gt=0)
    rest_every_moving_minutes: float | None = Field(default=None, gt=0)
    rest_duration_minutes: float | None = Field(default=None, gt=0)
    require_daylight: bool = False
    daylight_windows: list[DaylightWindow] = Field(default_factory=list)
    daylight_margin_minutes: float = Field(default=0, ge=0)
    campsite_candidates: list[CampsiteCandidate] = Field(default_factory=list)
    auto_schedule_camps: bool = False
    require_camp_water: bool = False
    next_day_departure_time: str | None = None
    minimum_overnight_minutes: float | None = Field(default=None, gt=0)
    party_size: int | None = Field(default=None, ge=1)
    max_days: int | None = Field(default=None, ge=1)

    @field_validator("surface_time_multipliers")
    @classmethod
    def positive_multipliers(cls, values):
        for name, value in values.items():
            if not name or isinstance(value, bool) or not math.isfinite(value) or value < 1:
                raise ValueError("Surface time multipliers must be finite and >= 1.")
        return values

    @field_validator("next_day_departure_time")
    @classmethod
    def departure_clock(cls, value):
        if value is not None:
            if len(value) != 5 or value[2] != ":":
                raise ValueError("Use HH:MM for the declared next-day departure.")
            time.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def coherent_options(self):
        if self.rest_every_moving_minutes is not None and self.rest_duration_minutes is None:
            raise ValueError("A recurring rest interval also needs a declared rest duration.")
        if self.party_size is not None and self.party_size < len(self.team_members):
            raise ValueError("Party size cannot be smaller than the supplied team.")
        ids = [candidate.candidate_id for candidate in self.campsite_candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("Campsite IDs must be unique.")
        member_ids = [str(m.get("member_id") or m.get("id") or f"member_{i + 1}")
                      for i, m in enumerate(self.team_members)]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Team member IDs must be unique.")
        return self


class TimingEvent(TimingModel):
    point_index: int = Field(ge=0)
    kind: Literal["stop", "camp", "depart", "deadline"]
    duration_minutes: float | None = Field(default=None, ge=0)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    latest_arrival_at: datetime | None = None
    label: str | None = None
    candidate_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    day_index: int | None = Field(default=None, ge=1)
    calendar_date: str | None = None
    source_text: str | None = None
    source_span: Any = None
    generated_from_candidate: bool = False

    @field_validator("departure_at", "arrival_at", "latest_arrival_at")
    @classmethod
    def aware_time(cls, stamp):
        if stamp is not None and stamp.utcoffset() is None:
            raise ValueError("Planning timestamps require an explicit timezone.")
        return stamp


def _options(value):
    return value if isinstance(value, TerrainTimingOptions) else TerrainTimingOptions.model_validate(value or {})


def _number(value, *, positive=False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Numeric planning inputs must not be booleans.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("A numeric planning input is invalid.") from error
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError("Rates must be positive; durations and ratios must be nonnegative and finite.")
    return number


def _first(raw, nested, *keys):
    for key in keys:
        if raw.get(key) is not None:
            return raw[key]
        if nested.get(key) is not None:
            return nested[key]
    return None


def _members(options):
    raw_members = list(options.team_members) or [{"member_id": "declared_scenario"}]
    if options.team_members and options.party_size and options.party_size > len(raw_members):
        raw_members.extend({"member_id": f"missing_party_member_{i + 1}"}
                           for i in range(len(raw_members), options.party_size))
    result = []
    for index, raw in enumerate(raw_members):
        nested = raw.get("scout_pace_coefficient") or {}
        if not isinstance(nested, dict):
            raise ValueError("Scout Pace Coefficient must be an object.")
        flat = _number(_first(raw, nested, "flat_speed_kmh"), positive=True)
        if flat is None:
            flat_mps = _number(_first(raw, nested, "flat_speed_mps", "flat_pace_mps", "pace_mps",
                                      "current_pace_mps", "planned_pace_mps", "moving_speed_mps", "speed_mps"), positive=True)
            flat = flat_mps * 3.6 if flat_mps is not None else None
        ascent = _number(_first(raw, nested, "ascent_speed_vertical_m_per_hour", "ascent_m_per_hour",
                               "vertical_ascent_speed_mph"), positive=True)
        descent = _number(_first(raw, nested, "descent_speed_vertical_m_per_hour", "descent_m_per_hour"), positive=True)
        downhill = _number(_first(raw, nested, "descent_speed_mps", "downhill_speed_mps", "downhill_pace_mps"), positive=True)
        uphill = _number(_first(raw, nested, "uphill_speed_mps", "uphill_pace_mps"), positive=True)
        assumed = []
        if not options.team_members or options.use_assumptions_for_missing_members:
            if flat is None and options.assumed_flat_speed_kmh is not None:
                flat = options.assumed_flat_speed_kmh; assumed.append("flat_speed_kmh")
            if ascent is None and options.assumed_ascent_m_per_hour is not None:
                ascent = options.assumed_ascent_m_per_hour; assumed.append("ascent_m_per_hour")
            if descent is None and options.assumed_descent_m_per_hour is not None:
                descent = options.assumed_descent_m_per_hour; assumed.append("descent_m_per_hour")
        ratios = {}
        for key, aliases in {
            "technical": ("technical_terrain_slowdown_ratio", "technical_slowdown_ratio"),
            "load": ("load_impact_ratio", "load_slowdown_ratio", "pack_slowdown_ratio"),
            "weather": ("weather_impact_ratio", "weather_slowdown_ratio", "rain_slowdown_ratio"),
            "late_trip": ("late_trip_decay_ratio", "late_trip_speed_decay_ratio", "fatigue_decay_ratio"),
        }.items():
            ratio = _number(_first(raw, nested, *aliases))
            if ratio is not None and ratio >= 1:
                raise ValueError("Scout slowdown ratios are speed reductions in [0, 1), not time multipliers.")
            ratios[key] = ratio
        uncertainty = _number(raw.get("uncertainty_fraction", options.uncertainty_fraction))
        if uncertainty >= 1:
            raise ValueError("Uncertainty fraction must be less than one.")
        refs = raw.get("source_refs") or []
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("Member source_refs must be a list of references.")
        result.append({"member_id": str(raw.get("member_id") or raw.get("id") or f"member_{index + 1}"),
                       "flat_speed_kmh": flat, "ascent_m_per_hour": ascent, "descent_m_per_hour": descent,
                       "downhill_speed_mps": downhill, "uphill_speed_mps": uphill,
                       "slowdown_ratios": ratios, "uncertainty_fraction": uncertainty,
                       "assumed_fields": assumed, "source_refs": list(dict.fromkeys(options.source_refs + refs)),
                       "rate_origin": "declared_scenario" if not options.team_members else "supplied_member_coefficients",
                       "rest_frequency_minutes": _number(_first(raw, nested, "rest_frequency_minutes", "rest_interval_minutes"), positive=True)})
    return result


def _points(values):
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError("Timing needs at least two ordered route points.")
    result = []
    previous_index = None
    for position, raw in enumerate(values):
        if not isinstance(raw, dict):
            raise ValueError("Each route point must be an object.")
        point = dict(raw)
        for field, bound in (("lat", 90), ("lon", 180)):
            value = point.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > bound:
                raise ValueError("Route coordinates must be finite WGS84 numbers.")
        if point.get("ele") is not None:
            elevation = point["ele"]
            if isinstance(elevation, bool) or not isinstance(elevation, (int, float)) or not math.isfinite(elevation):
                raise ValueError("Elevation must be finite or explicitly missing.")
        point_index = point.get("point_index", position)
        if isinstance(point_index, bool) or not isinstance(point_index, int) or point_index < 0:
            raise ValueError("Point indexes must be nonnegative integers.")
        if previous_index is not None and point_index != previous_index + 1:
            raise ValueError("Preserve consecutive canonical point indexes, including repeated visits.")
        previous_index = point["point_index"] = point_index
        result.append(point)
    return result


def _distance(a, b):
    lat1, lat2 = math.radians(a["lat"]), math.radians(b["lat"])
    dlat, dlon = lat2 - lat1, math.radians(b["lon"] - a["lon"])
    return 6371000 * 2 * math.asin(min(1, math.sqrt(math.sin(dlat / 2) ** 2 +
                                               math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)))


def _edge(a, b, options, members):
    span = _distance(a, b)
    missing = []
    if (b.get("break_before") and span > .01) or b.get("geometry_supported") is False:
        missing.append("route_geometry_gap")
    gain = loss = None
    if a.get("ele") is None or b.get("ele") is None:
        missing.append("elevation_missing")
    else:
        gain, loss = max(0., b["ele"] - a["ele"]), max(0., a["ele"] - b["ele"])
    surface = str(b.get("surface") or options.default_surface)
    multiplier = options.surface_time_multipliers.get(surface)
    assumed = []
    if surface == "unspecified":
        assumed.append("surface_unverified_no_adjustment")
    if b.get("break_before") and span <= .01 and not missing:
        # An identical-coordinate source transition adds no fictional connector.
        span = gain = loss = 0.
    estimates = []
    for member in members:
        member_missing = []
        flat = member["flat_speed_kmh"]
        if span > 0 and flat is None:
            member_missing.append("flat_speed_kmh")
        if gain and member["ascent_m_per_hour"] is None:
            member_missing.append("ascent_m_per_hour")
        if loss and member["descent_m_per_hour"] is None and member["downhill_speed_mps"] is None:
            member_missing.append("descent_rate")
        technical = member["slowdown_ratios"]["technical"]
        if multiplier is None and not (surface == "technical" and technical is not None):
            member_missing.append(f"surface_time_multiplier:{surface}")
        if member_missing:
            missing.extend(f"member:{member['member_id']}:{field}" for field in member_missing)
            estimates.append({"member_id": member["member_id"], "missing_inputs": member_missing})
            continue
        if gain is None or loss is None or "route_geometry_gap" in missing:
            estimates.append({"member_id": member["member_id"], "missing_inputs": list(missing)})
            continue
        horizontal_rate = flat * 1000 / 60 if flat is not None else None
        horizontal_method = "flat_speed"
        if loss and not gain and member["downhill_speed_mps"] is not None:
            horizontal_rate = min(horizontal_rate, member["downhill_speed_mps"] * 60) if horizontal_rate is not None else member["downhill_speed_mps"] * 60
            horizontal_method = "slower_of_flat_and_downhill_speed"
        elif gain and member["uphill_speed_mps"] is not None:
            horizontal_rate = min(horizontal_rate, member["uphill_speed_mps"] * 60) if horizontal_rate is not None else member["uphill_speed_mps"] * 60
            horizontal_method = "slower_of_flat_and_uphill_speed"
        horizontal = span / horizontal_rate if span else 0.
        ascending = gain / member["ascent_m_per_hour"] * 60 if gain else 0.
        descending = loss / member["descent_m_per_hour"] * 60 if loss and member["descent_m_per_hour"] else 0.
        applied_ratios = {key: value for key, value in member["slowdown_ratios"].items()
                          if value is not None and key != "technical" and (key != "late_trip" or b.get("late_trip") is True)}
        # An explicit surface multiplier replaces the observed technical drag;
        # applying both would silently charge the same terrain adjustment twice.
        if surface == "technical" and multiplier is None and technical is not None:
            applied_ratios["technical"] = technical
        retention = math.prod(1 - value for value in applied_ratios.values())
        minutes = max(horizontal, ascending + descending) * (multiplier if multiplier is not None else 1.) / retention
        u = member["uncertainty_fraction"]
        estimates.append({"member_id": member["member_id"], "duration_minutes": minutes,
                          "lower_minutes": minutes * (1 - u), "upper_minutes": minutes * (1 + u),
                          "components_minutes": {"horizontal": horizontal, "ascent": ascending, "descent": descending},
                          "horizontal_method": horizontal_method, "surface_time_multiplier": multiplier,
                          "applied_slowdown_ratios": applied_ratios, "source_refs": member["source_refs"],
                          "assumed_fields": member["assumed_fields"], "rate_origin": member["rate_origin"],
                          "uncertainty_fraction": u, "missing_inputs": []})
    usable = [m for m in estimates if "duration_minutes" in m]
    supported = not missing and len(usable) == len(members)
    slowest = max(usable, key=lambda m: m["duration_minutes"]) if usable else None
    source_refs = list(dict.fromkeys(options.source_refs + [ref for member in members for ref in member["source_refs"]]))
    source_a, source_b = a.get("source_point_index"), b.get("source_point_index")
    source_direction = ("forward" if source_b > source_a else "reverse" if source_b < source_a else "same_point") if (
        isinstance(source_a, int) and isinstance(source_b, int) and a.get("source_id") == b.get("source_id")) else "source_transition"
    return {"from_point_index": a["point_index"], "point_index": b["point_index"],
            "from_source_id": a.get("source_id"), "source_id": b.get("source_id"),
            "source_start_point_index": source_a, "source_end_point_index": source_b,
            "source_part_index": b.get("source_part_index", b.get("part_index")),
            "source_direction": source_direction, "source_refs": source_refs,
            "distance_m": span, "ascent_m": gain, "descent_m": loss, "surface": surface,
            "duration_minutes": slowest["duration_minutes"] if supported else None,
            "lower_minutes": max(m["lower_minutes"] for m in usable) if supported else None,
            "upper_minutes": max(m["upper_minutes"] for m in usable) if supported else None,
            "slowest_member_id": slowest["member_id"] if supported else None,
            "member_estimates": estimates, "missing_inputs": list(dict.fromkeys(missing)),
            "assumptions": assumed, "method": "terrain_team_workload_envelope" if supported else "unknown",
            "time_role": "planned_estimate", **BOUNDARY}


def _geometry_sha(points):
    selected = [{k: p.get(k) for k in ("point_index", "lat", "lon", "ele", "break_before", "surface", "late_trip",
                                      "source_id", "source_part_index", "part_index", "source_point_index", "geometry_supported")} for p in points]
    return hashlib.sha256(json.dumps(selected, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _sum_complete(values, key):
    return sum(v[key] for v in values) if all(v.get(key) is not None for v in values) else None


def estimate_segment_timing(points: list[dict], *, options: TerrainTimingOptions | dict | None = None,
                            segment_id: str = "", source_refs: list[str] | None = None) -> dict:
    """Estimate the supplied direction; never reuse or rescale old timestamps."""
    options, points = _options(options), _points(points)
    members = _members(options)
    edges = [_edge(a, b, options, members) for a, b in zip(points, points[1:])]
    complete = all(e["duration_minutes"] is not None for e in edges)
    return {"schema_version": TIMING_VERSION, "segment_id": segment_id,
            "status": "estimated" if complete else "unknown", "time_role": "planned_estimate",
            "duration_minutes": _sum_complete(edges, "duration_minutes"),
            "lower_minutes": _sum_complete(edges, "lower_minutes"),
            "upper_minutes": _sum_complete(edges, "upper_minutes"),
            "known_moving_minutes": sum(e["duration_minutes"] or 0. for e in edges),
            "distance_m": sum(e["distance_m"] for e in edges if "route_geometry_gap" not in e["missing_inputs"]),
            "ascent_m": _sum_complete(edges, "ascent_m"), "descent_m": _sum_complete(edges, "descent_m"),
            "edges": edges, "member_inputs": members,
            "missing_inputs": list(dict.fromkeys(m for e in edges for m in e["missing_inputs"])),
            "assumptions": {"formula": "sum_edges(max(horizontal_minutes, ascent_minutes + descent_minutes) * surface_time_multiplier / speed_retention)",
                            "team_basis": "slowest_member_per_edge", "uncertainty_kind": "declared_scenario_envelope_not_statistical_confidence",
                            "assumption_label": options.assumption_label, "fixed_stops_included": False,
                            "trh_cost_used_as_time": False, "personal_capability_verified": False,
                            "historical_timestamps_reused": False, "source_verification": "caller_required"},
            "source_refs": list(dict.fromkeys((source_refs or []) + options.source_refs +
                                               [ref for member in members for ref in member["source_refs"]])),
            "ordered_geometry_sha256": _geometry_sha(points), **BOUNDARY}


def _stamp(value):
    if value is None:
        return None
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("Departure requires an explicit timezone.")
    return stamp


def _iso(value):
    return value.isoformat() if value else None


def _clock_fields(clock, prefix):
    return {prefix + "_at": _iso(clock[0]), prefix + "_at_lower": _iso(clock[1]), prefix + "_at_upper": _iso(clock[2])}


def _advance(clock, minutes, lower=None, upper=None):
    values = (minutes, minutes if lower is None else lower, minutes if upper is None else upper)
    return [stamp + timedelta(minutes=value) if stamp is not None and value is not None else None
            for stamp, value in zip(clock, values)]


def _camp_review(candidate, options):
    result = candidate.model_dump(mode="json")
    missing = [key for key in ("water_available", "capacity_persons", "legal_use", "overnight_suitable")
               if result[key] is None]
    issues = []
    party_size = options.party_size or len(options.team_members) or None
    for key in ("legal_use", "overnight_suitable"):
        if result[key] is False:
            issues.append(key + "_not_available")
    if result["water_available"] is False:
        if options.require_camp_water:
            issues.append("required_camp_water_not_available")
        else:
            missing.append("camp_water_plan")
    if party_size is None:
        missing.append("party_size_for_capacity_review")
    if party_size is not None and candidate.capacity_persons is not None and candidate.capacity_persons < party_size:
        issues.append("insufficient_capacity")
    return {**result, "missing_inputs": missing, "issues": issues, "review_state": "candidate",
            "slope_alone_establishes_suitability": False, **BOUNDARY}


def _schedule_core(points, edges, options, departure, events, start_day_index=1):
    by_index = defaultdict(list)
    valid_indices = {p["point_index"] for p in points}
    for event in events:
        if event.point_index not in valid_indices:
            raise ValueError("An event references a point outside the canonical route axis.")
        by_index[event.point_index].append(event)
    camps = {c.candidate_id: c for c in options.campsite_candidates}
    if departure is None:
        start_departures = [event.departure_at for event in by_index[points[0]["point_index"]]
                            if event.kind == "depart" and event.departure_at is not None]
        if len(start_departures) == 1:
            departure = start_departures[0]
    clock = [departure, departure, departure]
    timeline, days, unknowns, conflicts, reviews, arrivals = [], [], [], [], [], {}
    full_supported = departure is not None
    if departure is None:
        unknowns.append({"code": "departure_missing", "point_index": points[0]["point_index"]})
    total_known = total_fixed = total_rest = 0.
    moving_since_rest = 0.

    def new_day(index):
        return {"day_id": f"D{len(days) + start_day_index}", "mission_day_id": f"D{len(days) + start_day_index}",
                "start_point_index": index, **_clock_fields(clock, "departure"),
                "moving_minutes": 0., "moving_minutes_lower": 0., "moving_minutes_upper": 0.,
                "fixed_rest_minutes": 0., "estimated_rest_minutes": 0., "source_rest_minutes": 0., "unknown_count": 0}

    day = new_day(points[0]["point_index"])

    def issue(code, index, **context):
        item = {"code": code, "point_index": index, "day_id": day["day_id"], **context}
        if item not in conflicts:
            conflicts.append(item)

    def check_limits(index, before=None):
        if options.max_daily_moving_minutes is not None and day["moving_minutes_upper"] > options.max_daily_moving_minutes:
            issue("daily_moving_limit_exceeded", index, upper_minutes=day["moving_minutes_upper"], limit_minutes=options.max_daily_moving_minutes)
        start = _stamp(day["departure_at"])
        if options.max_daily_elapsed_minutes is not None and clock[2] and start:
            elapsed = (clock[2] - start).total_seconds() / 60
            if elapsed > options.max_daily_elapsed_minutes:
                issue("daily_elapsed_limit_exceeded", index, upper_minutes=elapsed, limit_minutes=options.max_daily_elapsed_minutes)
        if not (options.require_daylight or options.daylight_windows):
            return
        anchor = before[0] if before and before[0] else clock[0]
        window = next((w for w in options.daylight_windows if anchor and w.sunrise_at.astimezone(anchor.tzinfo).date() == anchor.date()), None)
        if window is None:
            item = {"code": "daylight_window_missing", "point_index": index, "day_id": day["day_id"]}
            if item not in unknowns:
                unknowns.append(item)
            return
        margin = timedelta(minutes=options.daylight_margin_minutes)
        if before and before[1] and before[1] < window.sunrise_at + margin:
            issue("departure_before_daylight_window", index, source_ref=window.source_ref, earliest_departure_at=_iso(window.sunrise_at + margin))
        if clock[2] and clock[2] > window.sunset_at - margin:
            issue("arrival_after_daylight_window", index, source_ref=window.source_ref, latest_arrival_at=_iso(window.sunset_at - margin))

    def finish(index, label=None, camp=False):
        day.update({"end_point_index": index, "end_label": label, "camp": camp,
                    **_clock_fields(clock, "arrival"), "movement_complete": day["unknown_count"] == 0,
                    "rest_minutes": day["fixed_rest_minutes"] + day["estimated_rest_minutes"],
                    "moving_minutes_is_known_subtotal": day["unknown_count"] > 0})
        if day["unknown_count"] or not full_supported:
            day.update({"conditional_arrival_at": day["arrival_at"],
                        "conditional_arrival_at_lower": day["arrival_at_lower"],
                        "conditional_arrival_at_upper": day["arrival_at_upper"],
                        "conditional_on_prior_unknown": True})
            day.update(arrival_at=None, arrival_at_lower=None, arrival_at_upper=None)
        days.append(dict(day))

    for pos, point in enumerate(points):
        index = point["point_index"]
        if pos:
            edge = edges[pos - 1]
            before = list(clock)
            minutes = edge["duration_minutes"]
            if minutes is None:
                full_supported = False
                clock = [None, None, None]
                day["unknown_count"] += 1
                unknowns.append({"code": "segment_time_unknown", "point_index": index, "missing_inputs": edge["missing_inputs"]})
            else:
                clock = _advance(clock, minutes, edge["lower_minutes"], edge["upper_minutes"])
                day["moving_minutes"] += minutes
                day["moving_minutes_lower"] += edge["lower_minutes"]
                day["moving_minutes_upper"] += edge["upper_minutes"]
                total_known += minutes
                moving_since_rest += minutes
            timeline.append({**edge, "kind": "move", "day_id": day["day_id"],
                             **_clock_fields(before, "departure"), **_clock_fields(clock, "arrival"),
                             "conditional_on_explicit_departure": not full_supported})
            check_limits(index, before)
            if minutes is not None and options.rest_every_moving_minutes and pos < len(points) - 1:
                count = int(moving_since_rest // options.rest_every_moving_minutes)
                if count and not any(e.kind in {"stop", "camp"} for e in by_index[index]):
                    allowance = count * options.rest_duration_minutes
                    start = list(clock)
                    clock = _advance(clock, allowance)
                    day["estimated_rest_minutes"] += allowance
                    total_rest += allowance
                    moving_since_rest -= count * options.rest_every_moving_minutes
                    timeline.append({"kind": "rest_allowance", "point_index": index, "day_id": day["day_id"],
                                     "duration_minutes": allowance, **_clock_fields(start, "arrival"),
                                     **_clock_fields(clock, "departure"), "time_role": "declared_rest_assumption",
                                     "location_review_required": True, "interval_count": count, **BOUNDARY})
                    check_limits(index)
        arrivals[index] = {"point_index": index, "day_id": day["day_id"], **_clock_fields(clock, "arrival"),
                           "conditional_on_prior_unknown": not full_supported}
        arrival = list(clock)
        ordered = sorted(by_index[index], key=lambda e: {"deadline": 0, "stop": 1, "camp": 2, "depart": 3}[e.kind])
        for event in ordered:
            if event.day_index is not None and event.day_index != len(days) + start_day_index:
                issue("event_day_constraint_mismatch", index, expected_day_index=event.day_index)
            if event.calendar_date and clock[0] and clock[0].date().isoformat() != event.calendar_date:
                issue("event_date_constraint_mismatch", index, calendar_date=event.calendar_date)
            if event.kind == "deadline":
                target = event.latest_arrival_at or event.arrival_at
                if target is None:
                    issue("arrival_limit_missing", index)
                elif arrival[2] is None:
                    issue("arrival_constraint_unverifiable", index, latest_arrival_at=_iso(target))
                elif arrival[2] > target:
                    issue("arrival_constraint_unsatisfied", index, arrival_at_upper=_iso(arrival[2]), latest_arrival_at=_iso(target))
                elif event.arrival_at is not None and arrival[0] != target:
                    issue("exact_arrival_requires_review", index, arrival_at=_iso(arrival[0]), requested_arrival_at=_iso(target))
                timeline.append({"kind": "deadline", "point_index": index, "day_id": day["day_id"],
                                 "latest_arrival_at": _iso(event.latest_arrival_at), "requested_arrival_at": _iso(event.arrival_at),
                                 **_clock_fields(arrival, "arrival"), "label": event.label,
                                 "time_role": "explicit_planning_constraint", **BOUNDARY})
            elif event.kind == "stop":
                if event.duration_minutes is None:
                    full_supported = False; clock = [None, None, None]
                    day["unknown_count"] += 1
                    unknowns.append({"code": "fixed_stop_duration_missing", "point_index": index})
                    continue
                start = list(clock)
                clock = _advance(clock, event.duration_minutes)
                day["fixed_rest_minutes"] += event.duration_minutes; total_fixed += event.duration_minutes
                if options.rest_duration_minutes and event.duration_minutes >= options.rest_duration_minutes:
                    moving_since_rest = 0.
                timeline.append({"kind": "fixed_stop", "point_index": index, "day_id": day["day_id"],
                                 "duration_minutes": event.duration_minutes, "label": event.label,
                                 **_clock_fields(start, "arrival"), **_clock_fields(clock, "departure"),
                                 "time_role": "explicit_planning_constraint", **BOUNDARY})
                check_limits(index)
            elif event.kind == "camp":
                candidate = camps.get(event.candidate_id) if event.candidate_id else next((c for c in camps.values() if c.point_index == index), None)
                if candidate is not None and candidate.point_index != index:
                    raise ValueError("Selected campsite belongs to another route point occurrence.")
                candidate = candidate or CampsiteCandidate(candidate_id=event.candidate_id or f"camp.point.{index}", point_index=index, label=event.label or "")
                review = _camp_review(candidate, options); reviews.append(review)
                if review["issues"]:
                    issue("campsite_conditions_unsatisfied", index, candidate_id=candidate.candidate_id, reasons=review["issues"])
                finish(index, event.label or candidate.label, True)
                start = list(clock)
                next_departure = event.departure_at
                if next_departure is not None:
                    next_clock = [next_departure] * 3
                elif event.duration_minutes is not None:
                    next_clock = _advance(clock, event.duration_minutes)
                else:
                    next_clock = [None] * 3
                if next_clock[0] is None:
                    full_supported = False
                    unknowns.append({"code": "camp_departure_missing", "point_index": index})
                if start[2] and next_clock[1]:
                    min_rest = (event.duration_minutes if event.departure_at is None and event.duration_minutes is not None
                                else (next_clock[1] - start[2]).total_seconds() / 60)
                    if min_rest < 0:
                        issue("camp_departure_before_arrival", index)
                        full_supported = False; next_clock = [None] * 3
                    elif options.minimum_overnight_minutes and min_rest < options.minimum_overnight_minutes:
                        issue("minimum_overnight_rest_unsatisfied", index, lower_rest_minutes=min_rest,
                              minimum_minutes=options.minimum_overnight_minutes)
                timeline.append({"kind": "camp", "point_index": index, "day_id": day["day_id"],
                                 "candidate_id": candidate.candidate_id, "label": event.label or candidate.label,
                                 **_clock_fields(start, "arrival"), **_clock_fields(next_clock, "departure"),
                                 "duration_minutes": (next_clock[0] - start[0]).total_seconds() / 60 if next_clock[0] and start[0] else None,
                                 "generated_from_candidate": event.generated_from_candidate,
                                 "time_role": "explicit_planning_constraint", **BOUNDARY})
                clock = next_clock; moving_since_rest = 0.
                day = new_day(index)
            elif event.kind == "depart":
                prior_clock = list(clock)
                if event.departure_at is None:
                    issue("departure_time_missing", index); full_supported = False; clock = [None] * 3
                elif clock[2] and event.departure_at < clock[2]:
                    issue("departure_before_latest_estimated_arrival", index)
                    full_supported = False; clock = [None] * 3
                else:
                    clock = [event.departure_at] * 3
                    if index == day["start_point_index"]:
                        day.update(_clock_fields(clock, "departure"))
                timeline.append({"kind": "depart", "point_index": index, "day_id": day["day_id"],
                                 **_clock_fields(prior_clock, "arrival"), **_clock_fields(clock, "departure"),
                                 "requested_departure_at": _iso(event.departure_at), "label": event.label,
                                 "conditional_on_prior_unknown": not full_supported,
                                 "time_role": "explicit_planning_constraint", **BOUNDARY})
        if pos == len(points) - 1 and day["start_point_index"] < index:
            finish(index, "Finish")
    if options.max_days and len(days) > options.max_days:
        conflicts.append({"code": "maximum_days_exceeded", "days": len(days), "max_days": options.max_days})
    if not full_supported:
        finish_clock = [None] * 3
    else:
        finish_clock = ([_stamp(days[-1].get(key)) for key in ("arrival_at", "arrival_at_lower", "arrival_at_upper")]
                        if days else clock)
    camp_unknowns = [f"{c['candidate_id']}:{key}" for c in reviews for key in c["missing_inputs"]]
    status = "unknown" if not full_supported else "conflict" if conflicts else "needs_review" if unknowns or camp_unknowns else "estimated"
    return {"schema_version": TIMING_VERSION, "status": status, "time_role": "planned_estimate",
            "days": days, "timeline": timeline, "unknowns": unknowns, "conflicts": conflicts,
            "camp_reviews": reviews, "campsite_missing_inputs": camp_unknowns,
            "point_arrivals": list(arrivals.values()), **_clock_fields(finish_clock, "finish"),
            "total_moving_minutes": sum(day["moving_minutes"] for day in days) if full_supported else None,
            "known_moving_minutes": total_known, "fixed_rest_minutes": total_fixed,
            "estimated_rest_minutes": total_rest, "complete_route_eta": full_supported,
            "conditional_finish_at": _iso(clock[0]) if not full_supported else None, **BOUNDARY}


def plan_terrain_schedule(points: list[dict], *, options: TerrainTimingOptions | dict | None = None,
                          departure_at: datetime | str | None = None, events: list[dict | TimingEvent] | None = None,
                          start_day_index: int = 1) -> dict:
    """Plan the whole ordered route and, if requested, propose feasible camp splits.

    Automatic camps use ONLY supplied candidate points and explicit daily/daylight
    constraints. Unknown water/capacity/legal/suitability remain review items.
    No candidate reachable before a limit means a visible unsatisfied constraint,
    never a fictional campsite or a faster walking speed.
    """
    if isinstance(start_day_index, bool) or not isinstance(start_day_index, int) or start_day_index < 1:
        raise ValueError("The starting mission day index must be a positive integer.")
    options, points = _options(options), _points(points)
    members = _members(options)
    edges = [_edge(a, b, options, members) for a, b in zip(points, points[1:])]
    departure = _stamp(departure_at)
    planned_events = [event if isinstance(event, TimingEvent) else TimingEvent.model_validate(event) for event in (events or [])]
    result = _schedule_core(points, edges, options, departure, planned_events, start_day_index)
    generated = []
    actionable = {"daily_moving_limit_exceeded", "daily_elapsed_limit_exceeded", "arrival_after_daylight_window"}
    if options.auto_schedule_camps:
        while True:
            violation = next((c for c in result["conflicts"] if c["code"] in actionable), None)
            if violation is None:
                break
            if options.next_day_departure_time is None:
                result["unknowns"].append({"code": "auto_camp_next_day_departure_missing"})
                break
            day = next(d for d in result["days"] if d["day_id"] == violation["day_id"])
            arrivals = {p["point_index"]: p for p in result["point_arrivals"]}
            occupied = {e.point_index for e in planned_events if e.kind == "camp"}
            candidates = [c for c in options.campsite_candidates
                          if day["start_point_index"] < c.point_index < violation["point_index"]
                          and c.point_index not in occupied and not _camp_review(c, options)["issues"]
                          and arrivals.get(c.point_index, {}).get("arrival_at_upper")]
            if options.minimum_overnight_minutes is not None:
                rested = []
                for candidate in candidates:
                    candidate_arrival = _stamp(arrivals[candidate.point_index]["arrival_at_upper"])
                    tomorrow = datetime.combine(candidate_arrival.date() + timedelta(days=1),
                                                time.fromisoformat(options.next_day_departure_time), tzinfo=candidate_arrival.tzinfo)
                    if (tomorrow - candidate_arrival).total_seconds() / 60 >= options.minimum_overnight_minutes:
                        rested.append(candidate)
                candidates = rested
            candidate = max(candidates, key=lambda c: c.point_index) if candidates else None
            if candidate is None:
                result["conflicts"].append({"code": "no_reachable_campsite_before_limit", "day_id": day["day_id"],
                                             "point_index": violation["point_index"]})
                break
            arrival = _stamp(arrivals[candidate.point_index]["arrival_at_upper"])
            next_date = arrival.date() + timedelta(days=1)
            next_departure = datetime.combine(next_date, time.fromisoformat(options.next_day_departure_time), tzinfo=arrival.tzinfo)
            event = TimingEvent(kind="camp", point_index=candidate.point_index, candidate_id=candidate.candidate_id,
                                departure_at=next_departure, label=candidate.label, source_refs=candidate.source_refs,
                                generated_from_candidate=True)
            planned_events.append(event); generated.append(event.model_dump(mode="json"))
            result = _schedule_core(points, edges, options, departure, planned_events, start_day_index)
    result.update({"start_day_index": start_day_index, "generated_camp_events": generated, "ordered_geometry_sha256": _geometry_sha(points),
                   "options": options.model_dump(mode="json", exclude={"team_members"}), "member_inputs": members,
                   "source_refs": list(dict.fromkeys(options.source_refs + [r for m in members for r in m["source_refs"]] +
                                                    [w.source_ref for w in options.daylight_windows] +
                                                    [r for c in options.campsite_candidates for r in c.source_refs])),
                   "assumptions": {"formula": "ordered_edge_workload_envelope", "team_basis": "slowest_member_per_edge",
                                   "uncertainty_kind": "declared_scenario_envelope_not_statistical_confidence",
                                   "assumption_label": options.assumption_label, "fixed_stops_are_additional": True,
                                   "historical_dates_reused": False, "trh_cost_used_as_time": False,
                                   "personal_capability_verified": False, "source_verification": "caller_required",
                                   "overnight_candidates_are_not_permission": True}})
    return result
