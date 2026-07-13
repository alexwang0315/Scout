from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from cwa_precipitation_grid import CwaPrecipitationGrid
from rainfall_grid_freshness import evaluate_precipitation_freshness


def build_route_precipitation_trend(
    *,
    qpe_grid: CwaPrecipitationGrid,
    qpf_grid: CwaPrecipitationGrid,
    route_points: Sequence[tuple[float, float]],
    current_position: Mapping[str, Any] | None = None,
    target_position: Mapping[str, Any] | None = None,
    route_buffer_m: float = 1_500.0,
    evaluated_at: str | datetime | None = None,
) -> dict[str, Any]:
    if qpe_grid.grid_kind != "qpe_past_1h" or qpf_grid.grid_kind != "qpf_next_1h":
        raise ValueError("route precipitation trend requires QPE then QPF grids")
    _validate_grid_alignment(qpe_grid, qpf_grid)
    evaluated = (
        _aware_datetime(evaluated_at)
        if evaluated_at is not None
        else max(qpe_grid.fetched_at, qpf_grid.fetched_at)
    )
    current = _position_summary(
        qpe_grid,
        qpf_grid,
        current_position,
        include_id=False,
    )
    target = _position_summary(
        qpe_grid,
        qpf_grid,
        target_position,
        include_id=True,
    )
    if (
        not math.isfinite(route_buffer_m)
        or route_buffer_m <= 0
        or route_buffer_m > 20_000
    ):
        raise ValueError("invalid route precipitation buffer")
    corridor = _corridor_summary(
        qpe_grid,
        qpf_grid,
        route_points,
        route_buffer_m=route_buffer_m,
    )
    provided = int(current_position is not None) + int(target_position is not None)
    status = (
        "ready"
        if provided == 2
        else (
            "awaiting_position_and_target"
            if provided == 0
            else "awaiting_position_or_target"
        )
    )
    coverage_ratio = corridor["coveredRouteSampleCount"] / max(
        corridor["sampleCount"],
        1,
    )
    location_factor = 1.0 if provided == 2 else 0.8
    datum_factor = (
        0.82
        if max(qpe_grid.coordinate_uncertainty_m, qpf_grid.coordinate_uncertainty_m)
        else 0.95
    )
    excess_delay = max(
        0,
        max(qpe_grid.data_delay_minutes, qpf_grid.data_delay_minutes)
        - max(qpe_grid.expected_delay_minutes, qpf_grid.expected_delay_minutes),
    )
    delay_factor = max(0.3, 1 - excess_delay / 60)
    point_penalty = (
        0.7
        if any(
            item["status"] not in {"ready", "not_provided"}
            for item in (current, target)
        )
        else 1.0
    )
    qpe_freshness = evaluate_precipitation_freshness(
        grid_kind=qpe_grid.grid_kind,
        source_timestamp=qpe_grid.source_timestamp,
        valid_until=qpe_grid.valid_until,
        evaluated_at=evaluated,
    )
    qpf_freshness = evaluate_precipitation_freshness(
        grid_kind=qpf_grid.grid_kind,
        source_timestamp=qpf_grid.source_timestamp,
        valid_until=qpf_grid.valid_until,
        evaluated_at=evaluated,
    )
    stale_data = any(
        item["status"] != "current" for item in (qpe_freshness, qpf_freshness)
    )
    if stale_data:
        status = "stale_data"
    confidence = (
        0.0
        if stale_data
        else round(
            min(
                0.95,
                coverage_ratio
                * location_factor
                * datum_factor
                * delay_factor
                * point_penalty,
            ),
            2,
        )
    )
    return {
        "schemaVersion": "route_precipitation_trend.v1",
        "artifactKind": "route_precipitation_trend",
        "status": status,
        "evaluatedAt": evaluated.isoformat(),
        "currentPosition": current,
        "target": target,
        "corridor": corridor,
        "sourceTimestamps": {
            "past1hQpe": qpe_grid.source_timestamp.isoformat(),
            "next1hQpf": qpf_grid.source_timestamp.isoformat(),
        },
        "validWindows": {
            "past1hQpe": [
                qpe_grid.valid_from.isoformat(),
                qpe_grid.valid_until.isoformat(),
            ],
            "next1hQpf": [
                qpf_grid.valid_from.isoformat(),
                qpf_grid.valid_until.isoformat(),
            ],
        },
        "dataDelayMinutes": max(
            qpe_grid.data_delay_minutes, qpf_grid.data_delay_minutes
        ),
        "dataFreshness": {
            "status": "stale" if stale_data else "current",
            "qpfExpired": qpf_freshness["reason"] == "expired",
            "qpeStale": qpe_freshness["reason"] == "expired",
            "futureSourceTimestamp": any(
                item["reason"] == "future_source"
                for item in (qpe_freshness, qpf_freshness)
            ),
        },
        "confidence": confidence,
        "boundary": {
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "positionAccessRequiresApproval": True,
            "rawCoordinatesPersisted": False,
            "raspberryPiGridProcessing": False,
            "mobileGridProcessing": False,
        },
    }


