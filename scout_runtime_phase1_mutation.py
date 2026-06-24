from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safety_models import (
    SafetyEvent,
    SafetyEventType,
    SafetyLevel,
    SafetyState,
    SafetyTransition,
)
from safety_state_machine import SafetyStateMachine
from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyLnLevelCandidate,
    SafetyLnTransitionCandidate,
)
from scout_runtime_safety_reducer import (
    RuntimeSafetyPhase1AdapterResult,
    RuntimeSafetyReducerDecision,
    RuntimeSafetyReducerDataQuality,
)
from scout_runtime_safety_state_store import RuntimeSafetyStateSnapshot
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


Phase1MutationStatus = Literal["applied_transition", "accepted_no_transition"]

_PHASE1_LEVEL_BY_CANDIDATE: dict[str, SafetyLevel] = {
    "L0_NORMAL": SafetyLevel.NORMAL,
    "L1_CAUTION": SafetyLevel.WATCH,
    "L2_CONCERN": SafetyLevel.CONCERN,
    "L3_RETREAT": SafetyLevel.DISTRESS,
    "L4_ALERT_REVIEW": SafetyLevel.EMERGENCY,
}
_EVENT_TYPE_BY_GATE: dict[str, SafetyEventType] = {
    "pace_gate": SafetyEventType.PACE_PRESSURE,
    "delay_gate": SafetyEventType.DELAY_PRESSURE,
    "physiologic_gate": SafetyEventType.PHYSIOLOGIC_PRESSURE,
    "weather_gate": SafetyEventType.WEATHER_THREAT,
    "darkness_gate": SafetyEventType.DARKNESS_RISK,
    "environment_threat_gate": SafetyEventType.ENVIRONMENT_THREAT,
}
_CONFIDENCE_SCORE: dict[str, float] = {"low": 0.45, "medium": 0.7, "high": 0.9}
_PHASE1_STATE_MACHINE_ALLOWED_KEYS = {"timestamp"}


class Phase1TransitionPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False

    @model_validator(mode="after")
    def enforce_privacy(self) -> "Phase1TransitionPrivacy":
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("Phase 1 mutation artifacts cannot share raw private payloads")
        return self


class Phase1TransitionDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: SafetyGateConfidence = "low"
    gate_event_count: int = Field(default=0, ge=0)
    contributing_gate_count: int = Field(default=0, ge=0)
    missing_gate_ids: list[str] = Field(default_factory=list)
    stale_signal_names: list[str] = Field(default_factory=list)
    live_network_calls_made: bool = False
    limitations: list[str] = Field(default_factory=list)

    @classmethod
    def from_reducer(
        cls,
        data_quality: RuntimeSafetyReducerDataQuality,
        *,
        extra_limitations: list[str] | None = None,
    ) -> "Phase1TransitionDataQuality":
        return cls(
            confidence=data_quality.confidence,
            gate_event_count=data_quality.gate_event_count,
            contributing_gate_count=data_quality.contributing_gate_count,
            missing_gate_ids=data_quality.missing_gate_ids,
            stale_signal_names=data_quality.stale_signal_names,
            live_network_calls_made=data_quality.live_network_calls_made,
            limitations=[
                *data_quality.limitations,
                *(extra_limitations or []),
            ],
        )


