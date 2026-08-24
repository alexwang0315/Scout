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
    inspect_navigation_terrain_projection,
)
from qgis_spatial_contracts import (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_VERSION,
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
    TERRAIN_FEATURE_STACK_WORKFLOW_VERSION,
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


QGIS_WORKFLOW_ROOT_REF = "outputs/spatial/qgis"
QGIS_ALLOWED_WORKFLOWS = (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    TERRAIN_FEATURE_STACK_WORKFLOW_ID,
)
QGIS_ALLOWED_TOOL_IDS = (
    "qgis.context",
    "qgis.project.status",
    "qgis.layers.inspect",
    "qgis.capabilities.processing.search",
    "qgis.capabilities.processing.describe",
    "qgis.processing.slope",
    "qgis.processing.grass.slope_aspect",
    "qgis.processing.grass.geomorphon",
    "qgis.processing.grass.geomorphon_consensus",
    "qgis.processing.grass.watershed_stream",
    "qgis.processing.grass.thin",
    "qgis.processing.grass.raster_to_vector",
    "qgis.processing.grass.watershed",
    "qgis.processing.gdal.assign_projection",
    "qgis.processing.gdal.warp_reproject",
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
    timeout_s: float = 5.0
    fixture_mode: bool = False
    local_endpoint_required: bool = True

    @classmethod
    def from_env(cls) -> "QgisSpatialBackendConfig":
        return cls(
            enabled=_env_bool("SCOUT_QGIS_ENABLED", default=False),
            worker_url=_env_str("SCOUT_QGIS_WORKER_URL"),
            worker_token=_env_str("SCOUT_QGIS_WORKER_TOKEN"),
            timeout_s=_env_float("SCOUT_QGIS_TIMEOUT", default=5.0, floor=0.25, ceiling=120.0),
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
                        "qgis.processing.grass.geomorphon",
                        "qgis.processing.grass.geomorphon_consensus",
                        "qgis.processing.grass.watershed_stream",
                        "qgis.processing.grass.thin",
                        "qgis.processing.grass.raster_to_vector",
                        "qgis.processing.grass.watershed",
                        "qgis.processing.gdal.assign_projection",
                        "qgis.processing.gdal.warp_reproject",
                        "qgis.raster.identify",
                        "qgis.vector.export_candidate_geojson",
                        "qgis.render.map_preview",
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
        dem_refs, dem_source_refs, dem_hashes, source_resolution = self._dem_sources(
            project_root=project_root,
            dem_ref=request.dem_ref,
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
        combined_source_refs = list(dict.fromkeys([*source_refs, *dem_source_refs]))
        combined_source_hashes = {**source_hashes, **dem_hashes}
        payload = {
            "schema_version": "scout_qgis_worker_request.v0_1",
            "workflow_id": request.workflow_id,
            "project_id": project_id,
            "request_id": request_id,
            "requested_by": request.requested_by,
            "corridor_m": request.corridor_m,
            "route_geojson": _line_geojson(route_points),
            "dem_refs": [str(path) for path in dem_refs],
            "source_refs": combined_source_refs,
            "source_hashes": combined_source_hashes,
            "source_resolution": source_resolution,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "operational": False,
        }
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
                TERRAIN_FEATURE_STACK_WORKFLOW_VERSION
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
                        "terrain_feature_stack"
                        if request.workflow_id == TERRAIN_FEATURE_STACK_WORKFLOW_ID
                        else "terrain_context_preview"
                    ),
                    "source_count": len(dem_refs),
                    "tool_allowlist": list(QGIS_ALLOWED_TOOL_IDS),
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
            "slope_raster",
            "aspect_raster",
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
            max_bytes = (
                256 * 1024 * 1024
                if artifact_type.endswith("_raster")
                else 16 * 1024 * 1024
            )
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

        run_id = local_run.workflow_run_id
        root_ref = f"{QGIS_WORKFLOW_ROOT_REF}/{run_id}"
        route_ref = f"{root_ref}/terrain_feature_stack.geojson"
        metadata_ref = f"{root_ref}/artifact_metadata.json"
        refs_by_type = {
            "slope_raster": f"{root_ref}/grass_slope.tif",
            "aspect_raster": f"{root_ref}/grass_aspect.tif",
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
            "slope_raster": "grass:r.slope.aspect",
            "aspect_raster": "grass:r.slope.aspect",
            "geomorphon_raster": "grass:r.geomorphon",
            "geomorphon_fine_raster": "grass:r.geomorphon",
            "geomorphon_coarse_raster": "grass:r.geomorphon",
            "geomorphon_consensus_ridge_raster": "grass:r.mapcalc.simple",
            "geomorphon_consensus_valley_raster": "grass:r.mapcalc.simple",
            "flow_accumulation_raster": "grass:r.watershed",
            "stream_network_raster": "grass:r.watershed+r.mapcalc.simple",
            "ridge_lines_vector": "grass:r.mapcalc.simple+r.thin+r.to.vect",
            "valley_lines_vector": "grass:r.mapcalc.simple+r.thin+r.to.vect",
            "stream_network_vector": "grass:r.watershed+r.mapcalc.simple+r.thin+r.to.vect",
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
            metadata_ref: metadata_bytes,
            **{
                refs_by_type[artifact_type]: raw
                for artifact_type, raw in artifact_bytes.items()
            },
        }
        for ref, data in writes.items():
            _write_bytes(_safe_project_path(project_root, ref), data)
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
            detail=None,
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


def _validated_candidate_geojson(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = _json_bytes(payload)
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


def _validate_candidate_terrain_vector_bytes(
    raw: bytes,
    *,
    expected_kind: str,
) -> None:
    if len(raw) > 16 * 1024 * 1024:
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
                if coordinate_count > 500_000:
                    raise QgisSpatialBackendError(
                        "QGIS candidate terrain vector has too many coordinates"
                    )


def _public_worker_error(
    error: SpatialAnalysisError | None,
) -> SpatialAnalysisError | None:
    if error is None:
        return None
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
