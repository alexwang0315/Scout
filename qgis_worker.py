from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import shutil
import struct
import threading
import time
import zlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from qgis_mcp_stdio import (
    QGIS_MCP_ALLOWED_ALGORITHMS,
    QGIS_MCP_ALLOWED_TOOLS,
    QGIS_MCP_FLOW_CHANNEL_CANDIDATE_EXPRESSION,
    QGIS_MCP_GEOMORPHON_RIDGE_CONSENSUS_EXPRESSION,
    QGIS_MCP_GEOMORPHON_VALLEY_CONSENSUS_EXPRESSION,
    QgisMcpClientConfig,
    QgisMcpError,
    QgisMcpStdioClient,
    QgisMcpTimeout,
    QgisMcpToolError,
    QgisMcpToolRejected,
    QgisMcpUnavailable,
)
from qgis_spatial_contracts import (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    QgisBackendAvailability,
    SpatialAnalysisError,
    SpatialAnalysisErrorCode,
    SpatialCapabilityCategory,
    SpatialWorkflowState,
    SpatialWorkflowStep,
    SpatialWorkflowStepStatus,
)
from qgis_worker_contracts import (
    QgisWorkerArtifact,
    QgisWorkerResult,
    QgisWorkerRun,
    QgisWorkerStatus,
    QgisWorkerWorkflowRequest,
)


_TERMINAL_STATES = {
    SpatialWorkflowState.COMPLETED,
    SpatialWorkflowState.FAILED,
    SpatialWorkflowState.CANCELLED,
}
_GRASS_TERRAIN_FEATURE_SCHEMAS = {
    "grass:r.slope.aspect": {
        "required_parameters": frozenset({"elevation", "slope", "aspect"}),
        "output_parameters": ("slope", "aspect"),
    },
    "grass:r.geomorphon": {
        "required_parameters": frozenset({"elevation", "forms"}),
        "output_parameters": ("forms",),
    },
    "grass:r.mapcalc.simple": {
        "required_parameters": frozenset({"a", "b", "c", "expression", "output"}),
        "output_parameters": ("output",),
    },
    "grass:r.thin": {
        "required_parameters": frozenset({"input", "output"}),
        "output_parameters": ("output",),
    },
    "grass:r.to.vect": {
        "required_parameters": frozenset({"input", "output"}),
        "output_parameters": ("output",),
    },
    "grass:r.watershed": {
        "required_parameters": frozenset({"elevation", "accumulation"}),
        "output_parameters": ("accumulation",),
    },
}
_TERRAIN_FEATURE_NORMALIZATION_SCHEMAS = {
    "gdal:assignprojection": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "CRS"}),
        "output_parameters": (),
    }
}
_SAFE_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)
_MAX_TERRAIN_FEATURE_ROUTE_SAMPLES = 128
_GEOMORPHON_SCALES = (
    ("fine", 5),
    ("medium", 10),
    ("coarse", 20),
)
_MAX_CANDIDATE_VECTOR_FEATURES = 20_000
_GEOMORPHON_LABELS = {
    1: "flat",
    2: "peak",
    3: "ridge",
    4: "shoulder",
    5: "spur",
    6: "slope",
    7: "hollow",
    8: "footslope",
    9: "valley",
    10: "pit",
}


class QgisMcpClient(Protocol):
    @property
    def server_version(self) -> str:
        ...

    def initialize(self) -> dict[str, Any]:
        ...

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


