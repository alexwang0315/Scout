"""Planned route HTTP actions mounted in the existing project workbench router."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException, Response

from scout_planned_route_artifacts import (
    PlannedAnalysisSelectionRequest,
    PlannedReviewRequest,
    PlannedSaveRequest,
    PlannedTrailSourceRequest,
    acquire_planned_trail_sources,
    export_planned_version,
    get_analysis_selection,
    get_planned_version,
    list_planned_versions,
    preview_for_review,
    review_planned_version,
    save_planned_version,
    select_analysis_subject,
)
from scout_planned_route_models import PlannedRouteConflict, PlannedRouteRequest
from scout_planned_analysis import (
    PlannedAnalysisResumeRequest, PlannedAnalysisRunRequest, manager_for,
)


def _http_error(error: PlannedRouteConflict) -> HTTPException:
    status = 422 if error.code.startswith("invalid_") else 409
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def create_planned_route_router(*, project_root_for: Callable[[str], Path]) -> APIRouter:
    router = APIRouter(tags=["planned-route-candidates"])
    prefix = "/pretrip/projects/{project_id}/planned-route"

    def run(project_id: str, action, *args):
        try:
            return action(project_root_for(project_id), *args)
        except PlannedRouteConflict as exc:
            raise _http_error(exc) from exc

    @router.get(prefix + "/catalog")
    def catalog(project_id: str, response: Response) -> dict:
        from scout_planned_route import load_planned_catalog
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, load_planned_catalog)

    @router.post(prefix + "/sources/overpass")
    def overpass_sources(project_id: str, request: PlannedTrailSourceRequest) -> dict:
        return run(project_id, acquire_planned_trail_sources, request)

    @router.post(prefix + "/preview")
    def preview(project_id: str, request: PlannedRouteRequest, response: Response) -> dict:
        from scout_planned_route import compile_planned_route
        response.headers["Cache-Control"] = "no-store"
        return preview_for_review(run(project_id, compile_planned_route, request))

    @router.get(prefix + "/versions")
    def versions(project_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, list_planned_versions)

    @router.post(prefix + "/versions")
    def save(project_id: str, request: PlannedSaveRequest) -> dict:
        return run(project_id, save_planned_version, request)

    @router.get(prefix + "/versions/{version_id}")
    def version(project_id: str, version_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, get_planned_version, version_id)

    @router.post(prefix + "/review")
    def review(project_id: str, request: PlannedReviewRequest) -> dict:
        return run(project_id, review_planned_version, request)

    @router.get(prefix + "/analysis-selection")
    def selection(project_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, get_analysis_selection)

    @router.post(prefix + "/analysis-selection")
    def select(project_id: str, request: PlannedAnalysisSelectionRequest) -> dict:
        return run(project_id, select_analysis_subject, request)

    @router.get(prefix + "/analysis-runs")
    def analysis_runs(project_id: str, response: Response, version_id: str | None = None) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: manager_for(root).list(version_id))

    @router.post(prefix + "/analysis-runs", status_code=202)
    def start_analysis(project_id: str, request: PlannedAnalysisRunRequest) -> dict:
        return run(project_id, lambda root: manager_for(root).submit(request))

    @router.get(prefix + "/analysis-runs/{run_id}")
    def analysis_run(project_id: str, run_id: str, response: Response) -> dict:
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: manager_for(root).get(run_id))

    @router.post(prefix + "/analysis-runs/{run_id}/resume", status_code=202)
    def resume_analysis(project_id: str, run_id: str, request: PlannedAnalysisResumeRequest) -> dict:
        return run(project_id, lambda root: manager_for(root).resume(run_id, request))

    @router.get(prefix + "/analysis-runs/{run_id}/artifact")
    def analysis_artifact(project_id: str, run_id: str, ref: str) -> Response:
        import mimetypes
        from urllib.parse import quote
        data, filename = run(project_id, lambda root: manager_for(root).artifact(run_id, ref))
        return Response(data, media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                        headers={"Cache-Control": "no-store",
                                 "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
                                 "X-Scout-Runtime-Safety-Truth": "false"})

    @router.get(prefix + "/export/{version_id}/{format}")
    def export(project_id: str, version_id: str, format: Literal["gpx", "manifest", "bundle"]) -> Response:
        data, media_type, filename = run(project_id, export_planned_version, version_id, format)
        return Response(content=data, media_type=media_type, headers={
            "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Scout-Track-Role": "planned-candidate", "X-Scout-Runtime-Safety-Truth": "false",
        })

    return router
