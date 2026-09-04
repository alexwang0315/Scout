# Scout Terrain Route Hypothesis Engine

Status: `WORKING PROTOTYPE`

Workflow: `terrain_route_hypothesis.v1`

Domain schema: `scout_terrain_route_hypothesis.v0_2`

Algorithm: `terrain_route_hypothesis.v0_3`
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
- an optional reviewed `R4 historical_narrative_guided` hypothesis: Scout AI
  interprets historical prose into typed constraints, deterministic GIS code
  resolves candidate landforms, an optional hash-bound candidate corridor overlap
  ranks the complete candidate set for review, and a human confirms explicit
  map-point anchors before execution; each reviewed point compiles to a bounded
  local friction preference in addition to being an ordered route gate;
- one drainage-averse corridor profile plus three independently computed
  minimum anisotropic model-cost traces, while a bounded catalog still retains
  completed A/B runs for Dashboard selection;
- independent 5%, 10%, and 20% finite-cell corridor percentile layers;
- typed authority, evidence, unknowns, metrics, failures, provenance, and cache
  keys;
- stable 2D/3D MapLibre review with Rudy+TW context, vector hypothesis, corridor
  overlays, endpoint markers, and known-GPX reference;
- deterministic GPX terrain-consistency inspection against a selected,
  hash-bound hypothesis and corridor, with typed `CONSISTENT`,
  `PARTIALLY_CONSISTENT`, `TERRAIN_ANOMALY`, or `UNKNOWN` output and bounded
  candidate-only anomaly sample points for MapLibre review;
- Scout AI tool boundaries for arbitrary A/B generation, hypothesis explanation,
  multi-hypothesis comparison, and GPX terrain-consistency inspection;
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
  + optional historical narrative
      -> Scout Pydantic AI typed constraint plan
      -> deterministic DEM feature resolver
      -> optional hash-bound parent TRH corridor-overlap review rank
      -> unresolved/conflict preview + explicit map-point review
      -> typed review decisions + hash-bound R4 execution plan (raw prose excluded)
      -> bounded reviewed local-friction preferences + ordered route gates
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
| `terrain_route_hypothesis_artifacts.py` | Deterministic cache keys and allowlisted, structurally validated mapcalc expressions, including reviewed local-friction preferences. |
| `terrain_route_consistency.py` | Typed deterministic GPX terrain-consistency statuses, aggregate metrics, observations, mismatch explanations, unknowns, and authority invariants. |
| `scout_terrain_route_hypothesis_tool.py` | Scout AI generate/explain/compare/inspect tools, R4 anchor-alignment/conflict explanation, hash-bound workspace loading, GPX parsing, bounded GDAL sampling, and candidate-only output. |
| `terrain_route_guidance.py` | Candidate-only narrative constraints, source spans, unknowns, review decisions, bounded cost modifiers, and reviewed R4 execution plan. |
| `src/scout/agents/terrain_narrative_guidance.py` / `scout_terrain_narrative_guidance_tool.py` | Scout Pydantic AI interpretation boundary and read-only tool registration. |
| `terrain_route_guidance_workspace.py` | Hash-bound narrative, feature index, resolution, review, DEM binding, optional parent-TRH corridor-mask sampling, and worker-safe execution-plan compilation. |
| `qgis_spatial_contracts.py` / `qgis_spatial_backend.py` | Arbitrary A/B request validation and worker submission. |
| `qgis_worker.py` | Bounded QGIS/GRASS execution, validation, metrics, artifact and manifest publication. |
| `navigation_terrain_projection.py` | Hash-bound candidate projection and completed-hypothesis catalog selection. |
| `admin_api.py` | Read-only Navigation delivery, candidate overlay serving, hypothesis explain/compare, and typed GPX terrain-consistency API. |
| `docs/admin/scout-dashboard-v0.1.html` | A/B editor, lifecycle display, 2D/3D evidence review, GPX terrain-consistency inspector, and candidate-only language. |
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

Guided R4 additionally requires a current `REVIEWED` artifact, matching plan,
resolution, feature-index, review, parent-manifest, and DEM hashes, plus at
least one explicit WGS84 point created by a human map annotation. Selecting a
DEM ridge/valley line alone is not an executable point. A stale review, changed
DEM, missing point, reordered point, or unresolved required anchor fails closed.
The execution plan also requires exactly one ordered cost modifier per reviewed
anchor. A missing, duplicate, reordered, non-finite, out-of-range, or
structurally invalid modifier fails closed before GRASS execution.

