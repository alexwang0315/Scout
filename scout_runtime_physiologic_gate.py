from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import (
    Confidence,
    ReserveBand,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    ScoutEnergyReserveBaseline,
    aggregate_sha256,
    sha256_file,
)
from scout_energy_field_cue import WearableFieldObservation
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


HeartRateZone = Literal["z1", "z2", "z3", "z4", "z5"]
TrainingLoadClassification = Literal["well_below", "below", "steady", "above", "well_above"]
PostureOrGaitQuality = Literal["stable", "watch", "poor", "unstable", "unknown"]
BreathingRecoveryQuality = Literal["settled", "watch", "not_settled", "unknown"]
UserReportedDiscomfort = Literal["none", "mild", "stop_requested", "cannot_continue", "manual_help_request"]
ExternalPressureFlag = Literal[
    "pace_gate_failed",
    "delay_gate_failed",
    "darkness_pressure",
    "lost_or_routefinding_pressure",
    "weather_deteriorating",
    "seeking_shelter",
    "environment_threat",
    "companion_pace_pressure",
]
PhysiologicGateState = Literal[
    "warmup",
    "normal",
    "watch",
    "stop_and_rest",
    "retreat_suggested",
    "alert_candidate",
]
PhysiologicRequiredAction = Literal["none", "slow_down", "rest_now", "retreat_review", "alert_review"]


class PhysiologicGateThresholdPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = "workspace_fixture_thresholds.v0"
    source_basis: list[str] = Field(
        default_factory=lambda: [
            "tests/fixtures/wearables/*.json activity summaries",
            "tests/fixtures/wearables/field_observations/high_hr_drift.json",
            "tests/fixtures/wearables/field_observations/apple_effort_difficult_runtime_frame.json",
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/energy_vitals_snapshot.reviewed.json",
        ]
    )
    heart_rate_watch_drift_ratio: float = 0.08
    heart_rate_high_drift_ratio: float = 0.14
    heart_rate_extreme_drift_ratio: float = 0.22
    oxygen_uptake_watch_ratio: float = 0.90
    oxygen_uptake_stop_ratio: float = 0.85
    oxygen_uptake_retreat_ratio: float = 0.78
    altitude_oxygen_pressure_ratio: float = 0.82
    fast_recovery_ratio_to_personal_baseline: float = 1.10
    slow_recovery_ratio_to_personal_baseline: float = 0.80
    work_output_pre_reset_ratio: float = 0.95
    work_output_reset_ratio: float = 1.00
    work_output_overdraft_ratio: float = 1.20
    movement_efficiency_watch_ratio: float = 0.70
    movement_efficiency_stop_ratio: float = 0.50
    default_work_output_reset_ratio_hint: float = 1.25
    darkness_pressure_buffer_minutes: int = 30
    observation_window_minutes: int = 15
    minimum_external_pressure_for_danger: bool = True
    heart_rate_only_max_state: Literal["watch"] = "watch"
    advisory_only: bool = True
    medical_diagnosis: bool = False
    phase1_runtime_safety_truth: bool = False


WORKSPACE_THRESHOLD_POLICY = PhysiologicGateThresholdPolicy()


class PhysiologicStateSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantics_id: str = "physiologic_state_semantics.v0"
    high_heart_rate_alone_max_state: Literal["watch"] = "watch"
    vo2max_is_live_oxygen_uptake: bool = False
    oxygen_saturation_compared_to_vo2max: bool = False
    provider_values_are_scout_truth: bool = False
    stop_and_rest_requires_corroboration: bool = True
    retreat_suggested_requires_route_pressure_or_performance_collapse: bool = True
    alert_candidate_requires_explicit_help_request: bool = True
    stop_and_rest_basis: list[str] = Field(
        default_factory=lambda: [
            "heart-rate pressure plus oxygen-uptake ratio at or below stop threshold",
            "heart-rate pressure plus slow heart-rate recovery or unsettled breathing",
            "heart-rate pressure plus sustained low movement efficiency in a complete observation window",
            "work-output reset cue plus recovery, oxygen, performance, or subjective corroboration",
            "strong provider effort or training-load source value plus personal reserve pressure",
        ]
    )
    retreat_suggested_basis: list[str] = Field(
        default_factory=lambda: [
            "oxygen-uptake ratio at or below retreat threshold plus performance degradation",
            "overdraft-level work output plus external route pressure",
            "tight daylight or route pressure plus physiologic corroboration",
        ]
    )
    excluded_inferences: list[str] = Field(
        default_factory=lambda: [
            "no medical diagnosis",
            "no disease, dehydration, arrhythmia, overtraining, heat illness, or altitude illness inference",
            "no direct comparison between SpO2 percent and VO2max ml/kg/min",
            "no Phase 1 runtime safety truth mutation",
            "no safety API call or outbound alert",
        ]
    )

    @model_validator(mode="after")
    def enforce_semantics_boundary(self) -> "PhysiologicStateSemantics":
        if self.high_heart_rate_alone_max_state != "watch":
            raise ValueError("high heart rate alone must stay capped at watch")
        if self.vo2max_is_live_oxygen_uptake:
            raise ValueError("VO2max cannot be treated as live oxygen uptake")
        if self.oxygen_saturation_compared_to_vo2max:
            raise ValueError("oxygen saturation must not be compared to VO2max values")
        if self.provider_values_are_scout_truth:
            raise ValueError("provider values must not be treated as Scout truth")
        if not self.stop_and_rest_requires_corroboration:
            raise ValueError("stop_and_rest requires corroboration beyond heart rate alone")
        if not self.retreat_suggested_requires_route_pressure_or_performance_collapse:
            raise ValueError("retreat_suggested requires route pressure or performance collapse")
        if not self.alert_candidate_requires_explicit_help_request:
            raise ValueError("alert_candidate requires explicit help request in this slice")
        return self


STATE_SEMANTICS = PhysiologicStateSemantics()


