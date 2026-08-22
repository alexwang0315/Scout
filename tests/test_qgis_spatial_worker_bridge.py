from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qgis_spatial_backend import (
    QgisMcpHttpTransport,
    QgisSpatialBackend,
    QgisSpatialBackendConfig,
)
from qgis_spatial_contracts import (
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    QgisBackendAvailability,
    SpatialAnalysisRequest,
    SpatialWorkflowState,
)


def _test_access_value() -> str:
    return "".join(("test-scout-", "backend-worker-", "0123456789"))


def _fixed_now() -> datetime:
    return datetime(2026, 8, 21, 4, 30, tzinfo=timezone.utc)


def _workspace(root: Path) -> tuple[Path, dict[str, Any], Path]:
    project_root = root / "qgis_worker_demo"
    (project_root / "outputs").mkdir(parents=True)
    checkpoints = [
        {"lat": 24.05, "lon": 121.21},
        {"lat": 24.04, "lon": 121.22},
    ]
    (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps({"checkpoints": checkpoints}),
        encoding="utf-8",
    )
    project = {
        "project_id": "qgis_worker_demo",
        "route_name": "QGIS worker demo",
        "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
    }
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    dem = root / "source-dem.grd"
    dem.write_bytes(b"source-dem")
    summary = {
        "summary_id": "dtm_coverage.qgis_worker_demo",
        "missing_grid_count": 0,
        "candidate_tiles": [
            {
                "tile_id": "demo-dem",
                "grid_uri": str(dem),
                "intersects_route_bbox": True,
                "resolution_x_m": 20.0,
                "resolution_y_m": 20.0,
            }
        ],
    }
    summary_path = project_root / "normalized" / "terrain" / "dtm_coverage_summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    return project_root, project, dem


def _worker_run(state: str) -> dict[str, Any]:
    base = {
        "schema_version": "scout_qgis_worker.v0_1",
        "worker_run_id": "qgis-worker-demo-run",
        "project_id": "qgis_worker_demo",
        "workflow_id": "terrain_context_preview.v1",
        "workflow_version": "0.1",
        "request_id": "request-worker-demo",
        "requested_by": "dashboard_operator",
        "state": state,
        "created_at": "2026-08-21T04:30:00Z",
        "started_at": "2026-08-21T04:30:00Z" if state != "queued" else None,
        "updated_at": "2026-08-21T04:30:01Z",
        "completed_at": "2026-08-21T04:30:01Z" if state == "completed" else None,
        "processing_status": "completed" if state == "completed" else state,
        "render_status": "completed" if state == "completed" else "pending",
        "visual_review_status": "pending",
        "human_review_status": "pending",
        "steps": [],
        "warnings": [],
        "error": None,
        "audit_trail": [{"event": f"workflow_{state}", "at": "2026-08-21T04:30:01Z"}],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "phase1_runtime_mutation_allowed": False,
            "safety_api_called": False,
            "browser_direct_mcp_allowed": False,
            "arbitrary_python_allowed": False,
            "shell_execution_allowed": False,
            "unrestricted_filesystem_allowed": False,
            "human_review_required": True,
            "safe_or_walkable": "not_determined",
        },
    }
    if state != "completed":
        return {**base, "result": None}
    slope = b"real-qgis-slope-raster"
    render = b"real-qgis-render-png"
    return {
        **base,
        "result": {
            "maplibre_geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[121.21, 24.05], [121.22, 24.04]],
                        },
                        "properties": {
                            "kind": "qgis_candidate_route",
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[121.2, 24.03], [121.23, 24.03], [121.23, 24.06], [121.2, 24.06], [121.2, 24.03]]],
                        },
                        "properties": {
                            "kind": "qgis_slope_candidate",
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                            "visualization_only": True,
                        },
                    },
                ],
                "properties": {"candidate_only": True, "runtime_safety_truth": False},
            },
            "artifacts": [
                {
                    "artifact_id": "qgis-worker-demo-run.slope",
                    "artifact_type": "slope_raster",
                    "relative_ref": "slope.tif",
                    "media_type": "image/tiff",
                    "sha256": hashlib.sha256(slope).hexdigest(),
                    "byte_count": len(slope),
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "visualization_only": False,
                    "adds_source_resolution": False,
                },
                {
                    "artifact_id": "qgis-worker-demo-run.render",
                    "artifact_type": "qgis_render_preview",
                    "relative_ref": "qgis_render_preview.png",
                    "media_type": "image/png",
                    "sha256": hashlib.sha256(render).hexdigest(),
                    "byte_count": len(render),
                    "width_px": 960,
                    "height_px": 540,
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "visualization_only": True,
                    "adds_source_resolution": False,
                },
            ],
            "qgis_version": "3.44.12",
            "qgis_mcp_plugin_version": "0.4.8",
            "crs": "EPSG:3826",
            "source_resolution": {"x_m": 20.0, "y_m": 20.0, "adds_source_resolution": False},
            "output_resolution": {"render_width_px": 960, "render_height_px": 540},
            "processing_algorithms": ["gdal:slope"],
            "processing_parameters": {"slope_band": 1, "slope_scale": 1.0},
            "warnings": ["execution evidence only"],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "adds_source_resolution": False,
        },
    }


