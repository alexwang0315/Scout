# Spec: Scout Workspace Layout

Status: Draft

Date: 2026-06-25

## Objective

Define the canonical Scout workspace layout used by pretrip planning,
on-trip records, post-analysis, Scout AI tools, and official workspace
transfer.

The workspace is the portable, auditable unit of Scout outdoor intelligence. It
must preserve enough source material, normalized evidence, review decisions,
AI-generated candidates, and runtime handoff metadata to rebuild a trip plan on
another Scout host without mixing planning evidence with runtime safety truth.

This spec consolidates the directory expectations currently spread across:

- `docs/specs/pre-trip-planning-admin.md`;
- `docs/specs/pretrip-layer-preparation.md`;
- `docs/specs/pretrip-route-corridor-map-preparation.md`;
- `docs/specs/scout-closed-loop-operating-cycle.md`;
- `docs/specs/scout-ai-workspace-agent-tool-spec.md`;
- `docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`.

## Core Boundaries

1. A workspace stores evidence, candidates, reviews, generated artifacts, and
   transfer metadata.
2. Pretrip outputs are candidate or reviewed planning evidence. They are not
   Phase 1 runtime safety truth.
3. On-trip runtime records may be imported into a completed-trip workspace, but
   post-analysis must not rewrite the original pretrip candidates in place.
4. Scout AI may read, retrieve, synthesize, and propose. It must not silently
   install generated code, mutate runtime safety state, or promote model output
   to truth without deterministic validation and review.
5. Raw private material such as exact user tracks, wearable payloads, private
   timestamps, and hardware logs may live in local workspace roots, but official
   transfer packages must redact or coarsen them by default.

## Root Model

Production Scout hosts should use configurable roots. The examples below show
the intended Pi layout; development and tests may point the same environment
variables to `/tmp` or another local directory.

```text
/data/scout/
  materials/
    pretrip/{project_id}/
  pretrip/
    workspaces/{project_id}/
  runtime/
    sessions/{session_id}/
  completed_trips/
    {trip_id}/
  black-box/
    session_exports/{session_id}/
  exports/
    workspace_templates/{template_id}/
    ecosystem_contributions/{contribution_id}/
  raster-sources/
    {project_id}/
  caches/
    overpass/
    osm_pbf/
    weather/
    map_tiles/
```

Recommended environment variables:

```text
SCOUT_DATA_ROOT=/data/scout
SCOUT_MATERIAL_ROOT=/data/scout/materials
SCOUT_PRETRIP_WORKSPACE_ROOT=/data/scout/pretrip/workspaces
SCOUT_RUNTIME_SESSION_ROOT=/data/scout/runtime/sessions
SCOUT_COMPLETED_TRIP_ROOT=/data/scout/completed_trips
SCOUT_BLACK_BOX_EXPORT_ROOT=/data/scout/black-box/session_exports
SCOUT_EXPORT_ROOT=/data/scout/exports
SCOUT_RASTER_SOURCE_ROOT=/data/scout/raster-sources
SCOUT_OSM_PBF_CACHE_ROOT=/data/scout/caches/osm_pbf
```

## Material Source Bundle

The material source bundle is the rebuildable input layer. It stores user,
operator, or crawler-provided source material before Scout converts it into a
project workspace.

```text
materials/pretrip/{project_id}/
  material_manifest.json
  gpx/
    golden/
    reference/
    historical/
  maps/
    imagery/
    offline_tiles/
    map_images/
    ocr_inputs/
  terrain/
    dem/
    dtm/
    contours/
  documents/
    articles/
    webpages/
    route_guides/
    conversations/
  weather/
    forecast_snapshots/
    daylight_tables/
  health/
    wearable_exports/
    activity_exports/
  scout_templates/
    {template_id}/
  ai_inputs/
    prompts/
    retrieval_notes/
```

Rules:

- `material_manifest.json` records source paths, checksums, source type,
  retrieval/import time, license, provider, and privacy class.
- Bulk sources stay here or in `raster-sources/`; repo fixtures should keep only
  reduced synthetic or summary material.
- Connected preparation may fetch Overpass, weather, or web evidence into this
  source bundle or a cache, then copy only normalized refs into the workspace.

## Active Pretrip Workspace

The active pretrip workspace is the primary planning unit rendered by
`/admin/pretrip`, `/admin/debug`, `/admin`, and the Emergency Mobile Approval
UI v0.

