# Scout Admin Map Layer Contract

This contract prevents recurring GPX import, map preparation, and admin GIS
regressions. The machine-readable source of truth is
`scout_layer_contract.py`; this document is the human-readable checklist.

All layers are pretrip/admin candidate evidence or UI context unless explicitly
stated otherwise. None of these layers may mutate Phase 1 runtime safety truth.

## Contract Vs Preparation Boundary

The 32 layers in this document are the admin map UI contract
（管理介面地圖圖層契約）. They are not the same thing as the
`pretrip_layer_preparation.py --layers` input list.

`pretrip_layer_preparation.py` accepts only preparation-backed layers
（可由行前準備流程產生或更新的圖層）:

```text
osm, imagery, overpass, terrain, risk-score, risk-ribbon, risk-heatmap,
risk-delta, cwa-qpf, soil-moisture, antecedent-rain, cwa-weather, weather,
reference-tracks, route, segments, checkpoints, mcp, pois, hazards, corridors,
retreat, route-notes
```

Do not pass the full 32-layer contract list to `--layers`. Runtime-only WMTS
or UI layers such as `rudy`, `rudy-twmap`, `relief`, `geology`, `topo-5k`,
`forest`, `completed-track`, `boss-points`, `events`, and `weather-api` are
validated through the layer contract and browser smoke gates instead.
`boss-points` are synthesized as a preparation post-process when risk and
route-pressure inputs exist; `weather-api` is an overlay/status layer whose
preparation alias is `weather`.

This distinction is intentional:

- 32-layer contract gate: verifies controls, ordering, `data-layer-group`
  presence, surface-specific availability, and source/provenance contracts.
- 23-layer preparation run: refreshes workspace artifacts, refs, summaries,
  environment evidence placeholders, terrain outputs, OCR/mileage, route
  context, and risk outputs.
- WMTS-only（執行時圖磚）layers do not require workspace artifacts and must not be
  treated as missing preparation output.
- `completed-track` is after-action/admin only; it must be absent from
  `/admin/pretrip` and `/admin/debug` controls but present on `/admin`.

## Tile Provider And Cache Policy

The admin map supports many basemap providers, but only one rendered-map source
is currently allowed to enter route-bbox cache preparation:

```text
Rudy+TW = preparation cache + OCR + rendered hiking POI evidence
All other WMTS/XYZ basemaps = runtime tile delivery only
```

`Rudy+TW`（Rudy 疊 TW 登山圖） is the authoritative rendered hiking map source
for Scout's stable trail POI extraction. It may be cached for the selected
route bbox and used by OCR/icon extraction to produce mileage K anchors,
trail-name labels, temples/buildings, power-line/tower cues, communication
labels, and other `rendered_map_poi_candidate` evidence.

The following layers must be runtime tile providers only unless a future ADR or
spec explicitly changes their source role:

- NLSC WMTS layers such as `EMAP5`, `PHOTO_MIX`, `PHOTO2025`, `B5000`,
  `TOPO25K_114`, `MOI_HILLSHADE`, `MOI_SHADERMAP`, `MOI_SLOPEP_LV7_2`,
  `GeoSensitive2`, and `DDEM05`;
- OSM XYZ/WMTS/vector tile layers used for public/city/lowland readability;
- TWMap or other public WMTS/XYZ visual layers;
- Rudy without the TW overlay, unless separately promoted to an OCR source.

Runtime tile layers may use browser cache or the admin tile proxy for display,
zoom fallback, and provider isolation. They must not be bulk pre-cut into
`/data/scout/raster-tiles` by map preparation, and their absence from
`pretrip_layer_preparation.py` outputs is not a failed layer. This is especially
important for NLSC and OSM: they are valuable runtime basemaps, but they are not
the hiking POI authority in the current pretrip preparation design.

Historical/reference GPX notes remain route-condition evidence. They may
support hazard freshness, slow-passage interpretation, detour context, MCP/Boss
pressure, and candidate explanations. They should not be the primary source for
stable POI facts when Rudy+TW rendered-map evidence is available.

