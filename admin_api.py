from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from xml.etree.ElementTree import ParseError

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from admin_after_action import PRETRIP_CASE_ID, ROOT, build_admin_case_view, list_admin_cases
from admin_local_raster_tiles import (
    DEFAULT_RASTER_TILE_CACHE_ROOT,
    load_or_build_raster_tile_payload,
)
from admin_tile_proxy import (
    DEFAULT_OSM_TILE_CACHE_ROOT,
    load_or_build_osm_tile_payload,
)
from admin_weather_overlay import (
    OPEN_METEO_PROVIDER,
    build_pretrip_weather_overlay,
    build_weather_api_runtime_status,
    fetch_open_meteo_weather_snapshot,
)
from pretrip_admin_view import (
    build_pretrip_admin_view,
    list_pretrip_admin_projects,
    load_pretrip_admin_surface_projection,
    load_pretrip_debug_projection_view,
    load_pretrip_debug_projection_events,
    resolve_pretrip_project_artifacts,
)
from pretrip_expert_contribution_apply_plan import (
    DEFAULT_APPLY_PLAN_REF as DEFAULT_EXPERT_CONTRIBUTION_APPLY_PLAN_REF,
    DEFAULT_WORKSPACE_APPLY_RESULT_REF as DEFAULT_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF,
    apply_expert_contributions_to_workspace,
    write_expert_contribution_apply_plan,
)
from pretrip_import import PretripImportRequest, run_pretrip_import
from pretrip_energy_projection import (
    DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
    write_pretrip_energy_reserve_projection,
)
from post_analysis_energy_feedback import (
    POST_ANALYSIS_ENERGY_FEEDBACK_REF,
    write_post_analysis_energy_feedback,
)
from scout_companion_match_admin import refresh_companion_match_review_for_workspace
from pretrip_departure_reviewed_candidates import (
    DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF,
    write_departure_reviewed_candidates_for_workspace,
)
from pretrip_layer_preparation import (
    DEFAULT_LAYERS as DEFAULT_PRETRIP_LAYER_PREPARATION_LAYERS,
    LayerPreparationRequest,
    build_layer_preparation_preview,
    run_layer_preparation,
)
from pretrip_mcp_review import append_mcp_review_action
from pretrip_review_decision_apply_store import (
    write_review_decision_apply_plan_for_workspace,
)
from pretrip_review_decision_log import ReviewDecisionCorrection, ReviewDecisionRecord
from pretrip_review_decision_store import append_review_decision, append_review_decisions
from pretrip_route_note_disposition_store import append_route_note_disposition
from pretrip_route_note_review_options import AdminDisposition
from pretrip_route_note_reviewed_assumptions import (
    DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
    write_route_note_reviewed_assumptions_for_workspace,
)
from pretrip_source_ingest import sha256_file, summarize_gpx
from pretrip_workspace_edit import (
    PreTripWorkspaceEditRequest,
    apply_pretrip_workspace_edit_to_workspace,
)
from pretrip_workspace_project import copy_pretrip_project_workspace
from scout_wearable_admin import (
    build_daily_energy_overview,
    delete_wearable_energy_artifacts,
    delete_wearable_activity_log,
    export_wearable_energy_artifacts,
    import_wearable_activity_log,
    list_wearable_inventory,
    refresh_energy_reserve_from_inventory,
    wearable_inventory_root,
)
from scout_energy_reserve import ENERGY_BASELINE_FILENAME
from scout_mobile_handoff import DEFAULT_MOBILE_HANDOFF_FILENAME, build_mobile_energy_companion_handoff
from scout_wearable_daily_home import build_daily_home_preview
from scout_wearable_validator import validate_wearable_activity_summary_contract


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


class PreTripReviewDecisionBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[PreTripReviewDecisionRequest] = Field(min_length=1, max_length=100)
    persist_to_workspace: bool = False


class PreTripRouteNoteDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_note_ref: str = Field(min_length=1)
    disposition: AdminDisposition
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    decided_at: str | None = None
    persist_to_workspace: bool = False


class PreTripMcpReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_id: str = Field(min_length=1)
    decision: Literal["accepted", "linked", "split", "downgraded", "rejected"]
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    summary: str = Field(min_length=1)
    linked_cp_candidate_id: str | None = Field(default=None, min_length=1)
    split_target_ids: list[str] = Field(default_factory=list)
    downgrade_reason: str | None = Field(default=None, min_length=1)
    decided_at: str | None = None
    persist_to_workspace: bool = False


class PreTripImportGpxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    golden_route_gpx: str = Field(min_length=1)
    reference_dir: str | None = Field(default=None, min_length=1)
    reference_gpx: list[str] = Field(default_factory=list)
    reference_gpx_paths: list[str] = Field(default_factory=list)
    workspace_root: str | None = Field(default=None, min_length=1)
    profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = "pi-offline"
    template_project_root: str | None = Field(default=None, min_length=1)
    checkpoint_spacing_m: float = Field(default=1_500.0, gt=0)
    max_reference_display_points: int = Field(default=1_000, gt=0)
    import_timestamp: str | None = None
    import_stage: Literal["pretrip"] = "pretrip"
    overwrite: bool = False

    @model_validator(mode="after")
    def normalize_blank_paths(self) -> "PreTripImportGpxRequest":
        self.reference_dir = self.reference_dir.strip() or None if self.reference_dir else None
        self.workspace_root = self.workspace_root.strip() or None if self.workspace_root else None
        self.template_project_root = (
            self.template_project_root.strip() or None
            if self.template_project_root
            else None
        )
        combined = [
            path.strip()
            for path in [*self.reference_gpx_paths, *self.reference_gpx]
            if path.strip()
        ]
        self.reference_gpx_paths = combined
        self.reference_gpx = combined
        return self


class PreTripImportGpxRunRequest(PreTripImportGpxRequest):
    confirm_import: bool = False


class PreTripPrepareLayersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layers: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PRETRIP_LAYER_PREPARATION_LAYERS)
    )
    workspace_root: str | None = Field(default=None, min_length=1)
    profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = "pi-offline"
    network_mode: Literal["no-network", "explicit-fetch"] = "no-network"
    allow_network_fetch: bool = False
    route_corridor_m: float = Field(default=500.0, gt=0)
    bbox: dict[str, Any] | None = None
    prepared_at: str | None = None

    @model_validator(mode="after")
    def normalize_layers_and_workspace(self) -> "PreTripPrepareLayersRequest":
        self.layers = [layer.strip() for layer in self.layers if layer.strip()]
        self.workspace_root = self.workspace_root.strip() or None if self.workspace_root else None
        return self


class PreTripPrepareLayersRunRequest(PreTripPrepareLayersRequest):
    confirm_prepare: bool = False


class WearableImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1)
    overwrite: bool = False


class WearableEnergyRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_date: str | None = None


class WearableEnergyExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicit_consent: bool = False
    output_path: str | None = None
    include_reserve_summary: bool = False


class WearableEnergyDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_exports: bool = True


class WearableMobileHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_date: str | None = None
    companion_match_review_path: str | None = None


class CompanionMatchRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_capsule_paths: list[str] = Field(default_factory=list)
    candidate_profile_refs: list[str] | None = None
    review_score_threshold: int = Field(default=75, ge=0, le=100)


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
    resolved_wearable_inventory_root = wearable_inventory_root(_data_root_from_env())

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

    @router.get("/wearables")
    def wearable_inventory() -> dict[str, Any]:
        return list_wearable_inventory(
            inventory_root=resolved_wearable_inventory_root,
        ).model_dump(mode="json")

    @router.post("/wearables/validate")
    def wearable_validate(request: WearableImportRequest) -> dict[str, Any]:
        try:
            return validate_wearable_activity_summary_contract(
                _path_from_admin_request(request.source_path),
                root=ROOT,
            ).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/import")
    def wearable_import(request: WearableImportRequest) -> dict[str, Any]:
        try:
            return import_wearable_activity_log(
                source_path=_path_from_admin_request(request.source_path),
                inventory_root=resolved_wearable_inventory_root,
                source_root=ROOT,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/wearables/{activity_id}")
    def wearable_delete(activity_id: str) -> dict[str, Any]:
        return _delete_wearable_activity(
            activity_id=activity_id,
            inventory_root=resolved_wearable_inventory_root,
        )

    @router.post("/wearables/delete")
    def wearable_delete_post(request: dict[str, str]) -> dict[str, Any]:
        activity_id = request.get("activity_id")
        if not activity_id:
            raise HTTPException(status_code=422, detail="activity_id is required")
        return _delete_wearable_activity(
            activity_id=activity_id,
            inventory_root=resolved_wearable_inventory_root,
        )

    def _delete_wearable_activity(
        *,
        activity_id: str,
        inventory_root: Path,
    ) -> dict[str, Any]:
        try:
            return delete_wearable_activity_log(
                activity_id=activity_id,
                inventory_root=inventory_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/refresh-energy")
    def wearable_refresh_energy(request: WearableEnergyRefreshRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            return refresh_energy_reserve_from_inventory(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/daily-energy")
    def wearable_daily_energy(request: WearableEnergyRefreshRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            return build_daily_energy_overview(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
                write_artifact=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/daily-home-preview")
    def wearable_daily_home_preview(request: WearableEnergyRefreshRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            return build_daily_home_preview(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
                write_artifact=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/wearables/daily-home-preview", response_class=HTMLResponse)
    def wearable_daily_home_preview_page() -> str:
        try:
            result = build_daily_home_preview(
                inventory_root=resolved_wearable_inventory_root,
                write_artifact=True,
            )
            return Path(result["html_path"]).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/mobile-handoff")
    def wearable_mobile_handoff(request: WearableMobileHandoffRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            daily_result = build_daily_home_preview(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
                write_artifact=True,
            )
            return build_mobile_energy_companion_handoff(
                daily_home_preview_path=Path(daily_result["preview_path"]),
                companion_match_review_path=_optional_path_from_admin_request(
                    request.companion_match_review_path
                ),
                output_path=(
                    resolved_wearable_inventory_root
                    / "outputs"
                    / DEFAULT_MOBILE_HANDOFF_FILENAME
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/export-energy")
    def wearable_export_energy(request: WearableEnergyExportRequest) -> dict[str, Any]:
        try:
            return export_wearable_energy_artifacts(
                inventory_root=resolved_wearable_inventory_root,
                explicit_consent=request.explicit_consent,
                output_path=_optional_path_from_admin_request(request.output_path),
                include_reserve_summary=request.include_reserve_summary,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/delete-energy")
    def wearable_delete_energy(request: WearableEnergyDeleteRequest) -> dict[str, Any]:
        try:
            return delete_wearable_energy_artifacts(
                inventory_root=resolved_wearable_inventory_root,
                include_exports=request.include_exports,
            )
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/pretrip/projects")
    def pretrip_projects() -> dict[str, Any]:
        return {
            "projects": list_pretrip_admin_projects(
                workspace_root=pretrip_workspace_root,
            )
        }

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
        runtime_status = build_weather_api_runtime_status()
        live_weather_snapshot = None
        if runtime_status.ready and runtime_status.provider == OPEN_METEO_PROVIDER:
            try:
                live_weather_snapshot = fetch_open_meteo_weather_snapshot(
                    view["route"]["bounds"]
                )
            except Exception as exc:
                live_weather_snapshot = {
                    "artifact_kind": "open_meteo_weather_snapshot",
                    "status": "live_summary_failed",
                    "provider": OPEN_METEO_PROVIDER,
                    "external_api_calls_made": True,
                    "raw_payloads_embedded": False,
                    "authoritative_weather_computed": False,
                    "human_review_required": True,
                    "error_summary": str(exc),
                }
        return build_pretrip_weather_overlay(
            weather_payload,
            runtime_status=runtime_status,
            live_weather_snapshot=live_weather_snapshot,
        )

    @router.get("/pretrip/projects/{project_id}/admin-projection")
    def pretrip_project_admin_projection(project_id: str) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            return load_pretrip_admin_surface_projection(
                project_id,
                project_root=project_root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip admin projection not found",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/debug-projection-events")
    def pretrip_project_debug_projection_events(project_id: str) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            return load_pretrip_debug_projection_events(
                project_id,
                project_root=project_root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip debug projection events not found",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/debug-projection")
    def pretrip_project_debug_projection(project_id: str) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            return load_pretrip_debug_projection_view(
                project_id,
                project_root=project_root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip debug projection not found",
            ) from exc

    @router.post("/pretrip/projects/{project_id}/import-gpx-preview")
    def pretrip_import_gpx_preview(
        project_id: str,
        request: PreTripImportGpxRequest,
    ) -> dict[str, Any]:
        try:
            return _build_pretrip_import_gpx_preview(
                project_id=project_id,
                request=request,
                pretrip_workspace_root=pretrip_workspace_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ParseError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/pretrip/projects/{project_id}/import-gpx")
    def pretrip_import_gpx(
        project_id: str,
        request: PreTripImportGpxRunRequest,
    ) -> dict[str, Any]:
        if not request.confirm_import:
            raise HTTPException(
                status_code=400,
                detail="confirm_import=true is required",
            )

        try:
            workspace_root = _pretrip_import_workspace_root(
                pretrip_workspace_root,
                request=request,
            )
            _build_pretrip_import_gpx_preview(
                project_id=project_id,
                request=request,
                pretrip_workspace_root=pretrip_workspace_root,
            )
            manifest = run_pretrip_import(
                PretripImportRequest(
                    project_id=project_id,
                    primary_gpx=_path_from_admin_request(request.golden_route_gpx),
                    reference_dir=_optional_path_from_admin_request(request.reference_dir),
                    reference_gpx_paths=tuple(
                        _path_from_admin_request(path)
                        for path in request.reference_gpx_paths
                    ),
                    workspace_root=workspace_root,
                    profile=request.profile,
                    template_project_root=_optional_path_from_admin_request(
                        request.template_project_root
                    ),
                    checkpoint_spacing_m=request.checkpoint_spacing_m,
                    max_reference_display_points=request.max_reference_display_points,
                    overwrite=request.overwrite,
                    import_timestamp=request.import_timestamp,
                    import_stage="pretrip",
                )
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError, ParseError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        project_root = (workspace_root.expanduser() / project_id).resolve()
        outputs = manifest.get("outputs", {})
        manifest_path = project_root / outputs.get("import_manifest_ref", "")
        admin_projection_path = project_root / outputs.get("admin_projection_ref", "")
        debug_projection_events_path = (
            project_root / outputs.get("debug_projection_events_ref", "")
        )
        route_note_candidates_path = project_root / outputs.get(
            "route_note_candidates_ref",
            "",
        )
        route_note_ln_proposals_path = project_root / outputs.get(
            "route_note_ln_proposals_ref",
            "",
        )
        gis_perception_ai_judgements_path = project_root / outputs.get(
            "gis_perception_ai_judgements_ref",
            "",
        )
        gis_perception_candidates_path = project_root / outputs.get(
            "gis_perception_candidates_ref",
            "",
        )
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_import_gpx_result",
            "persisted": True,
            "preview": False,
            "manifest": manifest,
            "paths": {
                "project_root": str(project_root),
                "project": str(project_root / "project.json"),
                "project_path": str(project_root / "project.json"),
                "import_manifest": str(manifest_path),
                "manifest_path": str(manifest_path),
                "admin_projection": str(admin_projection_path),
                "admin_projection_path": str(admin_projection_path),
                "debug_projection_events": str(debug_projection_events_path),
                "debug_projection_events_path": str(debug_projection_events_path),
                "route_note_candidates": str(route_note_candidates_path),
                "route_note_candidates_path": str(route_note_candidates_path),
                "route_note_ln_proposals": str(route_note_ln_proposals_path),
                "route_note_ln_proposals_path": str(route_note_ln_proposals_path),
                "gis_perception_ai_judgements": str(gis_perception_ai_judgements_path),
                "gis_perception_ai_judgements_path": str(
                    gis_perception_ai_judgements_path
                ),
                "gis_perception_candidates": str(gis_perception_candidates_path),
                "gis_perception_candidates_path": str(gis_perception_candidates_path),
            },
            "boundary": _pretrip_import_gpx_boundary(
                request,
                admin_api_write_performed=True,
            ),
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_import_outputs_mutated": True,
            },
        }

    @router.get("/pretrip/projects/{project_id}/layer-preparation")
    def pretrip_project_layer_preparation(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            view = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc
        return view["layer_preparation"]

    @router.post("/pretrip/projects/{project_id}/prepare-layers-preview")
    def pretrip_prepare_layers_preview(
        project_id: str,
        request: PreTripPrepareLayersRequest,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_prepare_layers_project_root(
                pretrip_workspace_root,
                project_id=project_id,
                request=request,
            )
            manifest = build_layer_preparation_preview(
                _pretrip_prepare_layers_request(
                    project_id=project_id,
                    project_root=project_root,
                    request=request,
                )
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_layer_preparation_preview_result",
            "preview": True,
            "persisted": False,
            "manifest": manifest,
            "paths": _pretrip_prepare_layers_paths(project_root, manifest),
            "boundary": {
                **manifest["boundary"],
                "admin_api_write_performed": False,
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": False,
                "workspace_layer_outputs_mutated": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/prepare-layers")
    def pretrip_prepare_layers(
        project_id: str,
        request: PreTripPrepareLayersRunRequest,
    ) -> dict[str, Any]:
        if not request.confirm_prepare:
            raise HTTPException(
                status_code=400,
                detail="confirm_prepare=true is required",
            )

        try:
            project_root = _pretrip_prepare_layers_project_root(
                pretrip_workspace_root,
                project_id=project_id,
                request=request,
            )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError(
                    "prepare-layers writes only project workspaces, not repo fixtures"
                )
            manifest = run_layer_preparation(
                _pretrip_prepare_layers_request(
                    project_id=project_id,
                    project_root=project_root,
                    request=request,
                )
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_layer_preparation_result",
            "preview": False,
            "persisted": True,
            "manifest": manifest,
            "paths": _pretrip_prepare_layers_paths(project_root, manifest),
            "boundary": {
                **manifest["boundary"],
                "admin_api_write_performed": True,
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
                "workspace_layer_outputs_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/refresh-energy-projection")
    def pretrip_refresh_energy_projection(
        project_id: str,
        request: WearableEnergyRefreshRequest,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            if project_root is None:
                raise FileNotFoundError(
                    "pretrip energy projection requires a local workspace project"
                )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError("pretrip energy projection writes only project workspaces")
            baseline_path = resolved_wearable_inventory_root / "outputs" / ENERGY_BASELINE_FILENAME
            if not baseline_path.exists():
                reference_date = (
                    datetime.fromisoformat(request.reference_date).date()
                    if request.reference_date
                    else None
                )
                refresh_energy_reserve_from_inventory(
                    inventory_root=resolved_wearable_inventory_root,
                    reference_date=reference_date,
                )
            project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
            eta_plan_path = project_root / project.get("planned_eta_ref", "outputs/planned_eta.json")
            output_path = project_root / DEFAULT_PRETRIP_ENERGY_PROJECTION_REF
            projection = write_pretrip_energy_reserve_projection(
                eta_plan_path=eta_plan_path,
                energy_baseline_path=baseline_path,
                output_path=output_path,
                project_root=project_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_energy_projection_refresh_result",
            "persisted": True,
            "projection": projection.model_dump(mode="json"),
            "paths": {
                "project_root": str(project_root),
                "eta_plan": str(eta_plan_path),
                "energy_baseline": str(baseline_path),
                "energy_projection": str(output_path),
            },
            "boundary": projection.boundary.model_dump(mode="json"),
            "mutation": {
                "workspace_energy_projection_written": True,
                "project_source_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "safety_api_called": False,
                "fixture_files_mutated": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/refresh-companion-match")
    def pretrip_refresh_companion_match(
        project_id: str,
        request: CompanionMatchRefreshRequest,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            if project_root is None:
                raise FileNotFoundError(
                    "companion match refresh requires a local workspace project"
                )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError("companion match refresh writes only project workspaces")
            result = refresh_companion_match_review_for_workspace(
                inventory_root=resolved_wearable_inventory_root,
                project_root=project_root,
                candidate_capsule_paths=[
                    _path_from_admin_request(path)
                    for path in request.candidate_capsule_paths
                ],
                candidate_profile_refs=request.candidate_profile_refs,
                review_score_threshold=request.review_score_threshold,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            **result,
        }

    @router.post("/pretrip/projects/{project_id}/refresh-energy-feedback")
    def pretrip_refresh_energy_feedback(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            if project_root is None:
                raise FileNotFoundError(
                    "energy feedback refresh requires a local workspace project"
                )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError("energy feedback refresh writes only project workspaces")
            pretrip_projection_path = project_root / DEFAULT_PRETRIP_ENERGY_PROJECTION_REF
            capability_timeline_path = project_root / "outputs" / "capability_timeline.json"
            output_path = project_root / POST_ANALYSIS_ENERGY_FEEDBACK_REF
            feedback = write_post_analysis_energy_feedback(
                pretrip_projection_path=pretrip_projection_path,
                capability_timeline_path=capability_timeline_path,
                output_path=output_path,
                root=project_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "post_analysis_energy_feedback_refresh_result",
            "persisted": True,
            "post_analysis_energy_feedback": feedback.model_dump(mode="json"),
            "paths": {
                "project_root": str(project_root),
                "pretrip_projection": str(pretrip_projection_path),
                "capability_timeline": str(capability_timeline_path),
                "post_analysis_energy_feedback": str(output_path),
            },
            "boundary": {
                **feedback.boundary.model_dump(mode="json"),
                "workspace_mutation_allowed": True,
                "workspace_file_written": True,
                "pretrip_eta_autocalibration_allowed": False,
                "mission_graph_compile_allowed": False,
                "runtime_safety_truth": False,
            },
            "mutation": {
                "workspace_energy_feedback_written": True,
                "project_source_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "safety_api_called": False,
                "fixture_files_mutated": False,
                "raw_health_payload_shared": False,
                "raw_track_shared": False,
            },
        }

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

    @router.get("/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png")
    def imagery_tile(project_id: str, layer_id: str, z: int, x: int, y: int) -> Response:
        try:
            payload = load_or_build_raster_tile_payload(
                project_id,
                layer_id,
                z,
                x,
                y,
                cache_root=_raster_tile_cache_root_from_env(),
                fallback_enabled=_raster_tile_fallback_enabled_from_env(),
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

        try:
            record = _build_review_decision_record(project_id, project, request)
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

    @router.post("/pretrip/projects/{project_id}/review-decisions-batch")
    def pretrip_review_decision_batch(
        project_id: str,
        request: PreTripReviewDecisionBatchRequest,
    ) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            project = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        try:
            records = [
                _build_review_decision_record(project_id, project, decision_request)
                for decision_request in request.decisions
            ]
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        response = {
            "project_id": project_id,
            "artifact_kind": "pretrip_review_decision_batch_preview",
            "preview": True,
            "append_only": True,
            "record_count": len(records),
            "records": [record.model_dump(mode="json") for record in records],
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
                "batch_atomic_validation": True,
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
            decision_log = append_review_decisions(log_path, records)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        response["artifact_kind"] = "pretrip_review_decision_batch"
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

    @router.post("/pretrip/projects/{project_id}/mcp-review-actions")
    def pretrip_mcp_review_action(
        project_id: str,
        request: PreTripMcpReviewActionRequest,
    ) -> dict[str, Any]:
        if not request.persist_to_workspace:
            return {
                "project_id": project_id,
                "artifact_kind": "pretrip_mcp_review_action_preview",
                "preview": True,
                "append_only": True,
                "record": request.model_dump(mode="json"),
                "boundary": {
                    "candidate_only": True,
                    "workspace_file_mutation_allowed": False,
                    "source_mutation_allowed": False,
                    "package_mutation_allowed": False,
                    "runtime_mutation_allowed": False,
                    "phase1_runtime_mutation_allowed": False,
                    "phase2_writeback_allowed": False,
                    "external_api_calls_made": False,
                    "admin_api_write_performed": False,
                    "fixture_file_mutation_allowed": False,
                    "compiles_mission_graph": False,
                },
                "mutation": {
                    "workspace_files_mutated": False,
                    "runtime_mutated": False,
                    "phase1_runtime_mutated": False,
                    "phase2_writeback_performed": False,
                    "fixture_files_mutated": False,
                },
            }

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "MCP review persistence requires create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace project.json"
                ),
            )
        if _pretrip_project_root_is_repo_fixture(project_root):
            raise HTTPException(
                status_code=409,
                detail="MCP review actions write only local workspaces, not repo fixtures",
            )
        try:
            log = append_mcp_review_action(
                project_root,
                mcp_id=request.mcp_id,
                decision=request.decision,
                summary=request.summary,
                reviewer_alias=request.reviewer_alias,
                decided_at=request.decided_at,
                linked_cp_candidate_id=request.linked_cp_candidate_id,
                split_target_ids=tuple(request.split_target_ids),
                downgrade_reason=request.downgrade_reason,
            )
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_mcp_review_action",
            "preview": False,
            "persisted": True,
            "append_only": True,
            "counts": {
                "action_count": log.action_count,
                "runtime_truth_count": 0,
                "compile_count": 0,
            },
            "boundary": {
                "candidate_only": True,
                "workspace_file_mutation_allowed": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "compiles_mission_graph": False,
                "workspace_project_root": str(project_root),
            },
            "mutation": {
                "workspace_files_mutated": True,
                "workspace_mcp_review_log_mutated": True,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/workspace-edits")
    def pretrip_workspace_edit(
        project_id: str,
        request: PreTripWorkspaceEditRequest,
    ) -> dict[str, Any]:
        if not request.persist_to_workspace:
            raise HTTPException(
                status_code=409,
                detail="workspace edit operations require persist_to_workspace=true",
            )

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "workspace edit operations require create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace project.json"
                ),
            )

        try:
            return apply_pretrip_workspace_edit_to_workspace(project_root, request)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

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

    @router.post("/pretrip/projects/{project_id}/departure-reviewed-candidates")
    def pretrip_departure_reviewed_candidates(project_id: str) -> dict[str, Any]:
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
                    "departure reviewed candidates require "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            package = write_departure_reviewed_candidates_for_workspace(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        output_path = project_root / DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF
        return {
            "project_id": project_id,
            "artifact_kind": package.artifact_kind,
            "persisted": True,
            "counts": package.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "final_mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "not_departure_approval": True,
                "workspace_project_root": str(project_root),
                "workspace_departure_reviewed_candidates_path": str(output_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "final_mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_departure_reviewed_candidates_mutated": True,
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
            pretrip_project_root = (
                _pretrip_workspace_project_root(
                    pretrip_workspace_root,
                    project_id=case_id,
                )
                if case_id == PRETRIP_CASE_ID
                else None
            )
            return build_admin_case_view(
                case_id,
                incident_store_path=resolved_incident_store_path,
                pretrip_project_root=pretrip_project_root,
            )
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


def _build_review_decision_record(
    project_id: str,
    project: dict[str, Any],
    request: PreTripReviewDecisionRequest,
) -> ReviewDecisionRecord:
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
        draft_action["action_id"]
        if draft_action
        else f"review_draft.{project_id}.api.{request.candidate_ref}"
    )
    correction = (
        ReviewDecisionCorrection(**request.correction.model_dump())
        if request.correction is not None
        else None
    )

    return ReviewDecisionRecord(
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


def _review_decision_preview_id(
    project_id: str,
    request: PreTripReviewDecisionRequest,
) -> str:
    candidate_ref = request.candidate_ref.replace("/", "_")
    return f"review_decision_preview.{project_id}.{request.decision}.{candidate_ref}"


def _build_pretrip_import_gpx_preview(
    *,
    project_id: str,
    request: PreTripImportGpxRequest,
    pretrip_workspace_root: Path | None,
) -> dict[str, Any]:
    _validate_pretrip_import_project_id(project_id)
    if request.profile == "pi-online-explicit":
        raise ValueError("pi-online-explicit is reserved for a later audited network slice")

    workspace_root = _pretrip_import_workspace_root(
        pretrip_workspace_root,
        request=request,
    )
    golden_route = _path_from_admin_request(request.golden_route_gpx).resolve()
    if not golden_route.exists():
        raise FileNotFoundError(f"golden route GPX not found: {golden_route}")
    if not golden_route.is_file():
        raise ValueError(f"golden route GPX is not a file: {golden_route}")

    template_root = _optional_path_from_admin_request(request.template_project_root)
    if template_root is not None and not template_root.exists():
        raise FileNotFoundError(f"template project root not found: {template_root}")
    if template_root is not None and not template_root.is_dir():
        raise ValueError(f"template project root is not a directory: {template_root}")

    reference_paths = _pretrip_import_reference_paths(
        request,
        golden_route=golden_route,
    )
    route_summary = summarize_gpx(
        golden_route,
        f"artifact.gpx.{project_id}",
    ).model_dump(mode="json")
    project_root = (workspace_root.expanduser() / project_id).resolve()
    project_exists = project_root.exists()
    blocking_reasons = (
        ["target project workspace already exists and overwrite=false"]
        if project_exists and not request.overwrite
        else []
    )
    golden_source_record = _pretrip_import_source_record(
        golden_route,
        role=_pretrip_import_golden_route_role(request),
    )
    reference_source_records = [
        _pretrip_import_source_record(path, role="reference_track")
        for path in reference_paths
    ]

    return {
        "project_id": project_id,
        "artifact_kind": "pretrip_import_gpx_preview",
        "preview": True,
        "persisted": False,
        "profile": request.profile,
        "import_stage": request.import_stage,
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "project_root": str(project_root),
        "project_exists": project_exists,
        "overwrite_requested": request.overwrite,
        "plan": {
            "workspace_project_root": str(project_root),
            "target_project_exists": project_exists,
            "overwrite": request.overwrite,
            "can_run": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "profile": request.profile,
            "import_stage": request.import_stage,
            "checkpoint_spacing_m": request.checkpoint_spacing_m,
            "max_reference_display_points": request.max_reference_display_points,
            "golden_route_count": 1,
            "reference_track_count": len(reference_paths),
            "source_file_count": 1 + len(reference_paths),
            "output_paths": _pretrip_import_output_paths(project_root),
        },
        "inputs": {
            "golden_route_gpx": golden_source_record,
            "reference_tracks": reference_source_records,
            "template_project_root": str(template_root) if template_root else None,
        },
        "provenance": {
            "golden_route_gpx": {
                **golden_source_record,
                "route_summary": route_summary,
            },
            "reference_tracks": reference_source_records,
        },
        "route_summary": route_summary,
        "counts": {
            "source_file_count": 1 + len(reference_paths),
            "golden_route_count": 1,
            "reference_track_count": len(reference_paths),
            "route_point_count": route_summary["point_count"],
        },
        "settings": {
            "checkpoint_spacing_m": request.checkpoint_spacing_m,
            "max_reference_display_points": request.max_reference_display_points,
        },
        "planning_semantics": _pretrip_import_gpx_planning_semantics(request),
        "boundary": _pretrip_import_gpx_boundary(
            request,
            admin_api_write_performed=False,
        ),
        "mutation": {
            "source_mutated": False,
            "package_mutated": False,
            "mission_graph_mutated": False,
            "runtime_mutated": False,
            "phase1_runtime_mutated": False,
            "phase2_writeback_performed": False,
            "workspace_files_mutated": False,
        },
    }


def _pretrip_import_workspace_root(
    pretrip_workspace_root: Path | None,
    *,
    request: PreTripImportGpxRequest,
) -> Path:
    if request.workspace_root:
        return _path_from_admin_request(request.workspace_root)
    if pretrip_workspace_root is not None:
        return Path(pretrip_workspace_root).expanduser()
    raise HTTPException(
        status_code=409,
        detail="Import GPX requires create_admin_app(pretrip_workspace_root=...).",
    )


def _pretrip_prepare_layers_project_root(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
    request: PreTripPrepareLayersRequest,
) -> Path:
    if request.workspace_root:
        workspace_root = _path_from_admin_request(request.workspace_root)
        project_root = workspace_root.expanduser() / project_id
    elif pretrip_workspace_root is not None:
        project_root = Path(pretrip_workspace_root).expanduser() / project_id
    else:
        raise HTTPException(
            status_code=409,
            detail=(
                "Prepare layers requires create_admin_app("
                "pretrip_workspace_root=...) or workspace_root."
            ),
        )
    project_path = project_root / "project.json"
    if not project_path.exists():
        raise FileNotFoundError(f"project.json not found: {project_path}")
    return project_root.resolve()


def _pretrip_prepare_layers_request(
    *,
    project_id: str,
    project_root: Path,
    request: PreTripPrepareLayersRequest,
) -> LayerPreparationRequest:
    return LayerPreparationRequest(
        project_id=project_id,
        project_root=project_root,
        layers=tuple(request.layers),
        profile=request.profile,
        network_mode=request.network_mode,
        allow_network_fetch=request.allow_network_fetch,
        bbox=request.bbox,
        route_corridor_m=request.route_corridor_m,
        prepared_at=request.prepared_at,
    )


def _pretrip_prepare_layers_paths(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, str]:
    outputs = manifest.get("outputs", {})
    return {
        "project_root": str(project_root),
        "project": str(project_root / "project.json"),
        "project_path": str(project_root / "project.json"),
        "layer_preparation_manifest": str(
            project_root / outputs.get("layer_preparation_manifest_ref", "")
        ),
        "manifest_path": str(
            project_root / outputs.get("layer_preparation_manifest_ref", "")
        ),
        "layer_preparation_job": str(
            project_root / outputs.get("layer_preparation_job_ref", "")
        ),
        "summary": str(
            project_root / outputs.get("layer_preparation_summary_ref", "")
        ),
        "adapter_manifest": str(
            project_root / outputs.get("layer_adapter_manifest_ref", "")
        ),
        "validation_report": str(
            project_root / outputs.get("layer_validation_report_ref", "")
        ),
        "map_projection": str(
            project_root / outputs.get("layer_map_projection_ref", "")
        ),
        "debug_projection_events": str(
            project_root / outputs.get("layer_debug_projection_events_ref", "")
        ),
    }


def _pretrip_import_reference_paths(
    request: PreTripImportGpxRequest,
    *,
    golden_route: Path,
) -> list[Path]:
    candidates = [
        _path_from_admin_request(path).resolve()
        for path in request.reference_gpx_paths
    ]
    if request.reference_dir:
        reference_dir = _path_from_admin_request(request.reference_dir).resolve()
        if not reference_dir.exists():
            raise FileNotFoundError(f"reference directory not found: {reference_dir}")
        if not reference_dir.is_dir():
            raise ValueError(f"reference directory is not a directory: {reference_dir}")
        candidates.extend(sorted(reference_dir.glob("*.gpx")))

    unique: dict[str, Path] = {}
    for path in candidates:
        resolved = path.resolve()
        if resolved == golden_route:
            continue
        if not resolved.exists():
            raise FileNotFoundError(f"reference GPX not found: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"reference GPX is not a file: {resolved}")
        unique[resolved.as_posix()] = resolved
    return [unique[key] for key in sorted(unique)]


def _path_from_admin_request(value: str) -> Path:
    if "://" in value:
        raise ValueError("Import GPX requires local filesystem paths.")
    return Path(value).expanduser()


def _optional_path_from_admin_request(value: str | None) -> Path | None:
    return _path_from_admin_request(value) if value else None


def _pretrip_import_source_record(path: Path, *, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "uri": path.resolve().as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
    }


def _pretrip_import_output_paths(project_root: Path) -> dict[str, str]:
    output_refs = {
        "project": "project.json",
        "import_manifest": "outputs/import_manifest.json",
        "admin_projection": "outputs/admin_projection.json",
        "debug_projection_events": "outputs/debug_projection_events.jsonl",
        "pretrip_package": "outputs/pretrip_package.json",
        "route_summary": "normalized/routes/route_summary.json",
        "checkpoints": "candidates/checkpoints.json",
        "segments": "candidates/segments.json",
        "route_note_candidates": "candidates/route_note_candidates.json",
        "gis_perception_ai_judgements": "outputs/gis_perception_ai_judgements.json",
        "route_note_ln_proposals": "outputs/route_note_ln_proposals.json",
        "gis_perception_candidates": "outputs/gis_perception_candidates.json",
    }
    return {
        key: str((project_root / ref).resolve())
        for key, ref in output_refs.items()
    }


def _pretrip_import_golden_route_role(request: PreTripImportGpxRequest) -> str:
    return "golden_route_reference"


def _pretrip_import_gpx_planning_semantics(
    request: PreTripImportGpxRequest,
) -> dict[str, Any]:
    return {
        "golden_route": {
            "role": _pretrip_import_golden_route_role(request),
            "meaning": "selected similar reference route before departure",
            "actual_user_track": False,
            "runtime_safety_truth": False,
        },
        "pretrip_actual_user_track_exists": False,
        "manual_waypoint_route_policy": {
            "unwalked_route_sections_allowed": True,
            "manual_waypoints_required": True,
            "danger_review_required": True,
        },
    }


def _pretrip_import_gpx_boundary(
    request: PreTripImportGpxRequest,
    *,
    admin_api_write_performed: bool,
) -> dict[str, Any]:
    return {
        "pretrip_candidate_evidence_only": True,
        "golden_route_is_reference_evidence": True,
        "actual_user_track_available": False,
        "actual_user_track_required_before_post_analysis": True,
        "network_calls_allowed": False,
        "external_api_calls_made": False,
        "admin_api_write_performed": admin_api_write_performed,
        "workspace_file_mutation_allowed": admin_api_write_performed,
        "fixture_file_mutation_allowed": False,
        "source_mutation_allowed": False,
        "package_mutation_allowed": False,
        "mission_graph_mutation_allowed": False,
        "runtime_mutation_allowed": False,
        "compiles_mission_graph": False,
        "final_mission_graph_compiled": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "raw_gpx_embedded_in_json": False,
        "unwalked_route_sections_require_manual_waypoints": True,
        "unwalked_route_sections_require_danger_review": True,
    }


def _validate_pretrip_import_project_id(project_id: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if (
        not project_id
        or project_id in {".", ".."}
        or any(char not in allowed for char in project_id)
    ):
        raise ValueError(f"project_id contains unsafe characters: {project_id}")


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


def _pretrip_project_root_is_repo_fixture(project_root: Path) -> bool:
    fixture_root = (ROOT / "tests" / "fixtures" / "pretrip" / "projects").resolve()
    resolved = project_root.resolve()
    try:
        resolved.relative_to(fixture_root)
    except ValueError:
        return False
    return True


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


def _data_root_from_env() -> Path:
    value = os.getenv("SCOUT_DATA_ROOT")
    return Path(value).expanduser() if value else Path("/data/scout")


def _osm_tile_cache_root_from_env() -> Path:
    value = os.getenv("SCOUT_ADMIN_OSM_TILE_CACHE_ROOT")
    return Path(value).expanduser() if value else DEFAULT_OSM_TILE_CACHE_ROOT.expanduser()


def _osm_tile_fallback_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_OSM_TILE_FALLBACK", "true")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _raster_tile_cache_root_from_env() -> Path:
    value = os.getenv("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT")
    return (
        Path(value).expanduser()
        if value
        else DEFAULT_RASTER_TILE_CACHE_ROOT.expanduser()
    )


def _raster_tile_fallback_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_RASTER_TILE_FALLBACK", "true")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
