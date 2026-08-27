# Spec: Pretrip Historical GPX Importer

Date: 2026-06-02
Last updated: 2026-08-26

## Objective

Build a **Historical GPX Importer**（歷史/開放下載 GPX 匯入器） for Scout Phase 4
pretrip planning. It imports operator-supplied local GPX files downloaded from
open or community sources, normalizes them into a project workspace, and
produces a route-evidence bundle that downstream **Map Preparation**（地圖準備）
must use as its spatial base.

This spec extends `docs/specs/pretrip-standalone-importer.md` with a stricter
contract for historical / open-download GPX corpora:

- one selected **golden route**（主參考路線；出發前選定的相似路線）;
- many **reference tracks**（歷史/專家/山友參考軌跡）;
- extracted GPX waypoint/route notes;
- route geometry, bbox, and along-track corridor hints for map preparation;
- source attribution and freshness metadata for later Pydantic AI semantic
  judgement.

Pretrip has no actual user track yet. The golden route is not proof that the
current user has walked the route. It is a planning stand-in chosen from
historical evidence. The actual walked route belongs to post-analysis after the
trip returns safely.

For GPX import and Dashboard clone behavior, this dated spec and
`docs/specs/pretrip-layer-preparation.md` are normative. Older run logs,
temporary workarounds, or remembered trajectories that used importer-only
completion, a second preparation pass, manual artifact repair, or a `_v2`
workspace remain incident evidence only and must not be reintroduced as the
standard operating procedure.

## Role In The Pipeline

The importer must run before route-corridor map preparation:

```text
historical/open-download GPX corpus
  -> Historical GPX Importer
  -> route evidence bundle
  -> optional MCP synthesis from named-point evidence
  -> Route-Corridor Map Preparation
  -> OSM/GIS/web/raster along-track evidence
  -> Pydantic AI semantic judgement
  -> candidate CP / Ln / POI / detour review items
```

The route evidence bundle is the source of truth for map preparation scope. Map
preparation must not perform route-independent OSM/GIS/web searches for this
project when a valid importer route bundle exists. The receiving preparation
contract is `docs/specs/pretrip-layer-preparation.md`.

## Dashboard Workspace Clone And Single-Pass Contract

The normal Dashboard user flow for producing a new route workspace is the
Workspace page `Clone` action, backed by:

```text
POST /admin/dashboard/workspaces/{source_project_id}/clone
```

with `confirm_clone=true` and a new `target_project_id`. This is not a filesystem
copy operation. The canonical transaction is:

```text
read-only source workspace and material manifest
  -> validate all source identities, hashes, paths, and required tools
  -> one clean GPX import into a new target (`overwrite=false`)
  -> one full map preparation run using that target route bundle
  -> post-layer enrichments and map-preparation spec artifacts
  -> `outputs/workspace_clone_receipt.json`
  -> expose/open the target workspace only as prepared or explicitly degraded
```

The source workspace is an input catalog, not a derived-artifact template. The
clone flow must preserve these invariants:

- source and target project ids differ;
- source and target are direct children of the configured workspace root;
- the target does not already exist and is never overwritten;
- the source `project.json` and `inbox/source_manifest.json` project ids match
  the requested source id;
- the source inbox declares exactly one golden route and at least one reference
  GPX;
- every declared GPX exists inside the source workspace and matches its SHA-256;
- additional GPX files declared by the material corpus are deduplicated by
  content hash against the golden route and existing references;
- source-derived semantic outputs, CP templates, route architecture, risk
  layers, and Navigation results are not copied into the target;
- a hash/provider/tile-key verified raster cache may be reused as a cache
  optimization, but it is never route truth and must be recorded as fallback
  provenance;
- source MCP named-point evidence may be rebound only through its typed schema,
  with only `project_id` changed and both source and rebound hashes recorded.

