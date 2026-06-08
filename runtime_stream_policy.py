from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuntimeStreamPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStreamSourceKind(StrEnum):
    APPLE_WATCH = "apple_watch"
    MOBILE_PHONE = "mobile_phone"


class RuntimeStreamTransportKind(StrEnum):
    HTTP_PUSH = "http_push"
    WEBSOCKET = "websocket"


class RuntimeStreamAuthMethod(StrEnum):
    DEVICE_ID_SCOPED_TOKEN_HMAC_SIGNATURE = "device_id_scoped_token_hmac_signature"


class RuntimeStreamFallbackMode(StrEnum):
    LATEST_POINT_ONLY = "latest_point_only"


class RuntimeStreamOverLimitAction(StrEnum):
    BACKPRESSURE_THEN_DROP_OLDEST_EXCEPT_LATEST = (
        "backpressure_then_drop_oldest_except_latest"
    )


class RuntimeStreamSourcePolicy(RuntimeStreamPolicyModel):
    source_id: str = Field(min_length=1)
    source_kind: RuntimeStreamSourceKind
    accepted_transports: list[RuntimeStreamTransportKind] = Field(min_length=1)
    enabled_after_phase45_handoff: Literal[True] = True
    device_id_required: Literal[True] = True
    scoped_token_required: Literal[True] = True
    hmac_signature_required: Literal[True] = True
    timestamp_required: Literal[True] = True
    sequence_number_required: Literal[True] = True
    payload_hash_required: Literal[True] = True
    recommended_auth_method: Literal[
        RuntimeStreamAuthMethod.DEVICE_ID_SCOPED_TOKEN_HMAC_SIGNATURE
    ] = RuntimeStreamAuthMethod.DEVICE_ID_SCOPED_TOKEN_HMAC_SIGNATURE
    token_scope: Literal["runtime:observation:write"] = "runtime:observation:write"
    signature_algorithm: Literal["hmac_sha256"] = "hmac_sha256"
    rejects_device_id_only: Literal[True] = True
    rejects_unsigned_payload: Literal[True] = True

    @model_validator(mode="after")
    def enforce_source_policy_contract(self) -> "RuntimeStreamSourcePolicy":
        if RuntimeStreamTransportKind.HTTP_PUSH not in self.accepted_transports:
            raise ValueError("runtime stream source must support http_push")
        if RuntimeStreamTransportKind.WEBSOCKET not in self.accepted_transports:
            raise ValueError("runtime stream source must support websocket")
        return self


class RuntimeStreamBufferingPolicy(RuntimeStreamPolicyModel):
    queue_when_disconnected: Literal[True] = True
    retry_attempt_limit: Literal[5] = 5
    retry_exhausted_fallback: Literal[RuntimeStreamFallbackMode.LATEST_POINT_ONLY] = (
        RuntimeStreamFallbackMode.LATEST_POINT_ONLY
    )
    keeps_latest_point_after_retry_exhausted: Literal[True] = True
    drops_stale_queued_points_after_retry_exhausted: Literal[True] = True


class RuntimeStreamCadencePolicy(RuntimeStreamPolicyModel):
    max_hz: float = Field(default=10.0, gt=0)
    min_interval_ms: int = Field(default=100, ge=1)
    backpressure_enabled: Literal[True] = True
    rate_limit_enabled: Literal[True] = True
    over_limit_action: RuntimeStreamOverLimitAction = (
        RuntimeStreamOverLimitAction.BACKPRESSURE_THEN_DROP_OLDEST_EXCEPT_LATEST
    )

    @model_validator(mode="after")
    def enforce_cadence_contract(self) -> "RuntimeStreamCadencePolicy":
        if self.max_hz > 10.0:
            raise ValueError("runtime stream cadence must not exceed 10 Hz")
        if self.min_interval_ms < 100:
            raise ValueError("runtime stream min_interval_ms must be at least 100")
        return self


class RuntimeSafetyApiAccessPolicy(RuntimeStreamPolicyModel):
    safety_api_allowed_after_phase45_handoff: Literal[True] = True
    endpoint_prefix: Literal["/safety"] = "/safety"
    allowed_endpoint_refs: list[str] = Field(
        default_factory=lambda: [
            "POST /safety/observations",
            "GET /safety/state",
        ],
        min_length=1,
    )
    requires_final_mission_graph: Literal[True] = True
    requires_runtime_handoff_manifest: Literal[True] = True
    requires_runtime_activation: Literal[True] = True
    requires_runtime_observing_state: Literal[True] = True
    requires_source_policy_match: Literal[True] = True

    @model_validator(mode="after")
    def enforce_safety_api_policy_contract(self) -> "RuntimeSafetyApiAccessPolicy":
        if not all("/safety" in endpoint for endpoint in self.allowed_endpoint_refs):
            raise ValueError("runtime safety API endpoints must stay under /safety")
        return self


