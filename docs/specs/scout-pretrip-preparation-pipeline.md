# Scout Pretrip Preparation Pipeline

## Purpose

This document is the fixed operator contract for Scout pretrip preparation:
historical/public GPX import, route-corridor map preparation, Rudy/Rudy+TW OCR,
route context and mileage evidence, Boss/pressure synthesis, map-layer testing,
and Scout agent skills/tool entry points.

The goal is that a prepared workspace opens in `/admin/pretrip`,
`/admin/debug`, and `/admin` with route, CP/MCP/Boss, mileage, terrain, risk,
OCR, context, and raster/vector map layers already materialized. The operator
should not need to discover missing steps by manually inspecting the UI.

All outputs in this pipeline are pretrip candidate/evidence artifacts. They do
not mutate Phase 1 runtime safety truth, do not call `/safety/*`, do not write
Phase 2 Brain observed facts, and do not compile a final runtime `MissionGraph`.

## Fixed Order

The preparation order is non-negotiable:

1. Material layout check.
2. GPX importer.
3. Map preparation with explicit connected fetch for in-house pretrip work.
4. OCR over prepared Rudy/Rudy+TW tiles.
5. Raster label adapter normalization.
6. Route context collection and mileage tag alignment.
7. Risk, terrain, MCP, and Boss synthesis refresh.
8. 30-layer contract verification.
9. Browser smoke across `/admin/pretrip`, `/admin/debug`, and `/admin`.
10. Optional Scout deployment or service restart.

If one step is skipped, the run is partial and must be reported as partial.

## Material Layout

Pretrip source material must be collected under a route-specific material root
before import and map preparation:

```text
/data/scout/materials/pretrip/<project_id>/
  material_manifest.json
  sources/
    gpx/
      golden/
      reference/
    dtm/
    dem/
    imagery/
    ocr/
    route_context/
    route_pressure/
  cache_policy/
  operator_notes/
```

The workspace root is separate from the material root:

```text
/data/scout/admin/pretrip-workspaces/<project_id>/
```

The material root stores source inputs and provenance. The workspace root stores
normalized Scout artifacts, candidates, projections, and admin display outputs.
Do not scatter route material across arbitrary desktop paths once a workspace is
being prepared for Scout.

## GPX Importer

The importer is responsible for converting the selected golden GPX and
historical/reference GPX corpus into a deterministic Scout pretrip workspace.
It runs before map preparation.

Required behavior:

- The golden GPX is a pretrip planning reference, not the user's completed
  track.
- Golden and reference GPX both pass through speed filtering before downstream
  route summaries, checkpoints, segments, reference display geometry, and admin
  projections use them.
- GPX `trk`/`trkseg` boundaries are preserved through `coordinate_segments` for
  UI rendering.
- Importer outputs must preserve source path, SHA-256, source role, filter
  thresholds, removed counts, route summary, checkpoint count, segment count,
  debug projection, and admin projection.
- If Overpass-aligned route geometry exists later, golden GPX becomes one
  reference source; it is not navigation truth.

Canonical command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_import \
  --project-id <project_id> \
  --golden-route-gpx <material_root>/sources/gpx/golden/<route>.gpx \
  --reference-dir <material_root>/sources/gpx/reference \
  --workspace-root /data/scout/admin/pretrip-workspaces \
  --profile pi-offline \
  --material-root <material_root> \
  --checkpoint-spacing-m 500 \
  --max-reference-display-points 2500 \
  --max-reasonable-gpx-speed-kmh 120 \
  --max-previous-gpx-speed-ratio 8.0 \
  --import-stage pretrip \
  --overwrite
```

Expected core outputs:

```text
project.json
candidates/checkpoints.json
candidates/segments.json
candidates/map_candidates.json
normalized/routes/route_summary.json
normalized/routes/route_evidence_bundle.json
outputs/import_manifest.json
outputs/gpx_speed_filter_report.json
outputs/reference_tracks.json
outputs/reference_track_display_geometry.json
outputs/segment_display_geometry.json
outputs/admin_projection.json
outputs/debug_projection_events.jsonl
```

## Map Preparation

Map preparation consumes importer output and prepares route-corridor evidence.
For in-house pretrip work, assume network is available and use
`explicit-fetch`. Outdoor replay or CI may use `no-network`.

Current preparation-supported layer ids:

```text
imagery, osm, overpass, terrain, risk-score, risk-ribbon, risk-heatmap,
risk-delta, weather, reference-tracks, route, segments, checkpoints, mcp, pois,
hazards, corridors, retreat, route-notes
```

The broader UI contract still has 30 layers; those are verified separately by
the Scout layer contract gate.

Canonical connected command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_layer_preparation \
  --project-id <project_id> \
  --workspace-root /data/scout/admin/pretrip-workspaces \
  --layers imagery,osm,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,weather,reference-tracks,route,segments,checkpoints,mcp,pois,hazards,corridors,retreat,route-notes \
  --profile pi-online-explicit \
  --network-mode explicit-fetch \
  --allow-network-fetch \
  --route-evidence-bundle normalized/routes/route_evidence_bundle.json \
  --route-corridor-m 500 \
  --reference-track-corridor-m 300 \
  --ai-mode fixture-or-precomputed \
  --ai-output-policy hash-and-summary \
  --seed-imagery-cache \
  --imagery-provider-allows-offline-prefetch \
  --imagery-min-zoom 5 \
  --imagery-max-zoom 16 \
  --imagery-seed-max-tiles <bounded_count>
```