The target must be built from the declared raw/source material. It must not be
made to resemble `chilai_nanhua_day1_scoutAI` by copying Chilai-specific
checkpoints, ridges, valleys, route notes, reference timing, or risk evidence.
Feature parity means that the same preparation mechanisms run for the new
route; it does not mean that every route receives identical facts or counts.

### Material And Runtime Preflight

All failures that can be discovered without writing the target must be checked
before GPX import creates the target directory. Preflight includes:

- GPX source existence, roles, project identity, SHA-256, and corpus
  deduplication;
- material manifest schema and declared source paths;
- local OSM PBF path, SHA-256/source metadata, and cache policy when configured;
- Python `osmium` importability in the same interpreter that runs the Dashboard;
- the persistent `osmium` CLI binding used by preparation;
- DTM directories and declared full-route GeoTIFF sources, including hash, CRS,
  CRS evidence, and source resolution;
- typed MCP named-point evidence identity;
- writable workspace root and non-existent target path.

The supported workstation entrypoint is the project-owned runtime established
once by `tools/setup_dashboard_workspace_runtime.sh` and subsequently launched
through `scout-dashboard` or `tools/run_dashboard_workspace.sh`. A parser found
only in a legacy venv or an unrelated shell PATH does not satisfy this
preflight. The launch command must never install dependencies implicitly.

If a configured PBF exists but Python `osmium` is unavailable in the active
Dashboard interpreter, clone fails before import and no target workspace is
created. Falling back to Overpass does not satisfy the configured local-PBF
contract because it would leave the workspace without its required offline OSM
render extract.

### Single-Pass Handoff And Failure State

Importer success alone is not Workspace Clone success. The importer writes the
route evidence bundle, then the same user operation immediately invokes Layer
Preparation with the selected target, route corridor, material root, DTM refs,
local PBF refs, raster-cache policy, and post-process switches. The successful
receipt must identify both stages:

```text
stages.gpx_import.status = completed
stages.map_preparation.status = ready | ready_with_warnings | completed
clone_strategy = clean_import_from_source_inbox_then_map_preparation
dynamic_evidence_policy.weather_cwa_gee_overpass_refreshable = true
dynamic_evidence_policy.connected_refresh_rewrites_primary_layer_manifest = false
dynamic_evidence_policy.geology_runtime_provider_refreshable = true
dynamic_evidence_policy.geology_frozen_at_preparation = false
boundary.source_workspace_mutated = false
boundary.target_overwrite_allowed = false
```

If preparation fails after import, an `imported_preparation_failed` receipt may
remain for diagnosis, but the target is incomplete: it must not be advertised
as ready, selected automatically, or used as a departure workspace. Fix the
workflow/tool dependency and replay the same declared import-plus-preparation
transaction. Do not normalize a manual post-import repair or a newly named
`_v2` workspace as the standard path. A one-off repair can recover evidence for
debugging, but it is not acceptance proof until the original single-pass user
flow succeeds reproducibly.

A failed clone must not permanently consume the requested target id. The
preferred implementation imports and prepares in an operation-scoped staging
directory, writes the completed receipt last, and atomically publishes the
target only after validation. If a legacy implementation has already exposed a
partial target, Dashboard must provide an explicit resume or confirmed
discard-and-retry operation for the same target id. Asking the operator to add
`_v2` is not the recovery contract.

## Source Policy

**Open-download GPX**（開放下載 GPX） means the operator has already obtained a GPX
file from a route-sharing site, public archive, personal backup, or community
source and is allowed to use it for local planning. The importer does not grant
permission, crawl websites, bypass download warnings, or republish raw GPX.

Every source record should preserve:

- original local path;
- original filename;
- source URL or provider note when known;
- source title and author/provider when known;
- retrieval timestamp when known;
- file size;
- SHA-256 hash;
- license/permission note;
- route role: `golden_route`, `reference_track`, `excluded`, or `unknown`;
- importer timestamp and importer version.

Raw GPX XML must stay referenced by path/hash. Normalized Scout outputs must not
embed raw GPX payloads.

## Golden Route And References

The importer must distinguish:

- **golden route**（主參考路線）: the selected planning route used to build the
  route timeline, route bbox, segment frame, and map-preparation corridor;
- **reference tracks**（參考軌跡）: additional historical GPX tracks used for
  comparison, route uncertainty, route-note evidence, and candidate CP support;
- **manual waypoint route**（手動畫航點路線）: route sections that do not have
  historical track support and therefore require `danger_review`.

The selected golden route should be an operator-curated, complete point sequence
for the intended start-to-finish trip. It defines the Architecture mileage axis
from `0K` to finish. Downstream crowd coverage may mark bins
`insufficient_evidence`, but must not trim a sparse prefix, move the origin, or
replace this scope with a crowd-derived axis.

Multi-track and multi-`trkseg` inputs require an explicit route-identity check
before the golden route is accepted. The importer must inspect each part's
start/end coordinates, candidate order, direction, cross-part gap, timestamp
monotonicity, and intended trip direction. File/XML order must not be assumed to
be route order. A large endpoint jump is a route-identity blocker or reviewed
resume gap, not an ordinary segment. Display geometry must preserve legitimate
part boundaries and must not draw a synthetic connector between unrelated
tracks.

The route evidence bundle must persist the resulting route identity, including
an ordered part list, direction for each part, endpoint/gap diagnostics, source
hashes, and a deterministic route-identity fingerprint. Downstream preparation
records that fingerprint as an input and must reject route-derived artifacts
whose fingerprint belongs to a different order, direction, or route.

Once the golden route order or identity changes, every route-dependent output
must be regenerated from that route: route summary, CP/segments, retreat route,
reference timing, terrain, ridges/valleys, mileage/K alignment, Architecture,
risk, weather projection, Navigation, and map-preparation corridor. Passing a
layer-count or file-existence gate does not prove that these artifacts use the
correct route identity.

Golden geometry and statistical observation are separate roles. The golden GPX
also remains in `historical_gpx_source_index.json` as one equal-weight
`scope_reference`. The reference pace/energy analyzer reads each complete staged
source via `workspace_ref` and then evaluates every adjacent trackpoint pair with
its actual `delta_t`. Its V0 statistical window is the strict open interval
`1 < speed_kmh < 10`; an invalid pair removes only that pair. Whole-track or
whole-`<trkseg>` average speed must never discard otherwise usable samples.

When no GPX supports a section:

- it remains a manual waypoint route candidate;
- it receives `danger_review: true`;
- it can be planned, but not treated as historically observed;
- it must be visible to `/admin/pretrip` before any compile/handoff step.

## Commands

Mac/admin workstation example:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pretrip_import \
  --project-id nenggao_andongjun_alpha \
  --golden-route-gpx /Users/alexwang0315/Downloads/twmap-gpx-yunhai/能高安東軍.gpx.gpx \
  --reference-dir /Users/alexwang0315/Downloads/twmap-gpx-yunhai \
  --workspace-root /tmp/scout-pretrip-alpha \
  --profile mac-workstation \
  --checkpoint-spacing-m 750 \
  --max-reference-display-points 5000 \
  --max-reasonable-gpx-speed-kmh 120 \
  --mcp-named-point-evidence /Users/alexwang0315/scout-materials/sources/mcp/named_point_evidence.json
```

Scout Pi offline example:

```bash
/data/scout/venv/bin/python -m pretrip_import \
  --project-id nenggao_andongjun_alpha \
  --golden-route-gpx /data/scout/pretrip/inbox/golden/route.gpx \
  --reference-dir /data/scout/pretrip/inbox/references \
  --workspace-root /data/scout/pretrip/workspaces \
  --profile pi-offline \
  --checkpoint-spacing-m 750 \
  --max-reference-display-points 3000 \
  --max-reasonable-gpx-speed-kmh 120 \
  --mcp-named-point-evidence /data/scout/materials/pretrip/nenggao_andongjun_alpha/sources/mcp/named_point_evidence.json
