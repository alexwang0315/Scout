# Scout Terrain Route Hypothesis Engine

Status: `WORKING PROTOTYPE`

Workflow: `terrain_route_hypothesis.v1`

Domain schema: `scout_terrain_route_hypothesis.v0_2`

Algorithm: `terrain_route_hypothesis.v0_2`
Last verified: 2026-09-01

## 1. Purpose

Scout Terrain Route Hypothesis (TRH) answers:

> Given endpoints A and B and the currently available DEM evidence, which
> terrain corridors and model-cost traces are relatively plausible movement
> hypotheses?

It does **not** answer whether a trail exists, whether passage is currently
possible, whether the route is safe, or whether access is legal. The subsystem
produces candidate evidence for Scout AI, the Navigation Dashboard, GIS review,
and human comparison.

The governing question is not "where does AI guess there is a trail?" It is:

> Which movement hypotheses are supported by the current terrain evidence,
> how strongly are they supported relative to one another, and what remains
> unknown?

## 2. Non-negotiable authority contract

Every request, worker run, artifact, projection, catalog entry, HTTP response,
and Dashboard rendering must preserve:

```text
authority=candidate_only
source_type=terrain_hypothesis
candidate_only=true
runtime_safety_truth=false
operational=false
phase1_runtime_mutation_allowed=false
writes_to_official_trail_db=false
writes_to_safety_truth=false
promotion_allowed=false
safe_or_walkable=not_determined
```

TRH output must never be labeled `existing_trail`, `confirmed_trail`,
`safe_route`, `passable`, `legally_accessible`, or `recommended_route`.
`terrain_hypothesis`, `observed_trail`, `known_gpx`, `official_trail`,
`historical_route`, `human_verified`, and `unknown` remain distinct source
types. No terrain result can promote itself into another type.

A successful least-cost computation proves only that the model found a finite
trace through its raster cost domain. It does not prove that a trail, bridge,
rope, engineered tread, legal access, or currently usable passage exists.

## 3. Scope delivered in this round

The current thin slice supports:

- arbitrary WGS84 A/B selection on the Dashboard Navigation map;
- persisted A/B drafts and a configurable 100-5,000 m analysis margin;
- exact, hash-bound prepared DEM and parent terrain-manifest validation;
- GRASS slope, nonlinear slope friction, flow accumulation, resolution-aware
  drainage pressure, anisotropic traces, and symmetric macro-terrain corridor
  processing;
- three same-request alternatives by default: `R1 drainage_averse`, `R2
  balanced`, and `R3 terrain_only_baseline`;
- one drainage-averse corridor profile plus three independently computed
  minimum anisotropic model-cost traces, while a bounded catalog still retains
  completed A/B runs for Dashboard selection;
- independent 5%, 10%, and 20% finite-cell corridor percentile layers;
- typed authority, evidence, unknowns, metrics, failures, provenance, and cache
  keys;
- stable 2D/3D MapLibre review with Rudy+TW context, vector hypothesis, corridor
  overlays, endpoint markers, and known-GPX reference;
- a host-agnostic command runner that can execute the same bounded worker on
  macOS or Scout/Linux when that host has the required QGIS/GRASS runtime and
  hash-bound workspace inputs.

The three alternatives are different model assumptions, not a safety ranking.
Their costs are comparable only within each profile because the friction scales
differ. On terrain with one dominant optimum, two or more profiles may still
produce the same geometry; the run records that collision instead of inventing
spatial separation.

## 4. Architecture and boundaries

```text
Dashboard A/B draft (WGS84)
  -> Admin spatial request boundary
  -> QgisSpatialBackend
  -> Scout-owned QgisWorkerService
  -> allowlisted QGIS Processing / GRASS modules
  -> content-addressed candidate artifacts + processing manifest
  -> atomic Navigation terrain projection
  -> MapLibre 2D / 3D review
```

The domain layer owns typed models and authority invariants. It does not know
about subprocesses or shell commands. `QgisWorkerService` owns the processing
adapter, allowlist, cancellation, typed failures, artifact hashes, and run
receipts. The Dashboard submits a typed workflow request and renders only the
published Navigation projection; it does not construct GRASS commands.