```text
pretrip/workspaces/{project_id}/
  project.json
  cache/
    cwa-weather-imagery/
  inbox/
    source_manifest.json
    gpx/
    geojson/
    articles/
    webpages/
    images/
    conversations/
    field_exports/
    sensor_exports/
    scout_templates/
  sources/
    historical_gpx_source_index.json
    material_source_index.json
    template_source_index.json
    osm_pbf_source_index.json
  normalized/
    routes/
    map/
    notes/
    terrain/
    weather/
    sensors/
    vitals/
    context/
      route_context/
        route_context_evidence.json
        route_context_pack.json
        media_manifest.json
        source_manifest.json
        crawl_seed_plan.json
    pace/
    permissions/
    architecture/
    navigation/
    templates/
  candidates/
    checkpoints.json
    segments.json
    pois.json
    hazards.json
    route_notes.json
    map_candidates.json
    overpass_evidence.json
    retreat_routes.json
    route_guide_timing.json
    skill_config_manifest.json
    route_context_points.json
    route_mileage_k_anchors.json
    pace_fit_candidates.json
    contextual_permission_rules.json
    route_architecture_candidates.json
    weather_decision_candidates.json
    navigation_terrain_candidates.json
  reviews/
    human_reviews.json
    review_decision_log.json
    review_draft_log.json
    workspace_edit_log.json
    spatial_imprint_reviews.json
    ai_asset_install_decisions.jsonl
  outputs/
    import_manifest.json
    pretrip_package.json
    pretrip_package.reviewed.json
    compiled_mission_graph.candidate.json
    compiled_mission_graph.reviewed.json
    departure_bundle_manifest.json
    runtime_handoff_metadata.candidate.json
    runtime_audit_manifest.json
    admin_projection.json
    debug_projection_events.jsonl
    layers/
      raster_label_ocr_output.json
      normalized/
        raster_label_evidence.geojson
    risk/
    mcp/
    spatial_imprint_manifest.json
    spatial_imprint_set.json
    resource_plan.json
    planned_eta.json
    timing_measurements.json
    weather_daylight_evidence.json
    boss_points.json
    boss_points.geojson
    route_pressure_profile.json
    route_pressure_profile.geojson
    mileage_tag_alignment.json
    mileage_tag_alignment.geojson
    readiness_report.json
    brain_seed_nodes.json
    briefings/
      route_context_briefing.html
    environment/
      cwa/
      gee/
      derived/
  ai/
    candidates/
    approved/
    runs/
    registry/
    traces/
```

`cache/cwa-weather-imagery/` is project-local raw/provider cache state. The
preparation worker and cache-only Admin imagery endpoints must derive this
path from the validated project root; they must not select it from a global
cache environment variable. Its frame retention, pruning, server-job lock,
and relative asset refs are isolated from every other project workspace.
Canonical compact CWA evidence remains under `outputs/environment/cwa/`.

`project.json` is the anchor manifest. It should expose project-relative refs
for canonical artifacts, schema versions, source provenance, candidate counts,
review status, layer readiness, AI asset status, and boundary metadata such as:

```json
{
  "project_id": "chilai_nanhua_day1",
  "schema_version": "scout.workspace.v1",
  "workspace_kind": "pretrip",
  "runtime_safety_truth": false,
  "phase1_runtime_mutation_allowed": false,
  "phase2_brain_writeback_allowed": false
}
```

As the workspace evolves, `project.json` may also expose optional refs for
route-context, mileage, raster OCR, local OSM PBF extracts, and environment
evidence. Current examples include:

