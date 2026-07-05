from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("pretrip_package", "package_ref"),
    ("route_summary", "route_summary_ref"),
    ("route_comparison", "route_comparison_ref"),
    ("dtm_coverage_summary", "dtm_coverage_summary_ref"),
    ("segment_dtm_coverage", "segment_dtm_coverage_ref"),
    ("checkpoint_candidates", "checkpoint_candidates_ref"),
    ("segment_candidates", "segment_candidates_ref"),
    ("retreat_route_candidates", "retreat_routes_ref"),
    ("map_context_geojson", "map_context_ref"),
    ("map_candidates", "map_candidates_ref"),
    ("planning_references", "planning_references_ref"),
    ("route_guide_timing_candidates", "route_guide_timing_ref"),
    ("route_note_candidates", "route_note_candidates_ref"),
    ("route_note_ln_proposals", "route_note_ln_proposals_ref"),
    ("route_note_review_options", "route_note_review_options_ref"),
    ("skill_config_manifest", "skill_config_manifest_ref"),
    ("readiness_report", "readiness_report_ref"),
    ("human_review_log", "human_reviews_ref"),
    ("reviewed_pretrip_package", "reviewed_package_ref"),
    ("compiled_mission_graph_candidate", "compiled_mission_graph_candidate_ref"),
    ("compiled_mission_graph_reviewed", "compiled_mission_graph_reviewed_ref"),
    ("timing_measurements", "timing_measurements_ref"),
    ("planned_eta", "planned_eta_ref"),
    ("brain_seed_nodes", "brain_seed_nodes_ref"),
    ("planning_skill_audit", "planning_skill_audit_ref"),
    ("planning_skill_manifest_catalog", "planning_skill_manifest_catalog_ref"),
    ("poi_readiness_candidates", "poi_readiness_candidates_ref"),
    ("segment_policy_candidates", "segment_policy_candidates_ref"),
    ("plan_validation_candidates", "plan_validation_candidates_ref"),
    ("runtime_audit_manifest", "runtime_audit_manifest_ref"),
    ("runtime_handoff_metadata", "runtime_handoff_metadata_ref"),
    ("after_action_next_plan_candidates", "after_action_next_plan_candidates_ref"),
    ("review_queue_manifest", "review_queue_manifest_ref"),
    ("review_draft_log", "review_draft_log_ref"),
    ("review_decision_log", "review_decision_log_ref"),
    ("review_decision_apply_plan", "review_decision_apply_plan_ref"),
    ("external_import_queue", "external_import_queue_ref"),
    ("expert_contribution_log", "expert_contribution_log_ref"),
    ("remote_contact_summary", "remote_contact_summary_ref"),
    ("resource_plan", "resource_plan_ref"),
    ("departure_bundle_manifest", "departure_bundle_manifest_ref"),
    ("weather_daylight_evidence", "weather_daylight_evidence_ref"),
    ("contour_interpretation_candidates", "contour_interpretation_candidates_ref"),
)

OPTIONAL_PROJECT_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("route_context_evidence", "route_context_evidence_ref"),
    ("route_context_source_manifest", "route_context_source_manifest_ref"),
    ("route_context_pack", "route_context_pack_ref"),
    ("route_context_crawl_seed_plan", "route_context_crawl_seed_plan_ref"),
    ("route_context_media_manifest", "route_context_media_manifest_ref"),
    ("route_context_briefing", "route_context_briefing_ref"),
    ("route_context_points", "route_context_points_ref"),
    ("route_architecture", "route_architecture_ref"),
    ("pace_coefficients", "pace_coefficients_ref"),
    ("team_pace_fit", "team_pace_fit_ref"),
    ("route_pressure_profile", "route_pressure_profile_ref"),
    ("route_pressure_profile_geojson", "route_pressure_profile_geojson_ref"),
    ("boss_points", "boss_points_ref"),
    ("boss_points_geojson", "boss_points_geojson_ref"),
    ("offline_map_manifest", "offline_map_manifest_ref"),
    ("ins_dr_readiness", "ins_dr_readiness_ref"),
    ("route_weather_package", "route_weather_package_ref"),
    ("weather_source_manifest", "weather_source_manifest_ref"),
    ("weather_decision_candidates", "weather_decision_candidates_ref"),
    ("contextual_permission_model", "contextual_permission_model_ref"),
    ("contextual_permission_rules", "contextual_permission_rules_ref"),
)


@dataclass(frozen=True)
class PreTripArtifactManifest:
    project_id: str | None
    project_path: str
    project_root: str
    counts: dict[str, int]
    artifacts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_path": self.project_path,
            "project_root": self.project_root,
            "counts": self.counts,
            "artifacts": self.artifacts,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def build_pretrip_artifact_manifest(project_json_path: Path | str) -> PreTripArtifactManifest:
    project_path = Path(project_json_path)
    project_root = project_path.parent
    project = _load_json(project_path)

    artifacts = [
        _project_artifact_entry(project_root, project, artifact_kind, ref_key)
        for artifact_kind, ref_key in PROJECT_ARTIFACTS
    ]
    artifacts.extend(
        _project_artifact_entry(project_root, project, artifact_kind, ref_key)
        for artifact_kind, ref_key in OPTIONAL_PROJECT_ARTIFACTS
        if project.get(ref_key)
    )

    package_entry = next(
        entry for entry in artifacts if entry["artifact_kind"] == "pretrip_package"
    )
    artifacts.extend(_source_artifact_entries(package_entry))

    counts = {
        "total_artifacts": len(artifacts),
        "project_artifacts": sum(
            1 for artifact in artifacts if artifact.get("source") == "project"
        ),
        "source_artifacts": sum(
            1 for artifact in artifacts if artifact.get("source") == "pretrip_package"
        ),
        "missing_refs": sum(1 for artifact in artifacts if artifact.get("missing") is True),
    }

    return PreTripArtifactManifest(
        project_id=project.get("project_id"),
        project_path=project_path.as_posix(),
        project_root=project_root.as_posix(),
        counts=counts,
        artifacts=artifacts,
    )