class QgisWorkerInputError(ValueError):
    def __init__(self, code: SpatialAnalysisErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class _WorkerCancelled(RuntimeError):
    pass


class _WorkerProcessingFailed(RuntimeError):
    pass


class _WorkerCapabilityUnavailable(RuntimeError):
    pass


class _WorkerCrsUnresolved(RuntimeError):
    pass


class _WorkerRenderFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class QgisWorkerConfig:
    enabled: bool = False
    auth_token: str | None = None
    root: Path = Path.home() / ".scout-fusion" / "qgis-worker"
    source_roots: tuple[Path, ...] = ()
    timeout_s: float = 120.0
    poll_interval_s: float = 0.25
    request_max_bytes: int = 2 * 1024 * 1024
    mcp_command: tuple[str, ...] | None = None
    mcp_pythonpath: str | None = None

    def __post_init__(self) -> None:
        if self.auth_token is not None and len(self.auth_token) < 32:
            raise ValueError("SCOUT QGIS worker token must contain at least 32 characters")
        if not 1 <= int(self.request_max_bytes) <= 16 * 1024 * 1024:
            raise ValueError("QGIS worker request limit must be between 1 byte and 16 MiB")
        if not 0.25 <= float(self.timeout_s) <= 1800:
            raise ValueError("QGIS worker timeout must be between 0.25 and 1800 seconds")
        if not 0.01 <= float(self.poll_interval_s) <= 5:
            raise ValueError("QGIS worker poll interval must be between 0.01 and 5 seconds")

    @classmethod
    def from_env(cls) -> "QgisWorkerConfig":
        root = Path(
            os.getenv("SCOUT_QGIS_WORKER_ROOT", "~/.scout-fusion/qgis-worker")
        ).expanduser()
        roots_value = os.getenv("SCOUT_QGIS_SOURCE_ROOTS", "")
        source_roots = tuple(
            Path(value).expanduser()
            for value in roots_value.split(os.pathsep)
            if value.strip()
        )
        return cls(
            enabled=_env_bool("SCOUT_QGIS_WORKER_ENABLED", default=False),
            auth_token=_env_str("SCOUT_QGIS_WORKER_TOKEN"),
            root=root,
            source_roots=source_roots,
            timeout_s=_env_float("SCOUT_QGIS_WORKER_TIMEOUT", 120.0, 0.25, 1800.0),
            poll_interval_s=_env_float("SCOUT_QGIS_WORKER_POLL_INTERVAL", 0.25, 0.01, 5.0),
            request_max_bytes=_env_int(
                "SCOUT_QGIS_WORKER_REQUEST_MAX_BYTES",
                2 * 1024 * 1024,
                1,
                16 * 1024 * 1024,
            ),
            mcp_command=_mcp_command_from_env(),
            mcp_pythonpath=_env_str("SCOUT_QGIS_MCP_PYTHONPATH"),
        )


class QgisWorkerService:
    def __init__(
        self,
        *,
        config: QgisWorkerConfig,
        mcp_client: QgisMcpClient | None = None,
        now_factory: Any | None = None,
    ) -> None:
        self.config = config
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self.root = config.root.expanduser().resolve(strict=False)
        self.runs_root = self.root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_operations: dict[str, str] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._last_successful_handshake: str | None = None
        if mcp_client is not None:
            self.mcp = mcp_client
        elif config.mcp_command:
            self.mcp = QgisMcpStdioClient(
                QgisMcpClientConfig(
                    command=config.mcp_command,
                    timeout_s=min(config.timeout_s, 300.0),
                    run_root=self.runs_root,
                    source_roots=tuple(config.source_roots),
                    pythonpath=config.mcp_pythonpath,
                )
            )
        else:
            self.mcp = None
        self._recover_interrupted_runs()

    def close(self) -> None:
        if self.mcp is not None:
            self.mcp.close()

    def status(self) -> QgisWorkerStatus:
        base = {
            "enabled": self.config.enabled,
            "configured": bool(self.config.auth_token and self.mcp is not None),
            "tool_allowlist": sorted(QGIS_MCP_ALLOWED_TOOLS),
            "algorithm_allowlist": sorted(QGIS_MCP_ALLOWED_ALGORITHMS),
        }
        if not self.config.enabled:
            return QgisWorkerStatus(
                availability=QgisBackendAvailability.DISABLED,
                warnings=["Scout QGIS worker is disabled."],
                **base,
            )
        if not self.config.auth_token or self.mcp is None:
            return QgisWorkerStatus(
                availability=QgisBackendAvailability.NOT_CONFIGURED,
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                        message="Scout QGIS worker authentication or MCP command is not configured.",
                    )
                ],
                **base,
            )
        try:
            initialized = self.mcp.initialize()
        except (QgisMcpUnavailable, QgisMcpTimeout, QgisMcpError, OSError) as exc:
            return QgisWorkerStatus(
                availability=QgisBackendAvailability.UNAVAILABLE,
                backend_degraded=True,
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                        message="QGIS Agent MCP stdio server is unavailable.",
                        detail=str(exc),
                        retryable=True,
                    )
                ],
                **base,
            )
        mcp_version = _nested_text(initialized, ("serverInfo", "version")) or _mcp_version(self.mcp)
        try:
            snapshot = self.mcp.call_tool("qgis_session_snapshot", {"detail": "summary"})
        except (QgisMcpToolError, QgisMcpUnavailable, QgisMcpTimeout, QgisMcpError) as exc:
            return QgisWorkerStatus(
                availability=QgisBackendAvailability.DEGRADED,
                mcp_reachable=True,
                backend_degraded=True,
                qgis_mcp_plugin_version=mcp_version,
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.QGIS_UNAVAILABLE,
                        message="QGIS application/plugin bridge is unavailable.",
                        detail=str(exc),
                        retryable=True,
                    )
                ],
                **base,
            )
        qgis_version = _find_version(snapshot, "qgis")
        project_loaded = bool(
            _nested_value(snapshot, ("project", "file"))
            or _nested_value(snapshot, ("project", "layer_count"))
            or snapshot.get("layers")
        )
        self._last_successful_handshake = self._now_iso()
        return QgisWorkerStatus(
            availability=QgisBackendAvailability.AVAILABLE,
            mcp_reachable=True,
            qgis_application_available=True,
            plugin_bridge_available=True,
            project_loaded=project_loaded,
            capabilities_discoverable=True,
            qgis_version=qgis_version,
            qgis_mcp_plugin_version=mcp_version,
            last_successful_handshake=self._last_successful_handshake,
            **base,
        )

    def start(self, request: QgisWorkerWorkflowRequest) -> QgisWorkerRun:
        if not self.config.enabled or not self.config.auth_token or self.mcp is None:
            raise QgisWorkerInputError(
                SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                "Scout QGIS worker is not fully configured.",
            )
        dem_refs = tuple(self._validate_source(value) for value in request.dem_refs)
        now = self._now_iso()
        worker_run_id = f"qgis-worker-{now.translate(str.maketrans('', '', '-:.'))}-{uuid4().hex[:10]}"
        run = QgisWorkerRun(
            worker_run_id=worker_run_id,
            project_id=request.project_id,
            workflow_id=request.workflow_id,
            request_id=request.request_id,
            requested_by=request.requested_by,
            state=SpatialWorkflowState.QUEUED,
            created_at=now,
            updated_at=now,
            steps=_initial_steps(request.workflow_id),
            audit_trail=[
                {
                    "event": "workflow_queued",
                    "at": now,
                    "request_id": request.request_id,
                    "requested_by": request.requested_by,
                    "selected_capability": (
                        "terrain_feature_stack"
                        if request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
                        else "terrain_context_preview"
                    ),
                    "algorithm_allowlist": sorted(QGIS_MCP_ALLOWED_ALGORITHMS),
                    "source_count": len(dem_refs),
                }
            ],
        )
        run_root = self._run_root(worker_run_id)
        run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        _write_private_json(run_root / "request.json", request.model_dump(mode="json"))
        self._persist(run)
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._execute,
            args=(run, request, dem_refs, cancel_event),
            name=f"scout-qgis-{worker_run_id[-10:]}",
            daemon=True,
        )
        with self._lock:
            self._cancel_events[worker_run_id] = cancel_event
            self._threads[worker_run_id] = thread
        thread.start()
        return run

    def get(self, worker_run_id: str) -> QgisWorkerRun:
        return QgisWorkerRun.model_validate(_read_json(self._run_path(worker_run_id)))

    def cancel(self, worker_run_id: str, *, requested_by: str) -> QgisWorkerRun:
        run = self.get(worker_run_id)
        if run.state in _TERMINAL_STATES:
            return run
        with self._lock:
            event = self._cancel_events.setdefault(worker_run_id, threading.Event())
            event.set()
            operation_id = self._active_operations.get(worker_run_id)
        if operation_id and self.mcp is not None:
            try:
                self.mcp.call_tool(
                    "qgis_operation",
                    {"operation_id": operation_id, "action": "cancel"},
                )
            except QgisMcpError:
                pass
        if run.state is SpatialWorkflowState.QUEUED:
            now = self._now_iso()
            run = run.model_copy(
                update={
                    "state": SpatialWorkflowState.CANCELLED,
                    "updated_at": now,
                    "completed_at": now,
                    "processing_status": "cancelled",
                    "error": SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                        message="QGIS workflow was cancelled before execution.",
                        retryable=True,
                    ),
                    "audit_trail": [
                        *run.audit_trail,
                        {"event": "workflow_cancelled", "at": now, "requested_by": requested_by},
                    ],
                }
            )
            self._persist(run)
        return run

    def artifact_path(self, worker_run_id: str, artifact_id: str) -> tuple[QgisWorkerArtifact, Path]:
        run = self.get(worker_run_id)
        if run.result is None:
            raise FileNotFoundError("QGIS worker artifacts are not available")
        artifact = next(
            (item for item in run.result.artifacts if item.artifact_id == artifact_id),
            None,
        )
        if artifact is None:
            raise FileNotFoundError("QGIS worker artifact was not found")
        path = (self._run_root(worker_run_id) / artifact.relative_ref).resolve(strict=False)
        try:
            path.relative_to(self._run_root(worker_run_id))
        except ValueError as exc:
            raise FileNotFoundError("QGIS worker artifact path escaped its run") from exc
        if not path.is_file():
            raise FileNotFoundError("QGIS worker artifact file is unavailable")
        return artifact, path

    def _execute(
        self,
        queued: QgisWorkerRun,
        request: QgisWorkerWorkflowRequest,
        dem_refs: tuple[Path, ...],
        cancel_event: threading.Event,
    ) -> None:
        if request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID:
            self._execute_terrain_feature_stack(
                queued,
                request,
                dem_refs,
                cancel_event,
            )
            return
        run = queued
        run_root = self._run_root(run.worker_run_id)
        route_path = run_root / "route.geojson"
        slope_path = run_root / "slope.tif"
        render_path = run_root / "qgis_render_preview.png"
        visual_context_path = run_root / "qgis_visual_context.json"
        added_layers: list[str] = []
        slope_layer_id = ""
        current_step = "input_validation"
        try:
            now = self._now_iso()
            run = run.model_copy(
                update={
                    "state": SpatialWorkflowState.RUNNING,
                    "started_at": now,
                    "updated_at": now,
                    "processing_status": "running",
                    "audit_trail": [*run.audit_trail, {"event": "workflow_started", "at": now}],
                }
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "crs_inspection"
            initialized = self.mcp.initialize() if self.mcp is not None else {}
            session_snapshot = self._call(
                "qgis_session_snapshot",
                {"detail": "summary"},
            )
            context = self._call(
                "qgis_context",
                {
                    "task": "Prepare a bounded route terrain context preview using allowlisted DEM slope processing and render the map canvas.",
                    "budget_bytes": 8192,
                    "detail": "summary",
                    "tool_limit": 5,
                    "runtime_mode": "include",
                },
            )
            snapshot = context.get("snapshot")
            if isinstance(snapshot, dict) and snapshot.get("available") is False:
                error = snapshot.get("error")
                message = (
                    str(error.get("message"))
                    if isinstance(error, dict) and error.get("message")
                    else "QGIS application/plugin bridge is unavailable"
                )
                raise QgisMcpToolError(
                    message,
                    payload={"error": error} if isinstance(error, dict) else {},
                )
            qgis_version = _find_version(session_snapshot, "qgis")
            if qgis_version == "unavailable":
                qgis_version = _find_version(context, "qgis")
            mcp_version = _nested_text(initialized, ("serverInfo", "version")) or _mcp_version(self.mcp)
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "route_preparation"
            _write_private_json(route_path, request.route_geojson)
            route_layer = self._call(
                "qgis_project_action",
                {"action": "add_vector", "source": str(route_path), "name": f"Scout candidate route {run.worker_run_id[-10:]}"},
            )
            route_layer_id = str(route_layer.get("id") or route_layer.get("layer_id") or "")
            if not route_layer_id:
                raise _WorkerProcessingFailed("QGIS did not return a route layer ID")
            added_layers.append(route_layer_id)
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "dem_loaded"
            dem_input = self._prepare_dem(run.worker_run_id, dem_refs, cancel_event)
            run = self._complete_step(run, current_step)
            self._persist(run)

            current_step = "slope_generated"
            slope_operation = self._call(
                "qgis_processing_start",
                {
                    "algorithm": "gdal:slope",
                    "parameters": {
                        "INPUT": str(dem_input),
                        "BAND": 1,
                        "SCALE": 1.0,
                        "AS_PERCENT": False,
                        "COMPUTE_EDGES": True,
                        "ZEVENBERGEN": False,
                        "OUTPUT": str(slope_path),
                    },
                    "retain_outputs": True,
                    "add_to_project": False,
                    "allow_main_thread": False,
                },
            )
            slope_status = self._poll_operation(
                run.worker_run_id,
                _operation_id(slope_operation),
                cancel_event,
            )
            for value in (slope_status.get("retained_outputs") or {}).values():
                if isinstance(value, dict) and value.get("layer_id"):
                    retained_layer_id = str(value["layer_id"])
                    added_layers.append(retained_layer_id)
                    if not slope_layer_id:
                        slope_layer_id = retained_layer_id
            if not slope_path.is_file():
                raise _WorkerProcessingFailed("QGIS slope output file was not created")
            slope_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_raster",
                    "source": str(slope_path),
                    "name": f"Scout candidate slope {run.worker_run_id[-10:]}",
                },
            )
            slope_layer_id = str(
                slope_layer.get("id") or slope_layer.get("layer_id") or ""
            )
            if not slope_layer_id:
                raise _WorkerProcessingFailed(
                    "QGIS did not return a slope layer ID for visual review"
                )
            added_layers.append(slope_layer_id)
            self._call(
                "qgis_raster_style",
                {
                    "layer": slope_layer_id,
                    "action": "single_band_gray",
                    "band": 1,
                    "minimum": 0.0,
                    "maximum": 90.0,
                },
            )
            slope_inspection = self._call(
                "qgis_layer_inspect",
                {
                    "layer": slope_layer_id,
                    "include": ["metadata", "style", "statistics"],
                    "sample_limit": 0,
                },
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "map_rendered"
            if slope_layer_id:
                self._call(
                    "qgis_project_action",
                    {"action": "remove_layer", "layer": route_layer_id},
                )
                route_layer = self._call(
                    "qgis_project_action",
                    {
                        "action": "add_vector",
                        "source": str(route_path),
                        "name": f"Scout candidate route {run.worker_run_id[-10:]}",
                    },
                )
                route_layer_id = str(
                    route_layer.get("id") or route_layer.get("layer_id") or ""
                )
                if not route_layer_id:
                    raise _WorkerRenderFailed(
                        "QGIS did not return a route layer ID for visual review"
                    )
                added_layers.append(route_layer_id)
            for layer_id in (slope_layer_id, route_layer_id):
                self._call(
                    "qgis_layer_manage",
                    {"action": "set_visibility", "layer": layer_id, "visible": False},
                )
                self._call(
                    "qgis_layer_manage",
                    {"action": "set_visibility", "layer": layer_id, "visible": True},
                )
            route_inspection = self._call(
                "qgis_layer_inspect",
                {
                    "layer": route_layer_id,
                    "include": ["metadata", "style"],
                    "sample_limit": 0,
                },
            )
            slope_extent = (slope_inspection.get("summary") or {}).get("extent")
            if not isinstance(slope_extent, dict):
                raise _WorkerRenderFailed("QGIS slope extent is unavailable")
            try:
                review_extent = [
                    float(slope_extent[key])
                    for key in ("xmin", "ymin", "xmax", "ymax")
                ]
            except (KeyError, TypeError, ValueError) as exc:
                raise _WorkerRenderFailed("QGIS slope extent is invalid") from exc
            self._call(
                "qgis_canvas",
                {"action": "set_crs", "crs": "EPSG:3826"},
            )
            self._call(
                "qgis_canvas",
                {"action": "set_extent", "extent": review_extent},
            )
            visual_snapshot = self._call(
                "qgis_session_snapshot",
                {"detail": "summary"},
            )
            layer_tree = self._call(
                "qgis_project_inspect",
                {"section": "layer_tree"},
            )
            visual_context_payload = {
                "schema_version": "scout_qgis_visual_context.v0_1",
                "workflow_run_id": run.worker_run_id,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "slope_layer": slope_inspection,
                "route_layer": route_inspection,
                "session": visual_snapshot,
                "layer_tree": layer_tree,
            }
            _write_private_json(visual_context_path, visual_context_payload)
            screenshot = self._call(
                "qgis_visual_review",
                {
                    "action": "capture",
                    "target": "canvas",
                    "max_width": 1280,
                    "wait_ms": 3000,
                    "geometry_sample": 50,
                    "require_layout": False,
                    "require_saved": False,
                },
            )
            automated_review = screenshot.get("automated_review")
            if isinstance(automated_review, dict) and not automated_review.get(
                "passed", False
            ):
                findings = automated_review.get("findings") or []
                codes = [
                    str(item.get("code"))
                    for item in findings
                    if isinstance(item, dict) and item.get("code")
                ]
                raise _WorkerRenderFailed(
                    "QGIS automated visual checks failed: "
                    + (", ".join(codes[:8]) or "unknown finding")
                )
            fallback_used = False
            if not isinstance(screenshot.get("data"), str):
                fallback = self._call(
                    "qgis_screenshot",
                    {
                        "target": "canvas",
                        "max_width": 1280,
                        "as_artifact": False,
                    },
                )
                screenshot = {**screenshot, **fallback}
                fallback_used = True
            render_bytes = _decode_screenshot(screenshot)
            render_quality = _png_visual_quality(render_bytes)
            if not render_quality["passed"]:
                raise _WorkerRenderFailed(
                    "QGIS screenshot lacks bounded visual content: "
                    f"{render_quality['content_pixel_count']} content pixels "
                    f"of {render_quality['interior_pixel_count']} interior pixels"
                )
            visual_context_payload["render_quality"] = {
                **render_quality,
                "fallback_screenshot_used": fallback_used,
            }
            _write_private_json(visual_context_path, visual_context_payload)
            _write_private_bytes(render_path, render_bytes)
            run = self._complete_step(run, current_step)

            slope_artifact = _artifact(
                run.worker_run_id,
                "slope",
                "slope_raster",
                slope_path,
                "image/tiff",
            )
            render_artifact = _artifact(
                run.worker_run_id,
                "render",
                "qgis_render_preview",
                render_path,
                "image/png",
                width_px=_int_or_none(screenshot.get("width")),
                height_px=_int_or_none(screenshot.get("height")),
                visualization_only=True,
            )
            visual_context_artifact = _artifact(
                run.worker_run_id,
                "visual-context",
                "qgis_visual_context",
                visual_context_path,
                "application/json",
                visualization_only=True,
            )
            completed_at = self._now_iso()
            result = QgisWorkerResult(
                maplibre_geojson=_maplibre_result(
                    request.route_geojson,
                    run.worker_run_id,
                    request.project_id,
                    request.corridor_m,
                    slope_artifact.artifact_id,
                ),
                artifacts=[slope_artifact, render_artifact, visual_context_artifact],
                qgis_version=qgis_version,
                qgis_mcp_plugin_version=mcp_version,
                crs="EPSG:3826",
                source_resolution={
                    **request.source_resolution,
                    "adds_source_resolution": False,
                },
                output_resolution={
                    "slope_raster": "QGIS Processing output; inspect artifact metadata",
                    "render_width_px": render_artifact.width_px,
                    "render_height_px": render_artifact.height_px,
                },
                processing_algorithms=(
                    ["gdal:buildvirtualraster", "gdal:slope"]
                    if len(dem_refs) > 1
                    else ["gdal:slope"]
                ),
                processing_parameters={
                    "dem_source_count": len(dem_refs),
                    "slope_band": 1,
                    "slope_scale": 1.0,
                    "as_percent": False,
                    "compute_edges": True,
                    "zevenbergen": False,
                    "corridor_m": request.corridor_m,
                },
                warnings=[
                    "QGIS Processing success confirms execution only; it does not establish terrain or safety truth.",
                    "MapLibre slope coverage geometry is visualization-only and does not add source resolution.",
                ],
            )
            run = run.model_copy(
                update={
                    "state": SpatialWorkflowState.COMPLETED,
                    "updated_at": completed_at,
                    "completed_at": completed_at,
                    "processing_status": "completed",
                    "render_status": "completed",
                    "result": result,
                    "warnings": result.warnings,
                    "audit_trail": [
                        *run.audit_trail,
                        {
                            "event": "workflow_completed",
                            "at": completed_at,
                            "result": "candidate_evidence_exported",
                            "artifact_ids": [item.artifact_id for item in result.artifacts],
                            "processing_algorithms": result.processing_algorithms,
                        },
                    ],
                }
            )
            self._persist(run)
        except _WorkerCancelled:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "QGIS workflow was cancelled.",
                state=SpatialWorkflowState.CANCELLED,
                retryable=True,
            )
        except QgisMcpToolRejected as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.FORBIDDEN_CAPABILITY,
                "QGIS workflow attempted a forbidden capability.",
                detail=str(exc),
            )
        except QgisMcpTimeout as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "QGIS MCP workflow timed out.",
                detail=str(exc),
                retryable=True,
            )
        except (QgisMcpUnavailable, QgisMcpToolError, QgisMcpError) as exc:
            code = _mcp_failure_code(exc, current_step=current_step)
            self._fail_run(
                run,
                current_step,
                code,
                "QGIS MCP execution failed.",
                detail=str(exc),
                retryable=code
                in {
                    SpatialAnalysisErrorCode.QGIS_UNAVAILABLE,
                    SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                    SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                },
            )
        except _WorkerRenderFailed as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.RENDER_FAILED,
                "QGIS render failed.",
                detail=str(exc),
            )
        except _WorkerProcessingFailed as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.PROCESSING_FAILED,
                "QGIS Processing failed.",
                detail=str(exc),
            )
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.ARTIFACT_EXPORT_FAILED,
                "QGIS workflow artifact export failed.",
                detail=str(exc),
            )
        except Exception as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.UNKNOWN,
                "QGIS workflow encountered an unexpected bounded worker error.",
                detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._cleanup_layers(added_layers)
            with self._lock:
                self._active_operations.pop(run.worker_run_id, None)
                self._cancel_events.pop(run.worker_run_id, None)
                self._threads.pop(run.worker_run_id, None)

    def _execute_terrain_feature_stack(
        self,
        queued: QgisWorkerRun,
        request: QgisWorkerWorkflowRequest,
        dem_refs: tuple[Path, ...],
        cancel_event: threading.Event,
    ) -> None:
        run = queued
        run_root = self._run_root(run.worker_run_id)
        route_path = run_root / "route.geojson"
        projected_route_path = run_root / "route_epsg3826.gpkg"
        slope_path = run_root / "grass_slope.tif"
        aspect_path = run_root / "grass_aspect.tif"
        geomorphon_fine_path = run_root / "grass_geomorphon_fine.tif"
        geomorphon_path = run_root / "grass_geomorphon_landforms.tif"
        geomorphon_coarse_path = run_root / "grass_geomorphon_coarse.tif"
        ridge_consensus_path = run_root / "grass_geomorphon_ridge_consensus.tif"
        valley_consensus_path = run_root / "grass_geomorphon_valley_consensus.tif"
        ridge_thin_path = run_root / "grass_geomorphon_ridge_thin.tif"
        valley_thin_path = run_root / "grass_geomorphon_valley_thin.tif"
        ridge_projected_path = run_root / "ridge_lines_epsg3826.gpkg"
        valley_projected_path = run_root / "valley_lines_epsg3826.gpkg"
        ridge_geojson_path = run_root / "ridge_lines.geojson"
        valley_geojson_path = run_root / "valley_lines.geojson"
        accumulation_path = run_root / "grass_flow_accumulation.tif"
        stream_raster_path = run_root / "grass_stream_network.tif"
        stream_thin_path = run_root / "grass_stream_network_thin.tif"
        stream_projected_path = run_root / "stream_network_epsg3826.gpkg"
        stream_geojson_path = run_root / "stream_network.geojson"
        route_samples_path = run_root / "terrain_feature_route_samples.geojson"
        manifest_path = run_root / "terrain_feature_manifest.json"
        render_path = run_root / "qgis_render_preview.png"
        visual_context_path = run_root / "qgis_visual_context.json"
        project_path = run_root / "terrain_feature_stack.qgz"
        added_layers: list[str] = []
        current_step = "input_validation"
        try:
            now = self._now_iso()
            run = run.model_copy(
                update={
                    "state": SpatialWorkflowState.RUNNING,
                    "started_at": now,
                    "updated_at": now,
                    "processing_status": "running",
                    "audit_trail": [
                        *run.audit_trail,
                        {"event": "workflow_started", "at": now},
                    ],
                }
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "crs_inspection"
            initialized = self.mcp.initialize() if self.mcp is not None else {}
            session_snapshot = self._call(
                "qgis_session_snapshot",
                {"detail": "summary"},
            )
            context = self._call(
                "qgis_context",
                {
                    "task": (
                        "Prepare candidate-only multiscale geomorphons, bounded ridge and "
                        "valley line candidates, and a stream-network candidate with only "
                        "the exact allowlisted GRASS Processing tools; render spatial "
                        "evidence without drawing a route, water, hazard, or safety conclusion."
                    ),
                    "budget_bytes": 8192,
                    "detail": "summary",
                    "tool_limit": 5,
                    "runtime_mode": "include",
                },
            )
            snapshot = context.get("snapshot")
            if isinstance(snapshot, dict) and snapshot.get("available") is False:
                error = snapshot.get("error")
                message = (
                    str(error.get("message"))
                    if isinstance(error, dict) and error.get("message")
                    else "QGIS application/plugin bridge is unavailable"
                )
                raise QgisMcpToolError(
                    message,
                    payload={"error": error} if isinstance(error, dict) else {},
                )
            qgis_version = _find_version(session_snapshot, "qgis")
            if qgis_version == "unavailable":
                qgis_version = _find_version(context, "qgis")
            mcp_version = _nested_text(
                initialized, ("serverInfo", "version")
            ) or _mcp_version(self.mcp)
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "route_preparation"
            _write_private_json(route_path, request.route_geojson)
            source_route_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": str(route_path),
                    "name": f"Scout candidate route source {run.worker_run_id[-10:]}",
                },
            )
            source_route_layer_id = str(
                source_route_layer.get("id")
                or source_route_layer.get("layer_id")
                or ""
            )
            if not source_route_layer_id:
                raise _WorkerProcessingFailed(
                    "QGIS did not return a source route layer ID"
                )
            added_layers.append(source_route_layer_id)
            route_export = self._call(
                "qgis_vector_export",
                {
                    "layer": source_route_layer_id,
                    "path": str(projected_route_path),
                    "format": "gpkg",
                    "encoding": "UTF-8",
                    "selected_only": False,
                    "destination_crs": "EPSG:3826",
                    "overwrite": False,
                    "create_parent": False,
                    "include_z": False,
                    "save_metadata": True,
                },
            )
            exported_path = str(route_export.get("path") or "")
            exported_layer_name = str(route_export.get("layer_name") or "")
            if (
                not projected_route_path.is_file()
                or Path(exported_path).resolve(strict=False)
                != projected_route_path.resolve(strict=False)
                or int(route_export.get("feature_count", -1)) != 1
                or not exported_layer_name.startswith(
                    "Scout candidate route source "
                )
            ):
                raise _WorkerProcessingFailed(
                    "QGIS did not export exactly one projected route feature"
                )
            route_capabilities = [
                {
                    "kind": "tool",
                    "id": "qgis_vector_export",
                    "provider": "qgis",
                    "required_parameters": [
                        "layer",
                        "path",
                        "destination_crs",
                    ],
                    "output_parameters": ["path"],
                }
            ]
            self._call(
                "qgis_project_action",
                {"action": "remove_layer", "layer": source_route_layer_id},
            )
            route_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": (
                        f"{projected_route_path}|layername={exported_layer_name}"
                    ),
                    "name": f"Scout candidate route {run.worker_run_id[-10:]}",
                    "provider": "ogr",
                },
            )
            route_layer_id = str(
                route_layer.get("id") or route_layer.get("layer_id") or ""
            )
            if not route_layer_id:
                raise _WorkerProcessingFailed("QGIS did not return a route layer ID")
            added_layers.append(route_layer_id)
            route_crs_assignment = self._call(
                "qgis_crs",
                {
                    "action": "assign_layer",
                    "layer": route_layer_id,
                    "target": "EPSG:3826",
                    "value": "EPSG:3826",
                },
            )
            prepared_route_inspection = self._call(
                "qgis_layer_inspect",
                {
                    "layer": route_layer_id,
                    "include": ["metadata"],
                    "sample_limit": 0,
                },
            )
            prepared_route_summary = prepared_route_inspection.get("summary") or {}
            prepared_route_crs = str(
                prepared_route_summary.get("crs") or "UNKNOWN"
            ).upper()
            if prepared_route_crs not in {"3826", "EPSG:3826"}:
                raise _WorkerCrsUnresolved(
                    f"Prepared route CRS is unresolved or unsupported: {prepared_route_crs}"
                )
            _validate_projected_route_extent(prepared_route_summary.get("extent"))
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "dem_loaded"
            dem_input = self._prepare_dem(run.worker_run_id, dem_refs, cancel_event)
            dem_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_raster",
                    "source": str(dem_input),
                    "name": f"Scout source DEM {run.worker_run_id[-10:]}",
                },
            )
            dem_layer_id = str(
                dem_layer.get("id") or dem_layer.get("layer_id") or ""
            )
            if not dem_layer_id:
                raise _WorkerCrsUnresolved("QGIS did not return a source DEM layer ID")
            added_layers.append(dem_layer_id)
            source_dem_inspection = self._call(
                "qgis_layer_inspect",
                {
                    "layer": dem_layer_id,
                    "include": ["metadata"],
                    "sample_limit": 0,
                },
            )
            source_dem_crs = str(
                (source_dem_inspection.get("summary") or {}).get("crs")
                or "UNKNOWN"
            ).upper()
            if source_dem_crs not in {"3826", "EPSG:3826"}:
                raise _WorkerCrsUnresolved(
                    f"Source DEM CRS is unresolved or unsupported: {source_dem_crs}"
                )
            _require_extent_intersection(
                prepared_route_summary.get("extent"),
                (source_dem_inspection.get("summary") or {}).get("extent"),
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "capability_discovery"
            saved_project = self._call(
                "qgis_project_action",
                {"action": "save", "path": str(project_path)},
            )
            if not saved_project.get("saved") or not project_path.is_file():
                raise _WorkerProcessingFailed(
                    "QGIS temporary project was not saved before GRASS main-thread processing"
                )
            discovered = [
                *route_capabilities,
                *self._discover_grass_terrain_capabilities(),
            ]
            run = self._complete_step(run, current_step).model_copy(
                update={
                    "audit_trail": [
                        *run.audit_trail,
                        {
                            "event": "temporary_qgis_project_saved",
                            "at": self._now_iso(),
                            "project_ref": project_path.name,
                            "purpose": "bounded_grass_main_thread_processing",
                        },
                    ]
                }
            )
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "slope_aspect_generated"
            self._run_processing_outputs(
                worker_run_id=run.worker_run_id,
                algorithm="grass:r.slope.aspect",
                parameters={
                    "elevation": str(dem_input),
                    "format": 0,
                    "precision": 0,
                    "-a": False,
                    "-e": True,
                    "-n": True,
                    "zscale": 1.0,
                    "min_slope": 0.0,
                    "slope": str(slope_path),
                    "aspect": str(aspect_path),
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                },
                output_paths=(slope_path, aspect_path),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "geomorphon_generated"
            geomorphon_paths = {
                "fine": geomorphon_fine_path,
                "medium": geomorphon_path,
                "coarse": geomorphon_coarse_path,
            }
            for scale_name, search_cells in _GEOMORPHON_SCALES:
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="grass:r.geomorphon",
                    parameters={
                        "elevation": str(dem_input),
                        "search": search_cells,
                        "skip": 0,
                        "flat": 1.0,
                        "dist": 0.0,
                        "forms": str(geomorphon_paths[scale_name]),
                        "-m": False,
                        "-e": False,
                        "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                    },
                    output_paths=(geomorphon_paths[scale_name],),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "ridge_valley_vectorized"
            for expression, consensus_path, thin_path, vector_path in (
                (
                    QGIS_MCP_GEOMORPHON_RIDGE_CONSENSUS_EXPRESSION,
                    ridge_consensus_path,
                    ridge_thin_path,
                    ridge_projected_path,
                ),
                (
                    QGIS_MCP_GEOMORPHON_VALLEY_CONSENSUS_EXPRESSION,
                    valley_consensus_path,
                    valley_thin_path,
                    valley_projected_path,
                ),
            ):
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="grass:r.mapcalc.simple",
                    parameters={
                        "a": str(geomorphon_fine_path),
                        "b": str(geomorphon_path),
                        "c": str(geomorphon_coarse_path),
                        "expression": expression,
                        "output": str(consensus_path),
                    },
                    output_paths=(consensus_path,),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="grass:r.thin",
                    parameters={
                        "input": str(consensus_path),
                        "iterations": 200,
                        "output": str(thin_path),
                    },
                    output_paths=(thin_path,),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="grass:r.to.vect",
                    parameters={
                        "input": str(thin_path),
                        "type": 0,
                        "column": "class_code",
                        "-s": False,
                        "-v": True,
                        "-z": False,
                        "-b": False,
                        "-t": False,
                        "output": str(vector_path),
                    },
                    output_paths=(vector_path,),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "hydrology_generated"
            self._run_processing_outputs(
                worker_run_id=run.worker_run_id,
                algorithm="grass:r.watershed",
                parameters={
                    "elevation": str(dem_input),
                    "threshold": 25,
                    "convergence": 5,
                    "memory": 256,
                    "-s": False,
                    "-m": True,
                    "-4": False,
                    "-a": False,
                    "-b": False,
                    "accumulation": str(accumulation_path),
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                },
                output_paths=(accumulation_path,),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "stream_network_extracted"
            self._run_processing_outputs(
                worker_run_id=run.worker_run_id,
                algorithm="grass:r.mapcalc.simple",
                parameters={
                    "a": str(accumulation_path),
                    "expression": QGIS_MCP_FLOW_CHANNEL_CANDIDATE_EXPRESSION,
                    "output": str(stream_raster_path),
                },
                output_paths=(stream_raster_path,),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
            self._run_processing_outputs(
                worker_run_id=run.worker_run_id,
                algorithm="grass:r.thin",
                parameters={
                    "input": str(stream_raster_path),
                    "iterations": 200,
                    "output": str(stream_thin_path),
                },
                output_paths=(stream_thin_path,),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
            self._run_processing_outputs(
                worker_run_id=run.worker_run_id,
                algorithm="grass:r.to.vect",
                parameters={
                    "input": str(stream_thin_path),
                    "type": 0,
                    "column": "class_code",
                    "-s": False,
                    "-v": True,
                    "-z": False,
                    "-b": False,
                    "-t": False,
                    "output": str(stream_projected_path),
                },
                output_paths=(stream_projected_path,),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "crs_normalized"
            for output_path in (
                slope_path,
                aspect_path,
                geomorphon_fine_path,
                geomorphon_path,
                geomorphon_coarse_path,
                ridge_consensus_path,
                valley_consensus_path,
                ridge_thin_path,
                valley_thin_path,
                accumulation_path,
                stream_raster_path,
                stream_thin_path,
            ):
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="gdal:assignprojection",
                    parameters={"INPUT": str(output_path), "CRS": "EPSG:3826"},
                    output_paths=(output_path,),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "candidate_vectors_exported"
            candidate_vectors: dict[str, dict[str, Any]] = {}
            candidate_vector_layer_ids: dict[str, str] = {}
            for vector_name, projected_path, geojson_path, kind, label in (
                (
                    "ridge",
                    ridge_projected_path,
                    ridge_geojson_path,
                    "qgis_candidate_ridge_line",
                    "Multiscale ridge-line candidate",
                ),
                (
                    "valley",
                    valley_projected_path,
                    valley_geojson_path,
                    "qgis_candidate_valley_line",
                    "Multiscale valley-line candidate",
                ),
                (
                    "stream",
                    stream_projected_path,
                    stream_geojson_path,
                    "qgis_candidate_stream_network",
                    "DEM-derived stream-network candidate",
                ),
            ):
                payload, layer_id = self._export_candidate_terrain_vector(
                    run=run,
                    vector_name=vector_name,
                    projected_path=projected_path,
                    output_path=geojson_path,
                    kind=kind,
                    label=label,
                    added_layers=added_layers,
                )
                candidate_vectors[vector_name] = payload
                candidate_vector_layer_ids[vector_name] = layer_id
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "route_feature_sampling"
            route_samples_payload = self._sample_terrain_features_along_route(
                run=run,
                route_geojson=request.route_geojson,
                raster_paths={
                    "slope_degrees": slope_path,
                    "aspect_degrees": aspect_path,
                    "geomorphon_fine_code": geomorphon_fine_path,
                    "geomorphon_code": geomorphon_path,
                    "geomorphon_coarse_code": geomorphon_coarse_path,
                    "flow_accumulation_cells": accumulation_path,
                },
                output_path=route_samples_path,
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            manifest_payload = {
                "schema_version": "scout_terrain_feature_stack.v0_2",
                "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
                "workflow_run_id": run.worker_run_id,
                "engine": "qgis_processing_grass",
                "capabilities": discovered,
                "artifacts": {
                    "slope": slope_path.name,
                    "aspect": aspect_path.name,
                    "geomorphon_fine": geomorphon_fine_path.name,
                    "geomorphon_medium": geomorphon_path.name,
                    "geomorphon_coarse": geomorphon_coarse_path.name,
                    "geomorphon_ridge_consensus": ridge_consensus_path.name,
                    "geomorphon_valley_consensus": valley_consensus_path.name,
                    "ridge_lines": ridge_geojson_path.name,
                    "valley_lines": valley_geojson_path.name,
                    "flow_accumulation": accumulation_path.name,
                    "stream_network_raster": stream_raster_path.name,
                    "stream_network_vector": stream_geojson_path.name,
                    "route_feature_samples": route_samples_path.name,
                },
                "candidate_vector_feature_counts": {
                    name: len(payload.get("features") or [])
                    for name, payload in candidate_vectors.items()
                },
                "source_refs": request.source_refs,
                "source_hashes": request.source_hashes,
                "source_resolution": request.source_resolution,
                "source_crs": source_dem_crs,
                "source_dem_inspection": source_dem_inspection,
                "parameters": {
                    "route_preparation_tool": "qgis_vector_export",
                    "route_output_crs": "EPSG:3826",
                    "route_runtime_crs_assignment": (
                        route_crs_assignment.get("assignment") or {}
                    ),
                    "route_export_file_crs": "UNKNOWN",
                    "geomorphon_search_cells": {
                        scale_name: search_cells
                        for scale_name, search_cells in _GEOMORPHON_SCALES
                    },
                    "geomorphon_skip_cells": 0,
                    "geomorphon_flat_degrees": 1.0,
                    "geomorphon_consensus_minimum_scales": 2,
                    "ridge_geomorphon_code": 3,
                    "valley_geomorphon_code": 9,
                    "ridge_valley_thin_iterations": 200,
                    "ridge_valley_vector_type": "line",
                    "watershed_threshold_cells": 25,
                    "watershed_memory_mb": 256,
                    "watershed_disk_swap": True,
                    "stream_network_algorithm": (
                        "grass:r.watershed accumulation + fixed grass:r.mapcalc.simple "
                        "+ grass:r.thin + grass:r.to.vect"
                    ),
                    "stream_network_threshold_cells": 25,
                    "stream_network_thin_iterations": 200,
                    "candidate_vector_output_crs": "EPSG:4326",
                    "qgis_main_thread_processing": True,
                    "temporary_project_ref": project_path.name,
                    "crs_metadata_normalization": "gdal:assignprojection EPSG:3826",
                },
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "adds_source_resolution": False,
                "interpretation": (
                    "Multiscale terrain forms and derived ridge, valley, and stream lines "
                    "are candidate spatial evidence. They do not establish observed water, "
                    "hazard, navigability, route, trail, or safety truth."
                ),
            }
            _write_private_json(manifest_path, manifest_payload)

            current_step = "map_rendered"
            screenshot, render_bytes, slope_inspection = self._render_feature_stack_preview(
                run=run,
                route_source=(
                    f"{projected_route_path}|layername={exported_layer_name}"
                ),
                route_layer_id=route_layer_id,
                slope_path=slope_path,
                candidate_vector_sources={
                    "stream": (
                        candidate_vector_layer_ids["stream"],
                        stream_projected_path,
                    ),
                    "valley": (
                        candidate_vector_layer_ids["valley"],
                        valley_projected_path,
                    ),
                    "ridge": (
                        candidate_vector_layer_ids["ridge"],
                        ridge_projected_path,
                    ),
                },
                visual_context_path=visual_context_path,
                manifest_payload=manifest_payload,
                added_layers=added_layers,
            )
            _write_private_bytes(render_path, render_bytes)
            run = self._complete_step(run, current_step)

            slope_artifact = _artifact(
                run.worker_run_id,
                "grass-slope",
                "slope_raster",
                slope_path,
                "image/tiff",
            )
            aspect_artifact = _artifact(
                run.worker_run_id,
                "grass-aspect",
                "aspect_raster",
                aspect_path,
                "image/tiff",
            )
            geomorphon_artifact = _artifact(
                run.worker_run_id,
                "grass-geomorphon",
                "geomorphon_raster",
                geomorphon_path,
                "image/tiff",
            )
            geomorphon_fine_artifact = _artifact(
                run.worker_run_id,
                "grass-geomorphon-fine",
                "geomorphon_fine_raster",
                geomorphon_fine_path,
                "image/tiff",
            )
            geomorphon_coarse_artifact = _artifact(
                run.worker_run_id,
                "grass-geomorphon-coarse",
                "geomorphon_coarse_raster",
                geomorphon_coarse_path,
                "image/tiff",
            )
            ridge_consensus_artifact = _artifact(
                run.worker_run_id,
                "grass-geomorphon-ridge-consensus",
                "geomorphon_consensus_ridge_raster",
                ridge_consensus_path,
                "image/tiff",
            )
            valley_consensus_artifact = _artifact(
                run.worker_run_id,
                "grass-geomorphon-valley-consensus",
                "geomorphon_consensus_valley_raster",
                valley_consensus_path,
                "image/tiff",
            )
            accumulation_artifact = _artifact(
                run.worker_run_id,
                "grass-flow-accumulation",
                "flow_accumulation_raster",
                accumulation_path,
                "image/tiff",
            )
            stream_raster_artifact = _artifact(
                run.worker_run_id,
                "grass-stream-network-raster",
                "stream_network_raster",
                stream_raster_path,
                "image/tiff",
            )
            ridge_vector_artifact = _artifact(
                run.worker_run_id,
                "ridge-lines-vector",
                "ridge_lines_vector",
                ridge_geojson_path,
                "application/geo+json",
            )
            valley_vector_artifact = _artifact(
                run.worker_run_id,
                "valley-lines-vector",
                "valley_lines_vector",
                valley_geojson_path,
                "application/geo+json",
            )
            stream_vector_artifact = _artifact(
                run.worker_run_id,
                "stream-network-vector",
                "stream_network_vector",
                stream_geojson_path,
                "application/geo+json",
            )
            route_samples_artifact = _artifact(
                run.worker_run_id,
                "terrain-feature-route-samples",
                "terrain_feature_route_samples",
                route_samples_path,
                "application/geo+json",
            )
            manifest_artifact = _artifact(
                run.worker_run_id,
                "terrain-feature-manifest",
                "terrain_feature_manifest",
                manifest_path,
                "application/json",
            )
            render_artifact = _artifact(
                run.worker_run_id,
                "render",
                "qgis_render_preview",
                render_path,
                "image/png",
                width_px=_int_or_none(screenshot.get("width")),
                height_px=_int_or_none(screenshot.get("height")),
                visualization_only=True,
            )
            visual_context_artifact = _artifact(
                run.worker_run_id,
                "visual-context",
                "qgis_visual_context",
                visual_context_path,
                "application/json",
                visualization_only=True,
            )
            artifacts = [
                slope_artifact,
                aspect_artifact,
                geomorphon_fine_artifact,
                geomorphon_artifact,
                geomorphon_coarse_artifact,
                ridge_consensus_artifact,
                valley_consensus_artifact,
                accumulation_artifact,
                stream_raster_artifact,
                ridge_vector_artifact,
                valley_vector_artifact,
                stream_vector_artifact,
                route_samples_artifact,
                manifest_artifact,
                render_artifact,
                visual_context_artifact,
            ]
            completed_at = self._now_iso()
            processing_algorithms = [
                *(["gdal:buildvirtualraster"] if len(dem_refs) > 1 else []),
                "grass:r.slope.aspect",
                "grass:r.geomorphon",
                "grass:r.mapcalc.simple",
                "grass:r.thin",
                "grass:r.to.vect",
                "grass:r.watershed",
                "gdal:assignprojection",
            ]
            result = QgisWorkerResult(
                maplibre_geojson=_maplibre_result(
                    request.route_geojson,
                    run.worker_run_id,
                    request.project_id,
                    request.corridor_m,
                    slope_artifact.artifact_id,
                    route_samples_geojson=route_samples_payload,
                    route_samples_artifact_id=route_samples_artifact.artifact_id,
                    candidate_vector_geojsons={
                        "ridge": (
                            candidate_vectors["ridge"],
                            ridge_vector_artifact.artifact_id,
                        ),
                        "valley": (
                            candidate_vectors["valley"],
                            valley_vector_artifact.artifact_id,
                        ),
                        "stream": (
                            candidate_vectors["stream"],
                            stream_vector_artifact.artifact_id,
                        ),
                    },
                ),
                artifacts=artifacts,
                qgis_version=qgis_version,
                qgis_mcp_plugin_version=mcp_version,
                crs=str(
                    (slope_inspection.get("summary") or {}).get("crs")
                    or "UNKNOWN"
                ),
                source_resolution={
                    **request.source_resolution,
                    "adds_source_resolution": False,
                },
                output_resolution={
                    "status": "processing_output_requires_artifact_inspection",
                    "preserves_source_evidence_resolution": True,
                    "adds_source_resolution": False,
                    "render_width_px": render_artifact.width_px,
                    "render_height_px": render_artifact.height_px,
                },
                processing_algorithms=processing_algorithms,
                processing_parameters=manifest_payload["parameters"],
                warnings=[
                    "GRASS/QGIS execution success confirms processing only; it does not establish terrain or safety truth.",
                    "Multiscale geomorphons and extracted ridge, valley, and stream lines are candidate terrain morphology, not observed route, water, hazard, trail, or navigability conclusions.",
                    "Flow-channel candidates use absolute accumulation because corridor-edge negative values may indicate underestimated outside-region inflow; water presence is not confirmed.",
                    "Rendered appearance and interpolation do not add source resolution.",
                ],
            )
            run = run.model_copy(
                update={
                    "state": SpatialWorkflowState.COMPLETED,
                    "updated_at": completed_at,
                    "completed_at": completed_at,
                    "processing_status": "completed",
                    "render_status": "completed",
                    "result": result,
                    "warnings": result.warnings,
                    "audit_trail": [
                        *run.audit_trail,
                        {
                            "event": "workflow_completed",
                            "at": completed_at,
                            "result": "candidate_terrain_feature_evidence_exported",
                            "artifact_ids": [item.artifact_id for item in artifacts],
                            "processing_algorithms": processing_algorithms,
                        },
                    ],
                }
            )
            self._persist(run)
        except _WorkerCancelled:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "QGIS terrain feature workflow was cancelled.",
                state=SpatialWorkflowState.CANCELLED,
                retryable=True,
            )
        except _WorkerCapabilityUnavailable as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.UNSUPPORTED_TOOL,
                "Required GRASS Processing capability is unavailable.",
                detail=str(exc),
            )
        except _WorkerCrsUnresolved as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.CRS_UNRESOLVED,
                "QGIS terrain feature CRS could not be resolved.",
                detail=str(exc),
            )
        except QgisMcpToolRejected as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.FORBIDDEN_CAPABILITY,
                "QGIS terrain feature workflow attempted a forbidden capability.",
                detail=str(exc),
            )
        except QgisMcpTimeout as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "QGIS MCP terrain feature workflow timed out.",
                detail=str(exc),
                retryable=True,
            )
        except (QgisMcpUnavailable, QgisMcpToolError, QgisMcpError) as exc:
            code = _mcp_failure_code(exc, current_step=current_step)
            self._fail_run(
                run,
                current_step,
                code,
                "QGIS MCP terrain feature execution failed.",
                detail=str(exc),
                retryable=code
                in {
                    SpatialAnalysisErrorCode.QGIS_UNAVAILABLE,
                    SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                    SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                },
            )
        except _WorkerRenderFailed as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.RENDER_FAILED,
                "QGIS terrain feature render failed.",
                detail=str(exc),
            )
        except _WorkerProcessingFailed as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.PROCESSING_FAILED,
                "QGIS terrain feature Processing failed.",
                detail=str(exc),
            )
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.ARTIFACT_EXPORT_FAILED,
                "QGIS terrain feature artifact export failed.",
                detail=str(exc),
            )
        except Exception as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.UNKNOWN,
                "QGIS terrain feature workflow encountered an unexpected bounded worker error.",
                detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._cleanup_layers(added_layers)
            with self._lock:
                self._active_operations.pop(run.worker_run_id, None)
                self._cancel_events.pop(run.worker_run_id, None)
                self._threads.pop(run.worker_run_id, None)

    def _discover_grass_terrain_capabilities(self) -> list[dict[str, Any]]:
        contracts = {
            **{
                algorithm: {**contract, "provider": "grass"}
                for algorithm, contract in _GRASS_TERRAIN_FEATURE_SCHEMAS.items()
            },
            **_TERRAIN_FEATURE_NORMALIZATION_SCHEMAS,
        }
        return self._discover_processing_capabilities(contracts)

    def _discover_processing_capabilities(
        self,
        contracts: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        discovered: list[dict[str, Any]] = []
        for algorithm, contract in contracts.items():
            provider = str(contract["provider"])
            search = self._call(
                "qgis_capabilities_search",
                {"query": algorithm, "kinds": ["processing"], "limit": 5},
            )
            match = next(
                (
                    item
                    for item in search.get("results") or []
                    if isinstance(item, dict)
                    and item.get("kind") == "processing"
                    and item.get("id") == algorithm
                    and item.get("provider") == provider
                ),
                None,
            )
            if match is None:
                raise _WorkerCapabilityUnavailable(algorithm)
            description = self._call(
                "qgis_capability_describe",
                {"kind": "processing", "id": algorithm},
            )
            schema = description.get("input_schema")
            properties = schema.get("properties") if isinstance(schema, dict) else None
            parameter_names = set(properties) if isinstance(properties, dict) else set()
            required = contract["required_parameters"]
            if not required.issubset(parameter_names):
                missing = sorted(required - parameter_names)
                raise _WorkerCapabilityUnavailable(
                    f"{algorithm} missing parameters: {', '.join(missing)}"
                )
            discovered.append(
                {
                    "kind": "processing",
                    "id": algorithm,
                    "provider": provider,
                    "required_parameters": sorted(required),
                    "output_parameters": list(contract["output_parameters"]),
                }
            )
        return discovered

    def _run_processing_outputs(
        self,
        *,
        worker_run_id: str,
        algorithm: str,
        parameters: dict[str, Any],
        output_paths: tuple[Path, ...],
        cancel_event: threading.Event,
        added_layers: list[str],
    ) -> None:
        operation = self._call(
            "qgis_processing_start",
            {
                "algorithm": algorithm,
                "parameters": parameters,
                "retain_outputs": True,
                "add_to_project": False,
                "allow_main_thread": algorithm in _GRASS_TERRAIN_FEATURE_SCHEMAS,
            },
        )
        status = self._poll_operation(
            worker_run_id,
            _operation_id(operation),
            cancel_event,
        )
        for value in (status.get("retained_outputs") or {}).values():
            if isinstance(value, dict) and value.get("layer_id"):
                added_layers.append(str(value["layer_id"]))
        missing = [path.name for path in output_paths if not path.is_file()]
        if missing:
            raise _WorkerProcessingFailed(
                f"{algorithm} did not create outputs: {', '.join(missing)}"
            )

    def _export_candidate_terrain_vector(
        self,
        *,
        run: QgisWorkerRun,
        vector_name: str,
        projected_path: Path,
        output_path: Path,
        kind: str,
        label: str,
        added_layers: list[str],
    ) -> tuple[dict[str, Any], str]:
        layer_name = (
            f"Scout_candidate_terrain_vector_source_{vector_name}_"
            f"{run.worker_run_id[-10:]}"
        )
        layer = self._call(
            "qgis_project_action",
            {
                "action": "add_vector",
                "source": str(projected_path),
                "name": layer_name,
                "provider": "ogr",
            },
        )
        layer_id = str(layer.get("id") or layer.get("layer_id") or "")
        if not layer_id.startswith("Scout_candidate_terrain_vector_source_"):
            raise _WorkerProcessingFailed(
                f"QGIS did not return a bounded {vector_name} candidate layer ID"
            )
        added_layers.append(layer_id)
        crs_assignment = self._call(
            "qgis_crs",
            {
                "action": "assign_layer",
                "layer": layer_id,
                "target": "EPSG:3826",
                "value": "EPSG:3826",
            },
        )
        inspection = self._call(
            "qgis_layer_inspect",
            {
                "layer": layer_id,
                "include": ["metadata"],
                "sample_limit": 0,
            },
        )
        source_crs = str(
            (inspection.get("summary") or {}).get("crs") or "UNKNOWN"
        ).upper()
        if source_crs not in {"3826", "EPSG:3826"}:
            raise _WorkerCrsUnresolved(
                f"Candidate {vector_name} source CRS is unresolved: {source_crs}"
            )
        exported = self._call(
            "qgis_vector_export",
            {
                "layer": layer_id,
                "path": str(output_path),
                "format": "geojson",
                "encoding": "UTF-8",
                "selected_only": False,
                "destination_crs": "EPSG:4326",
                "overwrite": False,
                "create_parent": False,
                "include_z": False,
                "save_metadata": True,
            },
        )
        exported_path = str(exported.get("path") or "")
        feature_count = int(exported.get("feature_count", -1))
        if (
            not output_path.is_file()
            or Path(exported_path).resolve(strict=False)
            != output_path.resolve(strict=False)
            or not 0 <= feature_count <= _MAX_CANDIDATE_VECTOR_FEATURES
        ):
            raise _WorkerProcessingFailed(
                f"QGIS did not export a bounded {vector_name} candidate GeoJSON"
            )
        if output_path.stat().st_size > 16 * 1024 * 1024:
            raise _WorkerProcessingFailed(
                f"QGIS {vector_name} candidate GeoJSON exceeded the Scout limit"
            )
        try:
            raw_payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _WorkerProcessingFailed(
                f"QGIS {vector_name} candidate GeoJSON was malformed"
            ) from exc
        payload = _normalize_candidate_terrain_vector_geojson(
            raw_payload,
            worker_run_id=run.worker_run_id,
            vector_name=vector_name,
            kind=kind,
            label=label,
            crs_assignment=crs_assignment.get("assignment") or {},
        )
        if len(payload["features"]) != feature_count:
            raise _WorkerProcessingFailed(
                f"QGIS {vector_name} candidate feature count changed during export"
            )
        _write_private_json(output_path, payload)
        return payload, layer_id

    def _sample_terrain_features_along_route(
        self,
        *,
        run: QgisWorkerRun,
        route_geojson: dict[str, Any],
        raster_paths: dict[str, Path],
        output_path: Path,
        cancel_event: threading.Event,
        added_layers: list[str],
    ) -> dict[str, Any]:
        layer_ids: dict[str, str] = {}
        for field, raster_path in raster_paths.items():
            layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_raster",
                    "source": str(raster_path),
                    "name": f"Scout GRASS {field} {run.worker_run_id[-10:]}",
                },
            )
            layer_id = str(layer.get("id") or layer.get("layer_id") or "")
            if not layer_id or layer_id in layer_ids.values():
                raise _WorkerProcessingFailed(
                    f"QGIS did not return a unique raster layer ID for {field}"
                )
            layer_ids[field] = layer_id
            added_layers.append(layer_id)

        coordinates = _route_line_coordinates(route_geojson)
        sample_positions = _bounded_route_sample_positions(
            coordinates,
            max_samples=_MAX_TERRAIN_FEATURE_ROUTE_SAMPLES,
        )
        features: list[dict[str, Any]] = []
        complete_value_count = 0
        for sample_ordinal, sample in enumerate(sample_positions):
            self._check_cancel(cancel_event)
            lon, lat = sample["coordinate"]
            identified = self._call(
                "qgis_identify",
                {
                    "point": [lon, lat],
                    "crs": "EPSG:4326",
                    "layers": list(layer_ids.values()),
                    "tolerance": 0.0,
                    "limit_per_layer": 1,
                },
            )
            values_by_layer = _identified_raster_values(identified)
            sampled_values = {
                field: values_by_layer.get(layer_id)
                for field, layer_id in layer_ids.items()
            }
            available_fields = sorted(
                field for field, value in sampled_values.items() if value is not None
            )
            if available_fields:
                complete_value_count += 1
            geomorphon_fine_code = _geomorphon_code(
                sampled_values["geomorphon_fine_code"]
            )
            geomorphon_code = _geomorphon_code(sampled_values["geomorphon_code"])
            geomorphon_coarse_code = _geomorphon_code(
                sampled_values["geomorphon_coarse_code"]
            )
            geomorphon_consensus_code = _geomorphon_consensus_code(
                (
                    geomorphon_fine_code,
                    geomorphon_code,
                    geomorphon_coarse_code,
                )
            )
            accumulation = sampled_values["flow_accumulation_cells"]
            properties = {
                "sample_id": (
                    f"{run.worker_run_id}.terrain-feature-sample.{sample_ordinal:04d}"
                ),
                "workflow_run_id": run.worker_run_id,
                "kind": "qgis_terrain_feature_sample",
                "feature_class": "qgis_terrain_feature_sample",
                "route_vertex_index": sample["vertex_index"],
                "route_fraction": sample["route_fraction"],
                "distance_m": sample["distance_m"],
                "slope_degrees": sampled_values["slope_degrees"],
                "aspect_degrees": sampled_values["aspect_degrees"],
                "geomorphon_fine_code": geomorphon_fine_code,
                "geomorphon_fine_label": _GEOMORPHON_LABELS.get(
                    geomorphon_fine_code
                ),
                "geomorphon_code": geomorphon_code,
                "geomorphon_label": _GEOMORPHON_LABELS.get(geomorphon_code),
                "geomorphon_coarse_code": geomorphon_coarse_code,
                "geomorphon_coarse_label": _GEOMORPHON_LABELS.get(
                    geomorphon_coarse_code
                ),
                "geomorphon_consensus_code": geomorphon_consensus_code,
                "geomorphon_consensus_label": _GEOMORPHON_LABELS.get(
                    geomorphon_consensus_code
                ),
                "geomorphon_consensus_minimum_scales": 2,
                "flow_accumulation_cells": accumulation,
                "flow_accumulation_abs_cells": (
                    abs(accumulation) if accumulation is not None else None
                ),
                "flow_accumulation_likely_underestimated": (
                    accumulation < 0 if accumulation is not None else None
                ),
                "available_fields": available_fields,
                "missing_fields": sorted(set(raster_paths) - set(available_fields)),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "risk_score_applied": False,
                "risk_v2_status": "calibration_required",
                "fixture": False,
                "synthetic": False,
                "adds_source_resolution": False,
            }
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": properties,
                }
            )
        if not complete_value_count:
            raise _WorkerProcessingFailed(
                "QGIS raster identify returned no terrain feature values along the route"
            )
        payload = {
            "type": "FeatureCollection",
            "metadata": {
                "artifact_kind": "scout_qgis_terrain_feature_route_samples",
                "schema_version": "scout_qgis_terrain_feature_route_samples.v0_1",
                "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
                "workflow_run_id": run.worker_run_id,
                "sampling_method": "qgis_identify_nearest_raster_cell",
                "source_route_coordinate_count": len(coordinates),
                "sample_count": len(features),
                "sample_limit": _MAX_TERRAIN_FEATURE_ROUTE_SAMPLES,
                "sampled_raster_fields": list(raster_paths),
                "geomorphon_scales": {
                    scale_name: {"search_cells": search_cells}
                    for scale_name, search_cells in _GEOMORPHON_SCALES
                },
                "geomorphon_labels": {
                    str(code): label for code, label in _GEOMORPHON_LABELS.items()
                },
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "risk_score_applied": False,
                "risk_v2_status": "calibration_required",
                "adds_source_resolution": False,
                "interpretation": (
                    "Values are route-aligned candidate terrain inputs. They do not "
                    "classify hazard, route truth, navigability, or safety."
                ),
            },
            "features": features,
        }
        _write_private_json(output_path, payload)
        return payload

    def _render_feature_stack_preview(
        self,
        *,
        run: QgisWorkerRun,
        route_source: str,
        route_layer_id: str,
        slope_path: Path,
        candidate_vector_sources: dict[str, tuple[str, Path]],
        visual_context_path: Path,
        manifest_payload: dict[str, Any],
        added_layers: list[str],
    ) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
        slope_layer = self._call(
            "qgis_project_action",
            {
                "action": "add_raster",
                "source": str(slope_path),
                "name": f"Scout GRASS candidate slope {run.worker_run_id[-10:]}",
            },
        )
        slope_layer_id = str(
            slope_layer.get("id") or slope_layer.get("layer_id") or ""
        )
        if not slope_layer_id:
            raise _WorkerRenderFailed("QGIS did not return a slope layer ID")
        added_layers.append(slope_layer_id)
        self._call(
            "qgis_raster_style",
            {
                "layer": slope_layer_id,
                "action": "single_band_gray",
                "band": 1,
                "minimum": 0.0,
                "maximum": 90.0,
            },
        )
        slope_inspection = self._call(
            "qgis_layer_inspect",
            {
                "layer": slope_layer_id,
                "include": ["metadata", "style", "statistics"],
                "sample_limit": 0,
            },
        )
        slope_summary = slope_inspection.get("summary") or {}
        slope_crs = str(slope_summary.get("crs") or "UNKNOWN").upper()
        if slope_crs not in {"3826", "EPSG:3826"}:
            raise _WorkerRenderFailed(
                f"GRASS slope output CRS is unresolved or unsupported: {slope_crs}"
            )
        vector_render_styles = {
            "stream": ("#1769aa", 2.2),
            "valley": ("#38a7c7", 2.0),
            "ridge": ("#ffb000", 2.0),
        }
        render_vector_layer_ids: list[str] = []
        render_vector_inspections: dict[str, Any] = {}
        for vector_name, (source_layer_id, source_path) in candidate_vector_sources.items():
            self._call(
                "qgis_project_action",
                {"action": "remove_layer", "layer": source_layer_id},
            )
            vector_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": str(source_path),
                    "name": (
                        f"Scout candidate render {vector_name} "
                        f"{run.worker_run_id[-10:]}"
                    ),
                    "provider": "ogr",
                },
            )
            vector_layer_id = str(
                vector_layer.get("id") or vector_layer.get("layer_id") or ""
            )
            if not vector_layer_id:
                raise _WorkerRenderFailed(
                    f"QGIS did not return the {vector_name} candidate render layer"
                )
            added_layers.append(vector_layer_id)
            render_vector_layer_ids.append(vector_layer_id)
            color, width = vector_render_styles[vector_name]
            self._call(
                "qgis_style_apply",
                {
                    "layer": vector_layer_id,
                    "mode": "simple",
                    "color": color,
                    "opacity": 0.92,
                    "width": width,
                },
            )
            render_vector_inspections[vector_name] = self._call(
                "qgis_layer_inspect",
                {
                    "layer": vector_layer_id,
                    "include": ["metadata", "style"],
                    "sample_limit": 0,
                },
            )
        self._call(
            "qgis_project_action",
            {"action": "remove_layer", "layer": route_layer_id},
        )
        route_layer = self._call(
            "qgis_project_action",
            {
                "action": "add_vector",
                "source": route_source,
                "name": f"Scout candidate route {run.worker_run_id[-10:]}",
                "provider": "ogr",
            },
        )
        render_route_layer_id = str(
            route_layer.get("id") or route_layer.get("layer_id") or ""
        )
        if not render_route_layer_id:
            raise _WorkerRenderFailed("QGIS did not return a route layer ID for render")
        added_layers.append(render_route_layer_id)
        self._call(
            "qgis_style_apply",
            {
                "layer": render_route_layer_id,
                "mode": "simple",
                "color": "#ff365e",
                "opacity": 1.0,
                "width": 2.4,
            },
        )
        for layer_id in (
            slope_layer_id,
            *render_vector_layer_ids,
            render_route_layer_id,
        ):
            self._call(
                "qgis_layer_manage",
                {"action": "set_visibility", "layer": layer_id, "visible": False},
            )
            self._call(
                "qgis_layer_manage",
                {"action": "set_visibility", "layer": layer_id, "visible": True},
            )
        route_inspection = self._call(
            "qgis_layer_inspect",
            {
                "layer": render_route_layer_id,
                "include": ["metadata", "style"],
                "sample_limit": 0,
            },
        )
        extent = slope_summary.get("extent")
        if not isinstance(extent, dict):
            raise _WorkerRenderFailed("QGIS GRASS slope extent is unavailable")
        try:
            review_extent = [
                float(extent[key]) for key in ("xmin", "ymin", "xmax", "ymax")
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise _WorkerRenderFailed("QGIS GRASS slope extent is invalid") from exc
        self._call("qgis_canvas", {"action": "set_crs", "crs": "EPSG:3826"})
        self._call(
            "qgis_canvas",
            {"action": "set_extent", "extent": review_extent},
        )
        self._call("qgis_project_action", {"action": "refresh"})
        visual_context_payload = {
            "schema_version": "scout_qgis_visual_context.v0_1",
            "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            "workflow_run_id": run.worker_run_id,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "rendered_feature": "grass_slope_with_candidate_terrain_lines",
            "slope_layer": slope_inspection,
            "candidate_vector_layers": render_vector_inspections,
            "route_layer": route_inspection,
            "terrain_feature_manifest": manifest_payload,
            "session": self._call("qgis_session_snapshot", {"detail": "summary"}),
            "layer_tree": self._call(
                "qgis_project_inspect", {"section": "layer_tree"}
            ),
        }
        _write_private_json(visual_context_path, visual_context_payload)
        screenshot = self._call(
            "qgis_visual_review",
            {
                "action": "capture",
                "target": "canvas",
                "max_width": 1280,
                "wait_ms": 3000,
                "geometry_sample": 50,
                "require_layout": False,
                "require_saved": False,
            },
        )
        automated_review = screenshot.get("automated_review")
        if isinstance(automated_review, dict) and not automated_review.get(
            "passed", False
        ):
            findings = automated_review.get("findings") or []
            codes = [
                str(item.get("code"))
                for item in findings
                if isinstance(item, dict) and item.get("code")
            ]
            raise _WorkerRenderFailed(
                "QGIS automated visual checks failed: "
                + (", ".join(codes[:8]) or "unknown finding")
            )
        fallback_used = False
        if not isinstance(screenshot.get("data"), str):
            fallback = self._call(
                "qgis_screenshot",
                {"target": "canvas", "max_width": 1280, "as_artifact": False},
            )
            screenshot = {**screenshot, **fallback}
            fallback_used = True
        render_bytes = _decode_screenshot(screenshot)
        render_bytes, crop = _crop_png_to_content(render_bytes, padding_px=12)
        render_quality = _png_visual_quality(render_bytes)
        if not render_quality["passed"]:
            raise _WorkerRenderFailed(
                "QGIS screenshot lacks bounded visual content: "
                f"{render_quality['content_pixel_count']} content pixels "
                f"of {render_quality['interior_pixel_count']} interior pixels"
            )
        visual_context_payload["render_quality"] = {
            **render_quality,
            "fallback_screenshot_used": fallback_used,
            "content_crop": crop,
        }
        screenshot = {
            **screenshot,
            "width": render_quality["width"],
            "height": render_quality["height"],
        }
        _write_private_json(visual_context_path, visual_context_payload)
        return screenshot, render_bytes, slope_inspection

    def _prepare_dem(
        self,
        worker_run_id: str,
        dem_refs: tuple[Path, ...],
        cancel_event: threading.Event,
    ) -> Path:
        if len(dem_refs) == 1:
            return dem_refs[0]
        vrt_path = self._run_root(worker_run_id) / "dem_mosaic.vrt"
        operation = self._call(
            "qgis_processing_start",
            {
                "algorithm": "gdal:buildvirtualraster",
                "parameters": {
                    "INPUT": [str(path) for path in dem_refs],
                    "RESOLUTION": 0,
                    "SEPARATE": False,
                    "PROJ_DIFFERENCE": False,
                    "ADD_ALPHA": False,
                    "ASSIGN_CRS": None,
                    "RESAMPLING": 0,
                    "SRC_NODATA": None,
                    "EXTRA": "",
                    "OUTPUT": str(vrt_path),
                },
                "retain_outputs": True,
                "add_to_project": False,
                "allow_main_thread": False,
            },
        )
        self._poll_operation(worker_run_id, _operation_id(operation), cancel_event)
        if not vrt_path.is_file():
            raise _WorkerProcessingFailed("QGIS DEM mosaic output file was not created")
        return vrt_path

    def _poll_operation(
        self,
        worker_run_id: str,
        operation_id: str,
        cancel_event: threading.Event,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.timeout_s
        with self._lock:
            self._active_operations[worker_run_id] = operation_id
        while True:
            if cancel_event.is_set():
                try:
                    self._call(
                        "qgis_operation",
                        {"operation_id": operation_id, "action": "cancel"},
                    )
                finally:
                    raise _WorkerCancelled("QGIS operation cancellation requested")
            status = self._call(
                "qgis_operation",
                {"operation_id": operation_id, "action": "status"},
            )
            state = str(status.get("status", "unknown"))
            if state == "succeeded":
                validation = status.get("validation")
                if isinstance(validation, dict) and validation.get("passed") is False:
                    raise _WorkerProcessingFailed("QGIS output validation failed")
                return status
            if state in {"failed", "cancelled"}:
                if state == "cancelled":
                    raise _WorkerCancelled("QGIS operation was cancelled")
                error = status.get("error")
                detail_parts: list[str] = []
                if isinstance(error, dict) and error.get("message"):
                    detail_parts.append(str(error["message"]))
                issues = (
                    error.get("issues")
                    if isinstance(error, dict)
                    else None
                ) or (
                    status.get("validation", {}).get("issues")
                    if isinstance(status.get("validation"), dict)
                    else None
                )
                if isinstance(issues, list) and issues:
                    detail_parts.append(
                        "issues="
                        + json.dumps(
                            issues[:8],
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                feedback_log = status.get("feedback_log")
                if isinstance(feedback_log, str) and feedback_log.strip():
                    detail_parts.append(
                        "feedback=" + " ".join(feedback_log.split())[-1500:]
                    )
                raise _WorkerProcessingFailed(
                    "; ".join(detail_parts)
                    or "QGIS Processing operation failed"
                )
            if time.monotonic() >= deadline:
                raise QgisMcpTimeout(f"QGIS operation timed out: {operation_id}")
            time.sleep(self.config.poll_interval_s)

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.mcp is None:
            raise QgisMcpUnavailable("QGIS MCP client is not configured")
        return self.mcp.call_tool(tool, arguments)

    def _cleanup_layers(self, layer_ids: list[str]) -> None:
        for layer_id in reversed(layer_ids):
            try:
                self._call("qgis_project_action", {"action": "remove_layer", "layer": layer_id})
            except (QgisMcpError, OSError, ValueError):
                continue

    def _complete_step(self, run: QgisWorkerRun, step_id: str) -> QgisWorkerRun:
        now = self._now_iso()
        steps = [
            step.model_copy(
                update={
                    "status": SpatialWorkflowStepStatus.COMPLETED,
                    "started_at": step.started_at or now,
                    "completed_at": now,
                }
            )
            if step.step_id == step_id
            else step
            for step in run.steps
        ]
        return run.model_copy(update={"steps": steps, "updated_at": now})

    def _fail_run(
        self,
        run: QgisWorkerRun,
        step_id: str,
        code: SpatialAnalysisErrorCode,
        message: str,
        *,
        detail: str | None = None,
        state: SpatialWorkflowState = SpatialWorkflowState.FAILED,
        retryable: bool = False,
    ) -> None:
        now = self._now_iso()
        error = SpatialAnalysisError(
            code=code,
            message=message,
            detail=detail,
            retryable=retryable,
            at_step=step_id,
        )
        steps = [
            step.model_copy(
                update={
                    "status": SpatialWorkflowStepStatus.FAILED,
                    "started_at": step.started_at or now,
                    "completed_at": now,
                    "error": error,
                }
            )
            if step.step_id == step_id
            else step
            for step in run.steps
        ]
        failed = run.model_copy(
            update={
                "state": state,
                "updated_at": now,
                "completed_at": now,
                "processing_status": "cancelled" if state is SpatialWorkflowState.CANCELLED else "failed",
                "render_status": "failed" if code is SpatialAnalysisErrorCode.RENDER_FAILED else run.render_status,
                "steps": steps,
                "error": error,
                "audit_trail": [
                    *run.audit_trail,
                    {
                        "event": "workflow_cancelled" if state is SpatialWorkflowState.CANCELLED else "workflow_failed",
                        "at": now,
                        "error_code": code.value,
                        "at_step": step_id,
                    },
                ],
            }
        )
        self._persist(failed)

    def _validate_source(self, value: str) -> Path:
        try:
            candidate = Path(value).expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise QgisWorkerInputError(
                SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
                "DEM source is unavailable.",
            ) from exc
        if not candidate.is_file():
            raise QgisWorkerInputError(
                SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
                "DEM source is not a file.",
            )
        for root in self.config.source_roots:
            try:
                candidate.relative_to(root.expanduser().resolve(strict=True))
                return candidate
            except (FileNotFoundError, OSError, RuntimeError, ValueError):
                continue
        raise QgisWorkerInputError(
            SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
            "DEM source is outside Scout QGIS worker allowlisted roots.",
        )

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise _WorkerCancelled("QGIS workflow cancellation requested")

    def _persist(self, run: QgisWorkerRun) -> None:
        _write_private_json(self._run_path(run.worker_run_id), run.model_dump(mode="json"))

    def _run_path(self, worker_run_id: str) -> Path:
        return self._run_root(worker_run_id) / "worker_run.json"

    def _run_root(self, worker_run_id: str) -> Path:
        _validate_safe_id(worker_run_id)
        return (self.runs_root / worker_run_id).resolve(strict=False)

    def _recover_interrupted_runs(self) -> None:
        for path in self.runs_root.glob("*/worker_run.json"):
            try:
                run = QgisWorkerRun.model_validate(_read_json(path))
            except (OSError, json.JSONDecodeError, ValidationError):
                continue
            if run.state not in {SpatialWorkflowState.QUEUED, SpatialWorkflowState.RUNNING}:
                continue
            self._fail_run(
                run,
                "backend_handshake",
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "QGIS worker restarted before the workflow reached a terminal state.",
                retryable=True,
            )

    def _now_iso(self) -> str:
        value = self.now_factory()
        if not isinstance(value, datetime):
            value = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def create_qgis_worker_app(
    *,
    config: QgisWorkerConfig | None = None,
    mcp_client: QgisMcpClient | None = None,
) -> FastAPI:
    resolved = config or QgisWorkerConfig.from_env()
    service = QgisWorkerService(config=resolved, mcp_client=mcp_client)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="Scout QGIS Worker", version="0.1", lifespan=lifespan)
    app.state.qgis_worker_service = service

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > resolved.request_max_bytes:
                    return JSONResponse(status_code=413, content={"detail": "request body too large"})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "invalid content-length"})
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > resolved.request_max_bytes:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
        return await call_next(request)

    def authorize(request: Request) -> None:
        if not resolved.auth_token:
            raise HTTPException(status_code=503, detail="QGIS worker authentication is not configured")
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.casefold() != "bearer" or not hmac.compare_digest(supplied, resolved.auth_token):
            raise HTTPException(
                status_code=401,
                detail="QGIS worker authentication failed",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @app.get("/status", dependencies=[Depends(authorize)])
    def worker_status() -> JSONResponse:
        return JSONResponse(
            content=service.status().model_dump(mode="json"),
            headers={"Cache-Control": "no-store", "X-Scout-Runtime-Safety-Truth": "false"},
        )

    @app.get("/capabilities", dependencies=[Depends(authorize)])
    def worker_capabilities() -> JSONResponse:
        return JSONResponse(
            content={
                "schema_version": "scout_qgis_worker_capabilities.v0_1",
                "workflows": [
                    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
                    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
                ],
                "tools": sorted(QGIS_MCP_ALLOWED_TOOLS),
                "algorithms": sorted(QGIS_MCP_ALLOWED_ALGORITHMS),
                "blocked_capabilities": [
                    "arbitrary_python",
                    "shell",
                    "unrestricted_filesystem",
                    "arbitrary_tool_forwarding",
                    "implicit_network_fetch",
                    "plugin_installation",
                ],
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            },
            headers={"Cache-Control": "no-store", "X-Scout-Runtime-Safety-Truth": "false"},
        )

    @app.post(
        "/workflows/terrain_context_preview.v1",
        status_code=202,
        dependencies=[Depends(authorize)],
    )
    @app.post(
        "/workflows/terrain_feature_stack.v1",
        status_code=202,
        dependencies=[Depends(authorize)],
    )
    def start_workflow(request: QgisWorkerWorkflowRequest) -> JSONResponse:
        try:
            run = service.start(request)
        except QgisWorkerInputError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code.value, "message": str(exc)},
            ) from exc
        return JSONResponse(
            status_code=202,
            content=run.model_dump(mode="json"),
            headers={"Cache-Control": "no-store", "X-Scout-Runtime-Safety-Truth": "false"},
        )

    @app.get("/workflows/{worker_run_id}", dependencies=[Depends(authorize)])
    def workflow_state(worker_run_id: str) -> JSONResponse:
        try:
            run = service.get(worker_run_id)
        except (FileNotFoundError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="QGIS worker run not found") from exc
        return JSONResponse(
            content=run.model_dump(mode="json"),
            headers={"Cache-Control": "no-store", "X-Scout-Runtime-Safety-Truth": "false"},
        )

    @app.post("/workflows/{worker_run_id}/cancel", dependencies=[Depends(authorize)])
    def cancel_workflow(worker_run_id: str, requested_by: str = "scout_backend") -> JSONResponse:
        try:
            run = service.cancel(worker_run_id, requested_by=requested_by)
        except (FileNotFoundError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="QGIS worker run not found") from exc
        return JSONResponse(
            content=run.model_dump(mode="json"),
            headers={"Cache-Control": "no-store", "X-Scout-Runtime-Safety-Truth": "false"},
        )

    @app.get(
        "/workflows/{worker_run_id}/artifacts/{artifact_id}",
        dependencies=[Depends(authorize)],
    )
    def workflow_artifact(worker_run_id: str, artifact_id: str) -> FileResponse:
        try:
            artifact, path = service.artifact_path(worker_run_id, artifact_id)
        except (FileNotFoundError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=404, detail="QGIS worker artifact not found") from exc
        return FileResponse(
            path,
            media_type=artifact.media_type,
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"sha256:{artifact.sha256}"',
                "X-Scout-Candidate-Only": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
            },
        )

    return app


