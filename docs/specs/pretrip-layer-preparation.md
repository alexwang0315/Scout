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

Initial `CLI`（命令列介面） contract:

```bash
python -m pretrip_layer_preparation \
  --project-id chilai_nanhua_day1 \
  --workspace-root /data/scout/pretrip/workspaces \
  --layers osm,overpass,terrain,imagery,weather,reference-tracks,route,segments,checkpoints \
  --profile pi-offline \
  --network-mode no-network
```

`--network-mode no-network` is the default and must be valid on Mac/PC and Pi.
A future connected run must require an explicit network flag, for example
`--network-mode explicit-fetch --allow-network-fetch`, and must still write only
pretrip planning artifacts. `pi-offline` is the current Pi lightweight profile
for the implementation; it means Pi 輕量模式（只讀本機工作區與快取摘要）。

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

- default mode is `no-network`;
- `fetch` is the only lifecycle stage that may ever use live network;
- live fetch requires both `--network-mode explicit-fetch` and
  `--allow-network-fetch`;
- each live adapter must declare provider, timeout, cache root, rate-limit
  policy, source license, and raw-payload storage policy before it runs;
- public OSM bulk/offline tile download remains prohibited unless the provider
  is replaced with a self-hosted or explicitly offline-prefetch-permitted
  source;
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
