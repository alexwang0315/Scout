"""Expert terrain-annotation contract for candidate navigation intelligence."""

from __future__ import annotations

import math
from typing import Any


class TerrainAnnotationError(ValueError):
    """Raised when an expert terrain annotation is malformed or unsourced."""


EDGE_ROLE_MAP = {
    "main_ridge": "main_ridge_candidate",
    "spur_ridge": "spur_ridge_candidate",
    "drainage_trunk": "drainage_trunk",
    "tributary": "tributary",
    "watershed_boundary": "watershed_boundary",
    "contour_traverse_band": "contour_traverse_band",
    "observed_route": "gpx_observed",
}
NODE_ROLE_MAP = {
    "ridge_divide_point": "ridge_divide_node",
    "saddle": "saddle_node",
    "headwater": "headwater_node",
    "drainage_confluence": "drainage_confluence_node",
    "terrain_event": "terrain_event_node",
}


def normalize_expert_terrain_annotations(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate expert marks without promoting an image sketch to terrain truth."""

    if not isinstance(payload, dict):
        raise TerrainAnnotationError("annotation payload must be an object")
    annotation_set_id = _required_text(
        payload.get("annotation_set_id"), "annotation_set_id"
    )
    source_refs = _required_refs(payload.get("source_refs"), "source_refs")
    georeference = _normalize_georeference(payload.get("georeference"))
    raw_annotations = payload.get("annotations")
    if not isinstance(raw_annotations, list):
        raise TerrainAnnotationError("annotations must be a list")

    normalized = [
        _normalize_annotation(item, set_source_refs=source_refs)
        for item in raw_annotations
    ]
    geometry_ground_truth_eligible = bool(
        georeference["status"] == "georeferenced"
        and georeference["control_point_count"] >= 3
        and georeference["residual_rmse_m"] is not None
        and georeference["maximum_allowed_residual_m"] is not None
        and georeference["residual_rmse_m"]
        <= georeference["maximum_allowed_residual_m"]
        and all(item["map_geometry_available"] for item in normalized)
    )
    status = (
        "georeferenced_candidate_annotations"
        if geometry_ground_truth_eligible
        else "semantic_training_only"
    )
    return {
        "schema_version": "scout_expert_terrain_annotations.v0",
        "artifact_kind": "expert_terrain_annotations",
        "annotation_set_id": annotation_set_id,
        "status": status,
        "geometry_ground_truth_eligible": geometry_ground_truth_eligible,
        "georeference": georeference,
        "annotations": normalized,
        "source_refs": source_refs,
        "ontology": {
            "edge_roles": dict(EDGE_ROLE_MAP),
            "node_roles": dict(NODE_ROLE_MAP),
            "contour_traverse_band_is_ridge": False,
            "terrain_bifurcation_is_route_fork": False,
        },
        "limitations": [
            (
                "Unreferenced expert marks teach terrain semantics but cannot "
                "serve as coordinate geometry ground truth."
            ),
            (
                "A terrain divide or drainage branch does not prove a trail "
                "junction exists."
            ),
            (
                "A contour-compatible traverse band is not automatically a "
                "ridge, route, or currently walkable corridor."
            ),
        ],
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "safe_or_walkable": "not_determined",
            "human_review_required": True,
            "phase1_runtime_mutation_allowed": False,
        },
    }


def _normalize_georeference(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TerrainAnnotationError("georeference must be an object")
    status = str(value.get("status") or "unreferenced").strip()
    if status not in {"unreferenced", "georeferenced"}:
        raise TerrainAnnotationError("georeference status is unsupported")
    control_point_count = _nonnegative_int(value.get("control_point_count"))
    residual_rmse_m = _finite_number(value.get("residual_rmse_m"))
    maximum_allowed_residual_m = _positive_number(
        value.get("maximum_allowed_residual_m")
    )
    if status == "georeferenced":
        crs = _required_text(value.get("crs"), "georeference.crs")
    else:
        crs = None
    return {
        "status": status,
        "crs": crs,
        "control_point_count": control_point_count,
        "residual_rmse_m": residual_rmse_m,
        "maximum_allowed_residual_m": maximum_allowed_residual_m,
        "survey_grade": False,
    }


def _normalize_annotation(
    value: Any,
    *,
    set_source_refs: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TerrainAnnotationError("each annotation must be an object")
    annotation_id = _required_text(value.get("id"), "annotation.id")
    semantic_role = _required_text(
        value.get("semantic_role"),
        f"annotation {annotation_id} semantic_role",
    )
    if semantic_role not in EDGE_ROLE_MAP and semantic_role not in NODE_ROLE_MAP:
        raise TerrainAnnotationError(
            f"annotation {annotation_id} semantic_role is unsupported"
        )
    geometry_type = _required_text(
        value.get("geometry_type"),
        f"annotation {annotation_id} geometry_type",
    )
    expected_geometry = "LineString" if semantic_role in EDGE_ROLE_MAP else "Point"
    if geometry_type != expected_geometry:
        raise TerrainAnnotationError(
            f"annotation {annotation_id} requires {expected_geometry}"
        )
    source_refs = _required_refs(
        value.get("source_refs"),
        f"annotation {annotation_id} source_refs",
    )
    if not set(source_refs).intersection(set_source_refs):
        raise TerrainAnnotationError(
            f"annotation {annotation_id} source_refs do not cite the annotation set"
        )

    image_geometry = _normalize_geometry(
        value.get("image_coordinates"),
        geometry_type=geometry_type,
        field_name=f"annotation {annotation_id} image_coordinates",
        required=False,
    )
    map_geometry = _normalize_geometry(
        value.get("coordinates_twd97"),
        geometry_type=geometry_type,
        field_name=f"annotation {annotation_id} coordinates_twd97",
        required=False,
    )
    if image_geometry is None and map_geometry is None:
        raise TerrainAnnotationError(
            f"annotation {annotation_id} has no usable geometry"
        )

    result = {
        "id": annotation_id,
        "semantic_role": semantic_role,
        "geometry_type": geometry_type,
        "image_coordinates": image_geometry,
        "coordinates_twd97": map_geometry,
        "map_geometry_available": map_geometry is not None,
        "source_refs": source_refs,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "requires_human_review": True,
    }
    if semantic_role in EDGE_ROLE_MAP:
        result["terrain_edge_kind"] = EDGE_ROLE_MAP[semantic_role]
    else:
        result["terrain_node_kind"] = NODE_ROLE_MAP[semantic_role]
    return result


def _normalize_geometry(
    value: Any,
    *,
    geometry_type: str,
    field_name: str,
    required: bool,
) -> list[float] | list[list[float]] | None:
    if value is None and not required:
        return None
    if geometry_type == "Point":
        point = _coordinate_pair(value)
        if point is None:
            raise TerrainAnnotationError(f"{field_name} must be a coordinate pair")
        return point
    if not isinstance(value, list):
        raise TerrainAnnotationError(f"{field_name} must be a coordinate list")
    points = [_coordinate_pair(item) for item in value]
    if len(points) < 2 or any(point is None for point in points):
        raise TerrainAnnotationError(
            f"{field_name} must contain at least two coordinate pairs"
        )
    return [point for point in points if point is not None]


def _coordinate_pair(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x = _finite_number(value[0])
    y = _finite_number(value[1])
    if x is None or y is None:
        return None
    return [x, y]


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TerrainAnnotationError(f"{field_name} is required")
    return value.strip()[:200]


def _required_refs(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise TerrainAnnotationError(f"{field_name} must be a non-empty list")
    refs = list(
        dict.fromkeys(
            item.strip()[:500]
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )
    if not refs:
        raise TerrainAnnotationError(f"{field_name} must be a non-empty list")
    return refs[:32]


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_number(value: Any) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