Relevant implementation boundaries:

| Boundary | Responsibility |
|---|---|
| `terrain_route_hypothesis_models.py` | Authority, source types, request/result schema, cost config, corridor bands, metrics, provenance, catalog, typed failures. |
| `terrain_route_hypothesis_artifacts.py` | Deterministic cache keys and validated mapcalc expressions. |
| `qgis_spatial_contracts.py` / `qgis_spatial_backend.py` | Arbitrary A/B request validation and worker submission. |
| `qgis_worker.py` | Bounded QGIS/GRASS execution, validation, metrics, artifact and manifest publication. |
| `navigation_terrain_projection.py` | Hash-bound candidate projection and completed-hypothesis catalog selection. |
| `admin_api.py` | Read-only Navigation delivery and candidate overlay serving. |
| `docs/admin/scout-dashboard-v0.1.html` | A/B editor, lifecycle display, 2D/3D evidence review, and candidate-only language. |
| `tools/run_terrain_route_hypothesis_worker.py` | Host-agnostic local worker entrypoint and execution-host receipt. |

## 5. Required inputs and fail-closed validation

The live workflow requires:

1. a prepared DEM GeoTIFF;
2. its sibling `terrain_feature_manifest.json`;
3. matching declared file name and SHA-256;
4. square source cells and matching declared/analysis resolution;
5. `EPSG:3826` for the current prepared DEM workflow;
6. two distinct finite WGS84 endpoints inside the analysis domain;
7. a complete finite analysis grid with no unexpected NoData;
8. the required allowlisted QGIS/GRASS capabilities.

Missing or inconsistent evidence produces a typed unavailable/failure result.
The workflow must not guess through missing DEM, mismatched CRS, stale parent
manifest, unexpected NoData, incomplete cost surface, worker failure, or an
unconnected endpoint pair.

## 6. Terrain cost model v0.2

The current live model combines nonlinear slope friction with a bounded
drainage-pressure term:

```text
slope_friction = base_cost + slope_weight * piecewise_slope_cost
drainage_pressure = piecewise(abs(flow_accumulation), DEM_cell_area)
profile_friction = slope_friction + profile_multiplier * drainage_pressure
```

Default slope bands are:

| DEM slope | Cost label | Relative cost |
|---|---|---:|
| 0-10 degrees | `terrain_cost_low` | 1.0 |
| >10-20 degrees | `terrain_cost_moderate` | 2.4 |
| >20-30 degrees | `terrain_cost_increasing` | 5.5 |
| >30-40 degrees | `terrain_cost_high` | 13.0 |
| >40 degrees | `terrain_cost_extreme` | 30.0 |

These labels are terrain-model costs, not passability classes. The default
`candidate_exclusion_slope_degrees` is unset, so no fixed slope is automatically
declared impassable.

Default profile multipliers are `4.0` for `R1 drainage_averse`, `1.5` for `R2
balanced`, and `0.0` for `R3 terrain_only_baseline`. The pressure thresholds
represent approximately 1, 5, and 25 hectares of upstream contributing area,
converted to cell counts from the actual DEM resolution. This is a model
penalty, not confirmation of a river, water, hazard, or impassability. R3 may
therefore follow a valley or channel and remains useful as a visible baseline.

Typed configuration still carries roughness, curvature, generic drainage,
ridge, and TEII weights. Except for the explicit per-profile drainage penalty,
those terms remain inactive. A zero weight means "not included in this model",
not that the property is zero on the ground.

## 7. GRASS processing chain

The fixed live chain is:

```text
validated DEM rectangle
  -> grass:r.slope.aspect
  -> grass:r.mapcalc.simple nonlinear slope friction
  -> grass:r.watershed flow accumulation
  -> grass:r.mapcalc.simple resolution-aware drainage pressure
  -> three profile friction rasters
  -> three grass:r.walk.coords accumulated anisotropic A-to-B costs + directions
  -> three grass:r.path minimum anisotropic model-cost traces
  -> full-extent grass:r.cost from A
  -> full-extent grass:r.cost from B
  -> C_corridor(x,y) = C_A(x,y) + C_B(x,y) - C_AB
  -> finite-cell 5/10/20 percentile masks
  -> independent trace-in-band containment audit
  -> hypothesis + visualization + processing manifests
```

