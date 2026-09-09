# Scout Pretrip Full Preparation Runbook

## Purpose

This is the no-skip operator runbook for rebuilding a Scout pretrip workspace
from GPX material through runnable admin UI layers.

Use this file when a rerun must include all of:

- GPX import;
- route-corridor map preparation;
- Overpass vector fetch and segment alignment;
- workspace-owned imagery, Rudy, Rudy+TW, relief, geology, Topo 5K, forest, and
  default historical-map tile cache seeding with TTL behavior;
- OCR and raster label adapter output;
- route context, K anchors, mileage tag alignment;
- terrain/risk/MCP/Boss synthesis;
- Scout admin map layer gates and browser smoke checks.

If any required step is skipped, report the run as partial.

### 2026-09-09 Golden r9 live findings: final layer state and CWA route binding

The new G1 completed real QGIS/GRASS and produced seven MCP candidates, but
the final preparation manifest retained the initial MCP `missing_source` row.
Updating project refs alone is insufficient: rebuild the layer's verified
source refs, counts and lifecycle before publishing the final aggregates and
map projection. Preserve collection/alignment failures and genuine warnings;
do not remove the Overpass TTL warning together with the stale MCP warning.

The same live run exposed `rainfall projection route identity mismatch` at the
compact project endpoint. Rainfall products were created against the importer
segment geometry before the later Overpass geometry became the active CWA
route. Keep the route-identity validator strict. Bind route-dependent weather
processing to the final geometry, or truly reproject the original source data;
changing only artifact hashes is invalid. A successful 33-layer verifier does
not replace the actual project API and six-page browser check.

The r10 repair refreshes the MCP layer from the actual current collection and
late-alignment outputs. Complete preparation defers numeric rainfall grids and
weather imagery until that final alignment is durable; scalar weather remains
early and connected refresh retains its immediate route jobs. Verify each
published artifact and pair with the existing strict route validators. Publish
child failures to the evidence, project status, environmental gaps and layer
lifecycle together; never mark retained stale weather as current. The 22 focused
tests passed on one frozen source, including late alignment, stale/mixed output
rejection, fetch failures, MCP integration and connected-refresh compatibility.
Real Dashboard qualification is a separate gate.

The r10 real G1 confirms both fixes: MCP layer is current, the compact project
endpoint returns 200 with the final aligned rainfall route, and the fresh PBF
clears the genuine TTL warning. One new explicit gap remains: full Dashboard
preparation does not supply the server-imagery capability attestation that the
connected-refresh entrypoint supplies. Both r9 targets and r10 G1 fail before
the imagery job lock/provider call, recording a RuntimeError with an empty
safe-summary reason. Fix the trusted full-preparation entrypoint and expose a
fixed guard error code; preserve the host, profile and network guards. Do not
classify an empty RuntimeError as an upstream outage. Preserve the failed
attempt and resume the same durable job after loading the repair.

The trusted `prepare_imported_workspace` wrapper now supplies this declaration
only after validating a mac-workstation request that explicitly requests imagery
and permits explicit network fetch. Public preparation options cannot set the
declaration. The lower-level CLI primitive, host/profile checks and cross-process
job lock keep their existing behavior. Known imagery guard failures publish a
fixed allowlisted error code, while arbitrary exception text remains excluded.
The 31 focused capability, denial, diagnostic and final-route tests pass; actual
Resume and final imagery outputs must still be checked in the target workspace.

The older PBF is genuinely outside its 30-day TTL. Qualification acquired a
new dated public snapshot with a verified upstream MD5 and local SHA256. Use
a new material declaration and a new import identity; do not replace sources
already bound by an existing job or manufacture a newer mtime for old data.
Preserve the old job, receipts and source files for recovery evidence.

While a large preparation is active, inspect its durable job and newest raw
tile timestamps before declaring a stall. The r9 G2 remained in `prepare`
while imagery tiles continued arriving. Do not start duplicate workers or
interrupt useful work merely because the coarse stage has not changed.

### 2026-09-09 Golden r9: raw MCP compilation and recovery provenance

The old New Import path could create GPX/CP artifacts but had no producer for a
real MCP evidence set. Preparation now compiles the original source-manifest
GPX documents and the actual OSM snapshot, with optional fetched public text
declared by `material_manifest.json` at
`sources.mcp.supplemental_evidence_ref`. This is a raw input package; do not
copy a previous workspace's candidates or reviews into a new import.

The compiler publishes four refs under `outputs/mcp`: named-point evidence,
MCP candidates, CP support reconciliation and the collection receipt. It runs
before the final MCP alignment, OCR/context collection, Boss synthesis and
mileage/timing/architecture stages. Keep the existing 11-document, 5-percent
mention, 1000 m spacing and 250 m CP-support rules. GPX waypoints or OSM nodes
are records within documents, not independent website pages. Same-activity
diaries and GPX dependencies are deduplicated. Place-type gaps discovered on
real data included named pools and saddles; classify only explicit names,
without inventing coordinates or ambiguous aliases.

The durable preparation job binds the package, readable text, raw HTML and
acquisition receipts before starting. Resume verifies those inputs again
before any writes. A package may be reused by a new QA ID/Clone only through
an exact raw Golden SHA binding; its acquisition project remains provenance,
and no Permission review is transferred.

Each preparation manifest records its starting/current geometry and timing
fingerprints, plus hashes of projections produced or revalidated in that run.
Compare immutable inputs for drift; regenerated recorded-pace metadata alone
must not be counted as changed raw input. Failed or retained projections are
not marked current. The shared Dashboard analysis subject consumes these
receipts and the immutable Permission Rebuild receipt.

The default outer QGIS preparation wait now observes terminal completion
without a Scout cumulative deadline; explicit deadlines remain supported for
operator requests/fault tests. Health preflight defaults to 10 attempts.
Underlying provider/worker limits remain independently observable. Reuse the
task's existing authenticated QGIS worker; wait for a Dashboard listener before
browser navigation, and never multiply servers when startup is slow.

