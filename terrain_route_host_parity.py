"""Deterministic cross-host comparison for candidate-only TRH executions."""

from __future__ import annotations

import math
from typing import Any, Sequence


class TerrainRouteParityError(ValueError):
    """The two executions cannot be compared without guessing."""


_METRIC_KEYS = (
    "relative_cost",
    "distance_m",
    "elevation_gain_m",
    "elevation_loss_m",
    "max_slope_degrees",
    "median_slope_degrees",
    "high_cost_fraction",
    "drainage_pressure_fraction",
)


def compare_terrain_route_hosts(
    *,
    left_receipt: dict[str, Any],
    right_receipt: dict[str, Any],
    left_hypothesis: dict[str, Any],
    right_hypothesis: dict[str, Any],
    path_tolerance_m: float = 0.1,
    metric_abs_tolerance: float = 1e-6,
    corridor_relative_tolerance: float = 0.03,
) -> dict[str, Any]:
    """Compare model reproducibility, never passage, safety, or route truth."""

    tolerances = (
        float(path_tolerance_m),
        float(metric_abs_tolerance),
        float(corridor_relative_tolerance),
    )
    if not all(math.isfinite(value) and value >= 0 for value in tolerances):
        raise TerrainRouteParityError("parity tolerances must be finite and nonnegative")
    _validate_receipt(left_receipt, label="left")
    _validate_receipt(right_receipt, label="right")
    _validate_hypothesis_run(left_hypothesis, label="left")
    _validate_hypothesis_run(right_hypothesis, label="right")
    _validate_same_input_contract(left_receipt, right_receipt)
    _validate_hypothesis_dem_binding(left_receipt, left_hypothesis, label="left")
    _validate_hypothesis_dem_binding(right_receipt, right_hypothesis, label="right")

    left_by_strategy = _hypotheses_by_strategy(left_hypothesis)
    right_by_strategy = _hypotheses_by_strategy(right_hypothesis)
    if tuple(left_by_strategy) != tuple(right_by_strategy):
        raise TerrainRouteParityError("terrain route strategy sets or order differ")

    route_comparisons = [
        _compare_route(
            left_by_strategy[strategy],
            right_by_strategy[strategy],
            path_tolerance_m=tolerances[0],
            metric_abs_tolerance=tolerances[1],
        )
        for strategy in left_by_strategy
    ]
    corridor_comparison = _compare_corridor(
        left_by_strategy,
        right_by_strategy,
        relative_tolerance=tolerances[2],
    )
    left_engine = _engine_identity(left_hypothesis)
    right_engine = _engine_identity(right_hypothesis)
    engine_versions_exact = left_engine == right_engine
    within_tolerance = all(
        item["within_tolerance"] for item in route_comparisons
    ) and corridor_comparison["within_tolerance"]
    status = (
        "diverged"
        if not within_tolerance
        else "passed_exact_engine"
        if engine_versions_exact
        else "passed_with_engine_variance"
    )
    cross_host = (
        left_receipt["execution_host"] != right_receipt["execution_host"]
        or left_receipt["execution_architecture"]
        != right_receipt["execution_architecture"]
    )
    unknowns = []
    if not engine_versions_exact:
        unknowns.append("exact_engine_version_parity_unknown")
    unknowns.extend(
        (
            "field_conditions_unknown",
            "vegetation_unknown",
            "microterrain_unknown",
            "recent_landslide_unknown",
            "legal_access_unknown",
            "engineered_route_features_unknown",
        )
    )
    return {
        "schema_version": "scout_terrain_route_host_parity.v0_1",
        "status": status,
        "comparison_scope": "terrain_model_reproducibility_only",
        "input_contract_sha256": left_receipt["input_contract_sha256"],
        "source_dem_sha256s": left_receipt["source_dem_sha256s"],
        "terrain_parent_manifest_sha256": left_receipt[
            "terrain_parent_manifest_sha256"
        ],
        "left_host": {
            "name": left_receipt["execution_host"],
            "architecture": left_receipt["execution_architecture"],
            "engine": left_engine,
        },
        "right_host": {
            "name": right_receipt["execution_host"],
            "architecture": right_receipt["execution_architecture"],
            "engine": right_engine,
        },
        "cross_host_execution_proven": cross_host,
        "engine_versions_exact": engine_versions_exact,
        "tolerances": {
            "path_hausdorff_m": tolerances[0],
            "metric_absolute": tolerances[1],
            "corridor_relative": tolerances[2],
        },
        "route_comparisons": route_comparisons,
        "corridor_comparison": corridor_comparison,
        "unknowns": unknowns,
        "authority": "candidate_only",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
    }