```json
{
  "route_context_points_ref": "candidates/route_context_points.json",
  "route_mileage_k_anchors_ref": "candidates/route_mileage_k_anchors.json",
  "mileage_tag_alignment_ref": "outputs/mileage_tag_alignment.json",
  "mileage_tag_alignment_geojson_ref": "outputs/mileage_tag_alignment.geojson",
  "reference_pace_energy_analysis_ref": "outputs/reference_pace_energy_analysis.json",
  "reference_pace_energy_map_geojson_ref": "outputs/reference_pace_energy_map.geojson",
  "architecture_preparation_manifest_ref": "outputs/architecture_preparation_manifest.json",
  "architecture_preparation_status": "ready",
  "architecture_preparation_stage": "enriched",
  "raster_label_ocr_output_ref": "outputs/layers/raster_label_ocr_output.json",
  "raster_label_evidence_ref": "outputs/layers/normalized/raster_label_evidence.geojson",
  "osm_pbf_source_ref": "/data/scout/caches/osm_pbf/taiwan-latest.osm.pbf",
  "osm_pbf_source_url": "http://download.geofabrik.de/asia/taiwan-latest.osm.pbf",
  "osm_pbf_cache_status": "fresh",
  "osm_pbf_render_extract_ref": "normalized/map/osm_pbf_route_bbox.osm.pbf",
  "osm_pbf_render_extract_manifest_ref": "normalized/map/osm_pbf_render_extract_manifest.json",
  "osm_pbf_render_extract_source_kind": "local_osm_pbf_route_bbox_extract",
  "osm_pbf_render_extract_feature_count": 295,
  "route_context_briefing_ref": "outputs/briefings/route_context_briefing.html"
}
```

Consumers should prefer these refs over hardcoded paths, tolerate missing
optional refs, and avoid embedding large OCR, mileage alignment, OSM JSON, or
PBF payloads in admin or AI responses.

Route Architecture has a two-stage preparation contract. `core` uses the
historical GPX source index and primary/golden filtered route geometry;
`enriched` additionally uses risk-score points and route-pressure terrain
samples. `outputs/architecture_preparation_manifest.json` records the input
fingerprint, freshness, browseability, stage, aggregate counts, privacy, and
candidate-only boundary. `project.json` mirrors only refs, readiness fields,
and aggregate counts; it must not embed raw GPX or precise activity timestamps.

### Emergency Approval Workspace Consumption

Emergency Mobile Approval UI v0 reads the same active pretrip workspace
resources as `/admin/pretrip`, `/admin/debug`, and `/admin`. It is a
field-oriented approval surface, not a new workspace format.

Workspace resources are engineering/audit evidence in this surface. They should
be available through bottom evidence frame tabs together with the emergency
package draft and approval artifact, not placed before production path state,
decision controls, callout controls, or offline map review.

Required read-only GET resources:

```text
/admin/pretrip/projects/{project_id}?compact=1
/admin/pretrip/projects/{project_id}/admin-projection
/admin/pretrip/projects/{project_id}/debug-projection
/admin/pretrip/projects/{project_id}/debug-projection-events
```

The UI must treat `project.json` as the anchor through those projections and
must preserve these project-relative refs in any local approval/callout
artifact:

- `project.json`;
- `outputs/admin_projection.json`;
- `outputs/debug_projection_events.jsonl`;
- canonical `outputs/*`, `reviews/*`, `candidates/*`, `normalized/*`, and
  `sources/*` refs surfaced by the compact project view;
- layer refs exposed by the shared `map_layers` contract.

Emergency UI resource rules:

- use read-only GET only;
- do not POST workspace edits, review decisions, or transport approvals;
- do not call `/safety/*`;
- do not mutate Phase 1 runtime safety truth;
- do not mark outbound delivery as successful without verified transport
  receipts from the production transport layer;
- keep the offline map layer toggles bound to shared workspace map layers:
  cached Rudy+TW, cached imagery, Overpass, reference segments, CP/MCP, route
  notes, and terrain.

## Outdoor AI Agent Data Placement

`SCOUT_OUTDOOR_AI_AGENT_STANDARD` sections 6-11 require specific data families.
They should be placed as follows.

