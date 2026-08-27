# Pretrip Layer Preparation

Last updated: 2026-08-26

## Objective

`LayerPreparationJob`（圖層準備工作） prepares map and evidence layers for a
Phase 4 pretrip workspace before `/admin/pretrip` renders them. It turns local
route, terrain, raster, tile, weather, and review evidence into deterministic
workspace artifacts, while keeping Phase 1 runtime state and Phase 2 Brain
writeback out of scope.

The job is a planning-side compiler for layer readiness, not a live map
provider, crawler, route editor, safety adapter, or final `MissionGraph`
compiler.

For preparation behavior, this dated spec and
`docs/specs/pretrip-historical-gpx-importer.md` are normative. Older run logs,
temporary workarounds, or remembered trajectories that used a no-PBF retry,
post-run GeoJSON/raster repair, page-triggered Navigation backfill, or a second
workspace remain incident evidence only and must not be copied back into the
current procedure.

For the fixed end-to-end operator sequence that combines GPX import, connected
map preparation, Rudy/Rudy+TW OCR, raster label normalization, route context,
Boss synthesis, 32-layer verification, browser smoke checks, and Scout deploy
handoff, see `docs/specs/scout-pretrip-preparation-pipeline.md`.

This spec owns only the preparation-backed layer run. The admin map UI contract
is larger; see `docs/specs/scout-admin-map-layer-contract.md`. Its canonical
route-bundle producer is `docs/specs/pretrip-historical-gpx-importer.md`.

## Import Handoff And Single-Pass Preparation Contract

For a Dashboard Workspace Clone, this job is the second stage of the same user
operation, not an optional repair performed after opening the target. The
canonical handoff is:

```text
validated Historical GPX Importer route bundle
  -> route identity/corridor locked for this target
  -> all requested preparation-backed layers
  -> route-scoped raster/WMTS cache policy
  -> local OSM PBF route extract and MapLibre GeoJSON
  -> terrain/Navigation/risk/post-layer enrichments
  -> validation, clone receipt, and browser-visible workspace
```

The clone request should invoke `LayerPreparationRequest` with the target
project root and, when available, the material root, DTM dirs/full-route
GeoTIFF refs, local OSM PBF path/source URL/cache TTL, route and reference
corridors, raster-cache root, connected-network policy, and these orchestration
switches:

```text
run_post_layer_enrichments = true
run_map_preparation_spec_artifacts = true
seed_imagery_cache = true when explicit connected fetch is authorized
prepare_cwa_imagery = true when requested by the operator/profile
```

The target should open with route-derived data already materialized. This
includes, where source evidence supports it, CP/segments, MCP, Overpass/PBF
context, terrain visualization, full-route DTM coverage, ridge/valley and other
Navigation terrain derivatives, route pressure, risk score/ribbon/heatmap/delta,
Boss Points, mileage/K alignment, reference timing, route context, OCR labels,
and raster manifests/cache status. A route may legitimately produce fewer
features than Chilai Nanhua, but a missing mechanism or skipped preparation
stage must be reported as blocked/degraded rather than silently appearing as an
empty ready layer.

Importer-complete plus later manual repair is not the normal completion model.
A preparation failure leaves the clone incomplete. Fix the dependency or
workflow and replay the original one-import-plus-one-preparation user flow; do
not require an operator to create a second `_v2` workspace or discover and run
hidden page-specific backfills.

### Fixed Workstation Runtime And Parser Binding

The Dashboard and preparation worker must use the project-owned Python runtime,
not whichever system Python happens to launch port 9099. The supported setup is:

```bash
tools/setup_dashboard_workspace_runtime.sh
scout-dashboard --host 127.0.0.1 --port 9099 \
  --workspace-root /Users/alexwang0315/workspace
```

Setup is explicit and idempotent. It installs the `pretrip-workstation` extra
into `./venv`, records the `pyproject.toml` hash, and creates persistent
`~/.local/bin/scout-dashboard`, `~/.local/bin/osmium`, and
`./venv/bin/osmium` bindings. When the marker and imports are unchanged, setup
must skip package installation. The launch command never installs packages; it
puts `./venv/bin` first on process PATH and fails clearly when the runtime or
CLI binding is incomplete.

Local PBF preparation requires both capabilities to be discoverable by the
running preparation process:

- Python `osmium` importable from the active Dashboard interpreter;
- the `osmium` CLI executable reachable through that process PATH.

