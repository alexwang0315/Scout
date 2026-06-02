# Pretrip Layer Preparation

## Objective

`LayerPreparationJob`（圖層準備工作） prepares map and evidence layers for a
Phase 4 pretrip workspace before `/admin/pretrip` renders them. It turns local
route, terrain, raster, tile, weather, and review evidence into deterministic
workspace artifacts, while keeping Phase 1 runtime state and Phase 2 Brain
writeback out of scope.

The job is a planning-side compiler for layer readiness, not a live map
provider, crawler, route editor, safety adapter, or final `MissionGraph`
compiler.

## Admin API（管理介面 API）

The admin surface exposes the same job through workspace-only endpoints:

- `POST /admin/pretrip/projects/{project_id}/prepare-layers-preview`: builds a
  no-write preview of the `LayerPreparationJob`（圖層準備工作） plan.
- `POST /admin/pretrip/projects/{project_id}/prepare-layers`: requires
  `confirm_prepare=true`, writes only the selected project workspace outputs,
  and updates `project.json` layer refs.
- `GET /admin/pretrip/projects/{project_id}/layer-preparation`: returns the
  current layer preparation summary for `/admin/pretrip`.

The API refuses fixture mutation for confirmed runs and keeps `/admin/debug`
projection events read-only.

## CLI Command

Normal operator `CLI`（命令列介面） contract assumes the preparation machine has
network access and fetches route-corridor Overpass vector evidence:

```bash
python -m pretrip_layer_preparation \
  --project-id chilai_nanhua_day1 \
  --workspace-root /data/scout/pretrip/workspaces \
  --layers osm,overpass,terrain,imagery,weather,reference-tracks,route,segments,checkpoints \
  --profile pi-online-explicit \
  --network-mode explicit-fetch \
  --allow-network-fetch
```

Offline/CI fixture contract:

```bash
python -m pretrip_layer_preparation \
  --project-id chilai_nanhua_day1 \
  --workspace-root /data/scout/pretrip/workspaces \
  --layers osm,overpass,terrain,imagery,weather,reference-tracks,route,segments,checkpoints \
  --profile pi-offline \
  --network-mode no-network
```

`--network-mode no-network` remains the default for CI fixtures, deterministic
tests, and offline replay. Operator preparation should use
`--network-mode explicit-fetch --allow-network-fetch` when network is available,
and must still write only pretrip planning artifacts. `pi-offline` is the Pi
lightweight profile for local/cache-only replay; `pi-online-explicit` is the
operator profile for connected Overpass preparation.

OSM raster tiles are not required when Overpass vector evidence is present.
Overpass and OSM raster basemaps come from related OSM data, but they serve
different purposes: Overpass is structured route-corridor evidence for CP/POI
synthesis, while raster tiles are visual basemap support. This alpha treats
Overpass as the required connected OSM data fetch and leaves raster tile cache
as optional operator-provided visual support.

## Offline Map Handoff

The fixed production path for offline raster imagery is:

```text
Mac build workstation
  -> pretrip_offline_map_handoff.py
  -> rsync handoff package to scout.local:/data/scout/
  -> Scout admin serves /admin/tiles/imagery/... from /data/scout/raster-tiles
```

Scout hardware should not be the primary raster tile cutting machine. It may
serve tiles and run `LayerPreparationJob` against already-installed refs, but
the route's user-provided imagery package is prepared on Mac first.

Canonical Mac command:

```bash
PYTHONPATH=. ./venv/bin/python pretrip_offline_map_handoff.py \
  --project-id chilai_nanhua_day1 \
  --source-geotiff ~/Downloads/271000x2663000-9x4-v2016_TWD97.tag.tiff \
  --source-kmz ~/Downloads/271000x2663000-9x4-v2016_TWD97.tag.kmz \
  --package-root /tmp/scout-offline-map-handoff/chilai_nanhua_day1 \
  --scout-data-root /data/scout \
  --min-zoom 5 \
  --max-zoom 14
```

Canonical transfer:

```bash
rsync -a /tmp/scout-offline-map-handoff/chilai_nanhua_day1/ \
  alexwang0315@scout.local:/data/scout/
```

The package includes:

- `raster-sources/<project_id>/`: user-provided GeoTIFF/KMZ source files.
- `raster-tiles/<project_id>/imagery/...`: PNG tile cache cut on Mac.
- `admin/pretrip-workspaces/<project_id>/outputs/layers/manifests/`: Scout
  runtime source manifest and raster tile plan.
- `offline_map_handoff_manifest.json`: install summary, project refs, rsync
  hint, source role, and no-network boundary metadata.

After transfer, `project.json` must point to the installed manifest refs:

```json
{
  "imagery_manifest_ref": "outputs/layers/manifests/chilai_nanhua_day1.local_raster_source_manifest.json",
  "local_raster_manifest_ref": "outputs/layers/manifests/chilai_nanhua_day1.local_raster_source_manifest.json",
  "raster_tile_manifest_ref": "outputs/layers/manifests/chilai_nanhua_day1.raster_tile_pyramid_plan.json",
  "imagery_source_kind": "user_provided_local_geotiff",
  "imagery_source_tiff_ref": "/data/scout/raster-sources/chilai_nanhua_day1/271000x2663000-9x4-v2016_TWD97.tag.tiff",
  "imagery_source_kmz_ref": "/data/scout/raster-sources/chilai_nanhua_day1/271000x2663000-9x4-v2016_TWD97.tag.kmz",
  "imagery_tile_cache_root": "/data/scout/raster-tiles"
}
```

Only after these refs exist should Scout run:

```bash
./.venv/bin/python pretrip_layer_preparation.py \
  --project-root /data/scout/admin/pretrip-workspaces/chilai_nanhua_day1 \
  --project-id chilai_nanhua_day1 \
  --layers osm,imagery,overpass,terrain,risk-score,risk-ribbon,route,reference-tracks,segments,checkpoints,pois,hazards,corridors,retreat,route-notes,weather \
  --profile pi-online-explicit \
  --network-mode explicit-fetch \
  --allow-network-fetch
```

The resulting imagery layer should be `ready_from_project_ref`. A
`ready_with_fallback` imagery layer means the handoff package or project refs
are missing and should be fixed on Mac, not papered over on Scout.

## Workspace Outputs（工作區輸出）

The `workspace`（工作區） outputs live under the selected project root:

```text
<project-root>/
  outputs/layers/
    layer_preparation_manifest.json
    layer_preparation_job.json
    layer_preparation_summary.json
    layer_adapter_manifest.json
    layer_validation_report.json
    projections/
      pretrip_map_layers.json
      admin_debug_events.jsonl
```

Expected contents:

- `layer_preparation_manifest.json`: full machine-readable job manifest with
  inputs, outputs, counts, adapter records, validation, network policy, and
  boundary flags.
- `layer_preparation_job.json`: job id, inputs, profile, network mode, requested
  layers, started/finished timestamps, and stage statuses.
- `layer_adapter_manifest.json`: per-layer `adapter`（轉接器） name, version,
  source refs, cache refs, network policy, and output refs.
- `layer_preparation_summary.json`: human-readable readiness summary for
  `/admin/pretrip`.
- `layer_validation_report.json`: blockers, warnings, stale sources, missing
  cache entries, invalid bbox/CRS, and capacity-limit results.
- `projections/pretrip_map_layers.json`: render-ready layer refs for the admin
  map stack.
- `projections/admin_debug_events.jsonl`: read-only debug projection events,
  not live runtime events.

## Adapter Lifecycle

Each layer adapter follows one `lifecycle`（生命週期）:

1. `plan`（規劃）: inspect project metadata, requested layers, bbox, profile,
   cache roots, capacity limits, and network mode.
2. `fetch`（抓取）: acquire source material only when policy permits it. In
   `no-network`, this stage may read existing local files or cache indexes but
   must not call external services.
3. `import`（匯入）: register local sources by path, size, checksum, source kind,
   license note, timestamp, and storage scope.
4. `normalize`（正規化）: convert source-specific shapes into Scout layer refs,
   bbox/CRS metadata, tile templates, summary geometry, and stable ids.
5. `summarize`（摘要）: produce compact status, counts, cache size estimates,
   staleness notes, and operator warnings.
6. `validate`（驗證）: fail closed on missing required refs, invalid coordinates,
   unsupported CRS, capacity overflow, prohibited public tile prefetch, or
   forbidden runtime/Brain mutation.