def sample_grid_point(
    grid: CwaPrecipitationGrid,
    *,
    lat: float,
    lon: float,
) -> tuple[float | None, str]:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("position coordinates must be finite")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("position coordinates outside valid range")
    west, south, east, north = grid.bounds_wgs84
    if lon < west or lon >= east or lat < south or lat >= north:
        return None, "outside_grid"
    column = min(grid.width - 1, int((lon - west) / (east - west) * grid.width))
    row = min(grid.height - 1, int((north - lat) / (north - south) * grid.height))
    value = grid.values[row][column]
    return (value, "ready") if value is not None else (None, "missing_cell")


def _position_summary(
    qpe_grid: CwaPrecipitationGrid,
    qpf_grid: CwaPrecipitationGrid,
    position: Mapping[str, Any] | None,
    *,
    include_id: bool,
) -> dict[str, Any]:
    if position is None:
        return {
            "status": "not_provided",
            "past1hMm": None,
            "next1hMm": None,
            "trend": "unknown",
        }
    lat = _coordinate(position.get("lat"), "lat", -90, 90)
    lon = _coordinate(position.get("lon"), "lon", -180, 180)
    if not include_id:
        observed_at = position.get("observedAt")
        if observed_at is not None:
            observed = _aware_datetime(observed_at)
            reference = max(qpe_grid.fetched_at, qpf_grid.fetched_at)
            if observed < reference - timedelta(hours=24):
                raise ValueError("current position observation is stale")
            if observed > reference + timedelta(minutes=15):
                raise ValueError("current position observation is in the future")
        accuracy = position.get("accuracyM")
        if accuracy is not None and (
            _coordinate(accuracy, "accuracyM", 0, 100_000) < 0
        ):
            raise ValueError("invalid accuracyM")
    qpe, qpe_status = sample_grid_point(qpe_grid, lat=lat, lon=lon)
    qpf, qpf_status = sample_grid_point(qpf_grid, lat=lat, lon=lon)
    status = qpe_status if qpe_status != "ready" else qpf_status
    summary: dict[str, Any] = {
        "status": status,
        "past1hMm": qpe,
        "next1hMm": qpf,
        "qpeToQpfDeltaMm": round(qpf - qpe, 2)
        if qpe is not None and qpf is not None
        else None,
        "trend": _trend(qpe, qpf),
    }
    if include_id:
        target_id = str(position.get("id", "")).strip()
        if not target_id:
            raise ValueError("target id is required")
        summary["id"] = target_id[:128]
    return summary


def _corridor_summary(
    qpe_grid: CwaPrecipitationGrid,
    qpf_grid: CwaPrecipitationGrid,
    route_points: Sequence[tuple[float, float]],
    *,
    route_buffer_m: float,
) -> dict[str, Any]:
    sampled_points = _densify_route(route_points, max_points=2_000)
    qpe_cells: dict[tuple[int, int], float] = {}
    qpf_cells: dict[tuple[int, int], float] = {}
    covered_route_sample_count = 0
    for lat, lon in sampled_points:
        qpe_sample = _sample_grid_neighborhood(
            qpe_grid,
            lat=lat,
            lon=lon,
            radius_m=route_buffer_m,
        )
        qpf_sample = _sample_grid_neighborhood(
            qpf_grid,
            lat=lat,
            lon=lon,
            radius_m=route_buffer_m,
        )
        if qpe_sample.keys() & qpf_sample.keys():
            covered_route_sample_count += 1
        qpe_cells.update(qpe_sample)
        qpf_cells.update(qpf_sample)
    paired = [
        (qpe_cells[key], qpf_cells[key]) for key in qpe_cells.keys() & qpf_cells.keys()
    ]
    qpf_values = list(qpf_cells.values())
    qpf_sorted = sorted(qpf_values)
    return {
        "sampleCount": len(sampled_points),
        "sampledGridCellCount": len(qpe_cells.keys() | qpf_cells.keys()),
        "pairedSampleCount": len(paired),
        "coveredRouteSampleCount": covered_route_sample_count,
        "routeBufferM": route_buffer_m,
        "meanPast1hMm": _rounded_mean([item[0] for item in paired]),
        "meanNext1hMm": _rounded_mean([item[1] for item in paired]),
        "maxNext1hMm": max(qpf_values) if qpf_values else None,
        "p95Next1hMm": _percentile(qpf_sorted, 0.95),
        "heavySampleCount": sum(value >= 10 for value in qpf_values),
        "trend": _trend(
            _rounded_mean([item[0] for item in paired]),
            _rounded_mean([item[1] for item in paired]),
        ),
    }