| Standard section                          | Required data                                                                                                 | Canonical workspace refs                                                                                                                                                                                                                            | Boundary                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Sec. 6 Route Context Intelligence         | historical, cultural, natural, seasonal, observation-point, named-point, article, OCR, mileage tag, and map-label evidence | `normalized/context/route_context/*.json`, `candidates/route_context_points.json`, `candidates/route_mileage_k_anchors.json`, `outputs/mileage_tag_alignment.json`, `outputs/mileage_tag_alignment.geojson`, `outputs/briefings/route_context_briefing.html`, `outputs/mcp/named_point_evidence.json`, `outputs/layers/normalized/web_case_evidence.json`, `outputs/layers/normalized/raster_label_evidence.geojson`, `outputs/layers/raster_label_ocr_output.json` | Candidate evidence until reviewed                                                |
| Sec. 7 Readiness & Pace Fit               | pace coefficient, team pace fit, energy reserve, segment timing, daylight, workload estimates, route boss demand, challenge fit | `normalized/pace/pace_coefficients.json`, `normalized/pace/team_pace_fit.json`, `outputs/boss_points.json`, `outputs/boss_points.geojson`, `outputs/resource_plan.json`, `outputs/planned_eta.json`, `outputs/timing_measurements.json`, `outputs/weather_daylight_evidence.json`, post-analysis imported refs | Advisory planning evidence, not medical diagnosis or runtime safety truth        |
| Sec. 8 Contextual Permissioning           | permission rules, buffer budgets, stop/go constraints, CP progress requirements, decision traces              | `normalized/permissions/contextual_permission_model.json`, `candidates/contextual_permission_rules.json`, `outputs/compiled_mission_graph.*.json`, on-trip `runtime/sessions/{session_id}/contextual_permission_events.jsonl`                       | Pretrip rules are candidates; live actions require runtime authority             |
| Sec. 9 Route Architecture Intelligence    | checkpoint graph, route type, hard sections, retreat points, alternatives, route dependency analysis          | `normalized/architecture/route_architecture.json`, `candidates/retreat_routes.json`, `candidates/segments.json`, `outputs/segment_policy_candidates.json`, `outputs/compiled_mission_graph.*.json`                                                  | Reviewed plan can feed runtime handoff                                           |
| Sec. 10 Weather-to-Decision Intelligence  | forecast snapshots, weather windows, daylight, stale-source status, route-specific weather impacts, hydrologic background | `normalized/weather/forecast_snapshots.jsonl`, `normalized/weather/weather_source_manifest.json`, `outputs/weather_daylight_evidence.json`, `outputs/environment/cwa/*.json`, `outputs/environment/gee/*.json`, `outputs/environment/derived/*.json`, `candidates/weather_decision_candidates.json` | Time-limited advisory evidence with TTL                                          |
| Sec. 11 Navigation & Terrain Intelligence | offline map readiness, DEM/DTM, contours, slope/elevation, risk heat, terrain visualization, INS/DR readiness, raster OCR labels | `normalized/terrain/*`, `outputs/layers/normalized/terrain_*.png`, `outputs/layers/normalized/terrain_contours.geojson`, `outputs/layers/normalized/raster_label_evidence.geojson`, `outputs/layers/raster_label_ocr_output.json`, `outputs/risk/*`, `normalized/navigation/offline_map_manifest.json`, `normalized/navigation/ins_dr_readiness.json` | Terrain and risk layers are pretrip evidence; runtime navigation needs admission |

## Workspace-Scoped Scout AI Assets

Workspace-specific Scout AI generated skills, tools, and workflows must live
inside the workspace. They must not be copied into global repo directories or
loaded as permanent capabilities unless the capability registry and permission
gate approve them.

```text
ai/
  registry/
    workspace_tool_registry.json
    workspace_skill_registry.json
    workspace_workflow_registry.json
  candidates/
    skills/{skill_id}/
      skill_manifest.json
      prompts/
      schemas/
      examples/
      tests/
      sandbox_result.json
      provenance.json
    tools/{tool_id}/
      tool_manifest.json
      input_schema.json
      output_schema.json
      implementation/
      tests/
      sandbox_result.json
      security_review.json
      provenance.json
    workflows/{workflow_id}/
      workflow_spec.json
      execution_plan.json
      permission_request.json
      provenance.json
  approved/
    skills/{skill_id}/
    tools/{tool_id}/
    workflows/{workflow_id}/
  runs/
    model_interpretations.jsonl
    skill_runs.jsonl
    tool_invocations.jsonl
    workflow_runs.jsonl
  traces/
    {run_id}.json
```

Rules:

- `ai/candidates/**` is inert evidence. It may contain generated code but must
  not be imported or executed directly.
- Promotion from `ai/candidates/**` to `ai/approved/**` requires sandbox
  success, static checks, permission-gate decision, and a review record in
  `reviews/ai_asset_install_decisions.jsonl`.
- Approved workspace AI assets are scoped to this workspace by default. Export
  packages may include them only with policy metadata and without secrets.
- Every Scout AI answer or tool plan that uses workspace-local assets must write
  a run record under `ai/runs/` with input refs, output refs, model/provider
  metadata, boundary flags, and limitations.

