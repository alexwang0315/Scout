import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_runtime_handoff
from pretrip_departure_gate import build_chilai_departure_gate_manifest
from pretrip_departure_gate_resolution import (
    apply_departure_gate_resolutions,
    build_chilai_warning_resolution_log,
)
from pretrip_final_mission_graph import build_chilai_final_mission_graph_artifact
from pretrip_runtime_handoff import (
    DepartureApprovalRecord,
    RuntimeHandoffManifest,
    build_runtime_handoff_manifest,
    build_runtime_handoff_manifest_from_final_graph,
    load_runtime_handoff_manifest,
    write_runtime_handoff_manifest_for_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PACKAGE_HASH = "a" * 64
MISSION_GRAPH_HASH = "b" * 64


def test_builds_runtime_handoff_manifest_from_departure_approval_metadata_only():
    manifest = _build_manifest()
    payload = manifest.model_dump(mode="json")

    assert payload == {
        "handoff_id": "handoff.chilai_nanhua_day1.v1",
        "artifact_kind": "runtime_handoff_manifest",
        "profile_id": "guided_review.v0",
        "package": {
            "version": "pretrip.chilai_nanhua_day1.v1",
            "sha256": PACKAGE_HASH,
        },
        "mission_graph": {
            "version": "mission.chilai_nanhua_day1.v1",
            "sha256": MISSION_GRAPH_HASH,
        },
        "departure_approval_id": "departure_approval.chilai_nanhua_day1.v1",
        "approved_by": "reviewer:alex",
        "approved_at": "2026-05-18T08:30:00+08:00",
        "handoff_target": {
            "target_id": "runtime-node.scout-field-kit-01",
            "target_kind": "local_runtime_node",
            "target_profile": "phase1-field-runtime.v0",
        },
        "unresolved_warnings": [
            {
                "warning_id": "warning.water_source_uncertain",
                "severity": "warning",
                "summary": "Water source must be confirmed before the final ascent.",
                "runtime_eligible": True,
            }
        ],
        "override_reasons": [
            {
                "override_id": "override.daylight_margin",
                "reason": "Team carries headlamps and has an earlier turnaround time.",
                "approved_by": "reviewer:alex",
                "approved_at": "2026-05-18T08:25:00+08:00",
            }
        ],
        "rollback_reference": {
            "rollback_id": "rollback.chilai_nanhua_day1.previous",
            "previous_handoff_id": "handoff.chilai_nanhua_day1.v0",
            "previous_mission_graph_version": "mission.chilai_nanhua_day1.v0",
            "rollback_policy": "Revert to the previous immutable handoff manifest.",
        },
        "boundary": {
            "metadata_only": True,
            "planning_workspace_dependency_allowed": False,
            "phase1_safety_call_allowed": False,
            "live_runtime_mutation_allowed": False,
            "raw_payloads_embedded": False,
            "phase1_bridge_dependency_allowed": False,
        },
    }

    assert manifest.to_json() == json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def test_runtime_handoff_manifest_rejects_direct_safety_and_raw_payload_fragments():
    payload = _build_manifest().model_dump(mode="json")
    payload["handoff_target"]["target_id"] = "POST /safety/route-progress"

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        RuntimeHandoffManifest.model_validate(payload)

    payload = _build_manifest().model_dump(mode="json")
    payload["unresolved_warnings"][0]["summary"] = "<trkpt lat='24.1' lon='121.2'/>"

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        RuntimeHandoffManifest.model_validate(payload)

    payload = _build_manifest().model_dump(mode="json")
    payload["override_reasons"][0]["reason"] = 'raw GeoJSON {"coordinates": [121, 24]}'

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        RuntimeHandoffManifest.model_validate(payload)


def test_runtime_handoff_manifest_rejects_phase1_bridge_references():
    payload = _departure_approval_payload()
    payload["override_reasons"][0]["reason"] = "Use Phase1IncidentBridge after approval."

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        DepartureApprovalRecord.model_validate(payload)

    payload = _build_manifest().model_dump(mode="json")
    payload["rollback_reference"]["rollback_policy"] = (
        "Toggle SCOUT_PHASE2_INCIDENT_BRIDGE if needed."
    )

    with pytest.raises(ValidationError, match="forbidden runtime/raw payload fragment"):
        RuntimeHandoffManifest.model_validate(payload)


def test_runtime_handoff_manifest_requires_accepted_departure_approval_shape():
    payload = _departure_approval_payload()
    payload["status"] = "hold"

    with pytest.raises(ValidationError):
        build_runtime_handoff_manifest(
            handoff_id="handoff.chilai_nanhua_day1.v1",
            departure_approval=payload,
            mission_graph={
                "version": "mission.chilai_nanhua_day1.v1",
                "sha256": MISSION_GRAPH_HASH,
            },
            handoff_target={
                "target_id": "runtime-node.scout-field-kit-01",
                "target_kind": "local_runtime_node",
                "target_profile": "phase1-field-runtime.v0",
            },
            rollback_reference={
                "rollback_id": "rollback.chilai_nanhua_day1.previous",
                "rollback_policy": "Revert to the previous immutable handoff manifest.",
            },
        )


def test_builds_runtime_handoff_manifest_from_final_mission_graph():
    passed_gate = _passed_gate()
    final_graph = build_chilai_final_mission_graph_artifact(FIXTURE_ROOT, passed_gate)

    manifest = build_runtime_handoff_manifest_from_final_graph(
        passed_gate,
        final_graph,
        handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:15:00+08:00",
        handoff_target=_runtime_target(),
        rollback_reference=_rollback_reference(),
    )
    payload = manifest.model_dump(mode="json")

    assert payload["handoff_id"] == "handoff.chilai_nanhua_day1.quick_review.v0"
    assert payload["profile_id"] == "quick_review.v0"
    assert payload["package"] == {
        "version": "pretrip.chilai_nanhua_day1.v0:0.1.0",
        "sha256": final_graph.source_package_ref.sha256,
    }
    assert payload["mission_graph"] == {
        "version": final_graph.mission_graph_version,
        "sha256": final_graph.final_mission_graph_sha256,
    }
    assert payload["departure_approval_id"] == final_graph.departure_approval_id
    assert payload["approved_by"] == "reviewer:alex"
    assert payload["approved_at"] == "2026-05-18T09:15:00+08:00"
    assert payload["unresolved_warnings"] == []
    assert len(payload["override_reasons"]) == passed_gate.counts.override_reason_count
    assert payload["override_reasons"][0]["approved_by"] == "reviewer:alex"
    assert payload["override_reasons"][0]["approved_at"] == "2026-05-18T09:05:00+08:00"
    assert payload["boundary"] == {
        "metadata_only": True,
        "planning_workspace_dependency_allowed": False,
        "phase1_safety_call_allowed": False,
        "live_runtime_mutation_allowed": False,
        "raw_payloads_embedded": False,
        "phase1_bridge_dependency_allowed": False,
    }
    assert manifest.to_json().endswith("\n")


def test_runtime_handoff_from_final_graph_rejects_unapproved_or_raw_graph():
    passed_gate = _passed_gate()
    final_graph = _final_mission_graph().model_dump(mode="json")
    final_graph["mission_graph"]["route_source"] = "/Users/alexwang0315/downloads/raw.gpx"

    with pytest.raises(ValidationError, match="forbidden final MissionGraph fragment"):
        build_runtime_handoff_manifest_from_final_graph(
            passed_gate,
            final_graph,
            handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
            approved_by="reviewer:alex",
            approved_at="2026-05-18T09:15:00+08:00",
            handoff_target=_runtime_target(),
            rollback_reference=_rollback_reference(),
        )

    hold_gate = build_chilai_departure_gate_manifest(FIXTURE_ROOT)
    with pytest.raises(ValueError, match="passed departure gate"):
        build_runtime_handoff_manifest_from_final_graph(
            hold_gate,
            _final_mission_graph(),
            handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
            approved_by="reviewer:alex",
            approved_at="2026-05-18T09:15:00+08:00",
            handoff_target=_runtime_target(),
            rollback_reference=_rollback_reference(),
        )

    mismatched_gate = _passed_gate()
    mismatched_graph = _final_mission_graph().model_dump(mode="json")
    mismatched_graph["departure_approval_id"] = "departure_approval.other.resolved"
    with pytest.raises(ValueError, match="departure approval"):
        build_runtime_handoff_manifest_from_final_graph(
            mismatched_gate,
            mismatched_graph,
            handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
            approved_by="reviewer:alex",
            approved_at="2026-05-18T09:15:00+08:00",
            handoff_target=_runtime_target(),
            rollback_reference=_rollback_reference(),
        )


def test_runtime_handoff_writer_is_workspace_only_and_immutable(tmp_path):
    workspace_root = _copy_project_fixture(tmp_path)
    passed_gate = _passed_gate(workspace_root)
    final_graph = build_chilai_final_mission_graph_artifact(workspace_root, passed_gate)
    before = _fixture_hashes(FIXTURE_ROOT)

    written = write_runtime_handoff_manifest_for_workspace(
        workspace_root,
        passed_gate,
        final_graph,
        handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:15:00+08:00",
        handoff_target=_runtime_target(),
        rollback_reference=_rollback_reference(),
    )
    path = workspace_root / "outputs" / "runtime_handoff_manifest.json"
    loaded = load_runtime_handoff_manifest(path)

    assert loaded == written
    assert path.exists()
    assert _fixture_hashes(FIXTURE_ROOT) == before

    with pytest.raises(FileExistsError, match="already exists"):
        write_runtime_handoff_manifest_for_workspace(
            workspace_root,
            passed_gate,
            final_graph,
            handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
            approved_by="reviewer:alex",
            approved_at="2026-05-18T09:15:00+08:00",
            handoff_target=_runtime_target(),
            rollback_reference=_rollback_reference(),
        )

    with pytest.raises(ValueError, match="copied workspace"):
        write_runtime_handoff_manifest_for_workspace(
            FIXTURE_ROOT,
            _passed_gate(),
            _final_mission_graph(),
            handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
            approved_by="reviewer:alex",
            approved_at="2026-05-18T09:15:00+08:00",
            handoff_target=_runtime_target(),
            rollback_reference=_rollback_reference(),
        )


def test_runtime_handoff_module_has_no_live_runtime_dependencies():
    source = inspect.getsource(pretrip_runtime_handoff)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source


def _build_manifest() -> RuntimeHandoffManifest:
    return build_runtime_handoff_manifest(
        handoff_id="handoff.chilai_nanhua_day1.v1",
        departure_approval=_departure_approval_payload(),
        mission_graph={
            "version": "mission.chilai_nanhua_day1.v1",
            "sha256": MISSION_GRAPH_HASH,
        },
        handoff_target={
            "target_id": "runtime-node.scout-field-kit-01",
            "target_kind": "local_runtime_node",
            "target_profile": "phase1-field-runtime.v0",
        },
        rollback_reference={
            "rollback_id": "rollback.chilai_nanhua_day1.previous",
            "previous_handoff_id": "handoff.chilai_nanhua_day1.v0",
            "previous_mission_graph_version": "mission.chilai_nanhua_day1.v0",
            "rollback_policy": "Revert to the previous immutable handoff manifest.",
        },
    )


def _departure_approval_payload() -> dict:
    return {
        "approval_id": "departure_approval.chilai_nanhua_day1.v1",
        "status": "pass",
        "profile_id": "guided_review.v0",
        "approved_by": "reviewer:alex",
        "approved_at": "2026-05-18T08:30:00+08:00",
        "package": {
            "version": "pretrip.chilai_nanhua_day1.v1",
            "sha256": PACKAGE_HASH,
        },
        "unresolved_warnings": [
            {
                "warning_id": "warning.water_source_uncertain",
                "severity": "warning",
                "summary": "Water source must be confirmed before the final ascent.",
                "runtime_eligible": True,
            }
        ],
        "override_reasons": [
            {
                "override_id": "override.daylight_margin",
                "reason": "Team carries headlamps and has an earlier turnaround time.",
                "approved_by": "reviewer:alex",
                "approved_at": "2026-05-18T08:25:00+08:00",
            }
        ],
        "final_mission_graph_allowed": True,
    }


def _final_mission_graph():
    return build_chilai_final_mission_graph_artifact(FIXTURE_ROOT, _passed_gate())


def _passed_gate(project_root: Path = FIXTURE_ROOT):
    gate = build_chilai_departure_gate_manifest(project_root)
    resolution_log = build_chilai_warning_resolution_log(
        gate,
        reviewer_alias="reviewer:alex",
        decided_at="2026-05-18T09:00:00+08:00",
    )
    return apply_departure_gate_resolutions(
        gate,
        resolution_log,
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:05:00+08:00",
    )


def _runtime_target() -> dict:
    return {
        "target_id": "runtime-node.scout-field-kit-01",
        "target_kind": "local_runtime_node",
        "target_profile": "phase1-field-runtime.v0",
    }


def _rollback_reference() -> dict:
    return {
        "rollback_id": "rollback.chilai_nanhua_day1.previous",
        "previous_handoff_id": None,
        "previous_mission_graph_version": None,
        "rollback_policy": "Keep previous immutable handoff manifest if one exists.",
    }


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
