# Scout Weather And Environmental Sensing Spec

Date: 2026-06-14

## Objective

`Scout Weather And Environmental Sensing`（天氣與環境感知） defines how Scout
uses official weather, route-local observations, satellite soil moisture,
terrain, geology, seismic, tide, daylight, and historical route evidence to
support each pretrip **go/no-go**（是否出發） review.

The goal is not to create an automatic hazard truth engine. The goal is to
make every go/no-go decision carry more useful, source-backed context:

- what official warnings are active near the route;
- what recent and forecast weather says about rain, wind, fog, heat, cold, and
  typhoon exposure;
- whether the route has antecedent wetness（前期濕潤度） or root-zone soil
  moisture signals;
- whether terrain, geology, earthquake, or historical route-note evidence
  suggests a segment deserves extra review;
- what data is missing, stale, coarse, or not authoritative enough.

All outputs in this spec are **candidate evidence**（候選證據） until a human
reviewer accepts or rejects them. Model interpretation and external API output
must not mutate Phase 1 runtime safety truth, call `/safety/*`, or write Phase 2
Brain facts.

## Scope

In scope:

- CWA OpenData weather, warning, observation, forecast, astronomy, tide, marine,
  health-weather, earthquake, and climate/station background evidence;
- Google Earth Engine（GEE） access to NASA SMAP soil-moisture products and
  NASA GPM IMERG precipitation products;
- local DEM/DTM terrain products, TEII/risk factors, and route-aligned samples;
- optional geology/slope-disaster provider plugins when source licensing and
  API contracts are explicit;
- Pydantic AI semantic mediation（語意中介） over already-collected evidence;
- `/admin/pretrip`, `/admin`, and `/admin/debug` map/timeline projections;
- fixture-backed tests and replay with zero live network calls.

Out of scope:

- live runtime safety truth promotion;
- automatic dispatch, rescue notification, or outbound messages;
- direct landslide prediction from SMAP alone;
- client-side exposure of CWA or GEE credentials;
- committing large raw payloads, DEM rasters, or API dumps to git;
- relying on live network in tests.

## Decision Boundary

Scout should distinguish three layers:

1. `provider evidence`（來源證據）: raw or normalized CWA/GEE/geology/terrain
   data with provenance.
2. `review candidates`（審查候選）: route-linked CP, segment, timeline, or layer
   items derived from one or more evidence sources.
3. `reviewed departure decision`（已審核出發決策）: human-reviewed go/hold/no-go
   record with accepted evidence refs.

Only layer 3 may affect departure approval. Layers 1 and 2 can inform the UI,
Pydantic AI answers, and review queues, but remain non-authoritative.

## Current MVP Workspace Flow

The current local MVP path is:

```text
local weather points / warnings
  + route segments
  + weather_daylight_evidence
  -> pretrip_weather_decision_collection
  -> route_weather_package
  -> weather_source_manifest
  -> weather_decision_candidates
  -> scout.ai.weather_window.assess.v0
```

Canonical refs:

- `outputs/route_weather_package.json`
- `normalized/weather/weather_source_manifest.json`
- `candidates/weather_decision_candidates.json`
- `outputs/weather_daylight_evidence.json`

`pretrip_weather_decision_collection` is a workspace-local orchestration step. It
does not call GEE, expose `SCOUT_CWA_API_KEY`, or promote runtime safety truth.
When local weather points are missing, it still writes a conservative `DELAY`
candidate with missing fields so the Scout AI answer path does not guess from a
placeholder.

Current implementation status:

- CWA/OWDP fetcher（中央氣象署開放資料抓取器） exists in the server-side
  integration module and must resolve credentials through `SCOUT_CWA_API_KEY`
  first, with legacy `CWA_API_KEY` accepted only as a compatibility fallback.
- Admin live weather overlay（即時天氣圖層） remains opt-in through
  `SCOUT_WEATHER_API_ENABLED`. Its live summary fetch path is still Open-Meteo
  only; CWA output should be prepared as workspace evidence before becoming map
  or review candidates.
- GEE readiness（Google Earth Engine 可用性） is represented as a status gate:
  project, auth mode, and credential references can be checked without calling
  Earth Engine. Full SMAP/GPM fetching remains an explicit map-preparation
  step, never an implicit browser request.

## Source Families

### CWA OpenData

`CWA OpenData`（中央氣象署開放資料） is the primary official weather source for
Taiwan route planning.

Current Scout dataset groups:

| Family | Datasets | Scout use |
| --- | --- | --- |
| Warnings（警特報） | `W-C0033-001` to `W-C0033-005` | Official heavy rain, low/high temperature, fog, wind, and typhoon-related warning layers. |
| Typhoon（颱風） | `W-C0034-001`, `W-C0034-005` | Departure blockers or high-priority warning review when route time/bbox intersects typhoon impact. |
| Rain and weather observations（雨量與氣象觀測） | `O-A0002-001`, `O-A0001-001`, `O-A0003-001` | Nearby station markers, 1h/3h/24h rain, wind, gust, temperature, humidity, visibility. |
| QPF / quantitative precipitation forecast（定量降水預報） | `F-C0041-001` to `F-C0041-008` | Gridded route-bbox/corridor rainfall accumulation, peak window, lead-time, update cadence, and uncertainty review. |
| QPESUMS near-real-time rainfall grid（即時降雨格點） | `O-B0045-001`, `F-B0046-001` | Past-one-hour radar QPE and next-one-hour QPF numeric grids for route, team-position, target, and corridor sampling. |
| Township forecast（鄉鎮預報） | `F-D0047-021`, `F-D0047-023`, `F-D0047-041`, `F-D0047-043`, `F-D0047-089`, `F-D0047-091`, `F-D0047-093` | Route-township forecast timeline for rain, wind, temperature, comfort, and UV review. |
| Astronomy（日月出沒） | `A-B0062-001`, `A-B0063-001` | Dark-arrival warning, night-travel risk, headlamp/retreat time review. |
| Tide and marine（潮汐與海象） | `F-A0021-001`, `O-B0075-*` | Coastal trail, river-mouth, island, and tide-sensitive route review. |
| Health weather（健康氣象） | `M-A0085-001`, `F-A0085-002` to `F-A0085-005` | Heat injury, cold injury, temperature-difference review; advisory only. |
| Earthquake（地震） | `E-A0015-001`, `E-A0016-001` | Recent earthquake context near route; raises geology/terrain review priority but does not prove trail damage. |
| Climate/station background（氣候與測站背景） | `C-B0024-001`, `C-B0025-001`, `C-B0074-001`, `C-B0074-002` | Recent 30-day observation, daily rain, station metadata, and missing-station explanations. |

CWA credentials must stay server-side through `SCOUT_CWA_API_KEY`. The client UI
may request workspace evidence or a server-side fetch job, but must never receive
the API key.

### CWA QPF And Severe-Weather Update Cadence

`QPF`（定量降水預報） must be treated as its own source family, not merely as
generic township rain text. Scout should ingest CWA gridded QPF records into:

- `qpf_grid_layer`（定量降水格點圖層）: candidate GeoJSON points or polygons
  clipped to the route bbox/corridor;
- `qpf_route_timeline_evidence`（路線定量降水時間軸）: route-window events with
  valid time, lead time, accumulation window, and linked segment/checkpoint when
  available;
- `qpf_corridor_summary`（路線走廊定量降水摘要）: max, mean, p95, peak window,
  heavy-rain event count, and uncertainty policy.

Dataset window convention:

| Dataset | Window | Scout interpretation |
| --- | --- | --- |
| `F-C0041-001` | 0-6h | 6h accumulated QPF. |
| `F-C0041-002` | 6-12h | 6h accumulated QPF. |
| `F-C0041-003` | 12-18h | 6h accumulated QPF. |
| `F-C0041-004` | 18-24h | 6h accumulated QPF. |
| `F-C0041-005` | 0-3h | Intensified severe-weather nowcast window. |
| `F-C0041-006` | 3-6h | Intensified severe-weather nowcast window. |
| `F-C0041-007` | 6-9h | Intensified severe-weather nowcast window. |
| `F-C0041-008` | 9-12h | Intensified severe-weather nowcast window. |

Update cadence policy:

- regular QPF products are treated as 6-hour cadence unless provider metadata
  says otherwise;
- severe-weather operation（劇烈天氣作業）, including land typhoon warning,
  sea typhoon warning with significant land impact, large-scale heavy rain, or
  severe heavy-rain watch, may use intensified 3-hour cadence;
- Scout must preserve `qpf_update_cadence`, `qpf_lead_time`, and source
  timestamp so stale QPF cannot silently become low risk.

Uncertainty policy:

- Taiwan high-mountain terrain causes strong orographic rainfall effects;
- short, small, fast mesoscale convection can displace intense rainfall over a
  few kilometers or hours;
- ocean initial conditions remain less constrained than dense land station
  networks;
- forecast error grows with lead time.

Therefore QPF supports `hold review`, `warning candidate`, or compound
environment candidates. It must not be phrased as "this exact slope will/will
not receive X mm" or used as direct runtime safety truth.

### CWA QPESUMS Numeric Rainfall Grids

Scout uses the CWA file API products `O-B0045-001`（過去一小時雷達定量降雨
估計）and `F-B0046-001`（未來一小時定量降水預報）as numeric weather grids.
They are distinct from the backward-compatible township/forecast-derived
`outputs/environment/cwa/qpf_grid.geojson` point artifact.

The server normalizer must read dimensions, resolution, origin, timestamp,
unit, and cell ordering from structured provider metadata. It validates the
declared shape against the cell count, converts provider no-data sentinels to
`null`, reverses the provider's lower-left/longitude-first stream into Scout's
north-first row order, and converts the TWD67 source coordinates to WGS84. The
artifact records the transform method and conservative coordinate uncertainty;
it must never relabel untransformed TWD67 coordinates as WGS84.

