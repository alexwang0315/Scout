# Pretrip Standalone Importer

## Objective

Build a **standalone importer**（獨立匯入程式） for Phase 4 pre-trip planning.
It turns a local GPX corpus into a Scout project workspace that `/admin/pretrip`
can read without requiring a browser-driven manual script.

The first supported source shape is the TWMap-style batch used for the
Nenggao-Andongjun sample:

- one **golden route**（出發前選定的主參考路線；通常是最相似的山友 GPX）;
- zero or more **reference tracks**（專家/山友參考軌跡）;
- optional project-template metadata for admin display;
- optional local-only terrain/map evidence that can be added by later slices.

Pretrip（出發前規劃）has no actual user track yet. The route used to generate CP,
segments, and display geometry is a selected reference route, not proof that the
user has already walked it. After safe return, post-analysis（行後分析）may import
the actual walked track and replace the pretrip golden route for `/admin` and
post-analysis use.

If the user plans a route section that has no prior track evidence, Scout must
represent it as manually drawn waypoint candidates. This is allowed, but it must
raise a **danger review**（危險審查） warning because the route is previously
unobserved. A fork to an unwalked side path follows the same rule.

The importer may run on a Mac/PC admin workstation or on Scout Pi. In both
places it remains a Phase 4 planning tool: it produces **candidate evidence**
（候選證據） only and must not activate Phase 1 runtime safety behavior.

## Runtime Profiles

`mac-workstation`（Mac/PC 工作站模式）

- allowed to use local desktop paths;
- allowed to process larger local evidence directories;
- suitable for interactive planning and fixture generation.

`pi-offline`（Pi 離線模式）

- reads only local files under explicit input/workspace paths;
- makes no network calls;
- avoids heavy optional dependencies;
- writes to a Scout data root such as `/data/scout/pretrip/workspaces`;
- keeps source GPX files referenced by hash/path instead of copying them into
  repo fixtures.

`pi-online-explicit`（Pi 明確連線模式）

- reserved for a later slice;
- must require an explicit flag before any Overpass, tile, or weather request;
- must enforce timeout, cache, and rate-limit policy;
- still produces planning candidates only.

## Command Contract

Initial CLI:

```bash
python -m pretrip_import \
  --project-id nenggao-andongjun \
  --golden-route-gpx /data/scout/pretrip/inbox/similar_reference_route.gpx \
  --reference-dir /data/scout/pretrip/inbox/reference_tracks \
  --workspace-root /data/scout/pretrip/workspaces \
  --profile pi-offline
```

`--primary-gpx` remains as a deprecated compatibility alias for
`--golden-route-gpx`, but new commands should use `--golden-route-gpx`.

The command writes a project directory:

```text
<workspace-root>/<project-id>/
  project.json
  candidates/
    checkpoints.json
    segments.json
    map_candidates.json
  normalized/
    routes/route_summary.json
    map/map_context.geojson
  outputs/
    pretrip_package.json
    reference_tracks.json
    reference_track_display_geometry.json
    checkpoint_events.json
    segment_display_geometry.json
    import_manifest.json
    admin_projection.json
    debug_projection_events.jsonl
```

If `--template-project-root` is supplied, the importer may first copy the
template workspace and then overwrite the route-derived artifacts. This lets
`/admin/pretrip` display the imported project before every review/weather/ETA
artifact has a dedicated generator.

## Admin Surface Projections

The importer should supply read-only projection data for all current admin
surfaces:

- `/admin/pretrip` consumes the project workspace artifacts listed above.
- `/admin` may consume `outputs/admin_projection.json` as an
  **after-action-style projection**（後分析樣式投影資料）. This is not a completed
  mission replay. It is a route/evidence preview that lets the map-first admin
  surface inspect the imported route, source hashes, and candidate counts.
- `/admin/debug` may consume `outputs/debug_projection_events.jsonl` through the
  existing file-backed debug log path. These are **debug projection events**
  （debug 投影事件） that describe the import pipeline, not live field runtime
  events.

Admin API（管理介面 API） exposure:

- `GET /admin/pretrip/projects/{project_id}/admin-projection` returns
  `outputs/admin_projection.json` when the workspace has one.
- `GET /admin/pretrip/projects/{project_id}/debug-projection-events` returns a
  parsed summary of `outputs/debug_projection_events.jsonl`.
- `POST /admin/pretrip/projects/{project_id}/import-gpx-preview` validates a
  local **Import GPX**（匯入 GPX） request and returns a no-write preview of the
  selected golden route, reference tracks, output workspace, and safety
  boundary.
- `POST /admin/pretrip/projects/{project_id}/import-gpx` runs the standalone
  importer only after an explicit confirmation flag. This writes a local
  project workspace and refreshes `/admin/pretrip`, `/admin`, and `/admin/debug`
  projection artifacts, but still makes no `/safety/*` calls.
- A Pi admin runtime can point `SCOUT_DEBUG_LOG_PATH` at
  `outputs/debug_projection_events.jsonl` so `/admin/debug` renders the same
  events through the existing read-only debug API.

These projections must carry boundary metadata:

- `projection_only: true`;
- `phase1_runtime_mutation_allowed: false`;
- `phase2_brain_writeback_allowed: false`;
- `incident_store_mutation_allowed: false`;
- `real_outbound_transport_allowed: false`;
- `mission_graph_compiled: false`.

## Import GPX Admin Panel

The `/admin/pretrip` **Import GPX panel**（GPX 匯入面板） is the first UI entry
point for this importer. It should be a dedicated right-frame tab/panel rather
than a compressed toolbar prompt because the parameters are operationally
important:

- golden route GPX path;
- reference GPX directory and optional individual reference paths;
- workspace root;
- optional template project root;
- checkpoint spacing;
- maximum reference display points;
- overwrite confirmation.

The first UI slice uses server-side local paths, not browser file upload. This
keeps the same contract usable on Scout Pi and avoids hiding large file
processing behind the browser. Preview is read-only; run requires explicit
confirmation and writes only under the selected workspace root.

The panel must state the pretrip meaning clearly: the golden route is a selected
similar route for planning, not the user's actual walked route. The actual
walked track belongs to post-analysis after the trip returns safely.

## Data Treatment

The importer must preserve:

- source path and SHA-256 hash;
- source size;
- import timestamp;
- importer version;
- golden-route/reference role;
- generated artifact paths;
- candidate counts;
- profile and network policy.

The importer must not:

- write to `/safety/*`;
- compile a final `MissionGraph`;
- mutate Phase 1 runtime state;
- write Phase 2 Brain facts;
- embed raw GPX XML in normalized JSON outputs;
- require live network in `pi-offline`.

## Project Structure

Implementation files:

- `pretrip_import.py` - CLI entry point and import orchestration;
- `tests/test_pretrip_import.py` - fixture-backed importer tests;
- existing helper modules stay reusable:
  - `pretrip_source_ingest.py`;
  - `pretrip_candidate_generation.py`;
  - `pretrip_gpx_corpus.py`;
  - `pretrip_geojson_import.py`.

## Testing Strategy

Tests must use small generated GPX fixtures, not live network. They should
verify:

- CLI/core output is deterministic;
- primary and reference GPX files are separated correctly;
- route summary, CP, segment, event, and display-geometry artifacts are written;
- `project.json` points at the generated artifacts;
- `pi-offline` records `network_calls_allowed: false`;
- raw GPX XML is not embedded in JSON outputs;
- pretrip output records `actual_user_track_available: false`;
- unwalked route sections record the manual-waypoint + danger-review policy;
- a template workspace can be copied without mutating the source template.
- admin/debug projection artifacts are emitted and remain read-only.

## Success Criteria

- `python -m pretrip_import --help` works.
- A fixture GPX corpus can produce a standalone project workspace.
- The generated workspace includes route-derived artifacts needed by
  `/admin/pretrip`.
- The generated workspace includes read-only projection artifacts for `/admin`
  and `/admin/debug`.
- Focused tests pass without network.
- The implementation remains safe to run on Pi as an offline workspace writer,
  not as a field safety runtime.