### Local OSM PBF Evidence

Scout may derive structured OSM evidence from a local full-region `.osm.pbf`
file when pretrip map preparation is running offline. This is not a raster
basemap and must not create a new layer id. The resulting route-corridor extract
is Overpass-compatible for UI and downstream risk tooling, but its provenance
must clearly state `source = local_osm_pbf`.

Contract requirements:

- parse only a route corridor extract, not the full Taiwan PBF in-process;
- keep artifacts candidate-only and `runtime_safety_truth = false`;
- preserve PBF path, PBF hash when available, bbox/corridor, extraction command
  plan, raw OSM JSON hash, parser version, OSM object type/id/tags/geometry,
  and normalized GeoJSON ref;
- preserve the original download URL when known. For the current Taiwan alpha
  snapshot, this is
  `http://download.geofabrik.de/asia/taiwan-latest.osm.pbf`, stored locally as
  `~/downloads/taiwan-260624.osm.pbf`. UI/provenance text should describe it as
  "latest at download time"（下載當下最新版）, not a continuously updated local file;
- enforce a default `cache_ttl_days = 30` for the local PBF snapshot. Within TTL,
  Scout reuses the downloaded file and must not redownload `taiwan-latest.osm.pbf`
  every preparation run. After TTL, the layer remains candidate evidence but
  must expose `cache_status = stale_refresh_recommended` and
  `refresh_required = true` so a connected operator can refresh it explicitly;
- preserve a small route-bbox extract inside the workspace for OSM layer
  rendering. The preferred source is
  `normalized/map/osm_pbf_route_bbox.osm.pbf` when available, with
  `normalized/map/osm_pbf_phase_a_raw.osm.json` as the small filtered OSM JSON
  fallback. The `osm` layer must expose `local_osm_render_extract_ref`,
  `local_osm_render_extract_manifest_ref`, source kind, feature count, and
  `osm_rendering_policy = workspace_local_osm_extract_available` when this local
  extract exists;
- lifecycle for the `overpass` layer should show
  `completed_local_osm_pbf_extract`, not `completed_live_fetch`;
- the `osm` layer may report `covered_by_overpass_vector_evidence` because the
  same compatible vector-evidence ref feeds the map context, but UI wording
  should distinguish live Overpass from local OSM PBF when showing provenance.

### NLSC No-Application Services

The operator-provided
`~/Downloads/免申請服務介接說明表.pdf` is the current no-application service catalog
from NLSC（內政部國土測繪中心）. The table is dated `113/1/3`
（2024-01-03） and lists WMTS/WMS/API candidates that Scout can integrate
without a separate application step.

This contract treats those services as runtime provider candidates. They should
be added to the map provider registry and surfaced through layer controls after
the implementation verifies each service through WMTS/WMS `GetCapabilities` or
NLSC `MapLayerInfo`（圖層圖資說明）. They must not be bulk cached by pretrip map
preparation unless a later spec explicitly changes the source role.

Catalog groups to preserve in the provider registry:

| Provider group | NLSC codes | UI role |
|----------------|------------|---------|
| NLSC electronic maps | `EMAP`/`EMAP5`, `EMAP6`, `EMAP15`, `EMAP16`, `EMAP01`, `EMAP2`, `EMAP12`, `EMAP9`, `EMAP8`, `EMAP7`, `EMAP5_OPENDATA`, `EMAP6_OPENDATA`, `EMAP3826`, `EMAP3525` | Basemap and transparent overlay options. Good for general/city routes and non-hiking readability. |
| NLSC orthophoto | `PHOTO2`, `PHOTO_MIX`, `PHOTO3826` | Runtime imagery basemap; bottom visual layer. |
| NLSC land-use | `LUIMAP`, `LUIMAP*`, `COM_017 LandUsePointQuery` | Optional land-use overlay or point-query context. |
| NLSC topo/aerial products | `B5000`, `B25000`, `B50000`, `B100000`, `TOPO01K*`, `TOPO05K*`, `P5K*` | Runtime topographic or aerial reference overlays. |
| NLSC UAS orthophoto | `UAV*` | High-value runtime imagery for route revalidation, post-disaster visual comparison, and local slope/washout/landslide/riverbed change review. Must be a first-class provider group, not buried under generic topo products. |
| NLSC admin/cadastral/facility | `SCHOOL`, `ConvenienceStore`, `ROAD`, `LANDSECT`, `LANDSECT2`, `LandOffice`, `CITY`, `TOWN`, `Village` | Runtime context overlays or API-backed supporting evidence. |
| NLSC terrain-derived maps | `MOI_ASPECT`, `MOI_CONTOUR_2`, `MOI_CONTOUR`, `MOI_HILLSHADE`, `MOI_SHADERMAP`, `MOI_SLOPEP_GT30_2`, `MOI_SLOPEP_GT30`, `MOI_SLOPEP_LV7_2`, `MOI_SLOPEP_LV7` | Runtime terrain reference overlays; complementary to Scout DEM/DTM evidence. |
| NLSC open APIs | `COM_001`-`COM_017` | Route-context queries, administrative joins, road/intersection lookup, facility buffers, and layer metadata. |
| NLSC map-entry APIs | `WEB_001`-`WEB_005` | External deep-link/open-in-NLSC-map support only. |

Layer families with `*` are multi-layer families. The UI must discover the
actual layer ids from capabilities/metadata before listing every child layer.
Do not hardcode one `LUIMAP*`, `TOPO*`, `P5K*`, or `UAV*` child as if it were
the whole family. `UAV*` deserves separate coverage/year metadata, because UAS
orthophoto（無人飛行載具航拍正射影像） can be far more valuable than ordinary
basemaps for local route-condition review.

### Official Communication-Point Evidence

The Forestry and Nature Conservation Agency dataset
`data.gov.tw/dataset/106640`（林業及自然保育署山區手機可通訊點標示） is an
official point-evidence source, not a tile provider. It must not create a new
Scout layer id or bypass the 32-layer contract. Normalized records should render
through:

- `pois` for communication-point POI markers;
- `checkpoints` when the point is close enough to the planned route to become a
  proposed route checkpoint;
- timeline `Map / Risk` or `CP / Timeline` evidence groups, depending on
  whether the point is corridor context or a selected checkpoint.

Display requirements:

- primary label should combine route/trail name and marked location, for
  example `嘉明湖國家步道 1.5K 通訊點`;
- detail text should list available carrier names and original source agency;
- marker styling should distinguish official communication points from OCR
  labels and reference-GPX notes;
- labels remain above markers, route lines, terrain/risk overlays, and raster
  basemaps according to the general map z-order rule.

Provenance requirements:

- preserve data.gov.tw dataset id `106640`, MOA open-data id `G07`, resource id,
  source URL, request timestamp, raw payload hash, parser version, original
  record id, original KML/HTML fields, WGS84 lon/lat, and any TWD97 coordinates;
- record update cadence as annual and expose a stale-risk flag when the local
  package is older than the configured TTL;
- do not treat carrier names as guaranteed reception. The evidence means "this
  is an official marked communication attempt point"（官方標示可嘗試通訊點）, not
  "communication will work now"（即時通訊保證）.

## Regression Notes From Operator Reruns

The following mistakes are easy to repeat and are considered contract
regressions:

- Treating a preparation manifest with 23 ready layers as incomplete because
  the UI contract contains 32 layers. The missing nine are runtime-only or
  post-process/UI contract layers, not preparation inputs.
- Treating `rudy` or `rudy-twmap` as failed just because they do not appear in
  `pretrip_layer_preparation.py --layers`. Their UI controls are runtime layer
  controls; Rudy+TW may still be selected separately as the only current
  preparation cache/OCR source.
