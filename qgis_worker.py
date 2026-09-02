from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import platform
import re
import shutil
import struct
import subprocess
import threading
import time
import zlib
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from navigation_terrain_coordinates import twd97_to_wgs84
from pretrip_source_ingest import wgs84_to_twd97
from qgis_mcp_stdio import (
    QGIS_MCP_ALLOWED_ALGORITHMS,
    QGIS_MCP_ALLOWED_TOOLS,
    QGIS_MCP_FLOW_CHANNEL_CANDIDATE_EXPRESSION,
    QGIS_MCP_GEOMORPHON_RIDGE_CONSENSUS_EXPRESSION,
    QGIS_MCP_GEOMORPHON_VALLEY_CONSENSUS_EXPRESSION,
    QGIS_MCP_TERRAIN_LINE_MIN_LENGTH_EXPRESSION,
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
    TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
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
from terrain_route_hypothesis import default_route_unknowns, resolution_confidence_limits
from terrain_route_hypothesis_artifacts import (
    TERRAIN_ROUTE_CORRIDOR_SEMANTICS,
    TERRAIN_ROUTE_PROVENANCE_REVISION,
    TERRAIN_ROUTE_VISUALIZATION_REVISION,
    build_corridor_threshold_expression,
    build_drainage_pressure_expression,
    build_guidance_friction_expression,
    build_live_terrain_route_cache_keys,
    build_path_outside_band_expression,
    build_profile_friction_expression,
    build_relative_corridor_expression,
    build_slope_friction_expression,
    build_terrain_route_resolution_identity,
    build_terrain_route_source_identity,
)
from terrain_route_hypothesis_models import (
    TERRAIN_ROUTE_BAND_MODEL,
    TERRAIN_ROUTE_GUIDED_PATH_SEMANTICS,
    TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
    TERRAIN_ROUTE_PATH_MODEL,
    TERRAIN_ROUTE_PATH_SEMANTICS,
    CandidateCorridorBand,
    GeoJsonLineString,
    GeoPoint,
    RouteEvidence,
    RouteEvidencePolarity,
    TerrainHypothesisMetrics,
    TerrainHypothesisProvenance,
    TerrainRasterReference,
    TerrainRouteCandidateCorridor,
    TerrainRouteAlternativeProfile,
    TerrainRouteHypothesis,
    TerrainRouteHypothesisRun,
    TerrainRouteRunStatus,
    TerrainRouteStrategy,
)


_TERMINAL_STATES = {
    SpatialWorkflowState.COMPLETED,
    SpatialWorkflowState.FAILED,
    SpatialWorkflowState.CANCELLED,
}
_GRASS_TERRAIN_FEATURE_SCHEMAS = {
    "grass:r.contour": {
        "required_parameters": frozenset({"input", "output"}),
        "output_parameters": ("output",),
    },
    "grass:r.relief": {
        "required_parameters": frozenset({"input", "output"}),
        "output_parameters": ("output",),
    },
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
_GRASS_TERRAIN_ROUTE_SCHEMAS = {
    "grass:r.slope.aspect": {
        "required_parameters": frozenset({"elevation", "slope", "aspect"}),
        "output_parameters": ("slope", "aspect"),
    },
    "grass:r.mapcalc.simple": {
        "required_parameters": frozenset({"a", "expression", "output"}),
        "output_parameters": ("output",),
    },
    "grass:r.walk.coords": {
        "required_parameters": frozenset(
            {"elevation", "friction", "start_coordinates", "output", "outdir"}
        ),
        "output_parameters": ("output", "outdir"),
    },
    "grass:r.cost": {
        "required_parameters": frozenset(
            {"input", "start_coordinates", "output", "outdir"}
        ),
        "output_parameters": ("output", "outdir"),
    },
    "grass:r.path": {
        "required_parameters": frozenset(
            {"input", "start_points", "raster_path", "vector_path"}
        ),
        "output_parameters": ("raster_path", "vector_path"),
    },
    "grass:r.quantile": {
        "required_parameters": frozenset({"input", "percentiles", "file"}),
        "output_parameters": ("file",),
    },
    "grass:r.univar": {
        "required_parameters": frozenset({"map", "output"}),
        "output_parameters": ("output",),
    },
    "grass:r.watershed": {
        "required_parameters": frozenset({"elevation", "accumulation"}),
        "output_parameters": ("accumulation",),
    },
}
_TERRAIN_FEATURE_NORMALIZATION_SCHEMAS = {
    "gdal:buildvirtualraster": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "OUTPUT"}),
        "output_parameters": ("OUTPUT",),
    },
    "native:dissolve": {
        "provider": "native",
        "required_parameters": frozenset(
            {"INPUT", "FIELD", "SEPARATE_DISJOINT", "OUTPUT"}
        ),
        "output_parameters": ("OUTPUT",),
    },
    "native:extractbyexpression": {
        "provider": "native",
        "required_parameters": frozenset({"INPUT", "EXPRESSION", "OUTPUT"}),
        "output_parameters": ("OUTPUT",),
    },
    "gdal:assignprojection": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "CRS"}),
        "output_parameters": (),
    },
    "gdal:cliprasterbyextent": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "PROJWIN", "OUTPUT"}),
        "output_parameters": ("OUTPUT",),
    },
    "gdal:colorrelief": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "COLOR_TABLE", "OUTPUT"}),
        "output_parameters": ("OUTPUT",),
    },
    "gdal:rasterize": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "EXTENT", "OUTPUT"}),
        "output_parameters": ("OUTPUT",),
    },
    "gdal:warpreproject": {
        "provider": "gdal",
        "required_parameters": frozenset({"INPUT", "TARGET_CRS", "OUTPUT"}),
        "output_parameters": ("OUTPUT",),
    },
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
_MAX_TERRAIN_SURFACE_CELLS = 4_000_000
_MAX_TERRAIN_SURFACE_DIMENSION = 4096
_TERRAIN_CONTOUR_INTERVAL_M = 100.0
_MAX_TERRAIN_ROUTE_PATH_COORDINATES = 20_000
_MAX_TERRAIN_ROUTE_METRIC_SAMPLES = 80
_TERRAIN_ROUTE_CORRIDOR_COLORS = {
    5.0: "nv 0 0 0 0\n0 0 0 0 0\n1 23 144 125 155\n",
    10.0: "nv 0 0 0 0\n0 0 0 0 0\n1 36 112 177 130\n",
    20.0: "nv 0 0 0 0\n0 0 0 0 0\n1 217 139 37 105\n",
}
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
_ELEVATION_COLOR_RELIEF = """nv 0 0 0 0
0 23 92 52 190
500 39 132 73 190
1000 91 161 83 190
1500 186 193 99 190
2000 226 169 84 190
2500 211 112 63 190
3000 167 65 55 190
4000 121 36 53 210
"""
_SLOPE_COLOR_RELIEF = """nv 0 0 0 0
0 183 228 168 200
10 217 239 139 205
20 254 224 139 210
30 253 174 97 215
40 244 109 67 220
50 190 48 65 225
90 104 24 64 230
"""
_HILLSHADE_COLOR_RELIEF = """nv 0 0 0 0
0 18 24 28 205
64 72 80 82 185
128 145 151 145 155
192 213 214 197 120
255 255 255 240 75
"""
_CONTOUR_COLOR_RELIEF = """nv 0 0 0 0
0 0 0 0 0
254 247 246 234 0
255 247 246 234 225
"""


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


