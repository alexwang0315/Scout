from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from cwa_precipitation_grid import (
    CWA_QPE_PAST_1H_DATASET,
    CWA_QPF_NEXT_1H_DATASET,
    CoordinateTransformer,
    CwaPrecipitationGrid,
    parse_qpesums_grid,
)
from route_precipitation_sampler import build_route_precipitation_trend
from weather_grid_store import WeatherGridStore


RAINFALL_ROOT_REF = "outputs/environment/cwa/rainfall"
MAX_ROUTE_PROJECTION_FEATURES = 20_000
GridFetcher = Callable[..., dict[str, Any]]


def prepare_cwa_precipitation_workspace(
    *,
    project_root: Path,
    route_points: Sequence[tuple[float, float]],
    route_bbox: Mapping[str, float],
    fetched_at: str,
    fetcher: GridFetcher | None = None,
    coordinate_transformer: CoordinateTransformer | None = None,
) -> dict[str, Any]:
    """Fetch, normalize and persist QPE/QPF numeric grids on the server.

    This is intentionally a one-shot preparation primitive. Calling it never
    installs a scheduler and the returned project refs point only inside the
    supplied workspace.
    """

    resolved_root = project_root.resolve()
    if len(route_points) < 2:
        raise ValueError("CWA precipitation preparation requires route geometry")
    normalized_bbox = _validated_bbox(route_bbox)
    active_fetcher = fetcher or _default_fetcher
    grids = [
        parse_qpesums_grid(
            active_fetcher(dataset_id, file_format="JSON", timeout_s=30.0),
            fetched_at=fetched_at,
            coordinate_transformer=coordinate_transformer,
        )
        for dataset_id in (CWA_QPE_PAST_1H_DATASET, CWA_QPF_NEXT_1H_DATASET)
    ]
    by_kind = {grid.grid_kind: grid for grid in grids}
    store = WeatherGridStore(resolved_root / RAINFALL_ROOT_REF)
    manifest = store.update_manifest(grids)
    projection = build_route_grid_projection(grids, route_bbox=normalized_bbox)
    trend = build_route_precipitation_trend(
        qpe_grid=by_kind["qpe_past_1h"],
        qpf_grid=by_kind["qpf_next_1h"],
        route_points=route_points,
    )
    projection_ref = f"{RAINFALL_ROOT_REF}/route_grid_projection.geojson"
    trend_ref = f"{RAINFALL_ROOT_REF}/route_precipitation_trend.json"
    _atomic_json(resolved_root / projection_ref, projection)
    _atomic_json(resolved_root / trend_ref, trend)

    latest = manifest["latestByKind"]
    qpe_data_ref = f"{RAINFALL_ROOT_REF}/{latest['qpe_past_1h']['dataRef']}"
    qpf_data_ref = f"{RAINFALL_ROOT_REF}/{latest['qpf_next_1h']['dataRef']}"
    return {
        "cwa_rainfall_grid_status": "ready",
        "cwa_rainfall_grid_manifest_ref": f"{RAINFALL_ROOT_REF}/rainfall_grid_manifest.json",
        "cwa_qpe_numeric_grid_ref": qpe_data_ref,
        "cwa_qpf_numeric_grid_ref": qpf_data_ref,
        "cwa_rainfall_route_projection_ref": projection_ref,
        "cwa_rainfall_route_trend_ref": trend_ref,
        "team_target_rainfall_trend_ref": trend_ref,
        "cwa_rainfall_grid_source_timestamps": {
            kind: frame["sourceTimestamp"] for kind, frame in latest.items()
        },
        "cwa_rainfall_grid_data_delay_minutes": max(
            grid.data_delay_minutes for grid in grids
        ),
        "cwa_rainfall_grid_external_api_calls_made": True,
        "cwa_rainfall_grid_cacheable": False,
        "cwa_rainfall_grid_ttl_seconds": 0,
    }


