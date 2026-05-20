from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from runtime_input_admission import RuntimeInputAdmissionState
from runtime_remote_provider_policy import (
    RuntimeRemoteProviderPolicyContract,
    build_webhook_remote_provider_policy_contract,
)
from runtime_stream_controls import RuntimeStreamControlSnapshot, RuntimeStreamControlStore
from runtime_stream_policy import (
    RuntimeStreamPolicyManifest,
    build_default_runtime_stream_policy_manifest,
)
from runtime_stream_telemetry import RuntimeStreamTelemetrySnapshot, RuntimeStreamTelemetryStore


READ_ONLY_STATUS_ROUTE = "GET /runtime/streams/status-read-only"


class RuntimeStreamStatusSurfaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStreamStatusSurfaceBoundary(RuntimeStreamStatusSurfaceModel):
    read_only_surface: Literal[True] = True
    transport_routes_mounted: Literal[False] = False
    observation_ingest_allowed: Literal[False] = False
    stream_control_mutation_allowed: Literal[False] = False
    live_provider_send_allowed: Literal[False] = False
    safety_mutation_allowed: Literal[False] = False
    incident_bridge_enable_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    route_inventory: list[str] = Field(default_factory=lambda: [READ_ONLY_STATUS_ROUTE])


class RuntimeStreamStatusSurfaceSnapshot(RuntimeStreamStatusSurfaceModel):
    artifact_kind: Literal["runtime_stream_status_surface"] = (
        "runtime_stream_status_surface"
    )
    status: Literal["read_only_status_ready"] = "read_only_status_ready"
    policy: RuntimeStreamPolicyManifest
    telemetry: RuntimeStreamTelemetrySnapshot
    control: RuntimeStreamControlSnapshot
    remote_provider_policy: RuntimeRemoteProviderPolicyContract
    boundary: RuntimeStreamStatusSurfaceBoundary = Field(
        default_factory=RuntimeStreamStatusSurfaceBoundary
    )
    notes: list[str] = Field(
        default_factory=lambda: [
            "Read-only runtime stream status surface; no transport routes are mounted.",
            "Telemetry and control state are summaries only and do not embed raw payloads.",
            "Remote provider policy is shown as policy-only and does not send network requests.",
        ]
    )


def build_runtime_stream_status_surface(
    *,
    policy: RuntimeStreamPolicyManifest | None = None,
    telemetry_store: RuntimeStreamTelemetryStore | None = None,
    control_store: RuntimeStreamControlStore | None = None,
    admission_state: RuntimeInputAdmissionState | None = None,
    remote_provider_policy: RuntimeRemoteProviderPolicyContract | None = None,
) -> RuntimeStreamStatusSurfaceSnapshot:
    active_policy = policy or build_default_runtime_stream_policy_manifest()
    active_telemetry = telemetry_store or RuntimeStreamTelemetryStore()
    active_control = control_store or RuntimeStreamControlStore()
    active_remote_policy = (
        remote_provider_policy or build_webhook_remote_provider_policy_contract()
    )
    return RuntimeStreamStatusSurfaceSnapshot(
        policy=active_policy,
        telemetry=active_telemetry.snapshot(admission_state=admission_state),
        control=active_control.snapshot(),
        remote_provider_policy=active_remote_policy,
    )


def create_runtime_stream_status_router(
    *,
    telemetry_store: RuntimeStreamTelemetryStore | None = None,
    control_store: RuntimeStreamControlStore | None = None,
    admission_state: RuntimeInputAdmissionState | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/runtime/streams", tags=["runtime-stream-status"])

    @router.get("/status-read-only")
    def runtime_stream_status_read_only() -> dict[str, Any]:
        return build_runtime_stream_status_surface(
            telemetry_store=telemetry_store,
            control_store=control_store,
            admission_state=admission_state,
        ).model_dump(mode="json")

    return router