Map preparation must:

- fetch Overpass only through explicit network mode;
- seed Rudy/Rudy+TW imagery only when the provider allows offline prefetch;
- use a 30-day tile TTL instead of clearing valid cached tiles every run;
- prepare terrain hillshade, elevation tint, slope shading, and contours from
  local DEM/DTM when sources exist;
- keep terrain visualization separate from risk heat layers;
- refresh risk score, baseline risk ribbon, calibrated risk heatmap, and risk
  delta when requested;
- keep source refs and candidate-only boundary metadata on every artifact;
- write read-only admin/debug projections.

Expected map outputs:

```text
outputs/layers/layer_preparation_manifest.json
outputs/layers/layer_preparation_job.json
outputs/layers/layer_preparation_summary.json
outputs/layers/map_preparation_summary.json
outputs/layers/layer_adapter_manifest.json
outputs/layers/layer_validation_report.json
outputs/layers/plans/overpass_query.ql
outputs/layers/plans/raster_label_plan.json
outputs/layers/normalized/overpass_vector_evidence.geojson
outputs/layers/normalized/terrain_visualization.geojson
outputs/layers/normalized/terrain_hillshade.png
outputs/layers/normalized/terrain_elevation_tint.png
outputs/layers/normalized/terrain_slope_shading.png
outputs/layers/normalized/terrain_contours.png
outputs/layers/projections/pretrip_map_layers.json
outputs/layers/projections/admin_debug_events.jsonl
```

## OCR And Raster Label Normalization

OCR is part of map preparation for normal operator runs. The standalone OCR and
adapter CLIs remain available for debugging, fixture tests, and replacement of
OCR output.

OCR source policy:

- Preferred sources are Rudy and Rudy+TW tiles from the prepared tile cache.
- OCR output is explicit JSON only; it is not route context directly.
- `trail_mileage_k_anchor` and `road_mileage_stone` must remain distinct.
- Incomplete georeference becomes review-required evidence, not a crash.
- Missing Tesseract/pytesseract writes a blocked dependency artifact, not fake
  labels.

Standalone OCR command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_raster_label_ocr \
  --project-root /data/scout/admin/pretrip-workspaces/<project_id> \
  --raster-label-plan outputs/layers/plans/raster_label_plan.json \
  --output-ref outputs/layers/raster_label_ocr_output.json \
  --engine tesseract \
  --tesseract-lang chi_tra+eng \
  --source-id rudy-twmap \
  --json
```

Standalone adapter command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_raster_label_adapter \
  --project-root /data/scout/admin/pretrip-workspaces/<project_id> \
  --source outputs/layers/raster_label_ocr_output.json \
  --json
```

Expected OCR outputs:

```text
outputs/layers/raster_label_ocr_output.json
outputs/layers/cache/raster_label_ocr_tiles/
outputs/layers/normalized/raster_label_evidence.geojson
outputs/layers/raster_label_adapter_manifest.json
```

The adapter may write:

- `trail_mileage_k_anchor` candidates into route mileage anchor input;
- `road_mileage_stone` records into route context points only;
- `cellular_communication_point`, `contour_elevation_label`,
  `trail_name_label`, `named_place_label`, and `hazard_annotation_label` as
  candidate evidence.

It must not write Phase 1 runtime truth, `/safety/*`, or Phase 2 Brain facts.

## Route Context, Mileage, MCP, And Boss Refresh

After map preparation and OCR, route context collection must absorb the new
raster label evidence, Overpass vectors, historical GPX route notes, public
context packs, and Scout-owned P2 evidence when present.

Canonical route context command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_route_context_collection \
  --project-root /data/scout/admin/pretrip-workspaces/<project_id> \
  --route-keyword "<route keyword>" \
  --json