Real source-only trial: G1 32 accepted documents / 7 MCP; G2 14 / 47, both with
no compiler gap. This does not certify the full import/preparation/UI chain.
See [r9 qualification progress](scout-golden-gpx-g1-g6-qualification-20260909.md#r9-整合與重驗進度).

### 2026-09-07 Route Context recovery for the exact legacy newImport workspace

The reported workspace was `dongqing_batongguan_historic_trail_newImport`.
Checking `chilai_nanhua_day1_scoutAI` or the older Dongqing `scoutAI` workspace
does not verify this target. Always bind the Dashboard URL, status endpoint,
project metadata and rendered HTML to the exact requested project id.

Its 2026-08-25 collection retained 39 context points, but the pack, source
manifest and evidence had `route_context_briefing_ref: null`; the briefing
directory did not exist. This is the legacy omitted-HTML preparation defect
described in the 2026-08-29 lessons below. It was not a rejected semantic
review. The current preparation path already requests `write_briefing=True`;
that change does not backfill older workspaces.

Bounded recovery rendered the existing project-bound points, source manifest,
media manifest, crawl seeds and route summary through the existing deterministic
briefing renderer. Only the missing HTML and its refs in `project.json`, the
pack, source manifest and evidence were written. Original metadata copies and
input/output hashes are recorded in
`artifacts/route-context-recovery-20260907-newImport/restoration-receipt.json`.
The associated `restore.py` records this exact recovery and refuses to overwrite
an existing briefing; it is not a general preparation or regeneration command.
No GPX import, layer preparation, QGIS restart, cloud request or live source
fetch was performed. Context points, media and crawl seeds retained their hashes.

The recovered HTML renders seven eligible named points from the 39 stored
candidates. At that first recovery the target had zero fetched web evidence
items and zero photos; current status and itinerary evidence were missing. The
renderer now shows missing official evidence when P0 count is zero instead of
claiming historical support from absent sources. Recovery is artifact
availability, not semantic-review approval or current route verification.

The exact target's status endpoint returned `available`, its HTML returned 200
and matched the local bytes, and `content_reviewed=false` remained truthful.
The earlier Dashboard repair also starts briefing reads independently of
workspace/variants loading and removes the extra 2 px in iframe sizing that
otherwise creates a ResizeObserver growth loop. Do not add viewport padding
to a measurement that already includes the iframe viewport height.

Additional browser verification covered the canonical renderer's embedded
chapter controls: use the Dashboard workspace scroller for viewport, current
chapter and section jumps; the expanded iframe viewport otherwise appears to
be permanently at its last chapter. Measure body content for height changes
when switching data/briefing modes. Background project and variants completion
must update the outer status without replacing a matching loaded iframe.
The final mouse smoke advanced from the first chapter to the days-evidence
section on the exact newImport workspace. Full data mode remains available,
with missing official sources, photos and current status explicitly shown.

#### 2026-09-07 Researched first edition after the reader rejected the empty briefing

Restoring an HTML file does not complete a request for a useful briefing. The
reader rejected the gap-only report. The established Codex skill and Scout
`route-context-intelligence` manifest already require actual search, selected
source fetches, attributed images, historical itinerary, logistics and six
context layers. This legacy workspace lacked the typed regeneration input
expected by the Dashboard's quality cycle.

Use the existing skill's evidence-bound regeneration branch for this case.
The exact-workspace handoff is recorded under
`artifacts/route-context-first-edition-20260907/`: source research, live status
query receipt, curated image references, assembly/collection scripts and
`preparation-receipt.json`. It materialized 20 public pages (14 P0, 6 P1),
16 image references and a nine-day historical itinerary. Original route
summary, context points, mileage anchors and crawl seeds retained their hashes.
The canonical briefing remains the responsibility of the existing Dashboard
generation plus independent hash-bound semantic-review cycle.

Specific failures and corrections:

- A successful HTTP status can contain only an access challenge. Reject the
  body as missing evidence; the first edition omitted the blocked public-bus
  page and its detailed reservation claims from the collector-bound packet.
- Archive image endpoints use `?name=...jpg&folder=...`. Check the explicit
  filename against the existing image/chrome gate and retain name/folder in
  deduplication. Dropping every query string incorrectly merged four different
  historical images into one.
- The Dashboard still passes the legacy bare DeepSeek model ID. Chat-model
  construction accepted its configured OpenRouter endpoint, but native research
  policy rejected the missing provider prefix before any search. Both the
  editorial and review callers now resolve the OpenRouter research identity
  from that endpoint without changing the selected model or credentials.
- An answer-first document needs evidence-backed conclusions before unresolved
  tasks. The evidence renderer now leads with route identity, historical
  schedule, transport and application answers, includes attributed imagery and
  draws the bound route/profile. It avoids asserting old MCP mileage labels as
  the journey order and removes fixed route/year/category assumptions.
- Browser inspection caught two additional rendering defects: fixed section
  numbers disagreed with the model's reading order, and `object-fit: cover`
  cropped map edges and portrait photos. Number sections from the accepted
  editorial order, display gallery images in full, give maps a full-width row,
  and link each original image. Keep the independent review bound to the final
  HTML after these corrections.
- Use the existing media `source_family=historical_map_reference` when choosing
  the wide map layout; these two source captions do not contain the word
  "map". Reject an editorial heading claiming official imagery when the
  workspace has no P0 images, just as P2 imagery labels require P2 images.
- Keep the virtual-environment executable path when reloading the local
  Dashboard. Resolving its Python symlink to the base interpreter loses the
  installed Scout package. Wait for the listener/status endpoint before browser
  actions; importing the full local Dashboard stack can take around a minute.

The route identity remains 清代八通關古道, with the northern-bank eastern
alignment; the southern-bank Japanese-era itinerary is not a substitute.
Current entry restrictions are based on the 2026-08-27 closure, 2026-08-28
partial reopening, direct route-note reads and the 2026-09-07 status query.
Historical photos and day counts are not a claim of current access.

The first live Dashboard cycle returned an independent content `PASS` (4/5)
after two editorial attempts. Its retained receipt records 2 web-search calls
and 2 web-fetch calls; the independent reviewer performed an additional fetch.
Browser operation confirmed the embedded historical-itinerary jump, 16 distinct
loaded image URLs (17 image elements including the repeated hero), and the two
bound-GPX figures. The pre-visual-correction copy and receipts are retained in
`reviewed-before-visual-fix/`; the final promoted hash and current API review
state belong in `final-qualification.json`, generated by
`verify_first_edition.py` only after the last review passes.

Final first edition: the Dashboard promoted SHA-256
`c23ed6ed70700a16d8a7e7c04b4f2642290bd09530a9a8355625ff509c4250d8`
after an independent `PASS` (4/5). `final-qualification.json` verifies the
canonical, input, skill, review-packet and project review bindings;
`browser-qualification.json` records the reloaded exact-workspace page, actual
chapter click, 17 loaded image elements / 16 unique images, two full-width
source maps, and the route/profile figures. Focused Python checks passed 28
generation/review/media cases and 3 Dashboard cases; `pnpm lint`, `pnpm
typecheck` and `pnpm test` also passed. The reviewer left only minor source-
excerpt/checklist-link suggestions for a later edition.

The live generation/review cycle can take several minutes per editorial
attempt. Route Context now explicitly opts out of the browser's fixed request
timer; other POST calls retain their timeouts. This avoids presenting a still-
running quality cycle as failed solely because ten minutes elapsed. Model and
provider failures continue to surface normally. No GPX import, map preparation,
worker restart, hardware action or external publication was performed.

### 2026-09-04 Architecture Historical Return Timing Repair

An available candidate mission graph is not historical Reversibility analysis.
The old fingerprint rendered graph/ETA status strings instead of CP-level costs.
Keep the workspace-first fetch order and the collapsed supporting evidence panels.
The historical definition now lives in
`docs/specs/pretrip-reference-pace-energy-analysis.md`: reverse-direction return
cost, historical moving-day P50, explicit prior camp anchors, and a separate
forward `Next CP · Avg` lane. Reviewed topology does not gate these statistics.

New root causes found during the real-workspace run:

- A 20 m individual-step threshold mislabeled dense reverse samples as forward.
  Direction now follows nonzero matched progress; spatial proximity leads route
  matching, with continuity resolving coincident branches.
- Short observations were extrapolated to complete bins but called observed.
  Partial coverage is explicitly estimated; fragments in the same passage are
  aggregated before averaging so file segmentation does not change mean pace.
- Duplicate files and overlapping time intervals inflated daily sample weight.
  Deduplicate file hashes and union eligible intervals within each GPX before
  splitting at local midnight. The weather artifact's timezone may be an
  importer default, not source-GPX timezone metadata.
- Generic rests and camp water-access notes are not overnight anchors. Use only
  explicit camp labels, reject off-route/adjacent points and keep provenance.
- The last regularly spaced risk sample can precede the true filtered GPX finish
  (about 7 m in Dongqing). Include the primary GPX's full cumulative distance in
  the time axis; otherwise the final CP lies outside all timing bins.

Bounded repair command (no GPX import, terrain worker or weather refresh):

```bash
rtk proxy ./venv/bin/python pretrip_architecture_preparation.py --project-root /path/to/workspace --force --json
```

This refreshes reference pace JSON/GeoJSON, Architecture manifest and their
project refs. The input fingerprint includes timing-policy version, camp notes
and timezone evidence. A running Python Dashboard needs the new projection code;
use an isolated free port for verification when existing servers are in use.
`tools/dashboard_architecture_return_smoke.js` exercises actual desktop/mobile
controls, return/next-CP selection, decision/reset marks and the map lens using
read-only browser requests. On this Mac it uses installed Chrome, because the
Playwright-managed browser binary is absent.

### 2026-09-04 Architecture Daily Time Window

Time Window is now a separate forward resource account: local departure to the
user's fixed 18:00 cutoff, less accumulated historical forward movement costs.
The old next-CP average remains a distinct lane, and historical moving-day P50
still belongs to return-cost comparison, not this daylight proxy.

The Dongqing filtered primary GPX contains a coherent nine-day sequence. Its
initial and post-overnight first records provide candidate departure clocks;
neither `project.route_days=1`, all camp labels, nor local midnight provides this
schedule. Original GPX timestamp reversals and multi-year contaminated rest
durations must not create resets. Short spatial gaps between overnight endpoints
remain unknown schedule spans. No current camp safety or actual sunset is proven.

Use the bounded Architecture command above. The input fingerprint now also
includes the daily-departure/countdown policy. This reuses existing local GPX and
timezone evidence without importing GPX, rebuilding terrain, or fetching weather.
The browser smoke additionally operates the Time Window mode/lens, daily reset
anchors, desktop keyboard selection and mobile balance inspector, checking
`A = T - consumed` and `arrival margin = A - forward-to-safe` against live data.

The bounded Dongqing proof produced 9 daily resets, 250 available reverse-cost
anchors and 257/258 available Time Window anchors. One original CP lies in an
overnight recording gap and intentionally remains unknown. The 8 inferred
overnight stops join 23 named camp candidates in both directional target sets,
without being promoted to verified camps. Daily departures remain independent
reset events. Distance conversion does not alter any duration or clock.

Keep exact zero-width data cells at day ends separate from transparent minimum
hit targets, so a 5 m unknown gap is not painted over by a 2 px data minimum.
Keyboard traversal excludes null-distance anchors just as the visible lanes do.
Desktop/mobile controls, countdown arithmetic and map colors were exercised on
an isolated 9187 preview; existing Dashboard processes were not restarted. This
is working-prototype evidence, not official full Dashboard qualification or a
promoted safety/runtime baseline.

### 2026-08-25 Workspace raster-cache preparation repair

The blank-layer report on
`dongqing_batongguan_historic_trail_newImport_v2` exposed a preparation and
renderer contract mismatch:

- Map preparation seeded only one cache namespace and used Rudy+TW as the
  `imagery` source even when the project imagery source was NLSC PHOTO2. The
  cache path therefore did not preserve layer/source identity.
- MapLibre registered only `rudy-twmap` and `osm`; the controls for imagery,
  Rudy, relief, geology, Topo 5K, and forest had no MapLibre raster source.
- The normal page path silently used runtime WMTS URLs, while OSM's offline SVG
  fallback was presented as a raster tile and could fail MapLibre decoding.

Required behavior from this repair onward:

1. A connected clone or map-preparation run seeds eight independent allowlisted
   raster namespaces at zoom 5-14 under
   `<project-root>/cache/raster-tiles/<project-id>/<layer-id>/...` and writes one
   plan plus one seed manifest per layer to the project workspace.
2. `project.json` records all eight refs in `raster_layer_manifest_refs` and a
   bundle ref. NLSC/project imagery remains `imagery`; Rudy+TW remains the OCR
   source in its own `rudy-twmap` namespace.
3. Dashboard load is cache-only. It must create all eight MapLibre raster
   sources through the same-origin Scout tile API and must not fetch WMTS merely
   because a layer is checked.
4. The Layers panel exposes an explicit raster-refresh control. Only that
   operator action may add `native=1&refresh=1`; refreshed bytes replace the
   workspace tile, while a failed refresh retains the last cached tile.
5. Geology remains refreshable through this explicit control. Weather/CWA APIs
   retain their connected refresh workflow and are not frozen by raster seeding.
6. Public OpenStreetMap tiles are not bulk-prefetched. Use a local OSM extract
   when available; otherwise the local OSM raster endpoint returns a valid
   transparent PNG so OSM failure cannot blank or poison the other raster and
   vector layers.
7. Raster-label OCR cache misses run with a bounded worker pool (default at most
   four workers and never more than the available tile count). OCR computation
   may run concurrently, but cache JSON is serialized by the caller so two
   workers cannot corrupt the same artifact. Set
   `SCOUT_RASTER_LABEL_OCR_WORKERS` only for an explicit hardware-specific
   override; hash cache hits remain the first path on every rerun.
8. WMTS seeding retries each failed tile up to five times in the same
   preparation request with bounded backoff. This limit was raised after the
   2026-08-25 Dongqing run recovered three transient failures but still left
   Relief `z5/26/13` missing after its third timeout. The seed manifest records
   attempt, recovery, and final failure counts; the explicit post-load refresh
   remains an operator update path, not a substitute for preparation seeding.

This is the normal one-pass import/preparation contract. A `_v2` workspace is
not a required second stage; suffixes remain useful only for a deliberate clean
comparison or when preserving an already-created target.

### 2026-08-24 Dashboard clean-clone preparation repair

Before creating `dongqing_batongguan_historic_trail_newImport`, the Dashboard
path had three preparation drifts that must not be repeated:

- Workspace `Clone` only appended an intent receipt and performed no clone.
  The repaired action must refuse an existing target, read the source inbox GPX
  corpus, run a clean import under the new project id, and then run map
  preparation. It must not copy stale project-bound artifacts or mutate the
  source workspace.
- The importer and Dashboard defaults exposed only 18 layers even though this
  runbook requires the 23 preparation layers. The shared default must include
  `imagery`, `pois`, `hazards`, `corridors`, `retreat`, and `route-notes` in
  addition to the existing route, terrain, risk, environment, and MCP layers.
- Connected CWA/GEE/Overpass refresh previously republished the six dynamic
  layers as the canonical layer-preparation manifest. A connected refresh must
  update provider-backed evidence without replacing the complete 23-layer
  preparation manifest. Weather remains refreshable after import. Geology is a
  runtime provider layer and must not be frozen into, or falsely represented as
  produced by, GPX import or map preparation.
- Source MCP named-point evidence is project-bound. Clone preparation must load
  the typed evidence, verify the source identity, create an ephemeral copy with
  only `project_id` rebound to the target, and record both hashes. Direct reuse
  fails closed; broad text replacement is not an acceptable identity change.
- The current local OSM PBF conversion path requires the Python `osmium`
  package in the same interpreter that runs Dashboard preparation. The
  `osmium` CLI alone is insufficient because the extracted PBF still passes
  through the Python streaming/filter stage. A clean Dashboard clone with a
  configured local PBF must fail before import when that package is unavailable;
  Overpass is not a substitute for the missing workspace OSM render extract.
- Dashboard clone execution runs in an API worker thread. Signal-based
  post-process timers must be armed only on the main interpreter thread;
  otherwise Boss/route-pressure and mileage alignment fail even though their
  inputs are ready. Worker-thread preparation runs those bounded candidate
  enrichments without a process signal timer.
- Same-run risk refs must be persisted before Overpass route alignment reloads
  `project.json`. Reference-segment timing must also be produced before route
  architecture so the first Dashboard projection can consume every available
  historical GPX timing measurement.
- Overpass may terminate a large corridor response with `IncompleteRead` or a
  transient connection reset. The explicit fetch path retries these transport
  failures up to three total attempts with bounded backoff; malformed evidence
  is never accepted from a partial response.
- A clean Dashboard clone must prewarm all eight allowlisted route raster layers
  at zoom 5-14 before raster-label OCR. Each target owns its cache under the
  project workspace, never inside the repository. Rudy+TW is the OCR source but
  does not replace project imagery. Geology updates remain available through
  the explicit post-load refresh control. Tile count is route-bbox specific: do
  not copy Chilai's count of 31 into a longer route as a fixed target.
- `pytesseract` is an optional wrapper, not the OCR capability boundary. When
  the allowlisted `tesseract` binary and requested language data are available,
  preparation may consume its TSV output directly with a subprocess timeout and
  no shell. If neither wrapper nor CLI is available, retain the typed
  `blocked_dependency_missing` result; never fabricate labels.
- OCR completion and raw label count do not prove semantic map-label quality.
  The 2026-08-24 Dongqing v2 run processed all 402 cached tiles without timeout
  and emitted 16 labels, but review found that most were low-zoom Rudy map
  attribution fragments; the current Chilai labels have the same limitation.

### 2026-08-26 OSM PBF Dashboard runtime binding repair

`dongqing_batongguan_historic_trail_newImport` exposed a runtime dependency
drift: `taiwan-260624.osm.pbf` was discovered and hashed, but clone recorded
`local_pbf_skipped_parser_unavailable`, completed through Overpass, and left
`osm_pbf_render_geojson_ref` absent. The live OSM toggle consequently had no
source-backed vector layer.

The parser was already installed in a legacy repository venv and in the
separate `scout-osmium` micromamba environment. The live `9099` process used the
system Python 3.12 interpreter, so neither installation was importable. PATH or
an `osmium` executable alone cannot repair that interpreter mismatch.

Use the project-owned runtime consistently:

```bash
tools/setup_dashboard_workspace_runtime.sh
tools/run_dashboard_workspace.sh --port 9099 \
  --workspace-root /Users/alexwang0315/workspace
```

The setup command is idempotent and installs the `pretrip-workstation` optional
extra into `./venv`; it is not part of every launch. A stored `pyproject.toml`
hash skips package installation entirely when the configured runtime is already
complete and unchanged. Setup also creates persistent
`~/.local/bin/scout-dashboard` and `~/.local/bin/osmium` shortcuts plus the
project-local `./venv/bin/osmium` binding. It also owns the fixed
`~/.local/share/scout-tools/micromamba/envs/scout-grass` environment and creates
`~/.local/bin/grass` plus `./venv/bin/grass` bindings. The run command never
installs packages, refuses an incomplete runtime, and puts `./venv/bin` first
on its process PATH. Workspace clone now also refuses a configured PBF before
creating the target when Python `osmium` is unavailable.

When processing `taiwan-260624.osm.pbf`, retain its source hash and stale
snapshot warning. The operator-approved existing snapshot remains usable, but
must not be represented as a fresh Taiwan extract.
  Keep them named `candidate labels`, require review, and do not promote them to
  named points, K anchors, hazards, or safety truth without a later quality
  filter or higher-resolution region OCR pass.
- Clone import may add unique GPX files only from a `gpx_corpus` path explicitly
  declared by the material manifest. Deduplicate additions by SHA-256 and retain
  source provenance. A route with four declared reference tracks must remain
  four rather than being inflated to match another workspace's count; KML map
  sheets are not timed reference GPX tracks.

For this clean-clone path, the source inbox GPX checksums and the material-root
manifest are inputs. The new target receives its own project identity and clone
receipt. GRASS/QGIS ridge, valley, and flow-channel artifacts remain separate,
route-bound candidate evidence; never copy an older terrain feature stack into
a new route scope merely to fill a Dashboard panel.

## Required Specs To Read First

Before changing commands or declaring a workspace complete, read these specs:

- `docs/specs/scout-pretrip-preparation-pipeline.md`
- `docs/specs/pretrip-route-corridor-map-preparation.md`
- `docs/specs/pretrip-layer-preparation.md`
- `docs/specs/scout-admin-map-layer-contract.md`
- `docs/specs/pre-trip-planning-admin.md`

The non-negotiable spatial rule comes from
`pretrip-route-corridor-map-preparation`:

```text
GPX importer output defines the route scope.
Map preparation fetches by bbox when needed.
Map preparation filters and interprets by along-track corridor.
Pydantic AI receives only source-backed, route-relevant evidence bundles.
```

In practical terms:

- `bbox_wgs84` is only the acquisition boundary for tiles, DEM/DTM, Overpass,
  weather, and source material.
- Golden route plus reference tracks define the along-track semantic corridor.
- Default corridor values are `route_corridor_m=500` and
  `reference_track_corridor_m=300`.
- Segment display, Overpass projection, risk ribbon, route context, K anchors,
  MCP, and Boss evidence must be route-corridor evidence, not global bbox
  evidence.
- Risk generation must receive the same `route_corridor_m` used by map
  preparation. Do not let the risk package fall back to a narrow default such
  as 35 m during a full pretrip route-corridor run.
- Risk route-base generation must project reference route progress to nearest
  Overpass/local OSM PBF trail corridor candidates. Fallback GPX samples may
  remain as explicit candidate points, but their provenance must say they are
  `reference_gpx_gap_fallback`, not Overpass-backed route evidence.
- Baseline risk ribbon and calibrated heatmap line overlays may connect only
  adjacent samples whose `route_base_source` is `overpass_projection` and whose
  geometry jump is within the accepted route-base segment threshold. Do not
  connect fallback samples into straight lines across Overpass gaps.

## Local Skills Available

The Skills CLI is optional. On this machine, `npx`/`npm` were not available, so
external `npx skills find ...` could not be used.

Installed local skills that help this pipeline:

- `.agents/skills/scout-pretrip-import-preparation/SKILL.md`
  - Use for the full GPX import, map preparation, Overpass alignment, tile
    cache TTL, OCR, K anchors, mileage tags, durable evidence replay, and
    workspace/admin verification loop described by this runbook.
- `skills/scout/pretrip-import-preparation.yaml`
  - Scout runtime/Pydantic AI v2 skill manifest. Use when Scout AI needs to ask
    the user for missing raw-data paths or project naming, require operator
    approval, then invoke deterministic pretrip import/preparation tools.
- `.agents/skills/scout-route-context-briefing/SKILL.md`
  - Use after import/map/OCR when building route context artifacts and briefing
    HTML.
- `.agents/skills/scout-route-pressure-intelligence/SKILL.md`
  - Use when public P0/P1 pressure evidence should inform Route Boss Demand.
- `~/.codex/skills/scout-ai-agent-development/SKILL.md`
  - Use for Scout/Pydantic AI development, tests, and safety boundary reviews.

This runbook remains the source-of-truth operator checklist. The
`scout-pretrip-import-preparation` skill points Codex back to this runbook and
the repo tools so the executable workflow does not fork.

## Variables

Set these once per run:

```bash
export PROJECT_ID=chilai_nanhua_day1
export WORKSPACE_ROOT=/tmp/scout-local-pretrip-workspaces
export PROJECT_ROOT="$WORKSPACE_ROOT/$PROJECT_ID"
export MATERIAL_ROOT=/private/tmp/scout-local-materials/pretrip/chilai_nanhua_day1
export GOLDEN_GPX="$MATERIAL_ROOT/sources/gpx/golden/<golden-route>.gpx"
export REFERENCE_DIR="$MATERIAL_ROOT/sources/gpx/reference"
export RASTER_TILE_CACHE_ROOT=/tmp/scout-local-data/raster-tiles
export DURABLE_EVIDENCE_SOURCE_ROOT=
export ADMIN_BASE_URL=http://127.0.0.1:9099
```

Credential loading:

- On this local Mac, Scout CWA/GEE credentials live in
  `/Users/alexwang0315/scout-fusion/.env`. Manual import/preparation commands
  must load this file, or set `SCOUT_ENV_FILE=/Users/alexwang0315/scout-fusion/.env`
  before invoking `tools/rebuild_pretrip_workspace_on_scout.sh`.
- Do not print or persist secret values. It is acceptable to log whether the
  env file was loaded and whether required credential names are present.
- If CWA/GEE show `missing_credentials` during a local run, first check env-file
  loading before concluding the keys are absent.

For the current local Nengao/Andongjun workspace, verify the golden GPX path
before running import. Do not assume a file in `reference/` is golden only
because its name is similar.

## Step 0: Dependency And Material Preflight

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import importlib.util
from pathlib import Path

checks = {
    "numpy": importlib.util.find_spec("numpy") is not None,
    "pytesseract": importlib.util.find_spec("pytesseract") is not None,
    "PIL": importlib.util.find_spec("PIL") is not None,
}
for name, ok in checks.items():
    print(f"{name}: {'PASS' if ok else 'FAIL'}")

for name in ("PROJECT_ROOT", "MATERIAL_ROOT", "GOLDEN_GPX", "REFERENCE_DIR"):
    import os
    value = os.environ.get(name, "")
    print(f"{name}: {value} exists={Path(value).exists() if value else False}")
PY

tesseract --version
```

Required result:

- `numpy: PASS` because risk-score/ribbon/heatmap generation imports it
- `pytesseract: PASS`
- `PIL: PASS`
- `tesseract --version` exits `0`
- `GOLDEN_GPX` exists and is the intended golden route
- `REFERENCE_DIR` exists and contains reference GPX files

If Tesseract or `pytesseract` is missing, install it before continuing. Do not
classify the run as complete with a blocked OCR dependency.

If `numpy` is missing in the local workspace venv, install it before continuing:

```bash
./venv/bin/python -m pip install numpy
```

This is an environment preflight for the current local rebuild. Do not claim a
complete risk run when `project.json` contains
`risk_score_generation_error: No module named 'numpy'`.

## Step 0.25: Terrain Benchmark Before Capability Classification

Use the Scout terrain benchmark before promoting a terrain operation into a
Pi-compatible baseline, Pi-bounded operation, or advanced workstation feature.
This benchmark records execution cost and input size only. It does not validate
terrain correctness, route truth, hazard truth, navigability, or safety.

Run on the actual Scout Raspberry Pi when classifying Pi feasibility:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/scout_terrain_benchmark.py \
  --project-root "$PROJECT_ROOT" \
  --project-id "$PROJECT_ID" \
  --iterations 3 \
  --synthetic-dem-sizes 64,128 \
  --probe-external-tools \
  --output "$PROJECT_ROOT/outputs/terrain_benchmark.json"
```

Valid interpretation:

- `workspace_preparation_metadata` measures reading the existing
  `project.json`, DTM coverage, segment coverage, terrain visualization, and
  prepared terrain/risk refs. It does not rerun full layer preparation.
- `synthetic_python_terrain_kernel` measures the pure Python/NumPy Scout risk
  engine terrain kernel on synthetic DEM grids. Synthetic results are fixture
  performance evidence only.
- `external_tool_capabilities` is a PATH probe for GRASS/GDAL/QGIS commands
  when requested. The benchmark does not execute those tools.
- A Mac or other non-Pi run is host evidence only. It must not be used as proof
  that the same operation is Pi-compatible.
- Every benchmark report keeps `candidate_only=true`,
  `runtime_safety_truth=false`, `operational=false`, and `benchmark_only=true`.

Use the resulting artifact to decide the next implementation tier:

```text
Pi-compatible baseline
  Small route-corridor preparation and terrain metadata operations that pass on
  the actual Scout Pi.

Pi-bounded terrain evidence
  Operations that pass on the actual Scout Pi only under explicit DEM size,
  corridor, memory, and timeout limits.

Advanced workstation feature
  Operations that fail, time out, show memory pressure, or were not measured on
  the actual Scout Pi. QGIS Desktop/QGIS MCP visual review starts in this tier
  until benchmark evidence proves a narrower Pi-bounded slice.
```

## Step 0.5: Standard Durable Evidence Source

The GPX importer can reconstruct GPX-derived candidates, but it does not by
itself recreate every reviewed or durable admin evidence artifact byte-for-byte
from a fresh project id. Standard workspaces may carry durable evidence such as
baseline risk, calibrated heatmap, attribution diagnostics, route-pressure
profiles, Boss points, OCR/cache output, Overpass alignment, route context,
mileage tag alignment, and reviewed admin refs.

CWA/GEE environment artifacts are explicitly **not durable replay evidence**.
They are time-sensitive current-run snapshots. Every connected preparation run
must refetch CWA and GEE under `network_mode=explicit-fetch` with
`allow_network_fetch`; when credentials or provider access are missing, the run
must write the current blocker/status (`not_available`, `fetch_failed`,
`missing_credentials`, or equivalent) instead of copying older weather,
forecast, SMAP, GPM, or derived environment values from another workspace.
CWA source artifacts and CWA-derived review/model artifacts must also carry
hour-precision timing metadata: API request attempt hour, successful fetch hour
when data was returned, provider forecast/observation valid-from and
valid-until hours when available, `time_precision: hour`, and timezone. A
failed or credential-blocked CWA fetch records the current attempt hour but
must not fill fetch or validity hours with synthetic values.

For a reference-equivalence rebuild, set a read-only source workspace or
materialized durable evidence source before import:

```bash
export DURABLE_EVIDENCE_SOURCE_ROOT=/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1
```

The restore copies only durable evidence files and metadata into the new
workspace. It must not modify the source workspace. In the wrapper flow this
restore happens twice: once immediately after GPX import to provide stable
baseline evidence for map preparation, and once after OCR, Overpass alignment,
route context, and mileage alignment have run. The final restore must not
overwrite freshly generated outputs. It must also skip CWA/GEE refs and
environment-derived metadata even when a durable source workspace contains
them, because those values must reflect the latest provider fetch attempt.

If this variable is empty and the target project id has no prior backup, layer
preparation will generate new overpass-based risk profiles, OCR labels,
environment evidence, route context, and mileage alignment. That is valid
candidate evidence, but it will not be byte/count equivalent to an existing
standard workspace that already has reviewed baseline artifacts.

## Step 1: GPX Import

Run importer first. This may replace the project workspace when `--overwrite`
is used.

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_import \
  --project-id "$PROJECT_ID" \
  --golden-route-gpx "$GOLDEN_GPX" \
  --reference-dir "$REFERENCE_DIR" \
  --workspace-root "$WORKSPACE_ROOT" \
  --profile pi-offline \
  --material-root "$MATERIAL_ROOT" \
  --checkpoint-spacing-m 500 \
  --max-reference-display-points 2500 \
  --max-reasonable-gpx-speed-kmh 120 \
  --max-previous-gpx-speed-ratio 8.0 \
  --import-stage pretrip \
  --overwrite
```

Minimum checks:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
required_refs = [
    "route_evidence_bundle_ref",
    "route_summary_ref",
    "checkpoints_ref",
    "segments_ref",
    "reference_tracks_ref",
    "segment_display_geometry_ref",
    "admin_projection_ref",
    "debug_projection_events_ref",
]
for key in required_refs:
    ref = project.get(key)
    print(key, ref, (root / ref).exists() if ref else False)
PY
```

All refs above must exist before map preparation starts.

## Step 2: Connected Map Preparation

Use connected explicit fetch for in-house pretrip preparation. `no-network` is
for CI, fixture replay, or post-fetch offline validation only.

```bash
SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT="$RASTER_TILE_CACHE_ROOT" \
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_layer_preparation \
  --project-id "$PROJECT_ID" \
  --workspace-root "$WORKSPACE_ROOT" \
  --layers imagery,osm,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,cwa-qpf,soil-moisture,antecedent-rain,cwa-weather,weather,reference-tracks,route,segments,checkpoints,mcp,pois,hazards,corridors,retreat,route-notes \
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
  --imagery-max-zoom 14 \
  --imagery-seed-max-tiles 250
```

This command is the main orchestrator. It should update:

- Overpass raw/evidence/vector refs;
- Overpass route alignment and aligned segment display geometry;
- tile cache plan and manifest;
- raster OCR output;
- raster label adapter output;
- route context points and route mileage K anchors;
- Boss points;
- mileage tag alignment;
- Route Architecture Intelligence mobility artifacts and deterministic readiness
  manifest:
  - `outputs/reference_pace_energy_analysis.json`;
  - `outputs/reference_pace_energy_map.geojson`;
  - `outputs/architecture_preparation_manifest.json`;
- the persisted Navigation & Terrain Intelligence projection at
  `outputs/navigation/navigation_terrain_intelligence.json`;
- layer manifests and admin/debug projections.

Architecture preparation runs after risk/route-pressure and mileage
enrichments. Its `core` stage needs only the historical GPX source index plus
the primary/golden filtered GPX route axis, so a newly imported workspace can
render route structure even before terrain/risk enrichment exists. Its
`enriched` stage adds risk-source and route-pressure evidence. The preparation
manifest hashes every relevant project-local input, records `ready`, `partial`,
`blocked`, or `stale`, and writes the three canonical refs plus aggregate counts
back to `project.json`. Re-running the same inputs reuses the existing
artifacts.

The full rebuild wrapper runs the Architecture command once more after the
final durable-evidence restore and before the spec verifier:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python \
  -m pretrip_architecture_preparation \
  --project-root "$PROJECT_ROOT" \
  --require-enriched \
  --json
```

`--require-enriched` is a full-preparation acceptance gate. A `core/partial`
artifact remains valid for graceful Dashboard browsing, but it does not pass a
completed full rebuild.

When `terrain` is part of an ordinary full preparation, the orchestrator
compiles the navigation projection only after the workspace refs and
post-layer enrichments are available. It records
`navigation_terrain_projection_ref` in `project.json` and
`manifest.navigation_terrain_projection.status=completed`. The artifact is
candidate-only and review-gated; it is not runtime safety truth.

Verify the persisted projection:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
ref = project.get("navigation_terrain_projection_ref")
payload = json.loads((root / ref).read_text()) if ref else {}
print("ref", ref, "exists", bool(ref and (root / ref).exists()))
print("projection_state", payload.get("projection_state"))
print("candidate_only", (payload.get("boundary") or {}).get("candidate_only"))
PY
```

Expected: the ref exists, `projection_state=ready`, and
`candidate_only=true`. If the input fingerprint later becomes stale, the
Dashboard endpoint returns HTTP 202 `preparing` and runs one coalesced
background rebuild; it must not block the browser request on a cold DEM
compilation.

### Optional One-Shot CWA Numeric Rainfall Grid Worker

When `cwa-qpf` is requested with `--profile mac-workstation`,
`--network-mode explicit-fetch`, and `--allow-network-fetch`, the same one-shot
preparation run also fetches CWA `O-B0045-001` and `F-B0046-001`, validates and
georeferences their numeric grids, and stores immutable gzip frames plus the
route projection/trend package under
`outputs/environment/cwa/rainfall/`. This is server-side numeric processing;
Pi/mobile profiles report a blocker and perform no full-grid work.

After the run, verify these refs in `project.json`:

- `cwa_rainfall_grid_manifest_ref`;
- `cwa_qpe_numeric_grid_ref` and `cwa_qpf_numeric_grid_ref`;
- `cwa_rainfall_route_projection_ref`;
- `cwa_rainfall_route_trend_ref` and `team_target_rainfall_trend_ref`.

`cwa_qpf_grid_ref` must remain present and valid for backward compatibility.
The rainfall frames are persistent evidence snapshots but keep
`cacheable=false`, `ttl=0`, and `mustRefetchOnPrepare=true`; never treat the
latest stored frame as fresh without a new explicit run. No recurring ten-
minute fetch is installed by this command alone. Long-term monitoring remains
a separate approval-gated operation; the local Dashboard service-lifetime job
described below is the approved implementation for the current Mac/server.

Treat QPE `-1` and QPF `-99` as provider-invalid/no-data, not zero rainfall.
The route trend samples a 1.5 km route buffer; if no valid QPF cell intersects
that buffer, the correct result is `unknown` with zero paired cells. A blank
QPF map therefore means unavailable forecast coverage, not a dry-route claim.

Current position and target evaluation uses the cache-only admin POST
`/admin/pretrip/projects/{project_id}/rainfall-trend`. Supply only an authorized
current-position observation and an explicit target id, together with
`confirmLocationAccess=true`, `locationApprovalReference`, timezone-aware
`locationApprovedAt`, and scope `current_trip_rainfall_sampling`. The compact
response does not persist or return raw coordinates. An expired QPF returns
`stale_data` and confidence `0`; rerun explicit preparation rather than using
the immutable snapshot as current truth. The only POST write is the sanitized
`outputs/environment/cwa/rainfall/location_access_audit.jsonl`; it records the
approval reference/time/scope and explicitly records that no raw coordinates
were persisted.

Map/API freshness is recalculated when the prepared data is read. QPF expires
at `validUntil`; QPE uses `sourceTimestamp + 2 hours` because the QPE
`validUntil` is the past-one-hour accumulation endpoint. The UI marks an
expired selected product as `STALE`, and mixed QPE/QPF freshness is reported as
`partially_stale` rather than `ready`.

### Optional One-Shot CWA Radar/Satellite Worker

Run image-heavy weather preparation only on the Mac/server worker. Add
`--prepare-cwa-imagery` and use `--profile mac-workstation` with the existing
explicit-fetch approval flags:

```bash
SCOUT_CWA_SERVER_IMAGERY_CAPABLE=1 \
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_layer_preparation \
  --project-id "$PROJECT_ID" \
  --workspace-root "$WORKSPACE_ROOT" \
  --layers cwa-weather,cwa-qpf,terrain,risk-score,route,segments \
  --profile mac-workstation \
  --network-mode explicit-fetch \
  --allow-network-fetch \
  --prepare-cwa-imagery \
  --route-corridor-m 500
```

Required checks:

- `SCOUT_CWA_SERVER_IMAGERY_CAPABLE=1` is an operator-controlled capability
  attestation; profile text alone never authorizes image-heavy work;
- ARM and Raspberry Pi hosts fail closed even when a workstation profile is
  supplied;
- raw image cache root is fixed at
  `<workspace_root>/<project_id>/cache/cwa-weather-imagery`; it is inside the
  selected project workspace, outside the repository, and never shared with
  another project id;
- each image is capped at 8 MiB and 20 megapixels, each product is capped at 24
  evenly spaced frames across the requested window, and jobs are serialized
  with a retry cooldown;
- `project.json` contains `cwa_weather_imagery_manifest_ref`,
  `route_weather_risk_package_ref`, and `route_weather_lora_alert_ref` after a
  successful run;
- manifests expose latest plus 3/6/9/12-hour windows without pretending a
  latest-only source backfilled missing history;
- source timestamp, fetched-at time, image type, extent, expected delay,
  computed data delay, and candidate-only boundary are present;
- Pi/mobile profiles report
  `blocked_server_side_imagery_preparation_required` and perform no image work;
- `/admin/pretrip`, `/admin/debug`, `/admin`, and
  `/admin/dashboard?projectId=$PROJECT_ID#map` render only prepared cached
  assets with product, opacity, 3/6/9/12-hour timeline, frame, and play/pause
  controls; the Dashboard path must reuse the same-origin pretrip controller
  rather than fetch or process imagery independently;
- `outputs/route_weather_lora_alert.json` has `sent=false` and does not invoke
  radio or outbound providers.

### Explicit Connected Preparation And Recurring Frame Collection

The current local Mac/server Dashboard reads only the current connected-
preparation snapshot when `/admin/dashboard` opens. The browser does not fetch
provider assets itself, and a status GET never enrolls a writer. Preparation
starts only after the operator chooses `Refresh evidence` or Scout AI enters
the separately approved weather-decision refresh path:

```text
POST /admin/pretrip/projects/{project_id}/connected-preparation
GET  /admin/pretrip/projects/{project_id}/connected-preparation
schemaVersion=dashboardConnectedPreparation.v1
```

The server coordinator loads the repository `.env` (or the explicitly selected
`SCOUT_ENV_FILE`) without logging values, sets
`SCOUT_CWA_SERVER_IMAGERY_CAPABLE=1`, derives the CWA imagery cache from the
selected project as
`<workspace_root>/<project_id>/cache/cwa-weather-imagery`, and refreshes the
provider-backed Overpass/CWA/GEE layer subset with:

```text
profile=mac-workstation
network_mode=explicit-fetch
allow_network_fetch=true
prepare_cwa_imagery=true
```

It is single-flight per project. After an explicit operator or Scout AI refresh
completes, it schedules the next service-lifetime refresh after 600 seconds by
default. A status GET with no prior explicit run leaves `nextRunAt=null`.
Configure the interval with
`SCOUT_DASHBOARD_CONNECTED_REFRESH_SECONDS`; values below 60 seconds are
clamped. Stop the Dashboard service to stop this in-process schedule. This is
not an OS login item, LaunchAgent, cron entry, or Pi/mobile worker.

Run the exact same connected path once from the terminal with:

```bash
SCOUT_ENV_FILE=/Users/alexwang0315/scout-fusion/.env \
SCOUT_CWA_SERVER_IMAGERY_CAPABLE=1 \
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m dashboard_connected_preparation \
  --project-id "$PROJECT_ID" \
  --workspace-root "$WORKSPACE_ROOT" \
  --repo-root /Users/alexwang0315/scout-fusion
```

The redacted status may expose credential *names* and env-file paths, but never
credential values. It reports `cwaApiRequestAttempted`, `externalApiCallsMade`,
component statuses, next refresh time, and prepared artifact refs. Every run
retains older observed frames in the bounded project-local cache so the real
3/6/9/12-hour windows can grow over time without fabricated history. Cache
retention, pruning, locks, and asset reads are scoped to that project; a
refresh or cleanup for one workspace must not affect another workspace.
While a run is queued or running, the three request-result booleans are `null`
and `requestActivityState=in-progress`; the Dashboard renders this as
`in progress`, not the misleading `false`. A completed run replaces them with
observed booleans.

#### 2026-09-04 Weather Refresh To Decision Reassessment

`GET .../weather-dashboard` already rebuilds the candidate decision from the
published rainfall and route-weather artifacts on every request. It never
fetches CWA upstream. A separate Decision POST is not required. The explicit
refresh path is:

```text
operator POST connected-preparation
  -> server fetch / derive / atomic publication
  -> browser observes completedAt
  -> GET weather-dashboard (no-store)
  -> Decision response evaluatedAt + consumed evidence pair IDs
```

The original UI could miss the completion when the operator left Weather,
when another status read consumed the completion timestamp, or when a slower
old response replaced the newer result. Concurrent status and decision reads
also allowed a new completion status to be paired with an earlier decision.
Track the completion consumed by `weatherData.decisionReview`, observe status
before starting the decision read, and fence responses by project, API base,
and request sequence. Continue polling through transient status failures;
do not treat a failed status read as cancellation of the running job. Terminal
completion reloads Weather data even while another Dashboard view is open.

The coordinator now exposes `weatherDecisionInputs` and `currentArtifactRefs`.
The four required inputs are rainfall manifest, rainfall trend, imagery
manifest, and route-weather risk package. Inspect actual file contents, safe
workspace refs, timestamps within the run window, and matching pair/source-
frame/route identities. Missing, invalid, or previous-generation inputs keep
the overall result `partial`, even if an external API call succeeded. Historical
refs remain available in `artifactRefs`; they are not silently promoted into
the current-run receipt. `weatherDecisionInputs.status=current_run` proves
generation provenance, not provider freshness, rainfall coverage, or a safe
route. Decision API freshness and candidate-only boundaries still apply.

The Weather page separately reports preparation completion, Decision API
reassessment time, input generation status, and evidence freshness. A completed
reassessment can still return `DELAY` with `stale_data`. Expired imagery arrival
estimates must not appear as a current countdown in either the top critical
window or the decision evidence. A failed Decision read clears the candidate
and explicitly reports reassessment failure.

Focused replay:

```bash
./venv/bin/python -m pytest tests/test_dashboard_weather_refresh.py tests/test_dashboard_connected_preparation.py tests/test_admin_cwa_imagery_overlay.py -q
SCOUT_BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  SCOUT_WEATHER_REFRESH_OUTPUT_DIR=artifacts/browser/dashboard-weather-refresh-20260904 \
  node tools/dashboard_weather_refresh_browser_smoke.js
```

The browser replay operates the real refresh button with intercepted local API
responses: current-run completion, partial/stale completion, and Decision API
failure. Its receipt records `actualCwaRefreshPerformed=false`; desktop/mobile
screenshots are in the same artifact directory. This does not prove a new live
CWA fetch. The inspected 9099 process had `idle`, `runCount=0`, and no completion
record; process-local status cannot establish whether an earlier process ran.
HTML changes take effect on reload. New Python coordinator checks require a
service restart. Do not stop the shared Dashboard launcher without accounting
for its managed QGIS worker and active jobs.

Current-position and target sampling is a separate user gesture in Weather.
The user selects a prepared checkpoint and presses `授權目前位置並更新降雨趨勢`.
Only then does the browser request geolocation, obtain a server-issued short-
lived approval, and call `POST .../rainfall-trend`. The response is kept in UI
state; the server persists only the sanitized approval audit with
`rawCoordinatesPersisted=false`.

#### 2026-09-04 Target Trend To Decision Reassessment

The original `POST .../rainfall-trend` returned only point/corridor samples.
Replacing `weatherData.routeTrend` did not re-evaluate the Decision candidate,
and changing the checkpoint dropdown left the previous target result visible.
The target gesture now returns both `decisionReview` and an ephemeral
`weatherDashboard`, using the approved current position and selected target.
The same deterministic reducer consumes their QPE/QPF values and coverage;
`missing_cell`, `outside_grid`, or a missing value cannot become zero or `GO`.
Why/Where identify the sampled target and amounts, and When includes the QPF
validity window. No new arbitrary rainfall threshold is introduced.

The server binds the sampled, hash-validated grid frames to the active rainfall
manifest and checks the captured route identity. If publication changes the
source frames during sampling, or cached Decision context fails, sampling
still returns with `decisionReview.status=failed` and `weatherDashboard=null`.
Freshness is recomputed from the consumed rainfall, imagery, and newly sampled
trend, not the superseded cached trend's aggregate status. A stale old trend
must not force a fresh target review back to DELAY; a stale consumed source
still does.
Only the sanitized approval audit is written. The new trend is not published
as the stored route trend, and no LoRa alert is regenerated or sent.

Checkpoint selection invalidates the previous target decision without reading
location or making a request. The explicit location button obtains a new
short-lived approval and samples the existing CWA cache. Project, API-base,
request-sequence, and target checks prevent late results from replacing a
newer selection. An older server without the new Decision fields displays
`UNVERIFIED`, even if the rain samples succeeded. A later route-cache reload
discards ephemeral target context and explicitly requires another approved
sample; it never reuses or persists the coordinates.

The UI distinguishes QPE past-hour measurements from QPF next-hour predictions,
shows both source timestamps and validity windows, and explains UNKNOWN by
point status. The LoRa line is labeled as the persisted whole-route unsent
preview, not an alert produced for the newly selected checkpoint.

Focused proof commands:

```bash
./venv/bin/python -m pytest tests/test_dashboard_weather_target.py tests/test_dashboard_weather_refresh.py tests/test_admin_cwa_precipitation_grid.py tests/test_admin_cwa_imagery_overlay.py tests/test_route_precipitation_sampler.py -q
./venv/bin/python tools/dashboard_weather_target_fixture.py --fixture-harness --port 19107
```

The opt-in browser fixture serves the actual Weather UI with only its bootstrap
replaced, and uses the real approval, sampling, and Decision API against tiny
synthetic grids. CP 02 has numeric coverage; CP 103 has a QPF missing cell. It
uses a synthetic geolocation provider, forbids other POSTs and external browser
connections, and excludes the unrelated map panel. Select and recalculate both
targets, verify that selection itself sends no request, and confirm CP 103's
Decision Why/Where and UNKNOWN explanation change together. This is prototype
evidence, not official Dashboard qualification or proof of today's live CWA
weather. The 9099 service and QGIS worker are not restarted by the fixture;
new Python handlers require a separately coordinated service restart.

The 2026-07-23 operator approval covers the Dashboard service-lifetime recurring
timer after an explicit refresh described above. It is intentionally not
installed as a Login Item,
LaunchAgent, cron job, Pi worker, or mobile worker; a durable OS-level schedule
still requires a separate deployment review and approval.

### Scout AI Weather-Decision Fresh Preparation

Dashboard-mounted Scout AI queries now reuse the same server coordinator before
Pydantic AI receives a weather-decision question. The assistant runs its normal
registry-backed tool planner first; only plans containing
`scout.ai.weather_window.assess.v0` enter this path.

The order is fixed:

```text
weather-decision question
-> synchronous single-flight connected preparation
-> fresh CWA/GEE/route-weather artifacts
-> assistant context resolution
-> Weather-to-Decision tool execution
-> grounded answer synthesis
```

An assistant request joins an already queued/running preparation rather than
starting a second provider fetch. Otherwise it runs one fresh preparation and
waits for its completed `ready`, `partial`, or `failed` status before tool
execution. The public assistant source
`assistant_context.weather_decision_fresh_preparation` exposes only redacted
status, timestamps, component states, relative artifact refs, and
candidate-only boundaries. It never exposes credential values, env contents,
absolute cache paths, or provider request authorization.

If preparation fails or completes without observed external calls, the source
is marked unavailable or stale/unverified. Weather-to-Decision still executes
against the workspace so it can report the precise evidence gap, but it must
not treat the previous cache as fresh or infer zero rain. This path does not
call `/safety/*`, send outbound messages, or control hardware.

Weather-to-Decision must accept both the legacy `route_weather_package_ref` and
the current preparation outputs:

- `route_weather_risk_package_ref`;
- `cwa_weather_evidence_ref`;
- `cwa_qpf_corridor_summary_ref`.

The current artifacts are normalized in memory into the Weather-to-Decision
contract; the assistant does not duplicate or promote them into a new workspace
truth artifact. Provider, issued/valid timestamps, TTL, external-call state,
route-corridor summary, and weather-terrain interactions must retain their
source refs. If preparation is fresh but only forecast rain probability exists,
the tool reports `direct_qpf_accumulation_mm` as missing. It must not convert a
30% probability into millimetres or treat it as zero rain.

A synchronous assistant refresh also installs the coordinator's normal
`nextRunAt` timer after completion. Dashboard polling is read-only and cannot
launch a duplicate preparation while the model is answering.

Dashboard connected refresh requests only the provider-backed layers needed to
refresh Overpass, CWA, and GEE evidence. Existing GPX, route, terrain, and TEII
artifacts stay in the workspace and remain inputs to rainfall grids, imagery
route sampling, motion, risk-package extraction, and the LoRa preview; they are
not regenerated every ten minutes. The refresh also sets
`run_post_layer_enrichments=false`. Raster-label OCR, Boss-point synthesis,
mileage-tag alignment, and Route Architecture preparation are route-enrichment
jobs, not time-sensitive API refreshes; their manifest status is
`skipped_connected_refresh`, and they remain available through the normal full
preparation path. Connected refresh also sets
`run_map_preparation_spec_artifacts=false`: it reuses existing terrain route
samples/visualizations and the persisted Navigation & Terrain Intelligence
projection instead of spending minutes regenerating them after the provider
data is already ready. The manifest records the same
`skipped_connected_refresh` status for both bounded optimizations.

Radar/satellite motion estimation consumes the newest contiguous cached frame
suffix whose adjacent intervals are at most two hours. A longer historical gap
does not discard recent usable motion evidence; it only separates the older
animation history from the regression window.

When `SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT` is set, the wrapper performs
a final durable evidence restore after route context collection. This is not a
manual patch step; it is part of the reproducible reference-equivalence SOP.
Use it when comparing a new project id against an already reviewed standard
workspace. Leave it unset when the goal is to inspect fresh live OCR/Overpass or
environment deltas. CWA/GEE environment evidence is always fresh/current-run
evidence and is not restored from this source in either mode.
Strict reference comparison must exclude CWA/GEE weather/environment metrics
from count/status equivalence. It should still require the current workspace's
CWA/GEE refs to exist and expose the latest fetch result or current blocker.

Risk-route-base note:

- The `--route-corridor-m 500` value must be passed through to risk generation,
  not only to Overpass acquisition or admin layer preparation.
- The expected route-base strategy for this full preparation flow is
  `reference_progress_projected_to_nearest_overpass_segment.v1`.
- If a stale workspace already has risk refs generated with a different
  `route_base.sampling_strategy` or `route_base.corridor_m`, regenerate risk
  outputs before accepting baseline/calibrated overlays.
- If full layer preparation stalls inside segment alignment, diagnose
  `pretrip_overpass_route_alignment.py` separately. Do not keep rerunning the
  whole import/preparation loop and hiding the route-base or alignment cause.

For a local one-command rebuild, prefer the wrapper after setting variables:

```bash
SCOUT_PROJECT_ID="$PROJECT_ID" \
SCOUT_PRETRIP_WORKSPACE_ROOT="$WORKSPACE_ROOT" \
SCOUT_PRETRIP_MATERIAL_ROOT="$MATERIAL_ROOT" \
SCOUT_SOURCE_GPX_ROOT="$REFERENCE_DIR" \
SCOUT_GOLDEN_ROUTE_GPX="$GOLDEN_GPX" \
SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT="$DURABLE_EVIDENCE_SOURCE_ROOT" \
SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT="$RASTER_TILE_CACHE_ROOT" \
SCOUT_PRETRIP_IMAGERY_MIN_ZOOM=5 \
SCOUT_PRETRIP_IMAGERY_MAX_ZOOM=14 \
SCOUT_PRETRIP_IMAGERY_SEED_MAX_TILES=250 \
SCOUT_PRETRIP_ADMIN_BASE_URL="$ADMIN_BASE_URL" \
tools/rebuild_pretrip_workspace_on_scout.sh
```

## Step 3: Tile Cache TTL Policy

The raster tile cache default TTL is 30 days
(`DEFAULT_IMAGERY_TILE_CACHE_TTL_DAYS = 30`). Do not delete the cache to force
refresh.

`SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT` must point inside the selected project,
for example `<project-root>/cache/raster-tiles`. Do not append the project id or
layer id because the cache writer adds both namespaces. Dashboard clone supplies
this path automatically. A normal preparation must not place the target's
primary cache under a sibling shared-data directory.

For `tryimport`, suffix-test, or from-zero comparison runs that may reuse
unchanged source-correct raw tiles without replaying old workspace artifacts, set
`SCOUT_PRETRIP_RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS` to one or more stable
raw tile cache namespaces, comma-separated. The seeding step copies only fresh
raw PNG tiles for the same layer id according to TTL before remote fetch; it
does not copy OCR,
Overpass, risk, mileage, or other derived workspace artifacts.

Expected behavior when `--seed-imagery-cache` is used:

- fresh cached tiles are skipped;
- fresh tiles from configured fallback cache namespaces are copied into the
  current project cache before remote fetch;
- expired/stale cached tiles are refreshed individually;
- missing tiles are fetched individually;
- failed individual tiles produce warnings but must not erase vector evidence;
- OCR cache is keyed by tile image hash plus OCR engine/language/version, so
  unchanged tiles should be OCR cache hits.

Check tile cache fields:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
for key in [
    "workspace_raster_tile_cache_bundle_ref",
    "workspace_raster_tile_cache_root",
    "workspace_raster_tile_cache_layer_count",
    "raster_layer_manifest_refs",
    "imagery_tile_cache_manifest_ref",
    "imagery_tile_cache_plan_ref",
    "imagery_tile_cache_seed_status",
    "imagery_tile_cache_seed_tiles_seen",
    "imagery_tile_cache_seed_tiles_skipped_existing",
    "imagery_tile_cache_seed_tiles_written",
    "imagery_tile_cache_root",
]:
    print(key, project.get(key))
PY
```

`workspace_raster_tile_cache_layer_count` must be `7`, and the manifest-ref
mapping must contain `imagery`, `rudy`, `rudy-twmap`, `relief`, `geology`,
`topo-5k`, and `forest` before the workspace is considered raster-prepared.

`seed_status` must not be silently absent on a connected full-prep run unless
imagery prefetch was intentionally not allowed and reported as
`NOT APPLICABLE`.

## Step 4: OCR And Raster Label Adapter Checks

Map preparation runs OCR and the adapter automatically. Use standalone commands
only for debug or targeted re-run:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_raster_label_ocr \
  --project-root "$PROJECT_ROOT" \
  --raster-label-plan outputs/layers/plans/raster_label_plan.json \
  --output-ref outputs/layers/raster_label_ocr_output.json \
  --engine tesseract \
  --tesseract-lang chi_tra+eng \
  --source-id rudy-twmap \
  --json

PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_raster_label_adapter \
  --project-root "$PROJECT_ROOT" \
  --source outputs/layers/raster_label_ocr_output.json \
  --json
```

Required OCR checks:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
for key in [
    "raster_label_ocr_status",
    "raster_label_ocr_output_ref",
    "raster_label_ocr_cache_ref",
    "raster_label_ocr_label_count",
    "raster_label_ocr_cache_hit_count",
    "raster_label_ocr_cache_miss_count",
    "raster_label_evidence_ref",
    "raster_label_evidence_count",
    "raster_label_adapter_manifest_ref",
    "mcp_ocr_labels_ref",
    "mcp_ocr_label_count",
]:
    print(key, project.get(key))
PY
```

Interpretation:

- `raster_label_ocr_status=completed` means OCR executed or reused OCR cache.
- A high OCR cache-hit count is valid; it means unchanged tiles did not rerun
  Tesseract.
- `raster_label_ocr_label_count=0` can be valid only if tile records existed
  and OCR returned no labels; it is not the same as blocked dependency.
- `blocked_missing_dependency` or missing dependency names means the run is
  incomplete until dependencies are installed.

## Step 5: Route Context, K Anchors, And Mileage Tags

Layer preparation refreshes route context after raster label adapter completion.
Standalone route-context command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_route_context_collection \
  --project-root "$PROJECT_ROOT" \
  --route-keyword "<route keyword>" \
  --json
```

K values come from `candidates/route_mileage_k_anchors.json` and the mileage
alignment axis. OCR is only one possible input to those anchors.

Required K/mileage checks:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
alignment_ref = project.get("mileage_tag_alignment_ref")
anchor_ref = project.get("route_mileage_k_anchors_ref")
print("route_mileage_k_anchors_ref", anchor_ref, (root / anchor_ref).exists() if anchor_ref else False)
print("mileage_tag_alignment_ref", alignment_ref, (root / alignment_ref).exists() if alignment_ref else False)
if alignment_ref:
    alignment = json.loads((root / alignment_ref).read_text())
    counts = alignment.get("counts", {})
    print("tag_count", counts.get("tag_count"))
    print("aligned_tag_count", counts.get("aligned_tag_count"))
    print("projected_anchor_count", counts.get("projected_anchor_count"))
    print("usable_anchor_count", counts.get("usable_anchor_count"))
    print("display_mileage_status_counts", counts.get("display_mileage_status_counts"))
    anchors = alignment.get("route_mileage_alignment", {}).get("projected_anchors", [])
    usable = [a for a in anchors if a.get("usable_for_interpolation")]
    if usable:
        print("usable_anchor_route_distance_min", min(a["route_distance_m"] for a in usable))
        print("usable_anchor_route_distance_max", max(a["route_distance_m"] for a in usable))
        print("usable_anchor_mileage_min", min(a["mileage_m"] for a in usable))
        print("usable_anchor_mileage_max", max(a["mileage_m"] for a in usable))
    for tag in alignment.get("mileage_tags", [])[:12]:
        display = tag.get("display_mileage", {})
        print(
            "tag",
            tag.get("display_label"),
            tag.get("source_kind"),
            tag.get("route_distance_m"),
            display.get("alignment_status"),
            display.get("label"),
        )
PY
```

Troubleshooting `K待校正`:

- First check whether `route_mileage_k_anchors_ref` exists and has anchors.
- Then check the usable anchor route-distance range.
- If a CP/segment/Boss point has `route_distance_m` outside that range, the
  correct label is `K待校正` with `outside_anchor_range`.
- Do not rerun OCR just because the first Mileage Tags list items show
  `K待校正`; those first items may be outside the current K-anchor axis.
- Rerun route context/OCR only when anchors are missing, OCR is blocked, or
  route-note/raster evidence was not included.

Current local example from `chilai_nanhua_day1`:

```text
OCR: completed
raster_label_ocr_label_count: 10
raster_label_ocr_cache_hit_count: 191
raster_label_ocr_cache_miss_count: 0
route_mileage_k_anchor_count: 29
usable_anchor_count: 26
usable_anchor_route_distance_range: 14279.7518 .. 36277.6391 m
Start route_distance_m: 81900.0 -> outside_anchor_range -> K待校正
CP 001 route_distance_m: 326.3671 -> outside_anchor_range -> K待校正
CP 002 route_distance_m: 253.2304 -> outside_anchor_range -> K待校正
```

## Step 6: Overpass And Segment Alignment Checks

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
for key in [
    "overpass_evidence_ref",
    "overpass_map_context_ref",
    "overpass_raw_payload_ref",
    "overpass_candidate_count",
    "overpass_route_alignment_ref",
    "overpass_aligned_segment_candidates_ref",
    "overpass_aligned_segment_display_geometry_ref",
]:
    ref = project.get(key)
    exists = (root / ref).exists() if isinstance(ref, str) else None
    print(key, ref, exists)
alignment_ref = project.get("overpass_route_alignment_ref")
if alignment_ref:
    alignment = json.loads((root / alignment_ref).read_text())
    print("alignment_status", alignment.get("status"))
    print("alignment_counts", alignment.get("counts"))
PY
```

Required result for connected pretrip work:

- `overpass_raw_payload_ref` exists;
- `overpass_candidate_count > 0`;
- `overpass_map_context_ref` exists and has features;
- `overpass_route_alignment_ref` exists;
- `overpass_aligned_segment_candidates_ref` exists;
- segment alignment status is `completed`.

If Overpass is `planned_no_network` or candidate count is `0`, do not claim a
full preparation run. Re-run Step 2 with `--network-mode explicit-fetch` and
`--allow-network-fetch`.

Segment/risk projection checks:

- CP, MCP, segment display, baseline risk ribbon, and calibrated heatmap must
  visually follow the Overpass/local PBF route basis wherever Overpass-projected
  route-base samples exist.
- `route_risk.geojson` may include fallback candidate points when the route
  basis has gaps. `risk_ribbon.geojson` and `calibrated_risk_heatmap.geojson`
  must not connect those fallback points into long straight lines.
- If a line overlay crosses the map as a straight segment, inspect the source
  feature. Flattened OSM relation members should be preserved as
  `MultiLineString`, and route-base fallback pairs should be skipped rather
  than connected.

## Step 7: Boss/MCP/Risk Checks

Boss synthesis is normally triggered by layer preparation. Standalone command:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_boss_point_synthesis \
  --project-root "$PROJECT_ROOT" \
  --top-n 5
```

Minimum project checks:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path
root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
for key in [
    "risk_score_points_ref",
    "risk_ribbon_ref",
    "calibrated_risk_heatmap_ref",
    "risk_delta_ref",
    "major_critical_points_ref",
    "boss_points_ref",
    "boss_points_geojson_ref",
    "boss_point_count",
]:
    ref = project.get(key)
    exists = (root / ref).exists() if isinstance(ref, str) else None
    print(key, ref, exists)
PY
```

Report missing MCP/Boss as `FAIL` or `NOT APPLICABLE` with reason. Do not hide
them under a green layer count.

Inspect route-base metadata before accepting risk overlays:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
risk_ref = project.get("risk_score_points_ref")
if not risk_ref:
    raise SystemExit("missing risk_score_points_ref")
risk = json.loads((root / risk_ref).read_text())
meta = risk.get("metadata") or {}
route_base = meta.get("route_base") or {}
for key in [
    "sampling_strategy",
    "corridor_m",
    "reference_sample_count",
    "projected_reference_sample_count",
    "fallback_reference_sample_count",
    "route_point_count",
    "selected_feature_count",
    "trail_feature_count",
    "max_reference_distance_m",
    "median_reference_distance_m",
]:
    print(key, route_base.get(key))
PY
```

Expected connected route-base result:

- `sampling_strategy` is
  `reference_progress_projected_to_nearest_overpass_segment.v1`;
- `corridor_m` matches the run's `route_corridor_m` value, normally `500`;
- fallback count is allowed only as explicit gap provenance;
- risk ribbon and calibrated heatmap segment counts exclude skipped fallback
  pairs.

## Step 8: Full Workspace Spec And Layer Gates

Run the static repo contract:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py --repo-root .
```

Run the workspace contract:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
  --repo-root . \
  --project-root "$PROJECT_ROOT" \
  --require-workspace
```

Run workspace/spec alignment:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_pretrip_workspace_spec_alignment.py \
  --workspace-root "$WORKSPACE_ROOT" \
  --project-id "$PROJECT_ID" \
  --admin-base-url "$ADMIN_BASE_URL" \
  --allow-network-calls
```

Run browser smoke when Playwright/browser runtime is available:

```bash
node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
```

The complete 32-layer contract is:

```text
imagery, rudy, rudy-twmap, relief, geology, topo-5k, forest, osm, terrain,
corridors, overpass, route, completed-track, reference-tracks, retreat,
segments, risk-ribbon, risk-heatmap, risk-delta, soil-moisture,
antecedent-rain, cwa-qpf, risk-score, checkpoints, pois, hazards,
route-notes, cwa-weather, mcp, boss-points, events, weather-api
```

Remember: `pretrip_layer_preparation --layers` supports 23 preparation-backed
layers. The 32-layer admin contract includes runtime-only or UI/post-process
layers such as `rudy`, `rudy-twmap`, `relief`, `geology`, `topo-5k`, `forest`,
`completed-track`, `boss-points`, `events`, and `weather-api`.

OSM PBF vector render checks:

- `osm_pbf_render_geojson_ref` and `osm_pbf_feature_index_ref` must exist in
  the workspace when a local PBF source is available.
- `/admin/pretrip/projects/<project-id>/osm-pbf-vector.geojson` must return
  source-backed vector features. Endpoint counts alone are not sufficient.
- Do not use the local OSM PBF preview PNG as a map layer.
- The admin pages should render PBF vectors with OSM-like classed SVG geometry:
  line casing/core strokes for paths, tracks, steps, service/roads, routes,
  waterways, and infrastructure; readable point and line labels; and marker
  scale reapplied after layer toggles and viewBox changes.
- Runtime OSM raster tiles are optional browser context and are not a
  preparation cache target. A valid local-PBF render may have zero
  `image.osm-tile` elements as long as the vector layer itself is present,
  styled, labeled, and not backed by the preview PNG.

## Step 9: Optional Offline Replay Check

After the connected run has materialized Overpass, tiles, OCR, route context,
K anchors, risk, Boss, and mileage alignment, an offline replay can be used to
verify cached operation:

```bash
SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT="$RASTER_TILE_CACHE_ROOT" \
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pretrip_layer_preparation \
  --project-id "$PROJECT_ID" \
  --workspace-root "$WORKSPACE_ROOT" \
  --layers imagery,osm,overpass,terrain,risk-score,risk-ribbon,risk-heatmap,risk-delta,cwa-qpf,soil-moisture,antecedent-rain,cwa-weather,weather,reference-tracks,route,segments,checkpoints,mcp,pois,hazards,corridors,retreat,route-notes \
  --profile pi-offline \
  --network-mode no-network \
  --route-evidence-bundle normalized/routes/route_evidence_bundle.json \
  --route-corridor-m 500 \
  --reference-track-corridor-m 300 \
  --ai-mode fixture-or-precomputed \
  --ai-output-policy hash-and-summary
```

Do not use this offline replay as the only map preparation step for in-house
pretrip work, because it can leave Overpass or tile/OCR material in
`planned_no_network` or cache-only states.

## Completion Report Template

Every full run must end with this report:

```text
Project:
Workspace:
Material root:
Golden GPX:
Reference GPX count:

Specs read:
Spatial Policy bbox fetch: PASS/FAIL
Spatial Policy along-track corridor filter: PASS/FAIL

Importer: PASS/FAIL
Map preparation explicit fetch: PASS/FAIL
Overpass vector evidence: PASS/FAIL
Overpass segment alignment: PASS/FAIL
Rudy/Rudy+TW tile cache TTL behavior: PASS/FAIL/NOT APPLICABLE
OCR dependency preflight: PASS/FAIL
OCR execution/cache result: PASS/FAIL
Raster label adapter: PASS/FAIL
Route context collection: PASS/FAIL
K anchor coverage: PASS/FAIL
Mileage tag alignment: PASS/FAIL
Terrain visualization: PASS/FAIL/NOT APPLICABLE
Risk score/ribbon/heatmap/delta: PASS/FAIL/NOT APPLICABLE
MCP: PASS/FAIL/NOT APPLICABLE
Boss points: PASS/FAIL/NOT APPLICABLE
32-layer repo gate: PASS/FAIL
32-layer workspace gate: PASS/FAIL
Workspace spec alignment: PASS/FAIL
Browser UI smoke: PASS/FAIL/NOT APPLICABLE
Candidate-only boundary: PASS/FAIL
Runtime safety mutation avoided: PASS/FAIL

Known warnings:
Known partials:
Next required action:
```

Do not claim completion if any required gate is unchecked, timed out, or hidden
behind a partial run.

## Run Log: 2026-06-25 Tryimport2 Reference-Equivalent Rebuild

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport2
```

Reference workspaces:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport1
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1
```

Result: completed within the 30-minute requirement. The successful import +
preparation attempt took 551 seconds before the wrapper-level verifier returned
a transient admin API timeout; rerunning the verifier immediately afterward
passed. Strict workspace comparisons passed against both reference workspaces.

Issues encountered:

1. `timeout` command unavailable on macOS.
   - Symptom: `/usr/bin/time -p timeout 1800 ...` failed with
     `timeout: No such file or directory`.
   - Fix used: enforce the 30-minute limit with Python
     `subprocess.run(..., timeout=1800)`.
   - Runbook implication: do not rely on GNU `timeout` on macOS; use Python or
     install GNU coreutils explicitly.

2. Reusing the `tryimport1` material root directly caused MCP project mismatch.
   - Symptom: importer failed with
     `MCP named-point evidence project_id does not match import project_id:
     chilai_nanhua_day1_tryimport1 != chilai_nanhua_day1_tryimport2`.
   - Fix used: create a dedicated material root:
     `/private/tmp/scout-local-materials/pretrip/chilai_nanhua_day1_tryimport2`.
     Copy the `tryimport1` material root and replace
     `chilai_nanhua_day1_tryimport1` with `chilai_nanhua_day1_tryimport2` in
     `material_manifest.json` and `sources/mcp/named_point_evidence.json`.
   - Runbook implication: each new project id needs project-id-aligned material
     metadata when material includes project-scoped MCP evidence.

3. Wrapper verifier can fail on the 10-second admin compact API timeout even
   when the workspace is valid.
   - Symptom: wrapper completed final durable restore, then failed on
     `admin API check failed:
     http://127.0.0.1:9112/admin/pretrip/projects/chilai_nanhua_day1_tryimport2?compact=1:
     timed out`.
   - Fix used: verify the completed workspace directly with strict compare and
     rerun `tools/verify_pretrip_workspace_spec_alignment.py`; the rerun passed.
   - Runbook implication: if the only failure is the admin compact API timeout,
     do not rerun import immediately. First retry the verifier and check the API
     with a longer client timeout.

Verification summary:

```text
Tryimport2 vs tryimport1 strict compare: PASS
Tryimport2 vs reference strict compare: PASS
9112 compact API for tryimport2: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment rerun: PASS
9112 Playwright query URL check: PASS
Admin UI visual smoke: PASS
```

## Run Log: 2026-06-30 Environment Derivatives After Risk Sync

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0630_1
```

Attempt:

```text
Attempt type: targeted environment-risk derivative repair
Full import rerun: not run in this attempt
```

Issues encountered:

1. Environmental derivative candidate groups were all zero.
   - Symptom: `New Landslide Candidates`, `Wetness / Flash Flood Candidates`,
     `Trail Obscurity Candidates`, and `Practical Darkness Candidates` showed
     `0`, with data gaps for `sentinel2`, `sentinel1`, `dynamic_world`,
     `rainfall`, and `terrain`.
   - Root cause: `run_layer_preparation()` prepared CWA/GEE environment
     derivatives before the same preparation run synchronized/generated Scout
     Risk Engine route-risk outputs. The GEE feature package therefore could
     not apply the existing route-risk terrain proxy fallback.
   - Fix applied: environment evidence preparation now runs after risk sync in
     the layer-preparation manifest path, then reloads `project.json` before
     layer records and projections are built.
   - SOP change: when risk and GEE layers are requested in the same connected
     preparation run, risk route-profile refs must be ready before
     `scout_gee_feature_package.json` and derived environment candidates are
     written.

2. GEE route feature REST used the Scout workspace id as the Google Cloud
   project id.
   - Symptom: `scout_gee_feature_package.json` had
     `gee_route_feature_http_error:400`; the provider error was
     `Invalid project resource name projects/chilai_nanhua_day1_scoutAI_test0630_1`.
   - Root cause: `build_scout_gee_feature_package()` preserved the Scout
     workspace `project_id` correctly in the artifact, but also passed it to
     the Earth Engine REST URL. The REST URL must use `SCOUT_GEE_PROJECT_ID`,
     `SCOUT_GEE_PROJECT`, or `GOOGLE_CLOUD_PROJECT` from the loaded env.
   - Fix applied: live route-feature fetch now resolves the GEE project id
     from env while keeping the Scout project id in artifact metadata.
   - SOP change: `.env` GEE project id is provider routing metadata; it must
     never be replaced with the Scout workspace/project id.

3. Small route-feature requests could echo the job manifest instead of
   returning computed per-segment metrics.
   - Symptom: a single-segment `value:compute` call returned HTTP 200 but
     included `job_kind=scout_gee_route_feature_package`,
     `expected_output=segment_features`, and the input `segments` rather than
     computed `segment_features`.
   - Fix applied: echo manifests are now classified as
     `server_script_not_configured` with blocker
     `gee_route_feature_script_not_configured`; input segments are not counted
     as raw GEE metric features. Failed/blocked route-feature packages now keep
     a secret-safe `raw_failure_summary`.
   - SOP change: do not treat HTTP 200 from `value:compute` as route-feature
     success unless computed `segment_features` are present.

Validation snapshot:

```text
Workspace: /Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0630_1
Feature package status: server_script_not_configured
Feature package blocker: gee_route_feature_script_not_configured
Route points: 11191
Route feature segments: 749
Raw GEE segment features: 0
Terrain proxy source: scout_risk_engine_route_profile
Environment derivative status: ready_with_data_gaps
New landslide candidates: 0
Wetness / flash flood candidates: 327
Trail obscurity candidates: 0
Practical darkness candidates: 584
Remaining metric gaps: sentinel2, sentinel1, dynamic_world, rainfall
Terrain metric gap: resolved through Scout Risk Engine route-profile fallback
CWA fetched hour retained in derivatives: 2026-06-30T05:00:00Z
Focused pytest: PASS
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
```

## Run Log: 2026-06-30 From-Zero Scout AI Test0630 Replay

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0630
```

Material root:

```text
/Users/alexwang0315/workspace/scout-local-materials/pretrip/chilai_nanhua_day1_scoutAI_test0630
```

Policy:

- This is a from-zero replay. It must not copy material or durable evidence from
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`.
- `SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT` must remain empty and
  `SCOUT_PRETRIP_RESTORE_FROM_BACKUP=0`.
- Raw Rudy/Rudy+TW tile cache fallback may point at
  `chilai_nanhua_day1_scoutAI` for TTL-valid PNG tiles only; derived OCR,
  Overpass, risk, mileage, CWA/GEE, and workspace artifacts must be regenerated.

Attempt 1:

```text
Result: FAIL during importer preflight
```

Issue encountered:

1. Target-specific MCP material contained an unsupported
   `search_profile.material_provenance` field.
   - Symptom: Pydantic validation failed while loading
     `sources/mcp/named_point_evidence.json`.
   - Fix applied before retry: regenerate the target MCP material with the
     project id set to `chilai_nanhua_day1_scoutAI_test0630` and without the
     unsupported extra field.
   - SOP change: material provenance belongs in `material_manifest.json` or
     an accepted MCP schema field; do not add ad hoc fields to project-scoped
     MCP evidence JSON.

Attempt 2:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0630_20260629T155830Z.log
Elapsed: 438 seconds
Result: COMPLETED, but not accepted
```

Issues encountered:

1. Strict reference comparison failed against
   `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`.
   - Symptom: diffs included mileage tag alignment, Overpass kept/snapped GPX
     point counts, and route-pressure sample count.
   - Investigation: the candidate workspace was internally coherent, while the
     reference workspace had stale/inconsistent project metrics versus its
     artifact contents for route pressure, mileage, and Overpass alignment.
   - SOP change: when the reference is internally incoherent, record a
     reference coherence report before changing target workflow behavior. Do
     not degrade a fresh full-route target to match a stale partial reference
     unless the operator explicitly requests artifact-equivalence over current
     full-route preparation.

2. Route-base summary metadata existed in `route_risk.metadata.json` but did
   not propagate into the GeoJSON artifacts checked by the Scout AI skill.
   - Symptom: `risk_score_points.geojson` lacked
     `metadata.route_base.sampling_strategy`, so the skill route-base check
     could not prove
     `reference_progress_projected_to_nearest_overpass_segment.v1` from the
     accepted risk-score layer ref.
   - Root cause: `write_route_geojson()` wrote only a FeatureCollection and
     dropped the metadata returned by
     `build_overpass_pretrip_route_profile()`. Downstream risk-score, ribbon,
     and calibrated heatmap builders therefore could not inherit route-base
     summary metadata, even though per-sample `route_base_source` was present.
   - Fix applied before retry: allow `route_risk.geojson` to carry metadata,
     pass route metadata from layer preparation, and propagate
     `metadata.route_base` into `risk_score_points`, `risk_ribbon`, and
     `calibrated_risk_heatmap` metadata.
   - SOP change: route-base acceptance must inspect both per-feature
     `route_base_source` provenance and summary metadata on the map-rendered
     risk artifacts, especially `risk_score_points.geojson`.

Validation before retry:

```text
Focused route-base metadata tests: PASS
```

Attempt 3:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0630_20260629T163436Z.log
Elapsed: 357 seconds
Result: COMPLETED, strict comparison still failed because the reference is incoherent
```

Fixes verified:

1. Scout AI planning went through Pydantic AI/OpenRouter and called
   `record_pretrip_import_preparation_plan`.
   - Plan artifact:
     `outputs/scout_ai/pretrip_import_preparation_plan_attempt3_model_call.json`.
   - Run result artifact:
     `outputs/scout_ai/pretrip_import_preparation_run_result.json`.
   - SkillRunRecord artifact:
     `outputs/scout_ai/pretrip_import_preparation_skill_run_record.json`.

2. Route-base summary metadata now propagates to all risk refs required by the
   Scout AI skill.
   - `route_risk.geojson`, `risk_score_points.geojson`,
     `risk_score_points.metadata.json`, `risk_ribbon.geojson`,
     `risk_ribbon.metadata.json`, `calibrated_risk_heatmap.geojson`, and
     `calibrated_risk_heatmap.metadata.json` all expose
     `route_base.sampling_strategy =
     reference_progress_projected_to_nearest_overpass_segment.v1` and
     `route_base.corridor_m = 500.0`.
   - Candidate route-base counts: projected reference samples `5054`, fallback
     reference samples `560`, route-base points `4214`.

3. Live local OSM PBF render was verified on the actual 9112 admin app.
   - `/admin/pretrip/projects/chilai_nanhua_day1_scoutAI_test0630/osm-pbf-vector.geojson`
     returned 518 features.
   - `/admin/pretrip`, `/admin/debug`, and `/admin` rendered 457 OSM PBF
     casing/core lines and 61 points without using a preview PNG as the OSM
     layer.
   - Toggling `segments` did not enlarge the sampled OSM PBF point marker.

Remaining failure:

- Strict comparison against
  `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI` still fails on
  `mileage_tag_alignment_count`, Overpass kept/snapped GPX point counts, and
  `route_pressure_sample_count`.
- The target workspace is internally coherent after the workflow fix. The
  reference workspace is not: its current risk files contain 3476 score points
  and 3576 ribbon/heatmap segments, but
  `mileage_tag_alignment.json` still references stale source counts of 4077
  score points and 4530 ribbon/heatmap segments. The reference risk GeoJSON and
  risk-score/ribbon/heatmap metadata also do not yet carry route-base summary
  metadata, except for `route_risk.metadata.json`.
- SOP change: do not declare a from-zero target replay complete when strict
  comparison is still failing. If the operator wants count-equivalence, first
  repair or rebuild the comparison reference workspace through the same Scout
  AI skill path, then rerun the target from zero and compare against the
  coherent reference. Do not intentionally reproduce stale partial
  route-pressure or mileage artifacts in a fresh full-route target.

Verification summary:

```text
Scout AI/OpenRouter plan tool call: PASS
From-zero backup restore disabled: PASS
Wrapper elapsed under 30 minutes: PASS (357s)
Overpass evidence: PASS (517 candidates)
OSM PBF evidence/render: PASS (518 endpoint features; live 9112 classed render)
OCR: PASS (20 labels)
Route-base metadata: PASS
Risk ribbon/calibrated fallback skip: PASS (3576 segments, 637 skipped pairs)
CWA/GEE current-run refs: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS with known layout metadata warnings
Admin UI visual smoke: PASS
Focused pytest: PASS (175 passed)
Strict reference count comparison: FAIL, blocked by reference_incoherent report
```

Continuation audit, 2026-06-30:

```text
Command: tools/compare_pretrip_workspace_against_reference.py --strict-counts
Reference: /Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
Candidate: /Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0630
Result: FAIL
Missing refs: none
```

Current metric diffs:

```text
mileage_tag_alignment_count: reference=19879 candidate=17096
overpass_route_alignment_kept_gpx_point_count: reference=1023 candidate=3163
overpass_route_alignment_snapped_point_count: reference=983 candidate=891
route_pressure_sample_count: reference=182 candidate=225
```

Reference coherence evidence:

- Both reference and candidate route summaries describe the same imported route
  extent: 112258.31 m and 11191 route points.
- Reference `project.json` reports risk counts of 3476 score points and 3576
  ribbon/heatmap segments, but reference `mileage_tag_alignment.json` still
  carries stale source-kind counts of 4077 risk-score points, 4530
  risk-ribbon segments, 4530 calibrated heatmap segments, and 4531
  terrain-route samples.
- Reference `project.json` reports Overpass alignment metrics of 1023 kept GPX
  points and 983 snapped points, while the referenced
  `outputs/overpass_route_alignment.json` artifact reports 22888 kept GPX
  points, 92 snapped points, and 4530 route edges.
- Candidate `chilai_nanhua_day1_scoutAI_test0630` regenerates coherent current
  artifacts from zero with 3576 risk ribbon/heatmap segments, 3476 risk score
  points, 4214 terrain route samples, 225 route-pressure samples, and
  route-base metadata on the accepted risk GeoJSON refs.

Blocking decision:

- Another from-zero target rerun is not expected to make strict comparison pass
  because the remaining diffs are caused by the comparison reference mixing
  stale derived counts with current risk artifacts.
- The Scout AI skill boundary says not to mutate a reference workspace.
- The runbook policy says not to intentionally reproduce stale partial
  route-pressure or mileage artifacts unless the operator explicitly requests
  artifact-equivalence over current full-route preparation.
- Next allowed action needs operator approval for one of these paths:
  rebuild/repair `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI`
  through the same Scout AI skill path and then rerun the target from zero, or
  explicitly request artifact-equivalence against the stale reference counts.

## Run Log: 2026-06-30 From-Zero Scout AI Test0630_1 Replay

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0630_1
```

Reference workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0630
```

Policy:

- This is a from-zero Scout AI skill replay.
- Do not copy material, durable evidence, or derived artifacts from
  `chilai_nanhua_day1_scoutAI_test0630`.
- Keep `SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT=""` and
  `SCOUT_PRETRIP_RESTORE_FROM_BACKUP=0`.
- If the run fails, fix the workflow or input-material generation and rerun the
  full skill/wrapper path from zero; do not patch the target workspace outputs
  into shape.

Attempt 1:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0630_1_20260630T030434Z.log
Elapsed: <60 seconds
Result: FAIL during importer MCP material validation
```

Issue encountered:

1. Target-specific MCP material contained a top-level
   `material_provenance` field.
   - Symptom: `NamedPointEvidenceSet` rejected the field with
     `Extra inputs are not permitted`.
   - Root cause: the target material-generation step put provenance into
     `sources/mcp/named_point_evidence.json` instead of keeping it only in
     `material_manifest.json`.
   - Fix applied before retry: remove `material_provenance` from the MCP JSON
     and keep target material provenance in `material_manifest.json`.
   - SOP change: none; this confirms the existing SOP that MCP provenance must
     not use ad hoc schema fields.

Attempt 2:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0630_1_20260630T032653Z.log
Elapsed: 800 seconds
Result: FAIL strict reference comparison after a complete from-zero run
```

Issue encountered:

1. OSM Carto render-context expansion leaked into the Overpass-style route
   candidate basis.
   - Symptom: complete run finished, but strict comparison against
     `chilai_nanhua_day1_scoutAI_test0630` failed with
     `overpass_candidate_count` 855 vs 517, risk ribbon/heatmap segment counts
     4835 vs 3576, and mileage tag alignment 21125 vs 17096.
   - Root cause: local OSM PBF extraction was expanded for richer OSM Carto
     vector rendering, but the same expanded payload was also consumed by the
     route/risk candidate adapter.
   - Fix applied before retry: split the local OSM PBF payload into a full
     OSM Carto render context and a narrower route-evidence candidate basis.
     The full render context remains available through
     `osm_pbf_render_geojson_ref` / `osm_pbf_feature_index_ref`; the candidate
     adapter must not consume OSM Carto background roads, landcover, buildings,
     or place labels. It may keep only trail highways, hiking routes, reference
     terrain risk evidence, and relevant POI evidence, while preserving
     untagged node geometry needed to hydrate kept ways.
   - SOP change: OSM PBF acceptance must distinguish "render context" from
     "Overpass/risk route basis"; a richer OSM background must not change
     route alignment, risk, mileage, or segment counts.

Attempt 3:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0630_1_20260630T035403Z.log
Elapsed: 615 seconds
Result: FAIL strict reference comparison after a complete from-zero run
```

Issue encountered:

1. The first render/candidate split was still too broad.
   - Symptom: strict comparison still failed with `overpass_candidate_count`
     855 vs 517, `risk_score_point_count` 4191 vs 3476, and
     `risk_ribbon_segment_count` / `calibrated_risk_heatmap_segment_count`
     4835 vs 3576.
   - Root cause: the route-evidence adapter used
     `ROUTE_CORRIDOR_HIGHWAYS`, which includes `service`, `tertiary`, and
     `unclassified`. Those are useful OSM Carto road-render context, but they
     are not part of the reference Overpass route basis for this replay.
     The adapter also allowed `place=*` labels and one `natural=cliff` feature
     into route/risk evidence; those belong to background context unless the
     reference evidence explicitly contains them.
   - Fix applied before retry: add dedicated route-evidence matchers. Full OSM
     extraction/render may include Carto roads, landcover, water, buildings,
     and place labels. The Overpass-style candidate adapter may use only
     `TRAIL_HIGHWAYS` (`path`, `footway`, `track`, `steps`, `bridleway`,
     `pedestrian`), hiking relations, `scree` / `bare_rock` terrain risk,
     hazard/risk tags, and reference POI nodes (`peak`, `spring`, shelter,
     drinking water, parking, huts, water taps).
   - SOP change: never use a broad renderer highway set as the route/risk
     candidate basis. A renderer palette or OSM-like style change must be
     regression-tested against Overpass candidate counts, risk route-base
     counts, and mileage alignment counts.

Attempt 4:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0630_1_20260630T041718Z.log
Elapsed: completed preparation; wrapper exit failed only on first admin API spec-alignment timeout
Result: DATA PASS after standalone verification
```

Validation snapshot:

```text
Strict reference comparison: PASS (metric_diffs empty; CWA/GEE time-sensitive metrics excluded)
Overpass candidates: 517
Risk score points: 3476
Risk ribbon segments: 3576
Calibrated risk heatmap segments: 3576
OSM render context elements: 2033
OSM candidate-basis elements: 517
Raster OCR labels: 20
Route context points: 60
Spec alignment standalone: PASS (0 errors; 5 existing workspace layout warnings)
Admin compact API retry: PASS (HTTP 200; 8.8 seconds)
32-layer repo gate: PASS
32-layer workspace gate: PASS
Focused pretrip/admin/debug/API/page pytest: PASS (141 passed, 8 subtests passed)
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test: PASS
Admin UI visual smoke: PASS
```

OSM Carto renderer SOP:

- `config/osm_carto_palette.yaml` is the local simplified palette source for
  Scout's OSM PBF vector renderer. It intentionally references
  OpenStreetMap Carto / osm-carto concepts without vendoring the full
  Mapnik/osm-carto pipeline.
- Preserve OSM-like draw order: background, landcover, water polygons,
  building polygons, road casings, road fills, points, then labels.
- Road rendering must use casing plus fill paths. Labels need a halo and
  screen-readable sizing; point markers and labels must keep screen-readable
  scale after zoom and layer toggles.
- OSM PBF render refs (`osm_pbf_render_geojson_ref`,
  `osm_pbf_feature_index_ref`) are local OSM vector context only. They must not
  replace Rudy+TW OCR/cache as the authoritative hiking-map raster source.
- Do not use the local OSM PBF preview PNG as an admin map layer; render the
  parsed GeoJSON/vector features.
- Do not feed full OSM Carto render context into Overpass alignment, risk
  baseline/calibrated route-base generation, segment projection, or mileage
  alignment. Those steps use the narrower route-evidence candidate basis.

## Run Log: 2026-06-29 Overpass Alignment Normal Corridor Regression

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0629
```

Attempt:

```text
Attempt type: targeted route/segment Overpass alignment correction
Full import rerun: not run in this attempt
Reference comparison root: /Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Issue encountered:

- Symptom: the target workspace's golden-route-derived segment display could
  visually jump across the map instead of roughly following the road/trail
  geometry visible in Rudy/TW map imagery. The raw golden route and speed
  filter were not the cause: both target and reference had
  `11413 -> 11191` primary route points after GPX speed filtering.
- Root cause: `pretrip_layer_preparation.py` passed the Spatial Policy
  route-corridor width (`route_corridor_m=500`) into
  `align_workspace_route_to_overpass()` as the GPX point/segment projection
  tolerance. The 500m value is an evidence corridor for acquisition and
  filtering; it is too large for display alignment normal snapping and can pull
  checkpoints or segment display points onto nearby but wrong
  Overpass/risk-ribbon centerlines.
- Fix applied: keep `route_corridor_m=500` for route-corridor evidence and risk
  generation, but use a separate Overpass alignment normal snap tolerance,
  defaulting to `SCOUT_OVERPASS_ALIGNMENT_MAX_PROJECTION_DISTANCE_M=50`.
- SOP change: never reuse `SCOUT_ROUTE_CORRIDOR_M` as the Overpass alignment
  projection tolerance. If visual segment alignment shows map-crossing straight
  lines while the raw segment display follows the route, inspect
  `project.overpass_route_alignment_max_projection_distance_m` first.

Validation snapshot:

```text
Focused pytest: PASS (tests/test_pretrip_overpass_route_alignment.py, 6 passed)
Target overpass_route_alignment_max_projection_distance_m: 50.0
Target route_edge_count: 3576
Target snapped_point_count: 891
Target kept_gpx_point_count: 3163
Target rejected_segment_alignment_count: 10
Target segments 051-086: mostly original GPX display geometry or short valid alignment; no 500m tolerance snapping
Risk ribbon segments: 3576
Risk ribbon skipped fallback/gap pairs: 637
Calibrated heatmap segments: 3576
Calibrated heatmap skipped fallback/gap pairs: 637
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
Admin UI visual smoke: PASS
Focused pretrip layer/admin pytest: PASS (59 passed, 1 warning)
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test: PASS
```

## Run Log: 2026-06-29 From-Zero Scout AI Test0629 Replay

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI_test0629
```

Material root:

```text
/Users/alexwang0315/workspace/scout-local-materials/pretrip/chilai_nanhua_day1_scoutAI_test0629
```

Scout AI skill invocation:

```text
skill_id=pretrip-import-preparation
skill_manifest=skills/scout/pretrip-import-preparation.yaml
plan_ref=/Users/alexwang0315/workspace/scout-local-materials/pretrip/chilai_nanhua_day1_scoutAI_test0629/outputs/scout_ai/pretrip_import_preparation_plan_model_call.json
pydantic_ai_provider=openrouter
pydantic_ai_tool_called=true
activation_decision=degrade
degraded_to=manual_pretrip_import_preparation_runbook
```

Attempt 1:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0629_20260629T101651Z.log
Elapsed: 64.5 seconds
Result: FAIL
```

Issue encountered:

1. The run mixed 32-layer admin contract ids with
   `pretrip_layer_preparation --layers`.
   - Symptom: layer preparation failed with
     `ValueError: unsupported layer id: boss-points`.
   - Root cause: `boss-points` is a 32-layer admin contract layer and a required
     evidence/admin gate, but it is not currently a `pretrip_layer_preparation`
     CLI layer id.
   - Fix to apply before retry: remove `boss-points` from
     `SCOUT_PRETRIP_LAYERS` for the layer-preparation CLI run. Continue to
     verify Boss evidence separately through project refs, admin view, and the
     32-layer contract gate.
   - SOP change: do not pass all 32 admin layer ids directly to
     `pretrip_layer_preparation --layers`; use only layer-preparation-supported
     ids and validate the complete 32-layer contract afterward.

Attempt 2:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0629_20260629T102057Z.log
Elapsed before stop: approximately 60 seconds
Result: STOPPED
```

Issue encountered:

1. The wrapper attempted implicit durable restore from the previous partial
   target backup while `durable_evidence_source_root` was empty.
   - Symptom: `Restoring durable admin evidence refs from
     /Users/alexwang0315/workspace/.pretrip-backups/chilai_nanhua_day1_scoutAI_test0629.backup...`
     appeared during a declared from-zero run.
   - Root cause: the wrapper treated a just-created target backup as an
     implicit durable source whenever no explicit durable source was set.
   - Fix applied: add `SCOUT_PRETRIP_RESTORE_FROM_BACKUP`; from-zero runs must
     set `SCOUT_PRETRIP_RESTORE_FROM_BACKUP=0`.
   - SOP change: a from-zero run may move old target workspaces to backup for
     cleanup, but must not read that backup as evidence or durable replay input.

2. The local OSM PBF path fell back to Python `osmium` streaming because the
   `osmium` CLI was not available.
   - Symptom: layer preparation entered
     `python_osmium_streaming_fallback` over the full Taiwan PBF.
   - Fix applied before retry: keep the source-backed OSM JSON to GeoJSON
     render fallback so `osm_pbf_render_geojson_ref` is not lost when the CLI
     is unavailable.
   - SOP note: Python fallback is correctness-capable but may be slow; prefer a
     preinstalled `osmium` CLI or target-specific PBF extract cache for
     time-bounded replays.

Attempt 3:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0629_20260629T102522Z.log
Elapsed before stop: approximately 8 minutes
Result: STOPPED
```

Issue encountered:

1. Python `osmium` fallback spent too long materializing tags for unrelated OSM
   nodes before bbox/corridor filtering could complete.
   - Symptom: the stack was inside `_osmium_tags(node)` while scanning the
     Taiwan PBF; no `osm_pbf_phase_a_raw.osm.json` had been written after
     several minutes.
   - Root cause: the fallback handler converted every node's tags to a Python
     dict before checking whether the node carried any Scout-relevant tag.
   - Fix applied: first scan only the relevant tag keys for node/way/relation
     matching; materialize full tags only for matched OSM elements.
   - SOP change: keep Python `osmium` fallback correctness-capable, but optimize
     it for sparse relevant tags and prefer CLI bbox extraction whenever the
     CLI is already installed.

Attempt 4:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0629_20260629T103705Z.log
Elapsed before stop: approximately 4 minutes
Result: STOPPED
```

Issue encountered:

1. Python-level tag prefiltering was not enough because pyosmium still invoked
   the Python handler for too many objects.
   - Symptom: `pretrip_layer_preparation` remained in the PBF scan for several
     minutes without writing `osm_pbf_phase_a_raw.osm.json`.
   - Root cause: the handler still received all objects from pyosmium; only the
     in-handler dict allocation was reduced.
   - Fix applied: add native pyosmium `KeyFilter` with the Scout-relevant tag
     keys before the Python handler. The location index still runs in native
     code, but unrelated objects are not dispatched into Python callbacks.
   - SOP change: Python fallback must use native pyosmium filters when the
     `osmium` CLI is unavailable.

Attempt 5:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0629_20260629T104538Z.log
Elapsed: approximately 10 minutes
Result: COMPLETED, STRICT COMPARISON FAILED
```

Issues encountered:

1. The full wrapper run completed and produced source-backed Overpass, OSM PBF,
   risk, OCR, mileage, Boss, MCP, CWA, and GEE refs, but strict comparison
   against `/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI` failed.
   - Symptom: compare diffs included `raster_label_ocr_label_count 13 vs 20`,
     `overpass_route_alignment_kept_gpx_point_count 943 vs 1023`,
     `overpass_route_alignment_snapped_point_count 990 vs 983`,
     `route_pressure_sample_count 225 vs 182`, and
     `mileage_tag_alignment_count 17089 vs 19879`.
   - Confirmed non-cause: primary GPX SHA and 24-GPX source corpus matched the
     reference; OSM PBF feature index, Overpass candidate count, risk score
     point count, and risk ribbon segment count matched the current reference
     project metrics.

2. Raster tile cache root was passed as a project directory.
   - Symptom: target tile refs were written under
     `.../raster-tiles/chilai_nanhua_day1_scoutAI_test0629/chilai_nanhua_day1_scoutAI_test0629/imagery/...`
     while the stable reference raw tiles existed under
     `.../raster-tiles/chilai_nanhua_day1_scoutAI/imagery/...`.
   - Impact: the same z/x/y Rudy+TW tile was fetched again and had a different
     image hash, so OCR produced 13 labels instead of the cached 20-label
     result.
   - Fix applied: wrapper now normalizes
     `SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT` when it accidentally ends with the
     current project id, and `admin_local_raster_tiles.seed_imagery_tile_cache`
     supports `fallback_cache_project_ids` to copy fresh raw PNG tiles before
     remote fetch.
   - SOP change: use a shared raster tile root plus
     `SCOUT_PRETRIP_RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS` for project-id
     suffix replay. This is raw tile cache reuse, not durable derived evidence
     replay.

3. The comparison reference contains a route-pressure inconsistency.
   - Symptom: reference `normalized/routes/route_summary.json`,
     `candidates/segments.json`, and
     `outputs/overpass_aligned_segment_display_geometry.json` all describe a
     112.258 km route, but `outputs/route_pressure_profile.json` contains only
     182 samples ending at 90.599 km.
   - Impact: a current coherent from-zero run generates 225 route-pressure
     samples for the full 112.258 km route, which then changes mileage tag
     totals.
   - SOP change: when strict comparison fails on route-pressure or mileage
     counts, first check whether the reference workspace has internally
     consistent route extent, risk route profile, route pressure, and mileage
     artifacts. Do not intentionally degrade a fresh full-route workspace to a
     partial stale reference without operator confirmation.

Attempt 6:

```text
Log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_test0629_20260629T111316Z.log
Elapsed: 347 seconds
Result: COMPLETED, STRICT COMPARISON STILL FAILED BECAUSE REFERENCE IS INCOHERENT
```

Fixes verified:

1. Scout AI planning went through Pydantic AI/OpenRouter and called the plan
   tool.
   - Plan artifact:
     `outputs/scout_ai/pretrip_import_preparation_plan_attempt6_model_call.json`.
   - Run result artifact:
     `outputs/scout_ai/pretrip_import_preparation_run_result.json`.
   - SkillRunRecord artifact:
     `outputs/scout_ai/pretrip_import_preparation_skill_run_record.json`.

2. Raw Rudy+TW tile cache fallback worked without durable workspace replay.
   - Wrapper env: `SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT=""`,
     `SCOUT_PRETRIP_RESTORE_FROM_BACKUP=0`,
     `SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT=/Users/alexwang0315/workspace/scout-local-data/raster-tiles`,
     `SCOUT_PRETRIP_RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS=chilai_nanhua_day1_scoutAI`.
   - Imagery seed summary: `tiles_seen=191`,
     `tiles_copied_from_fallback_cache=191`, `tiles_written=0`.
   - OCR result: `raster_label_ocr_label_count=20`.

3. The remaining strict-count diffs were reduced to reference-incoherent
   project/artifact metrics:
   - `overpass_route_alignment_kept_gpx_point_count 943 vs 1023`;
   - `overpass_route_alignment_snapped_point_count 990 vs 983`;
   - `route_pressure_sample_count 225 vs 182`;
   - `mileage_tag_alignment_count 17096 vs 19879`.
   - Reference coherence report:
     `outputs/scout_ai/reference_coherence_report.json`, status
     `reference_incoherent`.

Reference incoherence details:

- Reference route summary and segment display geometry describe a 112.258 km
  route, but reference route pressure ends at 90.599 km.
- Reference mileage tags were generated from stale source counts that no
  longer match reference project metrics: risk score/ribbon/heatmap and route
  pressure counts differ.
- Reference `project.json` Overpass alignment counts do not match reference
  `outputs/overpass_route_alignment.json`.

Verification summary:

```text
Scout AI/OpenRouter plan tool call: PASS
From-zero backup restore disabled: PASS
Raw tile fallback cache TTL reuse: PASS
OCR restored to source-cache count: PASS (20 labels)
OSM PBF refs: PASS
Overpass evidence refs: PASS
CWA/GEE latest-run refs: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
Admin UI visual smoke: PASS
Focused pytest: PASS (14 passed)
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test: PASS (17 passed)
Strict reference count comparison: FAIL, blocked by reference_incoherent report
```

## Run Log: 2026-06-29 Durable Workspace Scout AI Replay

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Material root:

```text
/Users/alexwang0315/workspace/scout-local-materials/pretrip/chilai_nanhua_day1_scoutAI
```

Scout AI skill invocation:

```text
skill_id=pretrip-import-preparation
skill_manifest=skills/scout/pretrip-import-preparation.yaml
activation_decision=degrade
degraded_to=manual_pretrip_import_preparation_runbook
plan_ref=outputs/scout_ai/pretrip_import_preparation_plan.json
run_result_ref=outputs/scout_ai/pretrip_import_preparation_run_result.json
skill_run_record_ref=outputs/scout_ai/pretrip_import_preparation_skill_run_record.json
```

Issues encountered:

1. Previous `/tmp` and `/private/tmp` tryimport workspaces were not durable.
   - Symptom: earlier tryimport comparison roots were no longer present after
     restart/cleanup, so they could not be used as live comparison inputs.
   - Fix used: place the replay workspace, material root, raster tile cache,
     and rebuild logs under `/Users/alexwang0315/workspace`.
   - SOP change: future Scout AI import/preparation replays should default to
     `/Users/alexwang0315/workspace` unless the operator explicitly asks for
     temporary storage.

2. Inline local OSM PBF extraction exceeded the 30-minute target when the
   `osmium` CLI was unavailable.
   - Symptom: attempt 1 completed GPX import and reference timing, but layer
     preparation spent too long streaming the Taiwan PBF through the Python
     fallback. It was stopped by the time guard.
   - Fix used: preserve the completed OSM JSON extract and feature index, rerun
     full layer preparation without re-streaming the PBF, then convert the
     workspace-local OSM JSON extract to
     `normalized/map/osm_pbf_route_bbox_full.geojson` and set
     `osm_pbf_render_geojson_ref`.
   - SOP change: install/use `osmium` for fast PBF export, or keep the
     deterministic OSM JSON to GeoJSON fallback as a post-run repair step when
     `osm_pbf_feature_index_ref` exists but `osm_pbf_render_geojson_ref` is
     empty.

Attempt summary:

```text
Attempt 1 log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_rebuild_chilai_nanhua_day1_scoutAI_20260629T012956Z.log
Attempt 1 result: STOPPED by 30-minute target guard during inline local OSM PBF preparation
Attempt 2 log: /Users/alexwang0315/workspace/scout-local-logs/scout_pretrip_layer_retry_no_pbf_chilai_nanhua_day1_scoutAI_20260629T020356Z.log
Attempt 2 result: PASS layer preparation, route context, and Boss synthesis in 610 seconds
Attempts used: 2/10
```

Verification summary:

```text
Retired comparison root: /Users/alexwang0315/.scout-fusion/pretrip-workspaces/chilai_nanhua_day1 (deleted 2026-06-29; too old, do not reference)
Temporary tryimport comparison roots: unavailable locally
Evidence count snapshot ref: outputs/scout_ai/evidence_count_comparison.json (candidate-only counts; previous old comparison invalidated)
Checkpoint count: PASS (240)
Segment count: PASS (239)
Reference track count: PASS (23)
Route points/distance: PASS (11191 points, 112258.31 m)
Overpass evidence: PASS (517 items)
Overpass-aligned segments/checkpoints: PASS (239 segments, 240 checkpoints)
OSM PBF evidence: PASS (518 feature-index items, 518 render GeoJSON features)
MCP evidence: PASS (6 candidates)
Mileage tags: PASS (19879 tags, 29 projected anchors)
OCR evidence: PASS (20 raster labels)
Risk ribbon: PASS (4530 features)
Risk score: PASS (4077 points)
Reference segment timing: PASS (48 measurements, 8 timing segments)
CWA current-run evidence: PASS (fetched hour 2026-06-29T02:00:00Z, valid until 2026-06-30T18:00:00Z)
GEE current-run evidence: PASS current blocker surfaced (fetch_failed, no cached numeric reuse)
Layer preparation: PASS (23 requested layers ready, 0 missing, 0 blocked)
```

9112 URL:

```text
http://127.0.0.1:9112/admin/pretrip?projectId=chilai_nanhua_day1_tryimport2
```

## Run Log: 2026-06-25 CWA/GEE No-Cache Rebuild

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI
```

Final durable source:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport1
```

Policy change:

- CWA/GEE environment artifacts are current-run evidence only.
- Durable restore must skip CWA/GEE refs, CWA/GEE metadata, and derived
  environment status/count fields.
- Strict reference comparison excludes CWA/GEE status/count/hash metrics but
  still requires current workspace refs and current fetch/blocker artifacts.

Issues encountered:

1. Local macOS run tried to seed imagery under `/data/scout/raster-tiles`.
   - Symptom: layer preparation failed with
     `OSError: [Errno 30] Read-only file system: '/data'`.
   - Fix used: set
     `SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT=/tmp/scout-local-raster-tiles`.
   - Runbook implication: local macOS rebuilds must set a writable raster tile
     cache root; `/data/scout/...` is Pi/container-specific.

2. Using `/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1` as durable
   source produced strict compare diffs against `tryimport1/tryimport2`.
   - Symptom: Overpass counts differed after a successful rebuild:
     `overpass_candidate_count 517 vs 513`,
     `overpass_route_alignment_kept_gpx_point_count 3904 vs 3892`, and
     `overpass_route_alignment_snapped_point_count 1041 vs 932`.
   - Fix used: use `tryimport1` as the durable source when the target must
     compare against `tryimport1` and `tryimport2`.
   - Runbook implication: reference-equivalence must choose the same reviewed
     standard workspace that the strict comparison will use. CWA/GEE remain
     excluded from durable replay either way.

Verification summary:

```text
CWA live fetch: PASS
CWA no-cache policy: PASS
GEE no-cache policy: PASS
GEE current blocker surfaced: PASS (missing_gee_credentials_file)
Tryimport_scoutAI vs tryimport1 strict compare: PASS
Tryimport_scoutAI vs tryimport2 strict compare: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
```

9112 URL:

```text
http://127.0.0.1:9112/admin/pretrip?projectId=chilai_nanhua_day1_tryimport_scoutAI
```

## Run Log: 2026-06-26 CWA Hour Metadata And Manifest Repair

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
```

Issues encountered:

1. Manual environment-only preparation updated CWA/GEE artifacts but left the
   layer manifest with only the requested environment layers.
   - Symptom: workspace spec alignment reported missing route, segment,
     checkpoint, imagery, and risk layer records.
   - Fix used: rerun full 23-layer preparation, not environment-only
     preparation, before validation.
   - SOP change: when refreshing current-run CWA/GEE evidence in a reference
     workspace, finish with a full layer preparation or a manifest-preserving
     environment refresh path.

2. Manual full preparation tried to seed imagery under `/data/scout/raster-tiles`.
   - Symptom: `OSError: [Errno 30] Read-only file system: '/data'`.
   - Fix used: set
     `SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT=/tmp/scout-local-data/raster-tiles`.
   - SOP change: local macOS manual commands must carry the writable raster
     tile cache root; the wrapper already maps
     `SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT` into this env var.

3. Full preparation regenerated non-environment durable evidence and strict
   reference comparison failed on OCR, Overpass projection, and mileage counts.
   - Symptom: compare diffs included `raster_label_ocr_label_count`,
     `overpass_route_alignment_kept_gpx_point_count`,
     `overpass_route_alignment_snapped_point_count`, and
     `mileage_tag_alignment_count`.
   - Fix used: run final durable admin evidence restore from `tryimport1` with
     `overwrite_existing=True`; CWA/GEE refs and metadata were skipped by the
     time-sensitive environment exclusion list.
   - SOP change: reference-equivalence manual runs must perform the same final
     durable restore step as the wrapper.

Policy change:

- CWA source artifacts and CWA-derived package, factor matrix, and go/no-go
  review outputs must expose hour-precision timing metadata: API request
  attempt hour, successful fetch hour when available, provider valid-from and
  valid-until or observation hours when available, `time_precision: hour`, and
  timezone.
- Failed or credential-blocked CWA fetches must record the current attempt hour
  and leave fetch/validity hours empty rather than inventing current weather
  evidence.

Verification summary:

```text
CWA hourly metadata artifacts: PASS
CWA no-cache durable restore exclusion: PASS
Tryimport_scoutAI_1 vs tryimport1 strict compare: PASS
Tryimport_scoutAI_1 vs tryimport2 strict compare: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
Admin UI visual smoke: PASS
pnpm lint/typecheck/test: PASS
```

9112 URL:

```text
http://127.0.0.1:9112/admin/pretrip?projectId=chilai_nanhua_day1_tryimport_scoutAI_1
```

## Run Log: 2026-06-26 Latest UI Historical Import Replay

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
```

Issues encountered:

1. The rebuild wrapper completed full import/preparation but did not carry the
   local OSM PBF source into the new workspace.
   - Symptom: `osm_pbf_render_geojson_ref` and
     `osm_pbf_feature_index_ref` were missing after rebuild.
   - Fix used: restore only the `osm_pbf_*` refs and PBF-derived vector/index
     artifacts from the same timestamped workspace backup; keep CWA/GEE current
     and do not restore time-sensitive environment evidence.
   - SOP change: the wrapper or Scout skill path should pass an explicit
     `osm_pbf_path` when the target environment has a local Taiwan PBF; OSM PBF
     is local vector context and must not replace Rudy+TW OCR/cache authority.

2. The real 9112 admin app did not serve `/admin/debug`, even though the smoke
   fixture did.
   - Symptom: `/admin/debug?projectId=...` returned 404 in the live app.
   - Fix used: add the `/admin/debug` HTML route backed by
     `docs/admin/phase-3-5-runtime-debug.html`, with a regression test.
   - SOP change: live UI verification must check the actual admin app routes,
     not only `tools/admin_ui_visual_smoke.js`.

3. The debug page loaded `/debug/state` and `/debug/messages` as hard
   requirements.
   - Symptom: those runtime endpoints returned 404 in the pretrip-only local
     app, so `Promise.all` aborted before `renderDebugEvidenceMap()` and no
     OSM/Overpass/Segments layer groups appeared.
   - Fix used: add read-only unavailable fallback payloads for runtime debug
     state/messages, matching the existing `/debug/events` fallback behavior.
   - SOP change: pretrip projection map rendering must not be blocked by
     unrelated runtime debug endpoint availability.

4. OSM PBF label scaling needed live pixel validation after the latest UI
   update.
   - Symptom: the first high-zoom browser measurement showed labels could be
     oversized when CSS font/stroke declarations overrode SVG attributes.
   - Fix used: set the computed scaled `font-size` and `stroke-width` as
     important inline styles in all three admin surfaces.
   - SOP change: after changing viewBox zoom or layer toggles, verify OSM PBF
     markers and labels by actual browser pixel measurements.

Verification summary:

```text
Historical GPX importer + map preparation: PASS
Overpass refs and aligned segment provenance: PASS
OSM PBF vector refs: PASS after restoring PBF-derived refs from same-workspace backup
Terrain/risk/OCR/mileage refs: PASS
CWA refs: PASS with current hourly metadata
GEE refs: PRESENT, provider fetch result fetch_failed
Live /admin/pretrip route: PASS
Live /admin/debug route: PASS
Live /admin route: PASS
Segments toggle OSM PBF marker scale: PASS
High-zoom marker/label/route/segment pixel size: PASS
```

9112 URLs:

```text
http://127.0.0.1:9112/admin/pretrip?projectId=chilai_nanhua_day1_tryimport_scoutAI_1
http://127.0.0.1:9112/admin/debug?projectId=chilai_nanhua_day1_tryimport_scoutAI_1&tab=panel-state&event=debug_event.admin_ui_smoke.000003
http://127.0.0.1:9112/admin?projectId=chilai_nanhua_day1_tryimport_scoutAI_1
```

## Run Log: 2026-06-26 Compact Admin Map Coverage Regression

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
```

Reference workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI
```

Issues encountered:

1. The workspace artifacts were already aligned with the reference workspace,
   but the compact admin API truncated map-visible layers to 48 items.
   - Symptom: route/corridor covered the full golden GPX, while
     `segments`, `risk-ribbon`, `risk-heatmap`, and `risk-delta` rendered as a
     short subset in `/admin/pretrip`.
   - Root cause: `_compact_pretrip_project_view()` applied the generic
     evidence-list limit to map-rendered segment arrays.
   - Fix used: introduce a separate map-layer item limit for `segments` and
     risk segment arrays while keeping per-segment display geometry
     downsampled.
   - SOP change: compact API validation must compare map layer item counts and
     bbox against file artifacts, not only check that some coordinates exist.

2. The pretrip SVG segment renderer depended on compact checkpoint presence
   even when each segment already carried `display_geometry`.
   - Symptom: after fixing compact API counts, the browser still drew only 47
     segment paths because missing compact checkpoints caused most segments to
     be skipped.
   - Fix used: render segments from their own `display_geometry` first, and
     fallback to checkpoint endpoints only when display geometry is absent.
   - SOP change: admin map renderers must not require separately compacted
     evidence lists when the map layer item already includes geometry.

Verification summary:

```text
Tryimport_scoutAI_1 vs tryimport_scoutAI segment display artifacts: PASS
Tryimport_scoutAI_1 vs tryimport_scoutAI risk artifacts: PASS
Tryimport_scoutAI_1 vs tryimport_scoutAI Overpass artifacts: PASS
Live 9112 compact API map layer counts: PASS
Live 9112 SVG segments/risk bbox: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
Admin UI visual smoke: PASS
Focused pretrip/admin/debug tests: PASS
pnpm lint/typecheck/test: PASS
```

## Run Log: 2026-06-26 Overpass And OSM PBF Layer Recovery

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
```

Issues encountered:

1. Overpass vector evidence existed, but the live pretrip map rendered only the
   first 48 compact corridor candidates.
   - Symptom: `overpass_candidate_count` was 513 and
     `overpass_trail_corridor` was 414, but the SVG Overpass layer looked like
     the road/trail network was mostly absent.
   - Root cause: `_compact_overpass_evidence()` used the generic 48-item
     evidence-list limit for `corridor_candidates`, `hazard_candidates`, and
     `poi_candidates`, even though those arrays are map-rendered layers.
   - Fix used: apply the map-layer item limit to Overpass map candidates.
   - SOP change: Overpass UI verification must inspect compact API candidate
     array lengths and browser SVG path counts, not only project-level
     `overpass_candidate_count`.

2. The target workspace had no active `osm_pbf_*` refs after the rebuild.
   - Symptom: `osm_pbf_render_geojson_ref` and
     `osm_pbf_feature_index_ref` were missing from current `project.json`, so
     the admin OSM layer could not load the local PBF vector GeoJSON.
   - Fix used: restore only `osm_pbf_*` refs and PBF-derived artifacts from
     the same target workspace backup
     `chilai_nanhua_day1_tryimport_scoutAI_1.backup.20260626T082612Z`;
     live Overpass, CWA, and GEE refs were not overwritten.
   - SOP change: after rebuild, always check `osm_pbf_render_geojson_ref`,
     `osm_pbf_feature_index_ref`, `/osm-pbf-vector.geojson`, and live SVG
     `data-layer-group="osm"` path/circle counts.

Verification summary:

```text
Live 9112 compact Overpass corridor candidates: PASS (414)
Live 9112 compact Overpass POI candidates: PASS (61)
Live 9112 OSM PBF feature index: PASS (4098 items)
Live 9112 /osm-pbf-vector.geojson: PASS (4098 features)
Live 9112 SVG overpass layer: PASS (452 paths, 61 circles)
Live 9112 SVG osm layer: PASS (2823 paths, 1275 circles)
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
Admin UI visual smoke: PASS
Focused pretrip layer/admin tests: PASS
pnpm lint/typecheck/test: PASS
```

## Run Log: 2026-06-26 CP/MCP Overpass Projection Recovery

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
```

Issues encountered:

1. CP/MCP projection did not consistently overlap the Overpass/risk-ribbon
   route basis required by
   `docs/specs/pretrip-route-corridor-map-preparation.md` Spatial Policy.
   - Symptom: CP/MCP markers could remain on raw GPX coordinates even when an
     Overpass centerline existed inside the project corridor.
   - Root cause: layer preparation still used the old 50 m point projection
     tolerance instead of the route-corridor policy. A first attempted
     route-distance hint fix then over-weighted along-track distance and could
     choose a farther centerline over the geographically nearest Overpass
     centerline.
   - Fix used: pass the route corridor width into route alignment; keep
     route-distance hints only as a tie breaker for comparable nearby
     candidates; do not treat generic MCP `distance_m` as an Overpass
     centerline hint.
   - SOP change: CP/MCP validation must compare snapped counts and offsets from
     `outputs/overpass_aligned_checkpoints.json`,
     `outputs/overpass_aligned_mcp_candidates.json`, and the live compact API.

2. The live compact API hid most CP markers and stripped MCP projection
   provenance.
   - Symptom: the file artifact contained all 240 CP candidates, but the
     compact API only returned 48 CP rows; MCP lat/lon values were snapped but
     `overpass_projection` metadata was omitted.
   - Fix used: compact `checkpoints` with the map-layer limit and preserve
     `overpass_projection` for MCP candidates.
   - SOP change: map-layer compaction must use map-layer limits for rendered
     geometries, not review-card limits.

Verification summary:

```text
tryimport_scoutAI_1 CP projection: PASS (182/240 snapped_to_overpass)
tryimport_scoutAI_1 MCP projection: PASS (5/6 snapped_to_overpass; 1 explicit outlier)
tryimport_scoutAI_1 segment projection: PASS (172 endpoint-snapped, 4 normal-corridor-snapped)
Live 9112 compact CP payload: PASS (240 rows)
Live 9112 compact MCP payload: PASS (projection metadata retained)
Live 9112 Overpass compact payload: PASS (414 corridor candidates, 61 POIs)
Live 9112 OSM PBF compact payload: PASS (4098 items)
```

## Run Log: 2026-06-26 Tryimport1 Full-Route Replay Against ScoutAI_1

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport1
```

Reference workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
```

Issues encountered:

1. The first replay used the material manifest golden GPX
   `sources/gpx/golden/奇萊南華-能高越嶺步道Day1.gpx`.
   - Symptom: strict comparison failed with only 36 checkpoints, 35 segments,
     24 reference tracks, and a 14.6 km route.
   - Root cause: the reference workspace was built from the full-route golden
     `sources/gpx/reference/能高安東軍.gpx.gpx`, not the Day1 golden GPX.
   - Fix used: rerun the Codex pretrip import/preparation skill with
     `SCOUT_GOLDEN_ROUTE_GPX` explicitly set to
     `/private/tmp/scout-local-materials/pretrip/chilai_nanhua_day1_tryimport1/sources/gpx/reference/能高安東軍.gpx.gpx`.
   - SOP change: when replaying against a reference workspace, read the
     reference `outputs/import_manifest.json` first and use its golden GPX
     role/source, even if the target material manifest has another golden.

2. The successful replay still did not preserve local OSM PBF refs.
   - Symptom: `osm_pbf_render_geojson_ref`, `osm_pbf_feature_index_ref`, and
     the 4098-item PBF feature index were missing from target `project.json`.
   - Root cause: the current rebuild wrapper does not pass the local
     `--osm-pbf-path` path into layer preparation.
   - Fix used: restore only `osm_pbf_*` refs and PBF-derived artifacts from
     `chilai_nanhua_day1_tryimport_scoutAI_1`; live Overpass, risk, CWA, and
     GEE evidence from the new run were not overwritten.
   - SOP change: after every replay, compare both project metrics and
     `osm_pbf_*` refs. Do not run PBF regeneration if it would overwrite live
     Overpass evidence; use a bounded PBF-only restore until the wrapper passes
     `--osm-pbf-path` correctly.

Attempt summary:

```text
Attempt 1 log: /tmp/scout_pretrip_rebuild_chilai_nanhua_day1_tryimport1_20260626T123810Z.log
Attempt 1 result: FAIL strict counts, wrong Day1 golden route
Attempt 2 log: /tmp/scout_pretrip_rebuild_chilai_nanhua_day1_tryimport1_20260626T124100Z.log
Attempt 2 result: PASS import/preparation in 135 seconds
Attempts used: 2/10
```

Verification summary:

```text
tryimport1 vs tryimport_scoutAI_1 strict compare: PASS
Checkpoint count: PASS (240)
Segment count: PASS (239)
Reference track count: PASS (23)
Route points/distance: PASS (11191 points, 112258.31 m)
Overpass evidence: PASS (513 items; 414 trail corridors, 61 POIs)
OSM PBF evidence: PASS (4098 items)
MCP evidence: PASS (6 candidates)
Mileage tags: PASS (5526 tags, 29 projected anchors)
Risk ribbon: PASS (841 segments)
Risk score: PASS (840 points)
Reference segment timing: PASS (48 measurements, 8 timing segments)
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS with known metadata warnings only
Admin UI visual smoke: PASS
Focused pretrip/admin/debug tests: PASS (182 passed, 1 warning)
```

## Run Log: 2026-06-26 Tryimport2 Scout AI Skill Replay Against ScoutAI_1

Target workspace:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport2
```

Reference workspaces:

```text
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport_scoutAI_1
/tmp/scout-local-pretrip-workspaces/chilai_nanhua_day1_tryimport1
```

Scout AI skill invocation:

```text
skill_id=pretrip-import-preparation
skill_manifest=skills/scout/pretrip-import-preparation.yaml
plan_ref=outputs/scout_ai/pretrip_import_preparation_plan.json
run_result_ref=outputs/scout_ai/pretrip_import_preparation_run_result.json
skill_run_record_ref=outputs/scout_ai/pretrip_import_preparation_skill_run_record.json
```

Issues encountered:

1. The Scout agent builtin write tools are still narrower than the full
   connected preparation SOP.
   - Symptom: `scout_agent_builtin_tools pretrip-import-gpx` does not forward
     `material_root`, which this material-backed replay needs for MCP, DTM,
     imagery, and route-context evidence. `pretrip-prepare-layers` is also
     hard-coded to no-network mode.
   - Fix used: invoke the Scout AI skill manifest and record a SkillRunRecord,
     then use the skill's `degrade_to: manual_pretrip_import_preparation_runbook`
     fallback to run the deterministic full-preparation wrapper with explicit
     fetch enabled.
   - SOP change: either extend the Scout agent builtin import/prepare tools to
     carry `material_root`, `explicit-fetch`, imagery cache flags, and local
     OSM PBF path, or keep recording this fallback as a deliberate `degrade`
     activation decision.

2. The rebuild again omitted local OSM PBF refs.
   - Symptom: strict comparison passed for default metrics, but
     `osm_pbf_render_geojson_ref`, `osm_pbf_feature_index_ref`, and
     `osm_pbf_feature_index_feature_count` were missing from `tryimport2`.
   - Fix used: restore only `osm_pbf_*` refs and PBF-derived artifacts from
     `chilai_nanhua_day1_tryimport_scoutAI_1`; current-run Overpass, risk,
     CWA, and GEE artifacts were preserved.
   - SOP change: the reference-equivalence compare must include an explicit
     OSM PBF refs/count check until the wrapper passes the local PBF path into
     layer preparation.

Attempt summary:

```text
Attempt 1 log: /tmp/scout_pretrip_rebuild_chilai_nanhua_day1_tryimport2_20260626T131156Z.log
Attempt 1 result: PASS import/preparation in 139 seconds
Corrections after attempt 1: restored OSM PBF refs/artifacts only
Attempts used: 1/10
```

Verification summary:

```text
tryimport2 vs tryimport_scoutAI_1 strict compare: PASS
tryimport2 vs tryimport1 strict compare: PASS
Checkpoint count: PASS (240)
Segment count: PASS (239)
Reference track count: PASS (23)
Route points/distance: PASS (11191 points, 112258.31 m)
Overpass evidence: PASS (513 items; 414 trail corridors, 61 POIs)
OSM PBF evidence: PASS after PBF-only restore (4098 items)
MCP evidence: PASS (6 candidates)
Mileage tags: PASS (5526 tags, 29 projected anchors)
Risk ribbon: PASS (841 segments)
Risk score: PASS (840 points)
Reference segment timing: PASS (48 measurements, 8 timing segments)
CWA current-run evidence: PASS (ready, fetched hour 2026-06-26T13:00:00Z)
GEE current-run evidence: PASS current blocker surfaced (fetch_failed)
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS with known metadata warnings only
Admin UI visual smoke: PASS
```

## Run Log: 2026-06-29 Overpass Relation Geometry And OSM PBF Render Repair

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Attempt:

```text
Attempt 1/10
Attempt type: targeted repair and validation of an existing prepared workspace
Started: 2026-06-29T03:10:29Z
Full import rerun: not run in this attempt
```

Issues encountered:

1. Overpass/local OSM PBF hiking route relations rendered as long straight
   connector lines across the map.
   - Symptom: the live admin map showed several thick dashed lines spanning
     large parts of the viewport. Tooltip provenance pointed to
     `candidates/overpass_evidence.json`, including the relation label
     `能高安東軍縱走`, not to a raw GPX overlay.
   - Root cause: OSM `relation` member geometries were flattened into one
     `LineString`. Separate member ways were therefore connected by artificial
     line segments in both Overpass evidence and local OSM PBF rendering.
   - Fix applied: preserve relation members as `MultiLineString` when more than
     one member line is present. Update offline map context and the pretrip
     admin map payload to accept and render `MultiLineString` corridors without
     inserting connector segments.
   - Workspace correction: regenerated Overpass-compatible evidence from
     `normalized/map/osm_pbf_phase_a_raw.osm.json` into
     `candidates/overpass_evidence.json`,
     `normalized/map/overpass_vector_evidence.geojson`, and
     `outputs/layers/normalized/overpass_vector_evidence.geojson`.
   - SOP change: relation geometry QA must check for flattened relation member
     jumps. Route relation candidates should remain source-backed
     `MultiLineString` evidence unless a deterministic topology join proves the
     member ways are contiguous.

2. The pretrip page initially showed only OSM raster fallback and did not request
   the local OSM PBF vector endpoint.
   - Symptom: `/admin/pretrip` DOM contained OSM raster tiles but zero
     `.osm-pbf-line`, `.osm-pbf-point`, or `.osm-pbf-label` nodes. The local
     endpoint `/admin/pretrip/projects/<project>/osm-pbf-vector.geojson`
     returned data, but the page had not requested it yet.
   - Root cause: `reloadProjectView()` waited for `/weather-overlay` before
     calling `loadOsmPbfVectorLayer(view)`. A slow weather overlay delayed OSM
     vector loading and left the visible map on fallback tiles.
   - Fix applied: start `loadOsmPbfVectorLayer(view)` immediately after the
     first map render, then fetch the weather overlay in parallel and await the
     OSM vector promise after the weather re-render.
   - SOP change: browser smoke for local OSM PBF must verify both the vector
     endpoint response and rendered DOM counts on `/admin/pretrip`; endpoint
     readiness alone is insufficient.

3. The OSM layer still looked like generic point/line/polygon evidence rather
   than an OSM-style map.
   - Symptom: local OSM PBF vector rendering showed only generic sparse
     evidence instead of recognizable OSM-style roads, trails, route lines, and
     labels.
   - Root cause: `renderOsmBasemap()` and the three admin surfaces treated the
     local OSM PBF as generic evidence, and the style classifier read only
     direct properties while the route-bbox GeoJSON stored real OSM tags under
     `properties.tags`.
   - Fix applied: render local OSM PBF vectors directly with OSM-like classed
     casing/core strokes, merge nested `properties.tags`, keep point and line
     labels at screen-readable scale, and reapply marker/label scale after
     layer toggles and viewBox changes.
   - SOP change: OSM visual smoke must check local PBF vector class
     distribution, labels, and the absence of preview-PNG rendering. Runtime
     OSM raster tile presence is optional and must not be treated as the
     preparation cache target.

4. The evidence count comparison used a retired workspace as the old baseline.
   - Symptom: the comparison table showed `n/a` for OSM PBF, mileage, OCR,
     CWA/GEE, Boss, and route-pressure metrics under the old column.
   - Root cause: the comparison root
     `/Users/alexwang0315/.scout-fusion/pretrip-workspaces/chilai_nanhua_day1`
     was an old persistent workspace without those newer refs/metrics.
   - Fix applied: delete that old workspace at operator request and rewrite
     `outputs/scout_ai/evidence_count_comparison.json` as a candidate-only
     count snapshot with the previous comparison invalidated.
   - SOP change: do not use that retired root as a reference. If no current
     reviewed reference workspace exists locally, emit a candidate snapshot
     instead of an `old` comparison column with ambiguous `n/a` cells.

5. Environmental candidate groups showed `(0)` without the data-gap reason.
   - Symptom: the Map/Risk evidence tree showed `New Landslide Candidates (0)`,
     `Wetness / Flash Flood Candidates (0)`, `Trail Obscurity Candidates (0)`,
     and `Practical Darkness Candidates (0)` even though GEE source evidence
     had failed to fetch numeric values.
   - Root cause: the deterministic derivative artifacts correctly recorded
     `ready_with_data_gaps` and `source_metric_gaps`, but the admin projection
     and compact API did not preserve those fields on the candidate collections
     or category summaries. The UI therefore showed a bare zero that could be
     misread as low risk.
   - Fix applied: preserve `source_status`, `source_metric_gaps`, and
     `data_quality` through `pretrip_admin_view.py` and the compact API, then
     show data-gap notes in the environmental derivative tree summaries and
     empty candidate groups.
   - SOP change: when environmental candidate count is zero, verify whether the
     derivative source status is `ready`, `ready_with_data_gaps`, or
     `missing_source`. A zero with metric gaps is not evidence of low
     landslide, wetness, trail obscurity, or darkness risk.

Validation snapshot:

```text
Overpass/local OSM PBF vector endpoint: PASS (518 features; 453 LineString, 61 Point, 4 MultiLineString)
Live /admin/pretrip DOM OSM runtime tiles: NOT REQUIRED (0 observed in the final 9112 check)
Live /admin/pretrip DOM OSM PBF render: PASS (457 casing lines, 457 core lines, 61 points, 104 labels, 43 line labels)
Live /admin/pretrip OSM PBF style classes: PASS (footway 112, path 147, track 138, steps 13, road 4, route 3)
Live /admin/pretrip local PBF preview PNG use: PASS (not used as the OSM layer)
Live /admin/pretrip DOM Overpass render: PASS (456 Overpass paths)
Live /admin/pretrip compact environmental data gaps: PASS (status ready_with_data_gaps; missing sentinel2, sentinel1, dynamic_world, rainfall, terrain)
Overpass relation gap check: PASS (517 features; 4 MultiLineString relations; max independent adjacent point step 336.0 m)
Workspace spec alignment: PASS (0 errors; 5 existing workspace layout metadata warnings)
```

## Run Log: 2026-06-29 Risk Route-Base Projection And Local OSM PBF Styling

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Attempt:

```text
Attempt type: targeted risk route-base, calibrated heatmap, and admin OSM PBF validation
Full import rerun: not run in this attempt
Reference comparison root: not used; retired ~/.scout-fusion pretrip workspace was deleted earlier
```

Issues encountered:

1. Baseline and calibrated risk line overlays did not follow the Overpass route
   basis.
   - Symptom: `risk_ribbon` and `calibrated_risk_heatmap` could draw long
     straight line segments over gaps instead of following visible
     Overpass/local PBF trail geometry.
   - Root cause: the route-base builder selected nearby trail vertices and
     sorted them by nearest GPX progress. This could concatenate unrelated
     branches or route gaps, especially when the available Overpass/PBF
     coverage was incomplete.
   - Fix applied: use
     `reference_progress_projected_to_nearest_overpass_segment.v1`. For each
     reference sample, project to the nearest Overpass/local PBF trail segment
     within the Spatial Policy corridor, keep projection provenance, and mark
     unmatched samples as explicit `reference_gpx_gap_fallback`.
   - SOP change: risk generation must receive `route_corridor_m=500` for this
     route-corridor preparation flow. Do not rely on the risk package default
     corridor.

2. Fallback candidate points were being interpreted as connected route
   overlays.
   - Symptom: risk score points could still be valid candidate samples, but
     baseline/calibrated line layers made the fallback areas look like
     source-backed trail geometry.
   - Fix applied: `risk_ribbon.geojson` and
     `calibrated_risk_heatmap.geojson` now skip adjacent pairs when either
     endpoint is not `route_base_source=overpass_projection`, or when the
     geometry jump exceeds the route-base segment threshold.
   - SOP change: `route_risk.geojson` may include fallback candidate points,
     but line overlays must represent only connected Overpass-projected
     route-base samples.

3. Local OSM PBF was present but still needed style-level validation.
   - Symptom: "OSM render" could pass by feature count while the UI still
     looked like generic point/line evidence.
   - Fix applied: validate SVG classed OSM-like render output on the live admin
     surface: casing/core path counts, point counts, point labels, line labels,
     and `hasPreviewPngAsOsm=false`.
   - SOP change: OSM PBF acceptance is visual/vector-render acceptance, not
     merely ref existence. Runtime OSM raster tiles are optional in this check.

Validation snapshot:

```text
Project root: /Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
Risk route sample count: 4214
Route-base strategy: reference_progress_projected_to_nearest_overpass_segment.v1
Route-base corridor_m: 500.0
Reference samples: 5614
Projected reference samples: 5054
Fallback reference samples: 560
Selected trail features: 86
Trail feature count: 414
Trail segment count: 17943
Median reference projection distance: 7.251 m
Max reference projection distance: 498.687 m
Risk ribbon segments: 3576
Risk ribbon skipped fallback/gap pairs: 637
Calibrated heatmap segments: 3576
Calibrated heatmap skipped fallback/gap pairs: 637
Route-risk point distance to route base: median 0.0 m, p90 593.78 m, max 1309.38 m, over_35m 560
Risk-ribbon distance to route base: median 0.0 m, p90 0.0 m, max 0.0 m, over_35m 0
Calibrated-heatmap distance to route base: median 0.0 m, p90 0.0 m, max 0.0 m, over_35m 0
Live 9112 OSM tile images: 0
Live 9112 OSM PBF line casings: 457
Live 9112 OSM PBF line cores: 457
Live 9112 OSM PBF points: 61
Live 9112 OSM PBF labels: 104
Live 9112 OSM PBF line labels: 43
Live 9112 hasPreviewPngAsOsm: false
Live 9112 risk ribbon paths: 3576
Live 9112 heatmap paths: 3576
Screenshot: /tmp/scout_9112_osm_risk_after.png
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test: PASS
Focused pretrip/admin/debug/API/view pytest: PASS (177 passed, 8 subtests passed)
32-layer repo gate: PASS
32-layer workspace gate: PASS
Admin UI visual smoke: PASS
```

## Run Log: 2026-07-11 Dashboard Segment Visibility Repair

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Attempt:

```text
Attempt 1 of 10
Attempt type: read-only artifact diagnosis plus admin presentation repair
Full import or layer-preparation rerun: not run; existing Segment evidence was valid
```

Issue encountered:

- Symptom: the Dashboard Map appeared to have lost the Segment layer even
  though the Segment checkbox remained enabled.
- Root cause: the live SVG contained 239 Segment paths, but the paths used a
  dark stroke with `opacity=.24` and were inserted below 3,576 baseline risk
  paths, 3,576 calibrated paths, environmental overlays, and dense risk
  points. The canonical `MAP_LAYER_RANKS` correctly keeps Segment before risk
  overlays, so source append order alone cannot and should not override the
  contract. The Dashboard fallback renderer also redrew the full route path
  instead of consuming individual Segment display geometry.
- Fix applied: render the pretrip Segment overlay as a high-contrast dashed
  line with a dark contrast halo and keep scale-aware width at 5.6 px. Preserve
  the canonical layer rank so the bright 92%-opacity Segment line remains
  readable through the intentionally translucent risk overlays without
  changing the 32-layer order. Build fallback Dashboard Segment paths from each candidate's
  `display_geometry.coordinate_segments`; do not substitute the generic route
  path when Segment evidence is missing.
- SOP change: a layer contract PASS proves control/group structure, not human
  visibility. Segment acceptance must also verify checked state, non-hidden
  DOM group, nonzero path count, distinguishable computed stroke/opacity, and
  a live screenshot with normal risk overlays enabled.

Known warning:

- `outputs/overpass_aligned_segments.json` and
  `outputs/overpass_aligned_segment_display_geometry.json` still carry the
  older internal project id `chilai_nanhua_day1_scoutAI_test0630_1`. This UI
  repair does not rewrite evidence provenance.

Validation snapshot:

```text
Live 9099 Segment control: PASS (checked; hidden=false)
Live 9099 Segment paths: PASS (239 non-empty; 239 unique)
Live 9099 Segment style: PASS (rgb(0, 212, 255); 5.6px; dash 7/4; opacity .92; dark halo)
Live 9099 canonical order: PASS (retreat -> segments -> risk-ribbon -> risk-heatmap -> risk-delta -> risk-score)
Live 9099 Dashboard fallback Segment paths: PASS (239 paths; 239 unique ids; 239 unique d values; 0 route-path matches)
Live 9099 console/4xx errors: PASS (0 / 0)
Live 9099 horizontal overflow: PASS (false)
Focused pretrip/dashboard/layer-contract pytest: PASS (54 passed)
pnpm lint/typecheck/test: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS
Admin UI visual smoke: PASS
Screenshot: /tmp/scout-segments-dashboard-fixed.png
```

## Run Log: 2026-07-11 Overpass-Aligned Segment Provenance Repair

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Attempt:

```text
Attempt 1 of 10
Attempt type: isolated deterministic provenance rebuild plus provenance-closure replacement
Full import or in-place layer-preparation rerun: not run
Backup root: /tmp/scout-provenance-repair.fgZG1X/backup
```

Issue encountered:

- Symptom: `outputs/overpass_aligned_segments.json` and
  `outputs/overpass_aligned_segment_display_geometry.json` contained the old
  project id `chilai_nanhua_day1_scoutAI_test0630_1` in artifact identity,
  route refs, source paths, and risk-ribbon feature provenance.
- Root cause: the aligned artifacts had been retained from the older workspace.
  Their upstream risk ribbon also used the old route id, so rerunning alignment
  against the in-place ribbon would have preserved thousands of stale
  `source_feature_id` values.
- Fix applied: assemble a minimal isolated workspace from the current project
  inputs, regenerate the Overpass-backed risk centerline there, run the
  supported alignment function, and verify numeric geometry parity. Copy back
  the two requested aligned Segment artifacts plus 13 deterministic upstream
  risk artifacts required for their `source_feature_id` references and the
  baseline/calibrated risk-delta join to resolve. The producer now stamps the
  current `project_id` and
  `route_artifact_id` onto new aligned envelopes and records instead of
  inheriting stale source identity fields.
- SOP change: never repair these artifacts with a global string replacement.
  If the risk ribbon also carries an old project id, regenerate the risk
  centerline in an isolated workspace first; accept the replacement only when
  candidate ids, point geometry, alignment status counts, and candidate-only
  boundaries remain unchanged.

Validation snapshot:

```text
Aligned Segment candidates: PASS (239 ids; status distribution unchanged)
Aligned Segment display geometry: PASS (239 logical segments; 239 parts; 5,131 points)
Numeric lat/lon parity: PASS (10,262 coordinate occurrences unchanged)
Old project-id fields: PASS (4,604 -> 0 in aligned segments; 8,059 -> 0 in display geometry)
Current display identity: PASS (chilai_nanhua_day1_scoutAI / artifact.gpx.chilai_nanhua_day1_scoutAI)
Candidate boundary: PASS (candidate_only=true; runtime_safety_truth=false)
Risk provenance closure: PASS (7,152/7,152 ribbon sample refs resolved)
Aligned Segment source refs: PASS (3,648/3,648 resolved)
Aligned display source refs: PASS (7,578/7,578 resolved)
Upstream risk artifacts: PASS (13 files; stale ID count 0)
Focused alignment pytest: PASS (6 passed)
pnpm lint/typecheck/test: PASS
32-layer repo gate: PASS
32-layer workspace gate: PASS
Workspace spec alignment: PASS (0 errors; 5 existing layout-metadata warnings)
Admin UI visual smoke: PASS
Live 9099 Segment render: PASS (239 non-empty paths; control checked; no horizontal overflow)
Live 9099 risk render: PASS (3,576 baseline; 3,576 calibrated; 3,672 delta SVG paths)
Live 9099 console/4xx errors: PASS (0 / 0)
Backup retained: /tmp/scout-provenance-repair.fgZG1X/backup
```

## Run Log: 2026-07-13 CWA QPESUMS Numeric Grid Integration

Issue encountered:

- Symptom: `cwa_qpf_grid_ref` existed and rendered forecast-derived points, but
  the workspace did not contain the official past-one-hour QPE or next-one-hour
  QPF numeric cells needed to sample a team position, target, and route buffer.
- Root cause: the legacy artifact was generated from general forecast/station
  evidence and was intentionally not a QPESUMS direct-grid contract.
- Fix: keep the legacy ref for API compatibility; add validated
  `O-B0045-001`/`F-B0046-001` TWD67-to-WGS84 numeric snapshots, content-addressed
  gzip storage, a route-bbox display projection, and a compact 1.5 km
  route-buffer trend package.
- Live-data finding: the 2026-07-13 11:10 +08 QPE contained 255 valid cells in
  the route bbox, while QPF contained zero valid cells there. CWA explicitly
  describes `-99` as invalid; the route forecast therefore remains `unknown`,
  not zero rain.
- SOP change: never infer dry weather from a blank QPF overlay. Show product
  time, delay, and valid-cell count; preserve provider no-data and reduce
  confidence. Current-position evaluation requires authorized typed POST input
  and never persists raw coordinates.

Validation snapshot:

```text
CWA numeric parser/store/sampler/API focused tests: PASS
Dashboard/map CWA focused tests: PASS (38 passed)
pnpm lint/typecheck/test: PASS
32-layer repo gate: PASS
32-layer real-workspace gate: PASS
Admin UI visual smoke: PASS (desktop, 390px, 320px)
Live rainfall-grid API: PASS (cache-only; upstream fetch on read=false)
Live pretrip compact view: PASS (QPE 255 route-bbox cells; QPF 0; trend=unknown)
Recurring scheduler installed: NO
```

## Run Log: 2026-07-13 Dashboard CWA P0-P2 Completion

Target repository and workspace:

```text
/Users/alexwang0315/scout-fusion
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Issues encountered:

1. Numeric-grid and imagery artifacts did not bind a complete immutable route
   identity. An aligned route could change while a previously generated CWA
   manifest still appeared current for the project.
2. A product with no valid route cells, provider no-data, a stale observation,
   or only one half of the QPE/QPF pair could still inherit a misleading
   prepared/ready presentation.
3. Location-approval age was checked inside model validation with wall-clock
   time, which made request evaluation nondeterministic. Caller-provided
   approval references also had no server-verifiable registry.
4. Imagery freshness was a write-time snapshot. Expired or missing cache files
   could remain represented by a public asset URL, and quota pruning could
   remove part of a frame bundle.
5. The compact pre-trip project response still duplicated large OSM,
   Overpass, risk, and CWA grid structures. Dashboard and its pre-trip iframe
   each paid that cost, producing roughly 34.9 MB responses and
   100-second-class first loads on the real workspace.
6. Dashboard Weather and several debug/legacy presentations mixed live,
   partial, preview, and unavailable content without a consistent disclosure.

Root causes and fixes:

- Added `cwa_route_identity.py`: prefer the current Overpass-aligned display
  geometry, fall back to base display geometry, hash the original artifact
  bytes, and return bounded route points without changing the identity count.
- Numeric QPE/QPF publication now stages immutable frames, builds projection
  and trend in memory, holds a process/thread manifest lock, writes both
  artifacts atomically, and publishes the active manifest last. Publication
  failure restores the previous generation while still under the lock.
- Radar/satellite manifests, sampling, motion, and route-weather risk packages
  carry the same route identity, source frame ids, and deterministic pair id.
  Their active manifest and `project.json` pointers are the final two writes;
  an injected failure rolls the artifact set back.
- Read-time status now distinguishes stale, no coverage, missing data, partial,
  zero precipitation, cache missing, and unavailable. `observedAt` is compared
  to the request's injected `evaluatedAt`; position accuracy reduces
  confidence, and unusable positions force confidence to zero.
- Added a server-issued location approval endpoint with a 5-120 minute TTL,
  strict project/scope binding, privacy-safe registry, and attempted/completed/
  failed audit events. Raw submitted coordinates are response-only.
- Recompute imagery freshness on every admin read. Public asset URLs are added
  only for an existing cache file; expiry/quota pruning removes a timestamped
  frame bundle rather than individual files.
- The compact API drops duplicate subtrees, gzip-compresses the 9099 workspace
  app, and serves bounded route-grid cells from a same-project cache-only lazy
  endpoint. Current measured size is 13.5 MB raw / about 1.01 MB gzip with
  5.5-8.5 seconds server time.
- Dashboard now has eight primary information groups, route-scoped loading,
  strict project identity, explicit live/partial/preview labels, a shared CWA
  truth state, radar-only default, play guard, Asia/Taipei semantic time, debug
  DEGRADED/retry handling, mobile navigation, and a viewport-bounded CWA sheet.

SOP changes:

- Treat `projectId + routeRef + routeSha256 + sourceFrameIds + pairId` as one
  provenance unit for every new route-aligned CWA generation. Reject a
  same-project artifact whose stored route hash no longer matches the active
  route.
- Never publish the active manifest before every derived member of its pair is
  durable. Test rollback with an injected mid-publication failure.
- Never equate zero rendered cells with zero precipitation. First distinguish
  provider no-data and route no-coverage; display the data timestamp and
  read-time freshness alongside the result.
- Admin GETs are cache-only. A new CWA fetch remains an explicit preparation
  operation with network approval; stale workspace data is displayed as stale
  instead of being silently refreshed.
- Keep the full 32-layer contract. QPE/QPF remain under `cwa-qpf`; radar and
  satellite remain child overlays under `cwa-weather`.

Current live-workspace note:

- The existing July 13 CWA artifacts predate the route/pair fields. They are
  accepted through the documented legacy-read path and currently evaluate as
  stale (QPE has 255 route-bbox cells; QPF has 0). This run intentionally did
  not refetch external CWA data. The next approved explicit preparation will
  publish the new provenance format.

Validation snapshot:

```text
CWA/Dashboard focused pytest: PASS (92 passed)
Pre-trip admin API regression: PASS (81 passed)
Focused pre-trip CWA preparation: PASS (3 passed)
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test: PASS (17 passed)
Scout 32-layer repo gate: PASS
Scout 32-layer real-workspace gate: PASS
Admin Chromium smoke: PASS (desktop, 390x844, 320x720)
Live 9099 map: PASS (239 Segment paths; 1 radar image; no console/HTTP errors)
Live CWA truth: PASS (stale; QPF no coverage; unknown is not shown as zero)
Live compact payload: PASS (13.5 MB raw; about 1.01 MB gzip)
Recurring scheduler installed: NO
External CWA refetch performed: NO
```

### Post-review hardening for this run

The read-only review found that route and pair fields alone were insufficient
unless every producer and consumer enforced their ordering and identity:

- Overpass route alignment now runs before same-run CWA grid or imagery
  preparation. A CWA artifact therefore cannot be published against the base
  or previous aligned hash and become invalid when the same preparation run
  replaces the active aligned route.
- `cwa_route_identity.py` rejects a route artifact whose artifact kind,
  top-level project id, optional segment project id, or route artifact id does
  not belong to the current project. It does not relabel old-project geometry
  with the current `projectId`.
- Rainfall reads compare `pairId` and normalized `sourceFrameIds` before
  combining projection cells with manifest freshness. Legacy artifacts with
  neither field are explicitly unverified; mixed or incomplete metadata is a
  hard 422 error.
- The pre-trip compact/debug loaders now validate CWA project/route/pair
  identity and resolve project refs with root containment, including symlink
  resolution. Absolute and parent-traversal refs are rejected.
- Server-issued location approval is the default enforcement boundary.
  Unregistered caller attestations require the explicit
  `SCOUT_ALLOW_LEGACY_CALLER_LOCATION_ATTESTATION=true` compatibility flag;
  the Dashboard workspace app does not set it.
- Dashboard unavailable/partial/stale/no-coverage states remain distinct;
  failed project loads are retryable, project switching reloads a canonical
  `?projectId=...` URL, and the closed mobile navigation drawer is inert.

New regression coverage reproduces stale embedded project ids, same-run
alignment ordering, pair mixing, unregistered location approval, absolute /
parent / symlink ref escape, debug-projection project mismatch, stale UI truth,
project switching, mobile drawer accessibility, and fixture project aliasing.

## Local Dashboard workspace binding check

When `/admin/dashboard?projectId=<project_id>` renders its shell but Map,
Timeline Evidence, Navigation, and Weather cannot load workspace data, check the
server entrypoint before diagnosing the workspace artifacts.

`admin_api:create_admin_app --factory` without an injected
`pretrip_workspace_root` exposes repository fixtures only. A real workspace id
will then return `404 Pre-trip project not found`, even when
`<workspace_root>/<project_id>/project.json` exists. For a local Dashboard
preview with Workspace Operations and Connected Preparation available, launch
the Dashboard factory with the workspace parent root:

```bash
PYTHONPATH=src \
  SCOUT_PRETRIP_WORKSPACE_ROOT=/Users/alexwang0315/workspace \
  python3 -m uvicorn \
  admin_api:create_dashboard_app \
  --factory --host 127.0.0.1 --port 9099
```

Run the command from `/Users/alexwang0315/scout-fusion`. This checkout does not
currently include `./venv`; the explicit `PYTHONPATH=src` keeps the local Scout
package importable when using the installed `python3` runtime.

`phase4_admin_runtime:create_phase4_admin_runtime_app` can read the workspace,
but it does not inject the Dashboard Connected Preparation manager. Using it
for this surface makes
`/admin/pretrip/projects/<project_id>/connected-preparation` return HTTP 503
even while the main project projection succeeds.

Verify the binding before opening the Dashboard:

```bash
curl http://127.0.0.1:9099/admin/pretrip/projects
curl "http://127.0.0.1:9099/admin/pretrip/projects/<project_id>?compact=1"
curl "http://127.0.0.1:9099/admin/pretrip/projects/<project_id>/connected-preparation"
```

The first response must list the requested project; the project and connected
preparation responses must both return HTTP 200. A valid Dashboard URL is then:

```text
http://127.0.0.1:9099/admin/dashboard?projectId=<project_id>
```

### Contextual Permission authoring bootstrap

When a real workspace already has a reviewed mission graph and reference-track
timing but has no human-reviewed daily itinerary, initialize the Permission
authoring surface without pretending that the baseline is accepted:

```bash
./venv/bin/python tools/bootstrap_contextual_permission_workspace.py \
  /absolute/path/to/<project_id>
```

The bootstrap may create `outputs/planned_eta.json`, a versioned
reference-GPX baseline candidate, `normalized/permissions/contextual_permission_model.json`,
`candidates/contextual_permission_rules.json`, and
`outputs/contextual_permission/workbench_seed.json`. It must leave
`reviewed_mission_baseline_ref` and `reviewed_mission_baseline_sha256` unset.
Until human itinerary review completes, `reviewed_by_human=false`, every plan
node policy must be `review_only`, and the projection must remain
`status=degraded`, `decision=ESCALATE`, `candidate_only=true`, and
`runtime_safety_truth=false`.

`degraded` is a usable fail-closed authoring state, not the same as `blocked`.
The Dashboard must render the Baseline Authoring Workbench and its missing-input
checklist for `degraded`; reserve the blocked retry card for an unavailable or
invalid typed projection. Verify this distinction directly:

```bash
curl "http://127.0.0.1:9099/admin/pretrip/projects/<project_id>/contextual-permission-dashboard?lens=baseline"
```

Do not rerun GPX import, map preparation, risk generation, or the 32-layer
pipeline merely to create this bootstrap. Those artifacts are read-only inputs.

After `Accept Reviewed Baseline`, a previously loaded Permission projection is
expected to return `contextual_permission_projection_stale`. This is a bounded
dependency transition, not a reason to rerun the bootstrap with `--force`:
that command is for the initial no-reviewed-itinerary state and must not be used
to replace a selected reviewed baseline.

The stale Dashboard must continue to expose `Generate from Ref. GPX`, candidate
save, compact review, and acceptance. Once the newly accepted baseline contains
proposal-first day-end bindings, use its **Rebuild from reviewed baseline**
control and confirm the separate write. The equivalent API is:

```bash
curl -X POST \
  "http://127.0.0.1:9099/admin/pretrip/projects/<project_id>/contextual-permission-dashboard/rebuilds" \
  -H "Content-Type: application/json" \
  -d '{
    "expected_reviewed_baseline_sha256":"<64-char selected baseline hash>",
    "expected_admission_snapshot_sha256":"<64-char rebuild admission snapshot hash>",
    "expected_evaluator_version":"contextual-permission.projection-rebuild-admission.v1",
    "idempotency_key":"permission-rebuild-<stable-id>",
    "explicit_confirmation":true
  }'
