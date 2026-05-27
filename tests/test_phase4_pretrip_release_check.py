import json
import shutil
import subprocess
import sys
from pathlib import Path

from phase4_pretrip_release_check import build_release_check
from phase4_pretrip_release_check import _check_admin_ui_local_workspace_write_controls


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "project.json"
)


def test_current_chilai_pretrip_release_check_passes():
    summary = build_release_check(ROOT)

    assert summary["ok"]
    assert summary["failed_checks"] == []
    assert summary["missing_required_artifacts"] == []
    assert summary["checks"]["chilai_project_refs"]["project_id"] == "chilai_nanhua_day1"
    assert summary["checks"]["core_phase4_static_boundaries"]["violation_count"] == 0
    assert summary["checks"]["pretrip_admin_ui"]["view_project_id"] == "chilai_nanhua_day1"
    assert summary["checks"]["pretrip_admin_ui"]["checkpoint_count"] == 110
    assert summary["checks"]["pretrip_admin_ui"]["segment_count"] == 109
    assert summary["checks"]["pretrip_admin_ui"]["raw_payloads_embedded"] is False
    assert summary["checks"]["pretrip_admin_ui"]["ui_write_controls_disabled"] is False
    assert (
        summary["checks"]["pretrip_admin_ui"]["ui_write_controls_enabled_for_alpha"]
        is True
    )
    assert summary["checks"]["admin_map_layer_stack"]["pretrip_imagery_bottom"] is True
    assert summary["checks"]["admin_map_layer_stack"][
        "pretrip_imagery_local_raster_manifest_supported"
    ] is True
    assert summary["checks"]["admin_map_layer_stack"][
        "pretrip_imagery_local_raster_tile_url_template"
    ] == "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    assert summary["checks"]["admin_map_layer_stack"][
        "pretrip_raster_imagery_renderer_present"
    ] is True
    assert summary["checks"]["admin_map_layer_stack"][
        "pretrip_imagery_external_network_required"
    ] is False
    assert summary["checks"]["admin_map_layer_stack"]["pretrip_api_top"] is True
    assert summary["checks"]["admin_map_layer_stack"]["after_action_imagery_bottom"] is True
    assert summary["checks"]["admin_map_layer_stack"][
        "after_action_imagery_local_raster_manifest_supported"
    ] is True
    assert summary["checks"]["admin_map_layer_stack"][
        "after_action_imagery_local_raster_tile_url_template"
    ] == "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    assert summary["checks"]["admin_map_layer_stack"][
        "after_action_raster_imagery_renderer_present"
    ] is True
    assert summary["checks"]["admin_map_layer_stack"][
        "after_action_imagery_external_network_required"
    ] is False
    assert summary["checks"]["admin_map_layer_stack"]["after_action_api_top"] is True
    assert (
        summary["checks"]["admin_map_layer_stack"]["after_action_weather_api_available"]
        is False
    )
    assert summary["checks"]["admin_map_layer_stack"]["external_api_calls_made"] is False
    assert summary["checks"]["admin_map_layer_stack"]["osm_render_mode"] == (
        "osm_raster_tile"
    )
    assert summary["checks"]["admin_map_layer_stack"]["osm_tile_url_template"] == (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    assert (
        summary["checks"]["admin_map_layer_stack"]["osm_external_network_required"]
        is True
    )
    assert summary["checks"]["admin_map_layer_stack"]["page_order_ok"] == {
        "after_action": True,
        "pretrip": True,
    }
    assert summary["checks"]["admin_basemap_renderer"]["source_kind"] == (
        "openstreetmap_tile"
    )
    assert summary["checks"]["admin_basemap_renderer"]["tile_count"] > 0
    assert summary["checks"]["admin_basemap_renderer"]["tile_count"] <= 8
    assert summary["checks"]["admin_basemap_renderer"]["svg_image_count"] == (
        summary["checks"]["admin_basemap_renderer"]["tile_count"]
    )
    assert summary["checks"]["admin_basemap_renderer"]["tile_url_template"] == (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    assert (
        summary["checks"]["admin_basemap_renderer"]["external_network_required"]
        is True
    )
    assert (
        summary["checks"]["admin_basemap_renderer"]["source_has_nonstdlib_network"]
        is False
    )
    assert summary["checks"]["admin_tile_cache_builder"]["status"] == (
        "planned_capacity_ok"
    )
    assert summary["checks"]["admin_tile_cache_builder"]["cache_root"].endswith(
        ".cache/scout-fusion/osm-tiles"
    )
    assert summary["checks"]["admin_tile_cache_builder"]["hardware_deploy_target"] == (
        "scout_hardware"
    )
    assert summary["checks"]["admin_tile_cache_builder"]["bbox_expansion_ratio"] == 0.5
    assert summary["checks"]["admin_tile_cache_builder"]["min_zoom"] == 5
    assert summary["checks"]["admin_tile_cache_builder"]["max_zoom"] == 20
    assert summary["checks"]["admin_tile_cache_builder"]["within_capacity_limit"] is True
    assert summary["checks"]["admin_tile_cache_builder"]["capacity_limit_bytes"] == (
        10 * 1024 * 1024 * 1024
    )
    assert summary["checks"]["admin_tile_cache_builder"]["source_policy_status"] == (
        "public_osm_bulk_download_prohibited"
    )
    assert summary["checks"]["admin_tile_cache_builder"]["bulk_download_allowed"] is False
    assert summary["checks"]["admin_tile_cache_builder"]["public_osm_blocked"] is True
    assert summary["checks"]["admin_tile_cache_builder"]["dry_run_status"] == (
        "dry_run_ready"
    )
    assert (
        summary["checks"]["admin_tile_cache_builder"]["source_has_nonstdlib_network"]
        is False
    )
    assert summary["checks"]["admin_local_raster_source"]["status"] == "geotiff_wgs84"
    assert summary["checks"]["admin_local_raster_source"]["source_kind"] == (
        "local_geotiff"
    )
    assert summary["checks"]["admin_local_raster_source"]["layer_id"] == "imagery"
    assert summary["checks"]["admin_local_raster_source"]["crs_code"] == 4326
    assert summary["checks"]["admin_local_raster_source"]["bbox_wgs84"]
    assert (
        summary["checks"]["admin_local_raster_source"]["repo_fixture_write_allowed"]
        is False
    )
    assert (
        summary["checks"]["admin_local_raster_source"][
            "raw_raster_committed_to_repo_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_local_raster_source"]["external_network_required"]
        is False
    )
    assert (
        summary["checks"]["admin_local_raster_source"]["tile_cutting_performed"]
        is False
    )
    assert summary["checks"]["admin_local_raster_source"]["source_has_network"] is False
    assert summary["checks"]["admin_local_raster_tiles"]["status"] == (
        "planned_capacity_ok"
    )
    assert summary["checks"]["admin_local_raster_tiles"]["project_id"] == (
        "chilai_nanhua_day1"
    )
    assert summary["checks"]["admin_local_raster_tiles"]["layer_id"] == "imagery"
    assert summary["checks"]["admin_local_raster_tiles"]["runtime_tile_url_template"] == (
        "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    )
    assert summary["checks"]["admin_local_raster_tiles"]["within_capacity_limit"] is True
    assert (
        summary["checks"]["admin_local_raster_tiles"]["external_network_required"]
        is False
    )
    assert (
        summary["checks"]["admin_local_raster_tiles"]["downloads_tiles_into_repo"]
        is False
    )
    assert (
        summary["checks"]["admin_local_raster_tiles"][
            "raw_raster_committed_to_repo_allowed"
        ]
        is False
    )
    assert summary["checks"]["admin_local_raster_tiles"]["dry_run_status"] == (
        "dry_run_ready"
    )
    assert summary["checks"]["admin_local_raster_tiles"]["seed_status"] == (
        "seed_complete"
    )
    assert summary["checks"]["admin_local_raster_tiles"]["seed_tiles_written"] == 1
    assert summary["checks"]["admin_local_raster_tiles"]["payload_source"] == (
        "local_cache"
    )
    assert summary["checks"]["admin_local_raster_tiles"]["source_has_network"] is False
    assert summary["checks"]["admin_tile_proxy"]["status"] == "local_proxy_ready"
    assert summary["checks"]["admin_tile_proxy"]["url_template"] == (
        "/admin/tiles/osm/{z}/{x}/{y}.png"
    )
    assert (
        summary["checks"]["admin_tile_proxy"]["external_network_fetch_allowed"]
        is False
    )
    assert summary["checks"]["admin_tile_proxy"]["downloads_tiles_into_repo"] is False
    assert summary["checks"]["admin_tile_proxy"]["fallback_source"] == (
        "offline_fallback"
    )
    assert summary["checks"]["admin_tile_proxy"]["cached_source"] == "local_cache"
    assert summary["checks"]["admin_tile_proxy"]["source_has_nonstdlib_network"] is False
    assert summary["checks"]["admin_weather_overlay"]["status"] == "overlay_ready"
    assert summary["checks"]["admin_weather_overlay"]["layer_id"] == "weather-api"
    assert summary["checks"]["admin_weather_overlay"]["provider_mode"] == (
        "fixture_backed_local_admin_api"
    )
    assert summary["checks"]["admin_weather_overlay"]["external_api_calls_made"] is False
    assert summary["checks"]["admin_weather_overlay"]["raw_payloads_embedded"] is False
    assert summary["checks"]["admin_weather_overlay"]["card_count"] == 3
    assert summary["checks"]["admin_weather_overlay"]["glyph_count"] == 2
    assert summary["checks"]["admin_weather_overlay"]["runtime_disabled_ready"] is False
    assert summary["checks"]["admin_weather_overlay"]["runtime_enabled_ready"] is True
    assert summary["checks"]["admin_weather_overlay"]["runtime_open_meteo_ready"] is True
    assert summary["checks"]["admin_weather_overlay"]["live_provider_mode"] == (
        "live_open_meteo_summary"
    )
    assert (
        summary["checks"]["admin_weather_overlay"]["live_external_api_calls_made"]
        is True
    )
    assert summary["checks"]["phase4_live_demo_loader"]["status"] == "ready_to_start"
    assert summary["checks"]["phase4_live_demo_loader"]["pretrip_admin_url"] == (
        "http://127.0.0.1:9099/admin/pretrip"
    )
    assert (
        summary["checks"]["phase4_live_demo_loader"][
            "open_meteo_live_weather_enabled"
        ]
        is True
    )
    assert (
        summary["checks"]["phase4_live_demo_loader"][
            "local_osm_proxy_external_fetch_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["phase4_live_demo_loader"]["phase1_runtime_mutation_allowed"]
        is False
    )
    assert summary["checks"]["fixture_boundary"]["raw_files"] == []
    assert summary["checks"]["route_comparison"]["classification"] == "comparison_only"
    assert summary["checks"]["route_comparison"]["bbox_overlaps"] is True
    assert summary["checks"]["route_comparison"]["derived_summary_only"] is True
    assert summary["checks"]["route_comparison"]["raw_source_versioned"] is False
    assert summary["checks"]["route_comparison"]["authoritative_for_mission"] is False
    assert summary["checks"]["route_comparison"]["compiled_into_mission_graph"] is False
    assert summary["checks"]["dtm_metadata_only"]["candidate_tile_count"] == 48
    assert summary["checks"]["dtm_metadata_only"]["raw_payload_keys"] == []
    assert summary["checks"]["package_status"]["package_status"] == "candidate"
    assert summary["checks"]["package_status"]["reviewed_package_status"] == "reviewed"
    assert summary["checks"]["mission_graphs"]["graphs"]["candidate"]["checkpoint_count"] == 11
    assert summary["checks"]["mission_graphs"]["graphs"]["reviewed"]["segment_count"] == 10
    assert summary["checks"]["readiness"]["status"] == "ready"
    assert summary["checks"]["timing_measurements"]["measurement_count"] == 18
    assert summary["checks"]["remote_contact_summary"]["audience"] == "remote_contacts"
    assert summary["checks"]["remote_contact_summary"]["readiness_status"] == "ready"
    assert summary["checks"]["remote_contact_summary"]["planned_start"] == "2026-05-03T08:55:35+08:00"
    assert summary["checks"]["remote_contact_summary"]["day1_target_eta"] == "2026-05-03T15:25:35+08:00"
    assert summary["checks"]["remote_contact_summary"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["weather_daylight_evidence"]["status"] == "candidate_only"
    assert summary["checks"]["weather_daylight_evidence"]["validation_status"] == (
        "human_review_required"
    )
    assert summary["checks"]["weather_daylight_evidence"]["confidence"] == "unknown"
    assert summary["checks"]["weather_daylight_evidence"]["staleness"] == "placeholder"
    assert summary["checks"]["weather_daylight_evidence"]["expected_count"] == 1
    assert summary["checks"]["weather_daylight_evidence"]["threshold_policy_id"] == (
        "cwa_style_mountain_weather_daylight_reference.v0"
    )
    assert summary["checks"]["weather_daylight_evidence"]["threshold_policy_status"] == (
        "reference_only"
    )
    assert summary["checks"]["weather_daylight_evidence"]["threshold_policy_configurable"] is True
    assert summary["checks"]["weather_daylight_evidence"]["heavy_rain_1h_mm"] == 40.0
    assert summary["checks"]["weather_daylight_evidence"]["dense_fog_visibility_m"] == 200.0
    assert summary["checks"]["weather_daylight_evidence"]["yellow_avg_wind_mps"] == 10.8
    assert summary["checks"]["weather_daylight_evidence"]["dark_arrival_warning_margin_min"] == 60
    assert summary["checks"]["contour_interpretation_candidates"]["status"] == "candidate"
    assert summary["checks"]["contour_interpretation_candidates"]["candidate_count"] == 2
    assert summary["checks"]["contour_interpretation_candidates"]["expected_count"] == 2
    assert summary["checks"]["contour_interpretation_candidates"]["observed_fact_count"] == 0
    assert summary["checks"]["contour_interpretation_candidates"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["contour_interpretation_candidates"]["admin_review_pending_count"] == 2
    assert (
        summary["checks"]["contour_interpretation_candidates"][
            "accepted_planning_assumption_allowed_count"
        ]
        == 0
    )
    assert summary["checks"]["contour_interpretation_candidates"]["ai_assisted_count"] == 1
    assert summary["checks"]["brain_seed"]["observed_fact_count"] == 0
    assert summary["checks"]["brain_seed"]["model_interpretation_count"] == 6
    assert summary["checks"]["brain_seed"]["non_review_gated_interpretation_count"] == 0
    assert summary["checks"]["planning_skill_audit"]["record_count"] == 5
    assert summary["checks"]["planning_skill_audit"]["node_types"] == ["SkillRunRecord"]
    assert summary["checks"]["planning_skill_audit"]["automatic_writeback_count"] == 0
    assert summary["checks"]["planning_skill_audit"]["observed_fact_count"] == 0
    assert summary["checks"]["poi_readiness_candidates"]["status"] == "candidate_only"
    assert summary["checks"]["poi_readiness_candidates"]["finding_candidate_count"] == 0
    assert summary["checks"]["poi_readiness_candidates"]["warning_candidate_count"] == 0
    assert summary["checks"]["poi_readiness_candidates"]["blocker_candidate_count"] == 0
    assert summary["checks"]["poi_readiness_candidates"]["policy_candidate_count"] == 1
    assert summary["checks"]["poi_readiness_candidates"]["policy_categories"] == [
        "route_corridor_poi_coverage"
    ]
    assert summary["checks"]["poi_readiness_candidates"]["route_corridor_poi_count"] == 1
    assert summary["checks"]["poi_readiness_candidates"]["corridor_distance_m"] == 1000.0
    assert summary["checks"]["poi_readiness_candidates"]["minimum_poi_count"] == 1
    assert summary["checks"]["poi_readiness_candidates"]["policy_severity"] == "warning"
    assert summary["checks"]["poi_readiness_candidates"]["candidate_only"] is True
    assert summary["checks"]["segment_policy_candidates"]["status"] == "candidate_only"
    assert summary["checks"]["segment_policy_candidates"]["candidate_count"] == 10
    assert summary["checks"]["segment_policy_candidates"]["expected_count"] == 10
    assert summary["checks"]["segment_policy_candidates"]["human_review_required_count"] == 10
    assert summary["checks"]["segment_policy_candidates"]["requires_daylight_count"] == 10
    assert summary["checks"]["segment_policy_candidates"]["raw_payload_keys"] == []
    assert summary["checks"]["plan_validation_candidates"]["status"] == "candidate_only"
    assert summary["checks"]["plan_validation_candidates"]["finding_candidate_count"] == 6
    assert summary["checks"]["plan_validation_candidates"]["expected_count"] == 6
    assert summary["checks"]["plan_validation_candidates"]["warning_candidate_count"] == 6
    assert summary["checks"]["plan_validation_candidates"]["blocker_candidate_count"] == 0
    assert summary["checks"]["plan_validation_candidates"]["hard_readiness_status"] == "ready"
    assert summary["checks"]["plan_validation_candidates"]["hard_readiness_mutation_allowed"] is False
    assert summary["checks"]["plan_validation_candidates"]["raw_payloads_embedded"] is False
    assert summary["checks"]["runtime_audit_manifest"]["status"] == "candidate_only"
    assert summary["checks"]["runtime_audit_manifest"]["comparison_axis_count"] == 8
    assert summary["checks"]["runtime_audit_manifest"]["expected_axis_count"] == 8
    assert summary["checks"]["runtime_audit_manifest"]["observed_item_count"] == 0
    assert summary["checks"]["runtime_audit_manifest"]["live_comparison_count"] == 0
    assert summary["checks"]["runtime_audit_manifest"]["raw_payload_count"] == 0
    assert summary["checks"]["runtime_audit_manifest"]["incident_package_imported"] is False
    assert summary["checks"]["runtime_audit_manifest"]["phase1_runtime_mutation_allowed"] is False
    assert summary["checks"]["runtime_handoff_metadata"]["status"] == "candidate_metadata_only"
    assert summary["checks"]["runtime_handoff_metadata"]["route_ref_count"] == 4
    assert summary["checks"]["runtime_handoff_metadata"]["expected_route_ref_count"] == 4
    assert summary["checks"]["runtime_handoff_metadata"]["runtime_write_count"] == 0
    assert summary["checks"]["runtime_handoff_metadata"]["safety_call_count"] == 0
    assert summary["checks"]["runtime_handoff_metadata"]["bridge_mutation_count"] == 0
    assert summary["checks"]["runtime_handoff_metadata"]["phase1_runtime_mutation_allowed"] is False
    assert summary["checks"]["runtime_handoff_metadata"]["final_runtime_write_allowed"] is False
    assert "phase45_departure_runtime_handoff" in summary["checks"]
    assert summary["checks"]["phase45_departure_runtime_handoff"]["profile_count"] == 3
    assert summary["checks"]["phase45_departure_runtime_handoff"]["selected_profile"] == (
        "quick_review.v0"
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"]["quick_review_allowed"] is True
    assert "deep_mountain_out_and_back" in summary["checks"][
        "phase45_departure_runtime_handoff"
    ]["route_classes"]
    assert summary["checks"]["phase45_departure_runtime_handoff"]["hard_blocker_count"] == 8
    assert summary["checks"]["phase45_departure_runtime_handoff"]["departure_gate_status"] == "hold"
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "departure_gate_warning_count"
        ]
        >= 6
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"]["departure_gate_blocker_count"] == 0
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "departure_gate_hard_blocker_count"
        ]
        == 0
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"]["departure_approval_granted"] is False
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_generation_allowed"
        ]
        is False
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"]["runtime_handoff_allowed"] is False
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"]["resolution_count"]
        == summary["checks"]["phase45_departure_runtime_handoff"]["departure_gate_warning_count"]
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolution_warning_override_count"
        ]
        == summary["checks"]["phase45_departure_runtime_handoff"]["departure_gate_warning_count"]
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolution_blocker_attempt_count"
        ]
        == 0
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolution_local_workspace_only"
        ]
        is True
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolution_repo_fixture_write_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolved_departure_gate_status"
        ]
        == "passed"
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolved_departure_approval_granted"
        ]
        is True
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolved_final_mission_graph_generation_allowed"
        ]
        is True
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolved_runtime_handoff_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "resolved_unresolved_warning_count"
        ]
        == 0
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"]["resolved_blocker_count"] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"]["final_mission_graph_status"] == (
        "finalized"
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_checkpoint_count"
        ]
        == 11
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_segment_count"
        ]
        == 10
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_diversion_point_count"
        ]
        == 1
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_route_source"
    ] == "artifact:gpx:chilai_nanhua_day1"
    assert len(
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_sha256"
        ]
    ) == 64
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_runtime_write_count"
        ]
        == 0
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_safety_call_count"
        ]
        == 0
    )
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"][
            "final_mission_graph_phase2_writeback_count"
        ]
        == 0
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_runtime_handoff_performed"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_handoff_mission_graph_version"
    ] == summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_version"
    ]
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_handoff_mission_graph_sha256"
    ] == summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_sha256"
    ]
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_handoff_departure_approval_id"
    ] == summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_departure_approval_id"
    ]
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_handoff_package_sha256"
    ] != "a" * 64
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_handoff_mission_graph_sha256"
    ] != "b" * 64
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_handoff_override_reason_count"
    ] == summary["checks"]["phase45_departure_runtime_handoff"]["resolution_count"]
    assert summary["checks"]["phase45_departure_runtime_handoff"]["runtime_export_status"] == (
        "exported_not_activated"
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_mission_graph_sha256"
    ] == summary["checks"]["phase45_departure_runtime_handoff"][
        "final_mission_graph_sha256"
    ]
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_handoff_id"
    ] == "handoff.phase45.release_check.v0"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_file_write_count"
    ] == 2
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_live_activation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_phase1_live_session_mutation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_route_source_resolution_policy"
    ] == "runtime_target_must_resolve_artifact_refs"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_export_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_artifact_resolution_route_source_ref"
    ] == "artifact:gpx:chilai_nanhua_day1"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_artifact_resolution_count"
    ] == 1
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_artifact_resolution_resolved_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_artifact_resolution_missing_count"
    ] == 1
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_artifact_resolution_raw_payload_copy_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_artifact_resolution_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_status"
    ] == "activation_blocked"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_ready"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_performed"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_blocker_count"
    ] == 1
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_route_point_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_live_activation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_phase1_live_session_mutation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_preflight_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_rejects_blocked_preflight"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_ready_preflight_status"
    ] == "activation_ready"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_ready_preflight_ready"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_ready_preflight_blocker_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_ready_preflight_route_point_count"
    ] == 2
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_status"
    ] == "requested_not_activated"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_requested"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_performed"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_live_activation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_phase1_live_session_mutation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_activation_request_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_status"
    ] == "dry_run_passed"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_passed"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_performed"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_blocker_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_route_point_count"
    ] == 2
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_checkpoint_count"
    ] == 11
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_segment_count"
    ] == 10
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_duplicate_id_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_segment_reference_error_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_mission_graph_runtime_index_count"
    ] == 1
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_safety_runtime_session_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_live_activation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_phase1_live_session_mutation_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_load_dry_run_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_status"
    ] == "loaded_not_observing"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_record_written"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_blocked"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_session_created"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_performed"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_observations_processed_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_incident_package_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_stored_incident_path_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "actual_runtime_activation_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_status"
    ] == "observing"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_record_written"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_session_reused"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_observation_source"
    ] == "release_check_initial_fix"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_observations_processed_count"
    ] == 1
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_incident_package_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_stored_incident_path_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_safety_event_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_recording_policy_profile"
    ] == "medium"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observing_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_status"
    ] == "observing"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_record_written"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_session_reused"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_size"
    ] == 2
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_observations_processed_count"
    ] == 3
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_incident_bridge_enabled"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_observation_batch_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_record_count"
    ] == 3
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_statuses"
    ] == ["stream_blocked", "stream_blocked", "stream_blocked"]
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_requested_from_statuses"
    ] == ["observing", "paused", "ended"]
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_incident_bridge_enabled"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_stream_guard_boundary_ok"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_record_count"
    ] == 4
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_pause_status"
    ] == "paused"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_resume_status"
    ] == "observing"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_end_status"
    ] == "ended"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_abort_status"
    ] == "aborted"
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_end_terminal"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_abort_terminal"
    ] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_observations_processed_count"
    ] == 3
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_safety_api_call_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_phase2_writeback_count"
    ] == 0
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_incident_bridge_enabled"
    ] is False
    assert summary["checks"]["phase45_departure_runtime_handoff"][
        "runtime_lifecycle_boundary_ok"
    ] is True
    assert (
        summary["checks"]["phase45_departure_runtime_handoff"]["unique_finding_id_count"]
        == summary["checks"]["phase45_departure_runtime_handoff"]["finding_count"]
    )
    assert summary["checks"]["phase45_departure_runtime_handoff"]["runtime_handoff_boundary_ok"] is True
    assert summary["checks"]["phase45_departure_runtime_handoff"]["raw_payload_keys"] == []
    assert summary["checks"]["runtime_stream_policy"]["status"] == "policy_ready_not_connected"
    assert summary["checks"]["runtime_stream_policy"]["source_kinds"] == [
        "apple_watch",
        "mobile_phone",
    ]
    assert summary["checks"]["runtime_stream_policy"]["accepted_transports"] == [
        "http_push",
        "websocket",
    ]
    assert summary["checks"]["runtime_stream_policy"]["auth_methods"] == [
        "device_id_scoped_token_hmac_signature"
    ]
    assert summary["checks"]["runtime_stream_policy"]["retry_attempt_limit"] == 5
    assert summary["checks"]["runtime_stream_policy"]["retry_exhausted_fallback"] == (
        "latest_point_only"
    )
    assert summary["checks"]["runtime_stream_policy"]["max_hz"] == 10.0
    assert summary["checks"]["runtime_stream_policy"]["min_interval_ms"] == 100
    assert summary["checks"]["runtime_stream_policy"]["backpressure_enabled"] is True
    assert summary["checks"]["runtime_stream_policy"]["rate_limit_enabled"] is True
    assert (
        summary["checks"]["runtime_stream_policy"][
            "safety_api_allowed_after_phase45_handoff"
        ]
        is True
    )
    assert summary["checks"]["runtime_stream_policy"]["safety_api_endpoint_prefix"] == (
        "/safety"
    )
    assert summary["checks"]["runtime_stream_policy"]["incident_bridge_guard_status"] == (
        "opt_in_required_not_enabled"
    )
    assert (
        summary["checks"]["runtime_stream_policy"]["incident_bridge_enabled_by_default"]
        is False
    )
    assert (
        summary["checks"]["runtime_stream_policy"]["incident_bridge_opt_in_required"]
        is True
    )
    assert summary["checks"]["runtime_stream_policy"]["boundary_ok"] is True
    assert summary["checks"]["runtime_observation_envelope"]["envelope_status"] == (
        "signed_summary_only"
    )
    assert summary["checks"]["runtime_observation_envelope"]["source_kind"] == "apple_watch"
    assert summary["checks"]["runtime_observation_envelope"]["transport"] == "http_push"
    assert summary["checks"]["runtime_observation_envelope"]["token_scope"] == (
        "runtime:observation:write"
    )
    assert summary["checks"]["runtime_observation_envelope"]["sequence_no"] == 1
    assert summary["checks"]["runtime_observation_envelope"]["payload_hash_length"] == 64
    assert summary["checks"]["runtime_observation_envelope"]["signature_algorithm"] == (
        "hmac_sha256"
    )
    assert summary["checks"]["runtime_observation_envelope"]["signature_length"] == 64
    assert summary["checks"]["runtime_observation_envelope"]["signature_verifies"] is True
    assert (
        summary["checks"]["runtime_observation_envelope"]["tampered_payload_rejected"]
        is True
    )
    assert summary["checks"]["runtime_observation_envelope"]["raw_payload_embedded"] is False
    assert summary["checks"]["runtime_observation_envelope"]["calls_safety_api"] is False
    assert (
        summary["checks"]["runtime_observation_envelope"]["connects_device_stream"]
        is False
    )
    assert (
        summary["checks"]["runtime_observation_envelope"]["enables_incident_bridge"]
        is False
    )
    assert summary["checks"]["runtime_observation_envelope"]["writes_phase2_brain"] is False
    assert summary["checks"]["runtime_observation_envelope"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["runtime_input_admission"]["admission_status"] == (
        "admitted_not_forwarded"
    )
    assert summary["checks"]["runtime_input_admission"]["signature_verified"] is True
    assert summary["checks"]["runtime_input_admission"]["policy_matched"] is True
    assert summary["checks"]["runtime_input_admission"]["transport_allowed"] is True
    assert summary["checks"]["runtime_input_admission"]["token_scope_allowed"] is True
    assert summary["checks"]["runtime_input_admission"]["rejected_signature_status"] == (
        "rejected_signature"
    )
    assert summary["checks"]["runtime_input_admission"]["duplicate_status"] == (
        "rejected_duplicate"
    )
    assert summary["checks"]["runtime_input_admission"]["backpressure_status"] == (
        "queued_backpressure"
    )
    assert summary["checks"]["runtime_input_admission"]["disconnected_status"] == (
        "queued_disconnected"
    )
    assert summary["checks"]["runtime_input_admission"]["retry_exhausted_status"] == (
        "latest_point_retained"
    )
    assert summary["checks"]["runtime_input_admission"]["backpressure_queue_depth"] == 1
    assert summary["checks"]["runtime_input_admission"]["disconnected_queue_depth"] == 1
    assert summary["checks"]["runtime_input_admission"]["latest_retained_count"] == 1
    assert summary["checks"]["runtime_input_admission"]["raw_payload_embedded"] is False
    assert summary["checks"]["runtime_input_admission"]["creates_live_endpoint"] is False
    assert summary["checks"]["runtime_input_admission"]["calls_safety_api"] is False
    assert summary["checks"]["runtime_input_admission"]["forwards_to_runtime"] is False
    assert summary["checks"]["runtime_input_admission"]["connects_device_stream"] is False
    assert summary["checks"]["runtime_input_admission"]["enables_incident_bridge"] is False
    assert summary["checks"]["runtime_input_admission"]["writes_phase2_brain"] is False
    assert summary["checks"]["runtime_input_admission"]["safety_api_call_count"] == 0
    assert summary["checks"]["runtime_input_admission"]["runtime_forward_count"] == 0
    assert summary["checks"]["runtime_input_admission"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["safety_observation_admission_api"]["status"] == "accepted"
    assert summary["checks"]["safety_observation_admission_api"]["accepted_status_code"] == 200
    assert summary["checks"]["safety_observation_admission_api"]["duplicate_status_code"] == 409
    assert summary["checks"]["safety_observation_admission_api"]["tampered_status_code"] == 403
    assert summary["checks"]["safety_observation_admission_api"]["admission_status"] == (
        "admitted_not_forwarded"
    )
    assert summary["checks"]["safety_observation_admission_api"]["admission_source_id"] == (
        "runtime_source.apple_watch.v0"
    )
    assert summary["checks"]["safety_observation_admission_api"]["admission_sequence_no"] == 1
    assert summary["checks"]["safety_observation_admission_api"]["observations_accepted"] == 1
    assert (
        summary["checks"]["safety_observation_admission_api"][
            "observations_processed_after_rejections"
        ]
        == 1
    )
    assert summary["checks"]["safety_observation_admission_api"][
        "duplicate_admission_status"
    ] == "rejected_duplicate"
    assert summary["checks"]["safety_observation_admission_api"][
        "tampered_admission_status"
    ] == "rejected_signature"
    assert (
        summary["checks"]["safety_observation_admission_api"][
            "admission_summary_has_raw_payload"
        ]
        is False
    )
    assert summary["checks"]["safety_observation_admission_api"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["safety_observation_admission_api"]["incident_bridge_enabled"] is False
    assert summary["checks"]["safety_observation_admission_api"]["phase2_writeback_count"] == 0
    assert summary["checks"]["server_safety_observation_admission_config"]["status"] == (
        "configured_disabled_by_default"
    )
    assert summary["checks"]["server_safety_observation_admission_config"][
        "disabled_by_default"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "env_secret_supported"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "secret_file_supported"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "missing_secret_rejected"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "short_secret_rejected"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "missing_file_rejected"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "router_passes_config"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "fail_closed_guard"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "env_tokens_present"
    ] is True
    assert summary["checks"]["server_safety_observation_admission_config"][
        "secret_value_exposed"
    ] is False
    assert summary["checks"]["runtime_stream_transport_api"]["status"] == (
        "transport_surface_enabled_when_signed"
    )
    assert summary["checks"]["runtime_stream_transport_api"]["http_push_status_code"] == 200
    assert summary["checks"]["runtime_stream_transport_api"]["http_push_transport_surface"] == (
        "http_push"
    )
    assert summary["checks"]["runtime_stream_transport_api"]["http_push_admission_status"] == (
        "admitted_not_forwarded"
    )
    assert summary["checks"]["runtime_stream_transport_api"]["http_push_observations_processed"] == 1
    assert summary["checks"]["runtime_stream_transport_api"]["websocket_status"] == "accepted"
    assert summary["checks"]["runtime_stream_transport_api"]["websocket_transport_surface"] == (
        "websocket"
    )
    assert summary["checks"]["runtime_stream_transport_api"]["websocket_admission_status"] == (
        "admitted_not_forwarded"
    )
    assert summary["checks"]["runtime_stream_transport_api"]["websocket_observations_processed"] == 1
    assert summary["checks"]["runtime_stream_transport_api"]["mismatch_status_code"] == 422
    assert summary["checks"]["runtime_stream_transport_api"]["mismatch_reason"] == (
        "transport_endpoint_mismatch"
    )
    assert summary["checks"]["runtime_stream_transport_api"]["mismatch_observations_processed"] == 0
    assert summary["checks"]["runtime_stream_transport_api"]["server_mount_guard"] is True
    assert summary["checks"]["runtime_stream_transport_api"]["requires_signed_admission"] is True
    assert summary["checks"]["runtime_stream_transport_api"]["http_push_route_present"] is True
    assert summary["checks"]["runtime_stream_transport_api"]["websocket_route_present"] is True
    assert (
        summary["checks"]["runtime_stream_transport_api"][
            "admission_summary_has_raw_payload"
        ]
        is False
    )
    assert summary["checks"]["runtime_stream_transport_api"]["incident_bridge_enabled"] is False
    assert summary["checks"]["runtime_stream_transport_api"]["phase2_writeback_count"] == 0
    assert summary["checks"]["runtime_stream_telemetry"]["status"] == "telemetry_ready"
    assert summary["checks"]["runtime_stream_telemetry"]["initial_status"] == "idle"
    assert summary["checks"]["runtime_stream_telemetry"]["observed_status"] == "observing"
    assert summary["checks"]["runtime_stream_telemetry"]["accepted_count"] == 1
    assert summary["checks"]["runtime_stream_telemetry"]["rejected_count"] == 1
    assert summary["checks"]["runtime_stream_telemetry"]["queued_count"] == 0
    assert summary["checks"]["runtime_stream_telemetry"]["http_last_admission_status"] == (
        "admitted_not_forwarded"
    )
    assert summary["checks"]["runtime_stream_telemetry"]["http_last_rejection_reason"] == (
        "transport_endpoint_mismatch"
    )
    assert summary["checks"]["runtime_stream_telemetry"]["seen_dedupe_key_count"] == 1
    assert summary["checks"]["runtime_stream_telemetry"]["backpressure_queue_depth"] == 0
    assert summary["checks"]["runtime_stream_telemetry"]["disconnected_queue_depth"] == 0
    assert summary["checks"]["runtime_stream_telemetry"]["websocket_connection_lifecycle"] == [
        "idle",
        "connected",
        "closed",
    ]
    assert summary["checks"]["runtime_stream_telemetry"]["status_route_present"] is True
    assert summary["checks"]["runtime_stream_telemetry"]["store_injected"] is True
    assert summary["checks"]["runtime_stream_telemetry"]["boundary_declared"] is True
    assert summary["checks"]["runtime_stream_telemetry"]["raw_payload_embedded"] is False
    assert summary["checks"]["runtime_stream_telemetry"]["incident_bridge_enabled"] is False
    assert summary["checks"]["runtime_stream_telemetry"]["phase2_writeback_count"] == 0
    assert summary["checks"]["runtime_stream_telemetry"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["runtime_stream_controls"]["status"] == "local_controls_ready"
    assert summary["checks"]["runtime_stream_controls"]["initial_status"] == "observing"
    assert summary["checks"]["runtime_stream_controls"]["pause_status"] == "paused"
    assert summary["checks"]["runtime_stream_controls"]["resume_status"] == "observing"
    assert summary["checks"]["runtime_stream_controls"]["end_status"] == "ended"
    assert summary["checks"]["runtime_stream_controls"]["terminal_resume_rejected"] is True
    assert summary["checks"]["runtime_stream_controls"]["drain_queue_depth_before"] == 2
    assert summary["checks"]["runtime_stream_controls"]["drain_queue_depth_after"] == 0
    assert summary["checks"]["runtime_stream_controls"]["dedupe_keys_preserved_after_drain"] == [
        "dedupe-a"
    ]
    assert summary["checks"]["runtime_stream_controls"]["api_pause_status_code"] == 200
    assert (
        summary["checks"]["runtime_stream_controls"][
            "api_paused_observation_status_code"
        ]
        == 409
    )
    assert summary["checks"]["runtime_stream_controls"]["api_paused_rejection_reason"] == (
        "runtime_stream_paused"
    )
    assert summary["checks"]["runtime_stream_controls"]["api_resume_status_code"] == 200
    assert (
        summary["checks"]["runtime_stream_controls"][
            "api_accepted_after_resume_status_code"
        ]
        == 200
    )
    assert summary["checks"]["runtime_stream_controls"]["api_drain_queue_depth_before"] == 2
    assert summary["checks"]["runtime_stream_controls"]["api_drain_queue_depth_after"] == 0
    assert summary["checks"]["runtime_stream_controls"]["api_end_status_code"] == 200
    assert (
        summary["checks"]["runtime_stream_controls"][
            "api_ended_observation_status_code"
        ]
        == 409
    )
    assert summary["checks"]["runtime_stream_controls"]["api_ended_rejection_reason"] == (
        "runtime_stream_ended"
    )
    assert summary["checks"]["runtime_stream_controls"]["observations_processed"] == 1
    assert summary["checks"]["runtime_stream_controls"]["status_snapshot_control_status"] == (
        "ended"
    )
    assert summary["checks"]["runtime_stream_controls"]["route_tokens_present"] is True
    assert summary["checks"]["runtime_stream_controls"]["store_injected"] is True
    assert summary["checks"]["runtime_stream_controls"]["boundary_declared"] is True
    assert summary["checks"]["runtime_stream_controls"]["raw_payload_embedded"] is False
    assert summary["checks"]["runtime_stream_controls"]["controls_device_hardware"] is False
    assert summary["checks"]["runtime_stream_controls"]["incident_bridge_enabled"] is False
    assert summary["checks"]["runtime_stream_controls"]["phase2_writeback_count"] == 0
    assert summary["checks"]["runtime_stream_controls"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["default_status"] == (
        "opt_in_required"
    )
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["blocked_status"] == "blocked"
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["ready_status"] == (
        "ready_not_enabled"
    )
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["terminal_status"] == "blocked"
    assert (
        summary["checks"]["runtime_incident_bridge_opt_in"][
            "ready_bridge_enable_allowed_after_guard"
        ]
        is True
    )
    assert summary["checks"]["runtime_incident_bridge_opt_in"][
        "remote_notifications_enabled"
    ] is False
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["enable_performed"] is False
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["incident_bridge_enable_count"] == 0
    assert (
        summary["checks"]["runtime_incident_bridge_opt_in"][
            "remote_notification_send_count"
        ]
        == 0
    )
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["phase2_writeback_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_opt_in"]["boundary_ok"] is True
    assert summary["checks"]["runtime_incident_bridge_enablement"]["status"] == (
        "dry_run_ready"
    )
    assert summary["checks"]["runtime_incident_bridge_enablement"]["blocked_status"] == (
        "blocked"
    )
    assert summary["checks"]["runtime_incident_bridge_enablement"]["blocked_reasons"] == [
        "opt_in_guard_not_ready"
    ]
    assert summary["checks"]["runtime_incident_bridge_enablement"]["dry_run_status"] == (
        "dry_run_recorded"
    )
    assert summary["checks"]["runtime_incident_bridge_enablement"]["guard_status"] == (
        "ready_not_enabled"
    )
    assert summary["checks"]["runtime_incident_bridge_enablement"][
        "missing_recipient_reasons"
    ] == ["missing_recipient_refs"]
    assert summary["checks"]["runtime_incident_bridge_enablement"][
        "mock_outbound_message_count"
    ] == 2
    assert summary["checks"]["runtime_incident_bridge_enablement"]["mock_message_states"] == [
        "queued",
        "queued",
    ]
    assert summary["checks"]["runtime_incident_bridge_enablement"]["mock_message_categories"] == [
        "remote_status",
        "remote_status",
    ]
    assert summary["checks"]["runtime_incident_bridge_enablement"]["debug_event_kinds"] == [
        "outbound_message_queued",
        "outbound_message_queued",
    ]
    assert (
        summary["checks"]["runtime_incident_bridge_enablement"][
            "remote_notifications_enabled"
        ]
        is False
    )
    assert summary["checks"]["runtime_incident_bridge_enablement"]["enable_performed"] is False
    assert summary["checks"]["runtime_incident_bridge_enablement"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_incident_bridge_enablement"][
        "remote_notification_send_count"
    ] == 0
    assert summary["checks"]["runtime_incident_bridge_enablement"]["phase2_writeback_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_enablement"]["dry_run_only"] is True
    assert (
        summary["checks"]["runtime_incident_bridge_enablement"][
            "uses_mock_outbound_transport"
        ]
        is True
    )
    assert (
        summary["checks"]["runtime_incident_bridge_enablement"][
            "sends_real_remote_notification"
        ]
        is False
    )
    assert (
        summary["checks"]["runtime_incident_bridge_enablement"][
            "enables_phase1_incident_bridge"
        ]
        is False
    )
    assert summary["checks"]["runtime_incident_bridge_enablement"]["writes_phase2_brain"] is False
    assert summary["checks"]["runtime_incident_bridge_enablement"]["raw_payloads_embedded"] is False
    assert summary["checks"]["runtime_incident_bridge_enablement"]["real_sos_sent_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_enablement"]["real_sms_sent_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_enablement"]["real_satellite_sent_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_enablement"]["source_has_network"] is False
    assert summary["checks"]["runtime_incident_bridge_enablement"]["source_has_phase1_bridge"] is False
    assert summary["checks"]["runtime_incident_bridge_enablement"]["source_has_phase2_store"] is False
    assert summary["checks"]["runtime_incident_bridge_enablement"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["status"] == (
        "mock_delivery_ack_ready"
    )
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["ack_status"] == (
        "ack_recorded"
    )
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["cancel_status"] == (
        "cancel_recorded"
    )
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["rerun_status"] == (
        "rerun_recorded"
    )
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["blocked_status"] == (
        "blocked"
    )
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["blocked_reasons"] == [
        "enablement_record_not_dry_run"
    ]
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"][
        "delivered_cancel_status"
    ] == "blocked"
    assert all(
        reason.startswith("cannot_cancel_mock_delivered_message:")
        for reason in summary["checks"]["runtime_incident_bridge_delivery_ack"][
            "delivered_cancel_reasons"
        ]
    )
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["mock_delivered_count"] == 2
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["cancelled_count"] == 2
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["rerun_message_count"] == 2
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["ack_message_states"] == [
        "mock-delivered",
        "mock-delivered",
    ]
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["cancel_message_states"] == [
        "cancelled",
        "cancelled",
    ]
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["rerun_message_states"] == [
        "queued",
        "queued",
    ]
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["ack_debug_event_states"] == [
        "mock-delivered",
        "mock-delivered",
    ]
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["cancel_debug_event_states"] == [
        "cancelled",
        "cancelled",
    ]
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"][
        "remote_notification_send_count"
    ] == 0
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["phase2_writeback_count"] == 0
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"][
        "remote_notifications_enabled"
    ] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["enable_performed"] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["mock_ack_only"] is True
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"][
        "sends_real_remote_notification"
    ] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"][
        "enables_phase1_incident_bridge"
    ] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["writes_phase2_brain"] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["raw_payloads_embedded"] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["source_has_network"] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["source_has_phase1_bridge"] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["source_has_phase2_store"] is False
    assert summary["checks"]["runtime_incident_bridge_delivery_ack"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["runtime_remote_provider_policy"]["status"] == (
        "policy_ready_not_connected"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["provider_kind"] == (
        "webhook_telegram_like"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["provider_id"] == (
        "remote_provider.webhook_telegram_like.v0"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["auth_method"] == (
        "secret_ref_bearer_token_or_hmac_signature"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["secret_ref_required"] is True
    assert summary["checks"]["runtime_remote_provider_policy"]["token_value_embedded"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["raw_url_embedded"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["allowed_recipient_refs"] == [
        "remote_contact.primary",
        "remote_contact.backup",
    ]
    assert (
        summary["checks"]["runtime_remote_provider_policy"][
            "arbitrary_recipient_input_allowed"
        ]
        is False
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["allowed_message_classes"] == [
        "remote_status",
        "checkin",
        "incident_alert",
    ]
    assert summary["checks"]["runtime_remote_provider_policy"]["blocked_message_classes"] == [
        "sos"
    ]
    assert summary["checks"]["runtime_remote_provider_policy"]["remote_status_decision"] == (
        "allowed"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["checkin_decision"] == (
        "allowed"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["l2_incident_alert_decision"] == (
        "allowed"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["l3_incident_alert_decision"] == (
        "allowed"
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["sos_decision"] == "blocked"
    assert "sos_provider_not_implemented" in summary["checks"][
        "runtime_remote_provider_policy"
    ]["sos_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_policy"][
        "arbitrary_recipient_blocker_reasons"
    ] == ["recipient_ref_not_allowed"]
    assert "missing_noise_reduction_policy_ref" in summary["checks"][
        "runtime_remote_provider_policy"
    ]["missing_noise_blocker_reasons"]
    assert (
        summary["checks"]["runtime_remote_provider_policy"][
            "provider_cancellation_supported"
        ]
        is False
    )
    assert summary["checks"]["runtime_remote_provider_policy"][
        "followup_correction_allowed"
    ] is True
    assert summary["checks"]["runtime_remote_provider_policy"]["manual_retry_required"] is True
    assert summary["checks"]["runtime_remote_provider_policy"]["auto_escalate_provider"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["auto_sos_escalation"] is False
    assert summary["checks"]["runtime_remote_provider_policy"][
        "incident_alert_window_seconds"
    ] == 600
    assert summary["checks"]["runtime_remote_provider_policy"][
        "remote_status_window_seconds"
    ] == 300
    assert summary["checks"]["runtime_remote_provider_policy"]["audit_required_fields"] == [
        "provider_id",
        "recipient_ref",
        "message_class",
        "body_preview",
        "payload_hash",
        "send_status",
        "operator_id",
        "correlation_refs",
    ]
    assert summary["checks"]["runtime_remote_provider_policy"]["policy_only"] is True
    assert summary["checks"]["runtime_remote_provider_policy"]["creates_provider_adapter"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["sends_network_request"] is False
    assert (
        summary["checks"]["runtime_remote_provider_policy"][
            "sends_real_remote_notification"
        ]
        is False
    )
    assert (
        summary["checks"]["runtime_remote_provider_policy"][
            "enables_phase1_incident_bridge"
        ]
        is False
    )
    assert summary["checks"]["runtime_remote_provider_policy"]["writes_phase2_brain"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["raw_payloads_embedded"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["source_has_network"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["source_has_phase1_bridge"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["source_has_phase2_store"] is False
    assert summary["checks"]["runtime_remote_provider_policy"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["runtime_remote_provider_config_preflight"]["status"] == (
        "provider_config_ready"
    )
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "provider_config_ready"
    ] is True
    assert summary["checks"]["runtime_remote_provider_config_preflight"]["provider_kind"] == (
        "webhook_telegram_like"
    )
    assert summary["checks"]["runtime_remote_provider_config_preflight"]["provider_id"] == (
        "remote_provider.webhook_telegram_like.v0"
    )
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "endpoint_url_secret_ref"
    ] == "env:SCOUT_REMOTE_WEBHOOK_URL"
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "auth_secret_ref"
    ] == "env:SCOUT_REMOTE_WEBHOOK_TOKEN"
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "signature_secret_ref"
    ] == "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET"
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "required_secret_refs"
    ] == [
        "env:SCOUT_REMOTE_WEBHOOK_URL",
        "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
        "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET",
        "env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
        "env:SCOUT_REMOTE_BACKUP_TARGET_REF",
    ]
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "missing_secrets_status"
    ] == "provider_config_blocked"
    assert "env:SCOUT_REMOTE_PRIMARY_TARGET_REF" in summary["checks"][
        "runtime_remote_provider_config_preflight"
    ]["missing_secret_refs"]
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "mismatch_status"
    ] == "provider_config_blocked"
    assert "message_class_not_allowed:sos" in summary["checks"][
        "runtime_remote_provider_config_preflight"
    ]["mismatch_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "secret_values_loaded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "endpoint_url_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "token_value_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"]["config_only"] is True
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "creates_provider_adapter"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "sends_network_request"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "sends_real_remote_notification"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "enables_phase1_incident_bridge"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "writes_phase2_brain"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"]["send_performed"] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "remote_notification_send_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "phase2_writeback_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "source_has_network"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "source_has_phase1_bridge"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "source_has_phase2_store"
    ] is False
    assert summary["checks"]["runtime_remote_provider_config_preflight"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["status"] == (
        "payload_ready_not_sent"
    )
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["payload_ready"] is True
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["provider_kind"] == (
        "webhook_telegram_like"
    )
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["provider_id"] == (
        "remote_provider.webhook_telegram_like.v0"
    )
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "delivery_target_secret_ref"
    ] == "env:SCOUT_REMOTE_PRIMARY_TARGET_REF"
    assert len(summary["checks"]["runtime_remote_provider_payload_composer"]["payload_hash"]) == 64
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "incident_alert_status"
    ] == "payload_ready_not_sent"
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "incident_alert_delivery_target_secret_ref"
    ] == "env:SCOUT_REMOTE_BACKUP_TARGET_REF"
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "incident_alert_level"
    ] == "L2_CONCERN"
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "incident_alert_noise_reduction_policy_ref"
    ] == "noise_reduction_policy.family_low_noise.v0"
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "missing_noise_status"
    ] == "payload_blocked"
    assert "missing_noise_reduction_policy_ref" in summary["checks"][
        "runtime_remote_provider_payload_composer"
    ]["missing_noise_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "preflight_blocked_status"
    ] == "payload_blocked"
    assert "provider_config_preflight_not_ready" in summary["checks"][
        "runtime_remote_provider_payload_composer"
    ]["preflight_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["sos_status"] == (
        "payload_blocked"
    )
    assert "sos_provider_not_implemented" in summary["checks"][
        "runtime_remote_provider_payload_composer"
    ]["sos_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "arbitrary_recipient_status"
    ] == "payload_blocked"
    assert "recipient_ref_not_allowed" in summary["checks"][
        "runtime_remote_provider_payload_composer"
    ]["arbitrary_recipient_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "long_body_preview_length"
    ] <= 240
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "long_body_preview_has_newline"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["summary_only"] is True
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "raw_payloads_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "secret_values_loaded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "endpoint_url_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "token_value_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"]["send_performed"] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "remote_notification_send_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "phase2_writeback_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "source_has_network"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "source_has_phase1_bridge"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "source_has_phase2_store"
    ] is False
    assert summary["checks"]["runtime_remote_provider_payload_composer"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_send_queue"]["status"] == (
        "queued_not_sent"
    )
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "send_intent_queued"
    ] is True
    assert summary["checks"]["runtime_remote_provider_send_queue"]["provider_kind"] == (
        "webhook_telegram_like"
    )
    assert summary["checks"]["runtime_remote_provider_send_queue"]["provider_id"] == (
        "remote_provider.webhook_telegram_like.v0"
    )
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "delivery_target_secret_ref"
    ] == "env:SCOUT_REMOTE_PRIMARY_TARGET_REF"
    assert len(summary["checks"]["runtime_remote_provider_send_queue"]["payload_hash"]) == 64
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "provider_adapter_required_before_send"
    ] is True
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "manual_send_authorization_required"
    ] is True
    assert summary["checks"]["runtime_remote_provider_send_queue"]["summary_only"] is True
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "raw_payloads_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "secret_values_loaded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "endpoint_url_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "token_value_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "creates_provider_adapter"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "sends_network_request"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"]["send_performed"] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "remote_notification_send_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "phase2_writeback_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_send_queue"]["blocked_status"] == (
        "send_intent_blocked"
    )
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "blocked_send_intent_queued"
    ] is False
    assert "payload_not_ready" in summary["checks"]["runtime_remote_provider_send_queue"][
        "blocked_reasons"
    ]
    assert "sos_provider_not_implemented" in summary["checks"][
        "runtime_remote_provider_send_queue"
    ]["blocked_reasons"]
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "source_has_network"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "source_has_phase1_bridge"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "source_has_phase2_store"
    ] is False
    assert summary["checks"]["runtime_remote_provider_send_queue"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_adapter"]["status"] == "sent"
    assert summary["checks"]["runtime_remote_provider_live_adapter"]["default_status"] == (
        "live_send_blocked"
    )
    assert "provider_adapter_not_enabled" in summary["checks"][
        "runtime_remote_provider_live_adapter"
    ]["default_blocker_reasons"]
    assert "live_network_send_not_enabled" in summary["checks"][
        "runtime_remote_provider_live_adapter"
    ]["default_blocker_reasons"]
    assert "manual_send_authorization_missing" in summary["checks"][
        "runtime_remote_provider_live_adapter"
    ]["default_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "blocked_intent_status"
    ] == "live_send_blocked"
    assert "send_intent_not_queued" in summary["checks"][
        "runtime_remote_provider_live_adapter"
    ]["blocked_intent_reasons"]
    assert summary["checks"]["runtime_remote_provider_live_adapter"]["provider_kind"] == (
        "webhook_telegram_like"
    )
    assert summary["checks"]["runtime_remote_provider_live_adapter"]["provider_id"] == (
        "remote_provider.webhook_telegram_like.v0"
    )
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "delivery_target_secret_ref"
    ] == "keychain:scout/primary-target"
    assert len(summary["checks"]["runtime_remote_provider_live_adapter"]["payload_hash"]) == 64
    assert len(summary["checks"]["runtime_remote_provider_live_adapter"]["request_body_hash"]) == 64
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "live_network_send_attempted"
    ] is True
    assert summary["checks"]["runtime_remote_provider_live_adapter"]["send_performed"] is True
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "remote_notification_send_count"
    ] == 1
    assert summary["checks"]["runtime_remote_provider_live_adapter"]["http_status_code"] == 200
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "provider_message_ref"
    ] == "provider-message-001"
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "secret_ref_schemes"
    ] == ["env", "file", "keychain", "keychain"]
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "secret_values_loaded"
    ] is True
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "raw_secret_values_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "endpoint_url_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "token_value_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "creates_provider_adapter"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "sends_network_request"
    ] is True
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "phase2_writeback_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "source_has_stdlib_network"
    ] is True
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "source_has_nonstdlib_network"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "source_has_phase1_bridge"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "source_has_phase2_store"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_adapter"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_send_cli"]["status"] == "sent"
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "default_exit_code"
    ] == 2
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "default_status"
    ] == "live_send_blocked"
    assert "provider_adapter_not_enabled" in summary["checks"][
        "runtime_remote_provider_live_send_cli"
    ]["default_blocker_reasons"]
    assert "live_network_send_not_enabled" in summary["checks"][
        "runtime_remote_provider_live_send_cli"
    ]["default_blocker_reasons"]
    assert "manual_send_authorization_missing" in summary["checks"][
        "runtime_remote_provider_live_send_cli"
    ]["default_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "default_live_network_send_attempted"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "sent_exit_code"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "sent_status"
    ] == "sent"
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "sent_http_status_code"
    ] == 202
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "provider_message_ref"
    ] == "provider-message-cli-001"
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "sent_live_network_send_attempted"
    ] is True
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "sent_send_performed"
    ] is True
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "sent_remote_notification_send_count"
    ] == 1
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "transport_call_count"
    ] == 1
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "missing_exit_code"
    ] == 2
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "missing_status"
    ] == "operator_request_blocked"
    assert "missing_config_artifact" in summary["checks"][
        "runtime_remote_provider_live_send_cli"
    ]["missing_blocker_reasons"]
    assert "missing_send_intent_artifact" in summary["checks"][
        "runtime_remote_provider_live_send_cli"
    ]["missing_blocker_reasons"]
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "raw_secret_values_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "endpoint_url_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "token_value_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "phase2_writeback_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "source_has_phase1_bridge"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "source_has_phase2_store"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "source_has_nonstdlib_network"
    ] is False
    assert summary["checks"]["runtime_remote_provider_live_send_cli"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_demo_harness"][
        "response_status"
    ] == 202
    assert summary["checks"]["runtime_remote_provider_demo_harness"][
        "capture_count"
    ] == 1
    assert summary["checks"]["runtime_remote_provider_demo_harness"][
        "captured_method"
    ] == "POST"
    assert summary["checks"]["runtime_remote_provider_demo_harness"][
        "captured_path"
    ] == "/capture"
    assert summary["checks"]["runtime_remote_provider_demo_harness"][
        "source_has_stdlib_http_server"
    ] is True
    assert summary["checks"]["runtime_remote_provider_demo_harness"][
        "source_has_nonstdlib_network"
    ] is False
    assert summary["checks"]["runtime_remote_provider_demo_bundle"]["status"] == "ready"
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "localhost_only"
    ] is True
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "external_network_allowed"
    ] is False
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "sent_status"
    ] == "sent"
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "sent_http_status_code"
    ] == 202
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "remote_notification_send_count"
    ] == 1
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "incident_bridge_enable_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "phase2_writeback_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "capture_count"
    ] == 1
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "non_localhost_url_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_demo_bundle"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "blocked_status"
    ] == "blocked_missing_secret_refs"
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "ready_status"
    ] == "ready_requires_manual_send"
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "blocked_missing_secret_count"
    ] == 5
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "ready_missing_secret_count"
    ] == 0
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "blocked_send_intent_status"
    ] == "send_intent_blocked"
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "ready_send_intent_status"
    ] == "queued_not_sent"
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "external_network_allowed"
    ] is True
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "localhost_only"
    ] is False
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "secret_values_embedded"
    ] is False
    assert summary["checks"]["runtime_remote_provider_external_demo_bundle"][
        "forbidden_fragment_count"
    ] == 0
    assert summary["checks"]["after_action_next_plan_candidates"]["status"] == "candidate_only"
    assert summary["checks"]["after_action_next_plan_candidates"]["candidate_count"] == 3
    assert summary["checks"]["after_action_next_plan_candidates"]["expected_count"] == 3
    assert summary["checks"]["after_action_next_plan_candidates"]["source_case_id"] == (
        "scout_260512_field_golden"
    )
    assert summary["checks"]["after_action_next_plan_candidates"]["incident_package_ref_count"] == 0
    assert summary["checks"]["after_action_next_plan_candidates"]["observed_fact_writeback_allowed"] is False
    assert summary["checks"]["after_action_next_plan_candidates"]["historical_evidence_mutation_allowed"] is False
    assert summary["checks"]["after_action_next_plan_candidates"]["raw_payloads_embedded"] is False
    assert summary["checks"]["review_draft_log"]["status"] == "draft_only"
    assert summary["checks"]["review_draft_log"]["action_count"] == 3
    assert summary["checks"]["review_draft_log"]["category_counts"] == {
        "contour": 1,
        "poi_readiness": 1,
        "segment_policy": 1,
    }
    assert summary["checks"]["review_draft_log"]["decisions_recorded"] is False
    assert summary["checks"]["review_draft_log"]["source_mutation_allowed"] is False
    assert summary["checks"]["review_draft_log"]["package_mutation_allowed"] is False
    assert summary["checks"]["review_draft_log"]["review_log_mutation_allowed"] is False
    assert summary["checks"]["review_draft_log"]["runtime_mutation_allowed"] is False
    assert summary["checks"]["review_draft_log"]["phase1_runtime_mutation_allowed"] is False
    assert summary["checks"]["review_draft_log"]["phase2_writeback_allowed"] is False
    assert summary["checks"]["review_draft_log"]["admin_api_integration"] is False
    assert summary["checks"]["review_draft_log"]["raw_payloads_embedded"] is False
    assert summary["checks"]["review_decision_log"]["action_count"] == 3
    assert summary["checks"]["review_decision_log"]["accepted_count"] == 1
    assert summary["checks"]["review_decision_log"]["corrected_count"] == 1
    assert summary["checks"]["review_decision_log"]["rejected_count"] == 1
    assert summary["checks"]["review_decision_log"]["runtime_mutation_count"] == 0
    assert summary["checks"]["review_decision_log"]["package_mutation_count"] == 0
    assert summary["checks"]["review_decision_log"]["source_mutation_allowed"] is False
    assert summary["checks"]["review_decision_log"]["package_mutation_allowed"] is False
    assert summary["checks"]["review_decision_log"]["runtime_mutation_allowed"] is False
    assert summary["checks"]["review_decision_log"]["phase1_runtime_mutation_allowed"] is False
    assert summary["checks"]["review_decision_log"]["phase2_writeback_allowed"] is False
    assert summary["checks"]["review_decision_log"]["admin_api_integration"] is False
    assert summary["checks"]["review_decision_log"]["compiles_mission_graph"] is False
    assert summary["checks"]["review_decision_log"]["raw_payloads_embedded"] is False
    assert summary["checks"]["review_decision_apply_plan"]["decision_count"] == 3
    assert summary["checks"]["review_decision_apply_plan"]["accepted_count"] == 1
    assert summary["checks"]["review_decision_apply_plan"]["corrected_count"] == 1
    assert summary["checks"]["review_decision_apply_plan"]["rejected_count"] == 1
    assert summary["checks"]["review_decision_apply_plan"]["package_candidate_apply_count"] == 0
    assert summary["checks"]["review_decision_apply_plan"]["runtime_mutation_count"] == 0
    assert summary["checks"]["review_decision_apply_plan"]["would_apply_only"] is True
    assert summary["checks"]["review_decision_apply_plan"]["source_mutation_allowed"] is False
    assert summary["checks"]["review_decision_apply_plan"]["package_mutation_allowed"] is False
    assert summary["checks"]["review_decision_apply_plan"]["runtime_mutation_allowed"] is False
    assert summary["checks"]["review_decision_apply_plan"]["phase1_runtime_mutation_allowed"] is False
    assert summary["checks"]["review_decision_apply_plan"]["phase2_writeback_allowed"] is False
    assert summary["checks"]["review_decision_apply_plan"]["compiles_mission_graph"] is False
    assert summary["checks"]["review_decision_apply_plan"]["raw_payloads_embedded"] is False
    assert "admin_workspace_persistence_contract" in summary["checks"]
    assert summary["checks"]["admin_workspace_persistence_contract"]["preview_default"] is True
    assert summary["checks"]["admin_workspace_persistence_contract"]["requires_workspace_root"] is True
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "repo_fixture_action_count"
        ]
        == 3
    )
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "phase2_writeback_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "external_api_calls_made"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "duplicate_candidate_ref_guard"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "admin_project_view_workspace_overlay"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_persistence_contract"][
            "forbidden_source_fragment_count"
        ]
        == 0
    )
    assert "admin_workspace_project_creation_contract" in summary["checks"]
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "helper_has_raw_source_suffixes"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "helper_has_copy_pretrip_project_workspace"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "helper_rejects_raw_sources"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "helper_metadata_only_suffixes"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "admin_endpoint_present"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "admin_missing_tokens"
        ]
        == []
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "forbidden_source_fragment_count"
        ]
        == 0
    )
    assert (
        summary["checks"]["admin_workspace_project_creation_contract"][
            "repo_fixture_mutation_allowed"
        ]
        is False
    )
    assert "admin_ui_local_workspace_write_controls" in summary["checks"]
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "write_slice_landed"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "expected_route_tokens_present"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "expected_function_tokens_present"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "expected_persistence_tokens_present"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "expected_reject_tokens_present"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "expected_correct_tokens_present"
        ]
        is True
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "forbidden_token_count"
        ]
        == 0
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "phase2_writeback_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "crawler_or_external_import_write_allowed"
        ]
        is False
    )
    assert (
        summary["checks"]["admin_ui_local_workspace_write_controls"][
            "repo_fixture_mutation_allowed"
        ]
        is False
    )
    assert summary["checks"]["external_import_queue"]["status"] == "pending_human_review"
    assert summary["checks"]["external_import_queue"]["request_count"] == 3
    assert summary["checks"]["external_import_queue"]["pending_count"] == 3
    assert summary["checks"]["external_import_queue"]["crawler_enabled_count"] == 0
    assert summary["checks"]["external_import_queue"]["network_call_count"] == 0
    assert summary["checks"]["external_import_queue"]["observed_fact_count"] == 0
    assert summary["checks"]["external_import_queue"]["raw_payloads_embedded"] is False
    assert summary["checks"]["external_import_queue"]["no_network"] is True
    assert summary["checks"]["external_import_queue"]["no_crawler"] is True
    assert summary["checks"]["external_import_queue"]["fetches_remote_content"] is False
    assert summary["checks"]["external_import_queue"]["produces_observed_facts"] is False
    assert summary["checks"]["external_import_queue"]["produces_derived_measurements"] is False
    assert summary["checks"]["external_import_queue"]["source_ids"] == [
        "source.joyhike.main_site",
        "source.joyhike.blog",
        "source.ptt.sunriver_timing",
    ]
    assert summary["checks"]["route_note_candidates"]["status"] == "candidate_only"
    assert summary["checks"]["route_note_candidates"]["waypoint_count"] == 81
    assert summary["checks"]["route_note_candidates"]["note_candidate_count"] == 81
    assert summary["checks"]["route_note_candidates"]["hazard_hint_count"] == 3
    assert summary["checks"]["route_note_candidates"]["route_condition_hint_count"] == 20
    assert summary["checks"]["route_note_candidates"]["potential_ln_signal_count"] == 23
    assert summary["checks"]["route_note_candidates"]["observed_fact_count"] == 0
    assert summary["checks"]["route_note_candidates"]["raw_payload_count"] == 0
    assert summary["checks"]["route_note_candidates"]["candidate_only"] is True
    assert summary["checks"]["route_note_candidates"]["scout_interpretation_only"] is True
    assert (
        summary["checks"]["route_note_candidates"][
            "requires_human_review_before_ln_upgrade"
        ]
        is True
    )
    assert summary["checks"]["route_note_candidates"]["observed_fact_allowed"] is False
    assert summary["checks"]["route_note_candidates"]["raw_gpx_embedded"] is False
    assert summary["checks"]["route_note_candidates"]["runtime_mutation_allowed"] is False
    assert summary["checks"]["route_note_candidates"]["phase2_writeback_allowed"] is False
    assert summary["checks"]["route_note_ln_proposals"]["status"] == "candidate_only"
    assert summary["checks"]["route_note_ln_proposals"]["proposal_count"] == 23
    assert (
        summary["checks"]["route_note_ln_proposals"][
            "hint_coverage_proposal_count"
        ]
        == 20
    )
    assert (
        summary["checks"]["route_note_ln_proposals"][
            "warning_coverage_proposal_count"
        ]
        == 3
    )
    assert (
        summary["checks"]["route_note_ln_proposals"][
            "human_review_required_count"
        ]
        == 23
    )
    assert summary["checks"]["route_note_ln_proposals"]["observed_fact_count"] == 0
    assert summary["checks"]["route_note_ln_proposals"]["runtime_mutation_count"] == 0
    assert (
        summary["checks"]["route_note_ln_proposals"][
            "human_review_required_before_use"
        ]
        is True
    )
    assert (
        summary["checks"]["route_note_ln_proposals"][
            "crawler_or_network_source_allowed"
        ]
        is False
    )
    assert summary["checks"]["route_note_review_options"]["status"] == (
        "candidate_only_draft_only"
    )
    assert summary["checks"]["route_note_review_options"]["review_option_count"] == 23
    assert summary["checks"]["route_note_review_options"]["candidate_only_count"] == 23
    assert summary["checks"]["route_note_review_options"]["draft_only_count"] == 23
    assert summary["checks"]["route_note_review_options"]["decision_recorded_count"] == 0
    assert summary["checks"]["route_note_review_options"]["runtime_mutation_count"] == 0
    assert summary["checks"]["route_note_review_options"]["candidate_only"] is True
    assert summary["checks"]["route_note_review_options"]["draft_only"] is True
    assert summary["checks"]["route_note_review_options"]["review_options_only"] is True
    assert (
        summary["checks"]["route_note_review_options"][
            "decision_recording_allowed"
        ]
        is False
    )
    assert summary["checks"]["route_note_review_options"]["allowed_admin_dispositions"] == [
        "promote_hint",
        "promote_warning",
        "ignore",
        "field_verify",
    ]
    assert summary["checks"]["expert_contribution_log"]["status"] == (
        "candidate_memory_seed_only"
    )
    assert summary["checks"]["expert_contribution_log"]["contribution_count"] == 3
    assert summary["checks"]["expert_contribution_log"]["candidate_set_edit_count"] == 2
    assert summary["checks"]["expert_contribution_log"]["external_import_edit_count"] == 1
    assert (
        summary["checks"]["expert_contribution_log"]["memory_seed_candidate_count"]
        == 3
    )
    assert summary["checks"]["expert_contribution_log"]["brain_writeback_count"] == 0
    assert summary["checks"]["expert_contribution_log"]["raw_payload_count"] == 0
    assert (
        summary["checks"]["expert_contribution_log"]["candidate_set_edit_intent_only"]
        is True
    )
    assert (
        summary["checks"]["expert_contribution_log"]["external_import_edit_intent_only"]
        is True
    )
    assert (
        summary["checks"]["expert_contribution_log"]["requires_human_review_before_apply"]
        is True
    )
    assert (
        summary["checks"]["expert_contribution_log"]["memory_seed_candidate_only"]
        is True
    )
    assert summary["checks"]["expert_contribution_log"]["brain_writeback_allowed"] is False
    assert summary["checks"]["expert_contribution_log"]["package_mutation_allowed"] is False
    assert (
        summary["checks"]["expert_contribution_log"]["mission_graph_mutation_allowed"]
        is False
    )
    assert summary["checks"]["expert_contribution_log"]["runtime_mutation_allowed"] is False
    assert (
        summary["checks"]["expert_contribution_log"]["phase1_runtime_mutation_allowed"]
        is False
    )
    assert summary["checks"]["expert_contribution_log"]["phase2_writeback_allowed"] is False
    assert summary["checks"]["expert_contribution_log"]["external_api_calls_made"] is False
    assert summary["checks"]["expert_contribution_log"]["raw_payloads_embedded"] is False
    assert summary["checks"]["expert_contribution_log"]["operations"] == [
        "add_candidate",
        "update_candidate",
        "add_import_request",
    ]
    assert "workspace_only_artifact_boundaries" in summary["checks"]
    assert (
        summary["checks"]["workspace_only_artifact_boundaries"][
            "forbidden_fixture_output_count"
        ]
        == 0
    )
    assert (
        summary["checks"]["workspace_only_artifact_boundaries"][
            "forbidden_fixture_outputs"
        ]
        == []
    )
    assert summary["checks"]["workspace_only_artifact_boundaries"]["missing_tokens"] == {
        "admin_api.py": [],
        "pretrip_expert_contribution_apply_plan.py": [],
        "pretrip_route_note_reviewed_assumptions.py": [],
    }
    assert summary["checks"]["resource_plan"]["status"] == "candidate_only"
    assert summary["checks"]["resource_plan"]["device_count"] == 4
    assert summary["checks"]["resource_plan"]["equipment_count"] == 4
    assert summary["checks"]["resource_plan"]["external_api_calls_made"] is False
    assert summary["checks"]["resource_plan"]["raw_payloads_embedded"] is False
    assert summary["checks"]["resource_plan"]["hard_readiness_mutation_allowed"] is False
    assert summary["checks"]["resource_plan"]["blocks_existing_eta_or_readiness"] is False
    assert summary["checks"]["departure_bundle_manifest"]["status"] == "frozen_candidate"
    assert summary["checks"]["departure_bundle_manifest"]["required_ref_count"] == 24
    assert summary["checks"]["departure_bundle_manifest"]["audit_ref_count"] == 6
    assert summary["checks"]["departure_bundle_manifest"]["review_draft_log_ref_count"] == 1
    assert summary["checks"]["departure_bundle_manifest"]["review_draft_log_statuses"] == [
        "draft_only"
    ]
    assert summary["checks"]["departure_bundle_manifest"]["not_departure_approval"] is True
    assert summary["checks"]["departure_bundle_manifest"]["phase1_runtime_mutation_allowed"] is False
    assert summary["checks"]["scout260512_pretrip_regression"]["fixture_kind"] == (
        "field-data-to-fixtures-regression"
    )
    assert summary["checks"]["scout260512_pretrip_regression"]["primary_mountain_calibration"] is False
    assert summary["checks"]["scout260512_pretrip_regression"]["compiled_into_mountain_calibration"] is False
    assert summary["checks"]["scout260512_pretrip_regression"]["raw_files"] == []
    assert summary["checks"]["scout260512_pretrip_regression"]["forbidden_fragment_count"] == 0
    assert summary["checks"]["pretrip_implementation_status"]["implemented_milestones"] == [
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
        "4.5AP",
        "4.5AQ",
        "4.5AR",
        "4.5AS",
    ]
    assert summary["checks"]["pretrip_implementation_status"]["not_started_milestones"] == []
    assert summary["checks"]["pretrip_implementation_status"]["alpha_workable_mode"] is True
    assert summary["checks"]["pretrip_implementation_status"]["runtime_mutation_allowed"] is True
    assert summary["checks"]["pretrip_implementation_status"]["runtime_export_write_allowed"] is True
    assert (
        summary["checks"]["pretrip_implementation_status"][
            "runtime_activation_allowed_for_alpha"
        ]
        is True
    )
    assert (
        summary["checks"]["pretrip_implementation_status"][
            "runtime_operator_confirmation_required"
        ]
        is True
    )
    assert summary["checks"]["pretrip_implementation_status"]["ui_scope_included"] is True
    assert summary["checks"]["pretrip_implementation_status"]["ui_scope"] == (
        "alpha_workable_admin"
    )
    assert summary["checks"]["pretrip_implementation_status"]["focused_suite_test_count"] == 94
    assert "source.joyhike.main_site" in summary["checks"]["pretrip_source_registry"]["source_ids"]
    assert "source.joyhike.blog" in summary["checks"]["pretrip_source_registry"]["source_ids"]
    assert "source.ptt.sunriver_timing" in summary["checks"]["pretrip_source_registry"]["source_ids"]
    assert summary["checks"]["pretrip_source_registry"]["ptt_calibration_scope"] == (
        "calibration_inputs_only"
    )
    assert summary["checks"]["pretrip_decision_register"]["resolved_count"] == 16
    assert summary["checks"]["pretrip_decision_register"]["open_question_count"] == 0
    assert summary["checks"]["pretrip_decision_register"]["alpha_workable_mode"] is True
    assert summary["checks"]["pretrip_decision_register"]["no_network"] is False
    assert summary["checks"]["pretrip_decision_register"]["no_crawler"] is False
    assert summary["checks"]["pretrip_decision_register"]["ui_scope"] == (
        "alpha_workable_admin"
    )
    assert summary["checks"]["pretrip_decision_register"]["no_runtime_effects"] is False
    assert (
        summary["checks"]["pretrip_decision_register"][
            "runtime_operator_confirmation_required"
        ]
        is True
    )
    assert summary["checks"]["pretrip_fixture_hygiene"]["total_issues"] == 0
    assert summary["checks"]["pretrip_fixture_hygiene"]["raw_suffix_files"] == 0
    assert summary["checks"]["pretrip_fixture_hygiene"]["raw_route_suffix_files"] == 0
    assert summary["checks"]["pretrip_fixture_hygiene"]["oversized_files"] == 0
    assert summary["checks"]["pretrip_fixture_hygiene"]["forbidden_fragments"] == 0
    assert (
        summary["checks"]["fixture_boundary"]["large_evidence_allowed_for_alpha"]
        is True
    )
    assert summary["checks"]["artifact_manifest"]["missing_refs"] == 0


