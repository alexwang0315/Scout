"""Shared analysis identity through isolated real API Save/Accept/Rebuild paths."""
from __future__ import annotations

import hashlib
import json

import pytest

from scout_analysis_subject import build_analysis_subject, capture_analysis_geometry_binding
from test_scout_reference_gpx_workbench import (
    DASHBOARD, PROJECT_ID, _accept, _files, _fixture, _generate, _save,
)
from test_scout_reference_gpx_reconstruction import CP_REF, PRIMARY_REF


SUBJECT = f"/admin/pretrip/projects/{PROJECT_ID}/analysis-subject"


def _write(root, ref, value):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _sources(root):
    sha = hashlib.sha256((root / PRIMARY_REF).read_bytes()).hexdigest()
    _write(root, "outputs/gpx_speed_filter_report.json", {
        "primary": {"output_path": PRIMARY_REF, "output_sha256": sha},
    })
    if not (root / "candidates/checkpoints.json").exists():
        _write(root, "candidates/checkpoints.json", {
            "checkpoints": json.loads((root / CP_REF).read_text())["events"],
        })
    _write(root, "outputs/segment_display_geometry.json", {
        "source_gpx": {"sha256": sha}, "segments": [{
            "segment_candidate_id": "seg.day-crossing", "from_candidate_id": "cp.019",
            "to_candidate_id": "cp.021", "route_point_start_index": 19, "route_point_end_index": 21,
        }],
    })


def _rebuilt(tmp_path):
    client, root, _ = _fixture(tmp_path)
    _sources(root)
    draft = _generate(client)
    saved_response = _save(client, draft)
    assert saved_response.status_code == 200, saved_response.text
    accepted = _accept(client, draft, saved_response.json())
    assert accepted.status_code == 200, accepted.text
    admission = client.get(DASHBOARD).json()["rebuild"]
    rebuilt = client.post(f"{DASHBOARD}/rebuilds", json={
        "expected_reviewed_baseline_sha256": accepted.json()["reviewed_baseline_sha256"],
        "expected_admission_snapshot_sha256": admission["canonical_snapshot_sha256"],
        "expected_evaluator_version": admission["evaluator_version"],
        "idempotency_key": "six-axis-rebuild-001", "explicit_confirmation": True,
    })
    assert rebuilt.status_code == 200, rebuilt.text
    return client, root, draft, rebuilt.json()


def test_unaccepted_analysis_subject_is_read_only_and_does_not_invent_schedule(tmp_path):
    client, root, _ = _fixture(tmp_path)
    _sources(root)
    before = _files(root)
    response = client.get(SUBJECT)
    assert response.status_code == 200, response.text
    value = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert value["project_id"] == PROJECT_ID
    assert value["schedule_status"] == "not_adopted"
    assert value["mission_day_estimates"] == []
    assert value["sources"]["golden_geometry"]["sha256"] == hashlib.sha256((root / PRIMARY_REF).read_bytes()).hexdigest()
    assert _files(root) == before


def test_rebuild_retires_legacy_timing_and_exposes_original_adopted_schedule(tmp_path):
    client, root, draft, receipt = _rebuilt(tmp_path)
    eta = json.loads((root / receipt["planned_eta_ref"]).read_text())
    assert "assumption" not in eta and "estimates" not in eta
    assert eta["retired_legacy_timing"]["status"] == "superseded"
    assert eta["authoritative_collection"] == "mission_day_estimates"
    before = _files(root)
    value = client.get(SUBJECT).json()
    assert value["schedule_status"] == "adopted", value
    assert [d["eta"]["observed_elapsed_minutes"] for d in value["mission_day_estimates"]] == [600, 360]
    assert value["mission_day_estimates"][0]["reference_replay"] == draft["days"][0]["reference_replay"]
    assert value["day_segment_mapping"][0]["cp_segments"][0]["crosses_day_boundary"] is True
    assert value["timezone"] == "Asia/Taipei"
    assert value["dependencies"]["weather"]["historical_weather_status"] == "unknown"
    assert value["runtime_safety_truth"] is False
    assert value["departure_approval_granted"] is False
    assert _files(root) == before