class RuntimeIncidentBridgeOptInGuard(RuntimeStreamPolicyModel):
    guard_status: Literal["opt_in_required_not_enabled"] = "opt_in_required_not_enabled"
    enabled_by_default: Literal[False] = False
    opt_in_required: Literal[True] = True
    remote_notifications_enabled: Literal[False] = False
    stream_start_enables_bridge: Literal[False] = False
    requires_explicit_operator_opt_in: Literal[True] = True
    requires_remote_contact_policy: Literal[True] = True
    requires_noise_reduction_policy: Literal[True] = True


class RuntimeStreamPolicyBoundary(RuntimeStreamPolicyModel):
    policy_only: Literal[True] = True
    opens_safety_api_after_handoff: Literal[True] = True
    creates_live_endpoint: Literal[False] = False
    connects_device_stream: Literal[False] = False
    starts_websocket_server: Literal[False] = False
    calls_safety_api: Literal[False] = False
    enables_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    mutates_runtime_export: Literal[False] = False
    mutates_activation_request: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Stream Policy / 串流政策 records the approved live-stream contract.",
            "This slice opens the policy path for /safety after Phase 4.5 handoff, but creates no live endpoint.",
            "Incident bridge remains opt-in guarded and disabled by default.",
        ]
    )


class RuntimeStreamPolicyCounts(RuntimeStreamPolicyModel):
    source_policy_count: int = Field(ge=0)
    accepted_transport_count: int = Field(ge=0)
    live_endpoint_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    incident_bridge_enable_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


class RuntimeStreamPolicyManifest(RuntimeStreamPolicyModel):
    manifest_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_stream_policy_manifest"] = (
        "runtime_stream_policy_manifest"
    )
    status: Literal["policy_ready_not_connected"] = "policy_ready_not_connected"
    source_policies: list[RuntimeStreamSourcePolicy] = Field(min_length=1)
    buffering: RuntimeStreamBufferingPolicy
    cadence: RuntimeStreamCadencePolicy
    safety_api_access: RuntimeSafetyApiAccessPolicy
    incident_bridge_opt_in_guard: RuntimeIncidentBridgeOptInGuard
    boundary: RuntimeStreamPolicyBoundary
    counts: RuntimeStreamPolicyCounts

    @model_validator(mode="after")
    def enforce_manifest_contract(self) -> "RuntimeStreamPolicyManifest":
        source_kinds = {policy.source_kind for policy in self.source_policies}
        if source_kinds != {
            RuntimeStreamSourceKind.APPLE_WATCH,
            RuntimeStreamSourceKind.MOBILE_PHONE,
        }:
            raise ValueError("runtime stream policy must include Apple Watch and mobile phone")
        transports = {
            transport
            for policy in self.source_policies
            for transport in policy.accepted_transports
        }
        if transports != {
            RuntimeStreamTransportKind.HTTP_PUSH,
            RuntimeStreamTransportKind.WEBSOCKET,
        }:
            raise ValueError("runtime stream policy must include HTTP push and WebSocket")
        if self.counts.source_policy_count != len(self.source_policies):
            raise ValueError("source_policy_count must match source policies")
        if self.counts.accepted_transport_count != len(transports):
            raise ValueError("accepted_transport_count must match unique transports")
        return self

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_default_runtime_stream_policy_manifest() -> RuntimeStreamPolicyManifest:
    accepted_transports = [
        RuntimeStreamTransportKind.HTTP_PUSH,
        RuntimeStreamTransportKind.WEBSOCKET,
    ]
    source_policies = [
        RuntimeStreamSourcePolicy(
            source_id="runtime_source.apple_watch.v0",
            source_kind=RuntimeStreamSourceKind.APPLE_WATCH,
            accepted_transports=accepted_transports,
        ),
        RuntimeStreamSourcePolicy(
            source_id="runtime_source.mobile_phone.v0",
            source_kind=RuntimeStreamSourceKind.MOBILE_PHONE,
            accepted_transports=accepted_transports,
        ),
    ]
    return RuntimeStreamPolicyManifest(
        manifest_id="runtime_stream_policy.phase45.v0",
        source_policies=source_policies,
        buffering=RuntimeStreamBufferingPolicy(),
        cadence=RuntimeStreamCadencePolicy(),
        safety_api_access=RuntimeSafetyApiAccessPolicy(),
        incident_bridge_opt_in_guard=RuntimeIncidentBridgeOptInGuard(),
        boundary=RuntimeStreamPolicyBoundary(),
        counts=RuntimeStreamPolicyCounts(
            source_policy_count=len(source_policies),
            accepted_transport_count=len(set(accepted_transports)),
        ),
    )


def load_runtime_stream_policy_manifest(path: Path | str) -> RuntimeStreamPolicyManifest:
    return RuntimeStreamPolicyManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
