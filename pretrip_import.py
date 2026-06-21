from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from admin_imagery_sources import DEFAULT_IMAGERY_SOURCE_ID, DEFAULT_REGISTRY_ID
from geo_utils import haversine_m
from pretrip_candidate_generation import (
    generate_pretrip_candidates_from_gpx,
    generate_segment_candidates,
)
from pretrip_geojson_import import import_pretrip_geojson_candidates
from pretrip_gis_perception import build_gpx_gis_perception
from pretrip_gpx_corpus import (
    build_checkpoint_event_candidates,
    build_reference_track_display_geometry,
    build_reference_track_summary,
    build_segment_display_geometry,
    write_json,
)
from pretrip_gpx_filter import (
    DEFAULT_MAX_PREVIOUS_SPEED_RATIO,
    DEFAULT_MAX_REASONABLE_SPEED_KMH,
    write_speed_filtered_gpx,
)
from pretrip_mcp_synthesis import (
    DEFAULT_CP_SUPPORT_RECONCILIATION_OUTPUT_NAME,
    DEFAULT_OCR_LABEL_OUTPUT_NAME,
    DEFAULT_OUTPUT_NAME as DEFAULT_MCP_OUTPUT_NAME,
    DEFAULT_RETRIEVAL_PLAN_OUTPUT_NAME,
    build_cp_support_reconciliation,
    build_fixture_backed_retrieval_plan,
    load_named_point_evidence,
    normalize_ocr_labels_from_evidence,
    synthesize_mcp_candidates,
    write_cp_support_reconciliation,
    write_mcp_candidate_set,
    write_ocr_label_set,
    write_retrieval_plan,
)
from pretrip_models import (
    CandidateReviewState,
    DtmCoverageSummary,
    PreTripArtifactKind,
    PreTripCheckpointCandidate,
    PreTripPackage,
    PreTripProvenance,
    PreTripRetreatRouteCandidate,
    default_pretrip_package_boundary,
    default_pretrip_package_planning_semantics,
)
from pretrip_brain_seed import export_chilai_pretrip_brain_seed
from pretrip_mission_compiler import compile_pretrip_mission_graph
from pretrip_review_models import PreTripHumanReviewLog
from pretrip_review_queue import (
    PreTripReviewQueueManifest,
    ReviewQueueBoundary,
    ReviewQueueCategory,
    ReviewQueueCounts,
    ReviewQueueItem,
    build_chilai_review_queue_manifest,
)
from pretrip_route_note_review_options import build_route_note_review_options
from pretrip_segment_policy import build_chilai_segment_policy_candidates
from pretrip_source_ingest import (
    ingest_source_artifact,
    scan_dtm_coverage,
    sha256_file,
    summarize_gpx,
)
from pretrip_terrain_summary import summarize_segment_terrain_metadata
from pretrip_weather_daylight import (
    DaylightEvidenceWindow,
    PreTripWeatherDaylightEvidence,
    WeatherDaylightSourceRef,
    WeatherDaylightThresholdPolicy,
    WeatherDaylightValidation,
    WeatherWindowSummary,
)
from route_matching import GpxRoute, load_gpx_route
from runtime_debug_models import RuntimeDebugEvent


IMPORTER_VERSION = "0.1.0"
DEFAULT_CHECKPOINT_SPACING_M = 500.0
DEFAULT_IMAGERY_BBOX_SCALE_FACTOR = 1.15
DEFAULT_RESUME_SEGMENT_GAP_M = 1000.0
REST_AREA_MAX_SPEED_M_PER_MIN = 5.0
REST_AREA_CLUSTER_RADIUS_M = 80.0
REST_AREA_MIN_DURATION_SECONDS = 20 * 60
REST_AREA_MIN_SOURCE_POINT_COUNT = 16
ImportProfile = Literal["mac-workstation", "pi-offline", "pi-online-explicit"]
ImportStage = Literal["pretrip", "post_analysis"]
OFFLINE_PROFILES = {"mac-workstation", "pi-offline"}
DURABLE_ADMIN_EVIDENCE_REF_KEYS: tuple[str, ...] = (
    "readiness_report_ref",
    "resource_plan_ref",
    "planned_eta_ref",
    "departure_bundle_manifest_ref",
    "route_comparison_ref",
    "capability_timeline_import_ref",
    "post_analysis_capability_timeline_ref",
    "risk_route_profile_ref",
    "risk_route_profile_metadata_ref",
    "risk_route_profile_csv_ref",
    "risk_score_points_ref",
    "risk_score_points_metadata_ref",
    "risk_score_points_csv_ref",
    "risk_score_points_xyz_ref",
    "risk_ribbon_ref",
    "risk_ribbon_metadata_ref",
    "calibrated_risk_heatmap_ref",
    "calibrated_risk_heatmap_metadata_ref",
    "risk_attribution_diagnostic_ref",
    "route_pressure_profile_ref",
    "route_pressure_profile_geojson_ref",
    "boss_points_ref",
    "boss_points_geojson_ref",
)
DEFAULT_DURABLE_ADMIN_EVIDENCE_REFS: dict[str, str] = {
    "readiness_report_ref": "outputs/readiness_report.json",
    "resource_plan_ref": "outputs/resource_plan.json",
    "planned_eta_ref": "outputs/planned_eta.json",
    "departure_bundle_manifest_ref": "outputs/departure_bundle_manifest.json",
    "route_comparison_ref": "outputs/route_comparison.json",
    "capability_timeline_import_ref": "outputs/capability_timeline_import.json",
    "post_analysis_capability_timeline_ref": (
        "outputs/post_analysis_capability_timeline.json"
    ),
    "risk_route_profile_ref": "outputs/risk/route_risk.geojson",
    "risk_route_profile_metadata_ref": "outputs/risk/route_risk.metadata.json",
    "risk_route_profile_csv_ref": "outputs/risk/route_risk.csv",
    "risk_score_points_ref": "outputs/risk/risk_score_points.geojson",
    "risk_score_points_metadata_ref": "outputs/risk/risk_score_points.metadata.json",
    "risk_score_points_csv_ref": "outputs/risk/risk_score_points.csv",
    "risk_score_points_xyz_ref": "outputs/risk/risk_score_points.xyz",
    "risk_ribbon_ref": "outputs/risk/risk_ribbon.geojson",
    "risk_ribbon_metadata_ref": "outputs/risk/risk_ribbon.metadata.json",
    "calibrated_risk_heatmap_ref": "outputs/risk/calibrated_risk_heatmap.geojson",
    "calibrated_risk_heatmap_metadata_ref": (
        "outputs/risk/calibrated_risk_heatmap.metadata.json"
    ),
    "risk_attribution_diagnostic_ref": "outputs/risk/risk_attribution_diagnostic.json",
    "route_pressure_profile_ref": "outputs/route_pressure_profile.json",
    "route_pressure_profile_geojson_ref": "outputs/route_pressure_profile.geojson",
    "boss_points_ref": "outputs/boss_points.json",
    "boss_points_geojson_ref": "outputs/boss_points.geojson",
}
DURABLE_ADMIN_EVIDENCE_METADATA_KEYS: tuple[str, ...] = (
    "risk_route_sample_count",
    "risk_score_point_count",
    "risk_score_source_feature_count",
    "risk_score_source_profile",
    "risk_score_updated_at",
    "risk_ribbon_segment_count",
    "calibrated_risk_heatmap_segment_count",
    "calibrated_risk_heatmap_warning_cp_overlay_count",
    "risk_attribution_diagnostic_checkpoint_count",
    "route_pressure_sample_count",
    "route_pressure_peak_count",
    "boss_point_count",
    "boss_point_synthesis_status",
    "boss_point_synthesis_schema_version",
    "boss_point_synthesis_trigger",
    "boss_point_synthesis_updated_at",
    "boss_point_synthesis_candidate_only",
    "boss_point_synthesis_runtime_safety_truth",
)


@dataclass(frozen=True)
class PretripImportRequest:
    project_id: str
    # Backward-compatible name for the selected golden route GPX. In pretrip,
    # this is not the user's already-walked track.
    primary_gpx: Path
    workspace_root: Path
    reference_dir: Path | None = None
    reference_gpx_paths: tuple[Path, ...] = ()
    profile: ImportProfile = "pi-offline"
    template_project_root: Path | None = None
    checkpoint_spacing_m: float = DEFAULT_CHECKPOINT_SPACING_M
    max_reference_display_points: int = 1_000
    overwrite: bool = False
    import_timestamp: str | None = None
    import_stage: ImportStage = "pretrip"
    max_reasonable_gpx_speed_kmh: float = DEFAULT_MAX_REASONABLE_SPEED_KMH
    max_previous_gpx_speed_ratio: float = DEFAULT_MAX_PREVIOUS_SPEED_RATIO
    material_root: Path | None = None
    dtm_dirs: tuple[Path, ...] = ()
    mcp_named_point_evidence: Path | None = None


