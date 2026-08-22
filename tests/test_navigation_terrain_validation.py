from __future__ import annotations

import pytest

from navigation_terrain_validation import (
    build_terrain_validation_receipt,
    compare_polylines,
)


def _hierarchy(*, y_offset: float = 0.0) -> dict:
    return {
        "schema_version": "scout_navigation_terrain_hierarchy.v0",
        "grid": {
            "crs": "EPSG:3826",
            "cell_resolution_m": 20,
        },
        "method": {
            "ridge_extraction": "multi_scale_hessian_subcell_ridge_trace.v1",
            "drainage_extraction": "conditioned_mfd_accumulation_valley_trace.v1",
            "geometry": "subcell_support_constrained_topology_trace.v1",
        },
        "nodes": [
            {"id": "a", "kind": "ridge_end_node"},
            {"id": "b", "kind": "ridge_end_node"},
        ],
        "edges": [
            {
                "id": "ridge-1",
                "from": "a",
                "to": "b",
                "kind": "main_ridge_candidate",
                "coordinates_twd97": [
                    [250000, 2600000 + y_offset, 1000],
                    [250100, 2600000 + y_offset, 1000],
                ],
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
        },
    }


def _reference(*, annotator: str, set_id: str, y_offset: float = 0.0) -> dict:
    return {
        "annotation_set_id": set_id,
        "annotator_id": annotator,
        "reference_case_id": "case-01",
        "dataset_split": "blind_holdout",
        "independence_declared": True,
        "topology_review_complete": True,
        "ambiguous_mask_reviewed": True,
        "source_refs": [f"{set_id}.tif", f"{set_id}-controls.json"],
        "georeference": {
            "status": "georeferenced",
            "crs": "EPSG:3826",
            "control_point_count": 5,
            "residual_rmse_m": 2.0,
            "maximum_allowed_residual_m": 8.0,
        },
        "annotations": [
            {
                "id": f"{set_id}-ridge",
                "semantic_role": "main_ridge",
                "geometry_type": "LineString",
                "coordinates_twd97": [
                    [250000, 2600000 + y_offset],
                    [250100, 2600000 + y_offset],
                ],
                "uncertainty_half_width_m": 12,
                "ambiguous": False,
                "topology": {"connected_to": [], "junction_id": None},
                "source_refs": [f"{set_id}.tif"],
            }
        ],
        "ambiguous_masks": [],
    }


def _test_policy() -> dict:
    return {
        "schema_version": "scout_navigation_terrain_acceptance_policy.v0",
        "policy_id": "test-policy-only",
        "status": "approved",
        "baseline_receipt_ref": "test-baseline.json",
        "approved_by": ["test-reviewer-a", "test-reviewer-b"],
        "thresholds": {
            "lateral_rmse_m_max": 10,
            "h95_m_max": 15,
            "frechet_m_max": 20,
            "component_count_error_max": 0,
            "branch_count_error_max": 0,
            "junction_count_error_max": 0,
            "hydrologic_violation_fraction_max": 0,
            "grid_axis_quantized_fraction_max": 1,
        },
    }


def test_polyline_metrics_measure_lateral_offset() -> None:
    metrics = compare_polylines(
        [[0, 0], [100, 0]],
        [[0, 3], [100, 3]],
        sample_spacing_m=5,
    )

    assert metrics["lateral_rmse_m"] == pytest.approx(3.0, abs=0.01)
    assert metrics["h95_m"] == pytest.approx(3.0, abs=0.01)
    assert metrics["hausdorff_m"] == pytest.approx(3.0, abs=0.01)
    assert metrics["discrete_frechet_m"] == pytest.approx(3.0, abs=0.01)


def test_validation_gate_blocks_when_reference_is_missing() -> None:
    receipt = build_terrain_validation_receipt(_hierarchy(), [])

    assert receipt["validation_state"] == "blocked_pending_reference"
    assert receipt["gate_mode"] == "shadow_only"
    assert receipt["operational_authority"] is False
    assert receipt["event_source_mode"] == "prohibited"
    assert receipt["event_unlocks"] == {
        "crossing": False,
        "wrong_way": False,
        "recovery": False,
    }


def test_two_independent_blind_references_produce_baseline_but_not_promotion() -> None:
    receipt = build_terrain_validation_receipt(
        _hierarchy(y_offset=4),
        [
            _reference(annotator="expert-a", set_id="ref-a"),
            _reference(annotator="expert-b", set_id="ref-b", y_offset=2),
        ],
    )

    assert receipt["validation_state"] == "blocked_pending_acceptance_policy"
    assert receipt["baseline_status"] == "measured"
    assert receipt["reference_coverage"]["independent_annotator_count"] == 2
    assert receipt["aggregate_metrics"]["lateral_rmse_m"] > 0
    assert receipt["geometry_presentation_eligible"] is False
    assert receipt["event_source_mode"] == "prohibited"


def test_approved_policy_can_validate_geometry_without_unlocking_events() -> None:
    receipt = build_terrain_validation_receipt(
        _hierarchy(y_offset=3),
        [
            _reference(annotator="expert-a", set_id="ref-a"),
            _reference(annotator="expert-b", set_id="ref-b", y_offset=1),
        ],
        acceptance_policy=_test_policy(),
    )

    assert receipt["validation_state"] == "validated_candidate_geometry"
    assert receipt["geometry_presentation_eligible"] is True
    assert receipt["operational_authority"] is False
    assert receipt["event_source_mode"] == "prohibited_pending_event_type_gate"
    assert receipt["event_unlocks"]["crossing"] is False
    assert receipt["event_unlocks"]["wrong_way"] is False
    assert receipt["event_unlocks"]["recovery"] is False


def test_hydrologic_regression_fails_geometry_policy() -> None:
    hierarchy = _hierarchy()
    hierarchy["edges"].append(
        {
            "id": "drainage-1",
            "from": "a",
            "to": "b",
            "kind": "drainage_trunk",
            "coordinates_twd97": [[250000, 2600000, 1000], [250100, 2600000, 1010]],
            "conditioned_elevation_profile_m": [1000, 1010],
            "flow_accumulation_start": 10,
            "flow_accumulation_end": 5,
            "flow_supported": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    receipt = build_terrain_validation_receipt(
        hierarchy,
        [
            _reference(annotator="expert-a", set_id="ref-a"),
            _reference(annotator="expert-b", set_id="ref-b"),
        ],
        acceptance_policy=_test_policy(),
    )

    assert receipt["validation_state"] == "failed_candidate_geometry"
    assert receipt["hydrology"]["violation_fraction"] > 0
    assert "hydrologic_violation_fraction_max" in receipt["failed_thresholds"]
