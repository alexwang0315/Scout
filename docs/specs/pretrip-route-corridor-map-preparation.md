# Spec: Pretrip Route-Corridor Map Preparation

Date: 2026-06-02

## Objective

Build **Route-Corridor Map Preparation**（依路線走廊地圖準備） for Scout Phase 4
pretrip planning. It runs after the Historical GPX Importer and uses the
imported golden/reference routes to prepare OSM, GIS, terrain, web-case, raster
label, POI, and risk evidence along the planned route.

The core rule:

```text
GPX importer output defines the route scope.
Map preparation fetches by bbox when needed.
Map preparation filters and interprets by along-track corridor.
Pydantic AI receives only source-backed, route-relevant evidence bundles.
```

This avoids route-independent searches that flood Pydantic AI with irrelevant
OSM tags, POIs, web snippets, or raster labels.

## Relationship To Existing Specs

This spec depends on:

- `docs/specs/pretrip-historical-gpx-importer.md`
  - produces `normalized/routes/route_evidence_bundle.json`;
- `docs/specs/pretrip-layer-preparation.md`
  - defines layer lifecycle, network flag boundary, and admin projections;
- `docs/specs/pre-trip-planning-admin.md`
  - defines OSM/GIS/web/raster perception, candidate-only boundaries, and
    Pydantic AI judgement semantics.

## Pipeline Position

```text
Historical GPX Importer
  -> route_evidence_bundle.json
  -> Route-Corridor Map Preparation
  -> along-route OSM / GIS / DEM / raster / web-case evidence bundles
  -> Pydantic AI semantic judgement
  -> candidate CP / Ln / POI / terrain risk / detour outputs
  -> human review in /admin/pretrip
```

Map preparation must fail closed or produce a validation warning when no route
evidence bundle exists. It should not silently run global or route-independent
searches.

## Spatial Policy

Scout uses two spatial concepts:

- **bbox fetch boundary**（bbox 抓取邊界）: the expanded WGS84 bbox used to fetch
  tiles, DEM/DTM, Overpass, weather, web-case keyword scope, and other source
  material;
- **along-track corridor**（沿路線走廊）: distance-filtered geometry around the
  golden route and historical reference tracks used to decide which evidence is
  relevant enough for semantic judgement.

The bbox is necessary for efficient source acquisition. The along-track corridor
is necessary for precision.

```text
route_evidence_bundle.route_scope_for_map_preparation.bbox_wgs84
  -> source acquisition boundary

golden route + reference tracks + corridor meters
  -> semantic precision boundary
```

Default policy:

```json
{
  "corridor_policy": "bbox_fetch_then_along_track_filter",
  "route_corridor_m": 500,
  "reference_track_corridor_m": 300,
  "poi_include_distance_m": 250,
  "web_case_keyword_distance_m": 1000,
  "terrain_sample_distance_m": 20
}
```

These defaults must be configurable per project because dense mountain routes,
road approaches, ridge traverses, and untracked side trips need different
distances.

## Source Adapters

### OSM / Overpass Vector Evidence

Overpass queries are planned from the route bundle:

- use `bbox_wgs84` as the query bbox;
- include trail, route, POI, emergency, natural, tourism, amenity, and terrain
  risk tags;
- preserve query body, endpoint, timestamp, HTTP status, raw payload hash,
  normalized artifact paths, OSM object type/id/tags/geometry, conversion rule
  version, confidence, and stale risk;
- filter normalized objects by distance to golden/reference tracks before they
  enter Pydantic AI semantic judgement;
- keep trail corridors as map evidence unless a tag is specific enough to
  propose a CP/Ln/POI candidate.

Initial OSM categories:

- `trail_corridor_candidate`;
- `hiking_route_candidate`;
- `shelter_candidate`;
- `water_source_candidate`;
- `parking_candidate`;
- `peak_candidate`;
- `terrain_risk_candidate`;
- `emergency_access_candidate`;
- `viewpoint_candidate`.

### GIS / Terrain Evidence

Terrain preparation uses local DEM/DTM and risk outputs inside the bbox, then
samples along the route:

