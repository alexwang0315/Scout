from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from admin_map_layers import build_pretrip_map_layers
from post_analysis_capability import summarize_capability_artifacts
from scout_companion_match_models import build_companion_capability_capsule_from_timeline
from post_analysis_energy_feedback import POST_ANALYSIS_ENERGY_FEEDBACK_REF
from pretrip_layer_preparation import build_layer_preparation_not_prepared_view
from pretrip_energy_projection import DEFAULT_PRETRIP_ENERGY_PROJECTION_REF
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
GIS_PERCEPTION_AGGREGATION_RADIUS_M = 80.0
GIS_PERCEPTION_NEARBY_GROUP_RADIUS_M = 80.0
RISK_DELTA_COLORS = {
    "calibrated_higher": "#9333ea",
    "baseline_higher": "#2563eb",
    "aligned_high": "#7f1d1d",
    "minor_shift": "#64748b",
    "aligned": "#94a3b8",
}


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
    retreat_routes = _load_json(artifacts["retreat_routes"])
    map_candidates = _load_json(artifacts["map_candidates"])
    pretrip_package = _load_json(artifacts["package"])
    readiness = _load_json(artifacts["readiness"])
    eta = _load_json(artifacts["eta"])
    energy_projection = _load_optional_json(artifacts.get("energy_projection"))
    route_notes = _load_json(artifacts["route_notes"])
    overpass_evidence = _load_json(artifacts["overpass_evidence"])
    route_note_ln_proposals = _load_json(artifacts["route_note_ln_proposals"])
    gis_perception = _load_optional_json(artifacts.get("gis_perception"))
    gis_perception_ai_judgements = _load_optional_json(
        artifacts.get("gis_perception_ai_judgements")
    )
    route_note_review_options = _load_json(artifacts["route_note_review_options"])
    review_queue = _load_json(artifacts["review_queue"])
    review_draft_log = _load_json(artifacts["review_draft_log"])
    review_decision_log = _load_json(artifacts["review_decision_log"])
    review_decision_apply_plan = _load_json(artifacts["review_decision_apply_plan"])
    external_import_queue = _load_json(artifacts["external_import_queue"])
    expert_contribution_log = _load_json(artifacts["expert_contribution_log"])
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
    departure_bundle = _load_json(artifacts["departure_bundle"])
    resource_plan = _load_json(artifacts["resource_plan"])
    weather_daylight = _load_json(artifacts["weather_daylight"])
    contour = _load_json(artifacts["contour"])
    remote_summary = _load_json(artifacts["remote_summary"])
    route_comparison = _load_json(artifacts["route_comparison"])
    reference_tracks = _load_optional_json(artifacts.get("reference_tracks"))
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
    segment_dtm = _load_json(artifacts["segment_dtm"])
    human_reviews = _load_json(artifacts["human_reviews"])
    runtime_handoff = _load_json(artifacts["runtime_handoff"])
    runtime_audit = _load_json(artifacts["runtime_audit"])
    after_action = _load_json(artifacts["after_action"])
    brain_seed = _load_json(artifacts["brain_seed"])
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
    route_points = _route_point_samples(route_summary, checkpoints)
    route_polyline = _route_polyline(map_context)

    planning_tab = {
        "summary": _project_summary(project, route_summary, pretrip_package, source_refs),
        "route": {
            "source_id": route_summary["artifact_id"],
            "source_path": source_refs["route_summary"],
            "evidence_type": "pretrip_route_summary",
            "route_name": route_summary["route_name"],
            "bounds": route_summary["bbox_wgs84"],
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "elevation_min_m": route_summary.get("elevation_min_m"),
            "elevation_max_m": route_summary.get("elevation_max_m"),
            "started_at": route_summary.get("started_at"),
            "ended_at": route_summary.get("ended_at"),
            "point_samples": route_points,
            "polyline": route_polyline,
        },
        "mission_candidates": {
            "checkpoints": _candidate_list(
                checkpoints,
                source_path=source_refs["checkpoints"],
                evidence_type="pretrip_checkpoint_candidate",
            ),
            "segments": _candidate_list(
                segments,
                source_path=source_refs["segments"],
                evidence_type="pretrip_segment_candidate",
                display_geometry=_segment_display_geometry_by_id(
                    segment_display_geometry
                ),
            ),
            "retreat_routes": _candidate_list(
                retreat_routes,
                source_path=source_refs["retreat_routes"],
                evidence_type="pretrip_retreat_route_candidate",
            ),
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
        "route_notes": _route_note_summary(route_notes, source_refs["route_notes"]),
        "reference_tracks": _reference_tracks_summary(
            reference_tracks,
            source_refs.get("reference_tracks", ""),
            display_geometry=reference_track_display_geometry,
            display_source_path=source_refs.get("reference_track_display_geometry", ""),
        )
        if reference_tracks is not None
        else None,
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
        "contours": _contour_summary(contour, source_refs["contour"]),
        "remote_contacts": _remote_summary(remote_summary, source_refs["remote_summary"]),
    }
    planning_tab["risk_delta"] = _risk_delta_summary(
        project_id,
        planning_tab["risk_ribbon"],
        planning_tab["risk_heatmap"],
    )
    planning_tab["map_layers"] = build_pretrip_map_layers(
        source_refs=source_refs,
        weather=planning_tab["weather"],
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

    return {
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
        "checkpoint_events": planning_tab["checkpoint_events"],
        "layer_preparation": planning_tab["layer_preparation"],
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
        "mcp_review_actions": planning_tab.get("mcp_review_actions"),
        "spatial_imprints": planning_tab.get("spatial_imprints"),
        "departure_bundle": planning_tab["departure_bundle"],
        "resources": planning_tab["resources"],
        "weather": planning_tab["weather"],
        "contours": planning_tab["contours"],
        "map_layers": planning_tab["map_layers"],
        "import_manifest": post_analysis_tab.get("import_manifest"),
        "admin_surface_projection": post_analysis_tab.get("admin_surface_projection"),
        "debug_projection": post_analysis_tab.get("debug_projection"),
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
    artifacts = {
        "project": project_path,
        "route_summary": resolved_project_root / project["route_summary_ref"],
        "map_context": resolved_project_root / project["map_context_ref"],
        "checkpoints": resolved_project_root / project["checkpoint_candidates_ref"],
        "segments": resolved_project_root / project["segment_candidates_ref"],
        "retreat_routes": resolved_project_root / project["retreat_routes_ref"],
        "map_candidates": resolved_project_root / project["map_candidates_ref"],
        "package": resolved_project_root / project["package_ref"],
        "readiness": resolved_project_root / project["readiness_report_ref"],
        "eta": resolved_project_root / project["planned_eta_ref"],
        "route_notes": resolved_project_root / project["route_note_candidates_ref"],
        "overpass_evidence": resolved_project_root / project["overpass_evidence_ref"],
        "overpass_map_context": resolved_project_root
        / project["overpass_map_context_ref"],
        "overpass_raw_payload": resolved_project_root
        / project["overpass_raw_payload_ref"],
        "route_note_ln_proposals": resolved_project_root
        / project["route_note_ln_proposals_ref"],
        "route_note_review_options": resolved_project_root
        / project["route_note_review_options_ref"],
        "route_note_reviewed_assumptions": resolved_project_root
        / ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
        "departure_reviewed_candidates": resolved_project_root
        / DEPARTURE_REVIEWED_CANDIDATES_REF,
        "review_queue": resolved_project_root / project["review_queue_manifest_ref"],
        "review_draft_log": resolved_project_root / project["review_draft_log_ref"],
        "review_decision_log": resolved_project_root / project["review_decision_log_ref"],
        "review_decision_apply_plan": resolved_project_root
        / project["review_decision_apply_plan_ref"],
        "external_import_queue": resolved_project_root / project["external_import_queue_ref"],
        "expert_contribution_log": resolved_project_root / project["expert_contribution_log_ref"],
        "expert_contribution_apply_plan": resolved_project_root
        / EXPERT_CONTRIBUTION_APPLY_PLAN_REF,
        "expert_contribution_workspace_apply_result": resolved_project_root
        / EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF,
        "departure_bundle": resolved_project_root / project["departure_bundle_manifest_ref"],
        "resource_plan": resolved_project_root / project["resource_plan_ref"],
        "weather_daylight": resolved_project_root / project["weather_daylight_evidence_ref"],
        "contour": resolved_project_root / project["contour_interpretation_candidates_ref"],
        "remote_summary": resolved_project_root / project["remote_contact_summary_ref"],
        "route_comparison": resolved_project_root / project["route_comparison_ref"],
        "segment_dtm": resolved_project_root / project["segment_dtm_coverage_ref"],
        "human_reviews": resolved_project_root / project["human_reviews_ref"],
        "runtime_handoff": resolved_project_root / project["runtime_handoff_metadata_ref"],
        "runtime_audit": resolved_project_root / project["runtime_audit_manifest_ref"],
        "after_action": resolved_project_root / project["after_action_next_plan_candidates_ref"],
        "brain_seed": resolved_project_root / project["brain_seed_nodes_ref"],
    }
    for artifact_key, project_ref_key in {
        "reference_tracks": "reference_tracks_ref",
        "reference_track_display_geometry": "reference_track_display_geometry_ref",
        "checkpoint_events": "checkpoint_events_ref",
        "segment_display_geometry": "segment_display_geometry_ref",
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
        "admin_projection": "admin_projection_ref",
        "debug_projection_events": "debug_projection_events_ref",
        "gis_perception": "gis_perception_candidates_ref",
        "gis_perception_ai_judgements": "gis_perception_ai_judgements_ref",
        "mcp_named_point_evidence": "mcp_named_point_evidence_ref",
        "mcp_retrieval_plan": "mcp_retrieval_plan_ref",
        "mcp_ocr_labels": "mcp_ocr_labels_ref",
        "mcp_candidates": "mcp_candidates_ref",
        "mcp_cp_support_reconciliation": "mcp_cp_support_reconciliation_ref",
        "mcp_review_log": "mcp_review_log_ref",
        "spatial_imprint_candidates": "spatial_imprint_candidates_ref",
        "spatial_imprint_reviews": "spatial_imprint_reviews_ref",
        "spatial_imprint_set": "spatial_imprint_set_ref",
        "spatial_imprint_manifest": "spatial_imprint_manifest_ref",
    }.items():
        if project.get(project_ref_key):
            artifacts[artifact_key] = resolved_project_root / project[project_ref_key]
    for artifact_key, default_ref in {
        "spatial_imprint_candidates": DEFAULT_SPATIAL_IMPRINT_CANDIDATES_REF,
        "spatial_imprint_reviews": DEFAULT_SPATIAL_IMPRINT_REVIEWS_REF,
        "spatial_imprint_set": DEFAULT_SPATIAL_IMPRINT_SET_REF,
        "spatial_imprint_manifest": DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF,
        "energy_projection": DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
        "companion_match_review": COMPANION_MATCH_REVIEW_REF,
        "post_analysis_energy_feedback": POST_ANALYSIS_ENERGY_FEEDBACK_REF,
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
    def optional_project_path(ref_key: str) -> Path | None:
        project_ref = project.get(ref_key)
        return resolved_project_root / project_ref if project_ref else None

    route_summary = _load_json(resolved_project_root / project["route_summary_ref"])
    map_context = _load_json(resolved_project_root / project["map_context_ref"])
    checkpoints_raw = _load_json(
        resolved_project_root / project["checkpoint_candidates_ref"]
    )
    segments_raw = _load_json(resolved_project_root / project["segment_candidates_ref"])
    map_candidates_raw = _load_json(resolved_project_root / project["map_candidates_ref"])
    reference_tracks_raw = _load_optional_json(
        optional_project_path("reference_tracks_ref")
    )
    reference_track_display_geometry = _load_optional_json(
        optional_project_path("reference_track_display_geometry_ref")
    )
    checkpoint_events_raw = _load_optional_json(
        optional_project_path("checkpoint_events_ref")
    )
    segment_display_geometry = _load_optional_json(
        optional_project_path("segment_display_geometry_ref")
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
    mcp_named_point_evidence_raw = _load_optional_json(
        optional_project_path("mcp_named_point_evidence_ref")
    )
    mcp_retrieval_plan_raw = _load_optional_json(
        optional_project_path("mcp_retrieval_plan_ref")
    )
    mcp_ocr_labels_raw = _load_optional_json(optional_project_path("mcp_ocr_labels_ref"))
    mcp_candidates_raw = _load_optional_json(optional_project_path("mcp_candidates_ref"))
    mcp_cp_support_reconciliation_raw = _load_optional_json(
        optional_project_path("mcp_cp_support_reconciliation_ref")
    )
    mcp_review_log_raw = _load_optional_json(optional_project_path("mcp_review_log_ref"))
    source_refs = {
        "project": "project.json",
        "route_summary": project["route_summary_ref"],
        "map_context": project["map_context_ref"],
        "checkpoints": project["checkpoint_candidates_ref"],
        "segments": project["segment_candidates_ref"],
        "map_candidates": project["map_candidates_ref"],
        "reference_tracks": project.get("reference_tracks_ref", ""),
        "reference_track_display_geometry": project.get(
            "reference_track_display_geometry_ref",
            "",
        ),
        "checkpoint_events": project.get("checkpoint_events_ref", ""),
        "segment_display_geometry": project.get("segment_display_geometry_ref", ""),
        "overpass_evidence": project.get("overpass_evidence_ref", ""),
        "retreat_routes": project.get("retreat_routes_ref", ""),
        "readiness": project.get("readiness_report_ref", ""),
        "segment_dtm": project.get("segment_dtm_coverage_ref", ""),
        "route_notes": project.get("route_note_candidates_ref", ""),
        "risk_route_profile": project.get("risk_route_profile_ref", ""),
        "risk_route_profile_metadata": project.get("risk_route_profile_metadata_ref", ""),
        "risk_score_points": project.get("risk_score_points_ref", ""),
        "risk_score_points_metadata": project.get("risk_score_points_metadata_ref", ""),
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
        "mcp_candidates": project.get("mcp_candidates_ref", ""),
        "mcp_cp_support_reconciliation": project.get(
            "mcp_cp_support_reconciliation_ref",
            "",
        ),
        "mcp_review_log": project.get("mcp_review_log_ref", ""),
        "weather_daylight": project.get("weather_daylight_evidence_ref", ""),
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
    view = {
        "project_id": project_id,
        "route": {
            "source_id": route_summary["artifact_id"],
            "source_path": source_refs["route_summary"],
            "evidence_type": "pretrip_route_summary",
            "route_name": route_summary["route_name"],
            "bounds": route_summary["bbox_wgs84"],
            "point_count": route_summary["point_count"],
            "distance_m": route_summary["distance_m"],
            "elevation_min_m": route_summary.get("elevation_min_m"),
            "elevation_max_m": route_summary.get("elevation_max_m"),
            "started_at": route_summary.get("started_at"),
            "ended_at": route_summary.get("ended_at"),
            "polyline": _route_polyline(map_context),
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
        ),
        "reference_tracks": _reference_tracks_summary(
            reference_tracks_raw,
            source_refs["reference_tracks"],
            display_geometry=reference_track_display_geometry,
            display_source_path=source_refs["reference_track_display_geometry"],
        )
        if reference_tracks_raw is not None
        else _empty_reference_tracks(project_id, source_refs["reference_tracks"]),
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
        "readiness": _summary_with_source(
            readiness_raw or {"status": "unknown", "findings": []},
            source_id=f"readiness.{project_id}",
            source_path=source_refs["readiness"],
            evidence_type="pretrip_readiness_report",
            include_keys=("status", "findings"),
        ),
    }
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
            "display_geometry": _route_display_geometry_from_segments(
                project_id,
                view["segments"],
            ),
        },
        "checkpoints": view["checkpoints"],
        "segments": view["segments"],
        "retreat_routes": view["retreat_routes"],
        "map_candidates": view["map_candidates"],
        "overpass_evidence": view["overpass_evidence"],
        "gis_perception": view["gis_perception"],
        "gis_perception_timeline": view["gis_perception_timeline"],
        "reference_tracks": view["reference_tracks"],
        "checkpoint_events": view["checkpoint_events"],
        "risk_score": view["risk_score"],
        "risk_ribbon": view["risk_ribbon"],
        "risk_heatmap": view["risk_heatmap"],
        "risk_delta": view["risk_delta"],
        "major_critical_points": view.get("major_critical_points"),
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
    coordinates: list[dict[str, float]] = []
    for segment in segments:
        display_geometry = segment.get("display_geometry")
        segment_coordinates = (
            display_geometry.get("coordinates", [])
            if isinstance(display_geometry, dict)
            else []
        )
        if len(segment_coordinates) < 2:
            continue
        for point in segment_coordinates:
            if not isinstance(point, dict):
                continue
            lat = point.get("lat")
            lon = point.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            normalized = {"lat": float(lat), "lon": float(lon)}
            if coordinates and coordinates[-1] == normalized:
                continue
            coordinates.append(normalized)
    return {
        "source_id": f"route_display_geometry.{project_id}",
        "source_path": "outputs/segment_display_geometry.json",
        "evidence_type": "pretrip_route_display_geometry",
        "display_point_count": len(coordinates),
        "coordinates": coordinates,
        "boundary": {
            "display_geometry_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "internal_gpx_points_preserved": True,
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
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_gis_perception_candidates",
        "status": payload["status"],
        "source_profile": payload["source_profile"],
        "counts": payload["counts"],
        "classifier": payload["classifier"],
        "boundary": _summary_boundary(payload["boundary"]),
        "ai_judgements": ai_judgement_summary,
        "checkpoint_candidates": [
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
                "source_attribution": candidate.get("source_attribution", []),
                "human_review_required": candidate["human_review_required"],
            }
            for candidate in payload.get("checkpoint_candidates", [])
        ],
    }


def _gis_perception_ai_judgement_summary(
    payload: dict[str, Any] | None,
    source_path: str,
) -> dict[str, Any]:
    if payload is None:
        return {
            "source_path": source_path,
            "evidence_type": "pretrip_gis_perception_ai_judgements",
            "status": "not_available",
            "judgement_count": 0,
            "candidate_only": True,
            "runtime_safety_truth_count": 0,
        }
    return {
        "source_id": payload["artifact_kind"],
        "source_path": source_path,
        "evidence_type": "pretrip_gis_perception_ai_judgements",
        "provider_kind": payload["provider_kind"],
        "model_name": payload["model_name"],
        "prompt_sha256": payload["prompt_sha256"],
        "input_count": payload["input_count"],
        "judgement_count": payload["judgement_count"],
        "live_model_call_performed": payload["live_model_call_performed"],
        "network_calls_allowed": payload["network_calls_allowed"],
        "runtime_safety_truth_count": sum(
            1 for judgement in payload.get("judgements", [])
            if judgement.get("runtime_safety_truth") is not False
        ),
        "cp_needed_count": sum(
            1 for judgement in payload.get("judgements", [])
            if judgement.get("cp_needed") is True
        ),
        "preview_judgements": payload.get("judgements", [])[:12],
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
    return {
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
    }


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
        source_attribution = [
            {
                "source_kind": "overpass_candidate",
                "source_profile": "overpass_osm_tags",
                "source_candidate_id": candidate["candidate_id"],
                "source_artifact_id": overpass_evidence.get("source_id", ""),
                "source_role": "route_corridor_osm_evidence",
                "source_label": candidate.get("label") or candidate["candidate_id"],
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
        projected.append(
            {
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
                "route_note_summary": (
                    f"OSM {candidate.get('candidate_type')}: "
                    f"{candidate.get('label') or candidate['candidate_id']}"
                ),
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
            }
        )
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
    return {
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
                "checkpoint_type": item.get("checkpoint_type"),
                "semantic_aggregation_key": item.get("semantic_aggregation_key"),
                "summary": item.get("route_note_summary") or item["candidate_id"],
                "source_profile": item.get("source_profile"),
                "stale_route_note": item.get("stale_route_note", False),
                "route_note_freshness": item.get("route_note_freshness", "unknown"),
            }
            for item in group
        ]
        center_lat = sum(float(item["lat"]) for item in group) / len(group)
        center_lon = sum(float(item["lon"]) for item in group) / len(group)
        nearby_group = {
            "nearby_group_id": group_id,
            "source_id": group_id,
            "candidate_id": group_id,
            "evidence_type": "pretrip_gis_perception_nearby_group",
            "source_path": "project.json#gis-perception-nearby-group",
            "status": "candidate_only_grouping",
            "member_count": len(group),
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
    return {
        "item_id": f"review_queue.gis_perception.{candidate['candidate_id']}",
        "candidate_ref": candidate["candidate_id"],
        "category": "gis_perception_cp",
        "severity": severity,
        "title": f"GIS CP review: {candidate.get('checkpoint_type')}",
        "summary": candidate.get("route_note_summary") or candidate["candidate_id"],
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
            "nearby_group_size": candidate.get("nearby_group_size", 1),
            "nearby_group_members": candidate.get("nearby_group_members", []),
            "merged_candidate_ids": candidate.get("merged_candidate_ids", []),
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "accept_reject_allowed": True,
        "candidate_only": True,
        "human_review_required": True,
        "decision_recorded": False,
        "mutation_allowed": False,
        "map_target_ids": candidate.get("map_target_ids", [candidate["candidate_id"]]),
    }


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
        "human_review_required": True,
        "decision_recorded": False,
        "accept_reject_allowed": False,
        "mutation_allowed": False,
        "source_id": f"review_queue.energy_reserve.{_safe_view_key(depletion_checkpoint)}",
        "source_path": energy_projection.get("source_path", ""),
        "evidence_type": "pretrip_review_queue_item",
        "map_target_ids": [depletion_checkpoint],
    }
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
    return {
        item["segment_candidate_id"]: {
            "source_id": item["segment_candidate_id"],
            "source_path": payload.get("source_path")
            or "outputs/segment_display_geometry.json",
            "evidence_type": "pretrip_segment_display_geometry",
            "source_point_count": item.get("source_point_count"),
            "display_point_count": len(item.get("coordinates", [])),
            "coordinates": item.get("coordinates", []),
            "boundary": payload.get("boundary", {}),
        }
        for item in payload.get("segments", [])
    }


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
            "source_id": candidate["candidate_id"],
            "source_path": source_path,
            "evidence_type": evidence_type,
        }
        for candidate in candidates
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
    return {
        **item,
        "source_id": item["item_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_review_queue_item",
        "map_target_ids": _review_item_map_target_ids(item),
    }


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
            "group_type": "gis_nearby_group",
            "label": group.get("nearby_group_id"),
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


def _route_note_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_route_note_candidates",
        "status": payload["status"],
        "counts": payload["counts"],
        "boundary": _summary_boundary(payload["boundary"]),
        "candidates": [
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
                "source_fields_present": candidate["source_fields_present"],
            }
            for candidate in payload.get("candidates", [])
        ],
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
                "candidate_only": proposal["candidate_only"],
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
    support_rows = list((cp_support_reconciliation or {}).get("rows", []) or [])
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
            "fetch_summaries": retrieval_counts.get("fetch_summaries", [])[:12],
            "queries": retrieval_counts.get("queries", [])[:12],
        },
        "ocr": {
            "artifact_kind": ocr_counts.get("artifact_kind"),
            "label_count": ocr_counts.get("label_count", 0),
            "review_required_count": ocr_counts.get("review_required_count", 0),
            "labels": ocr_counts.get("labels", [])[:12],
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
        "candidates": [_spatial_imprint_item_summary(item) for item in candidate_items],
        "reviews": [
            {
                "review_id": record.get("review_id"),
                "candidate_ref": record.get("candidate_ref"),
                "decision": record.get("decision"),
                "reviewed_by": record.get("reviewed_by"),
                "reviewed_at": record.get("reviewed_at"),
                "summary": record.get("summary"),
            }
            for record in review_records
        ],
        "reviewed_imprints": [
            _spatial_imprint_item_summary(item) for item in reviewed_imprints
        ],
        "rejected_audit_refs": (manifest or {}).get("rejected_audit_refs", []),
        "disabled_audit_refs": (manifest or {}).get("disabled_audit_refs", []),
    }


def _spatial_imprint_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    trigger = item.get("trigger", {})
    predicates = list(trigger.get("predicates", []) or [])
    return {
        "imprint_id": item.get("imprint_id"),
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
        "route_refs": payload.get("route_refs", []),
        "terrain_refs": payload.get("terrain_refs", []),
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


def _contour_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["artifact_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_contour_interpretation_candidates",
        "status": payload["status"],
        "candidate_count": len(payload.get("candidates", [])),
        "not_observed_fact": payload["not_observed_fact"],
        "raw_payloads_embedded": False,
        "candidates": payload.get("candidates", []),
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
        "candidate_id": reference_id,
        "source_id": reference_id,
        "source_path": source_path,
        "evidence_type": "pretrip_reference_track",
        "label": track.get("route", {}).get("route_name") or reference_id,
        "review_state": "reference_only",
        "map_target_ids": [reference_id],
        **(
            {
                "display_geometry": {
                    "source_id": reference_id,
                    "source_path": display_source_path,
                    "evidence_type": "pretrip_reference_track_display_geometry",
                    "source_point_count": display.get("source_point_count"),
                    "display_point_count": display.get("display_point_count"),
                    "display_sampling_performed": display.get(
                        "display_sampling_performed"
                    ),
                    "coordinates": display.get("coordinates", []),
                }
            }
            if display is not None
            else {}
        ),
    }


def _checkpoint_events_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": f"checkpoint_events.{payload['project_id']}",
        "source_path": source_path,
        "evidence_type": "pretrip_checkpoint_event_candidates",
        "event_count": payload["event_count"],
        "source_gpx": payload["source_gpx"],
        "events": payload.get("events", []),
        "boundary": payload["boundary"],
        "notes": payload.get("notes", []),
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


def _segment_terrain_summary(payload: dict[str, Any], source_path: str) -> dict[str, Any]:
    return {
        "source_id": payload["dtm_coverage_summary_id"],
        "source_path": source_path,
        "evidence_type": "pretrip_segment_dtm_coverage",
        "route_artifact_id": payload["route_artifact_id"],
        "segment_count": payload["segment_count"],
        "candidate_tile_count": payload["candidate_tile_count"],
        "raw_payloads_embedded": False,
        "notes": payload["notes"],
        "segment_metadata": payload.get("segment_metadata", []),
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
    return {
        **summary,
        "source_id": "pretrip.imported_capability_timeline",
        "evidence_type": "pretrip_capability_timeline_import",
        "status": "read_only_post_analysis_import",
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
    return {
        "source_id": "brain_seed_nodes.chilai_nanhua_day1",
        "source_path": source_path,
        "evidence_type": "pretrip_brain_seed_nodes",
        "node_count": len(payload.get("nodes", [])),
        "artifact_count": len(payload.get("artifacts", [])),
        "derived_measurement_count": len(payload.get("derived_measurements", [])),
        "human_review_count": len(payload.get("human_reviews", [])),
        "model_interpretation_count": len(payload.get("model_interpretations", [])),
        "observed_fact_count": len(payload.get("observed_facts", [])),
    }


def _planning_sections(planning_tab: dict[str, Any]) -> list[dict[str, Any]]:
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
    route_notes = planning_tab["route_notes"]
    reference_tracks = planning_tab.get("reference_tracks")
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
            summary={"observed_fact_count": brain_seed["observed_fact_count"]},
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
        "counts": counts,
        "summary": summary,
    }
    if status is not None:
        section["status"] = status
    if boundary is not None:
        section["boundary"] = _summary_boundary(boundary)
    return section


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
    return {
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
    return {
        "source_id": pretrip_package["package_id"],
        "source_path": source_refs["package"],
        "evidence_type": "pretrip_raw_sample_summary",
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