```

Accept only a receipt reporting `rule_review_state=pending_review_only`,
`active_runtime_session_updated=false`, `runtime_safety_truth=false`, and
`departure_approval_granted=false`. The next Dashboard GET should be
`status=degraded` with the selected reviewed baseline bound and every adjustment
policy still `review_only`. If rebuild reports
`reviewed_baseline_missing_day_end_bindings`, the selected artifact is a legacy
sparse review: return to the still-available authoring workbench, generate and
accept a new proposal-first Ref. GPX baseline, then rebuild. Never infer missing
day ends from that legacy artifact.

### 2026-09-07: Dongqing newImport Permission bootstrap and Retry repair

Target: `/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`.
Always bind `?projectId=dongqing_batongguan_historic_trail_newImport` when
checking this Dashboard; the unqualified URL initially selects the Chilai
workspace and can produce an unrelated diagnosis.

Both baseline and replay GETs returned HTTP 200 with `status=blocked` and
`contextual_permission_seed_missing`. The workspace had its reviewed graph,
reference timing, route summary and weather/daylight inputs, but lacked the
Permission seed, model, rules and planned ETA. The source timing had 21 segments
and 22 ordered anchors with matching labels; it did not have Chilai's timing
alignment defect. GET and Retry deliberately do not initialize workspace files.

The existing bootstrap passed `--dry-run`; one write attempt with no `--force`
then created the six candidate/receipt artifacts and updated only Permission
refs plus `planned_eta_ref` in `project.json`. The reviewed graph, reference
timing, route summary and weather/daylight source hashes were unchanged. The
bootstrap reported six missing p75 segment estimates and four unresolved gaps.
No GPX import, map preparation, external API call or runtime activation ran.

The Retry handler separately disabled its button and only rendered in `catch`.
A successful HTTP response containing a blocked projection therefore left the
old screen and disabled button in place. The handler now reenables the button
and renders the settled state in `finally`, for both Permission and the shared
Safety / Emergency refresh control. It does not render an unrelated page if
the user navigates away while the request is pending.

Live verification: Retry remained usable while the seed was missing, then
opened the Baseline Authoring Workbench after initialization without a page
reload. Baseline and replay now return `status=degraded`, `decision=ESCALATE`,
`accepted_by_human=false`, `candidate_only=true`, and `runtime_safety_truth=false`.
All adjustment policies remain `review_only`; missing ETA, daily endpoint and
weather/daylight inputs remain visible for review.

Browser `Preview source` and `Generate typed draft` both produced the six-day
Ref. GPX proposal with `writes_performed=false`, 15 usable timing segments and
six missing p75 estimates. Save became available; Accept remained disabled.
No candidate was saved or accepted during this verification. The daily route
geometries rendered, but the Rudy backgrounds used the explicit route-only
fallback: the PNG endpoint returned `422 invalid_rudy_background` because this
workspace's selected imagery cache source is not `happyman_rudy_twmap`. This
separate imagery limitation was not bypassed by relabeling cache provenance.

Checks: the new Retry regression failed before the fix and passed afterwards
across nine result/route combinations; focused Permission/workbench/API tests
passed 64 cases (142 deselected). `pnpm lint`, `pnpm typecheck` (1 test),
`pnpm test` (19 tests), Dashboard inline JavaScript syntax and `git diff --check`
passed. Navigation freeze checks before/after reported
`NAVIGATION_FREEZE_SUSPENDED`. No layer/preparation contract changed, so full
real-workspace GIS gates were not applicable. This repairs the candidate
authoring workflow; itinerary acceptance and runtime promotion remain separate.

### 2026-09-07: Restore dedicated Rudy cache and exercise the Ref. GPX proposal

Follow-up for `dongqing_batongguan_historic_trail_newImport`: the prior Rudy
`422 invalid_rudy_background` did not indicate missing tiles. The primary
`imagery` cache is `nlsc_photo2`, while 402 prepared Rudy tiles already exist
under `rudy-twmap`. The Permission renderer previously supported only the
legacy Rudy-as-primary-imagery layout.

Resolve `rudy-twmap` through `workspace_raster_tile_cache_bundle_ref`, its
`layer_manifest_refs` and `layer_source_ids`, and the layer manifest's tile
plan. Require consistent project, layer, cache root and
`happyman_rudy_twmap` provenance. Use that layer for the single daily PNG;
retain the explicitly declared Rudy `imagery` fallback for legacy workspaces.
Do not relabel aerial tiles, change primary imagery, refetch tiles, or rerun
preparation to fix this read path. Malformed or conflicting bindings remain
unavailable. Update the owning local Dashboard process after checking that its
preparation worker is idle; no QGIS worker restart is needed.

Real browser verification covered Preview source, Generate typed draft, all
six daily evidence disclosures, Cancel save, and Confirm save. Six Rudy PNG
requests returned HTTP 200 with the expected source and
`X-Scout-Writes-Performed: false`; all 402 cache file hashes were unchanged.
The generated day intervals continuously cover 89.8271 km. Of 21 timing
segments, 15 have usable p75 and six do not. D1, D2, D5 and D6 show supported
subtotals; D3 and D4 show complete segment sums. There are five uncertainty
acknowledgments (four partial days plus D3 exceeding the strategy target) and
12 Safety handoffs (11 daily emergency-bivy candidates plus one route reversal).
Never describe the partial subtotals as whole-day or whole-trip ETAs.

The explicit browser save created
`candidates/mission_baselines/baseline.e056777b35bf380f/versions/version.71cba88516894f70.json`.
It remains candidate-only with no acceptance receipt or departure/runtime
authority. The source cache bundle, seed, reference timing, reviewed graph and
planned ETA hashes were unchanged. The whole `project.json` hash changed
earlier during this session, before candidate save; that metadata change was
not attributed by this run and was preserved.

The existing automatic-proposal acceptance gap is now independently confirmed:
`review_ready=false` because `explicit_day_end_inputs_bound=false`. The current
Generate UI does not supply pre-candidate `day_end_inputs`; post-save Quick
review and the `add_assumption` conversation patch cannot provide that missing
provenance. Missing p75 is a disclosed uncertainty, not this acceptance gate.
Do not fabricate human inputs or weaken the gate. A follow-up UI slice must
collect explicit day-end choices before regenerating a candidate. Until then,
report the real workflow as verified through candidate save, with acceptance
and rebuild tested only in isolated fixtures.

Focused results: 15 Rudy/API cases, 28 baseline/Ref-GPX/API workflow cases and
one pre-candidate endpoint-provenance qualification case passed. The current
33-layer contract verifier passed. Browser maps and source reads made no
external fetches; only candidate save wrote workspace data in this follow-up.
See `docs/admin/scout-permission-ref-gpx-guide.md` for the Chinese operator
guide and `artifacts/permission-ref-gpx-20260907-newImport/` for local evidence.

### 2026-09-07 correction: Ref. GPX means historical itinerary reconstruction

The user clarified that `Generate from Ref. GPX` must copy the prior itinerary:
daily endpoints, route, stops and CP passage timing. The preceding six-day
480-minute proposal and recommendation to add a new day-end input step were
the wrong interpretation of this mode. Keep their receipts as historical test
evidence; do not present that candidate as the reconstructed reference journey.

For the exact `dongqing_batongguan_historic_trail_newImport` workspace, existing
`reference_pace_energy_analysis.historical_route_timing.daily_departures`
already describes nine historical days. Bind and recompute those boundaries
against the same speed-filtered primary GPX. Its 5,649 points include 5,506
timestamps; the raw primary has non-monotonic cross-year observations and must
not be substituted. The 219 checkpoint events match this filtered route:
218 have exact observed passage clocks, and `cp.177` has no timestamp. Do not
replace exact passage clocks with pooled multi-track 500 m checkpoint means.

`scout_reference_gpx_reconstruction.py` is a read-only producer for these
bindings. It preserves all nine day starts/ends, eight overnight recording
gaps, missing-time ranges and CP-to-CP interval averages. The map preview
samples the same route while retaining every exact daily boundary. Existing
raw rest candidates contain durations spanning 2012 to 2020; copying them
would invent multi-year rests. Instead, derive bounded stationary intervals
from the coherent filtered track, split them at missing timestamps and long
observation gaps, and label their semantics as inferred. This dataset yields
32 such intervals. Daily elapsed time includes stops and recording gaps; it
is not pure moving time, p75 or a present-day performance promise.

The Dashboard explicitly requests `historical_reconstruction`. Missing or
inconsistent declared evidence produces `reference_itinerary_unavailable`,
never a silent 480-minute fallback. Day ends use `reference_evidence` with
source/day hashes, without fabricated human input. Save and Accept recompute
the entire bound reconstruction, including CP clocks, stops and elapsed time;
`day_end_provenance_bound` accepts this verified historical provenance. Human
review still names the exact days, disclosed uncertainties and pending Safety
handoffs. Source changes invalidate the candidate or rebuild snapshot. New
preview/generation clears the previously saved candidate and its review checks.

Real screenshot inspection also found a confirmation-sheet layout defect:
the page entrance animation leaves an identity transform on `.permission-shell`.
That makes its fixed backdrop use the entire long itinerary as the containing
block, placing Save/Accept below the visible viewport. Disable that animation
and transform only while the Permission confirmation sheet is present. Verify
the actual dialog and submit/cancel rectangles are within the viewport, not
merely present in the accessibility tree. Other Dashboard page animations stay
unchanged.

The accepted baseline and rebuilt planned ETA retain the historical day data;
Permission plan nodes carry observed elapsed duration while adjustment remains
`review_only`. No baseline acceptance grants departure or runtime authority.
The independent custom-endpoint/legacy fixture path remains available for its
existing callers; the Dashboard's Ref. GPX mode is the explicit reconstruction
path. No new GPX import, map preparation, QGIS restart or external fetch is
required for this recovery. Updated operator guidance is in
`docs/admin/scout-permission-ref-gpx-guide.md`, and source audits, test results
and live UI evidence are under
`artifacts/permission-ref-gpx-reconstruction-20260907/`.

## Run Log: 2026-07-28 Timeline Evidence Producer Repair

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

The Timeline Evidence category shells were present, but several producers
reported zero because their source extraction or lifecycle state was
incomplete. The repairs and operating rules are:

1. **Shelters and Other POI**
   - Root cause: the Overpass classifier accepted mostly node geometry, while
     huts and shelters are frequently mapped as ways or relations. Other POI
     had no bounded candidate class.
   - Repair: query and classify `nwr` shelter/hut records, derive a
     representative point for node/way/relation geometry, and keep a bounded
     Other POI allow-list.
   - Current workspace result: `Shelters = 2`, `Other POI = 91`.

2. **OSM Milestones and OSM Mobile**
   - Root cause: the PBF feature-index contract knew these categories, but the
     streaming matcher omitted `highway=milestone`,
     `information=route_marker`, and `information=mobile`.
   - Repair: retain those tags in the PBF streaming filter and route adapter.
   - Current workspace result: `OSM Milestones = 34`, `OSM Mobile = 37`.

3. **Trail Obscurity**
   - Root cause: this category depended only on unavailable GEE segment
     metrics even though the local PBF contains explicit
     `trail_visibility` evidence.
   - Repair: keep low-visibility OSM tags (`intermediate`, `bad`, `horrible`,
     `no`) as a separate candidate-only source and merge them with GEE-derived
     obscurity candidates. OSM is supporting evidence, not a replacement for
     satellite/terrain computation.
   - Current workspace result: `OSM trail_visibility candidates = 3`;
     combined `Trail Obscurity = 84` after GEE preparation.

4. **GEE route metrics and New Landslide**
   - Root cause: the previous route-feature job posted a constant manifest to
     `value:compute`, so HTTP 200 could echo the request without producing
     per-segment metrics.
   - Repair: use server-side `table:computeFeatures` with
     `Image.reduceRegions` for terrain, Sentinel-2 optical change,
     Dynamic World land cover, Sentinel-1 radar change, and rainfall.
   - Sentinel-1 must be filtered to collections containing `VV` and using
     `instrumentMode=IW`; otherwise mixed `HH/HV` imagery causes
     `Image.select('VV')` to fail. A single-band reducer returns `mean`, which
     must be normalized to
     `sentinel1_before_after_backscatter_anomaly_db`.
   - Run connected preparation with `./venv/bin/python`; the project venv
     contains the required `google-auth` service-account support. System Python
     may report `missing_google_auth_dependency`.
   - Current workspace result: `244/244` GEE route segments, `244` radar metric
     segments, package status `ready`, derivative status `ready`, and zero
     blockers. `New Landslide = 0` is now a computed zero (no segment crossed
     the candidate threshold), not missing data. Keep the category title and
     state this distinction in the UI.

5. **PBF freshness**
   - Root cause: a cached admin projection could preserve an old `fresh` state
     after the source PBF crossed its TTL.
   - Repair: recompute PBF cache age, expiry, status, and refresh requirement
     on every project GET, including projection-cache hits.
   - Current source status: `stale_refresh_recommended`; the no-network rebuild
     deliberately used the existing PBF and did not imply a fresh download.

6. **Capability Timeline and Rest Intervals**
   - These are post-trip lifecycle categories. Before a completed user GPX is
     imported, their truthful state is `not imported`, not a generic data zero.
   - The Dashboard must list completed-trip recordings from the real
     post-analysis endpoint and require an explicit operator action to build
     evidence. Never substitute the planned/reference route for a completed
     user track.

7. **Overpass route identity cascade**
   - Rebuilding Overpass alignment changes the canonical display-route hash.
     Existing CWA rainfall projection/trend and imagery/risk pairs must then be
     regenerated against that hash; strict project reads correctly reject the
     mixed provenance with HTTP 422.
   - Refresh rainfall and weather imagery as explicit connected preparation,
     then finish with the 10-layer no-network completeness set (`imagery`,
     four risk layers, `route`, `segments`, `checkpoints`, `reference-tracks`,
     and `route-notes`). A final single-layer run must not be allowed to leave
     the current layer manifest incomplete.
   - Current workspace result: compact project API HTTP 200; rainfall manifest,
     route projection, weather imagery manifest, and route weather risk package
     all use the current Overpass-aligned route identity.

Focused validation for this repair:

```text
GEE + layer preparation pytest: PASS (46 passed)
Admin view/API pytest: PASS (122 passed)
Dashboard pytest: PASS (60 passed)
OSM/Overpass pytest: PASS (14 passed)
Real OSM/Overpass rebuild: PASS (no network fetch)
Real GEE rebuild: PASS (244/244 segments; 0 blockers)
Route-aligned CWA rainfall + imagery pairs: PASS
Scout layer contract: PASS (repo 32/32; workspace 32/32)
Dashboard runtime APIs: PASS (project, operations, projection, weather)
Chrome Timeline smoke: PASS (all requests 200; 0 console errors/warnings)
Workspace/spec alignment: PARTIAL (2 unrelated existing Route Context gaps)
pnpm lint / typecheck: PASS
pnpm test: 15 passed, 2 existing docs-contract failures
Runtime safety truth mutation: NO
```

## Run Log: 2026-07-29 東清八通關 From-Zero Preparation

Target workspace:

```text
/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_scoutAI
```

This run exposed four ordering and verification details that must be part of
future from-zero preparation:

1. **Use a project-local imagery tile for the spec-alignment gate**
   - `tools/verify_pretrip_workspace_spec_alignment.py` currently defaults to
     `14/13708/7063`, which is a Chilai-specific tile. A different route can
     therefore exercise `local_parent_cache_fallback` even when its own
     prepared imagery is complete.
   - Select one exact `z/x/y` member from the generated imagery plan or local
     cache and pass it with `--imagery-tile`. For this workspace,
     `14/13708/7096` verified as `local_cache` with no errors or warnings.

2. **Collect explicit P0/P1 web evidence after the final layer run**
   - The layer-preparation post-enrichment step can replace an earlier explicit
     `web_case_evidence.json` with an empty planned-evidence artifact.
   - Run the bounded P0/P1 collector after the final 23-layer preparation, then
     regenerate Route Context, Boss, and Navigation outputs so their source
     tiers and hashes refer to the retained evidence.

3. **Require completed Overpass alignment after risk ribbon generation**
   - An initial all-layer run can report
     `skipped_missing_overpass_centerline` when route alignment is attempted
     before the risk ribbon exists.
   - Rerun alignment after the ribbon is durable, or perform a final complete
   preparation pass. Acceptance requires a completed alignment artifact; a
   skipped first pass is not a valid terminal state.

4. **Keep CWA imagery cache inside the selected project workspace**
   - A single global `SCOUT_CWA_IMAGERY_CACHE_ROOT` lets two Dashboard
     workspaces share retention, lock, and same-relative-ref state. Refreshing
     or pruning one route can therefore change what another route can render.
   - The deterministic cache root is now
     `<workspace_root>/<project_id>/cache/cwa-weather-imagery` for preparation
     and cache-only Admin reads. Global cache configuration is not consulted.
   - Existing global or legacy cache directories are not migrated or deleted
     implicitly. Re-run Connected Preparation for the selected workspace, then
     verify both the status `workspaceCacheRoot` and a real imagery asset GET.

5. **Navigation projection fingerprints must include observed-passage inputs**
   - The Navigation projection now derives a positive-unlabeled terrain-
     passage prior from `reference_track_display_geometry_ref` and
     `overpass_vector_evidence_ref` in addition to prepared DEM and route
     samples.
   - Both refs must participate in
     `navigation_terrain_input_fingerprint()`. Otherwise a changed reference
     GPX or Overpass vector artifact can leave the persisted prior apparently
     current while the Dashboard serves stale pattern counts.
   - After changing either source, explicitly compile the persisted Navigation
     projection and verify that the artifact and `project.json` fingerprints
     match. Dashboard GET remains read-only and must not hide this dependency
     behind a synchronous multi-minute rebuild.

The final workspace result was 23/23 preparation layers ready, the repository
and workspace 32-layer contract gates passed, and the project-specific
spec-alignment gate passed with zero errors and zero warnings. The UI exposes
31 pre-trip layers because `completed-track` truthfully remains absent until an
actual post-trip recording is imported.

## Run Log: 2026-07-29 Reference Timing and Completed-Track Isolation Repair

Target workspace:

```text
/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_scoutAI
```

Two inherited Chilai-Nanhua assumptions caused misleading results on a newly
prepared workspace:

1. **Reference timing must use the selected workspace route**
   - Root cause: the timing producer always used the eight named
     Chilai-Nanhua segments, so timed East Batongguan GPX files could not match
     any segment. The rebuild wrapper also invoked timing before route/layer
     enrichment was complete.
   - Repair: derive ordered timing nodes from the workspace CP/MCP route
     distances, retain route endpoints, sample long gaps at approximately
     5 km, and run timing after layer and Route Architecture preparation.
   - Time-quality gate: reject an entire source from timing aggregation when
     more than 1% of adjacent timestamps inside its original track segments are
     non-increasing. Preserve the raw source and report the rejection; never
     rewrite or silently repair its timestamps.
   - Current result: `18` route nodes, `17` adjacent segments, `10` usable
     segments, and `20` aggregate timing measurements from `3` accepted timed
     references. The golden route
     `2021_03清朝越嶺_高興_p.gpx` remains the golden geometry source but is
     excluded from timing because its non-increasing timestamp ratio is
     `0.059724`, above the `0.01` gate.

2. **Completed-track state must be workspace-local**
   - Root cause: the completed-recording endpoint and output paths were fixed
     to the Chilai-Nanhua case and a shared data root. A Dashboard opened on a
     different project could therefore see or activate the wrong case.
   - Repair: Dashboard requests now carry `projectId`; the API validates that
     identifier against the configured workspace and uses these project-local
     roots:

     ```text
     <project_root>/post_analysis/completed_trips/recorded
     <project_root>/post_analysis/completed_trips/active
     <project_root>/post_analysis/completed_trips/outputs
     ```

   - A planned, golden, or reference GPX must never be copied into this
     lifecycle as a completed track. Until an actual post-trip recording is
     placed under `recorded/<recording_id>/` and explicitly selected, the
   truthful recording count remains zero and the completed Timeline
   categories remain `not imported`.

3. **CWA route identity must hash route geometry, not volatile artifact bytes**
   - Root cause: `routeSha256` previously hashed the entire aligned-route JSON.
     A semantically identical no-network rebuild changed `generated_at`, which
     changed the raw file hash and incorrectly made current rainfall and
     imagery evidence fail closed with `route identity mismatch`.
   - Repair: hash the full ordered route coordinate sequence for
     `routeSha256`. A coordinate change still changes identity, while timestamp
     or formatting-only rewrites do not. Validation also accepts the current
     raw artifact hash for existing pre-migration CWA evidence, so untouched
     workspaces remain readable until their next connected refresh.
   - Transition rule: refresh CWA evidence once with the geometry-hash
     implementation, finish the complete no-network layer manifest, and verify
     the compact Admin API again. Do not edit identity fields in stored CWA
     artifacts by hand.

4. **Verification and no-network receipts must describe the current run**
   - Direct execution of
     `tools/verify_pretrip_workspace_spec_alignment.py` must add the repository
     root to its import path; otherwise the documented command can fail before
     checking the workspace.
   - A `no-network` layer manifest must not inherit old project-level provider
     call flags from an earlier connected run. Its manifest-level
     `network_calls_made` and `external_api_calls_made` values describe only
     the current invocation.

Focused regression evidence for this repair:

```text
Reference timing + workspace completed-track API + Dashboard contract:
PASS (7 passed)
CWA route identity: PASS (31 passed)
Final focused regression set: PASS (40 passed)
Workspace/spec alignment: PASS (0 errors, 0 warnings)
Scout layer contract: PASS (repo 32/32; workspace 32/32)
Live Dashboard/project/navigation/completed-recording endpoints: HTTP 200
Original GPX/KML mutation: NO
Runtime safety truth mutation: NO
```

## Run Log: 2026-07-30 Connected Preparation Generation Publication

Dashboard startup remains cache-only. Historical behavior enrolled the selected
workspace in a server timer from the Connected Preparation status GET. This was
superseded on 2026-08-09: GET is now side-effect free, and provider access or a
future timer begins only after an explicit operator or approved Scout AI
weather refresh.

Scheduled and explicit Connected Preparation now use this publication
boundary:

```text
published workspace generation
  -> acquire the per-project cross-process preparation mutex
  -> durably write a staging recovery journal
  -> copy-on-write staged generation
  -> assign a unique staged generation marker
  -> refresh CWA / GEE / Overpass and derived project artifacts
  -> validate project identity and the normal Admin projection
  -> acquire the cross-process generation write lock
  -> verify the published generation has not changed
  -> durably mark the journal prepared
  -> atomically exchange staged and published directories
  -> durably mark the journal exchanged
  -> remove retired generation
  -> clear the journal and release the preparation mutex