- Caching NLSC, OSM, TWMap, or other WMTS/XYZ basemaps during map preparation
  because they are visible in the UI. They are runtime tile providers. Only
  Rudy+TW is approved for route-bbox rendered-map cache/OCR in this phase.
- Treating the NLSC no-application catalog as proof that every listed item is
  a WMTS layer. The PDF lists WMTS/WMS/API service candidates; implementation
  must verify concrete service type and URL template before enabling controls.
- Hiding `UAV*` under a generic topo/aerial bucket. UAS orthophoto is a
  high-value route revalidation provider and must remain discoverable as its
  own provider family with coverage/year metadata.
- Adding the official mountain communication-point dataset as a 33rd layer.
  It must be normalized into the existing `pois` and optional checkpoint/timeline
  evidence groups while preserving source provenance and stale-risk metadata.
- Treating four terrain overlay PNGs as the total terrain source count. The
  four files are display modes; the terrain source coverage must be checked
  separately through DTM coverage and terrain visualization counts.
- Treating `soil-moisture` or `antecedent-rain` placeholder features as live
  GEE/SMAP/GPM measurements. When GEE credentials or the fetcher are absent,
  the layer may correctly render a `missing_credentials` status feature only.
- Treating `cwa-weather` with zero warning features as failed. It can be a
  valid fetched result when CWA warnings do not intersect the route/bbox.
- Clearing `/data/scout/raster-tiles` or OCR cache to force a rerun. Cache
  refresh must be stale/missing driven; OCR invalidation is keyed by tile
  image hash, OCR engine, language, and version.

