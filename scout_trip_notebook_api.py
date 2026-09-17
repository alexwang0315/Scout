"""Narrow Dashboard notebook surface: local evidence GETs and stateless analysis."""
from pathlib import Path
import json
import re
import hashlib

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from scout_trip_notebook import NotebookAnalysisRequest, analyze_notebook_track, build_notebook_snapshot
from scout_contextual_permission_workbench import ContextualPermissionConflict
from scout_planning_fine_tune import PlanningPreviewRequest, PlanningAcceptRequest
import scout_planning_fine_tune as planning

ASSETS = Path(__file__).parent / "docs/admin/trip-notebook"
ASSET_TYPES = {"index.html": "text/html", "app.js": "text/javascript", "core.js": "text/javascript",
               "store.js": "text/javascript", "planning.js": "text/javascript", "style.css": "text/css", "sw.js": "text/javascript"}


def notebook_project_root(workspace_root: Path | None, project_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", project_id):
        raise HTTPException(422, "Invalid project identity")
    if workspace_root is None:
        raise HTTPException(404, "No workspace configured")
    root = workspace_root.resolve()
    candidates = [root, root / project_id]
    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            continue
        manifest = (resolved / "project.json").resolve()
        if not manifest.is_relative_to(resolved):
            continue
        try:
            if json.loads(manifest.read_text()).get("project_id") == project_id:
                return resolved
        except (OSError, ValueError):
            continue
    raise HTTPException(404, "Selected workspace was not found")


def create_trip_notebook_router(workspace_root: Path | None) -> APIRouter:
    router = APIRouter(prefix="/trip-notebook", tags=["trip-notebook"])

    @router.get("/")
    def notebook_page():
        return asset_response("index.html")

    def planning_call(project_id, action, request=None):
        root = notebook_project_root(workspace_root, project_id)
        try:
            result = action(root, request) if request is not None else action(root)
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except ContextualPermissionConflict as exc:
            raise HTTPException(409, {"code": exc.code, "message": str(exc)}) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, "計畫資料無法讀取或驗證；未回報採用成功。") from exc

    @router.get("/planning/{project_id}")
    def planning_context(project_id: str):
        return planning_call(project_id, planning.planning_context)

    @router.post("/planning/{project_id}/arrange")
    def planning_arrange(project_id: str):
        return planning_call(project_id, planning.arrange)

    @router.post("/planning/{project_id}/preview")
    def planning_preview(project_id: str, request: PlanningPreviewRequest):
        return planning_call(project_id, planning.preview, request)

    @router.post("/planning/{project_id}/accept")
    def planning_accept(project_id: str, request: PlanningAcceptRequest):
        return planning_call(project_id, planning.accept, request)

    @router.get("/snapshot/{project_id}")
    def notebook_snapshot(project_id: str):
        root = notebook_project_root(workspace_root, project_id)
        try:
            result = build_notebook_snapshot(root)
            return JSONResponse(result, headers={"Cache-Control": "no-store", "X-Scout-Notebook-Version": result["version"]})
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/analyze")
    def notebook_analysis(request: NotebookAnalysisRequest):
        try:
            return JSONResponse(analyze_notebook_track(request), headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/{filename}")
    def notebook_asset(filename: str):
        return asset_response(filename)

    return router


def asset_response(filename: str) -> Response:
    if filename not in ASSET_TYPES:
        raise HTTPException(404, "Notebook asset not found")
    headers = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'; form-action 'none'"}
    if filename == "sw.js":
        version = hashlib.sha256(b"".join((ASSETS / name).read_bytes() for name in sorted(ASSET_TYPES))).hexdigest()[:20]
        script = (ASSETS / filename).read_text().replace("__SHELL_VERSION__", version)
        return Response(script, media_type="text/javascript", headers=headers)
    return FileResponse(ASSETS / filename, media_type=ASSET_TYPES[filename], headers=headers)