```

Preview from admin runtime:

```bash
curl -X POST http://127.0.0.1:9099/admin/pretrip/projects/nenggao_andongjun_alpha/import-gpx-preview \
  -H 'Content-Type: application/json' \
  -d '{
    "golden_route_gpx": "/data/scout/pretrip/inbox/golden/route.gpx",
    "reference_dir": "/data/scout/pretrip/inbox/references",
    "workspace_root": "/data/scout/pretrip/workspaces",
    "profile": "pi-offline"
  }'
```

Confirmed run from admin runtime must require an explicit confirmation flag:

```bash
curl -X POST http://127.0.0.1:9099/admin/pretrip/projects/nenggao_andongjun_alpha/import-gpx \
  -H 'Content-Type: application/json' \
  -d '{
    "confirm_workspace_write": true,
    "golden_route_gpx": "/data/scout/pretrip/inbox/golden/route.gpx",
    "reference_dir": "/data/scout/pretrip/inbox/references",
    "workspace_root": "/data/scout/pretrip/workspaces",
    "profile": "pi-offline"
  }'
```

The preferred end-user execution remains the Dashboard Workspace Clone action:

```bash
curl -X POST \
  http://127.0.0.1:9099/admin/dashboard/workspaces/source_workspace_id/clone \
  -H 'Content-Type: application/json' \
  -d '{
    "target_project_id": "new_workspace_id",
    "confirm_clone": true,
    "requested_by": "dashboard_operator"
  }'
```

Direct importer CLI calls are supported for development and fixture replay,
but a CLI import by itself is not proof of the Dashboard clone workflow.

## Output Structure

The importer writes under the selected workspace:

```text
<workspace-root>/<project-id>/
  project.json
  sources/
    historical_gpx_source_index.json
  normalized/
    routes/
      filtered/
        primary.<name>.speed_filtered.gpx
        reference_001.<name>.speed_filtered.gpx
      golden_route.geojson
      reference_tracks.geojson
      route_summary.json
      route_evidence_bundle.json
    notes/
      gpx_route_note_candidates.json
  candidates/
    checkpoints.json
    segments.json
    route_note_ln_proposals.json
    gis_checkpoint_candidates.json
  outputs/
    import_manifest.json
    workspace_clone_receipt.json  # Dashboard clone orchestration only
    mcp/
      named_point_evidence.json
      mcp_retrieval_plan.json
      mcp_ocr_labels.json
      mcp_candidates.json
      mcp_cp_support_reconciliation.json
    gpx_speed_filter_report.json
    resume_segments.json
    rest_area_candidates.json
    reference_tracks.json
    reference_track_display_geometry.json
    checkpoint_events.json
    segment_display_geometry.json
    admin_projection.json
    debug_projection_events.jsonl
