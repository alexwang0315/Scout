# Spec: Scout Spatial Imprint

## Status

Draft for the next alpha branch.

`Spatial Imprint`（空間印記）replaces the narrower "LBS geostamp" framing.
Scout needs a triggerable spatial annotation system that is not limited to flat
GPS geofencing. A spatial imprint can be planted before departure or during a
mission, and can later trigger a local cue for registered Scout clients when
their position, route progress, altitude, heading, sensor state, CP state, or
risk-layer context matches the imprint conditions.

Chinese annotation / 中文註釋: `Spatial Imprint` 是「空間印記」，不是單純的
GPS 點位提示。它可以依據位置、高度、方向、路線進度、CP、風險區、地磁、氣壓、
IMU/PDR 狀態等條件觸發語音或提示。

## Assumptions

- Scout clients are registered to a Scout machine or trip party before they can
  receive imprints.
- The first alpha implementation can be fixture-backed and simulator-driven.
- Voice cue delivery reuses the existing `VoiceCue` contract.
- GPS alone is insufficient; route-progress and sensor-assisted predicates are
  first-class concepts.
- Runtime-triggered imprints are advisory awareness cues, not Phase 1 safety
  state mutations.
- Permanent imprints are allowed by the product model, but the first alpha slice
  can keep them trip-local until admin deletion.

## Objective

Build a Spatial Imprint system for Scout that lets leaders, operators, pretrip
reviewers, or authorized Scout Agent tools plant location/context-aware cues.

Core scenarios:

- A pretrip reviewer plants a warning 50m before a major collapse wall.
- A route note produces a reviewed imprint before a confusing turn or
  non-obvious side trail.
- A leader plants a temporary rest-location imprint during the mission, so
  stretched-out team members hear the cue before arrival.
- A risk-score or terrain layer plants a caution cue when entering a high-risk
  segment.
- A sensor condition, such as altitude range plus heading, disambiguates a
  trigger where GPS alone is unreliable.

Success means Scout can:

- store reviewed spatial imprints in the pretrip/departure package;
- create temporary runtime imprints during a mission;
- evaluate deterministic trigger predicates from client context;
- queue a local voice/UI cue with suppression and receipt tracking;
- show planted and triggered imprints in `/admin/pretrip` and `/admin/debug`;
- keep every trigger auditable without turning model text into runtime safety
  truth.

## Relationship To Existing Specs

- `docs/specs/pre-trip-planning-admin.md` owns pretrip project workspaces,
  candidate evidence, review, and package preparation.
- `docs/specs/phase-4-5-departure-runtime-handoff.md` owns reviewed package,
  departure gate, final MissionGraph, runtime handoff, and runtime activation
  boundaries.
- `docs/specs/scout-voice-cue-layer.md` owns the local voice cue contract and
  playback boundary.
- `docs/specs/scout-agent-tools-cli.md` owns how Pydantic AI may call Scout
  tools to plant, review, dry-run, or expire imprints.
- Phase 1 remains the deterministic safety runtime. Spatial imprint triggers
  may use Phase 1 route-progress state as read-only context, but they must not
  mutate L0-L4 safety state or call live `/safety/*` mutation endpoints.

## Non-Goals

This spec does not:

- make imprints Phase 1 checkpoint truth;
- replace CP arrival, segment capsule sealing, or MissionGraph progress;
- make a model decide runtime trigger truth;
- require live network access;
- require a phone app implementation in the first slice;
- send SOS/SMS/satellite messages;
- control hardware beyond the existing voice/audio cue path;
- solve high-precision localization by GPS alone.

## Product Semantics

### Spatial Imprint Versus CP

| Concept | 中文說明 | Primary role | Runtime meaning |
| --- | --- | --- | --- |
| `CP` | 檢查點 | route structure, progress, check-in, segment boundary | mission progress truth |
| `SCP` | 語意/特殊檢查點 | reviewed planning candidate or route-note-derived point | planning/runtime cue reference after review |
| `Spatial Imprint` | 空間印記 | cue, guidance, warning, note, or temporary team coordination marker | awareness trigger only |
| `Risk Zone` | 風險區 | terrain/risk evidence layer | trigger context, not standalone safety truth |

Spatial imprints can reference CP/SCP/segments/risk zones, but they do not
become those objects.

### Planting Sources

