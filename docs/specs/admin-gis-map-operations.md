# Spec: Admin GIS Map Operations

Date: 2026-06-02

## Objective

Define the shared **GIS Map Operations**（GIS 地圖操作） contract for Scout's
three map-centered admin surfaces:

- `/admin` after-action review（行後檢視）;
- `/admin/debug` runtime debug console（runtime 除錯台）;
- `/admin/pretrip` pre-trip planning workspace（行前規劃工作區）.

The goal is to make pan/zoom, layer control, map focus, rectangle gestures,
timeline linkage, and candidate editing feel consistent across all three UIs,
while preserving each surface's phase boundary.

Success means an operator can move between the three pages and use the same map
mental model:

```text
timeline / evidence / workspace item
  -> double click or select
  -> map focuses the matching point, segment, bbox, or route context
  -> layer menu and zoom controls behave the same way
```

## Assumptions

1. Local alpha admin runs on `127.0.0.1:9099` in development. Scout hardware may
   expose another host/port such as `scout.local:9110`, but this spec is surface
   behavior, not port ownership.
2. Map layer definitions come from `admin_map_layers.py` and related admin
   projection artifacts.
3. OSM, imagery, DEM/DTM, risk, route, reference-track, weather, and runtime
   layers are evidence layers. They must expose availability and provenance
   rather than silently falling back to synthetic-looking placeholders.
4. `/admin/debug` is read-only. It may focus, filter, and export bug-report
   references, but it must not mutate runtime state.
5. `/admin` is read-only for completed missions. It may propose future planning
   candidates only through explicit reviewed export.
6. `/admin/pretrip` may mutate copied workspace candidate artifacts through
   explicit workspace edit tools. It must not write source fixtures, final
   `MissionGraph`, Phase 1 runtime, Phase 2 Brain state, `/safety/*`, or raw
   external payloads.

## Surface Scope

### `/admin`: After-Action Map Canvas

Purpose: inspect completed mission evidence.

Required GIS operations:

- render completed route, OSM/imagery context, corridors, hazards, checkpoints,
  Ln events, risk overlays, and optional post-analysis layers;
- evidence tree or timeline selection focuses the map target;
- map feature selection locates the corresponding evidence item when possible;
- double-clicking a timeline element focuses the map to that point, segment, or
  event context;
- rectangle tools are navigation-only unless a future reviewed-export mode is
  explicitly opened;
- no map action rewrites completed evidence.

### `/admin/debug`: Runtime Debug Evidence Map

Purpose: correlate runtime/debug events with geographic context.

Required GIS operations:

- render route, checkpoint, segment, runtime event, provider dropout, and
  projection evidence when coordinates exist;
- timeline event selection focuses the map target and updates the details panel;
- non-geographic events must explain why they cannot be placed on the map:
  missing coordinate, provider-only state, boundary-only event, unresolved
  artifact ref, or log-only event;
- map controls must not overlap timeline, detail tabs, or event payload panels;
- all interactions remain GET/read-only.

### `/admin/pretrip`: Planning Workspace Map

Purpose: build and review future mission candidates.

Required GIS operations:

- render golden/reference route, Overpass evidence, local imagery, OSM tiles,
  DTM/terrain, risk-score/ribbon/heat/delta, checkpoints, segments, MCP, route
  notes, POIs, retreat routes, weather overlays, and review state;
- timeline elements list owns CP and Segment Frame（CP/Segment 長形時間軸區域）;
- Review / Workspace lives in the right-side tab frame;
- double-clicking a CP, segment, route note, risk warning, or MCP candidate
  focuses the map;
- edit tools support:
  - add waypoint manually（手動新增航點）;
  - remove waypoint manually（手動移除航點）;
  - select trail generate waypoint（選取路徑產生航點）;
  - group select with rectangle（框選群組）;
- all edits write only copied workspace candidate artifacts and review logs.

## Shared Map Shell

All three surfaces should use the same conceptual map shell:

```text
MapShell
  LayerMenu
  NavigationControls
  InteractionModeControl
  MapViewport
  SelectionBridge
  DetailBridge
```

### Layer Menu（圖層選單）

Replace large checkbox-button rows with a compact menu.

Required behavior:

- collapsed control is an icon button or short `Layers` button;
- expanded menu groups layers by purpose:
  - Basemap（底圖）: `imagery`, `osm`, `terrain`;
  - Route（路線）: `route`, `reference-tracks`, `corridors`, `segments`;
  - Planning（規劃）: `checkpoints`, `mcp`, `route-notes`, `pois`, `retreat`;
  - Risk（風險）: `hazards`, `risk-score`, `risk-ribbon`, `risk-heatmap`,
    `risk-delta`;
  - Runtime（runtime）: `events`, provider/dropout/debug projection layers;
  - API（外部/動態）: `weather-api` and future operator-enabled overlays.