One explicit preparation run writes:

```text
outputs/environment/cwa/rainfall/rainfall_grid_manifest.json
outputs/environment/cwa/rainfall/grids/O-B0045-001/<timestamp>-<hash>.json.gz
outputs/environment/cwa/rainfall/grids/F-B0046-001/<timestamp>-<hash>.json.gz
outputs/environment/cwa/rainfall/route_grid_projection.geojson
outputs/environment/cwa/rainfall/route_precipitation_trend.json
```

The gzip frames are immutable, content-addressed numeric snapshots. Persisting
them does not make them reusable as current weather truth: every explicit
preparation must refetch, while older frames remain provenance/history. The
route projection contains only route-bbox cells for display; browser, mobile,
and Raspberry Pi clients never load or process the full grid.

`route_precipitation_trend.json` always contains a 1.5 km route-buffer summary.
Provider invalid values (`-1` for QPE and `-99` for QPF) remain missing/unknown;
they must never be silently converted to zero rain. It
uses an explicit, authorized current position and an explicit target id only
when supplied to the cache-only admin evaluator; it does not infer the target,
does not store raw current/target coordinates, and otherwise reports
`awaiting_position_and_target`. QPE-to-QPF difference is an observation versus
forecast comparison, not a measured rainfall rate. Target ETA beyond the
one-hour forecast horizon must remain outside the supported horizon rather
than being extrapolated.

Before pairing QPE/QPF cells, Scout validates product kind, dimensions,
resolution, WGS84 bounds, and source-time alignment. Confidence is based on
route samples with valid paired coverage, not a ratio between grid-cell count
and route-point count. Freshness uses one shared policy in the map, public
manifest, and route sampler: QPF expires at its provider `validUntil`, while
QPE remains current for at most two hours after `sourceTimestamp` because its
`validUntil` denotes the end of the past accumulation window rather than a
forecast expiry. A product more than 15 minutes in the future is also invalid.
If either paired product is stale, the route package becomes `stale_data` and
confidence is forced to zero even though the immutable evidence remains stored.

The browser endpoint `GET .../rainfall-grids` returns only redacted product
metadata. `POST .../rainfall-trend` requires `confirmLocationAccess=true`, a
typed approval reference/time/scope, validates coordinates/timestamps, samples
prepared workspace frames, returns compact values, and never fetches upstream
or writes the submitted position to disk. It appends only a sanitized approval
audit event (approval reference/time/scope and `rawCoordinatesPersisted=false`).
All outputs remain candidate-only, not runtime safety truth.

### CWA Radar And Satellite Imagery

CWA radar echo and Himawari satellite imagery are temporal child overlays of
the existing `cwa-weather` layer. They do not create new top-level Scout layer
ids. The verified OpenData registry includes:

- radar composite `O-A0058-001` through `O-A0058-006` for larger/Taiwan-near
  extents, terrain/no-terrain variants, and transparent overlays;
- single-site rainfall-radar products `O-A0084-001` through `O-A0084-003`;
- satellite color `O-B0028-*`, black-white `O-B0029-*`, enhanced color
  `O-B0030-*`, and visible `O-B0031-*`, with `001/002/003` representing
  full-disk/global, East Asia, and Taiwan products;
- true-color products only through a separately verified CWA satellite-portal
  adapter. Scout must not invent or scrape an undocumented URL.

The explicit one-shot worker is enabled with
`pretrip_layer_preparation --prepare-cwa-imagery` and requires all of:

```text
profile=mac-workstation
network_mode=explicit-fetch
allow_network_fetch=true
SCOUT_CWA_SERVER_IMAGERY_CAPABLE=1
```

It fetches metadata/images, keeps raw frames in
`SCOUT_CWA_IMAGERY_CACHE_ROOT` outside the workspace, builds bounded display
assets, georeferences them from registry metadata, samples the GPX route
buffer, and estimates echo/cloud motion. Raspberry Pi and mobile profiles must
not decode, resize, classify, sample, or motion-process these images. They may
only consume the compact JSON packages and cache-only display assets.

The server worker enforces an 8 MiB/20-megapixel limit per source image, a hard
24-frame limit per product (evenly spaced so the full 12-hour window remains
represented), one job at a time, and a retry cooldown after both successful
and failed jobs. The worker also requires an operator-controlled server
capability attestation and rejects ARM/Raspberry Pi hosts independently of the
requested profile.

Recent animation windows merge the official short-term-history response when a
dataset exposes one with the bounded rolling cache of timestamps actually
fetched by Scout. If CWA returns no history resource, the first run contains
only the latest frame and later runs accumulate real observed frames; Scout
does not fabricate a 3/6/9/12-hour backfill.

