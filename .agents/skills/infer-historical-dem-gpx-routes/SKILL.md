---
name: infer-historical-dem-gpx-routes
description: Reconstruct and visualize candidate historical mountain-route topologies from archival descriptions, old maps, coordinate tables, DEM terrain, and public or Scout-owned GPX evidence. Use when asked to locate an old settlement, station, hunting path, lost trail, or route between two points; enumerate terrain-feasible corridors; compare historical text against tracks; draw ridge/valley route hypotheses; or package the result for Scout AI. Never use the output as proof that a trail exists, is currently passable, or is safe.
---

# Infer Historical DEM + GPX Routes

## Purpose

Build an evidence-traceable route hypothesis rather than drawing one confident
line. Separate historical claims, observed GPX, DEM-derived terrain candidates,
and inferred connectors. Represent alternatives as shared nodes and edges so
common sections are not copied into several unrelated routes.

Treat every result as `candidate_only: true` and
`runtime_safety_truth: false`.

## Read First

1. Read `AGENTS.md` and preserve the Scout candidate/runtime boundary.
2. Read `docs/specs/scout-historical-dem-gpx-route-inference.md`.
3. Read `references/source-search-playbook.md` before remote research.
4. Run `python tools/historical_dem_gpx_route_inference.py --help`.
5. Inspect the target map, DEM metadata, GPX metadata, and existing project
   artifacts before changing code or generating outputs.

## Workflow

### 1. Frame the question

Record:

- start and destination;
- map extent, grid labels, scale, north orientation, and contour interval;
- historical names, aliases, indigenous names, Japanese-era names, and OCR
  variants;
- textual sequence constraints such as “camp → saddle → traverse → stream →
  house group”;
- requested scope: historical reconstruction, terrain feasibility, current
  walkability, or field verification.

If the request asks only for terrain feasibility, do not silently claim current
path existence.

### 2. Build a source ledger

Collect P0, P1, and P2 separately:

- P0: official surveys, park or forestry reports, coordinate tables,
  orthophotos, national DEM or map baselines, current closure/status sources;
- P1: public GPX, club records, expedition reports, route articles, community
  maps, forum posts, and videos with traceable dates;
- P2: Scout-owned completed-trip GPX, photographs, voice notes, deviations,
  dwell points, and reviewed field observations.

Store source ID, tier, URL or local path, publication and retrieval dates,
author/organization, coordinate reference system, exact claim, and limitations.
Do not flatten source tiers into a single confidence score.

### 3. Audit coordinates before geometry

Identify the CRS/datum for every grid, point table, GPX, DEM, and image
georeference. In Taiwan, explicitly distinguish TWD67 / TM2 zone 121
(`EPSG:3828`) from TWD97 / TM2 zone 121 (`EPSG:3826`).

Use the bundled affine conversion only for coarse map/30 m DEM matching. Mark it
`survey_grade: false`. Use an official grid-shift transformation for precise
field or cadastral work.

Reject any overlay that aligns only after an undocumented manual pixel shift.

### 4. Parse historical prose as ordered constraints

Convert prose into an ordered clue table:

| Order | Clue type | Example | Geometry implication |
|---|---|---|---|
| 1 | observed route | follow old road | constrain to a known corridor |
| 2 | elevation | 1115 m camp | match DEM band plus GPX profile |
| 3 | landform | saddle before 1148 peak | detect saddle, not summit |
| 4 | movement | contour/hunting path | prefer moderate cross-slope traverse |
| 5 | hydrology | 150 m from water | constrain distance to drainage |
| 6 | sequence | cross tributary then house group | enforce order in graph |

Determine which named point each sentence describes. Do not attach all clues to
the final destination merely because it is the search target.

### 5. Align GPX evidence

Keep raw observations separate from interpretations:

- retain original timestamp, coordinate, elevation, source, and file hash;
- remove obvious teleport spikes only through deterministic criteria;
- resample only for comparison, retaining the raw track;
- calculate distance from anchors and candidate bands;
- cluster repeated tracks to find shared corridors and deviations;
- classify each segment as observed, extrapolated, or missing.

A public GPX proves that a device recorded a trace, not that access is legal,
the path remains open, or the terrain is safe today.

### 6. Extract the DEM route grammar

Use a bounded DEM window and record provider, resolution, vertical datum, tile,
acquisition date, and processing steps.

Derive at least:

- slope and local relief;
- contour-compatible horizontal bands;
- continuous main-ridge/spur-ridge hierarchy, divide points, and saddles;
- D8 drainage/flow accumulation for valley transfer candidates;
- drainage trunks, tributaries, headwaters, and confluences;
- cliffs, deeply incised streams, and implausible cross-slope jumps;
- elevation agreement with textual anchors.

Generate multiple separated horizontal corridors. Then generate longitudinal
transfer lines from valleys, spurs, or saddles. Avoid eight near-duplicate
least-cost paths that differ by only a few pixels.