An installation in a legacy repository venv or isolated micromamba environment
does not count unless it is deliberately bound into this runtime. The CLI alone
is insufficient because the current filtered extract still enters Python
`osmium` normalization. The Python package alone may provide a correctness
fallback, but normal workstation preparation should retain the CLI fast path.

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
Those are UI/post-process contract layer ids, not `--layers` adapter ids. Their
provider manifests and route-scoped raster caches may still be prepared as
sidecars by map preparation. They are verified by
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
| Rudy+TW (`rudy-twmap`) | Yes, for the route bbox and OCR when requested. | Yes, with cache-first display and explicit refresh. | Authoritative hiking rendered-map evidence（登山圖面證據） for mileage K, stable POI, trail labels, rendered icons, and route-context OCR. |
| Rudy without TW overlay (`rudy`) | Optional route-bbox cache. | Yes. | Optional hiking basemap/reference. It must not be mixed with the Rudy+TW OCR evidence source unless explicitly selected as that evidence source. |
| NLSC WMTS layers | Optional bounded workspace cache for selected/required layers. | Yes, with cache-first display and explicit refresh. | Basemap/context such as `EMAP5`, `PHOTO_MIX`, `B5000`, `TOPO25K`, `MOI_HILLSHADE`, `GeoSensitive2`. |
| Historical map themes (`historical-map`) | Yes for the selected preparation theme; other themes are fetched on demand. | Yes, through a theme selector and workspace-cache refresh action. | Candidate-only historical comparison. Theme identity, provider, year, bbox, zooms, hashes, and attribution stay explicit. |
| OSM raster plus local PBF vector | Optional bounded raster cache; required local PBF route extract when configured. | Yes. | Raster provides visual context; PBF/Overpass provides structured features. Neither uses tile OCR as structured evidence. |
| TWMap/other public WMTS/XYZ | Optional bounded workspace cache when selected and provider policy permits. | Yes, with explicit refresh. | Candidate-only visual reference; never route-safety truth. |
| DEM/DTM, risk, CWA, GEE | Not map-tile cache. | Yes as Scout evidence overlays. | Workspace evidence artifacts and derived visualizations, not basemap tile providers. |

Workspace cache is bounded, provider-aware, and route-scoped; it is not public
bulk downloading. Preparation should cache the tiles needed to open the
workspace at the configured initial route bbox/zoom for every selected or
profile-required raster source whose provider policy permits caching. Cache
records must include project id, control layer id, source id/theme id, z/x/y,
route bbox, zoom range, fetch timestamp, TTL, response/content type, SHA-256,
attribution, and failure state. Runtime display reads the workspace cache first.

The dated Dashboard Clone baseline currently has eight cache-manifest entries:
`imagery`, `rudy`, `rudy-twmap`, `relief`, `geology`, `topo-5k`, `forest`, and
one selected historical-theme cache id such as `historical-fandi-1916`. A
different selected historical theme replaces that final id; it does not reuse
its directory. Any additional raster control enabled by default or requested
for opening must join the profile cache set when provider policy permits.
Sources that prohibit caching must be off by default or visibly marked as
requiring a connected runtime fetch, never shown as cache-ready.

Every cache-backed raster control must also retain an explicit post-load
refresh action, such as `Update checked raster layers from WMTS`; the historical
map selector additionally refreshes only its selected theme. Refresh writes to
the current workspace and must not overwrite another project. Offline or failed
providers keep the last complete generation and report `cache_missing`,
`stale_refresh_recommended`, or `refresh_failed`; they must not return a
transparent tile as `available` without disclosing that fallback.

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
map-context API registry. NLSC remains a runtime WMTS/WMS/API provider family,
while selected layers may also use the bounded route-bbox workspace cache
defined above. Cacheability does not promote a layer into an OCR or semantic
evidence role. Before enabling a layer, the
implementation must verify the advertised service type through NLSC
`GetCapabilities` or `MapLayerInfo`（圖層圖資說明） because PDF text extraction
does not preserve the WMTS/WMS/API checkmark columns reliably.

NLSC no-application candidates relevant to Scout:

| Category | Codes from the PDF | Scout usage |
|----------|--------------------|-------------|
| Electronic maps（電子地圖） | `EMAP`/`EMAP5`, `EMAP6`, `EMAP15`, `EMAP16`, `EMAP01`, `EMAP2`, `EMAP12`, `EMAP9`, `EMAP8`, `EMAP7`, `EMAP5_OPENDATA`, `EMAP6_OPENDATA`, `EMAP3826`, `EMAP3525` | Runtime basemap alternatives for general readability, contour/no-contour comparison, English UI, transparent overlays, and non-hiking/city-tour scenarios. |
| Orthophoto imagery（正射影像） | `PHOTO2`, `PHOTO_MIX`, `PHOTO3826` | Runtime imagery basemap and route-context visual inspection. A provider-approved bounded route cache is allowed; regional bulk mirroring is not. |
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

### Official Mountain Communication Point Dataset

The data.gov.tw dataset
`106640`（林業及自然保育署山區手機可通訊點標示） is an official
mountain communication-point evidence source and must be kept separate from
Rudy+TW OCR output. It is not a basemap or raster tile layer. It is route
context data that should normalize into `official_communication_point_candidate`
（官方手機可通訊點候選） records, then surface through the existing `pois`,
`checkpoints`, and timeline evidence groups.

Current source characteristics:

| Source | Scout handling |
|--------|----------------|
| Provider | Agriculture open-data platform / Forestry and Nature Conservation Agency（農業部資料開放平臺 / 林業及自然保育署）. |
| Dataset id | data.gov.tw `106640`, MOA open-data id `G07`. |
| Formats | KML/ZIP style open-data package and SHP-style resource where available. The importer should prefer structured resource metadata, then parse KML `Placemark` records when that is the available payload. |
| Update cadence | Annual（每年）. Treat older downloads as stale review evidence, not live signal truth. |
| Core fields | `序號`, `名稱`/步道名, `分署`, `標示地`, `縣市`, `TWD97_X`, `TWD97_Y`, WGS84 `東經`/`北緯`, carrier fields `中華電`, `遠傳電`, `台灣大`, `亞太電`, and `備註`. |
| Current known scale | The 2026 public notice describes 1,416 marked signs as of ROC 115 February. Do not hardcode this count; record it as source metadata. |

Normalization requirements:

- preserve dataset URL, source agency, resource id, request timestamp, raw
  payload hash, parser version, record id, original KML/HTML field values, and
  WGS84 geometry;
- preserve `TWD97_X/Y` when present for audit and cross-checking, but use WGS84
  `lon/lat` for Scout map display;
- derive `carrier_count`, `carrier_names`, and `emergency_call_candidate`
  metadata from the carrier fields, without claiming guaranteed reception;
- join candidates to the route corridor and nearby checkpoints by distance,
  not by name alone;
- emit a candidate CP only when the communication point falls inside the route
  corridor or configured along-track search buffer; otherwise retain it as
  route-context POI evidence;
- keep the caution text with the artifact: mountain communication quality is
  affected by terrain, weather, power supply, device capability, and carrier
  network state（山區地形、氣候、電力、手機與電信狀態皆會影響通訊品質）.

This source is stronger than unstructured reference-GPX notes for stable
communication POI facts, because the locations are official marked signs. It is
still candidate-only evidence: it may support pretrip review, retreat planning,
and "where to try communication" prompts, but it must not become runtime safety
truth or a guarantee that rescue calls will work.

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
Overpass, local OSM PBF, and OSM raster basemaps come from related OSM data,
but they serve different purposes: Overpass is connected structured
route-corridor evidence for CP/POI synthesis, local OSM PBF is offline
structured route-corridor evidence（離線 OSM 結構化圖徵證據）, while
OSM/NLSC/TWMap tiles are visual basemap support. This alpha treats Overpass or
local OSM PBF as the structured OSM evidence source and treats Rudy+TW as the
only approved rendered-map cache/OCR material for hiking POI, mileage, and
named-label extraction. OSM, NLSC, historical-map, and other WMTS/XYZ
basemaps may use provider-approved bounded workspace caches for immediate
display, but they remain visual context and do not inherit Rudy+TW's OCR or
semantic-evidence role.

### Local OSM PBF Evidence Source

When a configured full-region `.osm.pbf` file is available, it is a required
preparation input, not a hint that may silently fall back to Overpass. Preflight
must verify the path/hash and active-interpreter Python `osmium` before import
creates a clone target. Scout must not parse the whole file in-process when the
CLI fast path is available. The preparation flow must:

1. derive the route corridor bbox from the golden/reference planning route;
2. use `osmium extract` to cut the PBF to the route bbox plus configured
   corridor;
