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
    transport_routes_mounted: bool = False
    observation_ingest_allowed: bool = False
    stream_control_mutation_allowed: bool = False
    live_provider_send_allowed: bool = False
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
    transport_routes_mounted: bool = False,
    live_provider_send_allowed: bool = False,
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
        boundary=RuntimeStreamStatusSurfaceBoundary(
            transport_routes_mounted=transport_routes_mounted,
            observation_ingest_allowed=transport_routes_mounted,
            stream_control_mutation_allowed=transport_routes_mounted,
            live_provider_send_allowed=live_provider_send_allowed,
            route_inventory=_route_inventory(
                transport_routes_mounted=transport_routes_mounted,
            ),
        ),
        notes=_status_notes(transport_routes_mounted=transport_routes_mounted),
    )


def create_runtime_stream_status_router(
    *,
    telemetry_store: RuntimeStreamTelemetryStore | None = None,
    control_store: RuntimeStreamControlStore | None = None,
    admission_state: RuntimeInputAdmissionState | None = None,
    transport_routes_mounted: bool = False,
    live_provider_send_allowed: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/runtime/streams", tags=["runtime-stream-status"])

    @router.get("/status-read-only")
    def runtime_stream_status_read_only() -> dict[str, Any]:
        return build_runtime_stream_status_surface(
            telemetry_store=telemetry_store,
            control_store=control_store,
            admission_state=admission_state,
            transport_routes_mounted=transport_routes_mounted,
            live_provider_send_allowed=live_provider_send_allowed,
        ).model_dump(mode="json")

    return router


def _route_inventory(*, transport_routes_mounted: bool) -> list[str]:
    routes = [READ_ONLY_STATUS_ROUTE]
    if transport_routes_mounted:
        routes.extend(
            [
                "GET /runtime/streams/status",
                "GET /runtime/streams/control/status",
                "POST /runtime/streams/control/pause",
                "POST /runtime/streams/control/resume",
                "POST /runtime/streams/control/end",
                "POST /runtime/streams/control/drain-queue",
                "POST /runtime/streams/http-push/observations",
                "WS /runtime/streams/websocket/observations",
            ]
        )
    return routes


def _status_notes(*, transport_routes_mounted: bool) -> list[str]:
    if transport_routes_mounted:
        return [
            "Read-only runtime stream status surface; live transport routes are mounted separately.",
            "Telemetry and control state are summaries only and do not embed raw payloads.",
            "Remote provider policy is shown as policy-only and does not send network requests.",
        ]
    return [
        "Read-only runtime stream status surface; no transport routes are mounted.",
        "Telemetry and control state are summaries only and do not embed raw payloads.",
        "Remote provider policy is shown as policy-only and does not send network requests.",
    ]
