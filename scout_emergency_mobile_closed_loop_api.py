from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse

from scout_emergency_mobile_closed_loop_sandbox import (
    ClosedLoopSandboxBoundaryError,
    ClosedLoopSandboxConflict,
    ClosedLoopSandboxStore,
    SandboxApprovalRequest,
    SandboxRunRequest,
    SandboxTransportReceiptRequest,
)

DEFAULT_EMERGENCY_MOBILE_PAGE = (
    Path(__file__).resolve().parent
    / "docs"
    / "emergency"
    / "scout-emergency-mobile-approval-v0.html"
)


def create_emergency_mobile_ui_router(
    *,
    page_path: Path | str = DEFAULT_EMERGENCY_MOBILE_PAGE,
) -> APIRouter:
    router = APIRouter(prefix="/emergency", tags=["emergency-mobile-sandbox"])
    resolved_page = Path(page_path).expanduser()

    @router.get("/mobile-approval-v0", response_class=HTMLResponse)
    def emergency_mobile_page() -> Response:
        if not resolved_page.exists():
            raise HTTPException(status_code=404, detail="Emergency mobile page not found")
        return Response(
            resolved_page.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    return router


def create_emergency_mobile_closed_loop_router(
    *,
    store_root: Path | str,
    prefix: str = "/admin/dashboard/living",
) -> APIRouter:
    router = APIRouter(
        prefix=prefix,
        tags=["emergency-mobile-sandbox"],
    )
    store = ClosedLoopSandboxStore(store_root)

    @router.get("")
    def living_projection() -> dict[str, Any]:
        projection = store.load_current()
        return (
            projection.model_dump(mode="json")
            if projection is not None
            else store.empty_payload()
        )

    @router.get("/events")
    def living_events() -> dict[str, Any]:
        projection = store.load_current()
        if projection is None:
            return {
                "artifact_kind": "scout_emergency_mobile_closed_loop_event_projection",
                "status": "unavailable",
                "scenario_id": None,
                "event_count": 0,
                "events": [],
                "boundary": store.empty_payload()["boundary"],
            }
        return {
            "artifact_kind": "scout_emergency_mobile_closed_loop_event_projection",
            "status": "ok",
            "scenario_id": projection.scenario.scenario_id,
            "revision": projection.revision,
            "event_count": len(projection.timeline),
            "events": [event.model_dump(mode="json") for event in projection.timeline],
            "boundary": projection.boundary.model_dump(mode="json"),
        }

    @router.post("/scenarios/run")
    def run_scenario(request: SandboxRunRequest) -> dict[str, Any]:
        try:
            return store.run_scenario(request).model_dump(mode="json")
        except ClosedLoopSandboxBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ClosedLoopSandboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/approvals")
    def record_approval(request: SandboxApprovalRequest) -> dict[str, Any]:
        try:
            return store.record_approval(request).model_dump(mode="json")
        except ClosedLoopSandboxBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ClosedLoopSandboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/transport/receipts")
    def record_transport_receipt(
        request: SandboxTransportReceiptRequest,
    ) -> dict[str, Any]:
        try:
            return store.record_transport_receipt(request).model_dump(mode="json")
        except ClosedLoopSandboxBoundaryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ClosedLoopSandboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router
