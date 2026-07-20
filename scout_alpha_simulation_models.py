from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_emergency_mobile_closed_loop_sandbox import (
    SandboxApprovalArtifact,
    SandboxTransportAttempt,
    SandboxTransportReceipt,
    SandboxTransportSimulation,
)


ScenarioProfile = Literal[
    "nominal_gpx",
    "pace_pressure",
    "delay_pressure",
    "ridge_distress",
    "weather_exposure",
    "darkness_pressure",
    "environment_threat",
    "gnss_degraded",
    "network_recovery",
    "device_dropout",
]
IngressMode = Literal["synthetic_direct_feed", "loopback_mqtt_broker"]
FaultKind = Literal[
    "network_offline",
    "network_weak",
    "packet_drop",
    "packet_delay",
    "packet_duplicate",
    "packet_out_of_order",
    "gnss_dropout",
    "gnss_stale",
    "gnss_accuracy_degraded",
    "gnss_jump",
    "device_offline",
    "low_battery",
    "sensor_stale",
]
InteractionChannel = Literal["text", "voice", "ui_action"]
InteractionKind = Literal["command", "voice_transcript", "acknowledgement"]


_SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SandboxPlaybackConfig(StrictModel):
    virtual_start_at: str = "2026-07-20T08:00:00Z"
    speed_multiplier: float = Field(default=60.0, gt=0, le=3600)
    max_frames: int = Field(default=48, ge=2, le=512)
    fallback_source_interval_s: float = Field(default=10.0, gt=0, le=3600)


class SandboxFaultInjection(StrictModel):
    fault_id: str = Field(pattern=_SAFE_ID_PATTERN)
    kind: FaultKind
    start_frame: int = Field(ge=1)
    end_frame: int = Field(ge=1)
    device_id: str | None = Field(default=None, pattern=_SAFE_ID_PATTERN)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def validate_window(self) -> "SandboxFaultInjection":
        if self.end_frame < self.start_frame:
            raise ValueError("fault end_frame must be greater than or equal to start_frame")
        known_devices = {"sandbox-phone-v0", "sandbox-wearable-v0"}
        if self.device_id is not None and self.device_id not in known_devices:
            raise ValueError("fault device_id must identify the sandbox phone or wearable")
        gnss_kinds = {
            "gnss_dropout",
            "gnss_stale",
            "gnss_accuracy_degraded",
            "gnss_jump",
        }
        if self.kind in gnss_kinds and self.device_id not in {
            None,
            "sandbox-phone-v0",
        }:
            raise ValueError("GNSS faults can target only the sandbox phone")
        allowed_parameters = {
            "network_offline": set(),
            "network_weak": {"latency_ms"},
            "packet_drop": set(),
            "packet_delay": {"release_after_frames"},
            "packet_duplicate": set(),
            "packet_out_of_order": set(),
            "gnss_dropout": set(),
            "gnss_stale": {"stale_seconds"},
            "gnss_accuracy_degraded": {"horizontal_accuracy_m"},
            "gnss_jump": {"lat_delta", "lon_delta"},
            "device_offline": set(),
            "low_battery": {"level"},
            "sensor_stale": {"stale_seconds"},
        }[self.kind]
        unknown = set(self.parameters) - allowed_parameters
        if unknown:
            raise ValueError(f"unsupported fault parameter(s): {sorted(unknown)}")
        bounds = {
            "latency_ms": (0.0, 60_000.0),
            "release_after_frames": (1.0, 512.0),
            "stale_seconds": (0.0, 86_400.0),
            "horizontal_accuracy_m": (1.0, 10_000.0),
            "lat_delta": (-1.0, 1.0),
            "lon_delta": (-1.0, 1.0),
            "level": (0.0, 1.0),
        }
        for key, value in self.parameters.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"fault parameter {key} must be numeric")
            numeric = float(value)
            lower, upper = bounds[key]
            if not math.isfinite(numeric) or not lower <= numeric <= upper:
                raise ValueError(
                    f"fault parameter {key} must be between {lower} and {upper}"
                )
            if key == "release_after_frames" and numeric != int(numeric):
                raise ValueError("release_after_frames must be an integer")
        return self


