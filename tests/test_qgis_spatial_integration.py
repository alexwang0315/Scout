from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from admin_api import create_admin_app
from qgis_spatial_backend import (
    QgisSpatialBackend,
    QgisSpatialBackendConfig,
)
from qgis_spatial_contracts import (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    QgisBackendAvailability,
    SpatialAnalysisRequest,
    SpatialArtifact,
    SpatialArtifactStatus,
    SpatialEvidenceReviewRequest,
    SpatialWorkflowState,
)


class FakeTransport:
    def __init__(self, *, status_payload: Any = None, error: BaseException | None = None) -> None:
        self.status_payload = status_payload
        self.error = error
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        self.get_calls.append(url)
        if self.error is not None:
            raise self.error
        return self.status_payload


class FakeRuntimeAudit:
    def __init__(self) -> None:
        self.background_jobs: list[dict[str, Any]] = []
        self.workspace_writes: list[dict[str, Any]] = []

    def record_background_job(self, **values: Any) -> None:
        self.background_jobs.append(values)

    def record_workspace_io(self, **values: Any) -> None:
        self.workspace_writes.append(values)

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        self.post_calls.append((url, payload))
        if self.error is not None:
            raise self.error
        return self.status_payload


def _fixed_now() -> datetime:
    return datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _workspace(root: Path, project_id: str = "qgis_demo") -> tuple[Path, dict[str, Any]]:
    project_root = root / project_id
    output_root = project_root / "outputs"
    output_root.mkdir(parents=True)
    checkpoints = [
        {"checkpoint_id": "cp.start", "lat": 24.0506539, "lon": 121.2152310},
        {"checkpoint_id": "cp.001", "lat": 24.0525377, "lon": 121.2181223},
        {"checkpoint_id": "cp.002", "lat": 24.0495210, "lon": 121.2202911},
        {"checkpoint_id": "cp.finish", "lat": 24.0468285, "lon": 121.2232233},
    ]
    (output_root / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps({"checkpoints": checkpoints}, ensure_ascii=False),
        encoding="utf-8",
    )
    project = {
        "project_id": project_id,
        "route_name": "QGIS fixture route",
        "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
    }
    (project_root / "project.json").write_text(
        json.dumps(project, ensure_ascii=False),
        encoding="utf-8",
    )
    return project_root, project


def test_qgis_backend_disabled_and_not_configured_are_typed() -> None:
    disabled = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=False),
        now_factory=_fixed_now,
    ).status(project_id="qgis_demo")
    assert disabled.availability is QgisBackendAvailability.DISABLED
    assert disabled.enabled is False
    assert disabled.boundary.candidate_only is True
    assert disabled.boundary.runtime_safety_truth is False

    not_configured = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=True, worker_url=None),
        now_factory=_fixed_now,
    ).status(project_id="qgis_demo")
    assert not_configured.availability is QgisBackendAvailability.NOT_CONFIGURED
    assert not_configured.errors[0].code.value == "BACKEND_NOT_CONFIGURED"


def test_qgis_backend_rejects_non_local_worker_endpoint() -> None:
    transport = FakeTransport(status_payload={"qgis_version": "3.44"})
    status = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="https://qgis.example.invalid",
            worker_token="test-worker-token-0123456789abcdef",
        ),
        transport=transport,
        now_factory=_fixed_now,
    ).status(project_id="qgis_demo")
    assert status.availability is QgisBackendAvailability.ERROR
    assert status.endpoint_configured is True
    assert not transport.get_calls


