from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_observation_envelope import (
    RuntimeObservationEnvelope,
    verify_runtime_observation_envelope,
)
from runtime_stream_policy import (
    RuntimeStreamPolicyManifest,
    RuntimeStreamSourcePolicy,
)


class RuntimeInputAdmissionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeInputAdmissionStatus(StrEnum):
    ADMITTED_NOT_FORWARDED = "admitted_not_forwarded"
    QUEUED_BACKPRESSURE = "queued_backpressure"
    QUEUED_DISCONNECTED = "queued_disconnected"
    LATEST_POINT_RETAINED = "latest_point_retained"
    REJECTED_DUPLICATE = "rejected_duplicate"
    REJECTED_SEQUENCE = "rejected_sequence"
    REJECTED_SIGNATURE = "rejected_signature"
    REJECTED_SOURCE_POLICY = "rejected_source_policy"


class RuntimeInputAdmissionBoundary(RuntimeInputAdmissionModel):
    admission_only: Literal[True] = True
    raw_payload_embedded: Literal[False] = False
    creates_live_endpoint: Literal[False] = False
    calls_safety_api: Literal[False] = False
    forwards_to_runtime: Literal[False] = False
    connects_device_stream: Literal[False] = False
    enables_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Input Admission / 現場輸入准入 validates a signed envelope before any runtime forward.",
            "Admission decisions may queue or reject observations but do not call /safety.",
            "Raw observation payload is verified by hash/signature and is not embedded in the decision.",
        ]
    )


class RuntimeInputAdmissionCounts(RuntimeInputAdmissionModel):
    admitted_count: int = Field(default=0, ge=0)
    queued_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    live_endpoint_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    runtime_forward_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeInputAdmissionState(RuntimeInputAdmissionModel):
    last_sequence_by_stream: dict[str, int] = Field(default_factory=dict)
    last_observed_at_by_stream: dict[str, str] = Field(default_factory=dict)
    seen_dedupe_keys: list[str] = Field(default_factory=list)
    disconnected_queue_keys: list[str] = Field(default_factory=list)
    backpressure_queue_keys: list[str] = Field(default_factory=list)
    latest_retained_key_by_stream: dict[str, str] = Field(default_factory=dict)


class RuntimeInputAdmissionDecision(RuntimeInputAdmissionModel):
    artifact_kind: Literal["runtime_input_admission_decision"] = (
        "runtime_input_admission_decision"
    )
    status: RuntimeInputAdmissionStatus
    reason: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    transport: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    token_scope: str = Field(min_length=1)
    sequence_no: int = Field(ge=0)
    observed_at: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dedupe_key: str = Field(min_length=1)
    signature_verified: bool
    policy_matched: bool
    transport_allowed: bool
    token_scope_allowed: bool
    connected: bool
    retry_attempt: int = Field(ge=0)
    retry_attempt_limit: int = Field(ge=0)
    queue_depth: int = Field(ge=0)
    state_after: RuntimeInputAdmissionState
    counts: RuntimeInputAdmissionCounts
    boundary: RuntimeInputAdmissionBoundary = Field(
        default_factory=RuntimeInputAdmissionBoundary
    )

    @model_validator(mode="after")
    def enforce_decision_boundary(self) -> "RuntimeInputAdmissionDecision":
        if self.boundary.raw_payload_embedded:
            raise ValueError("runtime input admission must not embed raw payload")
        if self.boundary.calls_safety_api:
            raise ValueError("runtime input admission must not call /safety")
        if self.boundary.forwards_to_runtime:
            raise ValueError("runtime input admission must not forward to runtime")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def empty_runtime_input_admission_state() -> RuntimeInputAdmissionState:
    return RuntimeInputAdmissionState()