`r.walk` is used for all three displayed path hypotheses because it accounts
for directional uphill/downhill movement cost. The two `r.cost` surfaces use
the declared corridor profile, currently R1, for the symmetric corridor.
`stop_coordinates` is deliberately omitted so both cost rasters cover the
complete analysis extent; `C_AB` is sampled at B.

The trace and corridor are separate model products:

- the magenta/line hypothesis is a minimum anisotropic model-cost trace;
- the 5/10/20 corridor bands are percentiles of symmetric macro-terrain
  relative cost;
- corridor masks use an inclusive threshold and include all cells tied at the
  threshold;
- best-path cells are never unioned into a corridor mask merely to force
  containment;
- `contains_best_path` is an audit result, not a confidence claim.

## 8. Result and provenance

`TerrainRouteHypothesis` includes A/B endpoints, candidate geometry, corridor
references, terrain-model-relative metrics, positive/negative evidence,
unknowns, DEM resolution class, confidence limits, model version, and full
provenance.

Current metrics include within-profile relative model cost, distance, elevation
gain/loss, sampled maximum and median slope, high-cost fraction, drainage
pressure overlap, and high-drainage-pressure overlap. Route metrics are
sampled deterministically from at most 80 evenly spaced path vertices while
retaining both endpoints. Provenance records the original vertex count, sampled
count, method, and that sampled maximum slope is not a full-path-cell maximum.

The processing manifest records at least:

- DEM dataset/ref, SHA-256, CRS, extent, actual cell resolution, and parent
  manifest;
- original WGS84 endpoints and analysis margin;
- cost-model and algorithm versions, weights, and weights hash;
- QGIS, GRASS, MCP plugin, host, and architecture versions;
- ordered processing modules and bounded parameters;
- path/corridor semantics, `C_AB`, thresholds, tie handling, cell counts, and
  containment audit;
- derived-terrain, friction, cost-raster, and route-hypothesis cache keys;
- timestamp and candidate-only authority fields.

Cache identity is content-addressed from DEM/source hashes, resolution, extent,
endpoints, margin, model/algorithm versions, weights, and optional evidence
hashes. Stale or hash-mismatched evidence is not accepted as the active result.

## 9. Dashboard Navigation behavior

The Navigation map is the primary review surface:

1. Select `A`, click the map, then select `B` and click the map.
2. Adjust the analysis margin when needed.
3. Select **Generate candidate TRH**.
4. Review the progress counter and the final candidate line/corridor in 2D,
   3D, or split view.
5. Compare the terrain hypothesis with the known GPX and other evidence; do not
   interpret overlap as verification.

Lifecycle behavior is atomic and explicit:

- A/B, margin, clear, generate, and competing workflow controls are locked
  while the request is queued or running;
- polling updates the workflow controls without rebuilding the MapLibre map
  every 2.5 seconds;
- while a new run is active, a previously completed candidate may remain
  visible only with explicit "previous candidate retained" wording;
- the Navigation projection switches once, after the new run reaches
  `completed` and hash validation succeeds;
- a terminal failure keeps the previous completed evidence separate and shows
  typed failure code, stage, and non-empty detail;
- failure to load an optional corridor PNG does not blank the base map or the
  vector hypothesis;
- the permanent map boundary reads
  `CANDIDATE / TERRAIN HYPOTHESIS / NOT A VERIFIED TRAIL`.

`Rudy+TW original` disables elevation tint, hillshade, and contour overlays so
the original base imagery remains inspectable. Terrain overlays can be restored
without changing the candidate authority. Prepared Terrain RGB drives 3D
elevation display but adds no source resolution.

## 10. Portable execution