class Phase1TransitionRequestBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reducer_owned: bool = True
    individual_gate_owned: bool = False
    transition_request_only: bool = True
    deterministic_writer_required: bool = True
    phase1_runtime_mutation_requested: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_request_boundary(self) -> "Phase1TransitionRequestBoundary":
        if not self.reducer_owned or self.individual_gate_owned:
            raise ValueError("Phase 1 transition requests must be reducer-owned")
        if not self.transition_request_only or not self.deterministic_writer_required:
            raise ValueError("Phase 1 transition request must require deterministic writer")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("Phase 1 transition request cannot claim mutation already happened")
        if self.safety_api_called:
            raise ValueError("Phase 1 transition request cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("Phase 1 transition request cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("Phase 1 transition request cannot be a medical diagnosis")
        _raise_if_private_payload_shared(self)
        return self


class Phase1MutationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reducer_owned: bool = True
    deterministic_writer: bool = True
    phase1_runtime_safety_truth: bool = True
    phase1_l0_l4_state_mutated: bool = True
    safety_state_machine_applied: bool = True
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    outbound_policy_separate: bool = True
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_mutation_boundary(self) -> "Phase1MutationBoundary":
        if not (
            self.reducer_owned
            and self.deterministic_writer
            and self.phase1_runtime_safety_truth
            and self.phase1_l0_l4_state_mutated
            and self.safety_state_machine_applied
        ):
            raise ValueError("Phase 1 mutation result must be deterministic runtime truth")
        if self.safety_api_called:
            raise ValueError("Phase 1 mutation service cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("Phase 1 mutation service cannot send outbound alerts")
        if not self.outbound_policy_separate:
            raise ValueError("outbound policy must stay separate from Phase 1 mutation")
        if self.medical_diagnosis:
            raise ValueError("Phase 1 mutation result cannot be a medical diagnosis")
        _raise_if_private_payload_shared(self)
        return self


class Phase1TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_transition_request"
    artifact_version: str = "phase1_transition_request.v1"
    request_id: str = Field(min_length=1)
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    reducer_sha256: str = Field(min_length=1)
    reducer_source_path: str = Field(min_length=1)
    adapter_sha256: str = Field(min_length=1)
    adapter_source_path: str = Field(min_length=1)
    state_snapshot_id: str | None = None
    state_snapshot_sha256: str | None = None
    selected_gate_id: str = Field(min_length=1)
    selected_event_sha256: str | None = None
    contributing_gate_ids: list[str] = Field(default_factory=list)
    corroborating_gate_ids: list[str] = Field(default_factory=list)
    suppressed_gate_ids: list[str] = Field(default_factory=list)
    requested_ln_level_candidate: SafetyLnLevelCandidate
    requested_ln_transition_candidate: SafetyLnTransitionCandidate
    target_safety_level: SafetyLevel
    target_event_type: SafetyEventType
    reducer_recommendation: str
    event_time_offset_s: float = Field(default=0.0, ge=0.0)
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    route_id: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    map_target_ids: list[str] = Field(default_factory=list)
    eta_delay_minutes: int = Field(default=0, ge=0)
    route_pressure_review_required: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    data_quality: Phase1TransitionDataQuality = Field(
        default_factory=Phase1TransitionDataQuality
    )
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1TransitionRequestBoundary = Field(
        default_factory=Phase1TransitionRequestBoundary
    )

    @model_validator(mode="after")
    def enforce_request(self) -> "Phase1TransitionRequest":
        expected_level = _PHASE1_LEVEL_BY_CANDIDATE[self.requested_ln_level_candidate]
        if self.target_safety_level != expected_level:
            raise ValueError("target safety level must match requested L_n candidate")
        if self.target_event_type != _EVENT_TYPE_BY_GATE.get(
            self.selected_gate_id,
            SafetyEventType.UNSAFE_CONTINUATION,
        ):
            raise ValueError("target event type must match selected gate")
        if not self.contributing_gate_ids:
            raise ValueError("Phase 1 transition request requires contributing gates")
        if self.selected_gate_id not in self.contributing_gate_ids:
            raise ValueError("selected gate must be a contributing gate")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 transition request fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1MutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_safety_mutation_result"
    artifact_version: str = "phase1_safety_mutation_result.v1"
    mutation_id: str = Field(min_length=1)
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    status: Phase1MutationStatus
    previous_safety_level: SafetyLevel
    resulting_safety_level: SafetyLevel
    transition_performed: bool
    safety_event: SafetyEvent
    transition: SafetyTransition | None = None
    safety_state: SafetyState
    data_quality: Phase1TransitionDataQuality = Field(
        default_factory=Phase1TransitionDataQuality
    )
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1MutationBoundary = Field(default_factory=Phase1MutationBoundary)

    @model_validator(mode="after")
    def enforce_result(self) -> "Phase1MutationResult":
        if self.transition_performed != (self.transition is not None):
            raise ValueError("transition_performed must match transition presence")
        if self.resulting_safety_level != self.safety_state.level:
            raise ValueError("resulting safety level must match safety state")
        if self.status == "applied_transition" and not self.transition_performed:
            raise ValueError("applied_transition requires a transition")
        if self.status == "accepted_no_transition" and self.transition_performed:
            raise ValueError("accepted_no_transition cannot include a transition")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden Phase 1 mutation result fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class Phase1MutationAuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_id: str = Field(min_length=1)
    mutation_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    request_sha256: str = Field(min_length=1)
    status: Phase1MutationStatus
    previous_safety_level: SafetyLevel
    resulting_safety_level: SafetyLevel
    transition_performed: bool
    event_type: SafetyEventType


class Phase1MutationAuditIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_safety_mutation_audit_index"
    artifact_version: str = "phase1_safety_mutation_audit_index.v1"
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    mutation_count: int = Field(ge=0)
    latest_mutation_id: str | None = None
    latest_safety_level: SafetyLevel | None = None
    mutations: list[Phase1MutationAuditSummary] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1MutationBoundary | None = None

    @model_validator(mode="after")
    def enforce_index(self) -> "Phase1MutationAuditIndex":
        if self.mutation_count != len(self.mutations):
            raise ValueError("mutation_count must match mutations")
        if self.mutations:
            latest = self.mutations[-1]
            if self.latest_mutation_id != latest.mutation_id:
                raise ValueError("latest mutation id must match last audit summary")
            if self.latest_safety_level != latest.resulting_safety_level:
                raise ValueError("latest safety level must match last audit summary")
        elif self.latest_mutation_id is not None or self.latest_safety_level is not None:
            raise ValueError("empty mutation audit cannot declare latest fields")
        return self


class Phase1MutationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_safety_mutation_projection"
    artifact_version: str = "phase1_safety_mutation_projection.v1"
    status: Literal["ready", "missing", "error"]
    project_id: str
    source_provider: str = "scout_runtime_phase1_mutation"
    source_path: str = ""
    sha256: str | None = None
    latest_mutation_id: str | None = None
    latest_safety_level: SafetyLevel | None = None
    mutation_count: int = Field(default=0, ge=0)
    surface_targets: list[str] = Field(default_factory=lambda: ["/admin/debug", "/admin"])
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    privacy: Phase1TransitionPrivacy = Field(default_factory=Phase1TransitionPrivacy)
    boundary: Phase1MutationBoundary | None = None
    error_type: str | None = None
    error: str | None = None


class Phase1SafetyMutationService:
    def __init__(self, initial_state: SafetyState | None = None) -> None:
        self.state_machine = SafetyStateMachine(initial_state)

    def apply_transition_request(
        self,
        request: Phase1TransitionRequest | dict[str, Any],
        *,
        source_path: str = "inline:phase1-safety-mutation-result",
    ) -> Phase1MutationResult:
        request_model = (
            request
            if isinstance(request, Phase1TransitionRequest)
            else Phase1TransitionRequest.model_validate(request)
        )
        event = safety_event_from_phase1_transition_request(request_model)
        previous_level = self.state_machine.state.level
        transition = self.state_machine.apply_event(event)
        resulting_level = self.state_machine.state.level
        status: Phase1MutationStatus = (
            "applied_transition" if transition is not None else "accepted_no_transition"
        )
        mutation_id = _mutation_id(request_model, previous_level, resulting_level)
        digest = aggregate_sha256(
            [
                {
                    "mutation_id": mutation_id,
                    "source_path": source_path,
                    "request_sha256": request_model.sha256,
                    "previous_level": previous_level.value,
                    "resulting_level": resulting_level.value,
                    "transition_performed": transition is not None,
                }
            ]
        )
        return Phase1MutationResult(
            mutation_id=mutation_id,
            source_path=source_path,
            sha256=digest,
            request_id=request_model.request_id,
            request_sha256=request_model.sha256,
            status=status,
            previous_safety_level=previous_level,
            resulting_safety_level=resulting_level,
            transition_performed=transition is not None,
            safety_event=event,
            transition=transition,
            safety_state=self.state_machine.state,
            data_quality=request_model.data_quality,
        )


class Phase1MutationAuditStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.mutations_dir = self.root / "mutations"
        self.index_path = self.root / "phase1_safety_mutation_audit_index.json"
        self.mutations_dir.mkdir(parents=True, exist_ok=True)

    def save_result(
        self,
        result: Phase1MutationResult | dict[str, Any],
    ) -> Phase1MutationResult:
        result_model = (
            result
            if isinstance(result, Phase1MutationResult)
            else Phase1MutationResult.model_validate(result)
        )
        path = self.path_for(result_model.mutation_id)
        _atomic_write_json(path, result_model.model_dump(mode="json"))
        self.write_index()
        return self.load_result(result_model.mutation_id)

    def load_result(self, mutation_id: str) -> Phase1MutationResult:
        return load_phase1_mutation_result(self.path_for(mutation_id))

    def list_results(self) -> list[Phase1MutationResult]:
        return [
            load_phase1_mutation_result(path)
            for path in sorted(self.mutations_dir.glob("*.json"))
        ]

    def write_index(self) -> Phase1MutationAuditIndex:
        index = build_phase1_mutation_audit_index(
            self.list_results(),
            source_path=_relative_or_string(self.index_path, self.root),
        )
        _atomic_write_json(self.index_path, index.model_dump(mode="json"))
        return load_phase1_mutation_audit_index(self.index_path)

    def load_index(self) -> Phase1MutationAuditIndex:
        if not self.index_path.exists():
            return self.write_index()
        return load_phase1_mutation_audit_index(self.index_path)

    def path_for(self, mutation_id: str) -> Path:
        return self.mutations_dir / f"{mutation_id}.json"


def build_phase1_transition_request(
    reducer_decision: RuntimeSafetyReducerDecision | dict[str, Any],
    adapter_result: RuntimeSafetyPhase1AdapterResult | dict[str, Any],
    *,
    state_snapshot: RuntimeSafetyStateSnapshot | dict[str, Any] | None = None,
    source_path: str = "inline:phase1-transition-request",
    event_time_offset_s: float = 0.0,
) -> Phase1TransitionRequest:
    reducer = (
        reducer_decision
        if isinstance(reducer_decision, RuntimeSafetyReducerDecision)
        else RuntimeSafetyReducerDecision.model_validate(reducer_decision)
    )
    adapter = (
        adapter_result
        if isinstance(adapter_result, RuntimeSafetyPhase1AdapterResult)
        else RuntimeSafetyPhase1AdapterResult.model_validate(adapter_result)
    )
    snapshot = (
        None
        if state_snapshot is None
        else state_snapshot
        if isinstance(state_snapshot, RuntimeSafetyStateSnapshot)
        else RuntimeSafetyStateSnapshot.model_validate(state_snapshot)
    )
    if adapter.status != "transition_request_prepared":
        raise ValueError("Phase 1 transition request requires a prepared adapter")
    if adapter.selected_reducer_sha256 != reducer.sha256:
        raise ValueError("adapter result must reference reducer decision")
    if snapshot is not None and snapshot.reducer_sha256 != reducer.sha256:
        raise ValueError("state snapshot must reference reducer decision")
    if not reducer.selected_gate_id:
        raise ValueError("Phase 1 transition request requires selected gate")
    source_refs = _unique_string_list(
        [
            reducer.source_path,
            adapter.source_path,
            snapshot.source_path if snapshot else None,
        ]
    )
    map_target_ids = _unique_string_list(
        [
            target
            for summary in reducer.gate_summaries
            for target in summary.get("map_target_ids", [])
        ]
    )
    evidence_refs = _unique_string_list(
        [
            ref
            for summary in reducer.gate_summaries
            for ref in summary.get("evidence_refs", [])
        ]
    )
    reason = _mutation_reason(reducer)
    confidence = _CONFIDENCE_SCORE.get(reducer.data_quality.confidence, 0.45)
    target_level = _PHASE1_LEVEL_BY_CANDIDATE[reducer.ln_level_candidate]
    target_event_type = _EVENT_TYPE_BY_GATE.get(
        reducer.selected_gate_id,
        SafetyEventType.UNSAFE_CONTINUATION,
    )
    request_id = _request_id(reducer, adapter, snapshot)
    digest = aggregate_sha256(
        [
            {
                "request_id": request_id,
                "source_path": source_path,
                "reducer_sha256": reducer.sha256,
                "adapter_sha256": adapter.sha256,
                "snapshot_sha256": snapshot.sha256 if snapshot else None,
                "requested_ln_level": reducer.ln_level_candidate,
                "target_safety_level": target_level.value,
            }
        ]
    )
    return Phase1TransitionRequest(
        request_id=request_id,
        source_path=source_path,
        sha256=digest,
        reducer_sha256=reducer.sha256,
        reducer_source_path=reducer.source_path,
        adapter_sha256=adapter.sha256,
        adapter_source_path=adapter.source_path,
        state_snapshot_id=snapshot.snapshot_id if snapshot else None,
        state_snapshot_sha256=snapshot.sha256 if snapshot else None,
        selected_gate_id=reducer.selected_gate_id,
        selected_event_sha256=reducer.selected_event_sha256,
        contributing_gate_ids=reducer.contributing_gate_ids,
        corroborating_gate_ids=reducer.corroborating_gate_ids,
        suppressed_gate_ids=reducer.suppressed_gate_ids,
        requested_ln_level_candidate=reducer.ln_level_candidate,
        requested_ln_transition_candidate=reducer.ln_transition_candidate,
        target_safety_level=target_level,
        target_event_type=target_event_type,
        reducer_recommendation=reducer.recommendation,
        event_time_offset_s=event_time_offset_s,
        reason=reason,
        confidence=confidence,
        route_id=_first_summary_value(reducer, "route_id"),
        segment_id=_first_summary_value(reducer, "segment_id"),
        checkpoint_id=_first_summary_value(reducer, "checkpoint_id"),
        map_target_ids=map_target_ids,
        eta_delay_minutes=reducer.eta_delay_minutes,
        route_pressure_review_required=reducer.route_pressure_review_required,
        evidence_refs=evidence_refs,
        source_refs=source_refs,
        data_quality=Phase1TransitionDataQuality.from_reducer(
            reducer.data_quality,
            extra_limitations=[
                "Phase 1 transition request is local deterministic handoff",
                "outbound policy remains separate",
            ],
        ),
    )


def safety_event_from_phase1_transition_request(
    request: Phase1TransitionRequest | dict[str, Any],
) -> SafetyEvent:
    request_model = (
        request
        if isinstance(request, Phase1TransitionRequest)
        else Phase1TransitionRequest.model_validate(request)
    )
    details = {
        "phase1_transition_request_id": request_model.request_id,
        "phase1_transition_request_sha256": request_model.sha256,
        "reducer_sha256": request_model.reducer_sha256,
        "adapter_sha256": request_model.adapter_sha256,
        "selected_gate_id": request_model.selected_gate_id,
        "contributing_gate_ids": request_model.contributing_gate_ids,
        "corroborating_gate_ids": request_model.corroborating_gate_ids,
        "suppressed_gate_ids": request_model.suppressed_gate_ids,
        "route_id": request_model.route_id,
        "segment_id": request_model.segment_id,
        "checkpoint_id": request_model.checkpoint_id,
        "map_target_ids": request_model.map_target_ids,
        "eta_delay_minutes": request_model.eta_delay_minutes,
        "route_pressure_review_required": request_model.route_pressure_review_required,
        "source_refs": request_model.source_refs,
        "privacy": request_model.privacy.model_dump(mode="json"),
        "boundary": {
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "medical_diagnosis": False,
            "raw_health_payload_shared": False,
            "precise_timestamps_shared": False,
        },
    }
    return SafetyEvent(
        event_type=request_model.target_event_type,
        level=request_model.target_safety_level,
        timestamp=request_model.event_time_offset_s,
        reason=request_model.reason,
        confidence=request_model.confidence,
        details=details,
    )


def write_phase1_transition_request(
    request: Phase1TransitionRequest,
    output_path: Path | str,
) -> Phase1TransitionRequest:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, request.model_dump(mode="json"))
    return load_phase1_transition_request(path)


def load_phase1_transition_request(path: Path | str) -> Phase1TransitionRequest:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1TransitionRequest.model_validate(payload)


def write_phase1_mutation_result(
    result: Phase1MutationResult,
    output_path: Path | str,
) -> Phase1MutationResult:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, result.model_dump(mode="json"))
    return load_phase1_mutation_result(path)