When review ranking references an existing parent TRH, the resolver additionally
requires the hash-validated project catalog, completed hypothesis artifact,
matching A/B and cache key, processing-manifest parent-source hash chain, and the
source GeoTIFF for the named corridor band. The source mask has only `1=inside`
and `255=NoData/outside` semantics. A PNG visualization is never sampled as
evidence. Missing or changed catalog, hypothesis, raster, endpoint, sampler, CRS,
or parent hash fails closed before a feature index or resolution is published.

The deterministic feature resolver is also bound to the active A/B endpoints
and the declared 100-5000 m analysis margin. It clips QGIS ridge, valley, and
drainage vectors to that WGS84 route window and emits separate local
`LineString` candidates. It does not return a project-wide `MultiLineString` or
let a DEM-derived line act as an executable R4 anchor. Missing/distinctness/CRS
errors, out-of-window human points, or a local feature/coordinate budget
overflow fail closed and require a smaller analysis window.

For each DEM-derived feature, corridor overlap uses at most 24 deterministic
geometry samples and records inside plus outside/NoData counts. Ranking applies
typed landform and elevation first, then overlap with the selected corridor,
then narrative-sequence proximity. The explicit semantics are
`candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation`:
the overlap does not filter candidates or select an anchor, including when the
overlap is zero. Human map annotations remain separate and are never assigned
DEM corridor evidence.

The Dashboard may bind a same-A/B hash-bound TRH run, preferring an active run
that contains R1-R3 alternatives, to reduce visual review load. Saved catalog
entries remain supported, and the request boundary accepts at most three run
selections for legacy layouts. An active selection ID must match the first 12
characters of the project's bound cache key; every run independently passes
the hypothesis file hash, cache, DEM-parent, endpoint, and CRS checks. Corridor
rasters additionally pass the source-raster checks above. R1-R3 path vertices
are deterministically bounded while preserving endpoints, and each DEM feature
records its minimum distance to every path. The default Dashboard path scope is
200 m and is review UI scope, not route width or position accuracy.

The resolver preserves the complete typed set in
`candidate_feature_ids` and separately emits
`review_shortlist_feature_ids` as the union of candidates touching at least one
bound corridor or lying within scope of at least one R1-R3 path. This union is
ranking context, not the Dashboard's visible point set. A candidate without
path/corridor support is outside that review scope, not deleted from evidence. The shortlist
cannot select an anchor, change resolver authority, satisfy a required anchor,
or make R4 executable without an explicit human WGS84 Point.

The Dashboard uses a stricter, read-only `map-review-scope` projection for Gn
markers and their candidate lists. It samples each marker's own centroid in the
selected 5/10/20-percent source corridor GeoTIFF. A line touching the corridor
somewhere else, or lying within a broad R1-R3 path buffer, cannot admit an
outside marker. Saddle candidates also require centroid proximity to an R1-R3
path within one DEM-cell diagonal. That tolerance is a terrain-grid review
constraint, not historical-location accuracy. A missing match remains UNKNOWN;
the projection must never move a saddle onto a route to manufacture a match.

The projection binds the selected hypothesis, corridor band, raster hash,
source feature-index/resolution hashes, DEM parent and both A/B contexts. It also
works on older unscoped resolutions without rewriting them. Geometry from the
same DEM but a different source A/B may be visually clipped, with explicit
`endpoint_alignment=different_review_context`, both endpoint pairs and measured
differences. This projection always has `execution_eligible=false` and
`routing_effect=none`; it cannot rebind a resolution or review to the new A/B.
The existing resolver, human review and R4 execution keep their endpoint checks.
Pending, stale, unavailable
or NoData scope evidence must hide DEM candidates, never fall back to the full
set. Switching hypothesis or percentile refreshes the scope without writing a
review, selecting anchors, or rebuilding the map for the response. Labels keep
their original ranks, such as `G6 #2` and `G6 #5`, after filtering. Human map
annotations remain separate. Long hypothesis-name badges are omitted from the
map center; the external status/legend retains the candidate-only disclosure.

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