Do not call every horizontal line a ridge. A contour-compatible traverse or
waist band is a route-search corridor. A ridge is a continuous convex terrain
skeleton with a parent/child relation. Keep these edge kinds distinct:

```text
main_ridge_candidate
spur_ridge_candidate
watershed_boundary
contour_traverse_band
drainage_trunk
tributary
```

Use multi-scale cross-section or curvature evidence rather than a single-cell
TPI label when constructing the continuous skeleton. Prune pixel noise, retain
branch topology, identify the component backbone, and expose:

```text
ridge_divide_node
saddle_node
headwater_node
drainage_confluence_node
```

An expert line drawn on an ungeoreferenced screenshot may train semantic
classification, but it is not coordinate geometry ground truth. Require at
least three control points, a stated CRS, and a residual below the declared
tolerance before using the line as a georeferenced candidate annotation.
Use `references/expert-terrain-annotation-example.json` as the minimum
machine-readable semantic-annotation example.

### 7. Build shared topology

Create:

- named anchor nodes;
- band/valley intersections as switch nodes;
- main-ridge/spur-ridge and drainage-trunk/tributary graph edges;
- ridge divide, saddle, headwater, and drainage-confluence nodes;
- historical or GPX-observed shared edges;
- inferred connectors with explicit evidence gaps;
- forced final sequences from the historical narrative.

Enumerate simple paths through the graph. Preserve shared edges in one place and
list route options as edge-ID sequences.

Join the route graph to the terrain graph without equating the two. A terrain
bifurcation is not automatically a trail fork. Project the observed GPX onto
the terrain hierarchy and emit an ordered event sequence such as:

```text
watershed_crossing
drainage_crossing
saddle_passage
ridge_divide_passage
headwater_crossing
drainage_branch
route_terrain_transition
```

Each event must include route distance, terrain relation, source references,
an observable terrain prompt, a wrong-way cue, and a recovery prompt. Phrase
these as review cues, not proof of safety or commands to continue.

Compile the package:

```bash
python tools/historical_dem_gpx_route_inference.py compile \
  --input .agents/skills/infer-historical-dem-gpx-routes/references/iroko-example-input.json \
  --output /tmp/iroko-route-hypothesis.json
```

### 8. Visualize uncertainty

Draw in this order:

1. original/georeferenced basemap;
2. continuous main-ridge/spur-ridge and drainage hierarchy;
3. all separated contour-compatible traverse bands (`H1…Hn`);
4. longitudinal transfer candidates (`V1…Vn`);
5. historical and GPX anchors;
6. probable envelope as a translucent polygon;
7. one or more emphasized recombined hypotheses;
8. route-terrain event markers;
9. labels, scale, north, datum, source date, and candidate-only warning.

Use visually distinct styles:

- thick green for main ridges and thin green for spur ridges;
- dark blue for drainage trunks and light blue for tributaries;
- thin warm lines for horizontal bands;
- dashed blue lines for valleys/drainage;
- dark outer stroke plus bright inner stroke for a probable hypothesis;
- translucent fill for the uncertainty envelope;
- point symbols for anchors, divide points, saddles, and headwaters;
- red rings for route-terrain events;
- explicit “terrain hypothesis, not confirmed path” label.

Never erase alternatives merely to make the map look decisive.

### 9. Verify

Require:

- every node and edge has `source_refs`;
- datum and conversion method are visible;
- topology connects start to destination;
- no unintended geometry jump exceeds the chosen sampling threshold;
- route alternatives share reusable edges;
- conflicts and missing evidence remain visible;
- output flags remain candidate-only;
- current status/access/safety claims are absent unless separately sourced.

Run:

```bash
python -m pytest tests/test_historical_dem_gpx_route_inference.py -q
python /Users/alexwang0315/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  .agents/skills/infer-historical-dem-gpx-routes
```

## Required Output

Return or save:

- a source/provenance ledger;
- coordinate/datum audit;
- ordered historical clue table;
- anchors with source references;
- DEM and GPX processing summary;
- shared node/edge topology;
- enumerated candidate route options;
- contradictions and evidence gaps;
- GeoJSON/JSON and annotated map when requested;
- field-verification questions;
- explicit Scout boundary flags.

Use wording such as “候選路徑假說”, “地形上可能”, and “仍待踏查”. Do not use
“就是這條”, “可安全通行”, or “已證實” without appropriate independent evidence.

## Scout AI Integration

Use `skills/scout/historical-dem-gpx-route-inference.yaml` as the read-only
Scout AI routing manifest. Scout AI may plan searches, summarize sources,
explain conflicts, and propose graph structure. Deterministic tools must own
coordinate transformation, DEM operations, graph enumeration, schema
validation, provenance checks, and artifact receipts.

Do not write results into Phase 1, `/safety/*`, live navigation truth, outbound
transports, or hardware controls.
