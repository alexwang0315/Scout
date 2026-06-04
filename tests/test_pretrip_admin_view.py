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


def _assert_pretrip_candidate_metadata(item):
    assert item["review_state"]
    assert item["candidate_only"] is True
    assert item["runtime_safety_truth"] is False
    assert item["source_refs"]
    assert item["source_attribution"]
    assert item["confidence"] not in (None, "")
    assert item["stale_risk"] not in (None, "")
    assert item["extractor_version"]
    assert item["pydantic_ai_prompt_version"]
    assert len(item["model_output_sha256"]) == 64
    assert "runtime safety truth" in item["model_output_summary"]


PRETRIP_SPEC_METADATA_FIELDS = (
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


PRETRIP_EVIDENCE_LIST_MARKERS = (
    "candidate",
    "proposal",
    "review",
    "risk",
    "gis",
    "route_note",
    "mcp",
    "contour",
    "segment_policy",
    "poi_readiness",
    "overpass",
    "map_candidates",
    "retreat",
    "spatial_imprints",
    "workbench",
    "expert_contributions",
    "reference_tracks",
    "external_import",
    "capability_timeline",
    "sections",
    "candidate_tiles",
    "preview_judgements",
    "checkpoint",
    "segment",
    "ln_",
    "terrain",
    "hazard",
    "water",
    "shelter",
    "map_layers",
)


PRETRIP_EVIDENCE_LIST_IGNORE_MARKERS = (
    ".coordinates",
    "source_attribution",
    "source_refs",
    "provenance",
    "nearest_scout_cp",
    "score_components",
    "boundary",
    "source_family_coverage",
    "payload",
    "counts",
    "histogram",
    "visualization_spec",
    "slope_class_breaks",
    "bbox",
    "bounds",
    "segment_ref",
    "checkpoint_ref",
    "latest_status",
    "state_counts",
)


def _pretrip_spec_evidence_metadata_gaps(view):
    gaps = []

    def is_candidate_evidence_list(path, items):
        path_lower = path.lower()
        if any(marker in path_lower for marker in PRETRIP_EVIDENCE_LIST_IGNORE_MARKERS):
            return False
        keys = set().union(*(item.keys() for item in items[:20]))
        return (
            any(marker in path_lower for marker in PRETRIP_EVIDENCE_LIST_MARKERS)
            or bool(
                {
                    "candidate_id",
                    "evidence_type",
                    "review_state",
                    "candidate_only",
                    "runtime_safety_truth",
                    "source_refs",
                    "source_attribution",
                }
                & keys
            )
        )

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else key)
            return
        if not (
            isinstance(value, list)
            and value
            and all(isinstance(item, dict) for item in value)
            and is_candidate_evidence_list(path, value)
        ):
            return
        missing_counts = {field: 0 for field in PRETRIP_SPEC_METADATA_FIELDS}
        runtime_truth_count = 0
        for item in value:
            for field in PRETRIP_SPEC_METADATA_FIELDS:
                if item.get(field) in (None, "", []):
                    missing_counts[field] += 1
            if item.get("runtime_safety_truth") is not False:
                runtime_truth_count += 1
        missing_counts = {
            field: count
            for field, count in missing_counts.items()
            if count
        }
        if missing_counts or runtime_truth_count:
            gaps.append(
                {
                    "path": path,
                    "item_count": len(value),
                    "missing_counts": missing_counts,
                    "runtime_truth_count": runtime_truth_count,
                }
            )
        walk(value[0], f"{path}[0]")

    walk(view)
    return gaps


def test_pretrip_candidate_evidence_lists_preserve_spec_metadata():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    gaps = _pretrip_spec_evidence_metadata_gaps(view)

    assert gaps == []


def test_pretrip_admin_evidence_summaries_preserve_spec_metadata():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)
    summary_keys = (
        "summary",
        "route",
        "map_candidates",
        "readiness",
        "eta",
        "route_notes",
        "reference_tracks",
        "checkpoint_events",
        "layer_preparation",
        "risk_score",
        "risk_ribbon",
        "risk_heatmap",
        "risk_delta",
        "overpass_evidence",
        "gis_perception",
        "gis_perception_timeline",
        "route_note_ln_proposals",
        "route_note_review_options",
        "review_queue",
        "review_workbench",
        "review_draft_log",
        "review_decision_log",
        "review_decision_apply_plan",
        "external_import_queue",
        "expert_contributions",
        "major_critical_points",
        "spatial_imprints",
        "departure_bundle",
        "resources",
        "weather",
        "contours",
        "import_manifest",
        "admin_surface_projection",
        "debug_projection",
        "segment_terrain",
        "planning_skill_audit",
        "planning_skill_manifest_catalog",
        "capability_timeline_import",
        "companion_match_review",
        "post_analysis_energy_feedback",
    )

    missing = {}
    for key in summary_keys:
        summary = view.get(key)
        if not isinstance(summary, dict):
            continue
        gaps = [
            field
            for field in PRETRIP_SPEC_METADATA_FIELDS
            if summary.get(field) in (None, "", [])
        ]
        if gaps or summary.get("runtime_safety_truth") is not False:
            missing[key] = {
                "missing": gaps,
                "runtime_safety_truth": summary.get("runtime_safety_truth"),
            }

    assert missing == {}


