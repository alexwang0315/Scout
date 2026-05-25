from __future__ import annotations

import math


def wgs84_to_twd97(lat: float, lon: float) -> tuple[float, float]:
    """Project WGS84 lat/lon to Taiwan TWD97 TM2 zone 121 meters.

    This mirrors Scout Fusion's Phase 4 pretrip projection helper so the risk
    engine can run without requiring pyproj on a Raspberry Pi.
    """

    a = 6378137.0
    b = 6356752.314245
    lon0 = math.radians(121.0)
    k0 = 0.9999
    dx = 250000.0

    e = math.sqrt(1 - (b * b) / (a * a))
    e2 = e * e / (1 - e * e)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)

    n = a / math.sqrt(1 - (e * math.sin(lat_rad)) ** 2)
    t = math.tan(lat_rad) ** 2
    c = e2 * math.cos(lat_rad) ** 2
    a_lon = math.cos(lat_rad) * (lon_rad - lon0)
    m = a * (
        (1.0 - e**2 / 4.0 - 3.0 * e**4 / 64.0 - 5.0 * e**6 / 256.0)
        * lat_rad
        - (3.0 * e**2 / 8.0 + 3.0 * e**4 / 32.0 + 45.0 * e**6 / 1024.0)
        * math.sin(2.0 * lat_rad)
        + (15.0 * e**4 / 256.0 + 45.0 * e**6 / 1024.0)
        * math.sin(4.0 * lat_rad)
        - (35.0 * e**6 / 3072.0) * math.sin(6.0 * lat_rad)
    )

    x = dx + k0 * n * (
        a_lon
        + (1.0 - t + c) * a_lon**3 / 6.0
        + (5.0 - 18.0 * t + t**2 + 72.0 * c - 58.0 * e2) * a_lon**5 / 120.0
    )
    y = k0 * (
        m
        + n
        * math.tan(lat_rad)
        * (
            a_lon**2 / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c**2) * a_lon**4 / 24.0
            + (61.0 - 58.0 * t + t**2 + 600.0 * c - 330.0 * e2)
            * a_lon**6
            / 720.0
        )
    )
    return x, y


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return earth_radius_m * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def local_xy_m(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(ref_lat))
    return lon * meters_per_deg_lon, lat * meters_per_deg_lat