PHYSIOLOGIC_SIGNAL_NAMES = [
    "heart_rate_bpm",
    "heart_rate_zone",
    "workout_effort_score",
    "training_load_classification",
    "vo2max_estimate_ml_kg_min",
    "estimated_oxygen_uptake_ml_kg_min",
    "oxygen_uptake_ratio_to_personal_baseline",
    "oxygen_saturation_pct",
    "heart_rate_recovery_bpm_1min",
    "heart_rate_recovery_bpm_2min",
    "heart_rate_recovery_ratio_to_personal_baseline",
    "active_recovery_observed",
    "breathing_recovery_quality",
    "cumulative_work_output_kj",
    "work_output_ratio_to_reset_budget",
    "pace_mps",
    "movement_efficiency_ratio_to_personal_baseline",
    "vertical_speed_m_per_hour",
    "power_watts",
    "cadence_spm",
    "posture_or_gait_quality",
    "rest_ratio_recent_window",
    "user_reported_discomfort",
]


class PhysiologicGateBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisory_only: bool = True
    candidate_only: bool = True
    medical_diagnosis: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_safety_state_mutation_allowed: bool = False
    safety_api_called: bool = False
    safety_api_calls_allowed: bool = False
    outbound_alert_sent: bool = False
    outbound_alert_allowed: bool = False
    provider_values_are_scout_truth: bool = False

    @model_validator(mode="after")
    def enforce_boundary(self) -> "PhysiologicGateBoundary":
        if not self.advisory_only:
            raise ValueError("physiologic gate must remain advisory only")
        if not self.candidate_only:
            raise ValueError("physiologic gate must emit candidates only")
        if self.medical_diagnosis:
            raise ValueError("physiologic gate cannot be medical diagnosis")
        if self.phase1_runtime_safety_truth:
            raise ValueError("physiologic gate cannot be Phase 1 runtime safety truth")
        if self.phase1_runtime_mutation_allowed or self.phase1_safety_state_mutation_allowed:
            raise ValueError("physiologic gate cannot mutate Phase 1 runtime safety state")
        if self.safety_api_called or self.safety_api_calls_allowed:
            raise ValueError("physiologic gate cannot call or allow safety APIs")
        if self.outbound_alert_sent or self.outbound_alert_allowed:
            raise ValueError("physiologic gate cannot send outbound alerts in this slice")
        if self.provider_values_are_scout_truth:
            raise ValueError("provider values must not be treated as Scout truth")
        return self


class PhysiologicRouteContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    segment_id: str
    distance_to_next_checkpoint_m: float = Field(ge=0)
    estimated_minutes_to_next_checkpoint: int = Field(ge=0)
    estimated_minutes_to_planned_camp: int = Field(ge=0)
    daylight_buffer_minutes: int
    altitude_m: float | None = Field(default=None, ge=-500)
    altitude_oxygen_availability_ratio: float | None = Field(default=None, gt=0, le=1.1)
    external_pressure_flags: list[ExternalPressureFlag] = Field(default_factory=list)


class PhysiologicGateSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heart_rate_bpm: int | None = Field(default=None, ge=1)
    heart_rate_zone: HeartRateZone | None = None
    workout_effort_score: float | None = Field(default=None, ge=1, le=10)
    workout_effort_score_source: str | None = None
    workout_effort_score_provider_value: bool = True
    training_load_classification: TrainingLoadClassification | None = None
    vo2max_estimate_ml_kg_min: float | None = Field(default=None, ge=0)
    estimated_oxygen_uptake_ml_kg_min: float | None = Field(default=None, ge=0)
    oxygen_uptake_ratio_to_personal_baseline: float | None = Field(default=None, ge=0)
    oxygen_saturation_pct: float | None = Field(default=None, ge=0, le=100)
    oxygen_saturation_source: str | None = None
    oxygen_saturation_provider_value: bool = True
    heart_rate_recovery_bpm_1min: float | None = Field(default=None, ge=0)
    heart_rate_recovery_bpm_2min: float | None = Field(default=None, ge=0)
    heart_rate_recovery_ratio_to_personal_baseline: float | None = Field(default=None, ge=0)
    active_recovery_observed: bool | None = None
    breathing_recovery_quality: BreathingRecoveryQuality | None = None
    cumulative_work_output_kj: float | None = Field(default=None, ge=0)
    recent_high_output_work_kj: float | None = Field(default=None, ge=0)
    work_output_source: str | None = None
    work_output_provider_value: bool = True
    work_output_ratio_to_reset_budget: float | None = Field(default=None, ge=0)
    pace_mps: float | None = Field(default=None, ge=0)
    movement_efficiency_ratio_to_personal_baseline: float | None = Field(default=None, ge=0)
    vertical_speed_m_per_hour: float | None = None
    power_watts: float | None = Field(default=None, ge=0)
    cadence_spm: float | None = Field(default=None, ge=0)
    posture_or_gait_quality: PostureOrGaitQuality | None = None
    rest_ratio_recent_window: float | None = Field(default=None, ge=0, le=1)
    user_reported_discomfort: UserReportedDiscomfort | None = None

    @model_validator(mode="after")
    def enforce_provider_value_boundary(self) -> "PhysiologicGateSignals":
        if self.workout_effort_score is not None and not self.workout_effort_score_provider_value:
            raise ValueError("provider workout effort score must remain marked as provider value")
        if self.oxygen_saturation_pct is not None and not self.oxygen_saturation_provider_value:
            raise ValueError("provider oxygen saturation must remain marked as provider value")
        if self.cumulative_work_output_kj is not None and not self.work_output_provider_value:
            raise ValueError("work output must remain marked as source value")
        return self


class PhysiologicBaselineContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acute_window_days: int = Field(default=7, ge=1)
    recent_window_days: int = Field(default=28, ge=1)
    stable_window_days: int = Field(default=90, ge=1)
    personal_envelope_available: bool = False
    reserve_band: ReserveBand | None = None
    reserve_score: int | None = Field(default=None, ge=0, le=100)
    expected_heart_rate_bpm: int | None = Field(default=None, ge=1)
    expected_oxygen_uptake_ml_kg_min: float | None = Field(default=None, ge=0)
    expected_pace_mps: float | None = Field(default=None, ge=0)
    expected_cadence_spm: float | None = Field(default=None, ge=0)
    typical_completed_work_output_kj: float | None = Field(default=None, ge=0)
    reset_cue_work_output_kj: float | None = Field(default=None, ge=0)
    work_output_reset_ratio_hint: float = Field(
        default=WORKSPACE_THRESHOLD_POLICY.default_work_output_reset_ratio_hint,
        ge=1.0,
        le=2.0,
    )
    stable_baseline_activity_count: int = Field(default=0, ge=0)


class PhysiologicGateDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_count: int = Field(ge=0)
    missing_signal_names: list[str] = Field(default_factory=list)
    baseline_available: bool
    live_network_calls_made: bool = False
    heart_rate_confidence: Confidence = "low"
    gps_confidence: Confidence = "low"
    provider_value_confidence: Confidence = "low"
    limitations: list[str] = Field(default_factory=list)


class RestDirective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended: bool
    minimum_minutes: int = Field(ge=0)
    recheck_after_minutes: int = Field(ge=0)


class PhysiologicObservationWindowContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_minutes: int = Field(default=WORKSPACE_THRESHOLD_POLICY.observation_window_minutes, ge=1, le=60)
    elapsed_minutes: int | None = Field(default=None, ge=0)
    require_complete_window_for_stop_or_retreat: bool = True
    allow_user_request_bypass: bool = True
    allow_route_pressure_bypass: bool = True


class PhysiologicObservationWindowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_minutes: int = Field(ge=1, le=60)
    elapsed_minutes: int = Field(ge=0)
    complete: bool
    noise_reduction_applied: bool
    state_before_window_gate: PhysiologicGateState
    state_after_window_gate: PhysiologicGateState
    bypass_reason: str | None = None
    rationale: str


class RoutePressureEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_checkpoint_eta_revised_minutes: int = Field(ge=0)
    planned_camp_eta_revised_minutes: int = Field(ge=0)
    daylight_buffer_after_delay_minutes: int
    route_pressure_review_required: bool


class ExertionOverdraftStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["none", "reset_cue", "overdraft_candidate", "danger_overdraft_candidate"]
    danger_flag: bool
    involuntary_forward_pressure: bool
    external_pressure_flags: list[ExternalPressureFlag] = Field(default_factory=list)
    work_output_ratio_to_reset_budget: float | None = None
    advisory_only: bool = True
    phase1_runtime_safety_truth: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    handoff_gates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "ExertionOverdraftStatus":
        if not self.advisory_only:
            raise ValueError("exertion overdraft status must remain advisory only")
        if self.phase1_runtime_safety_truth:
            raise ValueError("exertion overdraft status cannot be Phase 1 runtime safety truth")
        if self.safety_api_called:
            raise ValueError("exertion overdraft status cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("exertion overdraft status cannot send outbound alerts")
        return self


class PhysiologicGateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_physiologic_gate_input"
    schema_version: str = "scout_runtime_physiologic_gate_input.v0"
    source_provider: str
    source_path: str
    sha256: str
    observed_at_offset_s: int = Field(ge=0)
    route_context: PhysiologicRouteContext
    signals: PhysiologicGateSignals = Field(default_factory=PhysiologicGateSignals)
    baseline: PhysiologicBaselineContext = Field(default_factory=PhysiologicBaselineContext)
    observation_window: PhysiologicObservationWindowContext = Field(
        default_factory=PhysiologicObservationWindowContext
    )
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: PhysiologicGateBoundary = Field(default_factory=PhysiologicGateBoundary)

    @model_validator(mode="after")
    def enforce_input_boundary(self) -> "PhysiologicGateInput":
        _enforce_privacy(self.privacy)
        return self


@dataclass(frozen=True)
class PhysiologicEvidence:
    severity_score: float
    reasons: list[str]
    explicit_alert_request: bool
    heart_rate_pressure: bool
    recovery_state: Literal["fast", "expected", "slow"] | None
    corroborating_dimensions: frozenset[str]


class PhysiologicGateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_physiologic_gate"
    schema_version: str = "scout_runtime_physiologic_gate.v0"
    gate_id: str = "physiologic_gate"
    state: PhysiologicGateState
    confidence: Confidence
    dominant_reasons: list[str]
    required_action: PhysiologicRequiredAction
    rest_directive: RestDirective
    observation_window: PhysiologicObservationWindowResult
    eta_delay_minutes: int = Field(ge=0)
    route_pressure_effect: RoutePressureEffect
    exertion_overdraft: ExertionOverdraftStatus
    threshold_policy: PhysiologicGateThresholdPolicy = Field(default_factory=PhysiologicGateThresholdPolicy)
    state_semantics: PhysiologicStateSemantics = Field(default_factory=PhysiologicStateSemantics)
    source_provider: str
    source_path: str
    sha256: str
    data_quality: PhysiologicGateDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: PhysiologicGateBoundary = Field(default_factory=PhysiologicGateBoundary)

    @model_validator(mode="after")
    def enforce_output_boundary(self) -> "PhysiologicGateOutput":
        _enforce_privacy(self.privacy)
        return self


def load_runtime_physiologic_gate_input(
    path: Path,
    *,
    root: Path | None = None,
) -> PhysiologicGateInput:
    payload = json.loads(path.read_text(encoding="utf-8"))
    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        raise ValueError(f"forbidden raw physiologic gate fields present: {', '.join(forbidden_paths)}")
    payload["source_path"] = _relpath(path, root or Path.cwd())
    payload["sha256"] = sha256_file(path)
    return PhysiologicGateInput.model_validate(payload)


def build_runtime_physiologic_gate(gate_input: PhysiologicGateInput) -> PhysiologicGateOutput:
    signal_count, missing_signal_names = _signal_inventory(gate_input.signals)
    drift_ratio = _heart_rate_drift_ratio(gate_input.signals, gate_input.baseline)
    evidence = _physiologic_evidence(gate_input, drift_ratio)
    raw_state = _gate_state(gate_input, evidence)
    observation_window = _observation_window_result(gate_input, evidence, raw_state)
    state = observation_window.state_after_window_gate
    eta_delay_minutes = _eta_delay_minutes(state)
    reasons = list(evidence.reasons)
    if observation_window.noise_reduction_applied:
        reasons.append(observation_window.rationale)
    elif observation_window.bypass_reason:
        reasons.append(observation_window.bypass_reason)
    daylight_buffer_after_delay = gate_input.route_context.daylight_buffer_minutes - eta_delay_minutes
    external_pressure_flags = _external_pressure_flags(gate_input.route_context, daylight_buffer_after_delay)
    exertion_overdraft = _exertion_overdraft_status(
        gate_input=gate_input,
        evidence=evidence,
        state=state,
        external_pressure_flags=external_pressure_flags,
    )
    route_pressure_review_required = state in {"retreat_suggested", "alert_candidate"} or (
        state == "stop_and_rest"
        and daylight_buffer_after_delay < WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
    ) or exertion_overdraft.danger_flag
    route_pressure_effect = RoutePressureEffect(
        next_checkpoint_eta_revised_minutes=(
            gate_input.route_context.estimated_minutes_to_next_checkpoint + eta_delay_minutes
        ),
        planned_camp_eta_revised_minutes=(
            gate_input.route_context.estimated_minutes_to_planned_camp + eta_delay_minutes
        ),
        daylight_buffer_after_delay_minutes=daylight_buffer_after_delay,
        route_pressure_review_required=route_pressure_review_required,
    )
    if (
        route_pressure_effect.daylight_buffer_after_delay_minutes
        < WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
        and state in {
            "stop_and_rest",
            "retreat_suggested",
            "alert_candidate",
        }
    ):
        reasons.append("rest delay leaves a tight daylight buffer for the route-pressure gates")
    if exertion_overdraft.danger_flag:
        reasons.append("exertion overdraft danger flag indicates likely involuntary forward progress")
    if missing_signal_names:
        reasons.append("missing signals lower confidence and are not interpreted as safe")

    data_quality = PhysiologicGateDataQuality(
        signal_count=signal_count,
        missing_signal_names=missing_signal_names,
        baseline_available=gate_input.baseline.personal_envelope_available,
        live_network_calls_made=False,
        heart_rate_confidence=gate_input.data_quality.heart_rate_confidence,
        gps_confidence=gate_input.data_quality.gps_confidence,
        provider_value_confidence=gate_input.data_quality.provider_value_confidence,
        limitations=_quality_limitations(gate_input, missing_signal_names),
    )
    output_sha = aggregate_sha256(
        [
            gate_input.sha256,
            {
                "state": state,
                "raw_state": raw_state,
                "threshold_policy": WORKSPACE_THRESHOLD_POLICY.policy_id,
                "state_semantics": STATE_SEMANTICS.semantics_id,
                "observation_window": observation_window.model_dump(mode="json"),
                "severity_score": round(evidence.severity_score, 3),
                "corroborating_dimensions": sorted(evidence.corroborating_dimensions),
                "exertion_overdraft_stage": exertion_overdraft.stage,
                "exertion_overdraft_danger_flag": exertion_overdraft.danger_flag,
                "eta_delay_minutes": eta_delay_minutes,
                "signal_count": signal_count,
            },
        ]
    )
    return PhysiologicGateOutput(
        state=state,
        confidence=_confidence(gate_input, signal_count),
        dominant_reasons=_dedupe_reasons(reasons),
        required_action=_required_action(state),
        rest_directive=_rest_directive(state),
        observation_window=observation_window,
        eta_delay_minutes=eta_delay_minutes,
        route_pressure_effect=route_pressure_effect,
        exertion_overdraft=exertion_overdraft,
        source_provider=gate_input.source_provider,
        source_path=gate_input.source_path,
        sha256=output_sha,
        data_quality=data_quality,
        privacy=gate_input.privacy,
        boundary=gate_input.boundary,
    )


def build_runtime_physiologic_gate_from_observation(
    observation: WearableFieldObservation,
    baseline: ScoutEnergyReserveBaseline | dict[str, Any],
    *,
    route_context: PhysiologicRouteContext | dict[str, Any],
    signal_overrides: dict[str, Any] | None = None,
) -> PhysiologicGateOutput:
    baseline_payload = baseline.model_dump(mode="json") if isinstance(baseline, ScoutEnergyReserveBaseline) else baseline
    route = (
        route_context
        if isinstance(route_context, PhysiologicRouteContext)
        else PhysiologicRouteContext.model_validate(route_context)
    )
    signal_payload = {
        "heart_rate_bpm": observation.heart_rate_bpm,
    }
    if signal_overrides:
        signal_payload.update(signal_overrides)
    gate_input = PhysiologicGateInput(
        source_provider=observation.source_provider,
        source_path=f"{observation.source_path}+{baseline_payload['source_path']}",
        sha256=aggregate_sha256([observation.sha256, baseline_payload["sha256"]]),
        observed_at_offset_s=observation.offset_s,
        route_context=route,
        signals=PhysiologicGateSignals.model_validate(signal_payload),
        baseline=PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band=observation.reserve_band_hint or baseline_payload["reserve_trend"]["current_band"],
            reserve_score=baseline_payload["reserve_trend"]["reserve_score"],
            expected_heart_rate_bpm=observation.expected_baseline_bpm,
            stable_baseline_activity_count=baseline_payload["stable_90_day_baseline"]["activity_count"],
        ),
        data_quality=_combine_energy_data_quality(observation.data_quality, baseline_payload["data_quality"]),
        privacy=observation.privacy,
    )
    return build_runtime_physiologic_gate(gate_input)


