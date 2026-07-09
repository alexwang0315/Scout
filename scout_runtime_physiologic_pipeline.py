from __future__ import annotations

import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
    sha256_file,
)
from scout_runtime_physiologic_gate import (
    PhysiologicBaselineContext,
    PhysiologicGateInput,
    PhysiologicGateOutput,
    PhysiologicObservationWindowContext,
    PhysiologicGateSignals,
    PhysiologicGateState,
    PhysiologicRouteContext,
    WORKSPACE_THRESHOLD_POLICY,
    build_runtime_physiologic_gate,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


ActivityKind = Literal["running", "walking", "hiking", "other"]
RecoveryClassification = Literal["fast", "expected", "slow", "unknown"]
ResetStage = Literal["none", "pre_reset", "reset_cue", "overdraft_candidate"]
EnergyOutputSource = Literal["provider_active_energy_kj", "running_power_integral_kj", "missing"]
LivePhysiologicFixtureProvider = Literal["apple_healthkit_live_fixture", "garmin_live_fixture", "manual_fixture"]
WindowRestCostStage = Literal["none", "watch", "rest_cost", "recovery_debt_candidate"]
RouteSegmentTimingSource = Literal["min", "p50", "p75", "max", "manual_guide"]
RoutePressureCompositeAction = Literal[
    "continue_monitoring",
    "slow_down",
    "stop_and_recheck",
    "team_pace_reset",
    "route_pressure_review",
    "retreat_review",
    "alert_review",
]
PhysioReviewTrendDirection = Literal["improved", "worse", "unchanged", "not_compared"]
PhysioReviewPriority = Literal["none", "monitor", "review", "urgent_review"]


class HighHeartRateBurden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds_bpm: list[int] = Field(default_factory=lambda: [160, 165, 170])
    total_minutes_at_or_above: dict[str, float] = Field(default_factory=dict)
    continuous_minutes_at_or_above: dict[str, float] = Field(default_factory=dict)
    percent_samples_at_or_above: dict[str, float] = Field(default_factory=dict)
    sample_count: int = Field(ge=0)
    sample_cadence_s: int | None = Field(default=None, ge=1)


class OxygenUptakeEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "speed_grade_proxy.v0"
    vo2max_estimate_ml_kg_min: float | None = Field(default=None, ge=0)
    baseline_vo2max_ml_kg_min: float | None = Field(default=None, ge=0)
    estimated_oxygen_cost_ml_kg_min: float | None = Field(default=None, ge=0)
    oxygen_uptake_ratio_to_personal_baseline: float | None = Field(default=None, ge=0)
    altitude_m: float | None = Field(default=None, ge=-500)
    altitude_oxygen_availability_ratio: float | None = Field(default=None, gt=0, le=1.1)
    oxygen_saturation_pct: float | None = Field(default=None, ge=0, le=100)
    provider_values_are_scout_truth: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "OxygenUptakeEstimate":
        if self.provider_values_are_scout_truth:
            raise ValueError("provider oxygen or VO2max values must not be Scout truth")
        return self


class HeartRateRecoveryFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recovery_drop_bpm: float | None = Field(default=None, ge=0)
    baseline_recovery_drop_bpm: float | None = Field(default=None, ge=0)
    recovery_ratio_to_personal_baseline: float | None = Field(default=None, ge=0)
    classification: RecoveryClassification = "unknown"
    source_value_only: bool = True


class WorkOutputResetFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy_output_kj: float | None = Field(default=None, ge=0)
    energy_output_source: EnergyOutputSource = "missing"
    typical_completed_output_kj: float | None = Field(default=None, ge=0)
    reset_cue_kj: float | None = Field(default=None, ge=0)
    ratio_to_reset_budget: float | None = Field(default=None, ge=0)
    reset_stage: ResetStage = "none"
    source_value_only: bool = True
    maximum_capability_claimed: bool = False

    @model_validator(mode="after")
    def enforce_boundary(self) -> "WorkOutputResetFeature":
        if not self.source_value_only:
            raise ValueError("work output must remain a source value")
        if self.maximum_capability_claimed:
            raise ValueError("work output reset cue must not claim maximum capability")
        return self


class WindowRestCostFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = "following_window_rest_cost.v0"
    rest_ratio_recent_window: float = Field(ge=0, le=1)
    following_rest_cost_minutes_next_60m: float = Field(ge=0)
    following_rest_window_count: int = Field(ge=0)
    stage: WindowRestCostStage = "none"
    source_value_only: bool = True
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "WindowRestCostFeature":
        if not self.source_value_only:
            raise ValueError("window rest cost must remain a source value")
        return self


class CompanionPacePressureWindowEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_index: int = Field(ge=1)
    elapsed_start_min: int = Field(ge=0)
    elapsed_end_min: int = Field(ge=0)
    companion_pace_ratio_to_user_reference: float | None = Field(default=None, ge=0)
    movement_efficiency_ratio_to_session_reference: float | None = Field(default=None, ge=0)
    heart_rate_pressure: bool
    high_hr_low_efficiency_window: bool
    rest_cost_stage: WindowRestCostStage
    following_rest_cost_minutes_next_60m: float = Field(ge=0)
    pressure_detected: bool
    reason_codes: list[str] = Field(default_factory=list)


class CompanionPacePressureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_companion_pace_pressure_evidence"
    artifact_version: str = "companion_pace_pressure_evidence.v1"
    source_provider: str
    source_path: str
    sha256: str
    source_replay_sha256: str
    session_index: int = Field(ge=1)
    companion_reference_source: str
    companion_reference_pace_mps: float | None = Field(default=None, ge=0)
    companion_reference_cadence_spm: float | None = Field(default=None, ge=0)
    user_reference_pace_mps: float | None = Field(default=None, ge=0)
    user_reference_cadence_spm: float | None = Field(default=None, ge=0)
    companion_pace_ratio_to_user_reference: float | None = Field(default=None, ge=0)
    pressure_detected: bool
    pressure_window_count: int = Field(ge=0)
    estimated_rest_cost_minutes: float = Field(ge=0)
    pressure_windows: list[CompanionPacePressureWindowEvidence]
    external_pressure_flags: list[str] = Field(default_factory=list)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "CompanionPacePressureEvidence":
        _enforce_privacy(self.privacy)
        if self.pressure_detected and "companion_pace_pressure" not in self.external_pressure_flags:
            raise ValueError("detected companion pace pressure must emit companion_pace_pressure flag")
        return self


class PhysiologicActivityWindowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_index: int = Field(ge=1)
    window_index: int = Field(ge=1)
    elapsed_start_min: int = Field(ge=0)
    elapsed_end_min: int = Field(ge=0)
    duration_min: float = Field(ge=0)
    distance_m: float = Field(ge=0)
    active_energy_kj: float | None = Field(default=None, ge=0)
    avg_heart_rate_bpm: float | None = Field(default=None, ge=0)
    max_heart_rate_bpm: float | None = Field(default=None, ge=0)
    p90_heart_rate_bpm: float | None = Field(default=None, ge=0)
    high_heart_rate_burden: HighHeartRateBurden
    heart_rate_pressure: bool
    pace_mps: float | None = Field(default=None, ge=0)
    cadence_spm: float | None = Field(default=None, ge=0)
    movement_efficiency_ratio_to_session_reference: float | None = Field(default=None, ge=0)
    high_hr_low_efficiency_window: bool
    rest_cost: WindowRestCostFeature


class PhysiologicWindowedActivityReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_physiologic_windowed_activity_replay"
    artifact_version: str = "runtime_physiologic_windowed_activity_replay.v1"
    source_provider: str
    source_path: str
    sha256: str
    activity_type: ActivityKind
    session_index: int = Field(ge=1)
    window_minutes: int = Field(ge=1, le=60)
    window_count: int = Field(ge=0)
    session_reference_pace_mps: float | None = Field(default=None, ge=0)
    session_reference_cadence_spm: float | None = Field(default=None, ge=0)
    windows: list[PhysiologicActivityWindowSummary]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "PhysiologicWindowedActivityReplay":
        _enforce_privacy(self.privacy)
        return self


class WalkingHikingBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_walking_hiking_baseline"
    artifact_version: str = "walking_hiking_baseline.v1"
    source_provider: str = "scout_runtime_windowed_activity_replay"
    source_path: str
    sha256: str
    activity_types: list[ActivityKind]
    replay_count: int = Field(ge=0)
    window_count: int = Field(ge=0)
    sustainable_pace_mps: float | None = Field(default=None, ge=0)
    sustainable_cadence_spm: float | None = Field(default=None, ge=0)
    typical_active_energy_kj_per_hour: float | None = Field(default=None, ge=0)
    typical_completed_output_kj: float | None = Field(default=None, ge=0)
    reset_cue_kj: float | None = Field(default=None, ge=0)
    reset_ratio_hint: float = Field(default=1.25, ge=1.0, le=2.0)
    rest_or_slowdown_frequency_per_hour: float = Field(ge=0)
    median_rest_ratio_per_window: float = Field(ge=0, le=1)
    median_rest_cost_minutes_next_60m: float = Field(ge=0)
    high_hr_low_efficiency_window_rate: float = Field(ge=0, le=1)
    ascent_efficiency_m_per_hour: float | None = Field(default=None, ge=0)
    descent_conservatism_index: float | None = Field(default=None, ge=0)
    runtime_baseline_context: PhysiologicBaselineContext
    confidence: Literal["low", "medium", "high"] = "low"
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "WalkingHikingBaseline":
        _enforce_privacy(self.privacy)
        return self


class RouteSegmentReferenceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_route_segment_reference_context"
    artifact_version: str = "route_segment_reference_context.v1"
    source_provider: str
    source_path: str
    sha256: str
    segment_id: str
    distance_m: float = Field(gt=0)
    ascent_m: float = Field(default=0.0, ge=0)
    descent_m: float = Field(default=0.0, ge=0)
    sample_count: int = Field(ge=0)
    distance_filter_m: float | None = Field(default=None, ge=0)
    reference_min_minutes: float | None = Field(default=None, gt=0)
    reference_p50_minutes: float | None = Field(default=None, gt=0)
    reference_p75_minutes: float | None = Field(default=None, gt=0)
    reference_max_minutes: float | None = Field(default=None, gt=0)
    manual_guide_minutes: float | None = Field(default=None, gt=0)
    selected_time_source: RouteSegmentTimingSource = "p75"
    selected_reference_minutes: float = Field(gt=0)
    route_expected_pace_mps: float = Field(gt=0)
    route_effort_units: float = Field(ge=0)
    route_effort_method: str = "distance_ascent_descent_units.v1"
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "RouteSegmentReferenceContext":
        _enforce_privacy(self.privacy)
        return self


class RouteSegmentWindowContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_index: int = Field(ge=1)
    elapsed_start_min: int = Field(ge=0)
    elapsed_end_min: int = Field(ge=0)
    segment_id: str
    route_expected_pace_mps: float = Field(gt=0)
    movement_efficiency_ratio_to_session_reference: float | None = Field(default=None, ge=0)
    movement_efficiency_ratio_to_route_context: float | None = Field(default=None, ge=0)
    heart_rate_pressure: bool
    high_hr_low_efficiency_window: bool
    route_pressure_window: bool
    reason_codes: list[str] = Field(default_factory=list)


class RouteSegmentContextualizedReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_route_segment_contextualized_replay"
    artifact_version: str = "route_segment_contextualized_replay.v1"
    source_provider: str = "scout_runtime_route_segment_contextualizer"
    source_path: str
    sha256: str
    source_replay_sha256: str
    source_segment_sha256: str
    segment_context: RouteSegmentReferenceContext
    window_count: int = Field(ge=0)
    route_pressure_window_count: int = Field(ge=0)
    selected_time_source: RouteSegmentTimingSource
    selected_reference_minutes: float = Field(gt=0)
    route_expected_pace_mps: float = Field(gt=0)
    windows: list[RouteSegmentWindowContext]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "RouteSegmentContextualizedReplay":
        _enforce_privacy(self.privacy)
        if self.route_pressure_window_count != sum(1 for window in self.windows if window.route_pressure_window):
            raise ValueError("route pressure window count must match contextualized windows")
        return self


class PhysiologicSessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_session_summary"
    artifact_version: str = "physiologic_session_summary.v1"
    session_index: int = Field(ge=1)
    activity_type: ActivityKind
    duration_s: int = Field(ge=0)
    distance_m: float = Field(default=0.0, ge=0)
    ascent_m: float = Field(default=0.0, ge=0)
    avg_heart_rate_bpm: float | None = Field(default=None, ge=0)
    max_heart_rate_bpm: float | None = Field(default=None, ge=0)
    p90_heart_rate_bpm: float | None = Field(default=None, ge=0)
    start_heart_rate_avg_5m_bpm: float | None = Field(default=None, ge=0)
    start_heart_rate_avg_10m_bpm: float | None = Field(default=None, ge=0)
    high_heart_rate_burden: HighHeartRateBurden
    vo2max_estimate_ml_kg_min: float | None = Field(default=None, ge=0)
    physical_effort_score: float | None = Field(default=None, ge=0)
    running_power_w: float | None = Field(default=None, ge=0)
    running_speed_kmh: float | None = Field(default=None, ge=0)
    active_energy_kj: float | None = Field(default=None, ge=0)
    oxygen_saturation_pct: float | None = Field(default=None, ge=0, le=100)
    oxygen_uptake: OxygenUptakeEstimate = Field(default_factory=OxygenUptakeEstimate)
    heart_rate_recovery: HeartRateRecoveryFeature = Field(default_factory=HeartRateRecoveryFeature)
    work_output: WorkOutputResetFeature = Field(default_factory=WorkOutputResetFeature)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


class PhysiologicFeatureBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_feature_baseline"
    artifact_version: str = "physiologic_feature_baseline.v1"
    session_count: int = Field(ge=0)
    baseline_vo2max_ml_kg_min: float | None = Field(default=None, ge=0)
    baseline_recovery_drop_bpm: float | None = Field(default=None, ge=0)
    typical_completed_output_kj: float | None = Field(default=None, ge=0)
    reset_cue_kj: float | None = Field(default=None, ge=0)
    reset_ratio_hint: float = Field(default=1.25, ge=1.0, le=2.0)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


class PhysiologicFeatureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_physiologic_feature_set"
    artifact_version: str = "runtime_physiologic_feature_set.v1"
    source_provider: str
    source_path: str
    sha256: str
    session_count: int = Field(ge=0)
    sessions: list[PhysiologicSessionSummary]
    baseline: PhysiologicFeatureBaseline
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "PhysiologicFeatureSet":
        _enforce_privacy(self.privacy)
        return self


class PhysiologicStateSmoothingFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_index: int = Field(ge=1)
    raw_state: PhysiologicGateState
    smoothed_state: PhysiologicGateState
    raw_required_action: str
    smoothed_required_action: str
    hold_reason: str


class PhysiologicStateSmoothingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_state_smoothing"
    artifact_version: str = "physiologic_state_smoothing.v1"
    source_provider: str
    source_path: str
    sha256: str
    frame_count: int = Field(ge=0)
    frames: list[PhysiologicStateSmoothingFrame]
    debounce_frames_for_stop: int = Field(default=2, ge=1)
    retreat_promotes_immediately_with_route_pressure: bool = True
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


class PhysiologicRoutePressureHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_route_pressure_handoff"
    artifact_version: str = "physiologic_route_pressure_handoff.v1"
    source_provider: str
    source_path: str
    sha256: str
    physiologic_state: PhysiologicGateState
    required_action: str
    eta_delay_minutes: int = Field(ge=0)
    daylight_buffer_after_delay_minutes: int
    route_pressure_review_required: bool
    handoff_gates: list[str] = Field(default_factory=list)
    exertion_overdraft_stage: str
    danger_flag: bool
    advisory_only: bool = True
    phase1_runtime_safety_truth: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "PhysiologicRoutePressureHandoff":
        if not self.advisory_only:
            raise ValueError("route-pressure handoff must remain advisory")
        if self.phase1_runtime_safety_truth or self.safety_api_called or self.outbound_alert_sent:
            raise ValueError("route-pressure handoff cannot mutate safety truth, call safety APIs, or alert")
        return self


class RoutePressureComposerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_route_pressure_composer_result"
    artifact_version: str = "route_pressure_composer_result.v1"
    source_provider: str = "scout_runtime_route_pressure_composer"
    source_path: str
    sha256: str
    physiologic_state: PhysiologicGateState
    required_action: RoutePressureCompositeAction
    rest_now: bool
    team_pace_reset_recommended: bool
    route_pressure_review_required: bool
    retreat_review_required: bool
    alert_review_required: bool
    eta_delay_minutes: int = Field(ge=0)
    physiologic_eta_delay_minutes: int = Field(ge=0)
    rest_cost_delay_minutes: float = Field(ge=0)
    companion_pressure_detected: bool
    pace_gate_failed: bool = False
    delay_gate_failed: bool = False
    handoff_gates: list[str] = Field(default_factory=list)
    dominant_reasons: list[str] = Field(default_factory=list)
    advisory_only: bool = True
    phase1_runtime_safety_truth: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "RoutePressureComposerResult":
        _enforce_privacy(self.privacy)
        if not self.advisory_only:
            raise ValueError("route pressure composer must remain advisory")
        if self.phase1_runtime_safety_truth or self.safety_api_called or self.outbound_alert_sent:
            raise ValueError("route pressure composer cannot mutate safety truth, call safety APIs, or alert")
        return self


class PhysiologicAdminDebugProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_admin_debug_projection"
    artifact_version: str = "physiologic_admin_debug_projection.v1"
    source_provider: str
    source_path: str
    sha256: str
    surface: str = "admin_debug_physiologic_evidence"
    cards: list[dict[str, Any]] = Field(default_factory=list)
    timeline_items: list[dict[str, Any]] = Field(default_factory=list)
    state_semantics: dict[str, Any] = Field(default_factory=dict)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


class ProviderMetricAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str
    sample_count: int = Field(ge=0)
    min_value: float | None = None
    mean_value: float | None = None
    median_value: float | None = None
    max_value: float | None = None
    source_value_only: bool = True
    scout_truth: bool = False

    @model_validator(mode="after")
    def enforce_source_value_boundary(self) -> "ProviderMetricAggregate":
        if not self.source_value_only or self.scout_truth:
            raise ValueError("provider metric aggregates must remain source values")
        return self


class HealthAutoExportPhysioAnalysisSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_index: int = Field(ge=1)
    activity_type: ActivityKind
    window_count: int = Field(ge=0)
    duration_min: float = Field(ge=0)
    distance_km: float = Field(ge=0)
    active_energy_kj: float | None = Field(default=None, ge=0)
    session_reference_pace_mps: float | None = Field(default=None, ge=0)
    session_reference_cadence_spm: float | None = Field(default=None, ge=0)
    avg_window_hr_bpm: float | None = Field(default=None, ge=0)
    max_window_p90_hr_bpm: float | None = Field(default=None, ge=0)
    hr_pressure_windows: int = Field(ge=0)
    high_hr_low_efficiency_windows: int = Field(ge=0)
    recovery_debt_candidate_windows: int = Field(ge=0)
    slow_or_rest_windows: int = Field(ge=0)
    max_following_rest_cost_min: float = Field(ge=0)
    min_movement_efficiency_ratio: float | None = Field(default=None, ge=0)
    gate_state_counts: dict[str, int] = Field(default_factory=dict)
    max_gate_state: PhysiologicGateState
    max_eta_delay_min: int = Field(ge=0)
    dominant_reason_samples: list[str] = Field(default_factory=list)


class HealthAutoExportPhysioAnalysisOverall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_duration_min: float = Field(ge=0)
    total_distance_km: float = Field(ge=0)
    total_active_energy_kj: float = Field(ge=0)
    total_windows: int = Field(ge=0)
    total_hr_pressure_windows: int = Field(ge=0)
    total_high_hr_low_efficiency_windows: int = Field(ge=0)
    total_recovery_debt_candidate_windows: int = Field(ge=0)
    max_gate_state: PhysiologicGateState


class HealthAutoExportPhysioAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_health_auto_export_physio_analysis"
    artifact_version: str = "health_auto_export_physio_analysis.v1"
    source_provider: str
    source_path: str
    sha256: str
    activity_type: ActivityKind
    session_count: int = Field(ge=0)
    analysis_window_minutes: int = Field(ge=1, le=60)
    baseline: WalkingHikingBaseline
    sessions: list[HealthAutoExportPhysioAnalysisSession]
    provider_metric_summaries: list[ProviderMetricAggregate] = Field(default_factory=list)
    overall: HealthAutoExportPhysioAnalysisOverall
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "HealthAutoExportPhysioAnalysis":
        _enforce_privacy(self.privacy)
        return self


class HealthAutoExportPhysioMetricDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str
    previous_median_value: float | None = None
    current_median_value: float | None = None
    absolute_delta: float | None = None
    relative_delta_pct: float | None = None
    source_value_only: bool = True
    scout_truth: bool = False

    @model_validator(mode="after")
    def enforce_source_value_boundary(self) -> "HealthAutoExportPhysioMetricDelta":
        if not self.source_value_only or self.scout_truth:
            raise ValueError("provider metric deltas must remain source values")
        return self


class HealthAutoExportPhysioAnalysisDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_health_auto_export_physio_analysis_delta"
    artifact_version: str = "health_auto_export_physio_analysis_delta.v1"
    source_provider: str = "scout_runtime_physio_analysis_delta"
    source_path: str
    sha256: str
    previous_analysis_sha256: str
    current_analysis_sha256: str
    activity_type: ActivityKind
    previous_max_gate_state: PhysiologicGateState
    current_max_gate_state: PhysiologicGateState
    gate_state_rank_delta: int
    state_direction: Literal["improved", "worse", "unchanged"]
    review_candidate_change: bool
    candidate_change_reasons: list[str] = Field(default_factory=list)
    no_candidate_change_reasons: list[str] = Field(default_factory=list)
    total_high_hr_low_efficiency_window_delta: int
    total_recovery_debt_candidate_window_delta: int
    total_hr_pressure_window_delta: int
    sustainable_pace_delta_mps: float | None = None
    sustainable_pace_delta_pct: float | None = None
    reset_cue_delta_kj: float | None = None
    reset_cue_delta_pct: float | None = None
    provider_metric_deltas: list[HealthAutoExportPhysioMetricDelta] = Field(default_factory=list)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "HealthAutoExportPhysioAnalysisDelta":
        _enforce_privacy(self.privacy)
        return self


class PhysioReviewCapsule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physio_review_capsule"
    artifact_version: str = "physio_review_capsule.v1"
    source_provider: str = "scout_runtime_physio_review_capsule"
    source_path: str
    sha256: str
    current_analysis_sha256: str
    delta_sha256: str | None = None
    activity_type: ActivityKind
    current_max_gate_state: PhysiologicGateState
    trend_direction: PhysioReviewTrendDirection
    review_candidate_change: bool
    review_priority: PhysioReviewPriority
    primary_reasons: list[str] = Field(default_factory=list)
    suggested_review_actions: list[str] = Field(default_factory=list)
    total_windows: int = Field(ge=0)
    total_hr_pressure_windows: int = Field(ge=0)
    total_high_hr_low_efficiency_windows: int = Field(ge=0)
    total_recovery_debt_candidate_windows: int = Field(ge=0)
    sustainable_pace_mps: float | None = Field(default=None, ge=0)
    reset_cue_kj: float | None = Field(default=None, ge=0)
    baseline_confidence: Literal["low", "medium", "high"]
    provider_metric_names: list[str] = Field(default_factory=list)
    advisory_only: bool = True
    capability_truth: bool = False
    route_approval: bool = False
    safety_api_called: bool = False
    phase1_runtime_safety_truth: bool = False
    outbound_alert_sent: bool = False
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "PhysioReviewCapsule":
        _enforce_privacy(self.privacy)
        if not self.advisory_only or self.capability_truth or self.route_approval:
            raise ValueError("physio review capsule must remain advisory and cannot approve routes")
        if self.safety_api_called or self.phase1_runtime_safety_truth or self.outbound_alert_sent:
            raise ValueError("physio review capsule cannot call safety APIs, mutate safety truth, or alert")
        return self


def build_feature_set_from_health_auto_export(
    source_path: Path,
    *,
    activity_type: ActivityKind = "running",
    altitude_m: float | None = None,
    reset_ratio_hint: float = 1.25,
) -> PhysiologicFeatureSet:
    payload, source_provider = _load_health_auto_export_payload(source_path)
    source_sha = sha256_file(source_path)
    source_label = str(source_path)
    raw_sessions = _session_summaries_from_payload(
        payload,
        source_path=source_path,
        activity_type=activity_type,
        altitude_m=altitude_m,
    )
    if not raw_sessions:
        raise ValueError(f"Health Auto Export payload has no {activity_type} workouts")
    baseline = build_feature_baseline(raw_sessions, reset_ratio_hint=reset_ratio_hint)
    sessions = [
        _session_with_baseline_features(session, baseline=baseline, altitude_m=altitude_m)
        for session in raw_sessions
    ]
    quality = _combine_quality([session.data_quality for session in sessions])
    feature_sha = aggregate_sha256(
        [
            source_sha,
            {
                "artifact": "runtime_physiologic_feature_set",
                "session_count": len(sessions),
                "activity_type": activity_type,
                "baseline": baseline.model_dump(mode="json"),
                "session_indexes": [session.session_index for session in sessions],
            },
        ]
    )
    return PhysiologicFeatureSet(
        source_provider=source_provider,
        source_path=source_label,
        sha256=feature_sha,
        session_count=len(sessions),
        sessions=sessions,
        baseline=baseline,
        data_quality=quality,
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def build_windowed_activity_replay_from_health_auto_export(
    source_path: Path,
    *,
    activity_type: ActivityKind = "walking",
    session_index: int = 1,
    window_minutes: int = WORKSPACE_THRESHOLD_POLICY.observation_window_minutes,
    reference_pace_mps: float | None = None,
    reference_cadence_spm: float | None = None,
) -> PhysiologicWindowedActivityReplay:
    payload, source_provider = _load_health_auto_export_payload(source_path)
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict) or not isinstance(data.get("workouts"), list):
        raise ValueError("Health Auto Export windowed replay requires data.workouts")
    workouts = [
        workout
        for workout in data["workouts"]
        if isinstance(workout, dict) and _workout_type(workout) == activity_type
    ]
    if not workouts:
        raise ValueError(f"Health Auto Export payload has no {activity_type} workouts")
    if session_index < 1 or session_index > len(workouts):
        raise ValueError(f"session_index {session_index} outside available {activity_type} workouts")
    workout = workouts[session_index - 1]
    start = _parse_apple_date(_string_from_value(workout.get("start")))
    if start is None:
        raise ValueError("Health Auto Export workout requires a parseable start time for window replay")
    duration_s = round(_number_from_value(workout.get("duration")) or 0)
    if not duration_s:
        end = _parse_apple_date(_string_from_value(workout.get("end")))
        duration_s = round((end - start).total_seconds()) if end else 0
    if duration_s <= 0:
        raise ValueError("Health Auto Export workout requires positive duration for window replay")

    source_sha = sha256_file(source_path)
    heart_rate_points = _heart_rate_points(workout, start=start)
    distance_points = _quantity_points(
        workout.get("walkingAndRunningDistance"),
        start=start,
        default_units="km",
        target_units="m",
    )
    if not distance_points:
        total_distance = _quantity(workout.get("distance"), default_units="km", target_units="m") or 0.0
        distance_points = _spread_total_over_windows(total_distance, duration_s=duration_s, window_minutes=window_minutes)
    step_points = _quantity_points(workout.get("stepCount"), start=start, default_units="count", target_units="count")
    energy_points = _quantity_points(workout.get("activeEnergy"), start=start, default_units="kJ", target_units="kJ")
    if not energy_points:
        total_energy = _quantity(workout.get("activeEnergyBurned"), default_units="kJ", target_units="kJ")
        if total_energy is not None:
            energy_points = _spread_total_over_windows(total_energy, duration_s=duration_s, window_minutes=window_minutes)

    window_s = window_minutes * 60
    raw_windows: list[dict[str, Any]] = []
    for index, start_s in enumerate(range(0, duration_s, window_s), start=1):
        end_s = min(duration_s, start_s + window_s)
        duration_min = round((end_s - start_s) / 60.0, 3)
        hr_window = [(offset_s - start_s, bpm) for offset_s, bpm in heart_rate_points if start_s <= offset_s < end_s]
        hr_values = [bpm for _, bpm in hr_window]
        distance_m = _window_sum(distance_points, start_s=start_s, end_s=end_s)
        steps = _window_sum(step_points, start_s=start_s, end_s=end_s)
        active_energy_kj = _window_sum(energy_points, start_s=start_s, end_s=end_s)
        pace_mps = distance_m / (end_s - start_s) if distance_m and end_s > start_s else None
        cadence_spm = steps / duration_min if steps and duration_min else None
        raw_windows.append(
            {
                "window_index": index,
                "elapsed_start_min": round(start_s / 60),
                "elapsed_end_min": round(end_s / 60),
                "duration_min": duration_min,
                "distance_m": distance_m,
                "active_energy_kj": active_energy_kj if active_energy_kj else None,
                "hr_window": hr_window,
                "hr_values": hr_values,
                "pace_mps": pace_mps,
                "cadence_spm": cadence_spm,
            }
        )

    reference_pace = reference_pace_mps or _reference_high_efficiency_value(
        [
            window["pace_mps"]
            for window in raw_windows
            if window["duration_min"] >= window_minutes * 0.8 and window["pace_mps"] is not None
        ]
    )
    reference_cadence = reference_cadence_spm or _reference_high_efficiency_value(
        [
            window["cadence_spm"]
            for window in raw_windows
            if window["duration_min"] >= window_minutes * 0.8 and window["cadence_spm"] is not None
        ]
    )
    session_hr_reference = _reference_heart_rate([bpm for _, bpm in heart_rate_points])
    window_payloads: list[dict[str, Any]] = []
    for window in raw_windows:
        movement_ratio = _movement_efficiency_from_window(
            pace_mps=window["pace_mps"],
            cadence_spm=window["cadence_spm"],
            reference_pace_mps=reference_pace,
            reference_cadence_spm=reference_cadence,
        )
        rest_ratio = _rest_ratio_from_efficiency(movement_ratio)
        avg_hr = _average(window["hr_values"])
        p90_hr = _percentile([round(value) for value in window["hr_values"]], 0.9)
        max_hr = max(window["hr_values"]) if window["hr_values"] else None
        heart_rate_pressure = _window_heart_rate_pressure(
            avg_hr=avg_hr,
            p90_hr=p90_hr,
            max_hr=max_hr,
            session_hr_reference=session_hr_reference,
        )
        high_hr_low_efficiency = (
            heart_rate_pressure
            and movement_ratio is not None
            and movement_ratio <= WORKSPACE_THRESHOLD_POLICY.movement_efficiency_stop_ratio
        )
        window_payloads.append(
            {
                **window,
                "avg_hr": avg_hr,
                "p90_hr": p90_hr,
                "max_hr": max_hr,
                "heart_rate_pressure": heart_rate_pressure,
                "movement_ratio": movement_ratio,
                "rest_ratio": rest_ratio,
                "high_hr_low_efficiency": high_hr_low_efficiency,
            }
        )

    windows: list[PhysiologicActivityWindowSummary] = []
    for index, window in enumerate(window_payloads):
        following = window_payloads[index + 1 : index + 5]
        following_rest_cost = round(
            sum(item["rest_ratio"] * item["duration_min"] for item in following),
            3,
        )
        following_rest_count = sum(1 for item in following if item["rest_ratio"] >= 0.4)
        if window["high_hr_low_efficiency"] and following_rest_cost >= window_minutes * 0.5:
            stage: WindowRestCostStage = "recovery_debt_candidate"
        elif window["high_hr_low_efficiency"]:
            stage = "rest_cost"
        elif window["rest_ratio"] >= 0.4:
            stage = "watch"
        else:
            stage = "none"
        windows.append(
            PhysiologicActivityWindowSummary(
                session_index=session_index,
                window_index=window["window_index"],
                elapsed_start_min=window["elapsed_start_min"],
                elapsed_end_min=window["elapsed_end_min"],
                duration_min=window["duration_min"],
                distance_m=round(window["distance_m"], 3),
                active_energy_kj=round(window["active_energy_kj"], 3)
                if window["active_energy_kj"] is not None
                else None,
                avg_heart_rate_bpm=round(window["avg_hr"], 3) if window["avg_hr"] is not None else None,
                max_heart_rate_bpm=round(window["max_hr"], 3) if window["max_hr"] is not None else None,
                p90_heart_rate_bpm=window["p90_hr"],
                high_heart_rate_burden=_high_hr_burden(
                    [(offset_s, round(bpm)) for offset_s, bpm in window["hr_window"]],
                    duration_s=round(window["duration_min"] * 60),
                ),
                heart_rate_pressure=window["heart_rate_pressure"],
                pace_mps=round(window["pace_mps"], 4) if window["pace_mps"] is not None else None,
                cadence_spm=round(window["cadence_spm"], 3) if window["cadence_spm"] is not None else None,
                movement_efficiency_ratio_to_session_reference=window["movement_ratio"],
                high_hr_low_efficiency_window=window["high_hr_low_efficiency"],
                rest_cost=WindowRestCostFeature(
                    rest_ratio_recent_window=window["rest_ratio"],
                    following_rest_cost_minutes_next_60m=following_rest_cost,
                    following_rest_window_count=following_rest_count,
                    stage=stage,
                    limitations=[
                        "rest cost is inferred from aggregate distance/cadence efficiency, not raw location",
                        "recovery debt is advisory route pacing evidence, not medical diagnosis",
                    ],
                ),
            )
        )

    result_sha = aggregate_sha256(
        [
            source_sha,
            {
                "artifact": "runtime_physiologic_windowed_activity_replay",
                "activity_type": activity_type,
                "session_index": session_index,
                "window_minutes": window_minutes,
                "reference_pace_mps": reference_pace,
                "reference_cadence_spm": reference_cadence,
                "windows": [window.model_dump(mode="json") for window in windows],
            },
        ]
    )
    return PhysiologicWindowedActivityReplay(
        source_provider=source_provider,
        source_path=str(source_path),
        sha256=result_sha,
        activity_type=activity_type,
        session_index=session_index,
        window_minutes=window_minutes,
        window_count=len(windows),
        session_reference_pace_mps=round(reference_pace, 4) if reference_pace is not None else None,
        session_reference_cadence_spm=round(reference_cadence, 3) if reference_cadence is not None else None,
        windows=windows,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if heart_rate_points else "low",
            gps_confidence="low",
            missing_hr_seconds=0 if heart_rate_points else duration_s,
            sample_cadence_s=_sample_cadence(heart_rate_points),
            provider_value_confidence="medium",
            limitations=[
                "windowed replay emits aggregate windows only",
                "movement efficiency is derived from distance or cadence against a session/reference pace",
                "rest cost is an advisory ETA-delay signal, not a medical diagnosis",
                "raw health payload, raw timestamps, and raw track geometry are not embedded",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def build_walking_hiking_baseline_from_windowed_replays(
    replays: list[PhysiologicWindowedActivityReplay | dict[str, Any]],
    *,
    source_path: str = "inline:windowed_walking_hiking_replays",
    reset_ratio_hint: float = WORKSPACE_THRESHOLD_POLICY.default_work_output_reset_ratio_hint,
) -> WalkingHikingBaseline:
    replay_models = [
        replay if isinstance(replay, PhysiologicWindowedActivityReplay) else PhysiologicWindowedActivityReplay.model_validate(replay)
        for replay in replays
    ]
    if not replay_models:
        raise ValueError("walking/hiking baseline requires at least one windowed replay")
    unsupported = sorted({replay.activity_type for replay in replay_models if replay.activity_type not in {"walking", "hiking"}})
    if unsupported:
        raise ValueError(f"walking/hiking baseline does not accept activity types: {', '.join(unsupported)}")

    reference_paces = [
        replay.session_reference_pace_mps
        for replay in replay_models
        if replay.session_reference_pace_mps is not None
    ]
    reference_cadences = [
        replay.session_reference_cadence_spm
        for replay in replay_models
        if replay.session_reference_cadence_spm is not None
    ]
    replay_energy_totals = [
        _replay_active_energy_kj(replay)
        for replay in replay_models
        if _replay_active_energy_kj(replay) is not None
    ]
    replay_energy_per_hour = [
        _replay_active_energy_kj_per_hour(replay)
        for replay in replay_models
        if _replay_active_energy_kj_per_hour(replay) is not None
    ]
    all_windows = [window for replay in replay_models for window in replay.windows]
    all_rest_ratios = [window.rest_cost.rest_ratio_recent_window for window in all_windows]
    all_rest_costs = [window.rest_cost.following_rest_cost_minutes_next_60m for window in all_windows]
    total_hours = sum(sum(window.duration_min for window in replay.windows) / 60.0 for replay in replay_models)
    slowdown_windows = [
        window
        for window in all_windows
        if window.rest_cost.rest_ratio_recent_window >= 0.4
    ]
    high_hr_low_efficiency_count = sum(1 for window in all_windows if window.high_hr_low_efficiency_window)
    typical_completed_output = round(float(median(replay_energy_totals)), 3) if replay_energy_totals else None
    reset_cue = (
        round(typical_completed_output * reset_ratio_hint, 3)
        if typical_completed_output is not None
        else None
    )
    sustainable_pace = round(float(median(reference_paces)), 4) if reference_paces else None
    sustainable_cadence = round(float(median(reference_cadences)), 3) if reference_cadences else None
    replay_count = len(replay_models)
    window_count = len(all_windows)
    confidence: Literal["low", "medium", "high"]
    if replay_count >= 5 and window_count >= 20 and sustainable_pace is not None:
        confidence = "high"
    elif replay_count >= 2 and window_count >= 8 and sustainable_pace is not None:
        confidence = "medium"
    else:
        confidence = "low"
    limitations = [
        "walking/hiking baseline is derived from sanitized windowed replay artifacts only",
        "baseline is personal advisory context, not route approval or medical diagnosis",
        "ascent/descent efficiency is unavailable until route-effort or segment context is attached",
        "reset cue is a pacing context and does not claim maximum capability",
    ]
    if replay_count < 3:
        limitations.append("limited replay count keeps public/general confidence low")
    baseline_context = PhysiologicBaselineContext(
        personal_envelope_available=sustainable_pace is not None or sustainable_cadence is not None,
        expected_pace_mps=sustainable_pace,
        expected_cadence_spm=sustainable_cadence,
        typical_completed_work_output_kj=typical_completed_output,
        reset_cue_work_output_kj=reset_cue,
        work_output_reset_ratio_hint=reset_ratio_hint,
        stable_baseline_activity_count=replay_count,
    )
    baseline_sha = aggregate_sha256(
        [
            [replay.sha256 for replay in replay_models],
            {
                "artifact": "walking_hiking_baseline",
                "source_path": source_path,
                "reset_ratio_hint": reset_ratio_hint,
                "sustainable_pace_mps": sustainable_pace,
                "sustainable_cadence_spm": sustainable_cadence,
                "typical_completed_output_kj": typical_completed_output,
                "window_count": window_count,
            },
        ]
    )
    return WalkingHikingBaseline(
        source_path=source_path,
        sha256=baseline_sha,
        activity_types=sorted({replay.activity_type for replay in replay_models}),
        replay_count=replay_count,
        window_count=window_count,
        sustainable_pace_mps=sustainable_pace,
        sustainable_cadence_spm=sustainable_cadence,
        typical_active_energy_kj_per_hour=round(float(median(replay_energy_per_hour)), 3)
        if replay_energy_per_hour
        else None,
        typical_completed_output_kj=typical_completed_output,
        reset_cue_kj=reset_cue,
        reset_ratio_hint=reset_ratio_hint,
        rest_or_slowdown_frequency_per_hour=round(len(slowdown_windows) / total_hours, 3)
        if total_hours
        else 0.0,
        median_rest_ratio_per_window=round(float(median(all_rest_ratios)), 3) if all_rest_ratios else 0.0,
        median_rest_cost_minutes_next_60m=round(float(median(all_rest_costs)), 3) if all_rest_costs else 0.0,
        high_hr_low_efficiency_window_rate=round(high_hr_low_efficiency_count / window_count, 3)
        if window_count
        else 0.0,
        runtime_baseline_context=baseline_context,
        confidence=confidence,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=min(
                (replay.data_quality.heart_rate_confidence for replay in replay_models),
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            gps_confidence=min(
                (replay.data_quality.gps_confidence for replay in replay_models),
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            provider_value_confidence=min(
                (replay.data_quality.provider_value_confidence for replay in replay_models),
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            limitations=limitations,
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
        limitations=limitations,
    )


def build_route_segment_reference_context(
    *,
    segment_id: str,
    distance_m: float,
    source_provider: str = "reference_segment_timing",
    source_path: str = "inline:reference_segment_timing",
    ascent_m: float = 0.0,
    descent_m: float = 0.0,
    sample_count: int = 0,
    distance_filter_m: float | None = None,
    reference_min_minutes: float | None = None,
    reference_p50_minutes: float | None = None,
    reference_p75_minutes: float | None = None,
    reference_max_minutes: float | None = None,
    manual_guide_minutes: float | None = None,
    selected_time_source: RouteSegmentTimingSource = "p75",
) -> RouteSegmentReferenceContext:
    selected_minutes = _selected_route_segment_minutes(
        selected_time_source=selected_time_source,
        reference_min_minutes=reference_min_minutes,
        reference_p50_minutes=reference_p50_minutes,
        reference_p75_minutes=reference_p75_minutes,
        reference_max_minutes=reference_max_minutes,
        manual_guide_minutes=manual_guide_minutes,
    )
    expected_pace = round(distance_m / (selected_minutes * 60.0), 4)
    route_effort_units = round((distance_m / 1000.0) + (ascent_m / 100.0) + (descent_m / 300.0), 3)
    limitations = [
        "reference segment timing is advisory route context, not route approval",
        "segment context stores aggregate timing statistics only; no raw GPX, timestamps, or coordinates",
        "P50/P75/manual guide times must be compared with terrain, weather, pack weight, and daylight elsewhere",
    ]
    if sample_count < 3 and manual_guide_minutes is None:
        limitations.append("low sample count keeps timing confidence low")
    segment_sha = aggregate_sha256(
        [
            {
                "artifact": "route_segment_reference_context",
                "source_provider": source_provider,
                "source_path": source_path,
                "segment_id": segment_id,
                "distance_m": round(distance_m, 3),
                "ascent_m": round(ascent_m, 3),
                "descent_m": round(descent_m, 3),
                "sample_count": sample_count,
                "distance_filter_m": distance_filter_m,
                "reference_min_minutes": reference_min_minutes,
                "reference_p50_minutes": reference_p50_minutes,
                "reference_p75_minutes": reference_p75_minutes,
                "reference_max_minutes": reference_max_minutes,
                "manual_guide_minutes": manual_guide_minutes,
                "selected_time_source": selected_time_source,
            }
        ]
    )
    provider_confidence = "medium" if sample_count >= 3 or manual_guide_minutes is not None else "low"
    return RouteSegmentReferenceContext(
        source_provider=source_provider,
        source_path=source_path,
        sha256=segment_sha,
        segment_id=segment_id,
        distance_m=round(distance_m, 3),
        ascent_m=round(ascent_m, 3),
        descent_m=round(descent_m, 3),
        sample_count=sample_count,
        distance_filter_m=distance_filter_m,
        reference_min_minutes=reference_min_minutes,
        reference_p50_minutes=reference_p50_minutes,
        reference_p75_minutes=reference_p75_minutes,
        reference_max_minutes=reference_max_minutes,
        manual_guide_minutes=manual_guide_minutes,
        selected_time_source=selected_time_source,
        selected_reference_minutes=round(selected_minutes, 3),
        route_expected_pace_mps=expected_pace,
        route_effort_units=route_effort_units,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="low",
            gps_confidence=provider_confidence,
            provider_value_confidence=provider_confidence,
            limitations=limitations,
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
        limitations=limitations,
    )


def apply_route_segment_context_to_windowed_replay(
    replay: PhysiologicWindowedActivityReplay | dict[str, Any],
    segment_context: RouteSegmentReferenceContext | dict[str, Any],
    *,
    route_efficiency_stop_ratio: float = WORKSPACE_THRESHOLD_POLICY.movement_efficiency_stop_ratio,
) -> RouteSegmentContextualizedReplay:
    replay_model = (
        replay
        if isinstance(replay, PhysiologicWindowedActivityReplay)
        else PhysiologicWindowedActivityReplay.model_validate(replay)
    )
    segment = (
        segment_context
        if isinstance(segment_context, RouteSegmentReferenceContext)
        else RouteSegmentReferenceContext.model_validate(segment_context)
    )
    windows: list[RouteSegmentWindowContext] = []
    for window in replay_model.windows:
        route_ratio = (
            round(window.pace_mps / segment.route_expected_pace_mps, 3)
            if window.pace_mps is not None and segment.route_expected_pace_mps
            else None
        )
        reason_codes = [f"route_expected_pace_source:{segment.selected_time_source}"]
        if route_ratio is not None and route_ratio <= route_efficiency_stop_ratio:
            reason_codes.append("route_context_low_movement_efficiency")
        if window.heart_rate_pressure:
            reason_codes.append("heart_rate_pressure")
        if window.high_hr_low_efficiency_window:
            reason_codes.append("session_high_hr_low_efficiency_window")
        if window.rest_cost.stage in {"rest_cost", "recovery_debt_candidate"}:
            reason_codes.append(f"rest_cost_stage:{window.rest_cost.stage}")
        route_pressure_window = (
            window.heart_rate_pressure
            and route_ratio is not None
            and route_ratio <= route_efficiency_stop_ratio
            and window.duration_min >= replay_model.window_minutes * 0.8
        )
        windows.append(
            RouteSegmentWindowContext(
                window_index=window.window_index,
                elapsed_start_min=window.elapsed_start_min,
                elapsed_end_min=window.elapsed_end_min,
                segment_id=segment.segment_id,
                route_expected_pace_mps=segment.route_expected_pace_mps,
                movement_efficiency_ratio_to_session_reference=(
                    window.movement_efficiency_ratio_to_session_reference
                ),
                movement_efficiency_ratio_to_route_context=route_ratio,
                heart_rate_pressure=window.heart_rate_pressure,
                high_hr_low_efficiency_window=window.high_hr_low_efficiency_window,
                route_pressure_window=route_pressure_window,
                reason_codes=reason_codes,
            )
        )
    pressure_count = sum(1 for window in windows if window.route_pressure_window)
    result_sha = aggregate_sha256(
        [
            replay_model.sha256,
            segment.sha256,
            {
                "artifact": "route_segment_contextualized_replay",
                "segment_id": segment.segment_id,
                "route_efficiency_stop_ratio": route_efficiency_stop_ratio,
                "route_pressure_window_indexes": [
                    window.window_index for window in windows if window.route_pressure_window
                ],
            },
        ]
    )
    limitations = [
        "route contextualization uses aggregate segment timing, not raw GPX geometry",
        "route-relative movement efficiency is advisory pace evidence, not a medical or safety-truth decision",
        "contextualized replay can feed pace/delay review but does not call safety APIs or send alerts",
    ]
    return RouteSegmentContextualizedReplay(
        source_path=f"{replay_model.source_path}#route-segment-context:{segment.segment_id}",
        sha256=result_sha,
        source_replay_sha256=replay_model.sha256,
        source_segment_sha256=segment.sha256,
        segment_context=segment,
        window_count=len(windows),
        route_pressure_window_count=pressure_count,
        selected_time_source=segment.selected_time_source,
        selected_reference_minutes=segment.selected_reference_minutes,
        route_expected_pace_mps=segment.route_expected_pace_mps,
        windows=windows,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=replay_model.data_quality.heart_rate_confidence,
            gps_confidence=min(
                replay_model.data_quality.gps_confidence,
                segment.data_quality.gps_confidence,
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            provider_value_confidence=segment.data_quality.provider_value_confidence,
            limitations=sorted({*limitations, *segment.data_quality.limitations}),
        ),
        privacy=replay_model.privacy,
        boundary=ScoutEnergyBoundary(),
        limitations=limitations,
    )


def build_feature_baseline(
    sessions: list[PhysiologicSessionSummary],
    *,
    reset_ratio_hint: float = 1.25,
) -> PhysiologicFeatureBaseline:
    vo2_values = [s.vo2max_estimate_ml_kg_min for s in sessions if s.vo2max_estimate_ml_kg_min is not None]
    recovery_values = [
        s.heart_rate_recovery.recovery_drop_bpm
        for s in sessions
        if s.heart_rate_recovery.recovery_drop_bpm is not None
    ]
    output_values = [_session_energy_output_kj(s) for s in sessions if _session_energy_output_kj(s) is not None]
    typical_output = round(float(median(output_values)), 3) if output_values else None
    reset_cue = round(typical_output * reset_ratio_hint, 3) if typical_output is not None else None
    limitations = [
        "physiologic feature baseline is personal and advisory only",
        "VO2max provider values are baseline context, not live oxygen uptake",
        "work-output reset cue is not maximum capability",
    ]
    if not vo2_values:
        limitations.append("VO2max baseline unavailable")
    if not recovery_values:
        limitations.append("heart-rate recovery baseline unavailable")
    if not output_values:
        limitations.append("work-output reset baseline unavailable")
    return PhysiologicFeatureBaseline(
        session_count=len(sessions),
        baseline_vo2max_ml_kg_min=round(float(median(vo2_values)), 3) if vo2_values else None,
        baseline_recovery_drop_bpm=round(float(median(recovery_values)), 3) if recovery_values else None,
        typical_completed_output_kj=typical_output,
        reset_cue_kj=reset_cue,
        reset_ratio_hint=reset_ratio_hint,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if any(s.avg_heart_rate_bpm for s in sessions) else "low",
            gps_confidence="low",
            provider_value_confidence="medium" if vo2_values else "low",
            limitations=limitations,
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def smooth_physio_gate_states(
    gate_outputs: list[PhysiologicGateOutput],
    *,
    source_path: str = "inline:physiologic_gate_outputs",
    debounce_frames_for_stop: int = 2,
) -> PhysiologicStateSmoothingResult:
    frames: list[PhysiologicStateSmoothingFrame] = []
    previous_smoothed: PhysiologicGateState = "normal"
    stop_like_streak = 0
    for index, output in enumerate(gate_outputs, start=1):
        raw_state = output.state
        if _state_rank(raw_state) >= _state_rank("stop_and_rest"):
            stop_like_streak += 1
        else:
            stop_like_streak = 0
        route_pressure = output.route_pressure_effect.route_pressure_review_required or output.exertion_overdraft.danger_flag
        if raw_state == "alert_candidate":
            smoothed_state = "alert_candidate"
            reason = "explicit alert candidate passes through"
        elif raw_state == "retreat_suggested" and route_pressure:
            smoothed_state = "retreat_suggested"
            reason = "retreat with route pressure passes through"
        elif _state_rank(raw_state) >= _state_rank("stop_and_rest") and stop_like_streak < debounce_frames_for_stop:
            smoothed_state = "watch" if _state_rank(previous_smoothed) < _state_rank("stop_and_rest") else previous_smoothed
            reason = "stop/rest requires debounce confirmation"
        elif _state_rank(raw_state) < _state_rank(previous_smoothed) and previous_smoothed in {"stop_and_rest", "retreat_suggested"}:
            smoothed_state = "watch"
            reason = "downgrade is gradual after a higher-pressure state"
        else:
            smoothed_state = raw_state
            reason = "raw state accepted"
        frames.append(
            PhysiologicStateSmoothingFrame(
                frame_index=index,
                raw_state=raw_state,
                smoothed_state=smoothed_state,
                raw_required_action=output.required_action,
                smoothed_required_action=_required_action_for_state(smoothed_state),
                hold_reason=reason,
            )
        )
        previous_smoothed = smoothed_state
    result_sha = aggregate_sha256(
        [
            {
                "artifact": "physiologic_state_smoothing",
                "source_path": source_path,
                "frames": [frame.model_dump(mode="json") for frame in frames],
            }
        ]
    )
    return PhysiologicStateSmoothingResult(
        source_provider="scout_runtime_physiologic_gate",
        source_path=source_path,
        sha256=result_sha,
        frame_count=len(frames),
        frames=frames,
        debounce_frames_for_stop=debounce_frames_for_stop,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium",
            gps_confidence="low",
            provider_value_confidence="low",
            limitations=[
                "state smoothing is deterministic hysteresis for UI/review stability",
                "smoothing does not mutate Phase 1 safety truth",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def build_route_pressure_handoff(gate_output: PhysiologicGateOutput) -> PhysiologicRoutePressureHandoff:
    handoff_gates = list(gate_output.exertion_overdraft.handoff_gates)
    if gate_output.route_pressure_effect.route_pressure_review_required and "delay_gate" not in handoff_gates:
        handoff_gates.append("delay_gate")
    handoff_sha = aggregate_sha256(
        [
            gate_output.sha256,
            {
                "artifact": "physiologic_route_pressure_handoff",
                "state": gate_output.state,
                "eta_delay_minutes": gate_output.eta_delay_minutes,
                "handoff_gates": handoff_gates,
            },
        ]
    )
    return PhysiologicRoutePressureHandoff(
        source_provider=gate_output.source_provider,
        source_path=gate_output.source_path,
        sha256=handoff_sha,
        physiologic_state=gate_output.state,
        required_action=gate_output.required_action,
        eta_delay_minutes=gate_output.eta_delay_minutes,
        daylight_buffer_after_delay_minutes=(
            gate_output.route_pressure_effect.daylight_buffer_after_delay_minutes
        ),
        route_pressure_review_required=gate_output.route_pressure_effect.route_pressure_review_required,
        handoff_gates=handoff_gates,
        exertion_overdraft_stage=gate_output.exertion_overdraft.stage,
        danger_flag=gate_output.exertion_overdraft.danger_flag,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=gate_output.data_quality.heart_rate_confidence,
            gps_confidence=gate_output.data_quality.gps_confidence,
            provider_value_confidence=gate_output.data_quality.provider_value_confidence,
            limitations=gate_output.data_quality.limitations,
        ),
        privacy=gate_output.privacy,
        boundary=ScoutEnergyBoundary(),
    )


def compose_route_pressure_decision(
    gate_outputs: list[PhysiologicGateOutput | dict[str, Any]],
    *,
    companion_pressure_evidence: CompanionPacePressureEvidence | dict[str, Any] | None = None,
    pace_gate_failed: bool = False,
    delay_gate_failed: bool = False,
    source_path: str = "inline:route_pressure_composer",
) -> RoutePressureComposerResult:
    if not gate_outputs:
        raise ValueError("route pressure composer requires at least one physiologic gate output")
    outputs = [
        output if isinstance(output, PhysiologicGateOutput) else PhysiologicGateOutput.model_validate(output)
        for output in gate_outputs
    ]
    companion_pressure = (
        companion_pressure_evidence
        if isinstance(companion_pressure_evidence, CompanionPacePressureEvidence)
        else CompanionPacePressureEvidence.model_validate(companion_pressure_evidence)
        if companion_pressure_evidence is not None
        else None
    )
    physiologic_state = max((output.state for output in outputs), key=_state_rank)
    physiologic_eta_delay = max(output.eta_delay_minutes for output in outputs)
    companion_detected = bool(companion_pressure and companion_pressure.pressure_detected)
    rest_cost_delay = companion_pressure.estimated_rest_cost_minutes if companion_pressure else 0.0
    handoff_gates = _dedupe_strings(
        [
            gate
            for output in outputs
            for gate in output.exertion_overdraft.handoff_gates
        ]
    )
    if companion_detected:
        for gate in ("companion_match_gate", "pace_gate", "delay_gate"):
            if gate not in handoff_gates:
                handoff_gates.append(gate)
    if pace_gate_failed and "pace_gate" not in handoff_gates:
        handoff_gates.append("pace_gate")
    if delay_gate_failed and "delay_gate" not in handoff_gates:
        handoff_gates.append("delay_gate")

    route_pressure_required = any(output.route_pressure_effect.route_pressure_review_required for output in outputs)
    route_pressure_required = route_pressure_required or companion_detected or pace_gate_failed or delay_gate_failed
    retreat_required = physiologic_state in {"retreat_suggested", "alert_candidate"} or (
        route_pressure_required and (pace_gate_failed or delay_gate_failed) and companion_detected
    )
    alert_required = physiologic_state == "alert_candidate"
    rest_now = any(output.rest_directive.recommended for output in outputs)
    team_pace_reset = companion_detected and rest_now
    action = _composer_action(
        physiologic_state=physiologic_state,
        alert_required=alert_required,
        retreat_required=retreat_required,
        route_pressure_required=route_pressure_required,
        team_pace_reset=team_pace_reset,
        rest_now=rest_now,
    )
    eta_delay = physiologic_eta_delay + math.ceil(rest_cost_delay)
    reasons = _dedupe_strings(
        [
            *_composer_reasons(
                physiologic_state=physiologic_state,
                companion_pressure=companion_pressure,
                pace_gate_failed=pace_gate_failed,
                delay_gate_failed=delay_gate_failed,
                route_pressure_required=route_pressure_required,
                rest_now=rest_now,
            ),
            *[
                reason
                for output in outputs
                for reason in output.dominant_reasons[:3]
            ],
        ]
    )
    result_sha = aggregate_sha256(
        [
            [output.sha256 for output in outputs],
            companion_pressure.sha256 if companion_pressure else None,
            {
                "artifact": "route_pressure_composer_result",
                "physiologic_state": physiologic_state,
                "required_action": action,
                "pace_gate_failed": pace_gate_failed,
                "delay_gate_failed": delay_gate_failed,
                "handoff_gates": handoff_gates,
                "eta_delay_minutes": eta_delay,
            },
        ]
    )
    return RoutePressureComposerResult(
        source_path=source_path,
        sha256=result_sha,
        physiologic_state=physiologic_state,
        required_action=action,
        rest_now=rest_now,
        team_pace_reset_recommended=team_pace_reset,
        route_pressure_review_required=route_pressure_required,
        retreat_review_required=retreat_required,
        alert_review_required=alert_required,
        eta_delay_minutes=eta_delay,
        physiologic_eta_delay_minutes=physiologic_eta_delay,
        rest_cost_delay_minutes=round(rest_cost_delay, 3),
        companion_pressure_detected=companion_detected,
        pace_gate_failed=pace_gate_failed,
        delay_gate_failed=delay_gate_failed,
        handoff_gates=handoff_gates,
        dominant_reasons=reasons,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=min(
                (output.data_quality.heart_rate_confidence for output in outputs),
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            gps_confidence=min(
                (output.data_quality.gps_confidence for output in outputs),
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            provider_value_confidence=min(
                (
                    output.data_quality.provider_value_confidence
                    for output in outputs
                ),
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            limitations=[
                "route pressure composer is advisory evidence only",
                "composer does not decide final safety truth, call safety APIs, or send alerts",
                "pace/delay gate booleans are explicit inputs; missing gates are not interpreted as safe",
            ],
        ),
        privacy=outputs[0].privacy,
        boundary=ScoutEnergyBoundary(),
    )


def build_admin_debug_projection(
    feature_set: PhysiologicFeatureSet,
    *,
    smoothing: PhysiologicStateSmoothingResult | None = None,
    handoffs: list[PhysiologicRoutePressureHandoff] | None = None,
) -> PhysiologicAdminDebugProjection:
    handoffs = handoffs or []
    burden_165 = [
        session.high_heart_rate_burden.total_minutes_at_or_above.get("165")
        for session in feature_set.sessions
        if session.high_heart_rate_burden.total_minutes_at_or_above.get("165") is not None
    ]
    cards = [
        {
            "id": "session_count",
            "label": "sessions",
            "value": feature_set.session_count,
        },
        {
            "id": "vo2max_baseline",
            "label": "VO2max baseline",
            "value": feature_set.baseline.baseline_vo2max_ml_kg_min,
            "unit": "ml/kg/min",
        },
        {
            "id": "hr165_burden_p50",
            "label": "HR >=165 p50",
            "value": round(float(median(burden_165)), 2) if burden_165 else None,
            "unit": "min",
        },
        {
            "id": "reset_cue",
            "label": "reset cue",
            "value": feature_set.baseline.reset_cue_kj,
            "unit": "kJ",
        },
    ]
    smoothed_by_index = {
        frame.frame_index: frame.model_dump(mode="json")
        for frame in (smoothing.frames if smoothing else [])
    }
    timeline_items = []
    for session in feature_set.sessions:
        timeline_items.append(
            {
                "item_id": f"physio-session-{session.session_index:03d}",
                "session_index": session.session_index,
                "activity_type": session.activity_type,
                "start_hr_5m_bpm": session.start_heart_rate_avg_5m_bpm,
                "hr_ge_165_min": session.high_heart_rate_burden.total_minutes_at_or_above.get("165"),
                "vo2max_estimate_ml_kg_min": session.vo2max_estimate_ml_kg_min,
                "oxygen_uptake_ratio_to_personal_baseline": (
                    session.oxygen_uptake.oxygen_uptake_ratio_to_personal_baseline
                ),
                "recovery_classification": session.heart_rate_recovery.classification,
                "work_reset_stage": session.work_output.reset_stage,
                "smoothed_state": smoothed_by_index.get(session.session_index, {}).get("smoothed_state"),
            }
        )
    projection_sha = aggregate_sha256(
        [
            feature_set.sha256,
            smoothing.sha256 if smoothing else None,
            [handoff.sha256 for handoff in handoffs],
            {
                "artifact": "physiologic_admin_debug_projection",
                "cards": cards,
                "timeline_count": len(timeline_items),
            },
        ]
    )
    return PhysiologicAdminDebugProjection(
        source_provider=feature_set.source_provider,
        source_path=feature_set.source_path,
        sha256=projection_sha,
        cards=cards,
        timeline_items=timeline_items,
        state_semantics={
            "high_heart_rate_alone_max_state": "watch",
            "vo2max_is_live_oxygen_uptake": False,
            "oxygen_saturation_compared_to_vo2max": False,
            "provider_values_are_scout_truth": False,
            "phase1_runtime_safety_truth": False,
        },
        data_quality=feature_set.data_quality,
        privacy=feature_set.privacy,
        boundary=feature_set.boundary,
    )


def build_health_auto_export_physio_analysis(
    source_path: Path,
    *,
    activity_type: ActivityKind = "walking",
    window_minutes: int = WORKSPACE_THRESHOLD_POLICY.observation_window_minutes,
    provider_metric_names: set[str] | None = None,
) -> HealthAutoExportPhysioAnalysis:
    if activity_type not in {"walking", "hiking"}:
        raise ValueError("Health Auto Export physio analysis currently accepts walking or hiking activities")
    payload, source_provider = _load_health_auto_export_payload(source_path)
    source_sha = sha256_file(source_path)
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict) or not isinstance(data.get("workouts"), list):
        raise ValueError("Health Auto Export physio analysis requires data.workouts")
    activity_count = sum(
        1
        for workout in data["workouts"]
        if isinstance(workout, dict) and _workout_type(workout) == activity_type
    )
    if activity_count <= 0:
        raise ValueError(f"Health Auto Export payload has no {activity_type} workouts")

    replays = [
        build_windowed_activity_replay_from_health_auto_export(
            source_path,
            activity_type=activity_type,
            session_index=session_index,
            window_minutes=window_minutes,
        )
        for session_index in range(1, activity_count + 1)
    ]
    baseline = build_walking_hiking_baseline_from_windowed_replays(
        replays,
        source_path=f"{source_path}#sanitized-windowed-{activity_type}-analysis",
    )
    sessions: list[HealthAutoExportPhysioAnalysisSession] = []
    all_gate_outputs: list[PhysiologicGateOutput] = []
    for replay in replays:
        gate_result = build_gate_inputs_from_windowed_activity_replay(
            replay,
            route_context=_analysis_route_context_for_replay(replay),
            baseline=baseline.runtime_baseline_context,
        )
        gate_outputs = [
            build_runtime_physiologic_gate(PhysiologicGateInput.model_validate(item))
            for item in gate_result["gate_inputs"]
        ]
        all_gate_outputs.extend(gate_outputs)
        sessions.append(_analysis_session_from_replay(replay, gate_outputs))

    metric_summaries = _provider_metric_summaries_from_payload(
        payload,
        metric_names=provider_metric_names,
    )
    overall = HealthAutoExportPhysioAnalysisOverall(
        total_duration_min=round(sum(session.duration_min for session in sessions), 3),
        total_distance_km=round(sum(session.distance_km for session in sessions), 3),
        total_active_energy_kj=round(
            sum(session.active_energy_kj or 0.0 for session in sessions),
            3,
        ),
        total_windows=sum(session.window_count for session in sessions),
        total_hr_pressure_windows=sum(session.hr_pressure_windows for session in sessions),
        total_high_hr_low_efficiency_windows=sum(
            session.high_hr_low_efficiency_windows for session in sessions
        ),
        total_recovery_debt_candidate_windows=sum(
            session.recovery_debt_candidate_windows for session in sessions
        ),
        max_gate_state=_max_gate_state(all_gate_outputs),
    )
    limitations = [
        "analysis emits sanitized aggregate session/window summaries only",
        "provider metric summaries are source values, not Scout truth",
        "VO2max is background cardio-fitness context and not live oxygen uptake",
        "raw HealthAutoExport payload, raw GPX, coordinates, and exact timestamps are not embedded",
        "analysis is advisory physiologic evidence and does not call safety APIs",
    ]
    analysis_sha = aggregate_sha256(
        [
            source_sha,
            baseline.sha256,
            {
                "artifact": "health_auto_export_physio_analysis",
                "activity_type": activity_type,
                "window_minutes": window_minutes,
                "sessions": [session.model_dump(mode="json") for session in sessions],
                "provider_metric_summaries": [
                    metric.model_dump(mode="json") for metric in metric_summaries
                ],
                "overall": overall.model_dump(mode="json"),
            },
        ]
    )
    return HealthAutoExportPhysioAnalysis(
        source_provider=source_provider,
        source_path=str(source_path),
        sha256=analysis_sha,
        activity_type=activity_type,
        session_count=len(sessions),
        analysis_window_minutes=window_minutes,
        baseline=baseline,
        sessions=sessions,
        provider_metric_summaries=metric_summaries,
        overall=overall,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=baseline.data_quality.heart_rate_confidence,
            gps_confidence=baseline.data_quality.gps_confidence,
            provider_value_confidence="medium" if metric_summaries else "low",
            limitations=limitations,
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
        limitations=limitations,
    )


def compare_health_auto_export_physio_analyses(
    previous: HealthAutoExportPhysioAnalysis | dict[str, Any],
    current: HealthAutoExportPhysioAnalysis | dict[str, Any],
    *,
    source_path: str = "inline:health_auto_export_physio_analysis_delta",
    material_pace_delta_pct: float = 15.0,
    material_reset_cue_delta_pct: float = 20.0,
) -> HealthAutoExportPhysioAnalysisDelta:
    previous_model = (
        previous
        if isinstance(previous, HealthAutoExportPhysioAnalysis)
        else HealthAutoExportPhysioAnalysis.model_validate(previous)
    )
    current_model = (
        current
        if isinstance(current, HealthAutoExportPhysioAnalysis)
        else HealthAutoExportPhysioAnalysis.model_validate(current)
    )
    if previous_model.activity_type != current_model.activity_type:
        raise ValueError("physio analysis delta requires matching activity_type")

    previous_rank = _state_rank(previous_model.overall.max_gate_state)
    current_rank = _state_rank(current_model.overall.max_gate_state)
    rank_delta = current_rank - previous_rank
    if rank_delta < 0:
        state_direction: Literal["improved", "worse", "unchanged"] = "improved"
    elif rank_delta > 0:
        state_direction = "worse"
    else:
        state_direction = "unchanged"

    high_hr_low_efficiency_delta = (
        current_model.overall.total_high_hr_low_efficiency_windows
        - previous_model.overall.total_high_hr_low_efficiency_windows
    )
    recovery_debt_delta = (
        current_model.overall.total_recovery_debt_candidate_windows
        - previous_model.overall.total_recovery_debt_candidate_windows
    )
    hr_pressure_delta = (
        current_model.overall.total_hr_pressure_windows
        - previous_model.overall.total_hr_pressure_windows
    )
    pace_delta = _optional_delta(
        current_model.baseline.sustainable_pace_mps,
        previous_model.baseline.sustainable_pace_mps,
    )
    pace_delta_pct = _optional_delta_pct(
        current_model.baseline.sustainable_pace_mps,
        previous_model.baseline.sustainable_pace_mps,
    )
    reset_delta = _optional_delta(
        current_model.baseline.reset_cue_kj,
        previous_model.baseline.reset_cue_kj,
    )
    reset_delta_pct = _optional_delta_pct(
        current_model.baseline.reset_cue_kj,
        previous_model.baseline.reset_cue_kj,
    )

    metric_deltas = _provider_metric_deltas(
        previous_model.provider_metric_summaries,
        current_model.provider_metric_summaries,
    )
    candidate_reasons = _candidate_change_reasons(
        rank_delta=rank_delta,
        high_hr_low_efficiency_delta=high_hr_low_efficiency_delta,
        recovery_debt_delta=recovery_debt_delta,
        hr_pressure_delta=hr_pressure_delta,
        pace_delta_pct=pace_delta_pct,
        reset_delta_pct=reset_delta_pct,
        material_pace_delta_pct=material_pace_delta_pct,
        material_reset_cue_delta_pct=material_reset_cue_delta_pct,
    )
    no_change_reasons: list[str] = []
    if not candidate_reasons:
        no_change_reasons = [
            "no material gate-state rank change",
            "no material high-HR/low-efficiency or recovery-debt change",
            "no material walking/hiking pace or reset-cue delta",
        ]

    limitations = [
        "analysis delta is advisory trend evidence, not route approval",
        "candidate change means review-worthy physiologic trend difference, not capability truth",
        "provider metric deltas remain source values and are not medical interpretation",
        "comparison does not read raw payloads, raw GPX, coordinates, or exact timestamps",
        "comparison does not call safety APIs or mutate Phase 1 safety truth",
    ]
    delta_sha = aggregate_sha256(
        [
            previous_model.sha256,
            current_model.sha256,
            {
                "artifact": "health_auto_export_physio_analysis_delta",
                "source_path": source_path,
                "rank_delta": rank_delta,
                "high_hr_low_efficiency_delta": high_hr_low_efficiency_delta,
                "recovery_debt_delta": recovery_debt_delta,
                "hr_pressure_delta": hr_pressure_delta,
                "pace_delta_pct": pace_delta_pct,
                "reset_delta_pct": reset_delta_pct,
                "candidate_reasons": candidate_reasons,
            },
        ]
    )
    return HealthAutoExportPhysioAnalysisDelta(
        source_path=source_path,
        sha256=delta_sha,
        previous_analysis_sha256=previous_model.sha256,
        current_analysis_sha256=current_model.sha256,
        activity_type=current_model.activity_type,
        previous_max_gate_state=previous_model.overall.max_gate_state,
        current_max_gate_state=current_model.overall.max_gate_state,
        gate_state_rank_delta=rank_delta,
        state_direction=state_direction,
        review_candidate_change=bool(candidate_reasons),
        candidate_change_reasons=candidate_reasons,
        no_candidate_change_reasons=no_change_reasons,
        total_high_hr_low_efficiency_window_delta=high_hr_low_efficiency_delta,
        total_recovery_debt_candidate_window_delta=recovery_debt_delta,
        total_hr_pressure_window_delta=hr_pressure_delta,
        sustainable_pace_delta_mps=pace_delta,
        sustainable_pace_delta_pct=pace_delta_pct,
        reset_cue_delta_kj=reset_delta,
        reset_cue_delta_pct=reset_delta_pct,
        provider_metric_deltas=metric_deltas,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=min(
                previous_model.data_quality.heart_rate_confidence,
                current_model.data_quality.heart_rate_confidence,
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            gps_confidence=min(
                previous_model.data_quality.gps_confidence,
                current_model.data_quality.gps_confidence,
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            provider_value_confidence=min(
                previous_model.data_quality.provider_value_confidence,
                current_model.data_quality.provider_value_confidence,
                key={"low": 0, "medium": 1, "high": 2}.get,
            ),
            limitations=limitations,
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
        limitations=limitations,
    )


def build_physio_review_capsule(
    current_analysis: HealthAutoExportPhysioAnalysis | dict[str, Any],
    *,
    delta: HealthAutoExportPhysioAnalysisDelta | dict[str, Any] | None = None,
    source_path: str = "inline:physio_review_capsule",
) -> PhysioReviewCapsule:
    current_model = (
        current_analysis
        if isinstance(current_analysis, HealthAutoExportPhysioAnalysis)
        else HealthAutoExportPhysioAnalysis.model_validate(current_analysis)
    )
    delta_model = (
        delta
        if isinstance(delta, HealthAutoExportPhysioAnalysisDelta)
        else HealthAutoExportPhysioAnalysisDelta.model_validate(delta)
        if delta is not None
        else None
    )
    if delta_model is not None and delta_model.current_analysis_sha256 != current_model.sha256:
        raise ValueError("physio review capsule delta must reference the current analysis")

    trend_direction: PhysioReviewTrendDirection = (
        delta_model.state_direction if delta_model is not None else "not_compared"
    )
    review_candidate_change = bool(delta_model and delta_model.review_candidate_change)
    review_priority = _physio_review_priority(
        current_model.overall.max_gate_state,
        review_candidate_change=review_candidate_change,
        trend_direction=trend_direction,
    )
    primary_reasons = _physio_review_reasons(current_model, delta_model)
    suggested_actions = _physio_review_actions(
        review_priority=review_priority,
        review_candidate_change=review_candidate_change,
    )
    limitations = [
        "physio review capsule is advisory review packaging, not route approval",
        "capsule state is baseline-relative trend evidence and not medical diagnosis",
        "candidate change is a review trigger, not capability truth",
        "capsule does not call safety APIs, mutate Phase 1 safety truth, or send alerts",
        "raw HealthAutoExport rows, raw GPX, coordinates, and exact timestamps are not embedded",
    ]
    capsule_sha = aggregate_sha256(
        [
            current_model.sha256,
            delta_model.sha256 if delta_model else None,
            {
                "artifact": "physio_review_capsule",
                "source_path": source_path,
                "current_max_gate_state": current_model.overall.max_gate_state,
                "trend_direction": trend_direction,
                "review_candidate_change": review_candidate_change,
                "review_priority": review_priority,
                "primary_reasons": primary_reasons,
            },
        ]
    )
    return PhysioReviewCapsule(
        source_path=source_path,
        sha256=capsule_sha,
        current_analysis_sha256=current_model.sha256,
        delta_sha256=delta_model.sha256 if delta_model else None,
        activity_type=current_model.activity_type,
        current_max_gate_state=current_model.overall.max_gate_state,
        trend_direction=trend_direction,
        review_candidate_change=review_candidate_change,
        review_priority=review_priority,
        primary_reasons=primary_reasons,
        suggested_review_actions=suggested_actions,
        total_windows=current_model.overall.total_windows,
        total_hr_pressure_windows=current_model.overall.total_hr_pressure_windows,
        total_high_hr_low_efficiency_windows=(
            current_model.overall.total_high_hr_low_efficiency_windows
        ),
        total_recovery_debt_candidate_windows=(
            current_model.overall.total_recovery_debt_candidate_windows
        ),
        sustainable_pace_mps=current_model.baseline.sustainable_pace_mps,
        reset_cue_kj=current_model.baseline.reset_cue_kj,
        baseline_confidence=current_model.baseline.confidence,
        provider_metric_names=[metric.metric_name for metric in current_model.provider_metric_summaries],
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=current_model.data_quality.heart_rate_confidence,
            gps_confidence=current_model.data_quality.gps_confidence,
            provider_value_confidence=current_model.data_quality.provider_value_confidence,
            limitations=limitations,
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
        limitations=limitations,
    )


def build_companion_pace_pressure_evidence_from_windowed_replay(
    replay: PhysiologicWindowedActivityReplay | dict[str, Any],
    *,
    companion_reference_pace_mps: float | None = None,
    companion_reference_cadence_spm: float | None = None,
    companion_reference_source: str = "manual_group_context",
    minimum_companion_pace_ratio: float = 1.15,
    require_recovery_debt: bool = True,
) -> CompanionPacePressureEvidence:
    replay_model = (
        replay
        if isinstance(replay, PhysiologicWindowedActivityReplay)
        else PhysiologicWindowedActivityReplay.model_validate(replay)
    )
    companion_ratio = _companion_pace_ratio_to_user_reference(
        companion_reference_pace_mps=companion_reference_pace_mps,
        companion_reference_cadence_spm=companion_reference_cadence_spm,
        user_reference_pace_mps=replay_model.session_reference_pace_mps,
        user_reference_cadence_spm=replay_model.session_reference_cadence_spm,
    )
    pressure_windows: list[CompanionPacePressureWindowEvidence] = []
    review_windows: list[CompanionPacePressureWindowEvidence] = []
    for window in replay_model.windows:
        reason_codes: list[str] = []
        if companion_ratio is not None and companion_ratio >= minimum_companion_pace_ratio:
            reason_codes.append("companion_reference_above_user_sustainable_context")
        if window.high_hr_low_efficiency_window:
            reason_codes.append("high_hr_low_efficiency_window")
        if window.rest_cost.stage in {"rest_cost", "recovery_debt_candidate"}:
            reason_codes.append(f"rest_cost_stage:{window.rest_cost.stage}")
        rest_debt_ok = (
            window.rest_cost.stage == "recovery_debt_candidate"
            if require_recovery_debt
            else window.rest_cost.stage in {"rest_cost", "recovery_debt_candidate"}
        )
        detected = (
            companion_ratio is not None
            and companion_ratio >= minimum_companion_pace_ratio
            and window.high_hr_low_efficiency_window
            and rest_debt_ok
        )
        evidence = CompanionPacePressureWindowEvidence(
            window_index=window.window_index,
            elapsed_start_min=window.elapsed_start_min,
            elapsed_end_min=window.elapsed_end_min,
            companion_pace_ratio_to_user_reference=companion_ratio,
            movement_efficiency_ratio_to_session_reference=(
                window.movement_efficiency_ratio_to_session_reference
            ),
            heart_rate_pressure=window.heart_rate_pressure,
            high_hr_low_efficiency_window=window.high_hr_low_efficiency_window,
            rest_cost_stage=window.rest_cost.stage,
            following_rest_cost_minutes_next_60m=window.rest_cost.following_rest_cost_minutes_next_60m,
            pressure_detected=detected,
            reason_codes=reason_codes,
        )
        if detected:
            pressure_windows.append(evidence)
        elif reason_codes:
            review_windows.append(evidence)
    detected_windows = pressure_windows
    pressure_detected = bool(detected_windows)
    estimated_rest_cost = round(
        sum(window.following_rest_cost_minutes_next_60m for window in detected_windows),
        3,
    )
    limitations = [
        "companion pace pressure is group-rhythm evidence, not a medical diagnosis or personal blame",
        "detector requires a companion or group reference pace/cadence and sanitized windowed replay",
        "pressure evidence contains relative window indexes only; no raw route, timestamps, or health samples",
    ]
    if companion_ratio is None:
        limitations.append("companion reference pace/cadence unavailable; pressure cannot be auto-detected")
    evidence_sha = aggregate_sha256(
        [
            replay_model.sha256,
            {
                "artifact": "companion_pace_pressure_evidence",
                "companion_reference_source": companion_reference_source,
                "companion_reference_pace_mps": companion_reference_pace_mps,
                "companion_reference_cadence_spm": companion_reference_cadence_spm,
                "minimum_companion_pace_ratio": minimum_companion_pace_ratio,
                "require_recovery_debt": require_recovery_debt,
                "detected_window_indexes": [window.window_index for window in detected_windows],
            },
        ]
    )
    return CompanionPacePressureEvidence(
        source_provider=replay_model.source_provider,
        source_path=f"{replay_model.source_path}#windowed-companion-pressure",
        sha256=evidence_sha,
        source_replay_sha256=replay_model.sha256,
        session_index=replay_model.session_index,
        companion_reference_source=companion_reference_source,
        companion_reference_pace_mps=companion_reference_pace_mps,
        companion_reference_cadence_spm=companion_reference_cadence_spm,
        user_reference_pace_mps=replay_model.session_reference_pace_mps,
        user_reference_cadence_spm=replay_model.session_reference_cadence_spm,
        companion_pace_ratio_to_user_reference=companion_ratio,
        pressure_detected=pressure_detected,
        pressure_window_count=len(detected_windows),
        estimated_rest_cost_minutes=estimated_rest_cost,
        pressure_windows=detected_windows or review_windows[:3],
        external_pressure_flags=["companion_pace_pressure"] if pressure_detected else [],
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=replay_model.data_quality.heart_rate_confidence,
            gps_confidence=replay_model.data_quality.gps_confidence,
            provider_value_confidence="medium" if companion_ratio is not None else "low",
            limitations=limitations,
        ),
        privacy=replay_model.privacy,
        boundary=replay_model.boundary,
        limitations=limitations,
    )


def build_gate_inputs_from_live_physio_fixture(
    source_path: Path,
    *,
    provider: LivePhysiologicFixtureProvider,
    route_context: PhysiologicRouteContext | dict[str, Any],
    baseline: PhysiologicBaselineContext | dict[str, Any],
) -> dict[str, Any]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    _assert_live_fixture_boundary(payload)
    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        raise ValueError(f"forbidden raw live physiologic fields present: {', '.join(forbidden_paths)}")
    frames = _live_frames(payload)
    route = route_context if isinstance(route_context, PhysiologicRouteContext) else PhysiologicRouteContext.model_validate(route_context)
    baseline_context = (
        baseline if isinstance(baseline, PhysiologicBaselineContext) else PhysiologicBaselineContext.model_validate(baseline)
    )
    source_sha = sha256_file(source_path)
    gate_inputs: list[PhysiologicGateInput] = []
    for index, frame in enumerate(frames, start=1):
        input_sha = aggregate_sha256(
            [
                source_sha,
                {
                    "provider": provider,
                    "index": index,
                    "offset_s": _int_from_value(_first_value(frame, "offset_s", "offsetSeconds")) or (index - 1) * 60,
                    "heart_rate_bpm": _int_from_value(_first_value(frame, "heart_rate_bpm", "bpm", "heartRate")),
                },
            ]
        )
        gate_inputs.append(
            PhysiologicGateInput(
                source_provider=provider,
                source_path=str(source_path),
                sha256=input_sha,
                observed_at_offset_s=_int_from_value(_first_value(frame, "offset_s", "offsetSeconds")) or (index - 1) * 60,
                route_context=route,
                signals=PhysiologicGateSignals(
                    heart_rate_bpm=_int_from_value(_first_value(frame, "heart_rate_bpm", "bpm", "heartRate")),
                    heart_rate_zone=_string_from_value(_first_value(frame, "heart_rate_zone", "heartRateZone")),
                    workout_effort_score=_number_from_value(_first_value(frame, "workout_effort_score", "effort")),
                    workout_effort_score_source=_string_from_value(
                        _first_value(frame, "workout_effort_score_source", "effortSource")
                    ),
                    vo2max_estimate_ml_kg_min=_number_from_value(_first_value(frame, "vo2max_estimate_ml_kg_min", "vo2max")),
                    estimated_oxygen_uptake_ml_kg_min=_number_from_value(
                        _first_value(frame, "estimated_oxygen_uptake_ml_kg_min", "estimatedOxygenUptake")
                    ),
                    oxygen_uptake_ratio_to_personal_baseline=_number_from_value(
                        _first_value(frame, "oxygen_uptake_ratio_to_personal_baseline", "oxygenUptakeRatio")
                    ),
                    oxygen_saturation_pct=_number_from_value(_first_value(frame, "oxygen_saturation_pct", "spo2")),
                    oxygen_saturation_source=_string_from_value(
                        _first_value(frame, "oxygen_saturation_source", "spo2Source")
                    ),
                    heart_rate_recovery_ratio_to_personal_baseline=_number_from_value(
                        _first_value(frame, "heart_rate_recovery_ratio_to_personal_baseline", "recoveryRatio")
                    ),
                    active_recovery_observed=_bool_from_value(_first_value(frame, "active_recovery_observed", "activeRecovery")),
                    breathing_recovery_quality=_string_from_value(
                        _first_value(frame, "breathing_recovery_quality", "breathingRecovery")
                    ),
                    cumulative_work_output_kj=_number_from_value(
                        _first_value(frame, "cumulative_work_output_kj", "workOutputKj")
                    ),
                    work_output_source=_string_from_value(_first_value(frame, "work_output_source", "workOutputSource")),
                    pace_mps=_number_from_value(_first_value(frame, "pace_mps", "speed_mps")),
                    movement_efficiency_ratio_to_personal_baseline=_number_from_value(
                        _first_value(
                            frame,
                            "movement_efficiency_ratio_to_personal_baseline",
                            "movementEfficiencyRatio",
                        )
                    ),
                    power_watts=_number_from_value(_first_value(frame, "power_watts", "power")),
                    cadence_spm=_number_from_value(_first_value(frame, "cadence_spm", "cadence")),
                    rest_ratio_recent_window=_number_from_value(_first_value(frame, "rest_ratio_recent_window", "restRatio")),
                    posture_or_gait_quality=_string_from_value(_first_value(frame, "posture_or_gait_quality", "gaitQuality")),
                    user_reported_discomfort=_string_from_value(
                        _first_value(frame, "user_reported_discomfort", "discomfort")
                    ),
                ),
                baseline=baseline_context,
                data_quality=ScoutEnergyDataQuality(
                    heart_rate_confidence="medium",
                    gps_confidence="low",
                    provider_value_confidence="low",
                    limitations=[
                        "live physiologic fixture normalized locally",
                        "no live network, provider API, runtime ingest, or safety API call",
                    ],
                ),
                privacy=ScoutEnergyPrivacy(),
            )
        )
    return {
        "artifact_kind": "scout_runtime_physiologic_live_adapter_result",
        "artifact_version": "runtime_physiologic_live_adapter_result.v1",
        "source_provider": provider,
        "source_path": str(source_path),
        "sha256": aggregate_sha256([source_sha, {"gate_input_count": len(gate_inputs), "provider": provider}]),
        "gate_input_count": len(gate_inputs),
        "gate_inputs": [item.model_dump(mode="json") for item in gate_inputs],
        "data_quality": ScoutEnergyDataQuality(
            heart_rate_confidence="medium",
            gps_confidence="low",
            provider_value_confidence="low",
            limitations=["local fixture adapter only; no real Apple/Garmin API calls"],
        ).model_dump(mode="json"),
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "boundary": ScoutEnergyBoundary().model_dump(mode="json"),
        "mutation": {
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def build_gate_inputs_from_windowed_activity_replay(
    replay: PhysiologicWindowedActivityReplay | dict[str, Any],
    *,
    route_context: PhysiologicRouteContext | dict[str, Any],
    baseline: PhysiologicBaselineContext | dict[str, Any],
    companion_pressure_evidence: CompanionPacePressureEvidence | dict[str, Any] | None = None,
    route_segment_contextualization: RouteSegmentContextualizedReplay | dict[str, Any] | None = None,
) -> dict[str, Any]:
    replay_model = (
        replay
        if isinstance(replay, PhysiologicWindowedActivityReplay)
        else PhysiologicWindowedActivityReplay.model_validate(replay)
    )
    route = route_context if isinstance(route_context, PhysiologicRouteContext) else PhysiologicRouteContext.model_validate(route_context)
    baseline_context = (
        baseline if isinstance(baseline, PhysiologicBaselineContext) else PhysiologicBaselineContext.model_validate(baseline)
    )
    companion_pressure = (
        companion_pressure_evidence
        if isinstance(companion_pressure_evidence, CompanionPacePressureEvidence)
        else CompanionPacePressureEvidence.model_validate(companion_pressure_evidence)
        if companion_pressure_evidence is not None
        else None
    )
    route_contextualization = (
        route_segment_contextualization
        if isinstance(route_segment_contextualization, RouteSegmentContextualizedReplay)
        else RouteSegmentContextualizedReplay.model_validate(route_segment_contextualization)
        if route_segment_contextualization is not None
        else None
    )
    if route_contextualization is not None and route_contextualization.source_replay_sha256 != replay_model.sha256:
        raise ValueError("route segment contextualization must be built from the same windowed replay")
    companion_pressure_window_indexes = {
        window.window_index
        for window in (companion_pressure.pressure_windows if companion_pressure else [])
        if window.pressure_detected
    }
    route_context_windows = {
        window.window_index: window
        for window in (route_contextualization.windows if route_contextualization else [])
    }
    route_pressure_window_indexes = {
        window.window_index
        for window in route_context_windows.values()
        if window.route_pressure_window
    }
    gate_inputs: list[PhysiologicGateInput] = []
    cumulative_energy_kj = 0.0
    for window in replay_model.windows:
        if window.active_energy_kj is not None:
            cumulative_energy_kj += window.active_energy_kj
        heart_rate = window.p90_heart_rate_bpm or window.avg_heart_rate_bpm
        route_window = route_context_windows.get(window.window_index)
        movement_efficiency = _minimum_present_float(
            [
                window.movement_efficiency_ratio_to_session_reference,
                route_window.movement_efficiency_ratio_to_route_context if route_window else None,
            ]
        )
        pressure_flags = []
        if window.window_index in companion_pressure_window_indexes:
            pressure_flags.append("companion_pace_pressure")
        if window.window_index in route_pressure_window_indexes:
            pressure_flags.append("pace_gate_failed")
        input_sha = aggregate_sha256(
            [
                replay_model.sha256,
                route_contextualization.sha256 if route_contextualization else None,
                {
                    "window_index": window.window_index,
                    "elapsed_end_min": window.elapsed_end_min,
                    "heart_rate": heart_rate,
                    "movement_efficiency": movement_efficiency,
                    "pressure_flags": pressure_flags,
                },
            ]
        )
        gate_inputs.append(
            PhysiologicGateInput(
                source_provider=replay_model.source_provider,
                source_path=f"{replay_model.source_path}#windowed-activity-replay",
                sha256=input_sha,
                observed_at_offset_s=window.elapsed_end_min * 60,
                route_context=_route_context_with_external_pressure(
                    route,
                    pressure_flags=pressure_flags,
                ),
                signals=PhysiologicGateSignals(
                    heart_rate_bpm=round(heart_rate) if heart_rate is not None else None,
                    heart_rate_zone=_heart_rate_zone_from_bpm(heart_rate),
                    movement_efficiency_ratio_to_personal_baseline=movement_efficiency,
                    pace_mps=window.pace_mps,
                    cadence_spm=window.cadence_spm,
                    cumulative_work_output_kj=round(cumulative_energy_kj, 3) if cumulative_energy_kj else None,
                    work_output_source="provider_active_energy_kj" if cumulative_energy_kj else None,
                    rest_ratio_recent_window=window.rest_cost.rest_ratio_recent_window,
                ),
                baseline=baseline_context,
                observation_window=PhysiologicObservationWindowContext(
                    window_minutes=replay_model.window_minutes,
                    elapsed_minutes=round(window.duration_min),
                ),
                data_quality=ScoutEnergyDataQuality(
                    heart_rate_confidence=replay_model.data_quality.heart_rate_confidence,
                    gps_confidence=replay_model.data_quality.gps_confidence,
                    provider_value_confidence=replay_model.data_quality.provider_value_confidence,
                    limitations=[
                        *replay_model.data_quality.limitations,
                        "gate input projected from sanitized windowed replay",
                        *(
                            ["route segment contextualization applied from aggregate reference timing"]
                            if route_contextualization is not None
                            else []
                        ),
                    ],
                ),
                privacy=replay_model.privacy,
            )
        )
    return {
        "artifact_kind": "scout_runtime_physiologic_windowed_gate_input_result",
        "artifact_version": "runtime_physiologic_windowed_gate_input_result.v1",
        "source_provider": replay_model.source_provider,
        "source_path": replay_model.source_path,
        "sha256": aggregate_sha256(
            [
                replay_model.sha256,
                companion_pressure.sha256 if companion_pressure else None,
                route_contextualization.sha256 if route_contextualization else None,
                {"gate_input_count": len(gate_inputs)},
            ]
        ),
        "gate_input_count": len(gate_inputs),
        "companion_pressure_window_count": len(companion_pressure_window_indexes),
        "route_segment_context_window_count": len(route_context_windows),
        "route_pressure_window_count": len(route_pressure_window_indexes),
        "gate_inputs": [item.model_dump(mode="json") for item in gate_inputs],
        "data_quality": replay_model.data_quality.model_dump(mode="json"),
        "privacy": replay_model.privacy.model_dump(mode="json"),
        "boundary": replay_model.boundary.model_dump(mode="json"),
        "mutation": {
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _load_health_auto_export_payload(source_path: Path) -> tuple[dict[str, Any], str]:
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as archive:
            member_name = _select_health_auto_export_member(archive.namelist())
            return json.loads(archive.read(member_name)), "health_auto_export_local_zip"
    return json.loads(source_path.read_text(encoding="utf-8")), "health_auto_export_local_json"


def _select_health_auto_export_member(names: list[str]) -> str:
    candidates = [
        name
        for name in names
        if Path(name).name.lower().startswith("healthautoexport-") and name.lower().endswith(".json")
    ]
    if not candidates:
        candidates = [name for name in names if name.lower().endswith(".json")]
    if not candidates:
        raise ValueError("Health Auto Export archive has no JSON member")
    return sorted(candidates)[0]


def _session_summaries_from_payload(
    payload: Any,
    *,
    source_path: Path,
    activity_type: ActivityKind,
    altitude_m: float | None,
) -> list[PhysiologicSessionSummary]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict) or not isinstance(data.get("workouts"), list):
        raise ValueError("Health Auto Export physiologic parser requires data.workouts")
    metrics = _metrics_by_day(data.get("metrics", []))
    sessions: list[PhysiologicSessionSummary] = []
    for workout in data["workouts"]:
        if not isinstance(workout, dict):
            continue
        workout_type = _workout_type(workout)
        if workout_type != activity_type:
            continue
        start = _parse_apple_date(_string_from_value(workout.get("start")))
        if start is None:
            continue
        day = start.date().isoformat()
        duration_s = round(_number_from_value(workout.get("duration")) or 0)
        if not duration_s:
            end = _parse_apple_date(_string_from_value(workout.get("end")))
            duration_s = round((end - start).total_seconds()) if end else 0
        heart_rate_points = _heart_rate_points(workout, start=start)
        heart_rates = [point[1] for point in heart_rate_points]
        avg_hr = _quantity(workout.get("avgHeartRate"), default_units="bpm", target_units="bpm")
        if avg_hr is None and heart_rates:
            avg_hr = sum(heart_rates) / len(heart_rates)
        max_hr = _quantity(workout.get("maxHeartRate"), default_units="bpm", target_units="bpm")
        if max_hr is None and heart_rates:
            max_hr = max(heart_rates)
        session = PhysiologicSessionSummary(
            session_index=len(sessions) + 1,
            activity_type=workout_type,
            duration_s=duration_s,
            distance_m=round(_quantity(workout.get("distance"), default_units="km", target_units="m") or 0.0, 1),
            ascent_m=round(_quantity(workout.get("elevationUp"), default_units="m", target_units="m") or 0.0, 1),
            avg_heart_rate_bpm=round(avg_hr, 3) if avg_hr is not None else None,
            max_heart_rate_bpm=round(max_hr, 3) if max_hr is not None else None,
            p90_heart_rate_bpm=_percentile(heart_rates, 0.9),
            start_heart_rate_avg_5m_bpm=_window_avg(heart_rate_points, 5 * 60) or (round(avg_hr, 3) if avg_hr else None),
            start_heart_rate_avg_10m_bpm=_window_avg(heart_rate_points, 10 * 60) or (round(avg_hr, 3) if avg_hr else None),
            high_heart_rate_burden=_high_hr_burden(heart_rate_points, duration_s=duration_s),
            vo2max_estimate_ml_kg_min=_metric_value(metrics, "vo2_max", day),
            physical_effort_score=_metric_value(metrics, "physical_effort", day),
            running_power_w=_metric_value(metrics, "running_power", day),
            running_speed_kmh=_metric_value(metrics, "running_speed", day),
            active_energy_kj=(
                _quantity(workout.get("activeEnergyBurned"), default_units="kJ", target_units="kJ")
                or _quantity(workout.get("activeEnergy"), default_units="kJ", target_units="kJ")
            ),
            oxygen_saturation_pct=_metric_value(metrics, "blood_oxygen_saturation", day),
            oxygen_uptake=OxygenUptakeEstimate(altitude_m=altitude_m),
            heart_rate_recovery=HeartRateRecoveryFeature(
                recovery_drop_bpm=_recovery_drop(workout),
            ),
            work_output=WorkOutputResetFeature(),
            data_quality=ScoutEnergyDataQuality(
                heart_rate_confidence="medium" if heart_rates or avg_hr else "low",
                gps_confidence="low",
                missing_hr_seconds=0 if heart_rates else duration_s,
                sample_cadence_s=_sample_cadence(heart_rate_points),
                provider_value_confidence="medium",
                limitations=[
                    "Health Auto Export physiologic parser emitted sanitized session summary only",
                    "raw health payload, raw heart-rate samples, exact timestamps, and route geometry are not embedded",
                    "VO2max and SpO2 remain provider source values, not Scout truth",
                ],
            ),
            privacy=ScoutEnergyPrivacy(),
            boundary=ScoutEnergyBoundary(),
        )
        sessions.append(session)
    return sessions


def _session_with_baseline_features(
    session: PhysiologicSessionSummary,
    *,
    baseline: PhysiologicFeatureBaseline,
    altitude_m: float | None,
) -> PhysiologicSessionSummary:
    output = _session_energy_output_kj(session)
    source: EnergyOutputSource
    if session.active_energy_kj is not None:
        source = "provider_active_energy_kj"
    elif session.running_power_w is not None and session.duration_s:
        source = "running_power_integral_kj"
    else:
        source = "missing"
    ratio = round(output / baseline.reset_cue_kj, 3) if output is not None and baseline.reset_cue_kj else None
    if ratio is None:
        reset_stage: ResetStage = "none"
    elif ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_overdraft_ratio:
        reset_stage = "overdraft_candidate"
    elif ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_reset_ratio:
        reset_stage = "reset_cue"
    elif ratio >= WORKSPACE_THRESHOLD_POLICY.work_output_pre_reset_ratio:
        reset_stage = "pre_reset"
    else:
        reset_stage = "none"
    recovery_ratio = (
        round(session.heart_rate_recovery.recovery_drop_bpm / baseline.baseline_recovery_drop_bpm, 3)
        if session.heart_rate_recovery.recovery_drop_bpm is not None and baseline.baseline_recovery_drop_bpm
        else None
    )
    if recovery_ratio is None:
        recovery_class: RecoveryClassification = "unknown"
    elif recovery_ratio >= WORKSPACE_THRESHOLD_POLICY.fast_recovery_ratio_to_personal_baseline:
        recovery_class = "fast"
    elif recovery_ratio <= WORKSPACE_THRESHOLD_POLICY.slow_recovery_ratio_to_personal_baseline:
        recovery_class = "slow"
    else:
        recovery_class = "expected"
    oxygen = _oxygen_estimate(session, baseline=baseline, altitude_m=altitude_m)
    return session.model_copy(
        update={
            "oxygen_uptake": oxygen,
            "heart_rate_recovery": HeartRateRecoveryFeature(
                recovery_drop_bpm=session.heart_rate_recovery.recovery_drop_bpm,
                baseline_recovery_drop_bpm=baseline.baseline_recovery_drop_bpm,
                recovery_ratio_to_personal_baseline=recovery_ratio,
                classification=recovery_class,
            ),
            "work_output": WorkOutputResetFeature(
                energy_output_kj=round(output, 3) if output is not None else None,
                energy_output_source=source,
                typical_completed_output_kj=baseline.typical_completed_output_kj,
                reset_cue_kj=baseline.reset_cue_kj,
                ratio_to_reset_budget=ratio,
                reset_stage=reset_stage,
            ),
        }
    )


def _oxygen_estimate(
    session: PhysiologicSessionSummary,
    *,
    baseline: PhysiologicFeatureBaseline,
    altitude_m: float | None,
) -> OxygenUptakeEstimate:
    altitude_ratio = _altitude_oxygen_ratio(altitude_m)
    speed_m_min = (session.running_speed_kmh or 0.0) * 1000.0 / 60.0
    grade = min(0.30, max(0.0, session.ascent_m / session.distance_m)) if session.distance_m else 0.0
    estimated_cost = 3.5 + 0.2 * speed_m_min + 0.9 * speed_m_min * grade if speed_m_min else None
    if estimated_cost is not None and baseline.baseline_vo2max_ml_kg_min:
        ratio = round((estimated_cost / baseline.baseline_vo2max_ml_kg_min) * (altitude_ratio or 1.0), 3)
    else:
        ratio = None
    limitations = [
        "speed/grade oxygen cost proxy is advisory, not measured oxygen uptake",
        "VO2max provider estimate is baseline context, not live oxygen uptake",
        "SpO2 percent is not compared to VO2max ml/kg/min",
    ]
    if altitude_m is not None:
        limitations.append("altitude oxygen availability is environmental context, not diagnosis")
    return OxygenUptakeEstimate(
        vo2max_estimate_ml_kg_min=session.vo2max_estimate_ml_kg_min,
        baseline_vo2max_ml_kg_min=baseline.baseline_vo2max_ml_kg_min,
        estimated_oxygen_cost_ml_kg_min=round(estimated_cost, 3) if estimated_cost is not None else None,
        oxygen_uptake_ratio_to_personal_baseline=ratio,
        altitude_m=altitude_m,
        altitude_oxygen_availability_ratio=altitude_ratio,
        oxygen_saturation_pct=session.oxygen_saturation_pct,
        limitations=limitations,
    )


def _session_energy_output_kj(session: PhysiologicSessionSummary) -> float | None:
    if session.active_energy_kj is not None:
        return session.active_energy_kj
    if session.running_power_w is not None and session.duration_s:
        return session.running_power_w * session.duration_s / 1000.0
    return None


def _replay_active_energy_kj(replay: PhysiologicWindowedActivityReplay) -> float | None:
    values = [window.active_energy_kj for window in replay.windows if window.active_energy_kj is not None]
    return round(sum(values), 3) if values else None


def _replay_active_energy_kj_per_hour(replay: PhysiologicWindowedActivityReplay) -> float | None:
    total_energy = _replay_active_energy_kj(replay)
    total_hours = sum(window.duration_min for window in replay.windows) / 60.0
    if total_energy is None or not total_hours:
        return None
    return round(total_energy / total_hours, 3)


def _analysis_route_context_for_replay(replay: PhysiologicWindowedActivityReplay) -> PhysiologicRouteContext:
    duration_min = max(1, round(sum(window.duration_min for window in replay.windows)))
    distance_m = round(sum(window.distance_m for window in replay.windows), 3)
    return PhysiologicRouteContext(
        route_id="sanitized.health_auto_export_analysis",
        segment_id=f"session-{replay.session_index}",
        distance_to_next_checkpoint_m=distance_m,
        estimated_minutes_to_next_checkpoint=duration_min,
        estimated_minutes_to_planned_camp=duration_min,
        daylight_buffer_minutes=120,
        external_pressure_flags=[],
    )


def _analysis_session_from_replay(
    replay: PhysiologicWindowedActivityReplay,
    gate_outputs: list[PhysiologicGateOutput],
) -> HealthAutoExportPhysioAnalysisSession:
    windows = replay.windows
    active_energy = _replay_active_energy_kj(replay)
    movement_ratios = [
        window.movement_efficiency_ratio_to_session_reference
        for window in windows
        if window.movement_efficiency_ratio_to_session_reference is not None
    ]
    p90_heart_rates = [
        window.p90_heart_rate_bpm for window in windows if window.p90_heart_rate_bpm is not None
    ]
    avg_heart_rates = [
        window.avg_heart_rate_bpm for window in windows if window.avg_heart_rate_bpm is not None
    ]
    return HealthAutoExportPhysioAnalysisSession(
        session_index=replay.session_index,
        activity_type=replay.activity_type,
        window_count=replay.window_count,
        duration_min=round(sum(window.duration_min for window in windows), 3),
        distance_km=round(sum(window.distance_m for window in windows) / 1000.0, 3),
        active_energy_kj=active_energy,
        session_reference_pace_mps=replay.session_reference_pace_mps,
        session_reference_cadence_spm=replay.session_reference_cadence_spm,
        avg_window_hr_bpm=round(sum(avg_heart_rates) / len(avg_heart_rates), 3)
        if avg_heart_rates
        else None,
        max_window_p90_hr_bpm=max(p90_heart_rates) if p90_heart_rates else None,
        hr_pressure_windows=sum(1 for window in windows if window.heart_rate_pressure),
        high_hr_low_efficiency_windows=sum(
            1 for window in windows if window.high_hr_low_efficiency_window
        ),
        recovery_debt_candidate_windows=sum(
            1 for window in windows if window.rest_cost.stage == "recovery_debt_candidate"
        ),
        slow_or_rest_windows=sum(
            1 for window in windows if window.rest_cost.rest_ratio_recent_window >= 0.4
        ),
        max_following_rest_cost_min=max(
            [window.rest_cost.following_rest_cost_minutes_next_60m for window in windows] or [0.0]
        ),
        min_movement_efficiency_ratio=min(movement_ratios) if movement_ratios else None,
        gate_state_counts=_gate_state_counts(gate_outputs),
        max_gate_state=_max_gate_state(gate_outputs),
        max_eta_delay_min=max([output.eta_delay_minutes for output in gate_outputs] or [0]),
        dominant_reason_samples=_dedupe_strings(
            [reason for output in gate_outputs for reason in output.dominant_reasons]
        )[:6],
    )


def _provider_metric_summaries_from_payload(
    payload: Any,
    *,
    metric_names: set[str] | None,
) -> list[ProviderMetricAggregate]:
    default_metric_names = {
        "active_energy",
        "blood_oxygen_saturation",
        "flights_climbed",
        "heart_rate",
        "heart_rate_variability",
        "resting_heart_rate",
        "step_count",
        "vo2_max",
        "walking_heart_rate_average",
        "walking_running_distance",
    }
    selected_names = metric_names or default_metric_names
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    metrics = data.get("metrics", []) if isinstance(data, dict) else []
    if not isinstance(metrics, list):
        return []
    summaries: list[ProviderMetricAggregate] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = _string_from_value(metric.get("name") or metric.get("type") or metric.get("identifier"))
        if not name or name not in selected_names:
            continue
        rows = metric.get("data") or metric.get("entries") or metric.get("values") or []
        if not isinstance(rows, list):
            continue
        values = [_metric_row_number(row) for row in rows]
        values = [value for value in values if value is not None]
        if not values:
            continue
        summaries.append(
            ProviderMetricAggregate(
                metric_name=name,
                sample_count=len(values),
                min_value=round(min(values), 3),
                mean_value=round(sum(values) / len(values), 3),
                median_value=round(float(median(values)), 3),
                max_value=round(max(values), 3),
            )
        )
    return sorted(summaries, key=lambda item: item.metric_name)


def _metric_row_number(row: Any) -> float | None:
    if isinstance(row, dict):
        return _number_from_value(
            _first_value(row, "qty", "value", "Avg", "avg", "average", "count")
        )
    return _number_from_value(row)


def _provider_metric_deltas(
    previous_metrics: list[ProviderMetricAggregate],
    current_metrics: list[ProviderMetricAggregate],
) -> list[HealthAutoExportPhysioMetricDelta]:
    previous_by_name = {metric.metric_name: metric for metric in previous_metrics}
    current_by_name = {metric.metric_name: metric for metric in current_metrics}
    metric_names = sorted(set(previous_by_name) | set(current_by_name))
    deltas: list[HealthAutoExportPhysioMetricDelta] = []
    for metric_name in metric_names:
        previous_value = previous_by_name.get(metric_name).median_value if metric_name in previous_by_name else None
        current_value = current_by_name.get(metric_name).median_value if metric_name in current_by_name else None
        deltas.append(
            HealthAutoExportPhysioMetricDelta(
                metric_name=metric_name,
                previous_median_value=previous_value,
                current_median_value=current_value,
                absolute_delta=_optional_delta(current_value, previous_value),
                relative_delta_pct=_optional_delta_pct(current_value, previous_value),
            )
        )
    return deltas


def _candidate_change_reasons(
    *,
    rank_delta: int,
    high_hr_low_efficiency_delta: int,
    recovery_debt_delta: int,
    hr_pressure_delta: int,
    pace_delta_pct: float | None,
    reset_delta_pct: float | None,
    material_pace_delta_pct: float,
    material_reset_cue_delta_pct: float,
) -> list[str]:
    reasons: list[str] = []
    if abs(rank_delta) >= 2:
        direction = "improved" if rank_delta < 0 else "worse"
        reasons.append(f"max physiologic gate state materially {direction}")
    if high_hr_low_efficiency_delta != 0:
        direction = "decreased" if high_hr_low_efficiency_delta < 0 else "increased"
        reasons.append(f"high-HR/low-efficiency windows {direction}")
    if recovery_debt_delta != 0:
        direction = "decreased" if recovery_debt_delta < 0 else "increased"
        reasons.append(f"recovery-debt candidate windows {direction}")
    if hr_pressure_delta != 0 and abs(rank_delta) >= 1:
        direction = "decreased" if hr_pressure_delta < 0 else "increased"
        reasons.append(f"heart-rate pressure windows {direction} with state movement")
    if pace_delta_pct is not None and abs(pace_delta_pct) >= material_pace_delta_pct:
        direction = "improved" if pace_delta_pct > 0 else "declined"
        reasons.append(f"sustainable pace materially {direction}")
    if reset_delta_pct is not None and abs(reset_delta_pct) >= material_reset_cue_delta_pct:
        direction = "increased" if reset_delta_pct > 0 else "decreased"
        reasons.append(f"reset cue materially {direction}")
    return reasons


def _physio_review_priority(
    current_state: PhysiologicGateState,
    *,
    review_candidate_change: bool,
    trend_direction: PhysioReviewTrendDirection,
) -> PhysioReviewPriority:
    if current_state in {"retreat_suggested", "alert_candidate"}:
        return "urgent_review"
    if current_state == "stop_and_rest" or (review_candidate_change and trend_direction == "worse"):
        return "review"
    if current_state == "watch" or review_candidate_change:
        return "monitor"
    return "none"


def _physio_review_reasons(
    current: HealthAutoExportPhysioAnalysis,
    delta: HealthAutoExportPhysioAnalysisDelta | None,
) -> list[str]:
    reasons = [
        f"current max physiologic gate state is {current.overall.max_gate_state}",
        f"current analysis has {current.overall.total_high_hr_low_efficiency_windows} high-HR/low-efficiency windows",
        f"current analysis has {current.overall.total_recovery_debt_candidate_windows} recovery-debt candidate windows",
    ]
    if delta is not None:
        reasons.append(f"trend direction is {delta.state_direction}")
        reasons.extend(delta.candidate_change_reasons or delta.no_candidate_change_reasons)
    else:
        reasons.append("no previous analysis delta attached")
    return _dedupe_strings(reasons)[:8]


def _physio_review_actions(
    *,
    review_priority: PhysioReviewPriority,
    review_candidate_change: bool,
) -> list[str]:
    if review_priority == "urgent_review":
        return [
            "route-pressure review should inspect physiologic evidence before any harder-route fit update",
            "keep broader retreat/weather/darkness/environment gates authoritative",
        ]
    if review_priority == "review":
        return [
            "review rest, pace, and delay evidence before changing route-fit assumptions",
            "keep this capsule out of Phase 1 safety truth",
        ]
    if review_priority == "monitor":
        actions = ["continue baseline-relative monitoring with 15-minute windows"]
        if review_candidate_change:
            actions.append("review trend before updating companion or capability matching")
        return actions
    return ["no physiologic review action from this capsule alone"]


def _optional_delta(current_value: float | None, previous_value: float | None) -> float | None:
    if current_value is None or previous_value is None:
        return None
    return round(current_value - previous_value, 3)


def _optional_delta_pct(current_value: float | None, previous_value: float | None) -> float | None:
    if current_value is None or previous_value in {None, 0}:
        return None
    return round(((current_value - previous_value) / previous_value) * 100.0, 3)


def _gate_state_counts(gate_outputs: list[PhysiologicGateOutput]) -> dict[str, int]:
    states: list[PhysiologicGateState] = [
        "warmup",
        "normal",
        "watch",
        "stop_and_rest",
        "retreat_suggested",
        "alert_candidate",
    ]
    return {state: sum(1 for output in gate_outputs if output.state == state) for state in states}


def _max_gate_state(gate_outputs: list[PhysiologicGateOutput]) -> PhysiologicGateState:
    if not gate_outputs:
        return "normal"
    return max((output.state for output in gate_outputs), key=_state_rank)


def _companion_pace_ratio_to_user_reference(
    *,
    companion_reference_pace_mps: float | None,
    companion_reference_cadence_spm: float | None,
    user_reference_pace_mps: float | None,
    user_reference_cadence_spm: float | None,
) -> float | None:
    if companion_reference_pace_mps is not None and user_reference_pace_mps:
        return round(companion_reference_pace_mps / user_reference_pace_mps, 3)
    if companion_reference_cadence_spm is not None and user_reference_cadence_spm:
        return round(companion_reference_cadence_spm / user_reference_cadence_spm, 3)
    return None


def _route_context_with_external_pressure(
    route: PhysiologicRouteContext,
    *,
    pressure_flags: list[str],
) -> PhysiologicRouteContext:
    if not pressure_flags:
        return route
    flags = list(route.external_pressure_flags)
    for pressure_flag in pressure_flags:
        if pressure_flag not in flags:
            flags.append(pressure_flag)
    return route.model_copy(update={"external_pressure_flags": flags})


def _selected_route_segment_minutes(
    *,
    selected_time_source: RouteSegmentTimingSource,
    reference_min_minutes: float | None,
    reference_p50_minutes: float | None,
    reference_p75_minutes: float | None,
    reference_max_minutes: float | None,
    manual_guide_minutes: float | None,
) -> float:
    values = {
        "min": reference_min_minutes,
        "p50": reference_p50_minutes,
        "p75": reference_p75_minutes,
        "max": reference_max_minutes,
        "manual_guide": manual_guide_minutes,
    }
    selected = values[selected_time_source]
    if selected is not None and selected > 0:
        return selected
    fallback_order: list[RouteSegmentTimingSource] = ["p75", "manual_guide", "p50", "max", "min"]
    for source in fallback_order:
        fallback = values[source]
        if fallback is not None and fallback > 0:
            return fallback
    raise ValueError("route segment reference context requires at least one positive timing value")


def _minimum_present_float(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(min(present), 3) if present else None


def _quantity_points(
    rows: Any,
    *,
    start: datetime,
    default_units: str,
    target_units: str,
) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    if not isinstance(rows, list):
        return points
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = _parse_apple_date(_string_from_value(row.get("date")))
        value = _quantity(row, default_units=default_units, target_units=target_units)
        if timestamp is not None and value is not None:
            points.append((max(0, round((timestamp - start).total_seconds())), value))
    return sorted(points, key=lambda item: item[0])


def _spread_total_over_windows(total: float, *, duration_s: int, window_minutes: int) -> list[tuple[int, float]]:
    if total <= 0 or duration_s <= 0:
        return []
    window_s = window_minutes * 60
    window_count = max(1, math.ceil(duration_s / window_s))
    value = total / window_count
    return [(index * window_s, value) for index in range(window_count)]


def _window_sum(points: list[tuple[int, float]], *, start_s: int, end_s: int) -> float:
    return sum(value for offset_s, value in points if start_s <= offset_s < end_s)


def _reference_high_efficiency_value(values: list[float]) -> float | None:
    values = [value for value in values if value and value > 0]
    if not values:
        return None
    ordered = sorted(values)
    top_half = ordered[len(ordered) // 2 :]
    return round(float(median(top_half or ordered)), 6)


def _reference_heart_rate(values: list[float]) -> float | None:
    values = [value for value in values if value and value > 0]
    return round(float(median(values)), 3) if values else None


def _movement_efficiency_from_window(
    *,
    pace_mps: float | None,
    cadence_spm: float | None,
    reference_pace_mps: float | None,
    reference_cadence_spm: float | None,
) -> float | None:
    if pace_mps is not None and reference_pace_mps:
        return round(pace_mps / reference_pace_mps, 3)
    if cadence_spm is not None and reference_cadence_spm:
        return round(cadence_spm / reference_cadence_spm, 3)
    return None


def _rest_ratio_from_efficiency(movement_ratio: float | None) -> float:
    if movement_ratio is None:
        return 0.0
    return round(max(0.0, 1.0 - min(1.0, movement_ratio)), 3)


def _window_heart_rate_pressure(
    *,
    avg_hr: float | None,
    p90_hr: float | None,
    max_hr: float | None,
    session_hr_reference: float | None,
) -> bool:
    if p90_hr is not None and p90_hr >= 160:
        return True
    if max_hr is not None and max_hr >= 170:
        return True
    if avg_hr is not None and session_hr_reference:
        drift = (avg_hr - session_hr_reference) / session_hr_reference
        return drift >= WORKSPACE_THRESHOLD_POLICY.heart_rate_high_drift_ratio
    return False


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _heart_rate_zone_from_bpm(heart_rate_bpm: float | None) -> str | None:
    if heart_rate_bpm is None:
        return None
    if heart_rate_bpm >= 160:
        return "z5"
    if heart_rate_bpm >= 150:
        return "z4"
    if heart_rate_bpm >= 135:
        return "z3"
    if heart_rate_bpm >= 120:
        return "z2"
    return "z1"


def _metrics_by_day(metrics: Any) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    if not isinstance(metrics, list):
        return result
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = _string_from_value(metric.get("name"))
        data = metric.get("data")
        if not name or not isinstance(data, list):
            continue
        result[name] = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            timestamp = _parse_apple_date(_string_from_value(row.get("date")))
            qty = _number_from_value(row.get("qty"))
            if timestamp is not None and qty is not None:
                result[name][timestamp.date().isoformat()] = round(qty, 6)
    return result


def _metric_value(metrics: dict[str, dict[str, float]], name: str, day: str) -> float | None:
    value = metrics.get(name, {}).get(day)
    return round(value, 3) if value is not None else None


def _workout_type(workout: dict[str, Any]) -> ActivityKind:
    name = str(workout.get("name") or "").lower()
    if "跑" in name or "run" in name:
        return "running"
    if "步行" in name or "walk" in name:
        return "walking"
    if "hike" in name or "登山" in name:
        return "hiking"
    return "other"


def _heart_rate_points(workout: dict[str, Any], *, start: datetime) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    samples = workout.get("heartRateData")
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            bpm = _number_from_value(_first_value(sample, "Avg", "avg", "qty", "value"))
            sample_time = _parse_apple_date(_string_from_value(sample.get("date")))
            if bpm is not None and sample_time is not None:
                points.append((max(0, round((sample_time - start).total_seconds())), round(bpm)))
    return sorted(points, key=lambda item: item[0])


def _high_hr_burden(points: list[tuple[int, int]], *, duration_s: int) -> HighHeartRateBurden:
    thresholds = [160, 165, 170]
    if not points:
        return HighHeartRateBurden(sample_count=0)
    cadence = _sample_cadence(points) or 5
    totals: dict[str, float] = {}
    continuous: dict[str, float] = {}
    percents: dict[str, float] = {}
    for threshold in thresholds:
        total_s = 0.0
        current_s = 0.0
        max_s = 0.0
        hits = 0
        for index, (offset_s, bpm) in enumerate(points):
            if index + 1 < len(points):
                step_s = points[index + 1][0] - offset_s
            else:
                step_s = min(cadence, max(0, duration_s - offset_s)) or cadence
            if step_s <= 0 or step_s > 60:
                step_s = cadence
            if bpm >= threshold:
                hits += 1
                total_s += step_s
                current_s += step_s
                max_s = max(max_s, current_s)
            else:
                current_s = 0.0
        key = str(threshold)
        totals[key] = round(total_s / 60.0, 3)
        continuous[key] = round(max_s / 60.0, 3)
        percents[key] = round(hits / len(points) * 100.0, 3)
    return HighHeartRateBurden(
        total_minutes_at_or_above=totals,
        continuous_minutes_at_or_above=continuous,
        percent_samples_at_or_above=percents,
        sample_count=len(points),
        sample_cadence_s=cadence,
    )


def _recovery_drop(workout: dict[str, Any]) -> float | None:
    values: list[float] = []
    samples = workout.get("heartRateRecovery")
    if not isinstance(samples, list):
        return None
    for sample in samples:
        if isinstance(sample, dict):
            value = _number_from_value(_first_value(sample, "Avg", "avg", "qty", "value"))
            if value is not None:
                values.append(value)
    if len(values) < 2:
        return None
    return round(max(0.0, values[0] - min(values)), 3)


def _window_avg(points: list[tuple[int, int]], window_s: int) -> float | None:
    values = [bpm for offset_s, bpm in points if 0 <= offset_s <= window_s]
    return round(sum(values) / len(values), 3) if values else None


def _percentile(values: list[int], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return round(ordered[lower] * (upper - position) + ordered[upper] * (position - lower), 3)


def _sample_cadence(points: list[tuple[int, int]]) -> int | None:
    if len(points) < 2:
        return None
    deltas = [current[0] - previous[0] for previous, current in zip(points, points[1:]) if current[0] > previous[0]]
    deltas = [delta for delta in deltas if 0 < delta < 300]
    return max(1, round(sum(deltas) / len(deltas))) if deltas else None


def _quantity(value: Any, *, default_units: str, target_units: str) -> float | None:
    if isinstance(value, list):
        values = [_quantity(item, default_units=default_units, target_units=target_units) for item in value]
        values = [item for item in values if item is not None]
        return sum(values) if values else None
    units = default_units
    raw = value
    if isinstance(value, dict):
        raw = value.get("qty", value.get("value"))
        units = str(value.get("units") or default_units)
    number = _number_from_value(raw)
    if number is None:
        return None
    normalized = units.lower()
    if target_units == "m" and normalized == "km":
        return number * 1000.0
    if target_units == "kj" and normalized in {"kcal", "cal"}:
        return number * 4.184
    return number


def _altitude_oxygen_ratio(altitude_m: float | None) -> float | None:
    if altitude_m is None:
        return None
    return round(math.exp(-altitude_m / 8434.5), 3)


def _combine_quality(qualities: list[ScoutEnergyDataQuality]) -> ScoutEnergyDataQuality:
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min((quality.heart_rate_confidence for quality in qualities), key=order.get),
        gps_confidence=min((quality.gps_confidence for quality in qualities), key=order.get),
        missing_hr_seconds=sum(quality.missing_hr_seconds for quality in qualities),
        provider_value_confidence=min((quality.provider_value_confidence for quality in qualities), key=order.get),
        limitations=sorted({item for quality in qualities for item in quality.limitations}),
    )


def _composer_action(
    *,
    physiologic_state: PhysiologicGateState,
    alert_required: bool,
    retreat_required: bool,
    route_pressure_required: bool,
    team_pace_reset: bool,
    rest_now: bool,
) -> RoutePressureCompositeAction:
    if alert_required:
        return "alert_review"
    if retreat_required:
        return "retreat_review"
    if team_pace_reset:
        return "team_pace_reset"
    if route_pressure_required:
        return "route_pressure_review"
    if rest_now:
        return "stop_and_recheck"
    if physiologic_state == "watch":
        return "slow_down"
    return "continue_monitoring"


def _composer_reasons(
    *,
    physiologic_state: PhysiologicGateState,
    companion_pressure: CompanionPacePressureEvidence | None,
    pace_gate_failed: bool,
    delay_gate_failed: bool,
    route_pressure_required: bool,
    rest_now: bool,
) -> list[str]:
    reasons = [f"max physiologic state is {physiologic_state}"]
    if rest_now:
        reasons.append("physiologic gate recommends rest and recheck")
    if companion_pressure and companion_pressure.pressure_detected:
        reasons.append(
            "companion pace pressure indicates group-rhythm mismatch with downstream rest-cost delay"
        )
    if companion_pressure and companion_pressure.estimated_rest_cost_minutes:
        reasons.append(
            f"estimated rest-cost delay is {companion_pressure.estimated_rest_cost_minutes:.1f} minutes"
        )
    if pace_gate_failed:
        reasons.append("pace gate input is failed")
    if delay_gate_failed:
        reasons.append("delay gate input is failed")
    if route_pressure_required:
        reasons.append("route pressure review is required by composed evidence")
    return reasons


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _state_rank(state: PhysiologicGateState) -> int:
    return {
        "warmup": 0,
        "normal": 1,
        "watch": 2,
        "stop_and_rest": 3,
        "retreat_suggested": 4,
        "alert_candidate": 5,
    }[state]


def _required_action_for_state(state: PhysiologicGateState) -> str:
    return {
        "warmup": "none",
        "normal": "none",
        "watch": "slow_down",
        "stop_and_rest": "rest_now",
        "retreat_suggested": "retreat_review",
        "alert_candidate": "alert_review",
    }[state]


def _assert_live_fixture_boundary(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    if payload.get("network_request_performed") or payload.get("real_provider_api_called"):
        raise ValueError("live physiologic fixture must not perform network or real provider API calls")
    if payload.get("runtime_ingest_performed") or payload.get("safety_api_called"):
        raise ValueError("live physiologic fixture must not ingest runtime state or call safety APIs")


def _live_frames(payload: Any) -> list[dict[str, Any]]:
    frames = payload.get("frames") if isinstance(payload, dict) else None
    if frames is None and isinstance(payload, dict):
        frames = payload.get("samples") or payload.get("observations")
    if frames is None and isinstance(payload, list):
        frames = payload
    if not isinstance(frames, list) or not frames or not all(isinstance(frame, dict) for frame in frames):
        raise ValueError("live physiologic fixture requires frames, samples, or observations")
    return frames


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


def _enforce_privacy(privacy: ScoutEnergyPrivacy) -> None:
    if privacy.raw_health_payload_shared:
        raise ValueError("physiologic feature set must not share raw health payload")
    if privacy.raw_samples_embedded:
        raise ValueError("physiologic feature set must not embed raw samples")
    if privacy.raw_track_shared:
        raise ValueError("physiologic feature set must not share raw track")
    if privacy.exact_timestamps_shared:
        raise ValueError("physiologic feature set must not share exact timestamps")
    if privacy.home_work_trace_shared:
        raise ValueError("physiologic feature set must not share home/work traces")


def _first_value(payload: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = _nested_value(payload, path)
        if value is not None:
            return value
    return None


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _parse_apple_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def _string_from_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _number_from_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int_from_value(value: Any) -> int | None:
    number = _number_from_value(value)
    return round(number) if number is not None else None


def _bool_from_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None