| Source | 中文說明 | Example | Review requirement |
| --- | --- | --- | --- |
| `pretrip_reviewed` | 出發前審核種植 | collapse wall, confusing turn, water point | human or profile-dependent review |
| `agent_proposed` | AI/Agent 提案 | AI proposes a warning from route notes | human review before package use |
| `operator_runtime` | 任務中操作者種植 | leader adds rest-point cue | explicit operator/user action |
| `user_runtime` | 使用者臨時種植 | user adds "wait here" note | trip policy decides audience |
| `system_candidate` | 系統候選 | risk score high zone suggests caution | review before persistent package use |

### Lifecycle

| Lifecycle | 中文說明 | Behavior |
| --- | --- | --- |
| `trip_scoped` | 本次行程有效 | expires when trip package closes unless preserved |
| `ttl_scoped` | 有期限 | expires at `expires_at` or after `ttl_seconds` |
| `admin_persistent` | 管理者保留 | remains until admin deletion |
| `disabled` | 停用 | retained for audit but does not trigger |
| `deleted_tombstone` | 刪除墓碑 | no trigger; keeps deletion audit |

Permanent imprints should not be physically removed without a tombstone. They
should become inactive and traceable.

## Data Model

### SpatialImprint

```json
{
  "imprint_id": "spatial_imprint.chilai_nanhua_day1.00042",
  "schema_version": "0.1.0",
  "label": "前方大崩壁",
  "kind": "route_warning",
  "severity": "warning",
  "planting_source": "pretrip_reviewed",
  "created_at": "2026-05-26T12:00:00+08:00",
  "created_by": {
    "actor_type": "operator",
    "actor_ref": "trip_leader"
  },
  "anchor": {
    "anchor_type": "route_progress",
    "route_id": "chilai_nanhua_day1",
    "segment_ref": "segment_017",
    "cp_ref": "cp_018",
    "distance_m": 8420.0,
    "trigger_before_m": 50.0,
    "coordinate": {
      "lat": 24.0301,
      "lon": 121.2842,
      "altitude_m": 2890.0,
      "vertical_accuracy_m": 20.0
    }
  },
  "trigger": {
    "operator": "all",
    "predicates": [
      {
        "type": "route_progress_window",
        "start_distance_m": 8370.0,
        "end_distance_m": 8420.0
      },
      {
        "type": "horizontal_radius",
        "lat": 24.0301,
        "lon": 121.2842,
        "radius_m": 45.0
      },
      {
        "type": "altitude_range",
        "min_m": 2860.0,
        "max_m": 2920.0
      },
      {
        "type": "heading_sector",
        "center_degrees": 315.0,
        "half_width_degrees": 60.0
      }
    ],
    "confidence_policy": {
      "min_position_confidence": 0.45,
      "allow_sensor_degraded": true,
      "reason_if_degraded": "GPS may be weak; route progress and altitude can still match."
    }
  },
  "payload": {
    "payload_type": "voice_cue",
    "text_zh": "前方約五十公尺有大崩壁，請靠內側通行並縮短隊伍間距。",
    "voice_priority": "warning",
    "voice_category": "environment",
    "source_kind": "deterministic_fact"
  },
  "audience": {
    "scope": "registered_trip_clients",
    "client_group_refs": ["current_trip_party"],
    "exclude_actor_refs": []
  },
  "lifecycle": {
    "state": "active",
    "scope": "trip_scoped",
    "ttl_seconds": null,
    "expires_at": null,
    "delete_requires_admin": true
  },
  "trigger_policy": {
    "once_per_client": true,
    "retrigger_after_seconds": null,
    "rearm_distance_m": 120.0,
    "dedupe_key": "chilai.collapse_wall.017",
    "suppress_if_acknowledged": true
  },
  "source_refs": [
    {
      "source_id": "route_note.reviewed.018",
      "source_path": "reviews/route_note_reviewed_assumptions.json"
    }
  ],
  "boundary": {
    "advisory_cue": true,
    "runtime_safety_truth": false,
    "phase1_safety_mutation_allowed": false,
    "live_safety_api_calls_allowed": false,
    "model_output_is_trigger_truth": false
  }
}
```

### SpatialImprintTriggerContext

