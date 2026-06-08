import hashlib
import inspect
import json
import shutil
from pathlib import Path
from textwrap import dedent

import pytest
from pydantic import ValidationError

import pretrip_runtime_artifact_resolution
import replay_runner
from pretrip_departure_gate import build_chilai_departure_gate_manifest
from pretrip_departure_gate_resolution import (
    apply_departure_gate_resolutions,
    build_chilai_warning_resolution_log,
)
from pretrip_final_mission_graph import build_chilai_final_mission_graph_artifact
from pretrip_runtime_artifact_resolution import (
    DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME,
    RuntimeArtifactResolutionManifest,
    build_runtime_artifact_resolution_manifest,
    load_runtime_artifact_resolution_manifest,
    resolve_runtime_route_source,
    write_runtime_artifact_resolution_manifest_for_workspace,
)
from pretrip_runtime_export import (
    build_runtime_export_bundle_manifest,
    write_runtime_export_bundle_for_workspace,
)
from pretrip_runtime_handoff import build_runtime_handoff_manifest_from_final_graph
from replay_runner import _resolve_route_source
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_builds_runtime_artifact_resolution_manifest_without_route_payload_copy():
    _, final_graph, handoff = _approved_chain()
    runtime_export = build_runtime_export_bundle_manifest(
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    )

    manifest = build_runtime_artifact_resolution_manifest(
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        resolved=False,
    )
    payload = manifest.model_dump(mode="json")

    assert payload["manifest_id"] == (
        "runtime_artifact_resolution.runtime_export.chilai_nanhua_day1.quick_review.v0"
    )
    assert payload["artifact_kind"] == "runtime_artifact_resolution_manifest"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["export_id"] == runtime_export.export_id
    assert payload["mission_graph_version"] == final_graph.mission_graph_version
    assert payload["mission_graph_sha256"] == final_graph.final_mission_graph_sha256
    assert payload["route_source_ref"] == "artifact:gpx:chilai_nanhua_day1"
    assert payload["resolutions"] == [
        {
            "artifact_ref": "artifact:gpx:chilai_nanhua_day1",
            "artifact_kind": "gpx_route",
            "runtime_ref": "route_artifacts/chilai_nanhua_day1.gpx",
            "runtime_path_basis": "relative_to_resolution_manifest",
            "sha256": None,
            "required": True,
            "resolved": False,
        }
    ]
    assert payload["counts"] == {
        "artifact_resolution_count": 1,
        "required_resolution_count": 1,
        "resolved_count": 0,
        "missing_count": 1,
        "raw_payload_copy_count": 0,
        "safety_api_call_count": 0,
        "phase1_live_session_mutation_count": 0,
        "phase2_writeback_count": 0,
    }
    assert payload["boundary"] == {
        "metadata_only": True,
        "raw_payloads_embedded": False,
        "route_payload_copy_allowed": False,
        "planning_workspace_dependency_allowed": False,
        "live_runtime_activation_allowed": False,
        "phase1_live_session_mutation_allowed": False,
        "safety_api_calls_allowed": False,
        "phase2_writeback_allowed": False,
        "missing_required_artifact_blocks_activation": True,
        "route_source_policy": "symbolic_artifact_ref_resolved_by_runtime_target",
        "notes": [
            "Runtime Artifact Resolution / runtime artifact 解析 keeps the MissionGraph route_source symbolic.",
            "The runtime target must mount or provide the referenced route file before activation.",
            "This manifest records metadata only and does not copy raw route payloads.",
        ],
    }
    assert manifest.to_json().endswith("\n")


def test_runtime_artifact_resolution_rejects_raw_local_or_escaping_paths():
    _, final_graph, handoff = _approved_chain()
    runtime_export = build_runtime_export_bundle_manifest(
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    )
    manifest = build_runtime_artifact_resolution_manifest(
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        resolved=False,
    ).model_dump(mode="json")

    absolute_payload = json.loads(json.dumps(manifest))
    absolute_payload["resolutions"][0]["runtime_ref"] = "/Users/alexwang0315/downloads/raw.gpx"
    with pytest.raises(ValidationError, match="relative runtime artifact path"):
        RuntimeArtifactResolutionManifest.model_validate(absolute_payload)

    escaping_payload = json.loads(json.dumps(manifest))
    escaping_payload["resolutions"][0]["runtime_ref"] = "../route_artifacts/raw.gpx"
    with pytest.raises(ValidationError, match="relative runtime artifact path"):
        RuntimeArtifactResolutionManifest.model_validate(escaping_payload)

    raw_payload = json.loads(json.dumps(manifest))
    raw_payload["resolutions"][0]["runtime_ref"] = "route_artifacts/<gpx>"
    with pytest.raises(ValidationError, match="forbidden runtime artifact resolution fragment"):
        RuntimeArtifactResolutionManifest.model_validate(raw_payload)