def _validate_grid_alignment(
    qpe_grid: CwaPrecipitationGrid,
    qpf_grid: CwaPrecipitationGrid,
) -> None:
    if (qpe_grid.width, qpe_grid.height) != (qpf_grid.width, qpf_grid.height):
        raise ValueError("QPE and QPF grid dimensions do not align")
    if not math.isclose(
        qpe_grid.resolution_degrees,
        qpf_grid.resolution_degrees,
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise ValueError("QPE and QPF grid resolution does not align")
    if any(
        not math.isclose(left, right, rel_tol=0, abs_tol=1e-6)
        for left, right in zip(qpe_grid.bounds_wgs84, qpf_grid.bounds_wgs84)
    ):
        raise ValueError("QPE and QPF grid bounds do not align")
    timestamp_gap = abs(
        (qpe_grid.source_timestamp - qpf_grid.source_timestamp).total_seconds()
    )
    if (
        timestamp_gap
        > max(
            qpe_grid.update_interval_minutes,
            qpf_grid.update_interval_minutes,
        )
        * 60
    ):
        raise ValueError("QPE and QPF source timestamps do not align")


def _sample_grid_neighborhood(
    grid: CwaPrecipitationGrid,
    *,
    lat: float,
    lon: float,
    radius_m: float,
) -> dict[tuple[int, int], float]:
    west, south, east, north = grid.bounds_wgs84
    if lon < west or lon >= east or lat < south or lat >= north:
        return {}
    dx = (east - west) / grid.width
    dy = (north - south) / grid.height
    center_col = min(grid.width - 1, int((lon - west) / dx))
    center_row = min(grid.height - 1, int((north - lat) / dy))
    cell_lat_m = max(1.0, dy * 111_320.0)
    cell_lon_m = max(1.0, dx * 111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    row_radius = math.ceil(radius_m / cell_lat_m)
    col_radius = math.ceil(radius_m / cell_lon_m)
    sampled: dict[tuple[int, int], float] = {}
    for row in range(
        max(0, center_row - row_radius), min(grid.height, center_row + row_radius + 1)
    ):
        cell_lat = north - (row + 0.5) * dy
        northing_m = abs(cell_lat - lat) * 111_320.0
        for column in range(
            max(0, center_col - col_radius),
            min(grid.width, center_col + col_radius + 1),
        ):
            cell_lon = west + (column + 0.5) * dx
            easting_m = (
                abs(cell_lon - lon) * 111_320.0 * max(math.cos(math.radians(lat)), 0.01)
            )
            if (
                math.hypot(easting_m, northing_m)
                > radius_m + math.hypot(cell_lon_m, cell_lat_m) / 2
            ):
                continue
            value = grid.values[row][column]
            if value is not None:
                sampled[(row, column)] = value
    return sampled


def _densify_route(
    route_points: Sequence[tuple[float, float]],
    *,
    max_points: int,
) -> list[tuple[float, float]]:
    validated = [
        (
            _coordinate(lat, "route lat", -90, 90),
            _coordinate(lon, "route lon", -180, 180),
        )
        for lat, lon in route_points
    ]
    if len(validated) < 2:
        raise ValueError("route precipitation sampling requires at least two points")
    dense: list[tuple[float, float]] = []
    for start, end in zip(validated, validated[1:]):
        steps = max(
            1,
            min(
                100,
                math.ceil(max(abs(end[0] - start[0]), abs(end[1] - start[1])) / 0.005),
            ),
        )
        for index in range(steps):
            fraction = index / steps
            dense.append(
                (
                    start[0] + (end[0] - start[0]) * fraction,
                    start[1] + (end[1] - start[1]) * fraction,
                )
            )
    dense.append(validated[-1])
    if len(dense) <= max_points:
        return dense
    step = math.ceil(len(dense) / max_points)
    return dense[::step][:max_points]


def _trend(past: float | None, future: float | None) -> str:
    if past is None or future is None:
        return "unknown"
    delta = future - past
    if delta > 0.5:
        return "intensifying"
    if delta < -0.5:
        return "easing"
    return "steady"


def _rounded_mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    return values[min(len(values) - 1, math.ceil(len(values) * ratio) - 1)]


def _coordinate(value: Any, field: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise ValueError(f"invalid {field}")
    return parsed


def _aware_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid observedAt") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observedAt must include timezone")
    return parsed
