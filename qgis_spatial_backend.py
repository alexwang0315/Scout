from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import math
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from pydantic import ValidationError

from navigation_terrain_projection_store import (
    NAVIGATION_TERRAIN_PROJECTION_REF,
    compile_navigation_terrain_projection,
    inspect_navigation_terrain_projection,
)
from qgis_spatial_contracts import (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_VERSION,
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    TERRAIN_FEATURE_STACK_WORKFLOW_VERSION,
    TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
    TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_VERSION,
    QgisBackendAvailability,
    QgisBackendStatus,
    QgisProjectContext,
    SpatialAnalysisError,
    SpatialAnalysisErrorCode,
    SpatialAnalysisRequest,
    SpatialArtifact,
    SpatialArtifactStatus,
    SpatialCapability,
    SpatialCapabilityCatalog,
    SpatialCapabilityCategory,
    SpatialEvidenceReviewRequest,
    SpatialRenderArtifact,
    SpatialWorkflowRun,
    SpatialWorkflowState,
    SpatialWorkflowStep,
    SpatialWorkflowStepStatus,
    qgis_candidate_boundary,
)
from qgis_worker_contracts import QgisWorkerRun
from route_matching import load_gpx_route
from terrain_route_hypothesis_artifacts import (
    TerrainRouteCacheKeys,
    build_live_terrain_route_cache_keys,
    build_terrain_route_resolution_identity,
    build_terrain_route_source_identity,
)
from terrain_route_hypothesis_models import (
    TERRAIN_ROUTE_BAND_MODEL,
    TERRAIN_ROUTE_BAND_SEMANTICS,
    TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
    TERRAIN_ROUTE_PATH_MODEL,
    TERRAIN_ROUTE_PATH_SEMANTICS,
    TerrainRouteHypothesis,
    TerrainRouteHypothesisRun,
    TerrainRouteRunStatus,
)
from terrain_route_guidance_workspace import (
    load_reviewed_guidance_execution_plan,
)


QGIS_WORKFLOW_ROOT_REF = "outputs/spatial/qgis"
QGIS_ALLOWED_WORKFLOWS = (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
)
QGIS_ALLOWED_TOOL_IDS = (
    "qgis.context",
    "qgis.project.status",
    "qgis.layers.inspect",
    "qgis.capabilities.processing.search",
    "qgis.capabilities.processing.describe",
    "qgis.processing.slope",
    "qgis.processing.grass.slope_aspect",
    "qgis.processing.grass.relief",
    "qgis.processing.grass.contour",
    "qgis.processing.grass.geomorphon",
    "qgis.processing.grass.geomorphon_consensus",
    "qgis.processing.grass.watershed_stream",
    "qgis.processing.grass.thin",
    "qgis.processing.grass.raster_to_vector",
    "qgis.processing.grass.watershed",
    "qgis.processing.grass.cost",
    "qgis.processing.grass.path",
    "qgis.processing.grass.quantile",
    "qgis.processing.grass.univar",
    "qgis.processing.grass.walk_coords",
    "qgis.processing.gdal.assign_projection",
    "qgis.processing.gdal.clip_raster_by_extent",
    "qgis.processing.gdal.color_relief",
    "qgis.processing.gdal.rasterize",
    "qgis.processing.gdal.warp_reproject",
    "qgis.processing.native.dissolve",
    "qgis.processing.native.extract_by_expression",
    "qgis.raster.identify",
    "qgis.vector.export_candidate_geojson",
    "qgis.render.map_preview",
    "scout.artifact.export",
)
QGIS_BLOCKED_CAPABILITIES = (
    "arbitrary_python",
    "pyqgis_execute",
    "shell",
    "unrestricted_filesystem",
    "browser_direct_mcp",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_TERMINAL_WORKFLOW_STATES = {
    SpatialWorkflowState.COMPLETED,
    SpatialWorkflowState.FAILED,
    SpatialWorkflowState.CANCELLED,
}


class QgisSpatialBackendError(Exception):
    pass


class QgisSpatialNotFound(QgisSpatialBackendError):
    pass


class QgisSpatialTransport(Protocol):
    def get_json(self, url: str, *, timeout_s: float) -> Any:
        ...

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        ...

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        ...


class QgisMcpHttpTransport:
    def __init__(self, *, auth_token: str | None = None) -> None:
        self.auth_token = auth_token

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def get_json(self, url: str, *, timeout_s: float) -> Any:
        request = Request(url, headers=self._headers())
        with urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, url: str, payload: dict[str, Any], *, timeout_s: float) -> Any:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=data,
            method="POST",
            headers=self._headers(content_type="application/json"),
        )
        with urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_bytes(self, url: str, *, timeout_s: float, max_bytes: int) -> bytes:
        request = Request(url, headers=self._headers())
        with urlopen(request, timeout=timeout_s) as response:
            value = response.read(max_bytes + 1)
        if len(value) > max_bytes:
            raise ValueError("QGIS worker artifact exceeded the Scout download limit")
        return value


@dataclass(frozen=True)
class QgisSpatialBackendConfig:
    enabled: bool = False
    worker_url: str | None = None
    worker_token: str | None = None
    timeout_s: float = 30.0
    fixture_mode: bool = False
    local_endpoint_required: bool = True

    @classmethod
    def from_env(cls) -> "QgisSpatialBackendConfig":
        return cls(
            enabled=_env_bool("SCOUT_QGIS_ENABLED", default=False),
            worker_url=_env_str("SCOUT_QGIS_WORKER_URL"),
            worker_token=_env_str("SCOUT_QGIS_WORKER_TOKEN"),
            timeout_s=_env_float(
                "SCOUT_QGIS_TIMEOUT",
                default=30.0,
                floor=0.25,
                ceiling=120.0,
            ),
            fixture_mode=_env_bool("SCOUT_QGIS_FIXTURE_MODE", default=False),
            local_endpoint_required=_env_bool(
                "SCOUT_QGIS_LOCAL_ENDPOINT_REQUIRED",
                default=True,
            ),
        )


