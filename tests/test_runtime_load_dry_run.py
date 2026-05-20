import hashlib
import inspect
import json
import shutil
from pathlib import Path
from textwrap import dedent

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
    write_runtime_activation_request_for_workspace,
)
from pretrip_runtime_artifact_resolution import (
    write_runtime_artifact_resolution_manifest_for_workspace,
)
from pretrip_runtime_export import write_runtime_export_bundle_for_workspace
from pretrip_runtime_handoff import build_runtime_handoff_manifest_from_final_graph
from runtime_load_dry_run import build_runtime_load_dry_run_report


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_runtime_load_dry_run_passes_without_live_session(tmp_path):
    workspace_root, export_root = _runtime_export_with_activation_request(tmp_path)

    report = build_runtime_load_dry_run_report(export_root)
    payload = report.model_dump(mode="json")

    assert payload["artifact_kind"] == "runtime_load_dry_run_report"
    assert payload["status"] == "dry_run_passed"
    assert payload["dry_run_passed"] is True
    assert payload["activation_performed"] is False
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["export_id"] == "runtime_export.chilai_nanhua_day1.quick_review.v0"
    assert payload["request_id"] == "runtime_activation_request.chilai_nanhua_day1.quick_review.v0"
    assert payload["route_source_ref"] == "artifact:gpx:chilai_nanhua_day1"
    assert payload["route_artifact_runtime_ref"] == "route_artifacts/chilai_nanhua_day1.gpx"
    assert payload["route_point_count"] == 2
    assert payload["mission_graph_index"] == {
        "checkpoint_count": 11,
        "segment_count": 10,
        "control_zone_count": 1,
        "recording_policy_count": 1,
        "first_checkpoint_id": "cp.start",
        "last_checkpoint_id": "cp.finish",
        "duplicate_id_count": 0,
        "segment_reference_error_count": 0,
    }
    assert payload["counts"] == {
        "required_file_count": 5,
        "present_file_count": 5,
        "missing_file_count": 0,
        "route_point_count": 2,
        "checkpoint_count": 11,
        "segment_count": 10,
        "control_zone_count": 1,
        "recording_policy_count": 1,
        "duplicate_id_count": 0,
        "segment_reference_error_count": 0,
        "mission_graph_runtime_index_count": 1,
        "blocker_count": 0,
        "safety_runtime_session_count": 0,
        "live_runtime_activation_count": 0,
        "safety_api_call_count": 0,
        "phase1_live_session_mutation_count": 0,
        "phase2_writeback_count": 0,
        "raw_payload_copy_count": 0,
    }
    assert payload["boundary"] == {
        "dry_run_only": True,
        "phase1_runtime_loader_check": True,
        "mission_graph_runtime_index_allowed": True,
        "live_runtime_activation_allowed": False,
        "safety_runtime_session_allowed": False,
        "phase1_live_session_mutation_allowed": False,
        "safety_api_calls_allowed": False,
        "phase2_writeback_allowed": False,
        "raw_payloads_embedded": False,
        "requires_explicit_final_activation": True,
        "notes": [
            "Runtime Load Dry Run / runtime 載入演練 validates loader inputs only.",
            "MissionGraphRuntime indexing is allowed for dry-run validation.",
            "SafetyRuntimeSession creation and live safety APIs remain closed.",
        ],
    }
    assert payload["findings"] == []
    serialized = report.to_json()
    assert str(workspace_root) not in serialized
    assert "/private/" not in serialized
    assert "<gpx" not in serialized


def test_runtime_load_dry_run_blocks_missing_activation_request(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    (export_root / "runtime_activation_request.json").unlink()

    report = build_runtime_load_dry_run_report(export_root)

    assert report.status == "dry_run_blocked"
    assert report.dry_run_passed is False
    assert report.counts.blocker_count == 1
    assert [finding.finding_id for finding in report.findings] == [
        "runtime_activation_request_missing"
    ]


def test_runtime_load_dry_run_blocks_tampered_request_preflight_hash(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    request_path = export_root / "runtime_activation_request.json"
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload["source"]["preflight_report_sha256"] = "0" * 64
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    report = build_runtime_load_dry_run_report(export_root)

    assert report.status == "dry_run_blocked"
    assert "runtime_activation_request_preflight_hash_mismatch" in {
        finding.finding_id for finding in report.findings
    }
    assert report.counts.safety_runtime_session_count == 0
    assert report.boundary.live_runtime_activation_allowed is False


def test_runtime_load_dry_run_blocks_route_artifact_regression(tmp_path):
    _, export_root = _runtime_export_with_activation_request(tmp_path)
    (export_root / "route_artifacts" / "chilai_nanhua_day1.gpx").unlink()

    report = build_runtime_load_dry_run_report(export_root)

    assert report.status == "dry_run_blocked"
    finding_ids = {finding.finding_id for finding in report.findings}
    assert "activation_preflight_not_ready" in finding_ids
    assert "route_artifact_missing" in finding_ids
    assert report.counts.route_point_count == 0


def test_runtime_load_dry_run_module_uses_no_live_runtime_session_or_safety_api():
    import runtime_load_dry_run

    source = inspect.getsource(runtime_load_dry_run)

    assert "MissionGraphRuntime(" in source
    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "SafetyRuntimeSession(" not in source
    assert "/safety/" not in source


def _runtime_export_with_activation_request(tmp_path: Path) -> tuple[Path, Path]:
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
    route_path.write_text(_tiny_gpx(), encoding="utf-8")
    write_runtime_artifact_resolution_manifest_for_workspace(
        workspace_root,
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        sha256=_sha256_file(route_path),
        resolved=True,
    )
    preflight = build_runtime_activation_preflight_report(export_root)
    write_runtime_activation_request_for_workspace(
        workspace_root,
        preflight,
        request_id="runtime_activation_request.chilai_nanhua_day1.quick_review.v0",
        requested_by="reviewer:alex",
        requested_at="2026-05-18T09:30:00+08:00",
        request_reason="Admin requests Phase 1 to load this reviewed MissionGraph.",
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