def _physiologic_evidence(
    gate_input: PhysiologicGateInput,
    drift_ratio: float | None,
) -> PhysiologicEvidence:
    severity = 0.0
    reasons = ["baseline-relative physiologic advisory only"]
    explicit_alert_request = False
    heart_rate_pressure = False
    corroborating_dimensions: set[str] = set()
    recovery_state = _heart_rate_recovery_state(gate_input.signals)
    reserve_band = gate_input.baseline.reserve_band
    if not gate_input.baseline.personal_envelope_available:
        severity += 1.0
        reasons.append("personal baseline envelope is unavailable")
    elif reserve_band:
        reserve_weight = {
            "normal": 0.0,
            "watch": 0.5,
            "rest_suggested": 1.0,
            "stop_and_check": 3.0,
        }[reserve_band]
        severity += reserve_weight
        if reserve_weight:
            reasons.append(f"reserve band context is {reserve_band}")

    if drift_ratio is not None:
        if drift_ratio >= WORKSPACE_THRESHOLD_POLICY.heart_rate_extreme_drift_ratio:
            severity += 3.0
        elif drift_ratio >= WORKSPACE_THRESHOLD_POLICY.heart_rate_high_drift_ratio:
            severity += 2.0
        elif drift_ratio >= WORKSPACE_THRESHOLD_POLICY.heart_rate_watch_drift_ratio:
            severity += 1.0
        if drift_ratio >= WORKSPACE_THRESHOLD_POLICY.heart_rate_watch_drift_ratio:
            reasons.append(f"heart-rate load is {drift_ratio:.3f} above expected personal baseline")
            heart_rate_pressure = True

    effort_score = gate_input.signals.workout_effort_score
    if effort_score is not None:
        if effort_score >= 9:
            severity += 3.0
        elif effort_score >= 8:
            severity += 2.0
        elif effort_score >= 7:
            severity += 1.0
        if effort_score >= 7:
            source = gate_input.signals.workout_effort_score_source or "provider workout effort score"
            reasons.append(f"workout effort score {effort_score:g} from {source} is provider source value only")
            corroborating_dimensions.add("effort")

    heart_rate_zone = gate_input.signals.heart_rate_zone
    if heart_rate_zone in {"z4", "z5"}:
        severity += 2.0 if heart_rate_zone == "z5" else 1.0
        reasons.append(f"current heart-rate zone is {heart_rate_zone}")
        heart_rate_pressure = True

    training_load = gate_input.signals.training_load_classification
    if training_load in {"above", "well_above"}:
        severity += 2.0 if training_load == "well_above" else 1.0
        reasons.append(f"provider training load classification is {training_load}")
        corroborating_dimensions.add("effort")

    oxygen_uptake_ratio = _oxygen_uptake_ratio(gate_input)
    if oxygen_uptake_ratio is not None:
        if oxygen_uptake_ratio <= WORKSPACE_THRESHOLD_POLICY.oxygen_uptake_retreat_ratio:
            severity += 3.0
        elif oxygen_uptake_ratio <= WORKSPACE_THRESHOLD_POLICY.oxygen_uptake_stop_ratio:
            severity += 2.0
        elif oxygen_uptake_ratio <= WORKSPACE_THRESHOLD_POLICY.oxygen_uptake_watch_ratio:
            severity += 1.0
        if oxygen_uptake_ratio <= WORKSPACE_THRESHOLD_POLICY.oxygen_uptake_watch_ratio:
            reasons.append(
                f"oxygen uptake proxy is {oxygen_uptake_ratio:.2f}x the personal or expected context"
            )
            corroborating_dimensions.add("oxygen_uptake")

    altitude_ratio = _altitude_oxygen_availability_ratio(gate_input.route_context)
    if altitude_ratio is not None and altitude_ratio <= WORKSPACE_THRESHOLD_POLICY.altitude_oxygen_pressure_ratio:
        severity += 1.0 if heart_rate_pressure or effort_score else 0.0
        reasons.append(
            f"route altitude oxygen availability proxy is {altitude_ratio:.2f}x sea-level context"
        )
        corroborating_dimensions.add("oxygen_availability")

    if gate_input.signals.oxygen_saturation_pct is not None:
        source = gate_input.signals.oxygen_saturation_source or "provider oxygen saturation"
        reasons.append(f"oxygen saturation {source} is preserved as provider source value only")
        reasons.append("oxygen saturation percent is not compared to VO2max ml/kg/min")

    work_output_ratio = _work_output_ratio_to_reset_budget(gate_input)
    if work_output_ratio is not None:
        if work_output_ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_overdraft_ratio:
            severity += 2.0
        elif work_output_ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_pre_reset_ratio:
            severity += 1.0
        if work_output_ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_pre_reset_ratio:
            reasons.append(f"work output is {work_output_ratio:.2f}x the personal reset cue budget")
            corroborating_dimensions.add("work_output")

    movement_efficiency_ratio = _movement_efficiency_ratio(gate_input)
    if movement_efficiency_ratio is not None:
        if movement_efficiency_ratio <= WORKSPACE_THRESHOLD_POLICY.movement_efficiency_stop_ratio:
            severity += 2.0
        elif movement_efficiency_ratio <= WORKSPACE_THRESHOLD_POLICY.movement_efficiency_watch_ratio:
            severity += 1.0
        if movement_efficiency_ratio <= WORKSPACE_THRESHOLD_POLICY.movement_efficiency_watch_ratio:
            reasons.append(
                f"movement efficiency is {movement_efficiency_ratio:.2f}x the personal or route context"
            )
            corroborating_dimensions.add("performance")
        if (
            heart_rate_pressure
            and movement_efficiency_ratio <= WORKSPACE_THRESHOLD_POLICY.movement_efficiency_stop_ratio
        ):
            severity += 1.0
            reasons.append(
                "high heart-rate pressure plus low movement efficiency indicates an exertion-cost window"
            )

    if recovery_state == "fast":
        severity = max(0.0, severity - 1.5)
        reasons.append("heart-rate recovery is faster than personal context; active pace-down recovery may be enough")
    elif recovery_state == "expected":
        reasons.append("heart-rate recovery is within the personal expected context")
    elif recovery_state == "slow":
        severity += 2.0
        reasons.append("heart-rate recovery is slower than personal context after high output")
        corroborating_dimensions.add("recovery")

    breathing_recovery = gate_input.signals.breathing_recovery_quality
    if breathing_recovery == "settled":
        severity = max(0.0, severity - 0.5)
        reasons.append("breathing recovery is settled during active recovery")
    elif breathing_recovery == "not_settled":
        severity += 1.0
        reasons.append("breathing recovery has not settled; this is an advisory field cue, not diagnosis")
        corroborating_dimensions.add("recovery")

    rest_ratio = gate_input.signals.rest_ratio_recent_window
    if rest_ratio is not None and rest_ratio >= 0.25:
        severity += 2.0 if rest_ratio >= 0.40 else 1.0
        reasons.append(f"recent rest ratio is {rest_ratio:.2f}")
        corroborating_dimensions.add("performance")

    gait_quality = gate_input.signals.posture_or_gait_quality
    if gait_quality in {"poor", "unstable"}:
        severity += 2.0 if gait_quality == "unstable" else 1.0
        reasons.append(f"posture or gait quality is {gait_quality}")
        corroborating_dimensions.add("performance")

    discomfort = gate_input.signals.user_reported_discomfort
    if discomfort in {"cannot_continue", "manual_help_request"}:
        explicit_alert_request = True
        reasons.append("user explicitly reported they cannot continue or requested help")
        corroborating_dimensions.add("subjective")
    elif discomfort == "stop_requested":
        severity += 2.0
        reasons.append("user explicitly requested a stop")
        corroborating_dimensions.add("subjective")
    elif discomfort == "mild":
        severity += 1.0
        reasons.append("user reported mild discomfort without medical inference")
        corroborating_dimensions.add("subjective")

    if (
        severity >= 5
        and gate_input.route_context.daylight_buffer_minutes
        <= WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
    ):
        severity += 1.0
        reasons.append("high strain coincides with tight remaining daylight buffer")

    if heart_rate_pressure and not corroborating_dimensions:
        reasons.append("heart-rate elevation alone is not treated as fatigue, low uptake, or danger")
    if not _has_oxygen_context(gate_input):
        reasons.append("oxygen uptake or altitude oxygen-availability context is missing")

    return PhysiologicEvidence(
        severity_score=severity,
        reasons=reasons,
        explicit_alert_request=explicit_alert_request,
        heart_rate_pressure=heart_rate_pressure,
        recovery_state=recovery_state,
        corroborating_dimensions=frozenset(corroborating_dimensions),
    )