| Scout layer | Required behavior | Files/components responsible | Ordering/dependency constraints | States and edge cases | Verification |
|-------------|-------------------|------------------------------|---------------------------------|-----------------------|--------------|
| `imagery` | Runtime WMTS imagery basemap, bottom-most visual layer. | `admin_map_layers.py`, `admin_imagery_sources.py`, three `docs/admin/*.html` pages. | z-index 0; below OSM and all evidence. | Uses runtime WMTS/XYZ delivery by default; failed tiles must not blank vector evidence. Do not create preparation raster cache except legacy explicit local raster handoff. | Contract verifier plus browser layer toggle/group check. |
| `rudy` | Optional Rudy hiking basemap overlay, runtime display only by default. | `admin_map_layers.py`, `admin_imagery_sources.py`, three admin pages. | Raster overlay rank 4; below OSM/evidence. | Off by default; network/cache failure isolated from evidence layers. Not an approved OCR/cache source unless later promoted. | Source id, control, rank, group, browser toggle. |
| `rudy-twmap` | Optional Rudy+TW basemap and current approved preparation cache/OCR source for hiking rendered-map evidence. | `admin_map_layers.py`, `admin_imagery_sources.py`, `pretrip_raster_label_ocr.py`. | Raster overlay rank 4; OCR output must pass through raster label adapter. | Can be visually off while still used as preparation/OCR source. It is the only current route-bbox map cache source for mileage K, stable POI, rendered labels, and icons. | Source id, OCR plan/source checks, control/rank/group/toggle. |
| `relief` | Optional runtime color relief raster reference. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; not Scout terrain visualization. | Off by default; no workspace artifact or preparation cache required. | Control/rank/source/group/toggle. |
| `geology` | Optional runtime geology context overlay. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; candidate context only. | Off by default; no safety truth or preparation cache. | Control/rank/source/group/toggle. |
| `topo-5k` | Optional runtime 1/5000 topographic reference. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; below Scout evidence. | Off by default; runtime WMTS only, no preparation cache. | Control/rank/source/group/toggle. |
| `forest` | Optional runtime forest compartment overlay. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; below Scout evidence. | Off by default; candidate context only, no preparation cache. | Control/rank/source/group/toggle. |
| `osm` | OSM/local XYZ basemap. | `admin_map_layers.py`, `admin_basemap_tiles.py`, `pretrip_layer_preparation.py`, admin pages. | z-index 8; above raster, below terrain/evidence. | Parent/cached fallback at high zoom; viewport must not become blank. | Preparation ready check, control/rank/group/toggle, browser zoom smoke. |
| `terrain` | DEM/DTM hillshade, elevation tint, slope shading, contours. | `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 20; above basemap, below route/risk/CP. | Missing DEM yields unavailable/partial evidence, not runtime truth. | Preparation ready check, artifact count/hash, group/rank/toggle. |
| `corridors` | Route corridor/map context evidence. | `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 40; below route and review targets. | May be unavailable without context source; must not block route display. | Source ref, rank, group, toggle. |
| `overpass` | Overpass vector evidence and route-center basis. | `pretrip_layer_preparation.py`, `pretrip_overpass_route_alignment.py`, `admin_map_layers.py`, admin pages. | z-index 42; route/CP/segment alignment should prefer this where confidence allows. | If absent, GPX remains candidate fallback with provenance. | Preparation refs, projection alignment, group/rank/toggle. |
| `route` | Reviewed/pretrip route line. | `pretrip_import.py`, `pretrip_layer_preparation.py`, `pretrip_overpass_route_alignment.py`, admin pages. | z-index 44; should use Overpass-aligned geometry when available. | Coarse GPX fallback must carry provenance and confidence. | Route count/source/alignment metadata, group/rank/toggle. |
| `completed-track` | Active completed-trip GPX track for post-analysis/admin only. | `post_analysis_completed_trip_recordings.py`, `admin_map_layers.py`, `docs/admin/phase1-after-action.html`. | z-index 45; after-action surface only. | Absent before trip selection; not pretrip route truth. | After-action control/group/rank and source availability checks. |
| `reference-tracks` | Reference GPX tracks preserving `trk`/`trkseg` boundaries. | `pretrip_import.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 46; below retreat/segments/risk. | Hidden to reduce clutter; never overrides reviewed route. | `coordinate_segments` source, rank/group/toggle. |
| `retreat` | Retreat/turnaround route candidates. | `pretrip_import.py`, `admin_map_layers.py`, admin pages. | z-index 48; above reference tracks, below segments. | May be unavailable; no autonomous runtime action. | Control/source availability/rank/group/toggle. |
| `segments` | Route segments from filtered/aligned route. | `pretrip_import.py`, `pretrip_overpass_route_alignment.py`, `pretrip_layer_preparation.py`, admin pages. | z-index 50; above route, below risk/CP. | Resume/coarse GPS gaps must be flagged; stroke width stays screen-sized at high zoom. | Segment count/source/alignment metadata, group/rank/toggle. |
| `risk-ribbon` | Baseline route risk ribbon. | `pretrip_risk_heatmap.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 54; below calibrated/delta/points. | Candidate evidence only; do not replace with calibrated heatmap. | Risk artifact count/source, group/rank/toggle. |
| `risk-heatmap` | Route-specific calibrated risk heatmap. | `pretrip_risk_heatmap.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 55; distinct from baseline. | Missing calibrated output must surface as unavailable. | Calibrated artifact count/source, group/rank/toggle. |
| `risk-delta` | Difference between baseline and calibrated risk. | `pretrip_risk_heatmap.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 56; depends on baseline and calibrated risk. | Off by default; unavailable if either input absent. | Delta source or paired-source ref, group/rank/toggle. |
| `soil-moisture` | GEE/SMAP soil moisture context. | `scout_gee_integration.py`, `admin_map_layers.py`, admin pages. | z-index 57; environmental candidate evidence. | Unavailable when GEE/data absent; no safety truth mutation. | Source availability, group/rank/toggle. |
| `antecedent-rain` | GEE/GPM antecedent rain context. | `scout_gee_integration.py`, `admin_map_layers.py`, admin pages. | z-index 58; environmental candidate evidence. | Unavailable when data absent; no safety truth mutation. | Source availability, group/rank/toggle. |
| `cwa-qpf` | Central Weather Administration quantitative precipitation forecast grid/context. | `admin_weather_overlay.py`, `scout_weather_integration.py`, `admin_map_layers.py`, admin pages. | z-index 59; weather candidate evidence below risk points. | Unavailable without fetched CWA/open weather evidence; no runtime safety truth mutation. | Source/status availability, group/rank/toggle. |
| `risk-score` | Point risk-score evidence. | `pretrip_risk_heatmap.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 60; above risk raster/ribbon layers. | Off by default; candidate evidence only. | Risk point artifact/source/count, group/rank/toggle. |
| `checkpoints` | CP candidates/reviewed checkpoints. | `pretrip_import.py`, `pretrip_overpass_route_alignment.py`, `pretrip_layer_preparation.py`, admin pages. | z-index 62; above risk layers. | Marker radius stays screen-sized; focus uses expected viewport policy. | CP count/source/alignment, group/rank/toggle/focus smoke. |
| `pois` | Named POI/context candidates, including official communication-point markers from the Forestry and Nature Conservation Agency mountain communication dataset. | `pretrip_route_context_collection.py`, `admin_map_layers.py`, admin pages. | z-index 64; above checkpoints, below hazards. | Avoid raw variable-name labels; unavailable if no POI source. Communication points are candidate evidence only and must preserve stale-risk/provenance metadata. | Label/source/group/rank/toggle. |
| `hazards` | Hazard candidates from terrain/context/OCR/notes/external evidence. | `pretrip_route_context_collection.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 65; above POI, below route notes/MCP/Boss. | Must keep provenance/review status; candidate only. | Source/group/rank/toggle. |
| `route-notes` | Historical/public route notes. | `pretrip_import.py`, `pretrip_route_context_collection.py`, `admin_map_layers.py`, admin pages. | z-index 66; above hazards, below MCP/Boss. | Can seed context collection; low-signal notes should not flood MCP/Boss. | Source/count/group/rank/toggle. |
| `cwa-weather` | Central Weather Administration warning, observation, and forecast evidence. | `admin_weather_overlay.py`, `scout_weather_integration.py`, `admin_map_layers.py`, admin pages. | z-index 67; weather candidate evidence above route notes and below MCP/Boss. | Unavailable without CWA/open weather source refs; no runtime safety truth mutation. | Weather source/status contract, group/rank/toggle. |
| `mcp` | Major Critical Point candidates. | `pretrip_route_context_collection.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 68; above route notes, below Boss. | Zero count must have explicit unavailable reason; preserve refs during preparation. | MCP count/source/alignment, group/rank/toggle. |
| `boss-points` | Route Boss Demand vs User Pace/Energy Reserve Challenge Fit points. | `pretrip_boss_point_synthesis.py`, `pretrip_layer_preparation.py`, `admin_map_layers.py`, admin pages. | z-index 70; above MCP. | Must not classify rest areas as Boss solely because people stop there. | Boss count/source/route-distance, group/rank/toggle/highlight smoke. |
| `events` | Planned/replayed Ln/action/event evidence. | `admin_evidence_timeline.py`, `admin_map_layers.py`, admin pages. | z-index 72; above Boss, below weather API status. | Pretrip may have no events; debug/after-action replay may show them. | Event source availability, group/rank/toggle. |
| `weather-api` | Weather API status/context overlay. | `admin_weather_overlay.py`, `admin_map_layers.py`, admin pages. | z-index 80; top contextual overlay. | Unavailable without provider/credentials; tests must not require hidden network calls. | Weather source/status contract, group/rank/toggle. |

Required local gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py --repo-root .
```

Required workspace gate after import/preparation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
  --repo-root . \
  --project-root /path/to/workspace \
  --require-workspace
```

Browser gate when Playwright is available:

```bash
node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
```