3. use `osmium tags-filter` to retain the same hiking/path/POI/hazard tag
   families as the Overpass Phase A query;
4. convert the small extract to OSM JSON and hydrate way/relation geometry from
   node refs;
5. normalize the result through the same planning-candidate contract as
   Overpass evidence;
6. write the route-bbox render GeoJSON and feature index used by the map;
7. expose that GeoJSON through the project OSM PBF endpoint and append its
   features to the active MapLibre collection under `layer_id = osm`.

Required workspace refs include:

```text
normalized/map/osm_pbf_route_bbox.osm.pbf
normalized/map/osm_pbf_phase_a_raw.osm.json
normalized/map/osm_pbf_render_extract_manifest.json
normalized/map/osm_pbf_route_bbox_full.geojson
outputs/layers/normalized/osm_pbf_feature_index.json
```

`project.json` must expose the corresponding source, SHA-256, raw payload,
route extract, render manifest, render GeoJSON, feature-index refs/counts, and
PBF cache/freshness fields. The admin endpoint is:

```text
GET /admin/pretrip/projects/{project_id}/osm-pbf-vector.geojson
```

The response remains `candidate_only=true` and
`runtime_safety_truth=false`.

The current Taiwan source file used in alpha testing is downloaded from
`http://download.geofabrik.de/asia/taiwan-latest.osm.pbf` and stored locally as
`~/Downloads/taiwan-260624.osm.pbf`. The path name is an operator snapshot name;
the artifact provenance must preserve both the original download URL and the
local file path/hash so future runs can distinguish "latest at download time"
from "latest now"（下載當下最新版，不等於目前最新版）.

`taiwan-latest.osm.pbf` is not a live dependency that must be refreshed on every
preparation run. Scout treats the downloaded file as a local PBF cache
（本地 PBF 快取） with a default `cache_ttl_days = 30`. Within 30 days of the
download snapshot timestamp, preparation must reuse the local file and avoid a
new download. After the TTL expires, preparation may still use the existing
local file as candidate evidence, but it must mark `pbf_cache.cache_status =
stale_refresh_recommended` and `refresh_required = true` so the next connected
operator run can refresh the file deliberately. The cache policy is
`download_once_reuse_until_ttl_expires`（下載一次，TTL 內重用）; do not delete the
file or clear unrelated raster/OCR caches just to force OSM PBF refresh.

This keeps the public Scout layer contract stable: the UI still reads the
existing `osm`/`overpass`/`pois`/`corridors` groups, while provenance marks the
source as `local_osm_pbf` instead of live Overpass. The generated artifact may
reuse `overpass_evidence_ref` and `overpass_map_context_ref` for compatibility,
but it must expose `artifact_kind = pretrip_osm_pbf_evidence`,
`source = local_osm_pbf`, `osm_pbf_source_ref`, `osm_pbf_source_url`,
`osm_pbf_source_sha256`, `osm_pbf_raw_payload_ref`, and
`osm_pbf_extracted_at`. It must also expose `osm_pbf_cache_ttl_days`,
`osm_pbf_cache_status`, `osm_pbf_cache_expires_at`,
`osm_pbf_refresh_required`, and a matching `pbf_cache` object in the source and
normalized evidence artifacts.

Because the Taiwan PBF is too large to read during admin rendering, preparation
must also preserve a workspace-local route-bbox extract（工作區內路線 bbox 小切片）
for OSM layer rendering. Preferred output is
`normalized/map/osm_pbf_route_bbox.osm.pbf` when the `osmium` CLI can create the
small PBF extract. If the environment only has the Python `osmium` streaming
fallback, the preferred render source may be the small filtered OSM JSON payload
instead. In both cases, `project.json` and the `osm` layer record must expose
`osm_pbf_render_extract_ref`, `osm_pbf_render_extract_manifest_ref`,
`osm_pbf_render_extract_source_kind`, and
`osm_pbf_render_extract_feature_count`. The manifest
`normalized/map/osm_pbf_render_extract_manifest.json` identifies the preferred
render source, the raw OSM JSON fallback, the cache status, and the route-bbox
scope. This artifact is for local map rendering and review context only; it is
still candidate-only evidence and is not runtime safety truth.

Local PBF parsing is still candidate-only evidence. It may improve offline
coverage and avoid live network fetches, but it is not runtime safety truth and
does not replace Rudy+TW rendered-map OCR for stable map labels.

