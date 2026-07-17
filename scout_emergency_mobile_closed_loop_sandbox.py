from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event
from scout_runtime_shadow_replay import run_runtime_shadow_replay
from scout_sensorlogger_mqtt_observer import (
    SensorLoggerMqttObserver,
    SensorLoggerMqttObserverConfig,
)


SandboxDecision = Literal[
    "agree_send",
    "do_not_send",
    "review_again_5_minutes",
    "review_again_10_minutes",
    "current_condition_ok_downgrade_request",
    "immediate_phone_call",
    "manual_copy_emergency_packet",
    "retreat_or_emergency_camp",
    "message_draft",
    "voice_call_script",
]
SandboxSimulationOutcome = Literal[
    "simulated_receipt_recorded",
    "simulated_rejected",
    "simulated_timeout",
]

_SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
_GATE_IDS = (
    "pace_gate",
    "delay_gate",
    "physiologic_gate",
    "weather_gate",
    "darkness_gate",
    "environment_threat_gate",
)


class ClosedLoopSandboxError(RuntimeError):
    pass


class ClosedLoopSandboxBoundaryError(ClosedLoopSandboxError):
    pass


class ClosedLoopSandboxConflict(ClosedLoopSandboxError):
    pass


class SandboxBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    synthetic_scenario: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    real_outbound_send_performed: bool = False
    production_transport_invoked: bool = False
    hardware_control_invoked: bool = False
    network_mqtt_publish_performed: bool = False
    precise_real_user_location_embedded: bool = False
    raw_health_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_sandbox_boundary(self) -> "SandboxBoundary":
        if not self.local_only or not self.synthetic_scenario or not self.candidate_only:
            raise ValueError("closed-loop sandbox must remain local synthetic candidate evidence")
        prohibited = (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.real_outbound_send_performed
            or self.production_transport_invoked
            or self.hardware_control_invoked
            or self.network_mqtt_publish_performed
            or self.precise_real_user_location_embedded
            or self.raw_health_payload_embedded
        )
        if prohibited:
            raise ValueError("closed-loop sandbox boundary cannot claim production effects")
        return self


class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(
        default="sandbox-ridge-distress-v0",
        min_length=1,
        max_length=128,
        pattern=_SAFE_ID_PATTERN,
    )
    run_id: str = Field(
        default="run-001",
        min_length=1,
        max_length=128,
        pattern=_SAFE_ID_PATTERN,
    )
    project_id: str = Field(
        default="chilai_nanhua_day1_scoutAI",
        min_length=1,
        max_length=128,
        pattern=_SAFE_ID_PATTERN,
    )
    source_mode: Literal["synthetic_replay"] = "synthetic_replay"
    profile: Literal["ridge_distress"] = "ridge_distress"
    observed_at: str = "2026-07-17T02:00:00Z"
    confirm_sandbox_run: bool = False


class SandboxApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=_SAFE_ID_PATTERN)
    packet_id: str = Field(pattern=_SAFE_ID_PATTERN)
    packet_sha256: str = Field(min_length=1, max_length=128)
    decision: SandboxDecision
    idempotency_key: str = Field(pattern=_SAFE_ID_PATTERN)
    confirm_sandbox_action: bool = False


class SandboxTransportSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=_SAFE_ID_PATTERN)
    attempt_id: str = Field(pattern=_SAFE_ID_PATTERN)
    attempt_sha256: str = Field(min_length=1, max_length=128)
    packet_id: str = Field(pattern=_SAFE_ID_PATTERN)
    packet_sha256: str = Field(min_length=1, max_length=128)
    outcome: SandboxSimulationOutcome
    idempotency_key: str = Field(pattern=_SAFE_ID_PATTERN)
    confirm_simulated_transport: bool = False


class SandboxScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    run_id: str
    project_id: str
    source_mode: Literal["synthetic_replay"]
    profile: Literal["ridge_distress"]
    observed_at: str


class SandboxIngressProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: str = "SensorLoggerMqttObserver.handle_message"
    mode: Literal["synthetic_direct_feed"] = "synthetic_direct_feed"
    transport_contract: str = "sensorlogger_over_mqtt"
    topic_ref: str
    accepted_message_count: int = Field(ge=0)
    invalid_message_count: int = Field(ge=0)
    device_count: int = Field(ge=0)
    sensor_names: list[str] = Field(default_factory=list)
    latest_ingress_id: str | None = None
    observer_status_ref: str
    network_mqtt_publish_performed: bool = False
    broker_connection_verified: bool = False


class SandboxEvaluationInputRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    record_hash: str
    device_id: str
    sensor_names: list[str] = Field(default_factory=list)


class SandboxEvaluationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_sandbox_evaluation_snapshot"
    artifact_version: str = "emergency_mobile_sandbox_evaluation_snapshot.v0"
    evaluation_snapshot_id: str
    sha256: str
    scenario_id: str
    scenario_revision: int = 1
    simulated_time: str
    input_records: list[SandboxEvaluationInputRecord]
    input_set_hash: str
    seal_reason: Literal["expected_synthetic_inputs_accepted"] = (
        "expected_synthetic_inputs_accepted"
    )
    gate_snapshot_ref: str
    reducer_ref: str
    candidate_only: bool = True
    runtime_safety_truth: bool = False

    @model_validator(mode="after")
    def enforce_snapshot(self) -> "SandboxEvaluationSnapshot":
        if len(self.input_records) != 2:
            raise ValueError("sandbox evaluation snapshot requires phone and wearable")
        if not self.candidate_only or self.runtime_safety_truth:
            raise ValueError("sandbox evaluation snapshot cannot claim runtime truth")
        return self


class SandboxRouteProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str
    segment_id: str
    checkpoint_id: str
    location_ref: str
    route_progress_m: float = Field(ge=0)
    distance_to_checkpoint_m: float = Field(ge=0)
    heading_deg: float = Field(ge=0, lt=360)
    horizontal_accuracy_m: float = Field(gt=0)
    fix_quality: Literal["fresh_synthetic_fix"] = "fresh_synthetic_fix"
    travel_direction: Literal["forward"] = "forward"
    source_ref: str


class SandboxGateProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    state_candidate: str
    severity: str
    ln_level_candidate: str
    confidence: str
    dominant_reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class SandboxSafetyProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_gate_id: str | None = None
    ln_level_candidate: str
    reducer_state: str
    recommendation: str
    reducer_sha256: str
    reducer_source_ref: str
    evaluation_snapshot_id: str
    evaluation_snapshot_sha256: str
    input_set_hash: str
    evaluation_snapshot_ref: str
    phase1_adapter_status: str
    gates: list[SandboxGateProjection]
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_l0_l4_state_mutated: bool = False


class SandboxTransportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["sms_text", "lora_compact", "mqtt_json"]
    status: Literal["draft_ready"] = "draft_ready"
    topic_ref: str | None = None
    summary: str
    sent: bool = False

    @model_validator(mode="after")
    def reject_sent_draft(self) -> "SandboxTransportDraft":
        if self.sent:
            raise ValueError("sandbox transport draft cannot be marked sent")
        return self


class SandboxAlertPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_sandbox_alert_candidate"
    artifact_version: str = "emergency_mobile_sandbox_alert_candidate.v0"
    packet_id: str
    sha256: str
    content_sha256: str
    scenario_id: str
    source_reducer_sha256: str
    source_reducer_ref: str
    source_evaluation_snapshot_id: str
    source_evaluation_snapshot_sha256: str
    source_input_set_hash: str
    safety_level_candidate: str
    selected_gate_id: str | None = None
    status: str = "pending_approval"
    location_ref: str
    summary: str
    requested_action: str
    transport_drafts: list[SandboxTransportDraft]
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    sent: bool = False

    @model_validator(mode="after")
    def reject_packet_effect_claims(self) -> "SandboxAlertPacket":
        if not self.candidate_only or self.runtime_safety_truth or self.sent:
            raise ValueError("sandbox alert packet cannot claim runtime truth or delivery")
        return self


class SandboxApprovalArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_sandbox_approval_action"
    artifact_version: str = "emergency_mobile_sandbox_approval_action.v0"
    approval_id: str
    sha256: str
    request_sha256: str
    scenario_id: str
    source_packet_id: str
    source_packet_sha256: str
    decision: SandboxDecision
    idempotency_key: str
    requested_transport: str
    external_send_requested: bool
    external_send_performed: bool = False
    phase1_mutation_requested: bool = False
    sent: bool = False

    @model_validator(mode="after")
    def reject_approval_effect_claims(self) -> "SandboxApprovalArtifact":
        if self.external_send_performed or self.phase1_mutation_requested or self.sent:
            raise ValueError("sandbox approval cannot claim an external effect")
        return self


class SandboxTransportAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_sandbox_transport_attempt"
    artifact_version: str = "emergency_mobile_sandbox_transport_attempt.v0"
    attempt_id: str
    sha256: str
    request_sha256: str
    scenario_id: str
    source_approval_id: str
    source_approval_sha256: str
    source_packet_id: str
    source_packet_sha256: str
    idempotency_key: str
    executor: str = "sandbox_transport_executor_v0"
    destination_alias: str = "synthetic_rescue_desk"
    attempted: bool = True
    simulated_transport: bool = True
    network_connection_attempted: bool = False
    production_transport_invoked: bool = False
    sent: bool = False

    @model_validator(mode="after")
    def reject_production_attempt_claims(self) -> "SandboxTransportAttempt":
        if (
            not self.simulated_transport
            or self.network_connection_attempted
            or self.production_transport_invoked
            or self.sent
        ):
            raise ValueError("sandbox attempt cannot claim a production transport effect")
        return self


class SandboxTransportSimulation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_sandbox_transport_simulation"
    artifact_version: str = "emergency_mobile_sandbox_transport_simulation.v0"
    simulation_id: str
    sha256: str
    request_sha256: str
    scenario_id: str
    source_attempt_id: str
    source_attempt_sha256: str
    source_packet_id: str
    source_packet_sha256: str
    outcome: SandboxSimulationOutcome
    idempotency_key: str
    executor: str = "sandbox_transport_executor_v0"
    manually_selected_outcome: bool = True
    network_connection_attempted: bool = False
    production_transport_invoked: bool = False
    receipt_recorded: bool = False
    sent: bool = False

    @model_validator(mode="after")
    def reject_simulation_effect_claims(self) -> "SandboxTransportSimulation":
        if (
            self.network_connection_attempted
            or self.production_transport_invoked
            or self.sent
        ):
            raise ValueError("sandbox simulation cannot claim a production effect")
        expected_receipt = self.outcome == "simulated_receipt_recorded"
        if self.receipt_recorded != expected_receipt:
            raise ValueError("sandbox simulation receipt state does not match outcome")
        return self


class SandboxTransportReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_sandbox_transport_receipt"
    artifact_version: str = "emergency_mobile_sandbox_transport_receipt.v0"
    receipt_id: str
    sha256: str
    request_sha256: str
    scenario_id: str
    source_approval_id: str
    source_attempt_id: str
    source_attempt_sha256: str
    source_packet_id: str
    source_packet_sha256: str
    outcome: Literal["simulated_receipt_recorded"] = "simulated_receipt_recorded"
    idempotency_key: str
    executor: str = "sandbox_transport_executor_v0"
    attempted: bool = True
    simulated_transport: bool = True
    simulated_receipt_correlated: bool = True
    production_delivery_verified: bool = False
    production_send_performed: bool = False
    sent: bool = False

    @model_validator(mode="after")
    def reject_production_delivery_claims(self) -> "SandboxTransportReceipt":
        if (
            not self.simulated_transport
            or not self.simulated_receipt_correlated
            or self.production_delivery_verified
            or self.production_send_performed
            or self.sent
        ):
            raise ValueError("sandbox receipt cannot claim production delivery")
        return self


class SandboxTimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    event_id: str
    kind: str
    observed_at_offset_s: int = Field(ge=0)
    summary: str
    source_refs: list[str] = Field(default_factory=list)
    scenario_id: str


class SandboxLivingProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_mobile_closed_loop_living_projection"
    schema_version: str = "scout.emergency_mobile_closed_loop.living.v0"
    status: str
    revision: int = Field(ge=1)
    scenario: SandboxScenario
    ingress: SandboxIngressProjection
    evaluation_snapshot: SandboxEvaluationSnapshot
    route: SandboxRouteProjection
    safety: SandboxSafetyProjection
    alert_packet: SandboxAlertPacket | None = None
    approval: SandboxApprovalArtifact | None = None
    transport_attempt: SandboxTransportAttempt | None = None
    transport_simulation: SandboxTransportSimulation | None = None
    transport_receipt: SandboxTransportReceipt | None = None
    timeline: list[SandboxTimelineEvent] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    artifact_refs: dict[str, str] = Field(default_factory=dict)
    boundary: SandboxBoundary = Field(default_factory=SandboxBoundary)

    @model_validator(mode="after")
    def enforce_projection(self) -> "SandboxLivingProjection":
        if self.safety.runtime_safety_truth or self.safety.phase1_l0_l4_state_mutated:
            raise ValueError("Living projection cannot promote replay to runtime truth")
        if (
            self.safety.evaluation_snapshot_sha256 != self.evaluation_snapshot.sha256
            or self.safety.input_set_hash != self.evaluation_snapshot.input_set_hash
        ):
            raise ValueError("Living safety candidate must bind the evaluation snapshot")
        sequences = [event.sequence for event in self.timeline]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("Living timeline sequences must be contiguous")
        return self


class ClosedLoopSandboxStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self.current_path = self.root / "current.json"
        self._lock = threading.RLock()

    def run_scenario(
        self,
        request: SandboxRunRequest | dict[str, Any],
    ) -> SandboxLivingProjection:
        item = (
            request
            if isinstance(request, SandboxRunRequest)
            else SandboxRunRequest.model_validate(request)
        )
        if not item.confirm_sandbox_run:
            raise ClosedLoopSandboxBoundaryError(
                "confirm_sandbox_run=true is required"
            )
        with self._lock:
            run_dir = self.root / "runs" / item.run_id
            ingress_dir = run_dir / "ingress"
            shadow_dir = run_dir / "shadow_replay"
            scenario_ref = "scenario_fixture.json"
            _write_json(
                run_dir / scenario_ref,
                {
                    **item.model_dump(mode="json"),
                    "confirm_sandbox_run": True,
                    "boundary": SandboxBoundary().model_dump(mode="json"),
                    "notes": [
                        "synthetic phone and wearable replay",
                        "directly exercises the SensorLogger MQTT observer handler",
                        "does not publish to a network broker",
                    ],
                },
            )

            observer, ingress_records = _run_sensorlogger_ingress(item, ingress_dir)
            observer_status = observer.status()
            observer_status_ref = "ingress/sensorlogger_mqtt_status.json"
            evaluation_snapshot_ref = "evaluation_snapshot.json"
            evaluation_snapshot = _build_evaluation_snapshot(item, ingress_records)
            _write_json(
                run_dir / evaluation_snapshot_ref,
                evaluation_snapshot.model_dump(mode="json"),
            )
            shadow = run_runtime_shadow_replay(
                {
                    "source_provider": "scout_emergency_mobile_closed_loop_sandbox",
                    "source_path": evaluation_snapshot_ref,
                    "route_gate_feed": _route_gate_feed(item, evaluation_snapshot),
                    "additional_gate_events": _additional_gate_events(
                        item, evaluation_snapshot
                    ),
                    "phase1_adapter_enabled": False,
                    "human_review_approved": False,
                    "phase1_mutation_enabled": False,
                },
                output_dir=shadow_dir,
            )
            route = SandboxRouteProjection(
                route_id=f"{item.project_id}.sandbox.route",
                segment_id="seg.001",
                checkpoint_id="camp.001",
                location_ref="segment:seg.001",
                route_progress_m=1850,
                distance_to_checkpoint_m=1350,
                heading_deg=42.5,
                horizontal_accuracy_m=6.0,
                source_ref=scenario_ref,
            )
            safety = _safety_projection(
                shadow,
                evaluation_snapshot=evaluation_snapshot,
                evaluation_snapshot_ref=evaluation_snapshot_ref,
            )
            packet = _build_alert_candidate(
                item,
                route,
                safety,
                evaluation_snapshot=evaluation_snapshot,
            )
            packet_ref = "alert_packet_candidate.json"
            _write_json(run_dir / packet_ref, packet.model_dump(mode="json"))
            timeline = _initial_timeline(
                item,
                ingress_records=ingress_records,
                reducer_ref="shadow_replay/runtime_safety_reducer_dry_run.json",
                packet_ref=packet_ref,
                safety=safety,
            )
            latest_ingress = dict(observer_status.get("ingress") or {}).get(
                "records", []
            )
            latest_ingress_id = (
                latest_ingress[-1].get("ingress_id") if latest_ingress else None
            )
            projection = SandboxLivingProjection(
                status="pending_approval",
                revision=1,
                scenario=SandboxScenario(
                    scenario_id=item.scenario_id,
                    run_id=item.run_id,
                    project_id=item.project_id,
                    source_mode=item.source_mode,
                    profile=item.profile,
                    observed_at=item.observed_at,
                ),
                ingress=SandboxIngressProjection(
                    topic_ref=f"scout/sandbox/{item.scenario_id}/sensorlogger",
                    accepted_message_count=int(observer_status.get("message_count", 0)),
                    invalid_message_count=int(
                        observer_status.get("invalid_message_count", 0)
                    ),
                    device_count=len(observer_status.get("sessions") or []),
                    sensor_names=list(observer_status.get("sensor_names") or []),
                    latest_ingress_id=latest_ingress_id,
                    observer_status_ref=observer_status_ref,
                ),
                evaluation_snapshot=evaluation_snapshot,
                route=route,
                safety=safety,
                alert_packet=packet,
                timeline=timeline,
                source_refs=[
                    scenario_ref,
                    observer_status_ref,
                    evaluation_snapshot_ref,
                    "shadow_replay/runtime_shadow_replay_result.json",
                    packet_ref,
                ],
                artifact_refs={
                    "run_dir": f"runs/{item.run_id}",
                    "scenario": scenario_ref,
                    "observer_status": observer_status_ref,
                    "evaluation_snapshot": evaluation_snapshot_ref,
                    "shadow_replay": "shadow_replay/runtime_shadow_replay_result.json",
                    "alert_packet": packet_ref,
                    "living_projection": "living_projection.json",
                },
            )
            self._persist_projection(projection)
            return projection

    def load_current(self) -> SandboxLivingProjection | None:
        with self._lock:
            if not self.current_path.exists():
                return None
            return SandboxLivingProjection.model_validate_json(
                self.current_path.read_text(encoding="utf-8")
            )

    def record_approval(
        self,
        request: SandboxApprovalRequest | dict[str, Any],
    ) -> SandboxLivingProjection:
        item = (
            request
            if isinstance(request, SandboxApprovalRequest)
            else SandboxApprovalRequest.model_validate(request)
        )
        if not item.confirm_sandbox_action:
            raise ClosedLoopSandboxBoundaryError(
                "confirm_sandbox_action=true is required"
            )
        with self._lock:
            projection = self._require_current()
            packet = projection.alert_packet
            if projection.scenario.scenario_id != item.scenario_id:
                raise ClosedLoopSandboxConflict("scenario_id does not match current run")
            if packet is None or packet.packet_id != item.packet_id:
                raise ClosedLoopSandboxConflict("packet_id does not match current packet")
            if packet.sha256 != item.packet_sha256:
                raise ClosedLoopSandboxConflict("packet hash does not match current packet")

            approval_path = self._run_dir(projection) / "approvals" / (
                f"{item.idempotency_key}.json"
            )
            request_sha = _digest(item.model_dump(mode="json"))
            if approval_path.exists():
                existing = SandboxApprovalArtifact.model_validate_json(
                    approval_path.read_text(encoding="utf-8")
                )
                if existing.request_sha256 != request_sha:
                    raise ClosedLoopSandboxConflict(
                        "approval idempotency key was used for another request"
                    )
                return projection
            if projection.approval is not None:
                raise ClosedLoopSandboxConflict(
                    "an approval action is already recorded for the current packet"
                )

            approval_id = f"approval:{item.scenario_id}:{item.idempotency_key}"
            approval = SandboxApprovalArtifact(
                approval_id=approval_id,
                sha256=_digest(
                    {
                        "approval_id": approval_id,
                        "request_sha256": request_sha,
                        "packet_sha256": packet.sha256,
                    }
                ),
                request_sha256=request_sha,
                scenario_id=item.scenario_id,
                source_packet_id=item.packet_id,
                source_packet_sha256=item.packet_sha256,
                decision=item.decision,
                idempotency_key=item.idempotency_key,
                requested_transport=(
                    "sandbox_transport_executor_v0"
                    if item.decision == "agree_send"
                    else "none"
                ),
                external_send_requested=item.decision == "agree_send",
            )
            _write_json(approval_path, approval.model_dump(mode="json"))
            attempt: SandboxTransportAttempt | None = None
            attempt_ref: str | None = None
            if approval.decision == "agree_send":
                attempt_ref = (
                    f"transport_attempts/{approval.idempotency_key}.json"
                )
                attempt_id = f"attempt:{item.scenario_id}:{approval.idempotency_key}"
                attempt_request_sha = _digest(
                    {
                        "approval_id": approval.approval_id,
                        "approval_sha256": approval.sha256,
                        "packet_id": packet.packet_id,
                        "packet_sha256": packet.sha256,
                        "executor": "sandbox_transport_executor_v0",
                    }
                )
                attempt = SandboxTransportAttempt(
                    attempt_id=attempt_id,
                    sha256=_digest(
                        {
                            "attempt_id": attempt_id,
                            "request_sha256": attempt_request_sha,
                            "approval_sha256": approval.sha256,
                            "packet_sha256": packet.sha256,
                            "destination_alias": "synthetic_rescue_desk",
                        }
                    ),
                    request_sha256=attempt_request_sha,
                    scenario_id=item.scenario_id,
                    source_approval_id=approval.approval_id,
                    source_approval_sha256=approval.sha256,
                    source_packet_id=packet.packet_id,
                    source_packet_sha256=packet.sha256,
                    idempotency_key=approval.idempotency_key,
                )
                _write_json(
                    self._run_dir(projection) / attempt_ref,
                    attempt.model_dump(mode="json"),
                )
            status = _status_for_decision(item.decision)
            packet_update = packet.model_copy(update={"status": status})
            timeline = [
                *projection.timeline,
                _timeline_event(
                    projection,
                    kind="approval_action_recorded",
                    summary=f"Operator sandbox action recorded: {item.decision}",
                    source_refs=[
                        projection.artifact_refs["alert_packet"],
                        f"approvals/{item.idempotency_key}.json",
                    ],
                ),
            ]
            if attempt is not None and attempt_ref is not None:
                timeline.append(
                    _timeline_event(
                        projection,
                        kind="sandbox_transport_attempt_recorded",
                        summary=(
                            "Sandbox-only attempt recorded from accepted approval; "
                            "network=false, production sent=false"
                        ),
                        source_refs=[
                            f"approvals/{item.idempotency_key}.json",
                            attempt_ref,
                        ],
                        sequence_offset=1,
                    )
                )
            added_refs = [f"approvals/{item.idempotency_key}.json"]
            if attempt_ref is not None:
                added_refs.append(attempt_ref)
            updated = SandboxLivingProjection.model_validate(
                {
                    **projection.model_dump(mode="json"),
                    "status": status,
                    "revision": projection.revision + 1,
                    "alert_packet": packet_update.model_dump(mode="json"),
                    "approval": approval.model_dump(mode="json"),
                    "transport_attempt": (
                        attempt.model_dump(mode="json") if attempt is not None else None
                    ),
                    "transport_simulation": None,
                    "transport_receipt": None,
                    "timeline": [event.model_dump(mode="json") for event in timeline],
                    "source_refs": [
                        *projection.source_refs,
                        *added_refs,
                    ],
                }
            )
            self._persist_projection(updated)
            return updated

    def record_transport_simulation(
        self,
        request: SandboxTransportSimulationRequest | dict[str, Any],
    ) -> SandboxLivingProjection:
        item = (
            request
            if isinstance(request, SandboxTransportSimulationRequest)
            else SandboxTransportSimulationRequest.model_validate(request)
        )
        if not item.confirm_simulated_transport:
            raise ClosedLoopSandboxBoundaryError(
                "confirm_simulated_transport=true is required"
            )
        with self._lock:
            projection = self._require_current()
            approval = projection.approval
            attempt = projection.transport_attempt
            packet = projection.alert_packet
            if projection.scenario.scenario_id != item.scenario_id:
                raise ClosedLoopSandboxConflict("scenario_id does not match current run")
            if approval is None or approval.decision != "agree_send":
                raise ClosedLoopSandboxConflict(
                    "simulation requires an accepted agree_send approval"
                )
            if attempt is None:
                raise ClosedLoopSandboxConflict(
                    "simulation requires an existing server-side sandbox attempt"
                )
            if attempt.attempt_id != item.attempt_id:
                raise ClosedLoopSandboxConflict("attempt_id does not match current attempt")
            if attempt.sha256 != item.attempt_sha256:
                raise ClosedLoopSandboxConflict("attempt hash does not match current attempt")
            if packet is None or packet.packet_id != item.packet_id:
                raise ClosedLoopSandboxConflict("packet_id does not match current packet")
            if packet.sha256 != item.packet_sha256:
                raise ClosedLoopSandboxConflict("packet hash does not match current packet")
            if (
                attempt.source_approval_id != approval.approval_id
                or attempt.source_approval_sha256 != approval.sha256
                or attempt.source_packet_id != packet.packet_id
                or attempt.source_packet_sha256 != packet.sha256
            ):
                raise ClosedLoopSandboxConflict(
                    "attempt does not match the accepted approval and immutable packet"
                )

            simulation_ref = f"simulations/{item.idempotency_key}.json"
            simulation_path = self._run_dir(projection) / simulation_ref
            request_sha = _digest(item.model_dump(mode="json"))
            if simulation_path.exists():
                existing = SandboxTransportSimulation.model_validate_json(
                    simulation_path.read_text(encoding="utf-8")
                )
                if existing.request_sha256 != request_sha:
                    raise ClosedLoopSandboxConflict(
                        "simulation idempotency key was used for another request"
                    )
                return projection
            if projection.transport_simulation is not None:
                raise ClosedLoopSandboxConflict(
                    "a simulator outcome is already recorded for this attempt"
                )

            simulation_id = f"simulation:{item.scenario_id}:{item.idempotency_key}"
            simulation = SandboxTransportSimulation(
                simulation_id=simulation_id,
                sha256=_digest(
                    {
                        "simulation_id": simulation_id,
                        "request_sha256": request_sha,
                        "attempt_sha256": attempt.sha256,
                        "packet_sha256": packet.sha256,
                        "outcome": item.outcome,
                    }
                ),
                request_sha256=request_sha,
                scenario_id=item.scenario_id,
                source_attempt_id=attempt.attempt_id,
                source_attempt_sha256=attempt.sha256,
                source_packet_id=packet.packet_id,
                source_packet_sha256=packet.sha256,
                outcome=item.outcome,
                idempotency_key=item.idempotency_key,
                receipt_recorded=item.outcome == "simulated_receipt_recorded",
            )
            _write_json(simulation_path, simulation.model_dump(mode="json"))

            receipt: SandboxTransportReceipt | None = None
            added_refs = [simulation_ref]
            if simulation.receipt_recorded:
                receipt_ref = f"receipts/{item.idempotency_key}.json"
                receipt_id = f"receipt:{item.scenario_id}:{item.idempotency_key}"
                receipt = SandboxTransportReceipt(
                    receipt_id=receipt_id,
                    sha256=_digest(
                        {
                            "receipt_id": receipt_id,
                            "request_sha256": request_sha,
                            "simulation_sha256": simulation.sha256,
                            "attempt_sha256": attempt.sha256,
                            "packet_sha256": packet.sha256,
                        }
                    ),
                    request_sha256=request_sha,
                    scenario_id=item.scenario_id,
                    source_approval_id=approval.approval_id,
                    source_attempt_id=attempt.attempt_id,
                    source_attempt_sha256=attempt.sha256,
                    source_packet_id=packet.packet_id,
                    source_packet_sha256=packet.sha256,
                    idempotency_key=item.idempotency_key,
                )
                _write_json(
                    self._run_dir(projection) / receipt_ref,
                    receipt.model_dump(mode="json"),
                )
                added_refs.append(receipt_ref)

            status = item.outcome
            packet_update = packet.model_copy(update={"status": status})
            if receipt is not None:
                event_kind = "sandbox_transport_receipt_recorded"
                event_summary = (
                    "Simulator receipt recorded and correlated; "
                    "no real transport or delivery occurred"
                )
            else:
                event_kind = "sandbox_transport_simulation_incomplete"
                event_summary = (
                    f"Simulator outcome {item.outcome}; no receipt, "
                    "network=false, production sent=false"
                )
            timeline = [
                *projection.timeline,
                _timeline_event(
                    projection,
                    kind=event_kind,
                    summary=event_summary,
                    source_refs=[
                        f"transport_attempts/{attempt.idempotency_key}.json",
                        *added_refs,
                    ],
                ),
            ]
            updated = SandboxLivingProjection.model_validate(
                {
                    **projection.model_dump(mode="json"),
                    "status": status,
                    "revision": projection.revision + 1,
                    "alert_packet": packet_update.model_dump(mode="json"),
                    "transport_simulation": simulation.model_dump(mode="json"),
                    "transport_receipt": (
                        receipt.model_dump(mode="json") if receipt is not None else None
                    ),
                    "timeline": [event.model_dump(mode="json") for event in timeline],
                    "source_refs": [*projection.source_refs, *added_refs],
                }
            )
            self._persist_projection(updated)
            return updated

    def empty_payload(self) -> dict[str, Any]:
        return {
            "artifact_kind": "scout_emergency_mobile_closed_loop_living_projection",
            "schema_version": "scout.emergency_mobile_closed_loop.living.v0",
            "status": "unavailable",
            "reason": "no_sandbox_run",
            "revision": 0,
            "timeline": [],
            "boundary": SandboxBoundary().model_dump(mode="json"),
        }

    def _require_current(self) -> SandboxLivingProjection:
        projection = self.load_current()
        if projection is None:
            raise ClosedLoopSandboxConflict("no current sandbox run")
        return projection

    def _run_dir(self, projection: SandboxLivingProjection) -> Path:
        return self.root / "runs" / projection.scenario.run_id

    def _persist_projection(self, projection: SandboxLivingProjection) -> None:
        run_path = self._run_dir(projection) / "living_projection.json"
        payload = projection.model_dump(mode="json")
        _write_json(run_path, payload)
        _write_json(self.current_path, payload)