def _initial_steps(workflow_id: str = TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID) -> list[SpatialWorkflowStep]:
    if workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID:
        values = (
            ("input_validation", "Input validation", SpatialCapabilityCategory.TERRAIN),
            ("crs_inspection", "CRS inspection", SpatialCapabilityCategory.PROJECT),
            ("route_preparation", "Route preparation", SpatialCapabilityCategory.VECTOR),
            ("dem_loaded", "DEM loaded", SpatialCapabilityCategory.RASTER),
            ("capability_discovery", "GRASS capability discovery", SpatialCapabilityCategory.PROCESSING),
            ("slope_aspect_generated", "Slope and aspect generated", SpatialCapabilityCategory.TERRAIN),
            ("geomorphon_generated", "Multiscale geomorphons generated", SpatialCapabilityCategory.TERRAIN),
            ("ridge_valley_vectorized", "Ridge and valley candidates vectorized", SpatialCapabilityCategory.TERRAIN),
            ("hydrology_generated", "Flow accumulation generated", SpatialCapabilityCategory.HYDROLOGY),
            ("stream_network_extracted", "Stream-network candidate extracted", SpatialCapabilityCategory.HYDROLOGY),
            ("crs_normalized", "CRS metadata normalized", SpatialCapabilityCategory.PROCESSING),
            ("candidate_vectors_exported", "Candidate lines exported for MapLibre", SpatialCapabilityCategory.VECTOR),
            ("route_feature_sampling", "Route terrain features sampled", SpatialCapabilityCategory.TERRAIN),
            ("map_rendered", "Map rendered", SpatialCapabilityCategory.RENDER),
            ("evidence_review_pending", "Evidence review pending", SpatialCapabilityCategory.CARTOGRAPHY),
        )
    else:
        values = (
            ("input_validation", "Input validation", SpatialCapabilityCategory.TERRAIN),
            ("crs_inspection", "CRS inspection", SpatialCapabilityCategory.PROJECT),
            ("route_preparation", "Route preparation", SpatialCapabilityCategory.VECTOR),
            ("dem_loaded", "DEM loaded", SpatialCapabilityCategory.RASTER),
            ("slope_generated", "Slope generated", SpatialCapabilityCategory.PROCESSING),
            ("map_rendered", "Map rendered", SpatialCapabilityCategory.RENDER),
            ("evidence_review_pending", "Evidence review pending", SpatialCapabilityCategory.CARTOGRAPHY),
        )
    return [
        SpatialWorkflowStep(
            step_id=step_id,
            label=label,
            status=SpatialWorkflowStepStatus.PENDING,
            selected_capability=category,
        )
        for step_id, label, category in values
    ]


