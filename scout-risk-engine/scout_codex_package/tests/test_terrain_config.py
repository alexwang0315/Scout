from __future__ import annotations

import numpy as np

from scout_risk.dem.io import DEMGrid
from scout_risk.dem.teii import compute_teii_from_dem
from scout_risk.terrain_config import (
    TerrainFeatureConfig,
    TerrainRiskProfileConfig,
    load_terrain_risk_config,
)


def test_default_terrain_config_loads_from_packaged_toml():
    loaded = load_terrain_risk_config()

    assert loaded.source.endswith("terrain_risk_profile.default.toml")
    assert len(loaded.sha256) == 64
    assert loaded.config.route_preparation.sample_interval_m == 20.0
    assert loaded.config.route_risk.risk_level_thresholds == [20.0, 40.0, 60.0, 80.0]
    assert "collapse" in loaded.config.cp_note_keywords
    assert loaded.metadata()["parameters"]["schema_version"] == loaded.config.schema_version


def test_partial_config_file_overrides_defaults(tmp_path):
    config_path = tmp_path / "terrain_config.toml"
    config_path.write_text(
        """
[route_preparation]
sample_interval_m = 120.0
overpass_corridor_m = 42.0

[route_risk]
risk_level_thresholds = [10.0, 30.0, 50.0, 70.0]
""",
        encoding="utf-8",
    )

    loaded = load_terrain_risk_config(config_path)

    assert loaded.config.route_preparation.sample_interval_m == 120.0
    assert loaded.config.route_preparation.overpass_corridor_m == 42.0
    assert loaded.config.route_preparation.dem_buffer_m == 140.0
    assert loaded.config.route_risk.risk_level_thresholds == [10.0, 30.0, 50.0, 70.0]


def test_terrain_feature_config_changes_teii_scale():
    y = np.arange(12, dtype=float)[:, None]
    dem = DEMGrid.from_array(1000.0 + y * 35.0 + np.zeros((12, 12)), pixel_size=20.0)
    default_config = TerrainRiskProfileConfig()
    conservative_slope_config = TerrainRiskProfileConfig(
        terrain_features=TerrainFeatureConfig(slope_score_scale_degrees=90.0)
    )

    _, default_teii = compute_teii_from_dem(dem, config=default_config)
    _, conservative_teii = compute_teii_from_dem(dem, config=conservative_slope_config)

    assert float(conservative_teii.mean()) < float(default_teii.mean())