def _gate_state(
    gate_input: PhysiologicGateInput,
    evidence: PhysiologicEvidence,
) -> PhysiologicGateState:
    if evidence.explicit_alert_request:
        return "alert_candidate"
    if gate_input.observed_at_offset_s < 600 and evidence.severity_score < 3:
        return "warmup"
    if evidence.severity_score < 1:
        return "normal"
    if (
        evidence.recovery_state == "fast"
        and evidence.severity_score < 6
        and not evidence.corroborating_dimensions.intersection({"oxygen_uptake", "oxygen_availability", "performance", "subjective"})
    ):
        return "watch"
    if evidence.heart_rate_pressure and not evidence.corroborating_dimensions:
        return "watch"
    if evidence.severity_score < 3:
        return "watch"
    if evidence.severity_score < 6:
        return "stop_and_rest"
    if (
        _has_external_pressure(gate_input.route_context)
        and "work_output" in evidence.corroborating_dimensions
        and evidence.corroborating_dimensions.intersection(
            {"recovery", "performance", "oxygen_uptake", "oxygen_availability", "subjective"}
        )
    ):
        return "retreat_suggested"
    if (
        gate_input.route_context.daylight_buffer_minutes <= WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
        and "performance" in evidence.corroborating_dimensions
        and evidence.corroborating_dimensions.intersection({"oxygen_uptake", "oxygen_availability", "subjective"})
    ):
        return "retreat_suggested"
    return "stop_and_rest"


def _observation_window_result(
    gate_input: PhysiologicGateInput,
    evidence: PhysiologicEvidence,
    raw_state: PhysiologicGateState,
) -> PhysiologicObservationWindowResult:
    context = gate_input.observation_window
    elapsed_minutes = (
        context.elapsed_minutes
        if context.elapsed_minutes is not None
        else gate_input.observed_at_offset_s // 60
    )
    complete = elapsed_minutes >= context.window_minutes
    bypass_reason = _observation_window_bypass_reason(gate_input, evidence, raw_state)
    should_hold = (
        context.require_complete_window_for_stop_or_retreat
        and not complete
        and raw_state in {"stop_and_rest", "retreat_suggested"}
        and bypass_reason is None
    )
    if should_hold:
        return PhysiologicObservationWindowResult(
            window_minutes=context.window_minutes,
            elapsed_minutes=elapsed_minutes,
            complete=False,
            noise_reduction_applied=True,
            state_before_window_gate=raw_state,
            state_after_window_gate="watch",
            rationale=(
                f"{context.window_minutes}-minute observation window has only "
                f"{elapsed_minutes} minutes; holding at watch to reduce transient noise"
            ),
        )
    if raw_state in {"stop_and_rest", "retreat_suggested"} and complete:
        rationale = f"{context.window_minutes}-minute observation window is complete"
    else:
        rationale = f"{context.window_minutes}-minute observation window did not need escalation gating"
    return PhysiologicObservationWindowResult(
        window_minutes=context.window_minutes,
        elapsed_minutes=elapsed_minutes,
        complete=complete,
        noise_reduction_applied=False,
        state_before_window_gate=raw_state,
        state_after_window_gate=raw_state,
        bypass_reason=bypass_reason,
        rationale=rationale,
    )


def _observation_window_bypass_reason(
    gate_input: PhysiologicGateInput,
    evidence: PhysiologicEvidence,
    raw_state: PhysiologicGateState,
) -> str | None:
    context = gate_input.observation_window
    if raw_state == "alert_candidate" and context.allow_user_request_bypass:
        return "explicit help request bypasses the observation window"
    if (
        context.allow_user_request_bypass
        and gate_input.signals.user_reported_discomfort in {"stop_requested", "cannot_continue", "manual_help_request"}
    ):
        return "explicit user stop/help context bypasses the observation window"
    if (
        context.allow_route_pressure_bypass
        and raw_state == "retreat_suggested"
        and _has_external_pressure(gate_input.route_context)
    ):
        return "route pressure bypasses the observation window for retreat review"
    if (
        context.allow_route_pressure_bypass
        and raw_state == "stop_and_rest"
        and gate_input.route_context.daylight_buffer_minutes <= WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
        and evidence.corroborating_dimensions.intersection({"oxygen_uptake", "oxygen_availability", "performance"})
    ):
        return "tight daylight plus physiologic corroboration bypasses the observation window"
    return None


