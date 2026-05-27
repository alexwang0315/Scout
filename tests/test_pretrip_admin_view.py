import json
import shutil
from pathlib import Path

import pytest

import pretrip_layer_preparation
from pretrip_layer_preparation import LayerPreparationRequest, run_layer_preparation
from pretrip_spatial_imprint_export import (
    write_pretrip_spatial_imprint_export_for_workspace,
)
from scout_companion_match_models import (
    build_companion_capability_capsule,
    build_companion_match_review_artifact,
    write_companion_match_review_artifact,
)
from scout_energy_models import load_wearable_activity_summaries
from pretrip_admin_view import (
    build_pretrip_admin_view,
    list_pretrip_admin_projects,
    load_pretrip_debug_projection_view,
)
from tests.test_pretrip_spatial_imprint_export import _candidate_set, _review_log


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "chilai_nanhua_day1"
WEARABLE_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_FIXTURE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_FIXTURE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_FIXTURE_ROOT / "garmin_body_battery_provider_values.json",
]


def test_builds_fixture_backed_pretrip_admin_view():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    assert view["project_id"] == PROJECT_ID
    assert view["summary"]["route_name"] == "2013-10-08 10:58:50 每日記錄"
    assert view["summary"]["status"] == "candidate"
    assert view["route"]["point_count"] == 6909
    assert view["route"]["distance_m"] == 162559.51
    assert len(view["route"]["point_samples"]) == 3
    assert len(view["route"]["polyline"]) >= 2
    assert len(view["checkpoints"]) == 110
    assert len(view["segments"]) == 109
    assert view["segments"][0]["display_geometry"]["display_point_count"] > 1
    assert len(view["retreat_routes"]) == 1
    assert view["reference_tracks"]["reference_track_count"] == 23
    assert view["reference_tracks"]["boundary"]["runtime_safety_truth"] is False
    assert len(view["reference_tracks"]["reference_tracks"]) == 23
    assert (
        view["reference_tracks"]["reference_tracks"][0]["display_geometry"][
            "display_point_count"
        ]
        > 1
    )
    assert view["checkpoint_events"]["event_count"] == 110
    assert view["checkpoint_events"]["source_gpx"]["point_count"] == 6909
    assert view["checkpoint_events"]["source_gpx"]["trimming_performed"] is False
    assert view["map_candidates"]["counts"] == {
        "corridor_candidates": 1,
        "hazard_candidates": 0,
        "poi_candidates": 2,
    }
    assert view["overpass_evidence"]["counts"]["candidates"] == 219
    assert view["overpass_evidence"]["counts"]["skipped"] == 0
    assert len(view["overpass_evidence"]["corridor_candidates"]) == 191
    assert len(view["overpass_evidence"]["hazard_candidates"]) == 0
    assert len(view["overpass_evidence"]["poi_candidates"]) == 28
    assert view["overpass_evidence"]["boundary"]["runtime_truth"] is False
    assert view["overpass_evidence"]["boundary"]["live_network_required"] is False
    assert view["overpass_evidence"]["request"]["endpoint"] == "https://overpass-api.de/api/interpreter"
    assert view["readiness"]["status"] == "ready"
    assert view["eta"]["target_eta"] == "2026-05-03T15:25:35+08:00"
    assert view["route_notes"]["counts"]["note_candidate_count"] == 81
    assert view["route_notes"]["counts"]["potential_ln_signal_count"] == 23
    assert view["route_notes"]["boundary"]["requires_human_review_before_ln_upgrade"] is True
    route_note_candidate = view["route_notes"]["candidates"][0]
    assert route_note_candidate["source_id"] == route_note_candidate["candidate_id"]
    assert route_note_candidate["source_path"].endswith(
        "candidates/route_note_candidates.json"
    )
    assert route_note_candidate["evidence_type"] == "pretrip_route_note_candidate"
    assert view["route_note_ln_proposals"]["counts"]["proposal_count"] == 23
    assert (
        view["route_note_ln_proposals"]["counts"]["warning_coverage_proposal_count"]
        == 3
    )
    assert (
        view["route_note_ln_proposals"]["boundary"][
            "human_review_required_before_use"
        ]
        is True
    )
    assert view["route_note_review_options"]["counts"]["review_option_count"] == 23
    assert (
        view["route_note_review_options"]["counts"]["decision_recorded_count"]
        == 0
    )
    assert view["route_note_review_options"]["boundary"]["draft_only"] is True
    assert view["risk_ribbon"]["status"] == "candidate_only"
    assert view["risk_ribbon"]["counts"]["segment_count"] == 841
    assert view["risk_ribbon"]["counts"]["source_sample_count"] == 842
    assert view["risk_ribbon"]["boundary"]["candidate_only"] is True
    assert view["risk_ribbon"]["boundary"]["runtime_safety_truth"] is False
    assert view["risk_ribbon"]["boundary"]["interpolated_surface"] is False
    assert view["risk_ribbon"]["segments"][0]["evidence_type"] == (
        "pretrip_risk_ribbon_segment"
    )
    assert view["risk_ribbon"]["segments"][0]["coordinates"][0] == {
        "lon": 121.1749947,
        "lat": 23.9536093,
    }
    assert view["gis_perception_timeline"]["counts"]["overpass_checkpoint_candidate_count"] == 9
    assert view["gis_perception_timeline"]["counts"]["checkpoint_candidate_count"] == 9
    assert view["major_critical_points"]["status"] == "candidate_only"
    assert view["major_critical_points"]["counts"]["mcp_candidate_count"] == 6
    assert view["major_critical_points"]["counts"]["dense_checkpoint_count"] == 110
    assert view["major_critical_points"]["counts"]["suppressed_point_count"] == 2
    assert view["major_critical_points"]["counts"]["retrieval_query_count"] == 11
    assert view["major_critical_points"]["counts"]["ocr_label_count"] == 1
    assert view["major_critical_points"]["counts"]["cp_support_supported_count"] == 5
    assert (
        view["major_critical_points"]["counts"]["cp_support_suggested_insertion_count"]
        == 1
    )
    assert view["major_critical_points"]["retrieval"]["planner_kind"] == (
        "pydantic_ai_tool_orchestration_plan"
    )
    assert view["major_critical_points"]["retrieval"]["truth_decision_allowed"] is False
    assert view["major_critical_points"]["retrieval"]["fetch_summary_count"] == 12
    assert view["major_critical_points"]["retrieval"]["live_network_performed"] is False
    assert (
        view["major_critical_points"]["cp_support_reconciliation"][
            "suggested_insertion_count"
        ]
        == 1
    )
    assert view["major_critical_points"]["boundary"]["runtime_safety_truth"] is False
    assert view["major_critical_points"]["boundary"]["compile_allowed"] is False
    assert any(
        candidate["label"] == "黑水塘"
        and candidate["source_family_coverage"]["mandatory_complete"] is True
        for candidate in view["major_critical_points"]["candidates"]
    )
    assert all(
        candidate["source_profile"] == "overpass_osm_tags"
        for candidate in view["gis_perception_timeline"]["checkpoint_candidates"]
    )
    assert any(
        attribution["source_kind"] == "overpass_candidate"
        for candidate in view["gis_perception_timeline"]["checkpoint_candidates"]
        for attribution in candidate["source_attribution"]
    )
    assert view["review_queue"]["counts"]["item_count"] == 53
    assert view["review_queue"]["counts"]["category_counts"]["route_note"] == 23
    assert view["review_queue"]["counts"]["category_counts"]["gis_perception_cp"] == 9
    assert view["review_workbench"]["status"] == "projection_only"
    assert view["review_workbench"]["counts"]["category_group_count"] == 8
    assert view["review_workbench"]["counts"]["bulk_eligible_count"] == 39
    assert view["review_workbench"]["counts"]["single_review_required_count"] == 14
    assert view["review_workbench"]["boundary"]["ai_triage_is_review_aid"] is True
    assert view["review_workbench"]["boundary"]["runtime_safety_truth"] is False
    assert any(
        group["group_id"] == "review_group.category.gis_perception_cp"
        and group["bulk_eligible_count"] == 9
        for group in view["review_workbench"]["category_groups"]
    )
    assert view["review_draft_log"]["status"] == "draft_only"
    assert view["review_draft_log"]["counts"]["action_count"] == 3
    assert view["review_decision_log"]["counts"]["action_count"] == 3
    assert view["expert_contributions"]["counts"]["contribution_count"] == 3
    assert view["expert_contributions"]["counts"]["memory_seed_candidate_count"] == 3
    assert view["expert_contributions"]["boundary"]["brain_writeback_allowed"] is False
    corrected_decision = next(
        decision
        for decision in view["review_decision_log"]["decisions"]
        if decision["decision"] == "corrected"
    )
    assert corrected_decision["correction_summary"] == (
        "Keep the conservative daylight and retreat flags, but require water "
        "status to remain reviewer-confirmed."
    )
    assert corrected_decision["correction_field_update_count"] == 2
    assert corrected_decision["correction_replacement_ref_count"] == 1
    assert view["review_decision_apply_plan"]["counts"]["decision_count"] == 3
    assert (
        view["review_decision_apply_plan"]["counts"]["package_candidate_apply_count"]
        == 0
    )
    assert view["external_import_queue"]["counts"]["request_count"] == 3
    assert view["departure_bundle"]["status"] == "frozen_candidate"
    assert [layer["layer_id"] for layer in view["map_layers"]] == [
        "imagery",
        "osm",
        "terrain",
        "corridors",
        "hazards",
        "route",
        "reference-tracks",
        "retreat",
        "risk-ribbon",
        "segments",
        "checkpoints",
        "pois",
        "route-notes",
        "mcp",
        "weather-api",
    ]
    assert view["map_layers"][0]["label_zh"].startswith("影像圖層")
    assert view["map_layers"][0]["local_raster_manifest_supported"] is True
    assert view["map_layers"][0]["local_raster_tile_url_template"] == (
        "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    )
    assert view["map_layers"][0]["external_network_required"] is False
    assert view["map_layers"][-1]["label_zh"].startswith("氣象 API")
    assert view["map_layers"][-1]["external_api_calls_made"] is False
    mcp_layer = next(layer for layer in view["map_layers"] if layer["layer_id"] == "mcp")
    assert mcp_layer["source_kind"] == "major_critical_point_candidate"
    assert mcp_layer["external_api_calls_made"] is False
    assert view["tabs"]["pre_trip_planning"]["map_layers"] == view["map_layers"]
    assert view["layer_preparation"]["status"] == "not_prepared"
    assert view["layer_preparation"]["network_policy"]["network_calls_made"] is False
    assert view["layer_preparation"]["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert view["layer_preparation"]["boundary"]["workspace_file_mutation_allowed"] is False
    capability = view["capability_timeline_import"]
    assert capability["evidence_type"] == "pretrip_capability_timeline_import"
    assert capability["status"] == "read_only_post_analysis_import"
    assert capability["counts"] == {"edge_count": 2, "rest_interval_count": 1}
    assert capability["summary"]["moving_time_s"] == 1800
    assert capability["summary"]["rest_time_s"] == 420
    assert capability["privacy"]["raw_track_shared"] is False
    assert capability["privacy"]["exact_timestamps_shared"] is False
    assert capability["privacy"]["incident_details_shared"] is False
    assert capability["planning_use"]["candidate_pacing_reference_only"] is True
    assert capability["planning_use"]["auto_applies_to_eta"] is False
    assert capability["planning_use"]["auto_compiles_mission_graph"] is False
    assert capability["boundary"]["runtime_safety_truth"] is False
    assert capability["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert capability["boundary"]["mission_graph_compile_allowed"] is False


def test_loads_debug_projection_view_with_shared_map_and_dense_timeline():
    projection = load_pretrip_debug_projection_view(PROJECT_ID, root=ROOT)

    assert projection["artifact_kind"] == "pretrip_debug_projection"
    assert projection["project_id"] == PROJECT_ID
    assert projection["event_count"] > 200
    assert projection["counts"]["checkpoint_candidate_count"] == 110
    assert projection["counts"]["segment_candidate_count"] == 109
    assert projection["counts"]["reference_track_count"] == 23
    assert projection["counts"]["mcp_candidate_count"] == 6
    assert projection["counts"]["mcp_suppressed_point_count"] == 2
    assert projection["counts"]["mcp_review_action_count"] == 0
    assert projection["counts"]["risk_ribbon_segment_count"] == 841
    assert projection["counts"]["source_lifecycle_event_count"] == 4
    assert projection["route"]["point_count"] == 6909
    assert (
        projection["route"]["display_geometry"]["boundary"][
            "internal_gpx_points_preserved"
        ]
        is True
    )
    assert projection["route"]["display_geometry"]["display_point_count"] > 6000
    assert projection["reference_tracks"]["reference_track_count"] == 23
    assert projection["major_critical_points"]["status"] == "candidate_only"
    assert projection["major_critical_points"]["counts"]["mcp_candidate_count"] == 6
    assert (
        projection["major_critical_points"]["boundary"]["runtime_safety_truth"]
        is False
    )
    assert (
        projection["major_critical_points"]["retrieval"]["live_network_performed"]
        is False
    )
    assert any(
        layer["layer_id"] == "mcp"
        and layer["source_path"] == "outputs/mcp/mcp_candidates.json"
        and layer["external_api_calls_made"] is False
        for layer in projection["map_layers"]
    )
    assert projection["risk_ribbon"]["counts"]["segment_count"] == 841
    assert projection["overpass_evidence"]["counts"]["candidates"] == 219
    assert projection["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert projection["boundary"]["runtime_safety_truth"] is False

    kinds = {event["kind"] for event in projection["timeline_events"]}
    assert {"checkpoint_detected", "route_progress_evaluated"}.issubset(kinds)
    checkpoint_event = next(
        event
        for event in projection["timeline_events"]
        if event["kind"] == "checkpoint_detected"
    )
    segment_event = next(
        event
        for event in projection["timeline_events"]
        if event["kind"] == "route_progress_evaluated"
    )
    assert checkpoint_event["payload"]["checkpoint_id"].startswith("cp.")
    assert checkpoint_event["payload"]["runtime_safety_truth"] is False
    assert segment_event["payload"]["segment_id"].startswith("seg.")
    assert segment_event["payload"]["map_target_ids"]


def test_builds_admin_view_from_local_workspace_project_root(tmp_path):
    fixture_project_root = (
        ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
    )
    workspace_project_root = tmp_path / PROJECT_ID
    shutil.copytree(fixture_project_root, workspace_project_root)
    workspace_log_path = workspace_project_root / "reviews" / "review_decision_log.json"
    workspace_log = json.loads(workspace_log_path.read_text(encoding="utf-8"))
    appended = dict(workspace_log["decisions"][0])
    appended["decision_id"] = "review_decision.workspace.accepted.extra"
    appended["candidate_ref"] = "workspace.local.extra"
    appended["summary"] = "Workspace-only accepted decision."
    workspace_log["decisions"].append(appended)
    workspace_log["counts"]["action_count"] = 4
    workspace_log["counts"]["accepted_count"] = 2
    workspace_log_path.write_text(
        json.dumps(workspace_log, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    view = build_pretrip_admin_view(
        PROJECT_ID,
        root=ROOT,
        project_root=workspace_project_root,
    )

    assert view["review_decision_log"]["source_path"] == (
        "reviews/review_decision_log.json"
    )
    assert view["review_decision_log"]["counts"]["action_count"] == 4
    assert view["review_decision_log"]["counts"]["accepted_count"] == 2
    assert view["review_decision_log"]["decisions"][-1]["candidate_ref"] == (
        "workspace.local.extra"
    )


def test_pretrip_imports_workspace_local_capability_timeline_export(tmp_path: Path):
    fixture_project_root = (
        ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
    )
    workspace_project_root = tmp_path / PROJECT_ID
    shutil.copytree(fixture_project_root, workspace_project_root)
    workspace_outputs = workspace_project_root / "outputs"
    workspace_outputs.mkdir(exist_ok=True)
    post_analysis_outputs = (
        ROOT
        / "tests"
        / "fixtures"
        / "post_analysis"
        / f"{PROJECT_ID}_post_analysis"
        / "outputs"
    )
    shutil.copy2(post_analysis_outputs / "capability_timeline.json", workspace_outputs)
    shutil.copy2(post_analysis_outputs / "capability_capsule.json", workspace_outputs)

    view = build_pretrip_admin_view(
        PROJECT_ID,
        root=ROOT,
        project_root=workspace_project_root,
    )

    capability = view["capability_timeline_import"]
    assert capability["source_path"] == "outputs/capability_timeline.json"
    assert capability["capsule_source_path"] == "outputs/capability_capsule.json"
    assert capability["counts"] == {"edge_count": 2, "rest_interval_count": 1}
    assert capability["planning_use"]["auto_applies_to_eta"] is False
    assert capability["boundary"]["workspace_mutation_allowed"] is False
    assert capability["boundary"]["mission_graph_compile_allowed"] is False


def test_pretrip_imports_workspace_local_companion_match_review(tmp_path: Path):
    fixture_project_root = (
        ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
    )
    workspace_project_root = tmp_path / PROJECT_ID
    shutil.copytree(fixture_project_root, workspace_project_root)
    workspace_outputs = workspace_project_root / "outputs"
    workspace_outputs.mkdir(exist_ok=True)
    activities = load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT)
    query = build_companion_capability_capsule(
        activities,
        owner_profile_ref="local_user.private",
    )
    candidate = build_companion_capability_capsule(
        activities,
        owner_profile_ref="shared_capsule.fixture",
    )
    artifact = build_companion_match_review_artifact(
        query,
        [candidate],
        query_profile_ref="local_user.private",
        candidate_profile_refs=["shared_capsule.fixture"],
    )
    write_companion_match_review_artifact(
        artifact,
        workspace_outputs / "companion_match_review.json",
    )

    view = build_pretrip_admin_view(
        PROJECT_ID,
        root=ROOT,
        project_root=workspace_project_root,
    )

    companion = view["companion_match_review"]
    assert companion["source_path"] == "outputs/companion_match_review.json"
    assert companion["evidence_type"] == "pretrip_companion_match_review"
    assert companion["counts"] == {
        "candidate_count": 1,
        "ranked_match_count": 1,
        "recommended_review_count": 0,
    }
    assert companion["summary"]["top_candidate_profile_ref"] == "shared_capsule.fixture"
    assert companion["summary"]["top_match_score"] == 100
    assert companion["summary"]["raw_health_payload_shared"] is False
    assert companion["summary"]["auto_applies_to_eta"] is False
    assert companion["boundary"]["medical_diagnosis"] is False
    assert companion["boundary"]["phase1_runtime_safety_truth"] is False
    assert companion["boundary"]["safety_api_calls_allowed"] is False
    assert companion["boundary"]["workspace_mutation_allowed"] is False
    assert companion["boundary"]["mission_graph_compile_allowed"] is False
    assert companion["boundary"]["pretrip_eta_autocalibration_allowed"] is False
    assert companion["boundary"]["runtime_safety_truth"] is False
    post_sections = {
        section["id"]: section
        for section in view["tabs"]["post_analysis"]["sections"]
    }
    assert post_sections["companion_match_review"]["counts"] == companion["counts"]
    sections_json = json.dumps(post_sections["companion_match_review"])
    assert "<trkpt" not in sections_json
    assert "raw_samples" not in sections_json
    assert "2013-10-08T" not in sections_json


def test_admin_view_exposes_workspace_risk_score_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_project_root = (
        ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
    )
    workspace_project_root = tmp_path / PROJECT_ID
    shutil.copytree(fixture_project_root, workspace_project_root)
    risk_source = tmp_path / "risk_out"
    _write_risk_score_outputs(risk_source)
    monkeypatch.setattr(
        pretrip_layer_preparation,
        "SCOUT_RISK_OUTPUT_SOURCES",
        {PROJECT_ID: risk_source},
    )
    run_layer_preparation(
        LayerPreparationRequest(
            project_id=PROJECT_ID,
            project_root=workspace_project_root,
            layers=("risk-score",),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    view = build_pretrip_admin_view(
        PROJECT_ID,
        root=ROOT,
        project_root=workspace_project_root,
    )

    assert view["risk_score"]["status"] == "candidate_only"
    assert view["risk_score"]["counts"]["point_count"] == 2
    assert view["risk_score"]["counts"]["max_pretrip_risk"] == 61.2
    assert view["risk_score"]["points"][0]["evidence_type"] == "pretrip_risk_score_point"
    assert view["risk_score"]["points"][0]["pretrip_risk"] == 61.2
    assert view["risk_score"]["boundary"]["runtime_safety_truth"] is False
    risk_layer = next(layer for layer in view["map_layers"] if layer["layer_id"] == "risk-score")
    assert risk_layer["default_enabled"] is False
    sections = {
        section["id"]: section
        for section in view["tabs"]["pre_trip_planning"]["sections"]
    }
    assert sections["risk_score"]["counts"]["point_count"] == 2
    assert sections["risk_score"]["summary"]["score_field"] == "pretrip_risk"


def test_view_is_summary_only_and_has_traceable_source_refs():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    samples = [
        view["summary"],
        view["route"],
        view["checkpoints"][0],
        view["segments"][0],
        view["retreat_routes"][0],
        view["map_candidates"]["poi_candidates"][0],
        view["risk_ribbon"],
        view["review_queue"],
        view["review_draft_log"],
        view["raw_sample_summary"],
    ]
    for sample in samples:
        assert sample["source_id"]
        assert sample["source_path"]
        assert sample["evidence_type"].startswith("pretrip_")

    raw_summary = view["raw_sample_summary"]
    assert raw_summary["raw_payloads_embedded"] is False
    assert raw_summary["raw_gpx_read"] is False
    assert raw_summary["raw_photo_read"] is False
    assert raw_summary["raw_dtm_read"] is False
    assert raw_summary["terrain_metadata"]["candidate_tile_count"] == 48
    assert raw_summary["terrain_metadata"]["segment_count"] == 109
    assert "raw_samples" not in str(raw_summary)


def test_view_exposes_planning_and_post_analysis_tabs():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    assert set(view["tabs"]) == {"pre_trip_planning", "post_analysis", "review_workspace"}
    planning = view["tabs"]["pre_trip_planning"]
    post = view["tabs"]["post_analysis"]
    review_workspace = view["tabs"]["review_workspace"]
    assert review_workspace["review_queue"]["boundary"]["candidate_queue_only"] is True
    assert review_workspace["review_draft_log"]["boundary"]["draft_only"] is True
    assert review_workspace["review_draft_log"]["boundary"]["decisions_recorded"] is False
    assert review_workspace["review_draft_log"]["boundary"]["package_mutation_allowed"] is False
    assert review_workspace["review_draft_log"]["boundary"]["source_mutation_allowed"] is False
    assert review_workspace["review_draft_log"]["boundary"]["runtime_mutation_allowed"] is False
    assert review_workspace["review_draft_log"]["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert review_workspace["review_decision_apply_plan"]["source_path"].endswith(
        "outputs/review_decision_apply_plan.json"
    )
    assert review_workspace["review_decision_apply_plan"]["boundary"]["would_apply_only"] is True
    assert (
        review_workspace["review_decision_apply_plan"]["boundary"][
            "package_mutation_allowed"
        ]
        is False
    )
    assert (
        review_workspace["review_decision_apply_plan"]["boundary"]["source_mutation_allowed"]
        is False
    )
    assert (
        review_workspace["review_decision_apply_plan"]["boundary"]["runtime_mutation_allowed"]
        is False
    )
    assert (
        review_workspace["review_decision_apply_plan"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        review_workspace["review_decision_apply_plan"]["boundary"]["phase2_writeback_allowed"]
        is False
    )
    assert (
        review_workspace["review_decision_apply_plan"]["boundary"]["compiles_mission_graph"]
        is False
    )
    assert review_workspace["spatial_imprints"]["counts"]["candidate_count"] == 4
    assert review_workspace["spatial_imprints"]["counts"]["reviewed_imprint_count"] == 3
    assert review_workspace["spatial_imprints"]["boundary"]["runtime_safety_truth"] is False
    assert planning["resources"]["raw_payloads_embedded"] is False
    assert planning["weather"]["external_api_calls_made"] is False
    assert post["runtime_handoff"]["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert post["after_action_next_plan"]["historical_evidence_mutation_allowed"] is False
    assert post["brain_seed"]["observed_fact_count"] == 0
    assert post["capability_timeline_import"]["counts"]["edge_count"] == 2
    assert post["capability_timeline_import"]["planning_use"]["auto_applies_to_eta"] is False
    assert post["capability_timeline_import"]["boundary"]["runtime_safety_truth"] is False


def test_tabs_expose_compact_traceable_detail_sections():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    planning_sections = view["tabs"]["pre_trip_planning"]["sections"]
    post_sections = view["tabs"]["post_analysis"]["sections"]
    review_sections = view["tabs"]["review_workspace"]["sections"]

    assert [(section["id"], section["title"]) for section in planning_sections] == [
        ("eta", "ETA Plan"),
        ("readiness", "Readiness"),
        ("resources", "Resources"),
        ("layer_preparation", "Layer Preparation"),
        ("risk_score", "Risk Score"),
        ("risk_ribbon", "Baseline Risk"),
        ("risk_heatmap", "Calibrated Heat"),
        ("risk_delta", "Risk Delta"),
        ("weather", "Weather And Daylight"),
        ("overpass_evidence", "Overpass Vector Evidence"),
        ("gis_perception_timeline", "GIS Perception CP Timeline"),
        ("major_critical_points", "Major Critical Points"),
        ("route_notes", "Route Notes"),
        ("route_note_ln_proposals", "Route Note Ln Proposals"),
        ("reference_tracks", "Reference Tracks"),
        ("checkpoint_events", "Checkpoint Events"),
        ("departure_bundle", "Departure Bundle"),
    ]
    assert [(section["id"], section["title"]) for section in review_sections] == [
        ("spatial_imprints", "Spatial Imprints"),
        ("route_note_review_options", "Route Note Review Options"),
        ("review_queue", "Review Queue"),
        ("review_workbench", "Review Workbench"),
        ("review_draft_log", "Review Draft Log"),
        ("review_decision_log", "Review Decision Log"),
        ("review_decision_apply_plan", "Review Decision Apply Plan"),
        ("external_import_queue", "External Import Queue"),
        ("expert_contributions", "Expert Contributions"),
    ]
    assert [(section["id"], section["title"]) for section in post_sections] == [
        ("runtime_handoff", "Runtime Handoff"),
        ("route_comparison", "Route Comparison"),
        ("brain_seed", "Brain Seed"),
        ("after_action_next_plan", "After-Action Next Plan"),
        ("capability_timeline_import", "Capability Timeline Import"),
        ("admin_surface_projection", "Admin Surface Projection"),
        ("debug_projection", "Debug Projection"),
    ]

    sections_by_id = {
        section["id"]: section
        for section in [*planning_sections, *post_sections, *review_sections]
    }
    for section in sections_by_id.values():
        assert section["source_id"]
        assert section["source_path"]
        assert section["evidence_type"].startswith("pretrip_")
        assert section["counts"]
        assert section["summary"]

    assert sections_by_id["eta"]["counts"] == {"estimate_count": 4}
    assert sections_by_id["readiness"]["counts"] == {"finding_count": 0}
    assert sections_by_id["resources"]["counts"] == {
        "device_count": 4,
        "equipment_count": 4,
        "team_member_count": 2,
        "warning_candidate_count": 3,
    }
    assert sections_by_id["weather"]["counts"] == {
        "hazard_note_count": 2,
        "source_ref_count": 2,
    }
    assert sections_by_id["review_queue"]["counts"]["item_count"] == 53
    assert sections_by_id["review_draft_log"]["counts"]["action_count"] == 3
    assert sections_by_id["review_draft_log"]["summary"]["draft_only"] is True
    assert sections_by_id["review_draft_log"]["summary"]["decisions_recorded"] is False
    assert sections_by_id["review_draft_log"]["summary"]["category_counts"] == {
        "contour": 1,
        "poi_readiness": 1,
        "segment_policy": 1,
    }
    assert sections_by_id["review_draft_log"]["boundary"]["draft_only"] is True
    assert sections_by_id["review_draft_log"]["boundary"]["package_mutation_allowed"] is False
    assert sections_by_id["review_decision_log"]["counts"]["action_count"] == 3
    assert sections_by_id["review_decision_log"]["summary"]["accepted_count"] == 1
    assert sections_by_id["review_decision_log"]["summary"]["corrected_count"] == 1
    assert sections_by_id["review_decision_log"]["summary"]["rejected_count"] == 1
    assert sections_by_id["review_decision_log"]["boundary"]["runtime_mutation_allowed"] is False
    assert sections_by_id["review_decision_log"]["boundary"]["phase2_writeback_allowed"] is False
    assert sections_by_id["review_decision_apply_plan"]["source_path"].endswith(
        "outputs/review_decision_apply_plan.json"
    )
    assert sections_by_id["review_decision_apply_plan"]["counts"]["decision_count"] == 3
    assert (
        sections_by_id["review_decision_apply_plan"]["counts"][
            "package_candidate_apply_count"
        ]
        == 0
    )
    assert (
        sections_by_id["review_decision_apply_plan"]["summary"][
            "package_candidate_apply_count"
        ]
        == 0
    )
    assert len(sections_by_id["review_decision_apply_plan"]["summary"]["decisions"]) == 3
    assert (
        sections_by_id["review_decision_apply_plan"]["boundary"][
            "package_mutation_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["review_decision_apply_plan"]["boundary"][
            "runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["review_decision_apply_plan"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["review_decision_apply_plan"]["boundary"][
            "phase2_writeback_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["review_decision_apply_plan"]["boundary"][
            "compiles_mission_graph"
        ]
        is False
    )
    assert sections_by_id["external_import_queue"]["counts"]["request_count"] == 3
    assert sections_by_id["external_import_queue"]["summary"]["pending_count"] == 3
    assert sections_by_id["external_import_queue"]["summary"]["network_call_count"] == 0
    assert sections_by_id["external_import_queue"]["summary"]["crawler_enabled_count"] == 0
    assert sections_by_id["external_import_queue"]["boundary"]["no_network"] is True
    assert sections_by_id["external_import_queue"]["boundary"]["no_crawler"] is True
    assert sections_by_id["route_notes"]["counts"]["note_candidate_count"] == 81
    assert sections_by_id["route_notes"]["summary"]["hazard_hint_count"] == 3
    assert sections_by_id["route_notes"]["summary"]["potential_ln_signal_count"] == 23
    assert sections_by_id["route_notes"]["boundary"]["raw_gpx_embedded"] is False
    assert sections_by_id["route_note_ln_proposals"]["counts"]["proposal_count"] == 23
    assert (
        sections_by_id["route_note_ln_proposals"]["summary"][
            "warning_coverage_proposal_count"
        ]
        == 3
    )
    assert (
        sections_by_id["route_note_ln_proposals"]["boundary"][
            "runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["route_note_review_options"]["counts"]["review_option_count"] == 23
    assert (
        sections_by_id["route_note_review_options"]["summary"][
            "allowed_admin_dispositions"
        ]
        == ["promote_hint", "promote_warning", "ignore", "field_verify"]
    )
    assert (
        sections_by_id["route_note_review_options"]["boundary"][
            "decision_recording_allowed"
        ]
        is False
    )
    assert sections_by_id["major_critical_points"]["counts"] == {
        "accepted_evidence_page_count": 12,
        "cp_support_suggested_insertion_count": 1,
        "cp_support_supported_count": 5,
        "dense_checkpoint_count": 110,
        "mcp_candidate_count": 6,
        "ocr_label_count": 1,
        "retrieval_query_count": 11,
        "review_required_ocr_label_count": 1,
        "review_action_count": 0,
        "suppressed_point_count": 2,
    }
    assert (
        sections_by_id["major_critical_points"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["spatial_imprints"]["counts"] == {
        "accepted_count": 3,
        "candidate_count": 4,
        "corrected_count": 0,
        "disabled_count": 1,
        "hardware_control_count": 0,
        "phase1_runtime_mutation_count": 0,
        "rejected_count": 0,
        "remote_outbound_send_count": 0,
        "review_record_count": 4,
        "reviewed_imprint_count": 3,
        "runtime_truth_count": 0,
        "safety_api_call_count": 0,
    }
    assert (
        sections_by_id["spatial_imprints"]["summary"]["reviewed_imprint_count"]
        == 3
    )
    assert (
        sections_by_id["spatial_imprints"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["expert_contributions"]["counts"]["contribution_count"] == 3
    assert sections_by_id["expert_contributions"]["summary"]["candidate_set_edit_count"] == 2
    assert sections_by_id["expert_contributions"]["summary"]["external_import_edit_count"] == 1
    assert sections_by_id["expert_contributions"]["summary"]["memory_seed_candidate_count"] == 3
    assert sections_by_id["expert_contributions"]["summary"]["brain_writeback_count"] == 0
    assert (
        sections_by_id["expert_contributions"]["boundary"]["memory_seed_candidate_only"]
        is True
    )
    assert (
        sections_by_id["expert_contributions"]["boundary"]["brain_writeback_allowed"]
        is False
    )
    assert sections_by_id["departure_bundle"]["counts"]["required_ref_count"] == 24
    assert sections_by_id["runtime_handoff"]["counts"]["safety_call_count"] == 0
    assert sections_by_id["route_comparison"]["counts"]["point_count_delta"] == -1275
    assert sections_by_id["brain_seed"]["counts"]["observed_fact_count"] == 0
    assert sections_by_id["after_action_next_plan"]["counts"]["candidate_count"] == 3
    assert sections_by_id["capability_timeline_import"]["counts"] == {
        "edge_count": 2,
        "rest_interval_count": 1,
    }
    assert sections_by_id["capability_timeline_import"]["summary"]["moving_time_s"] == 1800
    assert sections_by_id["capability_timeline_import"]["summary"]["raw_track_shared"] is False
    assert sections_by_id["capability_timeline_import"]["summary"]["auto_applies_to_eta"] is False
    assert (
        sections_by_id["capability_timeline_import"]["boundary"][
            "raw_track_shared_by_default"
        ]
        is False
    )
    assert (
        sections_by_id["capability_timeline_import"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["capability_timeline_import"]["boundary"]["runtime_safety_truth"]
        is False
    )
    assert sections_by_id["admin_surface_projection"]["counts"] == {
        "checkpoint_candidate_count": 110,
        "reference_track_count": 23,
        "segment_candidate_count": 109,
    }
    assert sections_by_id["admin_surface_projection"]["summary"]["surface_targets"] == [
        "/admin",
        "/admin/pretrip",
        "/admin/debug",
    ]
    assert (
        sections_by_id["admin_surface_projection"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["debug_projection"]["counts"] == {"event_count": 4}
    assert (
        sections_by_id["debug_projection"]["summary"][
            "file_runtime_debug_log_compatible"
        ]
        is True
    )
    assert (
        sections_by_id["debug_projection"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )


def test_view_exposes_optional_spatial_imprint_review_workspace(tmp_path):
    source_project_root = (
        ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
    )
    project_root = tmp_path / PROJECT_ID
    shutil.copytree(source_project_root, project_root)
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update(
        {
            "spatial_imprint_candidates_ref": "candidates/spatial_imprints.json",
            "spatial_imprint_reviews_ref": "reviews/spatial_imprint_reviews.json",
            "spatial_imprint_set_ref": "outputs/spatial_imprint_set.json",
            "spatial_imprint_manifest_ref": "outputs/spatial_imprint_manifest.json",
        }
    )
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (project_root / "candidates" / "spatial_imprints.json").write_text(
        _candidate_set().model_dump_json(),
        encoding="utf-8",
    )
    (project_root / "reviews" / "spatial_imprint_reviews.json").write_text(
        _review_log().model_dump_json(),
        encoding="utf-8",
    )
    write_pretrip_spatial_imprint_export_for_workspace(project_root)

    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT, project_root=project_root)
    spatial = view["spatial_imprints"]
    review_sections = {
        section["id"]: section
        for section in view["tabs"]["review_workspace"]["sections"]
    }

    assert spatial["status"] == "reviewed_pretrip_addendum"
    assert spatial["counts"]["candidate_count"] == 4
    assert spatial["counts"]["reviewed_imprint_count"] == 2
    assert spatial["boundary"]["runtime_activation_allowed"] is False
    assert spatial["reviewed_imprints"][0]["planting_source"] == "pretrip_reviewed"
    assert spatial["reviewed_imprints"][0]["payload_type"] == "voice_cue"
    assert "spatial_imprints" in review_sections
    assert review_sections["spatial_imprints"]["counts"]["runtime_truth_count"] == 0
    assert (
        review_sections["spatial_imprints"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )


def test_tab_detail_sections_do_not_embed_raw_payload_fragments():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)
    sections_json = json.dumps(
        {
            "planning": view["tabs"]["pre_trip_planning"]["sections"],
            "post": view["tabs"]["post_analysis"]["sections"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    assert "raw_samples" not in sections_json
    assert "source_uri" not in sections_json
    assert "/Users/alexwang0315/downloads" not in sections_json
    assert "coordinates" not in sections_json
    assert "proposed_fields" not in sections_json
    assert "reviewer_prompt" not in sections_json
    assert "confidence_after_review" not in sections_json
    assert "<trkpt" not in sections_json
    assert "2013-10-08T" not in sections_json


def test_review_draft_log_is_read_only_summary_without_raw_payloads():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)
    review_draft_log = view["review_draft_log"]

    assert review_draft_log["source_path"].endswith("reviews/review_draft_log.json")
    assert review_draft_log["evidence_type"] == "pretrip_review_draft_log"
    assert review_draft_log["status"] == "draft_only"
    assert review_draft_log["counts"]["action_count"] == 3
    assert review_draft_log["counts"]["draft_action_count"] == 3
    assert review_draft_log["counts"]["mutation_action_count"] == 0
    assert review_draft_log["category_counts"] == {
        "contour": 1,
        "poi_readiness": 1,
        "segment_policy": 1,
    }
    assert review_draft_log["boundary"]["draft_only"] is True
    assert review_draft_log["boundary"]["decisions_recorded"] is False
    assert review_draft_log["boundary"]["admin_api_integration"] is False
    assert review_draft_log["boundary"]["review_log_mutation_allowed"] is False
    assert review_draft_log["boundary"]["package_mutation_allowed"] is False
    assert review_draft_log["boundary"]["source_mutation_allowed"] is False
    assert review_draft_log["boundary"]["runtime_mutation_allowed"] is False
    assert review_draft_log["boundary"]["phase1_runtime_mutation_allowed"] is False

    assert len(review_draft_log["actions"]) == 3
    for action in review_draft_log["actions"]:
        assert action["draft_only"] is True
        assert action["decision_recorded"] is False
        assert action["package_mutation_allowed"] is False
        assert action["source_mutation_allowed"] is False
        assert action["runtime_mutation_allowed"] is False

    draft_json = json.dumps(review_draft_log, ensure_ascii=False, sort_keys=True)
    assert "proposed_fields" not in draft_json
    assert "reviewer_prompt" not in draft_json
    assert "target_segment_refs" not in draft_json
    assert "requested_review_output" not in draft_json
    assert "raw image" not in draft_json


def test_review_queue_items_include_map_highlight_targets():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)
    items = view["review_queue"]["items"]

    contour = next(item for item in items if item["category"] == "contour_interpretation")
    assert contour["source_id"] == contour["item_id"]
    assert contour["source_path"].endswith("outputs/review_queue_manifest.json")
    assert contour["evidence_type"] == "pretrip_review_queue_item"
    assert {"seg.001", "seg.002", "seg.003"} <= set(contour["map_target_ids"])

    segment_policy = next(item for item in items if item["category"] == "segment_policy")
    assert segment_policy["candidate_ref"].startswith("policy_candidate.chilai_nanhua_day1.seg.")
    assert any(target.startswith("seg.") for target in segment_policy["map_target_ids"])

    assert [item for item in items if item["severity"] == "blocker"] == []


def test_list_pretrip_admin_projects_and_unknown_project():
    projects = list_pretrip_admin_projects()

    assert projects == [
        {
            "project_id": PROJECT_ID,
            "name": "能高安東軍縱走 GPX corpus",
            "kind": "phase4_pretrip_fixture",
        }
    ]
    with pytest.raises(KeyError):
        build_pretrip_admin_view("missing", root=ROOT)


def _write_risk_score_outputs(directory: Path) -> None:
    directory.mkdir(parents=True)
    route_risk = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.2, 24.0]},
                "properties": {
                    "sample_id": "risk.sample.001",
                    "pretrip_risk": 61.2,
                    "risk_level": 4,
                    "distance_m": 10.0,
                    "teii_20m": 70.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.21, 24.01]},
                "properties": {
                    "sample_id": "risk.sample.002",
                    "pretrip_risk": 48.5,
                    "risk_level": 3,
                    "distance_m": 30.0,
                    "teii_20m": 55.0,
                },
            },
        ],
    }
    score_points = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.2, 24.0]},
                "properties": {
                    "x": 250000.0,
                    "y": 2650000.0,
                    "rs": 61.2,
                    "score_field": "pretrip_risk",
                    "route_id": "fixture",
                    "sample_id": "risk.sample.001",
                    "distance_m": 10.0,
                    "risk_level": 4,
                    "teii_20m": 70.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.21, 24.01]},
                "properties": {
                    "x": 250020.0,
                    "y": 2650020.0,
                    "rs": 48.5,
                    "score_field": "pretrip_risk",
                    "route_id": "fixture",
                    "sample_id": "risk.sample.002",
                    "distance_m": 30.0,
                    "risk_level": 3,
                    "teii_20m": 55.0,
                },
            },
        ],
    }
    files = {
        "route_risk.geojson": route_risk,
        "route_risk.metadata.json": {
            "artifact_kind": "scout_risk_overpass_route_profile_metadata",
            "route_risk_sample_count": 2,
            "boundary": {"candidate_only": True, "runtime_safety_truth": False},
        },
        "risk_score_points.geojson": score_points,
        "risk_score_points.metadata.json": {
            "artifact_kind": "scout_risk_score_point_map",
            "point_count": 2,
            "source_feature_count": 2,
            "score_field": "pretrip_risk",
            "snap_grid_m": 20.0,
            "boundary": {
                "candidate_only": True,
                "runtime_safety_truth": False,
                "route_aligned_samples_only": True,
            },
        },
    }
    for filename, payload in files.items():
        (directory / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (directory / "route_risk.csv").write_text("sample_id,pretrip_risk\n", encoding="utf-8")
    (directory / "risk_score_points.csv").write_text("x,y,rs\n", encoding="utf-8")
    (directory / "risk_score_points.xyz").write_text("250000 2650000 61.2\n", encoding="utf-8")