def test_cli_prints_compact_json():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "phase4_pretrip_release_check.py"),
            "--repo-root",
            str(ROOT),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "\n  " not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_admin_ui_write_controls_pass_when_local_workspace_slice_lands(tmp_path):
    page_dir = tmp_path / "docs" / "admin"
    page_dir.mkdir(parents=True)
    page = page_dir / "phase4-pretrip-planning.html"
    page.write_text(
        """
        <script>
          async function createLocalWorkspace() {
            return fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace`, {
              method: "POST"
            });
          }
          async function persistReviewDecision(candidateRef) {
            return fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decisions`, {
              method: "POST",
              body: JSON.stringify({
                candidate_ref: candidateRef,
                decision: "accepted",
                persist_to_workspace: true
              })
            });
          }
          async function rejectSelectedReviewToWorkspace(candidateRef) {
            const workspaceRejectReview = true;
            return fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decisions`, {
              method: "POST",
              body: JSON.stringify({
                candidate_ref: candidateRef,
                decision: "rejected",
                persist_to_workspace: true,
                workspaceRejectReview
              })
            });
          }
          async function correctSelectedReviewToWorkspace(candidateRef) {
            const workspaceCorrectReview = true;
            return fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decisions`, {
              method: "POST",
              body: JSON.stringify({
                candidate_ref: candidateRef,
                decision: "corrected",
                correction: {
                  summary: "Corrected in local workspace.",
                  field_updates: {},
                  replacement_ref_ids: []
                },
                persist_to_workspace: true,
                workspaceCorrectReview
              })
            });
          }
          async function regenerateReviewDecisionApplyPlan() {
            const response = await fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/review-decision-apply-plan`, {
              method: "POST"
            });
            const payload = await response.json();
            return [
              payload.boundary.workspace_file_mutation_allowed,
              payload.boundary.workspace_review_log,
              payload.boundary.workspace_review_decision_apply_plan
            ];
          }
        </script>
        """,
        encoding="utf-8",
    )

    check = _check_admin_ui_local_workspace_write_controls(tmp_path)

    assert check["ok"] is True
    assert check["write_slice_landed"] is True
    assert check["expected_route_tokens_present"] is True
    assert check["expected_function_tokens_present"] is True
    assert check["expected_persistence_tokens_present"] is True
    assert check["expected_reject_tokens_present"] is True
    assert check["expected_correct_tokens_present"] is True
    assert check["forbidden_token_count"] == 0