def _required_action(state: PhysiologicGateState) -> PhysiologicRequiredAction:
    return {
        "warmup": "none",
        "normal": "none",
        "watch": "slow_down",
        "stop_and_rest": "rest_now",
        "retreat_suggested": "retreat_review",
        "alert_candidate": "alert_review",
    }[state]


def _rest_directive(state: PhysiologicGateState) -> RestDirective:
    if state == "watch":
        return RestDirective(recommended=False, minimum_minutes=0, recheck_after_minutes=15)
    if state == "stop_and_rest":
        return RestDirective(recommended=True, minimum_minutes=15, recheck_after_minutes=15)
    if state == "retreat_suggested":
        return RestDirective(recommended=True, minimum_minutes=20, recheck_after_minutes=10)
    if state == "alert_candidate":
        return RestDirective(recommended=True, minimum_minutes=0, recheck_after_minutes=0)
    return RestDirective(recommended=False, minimum_minutes=0, recheck_after_minutes=0)


def _eta_delay_minutes(state: PhysiologicGateState) -> int:
    return {
        "warmup": 0,
        "normal": 0,
        "watch": 5,
        "stop_and_rest": 20,
        "retreat_suggested": 35,
        "alert_candidate": 60,
    }[state]


def _confidence(gate_input: PhysiologicGateInput, signal_count: int) -> Confidence:
    if not gate_input.baseline.personal_envelope_available or signal_count < 2:
        return "low"
    if signal_count >= 5 and gate_input.data_quality.heart_rate_confidence != "low":
        return "high"
    return "medium"


def _heart_rate_drift_ratio(
    signals: PhysiologicGateSignals,
    baseline: PhysiologicBaselineContext,
) -> float | None:
    if signals.heart_rate_bpm is None or baseline.expected_heart_rate_bpm is None:
        return None
    return round((signals.heart_rate_bpm - baseline.expected_heart_rate_bpm) / baseline.expected_heart_rate_bpm, 3)


def _oxygen_uptake_ratio(gate_input: PhysiologicGateInput) -> float | None:
    if gate_input.signals.oxygen_uptake_ratio_to_personal_baseline is not None:
        return round(gate_input.signals.oxygen_uptake_ratio_to_personal_baseline, 3)
    if (
        gate_input.signals.estimated_oxygen_uptake_ml_kg_min is not None
        and gate_input.baseline.expected_oxygen_uptake_ml_kg_min
    ):
        return round(
            gate_input.signals.estimated_oxygen_uptake_ml_kg_min
            / gate_input.baseline.expected_oxygen_uptake_ml_kg_min,
            3,
        )
    return None


def _altitude_oxygen_availability_ratio(route_context: PhysiologicRouteContext) -> float | None:
    if route_context.altitude_oxygen_availability_ratio is not None:
        return round(route_context.altitude_oxygen_availability_ratio, 3)
    if route_context.altitude_m is None:
        return None
    return round(pow(2.718281828, -route_context.altitude_m / 8434.5), 3)


def _heart_rate_recovery_state(
    signals: PhysiologicGateSignals,
) -> Literal["fast", "expected", "slow"] | None:
    ratio = signals.heart_rate_recovery_ratio_to_personal_baseline
    if ratio is None:
        return None
    if ratio >= WORKSPACE_THRESHOLD_POLICY.fast_recovery_ratio_to_personal_baseline:
        return "fast"
    if ratio <= WORKSPACE_THRESHOLD_POLICY.slow_recovery_ratio_to_personal_baseline:
        return "slow"
    return "expected"


def _work_output_ratio_to_reset_budget(gate_input: PhysiologicGateInput) -> float | None:
    if gate_input.signals.work_output_ratio_to_reset_budget is not None:
        return round(gate_input.signals.work_output_ratio_to_reset_budget, 3)
    if gate_input.signals.cumulative_work_output_kj is None:
        return None
    reset_budget = gate_input.baseline.reset_cue_work_output_kj
    if reset_budget is None and gate_input.baseline.typical_completed_work_output_kj is not None:
        reset_budget = (
            gate_input.baseline.typical_completed_work_output_kj
            * gate_input.baseline.work_output_reset_ratio_hint
        )
    if not reset_budget:
        return None
    return round(gate_input.signals.cumulative_work_output_kj / reset_budget, 3)


def _movement_efficiency_ratio(gate_input: PhysiologicGateInput) -> float | None:
    if gate_input.signals.movement_efficiency_ratio_to_personal_baseline is not None:
        return round(gate_input.signals.movement_efficiency_ratio_to_personal_baseline, 3)
    if gate_input.signals.pace_mps is not None and gate_input.baseline.expected_pace_mps:
        return round(gate_input.signals.pace_mps / gate_input.baseline.expected_pace_mps, 3)
    if gate_input.signals.cadence_spm is not None and gate_input.baseline.expected_cadence_spm:
        return round(gate_input.signals.cadence_spm / gate_input.baseline.expected_cadence_spm, 3)
    return None


def _external_pressure_flags(
    route_context: PhysiologicRouteContext,
    daylight_buffer_after_delay: int,
) -> list[ExternalPressureFlag]:
    flags = list(dict.fromkeys(route_context.external_pressure_flags))
    if (
        daylight_buffer_after_delay < WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
        and "darkness_pressure" not in flags
    ):
        flags.append("darkness_pressure")
    return flags


def _has_external_pressure(route_context: PhysiologicRouteContext) -> bool:
    return (
        bool(route_context.external_pressure_flags)
        or route_context.daylight_buffer_minutes < WORKSPACE_THRESHOLD_POLICY.darkness_pressure_buffer_minutes
    )