class _WorkerTerrainRouteUnavailable(RuntimeError):
    def __init__(self, code: SpatialAnalysisErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        if qgis_version == "unavailable":
            qgis_version = _bridge_qgis_version()
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
                        else "terrain_route_hypothesis"
                        if request.workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
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
        if request.workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID:
            self._execute_terrain_route_hypothesis(
                queued,
                request,
                dem_refs,
                cancel_event,
            )
            return
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
        projected_route_path = run_root / "route_epsg3826.gpkg"
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
            projected_route_layer_name = str(route_export.get("layer_name") or "")
            if (
                not projected_route_path.is_file()
                or Path(exported_path).resolve(strict=False)
                != projected_route_path.resolve(strict=False)
                or int(route_export.get("feature_count", -1)) != 1
                or not projected_route_layer_name.startswith(
                    "Scout candidate route source "
                )
            ):
                raise _WorkerProcessingFailed(
                    "QGIS did not export exactly one projected route feature"
                )
            self._call(
                "qgis_project_action",
                {"action": "remove_layer", "layer": source_route_layer_id},
            )
            route_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": (
                        f"{projected_route_path}|layername="
                        f"{projected_route_layer_name}"
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
            self._call(
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
                    "Prepared route CRS is unresolved or unsupported: "
                    f"{prepared_route_crs}"
                )
            _validate_projected_route_extent(prepared_route_summary.get("extent"))
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "dem_loaded"
            (
                dem_input,
                dem_normalized_source_count,
                dem_normalization_resolution_m,
                dem_analysis_extent,
            ) = self._prepare_dem(
                run.worker_run_id,
                dem_refs,
                request.source_resolution,
                prepared_route_summary.get("extent"),
                request.corridor_m,
                cancel_event,
            )
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
                        "source": (
                            f"{projected_route_path}|layername="
                            f"{projected_route_layer_name}"
                        ),
                        "name": f"Scout candidate route {run.worker_run_id[-10:]}",
                        "provider": "ogr",
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
                self._call(
                    "qgis_crs",
                    {
                        "action": "assign_layer",
                        "layer": route_layer_id,
                        "target": "EPSG:3826",
                        "value": "EPSG:3826",
                    },
                )
            self._call(
                "qgis_style_apply",
                {
                    "layer": route_layer_id,
                    "mode": "simple",
                    "color": "#ff365e",
                    "opacity": 1.0,
                    "width": 2.4,
                },
            )
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
            self._call("qgis_canvas", {"action": "refresh"})
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
            render_bytes, crop = _crop_png_to_content(
                render_bytes,
                padding_px=12,
            )
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
                processing_algorithms=[
                    *(
                        ["gdal:warpreproject"]
                        if dem_normalized_source_count
                        else []
                    ),
                    *(["gdal:buildvirtualraster"] if len(dem_refs) > 1 else []),
                    "gdal:cliprasterbyextent",
                    "gdal:assignprojection",
                    "gdal:slope",
                ],
                processing_parameters={
                    "dem_source_count": len(dem_refs),
                    "analysis_extent": dem_analysis_extent,
                    "python_dtm_processing_used": False,
                    "source_orientation_normalization": {
                        "applied": bool(dem_normalized_source_count),
                        "source_count": dem_normalized_source_count,
                        "algorithm": (
                            "gdal:warpreproject"
                            if dem_normalized_source_count
                            else None
                        ),
                        "source_crs": (
                            "EPSG:3826" if dem_normalized_source_count else None
                        ),
                        "target_crs": (
                            "EPSG:3826" if dem_normalized_source_count else None
                        ),
                        "target_resolution_m": dem_normalization_resolution_m,
                        "resampling": (
                            "nearest" if dem_normalized_source_count else None
                        ),
                        "adds_source_resolution": False,
                    },
                    "slope_band": 1,
                    "slope_scale": 1.0,
                    "as_percent": False,
                    "compute_edges": True,
                    "zevenbergen": False,
                    "corridor_m": request.corridor_m,
                },
                warnings=[
                    *(
                        [
                            "Allowlisted QGIS GDAL Warp normalized south-up XYZ DEM row orientation to north-up GeoTIFF without adding source resolution."
                        ]
                        if dem_normalized_source_count
                        else []
                    ),
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
        except _WorkerCrsUnresolved as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.CRS_UNRESOLVED,
                "QGIS route CRS could not be resolved.",
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

    def _execute_terrain_route_hypothesis(
        self,
        queued: QgisWorkerRun,
        request: QgisWorkerWorkflowRequest,
        dem_refs: tuple[Path, ...],
        cancel_event: threading.Event,
    ) -> None:
        run = queued
        run_root = self._run_root(run.worker_run_id)
        route_path = run_root / "terrain_route_endpoints.geojson"
        projected_route_path = run_root / "terrain_route_endpoints_epsg3826.gpkg"
        destination_path = run_root / "terrain_route_destination.geojson"
        projected_destination_path = run_root / "terrain_route_destination_epsg3826.gpkg"
        project_path = run_root / "terrain_route_hypothesis.qgz"
        dem_stats_path = run_root / "dem_univar.html"
        slope_path = run_root / "terrain_route_slope.tif"
        aspect_path = run_root / "terrain_route_aspect.tif"
        slope_friction_path = run_root / "terrain_route_slope_friction.tif"
        flow_accumulation_path = run_root / "terrain_route_flow_accumulation.tif"
        drainage_pressure_path = run_root / "terrain_route_drainage_pressure.tif"
        cost_a_path = run_root / "terrain_route_cost_from_a.tif"
        direction_a_path = run_root / "terrain_route_cost_direction_from_a.tif"
        cost_b_path = run_root / "terrain_route_cost_from_b.tif"
        direction_b_path = run_root / "terrain_route_cost_direction_from_b.tif"
        path_geojson_path = run_root / "terrain_route_best_path.geojson"
        corridor_path = run_root / "terrain_route_relative_corridor.tif"
        corridor_stats_path = run_root / "terrain_route_corridor_univar.html"
        quantiles_path = run_root / "terrain_route_corridor_quantiles.html"
        hypothesis_path = run_root / "terrain_route_hypothesis.json"
        manifest_path = run_root / "terrain_route_processing_manifest.json"
        added_layers: list[str] = []
        processing_invocations: list[dict[str, Any]] = []
        guidance_execution = request.terrain_route_guidance_execution_plan
        route_profiles = list(
            request.terrain_routing_cost_config.alternative_profiles
        )
        if guidance_execution is not None:
            route_profiles.append(
                TerrainRouteAlternativeProfile(
                    candidate_id="R4",
                    label="R4 reviewed historical-guidance terrain hypothesis",
                    strategy=TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED,
                    drainage_penalty_multiplier=1.5,
                )
            )
        route_profiles = tuple(route_profiles)
        corridor_profile = next(
            profile for profile in route_profiles if profile.corridor_profile
        )
        profile_outputs: dict[str, dict[str, Path]] = {}
        for profile in route_profiles:
            suffix = "" if profile.corridor_profile else f"_{profile.candidate_id.lower()}"
            profile_outputs[profile.candidate_id] = {
                "friction": run_root / f"terrain_route_friction{suffix}.tif",
                "walk_cost": run_root / f"terrain_route_walk_cost_from_a{suffix}.tif",
                "walk_direction": run_root
                / f"terrain_route_walk_direction_from_a{suffix}.tif",
                "path_raster": run_root / f"terrain_route_best_path{suffix}.tif",
                "path_projected": run_root
                / f"terrain_route_best_path_epsg3826{suffix}.gpkg",
                "path_geojson": run_root
                / f"terrain_route_best_path_{profile.candidate_id.lower()}.geojson",
            }
        primary_outputs = profile_outputs[corridor_profile.candidate_id]
        friction_path = primary_outputs["friction"]
        walk_cost_path = primary_outputs["walk_cost"]
        walk_direction_path = primary_outputs["walk_direction"]
        path_raster_path = primary_outputs["path_raster"]
        current_step = "input_validation"

        def process(
            algorithm: str,
            parameters: dict[str, Any],
            *outputs: Path,
        ) -> dict[str, Any]:
            processing_invocations.append(
                {
                    "sequence": len(processing_invocations) + 1,
                    "algorithm": algorithm,
                    "parameters": _bounded_processing_manifest_parameters(
                        parameters
                    ),
                }
            )
            return self._run_processing_outputs(
                worker_run_id=run.worker_run_id,
                algorithm=algorithm,
                parameters=parameters,
                output_paths=tuple(outputs),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )

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
            endpoints_geojson, start_wgs84, destination_wgs84 = (
                _terrain_route_endpoint_geojson(request.route_geojson)
            )
            source_dem_hashes = _verified_terrain_route_dem_hashes(
                request,
                dem_refs,
            )
            parent_manifest_ref = _parent_terrain_manifest_ref(
                request.source_refs,
                request.source_hashes,
            )
            cache_source_identity = build_terrain_route_source_identity(
                dem_sha256s=source_dem_hashes,
                parent_manifest_sha256=request.source_hashes[parent_manifest_ref],
            )
            cache_keys = build_live_terrain_route_cache_keys(
                source_hashes=cache_source_identity,
                source_resolution=build_terrain_route_resolution_identity(
                    request.source_resolution
                ),
                route_coordinates=(start_wgs84, destination_wgs84),
                analysis_margin_m=request.corridor_m,
                cost_config=request.terrain_routing_cost_config,
                guidance_review_sha256=(
                    guidance_execution.guidance_review_sha256
                    if guidance_execution is not None
                    else None
                ),
            )
            if (
                request.terrain_route_cache_keys is not None
                and request.terrain_route_cache_keys != cache_keys
            ):
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.INVALID_INPUT,
                    "Terrain route cache keys do not match the submitted inputs.",
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
                        f"Generate {len(route_profiles)} candidate-only terrain route hypothesis alternatives from explicit "
                        "A/B endpoints, including drainage-averse, balanced, and terrain-only "
                        "profiles. When a reviewed R4 execution plan is present, run its "
                        "ordered point anchors as piecewise GRASS segments. Use the fixed "
                        "allowlisted GRASS recipe; do not infer "
                        "a trail, safety, passage, legal access, or operational route truth."
                    ),
                    "budget_bytes": 8192,
                    "detail": "summary",
                    "tool_limit": 5,
                    "runtime_mode": "include",
                },
            )
            snapshot = context.get("snapshot")
            if isinstance(snapshot, dict) and snapshot.get("available") is False:
                raise QgisMcpUnavailable("QGIS application/plugin bridge is unavailable")
            qgis_version = _find_version(session_snapshot, "qgis")
            if qgis_version == "unavailable":
                qgis_version = _find_version(context, "qgis")
            qgis_version_source = "qgis_session_or_context"
            grass_version = _find_version(session_snapshot, "grass")
            if grass_version == "unavailable":
                grass_version = _find_version(context, "grass")
            grass_version_source = "qgis_session_or_context"
            if grass_version == "unavailable":
                grass_version = _host_grass_version()
                grass_version_source = "bounded_host_cli_probe"
            if qgis_version == "unavailable":
                qgis_version = _bridge_qgis_version()
                qgis_version_source = "qgis_bridge_registration"
            mcp_version = _nested_text(
                initialized, ("serverInfo", "version")
            ) or _mcp_version(self.mcp)
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "endpoint_preparation"
            _write_private_json(route_path, endpoints_geojson)
            route_source = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": str(route_path),
                    "name": f"Scout candidate route source {run.worker_run_id[-10:]}",
                },
            )
            route_source_layer_id = str(
                route_source.get("id") or route_source.get("layer_id") or ""
            )
            if not route_source_layer_id:
                raise _WorkerProcessingFailed(
                    "QGIS did not return a terrain route endpoint layer ID"
                )
            added_layers.append(route_source_layer_id)
            route_export = self._call(
                "qgis_vector_export",
                {
                    "layer": route_source_layer_id,
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
            route_layer_name = str(route_export.get("layer_name") or "")
            if (
                not projected_route_path.is_file()
                or int(route_export.get("feature_count", -1)) != 1
                or not route_layer_name.startswith("Scout candidate route source ")
            ):
                raise _WorkerProcessingFailed(
                    "QGIS did not export one projected A/B endpoint line"
                )
            self._call(
                "qgis_project_action",
                {"action": "remove_layer", "layer": route_source_layer_id},
            )
            route_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": f"{projected_route_path}|layername={route_layer_name}",
                    "name": f"Scout candidate route {run.worker_run_id[-10:]}",
                    "provider": "ogr",
                },
            )
            route_layer_id = str(
                route_layer.get("id") or route_layer.get("layer_id") or ""
            )
            if not route_layer_id:
                raise _WorkerProcessingFailed(
                    "QGIS did not return a projected A/B endpoint line layer"
                )
            added_layers.append(route_layer_id)
            self._call(
                "qgis_crs",
                {
                    "action": "assign_layer",
                    "layer": route_layer_id,
                    "target": "EPSG:3826",
                    "value": "EPSG:3826",
                },
            )
            route_inspection = self._call(
                "qgis_layer_inspect",
                {
                    "layer": route_layer_id,
                    "include": ["metadata"],
                    "sample_limit": 0,
                },
            )
            route_summary = route_inspection.get("summary") or {}
            route_crs = str(route_summary.get("crs") or "UNKNOWN").upper()
            if route_crs not in {"3826", "EPSG:3826"}:
                raise _WorkerCrsUnresolved(
                    f"Terrain route endpoint CRS is unresolved: {route_crs}"
                )
            _validate_projected_route_extent(route_summary.get("extent"))

            _write_private_json(
                destination_path,
                _terrain_route_destination_geojson(destination_wgs84),
            )
            destination_source = self._call(
                "qgis_project_action",
                {
                    "action": "add_vector",
                    "source": str(destination_path),
                    "name": (
                        f"Scout candidate route source destination "
                        f"{run.worker_run_id[-10:]}"
                    ),
                },
            )
            destination_source_id = str(
                destination_source.get("id")
                or destination_source.get("layer_id")
                or ""
            )
            if not destination_source_id:
                raise _WorkerProcessingFailed(
                    "QGIS did not return a destination point layer ID"
                )
            added_layers.append(destination_source_id)
            destination_export = self._call(
                "qgis_vector_export",
                {
                    "layer": destination_source_id,
                    "path": str(projected_destination_path),
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
            if (
                not projected_destination_path.is_file()
                or int(destination_export.get("feature_count", -1)) != 1
            ):
                raise _WorkerProcessingFailed(
                    "QGIS did not export one projected destination point"
                )
            start_x, start_y = wgs84_to_twd97(start_wgs84[1], start_wgs84[0])
            destination_x, destination_y = wgs84_to_twd97(
                destination_wgs84[1], destination_wgs84[0]
            )
            start_coordinate = (
                f"{_compact_number(start_x)},{_compact_number(start_y)}"
            )
            destination_coordinate = (
                f"{_compact_number(destination_x)},{_compact_number(destination_y)}"
            )
            guidance_projected_point_paths: dict[str, Path] = {}
            guidance_projected_coordinates: dict[str, tuple[float, float]] = {}
            if guidance_execution is not None:
                for anchor_index, anchor in enumerate(
                    guidance_execution.anchors,
                    start=1,
                ):
                    anchor_slug = f"{anchor_index:02d}_{anchor.constraint_id.lower()}"
                    anchor_source_path = (
                        run_root / f"terrain_route_guidance_anchor_{anchor_slug}.geojson"
                    )
                    anchor_projected_path = (
                        run_root
                        / f"terrain_route_guidance_anchor_{anchor_slug}_epsg3826.gpkg"
                    )
                    _write_private_json(
                        anchor_source_path,
                        _terrain_route_destination_geojson(
                            (anchor.point.x, anchor.point.y)
                        ),
                    )
                    anchor_source = self._call(
                        "qgis_project_action",
                        {
                            "action": "add_vector",
                            "source": str(anchor_source_path),
                            "name": (
                                "Scout candidate route source guidance "
                                f"{anchor.constraint_id} {run.worker_run_id[-10:]}"
                            ),
                        },
                    )
                    anchor_source_id = str(
                        anchor_source.get("id")
                        or anchor_source.get("layer_id")
                        or ""
                    )
                    if not anchor_source_id:
                        raise _WorkerProcessingFailed(
                            "QGIS did not return a reviewed guidance anchor layer ID"
                        )
                    added_layers.append(anchor_source_id)
                    anchor_export = self._call(
                        "qgis_vector_export",
                        {
                            "layer": anchor_source_id,
                            "path": str(anchor_projected_path),
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
                    if (
                        not anchor_projected_path.is_file()
                        or int(anchor_export.get("feature_count", -1)) != 1
                    ):
                        raise _WorkerProcessingFailed(
                            "QGIS did not export one reviewed guidance anchor point"
                        )
                    anchor_x, anchor_y = wgs84_to_twd97(
                        anchor.point.y,
                        anchor.point.x,
                    )
                    guidance_projected_point_paths[
                        anchor.constraint_id
                    ] = anchor_projected_path
                    guidance_projected_coordinates[
                        anchor.constraint_id
                    ] = (anchor_x, anchor_y)
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "dem_loaded"
            (
                dem_input,
                dem_normalized_source_count,
                dem_normalization_resolution_m,
                dem_analysis_extent,
            ) = self._prepare_dem(
                run.worker_run_id,
                dem_refs,
                request.source_resolution,
                route_summary.get("extent"),
                request.corridor_m,
                cancel_event,
            )
            dem_resolution_m = float(dem_analysis_extent["resolution_m"])
            if (
                dem_resolution_m
                > request.terrain_routing_cost_config.max_dem_resolution_m
            ):
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.DEM_RESOLUTION_TOO_LOW,
                    (
                        f"DEM resolution {dem_resolution_m}m exceeds the "
                        "terrain-route model limit."
                    ),
                )
            dem_layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_raster",
                    "source": str(dem_input),
                    "name": f"Scout source DEM {run.worker_run_id[-10:]}",
                },
            )
            dem_layer_id = str(dem_layer.get("id") or dem_layer.get("layer_id") or "")
            if not dem_layer_id:
                raise _WorkerCrsUnresolved("QGIS did not return a terrain route DEM layer")
            added_layers.append(dem_layer_id)
            dem_inspection = self._call(
                "qgis_layer_inspect",
                {
                    "layer": dem_layer_id,
                    "include": ["metadata", "statistics"],
                    "sample_limit": 0,
                },
            )
            dem_summary = dem_inspection.get("summary") or {}
            dem_crs = str(dem_summary.get("crs") or "UNKNOWN").upper()
            if dem_crs not in {"3826", "EPSG:3826"}:
                raise _WorkerCrsUnresolved(
                    f"Terrain route DEM CRS is unresolved: {dem_crs}"
                )
            dem_analysis_extent = _terrain_route_raster_analysis_extent(
                dem_analysis_extent,
                dem_summary,
            )
            _require_route_endpoints_inside_extent(
                (start_x, start_y),
                (destination_x, destination_y),
                dem_summary.get("extent"),
            )
            for anchor in (
                guidance_execution.anchors if guidance_execution is not None else ()
            ):
                projected_anchor = guidance_projected_coordinates[
                    anchor.constraint_id
                ]
                _require_route_endpoints_inside_extent(
                    projected_anchor,
                    projected_anchor,
                    dem_summary.get("extent"),
                )
            process(
                "grass:r.univar",
                {
                    "map": [str(dem_input)],
                    "zones": None,
                    "percentile": "",
                    "separator": "pipe",
                    "-e": False,
                    "output": str(dem_stats_path),
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                },
                dem_stats_path,
            )
            dem_stats = _parse_grass_univar_report(dem_stats_path)
            if int(dem_stats.get("null_cells", 0)) > 0:
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.NODATA_PRESENT,
                    "The bounded terrain route DEM contains NoData cells.",
                )
            if int(dem_stats.get("n", 0)) != int(
                dem_analysis_extent["cell_count"]
            ):
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
                    "The bounded terrain route DEM cell inventory is incomplete.",
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
                    "QGIS temporary terrain route project was not saved"
                )
            discovered = self._discover_grass_terrain_route_capabilities()
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "slope_friction_generated"
            process(
                "grass:r.slope.aspect",
                {
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
                slope_path,
                aspect_path,
            )
            friction_expression = build_slope_friction_expression(
                request.terrain_routing_cost_config
            )
            process(
                "grass:r.mapcalc.simple",
                {
                    "a": str(slope_path),
                    "expression": friction_expression,
                    "output": str(slope_friction_path),
                },
                slope_friction_path,
            )
            process(
                "grass:r.watershed",
                {
                    "elevation": str(dem_input),
                    "threshold": 25,
                    "convergence": 5,
                    "memory": 256,
                    "-s": False,
                    "-m": True,
                    "-4": False,
                    "-a": False,
                    "-b": False,
                    "accumulation": str(flow_accumulation_path),
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                },
                flow_accumulation_path,
            )
            drainage_pressure_expression = build_drainage_pressure_expression(
                dem_resolution_m
            )
            process(
                "grass:r.mapcalc.simple",
                {
                    "a": str(flow_accumulation_path),
                    "expression": drainage_pressure_expression,
                    "output": str(drainage_pressure_path),
                },
                drainage_pressure_path,
            )
            profile_friction_expressions: dict[str, str] = {}
            guidance_friction_expression: str | None = None
            for profile in route_profiles:
                profile_friction_expression = build_profile_friction_expression(
                    profile.drainage_penalty_multiplier
                )
                profile_friction_expressions[profile.candidate_id] = (
                    profile_friction_expression
                )
                output = profile_outputs[profile.candidate_id]["friction"]
                base_output = (
                    run_root / "terrain_route_friction_r4_base.tif"
                    if profile.strategy
                    is TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED
                    else output
                )
                process(
                    "grass:r.mapcalc.simple",
                    {
                        "a": str(slope_friction_path),
                        "b": str(drainage_pressure_path),
                        "expression": profile_friction_expression,
                        "output": str(base_output),
                    },
                    base_output,
                )
                if (
                    profile.strategy
                    is TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED
                ):
                    if guidance_execution is None:
                        raise _WorkerTerrainRouteUnavailable(
                            SpatialAnalysisErrorCode.INVALID_INPUT,
                            "R4 cannot compile local cost preferences without a reviewed guidance plan.",
                        )
                    guidance_friction_expression = (
                        build_guidance_friction_expression(
                            [
                                (
                                    guidance_projected_coordinates[
                                        modifier.constraint_id
                                    ][0],
                                    guidance_projected_coordinates[
                                        modifier.constraint_id
                                    ][1],
                                    modifier.influence_radius_m,
                                    modifier.minimum_friction_multiplier,
                                )
                                for modifier in guidance_execution.cost_modifiers
                            ]
                        )
                    )
                    process(
                        "grass:r.mapcalc.simple",
                        {
                            "a": str(base_output),
                            "expression": guidance_friction_expression,
                            "output": str(output),
                        },
                        output,
                    )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "walk_path_generated"
            profile_results: list[dict[str, Any]] = []

            def run_walk_path_segment(
                *,
                profile: TerrainRouteAlternativeProfile,
                alternative_index: int,
                segment_id: str,
                segment_start_wgs84: tuple[float, float],
                segment_destination_wgs84: tuple[float, float],
                segment_start_coordinate: str,
                segment_destination_coordinate: str,
                segment_destination_path: Path,
                outputs: dict[str, Path],
                path_semantics: str,
            ) -> dict[str, Any]:
                process(
                    "grass:r.walk.coords",
                    {
                        "elevation": str(dem_input),
                        "friction": str(outputs["friction"]),
                        "start_coordinates": segment_start_coordinate,
                        "stop_coordinates": segment_destination_coordinate,
                        "walk_coeff": "0.72,6.0,1.9998,-1.9998",
                        "lambda": 1.0,
                        "slope_factor": -0.2125,
                        "max_cost": 0.0,
                        "null_cost": None,
                        "memory": 300,
                        "-k": True,
                        "-n": False,
                        "output": str(outputs["walk_cost"]),
                        "outdir": str(outputs["walk_direction"]),
                        "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                    },
                    outputs["walk_cost"],
                    outputs["walk_direction"],
                )
                process(
                    "grass:r.path",
                    {
                        "input": str(outputs["walk_direction"]),
                        "format": 0,
                        "values": None,
                        "raster_path": str(outputs["path_raster"]),
                        "vector_path": str(outputs["path_projected"]),
                        "start_points": str(segment_destination_path),
                        "-c": False,
                        "-a": False,
                        "-n": False,
                        "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                        "GRASS_SNAP_TOLERANCE_PARAMETER": -1.0,
                        "GRASS_MIN_AREA_PARAMETER": 0.0001,
                        "GRASS_OUTPUT_TYPE_PARAMETER": 2,
                        "GRASS_VECTOR_EXPORT_NOCAT": False,
                    },
                    outputs["path_raster"],
                    outputs["path_projected"],
                )
                raw_path_payload, _path_layer_id = (
                    self._export_candidate_terrain_vector(
                        run=run,
                        vector_name=f"terrain_route_best_path_{segment_id}",
                        projected_path=outputs["path_projected"],
                        output_path=outputs["path_geojson"],
                        kind="terrain_route_hypothesis_best_path",
                        label=profile.label,
                        added_layers=added_layers,
                        max_geojson_bytes=8 * 1024 * 1024,
                        max_coordinate_count=_MAX_TERRAIN_ROUTE_PATH_COORDINATES,
                        workflow_id=TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
                    )
                )
                normalized_payload, coordinates = (
                    _normalize_terrain_route_best_path(
                        raw_path_payload,
                        start_wgs84=segment_start_wgs84,
                        destination_wgs84=segment_destination_wgs84,
                        worker_run_id=run.worker_run_id,
                        candidate_id=profile.candidate_id,
                        alternative_index=alternative_index,
                        label=profile.label,
                        strategy=profile.strategy,
                        drainage_penalty_multiplier=(
                            profile.drainage_penalty_multiplier
                        ),
                        endpoint_tolerance_m=max(
                            dem_resolution_m * 2.0,
                            10.0,
                        ),
                        path_semantics=path_semantics,
                    )
                )
                scalar = self._terrain_route_scalar_costs(
                    run=run,
                    destination_wgs84=segment_destination_wgs84,
                    rasters={"anisotropic_walk_cost": outputs["walk_cost"]},
                    added_layers=added_layers,
                ).get("anisotropic_walk_cost")
                if scalar is None:
                    raise _WorkerTerrainRouteUnavailable(
                        SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
                        (
                            "GRASS r.walk did not produce a connected model-cost "
                            f"segment for {segment_id}."
                        ),
                    )
                return {
                    "payload": normalized_payload,
                    "coordinates": coordinates,
                    "walk_cost": float(scalar),
                }

            for alternative_index, profile in enumerate(route_profiles, start=1):
                outputs = profile_outputs[profile.candidate_id]
                guided_segments: list[dict[str, Any]] = []
                if (
                    profile.strategy
                    is TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED
                ):
                    if guidance_execution is None:
                        raise _WorkerTerrainRouteUnavailable(
                            SpatialAnalysisErrorCode.INVALID_INPUT,
                            "R4 cannot run without a reviewed guidance execution plan.",
                        )
                    waypoint_rows: list[
                        tuple[tuple[float, float], str, Path | None, str]
                    ] = [
                        (start_wgs84, start_coordinate, None, "A"),
                        *[
                            (
                                (anchor.point.x, anchor.point.y),
                                (
                                    f"{_compact_number(guidance_projected_coordinates[anchor.constraint_id][0])},"
                                    f"{_compact_number(guidance_projected_coordinates[anchor.constraint_id][1])}"
                                ),
                                guidance_projected_point_paths[
                                    anchor.constraint_id
                                ],
                                anchor.constraint_id,
                            )
                            for anchor in guidance_execution.anchors
                        ],
                        (
                            destination_wgs84,
                            destination_coordinate,
                            projected_destination_path,
                            "B",
                        ),
                    ]
                    combined_coordinates: list[list[float]] = []
                    total_walk_cost = 0.0
                    for segment_index, (segment_start, segment_destination) in enumerate(
                        zip(waypoint_rows, waypoint_rows[1:]),
                        start=1,
                    ):
                        segment_suffix = f"r4_segment_{segment_index:02d}"
                        segment_outputs = {
                            "friction": outputs["friction"],
                            "walk_cost": run_root
                            / f"terrain_route_walk_cost_{segment_suffix}.tif",
                            "walk_direction": run_root
                            / f"terrain_route_walk_direction_{segment_suffix}.tif",
                            "path_raster": run_root
                            / f"terrain_route_best_path_{segment_suffix}.tif",
                            "path_projected": run_root
                            / f"terrain_route_best_path_{segment_suffix}_epsg3826.gpkg",
                            "path_geojson": run_root
                            / f"terrain_route_best_path_{segment_suffix}.geojson",
                        }
                        segment_result = run_walk_path_segment(
                            profile=profile,
                            alternative_index=alternative_index,
                            segment_id=segment_suffix,
                            segment_start_wgs84=segment_start[0],
                            segment_destination_wgs84=segment_destination[0],
                            segment_start_coordinate=segment_start[1],
                            segment_destination_coordinate=segment_destination[1],
                            segment_destination_path=segment_destination[2]
                            or projected_destination_path,
                            outputs=segment_outputs,
                            path_semantics=TERRAIN_ROUTE_GUIDED_PATH_SEMANTICS,
                        )
                        combined_coordinates = _append_guided_segment_coordinates(
                            combined_coordinates,
                            segment_result["coordinates"],
                            endpoint_tolerance_m=max(
                                dem_resolution_m * 2.0,
                                10.0,
                            ),
                        )
                        total_walk_cost += segment_result["walk_cost"]
                        guided_segments.append(
                            {
                                "segment_index": segment_index,
                                "start": segment_start[3],
                                "destination": segment_destination[3],
                                "walk_cost": segment_result["walk_cost"],
                                "vertex_count": len(
                                    segment_result["coordinates"]
                                ),
                            }
                        )
                    normalized_payload, coordinates = (
                        _normalize_terrain_route_best_path(
                            {
                                "type": "FeatureCollection",
                                "features": [
                                    {
                                        "type": "Feature",
                                        "geometry": {
                                            "type": "LineString",
                                            "coordinates": combined_coordinates,
                                        },
                                        "properties": {},
                                    }
                                ],
                            },
                            start_wgs84=start_wgs84,
                            destination_wgs84=destination_wgs84,
                            worker_run_id=run.worker_run_id,
                            candidate_id=profile.candidate_id,
                            alternative_index=alternative_index,
                            label=profile.label,
                            strategy=profile.strategy,
                            drainage_penalty_multiplier=(
                                profile.drainage_penalty_multiplier
                            ),
                            endpoint_tolerance_m=max(
                                dem_resolution_m * 2.0,
                                10.0,
                            ),
                            path_semantics=TERRAIN_ROUTE_GUIDED_PATH_SEMANTICS,
                        )
                    )
                    scalar = total_walk_cost
                else:
                    segment_result = run_walk_path_segment(
                        profile=profile,
                        alternative_index=alternative_index,
                        segment_id=profile.candidate_id.lower(),
                        segment_start_wgs84=start_wgs84,
                        segment_destination_wgs84=destination_wgs84,
                        segment_start_coordinate=start_coordinate,
                        segment_destination_coordinate=destination_coordinate,
                        segment_destination_path=projected_destination_path,
                        outputs=outputs,
                        path_semantics=TERRAIN_ROUTE_PATH_SEMANTICS,
                    )
                    normalized_payload = segment_result["payload"]
                    coordinates = segment_result["coordinates"]
                    scalar = segment_result["walk_cost"]
                profile_results.append(
                    {
                        "profile": profile,
                        "alternative_index": alternative_index,
                        "payload": normalized_payload,
                        "coordinates": coordinates,
                        "walk_ab": float(scalar),
                        "outputs": outputs,
                        "guided_segments": guided_segments,
                    }
                )
            best_path_payload = _combine_terrain_route_best_paths(
                profile_results,
                worker_run_id=run.worker_run_id,
            )
            _write_private_json(path_geojson_path, best_path_payload)
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "corridor_cost_generated"
            for origin, output, direction in (
                (
                    start_coordinate,
                    cost_a_path,
                    direction_a_path,
                ),
                (
                    destination_coordinate,
                    cost_b_path,
                    direction_b_path,
                ),
            ):
                process(
                    "grass:r.cost",
                    {
                        "input": str(friction_path),
                        "start_coordinates": origin,
                        "-k": True,
                        "-n": True,
                        "max_cost": 0.0,
                        "null_cost": None,
                        "memory": 300,
                        "output": str(output),
                        "outdir": str(direction),
                        "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                    },
                    output,
                    direction,
                )
            scalar_values = self._terrain_route_scalar_costs(
                run=run,
                destination_wgs84=destination_wgs84,
                rasters={"symmetric_c_ab": cost_a_path},
                added_layers=added_layers,
            )
            c_ab = scalar_values.get("symmetric_c_ab")
            if c_ab is None:
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
                    "No complete symmetric terrain-cost connection exists between A and B.",
                )
            corridor_expression = build_relative_corridor_expression(c_ab)
            process(
                "grass:r.mapcalc.simple",
                {
                    "a": str(cost_a_path),
                    "b": str(cost_b_path),
                    "expression": corridor_expression,
                    "output": str(corridor_path),
                },
                corridor_path,
            )
            process(
                "grass:r.univar",
                {
                    "map": [str(corridor_path)],
                    "zones": None,
                    "percentile": "",
                    "separator": "pipe",
                    "-e": False,
                    "output": str(corridor_stats_path),
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                },
                corridor_stats_path,
            )
            corridor_stats = _parse_grass_univar_report(corridor_stats_path)
            expected_cell_count = int(dem_stats["n"])
            if (
                int(corridor_stats.get("null_cells", 0)) > 0
                or int(corridor_stats.get("n", 0)) != expected_cell_count
            ):
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.COST_SURFACE_INCOMPLETE,
                    "The relative terrain corridor cost surface is incomplete.",
                )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "corridor_bands_generated"
            percentile_text = ",".join(
                _compact_number(value)
                for value in request.terrain_routing_cost_config.corridor_percentiles
            )
            process(
                "grass:r.quantile",
                {
                    "input": str(corridor_path),
                    "quantiles": 4,
                    "percentiles": percentile_text,
                    "bins": 1_000_000,
                    "-r": False,
                    "file": str(quantiles_path),
                    "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                },
                quantiles_path,
            )
            quantile_thresholds = _parse_grass_quantile_report(
                quantiles_path,
                request.terrain_routing_cost_config.corridor_percentiles,
            )
            band_records: list[dict[str, Any]] = []
            for index, percentile in enumerate(
                request.terrain_routing_cost_config.corridor_percentiles
            ):
                threshold = quantile_thresholds[float(percentile)]
                name = _terrain_route_percentile_name(percentile)
                band_path = run_root / f"terrain_route_{name}.tif"
                overlay_path = run_root / f"terrain_route_{name}.png"
                color_path = run_root / f"terrain_route_{name}_colors.txt"
                band_stats_path = run_root / f"terrain_route_{name}_univar.html"
                path_outside_path = run_root / f"terrain_route_path_outside_{name}.tif"
                path_outside_stats_path = (
                    run_root / f"terrain_route_path_outside_{name}_univar.html"
                )
                _write_private_bytes(
                    color_path,
                    _terrain_route_corridor_color_relief(percentile, index).encode(
                        "ascii"
                    ),
                )
                process(
                    "grass:r.mapcalc.simple",
                    {
                        "a": str(corridor_path),
                        "expression": build_corridor_threshold_expression(
                            threshold
                        ),
                        "output": str(band_path),
                    },
                    band_path,
                )
                process(
                    "grass:r.univar",
                    {
                        "map": [str(band_path)],
                        "zones": None,
                        "percentile": "",
                        "separator": "pipe",
                        "-e": False,
                        "output": str(band_stats_path),
                        "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                    },
                    band_stats_path,
                )
                band_stats = _parse_grass_univar_report(band_stats_path)
                process(
                    "grass:r.mapcalc.simple",
                    {
                        "a": str(path_raster_path),
                        "b": str(band_path),
                        "expression": build_path_outside_band_expression(),
                        "output": str(path_outside_path),
                    },
                    path_outside_path,
                )
                process(
                    "grass:r.univar",
                    {
                        "map": [str(path_outside_path)],
                        "zones": None,
                        "percentile": "",
                        "separator": "pipe",
                        "-e": False,
                        "output": str(path_outside_stats_path),
                        "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                    },
                    path_outside_stats_path,
                )
                path_outside_stats = _parse_grass_univar_report(
                    path_outside_stats_path
                )
                process(
                    "gdal:colorrelief",
                    {
                        "INPUT": str(band_path),
                        "BAND": 1,
                        "COMPUTE_EDGES": False,
                        "COLOR_TABLE": str(color_path),
                        "MATCH_MODE": 2,
                        "CREATION_OPTIONS": "",
                        "EXTRA": "-alpha",
                        "OUTPUT": str(overlay_path),
                    },
                    overlay_path,
                )
                band_records.append(
                    {
                        "name": name,
                        "percentile": float(percentile),
                        "threshold": float(threshold),
                        "cell_count": int(band_stats.get("n", 0)),
                        "contains_best_path": int(path_outside_stats.get("n", 0)) == 0,
                        "best_path_cells_outside": int(
                            path_outside_stats.get("n", 0)
                        ),
                        "band_path": band_path,
                        "overlay_path": overlay_path,
                    }
                )
            if any(
                first["threshold"] > second["threshold"]
                or first["cell_count"] > second["cell_count"]
                for first, second in zip(band_records, band_records[1:])
            ):
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.COST_SURFACE_INCOMPLETE,
                    "Terrain corridor percentile bands are not nested.",
                )
            run = self._complete_step(run, current_step)
            self._persist(run)
            self._check_cancel(cancel_event)

            current_step = "hypothesis_validated"
            for profile_result in profile_results:
                metrics, metric_sample_count = self._terrain_route_path_metrics(
                    run=run,
                    best_path_coordinates=profile_result["coordinates"],
                    rasters={
                        "elevation_m": dem_input,
                        "slope_degrees": slope_path,
                        "terrain_friction": profile_result["outputs"]["friction"],
                        "drainage_pressure": drainage_pressure_path,
                    },
                    high_cost_threshold=(
                        request.terrain_routing_cost_config.high_cost_threshold
                    ),
                    relative_cost=profile_result["walk_ab"],
                    added_layers=added_layers,
                )
                profile_result["metrics"] = metrics
                profile_result["metric_sample_count"] = metric_sample_count
            resolution_class, confidence_limits = resolution_confidence_limits(
                dem_resolution_m
            )
            bbox_wgs84 = dict(dem_analysis_extent["bbox_wgs84"])
            raster_ref = _terrain_route_raster_reference(
                corridor_path,
                crs="EPSG:3826",
                bbox_wgs84=bbox_wgs84,
            )
            corridor_bands = tuple(
                CandidateCorridorBand(
                    name=item["name"],
                    percentile=item["percentile"],
                    max_relative_corridor_cost=item["threshold"],
                    cell_count=item["cell_count"],
                    contains_best_path=item["contains_best_path"],
                    raster_ref=_terrain_route_raster_reference(
                        item["band_path"],
                        crs="EPSG:3826",
                        bbox_wgs84=bbox_wgs84,
                    ),
                    overlay_ref=_terrain_route_raster_reference(
                        item["overlay_path"],
                        crs="EPSG:3826",
                        bbox_wgs84=bbox_wgs84,
                    ),
                )
                for item in band_records
            )
            primary_result = next(
                item
                for item in profile_results
                if item["profile"].candidate_id == corridor_profile.candidate_id
            )
            distinct_geometry_count = int(
                best_path_payload["metadata"]["distinct_geometry_count"]
            )
            analysis_dem_hash = _file_sha256(dem_input)
            source_dem_hash = (
                source_dem_hashes[0]
                if len(source_dem_hashes) == 1
                else hashlib.sha256(
                    json.dumps(
                        sorted(source_dem_hashes),
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()
            )
            processing_manifest = {
                "schema_version": "scout_terrain_route_processing_manifest.v0_2",
                "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
                "workflow_run_id": run.worker_run_id,
                "parent_terrain_feature_manifest_ref": parent_manifest_ref,
                "parent_source_hashes": request.source_hashes,
                "cache_keys": cache_keys.model_dump(mode="json"),
                "analysis_extent": dem_analysis_extent,
                "source_dem_sha256s": list(source_dem_hashes),
                "source_dem_hash_semantics": (
                    "authoritative_input_content_hash"
                ),
                "analysis_dem_sha256": analysis_dem_hash,
                "analysis_dem_hash_semantics": (
                    "bounded_worker_raster_bytes_may_vary_by_gdal_grass_version"
                ),
                "dem_statistics": dem_stats,
                "corridor_statistics": corridor_stats,
                "corridor_semantics": TERRAIN_ROUTE_CORRIDOR_SEMANTICS,
                "corridor_formula": "C_A(x,y)+C_B(x,y)-C_AB",
                "corridor_cost_symmetric": True,
                "best_path_cost_symmetric": False,
                "path_model": {
                    "id": TERRAIN_ROUTE_PATH_MODEL,
                    "semantics": TERRAIN_ROUTE_PATH_SEMANTICS,
                    "recipe": "grass:r.walk.coords+grass:r.path",
                },
                "band_model": {
                    "id": TERRAIN_ROUTE_BAND_MODEL,
                    "semantics": TERRAIN_ROUTE_CORRIDOR_SEMANTICS,
                    "recipe": "symmetric_grass:r.cost",
                },
                "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
                "c_ab_model_cost": float(c_ab),
                "c_ab_extraction_method": "qgis_identify_at_destination",
                "anisotropic_walk_ab_cost": primary_result["walk_ab"],
                "threshold_mode": TERRAIN_ROUTE_CORRIDOR_SEMANTICS,
                "threshold_inclusive": True,
                "threshold_comparison_operator": "<=",
                "threshold_tie_handling": "include_all_cells_equal_to_threshold",
                "finite_corridor_cell_count": int(corridor_stats.get("n", 0)),
                "thresholds": [
                    {
                        "percentile": item["percentile"],
                        "max_relative_cost": item["threshold"],
                        "cell_count": item["cell_count"],
                        "contains_best_path": item["contains_best_path"],
                        "best_path_cells_outside": item["best_path_cells_outside"],
                    }
                    for item in band_records
                ],
                "bands_nested": True,
                "best_path_union_applied": False,
                "visualization_revision": TERRAIN_ROUTE_VISUALIZATION_REVISION,
                "provenance_revision": TERRAIN_ROUTE_PROVENANCE_REVISION,
                "execution_host": platform.node() or "unknown",
                "execution_architecture": platform.machine() or "unknown",
                "qgis_version_source": qgis_version_source,
                "grass_version_source": grass_version_source,
                "path_orientation": "A_TO_B",
                "endpoint_coordinate_semantics": "original_wgs84_coordinate",
                "endpoint_snap_distance_m": 0.0,
                "endpoint_tolerance_m": max(dem_resolution_m * 1.5, 1.0),
                "metric_sampling": {
                    "method": "deterministic_evenly_spaced_path_vertices",
                    "route_vertex_count": len(primary_result["coordinates"]),
                    "sample_count": primary_result["metric_sample_count"],
                    "maximum_sample_count": _MAX_TERRAIN_ROUTE_METRIC_SAMPLES,
                    "statistics_scope": "sampled_path_cells",
                    "max_slope_semantics": "maximum_of_sampled_cells_not_full_path_maximum",
                },
                "route_alternatives": [
                    {
                        "candidate_id": item["profile"].candidate_id,
                        "alternative_index": item["alternative_index"],
                        "strategy": item["profile"].strategy.value,
                        "drainage_penalty_multiplier": (
                            item["profile"].drainage_penalty_multiplier
                        ),
                        "corridor_profile": item["profile"].corridor_profile,
                        "anisotropic_walk_ab_cost": item["walk_ab"],
                        "route_vertex_count": len(item["coordinates"]),
                        "metric_sample_count": item["metric_sample_count"],
                        "guided_segments": item["guided_segments"],
                    }
                    for item in profile_results
                ],
                "alternative_count": len(profile_results),
                "distinct_geometry_count": distinct_geometry_count,
                "cross_profile_cost_comparison_allowed": False,
                "search_complete": True,
                "connectivity": "knight_move_enabled",
                "slope_friction_expression": friction_expression,
                "drainage_pressure_expression": drainage_pressure_expression,
                "profile_friction_expressions": profile_friction_expressions,
                "drainage_model": {
                    "source": "grass:r.watershed flow accumulation",
                    "semantics": "resolution-aware model penalty, not hazard or passability truth",
                    "river_or_channel_presence_confirmed": False,
                },
                "guidance_execution": (
                    {
                        "guidance_id": guidance_execution.guidance_id,
                        "guided_hypothesis_id": (
                            guidance_execution.guided_hypothesis_id
                        ),
                        "guidance_review_sha256": (
                            guidance_execution.guidance_review_sha256
                        ),
                        "plan_sha256": guidance_execution.plan_sha256,
                        "resolution_sha256": (
                            guidance_execution.resolution_sha256
                        ),
                        "feature_index_sha256": (
                            guidance_execution.feature_index_sha256
                        ),
                        "algorithm_version": (
                            guidance_execution.algorithm_version
                        ),
                        "cost_model_version": (
                            guidance_execution.cost_model_version
                        ),
                        "anchor_count": len(guidance_execution.anchors),
                        "review_decision_count": len(
                            guidance_execution.review_decisions
                        ),
                        "review_decisions": [
                            item.model_dump(mode="json")
                            for item in guidance_execution.review_decisions
                        ],
                        "anchors": [
                            {
                                "constraint_id": item.constraint_id,
                                "sequence_index": item.sequence_index,
                                "kind": item.kind.value,
                                "landform": item.landform.value,
                                "routing_effect": item.routing_effect.value,
                                "feature_id": item.feature_id,
                                "point": item.point.model_dump(mode="json"),
                                "selection_source": item.selection_source,
                                "source_layer_sha256": (
                                    item.source_layer_sha256
                                ),
                            }
                            for item in guidance_execution.anchors
                        ],
                        "cost_modifier_count": len(
                            guidance_execution.cost_modifiers
                        ),
                        "cost_modifiers": [
                            item.model_dump(mode="json")
                            for item in guidance_execution.cost_modifiers
                        ],
                        "guidance_friction_expression": (
                            guidance_friction_expression
                        ),
                        "disabled_constraint_ids": (
                            guidance_execution.disabled_constraint_ids
                        ),
                        "source_type": "historical_route",
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                        "safe_or_walkable": "not_determined",
                        "raw_narrative_forwarded_to_worker": False,
                    }
                    if guidance_execution is not None
                    else None
                ),
                "cost_model": request.terrain_routing_cost_config.model_dump(
                    mode="json"
                ),
                "processing_invocations": processing_invocations,
                "capabilities": discovered,
                "source_refs": request.source_refs,
                "source_hashes": request.source_hashes,
                "source_resolution": request.source_resolution,
                "qgis_version": qgis_version,
                "grass_version": grass_version,
                "qgis_mcp_plugin_version": mcp_version,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "safe_or_walkable": "not_determined",
            }
            dem_hash = source_dem_hash
            hypotheses: list[TerrainRouteHypothesis] = []
            for profile_result in profile_results:
                profile = profile_result["profile"]
                metrics = profile_result["metrics"]
                evidence: list[RouteEvidence] = []
                if metrics.median_slope_degrees <= 20:
                    evidence.append(
                        RouteEvidence(
                            code="moderate_slope",
                            polarity=RouteEvidencePolarity.POSITIVE,
                            description=(
                                "The DEM-derived median slope along this model trace is "
                                "within the configured moderate terrain-cost range."
                            ),
                        )
                    )
                if metrics.max_slope_degrees > 30:
                    evidence.append(
                        RouteEvidence(
                            code="steep_slope",
                            polarity=RouteEvidencePolarity.NEGATIVE,
                            description=(
                                "The model trace includes DEM cells in a high terrain-cost "
                                "slope band."
                            ),
                        )
                    )
                if profile.strategy is TerrainRouteStrategy.DRAINAGE_AVERSE:
                    evidence.append(
                        RouteEvidence(
                            code="drainage_pressure_penalized",
                            polarity=RouteEvidencePolarity.POSITIVE,
                            description=(
                                "This model profile applies the strongest relative cost to "
                                "DEM-derived flow-accumulation cells; it does not establish "
                                "that channels are unsafe or impassable."
                            ),
                        )
                    )
                elif profile.strategy is TerrainRouteStrategy.BALANCED:
                    evidence.append(
                        RouteEvidence(
                            code="moderate_drainage_penalty",
                            polarity=RouteEvidencePolarity.POSITIVE,
                            description=(
                                "This model profile applies a moderate relative drainage "
                                "penalty while retaining slope-driven alternatives."
                            ),
                        )
                    )
                elif (
                    profile.strategy
                    is TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED
                ):
                    evidence.extend(
                        [
                            RouteEvidence(
                                code="reviewed_historical_guidance_applied",
                                polarity=RouteEvidencePolarity.POSITIVE,
                                description=(
                                    "This candidate follows human-confirmed map points "
                                    "interpreted from a historical narrative, with each "
                                    "segment solved by the terrain model."
                                ),
                            ),
                            RouteEvidence(
                                code="historical_guidance_not_observation",
                                polarity=RouteEvidencePolarity.NEGATIVE,
                                description=(
                                    "Historical wording and reviewed map points do not "
                                    "establish a currently observed trail, passage, safety, "
                                    "or legal access."
                                ),
                            ),
                        ]
                    )
                else:
                    evidence.append(
                        RouteEvidence(
                            code="drainage_not_penalized",
                            polarity=RouteEvidencePolarity.NEGATIVE,
                            description=(
                                "This terrain-only baseline does not penalize drainage and "
                                "may follow valleys or channels; that is not evidence they "
                                "are passable."
                            ),
                        )
                    )
                if (metrics.high_drainage_pressure_fraction or 0) > 0:
                    evidence.append(
                        RouteEvidence(
                            code="drainage_pressure_overlap",
                            polarity=RouteEvidencePolarity.NEGATIVE,
                            description=(
                                "Sampled cells along this model trace still overlap high "
                                "DEM-derived drainage pressure."
                            ),
                        )
                    )
                weights = {
                    "slope_weight": request.terrain_routing_cost_config.slope_weight,
                    "roughness_weight": request.terrain_routing_cost_config.roughness_weight,
                    "curvature_weight": request.terrain_routing_cost_config.curvature_weight,
                    "drainage_weight": request.terrain_routing_cost_config.drainage_weight,
                    "drainage_penalty_multiplier": profile.drainage_penalty_multiplier,
                    "ridge_weight": request.terrain_routing_cost_config.ridge_weight,
                    "teii_weight": request.terrain_routing_cost_config.teii_weight,
                }
                profile_manifest = {
                    **processing_manifest,
                    "active_profile": profile.model_dump(mode="json"),
                    "metric_sampling": {
                        "method": "deterministic_evenly_spaced_path_vertices",
                        "route_vertex_count": len(profile_result["coordinates"]),
                        "sample_count": profile_result["metric_sample_count"],
                        "maximum_sample_count": _MAX_TERRAIN_ROUTE_METRIC_SAMPLES,
                        "statistics_scope": "sampled_path_cells",
                        "max_slope_semantics": "maximum_of_sampled_cells_not_full_path_maximum",
                    },
                    "guided_segments": profile_result["guided_segments"],
                }
                guided_profile = (
                    profile.strategy
                    is TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED
                )
                provenance = TerrainHypothesisProvenance(
                    dem_dataset_id=(
                        Path(request.dem_refs[0]).name
                        if len(request.dem_refs) == 1
                        else "multi_dem_mosaic"
                    ),
                    dem_sha256=dem_hash,
                    dem_resolution_m=dem_resolution_m,
                    dem_crs="EPSG:3826",
                    dem_extent={
                        "x_min": float(dem_analysis_extent["bbox_twd97"]["min_x"]),
                        "y_min": float(dem_analysis_extent["bbox_twd97"]["min_y"]),
                        "x_max": float(dem_analysis_extent["bbox_twd97"]["max_x"]),
                        "y_max": float(dem_analysis_extent["bbox_twd97"]["max_y"]),
                    },
                    input_endpoints={
                        "start": {"x": start_wgs84[0], "y": start_wgs84[1], "crs": "EPSG:4326"},
                        "destination": {"x": destination_wgs84[0], "y": destination_wgs84[1], "crs": "EPSG:4326"},
                    },
                    optional_evidence_refs=(
                        [f"terrain-guidance-review:{guidance_execution.guidance_id}"]
                        if guided_profile and guidance_execution is not None
                        else []
                    ),
                    optional_evidence_hashes=(
                        {
                            "terrain_guidance_review": (
                                guidance_execution.guidance_review_sha256
                            )
                        }
                        if guided_profile and guidance_execution is not None
                        else {}
                    ),
                    cost_model_version=request.terrain_routing_cost_config.model_version,
                    weights=weights,
                    weights_hash=hashlib.sha256(
                        json.dumps(weights, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    grass_version=grass_version,
                    qgis_version=qgis_version,
                    backend_id="qgis_worker_grass.v0_2",
                    modules_executed=[item["algorithm"] for item in processing_invocations],
                    commands_executed=processing_invocations,
                    timestamp=self._now_iso(),
                    algorithm_version=request.terrain_routing_cost_config.algorithm_version,
                    processing_manifest=profile_manifest,
                    cache_key=cache_keys.route_hypothesis,
                    cache_keys=cache_keys.model_dump(mode="json"),
                )
                hypotheses.append(
                    TerrainRouteHypothesis(
                        id=(
                            "terrain-route-hypothesis-"
                            f"{profile.candidate_id.lower()}-{cache_keys.route_hypothesis[:12]}"
                        ),
                        label=profile.label,
                        alternative_index=profile_result["alternative_index"],
                        strategy=profile.strategy,
                        drainage_penalty_multiplier=profile.drainage_penalty_multiplier,
                        start=GeoPoint(x=start_wgs84[0], y=start_wgs84[1], crs="EPSG:4326", label="A"),
                        destination=GeoPoint(x=destination_wgs84[0], y=destination_wgs84[1], crs="EPSG:4326", label="B"),
                        best_path=GeoJsonLineString(
                            coordinates=tuple(
                                (float(item[0]), float(item[1]))
                                for item in profile_result["coordinates"]
                            ),
                            crs="EPSG:4326",
                        ),
                        path_semantics=(
                            TERRAIN_ROUTE_GUIDED_PATH_SEMANTICS
                            if guided_profile
                            else TERRAIN_ROUTE_PATH_SEMANTICS
                        ),
                        corridor=(
                            TerrainRouteCandidateCorridor(bands=corridor_bands, raster_ref=raster_ref)
                            if profile.corridor_profile
                            else None
                        ),
                        score=None,
                        metrics=metrics,
                        reasons=evidence,
                        unknowns=default_route_unknowns(dem_resolution_m=dem_resolution_m),
                        dem_resolution_m=dem_resolution_m,
                        resolution_class=resolution_class,
                        confidence_limits=confidence_limits,
                        cost_model_version=request.terrain_routing_cost_config.model_version,
                        provenance=provenance,
                    )
                )
            hypothesis_run = TerrainRouteHypothesisRun(
                status=TerrainRouteRunStatus.COMPLETED,
                created_at=self._now_iso(),
                hypotheses=hypotheses,
                warnings=[
                    "Terrain model preference does not establish a trail, passage, safety, or legal access.",
                    "Cross-profile relative costs are not directly comparable because each profile uses a different friction model.",
                    "The terrain-only baseline does not penalize drainage and may overlap a valley or channel without establishing passage.",
                    "Corridor bands are finite-cell relative-cost percentiles and do not receive a best-path-cell union.",
                    *(
                        [
                            "R4 applies reviewed historical guidance as ordered terrain-model gates; it does not verify the narrative, trail existence, current passage, safety, or legal access."
                        ]
                        if guidance_execution is not None
                        else []
                    ),
                    *(
                        [
                            "Some route profiles produced identical geometry; their model assumptions remain distinct, but no spatial separation was invented."
                        ]
                        if distinct_geometry_count < len(profile_results)
                        else []
                    ),
                ],
                unknowns=default_route_unknowns(
                    dem_resolution_m=dem_resolution_m
                ),
            )
            _write_private_json(
                hypothesis_path,
                hypothesis_run.model_dump(mode="json"),
            )
            _write_private_json(manifest_path, processing_manifest)

            artifacts = [
                _artifact(
                    run.worker_run_id,
                    "terrain-route-hypothesis",
                    "terrain_route_hypothesis",
                    hypothesis_path,
                    "application/json",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-best-path",
                    "terrain_route_best_path_vector",
                    path_geojson_path,
                    "application/geo+json",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-slope",
                    "terrain_route_slope_raster",
                    slope_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-flow-accumulation",
                    "terrain_route_flow_accumulation_raster",
                    flow_accumulation_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-drainage-pressure",
                    "terrain_route_drainage_pressure_raster",
                    drainage_pressure_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-friction",
                    "terrain_route_friction_raster",
                    friction_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-walk-cost",
                    "terrain_route_walk_cost_raster",
                    walk_cost_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-walk-direction",
                    "terrain_route_walk_direction_raster",
                    walk_direction_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-cost-a",
                    "terrain_route_cost_from_a_raster",
                    cost_a_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-cost-b",
                    "terrain_route_cost_from_b_raster",
                    cost_b_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-direction-a",
                    "terrain_route_cost_direction_a_raster",
                    direction_a_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-direction-b",
                    "terrain_route_cost_direction_b_raster",
                    direction_b_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-corridor",
                    "terrain_route_corridor_raster",
                    corridor_path,
                    "image/tiff",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-quantiles",
                    "terrain_route_quantiles",
                    quantiles_path,
                    "text/html",
                ),
                _artifact(
                    run.worker_run_id,
                    "terrain-route-processing-manifest",
                    "terrain_route_processing_manifest",
                    manifest_path,
                    "application/json",
                ),
            ]
            for item in band_records:
                suffix = item["name"].replace("_corridor", "")
                artifacts.extend(
                    [
                        _artifact(
                            run.worker_run_id,
                            f"terrain-route-{suffix}-raster",
                            "terrain_route_corridor_band_raster",
                            item["band_path"],
                            "image/tiff",
                        ),
                        _artifact(
                            run.worker_run_id,
                            f"terrain-route-{suffix}-overlay",
                            "terrain_route_corridor_overlay",
                            item["overlay_path"],
                            "image/png",
                            width_px=int(dem_analysis_extent["width"]),
                            height_px=int(dem_analysis_extent["height"]),
                            visualization_only=True,
                        ),
                    ]
                )
            completed_at = self._now_iso()
            processing_algorithms = list(
                dict.fromkeys(
                    item["algorithm"] for item in processing_invocations
                )
            )
            result = QgisWorkerResult(
                maplibre_geojson=_terrain_route_maplibre_geojson(
                    best_path_payload,
                    start_wgs84=start_wgs84,
                    destination_wgs84=destination_wgs84,
                    hypothesis_id=hypotheses[0].id,
                    hypothesis_ids=[item.id for item in hypotheses],
                    cache_key=cache_keys.route_hypothesis,
                ),
                artifacts=artifacts,
                qgis_version=qgis_version,
                qgis_mcp_plugin_version=mcp_version,
                crs="EPSG:3826",
                source_resolution={
                    **request.source_resolution,
                    "dem_resolution_m": dem_resolution_m,
                    "adds_source_resolution": False,
                },
                output_resolution={
                    "status": "candidate_hypothesis_alternatives_generated",
                    "analysis_extent": dem_analysis_extent,
                    "path_crs": "EPSG:4326",
                    "raster_crs": "EPSG:3826",
                    "adds_source_resolution": False,
                },
                processing_algorithms=processing_algorithms,
                processing_parameters={
                    "recipe": "terrain_route_hypothesis.v1.drainage_profiles",
                    "alternative_count": len(hypotheses),
                    "distinct_geometry_count": distinct_geometry_count,
                    "cross_profile_cost_comparison_allowed": False,
                    "cache_keys": cache_keys.model_dump(mode="json"),
                    "cost_model": request.terrain_routing_cost_config.model_dump(
                        mode="json"
                    ),
                    "corridor_semantics": TERRAIN_ROUTE_CORRIDOR_SEMANTICS,
                    "path_model": TERRAIN_ROUTE_PATH_MODEL,
                    "path_semantics": TERRAIN_ROUTE_PATH_SEMANTICS,
                    "band_model": TERRAIN_ROUTE_BAND_MODEL,
                    "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
                    "best_path_union_applied": False,
                    "visualization_revision": TERRAIN_ROUTE_VISUALIZATION_REVISION,
                    "processing_invocations": processing_invocations,
                    "source_orientation_normalization": {
                        "applied": bool(dem_normalized_source_count),
                        "source_count": dem_normalized_source_count,
                        "target_resolution_m": dem_normalization_resolution_m,
                        "adds_source_resolution": False,
                    },
                },
                warnings=hypothesis_run.warnings,
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
                            "result": "candidate_terrain_route_hypothesis_alternatives_exported",
                            "artifact_ids": [item.artifact_id for item in artifacts],
                            "cache_key": cache_keys.route_hypothesis,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        },
                    ],
                }
            )
            run = self._complete_step(run, current_step)
            self._persist(run)
        except _WorkerCancelled:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "QGIS terrain route hypothesis workflow was cancelled.",
                state=SpatialWorkflowState.CANCELLED,
                retryable=True,
            )
        except _WorkerTerrainRouteUnavailable as exc:
            self._fail_run(
                run,
                current_step,
                exc.code,
                str(exc),
            )
        except _WorkerCapabilityUnavailable as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.UNSUPPORTED_TOOL,
                "A required terrain-route GRASS capability is unavailable.",
                detail=str(exc),
            )
        except _WorkerCrsUnresolved as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.CRS_UNRESOLVED,
                "Terrain route CRS or endpoint coverage could not be resolved.",
                detail=str(exc),
            )
        except QgisMcpToolRejected as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.FORBIDDEN_CAPABILITY,
                "Terrain route workflow attempted a forbidden QGIS capability.",
                detail=str(exc),
            )
        except QgisMcpTimeout as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                "Terrain route QGIS/GRASS execution timed out; result is unknown.",
                detail=str(exc),
                retryable=True,
            )
        except (QgisMcpUnavailable, QgisMcpToolError, QgisMcpError) as exc:
            code = _mcp_failure_code(exc, current_step=current_step)
            self._fail_run(
                run,
                current_step,
                code,
                "Terrain route QGIS/GRASS execution failed; no hypothesis was published.",
                detail=_bounded_mcp_exception_detail(exc),
                retryable=code
                in {
                    SpatialAnalysisErrorCode.QGIS_UNAVAILABLE,
                    SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                    SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                },
            )
        except _WorkerProcessingFailed as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.PROCESSING_FAILED,
                "Terrain route Processing failed closed.",
                detail=str(exc),
            )
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.ARTIFACT_EXPORT_FAILED,
                "Terrain route artifact validation or export failed closed.",
                detail=str(exc),
            )
        except Exception as exc:
            self._fail_run(
                run,
                current_step,
                SpatialAnalysisErrorCode.UNKNOWN,
                "Terrain route workflow encountered an unexpected bounded worker error.",
                detail=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._cleanup_layers(added_layers)
            with self._lock:
                self._active_operations.pop(run.worker_run_id, None)
                self._cancel_events.pop(run.worker_run_id, None)
                self._threads.pop(run.worker_run_id, None)

    def _terrain_route_scalar_costs(
        self,
        *,
        run: QgisWorkerRun,
        destination_wgs84: tuple[float, float],
        rasters: dict[str, Path],
        added_layers: list[str],
    ) -> dict[str, float | None]:
        layer_ids: dict[str, str] = {}
        for role, path in rasters.items():
            layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_raster",
                    "source": str(path),
                    "name": f"Scout terrain route {role} {run.worker_run_id[-10:]}",
                },
            )
            layer_id = str(layer.get("id") or layer.get("layer_id") or "")
            if not layer_id:
                raise _WorkerProcessingFailed(
                    f"QGIS did not return a raster layer for {role}"
                )
            layer_ids[role] = layer_id
            added_layers.append(layer_id)
        identified = self._call(
            "qgis_identify",
            {
                "point": [destination_wgs84[0], destination_wgs84[1]],
                "crs": "EPSG:4326",
                "layers": list(layer_ids.values()),
                "tolerance": 0.0,
                "limit_per_layer": 1,
            },
        )
        values = _identified_raster_values(identified)
        return {role: values.get(layer_id) for role, layer_id in layer_ids.items()}

    def _terrain_route_path_metrics(
        self,
        *,
        run: QgisWorkerRun,
        best_path_coordinates: list[list[float]],
        rasters: dict[str, Path],
        high_cost_threshold: float,
        relative_cost: float,
        added_layers: list[str],
    ) -> tuple[TerrainHypothesisMetrics, int]:
        layer_ids: dict[str, str] = {}
        for role, path in rasters.items():
            layer = self._call(
                "qgis_project_action",
                {
                    "action": "add_raster",
                    "source": str(path),
                    "name": f"Scout terrain route metric {role} {run.worker_run_id[-10:]}",
                },
            )
            layer_id = str(layer.get("id") or layer.get("layer_id") or "")
            if not layer_id:
                raise _WorkerProcessingFailed(
                    f"QGIS did not return a metric raster layer for {role}"
                )
            layer_ids[role] = layer_id
            added_layers.append(layer_id)
        samples = _bounded_route_sample_positions(
            best_path_coordinates,
            max_samples=_MAX_TERRAIN_ROUTE_METRIC_SAMPLES,
        )
        elevations: list[float] = []
        slopes: list[float] = []
        frictions: list[float] = []
        drainage_pressures: list[float] = []
        for sample in samples:
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
            values = _identified_raster_values(identified)
            sample_values = {
                role: values.get(layer_id) for role, layer_id in layer_ids.items()
            }
            if any(value is None for value in sample_values.values()):
                raise _WorkerTerrainRouteUnavailable(
                    SpatialAnalysisErrorCode.COST_SURFACE_INCOMPLETE,
                    "A best-path metric sample intersects missing DEM or cost data.",
                )
            elevations.append(float(sample_values["elevation_m"]))
            slopes.append(float(sample_values["slope_degrees"]))
            frictions.append(float(sample_values["terrain_friction"]))
            if "drainage_pressure" in sample_values:
                drainage_pressures.append(
                    float(sample_values["drainage_pressure"])
                )
        gain = 0.0
        loss = 0.0
        for first, second in zip(elevations, elevations[1:]):
            delta = second - first
            if delta >= 0:
                gain += delta
            else:
                loss += -delta
        distance = sum(
            _haversine_m(first[1], first[0], second[1], second[0])
            for first, second in zip(
                best_path_coordinates,
                best_path_coordinates[1:],
            )
        )
        return (
            TerrainHypothesisMetrics(
                relative_score=None,
                relative_cost=float(relative_cost),
                distance_m=float(distance),
                elevation_gain_m=float(gain),
                elevation_loss_m=float(loss),
                max_slope_degrees=max(slopes),
                median_slope_degrees=float(median(slopes)),
                high_cost_fraction=(
                    sum(value >= high_cost_threshold for value in frictions)
                    / len(frictions)
                ),
                ridge_fraction=None,
                valley_fraction=None,
                drainage_pressure_fraction=(
                    sum(value > 0 for value in drainage_pressures)
                    / len(drainage_pressures)
                    if drainage_pressures
                    else None
                ),
                high_drainage_pressure_fraction=(
                    sum(value >= 3 for value in drainage_pressures)
                    / len(drainage_pressures)
                    if drainage_pressures
                    else None
                ),
                teii_stats={},
            ),
            len(samples),
        )

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
        hillshade_path = run_root / "grass_hillshade.tif"
        slope_path = run_root / "grass_slope.tif"
        aspect_path = run_root / "grass_aspect.tif"
        contour_projected_path = run_root / "grass_contours_epsg3826.gpkg"
        contour_geojson_path = run_root / "grass_contours.geojson"
        contour_raster_path = run_root / "grass_contours_display.tif"
        elevation_tint_path = run_root / "terrain_elevation_tint.png"
        hillshade_overlay_path = run_root / "terrain_hillshade.png"
        slope_shading_path = run_root / "terrain_slope_shading.png"
        contours_overlay_path = run_root / "terrain_contours.png"
        elevation_colors_path = run_root / "elevation_color_relief.txt"
        hillshade_colors_path = run_root / "hillshade_color_relief.txt"
        slope_colors_path = run_root / "slope_color_relief.txt"
        contour_colors_path = run_root / "contour_color_relief.txt"
        geomorphon_fine_path = run_root / "grass_geomorphon_fine.tif"
        geomorphon_path = run_root / "grass_geomorphon_landforms.tif"
        geomorphon_coarse_path = run_root / "grass_geomorphon_coarse.tif"
        ridge_consensus_path = run_root / "grass_geomorphon_ridge_consensus.tif"
        valley_consensus_path = run_root / "grass_geomorphon_valley_consensus.tif"
        ridge_thin_path = run_root / "grass_geomorphon_ridge_thin.tif"
        valley_thin_path = run_root / "grass_geomorphon_valley_thin.tif"
        ridge_projected_path = run_root / "ridge_lines_epsg3826.gpkg"
        valley_projected_path = run_root / "valley_lines_epsg3826.gpkg"
        ridge_filtered_path = run_root / "ridge_lines_min160m_epsg3826.gpkg"
        valley_filtered_path = run_root / "valley_lines_min160m_epsg3826.gpkg"
        ridge_dissolved_path = run_root / "ridge_lines_min160m_dissolved_epsg3826.gpkg"
        valley_dissolved_path = run_root / "valley_lines_min160m_dissolved_epsg3826.gpkg"
        ridge_geojson_path = run_root / "ridge_lines.geojson"
        valley_geojson_path = run_root / "valley_lines.geojson"
        accumulation_path = run_root / "grass_flow_accumulation.tif"
        stream_raster_path = run_root / "grass_stream_network.tif"
        stream_thin_path = run_root / "grass_stream_network_thin.tif"
        stream_projected_path = run_root / "stream_network_epsg3826.gpkg"
        stream_filtered_path = run_root / "stream_network_min160m_epsg3826.gpkg"
        stream_dissolved_path = run_root / "stream_network_min160m_dissolved_epsg3826.gpkg"
        stream_geojson_path = run_root / "stream_network.geojson"
        route_samples_path = run_root / "terrain_feature_route_samples.geojson"
        manifest_path = run_root / "terrain_feature_manifest.json"
        surface_manifest_path = run_root / "terrain_surface_manifest.json"
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
            (
                dem_input,
                dem_normalized_source_count,
                dem_normalization_resolution_m,
                dem_analysis_extent,
            ) = self._prepare_dem(
                run.worker_run_id,
                dem_refs,
                request.source_resolution,
                prepared_route_summary.get("extent"),
                request.corridor_m,
                cancel_event,
            )
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

            current_step = "terrain_surface_generated"
            terrain_surface_processing = self._generate_standard_terrain_surface(
                worker_run_id=run.worker_run_id,
                dem_input=dem_input,
                slope_path=slope_path,
                analysis_extent=dem_analysis_extent,
                hillshade_path=hillshade_path,
                contour_projected_path=contour_projected_path,
                contour_raster_path=contour_raster_path,
                elevation_tint_path=elevation_tint_path,
                hillshade_overlay_path=hillshade_overlay_path,
                slope_shading_path=slope_shading_path,
                contours_overlay_path=contours_overlay_path,
                elevation_colors_path=elevation_colors_path,
                hillshade_colors_path=hillshade_colors_path,
                slope_colors_path=slope_colors_path,
                contour_colors_path=contour_colors_path,
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
                dem_input,
                slope_path,
                aspect_path,
                hillshade_path,
                contour_raster_path,
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
            for source_path, filtered_path, dissolved_path in (
                (ridge_projected_path, ridge_filtered_path, ridge_dissolved_path),
                (valley_projected_path, valley_filtered_path, valley_dissolved_path),
                (stream_projected_path, stream_filtered_path, stream_dissolved_path),
            ):
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="native:extractbyexpression",
                    parameters={
                        "INPUT": str(source_path),
                        "EXPRESSION": QGIS_MCP_TERRAIN_LINE_MIN_LENGTH_EXPRESSION,
                        "OUTPUT": str(filtered_path),
                        "FAIL_OUTPUT": None,
                    },
                    output_paths=(filtered_path,),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
                self._run_processing_outputs(
                    worker_run_id=run.worker_run_id,
                    algorithm="native:dissolve",
                    parameters={
                        "INPUT": str(filtered_path),
                        "FIELD": [],
                        "SEPARATE_DISJOINT": False,
                        "OUTPUT": str(dissolved_path),
                    },
                    output_paths=(dissolved_path,),
                    cancel_event=cancel_event,
                    added_layers=added_layers,
                )
            candidate_vectors: dict[str, dict[str, Any]] = {}
            candidate_vector_layer_ids: dict[str, str] = {}
            for vector_name, projected_path, geojson_path, kind, label in (
                (
                    "contour",
                    contour_projected_path,
                    contour_geojson_path,
                    "qgis_candidate_contour_line",
                    "GRASS 100 m contour candidate",
                ),
                (
                    "ridge",
                    ridge_dissolved_path,
                    ridge_geojson_path,
                    "qgis_candidate_ridge_line",
                    "Multiscale ridge-line candidate",
                ),
                (
                    "valley",
                    valley_dissolved_path,
                    valley_geojson_path,
                    "qgis_candidate_valley_line",
                    "Multiscale valley-line candidate",
                ),
                (
                    "stream",
                    stream_dissolved_path,
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
                    max_geojson_bytes=(
                        64 * 1024 * 1024 if vector_name == "contour" else 16 * 1024 * 1024
                    ),
                    max_coordinate_count=(
                        750_000 if vector_name == "contour" else 500_000
                    ),
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
                    "elevation_m": dem_input,
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
                    "dem_route_bbox": dem_input.name,
                    "slope": slope_path.name,
                    "aspect": aspect_path.name,
                    "hillshade": hillshade_path.name,
                    "elevation_tint_overlay": elevation_tint_path.name,
                    "hillshade_overlay": hillshade_overlay_path.name,
                    "slope_shading_overlay": slope_shading_path.name,
                    "contour_lines": contour_geojson_path.name,
                    "contours_overlay": contours_overlay_path.name,
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
                    "analysis_extent": dem_analysis_extent,
                    "terrain_surface_processing": terrain_surface_processing,
                    "terrain_surface_actual_processors": {
                        "dem_crop": "gdal:cliprasterbyextent",
                        "slope_aspect": "grass:r.slope.aspect",
                        "hillshade": "grass:r.relief",
                        "contours": "grass:r.contour",
                        "contour_rasterization": "gdal:rasterize",
                        "display_colorization": "gdal:colorrelief",
                        "candidate_line_filter": "native:extractbyexpression",
                        "candidate_line_merge": "native:dissolve",
                    },
                    "terrain_surface_overlay_alpha_channel": True,
                    "terrain_surface_color_relief_extra": "-alpha",
                    "candidate_line_minimum_length_m": 160.0,
                    "python_dtm_processing_used": False,
                    "route_preparation_tool": "qgis_vector_export",
                    "route_output_crs": "EPSG:3826",
                    "route_runtime_crs_assignment": (
                        route_crs_assignment.get("assignment") or {}
                    ),
                    "route_export_file_crs": "UNKNOWN",
                    "source_orientation_normalization": {
                        "applied": bool(dem_normalized_source_count),
                        "source_count": dem_normalized_source_count,
                        "algorithm": (
                            "gdal:warpreproject"
                            if dem_normalized_source_count
                            else None
                        ),
                        "source_crs": (
                            "EPSG:3826" if dem_normalized_source_count else None
                        ),
                        "target_crs": (
                            "EPSG:3826" if dem_normalized_source_count else None
                        ),
                        "target_resolution_m": dem_normalization_resolution_m,
                        "resampling": (
                            "nearest" if dem_normalized_source_count else None
                        ),
                        "adds_source_resolution": False,
                    },
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
            surface_manifest_payload = {
                "schema_version": "scout_qgis_terrain_surface.v0_1",
                "artifact_kind": "scout_qgis_terrain_surface_manifest",
                "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
                "workflow_run_id": run.worker_run_id,
                "status": "completed_candidate_surface",
                "coverage_scope": "full_route_extent_rectangle",
                "analysis_extent": dem_analysis_extent,
                "source_resolution": request.source_resolution,
                "actual_processor": "qgis_processing_grass",
                "actual_processors": manifest_payload["parameters"][
                    "terrain_surface_actual_processors"
                ],
                "fallback_used": False,
                "python_dtm_processing_used": False,
                "overlays": {
                    "elevation_tint": elevation_tint_path.name,
                    "hillshade": hillshade_overlay_path.name,
                    "slope_shading": slope_shading_path.name,
                    "contours": contours_overlay_path.name,
                },
                "overlay_alpha_channel": True,
                "overlay_pixel_format": "RGBA",
                "overlay_compositing": "source-over",
                "contour_vector": contour_geojson_path.name,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "adds_source_resolution": False,
                "interpretation": (
                    "The rectangular surface is standard GIS processing evidence. "
                    "It does not establish terrain, route, hazard, navigability, or safety truth."
                ),
            }
            _write_private_json(surface_manifest_path, surface_manifest_payload)

            current_step = "map_rendered"
            screenshot, render_bytes, slope_inspection = self._render_feature_stack_preview(
                run=run,
                route_source=(
                    f"{projected_route_path}|layername={exported_layer_name}"
                ),
                route_layer_id=route_layer_id,
                slope_path=slope_path,
                candidate_vector_sources={
                    "contour": (
                        candidate_vector_layer_ids["contour"],
                        contour_projected_path,
                    ),
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

            dem_artifact = _artifact(
                run.worker_run_id,
                "dem-route-bbox",
                "dem_route_bbox_raster",
                dem_input,
                "image/tiff",
            )
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
            hillshade_artifact = _artifact(
                run.worker_run_id,
                "grass-hillshade",
                "hillshade_raster",
                hillshade_path,
                "image/tiff",
            )
            elevation_tint_artifact = _artifact(
                run.worker_run_id,
                "elevation-tint-overlay",
                "elevation_tint_overlay",
                elevation_tint_path,
                "image/png",
                width_px=int(dem_analysis_extent["width"]),
                height_px=int(dem_analysis_extent["height"]),
                visualization_only=True,
            )
            hillshade_overlay_artifact = _artifact(
                run.worker_run_id,
                "hillshade-overlay",
                "hillshade_overlay",
                hillshade_overlay_path,
                "image/png",
                width_px=int(dem_analysis_extent["width"]),
                height_px=int(dem_analysis_extent["height"]),
                visualization_only=True,
            )
            slope_shading_artifact = _artifact(
                run.worker_run_id,
                "slope-shading-overlay",
                "slope_shading_overlay",
                slope_shading_path,
                "image/png",
                width_px=int(dem_analysis_extent["width"]),
                height_px=int(dem_analysis_extent["height"]),
                visualization_only=True,
            )
            contours_overlay_artifact = _artifact(
                run.worker_run_id,
                "contours-overlay",
                "contours_overlay",
                contours_overlay_path,
                "image/png",
                width_px=int(terrain_surface_processing["contour_pixel_width"]),
                height_px=int(terrain_surface_processing["contour_pixel_height"]),
                visualization_only=True,
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
            contour_vector_artifact = _artifact(
                run.worker_run_id,
                "contour-lines-vector",
                "contour_lines_vector",
                contour_geojson_path,
                "application/geo+json",
                visualization_only=True,
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
            surface_manifest_artifact = _artifact(
                run.worker_run_id,
                "terrain-surface-manifest",
                "terrain_surface_manifest",
                surface_manifest_path,
                "application/json",
                visualization_only=True,
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
                dem_artifact,
                slope_artifact,
                aspect_artifact,
                hillshade_artifact,
                elevation_tint_artifact,
                hillshade_overlay_artifact,
                slope_shading_artifact,
                contour_vector_artifact,
                contours_overlay_artifact,
                surface_manifest_artifact,
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
                *(
                    ["gdal:warpreproject"]
                    if dem_normalized_source_count
                    else []
                ),
                *(["gdal:buildvirtualraster"] if len(dem_refs) > 1 else []),
                "gdal:cliprasterbyextent",
                "grass:r.slope.aspect",
                "grass:r.relief",
                "grass:r.contour",
                "grass:r.geomorphon",
                "grass:r.mapcalc.simple",
                "grass:r.thin",
                "grass:r.to.vect",
                "grass:r.watershed",
                "native:dissolve",
                "native:extractbyexpression",
                "gdal:rasterize",
                "gdal:colorrelief",
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
                    "status": "route_rectangle_rendered",
                    "analysis_extent": dem_analysis_extent,
                    "preserves_source_evidence_resolution": True,
                    "adds_source_resolution": False,
                    "render_width_px": render_artifact.width_px,
                    "render_height_px": render_artifact.height_px,
                },
                processing_algorithms=processing_algorithms,
                processing_parameters=manifest_payload["parameters"],
                warnings=[
                    *(
                        [
                            "Allowlisted QGIS GDAL Warp normalized south-up XYZ DEM row orientation to north-up GeoTIFF without adding source resolution."
                        ]
                        if dem_normalized_source_count
                        else []
                    ),
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

    def _discover_grass_terrain_route_capabilities(self) -> list[dict[str, Any]]:
        contracts = {
            **{
                algorithm: {**contract, "provider": "grass"}
                for algorithm, contract in _GRASS_TERRAIN_ROUTE_SCHEMAS.items()
            },
            "gdal:colorrelief": _TERRAIN_FEATURE_NORMALIZATION_SCHEMAS[
                "gdal:colorrelief"
            ],
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
    ) -> dict[str, Any]:
        operation = self._call(
            "qgis_processing_start",
            {
                "algorithm": algorithm,
                "parameters": parameters,
                "retain_outputs": True,
                "add_to_project": False,
                "allow_main_thread": algorithm
                in {
                    **_GRASS_TERRAIN_FEATURE_SCHEMAS,
                    **_GRASS_TERRAIN_ROUTE_SCHEMAS,
                },
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
        return status

    def _generate_standard_terrain_surface(
        self,
        *,
        worker_run_id: str,
        dem_input: Path,
        slope_path: Path,
        analysis_extent: dict[str, Any],
        hillshade_path: Path,
        contour_projected_path: Path,
        contour_raster_path: Path,
        elevation_tint_path: Path,
        hillshade_overlay_path: Path,
        slope_shading_path: Path,
        contours_overlay_path: Path,
        elevation_colors_path: Path,
        hillshade_colors_path: Path,
        slope_colors_path: Path,
        contour_colors_path: Path,
        cancel_event: threading.Event,
        added_layers: list[str],
    ) -> dict[str, Any]:
        for path, value in (
            (elevation_colors_path, _ELEVATION_COLOR_RELIEF),
            (hillshade_colors_path, _HILLSHADE_COLOR_RELIEF),
            (slope_colors_path, _SLOPE_COLOR_RELIEF),
            (contour_colors_path, _CONTOUR_COLOR_RELIEF),
        ):
            _write_private_bytes(path, value.encode("ascii"))

        self._run_processing_outputs(
            worker_run_id=worker_run_id,
            algorithm="grass:r.relief",
            parameters={
                "input": str(dem_input),
                "altitude": 45.0,
                "azimuth": 315.0,
                "zscale": 1.0,
                "scale": 1.0,
                "units": 0,
                "output": str(hillshade_path),
                "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
            },
            output_paths=(hillshade_path,),
            cancel_event=cancel_event,
            added_layers=added_layers,
        )
        self._run_processing_outputs(
            worker_run_id=worker_run_id,
            algorithm="grass:r.contour",
            parameters={
                "input": str(dem_input),
                "step": _TERRAIN_CONTOUR_INTERVAL_M,
                "levels": "",
                "minlevel": None,
                "maxlevel": None,
                "cut": 2,
                "output": str(contour_projected_path),
                "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
                "GRASS_OUTPUT_TYPE_PARAMETER": 2,
                "GRASS_VECTOR_DSCO": "",
                "GRASS_VECTOR_LCO": "",
                "GRASS_VECTOR_EXPORT_NOCAT": False,
            },
            output_paths=(contour_projected_path,),
            cancel_event=cancel_event,
            added_layers=added_layers,
        )

        bbox = analysis_extent["bbox_twd97"]
        span_x = float(bbox["max_x"]) - float(bbox["min_x"])
        span_y = float(bbox["max_y"]) - float(bbox["min_y"])
        source_resolution_m = float(analysis_extent["resolution_m"])
        contour_visual_resolution_m = max(
            5.0,
            source_resolution_m / 2.0,
            span_x / _MAX_TERRAIN_SURFACE_DIMENSION,
            span_y / _MAX_TERRAIN_SURFACE_DIMENSION,
        )
        contour_visual_resolution_m = math.ceil(
            contour_visual_resolution_m * 10.0
        ) / 10.0
        self._run_processing_outputs(
            worker_run_id=worker_run_id,
            algorithm="gdal:rasterize",
            parameters={
                "INPUT": str(contour_projected_path),
                "FIELD": None,
                "BURN": 255.0,
                "USE_Z": False,
                "UNITS": 1,
                "WIDTH": contour_visual_resolution_m,
                "HEIGHT": contour_visual_resolution_m,
                "EXTENT": analysis_extent["qgis_extent"],
                "NODATA": 0.0,
                "CREATION_OPTIONS": "",
                "DATA_TYPE": 0,
                "INIT": 0.0,
                "INVERT": False,
                "EXTRA": "",
                "OUTPUT": str(contour_raster_path),
            },
            output_paths=(contour_raster_path,),
            cancel_event=cancel_event,
            added_layers=added_layers,
        )
        for source, colors, output in (
            (dem_input, elevation_colors_path, elevation_tint_path),
            (hillshade_path, hillshade_colors_path, hillshade_overlay_path),
            (slope_path, slope_colors_path, slope_shading_path),
            (contour_raster_path, contour_colors_path, contours_overlay_path),
        ):
            self._run_processing_outputs(
                worker_run_id=worker_run_id,
                algorithm="gdal:colorrelief",
                parameters={
                    "INPUT": str(source),
                    "BAND": 1,
                    "COMPUTE_EDGES": False,
                    "COLOR_TABLE": str(colors),
                    "MATCH_MODE": 2,
                    "CREATION_OPTIONS": "",
                    "EXTRA": "-alpha",
                    "OUTPUT": str(output),
                },
                output_paths=(output,),
                cancel_event=cancel_event,
                added_layers=added_layers,
            )
        return {
            "contour_interval_m": _TERRAIN_CONTOUR_INTERVAL_M,
            "contour_visual_resolution_m": contour_visual_resolution_m,
            "contour_pixel_width": int(math.ceil(span_x / contour_visual_resolution_m)),
            "contour_pixel_height": int(math.ceil(span_y / contour_visual_resolution_m)),
        }

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
        max_geojson_bytes: int = 16 * 1024 * 1024,
        max_coordinate_count: int = 500_000,
        workflow_id: str = TERRAIN_FEATURE_STACK_WORKFLOW_ID,
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
        if output_path.stat().st_size > max_geojson_bytes:
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
            max_coordinate_count=max_coordinate_count,
            workflow_id=workflow_id,
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
                "elevation_m": sampled_values["elevation_m"],
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
                "schema_version": "scout_qgis_terrain_feature_route_samples.v0_2",
                "workflow_id": TERRAIN_FEATURE_STACK_WORKFLOW_ID,
                "workflow_run_id": run.worker_run_id,
                "actual_processor": "qgis_processing_grass",
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
                "fixture": False,
                "synthetic": False,
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
            "contour": ("#ded8c7", 0.7),
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
        source_resolution: dict[str, Any],
        route_extent: Any,
        corridor_m: float,
        cancel_event: threading.Event,
    ) -> tuple[Path, int, float, dict[str, Any]]:
        normalized_refs: list[Path] = []
        normalization_resolution_m: float | None = None
        normalized_source_count = 0
        for index, dem_ref in enumerate(dem_refs):
            if dem_ref.suffix.casefold() != ".grd":
                normalized_refs.append(dem_ref)
                continue
            if normalization_resolution_m is None:
                normalization_resolution_m = _square_source_resolution(
                    source_resolution
                )
            output_path = (
                self._run_root(worker_run_id)
                / f"dem_source_{index + 1:02d}_north_up.tif"
            )
            operation = self._call(
                "qgis_processing_start",
                {
                    "algorithm": "gdal:warpreproject",
                    "parameters": {
                        "INPUT": str(dem_ref),
                        "SOURCE_CRS": "EPSG:3826",
                        "TARGET_CRS": "EPSG:3826",
                        "RESAMPLING": 0,
                        "NODATA": None,
                        "TARGET_RESOLUTION": normalization_resolution_m,
                        "CREATION_OPTIONS": "",
                        "DATA_TYPE": 0,
                        "TARGET_EXTENT": None,
                        "TARGET_EXTENT_CRS": None,
                        "MULTITHREADING": False,
                        "EXTRA": "",
                        "OUTPUT": str(output_path),
                    },
                    "retain_outputs": True,
                    "add_to_project": False,
                    "allow_main_thread": False,
                },
            )
            self._poll_operation(
                worker_run_id,
                _operation_id(operation),
                cancel_event,
            )
            if not output_path.is_file():
                raise _WorkerProcessingFailed(
                    "QGIS XYZ north-up normalization output file was not created"
                )
            normalized_refs.append(output_path)
            normalized_source_count += 1

        prepared_refs = tuple(normalized_refs)
        if len(prepared_refs) == 1:
            prepared_source = prepared_refs[0]
        else:
            vrt_path = self._run_root(worker_run_id) / "dem_mosaic.vrt"
            operation = self._call(
                "qgis_processing_start",
                {
                    "algorithm": "gdal:buildvirtualraster",
                    "parameters": {
                        "INPUT": [str(path) for path in prepared_refs],
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
            prepared_source = vrt_path

        resolution_m = normalization_resolution_m or _square_source_resolution(
            source_resolution
        )
        analysis_extent = _route_rectangle_extent(
            route_extent,
            corridor_m=corridor_m,
            resolution_m=resolution_m,
        )
        clipped_path = self._run_root(worker_run_id) / "dem_route_bbox.tif"
        operation = self._call(
            "qgis_processing_start",
            {
                "algorithm": "gdal:cliprasterbyextent",
                "parameters": {
                    "INPUT": str(prepared_source),
                    "PROJWIN": analysis_extent["qgis_extent"],
                    "OVERCRS": False,
                    "NODATA": None,
                    "CREATION_OPTIONS": "",
                    "DATA_TYPE": 0,
                    "EXTRA": "",
                    "OUTPUT": str(clipped_path),
                },
                "retain_outputs": True,
                "add_to_project": False,
                "allow_main_thread": False,
            },
        )
        self._poll_operation(worker_run_id, _operation_id(operation), cancel_event)
        if not clipped_path.is_file():
            raise _WorkerProcessingFailed("QGIS route-bbox DEM clip was not created")
        assignment = self._call(
            "qgis_processing_start",
            {
                "algorithm": "gdal:assignprojection",
                "parameters": {"INPUT": str(clipped_path), "CRS": "EPSG:3826"},
                "retain_outputs": True,
                "add_to_project": False,
                "allow_main_thread": False,
            },
        )
        self._poll_operation(worker_run_id, _operation_id(assignment), cancel_event)
        return (
            clipped_path,
            normalized_source_count,
            resolution_m,
            analysis_extent,
        )

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
                    TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
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
    @app.post(
        "/workflows/terrain_route_hypothesis.v1",
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
    if workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID:
        values = (
            ("input_validation", "Input validation", SpatialCapabilityCategory.TERRAIN),
            ("crs_inspection", "CRS inspection", SpatialCapabilityCategory.PROJECT),
            ("endpoint_preparation", "A/B endpoint preparation", SpatialCapabilityCategory.VECTOR),
            ("dem_loaded", "DEM and NoData audit", SpatialCapabilityCategory.RASTER),
            ("capability_discovery", "GRASS route capability discovery", SpatialCapabilityCategory.PROCESSING),
            ("slope_friction_generated", "Slope friction generated", SpatialCapabilityCategory.TERRAIN),
            ("walk_path_generated", "Anisotropic walk path generated", SpatialCapabilityCategory.TERRAIN),
            ("corridor_cost_generated", "Symmetric corridor costs generated", SpatialCapabilityCategory.TERRAIN),
            ("corridor_bands_generated", "Candidate corridor bands generated", SpatialCapabilityCategory.CARTOGRAPHY),
            ("hypothesis_validated", "Hypothesis and provenance validated", SpatialCapabilityCategory.TERRAIN),
            ("evidence_review_pending", "Evidence review pending", SpatialCapabilityCategory.CARTOGRAPHY),
        )
    elif workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID:
        values = (
            ("input_validation", "Input validation", SpatialCapabilityCategory.TERRAIN),
            ("crs_inspection", "CRS inspection", SpatialCapabilityCategory.PROJECT),
            ("route_preparation", "Route preparation", SpatialCapabilityCategory.VECTOR),
            ("dem_loaded", "DEM loaded", SpatialCapabilityCategory.RASTER),
            ("capability_discovery", "GRASS capability discovery", SpatialCapabilityCategory.PROCESSING),
            ("slope_aspect_generated", "Slope and aspect generated", SpatialCapabilityCategory.TERRAIN),
            ("terrain_surface_generated", "Rectangular terrain surface generated", SpatialCapabilityCategory.CARTOGRAPHY),
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


def _bounded_mcp_exception_detail(exc: QgisMcpError) -> str:
    details: list[str] = []

    def append(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in details:
            details.append(text[:500])

    append(str(exc))
    if isinstance(exc, QgisMcpToolError):
        error = exc.payload.get("error")
        if isinstance(error, dict):
            append(error.get("code"))
            append(error.get("message"))
            data = error.get("data")
            if isinstance(data, dict):
                append(data.get("reason"))
                append(data.get("detail"))
    suffix = "; ".join(details)
    return f"{type(exc).__name__}: {suffix}" if suffix else type(exc).__name__


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
    content: list[tuple[int, int]] = []
    frame_margin = 2 if width >= 5 and height >= 5 else 1
    background_counts: Counter[tuple[int, ...]] = Counter()
    for row in rows[frame_margin : height - frame_margin]:
        for x in range(frame_margin, width - frame_margin):
            offset = x * channels
            pixel = tuple(row[offset : offset + channels])
            if channels == 4 and pixel[3] <= 8:
                continue
            background_counts[pixel[:3]] += 1
    if not background_counts:
        return raw, {
            "applied": False,
            "reason": "no_opaque_pixels",
            "original_width": width,
            "original_height": height,
            "ignored_frame_margin_px": frame_margin,
            "adds_source_resolution": False,
        }
    background = background_counts.most_common(1)[0][0]
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
    frame_margin = 2 if width >= 5 and height >= 5 else 1
    interior: list[tuple[int, ...]] = []
    for row in rows[frame_margin : height - frame_margin]:
        for x in range(frame_margin, width - frame_margin):
            offset = x * channels
            pixel = tuple(row[offset : offset + channels])
            if channels == 4 and pixel[3] <= 8:
                continue
            interior.append(pixel)
    if not interior:
        raise _WorkerRenderFailed("QGIS screenshot PNG has no opaque review pixels")
    background = Counter(pixel[:3] for pixel in interior).most_common(1)[0][0]
    interior_pixels = len(interior)
    content_pixels = 0
    for pixel in interior:
        if any(abs(pixel[index] - background[index]) > 12 for index in range(3)):
            content_pixels += 1
    required = max(4, math.ceil(interior_pixels * 0.001))
    minimum_width_px = 320
    minimum_height_px = 180
    dimensions_passed = (
        width >= minimum_width_px and height >= minimum_height_px
    )
    return {
        "passed": dimensions_passed and content_pixels >= required,
        "dimensions_passed": dimensions_passed,
        "minimum_width_px": minimum_width_px,
        "minimum_height_px": minimum_height_px,
        "width": width,
        "height": height,
        "background_rgb": list(background),
        "ignored_frame_margin_px": frame_margin,
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


def _compact_number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


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


def _route_rectangle_extent(
    value: Any,
    *,
    corridor_m: float,
    resolution_m: float,
) -> dict[str, Any]:
    xmin, ymin, xmax, ymax = _extent_values(value, label="Prepared route")
    if not math.isfinite(corridor_m) or not 0 <= corridor_m <= 5000:
        raise _WorkerProcessingFailed("Route rectangle margin is outside the bounded range")
    if not math.isfinite(resolution_m) or not 0 < resolution_m <= 1000:
        raise _WorkerProcessingFailed("Route rectangle resolution is unavailable")
    bounded_xmin = math.floor((xmin - corridor_m) / resolution_m) * resolution_m
    bounded_ymin = math.floor((ymin - corridor_m) / resolution_m) * resolution_m
    bounded_xmax = math.ceil((xmax + corridor_m) / resolution_m) * resolution_m
    bounded_ymax = math.ceil((ymax + corridor_m) / resolution_m) * resolution_m
    width = int(round((bounded_xmax - bounded_xmin) / resolution_m))
    height = int(round((bounded_ymax - bounded_ymin) / resolution_m))
    if (
        width < 1
        or height < 1
        or width > _MAX_TERRAIN_SURFACE_DIMENSION
        or height > _MAX_TERRAIN_SURFACE_DIMENSION
        or width * height > _MAX_TERRAIN_SURFACE_CELLS
    ):
        raise _WorkerProcessingFailed(
            "Route rectangle exceeds the bounded terrain surface dimensions"
        )
    corners = [
        twd97_to_wgs84(x, y)
        for x, y in (
            (bounded_xmin, bounded_ymin),
            (bounded_xmin, bounded_ymax),
            (bounded_xmax, bounded_ymin),
            (bounded_xmax, bounded_ymax),
        )
    ]
    latitudes = [lat for lat, _lon in corners]
    longitudes = [lon for _lat, lon in corners]
    return {
        "scope": "full_route_extent_rectangle",
        "crs": "EPSG:3826",
        "margin_m": corridor_m,
        "resolution_m": resolution_m,
        "width": width,
        "height": height,
        "cell_count": width * height,
        "bbox_twd97": {
            "min_x": bounded_xmin,
            "min_y": bounded_ymin,
            "max_x": bounded_xmax,
            "max_y": bounded_ymax,
        },
        "bbox_wgs84": {
            "west": min(longitudes),
            "south": min(latitudes),
            "east": max(longitudes),
            "north": max(latitudes),
        },
        "qgis_extent": ",".join(
            _compact_number(item)
            for item in (bounded_xmin, bounded_xmax, bounded_ymin, bounded_ymax)
        ),
    }


def _terrain_route_raster_analysis_extent(
    requested_extent: dict[str, Any],
    raster_summary: dict[str, Any],
) -> dict[str, Any]:
    try:
        width_number = float(raster_summary.get("width"))
        height_number = float(raster_summary.get("height"))
    except (TypeError, ValueError) as exc:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
            "The clipped terrain route DEM grid dimensions are unavailable.",
        ) from exc
    if (
        not math.isfinite(width_number)
        or not math.isfinite(height_number)
        or width_number < 1
        or height_number < 1
        or not width_number.is_integer()
        or not height_number.is_integer()
    ):
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
            "The clipped terrain route DEM grid dimensions are invalid.",
        )
    width = int(width_number)
    height = int(height_number)
    if (
        width > _MAX_TERRAIN_SURFACE_DIMENSION
        or height > _MAX_TERRAIN_SURFACE_DIMENSION
        or width * height > _MAX_TERRAIN_SURFACE_CELLS
    ):
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
            "The clipped terrain route DEM grid exceeds bounded dimensions.",
        )

    xmin, ymin, xmax, ymax = _extent_values(
        raster_summary.get("extent"),
        label="Clipped terrain route DEM",
    )
    expected_resolution = float(requested_extent["resolution_m"])
    x_resolution = (xmax - xmin) / width
    y_resolution = (ymax - ymin) / height
    if not (
        math.isclose(x_resolution, expected_resolution, rel_tol=1e-6, abs_tol=1e-6)
        and math.isclose(y_resolution, expected_resolution, rel_tol=1e-6, abs_tol=1e-6)
    ):
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.INVALID_INPUT,
            "The clipped terrain route DEM grid resolution does not match provenance.",
        )

    corners = [
        twd97_to_wgs84(x, y)
        for x, y in (
            (xmin, ymin),
            (xmin, ymax),
            (xmax, ymin),
            (xmax, ymax),
        )
    ]
    latitudes = [lat for lat, _lon in corners]
    longitudes = [lon for _lat, lon in corners]
    return {
        **requested_extent,
        "grid_alignment": "source_dem_grid",
        "requested_grid": {
            "width": int(requested_extent["width"]),
            "height": int(requested_extent["height"]),
            "cell_count": int(requested_extent["cell_count"]),
            "bbox_twd97": dict(requested_extent["bbox_twd97"]),
        },
        "width": width,
        "height": height,
        "cell_count": width * height,
        "bbox_twd97": {
            "min_x": xmin,
            "min_y": ymin,
            "max_x": xmax,
            "max_y": ymax,
        },
        "bbox_wgs84": {
            "west": min(longitudes),
            "south": min(latitudes),
            "east": max(longitudes),
            "north": max(latitudes),
        },
        "qgis_extent": ",".join(
            _compact_number(item) for item in (xmin, xmax, ymin, ymax)
        ),
    }


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


def _terrain_route_endpoint_geojson(
    route_geojson: dict[str, Any],
) -> tuple[dict[str, Any], tuple[float, float], tuple[float, float]]:
    coordinates = _route_line_coordinates(route_geojson)
    start = (float(coordinates[0][0]), float(coordinates[0][1]))
    destination = (float(coordinates[-1][0]), float(coordinates[-1][1]))
    if _haversine_m(start[1], start[0], destination[1], destination[0]) < 1.0:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.ENDPOINTS_COINCIDENT,
            "Terrain route endpoints A and B are not spatially distinct.",
        )
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": coordinates,
                },
                "properties": {
                    "kind": "terrain_route_endpoint_baseline",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                },
            }
        ],
    }
    return payload, start, destination


def _terrain_route_destination_geojson(
    destination_wgs84: tuple[float, float],
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": list(destination_wgs84),
                },
                "properties": {
                    "kind": "terrain_route_destination",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                },
            }
        ],
    }


def _require_route_endpoints_inside_extent(
    start: tuple[float, float],
    destination: tuple[float, float],
    extent: Any,
) -> None:
    xmin, ymin, xmax, ymax = _extent_values(extent, label="Terrain route DEM")
    for label, (x, y) in (("A", start), ("B", destination)):
        if not xmin <= x <= xmax or not ymin <= y <= ymax:
            raise _WorkerTerrainRouteUnavailable(
                SpatialAnalysisErrorCode.ENDPOINT_OUTSIDE_DEM,
                f"Terrain route endpoint {label} is outside the DEM extent.",
            )


def _parse_grass_univar_report(path: Path) -> dict[str, float | int]:
    text = _grass_report_text(path)
    values: dict[str, float | int] = {}
    table_aliases = {
        "n": "n",
        "non_null_cells": "n",
        "null_cells": "null_cells",
        "cells": "cells",
        "total_cells": "cells",
        "min": "min",
        "minimum": "min",
        "max": "max",
        "maximum": "max",
        "mean": "mean",
    }
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        headers = [
            re.sub(r"[\s-]+", "_", item.strip().lower())
            for item in line.split("|")
        ]
        if "non_null_cells" not in headers and "n" not in headers:
            continue
        row = [item.strip() for item in lines[index + 1].split("|")]
        if len(row) != len(headers):
            raise _WorkerProcessingFailed(
                "GRASS univariate report table has inconsistent columns"
            )
        for header, raw_value in zip(headers, row, strict=True):
            target = table_aliases.get(header)
            if target is None:
                continue
            try:
                number = float(raw_value)
            except ValueError:
                continue
            if target in {"n", "null_cells", "cells"}:
                if (
                    not math.isfinite(number)
                    or number < 0
                    or not number.is_integer()
                ):
                    raise _WorkerProcessingFailed(
                        "GRASS univariate report contains an invalid cell count"
                    )
                values[target] = int(number)
            elif math.isfinite(number):
                values[target] = number
        break
    aliases = {
        "n": ("n", "non_null_cells", "non-null cells"),
        "null_cells": ("null_cells", "null cells"),
        "cells": ("cells", "total_cells", "total cells"),
        "min": ("min", "minimum"),
        "max": ("max", "maximum"),
        "mean": ("mean",),
    }
    for target, names in aliases.items():
        if target in values:
            continue
        for name in names:
            match = re.search(
                rf"(?im)(?:^|[|\n])\s*{re.escape(name)}\s*(?:=|:|[|])\s*"
                r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)",
                text,
            )
            if not match:
                continue
            number = float(match.group(1))
            values[target] = int(number) if target in {"n", "null_cells", "cells"} else number
            break
    if "n" not in values:
        raise _WorkerProcessingFailed("GRASS univariate report omitted finite-cell count")
    values.setdefault("null_cells", 0)
    values.setdefault("cells", int(values["n"]) + int(values["null_cells"]))
    return values


def _parse_grass_quantile_report(
    path: Path,
    expected_percentiles: tuple[float, ...],
) -> dict[float, float]:
    text = _grass_report_text(path)
    thresholds: dict[float, float] = {}
    number_pattern = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    for line in text.splitlines():
        numbers = [float(value) for value in re.findall(number_pattern, line)]
        if len(numbers) < 2:
            continue
        for percentile in expected_percentiles:
            if any(math.isclose(value, percentile, abs_tol=1e-7) for value in numbers[:-1]):
                threshold = float(numbers[-1])
                if math.isfinite(threshold) and threshold >= 0:
                    thresholds[float(percentile)] = threshold
    missing = [
        float(value)
        for value in expected_percentiles
        if float(value) not in thresholds
    ]
    if missing:
        raise _WorkerProcessingFailed(
            "GRASS quantile report omitted percentiles: "
            + ", ".join(_compact_number(value) for value in missing)
        )
    ordered = [thresholds[float(value)] for value in expected_percentiles]
    if ordered != sorted(ordered):
        raise _WorkerProcessingFailed("GRASS quantile thresholds are not monotonic")
    return thresholds


def _grass_report_text(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _WorkerProcessingFailed("GRASS report is unavailable") from exc
    if len(raw.encode("utf-8")) > 2 * 1024 * 1024:
        raise _WorkerProcessingFailed("GRASS report exceeded the bounded size")
    without_tags = re.sub(r"<[^>]+>", "\n", raw)
    return without_tags.replace("&nbsp;", " ").replace("&amp;", "&")


def _normalize_terrain_route_best_path(
    payload: dict[str, Any],
    *,
    start_wgs84: tuple[float, float],
    destination_wgs84: tuple[float, float],
    worker_run_id: str,
    candidate_id: str,
    alternative_index: int,
    label: str,
    strategy: TerrainRouteStrategy,
    drainage_penalty_multiplier: float,
    endpoint_tolerance_m: float,
    path_semantics: str = TERRAIN_ROUTE_PATH_SEMANTICS,
) -> tuple[dict[str, Any], list[list[float]]]:
    if path_semantics not in {
        TERRAIN_ROUTE_PATH_SEMANTICS,
        TERRAIN_ROUTE_GUIDED_PATH_SEMANTICS,
    }:
        raise _WorkerProcessingFailed("Terrain route path semantics are unsupported")
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list) or len(features) != 1:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
            "GRASS r.path did not produce exactly one connected path feature.",
        )
    geometry = features[0].get("geometry") if isinstance(features[0], dict) else None
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
            "GRASS r.path did not produce one LineString hypothesis.",
        )
    coordinates = [
        [float(item[0]), float(item[1])]
        for item in geometry.get("coordinates") or []
        if isinstance(item, list) and len(item) >= 2
    ]
    if not 2 <= len(coordinates) <= _MAX_TERRAIN_ROUTE_PATH_COORDINATES:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
            "GRASS r.path returned an empty or oversized path hypothesis.",
        )
    start_distance = _haversine_m(
        start_wgs84[1], start_wgs84[0], coordinates[0][1], coordinates[0][0]
    )
    destination_distance = _haversine_m(
        destination_wgs84[1],
        destination_wgs84[0],
        coordinates[-1][1],
        coordinates[-1][0],
    )
    reverse_start_distance = _haversine_m(
        start_wgs84[1], start_wgs84[0], coordinates[-1][1], coordinates[-1][0]
    )
    reverse_destination_distance = _haversine_m(
        destination_wgs84[1],
        destination_wgs84[0],
        coordinates[0][1],
        coordinates[0][0],
    )
    if (
        start_distance <= endpoint_tolerance_m
        and destination_distance <= endpoint_tolerance_m
    ):
        oriented = coordinates
    elif (
        reverse_start_distance <= endpoint_tolerance_m
        and reverse_destination_distance <= endpoint_tolerance_m
    ):
        oriented = list(reversed(coordinates))
    else:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
            "GRASS path endpoints do not match A and B within DEM-cell tolerance.",
        )
    feature = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": oriented},
        "properties": {
            "id": f"{worker_run_id}.terrain_route_hypothesis.{candidate_id}",
            "candidate_id": candidate_id,
            "alternative_index": alternative_index,
            "kind": "terrain_route_hypothesis_best_path",
            "feature_class": "terrain_route_hypothesis_best_path",
            "label": label,
            "strategy": strategy.value,
            "drainage_penalty_multiplier": drainage_penalty_multiplier,
            "relative_cost_comparison_scope": "within_profile_only",
            "path_model": TERRAIN_ROUTE_PATH_MODEL,
            "path_semantics": path_semantics,
            "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
            "authority": "candidate_only",
            "source_type": "terrain_hypothesis",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
            "observed": False,
            "official": False,
            "human_verified": False,
            "geometry_orientation": "A_TO_B",
            "not_verified_trail": True,
        },
    }
    return (
        {
            "type": "FeatureCollection",
            "metadata": {
                "schema_version": "scout_terrain_route_best_path.v0_2",
                "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
                "workflow_run_id": worker_run_id,
                "crs": "EPSG:4326",
                "authority": "candidate_only",
                "source_type": "terrain_hypothesis",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "safe_or_walkable": "not_determined",
                "path_model": TERRAIN_ROUTE_PATH_MODEL,
                "path_semantics": path_semantics,
                "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
                "candidate_id": candidate_id,
                "alternative_index": alternative_index,
                "strategy": strategy.value,
                "drainage_penalty_multiplier": drainage_penalty_multiplier,
            },
            "features": [feature],
        },
        oriented,
    )


