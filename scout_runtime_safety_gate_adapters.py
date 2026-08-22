from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyGateRouteContext,
    build_runtime_safety_gate_event,
)


WeatherGateLevel = Literal["none", "watch", "advisory", "unsafe", "severe"]
EnvironmentThreatImmediacy = Literal["distant", "nearby", "immediate"]
EnvironmentThreatPassability = Literal["passable", "limited", "blocked", "unknown"]


class PaceGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:pace-gate-observation"
    event_id: str = "pace_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    observed_segment_minutes: float = Field(ge=0)
    reference_p75_segment_minutes: float = Field(gt=0)
    reference_max_segment_minutes: float | None = Field(default=None, gt=0)
    observed_pace_min_per_km: float | None = Field(default=None, gt=0)
    reference_p75_pace_min_per_km: float | None = Field(default=None, gt=0)
    low_movement_efficiency_ratio: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class DelayGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:delay-gate-observation"
    event_id: str = "delay_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    delay_minutes: float
    planned_buffer_minutes: float | None = None
    checkpoint_deadline_missed: bool = False
    camp_deadline_missed: bool = False
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class DarknessGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:darkness-gate-observation"
    event_id: str = "darkness_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    daylight_buffer_minutes: float
    minutes_to_next_safe_objective: float = Field(ge=0)
    emergency_bivy_candidate_distance_m: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = True
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class WeatherGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:weather-gate-observation"
    event_id: str = "weather_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    warning_level: WeatherGateLevel = "none"
    warning_type: str | None = None
    wind_risk: bool = False
    rain_risk: bool = False
    lightning_risk: bool = False
    source_age_minutes: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class EnvironmentThreatGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:environment-threat-gate-observation"
    event_id: str = "environment_threat_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    threat_type: str
    passability: EnvironmentThreatPassability = "unknown"
    immediacy: EnvironmentThreatImmediacy = "nearby"
    route_blocked: bool = False
    safe_bypass_known: bool = False
    route_pressure_review_required: bool = True
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"

    @model_validator(mode="after")
    def normalize_blocked_passability(self) -> "EnvironmentThreatGateObservation":
        if self.route_blocked and self.passability == "passable":
            raise ValueError("route_blocked cannot be passable")
        return self


def build_pace_gate_event(
    observation: PaceGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, PaceGateObservation)
        else PaceGateObservation.model_validate(observation)
    )
    ratio = item.observed_segment_minutes / item.reference_p75_segment_minutes
    eta_delay = max(0, round(item.observed_segment_minutes - item.reference_p75_segment_minutes))
    efficiency = item.low_movement_efficiency_ratio
    severity = "none"
    transition = "none"
    state = "on_pace"
    action = "continue_monitoring"
    reasons = [f"segment_time_ratio:{ratio:.2f}"]
    if efficiency is not None:
        reasons.append(f"movement_efficiency_ratio:{efficiency:.2f}")

    if ratio >= 1.65 or (ratio >= 1.45 and item.route_pressure_review_required):
        severity = "retreat_review" if item.route_pressure_review_required else "rest"
        transition = (
            "candidate_retreat"
            if severity == "retreat_review"
            else "candidate_rest"
        )
        state = "pace_collapse_review" if severity == "retreat_review" else "pace_rest_review"
        action = "review_retreat_or_extended_rest" if severity == "retreat_review" else "stop_and_rest"
        reasons.append("observed pace is far slower than reference p75")
    elif ratio >= 1.35 or (efficiency is not None and efficiency < 0.65):
        severity = "rest"
        transition = "candidate_rest"
        state = "pace_rest_review"
        action = "slow_down_or_rest"
        reasons.append("slow pace with movement-efficiency pressure")
    elif ratio >= 1.15:
        severity = "watch"
        transition = "candidate_watch"
        state = "pace_watch"
        action = "watch_pace_and_recheck"
        reasons.append("pace is slower than reference p75")

    return build_runtime_safety_gate_event(
        gate_id="pace_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=item.route_pressure_review_required,
        eta_delay_minutes=eta_delay,
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 3 if item.observed_pace_min_per_km else 2,
            "limitations": [
                "pace gate uses aggregate segment timing only",
                "not a direct cause-of-fatigue diagnosis",
            ],
        },
        gate_payload={
            "observed_segment_minutes": item.observed_segment_minutes,
            "reference_p75_segment_minutes": item.reference_p75_segment_minutes,
            "reference_max_segment_minutes": item.reference_max_segment_minutes,
            "segment_time_ratio": round(ratio, 4),
            "observed_pace_min_per_km": item.observed_pace_min_per_km,
            "reference_p75_pace_min_per_km": item.reference_p75_pace_min_per_km,
            "low_movement_efficiency_ratio": efficiency,
        },
    )


