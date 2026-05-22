from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from admin_map_layers import build_pretrip_map_layers
from pretrip_layer_preparation import build_layer_preparation_not_prepared_view


ROOT = Path(__file__).resolve().parent
CHILAI_NANHUA_DAY1_PROJECT_ID = "chilai_nanhua_day1"
PRETRIP_PROJECTS_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"
EXPERT_CONTRIBUTION_APPLY_PLAN_REF = "outputs/expert_contribution_apply_plan.json"
EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF = (
    "outputs/expert_contribution_workspace_apply_result.json"
)
ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF = "outputs/route_note_reviewed_assumptions.json"


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
    route_notes = _load_json(artifacts["route_notes"])
    overpass_evidence = _load_json(artifacts["overpass_evidence"])
    route_note_ln_proposals = _load_json(artifacts["route_note_ln_proposals"])
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
    departure_bundle = _load_json(artifacts["departure_bundle"])
    resource_plan = _load_json(artifacts["resource_plan"])
    weather_daylight = _load_json(artifacts["weather_daylight"])
    contour = _load_json(artifacts["contour"])
    remote_summary = _load_json(artifacts["remote_summary"])
    route_comparison = _load_json(artifacts["route_comparison"])
    reference_tracks = _load_optional_json(artifacts.get("reference_tracks"))
    checkpoint_events = _load_optional_json(artifacts.get("checkpoint_events"))
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
        "overpass_evidence": _overpass_evidence_summary(
            overpass_evidence,
            source_refs["overpass_evidence"],
        ),
        "route_note_ln_proposals": _route_note_ln_proposal_summary(
            route_note_ln_proposals,
            source_refs["route_note_ln_proposals"],
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
    planning_tab["map_layers"] = build_pretrip_map_layers(
        source_refs=source_refs,
        weather=planning_tab["weather"],
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
    planning_sections = _planning_sections(planning_tab)
    review_workspace_section_ids = {
        "review_queue",
        "route_note_review_options",
        "route_note_reviewed_assumptions",
        "review_draft_log",
        "review_decision_log",
        "review_decision_apply_plan",
        "external_import_queue",
        "expert_contributions",
        "expert_contribution_apply_plan",
        "expert_contribution_workspace_apply_result",
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
        "overpass_evidence": planning_tab["overpass_evidence"],
        "route_note_ln_proposals": planning_tab["route_note_ln_proposals"],
        "route_note_review_options": planning_tab["route_note_review_options"],
        "route_note_reviewed_assumptions": planning_tab.get(
            "route_note_reviewed_assumptions"
        ),
        "review_queue": planning_tab["review_queue"],
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
        "departure_bundle": planning_tab["departure_bundle"],
        "resources": planning_tab["resources"],
        "weather": planning_tab["weather"],
        "contours": planning_tab["contours"],
        "map_layers": planning_tab["map_layers"],
        "import_manifest": post_analysis_tab.get("import_manifest"),
        "admin_surface_projection": post_analysis_tab.get("admin_surface_projection"),
        "debug_projection": post_analysis_tab.get("debug_projection"),
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
        "admin_projection": "admin_projection_ref",
        "debug_projection_events": "debug_projection_events_ref",
    }.items():
        if project.get(project_ref_key):
            artifacts[artifact_key] = resolved_project_root / project[project_ref_key]
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
    retreat_routes_raw = _load_optional_json(
        optional_project_path("retreat_routes_ref")
    )
    readiness_raw = _load_optional_json(
        optional_project_path("readiness_report_ref")
    )
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
        "reference_tracks": view["reference_tracks"],
        "checkpoint_events": view["checkpoint_events"],
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


def _geojson_line_coordinates(geometry: dict[str, Any]) -> list[dict[str, float]]:
    return [
        {"lon": float(lon), "lat": float(lat)}
        for lon, lat in geometry.get("coordinates", [])
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
    weather = planning_tab["weather"]
    overpass_evidence = planning_tab["overpass_evidence"]
    route_notes = planning_tab["route_notes"]
    reference_tracks = planning_tab.get("reference_tracks")
    checkpoint_events = planning_tab.get("checkpoint_events")
    route_note_ln_proposals = planning_tab["route_note_ln_proposals"]
    route_note_review_options = planning_tab["route_note_review_options"]
    route_note_reviewed_assumptions = planning_tab.get(
        "route_note_reviewed_assumptions"
    )
    review_queue = planning_tab["review_queue"]
    review_draft_log = planning_tab["review_draft_log"]
    review_decision_log = planning_tab["review_decision_log"]
    review_decision_apply_plan = planning_tab["review_decision_apply_plan"]
    external_import_queue = planning_tab["external_import_queue"]
    expert_contributions = planning_tab["expert_contributions"]
    expert_contribution_apply_plan = planning_tab.get("expert_contribution_apply_plan")
    expert_contribution_workspace_apply_result = planning_tab.get(
        "expert_contribution_workspace_apply_result"
    )
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