```json
{
  "client_id": "client.alex.watch",
  "scout_machine_id": "scout.pi5.alpha01",
  "trip_id": "chilai_nanhua_day1",
  "observed_at": "2026-05-26T12:04:31+08:00",
  "position": {
    "lat": 24.0300,
    "lon": 121.2840,
    "altitude_m": 2888.0,
    "horizontal_accuracy_m": 18.0,
    "vertical_accuracy_m": 12.0,
    "source": "gnss_pdr_fused"
  },
  "motion": {
    "heading_degrees": 318.0,
    "heading_source": "compass",
    "speed_mps": 0.8,
    "stationary": false
  },
  "route_progress": {
    "route_id": "chilai_nanhua_day1",
    "segment_ref": "segment_017",
    "progress_m": 8395.0,
    "nearest_cp_ref": "cp_018",
    "distance_to_nearest_cp_m": 42.0
  },
  "risk_context": {
    "risk_score": 0.78,
    "risk_zone_refs": ["risk_zone.collapse_wall.017"]
  },
  "sensor_state": {
    "barometer_available": true,
    "magnetometer_available": true,
    "imu_available": true,
    "gnss_confidence": 0.62,
    "pdr_confidence": 0.55
  }
}
```

### SpatialImprintTriggerEvent

```json
{
  "event_id": "spatial_imprint_trigger.000001",
  "imprint_id": "spatial_imprint.chilai_nanhua_day1.00042",
  "client_id": "client.alex.watch",
  "triggered_at": "2026-05-26T12:04:31+08:00",
  "status": "triggered",
  "matched_predicates": [
    "route_progress_window",
    "horizontal_radius",
    "altitude_range",
    "heading_sector"
  ],
  "suppressed": false,
  "queued_payload": {
    "payload_type": "voice_cue",
    "cue_id": "voice_cue.spatial_imprint.00042.000001"
  },
  "boundary": {
    "advisory_cue": true,
    "runtime_safety_truth": false,
    "phase1_safety_mutation_allowed": false
  }
}
```

## Trigger Predicate Model

The trigger engine should support composable predicates.

| Predicate | 中文說明 | Required inputs |
| --- | --- | --- |
| `horizontal_radius` | 平面半徑 | lat/lon, radius, client position |
| `altitude_range` | 高度範圍 | barometer/GNSS altitude |
| `vertical_delta_from_anchor` | 與 anchor 高差 | anchor altitude, client altitude |
| `heading_sector` | 指向/地磁方位扇形 | compass/heading |
| `route_progress_window` | 路線進度區間 | route progress estimate |
| `before_cp` | CP 前方距離 | CP ref, progress estimate |
| `inside_cp_radius` | 進入 CP 範圍 | CP coordinate/radius |
| `inside_segment` | 位於 segment | segment ref, progress estimate |
| `inside_risk_zone` | 進入風險區 | risk layer ref, position/progress |
| `risk_score_min` | 風險分數門檻 | route risk sample/ribbon |
| `sensor_state` | 感測器狀態 | GNSS/PDR/IMU/barometer health |
| `time_window` | 時間窗口 | local time |
| `client_group_match` | client 群組 | registered audience |

Predicate composition:

```json
{
  "operator": "all",
  "predicates": [
    {"type": "route_progress_window", "start_distance_m": 8370, "end_distance_m": 8420},
    {"type": "any", "predicates": [
      {"type": "horizontal_radius", "radius_m": 45},
      {"type": "inside_risk_zone", "risk_zone_ref": "risk_zone.collapse_wall.017"}
    ]}
  ]
}
```

The engine must emit matched and failed predicate details for `/admin/debug`.

## Payload Types

| Payload type | 中文說明 | First-slice status |
| --- | --- | --- |
| `voice_cue` | 語音提示 | first-class |
| `ui_cue` | client UI 提示 | schema only |
| `haptic_cue` | 震動提示 | schema only |
| `note_append` | 紀錄到 flight recorder | first-class for trace |
| `leader_message` | 領隊文字提示 | schema only |
| `local_alarm` | 本地警報聲 | future explicit hardware action |

`voice_cue` payloads should map into existing `VoiceCue` fields:

- `priority`: `info`, `caution`, `warning`, `urgent`;
- `category`: `route`, `body`, `weather`, `device`, `team`, `environment`;
- `source_kind`: `deterministic_fact`, `operator_note`, or
  `read_only_model_interpretation`;
- `spoken_allowed`;
- `repeat_policy`;
- boundary with no safety mutation and no remote outbound send.

## Client Registration And Audience