def test_qgis_backend_status_handles_unavailable_timeout_and_malformed_payload() -> None:
    timeout_status = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token="test-worker-token-0123456789abcdef",
        ),
        transport=FakeTransport(error=TimeoutError("slow qgis")),
        now_factory=_fixed_now,
    ).status(project_id="qgis_demo")
    assert timeout_status.availability is QgisBackendAvailability.UNAVAILABLE
    assert timeout_status.errors[0].code.value == "MCP_UNAVAILABLE"

    malformed_status = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token="test-worker-token-0123456789abcdef",
        ),
        transport=FakeTransport(status_payload=["not", "a", "status"]),
        now_factory=_fixed_now,
    ).status(project_id="qgis_demo")
    assert malformed_status.availability is QgisBackendAvailability.DEGRADED
    assert malformed_status.backend_degraded is True


def test_qgis_backend_status_honors_explicit_unavailable_flags_over_version_strings() -> None:
    status = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token="test-worker-token-0123456789abcdef",
        ),
        transport=FakeTransport(
            status_payload={
                "availability": "degraded",
                "mcp_reachable": True,
                "qgis_application_available": False,
                "plugin_bridge_available": False,
                "qgis_version": "unavailable",
                "qgis_mcp_plugin_version": "0.4.8",
            }
        ),
        now_factory=_fixed_now,
    ).status(project_id="qgis_demo")
    assert status.availability is QgisBackendAvailability.DEGRADED
    assert status.qgis_application_available is False
    assert status.plugin_bridge_available is False


def test_qgis_capability_catalog_is_allowlisted_and_blocks_dangerous_tools() -> None:
    catalog = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=False),
        now_factory=_fixed_now,
    ).capabilities()
    assert TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID in catalog.workflow_allowlist
    assert TERRAIN_FEATURE_STACK_WORKFLOW_ID in catalog.workflow_allowlist
    assert "qgis.processing.slope" in catalog.tool_allowlist
    assert "qgis.processing.grass.geomorphon" in catalog.tool_allowlist
    assert "arbitrary_python" in catalog.blocked_capabilities
    assert "shell" in catalog.blocked_capabilities
    assert all(capability.dangerous is False for capability in catalog.capabilities)


def test_qgis_artifact_schema_enforces_candidate_invariants() -> None:
    base = {
        "artifact_id": "artifact.demo",
        "artifact_type": "maplibre_geojson",
        "workflow_id": TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
        "workflow_version": "0.1",
        "workflow_run_id": "run.demo",
        "created_at": "2026-08-20T12:00:00Z",
        "processing_algorithm": "fixture",
    }
    artifact = SpatialArtifact(**base)
    assert artifact.crs == "UNKNOWN"
    assert artifact.provenance == {}
    assert artifact.runtime_safety_truth is False
    with pytest.raises(ValidationError):
        SpatialArtifact(**{**base, "runtime_safety_truth": True})
    with pytest.raises(ValidationError):
        SpatialArtifact(**{**base, "candidate_only": False})


def test_qgis_fixture_workflow_persists_candidate_artifacts(tmp_path: Path) -> None:
    project_root, project = _workspace(tmp_path)
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=True, fixture_mode=True),
        now_factory=_fixed_now,
    )
    run = backend.start_workflow(
        project_id="qgis_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(project_id="qgis_demo"),
    )
    assert run.state is SpatialWorkflowState.COMPLETED
    assert run.processing_status == "completed"
    assert run.render_status == "completed"
    assert run.visual_review_status == "pending"
    assert run.candidate_only is True
    assert run.runtime_safety_truth is False
    assert run.operational is False
    assert run.maplibre_geojson["features"]
    assert {feature["properties"]["kind"] for feature in run.maplibre_geojson["features"]} == {
        "qgis_candidate_route",
        "qgis_slope_candidate",
    }
    assert all(artifact.candidate_only for artifact in run.artifacts)
    assert all(not artifact.runtime_safety_truth for artifact in run.artifacts)
    persisted = backend.get_run(
        project_root=project_root,
        workflow_run_id=run.workflow_run_id,
    )
    assert persisted.workflow_run_id == run.workflow_run_id
    render_artifact = run.render_artifacts[0]
    artifact, render_path = backend.artifact_path(
        project_root=project_root,
        workflow_run_id=run.workflow_run_id,
        artifact_id=render_artifact.artifact_id,
    )
    assert artifact.media_type == "image/svg+xml"
    assert "synthetic / non-runtime / candidate-only" in render_path.read_text(encoding="utf-8")


