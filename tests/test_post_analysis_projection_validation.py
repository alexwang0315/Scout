"""Real selection/load regressions for persisted after-action provenance."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from post_analysis_completed_trip_recordings import (
    list_completed_trip_recordings,
    load_active_completed_trip_recording_projection,
    select_completed_trip_recording_for_post_analysis,
)
from post_analysis_completed_trip_scenarios import (
    load_active_completed_trip_scenario_projection,
    select_completed_trip_scenario_for_post_analysis,
)


ROOT = Path(__file__).resolve().parents[1]


def _json(path):
    return json.loads(path.read_text())


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _gpx(path, latitude="23.0"):
    path.parent.mkdir(parents=True, exist_ok=True)
    lat = float(latitude)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        f'<trkpt lat="{lat}" lon="121.0"><ele>100</ele><time>2026-01-01T00:00:00Z</time></trkpt>'
        f'<trkpt lat="{lat + .01}" lon="121.0"><ele>120</ele><time>2026-01-01T00:30:00Z</time></trkpt>'
        f'<trkpt lat="{lat + .02}" lon="121.0"><ele>150</ele><time>2026-01-01T01:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>'
    )


def _workspace(parent, project_id, latitude="23.0"):
    project = parent / project_id
    _write(project / "project.json", {
        "project_id": project_id,
        "route_family": project_id,
        "checkpoint_candidates_ref": "candidates/checkpoints.json",
        "segment_candidates_ref": "candidates/segments.json",
    })
    _write(project / "candidates/checkpoints.json", [
        {"candidate_id": "cp.start", "label": "Start", "lat": float(latitude), "lon": 121.0, "arrival_radius_m": 50},
        {"candidate_id": "cp.end", "label": "End", "lat": float(latitude) + .02, "lon": 121.0, "arrival_radius_m": 50},
    ])
    _write(project / "candidates/segments.json", [
        {"candidate_id": "seg.1", "from_candidate_id": "cp.start", "to_candidate_id": "cp.end", "distance_m": 2224.0}
    ])
    _gpx(project / "post_analysis/completed_trips/recorded/primary_user/track.gpx", latitude)
    catalog = list_completed_trip_recordings(data_root=parent / "data", project_id=project_id, project_root=project)
    selected = select_completed_trip_recording_for_post_analysis(
        catalog["recordings"][0]["recording_id"],
        data_root=parent / "data", project_id=project_id, project_root=project,
    )
    return project, Path(selected["paths"]["active_recording_record"])


@pytest.fixture
def selection(tmp_path):
    project, active_path = _workspace(tmp_path, "audit_project_a")
    return tmp_path, project, active_path


def _load(selection):
    data, project, _ = selection
    return load_active_completed_trip_recording_projection(
        data_root=data / "data", project_id=project.name, project_root=project,
    )


def _assert_rejected(result, code):
    assert result["status"] == "rejected"
    assert result["projection_validation"]["issues"][0]["code"] == code
    assert result["projection_validation"]["issues"][0]["message"]
    assert not {"capability_timeline", "completed_trip_track", "scout_reaction_simulation"} & result.keys()
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["human_review_required"] is True


def test_valid_workspace_selection_keeps_capability_and_rebuilds_cached_track(selection):
    _, _, active_path = selection
    active = _json(active_path)
    expected = active["capability_timeline"]["summary"]
    active["completed_trip_track"] = {"sentinel": "wrong cached track"}
    active["capability_timeline"] = {"sentinel": "wrong cached summary"}
    _write(active_path, active)
    result = _load(selection)
    assert result["capability_timeline"]["summary"] == expected
    assert result["completed_trip_track"].get("sentinel") is None
    assert result["projection_validation"]["status"] == "validated"


def test_requested_project_id_still_must_match_project_json(selection):
    data, project, _ = selection
    with pytest.raises(ValueError, match="project id does not match"):
        load_active_completed_trip_recording_projection(
            data_root=data / "data", project_id="other_project", project_root=project,
        )


@pytest.mark.parametrize("key,code", [
    ("project_id", "project_id_mismatch"),
    ("case_id", "case_id_mismatch"),
])
def test_active_record_identity_mismatch_is_rejected(selection, key, code):
    _, _, path = selection
    active = _json(path)
    active[key] = "other_project"
    _write(path, active)
    _assert_rejected(_load(selection), code)


def test_other_workspace_outputs_cannot_replace_requested_workspace(selection):
    data, _, path = selection
    _, other_path = _workspace(data, "audit_project_b", latitude="24.0")
    active = _json(path)
    active["outputs_dir"] = _json(other_path)["outputs_dir"]
    _write(path, active)
    _assert_rejected(_load(selection), "outputs_path_mismatch")


def test_other_recording_outputs_in_same_workspace_are_rejected(selection):
    _, _, path = selection
    active = _json(path)
    outputs = Path(active["outputs_dir"])
    other = outputs.with_name("different_recording")
    shutil.copytree(outputs, other)
    active["outputs_dir"] = str(other)
    _write(path, active)
    _assert_rejected(_load(selection), "outputs_path_mismatch")


def test_timeline_from_other_case_inside_expected_directory_is_rejected(selection):
    _, _, path = selection
    timeline_path = Path(_json(path)["outputs_dir"]) / "capability_timeline.json"
    timeline = _json(timeline_path)
    timeline["case_id"] = "other_project.other_recording"
    _write(timeline_path, timeline)
    _assert_rejected(_load(selection), "analysis_case_id_mismatch")


def test_capsule_from_other_case_is_rejected(selection):
    _, _, path = selection
    capsule_path = Path(_json(path)["outputs_dir"]) / "capability_capsule.json"
    capsule = _json(capsule_path)
    capsule["case_id"] = "other_project.other_recording"
    _write(capsule_path, capsule)
    _assert_rejected(_load(selection), "analysis_case_id_mismatch")


def test_active_track_changed_after_analysis_is_rejected(selection):
    _, _, path = selection
    gpx = Path(_json(path)["active_completed_track_gpx"])
    gpx.write_text(gpx.read_text() + "\n")
    _assert_rejected(_load(selection), "source_track_hash_mismatch")


def test_timeline_source_path_mismatch_is_rejected(selection):
    _, _, path = selection
    timeline_path = Path(_json(path)["outputs_dir"]) / "capability_timeline.json"
    timeline = _json(timeline_path)
    timeline["source_track"]["source_path"] = "/unrelated/track.gpx"
    _write(timeline_path, timeline)
    _assert_rejected(_load(selection), "source_track_path_mismatch")


def test_output_symlink_cannot_escape_to_other_workspace(selection):
    data, _, path = selection
    _, other_path = _workspace(data, "audit_project_b", latitude="24.0")
    active = _json(path)
    outputs = Path(active["outputs_dir"])
    outputs.rename(outputs.with_name(outputs.name + ".preserved"))
    outputs.symlink_to(Path(_json(other_path)["outputs_dir"]), target_is_directory=True)
    _assert_rejected(_load(selection), "outputs_path_mismatch")


def test_missing_artifact_does_not_fall_back_to_embedded_cached_summary(selection):
    _, _, path = selection
    active = _json(path)
    assert active["capability_timeline"]
    timeline_path = Path(active["outputs_dir"]) / "capability_timeline.json"
    timeline_path.rename(timeline_path.with_suffix(".preserved"))
    _assert_rejected(_load(selection), "timeline_missing")


def test_malformed_active_record_returns_explained_rejection(selection):
    _, _, path = selection
    path.write_text("{ unfinished")
    _assert_rejected(_load(selection), "artifact_unreadable")


def test_reaction_from_other_case_is_rejected(selection):
    _, _, path = selection
    reaction_path = Path(_json(path)["outputs_dir"]) / "scout_reaction_simulation.json"
    reaction = _json(reaction_path)
    reaction["case_id"] = "other_project"
    _write(reaction_path, reaction)
    _assert_rejected(_load(selection), "reaction_identity_mismatch")


def test_catalog_exposes_rejection_instead_of_invalid_active_selection(selection):
    data, project, path = selection
    active = _json(path)
    active["case_id"] = "other_project"
    _write(path, active)
    catalog = list_completed_trip_recordings(
        data_root=data / "data", project_id=project.name, project_root=project,
    )
    assert catalog["active_recording"] is None
    assert catalog["active_projection_validation"]["status"] == "rejected"


def _legacy_scenario(data_root):
    scenario_root = data_root / "materials/post_analysis/chilai_nanhua_day1/completed_trip_scenarios"
    scenario_root.mkdir(parents=True)
    gpx = scenario_root / "legacy_scenario.gpx"
    shutil.copy2(ROOT / "tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/completed_track.gpx", gpx)
    _write(scenario_root / "manifest.json", {"generated_files": [
        {"scenario_id": "legacy_scenario", "path": str(gpx), "sha256": hashlib.sha256(gpx.read_bytes()).hexdigest()}
    ]})
    selected = select_completed_trip_scenario_for_post_analysis("legacy_scenario", data_root=data_root)
    return Path(selected["paths"]["active_scenario_record"])


def test_legal_legacy_scenario_keeps_original_metrics(tmp_path):
    active_path = _legacy_scenario(tmp_path)
    expected = _json(active_path)["capability_timeline"]["summary"]
    loaded = load_active_completed_trip_scenario_projection(data_root=tmp_path)
    assert loaded["capability_timeline"]["summary"] == expected
    assert loaded["capability_timeline"]["summary"]["moving_time_s"] == 121605
    assert loaded["projection_validation"]["status"] == "validated"


def test_legacy_scenario_rejects_foreign_outputs(tmp_path):
    active_path = _legacy_scenario(tmp_path)
    _, other_path = _workspace(tmp_path, "audit_project_b")
    active = _json(active_path)
    active["outputs_dir"] = _json(other_path)["outputs_dir"]
    _write(active_path, active)
    _assert_rejected(load_active_completed_trip_scenario_projection(data_root=tmp_path), "outputs_path_mismatch")


def test_legal_legacy_recording_without_new_project_field_still_loads(tmp_path):
    recorded = tmp_path / "post_analysis/completed_trips/chilai_nanhua_day1/recorded/primary_user/track.gpx"
    recorded.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "tests/fixtures/post_analysis/chilai_nanhua_day1_post_analysis/completed_track.gpx", recorded)
    catalog = list_completed_trip_recordings(data_root=tmp_path)
    selected = select_completed_trip_recording_for_post_analysis(catalog["recordings"][0]["recording_id"], data_root=tmp_path)
    active_path = Path(selected["paths"]["active_recording_record"])
    active = _json(active_path)
    active.pop("project_id")
    _write(active_path, active)
    result = load_active_completed_trip_recording_projection(data_root=tmp_path)
    assert result["capability_timeline"]["summary"]["moving_time_s"] == 121605
    assert result["projection_validation"]["status"] == "validated"


def test_replaced_shared_legacy_inbox_invalidates_old_scenario(tmp_path):
    _legacy_scenario(tmp_path)
    recorded = tmp_path / "post_analysis/completed_trips/chilai_nanhua_day1/recorded/primary_user/different.gpx"
    _gpx(recorded)
    catalog = list_completed_trip_recordings(data_root=tmp_path)
    select_completed_trip_recording_for_post_analysis(catalog["recordings"][0]["recording_id"], data_root=tmp_path)
    _assert_rejected(load_active_completed_trip_scenario_projection(data_root=tmp_path), "source_track_hash_mismatch")
    assert load_active_completed_trip_recording_projection(data_root=tmp_path)["projection_validation"]["status"] == "validated"


def test_changed_gpx_during_track_projection_is_rejected(selection, monkeypatch):
    import post_analysis_completed_trip_recordings as recordings

    original = recordings.build_completed_trip_track_projection

    def change_after_build(gpx, **kwargs):
        result = original(gpx, **kwargs)
        gpx.write_text(gpx.read_text() + "\n")
        return result

    monkeypatch.setattr(recordings, "build_completed_trip_track_projection", change_after_build)
    _assert_rejected(_load(selection), "projection_changed_during_read")


def test_active_gpx_path_cannot_point_to_other_workspace(selection):
    data, _, path = selection
    _, other_path = _workspace(data, "audit_project_b")
    active = _json(path)
    active["active_completed_track_gpx"] = _json(other_path)["active_completed_track_gpx"]
    _write(path, active)
    _assert_rejected(_load(selection), "active_track_path_mismatch")


def test_timeline_symlink_cannot_escape_expected_output_directory(selection):
    data, _, path = selection
    _, other_path = _workspace(data, "audit_project_b")
    timeline = Path(_json(path)["outputs_dir"]) / "capability_timeline.json"
    timeline.rename(timeline.with_suffix(".preserved"))
    timeline.symlink_to(Path(_json(other_path)["outputs_dir"]) / "capability_timeline.json")
    _assert_rejected(_load(selection), "timeline_path_mismatch")


def test_recording_metadata_hash_disagreement_is_rejected(selection):
    _, _, path = selection
    active = _json(path)
    active["recording"]["sha256"] = "0" * 64
    _write(path, active)
    _assert_rejected(_load(selection), "selection_track_hash_mismatch")


def test_admin_case_api_exposes_foreign_output_rejection(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from admin_api import create_admin_app

    project_id = "chilai_nanhua_day1"
    workspaces = tmp_path / "workspaces"
    project = workspaces / project_id
    shutil.copytree(ROOT / "tests/fixtures/pretrip/projects" / project_id, project)
    recorded = project / "post_analysis/completed_trips/recorded/primary_user/track.gpx"
    _gpx(recorded)
    catalog = list_completed_trip_recordings(
        data_root=tmp_path / "data", project_id=project_id, project_root=project,
    )
    selected = select_completed_trip_recording_for_post_analysis(
        catalog["recordings"][0]["recording_id"],
        data_root=tmp_path / "data", project_id=project_id, project_root=project,
    )
    _, other_active_path = _workspace(workspaces, "audit_project_b")
    active_path = Path(selected["paths"]["active_recording_record"])
    active = _json(active_path)
    active["outputs_dir"] = _json(other_active_path)["outputs_dir"]
    _write(active_path, active)
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    client = TestClient(create_admin_app(
        pretrip_workspace_root=workspaces, runtime_audit_root=tmp_path / "audit",
    ))
    try:
        response = client.get("/admin/cases/" + project_id)
    finally:
        client.close()
    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == project_id
    assert "audit_project_b" not in payload.get("capability_timeline", {}).get("case_id", "")
    assert payload["completed_trip_recordings"]["active_recording"] is None
    rejected = payload["completed_trip_recordings"]["active_projection_validation"]
    assert rejected["status"] == "rejected"
    assert rejected["issues"][0]["code"] == "outputs_path_mismatch"
    assert rejected["issues"][0]["message"]

@pytest.mark.parametrize("name,field", [
    ("capability_capsule.json", "route_family"),
    ("capability_share_preview.json", "case_id"),
    ("capability_share_preview.json", "route_family"),
    ("capability_route_time_comparison.json", "case_id"),
    ("capability_route_time_comparison.json", "route_family"),
])
def test_companion_artifact_identity_mismatch_is_rejected(selection, name, field):
    _, project, active_path = selection
    active = _json(active_path)
    path = Path(active["outputs_dir"]) / name
    artifact = _json(path) if path.exists() else {
        "case_id": f"{project.name}.{active['recording']['recording_id']}",
        "route_family": project.name,
        "segments": [],
    }
    artifact[field] = "other_case" if field == "case_id" else "other_route"
    _write(path, artifact)
    _assert_rejected(_load(selection), f"companion_{field}_mismatch")


@pytest.mark.parametrize("name,fields", [
    ("capability_capsule.json", ["route_family"]),
    ("capability_share_preview.json", ["case_id", "route_family"]),
    ("capability_route_time_comparison.json", ["case_id", "route_family"]),
])
def test_legacy_companion_optional_identity_fields_may_be_absent(selection, name, fields):
    _, _, active_path = selection
    path = Path(_json(active_path)["outputs_dir"]) / name
    artifact = _json(path) if path.exists() else {"segments": []}
    for field in fields:
        artifact.pop(field, None)
    _write(path, artifact)
    assert _load(selection)["projection_validation"]["status"] == "validated"


def test_admin_pretrip_compact_rejection_restores_reference_import_after_cached_active(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from admin_api import create_admin_app

    project_id = "chilai_nanhua_day1"
    workspaces = tmp_path / "workspaces"
    project = workspaces / project_id
    shutil.copytree(ROOT / "tests/fixtures/pretrip/projects" / project_id, project)
    monkeypatch.setenv("SCOUT_DATA_ROOT", str(tmp_path / "data"))
    with TestClient(create_admin_app(
        pretrip_workspace_root=workspaces, runtime_audit_root=tmp_path / "audit",
    )) as client:
        endpoint = "/admin/pretrip/projects/" + project_id + "?compact=1"
        before = client.get(endpoint)
        assert before.status_code == 200
        reference = before.json()["capability_timeline_import"]
        assert reference["summary"]["moving_time_s"] == 121605

        _gpx(project / "post_analysis/completed_trips/recorded/primary_user/track.gpx")
        catalog = list_completed_trip_recordings(
            data_root=tmp_path / "data", project_id=project_id, project_root=project,
        )
        selected = select_completed_trip_recording_for_post_analysis(
            catalog["recordings"][0]["recording_id"],
            data_root=tmp_path / "data", project_id=project_id, project_root=project,
        )
        active = client.get(endpoint)
        assert active.status_code == 200
        assert active.json()["completed_trip_recordings"]["active_projection_validation"]["status"] == "validated"
        assert active.json()["capability_timeline"]["case_id"] == project_id + "." + selected["recording"]["recording_id"]

        capsule_path = Path(selected["paths"]["capability_capsule"])
        capsule = _json(capsule_path)
        capsule["route_family"] = "other_route"
        _write(capsule_path, capsule)
        after = client.get(endpoint)
    assert after.status_code == 200
    payload = after.json()
    catalog = payload["completed_trip_recordings"]
    assert catalog["active_recording"] is None
    assert catalog["active_projection_validation"]["status"] == "rejected"
    assert catalog["active_projection_validation"]["issues"][0]["code"] == "companion_route_family_mismatch"
    assert payload["capability_timeline_import"] == reference
    assert payload["reference_tracks"] == before.json()["reference_tracks"]
    assert not payload.get("capability_timeline")
    assert not payload.get("completed_trip_track")
    assert not payload.get("active_completed_trip_recording")