## On-Trip Runtime Session Workspace

Runtime sessions are separate from pretrip workspaces. They record what happened
in the field and may later be imported into a completed-trip workspace.

```text
runtime/sessions/{session_id}/
  session_manifest.json
  plan_refs/
    pretrip_package_ref.json
    mission_graph_ref.json
  events/
    event_index.jsonl
    plan_node_events.jsonl
    checkpoint_events.jsonl
    route_note_events.jsonl
    contextual_permission_events.jsonl
    scout_action_events.jsonl
    user_trigger_events.jsonl
  team/
    team_status_events.jsonl
    team_checkin_events.jsonl
    team_beacon_events.jsonl
    team_last_heard.jsonl
    team_care_events.jsonl
    group_progress_events.jsonl
  recorder/
    recorder_manifest.json
    recording_policy.json
    sequence_clock.json
    append_only_integrity_chain.jsonl
    retention_decisions.jsonl
  transports/
    ingress_evidence_index.jsonl
    egress_evidence_index.jsonl
    wan_mqtt_ingress_index.jsonl
    cellular_ingress_index.jsonl
    lora_lorawan_ingress_index.jsonl
    bluetooth_ingress_index.jsonl
    satellite_ingress_index.jsonl
    outbound_delivery_receipts.jsonl
    raw_payload_refs/
  sensor_logs/
    journey.scout-svr/
      manifest.json
      observations.jsonl
      application_routes.jsonl
      filter_outputs.jsonl
      navigation_estimates.jsonl
      vitals.jsonl
      transport_ingress_index.jsonl
      transport_egress_index.jsonl
    sensorlogger_mqtt/
      raw_messages.jsonl
      sensor_vitals_records.jsonl
      latency.jsonl
      status.json
    imu_pdr/
      raw_imu_events.jsonl
      pdr_estimates.jsonl
      route_constrained_estimates.jsonl
  hardware/
    hardware_status_events.jsonl
    hardware_resource_access_events.jsonl
    user_hardware_trigger_events.jsonl
    gpio_events.jsonl
    i2c_events.jsonl
    i2s_events.jsonl
    uart_events.jsonl
    usb_device_events.jsonl
    battery_events.jsonl
    gps_events.jsonl
    imu_events.jsonl
    audio_tts_events.jsonl
  communications/
    communication_node_events.jsonl
    outbound_queue_events.jsonl
    delivery_receipts.jsonl
  navigation/
    raw_gps.gpx
    ins_dr_estimates.jsonl
    pdr_estimates.jsonl
    route_constrained_estimates.jsonl
  black_box/
    black_box_manifest.json
    black_box_event_index.jsonl
    black_box_heartbeat_packets.jsonl
    search_black_box_snapshots.jsonl
    segment_capsules/
    raw_ring/
    incident_packages/
```

Runtime session records may be safety-relevant. Planning tools must not mutate
them. Admin/debug may render them as read-only evidence unless an explicit
runtime authority mode is active.

### Runtime Recorder And Black-Box Requirements

The runtime session workspace is Scout's field recorder. It must be able to
explain what Scout knew, what hardware was touched, what communication paths
worked, what failed, and which user or runtime trigger caused each action.

Required recorder behavior:

- write append-only JSONL records for events, hardware access, transport
  ingress/egress, team status, sensor routing, and black-box packets;
- assign a monotonic `sequence` and stable `event_id` within the session;
- record Scout receiver timestamps and source timestamps when available;
- record `source_adapter`, `ingress_transport` or `egress_transport`,
  `device_ref`, `session_ref`, payload size, payload hash, parse status, route
  status, and raw artifact refs;
- preserve all hardware resource access attempts, including GPIO, I2C, I2S,
  UART, USB, GPS, IMU, battery, audio/TTS, and modem/radio interactions;
- preserve user-triggered hardware actions separately from autonomous/runtime
  actions through `user_hardware_trigger_events.jsonl`;
- keep raw payload values, health values, precise tracks, credentials, HMAC
  secrets, MQTT passwords, LoRaWAN session keys, and access tokens out of UI
  summaries and status JSON;
- write `append_only_integrity_chain.jsonl` so later export/import tools can
  detect missing, reordered, or rewritten recorder files;
- follow `recording_policy.json` for high-rate raw payload retention while
  keeping complete indices and hashes for every accepted or rejected transport
  event.

