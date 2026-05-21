from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from checkpoint_manager import CheckpointArrival
from incident_store import IncidentStore
from mission_models import SegmentCapsule
from observation_adapter import sensorlog_payload_to_observations
from runtime_input_admission import (
    RuntimeInputAdmissionDecision,
    RuntimeInputAdmissionState,
    RuntimeInputAdmissionStatus,
    admit_runtime_observation_input,
    empty_runtime_input_admission_state,
)
from runtime_observation_envelope import RuntimeObservationEnvelope
from runtime_stream_policy import (
    RuntimeStreamPolicyManifest,
    RuntimeStreamTransportKind,
    build_default_runtime_stream_policy_manifest,
)
from safety_models import SafetyState
from safety_runtime_session import SafetyRuntimeSession, SafetyRuntimeUpdate


class SafetyAckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requester_id: str
    reason: str
    last_known_route_id: str | None = None


class SafetyObservationIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: Any
    device: str = "apple_watch"
    source: str = "live_sensorlog"
    received_at: float | None = None
    server_signal_snapshot: dict[str, Any] | None = None


class SafetySignedObservationIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: dict[str, Any]
    payload: Any
    device: str = "apple_watch"
    source: str = "runtime_signed_sensorlog"
    received_at: float | None = None
    server_signal_snapshot: dict[str, Any] | None = None
    connected: bool = True
    retry_attempt: int = 0


@dataclass
class SafetyObservationAdmissionConfig:
    secret_key: str
    policy_manifest: RuntimeStreamPolicyManifest = field(
        default_factory=build_default_runtime_stream_policy_manifest
    )
    state: RuntimeInputAdmissionState = field(
        default_factory=empty_runtime_input_admission_state
    )


@dataclass(frozen=True)
class SafetyApiSnapshot:
    safety_state: SafetyState
    checkpoint_hits: list[CheckpointArrival] = field(default_factory=list)
    segment_capsules: list[SegmentCapsule] = field(default_factory=list)
    latest_incident_id: str | None = None
    last_known_position: dict[str, Any] | None = None


def snapshot_from_replay_result(replay_result: Any) -> SafetyApiSnapshot:
    latest_package = replay_result.incident_packages[-1] if replay_result.incident_packages else None
    latest_sample = latest_package.raw_samples[-1] if latest_package and latest_package.raw_samples else None
    return SafetyApiSnapshot(
        safety_state=replay_result.safety_state,
        checkpoint_hits=replay_result.checkpoint_hits,
        segment_capsules=replay_result.segment_capsules,
        latest_incident_id=latest_package.incident_id if latest_package else None,
        last_known_position=_position_from_sample(latest_sample),
    )


def snapshot_from_runtime_session(runtime_session: SafetyRuntimeSession) -> SafetyApiSnapshot:
    runtime_snapshot = runtime_session.snapshot()
    latest_package = runtime_snapshot.incident_packages[-1] if runtime_snapshot.incident_packages else None
    latest_sample = latest_package.raw_samples[-1] if latest_package and latest_package.raw_samples else None
    return SafetyApiSnapshot(
        safety_state=runtime_snapshot.safety_state,
        checkpoint_hits=runtime_snapshot.checkpoint_hits,
        segment_capsules=runtime_snapshot.segment_capsules,
        latest_incident_id=latest_package.incident_id if latest_package else None,
        last_known_position=_position_from_sample(latest_sample),
    )