def admit_runtime_observation_input(
    envelope: RuntimeObservationEnvelope,
    payload: dict[str, Any],
    *,
    secret_key: str,
    policy_manifest: RuntimeStreamPolicyManifest,
    state: RuntimeInputAdmissionState | None = None,
    connected: bool = True,
    retry_attempt: int = 0,
) -> RuntimeInputAdmissionDecision:
    current_state = state or empty_runtime_input_admission_state()
    next_state = current_state.model_copy(deep=True)
    stream_key = _stream_key(envelope)
    retry_attempt_limit = policy_manifest.buffering.retry_attempt_limit

    signature_verified = verify_runtime_observation_envelope(
        envelope,
        payload,
        secret_key=secret_key,
    )
    if not signature_verified:
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.REJECTED_SIGNATURE,
            reason="payload_hash_or_signature_verification_failed",
            state_after=next_state,
            signature_verified=False,
            policy_matched=False,
            transport_allowed=False,
            token_scope_allowed=False,
            connected=connected,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(rejected_count=1),
        )

    source_policy = _find_source_policy(policy_manifest, envelope)
    policy_matched = source_policy is not None
    transport_allowed = bool(
        source_policy and envelope.transport in source_policy.accepted_transports
    )
    token_scope_allowed = bool(
        source_policy and envelope.token_scope == source_policy.token_scope
    )
    if not (policy_matched and transport_allowed and token_scope_allowed):
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.REJECTED_SOURCE_POLICY,
            reason=_source_policy_rejection_reason(
                policy_matched=policy_matched,
                transport_allowed=transport_allowed,
                token_scope_allowed=token_scope_allowed,
            ),
            state_after=next_state,
            signature_verified=True,
            policy_matched=policy_matched,
            transport_allowed=transport_allowed,
            token_scope_allowed=token_scope_allowed,
            connected=connected,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(rejected_count=1),
        )

    if envelope.dedupe_key in next_state.seen_dedupe_keys:
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.REJECTED_DUPLICATE,
            reason="dedupe_key_already_seen",
            state_after=next_state,
            signature_verified=True,
            policy_matched=True,
            transport_allowed=True,
            token_scope_allowed=True,
            connected=connected,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(rejected_count=1),
        )

    last_sequence = next_state.last_sequence_by_stream.get(stream_key)
    if last_sequence is not None and envelope.sequence_no <= last_sequence:
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.REJECTED_SEQUENCE,
            reason="sequence_number_not_monotonic",
            state_after=next_state,
            signature_verified=True,
            policy_matched=True,
            transport_allowed=True,
            token_scope_allowed=True,
            connected=connected,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(rejected_count=1),
        )

    if _below_min_interval(
        next_state.last_observed_at_by_stream.get(stream_key),
        envelope.observed_at,
        min_interval_ms=policy_manifest.cadence.min_interval_ms,
    ):
        _mark_seen(next_state, envelope)
        next_state.backpressure_queue_keys.append(envelope.dedupe_key)
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.QUEUED_BACKPRESSURE,
            reason="cadence_interval_below_policy_minimum",
            state_after=next_state,
            signature_verified=True,
            policy_matched=True,
            transport_allowed=True,
            token_scope_allowed=True,
            connected=connected,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(queued_count=1),
        )

    _mark_seen(next_state, envelope)
    if not connected and retry_attempt >= retry_attempt_limit:
        _drop_stream_queue(next_state, stream_key)
        next_state.latest_retained_key_by_stream[stream_key] = envelope.dedupe_key
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.LATEST_POINT_RETAINED,
            reason="retry_attempt_limit_reached_latest_point_only",
            state_after=next_state,
            signature_verified=True,
            policy_matched=True,
            transport_allowed=True,
            token_scope_allowed=True,
            connected=False,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(queued_count=1),
        )

    if not connected:
        next_state.disconnected_queue_keys.append(envelope.dedupe_key)
        return _decision(
            envelope,
            status=RuntimeInputAdmissionStatus.QUEUED_DISCONNECTED,
            reason="stream_disconnected_queued_for_retry",
            state_after=next_state,
            signature_verified=True,
            policy_matched=True,
            transport_allowed=True,
            token_scope_allowed=True,
            connected=False,
            retry_attempt=retry_attempt,
            retry_attempt_limit=retry_attempt_limit,
            counts=RuntimeInputAdmissionCounts(queued_count=1),
        )

    return _decision(
        envelope,
        status=RuntimeInputAdmissionStatus.ADMITTED_NOT_FORWARDED,
        reason="signed_source_policy_match_admitted_to_local_gate",
        state_after=next_state,
        signature_verified=True,
        policy_matched=True,
        transport_allowed=True,
        token_scope_allowed=True,
        connected=True,
        retry_attempt=retry_attempt,
        retry_attempt_limit=retry_attempt_limit,
        counts=RuntimeInputAdmissionCounts(admitted_count=1),
    )


