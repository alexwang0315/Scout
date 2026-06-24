from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_physiologic_integration import PhysiologicSafetyGateEvent
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


SafetyGateId = Literal[
    "pace_gate",
    "delay_gate",
    "physiologic_gate",
    "weather_gate",
    "darkness_gate",
    "environment_threat_gate",
]
SafetyGateSeverity = Literal[
    "none",
    "watch",
    "rest",
    "retreat_review",
    "alert_review",
]
SafetyLnTransitionCandidate = Literal[
    "none",
    "candidate_watch",
    "candidate_rest",
    "candidate_retreat",
    "candidate_alert_review",
]
SafetyLnLevelCandidate = Literal[
    "L0_NORMAL",
    "L1_CAUTION",
    "L2_CONCERN",
    "L3_RETREAT",
    "L4_ALERT_REVIEW",
]
SafetyGateConfidence = Literal["low", "medium", "high"]

PRIMARY_SAFETY_GATE_IDS: tuple[str, ...] = (
    "pace_gate",
    "delay_gate",
    "physiologic_gate",
    "weather_gate",
    "darkness_gate",
    "environment_threat_gate",
)

_LN_LEVEL_BY_TRANSITION: dict[str, SafetyLnLevelCandidate] = {
    "none": "L0_NORMAL",
    "candidate_watch": "L1_CAUTION",
    "candidate_rest": "L2_CONCERN",
    "candidate_retreat": "L3_RETREAT",
    "candidate_alert_review": "L4_ALERT_REVIEW",
}
_MIN_TRANSITION_BY_SEVERITY: dict[str, SafetyLnTransitionCandidate] = {
    "none": "none",
    "watch": "candidate_watch",
    "rest": "candidate_rest",
    "retreat_review": "candidate_retreat",
    "alert_review": "candidate_alert_review",
}


class SafetyGateRouteContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    map_target_ids: list[str] = Field(default_factory=list)
    distance_to_next_checkpoint_m: float | None = Field(default=None, ge=0)
    estimated_minutes_to_next_checkpoint: float | None = Field(default=None, ge=0)
    estimated_minutes_to_planned_camp: float | None = Field(default=None, ge=0)
    daylight_buffer_minutes: float | None = None
    altitude_m: float | None = None

    @model_validator(mode="after")
    def normalize_map_targets(self) -> "SafetyGateRouteContext":
        refs = [
            *(self.map_target_ids or []),
            self.segment_id,
            self.checkpoint_id,
        ]
        self.map_target_ids = _unique_string_list(refs)
        return self


class SafetyGateDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: SafetyGateConfidence = "low"
    signal_count: int = Field(default=0, ge=0)
    missing_signal_names: list[str] = Field(default_factory=list)
    stale_signal_names: list[str] = Field(default_factory=list)
    live_network_calls_made: bool = False
    limitations: list[str] = Field(default_factory=list)


class SafetyGatePrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class SafetyGateBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_only: bool = True
    reducer_required: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    direct_phase1_mutation_performed: bool = False
    direct_safety_api_call_allowed: bool = False
    direct_safety_api_call_performed: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_reducer_boundary(self) -> "SafetyGateBoundary":
        if not self.reducer_required:
            raise ValueError("runtime safety gate events must require reducer review")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
            or self.direct_phase1_mutation_performed
        ):
            raise ValueError("runtime safety gate events cannot mutate or own Phase 1 safety truth")
        if (
            self.direct_safety_api_call_allowed
            or self.direct_safety_api_call_performed
            or self.safety_api_called
        ):
            raise ValueError("runtime safety gate events cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("runtime safety gate events cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("runtime safety gate events cannot be medical diagnoses")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("runtime safety gate events cannot share raw private payloads")
        return self


class ScoutRuntimeSafetyGateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_gate_event"
    artifact_version: str = "runtime_safety_gate_event.v1"
    gate_id: SafetyGateId
    event_id: str = Field(min_length=1)
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    source_gate_artifact_kind: str | None = None
    source_gate_sha256: str | None = None
    observed_at_offset_s: int = Field(default=0, ge=0)
    state_candidate: str = Field(min_length=1)
    severity: SafetyGateSeverity = "none"
    ln_transition_candidate: SafetyLnTransitionCandidate = "none"
    ln_level_candidate: SafetyLnLevelCandidate | None = None
    required_action: str = "continue_monitoring"
    confidence: SafetyGateConfidence = "low"
    reducer_required: bool = True
    route_pressure_review_required: bool = False
    eta_delay_minutes: int = Field(default=0, ge=0)
    dominant_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    data_quality: SafetyGateDataQuality = Field(default_factory=SafetyGateDataQuality)
    privacy: SafetyGatePrivacy = Field(default_factory=SafetyGatePrivacy)
    boundary: SafetyGateBoundary = Field(default_factory=SafetyGateBoundary)
    gate_payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_event_contract(self) -> "ScoutRuntimeSafetyGateEvent":
        if not self.reducer_required:
            raise ValueError("runtime safety gate events must require reducer review")
        minimum_transition = _MIN_TRANSITION_BY_SEVERITY[self.severity]
        if _transition_rank(self.ln_transition_candidate) < _transition_rank(minimum_transition):
            raise ValueError("ln_transition_candidate is weaker than severity requires")
        expected_level = _LN_LEVEL_BY_TRANSITION[self.ln_transition_candidate]
        if self.ln_level_candidate is None:
            self.ln_level_candidate = expected_level
        elif self.ln_level_candidate != expected_level:
            raise ValueError("ln_level_candidate must match ln_transition_candidate")
        forbidden_paths = _forbidden_key_paths(
            {
                "route_context": self.route_context.model_dump(mode="json"),
                "gate_payload": self.gate_payload,
            }
        )
        if forbidden_paths:
            raise ValueError(f"forbidden raw safety gate fields present: {', '.join(forbidden_paths)}")
        if self.boundary.reducer_required is not True:
            raise ValueError("boundary.reducer_required must be true")
        if self.privacy.raw_health_payload_shared or self.privacy.precise_timestamps_shared:
            raise ValueError("safety gate event privacy flags are invalid")
        return self


class ScoutRuntimeSafetyGateEventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_gate_event_batch"
    artifact_version: str = "runtime_safety_gate_event_batch.v1"
    source_provider: str = "scout_runtime_safety_gate_models"
    source_path: str
    sha256: str
    event_count: int = Field(ge=0)
    events: list[ScoutRuntimeSafetyGateEvent]
    data_quality: SafetyGateDataQuality = Field(default_factory=SafetyGateDataQuality)
    privacy: SafetyGatePrivacy = Field(default_factory=SafetyGatePrivacy)
    boundary: SafetyGateBoundary = Field(default_factory=SafetyGateBoundary)

    @model_validator(mode="after")
    def enforce_batch(self) -> "ScoutRuntimeSafetyGateEventBatch":
        if self.event_count != len(self.events):
            raise ValueError("event_count must match events")
        return self


def build_runtime_safety_gate_event(
    *,
    gate_id: SafetyGateId,
    event_id: str,
    source_provider: str,
    source_path: str,
    state_candidate: str,
    severity: SafetyGateSeverity,
    ln_transition_candidate: SafetyLnTransitionCandidate,
    required_action: str,
    observed_at_offset_s: int = 0,
    confidence: SafetyGateConfidence = "low",
    source_gate_artifact_kind: str | None = None,
    source_gate_sha256: str | None = None,
    route_pressure_review_required: bool = False,
    eta_delay_minutes: int = 0,
    dominant_reasons: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    route_context: SafetyGateRouteContext | dict[str, Any] | None = None,
    data_quality: SafetyGateDataQuality | dict[str, Any] | None = None,
    privacy: SafetyGatePrivacy | dict[str, Any] | None = None,
    boundary: SafetyGateBoundary | dict[str, Any] | None = None,
    gate_payload: dict[str, Any] | None = None,
) -> ScoutRuntimeSafetyGateEvent:
    route_model = _route_context_model(route_context)
    data_quality_model = _data_quality_model(data_quality, confidence=confidence)
    privacy_model = _privacy_model(privacy)
    boundary_model = _boundary_model(boundary)
    normalized_evidence_refs = _unique_string_list(evidence_refs or [])
    normalized_reasons = _unique_string_list(dominant_reasons or [])
    payload = gate_payload or {}
    digest = aggregate_sha256(
        [
            {
                "gate_id": gate_id,
                "event_id": event_id,
                "source_provider": source_provider,
                "source_path": source_path,
                "source_gate_sha256": source_gate_sha256,
                "observed_at_offset_s": observed_at_offset_s,
                "state_candidate": state_candidate,
                "severity": severity,
                "ln_transition_candidate": ln_transition_candidate,
                "required_action": required_action,
                "route_context": route_model.model_dump(mode="json"),
                "evidence_refs": normalized_evidence_refs,
                "gate_payload": payload,
            }
        ]
    )
    return ScoutRuntimeSafetyGateEvent(
        gate_id=gate_id,
        event_id=event_id,
        source_provider=source_provider,
        source_path=source_path,
        sha256=digest,
        source_gate_artifact_kind=source_gate_artifact_kind,
        source_gate_sha256=source_gate_sha256,
        observed_at_offset_s=observed_at_offset_s,
        state_candidate=state_candidate,
        severity=severity,
        ln_transition_candidate=ln_transition_candidate,
        required_action=required_action,
        confidence=confidence,
        route_pressure_review_required=route_pressure_review_required,
        eta_delay_minutes=eta_delay_minutes,
        dominant_reasons=normalized_reasons,
        evidence_refs=normalized_evidence_refs,
        route_context=route_model,
        data_quality=data_quality_model,
        privacy=privacy_model,
        boundary=boundary_model,
        gate_payload=payload,
    )


def runtime_safety_gate_event_from_physiologic(
    event: PhysiologicSafetyGateEvent | dict[str, Any],
    *,
    route_context: SafetyGateRouteContext | dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> ScoutRuntimeSafetyGateEvent:
    physio_event = (
        event
        if isinstance(event, PhysiologicSafetyGateEvent)
        else PhysiologicSafetyGateEvent.model_validate(event)
    )
    refs = _unique_string_list(
        [
            *(evidence_refs or []),
            physio_event.event_id,
            physio_event.source_path,
            physio_event.sha256,
            physio_event.source_gate_sha256,
        ]
    )
    route_model = _route_context_model(route_context)
    confidence = _confidence_from_physio_quality(physio_event.data_quality)
    return build_runtime_safety_gate_event(
        gate_id="physiologic_gate",
        event_id=f"runtime_safety_gate_event:{physio_event.event_id}",
        source_provider=physio_event.source_provider,
        source_path=physio_event.source_path,
        source_gate_artifact_kind=physio_event.artifact_kind,
        source_gate_sha256=physio_event.source_gate_sha256,
        observed_at_offset_s=physio_event.observed_at_offset_s,
        state_candidate=physio_event.state_candidate,
        severity=physio_event.severity,
        ln_transition_candidate=physio_event.ln_transition_candidate,
        required_action=physio_event.required_action,
        confidence=confidence,
        route_pressure_review_required=physio_event.route_pressure_review_required,
        eta_delay_minutes=physio_event.eta_delay_minutes,
        dominant_reasons=physio_event.dominant_reasons,
        evidence_refs=refs,
        route_context=route_model,
        data_quality=SafetyGateDataQuality(
            confidence=confidence,
            signal_count=sum(
                1
                for key in (
                    "heart_rate_confidence",
                    "gps_confidence",
                    "provider_value_confidence",
                )
                if physio_event.data_quality.get(key) not in {None, "low"}
            ),
            limitations=[
                "converted from physiologic gate candidate event",
                "not Phase 1 safety truth until reducer applies policy",
            ],
        ),
        privacy=SafetyGatePrivacy(
            local_only=physio_event.privacy.local_only,
            raw_health_payload_shared=physio_event.privacy.raw_health_payload_shared,
            raw_track_shared=physio_event.privacy.raw_track_shared,
            precise_timestamps_shared=physio_event.privacy.exact_timestamps_shared,
            home_work_trace_shared=physio_event.privacy.home_work_trace_shared,
            shareable_by_default=physio_event.privacy.shareable_by_default,
        ),
        boundary=SafetyGateBoundary(),
        gate_payload={
            "physiologic_state_candidate": physio_event.state_candidate,
            "physiologic_severity": physio_event.severity,
            "route_pressure_review_required": physio_event.route_pressure_review_required,
            "safety_reducer_required": physio_event.safety_reducer_required,
        },
    )


def build_runtime_safety_gate_event_batch(
    events: list[ScoutRuntimeSafetyGateEvent | dict[str, Any]],
    *,
    source_path: str = "inline:runtime-safety-gate-events",
) -> ScoutRuntimeSafetyGateEventBatch:
    event_models = [
        event
        if isinstance(event, ScoutRuntimeSafetyGateEvent)
        else ScoutRuntimeSafetyGateEvent.model_validate(event)
        for event in events
    ]
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "events": [event.model_dump(mode="json") for event in event_models],
            }
        ]
    )
    return ScoutRuntimeSafetyGateEventBatch(
        source_path=source_path,
        sha256=digest,
        event_count=len(event_models),
        events=event_models,
        data_quality=SafetyGateDataQuality(
            confidence=_max_confidence([event.data_quality.confidence for event in event_models]),
            signal_count=sum(event.data_quality.signal_count for event in event_models),
            limitations=[
                "batch is reducer input only",
                "does not mutate Phase 1 safety state",
            ],
        ),
        privacy=SafetyGatePrivacy(),
        boundary=SafetyGateBoundary(),
    )