class QgisSpatialBackend:
    def __init__(
        self,
        *,
        config: QgisSpatialBackendConfig | None = None,
        transport: QgisSpatialTransport | None = None,
        runtime_audit: Any | None = None,
        now_factory: Any | None = None,
    ) -> None:
        self.config = config or QgisSpatialBackendConfig.from_env()
        self.transport = transport or QgisMcpHttpTransport(
            auth_token=self.config.worker_token
        )
        self.runtime_audit = runtime_audit
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._last_successful_handshake: str | None = None

    @classmethod
    def from_env(
        cls,
        *,
        runtime_audit: Any | None = None,
        now_factory: Any | None = None,
    ) -> "QgisSpatialBackend":
        return cls(
            config=QgisSpatialBackendConfig.from_env(),
            runtime_audit=runtime_audit,
            now_factory=now_factory,
        )

    def status(
        self,
        *,
        project_id: str,
        project_root: Path | None = None,
        project: dict[str, Any] | None = None,
    ) -> QgisBackendStatus:
        project_context = self._project_context(
            project_id=project_id,
            project_root=project_root,
            project=project,
        )
        boundary = qgis_candidate_boundary()
        if not self.config.enabled:
            return QgisBackendStatus(
                availability=QgisBackendAvailability.DISABLED,
                enabled=False,
                configured=False,
                endpoint_configured=bool(self.config.worker_url),
                project_loaded=project_context.project_loaded,
                project_context=project_context,
                warnings=[
                    "SCOUT_QGIS_ENABLED is false; QGIS evidence generation is disabled."
                ],
                boundary=boundary,
            )
        if self.config.fixture_mode:
            return QgisBackendStatus(
                availability=QgisBackendAvailability.AVAILABLE,
                enabled=True,
                configured=True,
                endpoint_configured=bool(self.config.worker_url),
                reachable=True,
                qgis_application_available=False,
                plugin_bridge_available=False,
                project_loaded=project_context.project_loaded,
                capabilities_discoverable=True,
                fixture_mode=True,
                last_successful_handshake=self._touch_handshake(),
                project_context=project_context,
                warnings=[
                    "Fixture mode is enabled; no live QGIS application was confirmed.",
                    "Fixture artifacts are synthetic and non-runtime evidence.",
                ],
                boundary=boundary,
            )
        if not self.config.worker_url:
            return QgisBackendStatus(
                availability=QgisBackendAvailability.NOT_CONFIGURED,
                enabled=True,
                configured=False,
                endpoint_configured=False,
                project_loaded=project_context.project_loaded,
                project_context=project_context,
                warnings=["SCOUT_QGIS_WORKER_URL is not configured."],
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                        message="QGIS worker endpoint is not configured.",
                        retryable=True,
                    )
                ],
                boundary=boundary,
            )
        if not self.config.worker_token or len(self.config.worker_token) < 32:
            return QgisBackendStatus(
                availability=QgisBackendAvailability.NOT_CONFIGURED,
                enabled=True,
                configured=False,
                endpoint_configured=True,
                project_loaded=project_context.project_loaded,
                project_context=project_context,
                warnings=[
                    "SCOUT_QGIS_WORKER_TOKEN is missing or shorter than 32 characters."
                ],
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                        message="Authenticated QGIS worker access is not configured.",
                    )
                ],
                boundary=boundary,
            )
        endpoint_error = self._endpoint_error(self.config.worker_url)
        if endpoint_error is not None:
            return QgisBackendStatus(
                availability=QgisBackendAvailability.ERROR,
                enabled=True,
                configured=False,
                endpoint_configured=True,
                project_loaded=project_context.project_loaded,
                project_context=project_context,
                warnings=[endpoint_error],
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                        message="QGIS worker endpoint failed Scout endpoint policy.",
                        detail=endpoint_error,
                    )
                ],
                boundary=boundary,
            )
        try:
            payload = self.transport.get_json(
                urljoin(self.config.worker_url.rstrip("/") + "/", "status"),
                timeout_s=self.config.timeout_s,
            )
        except TimeoutError as exc:
            return self._unavailable_status(project_context, "QGIS worker status timed out.", exc)
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            return self._unavailable_status(project_context, "QGIS worker status is unavailable.", exc)
        if not isinstance(payload, dict):
            return QgisBackendStatus(
                availability=QgisBackendAvailability.DEGRADED,
                enabled=True,
                configured=True,
                endpoint_configured=True,
                reachable=True,
                project_loaded=project_context.project_loaded,
                backend_degraded=True,
                project_context=project_context,
                errors=[
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                        message="QGIS worker status payload was malformed.",
                        retryable=True,
                    )
                ],
                boundary=boundary,
            )
        qgis_available = _status_capability_available(
            payload,
            explicit_keys=("qgis_application_available", "qgis_available"),
            evidence_keys=("qgis_version",),
        )
        bridge_available = _status_capability_available(
            payload,
            explicit_keys=("plugin_bridge_available", "bridge_available"),
            evidence_keys=("plugin_version", "qgis_mcp_plugin_version"),
        )
        capabilities_discoverable = bool(
            payload.get("capabilities_discoverable")
            or payload.get("capabilities")
            or payload.get("tool_count")
        )
        degraded = not (qgis_available and bridge_available and capabilities_discoverable)
        try:
            worker_availability = QgisBackendAvailability(str(payload.get("availability")))
        except ValueError:
            worker_availability = None
        availability = (
            worker_availability
            if worker_availability
            in {
                QgisBackendAvailability.DISABLED,
                QgisBackendAvailability.NOT_CONFIGURED,
                QgisBackendAvailability.UNAVAILABLE,
                QgisBackendAvailability.ERROR,
            }
            else (
                QgisBackendAvailability.DEGRADED
                if degraded
                else QgisBackendAvailability.AVAILABLE
            )
        )
        worker_errors: list[SpatialAnalysisError] = []
        for value in payload.get("errors") or []:
            try:
                validated = SpatialAnalysisError.model_validate(value)
                worker_errors.append(validated.model_copy(update={"detail": None}))
            except (TypeError, ValueError, ValidationError):
                worker_errors.append(
                    SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.UNKNOWN,
                        message="QGIS worker returned malformed error detail.",
                    )
                )
        return QgisBackendStatus(
            availability=availability,
            enabled=True,
            configured=True,
            endpoint_configured=True,
            reachable=True,
            qgis_application_available=qgis_available,
            plugin_bridge_available=bridge_available,
            project_loaded=project_context.project_loaded,
            capabilities_discoverable=capabilities_discoverable,
            backend_degraded=degraded,
            qgis_version=str(payload.get("qgis_version") or "unavailable"),
            qgis_mcp_plugin_version=str(
                payload.get("qgis_mcp_plugin_version")
                or payload.get("plugin_version")
                or "unavailable"
            ),
            last_successful_handshake=(
                str(payload["last_successful_handshake"])
                if payload.get("last_successful_handshake")
                else self._last_successful_handshake
            ),
            project_context=project_context,
            warnings=[
                warning
                for warning in payload.get("warnings", [])
                if isinstance(warning, str)
            ],
            errors=worker_errors,
            boundary=boundary,
        )

    def capabilities(self) -> SpatialCapabilityCatalog:
        return SpatialCapabilityCatalog(
            categories=[
                SpatialCapabilityCategory.PROJECT,
                SpatialCapabilityCategory.VECTOR,
                SpatialCapabilityCategory.RASTER,
                SpatialCapabilityCategory.PROCESSING,
                SpatialCapabilityCategory.TERRAIN,
                SpatialCapabilityCategory.HYDROLOGY,
                SpatialCapabilityCategory.CARTOGRAPHY,
                SpatialCapabilityCategory.RENDER,
                SpatialCapabilityCategory.LAYOUT,
                SpatialCapabilityCategory.THREE_D,
            ],
            capabilities=[
                SpatialCapability(
                    capability_id="terrain_context_preview",
                    category=SpatialCapabilityCategory.TERRAIN,
                    title="Terrain Context Preview",
                    workflow_ids=[TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID],
                    tool_allowlist=list(QGIS_ALLOWED_TOOL_IDS),
                ),
                SpatialCapability(
                    capability_id="qgis_visual_render",
                    category=SpatialCapabilityCategory.RENDER,
                    title="QGIS Visual Review Render",
                    workflow_ids=[
                        TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
                        TERRAIN_FEATURE_STACK_WORKFLOW_ID,
                        TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
                    ],
                    tool_allowlist=["qgis.render.map_preview", "scout.artifact.export"],
                ),
                SpatialCapability(
                    capability_id="terrain_feature_stack",
                    category=SpatialCapabilityCategory.TERRAIN,
                    title="GRASS Terrain Feature Stack",
                    workflow_ids=[TERRAIN_FEATURE_STACK_WORKFLOW_ID],
                    tool_allowlist=[
                        "qgis.capabilities.processing.search",
                        "qgis.capabilities.processing.describe",
                        "qgis.processing.grass.slope_aspect",
                        "qgis.processing.grass.relief",
                        "qgis.processing.grass.contour",
                        "qgis.processing.grass.geomorphon",
                        "qgis.processing.grass.geomorphon_consensus",
                        "qgis.processing.grass.watershed_stream",
                        "qgis.processing.grass.thin",
                        "qgis.processing.grass.raster_to_vector",
                        "qgis.processing.grass.watershed",
                        "qgis.processing.gdal.assign_projection",
                        "qgis.processing.gdal.clip_raster_by_extent",
                        "qgis.processing.gdal.color_relief",
                        "qgis.processing.gdal.rasterize",
                        "qgis.processing.gdal.warp_reproject",
                        "qgis.raster.identify",
                        "qgis.vector.export_candidate_geojson",
                        "qgis.render.map_preview",
                        "scout.artifact.export",
                    ],
                ),
                SpatialCapability(
                    capability_id="terrain_route_hypothesis",
                    category=SpatialCapabilityCategory.TERRAIN,
                    title="Candidate Terrain Route Hypothesis",
                    workflow_ids=[TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID],
                    tool_allowlist=[
                        "qgis.capabilities.processing.search",
                        "qgis.capabilities.processing.describe",
                        "qgis.processing.grass.slope_aspect",
                        "qgis.processing.grass.cost",
                        "qgis.processing.grass.path",
                        "qgis.processing.grass.quantile",
                        "qgis.processing.grass.univar",
                        "qgis.processing.grass.walk_coords",
                        "qgis.processing.gdal.color_relief",
                        "qgis.raster.identify",
                        "qgis.vector.export_candidate_geojson",
                        "scout.artifact.export",
                    ],
                ),
            ],
            blocked_capabilities=list(QGIS_BLOCKED_CAPABILITIES),
            workflow_allowlist=list(QGIS_ALLOWED_WORKFLOWS),
            tool_allowlist=list(QGIS_ALLOWED_TOOL_IDS),
        )

    def start_workflow(
        self,
        *,
        project_id: str,
        project_root: Path,
        project: dict[str, Any],
        request: SpatialAnalysisRequest,
    ) -> SpatialWorkflowRun:
        if request.project_id and request.project_id != project_id:
            return self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.INVALID_INPUT,
                message="Request project_id does not match the route project.",
            )
        if request.workflow_id not in QGIS_ALLOWED_WORKFLOWS:
            return self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.UNSUPPORTED_TOOL,
                message=f"Workflow is not allowlisted: {request.workflow_id}",
            )
        status = self.status(
            project_id=project_id,
            project_root=project_root,
            project=project,
        )
        if status.availability is QgisBackendAvailability.DISABLED:
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                message="QGIS backend is disabled.",
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        if status.availability in {
            QgisBackendAvailability.NOT_CONFIGURED,
            QgisBackendAvailability.UNAVAILABLE,
            QgisBackendAvailability.ERROR,
        }:
            code = (
                status.errors[0].code
                if status.errors
                else SpatialAnalysisErrorCode.QGIS_UNAVAILABLE
            )
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=code,
                message="QGIS backend is not available for workflow execution.",
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        if (
            self.config.fixture_mode
            and request.workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
        ):
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.GRASS_UNAVAILABLE,
                message=(
                    "Terrain route hypotheses require live QGIS/GRASS evidence; "
                    "fixture mode cannot generate them."
                ),
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        if self.config.fixture_mode:
            return self._run_fixture_terrain_context_preview(
                project_id=project_id,
                project_root=project_root,
                project=project,
                request=request,
                status=status,
            )
        return self._run_worker_terrain_context_preview(
            project_id=project_id,
            project_root=project_root,
            project=project,
            request=request,
            status=status,
        )

    def get_run(self, *, project_root: Path, workflow_run_id: str) -> SpatialWorkflowRun:
        run = self._load_run(project_root=project_root, workflow_run_id=workflow_run_id)
        if (
            run.state in {SpatialWorkflowState.QUEUED, SpatialWorkflowState.RUNNING}
            and run.backend_run_id
            and not self.config.fixture_mode
        ):
            return self._poll_worker_run(project_root=project_root, run=run)
        return run

    def get_latest_run(
        self,
        *,
        project_root: Path,
        workflow_id: str | None = None,
    ) -> SpatialWorkflowRun:
        if workflow_id is not None and workflow_id not in QGIS_ALLOWED_WORKFLOWS:
            raise QgisSpatialBackendError("QGIS workflow is not allowlisted")
        root = _safe_project_path(project_root, QGIS_WORKFLOW_ROOT_REF)
        if not root.is_dir():
            raise QgisSpatialNotFound("QGIS spatial workflow run not found")
        runs: list[SpatialWorkflowRun] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                _validate_safe_id(child.name, "workflow_run_id")
                run = self._load_run(
                    project_root=project_root,
                    workflow_run_id=child.name,
                )
            except (
                OSError,
                ValueError,
                ValidationError,
                json.JSONDecodeError,
                QgisSpatialBackendError,
            ):
                continue
            if workflow_id is None or run.workflow_id == workflow_id:
                runs.append(run)
        if not runs:
            raise QgisSpatialNotFound("QGIS spatial workflow run not found")
        latest = max(
            runs,
            key=lambda item: (item.created_at, item.updated_at, item.workflow_run_id),
        )
        return self.get_run(
            project_root=project_root,
            workflow_run_id=latest.workflow_run_id,
        )

    def _load_run(self, *, project_root: Path, workflow_run_id: str) -> SpatialWorkflowRun:
        path = self._run_root(project_root, workflow_run_id) / "workflow_run.json"
        if not path.is_file():
            raise QgisSpatialNotFound("QGIS spatial workflow run not found")
        return SpatialWorkflowRun.model_validate(_read_json(path))

    def list_artifacts(
        self,
        *,
        project_root: Path,
        workflow_run_id: str,
    ) -> list[SpatialArtifact]:
        run = self._load_run(project_root=project_root, workflow_run_id=workflow_run_id)
        artifacts: list[SpatialArtifact] = []
        artifacts.extend(run.artifacts)
        artifacts.extend(run.render_artifacts)
        return artifacts

    def get_artifact(
        self,
        *,
        project_root: Path,
        workflow_run_id: str,
        artifact_id: str,
    ) -> SpatialArtifact:
        for artifact in self.list_artifacts(
            project_root=project_root,
            workflow_run_id=workflow_run_id,
        ):
            if artifact.artifact_id == artifact_id:
                return artifact
        raise QgisSpatialNotFound("QGIS spatial artifact not found")

    def artifact_path(
        self,
        *,
        project_root: Path,
        workflow_run_id: str,
        artifact_id: str,
    ) -> tuple[SpatialArtifact, Path]:
        artifact = self.get_artifact(
            project_root=project_root,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
        )
        if not artifact.artifact_ref:
            raise QgisSpatialNotFound("QGIS spatial artifact has no file ref")
        path = _safe_project_path(project_root, artifact.artifact_ref)
        if not path.is_file():
            raise QgisSpatialNotFound("QGIS spatial artifact file not found")
        return artifact, path

    def cancel_workflow(
        self,
        *,
        project_root: Path,
        workflow_run_id: str,
        requested_by: str = "dashboard_operator",
    ) -> SpatialWorkflowRun:
        run = self._load_run(project_root=project_root, workflow_run_id=workflow_run_id)
        if run.state in {
            SpatialWorkflowState.COMPLETED,
            SpatialWorkflowState.FAILED,
            SpatialWorkflowState.CANCELLED,
        }:
            return run
        if run.backend_run_id and self.config.worker_url and not self.config.fixture_mode:
            try:
                payload = self.transport.post_json(
                    urljoin(
                        self.config.worker_url.rstrip("/") + "/",
                        f"workflows/{run.backend_run_id}/cancel",
                    ),
                    {"requested_by": requested_by},
                    timeout_s=self.config.timeout_s,
                )
                worker_run = QgisWorkerRun.model_validate(payload)
                return self._normalize_worker_run(
                    project_root=project_root,
                    local_run=run,
                    worker_run=worker_run,
                )
            except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError, ValidationError):
                # The local cancellation below remains fail-closed when the worker cannot respond.
                pass
        now = self._now_iso()
        cancelled = run.model_copy(
            update={
                "state": SpatialWorkflowState.CANCELLED,
                "updated_at": now,
                "completed_at": now,
                "processing_status": "cancelled",
                "render_status": run.render_status,
                "error": SpatialAnalysisError(
                    code=SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                    message="Workflow cancelled by dashboard operator.",
                    retryable=True,
                ),
                "audit_trail": [
                    *run.audit_trail,
                    {
                        "event": "workflow_cancelled",
                        "at": now,
                        "requested_by": requested_by,
                    },
                ],
            }
        )
        self._persist_run(project_root, cancelled)
        return cancelled

    def review_evidence(
        self,
        *,
        project_root: Path,
        workflow_run_id: str,
        request: SpatialEvidenceReviewRequest,
    ) -> SpatialWorkflowRun:
        run = self._load_run(project_root=project_root, workflow_run_id=workflow_run_id)
        if run.state is not SpatialWorkflowState.COMPLETED:
            raise QgisSpatialBackendError(
                "Only a completed QGIS workflow can be recorded as reviewed evidence"
            )
        if not run.artifacts or not run.render_artifacts:
            raise QgisSpatialBackendError(
                "QGIS evidence review requires candidate artifacts and a render artifact"
            )
        if run.human_review_status == "completed":
            return run
        now = self._now_iso()
        reviewed_artifacts = [
            artifact.model_copy(update={"status": SpatialArtifactStatus.REVIEWED_EVIDENCE})
            for artifact in run.artifacts
        ]
        reviewed_render_artifacts = [
            artifact.model_copy(
                update={
                    "status": SpatialArtifactStatus.REVIEWED_EVIDENCE,
                    "visual_review_status": "completed",
                }
            )
            for artifact in run.render_artifacts
        ]
        reviewed_steps = [
            step.model_copy(
                update={
                    "label": "Evidence review",
                    "status": SpatialWorkflowStepStatus.COMPLETED,
                    "started_at": step.started_at or now,
                    "completed_at": now,
                    "warning": (
                        "Evidence review recorded; candidate-only authority remains unchanged."
                    ),
                }
            )
            if step.step_id == "evidence_review_pending"
            else step
            for step in run.steps
        ]
        reviewed = run.model_copy(
            update={
                "updated_at": now,
                "visual_review_status": "completed",
                "human_review_status": "completed",
                "steps": reviewed_steps,
                "artifacts": reviewed_artifacts,
                "render_artifacts": reviewed_render_artifacts,
                "audit_trail": [
                    *run.audit_trail,
                    {
                        "event": "evidence_review_recorded",
                        "at": now,
                        "reviewed_by": request.reviewed_by,
                        "decision": request.decision,
                        "review_note": request.review_note,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "operational": False,
                    },
                ],
            }
        )
        self._persist_run(project_root, reviewed)
        return reviewed

    def _run_fixture_terrain_context_preview(
        self,
        *,
        project_id: str,
        project_root: Path,
        project: dict[str, Any],
        request: SpatialAnalysisRequest,
        status: QgisBackendStatus,
    ) -> SpatialWorkflowRun:
        now = self._now_iso()
        feature_stack = request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
        workflow_id = (
            TERRAIN_FEATURE_STACK_WORKFLOW_ID
            if feature_stack
            else TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID
        )
        workflow_version = (
            TERRAIN_FEATURE_STACK_WORKFLOW_VERSION
            if feature_stack
            else TERRAIN_CONTEXT_PREVIEW_WORKFLOW_VERSION
        )
        selected_capability = (
            "terrain_feature_stack" if feature_stack else "terrain_context_preview"
        )
        workflow_run_id = self._new_workflow_run_id()
        request_id = request.request_id or f"qgis-request-{uuid4().hex[:12]}"
        route_points, source_refs, source_hashes, route_warning = self._route_points(
            project_root,
            project,
            project_id=project_id,
        )
        if len(route_points) < 2:
            run = self._failed_run(
                project_id=project_id,
                request=request.model_copy(update={"request_id": request_id}),
                code=SpatialAnalysisErrorCode.INVALID_INPUT,
                message=f"Route geometry is unavailable for {request.workflow_id}.",
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        sampled_points = _sample_route_points(route_points, maximum=96)
        worker_feature_collection = self._fixture_geojson(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            route_points=sampled_points,
            corridor_m=request.corridor_m,
        )
        feature_collection, route_geometry = _partition_qgis_analysis_input_route(
            worker_feature_collection
        )
        geojson_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{workflow_run_id}/route_geometry.geojson"
        render_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{workflow_run_id}/qgis_render_preview.fixture.svg"
        metadata_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{workflow_run_id}/artifact_metadata.json"
        feature_manifest_ref = (
            f"{QGIS_WORKFLOW_ROOT_REF}/{workflow_run_id}/terrain_feature_manifest.fixture.json"
            if feature_stack
            else None
        )
        geojson_bytes = _json_bytes(route_geometry)
        render_svg = self._fixture_render_svg(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            route_points=sampled_points,
            corridor_m=request.corridor_m,
        )
        render_bytes = render_svg.encode("utf-8")
        warnings = (
            [
                "Fixture workflow used synthetic terrain feature descriptors; no live GRASS or QGIS Processing result was produced.",
                "No fixture raster may be treated as slope, aspect, geomorphon, or hydrology evidence.",
                "Rendered preview is synthetic non-runtime evidence.",
            ]
            if feature_stack
            else [
                "Fixture workflow used synthetic slope preview; no live QGIS Processing result was produced.",
                "Rendered preview is synthetic non-runtime evidence.",
            ]
        )
        if route_warning:
            warnings.append(route_warning)
        created_at = now
        geojson_artifact = SpatialArtifact(
            artifact_id=f"{workflow_run_id}.route_geometry",
            artifact_type="route_geometry",
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_run_id=workflow_run_id,
            created_at=created_at,
            source_refs=source_refs,
            source_hashes=source_hashes,
            qgis_version="unavailable",
            qgis_mcp_plugin_version="unavailable",
            crs="EPSG:4326",
            source_resolution={"status": "UNKNOWN", "adds_source_resolution": False},
            output_resolution={"geometry_points": len(sampled_points), "unit": "WGS84 coordinates"},
            processing_algorithm=f"fixture.{workflow_id}",
            processing_parameters={
                "corridor_m": request.corridor_m,
                "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
                "fixture_mode": True,
            },
            provenance=self._provenance(
                project_id=project_id,
                request=request,
                status=status,
                workflow_run_id=workflow_run_id,
                selected_capability=selected_capability,
                fixture=True,
            ),
            status=SpatialArtifactStatus.CANDIDATE,
            warnings=warnings,
            artifact_hash=_sha256_bytes(geojson_bytes),
            artifact_ref=geojson_ref,
            media_type="application/geo+json",
            fixture=True,
            synthetic=True,
            adds_source_resolution=False,
        )
        render_artifact = SpatialRenderArtifact(
            artifact_id=f"{workflow_run_id}.qgis_render_preview",
            artifact_type="qgis_render_preview",
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_run_id=workflow_run_id,
            created_at=created_at,
            source_refs=source_refs,
            source_hashes=source_hashes,
            qgis_version="unavailable",
            qgis_mcp_plugin_version="unavailable",
            crs="EPSG:4326",
            source_resolution={"status": "UNKNOWN", "adds_source_resolution": False},
            output_resolution={"width_px": 960, "height_px": 540, "render": "fixture_svg"},
            processing_algorithm="fixture.qgis_render.map_preview",
            processing_parameters={
                "corridor_m": request.corridor_m,
                "tool_allowlist": ["qgis.render.map_preview", "scout.artifact.export"],
                "fixture_mode": True,
            },
            provenance=self._provenance(
                project_id=project_id,
                request=request,
                status=status,
                workflow_run_id=workflow_run_id,
                selected_capability="qgis_visual_render",
                fixture=True,
            ),
            status=SpatialArtifactStatus.CANDIDATE,
            warnings=warnings,
            artifact_hash=_sha256_bytes(render_bytes),
            artifact_ref=render_ref,
            media_type="image/svg+xml",
            fixture=True,
            synthetic=True,
            adds_source_resolution=False,
            width_px=960,
            height_px=540,
            visual_review_status="pending",
        )
        feature_manifest_payload = (
            {
                "schema_version": "scout_terrain_feature_stack.v0_1",
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
                "fixture": True,
                "synthetic": True,
                "non_runtime": True,
                "produced_rasters": [],
                "planned_algorithms": [
                    "grass:r.slope.aspect",
                    "grass:r.geomorphon",
                    "grass:r.watershed",
                ],
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "adds_source_resolution": False,
                "warning": (
                    "Fixture descriptor only; no GRASS/QGIS raster evidence was produced."
                ),
            }
            if feature_stack
            else None
        )
        feature_manifest_bytes = (
            _json_bytes(feature_manifest_payload)
            if feature_manifest_payload is not None
            else None
        )
        feature_manifest_artifact = (
            SpatialArtifact(
                artifact_id=f"{workflow_run_id}.terrain_feature_manifest",
                artifact_type="terrain_feature_manifest",
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                workflow_run_id=workflow_run_id,
                created_at=created_at,
                source_refs=source_refs,
                source_hashes=source_hashes,
                qgis_version="unavailable",
                qgis_mcp_plugin_version="unavailable",
                crs="UNKNOWN",
                source_resolution={
                    "status": "UNKNOWN",
                    "adds_source_resolution": False,
                },
                output_resolution={"status": "fixture_descriptor_only"},
                processing_algorithm=f"fixture.{workflow_id}",
                processing_parameters={"fixture_mode": True},
                provenance=self._provenance(
                    project_id=project_id,
                    request=request,
                    status=status,
                    workflow_run_id=workflow_run_id,
                    selected_capability=selected_capability,
                    fixture=True,
                ),
                status=SpatialArtifactStatus.CANDIDATE,
                warnings=warnings,
                artifact_hash=_sha256_bytes(feature_manifest_bytes or b""),
                artifact_ref=feature_manifest_ref,
                media_type="application/json",
                fixture=True,
                synthetic=True,
                adds_source_resolution=False,
            )
            if feature_stack
            else None
        )
        metadata = {
            "schema_version": "scout_qgis_spatial_artifact_metadata.v0_1",
            "workflow_run_id": workflow_run_id,
            "artifact_ids": [
                geojson_artifact.artifact_id,
                *(
                    [feature_manifest_artifact.artifact_id]
                    if feature_manifest_artifact is not None
                    else []
                ),
                render_artifact.artifact_id,
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": True,
            "synthetic": True,
            "qgis_backend_status": status.model_dump(mode="json"),
            "source_refs": source_refs,
            "source_hashes": source_hashes,
            "crs": "EPSG:4326",
            "source_resolution": {"status": "UNKNOWN"},
            "output_resolution": {"geometry_points": len(sampled_points)},
            "warnings": warnings,
        }
        metadata_bytes = _json_bytes(metadata)
        metadata_artifact = SpatialArtifact(
            artifact_id=f"{workflow_run_id}.metadata",
            artifact_type="workflow_metadata",
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_run_id=workflow_run_id,
            created_at=created_at,
            source_refs=source_refs,
            source_hashes=source_hashes,
            qgis_version="unavailable",
            qgis_mcp_plugin_version="unavailable",
            crs="EPSG:4326",
            source_resolution={"status": "UNKNOWN"},
            output_resolution={"status": "metadata_only"},
            processing_algorithm=f"fixture.{workflow_id}",
            processing_parameters={"fixture_mode": True},
            provenance=self._provenance(
                project_id=project_id,
                request=request,
                status=status,
                workflow_run_id=workflow_run_id,
                selected_capability="artifact_metadata",
                fixture=True,
            ),
            status=SpatialArtifactStatus.CANDIDATE,
            warnings=warnings,
            artifact_hash=_sha256_bytes(metadata_bytes),
            artifact_ref=metadata_ref,
            media_type="application/json",
            fixture=True,
            synthetic=True,
        )
        steps = _completed_steps(now, workflow_id=workflow_id)
        fixture_artifacts = [
            geojson_artifact,
            *(
                [feature_manifest_artifact]
                if feature_manifest_artifact is not None
                else []
            ),
            metadata_artifact,
        ]
        fixture_refs = [
            geojson_ref,
            *([feature_manifest_ref] if feature_manifest_ref is not None else []),
            metadata_ref,
            render_ref,
        ]
        run = SpatialWorkflowRun(
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            requested_by=request.requested_by,
            state=SpatialWorkflowState.COMPLETED,
            created_at=now,
            started_at=now,
            updated_at=now,
            completed_at=now,
            processing_status="completed",
            render_status="completed",
            machine_review_status="not_started",
            visual_review_status="pending",
            human_review_status="pending",
            steps=steps,
            artifacts=fixture_artifacts,
            render_artifacts=[render_artifact],
            artifact_refs=fixture_refs,
            source_refs=source_refs,
            source_hashes=source_hashes,
            maplibre_geojson=feature_collection,
            warnings=warnings,
            audit_trail=[
                {
                    "event": "workflow_started",
                    "at": now,
                    "requested_by": request.requested_by,
                    "request_id": request_id,
                    "selected_capability": selected_capability,
                    "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
                },
                {
                    "event": "workflow_completed",
                    "at": now,
                    "result": "fixture_candidate_artifacts_exported",
                    "artifact_refs": fixture_refs,
                },
            ],
        )
        _write_bytes(_safe_project_path(project_root, geojson_ref), geojson_bytes)
        _write_bytes(_safe_project_path(project_root, render_ref), render_bytes)
        _write_bytes(_safe_project_path(project_root, metadata_ref), metadata_bytes)
        if feature_manifest_ref and feature_manifest_bytes is not None:
            _write_bytes(
                _safe_project_path(project_root, feature_manifest_ref),
                feature_manifest_bytes,
            )
        self._persist_run(project_root, run)
        self._record_workspace_io(
            project_id=project_id,
            artifact_ref=f"{QGIS_WORKFLOW_ROOT_REF}/{workflow_run_id}/workflow_run.json",
            artifact_kind="qgis_spatial_workflow_run",
            record_count=len(run.artifact_refs),
            byte_count=len(_json_bytes(run.model_dump(mode="json"))),
            summary="QGIS spatial fixture workflow run persisted",
        )
        return run

    def _run_worker_terrain_context_preview(
        self,
        *,
        project_id: str,
        project_root: Path,
        project: dict[str, Any],
        request: SpatialAnalysisRequest,
        status: QgisBackendStatus,
    ) -> SpatialWorkflowRun:
        terrain_route = request.workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
        endpoint_selection = request.terrain_route_endpoints if terrain_route else None
        if endpoint_selection is not None:
            endpoint_source_ref = "request://terrain-route-endpoints.v1"
            endpoint_identity = {
                "schema_version": "scout_terrain_route_endpoint_selection.v0_1",
                "start": {
                    "x": endpoint_selection.start.x,
                    "y": endpoint_selection.start.y,
                    "crs": endpoint_selection.start.crs,
                },
                "destination": {
                    "x": endpoint_selection.destination.x,
                    "y": endpoint_selection.destination.y,
                    "crs": endpoint_selection.destination.crs,
                },
            }
            route_points = [
                {
                    "lon": endpoint_selection.start.x,
                    "lat": endpoint_selection.start.y,
                },
                {
                    "lon": endpoint_selection.destination.x,
                    "lat": endpoint_selection.destination.y,
                },
            ]
            source_refs = [endpoint_source_ref]
            source_hashes = {
                endpoint_source_ref: _sha256_bytes(
                    _compact_json_bytes(endpoint_identity)
                )
            }
            route_warning = (
                "Terrain route endpoints came from an explicit candidate-only "
                "request; no GPX trail or safety authority was inferred."
            )
        else:
            endpoint_source_ref = None
            route_points, source_refs, source_hashes, route_warning = self._route_points(
                project_root,
                project,
                project_id=project_id,
            )
        if len(route_points) < 2:
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.INVALID_INPUT,
                message=f"Route geometry is unavailable for {request.workflow_id}.",
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        worker_route_points = (
            [route_points[0], route_points[-1]] if terrain_route else route_points
        )
        if not self.config.worker_url:
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                message="QGIS worker endpoint is not configured.",
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        request_id = request.request_id or f"qgis-request-{uuid4().hex[:12]}"
        guidance_execution_plan = None
        guidance_source_ref = None
        guidance_source_hash = None
        if terrain_route and request.terrain_route_guidance is not None:
            selection = request.terrain_route_guidance
            try:
                guidance_execution_plan = load_reviewed_guidance_execution_plan(
                    project_root,
                    project_id=project_id,
                    guidance_id=selection.guidance_id,
                    review_sha256=selection.review_sha256,
                )
                worker_route_points = [
                    route_points[0],
                    *[
                        {"lon": item.point.x, "lat": item.point.y}
                        for item in guidance_execution_plan.anchors
                    ],
                    route_points[-1],
                ]
                raw_guidance_ref = project.get(
                    "terrain_route_guidance_review_ref"
                )
                if not isinstance(raw_guidance_ref, str):
                    raise ValueError("terrain guidance review ref is unavailable")
                guidance_source_ref = raw_guidance_ref
                guidance_source_hash = _sha256_file(
                    _safe_project_path(project_root, raw_guidance_ref)
                )
            except (OSError, TypeError, ValueError, ValidationError) as exc:
                run = self._failed_run(
                    project_id=project_id,
                    request=request.model_copy(update={"request_id": request_id}),
                    code=SpatialAnalysisErrorCode.INVALID_INPUT,
                    message="Reviewed terrain route guidance is unavailable.",
                    status=status,
                    detail=str(exc),
                )
                self._persist_run(project_root, run)
                return run
        dem_ref = request.dem_ref
        if terrain_route and not dem_ref:
            raw_dem_ref = project.get("terrain_dem_route_bbox_raster_ref")
            dem_ref = (
                raw_dem_ref.strip()
                if isinstance(raw_dem_ref, str) and raw_dem_ref.strip()
                else None
            )
        dem_refs, dem_source_refs, dem_hashes, source_resolution = self._dem_sources(
            project_root=project_root,
            dem_ref=dem_ref,
        )
        if not dem_refs:
            run = self._failed_run(
                project_id=project_id,
                request=request.model_copy(update={"request_id": request_id}),
                code=SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
                message=f"No bounded DEM source is available for {request.workflow_id}.",
                status=status,
            )
            self._persist_run(project_root, run)
            return run
        if terrain_route:
            parent_ref, parent_hash = _terrain_route_parent_manifest_binding(
                project_root=project_root,
                project=project,
            )
            if parent_ref is None or parent_hash is None:
                run = self._failed_run(
                    project_id=project_id,
                    request=request.model_copy(update={"request_id": request_id}),
                    code=SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
                    message=(
                        "Terrain route workflow requires one immutable live "
                        "terrain-feature parent manifest."
                    ),
                    status=status,
                )
                self._persist_run(project_root, run)
                return run
            source_resolution = _terrain_route_parent_source_resolution(
                project_root=project_root,
                parent_ref=parent_ref,
                dem_ref=dem_ref,
            )
            if source_resolution is None:
                run = self._failed_run(
                    project_id=project_id,
                    request=request.model_copy(update={"request_id": request_id}),
                    code=SpatialAnalysisErrorCode.SOURCE_UNAVAILABLE,
                    message=(
                        "Terrain route workflow requires hash-bound DEM resolution "
                        "and CRS metadata from its terrain-feature parent manifest."
                    ),
                    status=status,
                )
                self._persist_run(project_root, run)
                return run
            stable_route_refs = [ref for ref in source_refs if ref != "project.json"]
            stable_route_hashes = {
                ref: value
                for ref, value in source_hashes.items()
                if ref != "project.json"
            }
            combined_source_refs = list(
                dict.fromkeys(
                    [
                        *stable_route_refs,
                        *dem_source_refs,
                        parent_ref,
                        *([guidance_source_ref] if guidance_source_ref else []),
                    ]
                )
            )
            combined_source_hashes = {
                **stable_route_hashes,
                **dem_hashes,
                parent_ref: parent_hash,
                **(
                    {guidance_source_ref: guidance_source_hash}
                    if guidance_source_ref and guidance_source_hash
                    else {}
                ),
            }
            try:
                if len(dem_source_refs) < len(dem_refs):
                    raise ValueError("DEM source hashes are incomplete")
                dem_content_refs = dem_source_refs[-len(dem_refs) :]
                if any(ref not in dem_hashes for ref in dem_content_refs):
                    raise ValueError("DEM source hash binding is incomplete")
                cache_source_identity = build_terrain_route_source_identity(
                    dem_sha256s=tuple(
                        dem_hashes[ref] for ref in dem_content_refs
                    ),
                    parent_manifest_sha256=parent_hash,
                )
                route_cache_keys = build_live_terrain_route_cache_keys(
                    source_hashes=cache_source_identity,
                    source_resolution=build_terrain_route_resolution_identity(
                        source_resolution
                    ),
                    route_coordinates=[
                        [point["lon"], point["lat"]]
                        for point in worker_route_points
                    ],
                    analysis_margin_m=request.corridor_m,
                    cost_config=request.terrain_routing_cost_config,
                    guidance_review_sha256=(
                        guidance_execution_plan.guidance_review_sha256
                        if guidance_execution_plan is not None
                        else None
                    ),
                )
            except (TypeError, ValueError, ValidationError) as exc:
                run = self._failed_run(
                    project_id=project_id,
                    request=request.model_copy(update={"request_id": request_id}),
                    code=SpatialAnalysisErrorCode.INVALID_INPUT,
                    message="Terrain route cache identity could not be compiled.",
                    status=status,
                    detail=str(exc),
                )
                self._persist_run(project_root, run)
                return run
            cached = self._cached_terrain_route_run(
                project_root=project_root,
                project=project,
                cache_keys=route_cache_keys,
            )
            if cached is not None:
                return cached
            _deactivate_terrain_route_hypothesis(project_root=project_root)
        else:
            combined_source_refs = list(
                dict.fromkeys([*source_refs, *dem_source_refs])
            )
            combined_source_hashes = {**source_hashes, **dem_hashes}
            route_cache_keys = None
        payload = {
            "schema_version": "scout_qgis_worker_request.v0_1",
            "workflow_id": request.workflow_id,
            "project_id": project_id,
            "request_id": request_id,
            "requested_by": request.requested_by,
            "corridor_m": request.corridor_m,
            "route_geojson": _line_geojson(worker_route_points),
            "dem_refs": [str(path) for path in dem_refs],
            "source_refs": combined_source_refs,
            "source_hashes": combined_source_hashes,
            "source_resolution": source_resolution,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        }
        if terrain_route:
            payload.update(
                {
                    "terrain_routing_cost_config": (
                        request.terrain_routing_cost_config.model_dump(mode="json")
                    ),
                    "terrain_route_cache_keys": route_cache_keys.model_dump(
                        mode="json"
                    ),
                    **(
                        {
                            "terrain_route_guidance_execution_plan": (
                                guidance_execution_plan.model_dump(mode="json")
                            )
                        }
                        if guidance_execution_plan is not None
                        else {}
                    ),
                }
            )
        try:
            response = self.transport.post_json(
                urljoin(
                    self.config.worker_url.rstrip("/") + "/",
                    f"workflows/{request.workflow_id}",
                ),
                payload,
                timeout_s=self.config.timeout_s,
            )
        except TimeoutError as exc:
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                message="QGIS worker workflow request timed out.",
                status=status,
                detail=str(exc),
            )
            self._persist_run(project_root, run)
            return run
        except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
            run = self._failed_run(
                project_id=project_id,
                request=request,
                code=SpatialAnalysisErrorCode.PROCESSING_FAILED,
                message="QGIS worker workflow request failed.",
                status=status,
                detail=str(exc),
            )
            self._persist_run(project_root, run)
            return run
        try:
            worker_run = QgisWorkerRun.model_validate(response)
            if (
                worker_run.project_id != project_id
                or worker_run.request_id != request_id
                or worker_run.workflow_id != request.workflow_id
            ):
                raise ValueError("QGIS worker run identity did not match the submitted request")
        except (TypeError, ValueError, ValidationError) as exc:
            run = self._failed_run(
                project_id=project_id,
                request=request.model_copy(update={"request_id": request_id}),
                code=SpatialAnalysisErrorCode.PROCESSING_FAILED,
                message="QGIS worker workflow response failed Scout normalization.",
                status=status,
                detail=str(exc),
            )
            self._persist_run(project_root, run)
            return run
        warnings = [*status.warnings, *worker_run.warnings]
        if route_warning:
            warnings.append(route_warning)
        run = SpatialWorkflowRun(
            project_id=project_id,
            workflow_id=request.workflow_id,
            workflow_version=(
                TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_VERSION
                if terrain_route
                else TERRAIN_FEATURE_STACK_WORKFLOW_VERSION
                if request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
                else TERRAIN_CONTEXT_PREVIEW_WORKFLOW_VERSION
            ),
            workflow_run_id=worker_run.worker_run_id,
            backend_run_id=worker_run.worker_run_id,
            request_id=request_id,
            requested_by=request.requested_by,
            state=worker_run.state,
            created_at=worker_run.created_at,
            started_at=worker_run.started_at,
            updated_at=worker_run.updated_at,
            completed_at=worker_run.completed_at,
            processing_status=worker_run.processing_status,
            render_status=worker_run.render_status,
            visual_review_status="pending",
            human_review_status="pending",
            steps=_public_worker_steps(worker_run.steps),
            source_refs=combined_source_refs,
            source_hashes=combined_source_hashes,
            source_resolution=source_resolution,
            warnings=warnings,
            error=_public_worker_error(worker_run.error),
            audit_trail=[
                {
                    "event": "worker_workflow_submitted",
                    "at": self._now_iso(),
                    "request_id": request_id,
                    "backend_run_id": worker_run.worker_run_id,
                    "selected_capability": (
                        "terrain_route_hypothesis"
                        if terrain_route
                        else "terrain_feature_stack"
                        if request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
                        else "terrain_context_preview"
                    ),
                    "source_count": len(dem_refs),
                    "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
                    "endpoint_selection_source": (
                        endpoint_selection.selection_source
                        if endpoint_selection is not None
                        else "workspace_route_geometry"
                    ),
                    "endpoint_source_ref": endpoint_source_ref,
                },
                *worker_run.audit_trail,
            ],
        )
        if run.state in _TERMINAL_WORKFLOW_STATES:
            run = self._normalize_worker_run(
                project_root=project_root,
                local_run=run,
                worker_run=worker_run,
            )
        self._persist_run(project_root, run)
        return run

    def _poll_worker_run(
        self,
        *,
        project_root: Path,
        run: SpatialWorkflowRun,
    ) -> SpatialWorkflowRun:
        if not self.config.worker_url or not run.backend_run_id:
            return run
        try:
            payload = self.transport.get_json(
                urljoin(
                    self.config.worker_url.rstrip("/") + "/",
                    f"workflows/{run.backend_run_id}",
                ),
                timeout_s=self.config.timeout_s,
            )
            worker_run = QgisWorkerRun.model_validate(payload)
            normalized = self._normalize_worker_run(
                project_root=project_root,
                local_run=run,
                worker_run=worker_run,
            )
        except (TimeoutError, OSError, URLError) as exc:
            normalized = run.model_copy(
                update={
                    "updated_at": self._now_iso(),
                    "warnings": [
                        *run.warnings,
                        f"QGIS worker polling is temporarily unavailable: {type(exc).__name__}",
                    ],
                }
            )
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            normalized = self._terminal_worker_error(
                run,
                code=SpatialAnalysisErrorCode.PROCESSING_FAILED,
                message="QGIS worker state failed Scout normalization.",
                detail=str(exc),
            )
        self._persist_run(project_root, normalized)
        return normalized

    def _normalize_worker_run(
        self,
        *,
        project_root: Path,
        local_run: SpatialWorkflowRun,
        worker_run: QgisWorkerRun,
    ) -> SpatialWorkflowRun:
        if (
            worker_run.worker_run_id != local_run.backend_run_id
            or worker_run.project_id != local_run.project_id
            or worker_run.request_id != local_run.request_id
            or worker_run.workflow_id != local_run.workflow_id
        ):
            return self._terminal_worker_error(
                local_run,
                code=SpatialAnalysisErrorCode.PROCESSING_FAILED,
                message="QGIS worker identity changed during polling.",
            )
        common = {
            "state": worker_run.state,
            "started_at": worker_run.started_at,
            "updated_at": worker_run.updated_at,
            "completed_at": worker_run.completed_at,
            "processing_status": worker_run.processing_status,
            "render_status": worker_run.render_status,
            "visual_review_status": "pending",
            "human_review_status": "pending",
            "steps": _public_worker_steps(worker_run.steps),
            "warnings": list(dict.fromkeys([*local_run.warnings, *worker_run.warnings])),
            "error": _public_worker_error(worker_run.error),
            "audit_trail": _merge_audit_trail(
                local_run.audit_trail,
                worker_run.audit_trail,
            ),
        }
        if worker_run.state in {SpatialWorkflowState.QUEUED, SpatialWorkflowState.RUNNING}:
            return local_run.model_copy(update=common)
        if worker_run.state is SpatialWorkflowState.CANCELLED:
            return local_run.model_copy(
                update={
                    **common,
                    "completed_at": worker_run.completed_at or self._now_iso(),
                    "processing_status": "cancelled",
                    "error": _public_worker_error(worker_run.error)
                    or SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
                        message="QGIS worker workflow was cancelled.",
                        retryable=True,
                    ),
                }
            )
        if worker_run.state is SpatialWorkflowState.FAILED:
            return local_run.model_copy(
                update={
                    **common,
                    "completed_at": worker_run.completed_at or self._now_iso(),
                    "processing_status": "failed",
                    "error": _public_worker_error(worker_run.error)
                    or SpatialAnalysisError(
                        code=SpatialAnalysisErrorCode.UNKNOWN,
                        message="QGIS worker failed without typed error detail.",
                    ),
                }
            )
        if worker_run.state is not SpatialWorkflowState.COMPLETED or worker_run.result is None:
            return self._terminal_worker_error(
                local_run,
                code=SpatialAnalysisErrorCode.PROCESSING_FAILED,
                message="QGIS worker returned an unsupported terminal state.",
            )
        try:
            return self._materialize_worker_result(
                project_root=project_root,
                local_run=local_run,
                worker_run=worker_run,
            )
        except (OSError, URLError, TimeoutError, ValueError, QgisSpatialBackendError) as exc:
            return self._terminal_worker_error(
                local_run,
                code=SpatialAnalysisErrorCode.ARTIFACT_EXPORT_FAILED,
                message="QGIS worker artifacts could not be normalized into Scout evidence.",
                detail=str(exc),
            )

    def _materialize_worker_result(
        self,
        *,
        project_root: Path,
        local_run: SpatialWorkflowRun,
        worker_run: QgisWorkerRun,
    ) -> SpatialWorkflowRun:
        result = worker_run.result
        if result is None or not self.config.worker_url:
            raise QgisSpatialBackendError("QGIS worker result is unavailable")
        if local_run.workflow_id == TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID:
            return self._materialize_terrain_route_hypothesis_result(
                project_root=project_root,
                local_run=local_run,
                worker_run=worker_run,
            )
        if local_run.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID:
            return self._materialize_terrain_feature_stack_result(
                project_root=project_root,
                local_run=local_run,
                worker_run=worker_run,
            )
        worker_feature_collection = _validated_candidate_geojson(
            result.maplibre_geojson
        )
        feature_collection, route_geometry = _partition_qgis_analysis_input_route(
            worker_feature_collection
        )
        slope_worker = next(
            (item for item in result.artifacts if item.artifact_type == "slope_raster"),
            None,
        )
        render_worker = next(
            (item for item in result.artifacts if item.artifact_type == "qgis_render_preview"),
            None,
        )
        if slope_worker is None or render_worker is None:
            raise QgisSpatialBackendError("QGIS worker result omitted slope or render evidence")
        slope_bytes = self._worker_artifact_bytes(worker_run.worker_run_id, slope_worker.artifact_id, 256 * 1024 * 1024)
        render_bytes = self._worker_artifact_bytes(worker_run.worker_run_id, render_worker.artifact_id, 16 * 1024 * 1024)
        if _sha256_bytes(slope_bytes) != slope_worker.sha256:
            raise QgisSpatialBackendError("QGIS slope artifact hash mismatch")
        if _sha256_bytes(render_bytes) != render_worker.sha256:
            raise QgisSpatialBackendError("QGIS render artifact hash mismatch")

        run_id = local_run.workflow_run_id
        route_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}/terrain_context_preview.geojson"
        slope_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}/slope.tif"
        render_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}/qgis_render_preview.png"
        metadata_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}/artifact_metadata.json"
        route_bytes = _json_bytes(route_geometry)
        processing_algorithm = (
            "gdal:slope"
            if "gdal:slope" in result.processing_algorithms
            else "UNKNOWN"
        )
        provenance = {
            "schema_version": "scout_qgis_spatial_provenance.v0_1",
            "initiated_by": local_run.requested_by,
            "request_id": local_run.request_id,
            "workflow_id": local_run.workflow_id,
            "workflow_run_id": run_id,
            "backend_run_id": worker_run.worker_run_id,
            "project_id": local_run.project_id,
            "selected_capability": "terrain_context_preview",
            "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
            "blocked_capabilities": list(QGIS_BLOCKED_CAPABILITIES),
            "fixture": False,
            "synthetic": False,
            "created_at": worker_run.completed_at or self._now_iso(),
            "authority": qgis_candidate_boundary().model_dump(mode="json"),
        }
        common = {
            "workflow_id": local_run.workflow_id,
            "workflow_version": local_run.workflow_version,
            "workflow_run_id": run_id,
            "created_at": worker_run.completed_at or self._now_iso(),
            "source_refs": local_run.source_refs,
            "source_hashes": local_run.source_hashes,
            "qgis_version": result.qgis_version,
            "qgis_mcp_plugin_version": result.qgis_mcp_plugin_version,
            "source_resolution": result.source_resolution,
            "provenance": provenance,
            "status": SpatialArtifactStatus.CANDIDATE,
            "warnings": result.warnings,
            "fixture": False,
            "synthetic": False,
            "adds_source_resolution": False,
        }
        route_artifact = SpatialArtifact(
            artifact_id=f"{run_id}.route_geometry",
            artifact_type="route_geometry",
            crs="EPSG:4326",
            output_resolution={"geometry": "MapLibre candidate GeoJSON"},
            processing_algorithm="qgis_project_action.add_vector",
            processing_parameters={"source_crs": "EPSG:4326"},
            artifact_hash=_sha256_bytes(route_bytes),
            artifact_ref=route_ref,
            media_type="application/geo+json",
            **common,
        )
        slope_artifact = SpatialArtifact(
            artifact_id=slope_worker.artifact_id,
            artifact_type="slope_raster",
            crs=result.crs,
            output_resolution=result.output_resolution,
            processing_algorithm=processing_algorithm,
            processing_parameters=result.processing_parameters,
            artifact_hash=slope_worker.sha256,
            artifact_ref=slope_ref,
            media_type=slope_worker.media_type,
            **common,
        )
        render_artifact = SpatialRenderArtifact(
            artifact_id=render_worker.artifact_id,
            artifact_type="qgis_render_preview",
            crs=result.crs,
            output_resolution=result.output_resolution,
            processing_algorithm="qgis_screenshot.canvas",
            processing_parameters={"visual_review_status": "pending"},
            artifact_hash=render_worker.sha256,
            artifact_ref=render_ref,
            media_type=render_worker.media_type,
            width_px=render_worker.width_px,
            height_px=render_worker.height_px,
            visual_review_status="pending",
            **common,
        )
        metadata = {
            "schema_version": "scout_qgis_spatial_artifact_metadata.v0_1",
            "workflow_run_id": run_id,
            "backend_run_id": worker_run.worker_run_id,
            "artifact_ids": [
                route_artifact.artifact_id,
                slope_artifact.artifact_id,
                render_artifact.artifact_id,
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": False,
            "synthetic": False,
            "qgis_version": result.qgis_version,
            "qgis_mcp_plugin_version": result.qgis_mcp_plugin_version,
            "crs": result.crs,
            "source_resolution": result.source_resolution,
            "output_resolution": result.output_resolution,
            "processing_algorithms": result.processing_algorithms,
            "processing_parameters": result.processing_parameters,
            "source_refs": local_run.source_refs,
            "source_hashes": local_run.source_hashes,
            "warnings": result.warnings,
            "adds_source_resolution": False,
        }
        metadata_bytes = _json_bytes(metadata)
        metadata_artifact = SpatialArtifact(
            artifact_id=f"{run_id}.metadata",
            artifact_type="workflow_metadata",
            crs=result.crs,
            output_resolution={"status": "metadata_only"},
            processing_algorithm=processing_algorithm,
            processing_parameters=result.processing_parameters,
            artifact_hash=_sha256_bytes(metadata_bytes),
            artifact_ref=metadata_ref,
            media_type="application/json",
            **common,
        )
        for ref, data in (
            (route_ref, route_bytes),
            (slope_ref, slope_bytes),
            (render_ref, render_bytes),
            (metadata_ref, metadata_bytes),
        ):
            _write_bytes(_safe_project_path(project_root, ref), data)
        completed = local_run.model_copy(
            update={
                "state": SpatialWorkflowState.COMPLETED,
                "started_at": worker_run.started_at,
                "updated_at": worker_run.updated_at,
                "completed_at": worker_run.completed_at or self._now_iso(),
                "processing_status": "completed",
                "render_status": "completed",
                "machine_review_status": "not_started",
                "visual_review_status": "pending",
                "human_review_status": "pending",
                "steps": _public_worker_steps(worker_run.steps),
                "artifacts": [route_artifact, slope_artifact, metadata_artifact],
                "render_artifacts": [render_artifact],
                "artifact_refs": [route_ref, slope_ref, metadata_ref, render_ref],
                "maplibre_geojson": feature_collection,
                "warnings": list(dict.fromkeys([*local_run.warnings, *result.warnings])),
                "error": None,
                "audit_trail": _merge_audit_trail(
                    local_run.audit_trail,
                    worker_run.audit_trail,
                    [{
                        "event": "worker_artifacts_normalized",
                        "at": self._now_iso(),
                        "artifact_refs": [route_ref, slope_ref, metadata_ref, render_ref],
                        "review_status": "pending",
                    }],
                ),
            }
        )
        self._record_workspace_io(
            project_id=local_run.project_id,
            artifact_ref=f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}/workflow_run.json",
            artifact_kind="qgis_spatial_workflow_run",
            record_count=len(completed.artifact_refs),
            byte_count=sum(len(value) for value in (route_bytes, slope_bytes, render_bytes, metadata_bytes)),
            summary="QGIS spatial worker evidence normalized and persisted",
        )
        return completed

    def _materialize_terrain_route_hypothesis_result(
        self,
        *,
        project_root: Path,
        local_run: SpatialWorkflowRun,
        worker_run: QgisWorkerRun,
    ) -> SpatialWorkflowRun:
        result = worker_run.result
        if result is None:
            raise QgisSpatialBackendError(
                "QGIS terrain route hypothesis result is unavailable"
            )
        feature_collection = _validated_candidate_geojson(result.maplibre_geojson)
        single_types = (
            "terrain_route_hypothesis",
            "terrain_route_best_path_vector",
            "terrain_route_slope_raster",
            "terrain_route_friction_raster",
            "terrain_route_walk_cost_raster",
            "terrain_route_walk_direction_raster",
            "terrain_route_cost_from_a_raster",
            "terrain_route_cost_from_b_raster",
            "terrain_route_cost_direction_a_raster",
            "terrain_route_cost_direction_b_raster",
            "terrain_route_corridor_raster",
            "terrain_route_quantiles",
            "terrain_route_processing_manifest",
        )
        workers_by_type = {
            artifact_type: [
                item
                for item in result.artifacts
                if item.artifact_type == artifact_type
            ]
            for artifact_type in (
                *single_types,
                "terrain_route_flow_accumulation_raster",
                "terrain_route_drainage_pressure_raster",
                "terrain_route_corridor_band_raster",
                "terrain_route_corridor_overlay",
            )
        }
        invalid = [
            artifact_type
            for artifact_type in single_types
            if len(workers_by_type[artifact_type]) != 1
        ]
        if invalid:
            raise QgisSpatialBackendError(
                "QGIS terrain route result omitted or duplicated artifacts: "
                + ", ".join(invalid)
            )
        artifacts_to_fetch = [
            *[workers_by_type[artifact_type][0] for artifact_type in single_types],
            *workers_by_type["terrain_route_flow_accumulation_raster"],
            *workers_by_type["terrain_route_drainage_pressure_raster"],
            *workers_by_type["terrain_route_corridor_band_raster"],
            *workers_by_type["terrain_route_corridor_overlay"],
        ]
        if len(artifacts_to_fetch) > 32:
            raise QgisSpatialBackendError(
                "QGIS terrain route result contains too many artifacts"
            )
        artifact_bytes: dict[str, bytes] = {}
        artifacts_by_relative_ref: dict[str, Any] = {}
        for worker_artifact in artifacts_to_fetch:
            max_bytes = (
                256 * 1024 * 1024
                if worker_artifact.media_type == "image/tiff"
                else 32 * 1024 * 1024
                if worker_artifact.media_type == "image/png"
                else 16 * 1024 * 1024
            )
            raw = self._worker_artifact_bytes(
                worker_run.worker_run_id,
                worker_artifact.artifact_id,
                max_bytes,
            )
            if len(raw) != worker_artifact.byte_count:
                raise QgisSpatialBackendError(
                    f"QGIS {worker_artifact.artifact_type} artifact byte count mismatch"
                )
            if _sha256_bytes(raw) != worker_artifact.sha256:
                raise QgisSpatialBackendError(
                    f"QGIS {worker_artifact.artifact_type} artifact hash mismatch"
                )
            relative_ref = _bounded_worker_relative_ref(worker_artifact.relative_ref)
            if relative_ref in artifacts_by_relative_ref:
                raise QgisSpatialBackendError(
                    "QGIS terrain route artifacts reused a relative reference"
                )
            artifact_bytes[worker_artifact.artifact_id] = raw
            artifacts_by_relative_ref[relative_ref] = worker_artifact

        hypothesis_worker = workers_by_type["terrain_route_hypothesis"][0]
        try:
            worker_hypothesis_payload = json.loads(
                artifact_bytes[hypothesis_worker.artifact_id].decode("utf-8")
            )
            worker_hypothesis = TerrainRouteHypothesisRun.model_validate(
                worker_hypothesis_payload
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise QgisSpatialBackendError(
                "QGIS terrain route hypothesis artifact is malformed"
            ) from exc
        if (
            worker_hypothesis.status is not TerrainRouteRunStatus.COMPLETED
            or not 1 <= len(worker_hypothesis.hypotheses) <= 6
        ):
            raise QgisSpatialBackendError(
                "QGIS terrain route hypotheses are not a bounded completed candidate set"
            )
        if len(worker_hypothesis.hypotheses) > 1 and any(
            len(workers_by_type[artifact_type]) != 1
            for artifact_type in (
                "terrain_route_flow_accumulation_raster",
                "terrain_route_drainage_pressure_raster",
            )
        ):
            raise QgisSpatialBackendError(
                "QGIS multi-route result omitted drainage model artifacts"
            )
        corridor_hypotheses = [
            item for item in worker_hypothesis.hypotheses if item.corridor is not None
        ]
        if len(corridor_hypotheses) != 1:
            raise QgisSpatialBackendError(
                "QGIS terrain route candidate set must bind exactly one corridor profile"
            )
        hypothesis = corridor_hypotheses[0]
        band_count = len(hypothesis.corridor.bands)
        if (
            band_count < 1
            or len(workers_by_type["terrain_route_corridor_band_raster"])
            != band_count
            or len(workers_by_type["terrain_route_corridor_overlay"]) != band_count
        ):
            raise QgisSpatialBackendError(
                "QGIS terrain route corridor artifact count does not match its schema"
            )
        _validate_terrain_route_best_path_bytes(
            artifact_bytes[
                workers_by_type["terrain_route_best_path_vector"][0].artifact_id
            ],
            hypotheses=worker_hypothesis.hypotheses,
        )
        manifest_worker = workers_by_type["terrain_route_processing_manifest"][0]
        processing_manifest = _validated_terrain_route_processing_manifest_bytes(
            artifact_bytes[manifest_worker.artifact_id],
            hypothesis=hypothesis,
        )

        cache_key = hypothesis.provenance.cache_key
        if any(
            item.provenance.cache_key != cache_key
            for item in worker_hypothesis.hypotheses
        ):
            raise QgisSpatialBackendError(
                "QGIS terrain route alternatives do not share one run cache identity"
            )
        root_ref = f"{QGIS_WORKFLOW_ROOT_REF}/terrain-route-cache/{cache_key}"
        refs_by_worker_ref = {
            relative_ref: f"{root_ref}/{relative_ref}"
            for relative_ref in artifacts_by_relative_ref
        }
        normalized_payload = _rewrite_terrain_route_workspace_refs(
            worker_hypothesis_payload,
            refs_by_worker_ref=refs_by_worker_ref,
            artifacts_by_relative_ref=artifacts_by_relative_ref,
        )
        normalized_hypothesis = TerrainRouteHypothesisRun.model_validate(
            normalized_payload
        )
        hypothesis_ref = f"{root_ref}/terrain_route_hypothesis.json"
        best_path_ref = refs_by_worker_ref[
            workers_by_type["terrain_route_best_path_vector"][0].relative_ref
        ]
        manifest_ref = f"{root_ref}/terrain_route_processing_manifest.json"
        visualization_ref = f"{root_ref}/terrain_route_visualization.json"
        metadata_ref = f"{root_ref}/artifact_metadata.json"
        normalized_hypothesis_bytes = _json_bytes(
            normalized_hypothesis.model_dump(mode="json")
        )
        processing_manifest = {
            **processing_manifest,
            "workspace_artifact_refs": sorted(refs_by_worker_ref.values()),
            "workspace_hypothesis_ref": hypothesis_ref,
            "workspace_visualization_ref": visualization_ref,
        }
        processing_manifest_bytes = _json_bytes(processing_manifest)
        visualization = _terrain_route_visualization_manifest(
            project_id=local_run.project_id,
            workflow_run_id=local_run.workflow_run_id,
            hypothesis_ref=hypothesis_ref,
            hypothesis=normalized_hypothesis,
            feature_collection=feature_collection,
            artifacts_by_relative_ref=artifacts_by_relative_ref,
        )
        visualization_bytes = _compact_json_bytes(visualization)
        metadata = {
            "schema_version": "scout_qgis_spatial_artifact_metadata.v0_1",
            "artifact_kind": "terrain_route_hypothesis_artifact_set",
            "workflow_run_id": local_run.workflow_run_id,
            "backend_run_id": worker_run.worker_run_id,
            "cache_keys": hypothesis.provenance.cache_keys,
            "cache_key": cache_key,
            "artifact_refs": sorted(
                [
                    *refs_by_worker_ref.values(),
                    hypothesis_ref,
                    manifest_ref,
                    visualization_ref,
                ]
            ),
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "safe_or_walkable": "not_determined",
            "qgis_version": result.qgis_version,
            "qgis_mcp_plugin_version": result.qgis_mcp_plugin_version,
            "grass_version": hypothesis.provenance.grass_version,
            "source_refs": local_run.source_refs,
            "source_hashes": local_run.source_hashes,
        }
        metadata_bytes = _json_bytes(metadata)

        writes = {
            refs_by_worker_ref[relative_ref]: artifact_bytes[worker.artifact_id]
            for relative_ref, worker in artifacts_by_relative_ref.items()
            if worker.artifact_type
            not in {
                "terrain_route_hypothesis",
                "terrain_route_processing_manifest",
            }
        }
        writes.update(
            {
                hypothesis_ref: normalized_hypothesis_bytes,
                manifest_ref: processing_manifest_bytes,
                visualization_ref: visualization_bytes,
                metadata_ref: metadata_bytes,
            }
        )
        for ref, raw in writes.items():
            _write_bytes(_safe_project_path(project_root, ref), raw)
        _validate_workspace_terrain_route_hypothesis(
            project_root=project_root,
            hypothesis=normalized_hypothesis,
            expected_cache_key=cache_key,
        )
        _activate_terrain_route_hypothesis(
            project_root=project_root,
            workflow_run_id=local_run.workflow_run_id,
            cache_key=cache_key,
            hypothesis_ref=hypothesis_ref,
            hypothesis_hash=_sha256_bytes(normalized_hypothesis_bytes),
            visualization_ref=visualization_ref,
            visualization_hash=_sha256_bytes(visualization_bytes),
            best_path_ref=best_path_ref,
            processing_manifest_ref=manifest_ref,
        )
        navigation_projection = _refresh_navigation_projection_after_terrain_route(
            project_root=project_root,
            project_id=local_run.project_id,
        )
        navigation_warnings = (
            []
            if navigation_projection["status"] == "ready"
            else [
                "Terrain route evidence was preserved, but the Navigation projection "
                "could not be refreshed and remains unavailable for map display."
            ]
        )

        created_at = worker_run.completed_at or self._now_iso()
        provenance = {
            "schema_version": "scout_qgis_spatial_provenance.v0_1",
            "initiated_by": local_run.requested_by,
            "request_id": local_run.request_id,
            "workflow_id": local_run.workflow_id,
            "workflow_run_id": local_run.workflow_run_id,
            "backend_run_id": worker_run.worker_run_id,
            "project_id": local_run.project_id,
            "selected_capability": "terrain_route_hypothesis",
            "fixture": False,
            "synthetic": False,
            "cache_keys": hypothesis.provenance.cache_keys,
            "created_at": created_at,
            "authority": qgis_candidate_boundary().model_dump(mode="json"),
        }
        common = {
            "workflow_id": local_run.workflow_id,
            "workflow_version": local_run.workflow_version,
            "workflow_run_id": local_run.workflow_run_id,
            "created_at": created_at,
            "source_refs": local_run.source_refs,
            "source_hashes": local_run.source_hashes,
            "qgis_version": result.qgis_version,
            "qgis_mcp_plugin_version": result.qgis_mcp_plugin_version,
            "source_resolution": result.source_resolution,
            "output_resolution": result.output_resolution,
            "processing_parameters": result.processing_parameters,
            "provenance": provenance,
            "status": SpatialArtifactStatus.CANDIDATE,
            "warnings": result.warnings,
            "fixture": False,
            "synthetic": False,
            "adds_source_resolution": False,
        }
        spatial_artifacts: list[SpatialArtifact] = []
        for relative_ref, worker in artifacts_by_relative_ref.items():
            if worker.artifact_type in {
                "terrain_route_hypothesis",
                "terrain_route_processing_manifest",
            }:
                continue
            ref = refs_by_worker_ref[relative_ref]
            spatial_artifacts.append(
                SpatialArtifact(
                    artifact_id=worker.artifact_id,
                    artifact_type=worker.artifact_type,
                    crs=(
                        "EPSG:4326"
                        if worker.artifact_type
                        == "terrain_route_best_path_vector"
                        else result.crs
                    ),
                    processing_algorithm=_terrain_route_processing_algorithm(
                        worker.artifact_type
                    ),
                    artifact_hash=worker.sha256,
                    artifact_ref=ref,
                    media_type=worker.media_type,
                    visualization_only=worker.visualization_only,
                    **common,
                )
            )
        for artifact_id, artifact_type, ref, raw, media_type, visualization_only in (
            (
                f"{local_run.workflow_run_id}.terrain-route-hypothesis",
                "terrain_route_hypothesis",
                hypothesis_ref,
                normalized_hypothesis_bytes,
                "application/json",
                False,
            ),
            (
                f"{local_run.workflow_run_id}.terrain-route-processing-manifest",
                "terrain_route_processing_manifest",
                manifest_ref,
                processing_manifest_bytes,
                "application/json",
                False,
            ),
            (
                f"{local_run.workflow_run_id}.terrain-route-visualization",
                "terrain_route_visualization",
                visualization_ref,
                visualization_bytes,
                "application/json",
                True,
            ),
            (
                f"{local_run.workflow_run_id}.metadata",
                "workflow_metadata",
                metadata_ref,
                metadata_bytes,
                "application/json",
                False,
            ),
        ):
            spatial_artifacts.append(
                SpatialArtifact(
                    artifact_id=artifact_id,
                    artifact_type=artifact_type,
                    crs="EPSG:4326" if visualization_only else result.crs,
                    processing_algorithm="scout.artifact.normalize",
                    artifact_hash=_sha256_bytes(raw),
                    artifact_ref=ref,
                    media_type=media_type,
                    visualization_only=visualization_only,
                    **common,
                )
            )
        artifact_refs = [
            item.artifact_ref
            for item in spatial_artifacts
            if item.artifact_ref is not None
        ]
        completed = local_run.model_copy(
            update={
                "state": SpatialWorkflowState.COMPLETED,
                "started_at": worker_run.started_at,
                "updated_at": worker_run.updated_at,
                "completed_at": created_at,
                "processing_status": "completed",
                "render_status": "completed",
                "machine_review_status": "not_started",
                "visual_review_status": "pending",
                "human_review_status": "pending",
                "steps": _public_worker_steps(worker_run.steps),
                "artifacts": spatial_artifacts,
                "render_artifacts": [],
                "artifact_refs": artifact_refs,
                "maplibre_geojson": feature_collection,
                "warnings": list(
                    dict.fromkeys(
                        [
                            *local_run.warnings,
                            *result.warnings,
                            *navigation_warnings,
                        ]
                    )
                ),
                "error": None,
                "audit_trail": _merge_audit_trail(
                    local_run.audit_trail,
                    worker_run.audit_trail,
                    [
                        {
                            "event": "terrain_route_hypothesis_activated",
                            "at": self._now_iso(),
                            "cache_key": cache_key,
                            "hypothesis_ref": hypothesis_ref,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                            "operational": False,
                        },
                        {
                            "event": "navigation_terrain_projection_refreshed",
                            "at": self._now_iso(),
                            **navigation_projection,
                            "candidate_only": True,
                            "runtime_safety_truth": False,
                        }
                    ],
                ),
            }
        )
        self._record_workspace_io(
            project_id=local_run.project_id,
            artifact_ref=hypothesis_ref,
            artifact_kind="terrain_route_hypothesis_artifact_set",
            record_count=len(artifact_refs),
            byte_count=sum(len(value) for value in writes.values()),
            summary="Candidate-only terrain route hypothesis normalized and activated",
        )
        return completed

    def _cached_terrain_route_run(
        self,
        *,
        project_root: Path,
        project: dict[str, Any],
        cache_keys: TerrainRouteCacheKeys,
    ) -> SpatialWorkflowRun | None:
        if project.get("terrain_route_hypothesis_cache_key") != cache_keys.route_hypothesis:
            return None
        hypothesis_ref = project.get("terrain_route_hypothesis_ref")
        workflow_run_id = project.get("terrain_route_hypothesis_workflow_run_id")
        if not isinstance(hypothesis_ref, str) or not isinstance(workflow_run_id, str):
            return None
        try:
            payload = TerrainRouteHypothesisRun.model_validate(
                _read_json(_safe_project_path(project_root, hypothesis_ref))
            )
            _validate_workspace_terrain_route_hypothesis(
                project_root=project_root,
                hypothesis=payload,
                expected_cache_key=cache_keys.route_hypothesis,
            )
            run = self._load_run(
                project_root=project_root,
                workflow_run_id=workflow_run_id,
            )
        except (
            OSError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
            QgisSpatialBackendError,
            QgisSpatialNotFound,
        ):
            return None
        if (
            run.workflow_id != TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID
            or run.state is not SpatialWorkflowState.COMPLETED
        ):
            return None
        _refresh_navigation_projection_after_terrain_route(
            project_root=project_root,
            project_id=run.project_id,
        )
        return run

    def _materialize_terrain_feature_stack_result(
        self,
        *,
        project_root: Path,
        local_run: SpatialWorkflowRun,
        worker_run: QgisWorkerRun,
    ) -> SpatialWorkflowRun:
        result = worker_run.result
        if result is None:
            raise QgisSpatialBackendError("QGIS terrain feature result is unavailable")
        worker_feature_collection = _validated_candidate_geojson(
            result.maplibre_geojson
        )
        feature_collection, route_geometry = _partition_qgis_analysis_input_route(
            worker_feature_collection
        )
        required_types = (
            "dem_route_bbox_raster",
            "slope_raster",
            "aspect_raster",
            "hillshade_raster",
            "elevation_tint_overlay",
            "hillshade_overlay",
            "slope_shading_overlay",
            "contour_lines_vector",
            "contours_overlay",
            "terrain_surface_manifest",
            "geomorphon_raster",
            "geomorphon_fine_raster",
            "geomorphon_coarse_raster",
            "geomorphon_consensus_ridge_raster",
            "geomorphon_consensus_valley_raster",
            "flow_accumulation_raster",
            "stream_network_raster",
            "ridge_lines_vector",
            "valley_lines_vector",
            "stream_network_vector",
            "terrain_feature_route_samples",
            "terrain_feature_manifest",
            "qgis_visual_context",
            "qgis_render_preview",
        )
        workers_by_type = {
            artifact_type: [
                item
                for item in result.artifacts
                if item.artifact_type == artifact_type
            ]
            for artifact_type in required_types
        }
        invalid = [
            artifact_type
            for artifact_type, matches in workers_by_type.items()
            if len(matches) != 1
        ]
        if invalid:
            raise QgisSpatialBackendError(
                "QGIS terrain feature result omitted or duplicated artifacts: "
                + ", ".join(invalid)
            )
        workers = {
            artifact_type: matches[0]
            for artifact_type, matches in workers_by_type.items()
        }
        artifact_bytes: dict[str, bytes] = {}
        for artifact_type, worker_artifact in workers.items():
            if artifact_type.endswith("_raster"):
                max_bytes = 256 * 1024 * 1024
            elif artifact_type.endswith("_overlay"):
                max_bytes = 32 * 1024 * 1024
            elif artifact_type == "contour_lines_vector":
                max_bytes = 64 * 1024 * 1024
            else:
                max_bytes = 16 * 1024 * 1024
            raw = self._worker_artifact_bytes(
                worker_run.worker_run_id,
                worker_artifact.artifact_id,
                max_bytes,
            )
            if len(raw) != worker_artifact.byte_count:
                raise QgisSpatialBackendError(
                    f"QGIS {artifact_type} artifact byte count mismatch"
                )
            if _sha256_bytes(raw) != worker_artifact.sha256:
                raise QgisSpatialBackendError(
                    f"QGIS {artifact_type} artifact hash mismatch"
                )
            artifact_bytes[artifact_type] = raw
        _validate_terrain_feature_route_samples_bytes(
            artifact_bytes["terrain_feature_route_samples"]
        )
        _validate_candidate_terrain_vector_bytes(
            artifact_bytes["ridge_lines_vector"],
            expected_kind="qgis_candidate_ridge_line",
        )
        _validate_candidate_terrain_vector_bytes(
            artifact_bytes["valley_lines_vector"],
            expected_kind="qgis_candidate_valley_line",
        )
        _validate_candidate_terrain_vector_bytes(
            artifact_bytes["stream_network_vector"],
            expected_kind="qgis_candidate_stream_network",
        )
        _validate_candidate_terrain_vector_bytes(
            artifact_bytes["contour_lines_vector"],
            expected_kind="qgis_candidate_contour_line",
            max_bytes=64 * 1024 * 1024,
            max_coordinate_count=750_000,
        )
        terrain_surface = _validated_terrain_surface_manifest_bytes(
            artifact_bytes["terrain_surface_manifest"]
        )

        run_id = local_run.workflow_run_id
        root_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}"
        route_ref = f"{root_ref}/terrain_feature_stack.geojson"
        terrain_visualization_ref = f"{root_ref}/terrain_visualization.geojson"
        metadata_ref = f"{root_ref}/artifact_metadata.json"
        refs_by_type = {
            "dem_route_bbox_raster": f"{root_ref}/dem_route_bbox.tif",
            "slope_raster": f"{root_ref}/grass_slope.tif",
            "aspect_raster": f"{root_ref}/grass_aspect.tif",
            "hillshade_raster": f"{root_ref}/grass_hillshade.tif",
            "elevation_tint_overlay": f"{root_ref}/terrain_elevation_tint.png",
            "hillshade_overlay": f"{root_ref}/terrain_hillshade.png",
            "slope_shading_overlay": f"{root_ref}/terrain_slope_shading.png",
            "contour_lines_vector": f"{root_ref}/grass_contours.geojson",
            "contours_overlay": f"{root_ref}/terrain_contours.png",
            "terrain_surface_manifest": f"{root_ref}/terrain_surface_manifest.json",
            "geomorphon_raster": f"{root_ref}/grass_geomorphon_landforms.tif",
            "geomorphon_fine_raster": f"{root_ref}/grass_geomorphon_fine.tif",
            "geomorphon_coarse_raster": f"{root_ref}/grass_geomorphon_coarse.tif",
            "geomorphon_consensus_ridge_raster": f"{root_ref}/grass_geomorphon_ridge_consensus.tif",
            "geomorphon_consensus_valley_raster": f"{root_ref}/grass_geomorphon_valley_consensus.tif",
            "flow_accumulation_raster": f"{root_ref}/grass_flow_accumulation.tif",
            "stream_network_raster": f"{root_ref}/grass_stream_network.tif",
            "ridge_lines_vector": f"{root_ref}/ridge_lines.geojson",
            "valley_lines_vector": f"{root_ref}/valley_lines.geojson",
            "stream_network_vector": f"{root_ref}/stream_network.geojson",
            "terrain_feature_route_samples": f"{root_ref}/terrain_feature_route_samples.geojson",
            "terrain_feature_manifest": f"{root_ref}/terrain_feature_manifest.json",
            "qgis_visual_context": f"{root_ref}/qgis_visual_context.json",
            "qgis_render_preview": f"{root_ref}/qgis_render_preview.png",
        }
        algorithms_by_type = {
            "dem_route_bbox_raster": "gdal:cliprasterbyextent",
            "slope_raster": "grass:r.slope.aspect",
            "aspect_raster": "grass:r.slope.aspect",
            "hillshade_raster": "grass:r.relief",
            "elevation_tint_overlay": "gdal:colorrelief",
            "hillshade_overlay": "gdal:colorrelief",
            "slope_shading_overlay": "gdal:colorrelief",
            "contour_lines_vector": "grass:r.contour",
            "contours_overlay": "gdal:rasterize+gdal:colorrelief",
            "terrain_surface_manifest": "scout.artifact.normalize",
            "geomorphon_raster": "grass:r.geomorphon",
            "geomorphon_fine_raster": "grass:r.geomorphon",
            "geomorphon_coarse_raster": "grass:r.geomorphon",
            "geomorphon_consensus_ridge_raster": "grass:r.mapcalc.simple",
            "geomorphon_consensus_valley_raster": "grass:r.mapcalc.simple",
            "flow_accumulation_raster": "grass:r.watershed",
            "stream_network_raster": "grass:r.watershed+r.mapcalc.simple",
            "ridge_lines_vector": "grass:r.mapcalc.simple+r.thin+r.to.vect+native:extractbyexpression+native:dissolve",
            "valley_lines_vector": "grass:r.mapcalc.simple+r.thin+r.to.vect+native:extractbyexpression+native:dissolve",
            "stream_network_vector": "grass:r.watershed+r.mapcalc.simple+r.thin+r.to.vect+native:extractbyexpression+native:dissolve",
            "terrain_feature_route_samples": "qgis_identify.raster_values",
            "terrain_feature_manifest": "scout.artifact.normalize",
            "qgis_visual_context": "qgis.visual_context",
        }
        route_bytes = _json_bytes(route_geometry)
        created_at = worker_run.completed_at or self._now_iso()
        provenance = {
            "schema_version": "scout_qgis_spatial_provenance.v0_1",
            "initiated_by": local_run.requested_by,
            "request_id": local_run.request_id,
            "workflow_id": local_run.workflow_id,
            "workflow_run_id": run_id,
            "backend_run_id": worker_run.worker_run_id,
            "project_id": local_run.project_id,
            "selected_capability": "terrain_feature_stack",
            "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
            "blocked_capabilities": list(QGIS_BLOCKED_CAPABILITIES),
            "fixture": False,
            "synthetic": False,
            "created_at": created_at,
            "authority": qgis_candidate_boundary().model_dump(mode="json"),
        }
        common = {
            "workflow_id": local_run.workflow_id,
            "workflow_version": local_run.workflow_version,
            "workflow_run_id": run_id,
            "created_at": created_at,
            "source_refs": local_run.source_refs,
            "source_hashes": local_run.source_hashes,
            "qgis_version": result.qgis_version,
            "qgis_mcp_plugin_version": result.qgis_mcp_plugin_version,
            "source_resolution": result.source_resolution,
            "provenance": provenance,
            "status": SpatialArtifactStatus.CANDIDATE,
            "warnings": result.warnings,
            "fixture": False,
            "synthetic": False,
            "adds_source_resolution": False,
        }
        route_artifact = SpatialArtifact(
            artifact_id=f"{run_id}.route_geometry",
            artifact_type="route_geometry",
            crs="EPSG:4326",
            output_resolution={"geometry": "MapLibre candidate GeoJSON"},
            processing_algorithm="qgis_project_action.add_vector",
            processing_parameters={"source_crs": "EPSG:4326"},
            artifact_hash=_sha256_bytes(route_bytes),
            artifact_ref=route_ref,
            media_type="application/geo+json",
            **common,
        )
        evidence_artifacts = [
            SpatialArtifact(
                artifact_id=workers[artifact_type].artifact_id,
                artifact_type=artifact_type,
                crs=result.crs,
                output_resolution=result.output_resolution,
                processing_algorithm=algorithms_by_type[artifact_type],
                processing_parameters=result.processing_parameters,
                artifact_hash=workers[artifact_type].sha256,
                artifact_ref=refs_by_type[artifact_type],
                media_type=workers[artifact_type].media_type,
                visualization_only=workers[artifact_type].visualization_only,
                **common,
            )
            for artifact_type in required_types
            if artifact_type != "qgis_render_preview"
        ]
        terrain_visualization = _qgis_grass_terrain_visualization(
            project_id=local_run.project_id,
            workflow_id=local_run.workflow_id,
            workflow_version=local_run.workflow_version,
            workflow_run_id=run_id,
            created_at=created_at,
            terrain_surface=terrain_surface,
            feature_collection=feature_collection,
            refs_by_type=refs_by_type,
            workers=workers,
            source_refs=local_run.source_refs,
            source_hashes=local_run.source_hashes,
            source_resolution=result.source_resolution,
        )
        terrain_visualization_bytes = _compact_json_bytes(terrain_visualization)
        terrain_visualization_artifact = SpatialArtifact(
            artifact_id=f"{run_id}.maplibre_terrain_visualization",
            artifact_type="maplibre_terrain_visualization",
            crs="EPSG:4326",
            output_resolution=terrain_surface["analysis_extent"],
            processing_algorithm="qgis_processing_grass",
            processing_parameters={
                "actual_processors": terrain_surface["actual_processors"],
                "coverage_scope": terrain_surface["coverage_scope"],
                "fallback_used": False,
                "python_dtm_processing_used": False,
            },
            artifact_hash=_sha256_bytes(terrain_visualization_bytes),
            artifact_ref=terrain_visualization_ref,
            media_type="application/geo+json",
            visualization_only=True,
            **common,
        )
        evidence_artifacts.append(terrain_visualization_artifact)
        render_worker = workers["qgis_render_preview"]
        render_artifact = SpatialRenderArtifact(
            artifact_id=render_worker.artifact_id,
            artifact_type="qgis_render_preview",
            crs=result.crs,
            output_resolution=result.output_resolution,
            processing_algorithm="qgis_visual_review.capture",
            processing_parameters={"visual_review_status": "pending"},
            artifact_hash=render_worker.sha256,
            artifact_ref=refs_by_type["qgis_render_preview"],
            media_type=render_worker.media_type,
            width_px=render_worker.width_px,
            height_px=render_worker.height_px,
            visual_review_status="pending",
            **common,
        )
        metadata = {
            "schema_version": "scout_qgis_spatial_artifact_metadata.v0_1",
            "workflow_run_id": run_id,
            "backend_run_id": worker_run.worker_run_id,
            "artifact_ids": [
                route_artifact.artifact_id,
                *[item.artifact_id for item in evidence_artifacts],
                render_artifact.artifact_id,
            ],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": False,
            "synthetic": False,
            "qgis_version": result.qgis_version,
            "qgis_mcp_plugin_version": result.qgis_mcp_plugin_version,
            "crs": result.crs,
            "source_resolution": result.source_resolution,
            "output_resolution": result.output_resolution,
            "processing_algorithms": result.processing_algorithms,
            "processing_parameters": result.processing_parameters,
            "source_refs": local_run.source_refs,
            "source_hashes": local_run.source_hashes,
            "warnings": result.warnings,
            "adds_source_resolution": False,
        }
        metadata_bytes = _json_bytes(metadata)
        metadata_artifact = SpatialArtifact(
            artifact_id=f"{run_id}.metadata",
            artifact_type="workflow_metadata",
            crs=result.crs,
            output_resolution={"status": "metadata_only"},
            processing_algorithm="scout.artifact.normalize",
            processing_parameters=result.processing_parameters,
            artifact_hash=_sha256_bytes(metadata_bytes),
            artifact_ref=metadata_ref,
            media_type="application/json",
            **common,
        )
        writes = {
            route_ref: route_bytes,
            terrain_visualization_ref: terrain_visualization_bytes,
            metadata_ref: metadata_bytes,
            **{
                refs_by_type[artifact_type]: raw
                for artifact_type, raw in artifact_bytes.items()
            },
        }
        for ref, data in writes.items():
            _write_bytes(_safe_project_path(project_root, ref), data)
        _activate_qgis_grass_terrain_visualization(
            project_root=project_root,
            workflow_run_id=run_id,
            terrain_visualization_ref=terrain_visualization_ref,
            refs_by_type=refs_by_type,
        )
        artifacts = [route_artifact, *evidence_artifacts, metadata_artifact]
        artifact_refs = [
            route_ref,
            *[item.artifact_ref for item in evidence_artifacts if item.artifact_ref],
            metadata_ref,
            refs_by_type["qgis_render_preview"],
        ]
        completed = local_run.model_copy(
            update={
                "state": SpatialWorkflowState.COMPLETED,
                "started_at": worker_run.started_at,
                "updated_at": worker_run.updated_at,
                "completed_at": created_at,
                "processing_status": "completed",
                "render_status": "completed",
                "machine_review_status": "not_started",
                "visual_review_status": "pending",
                "human_review_status": "pending",
                "steps": _public_worker_steps(worker_run.steps),
                "artifacts": artifacts,
                "render_artifacts": [render_artifact],
                "artifact_refs": artifact_refs,
                "maplibre_geojson": feature_collection,
                "warnings": list(
                    dict.fromkeys([*local_run.warnings, *result.warnings])
                ),
                "error": None,
                "audit_trail": _merge_audit_trail(
                    local_run.audit_trail,
                    worker_run.audit_trail,
                    [
                        {
                            "event": "worker_artifacts_normalized",
                            "at": self._now_iso(),
                            "artifact_refs": artifact_refs,
                            "review_status": "pending",
                        }
                    ],
                ),
            }
        )
        self._record_workspace_io(
            project_id=local_run.project_id,
            artifact_ref=f"{root_ref}/workflow_run.json",
            artifact_kind="qgis_spatial_terrain_feature_workflow_run",
            record_count=len(artifact_refs),
            byte_count=sum(len(value) for value in writes.values()),
            summary="QGIS GRASS terrain feature evidence normalized and persisted",
        )
        return completed

    def _worker_artifact_bytes(
        self,
        worker_run_id: str,
        artifact_id: str,
        max_bytes: int,
    ) -> bytes:
        getter = getattr(self.transport, "get_bytes", None)
        if not callable(getter) or not self.config.worker_url:
            raise QgisSpatialBackendError("QGIS worker transport cannot retrieve artifacts")
        return getter(
            urljoin(
                self.config.worker_url.rstrip("/") + "/",
                f"workflows/{worker_run_id}/artifacts/{artifact_id}",
            ),
            timeout_s=self.config.timeout_s,
            max_bytes=max_bytes,
        )

    def _terminal_worker_error(
        self,
        run: SpatialWorkflowRun,
        *,
        code: SpatialAnalysisErrorCode,
        message: str,
        detail: str | None = None,
    ) -> SpatialWorkflowRun:
        now = self._now_iso()
        error = SpatialAnalysisError(
            code=code,
            message=message,
            detail=detail,
            retryable=code
            in {
                SpatialAnalysisErrorCode.QGIS_UNAVAILABLE,
                SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
            },
        )
        return run.model_copy(
            update={
                "state": SpatialWorkflowState.FAILED,
                "updated_at": now,
                "completed_at": now,
                "processing_status": "failed",
                "error": error,
                "audit_trail": [
                    *run.audit_trail,
                    {"event": "worker_normalization_failed", "at": now, "error_code": code.value},
                ],
            }
        )

    def _dem_sources(
        self,
        *,
        project_root: Path,
        dem_ref: str | None,
    ) -> tuple[list[Path], list[str], dict[str, str], dict[str, Any]]:
        if dem_ref:
            try:
                path = _safe_project_path(project_root, dem_ref)
            except QgisSpatialBackendError:
                return [], [], {}, {"status": "UNKNOWN", "adds_source_resolution": False}
            if not path.is_file():
                return [], [], {}, {"status": "UNKNOWN", "adds_source_resolution": False}
            return (
                [path],
                [dem_ref],
                {dem_ref: _sha256_file(path)},
                {"status": "UNKNOWN", "adds_source_resolution": False},
            )
        summary_ref = "normalized/terrain/dtm_coverage_summary.json"
        summary_path = project_root / summary_ref
        if not summary_path.is_file():
            return [], [], {}, {"status": "UNKNOWN", "adds_source_resolution": False}
        try:
            summary = _read_json(summary_path)
        except (OSError, json.JSONDecodeError):
            return [], [], {}, {"status": "UNKNOWN", "adds_source_resolution": False}
        raster_sources = summary.get("raster_sources") if isinstance(summary, dict) else None
        if isinstance(raster_sources, list) and raster_sources:
            declared = raster_sources[0]
            if not isinstance(declared, dict):
                return [], [summary_ref], {summary_ref: _sha256_file(summary_path)}, {
                    "status": "INVALID_DECLARED_RASTER",
                    "adds_source_resolution": False,
                }
            try:
                raster_path = Path(str(declared["path"])).expanduser().resolve(strict=True)
                declared_hash = str(declared["sha256"])
                resolution_m = float(declared["source_resolution_m"])
                crs = str(declared["crs"]).upper()
            except (KeyError, FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
                return [], [summary_ref], {summary_ref: _sha256_file(summary_path)}, {
                    "status": "INVALID_DECLARED_RASTER",
                    "adds_source_resolution": False,
                }
            if (
                not raster_path.is_file()
                or raster_path.suffix.casefold() not in {".tif", ".tiff"}
                or not 0 < resolution_m <= 1000
                or crs not in {"3826", "EPSG:3826"}
                or len(declared_hash) != 64
                or any(char not in "0123456789abcdef" for char in declared_hash)
            ):
                return [], [summary_ref], {summary_ref: _sha256_file(summary_path)}, {
                    "status": "INVALID_DECLARED_RASTER",
                    "adds_source_resolution": False,
                }
            actual_hash = _sha256_file(raster_path)
            if actual_hash != declared_hash:
                return [], [summary_ref], {summary_ref: _sha256_file(summary_path)}, {
                    "status": "DECLARED_RASTER_HASH_MISMATCH",
                    "adds_source_resolution": False,
                }
            role = str(declared.get("role") or "declared_dem_raster")
            source_ref = f"{summary_ref}#raster_sources/0/{role}"
            return (
                [raster_path],
                [summary_ref, source_ref],
                {summary_ref: _sha256_file(summary_path), source_ref: actual_hash},
                {
                    "status": "reported",
                    "source_kind": "declared_full_extent_raster",
                    "raster_source_count": 1,
                    "x_m": resolution_m,
                    "y_m": resolution_m,
                    "crs": "EPSG:3826",
                    "crs_evidence": declared.get("crs_evidence") or "unavailable",
                    "adds_source_resolution": False,
                },
            )
        tiles = summary.get("candidate_tiles") if isinstance(summary, dict) else None
        if not isinstance(tiles, list):
            return [], [], {}, {"status": "UNKNOWN", "adds_source_resolution": False}
        paths: list[Path] = []
        hashes = {summary_ref: _sha256_file(summary_path)}
        resolutions: list[tuple[float, float]] = []
        tile_refs: list[str] = []
        for index, tile in enumerate(tiles[:32]):
            if not isinstance(tile, dict) or tile.get("intersects_route_bbox") is False:
                continue
            value = tile.get("grid_uri")
            if not isinstance(value, str):
                continue
            try:
                path = Path(value).expanduser().resolve(strict=True)
            except (FileNotFoundError, OSError, RuntimeError, ValueError):
                continue
            if not path.is_file():
                continue
            tile_id = str(tile.get("tile_id") or f"tile-{len(paths) + 1}")
            source_ref = f"{summary_ref}#candidate_tiles/{index}/{tile_id}"
            paths.append(path)
            tile_refs.append(source_ref)
            hashes[source_ref] = _sha256_file(path)
            try:
                resolutions.append(
                    (float(tile["resolution_x_m"]), float(tile["resolution_y_m"]))
                )
            except (KeyError, TypeError, ValueError):
                pass
        if not paths:
            return [], [summary_ref], hashes, {"status": "UNKNOWN", "adds_source_resolution": False}
        unique_resolutions = sorted(set(resolutions))
        resolution: dict[str, Any] = {
            "status": "reported" if len(unique_resolutions) == 1 else "mixed_or_unknown",
            "tile_count": len(paths),
            "adds_source_resolution": False,
        }
        if len(unique_resolutions) == 1:
            resolution.update(
                {"x_m": unique_resolutions[0][0], "y_m": unique_resolutions[0][1]}
            )
        return paths, [summary_ref, *tile_refs], hashes, resolution

    def _failed_run(
        self,
        *,
        project_id: str,
        request: SpatialAnalysisRequest,
        code: SpatialAnalysisErrorCode,
        message: str,
        status: QgisBackendStatus | None = None,
        detail: str | None = None,
    ) -> SpatialWorkflowRun:
        now = self._now_iso()
        workflow_run_id = self._new_workflow_run_id()
        request_id = request.request_id or f"qgis-request-{uuid4().hex[:12]}"
        error = SpatialAnalysisError(
            code=code,
            message=message,
            detail=detail,
            retryable=code
            in {
                SpatialAnalysisErrorCode.BACKEND_NOT_CONFIGURED,
                SpatialAnalysisErrorCode.QGIS_UNAVAILABLE,
                SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                SpatialAnalysisErrorCode.WORKFLOW_INTERRUPTED,
            },
        )
        return SpatialWorkflowRun(
            project_id=project_id,
            workflow_id=request.workflow_id,
            workflow_version=(
                TERRAIN_FEATURE_STACK_WORKFLOW_VERSION
                if request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
                else TERRAIN_CONTEXT_PREVIEW_WORKFLOW_VERSION
            ),
            workflow_run_id=workflow_run_id,
            request_id=request_id,
            requested_by=request.requested_by,
            state=SpatialWorkflowState.FAILED,
            created_at=now,
            started_at=now,
            updated_at=now,
            completed_at=now,
            processing_status="failed",
            render_status="not_started",
            machine_review_status="not_started",
            visual_review_status="pending",
            human_review_status="pending",
            steps=[
                SpatialWorkflowStep(
                    step_id="input_validation",
                    label="Input validation",
                    status=(
                        SpatialWorkflowStepStatus.FAILED
                        if code is SpatialAnalysisErrorCode.INVALID_INPUT
                        else SpatialWorkflowStepStatus.COMPLETED
                    ),
                    started_at=now,
                    completed_at=now,
                    selected_capability=SpatialCapabilityCategory.TERRAIN,
                    error=error if code is SpatialAnalysisErrorCode.INVALID_INPUT else None,
                ),
                SpatialWorkflowStep(
                    step_id="backend_handshake",
                    label="QGIS backend handshake",
                    status=SpatialWorkflowStepStatus.FAILED,
                    started_at=now,
                    completed_at=now,
                    selected_capability=SpatialCapabilityCategory.PROJECT,
                    error=error,
                ),
            ],
            warnings=status.warnings if status else [],
            error=error,
            audit_trail=[
                {
                    "event": "workflow_failed",
                    "at": now,
                    "requested_by": request.requested_by,
                    "request_id": request_id,
                    "error_code": code.value,
                    "backend_availability": status.availability.value if status else "unknown",
                }
            ],
        )

    def _project_context(
        self,
        *,
        project_id: str,
        project_root: Path | None,
        project: dict[str, Any] | None,
    ) -> QgisProjectContext:
        source_refs: list[str] = []
        if project_root is not None and (project_root / "project.json").is_file():
            source_refs.append("project.json")
        project_label = None
        crs = "UNKNOWN"
        if isinstance(project, dict):
            project_label = str(project.get("route_name") or project.get("name") or project_id)
            candidate_crs = (
                project.get("crs")
                or project.get("route_crs")
                or project.get("source_crs")
            )
            if isinstance(candidate_crs, str) and candidate_crs.strip():
                crs = candidate_crs.strip()
        return QgisProjectContext(
            project_id=project_id,
            project_loaded=project_root is not None and isinstance(project, dict),
            project_label=project_label,
            crs=crs,
            source_refs=source_refs,
        )

    def _unavailable_status(
        self,
        project_context: QgisProjectContext,
        message: str,
        exc: BaseException,
    ) -> QgisBackendStatus:
        return QgisBackendStatus(
            availability=QgisBackendAvailability.UNAVAILABLE,
            enabled=True,
            configured=True,
            endpoint_configured=True,
            reachable=False,
            project_loaded=project_context.project_loaded,
            project_context=project_context,
            errors=[
                SpatialAnalysisError(
                    code=SpatialAnalysisErrorCode.MCP_UNAVAILABLE,
                    message=message,
                    detail=str(exc),
                    retryable=True,
                )
            ],
        )

    def _route_points(
        self,
        project_root: Path,
        project: dict[str, Any],
        *,
        project_id: str,
    ) -> tuple[list[dict[str, float]], list[str], dict[str, str], str | None]:
        source_refs = ["project.json"]
        source_hashes: dict[str, str] = {}
        project_path = project_root / "project.json"
        if project_path.is_file():
            source_hashes["project.json"] = _sha256_file(project_path)
        (
            golden_points,
            golden_refs,
            golden_hashes,
            golden_warning,
            golden_declared,
        ) = _imported_golden_route_points(
            project_root=project_root,
            project=project,
            project_id=project_id,
        )
        source_refs.extend(golden_refs)
        source_hashes.update(golden_hashes)
        if golden_points:
            return golden_points, list(dict.fromkeys(source_refs)), source_hashes, golden_warning
        if golden_declared:
            return [], list(dict.fromkeys(source_refs)), source_hashes, golden_warning
        try:
            resolution = inspect_navigation_terrain_projection(
                project_root,
                project,
                project_id=project_id,
            )
            snapshot = resolution.payload
        except Exception:
            snapshot = {}
        points = _extract_points(snapshot.get("route_samples", {}).get("points"))
        if points:
            raw_projection_ref = project.get("navigation_terrain_projection_ref")
            projection_ref = (
                str(raw_projection_ref).strip()
                if isinstance(raw_projection_ref, str) and raw_projection_ref.strip()
                else NAVIGATION_TERRAIN_PROJECTION_REF
            )
            projection_path = _safe_project_path(project_root, projection_ref)
            source_refs.append(f"{projection_ref}#route_samples")
            if projection_path.is_file():
                source_hashes[projection_ref] = _sha256_file(projection_path)
            return points, source_refs, source_hashes, None
        route_ref = project.get("compiled_mission_graph_reviewed_ref") or project.get(
            "compiled_mission_graph_candidate_ref"
        )
        warning = "Navigation terrain route samples unavailable; fallback checkpoint route geometry used."
        if isinstance(route_ref, str) and route_ref.strip():
            path = _safe_project_path(project_root, route_ref)
            if path.is_file():
                payload = _read_json(path)
                points = _extract_points(payload.get("checkpoints") if isinstance(payload, dict) else None)
                if points:
                    source_refs.append(route_ref)
                    source_hashes[route_ref] = _sha256_file(path)
                    return points, source_refs, source_hashes, warning
        points = _extract_points(project.get("route", {}).get("points") if isinstance(project.get("route"), dict) else None)
        return points, source_refs, source_hashes, warning if points else None

    def _fixture_geojson(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        route_points: list[dict[str, float]],
        corridor_m: float,
    ) -> dict[str, Any]:
        route_feature = _line_geojson(route_points)["features"][0]
        route_feature["properties"] = {
            "id": f"{workflow_run_id}.route",
            "kind": "qgis_analysis_input_route",
            "feature_class": "qgis_analysis_input_route",
            "label": "Golden Route analysis input reference",
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "input_reference": True,
            "generated_by_qgis": False,
            "visualization_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "fixture": True,
            "synthetic": True,
        }
        slope_feature = _line_geojson(route_points)["features"][0]
        slope_feature["properties"] = {
            "id": f"{workflow_run_id}.slope_preview",
            "kind": "qgis_slope_candidate",
            "feature_class": "qgis_slope_candidate",
            "label": "Synthetic slope context preview",
            "project_id": project_id,
            "workflow_run_id": workflow_run_id,
            "corridor_m": corridor_m,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "visualization_only": True,
            "fixture": True,
            "synthetic": True,
            "adds_source_resolution": False,
        }
        return {
            "type": "FeatureCollection",
            "features": [slope_feature, route_feature],
            "properties": {
                "schema_version": "scout_qgis_maplibre_geojson.v0_1",
                "workflow_run_id": workflow_run_id,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "fixture": True,
                "synthetic": True,
            },
        }

    def _fixture_render_svg(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        route_points: list[dict[str, float]],
        corridor_m: float,
    ) -> str:
        width = 960
        height = 540
        coords = _svg_route_points(route_points, width=width, height=height)
        path = " ".join(
            f"{'M' if index == 0 else 'L'} {x:.1f} {y:.1f}"
            for index, (x, y) in enumerate(coords)
        )
        project_label = html.escape(project_id)
        workflow_label = html.escape(workflow_run_id)
        corridor_label = html.escape(str(round(corridor_m, 1)))
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Synthetic QGIS terrain context preview">
  <rect width="{width}" height="{height}" fill="#111914"/>
  <path d="M0 110 H960 M0 220 H960 M0 330 H960 M0 440 H960 M160 0 V540 M320 0 V540 M480 0 V540 M640 0 V540 M800 0 V540" stroke="#26352d" stroke-width="1"/>
  <path d="{path}" fill="none" stroke="#77d6c6" stroke-width="30" stroke-opacity=".20" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="{path}" fill="none" stroke="#ff4f91" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="{coords[0][0]:.1f}" cy="{coords[0][1]:.1f}" r="8" fill="#f6e27a" stroke="#101915" stroke-width="3"/>
  <circle cx="{coords[-1][0]:.1f}" cy="{coords[-1][1]:.1f}" r="8" fill="#f6e27a" stroke="#101915" stroke-width="3"/>
  <text x="34" y="48" fill="#f8f4df" font-family="Inter, Arial, sans-serif" font-size="24" font-weight="700">QGIS Visual Review Fixture</text>
  <text x="34" y="82" fill="#d7dfd1" font-family="Inter, Arial, sans-serif" font-size="16">synthetic / non-runtime / candidate-only / runtime_safety_truth=false</text>
  <text x="34" y="492" fill="#bfc9ba" font-family="Inter, Arial, sans-serif" font-size="14">project={project_label} · corridor={corridor_label}m</text>
  <text x="34" y="518" fill="#bfc9ba" font-family="Inter, Arial, sans-serif" font-size="14">workflow={workflow_label} · no terrain safety conclusion</text>
</svg>"""

    def _provenance(
        self,
        *,
        project_id: str,
        request: SpatialAnalysisRequest,
        status: QgisBackendStatus,
        workflow_run_id: str,
        selected_capability: str,
        fixture: bool,
    ) -> dict[str, Any]:
        return {
            "schema_version": "scout_qgis_spatial_provenance.v0_1",
            "initiated_by": request.requested_by,
            "request_id": request.request_id,
            "workflow_id": request.workflow_id,
            "workflow_run_id": workflow_run_id,
            "project_id": project_id,
            "selected_capability": selected_capability,
            "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
            "blocked_capabilities": list(QGIS_BLOCKED_CAPABILITIES),
            "backend_availability": status.availability.value,
            "fixture": fixture,
            "synthetic": fixture,
            "created_at": self._now_iso(),
            "authority": qgis_candidate_boundary().model_dump(mode="json"),
        }

    def _record_workspace_io(
        self,
        *,
        project_id: str,
        artifact_ref: str,
        artifact_kind: str,
        record_count: int | None,
        byte_count: int | None,
        summary: str,
    ) -> None:
        if self.runtime_audit is None:
            return
        try:
            self.runtime_audit.record_workspace_io(
                operation="write-qgis-spatial-artifact",
                workspace_id=project_id,
                artifact_kind=artifact_kind,
                artifact_ref=artifact_ref,
                record_count=record_count,
                byte_count=byte_count,
                module="admin-api",
                feature="dashboard-api",
                summary=summary,
            )
        except Exception:
            return

    def _persist_run(self, project_root: Path, run: SpatialWorkflowRun) -> None:
        ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run.workflow_run_id}/workflow_run.json"
        path = _safe_project_path(project_root, ref)
        previous_terminal = False
        if path.is_file():
            try:
                previous = SpatialWorkflowRun.model_validate(_read_json(path))
                previous_terminal = previous.state in _TERMINAL_WORKFLOW_STATES
            except (OSError, ValueError, ValidationError, json.JSONDecodeError):
                previous_terminal = False
        if run.state in _TERMINAL_WORKFLOW_STATES and not previous_terminal:
            self._record_terminal_workflow(run)
        _write_bytes(path, _json_bytes(run.model_dump(mode="json")))

    def _record_terminal_workflow(self, run: SpatialWorkflowRun) -> None:
        if self.runtime_audit is None:
            return
        outcome = (
            "succeeded"
            if run.state is SpatialWorkflowState.COMPLETED
            else "degraded"
            if run.state is SpatialWorkflowState.CANCELLED
            else "failed"
        )
        try:
            self.runtime_audit.record_background_job(
                workspace_id=run.project_id,
                job="qgis-terrain-context-preview-v1",
                outcome=outcome,
                duration_ms=_workflow_duration_ms(run),
                provider_call_count=None,
                record_count=len(run.artifact_refs),
                error_code=run.error.code.value if run.error else None,
                summary=(
                    "QGIS spatial evidence workflow completed; authority remains candidate-only"
                    if outcome == "succeeded"
                    else f"QGIS spatial evidence workflow ended as {run.state.value}"
                ),
            )
        except Exception:
            return

    def _run_root(self, project_root: Path, workflow_run_id: str) -> Path:
        _validate_safe_id(workflow_run_id, "workflow_run_id")
        return _safe_project_path(project_root, f"{QGIS_WORKFLOW_ROOT_REF}/{workflow_run_id}")

    def _new_workflow_run_id(self) -> str:
        stamp = self._now_iso().replace("-", "").replace(":", "").replace(".", "-").replace("Z", "Z")
        return f"qgis-tcp-{stamp}-{uuid4().hex[:10]}"

    def _now_iso(self) -> str:
        value = self.now_factory()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _touch_handshake(self) -> str:
        with self._lock:
            self._last_successful_handshake = self._now_iso()
            return self._last_successful_handshake

    def _endpoint_error(self, value: str) -> str | None:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "QGIS worker URL must be an http(s) URL."
        host = parsed.hostname or ""
        if host in {"localhost", "127.0.0.1", "::1"}:
            return None
        try:
            address = ipaddress.ip_address(host)
            if address.is_loopback:
                return None
        except ValueError:
            pass
        if not self.config.local_endpoint_required:
            if parsed.scheme != "https":
                return "Remote QGIS worker URLs must use HTTPS."
            return None
        return "QGIS worker URL must resolve to localhost/loopback in v0.1."


def _completed_steps(
    now: str,
    *,
    workflow_id: str = TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
) -> list[SpatialWorkflowStep]:
    if workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID:
        completed = (
            ("input_validation", "Input validation", SpatialCapabilityCategory.TERRAIN),
            ("crs_inspection", "CRS inspection", SpatialCapabilityCategory.PROJECT),
            ("route_preparation", "Route preparation", SpatialCapabilityCategory.VECTOR),
            ("dem_loaded", "DEM loaded", SpatialCapabilityCategory.RASTER),
            (
                "capability_discovery",
                "GRASS capability discovery",
                SpatialCapabilityCategory.PROCESSING,
            ),
            (
                "slope_aspect_generated",
                "Slope and aspect generated",
                SpatialCapabilityCategory.TERRAIN,
            ),
            (
                "geomorphon_generated",
                "Multiscale geomorphons generated",
                SpatialCapabilityCategory.TERRAIN,
            ),
            (
                "ridge_valley_vectorized",
                "Ridge and valley candidates vectorized",
                SpatialCapabilityCategory.TERRAIN,
            ),
            (
                "hydrology_generated",
                "Flow accumulation generated",
                SpatialCapabilityCategory.HYDROLOGY,
            ),
            (
                "stream_network_extracted",
                "Stream-network candidate extracted",
                SpatialCapabilityCategory.HYDROLOGY,
            ),
            (
                "crs_normalized",
                "CRS metadata normalized",
                SpatialCapabilityCategory.PROCESSING,
            ),
            (
                "candidate_vectors_exported",
                "Candidate lines exported for MapLibre",
                SpatialCapabilityCategory.VECTOR,
            ),
            (
                "route_feature_sampling",
                "Route terrain features sampled",
                SpatialCapabilityCategory.TERRAIN,
            ),
            ("map_rendered", "Map rendered", SpatialCapabilityCategory.RENDER),
        )
        return [
            *[
                SpatialWorkflowStep(
                    step_id=step_id,
                    label=label,
                    status=SpatialWorkflowStepStatus.COMPLETED,
                    started_at=now,
                    completed_at=now,
                    selected_capability=category,
                    warning=(
                        "Fixture-only step; no live GRASS/QGIS output was produced."
                    ),
                )
                for step_id, label, category in completed
            ],
            SpatialWorkflowStep(
                step_id="evidence_review_pending",
                label="Evidence review pending",
                status=SpatialWorkflowStepStatus.PENDING,
                selected_capability=SpatialCapabilityCategory.CARTOGRAPHY,
            ),
        ]
    return [
        SpatialWorkflowStep(
            step_id="input_validation",
            label="Input validation",
            status=SpatialWorkflowStepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            selected_capability=SpatialCapabilityCategory.TERRAIN,
        ),
        SpatialWorkflowStep(
            step_id="crs_inspection",
            label="CRS inspection",
            status=SpatialWorkflowStepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            selected_capability=SpatialCapabilityCategory.PROJECT,
            warning="CRS normalized to EPSG:4326 for fixture visualization.",
        ),
        SpatialWorkflowStep(
            step_id="route_preparation",
            label="Route preparation",
            status=SpatialWorkflowStepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            selected_capability=SpatialCapabilityCategory.VECTOR,
            tool_id="qgis.layers.inspect",
        ),
        SpatialWorkflowStep(
            step_id="dem_loaded",
            label="DEM loaded",
            status=SpatialWorkflowStepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            selected_capability=SpatialCapabilityCategory.RASTER,
            warning="Fixture mode did not load a live DEM; source resolution remains UNKNOWN.",
        ),
        SpatialWorkflowStep(
            step_id="slope_generated",
            label="Slope generated",
            status=SpatialWorkflowStepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            selected_capability=SpatialCapabilityCategory.PROCESSING,
            tool_id="qgis.processing.slope",
            warning="Synthetic slope preview only; not a terrain truth claim.",
        ),
        SpatialWorkflowStep(
            step_id="map_rendered",
            label="Map rendered",
            status=SpatialWorkflowStepStatus.COMPLETED,
            started_at=now,
            completed_at=now,
            selected_capability=SpatialCapabilityCategory.RENDER,
            tool_id="qgis.render.map_preview",
        ),
        SpatialWorkflowStep(
            step_id="evidence_review_pending",
            label="Evidence review pending",
            status=SpatialWorkflowStepStatus.PENDING,
            selected_capability=SpatialCapabilityCategory.CARTOGRAPHY,
        ),
    ]


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}


def _status_capability_available(
    payload: dict[str, Any],
    *,
    explicit_keys: tuple[str, ...],
    evidence_keys: tuple[str, ...],
) -> bool:
    for key in explicit_keys:
        if key in payload:
            return payload.get(key) is True
    for key in evidence_keys:
        value = payload.get(key)
        if value is not None and str(value).strip().casefold() not in {
            "",
            "unknown",
            "unavailable",
            "none",
            "null",
        }:
            return True
    return False


def _env_str(name: str) -> str | None:
    value = os.getenv(name)
    if not value or not value.strip():
        return None
    return value.strip()


def _env_float(name: str, *, default: float, floor: float, ceiling: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return max(floor, min(parsed, ceiling))


def _validate_safe_id(value: str, label: str) -> None:
    if not _SAFE_ID.match(value):
        raise QgisSpatialBackendError(f"unsafe {label}")


def _safe_project_path(project_root: Path, ref: str) -> Path:
    candidate = Path(str(ref))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise QgisSpatialBackendError("unsafe QGIS spatial artifact reference")
    root = project_root.expanduser().resolve()
    path = (root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise QgisSpatialBackendError("unsafe QGIS spatial artifact reference") from exc
    return path


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _compact_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _validated_candidate_geojson(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = _compact_json_bytes(payload)
    if len(encoded) > 8 * 1024 * 1024:
        raise QgisSpatialBackendError("QGIS MapLibre GeoJSON exceeded the Scout limit")
    value = json.loads(encoded.decode("utf-8"))
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise QgisSpatialBackendError("QGIS MapLibre result must be a FeatureCollection")
    if len(value["features"]) > 10_000:
        raise QgisSpatialBackendError("QGIS MapLibre result contains too many features")
    for feature in value["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise QgisSpatialBackendError("QGIS MapLibre result contains an invalid feature")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise QgisSpatialBackendError("QGIS MapLibre feature properties are unavailable")
        if properties.get("candidate_only") is not True:
            raise QgisSpatialBackendError("QGIS MapLibre feature is not candidate-only")
        if properties.get("runtime_safety_truth") is not False:
            raise QgisSpatialBackendError("QGIS MapLibre feature attempted runtime safety authority")
        if properties.get("operational") not in {None, False}:
            raise QgisSpatialBackendError("QGIS MapLibre feature attempted operational authority")
        properties["operational"] = False
    root_properties = value.setdefault("properties", {})
    if not isinstance(root_properties, dict):
        raise QgisSpatialBackendError("QGIS MapLibre collection properties are invalid")
    root_properties.update(
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        }
    )
    return value


def _partition_qgis_analysis_input_route(
    feature_collection: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    input_route_kinds = {"qgis_candidate_route", "qgis_analysis_input_route"}
    route_features: list[dict[str, Any]] = []
    result_features: list[dict[str, Any]] = []
    for feature in feature_collection["features"]:
        properties = feature.get("properties") or {}
        if properties.get("kind") not in input_route_kinds:
            result_features.append(feature)
            continue
        normalized_properties = {
            **properties,
            "kind": "qgis_analysis_input_route",
            "feature_class": "qgis_analysis_input_route",
            "label": "Golden Route analysis input reference",
            "input_reference": True,
            "generated_by_qgis": False,
            "visualization_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        }
        route_features.append({**feature, "properties": normalized_properties})
    if len(route_features) != 1:
        raise QgisSpatialBackendError(
            "QGIS workflow must return exactly one Golden Route input reference"
        )
    root_properties = dict(feature_collection.get("properties") or {})
    display_collection = {
        **feature_collection,
        "features": result_features,
        "properties": {
            **root_properties,
            "contains_analysis_input_route": False,
        },
    }
    route_collection = {
        "type": "FeatureCollection",
        "features": route_features,
        "properties": {
            **root_properties,
            "artifact_role": "analysis_input_reference",
            "generated_by_qgis": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        },
    }
    return display_collection, route_collection


def _validate_terrain_feature_route_samples_bytes(raw: bytes) -> None:
    if len(raw) > 8 * 1024 * 1024:
        raise QgisSpatialBackendError("QGIS route terrain samples exceeded the Scout limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError("QGIS route terrain samples are malformed") from exc
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise QgisSpatialBackendError("QGIS route terrain samples must be GeoJSON")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise QgisSpatialBackendError("QGIS route terrain sample metadata is unavailable")
    if (
        metadata.get("candidate_only") is not True
        or metadata.get("runtime_safety_truth") is not False
        or metadata.get("operational") is not False
        or metadata.get("risk_score_applied") is not False
    ):
        raise QgisSpatialBackendError(
            "QGIS route terrain sample metadata violated candidate authority"
        )
    features = payload.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= 128:
        raise QgisSpatialBackendError("QGIS route terrain sample count is outside the limit")
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if (
            not isinstance(properties, dict)
            or properties.get("candidate_only") is not True
            or properties.get("runtime_safety_truth") is not False
            or properties.get("operational") is not False
            or properties.get("risk_score_applied") is not False
        ):
            raise QgisSpatialBackendError(
                "QGIS route terrain sample attempted risk or runtime authority"
            )


def _bounded_worker_relative_ref(value: str) -> str:
    candidate = Path(str(value))
    if (
        candidate.is_absolute()
        or len(candidate.parts) != 1
        or candidate.name in {"", ".", ".."}
        or len(candidate.name) > 180
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain route artifact reference is not one bounded filename"
        )
    return candidate.name


def _validate_terrain_route_best_path_bytes(
    raw: bytes,
    *,
    hypotheses: list[TerrainRouteHypothesis],
) -> None:
    if len(raw) > 16 * 1024 * 1024:
        raise QgisSpatialBackendError(
            "QGIS terrain route best-path vector exceeded the limit"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError(
            "QGIS terrain route best-path vector is malformed"
        ) from exc
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    features = payload.get("features") if isinstance(payload, dict) else None
    if (
        payload.get("type") != "FeatureCollection"
        or not isinstance(metadata, dict)
        or metadata.get("authority") != "candidate_only"
        or metadata.get("source_type") != "terrain_hypothesis"
        or metadata.get("candidate_only") is not True
        or metadata.get("runtime_safety_truth") is not False
        or metadata.get("operational") is not False
        or metadata.get("safe_or_walkable") != "not_determined"
        or not isinstance(features, list)
        or len(features) != len(hypotheses)
        or not 1 <= len(features) <= 6
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain route best-path vector violated authority invariants"
        )
    features_by_candidate = {
        str(feature.get("properties", {}).get("candidate_id") or ""): feature
        for feature in features
        if isinstance(feature, dict)
    }
    for hypothesis in hypotheses:
        candidate_id = f"R{hypothesis.alternative_index}"
        feature = features_by_candidate.get(candidate_id)
        if feature is None and len(hypotheses) == 1:
            feature = features[0]
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if (
            not isinstance(geometry, dict)
            or geometry.get("type") != "LineString"
            or not isinstance(properties, dict)
            or properties.get("kind") != "terrain_route_hypothesis_best_path"
            or properties.get("authority") != "candidate_only"
            or properties.get("source_type") != "terrain_hypothesis"
            or properties.get("candidate_only") is not True
            or properties.get("runtime_safety_truth") is not False
            or properties.get("operational") is not False
            or properties.get("observed") is not False
            or properties.get("official") is not False
            or properties.get("human_verified") is not False
            or properties.get("path_model") != TERRAIN_ROUTE_PATH_MODEL
            or properties.get("path_semantics") != hypothesis.path_semantics
            or properties.get("path_band_relationship")
            != TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP
        ):
            raise QgisSpatialBackendError(
                "QGIS terrain route best-path feature attempted promotion"
            )
        coordinates = geometry.get("coordinates")
        expected = [list(item) for item in hypothesis.best_path.coordinates]
        if coordinates != expected:
            raise QgisSpatialBackendError(
                "QGIS terrain route best-path geometry disagrees with the typed hypothesis"
            )


def _validated_terrain_route_processing_manifest_bytes(
    raw: bytes,
    *,
    hypothesis: TerrainRouteHypothesis,
) -> dict[str, Any]:
    if len(raw) > 8 * 1024 * 1024:
        raise QgisSpatialBackendError(
            "QGIS terrain route processing manifest exceeded the limit"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError(
            "QGIS terrain route processing manifest is malformed"
        ) from exc
    expected = {
        "schema_version": "scout_terrain_route_processing_manifest.v0_2",
        "workflow_id": TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
        "corridor_semantics": (
            TERRAIN_ROUTE_BAND_SEMANTICS
        ),
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
            "semantics": TERRAIN_ROUTE_BAND_SEMANTICS,
            "recipe": "symmetric_grass:r.cost",
        },
        "path_band_relationship": TERRAIN_ROUTE_PATH_BAND_RELATIONSHIP,
        "best_path_union_applied": False,
        "path_orientation": "A_TO_B",
        "search_complete": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain route processing manifest violated model or authority invariants"
        )
    parent_ref = payload.get("parent_terrain_feature_manifest_ref")
    cache_keys = payload.get("cache_keys")
    if (
        not isinstance(parent_ref, str)
        or not parent_ref.endswith("terrain_feature_manifest.json")
        or not isinstance(cache_keys, dict)
        or cache_keys != hypothesis.provenance.cache_keys
        or cache_keys.get("route_hypothesis") != hypothesis.provenance.cache_key
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain route processing manifest lost parent or cache identity"
        )
    return payload


def _rewrite_terrain_route_workspace_refs(
    payload: dict[str, Any],
    *,
    refs_by_worker_ref: dict[str, str],
    artifacts_by_relative_ref: dict[str, Any],
) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload, ensure_ascii=False))
    hypotheses = normalized.get("hypotheses")
    if not isinstance(hypotheses, list) or not 1 <= len(hypotheses) <= 6:
        raise QgisSpatialBackendError(
            "QGIS terrain route hypothesis count is invalid"
        )
    corridors = [
        item.get("corridor")
        for item in hypotheses
        if isinstance(item, dict) and isinstance(item.get("corridor"), dict)
    ]
    if len(corridors) != 1:
        raise QgisSpatialBackendError(
            "QGIS terrain route candidate set must bind one corridor"
        )
    corridor = corridors[0]
    references = [corridor.get("raster_ref")]
    bands = corridor.get("bands")
    if not isinstance(bands, list) or not bands:
        raise QgisSpatialBackendError(
            "QGIS terrain route corridor bands are unavailable"
        )
    for band in bands:
        if not isinstance(band, dict):
            raise QgisSpatialBackendError(
                "QGIS terrain route corridor band is malformed"
            )
        references.extend([band.get("raster_ref"), band.get("overlay_ref")])
    for reference in references:
        if not isinstance(reference, dict):
            raise QgisSpatialBackendError(
                "QGIS terrain route raster reference is unavailable"
            )
        worker_ref = _bounded_worker_relative_ref(reference.get("artifact_ref", ""))
        worker = artifacts_by_relative_ref.get(worker_ref)
        workspace_ref = refs_by_worker_ref.get(worker_ref)
        if (
            worker is None
            or workspace_ref is None
            or reference.get("sha256") != worker.sha256
            or reference.get("media_type") != worker.media_type
            or reference.get("candidate_only") is not True
            or reference.get("runtime_safety_truth") is not False
            or reference.get("operational") is not False
        ):
            raise QgisSpatialBackendError(
                "QGIS terrain route raster reference failed artifact binding"
            )
        reference["artifact_ref"] = workspace_ref
    return normalized


def _terrain_route_visualization_manifest(
    *,
    project_id: str,
    workflow_run_id: str,
    hypothesis_ref: str,
    hypothesis: TerrainRouteHypothesisRun,
    feature_collection: dict[str, Any],
    artifacts_by_relative_ref: dict[str, Any],
) -> dict[str, Any]:
    corridor_routes = [
        item for item in hypothesis.hypotheses if item.corridor is not None
    ]
    if len(corridor_routes) != 1:
        raise QgisSpatialBackendError(
            "Terrain route visualization requires one candidate corridor profile"
        )
    route = corridor_routes[0]
    overlays: list[dict[str, Any]] = []
    opacity_by_percentile = {5.0: 0.58, 10.0: 0.44, 20.0: 0.30}
    for band in route.corridor.bands:
        if band.overlay_ref is None:
            raise QgisSpatialBackendError(
                "Terrain route visualization corridor overlay is unavailable"
            )
        worker_ref = Path(band.overlay_ref.artifact_ref).name
        worker = artifacts_by_relative_ref.get(worker_ref)
        if worker is None or worker.width_px is None or worker.height_px is None:
            raise QgisSpatialBackendError(
                "Terrain route visualization corridor dimensions are unavailable"
            )
        overlays.append(
            {
                "overlay_id": band.name,
                "mode": band.name,
                "source_path": band.overlay_ref.artifact_ref,
                "media_type": "image/png",
                "sha256": band.overlay_ref.sha256,
                "bbox_wgs84": band.overlay_ref.bbox_wgs84,
                "pixel_width": worker.width_px,
                "pixel_height": worker.height_px,
                "percentile": band.percentile,
                "max_relative_corridor_cost": band.max_relative_corridor_cost,
                "threshold_semantics": band.threshold_semantics,
                "contains_best_path": band.contains_best_path,
                "default_visible": math.isclose(band.percentile, 10.0),
                "opacity": opacity_by_percentile.get(float(band.percentile), 0.34),
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "visualization_only": True,
            }
        )
    return {
        "schema_version": "scout_terrain_route_visualization.v0_2",
        "artifact_kind": "terrain_route_hypothesis_visualization",
        "project_id": project_id,
        "workflow_run_id": workflow_run_id,
        "hypothesis_ref": hypothesis_ref,
        "cache_key": route.provenance.cache_key,
        "status": "candidate_ready",
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
        "display_labels": [
            "CANDIDATE",
            "TERRAIN HYPOTHESIS",
            "NOT A VERIFIED TRAIL",
        ],
        "path_model": {
            "id": route.path_model,
            "semantics": route.path_semantics,
            "display_name": "minimum anisotropic model-cost trace",
        },
        "band_model": {
            "id": route.corridor.band_model,
            "semantics": route.corridor.threshold_semantics,
            "display_name": "symmetric macro-terrain detour-score percentile cells",
        },
        "path_band_relationship": route.corridor.path_relationship,
        "alternative_profiles": [
            {
                "candidate": item.id,
                "label": item.label,
                "alternative_index": item.alternative_index,
                "strategy": item.strategy.value,
                "drainage_penalty_multiplier": (
                    item.drainage_penalty_multiplier
                ),
                "corridor_profile": item.corridor is not None,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
            }
            for item in hypothesis.hypotheses
        ],
        "features": feature_collection.get("features", []),
        "raster_overlays": overlays,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "visualization_only": True,
            "promotion_allowed": False,
        },
    }


def _validate_workspace_terrain_route_hypothesis(
    *,
    project_root: Path,
    hypothesis: TerrainRouteHypothesisRun,
    expected_cache_key: str,
) -> None:
    if (
        hypothesis.status is not TerrainRouteRunStatus.COMPLETED
        or not 1 <= len(hypothesis.hypotheses) <= 6
        or any(
            item.provenance.cache_key != expected_cache_key
            for item in hypothesis.hypotheses
        )
    ):
        raise QgisSpatialBackendError(
            "Workspace terrain route hypothesis cache identity is invalid"
        )
    corridor_routes = [
        item for item in hypothesis.hypotheses if item.corridor is not None
    ]
    if (
        len(corridor_routes) != 1
        or corridor_routes[0].corridor is None
        or corridor_routes[0].corridor.raster_ref is None
    ):
        raise QgisSpatialBackendError(
            "Workspace terrain route corridor is unavailable"
        )
    route = corridor_routes[0]
    references = [route.corridor.raster_ref]
    for band in route.corridor.bands:
        if band.raster_ref is None or band.overlay_ref is None:
            raise QgisSpatialBackendError(
                "Workspace terrain route band artifact is unavailable"
            )
        references.extend([band.raster_ref, band.overlay_ref])
    for reference in references:
        path = _safe_project_path(project_root, reference.artifact_ref)
        if not path.is_file() or _sha256_file(path) != reference.sha256:
            raise QgisSpatialBackendError(
                "Workspace terrain route artifact is missing or hash-invalid"
            )


def _terrain_route_processing_algorithm(artifact_type: str) -> str:
    return {
        "terrain_route_best_path_vector": "grass:r.walk.coords+grass:r.path",
        "terrain_route_slope_raster": "grass:r.slope.aspect",
        "terrain_route_flow_accumulation_raster": "grass:r.watershed",
        "terrain_route_drainage_pressure_raster": "grass:r.mapcalc.simple",
        "terrain_route_friction_raster": "grass:r.mapcalc.simple",
        "terrain_route_walk_cost_raster": "grass:r.walk.coords",
        "terrain_route_walk_direction_raster": "grass:r.walk.coords",
        "terrain_route_cost_from_a_raster": "grass:r.cost",
        "terrain_route_cost_from_b_raster": "grass:r.cost",
        "terrain_route_cost_direction_a_raster": "grass:r.cost",
        "terrain_route_cost_direction_b_raster": "grass:r.cost",
        "terrain_route_corridor_raster": "grass:r.mapcalc.simple",
        "terrain_route_corridor_band_raster": "grass:r.mapcalc.simple",
        "terrain_route_corridor_overlay": "gdal:colorrelief",
        "terrain_route_quantiles": "grass:r.quantile",
    }.get(artifact_type, "qgis_processing_grass")


def _validated_terrain_surface_manifest_bytes(raw: bytes) -> dict[str, Any]:
    if len(raw) > 1024 * 1024:
        raise QgisSpatialBackendError("QGIS terrain surface manifest exceeded the limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError("QGIS terrain surface manifest is malformed") from exc
    if not isinstance(payload, dict):
        raise QgisSpatialBackendError("QGIS terrain surface manifest must be an object")
    required_identity = {
        "schema_version": "scout_qgis_terrain_surface.v0_1",
        "artifact_kind": "scout_qgis_terrain_surface_manifest",
        "status": "completed_candidate_surface",
        "coverage_scope": "full_route_extent_rectangle",
        "actual_processor": "qgis_processing_grass",
        "fallback_used": False,
        "python_dtm_processing_used": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "adds_source_resolution": False,
    }
    if any(payload.get(key) != value for key, value in required_identity.items()):
        raise QgisSpatialBackendError(
            "QGIS terrain surface manifest violated processor or authority invariants"
        )
    expected_processors = {
        "dem_crop": "gdal:cliprasterbyextent",
        "slope_aspect": "grass:r.slope.aspect",
        "hillshade": "grass:r.relief",
        "contours": "grass:r.contour",
        "contour_rasterization": "gdal:rasterize",
        "display_colorization": "gdal:colorrelief",
    }
    processors = payload.get("actual_processors")
    if not isinstance(processors, dict) or any(
        processors.get(key) != value for key, value in expected_processors.items()
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain surface manifest omitted an allowlisted standard processor"
        )
    extent = payload.get("analysis_extent")
    if not isinstance(extent, dict) or extent.get("scope") != "full_route_extent_rectangle":
        raise QgisSpatialBackendError("QGIS terrain surface rectangle is unavailable")
    if str(extent.get("crs", "")).upper() != "EPSG:3826":
        raise QgisSpatialBackendError("QGIS terrain surface CRS must be EPSG:3826")
    resolution = _finite_manifest_number(extent.get("resolution_m"))
    margin = _finite_manifest_number(extent.get("margin_m"))
    width = extent.get("width")
    height = extent.get("height")
    cell_count = extent.get("cell_count")
    if (
        resolution is None
        or not 0 < resolution <= 1000
        or margin is None
        or not 0 <= margin <= 10_000
        or isinstance(width, bool)
        or not isinstance(width, int)
        or not 1 <= width <= 4096
        or isinstance(height, bool)
        or not isinstance(height, int)
        or not 1 <= height <= 4096
        or isinstance(cell_count, bool)
        or not isinstance(cell_count, int)
        or cell_count != width * height
        or cell_count > 4_000_000
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain surface dimensions are invalid or exceed the bounded limit"
        )
    twd97_bbox = _validated_surface_bbox(
        extent.get("bbox_twd97"),
        keys=("min_x", "min_y", "max_x", "max_y"),
        geographic=False,
    )
    _validated_surface_bbox(
        extent.get("bbox_wgs84"),
        keys=("west", "south", "east", "north"),
        geographic=True,
    )
    tolerance = max(1e-6, resolution * 1e-6)
    if not (
        math.isclose(
            twd97_bbox["max_x"] - twd97_bbox["min_x"],
            width * resolution,
            rel_tol=0.0,
            abs_tol=tolerance,
        )
        and math.isclose(
            twd97_bbox["max_y"] - twd97_bbox["min_y"],
            height * resolution,
            rel_tol=0.0,
            abs_tol=tolerance,
        )
    ):
        raise QgisSpatialBackendError(
            "QGIS terrain surface grid is not aligned with its declared extent"
        )
    return payload


def _finite_manifest_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _validated_surface_bbox(
    value: Any,
    *,
    keys: tuple[str, str, str, str],
    geographic: bool,
) -> dict[str, float]:
    if not isinstance(value, dict):
        raise QgisSpatialBackendError("QGIS terrain surface bounds are unavailable")
    normalized = {key: _finite_manifest_number(value.get(key)) for key in keys}
    if any(item is None for item in normalized.values()):
        raise QgisSpatialBackendError("QGIS terrain surface bounds are malformed")
    first_min, second_min, first_max, second_max = (normalized[key] for key in keys)
    if first_min >= first_max or second_min >= second_max:
        raise QgisSpatialBackendError("QGIS terrain surface bounds are inverted")
    if geographic and not (
        -180 <= first_min <= 180
        and -180 <= first_max <= 180
        and -90 <= second_min <= 90
        and -90 <= second_max <= 90
    ):
        raise QgisSpatialBackendError("QGIS terrain surface geographic bounds are invalid")
    return {key: float(normalized[key]) for key in keys}


def _qgis_grass_terrain_visualization(
    *,
    project_id: str,
    workflow_id: str,
    workflow_version: str,
    workflow_run_id: str,
    created_at: str,
    terrain_surface: dict[str, Any],
    feature_collection: dict[str, Any],
    refs_by_type: dict[str, str],
    workers: dict[str, Any],
    source_refs: list[str],
    source_hashes: dict[str, str],
    source_resolution: dict[str, Any],
) -> dict[str, Any]:
    extent = terrain_surface["analysis_extent"]
    bbox_twd97 = _validated_surface_bbox(
        extent["bbox_twd97"],
        keys=("min_x", "min_y", "max_x", "max_y"),
        geographic=False,
    )
    bbox_wgs84 = _validated_surface_bbox(
        extent["bbox_wgs84"],
        keys=("west", "south", "east", "north"),
        geographic=True,
    )
    overlay_definitions = (
        ("elevation_tint", "elevation_tint_overlay", True, 0.62, "gdal:colorrelief"),
        ("hillshade", "hillshade_overlay", True, 0.26, "grass:r.relief+gdal:colorrelief"),
        ("slope_shading", "slope_shading_overlay", False, 0.50, "grass:r.slope.aspect+gdal:colorrelief"),
        ("contours", "contours_overlay", True, 0.72, "grass:r.contour+gdal:rasterize+gdal:colorrelief"),
    )
    alpha_channel = terrain_surface.get("overlay_alpha_channel") is True
    overlays: list[dict[str, Any]] = []
    projected_width_m = bbox_twd97["max_x"] - bbox_twd97["min_x"]
    projected_height_m = bbox_twd97["max_y"] - bbox_twd97["min_y"]
    for mode, artifact_type, default_visible, opacity, processor in overlay_definitions:
        worker = workers[artifact_type]
        if worker.width_px is None or worker.height_px is None:
            raise QgisSpatialBackendError(
                f"QGIS {artifact_type} dimensions are unavailable"
            )
        overlays.append(
            {
                "overlay_id": mode,
                "mode": mode,
                "source_path": refs_by_type[artifact_type],
                "media_type": "image/png",
                "sha256": worker.sha256,
                "bbox_wgs84": bbox_wgs84,
                "bbox_twd97": bbox_twd97,
                "pixel_width": worker.width_px,
                "pixel_height": worker.height_px,
                "cell_resolution_m": float(extent["resolution_m"]),
                "visual_pixel_resolution_m": max(
                    projected_width_m / worker.width_px,
                    projected_height_m / worker.height_px,
                ),
                "coverage_scope": "full_route_extent_rectangle",
                "actual_processor": processor,
                "default_visible": default_visible,
                "opacity": opacity,
                "alpha_channel": alpha_channel,
                "compositing": "source-over" if alpha_channel else None,
                "image_rendering": "auto",
                "candidate_only": True,
                "runtime_safety_truth": False,
                "operational": False,
                "adds_source_resolution": False,
                "raw_dem_embedded_in_json": False,
            }
        )
    features = [
        item
        for item in feature_collection.get("features", [])
        if isinstance(item, dict)
    ]
    return {
        "type": "FeatureCollection",
        "artifact_kind": "pretrip_terrain_visualization",
        "schema_version": "scout_qgis_terrain_visualization.v0_1",
        "project_id": project_id,
        "source_id": f"{workflow_run_id}.maplibre_terrain_visualization",
        "evidence_type": "qgis_grass_route_extent_terrain_visualization",
        "status": "ready_from_qgis_grass_route_extent_rectangle",
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "workflow_run_id": workflow_run_id,
        "created_at": created_at,
        "features": features,
        "raster_overlays": overlays,
        "visualization_spec": {
            "modes": [item[0] for item in overlay_definitions],
            "terrain_visualization_layer": True,
            "risk_heat_layer": False,
            "coverage_scope": "full_route_extent_rectangle",
            "preferred_processor": "qgis_processing_grass",
            "actual_processor": "qgis_processing_grass",
            "actual_processors": terrain_surface["actual_processors"],
            "requires_standard_processor": True,
            "standard_processor_completed": True,
            "fallback_used": False,
            "fallback_when_unavailable": None,
            "python_dtm_processing_used": False,
            "route_aligned_proxy": False,
            "bitmap_overlay": True,
            "rgba_overlays": alpha_channel,
            "full_raster_hillshade_generated": True,
            "raw_dem_embedded_in_json": False,
            "rendered_appearance_is_new_spatial_evidence": False,
            "adds_source_resolution": False,
        },
        "counts": {
            "feature_count": len(features),
            "bitmap_overlay_count": len(overlays),
            "cell_count": int(extent["cell_count"]),
            "source_dtm_raster_count": 1,
            "source_dtm_tile_count": 0,
            "mode_count": len(overlays),
            "runtime_safety_truth_count": 0,
        },
        "dtm_grid": {
            "bbox_twd97": bbox_twd97,
            "bbox_wgs84": bbox_wgs84,
            "full_route_extent_bbox_twd97": bbox_twd97,
            "cell_resolution_m": float(extent["resolution_m"]),
            "selected_cell_count": int(extent["cell_count"]),
            "source_raster_count": 1,
            "crs": "EPSG:3826",
            "coverage_scope": "full_route_extent_rectangle",
            "raw_grid_embedded_in_json": False,
            "adds_source_resolution": False,
        },
        "source_refs": list(refs_by_type.values()),
        "source_binding": {
            "requested_source_refs": source_refs,
            "requested_source_hashes": source_hashes,
            "source_resolution": source_resolution,
            "surface_manifest_ref": refs_by_type["terrain_surface_manifest"],
            "route_bbox_dem_ref": refs_by_type["dem_route_bbox_raster"],
        },
        "provenance": {
            "processor": "qgis_processing_grass",
            "actual_processors": terrain_surface["actual_processors"],
            "workflow_id": workflow_id,
            "workflow_run_id": workflow_run_id,
            "fixture": False,
            "synthetic": False,
        },
        "warnings": [
            "GIS processing success proves execution only; terrain interpretation remains candidate evidence."
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
            "visualization_only": True,
            "adds_source_resolution": False,
        },
    }


def _activate_qgis_grass_terrain_visualization(
    *,
    project_root: Path,
    workflow_run_id: str,
    terrain_visualization_ref: str,
    refs_by_type: dict[str, str],
) -> None:
    project_path = project_root / "project.json"
    try:
        project = _read_json(project_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError("Scout project metadata is unavailable") from exc
    if not isinstance(project, dict):
        raise QgisSpatialBackendError("Scout project metadata must be an object")
    previous_ref = project.get("terrain_visualization_ref")
    updated = {
        **project,
        "terrain_visualization_ref": terrain_visualization_ref,
        "terrain_visualization_processor": "qgis_processing_grass",
        "terrain_visualization_workflow_run_id": workflow_run_id,
        "terrain_dem_route_bbox_raster_ref": refs_by_type["dem_route_bbox_raster"],
        "terrain_hillshade_raster_ref": refs_by_type["hillshade_raster"],
        "terrain_hillshade_overlay_ref": refs_by_type["hillshade_overlay"],
        "terrain_elevation_tint_overlay_ref": refs_by_type["elevation_tint_overlay"],
        "terrain_slope_shading_overlay_ref": refs_by_type["slope_shading_overlay"],
        "terrain_contours_overlay_ref": refs_by_type["contours_overlay"],
        "terrain_contour_lines_vector_ref": refs_by_type["contour_lines_vector"],
        "terrain_surface_manifest_ref": refs_by_type["terrain_surface_manifest"],
        "terrain_feature_manifest_ref": refs_by_type["terrain_feature_manifest"],
        "qgis_ridge_lines_vector_ref": refs_by_type["ridge_lines_vector"],
        "qgis_valley_lines_vector_ref": refs_by_type["valley_lines_vector"],
        "qgis_stream_network_vector_ref": refs_by_type["stream_network_vector"],
    }
    if isinstance(previous_ref, str) and previous_ref and previous_ref != terrain_visualization_ref:
        updated["terrain_visualization_previous_ref"] = previous_ref
    _write_bytes(project_path, _json_bytes(updated))


def _terrain_route_parent_manifest_binding(
    *,
    project_root: Path,
    project: dict[str, Any],
) -> tuple[str | None, str | None]:
    value = project.get("terrain_feature_manifest_ref")
    if not isinstance(value, str) or not value.endswith(
        "terrain_feature_manifest.json"
    ):
        return None, None
    try:
        path = _safe_project_path(project_root, value)
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError, QgisSpatialBackendError):
        return None, None
    if (
        not isinstance(payload, dict)
        or payload.get("candidate_only") is not True
        or payload.get("runtime_safety_truth") is not False
        or payload.get("operational") is not False
        or payload.get("fixture") is True
        or payload.get("synthetic") is True
    ):
        return None, None
    return value, _sha256_file(path)


def _terrain_route_parent_source_resolution(
    *,
    project_root: Path,
    parent_ref: str,
    dem_ref: str | None,
) -> dict[str, Any] | None:
    if not dem_ref:
        return None
    parent_path = Path(parent_ref)
    dem_path = Path(dem_ref)
    if (
        parent_path.parent != dem_path.parent
        or dem_path.suffix.casefold() not in {".tif", ".tiff"}
    ):
        return None
    try:
        payload = _read_json(_safe_project_path(project_root, parent_ref))
        source_resolution = payload["source_resolution"]
        artifacts = payload["artifacts"]
        analysis_extent = payload["parameters"]["analysis_extent"]
        x_m = float(source_resolution["x_m"])
        y_m = float(source_resolution["y_m"])
        analysis_resolution_m = float(analysis_extent["resolution_m"])
        crs = str(source_resolution["crs"]).upper()
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        QgisSpatialBackendError,
    ):
        return None
    if (
        not isinstance(payload, dict)
        or not isinstance(source_resolution, dict)
        or not isinstance(artifacts, dict)
        or artifacts.get("dem_route_bbox") != dem_path.name
        or source_resolution.get("status") != "reported"
        or source_resolution.get("adds_source_resolution") is not False
        or crs not in {"3826", "EPSG:3826"}
        or not math.isfinite(x_m)
        or not math.isfinite(y_m)
        or not math.isfinite(analysis_resolution_m)
        or not 0 < x_m <= 1000
        or not math.isclose(x_m, y_m, rel_tol=1e-9, abs_tol=1e-9)
        or not math.isclose(
            x_m,
            analysis_resolution_m,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        return None
    return {
        "status": "reported",
        "source_kind": "active_terrain_feature_dem",
        "x_m": x_m,
        "y_m": y_m,
        "crs": "EPSG:3826",
        "crs_evidence": source_resolution.get("crs_evidence") or "unavailable",
        "adds_source_resolution": False,
        "parent_terrain_feature_manifest_ref": parent_ref,
    }


_TERRAIN_ROUTE_ACTIVE_PROJECT_KEYS = frozenset(
    {
        "terrain_route_hypothesis_ref",
        "terrain_route_hypothesis_sha256",
        "terrain_route_hypothesis_cache_key",
        "terrain_route_hypothesis_visualization_ref",
        "terrain_route_hypothesis_visualization_sha256",
        "terrain_route_hypothesis_best_path_ref",
        "terrain_route_hypothesis_processing_manifest_ref",
        "terrain_route_hypothesis_workflow_run_id",
        "terrain_route_hypothesis_authority",
    }
)


def _deactivate_terrain_route_hypothesis(*, project_root: Path) -> None:
    project_path = project_root / "project.json"
    try:
        project = _read_json(project_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError("Scout project metadata is unavailable") from exc
    if not isinstance(project, dict):
        raise QgisSpatialBackendError("Scout project metadata must be an object")
    previous_ref = project.get("terrain_route_hypothesis_ref")
    updated = {
        key: value
        for key, value in project.items()
        if key not in _TERRAIN_ROUTE_ACTIVE_PROJECT_KEYS
    }
    if isinstance(previous_ref, str) and previous_ref:
        updated["terrain_route_hypothesis_previous_ref"] = previous_ref
    updated.update(
        {
            "terrain_route_hypothesis_status": "pending",
            "terrain_route_hypothesis_candidate_only": True,
            "terrain_route_hypothesis_runtime_safety_truth": False,
        }
    )
    _write_bytes(project_path, _json_bytes(updated))


def _refresh_navigation_projection_after_terrain_route(
    *,
    project_root: Path,
    project_id: str,
) -> dict[str, Any]:
    try:
        project = _read_json(project_root / "project.json")
        if not isinstance(project, dict):
            raise QgisSpatialBackendError("Scout project metadata must be an object")
        current = inspect_navigation_terrain_projection(
            project_root,
            project,
            project_id=project_id,
        )
        if current.payload.get("projection_state") == "ready":
            compilation = current.payload.get("projection_compilation") or {}
            return {
                "status": "ready",
                "source_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
                "input_fingerprint": compilation.get("input_fingerprint"),
                "served_from": "persisted_workspace_artifact",
            }
        compiled = compile_navigation_terrain_projection(
            project_root,
            project=project,
            project_id=project_id,
        )
        boundary = compiled.get("boundary")
        if (
            not isinstance(boundary, dict)
            or boundary.get("candidate_only") is not True
            or boundary.get("runtime_safety_truth") is not False
        ):
            raise QgisSpatialBackendError(
                "Navigation terrain projection violated candidate-only authority"
            )
        compilation = compiled.get("projection_compilation") or {}
        return {
            "status": "ready",
            "source_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
            "input_fingerprint": compilation.get("input_fingerprint"),
            "served_from": "compiled_after_terrain_route_materialization",
        }
    except (
        OSError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
        QgisSpatialBackendError,
    ) as exc:
        return {
            "status": "unavailable",
            "source_ref": NAVIGATION_TERRAIN_PROJECTION_REF,
            "error_type": type(exc).__name__,
            "served_from": "typed_failure",
        }


def _activate_terrain_route_hypothesis(
    *,
    project_root: Path,
    workflow_run_id: str,
    cache_key: str,
    hypothesis_ref: str,
    hypothesis_hash: str,
    visualization_ref: str,
    visualization_hash: str,
    best_path_ref: str,
    processing_manifest_ref: str,
) -> None:
    project_path = project_root / "project.json"
    try:
        project = _read_json(project_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError("Scout project metadata is unavailable") from exc
    if not isinstance(project, dict):
        raise QgisSpatialBackendError("Scout project metadata must be an object")
    previous_ref = project.get("terrain_route_hypothesis_ref")
    updated = {
        **project,
        "terrain_route_hypothesis_ref": hypothesis_ref,
        "terrain_route_hypothesis_sha256": hypothesis_hash,
        "terrain_route_hypothesis_cache_key": cache_key,
        "terrain_route_hypothesis_visualization_ref": visualization_ref,
        "terrain_route_hypothesis_visualization_sha256": visualization_hash,
        "terrain_route_hypothesis_best_path_ref": best_path_ref,
        "terrain_route_hypothesis_processing_manifest_ref": processing_manifest_ref,
        "terrain_route_hypothesis_workflow_run_id": workflow_run_id,
        "terrain_route_hypothesis_status": "completed",
        "terrain_route_hypothesis_authority": "candidate_only",
        "terrain_route_hypothesis_candidate_only": True,
        "terrain_route_hypothesis_runtime_safety_truth": False,
    }
    if isinstance(previous_ref, str) and previous_ref != hypothesis_ref:
        updated["terrain_route_hypothesis_previous_ref"] = previous_ref
    _write_bytes(project_path, _json_bytes(updated))


def _validate_candidate_terrain_vector_bytes(
    raw: bytes,
    *,
    expected_kind: str,
    max_bytes: int = 16 * 1024 * 1024,
    max_coordinate_count: int = 500_000,
) -> None:
    if len(raw) > max_bytes:
        raise QgisSpatialBackendError("QGIS candidate terrain vector exceeded the limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QgisSpatialBackendError(
            "QGIS candidate terrain vector is malformed"
        ) from exc
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise QgisSpatialBackendError("QGIS candidate terrain vector must be GeoJSON")
    metadata = payload.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("candidate_only") is not True
        or metadata.get("runtime_safety_truth") is not False
        or metadata.get("operational") is not False
        or metadata.get("risk_score_applied") is not False
        or str(metadata.get("crs", "")).upper() not in {"4326", "EPSG:4326"}
    ):
        raise QgisSpatialBackendError(
            "QGIS candidate terrain vector metadata violated authority or CRS"
        )
    features = payload.get("features")
    if not isinstance(features, list) or len(features) > 20_000:
        raise QgisSpatialBackendError(
            "QGIS candidate terrain vector feature count is outside the limit"
        )
    coordinate_count = 0
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if (
            not isinstance(properties, dict)
            or properties.get("kind") != expected_kind
            or properties.get("candidate_only") is not True
            or properties.get("runtime_safety_truth") is not False
            or properties.get("operational") is not False
            or properties.get("risk_score_applied") is not False
        ):
            raise QgisSpatialBackendError(
                "QGIS candidate terrain vector attempted runtime authority"
            )
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "LineString",
            "MultiLineString",
        }:
            raise QgisSpatialBackendError(
                "QGIS candidate terrain vector contains non-line geometry"
            )
        lines = (
            [geometry.get("coordinates")]
            if geometry.get("type") == "LineString"
            else geometry.get("coordinates")
        )
        if not isinstance(lines, list) or not lines:
            raise QgisSpatialBackendError(
                "QGIS candidate terrain vector contains empty geometry"
            )
        for line in lines:
            if not isinstance(line, list) or len(line) < 2:
                raise QgisSpatialBackendError(
                    "QGIS candidate terrain vector contains an invalid line"
                )
            for coordinate in line:
                if not isinstance(coordinate, list) or len(coordinate) < 2:
                    raise QgisSpatialBackendError(
                        "QGIS candidate terrain vector coordinate is malformed"
                    )
                try:
                    lon, lat = float(coordinate[0]), float(coordinate[1])
                except (TypeError, ValueError) as exc:
                    raise QgisSpatialBackendError(
                        "QGIS candidate terrain vector coordinate is not numeric"
                    ) from exc
                if (
                    not math.isfinite(lon)
                    or not math.isfinite(lat)
                    or not -180 <= lon <= 180
                    or not -90 <= lat <= 90
                ):
                    raise QgisSpatialBackendError(
                        "QGIS candidate terrain vector is outside EPSG:4326"
                    )
                coordinate_count += 1
                if coordinate_count > max_coordinate_count:
                    raise QgisSpatialBackendError(
                        "QGIS candidate terrain vector has too many coordinates"
                    )


def _public_worker_error(
    error: SpatialAnalysisError | None,
) -> SpatialAnalysisError | None:
    if error is None:
        return None
    if (
        error.code is SpatialAnalysisErrorCode.INVALID_INPUT
        and error.message
        == "Terrain route cache keys do not match the submitted inputs."
    ):
        return error.model_copy(
            update={
                "message": (
                    "Terrain route cache contract does not match the active QGIS "
                    "worker. Restart the QGIS worker and resubmit the same A/B inputs."
                ),
                "detail": None,
            }
        )
    return error.model_copy(update={"detail": None})


def _public_worker_steps(
    steps: list[SpatialWorkflowStep],
) -> list[SpatialWorkflowStep]:
    return [
        step.model_copy(update={"error": _public_worker_error(step.error)})
        for step in steps
    ]


def _merge_audit_trail(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
    return merged


def _workflow_duration_ms(run: SpatialWorkflowRun) -> int:
    start_value = run.started_at or run.created_at
    end_value = run.completed_at or run.updated_at
    try:
        started_at = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(end_value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _imported_golden_route_points(
    *,
    project_root: Path,
    project: dict[str, Any],
    project_id: str,
) -> tuple[
    list[dict[str, float]],
    list[str],
    dict[str, str],
    str | None,
    bool,
]:
    source_refs: list[str] = []
    source_hashes: dict[str, str] = {}
    declared = False
    candidate_refs: list[tuple[str, str | None]] = []
    bundle_ref = project.get("route_evidence_bundle_ref")
    if isinstance(bundle_ref, str) and bundle_ref.strip():
        declared = True
        bundle_ref = bundle_ref.strip()
        try:
            bundle_path = _safe_project_path(project_root, bundle_ref)
            bundle = _read_json(bundle_path)
            if not isinstance(bundle, dict):
                raise ValueError("route evidence bundle must be an object")
            if bundle.get("project_id") not in (None, project_id):
                raise ValueError("route evidence bundle project_id mismatch")
            boundary = bundle.get("boundary")
            if isinstance(boundary, dict) and boundary.get("runtime_safety_truth") is True:
                raise ValueError("route evidence bundle violated candidate authority")
            golden = bundle.get("golden_route")
            if not isinstance(golden, dict):
                raise ValueError("route evidence bundle has no Golden Route")
            filtered_ref = golden.get("filtered_geometry_ref")
            if isinstance(filtered_ref, str) and filtered_ref.strip():
                expected_filtered_hash = golden.get("filtered_geometry_sha256")
                if not isinstance(expected_filtered_hash, str) or re.fullmatch(
                    r"[a-f0-9]{64}", expected_filtered_hash
                ) is None:
                    raise ValueError(
                        "filtered Golden Route requires a valid SHA-256"
                    )
                candidate_refs.append(
                    (
                        filtered_ref.strip(),
                        expected_filtered_hash,
                    )
                )
            source_refs.append(bundle_ref)
            source_hashes[bundle_ref] = _sha256_file(bundle_path)
        except (OSError, ValueError, json.JSONDecodeError, QgisSpatialBackendError) as exc:
            return (
                [],
                source_refs,
                source_hashes,
                f"Declared Golden Route evidence is invalid: {type(exc).__name__}",
                True,
            )

    source_manifest_ref = "inbox/source_manifest.json"
    source_manifest_path = _safe_project_path(project_root, source_manifest_ref)
    if not candidate_refs and source_manifest_path.is_file():
        declared = True
        try:
            source_manifest = _read_json(source_manifest_path)
            sources = source_manifest.get("sources") if isinstance(source_manifest, dict) else None
            if not isinstance(sources, list):
                raise ValueError("source inbox manifest has no sources")
            golden_sources = [
                item
                for item in sources
                if isinstance(item, dict)
                and item.get("role") == "golden_route_reference"
            ]
            if len(golden_sources) != 1:
                raise ValueError("source inbox must declare exactly one Golden Route")
            source = golden_sources[0]
            source_ref = source.get("workspace_ref")
            if isinstance(source_ref, str) and source_ref.strip():
                candidate_refs.append(
                    (
                        source_ref.strip(),
                        str(source.get("sha256"))
                        if isinstance(source.get("sha256"), str)
                        else None,
                    )
                )
            source_refs.append(source_manifest_ref)
            source_hashes[source_manifest_ref] = _sha256_file(source_manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return (
                [],
                source_refs,
                source_hashes,
                f"Golden Route source manifest is invalid: {type(exc).__name__}",
                True,
            )

    errors: list[str] = []
    for source_ref, expected_hash in dict.fromkeys(candidate_refs):
        try:
            source_path = _safe_project_path(project_root, source_ref)
            if not source_path.is_file():
                errors.append(f"missing:{source_ref}")
                continue
            actual_hash = _sha256_file(source_path)
            if expected_hash and expected_hash != actual_hash:
                errors.append(f"hash_mismatch:{source_ref}")
                continue
            route = load_gpx_route(source_path)
            points = [
                {"lat": float(point.lat), "lon": float(point.lon)}
                for point in route.points
            ]
            original_count = len(points)
            points = _sample_route_points(points, maximum=20_000)
            source_refs.append(source_ref)
            source_hashes[source_ref] = actual_hash
            warning = None
            if len(points) < original_count:
                warning = (
                    "Golden GPX exceeded the bounded QGIS route coordinate limit; "
                    f"{original_count} points were deterministically sampled to {len(points)}."
                )
            return (
                points,
                list(dict.fromkeys(source_refs)),
                source_hashes,
                warning,
                True,
            )
        except (OSError, ValueError, QgisSpatialBackendError) as exc:
            errors.append(f"invalid:{source_ref}:{type(exc).__name__}")

    if declared:
        detail = ", ".join(errors[:3]) or "no bounded Golden GPX ref"
        return (
            [],
            list(dict.fromkeys(source_refs)),
            source_hashes,
            f"Imported Golden GPX is unavailable: {detail}",
            True,
        )
    return [], [], {}, None, False


def _extract_points(values: Any) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    iterable = values if isinstance(values, list) else []
    for item in iterable:
        if not isinstance(item, dict):
            continue
        lat = item.get("lat", item.get("latitude"))
        lon = item.get("lon", item.get("lng", item.get("longitude")))
        try:
            lat_value = float(lat)
            lon_value = float(lon)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
            continue
        points.append({"lat": lat_value, "lon": lon_value})
    return points


def _sample_route_points(points: list[dict[str, float]], *, maximum: int) -> list[dict[str, float]]:
    if len(points) <= maximum:
        return points
    step = max(1, len(points) // max(1, maximum - 1))
    sampled = points[::step][: maximum - 1]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


def _line_geojson(points: list[dict[str, float]]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[point["lon"], point["lat"]] for point in points],
                },
                "properties": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        ],
    }


def _svg_route_points(
    points: list[dict[str, float]],
    *,
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    lons = [point["lon"] for point in points]
    lats = [point["lat"] for point in points]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    lon_span = max(0.000001, max_lon - min_lon)
    lat_span = max(0.000001, max_lat - min_lat)
    padding = 72
    usable_width = width - padding * 2
    usable_height = height - padding * 2
    return [
        (
            padding + ((point["lon"] - min_lon) / lon_span) * usable_width,
            height - padding - ((point["lat"] - min_lat) / lat_span) * usable_height,
        )
        for point in points
    ]
