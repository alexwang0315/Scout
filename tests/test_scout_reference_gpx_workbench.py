"""Historical GPX reconstruction through real, isolated Dashboard API requests."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from test_scout_contextual_permission_workbench_api import PROJECT_ID, _client
from test_scout_reference_gpx_reconstruction import (
    CP_REF,
    PACE_REF,
    PRIMARY_REF,
    add_reference_sources,
)


PREFIX = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
DASHBOARD = f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
AUTHORING = {
    "mode": "reference_gpx",
    "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
    "reference_strategy": "historical_reconstruction",
}


def _fixture(tmp_path):
    client, store_root = _client(tmp_path, rich_reference=True)
    root = tmp_path / "workspace" / PROJECT_ID
    add_reference_sources(root)
    return client, root, store_root


def _files(root: Path):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def _generate(client):
    response = client.post(f"{PREFIX}/generate-draft", json=AUTHORING)
    assert response.status_code == 200, response.text
    return response.json()


def _save(client, draft):
    return client.post(f"{PREFIX}/candidates", json={
        "draft": draft, "expected_source_sha256": draft["source_sha256"],
        "idempotency_key": "reference-reconstruction-save-001",
        "explicit_confirmation": True,
    })


def _accept(client, draft, saved):
    requirements = draft["review_requirements"]
    return client.post(f"{PREFIX}/reviews/accept", json={
        "candidate_ref": saved["version_ref"],
        "candidate_sha256": saved["version_sha256"],
        "reviewer_alias": "isolated-fixture-reviewer",
        "reviewed_day_ids": requirements["required_reviewed_day_ids"],
        "acknowledged_uncertainty_ids": requirements["required_acknowledgment_uncertainty_ids"],
        "safety_handoff_acknowledged": requirements["safety_handoff_required"],
        "idempotency_key": "reference-reconstruction-accept-001",
        "explicit_confirmation": True,
    })


def test_reference_itinerary_has_bound_days_and_maps_without_new_endpoint_inputs(tmp_path):
    client, root, store = _fixture(tmp_path)
    before = _files(root)
    preview = client.post(f"{PREFIX}/preview", json=AUTHORING)
    assert preview.status_code == 200, preview.text
    draft = _generate(client)
    assert preview.json()["days"] == draft["days"]
    assert draft["proposal_strategy_id"] == "reference-gpx.historical-reconstruction"
    assert draft["proposal_summary"]["reconstructed_day_count"] == 2
    assert draft["proposal_summary"]["target_p75_minutes_per_day"] is None
    assert draft["proposal_summary"]["historical_checkpoint_count"] == 10
    assert draft["proposal_summary"]["historical_timed_checkpoint_count"] == 9
    assert draft["proposal_summary"]["historical_rest_stop_count"] == 1
    assert draft["day_end_inputs"] == []
    assert draft["day_end_input_contract_sha256"] is None
    assert [d["mission_day_id"] for d in draft["days"]] == ["D1", "D2"]
    # A real ten-hour historical day must survive the former eight-hour heuristic.
    first = draft["days"][0]
    assert first["eta_proposal"]["observed_elapsed_minutes"] == 600
    assert first["eta_proposal"]["segment_p75_sum_minutes"] is None
    assert first["reference_replay"]["departure_clock"] == "06:00:00"
    assert first["reference_replay"]["arrival_clock"] == "16:00:00"
    assert first["reference_replay"]["rest_stops"][0]["duration_minutes"] == 25
    for day in draft["days"]:
        proposal = day["primary_day_end_proposal"]
        assert proposal["selection_origin"] == "reference_evidence"
        assert proposal["reference_day_id"] == day["reference_replay"]["source_day_id"]
        assert proposal["selection_actor"] is None
        assert proposal["target"]["artifact"]["ref"] == PRIMARY_REF
    context_response = client.get(f"{PREFIX}/map-context")
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    assert context["sampling_policy"] == "reference_gpx_boundary_preserving_sample.v1"
    assert context["route_length_m"] < 3000  # never unrelated legacy fixture's 90 km axis
    for day in draft["reference_reconstruction"]["days"]:
        for kind in ("start", "end"):
            expected = {k: day[kind][k] for k in ("route_order_m", "lat", "lon")}
            assert expected in context["route_points"]
    assert _files(root) == before
    assert not store.exists()


def test_reference_candidate_can_be_accepted_and_rebuilt_with_history_preserved(tmp_path):
    client, root, store = _fixture(tmp_path)
    before_sources = {ref: (root / ref).read_bytes() for ref in (PRIMARY_REF, PACE_REF, CP_REF)}
    draft = _generate(client)
    saved_response = _save(client, draft)
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    assert saved["review_ready"] is True
    candidate = json.loads((root / saved["version_ref"]).read_text())
    assert candidate["promotion_gates"]["day_end_provenance_bound"] is True
    assert candidate["reference_reconstruction"] == draft["reference_reconstruction"]
    accepted = _accept(client, draft, saved)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    reviewed = json.loads((root / receipt["reviewed_baseline_ref"]).read_text())
    assert reviewed["reference_reconstruction"] == draft["reference_reconstruction"]
    assert reviewed["days"] == candidate["days"]
    admission = client.get(DASHBOARD).json()["rebuild"]
    assert admission["eligible"] is True, admission
    rebuilt = client.post(f"{DASHBOARD}/rebuilds", json={
        "expected_reviewed_baseline_sha256": receipt["reviewed_baseline_sha256"],
        "expected_admission_snapshot_sha256": admission["canonical_snapshot_sha256"],
        "expected_evaluator_version": admission["evaluator_version"],
        "idempotency_key": "reference-reconstruction-rebuild-001",
        "explicit_confirmation": True,
    })
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["rule_review_state"] == "pending_review_only"
    assert rebuilt.json()["runtime_safety_truth"] is False
    assert rebuilt.json()["active_runtime_session_updated"] is False
    assert rebuilt.json()["departure_approval_granted"] is False
    projection = client.get(DASHBOARD).json()
    nodes = [n for n in projection["remaining_plan"] if n["kind"] == "route_axis"]
    assert [n["baseline_duration_minutes"] for n in nodes] == [600, 360]
    assert all(n["adjustment_policy"] == "review_only" for n in nodes)
    assert projection["current_decision"]["decision"] == "ESCALATE"
    assert projection["authority"]["runtime_authorization_performed"] is False
    eta = json.loads((root / "outputs/planned_eta.json").read_text())
    assert eta["mission_day_estimates"][0]["reference_replay"] == draft["days"][0]["reference_replay"]
    assert all((root / ref).read_bytes() == content for ref, content in before_sources.items())
    assert not store.exists()


@pytest.mark.parametrize("field", ["cp_clock", "endpoint", "elapsed", "reference_origin"])
def test_forged_reference_proposal_is_rejected_before_candidate_write(tmp_path, field):
    client, root, _ = _fixture(tmp_path)
    draft = copy.deepcopy(_generate(client))
    day = draft["days"][0]
    if field == "cp_clock":
        day["reference_replay"]["checkpoint_windows"][0]["arrival_clock"] = "09:00:00"
    elif field == "endpoint":
        day["primary_day_end_proposal"]["target"]["route_order_m"] += 1
    elif field == "elapsed":
        day["eta_proposal"]["observed_elapsed_minutes"] = 480
    else:
        day["primary_day_end_proposal"]["reference_day_sha256"] = "0" * 64
    before = _files(root)
    rejected = _save(client, draft)
    assert rejected.status_code == 409, rejected.text
    assert "reference_reconstruction_mismatch" in rejected.text
    assert _files(root) == before


def test_explicit_reference_mode_never_falls_back_to_repartition_when_history_missing(tmp_path):
    client, _ = _client(tmp_path, rich_reference=True)
    response = client.post(f"{PREFIX}/generate-draft", json=AUTHORING)
    assert response.status_code == 409, response.text
    assert "reference_itinerary_unavailable" in response.text


def test_reference_source_change_after_save_blocks_accept_and_source_change_after_review_changes_snapshot(tmp_path):
    client, root, _ = _fixture(tmp_path)
    draft = _generate(client)
    saved = _save(client, draft).json()
    source = root / PRIMARY_REF
    original = source.read_bytes()
    source.write_bytes(original + b"\n")
    before = _files(root)
    rejected = _accept(client, draft, saved)
    assert rejected.status_code == 409, rejected.text
    assert _files(root) == before
    source.write_bytes(original)
    accepted = _accept(client, draft, saved)
    assert accepted.status_code == 200, accepted.text
    admission = client.get(DASHBOARD).json()["rebuild"]
    source.write_bytes(original + b"\n")
    changed = client.get(DASHBOARD).json()["rebuild"]
    assert changed["canonical_snapshot_sha256"] != admission["canonical_snapshot_sha256"]
    assert changed["eligible"] is False
