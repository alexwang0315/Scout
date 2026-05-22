import json
from pathlib import Path

from pretrip_artifact_manifest import PROJECT_ARTIFACTS, build_pretrip_artifact_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PROJECT_PATH = FIXTURE_ROOT / "project.json"


def test_builds_deterministic_manifest_with_stable_ordering():
    first = build_pretrip_artifact_manifest(PROJECT_PATH)
    second = build_pretrip_artifact_manifest(PROJECT_PATH)

    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")

    payload = first.to_dict()
    expected_project_kinds = [artifact_kind for artifact_kind, _ in PROJECT_ARTIFACTS]
    project_artifact_count = len(PROJECT_ARTIFACTS)
    assert [artifact["artifact_kind"] for artifact in payload["artifacts"][:project_artifact_count]] == (
        expected_project_kinds
    )
    assert [artifact["artifact_kind"] for artifact in payload["artifacts"][project_artifact_count:]] == [
        "gpx",
        "photo",
    ]
    assert payload["counts"] == {
        "missing_refs": 0,
        "project_artifacts": project_artifact_count,
        "source_artifacts": 2,
        "total_artifacts": project_artifact_count + 2,
    }


def test_preserves_artifact_refs_paths_and_sha256_where_available():
    manifest = build_pretrip_artifact_manifest(PROJECT_PATH).to_dict()
    artifacts = manifest["artifacts"]
    by_kind = {artifact["artifact_kind"]: artifact for artifact in artifacts[: len(PROJECT_ARTIFACTS)]}

    assert by_kind["pretrip_package"]["ref"] == "outputs/pretrip_package.json"
    assert by_kind["pretrip_package"]["package_id"] == "pretrip.chilai_nanhua_day1.v0"
    assert len(by_kind["pretrip_package"]["sha256"]) == 64
    assert by_kind["route_summary"]["ref"] == "normalized/routes/route_summary.json"
    assert by_kind["route_comparison"]["ref"] == "outputs/route_comparison.json"
    assert by_kind["route_comparison"]["classification"] == "comparison_only"
    assert by_kind["route_comparison"]["primary_route_name"] == "奇萊南華-能高越嶺步道Day1"
    assert by_kind["route_comparison"]["bbox_overlaps"] is True
    assert by_kind["dtm_coverage_summary"]["candidate_tile_count"] == 48
    assert by_kind["segment_dtm_coverage"]["segment_count"] == 109
    assert by_kind["segment_dtm_coverage"]["unlinked_segment_count"] == 0
    assert by_kind["checkpoint_candidates"]["item_count"] == 110
    assert by_kind["segment_candidates"]["item_count"] == 109
    assert by_kind["retreat_route_candidates"]["item_count"] == 1
    assert by_kind["map_context_geojson"]["feature_count"] == 3
    assert by_kind["map_candidates"]["corridor_candidate_count"] == 1
    assert by_kind["map_candidates"]["poi_candidate_count"] == 2
    assert by_kind["map_candidates"]["hazard_candidate_count"] == 0
    assert by_kind["planning_references"]["item_count"] == 3
    assert by_kind["route_guide_timing_candidates"]["item_count"] == 19
    assert by_kind["skill_config_manifest"]["scope"] == "pretrip_readiness"
    assert by_kind["readiness_report"]["status"] == "ready"
    assert by_kind["human_review_log"]["review_count"] == 47
    assert by_kind["reviewed_pretrip_package"]["status"] == "reviewed"
    assert by_kind["compiled_mission_graph_candidate"]["checkpoint_count"] == 11
    assert by_kind["compiled_mission_graph_candidate"]["segment_count"] == 10
    assert by_kind["compiled_mission_graph_candidate"]["diversion_point_count"] == 1
    assert by_kind["compiled_mission_graph_reviewed"]["checkpoint_count"] == 11
    assert by_kind["compiled_mission_graph_reviewed"]["segment_count"] == 10
    assert by_kind["compiled_mission_graph_reviewed"]["diversion_point_count"] == 1
    assert by_kind["timing_measurements"]["measurement_candidate_count"] == 18
    assert by_kind["planned_eta"]["estimate_count"] == 4
    assert by_kind["planned_eta"]["planned_start_time"] == "2026-05-03T08:55:35+08:00"
    assert by_kind["planned_eta"]["turn_back_checkpoint_node_name"] == "雲海保線所"
    assert by_kind["planned_eta"]["day1_target_node_name"] == "天池山莊"
    assert by_kind["planned_eta"]["target_eta"] == "2026-05-03T15:25:35+08:00"
    assert by_kind["planned_eta"]["team_multiplier_status"] == "not_derived_no_human_stats"
    assert by_kind["brain_seed_nodes"]["artifact_count"] == 13
    assert by_kind["brain_seed_nodes"]["human_review_count"] == 47
    assert by_kind["brain_seed_nodes"]["derived_measurement_count"] == 31
    assert by_kind["brain_seed_nodes"]["model_interpretation_count"] == 6
    assert by_kind["brain_seed_nodes"]["observed_fact_count"] == 0
    assert by_kind["brain_seed_nodes"]["node_count"] == 97
    assert by_kind["planning_skill_audit"]["record_count"] == 5
    assert by_kind["planning_skill_audit"]["node_types"] == ["SkillRunRecord"]
    assert by_kind["planning_skill_audit"]["skill_ids"] == [
        "pretrip-source-ingest",
        "pretrip-cp-segment-suggest",
        "pretrip-map-import",
        "pretrip-mission-compile",
        "pretrip-brain-seed-export",
    ]
    assert by_kind["poi_readiness_candidates"]["status"] == "candidate_only"
    assert by_kind["poi_readiness_candidates"]["policy_candidate_count"] == 1
    assert by_kind["poi_readiness_candidates"]["policy_categories"] == [
        "route_corridor_poi_coverage"
    ]
    assert by_kind["poi_readiness_candidates"]["finding_candidate_count"] == 0
    assert by_kind["poi_readiness_candidates"]["warning_candidate_count"] == 0
    assert by_kind["poi_readiness_candidates"]["blocker_candidate_count"] == 0
    assert by_kind["poi_readiness_candidates"]["route_corridor_poi_count"] == 1
    assert by_kind["poi_readiness_candidates"]["finding_severities"] == []
    assert by_kind["segment_policy_candidates"]["status"] == "candidate_only"
    assert by_kind["segment_policy_candidates"]["candidate_count"] == 10
    assert by_kind["segment_policy_candidates"]["candidate_only_count"] == 10
    assert by_kind["segment_policy_candidates"]["human_review_required_count"] == 10
    assert by_kind["segment_policy_candidates"]["requires_daylight_count"] == 10
    assert by_kind["segment_policy_candidates"]["retreat_available_count"] == 2
    assert by_kind["segment_policy_candidates"]["signal_expected_count"] == 1
    assert by_kind["plan_validation_candidates"]["status"] == "candidate_only"
    assert by_kind["plan_validation_candidates"]["finding_candidate_count"] == 6
    assert by_kind["plan_validation_candidates"]["warning_candidate_count"] == 6
    assert by_kind["plan_validation_candidates"]["blocker_candidate_count"] == 0
    assert by_kind["plan_validation_candidates"]["source_ref_count"] == 8
    assert by_kind["plan_validation_candidates"]["hard_readiness_status"] == "ready"
    assert by_kind["plan_validation_candidates"]["hard_readiness_finding_count"] == 0
    assert by_kind["plan_validation_candidates"]["hard_readiness_mutation_allowed"] is False
    assert by_kind["plan_validation_candidates"]["raw_payloads_embedded"] is False
    assert by_kind["plan_validation_candidates"]["finding_severities"] == ["warning"]
    assert by_kind["runtime_audit_manifest"]["manifest_id"] == (
        "runtime_audit_manifest.chilai_nanhua_day1.v0"
    )
    assert by_kind["runtime_audit_manifest"]["status"] == "candidate_only"
    assert by_kind["runtime_audit_manifest"]["runtime_artifact_kind"] == (
        "plan_to_runtime_audit_manifest"
    )
    assert by_kind["runtime_audit_manifest"]["comparison_axis_count"] == 8
    assert by_kind["runtime_audit_manifest"]["planned_ref_count"] == 15
    assert by_kind["runtime_audit_manifest"]["observed_item_count"] == 0
    assert by_kind["runtime_audit_manifest"]["live_comparison_count"] == 0
    assert by_kind["runtime_audit_manifest"]["raw_payload_count"] == 0
    assert by_kind["runtime_audit_manifest"]["incident_package_imported"] is False
    assert by_kind["runtime_audit_manifest"]["phase1_runtime_mutation_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["manifest_id"] == (
        "runtime_handoff_metadata.chilai_nanhua_day1.v0"
    )
    assert by_kind["runtime_handoff_metadata"]["status"] == "candidate_metadata_only"
    assert by_kind["runtime_handoff_metadata"]["handoff_artifact_kind"] == (
        "pretrip_runtime_handoff_metadata"
    )
    assert by_kind["runtime_handoff_metadata"]["plan_version_id"] == (
        "pretrip.chilai_nanhua_day1.v0:0.1.0"
    )
    assert by_kind["runtime_handoff_metadata"]["readiness_ref_count"] == 3
    assert by_kind["runtime_handoff_metadata"]["route_ref_count"] == 4
    assert by_kind["runtime_handoff_metadata"]["route_source_count"] == 1
    assert by_kind["runtime_handoff_metadata"]["runtime_write_count"] == 0
    assert by_kind["runtime_handoff_metadata"]["safety_call_count"] == 0
    assert by_kind["runtime_handoff_metadata"]["bridge_mutation_count"] == 0
    assert by_kind["runtime_handoff_metadata"]["candidate_metadata_only"] is True
    assert by_kind["runtime_handoff_metadata"]["phase1_runtime_mutation_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["safety_api_calls_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["bridge_mutation_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["final_runtime_write_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["live_runtime_read_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["phase2_writeback_allowed"] is False
    assert by_kind["runtime_handoff_metadata"]["raw_payloads_embedded"] is False
    assert by_kind["after_action_next_plan_candidates"]["artifact_id"] == (
        "after_action_next_plan_candidates.chilai_nanhua_day1.scout_260512.v0"
    )
    assert by_kind["after_action_next_plan_candidates"]["status"] == "candidate_only"
    assert by_kind["after_action_next_plan_candidates"]["source_case_id"] == (
        "scout_260512_field_golden"
    )
    assert by_kind["after_action_next_plan_candidates"]["candidate_count"] == 3
    assert by_kind["after_action_next_plan_candidates"]["evidence_ref_count"] == 11
    assert by_kind["after_action_next_plan_candidates"]["brain_node_ref_count"] == 3
    assert by_kind["after_action_next_plan_candidates"]["incident_package_ref_count"] == 0
    assert by_kind["after_action_next_plan_candidates"]["deterministic_finding_count"] == 1
    assert by_kind["after_action_next_plan_candidates"]["reviewer_note_count"] == 1
    assert by_kind["after_action_next_plan_candidates"]["model_suggestion_count"] == 1
    assert by_kind["after_action_next_plan_candidates"]["observed_fact_writeback_allowed"] is False
    assert by_kind["after_action_next_plan_candidates"]["historical_evidence_mutation_allowed"] is False
    assert by_kind["after_action_next_plan_candidates"]["raw_payloads_embedded"] is False
    assert by_kind["review_draft_log"]["log_id"] == "review_draft_log.chilai_nanhua_day1.v0"
    assert by_kind["review_draft_log"]["status"] == "draft_only"
    assert by_kind["review_draft_log"]["draft_artifact_kind"] == "pretrip_review_draft_log"
    assert by_kind["review_draft_log"]["action_count"] == 3
    assert by_kind["review_draft_log"]["draft_action_count"] == 3
    assert by_kind["review_draft_log"]["mutation_action_count"] == 0
    assert by_kind["review_draft_log"]["source_ref_count"] == 3
    assert by_kind["review_draft_log"]["category_counts"] == {
        "contour": 1,
        "poi_readiness": 1,
        "segment_policy": 1,
    }
    assert by_kind["review_draft_log"]["draft_only"] is True
    assert by_kind["review_draft_log"]["decisions_recorded"] is False
    assert by_kind["review_draft_log"]["external_api_calls_made"] is False
    assert by_kind["review_draft_log"]["source_mutation_allowed"] is False
    assert by_kind["review_draft_log"]["package_mutation_allowed"] is False
    assert by_kind["review_draft_log"]["review_log_mutation_allowed"] is False
    assert by_kind["review_draft_log"]["runtime_mutation_allowed"] is False
    assert by_kind["review_draft_log"]["phase1_runtime_mutation_allowed"] is False
    assert by_kind["review_draft_log"]["phase2_writeback_allowed"] is False
    assert by_kind["review_draft_log"]["admin_api_integration"] is False
    assert by_kind["review_draft_log"]["raw_payloads_embedded"] is False
    assert by_kind["review_decision_log"]["log_id"] == "review_decision_log.chilai_nanhua_day1.v0"
    assert by_kind["review_decision_log"]["decision_artifact_kind"] == (
        "pretrip_review_decision_log"
    )
    assert by_kind["review_decision_log"]["action_count"] == 3
    assert by_kind["review_decision_log"]["accepted_count"] == 1
    assert by_kind["review_decision_log"]["corrected_count"] == 1
    assert by_kind["review_decision_log"]["rejected_count"] == 1
    assert by_kind["review_decision_log"]["runtime_mutation_count"] == 0
    assert by_kind["review_decision_log"]["package_mutation_count"] == 0
    assert by_kind["review_decision_log"]["source_mutation_allowed"] is False
    assert by_kind["review_decision_log"]["package_mutation_allowed"] is False
    assert by_kind["review_decision_log"]["runtime_mutation_allowed"] is False
    assert by_kind["review_decision_log"]["phase1_runtime_mutation_allowed"] is False
    assert by_kind["review_decision_log"]["phase2_writeback_allowed"] is False
    assert by_kind["review_decision_log"]["admin_api_integration"] is False
    assert by_kind["review_decision_log"]["compiles_mission_graph"] is False
    assert by_kind["review_decision_log"]["raw_payloads_embedded"] is False
    assert by_kind["review_decision_apply_plan"]["plan_id"] == (
        "review_decision_apply_plan.chilai_nanhua_day1.v0"
    )
    assert by_kind["review_decision_apply_plan"]["apply_artifact_kind"] == (
        "pretrip_review_decision_apply_plan"
    )
    assert by_kind["review_decision_apply_plan"]["decision_count"] == 3
    assert by_kind["review_decision_apply_plan"]["accepted_count"] == 1
    assert by_kind["review_decision_apply_plan"]["corrected_count"] == 1
    assert by_kind["review_decision_apply_plan"]["rejected_count"] == 1
    assert by_kind["review_decision_apply_plan"]["package_candidate_apply_count"] == 0
    assert by_kind["review_decision_apply_plan"]["runtime_mutation_count"] == 0
    assert by_kind["review_decision_apply_plan"]["would_apply_only"] is True
    assert by_kind["review_decision_apply_plan"]["source_mutation_allowed"] is False
    assert by_kind["review_decision_apply_plan"]["package_mutation_allowed"] is False
    assert by_kind["review_decision_apply_plan"]["runtime_mutation_allowed"] is False
    assert by_kind["review_decision_apply_plan"]["phase1_runtime_mutation_allowed"] is False
    assert by_kind["review_decision_apply_plan"]["phase2_writeback_allowed"] is False
    assert by_kind["review_decision_apply_plan"]["compiles_mission_graph"] is False
    assert by_kind["review_decision_apply_plan"]["raw_payloads_embedded"] is False
    assert by_kind["external_import_queue"]["queue_id"] == (
        "external_import_queue.chilai_nanhua_day1.v0"
    )
    assert by_kind["external_import_queue"]["status"] == "pending_human_review"
    assert by_kind["external_import_queue"]["request_count"] == 3
    assert by_kind["external_import_queue"]["pending_count"] == 3
    assert by_kind["external_import_queue"]["crawler_enabled_count"] == 0
    assert by_kind["external_import_queue"]["network_call_count"] == 0
    assert by_kind["external_import_queue"]["observed_fact_count"] == 0
    assert by_kind["external_import_queue"]["raw_payloads_embedded"] is False
    assert by_kind["external_import_queue"]["no_network"] is True
    assert by_kind["external_import_queue"]["no_crawler"] is True
    assert by_kind["external_import_queue"]["source_ids"] == [
        "source.joyhike.main_site",
        "source.joyhike.blog",
        "source.ptt.sunriver_timing",
    ]
    assert by_kind["route_note_candidates"]["note_candidate_count"] == 81
    assert by_kind["route_note_candidates"]["hazard_hint_count"] == 2
    assert by_kind["route_note_candidates"]["route_condition_hint_count"] == 19
    assert by_kind["route_note_candidates"]["potential_ln_signal_count"] == 21
    assert (
        by_kind["route_note_candidates"]["requires_human_review_before_ln_upgrade"]
        is True
    )
    assert by_kind["route_note_candidates"]["raw_gpx_embedded"] is False
    assert by_kind["route_note_ln_proposals"]["status"] == "candidate_only"
    assert by_kind["route_note_ln_proposals"]["proposal_count"] == 21
    assert by_kind["route_note_ln_proposals"]["hint_coverage_proposal_count"] == 19
    assert by_kind["route_note_ln_proposals"]["warning_coverage_proposal_count"] == 2
    assert by_kind["route_note_ln_proposals"]["human_review_required_count"] == 21
    assert by_kind["route_note_ln_proposals"]["observed_fact_count"] == 0
    assert by_kind["route_note_ln_proposals"]["runtime_mutation_count"] == 0
    assert (
        by_kind["route_note_ln_proposals"]["human_review_required_before_use"]
        is True
    )
    assert by_kind["route_note_ln_proposals"]["raw_gpx_embedded"] is False
    assert by_kind["route_note_review_options"]["status"] == (
        "candidate_only_draft_only"
    )
    assert by_kind["route_note_review_options"]["review_option_count"] == 21
    assert by_kind["route_note_review_options"]["candidate_only_count"] == 21
    assert by_kind["route_note_review_options"]["draft_only_count"] == 21
    assert by_kind["route_note_review_options"]["decision_recorded_count"] == 0
    assert by_kind["route_note_review_options"]["runtime_mutation_count"] == 0
    assert by_kind["route_note_review_options"]["candidate_only"] is True
    assert by_kind["route_note_review_options"]["draft_only"] is True
    assert by_kind["route_note_review_options"]["review_options_only"] is True
    assert by_kind["route_note_review_options"]["decision_recording_allowed"] is False
    assert by_kind["route_note_review_options"]["raw_gpx_embedded"] is False
    assert by_kind["expert_contribution_log"]["log_id"] == (
        "expert_contribution_log.chilai_nanhua_day1.v0"
    )
    assert by_kind["expert_contribution_log"]["status"] == "candidate_memory_seed_only"
    assert by_kind["expert_contribution_log"]["contribution_count"] == 3
    assert by_kind["expert_contribution_log"]["candidate_set_edit_count"] == 2
    assert by_kind["expert_contribution_log"]["external_import_edit_count"] == 1
    assert by_kind["expert_contribution_log"]["memory_seed_candidate_count"] == 3
    assert by_kind["expert_contribution_log"]["brain_writeback_count"] == 0
    assert by_kind["expert_contribution_log"]["memory_seed_candidate_only"] is True
    assert by_kind["expert_contribution_log"]["brain_writeback_allowed"] is False
    assert by_kind["remote_contact_summary"]["summary_id"] == (
        "remote_contact_summary.chilai_nanhua_day1.v0"
    )
    assert by_kind["remote_contact_summary"]["audience"] == "remote_contacts"
    assert by_kind["remote_contact_summary"]["route_name"] == "奇萊南華-能高越嶺步道Day1"
    assert by_kind["remote_contact_summary"]["planned_start"] == "2026-05-03T08:55:35+08:00"
    assert by_kind["remote_contact_summary"]["day1_target_eta"] == "2026-05-03T15:25:35+08:00"
    assert by_kind["remote_contact_summary"]["turn_back_checkpoint_eta"] == (
        "2026-05-03T11:55:35+08:00"
    )
    assert by_kind["remote_contact_summary"]["return_to_entry_eta"] == (
        "2026-05-03T13:35:35+08:00"
    )
    assert by_kind["remote_contact_summary"]["readiness_status"] == "ready"
    assert by_kind["remote_contact_summary"]["source_package_version"] == "0.1.0"
    assert by_kind["remote_contact_summary"]["conservative_note_count"] == 3
    assert by_kind["resource_plan"]["plan_id"] == "resource_plan.chilai_nanhua_day1.v0"
    assert by_kind["resource_plan"]["status"] == "candidate_only"
    assert by_kind["resource_plan"]["resource_artifact_kind"] == "resource_team_departure_plan"
    assert by_kind["resource_plan"]["team_member_count"] == 2
    assert by_kind["resource_plan"]["device_count"] == 4
    assert by_kind["resource_plan"]["equipment_count"] == 4
    assert by_kind["resource_plan"]["warning_candidate_count"] == 3
    assert by_kind["resource_plan"]["blocker_candidate_count"] == 0
    assert by_kind["resource_plan"]["hard_readiness_mutation_allowed"] is False
    assert by_kind["resource_plan"]["blocks_existing_eta_or_readiness"] is False
    assert by_kind["resource_plan"]["external_api_calls_made"] is False
    assert by_kind["resource_plan"]["raw_payloads_embedded"] is False
    assert by_kind["departure_bundle_manifest"]["required_ref_count"] == 24
    assert by_kind["departure_bundle_manifest"]["audit_ref_count"] == 6
    assert by_kind["departure_bundle_manifest"]["not_departure_approval"] is True
    assert by_kind["weather_daylight_evidence"]["evidence_id"] == (
        "weather_daylight.chilai_nanhua_day1.2026-05-03.v0"
    )
    assert by_kind["weather_daylight_evidence"]["status"] == "candidate_only"
    assert by_kind["weather_daylight_evidence"]["date"] == "2026-05-03"
    assert by_kind["weather_daylight_evidence"]["route_ref"] == (
        "normalized/routes/route_summary.json"
    )
    assert by_kind["weather_daylight_evidence"]["validation_status"] == (
        "human_review_required"
    )
    assert by_kind["weather_daylight_evidence"]["confidence"] == "unknown"
    assert by_kind["weather_daylight_evidence"]["staleness"] == "placeholder"
    assert by_kind["weather_daylight_evidence"]["human_review_required"] is True
    assert by_kind["weather_daylight_evidence"]["authoritative_weather_computed"] is False
    assert by_kind["weather_daylight_evidence"]["external_api_calls_made"] is False
    assert by_kind["weather_daylight_evidence"]["daylight_source_status"] == (
        "manual_placeholder"
    )
    assert by_kind["weather_daylight_evidence"]["weather_source_status"] == (
        "manual_placeholder"
    )
    assert by_kind["weather_daylight_evidence"]["source_ref_count"] == 3
    assert by_kind["weather_daylight_evidence"]["threshold_policy_id"] == (
        "cwa_style_mountain_weather_daylight_reference.v0"
    )
    assert by_kind["weather_daylight_evidence"]["threshold_policy_status"] == (
        "reference_only"
    )
    assert by_kind["weather_daylight_evidence"]["threshold_policy_configurable"] is True
    assert by_kind["weather_daylight_evidence"]["dark_arrival_warning_margin_min"] == 60
    assert by_kind["contour_interpretation_candidates"]["artifact_id"] == (
        "contour_interpretation.chilai_nanhua_day1.v0"
    )
    assert by_kind["contour_interpretation_candidates"]["status"] == "candidate"
    assert by_kind["contour_interpretation_candidates"]["candidate_count"] == 2
    assert by_kind["contour_interpretation_candidates"]["not_observed_fact"] is True
    assert by_kind["contour_interpretation_candidates"]["human_review_required_count"] == 2

    source_artifacts = {
        artifact["ref"]: artifact
        for artifact in artifacts
        if artifact["source"] == "pretrip_package"
    }
    gpx = source_artifacts["artifact.gpx.chilai_nanhua_day1"]
    photo = source_artifacts["artifact.photo.g11_hiking"]
    assert gpx["artifact_kind"] == "gpx"
    assert gpx["path"].endswith(".gpx")
    assert gpx["sha256"] == "a270bbc769c9c521c4bb839a6230fb3760c37478c5b3ebe57f36f5d8755f6ee7"
    assert photo["artifact_kind"] == "photo"
    assert photo["path"].endswith(".jpg")
    assert photo["sha256"] == "ff28bf2fd66c6f8a63e759800fcdb8363862832ebe7b87dc900e849f1c7a058d"


def test_missing_refs_are_reported_without_raising(tmp_path):
    project_path = tmp_path / "project.json"
    project_path.write_text(
        json.dumps(
            {
                "project_id": "missing_refs",
                "package_ref": "outputs/not_present.json",
                "route_summary_ref": "",
            }
        )
    )

    manifest = build_pretrip_artifact_manifest(project_path).to_dict()
    by_kind = {artifact["artifact_kind"]: artifact for artifact in manifest["artifacts"]}

    assert manifest["counts"] == {
        "missing_refs": len(PROJECT_ARTIFACTS),
        "project_artifacts": len(PROJECT_ARTIFACTS),
        "source_artifacts": 0,
        "total_artifacts": len(PROJECT_ARTIFACTS),
    }
    assert by_kind["pretrip_package"]["missing_reason"] == "referenced_file_missing"
    assert by_kind["pretrip_package"]["ref"] == "outputs/not_present.json"
    assert by_kind["route_summary"]["missing_reason"] == "project_ref_absent"
    assert by_kind["route_comparison"]["missing"] is True
    assert "ref" not in by_kind["dtm_coverage_summary"]
    assert by_kind["readiness_report"]["missing"] is True
    assert by_kind["retreat_route_candidates"]["missing"] is True
    assert by_kind["map_context_geojson"]["missing"] is True
    assert by_kind["map_candidates"]["missing"] is True
    assert by_kind["planning_references"]["missing"] is True
    assert by_kind["route_guide_timing_candidates"]["missing"] is True
    assert by_kind["compiled_mission_graph_candidate"]["missing"] is True
    assert by_kind["human_review_log"]["missing"] is True
    assert by_kind["reviewed_pretrip_package"]["missing"] is True
    assert by_kind["compiled_mission_graph_reviewed"]["missing"] is True
    assert by_kind["timing_measurements"]["missing"] is True
    assert by_kind["planned_eta"]["missing"] is True
    assert by_kind["brain_seed_nodes"]["missing"] is True
    assert by_kind["planning_skill_audit"]["missing"] is True
    assert by_kind["poi_readiness_candidates"]["missing"] is True
    assert by_kind["segment_policy_candidates"]["missing"] is True
    assert by_kind["plan_validation_candidates"]["missing"] is True
    assert by_kind["runtime_audit_manifest"]["missing"] is True
    assert by_kind["runtime_handoff_metadata"]["missing"] is True
    assert by_kind["after_action_next_plan_candidates"]["missing"] is True
    assert by_kind["review_decision_apply_plan"]["missing"] is True
    assert by_kind["remote_contact_summary"]["missing"] is True
    assert by_kind["resource_plan"]["missing"] is True
    assert by_kind["weather_daylight_evidence"]["missing"] is True
    assert by_kind["contour_interpretation_candidates"]["missing"] is True


def test_manifest_does_not_embed_raw_dtm_gpx_or_photo_contents():
    manifest_json = build_pretrip_artifact_manifest(PROJECT_PATH).to_json()
    manifest = json.loads(manifest_json)

    assert "<trkpt" not in manifest_json
    assert "candidate_tiles" not in manifest_json
    assert "grid_uri" not in manifest_json
    assert "header_uri" not in manifest_json
    assert "image/jpeg" in manifest_json

    for artifact in manifest["artifacts"]:
        assert "content" not in artifact
        assert "contents" not in artifact
        assert "data" not in artifact
        if artifact["artifact_kind"] in {"gpx", "photo"}:
            assert set(artifact) <= {
                "artifact_kind",
                "media_type",
                "path",
                "ref",
                "sha256",
                "size_bytes",
                "source",
            }