def _run_sensorlogger_ingress(
    request: SandboxRunRequest,
    evidence_dir: Path,
) -> tuple[SensorLoggerMqttObserver, list[dict[str, Any]]]:
    topic = f"scout/sandbox/{request.scenario_id}/sensorlogger"
    observer = SensorLoggerMqttObserver(
        SensorLoggerMqttObserverConfig(
            host="sandbox.invalid",
            topic=topic,
            port=1883,
            use_tls=False,
            transport="tcp",
            client_id=f"sandbox-{request.run_id}",
            evidence_dir=evidence_dir,
        )
    )
    base_time = datetime.fromisoformat(
        request.observed_at.replace("Z", "+00:00")
    ).timestamp()
    messages = _sensorlogger_messages(request, base_time)
    records = [
        observer.handle_message(
            topic=topic,
            payload=json.dumps(message, ensure_ascii=False),
            received_at=(
                base_time
                + (1 if message.get("deviceId") == "sandbox-wearable-v0" else 0)
            ),
        )
        for message in messages
    ]
    if not all(record.get("accepted") for record in records):
        raise ClosedLoopSandboxError("synthetic SensorLogger ingress was rejected")
    return observer, records


def _sensorlogger_messages(
    request: SandboxRunRequest,
    base_time: float,
) -> list[dict[str, Any]]:
    base_ns = int(base_time * 1_000_000_000)
    return [
        {
            "messageId": 1,
            "sessionId": request.scenario_id,
            "deviceId": "sandbox-phone-v0",
            "payload": [
                {
                    "name": "location",
                    "time": base_ns,
                    "values": {
                        "latitude": 24.050482,
                        "longitude": 121.215181,
                        "horizontalAccuracy": 6.0,
                        "speed": 0.42,
                        "bearing": 42.5,
                    },
                },
                {
                    "name": "accelerometer",
                    "time": base_ns,
                    "values": {"x": 0.2, "y": -0.1, "z": 9.7},
                },
                {
                    "name": "battery",
                    "time": base_ns,
                    "values": {"level": 0.38, "charging": False},
                },
            ],
        },
        {
            "messageId": 1,
            "sessionId": request.scenario_id,
            "deviceId": "sandbox-wearable-v0",
            "payload": [
                {
                    "name": "heartRate",
                    "time": base_ns + 1_000_000_000,
                    "values": {"bpm": 168, "confidence": "high"},
                },
                {
                    "name": "oxygenSaturation",
                    "time": base_ns + 1_000_000_000,
                    "values": {"percent": 91, "confidence": "medium"},
                },
                {
                    "name": "battery",
                    "time": base_ns + 1_000_000_000,
                    "values": {"level": 0.46, "charging": False},
                },
            ],
        },
    ]


