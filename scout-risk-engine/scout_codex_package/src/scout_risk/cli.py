from __future__ import annotations

import json
from pathlib import Path

import typer

from scout_risk.calibration import write_calibration_report_placeholder
from scout_risk.cp.parser import load_cp_csv, parse_cp_notes
from scout_risk.cp.scp import compute_scp
from scout_risk.dem.io import read_dem, write_dem_array
from scout_risk.dem.teii import compute_teii_from_dem
from scout_risk.fusion.pretrip import (
    build_overpass_pretrip_route_profile,
    build_pretrip_route_profile,
)
from scout_risk.route.outputs import write_route_csv, write_route_geojson
from scout_risk.route.risk_score_map import (
    build_risk_ribbon_from_geojson,
    build_risk_score_point_map_from_geojson,
    write_risk_ribbon_geojson,
    write_risk_ribbon_metadata,
    write_risk_score_csv,
    write_risk_score_geojson,
    write_risk_score_metadata,
    write_risk_score_xyz,
)
from scout_risk.terrain_config import load_terrain_risk_config


app = typer.Typer(
    help="Scout Risk Engine pretrip terrain-risk CLI. Outputs are assistive, candidate-only risk evidence.",
)


@app.command("dem-features")
def dem_features(
    dem: Path = typer.Option(..., help="Input DEM/DTM .tif/.tiff/.npy/.npz"),
    out: Path = typer.Option(..., help="Output directory for feature .npy files"),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "--terrain-config",
        help="Terrain risk profile config TOML",
    ),
) -> None:
    loaded_config = load_terrain_risk_config(config_path)
    grid = read_dem(dem)
    features, _ = compute_teii_from_dem(grid, config=loaded_config.config)
    out.mkdir(parents=True, exist_ok=True)
    for name, values in features.as_dict().items():
        write_dem_array(out / f"{name}.npy", grid, values)
    typer.echo(f"wrote terrain feature rasters to {out}")


@app.command("compute-teii")
def compute_teii(
    dem: Path = typer.Option(..., help="Input DEM/DTM .tif/.tiff/.npy/.npz"),
    out: Path = typer.Option(..., help="Output TEII raster .tif/.npy/.npz"),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "--terrain-config",
        help="Terrain risk profile config TOML",
    ),
) -> None:
    loaded_config = load_terrain_risk_config(config_path)
    grid = read_dem(dem)
    _, teii = compute_teii_from_dem(grid, config=loaded_config.config)
    write_dem_array(out, grid, teii)
    typer.echo(f"wrote TEII_20m raster to {out}")


@app.command("parse-cp")
def parse_cp(
    input: Path = typer.Option(..., help="CP note CSV with lat/lon/text fields"),
    out: Path = typer.Option(..., help="Output JSON file"),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "--terrain-config",
        help="Terrain risk profile config TOML",
    ),
) -> None:
    loaded_config = load_terrain_risk_config(config_path)
    parsed = parse_cp_notes(
        load_cp_csv(input),
        hazard_keywords=loaded_config.config.cp_note_keywords,
    )
    payload = [
        {
            "lat": note.lat,
            "lon": note.lon,
            "text": note.text,
            "hazard_types": note.hazard_types,
            "matched_keywords": note.matched_keywords,
            "scp": compute_scp(note, config=loaded_config.config.scp),
        }
        for note in parsed
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"wrote CP/SCP notes to {out}")


@app.command("route-profile")
def route_profile(
    dem: Path = typer.Option(..., help="Input DEM/DTM .tif/.tiff/.npy/.npz"),
    gpx: Path = typer.Option(..., help="Input GPX route"),
    out: Path = typer.Option(..., help="Output GeoJSON path"),
    csv_out: Path | None = typer.Option(None, help="Optional CSV output path"),
    cp: Path | None = typer.Option(None, help="Optional CP note CSV"),
    route_id: str = typer.Option("route", help="Route id used in samples"),
    sample_interval_m: float | None = typer.Option(
        None,
        help="Sampling interval in meters; overrides config when set",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "--terrain-config",
        help="Terrain risk profile config TOML",
    ),
) -> None:
    loaded_config = load_terrain_risk_config(config_path)
    profile = build_pretrip_route_profile(
        dem_path=dem,
        gpx_path=gpx,
        cp_path=cp,
        route_id=route_id,
        sample_interval_m=sample_interval_m,
        terrain_config=loaded_config,
    )
    write_route_geojson(profile, out)
    if csv_out is not None:
        write_route_csv(profile, csv_out)
    typer.echo(f"wrote {len(profile.samples)} route risk samples to {out}")