- hillshade terrain visualization;
- elevation tint terrain visualization;
- slope shading terrain visualization;
- contour overlay;
- elevation samples;
- slope / roughness / TEII_20m / terrain risk dimensions;
- route risk ribbon;
- calibrated risk heatmap;
- risk delta between baseline and calibrated views;
- terrain-risk warning candidates for extreme excluded dimensions.

Preferred production terrain rendering uses a GeoTIFF/GDAL chain:

```text
DEM/DTM GeoTIFF
  -> GDAL hillshade
  -> GDAL slope
  -> GDAL color-relief for slope shading
  -> GDAL contour
  -> cut local tiles / GeoJSON
  -> /admin/pretrip display
```

Alpha bitmap overlays are acceptable as a bridge only when the manifest records
the DTM cell resolution, route-corridor width, processor, source checksums, and
candidate-only boundary metadata.

The alpha bitmap bridge emits four PNG overlays referenced by `project.json` and
`terrain_visualization.geojson`: `terrain_hillshade.png`,
`terrain_elevation_tint.png`, `terrain_slope_shading.png`, and
`terrain_contours.png`. These overlays are generated from the local DTM grid at
source cell resolution and clipped/projected to the route corridor. They are
display layers for `/admin/pretrip` and `/admin/debug`; they are not risk heat,
accepted hazards, or runtime safety truth.

`terrain visualization`（地形視覺化） and `risk heat`（風險熱區） must remain
separate:

- hillshade, elevation tint, slope shading, and contours are DEM/DTM display
  layers;
- route risk ribbon, calibrated risk heatmap, and risk delta are
  route-specific candidate-risk overlays;
- slope shading may support AI and human explanation, but by itself it is not an
  accepted hazard, Ln trigger, or runtime safety truth.

Terrain evidence sent to Pydantic AI should be compact and route-positioned. It
should not send large rasters or raw DEM payloads.

### Web Case Evidence

**Web Case Perception**（網路案例感知） is an explicit adapter, not a background
crawler.

Inputs:

- route family names from importer metadata;
- golden route node names;
- GPX route notes;
- OSM feature names;
- hut/shelter/water/peak/fork/trailhead names;
- manually supplied route keywords.

Query scope:

- generated query terms must be traceable to route or nearby feature refs;
- search results are accepted only if they can be linked to route family,
  named points, or along-track geometry;
- every result stores URL, retrieval time, title/snippet or snippet hash,
  query terms, stale-risk notes, source confidence, and review status.

Live web search must require explicit network mode. Fixture-backed tests use
stored snippets or saved HTML/text, not live network.

### Raster / Tile Label Evidence

**Raster Label Perception**（圖磚標註感知） reads local imagery, local map tiles,
or scanned route-guide references.

Map display imagery should prefer **WMTS-backed tile pyramid cache**
（以 WMTS 圖磚金字塔支撐的本機快取） when the source exposes WMTS. A single
fixed zoom cache is not sufficient for alpha map review because zooming will
stretch the same bitmap tiles and distort contour labels, line width, and map
symbol scale. For WMTS/XYZ sources, map preparation must store a multi-zoom tile
cache plan with:

- source id and provider;
- source kind, for example `wmts_kvp_tile`（WMTS KVP 參數式圖磚）;
- WMTS layer, style, TileMatrixSet（圖磚矩陣集合）, format, and endpoint hash;
- bbox fetch boundary and route-corridor scope;
- min/max zoom and per-zoom tile counts;
- cache root and runtime `/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png`
  proxy template;
- explicit network/cache policy.

`no-network` preparation writes only the plan and existing cache refs.
`explicit-fetch` preparation may seed the cache only from an allowlisted imagery
source and only into workspace or Scout Pi cache paths, never into repo
fixtures. The browser should request the current zoom's native tile when it is
available; fallback to a nearby cached zoom must be marked as resampled imagery
and should not be treated as precise evidence.

It may extract labels such as:

- `通訊點`;
- `水源`;
- `山屋`;
- `營地`;
- `遠眺...`;
- route names;
- warnings;
- viewpoint labels.