def _append_guided_segment_coordinates(
    current: list[list[float]],
    segment: list[list[float]],
    *,
    endpoint_tolerance_m: float,
) -> list[list[float]]:
    if len(segment) < 2:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
            "A guided terrain route segment has fewer than two vertices.",
        )
    if not current:
        combined = [list(item) for item in segment]
    else:
        join_distance = _haversine_m(
            current[-1][1],
            current[-1][0],
            segment[0][1],
            segment[0][0],
        )
        if join_distance > endpoint_tolerance_m:
            raise _WorkerTerrainRouteUnavailable(
                SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
                "Reviewed guidance segments did not join within DEM-cell tolerance.",
            )
        combined = [*current, *[list(item) for item in segment[1:]]]
    if len(combined) > _MAX_TERRAIN_ROUTE_PATH_COORDINATES:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.NO_CONNECTED_SOLUTION,
            "The combined guided terrain route exceeds the coordinate limit.",
        )
    return combined


def _combine_terrain_route_best_paths(
    profile_results: list[dict[str, Any]],
    *,
    worker_run_id: str,
) -> dict[str, Any]:
    if not 3 <= len(profile_results) <= 6:
        raise _WorkerProcessingFailed(
            "Terrain route analysis did not produce the configured alternatives"
        )
    features: list[dict[str, Any]] = []
    candidate_ids: list[str] = []
    candidate_path_semantics: dict[str, str] = {}
    geometry_hashes: set[str] = set()
    for item in profile_results:
        payload = item.get("payload")
        profile = item.get("profile")
        raw_features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(raw_features, list) or len(raw_features) != 1:
            raise _WorkerProcessingFailed(
                "Terrain route alternative payload is incomplete"
            )
        feature = raw_features[0]
        candidate_id = str(profile.candidate_id)
        candidate_ids.append(candidate_id)
        features.append(feature)
        candidate_path_semantics[candidate_id] = str(
            feature.get("properties", {}).get("path_semantics") or "unknown"
        )
        geometry_hashes.add(
            hashlib.sha256(
                json.dumps(
                    feature.get("geometry"),
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        )
    if len(candidate_ids) != len(set(candidate_ids)):
        raise _WorkerProcessingFailed("Terrain route alternative IDs are not unique")
    return {
        "type": "FeatureCollection",
        "metadata": {
            "schema_version": "scout_terrain_route_best_path.v0_2",
            "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            "workflow_run_id": worker_run_id,
            "crs": "EPSG:4326",
            "authority": "candidate_only",
            "source_type": "terrain_hypothesis",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
            "path_model": TERRAIN_ROUTE_PATH_MODEL,
            "path_semantics": TERRAIN_ROUTE_PATH_SEMANTICS,
            "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
            "candidate_ids": candidate_ids,
            "candidate_count": len(candidate_ids),
            "distinct_geometry_count": len(geometry_hashes),
            "candidate_path_semantics": candidate_path_semantics,
        },
        "features": features,
    }


def _terrain_route_percentile_name(percentile: float) -> str:
    value = float(percentile)
    rendered = (
        str(int(value))
        if value.is_integer()
        else _compact_number(value).replace(".", "_")
    )
    return f"top_{rendered}_percent_corridor"


def _terrain_route_corridor_color_relief(percentile: float, index: int) -> str:
    predefined = _TERRAIN_ROUTE_CORRIDOR_COLORS.get(float(percentile))
    if predefined is not None:
        return predefined
    palette = (
        (23, 144, 125, 150),
        (36, 112, 177, 125),
        (217, 139, 37, 105),
        (147, 84, 166, 95),
    )
    red, green, blue, alpha = palette[index % len(palette)]
    return f"nv 0 0 0 0\n0 0 0 0 0\n1 {red} {green} {blue} {alpha}\n"


def _terrain_route_raster_reference(
    path: Path,
    *,
    crs: str,
    bbox_wgs84: dict[str, float],
) -> TerrainRasterReference:
    return TerrainRasterReference(
        artifact_ref=path.name,
        sha256=_file_sha256(path),
        media_type="image/png" if path.suffix.casefold() == ".png" else "image/tiff",
        crs=crs,
        bbox_wgs84={key: float(value) for key, value in bbox_wgs84.items()},
    )


def _parent_terrain_manifest_ref(
    source_refs: list[str],
    source_hashes: dict[str, str],
) -> str:
    matches = [
        ref
        for ref in source_refs
        if ref.endswith("terrain_feature_manifest.json")
    ]
    if len(matches) != 1:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
            "Terrain route workflow requires one immutable terrain-feature parent manifest.",
        )
    if matches[0] not in source_hashes:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
            "Terrain-feature parent manifest hash is missing.",
        )
    return matches[0]