def _validate_receipt(receipt: dict[str, Any], *, label: str) -> None:
    if (
        receipt.get("status") != "completed"
        or receipt.get("workflow_id") != "terrain_route_hypothesis.v1"
        or receipt.get("authority") != "candidate_only"
        or receipt.get("candidate_only") is not True
        or receipt.get("runtime_safety_truth") is not False
        or receipt.get("operational") is not False
        or receipt.get("safe_or_walkable") != "not_determined"
    ):
        raise TerrainRouteParityError(f"{label} receipt is not candidate-only completed TRH")
    for key in (
        "execution_host",
        "execution_architecture",
        "input_contract_sha256",
        "terrain_parent_manifest_sha256",
    ):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            raise TerrainRouteParityError(f"{label} receipt is missing {key}")
    hashes = receipt.get("source_dem_sha256s")
    if not isinstance(hashes, list) or not hashes:
        raise TerrainRouteParityError(f"{label} receipt has no source DEM hashes")


def _validate_hypothesis_run(payload: dict[str, Any], *, label: str) -> None:
    if (
        payload.get("status") != "completed"
        or payload.get("candidate_only") is not True
        or payload.get("runtime_safety_truth") is not False
        or payload.get("safe_or_walkable") != "not_determined"
    ):
        raise TerrainRouteParityError(f"{label} hypothesis run is not candidate-only")
    hypotheses = payload.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise TerrainRouteParityError(f"{label} hypothesis run is empty")
    for hypothesis in hypotheses:
        if (
            not isinstance(hypothesis, dict)
            or hypothesis.get("authority") != "candidate_only"
            or hypothesis.get("candidate_only") is not True
            or hypothesis.get("runtime_safety_truth") is not False
            or hypothesis.get("safe_or_walkable") != "not_determined"
        ):
            raise TerrainRouteParityError(
                f"{label} hypothesis violated the candidate-only boundary"
            )


def _validate_same_input_contract(
    left: dict[str, Any],
    right: dict[str, Any],
) -> None:
    fields = (
        "input_contract_sha256",
        "source_dem_sha256s",
        "terrain_parent_manifest_sha256",
    )
    if any(left.get(field) != right.get(field) for field in fields):
        raise TerrainRouteParityError("terrain route input contract differs between hosts")