def _decision(
    envelope: RuntimeObservationEnvelope,
    *,
    status: RuntimeInputAdmissionStatus,
    reason: str,
    state_after: RuntimeInputAdmissionState,
    signature_verified: bool,
    policy_matched: bool,
    transport_allowed: bool,
    token_scope_allowed: bool,
    connected: bool,
    retry_attempt: int,
    retry_attempt_limit: int,
    counts: RuntimeInputAdmissionCounts,
) -> RuntimeInputAdmissionDecision:
    return RuntimeInputAdmissionDecision(
        status=status,
        reason=reason,
        source_id=envelope.source_id,
        source_kind=envelope.source_kind.value,
        transport=envelope.transport.value,
        device_id=envelope.device_id,
        token_scope=envelope.token_scope,
        sequence_no=envelope.sequence_no,
        observed_at=envelope.observed_at,
        payload_sha256=envelope.payload_sha256,
        dedupe_key=envelope.dedupe_key,
        signature_verified=signature_verified,
        policy_matched=policy_matched,
        transport_allowed=transport_allowed,
        token_scope_allowed=token_scope_allowed,
        connected=connected,
        retry_attempt=retry_attempt,
        retry_attempt_limit=retry_attempt_limit,
        queue_depth=(
            len(state_after.disconnected_queue_keys)
            + len(state_after.backpressure_queue_keys)
        ),
        state_after=state_after,
        counts=counts,
    )


def _find_source_policy(
    policy_manifest: RuntimeStreamPolicyManifest,
    envelope: RuntimeObservationEnvelope,
) -> RuntimeStreamSourcePolicy | None:
    for source_policy in policy_manifest.source_policies:
        if (
            source_policy.source_id == envelope.source_id
            and source_policy.source_kind == envelope.source_kind
        ):
            return source_policy
    return None


def _source_policy_rejection_reason(
    *,
    policy_matched: bool,
    transport_allowed: bool,
    token_scope_allowed: bool,
) -> str:
    if not policy_matched:
        return "source_id_or_source_kind_not_in_policy"
    if not transport_allowed:
        return "transport_not_allowed_by_source_policy"
    if not token_scope_allowed:
        return "token_scope_not_allowed_by_source_policy"
    return "source_policy_rejected"


def _mark_seen(
    state: RuntimeInputAdmissionState,
    envelope: RuntimeObservationEnvelope,
) -> None:
    stream_key = _stream_key(envelope)
    if envelope.dedupe_key not in state.seen_dedupe_keys:
        state.seen_dedupe_keys.append(envelope.dedupe_key)
    state.last_sequence_by_stream[stream_key] = envelope.sequence_no
    state.last_observed_at_by_stream[stream_key] = envelope.observed_at


def _drop_stream_queue(
    state: RuntimeInputAdmissionState,
    stream_key: str,
) -> None:
    prefix = f"{stream_key}:"
    state.disconnected_queue_keys = [
        key for key in state.disconnected_queue_keys if not key.startswith(prefix)
    ]


def _stream_key(envelope: RuntimeObservationEnvelope) -> str:
    return f"{envelope.source_id}:{envelope.device_id}"


def _below_min_interval(
    previous_observed_at: str | None,
    observed_at: str,
    *,
    min_interval_ms: int,
) -> bool:
    if previous_observed_at is None:
        return False
    previous = _parse_datetime(previous_observed_at)
    current = _parse_datetime(observed_at)
    delta_ms = (current - previous).total_seconds() * 1000.0
    return delta_ms < min_interval_ms


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _assert_no_raw_payload_fragments(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = (
        '"lat"',
        '"lon"',
        "elevation_m",
        "gps_horizontal_accuracy_m",
        "sensorlog",
        "loggingTime",
        "<gpx",
    )
    found = [fragment for fragment in forbidden if fragment in text]
    if found:
        raise ValueError(f"runtime input admission contains raw payload fragments: {found}")
