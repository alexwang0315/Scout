"""Read-only, hash-bound projection of one existing QGIS terrain workflow."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ConfigDict, Field

from scout.nextgen.intelligence_gateway import (
    CapabilityBroker, GeoScope, IntelligenceRequest, IntelligenceTaskType, WorkspaceBinding,
)
from scout.nextgen.claim_support import (
    ClaimEvidenceBinding, ClaimFact, ClaimSupportContract, SupportedClaim, evidence_payload_hash,
)
from scout.nextgen.praison_service import EvidenceCatalog, EvidenceCatalogItem, SpecialistReport
from scout.schemas.base import NonEmptyStr, SchemaModel


class TerrainProjectionSource(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: NonEmptyStr
    source_ref: NonEmptyStr
    verified_path: NonEmptyStr
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TerrainProjectionMetrics(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_count: int = Field(ge=1)
    missing_slope_count: int = Field(ge=0)
    missing_geomorphon_count: int = Field(ge=0)
    ridge_sample_count: int = Field(ge=0)
    slope_ge_30_count: int = Field(ge=0)
    slope_ge_40_count: int = Field(ge=0)
    max_slope_degrees: float | None = Field(default=None, ge=0, le=90)
    resolution_x_m: float = Field(gt=0, allow_inf_nan=False)
    resolution_y_m: float = Field(gt=0, allow_inf_nan=False)


class WorkspaceTerrainProjection(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scout.workspace_terrain_projection.v0"] = (
        "scout.workspace_terrain_projection.v0"
    )
    compiled_at: datetime
    workspace_binding: WorkspaceBinding
    workflow_run_id: NonEmptyStr
    source_artifact_generated_at: datetime
    sources: tuple[TerrainProjectionSource, ...]
    metrics: TerrainProjectionMetrics
    evidence_catalog: EvidenceCatalog
    human_review_status: NonEmptyStr
    machine_review_status: NonEmptyStr
    saddle_status: Literal["UNKNOWN"] = "UNKNOWN"
    field_conditions_status: Literal["UNKNOWN"] = "UNKNOWN"
    current_position_status: Literal["UNKNOWN"] = "UNKNOWN"
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    def build_request(self) -> IntelligenceRequest:
        verify_projection_sources(self)
        request_id = uuid4()
        binding = self.workspace_binding
        refs = tuple(item.source_ref for item in self.evidence_catalog.items)
        grant = CapabilityBroker().issue_grant(
            request_id=request_id, mission_id=binding.mission_id,
            task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
            allowed_capabilities=("route.read", "dem.read", "qgis.processing.slope"),
            evidence_refs_allowed=refs, ttl_seconds=3600,
            max_model_requests=10, max_tool_calls=10,
            provenance_ref=f"{self.schema_version}:{binding.input_hash}",
        )
        return IntelligenceRequest(
            request_id=request_id, mission_id=binding.mission_id,
            task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
            question=(
                "Summarize ridge and steep terrain candidates from this historical "
                "route/DEM analysis. State what remains UNKNOWN, including saddle "
                "evidence and current field conditions. This is not current route "
                "or safety advice."
            ),
            workspace_binding=binding, capability_grant=grant,
            geographic_scope=GeoScope(route_id=binding.route_id), evidence_refs=refs,
            claim_support=self.build_claim_support(),
            max_model_requests=10, allow_cloud_escalation=False, privacy_sensitive=True,
        )

    def build_claim_support(self) -> ClaimSupportContract:
        verify_projection_sources(self)
        item = next(item for item in self.evidence_catalog.items
                    if item.source_type == "qgis_terrain_samples")
        features = {feature["kind"]: feature for feature in item.attributes["candidate_features"]}
        metrics = self.metrics
        definitions = (
            ("ridge_samples", "ridge", (
                ClaimFact(name="sample_count", value=metrics.sample_count),
                ClaimFact(name="ridge_sample_count", value=metrics.ridge_sample_count),
                ClaimFact(name="missing_geomorphon_count", value=metrics.missing_geomorphon_count),
            )),
            ("steep_samples", "steep_terrain", (
                ClaimFact(name="sample_count", value=metrics.sample_count),
                ClaimFact(name="slope_ge_30_count", value=metrics.slope_ge_30_count),
                ClaimFact(name="slope_ge_40_count", value=metrics.slope_ge_40_count),
                ClaimFact(name="max_slope_degrees", value=metrics.max_slope_degrees),
                ClaimFact(name="missing_slope_count", value=metrics.missing_slope_count),
            )),
        )
        return ClaimSupportContract(
            input_hash=self.workspace_binding.input_hash,
            context_uncertainty_hashes=tuple(evidence_payload_hash(uncertainty.model_dump(mode="json"))
                                            for uncertainty in SpecialistReport.from_catalog_item(role="qgis", item=item).uncertainties),
            evidence=tuple(ClaimEvidenceBinding.from_evidence(
                source.as_candidate_evidence().model_dump(mode="json"),
            ) for source in self.evidence_catalog.items),
            claims=tuple(SupportedClaim(
                claim_id=claim_id, kind=kind, statement=features[kind]["claim"],
                evidence_id=item.evidence_id, facts=facts,
            ) for claim_id, kind, facts in definitions),
        )


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _workspace_path(root: Path, ref: str | Path) -> Path:
    path = (root / ref).resolve()
    if not path.is_relative_to(root):
        raise ValueError("terrain source is outside workspace")
    return path


def _candidate(payload: dict, *, real: bool = False) -> None:
    expected = {"candidate_only": True, "operational": False, "runtime_safety_truth": False}
    if real:
        expected.update(fixture=False, synthetic=False)
    if any(payload.get(key) is not value for key, value in expected.items()):
        raise ValueError("terrain source is not a real candidate-only artifact")
    if payload.get("adds_source_resolution", False) is not False:
        raise ValueError("terrain projection cannot add source resolution")


def _input_hash(sources, metrics, catalog) -> str:
    value = {
        "sources": [(item.role, item.source_ref, item.sha256) for item in sources],
        "metrics": metrics.model_dump(mode="json"),
        "catalog": catalog.model_dump(mode="json"),
    }
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def verify_projection_sources(projection: WorkspaceTerrainProjection) -> WorkspaceBinding:
    if (_input_hash(projection.sources, projection.metrics, projection.evidence_catalog)
            != projection.workspace_binding.input_hash):
        raise ValueError("stale terrain projection input binding")
    for source in projection.sources:
        path = Path(source.verified_path)
        if not path.is_file() or _hash_file(path) != source.sha256:
            raise ValueError(f"stale terrain projection source: {source.role}")
    return projection.workspace_binding


def _metrics(samples: dict, manifest: dict) -> TerrainProjectionMetrics:
    metadata = samples["metadata"]
    _candidate(metadata)
    run_id = manifest["workflow_run_id"]
    if metadata["workflow_run_id"] != run_id or samples.get("type") != "FeatureCollection":
        raise ValueError("terrain samples workflow binding mismatch")
    features = samples["features"]
    if len(features) != metadata["sample_count"] or not features:
        raise ValueError("terrain sample count mismatch")
    slopes, codes, sample_ids = [], [], []
    for feature in features:
        props = feature["properties"]
        _candidate(props, real=True)
        if props["workflow_run_id"] != run_id:
            raise ValueError("terrain sample workflow binding mismatch")
        sample_ids.append(props["sample_id"])
        slope = props.get("slope_degrees")
        if slope is not None:
            if type(slope) not in (int, float) or not math.isfinite(slope) or not 0 <= slope <= 90:
                raise ValueError("invalid terrain slope value")
            slopes.append(slope)
        code = props.get("geomorphon_consensus_code")
        if code is not None:
            if type(code) is not int or not 1 <= code <= 10:
                raise ValueError("invalid terrain geomorphon code")
            codes.append(code)
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("duplicate terrain sample ids")
    return TerrainProjectionMetrics(
        sample_count=len(features), missing_slope_count=len(features) - len(slopes),
        missing_geomorphon_count=len(features) - len(codes), ridge_sample_count=codes.count(3),
        slope_ge_30_count=sum(slope >= 30 for slope in slopes),
        slope_ge_40_count=sum(slope >= 40 for slope in slopes),
        max_slope_degrees=max(slopes) if slopes else None,
        resolution_x_m=manifest["source_resolution"]["x_m"],
        resolution_y_m=manifest["source_resolution"]["y_m"],
    )


def build_workspace_terrain_projection(
    workspace_root: Path, qgis_run: Path, dem_source: Path,
) -> WorkspaceTerrainProjection:
    """Compile existing outputs only; never prepare or modify the Workspace."""
    root = workspace_root.resolve(strict=True)
    sources: list[TerrainProjectionSource] = []

    def read_source(role: str, path: Path, ref: str | None = None, *, parse: bool = True):
        raw = path.read_bytes()
        sources.append(TerrainProjectionSource(
            role=role, source_ref=ref or str(path.relative_to(root)),
            verified_path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
        ))
        return json.loads(raw) if parse else sources[-1].sha256

    project = read_source("project", _workspace_path(root, "project.json"))
    bundle = read_source("route_bundle", _workspace_path(root, project["route_evidence_bundle_ref"]))
    route = _workspace_path(root, bundle["golden_route"]["filtered_geometry_ref"])
    route_hash = read_source("route", route, parse=False)
    run = _workspace_path(root, qgis_run)
    manifest_path = _workspace_path(root, run / "terrain_feature_manifest.json")
    manifest = read_source("manifest", manifest_path)
    workflow = read_source("workflow", _workspace_path(root, run / "workflow_run.json"))
    _candidate(manifest)
    _candidate(workflow)
    if (workflow["workflow_run_id"] != manifest["workflow_run_id"]
            or workflow["project_id"] != project["project_id"]
            or workflow["workflow_id"] != "terrain_feature_stack.v1"
            or manifest["workflow_id"] != "terrain_feature_stack.v1"
            or workflow["state"] != "completed"
            or workflow["processing_status"] != "completed"):
        raise ValueError("terrain workflow binding or completion mismatch")
    samples_path = _workspace_path(root, run / manifest["artifacts"]["route_feature_samples"])
    samples = read_source("samples", samples_path)
    for path in (manifest_path, samples_path):
        ref = str(path.relative_to(root))
        entries = [item for item in workflow["artifacts"] if item.get("artifact_ref") == ref]
        if len(entries) != 1 or entries[0].get("artifact_hash") != _hash_file(path):
            raise ValueError("terrain derived artifact hash mismatch")
        _candidate(entries[0], real=True)
    route_ref = str(route.relative_to(root))
    if (workflow["source_hashes"].get(route_ref) != route_hash
            or route_hash not in manifest["source_hashes"].values()):
        raise ValueError("terrain route source hash mismatch")
    dem_ref = manifest["source_dem_inspection"]["summary"]["source"]
    dem_hash = read_source("dem", dem_source.resolve(strict=True), dem_ref, parse=False)
    if manifest["source_hashes"].get(dem_ref) != dem_hash:
        raise ValueError("terrain DEM source hash mismatch")
    metrics = _metrics(samples, manifest)
    generated_at = datetime.fromisoformat(workflow["completed_at"].replace("Z", "+00:00"))
    if generated_at.tzinfo is None:
        raise ValueError("terrain artifact timestamp requires timezone")
    source_tuple = tuple(sources)
    catalog = _catalog(source_tuple, metrics, generated_at, manifest, workflow)
    binding = WorkspaceBinding(
        workspace_id=project["project_id"], workspace_revision=sources[0].sha256,
        mission_id=f"{project['project_id']}:terrain-intelligence-experimental",
        mission_version="read-only-projection-v0", route_id=f"{project['project_id']}:golden-route",
        route_version=route_hash, input_hash=_input_hash(source_tuple, metrics, catalog),
    )
    projection = WorkspaceTerrainProjection(
        compiled_at=datetime.now(UTC), workspace_binding=binding,
        workflow_run_id=manifest["workflow_run_id"], source_artifact_generated_at=generated_at,
        sources=source_tuple, metrics=metrics,
        evidence_catalog=catalog,
        human_review_status=workflow.get("human_review_status") or "UNKNOWN",
        machine_review_status=workflow.get("machine_review_status") or "UNKNOWN",
    )
    verify_projection_sources(projection)
    return projection


def _catalog(sources, metrics, generated_at, manifest, workflow) -> EvidenceCatalog:
    by_role = {item.role: item for item in sources}
    resolution = f"{metrics.resolution_x_m:g}m x {metrics.resolution_y_m:g}m"
    ridge = f"{metrics.ridge_sample_count}/{metrics.sample_count} samples have ridge consensus code 3."
    steep = (f"{metrics.slope_ge_30_count}/{metrics.sample_count} samples have slope >=30 degrees; "
             f"{metrics.slope_ge_40_count} have slope >=40 degrees; "
             f"maximum={metrics.max_slope_degrees} degrees.")
    uncertainties = [
        {"description": "Saddle evidence is UNKNOWN; no saddle derivative was supplied.",
         "missing_evidence": ["saddle_derivative"], "impact": "Do not infer saddle locations."},
        {"description": "Historical terrain artifacts, not current field observations.",
         "missing_evidence": ["current_field_conditions", "current_position"],
         "impact": "Trail existence, passability, hazards and safety remain UNKNOWN."},
        {"description": f"Review state: human={workflow.get('human_review_status', 'UNKNOWN')}; "
                        f"machine={workflow.get('machine_review_status', 'UNKNOWN')}.",
         "missing_evidence": ["qualified_terrain_review"], "impact": "Candidate analysis only."},
    ]
    if manifest.get("parameters", {}).get("route_export_file_crs") == "UNKNOWN":
        uncertainties.append({
            "description": "Original route export file CRS was UNKNOWN; runtime assignment was explicit.",
            "missing_evidence": ["independent_crs_review"],
            "impact": "Do not treat assigned metadata as independently verified alignment.",
        })
    if metrics.missing_slope_count or metrics.missing_geomorphon_count:
        uncertainties.append({
            "description": f"Missing samples: slope={metrics.missing_slope_count}; "
                           f"geomorphon={metrics.missing_geomorphon_count}.",
            "missing_evidence": ["complete_terrain_samples"],
            "impact": "Counts summarize available samples, not the whole route or corridor.",
        })
    common = {"generated_at": generated_at, "observed_at": None}
    return EvidenceCatalog(items=(
        EvidenceCatalogItem(
            evidence_id="workspace-route", source_ref=by_role["route"].source_ref,
            source_type="route_gpx", content_hash=by_role["route"].sha256,
            summary="Hash-verified historical reference GPX; not a current position or verified trail.",
            method="existing_filtered_gpx_hash_verification", **common,
        ),
        EvidenceCatalogItem(
            evidence_id="workspace-dem", source_ref=by_role["dem"].source_ref,
            source_type="dem_prepared", content_hash=by_role["dem"].sha256,
            summary=f"Historical {resolution} prepared DEM. Derived sample counts: {ridge} {steep}",
            method="prepared_dem_hash_verification_and_qgis_sample_aggregation",
            resolution=resolution, **common,
            attributes={"derived_sample_ref": by_role["samples"].source_ref,
                        "derived_sample_hash": by_role["samples"].sha256,
                        "uncertainties": uncertainties},
        ),
        EvidenceCatalogItem(
            evidence_id="workspace-qgis", source_ref=by_role["samples"].source_ref,
            source_type="qgis_terrain_samples", content_hash=by_role["samples"].sha256,
            summary=f"Deterministic historical sample aggregation. {ridge} {steep}",
            method="qgis_identify_nearest_raster_cell_then_python_aggregation",
            resolution=resolution, **common,
            attributes={"candidate_features": [
                {"kind": "ridge", "claim": ridge, "confidence": 1.0},
                {"kind": "steep_terrain", "claim": steep, "confidence": 1.0},
            ], "confidence_semantics": "exact source aggregation, not terrain or safety certainty",
                "uncertainties": uncertainties,
                "manifest_hash": by_role["manifest"].sha256,
                "workflow_hash": by_role["workflow"].sha256},
        ),
    ))