def test_builds_fixture_backed_pretrip_admin_view():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    assert view["project_id"] == PROJECT_ID
    assert view["summary"]["route_name"] == "2013-10-08 10:58:50 每日記錄"
    assert view["summary"]["status"] == "candidate"
    assert view["route"]["point_count"] == 2612
    assert view["route"]["distance_m"] == 55174.67
    assert len(view["route"]["point_samples"]) == 3
    assert len(view["route"]["polyline"]) >= 2
    assert len(view["checkpoints"]) == 124
    assert len(view["segments"]) == 123
    segment_040 = next(segment for segment in view["segments"] if segment["candidate_id"] == "seg.040")
    assert segment_040["distance_m"] < 1000.0
    assert view["admin_surface_projection"]["route"]["gpx_speed_filter"][
        "removed_track_point_count"
    ] == 60417
    assert view["admin_surface_projection"]["route"]["gpx_speed_filter"][
        "max_previous_speed_ratio"
    ] == 8.0
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
    _assert_pretrip_candidate_metadata(
        view["reference_tracks"]["reference_tracks"][0]
    )
    assert view["checkpoint_events"]["event_count"] == 124
    assert view["checkpoint_events"]["source_gpx"]["point_count"] == 2612
    assert view["checkpoint_events"]["source_gpx"]["trimming_performed"] is False
    _assert_pretrip_candidate_metadata(view["checkpoint_events"]["events"][0])
    _assert_pretrip_candidate_metadata(view["checkpoints"][0])
    _assert_pretrip_candidate_metadata(view["segments"][0])
    _assert_pretrip_candidate_metadata(view["retreat_routes"][0])
    assert view["map_candidates"]["counts"] == {
        "corridor_candidates": 1,
        "hazard_candidates": 0,
        "poi_candidates": 2,
    }
    _assert_pretrip_candidate_metadata(
        view["map_candidates"]["corridor_candidates"][0]
    )
    _assert_pretrip_candidate_metadata(view["map_candidates"]["poi_candidates"][0])
    assert view["overpass_evidence"]["counts"]["candidates"] == 219
    assert view["overpass_evidence"]["counts"]["skipped"] == 0
    assert len(view["overpass_evidence"]["corridor_candidates"]) == 191
    assert len(view["overpass_evidence"]["hazard_candidates"]) == 0
    assert len(view["overpass_evidence"]["poi_candidates"]) == 28
    _assert_pretrip_candidate_metadata(
        view["overpass_evidence"]["corridor_candidates"][0]
    )
    _assert_pretrip_candidate_metadata(view["overpass_evidence"]["poi_candidates"][0])
    assert view["overpass_evidence"]["boundary"]["runtime_truth"] is False
    assert view["overpass_evidence"]["boundary"]["live_network_required"] is False
    assert view["overpass_evidence"]["request"]["endpoint"] == "https://overpass-api.de/api/interpreter"
    assert view["evidence_timeline"]["artifact_kind"] == "scout_cross_surface_evidence_timeline"
    assert view["evidence_timeline"]["category_order"] == [
        "route",
        "checkpoints",
        "segments",
        "capability_timeline",
        "rest_intervals",
        "mcp",
        "gis_cp",
        "risk",
        "map_context",
        "reference_tracks",
        "review",
        "runtime_handoff",
    ]
    assert view["evidence_timeline"]["counts"] == {
        "category_count": 12,
        "available_category_count": 12,
        "total_evidence_count": 6656,
    }
    assert view["scout_agent_skills"]["artifact_kind"] == "scout_agent_skill_registry_summary"
    assert view["scout_agent_skills"]["counts"]["tool_count"] == 45
    assert view["scout_agent_skills"]["boundary"]["tool_execution_allowed_from_ui"] is False
    assert view["tabs"]["agent_skills"]["sections"][0]["id"] == "scout_agent_skills"
    assert view["readiness"]["status"] == "ready"
    assert view["eta"]["target_eta"] == "2013-10-08T18:28:50+08:00"
    assert view["route_notes"]["counts"]["note_candidate_count"] == 4406
    assert view["route_notes"]["counts"]["potential_ln_signal_count"] == 197
    assert view["route_notes"]["counts"]["stale_route_note_count"] == 611
    assert view["route_notes"]["boundary"]["requires_human_review_before_ln_upgrade"] is True
    route_note_candidate = view["route_notes"]["candidates"][0]
    assert route_note_candidate["source_id"] == route_note_candidate["candidate_id"]
    assert route_note_candidate["source_path"].endswith(
        "candidates/route_note_candidates.json"
    )
    assert route_note_candidate["evidence_type"] == "pretrip_route_note_candidate"
    assert route_note_candidate["route_note_freshness"] == "stale"
    assert route_note_candidate["stale_route_note"] is True
    assert route_note_candidate["review_state"] == "needs_review"
    assert route_note_candidate["source_attribution"][0]["source_kind"] == "gpx_route_note"
    assert route_note_candidate["pydantic_ai_prompt_version"]
    assert len(route_note_candidate["model_output_sha256"]) == 64
    assert view["route_note_ln_proposals"]["counts"]["proposal_count"] == 197
    assert (
        view["route_note_ln_proposals"]["counts"]["warning_coverage_proposal_count"]
        == 113
    )
    assert (
        view["route_note_ln_proposals"]["boundary"][
            "human_review_required_before_use"
        ]
        is True
    )
    ln_proposal = view["route_note_ln_proposals"]["proposals"][0]
    assert ln_proposal["review_state"] == "needs_review"
    assert ln_proposal["source_attribution"][0]["source_kind"] == "route_note_candidate"
    assert ln_proposal["pydantic_ai_prompt_version"]
    assert len(ln_proposal["model_output_sha256"]) == 64
    assert ln_proposal["confidence"] in {"low", "medium", "high"}
    assert ln_proposal["stale_risk"] in {"low", "medium", "high", "unknown"}
    assert view["route_note_review_options"]["counts"]["review_option_count"] == 197
    assert (
        view["route_note_review_options"]["counts"]["decision_recorded_count"]
        == 0
    )
    assert view["route_note_review_options"]["boundary"]["draft_only"] is True
    review_option = view["route_note_review_options"]["options"][0]
    assert review_option["review_state"] == "draft"
    assert review_option["source_attribution"][0]["source_kind"] == (
        "route_note_ln_proposal"
    )
    assert review_option["pydantic_ai_prompt_version"]
    assert len(review_option["model_output_sha256"]) == 64
    assert review_option["confidence"] in {"low", "medium", "high"}
    assert review_option["stale_risk"] in {"low", "medium", "high", "unknown"}
    assert view["risk_ribbon"]["status"] == "candidate_only"
    assert view["risk_ribbon"]["counts"]["segment_count"] == 841
    assert view["risk_ribbon"]["counts"]["source_sample_count"] == 842
    assert view["risk_ribbon"]["boundary"]["candidate_only"] is True
    assert view["risk_ribbon"]["boundary"]["runtime_safety_truth"] is False
    assert view["risk_ribbon"]["boundary"]["interpolated_surface"] is False
    assert view["risk_ribbon"]["segments"][0]["evidence_type"] == (
        "pretrip_risk_ribbon_segment"
    )
    assert view["risk_ribbon"]["segments"][0]["review_state"] == "needs_review"
    assert view["risk_ribbon"]["segments"][0]["candidate_only"] is True
    assert view["risk_ribbon"]["segments"][0]["runtime_safety_truth"] is False
    assert view["risk_ribbon"]["segments"][0]["source_refs"]
    assert view["risk_ribbon"]["segments"][0]["extractor_version"] == (
        "scout_risk_engine.heuristic_projection.v1"
    )
    assert view["risk_ribbon"]["segments"][0]["pydantic_ai_prompt_version"] == (
        "not_applicable_deterministic_risk_projection.v1"
    )
    assert len(view["risk_ribbon"]["segments"][0]["model_output_sha256"]) == 64
    assert "pretrip evidence only" in view["risk_ribbon"]["segments"][0][
        "model_output_summary"
    ]
    assert view["risk_ribbon"]["segments"][0]["coordinates"][0] == {
        "lon": 121.1749947,
        "lat": 23.9536093,
    }
    assert view["gis_perception_timeline"]["counts"]["overpass_checkpoint_candidate_count"] == 9
    assert view["gis_perception_timeline"]["counts"]["checkpoint_candidate_count"] == 304
    if view["gis_perception"]["checkpoint_candidates"]:
        raw_gis_cp = view["gis_perception"]["checkpoint_candidates"][0]
        assert raw_gis_cp["review_state"] == "needs_review"
        assert raw_gis_cp["candidate_only"] is True
        assert raw_gis_cp["runtime_safety_truth"] is False
        assert raw_gis_cp["source_refs"]
        assert raw_gis_cp["confidence"] in {"low", "medium", "high", "unknown"}
        assert raw_gis_cp["stale_risk"] in {"low", "medium", "high", "unknown"}
        assert raw_gis_cp["extractor_version"] == "0.1.0"
        assert raw_gis_cp["pydantic_ai_prompt_version"] == (
            "scout.gis_perception.structured_judgement.v0"
        )
        assert len(raw_gis_cp["model_output_sha256"]) == 64
        assert "candidate-only" in raw_gis_cp["model_output_summary"]
    timeline_gis_cp = view["gis_perception_timeline"]["checkpoint_candidates"][0]
    assert timeline_gis_cp["review_state"] == "needs_review"
    assert timeline_gis_cp["candidate_only"] is True
    assert timeline_gis_cp["runtime_safety_truth"] is False
    assert timeline_gis_cp["display_label"] == "3159南鞍營地"
    assert timeline_gis_cp["map_label"] == "3159南鞍營地"
    clustered_gis_cp = view["gis_perception_timeline"]["checkpoint_candidates"][1]
    assert clustered_gis_cp["candidate_id"].startswith("gis_cp_cluster.")
    assert clustered_gis_cp["display_label"] == "上切 / 108 上切點 / 103上切點"
    assert "gis_cp_cluster" not in clustered_gis_cp["display_label"]
    assert timeline_gis_cp["source_refs"]
    assert timeline_gis_cp["source_attribution"]
    assert len(timeline_gis_cp["model_output_sha256"]) == 64
    if view["gis_perception_timeline"]["nearby_groups"]:
        nearby_group = view["gis_perception_timeline"]["nearby_groups"][0]
        assert nearby_group["review_state"] == "display_group_only"
        assert nearby_group["candidate_only"] is True
        assert nearby_group["runtime_safety_truth"] is False
        assert nearby_group["display_label"].startswith("附近 CP: ")
        assert "gis_cp_nearby_group" not in nearby_group["display_label"]
        assert nearby_group["semantic_merge_allowed"] is False
        assert nearby_group["source_refs"]
        assert nearby_group["source_attribution"]
        assert len(nearby_group["model_output_sha256"]) == 64
    overpass_without_name = next(
        candidate
        for candidate in view["gis_perception_timeline"]["checkpoint_candidates"]
        if candidate.get("source_profile") == "overpass_osm_tags"
        and candidate.get("display_label") == "OSM 避難點"
    )
    assert "node/" not in overpass_without_name["display_label"]
    named_overpass = next(
        candidate
        for candidate in view["gis_perception_timeline"]["checkpoint_candidates"]
        if candidate.get("display_label") == "岩壁水源"
    )
    assert named_overpass["map_label"] == "岩壁水源"
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
    _assert_pretrip_candidate_metadata(
        view["major_critical_points"]["retrieval"]["queries"][0]
    )
    _assert_pretrip_candidate_metadata(
        view["major_critical_points"]["retrieval"]["fetch_summaries"][0]
    )
    _assert_pretrip_candidate_metadata(view["major_critical_points"]["ocr"]["labels"][0])
    _assert_pretrip_candidate_metadata(
        view["major_critical_points"]["cp_support_reconciliation"]["rows"][0]
    )
    assert (
        view["major_critical_points"]["retrieval"]["queries"][0][
            "source_attribution"
        ][0]["source_kind"]
        == "mcp_retrieval_query"
    )
    assert (
        view["major_critical_points"]["retrieval"]["fetch_summaries"][0][
            "source_attribution"
        ][0]["source_kind"]
        == "mcp_retrieval_fetch_summary"
    )
    assert (
        view["major_critical_points"]["ocr"]["labels"][0]["source_attribution"][0][
            "source_kind"
        ]
        == "mcp_ocr_label"
    )
    assert (
        view["major_critical_points"]["cp_support_reconciliation"]["rows"][0][
            "source_attribution"
        ][0]["source_kind"]
        == "mcp_cp_support_reconciliation"
    )
    assert (
        view["major_critical_points"]["cp_support_reconciliation"][
            "suggested_insertion_count"
        ]
        == 1
    )
    _assert_pretrip_candidate_metadata(view["major_critical_points"]["candidates"][0])
    assert view["major_critical_points"]["boundary"]["runtime_safety_truth"] is False
    assert view["major_critical_points"]["boundary"]["compile_allowed"] is False
    assert any(
        candidate["label"] == "黑水塘"
        and candidate["source_family_coverage"]["mandatory_complete"] is True
        for candidate in view["major_critical_points"]["candidates"]
    )
    source_profiles = {
        candidate["source_profile"]
        for candidate in view["gis_perception_timeline"]["checkpoint_candidates"]
    }
    assert "gpx_corpus_route_notes" in source_profiles
    assert "overpass_osm_tags" in source_profiles
    assert any(
        attribution["source_kind"] == "overpass_candidate"
        for candidate in view["gis_perception_timeline"]["checkpoint_candidates"]
        for attribution in candidate["source_attribution"]
    )
    assert view["review_queue"]["counts"]["item_count"] == 447
    assert view["review_queue"]["counts"]["category_counts"]["route_note"] == 23
    assert view["review_queue"]["counts"]["category_counts"]["gis_perception_cp"] == 304
    first_review_item = view["review_queue"]["items"][0]
    assert first_review_item["review_state"] == "needs_review"
    assert first_review_item["candidate_only"] is True
    assert first_review_item["runtime_safety_truth"] is False
    assert first_review_item["source_refs"]
    assert first_review_item["source_attribution"][0]["runtime_safety_truth"] is False
    assert first_review_item["extractor_version"] == (
        "pretrip_admin_review_queue_projection.v1"
    )
    assert first_review_item["pydantic_ai_prompt_version"] == (
        "not_applicable_deterministic_review_queue_projection.v1"
    )
    assert len(first_review_item["model_output_sha256"]) == 64
    _assert_pretrip_candidate_metadata(view["review_workbench"]["category_groups"][0])
    _assert_pretrip_candidate_metadata(view["review_workbench"]["severity_groups"][0])
    _assert_pretrip_candidate_metadata(view["review_draft_log"]["actions"][0])
    _assert_pretrip_candidate_metadata(view["review_decision_log"]["decisions"][0])
    _assert_pretrip_candidate_metadata(
        view["review_decision_apply_plan"]["decisions"][0]
    )
    _assert_pretrip_candidate_metadata(view["external_import_queue"]["requests"][0])
    _assert_pretrip_candidate_metadata(view["expert_contributions"]["records"][0])
    _assert_pretrip_candidate_metadata(view["spatial_imprints"]["candidates"][0])
    _assert_pretrip_candidate_metadata(view["spatial_imprints"]["reviews"][0])
    _assert_pretrip_candidate_metadata(
        view["spatial_imprints"]["reviewed_imprints"][0]
    )
    _assert_pretrip_candidate_metadata(view["contours"]["candidates"][0])
    _assert_pretrip_candidate_metadata(
        view["segment_terrain"]["segment_metadata"][0]
    )
    assert first_review_item["model_output_summary"]
    assert view["review_workbench"]["status"] == "projection_only"
    assert view["review_workbench"]["counts"]["category_group_count"] == 8
    assert view["review_workbench"]["counts"]["bulk_eligible_count"] == 376
    assert view["review_workbench"]["counts"]["single_review_required_count"] == 71
    assert view["review_workbench"]["boundary"]["ai_triage_is_review_aid"] is True
    assert view["review_workbench"]["boundary"]["runtime_safety_truth"] is False
    assert any(
        group["group_id"] == "review_group.category.gis_perception_cp"
        and group["bulk_eligible_count"] == 247
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
    _assert_pretrip_candidate_metadata(view["departure_bundle"]["terrain_refs"][0])
    assert [layer["layer_id"] for layer in view["map_layers"]] == [
        "imagery",
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
        "osm",
        "terrain",
        "corridors",
        "overpass",
        "route",
        "reference-tracks",
        "retreat",
        "segments",
        "risk-score",
        "risk-ribbon",
        "risk-heatmap",
        "risk-delta",
        "checkpoints",
        "pois",
        "hazards",
        "mcp",
        "route-notes",
        "events",
        "weather-api",
    ]
    assert view["map_layers"][0]["label_zh"].startswith("影像圖層")
    _assert_pretrip_candidate_metadata(view["map_layers"][0])
    assert view["map_layers"][0]["local_raster_manifest_supported"] is False
    assert view["map_layers"][0]["raster_tile_delivery"] == "direct_wmts_runtime"
    assert view["map_layers"][0]["external_network_required"] is True
    terrain_layer = next(layer for layer in view["map_layers"] if layer["layer_id"] == "terrain")
    assert terrain_layer["terrain_visualization_layer"] is True
    assert terrain_layer["risk_heat_layer"] is False
    assert terrain_layer["runtime_safety_truth"] is False
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
    assert capability["counts"] == {"edge_count": 73, "rest_interval_count": 62}
    assert capability["summary"]["moving_time_s"] == 121605
    assert capability["summary"]["rest_time_s"] == 220479
    assert capability["privacy"]["raw_track_shared"] is False
    assert capability["privacy"]["exact_timestamps_shared"] is False
    assert capability["privacy"]["incident_details_shared"] is False
    assert capability["planning_use"]["candidate_pacing_reference_only"] is True
    assert capability["planning_use"]["auto_applies_to_eta"] is False
    assert capability["planning_use"]["auto_compiles_mission_graph"] is False
    assert capability["boundary"]["runtime_safety_truth"] is False
    assert capability["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert capability["boundary"]["mission_graph_compile_allowed"] is False


def test_layer_preparation_rows_preserve_spec_metadata_after_workspace_run(
    tmp_path: Path,
) -> None:
    fixture_project_root = (
        ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID
    )
    workspace_project_root = tmp_path / PROJECT_ID
    shutil.copytree(fixture_project_root, workspace_project_root)

    run_layer_preparation(
        LayerPreparationRequest(
            project_id=PROJECT_ID,
            project_root=workspace_project_root,
            layers=(
                "osm",
                "overpass",
                "terrain",
                "imagery",
                "weather",
                "reference-tracks",
                "route",
                "segments",
                "checkpoints",
            ),
            prepared_at="2026-05-22T00:00:00+00:00",
        )
    )

    view = build_pretrip_admin_view(
        PROJECT_ID,
        root=ROOT,
        project_root=workspace_project_root,
    )

    rows = view["layer_preparation"]["layers"]
    assert len(rows) == 9
    for row in rows:
        assert row["evidence_type"] == "pretrip_layer_preparation_layer"
        assert row["source_path"] == "outputs/layers/layer_preparation_manifest.json"
        _assert_pretrip_candidate_metadata(row)

    assert _pretrip_spec_evidence_metadata_gaps(view) == []


def test_map_layers_expose_local_raster_coverage_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / PROJECT_ID
    shutil.copytree(ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PROJECT_ID, project_root)
    manifest_dir = project_root / "outputs" / "layers" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    raster_ref = (
        "outputs/layers/manifests/"
        "chilai_nanhua_day1.local_raster_source_manifest.json"
    )
    tile_ref = (
        "outputs/layers/manifests/"
        "chilai_nanhua_day1.raster_tile_pyramid_plan.json"
    )
    rudy_twmap_ref = (
        "outputs/layers/manifests/"
        "raster_tile_manifest.happyman_rudy_twmap.z12-z14.json"
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["local_raster_manifest_ref"] = raster_ref
    project["raster_tile_manifest_ref"] = tile_ref
    project["raster_layer_manifest_refs"] = {"rudy-twmap": rudy_twmap_ref}
    project_path.write_text(json.dumps(project, sort_keys=True), encoding="utf-8")
    (project_root / raster_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_local_raster_source_manifest",
                "georeference": {
                    "bbox_wgs84": {
                        "west": 121.21478855,
                        "south": 24.03365911,
                        "east": 121.30320941,
                        "north": 24.06992621,
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (project_root / tile_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_local_raster_tile_pyramid_plan",
                "bbox_wgs84": {
                    "west": 121.21478855,
                    "south": 24.03365911,
                    "east": 121.30320941,
                    "north": 24.06992621,
                },
                "zoom_range": "5-14",
                "cache_root": "/data/scout/raster-tiles",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (project_root / rudy_twmap_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "admin_imagery_tile_cache_plan",
                "bbox_wgs84": {
                    "west": 121.22,
                    "south": 24.04,
                    "east": 121.3,
                    "north": 24.06,
                },
                "zoom_range": "12-14",
                "min_zoom": 12,
                "max_zoom": 14,
                "cache_root": "/data/scout/raster-tiles",
                "total_tile_count": 25,
                "source_id": "happyman_rudy_twmap",
                "source_kind": "wmts_kvp_tile",
                "runtime_tile_url_template": (
                    "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
                ),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT, project_root=project_root)
    debug = load_pretrip_debug_projection_view(
        PROJECT_ID,
        root=ROOT,
        project_root=project_root,
    )

    for layer_set in (view["map_layers"], debug["map_layers"]):
        imagery = next(layer for layer in layer_set if layer["layer_id"] == "imagery")
        assert imagery["raster_tile_delivery"] == "direct_wmts_runtime"
        assert imagery["raster_coverage_policy"] == "render_visible_wmts_tiles_only"
        assert "raster_bbox_wgs84" not in imagery
        assert "local_raster_manifest_ref" not in imagery
        assert "raster_tile_manifest_ref" not in imagery
        assert "raster_layer_manifest_refs" not in imagery
        assert "raster_layer_manifests" not in imagery
        rudy_twmap = next(layer for layer in layer_set if layer["layer_id"] == "rudy-twmap")
        assert rudy_twmap["raster_tile_delivery"] == "direct_wmts_runtime"
        assert rudy_twmap["imagery_source_id"] == "happyman_rudy_twmap"


def test_loads_debug_projection_view_with_shared_map_and_dense_timeline():
    projection = load_pretrip_debug_projection_view(PROJECT_ID, root=ROOT)

    assert projection["artifact_kind"] == "pretrip_debug_projection"
    assert projection["project_id"] == PROJECT_ID
    assert projection["event_count"] > 200
    assert projection["counts"]["checkpoint_candidate_count"] == 124
    assert projection["counts"]["segment_candidate_count"] == 123
    assert projection["counts"]["reference_track_count"] == 23
    assert projection["counts"]["mcp_candidate_count"] == 6
    assert projection["counts"]["mcp_suppressed_point_count"] == 2
    assert projection["counts"]["mcp_review_action_count"] == 0
    assert projection["counts"]["risk_ribbon_segment_count"] == 841
    assert "terrain_bitmap_overlay_count" in projection["counts"]
    assert "terrain_visualization" in projection
    assert projection["terrain_visualization"]["boundary"]["runtime_safety_truth"] is False
    assert projection["counts"]["source_lifecycle_event_count"] == 4
    assert projection["route"]["point_count"] == 2612
    assert (
        projection["route"]["display_geometry"]["boundary"][
            "internal_gpx_points_preserved"
        ]
        is True
    )
    assert projection["route"]["display_geometry"]["display_point_count"] > 2000
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
    assert capability["counts"] == {"edge_count": 73, "rest_interval_count": 62}
    assert capability["planning_use"]["auto_applies_to_eta"] is False
    assert capability["boundary"]["workspace_mutation_allowed"] is False
    assert capability["boundary"]["mission_graph_compile_allowed"] is False


def test_pretrip_view_exposes_energy_reserve_monitor_without_runtime_mutation():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    monitor = view["energy_reserve_monitor"]
    assert monitor["artifact_kind"] == "scout_energy_reserve_monitor"
    assert monitor["status"] == "missing_health_data"
    assert monitor["health_data"]["loaded"] is False
    assert monitor["trip_capability"]["loaded"] is True
    assert monitor["candidate_change"]["applied_to_baseline"] is False
    assert monitor["boundary"]["phase1_runtime_safety_truth"] is False
    assert monitor["boundary"]["safety_api_calls_allowed"] is False
    assert monitor["mutation"]["safety_api_called"] is False
    assert (
        view["tabs"]["pre_trip_planning"]["energy_reserve_monitor"]
        == monitor
    )


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
    assert "<time" not in sections_json


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
    assert view["risk_score"]["points"][0]["review_state"] == "needs_review"
    assert view["risk_score"]["points"][0]["candidate_only"] is True
    assert view["risk_score"]["points"][0]["runtime_safety_truth"] is False
    assert view["risk_score"]["points"][0]["confidence"] == "medium"
    assert view["risk_score"]["points"][0]["stale_risk"] == "medium"
    assert view["risk_score"]["points"][0]["source_refs"]
    assert len(view["risk_score"]["points"][0]["model_output_sha256"]) == 64
    assert "pretrip evidence only" in view["risk_score"]["points"][0][
        "model_output_summary"
    ]
    assert view["risk_score"]["boundary"]["runtime_safety_truth"] is False
    assert view["terrain_visualization"]["status"] == "candidate_only"
    assert view["terrain_visualization"]["counts"]["feature_count"] == 0
    assert view["terrain_visualization"]["counts"]["bitmap_overlay_count"] == 4
    assert view["terrain_visualization"]["counts"]["cell_count"] > 0
    assert view["terrain_visualization"]["visualization_spec"]["modes"] == [
        "hillshade",
        "elevation_tint",
        "slope_shading",
        "contours",
    ]
    assert view["terrain_visualization"]["visualization_spec"]["bitmap_overlay"] is True
    assert view["terrain_visualization"]["visualization_spec"]["bitmap_cell_resolution_m"] == 20.0
    overlays = {overlay["mode"]: overlay for overlay in view["terrain_visualization"]["raster_overlays"]}
    assert set(overlays) == {"hillshade", "elevation_tint", "slope_shading", "contours"}
    assert overlays["slope_shading"]["cell_resolution_m"] == 20.0
    assert overlays["slope_shading"]["corridor_half_width_m"] == 500.0
    assert overlays["slope_shading"]["terrain_visualization_layer"] is True
    assert overlays["slope_shading"]["risk_heat_layer"] is False
    assert overlays["slope_shading"]["runtime_safety_truth"] is False
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

    assert set(view["tabs"]) == {
        "pre_trip_planning",
        "post_analysis",
        "review_workspace",
        "agent_skills",
    }
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
    assert post["brain_seed"]["boundary"]["automatic_brain_write_allowed"] is False
    assert post["brain_seed"]["boundary"]["model_output_as_observed_fact_allowed"] is False
    assert post["planning_skill_audit"]["counts"]["record_count"] == 5
    assert post["planning_skill_audit"]["boundary"]["skill_run_record_only"] is True
    assert (
        post["planning_skill_audit"]["boundary"]["automatic_brain_write_allowed"]
        is False
    )
    assert post["planning_skill_manifest_catalog"]["counts"]["manifest_count"] == 5
    assert (
        post["planning_skill_manifest_catalog"]["boundary"][
            "live_safety_endpoint_calls_allowed"
        ]
        is False
    )
    assert post["capability_timeline_import"]["counts"]["edge_count"] == 73
    assert post["capability_timeline_import"]["planning_use"]["auto_applies_to_eta"] is False
    assert post["capability_timeline_import"]["boundary"]["runtime_safety_truth"] is False


def test_tabs_expose_compact_traceable_detail_sections():
    view = build_pretrip_admin_view(PROJECT_ID, root=ROOT)

    planning_sections = view["tabs"]["pre_trip_planning"]["sections"]
    post_sections = view["tabs"]["post_analysis"]["sections"]
    review_sections = view["tabs"]["review_workspace"]["sections"]

    assert [(section["id"], section["title"]) for section in planning_sections] == [
        ("route", "Route Evidence"),
        ("checkpoints", "Checkpoint Candidates"),
        ("segments", "Segment Candidates"),
        ("map_candidates", "Map Candidates"),
        ("retreat_routes", "Retreat Routes"),
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
        ("planning_skill_audit", "Planning Skill Audit"),
        ("planning_skill_manifest_catalog", "Planning Skill Manifest Catalog"),
        ("capability_timeline_import", "Capability Timeline Import"),
        ("import_manifest", "Import Manifest"),
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

    assert sections_by_id["route"]["counts"] == {
        "point_count": 2612,
        "polyline_point_count": 124,
        "sample_count": 3,
    }
    assert sections_by_id["route"]["boundary"]["runtime_safety_truth"] is False
    assert sections_by_id["checkpoints"]["counts"]["candidate_count"] == 124
    assert sections_by_id["checkpoints"]["summary"]["sample_candidates"][0][
        "candidate_id"
    ] == "cp.start"
    assert sections_by_id["checkpoints"]["boundary"]["mission_graph_compile_allowed"] is False
    assert sections_by_id["segments"]["counts"]["candidate_count"] == 123
    assert sections_by_id["segments"]["summary"]["sample_candidates"][0][
        "candidate_id"
    ] == "seg.001"
    assert sections_by_id["segments"]["boundary"]["mission_graph_compile_allowed"] is False
    assert sections_by_id["map_candidates"]["counts"] == {
        "corridor_candidates": 1,
        "hazard_candidates": 0,
        "poi_candidates": 2,
    }
    assert sections_by_id["map_candidates"]["boundary"]["runtime_safety_truth"] is False
    assert sections_by_id["retreat_routes"]["counts"]["candidate_count"] == 1
    assert sections_by_id["retreat_routes"]["boundary"]["runtime_safety_truth"] is False
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
    assert sections_by_id["review_queue"]["counts"]["item_count"] == 447
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
    assert sections_by_id["route_notes"]["counts"]["note_candidate_count"] == 4406
    assert sections_by_id["route_notes"]["summary"]["hazard_hint_count"] == 113
    assert sections_by_id["route_notes"]["summary"]["potential_ln_signal_count"] == 197
    assert sections_by_id["route_notes"]["boundary"]["raw_gpx_embedded"] is False
    assert sections_by_id["route_note_ln_proposals"]["counts"]["proposal_count"] == 197
    assert (
        sections_by_id["route_note_ln_proposals"]["summary"][
            "warning_coverage_proposal_count"
        ]
        == 113
    )
    assert (
        sections_by_id["route_note_ln_proposals"]["boundary"][
            "runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["route_note_review_options"]["counts"]["review_option_count"] == 197
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
    assert (
        sections_by_id["brain_seed"]["summary"][
            "non_review_gated_model_interpretation_count"
        ]
        == 0
    )
    assert (
        sections_by_id["brain_seed"]["boundary"][
            "model_output_as_observed_fact_allowed"
        ]
        is False
    )
    assert sections_by_id["planning_skill_audit"]["counts"] == {
        "automatic_brain_write_count": 0,
        "observed_fact_count": 0,
        "record_count": 5,
        "skill_run_record_count": 5,
    }
    assert sections_by_id["planning_skill_audit"]["summary"]["node_types"] == [
        "SkillRunRecord"
    ]
    assert (
        sections_by_id["planning_skill_audit"]["boundary"][
            "automatic_brain_write_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["planning_skill_audit"]["boundary"][
            "observed_fact_write_allowed"
        ]
        is False
    )
    assert sections_by_id["planning_skill_manifest_catalog"]["counts"] == {
        "automatic_brain_write_allowed_count": 0,
        "candidate_outputs_only_count": 5,
        "live_safety_endpoint_call_allowed_count": 0,
        "manifest_count": 5,
        "observed_fact_write_allowed_count": 0,
        "phase1_runtime_mutation_allowed_count": 0,
        "review_required_count": 5,
    }
    assert (
        sections_by_id["planning_skill_manifest_catalog"]["boundary"][
            "automatic_brain_write_allowed"
        ]
        is False
    )
    assert (
        sections_by_id["planning_skill_manifest_catalog"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert sections_by_id["after_action_next_plan"]["counts"]["candidate_count"] == 3
    assert sections_by_id["capability_timeline_import"]["counts"] == {
        "edge_count": 73,
        "rest_interval_count": 62,
    }
    assert sections_by_id["capability_timeline_import"]["summary"]["moving_time_s"] == 121605
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
    admin_projection_counts = sections_by_id["admin_surface_projection"]["counts"]
    assert {
        key: admin_projection_counts[key]
        for key in [
            "checkpoint_candidate_count",
            "reference_track_count",
            "segment_candidate_count",
        ]
    } == {
        "checkpoint_candidate_count": 124,
        "reference_track_count": 23,
        "segment_candidate_count": 123,
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
    assert "<time" not in sections_json


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
    assert contour["review_state"] == "needs_review"
    assert contour["confidence"] == "low"
    assert contour["stale_risk"] == "unknown"
    assert contour["candidate_only"] is True
    assert contour["runtime_safety_truth"] is False
    assert "outputs/contour_interpretation_candidates.json" in contour["source_refs"]
    assert "contour.g11.seg_001_003" in contour["source_refs"]
    assert contour["source_attribution"][0]["source_kind"] == (
        "contour_interpretation_candidates"
    )
    assert len(contour["model_output_sha256"]) == 64

    segment_policy = next(item for item in items if item["category"] == "segment_policy")
    assert segment_policy["candidate_ref"].startswith("policy_candidate.chilai_nanhua_day1.seg.")
    assert any(target.startswith("seg.") for target in segment_policy["map_target_ids"])
    assert segment_policy["review_state"] == "needs_review"
    assert segment_policy["runtime_safety_truth"] is False
    assert segment_policy["source_refs"]

    gis_cp = next(item for item in items if item["category"] == "gis_perception_cp")
    assert gis_cp["review_state"] == "needs_review"
    assert gis_cp["runtime_safety_truth"] is False
    assert gis_cp["source_refs"]
    assert gis_cp["source_attribution"]
    assert len(gis_cp["model_output_sha256"]) == 64

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
                    "elevation_m": 100.0,
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
                    "elevation_m": 110.0,
                    "teii_20m": 55.0,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.22, 24.02]},
                "properties": {
                    "sample_id": "risk.sample.003",
                    "pretrip_risk": 22.0,
                    "risk_level": 1,
                    "distance_m": 60.0,
                    "elevation_m": 160.0,
                    "teii_20m": 10.0,
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
            "route_risk_sample_count": 3,
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