def test_admin_ui_write_controls_reject_forbidden_runtime_and_import_writes(tmp_path):
    page_dir = tmp_path / "docs" / "admin"
    page_dir.mkdir(parents=True)
    page = page_dir / "phase4-pretrip-planning.html"
    page.write_text(
        """
        <script>
          function createLocalWorkspace() {
            return fetch(`${apiBase()}/admin/pretrip/projects/${PROJECT_ID}/workspace`, {
              method: "PATCH"
            });
          }
          fetch(`${apiBase()}/safety/ack`);
          startCrawler();
          writeObservedFact();
        </script>
        """,
        encoding="utf-8",
    )

    check = _check_admin_ui_local_workspace_write_controls(tmp_path)

    assert check["ok"] is False
    categories = {item["category"] for item in check["forbidden_tokens"]}
    assert "absolute_fetch_to_safety" in categories
    assert "unsafe_patch_method" in categories
    assert "crawler_write" in categories
    assert "phase2_writeback" in categories


def test_release_check_reports_missing_project_ref(tmp_path):
    project_path = _copy_project_fixture(tmp_path)
    project = json.loads(project_path.read_text())
    project["readiness_report_ref"] = "outputs/not_present.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")

    summary = build_release_check(ROOT, project_json_path=project_path)

    assert summary["ok"] is False
    assert "chilai_project_refs" in summary["failed_checks"]
    assert "artifact_manifest" in summary["failed_checks"]
    assert "outputs/not_present.json" in summary["missing_required_artifacts"]
    assert summary["checks"]["artifact_manifest"]["missing_refs"] == 1