def _operation_id(value: dict[str, Any]) -> str:
    operation_id = value.get("id") or value.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id:
        raise _WorkerProcessingFailed("QGIS Processing did not return an operation ID")
    return operation_id


def _mcp_failure_code(
    exc: QgisMcpError,
    *,
    current_step: str,
) -> SpatialAnalysisErrorCode:
    if isinstance(exc, QgisMcpUnavailable):
        return SpatialAnalysisErrorCode.MCP_UNAVAILABLE
    message = str(exc).casefold()
    if isinstance(exc, QgisMcpToolError):
        error = exc.payload.get("error")
        data = error.get("data") if isinstance(error, dict) else None
        reason = str(data.get("reason", "")).casefold() if isinstance(data, dict) else ""
        if reason.startswith("registration_") or "bridge registration" in message:
            return SpatialAnalysisErrorCode.QGIS_UNAVAILABLE
    if current_step == "map_rendered":
        return SpatialAnalysisErrorCode.RENDER_FAILED
    return SpatialAnalysisErrorCode.PROCESSING_FAILED


def _artifact(
    worker_run_id: str,
    suffix: str,
    artifact_type: str,
    path: Path,
    media_type: str,
    *,
    width_px: int | None = None,
    height_px: int | None = None,
    visualization_only: bool = False,
) -> QgisWorkerArtifact:
    raw = path.read_bytes()
    return QgisWorkerArtifact(
        artifact_id=f"{worker_run_id}.{suffix}",
        artifact_type=artifact_type,
        relative_ref=path.name,
        media_type=media_type,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_count=len(raw),
        width_px=width_px,
        height_px=height_px,
        visualization_only=visualization_only,
    )


