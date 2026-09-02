from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from terrain_route_guidance import (
    TerrainGuidanceCorridorOverlap,
    TerrainGuidanceCorridorReference,
    TerrainGuidanceConstraintKind,
    TerrainGuidanceDirection,
    TerrainGuidanceFeatureCandidate,
    TerrainGuidanceFeatureIndex,
    TerrainGuidanceInterpretationStatus,
    TerrainGuidanceLandform,
    TerrainGuidanceMeasurementSemantics,
    TerrainGuidanceResolutionStatus,
    TerrainGuidanceReviewDecisionKind,
    TerrainGuidanceSearchWindow,
    build_narrative_guidance_review,
    interpret_terrain_route_narrative,
    resolve_terrain_route_guidance,
    validate_narrative_guidance_plan,
)
from terrain_route_hypothesis_models import GeoPoint


NARRATIVE = (
    "大致的定位策略是，於1148鞍沿著稜線走至其開始轉為上坡後，往西邊的坡切，"
    "沿遇到的第一個溝東側的稜線續行，在寬闊的稜線上抓方向往北走，偶爾看到黃布條，"
    "植被是及腰的草本植物，路徑濕滑。1140 H820m轉稜，至溪底前路徑清楚布條多，"
    "只是較陡和濕滑。1158 下至溪底，過溪有大石頭可踩著通過。1223 續行，"
    "沿著小溪溝上大概15m之後，想辦法找路往西腰繞，這段沒有跟到黃布條，"
    "繼續沿著獵徑之字繞上稜，並繞過稜上巨石。1247 抵達異祿閣稜線，稜線寬緩好走。"
)


def _feature(
    feature_id: str,
    *,
    landform: TerrainGuidanceLandform,
    x: float,
    y: float,
    elevation_m: float | None = None,
    direction: TerrainGuidanceDirection | None = None,
    relations: tuple[str, ...] = (),
) -> TerrainGuidanceFeatureCandidate:
    return TerrainGuidanceFeatureCandidate(
        feature_id=feature_id,
        label=feature_id,
        landform=landform,
        centroid=GeoPoint(x=x, y=y, crs="EPSG:3826"),
        elevation_m=elevation_m,
        direction=direction,
        relations=relations,
        source_layer="synthetic_terrain_features",
        source_layer_sha256="a" * 64,
    )


def test_historical_narrative_becomes_typed_candidate_only_constraints() -> None:
    plan = interpret_terrain_route_narrative(
        NARRATIVE,
        source_id="iroko-trip-record-d3",
        source_date="2017-01-01",
    )

    assert plan.status is TerrainGuidanceInterpretationStatus.PARTIALLY_RESOLVED
    assert plan.authority.value == "candidate_only"
    assert plan.candidate_only is True
    assert plan.runtime_safety_truth is False
    assert plan.review_required is True
    assert plan.source_type.value == "historical_route"
    assert plan.narrative_sha256
    assert [item.constraint_id for item in plan.constraints] == [
        f"G{index}" for index in range(1, len(plan.constraints) + 1)
    ]

    kinds = {item.kind for item in plan.constraints}
    assert {
        TerrainGuidanceConstraintKind.ORDERED_ANCHOR,
        TerrainGuidanceConstraintKind.FOLLOW_LANDFORM,
        TerrainGuidanceConstraintKind.DIRECTIONAL_TRAVERSE,
        TerrainGuidanceConstraintKind.RELATIVE_TO_FEATURE,
        TerrainGuidanceConstraintKind.EXPECTED_CROSSING,
        TerrainGuidanceConstraintKind.ASCEND_TO_LANDFORM,
    } <= kinds
    assert any(
        item.landform is TerrainGuidanceLandform.BROAD_RIDGE
        and item.direction is TerrainGuidanceDirection.NORTH
        for item in plan.constraints
    )
    assert any(
        item.approximate_value_m == 15
        and item.measurement_semantics
        is TerrainGuidanceMeasurementSemantics.UNKNOWN
        for item in plan.constraints
    )
    assert {item.code for item in plan.unknowns} >= {
        "1148_semantics_unknown",
        "15m_measurement_semantics_unknown",
        "trail_observation_not_dem_authority",
    }
    assert {item.code for item in plan.context_observations} >= {
        "marker_observation",
        "vegetation_observation",
        "wet_surface_observation",
        "hunting_path_observation",
    }
    assert all(
        NARRATIVE[item.source_span.start : item.source_span.end]
        == item.source_span.text
        for item in plan.constraints
    )
    assert all(item.boundary.promotion_allowed is False for item in plan.constraints)