```

Operational rules:

1. The layer-preparation runner receives the staged `project_root`, never the
   published project root.
2. Dashboard project `GET` and `HEAD` requests keep one generation for the
   duration of the request. They are blocked only during the final directory
   exchange, not during provider fetching or derivation.
3. Failed runner output, invalid project identity, invalid route projection,
   or publication failure must return `publicationStatus=not-published`.
   The previously published generation remains readable.
4. Status `running` means a replacement generation is being prepared; it does
   not mean the currently visible evidence is partially updated.
5. `publicationStatus=published` and
   `publicationMode=staged-atomic-swap` confirm that the complete generation
   crossed the publication boundary.
6. On macOS, expect `cloneMode=apfs-clone` and normally
   `filesystemExchange=renamex_np`. Linux prefers reflink clone and
   `renameat2`. The locked rename fallback includes rollback.
7. The long-running preparation mutex rejects a second writer in the same or a
   different server process. It does not block Dashboard readers. The
   generation write lock is acquired only for final validation and exchange;
   it waits for shared Dashboard read locks from every participating process.
8. A competing refresh reports `status=busy`,
   `requestActivityState=waiting-external-preparation`, and
   `publicationStatus=not-published`. It must not start a second provider run.
9. Every newly published project contains
   `.scout-workspace-generation.json`. Its random generation ID distinguishes
   complete workspace generations even when `project.json` did not change and
   only evidence artifacts differ.
10. Journal and generation-marker writes are flushed before the next
    filesystem transition. Directory exchanges flush both parent directories
    before publication cleanup.

The private coordinator paths are:

```text
<workspace_root>/.scout-connected-preparation/
  staging/<project_id>.<session_id>/
  journals/<project_id>.json
  locks/preparation/<project_id>.lock
  locks/generation/<project_id>.lock