def test_release_check_rejects_project_refs_that_escape_fixture_root(tmp_path):
    project_path = _copy_project_fixture(tmp_path)
    outside_path = tmp_path / "outside.json"
    outside_path.write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    project = json.loads(project_path.read_text())
    project["readiness_report_ref"] = str(outside_path)
    project_path.write_text(json.dumps(project), encoding="utf-8")

    summary = build_release_check(ROOT, project_json_path=project_path)

    assert summary["ok"] is False
    assert "chilai_project_refs" in summary["failed_checks"]
    assert any(
        item.startswith("readiness_report_ref:absolute_ref:")
        for item in summary["missing_required_artifacts"]
    )

    project_path = _copy_project_fixture(tmp_path / "traversal")
    outside_path = project_path.parent.parent / "outside.json"
    outside_path.write_text(json.dumps({"status": "ready"}), encoding="utf-8")
    project = json.loads(project_path.read_text())
    project["readiness_report_ref"] = "../outside.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")

    summary = build_release_check(ROOT, project_json_path=project_path)

    assert summary["ok"] is False
    assert "chilai_project_refs" in summary["failed_checks"]
    assert "readiness_report_ref:escaped_ref:../outside.json" in (
        summary["missing_required_artifacts"]
    )


def test_release_check_rejects_raw_payload_key_variants(tmp_path):
    project_path = _copy_project_fixture(tmp_path)
    summary_path = project_path.parent / "outputs" / "remote_contact_summary.json"
    payload = json.loads(summary_path.read_text())
    payload["raw_payload"] = {"coordinates": [[121.0, 24.0]]}
    payload["raw_payloads"] = [{"trkpt": "hidden"}]
    payload["payload"] = "<gpx></gpx>"
    payload["base64_payload"] = "base64,AAAA"
    summary_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = build_release_check(ROOT, project_json_path=project_path)

    assert summary["ok"] is False
    assert "remote_contact_summary" in summary["failed_checks"]
    raw_keys = summary["checks"]["remote_contact_summary"]["raw_payload_keys"]
    assert raw_keys == [
        "base64_payload",
        "payload",
        "raw_payload",
        "raw_payloads",
    ]