7. `project`（投影）: write only the workspace outputs listed above, including
   `/admin/pretrip` map-layer and `/admin/debug` projection artifacts.

Adapters may include route geometry, reference tracks, local OSM tile cache,
local raster imagery, terrain/DTM summaries, weather/daylight summaries, hazard
or POI candidates, and review-state overlays.

## DEM/DTM Visualization Preparation

`DEM/DTM Visualization Preparation`（DEM/DTM 地形視覺化準備） is the terrain
adapter path for admin display. It prepares visual layers from local DEM/DTM
while keeping raw rasters referenced by path/hash.

Required outputs may include:

- `terrain_hillshade`（陰影起伏圖）: shaded-relief raster or tile manifest.
- `terrain_elevation_tint`（高度分層色）: elevation color ramp raster/tile
  manifest.
- `terrain_slope_shading`（坡度著色）: slope-degree or percent-grade raster/tile
  manifest.
- `terrain_contours`（等高線）: contour GeoJSON or contour tile manifest.
- `terrain_route_samples`（沿線地形採樣）: compact route-aligned samples for
  elevation, slope, roughness, TEII_20m, and no-data coverage.
- `terrain_visualization`（地形視覺化摘要）: compact GeoJSON fallback/proxy
  that lets `/admin/pretrip` render hillshade, elevation tint, slope class, and
  contour markers before full DEM raster tiles are available.
- bitmap overlay refs for the alpha fallback:
  `terrain_hillshade_overlay_ref`, `terrain_elevation_tint_overlay_ref`,
  `terrain_slope_shading_overlay_ref`, and `terrain_contours_overlay_ref`.

Preferred production pipeline:

```text
DEM/DTM GeoTIFF
  -> GDAL hillshade
  -> GDAL slope
  -> GDAL color-relief for slope shading
  -> GDAL contour
  -> cut local tiles / GeoJSON
  -> /admin/pretrip display
```

Alpha implementations may emit a single bitmap overlay per terrain mode before
full local tile cutting is ready, but the manifest must mark the processor
(`gdal` vs fallback), the cell resolution, the corridor width, and whether raw
DEM/DTM payloads were embedded.

The alpha DTM bitmap fallback renders a route corridor rather than isolated
point markers: slope is calculated from the DEM/DTM grid at source resolution
(`20m` for the Chilai alpha material), then projected into PNG overlays covering
the configured route corridor (`route_corridor_m=500`, i.e. 1000m total width).
The overlay metadata must expose `cell_resolution_m`,
`corridor_half_width_m`, `bitmap_overlay=true`, `route_aligned_proxy=false`,
and `runtime_safety_truth=false`.

Suggested slope shading classes:

```text
0-10 deg   light green
10-20 deg  yellow-green
20-30 deg  yellow
30-40 deg  orange
40-50 deg  deep yellow / orange-red
>50 deg    red
```

The terrain visualization adapter must record:

- source DEM/DTM refs, checksums, CRS, vertical datum, resolution, bbox, and
  no-data policy;
- slope algorithm, window size, smoothing, and unit (`degree` or
  `percent_grade`);
- color ramp version and class thresholds;
- tile pyramid or GeoJSON simplification metadata;
- whether each layer is ready, missing, partially covered, or fallback-only.
- when the alpha fallback uses route-aligned samples instead of a full raster
  tile pyramid, it must mark `route_aligned_proxy=true` and
  `full_raster_hillshade_generated=false`.
- when the alpha fallback emits bitmap overlays from local DTM grid cells, it
  must preserve the DEM/DTM cell resolution for slope calculation and mark
  `bitmap_overlay=true`, `route_aligned_proxy=false`, and the corridor half
  width.

`terrain visualization layer`（地形視覺化圖層） is separate from `risk heat layer`
（風險熱區圖層）. Hillshade, elevation tint, slope shading, and contours explain
terrain evidence; `risk-score`, `risk-ribbon`, `risk-heatmap`, and `risk-delta`
remain route-specific candidate risk overlays. The layer job must not present
slope shading alone as an accepted hazard or runtime safety truth.

The same `terrain_visualization.raster_overlays` projection is consumed by
`/admin/pretrip` and `/admin/debug`. Debug rendering is read-only and uses the
existing `/admin/pretrip/projects/{project_id}/terrain-overlays/{mode}.png`
endpoint; it must not create a separate terrain truth source.