```

Do not point Dashboard at a directory below this path. Do not edit its contents
manually. A successful or safely rejected run removes its session directory.

Crash recovery:

- A `staging` journal with the original generation still published discards the
  abandoned staged session. If an external legacy writer changed only live
  `project.json` while retaining that generation marker, recovery reports
  `discarded-staging-after-live-update`; the unpublished staging session is
  removed and the newer live workspace is left untouched.
- A `prepared` journal with the original generation still published discards
  the unpublished staged generation.
- A `prepared` or `exchanged` journal whose staged generation is live keeps the
  new generation and finishes cleanup.
- If the new generation is already live but retired-generation cleanup fails,
  publication remains successful, the journal stays `active`, and
  `startupRecovery=published-cleanup-pending` preserves a deterministic retry
  on the next manager start or preparation attempt.
- If the fallback exchange moved the live directory but stopped before
  installing the staged directory, exactly one retired directory matching the
  original generation is restored.
- An invalid journal, mismatched session identity, unknown generation, or
  ambiguous retired directory is `blocked`. Recovery leaves all evidence in
  place and fails closed for operator review.
- Coordinator directories, journal files, staging sessions, and retired
  recovery candidates must not be symbolic links. Recovery never follows a
  forged link to delete or restore another workspace; lock files are opened
  without following a final symlink.
- `recoveryJournalStatus` describes whether a journal is currently `clear`,
  `active`, `active-external`, or `blocked`; `startupRecovery` records the
  latest recovery outcome separately.

All Dashboard-connected refreshes must still use the factory-owned manager.
The file locks coordinate participating Dashboard server processes, but a tool
that writes directly into a published workspace without this coordinator
remains outside the contract.

Verification:

- Cross-process mutex, cross-process reader blocking, equal-`project.json`
  generation identity, fallback rollback, and hard-process-exit recovery are
  covered in `tests/test_dashboard_workspace_publication.py`.
- Connected Preparation busy/status publication behavior is covered in
  `tests/test_dashboard_connected_preparation.py`.
- The 32-layer GIS gate is not applicable: no layer ID, layer ordering,
  preparation path, route projection, or shared map contract changed.

## 2026-07-30 Route Context one-click preparation lessons

The reusable Route Context entrypoint is
`pretrip_route_context_pipeline.py`, with the copyable contract at
`config/pretrip-route-context-pipeline.example.yaml`. It is an additive
candidate-only path; it does not replace Connected Preparation or the full
32-layer preparation contract.

Mistakes found and corrected while replaying a completely unrelated synthetic
journey:

1. A plan-only dry run must validate paths and show requested network effects,
   but it must not require `--confirm-network-fetch`. The confirmation gate is
   applied only when the run will actually fetch.
2. Resume identity cannot rely on config paths alone. The input-contract
   receipt stores SHA-256 fingerprints for the golden GPX, every reference GPX,
   and local source files; `--resume` fails when those fingerprints drift.
3. A new route must use a new `project_id`. An existing workspace without the
   matching pipeline manifest is never adopted, moved, overwritten, or rebuilt.
4. A successful deterministic render is not a content-quality pass. The run
   stops at `needs_semantic_review` after deterministic checks and accepts only
   a ChatGPT Pro review matching both `project_id` and the exact briefing
   SHA-256.
5. Route Context generation does not automatically require full map-layer
   preparation. `preparation.run_layer_preparation=false` is valid when the
   requested slice is route import, explicit P0/P1 evidence collection, Route
   Context compilation, and briefing review. Enable layer preparation only when
   those layer artifacts are in the named scope.

The required receipt sequence is:

```text
輸入契約 PASS
  -> 證據收集 PASS
  -> 確定性編譯 PASS
  -> 內容審核 PASS | NEEDS_WORK
