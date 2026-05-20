import json
import shutil
from pathlib import Path

import pytest

from pretrip_admin_view import build_pretrip_admin_view, list_pretrip_admin_projects


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "chilai_nanhua_day1"


def test_builds_fixture_backed_pretrip_admin_view():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    assert view["project_id"] == PROJECT_ID
    assert view["summary"]["route_name"] == "奇萊南華-能高越嶺步道Day1"
    assert view["summary"]["status"] == "candidate"
    assert view["route"]["point_count"] == 2211
    assert view["route"]["distance_m"] == 14599.78
    assert len(view["route"]["point_samples"]) == 3
    assert len(view["route"]["polyline"]) >= 2
    assert len(view["checkpoints"]) == 11
    assert len(view["segments"]) == 10
    assert len(view["retreat_routes"]) == 1
    assert view["map_candidates"]["counts"] == {
        "corridor_candidates": 1,
        "hazard_candidates": 1,
        "poi_candidates": 1,
    }
    assert view["readiness"]["status"] == "ready"
    assert view["eta"]["target_eta"] == "2026-05-03T15:25:35+08:00"
    assert view["route_notes"]["counts"]["note_candidate_count"] == 81
    assert view["route_notes"]["counts"]["potential_ln_signal_count"] == 21
    assert view["route_notes"]["boundary"]["requires_human_review_before_ln_upgrade"] is True
    route_note_candidate = view["route_notes"]["candidates"][0]
    assert route_note_candidate["source_id"] == route_note_candidate["candidate_id"]
    assert route_note_candidate["source_path"].endswith(
        "candidates/route_note_candidates.json"
    )
    assert route_note_candidate["evidence_type"] == "pretrip_route_note_candidate"
    assert view["route_note_ln_proposals"]["counts"]["proposal_count"] == 21
    assert (
        view["route_note_ln_proposals"]["counts"]["warning_coverage_proposal_count"]
        == 2
    )
    assert (
        view["route_note_ln_proposals"]["boundary"][
            "human_review_required_before_use"
        ]
        is True
    )
    assert view["route_note_review_options"]["counts"]["review_option_count"] == 21
    assert (
        view["route_note_review_options"]["counts"]["decision_recorded_count"]
        == 0
    )
    assert view["route_note_review_options"]["boundary"]["draft_only"] is True
    assert view["review_queue"]["counts"]["item_count"] == 42
    assert view["review_queue"]["counts"]["category_counts"]["route_note"] == 21
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
        "retreat",
        "segments",
        "checkpoints",
        "pois",
        "route-notes",
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
    assert view["tabs"]["pre_trip_planning"]["map_layers"] == view["map_layers"]


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


def test_view_is_summary_only_and_has_traceable_source_refs():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    samples = [
        view["summary"],
        view["route"],
        view["checkpoints"][0],
        view["segments"][0],
        view["retreat_routes"][0],
        view["map_candidates"]["hazard_candidates"][0],
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
    assert raw_summary["terrain_metadata"]["candidate_tile_count"] == 10
    assert raw_summary["terrain_metadata"]["segment_count"] == 10
    assert "raw_samples" not in str(raw_summary)


def test_view_exposes_planning_and_post_analysis_tabs():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    assert set(view["tabs"]) == {"pre_trip_planning", "post_analysis"}
    planning = view["tabs"]["pre_trip_planning"]
    post = view["tabs"]["post_analysis"]
    assert planning["review_queue"]["boundary"]["candidate_queue_only"] is True
    assert planning["review_draft_log"]["boundary"]["draft_only"] is True
    assert planning["review_draft_log"]["boundary"]["decisions_recorded"] is False
    assert planning["review_draft_log"]["boundary"]["package_mutation_allowed"] is False
    assert planning["review_draft_log"]["boundary"]["source_mutation_allowed"] is False
    assert planning["review_draft_log"]["boundary"]["runtime_mutation_allowed"] is False
    assert planning["review_draft_log"]["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert planning["review_decision_apply_plan"]["source_path"].endswith(
        "outputs/review_decision_apply_plan.json"
    )
    assert planning["review_decision_apply_plan"]["boundary"]["would_apply_only"] is True
    assert (
        planning["review_decision_apply_plan"]["boundary"][
            "package_mutation_allowed"
        ]
        is False
    )
    assert (
        planning["review_decision_apply_plan"]["boundary"]["source_mutation_allowed"]
        is False
    )
    assert (
        planning["review_decision_apply_plan"]["boundary"]["runtime_mutation_allowed"]
        is False
    )
    assert (
        planning["review_decision_apply_plan"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        planning["review_decision_apply_plan"]["boundary"]["phase2_writeback_allowed"]
        is False
    )
    assert (
        planning["review_decision_apply_plan"]["boundary"]["compiles_mission_graph"]
        is False
    )
    assert planning["resources"]["raw_payloads_embedded"] is False
    assert planning["weather"]["external_api_calls_made"] is False
    assert post["runtime_handoff"]["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert post["after_action_next_plan"]["historical_evidence_mutation_allowed"] is False
    assert post["brain_seed"]["observed_fact_count"] == 0


def test_tabs_expose_compact_traceable_detail_sections():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    planning_sections = view["tabs"]["pre_trip_planning"]["sections"]
    post_sections = view["tabs"]["post_analysis"]["sections"]

    assert [(section["id"], section["title"]) for section in planning_sections] == [
        ("eta", "ETA Plan"),
        ("readiness", "Readiness"),
        ("resources", "Resources"),
        ("weather", "Weather And Daylight"),
        ("route_notes", "Route Notes"),
        ("route_note_ln_proposals", "Route Note Ln Proposals"),
        ("route_note_review_options", "Route Note Review Options"),
        ("review_queue", "Review Queue"),
        ("review_draft_log", "Review Draft Log"),
        ("review_decision_log", "Review Decision Log"),
        ("review_decision_apply_plan", "Review Decision Apply Plan"),
        ("external_import_queue", "External Import Queue"),
        ("expert_contributions", "Expert Contributions"),
        ("departure_bundle", "Departure Bundle"),
    ]
    assert [(section["id"], section["title"]) for section in post_sections] == [
        ("runtime_handoff", "Runtime Handoff"),
        ("route_comparison", "Route Comparison"),
        ("brain_seed", "Brain Seed"),
        ("after_action_next_plan", "After-Action Next Plan"),
    ]

    sections_by_id = {
        section["id"]: section for section in [*planning_sections, *post_sections]
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
    assert sections_by_id["review_queue"]["counts"]["item_count"] == 42
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
    assert sections_by_id["route_notes"]["summary"]["hazard_hint_count"] == 2
    assert sections_by_id["route_notes"]["summary"]["potential_ln_signal_count"] == 21
    assert sections_by_id["route_notes"]["boundary"]["raw_gpx_embedded"] is False
    assert sections_by_id["route_note_ln_proposals"]["counts"]["proposal_count"] == 21
    assert (
        sections_by_id["route_note_ln_proposals"]["summary"][
            "warning_coverage_proposal_count"
        ]
        == 2
    )
    assert (
        sections_by_id["route_note_ln_proposals"]["boundary"][
            "runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["route_note_review_options"]["counts"]["review_option_count"] == 21
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
            "name": "奇萊南華-能高越嶺步道Day1",
            "kind": "phase4_pretrip_fixture",
        }
    ]
    with pytest.raises(KeyError):
        build_pretrip_admin_view("missing", root=ROOT)