def load_phase1_mutation_result(path: Path | str) -> Phase1MutationResult:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1MutationResult.model_validate(payload)


def build_phase1_mutation_audit_index(
    results: list[Phase1MutationResult | dict[str, Any]],
    *,
    source_path: str = "inline:phase1-mutation-audit-index",
) -> Phase1MutationAuditIndex:
    result_models = [
        result
        if isinstance(result, Phase1MutationResult)
        else Phase1MutationResult.model_validate(result)
        for result in results
    ]
    summaries = [_audit_summary(result) for result in result_models]
    latest = summaries[-1] if summaries else None
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "mutation_ids": [summary.mutation_id for summary in summaries],
                "mutation_hashes": [summary.sha256 for summary in summaries],
            }
        ]
    )
    return Phase1MutationAuditIndex(
        source_path=source_path,
        sha256=digest,
        mutation_count=len(summaries),
        latest_mutation_id=latest.mutation_id if latest else None,
        latest_safety_level=latest.resulting_safety_level if latest else None,
        mutations=summaries,
        boundary=Phase1MutationBoundary() if summaries else None,
    )


def write_phase1_mutation_audit_index(
    index: Phase1MutationAuditIndex,
    output_path: Path | str,
) -> Phase1MutationAuditIndex:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, index.model_dump(mode="json"))
    return load_phase1_mutation_audit_index(path)


