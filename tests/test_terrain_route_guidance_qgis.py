from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from qgis_spatial_contracts import SpatialAnalysisRequest
from qgis_worker_contracts import QgisWorkerWorkflowRequest
from terrain_route_guidance import (
    TerrainGuidanceCostModifier,
    TerrainGuidanceCostModifierKind,
    TerrainGuidanceExecutionAnchor,
    TerrainGuidanceExecutionPlan,
    TerrainGuidanceConstraintKind,
    TerrainGuidanceLandform,
    TerrainGuidanceResolutionStatus,
    TerrainGuidanceReviewDecision,
    TerrainGuidanceReviewDecisionKind,
    TerrainGuidanceRoutingEffect,
)
from terrain_route_hypothesis_artifacts import build_live_terrain_route_cache_keys
from terrain_route_hypothesis_models import GeoPoint, TerrainRoutingCostConfig


def _execution_plan() -> TerrainGuidanceExecutionPlan:
    return TerrainGuidanceExecutionPlan(
        guidance_id="terrain-guidance-demo",
        review_id="terrain-guidance-review-demo",
        guidance_review_sha256="a" * 64,
        plan_sha256="b" * 64,
        resolution_sha256="c" * 64,
        feature_index_sha256="d" * 64,
        dem_sha256="e" * 64,
        dem_resolution_m=20,
        dem_crs="EPSG:3826",
        reviewed_by="trip_leader",
        reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        review_decisions=[
            TerrainGuidanceReviewDecision(
                constraint_id="G1",
                sequence_index=0,
                resolver_status_before_review=TerrainGuidanceResolutionStatus.RESOLVED,
                resolver_candidate_feature_ids=["manual-g1"],
                human_selected_feature_id="manual-g1",
                selected_feature_source="human_map_annotation",
                decision_kind=(
                    TerrainGuidanceReviewDecisionKind.HUMAN_MAP_ANCHOR_CONFIRMED
                ),
                differs_from_ai_map_selection=True,
            )
        ],
        anchors=[
            TerrainGuidanceExecutionAnchor(
                constraint_id="G1",
                sequence_index=0,
                kind=TerrainGuidanceConstraintKind.FOLLOW_LANDFORM,
                landform=TerrainGuidanceLandform.RIDGE,
                routing_effect=TerrainGuidanceRoutingEffect.ORDERED_GATE,
                required_anchor=True,
                feature_id="manual-g1",
                point=GeoPoint(x=121.215, y=24.045, crs="EPSG:4326"),
                source_layer="dashboard_human_map_annotations",
                source_layer_sha256="f" * 64,
            )
        ],
        cost_modifiers=[
            TerrainGuidanceCostModifier(
                constraint_id="G1",
                sequence_index=0,
                modifier_kind=TerrainGuidanceCostModifierKind.RIDGE_LOCAL_PREFERENCE,
                influence_radius_m=100,
                minimum_friction_multiplier=0.78,
            )
        ],
    )


def test_guidance_selection_is_only_valid_for_candidate_terrain_route() -> None:
    selection = {
        "guidance_id": "terrain-guidance-demo",
        "guided_hypothesis_id": "R4",
        "review_sha256": "a" * 64,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
    }
    request = SpatialAnalysisRequest(
        workflow_id="terrain_route_hypothesis.v1",
        terrain_route_endpoints={
            "start": {"x": 121.21, "y": 24.05, "crs": "EPSG:4326"},
            "destination": {"x": 121.22, "y": 24.04, "crs": "EPSG:4326"},
        },
        terrain_route_guidance=selection,
    )
    assert request.terrain_route_guidance is not None
    assert request.terrain_route_guidance.guided_hypothesis_id == "R4"

    with pytest.raises(ValidationError, match="terrain_route_guidance"):
        SpatialAnalysisRequest(
            workflow_id="terrain_context_preview.v1",
            terrain_route_guidance=selection,
        )


def test_worker_request_binds_ordered_anchor_coordinates_and_authority() -> None:
    plan = _execution_plan()
    payload = {
        "workflow_id": "terrain_route_hypothesis.v1",
        "project_id": "guidance_demo",
        "request_id": "request-guided-demo",
        "requested_by": "dashboard_operator",
        "route_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [121.21, 24.05],
                            [121.215, 24.045],
                            [121.22, 24.04],
                        ],
                    },
                }
            ],
        },
        "dem_refs": ["/tmp/dem.tif"],
        "source_hashes": {"dem.tif": "e" * 64},
        "terrain_route_guidance_execution_plan": plan.model_dump(mode="json"),
    }
    request = QgisWorkerWorkflowRequest.model_validate(payload)
    assert request.terrain_route_guidance_execution_plan == plan
    assert request.candidate_only is True
    assert request.runtime_safety_truth is False

    payload["route_geojson"]["features"][0]["geometry"]["coordinates"] = [
        [121.21, 24.05],
        [121.22, 24.04],
    ]
    with pytest.raises(ValidationError, match="ordered guidance anchors"):
        QgisWorkerWorkflowRequest.model_validate(payload)


def test_execution_plan_rejects_cost_modifier_that_does_not_match_anchor() -> None:
    payload = _execution_plan().model_dump(mode="json")
    payload["cost_modifiers"][0]["constraint_id"] = "G2"

    with pytest.raises(ValidationError, match="cost modifiers must match"):
        TerrainGuidanceExecutionPlan.model_validate(payload)

    payload = _execution_plan().model_dump(mode="json")
    payload["review_decisions"][0]["human_selected_feature_id"] = "manual-g2"
    payload["review_decisions"][0]["resolver_candidate_feature_ids"] = ["manual-g2"]
    with pytest.raises(ValidationError, match="review decisions must match"):
        TerrainGuidanceExecutionPlan.model_validate(payload)


def test_guidance_review_hash_invalidates_only_guided_cost_and_route_cache() -> None:
    common = {
        "source_hashes": {"dem.tif": "e" * 64},
        "source_resolution": {"x_m": 20, "y_m": 20, "crs": "EPSG:3826"},
        "route_coordinates": [[121.21, 24.05], [121.22, 24.04]],
        "analysis_margin_m": 250,
        "cost_config": TerrainRoutingCostConfig(),
    }
    first = build_live_terrain_route_cache_keys(
        **common,
        guidance_review_sha256="a" * 64,
    )
    second = build_live_terrain_route_cache_keys(
        **common,
        guidance_review_sha256="b" * 64,
    )
    assert first.derived_terrain == second.derived_terrain
    assert first.friction == second.friction
    assert first.cost_raster != second.cost_raster
    assert first.route_hypothesis != second.route_hypothesis