def test_qgis_fixture_terrain_feature_stack_never_fabricates_rasters(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=True, fixture_mode=True),
        now_factory=_fixed_now,
    )
    run = backend.start_workflow(
        project_id="qgis_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
        ),
    )

    assert run.state is SpatialWorkflowState.COMPLETED
    assert run.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
    assert run.processing_status == "completed"
    assert run.visual_review_status == "pending"
    assert run.candidate_only is True
    assert run.runtime_safety_truth is False
    artifact_types = {artifact.artifact_type for artifact in run.artifacts}
    assert "terrain_feature_manifest" in artifact_types
    assert not {
        "slope_raster",
        "aspect_raster",
        "geomorphon_raster",
        "flow_accumulation_raster",
    }.intersection(artifact_types)
    manifest = next(
        artifact
        for artifact in run.artifacts
        if artifact.artifact_type == "terrain_feature_manifest"
    )
    assert manifest.fixture is True
    assert manifest.synthetic is True
    manifest_payload = json.loads(
        (project_root / manifest.artifact_ref).read_text(encoding="utf-8")
    )
    assert manifest_payload["produced_rasters"] == []
    assert manifest_payload["runtime_safety_truth"] is False


def test_qgis_review_promotes_only_evidence_status_and_preserves_authority_boundary(
    tmp_path: Path,
) -> None:
    project_root, project = _workspace(tmp_path)
    audit = FakeRuntimeAudit()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=True, fixture_mode=True),
        runtime_audit=audit,
        now_factory=_fixed_now,
    )
    run = backend.start_workflow(
        project_id="qgis_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(project_id="qgis_demo"),
    )
    reviewed = backend.review_evidence(
        project_root=project_root,
        workflow_run_id=run.workflow_run_id,
        request=SpatialEvidenceReviewRequest(
            reviewed_by="dashboard_operator",
            review_note="Visual binding inspected; no terrain truth conclusion.",
        ),
    )

    assert reviewed.state is SpatialWorkflowState.COMPLETED
    assert reviewed.processing_status == "completed"
    assert reviewed.render_status == "completed"
    assert reviewed.machine_review_status == "not_started"
    assert reviewed.visual_review_status == "completed"
    assert reviewed.human_review_status == "completed"
    assert all(
        artifact.status is SpatialArtifactStatus.REVIEWED_EVIDENCE
        for artifact in [*reviewed.artifacts, *reviewed.render_artifacts]
    )
    assert all(
        artifact.candidate_only
        and not artifact.runtime_safety_truth
        and not artifact.operational
        for artifact in [*reviewed.artifacts, *reviewed.render_artifacts]
    )
    assert reviewed.candidate_only is True
    assert reviewed.runtime_safety_truth is False
    assert reviewed.operational is False
    assert reviewed.steps[-1].status.value == "completed"
    assert reviewed.steps[-1].label == "Evidence review"
    assert reviewed.audit_trail[-1]["event"] == "evidence_review_recorded"
    assert len(audit.background_jobs) == 1

    persisted = backend.get_run(
        project_root=project_root,
        workflow_run_id=run.workflow_run_id,
    )
    assert persisted.human_review_status == "completed"
    assert len(audit.background_jobs) == 1


def test_qgis_fixture_workflow_failure_and_cancellation_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "qgis_demo"
    project_root.mkdir()
    project = {"project_id": "qgis_demo", "route_name": "missing geometry"}
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(enabled=True, fixture_mode=True),
        now_factory=_fixed_now,
    )
    run = backend.start_workflow(
        project_id="qgis_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(project_id="qgis_demo"),
    )
    assert run.state is SpatialWorkflowState.FAILED
    assert run.error is not None
    assert run.error.code.value == "INVALID_INPUT"
    cancelled = backend.cancel_workflow(
        project_root=project_root,
        workflow_run_id=run.workflow_run_id,
    )
    assert cancelled.state is SpatialWorkflowState.FAILED