def load_phase1_mutation_audit_index(path: Path | str) -> Phase1MutationAuditIndex:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return Phase1MutationAuditIndex.model_validate(payload)


def build_phase1_mutation_projection(
    project_id: str,
    *,
    project_root: Path | str,
    mutation_result_ref: str | None = None,
    mutation_audit_index_ref: str | None = None,
    shadow_replay_result_ref: str | None = None,
) -> Phase1MutationProjection:
    root = Path(project_root).expanduser()
    try:
        loaded = _load_projection_source(
            root,
            mutation_result_ref=mutation_result_ref,
            mutation_audit_index_ref=mutation_audit_index_ref,
            shadow_replay_result_ref=shadow_replay_result_ref,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return Phase1MutationProjection(
            status="error",
            project_id=project_id,
            source_path=str(
                mutation_result_ref
                or mutation_audit_index_ref
                or shadow_replay_result_ref
                or ""
            ),
            error_type=type(exc).__name__,
            error=str(exc),
        )
    if loaded is None:
        return Phase1MutationProjection(
            status="missing",
            project_id=project_id,
            source_path=str(
                mutation_result_ref
                or mutation_audit_index_ref
                or shadow_replay_result_ref
                or ""
            ),
        )
    source_path, result, index = loaded
    event = phase1_mutation_projection_event(result, sequence=0)
    digest = aggregate_sha256(
        [
            {
                "project_id": project_id,
                "source_path": source_path,
                "mutation_sha256": result.sha256,
                "index_sha256": index.sha256 if index else None,
            }
        ]
    )
    return Phase1MutationProjection(
        status="ready",
        project_id=project_id,
        source_path=source_path,
        sha256=digest,
        latest_mutation_id=result.mutation_id,
        latest_safety_level=result.resulting_safety_level,
        mutation_count=index.mutation_count if index else 1,
        timeline_events=[event],
        boundary=result.boundary,
    )


def phase1_mutation_projection_event(
    result: Phase1MutationResult,
    *,
    sequence: int,
) -> dict[str, Any]:
    severity = {
        SafetyLevel.NORMAL: "info",
        SafetyLevel.WATCH: "watch",
        SafetyLevel.CONCERN: "warning",
        SafetyLevel.DISTRESS: "critical",
        SafetyLevel.EMERGENCY: "critical",
    }[result.resulting_safety_level]
    return {
        "event_id": f"phase1_mutation.{result.mutation_id}",
        "sequence": sequence,
        "timestamp": "offset:phase1-safety-mutation",
        "kind": "phase1_safety_mutation_result",
        "label": result.resulting_safety_level.value,
        "severity": severity,
        "summary": result.safety_event.reason,
        "source_refs": [result.source_path],
        "map_refs": result.safety_event.details.get("map_target_ids", []),
        "payload": {
            "mutation_id": result.mutation_id,
            "request_id": result.request_id,
            "status": result.status,
            "previous_safety_level": result.previous_safety_level.value,
            "resulting_safety_level": result.resulting_safety_level.value,
            "transition_performed": result.transition_performed,
            "event_type": result.safety_event.event_type.value,
            "selected_gate_id": result.safety_event.details.get("selected_gate_id"),
            "boundary": result.boundary.model_dump(mode="json"),
            "privacy": result.privacy.model_dump(mode="json"),
        },
    }


def _audit_summary(result: Phase1MutationResult) -> Phase1MutationAuditSummary:
    return Phase1MutationAuditSummary(
        mutation_id=result.mutation_id,
        mutation_path=result.source_path,
        sha256=result.sha256,
        request_id=result.request_id,
        request_sha256=result.request_sha256,
        status=result.status,
        previous_safety_level=result.previous_safety_level,
        resulting_safety_level=result.resulting_safety_level,
        transition_performed=result.transition_performed,
        event_type=result.safety_event.event_type,
    )


def _request_id(
    reducer: RuntimeSafetyReducerDecision,
    adapter: RuntimeSafetyPhase1AdapterResult,
    snapshot: RuntimeSafetyStateSnapshot | None,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "reducer_sha256": reducer.sha256,
                "adapter_sha256": adapter.sha256,
                "snapshot_sha256": snapshot.sha256 if snapshot else None,
            }
        ]
    )
    return f"phase1_transition_request.{digest[:16]}"


