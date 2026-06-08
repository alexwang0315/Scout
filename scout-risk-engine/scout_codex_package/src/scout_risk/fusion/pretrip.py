from __future__ import annotations

from pathlib import Path

from scout_risk.cp.parser import load_cp_csv, parse_cp_notes
from scout_risk.dem.io import read_dem
from scout_risk.dem.teii import compute_teii_from_dem
from scout_risk.dem.twd97_tiles import build_dem_from_dtm_coverage
from scout_risk.geo import wgs84_to_twd97
from scout_risk.gpx.parser import load_gpx_points
from scout_risk.gpx.sampling import XYRoutePoint, gpx_points_to_dem_xy, resample_route_points
from scout_risk.overpass.route_base import OverpassRouteBase, build_overpass_route_base
from scout_risk.route.risk_profile import RouteRiskProfile, build_route_risk_profile
from scout_risk.terrain_config import LoadedTerrainRiskConfig, load_terrain_risk_config


def build_pretrip_route_profile(
    *,
    dem_path: str | Path,
    gpx_path: str | Path,
    cp_path: str | Path | None = None,
    route_id: str = "route",
    sample_interval_m: float | None = None,
    terrain_config: LoadedTerrainRiskConfig | None = None,
) -> RouteRiskProfile:
    loaded_config = terrain_config or load_terrain_risk_config()
    config = loaded_config.config
    effective_sample_interval_m = (
        sample_interval_m
        if sample_interval_m is not None
        else config.route_preparation.sample_interval_m
    )
    dem = read_dem(dem_path)
    _, teii = compute_teii_from_dem(dem, config=config)
    points = load_gpx_points(gpx_path)
    resampled = resample_route_points(points, interval_m=effective_sample_interval_m)
    route_xy = gpx_points_to_dem_xy(resampled, dem_crs=dem.crs)
    cp_notes = (
        parse_cp_notes(load_cp_csv(cp_path), hazard_keywords=config.cp_note_keywords)
        if cp_path is not None
        else []
    )
    return build_route_risk_profile(
        route_id=route_id,
        dem=dem,
        teii=teii,
        route_points=route_xy,
        cp_notes=cp_notes,
        risk_config=config.route_risk,
        scp_config=config.scp,
    )


def build_overpass_pretrip_route_profile(
    *,
    dtm_coverage_path: str | Path,
    overpass_geojson_path: str | Path,
    reference_gpx_path: str | Path,
    cp_path: str | Path | None = None,
    route_id: str = "overpass_aligned_route",
    sample_interval_m: float | None = None,
    corridor_m: float | None = None,
    dem_buffer_m: float | None = None,
    terrain_config: LoadedTerrainRiskConfig | None = None,
) -> tuple[RouteRiskProfile, dict]:
    loaded_config = terrain_config or load_terrain_risk_config()
    config = loaded_config.config
    effective_sample_interval_m = (
        sample_interval_m
        if sample_interval_m is not None
        else config.route_preparation.sample_interval_m
    )
    effective_corridor_m = (
        corridor_m
        if corridor_m is not None
        else config.route_preparation.overpass_corridor_m
    )
    effective_dem_buffer_m = (
        dem_buffer_m
        if dem_buffer_m is not None
        else config.route_preparation.dem_buffer_m
    )
    route_base = build_overpass_route_base(
        overpass_geojson_path=overpass_geojson_path,
        reference_gpx_path=reference_gpx_path,
        route_id=route_id,
        corridor_m=effective_corridor_m,
        reference_interval_m=config.route_preparation.overpass_reference_interval_m,
    )
    dtm_result = build_dem_from_dtm_coverage(
        dtm_coverage_path,
        route_points_wgs84=[(point.lat, point.lon) for point in route_base.points],
        buffer_m=effective_dem_buffer_m,
        pixel_size_m=config.route_preparation.dtm_pixel_size_m,
    )
    _, teii = compute_teii_from_dem(dtm_result.dem, config=config)
    route_xy = _overpass_route_base_samples_to_twd97(
        route_base,
        sample_interval_m=effective_sample_interval_m,
    )
    cp_notes = (
        parse_cp_notes(load_cp_csv(cp_path), hazard_keywords=config.cp_note_keywords)
        if cp_path is not None
        else []
    )
    profile = build_route_risk_profile(
        route_id=route_id,
        dem=dtm_result.dem,
        teii=teii,
        route_points=route_xy,
        cp_notes=cp_notes,
        risk_config=config.route_risk,
        scp_config=config.scp,
    )
    metadata = {
        "artifact_kind": "scout_risk_overpass_route_profile_metadata",
        "route_base": route_base.metadata,
        "dtm_mosaic": dtm_result.metadata,
        "sample_interval_m": effective_sample_interval_m,
        "route_preparation": {
            "sample_interval_m": effective_sample_interval_m,
            "overpass_corridor_m": effective_corridor_m,
            "overpass_reference_interval_m": (
                config.route_preparation.overpass_reference_interval_m
            ),
            "dem_buffer_m": effective_dem_buffer_m,
            "dtm_pixel_size_m": config.route_preparation.dtm_pixel_size_m,
        },
        "terrain_risk_config": loaded_config.metadata(),
        "route_risk_sample_count": len(profile.samples),
        "boundary": {
            "reference_gpx_not_used_as_route_centerline": True,
            "route_base_is_overpass_vector_evidence": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "raw_dtm_copied": False,
        },
    }
    return profile, metadata


def _overpass_route_base_samples_to_twd97(
    route_base: OverpassRouteBase,
    *,
    sample_interval_m: float,
) -> list[XYRoutePoint]:
    samples = resample_route_points(route_base.points, interval_m=sample_interval_m)
    output: list[XYRoutePoint] = []
    for sample in samples:
        x, y = wgs84_to_twd97(sample.lat, sample.lon)
        output.append(
            XYRoutePoint(
                x=x,
                y=y,
                distance_m=sample.distance_m,
                lat=sample.lat,
                lon=sample.lon,
                elevation_m=sample.elevation_m,
            )
        )
    return output