def _project_artifact_entry(
    project_root: Path,
    project: dict[str, Any],
    artifact_kind: str,
    ref_key: str,
) -> dict[str, Any]:
    ref = project.get(ref_key)
    entry: dict[str, Any] = {
        "artifact_kind": artifact_kind,
        "ref_key": ref_key,
        "source": "project",
    }
    if not ref:
        entry["missing"] = True
        entry["missing_reason"] = "project_ref_absent"
        return entry

    artifact_path = project_root / ref
    entry["ref"] = ref
    entry["path"] = artifact_path.as_posix()
    if not artifact_path.exists():
        entry["missing"] = True
        entry["missing_reason"] = "referenced_file_missing"
        return entry

    entry["sha256"] = _sha256_file(artifact_path)
    if artifact_kind == "route_context_briefing":
        entry.update(
            {
                "content_type": "text/html",
                "size_bytes": artifact_path.stat().st_size,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
        return entry
    payload = _load_json(artifact_path)
    entry.update(_project_artifact_summary(artifact_kind, payload))
    return entry


def _project_artifact_summary(artifact_kind: str, payload: Any) -> dict[str, Any]:
    if artifact_kind == "timing_measurements":
        return {
            "measurement_candidate_count": len(payload) if isinstance(payload, list) else 0,
        }

    if not isinstance(payload, dict):
        if isinstance(payload, list):
            return {"item_count": len(payload)}
        return {}

    if artifact_kind == "pretrip_package":
        return {
            key: payload[key]
            for key in ("package_id", "project_id", "version", "status")
            if key in payload
        } | {
            "source_artifact_count": len(payload.get("source_artifacts", [])),
            "checkpoint_candidate_count": len(payload.get("checkpoint_candidates", [])),
            "segment_candidate_count": len(payload.get("segment_candidates", [])),
            "has_dtm_coverage_summary": payload.get("dtm_coverage_summary") is not None,
        }

    if artifact_kind == "route_summary":
        return {
            key: payload[key]
            for key in ("artifact_id", "route_name", "point_count", "distance_m")
            if key in payload
        }

    if artifact_kind == "route_note_candidates":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "note_candidate_count": counts.get("note_candidate_count"),
            "hazard_hint_count": counts.get("hazard_hint_count"),
            "route_condition_hint_count": counts.get("route_condition_hint_count"),
            "camp_or_water_hint_count": counts.get("camp_or_water_hint_count"),
            "landmark_hint_count": counts.get("landmark_hint_count"),
            "potential_ln_signal_count": counts.get("potential_ln_signal_count"),
            "requires_human_review_before_ln_upgrade": boundary.get(
                "requires_human_review_before_ln_upgrade"
            ),
            "raw_gpx_embedded": boundary.get("raw_gpx_embedded"),
        }

    if artifact_kind == "route_note_ln_proposals":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "proposal_count": counts.get("proposal_count"),
            "hint_coverage_proposal_count": counts.get(
                "hint_coverage_proposal_count"
            ),
            "warning_coverage_proposal_count": counts.get(
                "warning_coverage_proposal_count"
            ),
            "human_review_required_count": counts.get("human_review_required_count"),
            "observed_fact_count": counts.get("observed_fact_count"),
            "runtime_mutation_count": counts.get("runtime_mutation_count"),
            "human_review_required_before_use": boundary.get(
                "human_review_required_before_use"
            ),
            "raw_gpx_embedded": boundary.get("raw_gpx_embedded"),
        }

    if artifact_kind == "route_note_review_options":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "review_option_count": counts.get("review_option_count"),
            "candidate_only_count": counts.get("candidate_only_count"),
            "draft_only_count": counts.get("draft_only_count"),
            "decision_recorded_count": counts.get("decision_recorded_count"),
            "runtime_mutation_count": counts.get("runtime_mutation_count"),
            "candidate_only": boundary.get("candidate_only"),
            "draft_only": boundary.get("draft_only"),
            "review_options_only": boundary.get("review_options_only"),
            "decision_recording_allowed": boundary.get("decision_recording_allowed"),
            "raw_gpx_embedded": boundary.get("raw_gpx_embedded"),
        }

    if artifact_kind == "route_context_evidence":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "route_context_point_count": counts.get("route_context_point_count"),
            "source_report_count": len(payload.get("source_report", [])),
            "route_context_points_ref": payload.get("route_context_points_ref"),
            "source_manifest_ref": payload.get("source_manifest_ref"),
            "route_context_pack_ref": payload.get("route_context_pack_ref"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
            "live_safety_api_calls_allowed": boundary.get(
                "live_safety_api_calls_allowed"
            ),
        }

    if artifact_kind == "route_context_source_manifest":
        cache_policy = payload.get("cache_policy", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "source_report_count": len(payload.get("source_report", [])),
            "required_missing_source_count": len(
                payload.get("required_missing_source_kinds", [])
            ),
            "optional_missing_source_count": len(
                payload.get("optional_missing_source_kinds", [])
            ),
            "cache_mode": cache_policy.get("mode"),
            "network_refresh_required": cache_policy.get(
                "network_refresh_required"
            ),
            "cache_only_answer_allowed": cache_policy.get(
                "cache_only_answer_allowed"
            ),
            "live_source_refresh_status": cache_policy.get(
                "live_source_refresh_status"
            ),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_context_pack":
        route_summary = payload.get("route_summary", {})
        query_policy = payload.get("query_policy", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "point_count": payload.get("point_count"),
            "route_context_points_ref": payload.get("route_context_points_ref"),
            "source_manifest_ref": payload.get("source_manifest_ref"),
            "route_summary_ref": payload.get("route_summary_ref"),
            "route_distance_m": route_summary.get("distance_m"),
            "raw_route_points_embedded": route_summary.get(
                "raw_route_points_embedded"
            ),
            "query_mode": query_policy.get("mode"),
            "stop_or_delay_advice_requires_contextual_permission": query_policy.get(
                "stop_or_delay_advice_requires_contextual_permission"
            ),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_context_crawl_seed_plan":
        seed_policy = payload.get("route_note_seed_policy", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "seed_count": payload.get("seed_count"),
            "route_note_seed_count": payload.get("route_note_seed_count"),
            "route_keywords": payload.get("route_keywords"),
            "source_tier_count": len(payload.get("source_tiers", [])),
            "route_notes_are_conclusion": seed_policy.get("route_notes_are_conclusion"),
            "route_notes_are_seed_material": seed_policy.get(
                "route_notes_are_seed_material"
            ),
            "route_note_point_policy": seed_policy.get("route_note_point_policy"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_context_media_manifest":
        boundary = payload.get("boundary", {})
        image_curation = payload.get("image_curation", {})
        visual_readiness = payload.get("visual_readiness", {})
        if not isinstance(visual_readiness, dict):
            visual_readiness = {}
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "media_count": payload.get("media_count"),
            "available_media_count": payload.get("available_media_count"),
            "duplicate_media_count": payload.get("duplicate_media_count"),
            "overflow_media_count": payload.get("overflow_media_count"),
            "anchored_media_count": payload.get("anchored_media_count"),
            "route_point_media_count": payload.get("route_point_media_count"),
            "gallery_image_count": len(payload.get("gallery_images", [])),
            "image_coverage_status": image_curation.get("coverage_status"),
            "visual_readiness_status": visual_readiness.get("status"),
            "visual_readiness_label": visual_readiness.get("label"),
            "visual_quality_gate": visual_readiness.get("quality_gate"),
            "missing_image_count_to_target": visual_readiness.get(
                "missing_image_count_to_target"
            ),
            "target_min_gallery_images": image_curation.get("target_min_gallery_images"),
            "target_max_gallery_images": image_curation.get("target_max_gallery_images"),
            "missing_context_layers": image_curation.get("missing_context_layers"),
            "has_hero_image": bool(payload.get("hero_image")),
            "raw_image_embedded": boundary.get("raw_image_embedded"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_context_points":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "point_count": payload.get("point_count"),
            "by_sec6_layer": counts.get("by_sec6_layer"),
            "by_sensitivity_level": counts.get("by_sensitivity_level"),
            "by_stop_advisory_candidate": counts.get(
                "by_stop_advisory_candidate"
            ),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_architecture":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        route_architecture = payload.get("route_architecture", {})
        route_decision = payload.get("route_decision", {})
        cp_graph = payload.get("cp_graph", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "decision": payload.get("decision"),
            "answerability": payload.get("answerability"),
            "route_type": route_architecture.get("route_type")
            if isinstance(route_architecture, dict)
            else None,
            "checkpoint_count": counts.get("checkpoint_count"),
            "segment_count": counts.get("segment_count"),
            "hard_point_count": counts.get("hard_point_count"),
            "retreat_option_count": counts.get("retreat_option_count"),
            "alternative_plan_option_count": counts.get(
                "alternative_plan_option_count"
            ),
            "next_action": route_decision.get("next_action")
            if isinstance(route_decision, dict)
            else None,
            "raw_route_geometry_embedded": cp_graph.get("raw_route_geometry_embedded")
            if isinstance(cp_graph, dict)
            else None,
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "pace_coefficients":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "coefficient_schema_count": payload.get("coefficient_schema_count"),
            "member_coefficient_count": counts.get("member_coefficient_count"),
            "missing_field_count": counts.get("missing_field_count"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
            "average_pace_used": boundary.get("average_pace_used"),
        }

    if artifact_kind == "team_pace_fit":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        pace_fit = payload.get("team_pace_fit", {})
        pace_guardian = payload.get("pace_guardian", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "decision": payload.get("decision"),
            "answerability": payload.get("answerability"),
            "member_count": counts.get("member_count"),
            "members_with_pace_count": counts.get("members_with_pace_count"),
            "vulnerable_member_count": counts.get("vulnerable_member_count"),
            "missing_field_count": counts.get("missing_field_count"),
            "pace_gap_ratio": pace_fit.get("pace_gap_ratio")
            if isinstance(pace_fit, dict)
            else None,
            "average_pace_used": pace_guardian.get("average_pace_used")
            if isinstance(pace_guardian, dict)
            else boundary.get("average_pace_used"),
            "human_review_required": payload.get("human_review_required"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "boss_points":
        boundary = payload.get("boundary", {})
        challenge = payload.get("challenge_fit_summary", {})
        pressure = payload.get("route_pressure_profile_summary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "boss_point_count": payload.get("boss_point_count"),
            "route_pressure_sample_count": pressure.get("sample_count")
            if isinstance(pressure, dict)
            else None,
            "route_pressure_peak_count": pressure.get("peak_count")
            if isinstance(pressure, dict)
            else None,
            "decision": challenge.get("decision")
            if isinstance(challenge, dict)
            else None,
            "highest_challenge_fit_score": challenge.get(
                "highest_challenge_fit_score"
            )
            if isinstance(challenge, dict)
            else None,
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
            "average_pace_used": boundary.get("average_pace_used"),
        }

    if artifact_kind == "route_pressure_profile":
        boundary = payload.get("boundary", {})
        counts = payload.get("counts", {})
        summary = payload.get("summary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "sample_count": counts.get("sample_count")
            if isinstance(counts, dict)
            else None,
            "peak_count": counts.get("peak_count") if isinstance(counts, dict) else None,
            "highest_route_pressure_score": summary.get(
                "highest_route_pressure_score"
            )
            if isinstance(summary, dict)
            else None,
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_pressure_profile_geojson":
        metadata = payload.get("metadata", {})
        return {
            "project_id": metadata.get("project_id")
            if isinstance(metadata, dict)
            else None,
            "feature_count": len(payload.get("features", [])),
            "candidate_only": metadata.get("candidate_only")
            if isinstance(metadata, dict)
            else None,
            "runtime_safety_truth": metadata.get("runtime_safety_truth")
            if isinstance(metadata, dict)
            else None,
        }

    if artifact_kind == "boss_points_geojson":
        metadata = payload.get("metadata", {})
        return {
            "project_id": metadata.get("project_id")
            if isinstance(metadata, dict)
            else None,
            "feature_count": len(payload.get("features", [])),
            "candidate_only": metadata.get("candidate_only")
            if isinstance(metadata, dict)
            else None,
            "runtime_safety_truth": metadata.get("runtime_safety_truth")
            if isinstance(metadata, dict)
            else None,
        }

    if artifact_kind == "offline_map_manifest":
        boundary = payload.get("boundary", {})
        map_readiness = payload.get("map_readiness", {})
        terrain_readiness = payload.get("terrain_readiness", {})
        demand = payload.get("navigation_demand", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "decision": payload.get("decision"),
            "answerability": payload.get("answerability"),
            "navigation_demand_level": demand.get("demand_level")
            if isinstance(demand, dict)
            else None,
            "offline_map_downloaded": map_readiness.get("offline_map_downloaded")
            if isinstance(map_readiness, dict)
            else None,
            "gpx_loaded_on_device": map_readiness.get("gpx_loaded_on_device")
            if isinstance(map_readiness, dict)
            else None,
            "risk_layers_available": map_readiness.get("risk_layers_available")
            if isinstance(map_readiness, dict)
            else None,
            "terrain_layers_available": map_readiness.get("terrain_layers_available")
            if isinstance(map_readiness, dict)
            else None,
            "risk_ribbon_segment_count": terrain_readiness.get(
                "risk_ribbon_segment_count"
            )
            if isinstance(terrain_readiness, dict)
            else None,
            "human_review_required": payload.get("human_review_required"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "ins_dr_readiness":
        boundary = payload.get("boundary", {})
        positioning = payload.get("positioning_readiness", {})
        map_skill = payload.get("map_skill_readiness", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "decision": payload.get("decision"),
            "answerability": payload.get("answerability"),
            "backup_positioning_available": positioning.get(
                "backup_positioning_available"
            )
            if isinstance(positioning, dict)
            else None,
            "team_map_user_count": positioning.get("team_map_user_count")
            if isinstance(positioning, dict)
            else None,
            "live_sensor_probe_performed": positioning.get(
                "live_sensor_probe_performed"
            )
            if isinstance(positioning, dict)
            else None,
            "contour_skill_confirmed": map_skill.get("contour_skill_confirmed")
            if isinstance(map_skill, dict)
            else None,
            "human_review_required": payload.get("human_review_required"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_weather_package":
        return {
            "route_id": payload.get("routeId") or payload.get("route_id"),
            "status": payload.get("status"),
            "provider": payload.get("provider"),
            "issued_at": payload.get("issued_at"),
            "valid_from": payload.get("valid_from") or payload.get("validFrom"),
            "valid_to": payload.get("valid_to") or payload.get("validTo"),
            "ttl_s": payload.get("ttl_s"),
            "segment_count": len(payload.get("segments", [])),
            "wx_alert_count": len(payload.get("wx_alerts", [])),
            "human_review_required": payload.get("human_review_required"),
            "authoritative_weather_computed": payload.get(
                "authoritative_weather_computed"
            ),
            "external_api_calls_made": payload.get("external_api_calls_made"),
            "runtime_safety_truth": payload.get("boundary", {}).get(
                "runtime_safety_truth"
            ),
            "candidate_only": payload.get("boundary", {}).get("candidate_only"),
        }

    if artifact_kind == "weather_source_manifest":
        cache_policy = payload.get("cache_policy", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "source_report_count": len(payload.get("source_report", [])),
            "required_missing_source_count": len(
                payload.get("required_missing_source_kinds", [])
            ),
            "optional_missing_source_count": len(
                payload.get("optional_missing_source_kinds", [])
            ),
            "cache_mode": cache_policy.get("mode"),
            "live_fetch_performed": cache_policy.get("live_fetch_performed"),
            "client_cwa_api_key_allowed": cache_policy.get(
                "client_cwa_api_key_allowed"
            ),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "weather_decision_candidates":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        candidates = payload.get("candidates", [])
        first = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "candidate_count": counts.get("candidate_count"),
            "missing_field_count": counts.get("missing_field_count"),
            "warning_count": counts.get("warning_count"),
            "wx_alert_count": counts.get("wx_alert_count"),
            "first_decision": first.get("decision"),
            "first_answerability": first.get("answerability"),
            "human_review_required": first.get("human_review_required"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "contextual_permission_model":
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "supported_action_count": len(payload.get("supported_actions", [])),
            "input_signal_count": payload.get("input_signal_count"),
            "source_report_count": len(payload.get("source_report", [])),
            "rules_ref": payload.get("rules_ref"),
            "decision_object_schema": payload.get("decision_object_schema"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "contextual_permission_rules":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "project_id": payload.get("project_id"),
            "schema_version": payload.get("schema_version"),
            "rule_count": counts.get("rule_count"),
            "allowed_count": counts.get("allowed_count"),
            "bounded_permission_count": counts.get("bounded_permission_count"),
            "no_go_count": counts.get("no_go_count"),
            "change_plan_count": counts.get("change_plan_count"),
            "escalate_count": counts.get("escalate_count"),
            "missing_field_count": counts.get("missing_field_count"),
            "human_review_required": payload.get("human_review_required"),
            "candidate_only": boundary.get("candidate_only"),
            "runtime_safety_truth": boundary.get("runtime_safety_truth"),
        }

    if artifact_kind == "route_comparison":
        return {
            key: payload[key]
            for key in ("comparison_id", "classification", "distance_delta_m", "point_count_delta")
            if key in payload
        } | {
            "primary_route_name": payload.get("primary_route", {}).get("route_name"),
            "comparison_route_name": payload.get("comparison_route", {}).get("route_name"),
            "bbox_overlaps": payload.get("bbox_comparison", {}).get("overlaps"),
        }

    if artifact_kind == "dtm_coverage_summary":
        return {
            key: payload[key]
            for key in (
                "summary_id",
                "route_artifact_id",
                "scanned_header_count",
                "missing_grid_count",
            )
            if key in payload
        } | {"candidate_tile_count": len(payload.get("candidate_tiles", []))}

    if artifact_kind == "segment_dtm_coverage":
        return {
            key: payload[key]
            for key in (
                "summary_id",
                "route_artifact_id",
                "dtm_coverage_summary_id",
                "segment_count",
                "candidate_tile_count",
            )
            if key in payload
        } | {"unlinked_segment_count": len(payload.get("unlinked_segment_ids", []))}

    if artifact_kind == "skill_config_manifest":
        return {
            key: payload[key]
            for key in ("manifest_id", "project_id", "scope", "version")
            if key in payload
        }

    if artifact_kind == "readiness_report":
        return {
            key: payload[key]
            for key in ("status",)
            if key in payload
        } | {"finding_count": len(payload.get("findings", []))}

    if artifact_kind == "map_context_geojson":
        return {
            "feature_count": len(payload.get("features", [])),
            "geojson_type": payload.get("type"),
        }

    if artifact_kind == "map_candidates":
        return {
            "corridor_candidate_count": len(payload.get("corridor_candidates", [])),
            "poi_candidate_count": len(payload.get("poi_candidates", [])),
            "hazard_candidate_count": len(payload.get("hazard_candidates", [])),
        }

    if artifact_kind == "compiled_mission_graph_candidate":
        return _mission_graph_summary(payload)

    if artifact_kind == "compiled_mission_graph_reviewed":
        return _mission_graph_summary(payload)

    if artifact_kind == "human_review_log":
        return {
            "log_id": payload.get("log_id"),
            "review_count": len(payload.get("reviews", [])),
        }

    if artifact_kind == "reviewed_pretrip_package":
        return {
            key: payload[key]
            for key in ("package_id", "project_id", "version", "status")
            if key in payload
        } | {
            "checkpoint_candidate_count": len(payload.get("checkpoint_candidates", [])),
            "segment_candidate_count": len(payload.get("segment_candidates", [])),
            "retreat_route_candidate_count": len(payload.get("retreat_route_candidates", [])),
        }

    if artifact_kind == "external_import_queue":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "queue_id": payload.get("queue_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "request_count": counts.get("request_count"),
            "pending_count": counts.get("pending_count"),
            "crawler_enabled_count": counts.get("crawler_enabled_count"),
            "network_call_count": counts.get("network_call_count"),
            "observed_fact_count": counts.get("observed_fact_count"),
            "raw_payloads_embedded": counts.get("raw_payloads_embedded"),
            "no_network": boundary.get("no_network"),
            "no_crawler": boundary.get("no_crawler"),
            "source_ids": [
                request.get("source_id")
                for request in payload.get("requests", [])
                if isinstance(request, dict) and request.get("source_id")
            ],
        }

    if artifact_kind == "expert_contribution_log":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "log_id": payload.get("log_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "contribution_count": counts.get("contribution_count"),
            "candidate_set_edit_count": counts.get("candidate_set_edit_count"),
            "external_import_edit_count": counts.get("external_import_edit_count"),
            "memory_seed_candidate_count": counts.get("memory_seed_candidate_count"),
            "brain_writeback_count": counts.get("brain_writeback_count"),
            "memory_seed_candidate_only": boundary.get("memory_seed_candidate_only"),
            "brain_writeback_allowed": boundary.get("brain_writeback_allowed"),
        }

    if artifact_kind == "brain_seed_nodes":
        return {
            "artifact_count": len(payload.get("artifacts", [])),
            "human_review_count": len(payload.get("human_reviews", [])),
            "derived_measurement_count": len(payload.get("derived_measurements", [])),
            "model_interpretation_count": len(payload.get("model_interpretations", [])),
            "observed_fact_count": len(payload.get("observed_facts", [])),
            "node_count": len(payload.get("nodes", [])),
        }

    if artifact_kind == "planned_eta":
        assumption = payload.get("assumption", {})
        return {
            "plan_id": payload.get("plan_id"),
            "estimate_count": len(payload.get("estimates", [])),
            "planned_start_time": assumption.get("planned_start_time"),
            "day1_target_node_name": assumption.get("day1_target_node_name"),
            "turn_back_checkpoint_node_name": assumption.get("turn_back_checkpoint_node_name"),
            "target_eta": assumption.get("target_eta"),
            "turn_back_checkpoint_eta": assumption.get("turn_back_checkpoint_eta"),
            "team_multiplier_status": assumption.get("team_multiplier_status"),
        }

    if artifact_kind == "planning_skill_audit":
        records = payload.get("records", [])
        return {
            "project_id": payload.get("project_id"),
            "record_count": len(records),
            "skill_ids": [
                record.get("skill_id")
                for record in records
                if isinstance(record, dict) and record.get("skill_id")
            ],
            "node_types": sorted(
                {
                    str(record.get("type"))
                    for record in records
                    if isinstance(record, dict) and record.get("type")
                }
            ),
        }

    if artifact_kind == "poi_readiness_candidates":
        counts = payload.get("counts", {})
        severities = sorted(
            {
                str(finding.get("severity"))
                for finding in payload.get("findings", [])
                if isinstance(finding, dict) and finding.get("severity")
            }
        )
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "policy_candidate_count": counts.get("policy_candidate_count"),
            "finding_candidate_count": counts.get("finding_candidate_count"),
            "warning_candidate_count": counts.get("warning_candidate_count"),
            "blocker_candidate_count": counts.get("blocker_candidate_count"),
            "route_corridor_poi_count": counts.get("route_corridor_poi_count"),
            "policy_categories": [
                policy.get("category")
                for policy in payload.get("policy_candidates", [])
                if isinstance(policy, dict) and policy.get("category")
            ],
            "finding_severities": severities,
        }

    if artifact_kind == "segment_policy_candidates":
        counts = payload.get("counts", {})
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "candidate_count": len(payload.get("candidates", [])),
            "candidate_only_count": counts.get("candidate_only_count"),
            "human_review_required_count": counts.get("human_review_required_count"),
            "requires_daylight_count": counts.get("requires_daylight_count"),
            "retreat_available_count": counts.get("retreat_available_count"),
            "signal_expected_count": counts.get("signal_expected_count"),
        }

    if artifact_kind == "plan_validation_candidates":
        counts = payload.get("counts", {})
        severities = sorted(
            {
                str(finding.get("severity"))
                for finding in payload.get("findings", [])
                if isinstance(finding, dict) and finding.get("severity")
            }
        )
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "finding_candidate_count": counts.get("finding_candidate_count"),
            "warning_candidate_count": counts.get("warning_candidate_count"),
            "blocker_candidate_count": counts.get("blocker_candidate_count"),
            "source_ref_count": counts.get("source_ref_count"),
            "hard_readiness_status": payload.get("hard_readiness_status"),
            "hard_readiness_finding_count": payload.get("hard_readiness_finding_count"),
            "hard_readiness_mutation_allowed": payload.get("hard_readiness_mutation_allowed"),
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
            "finding_severities": severities,
        }

    if artifact_kind == "runtime_audit_manifest":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "manifest_id": payload.get("manifest_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "runtime_artifact_kind": payload.get("artifact_kind"),
            "comparison_axis_count": counts.get("comparison_axis_count"),
            "planned_ref_count": counts.get("planned_ref_count"),
            "observed_item_count": counts.get("observed_item_count"),
            "live_comparison_count": counts.get("live_comparison_count"),
            "raw_payload_count": counts.get("raw_payload_count"),
            "incident_package_imported": boundary.get("incident_package_imported"),
            "phase1_runtime_mutation_allowed": boundary.get("phase1_runtime_mutation_allowed"),
            "axis_names": [
                axis.get("axis")
                for axis in payload.get("axes", [])
                if isinstance(axis, dict) and axis.get("axis")
            ],
        }

    if artifact_kind == "planning_skill_manifest_catalog":
        manifests = [
            manifest
            for manifest in payload.get("manifests", [])
            if isinstance(manifest, dict)
        ]
        return {
            "catalog_id": payload.get("catalog_id"),
            "project_id": payload.get("project_id"),
            "skill_catalog_artifact_kind": payload.get("artifact_kind"),
            "manifest_count": len(manifests),
            "skill_ids": [
                manifest.get("skill_id")
                for manifest in manifests
                if manifest.get("skill_id")
            ],
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
            "automatic_brain_write_allowed_count": sum(
                1
                for manifest in manifests
                if manifest.get("brain_writeback_policy", {}).get(
                    "automatic_brain_write_allowed"
                )
                is True
            ),
            "phase1_runtime_mutation_allowed_count": sum(
                1
                for manifest in manifests
                if manifest.get("runtime_mutation_policy", {}).get(
                    "phase1_runtime_mutation_allowed"
                )
                is True
            ),
        }

    if artifact_kind == "runtime_handoff_metadata":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "manifest_id": payload.get("manifest_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "handoff_artifact_kind": payload.get("artifact_kind"),
            "plan_version_id": payload.get("plan_version_id"),
            "readiness_ref_count": counts.get("readiness_ref_count"),
            "route_ref_count": counts.get("route_ref_count"),
            "route_source_count": counts.get("route_source_count"),
            "runtime_write_count": counts.get("runtime_write_count"),
            "safety_call_count": counts.get("safety_call_count"),
            "bridge_mutation_count": counts.get("bridge_mutation_count"),
            "candidate_metadata_only": boundary.get("candidate_metadata_only"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "safety_api_calls_allowed": boundary.get("safety_api_calls_allowed"),
            "bridge_mutation_allowed": boundary.get("bridge_mutation_allowed"),
            "final_runtime_write_allowed": boundary.get("final_runtime_write_allowed"),
            "live_runtime_read_allowed": boundary.get("live_runtime_read_allowed"),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
        }

    if artifact_kind == "after_action_next_plan_candidates":
        counts = payload.get("counts", {})
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "source_case_id": payload.get("source_case_id"),
            "status": payload.get("status"),
            "candidate_count": counts.get("candidate_count"),
            "evidence_ref_count": counts.get("evidence_ref_count"),
            "brain_node_ref_count": counts.get("brain_node_ref_count"),
            "incident_package_ref_count": counts.get("incident_package_ref_count"),
            "deterministic_finding_count": counts.get("deterministic_finding"),
            "reviewer_note_count": counts.get("reviewer_note"),
            "model_suggestion_count": counts.get("model_suggestion"),
            "observed_fact_writeback_allowed": payload.get("observed_fact_writeback_allowed"),
            "historical_evidence_mutation_allowed": payload.get(
                "historical_evidence_mutation_allowed"
            ),
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
        }

    if artifact_kind == "review_queue_manifest":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "manifest_id": payload.get("manifest_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "queue_artifact_kind": payload.get("artifact_kind"),
            "item_count": counts.get("item_count"),
            "warning_count": counts.get("warning_count"),
            "blocker_count": counts.get("blocker_count"),
            "review_count": counts.get("review_count"),
            "source_ref_count": counts.get("source_ref_count"),
            "category_counts": counts.get("category_counts"),
            "candidate_queue_only": boundary.get("candidate_queue_only"),
            "decisions_recorded": boundary.get("decisions_recorded"),
            "accepts_candidates": boundary.get("accepts_candidates"),
            "rejects_candidates": boundary.get("rejects_candidates"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "review_log_mutation_allowed": boundary.get("review_log_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
            "ui_included": boundary.get("ui_included"),
        }

    if artifact_kind == "review_draft_log":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "log_id": payload.get("log_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "draft_artifact_kind": payload.get("artifact_kind"),
            "action_count": counts.get("action_count"),
            "draft_action_count": counts.get("draft_action_count"),
            "mutation_action_count": counts.get("mutation_action_count"),
            "source_ref_count": counts.get("source_ref_count"),
            "category_counts": counts.get("category_counts"),
            "draft_only": boundary.get("draft_only"),
            "decisions_recorded": boundary.get("decisions_recorded"),
            "external_api_calls_made": boundary.get("external_api_calls_made"),
            "source_mutation_allowed": boundary.get("source_mutation_allowed"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "review_log_mutation_allowed": boundary.get("review_log_mutation_allowed"),
            "runtime_mutation_allowed": boundary.get("runtime_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "admin_api_integration": boundary.get("admin_api_integration"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
        }

    if artifact_kind == "review_decision_log":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "log_id": payload.get("log_id"),
            "project_id": payload.get("project_id"),
            "decision_artifact_kind": payload.get("artifact_kind"),
            "action_count": counts.get("action_count"),
            "accepted_count": counts.get("accepted_count"),
            "corrected_count": counts.get("corrected_count"),
            "rejected_count": counts.get("rejected_count"),
            "source_ref_count": counts.get("source_ref_count"),
            "runtime_mutation_count": counts.get("runtime_mutation_count"),
            "package_mutation_count": counts.get("package_mutation_count"),
            "raw_payloads_embedded": counts.get("raw_payloads_embedded"),
            "source_mutation_allowed": boundary.get("source_mutation_allowed"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "runtime_mutation_allowed": boundary.get("runtime_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "admin_api_integration": boundary.get("admin_api_integration"),
            "compiles_mission_graph": boundary.get("compiles_mission_graph"),
        }

    if artifact_kind == "review_decision_apply_plan":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "plan_id": payload.get("plan_id"),
            "project_id": payload.get("project_id"),
            "apply_artifact_kind": payload.get("artifact_kind"),
            "decision_count": counts.get("decision_count"),
            "accepted_count": counts.get("accepted"),
            "corrected_count": counts.get("corrected"),
            "rejected_count": counts.get("rejected"),
            "package_candidate_apply_count": counts.get("package_candidate_apply_count"),
            "runtime_mutation_count": counts.get("runtime_mutation_count"),
            "would_apply_only": boundary.get("would_apply_only"),
            "source_mutation_allowed": boundary.get("source_mutation_allowed"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "runtime_mutation_allowed": boundary.get("runtime_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "compiles_mission_graph": boundary.get("compiles_mission_graph"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
        }

    if artifact_kind == "remote_contact_summary":
        route = payload.get("route", {})
        source_package = payload.get("source_package", {})
        readiness = payload.get("readiness", {})
        return {
            "summary_id": payload.get("summary_id"),
            "project_id": payload.get("project_id"),
            "audience": payload.get("audience"),
            "route_name": route.get("route_name"),
            "planned_start": route.get("planned_start"),
            "day1_target_eta": route.get("day1_target_eta"),
            "turn_back_checkpoint_eta": route.get("turn_back_checkpoint_eta"),
            "return_to_entry_eta": route.get("return_to_entry_eta"),
            "readiness_status": readiness.get("status"),
            "source_package_version": source_package.get("version"),
            "conservative_note_count": len(payload.get("conservative_notes", [])),
        }

    if artifact_kind == "resource_plan":
        departure = payload.get("departure_readiness_context", {})
        return {
            "plan_id": payload.get("plan_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "resource_artifact_kind": payload.get("artifact_kind"),
            "team_member_count": len(payload.get("team_members", [])),
            "device_count": len(payload.get("devices", [])),
            "equipment_count": len(payload.get("equipment", [])),
            "warning_candidate_count": len(departure.get("warning_candidates", [])),
            "blocker_candidate_count": len(departure.get("blocker_candidates", [])),
            "hard_readiness_mutation_allowed": departure.get("hard_readiness_mutation_allowed"),
            "blocks_existing_eta_or_readiness": departure.get("blocks_existing_eta_or_readiness"),
            "external_api_calls_made": payload.get("external_api_calls_made"),
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
        }

    if artifact_kind == "departure_bundle_manifest":
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        artifact_manifest = payload.get("artifact_manifest", {})
        return {
            "bundle_id": payload.get("bundle_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "departure_artifact_kind": payload.get("artifact_kind"),
            "required_ref_count": counts.get("required_ref_count"),
            "route_ref_count": counts.get("route_ref_count"),
            "terrain_ref_count": counts.get("terrain_ref_count"),
            "audit_ref_count": counts.get("audit_ref_count"),
            "artifact_manifest_project_artifact_count": artifact_manifest.get(
                "project_artifact_count"
            ),
            "artifact_manifest_total_artifact_count": artifact_manifest.get(
                "total_artifact_count"
            ),
            "artifact_manifest_missing_ref_count": artifact_manifest.get(
                "missing_ref_count"
            ),
            "human_review_required_before_departure": boundary.get(
                "human_review_required_before_departure"
            ),
            "not_departure_approval": boundary.get("not_departure_approval"),
            "external_api_calls_made": boundary.get("external_api_calls_made"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
        }

    if artifact_kind == "weather_daylight_evidence":
        validation = payload.get("validation", {})
        daylight = payload.get("daylight", {})
        weather_window = payload.get("weather_window", {})
        threshold_policy = payload.get("threshold_policy") or {}
        return {
            "evidence_id": payload.get("evidence_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "date": payload.get("date"),
            "route_ref": payload.get("route_ref"),
            "validation_status": validation.get("validation_status"),
            "confidence": validation.get("confidence"),
            "staleness": validation.get("staleness"),
            "human_review_required": payload.get("human_review_required"),
            "authoritative_weather_computed": payload.get("authoritative_weather_computed"),
            "external_api_calls_made": payload.get("external_api_calls_made"),
            "daylight_source_status": daylight.get("source_status"),
            "weather_source_status": weather_window.get("source_status"),
            "source_ref_count": len(payload.get("source_refs", [])),
            "threshold_policy_id": threshold_policy.get("policy_id"),
            "threshold_policy_status": threshold_policy.get("policy_status"),
            "threshold_policy_configurable": threshold_policy.get("configurable"),
            "dark_arrival_warning_margin_min": threshold_policy.get("daylight", {}).get(
                "dark_arrival_warning_margin_min"
            ),
        }

    if artifact_kind == "contour_interpretation_candidates":
        return {
            "artifact_id": payload.get("artifact_id"),
            "project_id": payload.get("project_id"),
            "status": payload.get("status"),
            "candidate_count": len(payload.get("candidates", [])),
            "not_observed_fact": payload.get("not_observed_fact"),
            "human_review_required_count": sum(
                1
                for candidate in payload.get("candidates", [])
                if isinstance(candidate, dict) and candidate.get("human_review_required") is True
            ),
        }

    return {}


def _mission_graph_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in ("mission_id", "name", "route_source")
        if key in payload
    } | {
        "checkpoint_count": len(payload.get("checkpoints", [])),
        "segment_count": len(payload.get("segments", [])),
        "diversion_point_count": len(payload.get("diversion_points", [])),
    }


def _source_artifact_entries(package_entry: dict[str, Any]) -> list[dict[str, Any]]:
    if package_entry.get("missing"):
        return []

    package_path = package_entry.get("path")
    if not package_path:
        return []

    package = _load_json(Path(package_path))
    source_artifacts = package.get("source_artifacts", [])
    entries: list[dict[str, Any]] = []
    for artifact in source_artifacts:
        if not isinstance(artifact, dict):
            continue
        entry: dict[str, Any] = {
            "artifact_kind": artifact.get("kind", "other"),
            "source": "pretrip_package",
        }
        if artifact_ref := artifact.get("artifact_id"):
            entry["ref"] = artifact_ref
        if artifact_path := artifact.get("uri"):
            entry["path"] = artifact_path
        if sha256 := artifact.get("sha256"):
            entry["sha256"] = sha256
        if media_type := artifact.get("media_type"):
            entry["media_type"] = media_type
        if artifact.get("size_bytes") is not None:
            entry["size_bytes"] = artifact["size_bytes"]
        entries.append(entry)

    return sorted(
        entries,
        key=lambda entry: (
            entry.get("artifact_kind", ""),
            entry.get("ref", ""),
            entry.get("path", ""),
        ),
    )


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
