"""Coordinate conversion helpers for candidate terrain projections."""

from __future__ import annotations

import math


def twd97_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Convert EPSG:3826 coordinates to WGS84 with a bounded numeric inverse."""

    from pretrip_source_ingest import wgs84_to_twd97

    lat = float(y) / 110_900.0
    lon = 121.0 + (float(x) - 250_000.0) / (
        111_320.0 * max(math.cos(math.radians(lat)), 0.1)
    )
    for _ in range(10):
        projected_x, projected_y = wgs84_to_twd97(lat, lon)
        dx = float(x) - projected_x
        dy = float(y) - projected_y
        if abs(dx) + abs(dy) < 0.001:
            break
        delta = 1e-5
        lon_x, lon_y = wgs84_to_twd97(lat, lon + delta)
        lat_x, lat_y = wgs84_to_twd97(lat + delta, lon)
        a = (lon_x - projected_x) / delta
        b = (lat_x - projected_x) / delta
        c = (lon_y - projected_y) / delta
        d = (lat_y - projected_y) / delta
        determinant = a * d - b * c
        if abs(determinant) < 1e-9:
            break
        lon += (dx * d - b * dy) / determinant
        lat += (a * dy - dx * c) / determinant
    return lat, lon
