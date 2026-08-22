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
- When the user requests a from-zero run, do not use `SCOUT_PRETRIP_DURABLE_EVIDENCE_SOURCE_ROOT`, do not copy material from a reference workspace/material root, and do not repair target artifacts from the reference after the run. Use independent raw GPX/source material and rerun after workflow fixes instead.
- For a from-zero run, set `SCOUT_PRETRIP_RESTORE_FROM_BACKUP=0` so the wrapper does not implicitly replay durable refs from a previous partial target backup.
- Do not call `/safety/*`, update Phase 1 runtime safety truth, or present model/candidate output as runtime truth.
- Do not claim completion with missing OCR dependencies, `planned_no_network` Overpass, empty required refs, timed-out gates, or hidden partials.
- Do not claim completion when risk generation used a route corridor different from map preparation, when `route_base.sampling_strategy` is not `reference_progress_projected_to_nearest_overpass_segment.v1`, or when baseline/calibrated line overlays connect `reference_gpx_gap_fallback` samples into straight map-crossing segments.
- Do not claim local OSM PBF success from refs or endpoint counts alone. The live admin render must use source-backed PBF vector features with OSM-like casing/core strokes and readable labels, must not use the local preview PNG as the OSM layer, and may legitimately have zero runtime OSM raster tile images.
- Keep local OSM PBF render context separate from the Overpass/risk route basis. OSM Carto-style rendering may include roads, landcover, water, buildings, and place labels, but route alignment, risk route-base, segment projection, and mileage alignment may consume only the narrower trail/POI/terrain candidate basis (`TRAIL_HIGHWAYS`, hiking routes, reference POIs, and supported terrain risk evidence). Never use renderer highway sets such as `service`, `tertiary`, or `unclassified` as route/risk candidates unless the reference evidence explicitly requires them.
- Track attempts. Stop after 10 failed attempts. A successful import plus preparation run must finish within 30 minutes; if it cannot, record the failure in the runbook and improve the workflow before retrying.
- If the only failure is a 10-second admin compact API timeout after final durable restore, retry the verifier and a longer client timeout before rerunning import.

## Spatial Policy

Use the `pretrip-route-corridor-map-preparation` spatial policy exactly:

- GPX importer output defines route scope.
- Map preparation may fetch by bbox for acquisition.
- Map preparation must filter and interpret by along-track corridor.
- Pydantic AI receives only source-backed, route-relevant evidence bundles.

Default corridor values are `SCOUT_ROUTE_CORRIDOR_M=500` and `SCOUT_REFERENCE_TRACK_CORRIDOR_M=300`. Segment display, Overpass projection, risk ribbons, route context, K anchors, MCP, and Boss evidence must be corridor evidence, not global bbox evidence.

Risk generation must receive the same `SCOUT_ROUTE_CORRIDOR_M` as map preparation. The expected route-base strategy is `reference_progress_projected_to_nearest_overpass_segment.v1`: project reference route progress to nearest Overpass/local OSM PBF trail corridor candidates, mark unmatched samples as explicit `reference_gpx_gap_fallback`, and never present fallback samples as Overpass-backed route evidence. Baseline `risk_ribbon.geojson` and `calibrated_risk_heatmap.geojson` may connect only adjacent `overpass_projection` samples inside the accepted route-base segment threshold.

