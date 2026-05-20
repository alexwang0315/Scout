import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_departure_gate_resolution
from pretrip_departure_gate import (
    DepartureGateStatus,
    build_chilai_departure_gate_manifest,
)
from pretrip_departure_gate_resolution import (
    DepartureGateResolutionAction,
    DepartureGateResolutionLog,
    append_departure_gate_resolution,
    apply_departure_gate_resolutions,
    build_chilai_warning_resolution_log,
    build_departure_gate_resolution_record,
    load_departure_gate_resolution_log,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_warning_resolutions_legally_move_chilai_gate_from_hold_to_pass():
    gate = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    resolution_log = build_chilai_warning_resolution_log(
        gate,
        reviewer_alias="reviewer:alex",
        decided_at="2026-05-18T09:00:00+08:00",
    )

    resolved = apply_departure_gate_resolutions(
        gate,
        resolution_log,
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:05:00+08:00",
    )

    assert gate.status == DepartureGateStatus.HOLD
    assert resolution_log.counts.resolution_count == gate.counts.warning_count
    assert resolution_log.counts.warning_override_count == gate.counts.warning_count
    assert resolution_log.counts.blocker_resolution_attempt_count == 0
    assert resolved.status == DepartureGateStatus.PASSED
    assert resolved.approval.approval_granted is True
    assert resolved.approval.approved_by == "reviewer:alex"
    assert resolved.approval.approved_at == "2026-05-18T09:05:00+08:00"
    assert resolved.approval.final_mission_graph_generation_allowed is True
    assert resolved.boundary.final_mission_graph_generation_allowed is True
    assert resolved.boundary.runtime_handoff_allowed is False
    assert resolved.counts.warning_count == 0
    assert resolved.counts.unresolved_warning_count == 0
    assert resolved.counts.blocker_count == 0
    assert resolved.counts.override_reason_count == gate.counts.warning_count
    assert resolved.counts.runtime_write_count == 0
    assert resolved.counts.safety_call_count == 0
    assert resolved.counts.phase2_writeback_count == 0
    assert resolved.approval.unresolved_warnings == []
    assert resolved.approval.blockers == []
    assert len(resolved.approval.override_reasons) == gate.counts.warning_count


def test_partial_warning_resolution_keeps_gate_on_hold():
    gate = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    partial_log = build_chilai_warning_resolution_log(
        gate,
        reviewer_alias="reviewer:alex",
        decided_at="2026-05-18T09:00:00+08:00",
        finding_ids=[gate.findings[0].finding_id],
    )

    resolved = apply_departure_gate_resolutions(
        gate,
        partial_log,
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:05:00+08:00",
    )

    assert resolved.status == DepartureGateStatus.HOLD
    assert resolved.approval.approval_granted is False
    assert resolved.approval.final_mission_graph_generation_allowed is False
    assert resolved.counts.warning_count == gate.counts.warning_count - 1
    assert resolved.counts.unresolved_warning_count == gate.counts.warning_count - 1


def test_hard_blocker_cannot_be_overridden_by_resolution_log(tmp_path):
    project_root = _copy_project_fixture(tmp_path)
    retreat_path = project_root / "candidates" / "retreat_routes.json"
    retreats = json.loads(retreat_path.read_text(encoding="utf-8"))
    retreats[0]["review_state"] = "needs_human_review"
    retreat_path.write_text(json.dumps(retreats, indent=2, sort_keys=True) + "\n")
    blocked_gate = build_chilai_departure_gate_manifest(project_root)
    blocker = next(finding for finding in blocked_gate.findings if finding.severity == "blocker")

    with pytest.raises(ValueError, match="cannot resolve blocker"):
        build_departure_gate_resolution_record(
            blocked_gate,
            blocker,
            action=DepartureGateResolutionAction.WARNING_OVERRIDE,
            reason="Trip leader accepts this risk.",
            reviewer_alias="reviewer:alex",
            decided_at="2026-05-18T09:00:00+08:00",
        )

    warning_log = build_chilai_warning_resolution_log(
        blocked_gate,
        reviewer_alias="reviewer:alex",
        decided_at="2026-05-18T09:00:00+08:00",
    )
    resolved = apply_departure_gate_resolutions(
        blocked_gate,
        warning_log,
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:05:00+08:00",
    )

    assert resolved.status == DepartureGateStatus.BLOCKED
    assert resolved.approval.approval_granted is False
    assert resolved.approval.final_mission_graph_generation_allowed is False
    assert resolved.counts.blocker_count == 1
    assert resolved.counts.hard_blocker_count == 1


def test_resolution_records_require_reason_and_reject_runtime_or_raw_fragments():
    gate = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    finding = gate.findings[0]

    with pytest.raises(ValidationError):
        build_departure_gate_resolution_record(
            gate,
            finding,
            action=DepartureGateResolutionAction.WARNING_OVERRIDE,
            reason="",
            reviewer_alias="reviewer:alex",
            decided_at="2026-05-18T09:00:00+08:00",
        )

    with pytest.raises(ValidationError, match="forbidden departure gate resolution fragment"):
        build_departure_gate_resolution_record(
            gate,
            finding,
            action=DepartureGateResolutionAction.WARNING_OVERRIDE,
            reason="See /safety/route-progress before departure.",
            reviewer_alias="reviewer:alex",
            decided_at="2026-05-18T09:00:00+08:00",
        )

    with pytest.raises(ValidationError, match="forbidden departure gate resolution fragment"):
        build_departure_gate_resolution_record(
            gate,
            finding,
            action=DepartureGateResolutionAction.WARNING_OVERRIDE,
            reason="<trkpt lat='24.1' lon='121.2'/>",
            reviewer_alias="reviewer:alex",
            decided_at="2026-05-18T09:00:00+08:00",
        )


def test_append_resolution_store_writes_only_workspace_log(tmp_path):
    workspace_root = _copy_project_fixture(tmp_path)
    gate = build_chilai_departure_gate_manifest(workspace_root)
    finding = gate.findings[0]
    before = _fixture_hashes(FIXTURE_ROOT)

    log = append_departure_gate_resolution(
        workspace_root,
        gate,
        finding_id=finding.finding_id,
        action=DepartureGateResolutionAction.WARNING_OVERRIDE,
        reason="Admin reviewed the planning warning and accepts it for this departure gate.",
        reviewer_alias="reviewer:alex",
        decided_at="2026-05-18T09:00:00+08:00",
    )
    loaded = load_departure_gate_resolution_log(
        workspace_root / "reviews" / "departure_gate_resolution_log.json"
    )

    assert loaded == log
    assert log.boundary.local_workspace_only is True
    assert log.boundary.repo_fixture_write_allowed is False
    assert log.boundary.runtime_mutation_allowed is False
    assert log.boundary.phase1_runtime_mutation_allowed is False
    assert log.boundary.phase2_writeback_allowed is False
    assert log.counts.resolution_count == 1
    assert _fixture_hashes(FIXTURE_ROOT) == before

    with pytest.raises(ValueError, match="duplicate finding_id"):
        append_departure_gate_resolution(
            workspace_root,
            gate,
            finding_id=finding.finding_id,
            action=DepartureGateResolutionAction.WARNING_OVERRIDE,
            reason="Duplicate override should be rejected.",
            reviewer_alias="reviewer:alex",
            decided_at="2026-05-18T09:01:00+08:00",
        )


def test_resolution_module_has_no_runtime_dependencies():
    source = inspect.getsource(pretrip_departure_gate_resolution)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
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