def _verified_terrain_route_dem_hashes(
    request: QgisWorkerWorkflowRequest,
    dem_refs: tuple[Path, ...],
) -> tuple[str, ...]:
    if len(request.dem_refs) != len(dem_refs) or not dem_refs:
        raise _WorkerTerrainRouteUnavailable(
            SpatialAnalysisErrorCode.INVALID_INPUT,
            "Terrain route DEM source binding is incomplete.",
        )
    declared_hashes = tuple(request.source_hashes.values())
    verified: list[str] = []
    for dem_path in dem_refs:
        actual = _file_sha256(dem_path)
        if not any(hmac.compare_digest(actual, value) for value in declared_hashes):
            raise _WorkerTerrainRouteUnavailable(
                SpatialAnalysisErrorCode.INVALID_INPUT,
                "Terrain route DEM content does not match a declared source hash.",
            )
        verified.append(actual)
    return tuple(verified)


def _terrain_route_maplibre_geojson(
    best_path_payload: dict[str, Any],
    *,
    start_wgs84: tuple[float, float],
    destination_wgs84: tuple[float, float],
    hypothesis_id: str,
    hypothesis_ids: list[str],
    cache_key: str,
) -> dict[str, Any]:
    features = list(best_path_payload.get("features") or [])
    for role, label, coordinate in (
        ("start", "A", start_wgs84),
        ("destination", "B", destination_wgs84),
    ):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(coordinate)},
                "properties": {
                    "id": f"{hypothesis_id}.{role}",
                    "kind": f"terrain_route_hypothesis_{role}",
                    "feature_class": "terrain_route_hypothesis_endpoint",
                    "label": label,
                    "authority": "candidate_only",
                    "source_type": "terrain_hypothesis",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "safe_or_walkable": "not_determined",
                    "not_verified_trail": True,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "properties": {
            "artifact_kind": "terrain_route_hypothesis_maplibre",
            "hypothesis_id": hypothesis_id,
            "hypothesis_ids": hypothesis_ids,
            "alternative_count": len(hypothesis_ids),
            "cache_key": cache_key,
            "authority": "candidate_only",
            "source_type": "terrain_hypothesis",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
        },
        "features": features,
    }


