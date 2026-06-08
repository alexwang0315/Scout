from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class DEMGrid:
    """A small north-up DEM grid.

    Coordinates are interpreted in the DEM CRS. For synthetic tests this can be
    a simple local meter grid. GeoTIFF support is enabled when rasterio exists.
    """

    elevation: np.ndarray
    x_min: float
    y_max: float
    pixel_size: float = 20.0
    crs: str | None = None
    nodata: float | None = None

    def __post_init__(self) -> None:
        if self.elevation.ndim != 2:
            raise ValueError("DEM elevation must be a 2D array")
        if self.pixel_size <= 0:
            raise ValueError("DEM pixel_size must be positive")

    @classmethod
    def from_array(
        cls,
        elevation: np.ndarray,
        *,
        x_min: float = 0.0,
        y_max: float | None = None,
        pixel_size: float = 20.0,
        crs: str | None = None,
        nodata: float | None = None,
    ) -> "DEMGrid":
        array = np.asarray(elevation, dtype=float)
        if y_max is None:
            y_max = float((array.shape[0] - 1) * pixel_size)
        return cls(
            elevation=array,
            x_min=float(x_min),
            y_max=float(y_max),
            pixel_size=float(pixel_size),
            crs=crs,
            nodata=nodata,
        )

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevation.shape

    @property
    def resolution_m(self) -> float:
        return self.pixel_size

    @property
    def x_max(self) -> float:
        return self.x_min + (self.shape[1] - 1) * self.pixel_size

    @property
    def y_min(self) -> float:
        return self.y_max - (self.shape[0] - 1) * self.pixel_size

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x_min, self.y_min, self.x_max, self.y_max)

    def row_col_for_xy(self, x: float, y: float) -> tuple[int, int] | None:
        col = int(round((x - self.x_min) / self.pixel_size))
        row = int(round((self.y_max - y) / self.pixel_size))
        if row < 0 or col < 0 or row >= self.shape[0] or col >= self.shape[1]:
            return None
        return row, col

    def xy_for_row_col(self, row: int, col: int) -> tuple[float, float]:
        return (
            self.x_min + col * self.pixel_size,
            self.y_max - row * self.pixel_size,
        )

    def sample_xy(self, x: float, y: float) -> float | None:
        row_col = self.row_col_for_xy(x, y)
        if row_col is None:
            return None
        row, col = row_col
        value = float(self.elevation[row, col])
        if np.isnan(value):
            return None
        return value

    def window_values(self, row: int, col: int, radius_m: float) -> np.ndarray:
        radius_cells = max(0, int(round(radius_m / self.pixel_size)))
        r0 = max(0, row - radius_cells)
        r1 = min(self.shape[0], row + radius_cells + 1)
        c0 = max(0, col - radius_cells)
        c1 = min(self.shape[1], col + radius_cells + 1)
        return self.elevation[r0:r1, c0:c1]


def read_dem(path: str | Path) -> DEMGrid:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".npy":
        return DEMGrid.from_array(np.load(source))
    if suffix == ".npz":
        payload = np.load(source, allow_pickle=False)
        elevation = payload["elevation"]
        default_y_max = float((elevation.shape[0] - 1) * 20.0)
        return DEMGrid.from_array(
            elevation,
            x_min=_npz_float(payload, "x_min", 0.0),
            y_max=_npz_float(payload, "y_max", default_y_max),
            pixel_size=_npz_float(payload, "pixel_size", 20.0),
            crs=_npz_str(payload, "crs"),
            nodata=float(payload["nodata"]) if "nodata" in payload else None,
        )
    if suffix in {".tif", ".tiff"}:
        return _read_geotiff(source)
    raise ValueError(f"unsupported DEM format: {source.suffix}")


def write_dem_array(path: str | Path, dem: DEMGrid, values: np.ndarray) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    array = np.asarray(values, dtype=float)
    if suffix == ".npy":
        np.save(destination, array)
        return
    if suffix == ".npz":
        np.savez(
            destination,
            elevation=array,
            x_min=dem.x_min,
            y_max=dem.y_max,
            pixel_size=dem.pixel_size,
            crs=dem.crs or "",
            nodata=np.nan,
        )
        return
    if suffix in {".tif", ".tiff"}:
        _write_geotiff(destination, dem, array)
        return
    raise ValueError(f"unsupported DEM output format: {destination.suffix}")


def _read_geotiff(path: Path) -> DEMGrid:
    try:
        import rasterio
    except ImportError as exc:
        raise ImportError(
            "GeoTIFF DEM input requires rasterio. Use .npy/.npz for synthetic tests "
            "or install the geo optional dependencies."
        ) from exc

    with rasterio.open(path) as dataset:
        array = dataset.read(1).astype(float)
        nodata = dataset.nodata
        if nodata is not None:
            array[array == nodata] = np.nan
        transform = dataset.transform
        pixel_size = abs(float(transform.a))
        return DEMGrid(
            elevation=array,
            x_min=float(transform.c),
            y_max=float(transform.f),
            pixel_size=pixel_size,
            crs=str(dataset.crs) if dataset.crs else None,
            nodata=nodata,
        )


def _write_geotiff(path: Path, dem: DEMGrid, values: np.ndarray) -> None:
    try:
        import rasterio
        from rasterio.transform import from_origin
    except ImportError as exc:
        raise ImportError("GeoTIFF output requires rasterio") from exc

    transform = from_origin(dem.x_min, dem.y_max, dem.pixel_size, dem.pixel_size)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": "float32",
        "transform": transform,
        "nodata": np.nan,
    }
    if dem.crs:
        profile["crs"] = dem.crs
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(values.astype("float32"), 1)


def _npz_float(payload: Any, key: str, default: float) -> float:
    if key not in payload:
        return default
    return float(payload[key])


def _npz_str(payload: Any, key: str) -> str | None:
    if key not in payload:
        return None
    value = str(payload[key])
    return value or None