## Clean Rebuild And Durable Evidence Refs

Scout alpha rebuilds can move the existing workspace aside and regenerate GPX
and layer-preparation outputs from source material. Rebuild tooling must
preserve durable admin evidence artifacts that importer and map preparation do
not regenerate, including:

- `readiness_report_ref`;
- `resource_plan_ref`;
- `planned_eta_ref`;
- `departure_bundle_manifest_ref`;
- `route_comparison_ref`;
- capability timeline refs when present.

The restore path may copy only project-relative refs that remain inside the
source and destination workspace roots. It must not overwrite a destination
artifact that already exists. After restoring durable refs, the review queue and
admin/debug projections may be refreshed as workspace-only projections. This
keeps clean/overwrite reruns from dropping timeline/evidence surface content
while still rebuilding route, Overpass, terrain, imagery, and risk layers from
current source material.

## Overpass Route-Corridor Fetch

`Overpass Route-Corridor Fetch`（依路線走廊擷取 OSM 向量） is owned by
`LayerPreparationJob`（圖層準備工作）, because the layer job knows the selected
golden route, route bbox, route display geometry refs, and requested layer
boundary. The adapter must not issue a route-independent Overpass query.

Current behavior:

- derive `route_bbox_wgs84` from the selected golden route summary;
- expand it by `route_corridor_m` into `bbox_wgs84`, which is the actual query
  bbox for OSM/Overpass evidence;
- write a planned Overpass QL request at
  `outputs/layers/plans/overpass_query.ql`;
- in `no-network`, stop there and mark zero network calls;
- in `explicit-fetch` plus `allow_network_fetch`, fetch the raw Overpass JSON,
  store `normalized/map/overpass_phase_a_raw.json`, normalize it with
  `pretrip_overpass_ingest`, and write `candidates/overpass_evidence.json` plus
  `normalized/map/overpass_vector_evidence.geojson`.

All Overpass outputs are **pretrip candidate evidence**（行前候選證據）. They
can feed `/admin`, `/admin/pretrip`, and `/admin/debug`, but cannot become
runtime safety truth（現場安全真值） or mutate Phase 1/Phase 2 state.

## Network Flag Boundary

`network flag boundary`（網路旗標邊界） rules:

- default mode is `no-network` for fixtures and replay; normal operator
  preparation uses explicit connected Overpass fetch;
- `fetch` is the only lifecycle stage that may ever use live network;
- live fetch requires both `--network-mode explicit-fetch` and
  `--allow-network-fetch`;
- each live adapter must declare provider, timeout, cache root, rate-limit
  policy, source license, and raw-payload storage policy before it runs;
- public OSM bulk/offline tile download remains prohibited. OSM raster tile
  cache is optional visual support; Overpass vector evidence is the alpha
  path for connected OSM data preparation;
- no network flag may permit `/safety/*` mutation, Phase 2 Brain writeback,
  provider webhook sends, or final `MissionGraph` generation.

## Pi Lightweight Mode

`Pi lightweight mode`（Pi 輕量模式） is the default deployment profile for Scout
hardware:

- reads only local project files and explicit cache roots;
- skips heavyweight raster conversion unless precomputed manifests or tile
  plans already exist;
- prefers manifests, bbox summaries, tile-count plans, transparent fallbacks,
  and debug projections over large generated assets;
- writes under `/data/scout/pretrip/workspaces` or configured cache roots, not
  repo fixtures;
- keeps raw GPX, GeoTIFF, DTM, and tile payloads referenced by checksum/path;
- reports blocked or missing heavy layers as warnings unless the project policy
  marks them required.

## Success Criteria

- The command can produce a complete `layer_preparation_job.json`,
  `layer_adapter_manifest.json`, summary, validation report, and admin
  projections for a fixture-backed pretrip project.
- `no-network` mode records zero live network calls and remains valid on Scout
  Pi.
- Every adapter records source refs, output refs, network policy, and validation
  status.
- Workspace writes stay under the selected project output directory or declared
  cache roots.
- The job never mutates Phase 1 runtime state, Phase 2 Brain state, incident
  stores, provider send queues, or final `MissionGraph` artifacts.
- `/admin/pretrip` can render layer readiness from the projection output, and
  `/admin/debug` can show the job timeline as read-only projection events.
