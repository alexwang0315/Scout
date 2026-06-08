from __future__ import annotations

import numpy as np

from scout_risk.dem.io import DEMGrid
from scout_risk.dem.terrain_features import TerrainFeatures, compute_terrain_features
from scout_risk.terrain_config import TeiiConfig, TerrainRiskProfileConfig


TEII_WEIGHTS = TeiiConfig().weights


def compute_teii_20m(
    features: TerrainFeatures,
    *,
    config: TeiiConfig | None = None,
) -> np.ndarray:
    config = config or TeiiConfig()
    feature_map = features.as_dict()
    base = np.zeros_like(features.slope_macro, dtype=float)
    for name, weight in config.weights.items():
        base += weight * feature_map[name]
    peak = np.maximum.reduce(list(feature_map.values()))
    return np.clip(config.base_weight * base + config.peak_weight * peak, 0.0, 100.0)


def compute_teii_from_dem(
    dem: DEMGrid,
    *,
    config: TerrainRiskProfileConfig | None = None,
) -> tuple[TerrainFeatures, np.ndarray]:
    config = config or TerrainRiskProfileConfig()
    features = compute_terrain_features(dem, config=config.terrain_features)
    return features, compute_teii_20m(features, config=config.teii)