def test_parser_is_deterministic_and_rejects_authority_promotion() -> None:
    first = interpret_terrain_route_narrative(
        NARRATIVE,
        source_id="iroko-trip-record-d3",
    )
    second = interpret_terrain_route_narrative(
        NARRATIVE,
        source_id="iroko-trip-record-d3",
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    payload = first.model_dump(mode="json")
    with pytest.raises(ValidationError):
        type(first).model_validate({**payload, "candidate_only": False})
    with pytest.raises(ValidationError):
        type(first).model_validate({**payload, "source_type": "official_trail"})


def test_source_spans_and_hash_are_validated_fail_closed() -> None:
    plan = interpret_terrain_route_narrative(NARRATIVE, source_id="trip-record")

    validate_narrative_guidance_plan(plan, NARRATIVE)

    with pytest.raises(ValueError, match="narrative hash"):
        validate_narrative_guidance_plan(plan, NARRATIVE + " altered")

    payload = plan.model_dump(mode="json")
    payload["constraints"][0]["source_span"]["text"] = "invented"
    corrupted = type(plan).model_validate(payload)
    with pytest.raises(ValueError, match="source span"):
        validate_narrative_guidance_plan(corrupted, NARRATIVE)


def test_deterministic_feature_resolver_preserves_multiple_and_unresolved_candidates() -> None:
    plan = interpret_terrain_route_narrative(NARRATIVE, source_id="trip-record")
    index = TerrainGuidanceFeatureIndex(
        dem_sha256="d" * 64,
        dem_resolution_m=20,
        crs="EPSG:3826",
        algorithm_version="synthetic_features.v1",
        features=[
            _feature(
                "saddle-1142-west",
                landform=TerrainGuidanceLandform.SADDLE,
                x=273000,
                y=2584000,
                elevation_m=1142,
            ),
            _feature(
                "saddle-1155-east",
                landform=TerrainGuidanceLandform.SADDLE,
                x=273080,
                y=2583980,
                elevation_m=1155,
            ),
            _feature(
                "broad-ridge-north",
                landform=TerrainGuidanceLandform.BROAD_RIDGE,
                x=273100,
                y=2583800,
                direction=TerrainGuidanceDirection.NORTH,
            ),
            _feature(
                "ridge-east-of-drainage",
                landform=TerrainGuidanceLandform.RIDGE,
                x=273070,
                y=2583900,
                relations=("east_of_drainage",),
            ),
            _feature(
                "creek-crossing-1",
                landform=TerrainGuidanceLandform.DRAINAGE,
                x=273200,
                y=2583500,
            ),
        ],
    )

    resolution = resolve_terrain_route_guidance(plan, index)

    assert resolution.status is TerrainGuidanceInterpretationStatus.PARTIALLY_RESOLVED
    assert resolution.candidate_only is True
    assert resolution.runtime_safety_truth is False
    saddle = next(
        item
        for item in resolution.constraints
        if item.constraint_id == plan.constraints[0].constraint_id
    )
    assert saddle.status is TerrainGuidanceResolutionStatus.MULTIPLE_CANDIDATES
    assert saddle.candidate_feature_ids == [
        "saddle-1142-west",
        "saddle-1155-east",
    ]
    assert saddle.selected_feature_id is None
    assert resolution.human_confirmation_required is True
    assert resolution.unresolved_constraint_ids


def test_review_requires_explicit_anchor_selection_and_never_promotes_route_truth() -> None:
    plan = interpret_terrain_route_narrative(NARRATIVE, source_id="trip-record")
    index = TerrainGuidanceFeatureIndex(
        dem_sha256="d" * 64,
        dem_resolution_m=20,
        crs="EPSG:3826",
        algorithm_version="synthetic_features.v1",
        features=[
            _feature(
                "saddle-1142-west",
                landform=TerrainGuidanceLandform.SADDLE,
                x=273000,
                y=2584000,
                elevation_m=1142,
            ),
        ],
    )
    resolution = resolve_terrain_route_guidance(plan, index)

    with pytest.raises(ValueError, match="required anchor"):
        build_narrative_guidance_review(
            plan,
            resolution,
            selected_feature_ids={},
            reviewed_by="human-reviewer",
            reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )

    required = [
        item
        for item in resolution.constraints
        if item.required_anchor and item.candidate_feature_ids
    ]
    selections = {
        item.constraint_id: item.candidate_feature_ids[0]
        for item in required
    }
    review = build_narrative_guidance_review(
        plan,
        resolution,
        selected_feature_ids=selections,
        disabled_constraint_ids=resolution.unresolved_constraint_ids,
        reviewed_by="human-reviewer",
        reviewed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    assert review.reviewed is True
    assert review.candidate_only is True
    assert review.runtime_safety_truth is False
    assert review.boundary.writes_to_official_trail_db is False
    assert review.boundary.writes_to_safety_truth is False
    assert review.guided_hypothesis_id == "R4"
    selected_decisions = [
        item for item in review.review_decisions if item.human_selected_feature_id
    ]
    assert selected_decisions
    assert all(item.ai_selected_feature_id is None for item in selected_decisions)
    assert all(
        item.decision_kind
        is TerrainGuidanceReviewDecisionKind.HUMAN_SELECTED_CANDIDATE
        for item in selected_decisions
    )
    assert all(item.selection_authority == "human_map_review" for item in selected_decisions)


def test_candidates_without_elevation_are_ranked_by_narrative_sequence_proximity() -> None:
    plan = interpret_terrain_route_narrative(NARRATIVE, source_id="trip-record")
    expected_crossing = next(
        item
        for item in plan.constraints
        if item.kind is TerrainGuidanceConstraintKind.EXPECTED_CROSSING
    )
    start = GeoPoint(x=121.20, y=23.46, crs="EPSG:4326", label="A")
    destination = GeoPoint(x=121.22, y=23.48, crs="EPSG:4326", label="B")
    progress = expected_crossing.sequence_index / (len(plan.constraints) - 1)
    expected_x = start.x + (destination.x - start.x) * progress
    expected_y = start.y + (destination.y - start.y) * progress
    index = TerrainGuidanceFeatureIndex(
        dem_sha256="d" * 64,
        dem_resolution_m=20,
        crs="EPSG:4326",
        algorithm_version="synthetic_sequence_rank.v1",
        search_window=TerrainGuidanceSearchWindow(
            route_start=start,
            route_destination=destination,
            margin_m=1000,
            west=121.19,
            south=23.45,
            east=121.23,
            north=23.49,
        ),
        features=[
            TerrainGuidanceFeatureCandidate(
                feature_id="a-far-drainage",
                label="far drainage",
                landform=TerrainGuidanceLandform.DRAINAGE,
                centroid=GeoPoint(x=121.219, y=23.479, crs="EPSG:4326"),
                source_layer="synthetic_terrain_features",
                source_layer_sha256="a" * 64,
            ),
            TerrainGuidanceFeatureCandidate(
                feature_id="z-near-drainage",
                label="near drainage",
                landform=TerrainGuidanceLandform.DRAINAGE,
                centroid=GeoPoint(
                    x=expected_x,
                    y=expected_y,
                    crs="EPSG:4326",
                ),
                source_layer="synthetic_terrain_features",
                source_layer_sha256="b" * 64,
            ),
        ],
    )

    resolution = resolve_terrain_route_guidance(plan, index)
    crossing = next(
        item
        for item in resolution.constraints
        if item.constraint_id == expected_crossing.constraint_id
    )

    assert resolution.candidate_rank_semantics == (
        "typed_landform_elevation_then_candidate_corridor_overlap_then_narrative_sequence_proximity"
    )
    assert crossing.status is TerrainGuidanceResolutionStatus.MULTIPLE_CANDIDATES
    assert crossing.candidate_feature_ids == [
        "z-near-drainage",
        "a-far-drainage",
    ]
    assert crossing.selected_feature_id is None


def test_candidate_corridor_overlap_ranks_review_evidence_without_selecting_it() -> None:
    plan = interpret_terrain_route_narrative(NARRATIVE, source_id="trip-record")
    expected_crossing = next(
        item
        for item in plan.constraints
        if item.kind is TerrainGuidanceConstraintKind.EXPECTED_CROSSING
    )
    start = GeoPoint(x=121.20, y=23.46, crs="EPSG:4326", label="A")
    destination = GeoPoint(x=121.22, y=23.48, crs="EPSG:4326", label="B")
    index = TerrainGuidanceFeatureIndex(
        dem_sha256="d" * 64,
        dem_resolution_m=20,
        crs="EPSG:4326",
        algorithm_version="synthetic_corridor_rank.v1",
        reference_corridor=TerrainGuidanceCorridorReference(
            hypothesis_id="local-r1",
            hypothesis_sha256="c" * 64,
            cache_key="d" * 64,
            band_name="top_5_percent_corridor",
            raster_ref="candidate/top_5_percent_corridor.tif",
            raster_sha256="e" * 64,
            raster_crs="EPSG:3826",
            sampling_backend="synthetic_corridor_sampler.v1",
            sample_count=20,
            inside_sample_count=8,
            outside_or_nodata_sample_count=12,
            feature_count=2,
            features_with_overlap=1,
        ),
        search_window=TerrainGuidanceSearchWindow(
            route_start=start,
            route_destination=destination,
            margin_m=1000,
            west=121.19,
            south=23.45,
            east=121.23,
            north=23.49,
        ),
        features=[
            TerrainGuidanceFeatureCandidate(
                feature_id="a-near-outside-corridor",
                label="near narrative sequence but outside candidate corridor",
                landform=TerrainGuidanceLandform.DRAINAGE,
                centroid=GeoPoint(x=121.212, y=23.472, crs="EPSG:4326"),
                source_layer="synthetic_terrain_features",
                source_layer_sha256="a" * 64,
                reference_corridor_overlap=TerrainGuidanceCorridorOverlap(
                    hypothesis_id="local-r1",
                    band_name="top_5_percent_corridor",
                    sample_count=10,
                    inside_sample_count=0,
                    outside_or_nodata_sample_count=10,
                    overlap_fraction=0,
                ),
            ),
            TerrainGuidanceFeatureCandidate(
                feature_id="z-far-with-corridor-overlap",
                label="farther narrative sequence with candidate corridor overlap",
                landform=TerrainGuidanceLandform.DRAINAGE,
                centroid=GeoPoint(x=121.218, y=23.478, crs="EPSG:4326"),
                source_layer="synthetic_terrain_features",
                source_layer_sha256="b" * 64,
                reference_corridor_overlap=TerrainGuidanceCorridorOverlap(
                    hypothesis_id="local-r1",
                    band_name="top_5_percent_corridor",
                    sample_count=10,
                    inside_sample_count=8,
                    outside_or_nodata_sample_count=2,
                    overlap_fraction=0.8,
                ),
            ),
        ],
    )

    resolution = resolve_terrain_route_guidance(plan, index)
    crossing = next(
        item
        for item in resolution.constraints
        if item.constraint_id == expected_crossing.constraint_id
    )

    assert crossing.status is TerrainGuidanceResolutionStatus.MULTIPLE_CANDIDATES
    assert crossing.candidate_feature_ids == [
        "z-far-with-corridor-overlap",
        "a-near-outside-corridor",
    ]
    assert crossing.selected_feature_id is None
    assert resolution.human_confirmation_required is True