class AsyncWorkerTransport:
    def __init__(self) -> None:
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[str] = []
        self.byte_calls: list[str] = []

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        self.get_calls.append(url)
        if url.endswith("/status"):
            return {
                "availability": "available",
                "mcp_reachable": True,
                "qgis_application_available": True,
                "plugin_bridge_available": True,
                "capabilities_discoverable": True,
                "qgis_version": "3.44.12",
                "qgis_mcp_plugin_version": "0.4.8",
            }
        if url.endswith("/workflows/qgis-worker-demo-run"):
            return _worker_run("completed")
        raise AssertionError(f"unexpected GET: {url}")

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        self.post_calls.append((url, payload))
        if url.endswith("/cancel"):
            return {**_worker_run("queued"), "state": "cancelled", "processing_status": "cancelled"}
        return _worker_run("queued")

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        self.byte_calls.append(url)
        if url.endswith("qgis-worker-demo-run.slope"):
            return b"real-qgis-slope-raster"
        if url.endswith("qgis-worker-demo-run.render"):
            return b"real-qgis-render-png"
        raise AssertionError(f"unexpected artifact: {url}")


_ROUTE_SAMPLE_BYTES = json.dumps(
    {
        "type": "FeatureCollection",
        "metadata": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "risk_score_applied": False,
        },
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [121.21, 24.05]},
                "properties": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "risk_score_applied": False,
                    "slope_degrees": 35.0,
                    "geomorphon_code": 3,
                    "geomorphon_label": "ridge",
                },
            }
        ],
    },
    separators=(",", ":"),
).encode("utf-8")


_TERRAIN_FEATURE_BYTES = {
    "slope_raster": b"grass-slope-raster",
    "aspect_raster": b"grass-aspect-raster",
    "geomorphon_raster": b"grass-geomorphon-raster",
    "flow_accumulation_raster": b"grass-flow-accumulation-raster",
    "terrain_feature_route_samples": _ROUTE_SAMPLE_BYTES,
    "terrain_feature_manifest": b'{"candidate_only":true}',
    "qgis_visual_context": b'{"rendered_feature":"grass_slope_candidate"}',
    "qgis_render_preview": b"real-grass-qgis-render-png",
}