def _exertion_overdraft_status(
    *,
    gate_input: PhysiologicGateInput,
    evidence: PhysiologicEvidence,
    state: PhysiologicGateState,
    external_pressure_flags: list[ExternalPressureFlag],
) -> ExertionOverdraftStatus:
    work_output_ratio = _work_output_ratio_to_reset_budget(gate_input)
    reset_cue_crossed = (
        work_output_ratio is not None
        and work_output_ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_pre_reset_ratio
    )
    overdraft_candidate = (
        work_output_ratio is not None
        and work_output_ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_overdraft_ratio
        and state in {"stop_and_rest", "retreat_suggested", "alert_candidate"}
    )
    involuntary_forward_pressure = bool(external_pressure_flags)
    danger_flag = overdraft_candidate and involuntary_forward_pressure
    if danger_flag:
        stage = "danger_overdraft_candidate"
    elif overdraft_candidate:
        stage = "overdraft_candidate"
    elif reset_cue_crossed:
        stage = "reset_cue"
    else:
        stage = "none"
    handoff_gates = _overdraft_handoff_gates(external_pressure_flags)
    if danger_flag and "delay_gate" not in handoff_gates:
        handoff_gates.append("delay_gate")
    if danger_flag and "pace_gate" not in handoff_gates:
        handoff_gates.append("pace_gate")
    if "companion_pace_pressure" in external_pressure_flags:
        for gate in ("companion_match_gate", "pace_gate", "delay_gate"):
            if gate not in handoff_gates:
                handoff_gates.append(gate)
    return ExertionOverdraftStatus(
        stage=stage,
        danger_flag=danger_flag,
        involuntary_forward_pressure=involuntary_forward_pressure,
        external_pressure_flags=external_pressure_flags,
        work_output_ratio_to_reset_budget=work_output_ratio,
        handoff_gates=handoff_gates,
    )


def _overdraft_handoff_gates(external_pressure_flags: list[ExternalPressureFlag]) -> list[str]:
    gates: list[str] = []
    mapping = {
        "pace_gate_failed": "pace_gate",
        "delay_gate_failed": "delay_gate",
        "darkness_pressure": "darkness_gate",
        "lost_or_routefinding_pressure": "delay_gate",
        "weather_deteriorating": "weather_gate",
        "seeking_shelter": "environment_threat_gate",
        "environment_threat": "environment_threat_gate",
        "companion_pace_pressure": "companion_match_gate",
    }
    for flag in external_pressure_flags:
        gate = mapping[flag]
        if gate not in gates:
            gates.append(gate)
    return gates


def _has_oxygen_context(gate_input: PhysiologicGateInput) -> bool:
    return any(
        value is not None
        for value in (
            gate_input.signals.estimated_oxygen_uptake_ml_kg_min,
            gate_input.signals.oxygen_uptake_ratio_to_personal_baseline,
            gate_input.signals.oxygen_saturation_pct,
            gate_input.route_context.altitude_m,
            gate_input.route_context.altitude_oxygen_availability_ratio,
        )
    )


def _signal_inventory(signals: PhysiologicGateSignals) -> tuple[int, list[str]]:
    payload = signals.model_dump()
    present = []
    missing = []
    for signal_name in PHYSIOLOGIC_SIGNAL_NAMES:
        value = payload.get(signal_name)
        if signal_name == "user_reported_discomfort" and value == "none":
            value = None
        if value is None:
            missing.append(signal_name)
        else:
            present.append(signal_name)
    return len(present), missing


def _quality_limitations(
    gate_input: PhysiologicGateInput,
    missing_signal_names: list[str],
) -> list[str]:
    limitations = {
        *gate_input.data_quality.limitations,
        "physiologic gate is deterministic advisory evidence only",
        "live network calls are not made by this gate",
        (
            f"{gate_input.observation_window.window_minutes}-minute observation window reduces "
            "single-frame noise before stop/retreat escalation"
        ),
    }
    if missing_signal_names:
        limitations.add("missing signals lower confidence and are not interpreted as safe")
    if gate_input.signals.workout_effort_score is not None:
        limitations.add("provider workout effort is a source value, not Scout truth")
    if gate_input.signals.oxygen_saturation_pct is not None:
        limitations.add("provider oxygen saturation is a source value, not Scout truth")
        limitations.add("oxygen saturation percent is not compared to VO2max ml/kg/min")
    if _has_oxygen_context(gate_input):
        limitations.add("oxygen uptake and altitude context are advisory trend inputs, not diagnosis")
    if gate_input.signals.heart_rate_recovery_ratio_to_personal_baseline is not None:
        limitations.add("heart-rate recovery is an advisory active/passive recovery signal, not diagnosis")
    if gate_input.signals.cumulative_work_output_kj is not None:
        limitations.add("work output kJ is a reset-cue source value, not maximum capability or diagnosis")
    if _movement_efficiency_ratio(gate_input) is not None:
        limitations.add(
            "movement efficiency is performance corroboration only; low efficiency is not a medical diagnosis"
        )
    if _has_external_pressure(gate_input.route_context):
        limitations.add("exertion overdraft danger flag is advisory handoff evidence, not safety truth")
    return sorted(limitations)


def _combine_energy_data_quality(
    observation_quality: ScoutEnergyDataQuality,
    baseline_quality: dict[str, Any],
) -> ScoutEnergyDataQuality:
    order = {"low": 0, "medium": 1, "high": 2}
    limitations = sorted(
        {
            *observation_quality.limitations,
            *baseline_quality.get("limitations", []),
            "runtime physiologic gate is advisory evidence only",
        }
    )
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min(
            observation_quality.heart_rate_confidence,
            baseline_quality.get("heart_rate_confidence", "low"),
            key=order.get,
        ),
        gps_confidence=min(
            observation_quality.gps_confidence,
            baseline_quality.get("gps_confidence", "low"),
            key=order.get,
        ),
        missing_hr_seconds=observation_quality.missing_hr_seconds + baseline_quality.get("missing_hr_seconds", 0),
        provider_value_confidence=min(
            observation_quality.provider_value_confidence,
            baseline_quality.get("provider_value_confidence", "low"),
            key=order.get,
        ),
        limitations=limitations,
    )


def _enforce_privacy(privacy: ScoutEnergyPrivacy) -> None:
    if privacy.raw_health_payload_shared:
        raise ValueError("physiologic gate must not share raw health payload")
    if privacy.raw_samples_embedded:
        raise ValueError("physiologic gate must not embed raw samples")
    if privacy.raw_track_shared:
        raise ValueError("physiologic gate must not share raw tracks")
    if privacy.exact_timestamps_shared:
        raise ValueError("physiologic gate must not share exact timestamps")
    if privacy.home_work_trace_shared:
        raise ValueError("physiologic gate must not share home/work traces")


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return deduped


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