`tools/run_terrain_route_hypothesis_worker.py` packages the same typed request
and Scout-owned worker boundary for either macOS or Scout/Linux. It resolves the
QGIS Agent MCP package from an explicit path, `SCOUT_QGIS_MCP_PYTHONPATH`, the
macOS Scout QGIS profile, or `/opt/qgis-plugins/qgis_agent_mcp/_server`.

The runner writes an execution receipt containing the actual hostname,
architecture, run ID, duration, QGIS version, module list, artifact count, and
candidate-only boundary. Portability of the entrypoint is implemented and unit
tested. Actual execution on the Scout host remains `UNKNOWN` until that host is
reachable and completes the same real DEM workflow.

## 11. Verification evidence from this round

Focused automated checks completed for this documented slice:

- TRH domain, portable runner, QGIS MCP, spatial bridge, worker, and the
  required QGIS/GRASS candidate-risk adapter: 108 passed, 1 skipped;
- Navigation projection/DEM, admin API, Dashboard, and runtime launchers: 272
  passed;
- TRH documentation and Navigation-force authority contract: 2 passed;
- frontend lint passed;
- frontend typecheck passed;
- frontend test suite: 19 passed;
- Ruff passed for the changed QGIS worker/test surface;
- scoped `git diff --check` passed.

Two real local QGIS 3.44.13 / GRASS 8.5.0 runs verified arbitrary A/B behavior.
The regression pair close to the previously failing area completed as run
`qgis-worker-20260901T044232408212Z-11dc300da9` in about 116 seconds. Its
content-addressed result used cache key
`d3e4b6b26b2530fed0c9023a07bcc7f62cedf37fb67711de441af6a53c80d918`.

That 20 m run produced an 89-vertex trace, sampled 80 vertices for route
metrics, and published nested 5/10/20 corridor bands with 1,720, 3,439, and
6,878 cells. All three independently contained the trace. Dashboard review
showed the candidate line, corridor, endpoint markers, Rudy+TW context, decoded
3D DEM, and zero browser console errors after reload.

These numbers are an execution receipt, not a correctness target and not a
safety assessment.

## 12. Known limitations and UNKNOWNs

The current implementation must preserve all of the following:

| Limitation | Required interpretation |
|---|---|
| 20 m DEM | `macro_terrain_only`; one cell is roughly 400 square metres and cannot locate a metre-wide tread. |
| Vegetation | `vegetation_unknown`; density, bamboo/fern obstruction, visibility, and seasonal growth are not inferred. |
| Microterrain | `microterrain_unknown`; small cliffs, steps, road cuts, boulders, and short collapses may be invisible. |
| Recent landslide | `recent_landslide_unknown`; DEM age may predate storms or slope failure. |
| Legal access | `legal_access_unknown`; permits, closure, ownership, and access rights are not terrain properties. |
| Engineered trail | Bridge, rope, ladder, stairs, tunnel, retaining wall, and engineered tread presence remain unknown. |
| Water state | Current depth, discharge, flood state, and crossing condition remain unknown. |
| Drainage inference | Flow accumulation is DEM-derived at source resolution; it does not confirm a wet channel, seasonal flow, canyon, bridge, or usable crossing. |
| Trail surface | Mud, erosion, loose rock, scrambling, and tread condition remain unknown. |
| Scout-host execution | Portable runner exists, but a real Scout-host QGIS/GRASS receipt has not yet been collected. |

Resolution class is never an overall safety confidence score. A finer DEM may
support finer terrain-form candidates, but it still cannot establish current
passage, legal access, or operational safety.

## 13. Next recommended phase

The next highest-value phase is to add spatial-diversity constraints when two
profiles collapse onto the same optimum, and to compute a separately bound
corridor for each profile. After that, add versioned roughness, curvature,
ridge/valley, geomorphon, and TEII evidence one source at a time with
synthetic-terrain and real-workspace regression tests.

Known GPX terrain-consistency analysis and Scout AI tools remain separate later
work. Their outputs must be `CONSISTENT`, `PARTIALLY_CONSISTENT`,
`TERRAIN_ANOMALY`, or `UNKNOWN`, never automatic GPX correction or validity
judgment.