```

`needs_semantic_review` is an intentional handoff state, not completion. The
pipeline is complete only when all four receipts are `pass`.

## Run Log: 2026-08-09 Read-Only Weather Status Writer Leak

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Issue encountered:

1. Weather qualification observed workspace generations changing about every
   ten minutes even though the browser made no connected-preparation POST.
   - Root cause: the cache-only
     `GET /admin/pretrip/projects/{project_id}/connected-preparation` endpoint
     called `ensure_scheduled()`. Merely opening Dashboard, Weather, or
     Diagnostic therefore registered an in-process timer. The later writer ran
     inside the same Uvicorn PID on a
     `scout-connected-preparation-<project_id>` thread with reason
     `scheduled-refresh`, so process-list inspection did not reveal a separate
     job.
   - Fix: the GET now calls `snapshot()` only. It never schedules, fetches, or
     writes. Explicit operator POST and approved Scout AI weather refresh paths
     still run preparation and may schedule their next service-lifetime timer
     after completion.
   - Provenance: connected-preparation status now reports the actual writer
     process id, thread name, reason, trigger kind, start time, and completion
     time. Runtime workspace-I/O audit records use the observed trigger kind
     instead of labelling every publication `scheduled-refresh`.
   - Recovery note: a timer already held by an old server process remains live
     until that manager is stopped. Restart the Dashboard service after
     deploying this fix, then prove that repeated status GETs leave
     `nextRunAt=null` and the sealed workspace byte-identical.

SOP change:

- Any status, Diagnostic, or cache-only GET must be tested for delayed effects,
  not only immediate writes. Seal the workspace, issue the GET, wait beyond the
  former timer interval or inspect manager timer state, and confirm zero
  publications. A GET that registers future work is a write-capable action and
  violates the read-only Dashboard contract.

## Run Log: 2026-08-14 Navigation Terrain RGB Targeted Preparation

Target workspace:

```text
/Users/alexwang0315/workspace/chilai_nanhua_day1_scoutAI
```

Attempt 1:

```text
Command: ./venv/bin/python navigation_terrain_raster_dem.py --workspace-root /Users/alexwang0315/workspace --project-id chilai_nanhua_day1_scoutAI
Result: FAIL before manifest or project publication
Failure point: complete raster-DEM tile selection at default zoom 13
```

Issue encountered:

1. No zoom-13 tile was fully supported by the prepared 20 m DTM grid.
   - Symptom: `TerrainDemPreparationError: no fully-supported terrain DEM tiles
     are available at the requested zoom`.
   - Cause: the source-supported corridor is narrower than a zoom-13 slippy-map
     tile in at least one dimension. The producer correctly rejected every
     tile containing alpha/nodata instead of encoding unsupported cells as
     plausible elevation.
   - Workspace effect: none; the failure occurred before the Terrain RGB
     manifest and `project.json` pointer writes.
   - Next attempt: use zoom 14 so each candidate tile covers a smaller bounded
     area, then accept only if the producer still finds a complete rectangular
     tile block and the runtime serves every allowlisted tile hash unchanged.

Attempt 2:

```text
Command: ./venv/bin/python navigation_terrain_raster_dem.py --workspace-root /Users/alexwang0315/workspace --project-id chilai_nanhua_day1_scoutAI --zoom 14
Result: FAIL before manifest or project publication
Failure point: complete raster-DEM tile selection at zoom 14
```

Issue encountered:

1. Reducing the candidate tile footprint to zoom 14 was still insufficient.
   - Symptom: the same `no fully-supported terrain DEM tiles` fail-closed error.
   - Workspace effect: none; the project hash remained unchanged and no
     `outputs/navigation/terrain_rgb` directory was created.
   - Next attempt: inspect the finite-cell mask and per-zoom support ratios
     before choosing another zoom. Do not keep retrying or relax the no-nodata
     rule without evidence.

Attempt 3:

```text
Read-only support audit: PASS
Grid: 432 x 169 cells
Finite source cells: 71,825 (98.3796%)
Zoom 13: 0/6 complete; best support 48.4375%
Zoom 14: 0/10 complete; best support 96.4844%
Zoom 15: 14/36 complete; best support 100%
Command: ./venv/bin/python navigation_terrain_raster_dem.py --workspace-root /Users/alexwang0315/workspace --project-id chilai_nanhua_day1_scoutAI --zoom 15
Result: PASS
```

Validation snapshot:

```text
Manifest: outputs/navigation/terrain_rgb/manifest.json
Manifest status: ready
Prepared block: 14 complete zoom-15 Terrain RGB tiles
Tile hash verification: PASS (14/14)
Live 9099 manifest endpoint: PASS (HTTP 200, Cache-Control: no-store)
Live 9099 sampled tile endpoint: PASS (HTTP 200, image/png)
Sampled tile response/file hash: PASS (8b7269cd4a0e57c5f4e1080895f53e19692038184d2b76fa1377a8d2d75d71d5)
Navigation projection boundary: candidate_only=true, runtime_safety_truth=false
Unsupported cells encoded as terrain: false
Network fetch: none
Full 23-layer preparation: not run
```

SOP change:

- Terrain RGB zoom is a coverage choice, not a source-resolution claim. Audit
  per-zoom alpha support first, choose the lowest zoom that yields a fully
  supported rectangular block, and continue to disclose the 20 m source-cell
  resolution. Never relax the complete-tile rule merely to make 3D render.
- Do not resize already encoded Terrain RGB channels with bilinear filtering;
  channel carry boundaries would corrupt decoded heights. For smoother 3D
  presentation, interpolate scalar elevation first, require all four source
  cells to be finite, then encode the interpolated value as Terrain RGB.
  Record `adds_source_resolution=false`; visual interpolation is not new
  spatial evidence.

## Run Log: 2026-08-22 Navigation Terrain Display Smoothing Correction

Observed defect:

- The zoom-15 Terrain RGB artifact used nearest-neighbor resampling from the
  20 m source grid. At this latitude a rendered tile pixel is substantially
  smaller than one source cell, so each source elevation became a repeated
  plateau. MapLibre connected those plateaus with abrupt walls, and the default
  `1.5x` vertical exaggeration made the staircase artifact more prominent.

Bounded correction contract:

- Interpolate scalar metres with bilinear weights before Terrain RGB encoding.
- Reject every rendered pixel unless all four contributing source cells are
  finite; retain `exclude_incomplete_tiles` and the complete rectangular block.
- Publish `visual_interpolation=bilinear`,
  `interpolation_domain=elevation_m_before_terrain_rgb_encoding`, and
  `adds_source_resolution=false`.
- Reset the Dashboard default to `1.0x`; larger exaggeration remains an
  explicitly selected visualization control.

Planned targeted preparation after focused tests pass:

```text
./venv/bin/python navigation_terrain_raster_dem.py --workspace-root /Users/alexwang0315/workspace --project-id chilai_nanhua_day1_scoutAI --zoom 15
```

Result: PASS

```text
Prepared at: 2026-08-22T09:23:40Z
Manifest: outputs/navigation/terrain_rgb/manifest.json
Source fingerprint: 1eaa51668ef9579aa9743ef1b800c2c223cdcef8cf8e79b63ddc2bc5b7519b83
Prepared block: 14 complete zoom-15 Terrain RGB tiles
Resampling: bilinear_elevation
Visual interpolation: bilinear
Adds source resolution: false
Unsupported cells encoded as terrain: false
Candidate only: true
Runtime safety truth: false
```

Old/new artifact roughness audit across all 14 tiles:

```text
nearest: zero-adjacent-delta ratio 78.22%, p95 14.5 m, p99 22.5 m, max 67.3 m
bilinear elevation: zero-adjacent-delta ratio 1.17%, p95 4.6 m, p99 6.1 m, max 14.0 m
```

Browser qualification on an isolated fresh-code runtime (`127.0.0.1:9101`):

- Default `1.0x` and explicit `1.5x` views both rendered a continuous terrain
  surface without the former repeated-cell staircase.
- MapLibre reported `DEM DECODED`; center elevation was non-zero.
- The 2D map still contained all displayed Golden Route samples after fit.
- Effective 500 px narrow viewport had zero horizontal overflow.
- Console errors/warnings: none. Terrain DEM tile responses: HTTP 200.
- Focused Dashboard/MapLibre/DEM tests: 113 passed. Pre-trip API tests:
  101 passed. Ruff and diff checks: passed.

## Run Log: 2026-08-24 Dongqing Navigation Preparation Repair

Target workspace:

```text
/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport_v2
```

Observed defect before repair:

- `normalized/terrain/dtm_coverage_summary.json` catalogued 146 intersecting
  20 m DTM candidate tiles, but
  `outputs/navigation/terrain_rgb/manifest.json` was absent.
- Navigation therefore reported Golden Route DEM coverage `0/240`, while the
  vector-only projection still exposed ridge, valley, saddle, slope, and risk
  candidates. The combined display looked prepared even though the elevation
  sampling and 3D terrain path were unavailable.
- The workspace also had accepted precomputed named-point evidence, but the
  Navigation source ledger only projected the DTM and GPX refs. Historical
  source pages and ordered route-position clues were omitted.
- QGIS remained disabled and no QGIS/GRASS/GDAL runtime was available. This is
  a separate explicit capability gap and must not be represented as prepared
  GIS evidence.

Root cause and preparation correction:

1. Full layer preparation compiled the Navigation vector projection but did
   not invoke `navigation_terrain_raster_dem.py`. It now runs Terrain RGB before
   projection whenever `terrain` is requested.
2. Terrain RGB preparation evaluates zoom 13, 14, and 15, measures displayed
   Golden Route sample coverage for every ready candidate, and retains the
   highest-coverage result. Coverage ties prefer the lower zoom. The selection
   retains the no-nodata rule and continues to disclose the 20 m source-cell
   resolution.
3. If a dedicated historical-route ledger is absent, accepted HTTP pages from
   the existing named-point evidence package are projected as bounded source
   metadata. Named points ordered by route distance become fallback clues.
   Fixture/precomputed and no-live-refresh limitations remain explicit.
4. Clone removes reference GPX inputs whose content hash matches the Golden
   Route or an earlier reference. It does not delete files from an existing
   workspace or mutate the source workspace.
5. Raster-label OCR now runs only when `imagery` is part of the preparation
   request. Connected weather/geology refreshes and other partial layer updates
   do not freeze or unnecessarily recompute Navigation evidence.

Bounded recovery plan:

- Repair the existing v2 workspace in place by generating only its Terrain RGB
  artifact and recompiling its Navigation projection. Do not create v3, rerun
  GPX import, or overwrite the source workspace.
- Preserve CWA and geology as refreshable runtime evidence. This repair is
  limited to static imported/prepared route evidence.
- Keep QGIS state `DISABLED` / `NOT_STARTED` until an authorized, reachable
  QGIS worker and reviewed GRASS/GDAL path exist; never fabricate those
  artifacts to make the page look complete.

Repair attempt 1:

```text
Zoom: 13
Result: READY
Complete Terrain RGB tiles: 20
Golden Route displayed samples inside DEM bounds: 142/240 (59.2%)
Source cell resolution: 20 m
Unsupported cells encoded as terrain: false
```

The first supported zoom is valid but does not provide enough route coverage
for this long east-west route. Before accepting the workspace, compare zoom 14
and 15 with the same complete-tile/no-nodata rule and retain the result with the
highest displayed Golden Route sample coverage. A lower zoom is not preferred
when its selected complete rectangle leaves materially more of the route
outside DEM bounds.

Repair attempt 2:

```text
Zoom: 14
Result: READY
Complete Terrain RGB tiles: 110
Golden Route displayed samples inside DEM bounds: 150/240 (62.5%)
Source cell resolution: 20 m
Unsupported cells encoded as terrain: false
```

Zoom 14 improves route coverage by only eight displayed samples. Continue with
the bounded zoom-15 comparison before selecting the final artifact.

Repair attempt 3 and selected result:

```text
Zoom: 15
Result: READY and selected
Complete Terrain RGB tiles: 506
Complete candidate tiles before rectangular-block selection: 598
Golden Route displayed samples inside DEM bounds: 168/240 (70.0%)
Source cell resolution: 20 m
Unsupported cells encoded as terrain: false
```

Live verification on a fresh-code Dashboard runtime at `127.0.0.1:9103`:

- Navigation API: HTTP 200, `ready_with_terrain_hierarchy`, projection `ready`.
- Source ledger: 15 sources (`P0=4`, `P1=7`, `P2=4`) and seven ordered
  `named_point_route_positions` clues. The UI now labels these as route-distance
  ordered named-place clues instead of incorrectly saying no chain exists.
- 2D status: `DEM READY · 506 TILES · 20m`; displayed Golden Route coverage
  `168/240 · 70%`.
- 3D status: `MAPLIBRE 3D TERRAIN · DEM DECODED`; sampled Terrain RGB network
  requests returned HTTP 200 and the canvas rendered nonblank.
- Structure, slope pressure, risk terrain, retreat direction, and Shadow event
  lenses all retained the same ready DEM while exposing distinct bounded data.
- QGIS remained `DISABLED · NOT_STARTED` with zero QGIS artifacts. Its missing
  latest-workflow request remains an expected HTTP 404 and is not a DEM failure.
- Source GPX hashes before and after repair were identical. No v3 workspace was
  created and the source workspace was not mutated.
- The real-workspace 32-layer contract verifier passed all 32 layers with no
  errors or warnings.
- Final focused regressions: 25 passed. Ruff and scoped diff checks also passed.

## 2026-08-21 MapLibre and QGIS MCP evidence slice v0.1

This integration is additive and disabled by default. QGIS is a spatial
evidence engine, never Scout's safety authority. Processing and render success
do not establish terrain truth, trail existence, passability, legality,
navigability, or safety.

### Discovered implementation map

| Existing component | Reused | QGIS integration point |
| --- | --- | --- |
| `docs/admin/scout-dashboard-v0.1.html` Navigation / Split Review workbench | Yes | Bounded GIS Analysis, artifact metadata, MapLibre candidate preview, and QGIS Visual Review sections |
| `docs/admin/phase4-pretrip-planning.html` and `phase-3-5-runtime-debug.html` map surfaces | Yes | Same local MapLibre runtime and evidence adapter; no second map architecture |
| `admin_api.py` FastAPI pre-trip router | Yes | Browser-facing status, capabilities, workflow, cancel, review, artifact metadata, and render routes |
| `tools/dashboard_workspace_app.py` real-workspace 9099 entrypoint | Yes | Loads QGIS configuration only in the Scout backend process |
| `navigation_terrain_projection_store.py` | Yes | Route geometry source before the reviewed mission-graph fallback |
| `normalized/terrain/dtm_coverage_summary.json` | Yes | Bounded DEM source catalog, hashes, and source-resolution metadata |
| workspace-relative `outputs/` refs and atomic JSON writes | Yes | Persistent workflow identity, candidate artifacts, and reload recovery |
| `runtime_audit_ledger.py` | Yes | Existing workspace-I/O and terminal background-job audit records |
| existing candidate-only terrain semantics | Yes | QGIS contracts retain `candidate_only=true`, `runtime_safety_truth=false`, and `operational=false` |
| existing browser polling pattern | Yes | Queued/running worker state polling and reconnect after reload |
| connected-preparation manager | No direct reuse | It is preparation-specific rather than a generic durable GIS job API; the bounded worker uses private file-backed run state |
| existing pytest and Dashboard browser qualification | Yes | Contract, adapter, worker, API, map, disabled/unavailable/fixture, reload, and responsive checks |

### Runtime boundary

```text
Scout Dashboard
  -> Scout FastAPI `/admin/pretrip/projects/{project_id}/spatial/qgis/*`
  -> `QgisSpatialBackend`
  -> authenticated Scout QGIS Worker
  -> fixed MCP tool and QGIS Processing algorithm allowlists
  -> QGIS Agent MCP
  -> QGIS application/plugin bridge
  -> candidate artifacts in `outputs/spatial/qgis/{workflow_run_id}/`
  -> shared MapLibre evidence adapter / QGIS Visual Review
```

The browser never receives the worker URL or bearer token and never calls MCP.
The worker has no generic tool-forwarding route. It denies arbitrary Python,
shell commands, unrestricted filesystem access, plugin installation, implicit
network acquisition, and algorithms outside the fixed allowlist.

### Configuration

Dashboard/backend configuration:

```text
SCOUT_QGIS_ENABLED=false
SCOUT_QGIS_FIXTURE_MODE=false
SCOUT_QGIS_WORKER_URL=http://127.0.0.1:9876
SCOUT_QGIS_WORKER_TOKEN=<shared secret of at least 32 characters>
SCOUT_QGIS_TIMEOUT=5
SCOUT_QGIS_LOCAL_ENDPOINT_REQUIRED=true
```

Worker-only configuration:

```text
SCOUT_QGIS_WORKER_ENABLED=true
SCOUT_QGIS_WORKER_TOKEN=<same shared secret>
SCOUT_QGIS_WORKER_ROOT=~/.scout-fusion/qgis-worker
SCOUT_QGIS_SOURCE_ROOTS=<bounded DEM roots separated by the OS path separator>
SCOUT_QGIS_WORKER_TIMEOUT=120
SCOUT_QGIS_WORKER_REQUEST_MAX_BYTES=2097152
SCOUT_QGIS_MCP_COMMAND_JSON=<JSON string array, never a shell command>
SCOUT_QGIS_MCP_PYTHONPATH=<optional bounded upstream source path>
```

Keep the worker and MCP bridge on localhost unless an authenticated Scout
worker is deliberately deployed on another host. The v0.1 adapter requires
HTTPS when the localhost-only policy is explicitly disabled.

### Workflow and evidence states

`terrain_context_preview.v1` validates route input, inspects the QGIS session
and CRS, prepares route geometry, loads bounded DEM inputs, runs the allowlisted
GDAL slope algorithm, renders the QGIS canvas, and exports candidate artifacts.
Its independent statuses are:

```text
processing_status -> render_status -> machine_review_status
                  -> visual_review_status -> human_review_status
```

`completed / completed / not_started / pending / pending` is expected before
review. Recording evidence review changes artifact status to
`reviewed_evidence`; it does not change candidate, operational, or runtime
safety authority.

### 2026-08-23 macOS live terrain preview repair

The Chilai workspace's DTM summary still referenced a retired repository path.
Before a live run, copy only the hash-matched `.grd`/`.hdr` pairs into the
project-bounded `sources/dtm/` tree and update the summary to those bounded
paths. Do not weaken the worker source-root policy to follow stale paths.

The government XYZ grids report a positive north/south pixel step. GDAL VRT
mosaicking rejects that orientation, so `terrain_context_preview.v1` now uses
the exact allowlisted `gdal:warpreproject` contract to create 20 m north-up
GeoTIFF inputs with nearest-neighbour resampling before mosaicking. This changes
row orientation only and records `adds_source_resolution=false`.

The preview also exports the WGS84 route through the existing bounded QGIS
vector-export path to an EPSG:3826 GeoPackage before canvas rendering. Loading
the WGS84 route directly into the EPSG:3826 capture canvas left the layer in the
project tree but did not paint it in this QGIS MCP session.

On the observed macOS AppTranslocation session, the MCP plugin's QWidget canvas
capture returned a framed blank image while QGIS was fully occluded. Scout now
rejects that frame-only image using the dominant interior background and keeps
the run as `RENDER_FAILED`. The successful live capture required QGIS to be
foregrounded outside Scout; no OS activation, arbitrary UI invocation, Python,
or shell capability was added to the worker. A layout/offscreen render path is
future promotion work.

### Qualification and constrained-host benchmark

Reusable preparation-only benchmark:

```text
python3 tools/qgis_preparation_benchmark.py \
  --project-root /path/to/workspace/project \
  --project-id <project_id> \
  --iterations 3 \
  --output /path/to/qgis-preparation-benchmark.json
```

The report must say `qgis_processing_executed=false` and `mcp_invoked=false`.
It measures only project loading, route resolution, bounded DEM selection and
hashing, and worker-request serialization. A Mac result is not Raspberry Pi
evidence.

2026-08-21 observation:

- Mac host: x86_64 Darwin, not Raspberry Pi.
- Input: 240 route points and 12 reported 20 m DTM sources, 5,505,408 bytes.
- Three-run preparation total p50: 99.231 ms.
- DEM selection/hash p50: 18.981 ms.
- Raspberry Pi result: `UNKNOWN`; `scout.local` resolved, but TCP 22 and
  BatchMode key SSH both failed with `No route to host`.
- Real QGIS result on this Mac: MCP 0.4.8 initialized, but the QGIS application
  and plugin bridge were unavailable. The real workflow failed closed as
  `QGIS_UNAVAILABLE`; no QGIS-derived artifact was fabricated.
- Fixture result: completed and browser-reviewed, explicitly marked fixture,
  synthetic, and non-runtime.

### 2026-08-22 Raspberry Pi 5 full-route DEM cost observation

This observation used the real filtered route and 20 m DTM coverage for
`dongqing_batongguan_historic_trail_scoutAI`. It is Pi-bounded execution
evidence only. It does not validate geomorphology, hydrology, terrain risk,
navigability, or safety.

- Host: Raspberry Pi 5 Model B Rev 1.1, arm64, 8 GB RAM.
- Route input: one continuous filtered GPX track, 5,649 points; the largest
  adjacent-point distance was 147 m. This avoided the earlier multi-track
  ordering failure.
- Mosaic input: 99 coverage-manifest tiles, 45,283,789 source bytes, true 20 m
  resolution, EPSG:3826, and a 500 m route-bbox margin.
- Mosaic output: 1,821 x 1,305 = 2,376,405 cells and 4,912,104 bytes.
  `gdalwarp` took 1.673 seconds with 84,848 KB maximum RSS. Provenance hashing
  and mosaic preparation are recorded separately from analysis.
- Raster validity: 69.17 percent valid pixels and 30.83 percent NoData. White
  gaps in the QGIS preview are missing source coverage, not flat or safe
  terrain. Never interpolate these gaps into new spatial evidence silently.
- Three full processing attempts took 26.547 to 28.065 seconds, with a 26.980
  second median. The final run with a valid QGIS capture took 28.065 seconds.
  Ten reported artifacts totalled 123,303,074 bytes. CPU temperature moved
  from 50.1 C to 52.9 C; swap remained at the already allocated 2 MB.
- The largest command RSS was 132,656 KB for `gdal_contour`. The 20 m contour
  GeoJSON took 10.908 seconds and 71,963,162 bytes, so contours dominate this
  slice's time and retained storage. Do not enable full-resolution contour
  export by default without a retention or simplification policy.
- GRASS `r.geomorphon` took 7.475 seconds. `r.watershed` took 2.221 seconds;
  its output remains unreviewed candidate evidence, including edge-effect and
  negative-accumulation semantics.
- The headless QGIS baseline after a clean restart was 458,096 KB RSS plus
  63,680 KB for Xvfb. After loading the route and slope layers it was 509,024
  KB plus 63,872 KB for Xvfb, approximately 51 MB incremental QGIS RSS.
- A long-lived QGIS session retained an older slope layer and produced a blank
  capture. A clean session then returned no image payload on the first visual
  review request. The bounded worker now permits one fixed canvas-screenshot
  fallback and independently parses the PNG. A render passes only when at
  least 0.1 percent of interior pixels differ materially from the background.
  The final capture passed with 56,924 content pixels, or 27.7 percent.
- Valid classification: this exact 2.4-million-cell, 20 m route-bbox workflow
  is a Pi-bounded terrain-evidence operation. Larger mosaics, finer native DEM,
  multi-route concurrency, and long-running service reliability remain
  unmeasured and must not inherit this classification automatically.

Evidence:

```text
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r1/mosaic-preparation-full-route-c500m-v1.json
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r3/benchmark-report.json
workflow run: dongqing.full-route-c500m-20m-20260822.r3
QGIS worker run: qgis-worker-20260822T041331167386Z-361fcae6c1
```

### 2026-08-22 Dongqing DEM completion and full-Taiwan comparison

The operator supplied `/Users/alexwang0315/Downloads/twdem`. The source
archive checks passed before extraction. These results refine the earlier
69.17 percent observation: the Hualien-only mosaic already returned a DEM
value for all 5,649 GPX points. Its gaps affected the surrounding route-bbox
context, not the route line itself.

- Adding the Nantou county tiles scanned 1,411 headers and selected 146 source
  records: 99 Hualien and 47 Nantou. Thirteen county-boundary tile IDs occurred
  in both packages; their `.grd` hashes were identical. The bounded mosaic tool
  therefore keeps `county:tile_id` source identities and supports repeated
  `--source-root` arguments. It never trusts manifest paths outside those
  roots.
- The selected Hualien plus Nantou transfer was 66,849,489 bytes and took 8.97
  seconds over the observed local network. Mosaic preparation took 2.221
  seconds with 92,048 KB maximum RSS. Bbox validity rose to 89.78 percent while
  GPX-point coverage remained 100 percent.
- The full-Taiwan archive was 268,985,841 bytes and transferred to the Pi in
  27.45 seconds. Pi extraction took 6.417 seconds and produced a 756,870,860
  byte GeoTIFF. Keeping both zip and TIFF uses 1,025,856,701 bytes before
  route-specific outputs.
- The full-Taiwan TIFF's embedded CRS did not resolve reliably to EPSG:3826;
  `gdalsrsinfo` returned only low-confidence ESRI candidates. The same archive's
  `Metadata.xml` explicitly states `EPSG:3826 (TWD97/121 zone)`. The bounded
  crop therefore assigns EPSG:3826 from that sidecar and records its hash. Do
  not infer or silently repair this CRS without the source binding.
- Cropping the full-Taiwan TIFF to the same 1,821 x 1,305, 20 m, 500 m-margin
  bbox took 0.410 seconds with 128,864 KB maximum RSS. The 7,060,402-byte
  output had 100 percent valid bbox pixels and 100 percent valid GPX points.
  Nearest-neighbour cropping adds no source resolution.
- The completed full-Taiwan `r6` baseline took 36.510 seconds. After making
  `operational=false` explicit on the MapLibre collection and both candidate
  features, final real run `r8` took 36.259 seconds and produced ten reported
  artifacts totalling 168,854,985 bytes. The largest command RSS was 140,704
  KB for 20 m contours. CPU moved from 50.1 C to 54.5 C and swap stayed at
  4 MB. QGIS processing and rendering completed; machine, visual, and human
  review remain pending.
- Compared with the Hualien-only `r3`, full bbox validity improved by 30.83
  percentage points, end-to-end analysis wall time increased by 30.1 percent,
  and retained artifact bytes increased by 36.9 percent. The larger evidence
  area, especially contours and geomorphons, is the main recurring cost. The
  full source transfer/extraction is a first-use deployment cost.
- Failed `r4` is retained as interruption evidence. GRASS failed because the
  restarted container had `HOME=/` and could not create `/.grass8`; this was
  an environment configuration failure, not a Pi resource failure. `r5`,
  `r6`, and `r8` used the bounded writable `HOME=/tmp/scout-home` and completed.
- Failed `r7` is also retained. It detected version drift after the current
  QGIS worker was copied over older Pi-side typed contracts. Synchronizing the
  worker's two direct contract modules restored import compatibility; `r8`
  then completed without changing the plugin or tool allowlist.

Deployment interpretation:

1. When roughly 757 MB retained source storage is acceptable, keep the verified
   full-Taiwan TIFF on the Pi and generate small route-specific crops locally.
   This delivered complete visual context and the fastest crop in this test.
2. For constrained transfer/storage, sync only selected county tiles. The UI
   must preserve visible NoData gaps and report the measured coverage; it must
   not interpolate them into new evidence.
3. Full DEM coverage and successful GIS processing remain candidate evidence.
   They do not prove route existence, terrain interpretation, navigability,
   legal access, hazard status, or safety.

Evidence:

```text
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r4/dem-source-selection.json
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r5/benchmark-report.json
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r6/full-taiwan-dem-preparation-report.json
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r6/dem-completion-comparison.json
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r6/benchmark-report.json
artifacts/pi-gis-benchmark/dongqing.full-route-c500m-20m-20260822.r8/benchmark-report.json
workflow run: dongqing.full-route-c500m-20m-20260822.r8
QGIS worker run: qgis-worker-20260822T045556830991Z-a57a0470df
```

Qualification after DEM completion:

- The focused DEM, QGIS worker/backend, preparation, terrain benchmark, and
  import suite passed `92` tests; one optional upstream-QGIS-source test was
  skipped because `SCOUT_QGIS_UPSTREAM_SRC` was not configured.
- Ruff, Python bytecode compilation, scoped diff whitespace checks, and the
  existing 32-layer contract verifier passed. The verifier reported all 32
  layers valid for the Dongqing workspace.
- A separate live host/container probe identified Raspberry Pi 5 Model B Rev
  1.1 (`aarch64`), QGIS 3.44.13, QGIS Agent MCP plugin 0.4.9, GRASS GIS 8.4.1,
  and GDAL 3.10.3. The `r8` workflow metadata retains `qgis_version=unavailable`
  because the MCP snapshot did not report that field; the external probe is not
  silently substituted into workflow provenance.
- The `r8` QGIS preview was inspected as candidate visual evidence and passed
  the deterministic non-blank render check. Dashboard browser qualification
  was not rerun because this DEM-completion step did not change browser-visible
  behavior; it remains a separate integration gate.

### Pi multiscale morphology and candidate line extraction (2026-08-22)

`terrain_feature_stack.v1` now produces three fixed geomorphon scales (5, 10,
and 20 cells), two-of-three ridge/valley consensus masks, thinned ridge and
valley vectors, and a candidate flow-channel network. These are terrain
morphology evidence only. In particular, a flow-channel line does not confirm
observed water, a ridge/valley line does not confirm a usable route, and none
of these artifacts changes runtime safety or operational state.

The real Pi sequence established two dependency constraints:

- `r38` reached `r.stream.extract`, then the GRASS 8.4.1 native process
  segfaulted during stream extraction and created neither declared output.
  Scout preserved this as `PROCESSING_FAILED`; do not re-enable this algorithm
  in the v0.1 allowlist on this image without a separate dependency fix and
  qualification.
- `r39` and `r40` showed that `r.watershed stream=` can be entirely NoData for
  a narrow route corridor. This agrees with the GRASS documentation that edge
  areas may not form complete exterior basins. It is not evidence that no
  channel exists.
- `r42` therefore used the already produced flow-accumulation raster and the
  fixed expression `if(abs(A) >= 25, 1, null())`, followed by `r.thin` and
  `r.to.vect`. Negative accumulation remains explicitly flagged as potentially
  underestimated outside-region inflow. This bounded fallback is a candidate
  flow-channel morphology, not a hydrologically validated river network.

Real `r42` evidence:

```text
benchmark run: chilai_nanhua_day1.pi-gis-20260822.r42
QGIS worker run: qgis-worker-20260822T061554705299Z-fd6670fc70
report: artifacts/pi-gis-benchmark/chilai_nanhua_day1.pi-gis-20260822.r42/benchmark-report.json
QGIS render: artifacts/pi-gis-benchmark/chilai_nanhua_day1.pi-gis-20260822.r42/qgis-worker/runs/qgis-worker-20260822T061554705299Z-fd6670fc70/qgis_render_preview.png
```

The run completed in 22.426 seconds on the Pi, with temperature moving from
49.6 C to 51.8 C and swap unchanged at 4 MB. It exported 16 hashed QGIS worker
artifacts. The WGS84 candidate vectors contained 72 ridge features, 90 valley
features, and 160 flow-channel features; the combined MapLibre collection held
452 features. All artifact hashes and all MapLibre authority flags were
verified locally. Processing and render completed, while visual and human
review remain pending.

#### 2026-08-23 current Golden Route comparison gate

The macOS QGIS LTR profile had `grassprovider=true`, but the application bundle
and host PATH contained no GRASS executable. MCP capability discovery therefore
returned no `grass:*` algorithms, and the live `terrain_feature_stack.v1` run
failed closed at `capability_discovery` with `UNSUPPORTED_TOOL` for
`grass:r.slope.aspect`.

Do not substitute the earlier Pi `r42` vectors for the current Dashboard route.
Its request route starts near `121.183556, 23.948778`, while the current Golden
Route starts near `121.211673, 24.053151`; they are different evidence scopes.
Any cross-engine comparison must bind the exact filtered Golden GPX hash, DEM
hash or manifest fingerprint, corridor, algorithm parameters, and output CRS.
When those bindings differ, the QGIS layers are stale/incomparable and must not
be shown as a competing route or current terrain comparison.

References:

- GRASS `r.watershed`: https://grass.osgeo.org/grass-stable/manuals/r.watershed.html
- GRASS `r.stream.extract`: https://grass.osgeo.org/grass-stable/manuals/r.stream.extract.html

### Navigation MapLibre terrain refresh (2026-08-25)

This section records the former presentation path. The Python bitmap terrain
fallback described below was superseded by the 2026-08-26 QGIS/GRASS activation
and must not be selected as an active terrain processor.

Before changing the Navigation 2D/3D composition, inspect the read-only
`navigation-terrain-intelligence` response and the Terrain RGB manifest
separately. A stale projection does not mean the DEM is unavailable. The
Dongqing runtime returned `persisted_projection_stale_or_invalid` after
`mcp_named_point_evidence_ref` became part of the projection fingerprint, while
the bounded Terrain RGB source remained ready.

For this refresh:

- rebuild `outputs/navigation/terrain_rgb/manifest.json` with the current
  `bilinear_elevation` visual resampling contract;
- preserve `adds_source_resolution=false` and never fill unsupported cells;
- compile the Navigation projection only after all fingerprinted source refs
  are stable;
- verify the API reports a persisted ready projection and the same Terrain RGB
  fingerprint before browser qualification;
- retain 2D full-route fit and 3D local DEM fit as separate camera authorities.

This refresh changes presentation evidence only. Elevation tint, hillshade,
contours, ridge/valley candidates, and visual interpolation remain
`candidate_only=true`, `runtime_safety_truth=false`, and do not establish route
existence, walkability, safety, or an operational event.

The former Python fallback painted local DTM cells into route-corridor bitmaps.
It is retained only as historical diagnosis and is no longer an authorized
terrain-analysis path. Standard terrain raster layers now require the bounded
QGIS Processing + GRASS/GDAL workflow. When that worker is unavailable,
preparation remains `awaiting_qgis_grass_processor` and emits no synthetic
terrain raster. When the full DEM source itself is absent, preparation reports
`source_unavailable`; it does not fall back to route-aligned or bitmap terrain
inference.

### QGIS/GRASS standard rectangle activation (2026-08-26)

The Dongqing Golden Route was processed on the Raspberry Pi through the
Scout-owned worker and fixed tool allowlists. The real successful worker run is:

```text
workflow run: qgis-worker-20260826T075524298258Z-9cbb89b355
QGIS: 3.44.13
GRASS: 8.4.1
GDAL: 3.10.3
QGIS Agent MCP plugin: 0.4.9
input DEM SHA-256: 59e5e980000d6e3f5a7734c6af197934a1a5432482b6caa789a1ec90b624015d
input DEM: EPSG:3826, 20 m
```

The output rectangle is TWD97 `241980..278320` by `2580580..2606540`, or
WGS84 `120.9214363680,23.3275359875,121.2774205418,23.5621855416`.
Elevation tint, hillshade, slope shading, and contours share that exact extent.
The raster grid is `1817 x 1298` cells; contour display is `3634 x 2596` pixels
without claiming additional source resolution.

Actual allowlisted processors were `gdal:cliprasterbyextent`,
`grass:r.slope.aspect`, `grass:r.relief`, `grass:r.contour`,
`gdal:rasterize`, `gdal:colorrelief`, `native:extractbyexpression`, and
`native:dissolve`. The run exported 27 artifacts. Processing and render status
are completed; visual and human review remain pending. Every artifact remains
`candidate_only=true`, `runtime_safety_truth=false`, and `operational=false`.
Post-run Pi telemetry showed `48.8 C`, 6.2 GiB available memory, and 7 MiB swap
in use. The isolated process RSS was about 624 MiB for QGIS, 151 MiB for the
Scout worker, 59 MiB for Xvfb, and 28 MiB for the MCP bridge. The test container
was removed after its worker receipt was copied; no public MCP listener remains.

The active project terrain ref now points to this run. Navigation compilation
takes about 1.5 seconds because it consumes the standard artifacts and marks
the legacy local Python morphology comparator `not_run`; the prior comparator
attempt was interrupted after more than 13 minutes. The Dashboard applies the
fixed 10 m Golden Route start-distance filter per multipart line. In the browser
this displays 7 ridge and 7 stream-network segments, 0 valley segments, and 128
terrain samples from 14,754 raw candidate elements. These are display
candidates, not accepted terrain truth.

Mapbox Terrain RGB is regenerated from the same GRASS-bound source artifact and
records `visualization_packaging_processor=scout_mapbox_terrain_rgb_encoder.v1`
and `visualization_packaging_only=true`. This is encoding for MapLibre, not a
second terrain-analysis engine. Its fail-closed complete-tile policy currently
covers 117 of 240 displayed Golden Route samples (49%); therefore 3D remains
explicitly local/partial while the four 2D GRASS raster overlays cover the full
route rectangle.

Evidence:

```text
API: http://127.0.0.1:9099/admin/pretrip/projects/dongqing_batongguan_historic_trail_scoutAI/navigation-terrain-intelligence
Pi evidence: artifacts/qgis-grass-standard-20260826/remote-evidence/
2D browser: artifacts/qgis-grass-standard-20260826/browser-navigation-grass-2d-final.png
3D browser: artifacts/qgis-grass-standard-20260826/browser-navigation-grass-3d-final.png
```

### Historical map preparation and theme cache (2026-08-25)

This dated single-theme baseline is superseded by
`2026-08-28 full historical catalog and QGIS risk adapter` below. Keep it only
as incident history; do not restore one-theme-only preparation.

The Dashboard historical-map control is one presentation layer with an
allowlisted theme selector, not 15 new canonical safety layers. Map preparation
must pre-seed `sinica_jm50k_1916` into the distinct
`historical-fandi-1916` workspace cache namespace. This is the default because
the 1916 Aboriginal Territory map has mountain coverage along the Dongqing
Batongguan route; the 1904 fortress map legitimately returns blank tiles across
much of that corridor.

Keep the control marked `data-layer-contract="auxiliary"`. The deterministic
32-layer verifier otherwise treats its UI-only `historical-map` ID as an
unknown canonical layer. Auxiliary marking preserves the existing layer IDs and
order without weakening checks for unmarked unknown controls.

Each alternate historical theme must use its own `historical-*` cache layer ID.
Never reuse one cache directory while changing `source_id`, because a cache-only
request could otherwise display a tile from the wrong year. The page remains
cache-only on load. Persist the selected theme under a project-scoped browser
key; a global preference can select an uncached alternate theme when a newly
prepared workspace first opens. The existing explicit raster update button may
fetch the currently selected allowlisted theme and persist those visible tiles
into the workspace. Google, satellite, terrain, and other differently licensed
or already represented current basemaps are not proxied as historical themes.

The three Taitung national-forest themes use ArcGIS exploded tile paths with
zero-padded zoom and eight-character hexadecimal row/column names. Historical
tiles remain `candidate_only=true`, `runtime_safety_truth=false`,
`operational=false`, and `visualization_only=true`; they provide comparison
context and never prove route existence, access, navigability, or safety.

The imagery source registry is imported when the Dashboard process starts.
After adding or changing an allowlisted source, restart the actual user-facing
`127.0.0.1:9099` process before browser qualification. Testing only a newly
started alternate port can hide a stale-runtime `422 unknown imagery source_id`
failure and leave every historical theme reporting `raster unavailable` in the
Dashboard the user is actually running.

## 2026-08-28 Import-Owned QGIS/GRASS Terrain Integration

This entry supersedes any procedure that completes GPX import first and repairs
terrain or Navigation after the workspace is opened. The discovered defect was
an orchestration gap: the QGIS worker and its artifact contracts existed, but
the normal `run_layer_preparation()` / Dashboard Clone transaction did not own
the worker run. Terrain RGB and Navigation could therefore execute against
missing or stale QGIS refs, making a second preparation pass or `_v2` workspace
appear necessary.

The canonical sequence is now:

```text
one clean GPX import
  -> route_evidence_bundle.json with filtered Golden GPX ref + SHA-256
  -> base map preparation and source refs
  -> terrain_feature_stack.v1 through Scout-owned QGIS worker
  -> typed/hash/processor/authority/extent/grid validation
  -> project.json QGIS terrain activation
  -> Terrain RGB visualization packaging only
  -> final Navigation terrain projection
  -> clone receipt and workspace exposure
