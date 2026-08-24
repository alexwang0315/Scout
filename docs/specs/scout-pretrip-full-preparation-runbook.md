# Scout Pretrip Full Preparation Runbook

## Purpose

This is the no-skip operator runbook for rebuilding a Scout pretrip workspace
from GPX material through runnable admin UI layers.

Use this file when a rerun must include all of:

- GPX import;
- route-corridor map preparation;
- Overpass vector fetch and segment alignment;
- Rudy/Rudy+TW tile cache seeding with TTL behavior;
- OCR and raster label adapter output;
- route context, K anchors, mileage tag alignment;
- terrain/risk/MCP/Boss synthesis;
- Scout admin map layer gates and browser smoke checks.

If any required step is skipped, report the run as partial.

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

Current-position and target sampling is a separate user gesture in Weather.
The user selects a prepared checkpoint and presses `授權目前位置並更新降雨趨勢`.
Only then does the browser request geolocation, obtain a server-issued short-
lived approval, and call `POST .../rainfall-trend`. The response is kept in UI
state; the server persists only the sanitized approval audit with
`rawCoordinatesPersisted=false`.

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

`SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT` must point at the shared raster tile
root, for example `/Users/alexwang0315/workspace/scout-local-data/raster-tiles`
or `/tmp/scout-local-data/raster-tiles`. Do not set it to
`.../raster-tiles/<project-id>` because the cache writer already appends the
project namespace and layer id. The wrapper normalizes this mistake, but manual
commands must avoid it.

For `tryimport`, suffix-test, or from-zero comparison runs that must reuse
unchanged Rudy/Rudy+TW raw tiles without replaying old workspace artifacts, set
`SCOUT_PRETRIP_RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS` to one or more stable
raw tile cache namespaces, comma-separated. The seeding step copies only fresh
raw PNG tiles according to TTL before remote fetch; it does not copy OCR,
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
  abandoned staged session.
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

References:

- GRASS `r.watershed`: https://grass.osgeo.org/grass-stable/manuals/r.watershed.html
- GRASS `r.stream.extract`: https://grass.osgeo.org/grass-stable/manuals/r.stream.extract.html
