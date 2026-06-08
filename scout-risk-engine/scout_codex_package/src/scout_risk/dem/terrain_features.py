from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from scout_risk.dem.io import DEMGrid
from scout_risk.terrain_config import TerrainFeatureConfig


@dataclass(frozen=True)
class TerrainFeatures:
    slope_macro: np.ndarray
    downhill_drop_100m: np.ndarray
    local_relief_100m: np.ndarray
    contour_density: np.ndarray
    slope_continuity: np.ndarray

    def as_dict(self) -> dict[str, np.ndarray]:
        return {
            "slope_macro": self.slope_macro,
            "downhill_drop_100m": self.downhill_drop_100m,
            "local_relief_100m": self.local_relief_100m,
            "contour_density": self.contour_density,
            "slope_continuity": self.slope_continuity,
        }


def compute_terrain_features(
    dem: DEMGrid,
    *,
    config: TerrainFeatureConfig | None = None,
) -> TerrainFeatures:
    config = config or TerrainFeatureConfig()
    elevation = np.nan_to_num(dem.elevation, nan=np.nanmedian(dem.elevation))
    slope_macro = compute_slope_macro(
        elevation,
        dem.pixel_size,
        scale_degrees=config.slope_score_scale_degrees,
    )
    local_min = _window_filter(elevation, config.radius_m, dem.pixel_size, reducer="min")
    local_max = _window_filter(elevation, config.radius_m, dem.pixel_size, reducer="max")
    downhill_drop = clamp_score(
        elevation - local_min,
        scale=config.downhill_drop_score_scale_m,
    )
    local_relief = clamp_score(
        local_max - local_min,
        scale=config.local_relief_score_scale_m,
    )
    contour_density = clamp_score(
        local_max - local_min,
        scale=config.contour_density_relief_score_scale_m,
    )
    slope_continuity = _window_filter(
        slope_macro,
        config.radius_m,
        dem.pixel_size,
        reducer="mean",
    )
    return TerrainFeatures(
        slope_macro=slope_macro,
        downhill_drop_100m=downhill_drop,
        local_relief_100m=local_relief,
        contour_density=contour_density,
        slope_continuity=np.clip(slope_continuity, 0, 100),
    )


def compute_slope_macro(
    elevation: np.ndarray,
    pixel_size_m: float,
    *,
    scale_degrees: float = 45.0,
) -> np.ndarray:
    gy, gx = np.gradient(elevation.astype(float), pixel_size_m, pixel_size_m)
    slope_degrees = np.degrees(np.arctan(np.hypot(gx, gy)))
    return clamp_score(slope_degrees, scale=scale_degrees)


def clamp_score(values: np.ndarray | float, *, scale: float) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float) / scale * 100.0, 0.0, 100.0)


def _window_filter(
    values: np.ndarray,
    radius_m: float,
    pixel_size_m: float,
    *,
    reducer: str,
) -> np.ndarray:
    radius_cells = max(1, int(round(radius_m / pixel_size_m)))
    size = radius_cells * 2 + 1
    try:
        from scipy.ndimage import maximum_filter, minimum_filter, uniform_filter

        if reducer == "min":
            return minimum_filter(values, size=size, mode="nearest")
        if reducer == "max":
            return maximum_filter(values, size=size, mode="nearest")
        if reducer == "mean":
            return uniform_filter(values, size=size, mode="nearest")
    except ImportError:
        pass

    padded = np.pad(values, radius_cells, mode="edge")
    output = np.zeros_like(values, dtype=float)
    for row in range(values.shape[0]):
        for col in range(values.shape[1]):
            window = padded[row : row + size, col : col + size]
            if reducer == "min":
                output[row, col] = float(np.min(window))
            elif reducer == "max":
                output[row, col] = float(np.max(window))
            elif reducer == "mean":
                output[row, col] = float(np.mean(window))
            else:
                raise ValueError(f"unsupported reducer: {reducer}")
    return output
