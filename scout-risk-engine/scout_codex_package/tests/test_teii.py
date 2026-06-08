from __future__ import annotations

import numpy as np

from scout_risk.dem.io import DEMGrid
from scout_risk.dem.teii import compute_teii_from_dem


def test_flat_terrain_produces_low_teii():
    dem = DEMGrid.from_array(np.full((12, 12), 1000.0), pixel_size=20.0)

    features, teii = compute_teii_from_dem(dem)

    assert float(teii.max()) < 1.0
    assert float(features.slope_macro.max()) < 1.0


def test_steep_gradient_produces_higher_teii_than_flat():
    flat = DEMGrid.from_array(np.full((12, 12), 1000.0), pixel_size=20.0)
    y = np.arange(12, dtype=float)[:, None]
    steep = DEMGrid.from_array(1000.0 + y * 35.0 + np.zeros((12, 12)), pixel_size=20.0)

    _, flat_teii = compute_teii_from_dem(flat)
    _, steep_teii = compute_teii_from_dem(steep)

    assert float(steep_teii.mean()) > float(flat_teii.mean()) + 30.0
    assert 0.0 <= float(steep_teii.max()) <= 100.0


def test_local_drop_increases_drop_score():
    elevation = np.full((15, 15), 1000.0)
    elevation[7, 7] = 700.0
    dem = DEMGrid.from_array(elevation, pixel_size=20.0)

    features, teii = compute_teii_from_dem(dem)

    assert features.downhill_drop_100m[6, 7] > 80.0
    assert teii[6, 7] > teii[0, 0]