```

## Clean / Overwrite Rebuild Semantics

`--overwrite` and Scout rebuild scripts may regenerate route-derived artifacts
from the fixed source material, but they must not silently erase durable admin
evidence that importer and map preparation do not own. When an existing
workspace is moved aside before a clean rebuild, the new workspace should
restore safe project-relative refs from the backup for:

- `readiness_report_ref`;
- `resource_plan_ref`;
- `planned_eta_ref`;
- `departure_bundle_manifest_ref`;
- `route_comparison_ref`;
- capability timeline refs when present.

Restore rules:

- copy only refs that are relative to the source project root and resolve inside
  the destination project root;
- do not copy absolute paths or refs containing `..`;
- do not overwrite a destination artifact that already exists;
- refresh review/debug/admin projection summaries only as workspace projection
  artifacts;
- keep all restored artifacts pretrip/admin evidence and never promote them to
  Phase 1 runtime safety truth.

This lets operators rerun importer plus map preparation on Scout without losing
readiness, ETA, resource planning, departure bundle, route-comparison, or
timeline evidence that is still needed by `/admin/pretrip`, `/admin/debug`, and
handoff review surfaces.

Workspace Clone is stricter than an operator-approved rebuild: it always uses a
new target and `overwrite=false`. It must not rename a failed target to preserve
the requested name, replace the source, or silently restore semantic route
artifacts from a previous target. Any diagnostic partial target remains clearly
failed until an explicit cleanup/resume transaction is implemented and invoked.

## MCP Synthesis Integration

When `--mcp-named-point-evidence` is provided, or when the fixed material root
contains `sources/mcp/named_point_evidence.json`, the importer must run the
existing MCP synthesis pipeline after checkpoint generation and before admin
projection generation.

The importer writes:

- `outputs/mcp/named_point_evidence.json`;
- `outputs/mcp/mcp_retrieval_plan.json`;
- `outputs/mcp/mcp_ocr_labels.json`;
- `outputs/mcp/mcp_candidates.json`;
- `outputs/mcp/mcp_cp_support_reconciliation.json`.

`project.json`, `outputs/import_manifest.json`, and `outputs/admin_projection.json`
must include the corresponding `mcp_*_ref` values and counts. `/admin/pretrip`,
`/admin/debug`, and `/admin` must therefore show MCP from a clean re-imported
workspace, not only from restored fixture state.

MCP synthesis remains fixture-backed / evidence-only in this slice:

- no live search is performed by importer tests;
- no `/safety/*` endpoint is called;
- MCP candidates are pretrip planning evidence only;
- MCP cannot compile into runtime truth without human review and a later
  departure-gate handoff.

`normalized/routes/route_evidence_bundle.json` is the handoff artifact for map
preparation.

## Route Evidence Bundle

The route evidence bundle should be compact and deterministic:

```json
{
  "artifact_kind": "pretrip_historical_gpx_route_evidence_bundle",
  "schema_version": "historical_gpx_importer.v1",
  "project_id": "nenggao_andongjun_alpha",
  "golden_route": {
    "source_id": "gpx.source.能高安東軍",
    "source_path": "/data/scout/pretrip/inbox/golden/route.gpx",
    "sha256": "...",
    "geometry_ref": "normalized/routes/golden_route.geojson",
    "route_bbox_wgs84": [121.12, 23.91, 121.31, 24.04],
    "route_distance_m": 14600
  },
  "reference_tracks": [
    {
      "source_id": "gpx.source.001",
      "role": "reference_track",
      "geometry_ref": "normalized/routes/reference_tracks.geojson",
      "sha256": "...",
      "freshness": {
        "track_time_available": true,
        "old_route_note_flag": false
      }
    }
  ],
  "route_scope_for_map_preparation": {
    "bbox_wgs84": [121.10, 23.89, 121.33, 24.06],
    "route_corridor_m": 500,
    "reference_track_corridor_m": 300,
    "corridor_policy": "bbox_fetch_then_along_track_filter"
  },
  "note_candidate_refs": [
    "normalized/notes/gpx_route_note_candidates.json"
  ],
  "gpx_filter_refs": {
    "speed_filter_report_ref": "outputs/gpx_speed_filter_report.json",
    "resume_segment_report_ref": "outputs/resume_segments.json",
    "rest_area_candidates_ref": "outputs/rest_area_candidates.json"
  },
  "boundary": {
    "candidate_only": true,
    "actual_user_track_available": false,
    "phase1_runtime_mutation_allowed": false,
    "safety_api_called": false
  }
}
```

The bundle separates:

- `bbox_wgs84`: coarse fetch boundary for map preparation;
- `route_corridor_m`: along-track semantic filter around the golden route;
- `reference_track_corridor_m`: along-track support filter around historical
  reference tracks.

Reference segment timing must be generated against the current target
workspace's reviewed CP/MCP candidates, segments, and golden-route distance.
Names from GPX waypoints are supporting evidence, not join keys that authorize
reuse of another route's fixed checkpoint or timing template. Matching should
prefer route-distance windows and retain unmatched/low-quality tracks as
reviewable geometry rather than fabricating timing support.

## Five GPX Filter Mechanisms

The importer must run the **five GPX filter mechanisms**（GPX 五大過濾/診斷機制）
before route summaries, CP generation, segment generation, reference display
geometry, and map-preparation handoff are produced.

These filters are planning-data hygiene, not runtime truth. They protect the
pretrip workspace from obvious GPS artifacts while preserving evidence that may
carry human meaning.

These importer hygiene filters are not the Architecture statistical speed
window. In particular, `1 < speed_kmh < 10` must not be implemented here as
point deletion or whole-segment rejection. The importer preserves the raw staged
source by path/hash; statistical analysis reads that complete source and applies
its pairwise filter independently. A derived speed-filtered GPX remains a map/
normalization artifact and a compatibility fallback, not the default statistical
input.

### 1. Absolute Speed Outlier Filter（絕對速度離群點過濾）

Remove a track point when reaching it from the previous kept point would require
speed above `max_reasonable_speed_kmh`.

Default:

```text
max_reasonable_speed_kmh = 120.0
```

Output:

- removed point count;
- source index;
- lat/lon/time;
- required speed;
- reason: `required_speed_exceeds_absolute_threshold`.

### 2. Relative Speed Spike Filter（相對速度突增過濾）

Remove a track point when its required speed is above
`max_previous_speed_ratio` times the previous kept segment speed, even if it is
below the absolute threshold.

Default:

```text
max_previous_speed_ratio = 8.0
```

`3.0` remains a strict-mode value for regression tests or explicitly requested
cleanup runs, but it is too aggressive for alpha default GPX import because it
can remove many usable mountain-track points before map review.

Output:

- previous kept speed;
- max relative speed;
- speed ratio;
- reason: `required_speed_exceeds_previous_speed_ratio`.

### 3. Resume Gap Diagnostic（中斷後續接段診斷）

Long distance jumps can mean multi-day continuation, GPS-off time, transport,
or device restart. They must not be blindly pruned as speed outliers when the
gap is beyond `max_reasonable_point_gap_m`. Instead, keep the points and mark
the affected segment as a **resume segment**（續接段） needing review.

Default:

```text
max_reasonable_point_gap_m = 1000.0
```

Output:

```text
outputs/resume_segments.json
```

Affected segment candidates and segment display geometry must carry:

- `resume_segment: true`;
- gap count;
- max gap distance;
- source point indices;
- review state `needs_review`.

### 4. Route-Note Protection Filter（路線註記保護例外）

When a point would be removed by a speed filter but is near a GPX waypoint note,
the importer must keep it and report it as an exemption. This protects useful
human route notes from being lost because the associated GPS coordinate is
noisy.

Default:

```text
route_note_protection_radius_m = 30.0
```

Output:

- exempted point count;
- would-remove reason;
- route note text;
- nearest waypoint distance;
- exemption reason: `route_note_protected`.

### 5. Low-Speed Dense Cluster Filter（低速密集點群過濾/候選化）

Dense low-speed point clusters on the golden route should become
**rest area / camp area candidates**（休息/營地候選）, not noise. This is a
candidate-generation filter: it does not delete points, but converts slow dense
clusters into reviewable CP candidates.

Defaults:

```text
rest_area_max_speed_m_per_min = 5.0
rest_area_cluster_radius_m = 80.0
rest_area_min_duration_seconds = 1200
rest_area_min_source_point_count = 16
```

Output:

```text
outputs/rest_area_candidates.json
```

When accepted by deterministic policy, the importer inserts a checkpoint
candidate with:

- `checkpoint_type: rest_area`;
- `source_attribution.source_kind: rest_area_cluster`;
- source point count;
- duration;
- mean speed;
- cluster radius;
- distance to filtered route;
- review state `needs_review`.

## Filter Output Contract

The importer must write one compact filter report:

```text
outputs/gpx_speed_filter_report.json
```

The report includes:

- `artifact_kind: pretrip_gpx_speed_filter_report`;
- source file count;
- original / filtered / removed / exempted track point counts;
- per-source primary/reference summaries;
- `max_reasonable_speed_kmh`;
- `max_previous_speed_ratio`;
- `route_note_protection_radius_m`;
- source SHA-256 and filtered output SHA-256;
- boundary metadata:
  - `pretrip_candidate_evidence_only: true`;
  - `runtime_safety_truth: false`;
  - `phase1_runtime_mutation_allowed: false`;
  - `raw_gpx_embedded_in_json: false`.

Normalized route summaries, route display geometry, CP candidates, segment
candidates, reference-track display geometry, and route evidence bundle must be
built from the filtered GPX outputs, not the raw GPX files. Raw GPX remains
preserved as source evidence by path/hash.

Display geometry must preserve GPX track/segment boundaries（保留航跡分段邊界）:

- `coordinates` may remain as a backward-compatible flattened display list;
- `coordinate_segments` is the authoritative map-rendering list of line parts;
- `/admin`, `/admin/pretrip`, `/admin/debug`, and post-analysis reference-track
  rendering must prefer `coordinate_segments`;
- no UI should draw a synthetic line across two GPX `<trkseg>` / `<trk>`
  boundaries unless a later reviewed route-edit explicitly connects them.

`project.json`, `import_manifest.json`, `/admin/pretrip`, `/admin`, and
`/admin/debug` projections must include filter summary counts and references,
but must not embed long `removed_points` or `exempted_points` lists outside the
filter report.

## GPX Note Extraction

The importer should extract text from:

- waypoint `name`;
- waypoint `cmt`;
- waypoint `desc`;
- route point / track point extension notes when available;
- track names and segment names;
- timestamps when present.

Each note candidate must include:

- source GPX ref;
- source role;
- original text;
- normalized Traditional Chinese text when possible;
- coordinate or nearest route distance;
- note timestamp when available;
- freshness / stale flag;
- semantic aggregation key when deterministic rules can infer one;
- candidate-only boundary fields.

Example:

```json
{
  "candidate_id": "gpx_route_note.001",
  "source_kind": "gpx_route_note",
  "source_role": "reference_track",
  "text": "大崩壁，高繞",
  "lat": 23.98,
  "lon": 121.22,
  "nearest_golden_route_distance_m": 8120,
  "semantic_hints": ["collapse_hazard", "technical_detour"],
  "old_route_note_flag": false,
  "candidate_only": true,
  "runtime_safety_truth": false
}
```

Pydantic AI may classify these notes in a later pipeline stage, but the importer
must already preserve enough context for that judgement. The importer should
not require live model calls to complete.

## Admin Projection Requirements

The importer must provide all current admin surfaces with read-only projection
data:

- `/admin/pretrip`: project workspace, route layers, candidates, import status;
- `/admin`: after-action-style preview of route evidence, not a completed
  mission replay;
- `/admin/debug`: JSONL import pipeline events through debug projection.

Projection events must describe import steps, not runtime events:

```json
{
  "event_kind": "pretrip_import_projection",
  "project_id": "nenggao_andongjun_alpha",
  "stage": "route_evidence_bundle_written",
  "candidate_only": true,
  "phase1_runtime_mutation_allowed": false
}
```

## Project Structure

Current implementation files:

```text
pretrip_import.py
  CLI and orchestration.

pretrip_gpx_corpus.py
  GPX corpus scanning and source roles.

pretrip_candidate_generation.py
  Initial CP/segment candidate generation.

pretrip_route_note_candidates.py
  GPX note candidate extraction.

pretrip_route_note_ln_proposals.py
  Candidate-only Ln proposal projection from route notes.
```

Suggested additions:

```text
pretrip_historical_gpx_importer.py
  Historical/open-download GPX source indexing and route evidence bundle writer.

tests/test_pretrip_historical_gpx_importer.py
  Fixture-backed tests for source attribution, route roles, notes, and bundle output.
```

## Testing Strategy

Fixture-backed tests only. No live network.

Test cases:

- one golden GPX plus many reference GPX files;
- duplicate reference track detection by hash;
- source URL/provider metadata preservation when supplied;
- GPX waypoint `name`/`cmt`/`desc` extraction;
- stale route-note flag when timestamp exceeds freshness policy;
- semantically different nearby notes remain separate;
- absolute-speed outliers are removed and reported;
- relative-speed spikes are removed and reported;
- long-distance gaps are preserved and marked as resume segments;
- route-note protected outliers are retained and reported as exemptions;
- low-speed dense clusters produce rest/camp checkpoint candidates;
- route evidence bundle contains bbox and along-track corridor policy;
- raw GPX XML is not embedded in normalized JSON;
- admin/debug projections are read-only and boundary-tagged;
- `pi-offline` records `network_calls_allowed: false`;
- Dashboard clone rejects an existing target and never mutates the source;
- missing active-interpreter Python `osmium` blocks before importer invocation
  and leaves no target directory;
- a configured local PBF is forwarded into the same preparation request;
- additional material-corpus GPX files are hash-deduplicated;
- a discontinuous or wrongly ordered multi-track golden route cannot silently
  become ordinary connected segments;
- preparation failure is recorded as incomplete and is never projected as a
  successful clone;
- the successful clone receipt proves one import plus one preparation run,
  without a manual repair or `_v2` target.

Suggested command:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest -q \
  tests/test_pretrip_import.py \
  tests/test_pretrip_gpx_corpus.py \
  tests/test_pretrip_route_note_candidates.py \
  tests/test_pretrip_historical_gpx_importer.py
```

## Boundaries

Always:

- preserve raw source path/hash and source role;
- distinguish golden route, reference tracks, and manual waypoint routes;
- preserve note freshness and source attribution;
- apply the five GPX filter mechanisms before route summary, CP/segment
  generation, and map-preparation handoff;
- emit `route_evidence_bundle.json` for map preparation;
- keep outputs candidate-only and review-gated;
- treat Dashboard Clone as one import-plus-preparation operation and keep its
  source workspace read-only;
- preflight all discoverable material/tool failures before target creation;
- regenerate all route-dependent outputs when golden route identity changes.

Ask first:

- browser file upload;
- crawling route-sharing sites;
- publishing or redistributing raw GPX;
- live Pydantic AI model calls inside the importer;
- changing final `MissionGraph` generation behavior.

Never:

- call `/safety/*`;
- mutate Phase 1 runtime state;
- write Phase 2 Brain facts;
- compile final `MissionGraph`;
- treat historical GPX as actual current-user walked truth;
- hide route sections that have no historical support;
- embed raw GPX XML in Scout normalized artifacts;
- copy another route's CP, ridge/valley, timing, Navigation, risk, or
  Architecture artifacts to manufacture feature parity;
- present an import-only or post-repaired partial target as a successful clone;
- require a second `_v2` workspace to finish the normal user flow.

## Success Criteria

- A local historical/open-download GPX corpus can produce a Scout pretrip
  workspace.
- The output explicitly identifies one golden route and many reference tracks.
- Route notes are extracted with source attribution, freshness, and candidate
  boundaries.
- `route_evidence_bundle.json` gives map preparation a bbox and along-track
  corridor policy.
- `/admin/pretrip`, `/admin`, and `/admin/debug` can read projection artifacts.
- Focused tests pass without network.
- The Dashboard Workspace Clone user flow creates a new target without
  overwriting the source and completes importer plus preparation in one
  operation.
- All discoverable parser/material failures stop before target creation.
- The successful receipt and live workspace prove that no manual post-import
  repair or `_v2` replacement was required.

## Open Questions

- Should the default stale threshold for route notes be 2 years, 3 years, or
  route-category specific?
- Should source URL/license metadata be required for public sharing, but
  optional for private local planning?
- Should duplicate routes be detected only by file hash or also by geometry
  similarity?
- Should route evidence bundle include simplified geometry only, or both
  simplified and full-resolution geometry refs?
