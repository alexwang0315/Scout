from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from runtime_audit_ledger import DEFAULT_RUNTIME_AUDIT_ROOT, FileRuntimeAuditLedger


def create_runtime_audit_ledger(
    *,
    root: Path | str | None = None,
) -> FileRuntimeAuditLedger:
    configured_root = root or os.getenv("SCOUT_RUNTIME_AUDIT_ROOT")
    return FileRuntimeAuditLedger(root=configured_root or DEFAULT_RUNTIME_AUDIT_ROOT)


def install_runtime_audit(
    app: FastAPI,
    *,
    ledger: FileRuntimeAuditLedger,
    application: str = "scout-dashboard",
    runtime_profile: str = "dev",
    workspace_id: str | None = None,
) -> None:
    app.state.runtime_audit = ledger
    app.state.runtime_audit_degraded = False

    def ensure_started() -> None:
        try:
            ledger.ensure_started(
                application=application,
                runtime_profile=runtime_profile,
                workspace_id=workspace_id,
            )
        except Exception as exc:
            ledger.note_writer_failure(exc)
            app.state.runtime_audit_degraded = True

    def stop() -> None:
        try:
            ledger.stop(reason="clean-shutdown")
        except Exception as exc:
            ledger.note_writer_failure(exc)
            app.state.runtime_audit_degraded = True

    app.router.on_startup.append(ensure_started)
    app.router.on_shutdown.append(stop)

    @app.middleware("http")
    async def record_runtime_request(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        ensure_started()
        started_at = time.perf_counter()
        request_id = f"request-{uuid4().hex}"
        request.state.runtime_audit_request_id = request_id
        response: Response | None = None
        error_code: str | None = None
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            error_code = type(exc).__name__
            raise
        finally:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            status_code = response.status_code if response is not None else 500
            outcome = (
                "failed"
                if error_code is not None or status_code >= 500
                else "rejected"
                if status_code >= 400
                else "succeeded"
            )
            route = request.scope.get("route")
            route_template = getattr(route, "path", None) or request.url.path
            workspace_id_from_path = _safe_workspace_id(
                request.path_params.get("project_id")
            )
            byte_count = _response_byte_count(response)
            appended = ledger.record_http_request(
                method=request.method,
                route_template=str(route_template).split("?", 1)[0],
                status_code=status_code,
                outcome=outcome,
                duration_ms=duration_ms,
                byte_count=byte_count,
                request_id=request_id,
                workspace_id=workspace_id_from_path,
                error_code=_safe_error_code(error_code),
            )
            if appended is None and not (
                outcome == "succeeded"
                and str(route_template).startswith(
                    ("/admin/tiles/", "/admin/pretrip/tiles/")
                )
            ):
                app.state.runtime_audit_degraded = True

    app.include_router(create_runtime_audit_router(ledger))


def create_runtime_audit_router(
    ledger: FileRuntimeAuditLedger,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["runtime-audit"])

    @router.get("/runtime-audit")
    def runtime_audit_records(
        event_type: str | None = None,
        outcome: str | None = None,
        category: str | None = None,
        runtime_instance_id: str | None = None,
        workspace_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> JSONResponse:
        payload = ledger.query(
            event_type=event_type,
            outcome=outcome,
            category=category,
            runtime_instance_id=runtime_instance_id,
            workspace_id=workspace_id,
            limit=limit,
        )
        return JSONResponse(
            payload.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    return router


def _response_byte_count(response: Response | None) -> int | None:
    if response is None:
        return None
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def _safe_workspace_id(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        return None
    if not all(character.isalnum() or character in "_.-" for character in text):
        return None
    return text


def _safe_error_code(value: str | None) -> str | None:
    if value is None:
        return None
    safe = "".join(
        character if character.isalnum() or character in "_.:-" else "-"
        for character in value
    ).strip("-._:")
    return safe[:128] or "unknown-error"


__all__ = [
    "create_runtime_audit_ledger",
    "create_runtime_audit_router",
    "install_runtime_audit",
]
