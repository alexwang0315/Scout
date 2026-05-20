from __future__ import annotations

import argparse
import ast
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECT_PATH = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)

CORE_PHASE4_PATHS = (
    "pretrip_models.py",
    "pretrip_source_ingest.py",
    "pretrip_candidate_generation.py",
    "pretrip_geojson_import.py",
    "pretrip_map_compiler.py",
    "pretrip_terrain_summary.py",
    "pretrip_timing_calibration.py",
    "pretrip_eta_plan.py",
    "pretrip_skill_audit.py",
    "pretrip_skill_manifest_catalog.py",
    "pretrip_readiness.py",
    "pretrip_review_models.py",
    "pretrip_review_resolver.py",
    "pretrip_review_queue.py",
    "pretrip_mission_compiler.py",
    "pretrip_brain_seed.py",
    "pretrip_brain_seed_store.py",
    "pretrip_artifact_manifest.py",
    "pretrip_remote_summary.py",
    "pretrip_route_comparison.py",
    "pretrip_poi_readiness.py",
    "pretrip_segment_policy.py",
    "pretrip_plan_validation.py",
    "pretrip_runtime_audit.py",
    "pretrip_runtime_handoff_metadata.py",
    "pretrip_review_profiles.py",
    "pretrip_departure_gate.py",
    "pretrip_departure_gate_resolution.py",
    "pretrip_final_mission_graph.py",
    "pretrip_runtime_handoff.py",
    "pretrip_runtime_export.py",
    "runtime_artifact_resolution.py",
    "pretrip_runtime_artifact_resolution.py",
    "pretrip_runtime_activation_preflight.py",
    "pretrip_runtime_activation_request.py",
    "runtime_load_dry_run.py",
    "runtime_activation_loader.py",
    "runtime_stream_policy.py",
    "runtime_observation_envelope.py",
    "runtime_input_admission.py",
    "runtime_incident_bridge_opt_in.py",
    "runtime_incident_bridge_enablement.py",
    "runtime_incident_bridge_delivery_ack.py",
    "runtime_remote_provider_policy.py",
    "runtime_remote_provider_config_preflight.py",
    "runtime_remote_provider_payload_composer.py",
    "runtime_remote_provider_send_queue.py",
    "runtime_remote_provider_live_adapter.py",
    "runtime_remote_provider_live_send_cli.py",
    "runtime_remote_provider_demo_harness.py",
    "runtime_remote_provider_demo_bundle.py",
    "server_safety_observation_admission_config.py",
    "runtime_stream_transport_api.py",
    "runtime_stream_telemetry.py",
    "runtime_stream_controls.py",
    "pretrip_after_action_candidates.py",
    "pretrip_resource_plan.py",
    "pretrip_weather_daylight.py",
    "pretrip_contour_interpretation.py",
    "pretrip_departure_bundle.py",
    "pretrip_scout260512_fixture.py",
    "pretrip_project_matrix.py",
    "pretrip_source_registry.py",
    "pretrip_implementation_status.py",
    "pretrip_decision_register.py",
    "pretrip_fixture_hygiene.py",
    "admin_map_layers.py",
    "admin_local_raster_source.py",
    "admin_local_raster_tiles.py",
    "admin_tile_cache_builder.py",
    "admin_tile_proxy.py",
    "admin_weather_overlay.py",
    "pretrip_admin_view.py",
    "pretrip_review_draft.py",
    "pretrip_review_draft_fixture.py",
    "pretrip_review_decision_log.py",
    "pretrip_review_decision_apply.py",
    "pretrip_review_decision_apply_store.py",
    "pretrip_review_decision_store.py",
    "pretrip_workspace_project.py",
    "pretrip_external_import_queue.py",
    "pretrip_expert_contribution.py",
    "pretrip_expert_contribution_apply_plan.py",
    "pretrip_route_note_candidates.py",
    "pretrip_route_note_ln_proposals.py",
    "pretrip_route_note_review_options.py",
    "pretrip_route_note_reviewed_assumptions.py",
    "admin_basemap_tiles.py",
)

FOCUSED_PHASE4_TEST_PATHS = (
    "tests/test_pretrip_source_ingest.py",
    "tests/test_pretrip_candidate_generation.py",
    "tests/test_pretrip_geojson_import.py",
    "tests/test_pretrip_map_compiler.py",
    "tests/test_pretrip_terrain_summary.py",
    "tests/test_pretrip_timing_calibration.py",
    "tests/test_pretrip_eta_plan.py",
    "tests/test_pretrip_skill_audit.py",
    "tests/test_pretrip_skill_manifest_catalog.py",
    "tests/test_pretrip_readiness.py",
    "tests/test_pretrip_review_models.py",
    "tests/test_pretrip_review_resolver.py",
    "tests/test_pretrip_review_integration.py",
    "tests/test_pretrip_review_queue.py",
    "tests/test_pretrip_mission_compiler.py",
    "tests/test_pretrip_brain_seed.py",
    "tests/test_pretrip_brain_seed_store.py",
    "tests/test_pretrip_artifact_manifest.py",
    "tests/test_pretrip_remote_summary.py",
    "tests/test_pretrip_route_comparison.py",
    "tests/test_pretrip_poi_readiness.py",
    "tests/test_pretrip_segment_policy.py",
    "tests/test_pretrip_plan_validation.py",
    "tests/test_pretrip_runtime_audit.py",
    "tests/test_pretrip_runtime_handoff_metadata.py",
    "tests/test_pretrip_review_profiles.py",
    "tests/test_pretrip_departure_gate.py",
    "tests/test_pretrip_departure_gate_resolution.py",
    "tests/test_pretrip_final_mission_graph.py",
    "tests/test_pretrip_runtime_handoff.py",
    "tests/test_pretrip_runtime_export.py",
    "tests/test_pretrip_runtime_artifact_resolution.py",
    "tests/test_pretrip_runtime_activation_preflight.py",
    "tests/test_pretrip_runtime_activation_request.py",
    "tests/test_runtime_load_dry_run.py",
    "tests/test_runtime_activation_loader.py",
    "tests/test_runtime_stream_policy.py",
    "tests/test_runtime_observation_envelope.py",
    "tests/test_runtime_input_admission.py",
    "tests/test_safety_observation_admission_api.py",
    "tests/test_server_safety_observation_admission_config.py",
    "tests/test_runtime_stream_transport_api.py",
    "tests/test_runtime_stream_telemetry.py",
    "tests/test_runtime_stream_controls.py",
    "tests/test_runtime_incident_bridge_opt_in.py",
    "tests/test_runtime_incident_bridge_enablement.py",
    "tests/test_runtime_incident_bridge_delivery_ack.py",
    "tests/test_runtime_remote_provider_policy.py",
    "tests/test_runtime_remote_provider_config_preflight.py",
    "tests/test_runtime_remote_provider_payload_composer.py",
    "tests/test_runtime_remote_provider_send_queue.py",
    "tests/test_runtime_remote_provider_live_adapter.py",
    "tests/test_runtime_remote_provider_live_send_cli.py",
    "tests/test_runtime_remote_provider_demo_harness.py",
    "tests/test_runtime_remote_provider_demo_bundle.py",
    "tests/test_runtime_remote_provider_external_demo_bundle.py",
    "tests/test_pretrip_after_action_candidates.py",
    "tests/test_pretrip_resource_plan.py",
    "tests/test_pretrip_weather_daylight.py",
    "tests/test_pretrip_contour_interpretation.py",
    "tests/test_pretrip_departure_bundle.py",
    "tests/test_pretrip_scout260512_fixture.py",
    "tests/test_pretrip_project_matrix.py",
    "tests/test_pretrip_source_registry.py",
    "tests/test_pretrip_implementation_status.py",
    "tests/test_pretrip_decision_register.py",
    "tests/test_pretrip_fixture_hygiene.py",
    "tests/test_admin_map_layers.py",
    "tests/test_admin_local_raster_source.py",
    "tests/test_admin_local_raster_tiles.py",
    "tests/test_admin_basemap_tiles.py",
    "tests/test_admin_tile_cache_builder.py",
    "tests/test_admin_tile_proxy.py",
    "tests/test_admin_weather_overlay.py",
    "tests/test_pretrip_admin_view.py",
    "tests/test_pretrip_admin_page.py",
    "tests/test_pretrip_admin_api.py",
    "tests/test_admin_after_action.py",
    "tests/test_pretrip_review_draft.py",
    "tests/test_pretrip_review_draft_fixture.py",
    "tests/test_pretrip_review_decision_log.py",
    "tests/test_pretrip_review_decision_apply.py",
    "tests/test_pretrip_review_decision_apply_store.py",
    "tests/test_pretrip_review_decision_store.py",
    "tests/test_pretrip_workspace_project.py",
    "tests/test_pretrip_external_import_queue.py",
    "tests/test_pretrip_expert_contribution.py",
    "tests/test_pretrip_expert_contribution_apply_plan.py",
    "tests/test_pretrip_route_note_candidates.py",
    "tests/test_pretrip_route_note_ln_proposals.py",
    "tests/test_pretrip_route_note_review_options.py",
    "tests/test_pretrip_route_note_reviewed_assumptions.py",
    "tests/test_phase4_pretrip_release_check.py",
)

PHASE4_UI_PATHS = (
    "admin_map_layers.py",
    "admin_local_raster_source.py",
    "admin_local_raster_tiles.py",
    "admin_basemap_tiles.py",
    "admin_tile_cache_builder.py",
    "admin_tile_proxy.py",
    "admin_weather_overlay.py",
    "docs/admin/phase4-pretrip-planning.html",
    "docs/admin/phase1-after-action.html",
    "pretrip_admin_view.py",
    "tests/test_admin_map_layers.py",
    "tests/test_admin_local_raster_source.py",
    "tests/test_admin_local_raster_tiles.py",
    "tests/test_admin_basemap_tiles.py",
    "tests/test_admin_tile_cache_builder.py",
    "tests/test_admin_tile_proxy.py",
    "tests/test_admin_weather_overlay.py",
    "tests/test_pretrip_admin_view.py",
    "tests/test_pretrip_admin_page.py",
    "tests/test_pretrip_admin_api.py",
    "tests/test_admin_after_action.py",
)

RAW_FIXTURE_SUFFIXES = {
    ".asc",
    ".dem",
    ".gpx",
    ".grd",
    ".hdr",
    ".jpeg",
    ".jpg",
    ".las",
    ".laz",
    ".png",
    ".tif",
    ".tiff",
    ".zip",
}
MAX_FIXTURE_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class PathCheck:
    name: str
    required_paths: tuple[str, ...]


PATH_CHECKS = (
    PathCheck("core_phase4_modules", CORE_PHASE4_PATHS),
    PathCheck("focused_phase4_tests", FOCUSED_PHASE4_TEST_PATHS),
)


def build_release_check(
    repo_root: Path | str = REPO_ROOT,
    *,
    project_json_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    project_path = (
        Path(project_json_path)
        if project_json_path is not None
        else root / DEFAULT_PROJECT_PATH
    )
    project_root = project_path.parent

    checks: dict[str, Any] = {}
    missing_required: list[str] = []

    for path_check in PATH_CHECKS:
        check = _check_required_paths(root, path_check.required_paths)
        checks[path_check.name] = check
        missing_required.extend(check["missing"])

    ui_check = _check_pretrip_admin_ui(root)
    checks["pretrip_admin_ui"] = ui_check
    missing_required.extend(ui_check["missing"])

    admin_map_layer_check = _check_admin_map_layer_stack(root)
    checks["admin_map_layer_stack"] = admin_map_layer_check
    missing_required.extend(admin_map_layer_check["missing"])

    admin_local_raster_source_check = _check_admin_local_raster_source(root)
    checks["admin_local_raster_source"] = admin_local_raster_source_check
    missing_required.extend(admin_local_raster_source_check["missing"])

    admin_local_raster_tiles_check = _check_admin_local_raster_tiles(root)
    checks["admin_local_raster_tiles"] = admin_local_raster_tiles_check
    missing_required.extend(admin_local_raster_tiles_check["missing"])

    admin_basemap_renderer_check = _check_admin_basemap_renderer(root)
    checks["admin_basemap_renderer"] = admin_basemap_renderer_check
    missing_required.extend(admin_basemap_renderer_check["missing"])

    admin_tile_cache_builder_check = _check_admin_tile_cache_builder(root)
    checks["admin_tile_cache_builder"] = admin_tile_cache_builder_check
    missing_required.extend(admin_tile_cache_builder_check["missing"])

    admin_tile_proxy_check = _check_admin_tile_proxy(root)
    checks["admin_tile_proxy"] = admin_tile_proxy_check
    missing_required.extend(admin_tile_proxy_check["missing"])

    admin_weather_overlay_check = _check_admin_weather_overlay(root)
    checks["admin_weather_overlay"] = admin_weather_overlay_check
    missing_required.extend(admin_weather_overlay_check["missing"])

    static_boundary_check = _check_core_phase4_static_boundaries(root)
    checks["core_phase4_static_boundaries"] = static_boundary_check
    missing_required.extend(static_boundary_check["missing"])

    project_check = _check_project_refs(project_path)
    checks["chilai_project_refs"] = project_check
    missing_required.extend(project_check["missing"])

    fixture_check = _check_fixture_boundary(project_root)
    checks["fixture_boundary"] = fixture_check
    missing_required.extend(fixture_check["missing"])

    route_comparison_check = _check_route_comparison(project_root, project_check["project"])
    checks["route_comparison"] = route_comparison_check
    missing_required.extend(route_comparison_check["missing"])

    dtm_check = _check_dtm_metadata_only(project_root, project_check["project"])
    checks["dtm_metadata_only"] = dtm_check
    missing_required.extend(dtm_check["missing"])

    package_check = _check_packages(project_root, project_check["project"])
    checks["package_status"] = package_check
    missing_required.extend(package_check["missing"])

    mission_graph_check = _check_mission_graphs(project_root, project_check["project"])
    checks["mission_graphs"] = mission_graph_check
    missing_required.extend(mission_graph_check["missing"])

    readiness_check = _check_readiness(project_root, project_check["project"])
    checks["readiness"] = readiness_check
    missing_required.extend(readiness_check["missing"])

    timing_check = _check_timing_measurements(project_root, project_check["project"])
    checks["timing_measurements"] = timing_check
    missing_required.extend(timing_check["missing"])

    eta_check = _check_planned_eta(project_root, project_check["project"])
    checks["planned_eta"] = eta_check
    missing_required.extend(eta_check["missing"])

    remote_summary_check = _check_remote_contact_summary(project_root, project_check["project"])
    checks["remote_contact_summary"] = remote_summary_check
    missing_required.extend(remote_summary_check["missing"])

    weather_daylight_check = _check_weather_daylight_evidence(project_root, project_check["project"])
    checks["weather_daylight_evidence"] = weather_daylight_check
    missing_required.extend(weather_daylight_check["missing"])

    contour_check = _check_contour_interpretation_candidates(project_root, project_check["project"])
    checks["contour_interpretation_candidates"] = contour_check
    missing_required.extend(contour_check["missing"])

    brain_seed_check = _check_brain_seed(project_root, project_check["project"])
    checks["brain_seed"] = brain_seed_check
    missing_required.extend(brain_seed_check["missing"])

    skill_audit_check = _check_planning_skill_audit(project_root, project_check["project"])
    checks["planning_skill_audit"] = skill_audit_check
    missing_required.extend(skill_audit_check["missing"])

    skill_manifest_catalog_check = _check_planning_skill_manifest_catalog(
        project_root,
        project_check["project"],
    )
    checks["planning_skill_manifest_catalog"] = skill_manifest_catalog_check
    missing_required.extend(skill_manifest_catalog_check["missing"])

    poi_readiness_check = _check_poi_readiness_candidates(project_root, project_check["project"])
    checks["poi_readiness_candidates"] = poi_readiness_check
    missing_required.extend(poi_readiness_check["missing"])

    segment_policy_check = _check_segment_policy_candidates(project_root, project_check["project"])
    checks["segment_policy_candidates"] = segment_policy_check
    missing_required.extend(segment_policy_check["missing"])

    plan_validation_check = _check_plan_validation_candidates(project_root, project_check["project"])
    checks["plan_validation_candidates"] = plan_validation_check
    missing_required.extend(plan_validation_check["missing"])

    runtime_audit_check = _check_runtime_audit_manifest(project_root, project_check["project"])
    checks["runtime_audit_manifest"] = runtime_audit_check
    missing_required.extend(runtime_audit_check["missing"])

    runtime_handoff_check = _check_runtime_handoff_metadata(
        project_root,
        project_check["project"],
    )
    checks["runtime_handoff_metadata"] = runtime_handoff_check
    missing_required.extend(runtime_handoff_check["missing"])

    phase45_handoff_check = _check_phase45_departure_runtime_handoff(root)
    checks["phase45_departure_runtime_handoff"] = phase45_handoff_check
    missing_required.extend(phase45_handoff_check["missing"])

    runtime_stream_policy_check = _check_runtime_stream_policy()
    checks["runtime_stream_policy"] = runtime_stream_policy_check
    missing_required.extend(runtime_stream_policy_check["missing"])

    runtime_observation_envelope_check = _check_runtime_observation_envelope()
    checks["runtime_observation_envelope"] = runtime_observation_envelope_check
    missing_required.extend(runtime_observation_envelope_check["missing"])

    runtime_input_admission_check = _check_runtime_input_admission()
    checks["runtime_input_admission"] = runtime_input_admission_check
    missing_required.extend(runtime_input_admission_check["missing"])

    safety_observation_admission_api_check = _check_safety_observation_admission_api(root)
    checks["safety_observation_admission_api"] = safety_observation_admission_api_check
    missing_required.extend(safety_observation_admission_api_check["missing"])

    server_safety_observation_admission_config_check = (
        _check_server_safety_observation_admission_config(root)
    )
    checks["server_safety_observation_admission_config"] = (
        server_safety_observation_admission_config_check
    )
    missing_required.extend(
        server_safety_observation_admission_config_check["missing"]
    )

    runtime_stream_transport_api_check = _check_runtime_stream_transport_api(root)
    checks["runtime_stream_transport_api"] = runtime_stream_transport_api_check
    missing_required.extend(runtime_stream_transport_api_check["missing"])

    runtime_stream_telemetry_check = _check_runtime_stream_telemetry(root)
    checks["runtime_stream_telemetry"] = runtime_stream_telemetry_check
    missing_required.extend(runtime_stream_telemetry_check["missing"])

    runtime_stream_controls_check = _check_runtime_stream_controls(root)
    checks["runtime_stream_controls"] = runtime_stream_controls_check
    missing_required.extend(runtime_stream_controls_check["missing"])

    runtime_incident_bridge_opt_in_check = _check_runtime_incident_bridge_opt_in()
    checks["runtime_incident_bridge_opt_in"] = runtime_incident_bridge_opt_in_check
    missing_required.extend(runtime_incident_bridge_opt_in_check["missing"])

    runtime_incident_bridge_enablement_check = (
        _check_runtime_incident_bridge_enablement_dry_run(root)
    )
    checks["runtime_incident_bridge_enablement"] = (
        runtime_incident_bridge_enablement_check
    )
    missing_required.extend(runtime_incident_bridge_enablement_check["missing"])

    runtime_incident_bridge_delivery_ack_check = (
        _check_runtime_incident_bridge_delivery_ack(root)
    )
    checks["runtime_incident_bridge_delivery_ack"] = (
        runtime_incident_bridge_delivery_ack_check
    )
    missing_required.extend(runtime_incident_bridge_delivery_ack_check["missing"])

    runtime_remote_provider_policy_check = _check_runtime_remote_provider_policy(root)
    checks["runtime_remote_provider_policy"] = runtime_remote_provider_policy_check
    missing_required.extend(runtime_remote_provider_policy_check["missing"])

    runtime_remote_provider_config_preflight_check = (
        _check_runtime_remote_provider_config_preflight(root)
    )
    checks["runtime_remote_provider_config_preflight"] = (
        runtime_remote_provider_config_preflight_check
    )
    missing_required.extend(runtime_remote_provider_config_preflight_check["missing"])

    runtime_remote_provider_payload_composer_check = (
        _check_runtime_remote_provider_payload_composer(root)
    )
    checks["runtime_remote_provider_payload_composer"] = (
        runtime_remote_provider_payload_composer_check
    )
    missing_required.extend(runtime_remote_provider_payload_composer_check["missing"])

    runtime_remote_provider_send_queue_check = _check_runtime_remote_provider_send_queue(
        root
    )
    checks["runtime_remote_provider_send_queue"] = (
        runtime_remote_provider_send_queue_check
    )
    missing_required.extend(runtime_remote_provider_send_queue_check["missing"])

    runtime_remote_provider_live_adapter_check = (
        _check_runtime_remote_provider_live_adapter(root)
    )
    checks["runtime_remote_provider_live_adapter"] = (
        runtime_remote_provider_live_adapter_check
    )
    missing_required.extend(runtime_remote_provider_live_adapter_check["missing"])

    runtime_remote_provider_live_send_cli_check = (
        _check_runtime_remote_provider_live_send_cli(root)
    )
    checks["runtime_remote_provider_live_send_cli"] = (
        runtime_remote_provider_live_send_cli_check
    )
    missing_required.extend(runtime_remote_provider_live_send_cli_check["missing"])

    runtime_remote_provider_demo_harness_check = (
        _check_runtime_remote_provider_demo_harness(root)
    )
    checks["runtime_remote_provider_demo_harness"] = (
        runtime_remote_provider_demo_harness_check
    )
    missing_required.extend(runtime_remote_provider_demo_harness_check["missing"])

    runtime_remote_provider_demo_bundle_check = (
        _check_runtime_remote_provider_demo_bundle(root)
    )
    checks["runtime_remote_provider_demo_bundle"] = (
        runtime_remote_provider_demo_bundle_check
    )
    missing_required.extend(runtime_remote_provider_demo_bundle_check["missing"])

    runtime_remote_provider_external_demo_bundle_check = (
        _check_runtime_remote_provider_external_demo_bundle(root)
    )
    checks["runtime_remote_provider_external_demo_bundle"] = (
        runtime_remote_provider_external_demo_bundle_check
    )
    missing_required.extend(
        runtime_remote_provider_external_demo_bundle_check["missing"]
    )

    after_action_check = _check_after_action_next_plan_candidates(
        project_root,
        project_check["project"],
    )
    checks["after_action_next_plan_candidates"] = after_action_check
    missing_required.extend(after_action_check["missing"])

    review_queue_check = _check_review_queue_manifest(
        project_root,
        project_check["project"],
    )
    checks["review_queue_manifest"] = review_queue_check
    missing_required.extend(review_queue_check["missing"])

    review_draft_check = _check_review_draft_log(
        project_root,
        project_check["project"],
    )
    checks["review_draft_log"] = review_draft_check
    missing_required.extend(review_draft_check["missing"])

    review_decision_check = _check_review_decision_log(
        project_root,
        project_check["project"],
    )
    checks["review_decision_log"] = review_decision_check
    missing_required.extend(review_decision_check["missing"])

    review_decision_apply_check = _check_review_decision_apply_plan(
        project_root,
        project_check["project"],
    )
    checks["review_decision_apply_plan"] = review_decision_apply_check
    missing_required.extend(review_decision_apply_check["missing"])

    admin_workspace_persistence_check = _check_admin_workspace_persistence_contract(root)
    checks["admin_workspace_persistence_contract"] = admin_workspace_persistence_check
    missing_required.extend(admin_workspace_persistence_check["missing"])

    admin_workspace_project_creation_check = (
        _check_admin_workspace_project_creation_contract(root)
    )
    checks["admin_workspace_project_creation_contract"] = (
        admin_workspace_project_creation_check
    )
    missing_required.extend(admin_workspace_project_creation_check["missing"])

    admin_ui_write_controls_check = _check_admin_ui_local_workspace_write_controls(root)
    checks["admin_ui_local_workspace_write_controls"] = admin_ui_write_controls_check
    missing_required.extend(admin_ui_write_controls_check["missing"])

    external_import_check = _check_external_import_queue(
        project_root,
        project_check["project"],
    )
    checks["external_import_queue"] = external_import_check
    missing_required.extend(external_import_check["missing"])

    route_note_check = _check_route_note_candidates(
        project_root,
        project_check["project"],
    )
    checks["route_note_candidates"] = route_note_check
    missing_required.extend(route_note_check["missing"])

    route_note_ln_proposal_check = _check_route_note_ln_proposals(
        project_root,
        project_check["project"],
    )
    checks["route_note_ln_proposals"] = route_note_ln_proposal_check
    missing_required.extend(route_note_ln_proposal_check["missing"])

    route_note_review_options_check = _check_route_note_review_options(
        project_root,
        project_check["project"],
    )
    checks["route_note_review_options"] = route_note_review_options_check
    missing_required.extend(route_note_review_options_check["missing"])

    expert_contribution_check = _check_expert_contribution_log(
        project_root,
        project_check["project"],
    )
    checks["expert_contribution_log"] = expert_contribution_check
    missing_required.extend(expert_contribution_check["missing"])

    workspace_only_artifact_check = _check_workspace_only_artifact_boundaries(root)
    checks["workspace_only_artifact_boundaries"] = workspace_only_artifact_check
    missing_required.extend(workspace_only_artifact_check["missing"])

    resource_plan_check = _check_resource_plan(project_root, project_check["project"])
    checks["resource_plan"] = resource_plan_check
    missing_required.extend(resource_plan_check["missing"])

    departure_bundle_check = _check_departure_bundle_manifest(
        project_root,
        project_check["project"],
    )
    checks["departure_bundle_manifest"] = departure_bundle_check
    missing_required.extend(departure_bundle_check["missing"])

    scout260512_check = _check_scout260512_pretrip_regression(root)
    checks["scout260512_pretrip_regression"] = scout260512_check
    missing_required.extend(scout260512_check["missing"])

    project_matrix_check = _check_pretrip_project_matrix(root)
    checks["pretrip_project_matrix"] = project_matrix_check
    missing_required.extend(project_matrix_check["missing"])

    source_registry_check = _check_pretrip_source_registry(root)
    checks["pretrip_source_registry"] = source_registry_check
    missing_required.extend(source_registry_check["missing"])

    implementation_status_check = _check_pretrip_implementation_status(root)
    checks["pretrip_implementation_status"] = implementation_status_check
    missing_required.extend(implementation_status_check["missing"])

    decision_register_check = _check_pretrip_decision_register(root)
    checks["pretrip_decision_register"] = decision_register_check
    missing_required.extend(decision_register_check["missing"])

    fixture_hygiene_check = _check_pretrip_fixture_hygiene(root)
    checks["pretrip_fixture_hygiene"] = fixture_hygiene_check
    missing_required.extend(fixture_hygiene_check["missing"])

    manifest_check = _check_artifact_manifest(project_path)
    checks["artifact_manifest"] = manifest_check
    missing_required.extend(manifest_check["missing"])

    failed_checks = sorted(name for name, check in checks.items() if not check["ok"])
    missing_required = sorted(set(missing_required))
    return {
        "ok": not failed_checks,
        "repo_root": str(root),
        "project_path": str(project_path),
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_required_artifacts": missing_required,
    }


def _check_required_paths(root: Path, required_paths: Sequence[str]) -> dict[str, Any]:
    missing = sorted(path for path in required_paths if not (root / path).exists())
    return {
        "ok": not missing,
        "required": len(required_paths),
        "present": len(required_paths) - len(missing),
        "missing": missing,
    }


def _check_pretrip_admin_ui(root: Path) -> dict[str, Any]:
    from pretrip_admin_view import build_pretrip_admin_view

    missing: list[str] = []
    path_check = _check_required_paths(root, PHASE4_UI_PATHS)
    missing.extend(path_check["missing"])

    page_path = root / "docs" / "admin" / "phase4-pretrip-planning.html"
    page_text = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
    required_fragments = (
        "Scout Phase 4 Pre-Trip Planning",
        'id="map"',
        'id="evidenceTree"',
        'id="jsonPane"',
        "Pre-trip planning",
        "Post-analysis",
        "segment-overlay",
        "map-highlight",
        "selectEvidence",
        "/admin/pretrip/projects/${PROJECT_ID}",
        "summary only",
    )
    for fragment in required_fragments:
        if fragment not in page_text:
            missing.append(f"pretrip_admin_ui_missing_fragment:{fragment}")
    for disabled_control in ("featureEdit", "addCheckpoint", "externalDataImport"):
        expected = f'id="{disabled_control}" class="tool-button" type="button" disabled'
        if expected not in page_text:
            missing.append(f"pretrip_admin_ui_control_not_disabled:{disabled_control}")

    try:
        view = build_pretrip_admin_view("chilai_nanhua_day1", root=root)
    except Exception as exc:
        return {
            "ok": False,
            "path_count": path_check["present"],
            "view_project_id": None,
            "checkpoint_count": None,
            "segment_count": None,
            "raw_payloads_embedded": None,
            "ui_write_controls_disabled": None,
            "missing": [*missing, f"pretrip_admin_view:{exc}"],
        }

    raw_summary = view.get("raw_sample_summary", {})
    if raw_summary.get("raw_payloads_embedded") is not False:
        missing.append("pretrip_admin_ui_raw_payloads_embedded:false")
    if raw_summary.get("raw_gpx_read") is not False:
        missing.append("pretrip_admin_ui_raw_gpx_read:false")
    if raw_summary.get("raw_photo_read") is not False:
        missing.append("pretrip_admin_ui_raw_photo_read:false")
    if raw_summary.get("raw_dtm_read") is not False:
        missing.append("pretrip_admin_ui_raw_dtm_read:false")
    runtime_handoff = view.get("tabs", {}).get("post_analysis", {}).get("runtime_handoff", {})
    if runtime_handoff.get("boundary", {}).get("phase1_runtime_mutation_allowed") is not False:
        missing.append("pretrip_admin_ui_no_phase1_runtime_mutation")

    return {
        "ok": not missing,
        "path_count": path_check["present"],
        "view_project_id": view.get("project_id"),
        "checkpoint_count": len(view.get("checkpoints", [])),
        "segment_count": len(view.get("segments", [])),
        "raw_payloads_embedded": raw_summary.get("raw_payloads_embedded"),
        "ui_write_controls_disabled": all(
            f'id="{control}" class="tool-button" type="button" disabled' in page_text
            for control in ("featureEdit", "addCheckpoint", "externalDataImport")
        ),
        "missing": missing,
    }


def _check_admin_map_layer_stack(root: Path) -> dict[str, Any]:
    from admin_map_layers import (
        build_after_action_map_layers,
        build_pretrip_map_layers,
        map_layer_ids,
    )

    expected_pretrip = [
        "imagery",
        "osm",
        "terrain",
        "corridors",
        "hazards",
        "route",
        "retreat",
        "segments",
        "checkpoints",
        "pois",
        "route-notes",
        "weather-api",
    ]
    expected_after_action = [
        "imagery",
        "osm",
        "corridors",
        "hazards",
        "route",
        "checkpoints",
        "events",
        "weather-api",
    ]
    pretrip_layers = build_pretrip_map_layers(
        source_refs={
            "imagery": "external/local/chilai_nanhua_day1.local_raster_source_manifest.json",
            "map_context": "normalized/map/map_context.geojson",
            "map_candidates": "candidates/map_candidates.json",
            "route_summary": "normalized/route_summary.json",
            "segment_dtm": "normalized/terrain/segment_dtm_coverage.json",
            "weather_daylight": "outputs/weather_daylight_evidence.json",
        },
        weather={
            "source_id": "weather_daylight.chilai_nanhua_day1",
            "source_path": "outputs/weather_daylight_evidence.json",
            "external_api_calls_made": False,
        },
    )
    after_action_layers = build_after_action_map_layers(
        map_source_path="tests/fixtures/maps/scout_260512_overpass_map_context.geojson",
        map_metadata={"source": "openstreetmap_overpass"},
    )

    missing: list[str] = []
    if map_layer_ids(pretrip_layers) != expected_pretrip:
        missing.append("admin_map_layer_stack:pretrip_layer_order")
    if map_layer_ids(after_action_layers) != expected_after_action:
        missing.append("admin_map_layer_stack:after_action_layer_order")
    if pretrip_layers[0].get("layer_kind") != "imagery":
        missing.append("admin_map_layer_stack:pretrip_imagery_not_bottom")
    if pretrip_layers[0].get("local_raster_manifest_supported") is not True:
        missing.append("admin_map_layer_stack:pretrip_imagery_local_raster_manifest")
    if pretrip_layers[0].get("local_raster_tile_url_template") != (
        "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    ):
        missing.append("admin_map_layer_stack:pretrip_imagery_tile_template")
    if pretrip_layers[0].get("external_network_required") is not False:
        missing.append("admin_map_layer_stack:pretrip_imagery_external_network")
    if pretrip_layers[-1].get("layer_kind") != "api":
        missing.append("admin_map_layer_stack:pretrip_api_not_top")
    if after_action_layers[0].get("layer_kind") != "imagery":
        missing.append("admin_map_layer_stack:after_action_imagery_not_bottom")
    if after_action_layers[-1].get("layer_kind") != "api":
        missing.append("admin_map_layer_stack:after_action_api_not_top")
    if after_action_layers[-1].get("available") is not False:
        missing.append("admin_map_layer_stack:after_action_weather_api_not_disabled")
    if any(layer.get("external_api_calls_made") for layer in pretrip_layers):
        missing.append("admin_map_layer_stack:pretrip_external_api_call")
    if any(layer.get("external_api_calls_made") for layer in after_action_layers):
        missing.append("admin_map_layer_stack:after_action_external_api_call")
    osm_layers = [
        next(layer for layer in pretrip_layers if layer["layer_id"] == "osm"),
        next(layer for layer in after_action_layers if layer["layer_id"] == "osm"),
    ]
    for osm_layer in osm_layers:
        if osm_layer.get("render_mode") != "osm_raster_tile":
            missing.append("admin_map_layer_stack:osm_render_mode")
        if osm_layer.get("source_kind") != "openstreetmap_tile":
            missing.append("admin_map_layer_stack:osm_source_kind")
        if osm_layer.get("tile_url_template") != "https://tile.openstreetmap.org/{z}/{x}/{y}.png":
            missing.append("admin_map_layer_stack:osm_tile_url_template")
        if osm_layer.get("external_network_required") is not True:
            missing.append("admin_map_layer_stack:osm_external_network_required")
        if osm_layer.get("local_proxy_tile_url_template") != "/admin/tiles/osm/{z}/{x}/{y}.png":
            missing.append("admin_map_layer_stack:osm_local_proxy_template")
        if osm_layer.get("local_proxy_external_network_required") is not False:
            missing.append("admin_map_layer_stack:osm_local_proxy_network")
        if osm_layer.get("downloads_tiles_into_repo") is not False:
            missing.append("admin_map_layer_stack:osm_downloads_tiles_into_repo")
    weather_layers = [
        next(layer for layer in pretrip_layers if layer["layer_id"] == "weather-api"),
        next(layer for layer in after_action_layers if layer["layer_id"] == "weather-api"),
    ]
    for weather_layer in weather_layers:
        if weather_layer.get("render_mode") != "api_overlay":
            missing.append("admin_map_layer_stack:weather_api_render_mode")
        if weather_layer.get("external_network_required") is not False:
            missing.append("admin_map_layer_stack:weather_api_network_contract")
        if weather_layer.get("secret_value_embedded") is not False:
            missing.append("admin_map_layer_stack:weather_api_secret_value_embedded")

    page_checks = {
        "pretrip": (
            root / "docs" / "admin" / "phase4-pretrip-planning.html",
            expected_pretrip,
        ),
        "after_action": (
            root / "docs" / "admin" / "phase1-after-action.html",
            expected_after_action,
        ),
    }
    page_order_ok: dict[str, bool] = {}
    page_raster_imagery_ok = False
    for surface, (page_path, layer_ids) in page_checks.items():
        page_text = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
        if not page_text:
            missing.append(f"admin_map_layer_stack:{surface}_page_missing")
            page_order_ok[surface] = False
            continue
        for layer_id in layer_ids:
            if f'data-layer="{layer_id}"' not in page_text:
                missing.append(
                    f"admin_map_layer_stack:{surface}_missing_toggle:{layer_id}"
                )
            if f'data-layer-group": "{layer_id}"' not in page_text:
                missing.append(
                    f"admin_map_layer_stack:{surface}_missing_group:{layer_id}"
                )
        for fragment in (
            "OSM_TILE_URL_TEMPLATE",
            "OSM_LOCAL_TILE_URL_TEMPLATE",
            "function osmTileTemplate",
            "/admin/tiles/osm/{z}/{x}/{y}.png",
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "function renderOsmBasemap",
            "function osmTileCoverage",
            'el("image"',
            'class: "osm-tile"',
        ):
            if fragment not in page_text:
                missing.append(
                    f"admin_map_layer_stack:{surface}_missing_real_basemap:{fragment}"
                )
        if surface == "pretrip":
            raster_fragments = (
                "RASTER_LOCAL_TILE_URL_TEMPLATE",
                "function rasterTileTemplate",
                "function rasterTileCoverage",
                "function renderRasterImagery",
                "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png",
                'class: "raster-tile"',
                "data-raster-tile",
                "local_raster_tile_url_template",
            )
            for fragment in raster_fragments:
                if fragment not in page_text:
                    missing.append(
                        f"admin_map_layer_stack:{surface}_missing_raster_imagery:{fragment}"
                    )
            page_raster_imagery_ok = all(
                fragment in page_text for fragment in raster_fragments
            ) and page_text.find("renderRasterImagery(imageryGroup") < page_text.find(
                "renderOsmBasemap(osmGroup"
            )
            if not page_raster_imagery_ok:
                missing.append("admin_map_layer_stack:pretrip_raster_imagery_renderer")
        positions = [
            page_text.find(f'data-layer-group": "{layer_id}"')
            for layer_id in layer_ids
        ]
        page_order_ok[surface] = positions == sorted(positions) and all(
            position >= 0 for position in positions
        )
        if not page_order_ok[surface]:
            missing.append(f"admin_map_layer_stack:{surface}_dom_order")

    return {
        "ok": not missing,
        "pretrip_layer_ids": map_layer_ids(pretrip_layers),
        "after_action_layer_ids": map_layer_ids(after_action_layers),
        "ordering_policy": "imagery_bottom_api_top",
        "pretrip_imagery_bottom": pretrip_layers[0].get("layer_id") == "imagery",
        "pretrip_imagery_source_path": pretrip_layers[0].get("source_path"),
        "pretrip_imagery_local_raster_manifest_supported": pretrip_layers[0].get(
            "local_raster_manifest_supported"
        ),
        "pretrip_imagery_local_raster_tile_url_template": pretrip_layers[0].get(
            "local_raster_tile_url_template"
        ),
        "pretrip_raster_imagery_renderer_present": page_raster_imagery_ok,
        "pretrip_imagery_external_network_required": pretrip_layers[0].get(
            "external_network_required"
        ),
        "pretrip_api_top": pretrip_layers[-1].get("layer_id") == "weather-api",
        "after_action_imagery_bottom": after_action_layers[0].get("layer_id")
        == "imagery",
        "after_action_api_top": after_action_layers[-1].get("layer_id")
        == "weather-api",
        "after_action_weather_api_available": after_action_layers[-1].get("available"),
        "osm_render_mode": osm_layers[0].get("render_mode"),
        "osm_tile_url_template": osm_layers[0].get("tile_url_template"),
        "osm_local_proxy_tile_url_template": osm_layers[0].get(
            "local_proxy_tile_url_template"
        ),
        "osm_external_network_required": osm_layers[0].get("external_network_required"),
        "osm_local_proxy_external_network_required": osm_layers[0].get(
            "local_proxy_external_network_required"
        ),
        "weather_api_render_mode": weather_layers[0].get("render_mode"),
        "weather_api_external_network_required": weather_layers[0].get(
            "external_network_required"
        ),
        "external_api_calls_made": any(
            layer.get("external_api_calls_made")
            for layer in [*pretrip_layers, *after_action_layers]
        ),
        "page_order_ok": page_order_ok,
        "missing": missing,
    }


def _check_admin_basemap_renderer(root: Path) -> dict[str, Any]:
    try:
        from admin_basemap_tiles import (
            DEFAULT_ATTRIBUTION,
            DEFAULT_CACHE_POLICY,
            DEFAULT_MOUNTAIN_ROUTE_ZOOM,
            DEFAULT_OSM_TILE_URL_TEMPLATE,
            SOURCE_KIND,
            build_osm_basemap_contract,
        )
    except Exception as exc:
        return {
            "ok": False,
            "source_kind": None,
            "tile_count": 0,
            "svg_image_count": 0,
            "missing": [f"admin_basemap_renderer_import:{exc}"],
        }

    source_root = root if (root / "admin_basemap_tiles.py").exists() else REPO_ROOT
    source = (source_root / "admin_basemap_tiles.py").read_text(encoding="utf-8")
    contract = build_osm_basemap_contract(
        {
            "min_lat": 23.964,
            "min_lon": 121.255,
            "max_lat": 24.045,
            "max_lon": 121.355,
        },
        max_tiles=8,
    )
    tiles = contract.get("tiles", [])
    svg_images = contract.get("svg_images", [])
    first_tile = tiles[0] if tiles else {}
    first_image = svg_images[0] if svg_images else {}
    source_has_nonstdlib_network = any(
        token in source
        for token in (
            "import requests",
            "requests.",
            "import httpx",
            "httpx.",
            "import fastapi",
            "from fastapi",
        )
    )

    missing: list[str] = []
    if contract.get("source_kind") != SOURCE_KIND:
        missing.append("admin_basemap_renderer_source_kind")
    if not tiles:
        missing.append("admin_basemap_renderer_tiles_present")
    if len(tiles) > 8:
        missing.append("admin_basemap_renderer_max_tiles")
    if contract.get("zoom", DEFAULT_MOUNTAIN_ROUTE_ZOOM + 1) > DEFAULT_MOUNTAIN_ROUTE_ZOOM:
        missing.append("admin_basemap_renderer_zoom_not_bounded")
    if contract.get("tile_url_template") != DEFAULT_OSM_TILE_URL_TEMPLATE:
        missing.append("admin_basemap_renderer_osm_template")
    if contract.get("attribution") != DEFAULT_ATTRIBUTION:
        missing.append("admin_basemap_renderer_attribution")
    if contract.get("external_network_required") is not True:
        missing.append("admin_basemap_renderer_external_network_required")
    if contract.get("cache_policy") != DEFAULT_CACHE_POLICY:
        missing.append("admin_basemap_renderer_cache_policy")
    if len(svg_images) != len(tiles):
        missing.append("admin_basemap_renderer_svg_image_count")
    if first_tile and not str(first_tile.get("url", "")).startswith(
        "https://tile.openstreetmap.org/"
    ):
        missing.append("admin_basemap_renderer_tile_url")
    if first_image and first_image.get("tag") != "image":
        missing.append("admin_basemap_renderer_svg_image_tag")
    for key in ("x", "y", "width", "height", "href"):
        if first_image and key not in first_image:
            missing.append(f"admin_basemap_renderer_svg_image_key:{key}")
    if first_image and first_image.get("data-source-kind") != SOURCE_KIND:
        missing.append("admin_basemap_renderer_svg_source_kind")
    if source_has_nonstdlib_network:
        missing.append("admin_basemap_renderer_no_nonstdlib_network")

    return {
        "ok": not missing,
        "source_kind": contract.get("source_kind"),
        "zoom": contract.get("zoom"),
        "tile_count": len(tiles),
        "svg_image_count": len(svg_images),
        "tile_url_template": contract.get("tile_url_template"),
        "attribution": contract.get("attribution"),
        "external_network_required": contract.get("external_network_required"),
        "cache_policy": contract.get("cache_policy"),
        "first_tile_url": first_tile.get("url"),
        "first_svg_image_tag": first_image.get("tag"),
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "missing": missing,
    }


def _check_admin_tile_proxy(root: Path) -> dict[str, Any]:
    try:
        from admin_tile_proxy import (
            LOCAL_OSM_TILE_URL_TEMPLATE,
            build_osm_tile_proxy_contract,
            load_or_build_osm_tile_payload,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_tile_proxy_import:{exc}"],
        }

    source_root = root if (root / "admin_tile_proxy.py").exists() else REPO_ROOT
    source = (source_root / "admin_tile_proxy.py").read_text(encoding="utf-8")
    missing: list[str] = []
    contract: dict[str, Any] = {}
    fallback_source = None
    fallback_media_type = None
    cached_source = None
    cached_media_type = None
    fallback_disabled_missing_cache = False

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_root = Path(tmpdir)
            contract = build_osm_tile_proxy_contract(cache_root=cache_root)
            fallback = load_or_build_osm_tile_payload(1, 1, 1, cache_root=cache_root)
            fallback_source = fallback.source
            fallback_media_type = fallback.media_type
            cached_path = cache_root / "2" / "3" / "1.png"
            cached_path.parent.mkdir(parents=True)
            cached_path.write_bytes(b"\x89PNG\r\n\x1a\nrelease-check-tile")
            cached = load_or_build_osm_tile_payload(2, 3, 1, cache_root=cache_root)
            cached_source = cached.source
            cached_media_type = cached.media_type
            try:
                load_or_build_osm_tile_payload(
                    1,
                    1,
                    1,
                    cache_root=cache_root,
                    fallback_enabled=False,
                )
            except FileNotFoundError:
                fallback_disabled_missing_cache = True
    except Exception as exc:
        missing.append(f"admin_tile_proxy_smoke:{exc}")

    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.", "urlopen")
    )
    if contract.get("url_template") != LOCAL_OSM_TILE_URL_TEMPLATE:
        missing.append("admin_tile_proxy_url_template")
    if contract.get("external_network_fetch_allowed") is not False:
        missing.append("admin_tile_proxy_external_fetch")
    if contract.get("downloads_tiles_into_repo") is not False:
        missing.append("admin_tile_proxy_downloads_tiles_into_repo")
    if contract.get("cache_policy") != "local_file_cache_then_offline_fallback":
        missing.append("admin_tile_proxy_cache_policy")
    if fallback_source != "offline_fallback" or fallback_media_type != "image/svg+xml":
        missing.append("admin_tile_proxy_offline_fallback")
    if cached_source != "local_cache" or cached_media_type != "image/png":
        missing.append("admin_tile_proxy_local_cache")
    if not fallback_disabled_missing_cache:
        missing.append("admin_tile_proxy_fallback_disabled_missing_cache")
    if source_has_nonstdlib_network:
        missing.append("admin_tile_proxy_no_nonstdlib_network")

    return {
        "ok": not missing,
        "status": contract.get("status"),
        "url_template": contract.get("url_template"),
        "cache_policy": contract.get("cache_policy"),
        "external_network_fetch_allowed": contract.get("external_network_fetch_allowed"),
        "downloads_tiles_into_repo": contract.get("downloads_tiles_into_repo"),
        "fallback_source": fallback_source,
        "fallback_media_type": fallback_media_type,
        "cached_source": cached_source,
        "cached_media_type": cached_media_type,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "missing": missing,
    }


def _check_admin_tile_cache_builder(root: Path) -> dict[str, Any]:
    try:
        from admin_tile_cache_builder import (
            DEFAULT_TILE_CACHE_CAPACITY_BYTES,
            build_tile_cache_hardware_manifest,
            build_tile_cache_plan,
            load_pretrip_project_route_bbox,
            seed_tile_cache,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_tile_cache_builder_import:{exc}"],
        }

    source_root = root if (root / "admin_tile_cache_builder.py").exists() else REPO_ROOT
    source = (source_root / "admin_tile_cache_builder.py").read_text(encoding="utf-8")
    project_root = (
        root
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
    )
    if not (project_root / "project.json").exists():
        project_root = (
            REPO_ROOT
            / "tests"
            / "fixtures"
            / "pretrip"
            / "projects"
            / "chilai_nanhua_day1"
        )

    missing: list[str] = []
    try:
        bbox = load_pretrip_project_route_bbox(project_root)
        plan = build_tile_cache_plan(bbox)
        manifest = build_tile_cache_hardware_manifest(plan)
        permitted_plan = build_tile_cache_plan(
            bbox,
            min_zoom=5,
            max_zoom=5,
            tile_url_template="https://tiles.permitted.example/{z}/{x}/{y}.png",
        )
        dry_run_summary = seed_tile_cache(
            permitted_plan,
            provider_allows_offline_prefetch=True,
            dry_run=True,
            max_tiles=1,
        )
        public_osm_blocked = False
        try:
            seed_tile_cache(plan, provider_allows_offline_prefetch=True)
        except ValueError:
            public_osm_blocked = True
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_tile_cache_builder_smoke:{exc}"],
        }

    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.")
    )
    source_has_stdlib_network = "urlopen" in source
    if plan.get("status") != "planned_capacity_ok":
        missing.append("admin_tile_cache_builder_plan_status")
    if plan.get("cache_root") != str(Path("~/.cache/scout-fusion/osm-tiles").expanduser()):
        missing.append("admin_tile_cache_builder_cache_root")
    if plan.get("hardware_deploy_target") != "scout_hardware":
        missing.append("admin_tile_cache_builder_hardware_target")
    if plan.get("bbox_expansion_ratio") != 0.5:
        missing.append("admin_tile_cache_builder_bbox_expansion")
    if plan.get("min_zoom") != 5 or plan.get("max_zoom") != 20:
        missing.append("admin_tile_cache_builder_zoom_range")
    if plan.get("capacity_limit_bytes") != DEFAULT_TILE_CACHE_CAPACITY_BYTES:
        missing.append("admin_tile_cache_builder_capacity_limit")
    if plan.get("within_capacity_limit") is not True:
        missing.append("admin_tile_cache_builder_within_capacity")
    if plan.get("source_policy_status") != "public_osm_bulk_download_prohibited":
        missing.append("admin_tile_cache_builder_public_osm_policy")
    if plan.get("bulk_download_allowed") is not False:
        missing.append("admin_tile_cache_builder_public_osm_bulk_allowed")
    if not public_osm_blocked:
        missing.append("admin_tile_cache_builder_public_osm_not_blocked")
    if manifest.get("runtime_tile_url_template") != "/admin/tiles/osm/{z}/{x}/{y}.png":
        missing.append("admin_tile_cache_builder_runtime_template")
    if dry_run_summary.get("status") != "dry_run_ready":
        missing.append("admin_tile_cache_builder_dry_run")
    if source_has_nonstdlib_network:
        missing.append("admin_tile_cache_builder_no_nonstdlib_network")

    return {
        "ok": not missing,
        "status": plan.get("status"),
        "cache_root": plan.get("cache_root"),
        "hardware_deploy_target": plan.get("hardware_deploy_target"),
        "bbox_expansion_ratio": plan.get("bbox_expansion_ratio"),
        "min_zoom": plan.get("min_zoom"),
        "max_zoom": plan.get("max_zoom"),
        "capacity_limit_bytes": plan.get("capacity_limit_bytes"),
        "estimated_total_bytes": plan.get("estimated_total_bytes"),
        "estimated_total_gib": plan.get("estimated_total_gib"),
        "total_tile_count": plan.get("total_tile_count"),
        "within_capacity_limit": plan.get("within_capacity_limit"),
        "source_policy_status": plan.get("source_policy_status"),
        "bulk_download_allowed": plan.get("bulk_download_allowed"),
        "public_osm_blocked": public_osm_blocked,
        "hardware_manifest_status": manifest.get("status"),
        "dry_run_status": dry_run_summary.get("status"),
        "source_has_stdlib_network": source_has_stdlib_network,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "missing": missing,
    }


def _check_admin_local_raster_source(root: Path) -> dict[str, Any]:
    try:
        from admin_local_raster_source import (
            build_local_raster_source_manifest,
            write_local_raster_source_manifest,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_local_raster_source_import:{exc}"],
        }

    source_root = root if (root / "admin_local_raster_source.py").exists() else REPO_ROOT
    source = (source_root / "admin_local_raster_source.py").read_text(encoding="utf-8")
    missing: list[str] = []
    manifest: dict[str, Any] = {}
    written_size = None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_dir = Path(tmpdir) / "manifests"
            manifest_dir.mkdir()
            geotiff_path = manifest_dir / "release_check_wgs84.tiff"
            _write_release_check_geotiff(geotiff_path)
            manifest = build_local_raster_source_manifest(
                geotiff_path,
                project_id="chilai_nanhua_day1",
            )
            output_path = write_local_raster_source_manifest(
                manifest,
                manifest_dir / "release_check.local_raster_source_manifest.json",
            )
            written_size = output_path.stat().st_size
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_local_raster_source_smoke:{exc}"],
        }

    source_has_network = any(
        token in source
        for token in (
            "import requests",
            "requests.",
            "import httpx",
            "httpx.",
            "urlopen",
            "urllib.request",
        )
    )
    georef = manifest.get("georeference", {})
    source_file = manifest.get("source_file", {})
    placement = manifest.get("placement", {})
    if manifest.get("artifact_kind") != "admin_local_raster_source_manifest":
        missing.append("admin_local_raster_source_artifact_kind")
    if manifest.get("source_kind") != "local_geotiff":
        missing.append("admin_local_raster_source_source_kind")
    if manifest.get("layer_id") != "imagery":
        missing.append("admin_local_raster_source_layer")
    if georef.get("status") != "geotiff_wgs84":
        missing.append("admin_local_raster_source_georef_status")
    if georef.get("crs", {}).get("code") != 4326:
        missing.append("admin_local_raster_source_crs")
    if not georef.get("bbox_wgs84"):
        missing.append("admin_local_raster_source_bbox")
    if source_file.get("repo_fixture_write_allowed") is not False:
        missing.append("admin_local_raster_source_repo_fixture_boundary")
    if source_file.get("raw_raster_committed_to_repo_allowed") is not False:
        missing.append("admin_local_raster_source_raw_repo_boundary")
    if manifest.get("external_network_required") is not False:
        missing.append("admin_local_raster_source_external_network")
    if manifest.get("tile_cutting_performed") is not False:
        missing.append("admin_local_raster_source_tile_cutting")
    if placement.get("in_manifest_directory") is not True:
        missing.append("admin_local_raster_source_manifest_dir_warning")
    if not written_size or written_size >= 8 * 1024:
        missing.append("admin_local_raster_source_descriptor_size")
    if source_has_network:
        missing.append("admin_local_raster_source_no_network")

    return {
        "ok": not missing,
        "status": georef.get("status"),
        "source_kind": manifest.get("source_kind"),
        "layer_id": manifest.get("layer_id"),
        "crs_code": georef.get("crs", {}).get("code"),
        "bbox_wgs84": georef.get("bbox_wgs84"),
        "repo_fixture_write_allowed": source_file.get("repo_fixture_write_allowed"),
        "raw_raster_committed_to_repo_allowed": source_file.get(
            "raw_raster_committed_to_repo_allowed"
        ),
        "external_network_required": manifest.get("external_network_required"),
        "tile_cutting_performed": manifest.get("tile_cutting_performed"),
        "placement_in_manifest_directory": placement.get("in_manifest_directory"),
        "written_descriptor_size_bytes": written_size,
        "source_has_network": source_has_network,
        "missing": missing,
    }


def _check_admin_local_raster_tiles(root: Path) -> dict[str, Any]:
    try:
        from admin_local_raster_source import build_local_raster_source_manifest
        from admin_local_raster_tiles import (
            LOCAL_RASTER_TILE_URL_TEMPLATE,
            build_local_raster_tile_proxy_contract,
            build_raster_tile_pyramid_plan,
            cut_raster_tile_pyramid,
            load_or_build_raster_tile_payload,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_local_raster_tiles_import:{exc}"],
        }

    source_root = root if (root / "admin_local_raster_tiles.py").exists() else REPO_ROOT
    source = (source_root / "admin_local_raster_tiles.py").read_text(encoding="utf-8")
    missing: list[str] = []
    plan: dict[str, Any] = {}
    contract: dict[str, Any] = {}
    dry_run: dict[str, Any] = {}
    seed_summary: dict[str, Any] = {}
    payload_source = None
    payload_media_type = None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            geotiff_path = tmp_root / "release_check_wgs84.tiff"
            _write_release_check_geotiff(geotiff_path)
            source_manifest = build_local_raster_source_manifest(
                geotiff_path,
                project_id="chilai_nanhua_day1",
            )
            plan = build_raster_tile_pyramid_plan(
                source_manifest,
                cache_root=tmp_root / "raster-tiles",
                min_zoom=5,
                max_zoom=5,
            )
            contract = build_local_raster_tile_proxy_contract(
                cache_root=tmp_root / "raster-tiles"
            )
            dry_run = cut_raster_tile_pyramid(
                source_manifest,
                plan,
                dry_run=True,
                max_tiles=1,
            )
            seed_summary = cut_raster_tile_pyramid(
                source_manifest,
                plan,
                dry_run=False,
                max_tiles=1,
            )
            written_tiles = sorted((tmp_root / "raster-tiles").glob("**/*.png"))
            if written_tiles:
                relative = written_tiles[0].relative_to(tmp_root / "raster-tiles")
                z, x, filename = relative.parts[-3:]
                payload = load_or_build_raster_tile_payload(
                    "chilai_nanhua_day1",
                    "imagery",
                    z,
                    x,
                    filename.removesuffix(".png"),
                    cache_root=tmp_root / "raster-tiles",
                )
                payload_source = payload.source
                payload_media_type = payload.media_type
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_local_raster_tiles_smoke:{exc}"],
        }

    source_has_network = any(
        token in source
        for token in (
            "import requests",
            "requests.",
            "import httpx",
            "httpx.",
            "urlopen",
            "urllib.request",
        )
    )
    if plan.get("status") != "planned_capacity_ok":
        missing.append("admin_local_raster_tiles_plan_status")
    if plan.get("runtime_tile_url_template") != LOCAL_RASTER_TILE_URL_TEMPLATE:
        missing.append("admin_local_raster_tiles_runtime_template")
    if plan.get("external_network_required") is not False:
        missing.append("admin_local_raster_tiles_external_network")
    if plan.get("downloads_tiles_into_repo") is not False:
        missing.append("admin_local_raster_tiles_downloads_repo")
    if plan.get("raw_raster_committed_to_repo_allowed") is not False:
        missing.append("admin_local_raster_tiles_raw_repo_boundary")
    if dry_run.get("status") != "dry_run_ready" or dry_run.get("tiles_written") != 0:
        missing.append("admin_local_raster_tiles_dry_run")
    if seed_summary.get("status") != "seed_complete" or seed_summary.get("tiles_written") != 1:
        missing.append("admin_local_raster_tiles_seed")
    if contract.get("url_template") != LOCAL_RASTER_TILE_URL_TEMPLATE:
        missing.append("admin_local_raster_tiles_proxy_template")
    if contract.get("external_network_fetch_allowed") is not False:
        missing.append("admin_local_raster_tiles_proxy_external_network")
    if payload_source != "local_cache" or payload_media_type != "image/png":
        missing.append("admin_local_raster_tiles_payload")
    if source_has_network:
        missing.append("admin_local_raster_tiles_no_network")

    return {
        "ok": not missing,
        "status": plan.get("status"),
        "project_id": plan.get("project_id"),
        "layer_id": plan.get("layer_id"),
        "cache_root": plan.get("cache_root"),
        "runtime_tile_url_template": plan.get("runtime_tile_url_template"),
        "min_zoom": plan.get("min_zoom"),
        "max_zoom": plan.get("max_zoom"),
        "total_tile_count": plan.get("total_tile_count"),
        "estimated_total_gib": plan.get("estimated_total_gib"),
        "within_capacity_limit": plan.get("within_capacity_limit"),
        "external_network_required": plan.get("external_network_required"),
        "downloads_tiles_into_repo": plan.get("downloads_tiles_into_repo"),
        "raw_raster_committed_to_repo_allowed": plan.get(
            "raw_raster_committed_to_repo_allowed"
        ),
        "dry_run_status": dry_run.get("status"),
        "seed_status": seed_summary.get("status"),
        "seed_tiles_written": seed_summary.get("tiles_written"),
        "proxy_status": contract.get("status"),
        "payload_source": payload_source,
        "payload_media_type": payload_media_type,
        "source_has_network": source_has_network,
        "missing": missing,
    }


def _write_release_check_geotiff(path: Path) -> None:
    from PIL import Image, TiffImagePlugin

    image = Image.new("RGB", (4, 3), color=(16, 32, 48))
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[33550] = (0.01, 0.02, 0.0)
    tags[33922] = (0.0, 0.0, 0.0, 121.0, 24.0, 0.0)
    tags[34735] = (
        1,
        1,
        0,
        4,
        1024,
        0,
        1,
        2,
        1025,
        0,
        1,
        1,
        2048,
        0,
        1,
        4326,
        2049,
        34737,
        7,
        0,
    )
    tags[34737] = "WGS 84|"
    image.save(path, format="TIFF", tiffinfo=tags)


def _check_admin_weather_overlay(root: Path) -> dict[str, Any]:
    try:
        from admin_weather_overlay import (
            build_pretrip_weather_overlay,
            build_weather_api_runtime_status,
        )
        from pretrip_admin_view import build_pretrip_admin_view
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_weather_overlay_import:{exc}"],
        }

    source_root = root if (root / "admin_weather_overlay.py").exists() else REPO_ROOT
    source = (source_root / "admin_weather_overlay.py").read_text(encoding="utf-8")
    pretrip_page_path = root / "docs" / "admin" / "phase4-pretrip-planning.html"
    if not pretrip_page_path.exists():
        pretrip_page_path = REPO_ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
    after_action_page_path = root / "docs" / "admin" / "phase1-after-action.html"
    if not after_action_page_path.exists():
        after_action_page_path = REPO_ROOT / "docs" / "admin" / "phase1-after-action.html"
    pretrip_page = pretrip_page_path.read_text(encoding="utf-8")
    after_action_page = after_action_page_path.read_text(encoding="utf-8")

    missing: list[str] = []
    try:
        view = build_pretrip_admin_view("chilai_nanhua_day1")
        disabled_status = build_weather_api_runtime_status({})
        ready_status = build_weather_api_runtime_status(
            {
                "SCOUT_WEATHER_API_ENABLED": "true",
                "SCOUT_WEATHER_API_KEY": "release-check-secret",
            }
        )
        overlay = build_pretrip_weather_overlay(
            view["weather"],
            runtime_status=disabled_status,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"admin_weather_overlay_smoke:{exc}"],
        }

    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.", "urlopen")
    )
    if overlay.get("status") != "overlay_ready":
        missing.append("admin_weather_overlay_ready")
    if overlay.get("layer_id") != "weather-api":
        missing.append("admin_weather_overlay_layer_id")
    if overlay.get("provider_mode") != "fixture_backed_local_admin_api":
        missing.append("admin_weather_overlay_provider_mode")
    if overlay.get("external_api_calls_made") is not False:
        missing.append("admin_weather_overlay_external_api_call")
    if overlay.get("raw_payloads_embedded") is not False:
        missing.append("admin_weather_overlay_raw_payloads_embedded")
    if overlay.get("counts", {}).get("card_count") != 3:
        missing.append("admin_weather_overlay_card_count")
    if overlay.get("counts", {}).get("glyph_count") != 2:
        missing.append("admin_weather_overlay_glyph_count")
    if disabled_status.ready is not False:
        missing.append("admin_weather_overlay_disabled_status")
    if ready_status.ready is not True:
        missing.append("admin_weather_overlay_ready_status")
    for fragment in (
        "function renderWeatherOverlay",
        "/admin/pretrip/projects/${PROJECT_ID}/weather-overlay",
        "state.weatherOverlay",
    ):
        if fragment not in pretrip_page:
            missing.append(f"admin_weather_overlay_pretrip_page:{fragment}")
    for fragment in (
        "function renderWeatherOverlayPlaceholder",
        "Weather API overlay",
    ):
        if fragment not in after_action_page:
            missing.append(f"admin_weather_overlay_after_action_page:{fragment}")
    if source_has_nonstdlib_network:
        missing.append("admin_weather_overlay_no_nonstdlib_network")

    return {
        "ok": not missing,
        "status": overlay.get("status"),
        "layer_id": overlay.get("layer_id"),
        "provider_mode": overlay.get("provider_mode"),
        "external_api_calls_made": overlay.get("external_api_calls_made"),
        "raw_payloads_embedded": overlay.get("raw_payloads_embedded"),
        "card_count": overlay.get("counts", {}).get("card_count"),
        "glyph_count": overlay.get("counts", {}).get("glyph_count"),
        "runtime_disabled_ready": disabled_status.ready,
        "runtime_enabled_ready": ready_status.ready,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "missing": missing,
    }


def _check_core_phase4_static_boundaries(root: Path) -> dict[str, Any]:
    unsafe_import_prefixes = {
        "fastapi",
        "flask",
        "httpx",
        "requests",
        "selenium",
        "starlette",
        "uvicorn",
    }
    unsafe_call_names = {
        "Phase1IncidentBridge",
        "MissionGraphRuntime",
        "SafetyRuntimeSession",
        "urlopen",
    }
    allowed_calls_by_file = {
        "admin_tile_cache_builder.py": {"urlopen"},
        "runtime_load_dry_run.py": {"MissionGraphRuntime"},
        "runtime_activation_loader.py": {"SafetyRuntimeSession"},
        "runtime_remote_provider_live_adapter.py": {"urlopen"},
    }
    allowed_imports_by_file = {
        "runtime_stream_transport_api.py": {"fastapi"},
    }
    violations: list[dict[str, str]] = []

    for ref in CORE_PHASE4_PATHS:
        path = root / ref
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=ref)
        except SyntaxError as exc:
            violations.append(
                {
                    "path": ref,
                    "kind": "syntax_error",
                    "fragment": exc.msg,
                }
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".", maxsplit=1)[0]
                    if (
                        module in unsafe_import_prefixes
                        and module not in allowed_imports_by_file.get(ref, set())
                    ):
                        violations.append(
                            {
                                "path": ref,
                                "kind": "unsafe_import",
                                "fragment": alias.name,
                            }
                        )
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                module = module_name.split(".", maxsplit=1)[0]
                if (
                    module in unsafe_import_prefixes
                    and module not in allowed_imports_by_file.get(ref, set())
                ):
                    violations.append(
                        {
                            "path": ref,
                            "kind": "unsafe_import",
                            "fragment": module_name,
                        }
                    )
            elif isinstance(node, ast.Call):
                call_name = _call_name(node.func)
                if (
                    call_name in unsafe_call_names
                    and call_name not in allowed_calls_by_file.get(ref, set())
                ):
                    violations.append(
                        {
                            "path": ref,
                            "kind": "unsafe_call",
                            "fragment": call_name,
                        }
                    )

    return {
        "ok": not violations,
        "files_scanned": sum(1 for ref in CORE_PHASE4_PATHS if (root / ref).exists()),
        "violation_count": len(violations),
        "violations": violations,
        "missing": [
            f"core_phase4_static_boundary:{item['path']}:{item['kind']}:{item['fragment']}"
            for item in violations
        ],
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _check_project_refs(project_path: Path) -> dict[str, Any]:
    missing: list[str] = []
    parse_errors: dict[str, str] = {}
    refs: dict[str, str] = {}
    project: dict[str, Any] = {}

    if not project_path.exists():
        return {
            "ok": False,
            "project": project,
            "refs": refs,
            "parsed_refs": [],
            "parse_errors": {"project_json": "project file missing"},
            "missing": [project_path.as_posix()],
        }

    try:
        project = _load_json(project_path)
    except Exception as exc:
        return {
            "ok": False,
            "project": project,
            "refs": refs,
            "parsed_refs": [],
            "parse_errors": {"project_json": str(exc)},
            "missing": [project_path.as_posix()],
        }

    project_root = project_path.parent
    for key, value in sorted(project.items()):
        if not key.endswith("_ref"):
            continue
        if not isinstance(value, str) or not value:
            missing.append(key)
            continue
        refs[key] = value
        ref_path, ref_error = _resolve_project_ref(project_root, value)
        if ref_error is not None:
            missing.append(f"{key}:{ref_error}")
            continue
        assert ref_path is not None
        if not ref_path.exists():
            missing.append(value)
            continue
        try:
            payload = _load_json(ref_path)
            if ref_path.suffix == ".geojson" and (
                not isinstance(payload, dict) or payload.get("type") != "FeatureCollection"
            ):
                raise ValueError("GeoJSON ref is not a FeatureCollection")
        except Exception as exc:
            parse_errors[value] = str(exc)

    missing.extend(parse_errors)
    return {
        "ok": not missing,
        "project": project,
        "project_id": project.get("project_id"),
        "refs": refs,
        "parsed_refs": sorted(refs.values()),
        "parse_errors": parse_errors,
        "missing": sorted(set(missing)),
    }


def _check_fixture_boundary(project_root: Path) -> dict[str, Any]:
    raw_files: list[str] = []
    oversized_files: list[str] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(project_root).as_posix()
        if path.suffix.lower() in RAW_FIXTURE_SUFFIXES:
            raw_files.append(relative)
        if path.stat().st_size > MAX_FIXTURE_FILE_BYTES:
            oversized_files.append(relative)

    missing = [f"raw_fixture:{path}" for path in raw_files]
    missing.extend(f"oversized_fixture:{path}" for path in oversized_files)
    return {
        "ok": not missing,
        "max_fixture_file_bytes": MAX_FIXTURE_FILE_BYTES,
        "raw_files": raw_files,
        "oversized_files": oversized_files,
        "missing": missing,
    }


def _check_dtm_metadata_only(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    summary = _optional_json(project_root, project.get("dtm_coverage_summary_ref"))
    segment_summary = _optional_json(project_root, project.get("segment_dtm_coverage_ref"))
    missing: list[str] = []

    if not isinstance(summary, dict):
        missing.append(str(project.get("dtm_coverage_summary_ref") or "dtm_coverage_summary_ref"))
    if not isinstance(segment_summary, dict):
        missing.append(str(project.get("segment_dtm_coverage_ref") or "segment_dtm_coverage_ref"))

    raw_payload_keys = _raw_payload_keys(summary) | _raw_payload_keys(segment_summary)
    if raw_payload_keys:
        missing.extend(f"dtm_raw_payload_key:{key}" for key in sorted(raw_payload_keys))

    return {
        "ok": not missing,
        "candidate_tile_count": len(summary.get("candidate_tiles", [])) if isinstance(summary, dict) else 0,
        "segment_count": segment_summary.get("segment_count") if isinstance(segment_summary, dict) else None,
        "raw_payload_keys": sorted(raw_payload_keys),
        "missing": missing,
    }


def _check_route_comparison(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = _optional_json(project_root, project.get("route_comparison_ref"))
    missing: list[str] = []
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "classification": None,
            "bbox_overlaps": None,
            "raw_payload_keys": [],
            "compiled_into_mission_graph": None,
            "missing": [str(project.get("route_comparison_ref") or "route_comparison_ref")],
        }

    raw_payload_keys = _raw_payload_keys(payload)
    notes = payload.get("notes", [])
    note_text = " ".join(str(note) for note in notes)
    classification = payload.get("classification")
    bbox_overlaps = payload.get("bbox_comparison", {}).get("overlaps")
    source_use_treatment = payload.get("source_use_treatment", {})
    if classification != "comparison_only":
        missing.append("route_comparison_classification:comparison_only")
    if bbox_overlaps is not True:
        missing.append("route_comparison_bbox_overlaps:true")
    if "not compiled into MissionGraph" not in note_text:
        missing.append("route_comparison_not_compiled_note")
    expected_treatment = {
        "primary_user_provided_source": True,
        "external_reference_comparison_only": True,
        "redistributable_fixture_allowed": False,
        "derived_summary_only": True,
        "raw_source_versioned": False,
        "authoritative_for_mission": False,
        "compiled_into_mission_graph": False,
    }
    if not isinstance(source_use_treatment, dict):
        missing.append("route_comparison_source_use_treatment_present")
        source_use_treatment = {}
    for key, expected in expected_treatment.items():
        if source_use_treatment.get(key) is not expected:
            missing.append(f"route_comparison_source_use_treatment_{key}:{expected}")
    if raw_payload_keys:
        missing.extend(f"route_comparison_raw_payload_key:{key}" for key in sorted(raw_payload_keys))

    return {
        "ok": not missing,
        "classification": classification,
        "bbox_overlaps": bbox_overlaps,
        "primary_route_name": payload.get("primary_route", {}).get("route_name"),
        "comparison_route_name": payload.get("comparison_route", {}).get("route_name"),
        "raw_payload_keys": sorted(raw_payload_keys),
        "derived_summary_only": source_use_treatment.get("derived_summary_only"),
        "raw_source_versioned": source_use_treatment.get("raw_source_versioned"),
        "authoritative_for_mission": source_use_treatment.get("authoritative_for_mission"),
        "compiled_into_mission_graph": source_use_treatment.get("compiled_into_mission_graph"),
        "missing": missing,
    }


def _check_packages(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    package = _optional_json(project_root, project.get("package_ref"))
    reviewed = _optional_json(project_root, project.get("reviewed_package_ref"))
    missing: list[str] = []

    if package is None:
        missing.append(str(project.get("package_ref") or "package_ref"))
    if reviewed is None:
        missing.append(str(project.get("reviewed_package_ref") or "reviewed_package_ref"))

    package_status = _status(package)
    reviewed_status = _status(reviewed)
    if package_status != "candidate":
        missing.append("package_status:candidate")
    if reviewed_status != "reviewed":
        missing.append("reviewed_package_status:reviewed")

    return {
        "ok": not missing,
        "package_status": package_status,
        "reviewed_package_status": reviewed_status,
        "package_checkpoint_count": len(package.get("checkpoint_candidates", [])) if isinstance(package, dict) else 0,
        "reviewed_checkpoint_count": len(reviewed.get("checkpoint_candidates", [])) if isinstance(reviewed, dict) else 0,
        "missing": missing,
    }


def _check_mission_graphs(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from mission_models import MissionGraph

    missing: list[str] = []
    summaries: dict[str, dict[str, Any]] = {}
    refs = {
        "candidate": project.get("compiled_mission_graph_candidate_ref"),
        "reviewed": project.get("compiled_mission_graph_reviewed_ref"),
    }
    for name, ref in refs.items():
        payload = _optional_json(project_root, ref)
        if payload is None:
            missing.append(str(ref or f"{name}_mission_graph_ref"))
            continue
        try:
            graph = MissionGraph.model_validate(payload)
        except Exception as exc:
            missing.append(f"{ref}:{exc}")
            continue
        summaries[name] = {
            "mission_id": graph.mission_id,
            "checkpoint_count": len(graph.checkpoints),
            "segment_count": len(graph.segments),
            "diversion_point_count": len(graph.diversion_points),
        }
        if not graph.checkpoints or not graph.segments:
            missing.append(f"{ref}:empty_mission_graph")

    return {"ok": not missing, "graphs": summaries, "missing": missing}


def _check_readiness(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    report = _optional_json(project_root, project.get("readiness_report_ref"))
    status = report.get("status") if isinstance(report, dict) else None
    missing = [] if status == "ready" else ["readiness_status:ready"]
    return {
        "ok": not missing,
        "status": status,
        "finding_count": len(report.get("findings", [])) if isinstance(report, dict) else 0,
        "missing": missing,
    }


def _check_timing_measurements(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = _optional_json(project_root, project.get("timing_measurements_ref"))
    measurement_count = len(payload) if isinstance(payload, list) else 0
    expected_count = project.get("timing_measurement_count")
    missing = []
    if measurement_count != expected_count:
        missing.append(f"timing_measurement_count:{expected_count}")
    return {
        "ok": not missing,
        "measurement_count": measurement_count,
        "expected_count": expected_count,
        "missing": missing,
    }


def _check_planned_eta(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = _optional_json(project_root, project.get("planned_eta_ref"))
    missing: list[str] = []
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "estimate_count": 0,
            "expected_count": project.get("planned_eta_estimate_count"),
            "target_eta": None,
            "turn_back_checkpoint_eta": None,
            "team_multiplier_status": None,
            "missing": [str(project.get("planned_eta_ref") or "planned_eta_ref")],
        }

    assumption = payload.get("assumption", {})
    estimate_count = len(payload.get("estimates", []))
    expected_count = project.get("planned_eta_estimate_count")
    if estimate_count != expected_count:
        missing.append(f"planned_eta_estimate_count:{expected_count}")
    if assumption.get("day1_target_node_name") != "天池山莊":
        missing.append("planned_eta_target:天池山莊")
    if assumption.get("turn_back_checkpoint_node_name") != "雲海保線所":
        missing.append("planned_eta_turn_back_checkpoint:雲海保線所")
    if not assumption.get("target_eta"):
        missing.append("planned_eta_target_eta_present")
    if not assumption.get("turn_back_checkpoint_eta"):
        missing.append("planned_eta_turn_back_eta_present")
    if assumption.get("team_multiplier_status") != "not_derived_no_human_stats":
        missing.append("planned_eta_team_multiplier_status:not_derived_no_human_stats")

    return {
        "ok": not missing,
        "estimate_count": estimate_count,
        "expected_count": expected_count,
        "planned_start_time": assumption.get("planned_start_time"),
        "target_eta": assumption.get("target_eta"),
        "turn_back_checkpoint_eta": assumption.get("turn_back_checkpoint_eta"),
        "return_to_entry_eta_if_turn_back_at_checkpoint": assumption.get(
            "return_to_entry_eta_if_turn_back_at_checkpoint"
        ),
        "team_multiplier_status": assumption.get("team_multiplier_status"),
        "missing": missing,
    }


def _check_remote_contact_summary(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = _optional_json(project_root, project.get("remote_contact_summary_ref"))
    missing: list[str] = []
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "audience": None,
            "readiness_status": None,
            "planned_start": None,
            "day1_target_eta": None,
            "turn_back_checkpoint_eta": None,
            "return_to_entry_eta": None,
            "raw_payload_keys": [],
            "forbidden_fragment_count": 0,
            "missing": [str(project.get("remote_contact_summary_ref") or "remote_contact_summary_ref")],
        }

    route = payload.get("route", {})
    readiness = payload.get("readiness", {})
    raw_payload_keys = _raw_payload_keys(payload)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    forbidden_fragments = [
        "<trkpt",
        "<gpx",
        "candidate_tiles",
        "source_artifacts",
        "checkpoint_candidates",
        "segment_candidates",
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        "incident_samples",
        "raw_samples",
    ]
    found_forbidden = [fragment for fragment in forbidden_fragments if fragment in encoded]

    if payload.get("audience") != "remote_contacts":
        missing.append("remote_contact_summary_audience:remote_contacts")
    if readiness.get("status") != "ready":
        missing.append("remote_contact_summary_readiness:ready")
    for key in (
        "planned_start",
        "day1_target_eta",
        "turn_back_checkpoint_eta",
        "return_to_entry_eta",
    ):
        if not route.get(key):
            missing.append(f"remote_contact_summary_route_{key}_present")
    if raw_payload_keys:
        missing.extend(f"remote_contact_summary_raw_payload_key:{key}" for key in sorted(raw_payload_keys))
    if found_forbidden:
        missing.extend(f"remote_contact_summary_forbidden_fragment:{fragment}" for fragment in found_forbidden)

    return {
        "ok": not missing,
        "audience": payload.get("audience"),
        "readiness_status": readiness.get("status"),
        "planned_start": route.get("planned_start"),
        "day1_target_eta": route.get("day1_target_eta"),
        "turn_back_checkpoint_eta": route.get("turn_back_checkpoint_eta"),
        "return_to_entry_eta": route.get("return_to_entry_eta"),
        "raw_payload_keys": sorted(raw_payload_keys),
        "forbidden_fragment_count": len(found_forbidden),
        "missing": missing,
    }


def _check_weather_daylight_evidence(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_weather_daylight import PreTripWeatherDaylightEvidence

    ref = project.get("weather_daylight_evidence_ref")
    payload = _optional_json(project_root, ref)
    missing: list[str] = []
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "evidence_id": None,
            "status": None,
            "validation_status": None,
            "confidence": None,
            "staleness": None,
            "source_ref_count": 0,
            "expected_count": project.get("weather_daylight_evidence_count"),
            "missing": [str(ref or "weather_daylight_evidence_ref")],
        }

    try:
        evidence = PreTripWeatherDaylightEvidence.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "evidence_id": payload.get("evidence_id"),
            "status": payload.get("status"),
            "validation_status": payload.get("validation", {}).get("validation_status"),
            "confidence": payload.get("validation", {}).get("confidence"),
            "staleness": payload.get("validation", {}).get("staleness"),
            "source_ref_count": len(payload.get("source_refs", [])),
            "expected_count": project.get("weather_daylight_evidence_count"),
            "missing": [f"{ref}:{exc}"],
        }

    if project.get("weather_daylight_evidence_count") != 1:
        missing.append("weather_daylight_evidence_count:1")
    if evidence.status != "candidate_only":
        missing.append("weather_daylight_status:candidate_only")
    if evidence.validation.validation_status not in {"needs_review", "human_review_required"}:
        missing.append("weather_daylight_validation:needs_review_or_human_review_required")
    if not evidence.human_review_required:
        missing.append("weather_daylight_human_review_required:true")
    if evidence.authoritative_weather_computed:
        missing.append("weather_daylight_no_authoritative_weather_computed")
    if evidence.external_api_calls_made:
        missing.append("weather_daylight_no_external_api_calls")
    if evidence.route_ref != project.get("route_summary_ref"):
        missing.append("weather_daylight_route_ref_matches_route_summary_ref")
    threshold_policy = evidence.threshold_policy
    if threshold_policy is None:
        missing.append("weather_daylight_threshold_policy_present")
    else:
        if threshold_policy.policy_status != "reference_only":
            missing.append("weather_daylight_threshold_policy_status:reference_only")
        if not threshold_policy.configurable:
            missing.append("weather_daylight_threshold_policy_configurable:true")
        if threshold_policy.rainfall.heavy_rain_1h_mm != 40.0:
            missing.append("weather_daylight_heavy_rain_1h_mm:40")
        if threshold_policy.rainfall.heavy_rain_24h_mm != 80.0:
            missing.append("weather_daylight_heavy_rain_24h_mm:80")
        if threshold_policy.dense_fog.dense_fog_visibility_m != 200.0:
            missing.append("weather_daylight_dense_fog_visibility_m:200")
        if threshold_policy.strong_wind.yellow_avg_wind_mps != 10.8:
            missing.append("weather_daylight_yellow_avg_wind_mps:10.8")
        if threshold_policy.daylight.dark_arrival_warning_margin_min != 60:
            missing.append("weather_daylight_dark_arrival_warning_margin_min:60")

    return {
        "ok": not missing,
        "evidence_id": evidence.evidence_id,
        "status": evidence.status,
        "validation_status": evidence.validation.validation_status,
        "confidence": evidence.validation.confidence,
        "staleness": evidence.validation.staleness,
        "source_ref_count": len(evidence.source_refs),
        "expected_count": project.get("weather_daylight_evidence_count"),
        "threshold_policy_id": threshold_policy.policy_id if threshold_policy else None,
        "threshold_policy_status": threshold_policy.policy_status if threshold_policy else None,
        "threshold_policy_configurable": threshold_policy.configurable if threshold_policy else None,
        "heavy_rain_1h_mm": (
            threshold_policy.rainfall.heavy_rain_1h_mm if threshold_policy else None
        ),
        "dense_fog_visibility_m": (
            threshold_policy.dense_fog.dense_fog_visibility_m if threshold_policy else None
        ),
        "yellow_avg_wind_mps": (
            threshold_policy.strong_wind.yellow_avg_wind_mps if threshold_policy else None
        ),
        "dark_arrival_warning_margin_min": (
            threshold_policy.daylight.dark_arrival_warning_margin_min if threshold_policy else None
        ),
        "missing": missing,
    }


def _check_contour_interpretation_candidates(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_contour_interpretation import ContourInterpretationCandidateSet

    ref = project.get("contour_interpretation_candidates_ref")
    payload = _optional_json(project_root, ref)
    missing: list[str] = []
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "artifact_id": None,
            "status": None,
            "candidate_count": 0,
            "expected_count": project.get("contour_interpretation_candidate_count"),
            "observed_fact_count": 0,
            "raw_payload_keys": [],
            "forbidden_fragment_count": 0,
            "missing": [str(ref or "contour_interpretation_candidates_ref")],
        }

    try:
        candidate_set = ContourInterpretationCandidateSet.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "artifact_id": payload.get("artifact_id"),
            "status": payload.get("status"),
            "candidate_count": len(payload.get("candidates", [])),
            "expected_count": project.get("contour_interpretation_candidate_count"),
            "observed_fact_count": _observed_fact_count(payload),
            "raw_payload_keys": sorted(_raw_payload_keys(payload)),
            "forbidden_fragment_count": 0,
            "missing": [f"{ref}:{exc}"],
        }

    raw_payload_keys = _raw_payload_keys(payload)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    forbidden_fragments = ["data:image", "base64,", "<svg", "<img", "JFIF", "Exif", "PNG"]
    found_forbidden = [fragment for fragment in forbidden_fragments if fragment in encoded]
    observed_fact_count = _observed_fact_count(payload)
    candidate_count = len(candidate_set.candidates)
    expected_count = project.get("contour_interpretation_candidate_count")

    if candidate_count != expected_count:
        missing.append(f"contour_interpretation_candidate_count:{expected_count}")
    if candidate_set.status != "candidate":
        missing.append("contour_interpretation_status:candidate")
    if observed_fact_count:
        missing.append("contour_interpretation_observed_fact_count:0")
    if raw_payload_keys:
        missing.extend(f"contour_interpretation_raw_payload_key:{key}" for key in sorted(raw_payload_keys))
    if found_forbidden:
        missing.extend(f"contour_interpretation_forbidden_fragment:{fragment}" for fragment in found_forbidden)
    if any(not candidate.human_review_required for candidate in candidate_set.candidates):
        missing.append("contour_interpretation_human_review_required:true")
    if any(not candidate.admin_review_required for candidate in candidate_set.candidates):
        missing.append("contour_interpretation_admin_review_required:true")
    if any(candidate.not_observed_fact is not True for candidate in candidate_set.candidates):
        missing.append("contour_interpretation_not_observed_fact:true")
    admin_review_pending_count = sum(
        1
        for candidate in candidate_set.candidates
        if candidate.review_lifecycle.lifecycle_status == "admin_review_pending"
    )
    accepted_planning_assumption_allowed_count = sum(
        1 for candidate in candidate_set.candidates if candidate.accepted_planning_assumption_allowed
    )
    ai_assisted_count = sum(
        1 for candidate in candidate_set.candidates if candidate.interpretation_mode == "ai_assisted"
    )
    if admin_review_pending_count != candidate_count:
        missing.append("contour_interpretation_all_pending_admin_review")
    if accepted_planning_assumption_allowed_count:
        missing.append("contour_interpretation_no_accepted_planning_assumptions")
    if ai_assisted_count == 0:
        missing.append("contour_interpretation_ai_assisted_candidates_present")

    return {
        "ok": not missing,
        "artifact_id": candidate_set.artifact_id,
        "status": candidate_set.status,
        "candidate_count": candidate_count,
        "expected_count": expected_count,
        "observed_fact_count": observed_fact_count,
        "raw_payload_keys": sorted(raw_payload_keys),
        "forbidden_fragment_count": len(found_forbidden),
        "source_artifact_refs": candidate_set.source_artifact_refs,
        "admin_review_pending_count": admin_review_pending_count,
        "accepted_planning_assumption_allowed_count": (
            accepted_planning_assumption_allowed_count
        ),
        "ai_assisted_count": ai_assisted_count,
        "missing": missing,
    }


def _check_brain_seed(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = _optional_json(project_root, project.get("brain_seed_nodes_ref"))
    missing: list[str] = []
    observed_fact_count = 0
    model_interpretation_count = 0
    non_review_gated_interpretation_count = 0
    node_types: list[str] = []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "observed_fact_count": observed_fact_count,
            "model_interpretation_count": model_interpretation_count,
            "non_review_gated_interpretation_count": non_review_gated_interpretation_count,
            "node_types": node_types,
            "missing": [str(project.get("brain_seed_nodes_ref") or "brain_seed_nodes_ref")],
        }

    observed_fact_count = len(payload.get("observed_facts", []))
    node_types = sorted({str(node.get("type")) for node in payload.get("nodes", []) if isinstance(node, dict)})
    observed_fact_count += sum(1 for node in payload.get("nodes", []) if node.get("type") == "ObservedFact")
    model_interpretation_count = len(payload.get("model_interpretations", []))
    non_review_gated_interpretation_count = sum(
        1
        for node in payload.get("model_interpretations", [])
        if node.get("write_policy") != "append_only_requires_review"
    )
    if observed_fact_count:
        missing.append("brain_seed_observed_fact_count:0")
    if non_review_gated_interpretation_count:
        missing.append("brain_seed_model_interpretations_append_only_requires_review")

    return {
        "ok": not missing,
        "observed_fact_count": observed_fact_count,
        "model_interpretation_count": model_interpretation_count,
        "non_review_gated_interpretation_count": non_review_gated_interpretation_count,
        "node_types": node_types,
        "missing": missing,
    }


def _check_planning_skill_audit(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = _optional_json(project_root, project.get("planning_skill_audit_ref"))
    missing: list[str] = []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "record_count": 0,
            "expected_count": project.get("planning_skill_run_count"),
            "node_types": [],
            "automatic_writeback_count": 0,
            "observed_fact_count": 0,
            "missing": [str(project.get("planning_skill_audit_ref") or "planning_skill_audit_ref")],
        }

    records = [record for record in payload.get("records", []) if isinstance(record, dict)]
    expected_count = project.get("planning_skill_run_count")
    node_types = sorted({str(record.get("type")) for record in records if record.get("type")})
    automatic_writeback_count = sum(
        1
        for record in records
        if record.get("preflight_results", {})
        .get("writeback_policy", {})
        .get("automatic_brain_write")
        is True
    )
    observed_fact_count = sum(1 for record in records if record.get("type") == "ObservedFact")

    if len(records) != expected_count:
        missing.append(f"planning_skill_run_count:{expected_count}")
    if node_types != ["SkillRunRecord"]:
        missing.append("planning_skill_audit_node_types:SkillRunRecord")
    if automatic_writeback_count:
        missing.append("planning_skill_audit_automatic_writeback_count:0")
    if observed_fact_count:
        missing.append("planning_skill_audit_observed_fact_count:0")

    return {
        "ok": not missing,
        "record_count": len(records),
        "expected_count": expected_count,
        "node_types": node_types,
        "automatic_writeback_count": automatic_writeback_count,
        "observed_fact_count": observed_fact_count,
        "skill_ids": [
            record.get("skill_id") for record in records if record.get("skill_id")
        ],
        "missing": missing,
    }


def _check_planning_skill_manifest_catalog(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_skill_manifest_catalog import PlanningSkillManifestCatalog

    ref = project.get("planning_skill_manifest_catalog_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "manifest_count": 0,
            "expected_count": project.get("planning_skill_manifest_count"),
            "automatic_brain_write_allowed_count": None,
            "phase1_runtime_mutation_allowed_count": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "planning_skill_manifest_catalog_ref")],
        }

    try:
        catalog = PlanningSkillManifestCatalog.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "manifest_count": len(payload.get("manifests", [])),
            "expected_count": project.get("planning_skill_manifest_count"),
            "automatic_brain_write_allowed_count": None,
            "phase1_runtime_mutation_allowed_count": None,
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    manifest_count = len(catalog.manifests)
    expected_count = project.get("planning_skill_manifest_count")
    automatic_brain_write_allowed_count = sum(
        1
        for manifest in catalog.manifests
        if manifest.brain_writeback_policy.automatic_brain_write_allowed
    )
    phase1_runtime_mutation_allowed_count = sum(
        1
        for manifest in catalog.manifests
        if manifest.runtime_mutation_policy.phase1_runtime_mutation_allowed
    )
    if manifest_count != expected_count:
        missing.append(f"planning_skill_manifest_count:{expected_count}")
    if catalog.raw_payloads_embedded:
        missing.append("planning_skill_manifest_catalog_no_raw_payloads")
    if automatic_brain_write_allowed_count:
        missing.append("planning_skill_manifest_catalog_no_automatic_brain_write")
    if phase1_runtime_mutation_allowed_count:
        missing.append("planning_skill_manifest_catalog_no_phase1_runtime_mutation")
    if any(not manifest.review_requirement.required for manifest in catalog.manifests):
        missing.append("planning_skill_manifest_catalog_review_required")
    if any(not manifest.review_requirement.candidate_outputs_only for manifest in catalog.manifests):
        missing.append("planning_skill_manifest_catalog_candidate_outputs_only")

    return {
        "ok": not missing,
        "manifest_count": manifest_count,
        "expected_count": expected_count,
        "skill_ids": [manifest.skill_id for manifest in catalog.manifests],
        "automatic_brain_write_allowed_count": automatic_brain_write_allowed_count,
        "phase1_runtime_mutation_allowed_count": phase1_runtime_mutation_allowed_count,
        "raw_payloads_embedded": catalog.raw_payloads_embedded,
        "missing": missing,
    }


def _check_poi_readiness_candidates(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_poi_readiness import PoiReadinessCandidateReport

    ref = project.get("poi_readiness_candidates_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "finding_candidate_count": 0,
            "expected_count": project.get("poi_readiness_finding_candidate_count"),
            "warning_candidate_count": 0,
            "blocker_candidate_count": 0,
            "candidate_only": False,
            "missing": [str(ref or "poi_readiness_candidates_ref")],
        }

    try:
        report = PoiReadinessCandidateReport.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "finding_candidate_count": len(payload.get("findings", [])),
            "expected_count": project.get("poi_readiness_finding_candidate_count"),
            "warning_candidate_count": payload.get("counts", {}).get("warning_candidate_count", 0),
            "blocker_candidate_count": payload.get("counts", {}).get("blocker_candidate_count", 0),
            "candidate_only": False,
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    finding_count = len(report.findings)
    expected_count = project.get("poi_readiness_finding_candidate_count")
    if report.status != "candidate_only":
        missing.append("poi_readiness_status:candidate_only")
    if finding_count != expected_count:
        missing.append(f"poi_readiness_finding_candidate_count:{expected_count}")
    if not all(finding.candidate_only for finding in report.findings):
        missing.append("poi_readiness_all_findings_candidate_only")
    if not all(policy.candidate_only for policy in report.policy_candidates):
        missing.append("poi_readiness_all_policies_candidate_only")
    policy_categories = [policy.category for policy in report.policy_candidates]
    if policy_categories != ["route_corridor_poi_coverage"]:
        missing.append("poi_readiness_policy_categories:route_corridor_poi_coverage")
    route_corridor_poi_count = report.counts.get("route_corridor_poi_count", 0)
    if route_corridor_poi_count < 1:
        missing.append("poi_readiness_route_corridor_poi_count:>=1")
    if report.counts.get("blocker_candidate_count", 0) != 0:
        missing.append("poi_readiness_blocker_candidate_count:0")
    primary_policy = report.policy_candidates[0] if report.policy_candidates else None
    if primary_policy is None:
        missing.append("poi_readiness_policy_candidate_present")
    else:
        if primary_policy.corridor_distance_m != 1000.0:
            missing.append("poi_readiness_corridor_distance_m:1000")
        if primary_policy.minimum_poi_count != 1:
            missing.append("poi_readiness_minimum_poi_count:1")
        if primary_policy.severity != "warning":
            missing.append("poi_readiness_policy_severity:warning")

    return {
        "ok": not missing,
        "status": report.status,
        "finding_candidate_count": finding_count,
        "expected_count": expected_count,
        "warning_candidate_count": report.counts.get("warning_candidate_count", 0),
        "blocker_candidate_count": report.counts.get("blocker_candidate_count", 0),
        "policy_candidate_count": len(report.policy_candidates),
        "policy_categories": policy_categories,
        "route_corridor_poi_count": route_corridor_poi_count,
        "corridor_distance_m": primary_policy.corridor_distance_m if primary_policy else None,
        "minimum_poi_count": primary_policy.minimum_poi_count if primary_policy else None,
        "policy_severity": primary_policy.severity if primary_policy else None,
        "candidate_only": all(finding.candidate_only for finding in report.findings)
        and all(policy.candidate_only for policy in report.policy_candidates),
        "missing": missing,
    }


def _check_segment_policy_candidates(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_segment_policy import SegmentPolicyCandidateReport

    ref = project.get("segment_policy_candidates_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "candidate_count": 0,
            "expected_count": project.get("segment_policy_candidate_count"),
            "candidate_only_count": 0,
            "human_review_required_count": 0,
            "requires_daylight_count": 0,
            "raw_payload_keys": [],
            "missing": [str(ref or "segment_policy_candidates_ref")],
        }

    try:
        report = SegmentPolicyCandidateReport.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "candidate_count": len(payload.get("candidates", [])),
            "expected_count": project.get("segment_policy_candidate_count"),
            "candidate_only_count": payload.get("counts", {}).get("candidate_only_count", 0),
            "human_review_required_count": payload.get("counts", {}).get(
                "human_review_required_count", 0
            ),
            "requires_daylight_count": payload.get("counts", {}).get("requires_daylight_count", 0),
            "raw_payload_keys": sorted(_raw_payload_keys(payload)),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    candidate_count = len(report.candidates)
    expected_count = project.get("segment_policy_candidate_count")
    raw_payload_keys = _raw_payload_keys(payload)
    if report.status != "candidate_only":
        missing.append("segment_policy_status:candidate_only")
    if candidate_count != expected_count:
        missing.append(f"segment_policy_candidate_count:{expected_count}")
    if report.counts.get("candidate_only_count") != candidate_count:
        missing.append("segment_policy_candidate_only_count")
    if report.counts.get("human_review_required_count") != candidate_count:
        missing.append("segment_policy_human_review_required_count")
    if report.counts.get("requires_daylight_count") != candidate_count:
        missing.append("segment_policy_requires_daylight_count")
    if any(not candidate.candidate_only for candidate in report.candidates):
        missing.append("segment_policy_all_candidates_candidate_only")
    if any(not candidate.human_review_required for candidate in report.candidates):
        missing.append("segment_policy_all_candidates_human_review_required")
    if any(candidate.compile_boundary != "candidate_only_not_runtime" for candidate in report.candidates):
        missing.append("segment_policy_compile_boundary")
    if raw_payload_keys:
        missing.extend(f"segment_policy_raw_payload_key:{key}" for key in sorted(raw_payload_keys))

    return {
        "ok": not missing,
        "status": report.status,
        "candidate_count": candidate_count,
        "expected_count": expected_count,
        "candidate_only_count": report.counts.get("candidate_only_count", 0),
        "human_review_required_count": report.counts.get("human_review_required_count", 0),
        "requires_daylight_count": report.counts.get("requires_daylight_count", 0),
        "retreat_available_count": report.counts.get("retreat_available_count", 0),
        "signal_expected_count": report.counts.get("signal_expected_count", 0),
        "raw_payload_keys": sorted(raw_payload_keys),
        "missing": missing,
    }


def _check_plan_validation_candidates(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_plan_validation import PreTripPlanValidationCandidateReport

    ref = project.get("plan_validation_candidates_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "finding_candidate_count": 0,
            "expected_count": project.get("plan_validation_finding_candidate_count"),
            "warning_candidate_count": 0,
            "blocker_candidate_count": 0,
            "hard_readiness_status": None,
            "hard_readiness_mutation_allowed": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "plan_validation_candidates_ref")],
        }

    try:
        report = PreTripPlanValidationCandidateReport.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "finding_candidate_count": len(payload.get("findings", [])),
            "expected_count": project.get("plan_validation_finding_candidate_count"),
            "warning_candidate_count": payload.get("counts", {}).get("warning_candidate_count", 0),
            "blocker_candidate_count": payload.get("counts", {}).get("blocker_candidate_count", 0),
            "hard_readiness_status": payload.get("hard_readiness_status"),
            "hard_readiness_mutation_allowed": payload.get("hard_readiness_mutation_allowed"),
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    finding_count = len(report.findings)
    expected_count = project.get("plan_validation_finding_candidate_count")
    if report.status != "candidate_only":
        missing.append("plan_validation_status:candidate_only")
    if finding_count != expected_count:
        missing.append(f"plan_validation_finding_candidate_count:{expected_count}")
    if report.counts.get("finding_candidate_count") != finding_count:
        missing.append("plan_validation_counts_finding_candidate_count")
    if report.hard_readiness_status != "ready":
        missing.append("plan_validation_hard_readiness_status:ready")
    if report.hard_readiness_finding_count != 0:
        missing.append("plan_validation_hard_readiness_finding_count:0")
    if report.hard_readiness_mutation_allowed:
        missing.append("plan_validation_no_hard_readiness_mutation")
    if report.raw_payloads_embedded:
        missing.append("plan_validation_no_raw_payloads_embedded")
    if not all(finding.candidate_only for finding in report.findings):
        missing.append("plan_validation_all_findings_candidate_only")
    if any(finding.hard_readiness_mutation_allowed for finding in report.findings):
        missing.append("plan_validation_no_finding_hard_readiness_mutation")

    return {
        "ok": not missing,
        "status": report.status,
        "finding_candidate_count": finding_count,
        "expected_count": expected_count,
        "warning_candidate_count": report.counts.get("warning_candidate_count", 0),
        "blocker_candidate_count": report.counts.get("blocker_candidate_count", 0),
        "source_ref_count": report.counts.get("source_ref_count", 0),
        "hard_readiness_status": report.hard_readiness_status,
        "hard_readiness_finding_count": report.hard_readiness_finding_count,
        "hard_readiness_mutation_allowed": report.hard_readiness_mutation_allowed,
        "raw_payloads_embedded": report.raw_payloads_embedded,
        "missing": missing,
    }


def _check_runtime_audit_manifest(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_runtime_audit import PreTripRuntimeAuditManifest

    ref = project.get("runtime_audit_manifest_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "comparison_axis_count": 0,
            "expected_axis_count": project.get("runtime_audit_axis_count"),
            "observed_item_count": None,
            "live_comparison_count": None,
            "raw_payload_count": None,
            "missing": [str(ref or "runtime_audit_manifest_ref")],
        }

    try:
        manifest = PreTripRuntimeAuditManifest.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "comparison_axis_count": len(payload.get("axes", [])),
            "expected_axis_count": project.get("runtime_audit_axis_count"),
            "observed_item_count": payload.get("counts", {}).get("observed_item_count"),
            "live_comparison_count": payload.get("counts", {}).get("live_comparison_count"),
            "raw_payload_count": payload.get("counts", {}).get("raw_payload_count"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    axis_count = len(manifest.axes)
    expected_axis_count = project.get("runtime_audit_axis_count")
    if manifest.status != "candidate_only":
        missing.append("runtime_audit_status:candidate_only")
    if axis_count != expected_axis_count:
        missing.append(f"runtime_audit_axis_count:{expected_axis_count}")
    if manifest.counts.get("observed_item_count") != 0:
        missing.append("runtime_audit_observed_item_count:0")
    if manifest.counts.get("live_comparison_count") != 0:
        missing.append("runtime_audit_live_comparison_count:0")
    if manifest.counts.get("raw_payload_count") != 0:
        missing.append("runtime_audit_raw_payload_count:0")
    if manifest.boundary.incident_package_imported:
        missing.append("runtime_audit_no_incident_package_import")
    if manifest.boundary.phase1_runtime_mutation_allowed:
        missing.append("runtime_audit_no_phase1_runtime_mutation")
    if any(axis.comparison_executed for axis in manifest.axes):
        missing.append("runtime_audit_no_executed_comparisons")

    return {
        "ok": not missing,
        "status": manifest.status,
        "comparison_axis_count": axis_count,
        "expected_axis_count": expected_axis_count,
        "planned_ref_count": manifest.counts.get("planned_ref_count", 0),
        "observed_item_count": manifest.counts.get("observed_item_count"),
        "live_comparison_count": manifest.counts.get("live_comparison_count"),
        "raw_payload_count": manifest.counts.get("raw_payload_count"),
        "incident_package_imported": manifest.boundary.incident_package_imported,
        "phase1_runtime_mutation_allowed": manifest.boundary.phase1_runtime_mutation_allowed,
        "missing": missing,
    }


def _check_runtime_handoff_metadata(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_runtime_handoff_metadata import PreTripRuntimeHandoffMetadata

    ref = project.get("runtime_handoff_metadata_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "route_ref_count": 0,
            "expected_route_ref_count": project.get("runtime_handoff_route_ref_count"),
            "runtime_write_count": None,
            "safety_call_count": None,
            "bridge_mutation_count": None,
            "phase1_runtime_mutation_allowed": None,
            "final_runtime_write_allowed": None,
            "missing": [str(ref or "runtime_handoff_metadata_ref")],
        }

    try:
        metadata = PreTripRuntimeHandoffMetadata.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "ok": False,
            "status": payload.get("status"),
            "route_ref_count": counts.get("route_ref_count", 0),
            "expected_route_ref_count": project.get("runtime_handoff_route_ref_count"),
            "runtime_write_count": counts.get("runtime_write_count"),
            "safety_call_count": counts.get("safety_call_count"),
            "bridge_mutation_count": counts.get("bridge_mutation_count"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "final_runtime_write_allowed": boundary.get("final_runtime_write_allowed"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    expected_route_ref_count = project.get("runtime_handoff_route_ref_count")
    if metadata.status != "candidate_metadata_only":
        missing.append("runtime_handoff_status:candidate_metadata_only")
    if metadata.counts.route_ref_count != expected_route_ref_count:
        missing.append(f"runtime_handoff_route_ref_count:{expected_route_ref_count}")
    if metadata.counts.runtime_write_count != 0:
        missing.append("runtime_handoff_runtime_write_count:0")
    if metadata.counts.safety_call_count != 0:
        missing.append("runtime_handoff_safety_call_count:0")
    if metadata.counts.bridge_mutation_count != 0:
        missing.append("runtime_handoff_bridge_mutation_count:0")
    if metadata.boundary.phase1_runtime_mutation_allowed:
        missing.append("runtime_handoff_no_phase1_runtime_mutation")
    if metadata.boundary.safety_api_calls_allowed:
        missing.append("runtime_handoff_no_safety_api_calls")
    if metadata.boundary.bridge_mutation_allowed:
        missing.append("runtime_handoff_no_bridge_mutation")
    if metadata.boundary.final_runtime_write_allowed:
        missing.append("runtime_handoff_no_final_runtime_write")
    if metadata.boundary.live_runtime_read_allowed:
        missing.append("runtime_handoff_no_live_runtime_read")
    if metadata.boundary.phase2_writeback_allowed:
        missing.append("runtime_handoff_no_phase2_writeback")
    if metadata.boundary.raw_payloads_embedded:
        missing.append("runtime_handoff_no_raw_payloads")

    return {
        "ok": not missing,
        "status": metadata.status,
        "plan_version_id": metadata.plan_version_id,
        "readiness_ref_count": metadata.counts.readiness_ref_count,
        "route_ref_count": metadata.counts.route_ref_count,
        "expected_route_ref_count": expected_route_ref_count,
        "route_source_count": metadata.counts.route_source_count,
        "runtime_write_count": metadata.counts.runtime_write_count,
        "safety_call_count": metadata.counts.safety_call_count,
        "bridge_mutation_count": metadata.counts.bridge_mutation_count,
        "phase1_runtime_mutation_allowed": (
            metadata.boundary.phase1_runtime_mutation_allowed
        ),
        "safety_api_calls_allowed": metadata.boundary.safety_api_calls_allowed,
        "bridge_mutation_allowed": metadata.boundary.bridge_mutation_allowed,
        "final_runtime_write_allowed": metadata.boundary.final_runtime_write_allowed,
        "live_runtime_read_allowed": metadata.boundary.live_runtime_read_allowed,
        "phase2_writeback_allowed": metadata.boundary.phase2_writeback_allowed,
        "raw_payloads_embedded": metadata.boundary.raw_payloads_embedded,
        "missing": missing,
    }


def _check_phase45_departure_runtime_handoff(root: Path) -> dict[str, Any]:
    try:
        from pretrip_departure_gate import build_chilai_departure_gate_manifest
        from pretrip_departure_gate_resolution import (
            apply_departure_gate_resolutions,
            build_chilai_warning_resolution_log,
        )
        from pretrip_final_mission_graph import (
            build_chilai_final_mission_graph_artifact,
        )
        from pretrip_runtime_export import build_runtime_export_bundle_manifest
        from pretrip_runtime_artifact_resolution import (
            build_runtime_artifact_resolution_manifest,
        )
        from pretrip_runtime_activation_preflight import (
            build_runtime_activation_preflight_report,
        )
        from pretrip_runtime_activation_request import build_runtime_activation_request
        from runtime_activation_loader import (
            RuntimeLifecycleAction,
            activate_runtime_export,
            apply_runtime_lifecycle_control,
            process_runtime_observation_batch,
            request_runtime_stream_start,
            start_runtime_observing,
        )
        from runtime_load_dry_run import build_runtime_load_dry_run_report
        from safety_models import Observation
        from pretrip_review_profiles import (
            ReviewProfileId,
            build_chilai_review_context,
            get_baseline_hard_blocker_catalog,
            get_planning_review_profiles,
            select_planning_review_profile,
        )
        from pretrip_runtime_handoff import build_runtime_handoff_manifest_from_final_graph
    except Exception as exc:
        return {
            "ok": False,
            "selected_profile": None,
            "route_classes": [],
            "departure_gate_status": None,
            "departure_gate_warning_count": None,
            "departure_gate_blocker_count": None,
            "runtime_handoff_boundary_ok": None,
            "missing": [f"phase45_import:{exc}"],
        }

    missing: list[str] = []
    try:
        profiles = get_planning_review_profiles()
        hard_blocker_catalog = get_baseline_hard_blocker_catalog()
        context = build_chilai_review_context(root)
        selection = select_planning_review_profile(context, ReviewProfileId.QUICK)
        departure_gate = build_chilai_departure_gate_manifest(root)
        resolution_log = build_chilai_warning_resolution_log(
            departure_gate,
            reviewer_alias="release-check",
            decided_at="2026-05-18T00:05:00+08:00",
        )
        resolved_departure_gate = apply_departure_gate_resolutions(
            departure_gate,
            resolution_log,
            approved_by="release-check",
            approved_at="2026-05-18T00:10:00+08:00",
        )
        final_mission_graph = build_chilai_final_mission_graph_artifact(
            root,
            resolved_departure_gate,
        )
        handoff = build_runtime_handoff_manifest_from_final_graph(
            resolved_departure_gate,
            final_mission_graph,
            handoff_id="handoff.phase45.release_check.v0",
            approved_by="release-check",
            approved_at="2026-05-18T00:15:00+08:00",
            handoff_target={
                "target_id": "runtime-node.release-check",
                "target_kind": "runtime_export",
                "target_profile": "phase1-field-runtime.v0",
            },
            rollback_reference={
                "rollback_id": "rollback.phase45.release_check.v0",
                "rollback_policy": "Keep previous immutable handoff manifest.",
            },
        )
        runtime_export = build_runtime_export_bundle_manifest(
            final_mission_graph,
            handoff,
            export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
        )
        runtime_artifact_resolution = build_runtime_artifact_resolution_manifest(
            runtime_export,
            final_mission_graph,
            runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
            resolved=False,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            export_root = Path(temp_dir) / runtime_export.export_id
            export_root.mkdir()
            (export_root / "mission_graph.json").write_text(
                _canonical_json_text(
                    final_mission_graph.mission_graph.model_dump(mode="json")
                ),
                encoding="utf-8",
            )
            (export_root / "runtime_handoff_manifest.json").write_text(
                _canonical_json_text(handoff.model_dump(mode="json")),
                encoding="utf-8",
            )
            (export_root / "runtime_export_manifest.json").write_text(
                runtime_export.to_json(),
                encoding="utf-8",
            )
            (export_root / "runtime_artifact_resolution_manifest.json").write_text(
                runtime_artifact_resolution.to_json(),
                encoding="utf-8",
            )
            runtime_activation_preflight = build_runtime_activation_preflight_report(
                export_root
            )
            blocked_preflight_request_rejected = False
            try:
                build_runtime_activation_request(
                    runtime_activation_preflight,
                    request_id="runtime_activation_request.phase45.release_check.blocked.v0",
                    requested_by="release-check",
                    requested_at="2026-05-18T00:25:00+08:00",
                    request_reason="Release check verifies blocked preflight cannot request activation.",
                )
            except ValueError:
                blocked_preflight_request_rejected = True

            route_payload = _release_check_tiny_gpx()
            route_path = export_root / "route_artifacts" / "chilai_nanhua_day1.gpx"
            route_path.parent.mkdir(parents=True)
            route_path.write_text(route_payload, encoding="utf-8")
            ready_runtime_artifact_resolution = (
                build_runtime_artifact_resolution_manifest(
                    runtime_export,
                    final_mission_graph,
                    runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
                    sha256=_sha256_text(route_payload),
                    resolved=True,
                )
            )
            (export_root / "runtime_artifact_resolution_manifest.json").write_text(
                ready_runtime_artifact_resolution.to_json(),
                encoding="utf-8",
            )
            runtime_activation_ready_preflight = (
                build_runtime_activation_preflight_report(export_root)
            )
            runtime_activation_request = build_runtime_activation_request(
                runtime_activation_ready_preflight,
                request_id="runtime_activation_request.phase45.release_check.v0",
                requested_by="release-check",
                requested_at="2026-05-18T00:30:00+08:00",
                request_reason="Release check requests Phase 1 runtime load for a ready export.",
            )
            (export_root / "runtime_activation_request.json").write_text(
                runtime_activation_request.to_json(),
                encoding="utf-8",
            )
            runtime_load_dry_run = build_runtime_load_dry_run_report(export_root)
            runtime_activation_result = activate_runtime_export(
                export_root,
                Path(temp_dir) / "runtime_state",
                activation_id="runtime_activation.phase45.release_check.v0",
                activated_by="release-check",
                activated_at="2026-05-18T00:35:00+08:00",
                activation_reason="Release check verifies loaded_not_observing Phase 1 runtime activation.",
            )
            runtime_observing_result = start_runtime_observing(
                runtime_activation_result,
                Path(temp_dir) / "runtime_state",
                Observation(
                    timestamp=0.0,
                    source="release_check_initial_fix",
                    lat=24.0,
                    lon=121.0,
                    elevation_m=1000.0,
                    gps_horizontal_accuracy_m=8.0,
                    raw={"sensorlog": {"loggingTime": "2026-05-08T00:00:00Z"}},
                ),
                observing_id="runtime_observing.phase45.release_check.v0",
                started_by="release-check",
                started_at="2026-05-18T00:40:00+08:00",
                start_reason="Release check verifies first observation starts observing state.",
            )
            runtime_observation_batch_result = process_runtime_observation_batch(
                runtime_observing_result,
                Path(temp_dir) / "runtime_state",
                [
                    Observation(
                        timestamp=60.0,
                        source="release_check_watch_batch",
                        lat=24.00001,
                        lon=121.00001,
                        elevation_m=1001.0,
                        gps_horizontal_accuracy_m=9.0,
                        raw={"sensorlog": {"loggingTime": "2026-05-08T00:01:00Z"}},
                    ),
                    Observation(
                        timestamp=120.0,
                        source="release_check_watch_batch",
                        lat=24.00002,
                        lon=121.00002,
                        elevation_m=1002.0,
                        gps_horizontal_accuracy_m=10.0,
                        raw={"sensorlog": {"loggingTime": "2026-05-08T00:02:00Z"}},
                    ),
                ],
                batch_id="runtime_observation_batch.phase45.release_check.v0",
                processed_by="release-check",
                processed_at="2026-05-18T00:42:00+08:00",
                process_reason="Release check verifies bounded observation batch processing.",
            )
            runtime_stream_guard_result = request_runtime_stream_start(
                runtime_observation_batch_result,
                Path(temp_dir) / "runtime_state",
                stream_request_id="runtime_stream_guard.phase45.release_check.v0",
                stream_source_kind="watch_sensor_stream",
                requested_by="release-check",
                requested_at="2026-05-18T00:43:00+08:00",
                request_reason="Release check verifies continuous stream guard remains blocked.",
            )
            runtime_lifecycle_pause_result = apply_runtime_lifecycle_control(
                runtime_observation_batch_result,
                Path(temp_dir) / "runtime_state",
                action=RuntimeLifecycleAction.PAUSE,
                control_id="runtime_lifecycle.pause.phase45.release_check.v0",
                controlled_by="release-check",
                controlled_at="2026-05-18T00:45:00+08:00",
                control_reason="Release check verifies runtime pause transition.",
            )
            runtime_paused_stream_guard_result = request_runtime_stream_start(
                runtime_lifecycle_pause_result,
                Path(temp_dir) / "runtime_state",
                stream_request_id="runtime_stream_guard.paused.phase45.release_check.v0",
                stream_source_kind="watch_sensor_stream",
                requested_by="release-check",
                requested_at="2026-05-18T00:47:00+08:00",
                request_reason="Release check verifies paused stream requests remain blocked.",
            )
            runtime_lifecycle_resume_result = apply_runtime_lifecycle_control(
                runtime_lifecycle_pause_result,
                Path(temp_dir) / "runtime_state",
                action=RuntimeLifecycleAction.RESUME,
                control_id="runtime_lifecycle.resume.phase45.release_check.v0",
                controlled_by="release-check",
                controlled_at="2026-05-18T00:50:00+08:00",
                control_reason="Release check verifies runtime resume transition.",
            )
            runtime_lifecycle_end_result = apply_runtime_lifecycle_control(
                runtime_lifecycle_resume_result,
                Path(temp_dir) / "runtime_state",
                action=RuntimeLifecycleAction.END,
                control_id="runtime_lifecycle.end.phase45.release_check.v0",
                controlled_by="release-check",
                controlled_at="2026-05-18T00:55:00+08:00",
                control_reason="Release check verifies runtime end transition.",
            )
            runtime_ended_stream_guard_result = request_runtime_stream_start(
                runtime_lifecycle_end_result,
                Path(temp_dir) / "runtime_state",
                stream_request_id="runtime_stream_guard.ended.phase45.release_check.v0",
                stream_source_kind="watch_sensor_stream",
                requested_by="release-check",
                requested_at="2026-05-18T00:57:00+08:00",
                request_reason="Release check verifies terminal stream requests remain blocked.",
            )
            runtime_lifecycle_abort_result = apply_runtime_lifecycle_control(
                runtime_observing_result,
                Path(temp_dir) / "runtime_state",
                action=RuntimeLifecycleAction.ABORT,
                control_id="runtime_lifecycle.abort.phase45.release_check.v0",
                controlled_by="release-check",
                controlled_at="2026-05-18T01:00:00+08:00",
                control_reason="Release check verifies runtime abort transition.",
            )
    except Exception as exc:
        return {
            "ok": False,
            "selected_profile": None,
            "route_classes": [],
            "departure_gate_status": None,
            "departure_gate_warning_count": None,
            "departure_gate_blocker_count": None,
            "runtime_handoff_boundary_ok": None,
            "missing": [f"phase45_build:{exc}"],
        }

    route_classes = [
        route_class.value
        for route_class in selection.route_classification.route_classes
    ]
    finding_ids = [finding.finding_id for finding in departure_gate.findings]
    raw_payload_keys = sorted(
        _raw_payload_keys(departure_gate.model_dump(mode="json"))
        | _raw_payload_keys(final_mission_graph.model_dump(mode="json"))
        | _raw_payload_keys(handoff.model_dump(mode="json"))
        | _raw_payload_keys(runtime_export.model_dump(mode="json"))
        | _raw_payload_keys(runtime_artifact_resolution.model_dump(mode="json"))
        | _raw_payload_keys(runtime_activation_preflight.model_dump(mode="json"))
        | _raw_payload_keys(ready_runtime_artifact_resolution.model_dump(mode="json"))
        | _raw_payload_keys(runtime_activation_ready_preflight.model_dump(mode="json"))
        | _raw_payload_keys(runtime_activation_request.model_dump(mode="json"))
        | _raw_payload_keys(runtime_load_dry_run.model_dump(mode="json"))
        | _raw_payload_keys(
            runtime_activation_result.activation_record.model_dump(mode="json")
            if runtime_activation_result.activation_record is not None
            else runtime_activation_result.blocked_report.model_dump(mode="json")
            if runtime_activation_result.blocked_report is not None
            else {}
        )
        | _raw_payload_keys(
            runtime_observing_result.observation_start_record.model_dump(mode="json")
        )
        | _raw_payload_keys(
            runtime_observation_batch_result.observation_batch_record.model_dump(mode="json")
        )
        | _raw_payload_keys(runtime_stream_guard_result.stream_guard_record.model_dump(mode="json"))
        | _raw_payload_keys(
            runtime_paused_stream_guard_result.stream_guard_record.model_dump(mode="json")
        )
        | _raw_payload_keys(
            runtime_ended_stream_guard_result.stream_guard_record.model_dump(mode="json")
        )
        | _raw_payload_keys(runtime_lifecycle_pause_result.lifecycle_record.model_dump(mode="json"))
        | _raw_payload_keys(runtime_lifecycle_resume_result.lifecycle_record.model_dump(mode="json"))
        | _raw_payload_keys(runtime_lifecycle_end_result.lifecycle_record.model_dump(mode="json"))
        | _raw_payload_keys(runtime_lifecycle_abort_result.lifecycle_record.model_dump(mode="json"))
    )

    if set(profiles) != {
        ReviewProfileId.QUICK,
        ReviewProfileId.GUIDED,
        ReviewProfileId.EXPEDITION,
    }:
        missing.append("phase45_profiles_quick_guided_expedition")
    if any(blocker.override_allowed for blocker in hard_blocker_catalog.blockers):
        missing.append("phase45_hard_blockers_not_overrideable")
    if selection.selected_profile_id != ReviewProfileId.QUICK:
        missing.append("phase45_chilai_quick_review_allowed")
    if "deep_mountain_out_and_back" not in route_classes:
        missing.append("phase45_chilai_deep_mountain_out_and_back")
    if selection.hard_blockers:
        missing.append("phase45_chilai_no_hard_blockers")
    if departure_gate.status != "hold":
        missing.append("phase45_departure_gate_status_hold_until_warnings_resolved")
    if departure_gate.approval.approval_granted:
        missing.append("phase45_departure_gate_no_implicit_approval")
    if departure_gate.approval.final_mission_graph_generation_allowed:
        missing.append("phase45_no_final_mission_graph_before_gate_pass")
    if departure_gate.boundary.runtime_handoff_allowed:
        missing.append("phase45_gate_does_not_handoff_runtime")
    if departure_gate.counts.blocker_count != 0:
        missing.append("phase45_departure_gate_no_blockers_for_current_fixture")
    if departure_gate.counts.warning_count < 1:
        missing.append("phase45_departure_gate_surfaces_warnings")
    if len(finding_ids) != len(set(finding_ids)):
        missing.append("phase45_departure_gate_unique_finding_ids")
    if resolution_log.counts.resolution_count != departure_gate.counts.warning_count:
        missing.append("phase45_resolution_count_matches_warning_count")
    if resolution_log.counts.blocker_resolution_attempt_count != 0:
        missing.append("phase45_resolution_no_blocker_attempts")
    if not resolution_log.boundary.local_workspace_only:
        missing.append("phase45_resolution_local_workspace_only")
    if resolution_log.boundary.repo_fixture_write_allowed:
        missing.append("phase45_resolution_no_repo_fixture_write")
    if resolved_departure_gate.status != "passed":
        missing.append("phase45_resolved_gate_passed")
    if not resolved_departure_gate.approval.approval_granted:
        missing.append("phase45_resolved_gate_approval_granted")
    if not resolved_departure_gate.approval.final_mission_graph_generation_allowed:
        missing.append("phase45_resolved_gate_allows_final_mission_graph")
    if resolved_departure_gate.boundary.runtime_handoff_allowed:
        missing.append("phase45_resolved_gate_no_runtime_handoff")
    if resolved_departure_gate.counts.unresolved_warning_count != 0:
        missing.append("phase45_resolved_gate_no_unresolved_warnings")
    if resolved_departure_gate.counts.blocker_count != 0:
        missing.append("phase45_resolved_gate_no_blockers")
    if final_mission_graph.status != "finalized":
        missing.append("phase45_final_mission_graph_finalized")
    if final_mission_graph.departure_approval_id != resolved_departure_gate.approval.approval_id:
        missing.append("phase45_final_mission_graph_uses_resolved_approval")
    if final_mission_graph.mission_graph.route_source != "artifact:gpx:chilai_nanhua_day1":
        missing.append("phase45_final_mission_graph_sanitized_route_source")
    if final_mission_graph.counts.checkpoint_count != 11:
        missing.append("phase45_final_mission_graph_checkpoint_count")
    if final_mission_graph.counts.segment_count != 10:
        missing.append("phase45_final_mission_graph_segment_count")
    if final_mission_graph.counts.diversion_point_count != 1:
        missing.append("phase45_final_mission_graph_diversion_point_count")
    if final_mission_graph.counts.runtime_write_count != 0:
        missing.append("phase45_final_mission_graph_no_runtime_write")
    if final_mission_graph.counts.safety_call_count != 0:
        missing.append("phase45_final_mission_graph_no_safety_call")
    if final_mission_graph.counts.phase2_writeback_count != 0:
        missing.append("phase45_final_mission_graph_no_phase2_writeback")
    if not final_mission_graph.boundary.generated_after_departure_gate_passed:
        missing.append("phase45_final_mission_graph_after_gate_pass")
    if final_mission_graph.boundary.planning_workspace_dependency_allowed:
        missing.append("phase45_final_mission_graph_no_planning_workspace_dependency")
    if final_mission_graph.boundary.runtime_handoff_performed:
        missing.append("phase45_final_mission_graph_no_runtime_handoff")
    if final_mission_graph.boundary.phase1_runtime_mutation_allowed:
        missing.append("phase45_final_mission_graph_no_phase1_runtime_mutation")
    if final_mission_graph.boundary.safety_api_calls_allowed:
        missing.append("phase45_final_mission_graph_no_safety_api_calls")
    if final_mission_graph.boundary.phase2_writeback_allowed:
        missing.append("phase45_final_mission_graph_no_phase2_writeback")
    if final_mission_graph.boundary.raw_payloads_embedded:
        missing.append("phase45_final_mission_graph_no_raw_payloads")
    if handoff.package.sha256 != final_mission_graph.source_package_ref.sha256:
        missing.append("phase45_handoff_package_hash_matches_final_graph")
    if handoff.mission_graph.version != final_mission_graph.mission_graph_version:
        missing.append("phase45_handoff_mission_graph_version_matches_final_graph")
    if handoff.mission_graph.sha256 != final_mission_graph.final_mission_graph_sha256:
        missing.append("phase45_handoff_mission_graph_hash_matches_final_graph")
    if handoff.departure_approval_id != final_mission_graph.departure_approval_id:
        missing.append("phase45_handoff_departure_approval_matches_final_graph")
    if handoff.package.sha256 == "a" * 64 or handoff.mission_graph.sha256 == "b" * 64:
        missing.append("phase45_handoff_no_dummy_hashes")
    if runtime_export.status != "exported_not_activated":
        missing.append("phase45_runtime_export_not_activated")
    if runtime_export.mission_graph_sha256 != final_mission_graph.final_mission_graph_sha256:
        missing.append("phase45_runtime_export_final_graph_hash")
    if runtime_export.handoff_id != handoff.handoff_id:
        missing.append("phase45_runtime_export_handoff_id")
    if runtime_export.counts.runtime_file_write_count != 2:
        missing.append("phase45_runtime_export_file_write_count")
    if runtime_export.counts.live_runtime_activation_count != 0:
        missing.append("phase45_runtime_export_no_live_activation")
    if runtime_export.counts.safety_api_call_count != 0:
        missing.append("phase45_runtime_export_no_safety_api_call")
    if runtime_export.counts.phase1_live_session_mutation_count != 0:
        missing.append("phase45_runtime_export_no_live_session_mutation")
    if runtime_export.boundary.live_runtime_activation_allowed:
        missing.append("phase45_runtime_export_activation_closed")
    if runtime_export.boundary.phase1_live_session_mutation_allowed:
        missing.append("phase45_runtime_export_live_session_closed")
    if runtime_export.boundary.safety_api_calls_allowed:
        missing.append("phase45_runtime_export_safety_api_closed")
    if runtime_export.boundary.raw_payloads_embedded:
        missing.append("phase45_runtime_export_no_raw_payloads")
    if runtime_artifact_resolution.route_source_ref != final_mission_graph.mission_graph.route_source:
        missing.append("phase45_runtime_artifact_resolution_route_source")
    if runtime_artifact_resolution.export_id != runtime_export.export_id:
        missing.append("phase45_runtime_artifact_resolution_export_id")
    if runtime_artifact_resolution.mission_graph_sha256 != final_mission_graph.final_mission_graph_sha256:
        missing.append("phase45_runtime_artifact_resolution_final_graph_hash")
    if runtime_artifact_resolution.counts.artifact_resolution_count != 1:
        missing.append("phase45_runtime_artifact_resolution_count")
    if runtime_artifact_resolution.counts.resolved_count != 0:
        missing.append("phase45_runtime_artifact_resolution_no_repo_resolution")
    if runtime_artifact_resolution.counts.missing_count != 1:
        missing.append("phase45_runtime_artifact_resolution_missing_required_route")
    if runtime_artifact_resolution.counts.raw_payload_copy_count != 0:
        missing.append("phase45_runtime_artifact_resolution_no_route_payload_copy")
    if not runtime_artifact_resolution.boundary.metadata_only:
        missing.append("phase45_runtime_artifact_resolution_metadata_only")
    if runtime_artifact_resolution.boundary.raw_payloads_embedded:
        missing.append("phase45_runtime_artifact_resolution_no_raw_payloads")
    if runtime_artifact_resolution.boundary.route_payload_copy_allowed:
        missing.append("phase45_runtime_artifact_resolution_no_route_payload_copy_allowed")
    if runtime_artifact_resolution.boundary.live_runtime_activation_allowed:
        missing.append("phase45_runtime_artifact_resolution_no_live_activation")
    if runtime_artifact_resolution.boundary.phase1_live_session_mutation_allowed:
        missing.append("phase45_runtime_artifact_resolution_no_live_session_mutation")
    if runtime_artifact_resolution.boundary.safety_api_calls_allowed:
        missing.append("phase45_runtime_artifact_resolution_no_safety_api")
    if not runtime_artifact_resolution.boundary.missing_required_artifact_blocks_activation:
        missing.append("phase45_runtime_artifact_resolution_missing_blocks_activation")
    if runtime_activation_preflight.status != "activation_blocked":
        missing.append("phase45_runtime_activation_preflight_blocks_without_route")
    if runtime_activation_preflight.activation_ready:
        missing.append("phase45_runtime_activation_preflight_not_ready_without_route")
    if runtime_activation_preflight.activation_performed:
        missing.append("phase45_runtime_activation_preflight_no_activation")
    if runtime_activation_preflight.counts.blocker_count != 1:
        missing.append("phase45_runtime_activation_preflight_blocker_count")
    if runtime_activation_preflight.counts.live_runtime_activation_count != 0:
        missing.append("phase45_runtime_activation_preflight_no_live_activation_count")
    if runtime_activation_preflight.counts.safety_api_call_count != 0:
        missing.append("phase45_runtime_activation_preflight_no_safety_api_call")
    if runtime_activation_preflight.counts.phase1_live_session_mutation_count != 0:
        missing.append("phase45_runtime_activation_preflight_no_live_session_mutation")
    if runtime_activation_preflight.counts.phase2_writeback_count != 0:
        missing.append("phase45_runtime_activation_preflight_no_phase2_writeback")
    if not runtime_activation_preflight.boundary.preflight_only:
        missing.append("phase45_runtime_activation_preflight_only")
    if runtime_activation_preflight.boundary.live_runtime_activation_allowed:
        missing.append("phase45_runtime_activation_preflight_activation_closed")
    if runtime_activation_preflight.boundary.phase1_live_session_mutation_allowed:
        missing.append("phase45_runtime_activation_preflight_live_session_closed")
    if runtime_activation_preflight.boundary.safety_api_calls_allowed:
        missing.append("phase45_runtime_activation_preflight_safety_api_closed")
    if runtime_activation_preflight.boundary.phase2_writeback_allowed:
        missing.append("phase45_runtime_activation_preflight_phase2_writeback_closed")
    if not runtime_activation_preflight.boundary.requires_explicit_phase1_activation:
        missing.append("phase45_runtime_activation_preflight_requires_explicit_activation")
    if not blocked_preflight_request_rejected:
        missing.append("phase45_runtime_activation_request_rejects_blocked_preflight")
    if ready_runtime_artifact_resolution.counts.resolved_count != 1:
        missing.append("phase45_ready_runtime_artifact_resolution_resolved")
    if runtime_activation_ready_preflight.status != "activation_ready":
        missing.append("phase45_runtime_activation_ready_preflight_ready_status")
    if not runtime_activation_ready_preflight.activation_ready:
        missing.append("phase45_runtime_activation_ready_preflight_ready")
    if runtime_activation_ready_preflight.counts.blocker_count != 0:
        missing.append("phase45_runtime_activation_ready_preflight_no_blockers")
    if runtime_activation_ready_preflight.counts.route_point_count != 2:
        missing.append("phase45_runtime_activation_ready_preflight_route_points")
    if runtime_activation_request.status != "requested_not_activated":
        missing.append("phase45_runtime_activation_request_status")
    if not runtime_activation_request.activation_requested:
        missing.append("phase45_runtime_activation_request_requested")
    if runtime_activation_request.activation_performed:
        missing.append("phase45_runtime_activation_request_not_performed")
    if runtime_activation_request.source.preflight_report_id != runtime_activation_ready_preflight.report_id:
        missing.append("phase45_runtime_activation_request_preflight_ref")
    if runtime_activation_request.export_id != runtime_export.export_id:
        missing.append("phase45_runtime_activation_request_export_id")
    if runtime_activation_request.mission_graph_sha256 != runtime_export.mission_graph_sha256:
        missing.append("phase45_runtime_activation_request_mission_graph_hash")
    if runtime_activation_request.counts.preflight_blocker_count != 0:
        missing.append("phase45_runtime_activation_request_no_preflight_blockers")
    if runtime_activation_request.counts.runtime_activation_request_count != 1:
        missing.append("phase45_runtime_activation_request_count")
    if runtime_activation_request.counts.live_runtime_activation_count != 0:
        missing.append("phase45_runtime_activation_request_no_live_activation")
    if runtime_activation_request.counts.safety_api_call_count != 0:
        missing.append("phase45_runtime_activation_request_no_safety_api")
    if runtime_activation_request.counts.phase1_live_session_mutation_count != 0:
        missing.append("phase45_runtime_activation_request_no_live_session_mutation")
    if runtime_activation_request.counts.phase2_writeback_count != 0:
        missing.append("phase45_runtime_activation_request_no_phase2_writeback")
    if not runtime_activation_request.boundary.request_artifact_only:
        missing.append("phase45_runtime_activation_request_artifact_only")
    if not runtime_activation_request.boundary.requires_activation_ready_preflight:
        missing.append("phase45_runtime_activation_request_requires_ready_preflight")
    if runtime_activation_request.boundary.phase4_runtime_load_allowed:
        missing.append("phase45_runtime_activation_request_phase4_load_closed")
    if runtime_activation_request.boundary.live_runtime_activation_allowed:
        missing.append("phase45_runtime_activation_request_activation_closed")
    if runtime_activation_request.boundary.phase1_live_session_mutation_allowed:
        missing.append("phase45_runtime_activation_request_live_session_closed")
    if runtime_activation_request.boundary.safety_api_calls_allowed:
        missing.append("phase45_runtime_activation_request_safety_api_closed")
    if runtime_activation_request.boundary.phase2_writeback_allowed:
        missing.append("phase45_runtime_activation_request_phase2_writeback_closed")
    if not runtime_activation_request.boundary.requires_phase1_runtime_revalidation:
        missing.append("phase45_runtime_activation_request_requires_revalidation")
    if not runtime_activation_request.boundary.requires_runtime_operator_confirmation:
        missing.append("phase45_runtime_activation_request_requires_operator_confirmation")
    if runtime_load_dry_run.status != "dry_run_passed":
        missing.append("phase45_runtime_load_dry_run_passed")
    if not runtime_load_dry_run.dry_run_passed:
        missing.append("phase45_runtime_load_dry_run_flag")
    if runtime_load_dry_run.activation_performed:
        missing.append("phase45_runtime_load_dry_run_no_activation")
    if runtime_load_dry_run.request_id != runtime_activation_request.request_id:
        missing.append("phase45_runtime_load_dry_run_request_id")
    if runtime_load_dry_run.export_id != runtime_export.export_id:
        missing.append("phase45_runtime_load_dry_run_export_id")
    if runtime_load_dry_run.mission_graph_sha256 != runtime_export.mission_graph_sha256:
        missing.append("phase45_runtime_load_dry_run_mission_graph_hash")
    if runtime_load_dry_run.counts.blocker_count != 0:
        missing.append("phase45_runtime_load_dry_run_no_blockers")
    if runtime_load_dry_run.counts.mission_graph_runtime_index_count != 1:
        missing.append("phase45_runtime_load_dry_run_index_built")
    if runtime_load_dry_run.counts.checkpoint_count != final_mission_graph.counts.checkpoint_count:
        missing.append("phase45_runtime_load_dry_run_checkpoint_count")
    if runtime_load_dry_run.counts.segment_count != final_mission_graph.counts.segment_count:
        missing.append("phase45_runtime_load_dry_run_segment_count")
    if runtime_load_dry_run.counts.route_point_count != 2:
        missing.append("phase45_runtime_load_dry_run_route_points")
    if runtime_load_dry_run.counts.duplicate_id_count != 0:
        missing.append("phase45_runtime_load_dry_run_duplicate_ids")
    if runtime_load_dry_run.counts.segment_reference_error_count != 0:
        missing.append("phase45_runtime_load_dry_run_segment_references")
    if runtime_load_dry_run.counts.safety_runtime_session_count != 0:
        missing.append("phase45_runtime_load_dry_run_no_safety_session")
    if runtime_load_dry_run.counts.live_runtime_activation_count != 0:
        missing.append("phase45_runtime_load_dry_run_no_live_activation")
    if runtime_load_dry_run.counts.safety_api_call_count != 0:
        missing.append("phase45_runtime_load_dry_run_no_safety_api")
    if runtime_load_dry_run.counts.phase1_live_session_mutation_count != 0:
        missing.append("phase45_runtime_load_dry_run_no_live_session_mutation")
    if runtime_load_dry_run.counts.phase2_writeback_count != 0:
        missing.append("phase45_runtime_load_dry_run_no_phase2_writeback")
    if not runtime_load_dry_run.boundary.dry_run_only:
        missing.append("phase45_runtime_load_dry_run_only")
    if not runtime_load_dry_run.boundary.phase1_runtime_loader_check:
        missing.append("phase45_runtime_load_dry_run_loader_check")
    if not runtime_load_dry_run.boundary.mission_graph_runtime_index_allowed:
        missing.append("phase45_runtime_load_dry_run_index_allowed")
    if runtime_load_dry_run.boundary.live_runtime_activation_allowed:
        missing.append("phase45_runtime_load_dry_run_activation_closed")
    if runtime_load_dry_run.boundary.safety_runtime_session_allowed:
        missing.append("phase45_runtime_load_dry_run_safety_session_closed")
    if runtime_load_dry_run.boundary.phase1_live_session_mutation_allowed:
        missing.append("phase45_runtime_load_dry_run_live_session_closed")
    if runtime_load_dry_run.boundary.safety_api_calls_allowed:
        missing.append("phase45_runtime_load_dry_run_safety_api_closed")
    if runtime_load_dry_run.boundary.phase2_writeback_allowed:
        missing.append("phase45_runtime_load_dry_run_phase2_writeback_closed")
    if not runtime_load_dry_run.boundary.requires_explicit_final_activation:
        missing.append("phase45_runtime_load_dry_run_requires_final_activation")
    if runtime_activation_result.status != "loaded_not_observing":
        missing.append("phase45_actual_runtime_activation_loaded_not_observing")
    if runtime_activation_result.activation_record is None:
        missing.append("phase45_actual_runtime_activation_record")
    if runtime_activation_result.session is None:
        missing.append("phase45_actual_runtime_activation_session")
    if runtime_activation_result.blocked_report is not None:
        missing.append("phase45_actual_runtime_activation_not_blocked")
    if runtime_activation_result.activation_record is not None:
        activation_record = runtime_activation_result.activation_record
        if not activation_record.activation_performed:
            missing.append("phase45_actual_runtime_activation_performed")
        if activation_record.export_id != runtime_export.export_id:
            missing.append("phase45_actual_runtime_activation_export_id")
        if activation_record.request_id != runtime_activation_request.request_id:
            missing.append("phase45_actual_runtime_activation_request_id")
        if activation_record.mission_graph_sha256 != runtime_export.mission_graph_sha256:
            missing.append("phase45_actual_runtime_activation_mission_graph_hash")
        if activation_record.dry_run_report_id != runtime_load_dry_run.report_id:
            missing.append("phase45_actual_runtime_activation_dry_run_report_id")
        if activation_record.counts.runtime_activation_record_count != 1:
            missing.append("phase45_actual_runtime_activation_record_count")
        if activation_record.counts.safety_runtime_session_count != 1:
            missing.append("phase45_actual_runtime_activation_session_count")
        if activation_record.counts.observations_processed_count != 0:
            missing.append("phase45_actual_runtime_activation_no_observations")
        if activation_record.counts.incident_package_count != 0:
            missing.append("phase45_actual_runtime_activation_no_incidents")
        if activation_record.counts.stored_incident_path_count != 0:
            missing.append("phase45_actual_runtime_activation_no_stored_incidents")
        if activation_record.counts.safety_api_call_count != 0:
            missing.append("phase45_actual_runtime_activation_no_safety_api")
        if activation_record.counts.phase2_writeback_count != 0:
            missing.append("phase45_actual_runtime_activation_no_phase2_writeback")
        if not activation_record.boundary.phase1_runtime_loader:
            missing.append("phase45_actual_runtime_activation_phase1_loader")
        if not activation_record.boundary.creates_safety_runtime_session:
            missing.append("phase45_actual_runtime_activation_creates_session")
        if activation_record.boundary.starts_observation_processing:
            missing.append("phase45_actual_runtime_activation_observation_closed")
        if activation_record.boundary.calls_safety_api:
            missing.append("phase45_actual_runtime_activation_safety_api_closed")
        if activation_record.boundary.writes_phase2_brain:
            missing.append("phase45_actual_runtime_activation_phase2_closed")
        if activation_record.boundary.mutates_runtime_export:
            missing.append("phase45_actual_runtime_activation_export_immutable")
        if activation_record.boundary.mutates_activation_request:
            missing.append("phase45_actual_runtime_activation_request_immutable")
        if activation_record.boundary.incident_bridge_enabled:
            missing.append("phase45_actual_runtime_activation_bridge_closed")
        if activation_record.boundary.activation_state != "loaded_not_observing":
            missing.append("phase45_actual_runtime_activation_boundary_state")
    if runtime_activation_result.session is not None:
        activation_snapshot = runtime_activation_result.session.snapshot()
        if activation_snapshot.incident_packages:
            missing.append("phase45_actual_runtime_activation_session_no_incidents")
        if activation_snapshot.stored_incident_paths:
            missing.append("phase45_actual_runtime_activation_session_no_stored_incidents")
    if runtime_observing_result.status != "observing":
        missing.append("phase45_runtime_observing_status")
    if runtime_observing_result.session is not runtime_activation_result.session:
        missing.append("phase45_runtime_observing_reuses_session")
    observing_record = runtime_observing_result.observation_start_record
    if observing_record.activation_id != "runtime_activation.phase45.release_check.v0":
        missing.append("phase45_runtime_observing_activation_id")
    if observing_record.activation_status_before_start != "loaded_not_observing":
        missing.append("phase45_runtime_observing_starts_after_loaded")
    if observing_record.status != "observing":
        missing.append("phase45_runtime_observing_record_status")
    if observing_record.counts.safety_runtime_session_count != 1:
        missing.append("phase45_runtime_observing_session_count")
    if observing_record.counts.observations_processed_count != 1:
        missing.append("phase45_runtime_observing_first_observation")
    if observing_record.counts.safety_api_call_count != 0:
        missing.append("phase45_runtime_observing_no_safety_api")
    if observing_record.counts.phase2_writeback_count != 0:
        missing.append("phase45_runtime_observing_no_phase2_writeback")
    if observing_record.boundary.calls_safety_api:
        missing.append("phase45_runtime_observing_safety_api_closed")
    if observing_record.boundary.writes_phase2_brain:
        missing.append("phase45_runtime_observing_phase2_closed")
    if observing_record.boundary.mutates_runtime_export:
        missing.append("phase45_runtime_observing_export_immutable")
    if observing_record.boundary.mutates_activation_request:
        missing.append("phase45_runtime_observing_request_immutable")
    if observing_record.boundary.incident_bridge_enabled:
        missing.append("phase45_runtime_observing_bridge_closed")
    if observing_record.boundary.activation_state != "observing":
        missing.append("phase45_runtime_observing_boundary_state")
    observing_snapshot = runtime_observing_result.session.snapshot()
    if observing_snapshot.observations_processed != 3:
        missing.append("phase45_runtime_observing_session_observation_count")
    batch_record = runtime_observation_batch_result.observation_batch_record
    if runtime_observation_batch_result.status != "observing":
        missing.append("phase45_runtime_observation_batch_status")
    if runtime_observation_batch_result.session is not runtime_observing_result.session:
        missing.append("phase45_runtime_observation_batch_reuses_session")
    if batch_record.activation_id != "runtime_activation.phase45.release_check.v0":
        missing.append("phase45_runtime_observation_batch_activation_id")
    if batch_record.status != "observing" or batch_record.previous_status != "observing":
        missing.append("phase45_runtime_observation_batch_observing_status")
    if batch_record.observation_count != 2:
        missing.append("phase45_runtime_observation_batch_size")
    if batch_record.counts.observations_processed_count != 3:
        missing.append("phase45_runtime_observation_batch_processed_count")
    if batch_record.counts.safety_api_call_count != 0:
        missing.append("phase45_runtime_observation_batch_no_safety_api")
    if batch_record.counts.phase2_writeback_count != 0:
        missing.append("phase45_runtime_observation_batch_no_phase2_writeback")
    if batch_record.boundary.connects_continuous_sensor_stream:
        missing.append("phase45_runtime_observation_batch_no_continuous_stream")
    if batch_record.boundary.calls_safety_api:
        missing.append("phase45_runtime_observation_batch_safety_api_closed")
    if batch_record.boundary.writes_phase2_brain:
        missing.append("phase45_runtime_observation_batch_phase2_closed")
    if batch_record.boundary.mutates_runtime_export:
        missing.append("phase45_runtime_observation_batch_export_immutable")
    if batch_record.boundary.mutates_activation_request:
        missing.append("phase45_runtime_observation_batch_request_immutable")
    if batch_record.boundary.incident_bridge_enabled:
        missing.append("phase45_runtime_observation_batch_bridge_closed")
    if batch_record.boundary.raw_observations_embedded:
        missing.append("phase45_runtime_observation_batch_no_raw_observations")
    stream_guard_records = [
        runtime_stream_guard_result.stream_guard_record,
        runtime_paused_stream_guard_result.stream_guard_record,
        runtime_ended_stream_guard_result.stream_guard_record,
    ]
    expected_stream_statuses = ["observing", "paused", "ended"]
    for record, expected_status in zip(stream_guard_records, expected_stream_statuses, strict=True):
        if record.status != "stream_blocked":
            missing.append(f"phase45_runtime_stream_guard_blocked:{expected_status}")
        if record.requested_from_status != expected_status:
            missing.append(f"phase45_runtime_stream_guard_from_status:{expected_status}")
        if record.counts.safety_api_call_count != 0:
            missing.append(f"phase45_runtime_stream_guard_no_safety_api:{expected_status}")
        if record.counts.phase2_writeback_count != 0:
            missing.append(f"phase45_runtime_stream_guard_no_phase2:{expected_status}")
        if record.boundary.continuous_sensor_stream_allowed:
            missing.append(f"phase45_runtime_stream_guard_stream_closed:{expected_status}")
        if record.boundary.hardware_stream_control_allowed:
            missing.append(f"phase45_runtime_stream_guard_hardware_closed:{expected_status}")
        if record.boundary.safety_api_calls_allowed:
            missing.append(f"phase45_runtime_stream_guard_api_closed:{expected_status}")
        if record.boundary.incident_bridge_enabled:
            missing.append(f"phase45_runtime_stream_guard_bridge_closed:{expected_status}")
        if record.boundary.raw_stream_payloads_embedded:
            missing.append(f"phase45_runtime_stream_guard_no_raw_payloads:{expected_status}")
    lifecycle_records = [
        runtime_lifecycle_pause_result.lifecycle_record,
        runtime_lifecycle_resume_result.lifecycle_record,
        runtime_lifecycle_end_result.lifecycle_record,
        runtime_lifecycle_abort_result.lifecycle_record,
    ]
    if runtime_lifecycle_pause_result.status != "paused":
        missing.append("phase45_runtime_lifecycle_pause_status")
    if runtime_lifecycle_resume_result.status != "observing":
        missing.append("phase45_runtime_lifecycle_resume_status")
    if runtime_lifecycle_end_result.status != "ended":
        missing.append("phase45_runtime_lifecycle_end_status")
    if runtime_lifecycle_abort_result.status != "aborted":
        missing.append("phase45_runtime_lifecycle_abort_status")
    if runtime_lifecycle_pause_result.session is not runtime_observing_result.session:
        missing.append("phase45_runtime_lifecycle_pause_reuses_session")
    if runtime_lifecycle_resume_result.session is not runtime_observing_result.session:
        missing.append("phase45_runtime_lifecycle_resume_reuses_session")
    if runtime_lifecycle_end_result.session is not runtime_observing_result.session:
        missing.append("phase45_runtime_lifecycle_end_reuses_session")
    if runtime_lifecycle_abort_result.session is not runtime_observing_result.session:
        missing.append("phase45_runtime_lifecycle_abort_reuses_session")
    expected_transitions = [
        ("pause", "observing", "paused", False),
        ("resume", "paused", "observing", False),
        ("end", "observing", "ended", True),
        ("abort", "observing", "aborted", True),
    ]
    for record, (action, previous_status, status, terminal) in zip(
        lifecycle_records,
        expected_transitions,
        strict=True,
    ):
        if record.action != action:
            missing.append(f"phase45_runtime_lifecycle_action:{action}")
        if record.previous_status != previous_status:
            missing.append(f"phase45_runtime_lifecycle_previous:{action}")
        if record.status != status:
            missing.append(f"phase45_runtime_lifecycle_status:{action}")
        if record.terminal_state is not terminal:
            missing.append(f"phase45_runtime_lifecycle_terminal:{action}")
        if action in {"pause", "resume", "end"} and record.counts.observations_processed_count != 3:
            missing.append(f"phase45_runtime_lifecycle_preserves_batch_count:{action}")
        if action == "abort" and record.counts.observations_processed_count != 3:
            missing.append(f"phase45_runtime_lifecycle_preserves_shared_session_count:{action}")
        if record.counts.safety_api_call_count != 0:
            missing.append(f"phase45_runtime_lifecycle_no_safety_api:{action}")
        if record.counts.phase2_writeback_count != 0:
            missing.append(f"phase45_runtime_lifecycle_no_phase2_writeback:{action}")
        if record.boundary.processes_observation:
            missing.append(f"phase45_runtime_lifecycle_no_observation_processing:{action}")
        if record.boundary.calls_safety_api:
            missing.append(f"phase45_runtime_lifecycle_safety_api_closed:{action}")
        if record.boundary.writes_phase2_brain:
            missing.append(f"phase45_runtime_lifecycle_phase2_closed:{action}")
        if record.boundary.mutates_runtime_export:
            missing.append(f"phase45_runtime_lifecycle_export_immutable:{action}")
        if record.boundary.mutates_activation_request:
            missing.append(f"phase45_runtime_lifecycle_request_immutable:{action}")
        if record.boundary.incident_bridge_enabled:
            missing.append(f"phase45_runtime_lifecycle_bridge_closed:{action}")
    if raw_payload_keys:
        missing.append(f"phase45_no_raw_payload_keys:{','.join(raw_payload_keys)}")
    if not handoff.boundary.metadata_only:
        missing.append("phase45_handoff_metadata_only")
    if handoff.boundary.planning_workspace_dependency_allowed:
        missing.append("phase45_handoff_no_planning_workspace_dependency")
    if handoff.boundary.phase1_safety_call_allowed:
        missing.append("phase45_handoff_no_safety_call")
    if handoff.boundary.live_runtime_mutation_allowed:
        missing.append("phase45_handoff_no_live_runtime_mutation")
    if handoff.boundary.phase1_bridge_dependency_allowed:
        missing.append("phase45_handoff_no_phase1_bridge_dependency")
    if handoff.boundary.raw_payloads_embedded:
        missing.append("phase45_handoff_no_raw_payloads")

    return {
        "ok": not missing,
        "profile_count": len(profiles),
        "selected_profile": selection.selected_profile_id.value,
        "quick_review_allowed": selection.quick_review_allowed,
        "route_classes": route_classes,
        "hard_blocker_catalog_id": hard_blocker_catalog.catalog_id.value,
        "hard_blocker_count": len(hard_blocker_catalog.blockers),
        "departure_gate_status": departure_gate.status.value,
        "departure_gate_warning_count": departure_gate.counts.warning_count,
        "departure_gate_blocker_count": departure_gate.counts.blocker_count,
        "departure_gate_hard_blocker_count": departure_gate.counts.hard_blocker_count,
        "departure_approval_granted": departure_gate.approval.approval_granted,
        "final_mission_graph_generation_allowed": (
            departure_gate.approval.final_mission_graph_generation_allowed
        ),
        "resolution_count": resolution_log.counts.resolution_count,
        "resolution_warning_override_count": resolution_log.counts.warning_override_count,
        "resolution_blocker_attempt_count": (
            resolution_log.counts.blocker_resolution_attempt_count
        ),
        "resolution_local_workspace_only": resolution_log.boundary.local_workspace_only,
        "resolution_repo_fixture_write_allowed": (
            resolution_log.boundary.repo_fixture_write_allowed
        ),
        "resolved_departure_gate_status": resolved_departure_gate.status.value,
        "resolved_departure_approval_granted": (
            resolved_departure_gate.approval.approval_granted
        ),
        "resolved_final_mission_graph_generation_allowed": (
            resolved_departure_gate.approval.final_mission_graph_generation_allowed
        ),
        "resolved_runtime_handoff_allowed": (
            resolved_departure_gate.boundary.runtime_handoff_allowed
        ),
        "resolved_unresolved_warning_count": (
            resolved_departure_gate.counts.unresolved_warning_count
        ),
        "resolved_blocker_count": resolved_departure_gate.counts.blocker_count,
        "final_mission_graph_status": final_mission_graph.status,
        "final_mission_graph_version": final_mission_graph.mission_graph_version,
        "final_mission_graph_departure_approval_id": (
            final_mission_graph.departure_approval_id
        ),
        "final_mission_graph_checkpoint_count": (
            final_mission_graph.counts.checkpoint_count
        ),
        "final_mission_graph_segment_count": final_mission_graph.counts.segment_count,
        "final_mission_graph_diversion_point_count": (
            final_mission_graph.counts.diversion_point_count
        ),
        "final_mission_graph_route_source": (
            final_mission_graph.mission_graph.route_source
        ),
        "final_mission_graph_sha256": final_mission_graph.final_mission_graph_sha256,
        "final_mission_graph_runtime_write_count": (
            final_mission_graph.counts.runtime_write_count
        ),
        "final_mission_graph_safety_call_count": (
            final_mission_graph.counts.safety_call_count
        ),
        "final_mission_graph_phase2_writeback_count": (
            final_mission_graph.counts.phase2_writeback_count
        ),
        "final_mission_graph_runtime_handoff_performed": (
            final_mission_graph.boundary.runtime_handoff_performed
        ),
        "final_mission_graph_boundary_ok": (
            final_mission_graph.boundary.generated_after_departure_gate_passed
            and not final_mission_graph.boundary.planning_workspace_dependency_allowed
            and not final_mission_graph.boundary.runtime_handoff_performed
            and not final_mission_graph.boundary.phase1_runtime_mutation_allowed
            and not final_mission_graph.boundary.safety_api_calls_allowed
            and not final_mission_graph.boundary.phase2_writeback_allowed
            and not final_mission_graph.boundary.raw_payloads_embedded
        ),
        "runtime_handoff_allowed": departure_gate.boundary.runtime_handoff_allowed,
        "unique_finding_id_count": len(set(finding_ids)),
        "finding_count": len(finding_ids),
        "runtime_handoff_boundary_ok": (
            handoff.boundary.metadata_only
            and not handoff.boundary.planning_workspace_dependency_allowed
            and not handoff.boundary.phase1_safety_call_allowed
            and not handoff.boundary.live_runtime_mutation_allowed
            and not handoff.boundary.phase1_bridge_dependency_allowed
            and not handoff.boundary.raw_payloads_embedded
        ),
        "runtime_handoff_target_kind": handoff.handoff_target.target_kind,
        "runtime_handoff_package_sha256": handoff.package.sha256,
        "runtime_handoff_mission_graph_version": handoff.mission_graph.version,
        "runtime_handoff_mission_graph_sha256": handoff.mission_graph.sha256,
        "runtime_handoff_departure_approval_id": handoff.departure_approval_id,
        "runtime_handoff_override_reason_count": len(handoff.override_reasons),
        "runtime_export_status": runtime_export.status.value,
        "runtime_export_id": runtime_export.export_id,
        "runtime_export_mission_graph_sha256": runtime_export.mission_graph_sha256,
        "runtime_export_handoff_id": runtime_export.handoff_id,
        "runtime_export_file_write_count": (
            runtime_export.counts.runtime_file_write_count
        ),
        "runtime_export_live_activation_count": (
            runtime_export.counts.live_runtime_activation_count
        ),
        "runtime_export_safety_api_call_count": runtime_export.counts.safety_api_call_count,
        "runtime_export_phase1_live_session_mutation_count": (
            runtime_export.counts.phase1_live_session_mutation_count
        ),
        "runtime_export_route_source_resolution_policy": (
            runtime_export.boundary.route_source_resolution_policy
        ),
        "runtime_export_boundary_ok": (
            runtime_export.boundary.runtime_file_write_allowed
            and not runtime_export.boundary.live_runtime_activation_allowed
            and not runtime_export.boundary.phase1_live_session_mutation_allowed
            and not runtime_export.boundary.safety_api_calls_allowed
            and not runtime_export.boundary.raw_payloads_embedded
        ),
        "runtime_artifact_resolution_manifest_id": (
            runtime_artifact_resolution.manifest_id
        ),
        "runtime_artifact_resolution_route_source_ref": (
            runtime_artifact_resolution.route_source_ref
        ),
        "runtime_artifact_resolution_count": (
            runtime_artifact_resolution.counts.artifact_resolution_count
        ),
        "runtime_artifact_resolution_resolved_count": (
            runtime_artifact_resolution.counts.resolved_count
        ),
        "runtime_artifact_resolution_missing_count": (
            runtime_artifact_resolution.counts.missing_count
        ),
        "runtime_artifact_resolution_raw_payload_copy_count": (
            runtime_artifact_resolution.counts.raw_payload_copy_count
        ),
        "runtime_artifact_resolution_boundary_ok": (
            runtime_artifact_resolution.boundary.metadata_only
            and not runtime_artifact_resolution.boundary.raw_payloads_embedded
            and not runtime_artifact_resolution.boundary.route_payload_copy_allowed
            and not runtime_artifact_resolution.boundary.live_runtime_activation_allowed
            and not runtime_artifact_resolution.boundary.phase1_live_session_mutation_allowed
            and not runtime_artifact_resolution.boundary.safety_api_calls_allowed
            and runtime_artifact_resolution.boundary.missing_required_artifact_blocks_activation
        ),
        "runtime_activation_preflight_status": runtime_activation_preflight.status.value,
        "runtime_activation_preflight_ready": runtime_activation_preflight.activation_ready,
        "runtime_activation_preflight_performed": (
            runtime_activation_preflight.activation_performed
        ),
        "runtime_activation_preflight_blocker_count": (
            runtime_activation_preflight.counts.blocker_count
        ),
        "runtime_activation_preflight_route_point_count": (
            runtime_activation_preflight.counts.route_point_count
        ),
        "runtime_activation_preflight_live_activation_count": (
            runtime_activation_preflight.counts.live_runtime_activation_count
        ),
        "runtime_activation_preflight_safety_api_call_count": (
            runtime_activation_preflight.counts.safety_api_call_count
        ),
        "runtime_activation_preflight_phase1_live_session_mutation_count": (
            runtime_activation_preflight.counts.phase1_live_session_mutation_count
        ),
        "runtime_activation_preflight_phase2_writeback_count": (
            runtime_activation_preflight.counts.phase2_writeback_count
        ),
        "runtime_activation_preflight_boundary_ok": (
            runtime_activation_preflight.boundary.preflight_only
            and not runtime_activation_preflight.boundary.live_runtime_activation_allowed
            and not runtime_activation_preflight.boundary.phase1_live_session_mutation_allowed
            and not runtime_activation_preflight.boundary.safety_api_calls_allowed
            and not runtime_activation_preflight.boundary.phase2_writeback_allowed
            and runtime_activation_preflight.boundary.requires_explicit_phase1_activation
        ),
        "runtime_activation_request_rejects_blocked_preflight": (
            blocked_preflight_request_rejected
        ),
        "runtime_activation_ready_preflight_status": (
            runtime_activation_ready_preflight.status.value
        ),
        "runtime_activation_ready_preflight_ready": (
            runtime_activation_ready_preflight.activation_ready
        ),
        "runtime_activation_ready_preflight_blocker_count": (
            runtime_activation_ready_preflight.counts.blocker_count
        ),
        "runtime_activation_ready_preflight_route_point_count": (
            runtime_activation_ready_preflight.counts.route_point_count
        ),
        "runtime_activation_request_status": runtime_activation_request.status.value,
        "runtime_activation_request_requested": (
            runtime_activation_request.activation_requested
        ),
        "runtime_activation_request_performed": (
            runtime_activation_request.activation_performed
        ),
        "runtime_activation_request_preflight_report_id": (
            runtime_activation_request.source.preflight_report_id
        ),
        "runtime_activation_request_live_activation_count": (
            runtime_activation_request.counts.live_runtime_activation_count
        ),
        "runtime_activation_request_safety_api_call_count": (
            runtime_activation_request.counts.safety_api_call_count
        ),
        "runtime_activation_request_phase1_live_session_mutation_count": (
            runtime_activation_request.counts.phase1_live_session_mutation_count
        ),
        "runtime_activation_request_phase2_writeback_count": (
            runtime_activation_request.counts.phase2_writeback_count
        ),
        "runtime_activation_request_boundary_ok": (
            runtime_activation_request.boundary.request_artifact_only
            and runtime_activation_request.boundary.requires_activation_ready_preflight
            and not runtime_activation_request.boundary.phase4_runtime_load_allowed
            and not runtime_activation_request.boundary.live_runtime_activation_allowed
            and not runtime_activation_request.boundary.phase1_live_session_mutation_allowed
            and not runtime_activation_request.boundary.safety_api_calls_allowed
            and not runtime_activation_request.boundary.phase2_writeback_allowed
            and runtime_activation_request.boundary.requires_phase1_runtime_revalidation
            and runtime_activation_request.boundary.requires_runtime_operator_confirmation
        ),
        "runtime_load_dry_run_status": runtime_load_dry_run.status.value,
        "runtime_load_dry_run_passed": runtime_load_dry_run.dry_run_passed,
        "runtime_load_dry_run_performed": runtime_load_dry_run.activation_performed,
        "runtime_load_dry_run_request_id": runtime_load_dry_run.request_id,
        "runtime_load_dry_run_blocker_count": runtime_load_dry_run.counts.blocker_count,
        "runtime_load_dry_run_route_point_count": (
            runtime_load_dry_run.counts.route_point_count
        ),
        "runtime_load_dry_run_checkpoint_count": (
            runtime_load_dry_run.counts.checkpoint_count
        ),
        "runtime_load_dry_run_segment_count": runtime_load_dry_run.counts.segment_count,
        "runtime_load_dry_run_duplicate_id_count": (
            runtime_load_dry_run.counts.duplicate_id_count
        ),
        "runtime_load_dry_run_segment_reference_error_count": (
            runtime_load_dry_run.counts.segment_reference_error_count
        ),
        "runtime_load_dry_run_mission_graph_runtime_index_count": (
            runtime_load_dry_run.counts.mission_graph_runtime_index_count
        ),
        "runtime_load_dry_run_safety_runtime_session_count": (
            runtime_load_dry_run.counts.safety_runtime_session_count
        ),
        "runtime_load_dry_run_live_activation_count": (
            runtime_load_dry_run.counts.live_runtime_activation_count
        ),
        "runtime_load_dry_run_safety_api_call_count": (
            runtime_load_dry_run.counts.safety_api_call_count
        ),
        "runtime_load_dry_run_phase1_live_session_mutation_count": (
            runtime_load_dry_run.counts.phase1_live_session_mutation_count
        ),
        "runtime_load_dry_run_phase2_writeback_count": (
            runtime_load_dry_run.counts.phase2_writeback_count
        ),
        "runtime_load_dry_run_boundary_ok": (
            runtime_load_dry_run.boundary.dry_run_only
            and runtime_load_dry_run.boundary.phase1_runtime_loader_check
            and runtime_load_dry_run.boundary.mission_graph_runtime_index_allowed
            and not runtime_load_dry_run.boundary.live_runtime_activation_allowed
            and not runtime_load_dry_run.boundary.safety_runtime_session_allowed
            and not runtime_load_dry_run.boundary.phase1_live_session_mutation_allowed
            and not runtime_load_dry_run.boundary.safety_api_calls_allowed
            and not runtime_load_dry_run.boundary.phase2_writeback_allowed
            and runtime_load_dry_run.boundary.requires_explicit_final_activation
        ),
        "actual_runtime_activation_status": runtime_activation_result.status.value,
        "actual_runtime_activation_record_written": (
            runtime_activation_result.activation_record is not None
        ),
        "actual_runtime_activation_blocked": (
            runtime_activation_result.blocked_report is not None
        ),
        "actual_runtime_activation_session_created": (
            runtime_activation_result.session is not None
        ),
        "actual_runtime_activation_performed": (
            runtime_activation_result.activation_record.activation_performed
            if runtime_activation_result.activation_record is not None
            else False
        ),
        "actual_runtime_activation_request_id": (
            runtime_activation_result.activation_record.request_id
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_export_id": (
            runtime_activation_result.activation_record.export_id
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_observations_processed_count": (
            runtime_activation_result.activation_record.counts.observations_processed_count
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_incident_package_count": (
            runtime_activation_result.activation_record.counts.incident_package_count
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_stored_incident_path_count": (
            runtime_activation_result.activation_record.counts.stored_incident_path_count
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_safety_api_call_count": (
            runtime_activation_result.activation_record.counts.safety_api_call_count
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_phase2_writeback_count": (
            runtime_activation_result.activation_record.counts.phase2_writeback_count
            if runtime_activation_result.activation_record is not None
            else None
        ),
        "actual_runtime_activation_boundary_ok": (
            runtime_activation_result.activation_record is not None
            and runtime_activation_result.activation_record.boundary.phase1_runtime_loader
            and runtime_activation_result.activation_record.boundary.creates_safety_runtime_session
            and not runtime_activation_result.activation_record.boundary.starts_observation_processing
            and not runtime_activation_result.activation_record.boundary.calls_safety_api
            and not runtime_activation_result.activation_record.boundary.writes_phase2_brain
            and not runtime_activation_result.activation_record.boundary.mutates_runtime_export
            and not runtime_activation_result.activation_record.boundary.mutates_activation_request
            and not runtime_activation_result.activation_record.boundary.incident_bridge_enabled
            and runtime_activation_result.activation_record.boundary.activation_state
            == "loaded_not_observing"
        ),
        "runtime_observing_status": runtime_observing_result.status.value,
        "runtime_observing_record_written": (
            runtime_observing_result.observation_start_record is not None
        ),
        "runtime_observing_activation_id": (
            runtime_observing_result.observation_start_record.activation_id
        ),
        "runtime_observing_session_reused": (
            runtime_observing_result.session is runtime_activation_result.session
        ),
        "runtime_observing_observation_source": (
            runtime_observing_result.observation_start_record.observation_source
        ),
        "runtime_observing_observations_processed_count": (
            runtime_observing_result.observation_start_record.counts.observations_processed_count
        ),
        "runtime_observing_incident_package_count": (
            runtime_observing_result.observation_start_record.counts.incident_package_count
        ),
        "runtime_observing_stored_incident_path_count": (
            runtime_observing_result.observation_start_record.counts.stored_incident_path_count
        ),
        "runtime_observing_safety_event_count": (
            runtime_observing_result.observation_start_record.safety_event_count
        ),
        "runtime_observing_recording_policy_profile": (
            runtime_observing_result.observation_start_record.recording_policy_profile
        ),
        "runtime_observing_safety_api_call_count": (
            runtime_observing_result.observation_start_record.counts.safety_api_call_count
        ),
        "runtime_observing_phase2_writeback_count": (
            runtime_observing_result.observation_start_record.counts.phase2_writeback_count
        ),
        "runtime_observing_boundary_ok": (
            runtime_observing_result.observation_start_record.boundary.phase1_runtime_loader
            and runtime_observing_result.observation_start_record.boundary.uses_existing_safety_runtime_session
            and runtime_observing_result.observation_start_record.boundary.starts_observation_processing
            and runtime_observing_result.observation_start_record.boundary.accepts_single_initial_observation
            and not runtime_observing_result.observation_start_record.boundary.calls_safety_api
            and not runtime_observing_result.observation_start_record.boundary.writes_phase2_brain
            and not runtime_observing_result.observation_start_record.boundary.mutates_runtime_export
            and not runtime_observing_result.observation_start_record.boundary.mutates_activation_request
            and not runtime_observing_result.observation_start_record.boundary.incident_bridge_enabled
            and runtime_observing_result.observation_start_record.boundary.activation_state
            == "observing"
        ),
        "runtime_observation_batch_status": runtime_observation_batch_result.status.value,
        "runtime_observation_batch_record_written": (
            runtime_observation_batch_result.observation_batch_record is not None
        ),
        "runtime_observation_batch_session_reused": (
            runtime_observation_batch_result.session is runtime_observing_result.session
        ),
        "runtime_observation_batch_size": (
            runtime_observation_batch_result.observation_batch_record.observation_count
        ),
        "runtime_observation_batch_observations_processed_count": (
            runtime_observation_batch_result.observation_batch_record.counts.observations_processed_count
        ),
        "runtime_observation_batch_safety_api_call_count": (
            runtime_observation_batch_result.observation_batch_record.counts.safety_api_call_count
        ),
        "runtime_observation_batch_phase2_writeback_count": (
            runtime_observation_batch_result.observation_batch_record.counts.phase2_writeback_count
        ),
        "runtime_observation_batch_incident_bridge_enabled": (
            runtime_observation_batch_result.observation_batch_record.boundary.incident_bridge_enabled
        ),
        "runtime_observation_batch_boundary_ok": (
            runtime_observation_batch_result.observation_batch_record.boundary.phase1_runtime_loader
            and runtime_observation_batch_result.observation_batch_record.boundary.uses_existing_safety_runtime_session
            and runtime_observation_batch_result.observation_batch_record.boundary.starts_observation_processing
            and runtime_observation_batch_result.observation_batch_record.boundary.accepts_bounded_observation_batch
            and not runtime_observation_batch_result.observation_batch_record.boundary.connects_continuous_sensor_stream
            and not runtime_observation_batch_result.observation_batch_record.boundary.calls_safety_api
            and not runtime_observation_batch_result.observation_batch_record.boundary.writes_phase2_brain
            and not runtime_observation_batch_result.observation_batch_record.boundary.mutates_runtime_export
            and not runtime_observation_batch_result.observation_batch_record.boundary.mutates_activation_request
            and not runtime_observation_batch_result.observation_batch_record.boundary.incident_bridge_enabled
            and runtime_observation_batch_result.observation_batch_record.boundary.activation_state
            == "observing"
        ),
        "runtime_stream_guard_record_count": len(stream_guard_records),
        "runtime_stream_guard_statuses": [
            record.status for record in stream_guard_records
        ],
        "runtime_stream_guard_requested_from_statuses": [
            record.requested_from_status.value for record in stream_guard_records
        ],
        "runtime_stream_guard_safety_api_call_count": sum(
            record.counts.safety_api_call_count for record in stream_guard_records
        ),
        "runtime_stream_guard_phase2_writeback_count": sum(
            record.counts.phase2_writeback_count for record in stream_guard_records
        ),
        "runtime_stream_guard_incident_bridge_enabled": any(
            record.boundary.incident_bridge_enabled for record in stream_guard_records
        ),
        "runtime_stream_guard_boundary_ok": all(
            not record.boundary.continuous_sensor_stream_allowed
            and not record.boundary.hardware_stream_control_allowed
            and not record.boundary.safety_api_calls_allowed
            and not record.boundary.writes_phase2_brain
            and not record.boundary.mutates_runtime_export
            and not record.boundary.mutates_activation_request
            and not record.boundary.incident_bridge_enabled
            and not record.boundary.raw_stream_payloads_embedded
            and record.boundary.requires_future_stream_protocol
            for record in stream_guard_records
        ),
        "runtime_lifecycle_record_count": len(lifecycle_records),
        "runtime_lifecycle_pause_status": runtime_lifecycle_pause_result.status.value,
        "runtime_lifecycle_resume_status": runtime_lifecycle_resume_result.status.value,
        "runtime_lifecycle_end_status": runtime_lifecycle_end_result.status.value,
        "runtime_lifecycle_abort_status": runtime_lifecycle_abort_result.status.value,
        "runtime_lifecycle_end_terminal": (
            runtime_lifecycle_end_result.lifecycle_record.terminal_state
        ),
        "runtime_lifecycle_abort_terminal": (
            runtime_lifecycle_abort_result.lifecycle_record.terminal_state
        ),
        "runtime_lifecycle_observations_processed_count": (
            runtime_lifecycle_end_result.lifecycle_record.counts.observations_processed_count
        ),
        "runtime_lifecycle_safety_api_call_count": sum(
            record.counts.safety_api_call_count for record in lifecycle_records
        ),
        "runtime_lifecycle_phase2_writeback_count": sum(
            record.counts.phase2_writeback_count for record in lifecycle_records
        ),
        "runtime_lifecycle_incident_bridge_enabled": any(
            record.boundary.incident_bridge_enabled for record in lifecycle_records
        ),
        "runtime_lifecycle_boundary_ok": all(
            record.boundary.phase1_runtime_lifecycle_control
            and record.boundary.uses_existing_safety_runtime_session
            and not record.boundary.processes_observation
            and not record.boundary.calls_safety_api
            and not record.boundary.writes_phase2_brain
            and not record.boundary.mutates_runtime_export
            and not record.boundary.mutates_activation_request
            and not record.boundary.incident_bridge_enabled
            for record in lifecycle_records
        ),
        "raw_payload_keys": raw_payload_keys,
        "missing": missing,
    }


def _check_runtime_stream_policy() -> dict[str, Any]:
    try:
        from runtime_stream_policy import build_default_runtime_stream_policy_manifest
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_policy_import:{exc}"],
        }

    missing: list[str] = []
    try:
        manifest = build_default_runtime_stream_policy_manifest()
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_policy_build:{exc}"],
        }

    source_kinds = [policy.source_kind.value for policy in manifest.source_policies]
    transports = sorted(
        {
            transport.value
            for policy in manifest.source_policies
            for transport in policy.accepted_transports
        }
    )
    auth_methods = sorted(
        {policy.recommended_auth_method.value for policy in manifest.source_policies}
    )

    if manifest.status != "policy_ready_not_connected":
        missing.append("runtime_stream_policy_status")
    if source_kinds != ["apple_watch", "mobile_phone"]:
        missing.append("runtime_stream_policy_sources")
    if transports != ["http_push", "websocket"]:
        missing.append("runtime_stream_policy_transports")
    if auth_methods != ["device_id_scoped_token_hmac_signature"]:
        missing.append("runtime_stream_policy_auth_method")
    if not all(policy.device_id_required for policy in manifest.source_policies):
        missing.append("runtime_stream_policy_device_id_required")
    if not all(policy.scoped_token_required for policy in manifest.source_policies):
        missing.append("runtime_stream_policy_token_required")
    if not all(policy.hmac_signature_required for policy in manifest.source_policies):
        missing.append("runtime_stream_policy_hmac_required")
    if not all(policy.sequence_number_required for policy in manifest.source_policies):
        missing.append("runtime_stream_policy_sequence_required")
    if not all(policy.payload_hash_required for policy in manifest.source_policies):
        missing.append("runtime_stream_policy_payload_hash_required")
    if manifest.buffering.retry_attempt_limit != 5:
        missing.append("runtime_stream_policy_retry_limit")
    if manifest.buffering.retry_exhausted_fallback != "latest_point_only":
        missing.append("runtime_stream_policy_latest_point_fallback")
    if manifest.cadence.max_hz != 10.0:
        missing.append("runtime_stream_policy_max_10hz")
    if manifest.cadence.min_interval_ms != 100:
        missing.append("runtime_stream_policy_min_interval")
    if not manifest.cadence.backpressure_enabled:
        missing.append("runtime_stream_policy_backpressure")
    if not manifest.cadence.rate_limit_enabled:
        missing.append("runtime_stream_policy_rate_limit")
    if not manifest.safety_api_access.safety_api_allowed_after_phase45_handoff:
        missing.append("runtime_stream_policy_safety_api_after_handoff")
    if manifest.safety_api_access.endpoint_prefix != "/safety":
        missing.append("runtime_stream_policy_safety_prefix")
    if manifest.incident_bridge_opt_in_guard.enabled_by_default:
        missing.append("runtime_stream_policy_bridge_not_default_enabled")
    if not manifest.incident_bridge_opt_in_guard.opt_in_required:
        missing.append("runtime_stream_policy_bridge_opt_in_required")
    if manifest.incident_bridge_opt_in_guard.remote_notifications_enabled:
        missing.append("runtime_stream_policy_remote_notifications_closed")
    if not manifest.boundary.policy_only:
        missing.append("runtime_stream_policy_policy_only")
    if not manifest.boundary.opens_safety_api_after_handoff:
        missing.append("runtime_stream_policy_opens_safety_api_after_handoff")
    if manifest.boundary.creates_live_endpoint:
        missing.append("runtime_stream_policy_no_live_endpoint")
    if manifest.boundary.connects_device_stream:
        missing.append("runtime_stream_policy_no_device_stream")
    if manifest.boundary.starts_websocket_server:
        missing.append("runtime_stream_policy_no_websocket_server")
    if manifest.boundary.calls_safety_api:
        missing.append("runtime_stream_policy_no_safety_call")
    if manifest.boundary.enables_incident_bridge:
        missing.append("runtime_stream_policy_no_bridge_enable")
    if manifest.boundary.writes_phase2_brain:
        missing.append("runtime_stream_policy_no_phase2")

    return {
        "ok": not missing,
        "status": manifest.status,
        "source_kinds": source_kinds,
        "accepted_transports": transports,
        "auth_methods": auth_methods,
        "retry_attempt_limit": manifest.buffering.retry_attempt_limit,
        "retry_exhausted_fallback": manifest.buffering.retry_exhausted_fallback.value,
        "max_hz": manifest.cadence.max_hz,
        "min_interval_ms": manifest.cadence.min_interval_ms,
        "backpressure_enabled": manifest.cadence.backpressure_enabled,
        "rate_limit_enabled": manifest.cadence.rate_limit_enabled,
        "safety_api_allowed_after_phase45_handoff": (
            manifest.safety_api_access.safety_api_allowed_after_phase45_handoff
        ),
        "safety_api_endpoint_prefix": manifest.safety_api_access.endpoint_prefix,
        "incident_bridge_guard_status": (
            manifest.incident_bridge_opt_in_guard.guard_status
        ),
        "incident_bridge_enabled_by_default": (
            manifest.incident_bridge_opt_in_guard.enabled_by_default
        ),
        "incident_bridge_opt_in_required": (
            manifest.incident_bridge_opt_in_guard.opt_in_required
        ),
        "boundary_ok": (
            manifest.boundary.policy_only
            and manifest.boundary.opens_safety_api_after_handoff
            and not manifest.boundary.creates_live_endpoint
            and not manifest.boundary.connects_device_stream
            and not manifest.boundary.starts_websocket_server
            and not manifest.boundary.calls_safety_api
            and not manifest.boundary.enables_incident_bridge
            and not manifest.boundary.writes_phase2_brain
        ),
        "missing": missing,
    }


def _check_runtime_observation_envelope() -> dict[str, Any]:
    try:
        from runtime_observation_envelope import (
            build_signed_runtime_observation_envelope,
            verify_runtime_observation_envelope,
        )
    except Exception as exc:
        return {
            "ok": False,
            "envelope_status": None,
            "missing": [f"runtime_observation_envelope_import:{exc}"],
        }

    missing: list[str] = []
    payload = {
        "timestamp": 60.0,
        "source": "apple_watch",
        "lat": 24.0,
        "lon": 121.0,
        "elevation_m": 1001.0,
        "gps_horizontal_accuracy_m": 8.0,
    }
    try:
        envelope = build_signed_runtime_observation_envelope(
            payload,
            secret_key="release-check-secret",
            envelope_id="runtime_observation_envelope.release_check.v0",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport="http_push",
            device_id="watch.release_check.001",
            sequence_no=1,
            observed_at="2026-05-18T10:00:01+08:00",
            received_at="2026-05-18T10:00:02+08:00",
        )
    except Exception as exc:
        return {
            "ok": False,
            "envelope_status": None,
            "missing": [f"runtime_observation_envelope_build:{exc}"],
        }

    tampered_payload = dict(payload)
    tampered_payload["lat"] = 25.0
    serialized = envelope.to_json()
    forbidden_fragments = [
        fragment
        for fragment in (
            '"lat"',
            '"lon"',
            "elevation_m",
            "gps_horizontal_accuracy_m",
            "sensorlog",
            "loggingTime",
        )
        if fragment in serialized
    ]

    if envelope.payload_kind != "safety_observation":
        missing.append("runtime_observation_envelope_payload_kind")
    if len(envelope.payload_sha256) != 64:
        missing.append("runtime_observation_envelope_payload_hash")
    if len(envelope.signature) != 64:
        missing.append("runtime_observation_envelope_signature")
    if envelope.signature_algorithm != "hmac_sha256":
        missing.append("runtime_observation_envelope_signature_algorithm")
    if envelope.token_scope != "runtime:observation:write":
        missing.append("runtime_observation_envelope_token_scope")
    if envelope.sequence_no != 1:
        missing.append("runtime_observation_envelope_sequence")
    if not envelope.dedupe_key.startswith(
        "runtime_source.apple_watch.v0:watch.release_check.001:1:"
    ):
        missing.append("runtime_observation_envelope_dedupe_key")
    if not verify_runtime_observation_envelope(
        envelope,
        payload,
        secret_key="release-check-secret",
    ):
        missing.append("runtime_observation_envelope_signature_verifies")
    if verify_runtime_observation_envelope(
        envelope,
        tampered_payload,
        secret_key="release-check-secret",
    ):
        missing.append("runtime_observation_envelope_rejects_tampered_payload")
    if envelope.boundary.raw_payload_embedded:
        missing.append("runtime_observation_envelope_no_raw_payload")
    if envelope.boundary.calls_safety_api:
        missing.append("runtime_observation_envelope_no_safety_call")
    if envelope.boundary.connects_device_stream:
        missing.append("runtime_observation_envelope_no_device_stream")
    if envelope.boundary.enables_incident_bridge:
        missing.append("runtime_observation_envelope_no_bridge")
    if envelope.boundary.writes_phase2_brain:
        missing.append("runtime_observation_envelope_no_phase2")
    if forbidden_fragments:
        missing.append(
            f"runtime_observation_envelope_forbidden_fragments:{','.join(forbidden_fragments)}"
        )

    return {
        "ok": not missing,
        "envelope_status": "signed_summary_only",
        "source_kind": envelope.source_kind.value,
        "transport": envelope.transport.value,
        "token_scope": envelope.token_scope,
        "sequence_no": envelope.sequence_no,
        "payload_hash_length": len(envelope.payload_sha256),
        "signature_algorithm": envelope.signature_algorithm,
        "signature_length": len(envelope.signature),
        "signature_verifies": verify_runtime_observation_envelope(
            envelope,
            payload,
            secret_key="release-check-secret",
        ),
        "tampered_payload_rejected": not verify_runtime_observation_envelope(
            envelope,
            tampered_payload,
            secret_key="release-check-secret",
        ),
        "raw_payload_embedded": envelope.boundary.raw_payload_embedded,
        "calls_safety_api": envelope.boundary.calls_safety_api,
        "connects_device_stream": envelope.boundary.connects_device_stream,
        "enables_incident_bridge": envelope.boundary.enables_incident_bridge,
        "writes_phase2_brain": envelope.boundary.writes_phase2_brain,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_input_admission() -> dict[str, Any]:
    try:
        from runtime_input_admission import (
            RuntimeInputAdmissionStatus,
            admit_runtime_observation_input,
            empty_runtime_input_admission_state,
        )
        from runtime_observation_envelope import (
            build_signed_runtime_observation_envelope,
        )
        from runtime_stream_policy import build_default_runtime_stream_policy_manifest
    except Exception as exc:
        return {
            "ok": False,
            "admission_status": None,
            "missing": [f"runtime_input_admission_import:{exc}"],
        }

    missing: list[str] = []
    secret_key = "release-check-secret"
    payload = {
        "timestamp": 60.0,
        "source": "apple_watch",
        "lat": 24.0,
        "lon": 121.0,
        "elevation_m": 1001.0,
        "gps_horizontal_accuracy_m": 8.0,
    }

    def make_envelope(sequence_no: int, observed_at: str):
        return build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key,
            envelope_id=f"runtime_observation_envelope.admission.{sequence_no:04d}",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport="http_push",
            device_id="watch.release_check.001",
            sequence_no=sequence_no,
            observed_at=observed_at,
            received_at=observed_at,
        )

    try:
        manifest = build_default_runtime_stream_policy_manifest()
        state = empty_runtime_input_admission_state()
        first = make_envelope(1, "2026-05-18T10:00:01.000+08:00")
        accepted = admit_runtime_observation_input(
            first,
            payload,
            secret_key=secret_key,
            policy_manifest=manifest,
            state=state,
        )
        tampered_payload = dict(payload)
        tampered_payload["lat"] = 25.0
        tampered = admit_runtime_observation_input(
            first,
            tampered_payload,
            secret_key=secret_key,
            policy_manifest=manifest,
            state=state,
        )
        duplicate = admit_runtime_observation_input(
            first,
            payload,
            secret_key=secret_key,
            policy_manifest=manifest,
            state=accepted.state_after,
        )
        second = make_envelope(2, "2026-05-18T10:00:01.050+08:00")
        backpressured = admit_runtime_observation_input(
            second,
            payload,
            secret_key=secret_key,
            policy_manifest=manifest,
            state=accepted.state_after,
        )
        third = make_envelope(3, "2026-05-18T10:00:03.000+08:00")
        queued = admit_runtime_observation_input(
            third,
            payload,
            secret_key=secret_key,
            policy_manifest=manifest,
            state=accepted.state_after,
            connected=False,
            retry_attempt=0,
        )
        fourth = make_envelope(4, "2026-05-18T10:00:04.000+08:00")
        retained = admit_runtime_observation_input(
            fourth,
            payload,
            secret_key=secret_key,
            policy_manifest=manifest,
            state=queued.state_after,
            connected=False,
            retry_attempt=manifest.buffering.retry_attempt_limit,
        )
    except Exception as exc:
        return {
            "ok": False,
            "admission_status": None,
            "missing": [f"runtime_input_admission_build:{exc}"],
        }

    serialized = "\n".join(
        [
            accepted.to_json(),
            tampered.to_json(),
            duplicate.to_json(),
            backpressured.to_json(),
            queued.to_json(),
            retained.to_json(),
        ]
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            '"lat"',
            '"lon"',
            "elevation_m",
            "gps_horizontal_accuracy_m",
            "sensorlog",
            "loggingTime",
        )
        if fragment in serialized
    ]

    if accepted.status != RuntimeInputAdmissionStatus.ADMITTED_NOT_FORWARDED:
        missing.append("runtime_input_admission_accepts_signed_policy_match")
    if not accepted.signature_verified:
        missing.append("runtime_input_admission_signature_verified")
    if not accepted.policy_matched:
        missing.append("runtime_input_admission_policy_matched")
    if not accepted.transport_allowed:
        missing.append("runtime_input_admission_transport_allowed")
    if not accepted.token_scope_allowed:
        missing.append("runtime_input_admission_token_scope_allowed")
    if accepted.boundary.creates_live_endpoint:
        missing.append("runtime_input_admission_no_live_endpoint")
    if accepted.boundary.calls_safety_api:
        missing.append("runtime_input_admission_no_safety_api")
    if accepted.boundary.forwards_to_runtime:
        missing.append("runtime_input_admission_no_runtime_forward")
    if accepted.boundary.connects_device_stream:
        missing.append("runtime_input_admission_no_device_stream")
    if accepted.boundary.enables_incident_bridge:
        missing.append("runtime_input_admission_no_incident_bridge")
    if accepted.boundary.writes_phase2_brain:
        missing.append("runtime_input_admission_no_phase2")
    if tampered.status != RuntimeInputAdmissionStatus.REJECTED_SIGNATURE:
        missing.append("runtime_input_admission_rejects_tampered_payload")
    if duplicate.status != RuntimeInputAdmissionStatus.REJECTED_DUPLICATE:
        missing.append("runtime_input_admission_rejects_duplicate")
    if backpressured.status != RuntimeInputAdmissionStatus.QUEUED_BACKPRESSURE:
        missing.append("runtime_input_admission_backpressure_queue")
    if queued.status != RuntimeInputAdmissionStatus.QUEUED_DISCONNECTED:
        missing.append("runtime_input_admission_disconnected_queue")
    if retained.status != RuntimeInputAdmissionStatus.LATEST_POINT_RETAINED:
        missing.append("runtime_input_admission_latest_point_retained")
    if accepted.counts.safety_api_call_count != 0:
        missing.append("runtime_input_admission_zero_safety_calls")
    if retained.counts.runtime_forward_count != 0:
        missing.append("runtime_input_admission_zero_runtime_forwards")
    if forbidden_fragments:
        missing.append(
            f"runtime_input_admission_forbidden_fragments:{','.join(forbidden_fragments)}"
        )

    return {
        "ok": not missing,
        "admission_status": accepted.status.value,
        "signature_verified": accepted.signature_verified,
        "policy_matched": accepted.policy_matched,
        "transport_allowed": accepted.transport_allowed,
        "token_scope_allowed": accepted.token_scope_allowed,
        "rejected_signature_status": tampered.status.value,
        "duplicate_status": duplicate.status.value,
        "backpressure_status": backpressured.status.value,
        "disconnected_status": queued.status.value,
        "retry_exhausted_status": retained.status.value,
        "backpressure_queue_depth": backpressured.queue_depth,
        "disconnected_queue_depth": queued.queue_depth,
        "latest_retained_count": len(retained.state_after.latest_retained_key_by_stream),
        "raw_payload_embedded": accepted.boundary.raw_payload_embedded,
        "creates_live_endpoint": accepted.boundary.creates_live_endpoint,
        "calls_safety_api": accepted.boundary.calls_safety_api,
        "forwards_to_runtime": accepted.boundary.forwards_to_runtime,
        "connects_device_stream": accepted.boundary.connects_device_stream,
        "enables_incident_bridge": accepted.boundary.enables_incident_bridge,
        "writes_phase2_brain": accepted.boundary.writes_phase2_brain,
        "safety_api_call_count": accepted.counts.safety_api_call_count,
        "runtime_forward_count": retained.counts.runtime_forward_count,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_safety_observation_admission_api(root: Path) -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient

        from runtime_observation_envelope import build_signed_runtime_observation_envelope
        from safety_api import (
            SafetyApiSnapshot,
            SafetyObservationAdmissionConfig,
            create_safety_app,
        )
        from safety_models import SafetyState
        from safety_runtime_session import SafetyRuntimeSession
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"safety_observation_admission_api_import:{exc}"],
        }

    missing: list[str] = []
    secret_key = "release-check-api-admission-secret"
    payload = {
        "loggingTime": 60.0,
        "locationLatitude": "24.0",
        "locationLongitude": "121.0",
        "locationAltitude": "1001.0",
        "locationHorizontalAccuracy": "8.0",
        "pedometerDistance": 12.0,
        "pedometerNumberOfSteps": 18,
        "accelerometerAccelerationX": "0.1",
    }

    try:
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(
            root / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
        )
        client = TestClient(
            create_safety_app(
                SafetyApiSnapshot(safety_state=SafetyState()),
                runtime_session=session,
                observation_admission_config=admission_config,
            )
        )
        envelope = build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key,
            envelope_id="runtime_observation_envelope.safety_api.release_check.v0",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport="http_push",
            device_id="watch.release_check.api.001",
            sequence_no=1,
            observed_at="2026-05-19T08:00:01+08:00",
            received_at="2026-05-19T08:00:01+08:00",
        )
        request_body = {
            "envelope": envelope.model_dump(mode="json"),
            "payload": payload,
            "device": "apple_watch",
            "source": "runtime_signed_sensorlog",
            "received_at": 60.0,
        }
        accepted_response = client.post("/safety/observations", json=request_body)
        duplicate_response = client.post("/safety/observations", json=request_body)
        tampered_payload = dict(payload)
        tampered_payload["locationLatitude"] = "25.0"
        tampered_response = client.post(
            "/safety/observations",
            json={
                **request_body,
                "payload": tampered_payload,
            },
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"safety_observation_admission_api_build:{exc}"],
        }

    accepted_json = accepted_response.json()
    duplicate_json = duplicate_response.json()
    tampered_json = tampered_response.json()
    admission_summary = accepted_json.get("admission", {})
    serialized_admission = json.dumps(
        admission_summary, ensure_ascii=False, sort_keys=True
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            '"locationLatitude"',
            '"locationLongitude"',
            "raw_payload",
            "sensorlog",
            "accelerometerAccelerationX",
        )
        if fragment in serialized_admission
    ]

    if accepted_response.status_code != 200:
        missing.append("safety_observation_admission_api_accepts_signed_request")
    if accepted_json.get("observations_accepted") != 1:
        missing.append("safety_observation_admission_api_observation_forwarded_once")
    if admission_summary.get("status") != "admitted_not_forwarded":
        missing.append("safety_observation_admission_api_admission_summary")
    if "payload" in admission_summary or "raw_payload" in admission_summary:
        missing.append("safety_observation_admission_api_no_raw_payload_summary")
    if duplicate_response.status_code != 409:
        missing.append("safety_observation_admission_api_duplicate_409")
    if duplicate_json.get("detail", {}).get("admission_status") != "rejected_duplicate":
        missing.append("safety_observation_admission_api_duplicate_rejected")
    if tampered_response.status_code != 403:
        missing.append("safety_observation_admission_api_tampered_403")
    if tampered_json.get("detail", {}).get("admission_status") != "rejected_signature":
        missing.append("safety_observation_admission_api_tampered_rejected")
    if session.snapshot().observations_processed != 1:
        missing.append("safety_observation_admission_api_blocks_rejected_before_runtime")
    if forbidden_fragments:
        missing.append(
            f"safety_observation_admission_api_forbidden_fragments:{','.join(forbidden_fragments)}"
        )

    return {
        "ok": not missing,
        "status": accepted_json.get("status"),
        "accepted_status_code": accepted_response.status_code,
        "duplicate_status_code": duplicate_response.status_code,
        "tampered_status_code": tampered_response.status_code,
        "admission_status": admission_summary.get("status"),
        "admission_source_id": admission_summary.get("source_id"),
        "admission_sequence_no": admission_summary.get("sequence_no"),
        "observations_accepted": accepted_json.get("observations_accepted"),
        "observations_processed_after_rejections": (
            session.snapshot().observations_processed
        ),
        "duplicate_admission_status": duplicate_json.get("detail", {}).get(
            "admission_status"
        ),
        "tampered_admission_status": tampered_json.get("detail", {}).get(
            "admission_status"
        ),
        "admission_summary_has_raw_payload": (
            "payload" in admission_summary or "raw_payload" in admission_summary
        ),
        "forbidden_fragment_count": len(forbidden_fragments),
        "incident_bridge_enabled": False,
        "phase2_writeback_count": 0,
        "missing": missing,
    }


def _check_server_safety_observation_admission_config(root: Path) -> dict[str, Any]:
    try:
        from server_safety_observation_admission_config import (
            create_safety_observation_admission_config_from_env,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"server_safety_observation_admission_config_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "server.py").exists() else REPO_ROOT
    source = (source_root / "server.py").read_text(encoding="utf-8")
    helper_source = (
        source_root / "server_safety_observation_admission_config.py"
    ).read_text(encoding="utf-8")
    combined_source = source + "\n" + helper_source
    env_tokens = [
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED",
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET",
        "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE",
    ]
    missing_tokens = [token for token in env_tokens if token not in combined_source]
    with tempfile.TemporaryDirectory() as tmpdir:
        secret_path = Path(tmpdir) / "admission.secret"
        secret_path.write_text("fedcba9876543210\n", encoding="utf-8")
        try:
            disabled_config = create_safety_observation_admission_config_from_env({})
            env_config = create_safety_observation_admission_config_from_env(
                {
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "0123456789abcdef",
                }
            )
            file_config = create_safety_observation_admission_config_from_env(
                {
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "true",
                    "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE": str(secret_path),
                }
            )
        except Exception as exc:
            return {
                "ok": False,
                "status": None,
                "missing": [f"server_safety_observation_admission_config_build:{exc}"],
            }

    missing_secret_rejected = _raises_value_error(
        lambda: create_safety_observation_admission_config_from_env(
            {"SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1"}
        )
    )
    short_secret_rejected = _raises_value_error(
        lambda: create_safety_observation_admission_config_from_env(
            {
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET": "short",
            }
        )
    )
    missing_file_rejected = _raises_value_error(
        lambda: create_safety_observation_admission_config_from_env(
            {
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED": "1",
                "SCOUT_SAFETY_OBSERVATION_ADMISSION_SECRET_FILE": "/missing/scout/admission.secret",
            }
        )
    )
    router_passes_config = (
        "observation_admission_config=safety_observation_admission_config" in source
    )
    fail_closed_guard = (
        "safety_observation_admission_config_error" in source
        and "raise safety_observation_admission_config_error" in source
    )

    if disabled_config is not None:
        missing.append("server_safety_observation_admission_config_default_disabled")
    if env_config is None:
        missing.append("server_safety_observation_admission_config_env_secret")
    if file_config is None:
        missing.append("server_safety_observation_admission_config_file_secret")
    if not missing_secret_rejected:
        missing.append("server_safety_observation_admission_config_missing_secret_rejected")
    if not short_secret_rejected:
        missing.append("server_safety_observation_admission_config_short_secret_rejected")
    if not missing_file_rejected:
        missing.append("server_safety_observation_admission_config_missing_file_rejected")
    if missing_tokens:
        missing.append(
            f"server_safety_observation_admission_config_missing_tokens:{','.join(missing_tokens)}"
        )
    if not router_passes_config:
        missing.append("server_safety_observation_admission_config_router_passes_config")
    if not fail_closed_guard:
        missing.append("server_safety_observation_admission_config_fail_closed_guard")

    return {
        "ok": not missing,
        "status": "configured_disabled_by_default",
        "disabled_by_default": disabled_config is None,
        "env_secret_supported": env_config is not None,
        "secret_file_supported": file_config is not None,
        "missing_secret_rejected": missing_secret_rejected,
        "short_secret_rejected": short_secret_rejected,
        "missing_file_rejected": missing_file_rejected,
        "router_passes_config": router_passes_config,
        "fail_closed_guard": fail_closed_guard,
        "env_tokens_present": not missing_tokens,
        "secret_value_exposed": False,
        "missing": missing,
    }


def _check_runtime_stream_transport_api(root: Path) -> dict[str, Any]:
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime_observation_envelope import build_signed_runtime_observation_envelope
        from runtime_stream_transport_api import create_runtime_stream_transport_router
        from safety_api import SafetyObservationAdmissionConfig
        from safety_runtime_session import SafetyRuntimeSession
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_transport_api_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "server.py").exists() else REPO_ROOT
    server_source = (source_root / "server.py").read_text(encoding="utf-8")
    router_source = (source_root / "runtime_stream_transport_api.py").read_text(
        encoding="utf-8"
    )
    secret_key = "release-check-runtime-stream-secret"
    payload = {
        "loggingTime": 60.0,
        "locationLatitude": "24.0",
        "locationLongitude": "121.0",
        "locationAltitude": "1001.0",
        "locationHorizontalAccuracy": "8.0",
        "pedometerDistance": 12.0,
        "pedometerNumberOfSteps": 18,
        "accelerometerAccelerationX": "0.1",
    }

    def build_client() -> tuple[TestClient, SafetyRuntimeSession]:
        session = SafetyRuntimeSession(
            root / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
        )
        app = FastAPI()
        app.include_router(
            create_runtime_stream_transport_router(
                runtime_session=session,
                observation_admission_config=SafetyObservationAdmissionConfig(
                    secret_key=secret_key
                ),
            )
        )
        return TestClient(app), session

    def make_envelope(sequence_no: int, transport: str):
        return build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key,
            envelope_id=f"runtime_stream_transport.release_check.{sequence_no:04d}",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport=transport,
            device_id="watch.release_check.transport.001",
            sequence_no=sequence_no,
            observed_at=f"2026-05-19T08:00:0{sequence_no}+08:00",
            received_at=f"2026-05-19T08:00:0{sequence_no}+08:00",
        )

    try:
        http_client, http_session = build_client()
        http_envelope = make_envelope(1, "http_push")
        http_response = http_client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": http_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
                "received_at": 60.0,
            },
        )
        http_body = http_response.json()

        websocket_client, websocket_session = build_client()
        websocket_envelope = make_envelope(1, "websocket")
        with websocket_client.websocket_connect(
            "/runtime/streams/websocket/observations"
        ) as websocket:
            websocket.send_json(
                {
                    "envelope": websocket_envelope.model_dump(mode="json"),
                    "payload": payload,
                    "device": "apple_watch",
                    "source": "runtime_websocket_sensorlog",
                    "received_at": 60.0,
                }
            )
            websocket_body = websocket.receive_json()

        mismatch_client, mismatch_session = build_client()
        mismatch_envelope = make_envelope(1, "websocket")
        mismatch_response = mismatch_client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": mismatch_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        mismatch_body = mismatch_response.json()
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_transport_api_build:{exc}"],
        }

    server_mount_guard = (
        "_include_runtime_stream_transport_router(app)" in server_source
        and "safety_runtime_session is None" in server_source
        and "safety_observation_admission_config is None" in server_source
    )
    router_requires_signed_admission = (
        "SafetyObservationAdmissionConfig" in router_source
        and "ingest_safety_observation_body" in router_source
    )
    router_has_http_push = (
        '"/http-push/observations"' in router_source
        and "RuntimeStreamTransportKind.HTTP_PUSH" in router_source
    )
    router_has_websocket = (
        '"/websocket/observations"' in router_source
        and "RuntimeStreamTransportKind.WEBSOCKET" in router_source
    )
    admission_summaries = [
        http_body.get("admission", {}),
        websocket_body.get("admission", {}),
    ]
    serialized_admission = json.dumps(
        admission_summaries, ensure_ascii=False, sort_keys=True
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            '"locationLatitude"',
            '"locationLongitude"',
            "raw_payload",
            "sensorlog",
            "accelerometerAccelerationX",
        )
        if fragment in serialized_admission
    ]

    if http_response.status_code != 200:
        missing.append("runtime_stream_transport_api_http_push_accepts_signed")
    if http_body.get("transport_surface") != "http_push":
        missing.append("runtime_stream_transport_api_http_push_surface")
    if http_body.get("admission", {}).get("transport") != "http_push":
        missing.append("runtime_stream_transport_api_http_push_admission_transport")
    if http_session.snapshot().observations_processed != 1:
        missing.append("runtime_stream_transport_api_http_push_runtime_processed_once")
    if websocket_body.get("status") != "accepted":
        missing.append("runtime_stream_transport_api_websocket_accepts_signed")
    if websocket_body.get("transport_surface") != "websocket":
        missing.append("runtime_stream_transport_api_websocket_surface")
    if websocket_body.get("admission", {}).get("transport") != "websocket":
        missing.append("runtime_stream_transport_api_websocket_admission_transport")
    if websocket_session.snapshot().observations_processed != 1:
        missing.append("runtime_stream_transport_api_websocket_runtime_processed_once")
    if mismatch_response.status_code != 422:
        missing.append("runtime_stream_transport_api_transport_mismatch_422")
    if mismatch_body.get("detail", {}).get("reason") != "transport_endpoint_mismatch":
        missing.append("runtime_stream_transport_api_transport_mismatch_reason")
    if mismatch_session.snapshot().observations_processed != 0:
        missing.append("runtime_stream_transport_api_transport_mismatch_blocks_runtime")
    if not server_mount_guard:
        missing.append("runtime_stream_transport_api_server_mount_guard")
    if not router_requires_signed_admission:
        missing.append("runtime_stream_transport_api_requires_signed_admission")
    if not router_has_http_push:
        missing.append("runtime_stream_transport_api_http_push_route")
    if not router_has_websocket:
        missing.append("runtime_stream_transport_api_websocket_route")
    if forbidden_fragments:
        missing.append(
            f"runtime_stream_transport_api_forbidden_fragments:{','.join(forbidden_fragments)}"
        )

    return {
        "ok": not missing,
        "status": "transport_surface_enabled_when_signed",
        "http_push_status_code": http_response.status_code,
        "http_push_transport_surface": http_body.get("transport_surface"),
        "http_push_admission_status": http_body.get("admission", {}).get("status"),
        "http_push_observations_processed": (
            http_session.snapshot().observations_processed
        ),
        "websocket_status": websocket_body.get("status"),
        "websocket_transport_surface": websocket_body.get("transport_surface"),
        "websocket_admission_status": websocket_body.get("admission", {}).get(
            "status"
        ),
        "websocket_observations_processed": (
            websocket_session.snapshot().observations_processed
        ),
        "mismatch_status_code": mismatch_response.status_code,
        "mismatch_reason": mismatch_body.get("detail", {}).get("reason"),
        "mismatch_observations_processed": (
            mismatch_session.snapshot().observations_processed
        ),
        "server_mount_guard": server_mount_guard,
        "requires_signed_admission": router_requires_signed_admission,
        "http_push_route_present": router_has_http_push,
        "websocket_route_present": router_has_websocket,
        "admission_summary_has_raw_payload": bool(forbidden_fragments),
        "incident_bridge_enabled": False,
        "phase2_writeback_count": 0,
        "missing": missing,
    }


def _check_runtime_stream_telemetry(root: Path) -> dict[str, Any]:
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime_observation_envelope import build_signed_runtime_observation_envelope
        from runtime_stream_telemetry import RuntimeStreamTelemetryStore
        from runtime_stream_transport_api import create_runtime_stream_transport_router
        from safety_api import SafetyObservationAdmissionConfig
        from safety_runtime_session import SafetyRuntimeSession
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_telemetry_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "runtime_stream_transport_api.py").exists() else REPO_ROOT
    telemetry_source = (source_root / "runtime_stream_telemetry.py").read_text(
        encoding="utf-8"
    )
    router_source = (source_root / "runtime_stream_transport_api.py").read_text(
        encoding="utf-8"
    )
    secret_key = "release-check-runtime-stream-telemetry-secret"
    payload = {
        "loggingTime": 60.0,
        "locationLatitude": "24.0",
        "locationLongitude": "121.0",
        "locationAltitude": "1001.0",
        "locationHorizontalAccuracy": "8.0",
        "pedometerDistance": 12.0,
        "pedometerNumberOfSteps": 18,
        "accelerometerAccelerationX": "0.1",
    }

    try:
        telemetry_store = RuntimeStreamTelemetryStore()
        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        session = SafetyRuntimeSession(
            root / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
        )
        app = FastAPI()
        app.include_router(
            create_runtime_stream_transport_router(
                runtime_session=session,
                observation_admission_config=admission_config,
                telemetry_store=telemetry_store,
            )
        )
        client = TestClient(app)
        initial = client.get("/runtime/streams/status").json()
        accepted_envelope = build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key,
            envelope_id="runtime_stream_telemetry.release_check.accepted.v0",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport="http_push",
            device_id="watch.release_check.telemetry.001",
            sequence_no=1,
            observed_at="2026-05-19T08:00:01+08:00",
            received_at="2026-05-19T08:00:01+08:00",
        )
        mismatch_envelope = build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key,
            envelope_id="runtime_stream_telemetry.release_check.mismatch.v0",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport="websocket",
            device_id="watch.release_check.telemetry.001",
            sequence_no=2,
            observed_at="2026-05-19T08:00:02+08:00",
            received_at="2026-05-19T08:00:02+08:00",
        )
        accepted_response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": accepted_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        mismatch_response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": mismatch_envelope.model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        observed = client.get("/runtime/streams/status").json()
        telemetry_store.record_websocket_connected()
        connected = telemetry_store.snapshot(
            admission_state=admission_config.state
        ).model_dump(mode="json")
        telemetry_store.record_websocket_disconnected()
        closed = telemetry_store.snapshot(
            admission_state=admission_config.state
        ).model_dump(mode="json")
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_telemetry_build:{exc}"],
        }

    http_surface = observed.get("transport_surfaces", {}).get("http_push", {})
    serialized = json.dumps(observed, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = [
        fragment
        for fragment in (
            '"locationLatitude"',
            '"locationLongitude"',
            "accelerometerAccelerationX",
            '"payload":',
        )
        if fragment in serialized
    ]
    status_route_present = '"/status"' in router_source
    store_injected = (
        "telemetry_store: RuntimeStreamTelemetryStore | None = None" in router_source
        and "telemetry_store or RuntimeStreamTelemetryStore()" in router_source
    )
    boundary_declared = (
        "RuntimeStreamTelemetryBoundary" in telemetry_source
        and "raw_payload_embedded" in telemetry_source
        and "incident_bridge_enabled" in telemetry_source
        and "phase2_writeback_count" in telemetry_source
    )

    if initial.get("status") != "idle":
        missing.append("runtime_stream_telemetry_initial_idle")
    if accepted_response.status_code != 200:
        missing.append("runtime_stream_telemetry_accepts_signed_http")
    if mismatch_response.status_code != 422:
        missing.append("runtime_stream_telemetry_records_rejection")
    if observed.get("status") != "observing":
        missing.append("runtime_stream_telemetry_observing_status")
    if observed.get("totals", {}).get("accepted_count") != 1:
        missing.append("runtime_stream_telemetry_accepted_count")
    if observed.get("totals", {}).get("rejected_count") != 1:
        missing.append("runtime_stream_telemetry_rejected_count")
    if http_surface.get("last_admission_status") != "admitted_not_forwarded":
        missing.append("runtime_stream_telemetry_last_admission_status")
    if http_surface.get("last_rejection_reason") != "transport_endpoint_mismatch":
        missing.append("runtime_stream_telemetry_last_rejection_reason")
    if observed.get("admission_state", {}).get("seen_dedupe_key_count") != 1:
        missing.append("runtime_stream_telemetry_seen_dedupe_summary")
    if connected.get("transport_surfaces", {}).get("websocket", {}).get(
        "connection_status"
    ) != "connected":
        missing.append("runtime_stream_telemetry_websocket_connected")
    if closed.get("transport_surfaces", {}).get("websocket", {}).get(
        "connection_status"
    ) != "closed":
        missing.append("runtime_stream_telemetry_websocket_closed")
    if closed.get("totals", {}).get("active_websocket_connections") != 0:
        missing.append("runtime_stream_telemetry_websocket_connection_count")
    if observed.get("boundary", {}).get("raw_payload_embedded") is not False:
        missing.append("runtime_stream_telemetry_no_raw_payload_boundary")
    if observed.get("boundary", {}).get("incident_bridge_enabled") is not False:
        missing.append("runtime_stream_telemetry_no_incident_bridge")
    if observed.get("boundary", {}).get("phase2_writeback_count") != 0:
        missing.append("runtime_stream_telemetry_no_phase2_writeback")
    if not status_route_present:
        missing.append("runtime_stream_telemetry_status_route")
    if not store_injected:
        missing.append("runtime_stream_telemetry_store_injection")
    if not boundary_declared:
        missing.append("runtime_stream_telemetry_boundary_declared")
    if forbidden_fragments:
        missing.append(
            f"runtime_stream_telemetry_forbidden_fragments:{','.join(forbidden_fragments)}"
        )

    return {
        "ok": not missing,
        "status": "telemetry_ready",
        "initial_status": initial.get("status"),
        "observed_status": observed.get("status"),
        "accepted_count": observed.get("totals", {}).get("accepted_count"),
        "rejected_count": observed.get("totals", {}).get("rejected_count"),
        "queued_count": observed.get("totals", {}).get("queued_count"),
        "active_websocket_connections": closed.get("totals", {}).get(
            "active_websocket_connections"
        ),
        "http_last_admission_status": http_surface.get("last_admission_status"),
        "http_last_rejection_reason": http_surface.get("last_rejection_reason"),
        "seen_dedupe_key_count": observed.get("admission_state", {}).get(
            "seen_dedupe_key_count"
        ),
        "backpressure_queue_depth": observed.get("admission_state", {}).get(
            "backpressure_queue_depth"
        ),
        "disconnected_queue_depth": observed.get("admission_state", {}).get(
            "disconnected_queue_depth"
        ),
        "websocket_connection_lifecycle": [
            initial.get("transport_surfaces", {}).get("websocket", {}).get(
                "connection_status"
            ),
            connected.get("transport_surfaces", {}).get("websocket", {}).get(
                "connection_status"
            ),
            closed.get("transport_surfaces", {}).get("websocket", {}).get(
                "connection_status"
            ),
        ],
        "status_route_present": status_route_present,
        "store_injected": store_injected,
        "boundary_declared": boundary_declared,
        "raw_payload_embedded": observed.get("boundary", {}).get(
            "raw_payload_embedded"
        ),
        "incident_bridge_enabled": observed.get("boundary", {}).get(
            "incident_bridge_enabled"
        ),
        "phase2_writeback_count": observed.get("boundary", {}).get(
            "phase2_writeback_count"
        ),
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_stream_controls(root: Path) -> dict[str, Any]:
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from runtime_input_admission import RuntimeInputAdmissionState
        from runtime_observation_envelope import build_signed_runtime_observation_envelope
        from runtime_stream_controls import RuntimeStreamControlStore
        from runtime_stream_transport_api import create_runtime_stream_transport_router
        from safety_api import SafetyObservationAdmissionConfig
        from safety_runtime_session import SafetyRuntimeSession
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_controls_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "runtime_stream_controls.py").exists() else REPO_ROOT
    controls_source = (source_root / "runtime_stream_controls.py").read_text(
        encoding="utf-8"
    )
    router_source = (source_root / "runtime_stream_transport_api.py").read_text(
        encoding="utf-8"
    )
    secret_key = "release-check-runtime-stream-controls-secret"
    payload = {
        "loggingTime": 60.0,
        "locationLatitude": "24.0",
        "locationLongitude": "121.0",
        "locationAltitude": "1001.0",
        "locationHorizontalAccuracy": "8.0",
        "pedometerDistance": 12.0,
        "pedometerNumberOfSteps": 18,
        "accelerometerAccelerationX": "0.1",
    }

    def make_envelope(sequence_no: int):
        return build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key,
            envelope_id=f"runtime_stream_controls.release_check.{sequence_no:04d}",
            source_id="runtime_source.apple_watch.v0",
            source_kind="apple_watch",
            transport="http_push",
            device_id="watch.release_check.controls.001",
            sequence_no=sequence_no,
            observed_at=f"2026-05-19T08:00:0{sequence_no}+08:00",
            received_at=f"2026-05-19T08:00:0{sequence_no}+08:00",
        )

    try:
        store = RuntimeStreamControlStore()
        initial = store.snapshot().model_dump(mode="json")
        direct_pause = store.pause(
            operator_id="admin.local",
            reason="release check pause",
        )
        direct_resume = store.resume(
            operator_id="admin.local",
            reason="release check resume",
        )
        direct_end = store.end(
            operator_id="admin.local",
            reason="release check end",
        )
        terminal_resume_rejected = _raises_value_error(
            lambda: store.resume(operator_id="admin.local", reason="invalid")
        )
        queue_state = RuntimeInputAdmissionState(
            seen_dedupe_keys=["dedupe-a"],
            disconnected_queue_keys=["queued-a"],
            backpressure_queue_keys=["backpressure-a"],
            latest_retained_key_by_stream={"stream-a": "latest-a"},
        )
        drain_store = RuntimeStreamControlStore()
        drain_record = drain_store.drain_queue(
            queue_state,
            operator_id="admin.local",
            reason="release check drain",
        )

        admission_config = SafetyObservationAdmissionConfig(secret_key=secret_key)
        api_store = RuntimeStreamControlStore()
        session = SafetyRuntimeSession(
            root / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
        )
        app = FastAPI()
        app.include_router(
            create_runtime_stream_transport_router(
                runtime_session=session,
                observation_admission_config=admission_config,
                control_store=api_store,
            )
        )
        client = TestClient(app)
        pause_response = client.post(
            "/runtime/streams/control/pause",
            json={"operator_id": "admin.local", "reason": "pause"},
        )
        paused_response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": make_envelope(1).model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        resume_response = client.post(
            "/runtime/streams/control/resume",
            json={"operator_id": "admin.local", "reason": "resume"},
        )
        accepted_response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": make_envelope(2).model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        admission_config.state.disconnected_queue_keys.append("queued-a")
        admission_config.state.backpressure_queue_keys.append("backpressure-a")
        drain_response = client.post(
            "/runtime/streams/control/drain-queue",
            json={"operator_id": "admin.local", "reason": "drain"},
        )
        end_response = client.post(
            "/runtime/streams/control/end",
            json={"operator_id": "admin.local", "reason": "end"},
        )
        ended_response = client.post(
            "/runtime/streams/http-push/observations",
            json={
                "envelope": make_envelope(3).model_dump(mode="json"),
                "payload": payload,
                "device": "apple_watch",
                "source": "runtime_http_push_sensorlog",
            },
        )
        status_response = client.get("/runtime/streams/status")
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_stream_controls_build:{exc}"],
        }

    direct_boundary = direct_end.record.boundary.model_dump(mode="json")
    status_body = status_response.json()
    paused_body = paused_response.json()
    ended_body = ended_response.json()
    serialized_records = json.dumps(
        [
            initial,
            direct_pause.model_dump(mode="json"),
            direct_resume.model_dump(mode="json"),
            direct_end.model_dump(mode="json"),
            drain_record.model_dump(mode="json"),
            status_body.get("control", {}),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            '"locationLatitude"',
            '"locationLongitude"',
            "accelerometerAccelerationX",
            '"payload":',
        )
        if fragment in serialized_records
    ]
    route_tokens_present = all(
        token in router_source
        for token in (
            '"/control/status"',
            '"/control/pause"',
            '"/control/resume"',
            '"/control/end"',
            '"/control/drain-queue"',
        )
    )
    store_injected = (
        "control_store: RuntimeStreamControlStore | None = None" in router_source
        and "control_store or RuntimeStreamControlStore()" in router_source
    )
    boundary_declared = all(
        token in controls_source
        for token in (
            "local_control_only",
            "controls_device_hardware",
            "incident_bridge_enabled",
            "phase2_writeback_count",
            "raw_payload_embedded",
        )
    )

    if initial.get("status") != "observing":
        missing.append("runtime_stream_controls_initial_observing")
    if direct_pause.snapshot_after.status != "paused":
        missing.append("runtime_stream_controls_pause_to_paused")
    if direct_resume.snapshot_after.status != "observing":
        missing.append("runtime_stream_controls_resume_to_observing")
    if direct_end.snapshot_after.status != "ended":
        missing.append("runtime_stream_controls_end_to_terminal")
    if not terminal_resume_rejected:
        missing.append("runtime_stream_controls_terminal_resume_rejected")
    if drain_record.queue_depth_before != 2 or drain_record.queue_depth_after != 0:
        missing.append("runtime_stream_controls_drain_queue_depth")
    if queue_state.seen_dedupe_keys != ["dedupe-a"]:
        missing.append("runtime_stream_controls_drain_keeps_dedupe")
    if queue_state.disconnected_queue_keys or queue_state.backpressure_queue_keys:
        missing.append("runtime_stream_controls_drain_clears_queues")
    if queue_state.latest_retained_key_by_stream:
        missing.append("runtime_stream_controls_drain_clears_latest_retained")
    if pause_response.status_code != 200:
        missing.append("runtime_stream_controls_api_pause")
    if paused_response.status_code != 409:
        missing.append("runtime_stream_controls_api_paused_blocks_observation")
    if paused_body.get("detail", {}).get("reason") != "runtime_stream_paused":
        missing.append("runtime_stream_controls_api_paused_reason")
    if resume_response.status_code != 200:
        missing.append("runtime_stream_controls_api_resume")
    if accepted_response.status_code != 200:
        missing.append("runtime_stream_controls_api_resume_accepts_observation")
    if session.snapshot().observations_processed != 1:
        missing.append("runtime_stream_controls_api_runtime_processed_once")
    if drain_response.status_code != 200:
        missing.append("runtime_stream_controls_api_drain_queue")
    if drain_response.json().get("queue_depth_before") != 2:
        missing.append("runtime_stream_controls_api_drain_before")
    if drain_response.json().get("queue_depth_after") != 0:
        missing.append("runtime_stream_controls_api_drain_after")
    if end_response.status_code != 200:
        missing.append("runtime_stream_controls_api_end")
    if ended_response.status_code != 409:
        missing.append("runtime_stream_controls_api_ended_blocks_observation")
    if ended_body.get("detail", {}).get("reason") != "runtime_stream_ended":
        missing.append("runtime_stream_controls_api_ended_reason")
    if status_body.get("control", {}).get("status") != "ended":
        missing.append("runtime_stream_controls_status_in_telemetry")
    if direct_boundary.get("raw_payload_embedded") is not False:
        missing.append("runtime_stream_controls_no_raw_payload_boundary")
    if direct_boundary.get("controls_device_hardware") is not False:
        missing.append("runtime_stream_controls_no_hardware_control")
    if direct_boundary.get("incident_bridge_enabled") is not False:
        missing.append("runtime_stream_controls_no_incident_bridge")
    if direct_boundary.get("phase2_writeback_count") != 0:
        missing.append("runtime_stream_controls_no_phase2_writeback")
    if not route_tokens_present:
        missing.append("runtime_stream_controls_routes")
    if not store_injected:
        missing.append("runtime_stream_controls_store_injected")
    if not boundary_declared:
        missing.append("runtime_stream_controls_boundary_declared")
    if forbidden_fragments:
        missing.append(
            f"runtime_stream_controls_forbidden_fragments:{','.join(forbidden_fragments)}"
        )

    return {
        "ok": not missing,
        "status": "local_controls_ready",
        "initial_status": initial.get("status"),
        "pause_status": direct_pause.snapshot_after.status.value,
        "resume_status": direct_resume.snapshot_after.status.value,
        "end_status": direct_end.snapshot_after.status.value,
        "terminal_resume_rejected": terminal_resume_rejected,
        "drain_queue_depth_before": drain_record.queue_depth_before,
        "drain_queue_depth_after": drain_record.queue_depth_after,
        "dedupe_keys_preserved_after_drain": queue_state.seen_dedupe_keys,
        "api_pause_status_code": pause_response.status_code,
        "api_paused_observation_status_code": paused_response.status_code,
        "api_paused_rejection_reason": paused_body.get("detail", {}).get("reason"),
        "api_resume_status_code": resume_response.status_code,
        "api_accepted_after_resume_status_code": accepted_response.status_code,
        "api_drain_queue_depth_before": drain_response.json().get("queue_depth_before"),
        "api_drain_queue_depth_after": drain_response.json().get("queue_depth_after"),
        "api_end_status_code": end_response.status_code,
        "api_ended_observation_status_code": ended_response.status_code,
        "api_ended_rejection_reason": ended_body.get("detail", {}).get("reason"),
        "observations_processed": session.snapshot().observations_processed,
        "status_snapshot_control_status": status_body.get("control", {}).get("status"),
        "route_tokens_present": route_tokens_present,
        "store_injected": store_injected,
        "boundary_declared": boundary_declared,
        "raw_payload_embedded": direct_boundary.get("raw_payload_embedded"),
        "controls_device_hardware": direct_boundary.get("controls_device_hardware"),
        "incident_bridge_enabled": direct_boundary.get("incident_bridge_enabled"),
        "phase2_writeback_count": direct_boundary.get("phase2_writeback_count"),
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _raises_value_error(callback: Any) -> bool:
    try:
        callback()
    except ValueError:
        return True
    return False


def _check_runtime_incident_bridge_opt_in() -> dict[str, Any]:
    try:
        from runtime_incident_bridge_opt_in import (
            RuntimeIncidentBridgeOptInStatus,
            build_runtime_incident_bridge_opt_in_decision,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_incident_bridge_opt_in_import:{exc}"],
        }

    missing: list[str] = []
    default_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="observing",
        operator_opt_in=False,
    )
    blocked_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="observing",
        operator_opt_in=True,
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    ready_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="observing",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    terminal_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="ended",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )

    if default_decision.status != RuntimeIncidentBridgeOptInStatus.OPT_IN_REQUIRED:
        missing.append("runtime_incident_bridge_opt_in_default_requires_opt_in")
    if blocked_decision.status != RuntimeIncidentBridgeOptInStatus.BLOCKED:
        missing.append("runtime_incident_bridge_opt_in_missing_policy_blocked")
    if blocked_decision.blocker_reasons != ["missing_remote_contact_policy_ref"]:
        missing.append("runtime_incident_bridge_opt_in_remote_contact_required")
    if ready_decision.status != RuntimeIncidentBridgeOptInStatus.READY_NOT_ENABLED:
        missing.append("runtime_incident_bridge_opt_in_ready_not_enabled")
    if not ready_decision.bridge_enable_allowed_after_guard:
        missing.append("runtime_incident_bridge_opt_in_ready_flag")
    if terminal_decision.status != RuntimeIncidentBridgeOptInStatus.BLOCKED:
        missing.append("runtime_incident_bridge_opt_in_terminal_blocked")
    if terminal_decision.blocker_reasons != ["runtime_status_not_observing_or_paused"]:
        missing.append("runtime_incident_bridge_opt_in_runtime_status_required")
    for name, decision in (
        ("default", default_decision),
        ("blocked", blocked_decision),
        ("ready", ready_decision),
        ("terminal", terminal_decision),
    ):
        if decision.remote_notifications_enabled:
            missing.append(f"runtime_incident_bridge_opt_in_notification_enabled:{name}")
        if decision.enable_performed:
            missing.append(f"runtime_incident_bridge_opt_in_enable_performed:{name}")
        if decision.counts.incident_bridge_enable_count != 0:
            missing.append(f"runtime_incident_bridge_opt_in_bridge_count:{name}")
        if decision.counts.remote_notification_send_count != 0:
            missing.append(f"runtime_incident_bridge_opt_in_notification_count:{name}")
        if decision.counts.phase2_writeback_count != 0:
            missing.append(f"runtime_incident_bridge_opt_in_phase2:{name}")
        if decision.boundary.sends_remote_notification:
            missing.append(f"runtime_incident_bridge_opt_in_boundary_notification:{name}")
        if decision.boundary.enables_phase1_incident_bridge:
            missing.append(f"runtime_incident_bridge_opt_in_boundary_bridge:{name}")
        if decision.boundary.writes_phase2_brain:
            missing.append(f"runtime_incident_bridge_opt_in_boundary_phase2:{name}")

    return {
        "ok": not missing,
        "default_status": default_decision.status.value,
        "blocked_status": blocked_decision.status.value,
        "ready_status": ready_decision.status.value,
        "terminal_status": terminal_decision.status.value,
        "ready_bridge_enable_allowed_after_guard": (
            ready_decision.bridge_enable_allowed_after_guard
        ),
        "remote_notifications_enabled": ready_decision.remote_notifications_enabled,
        "enable_performed": ready_decision.enable_performed,
        "incident_bridge_enable_count": ready_decision.counts.incident_bridge_enable_count,
        "remote_notification_send_count": (
            ready_decision.counts.remote_notification_send_count
        ),
        "phase2_writeback_count": ready_decision.counts.phase2_writeback_count,
        "boundary_ok": (
            ready_decision.boundary.opt_in_guard_only
            and not ready_decision.boundary.sends_remote_notification
            and not ready_decision.boundary.enables_phase1_incident_bridge
            and not ready_decision.boundary.writes_phase2_brain
        ),
        "missing": missing,
    }


def _check_runtime_incident_bridge_enablement_dry_run(root: Path) -> dict[str, Any]:
    try:
        from mock_outbound_transport import MockOutboundTransport
        from runtime_debug_log import MemoryRuntimeDebugEventLog
        from runtime_incident_bridge_enablement import (
            RuntimeIncidentBridgeEnablementStatus,
            build_runtime_incident_bridge_enablement_dry_run,
        )
        from runtime_incident_bridge_opt_in import (
            build_runtime_incident_bridge_opt_in_decision,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_incident_bridge_enablement_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "runtime_incident_bridge_enablement.py").exists() else REPO_ROOT
    source = (source_root / "runtime_incident_bridge_enablement.py").read_text(
        encoding="utf-8"
    )
    default_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="observing",
        operator_opt_in=False,
    )
    ready_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="observing",
        operator_opt_in=True,
        remote_contact_policy_ref="remote_contact_policy.family.v0",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    log = MemoryRuntimeDebugEventLog()
    timestamps = iter(
        [
            "2026-05-19T23:00:01Z",
            "2026-05-19T23:00:02Z",
            "2026-05-19T23:00:03Z",
        ]
    )
    transport = MockOutboundTransport(
        session_id="runtime_session.release_check",
        mission_id="mission.release_check",
        debug_log=log,
        timestamp_factory=lambda: next(timestamps),
    )
    blocked_record = build_runtime_incident_bridge_enablement_dry_run(
        opt_in_decision=default_decision,
        operator_id="admin.release_check",
        recipient_refs=["remote_contact.primary"],
        reason="release check blocked dry run",
        outbound_transport=transport,
        timestamp_factory=lambda: "2026-05-19T23:00:00Z",
    )
    ready_record = build_runtime_incident_bridge_enablement_dry_run(
        opt_in_decision=ready_decision,
        operator_id="admin.release_check",
        recipient_refs=["remote_contact.primary", "remote_contact.backup"],
        reason="release check ready dry run",
        outbound_transport=transport,
        timestamp_factory=lambda: "2026-05-19T23:00:00Z",
    )
    missing_recipient_record = build_runtime_incident_bridge_enablement_dry_run(
        opt_in_decision=ready_decision,
        operator_id="admin.release_check",
        recipient_refs=[],
        reason="release check missing recipients",
        outbound_transport=None,
        timestamp_factory=lambda: "2026-05-19T23:00:00Z",
    )
    messages = transport.list_messages()
    serialized = json.dumps(
        [
            blocked_record.model_dump(mode="json"),
            ready_record.model_dump(mode="json"),
            missing_recipient_record.model_dump(mode="json"),
            [message.model_dump(mode="json") for message in messages],
            [event.model_dump(mode="json") for event in log.list_events()],
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"raw_payload":',
        )
        if fragment in serialized
    ]
    source_has_network = any(
        token in source for token in ("requests", "httpx", "urllib", "twilio")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source

    if blocked_record.status != RuntimeIncidentBridgeEnablementStatus.BLOCKED:
        missing.append("runtime_incident_bridge_enablement_blocks_guard_not_ready")
    if blocked_record.blocker_reasons != ["opt_in_guard_not_ready"]:
        missing.append("runtime_incident_bridge_enablement_guard_block_reason")
    if ready_record.status != RuntimeIncidentBridgeEnablementStatus.DRY_RUN_RECORDED:
        missing.append("runtime_incident_bridge_enablement_dry_run_recorded")
    if ready_record.guard_status != "ready_not_enabled":
        missing.append("runtime_incident_bridge_enablement_guard_status")
    if ready_record.counts.mock_outbound_message_count != 2:
        missing.append("runtime_incident_bridge_enablement_mock_message_count")
    if ready_record.counts.incident_bridge_enable_count != 0:
        missing.append("runtime_incident_bridge_enablement_no_bridge_enable")
    if ready_record.counts.remote_notification_send_count != 0:
        missing.append("runtime_incident_bridge_enablement_no_real_notification")
    if ready_record.counts.phase2_writeback_count != 0:
        missing.append("runtime_incident_bridge_enablement_no_phase2")
    if ready_record.remote_notifications_enabled:
        missing.append("runtime_incident_bridge_enablement_notifications_disabled")
    if ready_record.enable_performed:
        missing.append("runtime_incident_bridge_enablement_not_performed")
    if not ready_record.boundary.dry_run_only:
        missing.append("runtime_incident_bridge_enablement_dry_run_boundary")
    if not ready_record.boundary.uses_mock_outbound_transport:
        missing.append("runtime_incident_bridge_enablement_mock_boundary")
    if ready_record.boundary.sends_real_remote_notification:
        missing.append("runtime_incident_bridge_enablement_boundary_notification")
    if ready_record.boundary.enables_phase1_incident_bridge:
        missing.append("runtime_incident_bridge_enablement_boundary_phase1_bridge")
    if ready_record.boundary.writes_phase2_brain:
        missing.append("runtime_incident_bridge_enablement_boundary_phase2")
    if missing_recipient_record.blocker_reasons != ["missing_recipient_refs"]:
        missing.append("runtime_incident_bridge_enablement_recipient_required")
    if [message.transport for message in messages] != ["mock", "mock"]:
        missing.append("runtime_incident_bridge_enablement_mock_transport_only")
    if [message.category for message in messages] != ["remote_status", "remote_status"]:
        missing.append("runtime_incident_bridge_enablement_remote_status_category")
    if any(message.boundary.real_sos_sent for message in messages):
        missing.append("runtime_incident_bridge_enablement_no_real_sos")
    if any(message.boundary.real_sms_sent for message in messages):
        missing.append("runtime_incident_bridge_enablement_no_real_sms")
    if any(message.boundary.real_satellite_sent for message in messages):
        missing.append("runtime_incident_bridge_enablement_no_real_satellite")
    if [event.kind for event in log.list_events()] != [
        "outbound_message_queued",
        "outbound_message_queued",
    ]:
        missing.append("runtime_incident_bridge_enablement_debug_events")
    if source_has_network:
        missing.append("runtime_incident_bridge_enablement_no_network_imports")
    if source_has_phase1_bridge:
        missing.append("runtime_incident_bridge_enablement_no_phase1_bridge_import")
    if source_has_phase2_store:
        missing.append("runtime_incident_bridge_enablement_no_phase2_store_import")
    if forbidden_fragments:
        missing.append(
            "runtime_incident_bridge_enablement_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": "dry_run_ready",
        "blocked_status": blocked_record.status.value,
        "blocked_reasons": blocked_record.blocker_reasons,
        "dry_run_status": ready_record.status.value,
        "guard_status": ready_record.guard_status,
        "missing_recipient_reasons": missing_recipient_record.blocker_reasons,
        "mock_outbound_message_count": ready_record.counts.mock_outbound_message_count,
        "mock_message_states": [message.state for message in messages],
        "mock_message_categories": [message.category for message in messages],
        "debug_event_kinds": [event.kind for event in log.list_events()],
        "remote_notifications_enabled": ready_record.remote_notifications_enabled,
        "enable_performed": ready_record.enable_performed,
        "incident_bridge_enable_count": ready_record.counts.incident_bridge_enable_count,
        "remote_notification_send_count": (
            ready_record.counts.remote_notification_send_count
        ),
        "phase2_writeback_count": ready_record.counts.phase2_writeback_count,
        "dry_run_only": ready_record.boundary.dry_run_only,
        "uses_mock_outbound_transport": (
            ready_record.boundary.uses_mock_outbound_transport
        ),
        "sends_real_remote_notification": (
            ready_record.boundary.sends_real_remote_notification
        ),
        "enables_phase1_incident_bridge": (
            ready_record.boundary.enables_phase1_incident_bridge
        ),
        "writes_phase2_brain": ready_record.boundary.writes_phase2_brain,
        "raw_payloads_embedded": ready_record.boundary.raw_payloads_embedded,
        "real_sos_sent_count": sum(1 for message in messages if message.boundary.real_sos_sent),
        "real_sms_sent_count": sum(1 for message in messages if message.boundary.real_sms_sent),
        "real_satellite_sent_count": sum(
            1 for message in messages if message.boundary.real_satellite_sent
        ),
        "source_has_network": source_has_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_incident_bridge_delivery_ack(root: Path) -> dict[str, Any]:
    try:
        from mock_outbound_transport import MockOutboundTransport
        from runtime_debug_log import MemoryRuntimeDebugEventLog
        from runtime_incident_bridge_delivery_ack import (
            RuntimeIncidentBridgeDeliveryAction,
            RuntimeIncidentBridgeDeliveryAckStatus,
            build_runtime_incident_bridge_delivery_ack,
        )
        from runtime_incident_bridge_enablement import (
            build_runtime_incident_bridge_enablement_dry_run,
        )
        from runtime_incident_bridge_opt_in import (
            build_runtime_incident_bridge_opt_in_decision,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_incident_bridge_delivery_ack_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "runtime_incident_bridge_delivery_ack.py").exists() else REPO_ROOT
    source = (source_root / "runtime_incident_bridge_delivery_ack.py").read_text(
        encoding="utf-8"
    )

    def transport() -> tuple[MemoryRuntimeDebugEventLog, MockOutboundTransport]:
        log = MemoryRuntimeDebugEventLog()
        counter = {"value": 0}

        def timestamp() -> str:
            counter["value"] += 1
            return f"2026-05-19T23:20:{counter['value']:02d}Z"

        return log, MockOutboundTransport(
            session_id="runtime_session.release_check",
            mission_id="mission.release_check",
            debug_log=log,
            timestamp_factory=timestamp,
        )

    def ready_enablement(outbound: MockOutboundTransport):
        decision = build_runtime_incident_bridge_opt_in_decision(
            operator_id="admin.release_check",
            runtime_status="observing",
            operator_opt_in=True,
            remote_contact_policy_ref="remote_contact_policy.family.v0",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )
        return build_runtime_incident_bridge_enablement_dry_run(
            opt_in_decision=decision,
            operator_id="admin.release_check",
            recipient_refs=["remote_contact.primary", "remote_contact.backup"],
            reason="release check delivery ack",
            outbound_transport=outbound,
            timestamp_factory=lambda: "2026-05-19T23:20:00Z",
        )

    ack_log, ack_transport = transport()
    ack_enablement = ready_enablement(ack_transport)
    ack_record = build_runtime_incident_bridge_delivery_ack(
        enablement_record=ack_enablement,
        action=RuntimeIncidentBridgeDeliveryAction.CONFIRM_MOCK_DELIVERED,
        operator_id="admin.release_check",
        reason="release check confirm mock delivered",
        outbound_transport=ack_transport,
        timestamp_factory=lambda: "2026-05-19T23:21:00Z",
    )

    cancel_log, cancel_transport = transport()
    cancel_enablement = ready_enablement(cancel_transport)
    cancel_record = build_runtime_incident_bridge_delivery_ack(
        enablement_record=cancel_enablement,
        action=RuntimeIncidentBridgeDeliveryAction.CANCEL_MOCK_DELIVERY,
        operator_id="admin.release_check",
        reason="release check cancel mock delivery",
        outbound_transport=cancel_transport,
        timestamp_factory=lambda: "2026-05-19T23:22:00Z",
    )

    rerun_log, rerun_transport = transport()
    rerun_enablement = ready_enablement(rerun_transport)
    rerun_record = build_runtime_incident_bridge_delivery_ack(
        enablement_record=rerun_enablement,
        action=RuntimeIncidentBridgeDeliveryAction.RERUN_DRY_RUN,
        operator_id="admin.release_check",
        reason="release check rerun dry run refs",
        outbound_transport=rerun_transport,
        rerun_message_refs=[
            "mock_message.remote_status.rerun.000001",
            "mock_message.remote_status.rerun.000002",
        ],
        timestamp_factory=lambda: "2026-05-19T23:23:00Z",
    )

    blocked_decision = build_runtime_incident_bridge_opt_in_decision(
        operator_id="admin.release_check",
        runtime_status="observing",
        operator_opt_in=False,
    )
    blocked_enablement = build_runtime_incident_bridge_enablement_dry_run(
        opt_in_decision=blocked_decision,
        operator_id="admin.release_check",
        recipient_refs=["remote_contact.primary"],
        reason="release check blocked enablement",
        outbound_transport=rerun_transport,
        timestamp_factory=lambda: "2026-05-19T23:24:00Z",
    )
    blocked_record = build_runtime_incident_bridge_delivery_ack(
        enablement_record=blocked_enablement,
        action=RuntimeIncidentBridgeDeliveryAction.CONFIRM_MOCK_DELIVERED,
        operator_id="admin.release_check",
        reason="release check blocked ack",
        outbound_transport=rerun_transport,
        timestamp_factory=lambda: "2026-05-19T23:25:00Z",
    )

    delivered_cancel_record = build_runtime_incident_bridge_delivery_ack(
        enablement_record=ack_enablement,
        action=RuntimeIncidentBridgeDeliveryAction.CANCEL_MOCK_DELIVERY,
        operator_id="admin.release_check",
        reason="release check cannot cancel delivered",
        outbound_transport=ack_transport,
        timestamp_factory=lambda: "2026-05-19T23:26:00Z",
    )

    serialized = json.dumps(
        [
            ack_record.model_dump(mode="json"),
            cancel_record.model_dump(mode="json"),
            rerun_record.model_dump(mode="json"),
            blocked_record.model_dump(mode="json"),
            delivered_cancel_record.model_dump(mode="json"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"payload":',
        )
        if fragment in serialized
    ]
    source_has_network = any(
        token in source for token in ("requests", "httpx", "urllib", "twilio")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source

    if ack_record.status != RuntimeIncidentBridgeDeliveryAckStatus.ACK_RECORDED:
        missing.append("runtime_incident_bridge_delivery_ack_confirm_recorded")
    if ack_record.counts.mock_delivered_count != 2:
        missing.append("runtime_incident_bridge_delivery_ack_confirm_count")
    if [message.state for message in ack_transport.list_messages()] != [
        "mock-delivered",
        "mock-delivered",
    ]:
        missing.append("runtime_incident_bridge_delivery_ack_confirm_states")
    if cancel_record.status != RuntimeIncidentBridgeDeliveryAckStatus.CANCEL_RECORDED:
        missing.append("runtime_incident_bridge_delivery_ack_cancel_recorded")
    if cancel_record.counts.cancelled_count != 2:
        missing.append("runtime_incident_bridge_delivery_ack_cancel_count")
    if [message.state for message in cancel_transport.list_messages()] != [
        "cancelled",
        "cancelled",
    ]:
        missing.append("runtime_incident_bridge_delivery_ack_cancel_states")
    if rerun_record.status != RuntimeIncidentBridgeDeliveryAckStatus.RERUN_RECORDED:
        missing.append("runtime_incident_bridge_delivery_ack_rerun_recorded")
    if rerun_record.counts.rerun_message_count != 2:
        missing.append("runtime_incident_bridge_delivery_ack_rerun_count")
    if [message.state for message in rerun_transport.list_messages()] != [
        "queued",
        "queued",
    ]:
        missing.append("runtime_incident_bridge_delivery_ack_rerun_no_queue_mutation")
    if blocked_record.status != RuntimeIncidentBridgeDeliveryAckStatus.BLOCKED:
        missing.append("runtime_incident_bridge_delivery_ack_blocked")
    if blocked_record.blocker_reasons != ["enablement_record_not_dry_run"]:
        missing.append("runtime_incident_bridge_delivery_ack_block_reason")
    if delivered_cancel_record.status != RuntimeIncidentBridgeDeliveryAckStatus.BLOCKED:
        missing.append("runtime_incident_bridge_delivery_ack_blocks_delivered_cancel")
    if not all(
        reason.startswith("cannot_cancel_mock_delivered_message:")
        for reason in delivered_cancel_record.blocker_reasons
    ):
        missing.append("runtime_incident_bridge_delivery_ack_delivered_cancel_reason")
    for name, record in (
        ("ack", ack_record),
        ("cancel", cancel_record),
        ("rerun", rerun_record),
    ):
        if record.remote_notifications_enabled:
            missing.append(f"runtime_incident_bridge_delivery_ack_notification:{name}")
        if record.enable_performed:
            missing.append(f"runtime_incident_bridge_delivery_ack_enable:{name}")
        if record.counts.remote_notification_send_count != 0:
            missing.append(f"runtime_incident_bridge_delivery_ack_send_count:{name}")
        if record.counts.incident_bridge_enable_count != 0:
            missing.append(f"runtime_incident_bridge_delivery_ack_bridge_count:{name}")
        if record.counts.phase2_writeback_count != 0:
            missing.append(f"runtime_incident_bridge_delivery_ack_phase2:{name}")
        if not record.boundary.mock_ack_only:
            missing.append(f"runtime_incident_bridge_delivery_ack_boundary:{name}")
        if record.boundary.sends_real_remote_notification:
            missing.append(f"runtime_incident_bridge_delivery_ack_real_send:{name}")
        if record.boundary.enables_phase1_incident_bridge:
            missing.append(f"runtime_incident_bridge_delivery_ack_phase1:{name}")
        if record.boundary.writes_phase2_brain:
            missing.append(f"runtime_incident_bridge_delivery_ack_phase2_boundary:{name}")
        if record.boundary.raw_payloads_embedded:
            missing.append(f"runtime_incident_bridge_delivery_ack_raw:{name}")
    if source_has_network:
        missing.append("runtime_incident_bridge_delivery_ack_no_network_imports")
    if source_has_phase1_bridge:
        missing.append("runtime_incident_bridge_delivery_ack_no_phase1_bridge_import")
    if source_has_phase2_store:
        missing.append("runtime_incident_bridge_delivery_ack_no_phase2_store_import")
    if forbidden_fragments:
        missing.append(
            "runtime_incident_bridge_delivery_ack_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": "mock_delivery_ack_ready",
        "ack_status": ack_record.status.value,
        "cancel_status": cancel_record.status.value,
        "rerun_status": rerun_record.status.value,
        "blocked_status": blocked_record.status.value,
        "blocked_reasons": blocked_record.blocker_reasons,
        "delivered_cancel_status": delivered_cancel_record.status.value,
        "delivered_cancel_reasons": delivered_cancel_record.blocker_reasons,
        "mock_delivered_count": ack_record.counts.mock_delivered_count,
        "cancelled_count": cancel_record.counts.cancelled_count,
        "rerun_message_count": rerun_record.counts.rerun_message_count,
        "ack_message_states": [message.state for message in ack_transport.list_messages()],
        "cancel_message_states": [
            message.state for message in cancel_transport.list_messages()
        ],
        "rerun_message_states": [
            message.state for message in rerun_transport.list_messages()
        ],
        "ack_debug_event_states": [
            event.payload["state"]
            for event in ack_log.list_events(kind="outbound_message_state_changed")
        ],
        "cancel_debug_event_states": [
            event.payload["state"]
            for event in cancel_log.list_events(kind="outbound_message_state_changed")
        ],
        "remote_notification_send_count": (
            ack_record.counts.remote_notification_send_count
            + cancel_record.counts.remote_notification_send_count
            + rerun_record.counts.remote_notification_send_count
        ),
        "incident_bridge_enable_count": (
            ack_record.counts.incident_bridge_enable_count
            + cancel_record.counts.incident_bridge_enable_count
            + rerun_record.counts.incident_bridge_enable_count
        ),
        "phase2_writeback_count": (
            ack_record.counts.phase2_writeback_count
            + cancel_record.counts.phase2_writeback_count
            + rerun_record.counts.phase2_writeback_count
        ),
        "remote_notifications_enabled": any(
            record.remote_notifications_enabled
            for record in (ack_record, cancel_record, rerun_record)
        ),
        "enable_performed": any(
            record.enable_performed for record in (ack_record, cancel_record, rerun_record)
        ),
        "mock_ack_only": all(
            record.boundary.mock_ack_only
            for record in (ack_record, cancel_record, rerun_record)
        ),
        "sends_real_remote_notification": any(
            record.boundary.sends_real_remote_notification
            for record in (ack_record, cancel_record, rerun_record)
        ),
        "enables_phase1_incident_bridge": any(
            record.boundary.enables_phase1_incident_bridge
            for record in (ack_record, cancel_record, rerun_record)
        ),
        "writes_phase2_brain": any(
            record.boundary.writes_phase2_brain
            for record in (ack_record, cancel_record, rerun_record)
        ),
        "raw_payloads_embedded": any(
            record.boundary.raw_payloads_embedded
            for record in (ack_record, cancel_record, rerun_record)
        ),
        "source_has_network": source_has_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_remote_provider_policy(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_policy import (
            RuntimeRemoteMessageClass,
            RuntimeRemoteProviderDecisionStatus,
            build_webhook_remote_provider_policy_contract,
            evaluate_runtime_remote_message_request,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_policy_import:{exc}"],
        }

    missing: list[str] = []
    source_root = root if (root / "runtime_remote_provider_policy.py").exists() else REPO_ROOT
    source = (source_root / "runtime_remote_provider_policy.py").read_text(
        encoding="utf-8"
    )
    policy = build_webhook_remote_provider_policy_contract()
    remote_status = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="remote_contact.primary",
    )
    checkin = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.CHECKIN,
        recipient_ref="remote_contact.backup",
    )
    l2_alert = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
        recipient_ref="remote_contact.primary",
        incident_level="L2_CONCERN",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    l3_alert = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
        recipient_ref="remote_contact.backup",
        incident_level="L3_EMERGENCY",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    sos = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.SOS,
        recipient_ref="remote_contact.primary",
        incident_level="L3_EMERGENCY",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
    )
    arbitrary_recipient = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="https://example.invalid/webhook",
    )
    missing_noise = evaluate_runtime_remote_message_request(
        policy,
        message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
        recipient_ref="remote_contact.primary",
        incident_level="L2_CONCERN",
    )
    serialized = json.dumps(
        [
            policy.model_dump(mode="json"),
            remote_status.model_dump(mode="json"),
            checkin.model_dump(mode="json"),
            l2_alert.model_dump(mode="json"),
            l3_alert.model_dump(mode="json"),
            sos.model_dump(mode="json"),
            arbitrary_recipient.model_dump(mode="json"),
            missing_noise.model_dump(mode="json"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"payload":',
        )
        if fragment in serialized
    ]
    source_has_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.", "urllib", "twilio")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source

    if policy.status != "policy_ready_not_connected":
        missing.append("runtime_remote_provider_policy_status")
    if policy.provider_kind != "webhook_telegram_like":
        missing.append("runtime_remote_provider_policy_kind")
    if policy.provider_id != "remote_provider.webhook_telegram_like.v0":
        missing.append("runtime_remote_provider_policy_provider_id")
    if not policy.auth.secret_ref_required:
        missing.append("runtime_remote_provider_policy_secret_ref_required")
    if policy.auth.token_value_embedded:
        missing.append("runtime_remote_provider_policy_no_token_value")
    if policy.endpoint.raw_url_embedded:
        missing.append("runtime_remote_provider_policy_no_raw_url")
    if policy.recipients.arbitrary_recipient_input_allowed:
        missing.append("runtime_remote_provider_policy_no_arbitrary_recipient")
    if policy.recipients.allowed_recipient_refs != [
        "remote_contact.primary",
        "remote_contact.backup",
    ]:
        missing.append("runtime_remote_provider_policy_reviewed_recipient_refs")
    for name, decision in (
        ("remote_status", remote_status),
        ("checkin", checkin),
        ("l2_alert", l2_alert),
        ("l3_alert", l3_alert),
    ):
        if decision.status != RuntimeRemoteProviderDecisionStatus.ALLOWED:
            missing.append(f"runtime_remote_provider_policy_allowed:{name}")
        if decision.send_performed:
            missing.append(f"runtime_remote_provider_policy_send_performed:{name}")
        if decision.remote_notification_send_count != 0:
            missing.append(f"runtime_remote_provider_policy_send_count:{name}")
        if decision.incident_bridge_enable_count != 0:
            missing.append(f"runtime_remote_provider_policy_bridge_count:{name}")
        if decision.phase2_writeback_count != 0:
            missing.append(f"runtime_remote_provider_policy_phase2:{name}")
    if sos.status != RuntimeRemoteProviderDecisionStatus.BLOCKED:
        missing.append("runtime_remote_provider_policy_sos_blocked")
    if "sos_provider_not_implemented" not in sos.blocker_reasons:
        missing.append("runtime_remote_provider_policy_sos_reason")
    if arbitrary_recipient.blocker_reasons != ["recipient_ref_not_allowed"]:
        missing.append("runtime_remote_provider_policy_arbitrary_recipient_blocked")
    if "missing_noise_reduction_policy_ref" not in missing_noise.blocker_reasons:
        missing.append("runtime_remote_provider_policy_noise_required")
    if policy.cancellation.provider_cancellation_supported:
        missing.append("runtime_remote_provider_policy_no_provider_cancel")
    if not policy.cancellation.followup_correction_allowed:
        missing.append("runtime_remote_provider_policy_followup_correction")
    if policy.failure.auto_escalate_provider:
        missing.append("runtime_remote_provider_policy_no_auto_escalation")
    if policy.failure.auto_sos_escalation:
        missing.append("runtime_remote_provider_policy_no_auto_sos")
    if not policy.failure.manual_retry_required:
        missing.append("runtime_remote_provider_policy_manual_retry")
    if policy.rate_limits.incident_alert_window_seconds != 600:
        missing.append("runtime_remote_provider_policy_incident_alert_rate_limit")
    if policy.rate_limits.remote_status_window_seconds != 300:
        missing.append("runtime_remote_provider_policy_remote_status_rate_limit")
    if not policy.boundary.policy_only:
        missing.append("runtime_remote_provider_policy_boundary")
    if policy.boundary.creates_provider_adapter:
        missing.append("runtime_remote_provider_policy_no_adapter")
    if policy.boundary.sends_network_request:
        missing.append("runtime_remote_provider_policy_no_network_send")
    if policy.boundary.sends_real_remote_notification:
        missing.append("runtime_remote_provider_policy_no_real_send")
    if policy.boundary.enables_phase1_incident_bridge:
        missing.append("runtime_remote_provider_policy_no_phase1_bridge")
    if policy.boundary.writes_phase2_brain:
        missing.append("runtime_remote_provider_policy_no_phase2")
    if source_has_network:
        missing.append("runtime_remote_provider_policy_no_network_imports")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_policy_no_phase1_bridge_import")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_policy_no_phase2_store_import")
    if forbidden_fragments:
        missing.append(
            "runtime_remote_provider_policy_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": policy.status,
        "provider_id": policy.provider_id,
        "provider_kind": policy.provider_kind.value,
        "auth_method": policy.auth.auth_method,
        "secret_ref_required": policy.auth.secret_ref_required,
        "token_value_embedded": policy.auth.token_value_embedded,
        "raw_url_embedded": policy.endpoint.raw_url_embedded,
        "allowed_recipient_refs": policy.recipients.allowed_recipient_refs,
        "arbitrary_recipient_input_allowed": (
            policy.recipients.arbitrary_recipient_input_allowed
        ),
        "allowed_message_classes": [
            message_class.value
            for message_class in policy.message_classes.allowed_message_classes
        ],
        "blocked_message_classes": [
            message_class.value
            for message_class in policy.message_classes.blocked_message_classes
        ],
        "remote_status_decision": remote_status.status.value,
        "checkin_decision": checkin.status.value,
        "l2_incident_alert_decision": l2_alert.status.value,
        "l3_incident_alert_decision": l3_alert.status.value,
        "sos_decision": sos.status.value,
        "sos_blocker_reasons": sos.blocker_reasons,
        "arbitrary_recipient_decision": arbitrary_recipient.status.value,
        "arbitrary_recipient_blocker_reasons": arbitrary_recipient.blocker_reasons,
        "missing_noise_decision": missing_noise.status.value,
        "missing_noise_blocker_reasons": missing_noise.blocker_reasons,
        "provider_cancellation_supported": (
            policy.cancellation.provider_cancellation_supported
        ),
        "followup_correction_allowed": policy.cancellation.followup_correction_allowed,
        "cancellation_semantics": policy.cancellation.cancellation_semantics,
        "manual_retry_required": policy.failure.manual_retry_required,
        "auto_escalate_provider": policy.failure.auto_escalate_provider,
        "auto_sos_escalation": policy.failure.auto_sos_escalation,
        "incident_alert_window_seconds": (
            policy.rate_limits.incident_alert_window_seconds
        ),
        "remote_status_window_seconds": policy.rate_limits.remote_status_window_seconds,
        "audit_required_fields": policy.audit.required_fields,
        "policy_only": policy.boundary.policy_only,
        "creates_provider_adapter": policy.boundary.creates_provider_adapter,
        "sends_network_request": policy.boundary.sends_network_request,
        "sends_real_remote_notification": (
            policy.boundary.sends_real_remote_notification
        ),
        "enables_phase1_incident_bridge": policy.boundary.enables_phase1_incident_bridge,
        "writes_phase2_brain": policy.boundary.writes_phase2_brain,
        "raw_payloads_embedded": policy.boundary.raw_payloads_embedded,
        "source_has_network": source_has_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_remote_provider_config_preflight(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_config_preflight import (
            RuntimeRemoteProviderConfigPreflightStatus,
            build_webhook_remote_provider_config_template,
            run_runtime_remote_provider_config_preflight,
        )
        from runtime_remote_provider_policy import (
            RuntimeRemoteMessageClass,
            build_webhook_remote_provider_policy_contract,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_config_preflight_import:{exc}"],
        }

    missing: list[str] = []
    source_root = (
        root
        if (root / "runtime_remote_provider_config_preflight.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_config_preflight.py").read_text(
        encoding="utf-8"
    )
    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    required_secret_refs = config.required_secret_refs()
    ready_report = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs=set(required_secret_refs),
    )
    missing_secrets_report = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs={
            "env:SCOUT_REMOTE_WEBHOOK_URL",
            "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
        },
    )
    mismatch_config = build_webhook_remote_provider_config_template(policy)
    mismatch_config.provider_id = "remote_provider.other.v0"
    mismatch_config.enabled_message_classes.append(RuntimeRemoteMessageClass.SOS)
    mismatch_config.recipients[0].recipient_ref = "https://example.invalid/webhook"
    mismatch_report = run_runtime_remote_provider_config_preflight(
        policy,
        mismatch_config,
        available_secret_refs=set(mismatch_config.required_secret_refs()),
    )
    serialized = json.dumps(
        [
            config.model_dump(mode="json"),
            ready_report.model_dump(mode="json"),
            missing_secrets_report.model_dump(mode="json"),
            mismatch_report.model_dump(mode="json"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"payload":',
            '"secret_value"',
            "chat_id",
        )
        if fragment in serialized
    ]
    source_has_network = any(
        token in source
        for token in (
            "import requests",
            "requests.",
            "import httpx",
            "httpx.",
            "urllib",
            "twilio",
        )
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source

    if config.status != "config_template_not_connected":
        missing.append("runtime_remote_provider_config_status")
    if config.provider_id != policy.provider_id:
        missing.append("runtime_remote_provider_config_provider_id")
    if config.provider_kind != policy.provider_kind:
        missing.append("runtime_remote_provider_config_provider_kind")
    if config.endpoint.endpoint_ref != policy.endpoint.endpoint_ref:
        missing.append("runtime_remote_provider_config_endpoint_ref")
    if config.endpoint.endpoint_url_secret_ref != "env:SCOUT_REMOTE_WEBHOOK_URL":
        missing.append("runtime_remote_provider_config_endpoint_secret_ref")
    if config.auth.auth_secret_ref != "env:SCOUT_REMOTE_WEBHOOK_TOKEN":
        missing.append("runtime_remote_provider_config_auth_secret_ref")
    if config.auth.signature_secret_ref != "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET":
        missing.append("runtime_remote_provider_config_signature_secret_ref")
    if required_secret_refs != [
        "env:SCOUT_REMOTE_WEBHOOK_URL",
        "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
        "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
        "env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
        "env:SCOUT_REMOTE_BACKUP_TARGET_REF",
    ]:
        missing.append("runtime_remote_provider_config_required_secret_refs")
    if config.endpoint.raw_url_embedded:
        missing.append("runtime_remote_provider_config_no_raw_url")
    if config.auth.token_value_embedded:
        missing.append("runtime_remote_provider_config_no_token_value")
    if config.auth.secret_values_loaded:
        missing.append("runtime_remote_provider_config_no_secret_values_loaded")
    if not config.boundary.config_only:
        missing.append("runtime_remote_provider_config_boundary")
    if config.boundary.creates_provider_adapter:
        missing.append("runtime_remote_provider_config_no_adapter")
    if config.boundary.sends_network_request:
        missing.append("runtime_remote_provider_config_no_network")
    if config.boundary.sends_real_remote_notification:
        missing.append("runtime_remote_provider_config_no_real_send")
    if config.boundary.enables_phase1_incident_bridge:
        missing.append("runtime_remote_provider_config_no_phase1_bridge")
    if config.boundary.writes_phase2_brain:
        missing.append("runtime_remote_provider_config_no_phase2")
    if ready_report.status != RuntimeRemoteProviderConfigPreflightStatus.READY:
        missing.append("runtime_remote_provider_config_preflight_ready")
    if not ready_report.provider_config_ready:
        missing.append("runtime_remote_provider_config_preflight_ready_flag")
    if ready_report.blocker_count != 0:
        missing.append("runtime_remote_provider_config_preflight_ready_blockers")
    if ready_report.secret_values_loaded:
        missing.append("runtime_remote_provider_config_preflight_no_secret_load")
    if ready_report.send_performed:
        missing.append("runtime_remote_provider_config_preflight_no_send")
    if ready_report.remote_notification_send_count != 0:
        missing.append("runtime_remote_provider_config_preflight_no_remote_send")
    if ready_report.incident_bridge_enable_count != 0:
        missing.append("runtime_remote_provider_config_preflight_no_bridge")
    if ready_report.phase2_writeback_count != 0:
        missing.append("runtime_remote_provider_config_preflight_no_phase2")
    if missing_secrets_report.status != RuntimeRemoteProviderConfigPreflightStatus.BLOCKED:
        missing.append("runtime_remote_provider_config_preflight_missing_secret_blocked")
    if "missing_secret_refs" not in missing_secrets_report.blocker_reasons:
        missing.append("runtime_remote_provider_config_preflight_missing_secret_reason")
    if "env:SCOUT_REMOTE_PRIMARY_TARGET_REF" not in missing_secrets_report.missing_secret_refs:
        missing.append("runtime_remote_provider_config_preflight_missing_primary_ref")
    if mismatch_report.status != RuntimeRemoteProviderConfigPreflightStatus.BLOCKED:
        missing.append("runtime_remote_provider_config_preflight_mismatch_blocked")
    for reason in (
        "provider_id_mismatch",
        "message_class_not_allowed:sos",
        "recipient_ref_not_allowed:https://example.invalid/webhook",
    ):
        if reason not in mismatch_report.blocker_reasons:
            missing.append(f"runtime_remote_provider_config_preflight_reason:{reason}")
    if source_has_network:
        missing.append("runtime_remote_provider_config_preflight_no_network_imports")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_config_preflight_no_phase1_import")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_config_preflight_no_phase2_import")
    if forbidden_fragments:
        missing.append(
            "runtime_remote_provider_config_preflight_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": ready_report.status.value,
        "provider_config_ready": ready_report.provider_config_ready,
        "provider_id": config.provider_id,
        "provider_kind": config.provider_kind.value,
        "endpoint_ref": config.endpoint.endpoint_ref,
        "endpoint_url_secret_ref": config.endpoint.endpoint_url_secret_ref,
        "auth_secret_ref": config.auth.auth_secret_ref,
        "signature_secret_ref": config.auth.signature_secret_ref,
        "required_secret_refs": required_secret_refs,
        "missing_secrets_status": missing_secrets_report.status.value,
        "missing_secret_refs": missing_secrets_report.missing_secret_refs,
        "mismatch_status": mismatch_report.status.value,
        "mismatch_blocker_reasons": mismatch_report.blocker_reasons,
        "secret_values_loaded": ready_report.secret_values_loaded,
        "endpoint_url_embedded": ready_report.endpoint_url_embedded,
        "token_value_embedded": ready_report.token_value_embedded,
        "config_only": config.boundary.config_only,
        "creates_provider_adapter": config.boundary.creates_provider_adapter,
        "sends_network_request": config.boundary.sends_network_request,
        "sends_real_remote_notification": (
            config.boundary.sends_real_remote_notification
        ),
        "enables_phase1_incident_bridge": (
            config.boundary.enables_phase1_incident_bridge
        ),
        "writes_phase2_brain": config.boundary.writes_phase2_brain,
        "send_performed": ready_report.send_performed,
        "remote_notification_send_count": ready_report.remote_notification_send_count,
        "incident_bridge_enable_count": ready_report.incident_bridge_enable_count,
        "phase2_writeback_count": ready_report.phase2_writeback_count,
        "source_has_network": source_has_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_remote_provider_payload_composer(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_config_preflight import (
            build_webhook_remote_provider_config_template,
            run_runtime_remote_provider_config_preflight,
        )
        from runtime_remote_provider_payload_composer import (
            RuntimeRemoteProviderPayloadCompositionStatus,
            RuntimeRemoteProviderPayloadRequest,
            compose_runtime_remote_provider_payload,
        )
        from runtime_remote_provider_policy import (
            RuntimeRemoteMessageClass,
            build_webhook_remote_provider_policy_contract,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_payload_composer_import:{exc}"],
        }

    missing: list[str] = []
    source_root = (
        root
        if (root / "runtime_remote_provider_payload_composer.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_payload_composer.py").read_text(
        encoding="utf-8"
    )
    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    ready_preflight = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs=set(config.required_secret_refs()),
    )
    blocked_preflight = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs={"env:SCOUT_REMOTE_WEBHOOK_URL"},
    )
    remote_status_request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="remote_contact.primary",
        body_summary="Scout observing started. Group is moving as planned.",
        operator_id="operator.admin.local",
        correlation_refs=[
            "runtime_session.chilai_nanhua_day1.v0",
            "runtime_incident_bridge.guard.remote_status.v0",
        ],
    )
    incident_alert_request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
        recipient_ref="remote_contact.backup",
        body_summary="Scout detected L2 concern. Admin reviewed low-noise alert.",
        operator_id="operator.admin.local",
        incident_level="L2_CONCERN",
        noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        correlation_refs=["runtime_alert.l2.concern.v0"],
    )
    missing_noise_request = incident_alert_request.model_copy(
        update={"noise_reduction_policy_ref": None}
    )
    sos_request = remote_status_request.model_copy(
        update={"message_class": RuntimeRemoteMessageClass.SOS}
    )
    arbitrary_recipient_request = remote_status_request.model_copy(
        update={"recipient_ref": "https://example.invalid/webhook"}
    )
    long_body_request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.CHECKIN,
        recipient_ref="remote_contact.primary",
        body_summary="Line one\n" + ("safe summary " * 40),
        operator_id="operator.admin.local",
        correlation_refs=["runtime_checkin.v0"],
    )

    remote_status = compose_runtime_remote_provider_payload(
        policy,
        config,
        ready_preflight,
        remote_status_request,
    )
    incident_alert = compose_runtime_remote_provider_payload(
        policy,
        config,
        ready_preflight,
        incident_alert_request,
    )
    missing_noise = compose_runtime_remote_provider_payload(
        policy,
        config,
        ready_preflight,
        missing_noise_request,
    )
    preflight_blocked = compose_runtime_remote_provider_payload(
        policy,
        config,
        blocked_preflight,
        remote_status_request,
    )
    sos_blocked = compose_runtime_remote_provider_payload(
        policy,
        config,
        ready_preflight,
        sos_request,
    )
    arbitrary_recipient_blocked = compose_runtime_remote_provider_payload(
        policy,
        config,
        ready_preflight,
        arbitrary_recipient_request,
    )
    long_body = compose_runtime_remote_provider_payload(
        policy,
        config,
        ready_preflight,
        long_body_request,
    )
    serialized = json.dumps(
        [
            remote_status.model_dump(mode="json"),
            incident_alert.model_dump(mode="json"),
            missing_noise.model_dump(mode="json"),
            preflight_blocked.model_dump(mode="json"),
            sos_blocked.model_dump(mode="json"),
            arbitrary_recipient_blocked.model_dump(mode="json"),
            long_body.model_dump(mode="json"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"payload":',
            '"secret_value"',
            "chat_id",
        )
        if fragment in serialized
    ]
    source_has_network = any(
        token in source
        for token in (
            "import requests",
            "requests.",
            "import httpx",
            "httpx.",
            "urllib",
            "twilio",
        )
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source

    for name, composition in (
        ("remote_status", remote_status),
        ("incident_alert", incident_alert),
        ("long_body", long_body),
    ):
        if composition.status != RuntimeRemoteProviderPayloadCompositionStatus.READY_NOT_SENT:
            missing.append(f"runtime_remote_provider_payload_ready:{name}")
        if not composition.payload_ready:
            missing.append(f"runtime_remote_provider_payload_ready_flag:{name}")
        if composition.send_performed:
            missing.append(f"runtime_remote_provider_payload_send:{name}")
        if composition.remote_notification_send_count != 0:
            missing.append(f"runtime_remote_provider_payload_remote_send:{name}")
        if composition.incident_bridge_enable_count != 0:
            missing.append(f"runtime_remote_provider_payload_bridge:{name}")
        if composition.phase2_writeback_count != 0:
            missing.append(f"runtime_remote_provider_payload_phase2:{name}")
        if composition.raw_payloads_embedded:
            missing.append(f"runtime_remote_provider_payload_raw:{name}")
        if composition.secret_values_loaded:
            missing.append(f"runtime_remote_provider_payload_secret_loaded:{name}")
    if remote_status.delivery_target_secret_ref != "env:SCOUT_REMOTE_PRIMARY_TARGET_REF":
        missing.append("runtime_remote_provider_payload_primary_target_ref")
    if incident_alert.delivery_target_secret_ref != "env:SCOUT_REMOTE_BACKUP_TARGET_REF":
        missing.append("runtime_remote_provider_payload_backup_target_ref")
    if len(remote_status.payload_hash) != 64:
        missing.append("runtime_remote_provider_payload_hash")
    if incident_alert.incident_level != "L2_CONCERN":
        missing.append("runtime_remote_provider_payload_incident_level")
    if (
        incident_alert.noise_reduction_policy_ref
        != "noise_reduction_policy.family_low_noise.v0"
    ):
        missing.append("runtime_remote_provider_payload_noise_ref")
    if "\n" in long_body.body_preview or len(long_body.body_preview) > 240:
        missing.append("runtime_remote_provider_payload_body_preview_normalized")
    for name, composition, reason in (
        ("missing_noise", missing_noise, "missing_noise_reduction_policy_ref"),
        ("preflight_blocked", preflight_blocked, "provider_config_preflight_not_ready"),
        ("sos_blocked", sos_blocked, "sos_provider_not_implemented"),
        ("arbitrary_recipient", arbitrary_recipient_blocked, "recipient_ref_not_allowed"),
    ):
        if composition.status != RuntimeRemoteProviderPayloadCompositionStatus.BLOCKED:
            missing.append(f"runtime_remote_provider_payload_blocked:{name}")
        if composition.payload_ready:
            missing.append(f"runtime_remote_provider_payload_blocked_ready:{name}")
        if reason not in composition.blocker_reasons:
            missing.append(f"runtime_remote_provider_payload_reason:{name}")
        if composition.send_performed:
            missing.append(f"runtime_remote_provider_payload_blocked_send:{name}")
    if source_has_network:
        missing.append("runtime_remote_provider_payload_no_network_imports")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_payload_no_phase1_import")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_payload_no_phase2_import")
    if forbidden_fragments:
        missing.append(
            "runtime_remote_provider_payload_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": remote_status.status.value,
        "provider_id": remote_status.provider_id,
        "provider_kind": remote_status.provider_kind.value,
        "endpoint_ref": remote_status.endpoint_ref,
        "recipient_ref": remote_status.recipient_ref,
        "delivery_target_secret_ref": remote_status.delivery_target_secret_ref,
        "message_class": remote_status.message_class.value,
        "body_preview": remote_status.body_preview,
        "payload_hash": remote_status.payload_hash,
        "payload_ready": remote_status.payload_ready,
        "incident_alert_status": incident_alert.status.value,
        "incident_alert_delivery_target_secret_ref": (
            incident_alert.delivery_target_secret_ref
        ),
        "incident_alert_level": incident_alert.incident_level,
        "incident_alert_noise_reduction_policy_ref": (
            incident_alert.noise_reduction_policy_ref
        ),
        "missing_noise_status": missing_noise.status.value,
        "missing_noise_blocker_reasons": missing_noise.blocker_reasons,
        "preflight_blocked_status": preflight_blocked.status.value,
        "preflight_blocker_reasons": preflight_blocked.blocker_reasons,
        "sos_status": sos_blocked.status.value,
        "sos_blocker_reasons": sos_blocked.blocker_reasons,
        "arbitrary_recipient_status": arbitrary_recipient_blocked.status.value,
        "arbitrary_recipient_blocker_reasons": (
            arbitrary_recipient_blocked.blocker_reasons
        ),
        "long_body_preview_length": len(long_body.body_preview),
        "long_body_preview_has_newline": "\n" in long_body.body_preview,
        "summary_only": remote_status.summary_only,
        "raw_payloads_embedded": remote_status.raw_payloads_embedded,
        "secret_values_loaded": remote_status.secret_values_loaded,
        "endpoint_url_embedded": remote_status.endpoint_url_embedded,
        "token_value_embedded": remote_status.token_value_embedded,
        "send_performed": remote_status.send_performed,
        "remote_notification_send_count": remote_status.remote_notification_send_count,
        "incident_bridge_enable_count": remote_status.incident_bridge_enable_count,
        "phase2_writeback_count": remote_status.phase2_writeback_count,
        "source_has_network": source_has_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_remote_provider_send_queue(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_config_preflight import (
            build_webhook_remote_provider_config_template,
            run_runtime_remote_provider_config_preflight,
        )
        from runtime_remote_provider_payload_composer import (
            RuntimeRemoteProviderPayloadRequest,
            compose_runtime_remote_provider_payload,
        )
        from runtime_remote_provider_policy import (
            RuntimeRemoteMessageClass,
            build_webhook_remote_provider_policy_contract,
        )
        from runtime_remote_provider_send_queue import (
            RuntimeRemoteProviderSendIntentStatus,
            queue_runtime_remote_provider_send_intent,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_send_queue_import:{exc}"],
        }

    missing: list[str] = []
    source_root = (
        root if (root / "runtime_remote_provider_send_queue.py").exists() else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_send_queue.py").read_text(
        encoding="utf-8"
    )
    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    preflight = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs=set(config.required_secret_refs()),
    )
    request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="remote_contact.primary",
        body_summary="Scout observing started. Group is moving as planned.",
        operator_id="operator.admin.local",
        correlation_refs=[
            "runtime_session.chilai_nanhua_day1.v0",
            "runtime_incident_bridge.guard.remote_status.v0",
        ],
    )
    payload_preview = compose_runtime_remote_provider_payload(
        policy,
        config,
        preflight,
        request,
    )
    send_intent = queue_runtime_remote_provider_send_intent(
        payload_preview,
        intent_id="remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0",
        queued_by_operator_id="operator.admin.local",
        queued_at_iso="2026-05-19T23:10:00+08:00",
    )
    blocked_payload = compose_runtime_remote_provider_payload(
        policy,
        config,
        preflight,
        request.model_copy(update={"message_class": RuntimeRemoteMessageClass.SOS}),
    )
    blocked_intent = queue_runtime_remote_provider_send_intent(
        blocked_payload,
        intent_id="remote_provider_send_intent.chilai_nanhua_day1.sos.v0",
        queued_by_operator_id="operator.admin.local",
        queued_at_iso="2026-05-19T23:12:00+08:00",
    )
    serialized = json.dumps(
        [
            send_intent.model_dump(mode="json"),
            blocked_intent.model_dump(mode="json"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"payload":',
            '"secret_value"',
            "chat_id",
        )
        if fragment in serialized
    ]
    source_has_network = any(
        token in source
        for token in (
            "import requests",
            "requests.",
            "import httpx",
            "httpx.",
            "urllib",
            "twilio",
        )
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source

    if send_intent.status != RuntimeRemoteProviderSendIntentStatus.QUEUED_NOT_SENT:
        missing.append("runtime_remote_provider_send_queue_queued")
    if not send_intent.send_intent_queued:
        missing.append("runtime_remote_provider_send_queue_queued_flag")
    if send_intent.payload_hash != payload_preview.payload_hash:
        missing.append("runtime_remote_provider_send_queue_payload_hash")
    if send_intent.delivery_target_secret_ref != "env:SCOUT_REMOTE_PRIMARY_TARGET_REF":
        missing.append("runtime_remote_provider_send_queue_target_ref")
    if not send_intent.provider_adapter_required_before_send:
        missing.append("runtime_remote_provider_send_queue_adapter_required")
    if not send_intent.manual_send_authorization_required:
        missing.append("runtime_remote_provider_send_queue_manual_auth")
    if send_intent.send_performed:
        missing.append("runtime_remote_provider_send_queue_no_send")
    if send_intent.sends_network_request:
        missing.append("runtime_remote_provider_send_queue_no_network")
    if send_intent.creates_provider_adapter:
        missing.append("runtime_remote_provider_send_queue_no_adapter")
    if send_intent.remote_notification_send_count != 0:
        missing.append("runtime_remote_provider_send_queue_no_remote_send")
    if send_intent.incident_bridge_enable_count != 0:
        missing.append("runtime_remote_provider_send_queue_no_bridge")
    if send_intent.phase2_writeback_count != 0:
        missing.append("runtime_remote_provider_send_queue_no_phase2")
    if send_intent.raw_payloads_embedded:
        missing.append("runtime_remote_provider_send_queue_no_raw")
    if send_intent.secret_values_loaded:
        missing.append("runtime_remote_provider_send_queue_no_secret_load")
    if blocked_intent.status != RuntimeRemoteProviderSendIntentStatus.BLOCKED:
        missing.append("runtime_remote_provider_send_queue_blocked")
    if blocked_intent.send_intent_queued:
        missing.append("runtime_remote_provider_send_queue_blocked_queued")
    for reason in ("payload_not_ready", "sos_provider_not_implemented"):
        if reason not in blocked_intent.blocker_reasons:
            missing.append(f"runtime_remote_provider_send_queue_reason:{reason}")
    if blocked_intent.send_performed:
        missing.append("runtime_remote_provider_send_queue_blocked_send")
    if source_has_network:
        missing.append("runtime_remote_provider_send_queue_no_network_imports")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_send_queue_no_phase1_import")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_send_queue_no_phase2_import")
    if forbidden_fragments:
        missing.append(
            "runtime_remote_provider_send_queue_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": send_intent.status.value,
        "send_intent_queued": send_intent.send_intent_queued,
        "intent_id": send_intent.intent_id,
        "provider_id": send_intent.provider_id,
        "provider_kind": send_intent.provider_kind.value,
        "endpoint_ref": send_intent.endpoint_ref,
        "recipient_ref": send_intent.recipient_ref,
        "delivery_target_secret_ref": send_intent.delivery_target_secret_ref,
        "message_class": send_intent.message_class.value,
        "payload_hash": send_intent.payload_hash,
        "queued_by_operator_id": send_intent.queued_by_operator_id,
        "queued_at_iso": send_intent.queued_at_iso,
        "provider_adapter_required_before_send": (
            send_intent.provider_adapter_required_before_send
        ),
        "manual_send_authorization_required": (
            send_intent.manual_send_authorization_required
        ),
        "summary_only": send_intent.summary_only,
        "raw_payloads_embedded": send_intent.raw_payloads_embedded,
        "secret_values_loaded": send_intent.secret_values_loaded,
        "endpoint_url_embedded": send_intent.endpoint_url_embedded,
        "token_value_embedded": send_intent.token_value_embedded,
        "creates_provider_adapter": send_intent.creates_provider_adapter,
        "sends_network_request": send_intent.sends_network_request,
        "send_performed": send_intent.send_performed,
        "remote_notification_send_count": send_intent.remote_notification_send_count,
        "incident_bridge_enable_count": send_intent.incident_bridge_enable_count,
        "phase2_writeback_count": send_intent.phase2_writeback_count,
        "blocked_status": blocked_intent.status.value,
        "blocked_send_intent_queued": blocked_intent.send_intent_queued,
        "blocked_reasons": blocked_intent.blocker_reasons,
        "source_has_network": source_has_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_remote_provider_live_adapter(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_config_preflight import (
            build_webhook_remote_provider_config_template,
            run_runtime_remote_provider_config_preflight,
        )
        from runtime_remote_provider_live_adapter import (
            RuntimeRemoteProviderLiveSendOptions,
            RuntimeRemoteProviderLiveSendStatus,
            RuntimeRemoteSecretResolver,
            resolve_runtime_remote_secret_ref,
            send_runtime_remote_provider_webhook_intent,
        )
        from runtime_remote_provider_payload_composer import (
            RuntimeRemoteProviderPayloadRequest,
            compose_runtime_remote_provider_payload,
        )
        from runtime_remote_provider_policy import (
            RuntimeRemoteMessageClass,
            build_webhook_remote_provider_policy_contract,
        )
        from runtime_remote_provider_send_queue import (
            queue_runtime_remote_provider_send_intent,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_live_adapter_import:{exc}"],
        }

    missing: list[str] = []
    source_root = (
        root
        if (root / "runtime_remote_provider_live_adapter.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_live_adapter.py").read_text(
        encoding="utf-8"
    )
    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    with tempfile.TemporaryDirectory() as tmpdir:
        token_file = Path(tmpdir) / "provider-token.txt"
        token_file.write_text("file-token\n", encoding="utf-8")
        config.auth.auth_secret_ref = f"file:{token_file}"
        config.auth.signature_secret_ref = "keychain:scout/webhook-hmac"
        config.recipients[0].delivery_target_secret_ref = (
            "keychain:scout/primary-target"
        )
        preflight = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
        )
        request = RuntimeRemoteProviderPayloadRequest(
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="remote_contact.primary",
            body_summary="Scout observing started. Group is moving as planned.",
            operator_id="operator.admin.local",
            correlation_refs=[
                "runtime_session.chilai_nanhua_day1.v0",
                "runtime_incident_bridge.guard.remote_status.v0",
            ],
        )
        payload_preview = compose_runtime_remote_provider_payload(
            policy,
            config,
            preflight,
            request,
        )
        send_intent = queue_runtime_remote_provider_send_intent(
            payload_preview,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:10:00+08:00",
        )
        resolver = RuntimeRemoteSecretResolver(
            env={"SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook"},
            keychain_resolver=lambda service, account: f"keychain:{service}:{account}",
        )
        env_secret = resolve_runtime_remote_secret_ref(
            "env:SCOUT_REMOTE_WEBHOOK_URL",
            resolver=resolver,
        )
        file_secret = resolve_runtime_remote_secret_ref(
            f"file:{token_file}",
            resolver=resolver,
        )
        keychain_secret = resolve_runtime_remote_secret_ref(
            "keychain:scout/primary-target",
            resolver=resolver,
        )
        default_transport_calls: list[Any] = []
        default_blocked = send_runtime_remote_provider_webhook_intent(
            config,
            send_intent,
            options=RuntimeRemoteProviderLiveSendOptions(),
            resolver=resolver,
            transport=lambda web_request: default_transport_calls.append(web_request),
        )
        captured_requests: list[Any] = []

        def fake_transport(web_request: Any) -> dict[str, Any]:
            captured_requests.append(web_request)
            return {
                "status_code": 200,
                "response_body": "accepted",
                "provider_message_ref": "provider-message-001",
            }

        sent = send_runtime_remote_provider_webhook_intent(
            config,
            send_intent,
            options=RuntimeRemoteProviderLiveSendOptions(
                provider_adapter_enabled=True,
                live_network_send_enabled=True,
                manual_send_authorization=True,
            ),
            resolver=resolver,
            transport=fake_transport,
        )
        blocked_intent = send_intent.model_copy(
            update={
                "status": "send_intent_blocked",
                "send_intent_queued": False,
                "blocker_reasons": ["payload_not_ready"],
            }
        )
        blocked_send = send_runtime_remote_provider_webhook_intent(
            config,
            blocked_intent,
            options=RuntimeRemoteProviderLiveSendOptions(
                provider_adapter_enabled=True,
                live_network_send_enabled=True,
                manual_send_authorization=True,
            ),
            resolver=resolver,
            transport=fake_transport,
        )

    serialized = json.dumps(
        [
            env_secret.model_dump(mode="json"),
            file_secret.model_dump(mode="json"),
            keychain_secret.model_dump(mode="json"),
            default_blocked.model_dump(mode="json"),
            sent.model_dump(mode="json"),
            blocked_send.model_dump(mode="json"),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    forbidden_fragments = [
        fragment
        for fragment in (
            "locationLatitude",
            "locationLongitude",
            "accelerometerAccelerationX",
            "pedometerDistance",
            '"payload":',
            '"secret_value"',
            "file-token",
            "keychain:scout:primary-target",
            "webhook-hmac",
        )
        if fragment in serialized
    ]
    source_has_stdlib_network = "urllib.request" in source
    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.", "twilio")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source

    if env_secret.scheme != "env":
        missing.append("runtime_remote_provider_live_adapter_env_secret")
    if file_secret.scheme != "file":
        missing.append("runtime_remote_provider_live_adapter_file_secret")
    if keychain_secret.scheme != "keychain":
        missing.append("runtime_remote_provider_live_adapter_keychain_secret")
    if default_blocked.status != RuntimeRemoteProviderLiveSendStatus.BLOCKED:
        missing.append("runtime_remote_provider_live_adapter_default_blocked")
    for reason in (
        "provider_adapter_not_enabled",
        "live_network_send_not_enabled",
        "manual_send_authorization_missing",
    ):
        if reason not in default_blocked.blocker_reasons:
            missing.append(f"runtime_remote_provider_live_adapter_default_reason:{reason}")
    if default_blocked.live_network_send_attempted:
        missing.append("runtime_remote_provider_live_adapter_default_attempt")
    if default_transport_calls:
        missing.append("runtime_remote_provider_live_adapter_default_transport")
    if sent.status != RuntimeRemoteProviderLiveSendStatus.SENT:
        missing.append("runtime_remote_provider_live_adapter_sent")
    if not sent.live_network_send_attempted:
        missing.append("runtime_remote_provider_live_adapter_attempted")
    if not sent.send_performed:
        missing.append("runtime_remote_provider_live_adapter_performed")
    if sent.remote_notification_send_count != 1:
        missing.append("runtime_remote_provider_live_adapter_send_count")
    if sent.http_status_code != 200:
        missing.append("runtime_remote_provider_live_adapter_http_status")
    if sent.provider_message_ref != "provider-message-001":
        missing.append("runtime_remote_provider_live_adapter_provider_ref")
    if sent.secret_ref_schemes != ["env", "file", "keychain", "keychain"]:
        missing.append("runtime_remote_provider_live_adapter_secret_schemes")
    if sent.raw_secret_values_embedded:
        missing.append("runtime_remote_provider_live_adapter_secret_leak")
    if sent.endpoint_url_embedded:
        missing.append("runtime_remote_provider_live_adapter_url_leak")
    if sent.token_value_embedded:
        missing.append("runtime_remote_provider_live_adapter_token_leak")
    if len(captured_requests) != 1:
        missing.append("runtime_remote_provider_live_adapter_transport_call")
    elif captured_requests[0].method != "POST":
        missing.append("runtime_remote_provider_live_adapter_method")
    if blocked_send.status != RuntimeRemoteProviderLiveSendStatus.BLOCKED:
        missing.append("runtime_remote_provider_live_adapter_blocked_intent")
    if blocked_send.live_network_send_attempted:
        missing.append("runtime_remote_provider_live_adapter_blocked_attempt")
    if "send_intent_not_queued" not in blocked_send.blocker_reasons:
        missing.append("runtime_remote_provider_live_adapter_blocked_reason")
    if sent.incident_bridge_enable_count != 0:
        missing.append("runtime_remote_provider_live_adapter_no_bridge")
    if sent.phase2_writeback_count != 0:
        missing.append("runtime_remote_provider_live_adapter_no_phase2")
    if sent.raw_payloads_embedded:
        missing.append("runtime_remote_provider_live_adapter_no_raw_payload")
    if not source_has_stdlib_network:
        missing.append("runtime_remote_provider_live_adapter_urllib")
    if source_has_nonstdlib_network:
        missing.append("runtime_remote_provider_live_adapter_no_nonstdlib_network")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_live_adapter_no_phase1_import")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_live_adapter_no_phase2_import")
    if forbidden_fragments:
        missing.append(
            "runtime_remote_provider_live_adapter_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": sent.status.value,
        "default_status": default_blocked.status.value,
        "default_blocker_reasons": default_blocked.blocker_reasons,
        "blocked_intent_status": blocked_send.status.value,
        "blocked_intent_reasons": blocked_send.blocker_reasons,
        "provider_id": sent.provider_id,
        "provider_kind": sent.provider_kind.value,
        "endpoint_ref": sent.endpoint_ref,
        "recipient_ref": sent.recipient_ref,
        "delivery_target_secret_ref": sent.delivery_target_secret_ref,
        "message_class": sent.message_class.value,
        "payload_hash": sent.payload_hash,
        "request_body_hash": sent.request_body_hash,
        "queued_intent_id": sent.queued_intent_id,
        "live_network_send_attempted": sent.live_network_send_attempted,
        "send_performed": sent.send_performed,
        "remote_notification_send_count": sent.remote_notification_send_count,
        "http_status_code": sent.http_status_code,
        "provider_message_ref": sent.provider_message_ref,
        "secret_values_loaded": sent.secret_values_loaded,
        "secret_values_loaded_count": sent.secret_values_loaded_count,
        "secret_ref_schemes": [scheme.value for scheme in sent.secret_ref_schemes],
        "raw_secret_values_embedded": sent.raw_secret_values_embedded,
        "endpoint_url_embedded": sent.endpoint_url_embedded,
        "token_value_embedded": sent.token_value_embedded,
        "creates_provider_adapter": sent.creates_provider_adapter,
        "sends_network_request": sent.sends_network_request,
        "incident_bridge_enable_count": sent.incident_bridge_enable_count,
        "phase2_writeback_count": sent.phase2_writeback_count,
        "source_has_stdlib_network": source_has_stdlib_network,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "forbidden_fragment_count": len(forbidden_fragments),
        "transport_call_count": len(captured_requests),
        "missing": missing,
    }


def _check_runtime_remote_provider_live_send_cli(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_config_preflight import (
            build_webhook_remote_provider_config_template,
            run_runtime_remote_provider_config_preflight,
        )
        from runtime_remote_provider_live_adapter import RuntimeRemoteSecretResolver
        from runtime_remote_provider_live_send_cli import (
            run_runtime_remote_provider_live_send_cli,
        )
        from runtime_remote_provider_payload_composer import (
            RuntimeRemoteProviderPayloadRequest,
            compose_runtime_remote_provider_payload,
        )
        from runtime_remote_provider_policy import (
            RuntimeRemoteMessageClass,
            build_webhook_remote_provider_policy_contract,
        )
        from runtime_remote_provider_send_queue import (
            queue_runtime_remote_provider_send_intent,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_live_send_cli_import:{exc}"],
        }

    missing: list[str] = []
    source_root = (
        root
        if (root / "runtime_remote_provider_live_send_cli.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_live_send_cli.py").read_text(
        encoding="utf-8"
    )
    policy = build_webhook_remote_provider_policy_contract()
    config = build_webhook_remote_provider_config_template(policy)
    preflight = run_runtime_remote_provider_config_preflight(
        policy,
        config,
        available_secret_refs=set(config.required_secret_refs()),
    )
    request = RuntimeRemoteProviderPayloadRequest(
        message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
        recipient_ref="remote_contact.primary",
        body_summary="Scout observing started. Group is moving as planned.",
        operator_id="operator.admin.local",
        correlation_refs=[
            "runtime_session.chilai_nanhua_day1.v0",
            "runtime_incident_bridge.guard.remote_status.v0",
        ],
    )
    payload_preview = compose_runtime_remote_provider_payload(
        policy,
        config,
        preflight,
        request,
    )
    send_intent = queue_runtime_remote_provider_send_intent(
        payload_preview,
        intent_id="remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0",
        queued_by_operator_id="operator.admin.local",
        queued_at_iso="2026-05-19T23:10:00+08:00",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        config_path = tmp_root / "provider-config.json"
        intent_path = tmp_root / "send-intent.json"
        default_output_path = tmp_root / "default-result.json"
        sent_output_path = tmp_root / "sent-result.json"
        missing_output_path = tmp_root / "missing-result.json"
        config_path.write_text(config.to_json(), encoding="utf-8")
        intent_path.write_text(send_intent.to_json(), encoding="utf-8")
        resolver = RuntimeRemoteSecretResolver(
            env={
                "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
                "SCOUT_REMOTE_WEBHOOK_TOKEN": "super-secret-provider-token",
                "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "hmac-secret",
                "SCOUT_REMOTE_PRIMARY_TARGET_REF": "target-secret-value",
                "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup-secret-value",
            }
        )
        default_transport_calls: list[Any] = []
        default_exit, default_result = run_runtime_remote_provider_live_send_cli(
            [
                "--config",
                str(config_path),
                "--intent",
                str(intent_path),
                "--output",
                str(default_output_path),
            ],
            resolver=resolver,
            transport=lambda web_request: default_transport_calls.append(web_request),
        )
        captured_requests: list[Any] = []

        def fake_transport(web_request: Any) -> dict[str, Any]:
            captured_requests.append(web_request)
            return {
                "status_code": 202,
                "response_body": "accepted",
                "provider_message_ref": "provider-message-cli-001",
            }

        sent_exit, sent_result = run_runtime_remote_provider_live_send_cli(
            [
                "--config",
                str(config_path),
                "--intent",
                str(intent_path),
                "--output",
                str(sent_output_path),
                "--enable-provider-adapter",
                "--enable-live-network-send",
                "--authorize-manual-send",
            ],
            resolver=resolver,
            transport=fake_transport,
        )
        missing_exit, missing_result = run_runtime_remote_provider_live_send_cli(
            [
                "--config",
                str(tmp_root / "missing-config.json"),
                "--intent",
                str(tmp_root / "missing-intent.json"),
                "--output",
                str(missing_output_path),
                "--enable-provider-adapter",
                "--enable-live-network-send",
                "--authorize-manual-send",
            ],
            resolver=resolver,
            transport=fake_transport,
        )
        written = (
            default_output_path.read_text(encoding="utf-8")
            + sent_output_path.read_text(encoding="utf-8")
            + missing_output_path.read_text(encoding="utf-8")
        )

    forbidden_fragments = [
        fragment
        for fragment in (
            "https://example.invalid/webhook",
            "super-secret-provider-token",
            "target-secret-value",
            "backup-secret-value",
            '"secret_value"',
            "locationLatitude",
            "accelerometerAccelerationX",
            '"payload":',
        )
        if fragment in written
    ]
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source
    source_has_nonstdlib_network = any(
        token in source for token in ("import requests", "requests.", "import httpx", "httpx.")
    )

    if default_exit != 2:
        missing.append("runtime_remote_provider_live_send_cli_default_exit")
    if default_result.status != "live_send_blocked":
        missing.append("runtime_remote_provider_live_send_cli_default_blocked")
    for reason in (
        "provider_adapter_not_enabled",
        "live_network_send_not_enabled",
        "manual_send_authorization_missing",
    ):
        if reason not in default_result.blocker_reasons:
            missing.append(f"runtime_remote_provider_live_send_cli_default_reason:{reason}")
    if default_result.live_network_send_attempted:
        missing.append("runtime_remote_provider_live_send_cli_default_attempt")
    if default_transport_calls:
        missing.append("runtime_remote_provider_live_send_cli_default_transport")
    if sent_exit != 0:
        missing.append("runtime_remote_provider_live_send_cli_sent_exit")
    if sent_result.status != "sent":
        missing.append("runtime_remote_provider_live_send_cli_sent_status")
    if sent_result.http_status_code != 202:
        missing.append("runtime_remote_provider_live_send_cli_sent_http")
    if sent_result.provider_message_ref != "provider-message-cli-001":
        missing.append("runtime_remote_provider_live_send_cli_provider_ref")
    if not sent_result.live_network_send_attempted:
        missing.append("runtime_remote_provider_live_send_cli_sent_attempt")
    if not sent_result.send_performed:
        missing.append("runtime_remote_provider_live_send_cli_sent_performed")
    if len(captured_requests) != 1:
        missing.append("runtime_remote_provider_live_send_cli_transport_count")
    elif captured_requests[0].method != "POST":
        missing.append("runtime_remote_provider_live_send_cli_transport_method")
    if missing_exit != 2:
        missing.append("runtime_remote_provider_live_send_cli_missing_exit")
    if missing_result.status != "operator_request_blocked":
        missing.append("runtime_remote_provider_live_send_cli_missing_status")
    for reason in ("missing_config_artifact", "missing_send_intent_artifact"):
        if reason not in missing_result.blocker_reasons:
            missing.append(f"runtime_remote_provider_live_send_cli_missing_reason:{reason}")
    if missing_result.live_network_send_attempted:
        missing.append("runtime_remote_provider_live_send_cli_missing_attempt")
    if sent_result.incident_bridge_enable_count != 0:
        missing.append("runtime_remote_provider_live_send_cli_no_bridge")
    if sent_result.phase2_writeback_count != 0:
        missing.append("runtime_remote_provider_live_send_cli_no_phase2")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_live_send_cli_no_phase1_import")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_live_send_cli_no_phase2_import")
    if source_has_nonstdlib_network:
        missing.append("runtime_remote_provider_live_send_cli_no_nonstdlib_network")
    if forbidden_fragments:
        missing.append(
            "runtime_remote_provider_live_send_cli_forbidden_fragments:"
            + ",".join(forbidden_fragments)
        )

    return {
        "ok": not missing,
        "status": sent_result.status.value,
        "default_exit_code": default_exit,
        "default_status": default_result.status.value,
        "default_blocker_reasons": default_result.blocker_reasons,
        "default_live_network_send_attempted": (
            default_result.live_network_send_attempted
        ),
        "sent_exit_code": sent_exit,
        "sent_status": sent_result.status.value,
        "sent_http_status_code": sent_result.http_status_code,
        "provider_message_ref": sent_result.provider_message_ref,
        "sent_live_network_send_attempted": sent_result.live_network_send_attempted,
        "sent_send_performed": sent_result.send_performed,
        "sent_remote_notification_send_count": (
            sent_result.remote_notification_send_count
        ),
        "transport_call_count": len(captured_requests),
        "missing_exit_code": missing_exit,
        "missing_status": missing_result.status,
        "missing_blocker_reasons": missing_result.blocker_reasons,
        "secret_values_loaded": sent_result.secret_values_loaded,
        "raw_secret_values_embedded": sent_result.raw_secret_values_embedded,
        "endpoint_url_embedded": sent_result.endpoint_url_embedded,
        "token_value_embedded": sent_result.token_value_embedded,
        "incident_bridge_enable_count": sent_result.incident_bridge_enable_count,
        "phase2_writeback_count": sent_result.phase2_writeback_count,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "forbidden_fragment_count": len(forbidden_fragments),
        "missing": missing,
    }


def _check_runtime_remote_provider_demo_harness(root: Path) -> dict[str, Any]:
    try:
        import urllib.request

        from runtime_remote_provider_demo_harness import (
            run_local_webhook_demo_harness,
        )
    except Exception as exc:
        return {
            "ok": False,
            "capture_count": 0,
            "missing": [f"runtime_remote_provider_demo_harness_import:{exc}"],
        }

    source_root = (
        root
        if (root / "runtime_remote_provider_demo_harness.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_demo_harness.py").read_text(
        encoding="utf-8"
    )
    payload = {
        "provider_id": "remote_provider.webhook_telegram_like.v0",
        "message_class": "remote_status",
        "body_preview": "Local release-check webhook capture.",
    }
    body = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    missing: list[str] = []
    response_status = None
    response_payload: dict[str, Any] = {}
    capture_count = 0
    captured_path = None
    captured_method = None
    captured_body_hash = None
    try:
        with run_local_webhook_demo_harness() as harness:
            request = urllib.request.Request(
                harness.webhook_url("/capture"),
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                response_status = response.status
                response_payload = json.loads(response.read().decode("utf-8"))

            capture_count = harness.capture_count
            if harness.captured_requests:
                captured = harness.captured_requests[0]
                captured_path = captured.path
                captured_method = captured.method
                captured_body_hash = captured.body_hash
    except Exception as exc:
        missing.append(f"runtime_remote_provider_demo_harness_smoke:{exc}")

    expected_hash = hashlib.sha256(body).hexdigest()
    source_has_stdlib_http_server = "ThreadingHTTPServer" in source
    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source

    if response_status != 202:
        missing.append("runtime_remote_provider_demo_harness_status")
    if response_payload.get("status") != "captured":
        missing.append("runtime_remote_provider_demo_harness_response_status")
    if capture_count != 1:
        missing.append("runtime_remote_provider_demo_harness_capture_count")
    if captured_path != "/capture":
        missing.append("runtime_remote_provider_demo_harness_path")
    if captured_method != "POST":
        missing.append("runtime_remote_provider_demo_harness_method")
    if captured_body_hash != expected_hash:
        missing.append("runtime_remote_provider_demo_harness_body_hash")
    if response_payload.get("body_hash") != expected_hash:
        missing.append("runtime_remote_provider_demo_harness_response_hash")
    if not source_has_stdlib_http_server:
        missing.append("runtime_remote_provider_demo_harness_stdlib_server")
    if source_has_nonstdlib_network:
        missing.append("runtime_remote_provider_demo_harness_no_nonstdlib_network")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_demo_harness_no_phase1_bridge")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_demo_harness_no_phase2_store")

    return {
        "ok": not missing,
        "response_status": response_status,
        "response_payload_status": response_payload.get("status"),
        "capture_count": capture_count,
        "captured_method": captured_method,
        "captured_path": captured_path,
        "captured_body_hash": captured_body_hash,
        "source_has_stdlib_http_server": source_has_stdlib_http_server,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "missing": missing,
    }


def _check_runtime_remote_provider_demo_bundle(root: Path) -> dict[str, Any]:
    try:
        import re
        from urllib.parse import urlparse

        from runtime_remote_provider_demo_bundle import (
            build_local_webhook_demo_bundle,
        )
        from runtime_remote_provider_demo_harness import (
            run_local_webhook_demo_harness,
        )
        from runtime_remote_provider_live_adapter import RuntimeRemoteSecretResolver
        from runtime_remote_provider_live_send_cli import (
            run_runtime_remote_provider_live_send_cli,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "missing": [f"runtime_remote_provider_demo_bundle_import:{exc}"],
        }

    source_root = (
        root
        if (root / "runtime_remote_provider_demo_bundle.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_demo_bundle.py").read_text(
        encoding="utf-8"
    )
    missing: list[str] = []
    summary_status = None
    sent_status = None
    sent_http_status_code = None
    remote_notification_send_count = None
    incident_bridge_enable_count = None
    phase2_writeback_count = None
    capture_count = 0
    bundle_url_hostnames: list[str | None] = []
    bundle_forbidden_fragments: list[str] = []
    expected_paths_present = False
    external_network_allowed = None
    localhost_only = None

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with run_local_webhook_demo_harness() as harness:
                summary = build_local_webhook_demo_bundle(
                    tmpdir,
                    harness.webhook_url("/capture"),
                )
                summary_status = summary.status
                localhost_only = summary.localhost_only
                external_network_allowed = summary.external_network_allowed
                output_path = Path(tmpdir) / "release_check_live_send_result.json"
                demo_env = _load_json(Path(summary.demo_env_path))
                exit_code, result = run_runtime_remote_provider_live_send_cli(
                    [
                        "--config",
                        summary.provider_config_path,
                        "--intent",
                        summary.send_intent_path,
                        "--output",
                        str(output_path),
                        "--enable-provider-adapter",
                        "--enable-live-network-send",
                        "--authorize-manual-send",
                    ],
                    resolver=RuntimeRemoteSecretResolver(env=demo_env["env"]),
                )
                sent_status = getattr(result.status, "value", result.status)
                sent_http_status_code = result.http_status_code
                remote_notification_send_count = result.remote_notification_send_count
                incident_bridge_enable_count = result.incident_bridge_enable_count
                phase2_writeback_count = result.phase2_writeback_count
                capture_count = harness.capture_count
                if exit_code != 0:
                    missing.append("runtime_remote_provider_demo_bundle_cli_exit")

                expected_paths = [
                    summary.provider_config_path,
                    summary.send_intent_path,
                    summary.payload_preview_path,
                    summary.operator_command_path,
                    summary.demo_env_path,
                    str(Path(tmpdir) / "demo_summary.json"),
                    str(output_path),
                ]
                expected_paths_present = all(Path(path).exists() for path in expected_paths)
                combined = "\n".join(
                    Path(path).read_text(encoding="utf-8")
                    for path in expected_paths
                    if Path(path).exists()
                )
                bundle_url_hostnames = [
                    urlparse(url).hostname
                    for url in re.findall(r"https?://[^\s'\"<>]+", combined)
                ]
                bundle_forbidden_fragments = [
                    fragment
                    for fragment in (
                        "https://example.invalid",
                        "Phase1IncidentBridge",
                        "Phase2Brain",
                        "accelerometerAccelerationX",
                        "locationLatitude",
                    )
                    if fragment in combined
                ]
    except Exception as exc:
        missing.append(f"runtime_remote_provider_demo_bundle_smoke:{exc}")

    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source
    non_localhost_urls = [
        hostname
        for hostname in bundle_url_hostnames
        if hostname not in {"127.0.0.1", "localhost"}
    ]

    if summary_status != "ready":
        missing.append("runtime_remote_provider_demo_bundle_ready")
    if localhost_only is not True:
        missing.append("runtime_remote_provider_demo_bundle_localhost_only")
    if external_network_allowed is not False:
        missing.append("runtime_remote_provider_demo_bundle_no_external_network")
    if sent_status != "sent":
        missing.append("runtime_remote_provider_demo_bundle_sent")
    if sent_http_status_code != 202:
        missing.append("runtime_remote_provider_demo_bundle_http_status")
    if remote_notification_send_count != 1:
        missing.append("runtime_remote_provider_demo_bundle_send_count")
    if incident_bridge_enable_count != 0:
        missing.append("runtime_remote_provider_demo_bundle_no_bridge")
    if phase2_writeback_count != 0:
        missing.append("runtime_remote_provider_demo_bundle_no_phase2")
    if capture_count != 1:
        missing.append("runtime_remote_provider_demo_bundle_capture_count")
    if not expected_paths_present:
        missing.append("runtime_remote_provider_demo_bundle_paths")
    if non_localhost_urls:
        missing.append("runtime_remote_provider_demo_bundle_non_localhost_urls")
    if bundle_forbidden_fragments:
        missing.append(
            "runtime_remote_provider_demo_bundle_forbidden_fragments:"
            + ",".join(bundle_forbidden_fragments)
        )
    if source_has_nonstdlib_network:
        missing.append("runtime_remote_provider_demo_bundle_no_nonstdlib_network")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_demo_bundle_no_phase1_bridge")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_demo_bundle_no_phase2_store")

    return {
        "ok": not missing,
        "status": summary_status,
        "localhost_only": localhost_only,
        "external_network_allowed": external_network_allowed,
        "sent_status": sent_status,
        "sent_http_status_code": sent_http_status_code,
        "remote_notification_send_count": remote_notification_send_count,
        "incident_bridge_enable_count": incident_bridge_enable_count,
        "phase2_writeback_count": phase2_writeback_count,
        "capture_count": capture_count,
        "expected_paths_present": expected_paths_present,
        "bundle_url_hostnames": bundle_url_hostnames,
        "non_localhost_url_count": len(non_localhost_urls),
        "forbidden_fragment_count": len(bundle_forbidden_fragments),
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "missing": missing,
    }


def _check_runtime_remote_provider_external_demo_bundle(root: Path) -> dict[str, Any]:
    try:
        from runtime_remote_provider_demo_bundle import (
            build_external_webhook_demo_bundle,
        )
    except Exception as exc:
        return {
            "ok": False,
            "blocked_status": None,
            "ready_status": None,
            "missing": [f"runtime_remote_provider_external_demo_bundle_import:{exc}"],
        }

    source_root = (
        root
        if (root / "runtime_remote_provider_demo_bundle.py").exists()
        else REPO_ROOT
    )
    source = (source_root / "runtime_remote_provider_demo_bundle.py").read_text(
        encoding="utf-8"
    )
    missing: list[str] = []
    blocked_status = None
    ready_status = None
    blocked_missing_secret_count = None
    ready_missing_secret_count = None
    ready_send_intent_status = None
    blocked_send_intent_status = None
    external_network_allowed = None
    localhost_only = None
    expected_paths_present = False
    forbidden_fragment_count = 0
    secret_values_embedded = None

    required_refs = {
        "env:SCOUT_REMOTE_WEBHOOK_URL",
        "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
        "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
        "env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
        "env:SCOUT_REMOTE_BACKUP_TARGET_REF",
    }
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            blocked = build_external_webhook_demo_bundle(Path(tmpdir) / "blocked")
            ready = build_external_webhook_demo_bundle(
                Path(tmpdir) / "ready",
                available_secret_refs=required_refs,
            )
            blocked_status = blocked.status
            ready_status = ready.status
            blocked_missing_secret_count = len(blocked.missing_secret_refs)
            ready_missing_secret_count = len(ready.missing_secret_refs)
            blocked_send_intent_status = blocked.send_intent_status
            ready_send_intent_status = ready.send_intent_status
            external_network_allowed = ready.external_network_allowed
            localhost_only = ready.localhost_only
            secret_values_embedded = ready.secret_values_embedded
            expected_paths = [
                blocked.provider_config_path,
                blocked.send_intent_path,
                blocked.payload_preview_path,
                blocked.operator_command_path,
                blocked.secret_refs_path,
                str(Path(blocked.output_dir) / "demo_summary.json"),
                ready.provider_config_path,
                ready.send_intent_path,
                ready.payload_preview_path,
                ready.operator_command_path,
                ready.secret_refs_path,
                str(Path(ready.output_dir) / "demo_summary.json"),
            ]
            expected_paths_present = all(Path(path).exists() for path in expected_paths)
            combined = "\n".join(
                Path(path).read_text(encoding="utf-8")
                for path in expected_paths
                if Path(path).exists()
            )
            forbidden_fragment_count = len(
                [
                    fragment
                    for fragment in (
                        "https://example.invalid",
                        "operator-secret-not-exported",
                        "Phase1IncidentBridge",
                        "Phase2Brain",
                        "accelerometerAccelerationX",
                        "locationLatitude",
                    )
                    if fragment in combined
                ]
            )
    except Exception as exc:
        missing.append(f"runtime_remote_provider_external_demo_bundle_smoke:{exc}")

    source_has_nonstdlib_network = any(
        token in source
        for token in ("import requests", "requests.", "import httpx", "httpx.")
    )
    source_has_phase1_bridge = "Phase1IncidentBridge" in source
    source_has_phase2_store = "BrainFileStore" in source or "Phase2Brain" in source

    if blocked_status != "blocked_missing_secret_refs":
        missing.append("runtime_remote_provider_external_demo_bundle_blocked_status")
    if ready_status != "ready_requires_manual_send":
        missing.append("runtime_remote_provider_external_demo_bundle_ready_status")
    if blocked_missing_secret_count != len(required_refs):
        missing.append("runtime_remote_provider_external_demo_bundle_missing_refs")
    if ready_missing_secret_count != 0:
        missing.append("runtime_remote_provider_external_demo_bundle_ready_missing_refs")
    if blocked_send_intent_status != "send_intent_blocked":
        missing.append("runtime_remote_provider_external_demo_bundle_blocked_intent")
    if ready_send_intent_status != "queued_not_sent":
        missing.append("runtime_remote_provider_external_demo_bundle_ready_intent")
    if external_network_allowed is not True:
        missing.append("runtime_remote_provider_external_demo_bundle_external_network")
    if localhost_only is not False:
        missing.append("runtime_remote_provider_external_demo_bundle_not_localhost")
    if secret_values_embedded is not False:
        missing.append("runtime_remote_provider_external_demo_bundle_secret_values")
    if not expected_paths_present:
        missing.append("runtime_remote_provider_external_demo_bundle_paths")
    if forbidden_fragment_count:
        missing.append("runtime_remote_provider_external_demo_bundle_forbidden_fragments")
    if source_has_nonstdlib_network:
        missing.append("runtime_remote_provider_external_demo_bundle_no_nonstdlib_network")
    if source_has_phase1_bridge:
        missing.append("runtime_remote_provider_external_demo_bundle_no_phase1_bridge")
    if source_has_phase2_store:
        missing.append("runtime_remote_provider_external_demo_bundle_no_phase2_store")

    return {
        "ok": not missing,
        "blocked_status": blocked_status,
        "ready_status": ready_status,
        "blocked_missing_secret_count": blocked_missing_secret_count,
        "ready_missing_secret_count": ready_missing_secret_count,
        "blocked_send_intent_status": blocked_send_intent_status,
        "ready_send_intent_status": ready_send_intent_status,
        "external_network_allowed": external_network_allowed,
        "localhost_only": localhost_only,
        "secret_values_embedded": secret_values_embedded,
        "expected_paths_present": expected_paths_present,
        "forbidden_fragment_count": forbidden_fragment_count,
        "source_has_nonstdlib_network": source_has_nonstdlib_network,
        "source_has_phase1_bridge": source_has_phase1_bridge,
        "source_has_phase2_store": source_has_phase2_store,
        "missing": missing,
    }


def _check_after_action_next_plan_candidates(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_after_action_candidates import AfterActionNextPlanCandidateExport

    ref = project.get("after_action_next_plan_candidates_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "candidate_count": 0,
            "expected_count": project.get("after_action_next_plan_candidate_count"),
            "incident_package_ref_count": None,
            "observed_fact_writeback_allowed": None,
            "historical_evidence_mutation_allowed": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "after_action_next_plan_candidates_ref")],
        }

    try:
        export = AfterActionNextPlanCandidateExport.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "candidate_count": len(payload.get("candidates", [])),
            "expected_count": project.get("after_action_next_plan_candidate_count"),
            "incident_package_ref_count": payload.get("counts", {}).get("incident_package_ref_count"),
            "observed_fact_writeback_allowed": payload.get("observed_fact_writeback_allowed"),
            "historical_evidence_mutation_allowed": payload.get(
                "historical_evidence_mutation_allowed"
            ),
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    candidate_count = len(export.candidates)
    expected_count = project.get("after_action_next_plan_candidate_count")
    if export.status != "candidate_only":
        missing.append("after_action_status:candidate_only")
    if candidate_count != expected_count:
        missing.append(f"after_action_candidate_count:{expected_count}")
    if export.counts.get("candidate_count") != candidate_count:
        missing.append("after_action_counts_candidate_count")
    if export.observed_fact_writeback_allowed:
        missing.append("after_action_no_observed_fact_writeback")
    if export.historical_evidence_mutation_allowed:
        missing.append("after_action_no_historical_evidence_mutation")
    if export.raw_payloads_embedded:
        missing.append("after_action_no_raw_payloads_embedded")
    if any(not candidate.candidate_only for candidate in export.candidates):
        missing.append("after_action_all_candidates_candidate_only")
    if any(not candidate.human_review_required for candidate in export.candidates):
        missing.append("after_action_all_candidates_human_review_required")
    if any(candidate.observed_fact_writeback_allowed for candidate in export.candidates):
        missing.append("after_action_no_candidate_observed_fact_writeback")
    if any(candidate.historical_evidence_mutation_allowed for candidate in export.candidates):
        missing.append("after_action_no_candidate_historical_mutation")

    return {
        "ok": not missing,
        "status": export.status,
        "candidate_count": candidate_count,
        "expected_count": expected_count,
        "source_case_id": export.source_case_id,
        "evidence_ref_count": export.counts.get("evidence_ref_count", 0),
        "brain_node_ref_count": export.counts.get("brain_node_ref_count", 0),
        "incident_package_ref_count": export.counts.get("incident_package_ref_count", 0),
        "observed_fact_writeback_allowed": export.observed_fact_writeback_allowed,
        "historical_evidence_mutation_allowed": export.historical_evidence_mutation_allowed,
        "raw_payloads_embedded": export.raw_payloads_embedded,
        "missing": missing,
    }


def _check_review_queue_manifest(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_review_queue import PreTripReviewQueueManifest

    ref = project.get("review_queue_manifest_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "item_count": 0,
            "expected_count": project.get("review_queue_item_count"),
            "warning_count": None,
            "blocker_count": None,
            "decisions_recorded": None,
            "accepts_candidates": None,
            "package_mutation_allowed": None,
            "phase1_runtime_mutation_allowed": None,
            "missing": [str(ref or "review_queue_manifest_ref")],
        }

    try:
        manifest = PreTripReviewQueueManifest.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "ok": False,
            "status": payload.get("status"),
            "item_count": counts.get("item_count", 0),
            "expected_count": project.get("review_queue_item_count"),
            "warning_count": counts.get("warning_count"),
            "blocker_count": counts.get("blocker_count"),
            "decisions_recorded": boundary.get("decisions_recorded"),
            "accepts_candidates": boundary.get("accepts_candidates"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get(
                "phase1_runtime_mutation_allowed"
            ),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    item_count = len(manifest.items)
    expected_count = project.get("review_queue_item_count")
    if manifest.status != "candidate_review_queue_only":
        missing.append("review_queue_status:candidate_review_queue_only")
    if item_count != expected_count:
        missing.append(f"review_queue_item_count:{expected_count}")
    if manifest.counts.item_count != item_count:
        missing.append("review_queue_counts_item_count")
    if manifest.boundary.decisions_recorded:
        missing.append("review_queue_no_decisions_recorded")
    if manifest.boundary.accepts_candidates or manifest.boundary.rejects_candidates:
        missing.append("review_queue_no_accept_reject")
    if manifest.boundary.package_mutation_allowed:
        missing.append("review_queue_no_package_mutation")
    if manifest.boundary.review_log_mutation_allowed:
        missing.append("review_queue_no_review_log_mutation")
    if manifest.boundary.phase1_runtime_mutation_allowed:
        missing.append("review_queue_no_phase1_runtime_mutation")
    if manifest.boundary.phase2_writeback_allowed:
        missing.append("review_queue_no_phase2_writeback")
    if manifest.boundary.raw_payloads_embedded:
        missing.append("review_queue_no_raw_payloads")
    if manifest.boundary.ui_included:
        missing.append("review_queue_no_ui")

    return {
        "ok": not missing,
        "status": manifest.status,
        "item_count": item_count,
        "expected_count": expected_count,
        "warning_count": manifest.counts.warning_count,
        "blocker_count": manifest.counts.blocker_count,
        "review_count": manifest.counts.review_count,
        "source_ref_count": manifest.counts.source_ref_count,
        "category_counts": manifest.counts.category_counts,
        "decisions_recorded": manifest.boundary.decisions_recorded,
        "accepts_candidates": manifest.boundary.accepts_candidates,
        "rejects_candidates": manifest.boundary.rejects_candidates,
        "package_mutation_allowed": manifest.boundary.package_mutation_allowed,
        "review_log_mutation_allowed": manifest.boundary.review_log_mutation_allowed,
        "phase1_runtime_mutation_allowed": (
            manifest.boundary.phase1_runtime_mutation_allowed
        ),
        "phase2_writeback_allowed": manifest.boundary.phase2_writeback_allowed,
        "raw_payloads_embedded": manifest.boundary.raw_payloads_embedded,
        "ui_included": manifest.boundary.ui_included,
        "missing": missing,
    }


def _check_review_draft_log(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_review_draft_fixture import PreTripReviewDraftLog

    ref = project.get("review_draft_log_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "action_count": 0,
            "expected_count": project.get("review_draft_action_count"),
            "category_counts": {},
            "decisions_recorded": None,
            "source_mutation_allowed": None,
            "package_mutation_allowed": None,
            "runtime_mutation_allowed": None,
            "phase1_runtime_mutation_allowed": None,
            "admin_api_integration": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "review_draft_log_ref")],
        }

    try:
        draft_log = PreTripReviewDraftLog.model_validate(payload)
    except Exception as exc:
        boundary = payload.get("boundary", {})
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "status": payload.get("status"),
            "action_count": counts.get("action_count", 0),
            "expected_count": project.get("review_draft_action_count"),
            "category_counts": counts.get("category_counts", {}),
            "decisions_recorded": boundary.get("decisions_recorded"),
            "source_mutation_allowed": boundary.get("source_mutation_allowed"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "runtime_mutation_allowed": boundary.get("runtime_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get("phase1_runtime_mutation_allowed"),
            "admin_api_integration": boundary.get("admin_api_integration"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    expected_count = project.get("review_draft_action_count")
    action_count = len(draft_log.actions)
    boundary = draft_log.boundary
    if draft_log.status != "draft_only":
        missing.append("review_draft_status:draft_only")
    if action_count != expected_count:
        missing.append(f"review_draft_action_count:{expected_count}")
    if draft_log.counts.action_count != action_count:
        missing.append("review_draft_counts_action_count")
    if draft_log.counts.mutation_action_count != 0:
        missing.append("review_draft_no_mutation_actions")
    if boundary.decisions_recorded:
        missing.append("review_draft_no_decisions_recorded")
    if boundary.source_mutation_allowed:
        missing.append("review_draft_no_source_mutation")
    if boundary.package_mutation_allowed:
        missing.append("review_draft_no_package_mutation")
    if boundary.review_log_mutation_allowed:
        missing.append("review_draft_no_review_log_mutation")
    if boundary.runtime_mutation_allowed:
        missing.append("review_draft_no_runtime_mutation")
    if boundary.phase1_runtime_mutation_allowed:
        missing.append("review_draft_no_phase1_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("review_draft_no_phase2_writeback")
    if boundary.external_api_calls_made:
        missing.append("review_draft_no_external_api_calls")
    if boundary.admin_api_integration:
        missing.append("review_draft_no_admin_api_integration")
    if boundary.raw_payloads_embedded:
        missing.append("review_draft_no_raw_payloads")

    return {
        "ok": not missing,
        "status": draft_log.status,
        "action_count": action_count,
        "expected_count": expected_count,
        "category_counts": draft_log.counts.category_counts,
        "source_ref_count": draft_log.counts.source_ref_count,
        "decisions_recorded": boundary.decisions_recorded,
        "source_mutation_allowed": boundary.source_mutation_allowed,
        "package_mutation_allowed": boundary.package_mutation_allowed,
        "review_log_mutation_allowed": boundary.review_log_mutation_allowed,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase1_runtime_mutation_allowed": boundary.phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "external_api_calls_made": boundary.external_api_calls_made,
        "admin_api_integration": boundary.admin_api_integration,
        "raw_payloads_embedded": boundary.raw_payloads_embedded,
        "missing": missing,
    }


def _check_review_decision_log(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_review_decision_log import PreTripReviewDecisionLog

    ref = project.get("review_decision_log_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "action_count": 0,
            "expected_count": project.get("review_decision_action_count"),
            "accepted_count": 0,
            "corrected_count": 0,
            "rejected_count": 0,
            "runtime_mutation_count": None,
            "package_mutation_count": None,
            "phase1_runtime_mutation_allowed": None,
            "phase2_writeback_allowed": None,
            "admin_api_integration": None,
            "compiles_mission_graph": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "review_decision_log_ref")],
        }

    try:
        decision_log = PreTripReviewDecisionLog.model_validate(payload)
    except Exception as exc:
        boundary = payload.get("boundary", {})
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "action_count": counts.get("action_count", 0),
            "expected_count": project.get("review_decision_action_count"),
            "accepted_count": counts.get("accepted_count", 0),
            "corrected_count": counts.get("corrected_count", 0),
            "rejected_count": counts.get("rejected_count", 0),
            "runtime_mutation_count": counts.get("runtime_mutation_count"),
            "package_mutation_count": counts.get("package_mutation_count"),
            "phase1_runtime_mutation_allowed": boundary.get("phase1_runtime_mutation_allowed"),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "admin_api_integration": boundary.get("admin_api_integration"),
            "compiles_mission_graph": boundary.get("compiles_mission_graph"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    expected_count = project.get("review_decision_action_count")
    action_count = len(decision_log.decisions)
    boundary = decision_log.boundary
    counts = decision_log.counts
    if action_count != expected_count:
        missing.append(f"review_decision_action_count:{expected_count}")
    if counts.action_count != action_count:
        missing.append("review_decision_counts_action_count")
    if counts.accepted_count != 1 or counts.corrected_count != 1 or counts.rejected_count != 1:
        missing.append("review_decision_expected_decision_mix:1_accepted_1_corrected_1_rejected")
    if counts.runtime_mutation_count != 0:
        missing.append("review_decision_no_runtime_mutation_count")
    if counts.package_mutation_count != 0:
        missing.append("review_decision_no_package_mutation_count")
    if counts.raw_payloads_embedded:
        missing.append("review_decision_no_raw_payloads")
    if boundary.source_mutation_allowed:
        missing.append("review_decision_no_source_mutation")
    if boundary.package_mutation_allowed:
        missing.append("review_decision_no_package_mutation")
    if boundary.runtime_mutation_allowed:
        missing.append("review_decision_no_runtime_mutation")
    if boundary.phase1_runtime_mutation_allowed:
        missing.append("review_decision_no_phase1_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("review_decision_no_phase2_writeback")
    if boundary.external_api_calls_made:
        missing.append("review_decision_no_external_api_calls")
    if boundary.admin_api_integration:
        missing.append("review_decision_no_admin_api_integration")
    if boundary.compiles_mission_graph:
        missing.append("review_decision_no_mission_graph_compile")
    if boundary.raw_payloads_embedded:
        missing.append("review_decision_no_raw_payloads_boundary")

    return {
        "ok": not missing,
        "action_count": action_count,
        "expected_count": expected_count,
        "accepted_count": counts.accepted_count,
        "corrected_count": counts.corrected_count,
        "rejected_count": counts.rejected_count,
        "source_ref_count": counts.source_ref_count,
        "runtime_mutation_count": counts.runtime_mutation_count,
        "package_mutation_count": counts.package_mutation_count,
        "source_mutation_allowed": boundary.source_mutation_allowed,
        "package_mutation_allowed": boundary.package_mutation_allowed,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase1_runtime_mutation_allowed": boundary.phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "external_api_calls_made": boundary.external_api_calls_made,
        "admin_api_integration": boundary.admin_api_integration,
        "compiles_mission_graph": boundary.compiles_mission_graph,
        "raw_payloads_embedded": boundary.raw_payloads_embedded,
        "missing": missing,
    }


def _check_external_import_queue(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_external_import_queue import ExternalImportQueue

    ref = project.get("external_import_queue_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "request_count": 0,
            "expected_count": project.get("external_import_request_count"),
            "pending_count": 0,
            "crawler_enabled_count": None,
            "network_call_count": None,
            "observed_fact_count": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "external_import_queue_ref")],
        }

    try:
        queue = ExternalImportQueue.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "status": payload.get("status"),
            "request_count": counts.get("request_count", 0),
            "expected_count": project.get("external_import_request_count"),
            "pending_count": counts.get("pending_count", 0),
            "crawler_enabled_count": counts.get("crawler_enabled_count"),
            "network_call_count": counts.get("network_call_count"),
            "observed_fact_count": counts.get("observed_fact_count"),
            "raw_payloads_embedded": counts.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    counts = queue.counts
    boundary = queue.boundary
    expected_count = project.get("external_import_request_count")
    if len(queue.requests) != expected_count:
        missing.append(f"external_import_request_count:{expected_count}")
    if queue.status != "pending_human_review":
        missing.append("external_import_status:pending_human_review")
    if counts.pending_count != expected_count:
        missing.append(f"external_import_pending_count:{expected_count}")
    if counts.crawler_enabled_count != 0:
        missing.append("external_import_no_crawler_enabled")
    if counts.network_call_count != 0:
        missing.append("external_import_no_network_calls")
    if counts.observed_fact_count != 0:
        missing.append("external_import_no_observed_facts")
    if counts.raw_payloads_embedded:
        missing.append("external_import_no_raw_payloads")
    if not boundary.no_network:
        missing.append("external_import_no_network_boundary")
    if not boundary.no_crawler:
        missing.append("external_import_no_crawler_boundary")
    if boundary.fetches_remote_content:
        missing.append("external_import_no_fetch")
    if boundary.produces_observed_facts:
        missing.append("external_import_no_observed_fact_output")
    if boundary.produces_derived_measurements:
        missing.append("external_import_no_derived_measurement_output")

    return {
        "ok": not missing,
        "status": queue.status,
        "request_count": len(queue.requests),
        "expected_count": expected_count,
        "pending_count": counts.pending_count,
        "crawler_enabled_count": counts.crawler_enabled_count,
        "network_call_count": counts.network_call_count,
        "observed_fact_count": counts.observed_fact_count,
        "raw_payloads_embedded": counts.raw_payloads_embedded,
        "no_network": boundary.no_network,
        "no_crawler": boundary.no_crawler,
        "fetches_remote_content": boundary.fetches_remote_content,
        "produces_observed_facts": boundary.produces_observed_facts,
        "produces_derived_measurements": boundary.produces_derived_measurements,
        "source_ids": [request.source_id for request in queue.requests],
        "missing": missing,
    }


def _check_expert_contribution_log(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_expert_contribution import ExpertContributionLog

    ref = project.get("expert_contribution_log_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "contribution_count": 0,
            "expected_count": project.get("expert_contribution_count"),
            "candidate_set_edit_count": 0,
            "external_import_edit_count": 0,
            "memory_seed_candidate_count": 0,
            "brain_writeback_count": None,
            "missing": [str(ref or "expert_contribution_log_ref")],
        }

    try:
        contribution_log = ExpertContributionLog.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "status": payload.get("status"),
            "contribution_count": counts.get("contribution_count", 0),
            "expected_count": project.get("expert_contribution_count"),
            "candidate_set_edit_count": counts.get("candidate_set_edit_count", 0),
            "external_import_edit_count": counts.get("external_import_edit_count", 0),
            "memory_seed_candidate_count": counts.get("memory_seed_candidate_count", 0),
            "brain_writeback_count": counts.get("brain_writeback_count"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    counts = contribution_log.counts
    boundary = contribution_log.boundary
    expected_count = project.get("expert_contribution_count")
    expected_memory_seed_count = project.get(
        "expert_contribution_memory_seed_candidate_count"
    )
    if len(contribution_log.records) != expected_count:
        missing.append(f"expert_contribution_count:{expected_count}")
    if counts.contribution_count != expected_count:
        missing.append(f"expert_contribution_counts:{expected_count}")
    if counts.memory_seed_candidate_count != expected_memory_seed_count:
        missing.append(
            f"expert_contribution_memory_seed_count:{expected_memory_seed_count}"
        )
    if counts.candidate_set_edit_count < 1:
        missing.append("expert_contribution_candidate_set_edits_present")
    if counts.external_import_edit_count < 1:
        missing.append("expert_contribution_external_import_edits_present")
    if counts.brain_writeback_count != 0:
        missing.append("expert_contribution_no_brain_writeback")
    if counts.raw_payload_count != 0:
        missing.append("expert_contribution_no_raw_payload_count")
    if contribution_log.status != "candidate_memory_seed_only":
        missing.append("expert_contribution_status:candidate_memory_seed_only")
    if not boundary.candidate_set_edit_intent_only:
        missing.append("expert_contribution_candidate_set_intent_only")
    if not boundary.external_import_edit_intent_only:
        missing.append("expert_contribution_external_import_intent_only")
    if not boundary.requires_human_review_before_apply:
        missing.append("expert_contribution_requires_human_review")
    if not boundary.memory_seed_candidate_only:
        missing.append("expert_contribution_memory_seed_candidate_only")
    if boundary.brain_writeback_allowed:
        missing.append("expert_contribution_no_brain_writeback_boundary")
    if boundary.package_mutation_allowed:
        missing.append("expert_contribution_no_package_mutation")
    if boundary.mission_graph_mutation_allowed:
        missing.append("expert_contribution_no_mission_graph_mutation")
    if boundary.runtime_mutation_allowed:
        missing.append("expert_contribution_no_runtime_mutation")
    if boundary.phase1_runtime_mutation_allowed:
        missing.append("expert_contribution_no_phase1_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("expert_contribution_no_phase2_writeback")
    if boundary.external_api_calls_made:
        missing.append("expert_contribution_no_external_api_calls")
    if boundary.raw_payloads_embedded:
        missing.append("expert_contribution_no_raw_payloads")

    return {
        "ok": not missing,
        "status": contribution_log.status,
        "contribution_count": len(contribution_log.records),
        "expected_count": expected_count,
        "candidate_set_edit_count": counts.candidate_set_edit_count,
        "external_import_edit_count": counts.external_import_edit_count,
        "memory_seed_candidate_count": counts.memory_seed_candidate_count,
        "expected_memory_seed_candidate_count": expected_memory_seed_count,
        "brain_writeback_count": counts.brain_writeback_count,
        "raw_payload_count": counts.raw_payload_count,
        "candidate_set_edit_intent_only": boundary.candidate_set_edit_intent_only,
        "external_import_edit_intent_only": boundary.external_import_edit_intent_only,
        "requires_human_review_before_apply": boundary.requires_human_review_before_apply,
        "memory_seed_candidate_only": boundary.memory_seed_candidate_only,
        "brain_writeback_allowed": boundary.brain_writeback_allowed,
        "package_mutation_allowed": boundary.package_mutation_allowed,
        "mission_graph_mutation_allowed": boundary.mission_graph_mutation_allowed,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase1_runtime_mutation_allowed": boundary.phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "external_api_calls_made": boundary.external_api_calls_made,
        "raw_payloads_embedded": boundary.raw_payloads_embedded,
        "target_kinds": [record.target_kind.value for record in contribution_log.records],
        "operations": [record.operation.value for record in contribution_log.records],
        "missing": missing,
    }


def _check_route_note_candidates(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_route_note_candidates import RouteNoteCandidateSet

    ref = project.get("route_note_candidates_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "note_candidate_count": 0,
            "expected_count": project.get("route_note_candidate_count"),
            "potential_ln_signal_count": 0,
            "missing": [str(ref or "route_note_candidates_ref")],
        }

    try:
        notes = RouteNoteCandidateSet.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "note_candidate_count": counts.get("note_candidate_count", 0),
            "expected_count": project.get("route_note_candidate_count"),
            "potential_ln_signal_count": counts.get("potential_ln_signal_count", 0),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    counts = notes.counts
    boundary = notes.boundary
    expected_count = project.get("route_note_candidate_count")
    expected_ln_count = project.get("route_note_potential_ln_signal_count")
    if counts.note_candidate_count != expected_count:
        missing.append(f"route_note_candidate_count:{expected_count}")
    if counts.potential_ln_signal_count != expected_ln_count:
        missing.append(f"route_note_potential_ln_signal_count:{expected_ln_count}")
    if counts.observed_fact_count != 0:
        missing.append("route_note_no_observed_facts")
    if counts.raw_payload_count != 0:
        missing.append("route_note_no_raw_payload_count")
    if not boundary.candidate_only:
        missing.append("route_note_candidate_only")
    if not boundary.scout_interpretation_only:
        missing.append("route_note_model_interpretation_only")
    if not boundary.requires_human_review_before_ln_upgrade:
        missing.append("route_note_requires_human_review_before_ln_upgrade")
    if boundary.observed_fact_allowed:
        missing.append("route_note_no_observed_fact_allowed")
    if boundary.derived_measurement_allowed:
        missing.append("route_note_no_derived_measurement_allowed")
    if boundary.raw_gpx_embedded:
        missing.append("route_note_no_raw_gpx")
    if boundary.runtime_mutation_allowed:
        missing.append("route_note_no_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("route_note_no_phase2_writeback")

    return {
        "ok": not missing,
        "status": notes.status,
        "waypoint_count": counts.waypoint_count,
        "note_candidate_count": counts.note_candidate_count,
        "expected_count": expected_count,
        "hazard_hint_count": counts.hazard_hint_count,
        "route_condition_hint_count": counts.route_condition_hint_count,
        "camp_or_water_hint_count": counts.camp_or_water_hint_count,
        "landmark_hint_count": counts.landmark_hint_count,
        "potential_ln_signal_count": counts.potential_ln_signal_count,
        "expected_potential_ln_signal_count": expected_ln_count,
        "observed_fact_count": counts.observed_fact_count,
        "raw_payload_count": counts.raw_payload_count,
        "candidate_only": boundary.candidate_only,
        "scout_interpretation_only": boundary.scout_interpretation_only,
        "requires_human_review_before_ln_upgrade": (
            boundary.requires_human_review_before_ln_upgrade
        ),
        "observed_fact_allowed": boundary.observed_fact_allowed,
        "derived_measurement_allowed": boundary.derived_measurement_allowed,
        "raw_gpx_embedded": boundary.raw_gpx_embedded,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "missing": missing,
    }


def _check_route_note_ln_proposals(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_route_note_ln_proposals import RouteNoteLnProposalSet

    ref = project.get("route_note_ln_proposals_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "proposal_count": 0,
            "expected_count": project.get("route_note_ln_proposal_count"),
            "missing": [str(ref or "route_note_ln_proposals_ref")],
        }

    try:
        proposal_set = RouteNoteLnProposalSet.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "proposal_count": counts.get("proposal_count", 0),
            "expected_count": project.get("route_note_ln_proposal_count"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    counts = proposal_set.counts
    boundary = proposal_set.boundary
    expected_count = project.get("route_note_ln_proposal_count")
    expected_hint_count = project.get("route_note_ln_hint_coverage_proposal_count")
    expected_warning_count = project.get("route_note_ln_warning_coverage_proposal_count")
    if counts.proposal_count != expected_count:
        missing.append(f"route_note_ln_proposal_count:{expected_count}")
    if counts.hint_coverage_proposal_count != expected_hint_count:
        missing.append(
            f"route_note_ln_hint_coverage_proposal_count:{expected_hint_count}"
        )
    if counts.warning_coverage_proposal_count != expected_warning_count:
        missing.append(
            f"route_note_ln_warning_coverage_proposal_count:{expected_warning_count}"
        )
    if counts.human_review_required_count != counts.proposal_count:
        missing.append("route_note_ln_all_require_human_review")
    if counts.observed_fact_count != 0:
        missing.append("route_note_ln_no_observed_facts")
    if counts.derived_measurement_count != 0:
        missing.append("route_note_ln_no_derived_measurements")
    if counts.runtime_mutation_count != 0:
        missing.append("route_note_ln_no_runtime_mutation_count")
    if counts.phase1_runtime_mutation_count != 0:
        missing.append("route_note_ln_no_phase1_runtime_mutation_count")
    if counts.phase2_writeback_count != 0:
        missing.append("route_note_ln_no_phase2_writeback_count")
    if counts.raw_gpx_payload_count != 0:
        missing.append("route_note_ln_no_raw_gpx_payload")
    if not boundary.candidate_only:
        missing.append("route_note_ln_candidate_only")
    if not boundary.human_review_required_before_use:
        missing.append("route_note_ln_requires_human_review")
    if boundary.observed_fact_allowed:
        missing.append("route_note_ln_no_observed_fact_allowed")
    if boundary.derived_measurement_allowed:
        missing.append("route_note_ln_no_derived_measurement_allowed")
    if boundary.package_mutation_allowed:
        missing.append("route_note_ln_no_package_mutation")
    if boundary.mission_graph_mutation_allowed:
        missing.append("route_note_ln_no_mission_graph_mutation")
    if boundary.runtime_mutation_allowed:
        missing.append("route_note_ln_no_runtime_mutation")
    if boundary.phase1_runtime_mutation_allowed:
        missing.append("route_note_ln_no_phase1_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("route_note_ln_no_phase2_writeback")
    if boundary.raw_gpx_embedded:
        missing.append("route_note_ln_no_raw_gpx")
    if boundary.crawler_or_network_source_allowed:
        missing.append("route_note_ln_no_crawler_or_network")

    return {
        "ok": not missing,
        "status": proposal_set.status,
        "proposal_count": counts.proposal_count,
        "expected_count": expected_count,
        "hint_coverage_proposal_count": counts.hint_coverage_proposal_count,
        "expected_hint_coverage_proposal_count": expected_hint_count,
        "warning_coverage_proposal_count": counts.warning_coverage_proposal_count,
        "expected_warning_coverage_proposal_count": expected_warning_count,
        "human_review_required_count": counts.human_review_required_count,
        "observed_fact_count": counts.observed_fact_count,
        "derived_measurement_count": counts.derived_measurement_count,
        "runtime_mutation_count": counts.runtime_mutation_count,
        "phase1_runtime_mutation_count": counts.phase1_runtime_mutation_count,
        "phase2_writeback_count": counts.phase2_writeback_count,
        "raw_gpx_payload_count": counts.raw_gpx_payload_count,
        "candidate_only": boundary.candidate_only,
        "human_review_required_before_use": boundary.human_review_required_before_use,
        "observed_fact_allowed": boundary.observed_fact_allowed,
        "derived_measurement_allowed": boundary.derived_measurement_allowed,
        "package_mutation_allowed": boundary.package_mutation_allowed,
        "mission_graph_mutation_allowed": boundary.mission_graph_mutation_allowed,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase1_runtime_mutation_allowed": boundary.phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "raw_gpx_embedded": boundary.raw_gpx_embedded,
        "crawler_or_network_source_allowed": (
            boundary.crawler_or_network_source_allowed
        ),
        "proposal_kinds": sorted(
            {proposal.proposal_kind for proposal in proposal_set.proposals}
        ),
        "missing": missing,
    }


def _check_route_note_review_options(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_route_note_review_options import (
        ALLOWED_ADMIN_DISPOSITIONS,
        RouteNoteReviewOptions,
    )

    ref = project.get("route_note_review_options_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "review_option_count": 0,
            "expected_count": project.get("route_note_review_option_count"),
            "missing": [str(ref or "route_note_review_options_ref")],
        }

    try:
        options = RouteNoteReviewOptions.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        return {
            "ok": False,
            "review_option_count": counts.get("review_option_count", 0),
            "expected_count": project.get("route_note_review_option_count"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    counts = options.counts
    boundary = options.boundary
    expected_count = project.get("route_note_review_option_count")
    if counts.review_option_count != expected_count:
        missing.append(f"route_note_review_option_count:{expected_count}")
    if counts.source_proposal_count != project.get("route_note_ln_proposal_count"):
        missing.append("route_note_review_options_source_proposal_count")
    if counts.candidate_only_count != counts.review_option_count:
        missing.append("route_note_review_options_all_candidate_only")
    if counts.draft_only_count != counts.review_option_count:
        missing.append("route_note_review_options_all_draft_only")
    if counts.decision_recorded_count != 0:
        missing.append("route_note_review_options_no_decisions")
    if counts.runtime_mutation_count != 0:
        missing.append("route_note_review_options_no_runtime_mutation_count")
    if counts.phase1_runtime_mutation_count != 0:
        missing.append("route_note_review_options_no_phase1_runtime_mutation_count")
    if counts.phase2_writeback_count != 0:
        missing.append("route_note_review_options_no_phase2_writeback_count")
    if counts.raw_gpx_payload_count != 0:
        missing.append("route_note_review_options_no_raw_gpx_payload")
    if not boundary.candidate_only:
        missing.append("route_note_review_options_candidate_only")
    if not boundary.draft_only:
        missing.append("route_note_review_options_draft_only")
    if not boundary.review_options_only:
        missing.append("route_note_review_options_only")
    if boundary.decision_recording_allowed:
        missing.append("route_note_review_options_no_decision_recording")
    if boundary.package_mutation_allowed:
        missing.append("route_note_review_options_no_package_mutation")
    if boundary.mission_graph_mutation_allowed:
        missing.append("route_note_review_options_no_mission_graph_mutation")
    if boundary.runtime_mutation_allowed:
        missing.append("route_note_review_options_no_runtime_mutation")
    if boundary.phase1_runtime_mutation_allowed:
        missing.append("route_note_review_options_no_phase1_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("route_note_review_options_no_phase2_writeback")
    if boundary.raw_gpx_embedded:
        missing.append("route_note_review_options_no_raw_gpx")
    if boundary.crawler_or_network_source_allowed:
        missing.append("route_note_review_options_no_crawler_or_network")
    disposition_sets = {
        tuple(option.allowed_admin_dispositions)
        for option in options.options
    }
    if disposition_sets != {ALLOWED_ADMIN_DISPOSITIONS}:
        missing.append("route_note_review_options_allowed_dispositions")

    return {
        "ok": not missing,
        "status": options.status,
        "review_option_count": counts.review_option_count,
        "expected_count": expected_count,
        "source_proposal_count": counts.source_proposal_count,
        "candidate_only_count": counts.candidate_only_count,
        "draft_only_count": counts.draft_only_count,
        "decision_recorded_count": counts.decision_recorded_count,
        "runtime_mutation_count": counts.runtime_mutation_count,
        "phase1_runtime_mutation_count": counts.phase1_runtime_mutation_count,
        "phase2_writeback_count": counts.phase2_writeback_count,
        "raw_gpx_payload_count": counts.raw_gpx_payload_count,
        "candidate_only": boundary.candidate_only,
        "draft_only": boundary.draft_only,
        "review_options_only": boundary.review_options_only,
        "decision_recording_allowed": boundary.decision_recording_allowed,
        "package_mutation_allowed": boundary.package_mutation_allowed,
        "mission_graph_mutation_allowed": boundary.mission_graph_mutation_allowed,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase1_runtime_mutation_allowed": boundary.phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "raw_gpx_embedded": boundary.raw_gpx_embedded,
        "crawler_or_network_source_allowed": (
            boundary.crawler_or_network_source_allowed
        ),
        "allowed_admin_dispositions": list(ALLOWED_ADMIN_DISPOSITIONS),
        "missing": missing,
    }


def _check_review_decision_apply_plan(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_review_decision_apply import PreTripReviewDecisionApplyPlan

    ref = project.get("review_decision_apply_plan_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "decision_count": 0,
            "expected_count": project.get("review_decision_action_count"),
            "accepted_count": 0,
            "corrected_count": 0,
            "rejected_count": 0,
            "package_candidate_apply_count": None,
            "runtime_mutation_count": None,
            "would_apply_only": None,
            "source_mutation_allowed": None,
            "package_mutation_allowed": None,
            "runtime_mutation_allowed": None,
            "phase1_runtime_mutation_allowed": None,
            "phase2_writeback_allowed": None,
            "compiles_mission_graph": None,
            "raw_payloads_embedded": None,
            "missing": [str(ref or "review_decision_apply_plan_ref")],
        }

    try:
        plan = PreTripReviewDecisionApplyPlan.model_validate(payload)
    except Exception as exc:
        counts = payload.get("counts", {})
        boundary = payload.get("boundary", {})
        return {
            "ok": False,
            "decision_count": counts.get("decision_count", 0),
            "expected_count": project.get("review_decision_action_count"),
            "accepted_count": counts.get("accepted", 0),
            "corrected_count": counts.get("corrected", 0),
            "rejected_count": counts.get("rejected", 0),
            "package_candidate_apply_count": counts.get("package_candidate_apply_count"),
            "runtime_mutation_count": counts.get("runtime_mutation_count"),
            "would_apply_only": boundary.get("would_apply_only"),
            "source_mutation_allowed": boundary.get("source_mutation_allowed"),
            "package_mutation_allowed": boundary.get("package_mutation_allowed"),
            "runtime_mutation_allowed": boundary.get("runtime_mutation_allowed"),
            "phase1_runtime_mutation_allowed": boundary.get("phase1_runtime_mutation_allowed"),
            "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            "compiles_mission_graph": boundary.get("compiles_mission_graph"),
            "raw_payloads_embedded": boundary.get("raw_payloads_embedded"),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    counts = plan.counts
    boundary = plan.boundary
    expected_count = project.get("review_decision_action_count")
    if len(plan.decisions) != expected_count:
        missing.append(f"review_decision_apply_count:{expected_count}")
    if counts.decision_count != len(plan.decisions):
        missing.append("review_decision_apply_counts_decision_count")
    if counts.accepted != 1 or counts.corrected != 1 or counts.rejected != 1:
        missing.append("review_decision_apply_expected_decision_mix:1_accepted_1_corrected_1_rejected")
    if counts.package_candidate_apply_count != 0:
        missing.append("review_decision_apply_no_package_candidate_apply")
    if counts.runtime_mutation_count != 0:
        missing.append("review_decision_apply_no_runtime_mutation")
    if not boundary.would_apply_only:
        missing.append("review_decision_apply_would_apply_only")
    if boundary.source_mutation_allowed:
        missing.append("review_decision_apply_no_source_mutation")
    if boundary.package_mutation_allowed:
        missing.append("review_decision_apply_no_package_mutation")
    if boundary.runtime_mutation_allowed:
        missing.append("review_decision_apply_no_runtime_mutation_boundary")
    if boundary.phase1_runtime_mutation_allowed:
        missing.append("review_decision_apply_no_phase1_runtime_mutation")
    if boundary.phase2_writeback_allowed:
        missing.append("review_decision_apply_no_phase2_writeback")
    if boundary.compiles_mission_graph:
        missing.append("review_decision_apply_no_mission_graph_compile")
    if boundary.raw_payloads_embedded:
        missing.append("review_decision_apply_no_raw_payloads")

    return {
        "ok": not missing,
        "decision_count": len(plan.decisions),
        "expected_count": expected_count,
        "accepted_count": counts.accepted,
        "corrected_count": counts.corrected,
        "rejected_count": counts.rejected,
        "source_ref_count": counts.source_ref_count,
        "package_candidate_apply_count": counts.package_candidate_apply_count,
        "runtime_mutation_count": counts.runtime_mutation_count,
        "would_apply_only": boundary.would_apply_only,
        "source_mutation_allowed": boundary.source_mutation_allowed,
        "package_mutation_allowed": boundary.package_mutation_allowed,
        "runtime_mutation_allowed": boundary.runtime_mutation_allowed,
        "phase1_runtime_mutation_allowed": boundary.phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": boundary.phase2_writeback_allowed,
        "compiles_mission_graph": boundary.compiles_mission_graph,
        "raw_payloads_embedded": boundary.raw_payloads_embedded,
        "missing": missing,
    }


def _check_admin_workspace_persistence_contract(root: Path) -> dict[str, Any]:
    admin_path = root / "admin_api.py"
    store_path = root / "pretrip_review_decision_store.py"
    apply_store_path = root / "pretrip_review_decision_apply_store.py"
    workspace_project_path = root / "pretrip_workspace_project.py"
    fixture_path = root / DEFAULT_PROJECT_PATH
    missing: list[str] = []

    admin_text = admin_path.read_text(encoding="utf-8") if admin_path.exists() else ""
    store_text = store_path.read_text(encoding="utf-8") if store_path.exists() else ""
    apply_store_text = (
        apply_store_path.read_text(encoding="utf-8") if apply_store_path.exists() else ""
    )
    workspace_project_text = (
        workspace_project_path.read_text(encoding="utf-8")
        if workspace_project_path.exists()
        else ""
    )
    if not admin_text:
        missing.append("admin_workspace_persistence_contract:admin_api.py")
    if not store_text:
        missing.append("admin_workspace_persistence_contract:pretrip_review_decision_store.py")
    if not apply_store_text:
        missing.append(
            "admin_workspace_persistence_contract:pretrip_review_decision_apply_store.py"
        )
    if not workspace_project_text:
        missing.append("admin_workspace_persistence_contract:pretrip_workspace_project.py")

    admin_contract = _inspect_admin_api_workspace_contract(admin_text) if admin_text else {}
    preview_default = admin_contract.get("persist_to_workspace_default") is False
    requires_workspace_root = admin_contract.get("pretrip_workspace_root_default") is None
    if not admin_contract.get("has_persist_to_workspace_field"):
        missing.append("admin_api_persist_to_workspace_field")
    if not preview_default:
        missing.append("admin_api_persist_to_workspace_default_false")
    if not admin_contract.get("has_pretrip_workspace_root_param"):
        missing.append("admin_api_pretrip_workspace_root_param")
    if not requires_workspace_root:
        missing.append("admin_api_pretrip_workspace_root_default_none")
    if "persist_to_workspace requires create_admin_app(" not in admin_text:
        missing.append("admin_api_persistence_requires_injected_workspace_root")
    if "append_review_decision(log_path, record)" not in admin_text:
        missing.append("admin_api_append_only_store_call")
    if "write_review_decision_apply_plan_for_workspace(project_root)" not in admin_text:
        missing.append("admin_api_apply_plan_workspace_store_call")
    admin_project_view_workspace_overlay = (
        "build_pretrip_admin_view(project_id, project_root=project_root)" in admin_text
        and "_pretrip_workspace_project_root(" in admin_text
    )
    if not admin_project_view_workspace_overlay:
        missing.append("admin_api_project_view_workspace_overlay")
    if "copy_pretrip_project_workspace" not in workspace_project_text:
        missing.append("workspace_project_copy_helper")
    duplicate_candidate_ref_guard = (
        "_reject_duplicate_candidate_refs" in store_text
        and "duplicate candidate_ref" in store_text
    )
    if not duplicate_candidate_ref_guard:
        missing.append("review_decision_store_duplicate_candidate_ref_guard")

    repo_fixture_action_count = None
    if fixture_path.exists():
        project = _load_json(fixture_path)
        project_root = fixture_path.parent
        review_log = _optional_json(project_root, project.get("review_decision_log_ref"))
        if isinstance(review_log, dict):
            counts = review_log.get("counts", {})
            repo_fixture_action_count = counts.get("action_count")
        else:
            missing.append("admin_workspace_repo_fixture_review_decision_log")
    else:
        missing.append(str(fixture_path.relative_to(root)))

    if repo_fixture_action_count != 3:
        missing.append("admin_workspace_repo_fixture_action_count:3")

    forbidden_fragments = (
        "/safety",
        "Phase1IncidentBridge",
        "requests",
        "httpx",
        "phase2_brain",
        "Phase2Brain",
        "phase2_writeback_policy",
        "write_observed_fact",
    )
    source_text_by_ref = {
        "admin_api.py": admin_text,
        "pretrip_review_decision_store.py": store_text,
        "pretrip_review_decision_apply_store.py": apply_store_text,
        "pretrip_workspace_project.py": workspace_project_text,
    }
    forbidden_source_fragments: list[dict[str, str]] = []
    for ref, text in source_text_by_ref.items():
        for fragment in forbidden_fragments:
            if fragment in text:
                forbidden_source_fragments.append({"path": ref, "fragment": fragment})
    missing.extend(
        f"admin_workspace_forbidden_fragment:{item['path']}:{item['fragment']}"
        for item in forbidden_source_fragments
    )

    phase1_runtime_mutation_allowed = False
    phase2_writeback_allowed = False
    external_api_calls_made = False
    return {
        "ok": not missing,
        "preview_default": preview_default,
        "requires_workspace_root": requires_workspace_root,
        "repo_fixture_action_count": repo_fixture_action_count,
        "admin_project_view_workspace_overlay": admin_project_view_workspace_overlay,
        "phase1_runtime_mutation_allowed": phase1_runtime_mutation_allowed,
        "phase2_writeback_allowed": phase2_writeback_allowed,
        "external_api_calls_made": external_api_calls_made,
        "admin_api_contract": admin_contract,
        "duplicate_candidate_ref_guard": duplicate_candidate_ref_guard,
        "forbidden_source_fragment_count": len(forbidden_source_fragments),
        "forbidden_source_fragments": forbidden_source_fragments,
        "missing": missing,
    }


def _check_admin_workspace_project_creation_contract(root: Path) -> dict[str, Any]:
    admin_path = root / "admin_api.py"
    store_path = root / "pretrip_review_decision_store.py"
    apply_store_path = root / "pretrip_review_decision_apply_store.py"
    workspace_project_path = root / "pretrip_workspace_project.py"
    missing: list[str] = []

    admin_text = admin_path.read_text(encoding="utf-8") if admin_path.exists() else ""
    store_text = store_path.read_text(encoding="utf-8") if store_path.exists() else ""
    apply_store_text = (
        apply_store_path.read_text(encoding="utf-8") if apply_store_path.exists() else ""
    )
    workspace_project_text = (
        workspace_project_path.read_text(encoding="utf-8")
        if workspace_project_path.exists()
        else ""
    )
    if not admin_text:
        missing.append("admin_workspace_project_creation_contract:admin_api.py")
    if not store_text:
        missing.append(
            "admin_workspace_project_creation_contract:pretrip_review_decision_store.py"
        )
    if not apply_store_text:
        missing.append(
            "admin_workspace_project_creation_contract:"
            "pretrip_review_decision_apply_store.py"
        )
    if not workspace_project_text:
        missing.append(
            "admin_workspace_project_creation_contract:pretrip_workspace_project.py"
        )

    helper_tokens = {
        "RAW_SOURCE_SUFFIXES": "workspace_project_RAW_SOURCE_SUFFIXES",
        "ALLOWED_METADATA_SUFFIXES": "workspace_project_ALLOWED_METADATA_SUFFIXES",
        "copy_pretrip_project_workspace": "workspace_project_copy_pretrip_project_workspace",
        "raw source files are not allowed": "workspace_project_rejects_raw_source_files",
        "only JSON and GeoJSON metadata fixtures": (
            "workspace_project_metadata_only_json_geojson"
        ),
        "phase1_runtime_mutation_allowed": (
            "workspace_project_phase1_runtime_mutation_boundary"
        ),
        "phase2_writeback_allowed": "workspace_project_phase2_writeback_boundary",
    }
    helper_missing_tokens = [
        missing_name
        for token, missing_name in helper_tokens.items()
        if token not in workspace_project_text
    ]
    missing.extend(helper_missing_tokens)

    admin_route_tokens = (
        "/pretrip/projects/{project_id}/workspace",
        "/pretrip/projects/{project_id}/workspace-copy",
        "/pretrip/projects/{project_id}/local-workspace",
    )
    admin_workspace_route_present = any(
        token in admin_text for token in admin_route_tokens
    )
    admin_uses_workspace_copy_helper = "copy_pretrip_project_workspace" in admin_text
    admin_missing_tokens: list[str] = []
    if not admin_workspace_route_present:
        admin_missing_tokens.append(
            "admin_api_workspace_creation_route:"
            "/pretrip/projects/{project_id}/workspace"
        )
    if not admin_uses_workspace_copy_helper:
        admin_missing_tokens.append(
            "admin_api_uses_copy_pretrip_project_workspace"
        )

    # The admin endpoint is the next integration slice. If it is partially present,
    # fail loudly; if it is absent, report exact token names without making this
    # metadata-helper release check block the current fixture-backed release.
    admin_endpoint_partially_present = (
        admin_workspace_route_present != admin_uses_workspace_copy_helper
    )
    if admin_endpoint_partially_present:
        missing.extend(admin_missing_tokens)

    forbidden_fragments = (
        "/safety",
        "Phase1IncidentBridge",
        "requests",
        "httpx",
        "urllib",
        "aiohttp",
        "phase2_brain",
        "Phase2Brain",
        "phase2_writeback_policy",
        "write_observed_fact",
    )
    source_text_by_ref = {
        "admin_api.py": admin_text,
        "pretrip_review_decision_store.py": store_text,
        "pretrip_review_decision_apply_store.py": apply_store_text,
        "pretrip_workspace_project.py": workspace_project_text,
    }
    forbidden_source_fragments: list[dict[str, str]] = []
    for ref, text in source_text_by_ref.items():
        for fragment in forbidden_fragments:
            if fragment in text:
                forbidden_source_fragments.append({"path": ref, "fragment": fragment})
    missing.extend(
        f"admin_workspace_project_creation_forbidden_fragment:"
        f"{item['path']}:{item['fragment']}"
        for item in forbidden_source_fragments
    )

    admin_endpoint_present = (
        admin_workspace_route_present and admin_uses_workspace_copy_helper
    )
    return {
        "ok": not missing,
        "helper_has_raw_source_suffixes": (
            "RAW_SOURCE_SUFFIXES" in workspace_project_text
        ),
        "helper_has_copy_pretrip_project_workspace": (
            "copy_pretrip_project_workspace" in workspace_project_text
        ),
        "helper_rejects_raw_sources": (
            "raw source files are not allowed" in workspace_project_text
        ),
        "helper_metadata_only_suffixes": (
            "ALLOWED_METADATA_SUFFIXES" in workspace_project_text
        ),
        "admin_endpoint_present": admin_endpoint_present,
        "admin_workspace_route_present": admin_workspace_route_present,
        "admin_uses_workspace_copy_helper": admin_uses_workspace_copy_helper,
        "admin_missing_tokens": admin_missing_tokens,
        "admin_endpoint_partially_present": admin_endpoint_partially_present,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "external_api_calls_made": False,
        "repo_fixture_mutation_allowed": False,
        "forbidden_source_fragment_count": len(forbidden_source_fragments),
        "forbidden_source_fragments": forbidden_source_fragments,
        "missing": missing,
    }


def _check_admin_ui_local_workspace_write_controls(root: Path) -> dict[str, Any]:
    page_ref = "docs/admin/phase4-pretrip-planning.html"
    page_path = root / page_ref
    page_text = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
    missing: list[str] = []
    if not page_text:
        return {
            "ok": False,
            "page_present": False,
            "write_slice_landed": False,
            "expected_route_tokens_present": False,
            "expected_function_tokens_present": False,
            "expected_persistence_tokens_present": False,
            "forbidden_token_count": 0,
            "forbidden_tokens": [],
            "missing_route_tokens": [],
            "missing_function_tokens": [],
            "missing_persistence_tokens": [],
            "missing_reject_tokens": [],
            "missing_correct_tokens": [],
            "tolerated_absent_until_ui_slice": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "crawler_or_external_import_write_allowed": False,
            "repo_fixture_mutation_allowed": False,
            "missing": [page_ref],
        }

    expected_route_tokens = (
        "/admin/pretrip/projects/${PROJECT_ID}/workspace",
        "/admin/pretrip/projects/${PROJECT_ID}/review-decisions",
        "/admin/pretrip/projects/${PROJECT_ID}/review-decision-apply-plan",
    )
    expected_function_token_groups = {
        "create_local_workspace": (
            "createLocalWorkspace",
        ),
        "persist_review_decision": (
            "persistReviewDecision",
            "acceptSelectedReviewToWorkspace",
        ),
        "reject_review_decision": (
            "rejectSelectedReviewToWorkspace",
        ),
        "correct_review_decision": (
            "correctSelectedReviewToWorkspace",
        ),
        "regenerate_apply_plan": (
            "regenerateReviewDecisionApplyPlan",
            "refreshWorkspaceApplyPlan",
        ),
    }
    expected_persistence_tokens = (
        "persist_to_workspace",
    )
    expected_reject_tokens = (
        "workspaceRejectReview",
        'decision: "rejected"',
    )
    expected_correct_tokens = (
        "workspaceCorrectReview",
        'decision: "corrected"',
        "correction: {",
    )
    missing_route_tokens = [
        token for token in expected_route_tokens if token not in page_text
    ]
    missing_function_tokens = [
        name
        for name, token_options in expected_function_token_groups.items()
        if not any(token in page_text for token in token_options)
    ]
    missing_persistence_tokens = [
        token for token in expected_persistence_tokens if token not in page_text
    ]
    missing_reject_tokens = [
        token for token in expected_reject_tokens if token not in page_text
    ]
    missing_correct_tokens = [
        token for token in expected_correct_tokens if token not in page_text
    ]

    route_tokens_present = not missing_route_tokens
    function_tokens_present = not missing_function_tokens
    persistence_tokens_present = not missing_persistence_tokens
    reject_tokens_present = not missing_reject_tokens
    correct_tokens_present = not missing_correct_tokens
    landed_token_count = sum(
        1
        for token in (
            *expected_route_tokens,
            *(
                token
                for token_options in expected_function_token_groups.values()
                for token in token_options
            ),
            *expected_persistence_tokens,
            *expected_reject_tokens,
            *expected_correct_tokens,
        )
        if token in page_text
    )
    write_slice_landed = (
        route_tokens_present
        and function_tokens_present
        and persistence_tokens_present
        and reject_tokens_present
        and correct_tokens_present
    )
    partial_write_slice = landed_token_count > 0 and not write_slice_landed
    if partial_write_slice:
        missing.extend(
            f"admin_ui_write_control_missing_route:{token}"
            for token in missing_route_tokens
        )
        missing.extend(
            f"admin_ui_write_control_missing_function:{token}"
            for token in missing_function_tokens
        )
        missing.extend(
            f"admin_ui_write_control_missing_persistence:{token}"
            for token in missing_persistence_tokens
        )
        missing.extend(
            f"admin_ui_write_control_missing_reject:{token}"
            for token in missing_reject_tokens
        )
        missing.extend(
            f"admin_ui_write_control_missing_correct:{token}"
            for token in missing_correct_tokens
        )

    forbidden_patterns = {
        "fetch_to_safety": ('fetch("' + "/safety", "fetch('" + "/safety", "fetch(`/safety"),
        "absolute_fetch_to_safety": (
            'fetch("' + "${apiBase()}/safety",
            "fetch('" + "${apiBase()}/safety",
            "fetch(`${apiBase()}/safety",
        ),
        "unsafe_put_method": ('method: "PUT"', "method: 'PUT'", "method:\"PUT\""),
        "unsafe_patch_method": (
            'method: "PATCH"',
            "method: 'PATCH'",
            "method:\"PATCH\"",
        ),
        "unsafe_delete_method": (
            'method: "DELETE"',
            "method: 'DELETE'",
            "method:\"DELETE\"",
        ),
        "crawler_write": (
            "startCrawler",
            "runCrawler",
            "crawler_enabled: true",
            "crawlerEnabled = true",
        ),
        "external_import_write": (
            "persistExternalImport",
            "writeExternalImport",
            "fetchExternalImport",
            "/external-imports/write",
        ),
        "phase2_writeback": (
            "writeObservedFact",
            "phase2_writeback",
            "Phase2Brain",
        ),
    }
    forbidden_tokens: list[dict[str, str]] = []
    for category, patterns in forbidden_patterns.items():
        for pattern in patterns:
            if pattern in page_text:
                forbidden_tokens.append({"category": category, "token": pattern})
    missing.extend(
        f"admin_ui_write_control_forbidden:{item['category']}:{item['token']}"
        for item in forbidden_tokens
    )

    tolerated_absent_until_ui_slice = landed_token_count == 0
    return {
        "ok": not missing,
        "page_present": True,
        "write_slice_landed": write_slice_landed,
        "expected_route_tokens_present": route_tokens_present,
        "expected_function_tokens_present": function_tokens_present,
        "expected_persistence_tokens_present": persistence_tokens_present,
        "expected_reject_tokens_present": reject_tokens_present,
        "expected_correct_tokens_present": correct_tokens_present,
        "forbidden_token_count": len(forbidden_tokens),
        "forbidden_tokens": forbidden_tokens,
        "missing_route_tokens": missing_route_tokens,
        "missing_function_tokens": missing_function_tokens,
        "missing_persistence_tokens": missing_persistence_tokens,
        "missing_reject_tokens": missing_reject_tokens,
        "missing_correct_tokens": missing_correct_tokens,
        "tolerated_absent_until_ui_slice": tolerated_absent_until_ui_slice,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "crawler_or_external_import_write_allowed": False,
        "repo_fixture_mutation_allowed": False,
        "missing": missing,
    }


def _inspect_admin_api_workspace_contract(source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source, filename="admin_api.py")
    except SyntaxError as exc:
        return {"syntax_error": exc.msg}

    result: dict[str, Any] = {
        "has_persist_to_workspace_field": False,
        "persist_to_workspace_default": None,
        "has_pretrip_workspace_root_param": False,
        "pretrip_workspace_root_default": "missing",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "persist_to_workspace":
                result["has_persist_to_workspace_field"] = True
                result["persist_to_workspace_default"] = _literal_value(node.value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in {"create_admin_app", "create_admin_router"}:
                keyword_defaults = dict(zip(node.args.kwonlyargs, node.args.kw_defaults))
                for arg, default in keyword_defaults.items():
                    if arg.arg == "pretrip_workspace_root":
                        result["has_pretrip_workspace_root_param"] = True
                        result["pretrip_workspace_root_default"] = _literal_value(default)
    return result


def _literal_value(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except ValueError:
        return None


def _check_resource_plan(project_root: Path, project: dict[str, Any]) -> dict[str, Any]:
    from pretrip_resource_plan import PreTripResourcePlan

    ref = project.get("resource_plan_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "device_count": 0,
            "equipment_count": 0,
            "expected_device_count": project.get("resource_plan_device_count"),
            "expected_equipment_count": project.get("resource_plan_equipment_count"),
            "external_api_calls_made": None,
            "raw_payloads_embedded": None,
            "hard_readiness_mutation_allowed": None,
            "blocks_existing_eta_or_readiness": None,
            "missing": [str(ref or "resource_plan_ref")],
        }

    try:
        plan = PreTripResourcePlan.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "device_count": len(payload.get("devices", [])),
            "equipment_count": len(payload.get("equipment", [])),
            "expected_device_count": project.get("resource_plan_device_count"),
            "expected_equipment_count": project.get("resource_plan_equipment_count"),
            "external_api_calls_made": payload.get("external_api_calls_made"),
            "raw_payloads_embedded": payload.get("raw_payloads_embedded"),
            "hard_readiness_mutation_allowed": payload.get("departure_readiness_context", {}).get(
                "hard_readiness_mutation_allowed"
            ),
            "blocks_existing_eta_or_readiness": payload.get("departure_readiness_context", {}).get(
                "blocks_existing_eta_or_readiness"
            ),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    device_count = len(plan.devices)
    equipment_count = len(plan.equipment)
    if plan.status != "candidate_only":
        missing.append("resource_plan_status:candidate_only")
    if device_count != project.get("resource_plan_device_count"):
        missing.append(f"resource_plan_device_count:{project.get('resource_plan_device_count')}")
    if equipment_count != project.get("resource_plan_equipment_count"):
        missing.append(
            f"resource_plan_equipment_count:{project.get('resource_plan_equipment_count')}"
        )
    if plan.external_api_calls_made:
        missing.append("resource_plan_no_external_api_calls")
    if plan.raw_payloads_embedded:
        missing.append("resource_plan_no_raw_payloads_embedded")
    if plan.departure_readiness_context.hard_readiness_mutation_allowed:
        missing.append("resource_plan_no_hard_readiness_mutation")
    if plan.departure_readiness_context.blocks_existing_eta_or_readiness:
        missing.append("resource_plan_no_eta_or_readiness_block")

    return {
        "ok": not missing,
        "status": plan.status,
        "device_count": device_count,
        "equipment_count": equipment_count,
        "expected_device_count": project.get("resource_plan_device_count"),
        "expected_equipment_count": project.get("resource_plan_equipment_count"),
        "team_member_count": len(plan.team_members),
        "warning_candidate_count": len(plan.departure_readiness_context.warning_candidates),
        "blocker_candidate_count": len(plan.departure_readiness_context.blocker_candidates),
        "external_api_calls_made": plan.external_api_calls_made,
        "raw_payloads_embedded": plan.raw_payloads_embedded,
        "hard_readiness_mutation_allowed": (
            plan.departure_readiness_context.hard_readiness_mutation_allowed
        ),
        "blocks_existing_eta_or_readiness": (
            plan.departure_readiness_context.blocks_existing_eta_or_readiness
        ),
        "missing": missing,
    }


def _check_departure_bundle_manifest(
    project_root: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    from pretrip_departure_bundle import PreTripDepartureBundleManifest

    ref = project.get("departure_bundle_manifest_ref")
    payload = _optional_json(project_root, ref)
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": None,
            "required_ref_count": 0,
            "expected_required_ref_count": project.get(
                "departure_bundle_required_ref_count"
            ),
            "artifact_manifest_missing_ref_count": None,
            "human_review_required_before_departure": None,
            "not_departure_approval": None,
            "external_api_calls_made": None,
            "raw_payloads_embedded": None,
            "phase1_runtime_mutation_allowed": None,
            "phase2_writeback_allowed": None,
            "missing": [str(ref or "departure_bundle_manifest_ref")],
        }

    try:
        manifest = PreTripDepartureBundleManifest.model_validate(payload)
    except Exception as exc:
        return {
            "ok": False,
            "status": payload.get("status"),
            "required_ref_count": payload.get("counts", {}).get(
                "required_ref_count",
                0,
            ),
            "expected_required_ref_count": project.get(
                "departure_bundle_required_ref_count"
            ),
            "artifact_manifest_missing_ref_count": payload.get(
                "artifact_manifest",
                {},
            ).get("missing_ref_count"),
            "human_review_required_before_departure": payload.get("boundary", {}).get(
                "human_review_required_before_departure"
            ),
            "not_departure_approval": payload.get("boundary", {}).get(
                "not_departure_approval"
            ),
            "external_api_calls_made": payload.get("boundary", {}).get(
                "external_api_calls_made"
            ),
            "raw_payloads_embedded": payload.get("boundary", {}).get(
                "raw_payloads_embedded"
            ),
            "phase1_runtime_mutation_allowed": payload.get("boundary", {}).get(
                "phase1_runtime_mutation_allowed"
            ),
            "phase2_writeback_allowed": payload.get("boundary", {}).get(
                "phase2_writeback_allowed"
            ),
            "missing": [f"{ref}:{exc}"],
        }

    missing: list[str] = []
    expected_required_ref_count = project.get("departure_bundle_required_ref_count")
    if manifest.status != "frozen_candidate":
        missing.append("departure_bundle_status:frozen_candidate")
    if manifest.counts.required_ref_count != expected_required_ref_count:
        missing.append(f"departure_bundle_required_ref_count:{expected_required_ref_count}")
    review_draft_refs = [
        ref
        for ref in manifest.audit_refs
        if ref.ref_key == "review_draft_log_ref" and ref.status == "draft_only"
    ]
    if len(review_draft_refs) != 1:
        missing.append("departure_bundle_review_draft_log_ref:draft_only")
    elif review_draft_refs[0].summary.get("decisions_recorded") is not False:
        missing.append("departure_bundle_review_draft_log_no_decisions")
    if manifest.artifact_manifest.missing_ref_count != 0:
        missing.append("departure_bundle_artifact_manifest_missing_ref_count:0")
    if not manifest.boundary.human_review_required_before_departure:
        missing.append("departure_bundle_human_review_required")
    if not manifest.boundary.not_departure_approval:
        missing.append("departure_bundle_not_departure_approval")
    if manifest.boundary.external_api_calls_made:
        missing.append("departure_bundle_no_external_api_calls")
    if manifest.boundary.raw_payloads_embedded:
        missing.append("departure_bundle_no_raw_payloads")
    if manifest.boundary.phase1_runtime_mutation_allowed:
        missing.append("departure_bundle_no_phase1_runtime_mutation")
    if manifest.boundary.phase2_writeback_allowed:
        missing.append("departure_bundle_no_phase2_writeback")

    return {
        "ok": not missing,
        "status": manifest.status.value,
        "required_ref_count": manifest.counts.required_ref_count,
        "expected_required_ref_count": expected_required_ref_count,
        "route_ref_count": manifest.counts.route_ref_count,
        "terrain_ref_count": manifest.counts.terrain_ref_count,
        "audit_ref_count": manifest.counts.audit_ref_count,
        "review_draft_log_ref_count": len(review_draft_refs),
        "review_draft_log_statuses": [ref.status for ref in review_draft_refs],
        "artifact_manifest_missing_ref_count": manifest.artifact_manifest.missing_ref_count,
        "artifact_manifest_project_artifact_count": (
            manifest.artifact_manifest.project_artifact_count
        ),
        "artifact_manifest_total_artifact_count": (
            manifest.artifact_manifest.total_artifact_count
        ),
        "human_review_required_before_departure": (
            manifest.boundary.human_review_required_before_departure
        ),
        "not_departure_approval": manifest.boundary.not_departure_approval,
        "external_api_calls_made": manifest.boundary.external_api_calls_made,
        "raw_payloads_embedded": manifest.boundary.raw_payloads_embedded,
        "phase1_runtime_mutation_allowed": (
            manifest.boundary.phase1_runtime_mutation_allowed
        ),
        "phase2_writeback_allowed": manifest.boundary.phase2_writeback_allowed,
        "missing": missing,
    }


def _check_scout260512_pretrip_regression(root: Path) -> dict[str, Any]:
    from pretrip_models import PreTripPackage
    from pretrip_scout260512_fixture import load_scout_260512_pretrip_fixture

    fixture_root = (
        root
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "scout_260512_field_regression"
    )
    missing: list[str] = []
    try:
        fixture = load_scout_260512_pretrip_fixture(fixture_root)
        package = PreTripPackage.model_validate(fixture["package"])
    except Exception as exc:
        return {
            "ok": False,
            "fixture_kind": None,
            "project_id": None,
            "checkpoint_candidate_count": 0,
            "segment_candidate_count": 0,
            "raw_files": [],
            "raw_payloads_embedded": None,
            "primary_mountain_calibration": None,
            "compiled_into_mountain_calibration": None,
            "missing": [f"scout260512_pretrip_regression:{exc}"],
        }

    project = fixture["project"]
    raw_suffixes = {
        ".gpx",
        ".geojson",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".png",
        ".tif",
        ".tiff",
        ".zip",
    }
    raw_files = [
        path.relative_to(fixture_root).as_posix()
        for path in sorted(fixture_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in raw_suffixes
    ]
    serialized = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(fixture_root.rglob("*.json"))
    )
    forbidden_fragments = [
        "PdrSample/",
        "representative_samples",
        "raw_samples",
        "sensor_records",
        "imu_records",
        "heart_rate_records",
        '"features"',
        '"coordinates"',
        "<trkpt",
    ]
    found_forbidden = [fragment for fragment in forbidden_fragments if fragment in serialized]

    if project.get("fixture_kind") != "field-data-to-fixtures-regression":
        missing.append("scout260512_fixture_kind:field-data-to-fixtures-regression")
    if project.get("primary_mountain_calibration") is not False:
        missing.append("scout260512_not_primary_mountain_calibration")
    if project.get("compiled_into_mountain_calibration") is not False:
        missing.append("scout260512_not_compiled_into_mountain_calibration")
    if project.get("phase1_live_runtime_touched") is not False:
        missing.append("scout260512_no_phase1_live_runtime_touch")
    if project.get("raw_payloads_embedded") is not False:
        missing.append("scout260512_no_raw_payloads_embedded")
    if raw_files:
        missing.extend(f"scout260512_raw_fixture:{path}" for path in raw_files)
    if found_forbidden:
        missing.extend(
            f"scout260512_forbidden_fragment:{fragment}"
            for fragment in found_forbidden
        )

    return {
        "ok": not missing,
        "fixture_kind": project.get("fixture_kind"),
        "project_id": project.get("project_id"),
        "checkpoint_candidate_count": len(package.checkpoint_candidates),
        "segment_candidate_count": len(package.segment_candidates),
        "raw_files": raw_files,
        "forbidden_fragment_count": len(found_forbidden),
        "raw_payloads_embedded": project.get("raw_payloads_embedded"),
        "primary_mountain_calibration": project.get("primary_mountain_calibration"),
        "compiled_into_mountain_calibration": project.get(
            "compiled_into_mountain_calibration"
        ),
        "phase1_live_runtime_touched": project.get("phase1_live_runtime_touched"),
        "missing": missing,
    }


def _check_pretrip_project_matrix(root: Path) -> dict[str, Any]:
    from pretrip_project_matrix import build_pretrip_project_matrix

    matrix_path = root / "tests" / "fixtures" / "pretrip" / "project_matrix.json"
    missing: list[str] = []
    if not matrix_path.exists():
        return {
            "ok": False,
            "project_count": 0,
            "roles": {},
            "raw_payload_embedded_count": None,
            "phase1_live_runtime_touched_count": None,
            "missing": [matrix_path.as_posix()],
        }

    try:
        fixture = _load_json(matrix_path)
        expected = build_pretrip_project_matrix(root).to_dict()
    except Exception as exc:
        return {
            "ok": False,
            "project_count": 0,
            "roles": {},
            "raw_payload_embedded_count": None,
            "phase1_live_runtime_touched_count": None,
            "missing": [f"pretrip_project_matrix:{exc}"],
        }

    if fixture != expected:
        missing.append("pretrip_project_matrix_fixture_matches_builder")
    projects = fixture.get("projects", [])
    roles = {project.get("project_id"): project.get("role") for project in projects}
    if roles.get("chilai_nanhua_day1") != "primary_mountain_calibration":
        missing.append("project_matrix_chilai_role:primary_mountain_calibration")
    if roles.get("scout_260512_field_regression") != "field_data_to_fixtures_regression":
        missing.append("project_matrix_scout260512_role:field_data_to_fixtures_regression")
    raw_payload_embedded_count = sum(
        1
        for project in projects
        if project.get("raw_payload_embedding", {}).get("embedded") is True
    )
    phase1_live_runtime_touched_count = sum(
        1
        for project in projects
        if project.get("release_check_boundary_flags", {}).get(
            "phase1_live_runtime_touched"
        )
        is True
    )
    if raw_payload_embedded_count:
        missing.append("project_matrix_no_raw_payloads")
    if phase1_live_runtime_touched_count:
        missing.append("project_matrix_no_phase1_live_runtime_touch")

    return {
        "ok": not missing,
        "project_count": len(projects),
        "roles": roles,
        "raw_payload_embedded_count": raw_payload_embedded_count,
        "phase1_live_runtime_touched_count": phase1_live_runtime_touched_count,
        "missing": missing,
    }


def _check_pretrip_source_registry(root: Path) -> dict[str, Any]:
    from pretrip_source_registry import (
        PlanningSourceTreatment,
        PreTripSourceRegistry,
        build_default_pretrip_source_registry,
    )

    registry_path = (
        root
        / "tests"
        / "fixtures"
        / "pretrip"
        / "source_registry"
        / "chilai_nanhua_day1_source_registry.json"
    )
    missing: list[str] = []
    if not registry_path.exists():
        return {
            "ok": False,
            "source_count": 0,
            "observed_fact_policy": None,
            "network_policy": None,
            "observed_fact_treatment_count": None,
            "computed_eta_field_count": None,
            "missing": [registry_path.as_posix()],
        }

    try:
        payload = _load_json(registry_path)
        registry = PreTripSourceRegistry.model_validate(payload)
        expected = build_default_pretrip_source_registry()
    except Exception as exc:
        return {
            "ok": False,
            "source_count": 0,
            "observed_fact_policy": None,
            "network_policy": None,
            "observed_fact_treatment_count": None,
            "computed_eta_field_count": None,
            "missing": [f"pretrip_source_registry:{exc}"],
        }

    if registry != expected:
        missing.append("source_registry_fixture_matches_builder")
    if registry.network_policy != "no_network":
        missing.append("source_registry_network_policy:no_network")
    if registry.observed_fact_policy != "never":
        missing.append("source_registry_observed_fact_policy:never")
    observed_fact_treatment_count = sum(
        1
        for entry in registry.entries
        for treatment in entry.treatment
        if str(treatment) == "ObservedFact"
    )
    computed_eta_field_count = sum(
        1
        for entry in registry.entries
        if entry.timing_fitness_calibration is not None
        for field in entry.timing_fitness_calibration.supported_fields
        if "eta" in field.lower()
    )
    if observed_fact_treatment_count:
        missing.append("source_registry_no_observed_fact_treatment")
    if computed_eta_field_count:
        missing.append("source_registry_no_computed_eta_fields")
    if any(PlanningSourceTreatment.HUMAN_REVIEW not in entry.treatment for entry in registry.entries):
        missing.append("source_registry_human_review_required")
    entries_by_id = {entry.source_id: entry for entry in registry.entries}
    required_source_ids = {
        "source.joyhike.main_site",
        "source.joyhike.blog",
        "source.ptt.sunriver_timing",
        "source.local.gpx_dir",
        "source.local.jpg_dir",
        "source.local.dtm_dirs",
        "source.comparison.rudy_like_gpx",
        "source.scout_260512.field_refs",
    }
    if not required_source_ids <= set(entries_by_id):
        missing.append("source_registry_required_source_ids")
    for source_id in ("source.joyhike.main_site", "source.joyhike.blog"):
        entry = entries_by_id.get(source_id)
        treatments = {str(treatment) for treatment in entry.treatment} if entry else set()
        if treatments != {"Artifact", "ModelInterpretation", "HumanReview"}:
            missing.append(f"source_registry_{source_id}_reference_treatment")
        if entry is not None and entry.reference_only is not True:
            missing.append(f"source_registry_{source_id}_reference_only")
    ptt = entries_by_id.get("source.ptt.sunriver_timing")
    ptt_calibration_scope = (
        ptt.timing_fitness_calibration.output_scope
        if ptt is not None and ptt.timing_fitness_calibration is not None
        else None
    )
    if ptt_calibration_scope != "calibration_inputs_only":
        missing.append("source_registry_ptt_calibration_inputs_only")

    return {
        "ok": not missing,
        "source_count": len(registry.entries),
        "source_ids": sorted(entries_by_id),
        "observed_fact_policy": registry.observed_fact_policy,
        "network_policy": registry.network_policy,
        "observed_fact_treatment_count": observed_fact_treatment_count,
        "computed_eta_field_count": computed_eta_field_count,
        "ptt_calibration_scope": ptt_calibration_scope,
        "missing": missing,
    }


def _check_pretrip_implementation_status(root: Path) -> dict[str, Any]:
    from pretrip_implementation_status import build_pretrip_implementation_status_manifest

    status_path = root / "tests" / "fixtures" / "pretrip" / "implementation_status.json"
    missing: list[str] = []
    if not status_path.exists():
        return {
            "ok": False,
            "implemented_milestones": [],
            "not_started_milestones": [],
            "runtime_mutation_allowed": None,
            "ui_scope_included": None,
            "missing": [status_path.as_posix()],
        }

    try:
        fixture = _load_json(status_path)
        expected = build_pretrip_implementation_status_manifest().to_dict()
    except Exception as exc:
        return {
            "ok": False,
            "implemented_milestones": [],
            "not_started_milestones": [],
            "runtime_mutation_allowed": None,
            "ui_scope_included": None,
            "missing": [f"pretrip_implementation_status:{exc}"],
        }

    fixture_matches_builder = fixture == expected
    status_manifest = expected
    milestones = status_manifest.get("milestones", [])
    by_id = {milestone.get("milestone"): milestone for milestone in milestones}
    expected_implemented = {
        "0",
        "1",
        "2",
        "2A",
        "3",
        "4",
        "5",
        "6",
        "6A",
        "7",
        "8",
        "9",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
        "20",
        "21",
        "22",
        "23",
        "24",
        "25",
        "26",
        "4.5",
        "4.5A",
        "4.5B",
        "4.5C",
        "4.5D",
        "4.5E",
        "4.5F",
        "4.5G",
        "4.5H",
        "4.5I",
        "4.5J",
        "4.5K",
        "4.5L",
        "4.5M",
        "4.5N",
        "4.5O",
        "4.5P",
        "4.5Q",
        "4.5R",
        "4.5S",
        "4.5T",
        "4.5U",
        "4.5V",
        "4.5W",
        "4.5X",
        "4.5Y",
        "4.5Z",
        "4.5AA",
        "4.5AB",
        "4.5AC",
        "4.5AD",
        "4.5AE",
        "4.5AF",
        "4.5AG",
        "4.5AH",
        "4.5AI",
        "4.5AJ",
        "4.5AK",
        "4.5AL",
        "4.5AM",
        "4.5AN",
        "4.5AO",
    }
    implemented = {
        key
        for key, milestone in by_id.items()
        if milestone.get("implementation_status") == "implemented"
    }
    not_started = {
        key
        for key, milestone in by_id.items()
        if milestone.get("implementation_status") == "not_started"
    }
    if implemented != expected_implemented:
        missing.append("implementation_status_milestones_0_to_26_implemented")
    if not_started:
        missing.append("implementation_status_no_not_started_milestones")

    boundary = status_manifest.get("boundary", {})
    if boundary.get("runtime_mutation_allowed") is not False:
        missing.append("implementation_status_no_runtime_mutation")
    if boundary.get("runtime_export_write_allowed") is not True:
        missing.append("implementation_status_runtime_export_write_allowed")
    if boundary.get("phase1_live_runtime_touched") is not False:
        missing.append("implementation_status_no_phase1_runtime_touch")
    if boundary.get("phase2_bridge_touched") is not False:
        missing.append("implementation_status_no_phase2_bridge_touch")
    if boundary.get("ui_scope_included") is not True:
        missing.append("implementation_status_ui_scope_included")
    if boundary.get("ui_scope") != "fixture_backed_read_only_admin_preview":
        missing.append("implementation_status_ui_scope_fixture_backed_read_only")

    validation_commands = status_manifest.get("validation_commands", {})
    focused_command_parts = validation_commands.get("phase4_focused_suite", "").split()
    focused_tests = [part for part in focused_command_parts if part.startswith("tests/")]
    if focused_tests != list(FOCUSED_PHASE4_TEST_PATHS):
        missing.append("implementation_status_focused_suite_matches_release_check_order")
    if "tests/test_pretrip_decision_register.py" not in validation_commands.get(
        "phase4_focused_suite",
        "",
    ):
        missing.append("implementation_status_focused_suite_decision_register")
    if "tests/test_pretrip_fixture_hygiene.py" not in validation_commands.get(
        "phase4_focused_suite",
        "",
    ):
        missing.append("implementation_status_focused_suite_fixture_hygiene")
    for workspace_test in (
        "tests/test_pretrip_expert_contribution_apply_plan.py",
        "tests/test_pretrip_route_note_reviewed_assumptions.py",
        "tests/test_pretrip_final_mission_graph.py",
    ):
        if workspace_test not in validation_commands.get("phase4_focused_suite", ""):
            missing.append(f"implementation_status_focused_suite:{workspace_test}")
    for ui_test in (
        "tests/test_pretrip_admin_view.py",
        "tests/test_pretrip_admin_page.py",
        "tests/test_pretrip_admin_api.py",
        "tests/test_admin_map_layers.py",
        "tests/test_admin_basemap_tiles.py",
        "tests/test_admin_after_action.py",
        "tests/test_runtime_remote_provider_demo_harness.py",
        "tests/test_runtime_remote_provider_demo_bundle.py",
        "tests/test_runtime_remote_provider_external_demo_bundle.py",
        "tests/test_admin_tile_proxy.py",
        "tests/test_admin_weather_overlay.py",
        "tests/test_admin_tile_cache_builder.py",
        "tests/test_admin_local_raster_source.py",
        "tests/test_admin_local_raster_tiles.py",
        "tests/test_pretrip_review_draft.py",
        "tests/test_pretrip_review_draft_fixture.py",
    ):
        if ui_test not in validation_commands.get("phase4_focused_suite", ""):
            missing.append(f"implementation_status_focused_suite:{ui_test}")

    milestone_14 = by_id.get("14", {})
    milestone_14_coverage = milestone_14.get("release_check_coverage", {})
    if milestone_14.get("title") != "Admin-Created Metadata Workspace":
        missing.append("implementation_status_milestone_14_admin_metadata_workspace")
    for check_name in (
        "admin_workspace_project_creation_contract",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_14_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_14_coverage:{check_name}")

    milestone_15 = by_id.get("15", {})
    milestone_15_coverage = milestone_15.get("release_check_coverage", {})
    if milestone_15.get("title") != "Local Workspace Admin Write Controls":
        missing.append("implementation_status_milestone_15_admin_write_controls")
    for check_name in (
        "admin_ui_local_workspace_write_controls",
        "admin_workspace_project_creation_contract",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_15_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_15_coverage:{check_name}")

    milestone_16 = by_id.get("16", {})
    milestone_16_coverage = milestone_16.get("release_check_coverage", {})
    if milestone_16.get("title") != "Local Workspace Reject Review Control":
        missing.append("implementation_status_milestone_16_reject_review_control")
    for check_name in (
        "admin_ui_local_workspace_write_controls",
        "admin_workspace_project_creation_contract",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_16_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_16_coverage:{check_name}")

    milestone_17 = by_id.get("17", {})
    milestone_17_coverage = milestone_17.get("release_check_coverage", {})
    if milestone_17.get("title") != "Review Decision Duplicate Candidate Guard":
        missing.append("implementation_status_milestone_17_duplicate_candidate_guard")
    for check_name in (
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_17_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_17_coverage:{check_name}")

    milestone_18 = by_id.get("18", {})
    milestone_18_coverage = milestone_18.get("release_check_coverage", {})
    if milestone_18.get("title") != "Local Workspace Corrected Review Control":
        missing.append("implementation_status_milestone_18_corrected_review_control")
    for check_name in (
        "admin_ui_local_workspace_write_controls",
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_18_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_18_coverage:{check_name}")

    milestone_19 = by_id.get("19", {})
    milestone_19_coverage = milestone_19.get("release_check_coverage", {})
    if milestone_19.get("title") != "Workspace-Aware Admin View Overlay":
        missing.append("implementation_status_milestone_19_workspace_admin_view_overlay")
    for check_name in (
        "admin_workspace_persistence_contract",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_19_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_19_coverage:{check_name}")

    milestone_20 = by_id.get("20", {})
    milestone_20_coverage = milestone_20.get("release_check_coverage", {})
    if milestone_20.get("title") != "Review Decision Correction Detail Exposure":
        missing.append("implementation_status_milestone_20_correction_detail_exposure")
    for check_name in (
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_20_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_20_coverage:{check_name}")

    milestone_21 = by_id.get("21", {})
    milestone_21_coverage = milestone_21.get("release_check_coverage", {})
    if milestone_21.get("title") != "Expert Contribution Memory Seed Candidates":
        missing.append("implementation_status_milestone_21_expert_contribution_memory_seed")
    for check_name in (
        "expert_contribution_log",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_21_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_21_coverage:{check_name}")

    milestone_22 = by_id.get("22", {})
    milestone_22_coverage = milestone_22.get("release_check_coverage", {})
    if milestone_22.get("title") != "GPX Waypoint Route Note Candidates":
        missing.append("implementation_status_milestone_22_route_note_candidates")
    for check_name in (
        "route_note_candidates",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_22_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_22_coverage:{check_name}")

    milestone_23 = by_id.get("23", {})
    milestone_23_coverage = milestone_23.get("release_check_coverage", {})
    if milestone_23.get("title") != "Route Note Ln Proposal Candidates":
        missing.append("implementation_status_milestone_23_route_note_ln_proposals")
    for check_name in (
        "route_note_ln_proposals",
        "review_queue_manifest",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_23_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_23_coverage:{check_name}")

    milestone_24 = by_id.get("24", {})
    milestone_24_coverage = milestone_24.get("release_check_coverage", {})
    if milestone_24.get("title") != "Route Note Review Options":
        missing.append("implementation_status_milestone_24_route_note_review_options")
    for check_name in (
        "route_note_review_options",
        "artifact_manifest",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_24_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_24_coverage:{check_name}")

    milestone_25 = by_id.get("25", {})
    milestone_25_coverage = milestone_25.get("release_check_coverage", {})
    if milestone_25.get("title") != "Expert Contribution Workspace Apply Plan":
        missing.append("implementation_status_milestone_25_expert_contribution_apply_plan")
    for check_name in (
        "workspace_only_artifact_boundaries",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_25_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_25_coverage:{check_name}")

    milestone_26 = by_id.get("26", {})
    milestone_26_coverage = milestone_26.get("release_check_coverage", {})
    if milestone_26.get("title") != "Route Note Reviewed Workspace Assumptions":
        missing.append("implementation_status_milestone_26_route_note_reviewed_assumptions")
    for check_name in (
        "workspace_only_artifact_boundaries",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_26_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_26_coverage:{check_name}")

    milestone_45 = by_id.get("4.5", {})
    milestone_45_coverage = milestone_45.get("release_check_coverage", {})
    if milestone_45.get("title") != "Departure Gate and Runtime Handoff Boundary":
        missing.append("implementation_status_milestone_4_5_departure_runtime_handoff")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5_coverage:{check_name}")

    milestone_45a = by_id.get("4.5A", {})
    milestone_45a_coverage = milestone_45a.get("release_check_coverage", {})
    if milestone_45a.get("title") != "Departure Gate Resolution Path":
        missing.append("implementation_status_milestone_4_5a_departure_gate_resolution")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45a_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5a_coverage:{check_name}")

    milestone_45b = by_id.get("4.5B", {})
    milestone_45b_coverage = milestone_45b.get("release_check_coverage", {})
    if milestone_45b.get("title") != "Final MissionGraph Generation Gate":
        missing.append("implementation_status_milestone_4_5b_final_mission_graph")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45b_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5b_coverage:{check_name}")

    milestone_45c = by_id.get("4.5C", {})
    milestone_45c_coverage = milestone_45c.get("release_check_coverage", {})
    if milestone_45c.get("title") != "Final MissionGraph Runtime Handoff Link":
        missing.append("implementation_status_milestone_4_5c_runtime_handoff_link")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45c_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5c_coverage:{check_name}")

    milestone_45d = by_id.get("4.5D", {})
    milestone_45d_coverage = milestone_45d.get("release_check_coverage", {})
    if milestone_45d.get("title") != "Runtime Export Bundle Write Path":
        missing.append("implementation_status_milestone_4_5d_runtime_export")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45d_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5d_coverage:{check_name}")

    milestone_45e = by_id.get("4.5E", {})
    milestone_45e_coverage = milestone_45e.get("release_check_coverage", {})
    if milestone_45e.get("title") != "Runtime Artifact Resolution Manifest":
        missing.append("implementation_status_milestone_4_5e_runtime_artifact_resolution")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45e_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5e_coverage:{check_name}")

    milestone_45f = by_id.get("4.5F", {})
    milestone_45f_coverage = milestone_45f.get("release_check_coverage", {})
    if milestone_45f.get("title") != "Runtime Activation Preflight":
        missing.append("implementation_status_milestone_4_5f_runtime_activation_preflight")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45f_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5f_coverage:{check_name}")

    milestone_45g = by_id.get("4.5G", {})
    milestone_45g_coverage = milestone_45g.get("release_check_coverage", {})
    if milestone_45g.get("title") != "Runtime Activation Request":
        missing.append("implementation_status_milestone_4_5g_runtime_activation_request")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45g_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5g_coverage:{check_name}")

    milestone_45h = by_id.get("4.5H", {})
    milestone_45h_coverage = milestone_45h.get("release_check_coverage", {})
    if milestone_45h.get("title") != "Runtime Load Dry Run":
        missing.append("implementation_status_milestone_4_5h_runtime_load_dry_run")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45h_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5h_coverage:{check_name}")

    milestone_45i = by_id.get("4.5I", {})
    milestone_45i_coverage = milestone_45i.get("release_check_coverage", {})
    if milestone_45i.get("title") != "Actual Runtime Activation Loader":
        missing.append("implementation_status_milestone_4_5i_actual_runtime_activation")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45i_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5i_coverage:{check_name}")

    milestone_45j = by_id.get("4.5J", {})
    milestone_45j_coverage = milestone_45j.get("release_check_coverage", {})
    if milestone_45j.get("title") != "Runtime Observing Start":
        missing.append("implementation_status_milestone_4_5j_runtime_observing_start")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45j_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5j_coverage:{check_name}")

    milestone_45k = by_id.get("4.5K", {})
    milestone_45k_coverage = milestone_45k.get("release_check_coverage", {})
    if milestone_45k.get("title") != "Runtime Lifecycle Controls":
        missing.append("implementation_status_milestone_4_5k_runtime_lifecycle_controls")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45k_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5k_coverage:{check_name}")

    milestone_45l = by_id.get("4.5L", {})
    milestone_45l_coverage = milestone_45l.get("release_check_coverage", {})
    if milestone_45l.get("title") != "Runtime Observation Batch":
        missing.append("implementation_status_milestone_4_5l_runtime_observation_batch")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45l_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5l_coverage:{check_name}")

    milestone_45m = by_id.get("4.5M", {})
    milestone_45m_coverage = milestone_45m.get("release_check_coverage", {})
    if milestone_45m.get("title") != "Runtime Stream Guard":
        missing.append("implementation_status_milestone_4_5m_runtime_stream_guard")
    for check_name in (
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45m_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5m_coverage:{check_name}")

    milestone_45n = by_id.get("4.5N", {})
    milestone_45n_coverage = milestone_45n.get("release_check_coverage", {})
    if milestone_45n.get("title") != "Runtime Stream Policy":
        missing.append("implementation_status_milestone_4_5n_runtime_stream_policy")
    for check_name in (
        "runtime_stream_policy",
        "phase45_departure_runtime_handoff",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45n_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5n_coverage:{check_name}")

    milestone_45o = by_id.get("4.5O", {})
    milestone_45o_coverage = milestone_45o.get("release_check_coverage", {})
    if milestone_45o.get("title") != "Runtime Observation Envelope":
        missing.append("implementation_status_milestone_4_5o_runtime_observation_envelope")
    for check_name in (
        "runtime_observation_envelope",
        "runtime_stream_policy",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45o_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5o_coverage:{check_name}")

    milestone_45p = by_id.get("4.5P", {})
    milestone_45p_coverage = milestone_45p.get("release_check_coverage", {})
    if milestone_45p.get("title") != "Runtime Input Admission":
        missing.append("implementation_status_milestone_4_5p_runtime_input_admission")
    for check_name in (
        "runtime_input_admission",
        "runtime_observation_envelope",
        "runtime_stream_policy",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45p_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5p_coverage:{check_name}")

    milestone_45q = by_id.get("4.5Q", {})
    milestone_45q_coverage = milestone_45q.get("release_check_coverage", {})
    if milestone_45q.get("title") != "Safety Observation Admission API":
        missing.append("implementation_status_milestone_4_5q_safety_observation_admission_api")
    for check_name in (
        "safety_observation_admission_api",
        "runtime_input_admission",
        "runtime_observation_envelope",
        "runtime_stream_policy",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45q_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5q_coverage:{check_name}")

    milestone_45r = by_id.get("4.5R", {})
    milestone_45r_coverage = milestone_45r.get("release_check_coverage", {})
    if milestone_45r.get("title") != "Runtime Incident Bridge Opt-In Guard":
        missing.append("implementation_status_milestone_4_5r_runtime_incident_bridge_opt_in")
    for check_name in (
        "runtime_incident_bridge_opt_in",
        "runtime_stream_policy",
        "core_phase4_modules",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45r_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5r_coverage:{check_name}")

    milestone_45s = by_id.get("4.5S", {})
    milestone_45s_coverage = milestone_45s.get("release_check_coverage", {})
    if milestone_45s.get("title") != "Server Safety Admission Config":
        missing.append("implementation_status_milestone_4_5s_server_safety_admission_config")
    for check_name in (
        "server_safety_observation_admission_config",
        "safety_observation_admission_api",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45s_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5s_coverage:{check_name}")

    milestone_45t = by_id.get("4.5T", {})
    milestone_45t_coverage = milestone_45t.get("release_check_coverage", {})
    if milestone_45t.get("title") != "Runtime Stream Transport API":
        missing.append("implementation_status_milestone_4_5t_runtime_stream_transport_api")
    for check_name in (
        "runtime_stream_transport_api",
        "server_safety_observation_admission_config",
        "safety_observation_admission_api",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45t_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5t_coverage:{check_name}")

    milestone_45u = by_id.get("4.5U", {})
    milestone_45u_coverage = milestone_45u.get("release_check_coverage", {})
    if milestone_45u.get("title") != "Runtime Stream Telemetry":
        missing.append("implementation_status_milestone_4_5u_runtime_stream_telemetry")
    for check_name in (
        "runtime_stream_telemetry",
        "runtime_stream_transport_api",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45u_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5u_coverage:{check_name}")

    milestone_45v = by_id.get("4.5V", {})
    milestone_45v_coverage = milestone_45v.get("release_check_coverage", {})
    if milestone_45v.get("title") != "Runtime Stream Operator Controls":
        missing.append("implementation_status_milestone_4_5v_runtime_stream_controls")
    for check_name in (
        "runtime_stream_controls",
        "runtime_stream_transport_api",
        "runtime_stream_telemetry",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45v_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5v_coverage:{check_name}")

    milestone_45w = by_id.get("4.5W", {})
    milestone_45w_coverage = milestone_45w.get("release_check_coverage", {})
    if milestone_45w.get("title") != "Runtime Incident Bridge Enablement Dry Run":
        missing.append("implementation_status_milestone_4_5w_runtime_incident_bridge_enablement")
    for check_name in (
        "runtime_incident_bridge_enablement",
        "runtime_incident_bridge_opt_in",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45w_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5w_coverage:{check_name}")

    milestone_45x = by_id.get("4.5X", {})
    milestone_45x_coverage = milestone_45x.get("release_check_coverage", {})
    if milestone_45x.get("title") != "Mock Delivery Acknowledgment and Withdrawal":
        missing.append("implementation_status_milestone_4_5x_mock_delivery_ack")
    for check_name in (
        "runtime_incident_bridge_delivery_ack",
        "runtime_incident_bridge_enablement",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45x_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5x_coverage:{check_name}")

    milestone_45y = by_id.get("4.5Y", {})
    milestone_45y_coverage = milestone_45y.get("release_check_coverage", {})
    if milestone_45y.get("title") != "Webhook Remote Provider Policy Contract":
        missing.append("implementation_status_milestone_4_5y_remote_provider_policy")
    for check_name in (
        "runtime_remote_provider_policy",
        "runtime_incident_bridge_delivery_ack",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45y_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5y_coverage:{check_name}")

    milestone_45z = by_id.get("4.5Z", {})
    milestone_45z_coverage = milestone_45z.get("release_check_coverage", {})
    if milestone_45z.get("title") != "Remote Provider Config Preflight":
        missing.append("implementation_status_milestone_4_5z_remote_provider_config_preflight")
    for check_name in (
        "runtime_remote_provider_config_preflight",
        "runtime_remote_provider_policy",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45z_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5z_coverage:{check_name}")

    milestone_45aa = by_id.get("4.5AA", {})
    milestone_45aa_coverage = milestone_45aa.get("release_check_coverage", {})
    if milestone_45aa.get("title") != "Remote Provider Payload Composer":
        missing.append("implementation_status_milestone_4_5aa_remote_provider_payload")
    for check_name in (
        "runtime_remote_provider_payload_composer",
        "runtime_remote_provider_config_preflight",
        "runtime_remote_provider_policy",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45aa_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5aa_coverage:{check_name}")

    milestone_45ab = by_id.get("4.5AB", {})
    milestone_45ab_coverage = milestone_45ab.get("release_check_coverage", {})
    if milestone_45ab.get("title") != "Remote Provider Send Intent Queue":
        missing.append("implementation_status_milestone_4_5ab_remote_provider_send_queue")
    for check_name in (
        "runtime_remote_provider_send_queue",
        "runtime_remote_provider_payload_composer",
        "runtime_remote_provider_config_preflight",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ab_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ab_coverage:{check_name}")

    milestone_45ac = by_id.get("4.5AC", {})
    milestone_45ac_coverage = milestone_45ac.get("release_check_coverage", {})
    if milestone_45ac.get("title") != "Webhook Live Provider Adapter":
        missing.append("implementation_status_milestone_4_5ac_webhook_live_adapter")
    for check_name in (
        "runtime_remote_provider_live_adapter",
        "runtime_remote_provider_send_queue",
        "runtime_remote_provider_config_preflight",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ac_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ac_coverage:{check_name}")

    milestone_45ad = by_id.get("4.5AD", {})
    milestone_45ad_coverage = milestone_45ad.get("release_check_coverage", {})
    if milestone_45ad.get("title") != "Webhook Live Send Operator CLI":
        missing.append("implementation_status_milestone_4_5ad_webhook_live_send_cli")
    for check_name in (
        "runtime_remote_provider_live_send_cli",
        "runtime_remote_provider_live_adapter",
        "runtime_remote_provider_send_queue",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ad_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ad_coverage:{check_name}")

    milestone_45ae = by_id.get("4.5AE", {})
    milestone_45ae_coverage = milestone_45ae.get("release_check_coverage", {})
    if milestone_45ae.get("title") != "Shared Admin Map Layer Stack":
        missing.append("implementation_status_milestone_4_5ae_admin_map_layer_stack")
    for check_name in (
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ae_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ae_coverage:{check_name}")

    milestone_45af = by_id.get("4.5AF", {})
    milestone_45af_coverage = milestone_45af.get("release_check_coverage", {})
    if milestone_45af.get("title") != "Real OSM Basemap Renderer":
        missing.append("implementation_status_milestone_4_5af_real_osm_basemap")
    for check_name in (
        "admin_basemap_renderer",
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45af_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5af_coverage:{check_name}")

    milestone_45ag = by_id.get("4.5AG", {})
    milestone_45ag_coverage = milestone_45ag.get("release_check_coverage", {})
    if milestone_45ag.get("title") != "Local Webhook Demo Harness":
        missing.append("implementation_status_milestone_4_5ag_local_webhook_harness")
    for check_name in (
        "runtime_remote_provider_demo_harness",
        "runtime_remote_provider_live_send_cli",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ag_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ag_coverage:{check_name}")

    milestone_45ah = by_id.get("4.5AH", {})
    milestone_45ah_coverage = milestone_45ah.get("release_check_coverage", {})
    if milestone_45ah.get("title") != "Local Webhook Demo Bundle Builder":
        missing.append("implementation_status_milestone_4_5ah_local_demo_bundle")
    for check_name in (
        "runtime_remote_provider_demo_bundle",
        "runtime_remote_provider_demo_harness",
        "runtime_remote_provider_live_send_cli",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ah_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ah_coverage:{check_name}")

    milestone_45ai = by_id.get("4.5AI", {})
    milestone_45ai_coverage = milestone_45ai.get("release_check_coverage", {})
    if milestone_45ai.get("title") != "Local OSM Tile Cache Proxy":
        missing.append("implementation_status_milestone_4_5ai_local_osm_tile_proxy")
    for check_name in (
        "admin_tile_proxy",
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ai_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ai_coverage:{check_name}")

    milestone_45aj = by_id.get("4.5AJ", {})
    milestone_45aj_coverage = milestone_45aj.get("release_check_coverage", {})
    if milestone_45aj.get("title") != "Weather API Overlay Renderer":
        missing.append("implementation_status_milestone_4_5aj_weather_api_overlay")
    for check_name in (
        "admin_weather_overlay",
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45aj_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5aj_coverage:{check_name}")

    milestone_45ak = by_id.get("4.5AK", {})
    milestone_45ak_coverage = milestone_45ak.get("release_check_coverage", {})
    if milestone_45ak.get("title") != "External Webhook Demo Bundle":
        missing.append("implementation_status_milestone_4_5ak_external_webhook_bundle")
    for check_name in (
        "runtime_remote_provider_external_demo_bundle",
        "runtime_remote_provider_demo_bundle",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ak_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ak_coverage:{check_name}")

    milestone_45al = by_id.get("4.5AL", {})
    milestone_45al_coverage = milestone_45al.get("release_check_coverage", {})
    if milestone_45al.get("title") != "Hardware Tile Cache Plan Builder":
        missing.append("implementation_status_milestone_4_5al_tile_cache_builder")
    for check_name in (
        "admin_tile_cache_builder",
        "admin_tile_proxy",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45al_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5al_coverage:{check_name}")

    milestone_45am = by_id.get("4.5AM", {})
    milestone_45am_coverage = milestone_45am.get("release_check_coverage", {})
    if milestone_45am.get("title") != "Local GeoTIFF Raster Source Manifest":
        missing.append("implementation_status_milestone_4_5am_local_raster_source")
    for check_name in (
        "admin_local_raster_source",
        "admin_map_layer_stack",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45am_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5am_coverage:{check_name}")

    milestone_45an = by_id.get("4.5AN", {})
    milestone_45an_coverage = milestone_45an.get("release_check_coverage", {})
    if milestone_45an.get("title") != "Local GeoTIFF Raster Tile Pyramid":
        missing.append("implementation_status_milestone_4_5an_raster_tile_pyramid")
    for check_name in (
        "admin_local_raster_tiles",
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45an_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5an_coverage:{check_name}")

    milestone_45ao = by_id.get("4.5AO", {})
    milestone_45ao_coverage = milestone_45ao.get("release_check_coverage", {})
    if milestone_45ao.get("title") != "Pretrip Raster Imagery Renderer":
        missing.append("implementation_status_milestone_4_5ao_raster_imagery_renderer")
    for check_name in (
        "admin_map_layer_stack",
        "pretrip_admin_ui",
        "focused_phase4_tests",
    ):
        if check_name not in milestone_45ao_coverage.get("check_names", []):
            missing.append(f"implementation_status_milestone_4_5ao_coverage:{check_name}")

    return {
        "ok": not missing,
        "implemented_milestones": [
            milestone.get("milestone")
            for milestone in milestones
            if milestone.get("implementation_status") == "implemented"
        ],
        "not_started_milestones": sorted(not_started),
        "runtime_mutation_allowed": boundary.get("runtime_mutation_allowed"),
        "runtime_export_write_allowed": boundary.get("runtime_export_write_allowed"),
        "phase1_live_runtime_touched": boundary.get("phase1_live_runtime_touched"),
        "phase2_bridge_touched": boundary.get("phase2_bridge_touched"),
        "ui_scope_included": boundary.get("ui_scope_included"),
        "ui_scope": boundary.get("ui_scope"),
        "focused_suite_test_count": len(focused_tests),
        "fixture_matches_builder": fixture_matches_builder,
        "missing": missing,
    }


def _check_pretrip_decision_register(root: Path) -> dict[str, Any]:
    from pretrip_decision_register import (
        REQUIRED_OPEN_QUESTION_IDS,
        REQUIRED_RESOLVED_DECISION_IDS,
        load_pretrip_decision_register,
    )

    register_path = root / "tests" / "fixtures" / "pretrip" / "decision_register.json"
    missing: list[str] = []
    if not register_path.exists():
        return {
            "ok": False,
            "resolved_count": 0,
            "open_question_count": 0,
            "metadata_only": None,
            "no_network": None,
            "ui_scope": None,
            "no_runtime_effects": None,
            "missing": [register_path.as_posix()],
        }

    try:
        register = load_pretrip_decision_register(register_path)
    except Exception as exc:
        return {
            "ok": False,
            "resolved_count": 0,
            "open_question_count": 0,
            "metadata_only": None,
            "no_network": None,
            "ui_scope": None,
            "no_runtime_effects": None,
            "missing": [f"pretrip_decision_register:{exc}"],
        }

    resolved_ids = {decision.decision_id for decision in register.resolved_decisions}
    open_ids = {question.decision_id for question in register.open_questions}
    if resolved_ids != REQUIRED_RESOLVED_DECISION_IDS:
        missing.append("decision_register_required_resolved_decisions")
    if open_ids != REQUIRED_OPEN_QUESTION_IDS:
        missing.append("decision_register_required_open_questions")
    if register.metadata_only is not True:
        missing.append("decision_register_metadata_only")
    if register.no_network is not True:
        missing.append("decision_register_no_network")
    if register.no_crawler is not True:
        missing.append("decision_register_no_crawler")
    if register.ui_scope != "fixture_backed_read_only_admin_preview":
        missing.append("decision_register_ui_scope_fixture_backed_read_only")
    if register.no_runtime_effects is not True:
        missing.append("decision_register_no_runtime_effects")

    return {
        "ok": not missing,
        "resolved_count": len(register.resolved_decisions),
        "open_question_count": len(register.open_questions),
        "metadata_only": register.metadata_only,
        "no_network": register.no_network,
        "no_crawler": register.no_crawler,
        "ui_scope": register.ui_scope,
        "no_runtime_effects": register.no_runtime_effects,
        "missing": missing,
    }


def _check_pretrip_fixture_hygiene(root: Path) -> dict[str, Any]:
    from pretrip_fixture_hygiene import build_pretrip_fixture_hygiene_manifest

    manifest_path = root / "tests" / "fixtures" / "pretrip" / "fixture_hygiene_manifest.json"
    missing: list[str] = []
    if not manifest_path.exists():
        return {
            "ok": False,
            "files_scanned": 0,
            "json_files_scanned": 0,
            "total_issues": None,
            "raw_suffix_files": None,
            "oversized_files": None,
            "json_parse_errors": None,
            "forbidden_fragments": None,
            "missing": [manifest_path.as_posix()],
        }

    try:
        fixture = _load_json(manifest_path)
        expected = build_pretrip_fixture_hygiene_manifest(root).to_dict()
    except Exception as exc:
        return {
            "ok": False,
            "files_scanned": 0,
            "json_files_scanned": 0,
            "total_issues": None,
            "raw_suffix_files": None,
            "oversized_files": None,
            "json_parse_errors": None,
            "forbidden_fragments": None,
            "missing": [f"pretrip_fixture_hygiene:{exc}"],
        }

    if fixture != expected:
        missing.append("pretrip_fixture_hygiene_fixture_matches_builder")

    counts = fixture.get("counts", {})
    if counts.get("total_issues") != 0:
        missing.append("fixture_hygiene_total_issues:0")
    if counts.get("raw_suffix_files") != 0:
        missing.append("fixture_hygiene_raw_suffix_files:0")
    if counts.get("raw_route_suffix_files") != 0:
        missing.append("fixture_hygiene_raw_route_suffix_files:0")
    if counts.get("oversized_files") != 0:
        missing.append("fixture_hygiene_oversized_files:0")
    if counts.get("json_parse_errors") != 0:
        missing.append("fixture_hygiene_json_parse_errors:0")
    if counts.get("forbidden_fragments") != 0:
        missing.append("fixture_hygiene_forbidden_fragments:0")
    policy = fixture.get("policy", {})
    if policy.get("fixture_only") is not True:
        missing.append("fixture_hygiene_fixture_only")
    if policy.get("no_ui_or_runtime") is not True:
        missing.append("fixture_hygiene_no_ui_or_runtime")

    return {
        "ok": not missing,
        "files_scanned": counts.get("files_scanned"),
        "json_files_scanned": counts.get("json_files_scanned"),
        "total_issues": counts.get("total_issues"),
        "raw_suffix_files": counts.get("raw_suffix_files"),
        "raw_route_suffix_files": counts.get("raw_route_suffix_files"),
        "oversized_files": counts.get("oversized_files"),
        "json_parse_errors": counts.get("json_parse_errors"),
        "forbidden_fragments": counts.get("forbidden_fragments"),
        "missing": missing,
    }


def _check_workspace_only_artifact_boundaries(root: Path) -> dict[str, Any]:
    from pretrip_fixture_hygiene import find_repo_fixture_workspace_output_artifacts

    missing: list[str] = []
    forbidden_fixture_outputs = find_repo_fixture_workspace_output_artifacts(root)
    missing.extend(
        f"workspace_only_artifact_in_repo_fixture:{path}"
        for path in forbidden_fixture_outputs
    )

    source_expectations = {
        "pretrip_expert_contribution_apply_plan.py": (
            "DEFAULT_APPLY_PLAN_REF = \"outputs/expert_contribution_apply_plan.json\"",
            "DEFAULT_WORKSPACE_APPLY_RESULT_REF = \"outputs/expert_contribution_workspace_apply_result.json\"",
            "workspace_only: Literal[True] = True",
            "repo_fixture_write_allowed: Literal[False] = False",
            "apply_expert_contributions_to_workspace",
            "must be written only to a copied workspace",
        ),
        "pretrip_route_note_reviewed_assumptions.py": (
            "DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF",
            "outputs/route_note_reviewed_assumptions.json",
            "local_workspace_only: Literal[True] = True",
            "runtime_activation_allowed: Literal[False] = False",
            "write_route_note_reviewed_assumptions_for_workspace",
            "must be written only to a copied workspace",
        ),
        "admin_api.py": (
            "/pretrip/projects/{project_id}/route-note-dispositions",
            "persist_to_workspace",
            "workspace_file_mutation_allowed",
            "workspace_route_note_disposition_log_path",
        ),
    }
    present_tokens: dict[str, list[str]] = {}
    missing_tokens: dict[str, list[str]] = {}
    for ref, tokens in source_expectations.items():
        path = root / ref
        if not path.exists():
            missing.append(f"workspace_only_source_missing:{ref}")
            present_tokens[ref] = []
            missing_tokens[ref] = list(tokens)
            continue
        text = path.read_text(encoding="utf-8")
        present_tokens[ref] = [token for token in tokens if token in text]
        missing_tokens[ref] = [token for token in tokens if token not in text]
        missing.extend(
            f"workspace_only_source_token_missing:{ref}:{token}"
            for token in missing_tokens[ref]
        )

    return {
        "ok": not missing,
        "forbidden_fixture_outputs": forbidden_fixture_outputs,
        "forbidden_fixture_output_count": len(forbidden_fixture_outputs),
        "source_files_checked": sorted(source_expectations),
        "present_tokens": present_tokens,
        "missing_tokens": missing_tokens,
        "missing": missing,
    }


def _check_artifact_manifest(project_path: Path) -> dict[str, Any]:
    from pretrip_artifact_manifest import build_pretrip_artifact_manifest

    try:
        manifest = build_pretrip_artifact_manifest(project_path).to_dict()
    except Exception as exc:
        return {
            "ok": False,
            "missing_refs": None,
            "total_artifacts": 0,
            "missing": [f"artifact_manifest_error:{exc}"],
        }

    missing_refs = manifest["counts"]["missing_refs"]
    missing = [] if missing_refs == 0 else [f"artifact_manifest_missing_refs:{missing_refs}"]
    return {
        "ok": not missing,
        "missing_refs": missing_refs,
        "total_artifacts": manifest["counts"]["total_artifacts"],
        "missing": missing,
    }


def _optional_json(project_root: Path, ref: Any) -> Any | None:
    if not isinstance(ref, str) or not ref:
        return None
    path, ref_error = _resolve_project_ref(project_root, ref)
    if ref_error is not None or path is None:
        return None
    if not path.exists():
        return None
    return _load_json(path)


def _status(payload: Any) -> str | None:
    return payload.get("status") if isinstance(payload, dict) else None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_json_text(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _release_check_tiny_gpx() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="scout-release-check" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        "  <trk>\n"
        "    <name>release check route</name>\n"
        "    <trkseg>\n"
        '      <trkpt lat="24.000000" lon="121.000000"><ele>1000</ele></trkpt>\n'
        '      <trkpt lat="24.000100" lon="121.000100"><ele>1001</ele></trkpt>\n'
        "    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    )


def _resolve_project_ref(project_root: Path, ref: str) -> tuple[Path | None, str | None]:
    ref_path = Path(ref)
    if ref_path.is_absolute():
        return None, f"absolute_ref:{ref}"
    candidate = (project_root / ref_path).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        return None, f"escaped_ref:{ref}"
    return candidate, None


def _raw_payload_keys(payload: Any, *, prefix: str = "") -> set[str]:
    raw_key_names = {
        "base64_payload",
        "binary_payload",
        "content",
        "contents",
        "data",
        "grid",
        "payload",
        "pixels",
        "raster",
        "raw_payload",
        "raw_payloads",
        "route_payload",
        "sample_payload",
        "samples",
    }
    if isinstance(payload, dict):
        found: set[str] = set()
        for key, value in payload.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            if key in raw_key_names:
                found.add(key_path)
            found.update(_raw_payload_keys(value, prefix=key_path))
        return found
    if isinstance(payload, list):
        found: set[str] = set()
        for index, item in enumerate(payload):
            found.update(_raw_payload_keys(item, prefix=f"{prefix}[{index}]"))
        return found
    return set()


def _observed_fact_count(payload: Any) -> int:
    if isinstance(payload, dict):
        count = 1 if payload.get("type") == "ObservedFact" else 0
        return count + sum(_observed_fact_count(value) for value in payload.values())
    if isinstance(payload, list):
        return sum(_observed_fact_count(item) for item in payload)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a read-only Phase 4 pre-trip release fixture check."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to check. Defaults to this script's directory.",
    )
    parser.add_argument(
        "--project-json",
        type=Path,
        default=None,
        help="Optional project.json path. Defaults to the Chilai-Nanhua fixture.",
    )
    args = parser.parse_args(argv)

    summary = build_release_check(args.repo_root, project_json_path=args.project_json)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
