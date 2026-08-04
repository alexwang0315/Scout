# Scout Historical DEM + GPX Route Inference

Status: experimental capability specification
Boundary: candidate research artifact only
Codex skill: `.agents/skills/infer-historical-dem-gpx-routes/`
Scout AI manifest: `skills/scout/historical-dem-gpx-route-inference.yaml`
Deterministic compiler: `tools/historical_dem_gpx_route_inference.py`

## 1. Purpose

This capability reconstructs plausible mountain-route topology from incomplete,
heterogeneous evidence:

- historical prose and place names;
- archival maps and coordinate tables;
- georeferenced contour maps;
- DEM-derived ridges, saddles, slopes, and drainages;
- public GPX and route records;
- reviewed Scout-owned field evidence.

Its output is not “the route.” It is a graph of sourced observations,
terrain-feasible alternatives, shared route segments, conflicts, and missing
evidence that a researcher or field team can review.

The core product idea is:

> Make the gray zone between “a historical description exists” and “a verified
> modern path exists” explicit, inspectable, and progressively verifiable.

## 2. Non-goals and safety boundary

This capability does not:

- prove that a path exists on the ground;
- decide that a route is currently passable;
- authorize access, solo travel, or a go/no-go decision;
- infer vegetation density, rock stability, stream discharge, landslide
  activity, or legal access from DEM alone;
- write to Scout Phase 1, `/safety/*`, live navigation truth, hardware, or
  outbound transports;
- create a permanent “qualified for solo hiking” credential.

Every artifact must contain:

```json
{
  "candidate_only": true,
  "runtime_safety_truth": false,
  "safe_or_walkable": "not_determined"
}
```

## 3. Architecture

```text
historical sources ─┐
old maps / OCR ─────┤
official coordinates├──> evidence ledger + datum audit
public GPX ─────────┤                    │
Scout P2 evidence ──┘                    v
                                  ordered clue graph
DEM raster ──> slope/ridge/saddle/valley candidates
                                              │
                                              v
                                  shared node/edge topology
                                              │
                    deterministic validation + enumeration
                                              │
                         JSON / GeoJSON / annotated map
                                              │
                          human and field-review questions
```

The model may:

- search, select, and summarize sources;
- parse narrative sequence;
- propose aliases and route hypotheses;
- explain contradictions;
- draft field-verification questions.

Deterministic code owns:

- coordinate conversion and geometry;
- DEM calculations;
- GPX parsing and distance metrics;
- graph construction and path enumeration;
- source-reference validation;
- artifact flags, receipts, and hashes.

## 4. Evidence model

### 4.1 Source tiers

P0 — official and baseline:

- park, forestry, survey, cadastral, academic, and government reports;
- official coordinate tables, aerial imagery, DEM, maps, route status, closure,
  permit, and land-access sources.

P1 — public route/community:

- GPX repositories, climbing club records, expedition reports, professional
  route pages, hiking articles, forums, and videos;
- useful for names, sequences, repeated corridors, and completed-trip timing.

P2 — Scout-owned:

- completed-trip GPX, deviations, photographs, voice notes, barometric
  elevations, dwell records, and operator-reviewed field observations;
- private and exact-location evidence must follow Scout consent and privacy
  controls.

P0 does not automatically mean “correct about every historical interpretation.”
P1 does not automatically mean “unreliable.” Tier expresses source function,
not a universal numeric confidence.

### 4.2 Claim ledger

Store one claim per record:

```text
claim_id
claim_text
source_id
source_tier
source_location (page/table/track segment)
publication_date
retrieved_at
coordinate_reference_system
supports_or_refutes
limitations
```

If two sources disagree, preserve both and create a contradiction record. Do
not average incompatible coordinates or collapse competing name mappings.

## 5. Search method

Use the detailed query and acquisition procedure in:

` .agents/skills/infer-historical-dem-gpx-routes/references/source-search-playbook.md`

The minimum search sequence is:

1. build an alias matrix;
2. find official or archival sources;
3. find original GPX/route records;
4. search coordinate pairs and datum terms;
5. check current status separately;
6. preserve original files, URLs, hashes, dates, pages, and claims;
7. stop when remaining uncertainty can be stated as a specific evidence gap.

Useful search tokens include:

```text
GPX, 航跡, 紀錄, 踏查, 駐在所, 舊社, 獵路, 古道, 鞍部,
TWD67, TWD97, 座標, 調查, 復舊, 崩塌, 封閉
```

## 6. Map and coordinate audit

### 6.1 Read the map as an orienteer

Before route search, identify:

- map extent and grid coordinates;
- contour interval and index contours;
- north direction;
- scale or pixel-to-grid relationship;
- cliffs, re-entrants, spurs, saddles, terraces, benches, river crossings,
  gullies, and broad versus sharp ridges;
- human traces such as roads, paths, structures, clearings, survey labels, and
  old administrative boundaries.

Trace landform continuity, not individual contour lines. A usable traverse is
often a band of locally moderate cross-slope movement connected by a limited
number of saddles, gullies, or spurs.

### 6.2 Datum mismatch

For Taiwan TM2 zone 121:

- TWD67: `EPSG:3828`;
- TWD97: `EPSG:3826`;
- GPX: usually WGS84 `EPSG:4326`.

The common affine approximation used by the bundled compiler is:

```text
A = 0.00001549
B = 0.000006521

X97 = X67 + 807.8 + A*X67 + B*Y67
Y97 = Y67 - 248.6 + A*Y67 + B*X67
```

It is sufficient for approximate matching to a 30 m DEM or a small historical
map. It is not survey-grade. Preserve both original and converted coordinates,
label the method, and require an official grid-shift method for precise use.

### 6.3 Image georeferencing

For a rectangular grid image:

1. identify at least two, preferably four, known grid intersections;
2. fit pixel-to-map affine or projective transformation;
3. inspect residual error at unused check points;
4. reject a fit when residuals are comparable to corridor separation;
5. record crop, rotation, resampling, and original image hash.

Do not rely on one manually placed destination dot to georeference the image.

## 7. Historical narrative parsing

Convert a paragraph into ordered events and constraints.

Example:

```text
follow Qing-era road
→ 1115 m camp
→ contour along hunting path
→ saddle before 1148 peak
→ continue on hunting path
→ point beside route
→ water about 150 m away
→ humid fern/bamboo environment
→ cross tributary
→ second point
→ station below house group
```

For each clue record:

- subject point;
- sequence index;
- elevation range and tolerance;
- landform type;
- movement type;
- distance/direction relation;
- hydrologic relation;
- vegetation or surface clue;
- source and quotation location;
- whether it constrains a node, an edge, or an area.

The subject resolution matters. In the Iroko case, the “1115 m camp → 1148
saddle → hunting path → water 150 m” wording describes IR-1 rather than directly
describing the final station. The later IR-1 → tributary → IR-2 → station
sequence must be modeled explicitly.

## 8. GPX processing

### 8.1 Preserve raw observations

For each GPX:

- retain the original file and SHA-256;
- record source page, direct download URL, uploader, trip date, and retrieval
  date;
- count tracks, segments, points, timestamps, and elevation samples;
- record bounds;
- keep raw geometry immutable.

### 8.2 Deterministic cleanup

Create a derived track only when needed:

- split on large time gaps;
- flag rather than silently delete impossible speed jumps;
- remove duplicate consecutive points;
- optionally smooth elevation while keeping the raw profile;
- resample to a documented spacing for cross-track comparison.

### 8.3 Compare tracks

Calculate:

- nearest distance from each historical/DEM anchor to each track;
- overlap length within a corridor tolerance;
- repeated track density;
- direction and elevation-profile consistency;
- divergence/merge points;
- independence of evidence (copied GPX files count as one origin).

Classify output edges:

- `gpx_observed`;
- `historical_trace`;
- `dem_horizontal_band`;
- `dem_valley_transfer`;
- `inferred_connector`.

## 9. DEM processing