def _mutation_id(
    request: Phase1TransitionRequest,
    previous_level: SafetyLevel,
    resulting_level: SafetyLevel,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "request_sha256": request.sha256,
                "previous_level": previous_level.value,
                "resulting_level": resulting_level.value,
            }
        ]
    )
    return f"phase1_safety_mutation.{digest[:16]}"


def _mutation_reason(reducer: RuntimeSafetyReducerDecision) -> str:
    selected_gate = reducer.selected_gate_id or "runtime_safety_reducer"
    reasons = [
        summary.get("state_candidate")
        for summary in reducer.gate_summaries
        if summary.get("sha256") == reducer.selected_event_sha256
    ]
    reason = str(reasons[0]) if reasons else reducer.recommendation
    return (
        f"{selected_gate} requested {reducer.ln_level_candidate} via "
        f"{reducer.recommendation}: {reason}"
    )


def _first_summary_value(
    reducer: RuntimeSafetyReducerDecision,
    key: str,
) -> str | None:
    selected = [
        summary
        for summary in reducer.gate_summaries
        if summary.get("sha256") == reducer.selected_event_sha256
    ]
    candidates = selected or reducer.gate_summaries
    for summary in candidates:
        value = summary.get(key)
        if value:
            return str(value)
    return None


def _load_projection_source(
    root: Path,
    *,
    mutation_result_ref: str | None,
    mutation_audit_index_ref: str | None,
    shadow_replay_result_ref: str | None,
) -> tuple[str, Phase1MutationResult, Phase1MutationAuditIndex | None] | None:
    if mutation_result_ref:
        path = root / mutation_result_ref
        return mutation_result_ref, load_phase1_mutation_result(path), None
    if mutation_audit_index_ref:
        index_path = root / mutation_audit_index_ref
        index = load_phase1_mutation_audit_index(index_path)
        if not index.mutations:
            return None
        latest = index.mutations[-1]
        result_path = index_path.parent / latest.mutation_path
        if not result_path.exists():
            result_path = index_path.parent / "mutations" / f"{latest.mutation_id}.json"
        return (
            mutation_audit_index_ref,
            load_phase1_mutation_result(result_path),
            index,
        )
    if shadow_replay_result_ref:
        shadow_path = root / shadow_replay_result_ref
        payload = json.loads(shadow_path.read_text(encoding="utf-8"))
        result_payload = payload.get("phase1_mutation_result")
        if not result_payload:
            return None
        index_payload = payload.get("phase1_mutation_audit_index")
        index = (
            Phase1MutationAuditIndex.model_validate(index_payload)
            if index_payload
            else None
        )
        return (
            f"{shadow_replay_result_ref}#phase1_mutation_result",
            Phase1MutationResult.model_validate(result_payload),
            index,
        )
    return None


def _raise_if_private_payload_shared(value: Any) -> None:
    if (
        getattr(value, "raw_health_payload_shared", False)
        or getattr(value, "raw_track_shared", False)
        or getattr(value, "raw_gpx_shared", False)
        or getattr(value, "precise_timestamps_shared", False)
        or getattr(value, "home_work_trace_shared", False)
    ):
        raise ValueError("Phase 1 mutation artifacts cannot share raw private payloads")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _relative_or_string(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            lower_key = str(key).lower()
            if (
                lower_key in FORBIDDEN_RAW_KEYS
                and lower_key not in _PHASE1_STATE_MACHINE_ALLOWED_KEYS
            ):
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
