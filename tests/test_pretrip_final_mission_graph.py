import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_final_mission_graph
from mission_models import MissionGraph
from pretrip_departure_gate import build_chilai_departure_gate_manifest
from pretrip_departure_gate_resolution import (
    apply_departure_gate_resolutions,
    build_chilai_warning_resolution_log,
)
from pretrip_final_mission_graph import (
    FinalMissionGraphArtifact,
    build_chilai_final_mission_graph_artifact,
    load_final_mission_graph_artifact,
    write_final_mission_graph_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_builds_final_mission_graph_only_after_departure_gate_passes():
    passed_gate = _passed_gate()

    artifact = build_chilai_final_mission_graph_artifact(FIXTURE_ROOT, passed_gate)
    payload = artifact.model_dump(mode="json")

    assert payload["artifact_id"] == "final_mission_graph.chilai_nanhua_day1.quick_review.v0"
    assert payload["artifact_kind"] == "pretrip_final_mission_graph"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "finalized"
    assert payload["profile_id"] == "quick_review.v0"
    assert payload["departure_approval_id"] == passed_gate.approval.approval_id
    assert payload["approved_by"] == "reviewer:alex"
    assert payload["approved_at"] == "2026-05-18T09:05:00+08:00"
    assert payload["source_package_ref"]["ref"] == "outputs/pretrip_package.reviewed.json"
    assert payload["source_mission_graph_ref"]["ref"] == (
        "outputs/compiled_mission_graph.reviewed.json"
    )
    assert len(payload["source_package_ref"]["sha256"]) == 64
    assert len(payload["source_mission_graph_ref"]["sha256"]) == 64
    assert len(payload["final_mission_graph_sha256"]) == 64
    assert payload["counts"] == {
        "checkpoint_count": 11,
        "segment_count": 10,
        "diversion_point_count": 1,
        "unresolved_warning_count": 0,
        "blocker_count": 0,
        "runtime_write_count": 0,
        "safety_call_count": 0,
        "phase2_writeback_count": 0,
    }

    graph = MissionGraph.model_validate(payload["mission_graph"])
    assert graph.mission_id == payload["mission_graph_version"]
    assert graph.route_source == "artifact:gpx:chilai_nanhua_day1"
    assert len(graph.checkpoints) == 11
    assert len(graph.segments) == 10
    assert all(".gpx" not in checkpoint.source for checkpoint in graph.checkpoints)
    assert all("/Users/" not in checkpoint.source for checkpoint in graph.checkpoints)
    assert artifact.to_json().endswith("\n")


def test_final_mission_graph_rejects_hold_or_partial_departure_gate():
    hold_gate = build_chilai_departure_gate_manifest(FIXTURE_ROOT)

    with pytest.raises(ValueError, match="passed departure gate"):
        build_chilai_final_mission_graph_artifact(FIXTURE_ROOT, hold_gate)

    partial_log = build_chilai_warning_resolution_log(
        hold_gate,
        reviewer_alias="reviewer:alex",
        decided_at="2026-05-18T09:00:00+08:00",
        finding_ids=[hold_gate.findings[0].finding_id],
    )
    partial_gate = apply_departure_gate_resolutions(
        hold_gate,
        partial_log,
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:05:00+08:00",
    )

    with pytest.raises(ValueError, match="passed departure gate"):
        build_chilai_final_mission_graph_artifact(FIXTURE_ROOT, partial_gate)


def test_final_mission_graph_boundary_rejects_runtime_mutation_and_raw_sources():
    artifact = build_chilai_final_mission_graph_artifact(FIXTURE_ROOT, _passed_gate())
    payload = artifact.model_dump(mode="json")

    assert payload["boundary"] == {
        "immutable": True,
        "generated_after_departure_gate_passed": True,
        "planning_workspace_dependency_allowed": False,
        "runtime_handoff_required": True,
        "runtime_handoff_performed": False,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_calls_allowed": False,
        "phase2_writeback_allowed": False,
        "external_api_calls_made": False,
        "raw_payloads_embedded": False,
        "notes": [
            "Final MissionGraph / 最終任務圖 is generated only after Departure Gate passes.",
            "This artifact is not Runtime Handoff / 現場 runtime 交接 approval.",
            "No Phase 1 runtime state is mutated by this builder.",
        ],
    }

    serialized = artifact.to_json()
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        "catographydata",
        "PdrSample",
        "/Users/",
        ".gpx",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "raw_samples",
    ]:
        assert fragment not in serialized

    payload["boundary"]["phase1_runtime_mutation_allowed"] = True
    with pytest.raises(ValidationError):
        FinalMissionGraphArtifact.model_validate(payload)

    payload = artifact.model_dump(mode="json")
    payload["mission_graph"]["route_source"] = "/Users/alexwang0315/downloads/raw.gpx"
    with pytest.raises(ValidationError, match="forbidden final MissionGraph fragment"):
        FinalMissionGraphArtifact.model_validate(payload)


def test_final_mission_graph_writer_is_workspace_only_and_immutable(tmp_path):
    workspace_root = _copy_project_fixture(tmp_path)
    passed_gate = _passed_gate(workspace_root)
    before = _fixture_hashes(FIXTURE_ROOT)

    written = write_final_mission_graph_artifact(workspace_root, passed_gate)
    path = workspace_root / "outputs" / "final_mission_graph.json"
    loaded = load_final_mission_graph_artifact(path)

    assert loaded == written
    assert written.boundary.immutable is True
    assert path.exists()
    assert _fixture_hashes(FIXTURE_ROOT) == before

    with pytest.raises(FileExistsError, match="already exists"):
        write_final_mission_graph_artifact(workspace_root, passed_gate)

    with pytest.raises(ValueError, match="copied workspace"):
        write_final_mission_graph_artifact(FIXTURE_ROOT, _passed_gate())


def test_final_mission_graph_module_has_no_live_runtime_dependencies():
    source = inspect.getsource(pretrip_final_mission_graph)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "/safety/" not in source


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