def write_runtime_safety_gate_event(
    event: ScoutRuntimeSafetyGateEvent,
    output_path: Path | str,
) -> ScoutRuntimeSafetyGateEvent:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(event.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ScoutRuntimeSafetyGateEvent.model_validate_json(path.read_text(encoding="utf-8"))


def load_runtime_safety_gate_event(path: Path | str) -> ScoutRuntimeSafetyGateEvent:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(path)
    payload["sha256"] = payload.get("sha256") or sha256_file(Path(path).expanduser())
    return ScoutRuntimeSafetyGateEvent.model_validate(payload)


def _route_context_model(value: SafetyGateRouteContext | dict[str, Any] | None) -> SafetyGateRouteContext:
    if isinstance(value, SafetyGateRouteContext):
        return value
    return SafetyGateRouteContext.model_validate(value or {})


def _data_quality_model(
    value: SafetyGateDataQuality | dict[str, Any] | None,
    *,
    confidence: SafetyGateConfidence,
) -> SafetyGateDataQuality:
    if isinstance(value, SafetyGateDataQuality):
        return value
    payload = dict(value or {})
    payload.setdefault("confidence", confidence)
    return SafetyGateDataQuality.model_validate(payload)


def _privacy_model(value: SafetyGatePrivacy | dict[str, Any] | None) -> SafetyGatePrivacy:
    if isinstance(value, SafetyGatePrivacy):
        return value
    return SafetyGatePrivacy.model_validate(value or {})


def _boundary_model(value: SafetyGateBoundary | dict[str, Any] | None) -> SafetyGateBoundary:
    if isinstance(value, SafetyGateBoundary):
        return value
    return SafetyGateBoundary.model_validate(value or {})


def _confidence_from_physio_quality(data_quality: dict[str, Any]) -> SafetyGateConfidence:
    return _max_confidence(
        [
            data_quality.get("heart_rate_confidence"),
            data_quality.get("gps_confidence"),
            data_quality.get("provider_value_confidence"),
        ]
    )


def _max_confidence(values: list[Any]) -> SafetyGateConfidence:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


def _transition_rank(value: str) -> int:
    order = {
        "none": 0,
        "candidate_watch": 1,
        "candidate_rest": 2,
        "candidate_retreat": 3,
        "candidate_alert_review": 4,
    }
    return order.get(value, 0)


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
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _unique_string_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
