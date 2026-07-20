from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import HTMLResponse

from scout_emergency_mobile_closed_loop_sandbox import (
    SandboxApprovalRequest,
    SandboxTransportSimulationRequest,
)
from scout_alpha_simulation_sandbox import (
    AlphaSandboxAdvanceRequest,
    AlphaSandboxBoundaryError,
    AlphaSandboxConflict,
    AlphaSandboxError,
    AlphaSandboxInteractionRequest,
    AlphaSandboxRunRequest,
    AlphaSandboxStore,
    alpha_scenario_catalog,
)


DEFAULT_ALPHA_SANDBOX_PAGE = (
    Path(__file__).resolve().parent
    / "docs"
    / "emergency"
    / "scout-alpha-sandbox-v0.html"
)


def create_alpha_simulation_ui_router(
    *,
    page_path: Path | str = DEFAULT_ALPHA_SANDBOX_PAGE,
) -> APIRouter:
    router = APIRouter(prefix="/emergency", tags=["alpha-simulation-sandbox"])
    resolved_page = Path(page_path).expanduser()

    @router.get("/sandbox-alpha-v0", response_class=HTMLResponse)
    def alpha_sandbox_page() -> Response:
        if not resolved_page.exists():
            raise HTTPException(status_code=404, detail="Alpha sandbox page not found")
        return Response(
            resolved_page.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; connect-src 'self'; "
                    "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'none'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


def create_alpha_simulation_router(
    *,
    store_root: Path | str,
    prefix: str = "/admin/dashboard/living/alpha",
    default_workspace_root: Path | str | None = None,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["alpha-simulation-sandbox"])
    store = AlphaSandboxStore(store_root)
    configured_workspace = (
        Path(default_workspace_root).expanduser().resolve()
        if default_workspace_root is not None
        else None
    )
    run_defaults = _run_defaults(configured_workspace)

    def require_configured_workspace() -> Path:
        if configured_workspace is None or not run_defaults["workspace_configured"]:
            raise HTTPException(
                status_code=503,
                detail="Alpha sandbox requires a valid server-configured workspace",
            )
        return configured_workspace

    def require_current_workspace_match() -> None:
        workspace = require_configured_workspace()
        current = store.load_current()
        if current is None:
            return
        request_path = (
            store.root
            / "runs"
            / current.scenario.run_id
            / "scenario_request.json"
        )
        try:
            persisted = json.loads(request_path.read_text(encoding="utf-8"))
            persisted_workspace = Path(str(persisted["workspace_root"])).resolve()
            persisted_gpx_ref = str(persisted["gpx_ref"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                status_code=409,
                detail="current Alpha sandbox state has invalid workspace lineage",
            ) from exc
        if (
            persisted_workspace != workspace
            or persisted_gpx_ref != run_defaults["gpx_ref"]
        ):
            raise HTTPException(
                status_code=409,
                detail="current Alpha sandbox state belongs to another workspace source",
            )

    @router.get("")
    def current_projection() -> dict[str, Any]:
        require_current_workspace_match()
        current = store.load_current()
        return (
            current.model_dump(mode="json")
            if current is not None
            else store.empty_payload()
        )

    @router.get("/scenarios")
    def scenario_catalog() -> dict[str, Any]:
        scenarios = [item.model_dump(mode="json") for item in alpha_scenario_catalog()]
        return {
            "status": "success",
            "summary": f"{len(scenarios)} Alpha sandbox scenarios available.",
            "next_actions": ["prepare a scenario with POST /runs"],
            "artifacts": [],
            "scenario_count": len(scenarios),
            "scenarios": scenarios,
            "run_defaults": run_defaults,
            "boundary": store.empty_payload()["boundary"],
        }

    @router.post("/runs")
    def prepare_run(request: AlphaSandboxRunRequest) -> dict[str, Any]:
        workspace = require_configured_workspace()
        if request.workspace_root is not None:
            requested_workspace = Path(request.workspace_root).expanduser().resolve()
            if requested_workspace != workspace:
                raise HTTPException(
                    status_code=400,
                    detail="workspace_root is pinned to the server-configured sandbox workspace",
                )
        if request.project_id not in {None, run_defaults["project_id"]}:
            raise HTTPException(
                status_code=400,
                detail="project_id is pinned to the server-configured sandbox workspace",
            )
        if request.gpx_ref not in {None, run_defaults["gpx_ref"]}:
            raise HTTPException(
                status_code=400,
                detail="gpx_ref is pinned to the server-selected canonical route",
            )
        resolved = AlphaSandboxRunRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "workspace_root": str(workspace),
                "project_id": run_defaults["project_id"],
                "gpx_ref": run_defaults["gpx_ref"],
            }
        )
        return _invoke(lambda: store.prepare(resolved))

    @router.post("/advance")
    def advance_run(request: AlphaSandboxAdvanceRequest) -> dict[str, Any]:
        require_current_workspace_match()
        return _invoke(lambda: store.advance(request))

    @router.post("/interactions")
    def record_interaction(
        request: AlphaSandboxInteractionRequest,
    ) -> dict[str, Any]:
        require_current_workspace_match()
        return _invoke(lambda: store.record_interaction(request))

    @router.post("/approvals")
    def record_approval(request: SandboxApprovalRequest) -> dict[str, Any]:
        require_current_workspace_match()
        return _invoke(lambda: store.record_approval(request))

    @router.post("/transport/simulations")
    def record_transport_simulation(
        request: SandboxTransportSimulationRequest,
    ) -> dict[str, Any]:
        require_current_workspace_match()
        return _invoke(lambda: store.record_transport_simulation(request))

    return router


def _invoke(operation: Any) -> dict[str, Any]:
    try:
        return operation().model_dump(mode="json")
    except AlphaSandboxBoundaryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AlphaSandboxConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AlphaSandboxError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _run_defaults(workspace: Path | None) -> dict[str, Any]:
    invalid = {
        "workspace_configured": False,
        "workspace_ref": workspace.name if workspace is not None else None,
        "project_id": None,
        "gpx_ref": None,
    }
    if workspace is None or not workspace.is_dir():
        return invalid
    project_path = workspace / "project.json"
    try:
        if (
            not project_path.is_file()
            or project_path.is_symlink()
            or project_path.stat().st_size > 1_048_576
        ):
            return invalid
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return invalid
    if not isinstance(project, dict) or project.get("actual_user_track_available") is not False:
        return invalid
    project_id = project.get("project_id")
    selected: Path | None = None
    candidates = sorted(
        (workspace / "normalized/routes/filtered").glob("*.gpx"),
        key=lambda path: (
            "primary." not in path.name,
            "speed_filtered" not in path.name,
            path.name,
        ),
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(workspace)
        except (OSError, ValueError):
            continue
        if candidate.is_symlink() or not resolved.is_file():
            continue
        selected = resolved
        break
    if selected is None:
        return invalid
    gpx_ref = selected.relative_to(workspace).as_posix()
    try:
        AlphaSandboxRunRequest.model_validate(
            {
                "scenario_id": "alpha-server-default-validation",
                "run_id": "alpha-server-default-validation",
                "project_id": project_id,
                "workspace_root": str(workspace),
                "gpx_ref": gpx_ref,
            }
        )
    except ValueError:
        return invalid
    return {
        "workspace_configured": True,
        "workspace_ref": workspace.name,
        "project_id": project_id,
        "gpx_ref": gpx_ref,
    }


__all__ = [
    "DEFAULT_ALPHA_SANDBOX_PAGE",
    "create_alpha_simulation_router",
    "create_alpha_simulation_ui_router",
]
