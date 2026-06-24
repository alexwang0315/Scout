from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from admin_map_layers import build_pretrip_map_layers
from admin_evidence_timeline import (
    build_pretrip_evidence_timeline,
    build_scout_agent_skill_summary,
)
from post_analysis_capability import summarize_capability_artifacts
from scout_companion_match_models import build_companion_capability_capsule_from_timeline
from post_analysis_energy_feedback import POST_ANALYSIS_ENERGY_FEEDBACK_REF
from pretrip_layer_preparation import build_layer_preparation_not_prepared_view
from pretrip_energy_projection import DEFAULT_PRETRIP_ENERGY_PROJECTION_REF
from scout_energy_reserve_monitor import build_energy_reserve_monitor_from_view
from scout_runtime_physiologic_timeline import (
    PhysiologicTimelineProjection,
    build_physio_timeline_projection,
)
from scout_runtime_safety_gate_models import ScoutRuntimeSafetyGateEventBatch
from scout_runtime_safety_reducer import (
    RuntimeSafetyPhase1AdapterResult,
    RuntimeSafetyReducerDecision,
    reduce_runtime_safety_gate_events,
)
from pretrip_spatial_imprint_export import (
    DEFAULT_SPATIAL_IMPRINT_CANDIDATES_REF,
    DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF,
    DEFAULT_SPATIAL_IMPRINT_REVIEWS_REF,
    DEFAULT_SPATIAL_IMPRINT_SET_REF,
)


ROOT = Path(__file__).resolve().parent
CHILAI_NANHUA_DAY1_PROJECT_ID = "chilai_nanhua_day1"
PRETRIP_PROJECTS_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"
EXPERT_CONTRIBUTION_APPLY_PLAN_REF = "outputs/expert_contribution_apply_plan.json"
EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF = (
    "outputs/expert_contribution_workspace_apply_result.json"
)
ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF = "outputs/route_note_reviewed_assumptions.json"
DEPARTURE_REVIEWED_CANDIDATES_REF = "outputs/departure_reviewed_candidates.json"
COMPANION_MATCH_REVIEW_REF = "outputs/companion_match_review.json"
REFERENCE_SEGMENT_TIMING_REF = "outputs/reference_segment_timing.json"
GIS_PERCEPTION_AGGREGATION_RADIUS_M = 80.0
GIS_PERCEPTION_NEARBY_GROUP_RADIUS_M = 80.0
GIS_PERCEPTION_LABEL_MAX_CHARS = 64
ROUTE_PROJECTION_FILTER_VERSION = "pretrip_route_bounds_projection_filter.v1"
ROUTE_DISPLAY_BOUNDS_VERSION = "pretrip_route_reference_display_bounds.v1"
ROUTE_DISPLAY_BOUNDS_PRIMARY_OVERLAP_MIN = 0.55
ROUTE_DISPLAY_BOUNDS_COMPARISON_OVERLAP_MIN = 0.55
RISK_DELTA_COLORS = {
    "calibrated_higher": "#9333ea",
    "baseline_higher": "#2563eb",
    "aligned_high": "#7f1d1d",
    "minor_shift": "#64748b",
    "aligned": "#94a3b8",
}
READY_LAYER_STATUSES = {
    "ready",
    "ready_from_project_ref",
    "ready_with_fallback",
    "projection_ready",
}
EMPTY_PRETRIP_BOUNDARY = {
    "pretrip_candidate_evidence_only": True,
    "projection_only": True,
    "phase1_runtime_mutation_allowed": False,
    "phase2_brain_writeback_allowed": False,
    "runtime_safety_truth": False,
}


def _route_projection_bounds(route_summary: dict[str, Any]) -> dict[str, float] | None:
    bbox = route_summary.get("bbox_wgs84")
    if not isinstance(bbox, dict):
        return None
    try:
        bounds = {
            "south": float(bbox["min_lat"]),
            "north": float(bbox["max_lat"]),
            "west": float(bbox["min_lon"]),
            "east": float(bbox["max_lon"]),
        }
    except (KeyError, TypeError, ValueError):
        try:
            bounds = {
                "south": float(bbox["south"]),
                "north": float(bbox["north"]),
                "west": float(bbox["west"]),
                "east": float(bbox["east"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    if not (bounds["south"] <= bounds["north"] and bounds["west"] <= bounds["east"]):
        return None
    return bounds


def _expand_bounds_with_point(
    bounds: dict[str, float],
    point: dict[str, Any],
) -> None:
    try:
        lat = float(point["lat"])
        lon = float(point["lon"])
    except (KeyError, TypeError, ValueError):
        return
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return
    bounds["south"] = min(bounds["south"], lat)
    bounds["north"] = max(bounds["north"], lat)
    bounds["west"] = min(bounds["west"], lon)
    bounds["east"] = max(bounds["east"], lon)


def _display_geometry_points(display: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(display, dict):
        return []
    points: list[dict[str, Any]] = []
    coordinate_segments = display.get("coordinate_segments")
    if isinstance(coordinate_segments, list):
        for segment in coordinate_segments:
            if isinstance(segment, list):
                points.extend(point for point in segment if isinstance(point, dict))
    if points:
        return points
    coordinates = display.get("coordinates")
    if isinstance(coordinates, list):
        return [point for point in coordinates if isinstance(point, dict)]
    return []


def _reference_display_geometry_by_id(
    reference_track_display_geometry: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(reference_track_display_geometry, dict):
        return {}
    return {
        item["reference_id"]: item
        for item in reference_track_display_geometry.get("reference_tracks", [])
        if isinstance(item, dict) and item.get("reference_id")
    }


def _route_reference_display_bounds(
    route_summary: dict[str, Any],
    reference_tracks: dict[str, Any] | None,
    reference_track_display_geometry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    base_bounds = _route_projection_bounds(route_summary)
    if base_bounds is None:
        return None

    bounds = dict(base_bounds)
    display_by_id = _reference_display_geometry_by_id(reference_track_display_geometry)
    included_reference_ids: list[str] = []
    skipped_reference_ids: list[str] = []
    for track in (reference_tracks or {}).get("reference_tracks", []):
        if not isinstance(track, dict):
            continue
        reference_id = track.get("reference_id")
        comparison = track.get("bbox_comparison") or {}
        primary_overlap = float(comparison.get("primary_overlap_ratio") or 0.0)
        comparison_overlap = float(comparison.get("comparison_overlap_ratio") or 0.0)
        eligible = (
            bool(comparison.get("overlaps"))
            and primary_overlap >= ROUTE_DISPLAY_BOUNDS_PRIMARY_OVERLAP_MIN
            and comparison_overlap >= ROUTE_DISPLAY_BOUNDS_COMPARISON_OVERLAP_MIN
        )
        if not eligible or not reference_id:
            if reference_id:
                skipped_reference_ids.append(reference_id)
            continue
        points = _display_geometry_points(display_by_id.get(reference_id))
        if not points:
            skipped_reference_ids.append(reference_id)
            continue
        before = dict(bounds)
        for point in points:
            _expand_bounds_with_point(bounds, point)
        if bounds != before:
            included_reference_ids.append(reference_id)
        else:
            skipped_reference_ids.append(reference_id)

    return {
        "bounds_wgs84": bounds,
        "base_route_bounds_wgs84": base_bounds,
        "strategy": "route_bounds_plus_high_overlap_reference_display_geometry",
        "version": ROUTE_DISPLAY_BOUNDS_VERSION,
        "primary_overlap_min": ROUTE_DISPLAY_BOUNDS_PRIMARY_OVERLAP_MIN,
        "comparison_overlap_min": ROUTE_DISPLAY_BOUNDS_COMPARISON_OVERLAP_MIN,
        "included_reference_ids": included_reference_ids,
        "skipped_reference_ids": skipped_reference_ids,
        "raw_artifacts_mutated": False,
        "display_only": True,
        "runtime_safety_truth": False,
    }


def _point_within_projection_bounds(
    item: dict[str, Any],
    bounds: dict[str, float] | None,
) -> bool:
    if bounds is None:
        return True
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        bounds["south"] <= lat <= bounds["north"]
        and bounds["west"] <= lon <= bounds["east"]
    )


def _projection_filter_summary(
    *,
    source_count: int,
    visible_count: int,
    display_bounds: dict[str, float] | None,
) -> dict[str, Any]:
    if display_bounds is None:
        return {
            "strategy": "none",
            "source_candidate_count": source_count,
            "visible_candidate_count": visible_count,
            "filtered_out_of_route_bounds_count": 0,
            "raw_artifacts_mutated": False,
            "runtime_safety_truth": False,
        }
    return {
        "strategy": "route_bounds_wgs84_ui_projection_filter",
        "version": ROUTE_PROJECTION_FILTER_VERSION,
        "bounds_wgs84": dict(display_bounds),
        "source_candidate_count": source_count,
        "visible_candidate_count": visible_count,
        "filtered_out_of_route_bounds_count": source_count - visible_count,
        "raw_artifacts_mutated": False,
        "candidate_evidence_mutated": False,
        "runtime_safety_truth": False,
    }


def _missing_artifact_status(artifact_key: str) -> dict[str, Any]:
    return {
        "status": "missing_source",
        "counts": {},
        "boundary": dict(EMPTY_PRETRIP_BOUNDARY),
        "warnings": [f"{artifact_key} is not present in this standalone workspace."],
    }


def _default_pretrip_artifact(
    artifact_key: str,
    *,
    project_id: str,
    project: dict[str, Any],
    route_summary: dict[str, Any] | None = None,
    pretrip_package: dict[str, Any] | None = None,
) -> Any:
    route_summary = route_summary or {}
    pretrip_package = pretrip_package or {}
    boundary = dict(EMPTY_PRETRIP_BOUNDARY)
    if artifact_key == "retreat_routes":
        return []
    if artifact_key == "readiness":
        return {
            "report_id": f"readiness.{project_id}.missing",
            "status": "missing_source",
            "findings": [],
            "boundary": boundary,
        }
    if artifact_key == "eta":
        return {
            "plan_id": f"eta.{project_id}.missing",
            "status": "missing_source",
            "assumption": {},
            "estimates": [],
            "boundary": boundary,
        }
    if artifact_key == "overpass_evidence":
        return {
            "source_artifact": {"artifact_id": f"overpass.{project_id}.missing"},
            "status": "missing_source",
            "counts": {"candidates": 0},
            "boundary": boundary,
            "request": {
                "endpoint": "",
                "raw_response_sha256": "",
                "conversion_rule_version": "not_available",
            },
            "normalized_geojson_ref": "",
            "candidates": [],
            "skipped_objects": [],
        }
    if artifact_key == "review_draft_log":
        return {
            "log_id": f"review_draft.{project_id}.missing",
            "status": "missing_source",
            "counts": {"action_count": 0, "category_counts": {}},
            "boundary": boundary,
            "actions": [],
        }
    if artifact_key == "review_decision_log":
        return {
            "log_id": f"review_decisions.{project_id}.missing",
            "status": "missing_source",
            "counts": {"decision_count": 0},
            "apply_summary": {},
            "boundary": boundary,
            "decisions": [],
        }
    if artifact_key == "review_decision_apply_plan":
        return {
            "plan_id": f"review_apply.{project_id}.missing",
            "project_id": project_id,
            "package_id": pretrip_package.get("package_id", f"package.{project_id}"),
            "package_status": pretrip_package.get("status", "candidate_only"),
            "package_ref": project.get("package_ref", ""),
            "review_decision_log_ref": project.get("review_decision_log_ref", ""),
            "counts": {"decision_count": 0},
            "boundary": boundary,
            "decisions": [],
        }
    if artifact_key == "external_import_queue":
        return {
            "queue_id": f"external_import.{project_id}.missing",
            "status": "missing_source",
            "counts": {"request_count": 0},
            "boundary": boundary,
            "requests": [],
        }
    if artifact_key == "expert_contribution_log":
        return {
            "log_id": f"expert_contribution.{project_id}.missing",
            "status": "missing_source",
            "counts": {"contribution_count": 0},
            "boundary": boundary,
            "contributions": [],
        }
    if artifact_key == "departure_bundle":
        return {
            "bundle_id": f"departure_bundle.{project_id}.missing",
            "status": "missing_source",
            "counts": {"route_ref_count": 0, "terrain_ref_count": 0},
            "boundary": boundary,
            "package": {},
            "route_refs": [],
            "terrain_refs": [],
        }
    if artifact_key == "resource_plan":
        return {
            "plan_id": f"resource_plan.{project_id}.missing",
            "status": "missing_source",
            "raw_payloads_embedded": False,
            "external_api_calls_made": False,
            "devices": [],
            "equipment": [],
            "team_members": [],
            "departure_readiness_context": {},
        }
    if artifact_key == "weather_daylight":
        return {
            "evidence_id": f"weather_daylight.{project_id}.missing",
            "status": "missing_source",
            "external_api_calls_made": False,
            "authoritative_weather_computed": False,
            "location_name": route_summary.get("route_name", project_id),
            "date": "",
            "timezone": "",
            "daylight": {},
            "weather_window": {},
        }
    if artifact_key == "contour":
        return {
            "artifact_id": f"contour.{project_id}.missing",
            "status": "missing_source",
            "candidates": [],
            "not_observed_fact": True,
            "raw_payloads_embedded": False,
        }
    if artifact_key == "remote_summary":
        return {
            "summary_id": f"remote_contacts.{project_id}.missing",
            "audience": "operator",
            "readiness": "missing_source",
            "route": route_summary.get("route_name", project_id),
            "retreat_route_summary": "not_available",
            "conservative_notes": [],
        }
    if artifact_key == "route_comparison":
        return {
            "comparison_id": f"route_comparison.{project_id}.missing",
            "classification": "missing_source",
            "distance_delta_m": None,
            "point_count_delta": None,
            "bbox_comparison": {},
        }
    if artifact_key == "segment_dtm":
        return {
            "dtm_coverage_summary_id": f"segment_dtm.{project_id}.missing",
            "route_artifact_id": route_summary.get("artifact_id", project_id),
            "segment_count": project.get("segment_candidate_count", 0),
            "candidate_tile_count": 0,
            "notes": ["segment DTM coverage is not present in this standalone workspace."],
            "segment_metadata": [],
        }
    if artifact_key == "runtime_handoff":
        return {
            "manifest_id": f"runtime_handoff.{project_id}.missing",
            "status": "missing_source",
            "counts": {},
            "boundary": boundary,
        }
    if artifact_key == "runtime_audit":
        return {
            "manifest_id": f"runtime_audit.{project_id}.missing",
            "status": "missing_source",
            "counts": {},
            "axes": [],
            "boundary": boundary,
        }
    if artifact_key == "after_action":
        return {
            "artifact_id": f"after_action.{project_id}.missing",
            "status": "missing_source",
            "counts": {},
            "raw_payloads_embedded": False,
            "observed_fact_writeback_allowed": False,
            "historical_evidence_mutation_allowed": False,
        }
    return _missing_artifact_status(artifact_key)


def build_pretrip_admin_view(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> dict[str, Any]:
    artifacts = resolve_pretrip_project_artifacts(
        project_id,
        root=root,
        project_root=project_root,
    )
    project = _load_json(artifacts["project"])

    route_summary = _load_json(artifacts["route_summary"])
    map_context = _load_json(artifacts["map_context"])
    checkpoints = _load_json(artifacts["checkpoints"])
    segments = _load_json(artifacts["segments"])
    retreat_routes = _load_optional_json(artifacts.get("retreat_routes"))
    if retreat_routes is None:
        retreat_routes = _default_pretrip_artifact(
            "retreat_routes",
            project_id=project_id,
            project=project,
            route_summary=route_summary,
        )
    map_candidates = _load_json(artifacts["map_candidates"])
    pretrip_package = _load_json(artifacts["package"])
    readiness = _load_optional_json(
        artifacts.get("readiness")
    ) or _default_pretrip_artifact(
        "readiness",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    eta = _load_optional_json(artifacts.get("eta")) or _default_pretrip_artifact(
        "eta",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    energy_projection = _load_optional_json(artifacts.get("energy_projection"))
    route_notes = _load_json(artifacts["route_notes"])
    overpass_evidence = _load_optional_json(
        artifacts.get("overpass_evidence")
    ) or _default_pretrip_artifact(
        "overpass_evidence",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    route_note_ln_proposals = _load_json(artifacts["route_note_ln_proposals"])
    gis_perception = _load_optional_json(artifacts.get("gis_perception"))
    gis_perception_ai_judgements = _load_optional_json(
        artifacts.get("gis_perception_ai_judgements")
    )
    route_note_review_options = _load_json(artifacts["route_note_review_options"])
    review_queue = _load_json(artifacts["review_queue"])
    review_draft_log = _load_optional_json(
        artifacts.get("review_draft_log")
    ) or _default_pretrip_artifact(
        "review_draft_log",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    review_decision_log = _load_optional_json(
        artifacts.get("review_decision_log")
    ) or _default_pretrip_artifact(
        "review_decision_log",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    review_decision_apply_plan = _load_optional_json(
        artifacts.get("review_decision_apply_plan")
    ) or _default_pretrip_artifact(
        "review_decision_apply_plan",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
        pretrip_package=pretrip_package,
    )
    external_import_queue = _load_optional_json(
        artifacts.get("external_import_queue")
    ) or _default_pretrip_artifact(
        "external_import_queue",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    expert_contribution_log = _load_optional_json(
        artifacts.get("expert_contribution_log")
    ) or _default_pretrip_artifact(
        "expert_contribution_log",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    expert_contribution_apply_plan = _load_optional_json(
        artifacts["expert_contribution_apply_plan"]
    )
    expert_contribution_workspace_apply_result = _load_optional_json(
        artifacts["expert_contribution_workspace_apply_result"]
    )
    route_note_reviewed_assumptions = _load_optional_json(
        artifacts["route_note_reviewed_assumptions"]
    )
    departure_reviewed_candidates = _load_optional_json(
        artifacts["departure_reviewed_candidates"]
    )
    mcp_named_point_evidence = _load_optional_json(
        artifacts.get("mcp_named_point_evidence")
    )
    mcp_retrieval_plan = _load_optional_json(artifacts.get("mcp_retrieval_plan"))
    mcp_ocr_labels = _load_optional_json(artifacts.get("mcp_ocr_labels"))
    mcp_candidates = _load_optional_json(artifacts.get("mcp_candidates"))
    mcp_cp_support_reconciliation = _load_optional_json(
        artifacts.get("mcp_cp_support_reconciliation")
    )
    mcp_review_log = _load_optional_json(artifacts.get("mcp_review_log"))
    boss_points = _load_optional_json(artifacts.get("boss_points"))
    boss_points_geojson = _load_optional_json(artifacts.get("boss_points_geojson"))
    mileage_tag_alignment = _load_optional_json(artifacts.get("mileage_tag_alignment"))
    mileage_tag_alignment_geojson = _load_optional_json(
        artifacts.get("mileage_tag_alignment_geojson")
    )
    spatial_imprint_candidates = _load_optional_json(
        artifacts.get("spatial_imprint_candidates")
    )
    spatial_imprint_reviews = _load_optional_json(
        artifacts.get("spatial_imprint_reviews")
    )
    spatial_imprint_set = _load_optional_json(
        artifacts.get("spatial_imprint_set")
    )
    spatial_imprint_manifest = _load_optional_json(
        artifacts.get("spatial_imprint_manifest")
    )
    departure_bundle = _load_optional_json(
        artifacts.get("departure_bundle")
    ) or _default_pretrip_artifact(
        "departure_bundle",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
        pretrip_package=pretrip_package,
    )
    resource_plan = _load_optional_json(
        artifacts.get("resource_plan")
    ) or _default_pretrip_artifact(
        "resource_plan",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    weather_daylight = _load_optional_json(
        artifacts.get("weather_daylight")
    ) or _default_pretrip_artifact(
        "weather_daylight",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    contour = _load_optional_json(
        artifacts.get("contour")
    ) or _default_pretrip_artifact(
        "contour",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    remote_summary = _load_optional_json(
        artifacts.get("remote_summary")
    ) or _default_pretrip_artifact(
        "remote_summary",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    route_comparison = _load_optional_json(
        artifacts.get("route_comparison")
    ) or _default_pretrip_artifact(
        "route_comparison",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    reference_tracks = _load_optional_json(artifacts.get("reference_tracks"))
    reference_segment_timing = _load_optional_json(
        artifacts.get("reference_segment_timing")
    )
    checkpoint_events = _load_optional_json(artifacts.get("checkpoint_events"))
    risk_score_points = _load_optional_json(artifacts.get("risk_score_points"))
    risk_score_points_metadata = _load_optional_json(
        artifacts.get("risk_score_points_metadata")
    )
    risk_route_profile = _load_optional_json(artifacts.get("risk_route_profile"))
    risk_route_profile_metadata = _load_optional_json(
        artifacts.get("risk_route_profile_metadata")
    )
    risk_ribbon = _load_optional_json(artifacts.get("risk_ribbon"))
    risk_ribbon_metadata = _load_optional_json(
        artifacts.get("risk_ribbon_metadata")
    )
    risk_heatmap = _load_optional_json(artifacts.get("calibrated_risk_heatmap"))
    risk_heatmap_metadata = _load_optional_json(
        artifacts.get("calibrated_risk_heatmap_metadata")
    )
    cwa_weather_evidence = _load_optional_json(artifacts.get("cwa_weather_evidence"))
    cwa_warnings_geojson = _load_optional_json(artifacts.get("cwa_warnings_geojson"))
    cwa_observations_geojson = _load_optional_json(
        artifacts.get("cwa_observations_geojson")
    )
    cwa_qpf_grid = _load_optional_json(artifacts.get("cwa_qpf_grid"))
    cwa_qpf_corridor_summary = _load_optional_json(
        artifacts.get("cwa_qpf_corridor_summary")
    )
    gee_feature_package = _load_optional_json(artifacts.get("gee_feature_package"))
    environment_risk_derivatives = _load_optional_json(
        artifacts.get("environment_risk_derivatives")
    )
    new_landslide_candidates = _load_optional_json(
        artifacts.get("new_landslide_candidates")
    )
    wetness_flash_flood_susceptibility = _load_optional_json(
        artifacts.get("wetness_flash_flood_susceptibility")
    )
    trail_obscurity_risk = _load_optional_json(
        artifacts.get("trail_obscurity_risk")
    )
    practical_darkness_time = _load_optional_json(
        artifacts.get("practical_darkness_time")
    )
    route_revalidation_report = _load_optional_json(
        artifacts.get("route_revalidation_report")
    )
    soil_moisture_grid = _load_optional_json(artifacts.get("soil_moisture_grid"))
    smap_l4_corridor_summary = _load_optional_json(
        artifacts.get("smap_l4_corridor_summary")
    )
    antecedent_rain_grid = _load_optional_json(artifacts.get("antecedent_rain_grid"))
    gpm_imerg_corridor_summary = _load_optional_json(
        artifacts.get("gpm_imerg_corridor_summary")
    )
    segment_display_geometry = _load_optional_json(
        artifacts.get("segment_display_geometry")
    )
    reference_track_display_geometry = _load_optional_json(
        artifacts.get("reference_track_display_geometry")
    )
    import_manifest = _load_optional_json(artifacts.get("import_manifest"))
    layer_preparation_manifest = _load_optional_json(
        artifacts.get("layer_preparation_manifest")
    )
    admin_surface_projection = _load_optional_json(artifacts.get("admin_projection"))
    debug_projection_events = _load_optional_jsonl(
        artifacts.get("debug_projection_events")
    )
    segment_dtm = _load_optional_json(
        artifacts.get("segment_dtm")
    ) or _default_pretrip_artifact(
        "segment_dtm",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    terrain_visualization = _load_optional_json(artifacts.get("terrain_visualization"))
    human_reviews = _load_json(artifacts["human_reviews"])
    runtime_handoff = _load_optional_json(
        artifacts.get("runtime_handoff")
    ) or _default_pretrip_artifact(
        "runtime_handoff",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    runtime_audit = _load_optional_json(
        artifacts.get("runtime_audit")
    ) or _default_pretrip_artifact(
        "runtime_audit",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    after_action = _load_optional_json(
        artifacts.get("after_action")
    ) or _default_pretrip_artifact(
        "after_action",
        project_id=project_id,
        project=project,
        route_summary=route_summary,
    )
    brain_seed = _load_json(artifacts["brain_seed"])
    planning_skill_audit = _load_optional_json(
        artifacts.get("planning_skill_audit")
    )
    planning_skill_manifest_catalog = _load_optional_json(
        artifacts.get("planning_skill_manifest_catalog")
    )
    capability_timeline_import = _load_capability_timeline_import(
        project_id,
        root=root,
        project_root=artifacts["project"].parent,
    )
    companion_match_review = _load_optional_json(
        artifacts.get("companion_match_review")
    )
    post_analysis_energy_feedback = _load_optional_json(
        artifacts.get("post_analysis_energy_feedback")
    )

    source_refs = _source_refs(artifacts, root if project_root is None else project_root)
    route_projection_bounds = _route_projection_bounds(route_summary)
    route_display_bounds = _route_reference_display_bounds(
        route_summary,
        reference_tracks,
        reference_track_display_geometry,
    )
    route_points = _route_point_samples(route_summary, checkpoints)
    route_polyline = _route_polyline(map_context)
    segment_display_by_id = _segment_display_geometry_by_id(segment_display_geometry)
    mission_checkpoints = _candidate_list(
        checkpoints,
        source_path=source_refs["checkpoints"],
        evidence_type="pretrip_checkpoint_candidate",
    )
    mission_segments = _candidate_list(
        segments,
        source_path=source_refs["segments"],
        evidence_type="pretrip_segment_candidate",
        display_geometry=segment_display_by_id,
    )
    mission_retreat_routes = _candidate_list(
        retreat_routes,
        source_path=source_refs["retreat_routes"],
        evidence_type="pretrip_retreat_route_candidate",
    )
    route_display_geometry = _route_display_geometry_from_segments(
        project_id,
        mission_segments,
    )
    route_centerline_geometry = _route_display_geometry_from_risk_ribbon(
        project_id=project_id,
        payload=risk_ribbon,
        source_path=source_refs.get("risk_ribbon", ""),
    ) or route_display_geometry

    planning_tab = {
        "summary": _project_summary(project, route_summary, pretrip_package, source_refs),
        "route": {
            "source_id": route_summary["artifact_id"],
            "source_path": source_refs["route_summary"],
            "evidence_type": "pretrip_route_summary",
            "route_name": route_summary["route_name"],
            "bounds": route_summary["bbox_wgs84"],
            "display_bounds": (
                route_display_bounds["bounds_wgs84"]
                if route_display_bounds is not None
                else None
            ),
            "display_bounds_metadata": route_display_bounds,
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "elevation_min_m": route_summary.get("elevation_min_m"),
            "elevation_max_m": route_summary.get("elevation_max_m"),
            "started_at": route_summary.get("started_at"),
            "ended_at": route_summary.get("ended_at"),
            "point_samples": route_points,
            "polyline": route_polyline,
            "display_geometry": route_display_geometry,
        },
        "mission_candidates": {
            "checkpoints": mission_checkpoints,
            "segments": mission_segments,
            "retreat_routes": mission_retreat_routes,
        },
        "map_candidates": _map_candidate_summary(map_candidates, source_refs["map_candidates"]),
        "readiness": _summary_with_source(
            readiness,
            source_id=f"readiness.{project_id}",
            source_path=source_refs["readiness"],
            evidence_type="pretrip_readiness_report",
            include_keys=("status", "findings"),
        ),
        "eta": {
            "source_id": eta["plan_id"],
            "source_path": source_refs["eta"],
            "evidence_type": "pretrip_eta_plan",
            "planned_start_time": eta["assumption"].get("planned_start_time"),
            "target_eta": eta["assumption"].get("target_eta"),
            "turn_back_checkpoint_eta": eta["assumption"].get("turn_back_checkpoint_eta"),
            "estimate_count": len(eta.get("estimates", [])),
            "estimates": eta.get("estimates", []),
            "energy_reserve_projection": _energy_projection_summary(
                energy_projection,
                source_refs.get("energy_projection", ""),
            )
            if energy_projection is not None
            else None,
        },
        "route_notes": _route_note_summary(
            route_notes,
            source_refs["route_notes"],
            display_bounds=route_projection_bounds,
        ),
        "reference_tracks": _reference_tracks_summary(
            reference_tracks,
            source_refs.get("reference_tracks", ""),
            display_geometry=reference_track_display_geometry,
            display_source_path=source_refs.get("reference_track_display_geometry", ""),
        )
        if reference_tracks is not None
        else None,
        "reference_segment_timing": _reference_segment_timing_summary(
            reference_segment_timing,
            source_refs.get("reference_segment_timing", ""),
            project_id=project_id,
            route_segments=mission_segments,
        ),
        "checkpoint_events": _checkpoint_events_summary(
            checkpoint_events,
            source_refs.get("checkpoint_events", ""),
        )
        if checkpoint_events is not None
        else None,
        "layer_preparation": _layer_preparation_summary(
            layer_preparation_manifest,
            source_refs.get("layer_preparation_manifest", ""),
            project_id=project_id,
            project_root=artifacts["project"].parent,
        ),
        "terrain_visualization": _terrain_visualization_summary(
            project_id,
            terrain_visualization,
            source_refs.get("terrain_visualization", ""),
        ),
        "risk_score": _risk_score_summary(
            project_id,
            risk_score_points,
            risk_score_points_metadata,
            risk_route_profile,
            risk_route_profile_metadata,
            source_path=source_refs.get("risk_score_points", ""),
            metadata_source_path=source_refs.get("risk_score_points_metadata", ""),
            route_source_path=source_refs.get("risk_route_profile", ""),
            route_metadata_source_path=source_refs.get(
                "risk_route_profile_metadata",
                "",
            ),
        ),
        "risk_ribbon": _risk_ribbon_summary(
            project_id,
            risk_ribbon,
            risk_ribbon_metadata,
            source_path=source_refs.get("risk_ribbon", ""),
            metadata_source_path=source_refs.get("risk_ribbon_metadata", ""),
        ),
        "risk_heatmap": _risk_heatmap_summary(
            project_id,
            risk_heatmap,
            risk_heatmap_metadata,
            source_path=source_refs.get("calibrated_risk_heatmap", ""),
            metadata_source_path=source_refs.get(
                "calibrated_risk_heatmap_metadata",
                "",
            ),
        ),
        "overpass_evidence": _overpass_evidence_summary(
            overpass_evidence,
            source_refs["overpass_evidence"],
        ),
        "route_note_ln_proposals": _route_note_ln_proposal_summary(
            route_note_ln_proposals,
            source_refs["route_note_ln_proposals"],
        ),
        "gis_perception": _debug_projection_gis_perception_summary(
            project_id,
            gis_perception,
            source_refs.get("gis_perception", ""),
            ai_judgements_payload=gis_perception_ai_judgements,
            ai_judgements_source_path=source_refs.get(
                "gis_perception_ai_judgements",
                "",
            ),
            display_bounds=route_projection_bounds,
        ),
        "route_note_review_options": _route_note_review_options_summary(
            route_note_review_options,
            source_refs["route_note_review_options"],
        ),
        "review_queue": _review_queue_summary(review_queue, source_refs["review_queue"]),
        "review_draft_log": _review_draft_log_summary(
            review_draft_log,
            source_refs["review_draft_log"],
        ),
        "review_decision_log": _review_decision_log_summary(
            review_decision_log,
            source_refs["review_decision_log"],
        ),
        "review_decision_apply_plan": _review_decision_apply_plan_summary(
            review_decision_apply_plan,
            source_refs["review_decision_apply_plan"],
        ),
        "external_import_queue": _external_import_queue_summary(
            external_import_queue,
            source_refs["external_import_queue"],
        ),
        "expert_contributions": _expert_contribution_summary(
            expert_contribution_log,
            source_refs["expert_contribution_log"],
        ),
        "departure_bundle": _departure_bundle_summary(
            departure_bundle,
            source_refs["departure_bundle"],
        ),
        "resources": _resource_summary(resource_plan, source_refs["resource_plan"]),
        "weather": _weather_summary(weather_daylight, source_refs["weather_daylight"]),
        "cwa_qpf": _environment_geojson_summary(
            project_id,
            cwa_qpf_grid,
            source_path=source_refs.get("cwa_qpf_grid", ""),
            layer_id="cwa-qpf",
            evidence_type="cwa_forecast_derived_qpf_candidate",
            summary_payload=cwa_qpf_corridor_summary,
            summary_source_path=source_refs.get("cwa_qpf_corridor_summary", ""),
        ),
        "cwa_weather": _cwa_weather_environment_summary(
            project_id,
            evidence_payload=cwa_weather_evidence,
            warnings_geojson=cwa_warnings_geojson,
            observations_geojson=cwa_observations_geojson,
            source_refs=source_refs,
        ),
        "soil_moisture": _environment_geojson_summary(
            project_id,
            soil_moisture_grid,
            source_path=source_refs.get("soil_moisture_grid", ""),
            layer_id="soil-moisture",
            evidence_type="gee_soil_moisture_candidate",
            summary_payload=smap_l4_corridor_summary,
            summary_source_path=source_refs.get("smap_l4_corridor_summary", ""),
        ),
        "antecedent_rain": _environment_geojson_summary(
            project_id,
            antecedent_rain_grid,
            source_path=source_refs.get("antecedent_rain_grid", ""),
            layer_id="antecedent-rain",
            evidence_type="gee_antecedent_rain_candidate",
            summary_payload=gpm_imerg_corridor_summary,
            summary_source_path=source_refs.get("gpm_imerg_corridor_summary", ""),
        ),
        "contours": _contour_summary(contour, source_refs["contour"]),
        "remote_contacts": _remote_summary(remote_summary, source_refs["remote_summary"]),
    }
    planning_tab["environment_values"] = _environment_values_summary(
        project_id,
        source_refs=source_refs,
        cwa_qpf=planning_tab["cwa_qpf"],
        cwa_weather=planning_tab["cwa_weather"],
        soil_moisture=planning_tab["soil_moisture"],
        antecedent_rain=planning_tab["antecedent_rain"],
        gee_feature_package=gee_feature_package,
        environment_risk_derivatives=environment_risk_derivatives,
    )
    planning_tab["environment_risk_derivative_layers"] = (
        _environment_risk_derivative_layers_summary(
            project_id,
            source_refs=source_refs,
            environment_risk_derivatives=environment_risk_derivatives,
            new_landslide_candidates=new_landslide_candidates,
            wetness_flash_flood_susceptibility=wetness_flash_flood_susceptibility,
            trail_obscurity_risk=trail_obscurity_risk,
            practical_darkness_time=practical_darkness_time,
            route_revalidation_report=route_revalidation_report,
        )
    )
    planning_tab["risk_delta"] = _risk_delta_summary(
        project_id,
        planning_tab["risk_ribbon"],
        planning_tab["risk_heatmap"],
    )
    planning_tab["map_layers"] = build_pretrip_map_layers(
        source_refs=source_refs,
        weather=planning_tab["weather"],
    )
    planning_tab["map_layers"] = _map_layers_with_local_raster_metadata(
        planning_tab["map_layers"],
        project=project,
        local_raster_manifest=_load_optional_json(
            artifacts.get("local_raster_manifest")
        ),
        raster_tile_manifest=_load_optional_json(
            artifacts.get("raster_tile_manifest")
        ),
        raster_layer_manifests=_raster_layer_manifest_summaries(
            artifacts["project"].parent,
            project,
        ),
        local_raster_source_path=source_refs.get("local_raster_manifest", ""),
        raster_tile_source_path=source_refs.get("raster_tile_manifest", ""),
    )
    planning_tab["gis_perception_timeline"] = _gis_perception_timeline_summary(
        project_id,
        planning_tab["gis_perception"],
        overpass_evidence=planning_tab["overpass_evidence"],
    )
    planning_tab["review_queue"] = _review_queue_with_gis_perception_items(
        planning_tab["review_queue"],
        planning_tab["gis_perception_timeline"],
    )
    if energy_projection is not None:
        planning_tab["review_queue"] = _review_queue_with_energy_projection_item(
            planning_tab["review_queue"],
            planning_tab["eta"]["energy_reserve_projection"],
        )
    planning_tab["review_workbench"] = _review_workbench_summary(
        planning_tab["review_queue"],
        planning_tab["review_decision_log"],
        planning_tab["gis_perception_timeline"],
    )
    if route_note_reviewed_assumptions is not None:
        planning_tab["route_note_reviewed_assumptions"] = (
            _route_note_reviewed_assumptions_summary(
                route_note_reviewed_assumptions,
                source_refs["route_note_reviewed_assumptions"],
            )
        )
    if expert_contribution_apply_plan is not None:
        planning_tab["expert_contribution_apply_plan"] = (
            _expert_contribution_apply_plan_summary(
                expert_contribution_apply_plan,
                source_refs["expert_contribution_apply_plan"],
            )
        )
    if expert_contribution_workspace_apply_result is not None:
        planning_tab["expert_contribution_workspace_apply_result"] = (
            _expert_contribution_workspace_apply_result_summary(
                expert_contribution_workspace_apply_result,
                source_refs["expert_contribution_workspace_apply_result"],
            )
        )
    if departure_reviewed_candidates is not None:
        planning_tab["departure_reviewed_candidates"] = (
            _departure_reviewed_candidates_summary(
                departure_reviewed_candidates,
                source_refs["departure_reviewed_candidates"],
            )
        )
    if mcp_candidates is not None:
        planning_tab["major_critical_points"] = _mcp_summary(
            project_id=project_id,
            mcp_candidates=mcp_candidates,
            named_point_evidence=mcp_named_point_evidence,
            retrieval_plan=mcp_retrieval_plan,
            ocr_labels=mcp_ocr_labels,
            cp_support_reconciliation=mcp_cp_support_reconciliation,
            review_log=mcp_review_log,
            source_refs=source_refs,
        )
    if mcp_review_log is not None:
        planning_tab["mcp_review_actions"] = _mcp_review_actions_summary(
            mcp_review_log,
            source_refs["mcp_review_log"],
        )
    if boss_points is not None:
        planning_tab["boss_points"] = _boss_points_summary(
            boss_points,
            boss_points_geojson,
            source_refs=source_refs,
            route_display_geometry=route_centerline_geometry,
            route_bounds=route_projection_bounds,
        )
    if mileage_tag_alignment is not None:
        planning_tab["mileage_tag_alignment"] = _mileage_tag_alignment_summary(
            mileage_tag_alignment,
            mileage_tag_alignment_geojson,
            source_refs=source_refs,
        )
    if any(
        item is not None
        for item in (
            spatial_imprint_candidates,
            spatial_imprint_reviews,
            spatial_imprint_set,
            spatial_imprint_manifest,
        )
    ):
        planning_tab["spatial_imprints"] = _spatial_imprints_summary(
            project_id=project_id,
            candidates=spatial_imprint_candidates,
            reviews=spatial_imprint_reviews,
            imprint_set=spatial_imprint_set,
            manifest=spatial_imprint_manifest,
            source_refs=source_refs,
        )
    planning_sections = _planning_sections(planning_tab)
    review_workspace_section_ids = {
        "review_queue",
        "review_workbench",
        "route_note_review_options",
        "route_note_reviewed_assumptions",
        "review_draft_log",
        "review_decision_log",
        "review_decision_apply_plan",
        "external_import_queue",
        "expert_contributions",
        "expert_contribution_apply_plan",
        "expert_contribution_workspace_apply_result",
        "departure_reviewed_candidates",
        "mcp_review_actions",
        "spatial_imprints",
    }
    planning_tab["sections"] = [
        section
        for section in planning_sections
        if section["id"] not in review_workspace_section_ids
    ]

    post_analysis_tab = {
        "runtime_handoff": _runtime_handoff_summary(
            runtime_handoff,
            source_refs["runtime_handoff"],
        ),
        "runtime_audit": _runtime_audit_summary(runtime_audit, source_refs["runtime_audit"]),
        "route_comparison": _route_comparison_summary(
            route_comparison,
            source_refs["route_comparison"],
        ),
        "segment_terrain": _segment_terrain_summary(segment_dtm, source_refs["segment_dtm"]),
        "human_reviews": {
            "source_id": human_reviews["log_id"],
            "source_path": source_refs["human_reviews"],
            "evidence_type": "pretrip_human_review_log",
            "review_count": len(human_reviews.get("reviews", [])),
        },
        "after_action_next_plan": _after_action_summary(after_action, source_refs["after_action"]),
        "brain_seed": _brain_seed_summary(brain_seed, source_refs["brain_seed"]),
    }
    if planning_skill_audit is not None:
        post_analysis_tab["planning_skill_audit"] = _planning_skill_audit_summary(
            planning_skill_audit,
            source_refs.get("planning_skill_audit", ""),
        )
    if planning_skill_manifest_catalog is not None:
        post_analysis_tab["planning_skill_manifest_catalog"] = (
            _planning_skill_manifest_catalog_summary(
                planning_skill_manifest_catalog,
                source_refs.get("planning_skill_manifest_catalog", ""),
            )
        )
    if capability_timeline_import is not None:
        post_analysis_tab["capability_timeline_import"] = capability_timeline_import
    if companion_match_review is not None:
        post_analysis_tab["companion_match_review"] = (
            _companion_match_review_summary(
                companion_match_review,
                source_refs.get("companion_match_review", ""),
            )
        )
    if post_analysis_energy_feedback is not None:
        post_analysis_tab["post_analysis_energy_feedback"] = (
            _post_analysis_energy_feedback_summary(
                post_analysis_energy_feedback,
                source_refs.get("post_analysis_energy_feedback", ""),
            )
        )
    if admin_surface_projection is not None:
        post_analysis_tab["admin_surface_projection"] = _admin_projection_summary(
            admin_surface_projection,
            source_refs["admin_projection"],
        )
    if debug_projection_events is not None:
        post_analysis_tab["debug_projection"] = _debug_projection_events_summary(
            debug_projection_events,
            source_refs["debug_projection_events"],
        )
    if import_manifest is not None:
        post_analysis_tab["import_manifest"] = _import_manifest_summary(
            import_manifest,
            source_refs["import_manifest"],
        )
    post_analysis_tab["sections"] = _post_analysis_sections(post_analysis_tab)
    review_workspace_tab = {
        "review_queue": planning_tab["review_queue"],
        "review_workbench": planning_tab["review_workbench"],
        "route_note_review_options": planning_tab["route_note_review_options"],
        "route_note_reviewed_assumptions": planning_tab.get(
            "route_note_reviewed_assumptions"
        ),
        "review_draft_log": planning_tab["review_draft_log"],
        "review_decision_log": planning_tab["review_decision_log"],
        "review_decision_apply_plan": planning_tab["review_decision_apply_plan"],
        "external_import_queue": planning_tab["external_import_queue"],
        "expert_contributions": planning_tab["expert_contributions"],
        "expert_contribution_apply_plan": planning_tab.get(
            "expert_contribution_apply_plan"
        ),
        "expert_contribution_workspace_apply_result": planning_tab.get(
            "expert_contribution_workspace_apply_result"
        ),
        "departure_reviewed_candidates": planning_tab.get(
            "departure_reviewed_candidates"
        ),
        "mcp_review_actions": planning_tab.get("mcp_review_actions"),
        "spatial_imprints": planning_tab.get("spatial_imprints"),
    }
    review_workspace_tab["sections"] = [
        section
        for section in planning_sections
        if section["id"] in review_workspace_section_ids
    ]
    _decorate_admin_summary_metadata(planning_tab)
    _decorate_admin_summary_metadata(post_analysis_tab)
    _decorate_admin_summary_metadata(review_workspace_tab)

    view = {
        "project_id": project_id,
        "artifacts": source_refs,
        "summary": planning_tab["summary"],
        "route": planning_tab["route"],
        "checkpoints": planning_tab["mission_candidates"]["checkpoints"],
        "segments": planning_tab["mission_candidates"]["segments"],
        "retreat_routes": planning_tab["mission_candidates"]["retreat_routes"],
        "map_candidates": planning_tab["map_candidates"],
        "readiness": planning_tab["readiness"],
        "eta": planning_tab["eta"],
        "route_notes": planning_tab["route_notes"],
        "reference_tracks": planning_tab["reference_tracks"],
        "reference_segment_timing": planning_tab["reference_segment_timing"],
        "checkpoint_events": planning_tab["checkpoint_events"],
        "layer_preparation": planning_tab["layer_preparation"],
        "terrain_visualization": planning_tab["terrain_visualization"],
        "risk_score": planning_tab["risk_score"],
        "risk_ribbon": planning_tab["risk_ribbon"],
        "risk_heatmap": planning_tab["risk_heatmap"],
        "risk_delta": planning_tab["risk_delta"],
        "overpass_evidence": planning_tab["overpass_evidence"],
        "gis_perception": planning_tab["gis_perception"],
        "gis_perception_timeline": planning_tab["gis_perception_timeline"],
        "route_note_ln_proposals": planning_tab["route_note_ln_proposals"],
        "route_note_review_options": planning_tab["route_note_review_options"],
        "route_note_reviewed_assumptions": planning_tab.get(
            "route_note_reviewed_assumptions"
        ),
        "review_queue": planning_tab["review_queue"],
        "review_workbench": planning_tab["review_workbench"],
        "review_draft_log": planning_tab["review_draft_log"],
        "review_decision_log": planning_tab["review_decision_log"],
        "review_decision_apply_plan": planning_tab["review_decision_apply_plan"],
        "external_import_queue": planning_tab["external_import_queue"],
        "expert_contributions": planning_tab["expert_contributions"],
        "expert_contribution_apply_plan": planning_tab.get(
            "expert_contribution_apply_plan"
        ),
        "expert_contribution_workspace_apply_result": planning_tab.get(
            "expert_contribution_workspace_apply_result"
        ),
        "departure_reviewed_candidates": planning_tab.get(
            "departure_reviewed_candidates"
        ),
        "major_critical_points": planning_tab.get("major_critical_points"),
        "boss_points": planning_tab.get("boss_points"),
        "mileage_tag_alignment": planning_tab.get("mileage_tag_alignment"),
        "mcp_review_actions": planning_tab.get("mcp_review_actions"),
        "spatial_imprints": planning_tab.get("spatial_imprints"),
        "departure_bundle": planning_tab["departure_bundle"],
        "resources": planning_tab["resources"],
        "weather": planning_tab["weather"],
        "cwa_qpf": planning_tab["cwa_qpf"],
        "cwa_weather": planning_tab["cwa_weather"],
        "soil_moisture": planning_tab["soil_moisture"],
        "antecedent_rain": planning_tab["antecedent_rain"],
        "environment_values": planning_tab["environment_values"],
        "environment_risk_derivative_layers": planning_tab[
            "environment_risk_derivative_layers"
        ],
        "contours": planning_tab["contours"],
        "map_layers": planning_tab["map_layers"],
        "import_manifest": post_analysis_tab.get("import_manifest"),
        "admin_surface_projection": post_analysis_tab.get("admin_surface_projection"),
        "debug_projection": post_analysis_tab.get("debug_projection"),
        "segment_terrain": post_analysis_tab["segment_terrain"],
        "planning_skill_audit": post_analysis_tab.get("planning_skill_audit"),
        "planning_skill_manifest_catalog": post_analysis_tab.get(
            "planning_skill_manifest_catalog"
        ),
        "capability_timeline_import": post_analysis_tab.get(
            "capability_timeline_import"
        ),
        "companion_match_review": post_analysis_tab.get("companion_match_review"),
        "post_analysis_energy_feedback": post_analysis_tab.get(
            "post_analysis_energy_feedback"
        ),
        "raw_sample_summary": _raw_sample_summary(pretrip_package, segment_dtm, source_refs),
        "tabs": {
            "pre_trip_planning": planning_tab,
            "post_analysis": post_analysis_tab,
            "review_workspace": review_workspace_tab,
        },
    }
    view["evidence_timeline"] = build_pretrip_evidence_timeline(view)
    view["scout_agent_skills"] = build_scout_agent_skill_summary(root=root)
    view["tabs"]["agent_skills"] = _agent_skills_tab(
        view["scout_agent_skills"],
        view["evidence_timeline"],
    )
    view["energy_reserve_monitor"] = build_energy_reserve_monitor_from_view(
        view,
        surface="pretrip",
    )
    view["tabs"]["pre_trip_planning"]["energy_reserve_monitor"] = view[
        "energy_reserve_monitor"
    ]
    return view


def resolve_pretrip_project_artifacts(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> dict[str, Path]:
    resolved_project_root = resolve_pretrip_project_root(
        project_id,
        root=root,
        project_root=project_root,
    )
    project_path = resolved_project_root / "project.json"
    project = _load_json(project_path)
    def project_ref_path(
        project_ref_key: str,
        *,
        default_ref: str | None = None,
    ) -> Path:
        ref = project.get(project_ref_key) or default_ref
        if not ref:
            ref = f"outputs/missing/{project_ref_key.removesuffix('_ref')}.json"
        return resolved_project_root / str(ref)

    artifacts = {
        "project": project_path,
        "route_summary": resolved_project_root / project["route_summary_ref"],
        "map_context": resolved_project_root / project["map_context_ref"],
        "checkpoints": project_ref_path(
            "overpass_aligned_checkpoint_candidates_ref",
            default_ref=project["checkpoint_candidates_ref"],
        ),
        "segments": project_ref_path(
            "overpass_aligned_segment_candidates_ref",
            default_ref=project["segment_candidates_ref"],
        ),
        "retreat_routes": project_ref_path("retreat_routes_ref"),
        "map_candidates": resolved_project_root / project["map_candidates_ref"],
        "package": resolved_project_root / project["package_ref"],
        "readiness": project_ref_path("readiness_report_ref"),
        "eta": project_ref_path("planned_eta_ref"),
        "route_notes": resolved_project_root / project["route_note_candidates_ref"],
        "overpass_evidence": project_ref_path("overpass_evidence_ref"),
        "overpass_map_context": project_ref_path("overpass_map_context_ref"),
        "overpass_raw_payload": project_ref_path("overpass_raw_payload_ref"),
        "route_note_ln_proposals": resolved_project_root
        / project["route_note_ln_proposals_ref"],
        "route_note_review_options": resolved_project_root
        / project["route_note_review_options_ref"],
        "route_note_reviewed_assumptions": resolved_project_root
        / ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
        "departure_reviewed_candidates": resolved_project_root
        / DEPARTURE_REVIEWED_CANDIDATES_REF,
        "review_queue": resolved_project_root / project["review_queue_manifest_ref"],
        "review_draft_log": project_ref_path("review_draft_log_ref"),
        "review_decision_log": project_ref_path("review_decision_log_ref"),
        "review_decision_apply_plan": resolved_project_root
        / str(
            project.get("review_decision_apply_plan_ref")
            or "outputs/missing/review_decision_apply_plan.json"
        ),
        "external_import_queue": project_ref_path("external_import_queue_ref"),
        "expert_contribution_log": project_ref_path("expert_contribution_log_ref"),
        "expert_contribution_apply_plan": resolved_project_root
        / EXPERT_CONTRIBUTION_APPLY_PLAN_REF,
        "expert_contribution_workspace_apply_result": resolved_project_root
        / EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF,
        "departure_bundle": project_ref_path("departure_bundle_manifest_ref"),
        "resource_plan": project_ref_path("resource_plan_ref"),
        "weather_daylight": project_ref_path("weather_daylight_evidence_ref"),
        "contour": project_ref_path("contour_interpretation_candidates_ref"),
        "remote_summary": project_ref_path("remote_contact_summary_ref"),
        "route_comparison": project_ref_path("route_comparison_ref"),
        "segment_dtm": project_ref_path("segment_dtm_coverage_ref"),
        "human_reviews": resolved_project_root / project["human_reviews_ref"],
        "runtime_handoff": project_ref_path("runtime_handoff_metadata_ref"),
        "runtime_audit": project_ref_path("runtime_audit_manifest_ref"),
        "after_action": project_ref_path("after_action_next_plan_candidates_ref"),
        "brain_seed": resolved_project_root / project["brain_seed_nodes_ref"],
    }
    for artifact_key, project_ref_key in {
        "planning_skill_audit": "planning_skill_audit_ref",
        "planning_skill_manifest_catalog": "planning_skill_manifest_catalog_ref",
        "reference_tracks": "reference_tracks_ref",
        "reference_segment_timing": "reference_segment_timing_ref",
        "reference_track_display_geometry": "reference_track_display_geometry_ref",
        "checkpoint_events": "checkpoint_events_ref",
        "segment_display_geometry": "overpass_aligned_segment_display_geometry_ref",
        "import_manifest": "import_manifest_ref",
        "layer_preparation_manifest": "layer_preparation_manifest_ref",
        "layer_preparation_job": "layer_preparation_job_ref",
        "layer_preparation_summary": "layer_preparation_summary_ref",
        "layer_adapter_manifest": "layer_adapter_manifest_ref",
        "layer_validation_report": "layer_validation_report_ref",
        "layer_map_projection": "layer_map_projection_ref",
        "layer_debug_projection_events": "layer_debug_projection_events_ref",
        "risk_route_profile": "risk_route_profile_ref",
        "risk_route_profile_metadata": "risk_route_profile_metadata_ref",
        "risk_ribbon": "risk_ribbon_ref",
        "risk_ribbon_metadata": "risk_ribbon_metadata_ref",
        "calibrated_risk_heatmap": "calibrated_risk_heatmap_ref",
        "calibrated_risk_heatmap_metadata": "calibrated_risk_heatmap_metadata_ref",
        "risk_score_points": "risk_score_points_ref",
        "risk_score_points_metadata": "risk_score_points_metadata_ref",
        "terrain_visualization": "terrain_visualization_ref",
        "cwa_weather_evidence": "cwa_weather_evidence_ref",
        "cwa_warnings_geojson": "cwa_warnings_geojson_ref",
        "cwa_observations_geojson": "cwa_observations_geojson_ref",
        "cwa_qpf_grid": "cwa_qpf_grid_ref",
        "cwa_qpf_route_timeline": "cwa_qpf_route_timeline_ref",
        "cwa_qpf_corridor_summary": "cwa_qpf_corridor_summary_ref",
        "gee_feature_package": "gee_feature_package_ref",
        "environment_risk_derivatives": "environment_risk_derivatives_ref",
        "new_landslide_candidates": "new_landslide_candidates_ref",
        "wetness_flash_flood_susceptibility": (
            "wetness_flash_flood_susceptibility_ref"
        ),
        "trail_obscurity_risk": "trail_obscurity_risk_ref",
        "practical_darkness_time": "practical_darkness_time_ref",
        "route_revalidation_report": "route_revalidation_report_ref",
        "soil_moisture_grid": "soil_moisture_grid_ref",
        "smap_l4_timeseries": "smap_l4_timeseries_ref",
        "smap_l4_corridor_summary": "smap_l4_corridor_summary_ref",
        "antecedent_rain_grid": "antecedent_rain_grid_ref",
        "gpm_imerg_timeseries": "gpm_imerg_timeseries_ref",
        "gpm_imerg_corridor_summary": "gpm_imerg_corridor_summary_ref",
        "admin_projection": "admin_projection_ref",
        "debug_projection_events": "debug_projection_events_ref",
        "gis_perception": "gis_perception_candidates_ref",
        "gis_perception_ai_judgements": "gis_perception_ai_judgements_ref",
        "mcp_named_point_evidence": "mcp_named_point_evidence_ref",
        "mcp_retrieval_plan": "mcp_retrieval_plan_ref",
        "mcp_ocr_labels": "mcp_ocr_labels_ref",
        "mcp_candidates": "overpass_aligned_mcp_candidates_ref",
        "mcp_cp_support_reconciliation": "mcp_cp_support_reconciliation_ref",
        "mcp_review_log": "mcp_review_log_ref",
        "boss_points": "boss_points_ref",
        "boss_points_geojson": "boss_points_geojson_ref",
        "mileage_tag_alignment": "mileage_tag_alignment_ref",
        "mileage_tag_alignment_geojson": "mileage_tag_alignment_geojson_ref",
        "route_pressure_profile": "route_pressure_profile_ref",
        "route_pressure_profile_geojson": "route_pressure_profile_geojson_ref",
        "spatial_imprint_candidates": "spatial_imprint_candidates_ref",
        "spatial_imprint_reviews": "spatial_imprint_reviews_ref",
        "spatial_imprint_set": "spatial_imprint_set_ref",
        "spatial_imprint_manifest": "spatial_imprint_manifest_ref",
        "local_raster_manifest": "local_raster_manifest_ref",
        "raster_tile_manifest": "raster_tile_manifest_ref",
    }.items():
        if project.get(project_ref_key):
            artifacts[artifact_key] = resolved_project_root / project[project_ref_key]
    for artifact_key, fallback_ref_key in {
        "segment_display_geometry": "segment_display_geometry_ref",
        "mcp_candidates": "mcp_candidates_ref",
    }.items():
        artifacts.setdefault(artifact_key, project_ref_path(fallback_ref_key))
    for artifact_key, default_ref in {
        "spatial_imprint_candidates": DEFAULT_SPATIAL_IMPRINT_CANDIDATES_REF,
        "spatial_imprint_reviews": DEFAULT_SPATIAL_IMPRINT_REVIEWS_REF,
        "spatial_imprint_set": DEFAULT_SPATIAL_IMPRINT_SET_REF,
        "spatial_imprint_manifest": DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF,
        "energy_projection": DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
        "companion_match_review": COMPANION_MATCH_REVIEW_REF,
        "post_analysis_energy_feedback": POST_ANALYSIS_ENERGY_FEEDBACK_REF,
        "reference_segment_timing": REFERENCE_SEGMENT_TIMING_REF,
    }.items():
        artifacts.setdefault(artifact_key, resolved_project_root / default_ref)
    return artifacts


def resolve_pretrip_project_root(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> Path:
    if project_root is None and project_id != CHILAI_NANHUA_DAY1_PROJECT_ID:
        raise KeyError(project_id)
    resolved_project_root = (
        Path(project_root)
        if project_root is not None
        else root / "tests" / "fixtures" / "pretrip" / "projects" / project_id
    )
    project_path = resolved_project_root / "project.json"
    if not project_path.exists():
        raise KeyError(project_id)
    project = _load_json(project_path)
    if project.get("project_id") != project_id:
        raise KeyError(project_id)
    return resolved_project_root


def load_pretrip_admin_surface_projection(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> dict[str, Any]:
    resolved_project_root = resolve_pretrip_project_root(
        project_id,
        root=root,
        project_root=project_root,
    )
    project = _load_json(resolved_project_root / "project.json")
    projection_ref = project.get("admin_projection_ref")
    if not projection_ref:
        return _synthetic_admin_projection_for_project(project_id, resolved_project_root)
    projection_path = resolved_project_root / projection_ref
    if not projection_path.exists():
        return _synthetic_admin_projection_for_project(project_id, resolved_project_root)
    payload = _load_json(projection_path)
    return {
        **payload,
        "source_path": projection_ref,
        "evidence_type": "pretrip_admin_surface_projection",
    }


def load_pretrip_debug_projection_events(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> dict[str, Any]:
    resolved_project_root = resolve_pretrip_project_root(
        project_id,
        root=root,
        project_root=project_root,
    )
    project = _load_json(resolved_project_root / "project.json")
    events_ref = project.get("debug_projection_events_ref")
    layer_events_ref = project.get("layer_debug_projection_events_ref")
    layer_events = _load_optional_jsonl(
        resolved_project_root / layer_events_ref if layer_events_ref else None
    ) or []
    if not events_ref:
        events = _synthetic_debug_projection_events_for_project(project_id, resolved_project_root)
        events = [*events, *layer_events]
        return {
            "artifact_kind": "pretrip_debug_projection_events",
            "project_id": project_id,
            "source_path": "project.json#synthetic-debug-projection-events",
            "layer_source_path": layer_events_ref or "",
            "evidence_type": "pretrip_debug_projection_events",
            "event_count": len(events),
            "events": events,
            "boundary": _debug_projection_boundary(events),
        }
    events_path = resolved_project_root / events_ref
    if not events_path.exists():
        events = _synthetic_debug_projection_events_for_project(project_id, resolved_project_root)
        events = [*events, *layer_events]
        return {
            "artifact_kind": "pretrip_debug_projection_events",
            "project_id": project_id,
            "source_path": "project.json#synthetic-debug-projection-events",
            "layer_source_path": layer_events_ref or "",
            "evidence_type": "pretrip_debug_projection_events",
            "event_count": len(events),
            "events": events,
            "boundary": _debug_projection_boundary(events),
        }
    events = [*_load_jsonl(events_path), *layer_events]
    return {
        "artifact_kind": "pretrip_debug_projection_events",
        "project_id": project_id,
        "source_path": events_ref,
        "layer_source_path": layer_events_ref or "",
        "evidence_type": "pretrip_debug_projection_events",
        "event_count": len(events),
        "events": events,
        "boundary": _debug_projection_boundary(events),
    }


def load_pretrip_debug_projection_view(
    project_id: str,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> dict[str, Any]:
    resolved_project_root = resolve_pretrip_project_root(
        project_id,
        root=root,
        project_root=project_root,
    )
    project = _load_json(resolved_project_root / "project.json")
    def optional_project_path(*ref_keys: str) -> Path | None:
        for ref_key in ref_keys:
            project_ref = project.get(ref_key)
            if project_ref:
                return resolved_project_root / project_ref
        return None

    route_summary = _load_json(resolved_project_root / project["route_summary_ref"])
    route_projection_bounds = _route_projection_bounds(route_summary)
    map_context = _load_json(resolved_project_root / project["map_context_ref"])
    checkpoints_path = optional_project_path(
        "overpass_aligned_checkpoint_candidates_ref",
        "checkpoint_candidates_ref",
    )
    segments_path = optional_project_path(
        "overpass_aligned_segment_candidates_ref",
        "segment_candidates_ref",
    )
    checkpoints_raw = _load_json(checkpoints_path)
    segments_raw = _load_json(segments_path)
    map_candidates_raw = _load_json(resolved_project_root / project["map_candidates_ref"])
    reference_tracks_raw = _load_optional_json(
        optional_project_path("reference_tracks_ref")
    )
    reference_segment_timing_raw = _load_optional_json(
        optional_project_path("reference_segment_timing_ref")
        or (resolved_project_root / REFERENCE_SEGMENT_TIMING_REF)
    )
    reference_track_display_geometry = _load_optional_json(
        optional_project_path("reference_track_display_geometry_ref")
    )
    route_display_bounds = _route_reference_display_bounds(
        route_summary,
        reference_tracks_raw,
        reference_track_display_geometry,
    )
    checkpoint_events_raw = _load_optional_json(
        optional_project_path("checkpoint_events_ref")
    )
    segment_display_geometry = _load_optional_json(
        optional_project_path(
            "overpass_aligned_segment_display_geometry_ref",
            "segment_display_geometry_ref",
        )
    )
    overpass_evidence_raw = _load_optional_json(
        optional_project_path("overpass_evidence_ref")
    )
    gis_perception_raw = _load_optional_json(
        optional_project_path("gis_perception_candidates_ref")
    )
    gis_perception_ai_judgements_raw = _load_optional_json(
        optional_project_path("gis_perception_ai_judgements_ref")
    )
    retreat_routes_raw = _load_optional_json(
        optional_project_path("retreat_routes_ref")
    )
    readiness_raw = _load_optional_json(
        optional_project_path("readiness_report_ref")
    )
    risk_ribbon_raw = _load_optional_json(optional_project_path("risk_ribbon_ref"))
    risk_ribbon_metadata_raw = _load_optional_json(
        optional_project_path("risk_ribbon_metadata_ref")
    )
    risk_score_points_raw = _load_optional_json(
        optional_project_path("risk_score_points_ref")
    )
    risk_score_points_metadata_raw = _load_optional_json(
        optional_project_path("risk_score_points_metadata_ref")
    )
    risk_route_profile_raw = _load_optional_json(
        optional_project_path("risk_route_profile_ref")
    )
    risk_route_profile_metadata_raw = _load_optional_json(
        optional_project_path("risk_route_profile_metadata_ref")
    )
    risk_heatmap_raw = _load_optional_json(
        optional_project_path("calibrated_risk_heatmap_ref")
    )
    risk_heatmap_metadata_raw = _load_optional_json(
        optional_project_path("calibrated_risk_heatmap_metadata_ref")
    )
    cwa_weather_evidence_raw = _load_optional_json(
        optional_project_path("cwa_weather_evidence_ref")
    )
    cwa_warnings_geojson_raw = _load_optional_json(
        optional_project_path("cwa_warnings_geojson_ref")
    )
    cwa_observations_geojson_raw = _load_optional_json(
        optional_project_path("cwa_observations_geojson_ref")
    )
    cwa_qpf_grid_raw = _load_optional_json(optional_project_path("cwa_qpf_grid_ref"))
    cwa_qpf_corridor_summary_raw = _load_optional_json(
        optional_project_path("cwa_qpf_corridor_summary_ref")
    )
    gee_feature_package_raw = _load_optional_json(
        optional_project_path("gee_feature_package_ref")
    )
    environment_risk_derivatives_raw = _load_optional_json(
        optional_project_path("environment_risk_derivatives_ref")
    )
    new_landslide_candidates_raw = _load_optional_json(
        optional_project_path("new_landslide_candidates_ref")
    )
    wetness_flash_flood_susceptibility_raw = _load_optional_json(
        optional_project_path("wetness_flash_flood_susceptibility_ref")
    )
    trail_obscurity_risk_raw = _load_optional_json(
        optional_project_path("trail_obscurity_risk_ref")
    )
    practical_darkness_time_raw = _load_optional_json(
        optional_project_path("practical_darkness_time_ref")
    )
    route_revalidation_report_raw = _load_optional_json(
        optional_project_path("route_revalidation_report_ref")
    )
    soil_moisture_grid_raw = _load_optional_json(
        optional_project_path("soil_moisture_grid_ref")
    )
    smap_l4_corridor_summary_raw = _load_optional_json(
        optional_project_path("smap_l4_corridor_summary_ref")
    )
    antecedent_rain_grid_raw = _load_optional_json(
        optional_project_path("antecedent_rain_grid_ref")
    )
    gpm_imerg_corridor_summary_raw = _load_optional_json(
        optional_project_path("gpm_imerg_corridor_summary_ref")
    )
    terrain_visualization_raw = _load_optional_json(
        optional_project_path("terrain_visualization_ref")
    )
    segment_dtm_raw = _load_optional_json(optional_project_path("segment_dtm_coverage_ref"))
    mcp_named_point_evidence_raw = _load_optional_json(
        optional_project_path("mcp_named_point_evidence_ref")
    )
    mcp_retrieval_plan_raw = _load_optional_json(
        optional_project_path("mcp_retrieval_plan_ref")
    )
    mcp_ocr_labels_raw = _load_optional_json(optional_project_path("mcp_ocr_labels_ref"))
    mcp_candidates_raw = _load_optional_json(
        optional_project_path("overpass_aligned_mcp_candidates_ref", "mcp_candidates_ref")
    )
    mcp_cp_support_reconciliation_raw = _load_optional_json(
        optional_project_path("mcp_cp_support_reconciliation_ref")
    )
    mcp_review_log_raw = _load_optional_json(optional_project_path("mcp_review_log_ref"))
    boss_points_raw = _load_optional_json(optional_project_path("boss_points_ref"))
    boss_points_geojson_raw = _load_optional_json(
        optional_project_path("boss_points_geojson_ref")
    )
    mileage_tag_alignment_raw = _load_optional_json(
        optional_project_path("mileage_tag_alignment_ref")
    )
    mileage_tag_alignment_geojson_raw = _load_optional_json(
        optional_project_path("mileage_tag_alignment_geojson_ref")
    )
    physiologic_timeline_projection = _physiologic_timeline_projection_summary(
        project_id,
        project,
        project_root=resolved_project_root,
    )
    runtime_safety_reducer_projection = _runtime_safety_reducer_projection_summary(
        project_id,
        project,
        project_root=resolved_project_root,
    )
    source_refs = {
        "project": "project.json",
        "route_summary": project["route_summary_ref"],
        "map_context": project["map_context_ref"],
        "checkpoints": project.get(
            "overpass_aligned_checkpoint_candidates_ref",
            project["checkpoint_candidates_ref"],
        ),
        "segments": project.get(
            "overpass_aligned_segment_candidates_ref",
            project["segment_candidates_ref"],
        ),
        "map_candidates": project["map_candidates_ref"],
        "reference_tracks": project.get("reference_tracks_ref", ""),
        "reference_segment_timing": project.get(
            "reference_segment_timing_ref",
            REFERENCE_SEGMENT_TIMING_REF,
        ),
        "reference_track_display_geometry": project.get(
            "reference_track_display_geometry_ref",
            "",
        ),
        "checkpoint_events": project.get("checkpoint_events_ref", ""),
        "segment_display_geometry": project.get(
            "overpass_aligned_segment_display_geometry_ref",
            project.get("segment_display_geometry_ref", ""),
        ),
        "overpass_evidence": project.get("overpass_evidence_ref", ""),
        "retreat_routes": project.get("retreat_routes_ref", ""),
        "readiness": project.get("readiness_report_ref", ""),
        "segment_dtm": project.get("segment_dtm_coverage_ref", ""),
        "route_notes": project.get("route_note_candidates_ref", ""),
        "risk_route_profile": project.get("risk_route_profile_ref", ""),
        "risk_route_profile_metadata": project.get("risk_route_profile_metadata_ref", ""),
        "risk_score_points": project.get("risk_score_points_ref", ""),
        "risk_score_points_metadata": project.get("risk_score_points_metadata_ref", ""),
        "terrain_visualization": project.get("terrain_visualization_ref", ""),
        "risk_ribbon": project.get("risk_ribbon_ref", ""),
        "risk_ribbon_metadata": project.get("risk_ribbon_metadata_ref", ""),
        "calibrated_risk_heatmap": project.get("calibrated_risk_heatmap_ref", ""),
        "calibrated_risk_heatmap_metadata": project.get(
            "calibrated_risk_heatmap_metadata_ref",
            "",
        ),
        "gis_perception": project.get("gis_perception_candidates_ref", ""),
        "gis_perception_ai_judgements": project.get(
            "gis_perception_ai_judgements_ref",
            "",
        ),
        "mcp_named_point_evidence": project.get("mcp_named_point_evidence_ref", ""),
        "mcp_retrieval_plan": project.get("mcp_retrieval_plan_ref", ""),
        "mcp_ocr_labels": project.get("mcp_ocr_labels_ref", ""),
        "mcp_candidates": project.get(
            "overpass_aligned_mcp_candidates_ref",
            project.get("mcp_candidates_ref", ""),
        ),
        "mcp_cp_support_reconciliation": project.get(
            "mcp_cp_support_reconciliation_ref",
            "",
        ),
        "mcp_review_log": project.get("mcp_review_log_ref", ""),
        "boss_points": project.get("boss_points_ref", ""),
        "boss_points_geojson": project.get("boss_points_geojson_ref", ""),
        "mileage_tag_alignment": project.get("mileage_tag_alignment_ref", ""),
        "mileage_tag_alignment_geojson": project.get(
            "mileage_tag_alignment_geojson_ref",
            "",
        ),
        "physiologic_timeline_projection": project.get(
            "physiologic_timeline_projection_ref",
            "",
        ),
        "physiologic_artifact_index": project.get("physiologic_artifact_index_ref", ""),
        "physiologic_artifact_dir": project.get("physiologic_artifact_dir_ref", ""),
        "runtime_safety_gate_event_batch": project.get(
            "runtime_safety_gate_event_batch_ref",
            "",
        ),
        "runtime_safety_reducer_dry_run": project.get(
            "runtime_safety_reducer_dry_run_ref",
            "",
        ),
        "runtime_safety_phase1_adapter": project.get(
            "runtime_safety_phase1_adapter_ref",
            "",
        ),
        "weather_daylight": project.get("weather_daylight_evidence_ref", ""),
        "cwa_weather_evidence": project.get("cwa_weather_evidence_ref", ""),
        "cwa_warnings_geojson": project.get("cwa_warnings_geojson_ref", ""),
        "cwa_observations_geojson": project.get("cwa_observations_geojson_ref", ""),
        "cwa_qpf_grid": project.get("cwa_qpf_grid_ref", ""),
        "cwa_qpf_corridor_summary": project.get("cwa_qpf_corridor_summary_ref", ""),
        "gee_feature_package": project.get("gee_feature_package_ref", ""),
        "environment_risk_derivatives": project.get(
            "environment_risk_derivatives_ref",
            "",
        ),
        "new_landslide_candidates": project.get("new_landslide_candidates_ref", ""),
        "wetness_flash_flood_susceptibility": project.get(
            "wetness_flash_flood_susceptibility_ref",
            "",
        ),
        "trail_obscurity_risk": project.get("trail_obscurity_risk_ref", ""),
        "practical_darkness_time": project.get("practical_darkness_time_ref", ""),
        "route_revalidation_report": project.get("route_revalidation_report_ref", ""),
        "soil_moisture_grid": project.get("soil_moisture_grid_ref", ""),
        "smap_l4_corridor_summary": project.get("smap_l4_corridor_summary_ref", ""),
        "antecedent_rain_grid": project.get("antecedent_rain_grid_ref", ""),
        "gpm_imerg_corridor_summary": project.get(
            "gpm_imerg_corridor_summary_ref",
            "",
        ),
    }
    checkpoints = _candidate_list(
        checkpoints_raw,
        source_path=source_refs["checkpoints"],
        evidence_type="pretrip_checkpoint_candidate",
    )
    segments = _candidate_list(
        segments_raw,
        source_path=source_refs["segments"],
        evidence_type="pretrip_segment_candidate",
        display_geometry=_segment_display_geometry_by_id(segment_display_geometry),
    )
    route_display_geometry = _route_display_geometry_from_segments(
        project_id,
        segments,
    )
    route_centerline_geometry = _route_display_geometry_from_risk_ribbon(
        project_id=project_id,
        payload=risk_ribbon_raw,
        source_path=source_refs.get("risk_ribbon", ""),
    ) or route_display_geometry
    view = {
        "project_id": project_id,
        "route": {
            "source_id": route_summary["artifact_id"],
            "source_path": source_refs["route_summary"],
            "evidence_type": "pretrip_route_summary",
            "route_name": route_summary["route_name"],
            "bounds": route_summary["bbox_wgs84"],
            "display_bounds": (
                route_display_bounds["bounds_wgs84"]
                if route_display_bounds is not None
                else None
            ),
            "display_bounds_metadata": route_display_bounds,
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "elevation_min_m": route_summary.get("elevation_min_m"),
            "elevation_max_m": route_summary.get("elevation_max_m"),
            "started_at": route_summary.get("started_at"),
            "ended_at": route_summary.get("ended_at"),
            "polyline": _route_polyline(map_context),
            "display_geometry": route_display_geometry,
        },
        "checkpoints": checkpoints,
        "segments": segments,
        "retreat_routes": _candidate_list(
            retreat_routes_raw or [],
            source_path=source_refs["retreat_routes"],
            evidence_type="pretrip_retreat_route_candidate",
        ),
        "map_candidates": _map_candidate_summary(
            map_candidates_raw,
            source_refs["map_candidates"],
        ),
        "overpass_evidence": _debug_projection_overpass_summary(
            project_id,
            overpass_evidence_raw,
            source_refs["overpass_evidence"],
        ),
        "gis_perception": _debug_projection_gis_perception_summary(
            project_id,
            gis_perception_raw,
            source_refs["gis_perception"],
            ai_judgements_payload=gis_perception_ai_judgements_raw,
            ai_judgements_source_path=source_refs["gis_perception_ai_judgements"],
            display_bounds=route_projection_bounds,
        ),
        "reference_tracks": _reference_tracks_summary(
            reference_tracks_raw,
            source_refs["reference_tracks"],
            display_geometry=reference_track_display_geometry,
            display_source_path=source_refs["reference_track_display_geometry"],
        )
        if reference_tracks_raw is not None
        else _empty_reference_tracks(project_id, source_refs["reference_tracks"]),
        "reference_segment_timing": _reference_segment_timing_summary(
            reference_segment_timing_raw,
            source_refs["reference_segment_timing"],
            project_id=project_id,
            route_segments=segments,
        ),
        "checkpoint_events": _checkpoint_events_summary(
            checkpoint_events_raw,
            source_refs["checkpoint_events"],
        )
        if checkpoint_events_raw is not None
        else _empty_checkpoint_events(project_id, source_refs["checkpoint_events"]),
        "risk_score": _risk_score_summary(
            project_id,
            risk_score_points_raw,
            risk_score_points_metadata_raw,
            risk_route_profile_raw,
            risk_route_profile_metadata_raw,
            source_path=source_refs["risk_score_points"],
            metadata_source_path=source_refs["risk_score_points_metadata"],
            route_source_path=source_refs["risk_route_profile"],
            route_metadata_source_path=source_refs["risk_route_profile_metadata"],
        ),
        "terrain_visualization": _terrain_visualization_summary(
            project_id,
            terrain_visualization_raw,
            source_refs["terrain_visualization"],
        ),
        "segment_terrain": _segment_terrain_summary(
            segment_dtm_raw,
            source_refs["segment_dtm"],
        ),
        "risk_ribbon": _risk_ribbon_summary(
            project_id,
            risk_ribbon_raw,
            risk_ribbon_metadata_raw,
            source_path=source_refs["risk_ribbon"],
            metadata_source_path=source_refs["risk_ribbon_metadata"],
        ),
        "risk_heatmap": _risk_heatmap_summary(
            project_id,
            risk_heatmap_raw,
            risk_heatmap_metadata_raw,
            source_path=source_refs["calibrated_risk_heatmap"],
            metadata_source_path=source_refs["calibrated_risk_heatmap_metadata"],
        ),
        "map_layers": build_pretrip_map_layers(
            source_refs=source_refs,
            weather={
                "source_id": "pretrip.map_layer.weather_api",
                "source_path": source_refs["weather_daylight"],
                "external_api_calls_made": False,
            },
        ),
        "cwa_qpf": _environment_geojson_summary(
            project_id,
            cwa_qpf_grid_raw,
            source_path=source_refs.get("cwa_qpf_grid", ""),
            layer_id="cwa-qpf",
            evidence_type="cwa_forecast_derived_qpf_candidate",
            summary_payload=cwa_qpf_corridor_summary_raw,
            summary_source_path=source_refs.get("cwa_qpf_corridor_summary", ""),
        ),
        "cwa_weather": _cwa_weather_environment_summary(
            project_id,
            evidence_payload=cwa_weather_evidence_raw,
            warnings_geojson=cwa_warnings_geojson_raw,
            observations_geojson=cwa_observations_geojson_raw,
            source_refs=source_refs,
        ),
        "soil_moisture": _environment_geojson_summary(
            project_id,
            soil_moisture_grid_raw,
            source_path=source_refs.get("soil_moisture_grid", ""),
            layer_id="soil-moisture",
            evidence_type="gee_soil_moisture_candidate",
            summary_payload=smap_l4_corridor_summary_raw,
            summary_source_path=source_refs.get("smap_l4_corridor_summary", ""),
        ),
        "antecedent_rain": _environment_geojson_summary(
            project_id,
            antecedent_rain_grid_raw,
            source_path=source_refs.get("antecedent_rain_grid", ""),
            layer_id="antecedent-rain",
            evidence_type="gee_antecedent_rain_candidate",
            summary_payload=gpm_imerg_corridor_summary_raw,
            summary_source_path=source_refs.get("gpm_imerg_corridor_summary", ""),
        ),
        "readiness": _summary_with_source(
            readiness_raw or {"status": "unknown", "findings": []},
            source_id=f"readiness.{project_id}",
            source_path=source_refs["readiness"],
            evidence_type="pretrip_readiness_report",
            include_keys=("status", "findings"),
        ),
    }
    view["environment_values"] = _environment_values_summary(
        project_id,
        source_refs=source_refs,
        cwa_qpf=view["cwa_qpf"],
        cwa_weather=view["cwa_weather"],
        soil_moisture=view["soil_moisture"],
        antecedent_rain=view["antecedent_rain"],
        gee_feature_package=gee_feature_package_raw,
        environment_risk_derivatives=environment_risk_derivatives_raw,
    )
    view["environment_risk_derivative_layers"] = (
        _environment_risk_derivative_layers_summary(
            project_id,
            source_refs=source_refs,
            environment_risk_derivatives=environment_risk_derivatives_raw,
            new_landslide_candidates=new_landslide_candidates_raw,
            wetness_flash_flood_susceptibility=wetness_flash_flood_susceptibility_raw,
            trail_obscurity_risk=trail_obscurity_risk_raw,
            practical_darkness_time=practical_darkness_time_raw,
            route_revalidation_report=route_revalidation_report_raw,
        )
    )
    view["map_layers"] = _map_layers_with_local_raster_metadata(
        view["map_layers"],
        project=project,
        local_raster_manifest=_load_optional_json(
            optional_project_path("local_raster_manifest_ref")
        ),
        raster_tile_manifest=_load_optional_json(
            optional_project_path("raster_tile_manifest_ref")
        ),
        raster_layer_manifests=_raster_layer_manifest_summaries(
            resolved_project_root,
            project,
        ),
        local_raster_source_path=project.get("local_raster_manifest_ref", ""),
        raster_tile_source_path=project.get("raster_tile_manifest_ref", ""),
    )
    if mcp_candidates_raw is not None:
        view["major_critical_points"] = _mcp_summary(
            project_id=project_id,
            mcp_candidates=mcp_candidates_raw,
            named_point_evidence=mcp_named_point_evidence_raw,
            retrieval_plan=mcp_retrieval_plan_raw,
            ocr_labels=mcp_ocr_labels_raw,
            cp_support_reconciliation=mcp_cp_support_reconciliation_raw,
            review_log=mcp_review_log_raw,
            source_refs=source_refs,
        )
    if boss_points_raw is not None:
        view["boss_points"] = _boss_points_summary(
            boss_points_raw,
            boss_points_geojson_raw,
            source_refs=source_refs,
            route_display_geometry=route_centerline_geometry,
            route_bounds=route_projection_bounds,
        )
    if mileage_tag_alignment_raw is not None:
        view["mileage_tag_alignment"] = _mileage_tag_alignment_summary(
            mileage_tag_alignment_raw,
            mileage_tag_alignment_geojson_raw,
            source_refs=source_refs,
        )
    view["physiologic_timeline_projection"] = physiologic_timeline_projection
    view["runtime_safety_reducer_projection"] = runtime_safety_reducer_projection
    view["gis_perception_timeline"] = _gis_perception_timeline_summary(
        project_id,
        view["gis_perception"],
        overpass_evidence=view["overpass_evidence"],
    )
    view["risk_delta"] = _risk_delta_summary(
        project_id,
        view["risk_ribbon"],
        view["risk_heatmap"],
    )
    lifecycle_events = load_pretrip_debug_projection_events(
        project_id,
        root=root,
        project_root=resolved_project_root,
    )
    timeline_events = _debug_projection_timeline_events(
        view,
        lifecycle_events.get("events", []),
    )
    return {
        "artifact_kind": "pretrip_debug_projection",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "source_path": "project.json#debug-projection-view",
        "evidence_type": "pretrip_debug_projection_view",
        "surface_targets": ["/admin/debug"],
        "projection_only": True,
        "route": {
            **view["route"],
        },
        "checkpoints": view["checkpoints"],
        "segments": view["segments"],
        "retreat_routes": view["retreat_routes"],
        "map_candidates": view["map_candidates"],
        "overpass_evidence": view["overpass_evidence"],
        "gis_perception": view["gis_perception"],
        "gis_perception_timeline": view["gis_perception_timeline"],
        "reference_tracks": view["reference_tracks"],
        "reference_segment_timing": view["reference_segment_timing"],
        "checkpoint_events": view["checkpoint_events"],
        "risk_score": view["risk_score"],
        "terrain_visualization": view["terrain_visualization"],
        "segment_terrain": view["segment_terrain"],
        "risk_ribbon": view["risk_ribbon"],
        "risk_heatmap": view["risk_heatmap"],
        "risk_delta": view["risk_delta"],
        "cwa_qpf": view["cwa_qpf"],
        "cwa_weather": view["cwa_weather"],
        "soil_moisture": view["soil_moisture"],
        "antecedent_rain": view["antecedent_rain"],
        "environment_values": view["environment_values"],
        "environment_risk_derivative_layers": view[
            "environment_risk_derivative_layers"
        ],
        "major_critical_points": view.get("major_critical_points"),
        "boss_points": view.get("boss_points"),
        "mileage_tag_alignment": view.get("mileage_tag_alignment"),
        "physiologic_timeline_projection": view[
            "physiologic_timeline_projection"
        ],
        "runtime_safety_reducer_projection": view[
            "runtime_safety_reducer_projection"
        ],
        "map_layers": view["map_layers"],
        "readiness": view["readiness"],
        "timeline_events": timeline_events,
        "event_count": len(timeline_events),
        "source_debug_projection_events": lifecycle_events,
        "counts": {
            "route_point_count": view["route"]["point_count"],
            "checkpoint_candidate_count": len(view["checkpoints"]),
            "segment_candidate_count": len(view["segments"]),
            "reference_track_count": view["reference_tracks"].get(
                "reference_track_count",
                0,
            ),
            "reference_segment_timing_segment_count": view[
                "reference_segment_timing"
            ]["counts"].get("usable_segment_count", 0),
            "reference_segment_timing_measurement_count": view[
                "reference_segment_timing"
            ]["counts"].get("measurement_count", 0),
            "gis_perception_checkpoint_candidate_count": view[
                "gis_perception"
            ]["counts"].get("checkpoint_candidate_count", 0),
            "gis_perception_timeline_checkpoint_count": view[
                "gis_perception_timeline"
            ]["counts"].get("checkpoint_candidate_count", 0),
            "risk_ribbon_segment_count": view["risk_ribbon"]["counts"].get(
                "segment_count",
                0,
            ),
            "risk_heatmap_segment_count": view["risk_heatmap"]["counts"].get(
                "segment_count",
                0,
            ),
            "risk_delta_segment_count": view["risk_delta"]["counts"].get(
                "segment_count",
                0,
            ),
            "cwa_qpf_point_count": view["cwa_qpf"]["counts"].get(
                "point_count",
                0,
            ),
            "cwa_weather_point_count": view["cwa_weather"]["counts"].get(
                "point_count",
                0,
            ),
            "soil_moisture_point_count": view["soil_moisture"]["counts"].get(
                "point_count",
                0,
            ),
            "antecedent_rain_point_count": view["antecedent_rain"]["counts"].get(
                "point_count",
                0,
            ),
            "environment_value_item_count": view["environment_values"]["counts"].get(
                "item_count",
                0,
            ),
            "environment_risk_derivative_candidate_count": view[
                "environment_risk_derivative_layers"
            ]["counts"].get(
                "total_candidate_count",
                0,
            ),
            "gee_feature_package_segment_count": view["environment_values"][
                "counts"
            ].get(
                "gee_segment_count",
                0,
            ),
            "terrain_bitmap_overlay_count": view["terrain_visualization"]["counts"].get(
                "bitmap_overlay_count",
                0,
            ),
            "terrain_source_dtm_tile_count": view["terrain_visualization"]["counts"].get(
                "source_dtm_tile_count",
                0,
            ),
            "terrain_source_dtm_grid_cell_count": view["terrain_visualization"][
                "counts"
            ].get(
                "source_dtm_grid_cell_count",
                0,
            ),
            "terrain_sample_count": view["terrain_visualization"]["counts"].get(
                "cell_count",
                0,
            ),
            "segment_terrain_segment_count": view["segment_terrain"].get(
                "segment_count",
                0,
            ),
            "mcp_candidate_count": (
                view.get("major_critical_points", {})
                .get("counts", {})
                .get("mcp_candidate_count", 0)
            ),
            "mcp_suppressed_point_count": (
                view.get("major_critical_points", {})
                .get("counts", {})
                .get("suppressed_point_count", 0)
            ),
            "mcp_review_action_count": (
                view.get("major_critical_points", {})
                .get("counts", {})
                .get("review_action_count", 0)
            ),
            "boss_point_count": (
                view.get("boss_points", {})
                .get("counts", {})
                .get("boss_point_count", 0)
            ),
            "mileage_tag_count": (
                view.get("mileage_tag_alignment", {})
                .get("counts", {})
                .get("tag_count", 0)
            ),
            "mileage_tag_aligned_count": (
                view.get("mileage_tag_alignment", {})
                .get("counts", {})
                .get("aligned_tag_count", 0)
            ),
            "physiologic_timeline_event_count": view[
                "physiologic_timeline_projection"
            ].get("event_count", 0),
            "runtime_safety_reducer_event_count": view[
                "runtime_safety_reducer_projection"
            ].get("event_count", 0),
            "timeline_event_count": len(timeline_events),
            "source_lifecycle_event_count": lifecycle_events.get("event_count", 0),
        },
        "boundary": {
            **_debug_projection_boundary(lifecycle_events.get("events", [])),
            "projection_only": True,
            "golden_route_is_reference_evidence": True,
            "runtime_safety_truth": False,
            "candidate_only": True,
            "source_lifecycle_events_preserved": True,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "incident_store_mutation_allowed": False,
            "real_outbound_transport_allowed": False,
            "mission_graph_compiled": False,
        },
    }


def _synthetic_admin_projection_for_project(
    project_id: str,
    project_root: Path,
) -> dict[str, Any]:
    route_summary = _load_json(project_root / "normalized" / "routes" / "route_summary.json")
    checkpoints = _load_json(project_root / "candidates" / "checkpoints.json")
    segments = _load_json(project_root / "candidates" / "segments.json")
    reference_tracks = _load_optional_json(project_root / "outputs" / "reference_tracks.json")
    payload = {
        "artifact_kind": "pretrip_admin_surface_projection",
        "schema_version": "0.1.0",
        "project_id": project_id,
        "surface_targets": ["/admin", "/admin/pretrip", "/admin/debug"],
        "projection_only": True,
        "import_stage": "pretrip",
        "route": {
            "route_role": "golden_route_reference",
            "route_name": route_summary["route_name"],
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "bbox_wgs84": route_summary["bbox_wgs84"],
            "route_summary_ref": "normalized/routes/route_summary.json",
            "map_context_ref": "normalized/map/map_context.geojson",
        },
        "candidate_counts": {
            "checkpoint_candidate_count": len(checkpoints),
            "segment_candidate_count": len(segments),
            "reference_track_count": (
                reference_tracks or {}
            ).get("reference_track_count", 0),
        },
        "pretrip_surface": {
            "project_ref": "project.json",
            "package_ref": "outputs/pretrip_package.json",
        },
        "after_action_surface": {
            "after_action_style_projection": True,
            "completed_mission_replay": False,
            "incident_package_source": False,
            "pretrip_actual_user_track_available": False,
            "pretrip_golden_route_replacement_expected_after_return": True,
        },
        "debug_surface": {
            "debug_projection_events_ref": "project.json#synthetic-debug-projection-events",
            "file_runtime_debug_log_compatible": True,
            "live_runtime_events": False,
        },
        "boundary": {
            "projection_only": True,
            "golden_route_is_reference_evidence": True,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "incident_store_mutation_allowed": False,
            "real_outbound_transport_allowed": False,
            "mission_graph_compiled": False,
        },
    }
    return {
        **payload,
        "source_path": "project.json#synthetic-admin-projection",
        "evidence_type": "pretrip_admin_surface_projection",
    }


def _synthetic_debug_projection_events_for_project(
    project_id: str,
    project_root: Path,
) -> list[dict[str, Any]]:
    route_summary = _load_json(project_root / "normalized" / "routes" / "route_summary.json")
    checkpoints = _load_json(project_root / "candidates" / "checkpoints.json")
    segments = _load_json(project_root / "candidates" / "segments.json")
    reference_tracks = _load_optional_json(project_root / "outputs" / "reference_tracks.json")
    boundary = {
        "projection_only": True,
        "golden_route_is_reference_evidence": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "mission_graph_compiled": False,
    }
    base_payload = {
        "project_id": project_id,
        "profile": "pi-offline",
        "import_stage": "pretrip",
        "route_role": "golden_route_reference",
        "projection_only": True,
        "boundary": boundary,
    }
    event_specs = [
        ("debug_session_started", "Pretrip GPX projection started.", {}),
        (
            "provider_status_recorded",
            "Local GPX corpus projection sources were inspected.",
            {
                "provider": "local_gpx_corpus",
                "golden_route_count": 1,
                "reference_track_count": (
                    reference_tracks or {}
                ).get("reference_track_count", 0),
                "network_calls_allowed": False,
            },
        ),
        (
            "progress_update_recorded",
            "Pretrip route candidates were generated from the GPX set.",
            {
                "route_point_count": route_summary["point_count"],
                "distance_m": route_summary["distance_m"],
                "checkpoint_candidate_count": len(checkpoints),
                "segment_candidate_count": len(segments),
            },
        ),
        (
            "debug_session_completed",
            "Pretrip GPX projection completed without runtime mutation.",
            {
                "safety_level": "L0_NORMAL",
                "observations_processed": route_summary["point_count"],
                "mission_graph_compiled": False,
                "actual_user_track_available": False,
            },
        ),
    ]
    return [
        {
            "event_id": f"debug_event.pretrip_import.{project_id}.{index:06d}",
            "session_id": f"debug_session.pretrip_import.{project_id}",
            "mission_id": None,
            "timestamp": "2026-05-21T00:00:00+00:00",
            "sequence": index,
            "kind": kind,
            "source": "pretrip_import",
            "phase": "phase35",
            "severity": "info",
            "subject_ref": project_id,
            "correlation_refs": [f"artifact.gpx.{project_id}"],
            "summary": summary,
            "payload": {**base_payload, **payload},
        }
        for index, (kind, summary, payload) in enumerate(event_specs, start=1)
    ]


def _route_display_geometry_from_segments(
    project_id: str,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    coordinate_segments: list[list[dict[str, float]]] = []
    for segment in segments:
        display_geometry = segment.get("display_geometry")
        if not isinstance(display_geometry, dict):
            continue
        coordinate_segments.extend(
            _display_geometry_coordinate_segments(display_geometry)
        )
    coordinates = [
        point
        for coordinate_segment in coordinate_segments
        for point in coordinate_segment
    ]
    return {
        "source_id": f"route_display_geometry.{project_id}",
        "source_path": "outputs/segment_display_geometry.json",
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


def _route_display_geometry_from_risk_ribbon(
    *,
    project_id: str,
    payload: dict[str, Any] | None,
    source_path: str,
) -> dict[str, Any] | None:
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return None
    coordinate_segments: list[list[dict[str, float]]] = []
    route_segments: list[dict[str, Any]] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            continue
        coordinates = _geojson_line_coordinates(geometry)
        if len(coordinates) < 2:
            continue
        properties = feature.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        segment_id = (
            properties.get("segment_id")
            or properties.get("candidate_id")
            or f"risk_ribbon.{index:04d}"
        )
        segment_record = {
            "candidate_id": segment_id,
            "segment_candidate_id": segment_id,
            "start_distance_m": _coerce_float(properties.get("start_distance_m")),
            "end_distance_m": _coerce_float(properties.get("end_distance_m")),
            "coordinates": coordinates,
            "risk_distance_axis": properties.get("risk_distance_axis")
            or "overpass_risk_ribbon_distance",
        }
        segment_record.update(
            _projection_record_metadata(
                {
                    **segment_record,
                    "source_refs": [source_path or "outputs/risk_ribbon.geojson"],
                },
                source_path=source_path or "outputs/risk_ribbon.geojson",
                evidence_type="pretrip_overpass_risk_ribbon_route_segment",
                source_kind="risk_ribbon_route_display_geometry",
                identity_keys=("candidate_id", "segment_candidate_id"),
                confidence="medium",
                stale_risk="medium",
                review_state="projection_only",
                extractor_version="pretrip_admin_view.risk_ribbon_route_display.v1",
                prompt_version=(
                    "not_applicable_deterministic_risk_ribbon_projection.v1"
                ),
                summary=(
                    "Risk-ribbon centerline display segment projected for "
                    "pretrip map focus; candidate-only evidence, not runtime "
                    "safety truth."
                ),
            )
        )
        coordinate_segments.append(coordinates)
        route_segments.append(segment_record)
    coordinates = [point for segment in coordinate_segments for point in segment]
    if not coordinates:
        return None
    return {
        "source_id": f"route_pressure_centerline.{project_id}",
        "source_path": source_path or "outputs/risk_ribbon.geojson",
        "evidence_type": "pretrip_overpass_risk_ribbon_centerline",
        "display_point_count": len(coordinates),
        "display_segment_count": len(coordinate_segments),
        "coordinates": coordinates,
        "coordinate_segments": coordinate_segments,
        "route_segments": route_segments,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "centerline_source": "overpass_risk_ribbon",
            "internal_gpx_points_preserved": True,
            "gpx_segment_boundary_preserved": True,
            "overpass_centerline_preserved": True,
            "gpx_used_as_timing_and_behavior_evidence_only": True,
        },
    }


def _debug_projection_overpass_summary(
    project_id: str,
    payload: dict[str, Any] | None,
    source_path: str,
) -> dict[str, Any]:
    if payload is not None:
        return _overpass_evidence_summary(payload, source_path)
    return {
        "source_id": f"overpass_evidence.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_overpass_vector_evidence",
        "status": "not_available",
        "counts": {"candidates": 0, "skipped": 0},
        "boundary": {
            "candidate_only": True,
            "runtime_truth": False,
            "live_network_required": False,
        },
        "request": {},
        "source_artifact": {},
        "normalized_geojson_ref": "",
        "raw_response_sha256": "",
        "conversion_rule_version": "",
        "corridor_candidates": [],
        "hazard_candidates": [],
        "poi_candidates": [],
        "skipped_objects": [],
    }


def _debug_projection_gis_perception_summary(
    project_id: str,
    payload: dict[str, Any] | None,
    source_path: str,
    *,
    ai_judgements_payload: dict[str, Any] | None = None,
    ai_judgements_source_path: str = "",
    display_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    ai_judgement_summary = _gis_perception_ai_judgement_summary(
        ai_judgements_payload,
        ai_judgements_source_path,
    )
    if payload is None:
        return {
            "source_id": f"gis_perception.{project_id}",
            "source_path": source_path,
            "evidence_type": "pretrip_gis_perception_candidates",
            "status": "not_available",
            "source_profile": "gpx_corpus_route_notes",
            "counts": {"checkpoint_candidate_count": 0},
            "boundary": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
            },
            "ai_judgements": ai_judgement_summary,
            "checkpoint_candidates": [],
        }
    checkpoint_candidates = []
    for candidate in payload.get("checkpoint_candidates", []):
        display_label = _gis_perception_candidate_display_label(candidate)
        checkpoint_candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "source_id": candidate["candidate_id"],
                "source_path": source_path,
                "evidence_type": "pretrip_gis_perception_checkpoint_candidate",
                "checkpoint_type": candidate["checkpoint_type"],
                "lat": candidate["lat"],
                "lon": candidate["lon"],
                "source_route_note_candidate_id": candidate[
                    "source_route_note_candidate_id"
                ],
                "source_gpx_role": candidate["source_gpx_role"],
                "source_note_category": candidate["source_note_category"],
                "route_note_age_days": candidate.get("route_note_age_days"),
                "route_note_freshness": candidate.get(
                    "route_note_freshness",
                    "unknown",
                ),
                "stale_route_note": candidate.get("stale_route_note", False),
                "ai_source_signals": candidate.get("ai_source_signals", []),
                "linked_ln_proposal_id": candidate.get("linked_ln_proposal_id"),
                "proposed_ln_scope": candidate["proposed_ln_scope"],
                "route_note_summary": candidate["route_note_summary"],
                "display_label": display_label,
                "map_label": display_label,
                "source_attribution": candidate.get("source_attribution", []),
                "human_review_required": candidate["human_review_required"],
                **_gis_perception_candidate_provenance(
                    candidate,
                    source_path=source_path,
                    classifier=payload.get("classifier", {}),
                    evidence_type="pretrip_gis_perception_checkpoint_candidate",
                ),
            }
        )
    visible_checkpoint_candidates = [
        candidate
        for candidate in checkpoint_candidates
        if _point_within_projection_bounds(candidate, display_bounds)
    ]
    projection_filter = _projection_filter_summary(
        source_count=len(checkpoint_candidates),
        visible_count=len(visible_checkpoint_candidates),
        display_bounds=display_bounds,
    )
    counts = {
        **payload["counts"],
        "visible_checkpoint_candidate_count": len(visible_checkpoint_candidates),
        "filtered_out_of_route_bounds_count": projection_filter[
            "filtered_out_of_route_bounds_count"
        ],
    }
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_gis_perception_candidates",
        "status": payload["status"],
        "source_profile": payload["source_profile"],
        "counts": counts,
        "classifier": payload["classifier"],
        "boundary": _summary_boundary(payload["boundary"]),
        "ai_judgements": ai_judgement_summary,
        "projection_filter": projection_filter,
        "checkpoint_candidates": visible_checkpoint_candidates,
    }


def _gis_perception_ai_judgement_summary(
    payload: dict[str, Any] | None,
    source_path: str,
) -> dict[str, Any]:
    if payload is None:
        unavailable_ref = source_path or "outputs/gis_perception_ai_judgements.json"
        return {
            "source_id": "pretrip_gis_perception_ai_judgements.not_available",
            "source_path": source_path,
            "evidence_type": "pretrip_gis_perception_ai_judgements",
            "status": "not_available",
            **_projection_record_metadata(
                {
                    "candidate_id": "gis_perception_ai_judgements.not_available",
                    "source_refs": [unavailable_ref],
                },
                source_path=unavailable_ref,
                evidence_type="pretrip_gis_perception_ai_judgements",
                source_kind="gis_perception_ai_judgements",
                identity_keys=("candidate_id", "source_refs"),
                review_state="not_available",
                confidence="low",
                stale_risk="unknown",
                extractor_version="pretrip_gis_perception_ai_judgement.projection.v1",
                prompt_version="scout.gis_perception.structured_judgement.v0",
                summary=(
                    "GIS perception AI judgement summary is unavailable; no "
                    "runtime safety truth or Brain writeback is produced."
                ),
            ),
            "judgement_count": 0,
            "source_ref_count": 0,
            "source_refs": [unavailable_ref],
            "counts": {
                "input_count": 0,
                "judgement_count": 0,
                "source_ref_count": 0,
                "candidate_only_count": 0,
                "human_review_required_count": 0,
                "runtime_safety_truth_count": 0,
                "package_mutation_count": 0,
                "mission_graph_mutation_count": 0,
                "runtime_mutation_count": 0,
                "phase1_runtime_mutation_count": 0,
                "phase2_writeback_count": 0,
                "raw_model_output_count": 0,
            },
            "boundary": {
                "candidate_only": True,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "raw_gpx_embedded": False,
            },
            "candidate_only": True,
            "runtime_safety_truth": False,
            "runtime_safety_truth_count": 0,
        }
    counts = payload.get("counts") or {}
    boundary = payload.get("boundary") or {}
    source_refs = list(payload.get("source_refs") or [])
    runtime_safety_truth_count = counts.get(
        "runtime_safety_truth_count",
        sum(
            1 for judgement in payload.get("judgements", [])
            if judgement.get("runtime_safety_truth") is not False
        ),
    )
    return {
        "source_id": payload["artifact_kind"],
        "source_path": source_path,
        "evidence_type": "pretrip_gis_perception_ai_judgements",
        **_projection_record_metadata(
            {
                "candidate_id": payload["artifact_kind"],
                "source_refs": source_refs,
                "prompt_sha256": payload.get("prompt_sha256"),
            },
            source_path=source_path,
            evidence_type="pretrip_gis_perception_ai_judgements",
            source_kind="gis_perception_ai_judgements",
            identity_keys=("candidate_id", "source_refs", "prompt_sha256"),
            review_state="model_interpretation_summary",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_gis_perception_ai_judgement.projection.v1",
            prompt_version=payload.get(
                "prompt_version",
                "scout.gis_perception.structured_judgement.v0",
            ),
            summary=(
                "GIS perception AI judgement summary; ModelInterpretation "
                "projection only, not ObservedFact and not runtime safety truth."
            ),
        ),
        "provider_kind": payload["provider_kind"],
        "model_name": payload["model_name"],
        "prompt_sha256": payload["prompt_sha256"],
        "input_count": payload["input_count"],
        "judgement_count": payload["judgement_count"],
        "source_ref_count": len(source_refs),
        "source_refs": source_refs,
        "counts": counts,
        "boundary": _summary_boundary(boundary),
        "live_model_call_performed": payload["live_model_call_performed"],
        "network_calls_allowed": payload["network_calls_allowed"],
        "candidate_only": boundary.get("candidate_only", True),
        "runtime_safety_truth_count": runtime_safety_truth_count,
        "cp_needed_count": sum(
            1 for judgement in payload.get("judgements", [])
            if judgement.get("cp_needed") is True
        ),
        "preview_judgements": [
            {
                **judgement,
                **_projection_record_metadata(
                    {
                        **judgement,
                        "source_refs": source_refs,
                    },
                    source_path=source_path,
                    evidence_type="pretrip_gis_perception_ai_preview_judgement",
                    source_kind="gis_perception_ai_judgement",
                    identity_keys=("judgement_id", "candidate_id", "source_refs"),
                    review_state="model_interpretation_preview",
                    confidence=judgement.get("confidence", "medium"),
                    stale_risk=judgement.get("stale_risk", "medium"),
                    extractor_version="pretrip_gis_perception_ai_judgement.projection.v1",
                    prompt_version=payload.get(
                        "prompt_version",
                        "scout.gis_perception.structured_judgement.v0",
                    ),
                    summary=(
                        "GIS perception AI preview judgement; ModelInterpretation "
                        "only, not runtime safety truth."
                    ),
                ),
            }
            for judgement in payload.get("judgements", [])[:12]
        ],
    }


def _gis_perception_timeline_summary(
    project_id: str,
    gis_perception: dict[str, Any],
    *,
    overpass_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_path = (
        gis_perception.get("source_path")
        or "project.json#gis-perception-timeline"
    )
    gpx_raw_candidates = [
        _gis_perception_timeline_checkpoint(candidate, source_path)
        for candidate in gis_perception.get("checkpoint_candidates", [])
    ]
    overpass_raw_candidates = _overpass_gis_perception_timeline_checkpoints(
        overpass_evidence
    )
    raw_candidates = [*gpx_raw_candidates, *overpass_raw_candidates]
    aggregated_candidates = _aggregate_gis_perception_timeline_checkpoints(
        raw_candidates,
        radius_m=GIS_PERCEPTION_AGGREGATION_RADIUS_M,
    )
    candidates, nearby_groups = _apply_gis_perception_nearby_groups(
        aggregated_candidates,
        radius_m=GIS_PERCEPTION_NEARBY_GROUP_RADIUS_M,
    )
    warning_count = sum(
        1 for candidate in candidates
        if candidate.get("checkpoint_type") == "warning_review"
    )
    hint_count = sum(
        1 for candidate in candidates
        if candidate.get("checkpoint_type") == "hint_review"
    )
    water_or_camp_count = sum(
        1 for candidate in candidates
        if candidate.get("checkpoint_type") == "water_or_camp_review"
    )
    return {
        "source_id": f"gis_perception_timeline.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_gis_perception_timeline",
        "status": "candidate_only",
        "counts": {
            "raw_checkpoint_candidate_count": len(raw_candidates),
            "gpx_checkpoint_candidate_count": len(gpx_raw_candidates),
            "overpass_checkpoint_candidate_count": len(overpass_raw_candidates),
            "checkpoint_candidate_count": len(candidates),
            "warning_review_checkpoint_count": warning_count,
            "hint_review_checkpoint_count": hint_count,
            "water_or_camp_review_checkpoint_count": water_or_camp_count,
            "review_queue_item_count": len(candidates),
            "nearby_group_count": len(nearby_groups),
            "nearby_grouped_checkpoint_count": sum(
                group["member_count"] for group in nearby_groups
            ),
            "aggregated_source_candidate_count": sum(
                candidate.get("aggregation", {}).get("source_candidate_count", 1)
                for candidate in candidates
            ),
        },
        "aggregation": {
            "strategy": "type_semantic_then_spatial_radius",
            "radius_m": GIS_PERCEPTION_AGGREGATION_RADIUS_M,
            "semantic_compatibility_required": True,
            "semantic_judgement_source": "pydantic_ai_structured_judgement",
            "deterministic_coordinate_merge": True,
            "pydantic_ai_sets_reason_not_final_truth": True,
        },
        "nearby_grouping": {
            "strategy": "spatial_radius_preserve_semantic_detail",
            "radius_m": GIS_PERCEPTION_NEARBY_GROUP_RADIUS_M,
            "grouping_mutates_candidates": False,
            "semantic_merge_allowed": False,
        },
        "nearby_groups": nearby_groups,
        "checkpoint_candidates": candidates,
        "boundary": {
            "projection_only": True,
            "candidate_only": True,
            "human_review_required": True,
            "runtime_safety_truth": False,
            "mutates_checkpoint_candidates_json": False,
            "aggregation_mutates_source_candidates": False,
            "nearby_grouping_mutates_source_candidates": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
        },
    }


def _gis_perception_timeline_checkpoint(
    candidate: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    map_target_ids = [
        candidate["candidate_id"],
        candidate.get("source_route_note_candidate_id"),
        candidate.get("linked_ln_proposal_id"),
    ]
    checkpoint = {
        **candidate,
        "source_id": candidate["candidate_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_gis_perception_timeline_checkpoint_candidate",
        "timeline_element_type": "checkpoint_candidate",
        "status": "candidate_only",
        "review_state": "needs_review",
        "review_category": "gis_perception_cp",
        "source_profile": candidate.get("source_profile", "gpx_corpus_route_notes"),
        "semantic_aggregation_key": _gis_perception_semantic_aggregation_key(
            candidate
        ),
        "map_target_ids": [target for target in map_target_ids if target],
        **_gis_perception_candidate_provenance(
            candidate,
            source_path=source_path,
            evidence_type="pretrip_gis_perception_timeline_checkpoint_candidate",
        ),
    }
    display_label = _gis_perception_candidate_display_label(checkpoint)
    checkpoint["display_label"] = display_label
    checkpoint["map_label"] = display_label
    return checkpoint


def _overpass_gis_perception_timeline_checkpoints(
    overpass_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not overpass_evidence:
        return []
    source_path = overpass_evidence.get("source_path") or "project.json#overpass"
    candidates = [
        *overpass_evidence.get("hazard_candidates", []),
        *[
            candidate
            for candidate in overpass_evidence.get("poi_candidates", [])
            if candidate.get("candidate_type")
            in {
                "shelter_candidate",
                "water_source_candidate",
                "parking_candidate",
            }
        ],
    ]
    projected: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        coordinate = _overpass_candidate_coordinate(candidate)
        if coordinate is None:
            continue
        checkpoint_type, proposed_ln_scope, review_action = (
            _overpass_checkpoint_semantics(candidate)
        )
        ai_reason = _overpass_ai_reason_zh(candidate)
        candidate_id = f"gis_cp.overpass_tag.{_safe_view_key(candidate['candidate_id'])}"
        display_label = _overpass_candidate_display_label(candidate)
        route_note_summary = (
            display_label if display_label.startswith("OSM ") else f"OSM {display_label}"
        )
        source_attribution = [
            {
                "source_kind": "overpass_candidate",
                "source_profile": "overpass_osm_tags",
                "source_candidate_id": candidate["candidate_id"],
                "source_artifact_id": overpass_evidence.get("source_id", ""),
                "source_role": "route_corridor_osm_evidence",
                "source_label": candidate.get("label") or display_label,
                "evidence_type": candidate.get(
                    "evidence_type",
                    "pretrip_overpass_vector_evidence",
                ),
                "confidence": candidate.get("confidence", "low"),
                "stale_risk": candidate.get("stale_risk", "medium"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
        record = {
            "candidate_id": candidate_id,
            "source_id": candidate_id,
            "source_path": source_path,
            "evidence_type": "pretrip_gis_perception_timeline_checkpoint_candidate",
            "timeline_element_type": "checkpoint_candidate",
            "status": "candidate_only",
            "review_state": "needs_review",
            "review_category": "gis_perception_cp",
            "source_profile": "overpass_osm_tags",
            "checkpoint_type": checkpoint_type,
            "lat": round(coordinate["lat"], 7),
            "lon": round(coordinate["lon"], 7),
            "source_route_note_candidate_id": None,
            "source_gpx_key": None,
            "source_gpx_role": None,
            "source_note_category": None,
            "route_note_age_days": None,
            "route_note_freshness": "unknown",
            "stale_route_note": False,
            "ai_judgement_id": f"gis_ai_judgement.overpass_tag.fixture.{index:05d}",
            "ai_reason_zh": ai_reason,
            "ai_confidence": candidate.get("confidence", "low"),
            "ai_stale_risk": candidate.get("stale_risk", "medium"),
            "ai_source_signals": _overpass_ai_source_signals(candidate),
            "linked_ln_proposal_id": None,
            "proposed_ln_scope": proposed_ln_scope,
            "route_note_summary": route_note_summary,
            "display_label": display_label,
            "map_label": display_label,
            "recommended_review_action": review_action,
            "source_attribution": source_attribution,
            "source_attribution_count": len(source_attribution),
            "candidate_only": True,
            "human_review_required": True,
            "runtime_safety_truth": False,
            "raw_gpx_embedded": False,
            "semantic_aggregation_key": _overpass_semantic_aggregation_key(
                candidate
            ),
            "map_target_ids": [candidate["candidate_id"], candidate_id],
            "overpass_candidate_ref": candidate["candidate_id"],
            "osm": {
                "osm_type": candidate.get("osm_type"),
                "osm_id": candidate.get("osm_id"),
                "tags": candidate.get("tags", {}),
                "candidate_type": candidate.get("candidate_type"),
                "conversion_rule_version": candidate.get(
                    "conversion_rule_version"
                ),
            },
            **_gis_perception_candidate_provenance(
                {
                    **candidate,
                    "candidate_id": candidate_id,
                    "route_note_summary": route_note_summary,
                    "source_attribution": source_attribution,
                    "human_review_required": True,
                },
                source_path=source_path,
                evidence_type=(
                    "pretrip_gis_perception_timeline_checkpoint_candidate"
                ),
                default_prompt_version=(
                    "not_applicable_deterministic_overpass_projection"
                ),
            ),
        }
        projected.append(record)
    return projected


def _aggregate_gis_perception_timeline_checkpoints(
    candidates: list[dict[str, Any]],
    *,
    radius_m: float,
) -> list[dict[str, Any]]:
    clusters: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        for cluster in clusters:
            if _gis_perception_same_cluster(candidate, cluster, radius_m=radius_m):
                cluster.append(candidate)
                break
        else:
            clusters.append([candidate])
    return [
        _merged_gis_perception_timeline_checkpoint(index, cluster, radius_m=radius_m)
        for index, cluster in enumerate(clusters, start=1)
    ]


def _gis_perception_same_cluster(
    candidate: dict[str, Any],
    cluster: list[dict[str, Any]],
    *,
    radius_m: float,
) -> bool:
    if not cluster:
        return False
    if candidate.get("checkpoint_type") != cluster[0].get("checkpoint_type"):
        return False
    if candidate.get("semantic_aggregation_key") != cluster[0].get(
        "semantic_aggregation_key"
    ):
        return False
    if candidate.get("semantic_aggregation_key") == "other:preserve_detail":
        return False
    center_lat = sum(float(item["lat"]) for item in cluster) / len(cluster)
    center_lon = sum(float(item["lon"]) for item in cluster) / len(cluster)
    return _haversine_m(
        float(candidate["lat"]),
        float(candidate["lon"]),
        center_lat,
        center_lon,
    ) <= radius_m


def _merged_gis_perception_timeline_checkpoint(
    index: int,
    cluster: list[dict[str, Any]],
    *,
    radius_m: float,
) -> dict[str, Any]:
    representative = cluster[0]
    lat = sum(float(item["lat"]) for item in cluster) / len(cluster)
    lon = sum(float(item["lon"]) for item in cluster) / len(cluster)
    merged_candidate_ids = [item["candidate_id"] for item in cluster]
    source_attribution = _merge_source_attributions(cluster)
    summaries = _unique_limited(
        item.get("route_note_summary", "")
        for item in cluster
    )
    map_target_ids = _unique_limited(
        [
            *merged_candidate_ids,
            *[
                target
                for item in cluster
                for target in item.get("map_target_ids", [])
            ],
        ],
        limit=200,
    )
    source_refs = _unique_limited(
        [
            *[
                ref
                for item in cluster
                for ref in item.get("source_refs", [])
            ],
            *merged_candidate_ids,
        ],
        limit=240,
    )
    stale_risk = (
        "high"
        if any(item.get("stale_risk") == "high" for item in cluster)
        else representative.get("stale_risk", "medium")
    )
    merged = {
        **representative,
        "candidate_id": (
            f"gis_cp_cluster.{index:04d}."
            f"{_safe_view_key(representative['candidate_id'])}"
        ),
        "source_id": (
            f"gis_cp_cluster.{index:04d}."
            f"{_safe_view_key(representative['candidate_id'])}"
        ),
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "source_attribution": source_attribution,
        "source_attribution_count": len(source_attribution),
        "source_refs": source_refs,
        "confidence": representative.get("confidence", "medium"),
        "stale_risk": stale_risk,
        "review_state": "needs_review",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "extractor_version": representative.get(
            "extractor_version",
            "pretrip_gis_perception.projection.v1",
        ),
        "pydantic_ai_prompt_version": representative.get(
            "pydantic_ai_prompt_version"
        ),
        "model_output_sha256": _stable_projection_hash(
            {
                "candidate_ids": merged_candidate_ids,
                "source_refs": source_refs,
                "semantic_aggregation_key": representative.get(
                    "semantic_aggregation_key"
                ),
            }
        ),
        "model_output_summary": (
            "GIS perception timeline aggregate candidate; source candidates "
            "remain independent review items and runtime safety truth is false."
        ),
        "merged_candidate_ids": merged_candidate_ids,
        "route_note_summaries": summaries,
        "route_note_summary": (
            representative.get("route_note_summary", "")
            if len(cluster) == 1
            else f"{len(cluster)} historical route notes clustered near this CP"
        ),
        "map_target_ids": map_target_ids,
        "aggregation": {
            "strategy": "type_semantic_then_spatial_radius",
            "radius_m": radius_m,
            "source_candidate_count": len(cluster),
            "semantic_aggregation_key": representative.get(
                "semantic_aggregation_key"
            ),
            "semantic_compatibility_required": True,
            "representative_candidate_id": representative["candidate_id"],
            "merged_candidate_ids": merged_candidate_ids,
            "deterministic_coordinate_merge": "centroid",
            "semantic_judgement_source": "pydantic_ai_structured_judgement",
        },
    }
    display_source = (
        merged
        if len(cluster) == 1
        else {**merged, "display_label": "", "map_label": "", "label": ""}
    )
    display_label = _gis_perception_candidate_display_label(display_source)
    merged["display_label"] = display_label
    merged["map_label"] = display_label
    return merged


def _gis_perception_semantic_aggregation_key(candidate: dict[str, Any]) -> str:
    if candidate.get("source_profile") == "overpass_osm_tags":
        return _overpass_semantic_aggregation_key(candidate)
    note = str(candidate.get("route_note_summary") or "")
    signals = " ".join(str(signal) for signal in candidate.get("ai_source_signals", []))
    text = f"{note} {signals}"
    if any(token in text for token in ("高繞", "腰繞", "低繞", "繞路", "取右", "取左")):
        return "route:detour"
    if any(token in text for token in ("上切", "下切")):
        return "route:cut"
    if any(token in text for token in ("茂密", "林相", "芒草", "箭竹")):
        return "route:vegetation"
    if any(token in text for token in ("路徑不明", "路跡", "路徑", "有路", "好走", "獸俓")):
        return "route:path_condition"
    if any(token in text for token in ("崩塌", "崩壁", "坍方", "崩", "大崩壁")):
        return "hazard:collapse"
    if any(token in text for token in ("斷崖", "峭壁", "懸崖")):
        return "hazard:cliff"
    if any(token in text for token in ("架繩", "拉繩")):
        return "hazard:rope"
    if any(token in text for token in ("水源", "黑水", "水塘", "溪水")):
        return "resource:water"
    if any(token in text for token in ("營地", "山屋", "避難", "C1", "C2")):
        return "resource:camp_or_shelter"
    return "other:preserve_detail"


def _gis_perception_candidate_provenance(
    candidate: dict[str, Any],
    *,
    source_path: str,
    evidence_type: str,
    classifier: dict[str, Any] | None = None,
    default_prompt_version: str | None = None,
) -> dict[str, Any]:
    classifier = classifier or {}
    source_attribution = candidate.get("source_attribution", []) or []
    source_refs = _unique_limited(
        [
            source_path,
            candidate.get("candidate_id"),
            candidate.get("source_route_note_candidate_id"),
            candidate.get("linked_ln_proposal_id"),
            *[
                attribution.get("source_candidate_id")
                for attribution in source_attribution
                if isinstance(attribution, dict)
            ],
            *[
                attribution.get("source_artifact_id")
                for attribution in source_attribution
                if isinstance(attribution, dict)
            ],
            *[
                attribution.get("source_ref")
                for attribution in source_attribution
                if isinstance(attribution, dict)
            ],
        ],
        limit=120,
    )
    attribution_confidences = [
        attribution.get("confidence")
        for attribution in source_attribution
        if isinstance(attribution, dict) and attribution.get("confidence")
    ]
    attribution_stale_risks = [
        attribution.get("stale_risk")
        for attribution in source_attribution
        if isinstance(attribution, dict) and attribution.get("stale_risk")
    ]
    confidence = (
        candidate.get("confidence")
        or candidate.get("ai_confidence")
        or (attribution_confidences[0] if attribution_confidences else None)
        or "medium"
    )
    stale_risk = (
        candidate.get("stale_risk")
        or candidate.get("ai_stale_risk")
        or ("high" if candidate.get("stale_route_note") else None)
        or (attribution_stale_risks[0] if attribution_stale_risks else None)
        or "medium"
    )
    model_hash = (
        candidate.get("model_output_sha256")
        or classifier.get("prompt_sha256")
        or _stable_projection_hash(
            {
                "candidate_id": candidate.get("candidate_id"),
                "source_refs": source_refs,
                "source_attribution": source_attribution,
                "evidence_type": evidence_type,
            }
        )
    )
    prompt_version = (
        candidate.get("pydantic_ai_prompt_version")
        or classifier.get("prompt_version")
        or default_prompt_version
    )
    return {
        "source_refs": source_refs,
        "confidence": confidence,
        "stale_risk": stale_risk,
        "review_state": candidate.get("review_state", "needs_review"),
        "candidate_only": candidate.get("candidate_only", True),
        "runtime_safety_truth": candidate.get("runtime_safety_truth", False),
        "extractor_version": candidate.get(
            "extractor_version",
            "pretrip_gis_perception.projection.v1",
        ),
        "pydantic_ai_prompt_version": prompt_version,
        "model_output_sha256": str(model_hash),
        "model_output_summary": candidate.get("model_output_summary")
        or (
            f"{evidence_type} generated from GIS perception evidence; "
            "pretrip candidate-only review item, not runtime safety truth."
        ),
    }


def _overpass_candidate_coordinate(
    candidate: dict[str, Any],
) -> dict[str, float] | None:
    geometry = candidate.get("geometry") or {}
    geometry_type = geometry.get("type")
    if geometry_type == "Point":
        return _geojson_point_coordinate(geometry)
    points = _geojson_geometry_points(geometry)
    if not points:
        return None
    return {
        "lat": sum(point["lat"] for point in points) / len(points),
        "lon": sum(point["lon"] for point in points) / len(points),
    }


def _geojson_geometry_points(geometry: dict[str, Any]) -> list[dict[str, float]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "LineString":
        return [
            {"lon": float(lon), "lat": float(lat)}
            for lon, lat, *_ in coordinates
        ]
    if geometry_type == "Polygon":
        return [
            {"lon": float(lon), "lat": float(lat)}
            for ring in coordinates
            for lon, lat, *_ in ring
        ]
    if geometry_type == "MultiLineString":
        return [
            {"lon": float(lon), "lat": float(lat)}
            for line in coordinates
            for lon, lat, *_ in line
        ]
    return []


def _overpass_checkpoint_semantics(
    candidate: dict[str, Any],
) -> tuple[str, str, str]:
    candidate_type = candidate.get("candidate_type")
    if candidate_type == "terrain_risk_candidate":
        return "warning_review", "warning_coverage", "review_as_warning_cp"
    if candidate_type in {"shelter_candidate", "water_source_candidate"}:
        return "water_or_camp_review", "review_only", "review_as_water_or_camp_cp"
    return "hint_review", "review_only", "review_as_hint_cp"


def _overpass_ai_reason_zh(candidate: dict[str, Any]) -> str:
    candidate_type = candidate.get("candidate_type")
    label = candidate.get("label") or candidate.get("candidate_id")
    if candidate_type == "water_source_candidate":
        return f"OSM tag 顯示 {label} 可能是水源；水況會變動，需人工複核後才能當成補給 CP。"
    if candidate_type == "shelter_candidate":
        return f"OSM tag 顯示 {label} 可能是避難點或山屋；容量與開放狀態需人工複核。"
    if candidate_type == "parking_candidate":
        return f"OSM tag 顯示 {label} 可能是停車或道路接駁點；適合作為 pretrip 交通 CP 候選。"
    if candidate_type == "terrain_risk_candidate":
        return f"OSM tag 顯示 {label} 可能是地形風險；只能先進入警告 CP 候選並要求人工複核。"
    return f"OSM tag 顯示 {label} 可能有路線規劃價值；先保留為 review-only CP 候選。"


def _overpass_ai_source_signals(candidate: dict[str, Any]) -> list[str]:
    tags = candidate.get("tags", {})
    signals = [
        "source_kind:overpass_candidate",
        f"candidate_type:{candidate.get('candidate_type')}",
        f"feature_type:{candidate.get('feature_type')}",
    ]
    for key in ("amenity", "tourism", "natural", "emergency", "hazard", "risk"):
        if key in tags:
            signals.append(f"osm_tag:{key}={tags[key]}")
    return signals


def _overpass_semantic_aggregation_key(candidate: dict[str, Any]) -> str:
    candidate_type = candidate.get("candidate_type")
    if candidate_type == "water_source_candidate":
        return "resource:water"
    if candidate_type == "shelter_candidate":
        return "resource:camp_or_shelter"
    if candidate_type == "terrain_risk_candidate":
        return "hazard:terrain"
    if candidate_type == "parking_candidate":
        return "access:parking"
    return "overpass:preserve_detail"


def _apply_gis_perception_nearby_groups(
    candidates: list[dict[str, Any]],
    *,
    radius_m: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        for group in groups:
            if _gis_perception_nearby_group_member(
                candidate,
                group,
                radius_m=radius_m,
            ):
                group.append(candidate)
                break
        else:
            groups.append([candidate])

    group_by_candidate_id: dict[str, dict[str, Any]] = {}
    nearby_groups: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        if len(group) < 2:
            continue
        group_id = f"gis_cp_nearby_group.{index:04d}"
        members = [
            {
                "candidate_id": item["candidate_id"],
                **_projection_record_metadata(
                    item,
                    source_path="project.json#gis-perception-nearby-group-member",
                    evidence_type="pretrip_gis_perception_nearby_group_member",
                    source_kind="gis_nearby_group_member",
                    identity_keys=("candidate_id", "source_refs"),
                    review_state="display_group_member",
                    confidence=item.get("confidence", "medium"),
                    stale_risk=item.get("stale_risk", "medium"),
                    extractor_version="pretrip_gis_perception.nearby_group_projection.v1",
                    prompt_version="not_applicable_deterministic_nearby_grouping",
                    summary=(
                        "Nearby group member pointer for review navigation; "
                        "semantic candidate remains separate and not runtime safety truth."
                    ),
                ),
                "checkpoint_type": item.get("checkpoint_type"),
                "semantic_aggregation_key": item.get("semantic_aggregation_key"),
                "summary": _gis_perception_candidate_display_label(item),
                "display_label": item.get("display_label")
                or _gis_perception_candidate_display_label(item),
                "map_label": item.get("map_label")
                or _gis_perception_candidate_display_label(item),
                "source_profile": item.get("source_profile"),
                "stale_route_note": item.get("stale_route_note", False),
                "route_note_freshness": item.get("route_note_freshness", "unknown"),
            }
            for item in group
        ]
        center_lat = sum(float(item["lat"]) for item in group) / len(group)
        center_lon = sum(float(item["lon"]) for item in group) / len(group)
        source_refs = _unique_limited(
            [
                *[
                    ref
                    for item in group
                    for ref in item.get("source_refs", [])
                ],
                *[item["candidate_id"] for item in group],
            ],
            limit=240,
        )
        source_attribution = _merge_source_attributions(group)
        stale_risk = (
            "high"
            if any(item.get("stale_risk") == "high" for item in group)
            else "medium"
        )
        nearby_group = {
            "nearby_group_id": group_id,
            "source_id": group_id,
            "candidate_id": group_id,
            "evidence_type": "pretrip_gis_perception_nearby_group",
            "source_path": "project.json#gis-perception-nearby-group",
            "status": "candidate_only_grouping",
            "review_state": "display_group_only",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "confidence": "medium",
            "stale_risk": stale_risk,
            "source_refs": source_refs,
            "source_attribution": source_attribution,
            "extractor_version": "pretrip_gis_perception.nearby_group_projection.v1",
            "pydantic_ai_prompt_version": (
                "not_applicable_deterministic_nearby_grouping"
            ),
            "model_output_sha256": _stable_projection_hash(
                {
                    "nearby_group_id": group_id,
                    "member_ids": [item["candidate_id"] for item in group],
                    "source_refs": source_refs,
                }
            ),
            "model_output_summary": (
                "Nearby display group for map/review navigation only; semantic "
                "candidates are not merged and runtime safety truth is false."
            ),
            "member_count": len(group),
            "member_candidate_ids": [item["candidate_id"] for item in group],
            "lat": round(center_lat, 7),
            "lon": round(center_lon, 7),
            "radius_m": radius_m,
            "semantic_merge_allowed": False,
            "members": members,
            "semantic_keys": sorted(
                {
                    str(item.get("semantic_aggregation_key"))
                    for item in group
                    if item.get("semantic_aggregation_key")
                }
            ),
        }
        display_label = _gis_nearby_group_display_label(nearby_group)
        nearby_group["display_label"] = display_label
        nearby_group["map_label"] = display_label
        nearby_groups.append(nearby_group)
        for item in group:
            group_by_candidate_id[item["candidate_id"]] = nearby_group

    annotated: list[dict[str, Any]] = []
    for candidate in candidates:
        nearby_group = group_by_candidate_id.get(candidate["candidate_id"])
        if nearby_group is None:
            annotated.append(
                {
                    **candidate,
                    "nearby_group_id": None,
                    "nearby_group_size": 1,
                    "nearby_group_members": [],
                }
            )
            continue
        annotated.append(
            {
                **candidate,
                    "nearby_group_id": nearby_group["nearby_group_id"],
                    "nearby_group_label": nearby_group["display_label"],
                    "nearby_group_size": nearby_group["member_count"],
                    "nearby_group_members": nearby_group["members"],
                }
        )
    return annotated, nearby_groups


def _gis_perception_nearby_group_member(
    candidate: dict[str, Any],
    group: list[dict[str, Any]],
    *,
    radius_m: float,
) -> bool:
    center_lat = sum(float(item["lat"]) for item in group) / len(group)
    center_lon = sum(float(item["lon"]) for item in group) / len(group)
    return _haversine_m(
        float(candidate["lat"]),
        float(candidate["lon"]),
        center_lat,
        center_lon,
    ) <= radius_m


def _merge_source_attributions(
    cluster: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in cluster:
        for attribution in item.get("source_attribution", []):
            key = (
                str(attribution.get("source_kind", "")),
                str(attribution.get("source_candidate_id", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(attribution)
    return merged


def _unique_limited(values, *, limit: int = 12) -> list[str]:
    unique: list[str] = []
    for value in values:
        if not value or value in unique:
            continue
        unique.append(value)
        if len(unique) >= limit:
            break
    return unique


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _safe_view_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()[:96] or "candidate"


def _readable_label_text(value: Any, *, max_chars: int = GIS_PERCEPTION_LABEL_MAX_CHARS) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(
        r"\s*\|\s*\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\s*$",
        "",
        text,
    ).strip()
    if not text:
        return ""
    if _looks_like_internal_identifier(text):
        return ""
    if len(text) > max_chars:
        return f"{text[: max_chars - 1].rstrip()}…"
    return text


def _looks_like_internal_identifier(text: str) -> bool:
    compact = text.strip()
    if re.fullmatch(r"(?:node|way|relation)/\d+", compact):
        return True
    if re.fullmatch(r"\d{7,}", compact):
        return True
    if compact.startswith(
        (
            "gis_cp.",
            "gis_cp_",
            "gis_cp_cluster.",
            "gis_cp_nearby_group.",
            "cp_note.",
            "cp_note_",
            "pretrip_gis_",
            "overpass.",
            "overpass_",
            "route_note.reference_",
            "ln_proposal.route_note.",
        )
    ):
        return True
    return len(compact) > 48 and (
        compact.count("_") >= 3 or compact.count(".") >= 4
    )


def _semantic_key_label(key: Any) -> str:
    labels = {
        "route:detour": "繞路/岔路候選",
        "route:cut": "上切/下切候選",
        "route:vegetation": "植被遮蔽候選",
        "route:path_condition": "路況提示候選",
        "hazard:collapse": "崩塌地形候選",
        "hazard:cliff": "斷崖地形候選",
        "hazard:rope": "繩索地形候選",
        "hazard:terrain": "地形風險候選",
        "resource:water": "水源候選",
        "resource:camp_or_shelter": "營地/山屋候選",
        "access:parking": "停車/接駁候選",
    }
    return labels.get(str(key or ""), "")


def _checkpoint_type_label(checkpoint_type: Any) -> str:
    labels = {
        "warning_review": "風險 CP 候選",
        "hint_review": "路線提示 CP 候選",
        "water_or_camp_review": "水源/營地 CP 候選",
    }
    return labels.get(str(checkpoint_type or ""), "GIS CP 候選")


def _overpass_candidate_display_label(candidate: dict[str, Any]) -> str:
    tags = candidate.get("tags") or {}
    for key in (
        "name",
        "name:zh",
        "name:zh-Hant",
        "name:en",
        "alt_name",
        "loc_name",
        "official_name",
        "ref",
    ):
        label = _readable_label_text(tags.get(key) or candidate.get(key))
        if label:
            return label
    label = _readable_label_text(candidate.get("label"))
    if label:
        return label
    candidate_type = candidate.get("candidate_type")
    if candidate_type == "water_source_candidate":
        natural = tags.get("natural")
        return "OSM 水源" if natural != "spring" else "OSM 泉水/水源"
    if candidate_type == "shelter_candidate":
        shelter_type = str(tags.get("shelter_type") or "")
        return "OSM 涼亭/避難點" if shelter_type == "picnic_shelter" else "OSM 避難點"
    if candidate_type == "parking_candidate":
        return "OSM 停車/接駁點"
    if candidate_type == "terrain_risk_candidate":
        return "OSM 地形風險"
    return "OSM 路線候選"


def _gis_perception_candidate_display_label(candidate: dict[str, Any]) -> str:
    osm_tags = (candidate.get("osm") or {}).get("tags") or {}
    for value in (
        candidate.get("map_label"),
        candidate.get("display_label"),
        candidate.get("short_label"),
        candidate.get("label"),
        candidate.get("name"),
        osm_tags.get("name"),
        osm_tags.get("name:zh"),
        osm_tags.get("name:zh-Hant"),
        osm_tags.get("alt_name"),
        osm_tags.get("loc_name"),
    ):
        label = _readable_label_text(value)
        if label:
            return label
    summary_labels = [
        _readable_label_text(summary)
        for summary in candidate.get("route_note_summaries", [])
    ]
    summary_labels = _unique_limited([label for label in summary_labels if label], limit=3)
    if summary_labels:
        return _readable_label_text(" / ".join(summary_labels))
    for value in (
        candidate.get("route_note_summary"),
        candidate.get("summary"),
        candidate.get("ai_reason_zh"),
    ):
        label = _readable_label_text(value)
        if label:
            return label
    for attribution in candidate.get("source_attribution", []) or []:
        if not isinstance(attribution, dict):
            continue
        label = _readable_label_text(attribution.get("source_label"))
        if label:
            return label
    semantic_label = _semantic_key_label(candidate.get("semantic_aggregation_key"))
    if semantic_label:
        return semantic_label
    return _checkpoint_type_label(candidate.get("checkpoint_type"))


def _gis_nearby_group_display_label(group: dict[str, Any]) -> str:
    member_labels = _unique_limited(
        [
            _gis_perception_candidate_display_label(member)
            for member in group.get("members", [])
            if isinstance(member, dict)
        ],
        limit=3,
    )
    member_labels = [label for label in member_labels if label]
    if member_labels:
        return _readable_label_text(f"附近 CP: {' / '.join(member_labels)}")
    semantic_labels = _unique_limited(
        [
            _semantic_key_label(key)
            for key in group.get("semantic_keys", [])
        ],
        limit=2,
    )
    semantic_labels = [label for label in semantic_labels if label]
    if semantic_labels:
        return _readable_label_text(f"附近 CP: {' / '.join(semantic_labels)}")
    return "附近 CP"


def _review_queue_with_gis_perception_items(
    review_queue: dict[str, Any],
    gis_timeline: dict[str, Any],
) -> dict[str, Any]:
    items = [
        *review_queue.get("items", []),
        *[
            _gis_perception_review_queue_item(candidate, gis_timeline)
            for candidate in gis_timeline.get("checkpoint_candidates", [])
        ],
    ]
    category_counts = Counter(
        item.get("category", "unknown")
        for item in items
    )
    counts = {
        **review_queue.get("counts", {}),
        "item_count": len(items),
        "category_counts": dict(sorted(category_counts.items())),
        "gis_perception_cp_count": category_counts.get("gis_perception_cp", 0),
        "warning_count": sum(1 for item in items if item.get("severity") == "warning"),
        "review_count": sum(1 for item in items if item.get("severity") == "review"),
        "blocker_count": sum(1 for item in items if item.get("severity") == "blocker"),
    }
    return {
        **review_queue,
        "counts": counts,
        "items": items,
        "projection_notes": [
            *review_queue.get("projection_notes", []),
            "GIS perception CP candidates are projected into the review queue; no checkpoints.json mutation is performed.",
        ],
    }


def _gis_perception_review_queue_item(
    candidate: dict[str, Any],
    gis_timeline: dict[str, Any],
) -> dict[str, Any]:
    severity = (
        "warning"
        if candidate.get("checkpoint_type") == "warning_review"
        else "review"
    )
    source_refs = {
        attribution.get("source_kind", "unknown"): attribution.get("source_candidate_id")
        for attribution in candidate.get("source_attribution", [])
    }
    display_label = _gis_perception_candidate_display_label(candidate)
    item = {
        "item_id": f"review_queue.gis_perception.{candidate['candidate_id']}",
        "candidate_ref": candidate["candidate_id"],
        "category": "gis_perception_cp",
        "severity": severity,
        "title": f"GIS CP review: {display_label}",
        "summary": display_label,
        "source_artifact_kind": "pretrip_gis_perception_candidates",
        "source_ref": gis_timeline.get("source_path", ""),
        "source_ref_key": "gis_perception_candidates_ref",
        "review_focus": candidate.get("map_target_ids", [candidate["candidate_id"]]),
        "evidence_summary": {
            "checkpoint_type": candidate.get("checkpoint_type"),
            "proposed_ln_scope": candidate.get("proposed_ln_scope"),
            "ai_reason_zh": candidate.get("ai_reason_zh"),
            "ai_confidence": candidate.get("ai_confidence"),
            "ai_stale_risk": candidate.get("ai_stale_risk"),
            "source_attribution": candidate.get("source_attribution", []),
            "source_candidate_refs": source_refs,
            "aggregation": candidate.get("aggregation", {}),
            "nearby_group_id": candidate.get("nearby_group_id"),
            "nearby_group_label": candidate.get("nearby_group_label"),
            "nearby_group_size": candidate.get("nearby_group_size", 1),
            "nearby_group_members": candidate.get("nearby_group_members", []),
            "merged_candidate_ids": candidate.get("merged_candidate_ids", []),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "accept_reject_allowed": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "review_state": "needs_review",
        "confidence": candidate.get("confidence")
        or candidate.get("ai_confidence")
        or "medium",
        "stale_risk": candidate.get("stale_risk")
        or candidate.get("ai_stale_risk")
        or "medium",
        "source_refs": _review_queue_source_refs(
            {
                "source_ref": gis_timeline.get("source_path", ""),
                "candidate_ref": candidate.get("candidate_id", ""),
                "evidence_summary": {
                    "source_attribution": candidate.get("source_attribution", []),
                },
            }
        ),
        "source_attribution": candidate.get("source_attribution", []),
        "extractor_version": candidate.get(
            "extractor_version",
            "pretrip_admin_review_queue_projection.v1",
        ),
        "pydantic_ai_prompt_version": candidate.get("pydantic_ai_prompt_version"),
        "model_output_sha256": candidate.get("model_output_sha256")
        or _stable_projection_hash(
            {
                "candidate_ref": candidate.get("candidate_id"),
                "source_attribution": candidate.get("source_attribution", []),
            }
        ),
        "model_output_summary": candidate.get("model_output_summary")
        or "GIS perception CP candidate queued for human review; pretrip evidence only.",
        "decision_recorded": False,
        "mutation_allowed": False,
        "map_target_ids": candidate.get("map_target_ids", [candidate["candidate_id"]]),
    }
    item["evidence_summary"] = _review_queue_evidence_summary(
        item,
        source_path=item.get("source_ref", ""),
        source_refs=item.get("source_refs", []),
    )
    return item


def _review_queue_with_energy_projection_item(
    review_queue: dict[str, Any],
    energy_projection: dict[str, Any],
) -> dict[str, Any]:
    depletion_checkpoint = energy_projection.get("possible_depletion_checkpoint_name")
    if not depletion_checkpoint:
        return review_queue
    item = {
        "item_id": f"review_queue.energy_reserve.{_safe_view_key(depletion_checkpoint)}",
        "candidate_ref": f"energy_reserve.depletion_checkpoint.{_safe_view_key(depletion_checkpoint)}",
        "category": "energy_reserve",
        "severity": "warning",
        "title": f"Energy reserve review: {depletion_checkpoint}",
        "summary": (
            "Energy-adjusted ETA projection indicates this checkpoint may need "
            "rest, pacing, or turnaround review before departure."
        ),
        "source_artifact_kind": "pretrip_energy_reserve_projection",
        "source_ref": energy_projection.get("source_path", ""),
        "source_ref_key": "energy_projection_ref",
        "review_focus": [depletion_checkpoint],
        "evidence_summary": {
            "possible_depletion_checkpoint_name": depletion_checkpoint,
            "reserve_start_score": energy_projection.get("reserve_start_score"),
            "route_energy_multiplier": energy_projection.get("route_energy_multiplier"),
            "projected_target_eta": energy_projection.get("projected_target_eta"),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "medical_diagnosis": False,
        },
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "review_state": "needs_review",
        "confidence": "medium",
        "stale_risk": "medium",
        "source_refs": _review_queue_source_refs(
            {
                "source_ref": energy_projection.get("source_path", ""),
                "candidate_ref": f"energy_reserve.depletion_checkpoint.{_safe_view_key(depletion_checkpoint)}",
            }
        ),
        "source_attribution": [
            {
                "source_kind": "pretrip_energy_reserve_projection",
                "source_candidate_id": f"energy_reserve.depletion_checkpoint.{_safe_view_key(depletion_checkpoint)}",
                "source_artifact_id": energy_projection.get(
                    "source_id",
                    "pretrip_energy_reserve_projection",
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "extractor_version": "pretrip_admin_review_queue_projection.v1",
        "pydantic_ai_prompt_version": None,
        "model_output_sha256": _stable_projection_hash(
            {
                "candidate_ref": f"energy_reserve.depletion_checkpoint.{_safe_view_key(depletion_checkpoint)}",
                "source_ref": energy_projection.get("source_path", ""),
            }
        ),
        "model_output_summary": (
            "Energy reserve projection queued for human review; advisory "
            "pretrip evidence only and not runtime safety truth."
        ),
        "decision_recorded": False,
        "accept_reject_allowed": False,
        "mutation_allowed": False,
        "source_id": f"review_queue.energy_reserve.{_safe_view_key(depletion_checkpoint)}",
        "source_path": energy_projection.get("source_path", ""),
        "evidence_type": "pretrip_review_queue_item",
        "map_target_ids": [depletion_checkpoint],
    }
    item["evidence_summary"] = _review_queue_evidence_summary(
        item,
        source_path=item.get("source_ref", ""),
        source_refs=item.get("source_refs", []),
    )
    items = [*review_queue.get("items", []), item]
    category_counts = Counter(item.get("category", "unknown") for item in items)
    counts = {
        **review_queue.get("counts", {}),
        "item_count": len(items),
        "category_counts": dict(sorted(category_counts.items())),
        "energy_reserve_count": category_counts.get("energy_reserve", 0),
        "warning_count": sum(1 for entry in items if entry.get("severity") == "warning"),
        "review_count": sum(1 for entry in items if entry.get("severity") == "review"),
        "blocker_count": sum(1 for entry in items if entry.get("severity") == "blocker"),
    }
    return {
        **review_queue,
        "counts": counts,
        "items": items,
        "projection_notes": [
            *review_queue.get("projection_notes", []),
            "Energy reserve projection is added to review queue as advisory planning context only.",
        ],
    }
def _empty_reference_tracks(project_id: str, source_path: str) -> dict[str, Any]:
    return {
        "source_id": f"reference_tracks.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_reference_track_summary",
        "reference_track_count": 0,
        "route_role": "golden_route",
        "golden_route": {},
        "primary_route": {},
        "reference_tracks": [],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_gpx_copied_to_repo": False,
        },
        "notes": [],
    }


def _empty_checkpoint_events(project_id: str, source_path: str) -> dict[str, Any]:
    return {
        "source_id": f"checkpoint_events.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_checkpoint_event_candidates",
        "event_count": 0,
        "source_gpx": {},
        "events": [],
        "boundary": {
            "candidate_only": True,
            "runtime_mutation_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
        },
        "notes": [],
    }


def _debug_projection_timeline_events(
    view: dict[str, Any],
    lifecycle_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project_id = view["project_id"]
    route = view["route"]
    checkpoints = view["checkpoints"]
    segments = view["segments"]
    checkpoint_event_by_id = {
        event.get("checkpoint_candidate_id"): event
        for event in (view.get("checkpoint_events", {}).get("events") or [])
        if event.get("checkpoint_candidate_id")
    }
    boundary = {
        **_debug_projection_boundary(lifecycle_events),
        "projection_only": True,
        "golden_route_is_reference_evidence": True,
        "runtime_safety_truth": False,
        "candidate_only": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "mission_graph_compiled": False,
    }
    base_payload = {
        "project_id": project_id,
        "profile": "pretrip_debug_projection",
        "import_stage": "pretrip",
        "route_role": "golden_route_reference",
        "projection_only": True,
        "runtime_safety_truth": False,
        "boundary": boundary,
    }
    events: list[dict[str, Any]] = []

    def append_event(kind: str, summary: str, payload: dict[str, Any]) -> None:
        sequence = len(events) + 1
        event_timestamp = payload.pop(
            "timestamp",
            payload.get("observed_at")
            or route.get("started_at")
            or "2026-05-21T00:00:00Z",
        )
        subject_ref = payload.pop("subject_ref", f"pretrip.{project_id}")
        map_target_ids = payload.get("map_target_ids") or []
        events.append(
            {
                "event_id": f"debug_event.pretrip_projection.{project_id}.{sequence:06d}",
                "session_id": f"pretrip_projection.{project_id}",
                "mission_id": None,
                "sequence": sequence,
                "timestamp": event_timestamp,
                "phase": "phase4",
                "kind": kind,
                "severity": payload.pop("severity", "info"),
                "summary": summary,
                "subject_ref": subject_ref,
                "correlation_refs": [
                    "artifact.gpx.chilai_nanhua_day1",
                    *map_target_ids,
                ],
                "payload": {
                    **base_payload,
                    **payload,
                    "map_target_ids": map_target_ids,
                },
            }
        )

    append_event(
        "debug_session_started",
        f"{project_id} debug projection loaded from the shared GPX set.",
        {
            "subject_ref": f"project.{project_id}",
            "map_target_ids": ["route"],
            "route_point_count": route["point_count"],
            "distance_m": route["distance_m"],
            "checkpoint_candidate_count": len(checkpoints),
            "segment_candidate_count": len(segments),
            "reference_track_count": view.get("reference_tracks", {}).get(
                "reference_track_count",
                0,
            ),
        },
    )
    append_event(
        "provider_status_recorded",
        (
            "Debug projection sources use local GPX, map, OSM, Overpass, "
            "and DEM evidence only."
        ),
        {
            "subject_ref": "provider.pretrip_evidence_bundle",
            "provider": "pretrip_evidence_bundle",
            "status": "available",
            "map_target_ids": ["route", "overpass", "reference-tracks"],
            "network_calls_allowed": False,
            "local_fixture_backed": True,
            "overpass_candidate_count": view.get("overpass_evidence", {})
            .get("counts", {})
            .get("candidates", 0),
        },
    )

    for segment in view.get("reference_segment_timing", {}).get("segments", []):
        append_event(
            "reference_segment_timing_projected",
            (
                f"Reference timing range for {segment.get('label')} is "
                "available as aggregate historical GPX evidence."
            ),
            {
                "subject_ref": segment.get("segment_id"),
                "map_target_ids": segment.get("map_target_ids", []),
                "segment_id": segment.get("segment_id"),
                "segment_label": segment.get("label"),
                "from_node_name": segment.get("from_node_name"),
                "to_node_name": segment.get("to_node_name"),
                "sample_count": segment.get("sample_count"),
                "source_count": segment.get("source_count"),
                "duration_minutes": segment.get("duration_minutes"),
                "track_distance_km": segment.get("track_distance_km"),
                "distance_filter_km": segment.get("distance_filter_km"),
                "route_guide_comparison": segment.get("route_guide_comparison"),
                "rejected_summary": segment.get("rejected_summary"),
                "safety_level": "L0_PRETRIP_PROJECTION",
                "projection_event_type": "reference_segment_timing",
                "raw_gpx_embedded_in_json": False,
                "coordinates_embedded": False,
                "precise_timestamps_embedded": False,
            },
        )

    segment_by_from_checkpoint = {
        segment.get("from_candidate_id"): segment for segment in segments
    }
    for checkpoint in checkpoints:
        checkpoint_id = checkpoint.get("candidate_id", "")
        checkpoint_event = checkpoint_event_by_id.get(checkpoint_id, {})
        label = checkpoint.get("label") or checkpoint_id
        append_event(
            "checkpoint_detected",
            (
                f"Projected checkpoint candidate {label} is visible on the "
                "shared GPX timeline."
            ),
            {
                "timestamp": checkpoint_event.get("observed_at"),
                "subject_ref": checkpoint_id,
                "map_target_ids": [checkpoint_id],
                "checkpoint_id": checkpoint_id,
                "checkpoint_label": label,
                "checkpoint_type": checkpoint.get("checkpoint_type"),
                "progress_m": checkpoint_event.get("progress_m"),
                "route_point_index": checkpoint.get("route_point_index"),
                "lat": checkpoint.get("lat"),
                "lon": checkpoint.get("lon"),
                "safety_level": "L0_PRETRIP_PROJECTION",
                "projection_event_type": "checkpoint_candidate",
            },
        )
        segment = segment_by_from_checkpoint.get(checkpoint_id)
        if not segment:
            continue
        segment_label = segment.get("label") or segment.get("candidate_id", "")
        append_event(
            "route_progress_evaluated",
            (
                f"Projected segment frame {segment_label} links "
                f"{segment.get('from_candidate_id')} to {segment.get('to_candidate_id')}."
            ),
            {
                "timestamp": checkpoint_event.get("observed_at"),
                "subject_ref": segment.get("candidate_id"),
                "map_target_ids": [
                    segment.get("candidate_id"),
                    segment.get("from_candidate_id"),
                    segment.get("to_candidate_id"),
                ],
                "segment_id": segment.get("candidate_id"),
                "from_checkpoint_id": segment.get("from_candidate_id"),
                "to_checkpoint_id": segment.get("to_candidate_id"),
                "distance_m": segment.get("distance_m"),
                "elevation_gain_m": segment.get("elevation_gain_m"),
                "elevation_loss_m": segment.get("elevation_loss_m"),
                "route_point_start_index": segment.get("route_point_start_index"),
                "route_point_end_index": segment.get("route_point_end_index"),
                "observation_count": segment.get("route_point_end_index", 0),
                "safety_level": "L0_PRETRIP_PROJECTION",
            "projection_event_type": "segment_candidate",
            },
        )

    for checkpoint in view.get("gis_perception_timeline", {}).get("checkpoint_candidates", []):
        checkpoint_id = checkpoint.get("candidate_id", "")
        append_event(
            "gis_perception_checkpoint_projected",
            (
                f"Aggregated GIS perception checkpoint {checkpoint_id} is "
                "visible for pretrip review."
            ),
            {
                "subject_ref": checkpoint_id,
                "map_target_ids": checkpoint.get("map_target_ids", [checkpoint_id]),
                "checkpoint_id": checkpoint_id,
                "checkpoint_type": checkpoint.get("checkpoint_type"),
                "lat": checkpoint.get("lat"),
                "lon": checkpoint.get("lon"),
                "safety_level": "L0_PRETRIP_PROJECTION",
                "projection_event_type": "gis_perception_checkpoint_candidate",
                "source_attribution_count": checkpoint.get(
                    "source_attribution_count",
                    len(checkpoint.get("source_attribution", [])),
                ),
                "aggregation": checkpoint.get("aggregation", {}),
            },
        )

    for physiologic_event in (
        view.get("physiologic_timeline_projection", {}).get("events") or []
    ):
        events.append(
            _physiologic_debug_projection_event(
                physiologic_event,
                project_id=project_id,
                sequence=len(events) + 1,
            )
        )

    for reducer_event in _runtime_safety_reducer_debug_projection_events(
        view.get("runtime_safety_reducer_projection", {}),
        project_id=project_id,
        start_sequence=len(events) + 1,
    ):
        events.append(reducer_event)

    append_event(
        "debug_session_completed",
        f"{project_id} debug projection completed without runtime mutation.",
        {
            "timestamp": route.get("ended_at"),
            "subject_ref": f"project.{project_id}",
            "map_target_ids": ["route"],
            "observations_processed": route["point_count"],
            "safety_level": "L0_PRETRIP_PROJECTION",
            "checkpoint_candidate_count": len(checkpoints),
            "segment_candidate_count": len(segments),
        },
    )
    return events


def _physiologic_timeline_projection_summary(
    project_id: str,
    project: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    boundary = {
        "projection_only": True,
        "pretrip_candidate_evidence_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "medical_diagnosis": False,
        "raw_health_payload_shared": False,
        "raw_track_shared": False,
        "exact_timestamps_shared": False,
        "home_work_trace_shared": False,
    }
    projection_ref = project.get("physiologic_timeline_projection_ref")
    artifact_index_ref = project.get("physiologic_artifact_index_ref")
    artifact_dir_ref = project.get("physiologic_artifact_dir_ref")
    projection_path = _optional_project_ref_path(project_root, projection_ref)
    artifact_index_path = _optional_project_ref_path(project_root, artifact_index_ref)
    artifact_dir_path = _optional_project_ref_path(project_root, artifact_dir_ref)

    try:
        if projection_path is not None and projection_path.exists():
            projection = PhysiologicTimelineProjection.model_validate(
                _load_json(projection_path)
            )
            source_path = str(projection_ref)
        elif (
            artifact_index_path is not None
            and artifact_index_path.exists()
        ) or (
            artifact_dir_path is not None
            and artifact_dir_path.exists()
        ):
            projection = build_physio_timeline_projection(
                index_path=artifact_index_path
                if artifact_index_path is not None and artifact_index_path.exists()
                else None,
                artifact_dir=artifact_dir_path
                if artifact_dir_path is not None and artifact_dir_path.exists()
                else None,
                root=project_root,
                session_id=f"pretrip_projection.{project_id}.physiologic",
                mission_id=project_id,
            )
            source_path = str(artifact_index_ref or artifact_dir_ref)
        else:
            return {
                "artifact_kind": "pretrip_physio_timeline_projection_summary",
                "status": "missing",
                "project_id": project_id,
                "source_path": str(projection_ref or artifact_index_ref or artifact_dir_ref or ""),
                "event_count": 0,
                "events": [],
                "counts": {"event_count": 0},
                "boundary": boundary,
            }
    except (OSError, ValueError, TypeError) as exc:
        return {
            "artifact_kind": "pretrip_physio_timeline_projection_summary",
            "status": "error",
            "project_id": project_id,
            "source_path": str(projection_ref or artifact_index_ref or artifact_dir_ref or ""),
            "event_count": 0,
            "events": [],
            "counts": {"event_count": 0},
            "error_type": type(exc).__name__,
            "error": str(exc),
            "boundary": boundary,
        }

    payload = projection.model_dump(mode="json")
    return {
        "artifact_kind": "pretrip_physio_timeline_projection_summary",
        "status": "ready",
        "project_id": project_id,
        "source_path": source_path,
        "source_provider": payload["source_provider"],
        "source_sha256": payload["sha256"],
        "event_count": payload["event_count"],
        "events": payload["events"],
        "counts": payload["counts"],
        "source_artifacts": payload.get("source_artifacts", {}),
        "data_quality": payload["data_quality"],
        "privacy": payload["privacy"],
        "boundary": {
            **boundary,
            **payload["boundary"],
            "projection_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
        },
    }


def _physiologic_debug_projection_event(
    event: dict[str, Any],
    *,
    project_id: str,
    sequence: int,
) -> dict[str, Any]:
    payload = {
        **(event.get("payload") or {}),
    }
    map_target_ids = _unique_string_list(
        [
            *(event.get("map_refs") or []),
            *(payload.get("map_target_ids") or []),
            payload.get("segment_id"),
            payload.get("checkpoint_id"),
        ]
    )
    source_refs = _unique_string_list(
        [
            *(event.get("source_refs") or []),
            *(payload.get("source_refs") or []),
        ]
    )
    payload_boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
    payload["boundary"] = {
        **payload_boundary,
        "projection_only": True,
        "pretrip_candidate_evidence_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "medical_diagnosis": False,
        "raw_health_payload_shared": False,
        "raw_track_shared": False,
        "exact_timestamps_shared": False,
        "home_work_trace_shared": False,
    }
    payload.update(
        {
            "project_id": project_id,
            "profile": "pretrip_debug_projection",
            "import_stage": "physiologic_timeline_projection",
            "gate": payload.get("gate") or "physiologic_gate",
            "projection_only": True,
            "runtime_safety_truth": False,
            "map_target_ids": map_target_ids,
            "source_refs": source_refs,
        }
    )
    return {
        "event_id": event.get("event_id")
        or f"debug_event.pretrip_projection.{project_id}.physiologic.{sequence:06d}",
        "session_id": event.get("session_id")
        or f"pretrip_projection.{project_id}.physiologic",
        "mission_id": event.get("mission_id") or project_id,
        "sequence": sequence,
        "timestamp": event.get("timestamp") or "offset:physiologic",
        "phase": event.get("phase") or "phase35",
        "kind": event.get("kind") or "physiologic_gate_window",
        "severity": event.get("severity") or "info",
        "summary": event.get("summary")
        or "Physiologic gate projection available for debug review.",
        "subject_ref": event.get("subject_ref") or "physiologic_gate",
        "correlation_refs": _unique_string_list(
            [
                *(event.get("correlation_refs") or []),
                *source_refs,
                *map_target_ids,
            ]
        ),
        "source_refs": source_refs,
        "map_refs": map_target_ids,
        "payload": payload,
    }


def _runtime_safety_reducer_projection_summary(
    project_id: str,
    project: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    boundary = {
        "projection_only": True,
        "pretrip_candidate_evidence_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_alert_sent": False,
        "medical_diagnosis": False,
        "raw_health_payload_shared": False,
        "raw_track_shared": False,
        "exact_timestamps_shared": False,
        "home_work_trace_shared": False,
    }
    gate_batch_ref = project.get("runtime_safety_gate_event_batch_ref")
    reducer_ref = project.get("runtime_safety_reducer_dry_run_ref")
    phase1_adapter_ref = project.get("runtime_safety_phase1_adapter_ref")
    gate_batch_path = _optional_project_ref_path(project_root, gate_batch_ref)
    reducer_path = _optional_project_ref_path(project_root, reducer_ref)
    phase1_adapter_path = _optional_project_ref_path(project_root, phase1_adapter_ref)

    reducer: RuntimeSafetyReducerDecision | None = None
    phase1_adapter: RuntimeSafetyPhase1AdapterResult | None = None
    source_path = str(reducer_ref or gate_batch_ref or phase1_adapter_ref or "")
    try:
        if reducer_path is not None and reducer_path.exists():
            reducer = RuntimeSafetyReducerDecision.model_validate(
                _load_json(reducer_path)
            )
        elif gate_batch_path is not None and gate_batch_path.exists():
            batch = ScoutRuntimeSafetyGateEventBatch.model_validate(
                _load_json(gate_batch_path)
            )
            reducer = reduce_runtime_safety_gate_events(
                batch,
                source_path=str(gate_batch_ref),
            )
        if phase1_adapter_path is not None and phase1_adapter_path.exists():
            phase1_adapter = RuntimeSafetyPhase1AdapterResult.model_validate(
                _load_json(phase1_adapter_path)
            )
    except (OSError, ValueError, TypeError) as exc:
        return {
            "artifact_kind": "pretrip_runtime_safety_reducer_projection_summary",
            "status": "error",
            "project_id": project_id,
            "source_path": source_path,
            "event_count": 0,
            "events": [],
            "counts": {"event_count": 0},
            "error_type": type(exc).__name__,
            "error": str(exc),
            "boundary": boundary,
        }

    if reducer is None and phase1_adapter is None:
        return {
            "artifact_kind": "pretrip_runtime_safety_reducer_projection_summary",
            "status": "missing",
            "project_id": project_id,
            "source_path": source_path,
            "event_count": 0,
            "events": [],
            "counts": {"event_count": 0},
            "boundary": boundary,
        }

    reducer_payload = reducer.model_dump(mode="json") if reducer else None
    phase1_payload = phase1_adapter.model_dump(mode="json") if phase1_adapter else None
    event_count = int(reducer_payload is not None) + int(phase1_payload is not None)
    source_refs = _unique_string_list(
        [
            gate_batch_ref,
            reducer_ref,
            phase1_adapter_ref,
            reducer_payload.get("source_path") if reducer_payload else None,
            reducer_payload.get("sha256") if reducer_payload else None,
            phase1_payload.get("source_path") if phase1_payload else None,
            phase1_payload.get("sha256") if phase1_payload else None,
        ]
    )
    return {
        "artifact_kind": "pretrip_runtime_safety_reducer_projection_summary",
        "status": "ready",
        "project_id": project_id,
        "source_path": source_path,
        "source_refs": source_refs,
        "event_count": event_count,
        "reducer_dry_run": reducer_payload,
        "phase1_adapter_result": phase1_payload,
        "events": [],
        "counts": {
            "event_count": event_count,
            "gate_event_count": (
                reducer_payload.get("gate_event_count") if reducer_payload else 0
            ),
            "contributing_gate_count": (
                len(reducer_payload.get("contributing_gate_ids", []))
                if reducer_payload
                else 0
            ),
            "corroborating_gate_count": (
                len(reducer_payload.get("corroborating_gate_ids", []))
                if reducer_payload
                else 0
            ),
            "phase1_adapter_event_count": int(phase1_payload is not None),
        },
        "boundary": boundary,
    }


def _runtime_safety_reducer_debug_projection_events(
    summary: dict[str, Any],
    *,
    project_id: str,
    start_sequence: int,
) -> list[dict[str, Any]]:
    if summary.get("status") != "ready":
        return []
    source_refs = _unique_string_list(summary.get("source_refs") or [])
    reducer = summary.get("reducer_dry_run")
    phase1_adapter = summary.get("phase1_adapter_result")
    events: list[dict[str, Any]] = []
    sequence = start_sequence
    map_target_ids = _runtime_safety_reducer_map_target_ids(reducer)

    if isinstance(reducer, dict):
        boundary = {
            **(reducer.get("boundary") or {}),
            "projection_only": True,
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "medical_diagnosis": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
            "home_work_trace_shared": False,
        }
        payload = {
            "project_id": project_id,
            "profile": "pretrip_debug_projection",
            "projection_event_type": "runtime_safety_reducer_dry_run",
            "import_stage": "runtime_safety_reducer_projection",
            "gate": "multi_gate_safety_reducer",
            "projection_only": True,
            "runtime_safety_truth": False,
            "selected_gate_id": reducer.get("selected_gate_id"),
            "selected_event_id": reducer.get("selected_event_id"),
            "highest_severity": reducer.get("highest_severity"),
            "state": reducer.get("reducer_state"),
            "recommendation": reducer.get("recommendation"),
            "ln_transition_candidate": reducer.get("ln_transition_candidate"),
            "ln_level_candidate": reducer.get("ln_level_candidate"),
            "proposed_ln_transition_candidate": reducer.get(
                "proposed_ln_transition_candidate"
            ),
            "proposed_ln_level_candidate": reducer.get(
                "proposed_ln_level_candidate"
            ),
            "contributing_gate_ids": reducer.get("contributing_gate_ids", []),
            "corroborating_gate_ids": reducer.get("corroborating_gate_ids", []),
            "suppressed_gate_ids": reducer.get("suppressed_gate_ids", []),
            "suppressed_reasons": reducer.get("suppressed_reasons", []),
            "policy_trace": reducer.get("policy_trace", []),
            "hysteresis": reducer.get("hysteresis", {}),
            "eta_delay_minutes": reducer.get("eta_delay_minutes"),
            "source_refs": source_refs,
            "map_target_ids": map_target_ids,
            "boundary": boundary,
        }
        events.append(
            {
                "event_id": (
                    f"debug_event.runtime_safety_reducer."
                    f"{project_id}.{sequence:06d}"
                ),
                "session_id": f"pretrip_projection.{project_id}.runtime_safety",
                "mission_id": project_id,
                "sequence": sequence,
                "timestamp": "offset:runtime-safety-reducer",
                "phase": "phase35",
                "kind": "runtime_safety_reducer_dry_run",
                "severity": _runtime_safety_event_severity(
                    reducer.get("ln_level_candidate")
                ),
                "summary": (
                    "Runtime safety reducer dry-run: "
                    f"{reducer.get('recommendation', 'continue_monitoring')}"
                ),
                "subject_ref": "runtime_safety_reducer",
                "correlation_refs": _unique_string_list(
                    [
                        *source_refs,
                        *map_target_ids,
                        *(reducer.get("contributing_gate_ids") or []),
                    ]
                ),
                "source_refs": source_refs,
                "map_refs": map_target_ids,
                "payload": payload,
            }
        )
        sequence += 1

    if isinstance(phase1_adapter, dict):
        boundary = {
            **(phase1_adapter.get("boundary") or {}),
            "projection_only": True,
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_safety_truth": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_alert_sent": False,
            "medical_diagnosis": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
            "home_work_trace_shared": False,
        }
        payload = {
            "project_id": project_id,
            "profile": "pretrip_debug_projection",
            "projection_event_type": "runtime_safety_phase1_adapter_result",
            "import_stage": "runtime_safety_reducer_projection",
            "gate": "multi_gate_safety_reducer",
            "projection_only": True,
            "runtime_safety_truth": False,
            "status": phase1_adapter.get("status"),
            "state": phase1_adapter.get("status"),
            "phase1_adapter_enabled": phase1_adapter.get(
                "phase1_adapter_enabled"
            ),
            "human_review_approved": phase1_adapter.get(
                "human_review_approved"
            ),
            "transition_request_prepared": phase1_adapter.get(
                "transition_request_prepared"
            ),
            "phase1_transition_candidate": phase1_adapter.get(
                "phase1_transition_candidate"
            ),
            "selected_reducer_sha256": phase1_adapter.get(
                "selected_reducer_sha256"
            ),
            "ln_transition_candidate": phase1_adapter.get(
                "selected_reducer_transition_candidate"
            ),
            "ln_level_candidate": phase1_adapter.get(
                "selected_reducer_level_candidate"
            ),
            "source_refs": source_refs,
            "map_target_ids": map_target_ids,
            "boundary": boundary,
        }
        events.append(
            {
                "event_id": (
                    f"debug_event.runtime_safety_phase1_adapter."
                    f"{project_id}.{sequence:06d}"
                ),
                "session_id": f"pretrip_projection.{project_id}.runtime_safety",
                "mission_id": project_id,
                "sequence": sequence,
                "timestamp": "offset:runtime-safety-phase1-adapter",
                "phase": "phase35",
                "kind": "runtime_safety_phase1_adapter_result",
                "severity": _runtime_safety_event_severity(
                    phase1_adapter.get("selected_reducer_level_candidate")
                ),
                "summary": (
                    "Runtime safety Phase 1 adapter result: "
                    f"{phase1_adapter.get('status', 'unknown')}"
                ),
                "subject_ref": "runtime_safety_phase1_adapter",
                "correlation_refs": _unique_string_list([*source_refs, *map_target_ids]),
                "source_refs": source_refs,
                "map_refs": map_target_ids,
                "payload": payload,
            }
        )
    return events


def _runtime_safety_reducer_map_target_ids(
    reducer: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(reducer, dict):
        return []
    return _unique_string_list(
        [
            target
            for summary in reducer.get("gate_summaries", [])
            if isinstance(summary, dict)
            for target in summary.get("map_target_ids", [])
        ]
    )


def _runtime_safety_event_severity(level: Any) -> str:
    token = str(level or "")
    if "L4" in token:
        return "critical"
    if "L3" in token:
        return "warning"
    if "L2" in token:
        return "warning"
    return "info"


def _optional_project_ref_path(project_root: Path, ref: Any) -> Path | None:
    if not ref:
        return None
    path = Path(str(ref)).expanduser()
    return path if path.is_absolute() else project_root / path


def _unique_string_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def list_pretrip_admin_projects(
    *,
    workspace_root: Path | None = None,
) -> list[dict[str, str]]:
    projects = [
        {
            "project_id": CHILAI_NANHUA_DAY1_PROJECT_ID,
            "name": "能高安東軍縱走 GPX corpus",
            "kind": "phase4_pretrip_fixture",
        }
    ]
    if workspace_root is None:
        return projects

    root = Path(workspace_root).expanduser()
    candidates = []
    if (root / "project.json").exists():
        candidates.append(root / "project.json")
    candidates.extend(sorted(root.glob("*/project.json")))
    project_index_by_id = {
        project["project_id"]: index for index, project in enumerate(projects)
    }
    for project_path in candidates:
        try:
            project = _load_json(project_path)
        except (json.JSONDecodeError, OSError):
            continue
        project_id = str(project.get("project_id") or "")
        if not project_id:
            continue
        record = {
            "project_id": project_id,
            "name": str(project.get("route_name") or project_id),
            "kind": str(project.get("import_profile") or "phase4_pretrip_workspace"),
        }
        if project_id in project_index_by_id:
            projects[project_index_by_id[project_id]] = record
            continue
        project_index_by_id[project_id] = len(projects)
        projects.append(record)
    return projects


def _project_summary(
    project: dict[str, Any],
    route_summary: dict[str, Any],
    pretrip_package: dict[str, Any],
    source_refs: dict[str, str],
) -> dict[str, Any]:
    return {
        "project_id": project["project_id"],
        "source_id": project["project_id"],
        "source_path": source_refs["project"],
        "evidence_type": "pretrip_project",
        "route_name": route_summary["route_name"],
        "package_id": pretrip_package["package_id"],
        "status": pretrip_package["status"],
        "version": pretrip_package["version"],
        "notes": project.get("notes", []),
        "counts": {
            key: value
            for key, value in project.items()
            if key.endswith("_count") and isinstance(value, int)
        },
    }


def _candidate_list(
    candidates: list[dict[str, Any]],
    *,
    source_path: str,
    evidence_type: str,
    display_geometry: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    display_geometry = display_geometry or {}
    return [
        {
            **candidate,
            **_planning_candidate_provenance(
                candidate,
                source_path=source_path,
                evidence_type=evidence_type,
                default_summary=(
                    f"{evidence_type} projected from pretrip planning artifacts; "
                    "candidate-only evidence, not runtime safety truth."
                ),
            ),
            "source_id": candidate["candidate_id"],
            "source_path": source_path,
            "evidence_type": evidence_type,
            **(
                {"display_geometry": display_geometry[candidate["candidate_id"]]}
                if candidate["candidate_id"] in display_geometry
                else {}
            ),
        }
        for candidate in candidates
    ]


def _segment_display_geometry_by_id(
    payload: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not payload:
        return {}
    source_path = payload.get("source_path") or "outputs/segment_display_geometry.json"
    return {
        item["segment_candidate_id"]: {
            "source_id": item["segment_candidate_id"],
            "source_path": source_path,
            "evidence_type": "pretrip_segment_display_geometry",
            **_projection_record_metadata(
                item,
                source_path=source_path,
                evidence_type="pretrip_segment_display_geometry",
                source_kind="segment_display_geometry",
                identity_keys=("segment_candidate_id", "source_point_count"),
                review_state="display_geometry_only",
                confidence="medium",
                stale_risk="medium",
                extractor_version="pretrip_segment_display_geometry.projection.v1",
                prompt_version="not_applicable_deterministic_display_geometry.v1",
                summary=(
                    "Segment display geometry for admin map focus and rendering; "
                    "derived visualization evidence only, not runtime safety truth."
                ),
            ),
            "source_point_count": item.get("source_point_count"),
            "display_point_count": item.get(
                "display_point_count",
                len(item.get("coordinates", [])),
            ),
            "display_segment_count": item.get(
                "display_segment_count",
                len(item.get("coordinate_segments", [])),
            ),
            "coordinates": item.get("coordinates", []),
            "coordinate_segments": item.get("coordinate_segments", []),
            "segment_boundary_preserved": item.get(
                "segment_boundary_preserved",
                False,
            ),
            "resume_segment": item.get("resume_segment", False),
            "resume_gap_count": item.get("resume_gap_count", 0),
            "max_gap_m": item.get("max_gap_m"),
            "resume_gaps": item.get("resume_gaps", []),
            "boundary": payload.get("boundary", {}),
        }
        for item in payload.get("segments", [])
    }


def _display_geometry_coordinate_segments(
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


def _route_coordinate_at_distance(
    display_geometry: dict[str, Any] | None,
    distance_m: Any,
) -> dict[str, float] | None:
    if not isinstance(display_geometry, dict):
        return None
    try:
        target_m = float(distance_m)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(target_m):
        return None

    route_segments = display_geometry.get("route_segments")
    if isinstance(route_segments, list):
        for route_segment in route_segments:
            if not isinstance(route_segment, dict):
                continue
            start_m = _coerce_float(route_segment.get("start_distance_m"))
            end_m = _coerce_float(route_segment.get("end_distance_m"))
            coordinates = _normalized_coordinate_segment(
                route_segment.get("coordinates", [])
            )
            if (
                start_m is None
                or end_m is None
                or end_m <= start_m
                or len(coordinates) < 2
            ):
                continue
            if start_m <= target_m <= end_m:
                return _coordinate_at_segment_fraction(
                    coordinates,
                    (target_m - start_m) / (end_m - start_m),
                )

    segments = _display_geometry_coordinate_segments(display_geometry)
    first_point: dict[str, float] | None = None
    last_point: dict[str, float] | None = None
    cumulative_m = 0.0
    for segment in segments:
        if not segment:
            continue
        first_point = first_point or segment[0]
        last_point = segment[-1]
        if target_m <= 0:
            return dict(segment[0])
        for previous, current in zip(segment, segment[1:]):
            segment_m = _haversine_m(
                previous["lat"],
                previous["lon"],
                current["lat"],
                current["lon"],
            )
            if segment_m <= 0:
                continue
            if cumulative_m + segment_m >= target_m:
                ratio = max(0.0, min(1.0, (target_m - cumulative_m) / segment_m))
                return {
                    "lat": previous["lat"] + (current["lat"] - previous["lat"]) * ratio,
                    "lon": previous["lon"] + (current["lon"] - previous["lon"]) * ratio,
                }
            cumulative_m += segment_m
    if first_point is None:
        return None
    return dict(last_point or first_point)


def _coordinate_at_segment_fraction(
    segment: list[dict[str, float]],
    fraction: float,
) -> dict[str, float] | None:
    if not segment:
        return None
    fraction = max(0.0, min(1.0, fraction))
    if fraction <= 0:
        return dict(segment[0])
    if fraction >= 1:
        return dict(segment[-1])
    lengths: list[float] = []
    total_m = 0.0
    for previous, current in zip(segment, segment[1:]):
        length_m = _haversine_m(
            previous["lat"],
            previous["lon"],
            current["lat"],
            current["lon"],
        )
        lengths.append(length_m)
        total_m += max(0.0, length_m)
    if total_m <= 0:
        return dict(segment[0])
    target_m = total_m * fraction
    cumulative_m = 0.0
    for index, length_m in enumerate(lengths):
        if length_m <= 0:
            continue
        if cumulative_m + length_m >= target_m:
            previous = segment[index]
            current = segment[index + 1]
            ratio = max(0.0, min(1.0, (target_m - cumulative_m) / length_m))
            return {
                "lat": previous["lat"] + (current["lat"] - previous["lat"]) * ratio,
                "lon": previous["lon"] + (current["lon"] - previous["lon"]) * ratio,
            }
        cumulative_m += length_m
    return dict(segment[-1])


def _boss_point_source_coordinate(point: dict[str, Any]) -> dict[str, float] | None:
    try:
        lat = float(point["lat"])
        lon = float(point["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon}


def _boss_point_map_target_ids(point: dict[str, Any]) -> list[str]:
    return _unique_limited(
        [
            point.get("boss_point_id"),
            point.get("source_mcp_id"),
            point.get("source_candidate_id"),
            point.get("label"),
            *((point.get("source_refs") or []) if isinstance(point.get("source_refs"), list) else []),
        ],
        limit=16,
    )


def _boss_point_declared_coordinate_source(point: dict[str, Any]) -> str:
    route_pressure = (
        (point.get("route_boss_demand") or {}).get("route_pressure_profile")
        if isinstance(point.get("route_boss_demand"), dict)
        else {}
    )
    if not isinstance(route_pressure, dict):
        route_pressure = {}
    return str(
        point.get("coordinate_source")
        or route_pressure.get("coordinate_source")
        or "source_coordinate"
    )


def _route_display_coordinate_source(route_display_geometry: dict[str, Any] | None) -> str:
    if (
        isinstance(route_display_geometry, dict)
        and route_display_geometry.get("evidence_type")
        == "pretrip_overpass_risk_ribbon_centerline"
    ):
        return "overpass_risk_ribbon_route_distance_interpolation"
    return "route_distance_interpolation"


def _boss_point_display_label(point: dict[str, Any]) -> str:
    display_label = str(point.get("display_label") or "").strip()
    if display_label:
        return display_label
    alias = str((point.get("display_theme") or {}).get("alias") or "").strip()
    label = str(point.get("label") or "").strip()
    if alias and label:
        return f"{alias} {label}"
    return label or alias or str(point.get("boss_point_id") or "Boss Point")


def _boss_point_display_coordinate(
    point: dict[str, Any],
    *,
    route_display_geometry: dict[str, Any] | None,
    route_bounds: dict[str, float] | None,
) -> dict[str, Any]:
    source_coordinate = _boss_point_source_coordinate(point)
    if source_coordinate is not None and _point_within_projection_bounds(
        source_coordinate,
        route_bounds,
    ):
        coordinate_source = _boss_point_declared_coordinate_source(point)
        return {
            "lat": source_coordinate["lat"],
            "lon": source_coordinate["lon"],
            "coordinate_source": coordinate_source,
            "map_coordinate_source": coordinate_source,
            "coordinate_uncertain": False,
            "source_coordinate": dict(source_coordinate),
            "source_coordinate_out_of_route_bounds": False,
        }

    route_position = point.get("route_position") or {}
    distance_m = (
        route_position.get("distance_m")
        if isinstance(route_position, dict)
        else None
    )
    interpolated = _route_coordinate_at_distance(route_display_geometry, distance_m)
    if interpolated is not None:
        coordinate_source = _route_display_coordinate_source(route_display_geometry)
        metadata = {
            "lat": interpolated["lat"],
            "lon": interpolated["lon"],
            "coordinate_source": coordinate_source,
            "map_coordinate_source": coordinate_source,
            "coordinate_uncertain": True,
            "source_coordinate_out_of_route_bounds": source_coordinate is not None,
        }
        if source_coordinate is not None:
            metadata["source_coordinate"] = dict(source_coordinate)
        return metadata

    if source_coordinate is not None:
        coordinate_source = _boss_point_declared_coordinate_source(point)
        return {
            "lat": source_coordinate["lat"],
            "lon": source_coordinate["lon"],
            "coordinate_source": coordinate_source,
            "map_coordinate_source": f"{coordinate_source}_unbounded_fallback",
            "coordinate_uncertain": route_bounds is not None,
            "source_coordinate": dict(source_coordinate),
            "source_coordinate_out_of_route_bounds": route_bounds is not None,
        }
    return {
        "lat": None,
        "lon": None,
        "coordinate_source": "missing_coordinate",
        "map_coordinate_source": "missing_coordinate",
        "coordinate_uncertain": True,
        "source_coordinate_out_of_route_bounds": False,
    }


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


def _route_point_samples(
    route_summary: dict[str, Any],
    checkpoints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    samples = [
        {
            "sample_type": "route_start",
            "index": 0,
            "lat": checkpoints[0]["lat"],
            "lon": checkpoints[0]["lon"],
            "label": checkpoints[0]["label"],
        },
        {
            "sample_type": "route_mid_checkpoint",
            "index": checkpoints[len(checkpoints) // 2]["route_point_index"],
            "lat": checkpoints[len(checkpoints) // 2]["lat"],
            "lon": checkpoints[len(checkpoints) // 2]["lon"],
            "label": checkpoints[len(checkpoints) // 2]["label"],
        },
        {
            "sample_type": "route_end",
            "index": route_summary["point_count"] - 1,
            "lat": checkpoints[-1]["lat"],
            "lon": checkpoints[-1]["lon"],
            "label": checkpoints[-1]["label"],
        },
    ]
    return samples


def _route_polyline(map_context: dict[str, Any]) -> list[dict[str, float]]:
    for feature in map_context.get("features", []):
        if feature.get("geometry", {}).get("type") != "LineString":
            continue
        return [
            {"lon": float(lon), "lat": float(lat)}
            for lon, lat in feature["geometry"].get("coordinates", [])
        ]
    return []


def _map_candidate_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["source_artifact"]["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_map_candidates",
        "source_metadata": payload.get("source_metadata", {}),
        "corridor_candidates": _decorate_map_candidates(
            payload.get("corridor_candidates", []),
            source_path,
            "pretrip_map_corridor_candidate",
        ),
        "hazard_candidates": _decorate_map_candidates(
            payload.get("hazard_candidates", []),
            source_path,
            "pretrip_map_hazard_candidate",
        ),
        "poi_candidates": _decorate_map_candidates(
            payload.get("poi_candidates", []),
            source_path,
            "pretrip_map_poi_candidate",
        ),
        "counts": {
            "corridor_candidates": len(payload.get("corridor_candidates", [])),
            "hazard_candidates": len(payload.get("hazard_candidates", [])),
            "poi_candidates": len(payload.get("poi_candidates", [])),
        },
    }


def _decorate_map_candidates(
    candidates: list[dict[str, Any]],
    source_path: str,
    evidence_type: str,
) -> list[dict[str, Any]]:
    return [
        {
            **candidate,
            **_planning_candidate_provenance(
                candidate,
                source_path=source_path,
                evidence_type=evidence_type,
                default_summary=(
                    f"{evidence_type} projected from offline map evidence; "
                    "candidate-only evidence, not runtime safety truth."
                ),
            ),
            "source_id": candidate["candidate_id"],
            "source_path": source_path,
            "evidence_type": evidence_type,
        }
        for candidate in candidates
    ]


def _planning_candidate_provenance(
    candidate: dict[str, Any],
    *,
    source_path: str,
    evidence_type: str,
    default_summary: str,
) -> dict[str, Any]:
    provenance = [
        item
        for item in candidate.get("provenance", []) or []
        if isinstance(item, dict)
    ]
    source_refs = _unique_limited(
        [
            source_path,
            candidate.get("candidate_id"),
            *list(candidate.get("source_refs") or []),
            *[
                item.get("source_ref")
                for item in provenance
            ],
            *[
                item.get("uri")
                for item in provenance
            ],
        ],
        limit=32,
    )
    extractor_version = (
        candidate.get("extractor_version")
        or _candidate_provenance_method(provenance)
        or "pretrip_candidate_projection.v1"
    )
    model_hash = candidate.get("model_output_sha256") or _stable_projection_hash(
        {
            "candidate_id": candidate.get("candidate_id"),
            "evidence_type": evidence_type,
            "source_refs": source_refs,
            "review_state": candidate.get("review_state"),
        }
    )
    return {
        "source_refs": source_refs,
        "source_attribution": candidate.get("source_attribution")
        or _planning_source_attribution(
            provenance,
            source_path=source_path,
            candidate_id=candidate.get("candidate_id"),
            confidence=candidate.get("confidence", "medium"),
            stale_risk=candidate.get("stale_risk", "medium"),
        ),
        "confidence": candidate.get("confidence", "medium"),
        "stale_risk": candidate.get("stale_risk", "medium"),
        "review_state": candidate.get("review_state", "needs_review"),
        "candidate_only": candidate.get("candidate_only", True),
        "runtime_safety_truth": candidate.get("runtime_safety_truth", False),
        "extractor_version": extractor_version,
        "pydantic_ai_prompt_version": candidate.get(
            "pydantic_ai_prompt_version",
            "not_applicable_deterministic_pretrip_projection.v1",
        ),
        "model_output_sha256": str(model_hash),
        "model_output_summary": candidate.get("model_output_summary")
        or default_summary,
    }


def _candidate_provenance_method(provenance: list[dict[str, Any]]) -> str | None:
    for item in provenance:
        method = item.get("method")
        if method:
            return str(method)
    return None


def _planning_source_attribution(
    provenance: list[dict[str, Any]],
    *,
    source_path: str,
    candidate_id: Any,
    confidence: Any,
    stale_risk: Any,
) -> list[dict[str, Any]]:
    if not provenance:
        return [
            {
                "source_kind": "pretrip_artifact",
                "source_ref": source_path,
                "source_candidate_id": str(candidate_id or ""),
                "confidence": confidence,
                "stale_risk": stale_risk,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
    return [
        {
            "source_kind": item.get("source_kind", "pretrip_artifact"),
            "source_ref": item.get("source_ref") or source_path,
            "source_uri": item.get("uri"),
            "source_candidate_id": str(candidate_id or ""),
            "extractor_method": item.get("method"),
            "confidence": confidence,
            "stale_risk": stale_risk,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for item in provenance
    ]


def _summary_with_source(
    payload: dict[str, Any],
    *,
    source_id: str,
    source_path: str,
    evidence_type: str,
    include_keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_path": source_path,
        "evidence_type": evidence_type,
        **{key: payload.get(key) for key in include_keys},
    }


def _review_queue_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["manifest_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_review_queue_manifest",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": payload["boundary"],
        "items": [_review_queue_item(item, source_path) for item in payload.get("items", [])],
    }


def _review_queue_item(item: dict[str, Any], source_path: str) -> dict[str, Any]:
    evidence_summary = item.get("evidence_summary", {})
    source_refs = _review_queue_source_refs(item)
    source_attribution = _review_queue_source_attribution(item, source_refs)
    model_hash = item.get("model_output_sha256") or _stable_projection_hash(
        {
            "item_id": item.get("item_id"),
            "candidate_ref": item.get("candidate_ref"),
            "source_refs": source_refs,
            "evidence_summary": evidence_summary,
        }
    )
    result = {
        **item,
        "source_id": item["item_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_review_queue_item",
        "evidence_summary": _review_queue_evidence_summary(
            item,
            source_path=source_path,
            source_refs=source_refs,
        ),
        "review_state": item.get("review_state", "needs_review"),
        "confidence": item.get("confidence")
        or evidence_summary.get("confidence")
        or evidence_summary.get("ai_confidence")
        or "unknown",
        "stale_risk": item.get("stale_risk")
        or evidence_summary.get("stale_risk")
        or evidence_summary.get("ai_stale_risk")
        or "unknown",
        "candidate_only": item.get("candidate_only", True),
        "runtime_safety_truth": item.get("runtime_safety_truth", False),
        "source_refs": source_refs,
        "source_attribution": source_attribution,
        "extractor_version": item.get(
            "extractor_version",
            "pretrip_admin_review_queue_projection.v1",
        ),
        "pydantic_ai_prompt_version": item.get(
            "pydantic_ai_prompt_version",
            "not_applicable_deterministic_review_queue_projection.v1",
        ),
        "model_output_sha256": str(model_hash),
        "model_output_summary": item.get("model_output_summary")
        or item.get("summary")
        or (
            "Pretrip review queue item; candidate review aid only, "
            "not runtime safety truth."
        ),
        "map_target_ids": _review_item_map_target_ids(item),
    }
    return result


def _review_queue_evidence_summary(
    item: dict[str, Any],
    *,
    source_path: str,
    source_refs: list[str],
) -> dict[str, Any]:
    evidence_summary = item.get("evidence_summary", {})
    if not isinstance(evidence_summary, dict):
        evidence_summary = {}
    confidence = (
        item.get("confidence")
        or evidence_summary.get("confidence")
        or evidence_summary.get("ai_confidence")
        or "unknown"
    )
    stale_risk = (
        item.get("stale_risk")
        or evidence_summary.get("stale_risk")
        or evidence_summary.get("ai_stale_risk")
        or "unknown"
    )
    return {
        **evidence_summary,
        "source_id": f"{item.get('item_id', 'review_item')}.evidence_summary",
        "source_path": source_path,
        "evidence_type": "pretrip_review_queue_evidence_summary",
        **_projection_record_metadata(
            {
                **evidence_summary,
                "item_id": item.get("item_id"),
                "candidate_ref": item.get("candidate_ref"),
                "source_refs": source_refs,
            },
            source_path=source_path,
            evidence_type="pretrip_review_queue_evidence_summary",
            source_kind="review_queue_evidence_summary",
            identity_keys=("item_id", "candidate_ref", "rule_id", "source_refs"),
            review_state=item.get("review_state", "needs_review"),
            confidence=confidence,
            stale_risk=stale_risk,
            extractor_version="pretrip_admin_review_queue_projection.v1",
            prompt_version="not_applicable_deterministic_review_queue_projection.v1",
            summary=(
                "Nested review queue evidence summary for admin detail display; "
                "candidate review aid only, not runtime safety truth."
            ),
            candidate_only=item.get("candidate_only", True),
            runtime_safety_truth=False,
        ),
    }


def _review_queue_source_refs(item: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("source_ref", "candidate_ref"):
        value = item.get(key)
        if value:
            refs.append(str(value))
    evidence_summary = item.get("evidence_summary", {})
    if isinstance(evidence_summary, dict):
        source_artifact_refs = evidence_summary.get("source_artifact_refs", {})
        if isinstance(source_artifact_refs, dict):
            refs.extend(str(value) for value in source_artifact_refs.values() if value)
        for attribution in evidence_summary.get("source_attribution", []) or []:
            if isinstance(attribution, dict):
                for key in ("source_candidate_id", "source_artifact_id", "source_ref"):
                    value = attribution.get(key)
                    if value:
                        refs.append(str(value))
    return list(dict.fromkeys(refs))


def _review_queue_source_attribution(
    item: dict[str, Any],
    source_refs: list[str],
) -> list[dict[str, Any]]:
    evidence_summary = item.get("evidence_summary", {})
    if isinstance(evidence_summary, dict):
        attribution = evidence_summary.get("source_attribution")
        if isinstance(attribution, list) and attribution:
            return attribution
    return [
        {
            "source_kind": item.get("source_artifact_kind", "pretrip_review_source"),
            "source_ref_key": item.get("source_ref_key"),
            "source_candidate_id": item.get("candidate_ref"),
            "source_artifact_ref": item.get("source_ref"),
            "source_refs": source_refs,
            "candidate_only": item.get("candidate_only", True),
            "runtime_safety_truth": False,
        }
    ]


def _projection_record_metadata(
    record: dict[str, Any],
    *,
    source_path: str,
    evidence_type: str,
    source_kind: str,
    identity_keys: tuple[str, ...],
    review_state: str,
    confidence: Any,
    stale_risk: Any,
    extractor_version: str,
    prompt_version: str,
    summary: str,
    candidate_only: bool = True,
    runtime_safety_truth: bool = False,
) -> dict[str, Any]:
    identity_refs = [
        ref
        for key in identity_keys
        for ref in _mcp_source_ref_values(record.get(key))
    ]
    source_refs = _unique_limited(
        [
            source_path,
            *identity_refs,
            *_mcp_source_ref_values(record.get("source_refs")),
            *_mcp_source_ref_values(record.get("target_ids")),
        ],
        limit=64,
    )
    source_candidate_id = (
        record.get("candidate_ref")
        or record.get("item_id")
        or record.get("action_id")
        or record.get("decision_id")
        or record.get("review_id")
        or record.get("request_id")
        or record.get("contribution_id")
        or record.get("imprint_id")
        or record.get("candidate_id")
        or record.get("group_id")
        or ""
    )
    model_hash = record.get("model_output_sha256") or _stable_projection_hash(
        {
            "evidence_type": evidence_type,
            "source_kind": source_kind,
            "source_candidate_id": source_candidate_id,
            "source_refs": source_refs,
        }
    )
    return {
        "source_refs": source_refs,
        "source_attribution": [
            {
                "source_kind": source_kind,
                "source_ref": source_path,
                "source_candidate_id": str(source_candidate_id),
                "confidence": confidence,
                "stale_risk": stale_risk,
                "candidate_only": candidate_only,
                "runtime_safety_truth": runtime_safety_truth,
            }
        ],
        "confidence": confidence,
        "stale_risk": stale_risk,
        "review_state": review_state,
        "candidate_only": candidate_only,
        "runtime_safety_truth": runtime_safety_truth,
        "extractor_version": extractor_version,
        "pydantic_ai_prompt_version": prompt_version,
        "model_output_sha256": str(model_hash),
        "model_output_summary": summary,
    }


def _decorate_admin_summary_metadata(tab: dict[str, Any]) -> None:
    for value in tab.values():
        if not isinstance(value, dict):
            continue
        if not all(key in value for key in ("source_id", "source_path", "evidence_type")):
            continue
        _ensure_admin_summary_metadata(value)


def _ensure_admin_summary_metadata(summary: dict[str, Any]) -> None:
    if all(
        summary.get(field) not in (None, "", [])
        for field in (
            "source_refs",
            "source_attribution",
            "confidence",
            "stale_risk",
            "review_state",
            "candidate_only",
            "runtime_safety_truth",
            "model_output_sha256",
            "model_output_summary",
            "extractor_version",
            "pydantic_ai_prompt_version",
        )
    ):
        return
    boundary = summary.get("boundary") if isinstance(summary.get("boundary"), dict) else {}
    metadata = _projection_record_metadata(
        {
            "source_id": summary.get("source_id"),
            "source_path": summary.get("source_path"),
            "evidence_type": summary.get("evidence_type"),
            "status": summary.get("status"),
            "source_refs": summary.get("source_refs"),
        },
        source_path=str(summary.get("source_path") or ""),
        evidence_type=str(summary.get("evidence_type") or "pretrip_admin_summary"),
        source_kind="pretrip_admin_summary",
        identity_keys=("source_id", "source_path", "evidence_type", "status"),
        review_state=str(summary.get("review_state") or "projection_only"),
        confidence=summary.get("confidence") or "medium",
        stale_risk=summary.get("stale_risk") or "medium",
        extractor_version=str(
            summary.get("extractor_version")
            or "pretrip_admin_summary.projection.v1"
        ),
        prompt_version=str(
            summary.get("pydantic_ai_prompt_version")
            or "not_applicable_deterministic_admin_summary_projection.v1"
        ),
        summary=(
            str(summary.get("evidence_type") or "pretrip admin summary")
            + " summary for admin evidence navigation; candidate/pretrip "
            "projection only, not runtime safety truth."
        ),
        candidate_only=summary.get(
            "candidate_only",
            boundary.get("candidate_only", True),
        )
        is not False,
        runtime_safety_truth=summary.get(
            "runtime_safety_truth",
            boundary.get("runtime_safety_truth", False),
        )
        is True,
    )
    for key, value in metadata.items():
        if summary.get(key) in (None, "", []):
            summary[key] = value


def _review_item_map_target_ids(item: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    candidate_ref = str(item.get("candidate_ref") or "")
    if candidate_ref:
        targets.append(candidate_ref)
    targets.extend(str(ref) for ref in item.get("review_focus", []))

    if candidate_ref.startswith("policy_candidate.chilai_nanhua_day1."):
        targets.append(candidate_ref.removeprefix("policy_candidate.chilai_nanhua_day1."))
    if ".seg." in candidate_ref:
        segment_id = "seg." + candidate_ref.rsplit(".seg.", maxsplit=1)[-1]
        targets.append(segment_id)
    targets.extend(_review_focus_map_aliases(targets))

    deduped: list[str] = []
    for target in targets:
        if target and target not in deduped:
            deduped.append(target)
    return deduped


def _review_focus_map_aliases(targets: list[str]) -> list[str]:
    aliases: list[str] = []
    for target in targets:
        if target in {
            "map.poi.evacuation_exit",
            "map.poi.exit",
            "retreat_route.evacuation_exit",
        }:
            aliases.extend(
                [
                    "retreat.chilai_nanhua_day1.return_to_entry",
                    "map.poi.trailhead_entry",
                    "map.hazard.deep_mountain_no_easy_exit",
                ]
            )
    return aliases


def _review_workbench_summary(
    review_queue: dict[str, Any],
    review_decision_log: dict[str, Any],
    gis_perception_timeline: dict[str, Any],
) -> dict[str, Any]:
    items = review_queue.get("items", [])
    decided_refs = {
        decision.get("candidate_ref")
        for decision in review_decision_log.get("decisions", [])
        if decision.get("candidate_ref")
    }
    category_groups = [
        _review_workbench_group(
            group_id=f"review_group.category.{_safe_view_key(str(category))}",
            group_type="category",
            label=str(category).replace("_", " "),
            items=group_items,
            decided_refs=decided_refs,
        )
        for category, group_items in sorted(_group_by(items, "category").items())
    ]
    severity_groups = [
        _review_workbench_group(
            group_id=f"review_group.severity.{_safe_view_key(str(severity))}",
            group_type="severity",
            label=str(severity),
            items=group_items,
            decided_refs=decided_refs,
        )
        for severity, group_items in sorted(_group_by(items, "severity").items())
    ]
    gis_groups = [
        {
            "group_id": group.get("nearby_group_id"),
            **_projection_record_metadata(
                group,
                source_path=group.get("source_path")
                or "project.json#review-workbench-gis-nearby-group",
                evidence_type="pretrip_review_workbench_gis_nearby_group",
                source_kind="review_workbench_gis_nearby_group",
                identity_keys=("nearby_group_id", "source_refs", "member_candidate_ids"),
                review_state="inspect_group_members",
                confidence=group.get("confidence", "medium"),
                stale_risk=group.get("stale_risk", "medium"),
                extractor_version="pretrip_admin_review_workbench_projection.v1",
                prompt_version="not_applicable_deterministic_review_workbench_projection.v1",
                summary=(
                    "GIS nearby group review-workbench pointer; display grouping "
                    "only, not semantic merge and not runtime safety truth."
                ),
            ),
            "group_type": "gis_nearby_group",
            "label": group.get("display_label")
            or _gis_nearby_group_display_label(group),
            "item_count": group.get("member_count", 0),
            "candidate_refs": group.get("member_candidate_ids", []),
            "semantic_keys": group.get("semantic_keys", []),
            "review_action": "inspect_group_members",
            "bulk_action_allowed": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for group in gis_perception_timeline.get("nearby_groups", [])
    ]
    bulk_eligible_items = [
        item
        for item in items
        if _is_review_workbench_bulk_eligible(item, decided_refs)
    ]
    single_review_items = [
        item
        for item in items
        if item.get("candidate_ref") not in {bulk.get("candidate_ref") for bulk in bulk_eligible_items}
    ]
    return {
        "source_id": f"{review_queue.get('source_id', 'review_queue')}.workbench",
        "source_path": "project.json#review-workbench",
        "evidence_type": "pretrip_review_workbench_projection",
        "status": "projection_only",
        "counts": {
            "item_count": len(items),
            "category_group_count": len(category_groups),
            "severity_group_count": len(severity_groups),
            "gis_nearby_group_count": len(gis_groups),
            "bulk_eligible_count": len(bulk_eligible_items),
            "single_review_required_count": len(single_review_items),
            "decided_count": len(decided_refs),
        },
        "category_groups": category_groups,
        "severity_groups": severity_groups,
        "gis_nearby_groups": gis_groups,
        "triage": {
            "recommended_flow": [
                "clear blocker and warning filters first",
                "use category filters to select review-only repeated candidates",
                "bulk accept/reject only low-friction review items",
                "keep departure bundle and runtime handoff as single-review gates",
            ],
            "bulk_candidate_refs": [
                item["candidate_ref"] for item in bulk_eligible_items
            ],
            "single_review_candidate_refs": [
                item.get("candidate_ref")
                for item in single_review_items
                if item.get("candidate_ref")
            ],
        },
        "boundary": {
            "projection_only": True,
            "candidate_only": True,
            "ai_triage_is_review_aid": True,
            "bulk_actions_require_workspace_review_log": True,
            "package_mutation_allowed": False,
            "runtime_mutation_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "runtime_safety_truth": False,
        },
    }


def _group_by(items: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get(key) or "unknown"), []).append(item)
    return grouped


def _review_workbench_group(
    *,
    group_id: str,
    group_type: str,
    label: str,
    items: list[dict[str, Any]],
    decided_refs: set[str],
) -> dict[str, Any]:
    severity_counts = Counter(str(item.get("severity") or "unknown") for item in items)
    bulk_eligible = [
        item for item in items if _is_review_workbench_bulk_eligible(item, decided_refs)
    ]
    return {
        "group_id": group_id,
        "source_id": group_id,
        "source_path": "project.json#review-workbench",
        "evidence_type": "pretrip_review_workbench_group",
        **_projection_record_metadata(
            {
                "group_id": group_id,
                "candidate_refs": [
                    item["candidate_ref"] for item in items if item.get("candidate_ref")
                ],
                "group_type": group_type,
                "label": label,
            },
            source_path="project.json#review-workbench",
            evidence_type="pretrip_review_workbench_group",
            source_kind="review_workbench_group",
            identity_keys=("group_id", "group_type", "candidate_refs"),
            review_state="projection_only",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_admin_review_workbench_projection.v1",
            prompt_version="not_applicable_deterministic_review_workbench_projection.v1",
            summary=(
                "Review workbench grouping for human review navigation; "
                "projection-only planning aid, not runtime safety truth."
            ),
        ),
        "status": "projection_only",
        "group_type": group_type,
        "label": label,
        "category": label.replace(" ", "_"),
        "item_count": len(items),
        "undecided_count": sum(
            1
            for item in items
            if item.get("candidate_ref") and item.get("candidate_ref") not in decided_refs
        ),
        "bulk_eligible_count": len(bulk_eligible),
        "severity_counts": dict(sorted(severity_counts.items())),
        "candidate_refs": [
            item["candidate_ref"] for item in items if item.get("candidate_ref")
        ],
        "bulk_candidate_refs": [
            item["candidate_ref"] for item in bulk_eligible if item.get("candidate_ref")
        ],
        "review_action": (
            "filter_select_visible"
            if bulk_eligible
            else "single_item_review_required"
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _is_review_workbench_bulk_eligible(
    item: dict[str, Any],
    decided_refs: set[str],
) -> bool:
    candidate_ref = item.get("candidate_ref")
    if not candidate_ref or candidate_ref in decided_refs:
        return False
    if item.get("severity") != "review":
        return False
    return item.get("category") not in {"departure_bundle", "runtime_handoff"}


def _review_draft_log_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["log_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_review_draft_log",
        "status": payload["status"],
        "counts": payload["counts"],
        "category_counts": payload["counts"].get("category_counts", {}),
        "boundary": _summary_boundary(payload["boundary"]),
        "actions": [
            _review_draft_action_summary(action)
            for action in payload.get("actions", [])
        ],
    }


def _review_draft_action_summary(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action["action_id"],
        **_projection_record_metadata(
            action,
            source_path="reviews/review_draft_log.json",
            evidence_type="pretrip_review_draft_action",
            source_kind="review_draft_action",
            identity_keys=("action_id", "candidate_ref", "source_ref_key"),
            review_state=action.get("draft_state", "draft"),
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_review_draft_log.projection.v1",
            prompt_version="not_applicable_deterministic_review_draft_projection.v1",
            summary=(
                "Draft-only review action for admin navigation; "
                "not an accepted planning assumption and not runtime safety truth."
            ),
        ),
        "action_kind": action["action_kind"],
        "category": action["category"],
        "candidate_ref": action["candidate_ref"],
        "draft_only": action["draft_only"],
        "decision_recorded": action["decision_recorded"],
        "package_mutation_allowed": action["package_mutation_allowed"],
        "runtime_mutation_allowed": action["runtime_mutation_allowed"],
        "source_mutation_allowed": action["source_mutation_allowed"],
        "source_ref_key": action["source_ref_key"],
        "title": action["title"],
        "summary": action["summary"],
    }


def _review_decision_log_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["log_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_review_decision_log",
        "status": "fixture_only_decisions",
        "counts": payload["counts"],
        "apply_summary": payload["apply_summary"],
        "boundary": _summary_boundary(payload["boundary"]),
        "decisions": [
            {
                "decision_id": decision["decision_id"],
                **_projection_record_metadata(
                    decision,
                    source_path=source_path,
                    evidence_type="pretrip_review_decision",
                    source_kind="review_decision",
                    identity_keys=("decision_id", "candidate_ref", "draft_action_id"),
                    review_state=decision.get("decision", "decided"),
                    confidence="medium",
                    stale_risk="medium",
                    candidate_only=decision.get("package_mutation_allowed") is not True,
                    runtime_safety_truth=decision.get("runtime_mutation_allowed") is True,
                    extractor_version="pretrip_review_decision_log.projection.v1",
                    prompt_version="not_applicable_human_review_decision.v1",
                    summary=(
                        "Human review decision record over pretrip candidates; "
                        "does not create runtime safety truth."
                    ),
                ),
                "draft_action_id": decision["draft_action_id"],
                "decision": decision["decision"],
                "candidate_ref": decision["candidate_ref"],
                "target_ids": decision["target_ids"],
                "reviewer_alias": decision["reviewer_alias"],
                "decided_at": decision["decided_at"],
                "summary": decision["summary"],
                "correction_summary": (
                    decision.get("correction", {}).get("summary")
                    if decision.get("correction")
                    else None
                ),
                "correction_field_update_count": len(
                    decision.get("correction", {}).get("field_updates", {})
                    if decision.get("correction")
                    else {}
                ),
                "correction_replacement_ref_count": len(
                    decision.get("correction", {}).get("replacement_ref_ids", [])
                    if decision.get("correction")
                    else []
                ),
            }
            for decision in payload.get("decisions", [])
        ],
    }


def _review_decision_apply_plan_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["plan_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_review_decision_apply_plan",
        "status": "would_apply_only",
        "plan_id": payload["plan_id"],
        "project_id": payload["project_id"],
        "package_id": payload["package_id"],
        "package_status": payload["package_status"],
        "package_ref": payload["package_ref"],
        "review_decision_log_ref": payload["review_decision_log_ref"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "decisions": [
            {
                "decision_id": decision["decision_id"],
                **_projection_record_metadata(
                    decision,
                    source_path=source_path,
                    evidence_type="pretrip_review_decision_apply_plan_decision",
                    source_kind="review_decision_apply_plan",
                    identity_keys=("decision_id", "candidate_ref", "draft_action_id"),
                    review_state=decision.get("decision", "planned"),
                    confidence="medium",
                    stale_risk="medium",
                    extractor_version="pretrip_review_decision_apply_plan.projection.v1",
                    prompt_version="not_applicable_deterministic_review_apply_plan.v1",
                    summary=(
                        "Review decision apply-plan row; would-apply planning "
                        "projection only, not runtime safety truth."
                    ),
                ),
                "draft_action_id": decision["draft_action_id"],
                "decision": decision["decision"],
                "candidate_ref": decision["candidate_ref"],
                "target_ids": decision["target_ids"],
                "summary": decision["summary"],
                "correction_summary": decision.get("correction_summary"),
                "package_candidate_apply_count": decision[
                    "package_candidate_apply_count"
                ],
                "would_apply_to_package": decision["would_apply_to_package"],
                "source_ref_count": len(decision.get("source_refs", [])),
            }
            for decision in payload.get("decisions", [])
        ],
    }


def _external_import_queue_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["queue_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_external_import_queue",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "requests": [
            {
                "request_id": request["request_id"],
                **_projection_record_metadata(
                    request,
                    source_path=source_path,
                    evidence_type="pretrip_external_import_request",
                    source_kind="external_import_request",
                    identity_keys=("request_id", "source_id", "source_url"),
                    review_state=request.get("review_requirement", "needs_review"),
                    confidence="medium",
                    stale_risk="medium",
                    extractor_version="pretrip_external_import_queue.projection.v1",
                    prompt_version="not_applicable_deterministic_external_import_projection.v1",
                    summary=(
                        "External import request for future source ingest; "
                        "candidate-only planning request, not runtime safety truth."
                    ),
                ),
                "source_id": request["source_id"],
                "source_kind": request["source_kind"],
                "source_url": request["source_url"],
                "title": request["title"],
                "requested_artifact_kind": request["requested_artifact_kind"],
                "intended_treatment": request["intended_treatment"],
                "review_requirement": request["review_requirement"],
                "status": request["status"],
            }
            for request in payload.get("requests", [])
        ],
    }


def _route_note_summary(
    payload: dict[str, Any],
    source_path: str,
    *,
    display_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    candidates = [
        {
            "candidate_id": candidate["candidate_id"],
            "source_id": candidate["candidate_id"],
            "source_path": source_path,
            "evidence_type": "pretrip_route_note_candidate",
            "lat": candidate["lat"],
            "lon": candidate["lon"],
            "ele_m": candidate.get("ele_m"),
            "time": candidate.get("time"),
            "normalized_note": candidate["normalized_note"],
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
            "source_fields_present": candidate["source_fields_present"],
            "source_refs": candidate.get("source_refs", []),
            "source_attribution": candidate.get("source_attribution", []),
            "extractor_version": candidate.get("extractor_version"),
            "pydantic_ai_prompt_version": candidate.get(
                "pydantic_ai_prompt_version",
            ),
            "model_output_sha256": candidate.get("model_output_sha256"),
            "model_output_summary": candidate.get("model_output_summary"),
        }
        for candidate in payload.get("candidates", [])
    ]
    visible_candidates = [
        candidate
        for candidate in candidates
        if _point_within_projection_bounds(candidate, display_bounds)
    ]
    projection_filter = _projection_filter_summary(
        source_count=len(candidates),
        visible_count=len(visible_candidates),
        display_bounds=display_bounds,
    )
    counts = {
        **payload["counts"],
        "visible_candidate_count": len(visible_candidates),
        "filtered_out_of_route_bounds_count": projection_filter[
            "filtered_out_of_route_bounds_count"
        ],
    }
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_candidates",
        "status": payload["status"],
        "counts": counts,
        "boundary": _summary_boundary(payload["boundary"]),
        "projection_filter": projection_filter,
        "candidates": visible_candidates,
    }


def _layer_preparation_summary(
    payload: dict[str, Any] | None,
    source_path: str,
    *,
    project_id: str,
    project_root: Path,
) -> dict[str, Any]:
    if payload is None:
        return build_layer_preparation_not_prepared_view(
            project_id,
            project_root=project_root,
        )
    return {
        "source_id": payload["job_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_layer_preparation_manifest",
        "artifact_kind": "pretrip_layer_preparation_summary",
        "schema_version": payload["schema_version"],
        "project_id": payload["project_id"],
        "status": payload["validation"]["status"],
        "profile": payload["profile"],
        "network_mode": payload["network_mode"],
        "prepared_at": payload["finished_at"],
        "bbox_wgs84": payload["bbox_wgs84"],
        "route_corridor": payload["route_corridor"],
        "counts": payload["counts"],
        "network_policy": payload["network_policy"],
        "boundary": payload["boundary"],
        "layers": [
            {
                "layer_id": layer["layer_id"],
                "source_id": f"{payload['job_id']}.{layer['layer_id']}",
                "source_path": source_path,
                "evidence_type": "pretrip_layer_preparation_layer",
                **_projection_record_metadata(
                    {
                        **layer,
                        "candidate_id": layer["layer_id"],
                        "source_refs": [
                            source_path,
                            layer["layer_id"],
                            *[
                                ref.get("ref") if isinstance(ref, dict) else ref
                                for ref in layer.get("source_refs", [])
                            ],
                        ],
                    },
                    source_path=source_path,
                    evidence_type="pretrip_layer_preparation_layer",
                    source_kind=f"pretrip_layer_preparation.{layer['layer_id']}",
                    identity_keys=("candidate_id", "source_refs"),
                    review_state=(
                        "ready"
                        if layer.get("status") in READY_LAYER_STATUSES
                        else "needs_review"
                    ),
                    confidence=(
                        "medium"
                        if layer.get("status") in READY_LAYER_STATUSES
                        else "low"
                    ),
                    stale_risk=layer.get("stale_risk", "medium"),
                    extractor_version="pretrip_layer_preparation.projection.v1",
                    prompt_version="not_applicable_deterministic_layer_preparation_projection.v1",
                    summary=(
                        "Pretrip layer preparation row projected as planning "
                        "evidence metadata; not runtime safety truth."
                    ),
                ),
                "status": layer["status"],
                "adapter": layer["adapter"],
                "counts": layer["counts"],
                "source_ref_count": len(layer.get("source_refs", [])),
                "warning_count": len(layer.get("warnings", [])),
                "blocker_count": len(layer.get("blockers", [])),
                "stale_risk": layer.get("stale_risk"),
                "lifecycle": layer["lifecycle"],
            }
            for layer in payload.get("layers", [])
        ],
        "validation": payload["validation"],
        "outputs": payload["outputs"],
        "notes": payload.get("notes", []),
    }


def _risk_score_summary(
    project_id: str,
    score_payload: dict[str, Any] | None,
    score_metadata: dict[str, Any] | None,
    route_payload: dict[str, Any] | None,
    route_metadata: dict[str, Any] | None,
    *,
    source_path: str,
    metadata_source_path: str,
    route_source_path: str,
    route_metadata_source_path: str,
) -> dict[str, Any]:
    counts = {
        "point_count": 0,
        "route_sample_count": 0,
        "source_feature_count": 0,
        "risk_level_counts": {},
    }
    points: list[dict[str, Any]] = []
    features = score_payload.get("features", []) if score_payload else []
    route_sample_properties = {
        str(feature.get("properties", {}).get("sample_id")): feature.get(
            "properties",
            {},
        )
        for feature in (route_payload or {}).get("features", [])
        if feature.get("properties", {}).get("sample_id")
    }
    risk_values: list[float] = []
    level_counts: Counter[int] = Counter()
    for index, feature in enumerate(features):
        geometry = feature.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        if geometry.get("type") != "Point" or len(coordinates) < 2:
            continue
        properties = feature.get("properties", {})
        score = properties.get("rs")
        if score is None:
            continue
        risk_level = properties.get("risk_level")
        if isinstance(risk_level, int):
            level_counts[risk_level] += 1
        risk_value = float(score)
        risk_values.append(risk_value)
        sample_id = str(properties.get("sample_id") or f"risk_score.{index:04d}")
        route_properties = route_sample_properties.get(sample_id, {})
        provenance = _risk_candidate_provenance(
            metadata=score_metadata or {},
            source_path=source_path,
            metadata_source_path=metadata_source_path,
            route_source_path=route_source_path,
            route_metadata_source_path=route_metadata_source_path,
            default_summary=(
                "Scout Risk Engine route-aligned point score candidate; "
                "pretrip evidence only and not runtime safety truth."
            ),
        )
        points.append(
            {
                "candidate_id": f"risk_score_point.{_safe_view_key(sample_id)}",
                "source_id": f"risk_score_point.{_safe_view_key(sample_id)}",
                "source_path": source_path,
                "evidence_type": "pretrip_risk_score_point",
                "status": "candidate_only",
                "source_profile": "scout_risk_engine",
                "source_attribution": [
                    {
                        "source_kind": "scout_risk_engine_route_sample",
                        "source_profile": "scout_risk_engine",
                        "source_candidate_id": sample_id,
                        "source_artifact_id": "scout_risk_score_point_map",
                        "source_label": f"risk {risk_value:.1f}",
                        "evidence_type": "pretrip_risk_score_point",
                        "confidence": "medium",
                        "stale_risk": "medium",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
                "lat": float(coordinates[1]),
                "lon": float(coordinates[0]),
                "x": properties.get("x"),
                "y": properties.get("y"),
                "pretrip_risk": risk_value,
                "risk_level": risk_level,
                "score_field": properties.get("score_field", "pretrip_risk"),
                "route_id": properties.get("route_id"),
                "sample_id": sample_id,
                "distance_m": properties.get("distance_m"),
                "elevation_m": route_properties.get("elevation_m"),
                "teii_20m": properties.get("teii_20m", route_properties.get("teii_20m")),
                "tri": properties.get("tri", route_properties.get("tri")),
                "sri": properties.get("sri", route_properties.get("sri")),
                "lec": properties.get("lec", route_properties.get("lec")),
                "scp": properties.get("scp", route_properties.get("scp")),
                "explanation": route_properties.get("explanation", []),
                "source_sample_count": properties.get("source_sample_count"),
                "source_sample_ids": properties.get("source_sample_ids", []),
                "candidate_only": True,
                "runtime_safety_truth": False,
                **provenance,
            }
        )

    counts.update(
        {
            "point_count": len(points),
            "route_sample_count": (
                route_metadata or {}
            ).get(
                "route_risk_sample_count",
                len(route_payload.get("features", [])) if route_payload else 0,
            ),
            "source_feature_count": (score_metadata or {}).get(
                "source_feature_count",
                len(features),
            ),
            "risk_level_counts": {
                str(level): count for level, count in sorted(level_counts.items())
            },
        }
    )
    if risk_values:
        counts["max_pretrip_risk"] = round(max(risk_values), 2)
        counts["mean_pretrip_risk"] = round(sum(risk_values) / len(risk_values), 2)

    metadata = score_metadata or {}
    return {
        "source_id": "scout_risk_score_points." + project_id,
        "source_path": source_path or metadata_source_path or "project.json#risk-score",
        "metadata_source_path": metadata_source_path,
        "route_source_path": route_source_path,
        "route_metadata_source_path": route_metadata_source_path,
        "evidence_type": "pretrip_risk_score_points",
        "artifact_kind": metadata.get("artifact_kind", "scout_risk_score_point_map"),
        "status": "candidate_only" if points else "not_available",
        "score_field": metadata.get("score_field", "pretrip_risk"),
        "score_surface_type": metadata.get(
            "score_surface_type",
            "route_aligned_point_grid",
        ),
        "snap_grid_m": metadata.get("snap_grid_m"),
        "counts": counts,
        "points": points,
        "boundary": _summary_boundary(
            metadata.get(
                "boundary",
                {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "route_aligned_samples_only": True,
                },
            )
        ),
    }


def _terrain_visualization_summary(
    project_id: str,
    payload: dict[str, Any] | None,
    source_path: str,
) -> dict[str, Any]:
    payload = payload or {}
    visualization_spec = payload.get("visualization_spec", {})
    source_ref_values = [
        str(ref.get("ref"))
        for ref in payload.get("source_refs", [])
        if isinstance(ref, dict) and ref.get("ref")
    ]
    if source_path:
        source_ref_values.insert(0, source_path)
    source_ref_values = list(dict.fromkeys(source_ref_values))
    raster_overlays: list[dict[str, Any]] = []
    for overlay in payload.get("raster_overlays", []):
        if not isinstance(overlay, dict):
            continue
        overlay_id = str(overlay.get("overlay_id") or overlay.get("mode") or "")
        if not overlay_id:
            continue
        overlay_source_path = str(overlay.get("source_path") or "")
        model_hash = _stable_projection_hash(
            {
                "source_path": source_path,
                "overlay_id": overlay_id,
                "overlay_source_path": overlay_source_path,
                "sha256": overlay.get("sha256"),
                "cell_resolution_m": overlay.get("cell_resolution_m"),
                "corridor_half_width_m": overlay.get("corridor_half_width_m"),
            }
        )
        raster_overlays.append(
            {
                "candidate_id": f"terrain_visualization.overlay.{_safe_view_key(overlay_id)}",
                "source_id": f"terrain_visualization.overlay.{_safe_view_key(overlay_id)}",
                "source_path": overlay_source_path,
                "parent_source_path": source_path,
                "evidence_type": "pretrip_terrain_visualization_bitmap_overlay",
                "status": "candidate_only",
                "mode": overlay.get("mode") or overlay_id,
                "runtime_href": overlay.get("runtime_href"),
                "media_type": overlay.get("media_type", "image/png"),
                "sha256": overlay.get("sha256"),
                "bbox_wgs84": overlay.get("bbox_wgs84"),
                "bbox_twd97": overlay.get("bbox_twd97"),
                "pixel_width": overlay.get("pixel_width"),
                "pixel_height": overlay.get("pixel_height"),
                "cell_resolution_m": overlay.get("cell_resolution_m"),
                "corridor_half_width_m": overlay.get("corridor_half_width_m"),
                "corridor_total_width_m": overlay.get("corridor_total_width_m"),
                "default_visible": bool(overlay.get("default_visible")),
                "opacity": overlay.get("opacity"),
                "image_rendering": overlay.get("image_rendering", "pixelated"),
                "terrain_visualization_layer": True,
                "risk_heat_layer": False,
                "source_refs": source_ref_values,
                "source_attribution": [
                    {
                        "source_kind": "terrain_visualization_bitmap_overlay",
                        "source_ref": overlay_source_path,
                        "source_candidate_id": overlay_id,
                        "source_label": f"{overlay_id} bitmap overlay",
                        "evidence_type": "pretrip_terrain_visualization_bitmap_overlay",
                        "confidence": "medium",
                        "stale_risk": "medium",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
                "confidence": "medium",
                "stale_risk": "medium",
                "review_state": "needs_review",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "extractor_version": "pretrip_terrain_visualization.bitmap_overlay.v1",
                "pydantic_ai_prompt_version": (
                    "not_applicable_deterministic_terrain_visualization.v1"
                ),
                "model_output_sha256": model_hash,
                "model_output_summary": (
                    "DEM/DTM-derived terrain bitmap overlay; pretrip candidate "
                    "evidence only and not runtime safety truth."
                ),
            }
        )
    samples: list[dict[str, Any]] = []
    contours: list[dict[str, Any]] = []
    for index, feature in enumerate(payload.get("features", [])):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coordinate = _geojson_point_coordinate(geometry)
        properties = feature.get("properties") or {}
        sample_id = str(
            properties.get("terrain_visualization_id")
            or properties.get("terrain_sample_id")
            or properties.get("sample_id")
            or f"terrain_visualization.{index + 1:06d}"
        )
        model_hash = _stable_projection_hash(
            {
                "source_path": source_path,
                "sample_id": sample_id,
                "slope_degrees": properties.get("slope_degrees"),
                "elevation_m": properties.get("elevation_m"),
                "contour_index_m": properties.get("contour_index_m"),
            }
        )
        source_attribution = [
            {
                "source_kind": "terrain_visualization_artifact",
                "source_ref": source_path,
                "source_candidate_id": sample_id,
                "source_label": properties.get("slope_class_label") or "terrain sample",
                "evidence_type": "pretrip_terrain_visualization_sample",
                "confidence": "medium",
                "stale_risk": "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ]
        sample = {
            "candidate_id": f"terrain_visualization.{_safe_view_key(sample_id)}",
            "source_id": f"terrain_visualization.{_safe_view_key(sample_id)}",
            "source_path": source_path,
            "evidence_type": "pretrip_terrain_visualization_sample",
            "status": "candidate_only",
            "lat": coordinate["lat"],
            "lon": coordinate["lon"],
            "distance_m": properties.get("distance_m"),
            "elevation_m": properties.get("elevation_m"),
            "visualization_modes": properties.get(
                "visualization_modes",
                visualization_spec.get("modes", []),
            ),
            "hillshade_value": properties.get("hillshade_value"),
            "elevation_tint_color": properties.get("elevation_tint_color"),
            "slope_degrees": properties.get("slope_degrees"),
            "slope_class": properties.get("slope_class"),
            "slope_class_label": properties.get("slope_class_label"),
            "slope_color": properties.get("slope_color"),
            "contour_interval_m": properties.get("contour_interval_m"),
            "contour_index_m": properties.get("contour_index_m"),
            "contour_marker": bool(properties.get("contour_marker")),
            "terrain_visualization_layer": True,
            "risk_heat_layer": False,
            "source_refs": source_ref_values,
            "source_attribution": source_attribution,
            "confidence": "medium",
            "stale_risk": "medium",
            "review_state": "needs_review",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "extractor_version": "pretrip_terrain_visualization.route_aligned.v1",
            "pydantic_ai_prompt_version": (
                "not_applicable_deterministic_terrain_visualization.v1"
            ),
            "model_output_sha256": model_hash,
            "model_output_summary": (
                "DEM/DTM-derived route-aligned terrain visualization evidence; "
                "pretrip candidate evidence only and not runtime safety truth."
            ),
        }
        samples.append(sample)
        if sample["contour_marker"]:
            contours.append(
                {
                    **sample,
                    "candidate_id": sample["candidate_id"] + ".contour",
                    "source_id": sample["source_id"] + ".contour",
                    "evidence_type": "pretrip_terrain_contour_marker",
                }
            )

    counts = dict(payload.get("counts") or {})
    dtm_grid = payload.get("dtm_grid") if isinstance(payload.get("dtm_grid"), dict) else {}
    counts.setdefault("feature_count", len(samples))
    counts.setdefault("bitmap_overlay_count", len(raster_overlays))
    counts.setdefault("contour_marker_count", len(contours))
    if "source_dtm_tile_count" not in counts and dtm_grid.get("source_tile_count") is not None:
        counts["source_dtm_tile_count"] = dtm_grid.get("source_tile_count")
    if (
        "source_dtm_grid_cell_count" not in counts
        and dtm_grid.get("source_grid_cell_count") is not None
    ):
        counts["source_dtm_grid_cell_count"] = dtm_grid.get("source_grid_cell_count")
    return {
        "source_id": f"terrain_visualization.{project_id}",
        "source_path": source_path,
        "evidence_type": "pretrip_terrain_visualization",
        "artifact_kind": payload.get(
            "artifact_kind",
            "pretrip_terrain_visualization",
        ),
        "status": "candidate_only" if samples or raster_overlays else "not_available",
        "visualization_spec": visualization_spec,
        "counts": counts,
        "dtm_grid": dtm_grid,
        "raster_overlays": raster_overlays,
        "samples": samples,
        "contours": contours,
        "boundary": _summary_boundary(
            payload.get(
                "boundary",
                {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "terrain_visualization_layer": True,
                    "risk_heat_layer": False,
                },
            )
        ),
    }


def _risk_ribbon_summary(
    project_id: str,
    payload: dict[str, Any] | None,
    metadata_payload: dict[str, Any] | None,
    *,
    source_path: str,
    metadata_source_path: str,
) -> dict[str, Any]:
    payload_metadata = payload.get("metadata", {}) if payload else {}
    metadata = {
        **(payload_metadata if isinstance(payload_metadata, dict) else {}),
        **(metadata_payload or {}),
    }
    score_field = str(metadata.get("score_field") or "pretrip_risk")
    features = payload.get("features", []) if payload else []
    segments: list[dict[str, Any]] = []
    risk_values: list[float] = []
    bucket_counts: Counter[str] = Counter()
    for index, feature in enumerate(features):
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "LineString":
            continue
        try:
            coordinates = _geojson_line_coordinates(geometry)
        except (TypeError, ValueError):
            continue
        if len(coordinates) < 2:
            continue
        properties = feature.get("properties", {})
        score = _coerce_float(properties.get("rs", properties.get(score_field)))
        if score is None:
            continue
        risk_values.append(score)
        segment_id = str(properties.get("segment_id") or f"risk_ribbon.{index:04d}")
        risk_bucket = str(properties.get("risk_bucket") or _risk_bucket(score))
        bucket_counts[risk_bucket] += 1
        start_distance_m = _coerce_float(properties.get("start_distance_m"))
        end_distance_m = _coerce_float(properties.get("end_distance_m"))
        provenance = _risk_candidate_provenance(
            metadata=metadata,
            source_path=source_path,
            metadata_source_path=metadata_source_path,
            default_summary=(
                "Scout Risk Engine route-aligned risk ribbon segment candidate; "
                "pretrip evidence only and not runtime safety truth."
            ),
        )
        segments.append(
            {
                "candidate_id": f"risk_ribbon.{_safe_view_key(segment_id)}",
                "source_id": f"risk_ribbon.{_safe_view_key(segment_id)}",
                "segment_id": segment_id,
                "source_path": source_path,
                "metadata_source_path": metadata_source_path,
                "evidence_type": "pretrip_risk_ribbon_segment",
                "status": "candidate_only",
                "source_profile": "scout_risk_engine",
                "source_attribution": [
                    {
                        "source_kind": "scout_risk_engine_route_ribbon",
                        "source_profile": "scout_risk_engine",
                        "source_candidate_id": segment_id,
                        "source_artifact_id": metadata.get(
                            "artifact_kind",
                            "scout_risk_route_ribbon",
                        ),
                        "source_label": f"risk ribbon {score:.1f}",
                        "evidence_type": "pretrip_risk_ribbon_segment",
                        "confidence": "medium",
                        "stale_risk": "medium",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
                "label": f"{risk_bucket} risk {score:.1f}",
                "coordinates": coordinates,
                "lat": coordinates[0]["lat"],
                "lon": coordinates[0]["lon"],
                "pretrip_risk": score,
                "rs": score,
                "score_field": properties.get("score_field", score_field),
                "risk_level": properties.get("risk_level"),
                "risk_bucket": risk_bucket,
                "style_class": properties.get(
                    "style_class",
                    f"risk-ribbon-{risk_bucket}",
                ),
                "stroke": properties.get("stroke"),
                "route_id": properties.get("route_id"),
                "from_sample_id": properties.get("from_sample_id"),
                "to_sample_id": properties.get("to_sample_id"),
                "start_distance_m": start_distance_m,
                "end_distance_m": end_distance_m,
                "distance_m": start_distance_m,
                "candidate_only": bool(properties.get("candidate_only", True)),
                "runtime_safety_truth": bool(
                    properties.get("runtime_safety_truth", False)
                ),
                "interpolated_surface": bool(
                    properties.get("interpolated_surface", False)
                ),
                "route_aligned_samples_only": bool(
                    properties.get("route_aligned_samples_only", True)
                ),
                **provenance,
            }
        )

    counts: dict[str, Any] = {
        "segment_count": len(segments),
        "source_segment_count": _coerce_int(
            metadata.get("segment_count"),
            len(features) or 0,
        ),
        "source_sample_count": _coerce_int(metadata.get("source_sample_count"), 0),
        "skipped_pair_count": _coerce_int(metadata.get("skipped_pair_count"), 0),
        "risk_bucket_counts": {
            bucket: count for bucket, count in sorted(bucket_counts.items())
        },
    }
    if risk_values:
        counts["max_pretrip_risk"] = round(max(risk_values), 2)
        counts["mean_pretrip_risk"] = round(sum(risk_values) / len(risk_values), 2)

    return {
        "source_id": "scout_risk_ribbon." + project_id,
        "source_path": source_path or metadata_source_path or "project.json#risk-ribbon",
        "metadata_source_path": metadata_source_path,
        "evidence_type": "pretrip_risk_ribbon",
        "artifact_kind": metadata.get("artifact_kind", "scout_risk_route_ribbon"),
        "status": "candidate_only" if segments else "not_available",
        "score_field": score_field,
        "score_surface_type": metadata.get(
            "score_surface_type",
            "route_aligned_risk_ribbon",
        ),
        "counts": counts,
        "segments": segments,
        "style": metadata.get("style", {}),
        "boundary": _summary_boundary(
            metadata.get(
                "boundary",
                {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "interpolated_surface": False,
                    "route_aligned_samples_only": True,
                },
            )
        ),
    }


def _risk_candidate_provenance(
    *,
    metadata: dict[str, Any],
    source_path: str | None = "",
    metadata_source_path: str | None = "",
    route_source_path: str | None = "",
    route_metadata_source_path: str | None = "",
    default_summary: str,
) -> dict[str, Any]:
    source_refs = [
        ref
        for ref in (
            source_path,
            metadata_source_path,
            route_source_path,
            route_metadata_source_path,
            metadata.get("source_route_risk_ref"),
            metadata.get("source_risk_attribution_diagnostic_ref"),
            metadata.get("warning_cp_proposals_ref"),
        )
        if ref
    ]
    model_hash = metadata.get("source_route_risk_sha256") or metadata.get(
        "model_output_sha256"
    )
    if not model_hash:
        model_hash = _stable_projection_hash(
            {
                "artifact_kind": metadata.get("artifact_kind"),
                "source_refs": source_refs,
                "score_field": metadata.get("score_field"),
                "score_surface_type": metadata.get("score_surface_type"),
            }
        )
    return {
        "source_refs": list(dict.fromkeys(str(ref) for ref in source_refs)),
        "confidence": metadata.get("confidence", "medium"),
        "stale_risk": metadata.get("stale_risk", "medium"),
        "review_state": metadata.get("review_state", "needs_review"),
        "extractor_version": metadata.get(
            "extractor_version",
            "scout_risk_engine.heuristic_projection.v1",
        ),
        "pydantic_ai_prompt_version": metadata.get(
            "pydantic_ai_prompt_version",
            "not_applicable_deterministic_risk_projection.v1",
        ),
        "model_output_sha256": str(model_hash),
        "model_output_summary": metadata.get("model_output_summary", default_summary),
    }


def _stable_projection_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _risk_bucket(score: float) -> str:
    if score >= 80:
        return "extreme"
    if score >= 60:
        return "high"
    if score >= 40:
        return "moderate"
    return "low"


def _overpass_evidence_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    candidates = payload.get("candidates", [])
    return {
        "source_id": payload["source_artifact"]["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_overpass_vector_evidence",
        "status": "candidate_only",
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "request": payload["request"],
        "source_artifact": payload["source_artifact"],
        "normalized_geojson_ref": payload["normalized_geojson_ref"],
        "raw_response_sha256": payload["request"]["raw_response_sha256"],
        "conversion_rule_version": payload["request"]["conversion_rule_version"],
        "corridor_candidates": [
            _overpass_candidate(candidate, source_path, "pretrip_overpass_corridor_candidate")
            for candidate in candidates
            if candidate["feature_type"] == "approved_corridor"
        ],
        "hazard_candidates": [
            _overpass_candidate(candidate, source_path, "pretrip_overpass_hazard_candidate")
            for candidate in candidates
            if candidate["feature_type"] == "hazard_zone"
        ],
        "poi_candidates": [
            _overpass_candidate(candidate, source_path, "pretrip_overpass_poi_candidate")
            for candidate in candidates
            if candidate["feature_type"] == "poi"
        ],
        "skipped_objects": payload.get("skipped_objects", []),
    }


def _overpass_candidate(
    candidate: dict[str, Any],
    source_path: str,
    evidence_type: str,
) -> dict[str, Any]:
    feature = candidate["geojson_feature"]
    properties = feature["properties"]
    return {
        "candidate_id": candidate["candidate_id"],
        "source_id": candidate["candidate_id"],
        "source_path": source_path,
        "evidence_type": evidence_type,
        **_overpass_candidate_provenance(
            candidate,
            source_path=source_path,
            evidence_type=evidence_type,
        ),
        "label": candidate["label"],
        "candidate_type": candidate["candidate_type"],
        "feature_type": candidate["feature_type"],
        "review_state": "needs_review",
        "confidence": candidate["confidence"],
        "stale_risk": candidate["stale_risk"],
        "osm_type": candidate["osm_type"],
        "osm_id": candidate["osm_id"],
        "tags": candidate["tags"],
        "conversion_rule_version": candidate["conversion_rule_version"],
        "linked_route_ref": candidate.get("linked_route_ref"),
        "linked_segment_ref": candidate.get("linked_segment_ref"),
        "linked_checkpoint_ref": candidate.get("linked_checkpoint_ref"),
        "geometry": candidate["geometry"],
        "map_target_ids": [candidate["candidate_id"]],
        "map_summary": {
            "endpoint": properties.get("endpoint"),
            "http_status": properties.get("http_status"),
            "raw_response_sha256": properties.get("raw_response_sha256"),
            "normalized_artifact_path": properties.get("normalized_artifact_path"),
            "runtime_truth": properties.get("runtime_truth"),
        },
        **_overpass_map_payload(candidate, properties),
    }


def _overpass_map_payload(candidate: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
    geometry = candidate["geometry"]
    if candidate["feature_type"] == "approved_corridor":
        return {
            "corridor": {
                "corridor_id": candidate["candidate_id"],
                "name": candidate["label"],
                "coordinates": _geojson_line_coordinates(geometry),
                "corridor_half_width_m": 12.0,
                "route_level": properties.get("route_level"),
            }
        }
    if candidate["feature_type"] == "hazard_zone":
        return {
            "hazard": {
                "hazard_id": candidate["candidate_id"],
                "hazard_type": properties.get("hazard_type", "terrain_risk"),
                "name": candidate["label"],
                "polygon": _geojson_line_coordinates(
                    {"coordinates": geometry.get("coordinates", [[]])[0]}
                ),
            }
        }
    return {
        "poi": {
            "poi_id": candidate["candidate_id"],
            "poi_type": properties.get("poi_type", "unknown"),
            "name": candidate["label"],
            "coordinate": _geojson_point_coordinate(geometry),
        }
    }


def _overpass_candidate_provenance(
    candidate: dict[str, Any],
    *,
    source_path: str,
    evidence_type: str,
) -> dict[str, Any]:
    feature = candidate.get("geojson_feature", {})
    properties = feature.get("properties", {})
    source_refs = _unique_limited(
        [
            source_path,
            candidate.get("candidate_id"),
            candidate.get("linked_route_ref"),
            candidate.get("linked_segment_ref"),
            candidate.get("linked_checkpoint_ref"),
            properties.get("normalized_artifact_path"),
            properties.get("raw_response_sha256"),
            f"{candidate.get('osm_type')}:{candidate.get('osm_id')}",
        ],
        limit=32,
    )
    model_hash = candidate.get("model_output_sha256") or _stable_projection_hash(
        {
            "candidate_id": candidate.get("candidate_id"),
            "evidence_type": evidence_type,
            "osm_type": candidate.get("osm_type"),
            "osm_id": candidate.get("osm_id"),
            "tags": candidate.get("tags", {}),
            "source_refs": source_refs,
        }
    )
    return {
        "source_refs": source_refs,
        "source_attribution": [
            {
                "source_kind": "overpass_candidate",
                "source_profile": "overpass_osm_tags",
                "source_ref": source_path,
                "source_candidate_id": candidate.get("candidate_id"),
                "source_artifact_id": properties.get("normalized_artifact_path"),
                "source_label": candidate.get("label"),
                "osm_type": candidate.get("osm_type"),
                "osm_id": candidate.get("osm_id"),
                "confidence": candidate.get("confidence", "medium"),
                "stale_risk": candidate.get("stale_risk", "medium"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "candidate_only": candidate.get("candidate_only", True),
        "runtime_safety_truth": candidate.get("runtime_safety_truth", False),
        "extractor_version": candidate.get(
            "extractor_version",
            candidate.get("conversion_rule_version", "overpass-vector-evidence.v1"),
        ),
        "pydantic_ai_prompt_version": candidate.get(
            "pydantic_ai_prompt_version",
            "not_applicable_deterministic_overpass_projection.v1",
        ),
        "model_output_sha256": str(model_hash),
        "model_output_summary": candidate.get("model_output_summary")
        or (
            f"{evidence_type} normalized from Overpass/OSM tags; "
            "pretrip candidate-only map evidence, not runtime safety truth."
        ),
    }


def _risk_heatmap_summary(
    project_id: str,
    payload: dict[str, Any] | None,
    metadata_payload: dict[str, Any] | None,
    *,
    source_path: str,
    metadata_source_path: str,
) -> dict[str, Any]:
    summary = _risk_ribbon_summary(
        project_id,
        payload,
        metadata_payload,
        source_path=source_path,
        metadata_source_path=metadata_source_path,
    )
    summary["source_id"] = "scout_calibrated_risk_heatmap." + project_id
    summary["evidence_type"] = "pretrip_calibrated_risk_heatmap"
    for segment in summary.get("segments", []):
        segment["evidence_type"] = "pretrip_calibrated_risk_heatmap_segment"
        segment["source_profile"] = "scout_risk_engine_route_specific_calibration"
        segment["label"] = (
            f"{segment.get('risk_bucket', 'heat')} heat "
            f"{segment.get('pretrip_risk', 0):.1f}"
        )
        segment["route_specific_calibration_candidate"] = True
        segment["relative_bucket"] = segment.get("risk_bucket")
        for attribution in segment.get("source_attribution", []):
            attribution["source_kind"] = "scout_risk_engine_calibrated_heatmap"
            attribution["source_profile"] = (
                "scout_risk_engine_route_specific_calibration"
            )
            attribution["evidence_type"] = (
                "pretrip_calibrated_risk_heatmap_segment"
            )
    summary["boundary"]["route_specific_calibration_candidate"] = True
    return summary


def _risk_delta_summary(
    project_id: str,
    baseline: dict[str, Any] | None,
    calibrated: dict[str, Any] | None,
) -> dict[str, Any]:
    baseline_segments = (baseline or {}).get("segments", [])
    calibrated_segments = (calibrated or {}).get("segments", [])
    calibrated_by_key = {
        _risk_segment_key(segment): segment
        for segment in calibrated_segments
        if _risk_segment_key(segment)
    }
    segments: list[dict[str, Any]] = []
    delta_values: list[float] = []
    bucket_counts: Counter[str] = Counter()
    for index, baseline_segment in enumerate(baseline_segments):
        key = _risk_segment_key(baseline_segment)
        calibrated_segment = calibrated_by_key.get(key)
        if calibrated_segment is None:
            continue
        baseline_score = _coerce_float(baseline_segment.get("pretrip_risk"))
        calibrated_score = _coerce_float(calibrated_segment.get("pretrip_risk"))
        if baseline_score is None or calibrated_score is None:
            continue
        delta = round(calibrated_score - baseline_score, 2)
        bucket = _risk_delta_bucket(
            baseline_score,
            calibrated_score,
            baseline_segment.get("risk_bucket"),
            calibrated_segment.get("risk_bucket"),
        )
        bucket_counts[bucket] += 1
        delta_values.append(delta)
        coordinates = calibrated_segment.get("coordinates") or baseline_segment.get(
            "coordinates",
            [],
        )
        segment_id = (
            f"risk_delta.{baseline_segment.get('from_sample_id', index)}."
            f"{baseline_segment.get('to_sample_id', index)}"
        )
        provenance = _risk_candidate_provenance(
            metadata={
                "artifact_kind": "scout_risk_delta_comparison",
                "source_route_risk_sha256": _stable_projection_hash(
                    {
                        "baseline": baseline_segment.get("model_output_sha256"),
                        "calibrated": calibrated_segment.get("model_output_sha256"),
                        "segment_id": segment_id,
                    }
                ),
            },
            source_path=baseline_segment.get("source_path"),
            metadata_source_path=baseline_segment.get("metadata_source_path"),
            route_source_path=calibrated_segment.get("source_path"),
            route_metadata_source_path=calibrated_segment.get("metadata_source_path"),
            default_summary=(
                "Scout Risk Engine comparison candidate between baseline ribbon "
                "and calibrated heatmap; pretrip evidence only."
            ),
        )
        segments.append(
            {
                "candidate_id": f"risk_delta.{_safe_view_key(segment_id)}",
                "source_id": f"risk_delta.{_safe_view_key(segment_id)}",
                "segment_id": segment_id,
                "source_path": baseline_segment.get("source_path"),
                "metadata_source_path": calibrated_segment.get("metadata_source_path"),
                "evidence_type": "pretrip_risk_delta_segment",
                "status": "candidate_only",
                "source_profile": "scout_risk_engine_delta_comparison",
                "source_attribution": [
                    {
                        "source_kind": "scout_risk_engine_delta_comparison",
                        "source_profile": "scout_risk_engine_delta_comparison",
                        "source_candidate_id": segment_id,
                        "source_artifact_id": "scout_risk_delta_comparison",
                        "source_label": f"delta {delta:+.1f}",
                        "evidence_type": "pretrip_risk_delta_segment",
                        "confidence": "medium",
                        "stale_risk": "medium",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
                "label": f"{bucket.replace('_', ' ')} {delta:+.1f}",
                "coordinates": coordinates,
                "lat": coordinates[0]["lat"] if coordinates else None,
                "lon": coordinates[0]["lon"] if coordinates else None,
                "baseline_pretrip_risk": round(baseline_score, 2),
                "calibrated_risk_candidate": round(calibrated_score, 2),
                "pretrip_risk": abs(delta),
                "rs": abs(delta),
                "delta_score": delta,
                "abs_delta_score": abs(delta),
                "risk_bucket": bucket,
                "delta_bucket": bucket,
                "style_class": f"risk-delta-{bucket}",
                "stroke": RISK_DELTA_COLORS[bucket],
                "from_sample_id": baseline_segment.get("from_sample_id"),
                "to_sample_id": baseline_segment.get("to_sample_id"),
                "start_distance_m": baseline_segment.get("start_distance_m"),
                "end_distance_m": baseline_segment.get("end_distance_m"),
                "distance_m": baseline_segment.get("start_distance_m"),
                "baseline_risk_bucket": baseline_segment.get("risk_bucket"),
                "calibrated_risk_bucket": calibrated_segment.get("risk_bucket"),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "comparison_only": True,
                **provenance,
            }
        )

    counts: dict[str, Any] = {
        "segment_count": len(segments),
        "baseline_segment_count": len(baseline_segments),
        "calibrated_segment_count": len(calibrated_segments),
        "risk_bucket_counts": {
            bucket: count for bucket, count in sorted(bucket_counts.items())
        },
    }
    if delta_values:
        counts["max_abs_delta"] = round(max(abs(value) for value in delta_values), 2)
        counts["mean_abs_delta"] = round(
            sum(abs(value) for value in delta_values) / len(delta_values),
            2,
        )
    return {
        "source_id": "scout_risk_delta." + project_id,
        "source_path": (
            f"{(baseline or {}).get('source_path', '')} + "
            f"{(calibrated or {}).get('source_path', '')}"
        ).strip(" +"),
        "metadata_source_path": (
            f"{(baseline or {}).get('metadata_source_path', '')} + "
            f"{(calibrated or {}).get('metadata_source_path', '')}"
        ).strip(" +"),
        "evidence_type": "pretrip_risk_delta",
        "artifact_kind": "scout_risk_delta_comparison",
        "status": "candidate_only" if segments else "not_available",
        "score_field": "abs_delta_score",
        "score_surface_type": "baseline_vs_calibrated_delta",
        "counts": counts,
        "segments": segments,
        "style": {
            bucket: {"stroke": color}
            for bucket, color in RISK_DELTA_COLORS.items()
        },
        "boundary": _summary_boundary(
            {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "interpolated_surface": False,
                "route_aligned_samples_only": True,
                "comparison_only": True,
                "baseline_source": "risk_ribbon",
                "calibrated_source": "calibrated_risk_heatmap",
            }
        ),
    }


def _risk_segment_key(segment: dict[str, Any]) -> tuple[str, str] | None:
    start = segment.get("from_sample_id")
    end = segment.get("to_sample_id")
    if start and end:
        return str(start), str(end)
    return None


def _risk_delta_bucket(
    baseline_score: float,
    calibrated_score: float,
    baseline_bucket: Any,
    calibrated_bucket: Any,
) -> str:
    delta = calibrated_score - baseline_score
    high_calibrated = str(calibrated_bucket) in {"high", "very_high", "extreme"}
    high_baseline = baseline_score >= 80 or str(baseline_bucket) in {
        "high",
        "very_high",
        "extreme",
    }
    if high_baseline and high_calibrated:
        return "aligned_high"
    if delta >= 15:
        return "calibrated_higher"
    if delta <= -15:
        return "baseline_higher"
    if abs(delta) >= 7.5:
        return "minor_shift"
    return "aligned"


def _geojson_line_coordinates(geometry: dict[str, Any]) -> list[dict[str, float]]:
    return [
        {"lon": float(lon), "lat": float(lat)}
        for lon, lat, *_ in geometry.get("coordinates", [])
    ]


def _geojson_point_coordinate(geometry: dict[str, Any]) -> dict[str, float]:
    lon, lat = geometry.get("coordinates", [0.0, 0.0])[:2]
    return {"lon": float(lon), "lat": float(lat)}


def _route_note_ln_proposal_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_ln_proposals",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "proposals": [
            {
                "proposal_id": proposal["proposal_id"],
                "source_route_note_candidate_id": proposal[
                    "source_route_note_candidate_id"
                ],
                "source_waypoint_index": proposal["source_waypoint_index"],
                "lat": proposal["lat"],
                "lon": proposal["lon"],
                "source_note_category": proposal["source_note_category"],
                "proposal_kind": proposal["proposal_kind"],
                "proposed_coverage_label": proposal["proposed_coverage_label"],
                "route_note_summary": proposal["route_note_summary"],
                "human_review_required": proposal["human_review_required"],
                "review_state": proposal.get("review_state", "needs_review"),
                "confidence": proposal.get("confidence", "unknown"),
                "stale_risk": proposal.get("stale_risk", "unknown"),
                "candidate_only": proposal["candidate_only"],
                "runtime_safety_truth": proposal.get("runtime_safety_truth", False),
                "source_refs": proposal.get("source_refs", []),
                "source_attribution": proposal.get("source_attribution", []),
                "extractor_version": proposal.get("extractor_version"),
                "pydantic_ai_prompt_version": proposal.get(
                    "pydantic_ai_prompt_version",
                ),
                "model_output_sha256": proposal.get("model_output_sha256"),
                "model_output_summary": proposal.get("model_output_summary"),
            }
            for proposal in payload.get("proposals", [])
        ],
    }


def _route_note_review_options_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_review_options",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "options": [
            {
                "option_id": option["option_id"],
                "source_proposal_id": option["source_proposal_id"],
                "source_route_note_candidate_id": option[
                    "source_route_note_candidate_id"
                ],
                "source_waypoint_index": option["source_waypoint_index"],
                "source_note_category": option["source_note_category"],
                "proposal_kind": option["proposal_kind"],
                "proposed_coverage_label": option["proposed_coverage_label"],
                "route_note_summary": option["route_note_summary"],
                "allowed_admin_dispositions": option[
                    "allowed_admin_dispositions"
                ],
                "selected_admin_disposition": option[
                    "selected_admin_disposition"
                ],
                "decision_recorded": option["decision_recorded"],
                "review_state": option.get("review_state", "draft"),
                "confidence": option.get("confidence", "unknown"),
                "stale_risk": option.get("stale_risk", "unknown"),
                "candidate_only": option.get("candidate_only", True),
                "runtime_safety_truth": option.get("runtime_safety_truth", False),
                "draft_only": option.get("draft_only", True),
                "source_refs": option.get("source_refs", []),
                "source_attribution": option.get("source_attribution", []),
                "extractor_version": option.get("extractor_version"),
                "pydantic_ai_prompt_version": option.get(
                    "pydantic_ai_prompt_version",
                ),
                "model_output_sha256": option.get("model_output_sha256"),
                "model_output_summary": option.get("model_output_summary"),
            }
            for option in payload.get("options", [])
        ],
    }


def _route_note_reviewed_assumptions_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_reviewed_assumptions",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "accepted_interpretations": payload.get("accepted_interpretations", []),
        "ln_expansion_candidates": payload.get("ln_expansion_candidates", []),
        "field_verification_requests": payload.get("field_verification_requests", []),
        "ignored_dispositions": payload.get("ignored_dispositions", []),
    }


def _departure_reviewed_candidates_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_departure_reviewed_candidates",
        "status": "package_addendum_candidate",
        "project_id": payload["project_id"],
        "source_apply_plan_ref": payload["source_apply_plan_ref"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "candidates": [
            {
                "candidate_ref": candidate["candidate_ref"],
                "decision": candidate["decision"],
                "promotion_scope": candidate["promotion_scope"],
                "runtime_checkin_candidate": candidate["runtime_checkin_candidate"],
                "candidate_only": candidate["candidate_only"],
                "runtime_safety_truth": candidate["runtime_safety_truth"],
                "human_review_required_before_runtime_use": candidate[
                    "human_review_required_before_runtime_use"
                ],
                "target_ids": candidate.get("target_ids", []),
                "source_refs": candidate.get("source_refs", []),
                "summary": candidate["summary"],
                "correction_summary": candidate.get("correction_summary"),
            }
            for candidate in payload.get("candidates", [])
        ],
        "rejected_audit_refs": payload.get("rejected_audit_refs", []),
    }


def _mcp_summary(
    *,
    project_id: str,
    mcp_candidates: dict[str, Any],
    named_point_evidence: dict[str, Any] | None,
    retrieval_plan: dict[str, Any] | None,
    ocr_labels: dict[str, Any] | None,
    cp_support_reconciliation: dict[str, Any] | None,
    review_log: dict[str, Any] | None,
    source_refs: dict[str, str],
) -> dict[str, Any]:
    candidates = list(mcp_candidates.get("mcp_candidates", []) or [])
    retrieval_counts = retrieval_plan or {}
    ocr_counts = ocr_labels or {}
    retrieval_source_path = source_refs.get(
        "mcp_retrieval_plan",
        "outputs/mcp/mcp_retrieval_plan.json",
    )
    ocr_source_path = source_refs.get(
        "mcp_ocr_labels",
        "outputs/mcp/mcp_ocr_labels.json",
    )
    cp_support_source_path = source_refs.get(
        "mcp_cp_support_reconciliation",
        "outputs/mcp/mcp_cp_support_reconciliation.json",
    )
    retrieval_queries = [
        {
            **query,
            **_mcp_projection_provenance(
                query,
                source_path=retrieval_source_path,
                evidence_type="pretrip_mcp_retrieval_query",
                source_kind="mcp_retrieval_query",
                identity_keys=("query_id", "source_family_target", "query_text"),
                confidence="medium",
                stale_risk="medium",
                review_state="needs_review",
                model_output_summary=(
                    "MCP Pydantic AI retrieval query planning output; "
                    "fixture-backed candidate-only evidence, not runtime safety truth."
                ),
            ),
        }
        for query in retrieval_counts.get("queries", [])[:12]
    ]
    retrieval_fetch_summaries = [
        {
            **summary,
            **_mcp_projection_provenance(
                summary,
                source_path=retrieval_source_path,
                evidence_type="pretrip_mcp_retrieval_fetch_summary",
                source_kind="mcp_retrieval_fetch_summary",
                identity_keys=(
                    "fetch_id",
                    "query_id",
                    "source_page_id",
                    "snippet_hash",
                    "url",
                ),
                confidence=summary.get("route_relevance", "medium"),
                stale_risk=summary.get("stale_risk", "medium"),
                review_state="needs_review" if summary.get("accepted") else "rejected",
                model_output_summary=(
                    "MCP retrieval fetch summary and snippet hash; "
                    "candidate-only route-planning evidence, not runtime safety truth."
                ),
            ),
        }
        for summary in retrieval_counts.get("fetch_summaries", [])[:12]
    ]
    ocr_label_items = [
        {
            **label,
            **_mcp_projection_provenance(
                label,
                source_path=ocr_source_path,
                evidence_type="pretrip_mcp_ocr_label",
                source_kind="mcp_ocr_label",
                identity_keys=(
                    "ocr_label_id",
                    "named_point_id",
                    "source_ref",
                    "source_image_hash",
                    "label_text",
                ),
                confidence=label.get("confidence", "medium"),
                stale_risk="medium",
                review_state="needs_review"
                if label.get("review_required", True)
                else "reference_only",
                model_output_summary=(
                    "MCP OCR label projection from local map tile metadata; "
                    "review-gated candidate evidence, not runtime safety truth."
                ),
            ),
        }
        for label in ocr_counts.get("labels", [])[:12]
    ]
    support_rows = [
        {
            **_mcp_nested_support_projection(
                row,
                source_path=cp_support_source_path,
                evidence_type="pretrip_mcp_cp_support_reconciliation_row",
                source_kind="mcp_cp_support_reconciliation",
                review_state="needs_human_review",
            ),
            **_mcp_projection_provenance(
                row,
                source_path=cp_support_source_path,
                evidence_type="pretrip_mcp_cp_support_reconciliation_row",
                source_kind="mcp_cp_support_reconciliation",
                identity_keys=(
                    "mcp_id",
                    "label",
                    "support_status",
                    "recommendation",
                    "linked_cp_candidates",
                    "suggested_cp_insertion",
                ),
                confidence="medium",
                stale_risk="medium",
                review_state="needs_human_review",
                model_output_summary=(
                    "MCP-to-Scout-CP support reconciliation row; "
                    "review-gated planning evidence, not runtime safety truth."
                ),
            ),
        }
        for row in list((cp_support_reconciliation or {}).get("rows", []) or [])
    ]
    support_by_mcp_id = {row.get("mcp_id"): row for row in support_rows}
    review_actions = list((review_log or {}).get("actions", []) or [])
    latest_review_by_mcp_id = _latest_mcp_review_by_mcp_id(review_actions)
    counts = {
        "mcp_candidate_count": mcp_candidates.get(
            "mcp_candidate_count",
            len(candidates),
        ),
        "dense_checkpoint_count": mcp_candidates.get("dense_checkpoint_count", 0),
        "suppressed_point_count": mcp_candidates.get("suppressed_point_count", 0),
        "retrieval_query_count": retrieval_counts.get("query_count", 0),
        "accepted_evidence_page_count": (
            (named_point_evidence or {})
            .get("search_profile", {})
            .get("accepted_evidence_page_count", 0)
        ),
        "ocr_label_count": ocr_counts.get("label_count", 0),
        "review_required_ocr_label_count": ocr_counts.get("review_required_count", 0),
        "review_action_count": len(review_actions),
    }
    if cp_support_reconciliation is not None:
        counts["cp_support_supported_count"] = cp_support_reconciliation.get(
            "supported_count",
            0,
        )
        counts["cp_support_suggested_insertion_count"] = (
            cp_support_reconciliation.get("suggested_insertion_count", 0)
        )
    return {
        "source_id": f"mcp.{project_id}.v1",
        "source_path": source_refs.get("mcp_candidates", "outputs/mcp/mcp_candidates.json"),
        "evidence_type": "pretrip_major_critical_point_candidates",
        "status": "candidate_only",
        "project_id": project_id,
        "counts": counts,
        "policy": mcp_candidates.get("mcp_policy", {}),
        "source_refs": {
            "named_point_evidence": source_refs.get("mcp_named_point_evidence"),
            "retrieval_plan": source_refs.get("mcp_retrieval_plan"),
            "ocr_labels": source_refs.get("mcp_ocr_labels"),
            "candidates": source_refs.get("mcp_candidates"),
            "cp_support_reconciliation": source_refs.get(
                "mcp_cp_support_reconciliation"
            ),
            "review_actions": source_refs.get("mcp_review_log"),
        },
        "retrieval": {
            "artifact_kind": retrieval_counts.get("artifact_kind"),
            "planner_kind": retrieval_counts.get("planner_kind"),
            "pydantic_ai_responsibility": retrieval_counts.get(
                "pydantic_ai_responsibility"
            ),
            "truth_decision_allowed": retrieval_counts.get(
                "truth_decision_allowed",
                False,
            ),
            "fixture_backed": retrieval_counts.get("fixture_backed", True),
            "live_network_performed": retrieval_counts.get(
                "live_network_performed",
                False,
            ),
            "required_source_families": retrieval_counts.get(
                "required_source_families",
                [],
            ),
            "attempted_source_families": retrieval_counts.get(
                "attempted_source_families",
                [],
            ),
            "tool_contracts": retrieval_counts.get("tool_contracts", [])[:12],
            "fetch_summary_count": retrieval_counts.get("fetch_summary_count", 0),
            "fetch_summaries": retrieval_fetch_summaries,
            "queries": retrieval_queries,
        },
        "ocr": {
            "artifact_kind": ocr_counts.get("artifact_kind"),
            "label_count": ocr_counts.get("label_count", 0),
            "review_required_count": ocr_counts.get("review_required_count", 0),
            "labels": ocr_label_items,
        },
        "cp_support_reconciliation": {
            "artifact_kind": (cp_support_reconciliation or {}).get("artifact_kind"),
            "support_radius_m": (cp_support_reconciliation or {}).get(
                "support_radius_m",
                mcp_candidates.get("mcp_policy", {}).get("scout_cp_support_radius_m"),
            ),
            "supported_count": (cp_support_reconciliation or {}).get(
                "supported_count",
                0,
            ),
            "suggested_insertion_count": (
                cp_support_reconciliation or {}
            ).get("suggested_insertion_count", 0),
            "rows": support_rows[:12],
        },
        "candidates": [
            {
                **candidate,
                **_mcp_nested_support_projection(
                    candidate,
                    source_path=source_refs.get(
                        "mcp_candidates",
                        "outputs/mcp/mcp_candidates.json",
                    ),
                    evidence_type="pretrip_major_critical_point_candidate",
                    source_kind="mcp_candidate",
                    review_state=candidate.get("review_state", "needs_human_review"),
                ),
                **_mcp_projection_provenance(
                    candidate,
                    source_path=source_refs.get(
                        "mcp_candidates",
                        "outputs/mcp/mcp_candidates.json",
                    ),
                    evidence_type="pretrip_major_critical_point_candidate",
                    source_kind="mcp_candidate",
                    identity_keys=(
                        "mcp_id",
                        "label",
                        "linked_named_points",
                        "linked_cp_candidates",
                        "linked_risk_segments",
                    ),
                    confidence=candidate.get("confidence", "medium"),
                    stale_risk=candidate.get("stale_risk", "medium"),
                    review_state=candidate.get("review_state", "needs_human_review"),
                    model_output_summary=(
                        "Major critical point planning candidate synthesized "
                        "from named-point, CP, OCR, and risk support evidence; "
                        "not runtime safety truth."
                    ),
                ),
                "source_id": candidate.get("mcp_id"),
                "source_path": source_refs.get(
                    "mcp_candidates",
                    "outputs/mcp/mcp_candidates.json",
                ),
                "evidence_type": "pretrip_major_critical_point_candidate",
                "cp_support_reconciliation": support_by_mcp_id.get(
                    candidate.get("mcp_id")
                ),
                "latest_review_action": latest_review_by_mcp_id.get(
                    candidate.get("mcp_id")
                ),
            }
            for candidate in candidates
        ],
        "boundary": _summary_boundary(mcp_candidates.get("boundary", {})),
    }


def _boss_points_summary(
    boss_points_payload: dict[str, Any],
    boss_points_geojson: dict[str, Any] | None,
    *,
    source_refs: dict[str, str],
    route_display_geometry: dict[str, Any] | None = None,
    route_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    points = [
        point
        for point in boss_points_payload.get("boss_points", [])
        if isinstance(point, dict)
    ]
    source_path = (
        source_refs.get("boss_points")
        or boss_points_payload.get("boss_points_ref")
        or "outputs/boss_points.json"
    )
    geojson_source_path = (
        source_refs.get("boss_points_geojson")
        or boss_points_payload.get("boss_points_geojson_ref")
        or "outputs/boss_points.geojson"
    )
    geojson_features = (
        boss_points_geojson.get("features", [])
        if isinstance(boss_points_geojson, dict)
        else []
    )
    challenge_fit_summary = boss_points_payload.get("challenge_fit_summary")
    if not isinstance(challenge_fit_summary, dict):
        challenge_fit_summary = {}
    pressure_summary = boss_points_payload.get("route_pressure_profile_summary")
    if not isinstance(pressure_summary, dict):
        pressure_summary = {}
    demand_band_counts = Counter(
        str((point.get("route_boss_demand") or {}).get("band") or "unknown")
        for point in points
    )
    challenge_band_counts = Counter(
        str((point.get("challenge_fit") or {}).get("band") or "unknown")
        for point in points
    )
    boundary = {
        **boss_points_payload.get("boundary", {}),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "pretrip_candidate_evidence_only": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "medical_diagnosis": False,
    }
    projected_points = []
    for point in points:
        coordinate = _boss_point_display_coordinate(
            point,
            route_display_geometry=route_display_geometry,
            route_bounds=route_bounds,
        )
        map_target_ids = _boss_point_map_target_ids(point)
        projected_points.append(
            {
                "boss_point_id": point.get("boss_point_id"),
                "rank": point.get("rank"),
                "label": point.get("label"),
                "display_label": _boss_point_display_label(point),
                "map_label": point.get("map_label"),
                "display_mileage": point.get("display_mileage") or {},
                "source_candidate_id": point.get("source_candidate_id"),
                "source_mcp_id": point.get("source_mcp_id"),
                "display_theme": point.get("display_theme") or {},
                "lat": coordinate["lat"],
                "lon": coordinate["lon"],
                "source_coordinate": coordinate.get("source_coordinate"),
                "coordinate_source": coordinate["coordinate_source"],
                "map_coordinate_source": coordinate["map_coordinate_source"],
                "coordinate_uncertain": coordinate["coordinate_uncertain"],
                "source_coordinate_out_of_route_bounds": coordinate[
                    "source_coordinate_out_of_route_bounds"
                ],
                "route_position": point.get("route_position") or {},
                "mcp_classes": point.get("mcp_classes") or [],
                "linked_named_points": point.get("linked_named_points") or [],
                "map_target_ids": map_target_ids,
                "route_boss_demand": point.get("route_boss_demand") or {},
                "boss_selection": point.get("boss_selection") or {},
                "challenge_fit": point.get("challenge_fit") or {},
                "evidence_summary": point.get("evidence_summary") or {},
                "candidate_only": True,
                "runtime_safety_truth": False,
                "human_review_required": bool(
                    point.get("human_review_required", True)
                ),
                **_projection_record_metadata(
                    {
                        **point,
                        "candidate_id": point.get("boss_point_id")
                        or point.get("source_mcp_id")
                        or point.get("source_candidate_id"),
                        "map_target_ids": map_target_ids,
                        "source_refs": point.get("source_refs", []),
                    },
                    source_path=source_path,
                    evidence_type="pretrip_boss_point_challenge_fit",
                    source_kind="boss_point_challenge_fit",
                    identity_keys=(
                        "boss_point_id",
                        "source_mcp_id",
                        "source_candidate_id",
                        "label",
                        "source_refs",
                    ),
                    confidence="medium",
                    stale_risk="medium",
                    review_state="needs_human_review",
                    extractor_version="pretrip_boss_point_synthesis.projection.v1",
                    prompt_version=(
                        "not_applicable_deterministic_boss_point_projection.v1"
                    ),
                    summary=(
                        "Route Boss Demand compared with user pace coefficient "
                        "and private energy reserve bands to produce pretrip "
                        "Challenge Fit evidence; not runtime safety truth."
                    ),
                ),
            }
        )
    return {
        "source_id": (
            f"boss_points.{boss_points_payload.get('project_id', 'unknown')}.v1"
        ),
        "source_path": source_path,
        "geojson_source_path": geojson_source_path,
        "evidence_type": "pretrip_boss_point_challenge_fit",
        "status": boss_points_payload.get("status", "candidate_only"),
        "project_id": boss_points_payload.get("project_id"),
        "counts": {
            "boss_point_count": boss_points_payload.get(
                "boss_point_count",
                len(points),
            ),
            "geojson_feature_count": len(geojson_features),
            "route_pressure_sample_count": pressure_summary.get("sample_count"),
            "route_pressure_peak_count": pressure_summary.get("peak_count"),
            "not_ready_without_plan_change_count": challenge_band_counts.get(
                "not_ready_without_plan_change",
                0,
            ),
            "hard_requires_reviewed_buffer_count": challenge_band_counts.get(
                "hard_requires_reviewed_buffer",
                0,
            ),
            "boss_extreme_count": demand_band_counts.get("boss_extreme", 0),
            "boss_hard_count": demand_band_counts.get("boss_hard", 0),
        },
        "formula": {
            "route_boss_demand": (
                "sum(component_scores) * late_trip_multiplier * "
                "rest_stop_deemphasis_multiplier"
            ),
            "route_pressure_profile": (
                "full-route fixed-distance pressure bins -> local peaks -> "
                "Boss candidate merge"
            ),
            "challenge_fit": (
                "route_boss_demand_score * "
                "(1 + pace_energy_vulnerability)"
            ),
            "average_pace_only": False,
            "raw_health_payload_embedded": False,
        },
        "challenge_fit_summary": challenge_fit_summary,
        "route_pressure_profile_summary": pressure_summary,
        "band_counts": {
            "route_boss_demand": dict(demand_band_counts),
            "challenge_fit": dict(challenge_band_counts),
        },
        "boss_points": projected_points,
        "source_report": boss_points_payload.get("source_report", {}),
        "boundary": _summary_boundary(boundary),
    }


def _mileage_tag_alignment_summary(
    mileage_payload: dict[str, Any],
    mileage_geojson: dict[str, Any] | None,
    *,
    source_refs: dict[str, str],
) -> dict[str, Any]:
    tags = [
        tag
        for tag in mileage_payload.get("mileage_tags", [])
        if isinstance(tag, dict)
    ]
    counts = mileage_payload.get("counts") if isinstance(mileage_payload.get("counts"), dict) else {}
    raw_source_summary = (
        mileage_payload.get("raw_source_summary")
        if isinstance(mileage_payload.get("raw_source_summary"), dict)
        else {}
    )
    geojson_features = (
        mileage_geojson.get("features", [])
        if isinstance(mileage_geojson, dict)
        else []
    )
    route_alignment = (
        mileage_payload.get("route_mileage_alignment")
        if isinstance(mileage_payload.get("route_mileage_alignment"), dict)
        else {}
    )
    source_path = (
        source_refs.get("mileage_tag_alignment")
        or mileage_payload.get("mileage_tag_alignment_ref")
        or "outputs/mileage_tag_alignment.json"
    )
    geojson_source_path = (
        source_refs.get("mileage_tag_alignment_geojson")
        or mileage_payload.get("mileage_tag_alignment_geojson_ref")
        or "outputs/mileage_tag_alignment.geojson"
    )
    return {
        "source_id": (
            f"mileage_tag_alignment.{mileage_payload.get('project_id', 'unknown')}.v1"
        ),
        "source_path": source_path,
        "geojson_source_path": geojson_source_path,
        "evidence_type": "pretrip_workspace_mileage_tag_alignment",
        "status": mileage_payload.get("status", "candidate_only"),
        "project_id": mileage_payload.get("project_id"),
        "counts": {
            "tag_count": counts.get("tag_count", len(tags)),
            "aligned_tag_count": counts.get("aligned_tag_count", 0),
            "geojson_feature_count": len(geojson_features),
            "usable_anchor_count": counts.get("usable_anchor_count", 0),
            "projected_anchor_count": counts.get("projected_anchor_count", 0),
            "rejected_anchor_count": counts.get("rejected_anchor_count", 0),
            "candidate_only_count": counts.get("candidate_only_count", len(tags)),
            "runtime_safety_truth_count": counts.get("runtime_safety_truth_count", 0),
        },
        "source_kind_counts": counts.get("source_kind_counts", {}),
        "display_mileage_status_counts": counts.get(
            "display_mileage_status_counts",
            {},
        ),
        "route_projection_status_counts": counts.get(
            "route_projection_status_counts",
            {},
        ),
        "raw_source_summary": raw_source_summary,
        "route_mileage_alignment_summary": {
            "source_ref": route_alignment.get("source_ref"),
            "usable_anchor_count": route_alignment.get("usable_anchor_count", 0),
            "projected_anchor_count": route_alignment.get("projected_anchor_count", 0),
            "rejected_anchor_count": route_alignment.get("rejected_anchor_count", 0),
            "policy": route_alignment.get("policy", {}),
        },
        "sample_labels": [
            str(tag.get("display_label") or tag.get("display_mileage_label") or "")
            for tag in tags[:20]
        ],
        "timeline_items": [
            _mileage_timeline_tag_projection(tag, source_path)
            for tag in _select_mileage_timeline_tags(tags)
        ],
        "policy": mileage_payload.get("policy", {}),
        "boundary": _summary_boundary(mileage_payload.get("boundary", {})),
    }


def _select_mileage_timeline_tags(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred_source_kinds = {
        "checkpoint",
        "segment",
        "mcp_candidate",
        "boss_point",
        "route_pressure_sample",
        "trail_mileage_k_anchor",
        "road_mileage_stone",
    }
    candidates = [
        tag
        for tag in tags
        if isinstance(tag, dict)
        and _coerce_float(tag.get("lat")) is not None
        and _coerce_float(tag.get("lon")) is not None
        and (
            str(tag.get("source_kind") or "") in preferred_source_kinds
            or str(tag.get("route_projection_status") or "")
            in {"aligned", "nearby_offset", "route_distance_axis"}
        )
    ]

    def sort_key(tag: dict[str, Any]) -> tuple[int, float, str]:
        source_kind = str(tag.get("source_kind") or "")
        priority = 0 if source_kind in preferred_source_kinds else 1
        route_distance = _coerce_float(tag.get("route_distance_m"))
        if route_distance is None:
            route_distance = _coerce_float(tag.get("source_distance_m"))
        return (
            priority,
            route_distance if route_distance is not None else float("inf"),
            str(tag.get("mileage_tag_id") or tag.get("source_id") or ""),
        )

    return sorted(candidates, key=sort_key)[:240]


def _mileage_timeline_tag_projection(
    tag: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    display_mileage = tag.get("display_mileage")
    if not isinstance(display_mileage, dict):
        display_mileage = {}
    source_kind = str(tag.get("source_kind") or "mileage")
    source_id = str(tag.get("source_id") or tag.get("mileage_tag_id") or "mileage")
    label = str(
        tag.get("display_label")
        or tag.get("display_mileage_label")
        or display_mileage.get("label")
        or tag.get("source_label")
        or source_id
    )
    route_distance = _coerce_float(tag.get("route_distance_m"))
    projection_distance = _coerce_float(tag.get("route_projection_distance_m"))
    model_hash = _stable_projection_hash(
        {
            "source_path": source_path,
            "mileage_tag_id": tag.get("mileage_tag_id"),
            "source_id": source_id,
            "source_kind": source_kind,
            "route_distance_m": route_distance,
            "route_projection_status": tag.get("route_projection_status"),
            "display_mileage_label": tag.get("display_mileage_label"),
        }
    )
    source_refs = _unique_limited(
        [
            source_path,
            tag.get("source_ref"),
            tag.get("alignment_source_ref"),
            tag.get("route_projection_source_ref"),
        ]
    )
    return {
        "candidate_id": str(tag.get("mileage_tag_id") or f"mileage_tag.{source_id}"),
        "source_id": source_id,
        "source_path": source_path,
        "source_ref": tag.get("source_ref"),
        "evidence_type": "pretrip_mileage_tag_timeline_evidence",
        "label": label,
        "map_label": str(tag.get("display_mileage_label") or label),
        "source_kind": source_kind,
        "source_label": tag.get("source_label"),
        "lat": tag.get("lat"),
        "lon": tag.get("lon"),
        "route_distance_m": route_distance,
        "route_projection_distance_m": projection_distance,
        "route_projection_status": tag.get("route_projection_status"),
        "display_mileage": display_mileage,
        "display_mileage_label": tag.get("display_mileage_label"),
        "source_refs": source_refs,
        "review_state": "needs_review",
        "confidence": tag.get("confidence") or "medium",
        "stale_risk": "medium",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "source_attribution": [
            {
                "source_kind": source_kind,
                "source_ref": tag.get("source_ref") or source_path,
                "source_candidate_id": source_id,
                "source_label": tag.get("source_label") or label,
                "evidence_type": "pretrip_mileage_tag_timeline_evidence",
                "confidence": tag.get("confidence") or "medium",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "model_output_summary": (
            "Route mileage tag timeline projection; candidate-only pretrip "
            "evidence and not runtime safety truth."
        ),
        "model_output_sha256": model_hash,
        "extractor_version": "pretrip_mileage_tag_alignment.timeline_projection.v1",
        "pydantic_ai_prompt_version": (
            "not_applicable_deterministic_mileage_tag_alignment.v1"
        ),
    }


def _mcp_nested_support_projection(
    record: dict[str, Any],
    *,
    source_path: str,
    evidence_type: str,
    source_kind: str,
    review_state: str,
) -> dict[str, Any]:
    projected = dict(record)
    if isinstance(projected.get("spacing_suppression_details"), list):
        projected["spacing_suppression_details"] = [
            _mcp_spacing_suppression_detail_projection(
                detail,
                parent=record,
                source_path=source_path,
                parent_evidence_type=evidence_type,
                parent_source_kind=source_kind,
                review_state=review_state,
            )
            for detail in projected.get("spacing_suppression_details", [])
            if isinstance(detail, dict)
        ]
    if isinstance(projected.get("nearby_points_suppressed_by_spacing"), list):
        projected["nearby_points_suppressed_by_spacing"] = [
            _mcp_spacing_suppression_detail_projection(
                detail,
                parent=record,
                source_path=source_path,
                parent_evidence_type=evidence_type,
                parent_source_kind=source_kind,
                review_state=review_state,
            )
            for detail in projected.get("nearby_points_suppressed_by_spacing", [])
            if isinstance(detail, dict)
        ]
    return projected


def _mcp_spacing_suppression_detail_projection(
    detail: dict[str, Any],
    *,
    parent: dict[str, Any],
    source_path: str,
    parent_evidence_type: str,
    parent_source_kind: str,
    review_state: str,
) -> dict[str, Any]:
    source_kind = f"{parent_source_kind}_spacing_suppression_detail"
    evidence_type = f"{parent_evidence_type}_spacing_suppression_detail"
    return {
        **detail,
        **_mcp_projection_provenance(
            {
                **detail,
                "mcp_id": parent.get("mcp_id"),
                "candidate_id": detail.get("source_id"),
                "source_refs": [
                    source_path,
                    parent.get("mcp_id"),
                    parent.get("label"),
                    detail.get("source_id"),
                    detail.get("label"),
                    detail.get("reason"),
                ],
            },
            source_path=source_path,
            evidence_type=evidence_type,
            source_kind=source_kind,
            identity_keys=("mcp_id", "candidate_id", "source_id", "label", "reason"),
            confidence=detail.get("confidence", parent.get("confidence", "medium")),
            stale_risk=detail.get("stale_risk", parent.get("stale_risk", "medium")),
            review_state=detail.get("review_state", review_state),
            model_output_summary=(
                "MCP spacing-suppressed nearby point retained for review "
                "explainability; candidate-only planning evidence, not runtime "
                "safety truth."
            ),
        ),
    }


def _mcp_projection_provenance(
    record: dict[str, Any],
    *,
    source_path: str,
    evidence_type: str,
    source_kind: str,
    identity_keys: tuple[str, ...],
    confidence: Any,
    stale_risk: Any,
    review_state: str,
    model_output_summary: str,
) -> dict[str, Any]:
    identity_values = [
        ref
        for key in identity_keys
        for ref in _mcp_source_ref_values(record.get(key))
    ]
    nested_refs = []
    nearest_cp = record.get("nearest_scout_cp")
    if isinstance(nearest_cp, dict):
        nested_refs.extend(
            [
                nearest_cp.get("candidate_id"),
                nearest_cp.get("source_id"),
            ]
        )
    existing_source_refs = [
        ref
        for ref in _mcp_source_ref_values(record.get("source_refs"))
    ]
    existing_source_attribution = [
        attribution
        for attribution in record.get("source_attribution", []) or []
        if isinstance(attribution, dict)
    ]
    attribution_refs = [
        ref
        for attribution in existing_source_attribution
        for key in ("source_ref", "source_candidate_id", "source_artifact_id")
        for ref in _mcp_source_ref_values(attribution.get(key))
    ]
    source_refs = _unique_limited(
        [
            source_path,
            *existing_source_refs,
            *identity_values,
            *attribution_refs,
            *list(record.get("accepted_result_ids") or []),
            *list(record.get("rejected_result_ids") or []),
            *list(record.get("extracted_named_point_ids") or []),
            *list(record.get("linked_cp_candidates") or []),
            *nested_refs,
        ],
        limit=48,
    )
    identity_payload = {
        key: record.get(key)
        for key in identity_keys
        if record.get(key) is not None
    }
    model_hash = record.get("model_output_sha256") or _stable_projection_hash(
        {
            "evidence_type": evidence_type,
            "source_kind": source_kind,
            "source_refs": source_refs,
            "identity": identity_payload,
        }
    )
    source_attribution = existing_source_attribution or [
        {
            "source_kind": source_kind,
            "source_ref": source_path,
            "source_candidate_id": str(
                record.get("fetch_id")
                or record.get("query_id")
                or record.get("ocr_label_id")
                or record.get("mcp_id")
                or ""
            ),
            "confidence": confidence,
            "stale_risk": stale_risk,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    ]
    return {
        "source_refs": source_refs,
        "source_attribution": source_attribution,
        "confidence": confidence,
        "stale_risk": stale_risk,
        "review_state": record.get("review_state", review_state),
        "candidate_only": record.get("candidate_only", True),
        "runtime_safety_truth": record.get("runtime_safety_truth", False),
        "extractor_version": record.get(
            "extractor_version",
            "pretrip_mcp_synthesis.v1",
        ),
        "pydantic_ai_prompt_version": record.get(
            "pydantic_ai_prompt_version",
            "fixture_backed_pydantic_ai_tool_plan.v1",
        ),
        "model_output_sha256": str(model_hash),
        "model_output_summary": record.get(
            "model_output_summary",
            model_output_summary,
        ),
    }


def _mcp_source_ref_values(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        refs: list[str] = []
        for key in (
            "candidate_id",
            "source_id",
            "mcp_id",
            "label",
            "reason",
            "support_status",
        ):
            refs.extend(_mcp_source_ref_values(value.get(key)))
        return refs or [_stable_projection_hash(value)]
    if isinstance(value, (list, tuple, set)):
        return [
            ref
            for item in value
            for ref in _mcp_source_ref_values(item)
        ]
    return [str(value)]


def _latest_mcp_review_by_mcp_id(actions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for action in actions:
        mcp_id = action.get("mcp_id")
        if not mcp_id:
            continue
        latest[str(mcp_id)] = action
    return latest


def _mcp_review_actions_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    actions = list(payload.get("actions", []) or [])
    decision_counts = Counter(action.get("decision", "unknown") for action in actions)
    return {
        "source_id": f"mcp_review_actions.{payload.get('project_id', 'project')}",
        "source_path": source_path,
        "evidence_type": "pretrip_mcp_review_action_log",
        "status": "workspace_local_review_log",
        "project_id": payload.get("project_id"),
        "source_candidate_set_ref": payload.get("source_candidate_set_ref"),
        "counts": {
            "action_count": payload.get("action_count", len(actions)),
            "runtime_truth_count": 0,
            "compile_count": 0,
            "decision_counts": dict(sorted(decision_counts.items())),
        },
        "latest_by_mcp_id": _latest_mcp_review_by_mcp_id(actions),
        "actions": actions,
        "boundary": _summary_boundary(payload.get("boundary", {})),
    }


def _spatial_imprints_summary(
    *,
    project_id: str,
    candidates: dict[str, Any] | None,
    reviews: dict[str, Any] | None,
    imprint_set: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    source_refs: dict[str, str],
) -> dict[str, Any]:
    candidate_items = list((candidates or {}).get("candidates", []) or [])
    review_records = list((reviews or {}).get("records", []) or [])
    reviewed_imprints = list((imprint_set or {}).get("imprints", []) or [])
    counts = (
        dict(manifest["counts"])
        if manifest and isinstance(manifest.get("counts"), dict)
        else {
            "candidate_count": len(candidate_items),
            "review_record_count": len(review_records),
            "reviewed_imprint_count": len(reviewed_imprints),
            "runtime_truth_count": 0,
        }
    )
    source_path = (
        source_refs.get("spatial_imprint_manifest")
        or source_refs.get("spatial_imprint_set")
        or source_refs.get("spatial_imprint_candidates")
        or "project.json#spatial-imprints"
    )
    boundary = (
        manifest.get("boundary")
        if manifest and isinstance(manifest.get("boundary"), dict)
        else (imprint_set or candidates or {}).get("boundary", {})
    )
    return {
        "source_id": f"spatial_imprints.{project_id}.v0",
        "source_path": source_path,
        "evidence_type": "pretrip_spatial_imprints",
        "status": (
            "reviewed_pretrip_addendum"
            if reviewed_imprints
            else "candidate_review_workspace"
        ),
        "project_id": project_id,
        "counts": counts,
        "boundary": _summary_boundary(boundary),
        "manifest_ref": source_refs.get("spatial_imprint_manifest"),
        "spatial_imprint_set_ref": (
            manifest.get("spatial_imprint_set_ref")
            if manifest
            else source_refs.get("spatial_imprint_set")
        ),
        "candidate_source_path": source_refs.get("spatial_imprint_candidates"),
        "review_source_path": source_refs.get("spatial_imprint_reviews"),
        "candidates": [
            _spatial_imprint_item_summary(
                item,
                source_path=source_refs.get("spatial_imprint_candidates")
                or "candidates/spatial_imprints.json",
                review_state="needs_review",
            )
            for item in candidate_items
        ],
        "reviews": [
            {
                "review_id": record.get("review_id"),
                **_projection_record_metadata(
                    record,
                    source_path=source_refs.get("spatial_imprint_reviews")
                    or "reviews/spatial_imprint_reviews.json",
                    evidence_type="pretrip_spatial_imprint_review",
                    source_kind="spatial_imprint_review",
                    identity_keys=("review_id", "candidate_ref", "source_refs"),
                    review_state=record.get("decision", "reviewed"),
                    confidence="medium",
                    stale_risk="medium",
                    extractor_version="pretrip_spatial_imprint_review.projection.v1",
                    prompt_version="not_applicable_human_spatial_imprint_review.v1",
                    summary=(
                        "Human review record for a spatial imprint candidate; "
                        "review context only, not runtime safety truth."
                    ),
                ),
                "candidate_ref": record.get("candidate_ref"),
                "decision": record.get("decision"),
                "reviewed_by": record.get("reviewed_by"),
                "reviewed_at": record.get("reviewed_at"),
                "summary": record.get("summary"),
            }
            for record in review_records
        ],
        "reviewed_imprints": [
            _spatial_imprint_item_summary(
                item,
                source_path=source_refs.get("spatial_imprint_set")
                or "outputs/spatial_imprint_set.json",
                review_state="reviewed",
            )
            for item in reviewed_imprints
        ],
        "rejected_audit_refs": (manifest or {}).get("rejected_audit_refs", []),
        "disabled_audit_refs": (manifest or {}).get("disabled_audit_refs", []),
    }


def _spatial_imprint_item_summary(
    item: dict[str, Any],
    *,
    source_path: str,
    review_state: str,
) -> dict[str, Any]:
    trigger = item.get("trigger", {})
    predicates = list(trigger.get("predicates", []) or [])
    return {
        "imprint_id": item.get("imprint_id"),
        **_projection_record_metadata(
            item,
            source_path=source_path,
            evidence_type="pretrip_spatial_imprint",
            source_kind="spatial_imprint",
            identity_keys=("imprint_id", "source_refs", "label"),
            review_state=review_state,
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_spatial_imprint.projection.v1",
            prompt_version="not_applicable_deterministic_spatial_imprint_projection.v1",
            summary=(
                "Spatial imprint pretrip cue candidate or reviewed addendum; "
                "advisory planning evidence, not runtime safety truth."
            ),
        ),
        "label": item.get("label"),
        "kind": item.get("kind"),
        "severity": item.get("severity"),
        "planting_source": item.get("planting_source"),
        "lifecycle_state": (item.get("lifecycle") or {}).get("state"),
        "lifecycle_scope": (item.get("lifecycle") or {}).get("scope"),
        "payload_type": (item.get("payload") or {}).get("payload_type"),
        "text_zh": (item.get("payload") or {}).get("text_zh"),
        "anchor_type": (item.get("anchor") or {}).get("anchor_type"),
        "cp_ref": (item.get("anchor") or {}).get("cp_ref"),
        "segment_ref": (item.get("anchor") or {}).get("segment_ref"),
        "distance_m": (item.get("anchor") or {}).get("distance_m"),
        "trigger_operator": trigger.get("operator"),
        "predicate_types": [predicate.get("type") for predicate in predicates],
        "source_refs": item.get("source_refs", []),
        "boundary": _summary_boundary(item.get("boundary", {})),
    }


def _expert_contribution_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["log_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_expert_contribution_log",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "records": [
            {
                "contribution_id": record["contribution_id"],
                **_projection_record_metadata(
                    record,
                    source_path=source_path,
                    evidence_type="pretrip_expert_contribution_record",
                    source_kind="expert_contribution",
                    identity_keys=("contribution_id", "target_ref", "target_artifact_ref"),
                    review_state=record.get("review_state", "needs_review"),
                    confidence="medium",
                    stale_risk="medium",
                    extractor_version="pretrip_expert_contribution.projection.v1",
                    prompt_version="not_applicable_human_expert_contribution.v1",
                    summary=(
                        "Expert/admin contribution record for candidate planning "
                        "memory; not runtime safety truth."
                    ),
                ),
                "contributor_alias": record["contributor_alias"],
                "contributor_role": record["contributor_role"],
                "source_surface": record["source_surface"],
                "operation": record["operation"],
                "target_kind": record["target_kind"],
                "target_ref": record["target_ref"],
                "target_artifact_ref": record["target_artifact_ref"],
                "summary": record["summary"],
                "rationale": record["rationale"],
                "evidence_status": record["evidence_status"],
                "review_state": record["review_state"],
                "memory_seed_candidate": record["ai_assist"]["memory_seed_candidate"],
                "memory_writeback_allowed": record["ai_assist"][
                    "memory_writeback_allowed"
                ],
                "proposed_memory_tags": record["ai_assist"]["proposed_memory_tags"],
                "ai_assist_summary": record["ai_assist"]["summary"],
            }
            for record in payload.get("records", [])
        ],
    }


def _expert_contribution_apply_plan_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["plan_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_expert_contribution_apply_plan",
        "status": "workspace_apply_plan",
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "planned_operations": payload.get("planned_operations", []),
        "skipped_records": payload.get("skipped_records", []),
    }


def _expert_contribution_workspace_apply_result_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": payload["result_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_expert_contribution_workspace_apply_result",
        "status": "workspace_applied_candidate_import_metadata",
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "applied_operations": payload.get("applied_operations", []),
    }


def _departure_bundle_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["bundle_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_departure_bundle_manifest",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": payload["boundary"],
        "package": payload["package"],
        "route_refs": [
            _departure_bundle_route_ref(ref, source_path)
            for ref in payload.get("route_refs", [])
        ],
        "terrain_refs": [
            _departure_bundle_terrain_ref(ref, source_path)
            for ref in payload.get("terrain_refs", [])
        ],
    }


def _departure_bundle_route_ref(
    ref: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    metadata = _projection_record_metadata(
        ref,
        source_path=source_path,
        evidence_type="pretrip_departure_bundle_route_ref",
        source_kind="departure_bundle_route_ref",
        identity_keys=("ref_key", "ref", "sha256"),
        review_state="frozen_candidate_ref",
        confidence="medium" if ref.get("exists") else "low",
        stale_risk="medium",
        extractor_version="pretrip_departure_bundle.projection.v1",
        prompt_version="not_applicable_deterministic_departure_bundle_projection.v1",
        summary=(
            "Departure bundle route reference for reviewed-package staging; "
            "planning artifact metadata only, not runtime safety truth."
        ),
    )
    return {
        **ref,
        **metadata,
        "summary": _departure_bundle_ref_summary(
            ref.get("summary"),
            parent_ref=ref,
            source_path=source_path,
            source_kind="departure_bundle_route_ref_summary",
        ),
    }


def _departure_bundle_terrain_ref(
    ref: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    metadata = _projection_record_metadata(
        ref,
        source_path=source_path,
        evidence_type="pretrip_departure_bundle_terrain_ref",
        source_kind="departure_bundle_terrain_ref",
        identity_keys=("ref_key", "ref", "sha256"),
        review_state="frozen_candidate_ref",
        confidence="medium" if ref.get("exists") else "low",
        stale_risk="medium",
        extractor_version="pretrip_departure_bundle.projection.v1",
        prompt_version="not_applicable_deterministic_departure_bundle_projection.v1",
        summary=(
            "Departure bundle terrain reference for reviewed-package staging; "
            "planning artifact metadata only, not runtime safety truth."
        ),
    )
    return {
        **ref,
        **metadata,
        "summary": _departure_bundle_ref_summary(
            ref.get("summary"),
            parent_ref=ref,
            source_path=source_path,
            source_kind="departure_bundle_terrain_ref_summary",
        ),
    }


def _departure_bundle_ref_summary(
    summary: Any,
    *,
    parent_ref: dict[str, Any],
    source_path: str,
    source_kind: str,
) -> Any:
    if not isinstance(summary, dict):
        return summary
    return {
        **summary,
        "source_id": f"{parent_ref.get('ref_key', 'bundle_ref')}.summary",
        "source_path": source_path,
        "evidence_type": "pretrip_departure_bundle_ref_summary",
        **_projection_record_metadata(
            {
                **summary,
                "candidate_id": parent_ref.get("ref_key"),
                "source_refs": [
                    parent_ref.get("ref"),
                    parent_ref.get("ref_key"),
                    parent_ref.get("sha256"),
                ],
            },
            source_path=source_path,
            evidence_type="pretrip_departure_bundle_ref_summary",
            source_kind=source_kind,
            identity_keys=("candidate_id", "source_refs", "artifact_id"),
            review_state="frozen_candidate_ref_summary",
            confidence="medium" if parent_ref.get("exists") else "low",
            stale_risk="medium",
            extractor_version="pretrip_departure_bundle.projection.v1",
            prompt_version="not_applicable_deterministic_departure_bundle_projection.v1",
            summary=(
                "Nested departure bundle artifact summary for admin inspection; "
                "planning metadata only, not runtime safety truth."
            ),
        ),
    }


def _resource_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["plan_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_resource_plan",
        "status": payload["status"],
        "raw_payloads_embedded": payload["raw_payloads_embedded"],
        "external_api_calls_made": payload["external_api_calls_made"],
        "device_count": len(payload.get("devices", [])),
        "equipment_count": len(payload.get("equipment", [])),
        "team_member_count": len(payload.get("team_members", [])),
        "departure_readiness_context": payload.get("departure_readiness_context", {}),
    }


def _weather_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["evidence_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_weather_daylight_evidence",
        "status": payload["status"],
        "external_api_calls_made": payload["external_api_calls_made"],
        "authoritative_weather_computed": payload["authoritative_weather_computed"],
        "location_name": payload["location_name"],
        "date": payload["date"],
        "timezone": payload["timezone"],
        "daylight": payload["daylight"],
        "weather_window": payload["weather_window"],
    }


def _environment_geojson_summary(
    project_id: str,
    payload: dict[str, Any] | None,
    *,
    source_path: str,
    layer_id: str,
    evidence_type: str,
    summary_payload: dict[str, Any] | None = None,
    summary_source_path: str = "",
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    summary_payload = summary_payload if isinstance(summary_payload, dict) else {}
    features = (
        payload.get("features", [])
        if isinstance(payload, dict) and isinstance(payload.get("features"), list)
        else []
    )
    points = [
        point
        for feature in features
        if (point := _environment_feature_point(feature, source_path, layer_id))
        is not None
    ]
    status = "ready" if points else "missing_source"
    if isinstance(summary_payload, dict) and summary_payload.get("status"):
        status = str(summary_payload["status"])
    return {
        "source_id": f"{project_id}.{layer_id}",
        "source_path": source_path,
        "summary_source_path": summary_source_path,
        "evidence_type": evidence_type,
        "layer_id": layer_id,
        "status": status,
        "counts": {
            "feature_count": len(features),
            "point_count": len(points),
        },
        "bbox_wgs84": _environment_bbox(payload, summary_payload),
        "cache_policy": payload.get("cache_policy") or summary_payload.get("cache_policy"),
        "points": points,
        "features": points,
        "summary": summary_payload,
        "boundary": _summary_boundary(
            (payload or {}).get("boundary", {})
            if isinstance(payload, dict)
            else {
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
    }


def _cwa_weather_environment_summary(
    project_id: str,
    *,
    evidence_payload: dict[str, Any] | None,
    warnings_geojson: dict[str, Any] | None,
    observations_geojson: dict[str, Any] | None,
    source_refs: dict[str, str],
) -> dict[str, Any]:
    warning_summary = _environment_geojson_summary(
        project_id,
        warnings_geojson,
        source_path=source_refs.get("cwa_warnings_geojson", ""),
        layer_id="cwa-weather",
        evidence_type="cwa_weather_warning",
    )
    observation_summary = _environment_geojson_summary(
        project_id,
        observations_geojson,
        source_path=source_refs.get("cwa_observations_geojson", ""),
        layer_id="cwa-weather",
        evidence_type="cwa_rain_observation",
    )
    points = [*warning_summary["points"], *observation_summary["points"]]
    counts = dict((evidence_payload or {}).get("counts", {}))
    counts.update(
        {
            "warning_point_count": len(warning_summary["points"]),
            "observation_point_count": len(observation_summary["points"]),
            "point_count": len(points),
        }
    )
    return {
        "source_id": f"{project_id}.cwa-weather",
        "source_path": source_refs.get("cwa_weather_evidence", ""),
        "evidence_type": "cwa_weather_environment_evidence",
        "layer_id": "cwa-weather",
        "status": (evidence_payload or {}).get("status", "missing_source"),
        "counts": counts,
        "bbox_wgs84": (
            warning_summary.get("bbox_wgs84")
            or observation_summary.get("bbox_wgs84")
            or _environment_bbox(evidence_payload or {}, {})
        ),
        "cache_policy": (
            warning_summary.get("cache_policy")
            or observation_summary.get("cache_policy")
            or (evidence_payload or {}).get("cache_policy")
        ),
        "datasets": (evidence_payload or {}).get("datasets", []),
        "points": points,
        "features": points,
        "warnings": warning_summary["points"],
        "observations": observation_summary["points"],
        "external_api_calls_made": bool(
            (evidence_payload or {}).get("external_api_calls_made")
        ),
        "boundary": _summary_boundary(
            (evidence_payload or {}).get(
                "boundary",
                {"candidate_only": True, "runtime_safety_truth": False},
            )
        ),
    }


ENVIRONMENT_RISK_DERIVATIVE_SPECS: dict[str, dict[str, str]] = {
    "new_landslide_candidates": {
        "label": "新崩塌候選",
        "source_ref_key": "new_landslide_candidates",
        "candidate_kind": "new_landslide_candidate",
        "count_key": "new_landslide_candidate_count",
        "evidence_type": "pretrip_environment_new_landslide_candidate",
    },
    "wetness_flash_flood_susceptibility": {
        "label": "濕滑/溪溝暴漲候選",
        "source_ref_key": "wetness_flash_flood_susceptibility",
        "candidate_kind": "wetness_flash_flood_susceptibility",
        "count_key": "wetness_flash_flood_candidate_count",
        "evidence_type": "pretrip_environment_wetness_flash_flood_candidate",
    },
    "trail_obscurity_risk": {
        "label": "路跡不明候選",
        "source_ref_key": "trail_obscurity_risk",
        "candidate_kind": "trail_obscurity_risk",
        "count_key": "trail_obscurity_candidate_count",
        "evidence_type": "pretrip_environment_trail_obscurity_candidate",
    },
    "practical_darkness_time": {
        "label": "日落地形遮蔽候選",
        "source_ref_key": "practical_darkness_time",
        "candidate_kind": "practical_darkness_time",
        "count_key": "practical_darkness_candidate_count",
        "evidence_type": "pretrip_environment_practical_darkness_candidate",
    },
}


def _environment_risk_derivative_layers_summary(
    project_id: str,
    *,
    source_refs: dict[str, str],
    environment_risk_derivatives: dict[str, Any] | None,
    new_landslide_candidates: dict[str, Any] | None,
    wetness_flash_flood_susceptibility: dict[str, Any] | None,
    trail_obscurity_risk: dict[str, Any] | None,
    practical_darkness_time: dict[str, Any] | None,
    route_revalidation_report: dict[str, Any] | None,
) -> dict[str, Any]:
    payloads = {
        "new_landslide_candidates": new_landslide_candidates,
        "wetness_flash_flood_susceptibility": wetness_flash_flood_susceptibility,
        "trail_obscurity_risk": trail_obscurity_risk,
        "practical_darkness_time": practical_darkness_time,
    }
    summary_counts = (
        dict(environment_risk_derivatives.get("counts") or {})
        if isinstance(environment_risk_derivatives, dict)
        else {}
    )
    collections = {
        key: _environment_risk_candidate_collection_summary(
            project_id,
            key=key,
            spec=spec,
            payload=payloads[key],
            source_path=source_refs.get(spec["source_ref_key"], ""),
            summary_counts=summary_counts,
            derivatives_source_path=source_refs.get(
                "environment_risk_derivatives",
                "",
            ),
        )
        for key, spec in ENVIRONMENT_RISK_DERIVATIVE_SPECS.items()
    }
    report_source_path = source_refs.get("route_revalidation_report", "")
    report_status = (
        route_revalidation_report.get("status")
        if isinstance(route_revalidation_report, dict)
        else None
    ) or (
        (environment_risk_derivatives.get("route_revalidation_report") or {}).get(
            "status"
        )
        if isinstance(environment_risk_derivatives, dict)
        and isinstance(environment_risk_derivatives.get("route_revalidation_report"), dict)
        else None
    )
    total_candidate_count = sum(
        int(collection["counts"].get("candidate_count") or 0)
        for collection in collections.values()
    )
    source_ref_values = _unique_limited(
        [
            source_refs.get("project", "project.json"),
            source_refs.get("environment_risk_derivatives", ""),
            *(collection.get("source_path") for collection in collections.values()),
            report_source_path,
        ],
        limit=64,
    )
    counts = {
        "total_candidate_count": total_candidate_count,
        "category_count": len(collections),
        "new_landslide_candidate_count": collections["new_landslide_candidates"][
            "counts"
        ].get("candidate_count", 0),
        "wetness_flash_flood_candidate_count": collections[
            "wetness_flash_flood_susceptibility"
        ]["counts"].get("candidate_count", 0),
        "trail_obscurity_candidate_count": collections["trail_obscurity_risk"][
            "counts"
        ].get("candidate_count", 0),
        "practical_darkness_candidate_count": collections["practical_darkness_time"][
            "counts"
        ].get("candidate_count", 0),
    }
    return {
        "source_id": f"{project_id}.environment-risk-derivative-layers",
        "source_path": source_refs.get("environment_risk_derivatives", ""),
        "source_refs": source_ref_values,
        "evidence_type": "pretrip_environment_risk_derivative_layers",
        "artifact_kind": "pretrip_environment_risk_derivative_layers",
        "layer_id": "risk-delta",
        "status": (
            "ready"
            if total_candidate_count
            else (
                environment_risk_derivatives.get("status")
                if isinstance(environment_risk_derivatives, dict)
                else "missing_source"
            )
        ),
        "counts": counts,
        "category_items": _environment_risk_derivative_category_items(
            project_id,
            collections=collections,
            source_refs=source_refs,
            route_revalidation_report=route_revalidation_report,
            report_status=report_status,
        ),
        "route_revalidation_report": {
            "source_id": f"{project_id}.route-revalidation-report",
            "source_path": report_source_path,
            "evidence_type": "pretrip_environment_route_revalidation_report",
            "layer_id": "risk-delta",
            "label": "災後路線重評估",
            "status": report_status or "missing_event_date",
            "report": route_revalidation_report
            if isinstance(route_revalidation_report, dict)
            else {},
            "candidate_only": True,
            "runtime_safety_truth": False,
            **_projection_record_metadata(
                {
                    "candidate_id": f"{project_id}.route-revalidation-report",
                    "source_refs": source_ref_values,
                    "target_ids": ["risk-delta"],
                },
                source_path=report_source_path,
                evidence_type="pretrip_environment_route_revalidation_report",
                source_kind="environment_route_revalidation_report",
                identity_keys=("candidate_id", "source_refs", "target_ids"),
                review_state="needs_event_date",
                confidence="low",
                stale_risk="high",
                extractor_version="pretrip_environment_risk_derivatives.projection.v1",
                prompt_version=(
                    "not_applicable_deterministic_environment_risk_derivatives.v1"
                ),
                summary=(
                    "Route revalidation planning report projected from derived "
                    "environment evidence. Candidate-only review context, not "
                    "runtime safety truth."
                ),
            ),
        },
        **collections,
        "boundary": {
            "candidate_only": True,
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
            "server_side_only": True,
            "mobile_runtime_dependency": False,
            "raspberry_pi_runtime_dependency": False,
        },
    }


def _environment_risk_candidate_collection_summary(
    project_id: str,
    *,
    key: str,
    spec: dict[str, str],
    payload: dict[str, Any] | None,
    source_path: str,
    summary_counts: dict[str, Any],
    derivatives_source_path: str,
) -> dict[str, Any]:
    features = (
        [feature for feature in payload.get("features", []) if isinstance(feature, dict)]
        if isinstance(payload, dict)
        else []
    )
    candidates = [
        candidate
        for index, feature in enumerate(features)
        if (
            candidate := _environment_risk_candidate_from_feature(
                project_id,
                key=key,
                spec=spec,
                feature=feature,
                index=index,
                source_path=source_path,
                derivatives_source_path=derivatives_source_path,
            )
        )
        is not None
    ]
    candidate_count = len(candidates)
    declared_count = _coerce_int(summary_counts.get(spec["count_key"]), 0)
    severity_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    for candidate in candidates:
        severity = str(candidate.get("severity") or candidate.get("status") or "unknown")
        confidence = str(candidate.get("confidence") or "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
    return {
        "source_id": f"{project_id}.{key}",
        "source_path": source_path,
        "source_refs": _unique_limited(
            [source_path, derivatives_source_path],
            limit=16,
        ),
        "evidence_type": f"{spec['evidence_type']}_collection",
        "artifact_kind": "pretrip_environment_risk_derivative_candidate_collection",
        "layer_id": "risk-delta",
        "label": spec["label"],
        "status": (
            "ready"
            if candidate_count
            else (
                "ready_empty"
                if isinstance(payload, dict)
                else (
                    "missing_detail_source"
                    if declared_count
                    else "missing_or_empty_source"
                )
            )
        ),
        "counts": {
            "candidate_count": candidate_count,
            "feature_count": len(features),
            "declared_candidate_count": declared_count,
            "skipped_feature_count": max(len(features) - candidate_count, 0),
            "severity_counts": severity_counts,
            "confidence_counts": confidence_counts,
        },
        "bbox_wgs84": _environment_bbox(payload or {}, {}),
        "candidates": candidates,
        "features": candidates,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _environment_risk_candidate_from_feature(
    project_id: str,
    *,
    key: str,
    spec: dict[str, str],
    feature: dict[str, Any],
    index: int,
    source_path: str,
    derivatives_source_path: str,
) -> dict[str, Any] | None:
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    center = _environment_risk_candidate_center(props, geometry)
    if center is None:
        return None
    coordinates = _environment_risk_candidate_coordinates(geometry)
    source_segment_id = str(
        props.get("source_segment_id")
        or props.get("segment_id")
        or props.get("source_id")
        or ""
    )
    mid_distance = _coerce_float(props.get("mid_distance_m"))
    distance_label = (
        f"{mid_distance / 1000:.1f}K" if mid_distance is not None else f"{index + 1}"
    )
    fallback_id = source_segment_id or f"{index:03d}"
    candidate_id = str(
        props.get("candidate_id")
        or feature.get("id")
        or f"{project_id}.{key}.{fallback_id}"
    ).strip()
    label = str(props.get("label") or f"{spec['label']} {distance_label}")
    score = _coerce_float(props.get("score"))
    severity = str(props.get("severity") or "candidate")
    confidence = str(props.get("confidence") or "low")
    source_refs = _unique_limited(
        [
            source_path,
            derivatives_source_path,
            source_segment_id,
            props.get("source_raw_response_sha256"),
        ],
        limit=24,
    )
    item = {
        **props,
        "source_id": candidate_id,
        "candidate_id": candidate_id,
        "source_path": source_path,
        "source_refs": source_refs,
        "evidence_type": spec["evidence_type"],
        "layer_id": "risk-delta",
        "label": label,
        "candidate_kind": props.get("candidate_kind") or spec["candidate_kind"],
        "status": severity,
        "severity": severity,
        "confidence": confidence,
        "score": score,
        "lat": center["lat"],
        "lon": center["lon"],
        "coordinates": coordinates,
        "geometry_type": geometry.get("type"),
        "mid_distance_m": mid_distance,
        "start_distance_m": _coerce_float(props.get("start_distance_m")),
        "end_distance_m": _coerce_float(props.get("end_distance_m")),
        "supporting_metrics": props.get("supporting_metrics")
        if isinstance(props.get("supporting_metrics"), dict)
        else {},
        "missing_metrics": props.get("missing_metrics")
        if isinstance(props.get("missing_metrics"), list)
        else [],
        "rationale": props.get("rationale") or props.get("reason"),
        "source_segment_id": source_segment_id,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "map_target_ids": _unique_limited(
            [
                candidate_id,
                source_segment_id,
                props.get("segment_ref"),
                "risk-delta",
            ],
            limit=12,
        ),
        "boundary": {
            "candidate_only": True,
            "pretrip_candidate_evidence_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
        },
    }
    return {
        **item,
        **_projection_record_metadata(
            {
                **item,
                "source_refs": source_refs,
                "target_ids": item["map_target_ids"],
            },
            source_path=source_path,
            evidence_type=spec["evidence_type"],
            source_kind="environment_risk_derivative_candidate",
            identity_keys=("candidate_id", "source_refs", "target_ids"),
            review_state="candidate_review_pending",
            confidence=confidence,
            stale_risk=str(props.get("stale_risk") or "high"),
            extractor_version="pretrip_environment_risk_derivatives.projection.v1",
            prompt_version=(
                "not_applicable_deterministic_environment_risk_derivatives.v1"
            ),
            summary=(
                f"{spec['label']} projected from GEE/CWA/DEM route segment "
                "derivative evidence. Candidate-only planning evidence, not "
                "runtime safety truth."
            ),
        ),
    }


def _environment_risk_candidate_center(
    props: dict[str, Any],
    geometry: dict[str, Any],
) -> dict[str, float] | None:
    lat = _coerce_float(props.get("center_lat") or props.get("lat"))
    lon = _coerce_float(props.get("center_lon") or props.get("lon"))
    if lat is not None and lon is not None:
        return {"lat": lat, "lon": lon}
    geometry_type = geometry.get("type")
    try:
        if geometry_type == "Point":
            return _geojson_point_coordinate(geometry)
        if geometry_type == "LineString":
            coordinates = _geojson_line_coordinates(geometry)
            if coordinates:
                return coordinates[len(coordinates) // 2]
        if geometry_type == "MultiLineString":
            lines = geometry.get("coordinates", [])
            flattened = [
                {"lon": float(lon), "lat": float(lat)}
                for line in lines
                for lon, lat, *_ in line
            ]
            if flattened:
                return flattened[len(flattened) // 2]
    except (TypeError, ValueError):
        return None
    return None


def _environment_risk_candidate_coordinates(
    geometry: dict[str, Any],
) -> list[dict[str, float]]:
    try:
        if geometry.get("type") == "LineString":
            return _geojson_line_coordinates(geometry)
        if geometry.get("type") == "MultiLineString":
            return [
                {"lon": float(lon), "lat": float(lat)}
                for line in geometry.get("coordinates", [])
                for lon, lat, *_ in line
            ]
    except (TypeError, ValueError):
        return []
    return []


def _environment_risk_derivative_category_items(
    project_id: str,
    *,
    collections: dict[str, dict[str, Any]],
    source_refs: dict[str, str],
    route_revalidation_report: dict[str, Any] | None,
    report_status: str | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, spec in ENVIRONMENT_RISK_DERIVATIVE_SPECS.items():
        collection = collections[key]
        count = int(collection["counts"].get("candidate_count") or 0)
        first_candidate = (
            collection["candidates"][0] if collection.get("candidates") else {}
        )
        item = {
            "candidate_id": f"{project_id}.{key}.summary",
            "source_id": f"{project_id}.{key}.summary",
            "source_path": collection.get("source_path", ""),
            "source_refs": collection.get("source_refs", []),
            "evidence_type": "pretrip_environment_risk_derivative_category",
            "layer_id": "risk-delta",
            "label": f"{spec['label']}：{count}",
            "category_key": key,
            "candidate_kind": spec["candidate_kind"],
            "status": collection.get("status", "unknown"),
            "counts": collection.get("counts", {}),
            "candidate_count": count,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "map_target_ids": [key, "risk-delta"],
            "value_summary": {
                "candidate_count": count,
                "source_path": collection.get("source_path", ""),
                "first_candidate_label": first_candidate.get("label"),
            },
        }
        if first_candidate.get("lat") is not None and first_candidate.get("lon") is not None:
            item["lat"] = first_candidate["lat"]
            item["lon"] = first_candidate["lon"]
        items.append(
            {
                **item,
                **_projection_record_metadata(
                    {
                        **item,
                        "source_refs": item["source_refs"],
                        "target_ids": item["map_target_ids"],
                    },
                    source_path=item["source_path"],
                    evidence_type="pretrip_environment_risk_derivative_category",
                    source_kind="environment_risk_derivative_category",
                    identity_keys=("candidate_id", "source_refs", "target_ids"),
                    review_state="candidate_review_pending",
                    confidence=first_candidate.get("confidence") or "low",
                    stale_risk=first_candidate.get("stale_risk") or "high",
                    extractor_version=(
                        "pretrip_environment_risk_derivatives.projection.v1"
                    ),
                    prompt_version=(
                        "not_applicable_deterministic_environment_risk_derivatives.v1"
                    ),
                    summary=(
                        f"{spec['label']} category summary projected from "
                        "environment derivative candidate features. "
                        "Candidate-only planning evidence, not runtime safety truth."
                    ),
                ),
            }
        )
    report = route_revalidation_report if isinstance(route_revalidation_report, dict) else {}
    route_revalidation_item = {
        "candidate_id": f"{project_id}.route-revalidation-report.summary",
        "source_id": f"{project_id}.route-revalidation-report.summary",
        "source_path": source_refs.get("route_revalidation_report", ""),
        "source_refs": _unique_limited(
            [
                source_refs.get("route_revalidation_report", ""),
                source_refs.get("environment_risk_derivatives", ""),
            ]
        ),
        "evidence_type": "pretrip_environment_route_revalidation_report",
        "layer_id": "risk-delta",
        "label": "災後路線重評估",
        "category_key": "route_revalidation_report",
        "status": report_status or "missing_event_date",
        "counts": {},
        "candidate_only": True,
        "runtime_safety_truth": False,
        "map_target_ids": ["risk-delta"],
        "value_summary": {
            "route_revalidation_status": report_status,
            "event_date": report.get("event_date"),
            "headline": report.get("headline"),
        },
    }
    items.append(
        {
            **route_revalidation_item,
            **_projection_record_metadata(
                {
                    **route_revalidation_item,
                    "source_refs": route_revalidation_item["source_refs"],
                    "target_ids": route_revalidation_item["map_target_ids"],
                },
                source_path=route_revalidation_item["source_path"],
                evidence_type="pretrip_environment_route_revalidation_report",
                source_kind="environment_route_revalidation_report",
                identity_keys=("candidate_id", "source_refs", "target_ids"),
                review_state="needs_event_date",
                confidence="low",
                stale_risk="high",
                extractor_version="pretrip_environment_risk_derivatives.projection.v1",
                prompt_version=(
                    "not_applicable_deterministic_environment_risk_derivatives.v1"
                ),
                summary=(
                    "Route revalidation category summary projected from "
                    "environment derivative evidence. Candidate-only planning "
                    "evidence, not runtime safety truth."
                ),
            ),
        }
    )
    return items


def _environment_values_summary(
    project_id: str,
    *,
    source_refs: dict[str, str],
    cwa_qpf: dict[str, Any],
    cwa_weather: dict[str, Any],
    soil_moisture: dict[str, Any],
    antecedent_rain: dict[str, Any],
    gee_feature_package: dict[str, Any] | None,
    environment_risk_derivatives: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = [
        item
        for item in (
            _environment_layer_value_item(
                project_id,
                layer_id="cwa-qpf",
                label="CWA QPF values",
                summary=cwa_qpf,
                source_kind="cwa_qpf_numeric_database",
                confidence="medium",
                stale_risk="medium",
            ),
            _environment_layer_value_item(
                project_id,
                layer_id="cwa-weather",
                label="CWA weather values",
                summary=cwa_weather,
                source_kind="cwa_weather_numeric_database",
                confidence="medium",
                stale_risk="medium",
            ),
            _environment_layer_value_item(
                project_id,
                layer_id="soil-moisture",
                label="GEE soil moisture values",
                summary=soil_moisture,
                source_kind="gee_soil_moisture_numeric_database",
                confidence="medium",
                stale_risk="high",
            ),
            _environment_layer_value_item(
                project_id,
                layer_id="antecedent-rain",
                label="GEE antecedent rain values",
                summary=antecedent_rain,
                source_kind="gee_antecedent_rain_numeric_database",
                confidence="medium",
                stale_risk="high",
            ),
            _gee_feature_package_value_item(
                project_id,
                gee_feature_package,
                source_path=source_refs.get("gee_feature_package", ""),
            ),
            _environment_risk_derivatives_value_item(
                project_id,
                environment_risk_derivatives,
                source_path=source_refs.get("environment_risk_derivatives", ""),
            ),
        )
        if item is not None
    ]
    source_path = source_refs.get("project", "project.json")
    source_ref_values = _unique_limited(
        [
            source_path,
            *(item.get("source_path") for item in items),
            *(ref for item in items for ref in item.get("source_refs", [])),
        ]
    )
    boundary = {
        "candidate_only": True,
        "pretrip_candidate_evidence_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "external_api_calls_made": any(
            bool((item.get("boundary") or {}).get("external_api_calls_made"))
            for item in items
        ),
    }
    counts = {
        "item_count": len(items),
        "point_count": sum(
            int((item.get("counts") or {}).get("point_count") or 0) for item in items
        ),
        "dataset_count": len(
            {
                dataset_id
                for item in items
                for dataset_id in item.get("dataset_ids", [])
            }
        ),
        "gee_segment_count": sum(
            int((item.get("counts") or {}).get("segment_count") or 0)
            for item in items
        ),
    }
    return {
        "source_id": f"{project_id}.environment-values",
        "source_path": source_path,
        "source_refs": source_ref_values,
        "evidence_type": "pretrip_environment_value_database",
        "artifact_kind": "pretrip_environment_value_database",
        "status": "ready" if items else "missing_source",
        "counts": counts,
        "items": items,
        "boundary": boundary,
        **_projection_record_metadata(
            {
                "candidate_id": f"{project_id}.environment-values",
                "source_refs": source_ref_values,
                "counts": counts,
            },
            source_path=source_path,
            evidence_type="pretrip_environment_value_database",
            source_kind="environment_value_database",
            identity_keys=("candidate_id", "source_refs", "counts"),
            review_state="projection_only" if items else "missing_source",
            confidence="medium" if items else "low",
            stale_risk="high",
            extractor_version="pretrip_environment_values.projection.v1",
            prompt_version="not_applicable_deterministic_environment_values.v1",
            summary=(
                "CWA/GEE numeric evidence database projected into Map/Risk "
                "timeline review. Candidate-only planning context, not runtime "
                "safety truth."
            ),
        ),
    }


def _environment_layer_value_item(
    project_id: str,
    *,
    layer_id: str,
    label: str,
    summary: dict[str, Any],
    source_kind: str,
    confidence: str,
    stale_risk: str,
) -> dict[str, Any] | None:
    if not _environment_summary_has_values(summary):
        return None
    source_path = str(
        summary.get("summary_source_path") or summary.get("source_path") or ""
    )
    source_refs = _unique_limited(
        [
            source_path,
            summary.get("source_path"),
            summary.get("summary_source_path"),
            summary.get("source_id"),
        ]
    )
    center = _environment_summary_center(summary)
    points = [point for point in summary.get("points", []) if isinstance(point, dict)]
    value_summary = _environment_layer_value_payload(layer_id, summary)
    candidate_id = f"{project_id}.{layer_id}.environment-values"
    item = {
        "candidate_id": candidate_id,
        "source_id": candidate_id,
        "source_path": source_path,
        "evidence_type": "pretrip_environment_value_evidence",
        "layer_id": layer_id,
        "label": label,
        "status": summary.get("status", "unknown"),
        "counts": dict(summary.get("counts") or {}),
        "bbox_wgs84": summary.get("bbox_wgs84") or {},
        "cache_policy": summary.get("cache_policy"),
        "dataset_ids": _environment_dataset_ids(summary),
        "value_summary": value_summary,
        "raw_response_sha256": _first_point_value(points, "raw_summary_sha256"),
        "map_target_ids": _unique_limited(
            [point.get("source_id") for point in points if point.get("source_id")]
        ),
        "boundary": _environment_item_boundary(summary),
    }
    if center is not None:
        item.update(center)
    return {
        **item,
        **_projection_record_metadata(
            {
                **item,
                "source_refs": source_refs,
                "value_summary": value_summary,
            },
            source_path=source_path,
            evidence_type="pretrip_environment_value_evidence",
            source_kind=source_kind,
            identity_keys=("candidate_id", "source_refs", "value_summary"),
            review_state=(
                "projection_only"
                if summary.get("status") in {"ready", "fetched", "source_status_only"}
                else "needs_review"
            ),
            confidence=confidence,
            stale_risk=stale_risk,
            extractor_version="pretrip_environment_values.projection.v1",
            prompt_version="not_applicable_deterministic_environment_values.v1",
            summary=(
                f"{label} projected into pretrip Map/Risk timeline evidence; "
                "candidate-only numeric context, not runtime safety truth."
            ),
        ),
    }


def _gee_feature_package_value_item(
    project_id: str,
    payload: dict[str, Any] | None,
    *,
    source_path: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if not source_path and not payload:
        return None
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    route_buffer = route.get("buffer") if isinstance(route.get("buffer"), dict) else {}
    props = route_buffer.get("properties") if isinstance(route_buffer.get("properties"), dict) else {}
    bbox = props.get("bbox_wgs84") if isinstance(props.get("bbox_wgs84"), dict) else {}
    center = _bbox_center(bbox)
    counts = dict(payload.get("counts") or {})
    source_datasets = [
        dataset
        for dataset in payload.get("source_datasets", [])
        if isinstance(dataset, dict)
    ]
    dataset_ids = [
        str(dataset.get("dataset_id"))
        for dataset in source_datasets
        if dataset.get("dataset_id")
    ]
    candidate_id = f"{project_id}.gee-feature-package.values"
    value_summary = {
        "status": payload.get("status"),
        "segment_count": counts.get("segment_count"),
        "raw_segment_feature_count": counts.get("raw_segment_feature_count"),
        "stale_warning_count": counts.get("stale_warning_count"),
        "confidence_summary": payload.get("confidence_summary") or {},
        "cloud_filtering_thresholds": payload.get("cloud_filtering_thresholds") or {},
        "date_ranges": payload.get("date_ranges") or {},
    }
    boundary = {
        **_summary_boundary(payload.get("boundary", {})),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "server_side_only": bool(payload.get("server_side_only", True)),
        "mobile_runtime_dependency": bool(
            payload.get("mobile_runtime_dependency", False)
        ),
        "raspberry_pi_runtime_dependency": bool(
            payload.get("raspberry_pi_runtime_dependency", False)
        ),
    }
    item = {
        "candidate_id": candidate_id,
        "source_id": candidate_id,
        "source_path": source_path,
        "evidence_type": "pretrip_gee_route_environment_feature_package",
        "layer_id": "soil-moisture",
        "label": "GEE route feature package",
        "status": payload.get("status", "unknown"),
        "counts": counts,
        "bbox_wgs84": bbox,
        "dataset_ids": dataset_ids,
        "source_datasets": source_datasets,
        "value_summary": value_summary,
        "raw_response_sha256": payload.get("raw_response_sha256"),
        "stale_data_warnings": payload.get("stale_data_warnings", []),
        "cache_policy": {
            "cacheable": False,
            "ttl_seconds": 0,
            "must_refetch_on_prepare": True,
        },
        "boundary": boundary,
        "map_target_ids": ["risk-ribbon", "risk-score"],
    }
    if center is not None:
        item.update(center)
    source_refs = _unique_limited(
        [
            source_path,
            payload.get("raw_response_sha256"),
            *(dataset_ids[:16]),
        ]
    )
    return {
        **item,
        **_projection_record_metadata(
            {
                **item,
                "source_refs": source_refs,
                "value_summary": value_summary,
            },
            source_path=source_path,
            evidence_type="pretrip_gee_route_environment_feature_package",
            source_kind="gee_route_environment_feature_package",
            identity_keys=("candidate_id", "source_refs", "value_summary"),
            review_state=(
                "projection_only" if payload.get("status") == "ready" else "needs_review"
            ),
            confidence="medium" if payload.get("status") == "ready" else "low",
            stale_risk="high"
            if payload.get("stale_data_warnings")
            else "medium",
            extractor_version="pretrip_environment_values.projection.v1",
            prompt_version="not_applicable_deterministic_environment_values.v1",
            summary=(
                "Compact GEE route feature package projected into pretrip Map/Risk "
                "timeline evidence. Server-side export only; no mobile or Pi GEE "
                "runtime dependency."
            ),
        ),
    }


def _environment_risk_derivatives_value_item(
    project_id: str,
    payload: dict[str, Any] | None,
    *,
    source_path: str,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    counts = dict(payload.get("counts") or {})
    if not source_path and not counts:
        return None
    candidate_id = f"{project_id}.environment-risk-derivatives.values"
    report = (
        payload.get("route_revalidation_report")
        if isinstance(payload.get("route_revalidation_report"), dict)
        else {}
    )
    value_summary = {
        "status": payload.get("status"),
        "headline": payload.get("headline"),
        "new_landslide_candidate_count": counts.get(
            "new_landslide_candidate_count"
        ),
        "wetness_flash_flood_candidate_count": counts.get(
            "wetness_flash_flood_candidate_count"
        ),
        "trail_obscurity_candidate_count": counts.get(
            "trail_obscurity_candidate_count"
        ),
        "practical_darkness_candidate_count": counts.get(
            "practical_darkness_candidate_count"
        ),
        "route_revalidation_status": report.get("status"),
        "event_date": report.get("event_date"),
    }
    source_refs = _unique_limited(
        [
            source_path,
            payload.get("source_raw_response_sha256"),
            "outputs/environment/derived/new_landslide_candidates.geojson",
            "outputs/environment/derived/wetness_flash_flood_susceptibility.geojson",
            "outputs/environment/derived/trail_obscurity_risk.geojson",
            "outputs/environment/derived/practical_darkness_time.geojson",
            "outputs/environment/derived/route_revalidation_report.json",
        ]
    )
    source_datasets = [
        dataset
        for dataset in payload.get("source_datasets", [])
        if isinstance(dataset, dict)
    ]
    dataset_ids = [
        str(dataset.get("dataset_id"))
        for dataset in source_datasets
        if dataset.get("dataset_id")
    ]
    boundary = {
        **_summary_boundary(payload.get("boundary", {})),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "server_side_only": True,
        "mobile_runtime_dependency": False,
        "raspberry_pi_runtime_dependency": False,
    }
    item = {
        "candidate_id": candidate_id,
        "source_id": candidate_id,
        "source_path": source_path,
        "source_refs": source_refs,
        "evidence_type": "pretrip_environment_risk_derivative_database",
        "layer_id": "risk-delta",
        "label": "Environmental risk derivatives",
        "status": payload.get("status", "unknown"),
        "counts": counts,
        "dataset_ids": dataset_ids,
        "source_datasets": source_datasets,
        "value_summary": value_summary,
        "raw_response_sha256": payload.get("source_raw_response_sha256"),
        "source_metric_gaps": payload.get("source_metric_gaps", []),
        "cache_policy": {
            "cacheable": False,
            "ttl_seconds": 0,
            "must_refetch_on_prepare": True,
        },
        "boundary": boundary,
        "map_target_ids": [
            "risk-delta",
            "hazards",
            "soil-moisture",
            "antecedent-rain",
        ],
    }
    return {
        **item,
        **_projection_record_metadata(
            {
                **item,
                "source_refs": source_refs,
                "value_summary": value_summary,
            },
            source_path=source_path,
            evidence_type="pretrip_environment_risk_derivative_database",
            source_kind="environment_risk_derivatives",
            identity_keys=("candidate_id", "source_refs", "value_summary"),
            review_state=(
                "projection_only"
                if str(payload.get("status") or "").startswith("ready")
                else "needs_review"
            ),
            confidence=(
                "medium"
                if str(payload.get("status") or "").startswith("ready")
                else "low"
            ),
            stale_risk="high",
            extractor_version="pretrip_environment_values.projection.v1",
            prompt_version="not_applicable_deterministic_environment_values.v1",
            summary=(
                "Derived environmental risk candidates from GEE route segment "
                "features: landslide, wetness/flash flood, trail obscurity, "
                "practical darkness, and route revalidation. Candidate-only."
            ),
        ),
    }


def _environment_summary_has_values(summary: dict[str, Any]) -> bool:
    if not isinstance(summary, dict):
        return False
    if summary.get("source_path") or summary.get("summary_source_path"):
        return True
    if summary.get("points"):
        return True
    status = str(summary.get("status") or "")
    return status not in {"", "missing_source"}


def _environment_item_boundary(summary: dict[str, Any]) -> dict[str, Any]:
    boundary = dict(summary.get("boundary") or {})
    boundary.setdefault("candidate_only", True)
    boundary.setdefault("pretrip_candidate_evidence_only", True)
    boundary.setdefault("runtime_safety_truth", False)
    boundary.setdefault("phase1_runtime_mutation_allowed", False)
    return _summary_boundary(boundary)


def _environment_summary_center(summary: dict[str, Any]) -> dict[str, float] | None:
    bbox_center = _bbox_center(summary.get("bbox_wgs84"))
    if bbox_center is not None:
        return bbox_center
    for point in summary.get("points", []):
        if not isinstance(point, dict):
            continue
        lat = _coerce_float(point.get("lat"))
        lon = _coerce_float(point.get("lon"))
        if lat is not None and lon is not None:
            return {"lat": lat, "lon": lon}
    return None


def _bbox_center(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    west = _first_mapping_float(raw, ("west", "min_lon", "minLon"))
    east = _first_mapping_float(raw, ("east", "max_lon", "maxLon"))
    south = _first_mapping_float(raw, ("south", "min_lat", "minLat"))
    north = _first_mapping_float(raw, ("north", "max_lat", "maxLat"))
    if None in (west, east, south, north):
        return None
    return {"lat": (south + north) / 2.0, "lon": (west + east) / 2.0}


def _environment_dataset_ids(summary: dict[str, Any]) -> list[str]:
    datasets = summary.get("datasets") or (summary.get("summary") or {}).get("datasets")
    if isinstance(datasets, list):
        return [str(item) for item in datasets if item]
    points = [point for point in summary.get("points", []) if isinstance(point, dict)]
    return _unique_limited(
        [
            point.get("collection_id") or point.get("dataset_id") or point.get("provider")
            for point in points
        ]
    )


def _environment_layer_value_payload(
    layer_id: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    points = [point for point in summary.get("points", []) if isinstance(point, dict)]
    values = summary.get("summary", {}).get("values", {})
    if not isinstance(values, dict):
        values = {}
    if layer_id == "cwa-qpf":
        return {
            "max_rain_probability": _max_numeric(
                points,
                ("rain_probability", "rainProbability"),
            ),
            "max_rainfall_mm": _max_numeric(points, ("rainfall_mm", "rainfallMm")),
            "valid_from": _first_point_value(points, "valid_from", "start_time"),
            "valid_to": _first_point_value(points, "valid_to", "end_time"),
        }
    if layer_id == "cwa-weather":
        return {
            "warning_point_count": (summary.get("counts") or {}).get(
                "warning_point_count"
            ),
            "observation_point_count": (summary.get("counts") or {}).get(
                "observation_point_count"
            ),
            "max_last_24h_mm": _max_numeric(points, ("last_24h_mm", "rain_24h_mm")),
            "datasets": summary.get("datasets", []),
        }
    if layer_id == "soil-moisture":
        surface = _first_numeric(points, ("sm_surface_wetness", "sm_surface"))
        if surface is None:
            surface = _coerce_float(values.get("sm_surface_wetness"))
        rootzone = _first_numeric(points, ("sm_rootzone_wetness", "sm_rootzone"))
        if rootzone is None:
            rootzone = _coerce_float(values.get("sm_rootzone_wetness"))
        return {
            "sm_surface_wetness": surface,
            "sm_rootzone_wetness": rootzone,
            "antecedent_wetness_percentile": _first_numeric(
                points,
                ("antecedent_wetness_percentile",),
            ),
            "sample_count": (summary.get("summary") or {}).get("sample_count"),
        }
    if layer_id == "antecedent-rain":
        last_72h = _first_numeric(points, ("last_72h_mm",))
        if last_72h is None:
            last_72h = _coerce_float(values.get("last_72h_mm"))
        return {
            "last_72h_mm": last_72h,
            "last_24h_mm": _first_numeric(points, ("last_24h_mm",)),
            "last_3h_mm": _first_numeric(
                points,
                ("last_3h_mm", "precipitation_mm", "precipitation"),
            ),
            "sample_count": (summary.get("summary") or {}).get("sample_count"),
        }
    return {}


def _first_point_value(points: list[dict[str, Any]], *keys: str) -> Any:
    for point in points:
        for key in keys:
            value = point.get(key)
            if value not in (None, ""):
                return value
    return None


def _first_numeric(points: list[dict[str, Any]], keys: tuple[str, ...]) -> float | None:
    for point in points:
        for key in keys:
            value = _coerce_float(point.get(key))
            if value is not None:
                return value
    return None


def _first_mapping_float(raw: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _coerce_float(raw.get(key))
        if value is not None:
            return value
    return None


def _max_numeric(points: list[dict[str, Any]], keys: tuple[str, ...]) -> float | None:
    values = [
        value
        for point in points
        for key in keys
        if (value := _coerce_float(point.get(key))) is not None
    ]
    return max(values) if values else None


def _environment_bbox(
    payload: dict[str, Any],
    summary_payload: dict[str, Any],
) -> dict[str, float]:
    for raw in (payload.get("bbox_wgs84"), summary_payload.get("bbox_wgs84")):
        if not isinstance(raw, dict):
            continue
        west = _coerce_float(raw.get("west") or raw.get("min_lon") or raw.get("minLon"))
        east = _coerce_float(raw.get("east") or raw.get("max_lon") or raw.get("maxLon"))
        south = _coerce_float(raw.get("south") or raw.get("min_lat") or raw.get("minLat"))
        north = _coerce_float(raw.get("north") or raw.get("max_lat") or raw.get("maxLat"))
        if None not in (west, east, south, north):
            return {
                "west": float(west),
                "south": float(south),
                "east": float(east),
                "north": float(north),
            }
    return {}


def _environment_feature_point(
    feature: dict[str, Any],
    source_path: str,
    layer_id: str,
) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    if geometry.get("type") != "Point":
        return None
    try:
        coordinate = _geojson_point_coordinate(geometry)
    except (TypeError, ValueError):
        return None
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    source_id = str(props.get("source_id") or feature.get("id") or f"{layer_id}.point")
    label = str(
        props.get("label")
        or props.get("station_name")
        or props.get("headline")
        or props.get("area_name")
        or source_id
    )
    return {
        **props,
        "source_id": source_id,
        "candidate_id": source_id,
        "source_path": source_path,
        "source_refs": [source_path] if source_path else [],
        "evidence_type": props.get("evidence_type") or layer_id,
        "layer_id": props.get("layer_id") or layer_id,
        "label": label,
        "lat": coordinate["lat"],
        "lon": coordinate["lon"],
        "candidate_only": props.get("candidate_only", True),
        "runtime_safety_truth": props.get("runtime_safety_truth", False),
        "review_state": props.get("review_state", "needs_review"),
    }


def _contour_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_contour_interpretation_candidates",
        "status": payload["status"],
        "candidate_count": len(payload.get("candidates", [])),
        "not_observed_fact": payload["not_observed_fact"],
        "raw_payloads_embedded": False,
        "candidates": [
            {
                **candidate,
                **_projection_record_metadata(
                    {
                        **candidate,
                        "source_refs": list(
                            (candidate.get("source_artifact_refs") or {}).values()
                        )
                        + list(candidate.get("target_refs") or []),
                    },
                    source_path=source_path,
                    evidence_type="pretrip_contour_interpretation_candidate",
                    source_kind="contour_interpretation_candidate",
                    identity_keys=("candidate_id", "source_refs", "target_refs"),
                    review_state=(
                        (candidate.get("review_lifecycle") or {}).get(
                            "lifecycle_status"
                        )
                        or "admin_review_pending"
                    ),
                    confidence=candidate.get("confidence", "low"),
                    stale_risk=candidate.get("stale_risk", "medium"),
                    extractor_version="pretrip_contour_interpretation.projection.v1",
                    prompt_version="not_applicable_manual_contour_candidate.v1",
                    summary=(
                        "Contour interpretation candidate linked to map/DTM refs; "
                        "metadata-only planning evidence, not runtime safety truth."
                    ),
                ),
            }
            for candidate in payload.get("candidates", [])
        ],
    }


def _remote_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["summary_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_remote_contact_summary",
        "audience": payload["audience"],
        "readiness": payload["readiness"],
        "route": payload["route"],
        "retreat_route_summary": payload["retreat_route_summary"],
        "conservative_note_count": len(payload.get("conservative_notes", [])),
    }


def _runtime_handoff_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["manifest_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_runtime_handoff_metadata",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": payload["boundary"],
    }


def _runtime_audit_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["manifest_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_runtime_audit_manifest",
        "status": payload["status"],
        "counts": payload["counts"],
        "axes": payload.get("axes", []),
        "boundary": payload["boundary"],
    }


def _reference_tracks_summary(
    payload: dict[str, Any],
    source_path: str,
    *,
    display_geometry: dict[str, Any] | None = None,
    display_source_path: str = "",
) -> dict[str, Any]:
    display_by_id = {
        item["reference_id"]: item
        for item in (display_geometry or {}).get("reference_tracks", [])
    }
    return {
        "source_id": f"reference_tracks.{payload['project_id']}",
        "source_path": source_path,
        "evidence_type": "pretrip_reference_track_summary",
        "reference_track_count": payload["reference_track_count"],
        "route_role": payload.get("route_role", "golden_route"),
        "golden_route": payload.get("golden_route") or payload["primary_route"],
        "primary_route": payload["primary_route"],
        "reference_tracks": [
            _reference_track_item(track, source_path, display_by_id, display_source_path)
            for track in payload.get("reference_tracks", [])
        ],
        "boundary": payload["boundary"],
        "notes": payload.get("notes", []),
    }


def _reference_segment_timing_summary(
    payload: dict[str, Any] | None,
    source_path: str,
    *,
    project_id: str,
    route_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "source_id": f"reference_segment_timing.{project_id}.missing",
            "source_provider": "historical_gpx_source_index",
            "source_path": source_path,
            "sha256": None,
            "evidence_type": "pretrip_reference_segment_timing",
            "status": "missing_source",
            "counts": {
                "source_file_count": 0,
                "existing_source_file_count": 0,
                "timed_source_file_count": 0,
                "segment_count": 0,
                "usable_segment_count": 0,
                "measurement_count": 0,
            },
            "method": {},
            "segments": [],
            "data_quality": {
                "source_file_count": 0,
                "usable_segment_count": 0,
                "measurement_count": 0,
                "live_network_calls_made": False,
            },
            "privacy": {
                "aggregate_only": True,
                "raw_gpx_embedded_in_json": False,
                "raw_gpx_xml_embedded": False,
                "coordinates_embedded": False,
                "precise_timestamps_embedded": False,
                "source_original_paths_embedded": False,
            },
            "boundary": {
                "candidate_only": True,
                "pretrip_candidate_evidence_only": True,
                "medical_diagnosis": False,
                "phase1_runtime_safety_truth": False,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_brain_writeback_allowed": False,
                "safety_api_called": False,
                "historical_gpx_is_actual_user_track": False,
            },
            "notes": ["Reference segment timing artifact is not present."],
        }

    source_id = f"reference_segment_timing.{payload.get('project_id', project_id)}"
    segments = [
        segment for segment in payload.get("segments", []) if isinstance(segment, dict)
    ]
    focus_targets = _reference_segment_timing_focus_targets(
        segments,
        route_segments or [],
    )
    return {
        "source_id": source_id,
        "source_provider": payload.get("source_provider", "historical_gpx_source_index"),
        "source_path": source_path,
        "sha256": payload.get("sha256"),
        "route_guide_timing_source_path": payload.get("route_guide_timing_source_path"),
        "route_guide_timing_sha256": payload.get("route_guide_timing_sha256"),
        "evidence_type": "pretrip_reference_segment_timing",
        "status": payload.get("status", "unknown"),
        "counts": payload.get("counts", {}),
        "method": payload.get("method", {}),
        "segments": [
            _reference_segment_timing_item(
                segment,
                source_path,
                source_id,
                map_target_ids=focus_targets.get(str(segment.get("segment_id") or "")),
            )
            for segment in segments
        ],
        "data_quality": payload.get("data_quality", {}),
        "privacy": payload.get("privacy", {}),
        "boundary": payload.get("boundary", {}),
        "notes": payload.get("notes", []),
        **_projection_record_metadata(
            {
                "source_id": source_id,
                "source_refs": [
                    source_path,
                    payload.get("source_path"),
                    payload.get("route_guide_timing_source_path"),
                    payload.get("sha256"),
                ],
                "counts": payload.get("counts", {}),
            },
            source_path=source_path,
            evidence_type="pretrip_reference_segment_timing",
            source_kind="reference_segment_timing_aggregate",
            identity_keys=("source_id", "source_refs", "counts"),
            review_state="projection_only",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_reference_segment_timing.projection.v1",
            prompt_version="not_applicable_deterministic_reference_segment_timing.v1",
            summary=(
                "Reference segment timing aggregate for pretrip comparison; "
                "derived from historical GPX source metadata and route-guide "
                "timing, not runtime safety truth."
            ),
        ),
    }


def _reference_segment_timing_item(
    segment: dict[str, Any],
    source_path: str,
    parent_source_id: str,
    *,
    map_target_ids: list[str] | None = None,
) -> dict[str, Any]:
    segment_id = str(segment.get("segment_id") or "unknown_segment")
    return {
        **segment,
        "candidate_id": segment_id,
        "source_id": segment_id,
        "source_path": source_path,
        "evidence_type": "pretrip_reference_segment_timing_segment",
        "map_target_ids": _unique_limited(
            [
                *(map_target_ids or []),
                "route" if not map_target_ids else "",
            ],
            limit=36,
        ),
        "map_focus_basis": (
            "route_segment_distance_projection"
            if map_target_ids
            else "route_fallback_no_segment_distance_projection"
        ),
        "source_refs": _unique_limited(
            [
                source_path,
                parent_source_id,
                segment_id,
                *[
                    measurement.get("source_path")
                    for measurement in segment.get("measurements", [])
                    if isinstance(measurement, dict)
                ],
            ],
            limit=20,
        ),
        **_projection_record_metadata(
            {
                "segment_id": segment_id,
                "duration_minutes": segment.get("duration_minutes"),
                "sample_count": segment.get("sample_count"),
                "route_guide_comparison": segment.get("route_guide_comparison"),
            },
            source_path=source_path,
            evidence_type="pretrip_reference_segment_timing_segment",
            source_kind="reference_segment_timing_segment",
            identity_keys=(
                "segment_id",
                "duration_minutes",
                "sample_count",
                "route_guide_comparison",
            ),
            review_state="projection_only",
            confidence="medium" if segment.get("sample_count") else "low",
            stale_risk="medium",
            extractor_version="pretrip_reference_segment_timing.projection.v1",
            prompt_version="not_applicable_deterministic_reference_segment_timing.v1",
            summary=(
                "Per-segment reference timing range for admin/debug review; "
                "aggregate-only historical GPX evidence, not runtime safety truth."
            ),
        ),
    }


def _reference_segment_timing_focus_targets(
    timing_segments: list[dict[str, Any]],
    route_segments: list[dict[str, Any]],
) -> dict[str, list[str]]:
    route_intervals: list[dict[str, Any]] = []
    cursor_m = 0.0
    for segment in route_segments:
        segment_id = str(segment.get("candidate_id") or segment.get("source_id") or "")
        distance_m = _coerce_float(segment.get("distance_m")) or 0.0
        if not segment_id or distance_m <= 0:
            continue
        start_m = cursor_m
        cursor_m += distance_m
        route_intervals.append(
            {
                "segment_id": segment_id,
                "start_m": start_m,
                "end_m": cursor_m,
            }
        )
    if not route_intervals:
        return {}

    total_route_m = route_intervals[-1]["end_m"]
    timing_cursor_m = 0.0
    targets_by_timing_id: dict[str, list[str]] = {}
    for segment in timing_segments:
        segment_id = str(segment.get("segment_id") or "")
        distance_m = _reference_segment_timing_distance_m(segment)
        if not segment_id or distance_m <= 0:
            continue
        start_m = min(timing_cursor_m, total_route_m)
        end_m = min(max(start_m + distance_m, start_m + 1.0), total_route_m)
        matching_ids = [
            item["segment_id"]
            for item in route_intervals
            if item["end_m"] >= start_m and item["start_m"] <= end_m
        ]
        targets_by_timing_id[segment_id] = _unique_limited(matching_ids, limit=36)
        timing_cursor_m = end_m
    return targets_by_timing_id


def _reference_segment_timing_distance_m(segment: dict[str, Any]) -> float:
    track_distance = segment.get("track_distance_km")
    if isinstance(track_distance, dict):
        values = [
            _coerce_float(track_distance.get(key))
            for key in ("p50", "median", "mean", "min", "max")
        ]
        numeric = [value for value in values if value is not None and value > 0]
        if len(numeric) >= 2:
            return ((numeric[0] + numeric[-1]) / 2.0) * 1000.0
        if numeric:
            return numeric[0] * 1000.0
    distance_filter = segment.get("distance_filter_km")
    if isinstance(distance_filter, dict):
        minimum = _coerce_float(distance_filter.get("min"))
        maximum = _coerce_float(distance_filter.get("max"))
        if minimum is not None and maximum is not None and maximum > 0:
            return ((minimum + maximum) / 2.0) * 1000.0
    return 0.0


def _reference_track_item(
    track: dict[str, Any],
    source_path: str,
    display_by_id: dict[str, dict[str, Any]],
    display_source_path: str,
) -> dict[str, Any]:
    reference_id = track["reference_id"]
    display = display_by_id.get(reference_id)
    return {
        **track,
        "source_use_treatment": _reference_track_source_use_treatment(
            track,
            source_path,
        ),
        "candidate_id": reference_id,
        "source_id": reference_id,
        "source_path": source_path,
        "evidence_type": "pretrip_reference_track",
        **_reference_track_provenance(track, source_path),
        "label": track.get("route", {}).get("route_name") or reference_id,
        "review_state": "reference_only",
        "map_target_ids": [reference_id],
        **(
            {
                "display_geometry": {
                    "source_id": reference_id,
                    "source_path": display_source_path,
                    "evidence_type": "pretrip_reference_track_display_geometry",
                    **_projection_record_metadata(
                        {
                            **display,
                            "candidate_id": reference_id,
                            "source_refs": [
                                reference_id,
                                track.get("route", {}).get("artifact_id"),
                                track.get("route", {}).get("sha256"),
                            ],
                        },
                        source_path=display_source_path,
                        evidence_type="pretrip_reference_track_display_geometry",
                        source_kind="reference_track_display_geometry",
                        identity_keys=(
                            "candidate_id",
                            "source_refs",
                            "source_point_count",
                        ),
                        review_state="display_geometry_only",
                        confidence=track.get("confidence", "medium"),
                        stale_risk=track.get("stale_risk", "medium"),
                        extractor_version=(
                            "pretrip_reference_track_display_geometry.projection.v1"
                        ),
                        prompt_version=(
                            "not_applicable_deterministic_display_geometry.v1"
                        ),
                        summary=(
                            "Reference track display geometry for admin map focus "
                            "and comparison; derived visualization evidence only, "
                            "not runtime safety truth."
                        ),
                    ),
                    "source_point_count": display.get("source_point_count"),
                    "display_point_count": display.get("display_point_count"),
                    "display_segment_count": display.get("display_segment_count"),
                    "display_sampling_performed": display.get(
                        "display_sampling_performed"
                    ),
                    "coordinates": display.get("coordinates", []),
                    "coordinate_segments": display.get("coordinate_segments", []),
                    "segment_boundary_preserved": display.get(
                        "segment_boundary_preserved",
                        False,
                    ),
                }
            }
            if display is not None
            else {}
        ),
    }


def _reference_track_source_use_treatment(
    track: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    treatment = track.get("source_use_treatment") or {}
    reference_id = track.get("reference_id") or track.get("route", {}).get("artifact_id")
    return {
        **treatment,
        "source_id": f"{reference_id}.source_use_treatment",
        "source_path": source_path,
        "evidence_type": "pretrip_reference_track_source_use_treatment",
        **_projection_record_metadata(
            {
                **treatment,
                "candidate_id": reference_id,
                "source_refs": [
                    reference_id,
                    track.get("route", {}).get("artifact_id"),
                    track.get("route", {}).get("sha256"),
                    track.get("route", {}).get("source_uri"),
                ],
            },
            source_path=source_path,
            evidence_type="pretrip_reference_track_source_use_treatment",
            source_kind="reference_track_source_use_treatment",
            identity_keys=("candidate_id", "source_refs"),
            review_state="reference_only",
            confidence=track.get("confidence", "medium"),
            stale_risk=track.get("stale_risk", "medium"),
            extractor_version="pretrip_reference_tracks.projection.v1",
            prompt_version=(
                "not_applicable_deterministic_reference_track_projection.v1"
            ),
            summary=(
                "Reference track source-use boundary for pretrip comparison; "
                "not authoritative for MissionGraph and not runtime safety truth."
            ),
        ),
    }


def _reference_track_provenance(
    track: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    route = track.get("route", {})
    reference_id = track.get("reference_id") or route.get("artifact_id")
    source_uri = route.get("source_uri")
    source_refs = _unique_limited(
        [
            source_path,
            reference_id,
            route.get("artifact_id"),
            route.get("sha256"),
            source_uri,
        ],
        limit=16,
    )
    model_hash = _stable_projection_hash(
        {
            "reference_id": reference_id,
            "source_refs": source_refs,
            "distance_m": route.get("distance_m"),
            "point_count": route.get("point_count"),
        }
    )
    return {
        "source_refs": source_refs,
        "source_attribution": [
            {
                "source_kind": "reference_gpx_track",
                "source_ref": source_path,
                "source_uri": source_uri,
                "source_candidate_id": reference_id,
                "source_sha256": route.get("sha256"),
                "confidence": track.get("confidence", "medium"),
                "stale_risk": track.get("stale_risk", "medium"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "confidence": track.get("confidence", "medium"),
        "stale_risk": track.get("stale_risk", "medium"),
        "candidate_only": True,
        "runtime_safety_truth": False,
        "extractor_version": "pretrip_reference_tracks.projection.v1",
        "pydantic_ai_prompt_version": "not_applicable_deterministic_reference_track_projection.v1",
        "model_output_sha256": model_hash,
        "model_output_summary": (
            "Reference GPX track used as weak alignment and comparison evidence; "
            "pretrip candidate-only map evidence, not runtime safety truth."
        ),
    }


def _checkpoint_events_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": f"checkpoint_events.{payload['project_id']}",
        "source_path": source_path,
        "evidence_type": "pretrip_checkpoint_event_candidates",
        "event_count": payload["event_count"],
        "source_gpx": payload["source_gpx"],
        "events": [
            _checkpoint_event_summary(event, source_path)
            for event in payload.get("events", [])
        ],
        "boundary": payload["boundary"],
        "notes": payload.get("notes", []),
    }


def _checkpoint_event_summary(
    event: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        **event,
        **_projection_record_metadata(
            event,
            source_path=source_path,
            evidence_type="pretrip_checkpoint_event_candidate",
            source_kind="checkpoint_event_projection",
            identity_keys=(
                "event_id",
                "checkpoint_candidate_id",
                "route_point_index",
                "source_refs",
            ),
            review_state="candidate_event",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_checkpoint_event_projection.v1",
            prompt_version="not_applicable_deterministic_checkpoint_event_projection.v1",
            summary=(
                "Checkpoint event projection from pretrip route geometry; "
                "candidate-only planning event, not runtime safety truth."
            ),
        ),
    }


def _route_comparison_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["comparison_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_comparison",
        "classification": payload["classification"],
        "distance_delta_m": payload["distance_delta_m"],
        "point_count_delta": payload["point_count_delta"],
        "bbox_comparison": payload["bbox_comparison"],
    }


def _segment_terrain_summary(payload: dict[str, Any] | None, source_path: str) -> dict[str, Any]:
    if not payload:
        return {
            "source_id": "segment_terrain.unavailable",
            "source_path": source_path,
            "evidence_type": "pretrip_segment_dtm_coverage",
            "route_artifact_id": None,
            "segment_count": 0,
            "candidate_tile_count": 0,
            "raw_payloads_embedded": False,
            "notes": ["segment terrain metadata unavailable for this workspace"],
            "segment_metadata": [],
        }
    return {
        "source_id": payload["dtm_coverage_summary_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_segment_dtm_coverage",
        "route_artifact_id": payload["route_artifact_id"],
        "segment_count": payload["segment_count"],
        "candidate_tile_count": payload["candidate_tile_count"],
        "raw_payloads_embedded": False,
        "notes": payload["notes"],
        "segment_metadata": [
            _segment_terrain_metadata_summary(segment, source_path)
            for segment in payload.get("segment_metadata", [])
        ],
    }


def _segment_terrain_metadata_summary(
    segment: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        **segment,
        **_projection_record_metadata(
            {
                **segment,
                "source_refs": [
                    segment.get("segment_candidate_id"),
                    segment.get("from_candidate_id"),
                    segment.get("to_candidate_id"),
                    *[
                        tile.get("tile_ref") or tile.get("tile_id")
                        for tile in segment.get("candidate_tiles", [])
                    ],
                ],
            },
            source_path=source_path,
            evidence_type="pretrip_segment_dtm_metadata",
            source_kind="segment_dtm_metadata",
            identity_keys=(
                "segment_candidate_id",
                "from_candidate_id",
                "to_candidate_id",
                "source_refs",
            ),
            review_state="candidate_terrain_metadata",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_segment_dtm_coverage.projection.v1",
            prompt_version="not_applicable_deterministic_segment_dtm_projection.v1",
            summary=(
                "Segment-level DTM coverage metadata for pretrip terrain "
                "planning evidence, not runtime safety truth."
            ),
        ),
        "candidate_tiles": [
            {
                **tile,
                **_projection_record_metadata(
                    tile,
                    source_path=source_path,
                    evidence_type="pretrip_dtm_candidate_tile",
                    source_kind="dtm_candidate_tile",
                    identity_keys=("tile_id", "tile_ref", "match_reason"),
                    review_state="candidate_tile",
                    confidence="medium",
                    stale_risk="medium",
                    extractor_version="pretrip_segment_dtm_coverage.projection.v1",
                    prompt_version="not_applicable_deterministic_dtm_tile_projection.v1",
                    summary=(
                        "DTM candidate tile coverage metadata for terrain "
                        "planning evidence, not runtime safety truth."
                    ),
                ),
            }
            for tile in segment.get("candidate_tiles", [])
        ],
    }


def _after_action_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_after_action_next_plan_candidates",
        "status": payload["status"],
        "counts": payload["counts"],
        "raw_payloads_embedded": payload["raw_payloads_embedded"],
        "observed_fact_writeback_allowed": payload["observed_fact_writeback_allowed"],
        "historical_evidence_mutation_allowed": payload["historical_evidence_mutation_allowed"],
    }


def _load_capability_timeline_import(
    project_id: str,
    *,
    root: Path,
    project_root: Path,
) -> dict[str, Any] | None:
    candidate_roots = [
        (project_root / "outputs", project_root),
        (
            root
            / "tests"
            / "fixtures"
            / "post_analysis"
            / f"{project_id}_post_analysis"
            / "outputs",
            root,
        ),
    ]
    for output_dir, rel_root in candidate_roots:
        timeline_path = output_dir / "capability_timeline.json"
        capsule_path = output_dir / "capability_capsule.json"
        if timeline_path.exists() and capsule_path.exists():
            summary = summarize_capability_artifacts(
                timeline_path=timeline_path,
                capsule_path=capsule_path,
                root=rel_root,
            )
            return _capability_timeline_import_summary(
                summary,
                timeline_payload=_load_json(timeline_path),
            )
    return None


def _capability_timeline_import_summary(
    summary: dict[str, Any],
    *,
    timeline_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capsule_preview = summary.get("capsule_preview", {})
    boundary = summary.get("boundary", {})
    companion_capsule = (
        build_companion_capability_capsule_from_timeline(timeline_payload).model_dump(mode="json")
        if timeline_payload is not None
        else None
    )
    companion_capsule = (
        _companion_capability_capsule_projection(
            companion_capsule,
            source_path=summary.get(
                "source_path",
                "outputs/capability_timeline.json",
            ),
        )
        if companion_capsule is not None
        else None
    )

    def project_edge(edge: dict[str, Any]) -> dict[str, Any]:
        return {
            **_capability_timeline_edge_projection(edge),
            **_projection_record_metadata(
                edge,
                source_path=edge.get("source_path")
                or summary.get("source_path", "outputs/capability_timeline.json"),
                evidence_type=edge.get(
                    "evidence_type",
                    "pretrip_capability_timeline_edge",
                ),
                source_kind="capability_timeline_edge",
                identity_keys=("edge_id", "segment_id", "source_refs"),
                review_state="requires_human_review",
                confidence=edge.get("confidence", "medium"),
                stale_risk=edge.get("stale_risk", "medium"),
                extractor_version="post_analysis_capability_timeline.projection.v1",
                prompt_version="not_applicable_deterministic_capability_timeline_import.v1",
                summary=(
                    "Post-analysis capability timeline edge imported as "
                    "candidate-only pacing evidence, not runtime safety truth."
                ),
            ),
        }

    return {
        **summary,
        "source_id": "pretrip.imported_capability_timeline",
        "evidence_type": "pretrip_capability_timeline_import",
        "status": "read_only_post_analysis_import",
        "nodes": [
            {
                **node,
                **_projection_record_metadata(
                    node,
                    source_path=(node.get("source_refs") or ["outputs/capability_timeline.json"])[0],
                    evidence_type="pretrip_capability_timeline_node",
                    source_kind="capability_timeline_node",
                    identity_keys=("node_id", "source_refs"),
                    review_state="requires_human_review",
                    confidence=node.get("confidence", "medium"),
                    stale_risk=node.get("stale_risk", "medium"),
                    extractor_version="post_analysis_capability_timeline.projection.v1",
                    prompt_version="not_applicable_deterministic_capability_timeline_import.v1",
                    summary=(
                        "Post-analysis capability timeline node imported as "
                        "candidate-only pacing context, not runtime safety truth."
                    ),
                ),
            }
            for node in summary.get("nodes", [])
        ],
        "edges": [project_edge(edge) for edge in summary.get("edges", [])],
        "observed_edges": [
            project_edge(edge) for edge in summary.get("observed_edges", [])
        ],
        "route_time_comparison": {
            **(summary.get("route_time_comparison") or {}),
            "segments": [
                {
                    **segment,
                    **_projection_record_metadata(
                        segment,
                        source_path=(
                            segment.get("source_refs")
                            or ["outputs/capability_timeline.json#route-time"]
                        )[0],
                        evidence_type="pretrip_capability_timeline_route_time_comparison",
                        source_kind="capability_route_time_comparison",
                        identity_keys=("comparison_id", "edge_id", "segment_id", "source_refs"),
                        review_state="requires_human_review",
                        confidence=segment.get("confidence", "medium"),
                        stale_risk=segment.get("stale_risk", "medium"),
                        extractor_version="post_analysis_route_time_comparison.projection.v1",
                        prompt_version="not_applicable_deterministic_route_time_comparison.v1",
                        summary=(
                            "Route-time comparison imported as candidate-only "
                            "pacing evidence, not runtime safety truth."
                        ),
                    ),
                }
                for segment in (summary.get("route_time_comparison") or {}).get(
                    "segments",
                    [],
                )
            ],
        },
        "counts": {
            "edge_count": summary.get("edge_count", 0),
            "rest_interval_count": summary.get("rest_interval_count", 0),
        },
        "planning_use": {
            "candidate_pacing_reference_only": True,
            "requires_human_review_before_eta_use": True,
            "auto_applies_to_eta": False,
            "auto_compiles_mission_graph": False,
        },
        "companion_capability_capsule": companion_capsule,
        "privacy": {
            "source_scope": capsule_preview.get("source_scope"),
            "raw_track_shared": capsule_preview.get("raw_track_shared"),
            "exact_timestamps_shared": capsule_preview.get("exact_timestamps_shared"),
            "incident_details_shared": capsule_preview.get("incident_details_shared"),
        },
        "boundary": {
            **boundary,
            "read_only_import": True,
            "planning_candidate_input_only": True,
            "requires_human_review_before_use": True,
            "workspace_mutation_allowed": False,
            "pretrip_eta_autocalibration_allowed": False,
            "mission_graph_compile_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "runtime_safety_truth": False,
        },
    }


def _capability_timeline_edge_projection(edge: dict[str, Any]) -> dict[str, Any]:
    projected = dict(edge)
    terrain_profile = projected.get("terrain_profile")
    if isinstance(terrain_profile, dict):
        samples = terrain_profile.get("samples") or []
        projected["terrain_profile"] = {
            "source": terrain_profile.get("source"),
            "sample_distance_m": terrain_profile.get("sample_distance_m"),
            "sample_count": len(samples) if isinstance(samples, list) else 0,
            "profile_svg_ref": terrain_profile.get("profile_svg_ref"),
            "summary": terrain_profile.get("summary", {}),
        }
    return projected


def _companion_capability_capsule_projection(
    capsule: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    capsule_source_path = str(capsule.get("source_path") or source_path)
    source_id = capsule.get(
        "source_id",
        capsule.get("artifact_kind", "scout_companion_capability_capsule"),
    )
    return {
        **capsule,
        "source_id": source_id,
        "source_path": capsule_source_path,
        "evidence_type": "pretrip_companion_capability_capsule",
        **_projection_record_metadata(
            {
                **capsule,
                "candidate_id": capsule.get(
                    "owner_profile_ref",
                    "local_user.private",
                ),
                "source_refs": [
                    capsule_source_path,
                    source_path,
                    capsule.get("sha256"),
                    capsule.get("owner_profile_ref"),
                ],
            },
            source_path=capsule_source_path,
            evidence_type="pretrip_companion_capability_capsule",
            source_kind="post_analysis_capability_capsule",
            identity_keys=("candidate_id", "source_refs", "sha256"),
            review_state="review_only",
            confidence=capsule.get("confidence", "medium"),
            stale_risk="medium",
            extractor_version="post_analysis_capability_capsule.projection.v1",
            prompt_version="not_applicable_deterministic_companion_capsule_projection.v1",
            summary=(
                "Post-analysis companion capability capsule imported for "
                "pretrip review-only matching context; not runtime safety truth."
            ),
        ),
    }


def _companion_match_review_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    ranked_matches = payload.get("ranked_matches", [])
    recommended_review_refs = payload.get("recommended_review_refs", [])
    top_match = ranked_matches[0] if ranked_matches else {}
    privacy = payload.get("privacy", {})
    boundary = payload.get("boundary", {})
    return {
        "source_id": "pretrip.companion_match_review",
        "source_provider": payload.get("source_provider"),
        "source_path": source_path,
        "sha256": payload.get("sha256"),
        "evidence_type": "pretrip_companion_match_review",
        "status": "read_only_companion_match_review",
        "artifact_version": payload.get("artifact_version"),
        "query_profile_ref": payload.get("query_profile_ref"),
        "counts": {
            "candidate_count": payload.get("candidate_count", 0),
            "ranked_match_count": len(ranked_matches),
            "recommended_review_count": len(recommended_review_refs),
        },
        "summary": {
            "top_candidate_profile_ref": top_match.get("candidate_profile_ref"),
            "top_match_score": top_match.get("match_score"),
            "top_match_band": top_match.get("match_band"),
            "recommended_review_refs": recommended_review_refs[:12],
            "raw_health_payload_shared": privacy.get("raw_health_payload_shared"),
            "raw_track_shared": privacy.get("raw_track_shared"),
            "exact_timestamps_shared": privacy.get("exact_timestamps_shared"),
            "auto_applies_to_eta": False,
            "ranked_matches": [
                {
                    "candidate_profile_ref": match.get("candidate_profile_ref"),
                    "match_score": match.get("match_score"),
                    "match_band": match.get("match_band"),
                    "mismatch_notes": match.get("mismatch_notes", [])[:4],
                }
                for match in ranked_matches[:12]
            ],
        },
        "review_policy": payload.get("review_policy", {}),
        "data_quality": payload.get("data_quality", {}),
        "privacy": privacy,
        "boundary": {
            **boundary,
            "read_only_import": True,
            "planning_candidate_input_only": True,
            "requires_human_review_before_use": True,
            "workspace_mutation_allowed": False,
            "pretrip_eta_autocalibration_allowed": False,
            "mission_graph_compile_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "runtime_safety_truth": False,
            "medical_diagnosis": False,
            "phase1_runtime_safety_truth": False,
            "safety_api_calls_allowed": False,
        },
        "limitations": payload.get("limitations", []),
    }


def _post_analysis_energy_feedback_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    privacy = payload.get("privacy", {})
    boundary = payload.get("boundary", {})
    return {
        "source_id": "post_analysis.energy_reserve_feedback",
        "source_provider": payload.get("source_provider"),
        "source_path": source_path,
        "sha256": payload.get("sha256"),
        "evidence_type": "post_analysis_energy_reserve_feedback",
        "status": "read_only_post_analysis_feedback",
        "artifact_version": payload.get("artifact_version"),
        "case_id": payload.get("case_id"),
        "counts": {
            "feedback_note_count": len(payload.get("feedback_notes", [])),
            "has_predicted_depletion_checkpoint": int(
                bool(payload.get("predicted_depletion_checkpoint_name"))
            ),
        },
        "summary": {
            "pretrip_projection_source_path": payload.get(
                "pretrip_projection_source_path"
            ),
            "capability_timeline_source_path": payload.get(
                "capability_timeline_source_path"
            ),
            "predicted_target_duration_minutes": payload.get(
                "predicted_target_duration_minutes"
            ),
            "actual_elapsed_duration_minutes": payload.get(
                "actual_elapsed_duration_minutes"
            ),
            "actual_moving_duration_minutes": payload.get(
                "actual_moving_duration_minutes"
            ),
            "actual_vs_projected_elapsed_delta_minutes": payload.get(
                "actual_vs_projected_elapsed_delta_minutes"
            ),
            "predicted_depletion_checkpoint_name": payload.get(
                "predicted_depletion_checkpoint_name"
            ),
            "actual_rest_time_minutes": payload.get("actual_rest_time_minutes"),
            "raw_track_shared": privacy.get("raw_track_shared"),
            "exact_timestamps_shared": privacy.get("exact_timestamps_shared"),
            "auto_applies_to_eta": False,
        },
        "feedback_notes": payload.get("feedback_notes", []),
        "data_quality": payload.get("data_quality", {}),
        "privacy": privacy,
        "boundary": {
            **boundary,
            "read_only_import": True,
            "planning_calibration_candidate_only": True,
            "requires_human_review_before_use": True,
            "workspace_mutation_allowed": False,
            "pretrip_eta_autocalibration_allowed": False,
            "mission_graph_compile_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "runtime_safety_truth": False,
            "medical_diagnosis": False,
            "phase1_runtime_safety_truth": False,
            "safety_api_calls_allowed": False,
        },
    }


def _brain_seed_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    observed_facts = list(payload.get("observed_facts", []) or [])
    nodes = list(payload.get("nodes", []) or [])
    model_interpretations = list(payload.get("model_interpretations", []) or [])
    non_review_gated_model_count = sum(
        1
        for item in model_interpretations
        if item.get("write_policy") != "append_only_requires_review"
    )
    node_types = sorted(
        {str(node.get("type")) for node in nodes if node.get("type")}
    )
    return {
        "source_id": "brain_seed_nodes.chilai_nanhua_day1",
        "source_path": source_path,
        "evidence_type": "pretrip_brain_seed_nodes",
        "node_count": len(nodes),
        "artifact_count": len(payload.get("artifacts", [])),
        "derived_measurement_count": len(payload.get("derived_measurements", [])),
        "human_review_count": len(payload.get("human_reviews", [])),
        "model_interpretation_count": len(model_interpretations),
        "observed_fact_count": len(observed_facts)
        + sum(1 for node in nodes if node.get("type") == "ObservedFact"),
        "non_review_gated_model_interpretation_count": non_review_gated_model_count,
        "node_types": node_types,
        "boundary": {
            "candidate_seed_only": True,
            "automatic_brain_write_allowed": False,
            "explicit_operator_import_required": True,
            "model_output_as_observed_fact_allowed": False,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_brain_writeback_allowed": False,
        },
        "model_interpretations": [
            _brain_seed_model_interpretation_summary(item, source_path)
            for item in model_interpretations[:12]
        ],
    }


def _brain_seed_model_interpretation_summary(
    item: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        **item,
        **_projection_record_metadata(
            {
                **item,
                "source_refs": list(item.get("input_refs") or [])
                + list(item.get("artifact_refs") or []),
                "candidate_id": item.get("id"),
            },
            source_path=source_path,
            evidence_type="pretrip_brain_seed_model_interpretation",
            source_kind="brain_seed_model_interpretation",
            identity_keys=("id", "input_refs", "artifact_refs", "subject"),
            review_state="append_only_requires_review",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_brain_seed.projection.v1",
            prompt_version=item.get(
                "model_version",
                "not_applicable_planning_output_projection.v1",
            ),
            summary=(
                "Brain seed ModelInterpretation preview; append-only review "
                "artifact, not ObservedFact and not runtime safety truth."
            ),
        ),
    }


def _planning_skill_audit_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    records = [record for record in payload.get("records", []) if isinstance(record, dict)]
    automatic_writeback_count = sum(
        1
        for record in records
        if (record.get("preflight_results") or {})
        .get("writeback_policy", {})
        .get("automatic_brain_write")
        is True
    )
    observed_fact_count = sum(1 for record in records if record.get("type") == "ObservedFact")
    node_types = sorted({str(record.get("type")) for record in records if record.get("type")})
    return {
        "source_id": payload.get(
            "audit_id",
            f"planning_skill_audit.{payload.get('project_id', 'project')}",
        ),
        "source_path": source_path,
        "evidence_type": "pretrip_planning_skill_audit",
        "status": "skill_run_records_candidate_only",
        "project_id": payload.get("project_id"),
        "project_ref": payload.get("project_ref"),
        "counts": {
            "record_count": len(records),
            "automatic_brain_write_count": automatic_writeback_count,
            "observed_fact_count": observed_fact_count,
            "skill_run_record_count": sum(
                1 for record in records if record.get("type") == "SkillRunRecord"
            ),
        },
        "node_types": node_types,
        "records": [
            _planning_skill_record_summary(record, source_path)
            for record in records
        ],
        "boundary": {
            "skill_run_record_only": node_types == ["SkillRunRecord"],
            "automatic_brain_write_allowed": False,
            "observed_fact_write_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "runtime_safety_truth": False,
            "candidate_only": True,
        },
    }


def _planning_skill_record_summary(
    record: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    writeback_policy = (record.get("preflight_results") or {}).get(
        "writeback_policy",
        {},
    )
    return {
        **record,
        **_projection_record_metadata(
            {
                **record,
                "source_refs": list(record.get("input_refs") or [])
                + list(record.get("output_refs") or [])
                + list(record.get("artifact_refs") or []),
                "candidate_id": record.get("id"),
            },
            source_path=source_path,
            evidence_type="pretrip_planning_skill_run_record",
            source_kind="planning_skill_run_record",
            identity_keys=("id", "skill_id", "input_refs", "output_refs"),
            review_state="skill_run_record",
            confidence="medium",
            stale_risk="low",
            extractor_version="pretrip_planning_skill_audit.projection.v1",
            prompt_version="not_applicable_deterministic_skill_audit_projection.v1",
            summary=(
                "Planning SkillRunRecord for replayable pretrip evidence "
                "processing; no automatic Brain writeback and not runtime "
                "safety truth."
            ),
        ),
        "automatic_brain_write": writeback_policy.get("automatic_brain_write") is True,
        "creates_observed_fact": writeback_policy.get("creates_observed_fact") is True,
        "creates_model_interpretation": (
            writeback_policy.get("creates_model_interpretation") is True
        ),
    }


def _planning_skill_manifest_catalog_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    manifests = [
        manifest
        for manifest in payload.get("manifests", [])
        if isinstance(manifest, dict)
    ]
    automatic_brain_write_allowed_count = sum(
        1
        for manifest in manifests
        if (manifest.get("brain_writeback_policy") or {}).get(
            "automatic_brain_write_allowed"
        )
        is True
    )
    observed_fact_write_allowed_count = sum(
        1
        for manifest in manifests
        if (manifest.get("brain_writeback_policy") or {}).get(
            "observed_fact_write_allowed"
        )
        is True
    )
    phase1_runtime_mutation_allowed_count = sum(
        1
        for manifest in manifests
        if (manifest.get("runtime_mutation_policy") or {}).get(
            "phase1_runtime_mutation_allowed"
        )
        is True
    )
    live_safety_call_allowed_count = sum(
        1
        for manifest in manifests
        if (manifest.get("runtime_mutation_policy") or {}).get(
            "live_safety_endpoint_calls_allowed"
        )
        is True
    )
    return {
        "source_id": payload.get("catalog_id", "planning_skill_manifest_catalog"),
        "source_path": source_path,
        "evidence_type": "pretrip_planning_skill_manifest_catalog",
        "status": "candidate_skill_contracts",
        "project_id": payload.get("project_id"),
        "raw_payloads_embedded": payload.get("raw_payloads_embedded", False),
        "skill_config_manifest_ref": payload.get("skill_config_manifest_ref"),
        "counts": {
            "manifest_count": len(manifests),
            "automatic_brain_write_allowed_count": automatic_brain_write_allowed_count,
            "observed_fact_write_allowed_count": observed_fact_write_allowed_count,
            "phase1_runtime_mutation_allowed_count": phase1_runtime_mutation_allowed_count,
            "live_safety_endpoint_call_allowed_count": live_safety_call_allowed_count,
            "review_required_count": sum(
                1
                for manifest in manifests
                if (manifest.get("review_requirement") or {}).get("required") is True
            ),
            "candidate_outputs_only_count": sum(
                1
                for manifest in manifests
                if (manifest.get("review_requirement") or {}).get(
                    "candidate_outputs_only"
                )
                is True
            ),
        },
        "manifests": [
            _planning_skill_manifest_summary(manifest, source_path)
            for manifest in manifests
        ],
        "boundary": {
            "candidate_contracts_only": True,
            "raw_payloads_embedded": payload.get("raw_payloads_embedded", False),
            "automatic_brain_write_allowed": False,
            "observed_fact_write_allowed": False,
            "phase1_runtime_mutation_allowed": False,
            "live_safety_endpoint_calls_allowed": False,
            "runtime_safety_truth": False,
        },
    }


def _planning_skill_manifest_summary(
    manifest: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    input_refs = [
        item.get("ref")
        for item in manifest.get("allowed_input_refs", [])
        if isinstance(item, dict)
    ]
    output_refs = [
        item.get("ref")
        for item in manifest.get("allowed_output_refs", [])
        if isinstance(item, dict)
    ]
    return {
        **manifest,
        **_projection_record_metadata(
            {
                **manifest,
                "source_refs": input_refs + output_refs,
                "candidate_id": manifest.get("skill_id"),
            },
            source_path=source_path,
            evidence_type="pretrip_planning_skill_manifest",
            source_kind="planning_skill_manifest",
            identity_keys=("skill_id", "allowed_write_scope", "source_refs"),
            review_state=manifest.get("status", "candidate"),
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_planning_skill_manifest_catalog.projection.v1",
            prompt_version="not_applicable_deterministic_skill_manifest_projection.v1",
            summary=(
                "Planning skill manifest contract; candidate outputs require "
                "human review and no live safety endpoint or automatic Brain "
                "writeback is allowed."
            ),
        ),
    }


def _planning_sections(planning_tab: dict[str, Any]) -> list[dict[str, Any]]:
    route = planning_tab["route"]
    checkpoints = planning_tab["mission_candidates"]["checkpoints"]
    segments = planning_tab["mission_candidates"]["segments"]
    retreat_routes = planning_tab["mission_candidates"]["retreat_routes"]
    map_candidates = planning_tab["map_candidates"]
    eta = planning_tab["eta"]
    readiness = planning_tab["readiness"]
    resources = planning_tab["resources"]
    layer_preparation = planning_tab["layer_preparation"]
    risk_score = planning_tab["risk_score"]
    risk_ribbon = planning_tab["risk_ribbon"]
    risk_heatmap = planning_tab["risk_heatmap"]
    risk_delta = planning_tab["risk_delta"]
    weather = planning_tab["weather"]
    overpass_evidence = planning_tab["overpass_evidence"]
    gis_perception_timeline = planning_tab["gis_perception_timeline"]
    major_critical_points = planning_tab.get("major_critical_points")
    boss_points = planning_tab.get("boss_points")
    mileage_tag_alignment = planning_tab.get("mileage_tag_alignment")
    route_notes = planning_tab["route_notes"]
    reference_tracks = planning_tab.get("reference_tracks")
    reference_segment_timing = planning_tab.get("reference_segment_timing")
    checkpoint_events = planning_tab.get("checkpoint_events")
    route_note_ln_proposals = planning_tab["route_note_ln_proposals"]
    spatial_imprints = planning_tab.get("spatial_imprints")
    route_note_review_options = planning_tab["route_note_review_options"]
    route_note_reviewed_assumptions = planning_tab.get(
        "route_note_reviewed_assumptions"
    )
    review_queue = planning_tab["review_queue"]
    review_workbench = planning_tab["review_workbench"]
    review_draft_log = planning_tab["review_draft_log"]
    review_decision_log = planning_tab["review_decision_log"]
    review_decision_apply_plan = planning_tab["review_decision_apply_plan"]
    external_import_queue = planning_tab["external_import_queue"]
    expert_contributions = planning_tab["expert_contributions"]
    expert_contribution_apply_plan = planning_tab.get("expert_contribution_apply_plan")
    expert_contribution_workspace_apply_result = planning_tab.get(
        "expert_contribution_workspace_apply_result"
    )
    departure_reviewed_candidates = planning_tab.get("departure_reviewed_candidates")
    mcp_review_actions = planning_tab.get("mcp_review_actions")
    departure_bundle = planning_tab["departure_bundle"]

    sections = [
        _section(
            "route",
            "Route Evidence",
            route,
            counts={
                "point_count": route["point_count"],
                "sample_count": len(route.get("point_samples", [])),
                "polyline_point_count": len(route.get("polyline", [])),
            },
            summary={
                "route_name": route["route_name"],
                "distance_m": route["distance_m"],
                "bounds": route["bounds"],
                "started_at": route.get("started_at"),
                "ended_at": route.get("ended_at"),
            },
            boundary={
                "candidate_only": True,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
            },
        ),
        _section(
            "checkpoints",
            "Checkpoint Candidates",
            _candidate_collection_source(
                checkpoints,
                source_id="pretrip_checkpoint_candidates",
                evidence_type="pretrip_checkpoint_candidates",
            ),
            status="candidate_only",
            counts={
                "candidate_count": len(checkpoints),
                "compression_boundary_count": sum(
                    1 for checkpoint in checkpoints
                    if checkpoint.get("compression_boundary")
                ),
                "source_ref_count": len(
                    {
                        ref
                        for checkpoint in checkpoints
                        for ref in checkpoint.get("source_refs", [])
                    }
                ),
            },
            summary={
                "first_checkpoint_id": checkpoints[0]["candidate_id"] if checkpoints else None,
                "last_checkpoint_id": checkpoints[-1]["candidate_id"] if checkpoints else None,
                "sample_candidates": _candidate_section_previews(checkpoints),
            },
            boundary={
                "candidate_only": True,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
                "mission_graph_compile_allowed": False,
            },
        ),
        _section(
            "segments",
            "Segment Candidates",
            _candidate_collection_source(
                segments,
                source_id="pretrip_segment_candidates",
                evidence_type="pretrip_segment_candidates",
            ),
            status="candidate_only",
            counts={
                "candidate_count": len(segments),
                "resume_segment_count": sum(
                    1 for segment in segments
                    if segment.get("resume_segment")
                    or segment.get("display_geometry", {}).get("resume_segment")
                ),
                "source_ref_count": len(
                    {
                        ref
                        for segment in segments
                        for ref in segment.get("source_refs", [])
                    }
                ),
            },
            summary={
                "first_segment_id": segments[0]["candidate_id"] if segments else None,
                "last_segment_id": segments[-1]["candidate_id"] if segments else None,
                "sample_candidates": _candidate_section_previews(segments),
            },
            boundary={
                "candidate_only": True,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
                "mission_graph_compile_allowed": False,
            },
        ),
        _section(
            "map_candidates",
            "Map Candidates",
            map_candidates,
            status="candidate_only",
            counts=map_candidates["counts"],
            summary={
                "corridor_candidates": _candidate_section_previews(
                    map_candidates["corridor_candidates"]
                ),
                "hazard_candidates": _candidate_section_previews(
                    map_candidates["hazard_candidates"]
                ),
                "poi_candidates": _candidate_section_previews(
                    map_candidates["poi_candidates"]
                ),
            },
            boundary={
                "candidate_only": True,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
                "mission_graph_compile_allowed": False,
            },
        ),
        _section(
            "retreat_routes",
            "Retreat Routes",
            _candidate_collection_source(
                retreat_routes,
                source_id="pretrip_retreat_route_candidates",
                evidence_type="pretrip_retreat_route_candidates",
            ),
            status="candidate_only",
            counts={
                "candidate_count": len(retreat_routes),
                "source_ref_count": len(
                    {
                        ref
                        for retreat in retreat_routes
                        for ref in retreat.get("source_refs", [])
                    }
                ),
            },
            summary={
                "sample_candidates": _candidate_section_previews(retreat_routes),
            },
            boundary={
                "candidate_only": True,
                "runtime_safety_truth": False,
                "phase1_runtime_mutation_allowed": False,
                "mission_graph_compile_allowed": False,
            },
        ),
        _section(
            "eta",
            "ETA Plan",
            eta,
            counts={"estimate_count": eta["estimate_count"]},
            summary={
                "planned_start_time": eta["planned_start_time"],
                "target_eta": eta["target_eta"],
                "turn_back_checkpoint_eta": eta["turn_back_checkpoint_eta"],
            },
        ),
        _section(
            "readiness",
            "Readiness",
            readiness,
            status=readiness["status"],
            counts={"finding_count": len(readiness.get("findings") or [])},
            summary={"status": readiness["status"]},
        ),
        _section(
            "resources",
            "Resources",
            resources,
            status=resources["status"],
            counts={
                "device_count": resources["device_count"],
                "equipment_count": resources["equipment_count"],
                "team_member_count": resources["team_member_count"],
                "warning_candidate_count": len(
                    resources["departure_readiness_context"].get("warning_candidates", [])
                ),
            },
            summary={
                "departure_readiness_status": resources["departure_readiness_context"].get(
                    "status"
                ),
                "raw_payloads_embedded": resources["raw_payloads_embedded"],
                "external_api_calls_made": resources["external_api_calls_made"],
            },
        ),
        _section(
            "layer_preparation",
            "Layer Preparation",
            layer_preparation,
            status=layer_preparation["status"],
            counts=layer_preparation["counts"],
            summary={
                "profile": layer_preparation.get("profile"),
                "network_mode": layer_preparation["network_policy"].get(
                    "network_mode"
                ),
                "network_calls_made": layer_preparation["network_policy"].get(
                    "network_calls_made"
                ),
                "ready_layer_count": layer_preparation["counts"].get(
                    "ready_layer_count"
                ),
                "missing_layer_count": layer_preparation["counts"].get(
                    "missing_layer_count"
                ),
                "layers": [
                    {
                        "layer_id": layer["layer_id"],
                        "status": layer["status"],
                        "warning_count": layer.get("warning_count", 0),
                    }
                    for layer in layer_preparation.get("layers", [])
                ],
            },
            boundary=layer_preparation["boundary"],
        ),
        _section(
            "risk_score",
            "Risk Score",
            risk_score,
            status=risk_score["status"],
            counts=risk_score["counts"],
            summary={
                "score_field": risk_score["score_field"],
                "point_count": risk_score["counts"].get("point_count", 0),
                "route_sample_count": risk_score["counts"].get(
                    "route_sample_count",
                    0,
                ),
                "max_pretrip_risk": risk_score["counts"].get("max_pretrip_risk"),
                "risk_level_counts": risk_score["counts"].get(
                    "risk_level_counts",
                    {},
                ),
            },
            boundary=risk_score["boundary"],
        ),
        _section(
            "risk_ribbon",
            "Baseline Risk",
            risk_ribbon,
            status=risk_ribbon["status"],
            counts=risk_ribbon["counts"],
            summary={
                "score_field": risk_ribbon["score_field"],
                "score_surface_type": risk_ribbon["score_surface_type"],
                "segment_count": risk_ribbon["counts"].get("segment_count", 0),
                "source_sample_count": risk_ribbon["counts"].get(
                    "source_sample_count",
                    0,
                ),
                "max_pretrip_risk": risk_ribbon["counts"].get("max_pretrip_risk"),
                "risk_bucket_counts": risk_ribbon["counts"].get(
                    "risk_bucket_counts",
                    {},
                ),
            },
            boundary=risk_ribbon["boundary"],
        ),
        _section(
            "risk_heatmap",
            "Calibrated Heat",
            risk_heatmap,
            status=risk_heatmap["status"],
            counts=risk_heatmap["counts"],
            summary={
                "score_field": risk_heatmap["score_field"],
                "score_surface_type": risk_heatmap["score_surface_type"],
                "segment_count": risk_heatmap["counts"].get("segment_count", 0),
                "source_sample_count": risk_heatmap["counts"].get(
                    "source_sample_count",
                    0,
                ),
                "max_calibrated_risk": risk_heatmap["counts"].get(
                    "max_pretrip_risk"
                ),
                "risk_bucket_counts": risk_heatmap["counts"].get(
                    "risk_bucket_counts",
                    {},
                ),
            },
            boundary=risk_heatmap["boundary"],
        ),
        _section(
            "risk_delta",
            "Risk Delta",
            risk_delta,
            status=risk_delta["status"],
            counts=risk_delta["counts"],
            summary={
                "score_field": risk_delta["score_field"],
                "score_surface_type": risk_delta["score_surface_type"],
                "segment_count": risk_delta["counts"].get("segment_count", 0),
                "max_abs_delta": risk_delta["counts"].get("max_abs_delta"),
                "mean_abs_delta": risk_delta["counts"].get("mean_abs_delta"),
                "risk_bucket_counts": risk_delta["counts"].get(
                    "risk_bucket_counts",
                    {},
                ),
            },
            boundary=risk_delta["boundary"],
        ),
        _section(
            "weather",
            "Weather And Daylight",
            weather,
            status=weather["status"],
            counts={
                "hazard_note_count": len(weather["weather_window"].get("hazard_notes", [])),
                "source_ref_count": 2,
            },
            summary={
                "location_name": weather["location_name"],
                "date": weather["date"],
                "timezone": weather["timezone"],
                "weather_summary": weather["weather_window"].get("summary"),
                "daylight_source_status": weather["daylight"].get("source_status"),
                "external_api_calls_made": weather["external_api_calls_made"],
            },
        ),
        _section(
            "overpass_evidence",
            "Overpass Vector Evidence",
            overpass_evidence,
            status=overpass_evidence["status"],
            counts=overpass_evidence["counts"],
            summary={
                "candidate_count": overpass_evidence["counts"].get("candidates"),
                "skipped_object_count": overpass_evidence["counts"].get("skipped"),
                "raw_response_sha256": overpass_evidence["raw_response_sha256"],
                "conversion_rule_version": overpass_evidence[
                    "conversion_rule_version"
                ],
                "normalized_geojson_ref": overpass_evidence[
                    "normalized_geojson_ref"
                ],
                "endpoint": overpass_evidence["request"]["endpoint"],
                "live_network_required": overpass_evidence["boundary"].get(
                    "live_network_required"
                ),
            },
            boundary=overpass_evidence["boundary"],
        ),
        _section(
            "gis_perception_timeline",
            "GIS Perception CP Timeline",
            gis_perception_timeline,
            status=gis_perception_timeline["status"],
            counts=gis_perception_timeline["counts"],
            summary={
                "checkpoint_candidate_count": gis_perception_timeline[
                    "counts"
                ].get("checkpoint_candidate_count"),
                "raw_checkpoint_candidate_count": gis_perception_timeline[
                    "counts"
                ].get("raw_checkpoint_candidate_count"),
                "aggregation_radius_m": gis_perception_timeline[
                    "aggregation"
                ].get("radius_m"),
                "nearby_group_count": gis_perception_timeline["counts"].get(
                    "nearby_group_count"
                ),
                "nearby_group_radius_m": gis_perception_timeline[
                    "nearby_grouping"
                ].get("radius_m"),
                "nearby_groups": gis_perception_timeline["nearby_groups"][:12],
                "checkpoint_candidates": gis_perception_timeline[
                    "checkpoint_candidates"
                ][:12],
            },
            boundary=gis_perception_timeline["boundary"],
        ),
    ]
    if major_critical_points is not None:
        sections.append(
            _section(
                "major_critical_points",
                "Major Critical Points",
                major_critical_points,
                status=major_critical_points["status"],
                counts=major_critical_points["counts"],
                summary={
                    "mcp_candidate_count": major_critical_points["counts"].get(
                        "mcp_candidate_count",
                        0,
                    ),
                    "dense_checkpoint_count": major_critical_points["counts"].get(
                        "dense_checkpoint_count",
                        0,
                    ),
                    "suppressed_point_count": major_critical_points["counts"].get(
                        "suppressed_point_count",
                        0,
                    ),
                    "retrieval_query_count": major_critical_points["counts"].get(
                        "retrieval_query_count",
                        0,
                    ),
                    "ocr_label_count": major_critical_points["counts"].get(
                        "ocr_label_count",
                        0,
                    ),
                    "cp_support_supported_count": major_critical_points[
                        "counts"
                    ].get("cp_support_supported_count", 0),
                    "cp_support_suggested_insertion_count": major_critical_points[
                        "counts"
                    ].get("cp_support_suggested_insertion_count", 0),
                    "review_action_count": major_critical_points["counts"].get(
                        "review_action_count",
                        0,
                    ),
                    "candidates": major_critical_points["candidates"][:12],
                },
                boundary=major_critical_points["boundary"],
            )
        )
    if boss_points is not None:
        sections.append(
            _section(
                "boss_points",
                "Boss Points",
                boss_points,
                status=boss_points["status"],
                counts=boss_points["counts"],
                summary={
                    "decision": boss_points["challenge_fit_summary"].get(
                        "decision"
                    ),
                    "highest_challenge_fit_score": boss_points[
                        "challenge_fit_summary"
                    ].get("highest_challenge_fit_score"),
                    "highest_challenge_fit_label": boss_points[
                        "challenge_fit_summary"
                    ].get("highest_challenge_fit_label"),
                    "route_boss_demand_formula": boss_points["formula"].get(
                        "route_boss_demand"
                    ),
                    "challenge_fit_formula": boss_points["formula"].get(
                        "challenge_fit"
                    ),
                    "boss_points": boss_points["boss_points"][:12],
                },
                boundary=boss_points["boundary"],
            )
        )
    if mileage_tag_alignment is not None:
        sections.append(
            _section(
                "mileage_tag_alignment",
                "Mileage Tags",
                mileage_tag_alignment,
                status=mileage_tag_alignment["status"],
                counts=mileage_tag_alignment["counts"],
                summary={
                    "tag_count": mileage_tag_alignment["counts"].get("tag_count", 0),
                    "aligned_tag_count": mileage_tag_alignment["counts"].get(
                        "aligned_tag_count",
                        0,
                    ),
                    "usable_anchor_count": mileage_tag_alignment["counts"].get(
                        "usable_anchor_count",
                        0,
                    ),
                    "source_kind_counts": mileage_tag_alignment.get(
                        "source_kind_counts",
                        {},
                    ),
                    "raw_source_summary": mileage_tag_alignment.get(
                        "raw_source_summary",
                        {},
                    ),
                    "sample_labels": mileage_tag_alignment.get("sample_labels", [])[:12],
                },
                boundary=mileage_tag_alignment["boundary"],
            )
        )
    sections.extend(
        [
        _section(
            "route_notes",
            "Route Notes",
            route_notes,
            status=route_notes["status"],
            counts=route_notes["counts"],
            summary={
                "note_candidate_count": route_notes["counts"].get("note_candidate_count"),
                "hazard_hint_count": route_notes["counts"].get("hazard_hint_count"),
                "route_condition_hint_count": route_notes["counts"].get(
                    "route_condition_hint_count"
                ),
                "potential_ln_signal_count": route_notes["counts"].get(
                    "potential_ln_signal_count"
                ),
                "candidates": route_notes["candidates"][:12],
            },
            boundary=route_notes["boundary"],
        ),
        _section(
            "route_note_ln_proposals",
            "Route Note Ln Proposals",
            route_note_ln_proposals,
            status=route_note_ln_proposals["status"],
            counts=route_note_ln_proposals["counts"],
            summary={
                "proposal_count": route_note_ln_proposals["counts"].get(
                    "proposal_count"
                ),
                "hint_coverage_proposal_count": route_note_ln_proposals[
                    "counts"
                ].get("hint_coverage_proposal_count"),
                "warning_coverage_proposal_count": route_note_ln_proposals[
                    "counts"
                ].get("warning_coverage_proposal_count"),
                "proposals": route_note_ln_proposals["proposals"][:12],
            },
            boundary=route_note_ln_proposals["boundary"],
        ),
        ]
    )
    if spatial_imprints is not None:
        sections.append(
            _section(
                "spatial_imprints",
                "Spatial Imprints",
                spatial_imprints,
                status=spatial_imprints["status"],
                counts=spatial_imprints["counts"],
                summary={
                    "candidate_count": spatial_imprints["counts"].get(
                        "candidate_count",
                        0,
                    ),
                    "review_record_count": spatial_imprints["counts"].get(
                        "review_record_count",
                        0,
                    ),
                    "reviewed_imprint_count": spatial_imprints["counts"].get(
                        "reviewed_imprint_count",
                        0,
                    ),
                    "runtime_truth_count": spatial_imprints["counts"].get(
                        "runtime_truth_count",
                        0,
                    ),
                    "reviewed_imprints": spatial_imprints["reviewed_imprints"][:12],
                    "reviews": spatial_imprints["reviews"][:12],
                },
                boundary=spatial_imprints["boundary"],
            )
        )
    sections.extend(
        [
            _section(
            "route_note_review_options",
            "Route Note Review Options",
            route_note_review_options,
            status=route_note_review_options["status"],
            counts=route_note_review_options["counts"],
            summary={
                "review_option_count": route_note_review_options["counts"].get(
                    "review_option_count"
                ),
                "decision_recorded_count": route_note_review_options["counts"].get(
                    "decision_recorded_count"
                ),
                "allowed_admin_dispositions": [
                    "promote_hint",
                    "promote_warning",
                    "ignore",
                    "field_verify",
                ],
                "options": route_note_review_options["options"][:12],
            },
            boundary=route_note_review_options["boundary"],
            ),
        ]
    )
    if reference_tracks is not None:
        sections.append(
            _section(
                "reference_tracks",
                "Reference Tracks",
                reference_tracks,
                counts={"reference_track_count": reference_tracks["reference_track_count"]},
                summary={
                    "primary_route_name": reference_tracks["primary_route"].get("route_name"),
                    "runtime_safety_truth": reference_tracks["boundary"].get("runtime_safety_truth"),
                    "raw_gpx_copied_to_repo": reference_tracks["boundary"].get("raw_gpx_copied_to_repo"),
                },
                boundary=reference_tracks["boundary"],
            )
        )
    if reference_segment_timing is not None:
        sections.append(
            _section(
                "reference_segment_timing",
                "Reference Segment Timing",
                reference_segment_timing,
                status=reference_segment_timing["status"],
                counts=reference_segment_timing["counts"],
                summary={
                    "usable_segment_count": reference_segment_timing["counts"].get(
                        "usable_segment_count",
                        0,
                    ),
                    "measurement_count": reference_segment_timing["counts"].get(
                        "measurement_count",
                        0,
                    ),
                    "distance_rejected_measurement_count": reference_segment_timing[
                        "counts"
                    ].get("distance_rejected_measurement_count", 0),
                    "method": reference_segment_timing.get("method", {}),
                    "segments": [
                        {
                            "segment_id": segment.get("segment_id"),
                            "label": segment.get("label"),
                            "sample_count": segment.get("sample_count"),
                            "duration_minutes": segment.get("duration_minutes"),
                            "distance_filter_km": segment.get("distance_filter_km"),
                            "route_guide_comparison": segment.get(
                                "route_guide_comparison"
                            ),
                        }
                        for segment in reference_segment_timing.get("segments", [])[:12]
                    ],
                },
                boundary=reference_segment_timing["boundary"],
            )
        )
    if checkpoint_events is not None:
        sections.append(
            _section(
                "checkpoint_events",
                "Checkpoint Events",
                checkpoint_events,
                counts={"event_count": checkpoint_events["event_count"]},
                summary={
                    "source_point_count": checkpoint_events["source_gpx"].get("point_count"),
                    "trimming_performed": checkpoint_events["source_gpx"].get("trimming_performed"),
                    "sampling_performed": checkpoint_events["source_gpx"].get("sampling_performed"),
                },
                boundary=checkpoint_events["boundary"],
            )
        )
    if route_note_reviewed_assumptions is not None:
        sections.append(
            _section(
                "route_note_reviewed_assumptions",
                "Route Note Reviewed Assumptions",
                route_note_reviewed_assumptions,
                status=route_note_reviewed_assumptions["status"],
                counts=route_note_reviewed_assumptions["counts"],
                summary={
                    "accepted_interpretation_count": route_note_reviewed_assumptions[
                        "counts"
                    ].get("accepted_interpretation_count"),
                    "ln_expansion_candidate_count": route_note_reviewed_assumptions[
                        "counts"
                    ].get("ln_expansion_candidate_count"),
                    "field_verification_request_count": route_note_reviewed_assumptions[
                        "counts"
                    ].get("field_verification_request_count"),
                    "ignored_count": route_note_reviewed_assumptions["counts"].get(
                        "ignored_count"
                    ),
                },
                boundary=route_note_reviewed_assumptions["boundary"],
            )
        )
    sections.extend(
        [
        _section(
            "review_queue",
            "Review Queue",
            review_queue,
            status=review_queue["status"],
            counts=review_queue["counts"],
            summary={
                "category_counts": review_queue["counts"].get("category_counts", {}),
                "candidate_queue_only": review_queue["boundary"].get("candidate_queue_only"),
                "decisions_recorded": review_queue["boundary"].get("decisions_recorded"),
            },
            boundary=review_queue["boundary"],
        ),
        _section(
            "review_workbench",
            "Review Workbench",
            review_workbench,
            status=review_workbench["status"],
            counts=review_workbench["counts"],
            summary={
                "bulk_eligible_count": review_workbench["counts"].get(
                    "bulk_eligible_count"
                ),
                "single_review_required_count": review_workbench["counts"].get(
                    "single_review_required_count"
                ),
                "category_groups": review_workbench["category_groups"],
                "severity_groups": review_workbench["severity_groups"],
                "recommended_flow": review_workbench["triage"].get(
                    "recommended_flow",
                    [],
                ),
            },
            boundary=review_workbench["boundary"],
        ),
        _section(
            "review_draft_log",
            "Review Draft Log",
            review_draft_log,
            status=review_draft_log["status"],
            counts=review_draft_log["counts"],
            summary={
                "action_count": review_draft_log["counts"].get("action_count"),
                "category_counts": review_draft_log["category_counts"],
                "draft_only": review_draft_log["boundary"].get("draft_only"),
                "decisions_recorded": review_draft_log["boundary"].get(
                    "decisions_recorded"
                ),
                "mutation_action_count": review_draft_log["counts"].get(
                    "mutation_action_count"
                ),
                "actions": review_draft_log["actions"],
            },
            boundary=review_draft_log["boundary"],
        ),
        _section(
            "review_decision_log",
            "Review Decision Log",
            review_decision_log,
            status=review_decision_log["status"],
            counts=review_decision_log["counts"],
            summary={
                "action_count": review_decision_log["counts"].get("action_count"),
                "accepted_count": review_decision_log["counts"].get("accepted_count"),
                "corrected_count": review_decision_log["counts"].get("corrected_count"),
                "rejected_count": review_decision_log["counts"].get("rejected_count"),
                "runtime_mutation_count": review_decision_log["counts"].get(
                    "runtime_mutation_count"
                ),
                "package_mutation_count": review_decision_log["counts"].get(
                    "package_mutation_count"
                ),
                "decisions": review_decision_log["decisions"],
            },
            boundary=review_decision_log["boundary"],
        ),
        _section(
            "review_decision_apply_plan",
            "Review Decision Apply Plan",
            review_decision_apply_plan,
            status=review_decision_apply_plan["status"],
            counts=review_decision_apply_plan["counts"],
            summary={
                "plan_id": review_decision_apply_plan["plan_id"],
                "package_id": review_decision_apply_plan["package_id"],
                "package_status": review_decision_apply_plan["package_status"],
                "review_decision_log_ref": review_decision_apply_plan[
                    "review_decision_log_ref"
                ],
                "decision_count": review_decision_apply_plan["counts"].get(
                    "decision_count"
                ),
                "package_candidate_apply_count": review_decision_apply_plan[
                    "counts"
                ].get("package_candidate_apply_count"),
                "runtime_mutation_count": review_decision_apply_plan["counts"].get(
                    "runtime_mutation_count"
                ),
                "decisions": review_decision_apply_plan["decisions"],
            },
            boundary=review_decision_apply_plan["boundary"],
        ),
        _section(
            "external_import_queue",
            "External Import Queue",
            external_import_queue,
            status=external_import_queue["status"],
            counts=external_import_queue["counts"],
            summary={
                "request_count": external_import_queue["counts"].get("request_count"),
                "pending_count": external_import_queue["counts"].get("pending_count"),
                "network_call_count": external_import_queue["counts"].get(
                    "network_call_count"
                ),
                "crawler_enabled_count": external_import_queue["counts"].get(
                    "crawler_enabled_count"
                ),
                "source_ids": [
                    request["source_id"]
                    for request in external_import_queue.get("requests", [])
                ],
            },
            boundary=external_import_queue["boundary"],
        ),
        _section(
            "expert_contributions",
            "Expert Contributions",
            expert_contributions,
            status=expert_contributions["status"],
            counts=expert_contributions["counts"],
            summary={
                "contribution_count": expert_contributions["counts"].get(
                    "contribution_count"
                ),
                "candidate_set_edit_count": expert_contributions["counts"].get(
                    "candidate_set_edit_count"
                ),
                "external_import_edit_count": expert_contributions["counts"].get(
                    "external_import_edit_count"
                ),
                "memory_seed_candidate_count": expert_contributions["counts"].get(
                    "memory_seed_candidate_count"
                ),
                "brain_writeback_count": expert_contributions["counts"].get(
                    "brain_writeback_count"
                ),
                "records": expert_contributions["records"],
            },
            boundary=expert_contributions["boundary"],
        ),
        ]
    )
    if expert_contribution_apply_plan is not None:
        sections.append(
            _section(
                "expert_contribution_apply_plan",
                "Expert Contribution Apply Plan",
                expert_contribution_apply_plan,
                status=expert_contribution_apply_plan["status"],
                counts=expert_contribution_apply_plan["counts"],
                summary={
                    "planned_operation_count": expert_contribution_apply_plan[
                        "counts"
                    ].get("planned_operation_count"),
                    "candidate_set_operation_count": expert_contribution_apply_plan[
                        "counts"
                    ].get("candidate_set_operation_count"),
                    "external_import_operation_count": expert_contribution_apply_plan[
                        "counts"
                    ].get("external_import_operation_count"),
                },
                boundary=expert_contribution_apply_plan["boundary"],
            )
        )
    if expert_contribution_workspace_apply_result is not None:
        sections.append(
            _section(
                "expert_contribution_workspace_apply_result",
                "Expert Contribution Workspace Apply Result",
                expert_contribution_workspace_apply_result,
                status=expert_contribution_workspace_apply_result["status"],
                counts=expert_contribution_workspace_apply_result["counts"],
                summary={
                    "applied_operation_count": (
                        expert_contribution_workspace_apply_result["counts"].get(
                            "applied_operation_count"
                        )
                    ),
                    "checkpoint_candidate_append_count": (
                        expert_contribution_workspace_apply_result["counts"].get(
                            "checkpoint_candidate_append_count"
                        )
                    ),
                    "retreat_route_update_count": (
                        expert_contribution_workspace_apply_result["counts"].get(
                            "retreat_route_update_count"
                        )
                    ),
                    "external_import_request_append_count": (
                        expert_contribution_workspace_apply_result["counts"].get(
                            "external_import_request_append_count"
                        )
                    ),
                },
                boundary=expert_contribution_workspace_apply_result["boundary"],
            )
        )
    if departure_reviewed_candidates is not None:
        sections.append(
            _section(
                "departure_reviewed_candidates",
                "Departure Reviewed Candidates",
                departure_reviewed_candidates,
                status=departure_reviewed_candidates["status"],
                counts=departure_reviewed_candidates["counts"],
                summary={
                    "source_apply_plan_ref": departure_reviewed_candidates[
                        "source_apply_plan_ref"
                    ],
                    "promoted_candidate_count": departure_reviewed_candidates[
                        "counts"
                    ].get("promoted_candidate_count"),
                    "accepted_count": departure_reviewed_candidates["counts"].get(
                        "accepted_count"
                    ),
                    "corrected_count": departure_reviewed_candidates["counts"].get(
                        "corrected_count"
                    ),
                    "runtime_truth_count": departure_reviewed_candidates["counts"].get(
                        "runtime_truth_count"
                    ),
                    "candidates": departure_reviewed_candidates["candidates"],
                },
                boundary=departure_reviewed_candidates["boundary"],
            )
        )
    if mcp_review_actions is not None:
        sections.append(
            _section(
                "mcp_review_actions",
                "MCP Review Actions",
                mcp_review_actions,
                status=mcp_review_actions["status"],
                counts=mcp_review_actions["counts"],
                summary={
                    "action_count": mcp_review_actions["counts"].get(
                        "action_count",
                        0,
                    ),
                    "source_candidate_set_ref": mcp_review_actions.get(
                        "source_candidate_set_ref"
                    ),
                    "actions": mcp_review_actions["actions"][:12],
                },
                boundary=mcp_review_actions["boundary"],
            )
        )
    sections.append(
        _section(
            "departure_bundle",
            "Departure Bundle",
            departure_bundle,
            status=departure_bundle["status"],
            counts=departure_bundle["counts"],
            summary={
                "package_id": departure_bundle["package"].get("package_id"),
                "route_ref_count": len(departure_bundle.get("route_refs", [])),
                "terrain_ref_count": len(departure_bundle.get("terrain_refs", [])),
            },
            boundary=departure_bundle["boundary"],
        )
    )
    return sections


def _post_analysis_sections(post_analysis_tab: dict[str, Any]) -> list[dict[str, Any]]:
    runtime_handoff = post_analysis_tab["runtime_handoff"]
    route_comparison = post_analysis_tab["route_comparison"]
    brain_seed = post_analysis_tab["brain_seed"]
    after_action = post_analysis_tab["after_action_next_plan"]
    capability_timeline_import = post_analysis_tab.get("capability_timeline_import")
    companion_match_review = post_analysis_tab.get("companion_match_review")
    post_analysis_energy_feedback = post_analysis_tab.get(
        "post_analysis_energy_feedback"
    )
    import_manifest = post_analysis_tab.get("import_manifest")
    admin_surface_projection = post_analysis_tab.get("admin_surface_projection")
    debug_projection = post_analysis_tab.get("debug_projection")
    planning_skill_audit = post_analysis_tab.get("planning_skill_audit")
    planning_skill_manifest_catalog = post_analysis_tab.get(
        "planning_skill_manifest_catalog"
    )

    sections = [
        _section(
            "runtime_handoff",
            "Runtime Handoff",
            runtime_handoff,
            status=runtime_handoff["status"],
            counts=runtime_handoff["counts"],
            summary={
                "candidate_metadata_only": runtime_handoff["boundary"].get(
                    "candidate_metadata_only"
                ),
                "phase1_runtime_mutation_allowed": runtime_handoff["boundary"].get(
                    "phase1_runtime_mutation_allowed"
                ),
                "phase2_writeback_allowed": runtime_handoff["boundary"].get(
                    "phase2_writeback_allowed"
                ),
            },
            boundary=runtime_handoff["boundary"],
        ),
        _section(
            "route_comparison",
            "Route Comparison",
            route_comparison,
            status=route_comparison["classification"],
            counts={
                "distance_delta_m": route_comparison["distance_delta_m"],
                "point_count_delta": route_comparison["point_count_delta"],
                "bbox_overlap_count": int(
                    bool(route_comparison["bbox_comparison"].get("overlaps"))
                ),
            },
            summary={
                "classification": route_comparison["classification"],
                "primary_overlap_ratio": route_comparison["bbox_comparison"].get(
                    "primary_overlap_ratio"
                ),
                "comparison_overlap_ratio": route_comparison["bbox_comparison"].get(
                    "comparison_overlap_ratio"
                ),
            },
        ),
        _section(
            "brain_seed",
            "Brain Seed",
            brain_seed,
            counts={
                "node_count": brain_seed["node_count"],
                "artifact_count": brain_seed["artifact_count"],
                "derived_measurement_count": brain_seed["derived_measurement_count"],
                "human_review_count": brain_seed["human_review_count"],
                "model_interpretation_count": brain_seed["model_interpretation_count"],
                "observed_fact_count": brain_seed["observed_fact_count"],
            },
            summary={
                "observed_fact_count": brain_seed["observed_fact_count"],
                "non_review_gated_model_interpretation_count": brain_seed[
                    "non_review_gated_model_interpretation_count"
                ],
                "node_types": brain_seed["node_types"],
                "model_interpretations": brain_seed["model_interpretations"][:12],
            },
            boundary=brain_seed["boundary"],
        ),
        _section(
            "after_action_next_plan",
            "After-Action Next Plan",
            after_action,
            status=after_action["status"],
            counts=after_action["counts"],
            summary={
                "raw_payloads_embedded": after_action["raw_payloads_embedded"],
                "observed_fact_writeback_allowed": after_action[
                    "observed_fact_writeback_allowed"
                ],
                "historical_evidence_mutation_allowed": after_action[
                    "historical_evidence_mutation_allowed"
                ],
            },
        ),
    ]
    if planning_skill_audit is not None:
        sections.append(
            _section(
                "planning_skill_audit",
                "Planning Skill Audit",
                planning_skill_audit,
                status=planning_skill_audit["status"],
                counts=planning_skill_audit["counts"],
                summary={
                    "node_types": planning_skill_audit["node_types"],
                    "record_count": planning_skill_audit["counts"].get(
                        "record_count",
                        0,
                    ),
                    "automatic_brain_write_count": planning_skill_audit[
                        "counts"
                    ].get("automatic_brain_write_count", 0),
                    "observed_fact_count": planning_skill_audit["counts"].get(
                        "observed_fact_count",
                        0,
                    ),
                    "records": planning_skill_audit["records"][:12],
                },
                boundary=planning_skill_audit["boundary"],
            )
        )
    if planning_skill_manifest_catalog is not None:
        sections.append(
            _section(
                "planning_skill_manifest_catalog",
                "Planning Skill Manifest Catalog",
                planning_skill_manifest_catalog,
                status=planning_skill_manifest_catalog["status"],
                counts=planning_skill_manifest_catalog["counts"],
                summary={
                    "manifest_count": planning_skill_manifest_catalog[
                        "counts"
                    ].get("manifest_count", 0),
                    "automatic_brain_write_allowed_count": (
                        planning_skill_manifest_catalog["counts"].get(
                            "automatic_brain_write_allowed_count",
                            0,
                        )
                    ),
                    "phase1_runtime_mutation_allowed_count": (
                        planning_skill_manifest_catalog["counts"].get(
                            "phase1_runtime_mutation_allowed_count",
                            0,
                        )
                    ),
                    "manifests": planning_skill_manifest_catalog["manifests"][:12],
                },
                boundary=planning_skill_manifest_catalog["boundary"],
            )
        )
    if capability_timeline_import is not None:
        sections.append(
            _section(
                "capability_timeline_import",
                "Capability Timeline Import",
                capability_timeline_import,
                status=capability_timeline_import["status"],
                counts=capability_timeline_import["counts"],
                summary={
                    "moving_time_s": capability_timeline_import["summary"].get(
                        "moving_time_s"
                    ),
                    "elapsed_time_s": capability_timeline_import["summary"].get(
                        "elapsed_time_s"
                    ),
                    "rest_time_s": capability_timeline_import["summary"].get(
                        "rest_time_s"
                    ),
                    "distance_m": capability_timeline_import["summary"].get(
                        "distance_m"
                    ),
                    "source_scope": capability_timeline_import["privacy"].get(
                        "source_scope"
                    ),
                    "raw_track_shared": capability_timeline_import["privacy"].get(
                        "raw_track_shared"
                    ),
                    "auto_applies_to_eta": capability_timeline_import[
                        "planning_use"
                    ].get("auto_applies_to_eta"),
                    "edges": capability_timeline_import.get("edges", [])[:12],
                },
                boundary=capability_timeline_import["boundary"],
            )
        )
    if companion_match_review is not None:
        sections.append(
            _section(
                "companion_match_review",
                "Companion Match Review",
                companion_match_review,
                status=companion_match_review["status"],
                counts=companion_match_review["counts"],
                summary={
                    "top_candidate_profile_ref": companion_match_review[
                        "summary"
                    ].get("top_candidate_profile_ref"),
                    "top_match_score": companion_match_review["summary"].get(
                        "top_match_score"
                    ),
                    "top_match_band": companion_match_review["summary"].get(
                        "top_match_band"
                    ),
                    "recommended_review_refs": companion_match_review[
                        "summary"
                    ].get("recommended_review_refs", []),
                    "raw_health_payload_shared": companion_match_review[
                        "summary"
                    ].get("raw_health_payload_shared"),
                    "auto_applies_to_eta": companion_match_review["summary"].get(
                        "auto_applies_to_eta"
                    ),
                },
                boundary=companion_match_review["boundary"],
            )
        )
    if post_analysis_energy_feedback is not None:
        sections.append(
            _section(
                "post_analysis_energy_feedback",
                "Energy Feedback",
                post_analysis_energy_feedback,
                status=post_analysis_energy_feedback["status"],
                counts=post_analysis_energy_feedback["counts"],
                summary={
                    "predicted_target_duration_minutes": post_analysis_energy_feedback[
                        "summary"
                    ].get("predicted_target_duration_minutes"),
                    "actual_elapsed_duration_minutes": post_analysis_energy_feedback[
                        "summary"
                    ].get("actual_elapsed_duration_minutes"),
                    "actual_vs_projected_elapsed_delta_minutes": post_analysis_energy_feedback[
                        "summary"
                    ].get("actual_vs_projected_elapsed_delta_minutes"),
                    "predicted_depletion_checkpoint_name": post_analysis_energy_feedback[
                        "summary"
                    ].get("predicted_depletion_checkpoint_name"),
                    "raw_track_shared": post_analysis_energy_feedback[
                        "summary"
                    ].get("raw_track_shared"),
                    "auto_applies_to_eta": post_analysis_energy_feedback[
                        "summary"
                    ].get("auto_applies_to_eta"),
                },
                boundary=post_analysis_energy_feedback["boundary"],
            )
        )
    if import_manifest is not None:
        sections.append(
            _section(
                "import_manifest",
                "Import Manifest",
                import_manifest,
                status=import_manifest["profile"],
                counts=import_manifest["counts"],
                summary={
                    "source_file_count": import_manifest["counts"].get(
                        "source_file_count"
                    ),
                    "reference_track_count": import_manifest["counts"].get(
                        "reference_track_count"
                    ),
                    "network_calls_allowed": import_manifest["network_policy"].get(
                        "network_calls_allowed"
                    ),
                },
                boundary=import_manifest["boundary"],
            )
        )
    if admin_surface_projection is not None:
        sections.append(
            _section(
                "admin_surface_projection",
                "Admin Surface Projection",
                admin_surface_projection,
                counts=admin_surface_projection["candidate_counts"],
                summary={
                    "surface_targets": admin_surface_projection["surface_targets"],
                    "projection_only": admin_surface_projection["projection_only"],
                    "completed_mission_replay": admin_surface_projection[
                        "after_action_surface"
                    ].get("completed_mission_replay"),
                    "debug_projection_events_ref": admin_surface_projection[
                        "debug_surface"
                    ].get("debug_projection_events_ref"),
                },
                boundary=admin_surface_projection["boundary"],
            )
        )
    if debug_projection is not None:
        sections.append(
            _section(
                "debug_projection",
                "Debug Projection",
                debug_projection,
                counts={"event_count": debug_projection["event_count"]},
                summary={
                    "event_kinds": debug_projection["event_kinds"],
                    "file_runtime_debug_log_compatible": debug_projection[
                        "file_runtime_debug_log_compatible"
                    ],
                    "latest_summary": debug_projection["latest_summary"],
                },
                boundary=debug_projection["boundary"],
            )
        )
    return sections


def _agent_skills_tab(
    scout_agent_skills: dict[str, Any],
    evidence_timeline: dict[str, Any],
) -> dict[str, Any]:
    skill_source = {
        "source_id": "pretrip.scout_agent_skills",
        "source_path": scout_agent_skills["source_path"],
        "evidence_type": "pretrip_scout_agent_skill_registry_summary",
    }
    timeline_source = {
        "source_id": "pretrip.cross_surface_evidence_timeline",
        "source_path": "view.evidence_timeline",
        "evidence_type": "pretrip_cross_surface_evidence_timeline",
    }
    return {
        "source_id": skill_source["source_id"],
        "source_path": skill_source["source_path"],
        "evidence_type": skill_source["evidence_type"],
        "status": "read_only_registry_projection",
        "scout_agent_skills": scout_agent_skills,
        "evidence_timeline": evidence_timeline,
        "sections": [
            _section(
                "scout_agent_skills",
                "Scout Agent Skills",
                skill_source,
                status="read_only_registry_projection",
                counts=scout_agent_skills["counts"],
                summary={
                    "tool_count": scout_agent_skills["counts"].get("tool_count", 0),
                    "mode_counts": scout_agent_skills["counts"].get("mode_counts", {}),
                    "authorization_counts": scout_agent_skills["counts"].get(
                        "authorization_counts",
                        {},
                    ),
                    "write_capable_count": scout_agent_skills["counts"].get(
                        "write_capable_count",
                        0,
                    ),
                },
                boundary=scout_agent_skills["boundary"],
            ),
            _section(
                "evidence_timeline",
                "Evidence Timeline Alignment",
                timeline_source,
                status="projection_only",
                counts=evidence_timeline["counts"],
                summary={
                    "surface": evidence_timeline["surface"],
                    "category_order": evidence_timeline["category_order"],
                    "available_categories": [
                        item["category_id"]
                        for item in evidence_timeline["categories"]
                        if item["available"]
                    ],
                },
                boundary=evidence_timeline["boundary"],
            ),
        ],
    }


def _section(
    section_id: str,
    title: str,
    source: dict[str, Any],
    *,
    counts: dict[str, Any],
    summary: dict[str, Any],
    status: str | None = None,
    boundary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section = {
        "id": section_id,
        "title": title,
        "source_id": source["source_id"],
        "source_path": source["source_path"],
        "evidence_type": source["evidence_type"],
        **_projection_record_metadata(
            {
                "section_id": section_id,
                "source_id": source["source_id"],
                "source_path": source["source_path"],
                "evidence_type": source["evidence_type"],
            },
            source_path=source["source_path"],
            evidence_type="pretrip_admin_section_projection",
            source_kind="admin_section_projection",
            identity_keys=("section_id", "source_id", "source_path"),
            review_state="projection_only",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_admin_section.projection.v1",
            prompt_version="not_applicable_deterministic_admin_section_projection.v1",
            summary=(
                "Admin section summary for navigating pretrip evidence; "
                "projection-only UI metadata, not runtime safety truth."
            ),
        ),
        "counts": counts,
        "summary": summary,
    }
    if status is not None:
        section["status"] = status
    if boundary is not None:
        section["boundary"] = _summary_boundary(boundary)
    return section


def _candidate_collection_source(
    candidates: list[dict[str, Any]],
    *,
    source_id: str,
    evidence_type: str,
) -> dict[str, Any]:
    source_paths = _unique_limited(
        candidate.get("source_path")
        for candidate in candidates
        if candidate.get("source_path")
    )
    return {
        "source_id": source_id,
        "source_path": source_paths[0] if source_paths else source_id,
        "evidence_type": evidence_type,
    }


def _candidate_section_previews(
    candidates: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for candidate in candidates[:limit]:
        previews.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "label": candidate.get("label") or candidate.get("name"),
                "candidate_type": (
                    candidate.get("candidate_type")
                    or candidate.get("type")
                    or candidate.get("feature_type")
                ),
                "review_state": candidate.get("review_state"),
                "confidence": candidate.get("confidence"),
                "stale_risk": candidate.get("stale_risk"),
                "source_ref_count": len(candidate.get("source_refs", [])),
            }
        )
    return previews


def _summary_boundary(boundary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in boundary.items()
        if isinstance(value, bool) or key.endswith("_allowed")
    }


def _import_manifest_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": f"import_manifest.{payload['project_id']}",
        "source_path": source_path,
        "evidence_type": "pretrip_import_manifest",
        "profile": payload["profile"],
        "counts": payload["counts"],
        "network_policy": payload["network_policy"],
        "outputs": payload["outputs"],
        "boundary": payload["boundary"],
    }


def _admin_projection_summary(
    payload: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    summary = {
        "source_id": f"admin_surface_projection.{payload['project_id']}",
        "source_path": source_path,
        "evidence_type": "pretrip_admin_surface_projection",
        "artifact_kind": payload["artifact_kind"],
        "surface_targets": payload["surface_targets"],
        "projection_only": payload["projection_only"],
        "route": payload["route"],
        "candidate_counts": payload["candidate_counts"],
        "pretrip_surface": payload["pretrip_surface"],
        "after_action_surface": payload["after_action_surface"],
        "debug_surface": payload["debug_surface"],
        "boundary": payload["boundary"],
    }
    for key in (
        "route_notes",
        "route_note_ln_proposals",
        "route_note_review_options",
        "gis_perception",
        "major_critical_points",
        "departure_bundle",
        "runtime_handoff",
    ):
        if key in payload:
            if key == "major_critical_points":
                summary[key] = _decorate_embedded_admin_mcp_projection(
                    payload[key],
                    source_path=source_path,
                )
            else:
                summary[key] = (
                    dict(payload[key]) if isinstance(payload[key], dict) else payload[key]
                )
            if isinstance(summary[key], dict):
                _ensure_admin_summary_metadata(summary[key])
    _ensure_admin_summary_metadata(summary)
    return summary


def _decorate_embedded_admin_mcp_projection(
    mcp: dict[str, Any],
    *,
    source_path: str,
) -> dict[str, Any]:
    projected = dict(mcp)
    if isinstance(projected.get("preview_candidates"), list):
        projected["preview_candidates"] = [
            {
                **candidate,
                **_mcp_nested_support_projection(
                    candidate,
                    source_path=source_path,
                    evidence_type="pretrip_admin_surface_mcp_preview_candidate",
                    source_kind="admin_surface_mcp_preview_candidate",
                    review_state=candidate.get(
                        "review_state",
                        "needs_human_review",
                    ),
                ),
                **_mcp_projection_provenance(
                    candidate,
                    source_path=source_path,
                    evidence_type="pretrip_admin_surface_mcp_preview_candidate",
                    source_kind="admin_surface_mcp_preview_candidate",
                    identity_keys=("mcp_id", "candidate_id", "label"),
                    confidence=candidate.get("confidence", "medium"),
                    stale_risk=candidate.get("stale_risk", "medium"),
                    review_state=candidate.get(
                        "review_state",
                        "needs_human_review",
                    ),
                    model_output_summary=(
                        "Embedded admin-surface MCP preview candidate; "
                        "planning projection only, not runtime safety truth."
                    ),
                ),
            }
            for candidate in projected.get("preview_candidates", [])
        ]
    cp_support = projected.get("cp_support_reconciliation")
    if isinstance(cp_support, dict) and isinstance(cp_support.get("rows"), list):
        projected["cp_support_reconciliation"] = {
            **cp_support,
            "rows": [
                {
                    **row,
                    **_mcp_nested_support_projection(
                        row,
                        source_path=source_path,
                        evidence_type="pretrip_admin_surface_mcp_cp_support_row",
                        source_kind="admin_surface_mcp_cp_support",
                        review_state=row.get("review_state", "needs_human_review"),
                    ),
                    **_mcp_projection_provenance(
                        row,
                        source_path=source_path,
                        evidence_type="pretrip_admin_surface_mcp_cp_support_row",
                        source_kind="admin_surface_mcp_cp_support",
                        identity_keys=(
                            "mcp_id",
                            "label",
                            "support_status",
                            "recommendation",
                        ),
                        confidence=row.get("confidence", "medium"),
                        stale_risk=row.get("stale_risk", "medium"),
                        review_state=row.get("review_state", "needs_human_review"),
                        model_output_summary=(
                            "Embedded admin-surface MCP CP-support row; "
                            "planning projection only, not runtime safety truth."
                        ),
                    ),
                }
                for row in cp_support.get("rows", [])
            ],
        }
    ocr = projected.get("ocr")
    if isinstance(ocr, dict) and isinstance(ocr.get("labels"), list):
        projected["ocr"] = {
            **ocr,
            "labels": [
                {
                    **label,
                    **_mcp_projection_provenance(
                        label,
                        source_path=source_path,
                        evidence_type="pretrip_admin_surface_mcp_ocr_label",
                        source_kind="admin_surface_mcp_ocr_label",
                        identity_keys=(
                            "ocr_label_id",
                            "named_point_id",
                            "source_ref",
                            "source_image_hash",
                        ),
                        confidence=label.get("confidence", "medium"),
                        stale_risk=label.get("stale_risk", "medium"),
                        review_state=label.get("review_state", "needs_review"),
                        model_output_summary=(
                            "Embedded admin-surface MCP OCR label; planning "
                            "projection only, not runtime safety truth."
                        ),
                    ),
                }
                for label in ocr.get("labels", [])
            ],
        }
    return projected


def _debug_projection_events_summary(
    events: list[dict[str, Any]],
    source_path: str,
) -> dict[str, Any]:
    latest = events[-1] if events else {}
    return {
        "source_id": "debug_projection_events",
        "source_path": source_path,
        "evidence_type": "pretrip_debug_projection_events",
        "event_count": len(events),
        "event_kinds": [event.get("kind") for event in events],
        "latest_summary": latest.get("summary"),
        "file_runtime_debug_log_compatible": True,
        "events": events,
        "boundary": _debug_projection_boundary(events),
    }


def _debug_projection_boundary(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in events:
        payload = event.get("payload") or {}
        boundary = payload.get("boundary")
        if isinstance(boundary, dict):
            return boundary
    return {
        "projection_only": True,
        "phase1_runtime_mutation_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "mission_graph_compiled": False,
    }


def _raw_sample_summary(
    pretrip_package: dict[str, Any],
    segment_dtm: dict[str, Any],
    source_refs: dict[str, str],
) -> dict[str, Any]:
    source_path = source_refs["package"]
    return {
        "source_id": pretrip_package["package_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_raw_sample_summary",
        **_projection_record_metadata(
            {
                "candidate_id": pretrip_package["package_id"],
                "source_refs": [
                    source_path,
                    source_refs.get("segment_dtm"),
                    *[
                        artifact.get("artifact_id")
                        for artifact in pretrip_package.get("source_artifacts", [])
                    ],
                ],
            },
            source_path=source_path,
            evidence_type="pretrip_raw_sample_summary",
            source_kind="pretrip_package_source_artifact_summary",
            identity_keys=("candidate_id", "source_refs"),
            review_state="summary_only",
            confidence="medium",
            stale_risk="medium",
            extractor_version="pretrip_raw_sample_summary.projection.v1",
            prompt_version="not_applicable_deterministic_raw_sample_summary.v1",
            summary=(
                "Raw input sample summary records source artifact references "
                "without embedding raw GPX, photo, DTM, or runtime safety truth."
            ),
        ),
        "raw_payloads_embedded": False,
        "raw_gpx_read": False,
        "raw_photo_read": False,
        "raw_dtm_read": False,
        "source_artifacts": [
            {
                "artifact_id": artifact["artifact_id"],
                "kind": artifact["kind"],
                "uri": artifact["uri"],
                "media_type": artifact.get("media_type"),
                "sha256": artifact.get("sha256"),
                "size_bytes": artifact.get("size_bytes"),
            }
            for artifact in pretrip_package.get("source_artifacts", [])
        ],
        "terrain_metadata": {
            "candidate_tile_count": segment_dtm["candidate_tile_count"],
            "segment_count": segment_dtm["segment_count"],
            "notes": segment_dtm["notes"],
        },
    }


def _source_refs(artifacts: dict[str, Path], root: Path) -> dict[str, str]:
    return {key: _relpath(path, root) for key, path in artifacts.items()}


def _map_layers_with_local_raster_metadata(
    map_layers: list[dict[str, Any]],
    *,
    project: dict[str, Any] | None = None,
    local_raster_manifest: dict[str, Any] | None,
    raster_tile_manifest: dict[str, Any] | None,
    raster_layer_manifests: dict[str, dict[str, Any]] | None = None,
    local_raster_source_path: str,
    raster_tile_source_path: str,
) -> list[dict[str, Any]]:
    del local_raster_manifest, raster_tile_manifest
    del raster_layer_manifests, local_raster_source_path, raster_tile_source_path
    project_payload = project or {}
    imagery_bbox = _normalize_bbox_wgs84(project_payload.get("imagery_bbox_wgs84"))
    wmts_layer_ids = {
        "imagery",
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
    }
    enriched_layers: list[dict[str, Any]] = []
    for layer in map_layers:
        if layer.get("layer_id") not in wmts_layer_ids:
            enriched_layers.append(_map_layer_metadata(layer))
            continue
        enriched = dict(layer)
        if imagery_bbox and layer.get("layer_id") == "imagery":
            enriched["imagery_bbox_wgs84"] = imagery_bbox
            enriched["imagery_bbox_policy"] = project_payload.get(
                "imagery_bbox_policy",
                "route_visible_bounds_wmts_runtime",
            )
            enriched["imagery_bbox_scale_factor"] = project_payload.get(
                "imagery_bbox_scale_factor",
                1.15,
            )
        enriched["raster_tile_delivery"] = "direct_wmts_runtime"
        enriched["raster_coverage_policy"] = "render_visible_wmts_tiles_only"
        for key in (
            "imagery_source_id",
            "imagery_source_registry_id",
        ):
            if layer.get("layer_id") == "imagery" and project_payload.get(key):
                enriched[key] = project_payload[key]
        enriched_layers.append(_map_layer_metadata(enriched))
    return enriched_layers


def _raster_layer_manifest_summaries(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    refs = project.get("raster_layer_manifest_refs")
    if not isinstance(refs, dict):
        return {}
    summaries: dict[str, dict[str, Any]] = {}
    for layer_id, ref in refs.items():
        if not isinstance(layer_id, str) or not isinstance(ref, str):
            continue
        manifest_path = _project_ref_value_path(project_root, ref)
        manifest = _load_optional_json(manifest_path)
        if not isinstance(manifest, dict):
            continue
        summary: dict[str, Any] = {
            "layer_id": layer_id,
            "raster_tile_manifest_ref": ref,
            "local_raster_tile_url_template": (
                manifest.get("runtime_tile_url_template")
                or "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
            ),
        }
        for source_key, target_key in (
            ("bbox_wgs84", "raster_bbox_wgs84"),
            ("zoom_range", "raster_tile_zoom_range"),
            ("min_zoom", "raster_tile_min_zoom"),
            ("max_zoom", "raster_tile_max_zoom"),
            ("cache_root", "raster_tile_cache_root"),
            ("total_tile_count", "raster_tile_count"),
            ("source_id", "imagery_source_id"),
            ("source_kind", "imagery_source_kind"),
        ):
            if source_key in manifest:
                summary[target_key] = manifest[source_key]
        summaries[layer_id] = summary
    return summaries


def _project_ref_value_path(project_root: Path, ref: str) -> Path | None:
    if not ref or "\x00" in ref:
        return None
    path = Path(ref)
    if path.is_absolute() or ".." in path.parts:
        return None
    return project_root / path


def _map_layer_metadata(layer: dict[str, Any]) -> dict[str, Any]:
    source_path = str(layer.get("source_path") or "project.json#map-layers")
    source_refs = _unique_limited(
        [
            source_path,
            layer.get("source_id"),
            layer.get("layer_id"),
            layer.get("data_layer_group"),
            layer.get("local_raster_manifest_ref"),
            layer.get("raster_tile_manifest_ref"),
            layer.get("tile_url_template"),
            layer.get("local_proxy_tile_url_template"),
            layer.get("local_raster_tile_url_template"),
            layer.get("overlay_endpoint_template"),
        ],
        limit=24,
    )
    return {
        **layer,
        "evidence_type": "pretrip_admin_map_layer",
        **_projection_record_metadata(
            {
                **layer,
                "source_refs": source_refs,
                "candidate_id": layer.get("layer_id"),
            },
            source_path=source_path,
            evidence_type="pretrip_admin_map_layer",
            source_kind=str(layer.get("source_kind") or "admin_map_layer"),
            identity_keys=(
                "layer_id",
                "data_layer_group",
                "source_id",
                "source_refs",
            ),
            review_state="reference_only",
            confidence="medium" if layer.get("available", True) else "low",
            stale_risk="medium",
            extractor_version="pretrip_admin_map_layer_projection.v1",
            prompt_version="not_applicable_deterministic_map_layer_projection.v1",
            summary=(
                "Admin map layer descriptor for pretrip evidence rendering; "
                "layer metadata only, not runtime safety truth."
            ),
        ),
    }


def _normalize_bbox_wgs84(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        west = float(value["west"])
        south = float(value["south"])
        east = float(value["east"])
        north = float(value["north"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (west <= east and south <= north):
        return None
    return {"west": west, "south": south, "east": east, "north": north}


def _energy_projection_summary(
    projection: dict[str, Any],
    source_path: str,
) -> dict[str, Any]:
    return {
        "source_id": projection.get("artifact_kind", "pretrip_energy_reserve_projection"),
        "source_path": source_path,
        "evidence_type": "pretrip_energy_reserve_projection",
        "source_provider": projection.get("source_provider"),
        "baseline_source_path": projection.get("energy_baseline_source_path"),
        "eta_plan_source_path": projection.get("eta_plan_source_path"),
        "reserve_start_score": projection.get("reserve_start_score"),
        "route_energy_multiplier": projection.get("route_energy_multiplier"),
        "projected_target_eta": projection.get("projected_target_eta"),
        "possible_depletion_checkpoint_name": projection.get(
            "possible_depletion_checkpoint_name"
        ),
        "checkpoint_count": len(projection.get("checkpoints", [])),
        "checkpoints": projection.get("checkpoints", []),
        "data_quality": projection.get("data_quality", {}),
        "privacy": projection.get("privacy", {}),
        "boundary": projection.get("boundary", {}),
        "notes": projection.get("notes", []),
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_optional_json(path: Path | None) -> Any | None:
    return _load_json(path) if path is not None and path.exists() else None


def _load_optional_jsonl(path: Path | None) -> list[dict[str, Any]] | None:
    return _load_jsonl(path) if path is not None and path.exists() else None


def _relpath(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))