Full-disk products are converted server-side from the Himawari geostationary
view into a transparent Web-Mercator-aligned overlay before map delivery; the
raw disk is never exposed as a fallback overlay or stretched affinely over a
WGS84 rectangle. Full-disk remains
`routeSamplingSupported=false`, while East Asia and Taiwan products use affine
source georeferencing for map and eligible route sampling. True-color is
visual/corroborating only and uses the configured source's `Last-Modified`
timestamp.

Dashboard MAP embeds the canonical pretrip map and controls `cwa-weather`
through a same-origin state bridge. It exposes product, 3/6/9/12-hour window,
frame, radar/satellite opacity, play/pause, timestamp, and delay without
duplicating projection or image-processing code. The browser path remains
cache-only; all fetch, decode, georeference, route sampling, and motion work is
server-side, while Pi/mobile surfaces consume only prepared display assets and
compact candidate features.

Required workspace outputs:

```text
outputs/environment/cwa/imagery/registry_snapshot.json
outputs/environment/cwa/imagery/radar_frames_manifest.json
outputs/environment/cwa/imagery/satellite_frames_manifest.json
outputs/environment/cwa/imagery/route_imagery_sampling.json
outputs/environment/cwa/imagery/radar_motion_estimate.json
outputs/environment/cwa/imagery/weather_imagery_manifest.json
outputs/route_weather_risk_package.json
outputs/route_weather_lora_alert.json
```

The route package exposes `currentRainOnRoute`, `nearbyStrongEcho`,
`rainBandApproaching`, `estimatedRainArrivalMinutes`, `convectiveCellScore`,
`satelliteConvectiveCloudScore`, `cloudMotionTowardRoute`,
`dataDelayMinutes`, and `confidence`. A boolean is `null`, not reassuring
`false`, when coverage, georeferencing, freshness, or classification is not
adequate.

TEII remains immutable terrain evidence. Weather imagery may add review
candidates for rain plus dry creek, rain plus scree/cliff, convective cloud or
thunderstorm plus ridge, and strong echo plus steep descent only when the
terrain class/descent metadata is explicit. TEII alone must not invent a creek,
cliff, scree, ridge, or descent classification.

The LoRa artifact is byte-bounded candidate output only. Producing it does not
authorize an RF send, hardware access, Phase 1 mutation, or `/safety/*` call.
Recurring near-real-time polling remains a separately approved cron/systemd or
server workflow; this implementation does not silently install monitoring.

### SMAP Soil Moisture Through GEE

`SMAP soil moisture`（衛星土壤含水量） is useful as a hydrologic background
layer, especially before typhoons or prolonged rain.

Current GEE source collection:

- `NASA/SMAP/SPL4SMGP/008`: SMAP L4 3-hourly model-assimilated surface,
  root-zone, and profile soil moisture. Scout normalizes `sm_surface`,
  `sm_rootzone`, `sm_profile`, `sm_surface_wetness`,
  `sm_rootzone_wetness`, `sm_profile_wetness`, and `surface_temp`.
  Deprecated `NASA/SMAP/SPL4SMGP/007` must not be used.

Scout interpretation rules:

- use L4 for route-scale hydrologic background and root-zone trend（根區趨勢）;
- calculate corridor or bbox summaries, not single-slope conclusions;
- preserve grid scale, latency, quality flags, and stale risk;
- compare recent 7/14/30/90 day values against same-season or project baseline
  when enough history exists;
- combine with CWA rainfall, terrain, geology, and route-note evidence before
  proposing route candidates.

SMAP must not be phrased as "this slope is safe/unsafe." It may support wording
like "the route bbox has elevated antecedent wetness, review steep/collapse-note
segments before departure."

### GPM IMERG Precipitation Through GEE

`GPM IMERG precipitation`（GPM IMERG 降雨估計） is useful as antecedent rain
context（前期雨量背景） before typhoons, fronts, or prolonged rain. It should
answer "how wet has the route-scale environment recently been?", not "is this
exact slope safe now?"

Current GEE source collection:

- `NASA/GPM_L3/IMERG_V07`: GPM IMERG precipitation estimate. Scout normalizes
  route bbox/corridor samples into `precipitation_rate_mm_hr`,
  `precipitation_mm`, `MWprecipitation`, `IRprecipitation`, `randomError`, and
  `probabilityLiquidPrecipitation` when present.

Scout interpretation rules:

- calculate route bbox/corridor summaries for last 1h, 3h, 24h, and 72h
  accumulation;
- preserve grid scale, query body, raw payload hash, request timestamp, latency,
  and stale risk;
- treat GPM as satellite/model rainfall estimate（衛星/模式降雨估計）, not an
  official CWA warning, station observation, or terrain hazard truth;
- combine with CWA QPF/observations, SMAP wetness, terrain, geology, and
  historical route-note evidence before proposing CP/segment candidates.

GPM may support wording like "route-corridor antecedent rain is elevated; review
collapse-note or steep sections before departure." It must not be phrased as
"the trail is blocked" or "this slope will fail."