An imprint only triggers for clients registered to the Scout machine, trip, or
client group in the imprint audience record.

Required audience fields:

- `scope`: `registered_trip_clients`, `leader_only`, `specific_clients`,
  `scout_centre_clients`, or `all_registered_clients`;
- `client_group_refs`;
- `client_refs`;
- `exclude_actor_refs`;
- `requires_active_trip_membership`.

Alpha should start with `registered_trip_clients` and `specific_clients`.
`scout_centre_clients` should be preview/mock until the outbound send boundary
is explicitly wired.

## Runtime Flow

```text
client observation envelope
  -> position / altitude / heading / route-progress estimate
  -> load active SpatialImprintSet for this trip and client group
  -> evaluate trigger predicates
  -> apply lifecycle, TTL, suppression, once-per-client policy
  -> create SpatialImprintTriggerEvent
  -> map payload to VoiceCue or UI cue
  -> queue cue through voice/debug transport
  -> record trigger receipt and client delivery/ack state
```

The trigger engine is deterministic. AI may help plant or explain imprints, but
AI does not decide whether a runtime trigger condition matched.

## Pretrip Flow

```text
route notes / risk layer / reviewed CP / human edit
  -> imprint candidate
  -> review workbench
  -> reviewed SpatialImprintSet
  -> departure package addendum
  -> runtime load/dry-run validation
```

Pretrip imprint candidates must remain candidate-only until review and handoff.

Suggested workspace files:

```text
pretrip/projects/<project_id>/
  candidates/spatial_imprints.json
  reviews/spatial_imprint_reviews.json
  outputs/spatial_imprint_set.json
  outputs/spatial_imprint_trigger_dry_run.json
```

Suggested runtime package files:

```text
runtime_exports/<export_id>/
  spatial_imprint_set.json
  spatial_imprint_manifest.json
```

## Runtime Planting Flow

Runtime planting creates a new imprint during an active mission.

Example:

```text
leader: "在這裡前方 100 公尺種一個休息點提醒，後面隊員經過要聽到"
  -> operator/user intent
  -> current position and route progress captured
  -> create runtime imprint candidate
  -> explicit user/operator confirmation
  -> active runtime imprint store append
  -> trace event
```

Runtime-planted imprints should default to `ttl_scoped` unless the operator
explicitly sets `admin_persistent`.

## CLI Contract

Future `scout` CLI commands:

```text
scout imprint list --trip-root runtime_exports/chilai --json
scout imprint plant --input imprint_request.json --trace-log runtime-debug.jsonl --json
scout imprint expire --imprint-id spatial_imprint.chilai.00042 --operator-approved-by leader --json
scout imprint delete --imprint-id spatial_imprint.chilai.00042 --operator-approved-by admin --json
scout imprint trigger-dry-run --imprint-set spatial_imprint_set.json --context trigger_context.json --json
scout imprint export-pretrip --project-root pretrip/projects/chilai_nanhua_day1 --out outputs/spatial_imprint_set.json --json
```

Agent-facing wrappers:

```text
scout tools run scout.imprint.plant --input imprint_request.json --trace-log runtime-debug.jsonl
scout tools run scout.imprint.trigger_dry_run --input dry_run_request.json
```

CLI commands that plant, expire, delete, or activate imprints must emit the
standard `scout_agent_tool_result` envelope from
`docs/specs/scout-agent-tools-cli.md`.

## Admin Surfaces

### `/admin/pretrip`

Should show:

- imprint candidates;
- reviewed imprints;
- source route note/risk/CP refs;
- trigger condition summary;
- payload preview;
- lifecycle/TTL;
- bulk review and group selection;
- map overlay with route-progress and risk-layer anchors.

### `/admin/debug`

Should show:

- active runtime imprint set;
- trigger dry-run results;
- trigger events;
- predicate match/fail details;
- voice cue queue/played/failed receipts;
- per-client suppression and acknowledgement state.

### `/admin`

After-action view should show:

- where imprints were planted;
- which clients triggered them;
- whether cues were delivered/acknowledged;
- whether imprints caused operator/team coordination changes.

## Agent Integration

Pydantic AI may:

- propose new imprints from local evidence;
- summarize route-note/risk reasons for an imprint;
- draft `text_zh` voice payloads;
- choose a deterministic tool to plant or dry-run an imprint;
- explain trigger events after they occur.

Pydantic AI must not:

- declare runtime trigger truth;
- bypass explicit planting authorization;
- silently make a persistent imprint;
- convert model text into `ObservedFact`;
- mutate Phase 1 safety state.

## Boundary Rules

Always:

- include source refs and boundary metadata;
- preserve Chinese annotations for new product/safety terms;
- keep trigger evaluation deterministic;
- record trigger events and suppression decisions;
- support TTL and tombstone lifecycle;
- keep pretrip candidates out of runtime until reviewed/handoff stages.

Ask first:

- allowing imprints to persist across trips;
- adding real network sends to Scout Centre clients;
- adding hardware alarms as imprint payloads;
- using live sensor streams outside fixture/simulator tests;
- promoting imprint trigger output into Phase 1 safety runtime.

Never:

- call live `/safety/*` mutation endpoints from imprint evaluation;
- treat model-proposed imprints as reviewed facts;
- hard-delete imprints without tombstone audit;
- trigger remote SOS/SMS/satellite messages from an imprint;
- rely on GPS-only matching for narrow high-risk terrain without fallback or
  uncertainty metadata.

## Project Structure

Proposed files:

```text
spatial_imprint_models.py
spatial_imprint_store.py
spatial_imprint_trigger.py
spatial_imprint_cli.py
pretrip_spatial_imprint_candidates.py
pretrip_spatial_imprint_export.py
tests/test_spatial_imprint_models.py
tests/test_spatial_imprint_trigger.py
tests/test_spatial_imprint_cli.py
tests/test_pretrip_spatial_imprint_export.py
docs/specs/scout-spatial-imprint.md
```

UI/API follow-up files:

```text
admin_api.py
pretrip_admin_view.py
debug_api.py
docs/admin/phase4-pretrip-planning.html
docs/admin/phase-3-5-runtime-debug.html
```

## Testing Strategy

First-slice tests should be fixture-backed and network-free:

- schema accepts point, route-progress, CP, segment, altitude, heading, and risk
  predicates;
- lifecycle rejects expired/disabled imprints;
- trigger engine matches route-progress plus altitude plus heading;
- trigger engine records failed predicate reasons;
- once-per-client suppression works;
- TTL expiry works;
- trigger maps `voice_cue` payload into a `VoiceCue`;
- dry-run writes no live safety mutation and no remote outbound send;
- pretrip export keeps candidate/review boundary metadata;
- `/admin/debug` projection can render trigger events in a later UI slice.

Suggested command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. venv/bin/python -m pytest -q tests/test_spatial_imprint_models.py tests/test_spatial_imprint_trigger.py tests/test_spatial_imprint_cli.py tests/test_pretrip_spatial_imprint_export.py
```

## First Slice Plan

1. Add `spatial_imprint_models.py` with Pydantic models for imprint, trigger
   context, trigger event, lifecycle, audience, and predicates.
2. Add `spatial_imprint_trigger.py` with deterministic fixture-backed predicate
   evaluation.
3. Add `spatial_imprint_cli.py trigger-dry-run` that reads an imprint set and
   trigger context and emits JSON.
4. Add 3-5 Chilai fixture imprints covering collapse wall, confusing turn,
   high-risk segment, rest point, and risk-score threshold.
5. Add voice cue mapping without live playback.
6. Add tests for schema, trigger, suppression, TTL, and boundary flags.

## Success Criteria

- A Chilai fixture imprint set can be loaded.
- A dry-run context 50m before a warning anchor triggers exactly the expected
  imprint.
- A context with wrong altitude or heading records a non-trigger with reasons.
- A triggered voice cue carries existing `VoiceCueBoundary` constraints.
- Expired or disabled imprints do not trigger.
- Once-per-client suppression prevents repeated cues until rearm conditions are
  met.
- No live network, live `/safety/*`, or hardware mutation path is introduced.

## Open Questions

- Should `admin_persistent` imprints be stored per Scout machine, per route
  library, or per organization?
- Should runtime-planted imprints default to `ttl_scoped` or `trip_scoped`?
- Which client identifiers are stable enough for per-client suppression:
  watch/device id, user id, trip membership id, or Scout client registration id?
- Should heading predicates use compass heading, movement course, or both?
- How should route-progress confidence combine GNSS/PDR/IMU in the first
  production threshold?
- Should leader-created runtime imprints require one tap confirmation, voice
  confirmation, or both?