def _build_evaluation_snapshot(
    request: SandboxRunRequest,
    ingress_records: list[dict[str, Any]],
) -> SandboxEvaluationSnapshot:
    input_records = sorted(
        (
            SandboxEvaluationInputRecord(
                record_id=str(record.get("ingress_id") or ""),
                record_hash=str(record.get("payload_sha256") or ""),
                device_id=str(
                    record.get("device_id")
                    or (record.get("normalized_summary") or {}).get("device_id")
                    or ""
                ),
                sensor_names=sorted(
                    list(
                        record.get("sensor_names")
                        or (record.get("normalized_summary") or {}).get("sensor_names")
                        or []
                    )
                ),
            )
            for record in ingress_records
            if record.get("accepted") or record.get("parse_status") == "accepted"
        ),
        key=lambda item: (item.device_id, item.record_id),
    )
    if {item.device_id for item in input_records} != {
        "sandbox-phone-v0",
        "sandbox-wearable-v0",
    }:
        raise ClosedLoopSandboxError(
            "evaluation snapshot requires accepted synthetic phone and wearable records"
        )
    input_set_payload = [
        {
            "record_id": item.record_id,
            "record_hash": item.record_hash,
            "device_id": item.device_id,
            "sensor_names": item.sensor_names,
        }
        for item in input_records
    ]
    input_set_hash = _digest(input_set_payload)
    evaluation_snapshot_id = (
        f"snapshot:{request.scenario_id}:{input_set_hash[:20]}"
    )
    snapshot_payload = {
        "evaluation_snapshot_id": evaluation_snapshot_id,
        "scenario_id": request.scenario_id,
        "scenario_revision": 1,
        "simulated_time": request.observed_at,
        "input_records": input_set_payload,
        "input_set_hash": input_set_hash,
        "seal_reason": "expected_synthetic_inputs_accepted",
        "gate_snapshot_ref": "shadow_replay/runtime_safety_gate_event_batch.json",
        "reducer_ref": "shadow_replay/runtime_safety_reducer_dry_run.json",
    }
    return SandboxEvaluationSnapshot(
        **snapshot_payload,
        sha256=_digest(snapshot_payload),
    )