def create_safety_app(
    snapshot: SafetyApiSnapshot,
    incident_store: IncidentStore | None = None,
    *,
    runtime_session: SafetyRuntimeSession | None = None,
    server_signal_snapshot_provider: Callable[[], dict[str, Any] | None] | None = None,
    observation_admission_config: SafetyObservationAdmissionConfig | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout Fusion Phase 1 Safety API Mock")
    app.include_router(
        create_safety_router(
            snapshot,
            incident_store,
            runtime_session=runtime_session,
            server_signal_snapshot_provider=server_signal_snapshot_provider,
            observation_admission_config=observation_admission_config,
        )
    )
    return app


def create_safety_router(
    snapshot: SafetyApiSnapshot,
    incident_store: IncidentStore | None = None,
    *,
    runtime_session: SafetyRuntimeSession | None = None,
    server_signal_snapshot_provider: Callable[[], dict[str, Any] | None] | None = None,
    observation_admission_config: SafetyObservationAdmissionConfig | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/safety", tags=["safety"])

    @router.post("/ack")
    def ack(request: SafetyAckRequest) -> dict[str, Any]:
        current_snapshot = _current_snapshot(snapshot, runtime_session)
        latest_incident_id = _latest_incident_id(current_snapshot, incident_store)
        return {
            "requester_id": request.requester_id,
            "request_reason": request.reason,
            "last_known_route_id": request.last_known_route_id,
            "safety_state": current_snapshot.safety_state.model_dump(mode="json"),
            "last_known_position": current_snapshot.last_known_position,
            "latest_incident_id": latest_incident_id,
            "package_available": bool(latest_incident_id and incident_store and incident_store.exists(latest_incident_id)),
            "battery": {"status": "unknown"},
            "signal": {"status": "unknown"},
        }

    @router.get("/state")
    def state() -> dict[str, Any]:
        current_snapshot = _current_snapshot(snapshot, runtime_session)
        transitions = current_snapshot.safety_state.transitions
        return {
            "safety_state": current_snapshot.safety_state.model_dump(mode="json"),
            "latest_transition": transitions[-1].model_dump(mode="json") if transitions else None,
            "active_risk_reasons": [event.reason for event in current_snapshot.safety_state.active_events],
            "latest_incident_id": _latest_incident_id(current_snapshot, incident_store),
        }

    @router.get("/incidents/{incident_id}")
    def incident(incident_id: str) -> dict[str, Any]:
        if incident_store is None or not incident_store.exists(incident_id):
            raise HTTPException(status_code=404, detail="Incident package not found")
        return incident_store.load(incident_id).model_dump(mode="json")

    @router.get("/checkins")
    def checkins() -> dict[str, Any]:
        current_snapshot = _current_snapshot(snapshot, runtime_session)
        return {
            "checkins": [_checkpoint_arrival_dump(arrival) for arrival in current_snapshot.checkpoint_hits],
            "segment_capsules": [capsule.model_dump(mode="json") for capsule in current_snapshot.segment_capsules],
        }

    @router.get("/capsules/{capsule_id}")
    def capsule(capsule_id: str) -> dict[str, Any]:
        current_snapshot = _current_snapshot(snapshot, runtime_session)
        for segment_capsule in current_snapshot.segment_capsules:
            if segment_capsule.capsule_id == capsule_id:
                return segment_capsule.model_dump(mode="json")
        raise HTTPException(status_code=404, detail="Segment capsule not found")

    if runtime_session is not None:

        @router.post("/observations")
        async def ingest_observations(request: Request) -> dict[str, Any]:
            body = await request.json()
            return ingest_safety_observation_body(
                body,
                runtime_session=runtime_session,
                server_signal_snapshot_provider=server_signal_snapshot_provider,
                observation_admission_config=observation_admission_config,
            )

    return router


def ingest_safety_observation_body(
    body: Any,
    *,
    runtime_session: SafetyRuntimeSession,
    server_signal_snapshot_provider: Callable[[], dict[str, Any] | None] | None = None,
    observation_admission_config: SafetyObservationAdmissionConfig | None = None,
    required_transport: RuntimeStreamTransportKind | str | None = None,
) -> dict[str, Any]:
    admission_summary: dict[str, Any] | None = None
    transport_surface: str | None = None
    ingest_surface = "safety_api_direct"
    expected_transport = (
        RuntimeStreamTransportKind(required_transport)
        if required_transport is not None
        else None
    )
    if expected_transport is not None:
        ingest_surface = f"runtime_stream_{expected_transport.value}"
    if observation_admission_config is None:
        try:
            ingest_request = _ingest_request_from_body(body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
    else:
        try:
            signed_request = _signed_ingest_request_from_body(body)
            envelope = RuntimeObservationEnvelope.model_validate(signed_request.envelope)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        if not isinstance(signed_request.payload, dict):
            raise HTTPException(
                status_code=422,
                detail="signed observation payload must be a JSON object",
            )
        if expected_transport is not None and envelope.transport != expected_transport:
            raise HTTPException(
                status_code=422,
                detail={
                    "reason": "transport_endpoint_mismatch",
                    "expected_transport": expected_transport.value,
                    "actual_transport": envelope.transport.value,
                },
            )

        admission_decision = admit_runtime_observation_input(
            envelope,
            signed_request.payload,
            secret_key=observation_admission_config.secret_key,
            policy_manifest=observation_admission_config.policy_manifest,
            state=observation_admission_config.state,
            connected=signed_request.connected,
            retry_attempt=signed_request.retry_attempt,
        )
        observation_admission_config.state = admission_decision.state_after
        admission_summary = _admission_summary(admission_decision)
        if (
            admission_decision.status
            != RuntimeInputAdmissionStatus.ADMITTED_NOT_FORWARDED
        ):
            raise HTTPException(
                status_code=_admission_http_status(admission_decision.status),
                detail=admission_summary,
            )
        ingest_request = SafetyObservationIngestRequest(
            payload=signed_request.payload,
            device=signed_request.device,
            source=signed_request.source,
            received_at=signed_request.received_at,
            server_signal_snapshot=signed_request.server_signal_snapshot,
        )
        transport_surface = envelope.transport.value

    server_signal_snapshot = ingest_request.server_signal_snapshot
    if server_signal_snapshot is None and server_signal_snapshot_provider is not None:
        server_signal_snapshot = server_signal_snapshot_provider()

    try:
        observations = sensorlog_payload_to_observations(
            ingest_request.payload,
            device=ingest_request.device,
            source=ingest_request.source,
            received_at=ingest_request.received_at,
            server_signal_snapshot=server_signal_snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    updates = [runtime_session.observe(observation) for observation in observations]
    runtime_session.persist_incidents()
    runtime_snapshot = runtime_session.snapshot()
    response = {
        "status": "accepted",
        "observations_accepted": len(observations),
        "safety_level": runtime_snapshot.safety_state.level,
        "safety_events": [
            event.model_dump(mode="json")
            for update in updates
            for event in update.safety_events
        ],
        "recording_profiles": [update.recording_decision.profile for update in updates],
        "checkpoint_arrivals": [
            _checkpoint_arrival_dump(update.checkpoint_arrival)
            for update in updates
            if update.checkpoint_arrival is not None
        ],
        "incident_ids": [
            package.incident_id
            for update in updates
            for package in update.incident_packages
        ],
        "stored_incident_paths": [
            str(path)
            for update in updates
            for path in update.stored_incident_paths
        ],
        "latest_capabilities": _latest_capabilities(updates),
        "snapshot": {
            "observations_processed": runtime_snapshot.observations_processed,
            "checkpoint_hits": len(runtime_snapshot.checkpoint_hits),
            "segment_capsules": len(runtime_snapshot.segment_capsules),
            "incident_packages": len(runtime_snapshot.incident_packages),
            "stored_incidents": len(runtime_snapshot.stored_incident_paths),
        },
        "ingest_surface": ingest_surface,
    }
    if admission_summary is not None:
        response["admission"] = admission_summary
        if expected_transport is None:
            response["admission_transport"] = transport_surface
    if expected_transport is not None:
        response["transport_surface"] = transport_surface or expected_transport.value
    return response


def _ingest_request_from_body(body: Any) -> SafetyObservationIngestRequest:
    if isinstance(body, dict) and (
        "payload" in body
        or "device" in body
        or "source" in body
        or "received_at" in body
        or "server_signal_snapshot" in body
    ):
        return SafetyObservationIngestRequest.model_validate(body)
    return SafetyObservationIngestRequest(payload=body)


def _signed_ingest_request_from_body(body: Any) -> SafetySignedObservationIngestRequest:
    return SafetySignedObservationIngestRequest.model_validate(body)


def _admission_http_status(status: RuntimeInputAdmissionStatus) -> int:
    if status in {
        RuntimeInputAdmissionStatus.REJECTED_DUPLICATE,
        RuntimeInputAdmissionStatus.REJECTED_SEQUENCE,
    }:
        return 409
    if status in {
        RuntimeInputAdmissionStatus.QUEUED_BACKPRESSURE,
        RuntimeInputAdmissionStatus.QUEUED_DISCONNECTED,
        RuntimeInputAdmissionStatus.LATEST_POINT_RETAINED,
    }:
        return 202
    return 403


def _admission_summary(decision: RuntimeInputAdmissionDecision) -> dict[str, Any]:
    return {
        "admission_status": decision.status.value,
        "status": decision.status.value,
        "reason": decision.reason,
        "source_id": decision.source_id,
        "source_kind": decision.source_kind,
        "transport": decision.transport,
        "device_id": decision.device_id,
        "sequence_no": decision.sequence_no,
        "payload_sha256": decision.payload_sha256,
        "dedupe_key": decision.dedupe_key,
        "signature_verified": decision.signature_verified,
        "policy_matched": decision.policy_matched,
        "transport_allowed": decision.transport_allowed,
        "token_scope_allowed": decision.token_scope_allowed,
        "queue_depth": decision.queue_depth,
    }


def _latest_capabilities(updates: list[SafetyRuntimeUpdate]) -> dict[str, Any]:
    if not updates:
        return {}
    capabilities = updates[-1].observation.raw.get("capabilities")
    return capabilities if isinstance(capabilities, dict) else {}


def _current_snapshot(
    snapshot: SafetyApiSnapshot,
    runtime_session: SafetyRuntimeSession | None,
) -> SafetyApiSnapshot:
    if runtime_session is None:
        return snapshot
    return snapshot_from_runtime_session(runtime_session)


def _latest_incident_id(snapshot: SafetyApiSnapshot, incident_store: IncidentStore | None) -> str | None:
    if snapshot.latest_incident_id:
        return snapshot.latest_incident_id
    if incident_store is None:
        return None
    ids = incident_store.list_ids()
    return ids[-1] if ids else None


def _checkpoint_arrival_dump(arrival: CheckpointArrival) -> dict[str, Any]:
    return {
        "checkpoint": arrival.checkpoint.model_dump(mode="json"),
        "distance_m": arrival.distance_m,
        "segment_capsule": arrival.segment_capsule.model_dump(mode="json") if arrival.segment_capsule else None,
    }


def _position_from_sample(sample: dict[str, Any] | None) -> dict[str, Any] | None:
    if sample is None:
        return None
    return {
        "timestamp": sample.get("timestamp"),
        "lat": sample.get("lat"),
        "lon": sample.get("lon"),
        "elevation_m": sample.get("elevation_m"),
        "gps_horizontal_accuracy_m": sample.get("gps_horizontal_accuracy_m"),
    }