Transport evidence must cover:

| Transport family | Runtime refs | Required metadata |
| --- | --- | --- |
| Sensor Logger / MQTT | `transports/wan_mqtt_ingress_index.jsonl`, `sensor_logs/sensorlogger_mqtt/*` | broker class, topic, QoS, TLS status, message id, device/session refs, payload hash, latency |
| 4G / 5G / LTE internet | `transports/cellular_ingress_index.jsonl`, `communications/delivery_receipts.jsonl` | modem/interface ref, network class, signal summary, IP route status, delivery state |
| LoRa / LoRaWAN | `transports/lora_lorawan_ingress_index.jsonl`, `team/team_beacon_events.jsonl`, `black_box/black_box_heartbeat_packets.jsonl` | gateway id, region/band, RSSI, SNR, spreading factor, packet counter, last-heard refs |
| Bluetooth / BLE | `transports/bluetooth_ingress_index.jsonl` | service/characteristic refs, bridge device, RSSI, pairing state |
| Satellite or later NTN | `transports/satellite_ingress_index.jsonl` | provider class, message id, delay/retry metadata, summary/full-observation class |

Team records must live under `team/`, not only under generic communications.
They include member check-ins, last-heard observations, team beacons, team-care
prompts, group progress, and communication-node status. These records may feed
admin/debug and completed-trip analysis, but they must not be published in
workspace template exports unless redaction policy explicitly allows it.

Black-box records are the minimal recovery and incident reconstruction chain.
They should reference the event index, transport indices, hardware events,
team status, latest admitted position estimates, segment capsules, raw-ring
windows, incident packages, and beacon packets. They are not a separate source
of safety decisions; they are a durable evidence package for search, recovery,
and after-action review.

### Black-Box Session Export

`black-box/session_exports/{session_id}` is a sealed, portable export of the
runtime recorder. It is for recovery, incident reconstruction, support
handoff, and post-analysis import. It is not a pretrip template package.

```text
black-box/session_exports/{session_id}/
  black_box_export_manifest.json
  redaction_policy.json
  checksums.sha256
  timeline_index.jsonl
  bundle/
    session_manifest.json
    recorder/
    events/
    team/
    transports/
    sensor_logs/
    hardware/
    communications/
    navigation/
    black_box/
```

Rules:

- emergency/support exports may include more precise data than public template
  exports, but must still declare audience, purpose, retention policy, and
  redaction policy;
- every exported file must have a checksum and source runtime-session ref;
- export tooling must preserve append-only sequence order;
- export tooling must not invent missing event records or rewrite raw evidence;
- public or community workspace templates must not embed this export by default.

## Completed Trip Workspace

A completed trip workspace is created after a trip or field replay. It supports
post-analysis, capability timeline generation, Energy Reserve feedback, and
next-pretrip candidate exports.

```text
completed_trips/{trip_id}/
  trip_manifest.json
  recorded/
    recording_set_manifest.json
    primary_user/
      *.gpx
    participants/
      {participant_id}/
        *.gpx
    notes/
    sensor_exports/
    wearable_exports/
  runtime/
    imported_session_manifest.json
    events/
    team/
    recorder/
    transports/
    sensor_logs/
    hardware/
    communications/
    navigation/
    black_box/
  normalized/
    completed_tracks/
    segment_matches/
    rests/
    terrain/
    vitals/
    pace/
  outputs/
    capability_timeline.json
    capability_segments.csv
    capability_capsule.json
    capability_route_time_comparison.json
    post_analysis_energy_reserve_feedback.json
    energy_reserve_baseline_update_candidate.json
    energy_limit_candidate.json
    after_action_next_plan_candidates.json
  reviews/
    post_analysis_review_log.json
```

Rules:

- A completed trip may contain many GPX files and many participants.
- Admin may select one active analysis target, but storage must not assume one
  trip equals one GPX.
- Public/reference/golden pretrip GPX files are not capability sources unless
  explicitly marked as user-completed tracks.

## Official Workspace Transfer

Workspace transfer is the official Scout A to Scout B portability mechanism. It
is separate from runtime handoff.

### Export Layout