Overpass display alignment has a separate GPX-normal snap tolerance. Do not
reuse `SCOUT_ROUTE_CORRIDOR_M=500` as the point/segment projection tolerance:
the default normal snap is 50m via `SCOUT_OVERPASS_ALIGNMENT_MAX_PROJECTION_DISTANCE_M`.
Using 500m can pull GPX checkpoints and segment display points onto nearby but
wrong road/trail centerlines and create map-crossing straight segments.

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
RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS=<comma-separated-stable-raw-tile-cache-namespaces-or-empty>
DURABLE_EVIDENCE_SOURCE_ROOT=<read-only-reference-workspace-or-empty>
ADMIN_BASE_URL=http://127.0.0.1:<admin-port>
```

On this local Mac, CWA/GEE credentials are expected in `/Users/alexwang0315/scout-fusion/.env`. Set `SCOUT_ENV_FILE=/Users/alexwang0315/scout-fusion/.env` for wrapper/manual runs when provider credentials are needed. Do not print secret values; report only whether the env file was loaded and whether required credential names are present.

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

For a from-zero run, the material root must be created from independent raw sources named by the operator or discovered outside the reference workspace. It may contain a target-specific manifest, target-specific MCP JSON, local DTM source paths, local OSM PBF source paths, and raw GPX paths, but it must not be copied from the reference workspace or reference material root. Record the material provenance in `material_manifest.json`.

## Scout AI Skill Invocation Record

When the operator specifically asks to use the Scout AI skill, create an auditable Scout AI invocation envelope before the deterministic wrapper run:

- load `skills/scout/pretrip-import-preparation.yaml`;
- use the configured Pydantic AI/OpenRouter provider for the planning/approval artifact when credentials are present;
- record the model/tool plan reference, run result reference, and `SkillRunRecord` reference under `outputs/scout_ai/`;
- if the current Scout agent builtin write tools cannot perform connected preparation, record `activation_decision=degrade` with `degraded_to=manual_pretrip_import_preparation_runbook` and then run the wrapper exactly as this skill specifies.

This record does not replace the deterministic import/preparation gates. It proves the run was initiated through the Scout AI skill path rather than an untracked direct shell shortcut.

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
    "SCOUT_PRETRIP_RESTORE_FROM_BACKUP": os.environ.get("RESTORE_FROM_BACKUP", "1"),
    "SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT": os.environ["RASTER_TILE_CACHE_ROOT"],
    "SCOUT_PRETRIP_RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS": os.environ.get("RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS", ""),
    "SCOUT_PRETRIP_ADMIN_BASE_URL": os.environ["ADMIN_BASE_URL"],
    "SCOUT_ENV_FILE": os.environ.get("SCOUT_ENV_FILE", "/Users/alexwang0315/scout-fusion/.env"),
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
- Local OSM PBF evidence is vector context, not a replacement for Rudy/Rudy+TW OCR and not a preview PNG layer. When a local PBF source is available, require `osm_pbf_render_geojson_ref`, `osm_pbf_feature_index_ref`, and `/admin/pretrip/projects/<project-id>/osm-pbf-vector.geojson`.
- OSM PBF acceptance requires live vector rendering on the admin surface: line casing/core paths for trail/road/route classes, readable point and line labels, marker/label scale reapplied after layer toggles, and `hasPreviewPngAsOsm=false`. Runtime `image.osm-tile` count is optional and may be zero.
- Use `config/osm_carto_palette.yaml` as Scout's simplified OpenStreetMap Carto palette contract. Preserve render order: background, landcover, water polygons, building polygons, road casings, road fills, points, labels. This renderer context is for visual OSM background only and must not alter Overpass candidate counts, risk sample counts, or mileage alignment counts.
- Do not pass all 32 admin contract layer ids directly to `pretrip_layer_preparation --layers`. `boss-points` is an admin/evidence layer and must be verified through project refs, admin view, and the 32-layer gates, not as a layer-preparation CLI id.
- Cache and TTL checks apply to Scout-managed raster/imagery plans where the provider allows prefetch. Do not delete the cache to force refresh. Let stale tiles refresh individually.
- `SCOUT_PRETRIP_RASTER_TILE_CACHE_ROOT` must point at the shared raw tile root, not `<root>/<project-id>`. If the target project is a suffix/test replay, set `SCOUT_PRETRIP_RASTER_TILE_CACHE_FALLBACK_PROJECT_IDS` to stable raw tile cache namespaces so fresh Rudy/Rudy+TW PNG tiles are copied before remote fetch. This does not permit copying derived OCR, Overpass, risk, mileage, or workspace artifacts.
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

If strict comparison fails on route-pressure or mileage counts, inspect whether the reference workspace is internally coherent before changing workflow behavior. `route_summary`, `segment_display_geometry`, `route_risk`, `route_pressure_profile`, and `mileage_tag_alignment` should describe the same route extent. Do not intentionally reproduce a partial stale reference route-pressure profile unless the operator explicitly asks for artifact-equivalence over current full-route preparation.

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

Check risk route-base metadata before accepting risk overlays:

```bash
rtk env PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import json, os
from pathlib import Path

root = Path(os.environ["PROJECT_ROOT"])
project = json.loads((root / "project.json").read_text())
risk_ref = project.get("risk_score_points_ref")
if not risk_ref:
    raise SystemExit("missing risk_score_points_ref")
risk = json.loads((root / risk_ref).read_text())
route_base = (risk.get("metadata") or {}).get("route_base") or {}
for key in (
    "sampling_strategy",
    "corridor_m",
    "projected_reference_sample_count",
    "fallback_reference_sample_count",
    "route_point_count",
):
    print(key, route_base.get(key))
if route_base.get("sampling_strategy") != "reference_progress_projected_to_nearest_overpass_segment.v1":
    raise SystemExit("unexpected route_base.sampling_strategy")
if float(route_base.get("corridor_m") or 0) != 500.0:
    raise SystemExit("unexpected route_base.corridor_m")
PY
```

The risk point layer may contain fallback candidate points with explicit gap provenance. The baseline risk ribbon and calibrated heatmap must skip fallback/gap pairs, so their connected line geometry should stay on Overpass-projected route-base samples.

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
- OSM PBF refs: feature index, render GeoJSON, vector endpoint renderability, no preview-PNG layer use
- tile cache refs: plan, manifest, seed status, seen/skipped/written counts, cache root
- OCR refs: status, output, cache, label count, hit/miss count, raster label evidence, MCP OCR labels
- route context and mileage refs: route context pack, K anchors, mileage tag alignment, usable anchor count/range
- timing refs: reference segment timing measurement and segment counts
- environment/risk refs: current-run CWA/GEE/environment risk derivatives, route-base metadata, risk score/ribbon/heatmap/delta, skipped fallback/gap pair counts
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
OSM PBF vector refs and live render: PASS/FAIL/NOT APPLICABLE
Tile cache TTL behavior: PASS/FAIL/NOT APPLICABLE
OCR dependency and execution/cache: PASS/FAIL
Raster label adapter: PASS/FAIL
Route context, K anchors, mileage tags: PASS/FAIL
Reference segment timing: PASS/FAIL
Risk route-base strategy/corridor: PASS/FAIL/NOT APPLICABLE
Risk ribbon/calibrated fallback skip: PASS/FAIL/NOT APPLICABLE
CWA/GEE latest-run environment derivatives and timing: PASS/FAIL/NOT APPLICABLE
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