def _terrain_feature_worker_run(state: str) -> dict[str, Any]:
    payload = _worker_run(state)
    payload["workflow_id"] = TERRAIN_FEATURE_STACK_WORKFLOW_ID
    if state != "completed":
        return payload
    artifact_files = {
        "slope_raster": "grass_slope.tif",
        "aspect_raster": "grass_aspect.tif",
        "geomorphon_raster": "grass_geomorphon_landforms.tif",
        "flow_accumulation_raster": "grass_flow_accumulation.tif",
        "terrain_feature_route_samples": "terrain_feature_route_samples.geojson",
        "terrain_feature_manifest": "terrain_feature_manifest.json",
        "qgis_visual_context": "qgis_visual_context.json",
        "qgis_render_preview": "qgis_render_preview.png",
    }
    artifact_media = {
        "slope_raster": "image/tiff",
        "aspect_raster": "image/tiff",
        "geomorphon_raster": "image/tiff",
        "flow_accumulation_raster": "image/tiff",
        "terrain_feature_route_samples": "application/geo+json",
        "terrain_feature_manifest": "application/json",
        "qgis_visual_context": "application/json",
        "qgis_render_preview": "image/png",
    }
    artifacts = []
    for artifact_type, raw in _TERRAIN_FEATURE_BYTES.items():
        artifact = {
            "artifact_id": f"qgis-worker-demo-run.{artifact_type}",
            "artifact_type": artifact_type,
            "relative_ref": artifact_files[artifact_type],
            "media_type": artifact_media[artifact_type],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_count": len(raw),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "visualization_only": artifact_type
            in {"qgis_visual_context", "qgis_render_preview"},
            "adds_source_resolution": False,
        }
        if artifact_type == "qgis_render_preview":
            artifact.update({"width_px": 960, "height_px": 540})
        artifacts.append(artifact)
    payload["result"] = {
        **payload["result"],
        "artifacts": artifacts,
        "processing_algorithms": [
            "grass:r.slope.aspect",
            "grass:r.geomorphon",
            "grass:r.watershed",
        ],
        "processing_parameters": {
            "geomorphon_search_cells": 10,
            "watershed_threshold_cells": 50,
        },
        "warnings": ["candidate terrain feature execution evidence only"],
    }
    return payload


class TerrainFeatureWorkerTransport(AsyncWorkerTransport):
    def get_json(self, url: str, *, timeout_s: float) -> Any:
        self.get_calls.append(url)
        if url.endswith("/status"):
            return {
                "availability": "available",
                "mcp_reachable": True,
                "qgis_application_available": True,
                "plugin_bridge_available": True,
                "capabilities_discoverable": True,
                "qgis_version": "3.44.12",
                "qgis_mcp_plugin_version": "0.4.9",
            }
        if url.endswith("/workflows/qgis-worker-demo-run"):
            return _terrain_feature_worker_run("completed")
        raise AssertionError(f"unexpected GET: {url}")

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        self.post_calls.append((url, payload))
        return _terrain_feature_worker_run("queued")

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        self.byte_calls.append(url)
        artifact_type = url.rsplit(".", 1)[-1]
        if artifact_type in _TERRAIN_FEATURE_BYTES:
            return _TERRAIN_FEATURE_BYTES[artifact_type]
        raise AssertionError(f"unexpected artifact: {url}")


def test_qgis_backend_requires_worker_token_before_network_call() -> None:
    transport = AsyncWorkerTransport()
    status = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=None,
        ),
        transport=transport,
        now_factory=_fixed_now,
    ).status(project_id="qgis_worker_demo")
    assert status.availability is QgisBackendAvailability.NOT_CONFIGURED
    assert status.errors[0].code.value == "BACKEND_NOT_CONFIGURED"
    assert not transport.get_calls


def test_qgis_backend_worker_flow_is_queued_polled_and_normalized(tmp_path: Path) -> None:
    project_root, project, dem = _workspace(tmp_path)
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            request_id="request-worker-demo",
        ),
    )
    assert queued.state is SpatialWorkflowState.QUEUED
    assert queued.backend_run_id == "qgis-worker-demo-run"
    submitted = transport.post_calls[0][1]
    assert submitted["dem_refs"] == [str(dem)]
    assert submitted["source_resolution"]["x_m"] == 20.0
    assert submitted["candidate_only"] is True
    assert submitted["runtime_safety_truth"] is False

    completed = backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert completed.state is SpatialWorkflowState.COMPLETED
    assert completed.processing_status == "completed"
    assert completed.render_status == "completed"
    assert completed.visual_review_status == "pending"
    assert completed.runtime_safety_truth is False
    assert completed.maplibre_geojson["features"]
    assert {artifact.artifact_type for artifact in completed.artifacts} == {
        "route_geometry",
        "slope_raster",
        "workflow_metadata",
    }
    assert completed.render_artifacts[0].artifact_type == "qgis_render_preview"
    assert completed.render_artifacts[0].fixture is False
    assert completed.render_artifacts[0].synthetic is False
    assert len(transport.byte_calls) == 2
    for artifact in [*completed.artifacts, *completed.render_artifacts]:
        assert artifact.candidate_only is True
        assert artifact.runtime_safety_truth is False
        assert artifact.operational is False


