"""Explicit Recorded intake and replay actions under an existing workspace."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import quote

from fastapi import APIRouter, Response
from pydantic import Field

from scout_planned_analysis import PlannedAnalysisResumeRequest
from scout_planned_route_api import _http_error
from scout_planned_route_artifacts import (PlannedAnalysisSelectionRequest, get_analysis_selection,
    select_analysis_subject, _safe_path)
from scout_planned_route_models import PlannedModel, PlannedRouteConflict
from scout_recorded_analysis import (RecordedSetRequest, get_recorded_version,
    list_recorded_sources, list_recorded_versions, save_recorded_version, _parse_recording)
from scout_recorded_jobs import RecordedAnalysisManager, RecordedAnalysisRunRequest


class RecordedUpload(PlannedModel):
    file_name: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1)


def save_recorded_upload(root: Path, request: RecordedUpload) -> dict:
    name = request.file_name
    if Path(name).name != name or name.startswith(".") or not name.lower().endswith(".gpx") or any(c in name for c in ("\\", "\x00")):
        raise PlannedRouteConflict("invalid_recorded_filename", "Use a GPX filename without a directory.")
    raw = request.content.encode("utf-8")
    parts = _parse_recording(raw, name)
    sha = hashlib.sha256(raw).hexdigest()
    ref = f"post_analysis/completed_trips/recorded/imports/{sha}/{name}"
    target = _safe_path(root, ref)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if target.read_bytes() != raw:
            raise PlannedRouteConflict("recorded_upload_collision", "Stored recording differs from these original bytes.")
    else:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    return {"source_ref": ref, "sha256": sha, "file_name": name, "point_count": sum(map(len, parts)),
            "source_bytes_preserved": True, "candidate_only": True, "runtime_safety_truth": False}


def create_recorded_router(*, project_root_for: Callable[[str], Path]) -> APIRouter:
    router = APIRouter(tags=["recorded-post-analysis"])
    prefix = "/pretrip/projects/{project_id}/recorded-analysis"

    def run(project_id, fn, *args):
        try:
            return fn(project_root_for(project_id), *args)
        except PlannedRouteConflict as exc:
            raise _http_error(exc) from exc

    @router.get(prefix + "/sources")
    def sources(project_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, list_recorded_sources)

    @router.post(prefix + "/sources")
    def upload(project_id: str, request: RecordedUpload):
        return run(project_id, save_recorded_upload, request)

    @router.get(prefix + "/versions")
    def versions(project_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        result = run(project_id, list_recorded_versions)
        result["analysis_selection"] = run(project_id, get_analysis_selection)
        return result

    @router.post(prefix + "/versions")
    def save(project_id: str, request: RecordedSetRequest):
        return run(project_id, save_recorded_version, request)

    @router.get(prefix + "/versions/{version_id}")
    def version(project_id: str, version_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, get_recorded_version, version_id)

    @router.post(prefix + "/selection")
    def select(project_id: str, request: PlannedAnalysisSelectionRequest):
        return run(project_id, select_analysis_subject, request)

    @router.get(prefix + "/analysis-runs")
    def runs(project_id: str, response: Response, version_id: str | None = None):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: RecordedAnalysisManager(root).list(version_id))

    @router.post(prefix + "/analysis-runs", status_code=202)
    def start(project_id: str, request: RecordedAnalysisRunRequest):
        return run(project_id, lambda root: RecordedAnalysisManager(root).submit(request))

    @router.get(prefix + "/analysis-runs/{run_id}")
    def state(project_id: str, run_id: str, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return run(project_id, lambda root: RecordedAnalysisManager(root).get(run_id))

    @router.post(prefix + "/analysis-runs/{run_id}/resume", status_code=202)
    def resume(project_id: str, run_id: str, request: PlannedAnalysisResumeRequest):
        return run(project_id, lambda root: RecordedAnalysisManager(root).resume(run_id, request))

    @router.get(prefix + "/analysis-runs/{run_id}/artifact")
    def artifact(project_id: str, run_id: str, ref: str):
        data, name = run(project_id, lambda root: RecordedAnalysisManager(root).artifact(run_id, ref))
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

    @router.get(prefix + "/export/{version_id}/{format}")
    def export(project_id: str, version_id: str, format: Literal["gpx", "manifest", "comparison"]):
        bundle = run(project_id, get_recorded_version, version_id)
        name = {"gpx": "recorded.gpx", "manifest": "manifest.json", "comparison": "comparison.json"}[format]
        data = _safe_path(project_root_for(project_id), bundle["bundle_ref"] + "/" + name).read_bytes()
        return Response(data, media_type="application/gpx+xml" if format == "gpx" else "application/json",
            headers={"Cache-Control": "no-store", "X-Scout-Track-Role": "recorded",
                     "Content-Disposition": f'attachment; filename="{version_id}-{name}"'})
    return router
