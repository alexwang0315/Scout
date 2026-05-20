from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from admin_after_action import ROOT, build_admin_case_view, list_admin_cases
from admin_tile_proxy import (
    DEFAULT_OSM_TILE_CACHE_ROOT,
    load_or_build_osm_tile_payload,
)
from admin_weather_overlay import (
    build_pretrip_weather_overlay,
    build_weather_api_runtime_status,
)
from pretrip_admin_view import (
    build_pretrip_admin_view,
    list_pretrip_admin_projects,
    resolve_pretrip_project_artifacts,
)
from pretrip_expert_contribution_apply_plan import (
    DEFAULT_APPLY_PLAN_REF as DEFAULT_EXPERT_CONTRIBUTION_APPLY_PLAN_REF,
    DEFAULT_WORKSPACE_APPLY_RESULT_REF as DEFAULT_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF,
    apply_expert_contributions_to_workspace,
    write_expert_contribution_apply_plan,
)
from pretrip_review_decision_apply_store import (
    write_review_decision_apply_plan_for_workspace,
)
from pretrip_review_decision_log import ReviewDecisionCorrection, ReviewDecisionRecord
from pretrip_review_decision_store import append_review_decision
from pretrip_route_note_disposition_store import append_route_note_disposition
from pretrip_route_note_review_options import AdminDisposition
from pretrip_route_note_reviewed_assumptions import (
    DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
    write_route_note_reviewed_assumptions_for_workspace,
)
from pretrip_workspace_project import copy_pretrip_project_workspace


DEFAULT_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase1-after-action.html"
DEFAULT_PRETRIP_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
DEFAULT_ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"


class PreTripReviewDecisionCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    field_updates: dict[str, Any] = Field(default_factory=dict)
    replacement_ref_ids: list[str] = Field(default_factory=list)


class PreTripReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ref: str = Field(min_length=1)
    decision: Literal["accepted", "corrected", "rejected"]
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    summary: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    draft_action_id: str | None = None
    decided_at: str | None = None
    correction: PreTripReviewDecisionCorrectionRequest | None = None
    persist_to_workspace: bool = False

    @model_validator(mode="after")
    def enforce_correction_shape(self) -> "PreTripReviewDecisionRequest":
        if self.decision == "corrected" and self.correction is None:
            raise ValueError("corrected decision requires correction")
        if self.decision != "corrected" and self.correction is not None:
            raise ValueError("correction is only allowed for corrected decisions")
        return self


class PreTripRouteNoteDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_note_ref: str = Field(min_length=1)
    disposition: AdminDisposition
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    decided_at: str | None = None
    persist_to_workspace: bool = False