def test_qgis_backend_grass_feature_stack_is_hashed_and_normalized(
    tmp_path: Path,
) -> None:
    project_root, project, _ = _workspace(tmp_path)
    transport = TerrainFeatureWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(
            project_id="qgis_worker_demo",
            workflow_id=TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            request_id="request-worker-demo",
        ),
    )
    assert queued.state is SpatialWorkflowState.QUEUED
    assert transport.post_calls[0][0].endswith(
        "/workflows/terrain_feature_stack.v1"
    )
    assert transport.post_calls[0][1]["workflow_id"] == TERRAIN_FEATURE_STACK_WORKFLOW_ID

    completed = backend.get_run(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert completed.state is SpatialWorkflowState.COMPLETED
    assert completed.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
    assert completed.processing_status == "completed"
    assert completed.visual_review_status == "pending"
    assert len(transport.byte_calls) == len(_TERRAIN_FEATURE_BYTES)
    assert {artifact.artifact_type for artifact in completed.artifacts} == {
        "route_geometry",
        "slope_raster",
        "aspect_raster",
        "geomorphon_raster",
        "flow_accumulation_raster",
        "terrain_feature_route_samples",
        "terrain_feature_manifest",
        "qgis_visual_context",
        "workflow_metadata",
    }
    assert completed.render_artifacts[0].artifact_type == "qgis_render_preview"
    assert all(
        artifact.candidate_only
        and not artifact.runtime_safety_truth
        and not artifact.operational
        for artifact in [*completed.artifacts, *completed.render_artifacts]
    )
    assert all(
        (project_root / artifact.artifact_ref).is_file()
        for artifact in [*completed.artifacts, *completed.render_artifacts]
        if artifact.artifact_ref
    )


def test_qgis_backend_cancellation_is_forwarded_to_worker(tmp_path: Path) -> None:
    project_root, project, _ = _workspace(tmp_path)
    transport = AsyncWorkerTransport()
    backend = QgisSpatialBackend(
        config=QgisSpatialBackendConfig(
            enabled=True,
            worker_url="http://127.0.0.1:9876",
            worker_token=_test_access_value(),
        ),
        transport=transport,
        now_factory=_fixed_now,
    )
    queued = backend.start_workflow(
        project_id="qgis_worker_demo",
        project_root=project_root,
        project=project,
        request=SpatialAnalysisRequest(project_id="qgis_worker_demo", request_id="request-worker-demo"),
    )
    cancelled = backend.cancel_workflow(
        project_root=project_root,
        workflow_run_id=queued.workflow_run_id,
    )
    assert cancelled.state is SpatialWorkflowState.CANCELLED
    assert transport.post_calls[-1][0].endswith("/workflows/qgis-worker-demo-run/cancel")


def test_http_transport_attaches_bearer_token(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ok":true}'

    def fake_urlopen(request: Any, *, timeout: float) -> Response:
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("qgis_spatial_backend.urlopen", fake_urlopen)
    payload = QgisMcpHttpTransport(auth_token=_test_access_value()).get_json(
        "http://127.0.0.1:9876/status",
        timeout_s=2.5,
    )
    assert payload == {"ok": True}
    assert captured["authorization"] == f"Bearer {_test_access_value()}"
    assert captured["timeout"] == 2.5
