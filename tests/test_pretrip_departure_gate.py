import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_departure_gate
from pretrip_departure_gate import (
    DepartureApprovalRecord,
    DepartureGateStatus,
    PreTripDepartureGateManifest,
    build_chilai_departure_gate_manifest,
    load_departure_gate_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_builds_conservative_departure_gate_manifest_for_chilai_quick_review():
    first = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    second = build_chilai_departure_gate_manifest(ROOT)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")

    payload = first.model_dump(mode="json")
    assert payload["manifest_id"] == "departure_gate.chilai_nanhua_day1.quick_review.v0"
    assert payload["artifact_kind"] == "pretrip_departure_gate_manifest"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["planning_review_profile_ref"] == "quick_review.v0"
    assert payload["route_class"] == "deep_mountain_out_and_back"
    assert payload["trip_classification_zh"] == "深山原路折返"
    assert payload["status"] == "hold"
    assert payload["approval"]["approval_granted"] is False
    assert payload["approval"]["final_mission_graph_generation_allowed"] is False
    assert payload["approval"]["runtime_handoff_allowed"] is False
    assert payload["counts"]["input_ref_count"] == 10
    assert payload["counts"]["warning_count"] >= 6
    assert payload["counts"]["blocker_count"] == 0
    assert payload["counts"]["runtime_write_count"] == 0
    assert payload["counts"]["safety_call_count"] == 0
    assert payload["counts"]["phase2_writeback_count"] == 0
    finding_ids = [finding["finding_id"] for finding in payload["findings"]]
    assert len(finding_ids) == len(set(finding_ids))


def test_departure_gate_refs_reviewed_package_graph_and_gate_inputs():
    manifest = build_chilai_departure_gate_manifest(FIXTURE_ROOT).model_dump(mode="json")
    refs = {ref["ref_key"]: ref for ref in manifest["input_refs"]}

    assert refs["reviewed_package_ref"]["ref"] == "outputs/pretrip_package.reviewed.json"
    assert refs["reviewed_package_ref"]["status"] == "reviewed"
    assert refs["compiled_mission_graph_reviewed_ref"]["ref"] == (
        "outputs/compiled_mission_graph.reviewed.json"
    )
    assert refs["compiled_mission_graph_reviewed_ref"]["summary"] == {
        "checkpoint_count": 11,
        "segment_count": 10,
    }
    assert refs["readiness_report_ref"]["summary"] == {
        "finding_count": 0,
        "status": "ready",
    }
    assert refs["retreat_routes_ref"]["artifact_kind"] == "retreat_routes"
    assert refs["planned_eta_ref"]["summary"]["plan_id"] == (
        "eta_plan.chilai_nanhua_day1.day1.v0"
    )
    for ref in refs.values():
        assert ref["exists"] is True
        assert len(ref["sha256"]) == 64
        assert (FIXTURE_ROOT / ref["ref"]).exists()


def test_departure_gate_keeps_reviewed_package_separate_from_departure_approval():
    manifest = build_chilai_departure_gate_manifest(FIXTURE_ROOT)

    assert manifest.boundary.reviewed_package_is_not_departure_approval is True
    assert manifest.boundary.departure_approval_is_explicit is True
    assert manifest.boundary.final_mission_graph_generation_allowed is False
    assert manifest.boundary.runtime_handoff_allowed is False
    assert manifest.boundary.phase1_runtime_mutation_allowed is False
    assert manifest.boundary.safety_api_calls_allowed is False
    assert manifest.boundary.phase2_writeback_allowed is False

    messages = [finding.message for finding in manifest.findings]
    assert "Weather/daylight evidence is placeholder-only" in " ".join(messages)
    assert all(
        finding.blocker_override_allowed is True
        for finding in manifest.findings
        if finding.severity.value == "warning"
    )
    assert all(finding.chinese_explanation for finding in manifest.findings)


def test_departure_gate_blocks_when_return_to_entry_retreat_is_not_accepted(tmp_path):
    project_root = _copy_project_fixture(tmp_path)
    retreat_path = project_root / "candidates" / "retreat_routes.json"
    retreats = json.loads(retreat_path.read_text(encoding="utf-8"))
    retreats[0]["review_state"] = "needs_human_review"
    retreat_path.write_text(json.dumps(retreats, indent=2, sort_keys=True) + "\n")

    manifest = build_chilai_departure_gate_manifest(project_root)

    assert manifest.status == DepartureGateStatus.BLOCKED
    assert manifest.approval.approval_granted is False
    assert manifest.counts.blocker_count == 1
    assert manifest.counts.hard_blocker_count == 1
    assert manifest.approval.blockers[0].rule_id == (
        "no_retreat_policy_for_required_route"
    )
    assert manifest.approval.blockers[0].blocker_override_allowed is False


def test_departure_gate_manifest_round_trips_and_rejects_invalid_approval_state(tmp_path):
    manifest = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    output_path = tmp_path / "departure_gate.json"
    output_path.write_text(manifest.to_json(), encoding="utf-8")

    loaded = load_departure_gate_manifest(output_path)

    assert loaded == manifest

    payload = manifest.model_dump(mode="json")
    payload["approval"]["approval_granted"] = True
    with pytest.raises(ValidationError, match="approval_granted requires passed"):
        PreTripDepartureGateManifest.model_validate(payload)

    approval_payload = payload["approval"] | {
        "approval_granted": False,
        "final_mission_graph_generation_allowed": True,
    }
    with pytest.raises(ValidationError, match="final MissionGraph generation"):
        DepartureApprovalRecord.model_validate(approval_payload)


def test_departure_gate_has_no_runtime_side_effects_or_raw_payload_fragments():
    before = _fixture_hashes(FIXTURE_ROOT)
    manifest = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    after = _fixture_hashes(FIXTURE_ROOT)

    assert after == before
    serialized = manifest.to_json()
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        '"coordinates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
    ]:
        assert fragment not in serialized

    source = inspect.getsource(pretrip_departure_gate)
    assert "requests." not in source
    assert "httpx." not in source
    assert "Phase1IncidentBridge(" not in source


def _copy_project_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _fixture_hashes(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
