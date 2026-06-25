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

For the fixed end-to-end operator sequence that combines GPX import, connected
map preparation, Rudy/Rudy+TW OCR, raster label normalization, route context,
Boss synthesis, 32-layer verification, browser smoke checks, and Scout deploy
handoff, see `docs/specs/scout-pretrip-preparation-pipeline.md`.

This spec owns only the preparation-backed layer run. The admin map UI contract
is larger; see `docs/specs/scout-admin-map-layer-contract.md`.

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
  --layers osm,imagery,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,cwa-qpf,soil-moisture,antecedent-rain,cwa-weather,weather,reference-tracks,route,segments,checkpoints,mcp,pois,hazards,corridors,retreat,route-notes \
  --profile pi-online-explicit \
  --network-mode explicit-fetch \
  --allow-network-fetch \
  --seed-imagery-cache \
  --imagery-provider-allows-offline-prefetch
```

Offline/CI fixture contract:

```bash
python -m pretrip_layer_preparation \
  --project-id chilai_nanhua_day1 \
  --workspace-root /data/scout/pretrip/workspaces \
  --layers osm,imagery,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,cwa-qpf,soil-moisture,antecedent-rain,cwa-weather,weather,reference-tracks,route,segments,checkpoints,mcp,pois,hazards,corridors,retreat,route-notes \
  --profile pi-offline \
  --network-mode no-network
