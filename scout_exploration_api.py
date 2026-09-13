"""Explicit HTTP actions for zero-reference AOI workspaces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field

from scout_exploration_jobs import ExplorationJobManager, ExplorationPrepareCommand
from scout_exploration_models import ExplorationModel, ExplorationWorkspaceRequest
from scout_exploration_workspace import (
    BOUNDARY, STORE_REF, ExplorationWorkspaceError, _digest, _identity, _write,
    build_exploration_trh_requests, create_exploration_workspace, load_exploration_catalog,
)


class ExplorationTrhCommand(ExplorationModel):
    expected_intake_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    corridor_m: float = Field(default=500, ge=0)
    requested_by: str = Field(default="human_candidate_review", min_length=1)


def create_exploration_router(*, workspace_root: Path, launch: Callable | None = None,
                              preparer: Callable | None = None) -> APIRouter:
    """Mount below /admin; the owning server retains its authentication boundary."""
    base = Path(workspace_root).expanduser().resolve()
    router = APIRouter(tags=["exploration-workspaces"])
    prefix = "/pretrip/projects/{project_id}/exploration"

    def root_for(project_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", project_id):
            raise HTTPException(422, detail={"code": "invalid_project_id", "message": "Invalid exploration project ID"})
        root = base / project_id
        if root.is_symlink() or not root.is_dir() or root.resolve().parent != base:
            raise HTTPException(404, detail={"code": "exploration_project_missing", "message": "Exploration project is unavailable"})
        return root

    def action(project_id, function, *args, **kwargs):
        try:
            return function(root_for(project_id), *args, **kwargs)
        except (ExplorationWorkspaceError, OSError, ValueError) as exc:
            raise HTTPException(409, detail={"code": "exploration_conflict", "message": str(exc)}) from exc

    def manager(root):
        return ExplorationJobManager(root, launch=launch, **({"preparer": preparer} if preparer else {}))

    @router.post("/pretrip/exploration/projects", status_code=201)
    def create(request: ExplorationWorkspaceRequest) -> dict:
        try:
            created = create_exploration_workspace(base, request)
            return manager(Path(created["project_root"])).get()
        except (ExplorationWorkspaceError, OSError, ValueError) as exc:
            raise HTTPException(409, detail={"code": "exploration_conflict", "message": str(exc)}) from exc

    @router.get(prefix)
    def workspace(project_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return action(project_id, lambda root: manager(root).get())

    @router.get(prefix + "/prepare")
    def preparation_status(project_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return action(project_id, lambda root: manager(root).get())

    @router.post(prefix + "/prepare", status_code=202)
    def prepare(project_id: str, command: ExplorationPrepareCommand) -> dict:
        return action(project_id, lambda root: manager(root).submit(command))

    @router.post(prefix + "/prepare/resume", status_code=202)
    def resume(project_id: str, command: ExplorationPrepareCommand) -> dict:
        return action(project_id, lambda root: manager(root).submit(command, resume=True))

    @router.get(prefix + "/catalog")
    def catalog(project_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return action(project_id, load_exploration_catalog)

    @router.post(prefix + "/trh-request")
    def trh_request(project_id: str, command: ExplorationTrhCommand) -> dict:
        def compile_request(root):
            _, _, job = _identity(root)
            if command.expected_intake_sha256 != job["intake_sha256"]:
                raise ExplorationWorkspaceError("Refresh the exploration intake before preparing TRH requests")
            requests = [request.model_dump(mode="json") for request in build_exploration_trh_requests(
                root, corridor_m=command.corridor_m, requested_by=command.requested_by)]
            payload = {"schema_version": "scout_exploration_trh_requests.v1", "project_id": root.name,
                "intake_sha256": job["intake_sha256"], "requests": requests, "submitted": False,
                "request_count": len(requests), "scope": "A/via/B terrain hypotheses require candidate review",
                "route_activated": False, **BOUNDARY}
            ref = f"{STORE_REF}/trh_requests/{_digest(payload)}.json"
            sha = _write(root, ref, payload)
            return {**payload, "artifact_ref": ref, "artifact_sha256": sha}
        return action(project_id, compile_request)

    return router