def _decode_screenshot(value: dict[str, Any]) -> bytes:
    encoded = value.get("data")
    if not isinstance(encoded, str) or len(encoded) > 16 * 1024 * 1024:
        raise _WorkerRenderFailed("QGIS screenshot payload is unavailable or too large")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise _WorkerRenderFailed("QGIS screenshot payload is not valid base64") from exc
    if not raw or len(raw) > 12 * 1024 * 1024:
        raise _WorkerRenderFailed("QGIS screenshot bytes are outside the Scout limit")
    expected = value.get("sha256")
    actual = hashlib.sha256(raw).hexdigest()
    if isinstance(expected, str) and expected and not hmac.compare_digest(expected, actual):
        raise _WorkerRenderFailed("QGIS screenshot hash did not match its payload")
    return raw


def _crop_png_to_content(
    raw: bytes,
    *,
    padding_px: int,
) -> tuple[bytes, dict[str, Any]]:
    try:
        width, height, color_type, rows = _decode_png_rows(raw)
    except (ValueError, zlib.error, struct.error) as exc:
        raise _WorkerRenderFailed("QGIS screenshot PNG could not be cropped") from exc
    if width < 3 or height < 3:
        raise _WorkerRenderFailed("QGIS screenshot PNG is too small for review")
    channels = {2: 3, 6: 4}[color_type]
    background = tuple(rows[1][channels : channels * 2])
    content: list[tuple[int, int]] = []
    frame_margin = 2 if width >= 5 and height >= 5 else 1
    for y in range(frame_margin, height - frame_margin):
        row = rows[y]
        for x in range(frame_margin, width - frame_margin):
            offset = x * channels
            pixel = tuple(row[offset : offset + channels])
            if channels == 4 and pixel[3] <= 8:
                continue
            if any(abs(pixel[index] - background[index]) > 12 for index in range(3)):
                content.append((x, y))
    if not content:
        return raw, {
            "applied": False,
            "reason": "no_content_bbox",
            "original_width": width,
            "original_height": height,
            "ignored_frame_margin_px": frame_margin,
            "adds_source_resolution": False,
        }
    left = max(0, min(item[0] for item in content) - padding_px)
    top = max(0, min(item[1] for item in content) - padding_px)
    right = min(width - 1, max(item[0] for item in content) + padding_px)
    bottom = min(height - 1, max(item[1] for item in content) + padding_px)
    cropped_width = right - left + 1
    cropped_height = bottom - top + 1
    if cropped_width == width and cropped_height == height:
        return raw, {
            "applied": False,
            "reason": "content_uses_full_frame",
            "original_width": width,
            "original_height": height,
            "ignored_frame_margin_px": frame_margin,
            "adds_source_resolution": False,
        }
    cropped_rows = [
        row[left * channels : (right + 1) * channels]
        for row in rows[top : bottom + 1]
    ]
    cropped = _encode_png_rows(
        cropped_width,
        cropped_height,
        color_type,
        cropped_rows,
    )
    return cropped, {
        "applied": True,
        "original_width": width,
        "original_height": height,
        "crop_bbox_px": [left, top, right, bottom],
        "cropped_width": cropped_width,
        "cropped_height": cropped_height,
        "ignored_frame_margin_px": frame_margin,
        "resampled": False,
        "adds_source_resolution": False,
    }


