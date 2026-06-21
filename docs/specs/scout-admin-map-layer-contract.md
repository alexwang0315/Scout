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

## Regression Notes From Operator Reruns

The following mistakes are easy to repeat and are considered contract
regressions:

- Treating a preparation manifest with 23 ready layers as incomplete because
  the UI contract contains 32 layers. The missing nine are runtime-only or
  post-process/UI contract layers, not preparation inputs.
- Treating `rudy` or `rudy-twmap` as failed just because they do not appear in
  `pretrip_layer_preparation.py --layers`. They are WMTS/runtime layers, while
  Rudy+TW may still be used as the OCR source during preparation.
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
| `imagery` | WMTS imagery basemap, bottom-most visual layer. | `admin_map_layers.py`, `admin_imagery_sources.py`, three `docs/admin/*.html` pages. | z-index 0; below OSM and all evidence. | Can use runtime WMTS or seeded cache; failed tiles must not blank vector evidence. | Contract verifier plus browser layer toggle/group check. |
| `rudy` | Optional Rudy hiking basemap overlay. | `admin_map_layers.py`, `admin_imagery_sources.py`, three admin pages. | Raster overlay rank 4; below OSM/evidence. | Off by default; network/cache failure isolated from evidence layers. | Source id, control, rank, group, browser toggle. |
| `rudy-twmap` | Optional Rudy+TW basemap and preferred OCR source for trail mileage labels. | `admin_map_layers.py`, `admin_imagery_sources.py`, `pretrip_raster_label_ocr.py`. | Raster overlay rank 4; OCR output must pass through raster label adapter. | Can be visually off while still used as preparation/OCR source. | Source id, OCR plan/source checks, control/rank/group/toggle. |
| `relief` | Optional color relief raster reference. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; not Scout terrain visualization. | Off by default; no workspace artifact required. | Control/rank/source/group/toggle. |
| `geology` | Optional geology context overlay. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; candidate context only. | Off by default; no safety truth. | Control/rank/source/group/toggle. |
| `topo-5k` | Optional 1/5000 topographic reference. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; below Scout evidence. | Off by default; cache/network failure cannot hide route evidence. | Control/rank/source/group/toggle. |
| `forest` | Optional forest compartment overlay. | `admin_map_layers.py`, `admin_imagery_sources.py`, admin pages. | Raster overlay rank 4; below Scout evidence. | Off by default; candidate context only. | Control/rank/source/group/toggle. |
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
| `pois` | Named POI/context candidates. | `pretrip_route_context_collection.py`, `admin_map_layers.py`, admin pages. | z-index 64; above checkpoints, below hazards. | Avoid raw variable-name labels; unavailable if no POI source. | Label/source/group/rank/toggle. |
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