```

The preparation `--layers` input is intentionally smaller than the 32-layer
admin map contract. Valid preparation-backed layer ids are:

```text
osm, imagery, overpass, terrain, risk-score, risk-ribbon, risk-heatmap,
risk-delta, cwa-qpf, soil-moisture, antecedent-rain, cwa-weather, weather,
reference-tracks, route, segments, checkpoints, mcp, pois, hazards, corridors,
retreat, route-notes
```

Do not pass `rudy`, `rudy-twmap`, `relief`, `geology`, `topo-5k`, `forest`,
`completed-track`, `boss-points`, `events`, or `weather-api` to this command.
Those are runtime-only WMTS/UI/post-process contract layers
（執行時圖磚、介面、或後處理契約圖層） and are verified by
`tools/verify_scout_layer_contract.py` and browser smoke tests. `weather-api`
maps to the preparation alias `weather`; `boss-points` are synthesized after
risk/route-pressure artifacts exist.

## Runtime Tile Vs Preparation Cache Boundary

`Runtime tile`（執行時圖磚） and `preparation cache`（準備階段快取） are separate
contracts. Scout must not treat every visible basemap as a preparation raster
source.

The accepted map-source split is:

| Source family | Preparation cache? | Runtime display? | Scout role |
|---------------|--------------------|------------------|------------|
| Rudy+TW (`rudy-twmap`) | Yes, when explicitly requested for route bbox OCR. | Yes. | Authoritative hiking rendered-map evidence（登山圖面證據） for mileage K, stable POI, trail labels, rendered icons, and route-context OCR. |
| Rudy without TW overlay (`rudy`) | No by default. | Yes. | Optional hiking basemap/reference. It must not be mixed with the Rudy+TW OCR evidence source unless a later spec explicitly promotes it. |
| NLSC WMTS layers | No. | Yes. | Runtime basemap/context only, for example `EMAP5`, `PHOTO_MIX`, `B5000`, `TOPO25K`, `MOI_HILLSHADE`, `GeoSensitive2`. |
| OSM XYZ/WMTS/vector tiles | No. | Yes. | Runtime basemap for public/city/lowland readability. Structured OSM evidence comes from Overpass or future PBF parsing, not tile OCR. |
| TWMap/other public WMTS/XYZ | No. | Yes. | Runtime visual reference unless a source-specific OCR/cache policy is accepted later. |
| DEM/DTM, risk, CWA, GEE | Not map-tile cache. | Yes as Scout evidence overlays. | Workspace evidence artifacts and derived visualizations, not basemap tile providers. |

Only Rudy+TW may currently create a route-bbox map cache for OCR and rendered
map evidence extraction. All other WMTS/XYZ providers must be represented in a
tile-provider registry and fetched by the browser/admin tile proxy at runtime.
They must not be pre-cut into `/data/scout/raster-tiles` as a preparation
shortcut, and their absence from preparation outputs is not a missing-layer
failure.

The Rudy+TW cache is not only a visual cache. It is the stable source for
`rendered_map_poi_candidate`（圖面渲染 POI 候選）, mileage anchors, trail labels,
communication-point labels, temples/buildings, power-line/tower cues, and
other hiking-map facts that are visible on the authoritative rendered map.
Historical/reference GPX notes may support freshness and risk interpretation,
but they must not be the primary source for stable POI facts.

### NLSC No-Application Runtime Service Catalog

The local PDF `~/Downloads/免申請服務介接說明表.pdf` is the current operator-provided
catalog for National Land Surveying and Mapping Center
(`NLSC`, 內政部國土測繪中心) services that can be integrated without an application
step. The table date is `113/1/3`（民國 113 年 1 月 3 日, 2024-01-03）.

This catalog should seed Scout's `tile_provider_registry`（圖磚來源登錄表） and
map-context API registry. It does **not** change the preparation-cache boundary:
NLSC layers remain runtime WMTS/WMS/API providers unless a later spec explicitly
promotes one source into a cache/OCR role. Before enabling a layer, the
implementation must verify the advertised service type through NLSC
`GetCapabilities` or `MapLayerInfo`（圖層圖資說明） because PDF text extraction
does not preserve the WMTS/WMS/API checkmark columns reliably.

NLSC no-application candidates relevant to Scout:

| Category | Codes from the PDF | Scout usage |
|----------|--------------------|-------------|
| Electronic maps（電子地圖） | `EMAP`/`EMAP5`, `EMAP6`, `EMAP15`, `EMAP16`, `EMAP01`, `EMAP2`, `EMAP12`, `EMAP9`, `EMAP8`, `EMAP7`, `EMAP5_OPENDATA`, `EMAP6_OPENDATA`, `EMAP3826`, `EMAP3525` | Runtime basemap alternatives for general readability, contour/no-contour comparison, English UI, transparent overlays, and non-hiking/city-tour scenarios. |
| Orthophoto imagery（正射影像） | `PHOTO2`, `PHOTO_MIX`, `PHOTO3826` | Runtime imagery basemap and route-context visual inspection. It must not be bulk cached by map preparation. |
| Land-use context（國土利用） | `LUIMAP`, `LUIMAP*`, `LandUsePointQuery` (`COM_017`) | Runtime overlay and point query evidence for land-use context; candidate-only review material. |
| Topographic and aerial map products（地形圖與像片基本圖） | `B5000`, `B25000`, `B50000`, `B100000`, `TOPO01K*`, `TOPO05K*`, `P5K*` | Runtime topographic/orthophoto reference layers. `*` means multiple year/area layers must be discovered from capabilities/API metadata instead of hardcoding a single id. |
| UAS orthophoto（無人飛行載具航拍正射影像） | `UAV*` | High-value runtime imagery for disaster/revalidation review. This family is especially important for recent local slope, washout, landslide, riverbed, and route-access changes where satellite or countywide orthophoto is too coarse or stale. It must be registered as a first-class provider group, discovered by year/area coverage, and displayed as candidate-only visual evidence. |
| Administrative, cadastral, and facility context（行政、地籍、設施） | `SCHOOL`, `ConvenienceStore`, `ROAD`, `LANDSECT`, `LANDSECT2`, `LandOffice`, `CITY`, `TOWN`, `Village` | Runtime context overlays or API-backed query evidence. Useful for lowland/city routes and administrative provenance, not direct safety truth. |
| Terrain-derived map products（地形衍生圖） | `MOI_ASPECT`, `MOI_CONTOUR_2`, `MOI_CONTOUR`, `MOI_HILLSHADE`, `MOI_SHADERMAP`, `MOI_SLOPEP_GT30_2`, `MOI_SLOPEP_GT30`, `MOI_SLOPEP_LV7_2`, `MOI_SLOPEP_LV7` | Runtime visual terrain context that complements Scout DEM/DTM-derived terrain artifacts. These are not a substitute for local DEM/DTM feature computation. |
| Open API services（開放 API） | `COM_001`-`COM_017` including point-to-administrative-area queries, county/town/section/village lists, village KML, facility buffer queries, layer metadata, road/intersection queries, and land-use point query | Query-time supporting evidence for route context, geocoding/administrative joins, facility discovery, and source metadata. |
| Map-entry APIs（圖臺入口 API） | `WEB_001`-`WEB_005` | External handoff/deep-link support for opening NLSC map views; not a Scout evidence artifact by itself. |

Scout priority for the next runtime provider slice:

1. Register electronic map and orthophoto providers (`EMAP5`, `EMAP6`,
   `EMAP8`, `PHOTO2`, `PHOTO_MIX`) as runtime basemaps.
2. Register terrain-reference providers (`B5000`, `B25000`, `MOI_HILLSHADE`,
   `MOI_SHADERMAP`, `MOI_CONTOUR_2`, `MOI_SLOPEP_LV7_2`) as runtime overlays.
3. Register UAS orthophoto (`UAV*`) as a high-priority runtime provider family
   for route revalidation, post-event visual comparison, and local change
   review. Its child layers must be discovered by coverage/year metadata before
   display.
4. Register `LUIMAP` and administrative/cadastral overlays as optional
   context, off by default.
5. Register `COM_013 MapLayerInfo` as the preferred metadata lookup for layer
   descriptions and dynamically expanded `*` layer families.

In-house pre-trip preparation is connected by design. Before departure, the
operator should use `--network-mode explicit-fetch --allow-network-fetch
--seed-imagery-cache --imagery-provider-allows-offline-prefetch` so the
workspace stores the route corridor's vector evidence, Rudy+TW OCR/cache
evidence when selected, terrain overlays, route context, mileage anchors,
CP/MCP/Boss artifacts, and review queues while power and bandwidth are
available.
`--network-mode no-network` is only the CI fixture, deterministic test, or
outdoor replay posture. `pi-offline` is the Pi lightweight profile for
local/cache-only replay after departure; `pi-online-explicit` is the connected
operator profile for pre-trip materialization.

OSM raster tiles are not required when Overpass vector evidence is present.
Overpass and OSM raster basemaps come from related OSM data, but they serve
different purposes: Overpass is structured route-corridor evidence for CP/POI
synthesis, while OSM/NLSC/TWMap tiles are visual basemap support. This alpha
treats Overpass as the connected structured OSM data fetch and treats Rudy+TW
as the only approved rendered-map cache/OCR material for hiking POI, mileage,
and named-label extraction. OSM tiles, NLSC tiles, and other WMTS/XYZ basemaps
remain runtime-only.

## Offline Map Handoff

The legacy production path for offline user-provided raster imagery is:

```text
Mac build workstation
  -> pretrip_offline_map_handoff.py
  -> rsync handoff package to scout.local:/data/scout/
  -> Scout admin serves /admin/tiles/imagery/... from /data/scout/raster-tiles