### Terrain And Risk

`Terrain evidence`（地形證據） comes from local DEM/DTM and route sampling:

- elevation, slope, aspect, roughness, curvature, no-data coverage;
- TEII_20m and other configured terrain factors;
- risk heatmap/ribbon, risk-delta, and calibrated factor analysis;
- terrain hillshade, elevation tint, slope shading, and contours.

Terrain layers explain why a route section deserves review. They are not
weather and not standalone hazards. Compound review happens only when terrain
evidence is joined with weather/hydrology/geology/history.

### Geology And Landslide Context

`Geology context`（地質背景） is an optional source family. Candidate providers
may include Taiwan geology cloud services, government open-data downloads,
landslide inventory, sensitive-area polygons, fault or dip-slope layers, and
route-local operator-provided shapefiles.

Required provider contract:

- source owner, license, URL or local path, acquisition timestamp, bbox;
- raw payload hash and normalized artifact refs;
- CRS, geometry type, simplification, and precision policy;
- field mapping from provider properties to Scout categories;
- stale-risk policy, especially after large rain or earthquake events.

Scout categories should stay descriptive:

- `geology_sensitive_zone_candidate`;
- `historical_landslide_candidate`;
- `dip_slope_review_candidate`;
- `fault_or_fracture_context_candidate`;
- `post_earthquake_review_candidate`.

These records raise review priority. They must not assert that a trail is
currently blocked unless an accepted, source-backed closure or field report says
so.

### Historical Route And Map Perception Evidence

Historical GPX route notes, Overpass tags, map labels/OCR, web case evidence,
and route-guide material are semantic context sources. They can explain why an
environment signal matters:

- "大崩壁", "高繞", "落石", "乾溝", "溪水暴漲", "白牆", "通訊點";
- OSM tags for trail, shelter, water, peak, parking, hazard-like features;
- OCR map labels and guidebook timing/terrain notes.

Pydantic AI may classify and summarize these notes, but every generated CP or
Ln proposal must keep `source_attribution` and `runtime_safety_truth=false`.

## GEE API Contract

Scout may integrate Google Earth Engine through these server-side paths:

- Python API: best default for map preparation and admin-triggered fetches.
  Requires `ee.Authenticate()` or pre-existing credentials and
  `ee.Initialize(project=...)`.
- REST API: acceptable for server components that prefer direct HTTP. Useful
  resources include map tile creation, tile retrieval, table feature
  computation, value computation, image pixel computation, and map export.
- `reduceRegion` / route-corridor reductions: preferred for bbox/corridor
  statistics and point-buffer summaries.
- `getDownloadURL`: only for small chunks or reviewed GeoTIFF/NumPy exports; do
  not use it for large hidden bulk downloads.
- GEE Code Editor: prototyping only, not a Scout production dependency.

Environment variables:

```text
SCOUT_GEE_ENABLED=true|false
SCOUT_GEE_PROJECT=<google-cloud-project-id>
SCOUT_GEE_PROJECT_ID=<google-cloud-project-id>
SCOUT_GEE_AUTH_MODE=adc|service_account|user|user_oauth
SCOUT_GEE_SERVICE_ACCOUNT=<optional-service-account-email>
SCOUT_GEE_ACCOUNT=<optional-user-account-email>
SCOUT_GEE_CREDENTIALS_PATH=<optional-local-json-path>
GOOGLE_APPLICATION_CREDENTIALS=<optional-local-json-path>
```

Credential values and service-account keys must never be committed, embedded in
artifacts, or exposed to browser clients.

## Artifact Model

`EnvironmentEvidencePackage`（環境證據包） is the top-level package emitted by
map preparation.

Recommended project refs:

```text
outputs/environment/
  environment_evidence_package.json
  environment_factor_matrix.json
  go_no_go_review_draft.json
  cwa/
    cwa_weather_evidence.json
    warnings.geojson
    observations.geojson
    qpf_grid.geojson
    qpf_route_timeline.json
    qpf_corridor_summary.json
    forecast_timeline.json
    astronomy_timeline.json
    tide_marine_timeline.json
  smap/
    smap_soil_moisture_evidence.json
    smap_soil_moisture_timeseries.csv
    smap_soil_moisture_summary.geojson
    smap_overlay_manifest.json
  gpm/
    gpm_imerg_precipitation_evidence.json
  gee/
    smap_l4_timeseries.json
    smap_l4_corridor_summary.json
    soil_moisture_grid.geojson
    gpm_imerg_raw_summary.json
    gpm_imerg_timeseries.json
    gpm_imerg_corridor_summary.json
    antecedent_rain_grid.geojson
  geology/
    geology_context_evidence.json
    geology_context.geojson
  compound/
    compound_environment_candidates.geojson
    compound_environment_timeline.json
```

Each provider evidence record must include:

- `source_id`;
- `source_family`;
- `provider`;
- `dataset_id` or `collection_id`;
- `api_method`;
- `endpoint` or GEE collection path;
- `query_body` or query descriptor;
- `bbox_wgs84`;
- `route_corridor_m`;
- `time_window`;
- `request_timestamp`;
- `http_status` or provider status;
- `raw_payload_ref` or `raw_payload_hash`;
- `normalized_artifact_ref`;
- `license_note`;
- `confidence`;
- `stale_risk`;
- `runtime_safety_truth=false`.

Large raw payloads should live only in the workspace/cache area and be referenced
by hash/path. CI fixtures must remain small and deterministic.

## Environmental Factor Matrix

`environment_factor_matrix`（環境因子矩陣） is a route-linked table used by UI,
Pydantic AI, and review policy. It should preserve individual dimensions rather
than hiding them in one weighted score.

Minimum dimensions:

- `official_warning`: active CWA warning severity and type;
- `rain_observed`: recent 1h/3h/24h station rainfall;
- `rain_forecast`: route-township forecast rain signal;
- `qpf_accumulation`: route bbox/corridor QPF max, p95, mean, and event count;
- `qpf_peak_window`: QPF time window that drives the highest review concern;
- `qpf_update_cadence`: regular 6h or intensified 3h severe-weather cadence;
- `qpf_lead_time`: lead-time and accumulation-window metadata;
- `qpf_uncertainty`: mountain terrain, mesoscale convection, initial-condition,
  and lead-time uncertainty flags;
- `severe_weather_intensified_operation`: whether the evidence indicates a
  severe-weather intensified QPF operation/window;
- `wind_fog_temp`: wind/gust, fog/visibility, heat/cold signal;
- `daylight_margin`: planned ETA against sunset/civil twilight;
- `tide_marine`: tide or marine constraint for coastal/river-mouth routes;
- `antecedent_wetness`: SMAP L3/L4 recent percentile or anomaly;
- `rootzone_trend`: SMAP L4 root-zone increase/decrease;
- `antecedent_rain`: GPM IMERG 1h/3h/24h/72h route-corridor accumulation;
- `satellite_precipitation`: GPM provider metadata, limitations, and stale
  risk separate from official CWA weather;
- `earthquake_recentness`: recent significant/small-area earthquake context;
- `geology_context`: sensitive zone, landslide inventory, dip-slope, fault;
- `terrain_exposure`: slope, roughness, TEII_20m, corridor no-data;
- `historical_notes`: route-note or case evidence for collapse, detour, stream,
  fog, exposure, or communications.

The matrix must support:

- per-route, per-segment, per-checkpoint, and per-bbox summaries;
- source refs per factor;
- missing/stale flags per factor;
- percentile and absolute values where both are available;
- candidate-only `review_priority`, not direct safety mutation.

## Compound Candidate Rules

Scout should produce compound candidates when multiple independent source
families support the same review concern.

Examples:

- `rain_terrain_compound_candidate`: CWA heavy-rain warning plus high slope or
  high TEII_20m near a historical collapse note.
- `qpf_rain_terrain_compound_candidate`: high route-corridor QPF plus terrain,
  geology, SMAP wetness, or historical collapse/detour notes.
- `qpf_uncertainty_review_candidate`: QPF exists but lead-time, terrain, or
  mesoscale-convection uncertainty makes the go/no-go decision sensitive to
  further observation updates.
- `soil_saturation_review_candidate`: SMAP wetness percentile high plus recent
  rainfall plus route-note "大崩壁" or "高繞".
- `gpm_smap_hydrologic_compound_candidate`: GPM antecedent rain plus SMAP
  wetness, terrain/geology, and historical route-note evidence.
- `dark_arrival_candidate`: ETA beyond daylight margin plus forecast fog/rain.
- `stream_crossing_review_candidate`: recent rainfall plus route water crossing
  or dry-gully note.
- `post_earthquake_slope_review_candidate`: recent earthquake near route plus
  steep terrain/geology-sensitive area.
- `coastal_tide_review_candidate`: tide forecast overlaps route crossing/window.

Compound candidates must include a plain-language reason in Chinese and machine
readable refs:

```json
{
  "candidate_id": "environment.compound.segment_042.soil_saturation",
  "candidate_type": "soil_saturation_review_candidate",
  "route_link": {"segment_id": "segment_042"},
  "factor_refs": ["cwa.O-A0002-001.station_...", "smap.L4.grid_...", "route_note..."],
  "reason_zh": "前期土壤濕潤度偏高，且附近歷史航跡註記崩塌/高繞，建議行前審查。",
  "review_priority": "high",
  "runtime_safety_truth": false
}
```

## Go/No-Go Review Contract

`Go/No-Go Review`（出發決策審查） is the operator-facing synthesis. Scout may
draft a recommendation, but the accepted decision is human-reviewed.

Decision states:

- `go`: no unresolved hard blockers; warnings are reviewed or mitigated.
- `hold`: required evidence is missing/stale, or warnings need explicit review.
- `no_go`: policy-defined blocker is active for the route/time window.
- `manual_override_required`: operator can still choose to proceed only after
  writing a review reason and accepting residual risk.

Baseline blocker candidates:

- official CWA severe warning intersects route bbox/township and planned window;
- typhoon warning/path intersects route window;
- rainfall observation/forecast exceeds configured route policy;
- route-corridor QPF accumulation exceeds configured policy or QPF is stale
  during an active severe-weather/typhoon/heavy-rain window;
- daylight margin is negative beyond configured tolerance and no approved night
  plan exists;
- route policy marks a compound environment candidate as blocking;
- required terrain/geology/SMAP/CWA evidence is missing and the project policy
  marks it mandatory.

`go_no_go_review_draft.json` should contain:

- project id and route refs;
- review window and planned start/end;
- data freshness summary;
- blocker candidates;
- warning candidates;
- missing evidence;
- evidence source refs;
- Pydantic AI explanation refs when used;
- operator decision fields left empty until review.

The final accepted record should be separate from the draft and include reviewer,
timestamp, decision, accepted mitigations, unresolved warnings, and source hashes.

## Pydantic AI Role

Pydantic AI is a semantic mediator（語意中介）, not the owner of truth.

Allowed:

- summarize weather/environment factors for the review panel;
- explain why a candidate CP was proposed;
- classify route notes and provider tags into environmental concern types;
- rank review priorities based on the factor matrix;
- generate missing-evidence questions for the operator.

Disallowed:

- making the final go/no-go decision without human review;
- promoting candidate evidence to runtime safety truth;
- inventing API values or filling missing provider data;
- hiding stale/missing source warnings;
- sending messages or calling `/safety/*`.

Every AI output must be validated against a schema and must preserve source
refs. A model answer without source refs is UI prose only and cannot create a
candidate.

## UI Requirements

All three admin map surfaces should expose environment evidence consistently.

Layer groups:

- `weather-api`: CWA warnings, observations, forecast, astronomy, tide/marine;
- `qpf-grid`: CWA QPF accumulation grid, route-corridor summary, and peak
  time-window markers;
- `soil-moisture`: SMAP L3/L4 surface, root-zone, anomaly/percentile overlays;
- `antecedent-rain`: GPM IMERG route-corridor rainfall accumulation grid and
  1h/3h/24h/72h summary;
- `geology`: sensitive zones, historical landslide inventory, dip-slope/fault
  context when available;
- `terrain`: DEM/DTM hillshade, slope shading, contours, route samples;
- `compound-environment`: route-linked review candidates and go/no-go draft
  markers.

Timeline evidence:

- active warning intervals;
- forecast route windows;
- sunrise/sunset/moon/tide events;
- rainfall accumulation milestones;
- QPF peak accumulation windows and 3-hour intensified-update milestones;
- soil moisture percentile/anomaly events;
- GPM IMERG antecedent-rain accumulation milestones;
- recent earthquake review events;
- compound review candidates linked to CP/segment/frame.

Double-clicking any environment timeline element must focus the map to the
feature, segment, station, grid cell, or bbox context. If the evidence has no
exact coordinate, the UI must state whether it is township-level, bbox-level, or
SMAP grid-level.

## Map Preparation Integration

`LayerPreparationJob` should own environment sensing fetch/normalization because
it already knows:

- selected golden route;
- reference-track bbox;
- route corridor;
- project time window;
- requested layers;
- network policy;
- cache roots and output refs.

Suggested layer names:

```text
weather-api,cwa-weather,soil-moisture,smap-soil-moisture,
antecedent-rain,gpm-imerg-precipitation,
geology,earthquake-context,environment-factor-matrix,
compound-environment,go-no-go-review
```

The job may run these adapters in `explicit-fetch` mode only when the operator
sets `--allow-network-fetch`. In `no-network`, it must read existing workspace
artifacts or emit a missing/stale evidence report.

Alpha local-source adapters:

- `--smap-soil-moisture-source`（SMAP 土壤含水量來源） accepts a local
  fixture or pre-fetched GEE summary JSON and normalizes it into Scout evidence,
  time-series CSV, and summary GeoJSON. It preserves `raw_payload_ref`,
  `raw_payload_hash`, collection IDs, bbox/corridor, time window, grid scale,
  confidence, and stale risk.
- `--gpm-precipitation-source`（GPM IMERG 前期雨量來源） accepts a local
  fixture or pre-fetched GEE summary JSON and normalizes it into Scout
  antecedent-rain evidence, time-series JSON, corridor summary JSON, and
  `antecedent_rain_grid.geojson`. It preserves `raw_payload_ref`,
  `raw_payload_hash`, collection IDs, bbox/corridor, time window, grid scale,
  confidence, and stale risk.
- `--geology-context-source`（地質背景來源） accepts a local JSON/GeoJSON
  geology, landslide, dip-slope, fault, or operator context file and normalizes
  it into `geology_context_evidence.json` plus `geology_context.geojson`.