def _encode_png_rows(
    width: int,
    height: int,
    color_type: int,
    rows: list[bytes],
) -> bytes:
    channels = {2: 3, 6: 4}[color_type]
    if len(rows) != height or any(len(row) != width * channels for row in rows):
        raise _WorkerRenderFailed("QGIS screenshot crop rows are invalid")

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    scanlines = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(
            "IHDR".encode(),
            struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0),
        )
        + chunk("IDAT".encode(), zlib.compress(scanlines))
        + chunk("IEND".encode(), b"")
    )


def _png_visual_quality(raw: bytes) -> dict[str, Any]:
    try:
        width, height, color_type, rows = _decode_png_rows(raw)
    except (ValueError, zlib.error, struct.error) as exc:
        raise _WorkerRenderFailed("QGIS screenshot PNG could not be inspected") from exc
    if width < 3 or height < 3:
        raise _WorkerRenderFailed("QGIS screenshot PNG is too small for review")
    channels = {2: 3, 6: 4}[color_type]
    background_offset = channels
    background = tuple(rows[1][background_offset : background_offset + channels])
    interior_pixels = (width - 2) * (height - 2)
    content_pixels = 0
    for row in rows[1:-1]:
        for x in range(1, width - 1):
            offset = x * channels
            pixel = tuple(row[offset : offset + channels])
            if channels == 4 and pixel[3] <= 8:
                continue
            if any(abs(pixel[index] - background[index]) > 12 for index in range(3)):
                content_pixels += 1
    required = max(4, math.ceil(interior_pixels * 0.001))
    return {
        "passed": content_pixels >= required,
        "width": width,
        "height": height,
        "background_rgba": list(background),
        "interior_pixel_count": interior_pixels,
        "content_pixel_count": content_pixels,
        "content_ratio": round(content_pixels / interior_pixels, 6),
        "required_content_pixels": required,
    }


