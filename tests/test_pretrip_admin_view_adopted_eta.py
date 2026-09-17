"""Dashboard projection after the real Permission Save/Accept/Rebuild path."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from pretrip_admin_view import _planned_eta_summary, build_pretrip_admin_view
from test_scout_analysis_subject import _sources
from test_scout_reference_gpx_workbench import (
    DASHBOARD, PROJECT_ID, _accept, _files, _fixture, _generate, _save,
)
from test_scout_reference_gpx_reconstruction import CP_REF, PRIMARY_REF


FIXTURE = Path(__file__).parent / "fixtures/pretrip/projects/chilai_nanhua_day1"


def _complete_view_fixture(tmp_path):
    client, root, _ = _fixture(tmp_path)
    project = json.loads((root / "project.json").read_text())
    # The Permission fixture owns its source, candidate and receipt files.
    # Supply only its absent read-only Dashboard surfaces before the replay.
    for source in FIXTURE.rglob("*"):
        if source.relative_to(FIXTURE).as_posix() == "reviews/review_decision_log.json":
            continue
        target = root / source.relative_to(FIXTURE)
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    project = {**json.loads((FIXTURE / "project.json").read_text()), **project}
    # Keep the legacy Dashboard review schema separate from the new
    # Permission append-only list at reviews/review_decision_log.json.
    project["review_decision_log_ref"] = "reviews/dashboard_review_decision_log.json"
    shutil.copyfile(FIXTURE / "reviews/review_decision_log.json",
                    root / project["review_decision_log_ref"])
    (root / "project.json").write_text(json.dumps(project))
    cp_path = root / CP_REF
    cp = json.loads(cp_path.read_text())
    cp.update(project_id=PROJECT_ID, event_count=len(cp["events"]),
              source_gpx={"ref": PRIMARY_REF},
              boundary={"candidate_only": True, "runtime_safety_truth": False})
    cp_path.write_text(json.dumps(cp))
    projection_path = root / project["admin_projection_ref"]
    projection = {
        **json.loads((FIXTURE / "outputs/admin_projection.json").read_text()),
        **json.loads(projection_path.read_text()),
        "project_id": PROJECT_ID,
    }
    projection_path.write_text(json.dumps(projection))
    _sources(root)
    return client, root


def test_full_and_compact_project_survive_real_adopted_eta_rebuild(tmp_path):
    client, root = _complete_view_fixture(tmp_path)
    endpoint = f"/admin/pretrip/projects/{PROJECT_ID}"
    build_pretrip_admin_view(PROJECT_ID, project_root=root)
    before_rebuild = client.get(endpoint, params={"compact": "1"})
    assert before_rebuild.status_code == 200, before_rebuild.text
    draft = _generate(client)
    saved = _save(client, draft)
    assert saved.status_code == 200, saved.text
    accepted = _accept(client, draft, saved.json())
    assert accepted.status_code == 200, accepted.text
    admission = client.get(DASHBOARD).json()["rebuild"]
    rebuilt = client.post(f"{DASHBOARD}/rebuilds", json={
        "expected_reviewed_baseline_sha256": accepted.json()["reviewed_baseline_sha256"],
        "expected_admission_snapshot_sha256": admission["canonical_snapshot_sha256"],
        "expected_evaluator_version": admission["evaluator_version"],
        "idempotency_key": "project-view-rebuild-001", "explicit_confirmation": True,
    })
    assert rebuilt.status_code == 200, rebuilt.text
    raw_eta = json.loads((root / rebuilt.json()["planned_eta_ref"]).read_text())
    assert "assumption" not in raw_eta and "estimates" not in raw_eta
    assert raw_eta["retired_legacy_timing"]["status"] == "superseded"
    before = _files(root)
    subject = client.get(f"{endpoint}/analysis-subject").json()
    assert subject["schedule_status"] == "adopted", subject
    for compact in (False, True, True):
        response = client.get(endpoint, params={"compact": str(int(compact))})
        assert response.status_code == 200, response.text
        view = response.json()
        eta = view["eta"]
        assert eta["authoritative_collection"] == "mission_day_estimates"
        assert eta["mission_day_estimates"] == subject["mission_day_estimates"]
        assert eta["mission_day_estimates"] == raw_eta["mission_day_estimates"]
        assert [day["eta"]["observed_elapsed_minutes"] for day in eta["mission_day_estimates"]] == [600, 360]
        assert eta["mission_day_estimates"][0]["reference_replay"]["departure_clock"] == "06:00:00"
        assert eta["estimate_count"] == 2
        assert eta["estimates"] == []
        assert eta["planned_start_time"] is None
        assert eta["target_eta"] is None
        assert eta["turn_back_checkpoint_eta"] is None
        assert eta["reviewed_baseline_sha256"] == raw_eta["reviewed_baseline_sha256"]
        assert eta["legacy_timing_status"] == "superseded"
        assert eta["candidate_only"] is True
        assert eta["runtime_safety_truth"] is False
        assert eta["departure_approval_granted"] is False
        assert len(view["checkpoints"]) > 0
        section = next(item for item in view["tabs"]["pre_trip_planning"]["sections"] if item["id"] == "eta")
        assert section["counts"]["estimate_count"] == 2
    assert _files(root) == before


def test_legacy_eta_view_keeps_existing_dates_and_estimates():
    raw = json.loads((FIXTURE / "outputs/planned_eta.json").read_text())
    view = build_pretrip_admin_view("chilai_nanhua_day1")
    eta = view["eta"]
    assert eta["authoritative_collection"] == "estimates"
    assert eta["estimates"] == raw["estimates"]
    assert eta["estimate_count"] == 4
    assert eta["mission_day_estimates"] == []
    assert eta["planned_start_time"] == raw["assumption"]["planned_start_time"]
    assert eta["target_eta"] == "2013-10-08T18:28:50+08:00"


@pytest.mark.parametrize("days", [[], [{"mission_day_id": "D1", "eta": None}]])
def test_day_bound_eta_never_falls_back_to_retired_dates_or_estimates(days):
    eta = _planned_eta_summary({
        "plan_id": "eta.reviewed", "authoritative_collection": "mission_day_estimates",
        "mission_day_estimates": days,
        "assumption": {"planned_start_time": "2000-01-01T06:00:00Z", "target_eta": "old"},
        "estimates": [{"estimated_minutes": 999}],
        "retired_legacy_timing": {"values": {"assumption": {"target_eta": "old"}}},
    }, "outputs/planned_eta.json")
    assert eta["planned_start_time"] is None
    assert eta["target_eta"] is None
    assert eta["estimates"] == []
    assert eta["mission_day_estimates"] == days
    assert eta["estimate_count"] == len(days)


def test_invalid_day_collection_is_not_projected_as_a_valid_empty_plan():
    with pytest.raises(ValueError, match="mission_day_estimates"):
        _planned_eta_summary({"plan_id": "eta.invalid", "mission_day_estimates": {}}, "outputs/planned_eta.json")
