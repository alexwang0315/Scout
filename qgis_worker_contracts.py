from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from qgis_spatial_contracts import (
    TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID,
    QgisBackendAvailability,
    SpatialAnalysisError,
    SpatialAuthorityBoundary,
    SpatialWorkflowState,
    SpatialWorkflowStep,
    qgis_candidate_boundary,
)


QGIS_WORKER_SCHEMA_VERSION = "scout_qgis_worker.v0_1"
QGIS_WORKER_REQUEST_SCHEMA_VERSION = "scout_qgis_worker_request.v0_1"
QgisWorkerWorkflowId = Literal[
    "terrain_context_preview.v1",
    "terrain_feature_stack.v1",
]


class QgisWorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = QGIS_WORKER_SCHEMA_VERSION
    worker_id: str = "scout_qgis_worker"
    availability: QgisBackendAvailability
    enabled: bool
    configured: bool
    mcp_reachable: bool = False
    qgis_application_available: bool = False
    plugin_bridge_available: bool = False
    project_loaded: bool = False
    capabilities_discoverable: bool = False
    backend_degraded: bool = False
    qgis_version: str = "unavailable"
    qgis_mcp_plugin_version: str = "unavailable"
    last_successful_handshake: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[SpatialAnalysisError] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    algorithm_allowlist: list[str] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    boundary: SpatialAuthorityBoundary = Field(default_factory=qgis_candidate_boundary)


class QgisWorkerWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scout_qgis_worker_request.v0_1"] = (
        QGIS_WORKER_REQUEST_SCHEMA_VERSION
    )
    workflow_id: QgisWorkerWorkflowId = TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    requested_by: str = Field(min_length=1, max_length=120)
    corridor_m: float = Field(default=250.0, ge=0, le=5000)
    route_geojson: dict[str, Any]
    dem_refs: list[str] = Field(min_length=1, max_length=32)
    source_refs: list[str] = Field(default_factory=list, max_length=64)
    source_hashes: dict[str, str] = Field(default_factory=dict)
    source_resolution: dict[str, Any] = Field(default_factory=dict)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False

    @field_validator("route_geojson")
    @classmethod
    def validate_route_geojson(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "FeatureCollection":
            raise ValueError("route_geojson must be a FeatureCollection")
        features = value.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise ValueError("route_geojson must contain exactly one route feature")
        geometry = features[0].get("geometry") if isinstance(features[0], dict) else None
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError("route_geojson geometry must be a LineString")
        if not isinstance(coordinates, list) or not 2 <= len(coordinates) <= 20_000:
            raise ValueError("route_geojson must contain 2 to 20000 coordinates")
        for coordinate in coordinates:
            if not isinstance(coordinate, list) or len(coordinate) < 2:
                raise ValueError("route_geojson contains an invalid coordinate")
            lon, lat = coordinate[:2]
            if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
                raise ValueError("route_geojson coordinates must be numeric")
            if not -180 <= float(lon) <= 180 or not -90 <= float(lat) <= 90:
                raise ValueError("route_geojson coordinate is outside WGS84 bounds")
        return value


class QgisWorkerArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    artifact_type: Literal[
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
        "qgis_render_preview",
        "qgis_visual_context",
    ]
    relative_ref: str
    media_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_count: int = Field(ge=0)
    width_px: int | None = Field(default=None, ge=1, le=4096)
    height_px: int | None = Field(default=None, ge=1, le=4096)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    visualization_only: bool = False
    adds_source_resolution: Literal[False] = False

    @field_validator("relative_ref")
    @classmethod
    def validate_relative_ref(cls, value: str) -> str:
        if not value or value.startswith(("/", "~")) or ".." in value.split("/"):
            raise ValueError("worker artifact ref must be bounded and relative")
        return value


class QgisWorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maplibre_geojson: dict[str, Any]
    artifacts: list[QgisWorkerArtifact]
    qgis_version: str = "unavailable"
    qgis_mcp_plugin_version: str = "unavailable"
    crs: str = "UNKNOWN"
    source_resolution: dict[str, Any] = Field(default_factory=dict)
    output_resolution: dict[str, Any] = Field(default_factory=dict)
    processing_algorithms: list[str] = Field(default_factory=list)
    processing_parameters: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    adds_source_resolution: Literal[False] = False


class QgisWorkerRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = QGIS_WORKER_SCHEMA_VERSION
    worker_run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    project_id: str
    workflow_id: QgisWorkerWorkflowId = TERRAIN_CONTEXT_PREVIEW_WORKFLOW_ID
    workflow_version: str = "0.1"
    request_id: str
    requested_by: str
    state: SpatialWorkflowState
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None
    processing_status: str = "pending"
    render_status: str = "pending"
    visual_review_status: Literal["pending"] = "pending"
    human_review_status: Literal["pending"] = "pending"
    steps: list[SpatialWorkflowStep] = Field(default_factory=list)
    result: QgisWorkerResult | None = None
    warnings: list[str] = Field(default_factory=list)
    error: SpatialAnalysisError | None = None
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    operational: Literal[False] = False
    boundary: SpatialAuthorityBoundary = Field(default_factory=qgis_candidate_boundary)

    @model_validator(mode="after")
    def enforce_completed_result(self) -> "QgisWorkerRun":
        if self.state is SpatialWorkflowState.COMPLETED and self.result is None:
            raise ValueError("completed QGIS worker run requires a result")
        return self
