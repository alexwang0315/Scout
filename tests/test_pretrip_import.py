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
    )
    _write_gpx(
        references / "reference-a.gpx",
        name="reference a",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.02, 121.02, 1030.0, "2026-05-01T00:30:00Z"),
        ],
    )
    _write_gpx(
        references / "reference-b.gpx",
        name="reference b",
        points=[
            (24.001, 121.001, 1001.0, "2026-05-01T00:00:00Z"),
            (24.015, 121.015, 1015.0, "2026-05-01T00:20:00Z"),
        ],
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
    serialized_outputs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in project_root.rglob("*.json")
    )

    assert manifest["profile"] == "pi-offline"
    assert manifest["import_stage"] == "pretrip"
    assert manifest["network_policy"]["network_calls_allowed"] is False
    assert manifest["inputs"]["golden_route_gpx"]["role"] == "golden_route_reference"
    assert manifest["counts"]["reference_track_count"] == 2
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
    assert view["debug_projection"]["event_count"] == 4
    assert view["import_manifest"]["network_policy"]["network_calls_allowed"] is False
    assert {"import_manifest", "admin_surface_projection", "debug_projection"} <= post_sections


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float, str]],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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
                "<trk><trkseg>",
                trkpts,
                "</trkseg></trk>",
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )
    return path