OSM preparation acceptance requires more than artifact existence. For a route
whose extract contains renderable features, the live Dashboard must prove:

- the GeoJSON endpoint returns HTTP 200 with the workspace source ref;
- MapLibre receives a non-zero `osm` feature count and does not leave those
  features only in the hidden SVG fallback DOM;
- toggling OSM changes the actual map canvas and shows route-area roads/paths,
  waterways, areas, or points after other basemaps are disabled;
- no console error or candidate-authority conflict occurs;
- an unavailable OSM raster tile does not hide the prepared local PBF vector.

API success, hidden SVG primitive counts, checkbox state, and a non-empty file
are individually insufficient browser evidence.

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

This handoff path does **not** authorize unbounded mirroring of every runtime
WMTS/XYZ source. It does authorize the provider-aware, route-bbox/initial-zoom
workspace cache defined by this spec for each selected or profile-required
source whose provider terms permit caching. Rudy+TW additionally owns the OCR
evidence role; NLSC, OSM, TWMap, historical maps, and other WMTS/XYZ sources
remain visual context even when their opening tiles are cached. Existing
`/data/scout/raster-tiles` content must not be cleared to force a rerun; it is
preserved unless a documented stale/missing/invalidation condition applies.

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

When imagery has moved to WMTS runtime delivery, `imagery` may report
`wmts_runtime_only` only when provider policy prohibits caching or the selected
preparation profile explicitly did not request an opening cache. A selected or
profile-required, cache-permitted source with no usable opening tiles reports
`workspace_cache_missing` or an equivalent degraded status and exposes the
post-load refresh action; it must not be marked ready merely because a tile URL
exists. This distinction does not authorize deleting
`/data/scout/raster-tiles`; the cache may still be needed for offline replay,
OCR, or older handoff packages.

### Historical Map Theme Preparation

`historical-map` is one auxiliary presentation control backed by an allowlisted
theme catalog, not one canonical safety layer per year. Preparation must choose
an explicit theme and seed enough valid tiles for the route bbox and configured
initial zooms into the target workspace before the clone is complete. When the
operator does not choose a theme, the profile may select a documented
coverage-tested default. For the Dongqing Batongguan corridor, the current
tested default is `sinica_jm50k_1916` in the
`historical-fandi-1916` cache namespace; a nominally older theme such as the
1904 fortress map must not be selected merely by date when it returns blank
coverage for the route.

Every historical theme must have a distinct cache layer/source namespace.
Changing `source_id`, year, or provider while reusing another theme's cache
directory is forbidden because cache-only load could show the wrong map. The
theme manifest must record theme id, display name, provider, map year, source
URL/template kind, route bbox, zoom range, fetched and valid tile counts,
transparent/blank tile count, timestamps, TTL, per-tile hashes, attribution,
candidate boundary, and cache status.

The page loads the selected historical theme cache-first and remains network
quiet until the operator uses the selected-theme refresh action. That action
may fetch only the allowlisted selected theme, writes only to the current
workspace, and leaves the last complete cache generation intact when refresh
fails. The UI must distinguish `ready_from_workspace_cache`,
`workspace_cache_missing`, `stale_refresh_recommended`, `refresh_failed`, and
`provider_no_coverage`; a transparent response or HTTP success with no visible
map pixels is not a ready tile.

Historical-map browser acceptance requires the selected theme to alter the
actual map canvas over the route at a supported zoom with other basemaps off.
A populated selector, checked control, successful proxy response, or non-empty
cache directory is individually insufficient. Because the source registry is
loaded at Dashboard startup, source additions or changes must be qualified
against the restarted user-facing `127.0.0.1:9099` process rather than only an
alternate test port. All historical themes remain `candidate_only=true`,
`runtime_safety_truth=false`, `operational=false`, and
`visualization_only=true`.

## Workspace Outputs（工作區輸出）

The `workspace`（工作區） outputs live under the selected project root:

```text
<project-root>/
  cache/raster-tiles/
    <project_id>/<cache_layer_id>/<z>/<x>/<y>.*
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
  outputs/navigation/
    navigation_terrain_intelligence.json
  normalized/map/
    osm_pbf_route_bbox.osm.pbf
    osm_pbf_route_bbox_full.geojson
    osm_pbf_render_extract_manifest.json
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
- `cache/raster-tiles/`: provider-aware, route-scoped opening caches and
  per-source/theme manifests. These are visual cache generations, not copied
  route truth.
- `outputs/navigation/navigation_terrain_intelligence.json`: persisted
  Navigation projection compiled during preparation from this workspace's
  route, terrain, source ledger, MCP, and candidate evidence. The first page
  load should read it rather than schedule the missing preparation stage.

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

Source selection is route-identity bound. A full-route GeoTIFF declared by the
material manifest is preferred over a partial tile set or route-sample proxy.
Preflight must verify its resolved path, SHA-256, readability, CRS, horizontal
resolution, no-data policy, bbox, and coverage of the golden route plus the
configured corridor. A GeoTIFF prepared for another route, a file with a hash
mismatch, or a partial raster presented as full-route coverage is a blocker.
When a declared full-route source cannot be used, preparation must report the
exact dependency/coverage failure. Route-aligned samples may remain available as
separate candidate context, but they must not be rendered as terrain analysis or
make Navigation ready.

Required outputs may include:

- `terrain_hillshade`（陰影起伏圖）: shaded-relief raster or tile manifest.
- `terrain_elevation_tint`（高度分層色）: elevation color ramp raster/tile
  manifest.
- `terrain_slope_shading`（坡度著色）: slope-degree or percent-grade raster/tile
  manifest.
- `terrain_contours`（等高線）: contour GeoJSON or contour tile manifest.
- `terrain_route_samples`（沿線地形採樣）: compact route-aligned samples for
  elevation, slope, roughness, TEII_20m, and no-data coverage.
- `terrain_visualization`（地形視覺化摘要）: compact GeoJSON and raster-overlay
  manifest produced by the allowlisted QGIS Processing + GRASS/GDAL workflow.
- standard raster overlay refs:
  `terrain_hillshade_overlay_ref`, `terrain_elevation_tint_overlay_ref`,
  `terrain_slope_shading_overlay_ref`, and `terrain_contours_overlay_ref`.

If the DEM exists but the standard processor is unavailable, layer preparation
may still preserve route-aligned samples as separate candidate context, but
`terrain_visualization` must be `awaiting_qgis_grass_processor` with no raster
overlays. If the full DEM source is absent, its status must instead be
`source_unavailable`. Risk ribbon, route samples, or a locally painted Python
bitmap must not make terrain visualization ready.

Terrain preparation must then compile and persist
`outputs/navigation/navigation_terrain_intelligence.json` before declaring the
workspace ready. The projection input fingerprint includes this workspace's
golden-route identity, terrain refs, route samples, DTM coverage, source
ledger/hypothesis, MCP evidence, route-note candidates, reference display
geometry, and OSM/Overpass context. It must expose ridge/valley and related
terrain-candidate counts, source coverage, blockers/warnings, input refs, and
the candidate-only boundary. It must never reuse Chilai Nanhua ridge, valley,
checkpoint, segment, route-pressure, or timing outputs for a Dongqing route.

Zero ridge or valley candidates can be a legitimate route result only when the
algorithm ran against sufficient route-bound terrain coverage and records that
outcome explicitly. Missing projection, skipped compiler, unsupported terrain
coverage, or a lazy first-page compilation requirement is not equivalent to a
valid zero. Any change to golden-route identity, order, direction, source hash,
or terrain source invalidates the fingerprint and requires regeneration of the
Navigation projection and dependent terrain/risk outputs in the same
preparation run.

Preferred production pipeline:

```text
full-route DEM/DTM GeoTIFF + Golden Route
  -> QGIS Processing allowlist
  -> GDAL crop to full-route rectangle
  -> GRASS r.slope.aspect
  -> GRASS r.relief
  -> GRASS r.contour
  -> GRASS geomorphon / watershed candidate workflows when requested
  -> GDAL rasterize / color-relief and bounded vector export
  -> MapLibre raster overlays / candidate GeoJSON
  -> /admin/pretrip display