def _bounded_processing_manifest_parameters(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _bounded_processing_manifest_parameters(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_processing_manifest_parameters(item) for item in value]
    if isinstance(value, str):
        try:
            path = Path(value)
        except (OSError, ValueError):
            return value
        return path.name if path.is_absolute() else value
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    max_coordinate_count: int = 500_000,
    workflow_id: str = TERRAIN_FEATURE_STACK_WORKFLOW_ID,
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
        if coordinate_count > max_coordinate_count:
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
            "workflow_id": workflow_id,
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
            "kind": "qgis_analysis_input_route",
            "feature_class": "qgis_analysis_input_route",
            "label": "Golden Route analysis input reference",
            "project_id": project_id,
            "workflow_run_id": worker_run_id,
            "input_reference": True,
            "generated_by_qgis": False,
            "visualization_only": True,
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


def _bridge_qgis_version(path: Path | None = None) -> str:
    configured = _env_str("QGIS_MCP_CONNECTION_FILE")
    target = path or (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".qgis-mcp" / "connection.json"
    )
    try:
        if not target.is_file() or target.stat().st_size > 64 * 1024:
            return "unavailable"
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unavailable"
    version = payload.get("qgis_version") if isinstance(payload, dict) else None
    if not isinstance(version, str):
        return "unavailable"
    normalized = version.strip()
    if not normalized or len(normalized) > 120 or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._ +()-]*",
        normalized,
    ):
        return "unavailable"
    return normalized