def build_route_grid_projection(
    grids: Sequence[CwaPrecipitationGrid],
    *,
    route_bbox: Mapping[str, float],
) -> dict[str, Any]:
    bbox = _validated_bbox(route_bbox)
    features: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []
    for grid in grids:
        product = {
            "datasetId": grid.dataset_id,
            "gridKind": grid.grid_kind,
            "sourceTimestamp": grid.source_timestamp.isoformat(),
            "validFrom": grid.valid_from.isoformat(),
            "validUntil": grid.valid_until.isoformat(),
            "dataDelayMinutes": grid.data_delay_minutes,
            "expectedDelayMinutes": grid.expected_delay_minutes,
            "unit": grid.unit,
            "availableCellCount": 0,
        }
        products.append(product)
        west, south, east, north = grid.bounds_wgs84
        dx = (east - west) / grid.width
        dy = (north - south) / grid.height
        min_col = max(0, math.floor((bbox["west"] - west) / dx))
        max_col = min(grid.width - 1, math.floor((bbox["east"] - west) / dx))
        min_row = max(0, math.floor((north - bbox["north"]) / dy))
        max_row = min(grid.height - 1, math.floor((north - bbox["south"]) / dy))
        if min_col > max_col or min_row > max_row:
            continue
        for row in range(min_row, max_row + 1):
            cell_north = north - row * dy
            cell_south = cell_north - dy
            for column in range(min_col, max_col + 1):
                value = grid.values[row][column]
                if value is None:
                    continue
                cell_west = west + column * dx
                cell_east = cell_west + dx
                features.append(
                    {
                        "type": "Feature",
                        "id": f"{grid.grid_kind}.{row}.{column}",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [cell_west, cell_south],
                                [cell_east, cell_south],
                                [cell_east, cell_north],
                                [cell_west, cell_north],
                                [cell_west, cell_south],
                            ]],
                        },
                        "properties": {
                            "layerId": "cwa-qpf",
                            "datasetId": grid.dataset_id,
                            "gridKind": grid.grid_kind,
                            "rainfallMm": value,
                            "unit": grid.unit,
                            "sourceTimestamp": grid.source_timestamp.isoformat(),
                            "dataDelayMinutes": grid.data_delay_minutes,
                            "candidateOnly": True,
                            "runtimeSafetyTruth": False,
                        },
                    }
                )
                product["availableCellCount"] += 1
                if len(features) > MAX_ROUTE_PROJECTION_FEATURES:
                    raise ValueError("route precipitation projection exceeds feature limit")
    return {
        "type": "FeatureCollection",
        "schemaVersion": "cwa_route_grid_projection.v1",
        "artifactKind": "cwa_route_grid_projection",
        "bboxWgs84": bbox,
        "products": products,
        "features": features,
        "legend": {
            "unit": "mm",
            "stops": [0, 0.3, 1, 1.5, 3, 6, 10, 17, 25],
            "colors": [
                "#ffffff",
                "#77edf1",
                "#00a8f3",
                "#1ba500",
                "#f4f500",
                "#ff9800",
                "#f50000",
                "#8f0000",
                "#eb00dc",
            ],
        },
        "boundary": {
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "fullGridValuesExposed": False,
            "raspberryPiGridProcessing": False,
            "mobileGridProcessing": False,
        },
    }


def _default_fetcher(dataset_id: str, **kwargs: Any) -> dict[str, Any]:
    from scout_weather_integration import fetch_cwa_file_dataset

    return fetch_cwa_file_dataset(dataset_id, **kwargs)


def _validated_bbox(value: Mapping[str, float]) -> dict[str, float]:
    try:
        bbox = {
            key: float(value[key])
            for key in ("west", "south", "east", "north")
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid route bbox") from exc
    if not all(math.isfinite(item) for item in bbox.values()):
        raise ValueError("route bbox must be finite")
    if not (-180 <= bbox["west"] < bbox["east"] <= 180):
        raise ValueError("invalid route bbox longitude range")
    if not (-90 <= bbox["south"] < bbox["north"] <= 90):
        raise ValueError("invalid route bbox latitude range")
    return bbox


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