```

The manifest must identify the actual standard processor and algorithms, source
resolution, rectangle extent, parameters, and whether raw DEM/DTM payloads were
embedded. `standard_processor_completed=true`, `fallback_used=false`, and
`python_dtm_processing_used=false` are required before a standard terrain
visualization becomes the active project ref. No Python DTM analysis fallback is
authorized by this contract.

Mapbox Terrain RGB generation is a separate deterministic display-packaging
step. It may resample supported DEM values for encoding, but must record
`visualization_packaging_only=true`, its packaging processor, the upstream
analysis processor, `adds_source_resolution=false`, and its complete-tile
coverage. It does not rerun slope, contour, ridge, valley, or hydrology analysis.

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
- whether each layer is ready, missing, partially covered, or awaiting the
  standard processor;
- when route-aligned samples are available without the standard raster workflow,
  keep them separate and mark `full_raster_hillshade_generated=false`;
- when standard raster overlays are emitted, preserve the DEM/DTM source
  resolution and record `coverage_scope=full_route_extent_rectangle`,
  `adds_source_resolution=false`, and the actual rectangle bounds.

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

## Dynamic Weather And Geology Refresh Boundary

The initial full preparation must leave the workspace immediately usable while
preserving explicit connected refresh for time-varying evidence. Clone/import
must not freeze source-workspace weather, GEE, Overpass, or geology responses as
the target's current state.

- CWA weather, warning, observation, and QPF artifacts are current-run
  snapshots. Every explicit connected full preparation attempts CWA again and
  records request/fetch/validity hours or the current blocker.
- GEE/SMAP/GPM numeric evidence declares `cacheable=false`, `ttl_seconds=0`,
  and `must_refetch_on_prepare=true`. Missing credentials remain a typed
  `missing_credentials` status; HTTP/provider rejection remains
  `fetch_failed`, never a fabricated numeric layer.
- The geology visual/provider manifest and an allowed opening tile cache may be
  prepared for immediate display, but geology remains a refreshable runtime
  provider. Its imported cache is not a permanent geological truth snapshot.
- An explicit post-load connected refresh may update CWA, GEE, Overpass, and
  geology provider receipts/caches without rerunning GPX import or replacing
  the primary route-derived layer manifest. It writes only to the selected
  workspace and publishes a new validated dynamic generation atomically.
- A failed refresh keeps the last complete displayable generation with stale
  provenance and the new failure receipt. It must not erase the map or silently
  relabel old evidence as fresh.

Provider credentials and project identifiers remain server-side environment or
approved secret-store inputs. They must not be copied into the workspace,
receipt, browser payload, or documentation. Startup/status reads remain
cache-only and do not schedule hidden writers; network activity starts only
from full connected preparation or an explicit refresh action.

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

When rerunning importer + map preparation on a workstation or Scout hardware,
the operator must verify these items before declaring the workspace refreshed:

1. Start through the fixed project runtime. Confirm the active Dashboard Python
   can import `osmium`, its process PATH resolves the persistent `osmium` CLI
   binding, and setup reports the current dependency marker. If a configured
   PBF cannot pass this preflight, stop before creating the target workspace.
2. Use the Dashboard Workspace Clone operation with a new target id. Confirm the
   source workspace is unchanged, the target did not previously exist, and
   `outputs/workspace_clone_receipt.json` records one completed GPX-import stage
   followed by one completed preparation stage. A partial receipt, manual
   page-level backfill, or `_v2` target is not successful completion.
3. When local PBF is configured, verify its path/hash plus all required extract,
   render GeoJSON, manifest, and feature-index refs. Verify the project GeoJSON
   endpoint and a non-zero MapLibre `osm` feature count, then visually confirm
   the OSM toggle changes the canvas with raster basemaps off.
4. Verify the workspace raster-cache manifest covers every selected or
   profile-required, cache-permitted source at the opening bbox/zooms. Confirm
   the selected historical theme has a source-specific cache namespace and
   visible non-blank tiles. Missing cache must remain degraded and offer the
   explicit refresh action; a tile template or transparent response is not
   enough.
5. Preserve raster tile cache unless a documented cache invalidation condition
   is met. `/data/scout/raster-tiles` is refreshed by stale/missing policy, not
   by deletion. A small increase in tile count after a connected run can mean
   only missing or stale tiles were fetched.
6. Preserve OCR cache unless the tile image hash, OCR engine, language, or
   engine version changes. Empty OCR results are valid cache entries, but a
   missing OCR dependency/stage remains a typed blocker rather than a valid
   empty result.
7. Check terrain source coverage separately from display overlay count. Four
   terrain overlay PNGs mean four display modes; the actual DTM/DEM source tile
   count, grid-cell count, no-data coverage, full-route GeoTIFF hash, and route
   coverage must come from terrain artifacts. Confirm the persisted Navigation
   projection has the current route-input fingerprint and explicit ridge/valley
   counts or blockers before opening the Navigation page.
8. Check CWA evidence by feature family. `0` warning features can be a valid
   result when no active CWA warning intersects the route/bbox; it does not
   mean observation or QPF fetch failed. CWA weather/QPF artifacts are
   **no-cache evidence**: every explicit connected preparation must call CWA
   again and write a current-run snapshot or current blocker. Do not restore
   CWA weather, warning, observation, QPF, or CWA-derived environment values
   from a durable source workspace. Every CWA source artifact and every
   CWA-derived model/candidate output must expose hour-precision timing
   metadata: API request attempt time, successful fetch time when data was
   returned, forecast/observation valid-from and valid-until windows when the
   provider includes them, `time_precision: hour`, and timezone. Missing
   credentials or failed fetches must record the current attempt hour and leave
   fetch/validity hours empty rather than implying fresh evidence.
9. Check GEE evidence by status. `soil-moisture` and `antecedent-rain` may
   produce a `missing_credentials` status feature when `SCOUT_GEE_ENABLED`,
   Earth Engine credentials, or the live fetcher are unavailable. This is a
   candidate status overlay, not SMAP/GPM numeric evidence. When credentials
   are present and explicit fetch is attempted, `fetch_failed` with a
   `gee_http_error:403` blocker means Google Earth Engine access or Cloud
   project registration is incomplete; it must not collapse to
   `missing_credentials`. On Scout Pi, do not override
   `/data/scout/secrets/live-runtime.env` GEE values with empty compose
   defaults. GEE numeric values are current-run snapshots and must declare
   `cacheable: false`, `ttl_seconds: 0`, and
   `must_refetch_on_prepare: true`; do not restore them from a source workspace.
10. Confirm geology remains a refreshable runtime provider. Its opening cache
    may be prepared, but the clone receipt must say
    `geology_frozen_at_preparation=false`. Exercise connected refresh and verify
    it updates only dynamic provider evidence/cache without replacing the
    primary route-derived layer manifest.
11. Confirm Boss/route-pressure artifacts after risk outputs exist. Boss Points
    are generated as a post-process and remain part of the 32-layer UI contract,
    not a `--layers` input.
12. Run both gates:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
     --repo-root .

   PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
     --repo-root . \
     --project-root /data/scout/admin/pretrip-workspaces/chilai_nanhua_day1 \
     --require-workspace
   ```

