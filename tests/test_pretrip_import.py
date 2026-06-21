import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from debug_api import create_debug_app
from pretrip_admin_view import build_pretrip_admin_view
from pretrip_import import (
    PretripImportRequest,
    _dtm_source_dirs,
    restore_durable_admin_evidence_refs,
    run_pretrip_import,
)
from pretrip_source_ingest import wgs84_to_twd97
from runtime_debug_log import FileRuntimeDebugEventLog

ROOT = Path(__file__).resolve().parents[1]


def test_dtm_source_dirs_keeps_material_manifest_dirs_when_cli_adds_one(
    tmp_path: Path,
) -> None:
    material_root = tmp_path / "materials" / "chilai_nanhua_day1"
    nantou = material_root / "sources" / "dtm" / "nantou"
    hualien = material_root / "sources" / "dtm" / "hualien"
    extra = tmp_path / "extra-dtm"
    for path in (nantou, hualien, extra):
        path.mkdir(parents=True)
    (material_root / "material_manifest.json").write_text(
        json.dumps(
            {
                "sources": {
                    "dtm_dirs": [
                        nantou.as_posix(),
                        hualien.as_posix(),
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    source_dirs = _dtm_source_dirs(
        PretripImportRequest(
            project_id="chilai_nanhua_day1",
            primary_gpx=tmp_path / "route.gpx",
            workspace_root=tmp_path / "workspaces",
            material_root=material_root,
            dtm_dirs=(hualien, extra),
        )
    )

    assert [path.resolve() for path in source_dirs] == [
        nantou.resolve(),
        hualien.resolve(),
        extra.resolve(),
    ]


def test_pretrip_import_core_writes_pretrip_admin_and_debug_projections(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    references = inbox / "refs"
    references.mkdir(parents=True)
    golden_route = _write_gpx(
        inbox / "golden-route.gpx",
        name="golden route import",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.005, 121.005, 1010.0, "2026-05-01T00:10:00Z"),
            (24.01, 121.01, 1020.0, "2026-05-01T00:20:00Z"),
        ],
        waypoints=[
            (24.002, 121.002, "崩塌小心", "架繩通過", ""),
            (24.006, 121.006, "水源", "需確認", ""),
        ],
    )
    _write_gpx(
        references / "reference-a.gpx",
        name="reference a",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.02, 121.02, 1030.0, "2026-05-01T00:30:00Z"),
        ],
        waypoints=[
            (24.011, 121.011, "路徑不明", "下切後有路", ""),
        ],
    )
    _write_gpx(
        references / "reference-b.gpx",
        name="reference b",
        points=[
            (24.001, 121.001, 1001.0, "2026-05-01T00:00:00Z"),
            (24.015, 121.015, 1015.0, "2026-05-01T00:20:00Z"),
        ],
        waypoints=[],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="fixture_import",
            primary_gpx=golden_route,
            reference_dir=references,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            max_reference_display_points=2,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "fixture_import"
    project = _load(project_root / "project.json")
    admin_projection = _load(project_root / "outputs" / "admin_projection.json")
    package = _load(project_root / "outputs" / "pretrip_package.json")
    reviewed_package = _load(project_root / "outputs" / "pretrip_package.reviewed.json")
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")
    route_bundle = _load(project_root / "normalized" / "routes" / "route_evidence_bundle.json")
    reference_tracks = _load(project_root / "outputs" / "reference_tracks.json")
    reference_display = _load(project_root / "outputs" / "reference_track_display_geometry.json")
    route_notes = _load(project_root / "candidates" / "route_note_candidates.json")
    normalized_route_notes = _load(
        project_root / "normalized" / "notes" / "gpx_route_note_candidates.json"
    )
    gis_ai_judgements = _load(project_root / "outputs" / "gis_perception_ai_judgements.json")
    route_note_ln_proposals = _load(project_root / "outputs" / "route_note_ln_proposals.json")
    route_note_review_options = _load(project_root / "outputs" / "route_note_review_options.json")
    checkpoint_events = _load(project_root / "outputs" / "checkpoint_events.json")
    segment_display = _load(project_root / "outputs" / "segment_display_geometry.json")
    segment_policy = _load(project_root / "outputs" / "segment_policy_candidates.json")
    source_inbox = _load(project_root / "inbox" / "source_manifest.json")
    source_index = _load(project_root / "sources" / "historical_gpx_source_index.json")
    gis_perception = _load(project_root / "outputs" / "gis_perception_candidates.json")
    serialized_outputs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in project_root.rglob("*.json")
    )

    assert manifest["profile"] == "pi-offline"
    assert manifest["import_stage"] == "pretrip"
    assert manifest["network_policy"]["network_calls_allowed"] is False
    assert manifest["inputs"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert manifest["inputs"]["source_inbox"]["manifest_ref"] == "inbox/source_manifest.json"
    assert manifest["inputs"]["source_inbox"]["source_file_count"] == 3
    assert manifest["inputs"]["historical_gpx_source_index"] == {
        "source_ref": "sources/historical_gpx_source_index.json",
        "source_file_count": 3,
        "raw_payloads_embedded": False,
    }
    assert manifest["counts"]["reference_track_count"] == 2
    assert manifest["counts"]["route_note_candidate_count"] == 3
    assert manifest["counts"]["gis_perception_ai_judgement_count"] == 3
    assert manifest["counts"]["route_note_ln_proposal_count"] == 2
    assert manifest["counts"]["route_note_ln_hint_coverage_proposal_count"] == 1
    assert manifest["counts"]["route_note_ln_warning_coverage_proposal_count"] == 1
    assert manifest["counts"]["route_note_review_option_count"] == 2
    assert manifest["counts"]["gis_perception_checkpoint_candidate_count"] == 3
    assert manifest["counts"]["debug_projection_event_count"] == 4
    assert manifest["boundary"]["actual_user_track_available"] is False
    assert manifest["boundary"]["unwalked_route_sections_require_manual_waypoints"] is True
    assert manifest["boundary"]["unwalked_route_sections_require_danger_review"] is True
    assert manifest["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert package["source_artifacts"][0]["metadata"]["role"] == "golden_route_reference"
    assert package["source_artifacts"][0]["metadata"]["actual_user_track_available"] is False
    assert package["boundary"]["candidate_evidence_only"] is True
    assert package["boundary"]["reviewed_package_is_not_departure_approval"] is True
    assert package["boundary"]["departure_approval_granted"] is False
    assert package["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert package["planning_semantics"]["human_review_required_before_departure_gate"] is True
    assert reviewed_package["status"] == "reviewed"
    assert reviewed_package["metadata"]["review_status_source"] == (
        "reviewed_path_admin_continuity_placeholder"
    )
    assert reviewed_package["metadata"]["human_review_count"] == 0
    assert reviewed_package["metadata"]["departure_approval_granted"] is False
    assert project["import_manifest_ref"] == "outputs/import_manifest.json"
    assert project["route_evidence_bundle_ref"] == (
        "normalized/routes/route_evidence_bundle.json"
    )
    assert project["admin_projection_ref"] == "outputs/admin_projection.json"
    assert project["debug_projection_events_ref"] == "outputs/debug_projection_events.jsonl"
    assert project["route_note_candidates_ref"] == "candidates/route_note_candidates.json"
    assert project["normalized_route_note_candidates_ref"] == (
        "normalized/notes/gpx_route_note_candidates.json"
    )
    assert project["gis_perception_ai_judgements_ref"] == "outputs/gis_perception_ai_judgements.json"
    assert project["route_note_ln_proposals_ref"] == "outputs/route_note_ln_proposals.json"
    assert project["route_note_review_options_ref"] == "outputs/route_note_review_options.json"
    assert project["source_inbox_manifest_ref"] == "inbox/source_manifest.json"
    assert project["historical_gpx_source_index_ref"] == (
        "sources/historical_gpx_source_index.json"
    )
    assert project["route_note_ln_hint_coverage_proposal_count"] == 1
    assert project["route_note_ln_warning_coverage_proposal_count"] == 1
    assert project["route_note_review_option_count"] == 2
    assert project["source_inbox_file_count"] == 3
    assert project["gis_perception_candidates_ref"] == "outputs/gis_perception_candidates.json"
    assert project["route_role"] == "golden_route"
    assert project["actual_user_track_available"] is False
    assert project["boss_point_synthesis_status"] == "pending_map_preparation"
    assert project["boss_point_synthesis_trigger"] == "prepare_layers_with_risk"
    assert project["boss_point_synthesis_candidate_only"] is True
    assert project["boss_point_synthesis_runtime_safety_truth"] is False
    assert route_summary["route_name"] == "golden route import"
    assert route_bundle["artifact_kind"] == (
        "pretrip_historical_gpx_route_evidence_bundle"
    )
    assert route_bundle["golden_route"]["role"] == "golden_route_reference"
    assert route_bundle["golden_route"]["filtered_geometry_ref"].startswith(
        "normalized/routes/filtered/"
    )
    assert route_bundle["route_scope_for_map_preparation"]["corridor_policy"] == (
        "bbox_fetch_then_along_track_filter"
    )
    assert route_bundle["route_scope_for_map_preparation"]["route_corridor_m"] == 500.0
    assert (
        route_bundle["route_scope_for_map_preparation"]["reference_track_corridor_m"]
        == 300.0
    )
    assert route_bundle["gpx_filter_refs"] == {
        "rest_area_candidates_ref": "outputs/rest_area_candidates.json",
        "resume_segment_report_ref": "outputs/resume_segments.json",
        "speed_filter_report_ref": "outputs/gpx_speed_filter_report.json",
    }
    assert route_bundle["note_candidate_refs"] == [
        "normalized/notes/gpx_route_note_candidates.json",
        "candidates/route_note_candidates.json",
    ]
    assert route_bundle["boundary"]["actual_user_track_available"] is False
    assert route_bundle["boundary"]["safety_api_called"] is False
    assert manifest["boss_point_synthesis"]["status"] == "pending_map_preparation"
    assert manifest["boss_point_synthesis"]["trigger"] == "prepare_layers_with_risk"
    assert manifest["boss_point_synthesis"]["runtime_safety_truth"] is False
    assert "<trkpt" not in json.dumps(route_bundle, ensure_ascii=False).lower()
    assert reference_tracks["route_role"] == "golden_route"
    assert reference_tracks["golden_route"]["role"] == "golden_route_reference"
    assert reference_tracks["boundary"]["pretrip_actual_user_track_available"] is False
    assert reference_display["reference_track_count"] == 2
    assert all(
        track["display_point_count"] <= 2
        for track in reference_display["reference_tracks"]
    )
    assert admin_projection["surface_targets"] == ["/admin", "/admin/pretrip", "/admin/debug"]
    assert admin_projection["candidate_counts"]["gis_perception_checkpoint_candidate_count"] == 3
    assert admin_projection["candidate_counts"]["gis_perception_ai_judgement_count"] == 3
    assert admin_projection["route_notes"]["status"] == "candidate_only"
    assert admin_projection["route_notes"]["source_path"] == "candidates/route_note_candidates.json"
    assert admin_projection["route_notes"]["counts"]["note_candidate_count"] == 3
    assert admin_projection["route_notes"]["counts"]["route_note_time_unknown_count"] == 3
    assert admin_projection["route_notes"]["counts"]["stale_route_note_count"] == 0
    assert admin_projection["route_notes"]["counts"]["observed_fact_count"] == 0
    assert admin_projection["route_notes"]["boundary"]["candidate_only"] is True
    assert admin_projection["route_notes"]["boundary"]["raw_gpx_embedded"] is False
    assert (
        admin_projection["route_notes"]["boundary"][
            "requires_human_review_before_ln_upgrade"
        ]
        is True
    )
    assert len(admin_projection["route_notes"]["preview_candidates"]) == 3
    assert all(
        candidate["candidate_only"] is True
        and candidate["runtime_safety_truth"] is False
        and candidate["requires_human_review"] is True
        for candidate in admin_projection["route_notes"]["preview_candidates"]
    )
    preview_route_note = admin_projection["route_notes"]["preview_candidates"][0]
    assert preview_route_note["route_note_freshness"] == "unknown"
    assert preview_route_note["stale_route_note"] is False
    assert preview_route_note["review_state"] == "needs_review"
    assert preview_route_note["source_attribution"][0]["source_kind"] == "gpx_route_note"
    assert preview_route_note["pydantic_ai_prompt_version"]
    assert len(preview_route_note["model_output_sha256"]) == 64
    assert admin_projection["route_note_ln_proposals"]["status"] == "candidate_only"
    assert admin_projection["route_note_ln_proposals"]["counts"]["proposal_count"] == 2
    assert (
        admin_projection["route_note_ln_proposals"]["counts"][
            "phase1_runtime_mutation_count"
        ]
        == 0
    )
    assert (
        admin_projection["route_note_ln_proposals"]["boundary"][
            "human_review_required_before_use"
        ]
        is True
    )
    assert (
        admin_projection["route_note_ln_proposals"]["boundary"][
            "package_mutation_allowed"
        ]
        is False
    )
    assert len(admin_projection["route_note_ln_proposals"]["preview_proposals"]) == 2
    assert all(
        proposal["candidate_only"] is True
        and proposal["runtime_safety_truth"] is False
        and proposal["human_review_required"] is True
        for proposal in admin_projection["route_note_ln_proposals"][
            "preview_proposals"
        ]
    )
    preview_ln_proposal = admin_projection["route_note_ln_proposals"][
        "preview_proposals"
    ][0]
    assert preview_ln_proposal["review_state"] == "needs_review"
    assert preview_ln_proposal["source_attribution"][0]["source_kind"] == (
        "route_note_candidate"
    )
    assert preview_ln_proposal["pydantic_ai_prompt_version"]
    assert len(preview_ln_proposal["model_output_sha256"]) == 64
    assert preview_ln_proposal["confidence"] in {"low", "medium", "high"}
    assert preview_ln_proposal["stale_risk"] in {"low", "medium", "high", "unknown"}
    assert (
        admin_projection["route_note_review_options"]["status"]
        == "candidate_only_draft_only"
    )
    assert (
        admin_projection["route_note_review_options"]["counts"]["review_option_count"]
        == 2
    )
    assert (
        admin_projection["route_note_review_options"]["counts"][
            "decision_recorded_count"
        ]
        == 0
    )
    assert (
        admin_projection["route_note_review_options"]["boundary"][
            "decision_recording_allowed"
        ]
        is False
    )
    assert admin_projection["route_note_review_options"]["boundary"]["draft_only"] is True
    assert len(admin_projection["route_note_review_options"]["preview_options"]) == 2
    assert all(
        option["selected_admin_disposition"] is None
        and option["decision_recorded"] is False
        and option["draft_only"] is True
        and option["runtime_safety_truth"] is False
        for option in admin_projection["route_note_review_options"]["preview_options"]
    )
    preview_review_option = admin_projection["route_note_review_options"][
        "preview_options"
    ][0]
    assert preview_review_option["review_state"] == "draft"
    assert preview_review_option["source_attribution"][0]["source_kind"] == (
        "route_note_ln_proposal"
    )
    assert preview_review_option["pydantic_ai_prompt_version"]
    assert len(preview_review_option["model_output_sha256"]) == 64
    assert preview_review_option["confidence"] in {"low", "medium", "high"}
    assert preview_review_option["stale_risk"] in {"low", "medium", "high", "unknown"}
    assert admin_projection["gis_perception"]["source_profile"] == "gpx_corpus_route_notes"
    assert admin_projection["gis_perception"]["boundary"]["candidate_only"] is True
    assert admin_projection["gis_perception"]["ai_judgements"]["judgement_count"] == 3
    assert admin_projection["gis_perception"]["ai_judgements"]["network_calls_allowed"] is False
    assert admin_projection["gis_perception"]["ai_judgements"]["boundary"][
        "candidate_only"
    ] is True
    assert admin_projection["gis_perception"]["ai_judgements"]["boundary"][
        "phase1_runtime_mutation_allowed"
    ] is False
    assert admin_projection["gis_perception"]["ai_judgements"]["boundary"][
        "phase2_writeback_allowed"
    ] is False
    assert admin_projection["gis_perception"]["ai_judgements"]["source_ref_count"] == len(
        admin_projection["gis_perception"]["ai_judgements"]["source_refs"]
    )
    assert admin_projection["gis_perception"]["ai_judgements"]["counts"][
        "candidate_only_count"
    ] == 3
    assert admin_projection["gis_perception"]["ai_judgements"]["counts"][
        "human_review_required_count"
    ] == 3
    assert admin_projection["gis_perception"]["ai_judgements"]["counts"][
        "runtime_safety_truth_count"
    ] == 0
    assert admin_projection["gis_perception"]["ai_judgements"]["counts"][
        "phase1_runtime_mutation_count"
    ] == 0
    assert admin_projection["gis_perception"]["ai_judgements"]["counts"][
        "phase2_writeback_count"
    ] == 0
    assert admin_projection["route"]["route_role"] == "golden_route_reference"
    assert admin_projection["planning_semantics"]["pretrip_actual_user_track_exists"] is False
    assert (
        admin_projection["planning_semantics"]["manual_waypoint_route_policy"][
            "danger_review_required"
        ]
        is True
    )
    assert admin_projection["after_action_surface"]["completed_mission_replay"] is False
    assert admin_projection["debug_surface"]["file_runtime_debug_log_compatible"] is True
    assert admin_projection["boundary"]["projection_only"] is True
    assert route_notes["counts"]["note_candidate_count"] == 3
    assert gis_ai_judgements["provider_kind"] == "pydantic_ai_test"
    assert gis_ai_judgements["judgement_count"] == 3
    assert gis_ai_judgements["boundary"]["candidate_only"] is True
    assert gis_ai_judgements["boundary"]["package_mutation_allowed"] is False
    assert gis_ai_judgements["boundary"]["mission_graph_mutation_allowed"] is False
    assert gis_ai_judgements["boundary"]["runtime_mutation_allowed"] is False
    assert gis_ai_judgements["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert gis_ai_judgements["boundary"]["phase2_writeback_allowed"] is False
    assert gis_ai_judgements["boundary"]["raw_gpx_embedded"] is False
    assert gis_ai_judgements["source_refs"]
    assert gis_ai_judgements["counts"]["input_count"] == 3
    assert gis_ai_judgements["counts"]["judgement_count"] == 3
    assert gis_ai_judgements["counts"]["source_ref_count"] == len(
        gis_ai_judgements["source_refs"]
    )
    assert gis_ai_judgements["counts"]["candidate_only_count"] == 3
    assert gis_ai_judgements["counts"]["human_review_required_count"] == 3
    assert gis_ai_judgements["counts"]["runtime_safety_truth_count"] == 0
    assert gis_ai_judgements["counts"]["package_mutation_count"] == 0
    assert gis_ai_judgements["counts"]["mission_graph_mutation_count"] == 0
    assert gis_ai_judgements["counts"]["runtime_mutation_count"] == 0
    assert gis_ai_judgements["counts"]["phase1_runtime_mutation_count"] == 0
    assert gis_ai_judgements["counts"]["phase2_writeback_count"] == 0
    assert gis_ai_judgements["counts"]["raw_model_output_count"] == 0
    assert all(
        judgement["runtime_safety_truth"] is False
        for judgement in gis_ai_judgements["judgements"]
    )
    assert all(
        judgement["source_refs"]
        and judgement["prompt_sha256"]
        and judgement["pydantic_ai_prompt_version"]
        == "scout.gis_perception.structured_judgement.v0"
        and len(judgement["model_output_sha256"]) == 64
        and judgement["model_output_summary"]
        and judgement["review_state"] == "needs_review"
        for judgement in gis_ai_judgements["judgements"]
    )
    assert route_note_ln_proposals["counts"]["proposal_count"] == 2
    assert route_note_review_options["counts"]["source_proposal_count"] == 2
    assert route_note_review_options["counts"]["review_option_count"] == 2
    assert route_note_review_options["boundary"]["candidate_only"] is True
    assert route_note_review_options["boundary"]["draft_only"] is True
    assert source_inbox["artifact_kind"] == "pretrip_source_inbox_manifest"
    assert source_inbox["source_file_count"] == 3
    assert source_inbox["raw_payloads_embedded"] is False
    assert all(
        (project_root / source["workspace_ref"]).exists()
        for source in source_inbox["sources"]
    )
    assert all(
        source["raw_payload_embedded_in_json"] is False
        for source in source_inbox["sources"]
    )
    assert source_index["artifact_kind"] == "pretrip_historical_gpx_source_index"
    assert source_index["schema_version"] == "historical_gpx_importer.v1"
    assert source_index["source_file_count"] == 3
    assert source_index["raw_payloads_embedded"] is False
    assert source_index["sources"][0]["route_role"] == "golden_route"
    assert all(
        source["raw_payload_embedded_in_json"] is False
        for source in source_index["sources"]
    )
    assert normalized_route_notes == route_notes
    assert all(
        candidate["source_attribution"]
        and candidate["source_attribution"][0]["source_kind"] == "gpx_route"
        for candidate in package["checkpoint_candidates"]
    )
    _assert_import_candidates_have_pretrip_provenance(
        package["checkpoint_candidates"],
        expected_source_kind="gpx_route",
    )
    _assert_import_candidates_have_pretrip_provenance(
        package["segment_candidates"],
        expected_source_kind="gpx_route_segment",
    )
    _assert_import_projection_items_have_pretrip_provenance(
        checkpoint_events["events"],
        expected_source_kind="pretrip_checkpoint_candidate",
    )
    _assert_import_projection_items_have_pretrip_provenance(
        segment_display["segments"],
        expected_source_kind="pretrip_segment_candidate",
    )
    assert gis_perception["counts"]["checkpoint_candidate_count"] == 3
    assert gis_perception["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert all(
        candidate["source_attribution"]
        and candidate["source_attribution"][0]["source_kind"] == "gpx_route_note"
        for candidate in gis_perception["checkpoint_candidates"]
    )
    _assert_gis_perception_candidates_have_pretrip_provenance(
        gis_perception["checkpoint_candidates"]
    )
    _assert_segment_policy_candidates_have_pretrip_provenance(
        segment_policy["candidates"]
    )
    assert "<gpx" not in serialized_outputs
    assert "<trkpt" not in serialized_outputs

    debug_log = FileRuntimeDebugEventLog(project_root / "outputs" / "debug_projection_events.jsonl")
    debug_events = debug_log.list_events()
    assert [event.kind for event in debug_events] == [
        "debug_session_started",
        "provider_status_recorded",
        "progress_update_recorded",
        "debug_session_completed",
    ]
    debug_client = TestClient(create_debug_app(debug_log=debug_log))
    debug_state = debug_client.get("/debug/state").json()
    assert debug_state["event_count"] == 4
    assert debug_state["debug_boundary"]["read_only"] is True
    assert debug_state["debug_boundary"]["phase1_mutation_allowed"] is False

    admin_client = TestClient(create_admin_app(pretrip_workspace_root=tmp_path / "workspaces"))
    listed_projects = admin_client.get("/admin/pretrip/projects").json()["projects"]
    assert any(project["project_id"] == "fixture_import" for project in listed_projects)
    admin_projection_response = admin_client.get(
        "/admin/pretrip/projects/fixture_import/admin-projection"
    )
    assert admin_projection_response.status_code == 200
    assert admin_projection_response.json()["surface_targets"] == [
        "/admin",
        "/admin/pretrip",
        "/admin/debug",
    ]
    debug_projection_response = admin_client.get(
        "/admin/pretrip/projects/fixture_import/debug-projection-events"
    )
    assert debug_projection_response.status_code == 200
    assert debug_projection_response.json()["event_count"] == 4
    assert (
        debug_projection_response.json()["boundary"]["phase1_runtime_mutation_allowed"]
        is False
    )


def test_pretrip_import_uses_material_root_for_terrain_weather_and_retreat(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    golden_route = _write_gpx(
        inbox / "golden-route.gpx",
        name="material root golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.001, 121.001, 1010.0, "2026-05-01T00:10:00Z"),
            (24.002, 121.002, 1020.0, "2026-05-01T00:20:00Z"),
        ],
    )
    material_root = tmp_path / "materials" / "pretrip" / "material_import"
    dtm_dir = material_root / "sources" / "dtm" / "分幅_南投縣20MDEM(2025)"
    dtm_dir.mkdir(parents=True)
    x, y = wgs84_to_twd97(24.001, 121.001)
    _write_dtm_header(
        dtm_dir / "material_dem.hdr",
        tile_id="material",
        origin_x=int(x) - 1200,
        origin_y=int(y) - 1200,
    )
    (dtm_dir / "material_dem.grd").write_bytes(b"fixture")
    (material_root / "material_manifest.json").write_text(
        json.dumps(
            {
                "artifact_kind": "scout_pretrip_material_root_manifest",
                "layout_version": "0.1.0",
                "project_id": "material_import",
                "sources": {
                    "primary_gpx": str(golden_route),
                    "gpx_corpus": str(inbox),
                    "dtm_dirs": [str(dtm_dir)],
                },
                "boundary": {
                    "pretrip_candidate_evidence_only": True,
                    "runtime_safety_truth": False,
                    "phase1_runtime_mutation_allowed": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run_pretrip_import(
        PretripImportRequest(
            project_id="material_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            material_root=material_root,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "material_import"
    project = _load(project_root / "project.json")
    dtm_summary = _load(project_root / "normalized" / "terrain" / "dtm_coverage_summary.json")
    segment_dtm = _load(project_root / "normalized" / "terrain" / "segment_dtm_coverage.json")
    weather = _load(project_root / "outputs" / "weather_daylight_evidence.json")
    retreat_routes = _load(project_root / "candidates" / "retreat_routes.json")

    assert project["dtm_coverage_summary_ref"] == "normalized/terrain/dtm_coverage_summary.json"
    assert project["segment_dtm_coverage_ref"] == "normalized/terrain/segment_dtm_coverage.json"
    assert project["weather_daylight_evidence_ref"] == "outputs/weather_daylight_evidence.json"
    assert project["weather_daylight_evidence_count"] == 1
    assert project["retreat_routes_ref"] == "candidates/retreat_routes.json"
    assert project["retreat_route_candidate_count"] == 1
    assert dtm_summary["source_dirs"] == [str(dtm_dir.resolve())]
    assert dtm_summary["scanned_header_count"] == 1
    assert dtm_summary["candidate_tiles"][0]["tile_id"] == "material"
    assert segment_dtm["segment_count"] == project["segment_candidate_count"]
    assert weather["status"] == "candidate_only"
    assert weather["external_api_calls_made"] is False
    assert weather["authoritative_weather_computed"] is False
    assert retreat_routes[0]["candidate_id"] == "retreat.material_import.return_to_entry"
    assert retreat_routes[0]["runtime_safety_truth"] is False


def test_pretrip_import_generates_mcp_artifacts_from_named_point_evidence(
    tmp_path: Path,
) -> None:
    evidence_path = ROOT / "tests" / "fixtures" / "pretrip" / "mcp" / "named_point_evidence.json"
    evidence = _load(evidence_path)
    route_points = [
        (
            named_point["route_position"]["lat"],
            named_point["route_position"]["lon"],
            1000.0 + index,
            f"2026-05-01T{index:02d}:00:00Z",
        )
        for index, named_point in enumerate(
            sorted(
                evidence["named_points"],
                key=lambda item: item["route_position"]["distance_m"],
            )
        )
    ]
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="能高安東軍縱走",
        points=route_points,
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="chilai_nanhua_day1",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
            mcp_named_point_evidence=evidence_path,
        )
    )

    project_root = tmp_path / "workspaces" / "chilai_nanhua_day1"
    project = _load(project_root / "project.json")
    admin_projection = _load(project_root / "outputs" / "admin_projection.json")
    mcp_candidates = _load(project_root / "outputs" / "mcp" / "mcp_candidates.json")
    retrieval_plan = _load(project_root / "outputs" / "mcp" / "mcp_retrieval_plan.json")
    ocr_labels = _load(project_root / "outputs" / "mcp" / "mcp_ocr_labels.json")
    cp_support = _load(
        project_root / "outputs" / "mcp" / "mcp_cp_support_reconciliation.json"
    )

    assert manifest["inputs"]["mcp_named_point_evidence"]["raw_payload_embedded"] is False
    assert manifest["mcp_synthesis"]["boundary"]["live_network_performed"] is False
    assert manifest["mcp_synthesis"]["boundary"]["runtime_safety_truth"] is False
    assert manifest["counts"]["mcp_candidate_count"] == 6
    assert manifest["counts"]["mcp_retrieval_query_count"] == 11
    assert manifest["counts"]["mcp_ocr_label_count"] == 1
    assert manifest["counts"]["mcp_cp_support_supported_count"] == 5
    assert project["mcp_candidates_ref"] == "outputs/mcp/mcp_candidates.json"
    assert project["mcp_candidate_count"] == 6
    assert project["mcp_cp_support_supported_count"] == 5
    assert admin_projection["candidate_counts"]["mcp_candidate_count"] == 6
    assert admin_projection["major_critical_points"]["status"] == "candidate_only"
    assert (
        admin_projection["major_critical_points"]["retrieval"][
            "live_network_performed"
        ]
        is False
    )
    assert (
        admin_projection["major_critical_points"]["boundary"]["runtime_safety_truth"]
        is False
    )
    assert mcp_candidates["mcp_candidate_count"] == 6
    assert mcp_candidates["runtime_safety_truth"] is False
    assert mcp_candidates["compile_allowed"] is False
    assert retrieval_plan["query_count"] == 11
    assert retrieval_plan["live_network_performed"] is False
    assert retrieval_plan["truth_decision_allowed"] is False
    assert ocr_labels["label_count"] == 1
    assert cp_support["supported_count"] == 5
    assert cp_support["suggested_insertion_count"] == 1


def test_pretrip_import_filters_gpx_points_requiring_unreasonable_speed(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="speed filtered golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (25.0, 122.0, 1000.0, "2026-05-01T00:01:00Z"),
            (24.004, 121.004, 1005.0, "2026-05-01T00:20:00Z"),
        ],
    )
    reference_route = _write_gpx(
        tmp_path / "reference-route.gpx",
        name="speed filtered reference route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (25.1, 122.1, 1000.0, "2026-05-01T00:01:00Z"),
            (24.004, 121.004, 1010.0, "2026-05-01T00:30:00Z"),
        ],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="speed_filter_import",
            primary_gpx=golden_route,
            reference_gpx_paths=(reference_route,),
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "speed_filter_import"
    project = _load(project_root / "project.json")
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")
    filter_report = _load(project_root / "outputs" / "gpx_speed_filter_report.json")
    admin_projection = _load(project_root / "outputs" / "admin_projection.json")
    debug_events = [
        json.loads(line)
        for line in (project_root / "outputs" / "debug_projection_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    package = _load(project_root / "outputs" / "pretrip_package.json")
    primary_filtered_gpx = Path(filter_report["primary"]["output_path"]).read_text(
        encoding="utf-8"
    )

    assert manifest["counts"]["route_point_count"] == 2
    assert manifest["counts"]["gpx_speed_filter_original_point_count"] == 6
    assert manifest["counts"]["gpx_speed_filter_filtered_point_count"] == 4
    assert manifest["counts"]["gpx_speed_filter_removed_point_count"] == 2
    assert manifest["gpx_speed_filter"]["max_reasonable_speed_kmh"] == 120.0
    assert manifest["boundary"]["gpx_speed_filter_applied"] is True
    assert filter_report["removed_track_point_count"] == 2
    assert filter_report["primary"]["removed_track_point_count"] == 1
    assert filter_report["references"][0]["removed_track_point_count"] == 1
    assert filter_report["primary"]["removed_points"][0]["source_index"] == 1
    assert filter_report["boundary"]["pretrip_candidate_evidence_only"] is True
    assert filter_report["boundary"]["runtime_safety_truth"] is False
    assert route_summary["point_count"] == 2
    assert route_summary["bbox_wgs84"]["max_lat"] < 24.02
    assert route_summary["bbox_wgs84"]["max_lon"] < 121.02
    assert "25.0" not in primary_filtered_gpx
    assert "122.0" not in primary_filtered_gpx
    assert package["source_artifacts"][0]["metadata"]["gpx_speed_filter"][
        "removed_track_point_count"
    ] == 1
    assert package["source_artifacts"][0]["metadata"]["gpx_speed_filter"][
        "report_ref"
    ] == "outputs/gpx_speed_filter_report.json"
    assert package["source_artifacts"][0]["metadata"]["gpx_speed_filter"][
        "detail_lists_embedded"
    ] is False
    assert "removed_points" not in package["source_artifacts"][0]["metadata"][
        "gpx_speed_filter"
    ]
    assert "exempted_points" not in package["source_artifacts"][0]["metadata"][
        "gpx_speed_filter"
    ]
    assert admin_projection["route"]["gpx_speed_filter"]["removed_track_point_count"] == 2
    assert project["gpx_speed_filter_removed_track_point_count"] == 2
    assert project["gpx_speed_filter_report_ref"] == "outputs/gpx_speed_filter_report.json"
    assert "removed 2 point(s)" in debug_events[1]["summary"]
    assert debug_events[1]["payload"]["gpx_speed_filter"][
        "removed_track_point_count"
    ] == 2


def test_pretrip_import_filters_gpx_points_requiring_three_times_previous_speed(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="relative speed filtered golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.001, 121.0, 1001.0, "2026-05-01T00:10:00Z"),
            (24.006, 121.0, 1002.0, "2026-05-01T00:20:00Z"),
            (24.002, 121.0, 1003.0, "2026-05-01T00:30:00Z"),
        ],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="relative_speed_filter_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
            max_previous_gpx_speed_ratio=3.0,
        )
    )

    project_root = tmp_path / "workspaces" / "relative_speed_filter_import"
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")
    filter_report = _load(project_root / "outputs" / "gpx_speed_filter_report.json")
    primary_removed = filter_report["primary"]["removed_points"][0]
    primary_filtered_gpx = Path(filter_report["primary"]["output_path"]).read_text(
        encoding="utf-8"
    )

    assert manifest["counts"]["route_point_count"] == 3
    assert manifest["counts"]["gpx_speed_filter_removed_point_count"] == 1
    assert manifest["gpx_speed_filter"]["max_previous_speed_ratio"] == 3.0
    assert filter_report["primary"]["removed_track_point_count"] == 1
    assert primary_removed["source_index"] == 2
    assert primary_removed["reason"] == "required_speed_exceeds_previous_speed_ratio"
    assert primary_removed["required_speed_kmh"] < 120.0
    assert primary_removed["speed_ratio_to_previous_kept"] > 3.0
    assert route_summary["point_count"] == 3
    assert route_summary["bbox_wgs84"]["max_lat"] < 24.003
    assert 'lat="24.006"' not in primary_filtered_gpx


def test_pretrip_import_default_relative_speed_filter_keeps_five_times_spike(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="less aggressive relative speed filtered golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.001, 121.0, 1001.0, "2026-05-01T00:10:00Z"),
            (24.006, 121.0, 1002.0, "2026-05-01T00:20:00Z"),
            (24.002, 121.0, 1003.0, "2026-05-01T00:30:00Z"),
        ],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="default_relative_speed_filter_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "default_relative_speed_filter_import"
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")
    filter_report = _load(project_root / "outputs" / "gpx_speed_filter_report.json")
    primary_filtered_gpx = Path(filter_report["primary"]["output_path"]).read_text(
        encoding="utf-8"
    )

    assert manifest["counts"]["route_point_count"] == 4
    assert manifest["counts"]["gpx_speed_filter_removed_point_count"] == 0
    assert manifest["gpx_speed_filter"]["max_previous_speed_ratio"] == 8.0
    assert filter_report["primary"]["removed_track_point_count"] == 0
    assert route_summary["point_count"] == 4
    assert route_summary["bbox_wgs84"]["max_lat"] == 24.006
    assert 'lat="24.006"' in primary_filtered_gpx


def test_pretrip_import_preserves_gpx_segment_boundaries_in_display_geometry(
    tmp_path: Path,
) -> None:
    references = tmp_path / "references"
    references.mkdir()
    golden_route = _write_segmented_gpx(
        tmp_path / "golden-route.gpx",
        name="segmented golden route",
        segments=[
            [
                (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
                (24.001, 121.001, 1001.0, "2026-05-01T00:10:00Z"),
            ],
            [
                (24.5, 121.5, 1100.0, "2026-05-02T00:00:00Z"),
                (24.501, 121.501, 1101.0, "2026-05-02T00:10:00Z"),
            ],
        ],
    )
    _write_segmented_gpx(
        references / "reference.gpx",
        name="segmented reference route",
        segments=[
            [
                (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
                (24.002, 121.002, 1002.0, "2026-05-01T00:10:00Z"),
            ],
            [
                (24.6, 121.6, 1200.0, "2026-05-02T00:00:00Z"),
                (24.602, 121.602, 1202.0, "2026-05-02T00:10:00Z"),
            ],
        ],
    )

    run_pretrip_import(
        PretripImportRequest(
            project_id="segmented_display_import",
            primary_gpx=golden_route,
            reference_dir=references,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=100_000.0,
            max_reference_display_points=100,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "segmented_display_import"
    segment_display = _load(project_root / "outputs" / "segment_display_geometry.json")
    reference_display = _load(
        project_root / "outputs" / "reference_track_display_geometry.json"
    )
    view = build_pretrip_admin_view("segmented_display_import", project_root=project_root)

    segment_geometry = segment_display["segments"][0]
    reference_geometry = reference_display["reference_tracks"][0]
    view_segment_geometry = view["segments"][0]["display_geometry"]
    view_reference_geometry = view["reference_tracks"]["reference_tracks"][0][
        "display_geometry"
    ]
    route_display_geometry = view["admin_surface_projection"]["route"][
        "display_geometry"
    ]

    assert segment_geometry["display_segment_count"] == 2
    assert len(segment_geometry["coordinate_segments"]) == 2
    assert all(len(segment) == 2 for segment in segment_geometry["coordinate_segments"])
    assert segment_geometry["segment_boundary_preserved"] is True
    assert reference_geometry["display_segment_count"] == 2
    assert len(reference_geometry["coordinate_segments"]) == 2
    assert reference_geometry["segment_boundary_preserved"] is True
    assert view_segment_geometry["display_segment_count"] == 2
    assert len(view_segment_geometry["coordinate_segments"]) == 2
    assert len(view_reference_geometry["coordinate_segments"]) == 2
    assert route_display_geometry["display_segment_count"] == 2
    assert len(route_display_geometry["coordinate_segments"]) == 2


def test_pretrip_import_marks_long_distance_gaps_as_resume_segments(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="gap filtered golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.001, 121.0, 1001.0, "2026-05-01T00:10:00Z"),
            (24.15, 121.0, 1002.0, "2026-05-05T00:00:00Z"),
            (24.151, 121.0, 1003.0, "2026-05-05T00:10:00Z"),
        ],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="gap_filter_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "gap_filter_import"
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")
    filter_report = _load(project_root / "outputs" / "gpx_speed_filter_report.json")
    resume_segments = _load(project_root / "outputs" / "resume_segments.json")
    segments = _load(project_root / "candidates" / "segments.json")
    segment_display_geometry = _load(
        project_root / "outputs" / "segment_display_geometry.json"
    )

    assert manifest["counts"]["route_point_count"] == 4
    assert manifest["counts"]["gpx_speed_filter_removed_point_count"] == 0
    assert manifest["counts"]["resume_segment_count"] == 1
    assert route_summary["point_count"] == 4
    assert route_summary["bbox_wgs84"]["max_lat"] == 24.151
    assert filter_report["primary"]["removed_points"] == []
    assert resume_segments["max_reasonable_point_gap_m"] == 1000.0
    assert resume_segments["resume_segment_count"] == 1
    assert resume_segments["segments"][0]["segment_candidate_id"] == "seg.001"
    assert resume_segments["segments"][0]["resume_segment"] is True
    assert resume_segments["segments"][0]["gaps"][0]["distance_m"] > 1000.0
    assert "Resume segment:" in segments[0]["notes"]
    assert segments[0]["review_state"] == "needs_review"
    assert segment_display_geometry["resume_segment_count"] == 1
    assert segment_display_geometry["segments"][0]["resume_segment"] is True


def test_pretrip_import_keeps_speed_outlier_when_route_note_protected(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="route note protected speed outlier",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (25.0, 122.0, 1001.0, "2026-05-01T00:01:00Z"),
            (25.001, 122.001, 1002.0, "2026-05-01T00:10:00Z"),
        ],
        waypoints=[
            (25.0, 122.0, "路徑註記保留", "人工標註點", ""),
        ],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="route_note_protected_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "route_note_protected_import"
    filter_report = _load(project_root / "outputs" / "gpx_speed_filter_report.json")
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")

    assert manifest["counts"]["route_point_count"] == 3
    assert manifest["counts"]["gpx_speed_filter_removed_point_count"] == 0
    assert manifest["counts"]["gpx_speed_filter_exempted_point_count"] == 1
    assert route_summary["point_count"] == 3
    assert filter_report["primary"]["removed_points"] == []
    assert filter_report["primary"]["exempted_track_point_count"] == 1
    exempted = filter_report["primary"]["exempted_points"][0]
    assert exempted["source_index"] == 1
    assert exempted["would_remove_reason"] == "required_speed_exceeds_absolute_threshold"
    assert exempted["exemption_reason"] == "route_note_protected"
    assert "路徑註記保留" in exempted["route_note"]["note"]


def test_pretrip_import_adds_rest_area_checkpoint_from_low_speed_dense_cluster(
    tmp_path: Path,
) -> None:
    cluster_points = [
        (
            24.001 + (0.00001 if index % 2 else 0.0),
            121.001 + (0.00001 if index % 3 else 0.0),
            1000.0,
            f"2026-05-01T00:{5 + index * 2:02d}:00Z",
        )
        for index in range(16)
    ]
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="rest area cluster golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            *cluster_points,
            (24.006, 121.006, 1020.0, "2026-05-01T00:45:00Z"),
        ],
    )

    manifest = run_pretrip_import(
        PretripImportRequest(
            project_id="rest_area_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            checkpoint_spacing_m=2_000.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "rest_area_import"
    project = _load(project_root / "project.json")
    rest_area_report = _load(project_root / "outputs" / "rest_area_candidates.json")
    checkpoints = _load(project_root / "candidates" / "checkpoints.json")
    segments = _load(project_root / "candidates" / "segments.json")
    checkpoint_events = _load(project_root / "outputs" / "checkpoint_events.json")

    assert manifest["counts"]["rest_area_candidate_count"] == 1
    assert manifest["counts"]["rest_area_checkpoint_count"] == 1
    assert manifest["counts"]["checkpoint_candidate_count"] == 3
    assert manifest["counts"]["segment_candidate_count"] == 2
    assert project["rest_area_candidates_ref"] == "outputs/rest_area_candidates.json"
    assert project["rest_area_candidate_count"] == 1
    assert project["rest_area_checkpoint_count"] == 1
    assert rest_area_report["rest_area_candidate_count"] == 1
    assert rest_area_report["rest_area_checkpoint_count"] == 1
    rest_area = rest_area_report["candidates"][0]
    assert rest_area["checkpoint_inserted"] is True
    assert rest_area["label"] == "Rest area / camp area 001"
    assert rest_area["source_point_count"] == 16
    assert rest_area["duration_seconds"] >= 30 * 60
    assert rest_area["mean_speed_m_per_min"] < 5.0
    rest_checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint["checkpoint_type"] == "rest_area"
    ]
    assert len(rest_checkpoints) == 1
    assert rest_checkpoints[0]["candidate_id"] == rest_area["checkpoint_candidate_id"]
    assert rest_checkpoints[0]["source_attribution"][0]["source_kind"] == "rest_area_cluster"
    assert rest_checkpoints[0]["source_attribution"][0]["source_candidate_id"] == rest_area["candidate_id"]
    assert len(segments) == 2
    assert segments[0]["from_candidate_id"] == "cp.start"
    assert segments[0]["to_candidate_id"] == rest_area["checkpoint_candidate_id"]
    assert segments[1]["from_candidate_id"] == rest_area["checkpoint_candidate_id"]
    assert segments[1]["to_candidate_id"] == "cp.finish"
    assert any(
        event["checkpoint_candidate_id"] == "cp.rest_area.001"
        for event in checkpoint_events["events"]
    )


def test_pretrip_import_cli_copies_template_workspace_without_mutating_template(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    refs = inbox / "refs"
    refs.mkdir(parents=True)
    golden_route = _write_gpx(
        inbox / "golden-route.gpx",
        name="cli golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.004, 121.004, 1010.0, "2026-05-01T00:10:00Z"),
        ],
    )
    _write_gpx(
        refs / "reference.gpx",
        name="cli reference",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.004, 121.004, 1020.0, "2026-05-01T00:20:00Z"),
        ],
    )
    template = tmp_path / "template"
    (template / "reviews").mkdir(parents=True)
    (template / "project.json").write_text(
        json.dumps({"project_id": "template", "template_marker": True}, sort_keys=True),
        encoding="utf-8",
    )
    (template / "reviews" / "keep.json").write_text('{"kept": true}\n', encoding="utf-8")
    original_template_project = (template / "project.json").read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_import",
            "--project-id",
            "cli_import",
            "--golden-route-gpx",
            str(golden_route),
            "--reference-dir",
            str(refs),
            "--workspace-root",
            str(tmp_path / "workspaces"),
            "--template-project-root",
            str(template),
            "--profile",
            "pi-offline",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads(result.stdout)
    project_root = tmp_path / "workspaces" / "cli_import"
    project = _load(project_root / "project.json")

    assert manifest["artifact_kind"] == "pretrip_import_manifest"
    assert manifest["network_policy"]["network_calls_allowed"] is False
    assert manifest["inputs"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert project["project_id"] == "cli_import"
    assert project["template_marker"] is True
    assert project["reference_track_count"] == 1
    assert (project_root / "reviews" / "keep.json").exists()
    assert (template / "project.json").read_text(encoding="utf-8") == original_template_project
    assert (project_root / "outputs" / "admin_projection.json").exists()
    assert (project_root / "outputs" / "debug_projection_events.jsonl").exists()


def test_restore_durable_admin_evidence_refs_copies_safe_missing_refs(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_project"
    destination_root = tmp_path / "destination_project"
    (source_root / "outputs").mkdir(parents=True)
    (destination_root / "outputs").mkdir(parents=True)
    durable_refs = {
        "readiness_report_ref": "outputs/readiness_report.json",
        "resource_plan_ref": "outputs/resource_plan.json",
        "planned_eta_ref": "outputs/planned_eta.json",
        "departure_bundle_manifest_ref": "outputs/departure_bundle_manifest.json",
        "route_comparison_ref": "outputs/route_comparison.json",
        "capability_timeline_import_ref": "outputs/capability_timeline_import.json",
        "terrain_visualization_ref": (
            "outputs/layers/normalized/terrain_visualization.geojson"
        ),
        "terrain_hillshade_overlay_ref": (
            "outputs/layers/normalized/terrain_hillshade.png"
        ),
        "terrain_elevation_tint_overlay_ref": (
            "outputs/layers/normalized/terrain_elevation_tint.png"
        ),
        "post_analysis_capability_timeline_ref": "../outside.json",
    }
    for key, ref in durable_refs.items():
        if ref.startswith("../"):
            continue
        (source_root / ref).parent.mkdir(parents=True, exist_ok=True)
        (source_root / ref).write_text(
            json.dumps({"source_key": key}, sort_keys=True),
            encoding="utf-8",
        )
    (source_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "source",
                **durable_refs,
                "dtm_candidate_tile_count": 48,
                "dtm_scanned_header_count": 1411,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (destination_root / "outputs" / "route_comparison.json").write_text(
        json.dumps({"kept": "destination"}, sort_keys=True),
        encoding="utf-8",
    )
    (destination_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "destination",
                "route_comparison_ref": "outputs/route_comparison.json",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    summary = restore_durable_admin_evidence_refs(
        project_root=destination_root,
        source_root=source_root,
    )

    project = _load(destination_root / "project.json")
    assert project["readiness_report_ref"] == "outputs/readiness_report.json"
    assert project["resource_plan_ref"] == "outputs/resource_plan.json"
    assert project["planned_eta_ref"] == "outputs/planned_eta.json"
    assert project["departure_bundle_manifest_ref"] == (
        "outputs/departure_bundle_manifest.json"
    )
    assert project["capability_timeline_import_ref"] == (
        "outputs/capability_timeline_import.json"
    )
    assert project["terrain_visualization_ref"] == (
        "outputs/layers/normalized/terrain_visualization.geojson"
    )
    assert project["terrain_hillshade_overlay_ref"] == (
        "outputs/layers/normalized/terrain_hillshade.png"
    )
    assert project["terrain_elevation_tint_overlay_ref"] == (
        "outputs/layers/normalized/terrain_elevation_tint.png"
    )
    assert project["dtm_candidate_tile_count"] == 48
    assert project["dtm_scanned_header_count"] == 1411
    assert "post_analysis_capability_timeline_ref" not in project
    assert _load(destination_root / "outputs" / "readiness_report.json") == {
        "source_key": "readiness_report_ref"
    }
    assert _load(destination_root / "outputs" / "route_comparison.json") == {
        "kept": "destination"
    }
    assert (
        destination_root / "outputs" / "layers" / "normalized" / "terrain_hillshade.png"
    ).exists()
    assert summary["copied"]["readiness_report_ref"] == "outputs/readiness_report.json"
    assert summary["copied"]["terrain_hillshade_overlay_ref"] == (
        "outputs/layers/normalized/terrain_hillshade.png"
    )
    assert summary["restored"]["dtm_candidate_tile_count"] == 48
    assert summary["skipped"]["route_comparison_ref"] == "payload_ref_already_exists"
    assert summary["invalid"]["post_analysis_capability_timeline_ref"] == (
        "../outside.json"
    )


def test_pretrip_import_template_workspace_feeds_admin_view_projection(tmp_path: Path) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="admin view golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.004, 121.004, 1010.0, "2026-05-01T00:10:00Z"),
            (24.008, 121.008, 1020.0, "2026-05-01T00:20:00Z"),
        ],
    )
    template = (
        ROOT
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
    )

    run_pretrip_import(
        PretripImportRequest(
            project_id="imported_admin_view",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            template_project_root=template,
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "imported_admin_view"
    view = build_pretrip_admin_view("imported_admin_view", project_root=project_root)
    post_sections = {
        section["id"] for section in view["tabs"]["post_analysis"]["sections"]
    }

    assert view["admin_surface_projection"]["surface_targets"] == [
        "/admin",
        "/admin/pretrip",
        "/admin/debug",
    ]
    assert view["admin_surface_projection"]["route"]["route_role"] == (
        "golden_route_reference"
    )
    assert view["admin_surface_projection"]["route_notes"]["status"] == "candidate_only"
    assert (
        view["admin_surface_projection"]["route_note_ln_proposals"]["counts"][
            "proposal_count"
        ]
        == 0
    )
    assert (
        view["admin_surface_projection"]["route_note_review_options"]["counts"][
            "decision_recorded_count"
        ]
        == 0
    )
    assert (
        view["admin_surface_projection"]["route_note_review_options"]["boundary"][
            "draft_only"
        ]
        is True
    )
    assert view["admin_surface_projection"]["candidate_counts"]["mcp_candidate_count"] == 6
    assert (
        view["admin_surface_projection"]["major_critical_points"]["status"]
        == "candidate_only"
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["counts"][
            "mcp_candidate_count"
        ]
        == 6
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["counts"][
            "retrieval_query_count"
        ]
        == 11
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["counts"][
            "ocr_label_count"
        ]
        == 1
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["counts"][
            "cp_support_supported_count"
        ]
        == 5
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["retrieval"][
            "live_network_performed"
        ]
        is False
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["retrieval"][
            "truth_decision_allowed"
        ]
        is False
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["boundary"][
            "runtime_safety_truth"
        ]
        is False
    )
    assert (
        view["admin_surface_projection"]["major_critical_points"]["boundary"][
            "compile_allowed"
        ]
        is False
    )
    assert (
        len(
            view["admin_surface_projection"]["major_critical_points"][
                "preview_candidates"
            ]
        )
        == 6
    )
    assert view["admin_surface_projection"]["departure_bundle"]["status"] == (
        "frozen_candidate"
    )
    assert (
        view["admin_surface_projection"]["departure_bundle"]["boundary"][
            "not_departure_approval"
        ]
        is True
    )
    assert (
        view["admin_surface_projection"]["departure_bundle"]["boundary"][
            "human_review_required_before_departure"
        ]
        is True
    )
    assert (
        view["admin_surface_projection"]["departure_bundle"]["boundary"][
            "phase1_runtime_mutation_allowed"
        ]
        is False
    )
    assert (
        view["admin_surface_projection"]["departure_bundle"]["counts"][
            "required_ref_count"
        ]
        >= 1
    )
    assert (
        view["admin_surface_projection"]["runtime_handoff"]["status"]
        == "candidate_metadata_only"
    )
    assert (
        view["admin_surface_projection"]["runtime_handoff"]["boundary"][
            "candidate_metadata_only"
        ]
        is True
    )
    assert (
        view["admin_surface_projection"]["runtime_handoff"]["boundary"][
            "departure_approval_granted"
        ]
        is False
    )
    assert (
        view["admin_surface_projection"]["runtime_handoff"]["boundary"][
            "runtime_handoff_operator_trigger_required"
        ]
        is True
    )
    assert (
        view["admin_surface_projection"]["runtime_handoff"]["counts"][
            "runtime_write_count"
        ]
        == 0
    )
    assert (
        view["admin_surface_projection"]["runtime_handoff"]["counts"][
            "safety_call_count"
        ]
        == 0
    )
    assert view["reference_tracks"]["golden_route"]["pretrip_actual_user_track"] is False
    assert view["gis_perception"]["status"] == "candidate_only"
    assert view["gis_perception"]["counts"]["checkpoint_candidate_count"] == 0
    assert view["debug_projection"]["event_count"] == 4
    assert view["import_manifest"]["network_policy"]["network_calls_allowed"] is False
    assert {"import_manifest", "admin_surface_projection", "debug_projection"} <= post_sections


def test_admin_view_projects_aggregated_gis_perception_cp_into_review_queue(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="aggregated gis cp golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.004, 121.004, 1010.0, "2026-05-01T00:10:00Z"),
            (24.008, 121.008, 1020.0, "2026-05-01T00:20:00Z"),
        ],
        waypoints=[
            (24.00100, 121.00100, "大崩壁", "需要警戒", ""),
        ],
    )
    reference = _write_gpx(
        tmp_path / "reference-duplicate.gpx",
        name="reference duplicate hazard",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.004, 121.004, 1010.0, "2026-05-01T00:10:00Z"),
        ],
            waypoints=[
                (24.00125, 121.00125, "大崩壁崩塌地", "同一危險地形", ""),
                (24.00135, 121.00135, "高繞", "同一崩塌區附近的繞路提示", ""),
                (
                    24.00140,
                    121.00140,
                    "茂密林相",
                    "路跡不明需複查",
                    "",
                    "2018-01-01T00:00:00Z",
                ),
                (24.00600, 121.00600, "最後水源", "需人工確認", ""),
            ],
    )
    template = (
        ROOT
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
    )

    run_pretrip_import(
        PretripImportRequest(
            project_id="aggregated_gis_cp_view",
            primary_gpx=golden_route,
            reference_gpx_paths=(reference,),
            workspace_root=tmp_path / "workspaces",
            template_project_root=template,
            profile="pi-offline",
            checkpoint_spacing_m=500.0,
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "aggregated_gis_cp_view"
    view = build_pretrip_admin_view("aggregated_gis_cp_view", project_root=project_root)
    timeline = view["gis_perception_timeline"]
    review_queue = view["review_queue"]
    clustered_hazard = next(
        candidate
        for candidate in timeline["checkpoint_candidates"]
        if candidate["checkpoint_type"] == "warning_review"
    )

    assert view["gis_perception"]["counts"]["checkpoint_candidate_count"] == 5
    assert timeline["counts"]["gpx_checkpoint_candidate_count"] == 5
    assert timeline["counts"]["overpass_checkpoint_candidate_count"] == 9
    assert timeline["counts"]["raw_checkpoint_candidate_count"] == 14
    assert timeline["counts"]["checkpoint_candidate_count"] == 13
    assert timeline["counts"]["nearby_group_count"] == 1
    assert timeline["aggregation"]["strategy"] == "type_semantic_then_spatial_radius"
    assert timeline["aggregation"]["semantic_compatibility_required"] is True
    assert clustered_hazard["aggregation"]["source_candidate_count"] == 2
    assert clustered_hazard["source_attribution_count"] == 2
    assert clustered_hazard["aggregation"]["semantic_aggregation_key"] == (
        "hazard:collapse"
    )
    assert any(
        "大崩壁" in summary
        for summary in clustered_hazard["route_note_summaries"]
    )
    detour_hint = next(
        candidate
        for candidate in timeline["checkpoint_candidates"]
        if candidate["checkpoint_type"] == "hint_review"
        and candidate["aggregation"]["semantic_aggregation_key"] == "route:detour"
    )
    assert detour_hint["aggregation"]["semantic_aggregation_key"] == "route:detour"
    assert detour_hint["aggregation"]["source_candidate_count"] == 1
    vegetation_hint = next(
        candidate
        for candidate in timeline["checkpoint_candidates"]
        if candidate["aggregation"]["semantic_aggregation_key"] == "route:vegetation"
    )
    assert vegetation_hint["stale_route_note"] is True
    assert vegetation_hint["route_note_freshness"] == "stale"
    assert clustered_hazard["nearby_group_id"] == detour_hint["nearby_group_id"]
    assert clustered_hazard["nearby_group_id"] == vegetation_hint["nearby_group_id"]
    assert clustered_hazard["nearby_group_size"] == 3
    overpass_cps = [
        candidate for candidate in timeline["checkpoint_candidates"]
        if candidate.get("source_profile") == "overpass_osm_tags"
    ]
    assert len(overpass_cps) == 9
    assert any(
        attribution["source_kind"] == "overpass_candidate"
        for candidate in overpass_cps
        for attribution in candidate["source_attribution"]
    )
    assert review_queue["counts"]["category_counts"]["gis_perception_cp"] == 13
    assert review_queue["counts"]["category_counts"]["segment_policy"] == 2
    assert review_queue["counts"]["item_count"] == 30
    assert all(
        "seg.040" not in item["candidate_ref"]
        for item in review_queue["items"]
    )
    gis_review_item = next(
        item
        for item in review_queue["items"]
        if item["category"] == "gis_perception_cp"
    )
    assert gis_review_item["candidate_ref"].startswith("gis_cp_cluster.")
    assert gis_review_item["accept_reject_allowed"] is True
    assert gis_review_item["mutation_allowed"] is False
    assert gis_review_item["evidence_summary"]["runtime_safety_truth"] is False


def test_pretrip_import_preserves_workspace_local_imagery_refs(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="imagery ref preserved route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.001, 121.001, 1001.0, "2026-05-01T00:10:00Z"),
        ],
    )
    template_root = tmp_path / "template_project"
    manifest_dir = template_root / "outputs" / "layers" / "manifests"
    manifest_dir.mkdir(parents=True)
    (template_root / "project.json").write_text(
        json.dumps({"project_id": "imagery_import"}, sort_keys=True),
        encoding="utf-8",
    )
    (manifest_dir / "imagery_import.local_raster_source_manifest.json").write_text(
        json.dumps(
            {
                "source_kind": "local_geotiff",
                "source_file": {
                    "path": "/data/scout/raster-sources/imagery_import/map.tiff"
                },
                "handoff": {
                    "scout_kmz_path": "/data/scout/raster-sources/imagery_import/map.kmz"
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (manifest_dir / "imagery_import.raster_tile_pyramid_plan.json").write_text(
        json.dumps({"cache_root": "/data/scout/raster-tiles"}, sort_keys=True),
        encoding="utf-8",
    )

    run_pretrip_import(
        PretripImportRequest(
            project_id="imagery_import",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            template_project_root=template_root,
            profile="pi-offline",
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project = _load(tmp_path / "workspaces" / "imagery_import" / "project.json")

    assert project["imagery_manifest_ref"] == (
        "outputs/layers/manifests/imagery_import.local_raster_source_manifest.json"
    )
    assert project["local_raster_manifest_ref"] == project["imagery_manifest_ref"]
    assert project["raster_tile_manifest_ref"] == (
        "outputs/layers/manifests/imagery_import.raster_tile_pyramid_plan.json"
    )
    assert project["imagery_source_tiff_ref"] == (
        "/data/scout/raster-sources/imagery_import/map.tiff"
    )
    assert project["imagery_source_kmz_ref"] == (
        "/data/scout/raster-sources/imagery_import/map.kmz"
    )
    assert project["imagery_tile_cache_root"] == "/data/scout/raster-tiles"
    assert project["review_queue_manifest_ref"] == "outputs/review_queue_manifest.json"

    review_queue = _load(
        tmp_path
        / "workspaces"
        / "imagery_import"
        / "outputs"
        / "review_queue_manifest.json"
    )
    assert review_queue["boundary"]["candidate_queue_only"] is True
    assert review_queue["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert review_queue["boundary"]["phase2_writeback_allowed"] is False
    assert review_queue["counts"]["item_count"] >= 1


def test_pretrip_import_writes_imagery_scope_from_gpx_bbox_115_percent(
    tmp_path: Path,
) -> None:
    golden_route = _write_gpx(
        tmp_path / "golden-route.gpx",
        name="imagery scope route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.001, 121.002, 1001.0, "2026-05-01T00:10:00Z"),
        ],
    )

    run_pretrip_import(
        PretripImportRequest(
            project_id="imagery_scope",
            primary_gpx=golden_route,
            workspace_root=tmp_path / "workspaces",
            profile="pi-offline",
            import_timestamp="2026-05-21T00:00:00+00:00",
        )
    )

    project_root = tmp_path / "workspaces" / "imagery_scope"
    project = _load(project_root / "project.json")
    manifest = _load(project_root / "outputs" / "import_manifest.json")
    route_bundle = _load(
        project_root / "normalized" / "routes" / "route_evidence_bundle.json"
    )
    expected_bbox = {
        "west": 120.99985,
        "south": 23.999925,
        "east": 121.00215,
        "north": 24.001075,
    }

    assert project["imagery_source_id"] == "nlsc_photo2"
    assert project["imagery_source_registry_id"] == "scout.imagery_sources.default.v1"
    assert project["imagery_bbox_policy"] == "gpx_bbox_scaled_115_percent"
    assert project["imagery_bbox_scale_factor"] == 1.15
    assert project["imagery_bbox_wgs84"] == expected_bbox
    assert manifest["imagery_acquisition_scope"]["bbox_wgs84"] == expected_bbox
    assert route_bundle["imagery_scope_for_map_preparation"]["bbox_wgs84"] == (
        expected_bbox
    )


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_import_candidates_have_pretrip_provenance(
    candidates: list[dict],
    *,
    expected_source_kind: str,
) -> None:
    for candidate in candidates:
        assert candidate["source_refs"]
        assert candidate["source_attribution"]
        assert candidate["source_attribution"][0]["source_kind"] == expected_source_kind
        assert candidate["extractor_version"] == "pretrip_import.0.1.0"
        assert candidate["pydantic_ai_prompt_version"] == (
            "not_applicable_deterministic_pretrip_import"
        )
        assert candidate["model_output_sha256"]
        assert candidate["model_output_summary"]
        assert candidate["confidence"] in {"high", "medium"}
        assert candidate["stale_risk"] == "medium"
        assert candidate["candidate_only"] is True
        assert candidate["runtime_safety_truth"] is False


def _assert_import_projection_items_have_pretrip_provenance(
    items: list[dict],
    *,
    expected_source_kind: str,
) -> None:
    for item in items:
        assert item["source_refs"]
        assert item["source_attribution"]
        assert item["source_attribution"][0]["source_kind"] == expected_source_kind
        assert item["extractor_version"] == "pretrip_import.0.1.0"
        assert item["pydantic_ai_prompt_version"] == (
            "not_applicable_deterministic_pretrip_import"
        )
        assert item["model_output_sha256"]
        assert item["model_output_summary"]
        assert item["confidence"] in {"high", "medium"}
        assert item["stale_risk"] == "medium"
        assert item["review_state"] in {"proposed", "needs_review"}
        assert item["candidate_only"] is True
        assert item["runtime_safety_truth"] is False


def _assert_gis_perception_candidates_have_pretrip_provenance(
    candidates: list[dict],
) -> None:
    for candidate in candidates:
        assert candidate["source_refs"]
        assert candidate["source_attribution"]
        assert candidate["extractor_version"] == "0.1.0"
        assert candidate["pydantic_ai_prompt_version"] == (
            "scout.gis_perception.structured_judgement.v0"
        )
        assert candidate["model_output_sha256"]
        assert candidate["model_output_summary"]
        assert candidate["confidence"] in {"low", "medium", "high"}
        assert candidate["stale_risk"] in {"low", "medium", "high"}
        assert candidate["review_state"] == "needs_review"
        assert candidate["candidate_only"] is True
        assert candidate["runtime_safety_truth"] is False


def _assert_segment_policy_candidates_have_pretrip_provenance(
    candidates: list[dict],
) -> None:
    for candidate in candidates:
        assert candidate["source_refs"]
        assert candidate["source_attribution"]
        assert candidate["source_attribution"][0]["source_kind"] == (
            "pretrip_segment_candidate"
        )
        assert candidate["extractor_version"] == "pretrip_segment_policy.v0.1"
        assert candidate["pydantic_ai_prompt_version"] == (
            "not_applicable_deterministic_segment_policy"
        )
        assert candidate["model_output_sha256"]
        assert candidate["model_output_summary"]
        assert candidate["confidence"] in {"high", "medium"}
        assert candidate["stale_risk"] == "medium"
        assert candidate["candidate_only"] is True
        assert candidate["runtime_safety_truth"] is False


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float, str]],
    waypoints: list[tuple] | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    wpt_records = []
    for waypoint in waypoints or []:
        lat, lon, wpt_name, cmt, desc, *rest = waypoint
        wpt_time = rest[0] if rest else ""
        time_tag = f"<time>{wpt_time}</time>" if wpt_time else ""
        wpt_records.append(
            f'<wpt lat="{lat}" lon="{lon}">'
            f"<name>{wpt_name}</name><cmt>{cmt}</cmt><desc>{desc}</desc>"
            f"{time_tag}</wpt>"
        )
    wpts = "\n".join(wpt_records)
    trkpts = "\n".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele><time>{time}</time></trkpt>'
        for lat, lon, ele, time in points
    )
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
                f"<metadata><name>{name}</name></metadata>",
                wpts,
                "<trk><trkseg>",
                trkpts,
                "</trkseg></trk>",
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_segmented_gpx(
    path: Path,
    *,
    name: str,
    segments: list[list[tuple[float, float, float, str]]],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    track_segments = []
    for segment in segments:
        trkpts = "\n".join(
            f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele><time>{time}</time></trkpt>'
            for lat, lon, ele, time in segment
        )
        track_segments.append("\n".join(["<trk><trkseg>", trkpts, "</trkseg></trk>"]))
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
                f"<metadata><name>{name}</name></metadata>",
                *track_segments,
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_dtm_header(path: Path, *, tile_id: str, origin_x: int, origin_y: int) -> None:
    path.write_text(
        "\n".join(
            [
                "fixture tile",
                tile_id,
                "TWD97[2010]",
                "TWVD2001",
                "5000",
                "20",
                "20",
                "0",
                "144",
                "144",
                str(origin_x),
                str(origin_y),
                "10",
            ]
        )
        + "\n",
        encoding="big5",
    )
