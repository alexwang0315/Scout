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

## Local Skills Available

The Skills CLI is optional. On this machine, `npx`/`npm` were not available, so
external `npx skills find ...` could not be used.

Installed local skills that help this pipeline:

- `.agents/skills/scout-route-context-briefing/SKILL.md`
  - Use after import/map/OCR when building route context artifacts and briefing
    HTML.
- `.agents/skills/scout-route-pressure-intelligence/SKILL.md`
  - Use when public P0/P1 pressure evidence should inform Route Boss Demand.
- `~/.codex/skills/scout-ai-agent-development/SKILL.md`
  - Use for Scout/Pydantic AI development, tests, and safety boundary reviews.

There is currently no installed skill that fully wraps GPX import, map
preparation, TTL tile cache, OCR, K anchors, and all validation gates. This
runbook is the complete operator wrapper until such a skill exists.

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
export ADMIN_BASE_URL=http://127.0.0.1:9099
```

For the current local Nengao/Andongjun workspace, verify the golden GPX path
before running import. Do not assume a file in `reference/` is golden only
because its name is similar.

## Step 0: Dependency And Material Preflight

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python - <<'PY'
import importlib.util
from pathlib import Path

checks = {
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

- `pytesseract: PASS`
- `PIL: PASS`
- `tesseract --version` exits `0`
- `GOLDEN_GPX` exists and is the intended golden route
- `REFERENCE_DIR` exists and contains reference GPX files

If Tesseract or `pytesseract` is missing, install it before continuing. Do not
classify the run as complete with a blocked OCR dependency.

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
  --imagery-max-zoom 16 \
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
- layer manifests and admin/debug projections.

## Step 3: Tile Cache TTL Policy

The raster tile cache default TTL is 30 days
(`DEFAULT_IMAGERY_TILE_CACHE_TTL_DAYS = 30`). Do not delete the cache to force
refresh.

Expected behavior when `--seed-imagery-cache` is used:

- fresh cached tiles are skipped;
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