def _validate_hypothesis_dem_binding(
    receipt: dict[str, Any],
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    expected = set(receipt["source_dem_sha256s"])
    for hypothesis in payload["hypotheses"]:
        provenance = hypothesis.get("provenance")
        dem_hash = provenance.get("dem_sha256") if isinstance(provenance, dict) else None
        if dem_hash not in expected:
            raise TerrainRouteParityError(
                f"{label} hypothesis is not bound to the receipt source DEM"
            )


def _hypotheses_by_strategy(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for hypothesis in payload["hypotheses"]:
        strategy = hypothesis.get("strategy")
        if not isinstance(strategy, str) or not strategy or strategy in result:
            raise TerrainRouteParityError("terrain route strategy identity is invalid")
        result[strategy] = hypothesis
    return result


def _compare_route(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    path_tolerance_m: float,
    metric_abs_tolerance: float,
) -> dict[str, Any]:
    left_coordinates = _coordinates(left)
    right_coordinates = _coordinates(right)
    hausdorff_m = _hausdorff_m(left_coordinates, right_coordinates)
    metric_deltas: dict[str, float] = {}
    for key in _METRIC_KEYS:
        try:
            left_value = float(left["metrics"][key])
            right_value = float(right["metrics"][key])
        except (KeyError, TypeError, ValueError) as exc:
            raise TerrainRouteParityError(f"terrain route metric {key} is invalid") from exc
        if not math.isfinite(left_value) or not math.isfinite(right_value):
            raise TerrainRouteParityError(f"terrain route metric {key} is not finite")
        metric_deltas[key] = abs(left_value - right_value)
    metrics_within = all(
        delta <= metric_abs_tolerance for delta in metric_deltas.values()
    )
    return {
        "strategy": left["strategy"],
        "left_vertex_count": len(left_coordinates),
        "right_vertex_count": len(right_coordinates),
        "hausdorff_m": hausdorff_m,
        "metric_absolute_deltas": metric_deltas,
        "path_within_tolerance": hausdorff_m <= path_tolerance_m,
        "metrics_within_tolerance": metrics_within,
        "within_tolerance": (
            hausdorff_m <= path_tolerance_m and metrics_within
        ),
    }


def _compare_corridor(
    left_by_strategy: dict[str, dict[str, Any]],
    right_by_strategy: dict[str, dict[str, Any]],
    *,
    relative_tolerance: float,
) -> dict[str, Any]:
    left_items = [item for item in left_by_strategy.values() if item.get("corridor")]
    right_items = [item for item in right_by_strategy.values() if item.get("corridor")]
    if len(left_items) != 1 or len(right_items) != 1:
        raise TerrainRouteParityError("each execution must contain one corridor profile")
    left_bands = left_items[0]["corridor"].get("bands")
    right_bands = right_items[0]["corridor"].get("bands")
    if not isinstance(left_bands, list) or not isinstance(right_bands, list):
        raise TerrainRouteParityError("terrain corridor bands are unavailable")
    if len(left_bands) != len(right_bands) or not left_bands:
        raise TerrainRouteParityError("terrain corridor band counts differ")
    comparisons = []
    for left, right in zip(left_bands, right_bands, strict=True):
        if (
            left.get("name") != right.get("name")
            or left.get("percentile") != right.get("percentile")
        ):
            raise TerrainRouteParityError("terrain corridor band identities differ")
        try:
            cell_delta = _relative_delta(
                float(left["cell_count"]),
                float(right["cell_count"]),
            )
            threshold_delta = _relative_delta(
                float(left["max_relative_corridor_cost"]),
                float(right["max_relative_corridor_cost"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TerrainRouteParityError("terrain corridor statistics are invalid") from exc
        comparisons.append(
            {
                "name": left["name"],
                "percentile": left["percentile"],
                "cell_count_relative_delta": cell_delta,
                "threshold_relative_delta": threshold_delta,
                "within_tolerance": (
                    cell_delta <= relative_tolerance
                    and threshold_delta <= relative_tolerance
                ),
            }
        )
    return {
        "bands": comparisons,
        "within_tolerance": all(item["within_tolerance"] for item in comparisons),
    }


def _coordinates(hypothesis: dict[str, Any]) -> list[tuple[float, float]]:
    try:
        raw = hypothesis["best_path"]["coordinates"]
    except (KeyError, TypeError) as exc:
        raise TerrainRouteParityError("terrain route geometry is unavailable") from exc
    if not isinstance(raw, list) or not 2 <= len(raw) <= 5_000:
        raise TerrainRouteParityError("terrain route geometry size is outside bounds")
    coordinates: list[tuple[float, float]] = []
    for coordinate in raw:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            raise TerrainRouteParityError("terrain route coordinate is invalid")
        lon, lat = float(coordinate[0]), float(coordinate[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise TerrainRouteParityError("terrain route coordinate is not finite")
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise TerrainRouteParityError("terrain route coordinate is outside WGS84")
        coordinates.append((lon, lat))
    return coordinates


def _hausdorff_m(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
) -> float:
    def directed(
        source: Sequence[tuple[float, float]],
        destination: Sequence[tuple[float, float]],
    ) -> float:
        return max(
            min(_wgs84_distance_m(point, candidate) for candidate in destination)
            for point in source
        )

    return max(directed(left, right), directed(right, left))


def _wgs84_distance_m(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    mean_latitude = math.radians((left[1] + right[1]) / 2.0)
    dx = (left[0] - right[0]) * 111_320.0 * math.cos(mean_latitude)
    dy = (left[1] - right[1]) * 110_540.0
    return math.hypot(dx, dy)


def _relative_delta(left: float, right: float) -> float:
    if not math.isfinite(left) or not math.isfinite(right):
        raise ValueError("relative comparison requires finite values")
    return abs(left - right) / max(abs(left), abs(right), 1.0)


def _engine_identity(payload: dict[str, Any]) -> dict[str, str]:
    first = payload["hypotheses"][0].get("provenance")
    if not isinstance(first, dict):
        raise TerrainRouteParityError("terrain route engine provenance is unavailable")
    keys = (
        "qgis_version",
        "grass_version",
        "algorithm_version",
        "cost_model_version",
    )
    identity = {key: str(first.get(key) or "unavailable") for key in keys}
    for hypothesis in payload["hypotheses"][1:]:
        provenance = hypothesis.get("provenance")
        if not isinstance(provenance, dict):
            raise TerrainRouteParityError("terrain route engine provenance is unavailable")
        if any(str(provenance.get(key) or "unavailable") != identity[key] for key in keys):
            raise TerrainRouteParityError("engine provenance differs within one execution")
    return identity