@app.command("overpass-route-profile")
def overpass_route_profile(
    dtm_coverage: Path = typer.Option(
        ...,
        help="DTM coverage summary JSON referencing local TWD97 .grd tiles",
    ),
    overpass: Path = typer.Option(
        ...,
        help="Overpass vector evidence GeoJSON; trail LineStrings form the route base",
    ),
    reference_gpx: Path = typer.Option(
        ...,
        help=(
            "Reference GPX used only as a weak alignment prior. Its points are not "
            "used as the route-profile centerline."
        ),
    ),
    out: Path = typer.Option(..., help="Output route risk GeoJSON path"),
    csv_out: Path | None = typer.Option(None, help="Optional CSV output path"),
    metadata_out: Path | None = typer.Option(None, help="Optional metadata JSON path"),
    cp: Path | None = typer.Option(None, help="Optional CP note CSV"),
    route_id: str = typer.Option("overpass_aligned_route", help="Route id used in samples"),
    sample_interval_m: float | None = typer.Option(
        None,
        help="Sampling interval in meters; overrides config when set",
    ),
    corridor_m: float | None = typer.Option(
        None,
        help=(
            "Overpass trail vertices must be this close to the reference GPX "
            "corridor; overrides config when set"
        ),
    ),
    dem_buffer_m: float | None = typer.Option(
        None,
        help="TWD97 DTM clipping buffer around the selected Overpass route; overrides config when set",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "--terrain-config",
        help="Terrain risk profile config TOML",
    ),
) -> None:
    loaded_config = load_terrain_risk_config(config_path)
    profile, metadata = build_overpass_pretrip_route_profile(
        dtm_coverage_path=dtm_coverage,
        overpass_geojson_path=overpass,
        reference_gpx_path=reference_gpx,
        cp_path=cp,
        route_id=route_id,
        sample_interval_m=sample_interval_m,
        corridor_m=corridor_m,
        dem_buffer_m=dem_buffer_m,
        terrain_config=loaded_config,
    )
    write_route_geojson(profile, out)
    if csv_out is not None:
        write_route_csv(profile, csv_out)
    if metadata_out is None:
        metadata_out = out.with_suffix(out.suffix + ".metadata.json")
    metadata_out.parent.mkdir(parents=True, exist_ok=True)
    metadata_out.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    typer.echo(
        f"wrote {len(profile.samples)} Overpass-based route risk samples to {out}; "
        f"metadata {metadata_out}"
    )


@app.command("risk-score-map")
def risk_score_map(
    route_risk: Path = typer.Option(..., help="Input route_risk.geojson point samples"),
    csv_out: Path = typer.Option(..., help="Output CSV with x/y/rs point values"),
    xyz_out: Path | None = typer.Option(None, help="Optional XYZ output: x y rs"),
    geojson_out: Path | None = typer.Option(None, help="Optional GeoJSON point output"),
    metadata_out: Path | None = typer.Option(None, help="Optional metadata JSON output"),
    score_field: str = typer.Option("pretrip_risk", help="Route risk property used as rs"),
    snap_grid_m: float = typer.Option(
        20.0,
        help="TWD97 grid size in meters used to snap route risk points",
    ),
) -> None:
    point_map = build_risk_score_point_map_from_geojson(
        route_risk,
        score_field=score_field,
        snap_grid_m=snap_grid_m,
    )
    write_risk_score_csv(point_map, csv_out)
    if xyz_out is not None:
        write_risk_score_xyz(point_map, xyz_out)
    if geojson_out is not None:
        write_risk_score_geojson(point_map, geojson_out)
    if metadata_out is None:
        metadata_out = csv_out.with_suffix(csv_out.suffix + ".metadata.json")
    write_risk_score_metadata(point_map, metadata_out)
    typer.echo(
        f"wrote {len(point_map.points)} route-aligned risk score points to {csv_out}; "
        f"metadata {metadata_out}"
    )


@app.command("risk-ribbon")
def risk_ribbon(
    route_risk: Path = typer.Option(..., help="Input route_risk.geojson point samples"),
    out: Path = typer.Option(..., help="Output route-aligned risk ribbon GeoJSON"),
    metadata_out: Path | None = typer.Option(None, help="Optional metadata JSON output"),
    score_field: str = typer.Option("pretrip_risk", help="Route risk property used as rs"),
) -> None:
    ribbon = build_risk_ribbon_from_geojson(
        route_risk,
        score_field=score_field,
    )
    write_risk_ribbon_geojson(ribbon, out)
    if metadata_out is None:
        metadata_out = out.with_suffix(out.suffix + ".metadata.json")
    write_risk_ribbon_metadata(ribbon, metadata_out)
    typer.echo(
        f"wrote {len(ribbon.features)} route-aligned risk ribbon segments to {out}; "
        f"metadata {metadata_out}"
    )


@app.command("calibration-report")
def calibration_report(
    out: Path = typer.Option(..., help="Output JSON path"),
    route_profile_ref: str | None = typer.Option(None, help="Optional route profile artifact ref"),
) -> None:
    write_calibration_report_placeholder(out, route_profile_ref=route_profile_ref)
    typer.echo(f"wrote calibration placeholder to {out}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
