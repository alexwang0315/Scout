"""Fail-closed expert-reference evaluation for terrain candidate geometry.

This module measures candidate geometry; it does not create expert truth and it
never promotes a terrain result into navigation, notification, or safety
authority. Hard thresholds are deliberately external inputs so a synthetic
fixture cannot silently become the product acceptance standard.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from navigation_terrain_annotations import (
    TerrainAnnotationError,
    normalize_expert_terrain_annotations,
)

Point = tuple[float, float]

_REQUIRED_THRESHOLDS = (
    "lateral_rmse_m_max",
    "h95_m_max",
    "frechet_m_max",
    "component_count_error_max",
    "branch_count_error_max",
    "junction_count_error_max",
    "hydrologic_violation_fraction_max",
    "grid_axis_quantized_fraction_max",
)


def compare_polylines(
    candidate: Sequence[Sequence[float]],
    reference: Sequence[Sequence[float]],
    *,
    sample_spacing_m: float = 10.0,
) -> dict[str, float]:
    """Return deterministic lateral, H95, Hausdorff, and Fréchet metrics."""

    spacing = _positive_number(sample_spacing_m)
    if spacing is None:
        raise ValueError("sample_spacing_m must be positive")
    candidate_line = _line(candidate, "candidate")
    reference_line = _line(reference, "reference")
    candidate_samples = _resample(candidate_line, spacing)
    reference_samples = _resample(reference_line, spacing)
    reference_to_candidate = [
        _point_to_line_distance(point, candidate_line)
        for point in reference_samples
    ]
    candidate_to_reference = [
        _point_to_line_distance(point, reference_line)
        for point in candidate_samples
    ]
    symmetric = [*reference_to_candidate, *candidate_to_reference]
    lateral_rmse = math.sqrt(
        sum(distance * distance for distance in reference_to_candidate)
        / len(reference_to_candidate)
    )
    return {
        "lateral_rmse_m": round(lateral_rmse, 4),
        "h95_m": round(_percentile(symmetric, 0.95), 4),
        "hausdorff_m": round(max(symmetric), 4),
        "discrete_frechet_m": round(
            _discrete_frechet(candidate_samples, reference_samples),
            4,
        ),
    }


def build_terrain_validation_receipt(
    hierarchy: Mapping[str, Any],
    reference_sets: Sequence[Mapping[str, Any]],
    *,
    acceptance_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure expert references and return a non-operational gate receipt."""

    if not _candidate_boundary_is_valid(hierarchy.get("boundary")):
        return _blocked_receipt(
            "invalid_candidate_boundary",
            reference_errors=[],
        )
    normalized_sets, reference_errors = _normalize_reference_sets(reference_sets)
    blind_sets = [
        item for item in normalized_sets if item.get("blind_validation_eligible")
    ]
    qualified_sets, qualified_cases = _qualified_independent_sets(blind_sets)
    coverage = _reference_coverage(
        normalized_sets,
        blind_sets,
        qualified_sets,
        qualified_cases,
        reference_errors,
    )
    if not qualified_sets:
        return _blocked_receipt(
            "geometry_reference_validation_missing",
            reference_errors=reference_errors,
            reference_coverage=coverage,
        )

    comparisons, missing_matches = _compare_reference_sets(
        hierarchy,
        qualified_sets,
    )
    aggregate_metrics = _aggregate_geometry_metrics(comparisons)
    topology = _topology_evaluation(hierarchy, qualified_sets)
    hydrology = _hydrology_evaluation(hierarchy)
    orientation = _orientation_evaluation(hierarchy)
    disagreement = _expert_disagreement(qualified_sets)
    common = {
        "schema_version": "scout_navigation_terrain_validation_receipt.v0",
        "artifact_kind": "navigation_terrain_validation_receipt",
        "output_role": "candidate_geometry_validation_receipt",
        "baseline_status": "measured",
        "reference_coverage": coverage,
        "reference_comparisons": comparisons,
        "expert_disagreement": disagreement,
        "aggregate_metrics": aggregate_metrics,
        "topology": topology,
        "hydrology": hydrology,
        "orientation": orientation,
        "lineage": _lineage(hierarchy, qualified_sets, acceptance_policy),
        "reference_errors": reference_errors,
        "missing_candidate_match_count": missing_matches,
        "gate_mode": "shadow_only",
        "operational_authority": False,
        "effect_scope": "none",
        "event_unlocks": _closed_event_unlocks(),
        "boundary": _boundary(),
    }
    policy, policy_errors = _normalize_acceptance_policy(acceptance_policy)
    if policy is None:
        return {
            **common,
            "status": "blocked",
            "validation_state": "blocked_pending_acceptance_policy",
            "blocked_reason": "approved_reference_bound_thresholds_missing",
            "geometry_presentation_eligible": False,
            "event_source_mode": "prohibited",
            "acceptance_policy": None,
            "policy_errors": policy_errors,
            "failed_thresholds": [],
        }

    observed = {
        "lateral_rmse_m_max": aggregate_metrics.get("lateral_rmse_m"),
        "h95_m_max": aggregate_metrics.get("h95_m"),
        "frechet_m_max": aggregate_metrics.get("discrete_frechet_m"),
        "component_count_error_max": topology["component_count_error"],
        "branch_count_error_max": topology["branch_count_error"],
        "junction_count_error_max": topology["junction_count_error"],
        "hydrologic_violation_fraction_max": hydrology["violation_fraction"],
        "grid_axis_quantized_fraction_max": orientation[
            "grid_axis_quantized_fraction"
        ],
    }
    failed_thresholds = [
        threshold
        for threshold in _REQUIRED_THRESHOLDS
        if observed.get(threshold) is None
        or float(observed[threshold]) > float(policy["thresholds"][threshold])
    ]
    if missing_matches:
        failed_thresholds.append("missing_candidate_geometry")
    passed = not failed_thresholds
    return {
        **common,
        "status": "pass" if passed else "fail",
        "validation_state": (
            "validated_candidate_geometry"
            if passed
            else "failed_candidate_geometry"
        ),
        "blocked_reason": None if passed else "reference_bound_threshold_failure",
        "geometry_presentation_eligible": passed,
        "event_source_mode": (
            "prohibited_pending_event_type_gate" if passed else "prohibited"
        ),
        "acceptance_policy": policy,
        "policy_errors": policy_errors,
        "observed_threshold_values": observed,
        "failed_thresholds": failed_thresholds,
    }