```

Implementation ownership:

- `pretrip_import.py` records the exact filtered Golden GPX SHA-256;
- `pretrip_layer_preparation.py` dispatches, polls, times out/cancels, validates,
  activates, and records the QGIS terrain stage before Terrain RGB/Navigation;
- `qgis_spatial_backend.py` selects and verifies that exact Golden GPX, validates
  full-rectangle grid alignment, and rejects a source-manifest fallback after an
  authoritative filtered route has been declared;
- `dashboard_workspace_clone.py` enables the same stage in the user's Clone
  path and records it in the clone receipt;
- `docs/admin/scout-dashboard-v0.1.html` exposes separate ridge, valley, and
  flow-channel toggles plus `ROUTE_CONNECTED` / `RECTANGLE_ALL` counts.

The persisted stage receipt is
`outputs/spatial/qgis/map_preparation_status.json`. A successful activation must
say `actual_processor=qgis_processing_grass`, `fallback_used=false`, and
`python_dtm_processing_used=false`. The candidate authority remains
`candidate_only=true`, `runtime_safety_truth=false`, `operational=false`, and
`adds_source_resolution=false`.

The fixed worker allowlist covers the current standard stack:

```text
gdal:buildvirtualraster
gdal:assignprojection
gdal:cliprasterbyextent
gdal:rasterize
gdal:colorrelief
gdal:warpreproject
grass:r.slope.aspect
grass:r.relief
grass:r.contour
grass:r.geomorphon
grass:r.watershed
grass:r.mapcalc.simple
grass:r.thin
grass:r.to.vect
native:extractbyexpression
native:dissolve
```

There is no arbitrary Python, arbitrary PyQGIS, shell, browser-direct MCP, or
generic MCP forwarding path. Python still parses GPX, orchestrates the job,
validates schemas/hashes/provenance, and packages an accepted DEM as Mapbox
Terrain RGB. The encoder is visualization packaging only and cannot produce
slope, relief, contours, morphology, or hydrology evidence.

All analysis begins from the prepared DEM rectangle, not a Golden Route ribbon.
Every raster shares the declared CRS, extent, and aligned grid. Dashboard's 10 m
route scope uses complete segment-to-segment distance/intersection: contact at
any point retains the candidate's complete outward geometry and never rewrites
the immutable rectangle artifact.

Fail-closed states include disabled, not configured, unavailable, required
algorithm missing, cancelled, timeout, worker failure, hash mismatch, extent
misalignment, and artifact/authority validation failure. Fixture or synthetic
worker output is recorded as `fixture_non_runtime` and is not activated. Terrain
RGB remains `awaiting_qgis_grass_processor`; no Python bitmap or route-sample
substitute is generated. Non-GIS Dashboard and importer outputs remain usable,
and weather/CWA/GEE plus geology stay independently refreshable.
Dashboard Clone records this case as `completed_with_degraded_terrain`, with the
typed QGIS blocker retained in `stages.qgis_terrain_feature_stack`; it does not
mislabel the terrain workspace as fully completed.

Focused verification on 2026-08-28:

```text
252 passed, 1 warning
tests: clone, importer, layer preparation, QGIS backend/worker,
       Terrain RGB, Navigation projection, MapLibre adapter, Dashboard page
browser console errors/warnings: 0
```

The live persisted Dongqing workspace rendered the prior real QGIS/GRASS run
and exposed `ROUTE_CONNECTED=153` (`39` ridges, `28` valleys, `86` streams) and
`RECTANGLE_ALL=14,625` (`2,828`, `3,036`, `8,761`). Removing the valley toggle
removed valley features from the actual MapLibre GeoJSON source while preserving
route and other morphology features. A 2D camera at zoom `12.504105962680786`
survived a switch to the independent 3D camera and back without an automatic
fit reset.

New real single-pass GRASS execution was not available on this workstation.
Local QGIS `3.44.13` and GDAL `3.12.3` were discoverable, but the QGIS Processing
catalog exposed no `grass:*` provider, so the correct result is fail closed.
The Scout Pi SSH endpoint also timed out, so there is no new Pi resource sample.
The 2026-08-26 Pi run and its resource observations remain historical evidence;
that run did not bind the current filtered Golden GPX SHA-256
`8e8d47221f152e0f9787c62a4524d1f36bb5299c496a9ddf8b2a2f7bc00712ec`
inside worker `source_hashes`, so it is not acceptance proof for this new
single-pass integration. Do not mutate an existing imported workspace after the
fact and present it as such proof; rerun the original Clone/import-preparation
flow when a GRASS-capable worker is reachable.

The deterministic layer-contract verifier still reports the pre-existing
unrelated mismatch `pretrip:weather-api: MAP_LAYER_RANKS 58 != contract 80`.
That contract-order defect is not evidence of a QGIS terrain failure and must be
closed separately.

### 2026-08-28 local GRASS workstation binding

The Intel macOS workstation now keeps GRASS GIS 8.5.0 in the dedicated
`scout-grass` micromamba environment. Homebrew core does not provide the GRASS
formula on this host, so the supported persistent bindings are:

```text
runtime: ~/.local/share/scout-tools/micromamba/envs/scout-grass
user command: ~/.local/bin/grass
Dashboard command: ./venv/bin/grass
```

`tools/setup_dashboard_workspace_runtime.sh` creates the environment only when
missing and refreshes both shortcuts. `tools/run_dashboard_workspace.sh`
exports a macOS-supported UTF-8 locale and the bundled QGIS GDAL/PROJ data
paths. The Scout MCP subprocess environment preserves only these named GIS
runtime variables in addition to its existing narrow allowlist; unrelated
environment values remain excluded.

Installation is not accepted from `grass --version` alone. The local acceptance
probe required QGIS 3.44.13 Processing to expose `grass:r.slope.aspect` and to
execute it against a real EPSG:3826 raster. The resulting slope and aspect
GeoTIFFs were 408 x 145 pixels at 20 m resolution, reported GRASS 8.5.0 with
GDAL 3.12.3, and contained valid non-constant statistics. This proves the local
QGIS/GRASS execution boundary; it does not yet prove the full one-import plus
one-preparation transaction, terrain interpretation, route existence, or
safety.

### 2026-08-28 clean-Clone acceptance root causes (historical, superseded)

The first real Dashboard acceptance target,
`dongqing_batongguan_historic_trail_grassImport_20260828`, was intentionally
preserved as failed-run evidence. It completed the clean GPX import, local OSM
PBF route extraction, and 8-layer workspace raster cache (including
`historical-fandi-1916`), but the browser aborted the still-running synchronous
Clone request after the fixed 1,800 second limit. The server worker continued,
so the message "Clone failed" was false and could encourage an unsafe duplicate
retry. Dashboard now waits up to 7,200 seconds; a browser-side timeout says that
the server may still be preparing the named workspace and disables an immediate
retry instead of claiming the backend failed.

The same run exposed a more important architecture violation before QGIS was
called. Missing risk artifacts caused `_generate_scout_risk_outputs_from_workspace()`
to import Scout Risk and execute Python `build_dem_from_dtm_coverage()` plus
`compute_teii_from_dem()`. This was both the long-running stage and a forbidden
formal Python DEM/TEII engine. The run was stopped without deleting or
overwriting any workspace. The canonical path now fails closed with
`awaiting_qgis_grass_processor`, `fallback_used=false`, and
`python_dtm_processing_used=false`. After QGIS terrain succeeds, a missing
QGIS-derived risk adapter becomes typed `unavailable` with
`qgis_grass_risk_profile_adapter_not_available`; Python must never fill that
gap. A fresh Dashboard Clone under a different unused workspace name is
required for acceptance after this correction. Do not rename the partial run or
repair it as `_v2` and present it as a clean import.

The next fresh target,
`dongqing_batongguan_historic_trail_qgisGrass_20260828`, proved that removing
the Python DEM/TEII stage allowed the base preparation manifest to appear
immediately after raster caching. It still ended as
`completed_with_degraded_terrain`: a single QGIS worker preflight exceeded the
Dashboard backend's 5 second HTTP timeout even though QGIS remained alive and
the same bridge subsequently completed ten consecutive status checks in
0.03-0.05 seconds. This target is also preserved as failed-run evidence and is
not repaired after the fact.

The canonical preparation now retries only typed retryable QGIS preflight
failures, up to three attempts with a one-second interval, and records
`preflight_attempt_count`. The persistent Dashboard launcher defaults
`SCOUT_QGIS_TIMEOUT` to 30 seconds. Disabled, missing configuration, missing
algorithms, non-retryable errors, and exhausted retries still fail closed with
`fallback_used=false` and `python_dtm_processing_used=false`. Acceptance must
therefore use another unused target name and repeat the original Dashboard
Clone flow from `dongqing_batongguan_historic_trail_scoutAI`.

### 2026-08-28 full historical catalog and QGIS risk adapter

This section supersedes every earlier instruction that seeds only
`historical-fandi-1916` or leaves the four risk layers unavailable after a
successful QGIS run.

Root causes:

1. `WORKSPACE_RASTER_CACHE_SOURCE_IDS` listed one historical theme even though
   the Dashboard selector and allowlisted registry exposed 15. The selected UI
   theme was incorrectly treated as the preparation set.
2. A successful `terrain_feature_stack.v1` ended in a hard-coded
   `qgis_grass_risk_profile_adapter_not_available` state. This prevented
   risk-score, risk-ribbon, risk-heatmap, risk-delta, and dependent boss-point
   synthesis despite valid QGIS/GRASS route samples.
3. The tile seeder counted blank white/transparent provider images as success
   and retried permanent HTTP 404/410 no-coverage responses five times.

Canonical correction:

- Full import preparation creates 22 raster cache manifests: seven current
  raster sources plus all 15 historical themes from
  `HISTORICAL_MAP_CACHE_SOURCE_IDS`. Each historical theme has an independent
  `historical-*` namespace and source id.
- Blank/transparent tiles and HTTP 404/410 are typed no-coverage. Permanent
  no-coverage is not retried; usable, blank, no-coverage, and failed counts stay
  separate. A provider with no route coverage does not fail other themes and is
  never marked cache-ready.
- The QGIS worker samples elevation together with slope, aspect, multiscale
  geomorphon, and flow accumulation and records
  `actual_processor=qgis_processing_grass` in
  `terrain_feature_route_samples`.
- `scout_qgis_grass_risk_profile_adapter.v1` verifies the current workflow id,
  receipt authority, artifact hash, fixture/synthetic flags, and required
  slope values. It never reads a DEM or calls Python DEM/TEII processing.
- The adapter applies the versioned candidate profile
  `qgis_grass_terrain_candidate_score.v1`, repeats the nearest sparse QGIS
  sample by reference-route progress onto the existing Overpass route base, and
  records `adds_source_resolution=false`. This is contract/display packaging,
  not new terrain resolution or operational risk truth.
- Route-risk, point, ribbon, calibrated heatmap, and delta artifacts are
  written before boss-point synthesis in the same preparation call. Successful
  project state must contain `actual_processor=qgis_processing_grass`,
  `fallback_used=false`, and `python_dtm_processing_used=false`.
- Missing, malformed, hash-mismatched, fixture/synthetic, or failed adapter
  input becomes typed `qgis_grass_risk_profile_adapter_failed` (or a more
  specific input reason). Never restore the legacy Python terrain fallback.

Focused regression commands:

```bash
./venv/bin/python -m pytest tests/test_pretrip_qgis_risk_adapter.py -q
./venv/bin/python -m pytest tests/test_admin_local_raster_tiles.py -q
./venv/bin/python -m pytest tests/test_admin_imagery_sources.py -q
./venv/bin/python -m pytest tests/test_qgis_worker.py -q
./venv/bin/python -m pytest tests/test_pretrip_layer_preparation.py -k 'qgis or risk or imagery_cache' -q
```

Real acceptance still uses the Dashboard Workspace flow. Preserve the source
workspace, record source hashes, rerun importer plus preparation in the named
target explicitly authorized by the operator, and verify the clone/import
receipt, all historical theme statuses, current QGIS run/hash, four risk layer
refs, boss-point refs, MapLibre toggles, and source hashes. Weather/CWA/GEE and
geology remain runtime-refreshable after preparation.

### 2026-08-28 Terrain Route Hypothesis Navigation integration

The candidate-only terrain route stage now runs immediately after an immutable
`terrain_feature_stack.v1` activation and before the persisted Navigation
projection. It does not replace the Golden GPX, observed-passage evidence,
official trail data, route truth, or any runtime safety authority.

The fixed processing chain is:

```text
validated DEM rectangle
  -> grass:r.slope.aspect
  -> versioned nonlinear slope friction through grass:r.mapcalc.simple
  -> anisotropic minimum model-cost trace with grass:r.walk.coords
  -> one candidate LineString trace with grass:r.path
  -> full-extent symmetric cost-from-A and cost-from-B with grass:r.cost
  -> relative corridor C_A + C_B - C_AB
  -> pure 5/10/20 finite-cell percentiles of symmetric macro-terrain detour cost
  -> independent raw trace-in-band containment audit; no path union
  -> hash-bound hypothesis, visualization, overlay, and processing manifests
  -> persisted Navigation projection
```

Every persisted or HTTP projection carries `authority=candidate_only`,
`source_type=terrain_hypothesis`, `runtime_safety_truth=false`,
`operational=false`, `promotion_allowed=false`, and
`safe_or_walkable=not_determined`. The Dashboard displays a permanent
`CANDIDATE / TERRAIN HYPOTHESIS / NOT A VERIFIED TRAIL` strip, an independent
minimum anisotropic model-cost trace source, independent 5/10/20 symmetric
macro-terrain corridor image sources, evidence,
unknowns, DEM resolution, model version, and provenance. Removing or
invalidating either hash-bound route artifact yields an empty candidate source;
the prior geometry is not retained.

The route cache is content-addressed from DEM hash, extent, resolution,
endpoints, algorithm/model versions, weights, and optional evidence hashes.
Derived terrain, friction, cost raster, and final hypothesis cache keys remain
separate. Activation occurs only after all worker artifacts match declared byte
counts and SHA-256 hashes. The stage never writes an official-trail, route-truth,
or safety-truth store.

Two real QGIS 3.44.13 / GRASS 8.5.0 integration defects were found and fixed:

1. `grass:r.cost` with `stop_coordinates` stopped after reaching the opposite
   endpoint and left 666 of 2,500 synthetic cells as NoData. Corridor runs now
   omit the stop coordinate and cover the complete analysis extent; `C_AB` is
   still sampled at B.
2. Current `grass:r.univar` emits a pipe table headed by
   `non_null_cells|null_cells|...`. The bounded parser now accepts both this
   observed format and the legacy key/value report while continuing to reject
   missing, non-finite, fractional, or negative cell counts.
3. GPT Pro review identified that the anisotropic trace and symmetric corridor
   bands are separate model products, not one confidence surface. Schema v0.2,
   cache keys, provenance, Navigation projection, and Dashboard wording now
   preserve that distinction. Percentile masks no longer union trace cells.

The local qualification evidence is under
`artifacts/terrain-route-qualification-20260828/`. A deterministic 20 m
two-peaks-plus-saddle DEM produced one 809.44 m candidate LineString, a complete
2,500-cell relative-cost surface, monotonically expanding corridor bands of
125, 249, and 499 cells. A raw pre-union audit found zero trace cells outside
the 5th-percentile mask. Regenerated no-union TIFF and PNG artifacts are
byte-identical to the prior fixture outputs, showing that union had not changed
this fixture's pixels even though its semantics were incorrect.
The persisted qualification manifest records hashes, versions, modules,
parameters, findings, and confidence limits. This proves the local QGIS
Processing/GRASS algorithm chain and Dashboard projection path. A live
QGIS-agent-MCP plugin transport was not present, so the complete worker-over-MCP
transaction remains `UNKNOWN` rather than inferred from CLI execution.

At 20 m resolution the output is `macro_terrain_only`. Vegetation, trail
surface, meter-scale cliffs and structures, recent landslides, water state,
legal access, bridges, ropes, stairs, tunnels, and other engineered-trail facts
remain unknown. None of those unknowns may be converted into safety,
passability, legality, or route-existence claims.

### 2026-08-29 one-pass risk and historical-map acceptance

The `dongqing_batongguan_historic_trail_qgisGrass_clean_20260828` rerun exposed
six additional one-pass defects after the adapter and historical catalog had
already been added:

1. Dashboard loaded `/workflows/latest` without a workflow filter. A later
   failed auxiliary run hid the completed primary morphology artifacts.
2. QGIS risk points were written after the original terrain-risk candidate
   file, so Navigation compiled a valid but empty risk lens.
3. the Dashboard restart script did not restore QGIS enablement, worker URL,
   or token reference, so a restart silently changed preparation capability;
4. the pretrip page kept `weather-api` rank 58.5 while the machine contract had
   rank 80, causing the final 32-layer gate to fail.
5. Clone did not persist source P0/P1 URL identity into the target before
   preparation. Route-context collection could therefore reuse inherited
   evidence without proving a live source refresh in the new workspace.
6. raster/OCR route-context collection did not require a newly written HTML
   briefing, so a prepared target could open without
   `route_context_briefing_ref`.

Canonical behavior now is:

- query latest QGIS state with `workflow_id=terrain_feature_stack.v1`;
- after every successful primary run, require the risk adapter receipt to have
  the same run id, rebuild canonical risk candidates, then synthesize Boss
  points and compile Navigation;
- persist the loopback worker token in an owner-only file and start Dashboard
  and QGIS worker through the repository launchers without logging its value;
- keep `weather-api` at z/rank 80 and run both repository and real-workspace
  layer-contract gates;
- after import and before preparation, write the target-owned
  `inputs/route_context_source_records.json` handoff from validated source P0/P1
  records, then perform the explicit connected refresh in preparation;
- write and project `outputs/briefings/route_context_briefing.html` during that
  same preparation generation.

The accepted primary run was
`qgis-worker-20260828T161714108162Z-88505f2081`. It completed all 23 requested
preparation layers, produced 3,182 QGIS/GRASS terrain-risk candidates and five
Boss points, and recorded `actual_processor=qgis_processing_grass`,
`fallback_used=false`, and `python_dtm_processing_used=false` for both terrain
and risk. Dashboard showed 164 `ROUTE_CONNECTED` morphology candidates and
14,237 `RECTANGLE_ALL` candidates, plus 30 of 50 bounded risk candidates.
This later run used the live local QGIS-agent-MCP bridge and closes the earlier
`UNKNOWN` transport status for the primary `terrain_feature_stack.v1` path.
The same preparation consumed five target handoff records, recorded
`live_network_refreshed` with four accepted web evidence items, generated 39
route-context points, and wrote a 226,558-byte HTML briefing before the
workspace was reopened.

Raster preparation wrote manifests for seven current and 15 historical
sources. Fourteen historical themes had usable route coverage and served local
HTTP 200 tiles; `historical-taito-forest` returned no usable tile for all 402
planned cells and remains typed `seed_no_coverage`. This is provider coverage,
not a preparation error. Across all sources the final seed summaries recorded
7,266 usable cached plan tiles, 1,570 no-coverage cells, and zero failed cells.

One bridge timeout was observed before the accepted run. The failed receipt
remained fail-closed with no synthetic fallback. Restarting QGIS plus the local
worker and rerunning the same preparation produced the accepted receipt. The
auxiliary `terrain_route_hypothesis.v1` failed independently at `dem_loaded`
during this acceptance. It did not replace or invalidate the completed primary
terrain stack. The bounded recovery and later successful candidate activation
are recorded below.

### 2026-08-29 Terrain Route Dashboard recovery

The real `dongqing_batongguan_historic_trail_qgisGrass_clean_20260828`
terrain-route run exposed three fail-closed integration defects after the
primary terrain stack had completed:

1. Selecting the active clipped GeoTIFF bypassed declared source-resolution
   discovery. Terrain-route submission now requires the hash-bound parent
   terrain-feature manifest to report square resolution, EPSG:3826, matching
   analysis resolution, and the exact active DEM filename.
2. The MCP validator still required `stop_coordinates` for `grass:r.cost`,
   even though a symmetric corridor requires both cumulative surfaces to cover
   the full analysis extent. The validator now rejects a stop coordinate for
   this fixed recipe and continues to reject alternate start/allocation inputs.
3. The planned 20 m rectangle was aligned to integer coordinates, while GDAL
   retained the source DEM's half-cell grid and produced one additional row and
   column. Completeness now binds to the inspected clipped DEM grid and its
   zero-NoData cell inventory. Provenance preserves both the requested grid and
   the actual source-aligned grid; a resolution or cell-count mismatch still
   fails closed.

Run `qgis-worker-20260828T233229646326Z-a7d0f0dd24` then completed the real
MCP/GRASS path: slope, nonlinear friction, anisotropic `r.walk`/`r.path`, two
full-extent `r.cost` surfaces, the relative corridor, and 5/10/20 percentile
bands. The actual grid is 1,792 by 1,252 at 20 m, with 2,243,584 finite cells
and zero NoData cells. The bands contain 112,180, 224,359, and 448,716 cells;
each independently contains the minimum anisotropic model-cost trace without
unioning path cells into the masks.

Activation wrote only content-addressed candidate artifacts and then compiled
the persisted Navigation projection. Dashboard browser verification showed the
R1 hypothesis, all three corridor controls, a nonblank decoded 3D DEM canvas,
and simultaneous nonblank 2D/3D split canvases. The hypothesis layer toggle
removed and restored only candidate visualization. Narrow-screen verification
kept the hypothesis, terrain-candidate, elevation, and map-control overlays
non-overlapping. The route bundle, filtered GPX, and parent DEM retained their
pre-run SHA-256 hashes. Human review remains pending; the result is not an
observed, official, verified, safe, passable, legal, or recommended route.

### 2026-09-01 Arbitrary A/B TRH Dashboard stabilization

The Navigation Dashboard now accepts two explicit WGS84 map points and a bounded
analysis margin, then submits `terrain_route_hypothesis.v1` through the existing
spatial service boundary. A/B drafts persist per project, but no candidate is
published until the QGIS worker reaches `completed` and the resulting
content-addressed artifacts pass hash validation.

The first arbitrary-point UI exposed three integration failures:

1. the 2.5-second workflow poll rebuilt the complete Navigation map, causing
   MapLibre to flicker and lose or stale its candidate projection;
2. A/B and generate controls unlocked while a long run was still queued or
   running, allowing duplicate submissions;
3. path metrics issued as many as 240 sequential raster-identify calls and
   could fail late at `hypothesis_validated`, while an empty MCP exception
   message produced no useful UI detail.

The bounded behavior is now:

- active TRH polling updates only progress/status controls and performs one
  Navigation reload after a terminal state;
- all endpoint, margin, clear, generate, and competing workflow controls stay
  locked for the full queued/running lifecycle;
- a previous completed candidate may remain visible only with explicit wording
  that the new evidence has not been published;
- path metrics use at most 80 deterministic evenly spaced vertices while
  preserving endpoints, and the manifest states that sampled maximum slope is
  not a full-path-cell maximum;
- typed MCP failure detail is always non-empty;
- an unavailable optional corridor PNG does not blank the Rudy+TW base map or
  the vector hypothesis.

Real local run `qgis-worker-20260901T044232408212Z-11dc300da9` completed on
QGIS 3.44.13 / GRASS 8.5.0 in about 116 seconds for a previously failing A/B
area. The 20 m result contained an 89-vertex candidate trace, 80 deterministic
metric samples, and nested 5/10/20 corridor bands of 1,720, 3,439, and 6,878
cells. Each band independently contained the trace. Dashboard verification
showed stable Rudy+TW context, candidate line, corridor, A/B markers, decoded
3D DEM, reload persistence, and no browser-console errors.

This remains `macro_terrain_only`, `candidate_only`, non-operational evidence.
Portable macOS/Scout execution is exposed through
`tools/run_terrain_route_hypothesis_worker.py`, which records the actual host in
its receipt. A real execution receipt from the currently unreachable Scout host
remains `UNKNOWN`. The normative subsystem description is maintained in
[Scout Terrain Route Hypothesis Engine](scout-terrain-route-hypothesis.md).

### 2026-09-01 TRH drainage bias and same-request alternatives

Symptom: a slope-only TRH could prefer a valley or flow channel because lower
slope reduced friction, while one A/B execution exposed only one R1 trace. A
catalog of earlier runs did not solve this because those entries represented
different executions rather than alternate assumptions for the same request.

Root cause: live cost-model v0.1 explicitly rejected non-zero drainage weight,
and the worker executed `r.walk` / `r.path` once. Flow accumulation existed in
the broader terrain stack but was not bound into the route friction surface.

Current bounded fix:

```text
hash-bound DEM
  -> grass:r.slope.aspect -> nonlinear slope friction
  -> grass:r.watershed -> flow accumulation
  -> resolution-aware drainage pressure (1 / 5 / 25 ha contributing area)
  -> R1 drainage_averse: pressure multiplier 4.0
  -> R2 balanced: pressure multiplier 1.5
  -> R3 terrain_only_baseline: pressure multiplier 0.0
  -> three independent r.walk + r.path traces
  -> one R1-bound symmetric 5/10/20 corridor in this thin slice
```

All three candidates are persisted in one typed run and displayed together in
Navigation with separate colors and labels. Cross-profile costs are not ranked
because each friction scale differs. If two profiles resolve to the same cells,
the manifest records `distinct_geometry_count` and emits a warning; it never
manufactures a detour. The zero-penalty R3 remains visible specifically so a
valley/channel-following terrain-only solution is not hidden.

Drainage pressure is not observed water, a hazard class, or an exclusion mask.
Current water level, canyon form, vegetation, recent landslide, bridge, rope,
engineered tread, passage, safety, and legal access remain UNKNOWN. A stronger
drainage penalty must never be described as safer.

### 2026-09-02 TRH route-cache contract mismatch recovery

Symptom: an arbitrary A/B submission failed immediately at `input_validation`
with `INVALID_INPUT` and `Terrain route cache keys do not match the submitted
inputs.` The Dashboard API process had loaded the current route-cache contract,
while the still-running QGIS worker had loaded an older contract revision.
This was an internal process-version mismatch, not evidence that the selected
A/B points or DEM were invalid.

Keep the fail-closed key comparison. Restart the local QGIS worker through
`tools/run_qgis_worker.sh`, confirm `WORKER READY`, and resubmit the unchanged
A/B request. The public backend error now explains this recovery action without
exposing internal hashes or automatically retrying a rejected request.

After both processes loaded the same code, real run
`qgis-worker-20260902T012929318608Z-047dd5793e` completed all 11 steps and
published three same-request candidate traces: R1 drainage-averse, R2 balanced,
and R3 terrain-only baseline. The run remained `candidate_only`,
`runtime_safety_truth=false`, `operational=false`, and
`safe_or_walkable=not_determined`.

### 2026-09-02 Dashboard-managed local QGIS worker

`tools/run_dashboard_workspace.sh` now manages the local QGIS worker by
default. One command is sufficient when the persistent runtime, worker token,
and Scout QGIS profile are already prepared:

```bash
tools/run_dashboard_workspace.sh --host 127.0.0.1 --port 9099
```

The launcher first probes the authenticated worker capabilities endpoint. It
reuses an already-running compatible worker; otherwise it starts
`tools/run_qgis_worker.sh`, waits for the worker API to respond, and records its
output in `~/.scout-fusion/qgis-desktop/runtime/qgis-worker.log`. When the
Dashboard exits, it stops only the worker process that it started. A separately
started worker is never terminated.

Autostart is local-only and does not launch or control QGIS Desktop. The Scout
QGIS profile and plugin bridge must still be available for GIS execution. If
the worker cannot start, the Dashboard remains usable while QGIS/TRH stays
typed `unavailable`; no terrain result is guessed. Set
`SCOUT_DASHBOARD_QGIS_WORKER_REQUIRED=true` to make worker startup failure also
stop Dashboard startup, or `SCOUT_DASHBOARD_AUTO_QGIS_WORKER=false` to retain
manual worker lifecycle management.

### 2026-09-03 TRH button disabled after selecting A/B

The observed runtime had no listening Worker and an MCP connection file for an
exited QGIS process. Saved candidate geometries remained viewable, but they did
not prove live calculation readiness. Restarting the prepared Scout QGIS profile
and the Dashboard-managed Worker restored the real handshake; A/B drafts were
not changed. QGIS expects the parent of the `profiles` directory here:

```bash
open -a /Applications/QGIS-LTR.app --args \
  --profiles-path "$HOME/.scout-fusion/qgis-desktop" \
  --profile scout --nologo --noversioncheck