def test_writer_is_workspace_only_immutable_and_replay_resolves_symbolic_route(tmp_path):
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

    written = write_runtime_artifact_resolution_manifest_for_workspace(
        workspace_root,
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        sha256=_sha256_file(route_path),
        resolved=True,
    )
    manifest_path = export_root / DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME
    loaded = load_runtime_artifact_resolution_manifest(manifest_path)
    mission_graph_path = export_root / "mission_graph.json"

    assert loaded == written
    assert manifest_path.exists()
    assert resolve_runtime_route_source(
        mission_graph_path,
        "artifact:gpx:chilai_nanhua_day1",
        manifest_path,
    ) == route_path
    assert _resolve_route_source(
        mission_graph_path,
        "artifact:gpx:chilai_nanhua_day1",
    ) == route_path
    assert len(load_gpx_route(route_path).points) == 2

    with pytest.raises(FileExistsError, match="already exists"):
        write_runtime_artifact_resolution_manifest_for_workspace(
            workspace_root,
            runtime_export,
            final_graph,
            runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
            sha256=_sha256_file(route_path),
            resolved=True,
        )

    with pytest.raises(ValueError, match="copied workspace"):
        write_runtime_artifact_resolution_manifest_for_workspace(
            FIXTURE_ROOT,
            runtime_export,
            final_graph,
            runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
            resolved=False,
        )


def test_resolver_blocks_unresolved_missing_or_hash_mismatched_route(tmp_path):
    workspace_root = _copy_project_fixture(tmp_path)
    _, final_graph, handoff = _approved_chain(workspace_root)
    runtime_export = write_runtime_export_bundle_for_workspace(
        workspace_root,
        final_graph,
        handoff,
        export_id="runtime_export.chilai_nanhua_day1.quick_review.v0",
    )
    export_root = workspace_root / "runtime_exports" / runtime_export.export_id
    mission_graph_path = export_root / "mission_graph.json"
    route_path = export_root / "route_artifacts" / "chilai_nanhua_day1.gpx"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(_tiny_gpx(), encoding="utf-8")

    unresolved_manifest = build_runtime_artifact_resolution_manifest(
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        resolved=False,
    )
    unresolved_path = export_root / "unresolved_runtime_artifact_resolution.json"
    unresolved_path.write_text(unresolved_manifest.to_json(), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="is not resolved"):
        resolve_runtime_route_source(
            mission_graph_path,
            "artifact:gpx:chilai_nanhua_day1",
            unresolved_path,
        )

    missing_manifest = build_runtime_artifact_resolution_manifest(
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/missing.gpx",
        resolved=True,
    )
    missing_path = export_root / "missing_runtime_artifact_resolution.json"
    missing_path.write_text(missing_manifest.to_json(), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="runtime route artifact missing"):
        resolve_runtime_route_source(
            mission_graph_path,
            "artifact:gpx:chilai_nanhua_day1",
            missing_path,
        )

    bad_hash_manifest = build_runtime_artifact_resolution_manifest(
        runtime_export,
        final_graph,
        runtime_ref="route_artifacts/chilai_nanhua_day1.gpx",
        sha256="0" * 64,
        resolved=True,
    )
    bad_hash_path = export_root / "bad_hash_runtime_artifact_resolution.json"
    bad_hash_path.write_text(bad_hash_manifest.to_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        resolve_runtime_route_source(
            mission_graph_path,
            "artifact:gpx:chilai_nanhua_day1",
            bad_hash_path,
        )

    with pytest.raises(FileNotFoundError, match="artifact resolution manifest"):
        resolve_runtime_route_source(
            mission_graph_path,
            "artifact:gpx:chilai_nanhua_day1",
            export_root / "does_not_exist.json",
        )


def test_runtime_artifact_resolution_module_has_no_live_runtime_dependencies():
    source = inspect.getsource(pretrip_runtime_artifact_resolution)
    replay_source = inspect.getsource(replay_runner)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "MissionGraphRuntime(" not in source
    assert "/safety/" not in source
    assert "from pretrip_runtime_artifact_resolution" not in replay_source


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
