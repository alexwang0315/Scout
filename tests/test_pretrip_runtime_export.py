import inspect
import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_runtime_export
from mission_graph import load_mission_graph
from pretrip_departure_gate import build_chilai_departure_gate_manifest
from pretrip_departure_gate_resolution import (
    apply_departure_gate_resolutions,
    build_chilai_warning_resolution_log,
)
from pretrip_final_mission_graph import build_chilai_final_mission_graph_artifact
from pretrip_runtime_export import (
    RuntimeExportBundleManifest,
    build_runtime_export_bundle_manifest,
    load_runtime_export_bundle_manifest,
    write_runtime_export_bundle_for_workspace,
)
from pretrip_runtime_handoff import build_runtime_handoff_manifest_from_final_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_builds_runtime_export_bundle_manifest_without_live_activation():
    passed_gate, final_graph, handoff = _approved_chain()

    bundle = build_runtime_export_bundle_manifest(
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    )
    payload = bundle.model_dump(mode="json")

    assert payload["export_id"] == "runtime_export.chilai_nanhua_day1.quick_review.v0"
    assert payload["artifact_kind"] == "pretrip_runtime_export_bundle"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "exported_not_activated"
    assert payload["profile_id"] == "quick_review.v0"
    assert payload["departure_approval_id"] == passed_gate.approval.approval_id
    assert payload["handoff_id"] == handoff.handoff_id
    assert payload["mission_graph_version"] == final_graph.mission_graph_version
    assert payload["mission_graph_sha256"] == final_graph.final_mission_graph_sha256
    assert payload["package_sha256"] == final_graph.source_package_ref.sha256
    assert payload["runtime_target"] == {
        "target_id": "runtime-node.scout-field-kit-01",
        "target_kind": "local_runtime_node",
        "target_profile": "phase1-field-runtime.v0",
    }
    assert payload["files"] == {
        "mission_graph": {
            "ref": "runtime_exports/runtime_export.chilai_nanhua_day1.quick_review.v0/mission_graph.json",
            "artifact_kind": "mission_graph",
            "sha256": final_graph.final_mission_graph_sha256,
            "write_required": True,
        },
        "runtime_handoff_manifest": {
            "ref": "runtime_exports/runtime_export.chilai_nanhua_day1.quick_review.v0/runtime_handoff_manifest.json",
            "artifact_kind": "runtime_handoff_manifest",
            "sha256": _sha256_json(handoff.model_dump(mode="json")),
            "write_required": True,
        },
    }
    assert payload["counts"] == {
        "runtime_file_write_count": 2,
        "live_runtime_activation_count": 0,
        "safety_api_call_count": 0,
        "phase1_live_session_mutation_count": 0,
        "phase2_writeback_count": 0,
        "raw_payload_copy_count": 0,
    }
    assert payload["boundary"] == {
        "runtime_file_write_allowed": True,
        "live_runtime_activation_allowed": False,
        "phase1_live_session_mutation_allowed": False,
        "safety_api_calls_allowed": False,
        "phase2_writeback_allowed": False,
        "planning_workspace_dependency_allowed": False,
        "raw_payloads_embedded": False,
        "route_source_resolution_policy": "runtime_target_must_resolve_artifact_refs",
        "notes": [
            "Runtime Export / runtime 匯出 writes immutable runtime input files only.",
            "Activation / 啟動現場 session is a separate Phase 1 runtime decision.",
            "No live safety endpoint is called by this exporter.",
        ],
    }
    assert bundle.to_json().endswith("\n")


def test_runtime_export_rejects_mismatched_handoff_or_raw_runtime_fragments():
    _, final_graph, handoff = _approved_chain()
    payload = handoff.model_dump(mode="json")
    payload["mission_graph"]["sha256"] = "c" * 64

    with pytest.raises(ValueError, match="MissionGraph hash"):
        build_runtime_export_bundle_manifest(
            final_graph,
            payload,
            export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
        )

    bundle = build_runtime_export_bundle_manifest(
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    ).model_dump(mode="json")
    bundle["files"]["mission_graph"]["ref"] = "/Users/alexwang0315/downloads/raw.gpx"

    with pytest.raises(ValidationError, match="forbidden runtime export fragment"):
        RuntimeExportBundleManifest.model_validate(bundle)


def test_runtime_export_writer_is_workspace_only_immutable_and_phase1_loadable(tmp_path):
    workspace_root = _copy_project_fixture(tmp_path)
    passed_gate, final_graph, handoff = _approved_chain(workspace_root)
    before = _fixture_hashes(FIXTURE_ROOT)

    written = write_runtime_export_bundle_for_workspace(
        workspace_root,
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    )
    export_root = workspace_root / "runtime_exports" / "runtime_export.chilai_nanhua_day1.quick_review.v0"
    mission_graph_path = export_root / "mission_graph.json"
    handoff_path = export_root / "runtime_handoff_manifest.json"
    manifest_path = export_root / "runtime_export_manifest.json"
    loaded = load_runtime_export_bundle_manifest(manifest_path)

    assert loaded == written
    assert mission_graph_path.exists()
    assert handoff_path.exists()
    assert manifest_path.exists()
    assert load_mission_graph(mission_graph_path).mission_id == final_graph.mission_graph_version
    assert json.loads(handoff_path.read_text(encoding="utf-8"))["handoff_id"] == handoff.handoff_id
    assert _fixture_hashes(FIXTURE_ROOT) == before

    with pytest.raises(FileExistsError, match="already exists"):
        write_runtime_export_bundle_for_workspace(
            workspace_root,
            final_graph,
            handoff,
            export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
        )

    with pytest.raises(ValueError, match="copied workspace"):
        write_runtime_export_bundle_for_workspace(
            FIXTURE_ROOT,
            final_graph,
            handoff,
            export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
        )


def test_runtime_export_module_has_no_live_runtime_dependencies():
    source = inspect.getsource(pretrip_runtime_export)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "/safety/" not in source


def _approved_chain(project_root: Path = FIXTURE_ROOT):
    passed_gate = _passed_gate(project_root)
    final_graph = build_chilai_final_mission_graph_artifact(project_root, passed_gate)
    handoff = build_runtime_handoff_manifest_from_final_graph(
        passed_gate,
        final_graph,
        handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:15:00+08:00",
        handoff_target=_runtime_target(),
        rollback_reference=_rollback_reference(),
    )
    return passed_gate, final_graph, handoff


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


def _sha256_json(payload: dict) -> str:
    import hashlib

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
