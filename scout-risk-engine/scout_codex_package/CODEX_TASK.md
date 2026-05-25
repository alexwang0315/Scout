# Codex Task: Implement Scout Risk Engine MVP

You are working on the Scout project. Implement the `scout-risk-engine` MVP based on `docs/scout-risk-engine-spec.md`.

## Goal

Build a Python package that can:

1. Read a 20m DEM / DTM GeoTIFF.
2. Compute macro terrain features.
3. Compute TEII_20m raster.
4. Parse GPX routes and sample risk along the route.
5. Parse CP notes and compute SCP.
6. Export route risk profile as GeoJSON / CSV.
7. Include unit tests with synthetic DEM data.

## Do first

1. Create the repo structure described in the spec.
2. Implement only the pretrip core:
   - DEM features
   - TEII_20m
   - GPX route sampling
   - CP/SCP parser
   - route risk output
3. Add CLI commands with Typer.
4. Add pytest tests.

## Do not do yet

- No real hardware drivers.
- No live LoRa integration.
- No drone integration.
- No ML training.
- No mobile app.

## Key formulas

```text
TEII_20m =
0.25 × slope_macro
+ 0.25 × downhill_drop_100m
+ 0.20 × local_relief_100m
+ 0.15 × contour_density
+ 0.15 × slope_continuity
```

```text
TEII_20m_final =
0.70 × TEII_20m
+ 0.30 × max(
    slope_macro,
    downhill_drop_100m,
    local_relief_100m,
    contour_density,
    slope_continuity
)
```

Initial implementation may stub `contour_density` as a slope-derived proxy until contour generation is implemented.

## Acceptance criteria

- `pytest` passes.
- CLI can compute TEII from a synthetic or provided GeoTIFF.
- CLI can sample a GPX and output route risk GeoJSON.
- CP note parser recognizes at least:
  - 大崩壁
  - 崩塌
  - 高繞
  - 拉繩
  - 危崖
  - 瘦稜
  - 路跡不明
  - 溪溝
- Every output risk score is clamped to 0-100.
- Route samples include explanation strings.

## Safety requirement

Do not phrase outputs as "safe". Use "lower risk", "higher risk", "low tolerance", "requires caution". This project is an assistive risk model, not a guarantee.