### 9.1 Required metadata

Record:

- DEM provider and product;
- horizontal and vertical CRS/datum;
- nominal resolution;
- tile IDs and bounds;
- void filling, resampling, and smoothing;
- retrieval date;
- limitations such as canopy, buildings, or 30 m cell size.

### 9.2 Core derivatives

Slope:

```text
slope = atan(sqrt((dz/dx)^2 + (dz/dy)^2))
```

Local relief and curvature help distinguish broad benches from sharp spurs.
Topographic position can separate ridges, slopes, and valley bottoms.

The current Navigation hierarchy does not use a four-direction or D8 drainage
trace. It conditions bounded DEM windows with a priority-flood epsilon surface,
uses slope-weighted multiple-flow direction (MFD), accumulates contributing
area, retains only curvature candidates supported by downstream flow, and
records Strahler order plus Shreve magnitude. Large conditioning deltas are
suppressed from channel geometry because a filled closed depression can create
an artificial outlet trace. Raw elevation and conditioned elevation remain
separate in the artifact.

The dependency-free D8 command remains available only for legacy bounded
experiments and teaching fixtures. Its output must not be substituted for the
current hierarchy receipt. A drainage line is never automatically a walkable
valley route: waterfalls, incision, flood exposure, and dense vegetation are
unmodeled until separately evidenced.

### 9.3 Horizontal corridor candidates

Generate multiple separated traverse bands by minimizing a documented cost such
as:

```text
cost =
  slope_penalty
  + excessive_vertical_change
  + cliff_or_incision_penalty
  + distance_from_text_elevation
  + unsupported_connector_penalty
  - observed_gpx_support
  - historical_anchor_support
```

Then enforce corridor separation. If two outputs share most cells or stay within
one DEM pixel for most of their length, treat them as one family rather than two
independent alternatives.

### 9.4 Longitudinal layer changes

Find possible switches between horizontal bands at:

- saddles;
- low-gradient spurs;
- tributary heads;
- traversable-looking gullies;
- historical crossings;
- repeated GPX divergence points.

In visual outputs, label these separately from the horizontal bands (`V1…Vn`).
Valley transfer is a neutral topology term here, not a recommendation to walk
in the streambed.

### 9.5 Expert terrain skeleton

The expert examples add a hierarchy that cannot be represented by isolated
ridge, valley, and saddle points:

```text
main ridge
├─ spur ridge
│  └─ ridge divide point
└─ saddle

drainage trunk
├─ tributary
│  └─ headwater
└─ drainage confluence
```

Scout therefore keeps two different graph families:

- `terrain_hierarchy`: continuous landform skeleton and parent/branch
  relations;
- `route_topology`: observed or inferred human movement edges.

A terrain branch is not a path junction. A contour-compatible traverse band is
not a ridge. The following types must remain separate:

```text
main_ridge_candidate
spur_ridge_candidate
watershed_boundary
contour_traverse_band
drainage_trunk
tributary
```

The bounded construction implementation now separates the two landform
pipelines:

- ridge: multi-scale Gaussian support, Hessian curvature response, sub-cell
  localization, non-maximum suppression, tangent-aware graph tracing, and
  bounded DEM-supported recovery of broad T/Y junctions;
- drainage: priority-flood conditioning, slope-weighted MFD, contributing
  area, downstream acyclic topology, confluences, Strahler order, and Shreve
  magnitude;
- saddle: neighborhood sign change plus an opposite-sign Hessian eigenvalue
  gate, preventing a diagonal ridge from being mislabeled as a saddle;
- geometry: at most 0.35 cell support-constrained smoothing, retaining raw
  support points and a minimum candidate-support band of three cells.

The graph-diameter label remains a compatibility candidate
(`main_ridge_candidate`) rather than proof of a named principal divide.
Drainage trunk/tributary labels are based on contributing area and stream
order, not component diameter.

This is a deterministic morphology hypothesis. It does not infer a trail,
vegetation state, current surface condition, or walkability.

### 9.6 Expert annotation evidence