- each row shows label, Chinese annotation when helpful, availability state,
  source kind, and default-on/default-off state;
- unavailable layers remain visible but disabled with a reason;
- layer state can be encoded in URL or local view state for repeatable review;
- adding future layers must not make the map header taller by default.

Layout requirement:

- collapsed controls should fit inside one compact toolbar row;
- expanded layer menu may overlay the map, but it must be bounded, scrollable,
  and dismissible;
- the map render area should keep at least 70% of the local map module height;
- control/header area should not exceed 30% of the map module height when
  expanded.

Layer ordering follows `admin_map_layers.py`:

```text
imagery bottom
osm / terrain / evidence / planning / runtime
weather-api top
```

Risk layers must support both before/after comparison:

- `risk-score`: original route-aligned sample score;
- `risk-ribbon`: banded route risk layer;
- `risk-heatmap`: calibrated workspace-relative heat layer;
- `risk-delta`: comparison between baseline and calibrated heat.

### Tile And Raster Correctness

Imagery and OSM must never silently render as a misleading regular pattern or
"wave" placeholder.

Required behavior:

- local imagery uses `admin_local_raster_source_manifest` and
  `/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png`;
- OSM uses the local proxy first when offline/cache mode is active:
  `/admin/tiles/osm/{z}/{x}/{y}.png`;
- missing tiles render transparent or a clear unavailable tile state;
- missing source refs show an explicit layer warning in the menu and detail
  panel;
- no live network request is required for fixture-backed tests;
- source path, source id, cache policy, and external-network requirement are
  visible in debug details.

### Navigation Controls（平移縮放控制）

Required operations:

- pan by drag;
- zoom in/out by compact buttons;
- zoom to route bbox;
- zoom to selected feature;
- reset view to current project/case extent;
- keyboard support for `+`, `-`, arrow pan, `0` reset, and `Esc` cancel mode.

Zoom requirements:

- maximum zoom must be sufficient to isolate one CP in the viewport;
- point focus target should support approximately 5m ground-range inspection
  around the point when source resolution allows it;
- minimum zoom must fit the full project/case bbox with padding;
- each button click should change ground resolution by at least `2x`;
- focus-to-point, focus-to-segment, and focus-to-bbox must use the same
  animation and reduced-motion behavior across all three pages.

Suggested focus policy:

```text
point target      -> 5m to 20m viewport radius, based on source confidence
short segment     -> segment bbox + max(10m, 10% bbox padding)
long segment      -> segment bbox + 10% padding
route/project     -> full bbox + 10% padding
unknown geometry  -> do not move map; show reason in details
```

### Rectangle Gestures（框選/框放操作）

Rectangle behavior depends on interaction mode.

Navigation mode:

- drag left-top to right-bottom（左上往右下）zooms into the drawn rectangle;
- drag right-bottom to left-top（右下往左上）zooms out from the current view;
- tiny rectangles below a minimum pixel threshold are ignored;
- `Esc` cancels an in-progress rectangle.

Selection mode:

- rectangle selects visible map features intersecting the rectangle;
- `/admin/pretrip` can record the selection as a workspace edit candidate;
- `/admin` and `/admin/debug` can use rectangle selection only for local review
  filtering or bug-report export, not mutation;
- selected feature refs must be shown before any apply/export action.

Pretrip rectangle group selection output:

```json
{
  "operation_kind": "rectangle_group_select",
  "selection_mode": "visible_features_intersect_bbox",
  "bbox": [121.1, 23.9, 121.2, 24.0],
  "selected_refs": ["cp.yunhai", "segment.yunhai_to_tianchi"],
  "candidate_only": true,
  "runtime_safety_truth": false
}
```

### Timeline And Evidence Focus

Every timeline/evidence element with geographic context should resolve to a
shared map target.

Required behavior:

- single click selects the item and updates details;
- double click focuses the map to the item;
- focus is deterministic and based on source refs, not label text matching;
- a focused feature receives a visible highlight that survives layer redraw;
- if the relevant layer is hidden, the UI should either temporarily reveal the
  layer or show a prompt explaining which layer is hidden;
- the URL may include `selected_ref`, `map_bbox`, and layer state so a reviewer
  can share a reproducible admin view.

Shared target shape:

```json
{
  "target_ref": "cp.yunhai",
  "target_kind": "checkpoint",
  "geometry_kind": "Point",
  "coordinates": [121.23, 23.98],
  "bbox": [121.2299, 23.9799, 121.2301, 23.9801],
  "source_refs": ["candidates/checkpoints.json#cp.yunhai"],
  "confidence": "high"
}
```

## Pretrip Workspace Edit Tools

Workspace edit tools are candidate-only planning controls.

Required operations:

### Add Waypoint Manually（手動新增航點）