These alpha adapters are not live provider clients. They are the stable
artifact boundary used by tests, replay, and operator-prepared data. A future
GEE Python/REST fetcher or official geology-provider fetcher should write the
same raw summary shapes before this normalizer runs.

Connected alpha SMAP fetch:

- `--fetch-smap-gee`（抓取 SMAP/GEE） enables a server-side Earth Engine
  adapter in `LayerPreparationJob`.
- It is valid only with `--network-mode explicit-fetch` and
  `--allow-network-fetch`.
- It requires an explicit `--smap-start-date` and `--smap-end-date`.
- It creates `outputs/environment/gee/smap_l4_gee_raw_summary.json`, then runs
  the same SMAP evidence normalizer used by fixtures.
- It writes bounded normalized artifacts:
  `outputs/environment/gee/smap_l4_timeseries.json`,
  `outputs/environment/gee/smap_l4_corridor_summary.json`, and
  `outputs/environment/gee/soil_moisture_grid.geojson`.
- It may use `SCOUT_GEE_PROJECT_ID`, legacy `SCOUT_GEE_PROJECT`, or an
  explicitly provided server project, but credentials must remain server-side
  and must not be written to artifacts.

Connected alpha GPM IMERG fetch:

- `--fetch-gpm-imerg`（抓取 GPM IMERG/GEE） enables a server-side Earth Engine
  adapter in `LayerPreparationJob`.
- It is valid only with `--network-mode explicit-fetch` and
  `--allow-network-fetch`.
- It requires an explicit `--gpm-start-date` and `--gpm-end-date`.
- It creates `outputs/environment/gee/gpm_imerg_raw_summary.json`, then runs
  the same GPM evidence normalizer used by fixtures.
- It writes bounded normalized artifacts:
  `outputs/environment/gee/gpm_imerg_timeseries.json`,
  `outputs/environment/gee/gpm_imerg_corridor_summary.json`, and
  `outputs/environment/gee/antecedent_rain_grid.geojson`.
- It may use `SCOUT_GEE_PROJECT_ID`, legacy `SCOUT_GEE_PROJECT`,
  `--gpm-gee-project`, or an injected server-side client. Credentials must
  remain server-side and must not be written to artifacts.

The Scout AI assessment tool remains read-only. It reads prepared CWA, SMAP,
GPM, terrain, geology, factor matrix, compound candidates, and review draft
artifacts; it does not call GEE itself.

Scout AI registration:

- `scout.ai.environment_sensing.assess.v0` is the read-only tool for assessing
  prepared weather/environment evidence.
- Aliases: `scout.ai.environment_sensing.assess`,
  `scout.ai.weather_environment.assess`,
  `scout.ai.go_no_go_environment.assess`.
- The tool is callable through the dedicated
  `scout.ai.environment_sensing.assess` manifest or through the generic
  `scout.ai.tool.run` manifest. It reports source freshness, factor matrix
  dimensions, compound candidates, go/no-go draft state, missing evidence, and
  query plans without making live network calls.

## Testing

Required tests:

- parse fixture-backed CWA warning/observation/forecast/daylight/tide payloads;
- parse fixture-backed SMAP L3/L4 response summaries without live GEE;
- parse fixture-backed GPM IMERG response summaries without live GEE;
- verify injected fake GEE clients can exercise SMAP and GPM fetch paths without
  live network;
- normalize geology/context fixtures when provider data is available;
- build an environment factor matrix from local route, terrain, weather, SMAP,
  GPM, and route-note fixtures;
- generate compound candidates with source refs and `runtime_safety_truth=false`;
- draft go/hold/no-go review records without final human decision;
- verify missing/stale data stays visible and does not become zero-risk;
- verify tests make zero live network calls.

## References

- CWA OpenData API Swagger: <https://opendata.cwa.gov.tw/dist/opendata-swagger.html>
- CWA OpenData categories: <https://opendata.cwa.gov.tw/promotion/introduction/forecast>
  and sibling category pages for warning, observation, earthquake, climate,
  warning, mathematics, astronomy.
- GEE SMAP L3 collection: <https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL3SMP_E_006>
- GEE SMAP L4 collection: <https://developers.google.com/earth-engine/datasets/catalog/NASA_SMAP_SPL4SMGP_008>
- GEE GPM IMERG collection: <https://developers.google.com/earth-engine/datasets/catalog/NASA_GPM_L3_IMERG_V07>
- GEE REST API: <https://developers.google.com/earth-engine/reference/rest>
- GEE authentication: <https://developers.google.com/earth-engine/guides/auth>
- GEE service accounts: <https://developers.google.com/earth-engine/guides/service_account>
- GEE `reduceRegion`: <https://developers.google.com/earth-engine/apidocs/ee-image-reduceregion>
- GEE `getDownloadURL`: <https://developers.google.com/earth-engine/apidocs/ee-image-getdownloadurl>