```

Expected refreshed outputs:

```text
candidates/route_context_points.json
candidates/route_mileage_k_anchors.json
normalized/context/route_context/source_manifest.json
normalized/context/route_context/route_context_pack.json
outputs/briefings/route_context_briefing.html
```

Mileage tag alignment must then bind route events, CP, MCP, segments, pressure
samples, and Boss candidates to the best available trail-K anchor. If no
reliable OCR/source-backed K anchor exists, items stay `needs_review`; they
must not be silently presented as calibrated mileage.

Boss synthesis belongs after the route pressure profile and route context are
available. A Boss point should come from pressure-profile peaks plus MCP/named
point/review evidence. Rest areas, huts, camps, or flat regroup points must not
be classified as Boss solely because people stopped there. Sustained slow
movement must cover a meaningful span; default minimum pressure span is 500 m.

## Scout Skills And Agent Tool Entry Points

The deterministic pipeline above is the normal preparation path. Scout skills
and agent tools should wrap or explain that path; they should not create hidden
side pipelines.

Relevant local skills:

- `.agents/skills/scout-route-context-briefing/SKILL.md`
- `.agents/skills/scout-route-pressure-intelligence/SKILL.md`

Relevant Scout agent tool manifests:

- `scout.pretrip.import_gpx`
- `scout.pretrip.prepare_layers`
- `scout.pretrip.raster_label_ocr`
- `scout.pretrip.raster_label_adapter`
- `scout.pretrip.route_context_collect`
- `scout.pretrip.boss_points_synthesize`
- `scout.pretrip.route_briefing_compose`
- `scout.pretrip.pace_fit_collect`
- `scout.pretrip.navigation_terrain_collect`

Skill/tool requirements:

- Use workspace paths and source refs from `project.json`.
- Preserve candidate-only provenance and boundary metadata.
- Require explicit operator intent for network fetches.
- Keep OCR output and adapter normalization as separate artifacts even when map
  preparation orchestrates both.
- Report missing dependencies or source gaps instead of fabricating map,
  mileage, route context, or Boss evidence.

## Layer Verification

The complete UI/admin contract has 30 layers, documented in
`docs/specs/scout-admin-map-layer-contract.md` and enforced by
`scout_layer_contract.py`.

Run the static repo gate:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py --repo-root .
```

Run the workspace gate after import and map preparation:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
  --repo-root . \
  --project-root /data/scout/admin/pretrip-workspaces/<project_id> \
  --require-workspace
```

Run the broader workspace spec alignment check:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_pretrip_workspace_spec_alignment.py \
  --workspace-root /data/scout/admin/pretrip-workspaces \
  --project-id <project_id> \
  --admin-base-url http://127.0.0.1:9099 \
  --allow-network-calls
```

When browser tooling is available, run:

```bash
node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
```

The browser check must open all three admin surfaces and verify layer controls,
layer groups, basic map rendering, and toggles for every expected layer on that
surface.

## One-Command Scout Rebuild

`tools/rebuild_pretrip_workspace_on_scout.sh` is the current one-command entry
point for Scout hardware rebuilds. It already runs:

- GPX importer;
- durable admin evidence ref restore;
- layer preparation;
- route context collection;
- workspace spec alignment verifier.

Before this wrapper is treated as alpha-complete, it must also make these steps
explicit and visible in logs:

- imagery cache seeding flags for Rudy/Rudy+TW when network/cache policy
  permits;
- OCR stage result path and dependency status;
- raster label adapter result path;
- mileage alignment result path/count;
- Boss synthesis result path/count;
- `verify_scout_layer_contract.py` repo and workspace gates;
- browser visual smoke result when a browser runtime is available.

Required wrapper environment variables:

```text
SCOUT_PROJECT_ID
SCOUT_PRETRIP_WORKSPACE_ROOT
SCOUT_PRETRIP_MATERIAL_ROOT
SCOUT_SOURCE_GPX_ROOT
SCOUT_GOLDEN_ROUTE_GPX
SCOUT_PRETRIP_LAYERS
SCOUT_PRETRIP_NETWORK_MODE
SCOUT_PRETRIP_ALLOW_NETWORK_FETCH
SCOUT_ROUTE_CORRIDOR_M
SCOUT_REFERENCE_TRACK_CORRIDOR_M
```

Optional future wrapper variables:

```text
SCOUT_SEED_IMAGERY_CACHE
SCOUT_IMAGERY_PROVIDER_ALLOWS_OFFLINE_PREFETCH
SCOUT_IMAGERY_MIN_ZOOM
SCOUT_IMAGERY_MAX_ZOOM
SCOUT_IMAGERY_SEED_MAX_TILES
SCOUT_RUN_RASTER_LABEL_OCR
SCOUT_RUN_LAYER_CONTRACT_GATE
SCOUT_RUN_BROWSER_LAYER_SMOKE
```

## Completion Report Template

Every full preparation run must report:

```text
Project:
Workspace:
Material root:
Importer: PASS/FAIL
Map preparation: PASS/FAIL
Overpass: PASS/FAIL/NOT APPLICABLE
Terrain visualization: PASS/FAIL/NOT APPLICABLE
Risk baseline/calibrated/delta: PASS/FAIL/NOT APPLICABLE
Rudy/Rudy+TW tile seed: PASS/FAIL/NOT APPLICABLE
OCR: PASS/FAIL/NOT APPLICABLE
Raster label adapter: PASS/FAIL/NOT APPLICABLE
Route context: PASS/FAIL/NOT APPLICABLE
Mileage tags: PASS/FAIL/NOT APPLICABLE
MCP: PASS/FAIL/NOT APPLICABLE
Boss points: PASS/FAIL/NOT APPLICABLE
30-layer repo gate: PASS/FAIL
30-layer workspace gate: PASS/FAIL
Browser smoke: PASS/FAIL/NOT APPLICABLE
Scout deployment: PASS/FAIL/NOT APPLICABLE
Candidate-only boundary: PASS/FAIL
Runtime safety mutation: PASS/FAIL
```

Do not claim the workspace is complete if any required preparation artifact or
layer gate is unchecked.