def _normalize_reference_sets(
    reference_sets: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized = []
    errors = []
    for index, payload in enumerate(reference_sets):
        try:
            if (
                isinstance(payload, dict)
                and payload.get("artifact_kind") == "expert_terrain_annotations"
                and isinstance(payload.get("protocol"), dict)
            ):
                normalized.append(dict(payload))
            else:
                normalized.append(
                    normalize_expert_terrain_annotations(dict(payload))
                )
        except (TerrainAnnotationError, TypeError, ValueError) as exc:
            errors.append(f"reference_sets[{index}]: {exc}")
    return normalized, errors


def _qualified_independent_sets(
    blind_sets: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for item in blind_sets:
        case_id = str(item.get("protocol", {}).get("reference_case_id") or "")
        if case_id:
            by_case.setdefault(case_id, []).append(item)
    qualified_cases = [
        case_id
        for case_id, items in by_case.items()
        if len(
            {
                str(item.get("protocol", {}).get("annotator_id") or "")
                for item in items
            }
            - {""}
        )
        >= 2
    ]
    qualified = [item for case in qualified_cases for item in by_case[case]]
    return qualified, sorted(qualified_cases)


def _reference_coverage(
    normalized_sets: Sequence[dict[str, Any]],
    blind_sets: Sequence[dict[str, Any]],
    qualified_sets: Sequence[dict[str, Any]],
    qualified_cases: Sequence[str],
    errors: Sequence[str],
) -> dict[str, Any]:
    return {
        "provided_set_count": len(normalized_sets) + len(errors),
        "normalized_set_count": len(normalized_sets),
        "blind_eligible_set_count": len(blind_sets),
        "qualified_set_count": len(qualified_sets),
        "qualified_case_count": len(qualified_cases),
        "qualified_case_ids": list(qualified_cases),
        "independent_annotator_count": len(
            {
                str(item.get("protocol", {}).get("annotator_id") or "")
                for item in qualified_sets
            }
            - {""}
        ),
        "minimum_independent_annotators_per_case": 2,
        "normalization_error_count": len(errors),
    }


def _compare_reference_sets(
    hierarchy: Mapping[str, Any],
    reference_sets: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    edges = [item for item in hierarchy.get("edges", []) if isinstance(item, dict)]
    comparisons = []
    missing = 0
    for reference_set in reference_sets:
        protocol = reference_set.get("protocol", {})
        for annotation in reference_set.get("annotations", []):
            if (
                not isinstance(annotation, dict)
                or annotation.get("geometry_type") != "LineString"
                or annotation.get("ambiguous") is True
            ):
                continue
            reference_line = annotation.get("coordinates_twd97")
            expected_kind = str(annotation.get("terrain_edge_kind") or "")
            candidates = [
                edge
                for edge in edges
                if edge.get("kind") == expected_kind
                and isinstance(edge.get("coordinates_twd97"), list)
            ]
            scored = []
            for edge in candidates:
                try:
                    metrics = compare_polylines(
                        edge["coordinates_twd97"],
                        reference_line,
                    )
                except (TypeError, ValueError):
                    continue
                scored.append((metrics["h95_m"], str(edge.get("id") or ""), metrics))
            if not scored:
                missing += 1
                comparisons.append(
                    {
                        "reference_set_id": reference_set.get("annotation_set_id"),
                        "reference_case_id": protocol.get("reference_case_id"),
                        "annotator_id": protocol.get("annotator_id"),
                        "annotation_id": annotation.get("id"),
                        "terrain_edge_kind": expected_kind,
                        "matched_candidate_edge_id": None,
                        "metrics": None,
                    }
                )
                continue
            _score, edge_id, metrics = min(scored)
            comparisons.append(
                {
                    "reference_set_id": reference_set.get("annotation_set_id"),
                    "reference_case_id": protocol.get("reference_case_id"),
                    "annotator_id": protocol.get("annotator_id"),
                    "annotation_id": annotation.get("id"),
                    "terrain_edge_kind": expected_kind,
                    "matched_candidate_edge_id": edge_id,
                    "uncertainty_half_width_m": annotation.get(
                        "uncertainty_half_width_m"
                    ),
                    "metrics": metrics,
                }
            )
    return comparisons, missing


def _aggregate_geometry_metrics(
    comparisons: Sequence[dict[str, Any]],
) -> dict[str, float | None]:
    metric_names = (
        "lateral_rmse_m",
        "h95_m",
        "hausdorff_m",
        "discrete_frechet_m",
    )
    return {
        name: (
            round(
                max(
                    float(item["metrics"][name])
                    for item in comparisons
                    if isinstance(item.get("metrics"), dict)
                ),
                4,
            )
            if any(isinstance(item.get("metrics"), dict) for item in comparisons)
            else None
        )
        for name in metric_names
    }


def _topology_evaluation(
    hierarchy: Mapping[str, Any],
    reference_sets: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    candidate = _candidate_topology_signature(hierarchy)
    references = [_reference_topology_signature(item) for item in reference_sets]
    return {
        "candidate": candidate,
        "references": references,
        "component_count_error": max(
            (abs(candidate["component_count"] - item["component_count"]) for item in references),
            default=0,
        ),
        "branch_count_error": max(
            (abs(candidate["branch_count"] - item["branch_count"]) for item in references),
            default=0,
        ),
        "junction_count_error": max(
            (abs(candidate["junction_count"] - item["junction_count"]) for item in references),
            default=0,
        ),
    }


def _candidate_topology_signature(hierarchy: Mapping[str, Any]) -> dict[str, int]:
    edges = [item for item in hierarchy.get("edges", []) if isinstance(item, dict)]
    nodes: set[str] = set()
    adjacency: dict[str, set[str]] = {}
    for index, edge in enumerate(edges):
        start = str(edge.get("from") or f"edge-{index}-start")
        end = str(edge.get("to") or f"edge-{index}-end")
        nodes.update((start, end))
        adjacency.setdefault(start, set()).add(end)
        adjacency.setdefault(end, set()).add(start)
    return {
        "component_count": _component_count(nodes, adjacency),
        "branch_count": len(edges),
        "junction_count": sum(len(adjacency.get(node, set())) >= 3 for node in nodes),
    }


def _reference_topology_signature(reference_set: Mapping[str, Any]) -> dict[str, int]:
    annotations = [
        item
        for item in reference_set.get("annotations", [])
        if isinstance(item, dict)
        and item.get("geometry_type") == "LineString"
        and item.get("ambiguous") is not True
    ]
    ids = {str(item.get("id") or "") for item in annotations} - {""}
    adjacency = {annotation_id: set() for annotation_id in ids}
    junction_ids = set()
    for item in annotations:
        annotation_id = str(item.get("id") or "")
        topology = item.get("topology", {})
        if not isinstance(topology, dict):
            continue
        junction_id = topology.get("junction_id")
        if junction_id:
            junction_ids.add(str(junction_id))
        for target in topology.get("connected_to", []):
            if target in ids and target != annotation_id:
                adjacency[annotation_id].add(target)
                adjacency[target].add(annotation_id)
    return {
        "component_count": _component_count(ids, adjacency),
        "branch_count": len(annotations),
        "junction_count": len(junction_ids),
    }


def _component_count(nodes: set[str], adjacency: Mapping[str, set[str]]) -> int:
    count = 0
    remaining = set(nodes)
    while remaining:
        count += 1
        stack = [remaining.pop()]
        while stack:
            node = stack.pop()
            unseen = adjacency.get(node, set()) & remaining
            remaining -= unseen
            stack.extend(unseen)
    return count


def _hydrology_evaluation(hierarchy: Mapping[str, Any]) -> dict[str, Any]:
    drainage_edges = [
        item
        for item in hierarchy.get("edges", [])
        if isinstance(item, dict)
        and item.get("kind") in {"drainage_trunk", "tributary"}
    ]
    violations = []
    for edge in drainage_edges:
        profile = edge.get("conditioned_elevation_profile_m")
        monotonic_elevation = bool(
            isinstance(profile, list)
            and len(profile) >= 2
            and all(
                _finite_number(downstream) is not None
                and _finite_number(upstream) is not None
                and float(downstream) <= float(upstream) + 0.1
                for upstream, downstream in zip(profile, profile[1:])
            )
        )
        accumulation_start = _finite_number(edge.get("flow_accumulation_start"))
        accumulation_end = _finite_number(edge.get("flow_accumulation_end"))
        monotonic_accumulation = bool(
            accumulation_start is not None
            and accumulation_end is not None
            and accumulation_end >= accumulation_start
        )
        if not (
            edge.get("flow_supported") is True
            and monotonic_elevation
            and monotonic_accumulation
        ):
            violations.append(str(edge.get("id") or "unknown"))
    return {
        "inspected_edge_count": len(drainage_edges),
        "violation_count": len(violations),
        "violation_fraction": (
            round(len(violations) / len(drainage_edges), 6)
            if drainage_edges
            else 0.0
        ),
        "violating_edge_ids": violations[:64],
    }


def _orientation_evaluation(hierarchy: Mapping[str, Any]) -> dict[str, Any]:
    angles = []
    for edge in hierarchy.get("edges", []):
        if not isinstance(edge, dict):
            continue
        try:
            line = _line(edge.get("coordinates_twd97"), "candidate edge")
        except (TypeError, ValueError):
            continue
        angles.extend(
            math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0
            for a, b in zip(line, line[1:])
            if math.dist(a, b) > 1e-9
        )
    quantized = sum(_grid_axis_distance(angle) <= 2.0 for angle in angles)
    return {
        "segment_count": len(angles),
        "grid_axis_quantized_fraction": (
            round(quantized / len(angles), 6) if angles else 0.0
        ),
        "orientation_bin_counts": _orientation_bins(angles),
    }


def _expert_disagreement(reference_sets: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[tuple[str, Sequence[Sequence[float]]]]] = {}
    for reference_set in reference_sets:
        case_id = str(reference_set.get("protocol", {}).get("reference_case_id") or "")
        annotator_id = str(reference_set.get("protocol", {}).get("annotator_id") or "")
        for item in reference_set.get("annotations", []):
            if (
                isinstance(item, dict)
                and item.get("geometry_type") == "LineString"
                and item.get("ambiguous") is not True
            ):
                grouped.setdefault(
                    (case_id, str(item.get("terrain_edge_kind") or "")),
                    [],
                ).append((annotator_id, item.get("coordinates_twd97")))
    comparisons = []
    for (case_id, kind), lines in grouped.items():
        for index, (annotator_a, line_a) in enumerate(lines):
            for annotator_b, line_b in lines[index + 1 :]:
                if not annotator_a or annotator_a == annotator_b:
                    continue
                comparisons.append(
                    {
                        "reference_case_id": case_id,
                        "terrain_edge_kind": kind,
                        "annotators": [annotator_a, annotator_b],
                        "metrics": compare_polylines(line_a, line_b),
                    }
                )
    return {
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "maximum_h95_m": max(
            (item["metrics"]["h95_m"] for item in comparisons),
            default=None,
        ),
    }


def _normalize_acceptance_policy(
    value: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if value is None:
        return None, ["acceptance policy is missing"]
    errors = []
    if value.get("schema_version") != "scout_navigation_terrain_acceptance_policy.v0":
        errors.append("acceptance policy schema_version is unsupported")
    if value.get("status") != "approved":
        errors.append("acceptance policy is not approved")
    policy_id = str(value.get("policy_id") or "").strip()
    baseline_ref = str(value.get("baseline_receipt_ref") or "").strip()
    approved_by = [
        str(item).strip()
        for item in value.get("approved_by", [])
        if str(item).strip()
    ] if isinstance(value.get("approved_by"), list) else []
    if not policy_id:
        errors.append("acceptance policy policy_id is missing")
    if not baseline_ref:
        errors.append("acceptance policy baseline_receipt_ref is missing")
    if len(set(approved_by)) < 2:
        errors.append("acceptance policy requires two independent approvers")
    raw_thresholds = value.get("thresholds")
    thresholds = {}
    if not isinstance(raw_thresholds, Mapping):
        errors.append("acceptance policy thresholds are missing")
    else:
        for name in _REQUIRED_THRESHOLDS:
            number = _nonnegative_number(raw_thresholds.get(name))
            if number is None:
                errors.append(f"acceptance policy threshold {name} is invalid")
            else:
                thresholds[name] = number
    if errors:
        return None, errors
    return {
        "schema_version": value["schema_version"],
        "policy_id": policy_id,
        "status": "approved",
        "baseline_receipt_ref": baseline_ref,
        "approved_by": list(dict.fromkeys(approved_by)),
        "thresholds": thresholds,
    }, []


def _line(value: Any, field_name: str) -> list[Point]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a coordinate sequence")
    points = []
    for item in value:
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) < 2:
            raise ValueError(f"{field_name} contains an invalid coordinate")
        x = _finite_number(item[0])
        y = _finite_number(item[1])
        if x is None or y is None:
            raise ValueError(f"{field_name} contains a non-finite coordinate")
        point = (x, y)
        if not points or point != points[-1]:
            points.append(point)
    if len(points) < 2:
        raise ValueError(f"{field_name} must contain two distinct points")
    return points


def _resample(line: Sequence[Point], spacing_m: float) -> list[Point]:
    lengths = [math.dist(a, b) for a, b in zip(line, line[1:])]
    total = sum(lengths)
    if total <= 1e-9:
        return [line[0], line[-1]]
    count = max(2, min(256, int(math.ceil(total / spacing_m)) + 1))
    targets = [total * index / (count - 1) for index in range(count)]
    result = []
    segment_index = 0
    traversed = 0.0
    for target in targets:
        while (
            segment_index < len(lengths) - 1
            and traversed + lengths[segment_index] < target
        ):
            traversed += lengths[segment_index]
            segment_index += 1
        segment_length = lengths[segment_index]
        ratio = 0.0 if segment_length <= 1e-9 else (target - traversed) / segment_length
        a, b = line[segment_index], line[segment_index + 1]
        result.append((a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio))
    return result


def _point_to_line_distance(point: Point, line: Sequence[Point]) -> float:
    return min(
        _point_to_segment_distance(point, start, end)
        for start, end in zip(line, line[1:])
    )


def _point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    denominator = dx * dx + dy * dy
    if denominator <= 1e-18:
        return math.dist(point, start)
    ratio = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator),
    )
    projected = (start[0] + ratio * dx, start[1] + ratio * dy)
    return math.dist(point, projected)


def _discrete_frechet(a: Sequence[Point], b: Sequence[Point]) -> float:
    previous = [math.inf] * len(b)
    for index_a, point_a in enumerate(a):
        current = [math.inf] * len(b)
        for index_b, point_b in enumerate(b):
            distance = math.dist(point_a, point_b)
            if index_a == 0 and index_b == 0:
                current[index_b] = distance
            elif index_a == 0:
                current[index_b] = max(current[index_b - 1], distance)
            elif index_b == 0:
                current[index_b] = max(previous[index_b], distance)
            else:
                current[index_b] = max(
                    min(previous[index_b], previous[index_b - 1], current[index_b - 1]),
                    distance,
                )
        previous = current
    return previous[-1]


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    ratio = position - lower
    return ordered[lower] * (1.0 - ratio) + ordered[upper] * ratio


def _grid_axis_distance(angle_degrees: float) -> float:
    angle = angle_degrees % 180.0
    return min(abs(angle - axis) for axis in (0.0, 45.0, 90.0, 135.0, 180.0))


def _orientation_bins(angles: Sequence[float]) -> dict[str, int]:
    bins = {f"{start:03d}-{start + 15:03d}": 0 for start in range(0, 180, 15)}
    for angle in angles:
        start = min(165, int(angle // 15) * 15)
        bins[f"{start:03d}-{start + 15:03d}"] += 1
    return bins


def _lineage(
    hierarchy: Mapping[str, Any],
    reference_sets: Sequence[dict[str, Any]],
    acceptance_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    grid = hierarchy.get("grid", {}) if isinstance(hierarchy.get("grid"), Mapping) else {}
    return {
        "hierarchy_schema_version": hierarchy.get("schema_version"),
        "extractor_methods": dict(hierarchy.get("method", {}))
        if isinstance(hierarchy.get("method"), Mapping)
        else {},
        "dem_crs": grid.get("crs"),
        "dem_resolution_m": grid.get("cell_resolution_m"),
        "reference_set_ids": [item.get("annotation_set_id") for item in reference_sets],
        "acceptance_policy_id": (
            acceptance_policy.get("policy_id")
            if isinstance(acceptance_policy, Mapping)
            else None
        ),
        "join_policy": None,
        "event_semantics": "not_evaluated",
    }


def _blocked_receipt(
    reason: str,
    *,
    reference_errors: Sequence[str],
    reference_coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "scout_navigation_terrain_validation_receipt.v0",
        "artifact_kind": "navigation_terrain_validation_receipt",
        "status": "blocked",
        "validation_state": "blocked_pending_reference",
        "blocked_reason": reason,
        "baseline_status": "not_measured",
        "geometry_presentation_eligible": False,
        "event_source_mode": "prohibited",
        "gate_mode": "shadow_only",
        "operational_authority": False,
        "effect_scope": "none",
        "reference_coverage": dict(reference_coverage or {}),
        "reference_comparisons": [],
        "aggregate_metrics": {},
        "reference_errors": list(reference_errors),
        "event_unlocks": _closed_event_unlocks(),
        "boundary": _boundary(),
    }


def _candidate_boundary_is_valid(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("candidate_only") is True
        and value.get("runtime_safety_truth") is False
        and value.get("safe_or_walkable") == "not_determined"
    )


def _closed_event_unlocks() -> dict[str, bool]:
    return {"crossing": False, "wrong_way": False, "recovery": False}


def _boundary() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "human_review_required": True,
        "phase1_runtime_mutation_allowed": False,
        "operational_authority": False,
        "effect_scope": "none",
    }


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_number(value: Any) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


def _nonnegative_number(value: Any) -> float | None:
    number = _finite_number(value)
    return number if number is not None and number >= 0 else None