def test_qgis_api_status_workflow_artifacts_and_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _workspace(tmp_path)
    monkeypatch.setenv("SCOUT_QGIS_ENABLED", "true")
    monkeypatch.setenv("SCOUT_QGIS_FIXTURE_MODE", "true")
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=tmp_path,
            runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-audit",
        )
    )

    status_response = client.get("/admin/pretrip/projects/qgis_demo/spatial/qgis/status")
    assert status_response.status_code == 200
    assert status_response.json()["availability"] == "available"
    assert status_response.json()["fixture_mode"] is True
    assert status_response.headers["x-scout-runtime-safety-truth"] == "false"

    capabilities_response = client.get("/admin/pretrip/projects/qgis_demo/spatial/qgis/capabilities")
    assert capabilities_response.status_code == 200
    assert "terrain_context_preview.v1" in capabilities_response.json()["workflow_allowlist"]

    invalid_response = client.post(
        "/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows",
        json={
            "workflow_id": TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
            "project_id": "qgis_demo",
            "corridor_m": 5001,
        },
    )
    assert invalid_response.status_code == 422

    workflow_response = client.post(
        "/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows",
        json={
            "workflow_id": TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
            "project_id": "qgis_demo",
            "corridor_m": 250,
            "requested_by": "dashboard_operator",
        },
    )
    assert workflow_response.status_code == 201
    run = workflow_response.json()
    assert run["state"] == "completed"
    assert run["candidate_only"] is True
    assert run["runtime_safety_truth"] is False
    assert run["processing_status"] == "completed"
    assert run["visual_review_status"] == "pending"

    run_id = run["workflow_run_id"]
    state_response = client.get(f"/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows/{run_id}")
    assert state_response.status_code == 200
    assert state_response.json()["workflow_run_id"] == run_id

    artifacts_response = client.get(
        f"/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows/{run_id}/artifacts"
    )
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()["artifacts"]
    render_artifact = next(item for item in artifacts if item["artifact_type"] == "qgis_render_preview")
    assert render_artifact["fixture"] is True
    assert render_artifact["runtime_safety_truth"] is False

    metadata_response = client.get(
        f"/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows/{run_id}/artifacts/{render_artifact['artifact_id']}"
    )
    assert metadata_response.status_code == 200
    assert metadata_response.json()["candidate_only"] is True

    missing_artifact_response = client.get(
        f"/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows/{run_id}/artifacts/missing-artifact"
    )
    assert missing_artifact_response.status_code == 404

    render_response = client.get(
        f"/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows/{run_id}/artifacts/{render_artifact['artifact_id']}/render"
    )
    assert render_response.status_code == 200
    assert render_response.headers["content-type"].startswith("image/svg+xml")
    assert render_response.headers["x-scout-runtime-safety-truth"] == "false"
    assert b"QGIS Visual Review Fixture" in render_response.content

    review_response = client.post(
        f"/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows/{run_id}/review",
        json={
            "reviewed_by": "dashboard_operator",
            "review_note": "Visual evidence inspected; candidate boundary retained.",
        },
    )
    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["processing_status"] == "completed"
    assert reviewed["render_status"] == "completed"
    assert reviewed["human_review_status"] == "completed"
    assert reviewed["candidate_only"] is True
    assert reviewed["runtime_safety_truth"] is False
    assert reviewed["operational"] is False
    assert all(
        item["status"] == "reviewed_evidence"
        for item in [*reviewed["artifacts"], *reviewed["render_artifacts"]]
    )