Every extracted label must preserve:

- tile or image source ref;
- z/x/y or image bbox;
- source image hash;
- OCR/vision confidence;
- label geometry;
- distance to route/reference tracks;
- candidate-only boundary.

### Historical GPX Evidence

Map preparation reuses importer outputs:

- golden route geometry;
- reference tracks;
- route-note candidates;
- GPX speed filter report;
- resume segment diagnostics;
- rest/camp area candidates;
- stale flags;
- semantic hints;
- source attribution.

Repeated notes around the same place should be grouped before entering the
review timeline, but semantically different notes must remain separate. For
example, `大崩壁`（collapse hazard） and `高繞`（technical detour / route action）
may describe the same damaged area, but should not be forced into one CP unless
a human reviewer merges or links them.

Map preparation must use filtered GPX-derived route geometry from the importer
when filter outputs exist. It must preserve `gpx_speed_filter_report_ref`,
`resume_segment_report_ref`, and `rest_area_candidates_ref` in every route,
terrain, OSM, risk, and semantic bundle that depends on the route geometry.
This prevents later OSM/GIS/web/raster interpretation from being based on raw
GPS jumps that the importer already diagnosed.

## Pydantic AI Semantic Judgement

**Pydantic AI semantic judgement**（Pydantic AI 語意中介判斷） is the bridge from
normalized GIS evidence to planning candidates. It is not a source of runtime
safety truth.

The input bundle should be compact and source-backed:

```json
{
  "artifact_kind": "pretrip_gis_semantic_input_bundle",
  "schema_version": "route_corridor_map_preparation.v1",
  "project_id": "nenggao_andongjun_alpha",
  "route_scope_ref": "normalized/routes/route_evidence_bundle.json",
  "evidence_items": [
    {
      "evidence_id": "overpass.node.123",
      "source_kind": "overpass_candidate",
      "candidate_type": "water_source_candidate",
      "tags": {"amenity": "drinking_water"},
      "distance_to_golden_route_m": 34,
      "nearest_route_distance_m": 7120,
      "source_refs": ["normalized/map/overpass_vector_evidence.geojson#node.123"],
      "confidence": "medium",
      "stale_risk": "medium"
    },
    {
      "evidence_id": "gpx_route_note.001",
      "source_kind": "gpx_route_note",
      "text": "大崩壁，高繞",
      "distance_to_golden_route_m": 9,
      "semantic_hints": ["collapse_hazard", "technical_detour"],
      "source_refs": ["normalized/notes/gpx_route_note_candidates.json#gpx_route_note.001"]
    }
  ],
  "boundary": {
    "candidate_only": true,
    "runtime_safety_truth": false
  }
}
```

Pydantic AI outputs:

```json
{
  "artifact_kind": "gis_perception_ai_judgements",
  "schema_version": "gis_perception_ai_judgements.v1",
  "model_provider": "pydantic-ai-cloud",
  "model_name": "configured-by-runtime",
  "prompt_version": "gis_semantic_classifier.v1",
  "prompt_hash": "...",
  "input_bundle_ref": "outputs/gis_semantic_input_bundle.json",
  "judgements": [
    {
      "judgement_id": "gis_judgement.001",
      "source_evidence_refs": ["gpx_route_note.001", "overpass.way.456"],
      "proposed_candidate_kind": "checkpoint_candidate",
      "proposed_semantic_key": "collapse_hazard",
      "proposed_ln_level": "L2_candidate",
      "reason": "Historical GPX note and nearby OSM terrain context both indicate collapse/detour risk.",
      "confidence": "medium",
      "stale_risk": "medium",
      "requires_human_review": true
    }
  ],
  "boundary": {
    "candidate_only": true,
    "observed_fact": false,
    "runtime_safety_truth": false,
    "phase1_runtime_mutation_allowed": false
  }
}
```

The AI may classify:

- CP density;
- Ln proposal level;
- hazard/water/shelter/camp/signal/parking/peak/viewpoint candidates;
- detour route candidate;
- manual-waypoint danger review;
- stale route-note warnings;
- source disagreement explanations.

