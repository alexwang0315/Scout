# AGENTS.md

## Project: Scout Risk Engine

You are implementing a terrain-risk assistive system for hiking safety.

## Core principle

Scout does not guarantee safety. It estimates low-tolerance terrain and route difficulty using DEM/DTM, GPX, CP notes, and eventually field sensors.

Never phrase system output as "safe". Prefer:
- lower risk
- higher risk
- low tolerance terrain
- caution required
- uncertain due to resolution or sensor confidence

## MVP scope

Implement only the pretrip core first:

1. DEM / DTM reader
2. Terrain features
3. TEII_20m raster
4. GPX route sampling
5. CP note parser / SCP
6. Route risk output
7. CLI
8. Unit tests

Do not implement live sensor drivers, drone control, mobile app, or ML training unless explicitly asked.

## Coding standards

- Python 3.11+
- Use type hints.
- Use pydantic or dataclasses for schemas.
- Use numpy/scipy for raster math.
- Use rasterio for GeoTIFF.
- Use geopandas/shapely/pyproj for vector output.
- Use gpxpy for GPX.
- Use typer for CLI.
- Use pytest.

## Test expectations

Use synthetic DEM arrays for deterministic tests:
- flat terrain should produce low TEII
- steep gradient terrain should produce higher TEII
- local drop should increase drop score
- CP note parser should classify hazard keywords

## Safety language

Any generated route warning should include:
- risk source
- uncertainty if relevant
- action phrasing like "請放慢、確認現場路跡"

Avoid:
- "this route is safe"
- precise movement instructions near hazards
- implying GPS is exact
