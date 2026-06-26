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
from admin_imagery_sources import imagery_source_for_project
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
from scout_gee_integration import build_gee_runtime_status
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
from pretrip_gpx_filter import DEFAULT_MAX_REASONABLE_SPEED_KMH
from pretrip_import import (
    DEFAULT_CHECKPOINT_SPACING_M,
    PretripImportRequest,
    run_pretrip_import,
)
from pretrip_energy_projection import (
    DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
    write_pretrip_energy_reserve_projection,
)
from post_analysis_energy_feedback import (
    POST_ANALYSIS_ENERGY_FEEDBACK_REF,
    write_post_analysis_energy_feedback,
)
from post_analysis_completed_trip_scenarios import (
    list_completed_trip_scenarios,
    load_active_completed_trip_scenario_projection,
    select_completed_trip_scenario_for_post_analysis,
)
from post_analysis_completed_trip_recordings import (
    list_completed_trip_recordings,
    load_active_completed_trip_recording_projection,
    select_completed_trip_recording_for_post_analysis,
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
from scout_energy_reserve import (
    ENERGY_BASELINE_FILENAME,
    write_energy_reserve_artifacts_from_provider_sync_package,
    write_provider_live_executor_rehearsal,
    write_provider_live_executor_response_inbox_batch_receipt,
    write_provider_live_executor_response_inbox_batch_consumption,
    write_provider_live_executor_response_inbox_consumption,
    write_provider_live_executor_response_inbox_status_snapshot,
    write_provider_live_executor_pickup_response_consumption_receipt,
    write_provider_live_executor_pickup_response_consumption,
    write_provider_live_executor_pickup_status_snapshot,
    write_provider_live_executor_lifecycle_audit,
    write_provider_live_executor_production_readiness_gate,
    write_provider_live_executor_response_consumption,
)
from scout_energy_reserve_monitor import build_energy_reserve_monitor_from_view
from scout_mobile_handoff import DEFAULT_MOBILE_HANDOFF_FILENAME, build_mobile_energy_companion_handoff
from scout_runtime_physiologic_integration import (
    run_physio_integration_replay,
    write_physio_review_from_health_auto_export,
)
from scout_wearable_daily_home import build_daily_home_preview
from scout_wearable_provider_transport import (
    write_provider_live_connector_reference,
    write_provider_live_credential_vault_reference,
    write_provider_live_network_policy_reference,
    write_provider_live_phase1_safety_boundary_reference,
    write_provider_live_runtime_ingest_boundary_reference,
    write_provider_live_executor_fixture_replay,
    write_provider_live_executor_handoff_package,
    write_provider_live_executor_handoff_outbox_index,
    write_provider_live_executor_handoff_pickup_manifest,
    write_provider_live_executor_handoff_fixture_replay,
    write_provider_live_executor_pickup_response_manifest,
    write_provider_live_executor_registration,
    write_provider_live_executor_readiness,
    write_provider_live_executor_response_inbox_index,
    write_provider_live_executor_response_manifest,
    write_provider_live_transport_materialization,
    write_provider_live_transport_response_admission_from_executor_response_manifest,
    write_provider_live_transport_response_admission_from_fixture_replay,
    write_provider_live_transport_preflight,
    write_provider_live_transport_response_admission,
    write_provider_live_transport_request_plan,
    write_provider_live_transport_sync_package,
)
from scout_wearable_validator import validate_wearable_activity_summary_contract


DEFAULT_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase1-after-action.html"
DEFAULT_PRETRIP_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
DEFAULT_ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"
DEFAULT_ROUTE_CONTEXT_BRIEFING_REF = "outputs/briefings/route_context_briefing.html"


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
    checkpoint_spacing_m: float = Field(default=DEFAULT_CHECKPOINT_SPACING_M, gt=0)
    max_reference_display_points: int = Field(default=1_000, gt=0)
    max_reasonable_gpx_speed_kmh: float = Field(
        default=DEFAULT_MAX_REASONABLE_SPEED_KMH,
        gt=0,
    )
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


class WearableProviderLivePreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    account_ref: str = Field(min_length=1)
    device_ref: str | None = None
    auth_token_ref: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False


class WearableProviderLiveCredentialVaultReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    vault_ref: str = Field(min_length=1)
    account_ref: str = Field(min_length=1)
    device_ref: str | None = None
    token_ref: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveConnectorReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    connector_kind: Literal[
        "apple_healthkit_local_bridge_connector",
        "garmin_health_api_connector",
    ]
    connector_ref: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    connector_binary_ref: str | None = None
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveNetworkPolicyReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    policy_ref: str = Field(min_length=1)
    endpoint_ref: str = Field(min_length=1)
    egress_profile_ref: str | None = None
    tls_profile_ref: str | None = None
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveRuntimeIngestBoundaryReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    runtime_boundary_ref: str = Field(min_length=1)
    runtime_channel_ref: str = Field(min_length=1)
    artifact_kinds: list[str] = Field(min_length=1)
    handoff_mode: Literal[
        "post_analysis_reference_only",
        "advisory_energy_reference_only",
    ] = "post_analysis_reference_only"
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLivePhase1SafetyBoundaryReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    phase1_boundary_ref: str = Field(min_length=1)
    phase1_state_ref: str = Field(min_length=1)
    advisory_channel_ref: str = Field(min_length=1)
    artifact_kinds: list[str] = Field(min_length=1)
    handoff_mode: Literal[
        "advisory_reference_only",
        "post_analysis_reference_only",
        "advisory_energy_reference_only",
    ] = "advisory_reference_only"
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveRequestPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight_path: str | None = None
    window_start_date: str = Field(min_length=1)
    window_end_date: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)


class WearableProviderLiveResponseAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorReadinessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight_path: str = Field(min_length=1)
    executor_kind: Literal["apple_healthkit_local_bridge", "garmin_health_api_client"]
    executor_ref: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorRehearsalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveFixtureReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorHandoffOutboxIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox_dir: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorHandoffPickupManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox_index_path: str = Field(min_length=1)
    handoff_source_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveHandoffFixtureReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_handoff_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_handoff_path: str = Field(min_length=1)
    response_payload_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorPickupResponseManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_manifest_path: str = Field(min_length=1)
    response_payload_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseInboxIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_dir: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_response_manifest_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorResponseConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_response_manifest_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorPickupResponseConsumptionReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_response_consumption_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorPickupStatusSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_manifest_path: str = Field(min_length=1)
    executor_response_manifest_path: str | None = None
    pickup_response_consumption_path: str | None = None
    pickup_response_receipt_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorLifecycleAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_status_snapshot_path: str = Field(min_length=1)
    inbox_status_snapshot_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorProductionReadinessGateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_audit_path: str = Field(min_length=1)
    connector_reference_path: str | None = None
    credential_vault_reference_path: str | None = None
    network_policy_reference_path: str | None = None
    runtime_ingest_boundary_reference_path: str | None = None
    phase1_safety_boundary_reference_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseInboxConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_index_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    manifest_source_path: str | None = None
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorResponseInboxBatchConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_index_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorResponseInboxBatchReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_consumption_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseInboxStatusSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_index_path: str = Field(min_length=1)
    batch_consumption_path: str | None = None
    batch_receipt_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveReplayAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_replay_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveMaterializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admission_path: str = Field(min_length=1)
    output_dir: str | None = None
    overwrite: bool = False


class WearableProviderLiveSyncPackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialization_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveEnergyBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_package_path: str = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None


class WearablePhysioReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1)
    previous_source_path: str | None = None
    activity_type: Literal["walking", "hiking"] = "walking"
    window_minutes: int = Field(default=15, ge=1, le=60)
    output_dir: str | None = None


class WearablePhysioSensorLoggerReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensorlogger_vitals_path: str = Field(min_length=1)
    baseline_path: str | None = None
    baseline_context: dict[str, Any] | None = None
    route_context_path: str | None = None
    route_context: dict[str, Any] | None = None
    activity_type: Literal["walking", "hiking", "running", "other"] = "hiking"
    window_minutes: int = Field(default=15, ge=1, le=60)
    max_records: int = Field(default=1000, ge=1, le=10000)
    output_dir: str | None = None


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
    def admin_page() -> Response:
        if not DEFAULT_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Admin page not found")
        return Response(
            DEFAULT_ADMIN_PAGE.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/pretrip", response_class=HTMLResponse)
    def pretrip_admin_page() -> Response:
        if not DEFAULT_PRETRIP_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Pre-trip admin page not found")
        return Response(
            DEFAULT_PRETRIP_ADMIN_PAGE.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

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

    @router.get("/post-analysis/completed-trip-scenarios")
    def completed_trip_scenarios() -> dict[str, Any]:
        try:
            return list_completed_trip_scenarios(
                data_root=_data_root_from_env(),
                root=ROOT,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/post-analysis/completed-trip-scenarios/{scenario_id}/select")
    def select_completed_trip_scenario(scenario_id: str) -> dict[str, Any]:
        try:
            result = select_completed_trip_scenario_for_post_analysis(
                scenario_id,
                data_root=_data_root_from_env(),
                root=ROOT,
            )
            _attach_energy_reserve_monitor(
                result,
                inventory_root=resolved_wearable_inventory_root,
                surface="admin",
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Completed trip scenario not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/post-analysis/completed-trip-recordings")
    def completed_trip_recordings() -> dict[str, Any]:
        try:
            return list_completed_trip_recordings(
                data_root=_data_root_from_env(),
                root=ROOT,
            )
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/post-analysis/completed-trip-recordings/{recording_id}/select")
    def select_completed_trip_recording(recording_id: str) -> dict[str, Any]:
        try:
            result = select_completed_trip_recording_for_post_analysis(
                recording_id,
                data_root=_data_root_from_env(),
                root=ROOT,
            )
            _attach_energy_reserve_monitor(
                result,
                inventory_root=resolved_wearable_inventory_root,
                surface="admin",
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Completed trip recording not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

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

    @router.post("/wearables/physio-review")
    def wearable_physio_review(request: WearablePhysioReviewRequest) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "physiologic-review",
            )
            return write_physio_review_from_health_auto_export(
                _path_from_admin_request(request.source_path),
                previous_zip_path=_optional_path_from_admin_request(request.previous_source_path),
                output_dir=output_dir,
                activity_type=request.activity_type,
                window_minutes=request.window_minutes,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/physio-sensorlogger-replay")
    def wearable_physio_sensorlogger_replay(
        request: WearablePhysioSensorLoggerReplayRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "physiologic-sensorlogger-replay",
            )
            route_context = request.route_context
            if route_context is None and request.route_context_path:
                route_context = _load_admin_json(_path_from_admin_request(request.route_context_path))
            result = run_physio_integration_replay(
                _path_from_admin_request(request.sensorlogger_vitals_path),
                output_dir=output_dir,
                route_context=route_context,
                baseline_context=request.baseline_context,
                baseline_path=_optional_path_from_admin_request(request.baseline_path),
                activity_type=request.activity_type,
                window_minutes=request.window_minutes,
                max_records=request.max_records,
            )
            return result.model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
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

    @router.post("/wearables/provider-live-preflight")
    def wearable_provider_live_preflight(request: WearableProviderLivePreflightRequest) -> dict[str, Any]:
        try:
            output_path = (
                resolved_wearable_inventory_root
                / "outputs"
                / f"{request.provider}_preflight.json"
            )
            return write_provider_live_transport_preflight(
                provider=request.provider,
                output_path=output_path,
                explicit_consent=request.explicit_consent,
                account_ref=request.account_ref,
                device_ref=request.device_ref,
                auth_token_ref=request.auth_token_ref,
                scopes=request.scopes,
                requested_capabilities=request.capabilities,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-credential-vault-reference")
    def wearable_provider_live_credential_vault_reference(
        request: WearableProviderLiveCredentialVaultReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-credential-vault-references",
            )
            return write_provider_live_credential_vault_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_credential_vault_reference.json",
                explicit_consent=request.explicit_consent,
                vault_ref=request.vault_ref,
                account_ref=request.account_ref,
                device_ref=request.device_ref,
                token_ref=request.token_ref,
                scopes=request.scopes,
                capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-connector-reference")
    def wearable_provider_live_connector_reference(
        request: WearableProviderLiveConnectorReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-connector-references",
            )
            return write_provider_live_connector_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_connector_reference.json",
                explicit_consent=request.explicit_consent,
                connector_kind=request.connector_kind,
                connector_ref=request.connector_ref,
                connector_version=request.connector_version,
                connector_binary_ref=request.connector_binary_ref,
                supported_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-network-policy-reference")
    def wearable_provider_live_network_policy_reference(
        request: WearableProviderLiveNetworkPolicyReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-network-policy-references",
            )
            return write_provider_live_network_policy_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_network_policy_reference.json",
                explicit_consent=request.explicit_consent,
                policy_ref=request.policy_ref,
                endpoint_ref=request.endpoint_ref,
                egress_profile_ref=request.egress_profile_ref,
                tls_profile_ref=request.tls_profile_ref,
                allowed_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-runtime-ingest-boundary-reference")
    def wearable_provider_live_runtime_ingest_boundary_reference(
        request: WearableProviderLiveRuntimeIngestBoundaryReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-runtime-ingest-boundary-references",
            )
            return write_provider_live_runtime_ingest_boundary_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_runtime_ingest_boundary_reference.json",
                explicit_consent=request.explicit_consent,
                runtime_boundary_ref=request.runtime_boundary_ref,
                runtime_channel_ref=request.runtime_channel_ref,
                allowed_artifact_kinds=request.artifact_kinds,
                handoff_mode=request.handoff_mode,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-phase1-safety-boundary-reference")
    def wearable_provider_live_phase1_safety_boundary_reference(
        request: WearableProviderLivePhase1SafetyBoundaryReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-phase1-safety-boundary-references",
            )
            return write_provider_live_phase1_safety_boundary_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_phase1_safety_boundary_reference.json",
                explicit_consent=request.explicit_consent,
                phase1_boundary_ref=request.phase1_boundary_ref,
                phase1_state_ref=request.phase1_state_ref,
                advisory_channel_ref=request.advisory_channel_ref,
                allowed_artifact_kinds=request.artifact_kinds,
                handoff_mode=request.handoff_mode,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-request-plan")
    def wearable_provider_live_request_plan(request: WearableProviderLiveRequestPlanRequest) -> dict[str, Any]:
        try:
            preflight_path = _optional_path_from_admin_request(request.preflight_path)
            if preflight_path is None:
                preflight_candidates = sorted(
                    (resolved_wearable_inventory_root / "outputs").glob("*_preflight.json")
                )
                if not preflight_candidates:
                    raise FileNotFoundError("provider live preflight artifact not found")
                if len(preflight_candidates) > 1:
                    raise ValueError("preflight_path is required when multiple provider preflight artifacts exist")
                preflight_path = preflight_candidates[0]
            preflight_payload = json.loads(preflight_path.read_text(encoding="utf-8"))
            provider = preflight_payload.get("source_provider", "provider")
            output_path = (
                resolved_wearable_inventory_root
                / "outputs"
                / f"{provider}_request_plan.json"
            )
            return write_provider_live_transport_request_plan(
                preflight_path=preflight_path,
                output_path=output_path,
                window_start_date=request.window_start_date,
                window_end_date=request.window_end_date,
                requested_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-response-admit")
    def wearable_provider_live_response_admit(
        request: WearableProviderLiveResponseAdmissionRequest,
    ) -> dict[str, Any]:
        try:
            output_root = resolved_wearable_inventory_root / "outputs" / "provider-response-admissions"
            admission_output_path = output_root / f"{request.activity_id_prefix}.response_admission.json"
            return write_provider_live_transport_response_admission(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_dir=output_root / "sanitized-imports",
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                admission_output_path=admission_output_path,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-readiness")
    def wearable_provider_live_executor_readiness(
        request: WearableProviderLiveExecutorReadinessRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-readiness",
            )
            output_path = output_dir / "provider_live_executor_readiness.json"
            return write_provider_live_executor_readiness(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_optional_path_from_admin_request(request.executor_registration_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-register-executor")
    def wearable_provider_live_register_executor(
        request: WearableProviderLiveExecutorRegistrationRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-readiness",
            )
            output_path = output_dir / "provider_live_executor_registration.json"
            return write_provider_live_executor_registration(
                preflight_path=_path_from_admin_request(request.preflight_path),
                output_path=output_path,
                executor_kind=request.executor_kind,
                executor_ref=request.executor_ref,
                supported_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-rehearse-executor")
    def wearable_provider_live_rehearse_executor(
        request: WearableProviderLiveExecutorRehearsalRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            return write_provider_live_executor_rehearsal(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_path_from_admin_request(request.executor_registration_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-fixture-replay")
    def wearable_provider_live_fixture_replay(
        request: WearableProviderLiveFixtureReplayRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_executor_fixture_replay.json"
            return write_provider_live_executor_fixture_replay(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_path_from_admin_request(request.executor_registration_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-handoff")
    def wearable_provider_live_executor_handoff(
        request: WearableProviderLiveExecutorHandoffRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_executor_handoff.json"
            return write_provider_live_executor_handoff_package(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_path_from_admin_request(request.executor_registration_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-index-executor-handoff-outbox")
    def wearable_provider_live_index_executor_handoff_outbox(
        request: WearableProviderLiveExecutorHandoffOutboxIndexRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-handoff-outbox-index",
            )
            return write_provider_live_executor_handoff_outbox_index(
                outbox_dir=_path_from_admin_request(request.outbox_dir),
                output_path=output_dir / "provider_live_executor_handoff_outbox_index.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-handoff-pickup-manifest")
    def wearable_provider_live_executor_handoff_pickup_manifest(
        request: WearableProviderLiveExecutorHandoffPickupManifestRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-handoff-pickup-manifests",
            )
            return write_provider_live_executor_handoff_pickup_manifest(
                outbox_index_path=_path_from_admin_request(request.outbox_index_path),
                output_path=output_dir / "provider_live_executor_handoff_pickup_manifest.json",
                handoff_source_path=_optional_path_from_admin_request(
                    request.handoff_source_path
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-handoff-fixture-replay")
    def wearable_provider_live_handoff_fixture_replay(
        request: WearableProviderLiveHandoffFixtureReplayRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_handoff_fixture_replay.json"
            return write_provider_live_executor_handoff_fixture_replay(
                handoff_package_path=_path_from_admin_request(request.executor_handoff_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-pickup-response-manifest")
    def wearable_provider_live_executor_pickup_response_manifest(
        request: WearableProviderLiveExecutorPickupResponseManifestRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-response-manifests",
            )
            return write_provider_live_executor_pickup_response_manifest(
                pickup_manifest_path=_path_from_admin_request(request.pickup_manifest_path),
                response_payload_path=_path_from_admin_request(request.response_payload_path),
                output_path=output_dir / "provider_live_executor_pickup_response_manifest.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-manifest")
    def wearable_provider_live_executor_response_manifest(
        request: WearableProviderLiveExecutorResponseManifestRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_executor_response_manifest.json"
            return write_provider_live_executor_response_manifest(
                handoff_package_path=_path_from_admin_request(request.executor_handoff_path),
                response_payload_path=_path_from_admin_request(request.response_payload_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-index-executor-response-inbox")
    def wearable_provider_live_index_executor_response_inbox(
        request: WearableProviderLiveExecutorResponseInboxIndexRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox",
            )
            output_path = output_dir / "provider_live_executor_response_inbox_index.json"
            return write_provider_live_executor_response_inbox_index(
                inbox_dir=_path_from_admin_request(request.inbox_dir),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-admit")
    def wearable_provider_live_executor_response_admit(
        request: WearableProviderLiveExecutorResponseAdmissionRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            admission_output_path = output_dir / f"{request.activity_id_prefix}.executor_response_admission.json"
            return write_provider_live_transport_response_admission_from_executor_response_manifest(
                executor_response_manifest_path=_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                output_dir=output_dir / "executor-response-sanitized-imports",
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                admission_output_path=admission_output_path,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-response")
    def wearable_provider_live_consume_executor_response(
        request: WearableProviderLiveExecutorResponseConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-consumption",
            )
            return write_provider_live_executor_response_consumption(
                executor_response_manifest_path=_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-pickup-response")
    def wearable_provider_live_consume_executor_pickup_response(
        request: WearableProviderLiveExecutorResponseConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-response-consumption",
            )
            return write_provider_live_executor_pickup_response_consumption(
                executor_response_manifest_path=_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-pickup-response-consumption-receipt")
    def wearable_provider_live_executor_pickup_response_consumption_receipt(
        request: WearableProviderLiveExecutorPickupResponseConsumptionReceiptRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-response-consumption-receipts",
            )
            return write_provider_live_executor_pickup_response_consumption_receipt(
                pickup_response_consumption_path=_path_from_admin_request(
                    request.pickup_response_consumption_path
                ),
                output_path=output_dir
                / "provider_live_executor_pickup_response_consumption_receipt.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-pickup-status-snapshot")
    def wearable_provider_live_executor_pickup_status_snapshot(
        request: WearableProviderLiveExecutorPickupStatusSnapshotRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-status-snapshots",
            )
            return write_provider_live_executor_pickup_status_snapshot(
                pickup_manifest_path=_path_from_admin_request(request.pickup_manifest_path),
                executor_response_manifest_path=_optional_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                pickup_response_consumption_path=_optional_path_from_admin_request(
                    request.pickup_response_consumption_path
                ),
                pickup_response_receipt_path=_optional_path_from_admin_request(
                    request.pickup_response_receipt_path
                ),
                output_path=output_dir / "provider_live_executor_pickup_status_snapshot.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-lifecycle-audit")
    def wearable_provider_live_executor_lifecycle_audit(
        request: WearableProviderLiveExecutorLifecycleAuditRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-lifecycle-audits",
            )
            return write_provider_live_executor_lifecycle_audit(
                pickup_status_snapshot_path=_path_from_admin_request(
                    request.pickup_status_snapshot_path
                ),
                inbox_status_snapshot_path=_optional_path_from_admin_request(
                    request.inbox_status_snapshot_path
                ),
                output_path=output_dir / "provider_live_executor_lifecycle_audit.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-production-readiness-gate")
    def wearable_provider_live_executor_production_readiness_gate(
        request: WearableProviderLiveExecutorProductionReadinessGateRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-production-readiness-gates",
            )
            return write_provider_live_executor_production_readiness_gate(
                lifecycle_audit_path=_path_from_admin_request(
                    request.lifecycle_audit_path
                ),
                connector_reference_path=_optional_path_from_admin_request(
                    request.connector_reference_path
                ),
                credential_vault_reference_path=_optional_path_from_admin_request(
                    request.credential_vault_reference_path
                ),
                network_policy_reference_path=_optional_path_from_admin_request(
                    request.network_policy_reference_path
                ),
                runtime_ingest_boundary_reference_path=_optional_path_from_admin_request(
                    request.runtime_ingest_boundary_reference_path
                ),
                phase1_safety_boundary_reference_path=_optional_path_from_admin_request(
                    request.phase1_safety_boundary_reference_path
                ),
                output_path=output_dir / "provider_live_executor_production_readiness_gate.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-response-inbox")
    def wearable_provider_live_consume_executor_response_inbox(
        request: WearableProviderLiveExecutorResponseInboxConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-consumption",
            )
            return write_provider_live_executor_response_inbox_consumption(
                inbox_index_path=_path_from_admin_request(request.inbox_index_path),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                manifest_source_path=_optional_path_from_admin_request(request.manifest_source_path),
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-response-inbox-batch")
    def wearable_provider_live_consume_executor_response_inbox_batch(
        request: WearableProviderLiveExecutorResponseInboxBatchConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-batch-consumption",
            )
            return write_provider_live_executor_response_inbox_batch_consumption(
                inbox_index_path=_path_from_admin_request(request.inbox_index_path),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-inbox-batch-receipt")
    def wearable_provider_live_executor_response_inbox_batch_receipt(
        request: WearableProviderLiveExecutorResponseInboxBatchReceiptRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-batch-receipts",
            )
            return write_provider_live_executor_response_inbox_batch_receipt(
                batch_consumption_path=_path_from_admin_request(request.batch_consumption_path),
                output_path=output_dir / "provider_live_executor_response_inbox_batch_receipt.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-inbox-status-snapshot")
    def wearable_provider_live_executor_response_inbox_status_snapshot(
        request: WearableProviderLiveExecutorResponseInboxStatusSnapshotRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-status-snapshots",
            )
            return write_provider_live_executor_response_inbox_status_snapshot(
                inbox_index_path=_path_from_admin_request(request.inbox_index_path),
                batch_consumption_path=_optional_path_from_admin_request(
                    request.batch_consumption_path
                ),
                batch_receipt_path=_optional_path_from_admin_request(request.batch_receipt_path),
                output_path=output_dir / "provider_live_executor_response_inbox_status_snapshot.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-replay-admit")
    def wearable_provider_live_replay_admit(
        request: WearableProviderLiveReplayAdmissionRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            admission_output_path = output_dir / f"{request.activity_id_prefix}.replay_admission.json"
            return write_provider_live_transport_response_admission_from_fixture_replay(
                fixture_replay_path=_path_from_admin_request(request.fixture_replay_path),
                output_dir=output_dir / "replay-sanitized-imports",
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                admission_output_path=admission_output_path,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-materialize")
    def wearable_provider_live_materialize(
        request: WearableProviderLiveMaterializationRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-response-materialized",
            )
            materialization_output_path = output_dir / "provider_live_materialization.json"
            return write_provider_live_transport_materialization(
                admission_path=_path_from_admin_request(request.admission_path),
                output_dir=output_dir / "normalized",
                materialization_output_path=materialization_output_path,
                root=resolved_wearable_inventory_root,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-sync-package")
    def wearable_provider_live_sync_package(
        request: WearableProviderLiveSyncPackageRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-response-materialized",
            )
            package_output_path = output_dir / "provider_live_sync_package.json"
            return write_provider_live_transport_sync_package(
                materialization_path=_path_from_admin_request(request.materialization_path),
                package_output_path=package_output_path,
                root=resolved_wearable_inventory_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-build-energy")
    def wearable_provider_live_build_energy(
        request: WearableProviderLiveEnergyBuildRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-sync-energy",
            )
            return write_energy_reserve_artifacts_from_provider_sync_package(
                _path_from_admin_request(request.sync_package_path),
                output_dir=output_dir,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
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
    def pretrip_project(project_id: str, compact: bool = False) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            view = build_pretrip_admin_view(project_id, project_root=project_root)
            _attach_energy_reserve_monitor(
                view,
                inventory_root=resolved_wearable_inventory_root,
                surface="pretrip",
            )
            return _compact_pretrip_project_view(view) if compact else view
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

    @router.get(
        "/pretrip/projects/{project_id}/briefings/route-context",
        response_class=HTMLResponse,
    )
    def pretrip_project_route_context_briefing(project_id: str) -> Response:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
        briefing_ref = (
            project.get("route_context_briefing_ref")
            or DEFAULT_ROUTE_CONTEXT_BRIEFING_REF
        )
        briefing_path = _safe_pretrip_project_ref_path(project_root, briefing_ref)
        if briefing_path is None:
            raise HTTPException(status_code=422, detail="unsafe route context briefing path")
        if not briefing_path.exists():
            raise HTTPException(status_code=404, detail="route context briefing not prepared")
        return Response(
            briefing_path.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "X-Scout-Candidate-Only": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
                "X-Scout-Route-Context-Briefing": "true",
                "X-Scout-Source-Ref": str(briefing_ref),
            },
        )

    @router.get("/pretrip/projects/{project_id}/terrain-overlays/{mode}.png")
    def pretrip_project_terrain_overlay(project_id: str, mode: str) -> Response:
        if mode not in {"hillshade", "elevation_tint", "slope_shading", "contours"}:
            raise HTTPException(status_code=422, detail="unsupported terrain overlay mode")
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
        terrain_ref = project.get("terrain_visualization_ref")
        if not isinstance(terrain_ref, str) or not terrain_ref:
            raise HTTPException(status_code=404, detail="terrain visualization not prepared")
        terrain_path = project_root / terrain_ref
        if not terrain_path.exists():
            raise HTTPException(status_code=404, detail="terrain visualization artifact missing")
        terrain_payload = json.loads(terrain_path.read_text(encoding="utf-8"))
        overlays = terrain_payload.get("raster_overlays", [])
        overlay = next(
            (
                item
                for item in overlays
                if isinstance(item, dict) and item.get("mode") == mode
            ),
            None,
        )
        if not isinstance(overlay, dict):
            raise HTTPException(status_code=404, detail="terrain overlay not available")
        overlay_source_path = overlay.get("source_path")
        if not isinstance(overlay_source_path, str) or not overlay_source_path:
            raise HTTPException(status_code=404, detail="terrain overlay source missing")
        overlay_path = (project_root / overlay_source_path).resolve()
        try:
            overlay_path.relative_to(project_root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="unsafe terrain overlay path") from exc
        if not overlay_path.exists():
            raise HTTPException(status_code=404, detail="terrain overlay file missing")
        return Response(
            overlay_path.read_bytes(),
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache, max-age=0, must-revalidate",
                "X-Scout-Terrain-Overlay": mode,
                "X-Scout-Terrain-Overlay-Hash": str(overlay.get("sha256") or ""),
                "X-Scout-Runtime-Safety-Truth": "false",
            },
        )

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
            gee_runtime_status=build_gee_runtime_status(),
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
                    max_reasonable_gpx_speed_kmh=request.max_reasonable_gpx_speed_kmh,
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
    def osm_tile(
        z: int,
        x: int,
        y: int,
        fallback: str | None = None,
        v: str | None = None,
    ) -> Response:
        try:
            fallback_style = "offline" if fallback == "offline" else "transparent"
            payload = load_or_build_osm_tile_payload(
                z,
                x,
                y,
                cache_root=_osm_tile_cache_root_from_env(),
                fallback_enabled=_osm_tile_fallback_enabled_from_env(),
                fallback_style=fallback_style,
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
    def imagery_tile(
        project_id: str,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        source_id: str | None = None,
    ) -> Response:
        try:
            project = _pretrip_project_payload_for_tiles(
                pretrip_workspace_root,
                project_id=project_id,
            )
            imagery_source = imagery_source_for_project(
                project,
                layer_id=layer_id,
                registry_path=_imagery_source_registry_path_from_env(),
                source_id=source_id,
            )
            payload = load_or_build_raster_tile_payload(
                project_id,
                layer_id,
                z,
                x,
                y,
                cache_root=_raster_tile_cache_root_for_project(
                    pretrip_workspace_root,
                    project_id=project_id,
                ),
                fallback_enabled=_raster_tile_fallback_enabled_from_env(),
                imagery_source=imagery_source,
                allow_remote_fetch=_imagery_remote_fetch_enabled_from_env(),
                remote_fetch_timeout_seconds=_imagery_remote_fetch_timeout_from_env(),
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
            view = build_admin_case_view(
                case_id,
                incident_store_path=resolved_incident_store_path,
                pretrip_project_root=pretrip_project_root,
            )
            if case_id == PRETRIP_CASE_ID:
                _attach_completed_trip_scenario_projection(view, data_root=_data_root_from_env())
                _attach_completed_trip_recording_projection(view, data_root=_data_root_from_env())
            _attach_energy_reserve_monitor(
                view,
                inventory_root=resolved_wearable_inventory_root,
                surface="admin",
            )
            return view
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
            "max_reasonable_gpx_speed_kmh": request.max_reasonable_gpx_speed_kmh,
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
            "max_reasonable_gpx_speed_kmh": request.max_reasonable_gpx_speed_kmh,
        },
        "gpx_speed_filter": {
            "enabled": True,
            "max_reasonable_speed_kmh": request.max_reasonable_gpx_speed_kmh,
            "applied_in_preview": False,
            "applied_during_import": True,
            "rule": (
                "Import writes filtered GPX copies and removes track points that "
                "would require speed greater than max_reasonable_speed_kmh from "
                "the previous kept point, or greater than 3x the previous kept "
                "segment speed. Nearby GPX route notes protect points from "
                "automatic pruning; long GPS gaps are preserved as resume "
                "segment diagnostics."
            ),
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


def _compact_pretrip_project_view(view: dict[str, Any]) -> dict[str, Any]:
    """Keep browser payloads traceable without duplicating heavy tab lists."""
    compact = dict(view)
    tabs = view.get("tabs", {})
    pre_trip = tabs.get("pre_trip_planning", {}) if isinstance(tabs, dict) else {}
    post = tabs.get("post_analysis", {}) if isinstance(tabs, dict) else {}
    review = tabs.get("review_workspace", {}) if isinstance(tabs, dict) else {}
    agent = tabs.get("agent_skills", {}) if isinstance(tabs, dict) else {}
    terrain_visualization = view.get("terrain_visualization", {})
    compact["tabs"] = {
        "pre_trip_planning": {
            "sections": _compact_sections(pre_trip.get("sections")),
            "energy_reserve_monitor": view.get("energy_reserve_monitor"),
            "terrain_visualization": {
                "source_path": terrain_visualization.get("source_path", "")
                if isinstance(terrain_visualization, dict)
                else "",
                "counts": terrain_visualization.get("counts", {})
                if isinstance(terrain_visualization, dict)
                else {},
            },
        },
        "review_workspace": {
            "sections": _compact_sections(review.get("sections")),
        },
        "post_analysis": {
            "sections": _compact_sections(post.get("sections")),
            "segment_terrain": _compact_summary_payload(post.get("segment_terrain")),
            "runtime_handoff": _compact_summary_payload(post.get("runtime_handoff")),
            "route_comparison": _compact_summary_payload(post.get("route_comparison")),
            "capability_timeline_import": _compact_capability_timeline_import(
                post.get("capability_timeline_import")
            ),
            "brain_seed": _compact_summary_payload(post.get("brain_seed")),
        },
        "agent_skills": {
            "sections": _compact_sections(agent.get("sections")),
            "scout_agent_skills": _compact_summary_payload(
                agent.get("scout_agent_skills")
            ),
            "evidence_timeline": _compact_summary_payload(agent.get("evidence_timeline")),
        },
    }
    _compact_pretrip_heavy_layers(compact)
    compact["compact_payload"] = {
        "enabled": True,
        "removed_duplicate_tab_payload": True,
        "trimmed_heavy_layer_items": True,
        "full_project_api": f"/admin/pretrip/projects/{view.get('project_id', '')}",
        "runtime_safety_truth": False,
    }
    return compact


def _attach_energy_reserve_monitor(
    payload: dict[str, Any],
    *,
    inventory_root: Path,
    surface: str,
) -> None:
    payload["energy_reserve_monitor"] = build_energy_reserve_monitor_from_view(
        payload,
        inventory_root=inventory_root,
        surface=surface,
    )
    tabs = payload.get("tabs")
    if isinstance(tabs, dict):
        pretrip_tab = tabs.get("pre_trip_planning")
        if isinstance(pretrip_tab, dict):
            pretrip_tab["energy_reserve_monitor"] = payload["energy_reserve_monitor"]


def _attach_completed_trip_scenario_projection(
    view: dict[str, Any],
    *,
    data_root: Path,
) -> None:
    try:
        catalog = list_completed_trip_scenarios(data_root=data_root, root=ROOT)
    except FileNotFoundError:
        return
    view["completed_trip_scenarios"] = catalog
    active = load_active_completed_trip_scenario_projection(data_root=data_root, root=ROOT)
    if not active:
        return
    view["active_completed_trip_scenario"] = active.get("scenario")
    if active.get("scout_reaction_simulation"):
        view["scout_reaction_simulation"] = active.get("scout_reaction_simulation")
    capability = active.get("capability_timeline")
    if capability:
        capability["completed_trip_scenario"] = active.get("scenario")
        view["capability_timeline"] = capability


def _attach_completed_trip_recording_projection(
    view: dict[str, Any],
    *,
    data_root: Path,
) -> None:
    catalog = list_completed_trip_recordings(data_root=data_root, root=ROOT)
    view["completed_trip_recordings"] = catalog
    active = load_active_completed_trip_recording_projection(data_root=data_root, root=ROOT)
    if not active:
        return
    view["active_completed_trip_recording"] = active.get("recording")
    if active.get("completed_trip_track"):
        view["completed_trip_track"] = active.get("completed_trip_track")
    if active.get("scout_reaction_simulation"):
        view["scout_reaction_simulation"] = active.get("scout_reaction_simulation")
    capability = active.get("capability_timeline")
    if capability:
        capability["completed_trip_recording"] = active.get("recording")
        view["capability_timeline"] = capability


_COMPACT_COMMON_EVIDENCE_KEYS = (
    "candidate_id",
    "source_id",
    "item_id",
    "source_path",
    "metadata_source_path",
    "evidence_type",
    "status",
    "label",
    "title",
    "summary",
    "lat",
    "lon",
    "ele_m",
    "time",
    "distance_m",
    "start_distance_m",
    "end_distance_m",
    "review_state",
    "confidence",
    "stale_risk",
    "candidate_only",
    "runtime_safety_truth",
    "source_profile",
    "category",
    "severity",
    "candidate_ref",
    "map_target_ids",
    "review_focus",
    "target_ids",
    "human_review_required",
    "decision_recorded",
    "accept_reject_allowed",
    "mutation_allowed",
)
_COMPACT_SOURCE_ATTRIBUTION_KEYS = (
    "source_kind",
    "source_profile",
    "source_ref",
    "source_candidate_id",
    "source_artifact_id",
    "source_label",
    "source_role",
    "evidence_type",
    "confidence",
    "stale_risk",
    "candidate_only",
    "runtime_safety_truth",
    "osm_type",
    "osm_id",
)
_COMPACT_BOUNDARY_KEYS = (
    "candidate_only",
    "pretrip_candidate_evidence_only",
    "projection_only",
    "phase1_runtime_mutation_allowed",
    "phase2_brain_writeback_allowed",
    "runtime_safety_truth",
    "safety_api_calls_allowed",
    "final_runtime_write_allowed",
    "not_departure_approval",
    "human_review_required_before_departure",
)
_COMPACT_ROUTE_NOTE_LIMIT = 120
_COMPACT_COLLECTION_ITEM_LIMIT = 48
_COMPACT_ROUTE_DISPLAY_POINTS_PER_SEGMENT = 24
_COMPACT_SEGMENT_DISPLAY_POINTS_PER_SEGMENT = 4


def _compact_mapping(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _compact_source_attribution(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        return []
    first = payload[0]
    if not isinstance(first, dict):
        return []
    return [_compact_mapping(first, _COMPACT_SOURCE_ATTRIBUTION_KEYS)]


def _compact_boundary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return _compact_mapping(payload, _COMPACT_BOUNDARY_KEYS)


def _compact_evidence_item(
    item: dict[str, Any],
    *,
    extra_keys: tuple[str, ...] = (),
    source_ref_limit: int = 0,
    include_source_attribution: bool = False,
) -> dict[str, Any]:
    compact = _compact_mapping(item, (*_COMPACT_COMMON_EVIDENCE_KEYS, *extra_keys))
    source_refs = item.get("source_refs")
    if source_ref_limit > 0 and isinstance(source_refs, list):
        compact["source_refs"] = source_refs[:source_ref_limit]
    if include_source_attribution:
        source_attribution = _compact_source_attribution(item.get("source_attribution"))
        if source_attribution:
            compact["source_attribution"] = source_attribution
    boundary = _compact_boundary(item.get("boundary"))
    if boundary:
        compact["boundary"] = boundary
    evidence_summary = item.get("evidence_summary")
    if isinstance(evidence_summary, dict):
        compact["evidence_summary"] = _compact_evidence_item(
            evidence_summary,
            extra_keys=("interpretation_mode", "not_observed_fact"),
        )
    return compact


def _compact_collection_items(
    payload: Any,
    item_key: str,
    *,
    extra_keys: tuple[str, ...] = (),
    limit: int = _COMPACT_COLLECTION_ITEM_LIMIT,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    items = payload.get(item_key)
    if isinstance(items, list):
        source_count = len(items)
        kept_items = items[:limit] if limit > 0 else []
        compact[item_key] = [
            _compact_evidence_item(item, extra_keys=extra_keys)
            if isinstance(item, dict)
            else item
            for item in kept_items
        ]
        compact[f"source_{item_key}_count"] = source_count
        compact["admin_payload_item_limit"] = limit
        compact["admin_payload_truncated"] = source_count > len(kept_items)
    return compact


def _compact_summary_collection_items(
    payload: Any,
    item_key: str,
    *,
    extra_keys: tuple[str, ...] = (),
    limit: int = _COMPACT_COLLECTION_ITEM_LIMIT,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    items = payload.get(item_key)
    if isinstance(items, list):
        source_count = len(items)
        kept_items = items[:limit] if limit > 0 else []
        compact[item_key] = [
            _compact_evidence_item(item, extra_keys=extra_keys)
            if isinstance(item, dict)
            else item
            for item in kept_items
        ]
        compact[f"source_{item_key}_count"] = source_count
        compact["admin_payload_item_limit"] = limit
        compact["admin_payload_truncated"] = source_count > len(kept_items)
    for key in ("bbox_wgs84", "cache_policy", "geojson_source_path"):
        if key in payload:
            compact[key] = payload[key]
    return compact


def _compact_collection_list(
    payload: Any,
    *,
    extra_keys: tuple[str, ...] = (),
    limit: int = _COMPACT_COLLECTION_ITEM_LIMIT,
) -> Any:
    if not isinstance(payload, list):
        return payload
    kept_items = payload[:limit] if limit > 0 else []
    return [
        _compact_evidence_item(item, extra_keys=extra_keys)
        if isinstance(item, dict)
        else item
        for item in kept_items
    ]


def _compact_sections(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [
        _compact_summary_payload(section)
        if isinstance(section, dict)
        else {"summary": str(section)}
        for section in payload
    ]


def _compact_summary_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    keep_keys = (
        "id",
        "title",
        "label",
        "label_zh",
        "source_id",
        "source_path",
        "evidence_type",
        "artifact_kind",
        "status",
        "counts",
        "summary",
        "boundary",
        "source_refs",
        "confidence",
        "stale_risk",
        "review_state",
        "candidate_only",
        "runtime_safety_truth",
    )
    compact = _compact_mapping(payload, keep_keys)
    if isinstance(compact.get("summary"), dict):
        compact["summary"] = _compact_mapping(
            compact["summary"],
            (
                "status",
                "counts",
                "decision",
                "challenge_fit_decision",
                "top_candidate_profile_ref",
                "top_match_score",
            ),
        )
    if isinstance(compact.get("boundary"), dict):
        compact["boundary"] = _compact_boundary(compact["boundary"])
    source_refs = compact.get("source_refs")
    if isinstance(source_refs, list):
        compact["source_refs"] = source_refs[:12]
    return compact


def _compact_overpass_evidence(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    for key, extra_keys in {
        "corridor_candidates": (
            "candidate_type",
            "feature_type",
            "osm_type",
            "osm_id",
            "lat",
            "lon",
            "distance_to_route_m",
            "corridor",
        ),
        "hazard_candidates": (
            "candidate_type",
            "feature_type",
            "osm_type",
            "osm_id",
            "lat",
            "lon",
            "distance_to_route_m",
            "hazard",
        ),
        "poi_candidates": (
            "candidate_type",
            "feature_type",
            "osm_type",
            "osm_id",
            "lat",
            "lon",
            "distance_to_route_m",
            "poi",
        ),
    }.items():
        items = payload.get(key)
        if isinstance(items, list):
            compact[key] = [
                _compact_overpass_candidate(item, extra_keys=extra_keys)
                if isinstance(item, dict)
                else item
                for item in items[:_COMPACT_COLLECTION_ITEM_LIMIT]
            ]
            compact[f"source_{key}_count"] = len(items)
            compact["admin_payload_item_limit"] = _COMPACT_COLLECTION_ITEM_LIMIT
            compact["admin_payload_truncated"] = len(items) > _COMPACT_COLLECTION_ITEM_LIMIT
    return compact


def _compact_overpass_candidate(
    item: dict[str, Any],
    *,
    extra_keys: tuple[str, ...],
) -> dict[str, Any]:
    compact = _compact_evidence_item(
        item,
        extra_keys=extra_keys,
        source_ref_limit=2,
    )
    corridor = compact.get("corridor")
    if isinstance(corridor, dict):
        compact["corridor"] = _compact_overpass_corridor(corridor)
    hazard = compact.get("hazard")
    if isinstance(hazard, dict):
        compact["hazard"] = _compact_overpass_hazard(hazard)
    poi = compact.get("poi")
    if isinstance(poi, dict):
        compact["poi"] = _compact_overpass_poi(poi)
    return compact


def _compact_overpass_corridor(corridor: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_mapping(
        corridor,
        ("corridor_id", "name", "corridor_half_width_m", "route_level"),
    )
    coordinates = corridor.get("coordinates")
    if isinstance(coordinates, list):
        compact["coordinates"] = _sample_points(
            [point for point in coordinates if isinstance(point, dict)],
            32,
        )
        compact["source_coordinate_count"] = len(coordinates)
        compact["admin_payload_point_cap"] = 32
    return compact


def _compact_overpass_hazard(hazard: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_mapping(hazard, ("hazard_id", "hazard_type", "name"))
    polygon = hazard.get("polygon")
    if isinstance(polygon, list):
        compact["polygon"] = _sample_points(
            [point for point in polygon if isinstance(point, dict)],
            32,
        )
        compact["source_polygon_point_count"] = len(polygon)
        compact["admin_payload_point_cap"] = 32
    return compact


def _compact_overpass_poi(poi: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_mapping(poi, ("poi_id", "poi_type", "name"))
    coordinate = poi.get("coordinate")
    if isinstance(coordinate, dict):
        compact["coordinate"] = _compact_display_point(coordinate)
    return compact


def _compact_reference_tracks(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    tracks = payload.get("reference_tracks")
    if isinstance(tracks, list):
        compact["reference_tracks"] = [
            _compact_reference_track(track) if isinstance(track, dict) else track
            for track in tracks
        ]
    return compact


def _compact_reference_track(track: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_evidence_item(track)
    route = track.get("route")
    if isinstance(route, dict):
        compact["route"] = _compact_mapping(
            route,
            ("distance_m", "point_count", "bounds", "display_bounds"),
        )
    display_geometry = track.get("display_geometry")
    if isinstance(display_geometry, dict):
        compact["display_geometry"] = _compact_display_geometry(
            display_geometry,
            max_points_per_segment=24,
        )
    return compact


def _compact_route(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_mapping(
        payload,
        (
            "source_id",
            "source_path",
            "evidence_type",
            "route_name",
            "distance_m",
            "point_count",
            "bounds",
            "display_bounds",
            "display_bounds_metadata",
            "elevation_min_m",
            "elevation_max_m",
            "review_state",
            "confidence",
            "stale_risk",
            "candidate_only",
            "runtime_safety_truth",
        ),
    )
    display_geometry = payload.get("display_geometry")
    if isinstance(display_geometry, dict):
        compact["display_geometry"] = _compact_display_geometry(
            display_geometry,
            max_points_per_segment=_COMPACT_ROUTE_DISPLAY_POINTS_PER_SEGMENT,
        )
    elif isinstance(payload.get("polyline"), list):
        compact["polyline"] = [_compact_display_point(point) for point in payload["polyline"]]
    return compact


def _compact_display_geometry(
    display_geometry: dict[str, Any],
    *,
    max_points_per_segment: int,
) -> dict[str, Any]:
    coordinate_segments = _display_coordinate_segments(display_geometry)
    bounded_segments = [
        _sample_points(segment, max_points_per_segment)
        for segment in coordinate_segments
        if segment
    ]
    coordinates = [point for segment in bounded_segments for point in segment]
    source_point_count = display_geometry.get(
        "display_point_count",
        sum(len(segment) for segment in coordinate_segments),
    )
    compact = _compact_mapping(
        display_geometry,
        (
            "source_id",
            "source_path",
            "evidence_type",
            "display_segment_count",
            "segment_boundary_preserved",
            "boundary",
        ),
    )
    compact.update(
        {
            "source_display_point_count": source_point_count,
            "display_point_count": len(coordinates),
            "display_segment_count": len(bounded_segments),
            "coordinate_segments": bounded_segments,
            "geometry_simplified_for_admin_payload": len(coordinates)
            < source_point_count,
            "admin_payload_point_cap": max_points_per_segment,
        }
    )
    return compact


def _display_coordinate_segments(display_geometry: dict[str, Any]) -> list[list[dict[str, Any]]]:
    coordinate_segments = display_geometry.get("coordinate_segments")
    if isinstance(coordinate_segments, list):
        segments = [
            [dict(point) for point in segment if isinstance(point, dict)]
            for segment in coordinate_segments
            if isinstance(segment, list)
        ]
        segments = [segment for segment in segments if segment]
        if segments:
            return segments
    coordinates = display_geometry.get("coordinates")
    if isinstance(coordinates, list):
        segment = [dict(point) for point in coordinates if isinstance(point, dict)]
        return [segment] if segment else []
    return []


def _sample_points(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points <= 0 or len(points) <= max_points:
        return [_compact_display_point(point) for point in points]
    if max_points == 1:
        return [_compact_display_point(points[0])]
    last_index = len(points) - 1
    indexes = {round(index * last_index / (max_points - 1)) for index in range(max_points)}
    return [_compact_display_point(points[index]) for index in sorted(indexes)]


def _compact_display_point(point: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(
        point,
        (
            "lat",
            "lon",
            "ele_m",
            "elevation_m",
            "distance_m",
            "route_distance_m",
        ),
    )


def _compact_gis_perception_timeline(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    checkpoint_candidates = payload.get("checkpoint_candidates")
    if isinstance(checkpoint_candidates, list):
        compact["checkpoint_candidates"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "checkpoint_type",
                    "source_route_note_candidate_id",
                    "source_gpx_role",
                    "source_note_category",
                    "route_note_age_days",
                    "route_note_freshness",
                    "stale_route_note",
                    "linked_ln_proposal_id",
                    "proposed_ln_scope",
                    "route_note_summary",
                    "timeline_element_type",
                    "review_category",
                    "semantic_aggregation_key",
                    "nearby_group_id",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in checkpoint_candidates
        ]
    nearby_groups = payload.get("nearby_groups")
    if isinstance(nearby_groups, list):
        compact["nearby_groups"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "nearby_group_id",
                    "member_count",
                    "semantic_keys",
                    "timeline_element_type",
                    "review_category",
                    "semantic_aggregation_key",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in nearby_groups
        ]
    return compact


def _compact_major_critical_points(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        compact["candidates"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "mcp_id",
                    "mcp_classes",
                    "mention_ratio",
                    "accepted_evidence_page_count",
                    "linked_cp_candidates",
                    "linked_named_points",
                    "linked_risk_segments",
                    "nearest_scout_cp",
                    "source_family_coverage",
                    "nearby_points_suppressed_by_spacing",
                    "cp_support_reconciliation",
                    "suggested_cp_insertion",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in candidates
        ]
    return compact


def _compact_route_notes(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        keep_keys = (
            "candidate_id",
            "evidence_type",
            "lat",
            "lon",
            "normalized_note",
            "note_category",
            "review_state",
            "route_note_freshness",
            "stale_route_note",
            "candidate_only",
            "runtime_safety_truth",
        )
        source_count = len(candidates)
        kept_candidates = candidates[:_COMPACT_ROUTE_NOTE_LIMIT]
        compact["candidates"] = [
            _compact_mapping(item, keep_keys) if isinstance(item, dict) else item
            for item in kept_candidates
        ]
        compact["source_candidate_count"] = source_count
        compact["admin_payload_candidate_limit"] = _COMPACT_ROUTE_NOTE_LIMIT
        compact["admin_payload_truncated"] = source_count > len(kept_candidates)
    return compact


def _compact_mileage_tag_alignment(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "geojson_source_path",
        "source_kind_counts",
        "display_mileage_status_counts",
        "route_projection_status_counts",
        "raw_source_summary",
        "route_mileage_alignment_summary",
        "sample_labels",
        "policy",
    ):
        if key in payload:
            compact[key] = payload[key]
    timeline_items = payload.get("timeline_items")
    if isinstance(timeline_items, list):
        kept_items = timeline_items[:_COMPACT_COLLECTION_ITEM_LIMIT]
        compact["timeline_items"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "display_mileage_label",
                    "display_mileage_status",
                    "source_kind",
                    "route_projection_status",
                    "route_distance_m",
                    "mileage_m",
                    "map_target_ids",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in kept_items
        ]
        compact["source_timeline_items_count"] = len(timeline_items)
        compact["admin_payload_item_limit"] = _COMPACT_COLLECTION_ITEM_LIMIT
        compact["admin_payload_truncated"] = len(timeline_items) > len(kept_items)
    return compact


def _compact_environment_risk_derivative_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return _compact_evidence_item(
        item,
        extra_keys=(
            "candidate_kind",
            "layer_id",
            "geometry_type",
            "coordinates",
            "score",
            "mid_distance_m",
            "start_distance_m",
            "end_distance_m",
            "supporting_metrics",
            "cwa_time_metadata",
            "source_time_metadata",
            "cwa_api_request_attempted_at",
            "cwa_api_request_attempted_at_hour",
            "cwa_api_fetched_at",
            "cwa_api_fetched_at_hour",
            "cwa_forecast_valid_from_hour",
            "cwa_forecast_valid_until_hour",
            "cwa_warning_valid_until_hour",
            "cwa_latest_observation_at_hour",
            "cwa_valid_from_hour",
            "cwa_valid_until_hour",
            "time_precision",
            "timezone",
        ),
    )


def _compact_environment_risk_derivative_collection(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "layer_id",
        "label",
        "counts",
        "bbox_wgs84",
        "cwa_time_metadata",
        "source_time_metadata",
        "cwa_api_fetched_at_hour",
        "cwa_valid_until_hour",
        "time_precision",
        "timezone",
    ):
        if key in payload:
            compact[key] = payload[key]
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        kept_candidates = candidates[:_COMPACT_COLLECTION_ITEM_LIMIT]
        compact["candidates"] = [
            _compact_environment_risk_derivative_candidate(item)
            if isinstance(item, dict)
            else item
            for item in kept_candidates
        ]
        compact["source_candidates_count"] = len(candidates)
        compact["admin_payload_item_limit"] = _COMPACT_COLLECTION_ITEM_LIMIT
        compact["admin_payload_truncated"] = len(candidates) > len(kept_candidates)
    return compact


def _compact_environment_risk_derivative_layers(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in ("layer_id", "counts", "category_items"):
        if key in payload and key != "category_items":
            compact[key] = payload[key]
    category_items = payload.get("category_items")
    if isinstance(category_items, list):
        compact["category_items"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "candidate_count",
                    "value_summary",
                    "layer_id",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in category_items
        ]
    for key in (
        "new_landslide_candidates",
        "wetness_flash_flood_susceptibility",
        "trail_obscurity_risk",
        "practical_darkness_time",
    ):
        compact[key] = _compact_environment_risk_derivative_collection(
            payload.get(key)
        )
    if isinstance(payload.get("route_revalidation_report"), dict):
        compact["route_revalidation_report"] = _compact_summary_payload(
            payload["route_revalidation_report"]
        )
    return compact


def _compact_review_workbench(payload: Any) -> Any:
    compact = _compact_summary_collection_items(
        payload,
        "category_groups",
        extra_keys=(
            "item_count",
            "bulk_eligible_count",
            "review_action",
            "category",
        ),
    )
    return compact


def _compact_route_note_review_options(payload: Any) -> Any:
    return _compact_summary_collection_items(
        payload,
        "options",
        extra_keys=(
            "candidate_ref",
            "candidate_id",
            "disposition",
            "recommended_disposition",
            "route_note_freshness",
            "stale_route_note",
            "confidence",
        ),
    )


def _compact_capability_timeline_import(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "edge_count",
        "observed_edge_count",
        "planned_segment_count",
        "traversed_segment_count",
        "partial_segment_count",
        "unreached_segment_count",
        "completion_status",
        "planning_use",
        "privacy",
    ):
        if key in payload:
            compact[key] = payload[key]
    summary = payload.get("summary")
    if isinstance(summary, dict):
        compact["summary"] = _compact_mapping(
            summary,
            (
                "edge_count",
                "moving_time_s",
                "rest_time_s",
                "elapsed_time_s",
                "distance_m",
                "ascent_m",
                "descent_m",
                "raw_track_shared",
                "auto_applies_to_eta",
            ),
        )
    edges = payload.get("edges")
    if isinstance(edges, list):
        compact["edges"] = [
            _compact_evidence_item(
                edge,
                extra_keys=(
                    "edge_id",
                    "segment_id",
                    "from_node_id",
                    "to_node_id",
                    "direction",
                    "traversal_status",
                    "elapsed_time_s",
                    "moving_time_s",
                    "rest_time_s",
                    "distance_m",
                    "ascent_m",
                    "descent_m",
                    "guide_time_min",
                ),
            )
            if isinstance(edge, dict)
            else edge
            for edge in edges
        ]
    return compact


def _compact_pretrip_heavy_layers(view: dict[str, Any]) -> None:
    view["route"] = _compact_route(view.get("route"))
    view["segments"] = _compact_segments(view.get("segments"))
    view["checkpoints"] = _compact_collection_list(
        view.get("checkpoints"),
        extra_keys=("lat", "lon", "label", "route_distance_m", "overpass_projection"),
    )
    view["environment_risk_derivative_layers"] = (
        _compact_environment_risk_derivative_layers(
        view.get("environment_risk_derivative_layers")
        )
    )
    for key in (
        "admin_surface_projection",
        "checkpoint_events",
        "route_note_ln_proposals",
        "segment_terrain",
    ):
        view[key] = _compact_summary_payload(view.get(key))
    view["capability_timeline_import"] = _compact_capability_timeline_import(
        view.get("capability_timeline_import")
    )
    view["review_queue"] = _compact_summary_collection_items(
        view.get("review_queue"),
        "items",
        extra_keys=(
            "severity",
            "category",
            "source_ref",
            "source_ref_key",
            "source_artifact_kind",
            "review_category",
            "bulk_candidate_refs",
        ),
    )
    view["review_workbench"] = _compact_review_workbench(view.get("review_workbench"))
    view["route_note_review_options"] = _compact_route_note_review_options(
        view.get("route_note_review_options")
    )
    view["mileage_tag_alignment"] = _compact_mileage_tag_alignment(
        view.get("mileage_tag_alignment")
    )
    view["route_notes"] = _compact_route_notes(view.get("route_notes"))
    view["risk_score"] = _compact_summary_collection_items(
        view.get("risk_score"),
        "points",
        extra_keys=(
            "pretrip_risk",
            "risk_level",
            "score_field",
            "route_id",
            "sample_id",
            "elevation_m",
            "teii_20m",
            "tri",
            "sri",
            "lec",
            "scp",
        ),
    )
    risk_segment_keys = (
        "segment_id",
        "coordinates",
        "pretrip_risk",
        "calibrated_risk_candidate",
        "baseline_pretrip_risk",
        "delta_score",
        "score_field",
        "risk_level",
        "risk_bucket",
        "delta_bucket",
        "style_class",
        "stroke",
        "route_id",
        "from_sample_id",
        "to_sample_id",
    )
    view["risk_ribbon"] = _compact_summary_collection_items(
        view.get("risk_ribbon"),
        "segments",
        extra_keys=risk_segment_keys,
    )
    view["risk_heatmap"] = _compact_summary_collection_items(
        view.get("risk_heatmap"),
        "segments",
        extra_keys=risk_segment_keys,
    )
    view["risk_delta"] = _compact_summary_collection_items(
        view.get("risk_delta"),
        "segments",
        extra_keys=risk_segment_keys,
    )
    view["terrain_visualization"] = _compact_collection_items(
        view.get("terrain_visualization"),
        "samples",
        extra_keys=(
            "elevation_m",
            "visualization_modes",
            "hillshade_value",
            "elevation_tint_color",
            "slope_degrees",
            "slope_class",
            "slope_class_label",
            "slope_color",
            "contour_interval_m",
            "contour_index_m",
            "contour_marker",
            "terrain_visualization_layer",
            "risk_heat_layer",
        ),
    )
    if isinstance(view.get("terrain_visualization"), dict):
        view["terrain_visualization"]["contours"] = []
    view["gis_perception_timeline"] = _compact_gis_perception_timeline(
        view.get("gis_perception_timeline")
    )
    if isinstance(view.get("gis_perception"), dict):
        view["gis_perception"] = {
            key: value
            for key, value in view["gis_perception"].items()
            if key
            in {
                "source_id",
                "source_path",
                "evidence_type",
                "status",
                "source_profile",
                "counts",
                "classifier",
                "boundary",
                "source_refs",
                "confidence",
                "stale_risk",
                "review_state",
                "candidate_only",
                "runtime_safety_truth",
            }
        }
    view["major_critical_points"] = _compact_major_critical_points(
        view.get("major_critical_points")
    )
    view["overpass_evidence"] = _compact_overpass_evidence(view.get("overpass_evidence"))
    view["reference_tracks"] = _compact_reference_tracks(view.get("reference_tracks"))


def _compact_segments(payload: Any) -> Any:
    if not isinstance(payload, list):
        return payload
    compact_segments = _compact_collection_list(
        payload,
        extra_keys=(
            "lat",
            "lon",
            "label",
            "distance_m",
            "gpx_distance_m",
            "from_candidate_id",
            "to_candidate_id",
            "overpass_projection",
            "overpass_route_distance_m",
            "route_basis",
        ),
    )
    for compact_segment, original_segment in zip(compact_segments, payload):
        if not isinstance(compact_segment, dict) or not isinstance(original_segment, dict):
            continue
        display_geometry = original_segment.get("display_geometry")
        if isinstance(display_geometry, dict):
            compact_segment["display_geometry"] = _compact_display_geometry(
                display_geometry,
                max_points_per_segment=_COMPACT_SEGMENT_DISPLAY_POINTS_PER_SEGMENT,
            )
    return compact_segments


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


def _load_admin_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _provider_live_output_dir(value: str | None, *, root: Path, default: Path) -> Path:
    if not value:
        return default
    output_root = (root / "outputs").resolve()
    requested = _path_from_admin_request(value)
    if requested.is_absolute():
        raise ValueError("provider-live output_dir must be relative to the wearable output root")
    if any(part == ".." for part in requested.parts):
        raise ValueError("provider-live output_dir cannot contain parent traversal")
    resolved = (output_root / requested).resolve()
    if resolved != output_root and output_root not in resolved.parents:
        raise ValueError("provider-live output_dir must stay under the wearable output root")
    return resolved


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
        "gpx_speed_filter_report": "outputs/gpx_speed_filter_report.json",
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


def _raster_tile_cache_root_for_project(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return _raster_tile_cache_root_from_env()
    try:
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _raster_tile_cache_root_from_env()
    cache_root = project.get("imagery_tile_cache_root")
    if isinstance(cache_root, str) and cache_root.strip():
        return Path(cache_root).expanduser()
    manifest_ref = project.get("raster_tile_manifest_ref")
    manifest_path = _safe_pretrip_project_ref_path(project_root, manifest_ref)
    if manifest_path is None or not manifest_path.exists():
        return _raster_tile_cache_root_from_env()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _raster_tile_cache_root_from_env()
    manifest_cache_root = manifest.get("cache_root")
    if isinstance(manifest_cache_root, str) and manifest_cache_root.strip():
        return Path(manifest_cache_root).expanduser()
    return _raster_tile_cache_root_from_env()


def _pretrip_project_payload_for_tiles(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> dict[str, Any]:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return {}
    try:
        return json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _imagery_source_registry_path_from_env() -> Path | None:
    value = os.getenv("SCOUT_IMAGERY_SOURCE_REGISTRY_PATH")
    return Path(value).expanduser() if value else None


def _imagery_remote_fetch_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_IMAGERY_REMOTE_FETCH", "false")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _imagery_remote_fetch_timeout_from_env() -> float:
    value = os.getenv("SCOUT_ADMIN_IMAGERY_REMOTE_FETCH_TIMEOUT_SECONDS")
    if not value:
        return 10.0
    try:
        timeout = float(value)
    except ValueError:
        return 10.0
    return max(0.25, min(timeout, 60.0))


def _safe_pretrip_project_ref_path(
    project_root: Path,
    ref: Any,
) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    candidate = Path(ref)
    if candidate.is_absolute() or any(part in {"..", "."} for part in candidate.parts):
        return None
    resolved_root = project_root.resolve()
    resolved_path = (project_root / candidate).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved_path


def _raster_tile_fallback_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_RASTER_TILE_FALLBACK", "true")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
