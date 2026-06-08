# Scout Risk Engine

MVP implementation target for the Scout terrain-risk system.

## First milestone

Compute `TEII_20m` from a DEM/DTM and sample route risk along GPX tracks.

See:

- `docs/scout-risk-engine-spec.md`
- `CODEX_TASK.md`
- `AGENTS.md`

## Current MVP

This package currently implements the pretrip core only:

- DEM/DTM reader for `.npy`, `.npz`, and GeoTIFF when `rasterio` is installed
- DEM terrain features: `slope_macro`, `downhill_drop_100m`, `local_relief_100m`, `contour_density`, `slope_continuity`
- `TEII_20m` formula with peak gate
- GPX parser and route resampling
- CP note parser and `SCP` scoring
- Route risk profile with GeoJSON and CSV output
- Route-aligned risk score point map（沿路徑風險數值點圖）with CSV/XYZ/GeoJSON output
- Typer CLI
- Calibration report placeholder

It does not implement hardware drivers, LoRa mesh, drone control, mobile apps, or ML training.

## CLI

```bash
scout-risk compute-teii --dem data/dem.npy --out out/teii.npy
scout-risk dem-features --dem data/dem.npy --out out/features
scout-risk parse-cp --input examples/sample_cp_notes.csv --out out/cp.json
scout-risk route-profile --dem data/dem.npy --gpx data/route.gpx --cp examples/sample_cp_notes.csv --out out/route_risk.geojson --csv-out out/route_risk.csv
scout-risk overpass-route-profile \
  --dtm-coverage ../../tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/terrain/dtm_coverage_summary.json \
  --overpass ../../tests/fixtures/pretrip/projects/chilai_nanhua_day1/normalized/map/overpass_vector_evidence.geojson \
  --reference-gpx ~/Downloads/twmap-gpx-yunhai/能高安東軍.gpx.gpx \
  --out out/chilai_overpass/route_risk.geojson \
  --csv-out out/chilai_overpass/route_risk.csv
scout-risk risk-score-map \
  --route-risk out/chilai_overpass/route_risk.geojson \
  --csv-out out/chilai_overpass/risk_score_points.csv \
  --xyz-out out/chilai_overpass/risk_score_points.xyz \
  --geojson-out out/chilai_overpass/risk_score_points.geojson
scout-risk calibration-report --out out/calibration_report.json
```

Outputs are candidate-only terrain-risk evidence. Do not treat them as runtime safety truth.

`overpass-route-profile` uses Overpass/OSM trail LineString geometry as the
route-profile base. The GPX path is only a weak alignment prior（弱對位參考）for
choosing and ordering nearby OSM trail vertices; GPX points are not emitted as
the route centerline.

`risk-score-map` converts route risk point samples into a DTM-like numeric point
file. CSV/XYZ coordinates are snapped TWD97 `EPSG:3826` x/y values and `rs`
defaults to `pretrip_risk`. This is not an interpolated raster; it only emits
route-aligned risk samples.
