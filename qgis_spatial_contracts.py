from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


QGIS_SPATIAL_SCHEMA_VERSION = "scout_qgis_spatial.v0_1"
TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID = "terrain_context_preview.v1"
TERRAIN_CONTEXT_PREVIEW_WORKFLOW_VERSION = "0.1"
TERRAIN_FEATURE_STACK_WORKFLOW_ID = "terrain_feature_stack.v1"
TERRAIN_FEATURE_STACK_WORKFLOW_VERSION = "0.1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QgisBackendAvailability(str, Enum):
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    CONNECTING = "connecting"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    ERROR = "error"


class SpatialCapabilityCategory(str, Enum):
    PROJECT = "project"
    VECTOR = "vector"
    RASTER = "raster"
    PROCESSING = "processing"
    TERRAIN = "terrain"
    HYDROLOGY = "hydrology"
    CARTOGRAPHY = "cartography"
    RENDER = "render"
    LAYOUT = "layout"
    THREE_D = "3d"


class SpatialWorkflowState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpatialWorkflowStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SpatialArtifactStatus(str, Enum):
    RAW = "raw"
    CANDIDATE = "candidate"
    REVIEWED_EVIDENCE = "reviewed_evidence"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class SpatialAnalysisErrorCode(str, Enum):
    BACKEND_NOT_CONFIGURED = "BACKEND_NOT_CONFIGURED"
    QGIS_UNAVAILABLE = "QGIS_UNAVAILABLE"
    MCP_UNAVAILABLE = "MCP_UNAVAILABLE"
    PROJECT_UNAVAILABLE = "PROJECT_UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    CRS_UNRESOLVED = "CRS_UNRESOLVED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    WORKFLOW_INTERRUPTED = "WORKFLOW_INTERRUPTED"
    ARTIFACT_EXPORT_FAILED = "ARTIFACT_EXPORT_FAILED"
    UNSUPPORTED_TOOL = "UNSUPPORTED_TOOL"
    FORBIDDEN_CAPABILITY = "FORBIDDEN_CAPABILITY"
    UNKNOWN = "UNKNOWN"


class SpatialAuthorityBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_called: Literal[False] = False
    browser_direct_mcp_allowed: Literal[False] = False
    arbitrary_python_allowed: Literal[False] = False
    shell_execution_allowed: Literal[False] = False
    unrestricted_filesystem_allowed: Literal[False] = False
    human_review_required: bool = True
    safe_or_walkable: Literal["not_determined"] = "not_determined"


def qgis_candidate_boundary() -> SpatialAuthorityBoundary:
    return SpatialAuthorityBoundary()


class SpatialAnalysisError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: SpatialAnalysisErrorCode
    message: str
    detail: str | None = None
    retryable: bool = False
    at_step: str | None = None


class QgisProjectContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    project_loaded: bool = False
    project_label: str | None = None
    crs: str = "UNKNOWN"
    source_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class QgisBackendStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = QGIS_SPATIAL_SCHEMA_VERSION
    backend_id: str = "qgis_agent_mcp"
    availability: QgisBackendAvailability
    enabled: bool
    configured: bool
    endpoint_configured: bool = False
    reachable: bool = False
    qgis_application_available: bool = False
    plugin_bridge_available: bool = False
    project_loaded: bool = False
    capabilities_discoverable: bool = False
    backend_degraded: bool = False
    fixture_mode: bool = False
    qgis_version: str = "unavailable"
    qgis_mcp_plugin_version: str = "unavailable"
    last_successful_handshake: str | None = None
    project_context: QgisProjectContext | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[SpatialAnalysisError] = Field(default_factory=list)
    boundary: SpatialAuthorityBoundary = Field(default_factory=qgis_candidate_boundary)


class SpatialCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    category: SpatialCapabilityCategory
    title: str
    enabled: bool = True
    allowed: bool = True
    workflow_ids: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    dangerous: Literal[False] = False
    arbitrary_python_allowed: Literal[False] = False
    shell_execution_allowed: Literal[False] = False


class SpatialCapabilityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = QGIS_SPATIAL_SCHEMA_VERSION
    backend_id: str = "qgis_agent_mcp"
    categories: list[SpatialCapabilityCategory] = Field(default_factory=list)
    capabilities: list[SpatialCapability] = Field(default_factory=list)
    blocked_capabilities: list[str] = Field(default_factory=list)
    workflow_allowlist: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    boundary: SpatialAuthorityBoundary = Field(default_factory=qgis_candidate_boundary)


class SpatialAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str = TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID
    project_id: str | None = None
    route_ref: str | None = None
    dem_ref: str | None = None
    corridor_m: float = 250.0
    requested_by: str = "dashboard_operator"
    request_id: str | None = None

    @field_validator("corridor_m")
    @classmethod
    def validate_corridor_m(cls, value: float) -> float:
        corridor = float(value)
        if corridor < 0 or corridor > 5000:
            raise ValueError("corridor_m must be between 0 and 5000")
        return corridor

    @field_validator("workflow_id")
    @classmethod
    def validate_workflow_id(cls, value: str) -> str:
        workflow_id = value.strip()
        if not workflow_id:
            raise ValueError("workflow_id is required")
        return workflow_id


class SpatialEvidenceReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["reviewed_evidence"] = "reviewed_evidence"
    reviewed_by: str = Field(min_length=1, max_length=120)
    review_note: str = Field(default="", max_length=1000)

    @field_validator("reviewed_by", "review_note")
    @classmethod
    def strip_review_text(cls, value: str) -> str:
        return value.strip()


class SpatialWorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    label: str
    status: SpatialWorkflowStepStatus
    started_at: str | None = None
    completed_at: str | None = None
    selected_capability: SpatialCapabilityCategory | None = None
    tool_id: str | None = None
    warning: str | None = None
    error: SpatialAnalysisError | None = None


class SpatialArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    artifact_type: str
    schema_version: str = "scout_qgis_spatial_artifact.v0_1"
    workflow_id: str
    workflow_version: str
    workflow_run_id: str
    created_at: str
    source_refs: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    qgis_version: str = "unavailable"
    qgis_mcp_plugin_version: str = "unavailable"
    crs: str = "UNKNOWN"
    source_resolution: dict[str, Any] = Field(default_factory=dict)
    output_resolution: dict[str, Any] = Field(default_factory=dict)
    processing_algorithm: str = "UNKNOWN"
    processing_parameters: dict[str, Any] = Field(default_factory=dict)
    candidate_only: bool = True
    visualization_only: bool = False
    runtime_safety_truth: bool = False
    operational: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)
    status: SpatialArtifactStatus = SpatialArtifactStatus.CANDIDATE
    warnings: list[str] = Field(default_factory=list)
    errors: list[SpatialAnalysisError] = Field(default_factory=list)
    artifact_hash: str | None = None
    artifact_ref: str | None = None
    media_type: str = "application/json"
    fixture: bool = False
    synthetic: bool = False
    adds_source_resolution: bool = False

    @model_validator(mode="after")
    def enforce_candidate_boundary(self) -> "SpatialArtifact":
        if self.candidate_only is not True:
            raise ValueError("QGIS-derived artifacts must be candidate_only=true")
        if self.runtime_safety_truth is not False:
            raise ValueError("QGIS-derived artifacts must keep runtime_safety_truth=false")
        if self.operational is not False:
            raise ValueError("QGIS-derived artifacts must keep operational=false")
        return self


class SpatialRenderArtifact(SpatialArtifact):
    width_px: int | None = None
    height_px: int | None = None
    render_status: str = "completed"
    visual_review_status: str = "pending"

    @model_validator(mode="after")
    def enforce_visualization_boundary(self) -> "SpatialRenderArtifact":
        self.visualization_only = True
        return self


class SpatialWorkflowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = QGIS_SPATIAL_SCHEMA_VERSION
    project_id: str
    workflow_id: str
    workflow_version: str
    workflow_run_id: str
    backend_run_id: str | None = None
    backend_id: str = "qgis_agent_mcp"
    request_id: str
    requested_by: str
    state: SpatialWorkflowState
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None
    processing_status: str = "pending"
    render_status: str = "pending"
    machine_review_status: str = "not_started"
    visual_review_status: str = "pending"
    human_review_status: str = "pending"
    steps: list[SpatialWorkflowStep] = Field(default_factory=list)
    artifacts: list[SpatialArtifact] = Field(default_factory=list)
    render_artifacts: list[SpatialRenderArtifact] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    source_resolution: dict[str, Any] = Field(default_factory=dict)
    maplibre_geojson: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    error: SpatialAnalysisError | None = None
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    operational: bool = False
    boundary: SpatialAuthorityBoundary = Field(default_factory=qgis_candidate_boundary)

    @model_validator(mode="after")
    def enforce_workflow_boundary(self) -> "SpatialWorkflowRun":
        if self.candidate_only is not True:
            raise ValueError("QGIS workflows must be candidate_only=true")
        if self.runtime_safety_truth is not False:
            raise ValueError("QGIS workflows must keep runtime_safety_truth=false")
        if self.operational is not False:
            raise ValueError("QGIS workflows must keep operational=false")
        return self