def _route_gate_feed(
    request: SandboxRunRequest,
    evaluation_snapshot: SandboxEvaluationSnapshot,
) -> dict[str, Any]:
    route_id = f"{request.project_id}.sandbox.route"
    return {
        "source_provider": "scout_emergency_mobile_closed_loop_sandbox",
        "source_path": (
            f"evaluation_snapshot.json#{evaluation_snapshot.input_set_hash}"
        ),
        "route_id": route_id,
        "segment_timings": [
            {
                "segment_id": "seg.001",
                "from_checkpoint_id": "cp.start",
                "to_checkpoint_id": "camp.001",
                "distance_m": 3200,
                "reference_p50_minutes": 55,
                "reference_p75_minutes": 70,
                "reference_max_minutes": 105,
                "map_target_ids": ["seg.001", "camp.001"],
                "source_ref": "scenario_fixture.json#segment_timing",
            }
        ],
        "planned_timeline": [
            {
                "checkpoint_id": "camp.001",
                "checkpoint_kind": "camp",
                "segment_id": "seg.001",
                "planned_arrival_offset_min": 150,
                "latest_arrival_offset_min": 180,
                "map_target_ids": ["camp.001", "seg.001"],
                "source_ref": "scenario_fixture.json#planned_timeline",
            }
        ],
        "progress_frames": [
            {
                "frame_id": "frame.distress.001",
                "route_id": route_id,
                "observed_at_offset_s": 7200,
                "elapsed_route_minutes": 120,
                "segment_id": "seg.001",
                "target_checkpoint_id": "camp.001",
                "elapsed_segment_minutes": 90,
                "observed_segment_distance_m": 1850,
                "estimated_minutes_to_target": 30,
                "daylight_buffer_minutes": 90,
                "minutes_to_next_safe_objective": 65,
                "emergency_bivy_candidate_distance_m": 450,
                "route_pressure_review_required": True,
                "confidence": "high",
                "evidence_refs": [
                    "ingress/sensorlogger_mqtt_status.json",
                    "evaluation_snapshot.json",
                    "scenario_fixture.json#route_progress",
                ],
            }
        ],
        "data_quality": {
            "confidence": "high",
            "signal_count": 4,
            "live_network_calls_made": False,
            "limitations": ["synthetic replay fixture"],
        },
    }


def _additional_gate_events(
    request: SandboxRunRequest,
    evaluation_snapshot: SandboxEvaluationSnapshot,
) -> list[Any]:
    route_id = f"{request.project_id}.sandbox.route"
    route_context = {
        "route_id": route_id,
        "segment_id": "seg.001",
        "checkpoint_id": "camp.001",
        "map_target_ids": ["seg.001", "camp.001"],
        "distance_to_next_checkpoint_m": 1350,
        "estimated_minutes_to_next_checkpoint": 30,
        "daylight_buffer_minutes": 90,
    }
    snapshot_payload = {
        "evaluation_snapshot_id": evaluation_snapshot.evaluation_snapshot_id,
        "input_set_hash": evaluation_snapshot.input_set_hash,
    }
    common = {
        "source_provider": "scout_emergency_mobile_closed_loop_sandbox",
        "source_path": "evaluation_snapshot.json",
        "observed_at_offset_s": 7201,
        "route_context": route_context,
        "evidence_refs": [
            "ingress/sensorlogger_mqtt_status.json",
            "evaluation_snapshot.json",
            "scenario_fixture.json#condition_overlays",
        ],
    }
    return [
        build_runtime_safety_gate_event(
            **common,
            gate_id="physiologic_gate",
            event_id=f"physiologic_gate:{request.scenario_id}",
            state_candidate="physiologic_retreat_review",
            severity="retreat_review",
            ln_transition_candidate="candidate_retreat",
            required_action="stop_and_review_retreat_or_emergency_camp",
            confidence="high",
            route_pressure_review_required=True,
            dominant_reasons=[
                "synthetic elevated heart-rate aggregate",
                "synthetic low oxygen-saturation aggregate",
                "not a medical diagnosis",
            ],
            gate_payload={
                **snapshot_payload,
                "aggregate_fixture": True,
                "medical_diagnosis": False,
            },
        ),
        build_runtime_safety_gate_event(
            **common,
            gate_id="weather_gate",
            event_id=f"weather_gate:{request.scenario_id}",
            state_candidate="strong_wind_watch",
            severity="watch",
            ln_transition_candidate="candidate_watch",
            required_action="watch_wind_and_recheck",
            confidence="medium",
            dominant_reasons=["synthetic ridge wind overlay"],
            gate_payload={
                **snapshot_payload,
                "condition_overlay": "synthetic_strong_wind_watch",
            },
        ),
        build_runtime_safety_gate_event(
            **common,
            gate_id="environment_threat_gate",
            event_id=f"environment_threat_gate:{request.scenario_id}",
            state_candidate="no_confirmed_environment_threat",
            severity="none",
            ln_transition_candidate="none",
            required_action="continue_monitoring",
            confidence="medium",
            dominant_reasons=["no confirmed threat in synthetic overlay"],
            gate_payload={
                **snapshot_payload,
                "condition_overlay": "synthetic_clear",
            },
        ),
    ]


def _safety_projection(
    shadow: Any,
    *,
    evaluation_snapshot: SandboxEvaluationSnapshot,
    evaluation_snapshot_ref: str,
) -> SandboxSafetyProjection:
    summaries = {
        summary["gate_id"]: summary
        for summary in shadow.reducer_decision.gate_summaries
    }
    gates: list[SandboxGateProjection] = []
    for gate_id in _GATE_IDS:
        summary = summaries.get(gate_id) or {
            "gate_id": gate_id,
            "state_candidate": "not_observed",
            "severity": "none",
            "ln_level_candidate": "L0_NORMAL",
            "confidence": "low",
            "dominant_reasons": ["gate evidence unavailable"],
            "evidence_refs": [],
        }
        gates.append(
            SandboxGateProjection(
                gate_id=str(summary["gate_id"]),
                state_candidate=str(summary["state_candidate"]),
                severity=str(summary["severity"]),
                ln_level_candidate=str(summary["ln_level_candidate"]),
                confidence=str(summary["confidence"]),
                dominant_reasons=list(summary.get("dominant_reasons") or []),
                evidence_refs=list(summary.get("evidence_refs") or []),
            )
        )
    return SandboxSafetyProjection(
        selected_gate_id=shadow.selected_gate_id,
        ln_level_candidate=shadow.ln_level_candidate,
        reducer_state=shadow.reducer_state,
        recommendation=shadow.recommendation,
        reducer_sha256=shadow.reducer_decision.sha256,
        reducer_source_ref=shadow.artifact_refs.reducer_decision_path,
        evaluation_snapshot_id=evaluation_snapshot.evaluation_snapshot_id,
        evaluation_snapshot_sha256=evaluation_snapshot.sha256,
        input_set_hash=evaluation_snapshot.input_set_hash,
        evaluation_snapshot_ref=evaluation_snapshot_ref,
        phase1_adapter_status=shadow.phase1_adapter_result.status,
        gates=gates,
    )