def run_pretrip_import(request: PretripImportRequest) -> dict[str, Any]:
    _validate_request(request)
    project_root = request.workspace_root.expanduser() / request.project_id
    _prepare_project_root(
        project_root=project_root,
        template_project_root=request.template_project_root,
        overwrite=request.overwrite,
    )

    primary_gpx = request.primary_gpx.expanduser().resolve()
    reference_paths = _reference_paths(request, primary_gpx=primary_gpx)
    import_timestamp = request.import_timestamp or _utc_now()
    source_inbox_manifest = _stage_source_inbox(
        project_root=project_root,
        project_id=request.project_id,
        primary_gpx=primary_gpx,
        reference_paths=reference_paths,
    )
    primary_artifact_id = f"artifact.gpx.{request.project_id}"
    package_id = f"pretrip.{request.project_id}.v0"
    gpx_filter = _prepare_speed_filtered_gpx(
        project_root=project_root,
        primary_gpx=primary_gpx,
        reference_paths=reference_paths,
        max_reasonable_speed_kmh=request.max_reasonable_gpx_speed_kmh,
        max_previous_speed_ratio=request.max_previous_gpx_speed_ratio,
    )
    filtered_primary_gpx = gpx_filter["primary"]["filtered_path"]
    filtered_reference_paths = [
        item["filtered_path"] for item in gpx_filter["references"]
    ]
    gpx_filter_report = _gpx_filter_manifest_payload(gpx_filter)
    gpx_speed_filter_report_ref = "outputs/gpx_speed_filter_report.json"

    route_summary = summarize_gpx(filtered_primary_gpx, primary_artifact_id)
    dtm_coverage_summary = _build_dtm_coverage_from_material(
        request=request,
        route_summary=route_summary,
        primary_artifact_id=primary_artifact_id,
    )
    candidate_result = generate_pretrip_candidates_from_gpx(
        filtered_primary_gpx,
        checkpoint_spacing_m=request.checkpoint_spacing_m,
        source_ref=primary_artifact_id,
    )
    route = load_gpx_route(filtered_primary_gpx)
    rest_area_report = _build_rest_area_candidate_report(
        project_id=request.project_id,
        primary_gpx=primary_gpx,
        filtered_route=route,
        primary_artifact_id=primary_artifact_id,
        gpx_speed_filter=gpx_filter_report["primary"],
    )
    checkpoint_candidates = _merge_rest_area_checkpoints(
        candidate_result.checkpoint_candidates,
        rest_area_report=rest_area_report,
        primary_gpx=primary_gpx,
        primary_artifact_id=primary_artifact_id,
    )
    checkpoint_candidates = _stamp_import_checkpoint_candidates(
        checkpoint_candidates,
        primary_artifact_id=primary_artifact_id,
    )
    _mark_rest_area_checkpoint_insertions(
        rest_area_report,
        checkpoint_candidates=checkpoint_candidates,
    )
    segment_candidates_base = generate_segment_candidates(
        route,
        checkpoint_candidates,
        source_ref=primary_artifact_id,
    )
    resume_segment_report = _build_resume_segment_report(
        route=route,
        segment_candidates=segment_candidates_base,
    )
    segment_candidates = _annotate_resume_segment_candidates(
        segment_candidates_base,
        resume_segment_report=resume_segment_report,
    )
    segment_candidates = _stamp_import_segment_candidates(
        segment_candidates,
        primary_artifact_id=primary_artifact_id,
    )
    source_artifacts = [
        ingest_source_artifact(
            artifact_id=primary_artifact_id,
            path=primary_gpx,
            kind=PreTripArtifactKind.GPX,
            media_type="application/gpx+xml",
            method="pretrip_import.run_pretrip_import",
            metadata={
                "role": _golden_route_role(request),
                "imported_at": import_timestamp,
                "import_stage": request.import_stage,
                "actual_user_track_available": request.import_stage == "post_analysis",
                "pretrip_selected_reference_route": request.import_stage == "pretrip",
                "gpx_speed_filter": _gpx_filter_source_summary(
                    gpx_filter_report["primary"],
                    report_ref=gpx_speed_filter_report_ref,
                ),
            },
        )
    ]
    for index, reference_path in enumerate(reference_paths, start=1):
        reference_id = f"{primary_artifact_id}.reference.{index:03d}"
        source_artifacts.append(
            ingest_source_artifact(
                artifact_id=reference_id,
                path=reference_path,
                kind=PreTripArtifactKind.GPX,
                media_type="application/gpx+xml",
                method="pretrip_import.run_pretrip_import",
                metadata={
                    "role": "reference_track",
                    "imported_at": import_timestamp,
                    "gpx_speed_filter": _gpx_filter_source_summary(
                        gpx_filter_report["references"][index - 1],
                        report_ref=gpx_speed_filter_report_ref,
                    ),
                },
            )
        )

    package = PreTripPackage(
        package_id=package_id,
        project_id=request.project_id,
        version=IMPORTER_VERSION,
        route_summary=route_summary,
        source_artifacts=source_artifacts,
        dtm_coverage_summary=dtm_coverage_summary,
        checkpoint_candidates=checkpoint_candidates,
        segment_candidates=segment_candidates,
        readiness_notes=[
            "Generated by standalone pretrip importer; planning candidate only.",
            (
                "Golden route（出發前選定的主參考路線）is not proof that the "
                "user has already walked this route."
            ),
            "Standalone importer（獨立匯入程式）output is not Phase 1 runtime safety truth.",
        ],
        planning_semantics={
            **default_pretrip_package_planning_semantics(),
            **_planning_semantics(request),
            "human_review_required_before_departure_gate": True,
        },
        boundary={
            **default_pretrip_package_boundary(),
            "actual_user_track_available": request.import_stage == "post_analysis",
            "raw_gpx_embedded_in_json": False,
            "gpx_speed_filter_applied": True,
        },
        metadata={
            "artifact_boundary_metadata_version": "pretrip_package_boundary.v1",
            "review_status_source": "importer_candidate_generation",
            "human_review_count": 0,
            "departure_approval_granted": False,
        },
    )

    map_context = _build_map_context(
        project_id=request.project_id,
        checkpoint_candidates=checkpoint_candidates,
    )
    map_candidates = import_pretrip_geojson_candidates(
        map_context,
        uri="normalized/map/map_context.geojson",
        source_ref="normalized/map/map_context.geojson",
    )
    reference_tracks = build_reference_track_summary(
        project_id=request.project_id,
        primary_gpx_path=filtered_primary_gpx,
        reference_gpx_paths=filtered_reference_paths,
        primary_artifact_id=primary_artifact_id,
    )
    checkpoint_events = build_checkpoint_event_candidates(
        project_id=request.project_id,
        route_gpx_path=filtered_primary_gpx,
        checkpoint_candidates=checkpoint_candidates,
        route_artifact_id=primary_artifact_id,
    )
    checkpoint_events = _stamp_checkpoint_event_provenance(
        checkpoint_events,
        checkpoint_candidates=checkpoint_candidates,
        primary_artifact_id=primary_artifact_id,
    )
    segment_display_geometry = build_segment_display_geometry(
        project_id=request.project_id,
        route_gpx_path=filtered_primary_gpx,
        segment_candidates=segment_candidates,
        route_artifact_id=primary_artifact_id,
    )
    segment_display_geometry = _stamp_segment_display_provenance(
        segment_display_geometry,
        segment_candidates=segment_candidates,
        primary_artifact_id=primary_artifact_id,
    )
    segment_display_geometry = _annotate_segment_display_geometry(
        segment_display_geometry,
        resume_segment_report=resume_segment_report,
    )
    segment_policy_candidates = build_chilai_segment_policy_candidates(package)
    segment_dtm_coverage = _build_import_segment_dtm_coverage(
        project_root=project_root,
        package=package,
    )
    retreat_routes = _build_default_retreat_routes(
        request=request,
        route_summary=route_summary.model_dump(mode="json"),
        checkpoint_candidates=checkpoint_candidates,
        primary_artifact_id=primary_artifact_id,
        primary_gpx=primary_gpx,
    )
    weather_daylight = _build_weather_daylight_placeholder(
        request=request,
        route_summary=route_summary.model_dump(mode="json"),
    )
    empty_review_log = PreTripHumanReviewLog(
        log_id=f"review_log.{request.project_id}.reimported.v0"
    )
    reviewed_path_package = package.model_copy(
        update={
            "status": "reviewed",
            "readiness_notes": [
                *package.readiness_notes,
                (
                    "Reviewed-path artifact mirrors the current re-imported "
                    "candidate package for admin continuity; it is not departure "
                    "approval and remains outside Phase 1 runtime safety truth."
                ),
            ],
            "metadata": {
                **package.metadata,
                "review_status_source": "reviewed_path_admin_continuity_placeholder",
                "human_review_count": 0,
                "review_log_ref": "reviews/human_reviews.json",
                "reviewed_package_is_not_departure_approval": True,
                "departure_approval_granted": False,
                "departure_gate_required_before_runtime": True,
            },
        }
    )
    compiled_candidate_graph = compile_pretrip_mission_graph(
        package,
        allow_unreviewed=True,
    )
    reference_display_geometry = build_reference_track_display_geometry(
        project_id=request.project_id,
        primary_gpx_path=filtered_primary_gpx,
        reference_gpx_paths=filtered_reference_paths,
        primary_artifact_id=primary_artifact_id,
        max_points_per_track=request.max_reference_display_points,
    )
    gis_perception_result = build_gpx_gis_perception(
        project_id=request.project_id,
        primary_gpx_path=filtered_primary_gpx,
        reference_gpx_paths=filtered_reference_paths,
        primary_artifact_id=primary_artifact_id,
    )
    route_note_review_options = build_route_note_review_options(
        gis_perception_result.route_note_ln_proposals
    )

    output_refs = {
        "source_inbox_manifest_ref": "inbox/source_manifest.json",
        "historical_gpx_source_index_ref": "sources/historical_gpx_source_index.json",
        "package_ref": "outputs/pretrip_package.json",
        "route_summary_ref": "normalized/routes/route_summary.json",
        "route_evidence_bundle_ref": "normalized/routes/route_evidence_bundle.json",
        "map_context_ref": "normalized/map/map_context.geojson",
        "map_candidates_ref": "candidates/map_candidates.json",
        "checkpoint_candidates_ref": "candidates/checkpoints.json",
        "segment_candidates_ref": "candidates/segments.json",
        "retreat_routes_ref": "candidates/retreat_routes.json",
        "route_note_candidates_ref": "candidates/route_note_candidates.json",
        "normalized_route_note_candidates_ref": "normalized/notes/gpx_route_note_candidates.json",
        "gis_perception_ai_judgements_ref": "outputs/gis_perception_ai_judgements.json",
        "route_note_ln_proposals_ref": "outputs/route_note_ln_proposals.json",
        "route_note_review_options_ref": "outputs/route_note_review_options.json",
        "gis_perception_candidates_ref": "outputs/gis_perception_candidates.json",
        "reference_tracks_ref": "outputs/reference_tracks.json",
        "reference_track_display_geometry_ref": "outputs/reference_track_display_geometry.json",
        "checkpoint_events_ref": "outputs/checkpoint_events.json",
        "segment_display_geometry_ref": "outputs/segment_display_geometry.json",
        "segment_policy_candidates_ref": "outputs/segment_policy_candidates.json",
        "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
        "human_reviews_ref": "reviews/human_reviews.json",
        "reviewed_package_ref": "outputs/pretrip_package.reviewed.json",
        "compiled_mission_graph_candidate_ref": "outputs/compiled_mission_graph.candidate.json",
        "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
        "brain_seed_nodes_ref": "outputs/brain_seed_nodes.json",
        "gpx_speed_filter_report_ref": gpx_speed_filter_report_ref,
        "resume_segment_report_ref": "outputs/resume_segments.json",
        "rest_area_candidates_ref": "outputs/rest_area_candidates.json",
        "import_manifest_ref": "outputs/import_manifest.json",
        "admin_projection_ref": "outputs/admin_projection.json",
        "debug_projection_events_ref": "outputs/debug_projection_events.jsonl",
    }
    if dtm_coverage_summary is not None:
        output_refs["dtm_coverage_summary_ref"] = (
            "normalized/terrain/dtm_coverage_summary.json"
        )
    if segment_dtm_coverage is not None:
        output_refs["segment_dtm_coverage_ref"] = (
            "normalized/terrain/segment_dtm_coverage.json"
        )
    mcp_import_summary = _build_mcp_import_artifacts(
        request=request,
        project_root=project_root,
        output_refs=output_refs,
        route_name=route_summary.route_name,
        checkpoint_candidates=checkpoint_candidates,
        import_timestamp=import_timestamp,
    )
    historical_gpx_source_index = _build_historical_gpx_source_index(
        project_id=request.project_id,
        import_timestamp=import_timestamp,
        source_inbox_manifest=source_inbox_manifest,
    )
    route_evidence_bundle = _build_route_evidence_bundle(
        request=request,
        project_root=project_root,
        primary_artifact_id=primary_artifact_id,
        primary_gpx=primary_gpx,
        reference_paths=reference_paths,
        route_summary=route_summary.model_dump(mode="json"),
        output_refs=output_refs,
        gpx_speed_filter=gpx_filter_report,
    )
    manifest = _build_import_manifest(
        request=request,
        project_root=project_root,
        primary_gpx=primary_gpx,
        reference_paths=reference_paths,
        import_timestamp=import_timestamp,
        output_refs=output_refs,
        route_summary=route_summary.model_dump(mode="json"),
        checkpoint_count=len(checkpoint_candidates),
        segment_count=len(segment_candidates),
        rest_area_report=rest_area_report,
        resume_segment_report=resume_segment_report,
        gis_perception=gis_perception_result.gis_perception.model_dump(mode="json"),
        gis_perception_ai_judgements=gis_perception_result.gis_perception_ai_judgements.model_dump(mode="json"),
        route_note_candidates=gis_perception_result.route_note_candidates.model_dump(mode="json"),
        route_note_ln_proposals=gis_perception_result.route_note_ln_proposals.model_dump(mode="json"),
        route_note_review_options=route_note_review_options.model_dump(mode="json"),
        source_inbox_manifest=source_inbox_manifest,
        historical_gpx_source_index=historical_gpx_source_index,
        gpx_speed_filter=gpx_filter_report,
    )
    _attach_mcp_import_manifest(manifest, mcp_import_summary)
    admin_projection = _build_admin_projection(
        request=request,
        project_root=project_root,
        route_summary=route_summary.model_dump(mode="json"),
        output_refs=output_refs,
        reference_track_count=len(reference_paths),
        checkpoint_count=len(checkpoint_candidates),
        segment_count=len(segment_candidates),
        segment_display_geometry=segment_display_geometry,
        rest_area_report=rest_area_report,
        resume_segment_report=resume_segment_report,
        gis_perception=gis_perception_result.gis_perception.model_dump(mode="json"),
        gis_perception_ai_judgements=gis_perception_result.gis_perception_ai_judgements.model_dump(mode="json"),
        route_note_candidates=gis_perception_result.route_note_candidates.model_dump(mode="json"),
        route_note_ln_proposals=gis_perception_result.route_note_ln_proposals.model_dump(mode="json"),
        route_note_review_options=route_note_review_options.model_dump(mode="json"),
        gpx_speed_filter=gpx_filter_report,
    )
    debug_events = _build_debug_projection_events(
        request=request,
        import_timestamp=import_timestamp,
        route_summary=route_summary.model_dump(mode="json"),
        reference_track_count=len(reference_paths),
        checkpoint_count=len(checkpoint_candidates),
        segment_count=len(segment_candidates),
        rest_area_report=rest_area_report,
        resume_segment_report=resume_segment_report,
        gis_perception=gis_perception_result.gis_perception.model_dump(mode="json"),
        gis_perception_ai_judgements=gis_perception_result.gis_perception_ai_judgements.model_dump(mode="json"),
        gpx_speed_filter=gpx_filter_report,
    )
    manifest["counts"]["debug_projection_event_count"] = len(debug_events)

    write_json(project_root / output_refs["package_ref"], package.model_dump(mode="json"))
    write_json(project_root / output_refs["route_summary_ref"], route_summary.model_dump(mode="json"))
    write_json(
        project_root / output_refs["historical_gpx_source_index_ref"],
        historical_gpx_source_index,
    )
    write_json(project_root / output_refs["route_evidence_bundle_ref"], route_evidence_bundle)
    write_json(project_root / output_refs["map_context_ref"], map_context)
    write_json(project_root / output_refs["map_candidates_ref"], map_candidates.model_dump(mode="json"))
    write_json(
        project_root / output_refs["checkpoint_candidates_ref"],
        [candidate.model_dump(mode="json") for candidate in checkpoint_candidates],
    )
    write_json(
        project_root / output_refs["segment_candidates_ref"],
        [candidate.model_dump(mode="json") for candidate in segment_candidates],
    )
    write_json(
        project_root / output_refs["retreat_routes_ref"],
        [candidate.model_dump(mode="json") for candidate in retreat_routes],
    )
    write_json(
        project_root / output_refs["route_note_candidates_ref"],
        gis_perception_result.route_note_candidates.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["normalized_route_note_candidates_ref"],
        gis_perception_result.route_note_candidates.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["gis_perception_ai_judgements_ref"],
        gis_perception_result.gis_perception_ai_judgements.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["route_note_ln_proposals_ref"],
        gis_perception_result.route_note_ln_proposals.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["route_note_review_options_ref"],
        route_note_review_options.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["gis_perception_candidates_ref"],
        gis_perception_result.gis_perception.model_dump(mode="json"),
    )
    write_json(project_root / output_refs["reference_tracks_ref"], reference_tracks)
    write_json(project_root / output_refs["gpx_speed_filter_report_ref"], gpx_filter_report)
    write_json(project_root / output_refs["resume_segment_report_ref"], resume_segment_report)
    write_json(project_root / output_refs["rest_area_candidates_ref"], rest_area_report)
    write_json(
        project_root / output_refs["reference_track_display_geometry_ref"],
        reference_display_geometry,
    )
    write_json(project_root / output_refs["checkpoint_events_ref"], checkpoint_events)
    write_json(project_root / output_refs["segment_display_geometry_ref"], segment_display_geometry)
    write_json(
        project_root / output_refs["segment_policy_candidates_ref"],
        segment_policy_candidates.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["weather_daylight_evidence_ref"],
        weather_daylight.model_dump(mode="json"),
    )
    if dtm_coverage_summary is not None:
        write_json(
            project_root / output_refs["dtm_coverage_summary_ref"],
            dtm_coverage_summary.model_dump(mode="json"),
        )
    write_json(
        project_root / output_refs["human_reviews_ref"],
        empty_review_log.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["reviewed_package_ref"],
        reviewed_path_package.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["compiled_mission_graph_candidate_ref"],
        compiled_candidate_graph.model_dump(mode="json"),
    )
    write_json(
        project_root / output_refs["compiled_mission_graph_reviewed_ref"],
        compiled_candidate_graph.model_dump(mode="json"),
    )
    if segment_dtm_coverage is not None:
        write_json(
            project_root / output_refs["segment_dtm_coverage_ref"],
            segment_dtm_coverage.model_dump(mode="json"),
        )
    write_json(project_root / output_refs["import_manifest_ref"], manifest)
    write_json(project_root / output_refs["admin_projection_ref"], admin_projection)
    _write_jsonl(project_root / output_refs["debug_projection_events_ref"], debug_events)
    project_payload = _project_payload(
        project_root=project_root,
        project_id=request.project_id,
        output_refs=output_refs,
        route_summary=route_summary.model_dump(mode="json"),
        reference_track_count=len(reference_paths),
        checkpoint_count=len(checkpoint_candidates),
        segment_count=len(segment_candidates),
        resume_segment_count=resume_segment_report["resume_segment_count"],
        rest_area_candidate_count=rest_area_report["rest_area_candidate_count"],
        rest_area_checkpoint_count=rest_area_report["rest_area_checkpoint_count"],
        checkpoint_event_count=len(checkpoint_events["events"]),
        reference_track_display_geometry_count=reference_display_geometry[
            "reference_track_count"
        ],
        gis_perception=gis_perception_result.gis_perception.model_dump(mode="json"),
        gis_perception_ai_judgements=gis_perception_result.gis_perception_ai_judgements.model_dump(mode="json"),
        route_note_ln_proposals=gis_perception_result.route_note_ln_proposals.model_dump(mode="json"),
        route_note_review_options=route_note_review_options.model_dump(mode="json"),
        source_inbox_manifest=source_inbox_manifest,
        import_stage=request.import_stage,
        gpx_speed_filter=gpx_filter_report,
        segment_display_geometry=segment_display_geometry,
        segment_policy_candidates=segment_policy_candidates.model_dump(mode="json"),
        retreat_route_count=len(retreat_routes),
        weather_daylight_evidence_count=1,
        segment_dtm_coverage=(
            segment_dtm_coverage.model_dump(mode="json")
            if segment_dtm_coverage is not None
            else None
        ),
        dtm_coverage_summary=(
            dtm_coverage_summary.model_dump(mode="json")
            if dtm_coverage_summary is not None
            else None
        ),
        mcp_import_summary=mcp_import_summary,
    )
    write_json(project_root / "project.json", project_payload)
    brain_seed = _rebuild_brain_seed_if_possible(
        project_root=project_root,
        mission_id=compiled_candidate_graph.mission_id,
    )
    if brain_seed is not None:
        write_json(
            project_root / output_refs["brain_seed_nodes_ref"],
            brain_seed.model_dump(),
        )
        project_payload["brain_seed_node_count"] = len(brain_seed.nodes)
    project_payload["human_review_count"] = 0
    write_json(project_root / "project.json", project_payload)
    runtime_handoff_metadata = _rebuild_runtime_handoff_metadata_if_possible(project_root)
    if runtime_handoff_metadata is not None:
        runtime_handoff_ref = project_payload.get(
            "runtime_handoff_metadata_ref",
            "outputs/runtime_handoff_metadata.candidate.json",
        )
        write_json(
            project_root / runtime_handoff_ref,
            runtime_handoff_metadata.model_dump(mode="json"),
        )
        project_payload["runtime_handoff_metadata_ref"] = runtime_handoff_ref
        write_json(project_root / "project.json", project_payload)
        _refresh_admin_projection_export_summaries(project_root)
    review_queue_manifest = _rebuild_review_queue_if_possible(project_root)
    if review_queue_manifest is not None:
        write_json(
            project_root / "outputs" / "review_queue_manifest.json",
            review_queue_manifest.model_dump(mode="json"),
        )
        project_payload["review_queue_manifest_ref"] = "outputs/review_queue_manifest.json"
        project_payload["review_queue_item_count"] = review_queue_manifest.counts.item_count
        write_json(project_root / "project.json", project_payload)
    return manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Import a local GPX corpus into a Scout pretrip project workspace."
    )
    parser.add_argument("--project-id", required=True)
    route_group = parser.add_mutually_exclusive_group(required=True)
    route_group.add_argument(
        "--golden-route-gpx",
        type=Path,
        help=(
            "Selected golden route GPX for pretrip planning; this is a similar "
            "reference route, not the user's actual track before departure."
        ),
    )
    route_group.add_argument(
        "--primary-gpx",
        type=Path,
        help="Deprecated alias for --golden-route-gpx.",
    )
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--reference-gpx", type=Path, action="append", default=[])
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument(
        "--profile",
        choices=("mac-workstation", "pi-offline", "pi-online-explicit"),
        default="pi-offline",
    )
    parser.add_argument("--template-project-root", type=Path)
    parser.add_argument(
        "--material-root",
        type=Path,
        help=(
            "Fixed Scout pretrip material root. When omitted, "
            "SCOUT_PRETRIP_MATERIAL_ROOT or /data/scout/materials/pretrip/<project-id> "
            "is used if present."
        ),
    )
    parser.add_argument(
        "--dtm-dir",
        type=Path,
        action="append",
        default=[],
        help=(
            "Additional local DTM source directory for metadata-only terrain "
            "coverage. Material-root DTM dirs remain included when present."
        ),
    )
    parser.add_argument(
        "--mcp-named-point-evidence",
        type=Path,
        help=(
            "Fixture-backed named-point evidence for MCP synthesis. When omitted, "
            "the importer looks for sources/mcp/named_point_evidence.json under "
            "the fixed material root."
        ),
    )
    parser.add_argument("--checkpoint-spacing-m", type=float, default=DEFAULT_CHECKPOINT_SPACING_M)
    parser.add_argument("--max-reference-display-points", type=int, default=1_000)
    parser.add_argument(
        "--max-reasonable-gpx-speed-kmh",
        type=float,
        default=DEFAULT_MAX_REASONABLE_SPEED_KMH,
        help="Remove GPX track points that require more than this speed from the previous kept point.",
    )
    parser.add_argument(
        "--max-previous-gpx-speed-ratio",
        type=float,
        default=DEFAULT_MAX_PREVIOUS_SPEED_RATIO,
        help=(
            "Remove GPX track points that require more than this multiple of "
            "the previous kept segment speed."
        ),
    )
    parser.add_argument(
        "--import-stage",
        choices=("pretrip", "post_analysis"),
        default="pretrip",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    golden_route_gpx = args.golden_route_gpx or args.primary_gpx

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id=args.project_id,
            primary_gpx=golden_route_gpx,
            reference_dir=args.reference_dir,
            reference_gpx_paths=tuple(args.reference_gpx),
            workspace_root=args.workspace_root,
            profile=args.profile,
            template_project_root=args.template_project_root,
            checkpoint_spacing_m=args.checkpoint_spacing_m,
            max_reference_display_points=args.max_reference_display_points,
            max_reasonable_gpx_speed_kmh=args.max_reasonable_gpx_speed_kmh,
            max_previous_gpx_speed_ratio=args.max_previous_gpx_speed_ratio,
            material_root=args.material_root,
            dtm_dirs=tuple(args.dtm_dir),
            mcp_named_point_evidence=args.mcp_named_point_evidence,
            overwrite=args.overwrite,
            import_stage=args.import_stage,
        )
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))