When present, R4 uses the balanced `1.5` drainage multiplier in this V1 slice,
but its reviewed anchors divide the calculation into ordered anisotropic
segments. Before those segments run, every reviewed point compiles to a local
binary preference with a 20-500 m influence radius and a minimum friction
multiplier between `0.5` and `1.0`. The current typed presets distinguish ridge,
saddle, drainage crossing, directional traverse, relative-feature, elevation,
and generic reviewed gates. They lower local model friction without creating a
zero-cost cell, hard barrier, or route truth. R1-R3 retain their original
friction expressions. R4 is not ranked against R1-R3 and is not evidence that
the historical description remains correct on the ground.

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
  -> optional R4: grass:r.mapcalc.simple applies bounded reviewed local
     preferences to an isolated balanced base raster
  -> optional R4: A -> reviewed anchor 1 -> ... -> B,
     one grass:r.walk.coords + grass:r.path pair per segment
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

For R4, every segment must produce a finite cost and a path whose endpoints join
the reviewed points within DEM-cell tolerance. Segment costs are summed only as
the R4 within-profile cost. Any failed segment makes the guided calculation
unavailable; Scout never bridges the gap with a straight line. The worker
receives the typed points and review hashes, not the raw narrative.
The local-friction expression is generated from numeric typed fields and then
structurally revalidated; arbitrary expressions or narrative text cannot enter
`r.mapcalc`.

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
- for R4, guidance/review/plan/resolution/feature-index hashes, typed human
  review decisions, ordered point anchors, bounded cost modifiers, the validated
  guidance-friction expression, disabled constraints, per-segment costs and
  module receipts;
- when used for review ordering, the parent hypothesis/catalog/cache/raster
  hashes, corridor band, sampler backend, bounded sample counts, and
  `candidate_corridor_overlap_is_review_rank_evidence_not_route_confirmation`
  semantics;
- timestamp and candidate-only authority fields.

Cache identity is content-addressed from DEM/source hashes, resolution, extent,
endpoints, margin, model/algorithm versions, weights, and optional evidence
hashes. Stale or hash-mismatched evidence is not accepted as the active result.
Changing only the guidance review hash reuses the derived-terrain and baseline
friction keys but invalidates guided cost-raster and route-hypothesis keys.

## 9. Dashboard Navigation behavior

The Navigation map is the primary review surface:

1. Select `A`, click the map, then select `B` and click the map.
2. Adjust the analysis margin when needed.
3. Select **Generate candidate TRH**.
4. Review the progress counter and the final candidate line/corridor in 2D,
   3D, or split view.
5. Compare the terrain hypothesis with the known GPX and other evidence; do not
   interpret overlap as verification.

Optional reviewed R4 flow:

1. Paste the historical description and identify its source.
2. Let Scout AI create a typed constraint preview with exact source spans,
   conflicts, and unknowns.
3. Select an existing hypothesis and use **Apply current hypothesis A/B**, or
   set a new A/B manually. Changing A/B invalidates every prior guidance review.
   When the same-A/B run contains R1-R3, the resolver uses all three path
   geometries plus the run's single corridor profile as a hash-bound review-scope
   union; this is not multi-model route confirmation.
4. Resolve DEM-derived candidate zones. The adapter samples line centroids from
   the bound DEM, derives candidate-only ridge-local-minimum saddle proxies, and
   ranks matches by typed landform, elevation difference, optional hash-bound
   parent-TRH corridor overlap, then narrative-sequence proximity between A and
   B. Zero or multiple matches remain in the complete resolution and no
   automatic anchor selection is made. The map shows only marker points inside
   the currently selected corridor, with an additional path-proximity condition
   for saddles, while reporting the complete count; an out-of-scope candidate is
   retained in evidence and can never be treated as disproven. Corridor support
   is review evidence relative to terrain models, not confirmation of a
   historical route.
   Sampling provenance records `completed`, `partial`, `no_data`, or
   `unavailable` plus total/NoData counts. NoData cannot create elevation or
   saddle evidence.
