# Spec: Pretrip Historical GPX Importer

Date: 2026-06-02

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

## Role In The Pipeline

The importer must run before route-corridor map preparation:

```text
historical/open-download GPX corpus
  -> Historical GPX Importer
  -> route evidence bundle
  -> Route-Corridor Map Preparation
  -> OSM/GIS/web/raster along-track evidence
  -> Pydantic AI semantic judgement
  -> candidate CP / Ln / POI / detour review items
```

The route evidence bundle is the source of truth for map preparation scope. Map
preparation must not perform route-independent OSM/GIS/web searches for this
project when a valid importer route bundle exists.

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
  --max-reasonable-gpx-speed-kmh 120
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
  --max-reasonable-gpx-speed-kmh 120
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

## Five GPX Filter Mechanisms

The importer must run the **five GPX filter mechanisms**（GPX 五大過濾/診斷機制）
before route summaries, CP generation, segment generation, reference display
geometry, and map-preparation handoff are produced.

These filters are planning-data hygiene, not runtime truth. They protect the
pretrip workspace from obvious GPS artifacts while preserving evidence that may
carry human meaning.

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
max_previous_speed_ratio = 3.0
```

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
- `pi-offline` records `network_calls_allowed: false`.

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
- keep outputs candidate-only and review-gated.

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
- embed raw GPX XML in Scout normalized artifacts.

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

## Open Questions

- Should the default stale threshold for route notes be 2 years, 3 years, or
  route-category specific?
- Should source URL/license metadata be required for public sharing, but
  optional for private local planning?
- Should duplicate routes be detected only by file hash or also by geometry
  similarity?
- Should route evidence bundle include simplified geometry only, or both
  simplified and full-resolution geometry refs?