class AlphaSandboxRunRequest(StrictModel):
    scenario_id: str = Field(pattern=_SAFE_ID_PATTERN)
    run_id: str = Field(pattern=_SAFE_ID_PATTERN)
    project_id: str | None = Field(default=None, pattern=_SAFE_ID_PATTERN)
    workspace_root: str | None = Field(default=None, min_length=1, max_length=4096)
    gpx_ref: str | None = Field(default=None, max_length=4096)
    scenario_profile: ScenarioProfile = "nominal_gpx"
    ingress_mode: IngressMode = "loopback_mqtt_broker"
    playback: SandboxPlaybackConfig = Field(default_factory=SandboxPlaybackConfig)
    faults: list[SandboxFaultInjection] = Field(default_factory=list, max_length=128)
    confirm_sandbox_run: bool = False


class AlphaSandboxAdvanceRequest(StrictModel):
    scenario_id: str = Field(pattern=_SAFE_ID_PATTERN)
    run_id: str = Field(pattern=_SAFE_ID_PATTERN)
    expected_revision: int = Field(ge=1)
    frame_count: int = Field(default=1, ge=1, le=512)
    to_completion: bool = False
    confirm_sandbox_advance: bool = False


class AlphaSandboxInteractionRequest(StrictModel):
    scenario_id: str = Field(pattern=_SAFE_ID_PATTERN)
    run_id: str = Field(pattern=_SAFE_ID_PATTERN)
    expected_revision: int = Field(ge=1)
    channel: InteractionChannel
    kind: InteractionKind
    content: str = Field(min_length=1, max_length=500)
    confirm_sandbox_interaction: bool = False


class AlphaScenarioCatalogItem(StrictModel):
    profile: ScenarioProfile
    label: str
    description: str
    expected_selected_gate_id: str | None = None
    default_fault_kinds: list[FaultKind] = Field(default_factory=list)
    candidate_only: bool = True
    runtime_safety_truth: bool = False


class AlphaScenarioProjection(StrictModel):
    scenario_id: str
    run_id: str
    project_id: str
    profile: ScenarioProfile
    source_mode: Literal["synthetic_replay"] = "synthetic_replay"
    source_role: Literal["historical_reference_gpx"] = "historical_reference_gpx"
    workspace_root_ref: str
    gpx_ref: str


class AlphaPlaybackProjection(StrictModel):
    state: Literal["prepared", "running", "completed"]
    cursor: int = Field(ge=0)
    total_frames: int = Field(ge=1)
    total_source_points: int = Field(ge=1)
    source_started_at: str | None = None
    source_ended_at: str | None = None
    virtual_start_at: str
    virtual_current_at: str
    source_elapsed_s: float = Field(ge=0)
    playback_elapsed_s: float = Field(ge=0)
    speed_multiplier: float = Field(gt=0)
    source_time_anomaly_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_cursor(self) -> "AlphaPlaybackProjection":
        if self.cursor > self.total_frames:
            raise ValueError("playback cursor cannot exceed total_frames")
        return self


class AlphaIngressProjection(StrictModel):
    adapter: str = "SensorLoggerMqttObserver.handle_message"
    mode: IngressMode
    topic_ref: str
    accepted_message_count: int = Field(default=0, ge=0)
    rejected_message_count: int = Field(default=0, ge=0)
    dropped_message_count: int = Field(default=0, ge=0)
    delayed_message_count: int = Field(default=0, ge=0)
    duplicate_message_id_count: int = Field(default=0, ge=0)
    out_of_order_message_id_count: int = Field(default=0, ge=0)
    message_gap_count: int = Field(default=0, ge=0)
    broker_connection_verified: bool = False
    loopback_publish_count: int = Field(default=0, ge=0)
    loopback_subscriber_delivery_count: int = Field(default=0, ge=0)
    external_network_calls_made: bool = False
    observer_status_ref: str | None = None


class AlphaNetworkProjection(StrictModel):
    current_state: Literal["online", "weak", "offline", "recovered"] = "online"
    transition_count: int = Field(default=0, ge=0)
    offline_frame_count: int = Field(default=0, ge=0)
    weak_frame_count: int = Field(default=0, ge=0)
    recovered: bool = False
    transition_refs: list[str] = Field(default_factory=list)


