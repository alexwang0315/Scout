import hashlib
import inspect
import json
import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from pretrip_departure_gate import build_chilai_departure_gate_manifest
from pretrip_departure_gate_resolution import (
    apply_departure_gate_resolutions,
    build_chilai_warning_resolution_log,
)
from pretrip_final_mission_graph import build_chilai_final_mission_graph_artifact
from pretrip_runtime_activation_preflight import (
    build_runtime_activation_preflight_report,
)
from pretrip_runtime_activation_request import (
    RuntimeActivationRequest,
    build_runtime_activation_request,
    load_runtime_activation_request,
    write_runtime_activation_request_for_workspace,
)
from pretrip_runtime_artifact_resolution import (
    write_runtime_artifact_resolution_manifest_for_workspace,
)
from pretrip_runtime_export import write_runtime_export_bundle_for_workspace
from pretrip_runtime_handoff import build_runtime_handoff_manifest_from_final_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_activation_request_builds_from_ready_preflight_without_live_activation(tmp_path):
    workspace_root, export_root = _runtime_export_with_route(
        tmp_path,
        route_sha_mode="valid",
    )
    preflight = build_runtime_activation_preflight_report(export_root)

    request = build_runtime_activation_request(
        preflight,
        request_id="runtime_activation_request.chilai_nanhua_day1.quick_review.v0",
        requested_by="reviewer:alex",
        requested_at="2026-05-18T09:30:00+08:00",
        request_reason="Admin requests Phase 1 to load this reviewed MissionGraph.",
    )
    payload = request.model_dump(mode="json")

    assert payload["artifact_kind"] == "runtime_activation_request"
    assert payload["status"] == "requested_not_activated"
    assert payload["activation_requested"] is True
    assert payload["activation_performed"] is False
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["export_id"] == "runtime_export.chilai_nanhua_day1.quick_review.v0"
    assert payload["mission_graph_version"] == preflight.mission_graph_version
    assert payload["mission_graph_sha256"] == preflight.mission_graph_sha256
    assert payload["route_source_ref"] == "artifact:gpx:chilai_nanhua_day1"
    assert payload["route_artifact_runtime_ref"] == "route_artifacts/chilai_nanhua_day1.gpx"
    assert payload["route_point_count"] == 2
    assert payload["requested_by"] == "reviewer:alex"
    assert payload["requested_at"] == "2026-05-18T09:30:00+08:00"
    assert payload["source"] == {
        "preflight_report_id": preflight.report_id,
        "preflight_report_sha256": _sha256_json(preflight.model_dump(mode="json")),
        "preflight_status": "activation_ready",
        "mission_graph_ref": "runtime_exports/runtime_export.chilai_nanhua_day1.quick_review.v0/mission_graph.json",
        "runtime_handoff_manifest_ref": "runtime_exports/runtime_export.chilai_nanhua_day1.quick_review.v0/runtime_handoff_manifest.json",
        "runtime_export_manifest_ref": "runtime_exports/runtime_export.chilai_nanhua_day1.quick_review.v0/runtime_export_manifest.json",
        "runtime_artifact_resolution_manifest_ref": "runtime_exports/runtime_export.chilai_nanhua_day1.quick_review.v0/runtime_artifact_resolution_manifest.json",
    }
    assert payload["counts"] == {
        "preflight_blocker_count": 0,
        "runtime_activation_request_count": 1,
        "route_point_count": 2,
        "live_runtime_activation_count": 0,
        "safety_api_call_count": 0,
        "phase1_live_session_mutation_count": 0,
        "phase2_writeback_count": 0,
        "raw_payload_copy_count": 0,
    }
    assert payload["boundary"] == {
        "request_artifact_only": True,
        "requires_activation_ready_preflight": True,
        "phase4_runtime_load_allowed": False,
        "live_runtime_activation_allowed": False,
        "phase1_live_session_mutation_allowed": False,
        "safety_api_calls_allowed": False,
        "phase2_writeback_allowed": False,
        "raw_payloads_embedded": False,
        "requires_phase1_runtime_revalidation": True,
        "requires_runtime_operator_confirmation": True,
        "notes": [
            "Runtime Activation Request / runtime 啟動請求 records operator intent only.",
            "The request asks Phase 1 to load a reviewed MissionGraph after revalidation.",
            "This artifact does not start a live field session by itself.",
        ],
    }
    serialized = request.to_json()
    assert str(workspace_root) not in serialized
    assert "/private/" not in serialized
    assert "<gpx" not in serialized


def test_activation_request_rejects_blocked_preflight(tmp_path):
    _, export_root = _runtime_export_with_route(
        tmp_path,
        route_sha_mode="unresolved",
    )
    preflight = build_runtime_activation_preflight_report(export_root)

    with pytest.raises(ValueError, match="activation-ready preflight"):
        build_runtime_activation_request(
            preflight,
            request_id="runtime_activation_request.chilai_nanhua_day1.quick_review.v0",
            requested_by="reviewer:alex",
            requested_at="2026-05-18T09:30:00+08:00",
            request_reason="Admin requests Phase 1 to load this reviewed MissionGraph.",
        )