def build_delay_gate_event(
    observation: DelayGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, DelayGateObservation)
        else DelayGateObservation.model_validate(observation)
    )
    negative_buffer = (
        item.planned_buffer_minutes is not None and item.planned_buffer_minutes < 0
    )
    deadline_missed = item.checkpoint_deadline_missed or item.camp_deadline_missed
    delay = item.delay_minutes
    severity = "none"
    transition = "none"
    state = "on_schedule"
    action = "continue_monitoring"
    reasons = [f"delay_minutes:{delay:.1f}"]
    if item.planned_buffer_minutes is not None:
        reasons.append(f"planned_buffer_minutes:{item.planned_buffer_minutes:.1f}")

    if delay >= 60 or deadline_missed or negative_buffer:
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "timeline_retreat_review"
        action = "review_retreat_hold_or_bivy"
        reasons.append("timeline buffer is exhausted")
    elif delay >= 30:
        severity = "rest"
        transition = "candidate_rest"
        state = "timeline_rest_review"
        action = "pause_plan_and_recompute_eta"
        reasons.append("delay consumes meaningful route buffer")
    elif delay >= 10:
        severity = "watch"
        transition = "candidate_watch"
        state = "timeline_watch"
        action = "watch_delay_and_recheck"
        reasons.append("delay exceeds watch threshold")

    return build_runtime_safety_gate_event(
        gate_id="delay_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required or severity == "retreat_review"
        ),
        eta_delay_minutes=max(0, round(delay)),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2,
            "limitations": ["delay gate does not infer the reason for delay"],
        },
        gate_payload={
            "delay_minutes": delay,
            "planned_buffer_minutes": item.planned_buffer_minutes,
            "checkpoint_deadline_missed": item.checkpoint_deadline_missed,
            "camp_deadline_missed": item.camp_deadline_missed,
        },
    )


def build_darkness_gate_event(
    observation: DarknessGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, DarknessGateObservation)
        else DarknessGateObservation.model_validate(observation)
    )
    margin = item.daylight_buffer_minutes - item.minutes_to_next_safe_objective
    severity = "none"
    transition = "none"
    state = "daylight_buffer_ok"
    action = "continue_monitoring"
    reasons = [
        f"daylight_buffer_minutes:{item.daylight_buffer_minutes:.1f}",
        f"minutes_to_next_safe_objective:{item.minutes_to_next_safe_objective:.1f}",
        f"daylight_margin_minutes:{margin:.1f}",
    ]

    if margin < -30:
        severity = "alert_review"
        transition = "candidate_alert_review"
        state = "darkness_alert_review"
        action = "review_hold_bivy_or_alert"
        reasons.append("next safe objective is beyond daylight buffer")
    elif margin < 0:
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "darkness_retreat_review"
        action = "review_retreat_or_emergency_bivy"
        reasons.append("daylight buffer is negative")
    elif margin < 30:
        severity = "rest"
        transition = "candidate_rest"
        state = "darkness_rest_review"
        action = "recompute_eta_before_continuing"
        reasons.append("daylight margin is narrow")
    elif margin < 60:
        severity = "watch"
        transition = "candidate_watch"
        state = "darkness_watch"
        action = "watch_daylight_buffer"
        reasons.append("daylight margin is below conservative buffer")

    route_context = item.route_context.model_copy(
        update={"daylight_buffer_minutes": item.daylight_buffer_minutes}
    )
    return build_runtime_safety_gate_event(
        gate_id="darkness_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=item.route_pressure_review_required,
        eta_delay_minutes=max(0, round(-margin)),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2,
            "limitations": ["darkness gate uses route-relative daylight margin"],
        },
        gate_payload={
            "daylight_buffer_minutes": item.daylight_buffer_minutes,
            "minutes_to_next_safe_objective": item.minutes_to_next_safe_objective,
            "daylight_margin_minutes": margin,
            "emergency_bivy_candidate_distance_m": (
                item.emergency_bivy_candidate_distance_m
            ),
        },
    )