- triggered by map click or typed coordinate;
- requires label, waypoint type, and source note;
- writes a checkpoint candidate to copied workspace artifacts;
- appends reviewer/timestamp/source summary to `reviews/workspace_edit_log.json`.

### Remove Waypoint Manually（手動移除航點）

- removes or marks a copied workspace candidate as rejected;
- cannot remove immutable start/finish checkpoints;
- must show affected segments before apply.

### Select Trail Generate Waypoint（選取路徑產生航點）

- user selects a trail/corridor/reference-track segment;
- Scout proposes a waypoint candidate at endpoint, bend, junction, high-risk
  transition, or user-clicked point on the trail;
- output remains `needs_human_review` until accepted.

### Group Select With Rectangle（框選群組）

- rectangle selection creates a reviewed selection set;
- can bulk tag, review, compare, or create draft operations over CP/segment/POI
  candidates;
- no bulk destructive apply without a preview and explicit confirmation.

All workspace edit operations use:

```text
POST /admin/pretrip/projects/{project_id}/workspace-edits
```

No workspace edit operation may call `/safety/*`.

## Data Contracts

### Map View State

```json
{
  "surface": "/admin/pretrip",
  "project_id": "chilai_nanhua_day1",
  "selected_ref": "cp.yunhai",
  "map_bbox": [121.12, 23.91, 121.31, 24.04],
  "zoom_resolution_m_per_px": 2.5,
  "enabled_layers": ["imagery", "osm", "route", "checkpoints", "risk-heatmap"],
  "interaction_mode": "navigation",
  "last_focus_reason": "timeline_double_click"
}
```

### Map Interaction Event

```json
{
  "event_kind": "map_focus",
  "surface": "/admin",
  "trigger": "timeline_double_click",
  "target_ref": "event.ln.001",
  "target_kind": "runtime_event",
  "layer_id": "events",
  "bbox": [121.12, 23.91, 121.13, 23.92],
  "handled": true,
  "reason": null
}
```

### Layer Availability State

```json
{
  "layer_id": "imagery",
  "available": false,
  "enabled": false,
  "reason": "local_raster_manifest_missing",
  "source_path": "external/local/chilai_nanhua_day1.local_raster_source_manifest.json",
  "external_network_required": false,
  "fallback_render": "transparent"
}
```

## Commands

Focused backend tests:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest -q \
  tests/test_admin_map_layers.py \
  tests/test_admin_after_action.py \
  tests/test_debug_page.py \
  tests/test_pretrip_admin_page.py \
  tests/test_pretrip_workspace_project.py
```

Pretrip layer and risk checks:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest -q \
  tests/test_pretrip_layer_preparation.py \
  tests/test_pretrip_risk_heatmap.py \
  tests/test_admin_basemap_tiles.py \
  tests/test_admin_local_raster_tiles.py \
  tests/test_admin_tile_proxy.py
```

Local admin server:

```bash
SCOUT_DATA_ROOT=/tmp/scout-fusion-data \
SCOUT_PRETRIP_WORKSPACE_ROOT=/tmp/scout-fusion-pretrip-workspaces \
SCOUT_DEBUG_API_ENABLED=1 \
SCOUT_RUNTIME_PROFILE=local-alpha-workspace \
/Users/alexwang0315/scout-fusion/venv/bin/python -m uvicorn \
  phase4_admin_runtime:create_phase4_admin_runtime_app \
  --factory --host 127.0.0.1 --port 9099
```

Browser visual smoke:

```bash
node tools/admin_ui_visual_smoke.js \
  --base-url http://127.0.0.1:9099 \
  --surfaces /admin,/admin/debug,/admin/pretrip
```

## Project Structure

Current relevant files:

```text
admin_map_layers.py
  Shared layer declarations, z-order, source refs, tile/raster contracts.

docs/admin/phase1-after-action.html
  /admin after-action map UI.

docs/admin/phase-3-5-runtime-debug.html
  /admin/debug runtime debug UI.

docs/admin/phase4-pretrip-planning.html
  /admin/pretrip planning UI.

admin_after_action.py
debug_api.py
pretrip_admin_view.py
pretrip_workspace_edit.py
phase4_admin_runtime.py
  Surface data and mutation boundaries.
```

Suggested future files:

```text
admin_gis_map_state.py
  Shared Python view-state and focus-target serializers.

docs/admin/admin-gis-map.js
  Shared browser map shell, layer menu, zoom/focus, and rectangle gesture code.

tests/test_admin_gis_map_state.py
  Backend contract tests for focus targets, layer state, and view-state JSON.

tests/test_admin_gis_map_browser.py
  Browser smoke contract for no overlap, layer menu, focus, and rectangle gestures.
```

## Implementation Plan

### Slice 1: Spec And Shared Contract