def test_qgis_api_disabled_does_not_require_worker_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _workspace(tmp_path)
    monkeypatch.delenv("SCOUT_QGIS_ENABLED", raising=False)
    monkeypatch.delenv("SCOUT_QGIS_FIXTURE_MODE", raising=False)
    monkeypatch.delenv("SCOUT_QGIS_WORKER_URL", raising=False)
    client = TestClient(
        create_admin_app(
            pretrip_workspace_root=tmp_path,
            runtime_audit_root=tmp_path.parent / f"{tmp_path.name}-audit",
        )
    )
    response = client.get("/admin/pretrip/projects/qgis_demo/spatial/qgis/status")
    assert response.status_code == 200
    assert response.json()["availability"] == "disabled"
    assert response.json()["boundary"]["runtime_safety_truth"] is False

    workflow_response = client.post(
        "/admin/pretrip/projects/qgis_demo/spatial/qgis/workflows",
        json={"project_id": "qgis_demo", "workflow_id": TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID},
    )
    assert workflow_response.status_code == 201
    assert workflow_response.json()["state"] == "failed"
    assert workflow_response.json()["error"]["code"] == "BACKEND_NOT_CONFIGURED"
    assert workflow_response.json()["runtime_safety_truth"] is False


def test_dashboard_qgis_panel_contract_is_backend_only() -> None:
    html = Path("docs/admin/scout-dashboard-v0.1.html").read_text(encoding="utf-8")
    assert 'src="/admin/scout-maplibre-evidence.js"' in html
    assert 'data-qgis-spatial-panel="true"' in html
    assert 'data-qgis-maplibre-preview="true"' in html
    assert 'data-scout-maplibre-evidence="qgis"' in html
    assert "qgisSpatialEvidenceFeatureCollection" in html
    assert "adapter.createEvidenceFeature" in html
    assert 'const layerId = kind === "qgis_candidate_route"' in html
    assert '? "qgis-route"' in html
    assert ': kind === "qgis_terrain_feature_sample"' in html
    assert '? "qgis-terrain-samples"' in html
    assert 'kind === "qgis_candidate_ridge_line"' in html
    assert '"qgis-ridge-lines"' in html
    assert 'kind === "qgis_candidate_valley_line"' in html
    assert '"qgis-valley-lines"' in html
    assert 'kind === "qgis_candidate_stream_network"' in html
    assert '"qgis-stream-network"' in html
    assert 'id: "scout-qgis-ridge-candidate"' in html
    assert 'id: "scout-qgis-valley-candidate"' in html
    assert 'id: "scout-qgis-stream-network-candidate"' in html
    assert 'data-qgis-layer-toggle="ridges"' in html
    assert 'data-qgis-layer-toggle="valleys"' in html
    assert 'data-qgis-layer-toggle="streams"' in html
    assert "scout-qgis-route-preview" not in html
    assert "scout-qgis-slope-preview" not in html
    assert "qgisSpatialBasePath()" in html
    assert 'data-qgis-review-evidence="true"' in html
    assert 'data-qgis-visual-review="not-started"' in html
    assert 'data-qgis-visual-review="render-unavailable"' in html
    assert "QGIS integration is disabled. No workflow or rendered evidence artifact exists." in html
    assert "Visual review cannot begin." in html
    assert 'data-qgis-terrain-features="true"' in html
    assert 'startQgisSpatialWorkflow("terrain_feature_stack.v1")' in html
    assert "GRASS capability discovery" in html
    assert "Multiscale geomorphons generated" in html
    assert "Ridge and valley candidates vectorized" in html
    assert "Stream-network candidate extracted" in html
    assert ".qgis-analysis-panel .navigation-reading-head" in html
    assert "flex-wrap: wrap" in html
    assert "/spatial/qgis" in html
    assert "candidate_only=true" in html
    assert "runtime_safety_truth=false" in html
    assert "SCOUT_QGIS_WORKER_URL" not in html
    assert "execute arbitrary Python" not in html