```

Scout hardware should not be the primary raster tile cutting machine. It may
serve tiles and run `LayerPreparationJob` against already-installed refs, but
the route's user-provided imagery package is prepared on Mac first.

This handoff path does **not** authorize caching every runtime WMTS/XYZ source.
For new preparation work, Rudy+TW is the only map provider allowed to create a
route-bbox cache for OCR. NLSC, OSM, TWMap, and other WMTS/XYZ layers should be
displayed by runtime tile templates instead. Existing `/data/scout/raster-tiles`
content must not be cleared to force a rerun; it is preserved unless a documented
stale/missing/invalidation condition applies.

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
  --layers osm,imagery,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,cwa-qpf,soil-moisture,antecedent-rain,cwa-weather,weather,reference-tracks,route,segments,checkpoints,mcp,pois,hazards,corridors,retreat,route-notes \
  --profile pi-online-explicit \
  --network-mode explicit-fetch \
  --allow-network-fetch \
  --seed-imagery-cache \
  --imagery-provider-allows-offline-prefetch
```

The resulting imagery layer should be `ready_from_project_ref`. A
`ready_with_fallback` imagery layer means the handoff package or project refs
are missing and should be fixed on Mac, not papered over on Scout.

When imagery has moved to WMTS runtime delivery, `imagery` may instead report
`wmts_runtime_only`. That is valid for display layers and does not authorize
deleting `/data/scout/raster-tiles`; the raster cache may still be needed for
offline replay, OCR, or older handoff packages.

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
    raster_label_ocr_output.json
    raster_label_adapter_manifest.json
    normalized/raster_label_evidence.geojson
    projections/
      pretrip_map_layers.json
      admin_debug_events.jsonl
  normalized/context/route_context/
    route_context_evidence.json
    source_manifest.json
    route_context_pack.json
    crawl_seed_plan.json
  candidates/
    route_context_points.json
    route_mileage_k_anchors.json
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
- `raster_label_ocr_output.json`: Rudy/Rudy+TW OCR stage output or explicit
  blocked-dependency/missing-tile status. It is adapter input, not route
  context directly.
- `cache/raster_label_ocr_tiles/*.json`: per-tile OCR result cache keyed by
  tile image SHA-256, OCR engine version, engine name, and language. Empty OCR
  results are cached too, so rerunning map preparation does not repeatedly run
  Tesseract on unchanged tiles.
- `normalized/raster_label_evidence.geojson`: normalized candidate-only raster
  label evidence produced through the adapter contract.
- `route_context_points.json` and `route_mileage_k_anchors.json`: route context
  and trail-K anchors refreshed by map preparation after raster label evidence
  is available.
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
- capability timeline refs when present;
- imported Scout workspace template refs and template import candidate refs when
  present.

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
- runs Rudy/Rudy+TW OCR only when explicit imagery tile cache preparation is
  permitted, otherwise records a blocked OCR stage instead of fabricating
  mileage anchors;