def _parse_grass_version_output(output: str) -> str:
    match = re.search(
        r"\bGRASS(?: GIS)?\s+([0-9]+(?:\.[0-9]+){1,2})\b",
        str(output),
    )
    return match.group(1) if match else "unavailable"


def _host_grass_version() -> str:
    configured = _env_str("SCOUT_GRASS_COMMAND") or "grass"
    executable = shutil.which(configured)
    if executable is None:
        return "unavailable"
    environment = {
        "HOME": os.environ.get("HOME", str(Path.home())),
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C",
        "LC_ALL": "C",
    }
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return _parse_grass_version_output(
        "\n".join((completed.stdout, completed.stderr))
    )


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


def _square_source_resolution(source_resolution: dict[str, Any]) -> float:
    try:
        x_m = float(source_resolution["x_m"])
        y_m = float(source_resolution["y_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _WorkerProcessingFailed(
            "XYZ DEM normalization requires reported x/y source resolution"
        ) from exc
    if (
        not math.isfinite(x_m)
        or not math.isfinite(y_m)
        or not 0 < x_m <= 1000
        or not 0 < y_m <= 1000
        or not math.isclose(x_m, y_m, rel_tol=1e-9, abs_tol=1e-9)
    ):
        raise _WorkerProcessingFailed(
            "XYZ DEM normalization requires a bounded square source resolution"
        )
    return x_m


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