```text
exports/workspace_templates/{template_id}/
  workspace_template_manifest.json
  workspace_template_package.json
  workspace_template_redaction_report.json
  workspace_template_checksums.sha256
  bundle/
    project.json
    sources/
    normalized/
    candidates/
    reviews/
    outputs/
    ai/
      approved/
      registry/
  ecosystem_contribution.candidate.json
```

### Import Layout

```text
pretrip/workspaces/{project_id}/
  inbox/
    scout_templates/{template_id}/
      workspace_template_package.json
      workspace_template_manifest.json
      workspace_template_redaction_report.json
  normalized/
    templates/{template_id}/
      imported_manifest.json
      source_refs.json
  candidates/
    template_imported_cp_candidates.json
    template_imported_scout_time_refs.json
    template_imported_route_notes.json
    template_imported_route_context.json
    template_imported_energy_hints.json
  reviews/
    template_import_review_log.json
```

Transfer rules:

- Export packages are self-describing and include schema version, source
  workspace hash, route family, exporter policy, included sections, redaction
  summary, artifact refs, review status, and import expectations.
- Scout B imports template material as candidate evidence. It must not overwrite
  local reviewed decisions.
- Raw exact tracks, wearable payloads, exact timestamps, private identities, and
  incident packages are excluded by default.
- AI assets may be exported only when they are workspace-approved and the export
  policy allows generated capability metadata/code. Imported AI assets return to
  `ai/candidates/**` unless Scout B explicitly approves them.

## Layer Preparation Placement

Map and terrain preparation writes under:

```text
outputs/layers/
  layer_preparation_manifest.json
  layer_preparation_summary.json
  map_preparation_summary.json
  plans/
  manifests/
  normalized/
  semantic/
  candidates/
  projections/
```

Local OSM PBF evidence（本地 OSM PBF 證據） has two storage levels:

1. Full-region PBF cache（全區 PBF 快取） outside the project workspace, for
   example `/data/scout/caches/osm_pbf/taiwan-latest.osm.pbf`. This file may be
   hundreds of megabytes and must not be copied into every workspace or git
   fixture. It is referenced by absolute path, hash, source URL, and cache TTL
   metadata.
2. Workspace-local route-bbox extract（工作區內路線 bbox 小切片） inside the
   selected project workspace. This is the portable rendering/evidence unit for
   the `osm` layer and downstream Overpass-compatible candidate extraction.

Canonical local OSM extract placement:

```text
pretrip/workspaces/{project_id}/
  sources/
    osm_pbf_source_index.json
  normalized/
    map/
      osm_pbf_route_bbox.osm.pbf
      osm_pbf_phase_a_raw.osm.json
      osm_pbf_render_extract_manifest.json
      overpass_vector_evidence.geojson
  candidates/
    overpass_evidence.json
```

The preferred OSM render source is
`normalized/map/osm_pbf_route_bbox.osm.pbf` when `osmium extract` can write a
small PBF. If only the Python streaming fallback is available, the render source
may be `normalized/map/osm_pbf_phase_a_raw.osm.json`. In both cases,
`osm_pbf_render_extract_manifest.json` must declare:

- `preferred_render_source_ref`;
- `preferred_render_source_kind`;
- optional `pbf_extract_ref`;
- `osmjson_extract_ref`;
- `feature_count`;
- extraction bbox/corridor plan;
- PBF cache status, TTL, source URL, and refresh recommendation;
- `candidate_only=true` and `runtime_safety_truth=false`.

The full Taiwan PBF is a cache/source artifact, not a workspace artifact. The
small extract is a workspace artifact. Admin UI and Scout AI tools should read
the small extract refs from `project.json` or map-layer metadata instead of
opening the full-region PBF during rendering.

Terrain visualization layers belong to `outputs/layers/normalized/`:

```text
terrain_hillshade.png
terrain_elevation_tint.png
terrain_slope_shading.png
terrain_contours.geojson
terrain_route_samples.geojson
terrain_visualization.geojson
```

Raster OCR and map-label evidence belongs under the layer preparation output
tree. The raw OCR output should stay bounded by refs, and the normalized
GeoJSON is the primary Scout AI query surface:

```text
outputs/layers/
  raster_label_ocr_output.json
  normalized/
    raster_label_evidence.geojson
```

Risk heat layers belong to `outputs/risk/` or explicitly named risk refs:

```text
risk_score_points.geojson
risk_ribbon.geojson
calibrated_risk_heatmap.geojson
risk_delta.geojson
risk_attribution_diagnostic.json
```

