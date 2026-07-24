"""Deterministic projectors from Scout evidence surfaces into MSER state.

The projectors never promote candidate evidence to runtime safety truth. They
also never translate missing or freshness-unknown input into a low-risk value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from scout.schemas.mser import (
    CompactDimension,
    CompactSignal,
    CommunicationLatentState,
    EnvironmentalRepresentation,
    HumanLatentState,
    OperationalLatentState,
    SignalAvailability,
    TerrainLatentState,
    WeatherLatentState,
)


_LIVE_TTL = timedelta(minutes=5)
_NEAR_LIVE_TTL = timedelta(minutes=15)
_FORECAST_TTL = timedelta(hours=3)
_TERRAIN_TTL = timedelta(days=1)
_ROUTE_TTL = timedelta(days=1)

_UNKNOWN_FIX_MARKERS = ("unknown", "no_fix", "invalid", "unavailable")
_ENERGY_BANDS = {
    "high": 0.82,
    "good": 0.78,
    "medium": 0.55,
    "moderate": 0.55,
    "low": 0.28,
    "critical": 0.12,
}


def _payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped
    raise TypeError("MSER projector input must be a mapping or Pydantic model")


def _unwrap_total_info(value: object) -> dict[str, Any]:
    data = _payload(value)
    summary = data.get("context_summary")
    return _payload(summary) if isinstance(summary, Mapping) else data


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _at(value: Mapping[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _first(value: Mapping[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        result = _at(value, *path)
        if result is not None:
            return result
    return None


def _first_number(value: Mapping[str, Any], *paths: tuple[str, ...]) -> float | None:
    raw = _first(value, *paths)
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _score(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1.0 and number <= 100.0:
        number /= 100.0
    return min(max(number, 0.0), 1.0)


def _source_path(value: Mapping[str, Any], fallback: str) -> str:
    raw = value.get("source_path") or value.get("source_ref")
    if isinstance(raw, str) and raw.strip():
        if "://" in raw:
            return raw
        return f"workspace://{raw.lstrip('/')}"
    return fallback


def _scenario_refs(payload: Mapping[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for item in payload.get("source_refs") or ():
        if not isinstance(item, Mapping):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        role = item.get("role")
        if isinstance(path, str) and path:
            suffix = f"#sha256={digest}" if isinstance(digest, str) and digest else ""
            refs.append(f"workspace://{path.lstrip('/')}{suffix}")
        elif isinstance(role, str) and role:
            refs.append(f"scenario-source://{role}")
    scenario_id = str(payload.get("scenario_id") or "unknown")
    for overlay in payload.get("condition_overlay_refs") or ():
        if isinstance(overlay, str) and overlay:
            refs.append(f"scenario://{scenario_id}/overlay/{overlay}")
    return tuple(dict.fromkeys(refs))


def _context_refs(
    context: Mapping[str, Any],
    *,
    fallback: str,
    children: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, ...]:
    refs = [_source_path(context, fallback)]
    refs.extend(
        _source_path(child, fallback)
        for child in children
        if child and child.get("status") != "missing"
    )
    return tuple(dict.fromkeys(refs))


def _signal_id(
    source_kind: str,
    dimension: CompactDimension,
    refs: tuple[str, ...],
    value: object,
) -> str:
    canonical = json.dumps(
        [source_kind, dimension.value, refs, value],
        ensure_ascii=True,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"mser.{source_kind}.{dimension.value}.{digest}"


def _missing_signal(
    dimension: CompactDimension,
    *,
    source_kind: str,
    reason: str,
    refs: tuple[str, ...] = (),
) -> CompactSignal:
    return CompactSignal(
        signal_id=_signal_id(source_kind, dimension, refs, None),
        dimension=dimension,
        availability=SignalAvailability.MISSING,
        confidence=0.0,
        source_refs=refs,
        derivation=reason,
    )


def _signal(
    dimension: CompactDimension,
    value: object,
    *,
    source_kind: str,
    refs: tuple[str, ...],
    confidence: float,
    observed_at: datetime | None,
    now: datetime,
    ttl: timedelta,
    unit: str | None = None,
    valid_until: datetime | None = None,
    derivation: str,
    risk_upper_bound: float | None = None,
    force_missing: bool = False,
) -> CompactSignal:
    if force_missing or value is None or observed_at is None or not refs:
        return _missing_signal(
            dimension,
            source_kind=source_kind,
            reason=(
                f"{derivation}; unavailable because value, provenance, or freshness "
                "is unknown"
            ),
            refs=refs,
        )
    bounded_confidence = min(max(float(confidence), 0.0), 1.0)
    expires_at = valid_until or observed_at + ttl
    availability = (
        SignalAvailability.STALE if expires_at < now else SignalAvailability.AVAILABLE
    )
    return CompactSignal(
        signal_id=_signal_id(source_kind, dimension, refs, value),
        dimension=dimension,
        value=value,
        unit=unit,
        availability=availability,
        confidence=bounded_confidence,
        risk_upper_bound=risk_upper_bound,
        observed_at=observed_at,
        valid_until=expires_at,
        source_refs=refs,
        derivation=derivation,
    )


def _overlay_text(payload: Mapping[str, Any]) -> str:
    values = payload.get("condition_overlay_refs") or ()
    return " ".join(str(item).lower() for item in values)


def _has_overlay(text: str, *markers: str) -> bool:
    return any(marker in text for marker in markers)


def _scenario_observed_at(payload: Mapping[str, Any]) -> datetime | None:
    return _parse_datetime(payload.get("observed_at"))


def _risk_candidate(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("risk_terrain_candidate")
    return _payload(value) if isinstance(value, Mapping) else {}


def _scenario_terrain(
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> TerrainLatentState:
    candidate = _risk_candidate(payload)
    overlays = _overlay_text(payload)
    observed_at = _scenario_observed_at(payload)
    refs = _scenario_refs(payload)
    source_kind = "scenario"

    def terrain_signal(
        dimension: CompactDimension,
        key: str,
        *,
        risk_upper_bound: bool = False,
    ) -> CompactSignal:
        value = _score(candidate.get(key))
        return _signal(
            dimension,
            value,
            source_kind=source_kind,
            refs=refs,
            confidence=0.88,
            observed_at=observed_at,
            now=now,
            ttl=_TERRAIN_TTL,
            derivation=f"scenario risk_terrain_candidate.{key}",
            risk_upper_bound=(
                min(value + 0.08, 1.0)
                if value is not None and risk_upper_bound
                else None
            ),
        )

    visibility: float | None = _score(candidate.get("visibility"))
    visibility_derivation = "scenario risk_terrain_candidate.visibility"
    if _has_overlay(overlays, "rain_fog", "heavy_fog", "大雨", "迷霧"):
        visibility = min(visibility if visibility is not None else 1.0, 0.14)
        visibility_derivation = "synthetic rain/fog overlay"
    elif _has_overlay(overlays, "daylight:dark", "摸黑", "night"):
        visibility = min(visibility if visibility is not None else 1.0, 0.08)
        visibility_derivation = "synthetic darkness overlay"
    elif _has_overlay(overlays, "weather:stable", "visibility:good"):
        visibility = visibility if visibility is not None else 0.9
        visibility_derivation = "synthetic stable-visibility overlay"

    slip_value = _score(candidate.get("slip_risk"))
    slip_derivation = "scenario risk_terrain_candidate.slip_risk"
    if _has_overlay(overlays, "rain_fog", "heavy_rain", "大雨"):
        slip_value = max(slip_value or 0.0, 0.78)
        slip_derivation = "terrain slip candidate compounded by synthetic rain overlay"

    terrain_confidence = 0.9 if refs else None
    return TerrainLatentState(
        exposure_risk=terrain_signal(
            CompactDimension.EXPOSURE_RISK,
            "exposure_risk",
            risk_upper_bound=True,
        ),
        slip_risk=_signal(
            CompactDimension.SLIP_RISK,
            slip_value,
            source_kind=source_kind,
            refs=refs,
            confidence=0.84,
            observed_at=observed_at,
            now=now,
            ttl=_NEAR_LIVE_TTL if "overlay" in slip_derivation else _TERRAIN_TTL,
            derivation=slip_derivation,
            risk_upper_bound=(
                min(slip_value + 0.1, 1.0) if slip_value is not None else None
            ),
        ),
        rockfall_risk=terrain_signal(
            CompactDimension.ROCKFALL_RISK,
            "rockfall_risk",
            risk_upper_bound=True,
        ),
        escape_cost=terrain_signal(CompactDimension.ESCAPE_COST, "escape_cost"),
        visibility=_signal(
            CompactDimension.VISIBILITY,
            visibility,
            source_kind=source_kind,
            refs=refs,
            confidence=0.82,
            observed_at=observed_at,
            now=now,
            ttl=_NEAR_LIVE_TTL,
            derivation=visibility_derivation,
        ),
        terrain_complexity=terrain_signal(
            CompactDimension.TERRAIN_COMPLEXITY,
            "terrain_complexity",
        ),
        terrain_confidence=_signal(
            CompactDimension.TERRAIN_CONFIDENCE,
            terrain_confidence,
            source_kind=source_kind,
            refs=refs,
            confidence=0.9,
            observed_at=observed_at,
            now=now,
            ttl=_TERRAIN_TTL,
            derivation="scenario source and route interpolation confidence",
        ),
    )


def _scenario_weather(
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> WeatherLatentState:
    overlays = _overlay_text(payload)
    observed_at = _scenario_observed_at(payload)
    refs = _scenario_refs(payload)
    stability: float | None = None
    trend: str | None = None
    danger_window: str | None = None
    forecast_confidence: float | None = None
    if _has_overlay(overlays, "rain_fog", "heavy_rain", "大雨", "迷霧"):
        stability = 0.12
        trend = "deteriorating"
        danger_window = "active_and_next_3h"
        forecast_confidence = 0.82
    elif _has_overlay(overlays, "thunderstorm", "storm", "雷雨"):
        stability = 0.05
        trend = "rapidly_deteriorating"
        danger_window = "active_and_next_3h"
        forecast_confidence = 0.86
    elif _has_overlay(overlays, "weather:stable", "weather:normal"):
        stability = 0.86
        trend = "stable"
        danger_window = "no_synthetic_danger_window"
        forecast_confidence = 0.8

    def weather_signal(
        dimension: CompactDimension,
        value: object,
        derivation: str,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="scenario",
            refs=refs,
            confidence=forecast_confidence or 0.0,
            observed_at=observed_at,
            now=now,
            ttl=_FORECAST_TTL,
            derivation=derivation,
        )

    return WeatherLatentState(
        weather_stability=weather_signal(
            CompactDimension.WEATHER_STABILITY,
            stability,
            "synthetic scenario weather overlay stability",
        ),
        weather_trend=weather_signal(
            CompactDimension.WEATHER_TREND,
            trend,
            "synthetic scenario weather overlay trend",
        ),
        danger_window=weather_signal(
            CompactDimension.DANGER_WINDOW,
            danger_window,
            "synthetic scenario weather overlay danger window",
        ),
        forecast_confidence=weather_signal(
            CompactDimension.FORECAST_CONFIDENCE,
            forecast_confidence,
            "synthetic scenario weather overlay confidence",
        ),
    )


def _scenario_human(
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> HumanLatentState:
    overlays = _overlay_text(payload)
    observed_at = _scenario_observed_at(payload)
    refs = _scenario_refs(payload)
    values: tuple[float, float, float, float, float] | None = None
    if _has_overlay(overlays, "fatigue_decline", "walking_unstable", "體能下降"):
        values = (0.88, 0.2, 0.42, 0.2, 0.34)
    elif _has_overlay(overlays, "human:normal", "human:stable"):
        values = (0.2, 0.82, 0.9, 0.8, 0.05)
    fatigue, energy, cognition, margin, urgency = values or (
        None,
        None,
        None,
        None,
        None,
    )

    def human_signal(
        dimension: CompactDimension,
        value: float | None,
        label: str,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="scenario",
            refs=refs,
            confidence=0.82,
            observed_at=observed_at,
            now=now,
            ttl=_LIVE_TTL,
            derivation=f"synthetic scenario human overlay {label}",
            risk_upper_bound=(
                min(value + 0.08, 1.0)
                if value is not None and label in {"fatigue", "medical urgency"}
                else None
            ),
        )

    return HumanLatentState(
        fatigue_index=human_signal(
            CompactDimension.FATIGUE_INDEX,
            fatigue,
            "fatigue",
        ),
        energy_reserve=human_signal(
            CompactDimension.ENERGY_RESERVE,
            energy,
            "energy reserve",
        ),
        cognitive_confidence=human_signal(
            CompactDimension.COGNITIVE_CONFIDENCE,
            cognition,
            "cognitive confidence",
        ),
        safety_margin=human_signal(
            CompactDimension.SAFETY_MARGIN,
            margin,
            "safety margin",
        ),
        medical_urgency=human_signal(
            CompactDimension.MEDICAL_URGENCY,
            urgency,
            "medical urgency",
        ),
    )


def _scenario_communication(
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> CommunicationLatentState:
    overlays = _overlay_text(payload)
    observed_at = _scenario_observed_at(payload)
    refs = _scenario_refs(payload)
    values: tuple[float, float, float] | None = None
    if _has_overlay(overlays, "communication:reliable", "communication:normal"):
        values = (0.82, 0.78, 0.76)
    elif _has_overlay(overlays, "communication:weak", "coverage:weak"):
        values = (0.34, 0.3, 0.28)
    elif _has_overlay(overlays, "communication:offline", "no_signal"):
        values = (0.05, 0.1, 0.08)
    reliability, coverage, emergency = values or (None, None, None)

    def communication_signal(
        dimension: CompactDimension,
        value: float | None,
        label: str,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="scenario",
            refs=refs,
            confidence=0.8,
            observed_at=observed_at,
            now=now,
            ttl=_LIVE_TTL,
            derivation=f"synthetic scenario communication overlay {label}",
        )

    return CommunicationLatentState(
        communication_reliability=communication_signal(
            CompactDimension.COMMUNICATION_RELIABILITY,
            reliability,
            "reliability",
        ),
        coverage_confidence=communication_signal(
            CompactDimension.COVERAGE_CONFIDENCE,
            coverage,
            "coverage confidence",
        ),
        emergency_reachability=communication_signal(
            CompactDimension.EMERGENCY_REACHABILITY,
            emergency,
            "emergency reachability",
        ),
    )


def _scenario_operation(
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> OperationalLatentState:
    candidate = _risk_candidate(payload)
    overlays = _overlay_text(payload)
    observed_at = _scenario_observed_at(payload)
    refs = _scenario_refs(payload)
    fix_quality = str(payload.get("fix_quality") or "").lower()
    unknown_fix = any(marker in fix_quality for marker in _UNKNOWN_FIX_MARKERS)
    accuracy = _first_number(payload, ("horizontal_accuracy_m",))
    explicit_confidence = _score(payload.get("confidence"))
    gps_confidence = explicit_confidence
    if gps_confidence is None and accuracy is not None:
        gps_confidence = min(max(1.0 - accuracy / 50.0, 0.0), 0.95)
    route_distance = _first_number(payload, ("nearest_route_distance_m",))
    route_alignment = (
        min(max(1.0 - route_distance / 100.0, 0.0), 1.0)
        if route_distance is not None
        else None
    )
    risk_score = _score(candidate.get("risk_score"))

    if _has_overlay(overlays, "daylight:dark", "摸黑", "night"):
        remaining_daylight = 0.0
    elif _has_overlay(overlays, "daylight:ample"):
        remaining_daylight = 240.0
    elif _has_overlay(overlays, "daylight:limited"):
        remaining_daylight = 45.0
    else:
        remaining_daylight = None

    mission_on_schedule = _has_overlay(overlays, "mission:on_schedule")
    team_distance = 15.0 if mission_on_schedule else None
    mission_margin = 0.78 if mission_on_schedule else None
    route_feasibility = 0.8 if mission_on_schedule else None

    def operation_signal(
        dimension: CompactDimension,
        value: object,
        *,
        label: str,
        ttl: timedelta = _LIVE_TTL,
        unit: str | None = None,
        confidence: float = 0.85,
        force_missing: bool = False,
        risk_upper_bound: float | None = None,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="scenario",
            refs=refs,
            confidence=confidence,
            observed_at=observed_at,
            now=now,
            ttl=ttl,
            unit=unit,
            derivation=f"scenario {label}",
            force_missing=force_missing,
            risk_upper_bound=risk_upper_bound,
        )

    return OperationalLatentState(
        gps_confidence=operation_signal(
            CompactDimension.GPS_CONFIDENCE,
            gps_confidence,
            label="GNSS fix confidence",
            force_missing=unknown_fix,
        ),
        route_alignment=operation_signal(
            CompactDimension.ROUTE_ALIGNMENT,
            route_alignment,
            label="nearest-route-distance alignment",
            force_missing=unknown_fix,
        ),
        route_progress=operation_signal(
            CompactDimension.ROUTE_PROGRESS,
            _first_number(payload, ("route_progress_m",)),
            label="canonical route progress",
            unit="m",
            force_missing=unknown_fix,
        ),
        current_hazard=operation_signal(
            CompactDimension.CURRENT_HAZARD,
            risk_score,
            label="terrain candidate composite risk",
            ttl=_TERRAIN_TTL,
            confidence=0.86,
            risk_upper_bound=(
                min(risk_score + 0.08, 1.0) if risk_score is not None else None
            ),
        ),
        team_distance=operation_signal(
            CompactDimension.TEAM_DISTANCE,
            team_distance,
            label="synthetic team-spacing overlay",
            unit="m",
        ),
        remaining_daylight=operation_signal(
            CompactDimension.REMAINING_DAYLIGHT,
            remaining_daylight,
            label="synthetic daylight overlay",
            unit="min",
        ),
        shelter_reachability=operation_signal(
            CompactDimension.SHELTER_REACHABILITY,
            None,
            label="shelter reachability not supplied",
        ),
        water_margin=operation_signal(
            CompactDimension.WATER_MARGIN,
            None,
            label="water margin not supplied",
        ),
        camp_viability=operation_signal(
            CompactDimension.CAMP_VIABILITY,
            None,
            label="camp viability not supplied",
        ),
        mission_margin=operation_signal(
            CompactDimension.MISSION_MARGIN,
            mission_margin,
            label="synthetic mission schedule overlay",
        ),
        route_feasibility=operation_signal(
            CompactDimension.ROUTE_FEASIBILITY,
            route_feasibility,
            label="synthetic route-feasibility overlay",
            ttl=_ROUTE_TTL,
        ),
        wildlife_pressure=operation_signal(
            CompactDimension.WILDLIFE_PRESSURE,
            None,
            label="wildlife pressure not supplied",
        ),
        historical_context_relevance=operation_signal(
            CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            None,
            label="historical context not supplied",
        ),
    )


def _context_time(
    context: Mapping[str, Any],
    *children: Mapping[str, Any],
) -> datetime | None:
    candidates: list[object] = [
        context.get("observed_at"),
        context.get("generated_at"),
        context.get("fetched_at"),
        context.get("updated_at"),
    ]
    for child in children:
        candidates.extend(
            (
                child.get("observed_at"),
                child.get("generated_at"),
                child.get("fetched_at"),
                child.get("updated_at"),
            )
        )
    parsed = [item for item in (_parse_datetime(value) for value in candidates) if item]
    return max(parsed) if parsed else None


def _total_info_terrain(
    total_info: Mapping[str, Any],
    *,
    now: datetime,
) -> TerrainLatentState:
    context = _payload(total_info.get("terrain_risk_context") or {})
    profile = _payload(context.get("risk_route_profile") or {})
    refs = _context_refs(
        context,
        fallback="workspace://total-info/terrain_risk_context",
        children=(profile,),
    )
    observed_at = _context_time(context, profile)
    status_available = str(context.get("status") or "").startswith("available")
    mean_score = _score(
        _first(
            profile,
            ("score_summary", "mean_score"),
            ("score_summary", "mean"),
        )
    )
    explicit = {
        "exposure": _score(
            _first(context, ("exposure_risk",), ("compact_state", "exposure_risk"))
        ),
        "slip": _score(_first(context, ("slip_risk",), ("compact_state", "slip_risk"))),
        "rockfall": _score(
            _first(context, ("rockfall_risk",), ("compact_state", "rockfall_risk"))
        ),
        "escape": _score(
            _first(context, ("escape_cost",), ("compact_state", "escape_cost"))
        ),
        "visibility": _score(
            _first(context, ("visibility",), ("compact_state", "visibility"))
        ),
    }

    def terrain_signal(
        dimension: CompactDimension,
        value: float | None,
        label: str,
        *,
        confidence: float = 0.72,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="total_info",
            refs=refs,
            confidence=confidence,
            observed_at=observed_at,
            now=now,
            ttl=_TERRAIN_TTL,
            derivation=f"total-info terrain {label}",
            force_missing=not status_available,
        )

    return TerrainLatentState(
        exposure_risk=terrain_signal(
            CompactDimension.EXPOSURE_RISK,
            explicit["exposure"],
            "explicit exposure risk",
        ),
        slip_risk=terrain_signal(
            CompactDimension.SLIP_RISK,
            explicit["slip"],
            "explicit slip risk",
        ),
        rockfall_risk=terrain_signal(
            CompactDimension.ROCKFALL_RISK,
            explicit["rockfall"],
            "explicit rockfall risk",
        ),
        escape_cost=terrain_signal(
            CompactDimension.ESCAPE_COST,
            explicit["escape"],
            "explicit escape cost",
        ),
        visibility=terrain_signal(
            CompactDimension.VISIBILITY,
            explicit["visibility"],
            "explicit visibility",
        ),
        terrain_complexity=terrain_signal(
            CompactDimension.TERRAIN_COMPLEXITY,
            mean_score,
            "route-profile mean score proxy",
            confidence=0.64,
        ),
        terrain_confidence=terrain_signal(
            CompactDimension.TERRAIN_CONFIDENCE,
            0.72 if status_available else None,
            "artifact coverage confidence",
        ),
    )


def _total_info_weather(
    total_info: Mapping[str, Any],
    *,
    now: datetime,
) -> WeatherLatentState:
    context = _payload(total_info.get("weather_environment_context") or {})
    qpf = _payload(context.get("cwa_qpf") or {})
    gpm = _payload(context.get("gee_gpm") or {})
    cwa = _payload(context.get("cwa_weather") or {})
    refs = _context_refs(
        context,
        fallback="workspace://total-info/weather_environment_context",
        children=(qpf, gpm, cwa),
    )
    observed_at = _context_time(context, qpf, gpm, cwa)
    valid_until = _parse_datetime(
        _first(
            qpf,
            ("forecast_valid_until",),
            ("valid_until",),
            ("valid_to",),
        )
    )
    fresh_values = context.get("freshness")
    freshness = (
        tuple(str(item).lower() for item in fresh_values.values())
        if isinstance(fresh_values, Mapping)
        else ()
    )
    status_available = "available" in str(context.get("status") or "")
    rain_probability = _score(
        _first(qpf, ("max_rain_probability",), ("values", "max_rain_probability"))
    )
    rain_mm = _first_number(
        qpf,
        ("max_observed_24h_mm",),
        ("max_accumulation_mm",),
        ("values", "max"),
    )
    explicit_stability = _score(context.get("weather_stability"))
    rain_pressure = max(
        rain_probability or 0.0,
        min((rain_mm or 0.0) / 100.0, 1.0),
    )
    stability = (
        explicit_stability
        if explicit_stability is not None
        else 1.0 - rain_pressure
        if rain_probability is not None or rain_mm is not None
        else None
    )
    trend = _first(
        context,
        ("weather_trend",),
        ("gee_gpm", "values", "trend"),
        ("cwa_qpf", "values", "trend"),
    )
    danger_window = context.get("danger_window")
    if danger_window is None and valid_until is not None and rain_pressure >= 0.6:
        danger_window = f"through_{valid_until.isoformat()}"
    forecast_confidence = _score(context.get("forecast_confidence"))
    if forecast_confidence is None and freshness:
        forecast_confidence = (
            0.8 if "fresh" in freshness else 0.25 if "stale" in freshness else 0.45
        )

    def weather_signal(
        dimension: CompactDimension,
        value: object,
        label: str,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="total_info",
            refs=refs,
            confidence=forecast_confidence or 0.0,
            observed_at=observed_at,
            valid_until=valid_until,
            now=now,
            ttl=_FORECAST_TTL,
            derivation=f"total-info weather {label}",
            force_missing=not status_available,
        )

    return WeatherLatentState(
        weather_stability=weather_signal(
            CompactDimension.WEATHER_STABILITY,
            stability,
            "rain-pressure stability reduction",
        ),
        weather_trend=weather_signal(
            CompactDimension.WEATHER_TREND,
            trend,
            "normalized precipitation trend",
        ),
        danger_window=weather_signal(
            CompactDimension.DANGER_WINDOW,
            danger_window,
            "forecast-valid danger window",
        ),
        forecast_confidence=weather_signal(
            CompactDimension.FORECAST_CONFIDENCE,
            forecast_confidence,
            "source freshness confidence",
        ),
    )


def _total_info_human(
    total_info: Mapping[str, Any],
    *,
    now: datetime,
) -> HumanLatentState:
    context = _payload(total_info.get("body_resource_context") or {})
    sensor = _payload(total_info.get("sensor_snapshot_context") or {})
    latest = _payload(sensor.get("latest_sensor_vitals_record") or {})
    refs = _context_refs(
        context,
        fallback="workspace://total-info/body_resource_context",
        children=(latest,),
    )
    observed_at = _context_time(context, latest)
    status_available = "available" in str(context.get("status") or "")
    band = str(context.get("energy_reserve_band") or "").lower()
    energy = _score(context.get("energy_reserve"))
    if energy is None:
        energy = _ENERGY_BANDS.get(band)
    values = {
        CompactDimension.FATIGUE_INDEX: _score(context.get("fatigue_index")),
        CompactDimension.ENERGY_RESERVE: energy,
        CompactDimension.COGNITIVE_CONFIDENCE: _score(
            context.get("cognitive_confidence")
        ),
        CompactDimension.SAFETY_MARGIN: _score(context.get("safety_margin")),
        CompactDimension.MEDICAL_URGENCY: _score(context.get("medical_urgency")),
    }

    def human_signal(dimension: CompactDimension, label: str) -> CompactSignal:
        return _signal(
            dimension,
            values[dimension],
            source_kind="total_info",
            refs=refs,
            confidence=0.68 if dimension == CompactDimension.ENERGY_RESERVE else 0.75,
            observed_at=observed_at,
            now=now,
            ttl=_NEAR_LIVE_TTL,
            derivation=f"total-info human {label}",
            force_missing=not status_available,
        )

    return HumanLatentState(
        fatigue_index=human_signal(
            CompactDimension.FATIGUE_INDEX,
            "fatigue index",
        ),
        energy_reserve=human_signal(
            CompactDimension.ENERGY_RESERVE,
            "energy reserve band",
        ),
        cognitive_confidence=human_signal(
            CompactDimension.COGNITIVE_CONFIDENCE,
            "cognitive confidence",
        ),
        safety_margin=human_signal(
            CompactDimension.SAFETY_MARGIN,
            "safety margin",
        ),
        medical_urgency=human_signal(
            CompactDimension.MEDICAL_URGENCY,
            "medical urgency",
        ),
    )


def _total_info_communication(
    total_info: Mapping[str, Any],
    *,
    now: datetime,
) -> CommunicationLatentState:
    context = _payload(total_info.get("communication_context") or {})
    refs = _context_refs(
        context,
        fallback="workspace://total-info/communication_context",
    )
    observed_at = _context_time(context)
    status_available = "available" in str(context.get("status") or "")

    def communication_signal(
        dimension: CompactDimension,
        key: str,
    ) -> CompactSignal:
        return _signal(
            dimension,
            _score(context.get(key)),
            source_kind="total_info",
            refs=refs,
            confidence=0.78,
            observed_at=observed_at,
            now=now,
            ttl=_LIVE_TTL,
            derivation=f"total-info communication {key}",
            force_missing=not status_available,
        )

    return CommunicationLatentState(
        communication_reliability=communication_signal(
            CompactDimension.COMMUNICATION_RELIABILITY,
            "communication_reliability",
        ),
        coverage_confidence=communication_signal(
            CompactDimension.COVERAGE_CONFIDENCE,
            "coverage_confidence",
        ),
        emergency_reachability=communication_signal(
            CompactDimension.EMERGENCY_REACHABILITY,
            "emergency_reachability",
        ),
    )


def _total_info_operation(
    total_info: Mapping[str, Any],
    *,
    now: datetime,
) -> OperationalLatentState:
    location_context = _payload(total_info.get("location_context") or {})
    snapshot = _payload(location_context.get("live_navigation_snapshot") or {})
    mission = _payload(total_info.get("mission_context") or {})
    route = _payload(total_info.get("route_context") or {})
    location_refs = _context_refs(
        location_context,
        fallback="workspace://total-info/location_context",
    )
    mission_refs = _context_refs(
        mission,
        fallback="workspace://total-info/mission_context",
    )
    route_refs = _context_refs(
        route,
        fallback="workspace://total-info/route_context",
    )
    location_time = _context_time(snapshot, location_context)
    mission_time = _context_time(mission)
    route_time = _context_time(route)
    fix_quality = str(snapshot.get("fix_quality") or "").lower()
    unknown_fix = any(marker in fix_quality for marker in _UNKNOWN_FIX_MARKERS)
    accuracy = _first_number(snapshot, ("horizontal_accuracy_m",))
    gps_confidence = _score(snapshot.get("confidence"))
    if gps_confidence is None and accuracy is not None:
        gps_confidence = min(max(1.0 - accuracy / 50.0, 0.0), 0.95)
    route_distance = _first_number(snapshot, ("nearest_route_distance_m",))
    route_alignment = (
        min(max(1.0 - route_distance / 100.0, 0.0), 1.0)
        if route_distance is not None
        else None
    )

    def location_signal(
        dimension: CompactDimension,
        value: object,
        label: str,
        *,
        unit: str | None = None,
    ) -> CompactSignal:
        return _signal(
            dimension,
            value,
            source_kind="total_info",
            refs=location_refs,
            confidence=0.9,
            observed_at=location_time,
            now=now,
            ttl=_LIVE_TTL,
            unit=unit,
            derivation=f"total-info navigation {label}",
            force_missing=unknown_fix
            or str(location_context.get("status") or "") != "available",
        )

    def mission_signal(
        dimension: CompactDimension,
        key: str,
        label: str,
        *,
        unit: str | None = None,
    ) -> CompactSignal:
        return _signal(
            dimension,
            _first(mission, (key,), ("compact_state", key)),
            source_kind="total_info",
            refs=mission_refs,
            confidence=0.78,
            observed_at=mission_time,
            now=now,
            ttl=_NEAR_LIVE_TTL,
            unit=unit,
            derivation=f"total-info mission {label}",
            force_missing="available" not in str(mission.get("status") or ""),
        )

    route_feasibility = _score(
        _first(mission, ("route_feasibility",), ("compact_state", "route_feasibility"))
    )
    if route_feasibility is None:
        route_feasibility_signal = _missing_signal(
            CompactDimension.ROUTE_FEASIBILITY,
            source_kind="total_info",
            reason="route summary alone is insufficient to infer route feasibility",
            refs=route_refs,
        )
    else:
        route_feasibility_signal = _signal(
            CompactDimension.ROUTE_FEASIBILITY,
            route_feasibility,
            source_kind="total_info",
            refs=tuple(dict.fromkeys((*mission_refs, *route_refs))),
            confidence=0.72,
            observed_at=mission_time or route_time,
            now=now,
            ttl=_ROUTE_TTL,
            derivation="explicit total-info route feasibility",
        )

    return OperationalLatentState(
        gps_confidence=location_signal(
            CompactDimension.GPS_CONFIDENCE,
            gps_confidence,
            "GNSS confidence",
        ),
        route_alignment=location_signal(
            CompactDimension.ROUTE_ALIGNMENT,
            route_alignment,
            "route alignment",
        ),
        route_progress=location_signal(
            CompactDimension.ROUTE_PROGRESS,
            _first_number(snapshot, ("route_progress_m",)),
            "route progress",
            unit="m",
        ),
        current_hazard=mission_signal(
            CompactDimension.CURRENT_HAZARD,
            "current_hazard",
            "current hazard",
        ),
        team_distance=mission_signal(
            CompactDimension.TEAM_DISTANCE,
            "team_distance_m",
            "team distance",
            unit="m",
        ),
        remaining_daylight=mission_signal(
            CompactDimension.REMAINING_DAYLIGHT,
            "remaining_daylight_minutes",
            "remaining daylight",
            unit="min",
        ),
        shelter_reachability=mission_signal(
            CompactDimension.SHELTER_REACHABILITY,
            "shelter_reachability",
            "shelter reachability",
        ),
        water_margin=mission_signal(
            CompactDimension.WATER_MARGIN,
            "water_margin",
            "water margin",
        ),
        camp_viability=mission_signal(
            CompactDimension.CAMP_VIABILITY,
            "camp_viability",
            "camp viability",
        ),
        mission_margin=mission_signal(
            CompactDimension.MISSION_MARGIN,
            "mission_margin",
            "mission margin",
        ),
        route_feasibility=route_feasibility_signal,
        wildlife_pressure=mission_signal(
            CompactDimension.WILDLIFE_PRESSURE,
            "wildlife_pressure",
            "wildlife pressure",
        ),
        historical_context_relevance=mission_signal(
            CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
            "historical_context_relevance",
            "historical context relevance",
        ),
    )


def _representation_id(
    source_kind: str,
    source_identity: str,
    states: tuple[object, ...],
) -> str:
    payload = [
        source_kind,
        source_identity,
        *[
            state.model_dump(mode="json", exclude_none=False)
            for state in states
            if hasattr(state, "model_dump")
        ],
    ]
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"mser.{source_kind}.{digest}"


def _representation_refs(states: tuple[object, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for state in states:
        signals = getattr(state, "signals", None)
        if not callable(signals):
            continue
        for signal in signals():
            refs.extend(signal.source_refs)
    return tuple(dict.fromkeys(refs))


def project_scenario_context(
    scenario: object,
    *,
    now: datetime | None = None,
) -> EnvironmentalRepresentation:
    """Project a six-forces ``ScenarioContext`` into a complete MSER envelope."""

    payload = _payload(scenario)
    projection_time = (now or datetime.now(UTC)).astimezone(UTC)
    states = (
        _scenario_terrain(payload, now=projection_time),
        _scenario_weather(payload, now=projection_time),
        _scenario_human(payload, now=projection_time),
        _scenario_communication(payload, now=projection_time),
        _scenario_operation(payload, now=projection_time),
    )
    return EnvironmentalRepresentation(
        representation_id=_representation_id(
            "scenario",
            str(payload.get("scenario_id") or "unknown"),
            states,
        ),
        generated_at=projection_time,
        terrain=states[0],
        weather=states[1],
        human=states[2],
        communication=states[3],
        operation=states[4],
        source_refs=_representation_refs(states),
    )


def project_total_info(
    total_info: object,
    *,
    now: datetime | None = None,
) -> EnvironmentalRepresentation:
    """Project an assistant total-info summary without reading raw artifacts."""

    payload = _unwrap_total_info(total_info)
    projection_time = (now or datetime.now(UTC)).astimezone(UTC)
    states = (
        _total_info_terrain(payload, now=projection_time),
        _total_info_weather(payload, now=projection_time),
        _total_info_human(payload, now=projection_time),
        _total_info_communication(payload, now=projection_time),
        _total_info_operation(payload, now=projection_time),
    )
    return EnvironmentalRepresentation(
        representation_id=_representation_id(
            "total_info",
            str(payload.get("project_id") or "unknown"),
            states,
        ),
        generated_at=projection_time,
        terrain=states[0],
        weather=states[1],
        human=states[2],
        communication=states[3],
        operation=states[4],
        source_refs=_representation_refs(states),
    )


class TerrainDomainProjector:
    """Explicit terrain projector surface for registry and dependency injection."""

    from_scenario = staticmethod(_scenario_terrain)
    from_total_info = staticmethod(_total_info_terrain)


class WeatherDomainProjector:
    from_scenario = staticmethod(_scenario_weather)
    from_total_info = staticmethod(_total_info_weather)


class HumanDomainProjector:
    from_scenario = staticmethod(_scenario_human)
    from_total_info = staticmethod(_total_info_human)


class CommunicationDomainProjector:
    from_scenario = staticmethod(_scenario_communication)
    from_total_info = staticmethod(_total_info_communication)


class NavigationMissionDomainProjector:
    from_scenario = staticmethod(_scenario_operation)
    from_total_info = staticmethod(_total_info_operation)


__all__ = [
    "CommunicationDomainProjector",
    "HumanDomainProjector",
    "NavigationMissionDomainProjector",
    "TerrainDomainProjector",
    "WeatherDomainProjector",
    "project_scenario_context",
    "project_total_info",
]