def _decode_png_rows(raw: bytes) -> tuple[int, int, int, list[bytes]]:
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    offset = 8
    width = height = bit_depth = color_type = interlace = None
    compressed = bytearray()
    while offset + 12 <= len(raw):
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        if length > 12 * 1024 * 1024 or offset + 12 + length > len(raw):
            raise ValueError("invalid PNG chunk length")
        kind = raw[offset + 4 : offset + 8]
        payload = raw[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if (
        width is None
        or height is None
        or not 1 <= width <= 1600
        or not 1 <= height <= 1600
        or bit_depth != 8
        or color_type not in {2, 6}
        or interlace != 0
    ):
        raise ValueError("unsupported PNG format")
    channels = {2: 3, 6: 4}[color_type]
    row_bytes = width * channels
    expected_bytes = (row_bytes + 1) * height
    decompressor = zlib.decompressobj()
    decoded = decompressor.decompress(bytes(compressed), expected_bytes + 1)
    if len(decoded) > expected_bytes or decompressor.unconsumed_tail:
        raise ValueError("PNG data exceeds the bounded image size")
    decoded += decompressor.flush()
    if len(decoded) != expected_bytes or not decompressor.eof:
        raise ValueError("unexpected PNG data length")
    rows: list[bytes] = []
    cursor = 0
    previous = bytes(row_bytes)
    for _ in range(height):
        filter_type = decoded[cursor]
        cursor += 1
        encoded = decoded[cursor : cursor + row_bytes]
        cursor += row_bytes
        reconstructed = bytearray(row_bytes)
        for index, value in enumerate(encoded):
            left = reconstructed[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = _paeth(left, up, upper_left)
            else:
                raise ValueError("unsupported PNG row filter")
            reconstructed[index] = (value + predictor) & 0xFF
        previous = bytes(reconstructed)
        rows.append(previous)
    return width, height, color_type, rows


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= upper_left_distance:
        return left
    if up_distance <= upper_left_distance:
        return up
    return upper_left


def _extent_values(value: Any, *, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, dict):
        raise _WorkerCrsUnresolved(f"{label} extent is unavailable")
    try:
        xmin, ymin, xmax, ymax = (
            float(value[key]) for key in ("xmin", "ymin", "xmax", "ymax")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _WorkerCrsUnresolved(f"{label} extent is invalid") from exc
    if (
        not all(math.isfinite(item) for item in (xmin, ymin, xmax, ymax))
        or xmin > xmax
        or ymin > ymax
        or (xmin == xmax and ymin == ymax)
    ):
        raise _WorkerCrsUnresolved(f"{label} extent is invalid")
    return xmin, ymin, xmax, ymax


def _validate_projected_route_extent(value: Any) -> None:
    xmin, ymin, xmax, ymax = _extent_values(value, label="Prepared route")
    if (
        max(abs(xmin), abs(xmax)) < 10_000
        or max(abs(ymin), abs(ymax)) < 10_000
        or xmax - xmin > 100_000
        or ymax - ymin > 100_000
    ):
        raise _WorkerCrsUnresolved(
            "Prepared route coordinates do not match bounded projected EPSG:3826 values"
        )


def _require_extent_intersection(route_extent: Any, dem_extent: Any) -> None:
    route_xmin, route_ymin, route_xmax, route_ymax = _extent_values(
        route_extent,
        label="Prepared route",
    )
    dem_xmin, dem_ymin, dem_xmax, dem_ymax = _extent_values(
        dem_extent,
        label="Source DEM",
    )
    if (
        route_xmax < dem_xmin
        or route_xmin > dem_xmax
        or route_ymax < dem_ymin
        or route_ymin > dem_ymax
    ):
        raise _WorkerCrsUnresolved(
            "Prepared route extent does not intersect the source DEM extent"
        )


def _route_line_coordinates(route_geojson: dict[str, Any]) -> list[list[float]]:
    try:
        raw = route_geojson["features"][0]["geometry"]["coordinates"]
    except (KeyError, IndexError, TypeError) as exc:
        raise _WorkerProcessingFailed("QGIS route geometry is unavailable") from exc
    coordinates = [
        [float(value[0]), float(value[1])]
        for value in raw
        if isinstance(value, list) and len(value) >= 2
    ]
    if len(coordinates) < 2:
        raise _WorkerProcessingFailed("QGIS route geometry has fewer than two points")
    return coordinates


def _bounded_route_sample_positions(
    coordinates: list[list[float]],
    *,
    max_samples: int,
) -> list[dict[str, Any]]:
    cumulative = [0.0]
    for start, end in zip(coordinates, coordinates[1:]):
        cumulative.append(
            cumulative[-1] + _haversine_m(start[1], start[0], end[1], end[0])
        )
    if len(coordinates) <= max_samples:
        indices = list(range(len(coordinates)))
    else:
        indices = sorted(
            {
                round(ordinal * (len(coordinates) - 1) / (max_samples - 1))
                for ordinal in range(max_samples)
            }
        )
    denominator = max(1, len(coordinates) - 1)
    return [
        {
            "coordinate": coordinates[index],
            "vertex_index": index,
            "route_fraction": round(index / denominator, 8),
            "distance_m": round(cumulative[index], 2),
        }
        for index in indices
    ]


def _identified_raster_values(payload: dict[str, Any]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    results = payload.get("results")
    if not isinstance(results, list):
        return values
    for result in results:
        if not isinstance(result, dict):
            continue
        layer = result.get("layer")
        layer_id = str(layer.get("id") or "") if isinstance(layer, dict) else ""
        if not layer_id:
            continue
        raster_values = result.get("values")
        values[layer_id] = _first_finite_raster_value(raster_values)
    return values


def _first_finite_raster_value(value: Any) -> float | None:
    candidates = value.values() if isinstance(value, dict) else ()
    for candidate in candidates:
        try:
            number = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _geomorphon_code(value: float | None) -> int | None:
    if value is None:
        return None
    code = int(round(value))
    if abs(value - code) > 0.01 or code not in _GEOMORPHON_LABELS:
        return None
    return code


def _geomorphon_consensus_code(values: tuple[int | None, ...]) -> int | None:
    available = [value for value in values if value is not None]
    for code in sorted(set(available)):
        if available.count(code) >= 2:
            return code
    return None


def _normalize_candidate_terrain_vector_geojson(
    payload: Any,
    *,
    worker_run_id: str,
    vector_name: str,
    kind: str,
    label: str,
    crs_assignment: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise _WorkerProcessingFailed(
            f"QGIS {vector_name} candidate output is not a FeatureCollection"
        )
    features = payload.get("features")
    if not isinstance(features, list) or len(features) > _MAX_CANDIDATE_VECTOR_FEATURES:
        raise _WorkerProcessingFailed(
            f"QGIS {vector_name} candidate feature count is outside the bounded limit"
        )
    normalized: list[dict[str, Any]] = []
    coordinate_count = 0
    for ordinal, feature in enumerate(features):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "LineString",
            "MultiLineString",
        }:
            raise _WorkerProcessingFailed(
                f"QGIS {vector_name} candidate contains non-line geometry"
            )
        coordinate_count += _validate_wgs84_line_geometry(geometry)
        if coordinate_count > 500_000:
            raise _WorkerProcessingFailed(
                f"QGIS {vector_name} candidate contains too many coordinates"
            )
        source_properties = feature.get("properties")
        properties = dict(source_properties) if isinstance(source_properties, dict) else {}
        properties.update(
            {
                "id": f"{worker_run_id}.{vector_name}.{ordinal:05d}",
                "kind": kind,
                "feature_class": kind,
                "label": label,
                "workflow_run_id": worker_run_id,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "risk_score_applied": False,
                "fixture": False,
                "synthetic": False,
                "adds_source_resolution": False,
                "terrain_interpretation_only": True,
                "observed": False,
            }
        )
        if vector_name in {"ridge", "valley"}:
            properties.update(
                {
                    "derivation": "multiscale_geomorphon_consensus",
                    "minimum_scale_votes": 2,
                }
            )
        if vector_name == "stream":
            properties.update(
                {
                    "derivation": (
                        "grass_r_watershed_accumulation_threshold_thin_to_vect"
                    ),
                    "water_presence_confirmed": False,
                    "outside_region_flow_may_be_underestimated": True,
                }
            )
        normalized.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": properties,
            }
        )
    return {
        "type": "FeatureCollection",
        "metadata": {
            "schema_version": "scout_qgis_candidate_terrain_vector.v0_1",
            "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
            "workflow_run_id": worker_run_id,
            "vector_name": vector_name,
            "feature_count": len(normalized),
            "coordinate_count": coordinate_count,
            "crs": "EPSG:4326",
            "source_file_crs": "UNKNOWN",
            "source_runtime_crs_assignment": crs_assignment,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "risk_score_applied": False,
            "fixture": False,
            "synthetic": False,
            "adds_source_resolution": False,
            "interpretation": (
                "DEM-derived terrain morphology candidate only; not observed route, "
                "water, navigability, hazard, or safety truth."
            ),
        },
        "features": normalized,
    }


def _validate_wgs84_line_geometry(geometry: dict[str, Any]) -> int:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    lines = [coordinates] if geometry_type == "LineString" else coordinates
    if not isinstance(lines, list) or not lines:
        raise _WorkerProcessingFailed("Candidate terrain line geometry is empty")
    coordinate_count = 0
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            raise _WorkerProcessingFailed("Candidate terrain line has too few coordinates")
        for coordinate in line:
            if not isinstance(coordinate, list) or len(coordinate) < 2:
                raise _WorkerProcessingFailed("Candidate terrain coordinate is malformed")
            try:
                lon, lat = float(coordinate[0]), float(coordinate[1])
            except (TypeError, ValueError) as exc:
                raise _WorkerProcessingFailed(
                    "Candidate terrain coordinate is not numeric"
                ) from exc
            if (
                not math.isfinite(lon)
                or not math.isfinite(lat)
                or not -180 <= lon <= 180
                or not -90 <= lat <= 90
            ):
                raise _WorkerProcessingFailed(
                    "Candidate terrain coordinate is outside EPSG:4326"
                )
            coordinate_count += 1
    return coordinate_count


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _maplibre_result(
    route_geojson: dict[str, Any],
    worker_run_id: str,
    project_id: str,
    corridor_m: float,
    slope_artifact_id: str,
    *,
    route_samples_geojson: dict[str, Any] | None = None,
    route_samples_artifact_id: str | None = None,
    candidate_vector_geojsons: dict[str, tuple[dict[str, Any], str]] | None = None,
) -> dict[str, Any]:
    coordinates = route_geojson["features"][0]["geometry"]["coordinates"]
    route = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": {
            "id": f"{worker_run_id}.route",
            "kind": "qgis_candidate_route",
            "feature_class": "qgis_candidate_route",
            "label": "QGIS candidate route context",
            "project_id": project_id,
            "workflow_run_id": worker_run_id,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": False,
            "synthetic": False,
        },
    }
    lons = [float(value[0]) for value in coordinates]
    lats = [float(value[1]) for value in coordinates]
    padding = max(0.0001, float(corridor_m) / 111_320.0)
    west, east = min(lons) - padding, max(lons) + padding
    south, north = min(lats) - padding, max(lats) + padding
    coverage = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
        },
        "properties": {
            "id": f"{worker_run_id}.slope_coverage",
            "kind": "qgis_slope_candidate",
            "feature_class": "qgis_slope_candidate",
            "label": "QGIS slope artifact coverage binding",
            "project_id": project_id,
            "workflow_run_id": worker_run_id,
            "artifact_id": slope_artifact_id,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "visualization_only": True,
            "fixture": False,
            "synthetic": False,
            "adds_source_resolution": False,
        },
    }
    sample_features: list[dict[str, Any]] = []
    if isinstance(route_samples_geojson, dict):
        for feature in route_samples_geojson.get("features") or []:
            if not isinstance(feature, dict):
                continue
            properties = dict(feature.get("properties") or {})
            properties["artifact_id"] = route_samples_artifact_id
            sample_features.append({**feature, "properties": properties})
    candidate_vector_features: list[dict[str, Any]] = []
    for payload, artifact_id in (candidate_vector_geojsons or {}).values():
        for feature in payload.get("features") or []:
            if not isinstance(feature, dict):
                continue
            properties = dict(feature.get("properties") or {})
            properties["artifact_id"] = artifact_id
            candidate_vector_features.append({**feature, "properties": properties})
    return {
        "type": "FeatureCollection",
        "features": [
            coverage,
            *candidate_vector_features,
            route,
            *sample_features,
        ],
        "properties": {
            "schema_version": "scout_qgis_maplibre_geojson.v0_1",
            "workflow_run_id": worker_run_id,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": False,
            "synthetic": False,
        },
    }