Terrain visualization is map-reading evidence. Risk heat is planning diagnostic
evidence. Neither becomes runtime safety truth without the reviewed handoff
chain.

Weather and environment preparation writes server-side evidence under:

```text
outputs/environment/
  cwa/
    cwa_weather_evidence.json
    cwa_qpf_corridor_summary.json
    cwa_qpf_route_timeline_evidence.json
  gee/
    smap_l4_timeseries.json
    smap_l4_corridor_summary.json
    soil_moisture_grid.geojson
  derived/
    compound_weather_terrain_candidates.json
```

These artifacts are pretrip candidate evidence. CWA API keys, GEE credentials,
raw authorization headers, and provider tokens must never be written to the
workspace or exposed to client-side UI.

## Validation Requirements

A workspace validator should verify:

1. `project.json` exists and declares `schema_version`, `workspace_kind`, and
   boundary flags.
2. All project-relative refs in `project.json` exist or are marked optional.
   The validator should treat new `*_ref` fields as first-class refs instead of
   requiring a fixed historical allowlist.
3. `inbox/source_manifest.json` links raw imports to checksums and privacy
   classes.
4. `sources/*_index.json` records source provenance.
5. Candidate artifacts link back to source refs and review status.
6. Layer preparation refs exist when layer readiness claims are present.
7. Scout AI generated assets under `ai/approved/**` have sandbox, permission,
   and review records.
8. Runtime session workspaces that contain field records include
   `recorder/recorder_manifest.json`, `events/event_index.jsonl`, transport
   ingress/egress indices, hardware resource-access records, team status
   records, and `black_box/black_box_manifest.json`.
9. Transport and hardware records include sequence, timestamp, source adapter or
   hardware interface, payload/hash refs when applicable, parse/action status,
   and `credential_value_exposed=false`.
10. Black-box exports include checksums, source runtime-session refs, redaction
    policy, and append-only sequence order.
11. Transfer packages include checksums, redaction reports, and import policy.
12. No pretrip artifact claims `runtime_safety_truth=true`.
13. Completed-trip workspaces do not treat public/reference GPX as user
    capability evidence unless explicitly marked.
14. Route-context, mileage, and raster OCR artifacts remain candidate-only or
    review-required unless a reviewed package explicitly promotes them.
15. Large artifacts such as `outputs/mileage_tag_alignment.json`,
    `outputs/layers/raster_label_ocr_output.json`, and provider raw-response
    caches are referenced and summarized in AI/admin outputs rather than
    embedded wholesale.
16. CWA/GEE/environment artifacts include source refs, stale-risk or timestamp
    metadata, candidate-only boundaries, and no secrets.
17. Local OSM PBF workspaces do not embed the full-region `.osm.pbf` in the
    project tree. They should reference the full PBF cache by path/hash and
    preserve only the route-bbox extract or filtered OSM JSON under
    `normalized/map/`.
18. When `osm_pbf_render_extract_ref` is present, the referenced file and
    `osm_pbf_render_extract_manifest_ref` must exist, the manifest must identify
    the preferred render source and fallback source, and the `osm` layer must
    expose matching `local_osm_render_extract_*` metadata.

## Alpha Acceptance Criteria

- Historical GPX importer writes to the active pretrip workspace and keeps raw
  sources in `inbox/` or the material bundle.
- Map preparation reads the active workspace and writes only workspace outputs.
- Route-context, mileage anchors, raster OCR labels, and environment evidence
  are discoverable through `project.json` refs and Scout AI read-only tools.
- `/admin`, `/admin/debug`, `/admin/pretrip`, and Emergency Mobile Approval UI
  v0 read the same workspace projection refs.
- Post-analysis reads completed-trip workspaces and exports next-pretrip
  candidates without rewriting the original pretrip candidates.
- Workspace template export/import can move reviewed planning evidence from one
  Scout host to another as candidate evidence.
- Workspace-specific Scout AI skills, tools, and workflows are stored under
  `ai/`, sandboxed before approval, and never loaded globally by path accident.
- Runtime recorder layout can preserve Sensor Logger/MQTT, cellular, LoRaWAN,
  Bluetooth, satellite, team, GPIO/I2C/I2S/UART/USB, IMU/PDR, and hardware
  resource-access evidence as append-only black-box records.