def build_weather_gate_event(
    observation: WeatherGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, WeatherGateObservation)
        else WeatherGateObservation.model_validate(observation)
    )
    severity_by_level = {
        "none": ("none", "none", "weather_ok", "continue_monitoring"),
        "watch": ("watch", "candidate_watch", "weather_watch", "watch_weather"),
        "advisory": (
            "rest",
            "candidate_rest",
            "weather_rest_review",
            "pause_plan_and_recheck_weather",
        ),
        "unsafe": (
            "retreat_review",
            "candidate_retreat",
            "weather_retreat_review",
            "review_retreat_or_hold",
        ),
        "severe": (
            "alert_review",
            "candidate_alert_review",
            "weather_alert_review",
            "review_alert_hold_or_retreat",
        ),
    }
    severity, transition, state, action = severity_by_level[item.warning_level]
    reasons = [f"warning_level:{item.warning_level}"]
    if item.warning_type:
        reasons.append(f"warning_type:{item.warning_type}")
    for key, enabled in (
        ("wind_risk", item.wind_risk),
        ("rain_risk", item.rain_risk),
        ("lightning_risk", item.lightning_risk),
    ):
        if enabled:
            reasons.append(key)

    missing = []
    stale = []
    if item.source_age_minutes is None:
        missing.append("source_age_minutes")
    elif item.source_age_minutes > 180:
        stale.append("weather_source")

    return build_runtime_safety_gate_event(
        gate_id="weather_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required
            or severity in {"retreat_review", "alert_review"}
        ),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2 + int(item.wind_risk) + int(item.rain_risk),
            "missing_signal_names": missing,
            "stale_signal_names": stale,
            "live_network_calls_made": False,
            "limitations": ["weather gate tests use structured fixture evidence"],
        },
        gate_payload={
            "warning_level": item.warning_level,
            "warning_type": item.warning_type,
            "wind_risk": item.wind_risk,
            "rain_risk": item.rain_risk,
            "lightning_risk": item.lightning_risk,
            "source_age_minutes": item.source_age_minutes,
        },
    )


def build_environment_threat_gate_event(
    observation: EnvironmentThreatGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, EnvironmentThreatGateObservation)
        else EnvironmentThreatGateObservation.model_validate(observation)
    )
    severity = "watch"
    transition = "candidate_watch"
    state = "environment_threat_watch"
    action = "watch_environment_threat"
    reasons = [
        f"threat_type:{item.threat_type}",
        f"passability:{item.passability}",
        f"immediacy:{item.immediacy}",
    ]

    if item.route_blocked or item.passability == "blocked":
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "environment_route_blocked_review"
        action = "review_retreat_or_safe_bypass"
        reasons.append("route is blocked or no longer passable")
    elif item.immediacy == "immediate" and not item.safe_bypass_known:
        severity = "alert_review"
        transition = "candidate_alert_review"
        state = "environment_immediate_threat_review"
        action = "review_hold_retreat_or_alert"
        reasons.append("immediate threat without known safe bypass")
    elif item.passability == "limited" or item.immediacy == "nearby":
        severity = "rest"
        transition = "candidate_rest"
        state = "environment_rest_review"
        action = "stop_and_review_route"
        reasons.append("field hazard limits route confidence")

    return build_runtime_safety_gate_event(
        gate_id="environment_threat_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required
            or severity in {"retreat_review", "alert_review"}
        ),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2,
            "limitations": [
                "environment threat gate uses structured field report evidence",
            ],
        },
        gate_payload={
            "threat_type": item.threat_type,
            "passability": item.passability,
            "immediacy": item.immediacy,
            "route_blocked": item.route_blocked,
            "safe_bypass_known": item.safe_bypass_known,
        },
    )


def build_runtime_safety_gate_events_from_fixture(
    payload: dict[str, Any],
):
    events = []
    if "pace" in payload:
        events.append(build_pace_gate_event(payload["pace"]))
    if "delay" in payload:
        events.append(build_delay_gate_event(payload["delay"]))
    if "darkness" in payload:
        events.append(build_darkness_gate_event(payload["darkness"]))
    if "weather" in payload:
        events.append(build_weather_gate_event(payload["weather"]))
    if "environment_threat" in payload:
        events.append(build_environment_threat_gate_event(payload["environment_threat"]))
    return events