def _mcp_command_from_env() -> tuple[str, ...] | None:
    configured = _env_str("SCOUT_QGIS_MCP_COMMAND_JSON")
    if configured:
        try:
            value = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise ValueError("SCOUT_QGIS_MCP_COMMAND_JSON must be valid JSON") from exc
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError("SCOUT_QGIS_MCP_COMMAND_JSON must be a non-empty string array")
        return tuple(value)
    launcher = Path.home() / ".qgis-mcp" / "bin" / "qgis_mcp_launcher.py"
    if launcher.is_file():
        return (str(launcher),)
    executable = shutil.which("qgis-mcp")
    return (executable,) if executable else None


def _nested_value(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_text(value: dict[str, Any], path: tuple[str, ...]) -> str | None:
    candidate = _nested_value(value, path)
    return str(candidate) if candidate not in {None, ""} else None


def _find_version(value: Any, keyword: str) -> str:
    if isinstance(value, dict):
        for key, candidate in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if keyword in normalized and "version" in normalized and candidate:
                return str(candidate)
        for candidate in value.values():
            result = _find_version(candidate, keyword)
            if result != "unavailable":
                return result
    elif isinstance(value, list):
        for candidate in value:
            result = _find_version(candidate, keyword)
            if result != "unavailable":
                return result
    return "unavailable"


def _mcp_version(client: QgisMcpClient | None) -> str:
    if client is None:
        return "unavailable"
    value = getattr(client, "server_version", "unavailable")
    return str(value) if value else "unavailable"


def _validate_safe_id(value: str) -> None:
    if not value or len(value) > 160 or value[0] not in _SAFE_ID_CHARS or any(
        char not in _SAFE_ID_CHARS for char in value
    ):
        raise ValueError("invalid QGIS worker identifier")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_private_json(path: Path, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    _write_private_bytes(path, data)


def _write_private_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("xb") as stream:
        os.chmod(temporary, 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().casefold() in {"1", "true", "yes", "on"}


def _env_str(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _env_float(name: str, default: float, floor: float, ceiling: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(ceiling, max(floor, value))


def _env_int(name: str, default: int, floor: int, ceiling: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(ceiling, max(floor, value))