5. Focus one `Gn` at a time in the R4 review frame. The Dashboard defaults to
   the first required review constraint. Clicking its narrative, source text,
   DEM summary, or candidate evidence preview switches highlight; Enter/Space
   on the focusable evidence area does the same. It provides previous/next and explicit
   all-Gn controls, draws every in-scope candidate for the focused constraint
   with its original numbered highlight marker, dims other constraint lines,
   and fits the existing MapLibre view to the focused marker bounds. Focus changes only
   presentation state: candidate lines, points, ranks, and markers remain
   context and none is an executable anchor choice.
   Anchor, select, disable, and other interactive controls retain their own
   actions without also triggering the evidence-area focus handler.
6. Place explicit map-point anchors or explicitly disable constraints, then save
   the human review artifact under the visible reviewer alias. The Dashboard
   defaults to `dashboard_operator`; it does not claim the operator is a trip
   leader. The artifact records that Scout AI made no map selection and preserves
   each human-selected point, disabled constraint, source, and pre-review
   resolver candidate set as typed review decisions.
7. Generate R4. The result appears as a fourth green dashed candidate alongside
   R1-R3 and retains `historical_narrative_guided` path semantics.
8. Use the explanation tool to inspect each reviewed anchor's distance to R4 at
   a tolerance of `max(10 m, 2 DEM cells)`. `aligned` means only that the
   candidate geometry reflects the reviewed map binding; `conflict` or
   `unavailable` does not determine real-world passage or narrative validity.

Worker readiness recovery:

- A/B drafts remain browser-local when the Worker is unavailable. The builder
  names the blocking condition (disabled/unconfigured Worker, lost connection,
  timeout, missing QGIS bridge, or missing TRH capability) next to the disabled
  generation control.
- **重新檢查 Worker** repeats only status, capability, and runtime-control
  metadata GET requests. It
  updates controls in place without rebuilding the map, changing A/B, replacing
  the current candidate, or clearing narrative review and Gn focus. Completing
  an A/B selection also retries an unavailable connection once. Concurrent
  checks are coalesced; responses from a different project or API host are
  discarded. There is no background retry loop or automatic route submission.
- Initial rendering, in-place updates, R4 controls, and TRH submission use the
  same live-Worker gate. A reachable Worker with a missing QGIS application or
  bridge, a synthetic fixture, or an unconfirmed TRH capability cannot enable
  generation. Running workflows retain their lock and are not interrupted by
  a readiness check. R4 still requires its explicit human review.
- **啟動 Worker** is a separate explicit local action. The workspace Dashboard
  injects `QgisRuntimeController` with `LocalQgisRuntimeHost`; the general admin
  API defaults to `NOT_MANAGED`. Only a same-origin JSON POST from a loopback
  client can call `/spatial/qgis/runtime/ensure-ready`. The body accepts only
  `action=ensure_ready`, never a command, host, credentials, or authority.
  Entering Navigation, status GETs, and Diagnostic never launch services.
- The start-only adapter reuses a live Worker/bridge. On macOS it can open the
  already-prepared Scout QGIS profile if no QGIS instance is running, then start
  the fixed local Worker launcher. It never kills a process, installs a plugin,
  edits credentials, or restarts an active job. An existing unresponsive QGIS
  session returns `QGIS_SESSION_REQUIRES_ATTENTION`; remote configurations return
  `REMOTE_MANAGED`. Linux can reuse an existing bridge but this button does not
  start a container or remote service.
- Startup is serialized, bounded, and audited in the prepared runtime directory
  (`qgis-runtime-control.jsonl`); Worker output is in
  `qgis-worker-navigation.log`. Receipts contain request/project IDs, timestamps,
  action names and typed outcomes, not secrets. Runtime GET shows control
  eligibility and the last operation receipt, not proof of current readiness.
  Only a fresh authenticated Worker/QGIS/bridge/capability check unlocks TRH.
  Starting preserves A/B, current map, narrative, anchors, and Gn focus. It never
  submits a terrain job or satisfies R4 human review.
- The shell Dashboard launcher still starts/reuses only the Worker. Workers
  started by the explicit Navigation action remain available for reuse across
  Dashboard restarts; this action has no stop/restart command. A stale MCP file
  or listening port alone never proves READY. See the preparation runbook.

Navigation diagnostics:

- `System > Diagnostic > Navigation 體檢` runs only DASH-025 and DASH-038-043.
  Existing single-check retry and Diag all remain available. Results are scoped
  to the current project, hypothesis selection, and corridor band; switching
  context invalidates them, and simultaneous batches/retries are prevented.
- DASH-039 checks the real Worker handshake and TRH workflow capability, not a
  fixture or a new GRASS execution. A timeout is a failure even if saved routes
  remain visible.
- DASH-040 checks saved candidate geometries, processing provenance, and all
  three corridor PNG responses, SHA-256 hashes, and decoded dimensions.
- DASH-041 checks the R4 source hashes, corridor scope, retained original ranks,
  and saddle-to-path bound. NoData/missing evidence fails closed; unresolved Gn
  and different review A/B remain visible warnings.
- DASH-042 separates reviewed Point-anchor readiness from existing R4 execution
  evidence tied to that review. Missing review or execution remains UNKNOWN;
  readiness alone cannot produce a successful execution receipt.
- DASH-043 renders the current review in isolated DOM and exercises the same
  evidence click/keyboard/previous/next bindings and focused feature projection
  used by Navigation. It does not move the live map or change anchors/review.
- This read-only batch does not generate TRH/R4, save review, modify GPX, or
  access runtime safety authority. Passing it is not proof of a fresh computation
  or real-world trail conditions. See the existing Dashboard functional
  verification checklist for actual execution and browser acceptance steps.

Optional known-GPX terrain comparison:

1. Select the exact Dashboard hypothesis and 5/10/20 percent corridor band.
2. Select **Check primary GPX**. The Dashboard sends the selected option's
   workspace-relative hypothesis ref, not only its display ID.
3. Scout verifies the candidate-only historical GPX source index and GPX hash,
   aligns the hypothesis endpoints to one GPX segment, and samples at most 400
   deterministic points by default.
4. Review aggregate corridor, slope, drainage, TEII, and trace-deviation evidence
   plus bounded anomaly points on the same MapLibre map.
5. Preserve missing dimensions as `UNKNOWN`. A mismatch is not GPX invalidity and
   does not modify the GPX.

The reviewer confirms the interpretation-to-map binding only. This does not
change the source to `human_verified`, verify a trail, or grant runtime safety
authority.

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
candidate-only boundary. It also records a host-path-independent input contract
from the source DEM hashes, terrain parent-manifest hash, resolution semantics,
endpoints, margin, cost configuration, and optional guidance-review hash.

The optional `--guidance-execution-plan` input accepts only a reviewed
`TerrainGuidanceExecutionPlan`. It rejects extra raw-narrative fields, requires
matching DEM hash/resolution/CRS, and inserts only the reviewed WGS84 Point
anchors into A to B. The receipt records R4 review hashes and explicitly scopes
human review to interpretation-to-map binding.

`deploy/pi-gis/launch-qgis-mcp.sh` starts Xvfb without the `xvfb-run` PID 1
signal handshake, waits for the bounded display socket, and then execs QGIS.
This fixes the observed headless aarch64 startup stall without changing the
live Scout Admin container.

`tools/compare_terrain_route_hosts.py` compares two receipts and hypothesis
artifacts. Input/authority mismatch is unavailable; path, metric, and corridor
variance is reported against explicit reproducibility tolerances. This parity
receipt is not a trail, passage, or safety assessment.

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

Cross-host prototype execution is now proven for the same 20 m DEM, A/B,
1000 m margin, model, and algorithm. The Mac x86_64 run used QGIS 3.44.13 and
GRASS 8.5.0, completed in 59.722 seconds, and published 21 artifacts. The Scout
aarch64 isolated container used QGIS 3.44.13 and GRASS 8.4.1, completed in
29.747 seconds, and published 21 artifacts. Both receipts share input contract
`8c4991fb38674ebd73191c3a7f0c52eb8581b5a092435c1ae70c402b194a42ca`.

R1/R2/R3 vertex counts matched at 95/93/89. Each path had about
`3.93e-10 m` Hausdorff difference and metric deltas below `1e-6`. Corridor
cell-count differences were about 1.1 percent and threshold differences were
at most 2.07 percent, within the declared 3 percent raster-engine tolerance.
The result is `passed_with_engine_variance`; exact GRASS-version parity remains
UNKNOWN. Machine-readable evidence is stored in:

- `docs/evals/scout-terrain-route-mac-receipt-20260901.json`
- `docs/evals/scout-terrain-route-scout-receipt-20260901.json`
- `docs/evals/scout-terrain-route-host-parity-20260901.json`
- `docs/evals/scout-terrain-route-host-parity-20260901.md`

The narrative-guidance extension added focused checks for exact source spans,
prompt-injection resistance, typed Scout AI output, tool registry/planner/
executor behavior, hash-bound workspace lifecycle, stale DEM/review rejection,
route-window clipping and bounds validation, local candidate budget failure,
manual map-point requirements, refresh-safe narrative recovery, cache
invalidation, worker request isolation,
ordered multi-segment GRASS execution, four-alternative materialization,
Navigation projection, and Dashboard R4 submission/style. The combined focused
TRH/QGIS/Navigation/Dashboard regression set completed with **226 passed** on
2026-09-01. This is prototype evidence, not Scout-host qualification.

The Scout AI/GPX consistency extension completed **254 focused AI, registry,
planner, guidance, standard, and terrain-consistency tests**, including 16
direct consistency/API tests. The Dashboard static suite completed **137
tests**, and its single inline script passed a Node syntax parse. A real Admin
API and browser replay against the full-route R1 artifact sampled 400 points and
returned `PARTIALLY_CONSISTENT`: 0.5 percent outside the selected 10 percent
corridor, 23.869 percent on DEM cells at or above the configured extreme-slope
threshold, and 93.5 percent farther than 100 m from that specific model trace.
Drainage and TEII remained `UNKNOWN`. The GPX was unchanged, 377 bounded anomaly
sample points were available to MapLibre, 2D remained ready, and the 3D canvas
and Rudy+TW source remained present. This is terrain-model consistency only;
it is not GPX validity, trail verification, passability, access, or safety.
Evidence is recorded in
`docs/evals/scout-trh-gpx-terrain-consistency-20260901.md`.

On 2026-09-02, the real 1148 saddle to Iroko station catalog hypothesis was
reused as the guidance A/B window. Hash-bound GDAL sampling completed against
the 20 m DEM and produced three saddle proxies in the local search extent. A
second hash-bound pass sampled the selected R1 5 percent source corridor mask:
1,595 bounded samples covered 203 DEM features, 78 samples were inside, and 18
features had non-zero overlap. The typed `G1` 1148-saddle constraint retained
its one candidate at 1144.57 m with zero overlap; `G6` retained all five ridge
candidates within the configured 80 m elevation tolerance. `G7` retained all
131 drainage candidates and `G11` retained all 32 ridge candidates while
overlap changed only their deterministic review order. The workspace review was
explicitly cleared and `guided_execution_ready=false`; no R4 was synthesized
from these candidates. This evidence is recorded in
`docs/evals/scout-trh-narrative-guidance-candidate-ranking-20260902.md`.
The expanded guidance, projection, Dashboard, Scout AI, standard, and GPX
consistency regression set completed with **520 passed**; Ruff and diff
whitespace checks also passed. A live Dashboard replay selected the local
Iroko hypothesis in both 2D and 3D, rendered one MapLibre canvas with no WebGL
error banner, displayed the overlap provenance and ranked markers, and kept
review plus R4 disabled pending human map points.

The reviewed local-cost compiler was subsequently exercised through the real
macOS QGIS-LTR / GRASS 8.5 `grass:r.mapcalc.simple` provider. Against a 20 m
EPSG:3826 baseline friction raster, a reviewed ridge preference with multiplier
`0.78` changed the anchor sample from `3.4` to `2.652`; the output retained the
same 234 by 147 grid, 100 percent valid cells, and finite positive range. Focused
tests additionally prove one-to-one anchor/modifier binding, expression
injection rejection, unchanged R1-R3 profile expressions, typed human review
decisions, and R4 alignment/conflict explanation. This is processing evidence,
not evidence of a trail, passage, safety, or legal access.
The expanded affected-surface suite completed **489 passed**, and a live
Dashboard smoke switched the real Iroko workspace between one-canvas 2D and 3D
states without a visible MapLibre/WebGL error. Review and R4 generation stayed
disabled because no human Point anchors had been supplied.

### 2026-09-04 Arbitrary A/B extent and map-retention repair