The AI must not decide coordinate truth, accept candidates, compile final
mission graphs, or trigger runtime warnings.

## Commands

Normal connected operator preparation from importer output:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pretrip_layer_preparation \
  --project-root /tmp/scout-pretrip-alpha/nenggao_andongjun_alpha \
  --route-evidence-bundle normalized/routes/route_evidence_bundle.json \
  --layers osm,overpass,imagery,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,pois,hazards,corridors,route-notes \
  --route-corridor-m 500 \
  --reference-track-corridor-m 300 \
  --network-mode explicit-fetch \
  --allow-network-fetch \
  --ai-mode fixture-or-precomputed
```

Scout alpha fixed-material rebuild:

```bash
cd /home/alexwang0315/scout-fusion-agent-hw-test-20260601
SCOUT_PRETRIP_ADMIN_BASE_URL=http://127.0.0.1:9100 \
PYTHONDONTWRITEBYTECODE=1 \
bash tools/rebuild_pretrip_workspace_on_scout.sh
```

The rebuild script reads the fixed material structure under
`/data/scout/materials/pretrip/{project_id}`, regenerates GPX importer outputs,
restores durable admin evidence refs from the moved backup workspace, runs
route-corridor map preparation with Overpass, imagery, terrain, risk, route,
reference-track, CP/POI/hazard, corridor, retreat, and route-note layers, then
collects Sec. 6 route-context evidence into the local route context pack before
the final workspace verifier runs.

No-network fixture/replay planning remains available for deterministic tests:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pretrip_layer_preparation \
  --project-root /tmp/scout-pretrip-alpha/nenggao_andongjun_alpha \
  --route-evidence-bundle normalized/routes/route_evidence_bundle.json \
  --layers osm,imagery,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,pois,hazards,corridors,route-notes \
  --route-corridor-m 500 \
  --reference-track-corridor-m 300 \
  --network-mode no-network \
  --ai-mode fixture-or-precomputed
```

OSM raster tile fetching is not required in this alpha when Overpass vector
evidence is present. Overpass is the connected OSM data source for route
evidence and CP/POI synthesis; raster tiles are optional visual basemap support.

Admin projection endpoint:

```bash
curl http://127.0.0.1:9099/admin/pretrip/projects/nenggao_andongjun_alpha/layer-preparation
```

## Output Structure

```text
<project-root>/
  outputs/
    layers/
      layer_preparation_job.json
      layer_adapter_manifest.json
      layer_validation_report.json
      map_preparation_summary.json
      plans/
        overpass_query.ql
        web_case_query_plan.json
        raster_label_plan.json
      normalized/
        overpass_vector_evidence.geojson
        terrain_route_samples.geojson
        terrain_hillshade.png
        terrain_elevation_tint.png
        terrain_slope_shading.png
        terrain_contours.png
        terrain_hillshade_manifest.json
        terrain_elevation_tint_manifest.json
        terrain_slope_shading_manifest.json
        terrain_contours.geojson
        terrain_visualization.geojson
        web_case_evidence.json
        raster_label_evidence.geojson
      semantic/
        gis_semantic_input_bundle.json
        gis_perception_ai_judgements.json
      candidates/
        gis_checkpoint_candidates.json
        ln_proposals.json
        poi_candidates.json
        terrain_risk_candidates.json
        detour_route_candidates.json
      projections/
        pretrip_map_layers.json
        admin_debug_events.jsonl
```

## Project Structure

Current files:

```text
pretrip_layer_preparation.py
  Layer preparation orchestration.

pretrip_overpass_ingest.py
  Overpass raw/fixture normalization.

pretrip_gis_perception.py
  Candidate-only GIS perception structures.

pretrip_risk_heatmap.py
pretrip_risk_attribution_diagnostic.py
  Risk heat/delta and factor-attribution outputs.

admin_map_layers.py
  Layer declarations for /admin, /admin/debug, and /admin/pretrip.
```

Suggested additions:

```text
pretrip_route_corridor_map_preparation.py
  Route-evidence-bundle reader, bbox/corridor filtering, and semantic input writer.

pretrip_web_case_evidence.py
  Explicit web-case query plan and fixture-backed evidence adapter.

pretrip_raster_label_evidence.py
  Local raster/tile label extraction adapter contract.

tests/test_pretrip_route_corridor_map_preparation.py
  Fixture-backed route bundle, OSM, GPX, terrain, and AI input tests.
```

## Testing Strategy

Fixture-backed tests only by default.

Unit tests:

- route evidence bundle is required;
- bbox fetch boundary is derived from importer output;
- filtered GPX provenance is carried into layer and semantic outputs;
- resume segments remain review warnings instead of being treated as continuous
  walkable evidence;
- rest/camp area candidates remain CP candidates available to semantic bundles;
- OSM objects outside along-track corridor are excluded from AI input;
- nearby OSM POIs inside corridor produce candidate evidence;
- GPX notes and OSM tags share `source_attribution` but remain separate source
  types;
- stale GPX notes keep stale flags;
- `大崩壁` and `高繞` remain separate semantic keys unless explicitly linked;
- semantic input bundle excludes raw GPX, raw rasters, and oversized web text;
- Pydantic AI judgement artifacts are candidate-only and hash/source backed.

Integration tests:

- run importer fixture, then map preparation fixture;
- verify map preparation uses the imported route bundle;
- verify layer projection contains OSM, terrain, risk, route notes, and POI
  layers when source refs exist;
- verify no-network mode makes zero live calls;
- verify explicit-fetch mode still records provider, query, timestamp, timeout,
  source license, and raw payload policy.

Suggested command:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest -q \
  tests/test_pretrip_historical_gpx_importer.py \
  tests/test_pretrip_route_corridor_map_preparation.py \
  tests/test_pretrip_overpass_ingest.py \
  tests/test_pretrip_gis_perception.py \
  tests/test_pretrip_layer_preparation.py
```

## Boundaries

Always:

- start from importer `route_evidence_bundle.json`;
- use bbox for acquisition and along-track corridor for semantic relevance;
- preserve source refs, source hashes, timestamps, confidence, stale risk, and
  review status;
- keep Pydantic AI output as intermediary `gis_perception_ai_judgements`;
- write candidate-only CP/Ln/POI/detour/terrain-risk artifacts.

Ask first:

- live web search;
- live Overpass download outside stored fixtures;
- cloud Pydantic AI model calls;
- raster OCR/vision over copyrighted map images;
- changing final MissionGraph compile behavior;
- increasing corridor widths enough to include broad off-route POI searches.

Never:

- run route-independent map or web searches when a route bundle exists;
- send raw GPX, raw DEM, raw tiles, or large scraped text directly to AI;
- treat AI output as `ObservedFact`, `DerivedMeasurement`, or runtime safety
  truth;
- call `/safety/*`;
- mutate Phase 1 runtime state;
- write Phase 2 Brain facts;
- compile final `MissionGraph`;
- silently render missing OSM/imagery/terrain as fake-looking map patterns.

## Success Criteria

- Map preparation refuses or warns when importer route evidence is missing.
- OSM/GIS/web/raster evidence is scoped by importer bbox and filtered by
  along-track distance.
- Along-route features and POIs are converted into source-backed semantic input
  bundles.
- Pydantic AI judgement artifacts can explain why a CP/Ln/POI/detour candidate
  was proposed.
- Repeated historical route notes are grouped without collapsing semantically
  different details.
- All outputs remain candidate-only and review-gated.
- Tests pass without live network.

## Open Questions

- What should the default `route_corridor_m` be for Taiwan mountain routes:
  250m, 500m, or route-class dependent?
- Should reference tracks have a narrower corridor than the golden route by
  default?
- Should web-case search be per route family first, then per named point, or
  only per named point to reduce noise?
- Should Pydantic AI receive one bundle for the whole route or one bundle per
  segment/CP window?
- How should seasonal route-note freshness differ for water, vegetation,
  collapse, and road-access notes?