class AlphaDeviceProjection(StrictModel):
    device_id: str
    role: Literal["phone", "wearable"]
    current_state: Literal["online", "offline", "degraded"] = "online"
    message_count: int = Field(default=0, ge=0)
    sensor_names: list[str] = Field(default_factory=list)
    battery_level: float | None = Field(default=None, ge=0, le=1)
    offline_event_count: int = Field(default=0, ge=0)
    stale_sensor_event_count: int = Field(default=0, ge=0)


class AlphaRouteProjection(StrictModel):
    route_id: str
    source_role: Literal["historical_reference_gpx"] = "historical_reference_gpx"
    route_progress_m: float = Field(default=0, ge=0)
    total_distance_m: float = Field(default=0, ge=0)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    elevation_m: float | None = None
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    horizontal_accuracy_m: float | None = Field(default=None, gt=0)
    fix_quality: Literal[
        "not_started",
        "fresh_synthetic_fix",
        "stale_synthetic_fix",
        "degraded_synthetic_fix",
        "position_unknown",
    ] = "not_started"
    travel_direction: Literal["forward"] = "forward"
    position_unknown_event_count: int = Field(default=0, ge=0)
    source_ref: str


class AlphaFaultSummary(StrictModel):
    scheduled_count: int = Field(default=0, ge=0)
    applied_count: int = Field(default=0, ge=0)
    applied_by_kind: dict[str, int] = Field(default_factory=dict)
    active_fault_ids: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)


class AlphaInteractionEvent(StrictModel):
    interaction_id: str
    sequence: int = Field(ge=1)
    direction: Literal["user_to_scout", "scout_to_user"]
    channel: InteractionChannel
    kind: InteractionKind
    content: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_redacted: bool = False
    correlation_id: str
    simulated_at: str
    synthetic: bool = True
    audio_transport_simulated: bool = False
    hardware_audio_invoked: bool = False
    external_send_performed: bool = False

    @model_validator(mode="after")
    def reject_effect_claims(self) -> "AlphaInteractionEvent":
        if not self.synthetic or self.hardware_audio_invoked or self.external_send_performed:
            raise ValueError("alpha interaction cannot claim hardware or external effects")
        if (
            self.direction == "user_to_scout"
            and self.channel in {"text", "voice"}
            and not self.content_redacted
        ):
            raise ValueError("synthetic text and voice input must be redacted at rest")
        return self


class AlphaGateProjection(StrictModel):
    gate_id: str
    state_candidate: str
    severity: str
    ln_level_candidate: str
    confidence: str
    dominant_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class AlphaSafetyProjection(StrictModel):
    selected_gate_id: str | None = None
    ln_level_candidate: str = "L0_NORMAL"
    reducer_state: str = "normal"
    recommendation: str = "continue_monitoring"
    phase1_adapter_status: str = "blocked_feature_flag_disabled"
    gate_count: int = Field(default=0, ge=0)
    gates: list[AlphaGateProjection] = Field(default_factory=list)
    reducer_source_ref: str | None = None
    reducer_sha256: str | None = None
    decisive_evidence_refs: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False


class AlphaAlertCandidate(StrictModel):
    artifact_kind: str = "scout_alpha_mobile_wearable_alert_candidate"
    schema_version: str = "scout.alpha.mobile_wearable_alert_candidate.v0.1"
    packet_id: str
    sha256: str
    content_sha256: str
    scenario_id: str
    run_id: str
    source_revision: int = Field(ge=1)
    source_safety_sha256: str
    source_safety_ref: str
    selected_gate_id: str | None = None
    ln_level_candidate: str
    recommendation: str
    status: str = "pending_approval"
    location_ref: str
    summary: str
    requested_action: str = "operator_review"
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    sent: bool = False

    @model_validator(mode="after")
    def reject_effect_claims(self) -> "AlphaAlertCandidate":
        if not self.candidate_only or self.runtime_safety_truth or self.sent:
            raise ValueError("alpha alert candidate cannot claim runtime truth or delivery")
        return self


class AlphaReplayTimelineEvent(StrictModel):
    event_id: str
    sequence: int = Field(ge=1)
    revision: int = Field(ge=1)
    kind: Literal["replay_prepared", "replay_advanced", "replay_completed"]
    frame_cursor: int = Field(ge=0)
    virtual_at: str
    summary: str
    source_refs: list[str] = Field(default_factory=list)
    synthetic: bool = True
    runtime_safety_truth: bool = False

    @model_validator(mode="after")
    def reject_runtime_truth(self) -> "AlphaReplayTimelineEvent":
        if not self.synthetic or self.runtime_safety_truth:
            raise ValueError("alpha replay timeline cannot claim runtime truth")
        return self