The failed Dongqing A/B run `qgis-worker-20260904T005941165938Z-c59eeb94a5`
stopped at `dem_loaded` with `NODATA_PRESENT`: its 1,000 m analysis margin
extended beyond the previously prepared GPX-bounded DEM. The resulting clip
contained 13,994 NoData cells out of 62,088. This was a source-selection problem,
not permission to relax the finite-grid requirement.

For explicit A/B requests without an operator-specified `dem_ref`, the backend
now selects the registered full-extent raster when its source and coverage
summary hashes are bound by the terrain-feature parent. Its CRS and native
resolution must match that parent. Missing, changed, or mismatched registered
sources fail closed. The worker still crops the requested extent and rejects
NoData; it does not shrink the margin, interpolate gaps, or change cost weights.
The actual full DEM hash participates in all existing cache/provenance keys.
The prepared parent DEM hash is retained separately in `source_hashes` and
`source_resolution.parent_dem_sha256`, and participates in cache identity.
This preserves the existing R4 corridor/path parent-chain validation while
making clear that only the full raster supplies the new analysis pixels.
Projects without a parent-bound full raster retain the bounded-source path.

Starting an A/B attempt no longer clears the published candidate's project
references. Only successful validation and materialization publishes a new
candidate. Failed/cancelled attempts remain separate typed workflow receipts;
the Dashboard explicitly identifies a retained candidate as an earlier result,
not a solution for the failed request. Import/preparation invalidation remains
unchanged.

Navigation loads completed `terrain_feature_stack.v1` evidence independently
of the latest TRH job. Ridge, valley and drainage vectors plus their full GPX
reference geometry no longer come from a queued/failed TRH receipt. Reloading
the page restores that baseline and the failed job's visible error; TRH input
lines never replace the reference GPX. A/B drafts and R4 human review are not
reset or automatically completed.
Transient projection preparation/timeouts retain the previously loaded map
with an explicit previous-evidence notice. Authoritative unavailable/failed
projections still replace stale evidence, and responses for a different
project/API scope are ignored.

Live recovery used the original failed A/B and unchanged 1,000 m margin in
`qgis-worker-20260904T012958960072Z-8d6d01ab12`: all 62,088 clipped DEM cells were
finite, and R1/R2/R3 completed. Cache identity
`82a9f7b4511226e028261759c6a04f002a59aca177dcf5d30152d5ab89f869c9`
retains both the full raster and prepared-DEM parent bindings. A read-only R4
replay accepted its 10% corridor and three candidate paths without modifying
the workspace or completing human review.

The operator subsequently submitted a newer A/B through a still-running old
Dashboard on port 9100. That process repeated the premature-deactivation bug;
updating only port 9099 had not updated the operator's actual backend. After
the newer job completed, port 9100 was restarted against the updated code while
preserving the shared QGIS worker and the newer result (active cache prefix
`be8797bfcd83`). Both local Dashboard entrypoints now serve the repair.

Verification: the combined affected Python suite produced 442 passes and one
worker-poll timing failure; that test passed unchanged when rerun separately.
Focused frontend checks and the real-workspace 32-layer contract passed. Browser
smoke observed Rudy+TW, three candidates, decoded 3D DEM, and restored morphology
counts (41 ridge, 24 valley, 99 drainage). R4 scope remained candidate-only and
explicitly marked differing source A/B as range comparison only. Remote Scout
execution was not retested, and no runtime or route authority was promoted.

### 2026-09-04 Workspace-owned regional DEM preparation

Both endpoints in the original failed A/B request were inside the route bbox.
The failure was a preparation-contract mismatch: the terrain-feature DEM had
only a 250 m margin, while arbitrary A/B analysis requested 1,000 m. Endpoint
containment alone does not prove containment of the buffered analysis extent.

The normal preparation path now stores a separate regional GeoTIFF plus typed
manifest under `outputs/terrain/dem/<identity>/`. Default preparation covers
the complete route bbox plus 5,000 m and two native cells of alignment guard.
The existing 250 m morphology surface and route relevance filters are unchanged.
Per-request TRH clipping remains bounded by its actual A/B and requested margin.