def create_admin_app(
    *,
    incident_store_path: Path | None = None,
    pretrip_workspace_root: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Scout Fusion Admin API")
    app.include_router(
        create_admin_router(
            incident_store_path=incident_store_path,
            pretrip_workspace_root=pretrip_workspace_root,
        )
    )
    return app


def create_admin_router(
    *,
    incident_store_path: Path | None = None,
    pretrip_workspace_root: Path | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])
    resolved_incident_store_path = incident_store_path or _incident_store_from_env()

    @router.get("", response_class=HTMLResponse)
    def admin_page() -> str:
        if not DEFAULT_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Admin page not found")
        return DEFAULT_ADMIN_PAGE.read_text(encoding="utf-8")

    @router.get("/pretrip", response_class=HTMLResponse)
    def pretrip_admin_page() -> str:
        if not DEFAULT_PRETRIP_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Pre-trip admin page not found")
        return DEFAULT_PRETRIP_ADMIN_PAGE.read_text(encoding="utf-8")

    @router.get("/scout-assistant-ui.js")
    def assistant_ui_script() -> Response:
        if not DEFAULT_ASSISTANT_UI_SCRIPT.exists():
            raise HTTPException(status_code=404, detail="Assistant UI script not found")
        return Response(
            DEFAULT_ASSISTANT_UI_SCRIPT.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    @router.get("/cases")
    def cases() -> dict[str, Any]:
        return {"cases": list_admin_cases()}

    @router.get("/pretrip/projects")
    def pretrip_projects() -> dict[str, Any]:
        return {"projects": list_pretrip_admin_projects()}

    @router.get("/pretrip/projects/{project_id}")
    def pretrip_project(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            return build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

    @router.get("/pretrip/projects/{project_id}/weather-overlay")
    def pretrip_project_weather_overlay(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            view = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        weather_payload = {**view["weather"], "project_id": project_id}
        return build_pretrip_weather_overlay(
            weather_payload,
            runtime_status=build_weather_api_runtime_status(),
        )

    @router.get("/tiles/osm/{z}/{x}/{y}.png")
    def osm_tile(z: int, x: int, y: int) -> Response:
        try:
            payload = load_or_build_osm_tile_payload(
                z,
                x,
                y,
                cache_root=_osm_tile_cache_root_from_env(),
                fallback_enabled=_osm_tile_fallback_enabled_from_env(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return Response(
            payload.body,
            media_type=payload.media_type,
            headers=payload.headers(),
        )

    @router.post("/pretrip/projects/{project_id}/workspace")
    def pretrip_project_workspace(project_id: str) -> dict[str, Any]:
        try:
            artifacts = resolve_pretrip_project_artifacts(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        if pretrip_workspace_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "workspace copy requires create_admin_app("
                    "pretrip_workspace_root=...)"
                ),
            )

        workspace_destination_root = Path(pretrip_workspace_root).expanduser()
        workspace_project_root = workspace_destination_root / project_id
        if workspace_project_root.exists():
            raise HTTPException(
                status_code=409,
                detail=f"workspace project root already exists: {workspace_project_root}",
            )

        try:
            manifest = copy_pretrip_project_workspace(
                artifacts["project"].parent,
                workspace_destination_root,
                project_id=project_id,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_workspace_copy",
            "persisted": True,
            "manifest": manifest,
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": manifest["workspace_root"],
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/review-decisions")
    def pretrip_review_decision(
        project_id: str,
        request: PreTripReviewDecisionRequest,
    ) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            project = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        queue_item = _find_review_queue_item(project, request.candidate_ref)
        if queue_item is None:
            raise HTTPException(status_code=422, detail="candidate_ref is not in the review queue")

        draft_action = _find_review_draft_action(project, request.candidate_ref)
        target_ids = (
            request.target_ids
            or queue_item.get("review_focus")
            or queue_item.get("map_target_ids")
            or [request.candidate_ref]
        )
        decided_at = request.decided_at or datetime.now(timezone.utc).isoformat()
        draft_action_id = request.draft_action_id or (
            draft_action["action_id"] if draft_action else f"review_draft.{project_id}.api.{request.candidate_ref}"
        )
        correction = (
            ReviewDecisionCorrection(**request.correction.model_dump())
            if request.correction is not None
            else None
        )

        try:
            record = ReviewDecisionRecord(
                decision_id=_review_decision_preview_id(project_id, request),
                draft_action_id=draft_action_id,
                decision=request.decision,
                candidate_ref=request.candidate_ref,
                target_ids=target_ids,
                source_review_queue_item_refs=[
                    {
                        "review_queue_manifest_id": project["review_queue"]["source_id"],
                        "item_id": queue_item["item_id"],
                        "source_ref": queue_item["source_ref"],
                        "candidate_ref": request.candidate_ref,
                    }
                ],
                reviewer_alias=request.reviewer_alias,
                decided_at=decided_at,
                summary=request.summary,
                correction=correction,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        response = {
            "project_id": project_id,
            "artifact_kind": "pretrip_review_decision_preview",
            "preview": True,
            "append_only": True,
            "record": record.model_dump(mode="json"),
            "boundary": {
                "append_only": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": False,
                "fixture_file_mutation_allowed": False,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
            },
        }
        if not request.persist_to_workspace:
            return response

        log_path = _pretrip_workspace_review_log_path(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if log_path is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "persist_to_workspace requires create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace review log"
                ),
            )
        try:
            decision_log = append_review_decision(log_path, record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        response["artifact_kind"] = "pretrip_review_decision"
        response["preview"] = False
        response["persisted"] = True
        response["counts"] = decision_log.counts.model_dump(mode="json")
        response["boundary"]["admin_api_write_performed"] = True
        response["boundary"]["workspace_file_mutation_allowed"] = True
        response["boundary"]["workspace_review_log_path"] = str(log_path)
        response["mutation"]["workspace_files_mutated"] = True
        response["mutation"]["workspace_review_log_mutated"] = True
        return response

    @router.post("/pretrip/projects/{project_id}/route-note-dispositions")
    def pretrip_route_note_disposition(
        project_id: str,
        request: PreTripRouteNoteDispositionRequest,
    ) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        if not request.persist_to_workspace:
            raise HTTPException(
                status_code=409,
                detail=(
                    "route-note disposition persistence requires "
                    "persist_to_workspace=true and create_admin_app("
                    "pretrip_workspace_root=...)"
                ),
            )

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "route-note disposition persistence requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        decided_at = request.decided_at or datetime.now(timezone.utc).isoformat()
        try:
            log = append_route_note_disposition(
                project_root,
                route_note_ref=request.route_note_ref,
                disposition=request.disposition,
                reviewer_alias=request.reviewer_alias,
                decided_at=decided_at,
            )
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        log_path = project_root / "reviews" / "route_note_disposition_log.json"
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_route_note_disposition_log",
            "persisted": True,
            "counts": log.counts.model_dump(mode="json"),
            "record": log.records[-1].model_dump(mode="json"),
            "boundary": {
                "append_only": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_route_note_disposition_log_path": str(log_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_route_note_disposition_log_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/review-decision-apply-plan")
    def pretrip_review_decision_apply_plan(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "review-decision apply plan regeneration requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            plan = write_review_decision_apply_plan_for_workspace(project_root)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        apply_plan_path = _pretrip_workspace_apply_plan_path(project_root)
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_review_decision_apply_plan",
            "persisted": True,
            "counts": plan.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_apply_plan_path": str(apply_plan_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_review_decision_apply_plan_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/route-note-reviewed-assumptions")
    def pretrip_route_note_reviewed_assumptions(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "route-note reviewed assumptions require "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            assumptions = write_route_note_reviewed_assumptions_for_workspace(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        output_path = project_root / DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF
        return {
            "project_id": project_id,
            "artifact_kind": assumptions.artifact_kind,
            "persisted": True,
            "counts": assumptions.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_route_note_reviewed_assumptions_path": str(output_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_route_note_reviewed_assumptions_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/expert-contribution-apply-plan")
    def pretrip_expert_contribution_apply_plan(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "expert contribution apply plan generation requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            plan = write_expert_contribution_apply_plan(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        apply_plan_path = project_root / DEFAULT_EXPERT_CONTRIBUTION_APPLY_PLAN_REF
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_expert_contribution_apply_plan",
            "persisted": True,
            "counts": plan.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "candidate_artifact_mutation_allowed": False,
                "external_import_queue_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_expert_contribution_apply_plan_path": str(apply_plan_path),
            },
            "mutation": {
                "source_mutated": False,
                "candidate_artifacts_mutated": False,
                "external_import_queue_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_expert_contribution_apply_plan_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/expert-contribution-workspace-apply-result")
    def pretrip_expert_contribution_workspace_apply_result(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "expert contribution workspace apply requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            result = apply_expert_contributions_to_workspace(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        result_path = project_root / DEFAULT_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF
        return {
            "project_id": project_id,
            "artifact_kind": result.artifact_kind,
            "persisted": True,
            "counts": result.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "workspace_candidate_artifact_mutation_allowed": True,
                "workspace_external_import_queue_mutation_allowed": True,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_expert_contribution_apply_result_path": str(result_path),
            },
            "mutation": {
                "source_mutated": False,
                "workspace_candidate_artifacts_mutated": True,
                "workspace_external_import_queue_mutated": True,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_expert_contribution_apply_result_mutated": True,
            },
        }

    @router.get("/cases/{case_id}")
    def case(case_id: str) -> dict[str, Any]:
        try:
            return build_admin_case_view(case_id, incident_store_path=resolved_incident_store_path)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Admin case not found") from exc

    return router


def _find_review_queue_item(project: dict[str, Any], candidate_ref: str) -> dict[str, Any] | None:
    for item in project["review_queue"]["items"]:
        if item.get("candidate_ref") == candidate_ref:
            return item
    return None


def _find_review_draft_action(project: dict[str, Any], candidate_ref: str) -> dict[str, Any] | None:
    for action in project["review_draft_log"]["actions"]:
        if action.get("candidate_ref") == candidate_ref:
            return action
    return None


def _review_decision_preview_id(
    project_id: str,
    request: PreTripReviewDecisionRequest,
) -> str:
    candidate_ref = request.candidate_ref.replace("/", "_")
    return f"review_decision_preview.{project_id}.{request.decision}.{candidate_ref}"


def _pretrip_workspace_review_log_path(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return None

    candidate = project_root / "reviews" / "review_decision_log.json"
    return candidate if candidate.exists() else None


def _pretrip_workspace_project_root(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    if pretrip_workspace_root is None:
        return None

    root = Path(pretrip_workspace_root).expanduser()
    candidates = [
        root / "project.json",
        root / project_id / "project.json",
        root
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / project_id
        / "project.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.parent
    return None


def _pretrip_workspace_apply_plan_path(project_root: Path) -> Path:
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    apply_plan_ref = project.get(
        "review_decision_apply_plan_ref",
        "outputs/review_decision_apply_plan.json",
    )
    return project_root / str(apply_plan_ref)


def _incident_store_from_env() -> Path | None:
    value = os.getenv("SCOUT_SAFETY_INCIDENT_STORE")
    return Path(value).expanduser() if value else None


def _osm_tile_cache_root_from_env() -> Path:
    value = os.getenv("SCOUT_ADMIN_OSM_TILE_CACHE_ROOT")
    return Path(value).expanduser() if value else DEFAULT_OSM_TILE_CACHE_ROOT.expanduser()


def _osm_tile_fallback_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_OSM_TILE_FALLBACK", "true")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
