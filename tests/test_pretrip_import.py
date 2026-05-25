import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import create_admin_app
from debug_api import create_debug_app
from pretrip_admin_view import build_pretrip_admin_view
from pretrip_import import PretripImportRequest, run_pretrip_import
from runtime_debug_log import FileRuntimeDebugEventLog

ROOT = Path(__file__).resolve().parents[1]


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
    route_summary = _load(project_root / "normalized" / "routes" / "route_summary.json")
    reference_tracks = _load(project_root / "outputs" / "reference_tracks.json")
    reference_display = _load(project_root / "outputs" / "reference_track_display_geometry.json")
    route_notes = _load(project_root / "candidates" / "route_note_candidates.json")
    gis_ai_judgements = _load(project_root / "outputs" / "gis_perception_ai_judgements.json")
    route_note_ln_proposals = _load(project_root / "outputs" / "route_note_ln_proposals.json")
    gis_perception = _load(project_root / "outputs" / "gis_perception_candidates.json")
    serialized_outputs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in project_root.rglob("*.json")
    )

    assert manifest["profile"] == "pi-offline"
    assert manifest["import_stage"] == "pretrip"
    assert manifest["network_policy"]["network_calls_allowed"] is False
    assert manifest["inputs"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert manifest["counts"]["reference_track_count"] == 2
    assert manifest["counts"]["route_note_candidate_count"] == 3
    assert manifest["counts"]["gis_perception_ai_judgement_count"] == 3
    assert manifest["counts"]["route_note_ln_proposal_count"] == 2
    assert manifest["counts"]["gis_perception_checkpoint_candidate_count"] == 3
    assert manifest["counts"]["debug_projection_event_count"] == 4
    assert manifest["boundary"]["actual_user_track_available"] is False
    assert manifest["boundary"]["unwalked_route_sections_require_manual_waypoints"] is True
    assert manifest["boundary"]["unwalked_route_sections_require_danger_review"] is True
    assert manifest["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert package["source_artifacts"][0]["metadata"]["role"] == "golden_route_reference"
    assert package["source_artifacts"][0]["metadata"]["actual_user_track_available"] is False
    assert project["import_manifest_ref"] == "outputs/import_manifest.json"
    assert project["admin_projection_ref"] == "outputs/admin_projection.json"
    assert project["debug_projection_events_ref"] == "outputs/debug_projection_events.jsonl"
    assert project["route_note_candidates_ref"] == "candidates/route_note_candidates.json"
    assert project["gis_perception_ai_judgements_ref"] == "outputs/gis_perception_ai_judgements.json"
    assert project["route_note_ln_proposals_ref"] == "outputs/route_note_ln_proposals.json"
    assert project["gis_perception_candidates_ref"] == "outputs/gis_perception_candidates.json"
    assert project["route_role"] == "golden_route"
    assert project["actual_user_track_available"] is False
    assert route_summary["route_name"] == "golden route import"
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
    assert admin_projection["gis_perception"]["source_profile"] == "gpx_corpus_route_notes"
    assert admin_projection["gis_perception"]["boundary"]["candidate_only"] is True
    assert admin_projection["gis_perception"]["ai_judgements"]["judgement_count"] == 3
    assert admin_projection["gis_perception"]["ai_judgements"]["network_calls_allowed"] is False
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
    assert all(
        judgement["runtime_safety_truth"] is False
        for judgement in gis_ai_judgements["judgements"]
    )
    assert route_note_ln_proposals["counts"]["proposal_count"] == 2
    assert gis_perception["counts"]["checkpoint_candidate_count"] == 3
    assert gis_perception["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert all(
        candidate["source_attribution"]
        and candidate["source_attribution"][0]["source_kind"] == "gpx_route_note"
        for candidate in gis_perception["checkpoint_candidates"]
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


def test_pretrip_import_cli_copies_template_workspace_without_mutating_template(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    refs = inbox / "refs"
    refs.mkdir(parents=True)
    golden_route = _write_gpx(
        inbox / "golden-route.gpx",
        name="cli golden route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.01, 121.01, 1010.0, "2026-05-01T00:10:00Z"),
        ],
    )
    _write_gpx(
        refs / "reference.gpx",
        name="cli reference",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.02, 121.02, 1020.0, "2026-05-01T00:20:00Z"),
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
    assert review_queue["counts"]["item_count"] == 57
    gis_review_item = next(
        item
        for item in review_queue["items"]
        if item["category"] == "gis_perception_cp"
    )
    assert gis_review_item["candidate_ref"].startswith("gis_cp_cluster.")
    assert gis_review_item["accept_reject_allowed"] is True
    assert gis_review_item["mutation_allowed"] is False
    assert gis_review_item["evidence_summary"]["runtime_safety_truth"] is False


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