class AlphaSandboxBoundary(StrictModel):
    local_only: bool = True
    synthetic_scenario: bool = True
    historical_reference_gpx_only: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    real_outbound_send_performed: bool = False
    production_transport_invoked: bool = False
    hardware_control_invoked: bool = False
    hardware_audio_invoked: bool = False
    network_mqtt_publish_performed: bool = False
    local_loopback_mqtt_publish_performed: bool = False
    loopback_network_only: bool = True
    external_network_calls_made: bool = False
    precise_real_user_location_embedded: bool = False
    raw_real_user_health_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_boundary(self) -> "AlphaSandboxBoundary":
        if not (
            self.local_only
            and self.synthetic_scenario
            and self.historical_reference_gpx_only
            and self.candidate_only
            and self.loopback_network_only
        ):
            raise ValueError("alpha sandbox must remain local synthetic candidate replay")
        prohibited = (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.real_outbound_send_performed
            or self.production_transport_invoked
            or self.hardware_control_invoked
            or self.hardware_audio_invoked
            or self.network_mqtt_publish_performed
            or self.external_network_calls_made
            or self.precise_real_user_location_embedded
            or self.raw_real_user_health_payload_embedded
        )
        if prohibited:
            raise ValueError("alpha sandbox boundary cannot claim runtime effects")
        return self


class AlphaSandboxLivingProjection(StrictModel):
    artifact_kind: str = "scout_alpha_mobile_wearable_sandbox_living_projection"
    schema_version: str = "scout.alpha.mobile_wearable_sandbox.living.v0.1"
    status: Literal["prepared", "running", "completed"]
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    revision: int = Field(ge=1)
    scenario: AlphaScenarioProjection
    playback: AlphaPlaybackProjection
    ingress: AlphaIngressProjection
    network: AlphaNetworkProjection
    devices: dict[str, AlphaDeviceProjection]
    route: AlphaRouteProjection
    fault_summary: AlphaFaultSummary
    timeline: list[AlphaReplayTimelineEvent] = Field(default_factory=list)
    interactions: list[AlphaInteractionEvent] = Field(default_factory=list)
    safety: AlphaSafetyProjection = Field(default_factory=AlphaSafetyProjection)
    alert_candidate: AlphaAlertCandidate | None = None
    approval: SandboxApprovalArtifact | None = None
    transport_attempt: SandboxTransportAttempt | None = None
    transport_simulation: SandboxTransportSimulation | None = None
    transport_receipt: SandboxTransportReceipt | None = None
    source_hashes: dict[str, str] = Field(default_factory=dict)
    source_refs: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    boundary: AlphaSandboxBoundary = Field(default_factory=AlphaSandboxBoundary)

    @model_validator(mode="after")
    def enforce_projection(self) -> "AlphaSandboxLivingProjection":
        if self.safety.runtime_safety_truth or self.safety.phase1_l0_l4_state_mutated:
            raise ValueError("alpha Living projection cannot promote replay to runtime truth")
        if self.playback.cursor > self.playback.total_frames:
            raise ValueError("alpha Living cursor exceeds frame count")
        if self.transport_receipt is not None and self.approval is None:
            raise ValueError("alpha receipt must retain its approval lineage")
        return self


__all__ = [
    "AlphaDeviceProjection",
    "AlphaAlertCandidate",
    "AlphaFaultSummary",
    "AlphaGateProjection",
    "AlphaIngressProjection",
    "AlphaInteractionEvent",
    "AlphaNetworkProjection",
    "AlphaPlaybackProjection",
    "AlphaRouteProjection",
    "AlphaReplayTimelineEvent",
    "AlphaSafetyProjection",
    "AlphaSandboxAdvanceRequest",
    "AlphaSandboxBoundary",
    "AlphaSandboxInteractionRequest",
    "AlphaSandboxLivingProjection",
    "AlphaSandboxRunRequest",
    "AlphaScenarioCatalogItem",
    "AlphaScenarioProjection",
    "FaultKind",
    "IngressMode",
    "SandboxFaultInjection",
    "SandboxPlaybackConfig",
    "ScenarioProfile",
]
