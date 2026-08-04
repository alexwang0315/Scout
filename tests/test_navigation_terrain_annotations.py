from __future__ import annotations

import json
from pathlib import Path

import pytest

from navigation_terrain_annotations import (
    TerrainAnnotationError,
    normalize_expert_terrain_annotations,
)


def test_unreferenced_expert_marks_are_semantic_training_evidence_only() -> None:
    result = normalize_expert_terrain_annotations(
        {
            "annotation_set_id": "expert-photo-1",
            "source_refs": ["expert-photo-1.jpg"],
            "georeference": {"status": "unreferenced"},
            "annotations": [
                {
                    "id": "main-ridge-a",
                    "semantic_role": "main_ridge",
                    "geometry_type": "LineString",
                    "image_coordinates": [[12, 18], [40, 31], [72, 28]],
                    "source_refs": ["expert-photo-1.jpg"],
                },
                {
                    "id": "horizontal-band-a",
                    "semantic_role": "contour_traverse_band",
                    "geometry_type": "LineString",
                    "image_coordinates": [[10, 60], [80, 61]],
                    "source_refs": ["expert-photo-1.jpg"],
                },
            ],
        }
    )

    assert result["status"] == "semantic_training_only"
    assert result["geometry_ground_truth_eligible"] is False
    assert result["annotations"][0]["terrain_edge_kind"] == ("main_ridge_candidate")
    assert result["annotations"][1]["terrain_edge_kind"] == ("contour_traverse_band")
    assert result["annotations"][1]["terrain_edge_kind"] != ("main_ridge_candidate")
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False


def test_georeferenced_expert_marks_require_bounded_residual() -> None:
    result = normalize_expert_terrain_annotations(
        {
            "annotation_set_id": "expert-map-2",
            "source_refs": ["expert-map-2.tif", "control-points.json"],
            "georeference": {
                "status": "georeferenced",
                "crs": "EPSG:3826",
                "control_point_count": 4,
                "residual_rmse_m": 8.5,
                "maximum_allowed_residual_m": 20,
            },
            "annotations": [
                {
                    "id": "divide-1",
                    "semantic_role": "ridge_divide_point",
                    "geometry_type": "Point",
                    "coordinates_twd97": [250100, 2600100],
                    "source_refs": ["expert-map-2.tif", "control-points.json"],
                }
            ],
        }
    )

    assert result["status"] == "georeferenced_candidate_annotations"
    assert result["geometry_ground_truth_eligible"] is True
    assert result["blind_validation_eligible"] is False
    assert result["annotations"][0]["terrain_node_kind"] == "ridge_divide_node"


def test_blind_reference_requires_independent_protocol_and_uncertainty() -> None:
    result = normalize_expert_terrain_annotations(
        {
            "annotation_set_id": "expert-map-blind-a",
            "annotator_id": "expert-a",
            "reference_case_id": "watershed-window-01",
            "dataset_split": "blind_holdout",
            "independence_declared": True,
            "topology_review_complete": True,
            "ambiguous_mask_reviewed": True,
            "source_refs": ["expert-map.tif", "controls.json"],
            "georeference": {
                "status": "georeferenced",
                "crs": "EPSG:3826",
                "control_point_count": 6,
                "residual_rmse_m": 4.2,
                "maximum_allowed_residual_m": 10,
            },
            "annotations": [
                {
                    "id": "ridge-a",
                    "semantic_role": "main_ridge",
                    "geometry_type": "LineString",
                    "coordinates_twd97": [[250000, 2600000], [250100, 2600100]],
                    "uncertainty_half_width_m": 18,
                    "ambiguous": False,
                    "topology": {"connected_to": [], "junction_id": None},
                    "source_refs": ["expert-map.tif"],
                }
            ],
            "ambiguous_masks": [
                {
                    "id": "mask-a",
                    "coordinates_twd97": [
                        [250040, 2600040],
                        [250060, 2600040],
                        [250060, 2600060],
                        [250040, 2600040],
                    ],
                    "source_refs": ["expert-map.tif"],
                }
            ],
        }
    )

    assert result["blind_validation_eligible"] is True
    assert result["protocol"]["annotator_id"] == "expert-a"
    assert result["protocol"]["dataset_split"] == "blind_holdout"
    assert result["annotations"][0]["uncertainty_half_width_m"] == 18
    assert result["annotations"][0]["ambiguous"] is False
    assert result["ambiguous_masks"][0]["geometry_type"] == "Polygon"


def test_unknown_reference_dataset_split_fails_closed() -> None:
    with pytest.raises(TerrainAnnotationError, match="dataset_split"):
        normalize_expert_terrain_annotations(
            {
                "annotation_set_id": "bad-split",
                "dataset_split": "production",
                "source_refs": ["expert.jpg"],
                "georeference": {"status": "unreferenced"},
                "annotations": [],
            }
        )


def test_annotation_model_rejects_missing_provenance() -> None:
    with pytest.raises(TerrainAnnotationError, match="source_refs"):
        normalize_expert_terrain_annotations(
            {
                "annotation_set_id": "bad",
                "source_refs": ["expert.jpg"],
                "georeference": {"status": "unreferenced"},
                "annotations": [
                    {
                        "id": "ridge",
                        "semantic_role": "main_ridge",
                        "geometry_type": "LineString",
                        "image_coordinates": [[0, 0], [1, 1]],
                    }
                ],
            }
        )


def test_skill_expert_annotation_example_matches_runtime_contract() -> None:
    example_path = (
        Path(__file__).parents[1]
        / ".agents/skills/infer-historical-dem-gpx-routes/references"
        / "expert-terrain-annotation-example.json"
    )
    result = normalize_expert_terrain_annotations(
        json.loads(example_path.read_text(encoding="utf-8"))
    )

    assert result["status"] == "semantic_training_only"
    assert len(result["annotations"]) == 4