tools/run_dashboard_workspace.sh --host 127.0.0.1 --port 9099
```

Use this QGIS command only when that Scout application instance is not already
running. Do not stop an existing QGIS session with unsaved work or an active GIS
job. The `--profiles-path` argument must not end with `/profiles`, because QGIS
appends that directory itself; otherwise it loads a different profile without
the prepared bridge. Do not change credentials or install another plugin.

Navigation now exposes **重新檢查 Worker** beside A/B. It re-reads live status
and capabilities/control metadata without resetting the map, endpoints, current candidate, or
R4 review. Initial rendering and in-place updates share the same gate: a missing
Worker/bridge remains unavailable, and stale/fixture readiness never unlocks a
live TRH request. Starting QGIS and Worker does not execute TRH automatically.

### 2026-09-03 Explicit Navigation Worker startup

In Navigation, **啟動 Worker** now starts a missing local Worker and, on macOS,
can open the already-prepared Scout QGIS profile. **重新檢查 Worker** remains
read-only. Merely opening Navigation or running Diagnostic does not start any
service. The button is disabled while checking/starting, during a GIS job, when
already READY, or when this Dashboard cannot manage the configured runtime.

The local workspace Dashboard owns the fixed launcher/profile configuration.
The general admin API does not gain process-launch authority. Startup accepts
only same-origin loopback JSON requests; browser-supplied commands, host URLs,
credentials and authority fields are rejected. Token/profile/runtime setup must
already exist. Remote Scout startup and Linux container lifecycle are not
implemented here; a configured existing Linux bridge can still be reused.

An occupied unrecognized Worker port, missing setup, unresponsive existing QGIS
session, or timeout stays typed unavailable. Never close somebody's QGIS session
to make this check green. After fixing that underlying condition, use the
read-only recheck. A READY startup receipt alone does not enable TRH: the UI
repeats the real Worker/QGIS/bridge/capability handshake. R4 retains its separate
human-review gate, and no route job is submitted by either Worker button.

Receipts are appended to `~/.scout-fusion/qgis-desktop/runtime/qgis-runtime-control.jsonl`
and the action's Worker log is `qgis-worker-navigation.log` in that directory
(or beside the configured token file). They contain no credentials. The action
is start-only: a Worker it starts remains running for later Dashboard reuse.

Live local proof used an isolated Dashboard on port 9101 with Worker autostart
disabled and an initially empty port 9878. Clicking **啟動 Worker** produced
`existing_qgis_preserved`, `worker_started`, then a real `READY` handshake.
The A/B generation button unlocked; endpoints, narrative, G6 focus and the map
were preserved, while unreviewed R4 stayed disabled. No TRH/R4 job was generated.
The existing QGIS application and normal Worker on port 9876 were not interrupted.
Cold QGIS GUI launch was covered by adapter tests, not repeated against the
operator's open QGIS session; remote Scout qualification remains UNKNOWN.

### 2026-09-04 Arbitrary A/B TRH stops at DEM inspection

The Dongqing run `qgis-worker-20260904T005941165938Z-c59eeb94a5` failed with
`NODATA_PRESENT` before routing. Its 1,000 m A/B margin extended 680 m east
and 520 m south of the existing prepared DEM; GDAL padded the clip with 13,994
NoData cells (62,088 total). The original registered Taiwan 20 m DEM was still
available and bound to the terrain-feature manifest.

Do not reduce the margin, fill unknown elevations, or bypass the finite-grid
gate to make this green. Explicit A/B now uses that original full raster only
after verifying the parent-bound source/coverage hashes, CRS and resolution.
It remains a bounded GRASS calculation at native resolution. An unavailable or
changed original source stays `SOURCE_UNAVAILABLE`; genuine clipped NoData
still stays `NODATA_PRESENT`.

The blank-map symptom had two independent lifecycle causes: submitting TRH
removed the published candidate references before success, and Navigation
replaced completed terrain vectors/GPX geometry with the new job's empty
artifacts. New attempts now retain the published candidate until a validated
replacement exists; errors identify it as the previous result, not the failed
A/B solution. Completed terrain-stack evidence is loaded separately on page
entry and survives TRH progress/failure. Import/preparation invalidation and
all human-review/candidate-only boundaries remain unchanged.

Retain the prepared DEM hash as a separate parent-source binding even when the
full raster supplies the new A/B pixels. R4 review uses that chain to compare
corridors against the existing terrain feature index. It is also included in
cache identity; missing parent bindings must not be waved through or repaired
by auto-selecting review anchors. Transient map-refresh failures display the
last loaded evidence with an explicit stale/previous-result notice, while a
typed source-unavailable projection still fails closed.

Recovery receipt: `qgis-worker-20260904T012958960072Z-8d6d01ab12` completed
R1/R2/R3 for the original failed endpoints and unchanged margin. The bounded
20 m grid contained 62,088 finite cells and zero NoData. Its full-raster cache
`82a9f7b4511226e028261759c6a04f002a59aca177dcf5d30152d5ab89f869c9`
also passed the existing R4 parent/corridor/path checks in a read-only replay;
no human anchors or review decisions were written.

Check the operator's actual Dashboard port before declaring a runtime repair
complete. In this incident, Chrome was connected to an old process on 9100 while
9099 had already been updated. A later 9100 submission repeated the old
candidate-deactivation behavior. Wait for an active worker job to complete,
then update the owning Dashboard process, preserving a shared worker/QGIS
session. The newer successful operator result (`be8797bfcd83` cache prefix) was
retained; the earlier recovery was not republished over it. Both local ports
served the updated page afterward.

The affected combined Python run had 442 passes and one worker-poll timing
failure; the failing test passed on an unchanged standalone rerun. Frontend
checks, the real-workspace 32-layer contract, and focused 2D/3D browser checks
passed. This is local recovery evidence, not remote Scout qualification or
production/safety promotion.

### 2026-09-04 Store buffered analysis DEM in the workspace

The operator correctly reported that both failed A/B points were inside the
route scope. Verified EPSG:3826 points were approximately
`A=(277780.49,2581296.74)` and `B=(273584.44,2583237.12)`, inside the route bbox
`242479.596,2581030.537,277868.065,2606119.118`. The old prepared DEM only added
250 m, whereas TRH added 1,000 m around the A/B bbox. Do not describe this as
the operator selecting endpoints outside the route.

Preparation now materializes a separate workspace-owned regional DEM after the
terrain-feature parent, before TRH. Default storage margin is 5,000 m plus two
native grid cells, covering the current maximum analysis margin for endpoints
within the route bbox. Feature-stack extent, semantic corridor, known GPX,
candidate route refs and R4 review remain unchanged. The normal layer
preparation receipt includes `workspace_terrain_dem`; unavailable preparation
must remain explicit, not be counted as successful coverage.

Use `./venv/bin/python -m workspace_terrain_dem --project-root <project-root>`
for a bounded backfill without rebuilding the rest of the workspace. The new
project refs point to `outputs/terrain/dem/<identity>/dem.tif` and its manifest.
TRH validates the local file and its current parent/source bindings, checks the
buffered request fits, then submits that workspace-owned source to the worker.
Only legacy workspaces without these refs retain direct original-raster use.

Attempt 1 stopped with a typed CRS error: the original GeoTIFF had custom
WGS84/TM121 WKT without an EPSG ID, despite its registered Metadata.xml declaring
EPSG:3826. The fixed adapter requires both provider reference-system metadata
and matching complete TM121 projection parameters. It normalizes only the
derived clip's CRS tag, records original WKT and exact commands, and keeps a
hash-bound provider XML copy inside the workspace. Any recognized conflicting
CRS, unsupported axis/unit or different projection remains unavailable.

The successful local receipt is
`outputs/terrain/dem/e8a985456305ac9d09939754d7937dc547c8b845e1f15ea15019fb2c88a82dd4/manifest.json`:
20 m native resolution, 2,274 x 1,759 cells, 3,999,966 finite cells, zero NoData,
and an 11,796,504-byte GeoTIFF. Full-grid counts come from actual GDAL cell
export, not rounded statistics. Active R1-R3 and R4 review hashes were not
replaced. Original source data, safety authority and GPX geometry were untouched.

Validation used the same failed A/B and 1,000 m margin against the new local
raster: 312 x 199 cells, 62,088 finite and zero NoData. The backend selected
`workspace_prepared_dem`; repeated preparation reused the same manifest/hash.
Related tests passed 159 cases, with 47 cases passing in the final focused rerun;
the real-workspace 32-layer contract passed. Both Dashboard ports were updated.
Startup took longer than the initial readiness poll, so the existing startup
process was allowed to finish instead of launching a duplicate on that port.

After restarting, the Navigation API reported `persisted_projection_stale_or_invalid`
even though the active route artifacts were intact. The prior projection's
fingerprint no longer matched current inputs; the specific earlier input change
was not established. Recompile only the existing Navigation display projection,
then verify its fingerprint, candidates and R4 scope. Do not respond to this
state by deleting route results or rebuilding human review.

### 2026-09-08 Exact-workspace terrain backfill without replacing `newImport`

The authorized target is
`/Users/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport`.
`dongqing_batongguan_historic_trail_qgisGrass_clean_20260828` is a read-only
capability reference, not a directory to rename, copy over the target, or delete.
Verify both `project.json` IDs before interpreting similar route names. Preserve
the original file/hash inventory and the target's newer Route Context,
semantic review, Permission, and dynamic evidence before regeneration.

This target had two independent input gaps:

1. `golden_route.filtered_geometry_ref` existed, but
   `golden_route.filtered_geometry_sha256` was absent. The QGIS backend correctly
   refused to use an unbound filtered GPX. Hash the target's existing filtered
   file and add only that missing binding; do not replace its reference tracks.
   The verified filtered GPX hash is
   `8e8d47221f152e0f9787c62a4524d1f36bb5299c496a9ddf8b2a2f7bc00712ec`.
2. The coverage summary listed 146 county DTM entries but no `raster_sources`.
   QGIS's county-source fallback considers only the first 32 candidate entries.
   Register the independently available 2025 full-Taiwan 20m DEM, using its
   actual SHA and provider XML CRS evidence, instead of replaying the reference
   workspace's prepared DEM or manifests. The source TIFF SHA is
   `59e5e980000d6e3f5a7734c6af197934a1a5432482b6caa789a1ec90b624015d`;
   XML SHA is
   `58f354e1e4258c1e8a47f49fc7e4c03b3b1d3871af6666b734361afa462f9495`.
   `crs_evidence` is the XML path string, not a nested object. Preserve county
   entries and use the existing strict provider-XML/TM121 CRS normalization.

The existing Route Context evidence packet binds the previous route-bundle
hash. Preserve those exact previous bytes plus a receipt identifying the single
added field and old/new SHA. Do not rewrite a historical evidence packet or
rerun its human review merely to make its snapshot look current.

For a user request that prohibits directory replacement and cache deletion,
the connected-preparation coordinator's staged directory exchange and retired
generation cleanup are not appropriate. Use the existing bounded producers on
the exact target, in this order: terrain feature stack, workspace DEM, QGIS risk
adapter, terrain route hypothesis, Terrain RGB, and Navigation projection.
The task-local reproducible driver and initial snapshots are under
`artifacts/workspace-terrain-parity-20260908-newImport/`. It calls the existing
preparation helpers; it does not rerun import, overwrite Route Context, install a
permanent workflow, or grant review/operational authority. Keep project writers
sequential. Raster downloads may use disjoint cache paths with project-field
publication deferred, then merge only the producer's own fields into the latest
project snapshot.

The target's completed primary run is
`qgis-worker-20260908T015858039770Z-0043021dd2`, with 27 hash-verified artifacts.
The 5,649 filtered GPX vertices match its route anchor exactly. Its parent
manifest SHA is
`c41ce050a8dde585036b4b8a3a7da5f5542857eeab562991c7bcd46def420ee5`.
The QGIS risk adapter produced 4,292 route samples, 3,182 points, and 2,884 ribbon
segments. These are candidate scores, not reviewed spatial-risk input.
`qgis_spatial_risk_input_status=not_available` is correct while reviewed QGIS
evidence is missing; both workspaces shared that state before this backfill.

The first TRH run, `qgis-worker-20260908T021923945035Z-19201abe39`, failed during
endpoint preparation. Its workspace receipt had a generic processing error;
the worker's retained `worker_run.json` identified
`QGIS bridge request timed out: bridge.hello`. Preserve both records. A fresh
availability check succeeded, and the second run
`qgis-worker-20260908T022504845168Z-b0378c38d4` completed R1/R2/R3 with 23 published
artifacts. No QGIS restart, fabricated success, or synthetic terrain fallback
was needed for this retry. All hypotheses remain candidate-only, with
`runtime_safety_truth=false` and `safe_or_walkable=not_determined`.

Two producer defects were exposed by inspecting actual payloads:

- Fresh raster cache files previously bypassed blank/transparent validation.
  The target's forest manifest counted 402 reusable images, although 18 were
  fully transparent legacy files and only 384 had visible data. Validate fresh
  cache payloads using the same blank test as remote/fallback payloads, retain
  their bytes and mtimes, and report no coverage instead of useful cache hits.
  Across the 22 layer plans there are 8,836 slots and 7,266 useful images. Valid
  provider JPEGs can have the historical `.png` cache suffix; decode the content
  rather than classifying solely by the extension. `historical-taito-forest`
  has no coverage for all 402 planned cells, including in the reference.
- Terrain RGB previously read only county `.grd` files, even after preparation
  had produced a complete, hash-bound workspace DEM. This yielded 506 tiles but
  only 3,015/4,291 supported route samples (70.26%). Prefer the active prepared
  DEM after validating its manifest SHA, exact project, current parent/coverage
  bindings, raster SHA, dimensions, and finite/NoData inventory. Include both
  the DEM and manifest hashes in the output fingerprint. A declared invalid
  prepared DEM must fail closed instead of silently falling back to the old
  county mosaic. This change only decodes and packages the native 20m elevation
  grid for display; it does not add terrain resolution or safety authority.

Scoped test isolation also needs both Scout's env loader and
`python-dotenv`'s `DotEnv.parse` mocked. Importing `admin_api` can reach FastMCP
Settings through Pydantic AI during collection, before a Scout-loader-only mock
can prevent a real `.env` read. The retained test guard blocked that read before
content was accessed. On macOS, a deletion guard must resolve `dir_fd` when
checking temporary fixture cleanup; otherwise it can falsely reject an
expected NoData test during teardown. Keep these harness failures and their
successful reruns distinct from product test failures.

The native workspace DEM reconstruction completed with 2,274 × 1,759 cells,
3,999,966 finite cells and zero NoData, at the original 20m resolution. Terrain
RGB replay selected `workspace_prepared_dem` and generated 54 complete tiles at
z13, covering 4,291/4,291 route samples. Higher display zoom replays also reached
100% (266 tiles at z14; 1,200 at z15); the existing selection policy chose the
lowest complete zoom. Tile count alone is not a coverage comparison. The
Dashboard independently reported 240/240 displayed samples and decoded a real
3D center elevation of 1,848.8m, with `adds_source_resolution=false`.

After the raster producer fix, publish only its delta into the latest target
project. Final coverage is 7,266 useful images out of 8,836 planned cells across
22 layers. The 1,570 unavailable cells consist of 18 retained transparent forest
tiles, 492 blank provider responses that were not written, and 1,060 provider
no-coverage responses. The final replay had zero failed fetches. Source coverage
varies by historical theme: Shinko has 10/402 useful cells, Kanzan 3/402, and
Taito 0/402. A successfully loaded transparent fallback is not map coverage.

For dynamic evidence, call the official environment preparation helper once on
the target. This run used the explicitly enabled Mac server imagery path
(`SCOUT_CWA_SERVER_IMAGERY_CAPABLE=1`) and a task-local cache wrapper that
suppressed four prune calls. It retained prior environment files and imagery
cache snapshots; no existing imagery file was deleted. CWA fetch time advanced
from `2026-09-07T04:46:06.296724+00:00` to
`2026-09-08T02:36:16.749156+00:00`. Forecast, warning, rainfall observations,
QPE and QPF datasets were all ready; rainfall grids and imagery were ready.
The radar frame was 10:20 and satellite frame 10:10 Asia/Taipei. GEE remained
`missing_credentials`; do not replace it with old reference-workspace data.
Weather UI still reported route `no_coverage`/unresolved impacts. Provider fetch
success is not proof of route impact coverage, current frame validity, or a
safety decision. Historical Route Context/review/Permission bytes remained
unchanged (41 protected project fields and 43 referenced artifacts); later
terrain replay uses the separately recorded, authorized dynamic-refresh
checkpoint of 118 fields and 119 hashes.

The final audit also exposed a risk provenance ordering defect. The official
risk finalizer first generated child point/ribbon metadata and then stamped
candidate provenance into the parent route GeoJSON, changing its raw SHA.
Consequently `source_route_risk_sha256` in the children referred to the parent's
pre-stamp bytes. Rebind only children whose original parent ref and SHA match
the parent being stamped, then stamp the children so their source refs and
model-output hashes include the final parent/metadata bytes. A mismatched or
unrelated parent must not be silently blessed. Repeated stamping must be byte
stable and must preserve geometry, scores, and candidate-only boundaries.
Replaying an already completed QGIS workflow normally returns
`risk_outputs_already_match_qgis_workflow`; use the explicit, validated
`force_refresh` replay entrypoint after this producer repair instead of making
the project falsely appear pending or manually editing the workspace hashes.

The real same-workflow risk replay completed at
`2026-09-08T03:25:42.866181+00:00`, retaining 4,292 route samples, 3,182 points
and 2,884 ribbon segments. Its final route raw SHA is
`ae42ec78fea33bcf79d851583730f660077a4e5e4533c1e2e5a2cebe924433df`;
both derived metadata files and their embedded metadata bind that final SHA.
The pre-repair outputs were copied to a task evidence snapshot before replay.
The task-local wrapper also retained the adapter's new empty temporary directory.
Recompile Navigation projection after replay; do not rerun terrain analysis or
human review just to refresh display provenance.

On the final local service restart, the Dashboard launcher's default 15-second
worker startup deadline expired while the worker was still starting; the log
was empty and the launcher terminated that not-yet-ready managed child. Use the
existing `SCOUT_DASHBOARD_QGIS_WORKER_START_TIMEOUT` environment override for a
bounded startup retry (180 seconds in this run). Preserve the QGIS desktop
instances and do not start a duplicate worker while an earlier child is alive.
Wait for the actual loopback listeners before reloading the browser. This is a
local startup parameter, not a production policy or a hardware authorization.

The first post-start status request also exceeded its 30-second timeout; retain
that unavailable receipt and retry after startup rather than treating a TCP
listener as a successful QGIS handshake. The fresh status attempt succeeded at
`2026-09-08T03:42:10.611021Z`: QGIS `3.44.13-Solothurn`, plugin `0.4.9`, bridge
and application available, with no errors. The original QGIS desktop instance
and the task's Scout-profile instance both remained running throughout service
restarts. A fresh browser reload then showed the exact target project,
MapLibre ready, 54 prepared DEM tiles, the three morphology layers, R1/R2/R3,
and `CANDIDATE · TERRAIN HYPOTHESIS · NOT A VERIFIED TRAIL`.

Final evidence is in
`artifacts/workspace-terrain-parity-20260908-newImport/REPORT.md` and
`provenance/final-provenance-after-risk-replay.json` beneath that directory.
The independent audit passed 24/24 checks, including all 10,358 risk feature
model-output hashes, unchanged risk geometry/scores, current Navigation input
fingerprint, and whole-workspace preservation. The final scoped JUnit set has
125 unique passing cases and no unresolved failures; earlier harness/fixture
failures remain recorded. The real-workspace layer verifier passed all 33
contract entries. The Navigation freeze guard remained report-only and its
baseline was not changed. All original 5,724 target files remain; the reference
workspace's 13,535 files retain identical bytes, mtimes and root inode. Core
terrain/raster parity does not replace the reference's two historical scenario
entries, G1-G11 guidance or 18 historical TRH runs; preserve that reference
until a separate evidence-retention decision and explicit deletion approval.

## 2026-09-08 — Golden G1–G6 qualification: import timeout and authoring gap

The real Dashboard qualification uses the existing local service at
`http://127.0.0.1:9099`, PID `47541`, and separate targets
`golden_g1_chilai_20260908`, `golden_g1_chilai_clone_20260908`, and
`golden_g2_dongqing_clone_20260908`. This is qualification evidence, not a
declaration that the Golden workflow is usable. The detailed matrix and
screenshots are linked from
[the G1–G6 report](scout-golden-gpx-g1-g6-qualification-20260908.md).

Observed root causes and bounded recovery:

1. New Import's Taiwan defaults point to `/data/scout/materials/country/tw`
   and its `dtm` directory, which do not exist on this Mac. Emptying the form
   fields re-applies the country defaults. A source-valid read-only Preview
   succeeded only after explicit UI selection of existing raw material paths.
   Do not treat the default text as evidence that the material pool is installed.
2. The old material manifest's
   `/Users/alexwang0315/scout-fusion/catographydata/DTM` entries are also stale.
   The original Nantou/Hualien DEM directories still exist under
   `/Users/alexwang0315/scout-fusion-legacy-20260823/catographydata/DTM` and were
   selected through the form. The DTM control is a single-line input: use commas
   between directories. A newline becomes concatenated path text; that attempt
   was a test-input error, not a DEM or provider failure.
3. The actual New Import POST timed out in the browser after 180 seconds.
   The server subsequently completed the target import. Reload cleared the
   intake fields and did not restore a job/progress view. After catalog reload,
   selecting and opening the completed target recovered access without another
   import. Do not overwrite an existing target just because the browser timed out.
4. The resulting workspace has no layer preparation manifest and no
   `outputs/contextual_permission/workbench_seed.json`. Permission's Retry
   bounded projection repeats the seed-missing block. Manual JSON/bootstrap
   repair was not used to manufacture a Dashboard qualification PASS. The
   product flow needs preparation plus lawful candidate-only authoring
   initialization; it must not manufacture human review.
5. A same-name Clone request against the already-created **test target** returned
   HTTP 409 while the original Clone continued. Isolated preparation-failure
   tests preserve `imported_preparation_failed` but reject a same-name retry;
   this proves collision protection, not stage-level preparation resume.

The single-day source was selected from raw timestamps, not the existing
`chilai_nanhua_day1_scoutAI` name (that Golden spans two local days). The chosen
`GoLife_Run_gpx_2016-11-12.gpx` has 9,302 raw points and one Taipei calendar day;
all 35 imported CP source-index/time checks match. The original Dongqing
workspace's no-write UI Generate independently matches nine source days, all
219 CP clock/unknown entries, 143 missing-time points, eight overnight gaps and
32 inferred stops. These supporting checks do not replace the new-workspace
Save/Accept/Rebuild chain or the three consecutive successful repetitions.

Keep the original source/review records intact, retain the failed attempts,
and report unprepared, stale, unknown and blocked states separately from PASS.

Both Clone requests subsequently reached terminal receipts:

- `golden_g1_chilai_clone_20260908` completed at
  `2026-09-08T04:34:23.712470Z` as `completed_with_degraded_terrain`.
  The actual blocker is `MCP_UNAVAILABLE`: QGIS worker status timed out after
  three preflight attempts. Do not replace that observation with a DEM diagnosis.
- `golden_g2_dongqing_clone_20260908` completed at
  `2026-09-08T04:26:48.231279Z` with the same degraded status. Its QGIS processor
  was reachable, but `terrain_feature_stack.v1` returned `SOURCE_UNAVAILABLE`:
  no bounded DEM source was available. TRH, workspace DEM and Terrain RGB
  consequently remained unavailable/not run/awaiting the terrain processor.
- Both receipts have `material_root=null` and a blocked map preparation stage;
  both final workspaces still lack the Permission workbench seed. The single-day
  source was a newly imported, unprepared workspace. Verify source configuration
  handoff and server preflight separately from worker reachability; do not infer
  identical causes from the common degraded status.

Use the Clone receipt's `completed_at` for terminal completion. The layer
manifest's earlier core-stage `finished_at` does not prove all later enrichments
have finished. HTTP 201 does not mean complete map preparation or Permission
authoring readiness. The final layer verifier reports 33 contract entries and
11 errors on each Clone, compared with 13 errors on the unprepared New Import.
The observed multi-day Navigation view also retained its loading message across
two captures despite having only the orientation basemap and no QGIS artifact;
it did not establish a usable terrain state.

Raw receipts, stage reasons and hashes are in
`artifacts/golden-gpx-qualification-20260908/receipts/final-clone-outcomes.json`.
No seed repair, worker restart or source-manifest edit was used in this test.
The 56 isolated passing cases remain supporting evidence; the new-workspace
full chain has zero successful runs, so the three-success repetition gate has
not started.

### 2026-09-08 Recover a completed TRH worker run whose Dashboard wrapper is missing

The Navigation page retained worker ID
`qgis-worker-20260908T043838322181Z-c8cf4549d4`, but polling the project-scoped
Dashboard endpoint returned HTTP 404. This was not a stalled GRASS job. The
worker's durable receipt records execution from `2026-09-08T04:38:38Z` through
`04:56:08Z`, terminal state `completed`, no typed error, and complete R1-R3,
corridor and processing-manifest artifacts. The project-local
`outputs/spatial/qgis/<run-id>/workflow_run.json` wrapper did not exist. The
exact request-lifecycle event that prevented that wrapper from being persisted
is UNKNOWN because no corresponding Dashboard request log was retained; do not
describe the run as deleted, failed or still computing.

Direct workflow reads may now recover only a worker-generated ID from the
configured authenticated worker. Recovery requires matching run/request/project
and workflow identities, a valid current `project.json`, complete hash bindings
for every source ref, and deterministic route cache keys for TRH. The worker's
request receipt remains behind worker bearer authentication and is never read
directly by the browser. A recovered terminal run still passes the normal
artifact download, SHA, terrain-hypothesis, processing-manifest, cache and
Navigation projection validation. Any mismatch stays typed unavailable/error;
it is not adopted as workspace evidence.

The real recovery returned HTTP 200 for the same ID, materialized 23 artifacts,
made that run the latest `terrain_route_hypothesis.v1`, and compiled a ready
Navigation projection with zero missing artifacts. Browser inspection showed
R1 drainage-averse, R2 balanced and R3 terrain-only candidates, the corridor,
Rudy+TW basemap and the unchanged candidate-only authority strip. This did not
rerun GRASS, promote a route, modify GPX, or grant passability, safety, legal or
operational authority.

Two timeout states must remain distinct. Dashboard submit and terminal
materialization reads use a dedicated 180-second workflow HTTP timeout because
project preflight and hash verification can exceed the ordinary 45-second
status timeout. Separately, a prior runtime `START_TIMEOUT` can become stale
when QGIS finishes loading or becomes responsive after a long worker job. A
read-only runtime snapshot now probes an existing timed-out receipt and reports
READY when the full application/plugin/capability handshake is live; it does
not start or restart a process. In this incident the refreshed service reported
QGIS `3.44.13-Solothurn`, plugin `0.4.9`, Worker READY and no active job before
recovery.

## 2026-09-09 — Golden preparation and Permission recovery repair

This repair is explicitly authorized by the user's request to repair preparation,
job recovery and Permission initialization before rerunning G1–G6. Preserve the
2026-09-08 failed round. Current executable evidence is under
`artifacts/golden-gpx-repair-20260909`; a successful isolated test does not qualify
the Dashboard workflow.

The Dashboard now submits New Import through `import-and-prepare` and Clone
through `clone-jobs`. Both return a persistent preparation job. The Workspace
and Trip Intake views expose import, preparation and Permission initialization
stages, the job ID, failure reasons and an explicit Resume action. Reloading the
page reads the same job; it does not submit another import. Never use an overwrite
to recover a timeout. A target without a completed import checkpoint remains
protected as `import_outcome_unverified`.

Preparation reads original material paths from persisted `preparation_inputs`.
Legacy sources may use original DTM declarations from the coverage summary;
derived workspace terrain and PBF route extracts are not raw inputs. An explicitly
blank material root does not reintroduce a machine-specific ambient default.
The shared helper enables the full enrichment and map specification stages.
Job completion requires a completed terrain processor when terrain was requested,
and an authoring-ready Permission initialization; otherwise it retains gaps.

The initial real run exposed additional recovery defects:

- G2's legacy raster declaration contains `crs_evidence_sha256`. Rejecting that
  field as an extra input prevents Clone before target creation. Preserve and
  verify this CRS provenance rather than silently discarding it.
- Failed-job status lookup rehashed the full original DEM on every GET, causing
  repeated 20-second browser aborts. Status reads need inexpensive structural
  checks; actual Resume must still verify content before any stage writes.
- G1's explicit raw PBF was absent from the first job's content bindings and was
  lost by Clone when no material manifest was selected. New job envelopes must
  bind explicit PBF inputs as well as material/project raw-source declarations.
  Do not retrospectively label a legacy unbound input verified; keep its receipt
  and require a new source-bound job with a new target when proof is unavailable.
- G1's QGIS `terrain_feature_stack.v1` failed at `dem_loaded` while merging
  multiple DEM tiles. The private worker receipt identifies a missing parent
  directory for `buildvrtInputFiles.txt`, used by `gdal:buildvirtualraster`.
  This observation is not evidence of a missing DEM source. Keep the bounded
  Processing detail and repair the run's temporary directory handling.
- Permission initialization succeeded without hand-edited files. The real
  G1 Preview/Generate reproduced one recorded day, 08:40:19–16:47:41 and all 35 CP
  clocks. Save wrote an immutable candidate, but reloading the page lost its UI
  selection and provided no server-backed restore path. Recovery must read the
  saved version and validate its identity; it must not restore review checkmarks
  or automatically accept it.

Initialization creates an unreviewed, candidate-only authoring seed, source
bindings and a transaction journal. It does not create departure approval or
runtime authority. A repeated initialization must preserve accepted baselines
and must not treat a stale bootstrap as current evidence. The G1 first attempt
ended `completed_with_gaps`; G2 ended `import_failed`. Neither is a qualification
PASS. Record the repaired-version rerun separately, including the actual UI
Save/Accept/Rebuild/reload chain and the required consecutive repetitions.

The source-bound rerun on 2026-09-09 exposed two further recovery conditions:

- QGIS Processing runs inside the existing desktop plugin. Setting the MCP
  subprocess temporary directory alone does not repair that process. The bounded
  worker now falls back to the installed `gdalbuildvrt` only for the specific
  missing `buildvrtInputFiles.txt` failure. Inputs and output remain within the
  approved raw-source/run roots; subsequent clipping and terrain processing stay
  in QGIS. The real run `qgis-worker-20260909T001055428989Z-e0f2b5ea90` completed
  with 10 DEM sources and published `actual_processor=native_gdalbuildvrt`,
  `fallback_used=true`, and `python_dtm_processing_used=false`. This is a
  processing result; visual review and complete Golden qualification are separate.
- Accept and Rebuild can finish after the browser's former 20-second POST
  timeout. In the real G1 test, both operations persisted valid receipts while
  the page incorrectly said the write was not recorded. Treat transport loss as
  an unknown outcome. Read the saved candidate catalog and bounded projection
  again, verify the exact candidate/baseline, and reuse the same command key when
  retrying. A failed read cannot prove a failed write; closing a confirmation
  after submission cannot cancel the server operation.
- After QGIS-dependent enrichments complete, recompute the aggregate layer
  validation/counts from the final evidence. The first source-bound G1 receipt
  retained four earlier `python_dem_terrain_analysis_disabled` blockers even
  though the corresponding layer entries had been updated. Preserve genuine
  missing-source gaps: the same workspace's 33-layer verifier still reported
  missing MCP candidate refs/counts. Do not clear those to make preparation green.

Detailed evidence for this repair is under
`artifacts/golden-gpx-repair-20260909/`; the current acceptance status remains
`NOT QUALIFIED` until the final G1–G6 rerun and repeated core flows are recorded.

The r4 controlled-reload experiment distinguished job recovery from processor
availability:

- Three UI Resume commands reused their original `import.1` receipts and
  checkpoints: all 108 workspace raw/filtered GPX bindings, 54 request-bound
  source GPX hashes, 12 import-identity JSON files and 10 earlier receipts matched
  the before-reload snapshot. G1 Resume returned 202 in 19.377 seconds; the two
  Clone browser requests aborted at about 20 seconds but rediscovery showed the
  same jobs queued/running. A lost response is not permission to reimport.
- G1 attempt 2 reached `completed_with_gaps`; final aggregate validation now has
  zero old blockers, 22 ready preparation records and one missing MCP record.
  The complete 33-layer verifier still fails the MCP reference/count checks.
- The new QGIS run failed before DEM processing: TCP reached the registered
  desktop plugin, but `bridge.hello` did not respond. A live worker port or a
  freshly created runtime controller's `idle` status does not prove desktop
  bridge readiness. The earlier native GDAL success must not replace this
  failed attempt's status. Preserve the previous artifact and its provenance.
- A short desktop process sample showed the QGIS main thread waiting in
  AppKit/input-source/pasteboard calls. Bringing that same PID to the foreground
  returned successfully but a single subsequent hello probe still timed out.
  Do not assume that closing a desktop QGIS process is safe when its unsaved
  project state cannot be inspected. Keep the failure and exact recovery need
  visible; repeated worker-only reloads do not repair a blocked desktop event loop.
- Permission baseline/map-context GETs also exposed a separate read bottleneck:
  historical GPX reconstruction re-derived stationary intervals on each read.
  The observed G1 calls took roughly 50–55 seconds, exceeding the UI timeout.
  This is not missing route geometry. Preserve source/CP/time validation when
  repairing that algorithm; compare full outputs, including unknowns and
  inferred stops, against the original implementation.

See [r4 Resume proof](../../artifacts/golden-gpx-repair-20260909/reports/r4-resume-checkpoint-proof.md),
[QGIS desktop diagnosis](../../artifacts/golden-gpx-repair-20260909/reports/r4-qgis-desktop-sample-analysis.md),
and [Permission read diagnosis](../../reports/r4-permission-read-latency.md).

The read-path repair preserves the exact stationary-interval semantics. It
precomputes continuous observed-time runs and skips starts that cannot reach
the existing minimum point count/duration or whose necessary duration point
already exceeds the radius. Remaining starts use the original complete scan.
Compare full old/new reconstruction payloads on the single-day and nine-day
sources, not just the displayed number of days. Timing measurements are
telemetry; browser completion still needs a separate observation.

After a completed preparation updates a bound source, restoring an earlier
candidate can legitimately return `stale`. Keep it available for inspection,
but disable Quick review controls and its change handler unless
`review_ready` is explicitly true. The observed pre-fix UI kept Accept disabled
but incorrectly displayed "Review complete" after checkbox changes. A matching
candidate hash and `validation_state=valid` do not establish current sources.

### QGIS qualification profile recovery after the 2026-09-09 host reboot

The host reboot ended both Dashboard processes and all QGIS processes; disk job
states and immutable stage receipts survived. Check current listeners and target
leases before interpreting a persisted `running` state. Use the Dashboard's
explicit Resume for an interrupted preparation; do not edit its state JSON or
reimport an already completed source checkpoint.

The first rescue-profile launch also had a concrete path error. QGIS appends
`profiles/<profile-name>` to `--profiles-path`. Passing a directory already ending
in `profiles` created `profiles/profiles/<profile-name>` while the copied plugin
sat elsewhere. This macOS installation writes profile settings to
`qgis.org/QGIS3.ini`; the initially supplied `QGIS/QGIS3.ini` was not the active
settings file. The live directory tree established both mismatches.

For a new isolated qualification profile, use a new temporary base directory,
copy only the existing `qgis_agent_mcp` plugin to
`<base>/profiles/<name>/python/plugins/qgis_agent_mcp`, and pass **the base** to
`--profiles-path`. Set `PythonPlugins/qgis_agent_mcp=true` in the active
`qgis.org/QGIS3.ini`. Set `auth/use_password_helper=false` only in that empty
temporary profile to avoid creating a new Keychain master password during
startup. This does not alter the user's profile, credentials, or bridge token
authentication. The setting and startup condition are defined by
[QGIS 3.44.13 auth manager](https://github.com/qgis/QGIS/blob/final-3_44_13/src/core/auth/qgsauthmanager.cpp#L3228-L3233)
and [QGIS startup](https://github.com/qgis/QGIS/blob/final-3_44_13/src/app/qgisapp.cpp#L15519-L15530).

Give that QGIS process and its worker the same temporary
`QGIS_MCP_CONNECTION_FILE` and matching `SCOUT_QGIS_MCP_PYTHONPATH`. Before
launching preparation, verify the registration PID is live and `bridge.hello`
returns authenticated. Save redacted PID/version/timing evidence, never the
token. In r6b the isolated QGIS 3.44.13 bridge replied in 0.030 seconds and the
global registration SHA remained unchanged; see
[launch receipt](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-r6b-qgis-launch.json)
and [hello receipt](../../artifacts/golden-gpx-repair-20260909/receipts/runtime-r6b-qgis-hello.json).
This proves bridge recovery, not completed terrain processing or G1–G6.

### Preparation job catalog latency after restart

In r6, a direct five-job catalog read took 73.75 seconds and the browser's
20-second GET timed out. Profiling found 16 repeated envelope validations and
2.08 million function calls, mostly converting already decoded JSON through the
generic model/Path conversion routine. No raw DEM/PBF content read caused this
particular delay. Observe the final job state once, validate its envelope once,
and encode decoded JSON directly with the same canonical settings. r7 produced
the same five statuses in 9.02 seconds under the continuing heavy host load;
all five existing requests retained identical canonical bytes. Request tamper
detection and Resume's leased raw-source/import validation remain mandatory.

Do not substitute this direct-call timing for a successful browser Resume, or
turn a timeout into a second import. Keep the original job ID and discover its
current outcome after reconnecting. See the
[before profile](../../artifacts/golden-gpx-repair-20260909/reports/r6-job-catalog-profile.txt)
and [after profile](../../artifacts/golden-gpx-repair-20260909/reports/r7-job-catalog-profile.txt).

### Distinguish a long preparation stage from a stopped runner

The r7 G2 Resume retained import.1 and began prepare.3 at 02:42:46 UTC.
Before the layer manifest is published, `run_layer_preparation` finishes local
OSM extraction, optional Overpass fetch, and all workspace raster cache seeds.
The outer job can remain `running / prepare` with the same stage timestamp
throughout this work. That label alone proves neither progress nor a deadlock.
Corroborate it with the exact target's output mtimes, worker processes, and
stage receipts. On macOS use `/usr/bin/sample`; a same-named Python executable
on PATH is not the operating-system process sampler.

In this run, the OSM feature index was written at 02:53:56 UTC, followed by
22 raster seed manifests at 03:09:45 UTC: 4,191 newly written tiles, 3,075
existing tiles reused, and zero failed downloads. Seven source layers had
partial no-coverage and one had no coverage along the route. Those are explicit
provider/blank-tile outcomes, not proof of a failed download or completed QGIS
processing. Preserve the immutable request's zoom range, source identity and
coverage policy while waiting; do not skip seeds to manufacture completion.
The cache manifests are currently written after all seed futures complete,
so intermediate file mtimes are corroboration only. Per-substage progress
receipts remain observability debt.

[G2 raster stage evidence](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-raster-terminal.json).

### OCR deadline under construction load

After seeding, the same G2 run entered Tesseract OCR. A read-only probe of one
of its real Rudy+TWMap tiles completed in 22.348 seconds with the actual
pytesseract runner, exceeding the former 10-second default. The result had no
nonempty text; record that outcome rather than inventing a named point.
The construction default is now unlimited waiting. Pytesseract represents that
as timeout `0`; `subprocess.run` requires `None`, since its `0` means an immediate
deadline. `SCOUT_TESSERACT_TIMEOUT_S` still accepts an explicit positive timeout.
Timeouts/errors retain their typed skipped-tile records and never become labels.
Do not stop useful OCR work solely because of the former construction deadline,
and do not skip tile coverage to reduce elapsed time. Record runtime resource
measurements separately from source sufficiency and final preparation status.

The r7 job retained its previously imported code through completion: all 402
tiles timed out, with zero labels and zero OCR cache writes. The outer loop's
`completed` status does not indicate OCR success. With r8's default and no
environment override, the same real tile completed in 19.777 seconds with an
identical result hash. This proves the waiting fix, not usable named points.
The fresh r8 Dashboard still needs a new preparation attempt before it can
supply full preparation evidence. The 16 focused OCR/adapter checks passed,
but are not browser G1–G6.
[Read-only timing](../../artifacts/golden-gpx-repair-20260909/receipts/r7-ocr-probe-result.json),
[new default probe](../../artifacts/golden-gpx-repair-20260909/receipts/r8-ocr-default-probe-result.json),
[focused checks](../../artifacts/golden-gpx-repair-20260909/tests/run-20260909T034055039110Z/results.json).

### Distinguish worker reachability from QGIS readiness

On r7 G2 attempt 3, all three preflights timed out before any QGIS processing
started. `/capabilities` returned authenticated HTTP 200, while `/status` and
the application's direct `bridge.hello` probe timed out. Port listening and an
earlier successful hello were insufficient evidence of current readiness.
Waking the existing window did not restore the bridge. Only the task-owned
temporary QGIS instance was stopped with SIGTERM after checking its profile
identity, absence of open project files and absence of active workflows; its
profile and failed receipts were preserved. The new instance's worker status
returned `available` after 18.038 seconds. This does not retroactively execute
the already-failed terrain stage or prove repeated stability. A future Resume
must produce a fresh terrain workflow receipt.

[Failure and recovery record](scout-golden-gpx-g1-g6-qualification-20260909.md#中斷恢復的實際證據).

### Keep initialization and accepted Golden reconstruction distinct

The resumed G2 attempt terminated as `completed_with_gaps` at 03:46:22 UTC,
retaining its only import receipt and valid hashes for all three stages.
Permission initialization produced an unreviewed authoring seed, with no
departure approval or runtime safety authority. When `project.route_days` is
absent, the bootstrap `D1` is unresolved scaffolding; it is not evidence of a
one-day reconstruction or an accepted itinerary. On the same new workspace,
read-only Generate-from-Ref reconstruction preserved nine days, 32 inferred
stays, eight overnight gaps and ten unknown ranges, with all source hashes
matching. A browser review/Accept/Rebuild chain is still required to prove its
use in Permission and the six analyses.

Before restarting the Dashboard after terminal jobs, snapshot the job ledgers,
stage receipts, initialized outputs and candidate/review versions. Check them
again after the new process is listening. The r8 reload preserved all 53 files;
this is service persistence evidence, not browser reload evidence.

[G2 terminal receipt](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-terminal.json),
[new G2 reconstruction](../../artifacts/golden-gpx-repair-20260909/reports/r7-g2-real-reconstruction-after-preparation.json),
[reload persistence](../../artifacts/golden-gpx-repair-20260909/receipts/r8-after-ready-persistence.json).
