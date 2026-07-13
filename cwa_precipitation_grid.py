from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CWA_QPE_PAST_1H_DATASET = "O-B0045-001"
CWA_QPF_NEXT_1H_DATASET = "F-B0046-001"
MAX_GRID_CELLS = 500_000
EXPECTED_DELAY_MINUTES = 10
UPDATE_INTERVAL_MINUTES = 10

GridKind = Literal["qpe_past_1h", "qpf_next_1h"]
CoordinateTransformer = Callable[[float, float], tuple[float, float]]


class PrecipitationGridBoundary(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_only: bool = True
    runtime_safety_truth: bool = False
    server_side_only: bool = True
    raspberry_pi_grid_processing: bool = False
    mobile_grid_processing: bool = False


class CwaPrecipitationGrid(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "cwa_precipitation_grid.v1"
    normalization_version: str = "cwa_precipitation_normalizer.v1"
    artifact_kind: str = "cwa_precipitation_grid"
    dataset_id: str
    grid_kind: GridKind
    accumulation_window_minutes: int = 60
    unit: Literal["mm"] = "mm"
    source_timestamp: datetime
    fetched_at: datetime
    valid_from: datetime
    valid_until: datetime
    data_delay_minutes: int = Field(ge=0)
    expected_delay_minutes: int = EXPECTED_DELAY_MINUTES
    update_interval_minutes: int = UPDATE_INTERVAL_MINUTES
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    resolution_degrees: float = Field(gt=0)
    source_crs: Literal["TWD67"] = "TWD67"
    output_crs: Literal["EPSG:4326"] = "EPSG:4326"
    transform_method: str
    georeference_metadata_authority: str = "datasetInfo.parameterSet"
    coordinate_uncertainty_m: int = Field(ge=0)
    source_payload_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    source_metadata_warnings: tuple[str, ...] = ()
    source_nodata: float
    row_order: Literal["north_to_south"] = "north_to_south"
    column_order: Literal["west_to_east"] = "west_to_east"
    bounds_wgs84: tuple[float, float, float, float]
    values: tuple[tuple[float | None, ...], ...]
    boundary: PrecipitationGridBoundary = PrecipitationGridBoundary()

    @model_validator(mode="after")
    def validate_grid_contract(self) -> "CwaPrecipitationGrid":
        expected_kind = {
            CWA_QPE_PAST_1H_DATASET: ("qpe_past_1h", -1.0),
            CWA_QPF_NEXT_1H_DATASET: ("qpf_next_1h", -99.0),
        }.get(self.dataset_id)
        if expected_kind is None or (self.grid_kind, self.source_nodata) != expected_kind:
            raise ValueError("dataset, grid kind, and no-data sentinel disagree")
        if self.width * self.height > MAX_GRID_CELLS:
            raise ValueError("weather grid exceeds cell limit")
        if len(self.values) != self.height or any(
            len(row) != self.width for row in self.values
        ):
            raise ValueError("weather grid shape does not match dimensions")
        for row in self.values:
            for value in row:
                if value is not None and (
                    not math.isfinite(value) or value < 0 or value > 5_000
                ):
                    raise ValueError("weather grid contains unsafe value")
        west, south, east, north = self.bounds_wgs84
        if not all(math.isfinite(value) for value in self.bounds_wgs84):
            raise ValueError("weather grid bounds must be finite")
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("weather grid bounds are invalid")
        if self.valid_from >= self.valid_until:
            raise ValueError("weather grid validity window is invalid")
        return self


def parse_qpesums_grid(
    payload: Mapping[str, Any],
    *,
    fetched_at: str | datetime,
    coordinate_transformer: CoordinateTransformer | None = None,
) -> CwaPrecipitationGrid:
    """Normalize a CWA QPESUMS file-API payload into a validated numeric grid.

    The provider payload enumerates cells from the lower-left, longitude first.
    Scout stores row zero at the north so map rendering and route sampling share
    one deterministic orientation.
    """

    root = _mapping(payload.get("cwaopendata"), "cwaopendata")
    dataset_id = str(root.get("dataid", "")).strip()
    if dataset_id == CWA_QPE_PAST_1H_DATASET:
        grid_kind: GridKind = "qpe_past_1h"
        source_nodata = -1.0
    elif dataset_id == CWA_QPF_NEXT_1H_DATASET:
        grid_kind = "qpf_next_1h"
        source_nodata = -99.0
    else:
        raise ValueError("unsupported CWA precipitation dataset")

    dataset = _mapping(root.get("dataset"), "dataset")
    info = _mapping(dataset.get("datasetInfo"), "datasetInfo")
    parameters = _mapping(info.get("parameterSet"), "parameterSet")
    contents = _mapping(dataset.get("contents"), "contents")
    source_payload_sha256 = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    width = _positive_int(parameters.get("GridDimensionX"), "GridDimensionX")
    height = _positive_int(parameters.get("GridDimensionY"), "GridDimensionY")
    if width * height > MAX_GRID_CELLS:
        raise ValueError("CWA precipitation grid exceeds cell limit")
    resolution = _finite_float(parameters.get("GridResolution"), "GridResolution")
    if resolution <= 0 or resolution > 1:
        raise ValueError("invalid CWA precipitation grid resolution")
    start_lon = _finite_float(parameters.get("StartPointLongitude"), "StartPointLongitude")
    start_lat = _finite_float(parameters.get("StartPointLatitude"), "StartPointLatitude")
    if not (-180 <= start_lon <= 180 and -90 <= start_lat <= 90):
        raise ValueError("invalid CWA precipitation grid origin")
    if str(parameters.get("Precipitation", "")).strip().lower() != "mm":
        raise ValueError("CWA precipitation grid unit must be mm")

    source_timestamp = _aware_datetime(parameters.get("DateTime"), "DateTime")
    fetched = _aware_datetime(fetched_at, "fetched_at")
    raw_values = str(contents.get("content", "")).split(",")
    if len(raw_values) != width * height:
        raise ValueError("CWA precipitation grid dimensions do not match cell count")

    cells: list[float | None] = []
    for raw_value in raw_values:
        value = _finite_float(raw_value, "precipitation cell")
        if math.isclose(value, source_nodata, abs_tol=1e-9):
            cells.append(None)
        elif value < 0 or value > 5_000:
            raise ValueError("CWA precipitation grid contains unsafe cell value")
        else:
            cells.append(value)

    south_first_rows = [
        tuple(cells[offset : offset + width])
        for offset in range(0, len(cells), width)
    ]
    values = tuple(reversed(south_first_rows))
    transformer = coordinate_transformer or twd67_to_wgs84
    metadata_warnings = _source_metadata_warnings(
        str(contents.get("contentDescription", "")),
        start_lat=start_lat,
        start_lon=start_lon,
        resolution=resolution,
    )
    bounds = _transformed_bounds(
        start_lat=start_lat,
        start_lon=start_lon,
        width=width,
        height=height,
        resolution=resolution,
        transformer=transformer,
    )
    delay_minutes = max(
        0,
        round((fetched.astimezone(source_timestamp.tzinfo) - source_timestamp).total_seconds() / 60),
    )
    if grid_kind == "qpe_past_1h":
        valid_from = source_timestamp - timedelta(minutes=60)
        valid_until = source_timestamp
    else:
        valid_from = source_timestamp
        valid_until = source_timestamp + timedelta(minutes=60)

    custom_transform = coordinate_transformer is not None
    return CwaPrecipitationGrid(
        dataset_id=dataset_id,
        grid_kind=grid_kind,
        source_timestamp=source_timestamp,
        fetched_at=fetched,
        valid_from=valid_from,
        valid_until=valid_until,
        data_delay_minutes=delay_minutes,
        width=width,
        height=height,
        resolution_degrees=resolution,
        transform_method=(
            "injected_coordinate_transformer"
            if custom_transform
            else "twd67_geocentric_translation_to_wgs84.v1"
        ),
        coordinate_uncertainty_m=0 if custom_transform else 150,
        source_payload_sha256=source_payload_sha256,
        source_metadata_warnings=metadata_warnings,
        source_nodata=source_nodata,
        bounds_wgs84=bounds,
        values=values,
    )


def twd67_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """Convert TWD67 geographic coordinates to WGS84 without a heavy GIS runtime.

    This uses the conventional three-parameter geocentric translation and marks
    a conservative uncertainty in the normalized artifact. It is appropriate for
    the ~1.3 km QPESUMS cells, not for survey-grade positioning.
    """

    x, y, z = _geodetic_to_ecef(lat, lon, 0.0, a=6_378_160.0, inverse_f=298.25)
    translated = (x - 730.160, y - 346.212, z - 472.186)
    return _ecef_to_geodetic(*translated, a=6_378_137.0, inverse_f=298.257223563)


def _geodetic_to_ecef(
    lat: float,
    lon: float,
    height: float,
    *,
    a: float,
    inverse_f: float,
) -> tuple[float, float, float]:
    phi = math.radians(lat)
    lam = math.radians(lon)
    f = 1 / inverse_f
    e2 = f * (2 - f)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    x = (n + height) * math.cos(phi) * math.cos(lam)
    y = (n + height) * math.cos(phi) * math.sin(lam)
    z = (n * (1 - e2) + height) * math.sin(phi)
    return x, y, z


def _ecef_to_geodetic(
    x: float,
    y: float,
    z: float,
    *,
    a: float,
    inverse_f: float,
) -> tuple[float, float]:
    f = 1 / inverse_f
    e2 = f * (2 - f)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(8):
        n = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        height = p / max(math.cos(lat), 1e-12) - n
        next_lat = math.atan2(z, p * (1 - e2 * n / (n + height)))
        if abs(next_lat - lat) < 1e-13:
            lat = next_lat
            break
        lat = next_lat
    return math.degrees(lat), math.degrees(lon)


def _transformed_bounds(
    *,
    start_lat: float,
    start_lon: float,
    width: int,
    height: int,
    resolution: float,
    transformer: CoordinateTransformer,
) -> tuple[float, float, float, float]:
    half = resolution / 2
    source_corners = (
        (start_lat - half, start_lon - half),
        (start_lat - half, start_lon + (width - 1) * resolution + half),
        (start_lat + (height - 1) * resolution + half, start_lon - half),
        (
            start_lat + (height - 1) * resolution + half,
            start_lon + (width - 1) * resolution + half,
        ),
    )
    transformed = [transformer(lat, lon) for lat, lon in source_corners]
    if any(not math.isfinite(lat) or not math.isfinite(lon) for lat, lon in transformed):
        raise ValueError("coordinate transformer returned non-finite bounds")
    lats = [item[0] for item in transformed]
    lons = [item[1] for item in transformed]
    return min(lons), min(lats), max(lons), max(lats)


def _source_metadata_warnings(
    description: str,
    *,
    start_lat: float,
    start_lon: float,
    resolution: float,
) -> tuple[str, ...]:
    warnings: list[str] = []
    origin_match = re.search(
        r"東經\s*([0-9]+(?:\.[0-9]+)?).*?北緯\s*([0-9]+(?:\.[0-9]+)?)",
        description,
    )
    if origin_match:
        prose_lon = float(origin_match.group(1))
        prose_lat = float(origin_match.group(2))
        if (
            abs(prose_lon - start_lon) > resolution / 2
            or abs(prose_lat - start_lat) > resolution / 2
        ):
            warnings.append(
                "content_description_origin_disagrees_with_structured_parameter_set"
            )
    if "TWD67" not in description.upper():
        warnings.append("content_description_does_not_declare_twd67")
    return tuple(warnings)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"missing or invalid {field}")
    return value


def _positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed <= 0:
        raise ValueError(f"invalid {field}")
    return parsed


def _finite_float(value: Any, field: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite {field}")
    return parsed


def _aware_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed
