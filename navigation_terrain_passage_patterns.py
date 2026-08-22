"""Explainable positive-unlabeled terrain patterns from observed passage lines."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import Any, Mapping, Sequence

from navigation_terrain_dem import WorkspaceTerrainGrid
from pretrip_source_ingest import wgs84_to_twd97

MAX_OBSERVED_PATHS = 500
MAX_POINTS_PER_PATH = 320
MAX_OBSERVATIONS = 30_000


def build_terrain_passage_prior(
    workspace_grid: WorkspaceTerrainGrid,
    *,
    observed_paths: Sequence[dict[str, Any]],
    terrain_hierarchy: Mapping[str, Any],
    source_refs: Sequence[str],
) -> dict[str, Any]:
    """Describe terrain patterns along known vectors without inventing negatives."""

    elevations = {
        (float(x), float(y)): float(elevation)
        for (x, y), elevation in workspace_grid.elevations.items()
        if all(math.isfinite(value) for value in (x, y, elevation))
    }
    if len(elevations) < 9:
        return empty_terrain_passage_prior(
            "Workspace DEM has insufficient supported cells for passage patterns."
        )
    resolution_m = float(workspace_grid.resolution_m)
    origin = (
        min(cell[0] for cell in elevations),
        min(cell[1] for cell in elevations),
    )
    relation_index = _terrain_relation_index(
        terrain_hierarchy,
        origin=origin,
        resolution_m=resolution_m,
    )

    normalized_paths, duplicate_path_count = _normalize_observed_paths(
        observed_paths,
        origin=origin,
        resolution_m=resolution_m,
    )
    observations: list[dict[str, Any]] = []
    observations_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unsupported_sample_count = 0
    source_path_counts: Counter[str] = Counter()
    for path in normalized_paths:
        if len(observations) >= MAX_OBSERVATIONS:
            break
        source_path_counts[path["source_kind"]] += 1
        sampled, unsupported = _path_observations(
            path,
            elevations,
            origin=origin,
            resolution_m=resolution_m,
            relation_index=relation_index,
            remaining_budget=MAX_OBSERVATIONS - len(observations),
        )
        unsupported_sample_count += unsupported
        observations.extend(sampled)
        observations_by_path[path["id"]].extend(sampled)

    if not observations:
        return empty_terrain_passage_prior(
            "No observed GPX or OSM/Overpass trail sample intersects supported DEM cells."
        ) | {
            "source_path_counts": dict(sorted(source_path_counts.items())),
            "sampling": {
                "supported_observation_count": 0,
                "unsupported_sample_count": unsupported_sample_count,
                "unsupported_gap_bridge_count": 0,
                "maximum_observation_count": MAX_OBSERVATIONS,
                "duplicate_path_count": duplicate_path_count,
            },
        }

    source_profiles = {
        source_kind: _observation_profile(
            [item for item in observations if item["source_kind"] == source_kind]
        )
        for source_kind in sorted({item["source_kind"] for item in observations})
    }
    pattern_counts = Counter(item["pattern_key"] for item in observations)
    transition_counts: Counter[tuple[str, str]] = Counter()
    for path_observations in observations_by_path.values():
        tokens = [item["pattern_key"] for item in path_observations]
        transition_counts.update(zip(tokens, tokens[1:]))

    return {
        "schema_version": "scout_navigation_terrain_passage_prior.v0",
        "artifact_kind": "observed_terrain_passage_patterns",
        "status": "observed_positive_patterns",
        "model_kind": "descriptive_positive_only_prior.v0",
        "source_path_count": sum(source_path_counts.values()),
        "source_path_counts": dict(sorted(source_path_counts.items())),
        "observation_count": len(observations),
        "source_profiles": source_profiles,
        "feature_distributions": _observation_profile(observations),
        "dominant_patterns": [
            {
                "pattern": pattern,
                "count": count,
                "share": round(count / len(observations), 4),
            }
            for pattern, count in pattern_counts.most_common(12)
        ],
        "dominant_transitions": [
            {
                "from_pattern": start,
                "to_pattern": end,
                "count": count,
            }
            for (start, end), count in transition_counts.most_common(12)
        ],
        "feature_schema": {
            "slope_degrees": "DEM central-difference slope at observed passage sample",
            "contour_alignment_degrees": (
                "0 degrees follows the local contour tangent; 90 degrees follows the fall line"
            ),
            "tpi_m": "center elevation minus eight-neighbor mean",
            "local_relief_m": "eight-neighbor plus center elevation range",
            "terrain_relation": (
                "proximity to candidate ridge, drainage or saddle support; not a route label"
            ),
        },
        "learning_contract": {
            "learning_mode": "positive_unlabeled_descriptive_prior",
            "positive_sources": ["gpx_observed", "gpx_reference", "osm_overpass_trail"],
            "osm_absence_semantics": "unknown",
            "negative_labels_created": False,
            "rudy_tw_role": "visual_reference_only_no_label_extraction",
            "provider_bias_retained": True,
            "classifier_trained": False,
            "future_model_family": "positive_unlabeled_or_case_control_after_bias_audit",
            "osm_mapping_completeness": "unknown_not_measured",
            "terrain_extraction_feedback": "prohibited",
        },
        "evaluation": {
            "classifier_holdout_status": "not_applicable_descriptive_prior",
            "route_level_holdout_required_before_training": True,
            "region_level_holdout_required_before_training": True,
            "feature_contributions": "explicit_pattern_counts_and_source_profiles",
        },
        "sampling": {
            "supported_observation_count": len(observations),
            "unsupported_sample_count": unsupported_sample_count,
            "unsupported_gap_bridge_count": 0,
            "maximum_observation_count": MAX_OBSERVATIONS,
            "observation_spacing_m": round(resolution_m * 0.75, 2),
            "coordinates_embedded": False,
            "duplicate_path_count": duplicate_path_count,
            "deduplication_method": "direction_invariant_source_cell_chain.v1",
        },
        "source_refs": _bounded_refs(source_refs),
        "limitations": [
            "Observed GPX and mapped OSM trails are biased positive samples, not a census.",
            "OSM absence is unknown and is never converted into a negative label.",
            "Rudy+TW is used for human visual comparison, not pixel-derived training truth.",
            "Terrain association does not establish that a different place is passable.",
            "Vegetation, cliffs, land access, erosion and current conditions are unmodeled.",
        ],
        "boundary": _candidate_boundary(),
    }


def observed_paths_from_projected_route(
    route_points: Sequence[dict[str, Any]],
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    coordinates = [
        [float(point["x_twd97"]), float(point["y_twd97"])]
        for point in route_points
        if _finite(point.get("x_twd97")) is not None
        and _finite(point.get("y_twd97")) is not None
    ]
    if len(coordinates) < 2:
        return []
    return [
        {
            "id": "prepared-gpx-baseline",
            "source_kind": "gpx_observed",
            "coordinates_twd97": _evenly_sample(coordinates, MAX_POINTS_PER_PATH),
            "source_refs": [source_ref],
        }
    ]


def observed_paths_from_reference_tracks(
    payload: Mapping[str, Any],
    *,
    source_ref: str,
) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    tracks = payload.get("reference_tracks", [])
    if not isinstance(tracks, list):
        return paths
    for track_index, track in enumerate(tracks[:64]):
        if not isinstance(track, dict):
            continue
        raw_segments = track.get("coordinate_segments", [])
        if not isinstance(raw_segments, list) or not raw_segments:
            raw_segments = [track.get("coordinates", [])]
        for segment_index, segment in enumerate(raw_segments[:64]):
            coordinates = _wgs84_points_to_twd97(segment)
            if len(coordinates) < 2:
                continue
            paths.append(
                {
                    "id": (
                        f"reference-track-{track_index:02d}-segment-{segment_index:02d}"
                    ),
                    "source_kind": "gpx_reference",
                    "coordinates_twd97": _evenly_sample(
                        coordinates,
                        MAX_POINTS_PER_PATH,
                    ),
                    "source_refs": [source_ref],
                }
            )
            if len(paths) >= MAX_OBSERVED_PATHS:
                return paths
    return paths


def observed_paths_from_overpass(
    payload: Mapping[str, Any],
    *,
    source_ref: str,
    bbox_twd97: Mapping[str, float],
) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    features = payload.get("features", [])
    if not isinstance(features, list):
        return paths
    for feature_index, feature in enumerate(features):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties", {})
        if not isinstance(properties, dict) or properties.get("candidate_type") not in {
            "trail_corridor_candidate",
            "hiking_route_candidate",
        }:
            continue
        geometry = feature.get("geometry", {})
        if not isinstance(geometry, dict):
            continue
        raw_lines = (
            [geometry.get("coordinates", [])]
            if geometry.get("type") == "LineString"
            else geometry.get("coordinates", [])
            if geometry.get("type") == "MultiLineString"
            else []
        )
        if not isinstance(raw_lines, list):
            continue
        for line_index, line in enumerate(raw_lines[:32]):
            coordinates = _wgs84_coordinate_pairs_to_twd97(line)
            if len(coordinates) < 2 or not _line_intersects_bbox(coordinates, bbox_twd97):
                continue
            paths.append(
                {
                    "id": f"overpass-{feature_index:04d}-{line_index:02d}",
                    "source_kind": "osm_overpass_trail",
                    "coordinates_twd97": _evenly_sample(
                        coordinates,
                        MAX_POINTS_PER_PATH,
                    ),
                    "source_refs": [source_ref],
                }
            )
            if len(paths) >= MAX_OBSERVED_PATHS:
                return paths
    return paths


def empty_terrain_passage_prior(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_terrain_passage_prior.v0",
        "artifact_kind": "observed_terrain_passage_patterns",
        "status": "not_prepared",
        "model_kind": "descriptive_positive_only_prior.v0",
        "source_path_count": 0,
        "source_path_counts": {},
        "observation_count": 0,
        "source_profiles": {},
        "feature_distributions": {},
        "dominant_patterns": [],
        "dominant_transitions": [],
        "learning_contract": {
            "learning_mode": "positive_unlabeled_descriptive_prior",
            "osm_absence_semantics": "unknown",
            "negative_labels_created": False,
            "rudy_tw_role": "visual_reference_only_no_label_extraction",
            "provider_bias_retained": True,
            "classifier_trained": False,
            "osm_mapping_completeness": "unknown_not_measured",
            "terrain_extraction_feedback": "prohibited",
        },
        "evaluation": {
            "classifier_holdout_status": "not_applicable_descriptive_prior",
            "route_level_holdout_required_before_training": True,
            "region_level_holdout_required_before_training": True,
            "feature_contributions": "not_prepared",
        },
        "sampling": {
            "supported_observation_count": 0,
            "unsupported_sample_count": 0,
            "unsupported_gap_bridge_count": 0,
            "maximum_observation_count": MAX_OBSERVATIONS,
            "duplicate_path_count": 0,
            "deduplication_method": "direction_invariant_source_cell_chain.v1",
        },
        "source_refs": [],
        "limitations": [reason],
        "boundary": _candidate_boundary(),
    }


def _path_observations(
    path: Mapping[str, Any],
    elevations: Mapping[tuple[float, float], float],
    *,
    origin: tuple[float, float],
    resolution_m: float,
    relation_index: Mapping[tuple[int, int], list[tuple[float, float, str]]],
    remaining_budget: int,
) -> tuple[list[dict[str, Any]], int]:
    coordinates = path["coordinates_twd97"]
    observations: list[dict[str, Any]] = []
    unsupported = 0
    last_cell: tuple[float, float] | None = None
    for start, end in zip(coordinates, coordinates[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_m = math.hypot(dx, dy)
        if length_m < 0.01:
            continue
        step_count = max(1, min(256, math.ceil(length_m / (resolution_m * 0.75))))
        for step in range(step_count):
            if len(observations) >= remaining_budget:
                return observations, unsupported
            ratio = (step + 0.5) / step_count
            x = start[0] + dx * ratio
            y = start[1] + dy * ratio
            cell = _snap_cell(x, y, origin=origin, resolution_m=resolution_m)
            if cell == last_cell:
                continue
            last_cell = cell
            metrics = _local_terrain_metrics(
                cell,
                elevations,
                movement=(dx, dy),
                resolution_m=resolution_m,
            )
            if metrics is None:
                unsupported += 1
                continue
            relation = _terrain_relation(
                cell,
                relation_index,
                origin=origin,
                resolution_m=resolution_m,
            )
            slope_bin = _slope_bin(metrics["slope_degrees"])
            alignment_bin = _alignment_bin(metrics["contour_alignment_degrees"])
            form = _terrain_form(metrics["tpi_m"])
            observations.append(
                {
                    "path_id": path["id"],
                    "source_kind": path["source_kind"],
                    **metrics,
                    "terrain_relation": relation,
                    "slope_bin": slope_bin,
                    "alignment_bin": alignment_bin,
                    "terrain_form": form,
                    "pattern_key": f"{slope_bin}|{alignment_bin}|{relation}|{form}",
                }
            )
    return observations, unsupported


def _local_terrain_metrics(
    cell: tuple[float, float],
    elevations: Mapping[tuple[float, float], float],
    *,
    movement: tuple[float, float],
    resolution_m: float,
) -> dict[str, float] | None:
    center = elevations.get(cell)
    if center is None:
        return None
    east = elevations.get((cell[0] + resolution_m, cell[1]))
    west = elevations.get((cell[0] - resolution_m, cell[1]))
    north = elevations.get((cell[0], cell[1] + resolution_m))
    south = elevations.get((cell[0], cell[1] - resolution_m))
    if any(value is None for value in (east, west, north, south)):
        return None
    dzdx = (float(east) - float(west)) / (2 * resolution_m)
    dzdy = (float(north) - float(south)) / (2 * resolution_m)
    gradient = math.hypot(dzdx, dzdy)
    slope_degrees = math.degrees(math.atan(gradient))
    movement_length = math.hypot(*movement)
    if movement_length <= 1e-9 or gradient <= 1e-9:
        contour_alignment = 0.0
    else:
        fall_line_component = abs(
            (movement[0] / movement_length) * (dzdx / gradient)
            + (movement[1] / movement_length) * (dzdy / gradient)
        )
        contour_alignment = math.degrees(
            math.asin(max(0.0, min(1.0, fall_line_component)))
        )
    neighbors = [
        elevations.get((cell[0] + dx * resolution_m, cell[1] + dy * resolution_m))
        for dx, dy in (
            (-1, -1),
            (0, -1),
            (1, -1),
            (-1, 0),
            (1, 0),
            (-1, 1),
            (0, 1),
            (1, 1),
        )
    ]
    supported_neighbors = [float(value) for value in neighbors if value is not None]
    if len(supported_neighbors) < 6:
        return None
    tpi_m = float(center) - sum(supported_neighbors) / len(supported_neighbors)
    local_relief_m = max([float(center), *supported_neighbors]) - min(
        [float(center), *supported_neighbors]
    )
    return {
        "slope_degrees": round(slope_degrees, 3),
        "contour_alignment_degrees": round(contour_alignment, 3),
        "tpi_m": round(tpi_m, 3),
        "local_relief_m": round(local_relief_m, 3),
    }


def _observation_profile(observations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not observations:
        return {
            "observation_count": 0,
            "slope_counts": {},
            "alignment_counts": {},
            "terrain_relation_counts": {},
            "terrain_form_counts": {},
            "quantiles": {},
        }
    slopes = sorted(float(item["slope_degrees"]) for item in observations)
    alignments = sorted(
        float(item["contour_alignment_degrees"]) for item in observations
    )
    return {
        "observation_count": len(observations),
        "slope_counts": dict(sorted(Counter(item["slope_bin"] for item in observations).items())),
        "alignment_counts": dict(
            sorted(Counter(item["alignment_bin"] for item in observations).items())
        ),
        "terrain_relation_counts": dict(
            sorted(Counter(item["terrain_relation"] for item in observations).items())
        ),
        "terrain_form_counts": dict(
            sorted(Counter(item["terrain_form"] for item in observations).items())
        ),
        "quantiles": {
            "slope_degrees_p50": round(_quantile(slopes, 0.5), 2),
            "slope_degrees_p75": round(_quantile(slopes, 0.75), 2),
            "slope_degrees_p90": round(_quantile(slopes, 0.9), 2),
            "contour_alignment_degrees_p50": round(_quantile(alignments, 0.5), 2),
            "contour_alignment_degrees_p90": round(_quantile(alignments, 0.9), 2),
        },
    }


def _terrain_relation_index(
    hierarchy: Mapping[str, Any],
    *,
    origin: tuple[float, float],
    resolution_m: float,
) -> dict[tuple[int, int], list[tuple[float, float, str]]]:
    index: dict[tuple[int, int], list[tuple[float, float, str]]] = defaultdict(list)
    edges = hierarchy.get("edges", [])
    if isinstance(edges, list):
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            kind = str(edge.get("kind") or "terrain_candidate")
            coordinates = edge.get("coordinates_twd97", [])
            if not isinstance(coordinates, list):
                continue
            for point in coordinates:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                x, y = _finite(point[0]), _finite(point[1])
                if x is None or y is None:
                    continue
                key = _cell_index(x, y, origin=origin, resolution_m=resolution_m)
                index[key].append((x, y, kind))
    nodes = hierarchy.get("nodes", [])
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict) or node.get("kind") != "saddle_node":
                continue
            x, y = _finite(node.get("x_twd97")), _finite(node.get("y_twd97"))
            if x is None or y is None:
                continue
            key = _cell_index(x, y, origin=origin, resolution_m=resolution_m)
            index[key].append((x, y, "saddle_candidate"))
    return dict(index)


def _terrain_relation(
    cell: tuple[float, float],
    index: Mapping[tuple[int, int], list[tuple[float, float, str]]],
    *,
    origin: tuple[float, float],
    resolution_m: float,
) -> str:
    base = _cell_index(cell[0], cell[1], origin=origin, resolution_m=resolution_m)
    candidates: list[tuple[float, str]] = []
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            for x, y, kind in index.get((base[0] + dx, base[1] + dy), []):
                distance_m = math.hypot(cell[0] - x, cell[1] - y)
                if distance_m <= resolution_m * 2.5:
                    candidates.append((distance_m, kind))
    if not candidates:
        return "no_nearby_terrain_candidate"
    return min(
        candidates,
        key=lambda item: (
            0 if item[1] == "saddle_candidate" else 1,
            item[0],
            item[1],
        ),
    )[1]


def _normalize_observed_paths(
    observed_paths: Sequence[dict[str, Any]],
    *,
    origin: tuple[float, float],
    resolution_m: float,
) -> tuple[list[dict[str, Any]], int]:
    result = []
    signatures: set[tuple[tuple[int, int], ...]] = set()
    duplicate_count = 0
    for index, path in enumerate(observed_paths[:MAX_OBSERVED_PATHS]):
        if not isinstance(path, dict):
            continue
        source_kind = str(path.get("source_kind") or "unknown")
        coordinates = []
        for point in path.get("coordinates_twd97", []):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            x, y = _finite(point[0]), _finite(point[1])
            if x is None or y is None:
                continue
            coordinate = [x, y]
            if not coordinates or coordinate != coordinates[-1]:
                coordinates.append(coordinate)
        coordinates = _evenly_sample(coordinates, MAX_POINTS_PER_PATH)
        if len(coordinates) < 2:
            continue
        cell_chain = tuple(
            dict.fromkeys(
                _cell_index(
                    point[0],
                    point[1],
                    origin=origin,
                    resolution_m=resolution_m,
                )
                for point in coordinates
            )
        )
        reverse_chain = tuple(reversed(cell_chain))
        signature = min(cell_chain, reverse_chain)
        if signature in signatures:
            duplicate_count += 1
            continue
        signatures.add(signature)
        result.append(
            {
                "id": str(path.get("id") or f"observed-path-{index:04d}"),
                "source_kind": source_kind,
                "coordinates_twd97": coordinates,
                "source_refs": _bounded_refs(path.get("source_refs", [])),
            }
        )
    return result, duplicate_count


def _wgs84_points_to_twd97(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    coordinates = []
    for item in value:
        if not isinstance(item, dict):
            continue
        lat, lon = _finite(item.get("lat")), _finite(item.get("lon"))
        if lat is None or lon is None:
            continue
        x, y = wgs84_to_twd97(lat, lon)
        coordinates.append([x, y])
    return coordinates


def _wgs84_coordinate_pairs_to_twd97(value: Any) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    coordinates = []
    for item in _evenly_sample(value, MAX_POINTS_PER_PATH):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lon, lat = _finite(item[0]), _finite(item[1])
        if lat is None or lon is None:
            continue
        x, y = wgs84_to_twd97(lat, lon)
        coordinates.append([x, y])
    return coordinates


def _line_intersects_bbox(
    coordinates: Sequence[Sequence[float]],
    bbox: Mapping[str, float],
) -> bool:
    min_x = _finite(bbox.get("min_x"))
    max_x = _finite(bbox.get("max_x"))
    min_y = _finite(bbox.get("min_y"))
    max_y = _finite(bbox.get("max_y"))
    if None in (min_x, max_x, min_y, max_y):
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        return bool(xs and ys)
    line_min_x = min(point[0] for point in coordinates)
    line_max_x = max(point[0] for point in coordinates)
    line_min_y = min(point[1] for point in coordinates)
    line_max_y = max(point[1] for point in coordinates)
    return not (
        line_max_x < float(min_x)
        or line_min_x > float(max_x)
        or line_max_y < float(min_y)
        or line_min_y > float(max_y)
    )


def _snap_cell(
    x: float,
    y: float,
    *,
    origin: tuple[float, float],
    resolution_m: float,
) -> tuple[float, float]:
    return (
        origin[0] + round((x - origin[0]) / resolution_m) * resolution_m,
        origin[1] + round((y - origin[1]) / resolution_m) * resolution_m,
    )


def _cell_index(
    x: float,
    y: float,
    *,
    origin: tuple[float, float],
    resolution_m: float,
) -> tuple[int, int]:
    return (
        round((x - origin[0]) / resolution_m),
        round((y - origin[1]) / resolution_m),
    )


def _slope_bin(value: float) -> str:
    if value < 10:
        return "slope_00_10"
    if value < 20:
        return "slope_10_20"
    if value < 30:
        return "slope_20_30"
    if value < 40:
        return "slope_30_40"
    return "slope_40_plus"


def _alignment_bin(value: float) -> str:
    if value < 22.5:
        return "contour_following"
    if value < 67.5:
        return "oblique"
    return "fall_line"


def _terrain_form(tpi_m: float) -> str:
    if tpi_m > 2:
        return "locally_convex"
    if tpi_m < -2:
        return "locally_concave"
    return "locally_neutral"


def _quantile(values: Sequence[float], ratio: float) -> float:
    if not values:
        return 0.0
    position = max(0.0, min(1.0, ratio)) * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return float(values[lower]) * (1 - fraction) + float(values[upper]) * fraction


def _evenly_sample(items: Sequence[Any], limit: int) -> list[Any]:
    values = list(items)
    if len(values) <= limit:
        return values
    indices = {
        round(index * (len(values) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [values[index] for index in sorted(indices)]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bounded_refs(values: Sequence[str]) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return list(
        dict.fromkeys(
            value.strip()
            for value in values[:32]
            if isinstance(value, str) and value.strip()
        )
    )


def _candidate_boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "trail_existence_asserted": False,
        "passability_asserted": False,
        "legality_asserted": False,
        "safe_or_walkable": "not_determined",
        "human_review_required": True,
        "phase1_runtime_mutation_allowed": False,
        "safety_api_called": False,
    }