- keeps imagery tile cache entries fresh for 30 days by default, refreshing
  only stale or missing tiles; OCR result cache is invalidated by tile image
  hash and OCR engine/language/version rather than by clearing the workspace;
- prefers manifests, bbox summaries, tile-count plans, transparent fallbacks,
  and debug projections over large generated assets;
- writes under `/data/scout/pretrip/workspaces` or configured cache roots, not
  repo fixtures;
- keeps raw GPX, GeoTIFF, DTM, and tile payloads referenced by checksum/path;
- reports blocked or missing heavy layers as warnings unless the project policy
  marks them required.

## Operator Rerun Checklist

When rerunning importer + map preparation on Scout hardware, the operator must
verify these items before declaring the workspace refreshed:

1. Preserve raster tile cache unless a documented cache invalidation condition
   is met. `/data/scout/raster-tiles` is refreshed by stale/missing policy, not
   by deletion. A small increase in tile count after a connected run can mean
   only missing or stale tiles were fetched.
2. Preserve OCR cache unless the tile image hash, OCR engine, language, or
   engine version changes. Empty OCR results are valid cache entries.
3. Check terrain source coverage separately from display overlay count. Four
   terrain overlay PNGs mean four display modes; the actual DTM/DEM source tile
   count, grid-cell count, and no-data coverage must be read from the terrain
   visualization and DTM coverage artifacts.
4. Check CWA evidence by feature family. `0` warning features can be a valid
   result when no active CWA warning intersects the route/bbox; it does not
   mean observation or QPF fetch failed.
5. Check GEE evidence by status. `soil-moisture` and `antecedent-rain` may
   produce a `missing_credentials` status feature when `SCOUT_GEE_ENABLED`,
   Earth Engine credentials, or the live fetcher are unavailable. This is a
   candidate status overlay, not SMAP/GPM numeric evidence. When credentials
   are present and explicit fetch is attempted, `fetch_failed` with a
   `gee_http_error:403` blocker means Google Earth Engine access or the Cloud
   project registration is still incomplete; it must not be collapsed back to
   `missing_credentials`. On Scout Pi deployments, do not override
   `/data/scout/secrets/live-runtime.env` GEE values with empty
   `docker-compose` environment defaults, or the credential path will disappear
   inside the container. GEE numeric values are **no-cache evidence**
   (不快取的數值取證): `gee_raw_summary.json`, SMAP/GPM GeoJSON, corridor
   summaries, and timeseries files are the current preparation run's evidence
   snapshot only. They must declare `cacheable: false`, `ttl_seconds: 0`, and
   `must_refetch_on_prepare: true`; a later preparation run must call GEE again
   under `network_mode=explicit-fetch` instead of reusing earlier SMAP/GPM
   numbers as environmental state.
6. Confirm Boss/route-pressure artifacts after risk outputs exist. Boss Points
   are generated as a post-process and remain part of the 32-layer UI contract,
   not a `--layers` input.
7. Run both gates:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
     --repo-root .

   PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
     --repo-root . \
     --project-root /data/scout/admin/pretrip-workspaces/chilai_nanhua_day1 \
     --require-workspace
   ```

8. Run the browser smoke gate when Playwright is available:

   ```bash
   node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
   ```

9. Verify Scout URLs through `scout.local`, not only loopback:
   `/admin/pretrip?tiles=local`, `/admin/debug?tiles=local`, and
   `/admin?tiles=local`.

The expected successful connected run has a preparation manifest whose
`requested_layers` are the 23 preparation-backed layers above. The admin UI may
still expose 31 or 32 controls depending on surface: `completed-track` is
after-action/admin only and should not appear on `/admin/pretrip` or
`/admin/debug`.

## Success Criteria

- The command can produce a complete `layer_preparation_job.json`,
  `layer_adapter_manifest.json`, summary, validation report, and admin
  projections for a fixture-backed pretrip project.
- `no-network` mode records zero live network calls and remains valid on Scout
  Pi.
- Every adapter records source refs, output refs, network policy, and validation
  status.
- Raster OCR, adapter normalization, route-context refresh, and mileage tag
  alignment are orchestrated by map preparation so prepared workspaces open with
  CP/MCP/Boss/mileage evidence already materialized.
- Workspace writes stay under the selected project output directory or declared
  cache roots.
- The job never mutates Phase 1 runtime state, Phase 2 Brain state, incident
  stores, provider send queues, or final `MissionGraph` artifacts.
- `/admin/pretrip` can render layer readiness from the projection output, and
  `/admin/debug` can show the job timeline as read-only projection events.
