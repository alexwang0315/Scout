"""Weather endpoint parity without rebuilding the unrelated map projections."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import admin_api
import pretrip_admin_view as views
from admin_weather_overlay import (
    build_pretrip_weather_overlay,
    build_weather_api_runtime_status,
)
from scout_gee_integration import build_gee_runtime_status


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "chilai_nanhua_day1"
FIXTURE_ROOT = ROOT / "tests/fixtures/pretrip/projects" / PROJECT_ID


@pytest.fixture
def workspace(tmp_path):
    project_root = tmp_path / PROJECT_ID
    shutil.copytree(FIXTURE_ROOT, project_root)
    return project_root


def _project(project_root):
    return json.loads((project_root / "project.json").read_text())


def _write_project(project_root, project):
    (project_root / "project.json").write_text(json.dumps(project))


def _projection(project_root):
    return views.load_pretrip_weather_projection(PROJECT_ID, project_root=project_root)


@pytest.mark.parametrize("source_state", ["present", "missing_file", "missing_ref", "empty"])
def test_weather_projection_matches_full_view_and_provenance(workspace, source_state):
    project = _project(workspace)
    weather_path = workspace / project["weather_daylight_evidence_ref"]
    if source_state == "missing_file":
        weather_path.unlink()
    elif source_state == "missing_ref":
        project.pop("weather_daylight_evidence_ref")
        _write_project(workspace, project)
    elif source_state == "empty":
        weather_path.write_text("{}")

    full = views.build_pretrip_admin_view(PROJECT_ID, project_root=workspace)
    small = _projection(workspace)

    assert small["weather"] == full["weather"]
    assert small["route"]["bounds"] == full["route"]["bounds"]
    assert small["weather"]["candidate_only"] is True
    assert small["weather"]["runtime_safety_truth"] is False
    assert small["weather"]["source_refs"]
    if source_state != "present":
        assert small["weather"]["status"] == "missing_source"
    if source_state == "missing_ref":
        assert small["weather"]["source_path"] == (
            "outputs/missing/weather_daylight_evidence.json"
        )


def test_builtin_fixture_weather_projection_preserves_repository_relative_refs():
    full = views.build_pretrip_admin_view(PROJECT_ID)
    small = views.load_pretrip_weather_projection(PROJECT_ID)
    assert small["weather"] == full["weather"]
    assert small["route"]["bounds"] == full["route"]["bounds"]
    assert small["weather"]["source_path"].startswith("tests/fixtures/pretrip/")


def test_weather_projection_reads_only_project_route_and_weather(workspace, monkeypatch):
    project = _project(workspace)
    allowed = {
        workspace / "project.json",
        workspace / project["route_summary_ref"],
        workspace / project["weather_daylight_evidence_ref"],
    }
    reads = []
    original = views._load_json

    def checked_read(path):
        assert path in allowed, f"unrelated weather input read: {path.name}"
        reads.append(path)
        return original(path)

    monkeypatch.setattr(views, "_load_json", checked_read)
    _projection(workspace)
    assert set(reads) == allowed


def test_weather_projection_observes_edit_remove_restore_and_ref_change(workspace):
    project = _project(workspace)
    original_path = workspace / project["weather_daylight_evidence_ref"]
    original = json.loads(original_path.read_text())
    first = _projection(workspace)
    edited = {**original, "location_name": "edited same-request weather source"}
    original_path.write_text(json.dumps(edited))
    assert _projection(workspace)["weather"]["location_name"] == edited["location_name"]
    original_path.unlink()
    assert _projection(workspace)["weather"]["status"] == "missing_source"
    original_path.write_text(json.dumps(original))
    assert _projection(workspace) == first
    alternate = workspace / "outputs/alternate_weather.json"
    alternate.write_text(json.dumps(edited))
    project["weather_daylight_evidence_ref"] = "outputs/alternate_weather.json"
    _write_project(workspace, project)
    changed = _projection(workspace)
    assert changed["weather"]["source_path"] == "outputs/alternate_weather.json"
    assert changed["weather"]["location_name"] == edited["location_name"]


def test_weather_projection_observes_route_bounds_edits(workspace):
    route_path = workspace / _project(workspace)["route_summary_ref"]
    route = json.loads(route_path.read_text())
    first = _projection(workspace)["route"]["bounds"]
    route["bbox_wgs84"] = {
        "min_lat": 23.0, "max_lat": 23.1, "min_lon": 121.0, "max_lon": 121.1
    }
    route_path.write_text(json.dumps(route))
    assert _projection(workspace)["route"]["bounds"] == route["bbox_wgs84"] != first


@pytest.mark.parametrize("ref_key", ["weather_daylight_evidence_ref", "route_summary_ref", "map_context_ref"])
@pytest.mark.parametrize("escape", ["relative", "absolute", "symlink"])
def test_weather_projection_retains_all_artifact_containment_checks(workspace, ref_key, escape):
    project = _project(workspace)
    outside = workspace.parent / "outside.json"
    outside.write_text('{"sentinel":"must not be loaded"}')
    if escape == "relative":
        project[ref_key] = "../outside.json"
    elif escape == "absolute":
        project[ref_key] = str(outside)
    else:
        (workspace / "escape.json").symlink_to(outside)
        project[ref_key] = "escape.json"
    _write_project(workspace, project)
    with pytest.raises(ValueError, match="unsafe pre-trip project artifact ref"):
        _projection(workspace)


@pytest.mark.parametrize("invalid", ["missing_project", "wrong_identity", "unknown_fixture"])
def test_weather_projection_rejects_invalid_project_identity(workspace, invalid):
    if invalid == "missing_project":
        (workspace / "project.json").unlink()
    elif invalid == "wrong_identity":
        project = _project(workspace)
        project["project_id"] = "another_workspace"
        _write_project(workspace, project)
    with pytest.raises(KeyError):
        if invalid == "unknown_fixture":
            views.load_pretrip_weather_projection("not-a-builtin-project")
        else:
            _projection(workspace)


@pytest.mark.parametrize("damage", ["invalid_json", "invalid_weather", "missing_route"])
def test_weather_projection_does_not_hide_corrupt_or_required_inputs(workspace, damage):
    project = _project(workspace)
    if damage == "missing_route":
        (workspace / project["route_summary_ref"]).unlink()
        expected = FileNotFoundError
    else:
        (workspace / project["weather_daylight_evidence_ref"]).write_text(
            "{" if damage == "invalid_json" else '{"status":"incomplete"}'
        )
        expected = json.JSONDecodeError if damage == "invalid_json" else KeyError
    with pytest.raises(expected):
        _projection(workspace)


@pytest.mark.parametrize("provider", ["disabled", "open_meteo", "open_meteo_failure"])
def test_weather_overlay_api_keeps_full_view_contract_without_full_builder(workspace, monkeypatch, provider):
    full = views.build_pretrip_admin_view(PROJECT_ID, project_root=workspace)
    runtime = build_weather_api_runtime_status({
        "SCOUT_WEATHER_API_ENABLED": "false" if provider == "disabled" else "true",
        "SCOUT_WEATHER_API_PROVIDER": "open_meteo",
    })
    gee = build_gee_runtime_status({})
    snapshot = {
        "artifact_kind": "open_meteo_weather_snapshot",
        "status": "live_summary_ready", "provider": "open_meteo",
        "current": {"temperature_2m_c": 18.2},
        "external_api_calls_made": True,
        "authoritative_weather_computed": False,
        "raw_payloads_embedded": False,
        "human_review_required": True,
    }
    seen_bounds = []

    def fake_fetch(bounds):
        assert provider != "disabled", "disabled weather must not call its provider"
        seen_bounds.append(bounds)
        if provider == "open_meteo_failure":
            raise TimeoutError("fixture provider deadline")
        return snapshot

    def forbidden_full(*args, **kwargs):
        pytest.fail("weather overlay rebuilt unrelated full Dashboard projections")

    monkeypatch.setattr(admin_api, "build_pretrip_admin_view", forbidden_full)
    monkeypatch.setattr(admin_api, "build_weather_api_runtime_status", lambda: runtime)
    monkeypatch.setattr(admin_api, "build_gee_runtime_status", lambda: gee)
    monkeypatch.setattr(admin_api, "fetch_open_meteo_weather_snapshot", fake_fetch)
    client = TestClient(admin_api.create_admin_app(pretrip_workspace_root=workspace.parent))
    response = client.get(f"/admin/pretrip/projects/{PROJECT_ID}/weather-overlay")
    assert response.status_code == 200
    expected_snapshot = snapshot if provider == "open_meteo" else None
    if provider == "open_meteo_failure":
        expected_snapshot = {
            "artifact_kind": "open_meteo_weather_snapshot",
            "status": "live_summary_failed", "provider": "open_meteo",
            "external_api_calls_made": True,
            "raw_payloads_embedded": False,
            "authoritative_weather_computed": False,
            "human_review_required": True,
            "error_summary": "fixture provider deadline",
        }
    expected = build_pretrip_weather_overlay(
        {**full["weather"], "project_id": PROJECT_ID},
        runtime_status=runtime, gee_runtime_status=gee,
        live_weather_snapshot=expected_snapshot,
    )
    assert response.json() == expected
    assert seen_bounds == ([] if provider == "disabled" else [full["route"]["bounds"]])


def test_weather_overlay_api_preserves_unknown_project_404(workspace, monkeypatch):
    def forbidden_provider(*args, **kwargs):
        pytest.fail("invalid project must not reach the weather provider")

    monkeypatch.setattr(admin_api, "fetch_open_meteo_weather_snapshot", forbidden_provider)
    client = TestClient(admin_api.create_admin_app(pretrip_workspace_root=workspace.parent))
    response = client.get("/admin/pretrip/projects/unknown-workspace/weather-overlay")
    assert response.status_code == 404
    assert response.json() == {"detail": "Pre-trip project not found"}