def test_activation_request_writer_is_workspace_only_and_immutable(tmp_path):
    workspace_root, export_root = _runtime_export_with_route(
        tmp_path,
        route_sha_mode="valid",
    )
    preflight = build_runtime_activation_preflight_report(export_root)

    written = write_runtime_activation_request_for_workspace(
        workspace_root,
        preflight,
        request_id="runtime_activation_request.chilai_nanhua_day1.quick_review.v0",
        requested_by="reviewer:alex",
        requested_at="2026-05-18T09:30:00+08:00",
        request_reason="Admin requests Phase 1 to load this reviewed MissionGraph.",
    )

    path = export_root / "runtime_activation_request.json"
    loaded = load_runtime_activation_request(path)
    assert loaded == written
    assert RuntimeActivationRequest.model_validate_json(path.read_text(encoding="utf-8")) == written

    with pytest.raises(FileExistsError, match="runtime activation request already exists"):
        write_runtime_activation_request_for_workspace(
            workspace_root,
            preflight,
            request_id="runtime_activation_request.chilai_nanhua_day1.quick_review.v0",
            requested_by="reviewer:alex",
            requested_at="2026-05-18T09:30:00+08:00",
            request_reason="Admin requests Phase 1 to load this reviewed MissionGraph.",
        )

    with pytest.raises(ValueError, match="copied workspace"):
        write_runtime_activation_request_for_workspace(
            FIXTURE_ROOT,
            preflight,
            request_id="runtime_activation_request.chilai_nanhua_day1.quick_review.v0",
            requested_by="reviewer:alex",
            requested_at="2026-05-18T09:30:00+08:00",
            request_reason="Admin requests Phase 1 to load this reviewed MissionGraph.",
        )


def test_activation_request_module_has_no_live_runtime_dependencies():
    import pretrip_runtime_activation_request

    source = inspect.getsource(pretrip_runtime_activation_request)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "SafetyRuntimeSession(" not in source
    assert "MissionGraphRuntime(" not in source
    assert "/safety/" not in source


def _runtime_export_with_route(
    tmp_path: Path,
    *,
    route_sha_mode: str,
) -> tuple[Path, Path]:
    workspace_root = _copy_project_fixture(tmp_path)
    _, final_graph, handoff = _approved_chain(workspace_root)
    runtime_export = write_runtime_export_bundle_for_workspace(
        workspace_root,
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    )
    export_root = workspace_root / "runtime_exports" / runtime_export.export_id
    route_path = export_root / "route_artifacts" / "chilai_nanhua_day1.gpx"
    route_path.parent.mkdir(parents=True)
    if route_sha_mode != "missing":
        route_path.write_text(_tiny_gpx(), encoding="utf-8")

    if route_sha_mode == "valid":
        sha256 = _sha256_file(route_path)
        resolved = True
    elif route_sha_mode == "missing":
        sha256 = None
        resolved = True
    elif route_sha_mode == "unresolved":
        sha256 = None
        resolved = False
    else:
        raise ValueError(route_sha_mode)

    write_runtime_artifact_resolution_manifest_for_workspace(
        workspace_root,
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        sha256=sha256,
        resolved=resolved,
    )
    return workspace_root, export_root


def _approved_chain(project_root: Path = FIXTURE_ROOT):
    passed_gate = _passed_gate(project_root)
    final_graph = build_chilai_final_mission_graph_artifact(project_root, passed_gate)
    handoff = build_runtime_handoff_manifest_from_final_graph(
        passed_gate,
        final_graph,
        handoff_id="handoff.chilai_nanhua_day1.quick_review.v0",
        approved_by="reviewer:alex",
        approved_at="2026-05-18T09:15:00+08:00",
        handoff_target={
            "target_id": "runtime-node.scout-field-kit-01",
            "target_kind": "local_runtime_node",
            "target_profile": "phase1-field-runtime.v0",
        },
        rollback_reference={
            "rollback_id": "rollback.chilai_nanhua_day1.previous",
            "previous_handoff_id": None,
            "previous_mission_graph_version": None,
            "rollback_policy": "Keep previous immutable handoff manifest if one exists.",
        },
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


def _copy_project_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def _tiny_gpx() -> str:
    return dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" creator="scout-test" xmlns="http://www.topografix.com/GPX/1/1">
          <trk>
            <name>tiny route</name>
            <trkseg>
              <trkpt lat="24.000000" lon="121.000000">
                <ele>1000</ele>
                <time>2026-05-08T00:00:00Z</time>
              </trkpt>
              <trkpt lat="24.000100" lon="121.000100">
                <ele>1001</ele>
                <time>2026-05-08T00:01:00Z</time>
              </trkpt>
            </trkseg>
          </trk>
        </gpx>
        """
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