def _build_alert_candidate(
    request: SandboxRunRequest,
    route: SandboxRouteProjection,
    safety: SandboxSafetyProjection,
    *,
    evaluation_snapshot: SandboxEvaluationSnapshot,
) -> SandboxAlertPacket:
    packet_id = f"sandbox.packet:{request.scenario_id}:{request.run_id}"
    summary = (
        f"{safety.selected_gate_id or 'reducer'} produced "
        f"{safety.ln_level_candidate}; review retreat or emergency camp"
    )
    mqtt_topic = f"scout/sandbox/{request.scenario_id}/alerts/{request.run_id}"
    packet_content_sha = _digest(
        {
            "scenario_id": request.scenario_id,
            "reducer_sha256": safety.reducer_sha256,
            "evaluation_snapshot_sha256": evaluation_snapshot.sha256,
            "input_set_hash": evaluation_snapshot.input_set_hash,
            "level": safety.ln_level_candidate,
            "location_ref": route.location_ref,
            "summary": summary,
        }
    )
    packet_sha = _digest(
        {
            "packet_id": packet_id,
            "content_sha256": packet_content_sha,
        }
    )
    return SandboxAlertPacket(
        packet_id=packet_id,
        sha256=packet_sha,
        content_sha256=packet_content_sha,
        scenario_id=request.scenario_id,
        source_reducer_sha256=safety.reducer_sha256,
        source_reducer_ref=safety.reducer_source_ref,
        source_evaluation_snapshot_id=evaluation_snapshot.evaluation_snapshot_id,
        source_evaluation_snapshot_sha256=evaluation_snapshot.sha256,
        source_input_set_hash=evaluation_snapshot.input_set_hash,
        safety_level_candidate=safety.ln_level_candidate,
        selected_gate_id=safety.selected_gate_id,
        location_ref=route.location_ref,
        summary=summary,
        requested_action="stop, review retreat or emergency camp, and request operator approval",
        transport_drafts=[
            SandboxTransportDraft(
                profile="sms_text",
                summary="SCOUT SANDBOX ALERT DRAFT - NOT SENT",
            ),
            SandboxTransportDraft(
                profile="lora_compact",
                summary="compact sandbox payload ready; radio not invoked",
            ),
            SandboxTransportDraft(
                profile="mqtt_json",
                topic_ref=mqtt_topic,
                summary="sandbox MQTT draft ready; publish not performed",
            ),
        ],
    )


def _initial_timeline(
    request: SandboxRunRequest,
    *,
    ingress_records: list[dict[str, Any]],
    reducer_ref: str,
    packet_ref: str,
    safety: SandboxSafetyProjection,
) -> list[SandboxTimelineEvent]:
    events = [
        SandboxTimelineEvent(
            sequence=1,
            event_id=f"{request.run_id}:scenario_started",
            kind="sandbox_scenario_started",
            observed_at_offset_s=0,
            summary="Synthetic phone/wearable closed-loop scenario started",
            source_refs=["scenario_fixture.json"],
            scenario_id=request.scenario_id,
        )
    ]
    for index, record in enumerate(ingress_records, start=2):
        events.append(
            SandboxTimelineEvent(
                sequence=index,
                event_id=f"{request.run_id}:ingress:{index - 1}",
                kind="sensorlogger_ingress_accepted",
                observed_at_offset_s=index - 2,
                summary=(
                    f"Accepted synthetic {record.get('device_id')} message via "
                    "SensorLogger observer handler"
                ),
                source_refs=[
                    "ingress/sensorlogger_mqtt_status.json",
                    str(record.get("ingress_id") or "ingress:unknown"),
                ],
                scenario_id=request.scenario_id,
            )
        )
    events.extend(
        [
            SandboxTimelineEvent(
                sequence=len(events) + 1,
                event_id=f"{request.run_id}:reducer",
                kind="runtime_safety_reducer_candidate",
                observed_at_offset_s=7201,
                summary=(
                    f"Reducer selected {safety.selected_gate_id} at "
                    f"{safety.ln_level_candidate}; candidate-only"
                ),
                source_refs=[reducer_ref],
                scenario_id=request.scenario_id,
            ),
            SandboxTimelineEvent(
                sequence=len(events) + 2,
                event_id=f"{request.run_id}:alert_packet",
                kind="sandbox_alert_packet_prepared",
                observed_at_offset_s=7202,
                summary="Prepared alert candidate; production sent=false",
                source_refs=[packet_ref],
                scenario_id=request.scenario_id,
            ),
        ]
    )
    return events


def _timeline_event(
    projection: SandboxLivingProjection,
    *,
    kind: str,
    summary: str,
    source_refs: list[str],
    sequence_offset: int = 0,
) -> SandboxTimelineEvent:
    sequence = len(projection.timeline) + 1 + sequence_offset
    return SandboxTimelineEvent(
        sequence=sequence,
        event_id=f"{projection.scenario.run_id}:{kind}:{sequence}",
        kind=kind,
        observed_at_offset_s=7200 + sequence,
        summary=summary,
        source_refs=source_refs,
        scenario_id=projection.scenario.scenario_id,
    )


def _status_for_decision(decision: SandboxDecision) -> str:
    return {
        "agree_send": "approved_sandbox_attempt_recorded",
        "do_not_send": "cancelled",
        "review_again_5_minutes": "review_scheduled_5_minutes",
        "review_again_10_minutes": "review_scheduled_10_minutes",
        "current_condition_ok_downgrade_request": "downgrade_requested",
        "immediate_phone_call": "manual_callout_selected",
        "manual_copy_emergency_packet": "manual_copy_prepared",
        "retreat_or_emergency_camp": "route_action_selected",
        "message_draft": "message_draft_selected",
        "voice_call_script": "voice_call_script_selected",
    }[decision]


def _digest(payload: Any) -> str:
    return aggregate_sha256([payload])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)
