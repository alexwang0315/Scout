from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from runtime_stream_controls import (
    RuntimeStreamControlRequest,
    RuntimeStreamControlStore,
)
from runtime_stream_policy import RuntimeStreamTransportKind
from runtime_stream_telemetry import RuntimeStreamTelemetryStore
from safety_api import (
    SafetyObservationAdmissionConfig,
    ingest_safety_observation_body,
)
from safety_runtime_session import SafetyRuntimeSession


def create_runtime_stream_transport_router(
    *,
    runtime_session: SafetyRuntimeSession,
    observation_admission_config: SafetyObservationAdmissionConfig,
    server_signal_snapshot_provider: Callable[[], dict[str, Any] | None] | None = None,
    telemetry_store: RuntimeStreamTelemetryStore | None = None,
    control_store: RuntimeStreamControlStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/runtime/streams", tags=["runtime-streams"])
    telemetry = telemetry_store or RuntimeStreamTelemetryStore()
    controls = control_store or RuntimeStreamControlStore()

    @router.get("/status")
    def runtime_stream_status() -> dict[str, Any]:
        snapshot = telemetry.snapshot(
            admission_state=observation_admission_config.state
        ).model_dump(mode="json")
        snapshot["control"] = controls.snapshot().model_dump(mode="json")
        return snapshot

    @router.get("/control/status")
    def runtime_stream_control_status() -> dict[str, Any]:
        return controls.snapshot().model_dump(mode="json")

    @router.post("/control/pause")
    def pause_runtime_stream(request: RuntimeStreamControlRequest) -> dict[str, Any]:
        try:
            result = controls.pause(
                operator_id=request.operator_id,
                reason=request.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"reason": str(exc)}) from exc
        return result.model_dump(mode="json")

    @router.post("/control/resume")
    def resume_runtime_stream(request: RuntimeStreamControlRequest) -> dict[str, Any]:
        try:
            result = controls.resume(
                operator_id=request.operator_id,
                reason=request.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"reason": str(exc)}) from exc
        return result.model_dump(mode="json")

    @router.post("/control/end")
    def end_runtime_stream(request: RuntimeStreamControlRequest) -> dict[str, Any]:
        try:
            result = controls.end(
                operator_id=request.operator_id,
                reason=request.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"reason": str(exc)}) from exc
        return result.model_dump(mode="json")

    @router.post("/control/drain-queue")
    def drain_runtime_stream_queue(request: RuntimeStreamControlRequest) -> dict[str, Any]:
        try:
            record = controls.drain_queue(
                observation_admission_config.state,
                operator_id=request.operator_id,
                reason=request.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"reason": str(exc)}) from exc
        return record.model_dump(mode="json")

    @router.post("/http-push/observations")
    async def ingest_http_push_observation(body: dict[str, Any]) -> dict[str, Any]:
        control_rejection = _control_rejection(controls)
        if control_rejection is not None:
            telemetry.record_rejected(
                RuntimeStreamTransportKind.HTTP_PUSH,
                status_code=409,
                detail=control_rejection,
            )
            raise HTTPException(status_code=409, detail=control_rejection)
        try:
            response = ingest_safety_observation_body(
                body,
                runtime_session=runtime_session,
                server_signal_snapshot_provider=server_signal_snapshot_provider,
                observation_admission_config=observation_admission_config,
                required_transport=RuntimeStreamTransportKind.HTTP_PUSH,
            )
        except HTTPException as exc:
            telemetry.record_rejected(
                RuntimeStreamTransportKind.HTTP_PUSH,
                status_code=exc.status_code,
                detail=exc.detail,
            )
            raise
        telemetry.record_accepted(RuntimeStreamTransportKind.HTTP_PUSH, response)
        return response

    @router.websocket("/websocket/observations")
    async def ingest_websocket_observations(websocket: WebSocket) -> None:
        await websocket.accept()
        telemetry.record_websocket_connected()
        try:
            while True:
                body = await websocket.receive_json()
                try:
                    control_rejection = _control_rejection(controls)
                    if control_rejection is not None:
                        raise HTTPException(status_code=409, detail=control_rejection)
                    response = ingest_safety_observation_body(
                        body,
                        runtime_session=runtime_session,
                        server_signal_snapshot_provider=server_signal_snapshot_provider,
                        observation_admission_config=observation_admission_config,
                        required_transport=RuntimeStreamTransportKind.WEBSOCKET,
                    )
                    telemetry.record_accepted(
                        RuntimeStreamTransportKind.WEBSOCKET,
                        response,
                    )
                except HTTPException as exc:
                    response = {
                        "status": "rejected",
                        "code": exc.status_code,
                        "detail": exc.detail,
                    }
                    telemetry.record_rejected(
                        RuntimeStreamTransportKind.WEBSOCKET,
                        status_code=exc.status_code,
                        detail=exc.detail,
                    )
                except ValidationError as exc:
                    response = {
                        "status": "rejected",
                        "code": 422,
                        "detail": exc.errors(),
                    }
                    telemetry.record_rejected(
                        RuntimeStreamTransportKind.WEBSOCKET,
                        status_code=422,
                        detail=exc.errors(),
                    )
                await websocket.send_json(response)
        except WebSocketDisconnect:
            pass
        finally:
            telemetry.record_websocket_disconnected()

    return router


def _control_rejection(controls: RuntimeStreamControlStore) -> dict[str, Any] | None:
    reason = controls.reject_reason_for_observation()
    if reason is None:
        return None
    return {
        "reason": reason,
        "control_status": controls.status.value,
    }
