---
name: scout-pretrip-import-preparation
description: Rebuild and verify Scout pretrip workspaces from GPX/material inputs through importer, map preparation, Overpass corridor alignment, raster tile cache TTL behavior, OCR, K anchors, mileage tags, route context, risk derivatives, durable evidence replay, admin layer gates, and runnable admin UI checks. Use when asked to import GPX, rerun map preparation, refresh tile cache, debug missing OCR or OSM/Overpass layers, create a new local pretrip workspace, or compare a candidate workspace against reference Scout pretrip workspaces.
---

# Scout Pretrip Import Preparation

## Overview

Use this skill to run the complete Scout pretrip import and preparation loop without skipping hidden dependencies or validation gates. The canonical implementation stays in the repo tools; this skill fixes the order, variables, retry policy, and evidence checks another Codex instance must follow.

## Required Reading

Before running or editing anything, read the current versions of:

- `docs/specs/scout-pretrip-full-preparation-runbook.md`
- `docs/specs/scout-pretrip-preparation-pipeline.md`
- `docs/specs/pretrip-route-corridor-map-preparation.md`
- `docs/specs/pretrip-layer-preparation.md`
- `docs/specs/scout-admin-map-layer-contract.md`
- `docs/specs/pre-trip-planning-admin.md`
- `skills/scout/pretrip-import-preparation.yaml`
- `tools/rebuild_pretrip_workspace_on_scout.sh`
- `tools/compare_pretrip_workspace_against_reference.py`

Also respect repo `AGENTS.md`. In this repo, prefix shell commands with `rtk`; if the shell lacks `rtk`, define `rtk(){ "$@"; };` inside the command before running repo commands.

## Non-Negotiable Boundaries

- Do not mutate a reference workspace. Use it only through `SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT` or comparison tools.
- Do not call `/safety/*`, update Phase 1 runtime safety truth, or present model/candidate output as runtime truth.
- Do not claim completion with missing OCR dependencies, `planned_no_network` Overpass, empty required refs, timed-out gates, or hidden partials.
- Track attempts. Stop after 10 failed attempts. A successful import plus preparation run must finish within 30 minutes; if it cannot, record the failure in the runbook and improve the workflow before retrying.
- If the only failure is a 10-second admin compact API timeout after final durable restore, retry the verifier and a longer client timeout before rerunning import.

## Spatial Policy

Use the `pretrip-route-corridor-map-preparation` spatial policy exactly:

- GPX importer output defines route scope.
- Map preparation may fetch by bbox for acquisition.
- Map preparation must filter and interpret by along-track corridor.
- Pydantic AI receives only source-backed, route-relevant evidence bundles.

Default corridor values are `SCOUT_ROUTE_CORRIDOR_M=500` and `SCOUT_REFERENCE_TRACK_CORRIDOR_M=300`. Segment display, Overpass projection, risk ribbons, route context, K anchors, MCP, and Boss evidence must be corridor evidence, not global bbox evidence.

## Preflight

Identify these values before running:

```bash
PROJECT_ID=<target-project-id>
WORKSPACE_ROOT=/tmp/scout-local-pretrip-workspaces
PROJECT_ROOT="$WORKSPACE_ROOT/$PROJECT_ID"
MATERIAL_ROOT=<target-project-material-root>
SOURCE_GPX_ROOT=<reference-gpx-directory>
GOLDEN_ROUTE_GPX=<intended-golden-route-gpx>
RASTER_TILE_CACHE_ROOT=/tmp/scout-local-data/raster-tiles
DURABLE_EVIDENCE_SOURCE_ROOT=<read-only-reference-workspace-or-empty>
ADMIN_BASE_URL=http://127.0.0.1:<admin-port>
```

Verify dependencies and material paths first:

```bash
rtk ./venv/bin/python - <<'PY'
import importlib.util
import os
from pathlib import Path

for name in ("numpy", "PIL", "pytesseract"):
    print(f"{name}: {'PASS' if importlib.util.find_spec(name) else 'FAIL'}")
for name in ("MATERIAL_ROOT", "SOURCE_GPX_ROOT", "GOLDEN_ROUTE_GPX"):
    value = os.environ.get(name, "")
    print(f"{name}: {value} exists={Path(value).exists() if value else False}")
PY
rtk tesseract --version
```

If OCR is missing, install local tooling before continuing. Do not mark OCR as blocked and move on:

```bash
rtk ./venv/bin/python -m pip install pytesseract
rtk brew install tesseract tesseract-lang
rtk tesseract --version
```

If `numpy` is missing from the local venv, install it before risk generation:

```bash
rtk ./venv/bin/python -m pip install numpy
```

## Material Root Policy

Each target project id needs material metadata aligned to that project id when material includes project-scoped MCP evidence.

If creating `tryimportN` from another material root, copy the material root to a target-specific path and update project-scoped JSON such as:

- `material_manifest.json`
- `sources/mcp/named_point_evidence.json`

Do not point a new project id at a previous project id's MCP material unchanged; the importer should reject it with a project mismatch.

## One-Command Rebuild

Prefer the wrapper. It performs GPX import, durable evidence restore, reference segment timing, connected map preparation, route context collection, final durable evidence restore, and workspace spec alignment.

Use Python for the 30-minute timeout on macOS because GNU `timeout` may not exist:

```bash
rtk ./venv/bin/python - <<'PY'
import os
import subprocess
import time

env = os.environ.copy()
env.update({
    "SCOUT_PROJECT_ID": os.environ["PROJECT_ID"],
    "SCOUT_PRETRIP_WORKSPACE_ROOT": os.environ["WORKSPACE_ROOT"],
    "SCOUT_PRETRIP_MATERIAL_ROOT": os.environ["MATERIAL_ROOT"],
    "SCOUT_SOURCE_GPX_ROOT": os.environ["SOURCE_GPX_ROOT"],
    "SCOUT_GOLDEN_ROUTE_GPX": os.environ["GOLDEN_ROUTE_GPX"],
    "SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT": os.environ.get("DURABLE_EVIDENCE_SOURCE_ROOT", ""),
    "SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT": os.environ["RASTER_TILE_CACHE_ROOT"],
    "SCOUT_PRETRIP_ADMIN_BASE_URL": os.environ["ADMIN_BASE_URL"],
    "SCOUT_PRETRIP_LAYER_PROFILE": "pi-online-explicit",
    "SCOUT_PRETRIP_NETWORK_MODE": "explicit-fetch",
    "SCOUT_PRETRIP_ALLOW_NETWORK_FETCH": "1",
    "SCOUT_ROUTE_CORRIDOR_M": "500",
    "SCOUT_REFERENCE_TRACK_CORRIDOR_M": "300",
    "SCOUT_PRETRIP_SEED_IMAGERY_CACHE": "1",
    "SCOUT_PRETRIP_IMAGERY_MIN_ZOOM": "5",
    "SCOUT_PRETRIP_IMAGERY_MAX_ZOOM": "14",
    "SCOUT_PRETRIP_IMAGERY_SEED_MAX_TILES": "250",
})
started = time.monotonic()
subprocess.run(["tools/rebuild_pretrip_workspace_on_scout.sh"], env=env, timeout=1800, check=True)
print(f"elapsed_seconds={time.monotonic() - started:.0f}")
PY
```

For fresh live evidence inspection, leave `DURABLE_EVIDENCE_SOURCE_ROOT` empty. For reference-equivalence rebuilds, set it to the reviewed standard workspace. CWA/GEE environment evidence is always current-run, no-cache evidence: never replay CWA weather/QPF, GEE SMAP/GPM, or derived environment risk values from a durable source workspace or local workspace cache. A connected preparation run must refetch them or record the current blocker/status.

## OSM, Overpass, And Tile Cache Policy

- Overpass vector evidence must be fetched in connected mode and aligned to route segments. `planned_no_network` or zero candidates is not a complete connected preparation run.
- Do not bulk-cache public OSM Standard raster tiles. If the OSM base map is not visible, verify admin layer wiring, tile proxy behavior, and browser network failures instead of treating absent cached OSM raster tiles as the import target.
- Cache and TTL checks apply to Scout-managed raster/imagery plans where the provider allows prefetch. Do not delete the cache to force refresh. Let stale tiles refresh individually.
- CWA/GEE artifacts are not TTL cache artifacts. Treat `cwa-weather`, `cwa-qpf`, `soil-moisture`, `antecedent-rain`, and environment risk derivatives as latest-run evidence every time.
- Every CWA source artifact and every CWA-derived model/review artifact must carry hour-precision timing metadata: API request attempt hour, successful fetch hour when data was returned, provider valid-from/valid-until or observation hours when available, `time_precision: hour`, and timezone. A failed or credential-blocked fetch must leave fetch/validity hours empty instead of inventing freshness.
- OCR cache is keyed by tile image hash and OCR engine/language/version. Cache hits are valid execution evidence.

## Required Checks

Run strict comparison when reference workspaces are provided:

```bash
rtk ./venv/bin/python tools/compare_pretrip_workspace_against_reference.py \
  --reference-root <reference-workspace-root> \
  --candidate-root "$PROJECT_ROOT" \
  --strict-counts
```

Run the Scout layer contract gates:

```bash
rtk env PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py --repo-root .

rtk env PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_scout_layer_contract.py \
  --repo-root . \
  --project-root "$PROJECT_ROOT" \
  --require-workspace
```

Run workspace spec alignment:

```bash
rtk env PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/verify_pretrip_workspace_spec_alignment.py \
  --workspace-root "$WORKSPACE_ROOT" \
  --project-id "$PROJECT_ID" \
  --admin-base-url "$ADMIN_BASE_URL" \
  --allow-network-calls
```

Run admin browser smoke when the browser runtime is available:

```bash
rtk node tools/admin_ui_visual_smoke.js --python ./venv/bin/python
```

Open the runnable UI at:

```text
$ADMIN_BASE_URL/admin/pretrip?projectId=$PROJECT_ID
```

The complete admin layer contract has 32 layers:

```text
imagery, rudy, rudy-twmap, relief, geology, topo-5k, forest, osm, terrain,
corridors, overpass, route, completed-track, reference-tracks, retreat,
segments, risk-ribbon, risk-heatmap, risk-delta, soil-moisture,
antecedent-rain, cwa-qpf, risk-score, checkpoints, pois, hazards,
route-notes, cwa-weather, mcp, boss-points, events, weather-api
```

Report every layer as PASS or FAIL when the task touches GPX import, map preparation, admin map rendering, layer controls, route projection, terrain/risk outputs, OCR, Boss/MCP, mileage evidence, or `/admin/pretrip`, `/admin/debug`, `/admin`.

## Artifact Checks

Inspect `project.json` and referenced files for at least:

- importer refs: route evidence bundle, summary, checkpoints, segments, reference tracks, admin/debug projection
- Overpass refs: raw payload, map context, evidence, route alignment, aligned segment candidates/display geometry
- tile cache refs: plan, manifest, seed status, seen/skipped/written counts, cache root
- OCR refs: status, output, cache, label count, hit/miss count, raster label evidence, MCP OCR labels
- route context and mileage refs: route context pack, K anchors, mileage tag alignment, usable anchor count/range
- timing refs: reference segment timing measurement and segment counts
- environment/risk refs: current-run CWA/GEE/environment risk derivatives, risk score/ribbon/heatmap/delta
- MCP/Boss refs: named-point evidence, route pressure profile, Boss point JSON and GeoJSON

Do not use a green item count as a substitute for required refs and non-empty source-backed evidence.

## Retry And Runbook Logging

Append every failed attempt and fix to `docs/specs/scout-pretrip-full-preparation-runbook.md` with:

- timestamp and target workspace
- attempt number out of 10
- elapsed seconds
- failing command or gate
- exact symptom
- root cause if known
- fix applied before retry
- whether the issue changes the SOP

Known SOP issues from the local 2026-06-25 run:

- macOS may lack GNU `timeout`; use Python `subprocess.run(..., timeout=1800)`.
- MCP material copied from another project id must have project-scoped JSON updated for the target id.
- A wrapper-level 10-second admin compact API timeout can happen after a valid final restore; retry the verifier and longer API request before rerunning import.

## Completion Report

End with a concise report:

```text
Project:
Workspace:
Material root:
Golden GPX:
Reference workspaces:
Elapsed seconds:
Attempts used:

Specs read: PASS/FAIL
Spatial policy bbox fetch and corridor filter: PASS/FAIL
Importer: PASS/FAIL
Map preparation explicit fetch: PASS/FAIL
Overpass vector evidence and segment alignment: PASS/FAIL
Tile cache TTL behavior: PASS/FAIL/NOT APPLICABLE
OCR dependency and execution/cache: PASS/FAIL
Raster label adapter: PASS/FAIL
Route context, K anchors, mileage tags: PASS/FAIL
Reference segment timing: PASS/FAIL
Risk/environment derivatives: PASS/FAIL/NOT APPLICABLE
MCP/Boss evidence: PASS/FAIL/NOT APPLICABLE
Reference comparison: PASS/FAIL/NOT APPLICABLE
32-layer repo gate: PASS/FAIL
32-layer workspace gate: PASS/FAIL
Workspace spec alignment: PASS/FAIL
Browser UI smoke: PASS/FAIL/NOT APPLICABLE
Runnable UI URL:
Known warnings:
Known partials:
Next required action:
```

Only claim completion when the required gates for the user's stated target are checked and evidence-backed.