def _validate_request(request: PretripImportRequest) -> None:
    if not request.project_id:
        raise ValueError("project_id is required")
    if request.profile not in {"mac-workstation", "pi-offline", "pi-online-explicit"}:
        raise ValueError(f"unsupported import profile: {request.profile}")
    if request.profile == "pi-online-explicit":
        raise ValueError("pi-online-explicit is reserved for a later audited network slice")
    if request.import_stage not in {"pretrip", "post_analysis"}:
        raise ValueError(f"unsupported import stage: {request.import_stage}")
    if request.checkpoint_spacing_m <= 0:
        raise ValueError("checkpoint_spacing_m must be greater than 0")
    if request.max_reference_display_points <= 0:
        raise ValueError("max_reference_display_points must be greater than 0")
    if request.max_reasonable_gpx_speed_kmh <= 0:
        raise ValueError("max_reasonable_gpx_speed_kmh must be greater than 0")
    if request.max_previous_gpx_speed_ratio <= 0:
        raise ValueError("max_previous_gpx_speed_ratio must be greater than 0")
    primary = request.primary_gpx.expanduser()
    if not primary.exists():
        raise FileNotFoundError(f"golden route GPX not found: {primary}")
    if request.reference_dir is not None and not request.reference_dir.expanduser().exists():
        raise FileNotFoundError(f"reference directory not found: {request.reference_dir}")
    if request.template_project_root is not None and not request.template_project_root.expanduser().exists():
        raise FileNotFoundError(f"template project root not found: {request.template_project_root}")
    if request.material_root is not None and not request.material_root.expanduser().exists():
        raise FileNotFoundError(f"material root not found: {request.material_root}")
    if (
        request.mcp_named_point_evidence is not None
        and not request.mcp_named_point_evidence.expanduser().exists()
    ):
        raise FileNotFoundError(
            f"MCP named-point evidence not found: {request.mcp_named_point_evidence}"
        )
    for dtm_dir in request.dtm_dirs:
        if not dtm_dir.expanduser().exists():
            raise FileNotFoundError(f"DTM directory not found: {dtm_dir}")


def _prepare_project_root(
    *,
    project_root: Path,
    template_project_root: Path | None,
    overwrite: bool,
) -> None:
    if project_root.exists():
        if not overwrite:
            raise FileExistsError(f"project workspace already exists: {project_root}")
        shutil.rmtree(project_root)
    if template_project_root is not None:
        shutil.copytree(template_project_root.expanduser(), project_root)
    else:
        project_root.mkdir(parents=True)


def _reference_paths(request: PretripImportRequest, *, primary_gpx: Path) -> list[Path]:
    candidates = [path.expanduser().resolve() for path in request.reference_gpx_paths]
    if request.reference_dir is not None:
        candidates.extend(sorted(path.resolve() for path in request.reference_dir.expanduser().glob("*.gpx")))
    unique: dict[str, Path] = {}
    for path in candidates:
        if path == primary_gpx:
            continue
        if not path.exists():
            raise FileNotFoundError(f"reference GPX not found: {path}")
        unique[path.as_posix()] = path
    return [unique[key] for key in sorted(unique)]


def _stage_source_inbox(
    *,
    project_root: Path,
    project_id: str,
    primary_gpx: Path,
    reference_paths: list[Path],
) -> dict[str, Any]:
    inbox_root = project_root / "inbox"
    gpx_root = inbox_root / "gpx"
    gpx_root.mkdir(parents=True, exist_ok=True)

    sources: list[dict[str, Any]] = []
    staged = [(primary_gpx, "golden_route_reference", "primary")]
    staged.extend(
        (path, "reference_track", f"reference_{index:03d}")
        for index, path in enumerate(reference_paths, start=1)
    )
    for path, role, prefix in staged:
        destination = gpx_root / f"{prefix}.{_safe_file_name(path.name)}"
        if path.resolve() != destination.resolve():
            shutil.copy2(path, destination)
        stat = destination.stat()
        sources.append(
            {
                "role": role,
                "original_path": path.resolve().as_posix(),
                "workspace_ref": destination.relative_to(project_root).as_posix(),
                "sha256": sha256_file(destination),
                "size_bytes": stat.st_size,
                "media_type": "application/gpx+xml",
                "imported_as_raw_file": True,
                "raw_payload_embedded_in_json": False,
            }
        )

    manifest = {
        "artifact_kind": "pretrip_source_inbox_manifest",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "source_file_count": len(sources),
        "raw_payloads_embedded": False,
        "sources": sources,
        "boundary": {
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "raw_gpx_embedded_in_json": False,
        },
    }
    write_json(inbox_root / "source_manifest.json", manifest)
    return manifest