def test_release_check_rejects_observed_facts_in_brain_seed(tmp_path):
    project_path = _copy_project_fixture(tmp_path)
    brain_seed_path = project_path.parent / "outputs" / "brain_seed_nodes.json"
    payload = json.loads(brain_seed_path.read_text())
    observed_fact = {
        "id": "fact.pretrip.invalid",
        "type": "ObservedFact",
        "mission_id": "mission.chilai_nanhua_day1.0.1.0",
    }
    payload["observed_facts"].append(observed_fact)
    payload["nodes"].append(observed_fact)
    brain_seed_path.write_text(json.dumps(payload), encoding="utf-8")

    summary = build_release_check(ROOT, project_json_path=project_path)

    assert summary["ok"] is False
    assert "brain_seed" in summary["failed_checks"]
    assert summary["checks"]["brain_seed"]["observed_fact_count"] == 2
    assert "brain_seed_observed_fact_count:0" in summary["missing_required_artifacts"]


def test_release_check_rejects_raw_artifacts_inside_fixture(tmp_path):
    project_path = _copy_project_fixture(tmp_path)
    raw_path = project_path.parent / "raw_route.gpx"
    raw_path.write_text("<gpx></gpx>", encoding="utf-8")

    summary = build_release_check(ROOT, project_json_path=project_path)

    assert summary["ok"] is False
    assert "fixture_boundary" in summary["failed_checks"]
    assert summary["checks"]["fixture_boundary"]["raw_files"] == ["raw_route.gpx"]
    assert "raw_fixture:raw_route.gpx" in summary["missing_required_artifacts"]


def test_release_check_rejects_workspace_only_outputs_inside_repo_fixtures(tmp_path):
    project_path = _copy_project_fixture(tmp_path)
    output_path = (
        tmp_path
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
        / "outputs"
        / "route_note_reviewed_assumptions.json"
    )
    output_path.parent.mkdir(parents=True)
    output_path.write_text(json.dumps({"workspace_only": True}), encoding="utf-8")

    summary = build_release_check(tmp_path, project_json_path=project_path)

    assert summary["ok"] is False
    assert "workspace_only_artifact_boundaries" in summary["failed_checks"]
    assert summary["checks"]["workspace_only_artifact_boundaries"]["forbidden_fixture_outputs"] == [
        (
            "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/"
            "route_note_reviewed_assumptions.json"
        )
    ]
    assert (
        "workspace_only_artifact_in_repo_fixture:"
        "tests/fixtures/pretrip/projects/chilai_nanhua_day1/outputs/"
        "route_note_reviewed_assumptions.json"
        in summary["missing_required_artifacts"]
    )


def _copy_project_fixture(tmp_path: Path) -> Path:
    source = PROJECT_PATH.parent
    target = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(source, target)
    return target / "project.json"