@pytest.mark.parametrize("rewrite_seed", [False, True])
def test_eta_change_is_stale_even_if_mutable_seed_hash_is_rewritten(tmp_path, rewrite_seed):
    client, root, _, receipt = _rebuilt(tmp_path)
    before = client.get(SUBJECT).json()
    path = root / receipt["planned_eta_ref"]
    eta = json.loads(path.read_text())
    eta["mission_day_estimates"][0]["eta"]["observed_elapsed_minutes"] = 480
    path.write_text(json.dumps(eta))
    if rewrite_seed:
        seed_path = root / receipt["workbench_seed_ref"]
        seed = json.loads(seed_path.read_text())
        seed["baseline"]["source_hashes"]["planned_eta_ref"] = hashlib.sha256(path.read_bytes()).hexdigest()
        seed_path.write_text(json.dumps(seed))
    after = _files(root)
    projection = client.get(DASHBOARD).json()
    assert projection["status"] == "blocked"
    assert projection["error"]["code"] == "contextual_permission_projection_stale"
    subject = client.get(SUBJECT).json()
    assert subject["schedule_status"] == "stale"
    assert subject["mission_day_estimates"] == []
    assert "planned_eta_rebuild_binding_mismatch" in subject["issues"]
    assert subject["analysis_revision"] != before["analysis_revision"]
    assert _files(root) == after


def test_changed_recorded_cp_source_invalidates_adopted_schedule(tmp_path):
    client, root, _, _ = _rebuilt(tmp_path)
    before = client.get(SUBJECT).json()
    payload = json.loads((root / CP_REF).read_text())
    payload["events"][0]["observed_at"] = None
    _write(root, CP_REF, payload)
    subject = client.get(SUBJECT).json()
    assert subject["schedule_status"] == "stale"
    assert subject["issues"] == ["reviewed_source_changed"]
    assert subject["mission_day_estimates"] == []
    assert subject["timing_fingerprint"] != before["timing_fingerprint"]


def test_preparation_receipt_binds_inputs_and_outputs_without_marking_retained_data_current(tmp_path):
    _, root, _ = _fixture(tmp_path)
    _sources(root)
    binding = capture_analysis_geometry_binding(root)
    ref = "outputs/navigation/test_projection.json"
    _write(root, ref, {"status": "ready", "candidate_only": True})
    manifest = {
        "analysis_geometry_binding": binding, "analysis_geometry_binding_current": binding,
        "analysis_geometry_drift": False,
        "analysis_projection_outputs": {"navigation": [{
            "ref": ref, "sha256": hashlib.sha256((root / ref).read_bytes()).hexdigest(), "status": "ready",
        }]},
    }
    _write(root, "outputs/layers/layer_preparation_manifest.json", manifest)
    subject = build_analysis_subject(root)
    assert subject.dependencies["navigation"]["status"] == "current_sources"
    assert subject.dependencies["architecture"]["status"] == "stale_or_unverified"
    _write(root, ref, {"status": "ready", "old_projection_changed": True})
    assert build_analysis_subject(root).dependencies["navigation"]["status"] == "stale_or_unverified"


def test_source_reference_cannot_escape_selected_workspace(tmp_path):
    _, root, _ = _fixture(tmp_path)
    secret = tmp_path / "private-source.gpx"
    secret.write_text("not a workspace source")
    _write(root, "outputs/gpx_speed_filter_report.json", {"primary": {"output_path": str(secret)}})
    source = build_analysis_subject(root).sources["golden_geometry"]
    assert source.status == "invalid" and source.ref is None and source.sha256 is None


def test_interrupted_rebuild_never_exposes_an_adopted_schedule(tmp_path):
    client, root, _, _ = _rebuilt(tmp_path)
    _write(root, "reviews/contextual_permission_rebuild_transactions/pending.json", {"interrupted": True})
    value = client.get(SUBJECT).json()
    assert value["schedule_status"] == "rebuild_required"
    assert value["mission_day_estimates"] == []
    assert value["issues"] == ["baseline_or_projection_write_in_doubt"]


def test_candidate_graph_change_is_stale_even_when_recorded_golden_is_unchanged(tmp_path):
    client, root, _, _ = _rebuilt(tmp_path)
    before = client.get(SUBJECT).json()
    path = root / "outputs/compiled_mission_graph.reviewed.json"
    graph = json.loads(path.read_text())
    graph["changed_after_review"] = True
    path.write_text(json.dumps(graph))
    value = client.get(SUBJECT).json()
    assert value["schedule_status"] == "stale"
    assert value["issues"] == ["reviewed_candidate_source_changed"]
    assert value["sources"]["golden_geometry"] == before["sources"]["golden_geometry"]
    assert value["mission_day_estimates"] == []