def _build_historical_gpx_source_index(
    *,
    project_id: str,
    import_timestamp: str,
    source_inbox_manifest: dict[str, Any],
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for index, source in enumerate(source_inbox_manifest["sources"]):
        role = source["role"]
        source_id = (
            f"gpx.source.{project_id}.primary"
            if index == 0
            else f"gpx.source.{project_id}.reference.{index:03d}"
        )
        route_role = "golden_route" if role == "golden_route_reference" else role
        original_path = source["original_path"]
        sources.append(
            {
                "source_id": source_id,
                "route_role": route_role,
                "role": role,
                "original_path": original_path,
                "original_filename": Path(original_path).name,
                "workspace_ref": source["workspace_ref"],
                "sha256": source["sha256"],
                "size_bytes": source["size_bytes"],
                "media_type": source["media_type"],
                "provider": "operator_supplied_local_file",
                "source_url": None,
                "license_permission_note": "operator supplied local GPX; permission must be reviewed before publication.",
                "imported_at": import_timestamp,
                "importer_version": IMPORTER_VERSION,
                "imported_as_raw_file": source.get("imported_as_raw_file", True),
                "raw_payload_embedded_in_json": False,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    return {
        "artifact_kind": "pretrip_historical_gpx_source_index",
        "schema_version": "historical_gpx_importer.v1",
        "project_id": project_id,
        "source_file_count": len(sources),
        "raw_payloads_embedded": False,
        "sources": sources,
        "boundary": {
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "raw_gpx_embedded_in_json": False,
        },
    }


def _prepare_speed_filtered_gpx(
    *,
    project_root: Path,
    primary_gpx: Path,
    reference_paths: list[Path],
    max_reasonable_speed_kmh: float,
    max_previous_speed_ratio: float,
) -> dict[str, Any]:
    filter_root = project_root / "normalized" / "routes" / "filtered"
    primary_report = write_speed_filtered_gpx(
        primary_gpx,
        filter_root / f"primary.{_safe_file_stem(primary_gpx)}.speed_filtered.gpx",
        max_reasonable_speed_kmh=max_reasonable_speed_kmh,
        max_previous_speed_ratio=max_previous_speed_ratio,
    )
    reference_reports = []
    for index, reference_path in enumerate(reference_paths, start=1):
        reference_reports.append(
            write_speed_filtered_gpx(
                reference_path,
                filter_root
                / f"reference_{index:03d}.{_safe_file_stem(reference_path)}.speed_filtered.gpx",
                max_reasonable_speed_kmh=max_reasonable_speed_kmh,
                max_previous_speed_ratio=max_previous_speed_ratio,
            )
        )
    return {
        "primary": {
            "original_path": primary_gpx,
            "filtered_path": Path(primary_report.output_path),
            "report": primary_report,
        },
        "references": [
            {
                "original_path": original_path,
                "filtered_path": Path(report.output_path),
                "report": report,
            }
            for original_path, report in zip(reference_paths, reference_reports)
        ],
    }


def _gpx_filter_manifest_payload(gpx_filter: dict[str, Any]) -> dict[str, Any]:
    primary = gpx_filter["primary"]["report"].to_dict()
    references = [item["report"].to_dict() for item in gpx_filter["references"]]
    source_reports = [primary, *references]
    return {
        "artifact_kind": "pretrip_gpx_speed_filter_report",
        "schema_version": "0.1.0",
        "filter_scope": "pretrip_import_gpx_sources",
        "max_reasonable_speed_kmh": primary["max_reasonable_speed_kmh"],
        "max_previous_speed_ratio": primary["max_previous_speed_ratio"],
        "route_note_protection_radius_m": primary[
            "route_note_protection_radius_m"
        ],
        "source_file_count": len(source_reports),
        "original_track_point_count": sum(
            item["original_track_point_count"] for item in source_reports
        ),
        "filtered_track_point_count": sum(
            item["filtered_track_point_count"] for item in source_reports
        ),
        "removed_track_point_count": sum(
            item["removed_track_point_count"] for item in source_reports
        ),
        "exempted_track_point_count": sum(
            item["exempted_track_point_count"] for item in source_reports
        ),
        "primary": primary,
        "references": references,
        "boundary": {
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "raw_gpx_embedded_in_json": False,
            "original_source_gpx_preserved_as_source_artifact": True,
        },
    }


def _safe_file_stem(path: Path) -> str:
    allowed = []
    for character in path.stem:
        if character.isalnum() or character in {"-", "_"}:
            allowed.append(character)
        else:
            allowed.append("_")
    return "".join(allowed).strip("_") or "route"


def _safe_file_name(name: str) -> str:
    path = Path(name)
    suffix = "".join(path.suffixes) or ".gpx"
    stem = _safe_file_stem(path)
    return f"{stem}{suffix}"


def _build_resume_segment_report(
    *,
    route: GpxRoute,
    segment_candidates: list[Any],
    max_gap_m: float = DEFAULT_RESUME_SEGMENT_GAP_M,
) -> dict[str, Any]:
    segment_reports: list[dict[str, Any]] = []
    for segment in segment_candidates:
        start_index = segment.route_point_start_index
        end_index = segment.route_point_end_index
        if start_index is None or end_index is None or start_index >= end_index:
            continue
        large_gaps = []
        for previous_index in range(start_index, end_index):
            if previous_index + 1 >= len(route.points):
                continue
            previous = route.points[previous_index]
            current = route.points[previous_index + 1]
            distance_m = haversine_m(previous.lat, previous.lon, current.lat, current.lon)
            if distance_m <= max_gap_m:
                continue
            large_gaps.append(
                {
                    "from_route_point_index": previous_index,
                    "to_route_point_index": previous_index + 1,
                    "distance_m": round(distance_m, 3),
                    "from_time": previous.timestamp,
                    "to_time": current.timestamp,
                    "from_lat": round(previous.lat, 7),
                    "from_lon": round(previous.lon, 7),
                    "to_lat": round(current.lat, 7),
                    "to_lon": round(current.lon, 7),
                }
            )
        if not large_gaps:
            continue
        segment_reports.append(
            {
                "segment_candidate_id": segment.candidate_id,
                "from_candidate_id": segment.from_candidate_id,
                "to_candidate_id": segment.to_candidate_id,
                "route_point_start_index": start_index,
                "route_point_end_index": end_index,
                "resume_segment": True,
                "resume_gap_count": len(large_gaps),
                "max_gap_m": max(item["distance_m"] for item in large_gaps),
                "gaps": large_gaps,
            }
        )
    return {
        "artifact_kind": "pretrip_resume_segment_diagnostic",
        "schema_version": "0.1.0",
        "max_reasonable_point_gap_m": max_gap_m,
        "resume_segment_count": len(segment_reports),
        "segments": segment_reports,
        "boundary": {
            "candidate_diagnostic_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "gpx_points_pruned_for_gap": False,
        },
        "notes": [
            "Adjacent kept GPX points farther than max_reasonable_point_gap_m are preserved and marked as resume segments.",
            "This catches multi-day or GPS-off gaps without cascading point deletion.",
        ],
    }


def _annotate_resume_segment_candidates(
    segment_candidates: list[Any],
    *,
    resume_segment_report: dict[str, Any],
) -> list[Any]:
    resume_by_id = {
        item["segment_candidate_id"]: item
        for item in resume_segment_report.get("segments", [])
    }
    annotated = []
    for segment in segment_candidates:
        resume = resume_by_id.get(segment.candidate_id)
        if not resume:
            annotated.append(segment)
            continue
        note = (
            f"Resume segment: contains {resume['resume_gap_count']} adjacent GPX "
            f"gap(s) over {resume_segment_report['max_reasonable_point_gap_m']}m; "
            "preserved as cross-day/GPS-off evidence instead of pruning."
        )
        existing_notes = segment.notes.strip()
        annotated.append(
            segment.model_copy(
                update={
                    "notes": f"{existing_notes} {note}".strip(),
                    "review_state": CandidateReviewState.NEEDS_REVIEW,
                }
            )
        )
    return annotated


def _stamp_import_checkpoint_candidates(
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    *,
    primary_artifact_id: str,
) -> list[PreTripCheckpointCandidate]:
    return [
        _stamp_import_candidate(
            candidate,
            primary_artifact_id=primary_artifact_id,
            evidence_type="pretrip_checkpoint_candidate",
            source_kind="gpx_route",
            method="pretrip_candidate_generation.generate_checkpoint_candidates",
        )
        for candidate in checkpoint_candidates
    ]


def _stamp_import_segment_candidates(
    segment_candidates: list[Any],
    *,
    primary_artifact_id: str,
) -> list[Any]:
    return [
        _stamp_import_candidate(
            candidate,
            primary_artifact_id=primary_artifact_id,
            evidence_type="pretrip_segment_candidate",
            source_kind="gpx_route_segment",
            method="pretrip_candidate_generation.generate_segment_candidates",
        )
        for candidate in segment_candidates
    ]


def _stamp_import_candidate(
    candidate: Any,
    *,
    primary_artifact_id: str,
    evidence_type: str,
    source_kind: str,
    method: str,
) -> Any:
    source_refs = list(dict.fromkeys([*candidate.source_refs, primary_artifact_id]))
    source_attribution = [
        {
            **attribution,
            "confidence": attribution.get("confidence", candidate.confidence),
            "stale_risk": attribution.get("stale_risk", candidate.stale_risk),
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for attribution in candidate.source_attribution
    ]
    if not source_attribution:
        source_attribution = [
            {
                "source_kind": source_kind,
                "source_ref": primary_artifact_id,
                "source_candidate_id": candidate.candidate_id,
                "method": method,
                "evidence_type": evidence_type,
                "confidence": candidate.confidence,
                "stale_risk": candidate.stale_risk,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
    summary = (
        f"{evidence_type} generated from filtered GPX route geometry by "
        "deterministic pretrip importer; candidate-only evidence, not runtime "
        "safety truth."
    )
    return candidate.model_copy(
        update={
            "source_refs": source_refs,
            "source_attribution": source_attribution,
            "extractor_version": f"pretrip_import.{IMPORTER_VERSION}",
            "pydantic_ai_prompt_version": (
                "not_applicable_deterministic_pretrip_import"
            ),
            "model_output_summary": summary,
            "model_output_sha256": _candidate_provenance_hash(
                candidate,
                evidence_type=evidence_type,
                source_refs=source_refs,
            ),
            "stale_risk": candidate.stale_risk or "medium",
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )


def _candidate_provenance_hash(
    candidate: Any,
    *,
    evidence_type: str,
    source_refs: list[str],
) -> str:
    material = {
        "candidate_id": candidate.candidate_id,
        "label": candidate.label,
        "source_refs": source_refs,
        "evidence_type": evidence_type,
        "route_point_index": getattr(candidate, "route_point_index", None),
        "route_point_start_index": getattr(candidate, "route_point_start_index", None),
        "route_point_end_index": getattr(candidate, "route_point_end_index", None),
        "from_candidate_id": getattr(candidate, "from_candidate_id", None),
        "to_candidate_id": getattr(candidate, "to_candidate_id", None),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _stamp_checkpoint_event_provenance(
    checkpoint_events: dict[str, Any],
    *,
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    primary_artifact_id: str,
) -> dict[str, Any]:
    candidates_by_id = {candidate.candidate_id: candidate for candidate in checkpoint_candidates}
    for event in checkpoint_events.get("events", []):
        candidate = candidates_by_id.get(event.get("checkpoint_candidate_id"))
        source_refs = event.get("source_refs") or [primary_artifact_id]
        if candidate is not None:
            source_refs = list(dict.fromkeys([*source_refs, *candidate.source_refs]))
        event["source_refs"] = source_refs
        event["source_attribution"] = [
            {
                "source_kind": "pretrip_checkpoint_candidate",
                "source_ref": primary_artifact_id,
                "source_candidate_id": event.get("checkpoint_candidate_id"),
                "method": "pretrip_gpx_corpus.build_checkpoint_event_candidates",
                "evidence_type": "pretrip_checkpoint_event_projection",
                "confidence": candidate.confidence if candidate else "medium",
                "stale_risk": candidate.stale_risk if candidate else "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
        event["extractor_version"] = f"pretrip_import.{IMPORTER_VERSION}"
        event["pydantic_ai_prompt_version"] = (
            "not_applicable_deterministic_pretrip_import"
        )
        event["model_output_summary"] = (
            "Checkpoint event projection generated from pretrip checkpoint "
            "candidate for admin timeline display; candidate-only evidence."
        )
        event["model_output_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    "event_id": event.get("event_id"),
                    "checkpoint_candidate_id": event.get("checkpoint_candidate_id"),
                    "source_refs": source_refs,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        event["confidence"] = candidate.confidence if candidate else "medium"
        event["stale_risk"] = candidate.stale_risk if candidate else "medium"
        event["review_state"] = str(candidate.review_state) if candidate else "proposed"
        event["candidate_only"] = True
        event["runtime_safety_truth"] = False
    return checkpoint_events


def _stamp_segment_display_provenance(
    segment_display_geometry: dict[str, Any],
    *,
    segment_candidates: list[Any],
    primary_artifact_id: str,
) -> dict[str, Any]:
    candidates_by_id = {candidate.candidate_id: candidate for candidate in segment_candidates}
    for segment in segment_display_geometry.get("segments", []):
        candidate = candidates_by_id.get(segment.get("segment_candidate_id"))
        source_refs = [primary_artifact_id]
        if candidate is not None:
            source_refs = list(dict.fromkeys([*source_refs, *candidate.source_refs]))
        segment["source_refs"] = source_refs
        segment["source_attribution"] = [
            {
                "source_kind": "pretrip_segment_candidate",
                "source_ref": primary_artifact_id,
                "source_candidate_id": segment.get("segment_candidate_id"),
                "method": "pretrip_gpx_corpus.build_segment_display_geometry",
                "evidence_type": "pretrip_segment_display_geometry",
                "confidence": candidate.confidence if candidate else "medium",
                "stale_risk": candidate.stale_risk if candidate else "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
        segment["extractor_version"] = f"pretrip_import.{IMPORTER_VERSION}"
        segment["pydantic_ai_prompt_version"] = (
            "not_applicable_deterministic_pretrip_import"
        )
        segment["model_output_summary"] = (
            "Segment display geometry generated from pretrip segment candidate "
            "for admin map projection; candidate-only evidence."
        )
        segment["model_output_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    "segment_candidate_id": segment.get("segment_candidate_id"),
                    "source_refs": source_refs,
                    "route_point_start_index": segment.get("route_point_start_index"),
                    "route_point_end_index": segment.get("route_point_end_index"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        segment["confidence"] = candidate.confidence if candidate else "medium"
        segment["stale_risk"] = candidate.stale_risk if candidate else "medium"
        segment["review_state"] = str(candidate.review_state) if candidate else "proposed"
        segment["candidate_only"] = True
        segment["runtime_safety_truth"] = False
    return segment_display_geometry


def _annotate_segment_display_geometry(
    segment_display_geometry: dict[str, Any],
    *,
    resume_segment_report: dict[str, Any],
) -> dict[str, Any]:
    resume_by_id = {
        item["segment_candidate_id"]: item
        for item in resume_segment_report.get("segments", [])
    }
    for segment in segment_display_geometry.get("segments", []):
        resume = resume_by_id.get(segment.get("segment_candidate_id"))
        if not resume:
            continue
        segment["resume_segment"] = True
        segment["resume_gap_count"] = resume["resume_gap_count"]
        segment["max_gap_m"] = resume["max_gap_m"]
        segment["resume_gaps"] = resume["gaps"]
    segment_display_geometry["resume_segment_count"] = resume_segment_report[
        "resume_segment_count"
    ]
    segment_display_geometry["resume_segment_report_ref"] = "outputs/resume_segments.json"
    return segment_display_geometry


def _build_rest_area_candidate_report(
    *,
    project_id: str,
    primary_gpx: Path,
    filtered_route: GpxRoute,
    primary_artifact_id: str,
    gpx_speed_filter: dict[str, Any],
) -> dict[str, Any]:
    source_route = load_gpx_route(primary_gpx)
    removed_indices = {
        item["source_index"] for item in gpx_speed_filter.get("removed_points", [])
    }
    exempted_indices = {
        item["source_index"] for item in gpx_speed_filter.get("exempted_points", [])
    }
    candidates: list[dict[str, Any]] = []
    index = 0
    while index < len(source_route.points):
        end = _rest_area_cluster_end(source_route.points, index)
        if end is None:
            index += 1
            continue
        cluster_points = source_route.points[index:end]
        candidate = _rest_area_candidate_record(
            project_id=project_id,
            sequence=len(candidates) + 1,
            cluster_points=cluster_points,
            source_start_index=index,
            source_end_index=end - 1,
            filtered_route=filtered_route,
            primary_artifact_id=primary_artifact_id,
            removed_indices=removed_indices,
            exempted_indices=exempted_indices,
        )
        if candidate is not None:
            candidates.append(candidate)
            index = end
        else:
            index += 1
    return {
        "artifact_kind": "pretrip_rest_area_candidates",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "source_artifact_id": primary_artifact_id,
        "source_gpx": primary_gpx.as_posix(),
        "rest_area_candidate_count": len(candidates),
        "rest_area_checkpoint_count": 0,
        "policy": {
            "max_speed_m_per_min": REST_AREA_MAX_SPEED_M_PER_MIN,
            "cluster_radius_m": REST_AREA_CLUSTER_RADIUS_M,
            "min_duration_seconds": REST_AREA_MIN_DURATION_SECONDS,
            "min_source_point_count": REST_AREA_MIN_SOURCE_POINT_COUNT,
        },
        "candidates": candidates,
        "boundary": {
            "candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "raw_gpx_embedded": False,
        },
        "notes": [
            "Rest area / camp area candidates are derived from dense low-speed primary GPX clusters.",
            "They preserve planning explanation after GPX detail compression; human review is still required.",
        ],
    }


def _rest_area_cluster_end(points: list[Any], start_index: int) -> int | None:
    start = points[start_index]
    end = start_index + 1
    while end < len(points):
        point = points[end]
        if haversine_m(start.lat, start.lon, point.lat, point.lon) > REST_AREA_CLUSTER_RADIUS_M:
            break
        end += 1
    if end - start_index < REST_AREA_MIN_SOURCE_POINT_COUNT:
        return None
    return end


def _rest_area_candidate_record(
    *,
    project_id: str,
    sequence: int,
    cluster_points: list[Any],
    source_start_index: int,
    source_end_index: int,
    filtered_route: GpxRoute,
    primary_artifact_id: str,
    removed_indices: set[int],
    exempted_indices: set[int],
) -> dict[str, Any] | None:
    start_time = _parse_route_time(cluster_points[0].timestamp)
    end_time = _parse_route_time(cluster_points[-1].timestamp)
    if start_time is None or end_time is None:
        return None
    duration_seconds = (end_time - start_time).total_seconds()
    if duration_seconds < REST_AREA_MIN_DURATION_SECONDS:
        return None
    lat = sum(point.lat for point in cluster_points) / len(cluster_points)
    lon = sum(point.lon for point in cluster_points) / len(cluster_points)
    displacement_m = haversine_m(
        cluster_points[0].lat,
        cluster_points[0].lon,
        cluster_points[-1].lat,
        cluster_points[-1].lon,
    )
    speed_m_per_min = displacement_m / (duration_seconds / 60.0)
    if speed_m_per_min > REST_AREA_MAX_SPEED_M_PER_MIN:
        return None
    max_radius_m = max(
        haversine_m(lat, lon, point.lat, point.lon) for point in cluster_points
    )
    route_point_index, route_distance_m = _nearest_route_point_index(
        filtered_route,
        lat=lat,
        lon=lon,
    )
    candidate_id = f"rest_area.{project_id}.{sequence:03d}"
    checkpoint_candidate_id = f"cp.rest_area.{sequence:03d}"
    source_indices = set(range(source_start_index, source_end_index + 1))
    return {
        "candidate_id": candidate_id,
        "checkpoint_candidate_id": checkpoint_candidate_id,
        "label": f"Rest area / camp area {sequence:03d}",
        "checkpoint_type": "rest_area",
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "route_point_index": route_point_index,
        "distance_to_filtered_route_m": round(route_distance_m, 3),
        "source_point_start_index": source_start_index,
        "source_point_end_index": source_end_index,
        "source_point_count": len(cluster_points),
        "started_at": cluster_points[0].timestamp,
        "ended_at": cluster_points[-1].timestamp,
        "duration_seconds": round(duration_seconds, 3),
        "mean_speed_m_per_min": round(speed_m_per_min, 3),
        "cluster_radius_m": round(max_radius_m, 3),
        "speed_filter_removed_point_count": len(source_indices & removed_indices),
        "speed_filter_exempted_point_count": len(source_indices & exempted_indices),
        "source_refs": [primary_artifact_id],
        "review_state": "needs_review",
        "confidence": "medium",
    }


def _merge_rest_area_checkpoints(
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    *,
    rest_area_report: dict[str, Any],
    primary_gpx: Path,
    primary_artifact_id: str,
) -> list[PreTripCheckpointCandidate]:
    occupied_indices = {
        candidate.route_point_index
        for candidate in checkpoint_candidates
        if candidate.route_point_index is not None
    }
    rest_checkpoints: list[PreTripCheckpointCandidate] = []
    provenance = PreTripProvenance(
        source_ref=primary_artifact_id,
        source_kind=PreTripArtifactKind.GPX,
        uri=primary_gpx.as_posix(),
        method="pretrip_import.rest_area_cluster_analysis",
        notes=(
            "Derived from low-speed dense GPX source clusters; candidate-only "
            "rest/camp area evidence."
        ),
    )
    for candidate in rest_area_report.get("candidates", []):
        route_point_index = candidate.get("route_point_index")
        if route_point_index in occupied_indices:
            continue
        occupied_indices.add(route_point_index)
        rest_checkpoints.append(
            PreTripCheckpointCandidate(
                candidate_id=candidate["checkpoint_candidate_id"],
                label=candidate["label"],
                source_refs=[
                    primary_artifact_id,
                    "outputs/rest_area_candidates.json",
                ],
                provenance=[provenance],
                review_state=CandidateReviewState.NEEDS_REVIEW,
                confidence="medium",
                notes=(
                    "Rest area / camp area candidate from low-speed dense GPX "
                    f"cluster: {candidate['source_point_count']} source points over "
                    f"{round(candidate['duration_seconds'] / 60.0, 1)} min at "
                    f"{candidate['mean_speed_m_per_min']} m/min."
                ),
                lat=candidate["lat"],
                lon=candidate["lon"],
                route_point_index=route_point_index,
                checkpoint_type="rest_area",
                arrival_radius_m=max(30.0, candidate["cluster_radius_m"]),
                source_attribution=[
                    {
                        "source_kind": "rest_area_cluster",
                        "source_ref": "outputs/rest_area_candidates.json",
                        "source_candidate_id": candidate["candidate_id"],
                        "method": "pretrip_import.rest_area_cluster_analysis",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
            )
        )
    return sorted(
        [*checkpoint_candidates, *rest_checkpoints],
        key=lambda candidate: (
            candidate.route_point_index
            if candidate.route_point_index is not None
            else 10**12
        ),
    )


def _mark_rest_area_checkpoint_insertions(
    rest_area_report: dict[str, Any],
    *,
    checkpoint_candidates: list[PreTripCheckpointCandidate],
) -> None:
    checkpoint_ids = {candidate.candidate_id for candidate in checkpoint_candidates}
    inserted_count = 0
    for candidate in rest_area_report.get("candidates", []):
        inserted = candidate["checkpoint_candidate_id"] in checkpoint_ids
        candidate["checkpoint_inserted"] = inserted
        if inserted:
            inserted_count += 1
    rest_area_report["rest_area_checkpoint_count"] = inserted_count


def _nearest_route_point_index(
    route: GpxRoute,
    *,
    lat: float,
    lon: float,
) -> tuple[int, float]:
    best_index = 0
    best_distance = float("inf")
    for index, point in enumerate(route.points):
        distance = haversine_m(lat, lon, point.lat, point.lon)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index, best_distance


def _parse_route_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_import_segment_dtm_coverage(
    *,
    project_root: Path,
    package: PreTripPackage,
) -> Any | None:
    if package.dtm_coverage_summary is not None:
        return summarize_segment_terrain_metadata(
            segment_candidates=package.segment_candidates,
            dtm_coverage_summary=package.dtm_coverage_summary,
            summary_id=f"terrain_summary.{package.project_id}.imported_route",
        )
    dtm_coverage_path = project_root / "normalized" / "terrain" / "dtm_coverage_summary.json"
    if not dtm_coverage_path.exists():
        return None
    inherited_dtm_coverage = json.loads(dtm_coverage_path.read_text(encoding="utf-8"))
    if not inherited_dtm_coverage:
        return None
    return summarize_segment_terrain_metadata(
        segment_candidates=package.segment_candidates,
        dtm_coverage_summary=DtmCoverageSummary.model_validate(inherited_dtm_coverage),
        summary_id=f"terrain_summary.{package.project_id}.imported_route",
    )


def _build_dtm_coverage_from_material(
    *,
    request: PretripImportRequest,
    route_summary: Any,
    primary_artifact_id: str,
) -> DtmCoverageSummary | None:
    dtm_dirs = _dtm_source_dirs(request)
    if not dtm_dirs:
        return None
    return scan_dtm_coverage(
        route_summary=route_summary,
        source_dirs=dtm_dirs,
        summary_id=f"dtm_coverage.{request.project_id}.material_root",
    ).model_copy(update={"route_artifact_id": primary_artifact_id})


def _material_root_for_request(request: PretripImportRequest) -> Path | None:
    if request.material_root is not None:
        return request.material_root.expanduser()
    env_value = os.environ.get("SCOUT_PRETRIP_MATERIAL_ROOT")
    if env_value:
        return Path(env_value).expanduser()
    default = Path("/data/scout/materials/pretrip") / request.project_id
    return default if default.exists() else None


def _material_manifest(request: PretripImportRequest) -> dict[str, Any]:
    material_root = _material_root_for_request(request)
    if material_root is None:
        return {}
    manifest_path = material_root / "material_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _dtm_source_dirs(request: PretripImportRequest) -> list[Path]:
    manifest = _material_manifest(request)
    manifest_dirs = [
        Path(value).expanduser()
        for value in manifest.get("sources", {}).get("dtm_dirs", [])
        if Path(value).expanduser().exists()
    ]
    explicit_dirs = [
        path.expanduser()
        for path in request.dtm_dirs
        if path.expanduser().exists()
    ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in [*manifest_dirs, *explicit_dirs]:
        key = path.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _resolve_mcp_named_point_evidence(request: PretripImportRequest) -> Path | None:
    if request.mcp_named_point_evidence is not None:
        return request.mcp_named_point_evidence.expanduser().resolve()
    material_root = _material_root_for_request(request)
    if material_root is None:
        return None
    manifest = _material_manifest(request)
    manifest_source = manifest.get("sources", {}).get("mcp_named_point_evidence")
    candidates: list[Path] = []
    if isinstance(manifest_source, str):
        candidates.append(Path(manifest_source).expanduser())
    candidates.extend(
        [
            material_root / "sources" / "mcp" / "named_point_evidence.json",
            material_root / "mcp" / "named_point_evidence.json",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _mcp_output_refs() -> dict[str, str]:
    return {
        "mcp_named_point_evidence_ref": "outputs/mcp/named_point_evidence.json",
        "mcp_retrieval_plan_ref": (
            f"outputs/mcp/{DEFAULT_RETRIEVAL_PLAN_OUTPUT_NAME}"
        ),
        "mcp_ocr_labels_ref": f"outputs/mcp/{DEFAULT_OCR_LABEL_OUTPUT_NAME}",
        "mcp_candidates_ref": f"outputs/mcp/{DEFAULT_MCP_OUTPUT_NAME}",
        "mcp_cp_support_reconciliation_ref": (
            f"outputs/mcp/{DEFAULT_CP_SUPPORT_RECONCILIATION_OUTPUT_NAME}"
        ),
    }


def _build_mcp_import_artifacts(
    *,
    request: PretripImportRequest,
    project_root: Path,
    output_refs: dict[str, str],
    route_name: str,
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    import_timestamp: str,
) -> dict[str, Any] | None:
    evidence_path = _resolve_mcp_named_point_evidence(request)
    if evidence_path is None:
        return None

    evidence_set = load_named_point_evidence(evidence_path)
    if evidence_set.project_id != request.project_id:
        raise ValueError(
            "MCP named-point evidence project_id does not match import project_id: "
            f"{evidence_set.project_id} != {request.project_id}"
        )

    mcp_refs = _mcp_output_refs()
    output_refs.update(mcp_refs)
    checkpoint_ref = output_refs["checkpoint_candidates_ref"]
    write_json(
        project_root / checkpoint_ref,
        [candidate.model_dump(mode="json") for candidate in checkpoint_candidates],
    )
    _write_mcp_project_stub(
        project_root=project_root,
        project_id=request.project_id,
        output_refs=output_refs,
    )

    mcp_source_refs = (mcp_refs["mcp_named_point_evidence_ref"],)
    evidence_output_path = project_root / mcp_refs["mcp_named_point_evidence_ref"]
    evidence_output_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_output_path.write_text(evidence_set.to_json(), encoding="utf-8")

    retrieval_plan = build_fixture_backed_retrieval_plan(
        evidence_set,
        route_name=route_name,
        generated_at=import_timestamp,
    )
    write_retrieval_plan(
        retrieval_plan,
        project_root / mcp_refs["mcp_retrieval_plan_ref"],
    )
    ocr_labels = normalize_ocr_labels_from_evidence(
        evidence_set,
        source_refs=mcp_source_refs,
    )
    write_ocr_label_set(
        ocr_labels,
        project_root / mcp_refs["mcp_ocr_labels_ref"],
    )
    candidate_set = synthesize_mcp_candidates(
        evidence_set,
        project_root=project_root,
        source_refs=mcp_source_refs,
    )
    write_mcp_candidate_set(
        candidate_set,
        project_root / mcp_refs["mcp_candidates_ref"],
    )
    cp_support = build_cp_support_reconciliation(
        candidate_set,
        source_candidate_set_ref=mcp_refs["mcp_candidates_ref"],
    )
    write_cp_support_reconciliation(
        cp_support,
        project_root / mcp_refs["mcp_cp_support_reconciliation_ref"],
    )
    _write_mcp_project_stub(
        project_root=project_root,
        project_id=request.project_id,
        output_refs=output_refs,
    )

    return {
        "enabled": True,
        "source_path": evidence_path.as_posix(),
        "source_sha256": sha256_file(evidence_path),
        "refs": mcp_refs,
        "counts": {
            "mcp_candidate_count": candidate_set.mcp_candidate_count,
            "mcp_suppressed_point_count": candidate_set.suppressed_point_count,
            "mcp_dense_checkpoint_count": candidate_set.dense_checkpoint_count,
            "mcp_retrieval_query_count": retrieval_plan.query_count,
            "mcp_ocr_label_count": ocr_labels.label_count,
            "mcp_cp_support_supported_count": cp_support.supported_count,
            "mcp_cp_support_suggested_insertion_count": (
                cp_support.suggested_insertion_count
            ),
        },
        "boundary": {
            "pretrip_candidate_evidence_only": True,
            "fixture_backed": True,
            "live_network_performed": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "compile_allowed": False,
        },
    }


def _write_mcp_project_stub(
    *,
    project_root: Path,
    project_id: str,
    output_refs: dict[str, str],
) -> None:
    project_path = project_root / "project.json"
    payload: dict[str, Any] = {}
    if project_path.exists():
        try:
            existing = json.loads(project_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
        except json.JSONDecodeError:
            payload = {}
    payload.update(
        {
            "project_id": project_id,
            "checkpoint_candidates_ref": output_refs["checkpoint_candidates_ref"],
        }
    )
    payload.update(
        {
            key: value
            for key, value in output_refs.items()
            if key.startswith("mcp_") and key.endswith("_ref")
        }
    )
    write_json(project_path, payload)


def _build_default_retreat_routes(
    *,
    request: PretripImportRequest,
    route_summary: dict[str, Any],
    checkpoint_candidates: list[PreTripCheckpointCandidate],
    primary_artifact_id: str,
    primary_gpx: Path,
) -> list[PreTripRetreatRouteCandidate]:
    if not checkpoint_candidates:
        return []
    start = checkpoint_candidates[0]
    finish = checkpoint_candidates[-1]
    return [
        PreTripRetreatRouteCandidate(
            candidate_id=f"retreat.{request.project_id}.return_to_entry",
            label="Return to entry via reversed golden route",
            source_refs=[primary_artifact_id],
            provenance=[
                PreTripProvenance(
                    source_ref=primary_artifact_id,
                    source_kind=PreTripArtifactKind.GPX,
                    uri=primary_gpx.resolve().as_posix(),
                    method="pretrip_import.default_return_to_entry_retreat",
                    notes=(
                        "Generated from the selected golden route as a candidate "
                        "return-to-entry retreat assumption; human review remains required."
                    ),
                )
            ],
            review_state=CandidateReviewState.NEEDS_REVIEW,
            confidence="medium",
            stale_risk="medium",
            notes=(
                "Candidate-only retreat route generated by reversing the selected "
                "golden route. It is not a field-verified evacuation route."
            ),
            retreat_type="return_to_entry",
            entry_checkpoint_candidate_id=start.candidate_id,
            trigger_checkpoint_candidate_id=finish.candidate_id,
            route_point_start_index=start.route_point_index,
            route_point_end_index=finish.route_point_index,
            reversed_from_primary_route=True,
            distance_m=float(route_summary.get("distance_m", 0.0)),
            expected_use="both",
            human_review_required=True,
        )
    ]


def _build_weather_daylight_placeholder(
    *,
    request: PretripImportRequest,
    route_summary: dict[str, Any],
) -> PreTripWeatherDaylightEvidence:
    started_at = str(route_summary.get("started_at") or "")
    ended_at = str(route_summary.get("ended_at") or "")
    date = (started_at[:10] if len(started_at) >= 10 else _utc_now()[:10])
    window_start = started_at or f"{date}T00:00:00+08:00"
    window_end = ended_at or f"{date}T23:59:59+08:00"
    route_ref = "normalized/routes/route_summary.json"
    bbox = route_summary.get("bbox_wgs84")
    return PreTripWeatherDaylightEvidence(
        evidence_id=f"weather_daylight.{request.project_id}.{date}.imported_placeholder",
        project_id=request.project_id,
        date=date,
        timezone="Asia/Taipei",
        location_name=f"{request.project_id} route corridor",
        route_ref=route_ref,
        bbox_wgs84=bbox,
        daylight=DaylightEvidenceWindow(
            date=date,
            timezone="Asia/Taipei",
            notes=(
                "Importer generated a route/date placeholder only; sunrise, "
                "sunset, and twilight require human review or explicit source input."
            ),
        ),
        weather_window=WeatherWindowSummary(
            window_start=window_start,
            window_end=window_end,
            summary="Weather not evaluated; placeholder generated during local GPX import.",
            hazard_notes=[
                "No external weather or daylight API was called.",
                "Human review is required before departure-gate use.",
            ],
            notes="Candidate-only local placeholder for map/layer preparation completeness.",
        ),
        threshold_policy=WeatherDaylightThresholdPolicy(),
        source_refs=[route_ref, "cwa.weather_warning_thresholds"],
        source_details=[
            WeatherDaylightSourceRef(
                source_ref=route_ref,
                title="Imported golden route summary",
                uri=route_ref,
                notes="Route/date/bbox context only; not authoritative weather evidence.",
            )
        ],
        validation=WeatherDaylightValidation(
            notes=[
                "Generated by standalone importer to keep the planning evidence surface explicit.",
                "Do not use as authoritative weather or daylight truth.",
            ]
        ),
        human_review_required=True,
        authoritative_weather_computed=False,
        external_api_calls_made=False,
        notes=[
            "Candidate-only fixture generated without network calls.",
            "This artifact exists so map preparation can render a source-backed warning instead of a missing layer.",
        ],
    )


def _rebuild_review_queue_if_possible(project_root: Path) -> Any | None:
    try:
        return build_chilai_review_queue_manifest(project_root)
    except (FileNotFoundError, KeyError, ValueError):
        return _build_import_review_queue_manifest(project_root)


def _build_import_review_queue_manifest(project_root: Path) -> PreTripReviewQueueManifest:
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    items: list[ReviewQueueItem] = []
    source_refs: list[str] = []

    route_note_ref = project.get("route_note_candidates_ref")
    if route_note_ref and (project_root / route_note_ref).exists():
        source_refs.append(route_note_ref)
        route_notes = json.loads((project_root / route_note_ref).read_text(encoding="utf-8"))
        for candidate in route_notes.get("candidates", []):
            if candidate.get("potential_ln_signal") is not True:
                continue
            category = str(candidate.get("note_category", "uncategorized_note"))
            severity: Literal["review", "warning", "blocker"] = (
                "warning" if category == "hazard_hint" else "review"
            )
            candidate_id = str(candidate["candidate_id"])
            items.append(
                ReviewQueueItem(
                    item_id=f"review_queue.{project['project_id']}.route_note.{candidate_id}",
                    category=ReviewQueueCategory.ROUTE_NOTE,
                    source_ref_key="route_note_candidates_ref",
                    source_ref=route_note_ref,
                    source_artifact_kind=route_notes.get(
                        "artifact_kind",
                        "pretrip_route_note_candidates",
                    ),
                    candidate_ref=candidate_id,
                    severity=severity,
                    title=f"Route note Ln proposal review: {category}",
                    summary=str(candidate.get("normalized_note", "")),
                    review_focus=[
                        "route_note_interpretation",
                        "ln_warning_candidate",
                        "accept_ignore_or_field_verify",
                    ],
                    evidence_summary={
                        "note_category": category,
                        "potential_ln_signal": candidate.get("potential_ln_signal"),
                        "requires_human_review": candidate.get(
                            "requires_human_review"
                        ),
                        "candidate_only": candidate.get("candidate_only"),
                        "runtime_safety_truth": candidate.get("runtime_safety_truth"),
                        "source_ref_count": len(candidate.get("source_refs", [])),
                    },
                )
            )

    segment_policy_ref = project.get("segment_policy_candidates_ref")
    if segment_policy_ref and (project_root / segment_policy_ref).exists():
        source_refs.append(segment_policy_ref)
        segment_policy = json.loads(
            (project_root / segment_policy_ref).read_text(encoding="utf-8")
        )
        for candidate in segment_policy.get("candidates", []):
            if candidate.get("human_review_required") is not True:
                continue
            candidate_id = str(candidate["candidate_id"])
            requirement = candidate.get("requirement", {})
            items.append(
                ReviewQueueItem(
                    item_id=f"review_queue.{project['project_id']}.segment_policy.{candidate_id}",
                    category=ReviewQueueCategory.SEGMENT_POLICY,
                    source_ref_key="segment_policy_candidates_ref",
                    source_ref=segment_policy_ref,
                    source_artifact_kind=segment_policy.get(
                        "artifact_kind",
                        "segment_policy_candidates",
                    ),
                    candidate_ref=candidate_id,
                    severity="review",
                    title=f"Segment policy review: {candidate.get('segment_candidate_id', candidate_id)}",
                    summary=str(candidate.get("notes", "Human review required.")),
                    review_focus=[
                        name
                        for name, enabled in [
                            (
                                "daylight_required",
                                requirement.get("requires_daylight"),
                            ),
                            (
                                "water_unavailable",
                                requirement.get("water_available") is False,
                            ),
                            (
                                "camp_unavailable",
                                requirement.get("camp_available") is False,
                            ),
                            (
                                "retreat_unavailable",
                                requirement.get("retreat_available") is False,
                            ),
                            (
                                "signal_unexpected",
                                requirement.get("signal_expected") is False,
                            ),
                        ]
                        if enabled
                    ],
                    evidence_summary={
                        "segment_candidate_id": candidate.get("segment_candidate_id"),
                        "review_state": candidate.get("review_state"),
                        "candidate_only": candidate.get("candidate_only"),
                        "runtime_safety_truth": False,
                    },
                )
            )

    items.sort(key=lambda item: (item.category.value, item.item_id))
    category_counts = Counter(item.category.value for item in items)
    return PreTripReviewQueueManifest(
        manifest_id=f"review_queue.{project['project_id']}.reimported.v0",
        project_id=project["project_id"],
        source_refs=source_refs,
        items=items,
        counts=ReviewQueueCounts(
            item_count=len(items),
            warning_count=sum(1 for item in items if item.severity == "warning"),
            blocker_count=sum(1 for item in items if item.severity == "blocker"),
            review_count=sum(1 for item in items if item.severity == "review"),
            source_ref_count=len(source_refs),
            category_counts=dict(sorted(category_counts.items())),
        ),
        boundary=ReviewQueueBoundary(
            notes=[
                "Importer fallback review queue for rebuilt local workspaces.",
                "Queue records candidate pointers only and stores no decisions.",
                "No package, MissionGraph, Phase 1 runtime, or Phase 2 Brain mutation is performed.",
            ],
        ),
        notes=[
            "Generated because the full fixture-derived review queue could not be rebuilt from this minimal import workspace.",
            "Route-note and segment-policy candidates remain review-gated planning evidence.",
        ],
    )


def _rebuild_brain_seed_if_possible(
    *,
    project_root: Path,
    mission_id: str,
) -> Any | None:
    try:
        return export_chilai_pretrip_brain_seed(
            project_root,
            reviewed=True,
            mission_id=mission_id,
        )
    except (FileNotFoundError, KeyError, ValueError):
        return None


def _rebuild_runtime_handoff_metadata_if_possible(project_root: Path) -> Any | None:
    try:
        from pretrip_runtime_handoff_metadata import build_chilai_runtime_handoff_metadata

        return build_chilai_runtime_handoff_metadata(project_root)
    except (FileNotFoundError, KeyError, ValueError):
        return None


def _build_map_context(*, project_id: str, checkpoint_candidates: list[Any]) -> dict[str, Any]:
    coordinates = [
        [round(candidate.lon, 7), round(candidate.lat, 7)]
        for candidate in checkpoint_candidates
    ]
    if len(coordinates) < 2:
        raise ValueError("At least two checkpoint candidates are required for map context")

    return {
        "type": "FeatureCollection",
        "properties": {
            "source": "pretrip_standalone_importer",
            "source_version": IMPORTER_VERSION,
            "confidence": 0.66,
            "known_staleness_risk": "medium",
            "notes": (
                "Map context（地圖脈絡）is generated from imported GPX checkpoint "
                "coordinates and is planning evidence only."
            ),
        },
        "features": [
            {
                "type": "Feature",
                "id": f"{project_id}.imported_golden_route_cp_corridor",
                "properties": {
                    "feature_type": "approved_corridor",
                    "name": "Imported golden route CP corridor candidate",
                    "route_level": "planning_candidate",
                    "corridor_half_width_m": 30.0,
                    "source": "pretrip_standalone_importer",
                    "source_version": IMPORTER_VERSION,
                    "confidence": 0.66,
                    "known_staleness_risk": "medium",
                },
                "geometry": {"type": "LineString", "coordinates": coordinates},
            },
            _poi_feature(project_id, "start", "Imported golden route start candidate", coordinates[0]),
            _poi_feature(project_id, "finish", "Imported golden route finish candidate", coordinates[-1]),
        ],
    }


def _poi_feature(project_id: str, role: str, name: str, coordinate: list[float]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": f"{project_id}.imported_golden_route_{role}",
        "properties": {
            "feature_type": "poi",
            "name": name,
            "poi_type": "trailhead",
            "source": "pretrip_standalone_importer",
            "source_version": IMPORTER_VERSION,
            "confidence": 0.66,
            "known_staleness_risk": "medium",
        },
        "geometry": {"type": "Point", "coordinates": coordinate},
    }


def _build_import_manifest(
    *,
    request: PretripImportRequest,
    project_root: Path,
    primary_gpx: Path,
    reference_paths: list[Path],
    import_timestamp: str,
    output_refs: dict[str, str],
    route_summary: dict[str, Any],
    checkpoint_count: int,
    segment_count: int,
    rest_area_report: dict[str, Any],
    resume_segment_report: dict[str, Any],
    gis_perception: dict[str, Any],
    gis_perception_ai_judgements: dict[str, Any],
    route_note_candidates: dict[str, Any],
    route_note_ln_proposals: dict[str, Any],
    route_note_review_options: dict[str, Any],
    source_inbox_manifest: dict[str, Any],
    historical_gpx_source_index: dict[str, Any],
    gpx_speed_filter: dict[str, Any],
) -> dict[str, Any]:
    filter_summary = _gpx_filter_summary(gpx_speed_filter, output_refs=output_refs)
    imagery_scope = _build_imagery_acquisition_scope(route_summary)
    return {
        "artifact_kind": "pretrip_import_manifest",
        "schema_version": "0.1.0",
        "importer_version": IMPORTER_VERSION,
        "project_id": request.project_id,
        "profile": request.profile,
        "import_stage": request.import_stage,
        "imported_at": import_timestamp,
        "workspace_root": project_root.resolve().as_posix(),
        "network_policy": {
            "network_calls_allowed": False,
            "profile": request.profile,
            "notes": "pi-offline（Pi 離線模式）and mac-workstation import local files only in this slice.",
        },
        "inputs": {
            "source_inbox": {
                "manifest_ref": output_refs["source_inbox_manifest_ref"],
                "source_file_count": source_inbox_manifest["source_file_count"],
                "raw_payloads_embedded": False,
            },
            "historical_gpx_source_index": {
                "source_ref": output_refs["historical_gpx_source_index_ref"],
                "source_file_count": historical_gpx_source_index["source_file_count"],
                "raw_payloads_embedded": False,
            },
            "golden_route_gpx": _source_record(
                primary_gpx,
                role=_golden_route_role(request),
            ),
            "reference_tracks": [
                _source_record(path, role="reference_track")
                for path in reference_paths
            ],
        },
        "outputs": output_refs,
        "gpx_speed_filter": filter_summary,
        "imagery_acquisition_scope": imagery_scope,
        "counts": {
            "source_file_count": 1 + len(reference_paths),
            "golden_route_count": 1,
            "reference_track_count": len(reference_paths),
            "gpx_speed_filter_original_point_count": gpx_speed_filter[
                "original_track_point_count"
            ],
            "gpx_speed_filter_filtered_point_count": gpx_speed_filter[
                "filtered_track_point_count"
            ],
            "gpx_speed_filter_removed_point_count": gpx_speed_filter[
                "removed_track_point_count"
            ],
            "gpx_speed_filter_exempted_point_count": gpx_speed_filter[
                "exempted_track_point_count"
            ],
            "resume_segment_count": resume_segment_report["resume_segment_count"],
            "rest_area_candidate_count": rest_area_report["rest_area_candidate_count"],
            "rest_area_checkpoint_count": rest_area_report["rest_area_checkpoint_count"],
            "checkpoint_candidate_count": checkpoint_count,
            "segment_candidate_count": segment_count,
            "route_note_candidate_count": route_note_candidates["counts"]["note_candidate_count"],
            "route_note_potential_ln_signal_count": route_note_candidates["counts"][
                "potential_ln_signal_count"
            ],
            "route_note_ln_proposal_count": route_note_ln_proposals["counts"]["proposal_count"],
            "route_note_ln_hint_coverage_proposal_count": route_note_ln_proposals[
                "counts"
            ]["hint_coverage_proposal_count"],
            "route_note_ln_warning_coverage_proposal_count": route_note_ln_proposals[
                "counts"
            ]["warning_coverage_proposal_count"],
            "route_note_review_option_count": route_note_review_options["counts"][
                "review_option_count"
            ],
            "gis_perception_ai_judgement_count": gis_perception_ai_judgements[
                "judgement_count"
            ],
            "gis_perception_checkpoint_candidate_count": gis_perception["counts"][
                "checkpoint_candidate_count"
            ],
            "route_point_count": route_summary["point_count"],
        },
        "resume_segments": {
            "enabled": True,
            "max_reasonable_point_gap_m": resume_segment_report[
                "max_reasonable_point_gap_m"
            ],
            "resume_segment_count": resume_segment_report["resume_segment_count"],
            "report_ref": output_refs["resume_segment_report_ref"],
        },
        "rest_areas": {
            "enabled": True,
            "rest_area_candidate_count": rest_area_report["rest_area_candidate_count"],
            "rest_area_checkpoint_count": rest_area_report["rest_area_checkpoint_count"],
            "report_ref": output_refs["rest_area_candidates_ref"],
            "policy": rest_area_report["policy"],
        },
        "boss_point_synthesis": {
            "status": "pending_map_preparation",
            "trigger": "prepare_layers_with_risk",
            "required_refs": [
                "risk_ribbon_ref",
                "segment_display_geometry_ref",
                "mcp_candidates_ref",
                "route_note_candidates_ref",
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "review_gated": True,
        },
        "planning_semantics": _planning_semantics(request),
        "boundary": {
            "pretrip_candidate_evidence_only": True,
            "golden_route_is_reference_evidence": True,
            "actual_user_track_available": request.import_stage == "post_analysis",
            "actual_user_track_required_before_post_analysis": request.import_stage == "pretrip",
            "unwalked_route_sections_require_manual_waypoints": True,
            "unwalked_route_sections_require_danger_review": True,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "incident_store_mutation_allowed": False,
            "real_outbound_transport_allowed": False,
            "mission_graph_compiled": False,
            "raw_gpx_embedded_in_json": False,
            "gpx_speed_filter_applied": True,
        },
    }


def _attach_mcp_import_manifest(
    manifest: dict[str, Any],
    mcp_import_summary: dict[str, Any] | None,
) -> None:
    if mcp_import_summary is None:
        return
    manifest["inputs"]["mcp_named_point_evidence"] = {
        "source_path": mcp_import_summary["source_path"],
        "sha256": mcp_import_summary["source_sha256"],
        "role": "fixture_backed_named_point_evidence",
        "raw_payload_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    manifest["outputs"].update(mcp_import_summary["refs"])
    manifest["counts"].update(mcp_import_summary["counts"])
    manifest["mcp_synthesis"] = {
        "enabled": True,
        "source_ref": mcp_import_summary["refs"]["mcp_named_point_evidence_ref"],
        "candidate_ref": mcp_import_summary["refs"]["mcp_candidates_ref"],
        "retrieval_plan_ref": mcp_import_summary["refs"]["mcp_retrieval_plan_ref"],
        "ocr_labels_ref": mcp_import_summary["refs"]["mcp_ocr_labels_ref"],
        "cp_support_reconciliation_ref": mcp_import_summary["refs"][
            "mcp_cp_support_reconciliation_ref"
        ],
        "boundary": mcp_import_summary["boundary"],
    }


def _build_route_evidence_bundle(
    *,
    request: PretripImportRequest,
    project_root: Path,
    primary_artifact_id: str,
    primary_gpx: Path,
    reference_paths: list[Path],
    route_summary: dict[str, Any],
    output_refs: dict[str, str],
    gpx_speed_filter: dict[str, Any],
) -> dict[str, Any]:
    route_bbox = _route_bbox_list(route_summary)
    scope_bbox = _expand_bbox_list(route_bbox, 500.0)
    imagery_scope = _build_imagery_acquisition_scope(route_summary)
    return {
        "artifact_kind": "pretrip_historical_gpx_route_evidence_bundle",
        "schema_version": "historical_gpx_importer.v1",
        "project_id": request.project_id,
        "golden_route": {
            "source_id": primary_artifact_id,
            "source_path": primary_gpx.resolve().as_posix(),
            "sha256": sha256_file(primary_gpx),
            "role": _golden_route_role(request),
            "geometry_ref": output_refs["map_context_ref"],
            "filtered_geometry_ref": _project_ref(
                project_root,
                Path(gpx_speed_filter["primary"]["output_path"]),
            ),
            "route_summary_ref": output_refs["route_summary_ref"],
            "route_bbox_wgs84": route_bbox,
            "route_distance_m": route_summary["distance_m"],
        },
        "reference_tracks": [
            {
                "source_id": f"{primary_artifact_id}.reference.{index:03d}",
                "role": "reference_track",
                "source_path": path.resolve().as_posix(),
                "sha256": sha256_file(path),
                "geometry_ref": output_refs["reference_track_display_geometry_ref"],
                "filtered_geometry_ref": _project_ref(
                    project_root,
                    Path(gpx_speed_filter["references"][index - 1]["output_path"]),
                ),
                "freshness": {
                    "track_time_available": True,
                    "old_route_note_flag": False,
                },
            }
            for index, path in enumerate(reference_paths, start=1)
        ],
        "route_scope_for_map_preparation": {
            "bbox_wgs84": scope_bbox,
            "route_corridor_m": 500.0,
            "reference_track_corridor_m": 300.0,
            "corridor_policy": "bbox_fetch_then_along_track_filter",
        },
        "imagery_scope_for_map_preparation": imagery_scope,
        "note_candidate_refs": [
            output_refs["normalized_route_note_candidates_ref"],
            output_refs["route_note_candidates_ref"],
        ],
        "gpx_filter_refs": {
            "speed_filter_report_ref": output_refs["gpx_speed_filter_report_ref"],
            "resume_segment_report_ref": output_refs["resume_segment_report_ref"],
            "rest_area_candidates_ref": output_refs["rest_area_candidates_ref"],
        },
        "boundary": {
            "candidate_only": True,
            "actual_user_track_available": request.import_stage == "post_analysis",
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "safety_api_called": False,
            "runtime_safety_truth": False,
            "raw_gpx_embedded_in_json": False,
        },
    }


def _route_bbox_list(route_summary: dict[str, Any]) -> list[float]:
    bbox = route_summary["bbox_wgs84"]
    return [
        float(bbox["min_lon"]),
        float(bbox["min_lat"]),
        float(bbox["max_lon"]),
        float(bbox["max_lat"]),
    ]


def _build_imagery_acquisition_scope(route_summary: dict[str, Any]) -> dict[str, Any]:
    route_bbox = _route_bbox_list(route_summary)
    imagery_bbox = _scale_bbox_list(route_bbox, DEFAULT_IMAGERY_BBOX_SCALE_FACTOR)
    return {
        "artifact_kind": "pretrip_imagery_acquisition_scope",
        "schema_version": "scout_imagery_source_scope.v1",
        "source": "historical_gpx_importer",
        "source_route_bbox_wgs84": _bbox_list_to_dict(route_bbox),
        "bbox_wgs84": _bbox_list_to_dict(imagery_bbox),
        "scale_factor": DEFAULT_IMAGERY_BBOX_SCALE_FACTOR,
        "bbox_policy": "gpx_bbox_scaled_115_percent",
        "imagery_source_id": DEFAULT_IMAGERY_SOURCE_ID,
        "imagery_source_registry_id": DEFAULT_REGISTRY_ID,
        "tile_cache_policy": "scout_proxy_cache_first_explicit_remote_fetch",
        "runtime_safety_truth": False,
        "notes_zh": [
            "影像圖層取用範圍依 GPX bbox 中心放大到 115%。",
            "這是圖磚取用範圍，不是 Phase 1 runtime safety truth。",
        ],
    }


def _bbox_list_to_dict(bbox: list[float]) -> dict[str, float]:
    west, south, east, north = bbox
    return {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
    }


def _scale_bbox_list(bbox: list[float], scale_factor: float) -> list[float]:
    if scale_factor <= 0:
        raise ValueError("scale_factor must be positive")
    west, south, east, north = bbox
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    width = max(east - west, 1e-6)
    height = max(north - south, 1e-6)
    scaled_width = width * scale_factor
    scaled_height = height * scale_factor
    return [
        round(max(-180.0, center_lon - scaled_width / 2.0), 7),
        round(max(-90.0, center_lat - scaled_height / 2.0), 7),
        round(min(180.0, center_lon + scaled_width / 2.0), 7),
        round(min(90.0, center_lat + scaled_height / 2.0), 7),
    ]


def _expand_bbox_list(bbox: list[float], corridor_m: float) -> list[float]:
    west, south, east, north = bbox
    lat_delta = corridor_m / 111_320.0
    mean_lat = (south + north) / 2.0
    lon_scale = max(0.1, math.cos(math.radians(mean_lat)))
    lon_delta = corridor_m / (111_320.0 * lon_scale)
    return [
        round(west - lon_delta, 7),
        round(south - lat_delta, 7),
        round(east + lon_delta, 7),
        round(north + lat_delta, 7),
    ]


def _project_ref(project_root: Path, path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _admin_route_note_projection_summary(
    payload: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_candidates",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": payload["boundary"],
        "preview_candidates": [
            {
                "candidate_id": candidate["candidate_id"],
                "lat": candidate["lat"],
                "lon": candidate["lon"],
                "note_category": candidate["note_category"],
                "potential_ln_signal": candidate["potential_ln_signal"],
                "requires_human_review": candidate["requires_human_review"],
                "review_state": candidate.get("review_state", "needs_review"),
                "confidence": candidate.get("confidence", "unknown"),
                "stale_risk": candidate.get("stale_risk", "unknown"),
                "route_note_age_days": candidate.get("route_note_age_days"),
                "route_note_freshness": candidate.get(
                    "route_note_freshness",
                    "unknown",
                ),
                "stale_route_note": candidate.get("stale_route_note", False),
                "candidate_only": candidate.get("candidate_only", True),
                "runtime_safety_truth": candidate.get("runtime_safety_truth", False),
                "source_refs": candidate.get("source_refs", []),
                "source_attribution": candidate.get("source_attribution", []),
                "extractor_version": candidate.get("extractor_version"),
                "pydantic_ai_prompt_version": candidate.get(
                    "pydantic_ai_prompt_version",
                ),
                "model_output_sha256": candidate.get("model_output_sha256"),
                "model_output_summary": candidate.get("model_output_summary"),
                "normalized_note": candidate["normalized_note"],
            }
            for candidate in payload.get("candidates", [])[:12]
        ],
    }


def _admin_route_note_ln_projection_summary(
    payload: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_ln_proposals",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": payload["boundary"],
        "preview_proposals": [
            {
                "proposal_id": proposal["proposal_id"],
                "source_route_note_candidate_id": proposal[
                    "source_route_note_candidate_id"
                ],
                "proposal_kind": proposal["proposal_kind"],
                "proposed_coverage_label": proposal["proposed_coverage_label"],
                "human_review_required": proposal["human_review_required"],
                "review_state": proposal.get("review_state", "needs_review"),
                "confidence": proposal.get("confidence", "unknown"),
                "stale_risk": proposal.get("stale_risk", "unknown"),
                "candidate_only": proposal["candidate_only"],
                "runtime_safety_truth": proposal["runtime_safety_truth"],
                "source_refs": proposal.get("source_refs", []),
                "source_attribution": proposal.get("source_attribution", []),
                "extractor_version": proposal.get("extractor_version"),
                "pydantic_ai_prompt_version": proposal.get(
                    "pydantic_ai_prompt_version",
                ),
                "model_output_sha256": proposal.get("model_output_sha256"),
                "model_output_summary": proposal.get("model_output_summary"),
                "route_note_summary": proposal["route_note_summary"],
            }
            for proposal in payload.get("proposals", [])[:12]
        ],
    }


def _admin_route_note_review_options_projection_summary(
    payload: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_review_options",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": payload["boundary"],
        "preview_options": [
            {
                "option_id": option["option_id"],
                "source_proposal_id": option["source_proposal_id"],
                "allowed_admin_dispositions": option["allowed_admin_dispositions"],
                "selected_admin_disposition": option["selected_admin_disposition"],
                "decision_recorded": option["decision_recorded"],
                "review_state": option.get("review_state", "draft"),
                "confidence": option.get("confidence", "unknown"),
                "stale_risk": option.get("stale_risk", "unknown"),
                "candidate_only": option["candidate_only"],
                "runtime_safety_truth": option["runtime_safety_truth"],
                "draft_only": option["draft_only"],
                "source_refs": option.get("source_refs", []),
                "source_attribution": option.get("source_attribution", []),
                "extractor_version": option.get("extractor_version"),
                "pydantic_ai_prompt_version": option.get(
                    "pydantic_ai_prompt_version",
                ),
                "model_output_sha256": option.get("model_output_sha256"),
                "model_output_summary": option.get("model_output_summary"),
            }
            for option in payload.get("options", [])[:12]
        ],
    }


def _admin_mcp_projection_summary_from_project(
    project_root: Path,
    *,
    project_id: str,
) -> dict[str, Any] | None:
    project_path = project_root / "project.json"
    if not project_path.exists():
        return None
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    source_refs = {
        "named_point_evidence": project.get("mcp_named_point_evidence_ref"),
        "retrieval_plan": project.get("mcp_retrieval_plan_ref"),
        "ocr_labels": project.get("mcp_ocr_labels_ref"),
        "candidates": project.get("mcp_candidates_ref"),
        "cp_support_reconciliation": project.get("mcp_cp_support_reconciliation_ref"),
        "review_actions": project.get("mcp_review_log_ref"),
    }
    mcp_candidates = _load_optional_project_json_ref(
        project_root,
        source_refs["candidates"],
    )
    if not isinstance(mcp_candidates, dict):
        return None
    named_point_evidence = _load_optional_project_json_ref(
        project_root,
        source_refs["named_point_evidence"],
    )
    retrieval_plan = _load_optional_project_json_ref(
        project_root,
        source_refs["retrieval_plan"],
    )
    ocr_labels = _load_optional_project_json_ref(project_root, source_refs["ocr_labels"])
    cp_support = _load_optional_project_json_ref(
        project_root,
        source_refs["cp_support_reconciliation"],
    )
    review_log = _load_optional_project_json_ref(
        project_root,
        source_refs["review_actions"],
    )
    candidates = list(mcp_candidates.get("mcp_candidates", []) or [])
    review_actions = list((review_log or {}).get("actions", []) or [])
    retrieval = retrieval_plan or {}
    ocr = ocr_labels or {}
    cp_support_payload = cp_support or {}
    counts = {
        "mcp_candidate_count": mcp_candidates.get("mcp_candidate_count", len(candidates)),
        "dense_checkpoint_count": mcp_candidates.get("dense_checkpoint_count", 0),
        "suppressed_point_count": mcp_candidates.get("suppressed_point_count", 0),
        "retrieval_query_count": retrieval.get("query_count", 0),
        "accepted_evidence_page_count": (
            (named_point_evidence or {})
            .get("search_profile", {})
            .get("accepted_evidence_page_count", 0)
        ),
        "ocr_label_count": ocr.get("label_count", 0),
        "review_required_ocr_label_count": ocr.get("review_required_count", 0),
        "cp_support_supported_count": cp_support_payload.get("supported_count", 0),
        "cp_support_suggested_insertion_count": cp_support_payload.get(
            "suggested_insertion_count",
            0,
        ),
        "review_action_count": len(review_actions),
    }
    return {
        "source_id": f"mcp.{project_id}.v1",
        "source_path": source_refs["candidates"] or "outputs/mcp/mcp_candidates.json",
        "evidence_type": "pretrip_major_critical_point_candidates",
        "status": "candidate_only",
        "project_id": project_id,
        "counts": counts,
        "policy": mcp_candidates.get("mcp_policy", {}),
        "source_refs": source_refs,
        "retrieval": {
            "artifact_kind": retrieval.get("artifact_kind"),
            "planner_kind": retrieval.get("planner_kind"),
            "pydantic_ai_responsibility": retrieval.get(
                "pydantic_ai_responsibility"
            ),
            "truth_decision_allowed": retrieval.get("truth_decision_allowed", False),
            "fixture_backed": retrieval.get("fixture_backed", True),
            "live_network_performed": retrieval.get("live_network_performed", False),
            "required_source_families": retrieval.get("required_source_families", []),
            "attempted_source_families": retrieval.get("attempted_source_families", []),
            "fetch_summary_count": retrieval.get("fetch_summary_count", 0),
            "queries": retrieval.get("queries", [])[:12],
            "fetch_summaries": retrieval.get("fetch_summaries", [])[:12],
        },
        "ocr": {
            "artifact_kind": ocr.get("artifact_kind"),
            "label_count": ocr.get("label_count", 0),
            "review_required_count": ocr.get("review_required_count", 0),
            "labels": ocr.get("labels", [])[:12],
        },
        "cp_support_reconciliation": {
            "artifact_kind": cp_support_payload.get("artifact_kind"),
            "support_radius_m": cp_support_payload.get("support_radius_m"),
            "supported_count": cp_support_payload.get("supported_count", 0),
            "suggested_insertion_count": cp_support_payload.get(
                "suggested_insertion_count",
                0,
            ),
            "rows": cp_support_payload.get("rows", [])[:12],
        },
        "preview_candidates": [
            {
                "mcp_id": candidate.get("mcp_id"),
                "label": candidate.get("label"),
                "point_class": candidate.get("point_class", []),
                "lat": candidate.get("lat"),
                "lon": candidate.get("lon"),
                "confidence": candidate.get("confidence"),
                "stale_risk": candidate.get("stale_risk"),
                "review_state": candidate.get("review_state"),
                "candidate_only": candidate.get("candidate_only", True),
                "runtime_safety_truth": candidate.get("runtime_safety_truth", False),
                "source_refs": candidate.get("source_refs", []),
                "source_attribution": candidate.get("source_attribution", []),
                "nearest_scout_cp": candidate.get("nearest_scout_cp"),
                "suggested_cp_insertion": candidate.get("suggested_cp_insertion"),
                "nearby_points_suppressed_by_spacing": candidate.get(
                    "nearby_points_suppressed_by_spacing",
                    [],
                ),
            }
            for candidate in candidates[:12]
        ],
        "boundary": mcp_candidates.get("boundary", {}),
    }


def _load_optional_project_json_ref(
    project_root: Path,
    ref: Any,
) -> dict[str, Any] | None:
    if not isinstance(ref, str) or not ref:
        return None
    path = project_root / ref
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _admin_departure_bundle_projection_summary_from_project(
    project_root: Path,
) -> dict[str, Any] | None:
    project = _load_project_payload(project_root)
    if project is None:
        return None
    ref = project.get("departure_bundle_manifest_ref")
    payload = _load_optional_project_json_ref(project_root, ref)
    if not isinstance(payload, dict):
        return None
    return {
        "source_id": payload.get("bundle_id", "departure_bundle.unknown"),
        "source_path": ref,
        "evidence_type": "pretrip_departure_bundle_manifest",
        "status": payload.get("status"),
        "counts": payload.get("counts", {}),
        "boundary": payload.get("boundary", {}),
        "package": payload.get("package", {}),
        "route_ref_count": len(payload.get("route_refs", []) or []),
        "terrain_ref_count": len(payload.get("terrain_refs", []) or []),
        "audit_ref_count": len(payload.get("audit_refs", []) or []),
        "required_refs_preview": payload.get("required_refs", [])[:24],
    }


def _admin_runtime_handoff_projection_summary_from_project(
    project_root: Path,
) -> dict[str, Any] | None:
    project = _load_project_payload(project_root)
    if project is None:
        return None
    ref = project.get("runtime_handoff_metadata_ref")
    payload = _load_optional_project_json_ref(project_root, ref)
    if not isinstance(payload, dict):
        return None
    return {
        "source_id": payload.get("manifest_id", "runtime_handoff_metadata.unknown"),
        "source_path": ref,
        "evidence_type": "pretrip_runtime_handoff_metadata",
        "status": payload.get("status"),
        "counts": payload.get("counts", {}),
        "boundary": payload.get("boundary", {}),
        "route_refs": payload.get("route_refs", []),
        "readiness_refs": payload.get("readiness_refs", []),
        "reviewed_package": payload.get("reviewed_package", {}),
    }


def _admin_export_handoff_projection_summaries(
    project_root: Path,
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    departure_bundle = _admin_departure_bundle_projection_summary_from_project(
        project_root
    )
    if departure_bundle is not None:
        summaries["departure_bundle"] = departure_bundle
    runtime_handoff = _admin_runtime_handoff_projection_summary_from_project(
        project_root
    )
    if runtime_handoff is not None:
        summaries["runtime_handoff"] = runtime_handoff
    return summaries


def _refresh_admin_projection_export_summaries(project_root: Path) -> None:
    project = _load_project_payload(project_root)
    if project is None:
        return
    admin_projection_ref = project.get("admin_projection_ref")
    if not isinstance(admin_projection_ref, str) or not admin_projection_ref:
        return
    admin_projection_path = project_root / admin_projection_ref
    if not admin_projection_path.exists():
        return
    try:
        projection = json.loads(admin_projection_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(projection, dict):
        return
    projection.update(_admin_export_handoff_projection_summaries(project_root))
    write_json(admin_projection_path, projection)


def _load_project_payload(project_root: Path) -> dict[str, Any] | None:
    project_path = project_root / "project.json"
    if not project_path.exists():
        return None
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return project if isinstance(project, dict) else None


def _build_admin_projection(
    *,
    request: PretripImportRequest,
    project_root: Path,
    route_summary: dict[str, Any],
    output_refs: dict[str, str],
    reference_track_count: int,
    checkpoint_count: int,
    segment_count: int,
    segment_display_geometry: dict[str, Any],
    rest_area_report: dict[str, Any],
    resume_segment_report: dict[str, Any],
    gis_perception: dict[str, Any],
    gis_perception_ai_judgements: dict[str, Any],
    route_note_candidates: dict[str, Any],
    route_note_ln_proposals: dict[str, Any],
    route_note_review_options: dict[str, Any],
    gpx_speed_filter: dict[str, Any],
) -> dict[str, Any]:
    filter_summary = _gpx_filter_summary(gpx_speed_filter, output_refs=output_refs)
    mcp_summary = _admin_mcp_projection_summary_from_project(
        project_root,
        project_id=request.project_id,
    )
    candidate_counts = {
        "checkpoint_candidate_count": checkpoint_count,
        "segment_candidate_count": segment_count,
        "reference_track_count": reference_track_count,
        "rest_area_candidate_count": rest_area_report["rest_area_candidate_count"],
        "rest_area_checkpoint_count": rest_area_report["rest_area_checkpoint_count"],
        "resume_segment_count": resume_segment_report["resume_segment_count"],
        "route_note_candidate_count": gis_perception["counts"][
            "gpx_route_note_candidate_count"
        ],
        "route_note_ln_proposal_count": gis_perception["counts"][
            "gpx_ln_proposal_count"
        ],
        "gis_perception_ai_judgement_count": gis_perception_ai_judgements[
            "judgement_count"
        ],
        "gis_perception_checkpoint_candidate_count": gis_perception["counts"][
            "checkpoint_candidate_count"
        ],
    }
    if mcp_summary is not None:
        candidate_counts.update(
            {
                "mcp_candidate_count": mcp_summary["counts"].get(
                    "mcp_candidate_count",
                    0,
                ),
                "mcp_suppressed_point_count": mcp_summary["counts"].get(
                    "suppressed_point_count",
                    0,
                ),
                "mcp_review_action_count": mcp_summary["counts"].get(
                    "review_action_count",
                    0,
                ),
            }
        )
    projection = {
        "artifact_kind": "pretrip_admin_surface_projection",
        "schema_version": "0.1.0",
        "project_id": request.project_id,
        "surface_targets": ["/admin", "/admin/pretrip", "/admin/debug"],
        "projection_only": True,
        "import_stage": request.import_stage,
        "route": {
            "route_role": _golden_route_role(request),
            "route_name": route_summary["route_name"],
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "bbox_wgs84": route_summary["bbox_wgs84"],
            "route_summary_ref": output_refs["route_summary_ref"],
            "map_context_ref": output_refs["map_context_ref"],
            "gpx_speed_filter": filter_summary,
            "display_geometry": _route_display_geometry_from_segment_display_geometry(
                project_id=request.project_id,
                segment_display_geometry=segment_display_geometry,
                source_path=output_refs["segment_display_geometry_ref"],
            ),
        },
        "candidate_counts": candidate_counts,
        "gis_perception": {
            "source_profile": gis_perception["source_profile"],
            "status": gis_perception["status"],
            "counts": gis_perception["counts"],
            "classifier": gis_perception["classifier"],
            "boundary": gis_perception["boundary"],
            "ai_judgements": {
                "artifact_kind": gis_perception_ai_judgements["artifact_kind"],
                "provider_kind": gis_perception_ai_judgements["provider_kind"],
                "model_name": gis_perception_ai_judgements["model_name"],
                "prompt_sha256": gis_perception_ai_judgements["prompt_sha256"],
                "input_count": gis_perception_ai_judgements["input_count"],
                "judgement_count": gis_perception_ai_judgements["judgement_count"],
                "source_ref_count": len(
                    gis_perception_ai_judgements.get("source_refs", [])
                ),
                "source_refs": gis_perception_ai_judgements.get("source_refs", []),
                "counts": gis_perception_ai_judgements.get("counts", {}),
                "boundary": gis_perception_ai_judgements.get("boundary", {}),
                "candidate_only": gis_perception_ai_judgements.get(
                    "boundary",
                    {},
                ).get("candidate_only", True),
                "raw_model_output_embedded": gis_perception_ai_judgements[
                    "raw_model_output_embedded"
                ],
                "live_model_call_performed": gis_perception_ai_judgements[
                    "live_model_call_performed"
                ],
                "network_calls_allowed": gis_perception_ai_judgements[
                    "network_calls_allowed"
                ],
            },
            "gis_perception_candidates_ref": output_refs["gis_perception_candidates_ref"],
            "gis_perception_ai_judgements_ref": output_refs[
                "gis_perception_ai_judgements_ref"
            ],
            "route_note_candidates_ref": output_refs["route_note_candidates_ref"],
            "route_note_ln_proposals_ref": output_refs["route_note_ln_proposals_ref"],
        },
        "route_notes": _admin_route_note_projection_summary(
            route_note_candidates,
            source_path=output_refs["route_note_candidates_ref"],
        ),
        "route_note_ln_proposals": _admin_route_note_ln_projection_summary(
            route_note_ln_proposals,
            source_path=output_refs["route_note_ln_proposals_ref"],
        ),
        "route_note_review_options": _admin_route_note_review_options_projection_summary(
            route_note_review_options,
            source_path=output_refs["route_note_review_options_ref"],
        ),
        "pretrip_surface": {
            "project_ref": "project.json",
            "package_ref": output_refs["package_ref"],
            "import_manifest_ref": output_refs["import_manifest_ref"],
            "resume_segment_report_ref": output_refs["resume_segment_report_ref"],
            "rest_area_candidates_ref": output_refs["rest_area_candidates_ref"],
        },
        "after_action_surface": {
            "after_action_style_projection": True,
            "completed_mission_replay": False,
            "incident_package_source": False,
            "pretrip_actual_user_track_available": request.import_stage == "post_analysis",
            "pretrip_golden_route_replacement_expected_after_return": (
                request.import_stage == "pretrip"
            ),
            "notes": (
                "/admin can inspect this imported route as map-first planning evidence, "
                "not as completed mission evidence."
            ),
        },
        "planning_semantics": _planning_semantics(request),
        "debug_surface": {
            "debug_projection_events_ref": output_refs["debug_projection_events_ref"],
            "file_runtime_debug_log_compatible": True,
            "live_runtime_events": False,
        },
        "boundary": _projection_boundary(),
    }
    if mcp_summary is not None:
        projection["major_critical_points"] = mcp_summary
    projection.update(_admin_export_handoff_projection_summaries(project_root))
    return projection


def _route_display_geometry_from_segment_display_geometry(
    *,
    project_id: str,
    segment_display_geometry: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    coordinate_segments: list[list[dict[str, float]]] = []
    for segment in segment_display_geometry.get("segments", []):
        coordinate_segments.extend(_display_coordinate_segments(segment))
    coordinates = [
        point
        for coordinate_segment in coordinate_segments
        for point in coordinate_segment
    ]
    return {
        "source_id": f"route_display_geometry.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_route_display_geometry",
        "display_point_count": len(coordinates),
        "display_segment_count": len(coordinate_segments),
        "coordinates": coordinates,
        "coordinate_segments": coordinate_segments,
        "boundary": {
            "display_geometry_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "internal_gpx_points_preserved": True,
            "gpx_segment_boundary_preserved": True,
        },
    }


def _display_coordinate_segments(
    display_geometry: dict[str, Any],
) -> list[list[dict[str, float]]]:
    coordinate_segments = display_geometry.get("coordinate_segments")
    if isinstance(coordinate_segments, list):
        normalized_segments = [
            _normalized_coordinate_segment(segment)
            for segment in coordinate_segments
            if isinstance(segment, list)
        ]
        normalized_segments = [
            segment for segment in normalized_segments if len(segment) >= 2
        ]
        if normalized_segments:
            return normalized_segments
    coordinates = _normalized_coordinate_segment(
        display_geometry.get("coordinates", [])
    )
    return [coordinates] if len(coordinates) >= 2 else []


def _normalized_coordinate_segment(segment: list[Any]) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for point in segment:
        if not isinstance(point, dict):
            continue
        lat = point.get("lat")
        lon = point.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        normalized.append({"lat": float(lat), "lon": float(lon)})
    return normalized


def _build_debug_projection_events(
    *,
    request: PretripImportRequest,
    import_timestamp: str,
    route_summary: dict[str, Any],
    reference_track_count: int,
    checkpoint_count: int,
    segment_count: int,
    rest_area_report: dict[str, Any],
    resume_segment_report: dict[str, Any],
    gis_perception: dict[str, Any],
    gis_perception_ai_judgements: dict[str, Any],
    gpx_speed_filter: dict[str, Any],
) -> list[dict[str, Any]]:
    session_id = f"debug_session.pretrip_import.{request.project_id}"
    filter_summary = _gpx_filter_summary(gpx_speed_filter, output_refs={})
    base_payload = {
        "project_id": request.project_id,
        "profile": request.profile,
        "import_stage": request.import_stage,
        "route_role": _golden_route_role(request),
        "projection_only": True,
        "planning_semantics": _planning_semantics(request),
        "gpx_speed_filter": filter_summary,
        "boundary": _projection_boundary(),
    }
    events = [
        RuntimeDebugEvent(
            event_id=f"debug_event.pretrip_import.{request.project_id}.000001",
            session_id=session_id,
            timestamp=import_timestamp,
            sequence=1,
            kind="debug_session_started",
            source="pretrip_import",
            phase="phase35",
            severity="info",
            subject_ref=request.project_id,
            summary="Pretrip import projection started.",
            payload=base_payload,
        ),
        RuntimeDebugEvent(
            event_id=f"debug_event.pretrip_import.{request.project_id}.000002",
            session_id=session_id,
            timestamp=import_timestamp,
            sequence=2,
            kind="provider_status_recorded",
            source="pretrip_import",
            phase="phase35",
            severity="info",
            subject_ref=request.project_id,
            summary=(
                "Local GPX import sources were inspected; GPX speed filter "
                f"removed {filter_summary['removed_track_point_count']} point(s)."
            ),
            payload={
                **base_payload,
                "provider": "local_gpx_corpus",
                "gis_perception_provider": gis_perception_ai_judgements[
                    "provider_kind"
                ],
                "gis_perception_model_name": gis_perception_ai_judgements[
                    "model_name"
                ],
                "gis_perception_prompt_sha256": gis_perception_ai_judgements[
                    "prompt_sha256"
                ],
                "golden_route_count": 1,
                "reference_track_count": reference_track_count,
                "network_calls_allowed": False,
            },
        ),
        RuntimeDebugEvent(
            event_id=f"debug_event.pretrip_import.{request.project_id}.000003",
            session_id=session_id,
            timestamp=import_timestamp,
            sequence=3,
            kind="progress_update_recorded",
            source="pretrip_import",
            phase="phase35",
            severity="info",
            subject_ref=request.project_id,
            summary="Pretrip route candidates were generated.",
            payload={
                **base_payload,
                "route_point_count": route_summary["point_count"],
                "distance_m": route_summary["distance_m"],
                "checkpoint_candidate_count": checkpoint_count,
                "segment_candidate_count": segment_count,
                "rest_area_candidate_count": rest_area_report["rest_area_candidate_count"],
                "rest_area_checkpoint_count": rest_area_report["rest_area_checkpoint_count"],
                "resume_segment_count": resume_segment_report["resume_segment_count"],
                "route_note_candidate_count": gis_perception["counts"][
                    "gpx_route_note_candidate_count"
                ],
                "route_note_ln_proposal_count": gis_perception["counts"][
                    "gpx_ln_proposal_count"
                ],
                "gis_perception_ai_judgement_count": gis_perception_ai_judgements[
                    "judgement_count"
                ],
                "gis_perception_checkpoint_candidate_count": gis_perception["counts"][
                    "checkpoint_candidate_count"
                ],
            },
        ),
        RuntimeDebugEvent(
            event_id=f"debug_event.pretrip_import.{request.project_id}.000004",
            session_id=session_id,
            timestamp=import_timestamp,
            sequence=4,
            kind="debug_session_completed",
            source="pretrip_import",
            phase="phase35",
            severity="info",
            subject_ref=request.project_id,
            summary="Pretrip import projection completed.",
            payload={
                **base_payload,
                "safety_level": "L0_NORMAL",
                "observations_processed": route_summary["point_count"],
                "mission_graph_compiled": False,
                "actual_user_track_available": request.import_stage == "post_analysis",
            },
        ),
    ]
    return [event.model_dump(mode="json") for event in events]


def _projection_boundary() -> dict[str, bool]:
    return {
        "projection_only": True,
        "golden_route_is_reference_evidence": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "mission_graph_compiled": False,
    }


def _source_record(path: Path, *, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "uri": path.resolve().as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
    }


def _golden_route_role(request: PretripImportRequest) -> str:
    if request.import_stage == "post_analysis":
        return "actual_track_replacing_pretrip_golden_route"
    return "golden_route_reference"


def _planning_semantics(request: PretripImportRequest) -> dict[str, Any]:
    return {
        "golden_route": {
            "meaning": (
                "selected similar reference route before departure"
                if request.import_stage == "pretrip"
                else "actual walked route replacing the pretrip golden route"
            ),
            "actual_user_track": request.import_stage == "post_analysis",
            "runtime_safety_truth": False,
        },
        "pretrip_actual_user_track_exists": request.import_stage == "post_analysis",
        "manual_waypoint_route_policy": {
            "unwalked_route_sections_allowed": True,
            "manual_waypoints_required": True,
            "danger_review_required": True,
            "notes": (
                "Unwalked route sections（未曾發生的路徑區段）can be planned only "
                "through manually drawn waypoint candidates and must raise danger review."
            ),
        },
        "post_analysis_replacement_policy": {
            "actual_track_may_replace_pretrip_golden_route": True,
            "historical_planning_evidence_mutation_allowed": False,
        },
    }


def _project_payload(
    *,
    project_root: Path,
    project_id: str,
    output_refs: dict[str, str],
    route_summary: dict[str, Any],
    reference_track_count: int,
    checkpoint_count: int,
    segment_count: int,
    resume_segment_count: int,
    rest_area_candidate_count: int,
    rest_area_checkpoint_count: int,
    checkpoint_event_count: int,
    reference_track_display_geometry_count: int,
    gis_perception: dict[str, Any],
    gis_perception_ai_judgements: dict[str, Any],
    route_note_ln_proposals: dict[str, Any],
    route_note_review_options: dict[str, Any],
    source_inbox_manifest: dict[str, Any],
    import_stage: ImportStage,
    gpx_speed_filter: dict[str, Any],
    segment_display_geometry: dict[str, Any],
    segment_policy_candidates: dict[str, Any],
    retreat_route_count: int,
    weather_daylight_evidence_count: int,
    segment_dtm_coverage: dict[str, Any] | None,
    dtm_coverage_summary: dict[str, Any] | None,
    mcp_import_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    project_path = project_root / "project.json"
    payload: dict[str, Any] = {}
    if project_path.exists():
        payload = json.loads(project_path.read_text(encoding="utf-8"))
    imagery_scope = _build_imagery_acquisition_scope(route_summary)
    imagery_source_id = str(
        payload.get("imagery_source_id") or imagery_scope["imagery_source_id"]
    )
    payload.update(
        {
            "project_id": project_id,
            "route_name": route_summary["route_name"],
            "import_profile": "standalone_pretrip_importer",
            "import_stage": import_stage,
            "route_role": "golden_route",
            "actual_user_track_available": import_stage == "post_analysis",
            "importer_version": IMPORTER_VERSION,
            **output_refs,
            "source_inbox_file_count": source_inbox_manifest["source_file_count"],
            "source_artifact_count": 1 + reference_track_count,
            "checkpoint_candidate_count": checkpoint_count,
            "segment_candidate_count": segment_count,
            "resume_segment_count": resume_segment_count,
            "rest_area_candidate_count": rest_area_candidate_count,
            "rest_area_checkpoint_count": rest_area_checkpoint_count,
            "checkpoint_event_count": checkpoint_event_count,
            "reference_track_display_geometry_count": (
                reference_track_display_geometry_count
            ),
            "segment_display_geometry_count": segment_display_geometry.get(
                "segment_count",
                segment_count,
            ),
            "segment_policy_candidate_count": segment_policy_candidates["counts"][
                "segment_policy_candidate_count"
            ],
            "retreat_route_candidate_count": retreat_route_count,
            "weather_daylight_evidence_count": weather_daylight_evidence_count,
            "route_note_candidate_count": gis_perception["counts"][
                "gpx_route_note_candidate_count"
            ],
            "route_note_potential_ln_signal_count": gis_perception["counts"][
                "gpx_potential_ln_signal_count"
            ],
            "route_note_ln_proposal_count": gis_perception["counts"]["gpx_ln_proposal_count"],
            "route_note_ln_hint_coverage_proposal_count": route_note_ln_proposals[
                "counts"
            ]["hint_coverage_proposal_count"],
            "route_note_ln_warning_coverage_proposal_count": route_note_ln_proposals[
                "counts"
            ]["warning_coverage_proposal_count"],
            "route_note_review_option_count": route_note_review_options["counts"][
                "review_option_count"
            ],
            "gis_perception_ai_judgement_count": gis_perception_ai_judgements[
                "judgement_count"
            ],
            "gis_perception_checkpoint_candidate_count": gis_perception["counts"][
                "checkpoint_candidate_count"
            ],
            "map_corridor_candidate_count": 1,
            "map_hazard_candidate_count": 0,
            "map_poi_candidate_count": 2,
            "reference_track_count": reference_track_count,
            "gpx_speed_filter_report_ref": output_refs["gpx_speed_filter_report_ref"],
            "gpx_speed_filter_removed_track_point_count": gpx_speed_filter[
                "removed_track_point_count"
            ],
            "gpx_speed_filter_exempted_track_point_count": gpx_speed_filter[
                "exempted_track_point_count"
            ],
            "gpx_speed_filter_max_reasonable_speed_kmh": gpx_speed_filter[
                "max_reasonable_speed_kmh"
            ],
            "resume_segment_report_ref": output_refs["resume_segment_report_ref"],
            "resume_segment_max_reasonable_point_gap_m": DEFAULT_RESUME_SEGMENT_GAP_M,
            "imagery_source_id": imagery_source_id,
            "imagery_source_registry_id": imagery_scope["imagery_source_registry_id"],
            "imagery_bbox_wgs84": imagery_scope["bbox_wgs84"],
            "imagery_source_route_bbox_wgs84": imagery_scope["source_route_bbox_wgs84"],
            "imagery_bbox_scale_factor": imagery_scope["scale_factor"],
            "imagery_bbox_policy": imagery_scope["bbox_policy"],
            "imagery_tile_cache_policy": imagery_scope["tile_cache_policy"],
            "boss_point_synthesis_status": "pending_map_preparation",
            "boss_point_synthesis_trigger": "prepare_layers_with_risk",
            "boss_point_synthesis_candidate_only": True,
            "boss_point_synthesis_runtime_safety_truth": False,
        }
    )
    if mcp_import_summary is not None:
        payload.update(mcp_import_summary["refs"])
        payload.update(mcp_import_summary["counts"])
        payload["mcp_named_point_evidence_source_path"] = mcp_import_summary[
            "source_path"
        ]
        payload["mcp_named_point_evidence_sha256"] = mcp_import_summary[
            "source_sha256"
        ]
    if segment_dtm_coverage is not None:
        payload["segment_dtm_coverage_ref"] = "normalized/terrain/segment_dtm_coverage.json"
        payload["segment_dtm_segment_count"] = segment_dtm_coverage.get(
            "segment_count",
            segment_count,
        )
    if dtm_coverage_summary is not None:
        payload["dtm_candidate_tile_count"] = len(
            dtm_coverage_summary.get("candidate_tiles", [])
        )
        payload["dtm_scanned_header_count"] = dtm_coverage_summary.get(
            "scanned_header_count",
            0,
        )
    _restore_local_imagery_refs_from_workspace(
        payload,
        project_root=project_root,
        project_id=project_id,
    )
    _restore_durable_admin_refs_from_workspace(payload, project_root=project_root)
    return payload


def _restore_local_imagery_refs_from_workspace(
    payload: dict[str, Any],
    *,
    project_root: Path,
    project_id: str,
) -> None:
    manifest_ref = (
        f"outputs/layers/manifests/{project_id}.local_raster_source_manifest.json"
    )
    tile_plan_ref = (
        f"outputs/layers/manifests/{project_id}.raster_tile_pyramid_plan.json"
    )
    manifest_path = project_root / manifest_ref
    tile_plan_path = project_root / tile_plan_ref
    if manifest_path.exists():
        payload.setdefault("imagery_manifest_ref", manifest_ref)
        payload.setdefault("local_raster_manifest_ref", manifest_ref)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        source_file = manifest.get("source_file") or {}
        handoff = manifest.get("handoff") or {}
        source_path = source_file.get("path") or handoff.get("scout_source_path")
        kmz_path = handoff.get("scout_kmz_path")
        if source_path:
            payload.setdefault("imagery_source_tiff_ref", source_path)
        if kmz_path:
            payload.setdefault("imagery_source_kmz_ref", kmz_path)
        if manifest.get("source_kind"):
            payload.setdefault(
                "imagery_source_kind",
                "user_provided_local_geotiff",
            )
    if tile_plan_path.exists():
        payload.setdefault("raster_tile_manifest_ref", tile_plan_ref)
        try:
            tile_plan = json.loads(tile_plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            tile_plan = {}
        if tile_plan.get("cache_root"):
            payload.setdefault("imagery_tile_cache_root", tile_plan["cache_root"])


def restore_durable_admin_evidence_refs(
    *,
    project_root: Path,
    source_root: Path,
) -> dict[str, Any]:
    """Restore admin evidence refs that importer/layer prep do not regenerate."""

    project_root = project_root.expanduser()
    source_root = source_root.expanduser()
    project_payload = _load_project_payload(project_root) or {
        "project_id": project_root.name
    }
    summary = _restore_durable_admin_refs_from_workspace(
        project_payload,
        project_root=project_root,
        source_root=source_root,
    )
    write_json(project_root / "project.json", project_payload)
    _refresh_admin_projection_export_summaries(project_root)
    review_queue_manifest = _rebuild_review_queue_if_possible(project_root)
    if review_queue_manifest is not None:
        write_json(
            project_root / "outputs" / "review_queue_manifest.json",
            review_queue_manifest.model_dump(mode="json"),
        )
        project_payload["review_queue_manifest_ref"] = (
            "outputs/review_queue_manifest.json"
        )
        project_payload["review_queue_item_count"] = (
            review_queue_manifest.counts.item_count
        )
        write_json(project_root / "project.json", project_payload)
        summary["review_queue_refreshed"] = True
    else:
        summary["review_queue_refreshed"] = False
    return summary


def _restore_durable_admin_refs_from_workspace(
    payload: dict[str, Any],
    *,
    project_root: Path,
    source_root: Path | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "source_root": source_root.as_posix() if source_root is not None else None,
        "restored": {},
        "copied": {},
        "skipped": {},
        "invalid": {},
    }
    if source_root is not None:
        source_project = _load_project_payload(source_root)
        if source_project is None:
            summary["source_project_missing"] = True
        else:
            _copy_durable_admin_evidence_files(
                source_project=source_project,
                source_root=source_root,
                destination_root=project_root,
                summary=summary,
            )
            for key in DURABLE_ADMIN_EVIDENCE_METADATA_KEYS:
                if key in payload:
                    summary["skipped"][key] = "payload_value_already_exists"
                    continue
                if key not in source_project:
                    summary["skipped"][key] = "source_value_missing"
                    continue
                payload[key] = source_project[key]
                summary["restored"][key] = source_project[key]
    for key in DURABLE_ADMIN_EVIDENCE_REF_KEYS:
        if _payload_ref_exists(payload, key, project_root=project_root):
            summary["skipped"][key] = "payload_ref_already_exists"
            continue
        restored_ref = summary["copied"].get(key) or DEFAULT_DURABLE_ADMIN_EVIDENCE_REFS[key]
        restored_path = _safe_project_ref_path(project_root, restored_ref)
        if restored_path is None:
            summary["invalid"][key] = restored_ref
            continue
        if restored_path.exists():
            payload[key] = restored_ref
            summary["restored"][key] = restored_ref
    return summary


def _copy_durable_admin_evidence_files(
    *,
    source_project: dict[str, Any],
    source_root: Path,
    destination_root: Path,
    summary: dict[str, Any],
) -> None:
    for key in DURABLE_ADMIN_EVIDENCE_REF_KEYS:
        ref = source_project.get(key)
        if not isinstance(ref, str) or not ref:
            summary["skipped"][key] = "source_ref_missing"
            continue
        source_path = _safe_project_ref_path(source_root, ref)
        destination_path = _safe_project_ref_path(destination_root, ref)
        if source_path is None or destination_path is None:
            summary["invalid"][key] = ref
            continue
        if not source_path.exists():
            summary["skipped"][key] = "source_file_missing"
            continue
        if destination_path.exists():
            summary["skipped"][key] = "destination_file_exists"
            continue
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.is_dir():
            shutil.copytree(source_path, destination_path)
        else:
            shutil.copy2(source_path, destination_path)
        summary["copied"][key] = ref


def _payload_ref_exists(
    payload: dict[str, Any],
    key: str,
    *,
    project_root: Path,
) -> bool:
    ref = payload.get(key)
    if not isinstance(ref, str) or not ref:
        return False
    path = _safe_project_ref_path(project_root, ref)
    return path is not None and path.exists()


def _safe_project_ref_path(project_root: Path, ref: str) -> Path | None:
    candidate = Path(ref)
    if candidate.is_absolute() or any(part in {"..", "."} for part in candidate.parts):
        return None
    project_root_resolved = project_root.resolve()
    path = (project_root / candidate).resolve()
    try:
        path.relative_to(project_root_resolved)
    except ValueError:
        return None
    return path


def _gpx_filter_summary(
    gpx_speed_filter: dict[str, Any],
    *,
    output_refs: dict[str, str],
) -> dict[str, Any]:
    return {
        "enabled": True,
        "applied": True,
        "filter_scope": gpx_speed_filter["filter_scope"],
        "max_reasonable_speed_kmh": gpx_speed_filter["max_reasonable_speed_kmh"],
        "max_previous_speed_ratio": gpx_speed_filter["max_previous_speed_ratio"],
        "route_note_protection_radius_m": gpx_speed_filter[
            "route_note_protection_radius_m"
        ],
        "source_file_count": gpx_speed_filter["source_file_count"],
        "original_track_point_count": gpx_speed_filter["original_track_point_count"],
        "filtered_track_point_count": gpx_speed_filter["filtered_track_point_count"],
        "removed_track_point_count": gpx_speed_filter["removed_track_point_count"],
        "exempted_track_point_count": gpx_speed_filter["exempted_track_point_count"],
        "report_ref": output_refs.get("gpx_speed_filter_report_ref"),
        "primary_removed_track_point_count": gpx_speed_filter["primary"][
            "removed_track_point_count"
        ],
        "reference_removed_track_point_count": sum(
            item["removed_track_point_count"]
            for item in gpx_speed_filter["references"]
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _gpx_filter_source_summary(
    source_report: dict[str, Any],
    *,
    report_ref: str,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "applied": True,
        "max_reasonable_speed_kmh": source_report["max_reasonable_speed_kmh"],
        "max_previous_speed_ratio": source_report["max_previous_speed_ratio"],
        "route_note_protection_radius_m": source_report[
            "route_note_protection_radius_m"
        ],
        "original_track_point_count": source_report["original_track_point_count"],
        "filtered_track_point_count": source_report["filtered_track_point_count"],
        "removed_track_point_count": source_report["removed_track_point_count"],
        "exempted_track_point_count": source_report["exempted_track_point_count"],
        "filtered_path": source_report["output_path"],
        "report_ref": report_ref,
        "detail_lists_embedded": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    main()