13. Run the browser smoke gate when Playwright is available:

   ```bash
   node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
   ```

14. Qualify the actual user-facing process after restart. On the workstation,
    this is `127.0.0.1:9099`; on Scout hardware, verify through `scout.local`,
    not only loopback. Exercise `/admin/pretrip?tiles=local`,
    `/admin/debug?tiles=local`, and `/admin?tiles=local`, including OSM,
    historical-map, Navigation, and raster refresh behavior.

The expected successful connected run has a preparation manifest whose
`requested_layers` are the 23 preparation-backed layers above. The admin UI may
still expose 31 or 32 controls depending on surface: `completed-track` is
after-action/admin only and should not appear on `/admin/pretrip` or
`/admin/debug`. Historical run logs that describe importer-only completion,
no-PBF retries, post-run GeoJSON repair, manual page backfills, or creating a
second workspace are incident history, not the current procedure.

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
- A Dashboard clone succeeds through one GPX import plus one full preparation
  in the new target, without overwriting the source, creating `_v2`, or relying
  on a page-triggered backfill.
- Configured local OSM PBF produces workspace-local route extracts, render
  GeoJSON, a feature index, and browser-visible MapLibre features before the
  clone receipt is complete.
- Selected/profile-required raster sources have valid route-scoped opening
  caches when provider policy permits; the selected historical theme is visibly
  rendered and every cache-backed control retains explicit refresh.
- Full-route terrain and the persisted Navigation projection are compiled from
  the target's route identity. Missing coverage/compiler work is blocked or
  degraded, never represented as a successful empty Navigation result.
- CWA/GEE remain current-run evidence and geology remains refreshable after
  import; explicit connected refresh does not rerun GPX import or replace the
  primary route-derived layer manifest.
- Workspace writes stay under the selected project output directory or declared
  cache roots.
- The job never mutates Phase 1 runtime state, Phase 2 Brain state, incident
  stores, provider send queues, or final `MissionGraph` artifacts.
- `/admin/pretrip` can render layer readiness from the projection output, and
  `/admin/debug` can show the job timeline as read-only projection events.
