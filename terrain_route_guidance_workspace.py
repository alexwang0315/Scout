"""Workspace lifecycle for reviewed narrative-guided terrain hypotheses."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scout.agents import PydanticScoutAgentProvider, ScoutDeps, TerrainNarrativeGuidanceAgent
from terrain_route_guidance import (
    TerrainGuidanceConstraintKind,
    TerrainGuidanceCorridorOverlap,
    TerrainGuidanceCorridorReference,
    TerrainGuidanceCostModifier,
    TerrainGuidanceCostModifierKind,
    TerrainGuidanceFeatureCandidate,
    TerrainGuidanceFeatureIndex,
    TerrainGuidanceExecutionAnchor,
    TerrainGuidanceExecutionPlan,
    TerrainGuidanceInterpretationStatus,
    TerrainGuidanceLandform,
    TerrainGuidanceResolution,
    TerrainGuidanceReviewStatus,
    TerrainGuidanceSearchWindow,
    TerrainNarrativeConstraint,
    TerrainNarrativeGuidancePlan,
    TerrainNarrativeGuidanceReview,
    build_narrative_guidance_review,
    resolve_terrain_route_guidance,
    terrain_guidance_plan_sha256,
    terrain_guidance_resolution_sha256,
    terrain_guidance_review_sha256,
    validate_narrative_guidance_plan,
)
from terrain_route_hypothesis_models import (
    GeoPoint,
    TerrainRouteHypothesisCatalog,
    TerrainRouteHypothesisRun,
    TerrainRouteRunStatus,
)


GUIDANCE_WORKSPACE_ROOT_REF = "outputs/spatial/qgis/terrain_route_guidance"
GUIDANCE_MANIFEST_VERSION = "scout_terrain_route_guidance_manifest.v0_1"
GUIDED_ROUTE_CACHE_VERSION = "scout_guided_terrain_route_cache.v0_1"
MAX_GUIDANCE_LOCAL_FEATURES = 2_000
MAX_GUIDANCE_LOCAL_COORDINATES = 100_000
TERRAIN_GUIDANCE_DEM_DERIVATION_VERSION = "dem_ridge_elevation_saddle_proxy.v0_1"
MAX_GUIDANCE_CORRIDOR_SAMPLES_PER_FEATURE = 24
MAX_GUIDANCE_CORRIDOR_SAMPLE_POINTS = 50_000


@dataclass(frozen=True)
class _CandidateCorridorReference:
    hypothesis_id: str
    hypothesis_sha256: str
    cache_key: str
    band_name: str
    raster_ref: str
    raster_sha256: str
    raster_crs: str
    raster_path: Path
    bbox_wgs84: dict[str, float]
    inside_value: float = 1.0
    nodata_value: float = 255.0


class TerrainGuidanceElevationSampler(Protocol):
    backend_id: str

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]: ...


class TerrainGuidanceWorkspaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TerrainGuidanceInterpretRequest(TerrainGuidanceWorkspaceModel):
    narrative: str = Field(min_length=1, max_length=32_000)
    source_id: str = Field(min_length=1, max_length=240)
    source_date: str | None = Field(default=None, max_length=80)
    requested_by: str = Field(default="dashboard_operator", min_length=1, max_length=120)

    @field_validator("narrative", "source_id", "source_date", "requested_by")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("text value cannot be blank")
        return normalized


class TerrainGuidanceManualAnchorRequest(TerrainGuidanceWorkspaceModel):
    constraint_id: str = Field(pattern=r"^G[1-9][0-9]*$")
    point: GeoPoint


class TerrainGuidanceResolveRequest(TerrainGuidanceWorkspaceModel):
    guidance_id: str = Field(min_length=1)
    route_start: GeoPoint | None = None
    route_destination: GeoPoint | None = None
    search_margin_m: float = Field(default=1000, ge=100, le=5000)
    reference_hypothesis_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,79}$",
    )
    reference_corridor_band_name: Literal[
        "top_5_percent_corridor",
        "top_10_percent_corridor",
        "top_20_percent_corridor",
    ] = "top_5_percent_corridor"
    manual_anchors: list[TerrainGuidanceManualAnchorRequest] = Field(
        default_factory=list,
        max_length=100,
    )

    @field_validator("manual_anchors")
    @classmethod
    def unique_manual_constraints(
        cls,
        value: list[TerrainGuidanceManualAnchorRequest],
    ) -> list[TerrainGuidanceManualAnchorRequest]:
        ids = [item.constraint_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("manual anchor constraint IDs must be unique")
        return value

    @model_validator(mode="after")
    def require_route_window(self) -> "TerrainGuidanceResolveRequest":
        if self.route_start is None or self.route_destination is None:
            raise ValueError("route_start and route_destination are required")
        if (
            self.route_start.crs != "EPSG:4326"
            or self.route_destination.crs != "EPSG:4326"
        ):
            raise ValueError("terrain guidance route endpoints must use EPSG:4326")
        if (
            self.route_start.x == self.route_destination.x
            and self.route_start.y == self.route_destination.y
        ):
            raise ValueError("terrain guidance route endpoints must differ")
        return self


class TerrainGuidanceReviewRequest(TerrainGuidanceWorkspaceModel):
    guidance_id: str = Field(min_length=1)
    selected_feature_ids: dict[str, str] = Field(default_factory=dict)
    disabled_constraint_ids: list[str] = Field(default_factory=list)
    reviewed_by: str = Field(default="trip_leader", min_length=1, max_length=120)
    reviewed_at: datetime | None = None

    @field_validator("reviewed_by")
    @classmethod
    def normalize_reviewer(cls, value: str) -> str:
        return value.strip()


class TerrainRouteGuidanceWorkspaceService:
    """Persist a hash-bound interpret -> resolve -> human-review lifecycle."""

    def __init__(
        self,
        *,
        now_factory: Callable[[], datetime] | None = None,
        elevation_sampler: TerrainGuidanceElevationSampler | None = None,
    ) -> None:
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._elevation_sampler = elevation_sampler

    def interpret(
        self,
        project_root: Path | str,
        *,
        project_id: str,
        request: TerrainGuidanceInterpretRequest,
    ) -> dict[str, Any]:
        root, project = _load_project(project_root, project_id=project_id)
        deps = ScoutDeps(
            capability_registry=None,
            memory_store=None,
            workflow_store=None,
            sandbox=None,
            permission_gate=None,
            notification_gateway=None,
            docs_search=None,
            user_id=request.requested_by,
            active_context={"project_root": str(root), "project_id": project_id},
        )
        plan = TerrainNarrativeGuidanceAgent(PydanticScoutAgentProvider()).interpret(
            request.narrative,
            source_id=request.source_id,
            source_date=request.source_date,
            deps=deps,
        )
        guidance_root_ref = f"{GUIDANCE_WORKSPACE_ROOT_REF}/{plan.guidance_id}"
        narrative_ref = f"{guidance_root_ref}/narrative.txt"
        plan_ref = f"{guidance_root_ref}/guidance_plan.json"
        manifest_ref = f"{guidance_root_ref}/manifest.json"
        narrative_bytes = request.narrative.encode("utf-8")
        plan_bytes = _json_bytes(plan.model_dump(mode="json"))
        _write_bytes(_safe_project_path(root, narrative_ref), narrative_bytes)
        _write_bytes(_safe_project_path(root, plan_ref), plan_bytes)
        parent = _terrain_parent_binding(root, project, required=False)
        refs = {
            "root_ref": guidance_root_ref,
            "narrative_ref": narrative_ref,
            "guidance_plan_ref": plan_ref,
            "manifest_ref": manifest_ref,
        }
        manifest = _guidance_manifest(
            project_id=project_id,
            plan=plan,
            status="interpreted",
            refs=refs,
            hashes={
                "narrative_sha256": _sha256_bytes(narrative_bytes),
                "guidance_plan_sha256": _sha256_bytes(plan_bytes),
            },
            generated_at=self._now(),
            requested_by=request.requested_by,
            parent=parent,
        )
        _write_json(_safe_project_path(root, manifest_ref), manifest)
        updates: dict[str, Any] = {
            "terrain_route_guidance_id": plan.guidance_id,
            "terrain_route_guidance_status": "interpreted",
            "terrain_route_guidance_root_ref": guidance_root_ref,
            "terrain_route_guidance_narrative_ref": narrative_ref,
            "terrain_route_guidance_narrative_sha256": plan.narrative_sha256,
            "terrain_route_guidance_plan_ref": plan_ref,
            "terrain_route_guidance_plan_sha256": terrain_guidance_plan_sha256(plan),
            "terrain_route_guidance_manifest_ref": manifest_ref,
            "terrain_route_guidance_feature_index_ref": None,
            "terrain_route_guidance_feature_index_sha256": None,
            "terrain_route_guidance_resolution_ref": None,
            "terrain_route_guidance_resolution_sha256": None,
            "terrain_route_guidance_review_ref": None,
            "terrain_route_guidance_review_sha256": None,
            "terrain_route_guidance_guided_execution_ready": False,
            "terrain_route_guidance_candidate_only": True,
            "terrain_route_guidance_runtime_safety_truth": False,
            "terrain_route_guidance_operational": False,
            "terrain_route_guidance_updated_at": self._now().isoformat(),
        }
        if parent is not None:
            updates.update(
                {
                    "terrain_route_guidance_dem_sha256": parent["dem_sha256"],
                    "terrain_route_guidance_parent_manifest_sha256": parent[
                        "parent_manifest_sha256"
                    ],
                }
            )
        _update_project(root, project, updates)
        return {
            "artifact_kind": "terrain_route_guidance_workspace_state",
            "project_id": project_id,
            "status": "interpreted",
            "guidance_plan": plan.model_dump(mode="json"),
            "workspace_refs": refs,
            "manifest": manifest,
            **_candidate_boundary(),
        }

    def resolve(
        self,
        project_root: Path | str,
        *,
        project_id: str,
        request: TerrainGuidanceResolveRequest,
    ) -> dict[str, Any]:
        root, project = _load_project(project_root, project_id=project_id)
        plan, narrative = _load_active_plan(root, project, request.guidance_id)
        parent = _terrain_parent_binding(root, project, required=True)
        expected_dem_sha = project.get("terrain_route_guidance_dem_sha256")
        if isinstance(expected_dem_sha, str) and expected_dem_sha != parent["dem_sha256"]:
            raise ValueError(
                "active DEM hash changed after narrative interpretation; interpret or explicitly rebind guidance again"
            )
        validate_narrative_guidance_plan(plan, narrative)
        search_window = _build_search_window(
            request.route_start,
            request.route_destination,
            margin_m=request.search_margin_m,
        )
        corridor_reference = _load_candidate_corridor_reference(
            root,
            project,
            project_id=project_id,
            parent=parent,
            search_window=search_window,
            hypothesis_id=request.reference_hypothesis_id,
            band_name=request.reference_corridor_band_name,
        )
        if corridor_reference is not None and self._elevation_sampler is None:
            raise ValueError("candidate corridor sampling is unavailable on this host")
        feature_index = _build_feature_index(
            root,
            project,
            plan=plan,
            parent=parent,
            search_window=search_window,
            manual_anchors=request.manual_anchors,
            elevation_sampler=self._elevation_sampler,
            corridor_reference=corridor_reference,
        )
        resolution = resolve_terrain_route_guidance(plan, feature_index)
        guidance_root_ref = str(project["terrain_route_guidance_root_ref"])
        feature_ref = f"{guidance_root_ref}/feature_index.json"
        resolution_ref = f"{guidance_root_ref}/resolution.json"
        feature_bytes = _json_bytes(feature_index.model_dump(mode="json"))
        resolution_bytes = _json_bytes(resolution.model_dump(mode="json"))
        _write_bytes(_safe_project_path(root, feature_ref), feature_bytes)
        _write_bytes(_safe_project_path(root, resolution_ref), resolution_bytes)
        status = (
            "resolved"
            if resolution.status is TerrainGuidanceInterpretationStatus.COMPLETED
            else "partially_resolved"
        )
        updates = {
            "terrain_route_guidance_status": status,
            "terrain_route_guidance_feature_index_ref": feature_ref,
            "terrain_route_guidance_feature_index_sha256": _model_sha256(
                feature_index
            ),
            "terrain_route_guidance_resolution_ref": resolution_ref,
            "terrain_route_guidance_resolution_sha256": terrain_guidance_resolution_sha256(
                resolution
            ),
            "terrain_route_guidance_review_ref": None,
            "terrain_route_guidance_review_sha256": None,
            "terrain_route_guidance_guided_execution_ready": False,
            "terrain_route_guidance_dem_sha256": parent["dem_sha256"],
            "terrain_route_guidance_parent_manifest_sha256": parent[
                "parent_manifest_sha256"
            ],
            "terrain_route_guidance_updated_at": self._now().isoformat(),
        }
        project = _update_project(root, project, updates)
        manifest = _update_guidance_manifest(
            root,
            project,
            status=status,
            refs={
                "feature_index_ref": feature_ref,
                "resolution_ref": resolution_ref,
            },
            hashes={
                "feature_index_sha256": _sha256_bytes(feature_bytes),
                "resolution_sha256": _sha256_bytes(resolution_bytes),
            },
            parent=parent,
            generated_at=self._now(),
            clear_review=True,
        )
        return {
            "artifact_kind": "terrain_route_guidance_workspace_state",
            "project_id": project_id,
            "status": status,
            "guidance_plan": plan.model_dump(mode="json"),
            "feature_index": feature_index.model_dump(mode="json"),
            "resolution": resolution.model_dump(mode="json"),
            "review": None,
            "review_sha256": None,
            "guided_execution_ready": False,
            "workspace_refs": {
                "feature_index_ref": feature_ref,
                "resolution_ref": resolution_ref,
            },
            "manifest": manifest,
            **_candidate_boundary(),
        }

    def review(
        self,
        project_root: Path | str,
        *,
        project_id: str,
        request: TerrainGuidanceReviewRequest,
    ) -> dict[str, Any]:
        root, project = _load_project(project_root, project_id=project_id)
        plan, _ = _load_active_plan(root, project, request.guidance_id)
        resolution = _load_bound_model(
            root,
            project,
            ref_key="terrain_route_guidance_resolution_ref",
            hash_key="terrain_route_guidance_resolution_sha256",
            model_type=TerrainGuidanceResolution,
        )
        feature_index = _load_bound_model(
            root,
            project,
            ref_key="terrain_route_guidance_feature_index_ref",
            hash_key="terrain_route_guidance_feature_index_sha256",
            model_type=TerrainGuidanceFeatureIndex,
        )
        feature_ids = {item.feature_id for item in feature_index.features}
        if any(value not in feature_ids for value in request.selected_feature_ids.values()):
            raise ValueError("review selected a feature outside the bound feature index")
        reviewed_at = request.reviewed_at or self._now()
        review = build_narrative_guidance_review(
            plan,
            resolution,
            selected_feature_ids=request.selected_feature_ids,
            disabled_constraint_ids=request.disabled_constraint_ids,
            reviewed_by=request.reviewed_by,
            reviewed_at=reviewed_at,
            feature_selection_sources={
                item.feature_id: item.selection_source
                for item in feature_index.features
            },
        )
        feature_by_id = {item.feature_id: item for item in feature_index.features}
        selected_features = [
            feature_by_id[item.feature_id] for item in review.selected_anchors
        ]
        explicit_point_anchors = bool(selected_features) and all(
            item.selection_source == "human_map_annotation"
            and isinstance(item.geometry, dict)
            and item.geometry.get("type") == "Point"
            for item in selected_features
        )
        guided_execution_ready = (
            review.review_status is TerrainGuidanceReviewStatus.REVIEWED
            and explicit_point_anchors
        )
        guidance_root_ref = str(project["terrain_route_guidance_root_ref"])
        review_ref = f"{guidance_root_ref}/review.json"
        review_bytes = _json_bytes(review.model_dump(mode="json"))
        _write_bytes(_safe_project_path(root, review_ref), review_bytes)
        review_sha = terrain_guidance_review_sha256(review)
        status = "reviewed" if guided_execution_ready else "partially_reviewed"
        updates = {
            "terrain_route_guidance_status": status,
            "terrain_route_guidance_review_ref": review_ref,
            "terrain_route_guidance_review_sha256": review_sha,
            "terrain_route_guidance_guided_execution_ready": guided_execution_ready,
            "terrain_route_guidance_updated_at": self._now().isoformat(),
        }
        project = _update_project(root, project, updates)
        parent = _terrain_parent_binding(root, project, required=True)
        manifest = _update_guidance_manifest(
            root,
            project,
            status=status,
            refs={"review_ref": review_ref},
            hashes={"review_sha256": _sha256_bytes(review_bytes)},
            parent=parent,
            generated_at=self._now(),
            review={
                "reviewed_by": review.reviewed_by,
                "reviewed_at": review.reviewed_at.isoformat(),
                "selected_anchor_count": len(review.selected_anchors),
                "review_decision_count": len(review.review_decisions),
                "ai_map_selection_performed": False,
                "disabled_constraint_ids": review.disabled_constraint_ids,
                "guided_execution_ready": guided_execution_ready,
            },
        )
        return {
            "artifact_kind": "terrain_route_guidance_workspace_state",
            "project_id": project_id,
            "status": status,
            "review": review.model_dump(mode="json"),
            "review_sha256": review_sha,
            "guided_execution_ready": guided_execution_ready,
            "workspace_refs": {"review_ref": review_ref},
            "manifest": manifest,
            **_candidate_boundary(),
        }

    def inspect(
        self,
        project_root: Path | str,
        *,
        project_id: str,
    ) -> dict[str, Any]:
        root, project = _load_project(project_root, project_id=project_id)
        guidance_id = project.get("terrain_route_guidance_id")
        if not isinstance(guidance_id, str):
            return {
                "artifact_kind": "terrain_route_guidance_workspace_state",
                "project_id": project_id,
                "status": "not_started",
                "guidance_plan": None,
                "feature_index": None,
                "resolution": None,
                "review": None,
                "guided_execution_ready": False,
                **_candidate_boundary(),
            }
        plan, narrative = _load_active_plan(root, project, guidance_id)
        feature_index = _optional_bound_model(
            root,
            project,
            ref_key="terrain_route_guidance_feature_index_ref",
            hash_key="terrain_route_guidance_feature_index_sha256",
            model_type=TerrainGuidanceFeatureIndex,
        )
        resolution = _optional_bound_model(
            root,
            project,
            ref_key="terrain_route_guidance_resolution_ref",
            hash_key="terrain_route_guidance_resolution_sha256",
            model_type=TerrainGuidanceResolution,
        )
        review = _optional_bound_model(
            root,
            project,
            ref_key="terrain_route_guidance_review_ref",
            hash_key="terrain_route_guidance_review_sha256",
            model_type=TerrainNarrativeGuidanceReview,
        )
        return {
            "artifact_kind": "terrain_route_guidance_workspace_state",
            "project_id": project_id,
            "status": str(project.get("terrain_route_guidance_status") or "unknown"),
            "narrative": narrative,
            "guidance_plan": plan.model_dump(mode="json"),
            "feature_index": (
                feature_index.model_dump(mode="json") if feature_index else None
            ),
            "resolution": resolution.model_dump(mode="json") if resolution else None,
            "review": review.model_dump(mode="json") if review else None,
            "review_sha256": (
                str(project.get("terrain_route_guidance_review_sha256"))
                if review is not None
                else None
            ),
            "guided_execution_ready": bool(
                project.get("terrain_route_guidance_guided_execution_ready")
            ),
            "workspace_refs": {
                key: project.get(key)
                for key in (
                    "terrain_route_guidance_root_ref",
                    "terrain_route_guidance_narrative_ref",
                    "terrain_route_guidance_plan_ref",
                    "terrain_route_guidance_feature_index_ref",
                    "terrain_route_guidance_resolution_ref",
                    "terrain_route_guidance_review_ref",
                    "terrain_route_guidance_manifest_ref",
                )
                if project.get(key)
            },
            **_candidate_boundary(),
        }

    def _now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def build_guided_route_cache_binding(
    review: TerrainNarrativeGuidanceReview | dict[str, Any],
    *,
    dem_sha256: str,
) -> dict[str, Any]:
    parsed = (
        review
        if isinstance(review, TerrainNarrativeGuidanceReview)
        else TerrainNarrativeGuidanceReview.model_validate(review)
    )
    review_sha = terrain_guidance_review_sha256(parsed)
    payload = {
        "schema_version": GUIDED_ROUTE_CACHE_VERSION,
        "guided_hypothesis_id": parsed.guided_hypothesis_id,
        "guidance_id": parsed.guidance_id,
        "guidance_review_sha256": review_sha,
        "dem_sha256": dem_sha256,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return {**payload, "cache_binding_sha256": _sha256_json(payload)}


def load_reviewed_guidance_execution_plan(
    project_root: Path | str,
    *,
    project_id: str,
    guidance_id: str,
    review_sha256: str,
) -> TerrainGuidanceExecutionPlan:
    """Compile reviewed map points into the only guidance payload a worker may run."""

    root, project = _load_project(project_root, project_id=project_id)
    if project.get("terrain_route_guidance_id") != guidance_id:
        raise ValueError("requested terrain guidance is not the active workspace plan")
    stored_review_sha = project.get("terrain_route_guidance_review_sha256")
    if stored_review_sha != review_sha256:
        raise ValueError("terrain guidance review hash does not match the active review")
    if project.get("terrain_route_guidance_guided_execution_ready") is not True:
        raise ValueError("terrain guidance has not passed the human review execution gate")

    plan, _ = _load_active_plan(root, project, guidance_id)
    resolution = _load_bound_model(
        root,
        project,
        ref_key="terrain_route_guidance_resolution_ref",
        hash_key="terrain_route_guidance_resolution_sha256",
        model_type=TerrainGuidanceResolution,
    )
    feature_index = _load_bound_model(
        root,
        project,
        ref_key="terrain_route_guidance_feature_index_ref",
        hash_key="terrain_route_guidance_feature_index_sha256",
        model_type=TerrainGuidanceFeatureIndex,
    )
    review = _load_bound_model(
        root,
        project,
        ref_key="terrain_route_guidance_review_ref",
        hash_key="terrain_route_guidance_review_sha256",
        model_type=TerrainNarrativeGuidanceReview,
    )
    if not isinstance(resolution, TerrainGuidanceResolution):
        raise TypeError("terrain guidance resolution type is invalid")
    if not isinstance(feature_index, TerrainGuidanceFeatureIndex):
        raise TypeError("terrain guidance feature index type is invalid")
    if not isinstance(review, TerrainNarrativeGuidanceReview):
        raise TypeError("terrain guidance review type is invalid")
    if (
        review.review_status is not TerrainGuidanceReviewStatus.REVIEWED
        or not review.selected_anchors
        or terrain_guidance_review_sha256(review) != review_sha256
        or review.guidance_id != plan.guidance_id
        or review.plan_sha256 != terrain_guidance_plan_sha256(plan)
        or review.resolution_sha256 != terrain_guidance_resolution_sha256(resolution)
        or resolution.feature_index_sha256 != _model_sha256(feature_index)
    ):
        raise ValueError("terrain guidance review chain is incomplete or hash-invalid")
    parent = _terrain_parent_binding(root, project, required=True)
    if parent is None or (
        parent["dem_sha256"] != feature_index.dem_sha256
        or parent["dem_sha256"] != resolution.dem_sha256
    ):
        raise ValueError("terrain guidance DEM hash changed after review")

    constraint_by_id = {item.constraint_id: item for item in plan.constraints}
    feature_by_id = {item.feature_id: item for item in feature_index.features}
    anchors: list[TerrainGuidanceExecutionAnchor] = []
    for selection in review.selected_anchors:
        constraint = constraint_by_id.get(selection.constraint_id)
        feature = feature_by_id.get(selection.feature_id)
        if constraint is None or feature is None:
            raise ValueError("terrain guidance review references unavailable evidence")
        if (
            feature.selection_source != "human_map_annotation"
            or not isinstance(feature.geometry, dict)
            or feature.geometry.get("type") != "Point"
            or selection.constraint_id not in feature.supported_constraint_ids
        ):
            raise ValueError(
                "guided R4 execution requires an explicit human map point for every selected anchor"
            )
        anchors.append(
            TerrainGuidanceExecutionAnchor(
                constraint_id=constraint.constraint_id,
                sequence_index=constraint.sequence_index,
                kind=constraint.kind,
                landform=constraint.landform or TerrainGuidanceLandform.UNKNOWN,
                routing_effect=constraint.routing_effect,
                required_anchor=constraint.required_anchor,
                feature_id=feature.feature_id,
                point=feature.centroid,
                source_layer=feature.source_layer,
                source_layer_sha256=feature.source_layer_sha256,
            )
        )
    anchors.sort(key=lambda item: item.sequence_index)
    cost_modifiers = [
        _compile_reviewed_cost_modifier(
            constraint_by_id[anchor.constraint_id],
            dem_resolution_m=float(parent["dem_resolution_m"]),
        )
        for anchor in anchors
    ]
    return TerrainGuidanceExecutionPlan(
        guidance_id=guidance_id,
        review_id=review.review_id,
        guidance_review_sha256=review_sha256,
        plan_sha256=review.plan_sha256,
        resolution_sha256=review.resolution_sha256,
        feature_index_sha256=_model_sha256(feature_index),
        dem_sha256=parent["dem_sha256"],
        dem_resolution_m=parent["dem_resolution_m"],
        dem_crs=parent["dem_crs"],
        reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at,
        review_decisions=review.review_decisions,
        anchors=anchors,
        cost_modifiers=cost_modifiers,
        disabled_constraint_ids=review.disabled_constraint_ids,
    )


def _compile_reviewed_cost_modifier(
    constraint: TerrainNarrativeConstraint,
    *,
    dem_resolution_m: float,
) -> TerrainGuidanceCostModifier:
    """Compile one reviewed point constraint into a finite local model preference."""

    if (
        constraint.kind is TerrainGuidanceConstraintKind.EXPECTED_CROSSING
        or constraint.landform is TerrainGuidanceLandform.DRAINAGE
    ):
        modifier_kind = TerrainGuidanceCostModifierKind.DRAINAGE_CROSSING_GATE
        base_radius_m = 80.0
        cell_radius = 4.0
        multiplier = 0.65
    elif constraint.landform is TerrainGuidanceLandform.SADDLE:
        modifier_kind = TerrainGuidanceCostModifierKind.SADDLE_LOCAL_PREFERENCE
        base_radius_m = 100.0
        cell_radius = 5.0
        multiplier = 0.75
    elif constraint.kind is TerrainGuidanceConstraintKind.DIRECTIONAL_TRAVERSE:
        modifier_kind = TerrainGuidanceCostModifierKind.DIRECTIONAL_TRAVERSE_GATE
        base_radius_m = 120.0
        cell_radius = 6.0
        multiplier = 0.85
    elif constraint.kind is TerrainGuidanceConstraintKind.RELATIVE_TO_FEATURE:
        modifier_kind = TerrainGuidanceCostModifierKind.RELATIVE_FEATURE_GATE
        base_radius_m = 100.0
        cell_radius = 5.0
        multiplier = 0.82
    elif constraint.kind is TerrainGuidanceConstraintKind.ELEVATION_BAND:
        modifier_kind = TerrainGuidanceCostModifierKind.ELEVATION_GATE
        base_radius_m = 80.0
        cell_radius = 4.0
        multiplier = 0.85
    elif constraint.landform in {
        TerrainGuidanceLandform.RIDGE,
        TerrainGuidanceLandform.BROAD_RIDGE,
    } or constraint.kind in {
        TerrainGuidanceConstraintKind.FOLLOW_LANDFORM,
        TerrainGuidanceConstraintKind.ASCEND_TO_LANDFORM,
    }:
        modifier_kind = TerrainGuidanceCostModifierKind.RIDGE_LOCAL_PREFERENCE
        base_radius_m = 100.0
        cell_radius = 5.0
        multiplier = 0.78
    else:
        modifier_kind = TerrainGuidanceCostModifierKind.GENERIC_REVIEWED_GATE
        base_radius_m = 80.0
        cell_radius = 4.0
        multiplier = 0.9
    radius_m = min(
        500.0,
        max(20.0, base_radius_m, float(dem_resolution_m) * cell_radius),
    )
    return TerrainGuidanceCostModifier(
        constraint_id=constraint.constraint_id,
        sequence_index=constraint.sequence_index,
        modifier_kind=modifier_kind,
        influence_radius_m=radius_m,
        minimum_friction_multiplier=multiplier,
    )


def _build_search_window(
    route_start: GeoPoint | None,
    route_destination: GeoPoint | None,
    *,
    margin_m: float,
) -> TerrainGuidanceSearchWindow:
    if route_start is None or route_destination is None:
        raise ValueError("route_start and route_destination are required")
    midpoint_latitude = (route_start.y + route_destination.y) / 2.0
    latitude_margin = margin_m / 111_320.0
    longitude_scale = 111_320.0 * max(
        0.01,
        abs(math.cos(math.radians(midpoint_latitude))),
    )
    longitude_margin = margin_m / longitude_scale
    return TerrainGuidanceSearchWindow(
        route_start=route_start,
        route_destination=route_destination,
        margin_m=margin_m,
        west=max(-180.0, min(route_start.x, route_destination.x) - longitude_margin),
        south=max(-90.0, min(route_start.y, route_destination.y) - latitude_margin),
        east=min(180.0, max(route_start.x, route_destination.x) + longitude_margin),
        north=min(90.0, max(route_start.y, route_destination.y) + latitude_margin),
    )


def _point_inside_search_window(
    point: GeoPoint,
    search_window: TerrainGuidanceSearchWindow,
) -> bool:
    return (
        search_window.west <= point.x <= search_window.east
        and search_window.south <= point.y <= search_window.north
    )


def _clip_line_geometry_to_window(
    geometry: Any,
    search_window: TerrainGuidanceSearchWindow,
) -> list[list[list[float]]]:
    if not isinstance(geometry, dict):
        raise ValueError("terrain guidance feature geometry is missing")
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        line_strings = [coordinates]
    elif geometry_type == "MultiLineString":
        line_strings = coordinates
    else:
        raise ValueError("terrain guidance vectors must contain line geometry")
    if not isinstance(line_strings, list):
        raise ValueError("terrain guidance line coordinates are malformed")

    parts: list[list[list[float]]] = []
    for raw_line in line_strings:
        points = _validated_line_points(raw_line)
        parts.extend(_clip_line_string(points, search_window))
    return parts


def _validated_line_points(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("terrain guidance line must contain at least two points")
    points: list[tuple[float, float]] = []
    for raw_point in value:
        if (
            not isinstance(raw_point, list)
            or len(raw_point) < 2
            or not isinstance(raw_point[0], (int, float))
            or not isinstance(raw_point[1], (int, float))
        ):
            raise ValueError("terrain guidance line point is malformed")
        point = (float(raw_point[0]), float(raw_point[1]))
        if (
            not math.isfinite(point[0])
            or not math.isfinite(point[1])
            or not (-180 <= point[0] <= 180)
            or not (-90 <= point[1] <= 90)
        ):
            raise ValueError("terrain guidance vector is not finite EPSG:4326")
        points.append(point)
    return points


def _clip_line_string(
    points: Sequence[tuple[float, float]],
    search_window: TerrainGuidanceSearchWindow,
) -> list[list[list[float]]]:
    parts: list[list[list[float]]] = []
    current: list[list[float]] = []
    for start, destination in zip(points, points[1:]):
        clipped = _clip_line_segment(start, destination, search_window)
        if clipped is None:
            if len(current) >= 2:
                parts.append(current)
            current = []
            continue
        clipped_start = _rounded_coordinate(clipped[0])
        clipped_destination = _rounded_coordinate(clipped[1])
        if not current:
            current = [clipped_start, clipped_destination]
        elif current[-1] == clipped_start:
            if current[-1] != clipped_destination:
                current.append(clipped_destination)
        else:
            if len(current) >= 2:
                parts.append(current)
            current = [clipped_start, clipped_destination]
    if len(current) >= 2:
        parts.append(current)
    return [part for part in parts if len({tuple(point) for point in part}) >= 2]


def _clip_line_segment(
    start: tuple[float, float],
    destination: tuple[float, float],
    search_window: TerrainGuidanceSearchWindow,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    x0, y0 = start
    x1, y1 = destination
    dx = x1 - x0
    dy = y1 - y0
    lower = 0.0
    upper = 1.0
    for coefficient, distance in (
        (-dx, x0 - search_window.west),
        (dx, search_window.east - x0),
        (-dy, y0 - search_window.south),
        (dy, search_window.north - y0),
    ):
        if coefficient == 0:
            if distance < 0:
                return None
            continue
        ratio = distance / coefficient
        if coefficient < 0:
            if ratio > upper:
                return None
            lower = max(lower, ratio)
        else:
            if ratio < lower:
                return None
            upper = min(upper, ratio)
    return (
        (x0 + lower * dx, y0 + lower * dy),
        (x0 + upper * dx, y0 + upper * dy),
    )


def _rounded_coordinate(point: tuple[float, float]) -> list[float]:
    return [round(point[0], 9), round(point[1], 9)]


def _load_candidate_corridor_reference(
    project_root: Path,
    project: dict[str, Any],
    *,
    project_id: str,
    parent: dict[str, Any],
    search_window: TerrainGuidanceSearchWindow,
    hypothesis_id: str | None,
    band_name: str,
) -> _CandidateCorridorReference | None:
    if hypothesis_id is None:
        return None
    catalog_ref = project.get("terrain_route_hypothesis_catalog_ref")
    catalog_sha = project.get("terrain_route_hypothesis_catalog_sha256")
    if not isinstance(catalog_ref, str) or not isinstance(catalog_sha, str):
        raise ValueError("candidate corridor reference requires a bound TRH catalog")
    catalog_path = _safe_project_path(project_root, catalog_ref)
    if _sha256_file(catalog_path) != catalog_sha:
        raise ValueError("terrain route hypothesis catalog hash mismatch")
    catalog = TerrainRouteHypothesisCatalog.model_validate(_read_json(catalog_path))
    if catalog.project_id != project_id:
        raise ValueError("terrain route hypothesis catalog project mismatch")
    entry = next(
        (item for item in catalog.entries if item.id == hypothesis_id),
        None,
    )
    if entry is None:
        raise ValueError("candidate corridor reference hypothesis was not found")

    hypothesis_path = _safe_project_path(project_root, entry.hypothesis_ref)
    if _sha256_file(hypothesis_path) != entry.hypothesis_sha256:
        raise ValueError("candidate corridor hypothesis hash mismatch")
    run = TerrainRouteHypothesisRun.model_validate(_read_json(hypothesis_path))
    if run.status is not TerrainRouteRunStatus.COMPLETED:
        raise ValueError("candidate corridor hypothesis is not completed")
    corridor_hypotheses = [
        item for item in run.hypotheses if item.corridor is not None
    ]
    if len(corridor_hypotheses) != 1:
        raise ValueError("candidate corridor hypothesis must bind exactly one corridor")
    hypothesis = corridor_hypotheses[0]
    if hypothesis.provenance.cache_key != entry.cache_key:
        raise ValueError("candidate corridor cache binding mismatch")
    parent_source_hashes = hypothesis.provenance.processing_manifest.get(
        "parent_source_hashes"
    )
    parent_hash_chain_matches = (
        isinstance(parent_source_hashes, dict)
        and parent_source_hashes.get(parent["dem_ref"]) == parent["dem_sha256"]
        and parent_source_hashes.get(parent["parent_manifest_ref"])
        == parent["parent_manifest_sha256"]
    )
    if (
        hypothesis.provenance.dem_sha256 != parent["dem_sha256"]
        and not parent_hash_chain_matches
    ):
        raise ValueError(
            "candidate corridor DEM parent hash chain differs from active terrain evidence"
        )
    endpoint_tolerance_m = max(30.0, float(parent["dem_resolution_m"]) * 2.0)
    if (
        _wgs84_distance_m(
            (hypothesis.start.x, hypothesis.start.y),
            (search_window.route_start.x, search_window.route_start.y),
        )
        > endpoint_tolerance_m
        or _wgs84_distance_m(
            (hypothesis.destination.x, hypothesis.destination.y),
            (
                search_window.route_destination.x,
                search_window.route_destination.y,
            ),
        )
        > endpoint_tolerance_m
    ):
        raise ValueError("candidate corridor endpoints do not match the guidance A/B")
    band = next(
        (item for item in hypothesis.corridor.bands if item.name == band_name),
        None,
    )
    if band is None or band.raster_ref is None:
        raise ValueError("candidate corridor raster band is unavailable")
    raster = band.raster_ref
    if raster.media_type != "image/tiff":
        raise ValueError("candidate corridor ranking requires the source GeoTIFF mask")
    if raster.crs.strip().upper() != str(parent["dem_crs"]).strip().upper():
        raise ValueError("candidate corridor raster CRS differs from the active DEM")
    bbox = _validated_wgs84_bbox(raster.bbox_wgs84)
    raster_path = _safe_project_path(project_root, raster.artifact_ref)
    if _sha256_file(raster_path) != raster.sha256:
        raise ValueError("candidate corridor raster hash mismatch")
    return _CandidateCorridorReference(
        hypothesis_id=entry.id,
        hypothesis_sha256=entry.hypothesis_sha256,
        cache_key=entry.cache_key,
        band_name=band.name,
        raster_ref=raster.artifact_ref,
        raster_sha256=raster.sha256,
        raster_crs=raster.crs.strip().upper(),
        raster_path=raster_path,
        bbox_wgs84=bbox,
    )


def _validated_wgs84_bbox(value: dict[str, float] | None) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError("candidate corridor raster requires a WGS84 bounding box")
    try:
        bbox = {
            key: float(value[key])
            for key in ("west", "south", "east", "north")
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("candidate corridor raster WGS84 bounds are invalid") from exc
    if (
        any(not math.isfinite(number) for number in bbox.values())
        or bbox["west"] >= bbox["east"]
        or bbox["south"] >= bbox["north"]
        or not -180 <= bbox["west"] <= 180
        or not -180 <= bbox["east"] <= 180
        or not -90 <= bbox["south"] <= 90
        or not -90 <= bbox["north"] <= 90
    ):
        raise ValueError("candidate corridor raster WGS84 bounds are invalid")
    return bbox


def _build_feature_index(
    project_root: Path,
    project: dict[str, Any],
    *,
    plan: TerrainNarrativeGuidancePlan,
    parent: dict[str, Any],
    search_window: TerrainGuidanceSearchWindow,
    manual_anchors: Sequence[TerrainGuidanceManualAnchorRequest],
    elevation_sampler: TerrainGuidanceElevationSampler | None,
    corridor_reference: _CandidateCorridorReference | None,
) -> TerrainGuidanceFeatureIndex:
    features: list[TerrainGuidanceFeatureCandidate] = []
    coordinate_count = 0
    vector_specs = (
        (
            "qgis_ridge_lines_vector_ref",
            TerrainGuidanceLandform.RIDGE,
            "qgis_candidate_ridge_line",
        ),
        (
            "qgis_valley_lines_vector_ref",
            TerrainGuidanceLandform.VALLEY,
            "qgis_candidate_valley_line",
        ),
        (
            "qgis_stream_network_vector_ref",
            TerrainGuidanceLandform.DRAINAGE,
            "qgis_candidate_stream_network",
        ),
    )
    for project_key, landform, expected_kind in vector_specs:
        ref = project.get(project_key)
        if not isinstance(ref, str) or not ref:
            continue
        path = _safe_project_path(project_root, ref)
        payload = _read_json(path)
        source_sha = _sha256_file(path)
        raw_features = payload.get("features") if isinstance(payload, dict) else None
        if payload.get("type") != "FeatureCollection" or not isinstance(raw_features, list):
            raise ValueError(f"terrain guidance vector is malformed: {ref}")
        feature_number = 0
        for index, raw in enumerate(raw_features):
            if not isinstance(raw, dict) or not isinstance(raw.get("properties"), dict):
                raise ValueError(f"terrain guidance vector feature is malformed: {ref}")
            properties = raw["properties"]
            geometry = raw.get("geometry")
            if (
                properties.get("kind") != expected_kind
                or properties.get("candidate_only") is not True
                or properties.get("runtime_safety_truth") is not False
                or properties.get("operational") is not False
            ):
                raise ValueError(f"terrain guidance vector authority is invalid: {ref}")
            clipped_parts = _clip_line_geometry_to_window(geometry, search_window)
            for part_index, part in enumerate(clipped_parts):
                feature_number += 1
                coordinate_count += len(part)
                if (
                    len(features) >= MAX_GUIDANCE_LOCAL_FEATURES
                    or coordinate_count > MAX_GUIDANCE_LOCAL_COORDINATES
                ):
                    raise ValueError(
                        "terrain guidance local candidate budget exceeded; reduce the A/B search margin"
                    )
                clipped_geometry = {"type": "LineString", "coordinates": part}
                centroid = _geometry_centroid(clipped_geometry)
                feature_seed = {
                    "ref": ref,
                    "index": index,
                    "part_index": part_index,
                    "geometry": clipped_geometry,
                    "landform": landform.value,
                    "search_window": search_window.model_dump(mode="json"),
                }
                feature_id = f"{landform.value}-{_sha256_json(feature_seed)[:16]}"
                features.append(
                    TerrainGuidanceFeatureCandidate(
                        feature_id=feature_id,
                        label=f"{landform.value} candidate {feature_number}",
                        landform=landform,
                        centroid=GeoPoint(
                            x=centroid[0],
                            y=centroid[1],
                            crs="EPSG:4326",
                        ),
                        geometry=clipped_geometry,
                        source_layer=ref,
                        source_layer_sha256=source_sha,
                    )
                )
    elevation_sampling_status = "unavailable"
    elevation_sampling_backend: str | None = None
    elevation_sample_count = 0
    elevation_nodata_count = 0
    derived_saddle_count = 0
    if elevation_sampler is not None:
        (
            features,
            derived_saddle_count,
            elevation_sample_count,
            elevation_nodata_count,
        ) = _add_dem_elevation_and_saddle_candidates(
            project_root,
            features,
            parent=parent,
            elevation_sampler=elevation_sampler,
        )
        if elevation_sample_count:
            elevation_sampling_backend = elevation_sampler.backend_id
            elevation_sampling_status = (
                "no_data"
                if elevation_nodata_count == elevation_sample_count
                else "partial" if elevation_nodata_count else "completed"
            )
    reference_corridor: TerrainGuidanceCorridorReference | None = None
    if corridor_reference is not None:
        if elevation_sampler is None:
            raise ValueError("candidate corridor sampling is unavailable on this host")
        features, reference_corridor = _add_candidate_corridor_overlap(
            features,
            reference=corridor_reference,
            sampler=elevation_sampler,
        )
    constraint_by_id = {item.constraint_id: item for item in plan.constraints}
    for anchor in manual_anchors:
        if len(features) >= MAX_GUIDANCE_LOCAL_FEATURES:
            raise ValueError(
                "terrain guidance local candidate budget exceeded; reduce the A/B search margin"
            )
        constraint = constraint_by_id.get(anchor.constraint_id)
        if constraint is None:
            raise ValueError(
                f"manual map anchor references unknown constraint {anchor.constraint_id}"
            )
        if anchor.point.crs != "EPSG:4326":
            raise ValueError("Dashboard manual map anchors must use EPSG:4326")
        if not _point_inside_search_window(anchor.point, search_window):
            raise ValueError("Dashboard manual map anchor must be inside the A/B search window")
        seed = {
            "constraint_id": anchor.constraint_id,
            "point": anchor.point.model_dump(mode="json"),
        }
        source_sha = _sha256_json(seed)
        features.append(
            TerrainGuidanceFeatureCandidate(
                feature_id=f"manual-{anchor.constraint_id.lower()}-{source_sha[:12]}",
                label=anchor.point.label or f"Map anchor {anchor.constraint_id}",
                landform=constraint.landform or TerrainGuidanceLandform.UNKNOWN,
                centroid=anchor.point,
                supported_constraint_ids=(anchor.constraint_id,),
                geometry={
                    "type": "Point",
                    "coordinates": [anchor.point.x, anchor.point.y],
                },
                selection_source="human_map_annotation",
                source_layer="dashboard_human_map_annotations",
                source_layer_sha256=source_sha,
            )
        )
    return TerrainGuidanceFeatureIndex(
        dem_sha256=parent["dem_sha256"],
        dem_resolution_m=parent["dem_resolution_m"],
        crs="EPSG:4326",
        algorithm_version=(
            "qgis_feature_vectors_route_window_plus_dem_elevation_saddles_plus_candidate_corridor_overlap_plus_human_map_annotations.v0_4"
            if corridor_reference is not None
            else
            "qgis_feature_vectors_route_window_plus_dem_elevation_saddles_plus_human_map_annotations.v0_3"
            if elevation_sampler is not None
            else "qgis_feature_vectors_route_window_plus_human_map_annotations.v0_2"
        ),
        elevation_sampling_status=elevation_sampling_status,
        elevation_sampling_backend=elevation_sampling_backend,
        elevation_sample_count=elevation_sample_count,
        elevation_nodata_count=elevation_nodata_count,
        derived_saddle_count=derived_saddle_count,
        reference_corridor=reference_corridor,
        search_window=search_window,
        features=features,
    )


def _add_candidate_corridor_overlap(
    features: Sequence[TerrainGuidanceFeatureCandidate],
    *,
    reference: _CandidateCorridorReference,
    sampler: TerrainGuidanceElevationSampler,
) -> tuple[
    list[TerrainGuidanceFeatureCandidate],
    TerrainGuidanceCorridorReference,
]:
    dem_features = [
        item for item in features if item.selection_source == "dem_derived"
    ]
    if not dem_features:
        raise ValueError("candidate corridor ranking requires DEM-derived features")
    all_points: list[tuple[float, float]] = []
    feature_spans: list[tuple[TerrainGuidanceFeatureCandidate, int, int]] = []
    for feature in dem_features:
        points = _candidate_corridor_sample_points(feature)
        start = len(all_points)
        all_points.extend(points)
        feature_spans.append((feature, start, len(all_points)))
    if len(all_points) > MAX_GUIDANCE_CORRIDOR_SAMPLE_POINTS:
        raise ValueError(
            "candidate corridor sample budget exceeded; reduce the A/B search margin"
        )

    bbox = reference.bbox_wgs84
    sampled_indexes = [
        index
        for index, (longitude, latitude) in enumerate(all_points)
        if bbox["west"] <= longitude <= bbox["east"]
        and bbox["south"] <= latitude <= bbox["north"]
    ]
    sampled_points = tuple(all_points[index] for index in sampled_indexes)
    sampled_values = _validated_dem_samples(
        sampler.sample(reference.raster_path, sampled_points),
        expected_count=len(sampled_points),
    )
    values: list[float | None] = [None] * len(all_points)
    for index, value in zip(sampled_indexes, sampled_values, strict=True):
        values[index] = value

    overlap_by_id: dict[str, TerrainGuidanceCorridorOverlap] = {}
    total_inside = 0
    total_outside = 0
    features_with_overlap = 0
    for feature, start, end in feature_spans:
        inside_count = 0
        outside_count = 0
        for value in values[start:end]:
            if value is None or math.isclose(
                value,
                reference.nodata_value,
                abs_tol=1e-6,
            ):
                outside_count += 1
            elif math.isclose(value, reference.inside_value, abs_tol=1e-6):
                inside_count += 1
            else:
                raise ValueError("candidate corridor mask returned an unexpected value")
        sample_count = end - start
        overlap = TerrainGuidanceCorridorOverlap(
            hypothesis_id=reference.hypothesis_id,
            band_name=reference.band_name,
            sample_count=sample_count,
            inside_sample_count=inside_count,
            outside_or_nodata_sample_count=outside_count,
            overlap_fraction=inside_count / sample_count,
        )
        overlap_by_id[feature.feature_id] = overlap
        total_inside += inside_count
        total_outside += outside_count
        if inside_count:
            features_with_overlap += 1
    enriched = [
        item.model_copy(
            update={"reference_corridor_overlap": overlap_by_id[item.feature_id]}
        )
        if item.feature_id in overlap_by_id
        else item
        for item in features
    ]
    bound_reference = TerrainGuidanceCorridorReference(
        hypothesis_id=reference.hypothesis_id,
        hypothesis_sha256=reference.hypothesis_sha256,
        cache_key=reference.cache_key,
        band_name=reference.band_name,
        raster_ref=reference.raster_ref,
        raster_sha256=reference.raster_sha256,
        raster_crs=reference.raster_crs,
        sampling_backend=sampler.backend_id,
        sample_count=len(all_points),
        inside_sample_count=total_inside,
        outside_or_nodata_sample_count=total_outside,
        feature_count=len(dem_features),
        features_with_overlap=features_with_overlap,
        inside_value=reference.inside_value,
        nodata_value=reference.nodata_value,
    )
    return enriched, bound_reference


def _candidate_corridor_sample_points(
    feature: TerrainGuidanceFeatureCandidate,
) -> tuple[tuple[float, float], ...]:
    geometry = feature.geometry
    if isinstance(geometry, dict) and geometry.get("type") == "LineString":
        points = _validated_line_points(geometry.get("coordinates"))
    else:
        points = [(feature.centroid.x, feature.centroid.y)]
    if len(points) <= MAX_GUIDANCE_CORRIDOR_SAMPLES_PER_FEATURE:
        return tuple(points)
    maximum = MAX_GUIDANCE_CORRIDOR_SAMPLES_PER_FEATURE
    indexes = [
        round(index * (len(points) - 1) / (maximum - 1))
        for index in range(maximum)
    ]
    return tuple(points[index] for index in dict.fromkeys(indexes))


def _add_dem_elevation_and_saddle_candidates(
    project_root: Path,
    features: Sequence[TerrainGuidanceFeatureCandidate],
    *,
    parent: dict[str, Any],
    elevation_sampler: TerrainGuidanceElevationSampler,
) -> tuple[list[TerrainGuidanceFeatureCandidate], int, int, int]:
    """Attach DEM samples and derive ridge-local-minimum saddle proxies."""

    dem_path = _safe_project_path(project_root, str(parent["dem_ref"]))
    line_features = [
        item
        for item in features
        if item.selection_source == "dem_derived"
        and isinstance(item.geometry, dict)
        and item.geometry.get("type") == "LineString"
    ]
    centroid_points = tuple(
        (item.centroid.x, item.centroid.y) for item in line_features
    )
    centroid_values = _validated_dem_samples(
        elevation_sampler.sample(dem_path, centroid_points),
        expected_count=len(centroid_points),
    )
    elevation_by_id = {
        item.feature_id: value for item, value in zip(line_features, centroid_values)
    }
    enriched = [
        item.model_copy(update={"elevation_m": elevation_by_id[item.feature_id]})
        if item.feature_id in elevation_by_id
        else item
        for item in features
    ]

    ridge_features = [
        item for item in enriched if item.landform is TerrainGuidanceLandform.RIDGE
    ]
    ridge_points: list[tuple[float, float]] = []
    ridge_spans: list[tuple[TerrainGuidanceFeatureCandidate, int, int]] = []
    for feature in ridge_features:
        coordinates = _validated_line_points(feature.geometry["coordinates"])
        start = len(ridge_points)
        ridge_points.extend(coordinates)
        ridge_spans.append((feature, start, len(ridge_points)))
    ridge_values = _validated_dem_samples(
        elevation_sampler.sample(dem_path, tuple(ridge_points)),
        expected_count=len(ridge_points),
    )

    saddle_candidates: list[TerrainGuidanceFeatureCandidate] = []
    minimum_separation_m = max(40.0, float(parent["dem_resolution_m"]) * 3.0)
    for ridge, start, end in ridge_spans:
        values = ridge_values[start:end]
        points = ridge_points[start:end]
        radius = 2 if len(points) >= 5 else 1
        for index in _local_minimum_indices(values, radius=radius):
            point = points[index]
            elevation_m = values[index]
            if elevation_m is None:
                continue
            duplicate_index = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(saddle_candidates)
                    if _wgs84_distance_m(
                        (candidate.centroid.x, candidate.centroid.y),
                        point,
                    )
                    <= minimum_separation_m
                ),
                None,
            )
            if duplicate_index is not None:
                if (
                    saddle_candidates[duplicate_index].elevation_m is not None
                    and saddle_candidates[duplicate_index].elevation_m <= elevation_m
                ):
                    continue
                saddle_candidates.pop(duplicate_index)
            seed = {
                "algorithm_version": TERRAIN_GUIDANCE_DEM_DERIVATION_VERSION,
                "dem_sha256": parent["dem_sha256"],
                "ridge_feature_id": ridge.feature_id,
                "ridge_source_sha256": ridge.source_layer_sha256,
                "point": [round(point[0], 9), round(point[1], 9)],
                "elevation_m": round(elevation_m, 6),
            }
            evidence_sha = _sha256_json(seed)
            saddle_candidates.append(
                TerrainGuidanceFeatureCandidate(
                    feature_id=f"saddle-{evidence_sha[:16]}",
                    label=f"DEM ridge-local-minimum candidate · {elevation_m:.0f}m",
                    landform=TerrainGuidanceLandform.SADDLE,
                    centroid=GeoPoint(
                        x=point[0],
                        y=point[1],
                        crs="EPSG:4326",
                    ),
                    elevation_m=elevation_m,
                    relations=("ridge_local_minimum_proxy",),
                    geometry={
                        "type": "Point",
                        "coordinates": [point[0], point[1]],
                    },
                    source_layer=(
                        f"{ridge.source_layer}#dem-ridge-local-minimum-proxy"
                    ),
                    source_layer_sha256=evidence_sha,
                )
            )
    if len(enriched) + len(saddle_candidates) > MAX_GUIDANCE_LOCAL_FEATURES:
        raise ValueError(
            "terrain guidance local candidate budget exceeded; reduce the A/B search margin"
        )
    saddle_candidates.sort(key=lambda item: item.feature_id)
    sample_count = len(centroid_values) + len(ridge_values)
    nodata_count = sum(value is None for value in centroid_values) + sum(
        value is None for value in ridge_values
    )
    return (
        [*enriched, *saddle_candidates],
        len(saddle_candidates),
        sample_count,
        nodata_count,
    )


def _validated_dem_samples(
    values: Sequence[float | None],
    *,
    expected_count: int,
) -> tuple[float | None, ...]:
    if len(values) != expected_count:
        raise ValueError("terrain guidance DEM sampler returned an incomplete result")
    normalized: list[float | None] = []
    for value in values:
        if value is None:
            normalized.append(None)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("terrain guidance DEM sampler returned invalid data") from exc
        normalized.append(number if math.isfinite(number) else None)
    return tuple(normalized)


def _local_minimum_indices(
    values: Sequence[float | None],
    *,
    radius: int,
) -> list[int]:
    if radius < 1:
        raise ValueError("terrain guidance local-minimum radius must be positive")
    matches: list[int] = []
    for index in range(radius, len(values) - radius):
        value = values[index]
        neighbors = [
            *values[index - radius : index],
            *values[index + 1 : index + radius + 1],
        ]
        if value is None or any(item is None for item in neighbors):
            continue
        if value <= min(float(item) for item in neighbors if item is not None):
            matches.append(index)
    return matches


def _wgs84_distance_m(
    start: tuple[float, float],
    destination: tuple[float, float],
) -> float:
    mean_latitude = math.radians((start[1] + destination[1]) / 2.0)
    x_m = (destination[0] - start[0]) * 111_320.0 * math.cos(mean_latitude)
    y_m = (destination[1] - start[1]) * 111_320.0
    return math.hypot(x_m, y_m)


def _terrain_parent_binding(
    project_root: Path,
    project: dict[str, Any],
    *,
    required: bool,
) -> dict[str, Any] | None:
    manifest_ref = project.get("terrain_feature_manifest_ref")
    dem_ref = project.get("terrain_dem_route_bbox_raster_ref")
    if not isinstance(manifest_ref, str) or not isinstance(dem_ref, str):
        if required:
            raise ValueError("terrain guidance requires an active terrain feature DEM manifest")
        return None
    manifest_path = _safe_project_path(project_root, manifest_ref)
    dem_path = _safe_project_path(project_root, dem_ref)
    manifest = _read_json(manifest_path)
    source_resolution = manifest.get("source_resolution")
    artifacts = manifest.get("artifacts")
    if (
        manifest.get("candidate_only") is not True
        or manifest.get("runtime_safety_truth") is not False
        or manifest.get("operational") is not False
        or manifest.get("fixture") is True
        or manifest.get("synthetic") is True
        or not isinstance(source_resolution, dict)
        or not isinstance(artifacts, dict)
        or artifacts.get("dem_route_bbox") != dem_path.name
    ):
        raise ValueError("terrain guidance parent manifest authority or DEM binding is invalid")
    try:
        x_m = float(source_resolution["x_m"])
        y_m = float(source_resolution["y_m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("terrain guidance DEM resolution is unavailable") from exc
    if (
        source_resolution.get("status") != "reported"
        or source_resolution.get("adds_source_resolution") is not False
        or x_m <= 0
        or y_m <= 0
        or abs(x_m - y_m) > 1e-9
    ):
        raise ValueError("terrain guidance DEM resolution is invalid")
    if not dem_path.is_file():
        raise ValueError("terrain guidance DEM file is unavailable")
    return {
        "parent_manifest_ref": manifest_ref,
        "parent_manifest_sha256": _sha256_file(manifest_path),
        "dem_ref": dem_ref,
        "dem_sha256": _sha256_file(dem_path),
        "dem_resolution_m": x_m,
        "dem_crs": str(source_resolution.get("crs") or "UNKNOWN"),
    }


def _load_active_plan(
    project_root: Path,
    project: dict[str, Any],
    guidance_id: str,
) -> tuple[TerrainNarrativeGuidancePlan, str]:
    if project.get("terrain_route_guidance_id") != guidance_id:
        raise ValueError("requested terrain guidance is not the active workspace plan")
    plan = _load_bound_model(
        project_root,
        project,
        ref_key="terrain_route_guidance_plan_ref",
        hash_key="terrain_route_guidance_plan_sha256",
        model_type=TerrainNarrativeGuidancePlan,
    )
    narrative_ref = project.get("terrain_route_guidance_narrative_ref")
    expected_hash = project.get("terrain_route_guidance_narrative_sha256")
    if not isinstance(narrative_ref, str) or not isinstance(expected_hash, str):
        raise ValueError("terrain guidance narrative binding is unavailable")
    narrative_path = _safe_project_path(project_root, narrative_ref)
    narrative = narrative_path.read_text(encoding="utf-8")
    if _sha256_text(narrative) != expected_hash:
        raise ValueError("terrain guidance narrative hash mismatch")
    validate_narrative_guidance_plan(plan, narrative)
    return plan, narrative


def _load_bound_model(
    project_root: Path,
    project: dict[str, Any],
    *,
    ref_key: str,
    hash_key: str,
    model_type: type[BaseModel],
) -> BaseModel:
    ref = project.get(ref_key)
    expected_hash = project.get(hash_key)
    if not isinstance(ref, str) or not isinstance(expected_hash, str):
        raise ValueError(f"workspace artifact binding is unavailable: {ref_key}")
    path = _safe_project_path(project_root, ref)
    payload = _read_json(path)
    model = model_type.model_validate(payload)
    actual_hash = _model_sha256(model)
    if actual_hash != expected_hash:
        raise ValueError(f"workspace artifact hash mismatch: {ref_key}")
    return model


def _optional_bound_model(
    project_root: Path,
    project: dict[str, Any],
    *,
    ref_key: str,
    hash_key: str,
    model_type: type[BaseModel],
) -> BaseModel | None:
    if not project.get(ref_key) and not project.get(hash_key):
        return None
    return _load_bound_model(
        project_root,
        project,
        ref_key=ref_key,
        hash_key=hash_key,
        model_type=model_type,
    )


def _guidance_manifest(
    *,
    project_id: str,
    plan: TerrainNarrativeGuidancePlan,
    status: str,
    refs: dict[str, Any],
    hashes: dict[str, Any],
    generated_at: datetime,
    requested_by: str,
    parent: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "artifact_kind": "terrain_route_guidance_processing_manifest",
        "schema_version": GUIDANCE_MANIFEST_VERSION,
        "project_id": project_id,
        "guidance_id": plan.guidance_id,
        "status": status,
        "generated_at": generated_at.isoformat(),
        "requested_by": requested_by,
        "source": {
            "source_id": plan.source_id,
            "source_type": plan.source_type.value,
            "source_date": plan.source_date,
            "narrative_sha256": plan.narrative_sha256,
        },
        "interpreter": {
            "parser_version": plan.parser_version,
            "model_provider": plan.model_provider,
            "model_name": plan.model_name,
            "prompt_version": plan.prompt_version,
        },
        "refs": refs,
        "hashes": hashes,
        "terrain_parent": parent,
        "review": None,
        "history": [
            {
                "status": status,
                "at": generated_at.isoformat(),
            }
        ],
        "boundary": _candidate_boundary(),
    }


def _update_guidance_manifest(
    project_root: Path,
    project: dict[str, Any],
    *,
    status: str,
    refs: dict[str, Any],
    hashes: dict[str, Any],
    parent: dict[str, Any],
    generated_at: datetime,
    review: dict[str, Any] | None = None,
    clear_review: bool = False,
) -> dict[str, Any]:
    manifest_ref = project.get("terrain_route_guidance_manifest_ref")
    if not isinstance(manifest_ref, str):
        raise ValueError("terrain guidance manifest ref is unavailable")
    path = _safe_project_path(project_root, manifest_ref)
    manifest = _read_json(path)
    if (
        manifest.get("boundary", {}).get("candidate_only") is not True
        or manifest.get("boundary", {}).get("runtime_safety_truth") is not False
    ):
        raise ValueError("terrain guidance manifest authority is invalid")
    history = list(manifest.get("history") or [])
    history.append({"status": status, "at": generated_at.isoformat()})
    updated = {
        **manifest,
        "status": status,
        "updated_at": generated_at.isoformat(),
        "refs": {**dict(manifest.get("refs") or {}), **refs},
        "hashes": {**dict(manifest.get("hashes") or {}), **hashes},
        "terrain_parent": parent,
        "review": (
            None
            if clear_review
            else review if review is not None else manifest.get("review")
        ),
        "history": history,
    }
    _write_json(path, updated)
    return updated


def _load_project(
    project_root: Path | str,
    *,
    project_id: str,
) -> tuple[Path, dict[str, Any]]:
    root = Path(project_root).expanduser().resolve()
    path = root / "project.json"
    project = _read_json(path)
    if not isinstance(project, dict):
        raise ValueError("project.json must contain an object")
    if project.get("project_id") != project_id:
        raise ValueError("terrain guidance project_id mismatch")
    return root, project


def _update_project(
    project_root: Path,
    project: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    updated = {**project, **updates}
    _write_json(project_root / "project.json", updated)
    return updated


def _safe_project_path(project_root: Path, ref: str) -> Path:
    if not ref or Path(ref).is_absolute():
        raise ValueError("terrain guidance workspace ref must be project-relative")
    root = project_root.resolve()
    path = (root / ref).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("terrain guidance workspace ref escapes project root") from exc
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"workspace JSON is unavailable or invalid: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"workspace JSON must contain an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_bytes(path, _json_bytes(payload))


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _geometry_centroid(geometry: Any) -> tuple[float, float]:
    if not isinstance(geometry, dict):
        raise ValueError("terrain guidance feature geometry is missing")
    coordinates = geometry.get("coordinates")
    points = _flatten_points(coordinates)
    if not points:
        raise ValueError("terrain guidance feature geometry has no coordinates")
    x = sum(point[0] for point in points) / len(points)
    y = sum(point[1] for point in points) / len(points)
    if not (-180 <= x <= 180 and -90 <= y <= 90):
        raise ValueError("terrain guidance vector is not EPSG:4326 GeoJSON")
    return x, y


def _flatten_points(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        return [(float(value[0]), float(value[1]))]
    points: list[tuple[float, float]] = []
    for item in value:
        points.extend(_flatten_points(item))
    return points


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
        "promotion_allowed": False,
        "writes_to_official_trail_db": False,
        "writes_to_safety_truth": False,
    }


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _model_sha256(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(payload)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_json_bytes(value))


__all__ = [
    "GUIDANCE_MANIFEST_VERSION",
    "GUIDANCE_WORKSPACE_ROOT_REF",
    "GUIDED_ROUTE_CACHE_VERSION",
    "TerrainGuidanceInterpretRequest",
    "TerrainGuidanceManualAnchorRequest",
    "TerrainGuidanceResolveRequest",
    "TerrainGuidanceReviewRequest",
    "TerrainRouteGuidanceWorkspaceService",
    "build_guided_route_cache_binding",
    "load_reviewed_guidance_execution_plan",
]