Expert sketches require an explicit evidence state:

- `semantic_training_only`: an unreferenced image can teach the difference
  between main ridge, spur, divide point, drainage, and route trace;
- `georeferenced_candidate_annotations`: the image has a stated CRS, at least
  three control points, bounded residual error, and map coordinates for every
  annotation.

Only the second state is eligible for geometry comparison, and it remains
candidate-only. A manually shifted screenshot is never geometry ground truth.

Blind validation requires more than georeferencing. Every reference set must
also declare an annotator ID, common reference-case ID, tuning or blind-holdout
split, independent annotation, completed topology review, completed ambiguous-
area review, and an uncertainty half-width for every line. At least two
independent annotators must cover the same blind case. Their disagreement is a
reported metric, not silently averaged away.

`navigation_terrain_validation.py` measures lateral RMSE, symmetric H95,
Hausdorff distance, discrete Fréchet distance, component/branch/junction error,
orientation spectrum, grid-axis concentration, and hydrologic monotonicity. It
contains no default promotion thresholds. Without an externally approved,
baseline-linked policy, the result is
`blocked_pending_acceptance_policy`; without qualified references it is
`blocked_pending_reference`.

### 9.7 Route-to-terrain event join

Project GPX segments onto the terrain hierarchy and emit events in increasing
route-distance order:

```text
watershed_crossing
drainage_crossing
saddle_passage
ridge_divide_passage
headwater_crossing
drainage_branch
route_terrain_transition
```

Every event records:

- route distance and off-route geometry distance;
- crossing angle or aligned relation;
- terrain feature and source references;
- an offline observation hypothesis;
- offline wrong-way and recovery text for shadow replay only.

Before reference-bound validation and a separate event-type gate, every event
is `shadow_only`, `operational_authority=false`, `effect_scope=none`, and
`presentation_scope=developer_debug_only`. Missing or old authority fields fail
closed. The general Dashboard projection removes wrong-way, recovery, and exact
crossing-distance language; it can show only a neutral shadow-review
hypothesis. Passing geometry alone never unlocks crossing, wrong-way, recovery,
notification, live navigation state, or safety effects.

## 10. Shared topology instead of independent lines

Represent the landscape as reusable edges.

```text
trailhead
  └─ observed old-road edge
      └─ 1115 camp
          └─ observed edge
              └─ 1148 saddle
                  ├─ H4 ───────────────┐
                  └─ H5 ─ V1 switch ──┤
                                      └─ IR1 ─ IR2 ─ station
```

Benefits:

- alternatives recombine naturally;
- common sections have one source/provenance record;
- field verification can target uncertain switches;
- new GPX can support or refute one edge without replacing entire routes;
- Scout can explain “where hypotheses differ” instead of presenting several
  opaque polylines.

The deterministic compiler enumerates simple edge paths and identifies shared
edges. It does not choose a safe route.

## 11. Visualization method

The successful Iroko overlay used:

- eight separated, north-to-south horizontal bands (`H1–H8`);
- legacy D8 flow-accumulation trunks for longitudinal valleys (`V1–Vn`),
  retained as provenance of the original experiment rather than the current
  Navigation hierarchy method;
- a probable envelope between H4 and H5;
- a recombined hypothesis following H5, switching through V1 to H4, then
  passing IR-1, IR-2, and the station;
- dark halo plus bright yellow center for the emphasized route;
- translucent yellow uncertainty area;
- blue dashed valley lines;
- historical anchor labels;
- a visible warning: “地形拼接假說，非已確認獵路”.

Rendering rules:

1. show all materially distinct bands before emphasizing a hypothesis;
2. avoid colors that make valley lines look like confirmed streams or trails;
3. include grid/CRS, date, scale, north, legend, and source note;
4. label inferred segments differently from observed GPX;
5. export both image and machine-readable GeoJSON/JSON;
6. inspect geometry for gaps and excessive adjacent spacing.

## 12. Iroko worked example

### 12.1 Corrected anchors

Approximate TWD97/TM2 zone 121:

| Anchor | Easting | Northing | Basis |
|---|---:|---:|---|
| trailhead A | 277200.84 | 2581264.92 | public GPX/map |
| 1115 m camp | 276357.51 | 2582234.13 | public GPX |
| 1148 pre-peak saddle | 276199.24 | 2582456.88 | GPX + DEM |
| IR-1 | 273758.87 | 2583183.20 | official T67 converted approximately |
| IR-2 | 273698.87 | 2583353.20 | official T67 converted approximately |
| station | 273562.87 | 2583348.20 | official T67 converted approximately |

Original official station coordinate:

```text
TWD67 272734 / 2583555
```

Plotting this raw value on a TWD97 grid causes an error of roughly the order of
0.8 km, large enough to select the wrong slope system.

### 12.2 Resulting hypothesis

The terrain-only graph found:

- a shared observed entrance to the 1115 m camp and 1148 saddle;
- several east-west traverse families;
- longitudinal valley/switch candidates;
- H4/H5 as the principal probable envelope;
- a recombined candidate H5 → V1 → H4 → IR-1 → IR-2 → station.

This is an explanatory hypothesis. The H4/H5 continuity, V1 switch, vegetation,
landslide state, stream crossing, land access, and present trail condition
remain field or newer-source questions.

The runnable example is:

```text
.agents/skills/infer-historical-dem-gpx-routes/references/iroko-example-input.json
```

## 13. Input and output contract

The compiler input contains:

```text
project_id
route_name
coordinate_context
sources[]
anchors[]
nodes[]
edges[]
start_node
end_node
contradictions[]
evidence_gaps[]
```

Every anchor, node, edge, and contradiction requires `source_refs`.

Run:

```bash
python tools/historical_dem_gpx_route_inference.py compile \
  --input <case.json> \
  --output <compiled.json>
```

For a bounded elevation grid:

```bash
python tools/historical_dem_gpx_route_inference.py dem-d8 \
  --input <dem-grid.json> \
  --output <d8.json>
```

The small dependency-free D8 function is appropriate for legacy tests and
bounded teaching experiments. It is not the current Navigation hierarchy
extractor. Larger experiments should preserve the conditioned-MFD lineage and
use a reviewed GDAL/rasterio/Whitebox adapter without weakening the output or
provenance contract.

## 14. Validation and acceptance

A capability proof passes when:

- original and converted coordinates are distinguishable;
- all evidence has source IDs and tiers;
- the historical narrative becomes an ordered constraint chain;
- DEM and GPX evidence are separately labeled;
- route alternatives are graph paths over shared edges;
- at least one route path connects start to destination;
- contradictions and evidence gaps survive compilation;
- JSON/GeoJSON and visual output agree;
- candidate/runtime flags are correct;
- arbitrary rotations, sinusoidal/S curves, Y junctions, saddles, broad/sharp
  crests, multiple resolutions, flats, and depressions pass analytic
  regressions;
- downstream drainage geometry is monotonic on conditioned elevation and
  increasing in contributing area;
- expert baseline metrics are recorded before an acceptance policy is
  approved;
- absence of two independent blind references or an approved policy remains a
  blocking receipt, never a silent pass;
- the focused tests and skill validator pass.

It does not pass merely because a line is visually plausible.

## 15. Field-verification handoff

Convert uncertainty into bounded questions:

- Does a tread, cut bench, blaze, wall, terrace, or artifact exist at this edge?
- Is the band continuous through the suspected switch?
- Is a mapped drainage crossable at ordinary flow?
- Is the historical point on the stated side of the tributary?
- Does local elevation agree with the source within expected DEM/GPS error?
- Are cliffs, landslides, dense bamboo, private land, closures, or restoration
  zones present?
- Can photographs and GPX be captured with consent and source metadata?

Field evidence should support or refute individual nodes/edges. It must not
silently replace the original hypothesis or erase failed alternatives.

## 16. Promotion debt

Before productionization:

- add robust raster adapters and official datum grid shifts;
- add GPX origin/de-duplication checks;
- add georeferencing residual reports;
- quantify corridor-equivalence and terrain-cost sensitivity;
- promote the experimental browser lenses and topology projection to a stable
  GeoJSON/schema contract;
- connect operator review and field-evidence disposition;
- define privacy retention for P2 exact-location data;
- evaluate against multiple known historical-route cases;
- calibrate uncertainty without converting it into a misleading safety score.

## 17. Construction slice status

The first Dashboard-connected construction slice is implemented:

- deterministic bounded DEM morphology candidates for ridge, valley, and
  saddle locations;
- P0/P1/P2 source ledger plus coordinate audit and ordered GPX waypoint clues;
- reusable node/edge route topology with reference GPX prevented from becoming
  automatic route options;
- browser lenses for structure, pressure, risk, and retreat plus visible source,
  topology, contradiction, and gap panels;
- a runnable Iroko fixture that compiles two options from shared edges.

The Chilai workspace now links two traceable P1 sources: a professional
SameJan route narrative and a Keepon completed-trip/GPX landing page. A
deterministic compiler combines only the three route combinations explicitly
described by the P1 narrative (both summits, Qilai South only, or Nanhua only)
with the workspace GPX anchors and P0 terrain/history baselines. The primary
map still shows one observed GPX baseline; the three alternatives stay in a
separate `candidate_topology` layer and are not current-access or walkability
claims.

The former 1,472-line workspace implementation has also been split behind a
small compatibility facade:

- `navigation_terrain_dem.py` owns bounded DEM morphology;
- `navigation_terrain_coordinates.py` owns bounded CRS conversion;
- `navigation_terrain_sources.py` owns P0/P1/P2 provenance and clue chains;
- `navigation_terrain_topology.py` owns observed and compiled candidate graphs.

This removes the known monolith debt without changing the public API imported
by the Dashboard projection.

The next expert-reading construction slices are also implemented behind the
facade:

- `navigation_terrain_annotations.py` owns expert annotation semantics and
  georeference, independent-review, uncertainty, ambiguous-mask, and blind-
  holdout eligibility;
- `navigation_terrain_morphometry.py` owns multi-scale Hessian/sub-cell ridge
  candidates and support-constrained topology tracing;
- `navigation_terrain_hydrology.py` owns priority-flood conditioning, MFD,
  accumulation, directed topology, and stream order;
- `navigation_terrain_skeleton.py` owns continuous main/spur ridge and
  trunk/tributary graph extraction;
- `navigation_terrain_validation.py` owns reference-bound geometry, topology,
  orientation, and hydrologic metrics plus the fail-closed promotion receipt;
- `navigation_terrain_skeleton_workspace.py` owns the prepared DEM adapter;
- `navigation_route_terrain_events.py` owns ordered GPX-to-terrain events.

The construction path now continues through the bounded Dashboard projection
and workbench:

- `navigation_terrain_projection_expert.py` converts the hierarchy and event
  sequence to WGS84 display geometry without exposing the raw DEM or GPX;
- the projection returns at most 240 hierarchy edges, 500 nodes, and 80 ordered
  route-terrain events, with explicit source counts and truncation;
- the Dashboard draws only muted candidate-support bands by default; exact
  hierarchy centerlines, glow, and authoritative “main” labels are disabled;
- the event lens is explicitly a developer/QA shadow view. It exposes a neutral
  review hypothesis and strips wrong-way, recovery, and exact crossing-
  distance action language;
- the projection always carries a terrain-validation receipt. With the current
  workspaces' missing qualified expert references, it remains
  `blocked_pending_reference` and `event_source_mode=prohibited`;
- `tools/navigation_terrain_expert_eval.py` deterministically checks
  unreferenced expert annotation semantics, branched DEM topology, and ordered
  route-terrain events.

This is still an experimental projection rather than a stable GeoJSON/API
contract. The generated hierarchy and event sequence remain candidate-only,
do not determine safe or walkable terrain, and do not mutate runtime safety
truth.