`terrain_workspace_dem_manifest_ref` and its hash bind the prepared raster to
the project, current terrain parent, parent DEM, coverage summary, original
raster hash, CRS and native resolution. The backend prefers this file before
the legacy full-raster recovery path. A present but invalid or insufficient
workspace preparation fails closed, without falling back to another DEM.
Successful cached use does not require the original external material file;
the immutable source declaration, local parent, output hash and any local CRS
evidence snapshot must still validate. Changed source declarations require
preparation again.

Backfill an existing workspace without rebuilding morphology, R1-R3 or R4:

```bash
./venv/bin/python -m workspace_terrain_dem --project-root <workspace-project-root>
```

The GDAL adapter uses an outward, source-grid-aligned clip with `-epo`, without
resampling, filling gaps, or changing source resolution. It counts every cell
through GDAL XYZ export; rounded valid-percent statistics are not sufficient.
CRS mismatches normally fail closed. An unidentifiable WGS84/TM121 header is
resolved only when the registered ISO provider metadata declares EPSG:3826 and
all projection parameters, axis directions and units match. The derived clip's
CRS tag is then normalized explicitly, with the original WKT, exact commands,
provider XML snapshot/hash and decision retained. The original raster is never
modified; recognized conflicting CRSs or unmatched metadata are rejected.

Local Dongqing receipt `e8a985456305ac9d09939754d7937dc547c8b845e1f15ea15019fb2c88a82dd4`
contains a 2,274 by 1,759 native 20 m grid: 3,999,966 finite cells, zero NoData,
11,796,504 GeoTIFF bytes. EPSG:3826 bounds are
`237430,2575990,282910,2611170` (min x, min y, max x, max y). The active
`be8797bfcd83` route result and all existing R4 source/review hashes were retained.
This is local preparation evidence; remote Scout execution is not newly qualified.

Verification retained the exact original failed A/B and 1,000 m analysis margin:
the backend selected `workspace_prepared_dem`, and GDAL produced 312 x 199 cells,
all 62,088 finite with zero NoData. Repeating preparation reused the same local
manifest/hash. The related preparation, R4 and backend suite passed 159 tests;
the final focused DEM/backend run passed 47 tests, and the real-workspace
32-layer contract passed. The existing Navigation display projection was
refreshed after its input fingerprint was found stale; this did not regenerate
or overwrite the active hypotheses or human review.

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
| Historical narrative | Wording may be old, ambiguous, incomplete, GPS-shifted, or refer to a route that changed; interpretation confidence is not current-ground truth. |
| Reviewed point anchors | Human review confirms only the selected map interpretation; point placement error and feature ambiguity remain possible. |
| Reviewed local-friction preference | A lower multiplier only expresses the reviewed narrative as a bounded model preference. It does not confirm terrain condition, passage, or the historical account. |
| Saddle proxy | A ridge-local elevation minimum is only a DEM-derived saddle candidate. It does not confirm a named saddle, route junction, tread, or usable crossing. |
| Sequence ranking | Proximity to a linear A/B narrative-sequence reference orders review candidates only. It is not a route trace or proof that the historical sequence occurred there. |
| Candidate corridor overlap | Overlap is measured against one selected, hash-bound terrain-model corridor and only orders human-review candidates. Zero overlap does not disprove the narrative, and high overlap does not confirm a trail, historical route, passage, or correct anchor. |
| Scout-host execution | Isolated aarch64 execution is proven for one real 20 m DEM workload. Permanent service deployment, restart/runbook qualification, and exact GRASS 8.5/8.4 parity remain UNKNOWN. |

Resolution class is never an overall safety confidence score. A finer DEM may
support finer terrain-form candidates, but it still cannot establish current
passage, legal access, or operational safety.

## 13. Next recommended phase

The next highest-value phase is to complete human map-point review and qualify
the full R4 path on the real 1148 saddle to Iroko workspace on both hosts. The AI
and worker must not synthesize this review. Then add spatial-diversity constraints when two
profiles collapse onto the same optimum, and compute a separately bound corridor
for each profile. After that, add versioned roughness, curvature, ridge/valley,
geomorphon, and TEII evidence one source at a time with synthetic-terrain and
real-workspace regression tests. The implemented narrative and GPX tools remain
candidate/review capabilities and have no GIS safety, passage, legal-access, or
GPX-correction authority.