- Add this spec.
- Add view-state and focus-target schema tests.
- Acceptance:
  - all three surfaces have documented operation parity;
  - no runtime mutation or workspace-edit ambiguity remains.

### Slice 2: Compact Layer Menu

- Replace large checkbox-button controls with a menu on `/admin/pretrip`.
- Reuse on `/admin` and `/admin/debug`.
- Acceptance:
  - controls do not overlap the map or detail panes;
  - future layers remain scrollable inside the menu;
  - unavailable imagery/OSM/terrain layers show explicit reasons.

### Slice 3: Shared Pan/Zoom/Focus

- Implement shared map focus and zoom step rules.
- Add timeline double-click focus.
- Acceptance:
  - point focus can inspect a single CP around a 5m target range;
  - click zoom step changes ground resolution by at least `2x`;
  - selected item highlight is consistent across surfaces.

### Slice 4: Rectangle Navigation

- Implement zoom-in and zoom-out rectangle gestures.
- Acceptance:
  - left-top to right-bottom zooms in;
  - right-bottom to left-top zooms out;
  - `Esc` cancels;
  - reduced-motion users do not get forced animations.

### Slice 5: Pretrip Rectangle Selection And Edit Tools

- Enable add/remove waypoint, trail-to-waypoint, and rectangle group selection.
- Acceptance:
  - edits write only copied workspace candidates;
  - start/finish checkpoints cannot be removed;
  - every edit is logged with reviewer, timestamp, target refs, and boundary.

### Slice 6: Cross-Surface Alignment

- Align `/admin`, `/admin/debug`, and `/admin/pretrip` map shell behavior.
- Acceptance:
  - same layer menu structure;
  - same zoom/focus semantics;
  - same layer availability messaging;
  - browser smoke proves no control overlap at desktop and mobile widths.

## Testing Strategy

Use fixture-backed tests only by default.

Unit tests:

- layer order and z-index from `admin_map_layers.py`;
- layer availability fallback for missing imagery/OSM/terrain;
- view-state serialization and URL state parsing;
- zoom math and minimum/maximum focus bounds;
- rectangle direction handling;
- pretrip workspace edit log shape.

API tests:

- `/admin` view model emits focusable targets for evidence items;
- `/admin/debug` emits map targets or explicit non-geographic reasons;
- `/admin/pretrip` emits project layer state and accepts only candidate edits.

Browser tests:

- layer menu opens/closes without resizing the map incoherently;
- controls do not overlap timeline/details;
- double-click timeline element focuses map;
- rectangle zoom in/out works;
- pretrip group selection previews refs before apply;
- risk heat/ribbon/delta layers can be toggled independently.

No test may depend on live Overpass, live OSM tile downloads, live weather, or
external network availability.

## Boundaries

Always:

- keep `/admin/debug` GET/read-only;
- keep `/admin` completed mission evidence immutable;
- keep `/admin/pretrip` edits workspace-candidate-only;
- show layer provenance, availability, cache policy, and external-network
  requirement;
- make hidden/unavailable layers explicit instead of rendering misleading
  placeholders;
- keep map controls compact and non-overlapping.

Ask first:

- adding a new map rendering library;
- changing the final `MissionGraph` compiler contract;
- making any layer provider live by default;
- adding public sharing or account-level persistence for map state;
- bulk destructive workspace edit operations.

Never:

- call `/safety/*` from GIS map controls;
- let `/admin/debug` mutate runtime or Phase 2 Brain state;
- let `/admin` rewrite completed mission evidence;
- write source fixtures from pretrip edit tools;
- hide uncertainty or staleness for OSM, imagery, DEM/DTM, weather, or risk
  layers;
- present candidate risk heatmaps as runtime safety truth.

## Success Criteria

- `/admin`, `/admin/debug`, and `/admin/pretrip` expose a consistent layer menu,
  pan/zoom, focus, and selection model.
- Map controls stay compact and do not cover timeline/detail content.
- Timeline double-click focuses the matching map target.
- Zoom can isolate a single CP and also return to the full project/case route.
- Rectangle gestures support zoom-in, zoom-out, and pretrip group selection.
- Imagery/OSM/terrain/risk layer failures are visible as evidence states, not
  misleading placeholder graphics.
- Pretrip edit tools produce candidate-only workspace artifacts and logs.
- Fixture-backed backend and browser smoke tests verify the three surfaces.

## Open Questions

- Should the shared map shell stay in plain JavaScript, or should a later alpha
  slice introduce a small map component module?
- Should layer state persist in URL only, local storage only, or both?
- Should rectangle selection include hidden layers if the user explicitly asks,
  or visible layers only by default?
- Should right-to-left zoom-out rectangle use current viewport center or
  rectangle center as the zoom-out anchor?
- Should `/admin/debug` offer a bug-report export that includes current map view
  state and selected event refs?
