# Spec: Phase 1 Trail Black Box

## Objective

Build the first engineering milestone for Scout as a wilderness safety black box and edge-agent runtime.

Phase 1 must prove that the current Mac/iPhone/Apple Watch + FastAPI prototype can:

1. Load a planned route as a `MissionGraph` with checkpoints, control zones, segment requirements, diversion points, and recording policies.
2. Record GPS/PDR/IMU/signal/resource observations through a small rolling raw-sample buffer.
3. Match movement against route segments, checkpoints, and control zones.
4. Seal completed segments into compressed `SegmentCapsule` records.
5. Detect path, terrain, resource, environment, and communication risk conditions.
6. Escalate through auditable L0-L4 safety states.
7. Generate an incident package when risk crosses the configured trigger point.
8. Expose ack/reack behavior through an API mock.
9. Let AI summarize incident packages without directly controlling emergency escalation.

The primary users are wilderness explorers and search-and-rescue responders. The system should behave like a route-aware field safety recorder: useful during an incident, useful at planned check-in boundaries, and useful afterward for evidence, SOP improvement, and failure analysis.

## Scope

### Current Implementation Snapshot

The current Phase 1 baseline is replay-driven and deterministic. It includes:

- `MissionGraphRuntime` for checkpoints, control zones, segment requirements, and recording policies.
- Apple Watch SensorLog JSON to GPX conversion and replay fixtures for normal, off-route, backtracking/looping, and weak-GPS routes.
- `OfflineMapContext` backed by synthetic GeoJSON corridor and hazard evidence.
- `RouteProgressEvaluator`, `RiskRuleEvaluator`, and `PdrFallbackEstimator` for map corridor deviation, hazard/risk-rule evaluation, backtracking/looping, and weak-GPS fallback.
- `GoNoGoEvaluator` for deterministic resource, daylight, weather, and communication continuation decisions.
- Provider interface layer with fixture-backed resource, environment, and communication providers that emit normalized states for `GoNoGoEvaluator`.
- `RecordingPolicyRuntime` for safety-level-aware recording profiles and raw-ring window selection.
- `IncidentPackageBuilder`, structured incident evidence summaries, `IncidentStore` JSON persistence, and `Safety API Mock` endpoints.
- `phase1_replay_demo.py` for running the full Phase 1 replay pipeline from the command line.
- `observation_adapter.py` for capability-based SensorLog/Apple Watch/iPhone payload normalization into `Observation`.
- `SafetyRuntimeSession` for streaming normalized observations through MissionGraph, offline map evidence, route progress, recording policy, and incident package logic.
- Live FastAPI safety ingest at `POST /safety/observations`, mounted on the existing server app without changing `/pdr/update`.

This snapshot remains synthetic-map and fixture-first. It is ready for real Apple Watch/GPX and real local map fixture trials. The Observation Layer now has payload normalization, a streaming safety runtime session, and a live FastAPI ingest endpoint. The legacy `/pdr/update` endpoint remains unchanged for the Wi-Fi/PDR prototype flow.

### In Scope

- Data models for `Observation`, `SafetyEvent`, `SafetyState`, `SafetyTransition`, and `IncidentPackage`.
- Mission models for `MissionGraph`, `Checkpoint`, `ControlZone`, `RouteSegment`, `RecordingPolicy`, `SegmentCapsule`, `ResourceState`, `EnvironmentState`, `CommunicationState`, `SegmentRequirement`, `DiversionPoint`, and `GoNoGoDecision`.
- A safety state machine with L0-L4 states.
- A local rolling raw-sample buffer sized for short incident context, not full-trip retention.
- Checkpoint detection and segment sealing.
- Incident package generation from the raw-sample buffer.
- Compressed segment capsules and trajectory summaries outside the raw incident window.
- Minimal route matching against GPX or GeoJSON.
- Fixture-backed offline map evidence layer using synthetic GeoJSON map context.
- L2 triggers for route, terrain, resource, environment, and communication events.
- Mock/fixture-backed resource, environment, and communication providers.
- Replay runner for sample sessions.
- API mock for ack/reack and incident package retrieval.
- Tests that run without OpenRouter or network access.

### Out of Scope

- Raspberry Pi or other hardware port.
- Full offline map engine.
- Real-world map ingestion, map rendering, vector tile serving, or map provider synchronization.
- Live weather/sunset provider integration.
- Real AT-command modem/radio implementation.
- Production radio protocol for ack/reack.
- LLM-controlled emergency escalation.
- Persistent database.
- Polished dashboard.
- Full plugin marketplace/runtime.

## Incident Package Policy

Scout records raw sensor samples into a short circular buffer during normal operation. Full-trip raw retention is not a Phase 1 goal.

Route progress is stored as sealed segment capsules:

- Passing a checkpoint seals the previous route segment.
- The sealed `SegmentCapsule` contains compressed trajectory, sensor, signal, resource, and event summaries.
- The raw ring buffer can be reset or reduced after successful sealing.
- If communication is available, Scout emits a check-in or capsule summary through the ack/reack/mock communication interface.

When the safety state machine reaches the configured incident trigger state, the incident package starts preserving lossless raw detail:

- The package includes the previous recording-policy raw window from the rolling buffer.
- The package window is selected from the active `RecordingPolicy.raw_ring_seconds`; current fixtures use 180s for low policy and 300s for medium/high-risk policy.
- Data outside the incident raw window is stored as summaries and compressed trajectory segments.

Default trigger point:

- `L2 Concern` is the first incident trigger state.
- L1 increases observation density but does not create an incident package by itself.
- L3 and L4 append stronger escalation metadata to the same package unless a separate incident is explicitly opened later.

The trigger timestamp is the first transition time into the incident trigger state. For example:

```text
L0 Normal -> L1 Watch -> L2 Concern
                         ^
                         incident_triggered_at
```

The package must preserve enough data for later reconstruction:

- Raw sensor samples from `incident_triggered_at - raw_ring_seconds` through `incident_triggered_at + raw_ring_seconds`. The package is created at trigger time and then keeps appending live/replay observations until the post-trigger window ends.
- Safety events and state transitions.
- Matched route segment and deviation measurements.
- GPS/PDR trajectory summaries before and after the raw window.
- Signal-strength summaries.
- AI-readable incident summary input.

`ai_summary_input` is structured evidence, not an LLM decision surface. It contains the trigger event, mission context, route evidence, map evidence, Go/No-Go decision when present, raw-window metadata, sealed capsule ids, and latest safety transition.
Trigger evidence remains pinned to the trigger timestamp even as later post-trigger samples extend the raw window; raw-window metadata also records the latest appended sample timestamp.

## Mission Graph

`MissionGraph` is the pre-trip and replay-time route plan. It is the main Phase 1 context object.

It contains:

- `checkpoints`: important navigation or decision points.
- `segments`: route sections between checkpoints.
- `control_zones`: terrain/resource/communication contexts.
- `recording_policies`: sampling and retention rules per zone and safety level.
- `segment_requirements`: minimum resources needed before starting each segment.
- `diversion_points`: retreat, camp, water, road access, or signal options.

`Checkpoint` is not a generic waypoint. It marks a mission-relevant boundary:

- terrain transition, such as open grassland to forest;
- ridge, scree, water source, camp, retreat fork, or fragmented terrain entry;
- last known signal spot or expected weak-GPS boundary;
- forced decision gate before a high-risk segment.

Checkpoint arrival should:

- seal the prior `SegmentCapsule`;
- emit a check-in if communication allows;
- apply the next segment's `RecordingPolicy`;
- evaluate `SegmentRequirement` before continuing;
- reset or shrink raw recording unless risk state requires retention.

## Resource-Aware Mission Segmentation

Control zones and segment boundaries should account for human/device resources, not only terrain.

Flight analogy:

```text
fuel / weather / airport capability
≈
body energy / device battery / daylight / weather / retreat/camp/water/signal options
```

`SegmentRequirement` should support:

- minimum device battery;
- minimum estimated human energy;
- expected duration;
- latest safe departure time;
- daylight requirement;
- water/camp/retreat availability;
- expected communication quality;
- zone-specific risk floor.

`ResourceState`, `EnvironmentState`, and `CommunicationState` feed deterministic go/no-go logic.

`GoNoGoDecision` values:

- `continue`
- `hold`
- `rest`
- `turn_back`
- `divert`
- `camp`

Phase 1 may use simple heuristics:

- estimated arrival exceeds sunset margin;
- device battery below next segment requirement;
- pace trend drops below planned pace threshold;
- heart-rate trend stays high for configured duration;
- next segment has no signal and current confidence is low;
- next safe diversion requires more resource than currently estimated.

These decisions are preventive. They may raise L1/L2 before physical danger occurs.

The initial deterministic `GoNoGoEvaluator` should consume a `RouteSegment`, `ResourceState`, `EnvironmentState`, `CommunicationState`, and route context fixture. It may emit:

- `RESOURCE_CONSTRAINT` for battery or human-energy deficits;
- `UNSAFE_CONTINUATION` for daylight, weather, communication, or high-risk-zone continuation concerns;
- no event when current state satisfies the next segment requirement.

The evaluator must stay provider-agnostic. It consumes normalized state models only.

## Provider Interfaces

Phase 1 should not require real-time external APIs. It must define provider interfaces and use mock/fixture-backed implementations.

### ResourceProvider

Provides human/device resource state:

- device battery;
- estimated human energy;
- pace trend;
- heart-rate trend;
- fatigue score;
- optional hydration/body-temperature fields.

### EnvironmentProvider

Provides environmental context:

- weather risk;
- temperature;
- rain probability;
- wind speed;
- sunset time;
- daylight remaining;
- visibility.

Future provider candidates include Open-Meteo, NOAA, Taiwan Central Weather Administration, Apple WeatherKit, and offline sunrise/sunset calculations.

### CommunicationProvider

Provides communication capabilities and delivery confidence:

- Wi-Fi, cellular, satellite, Bluetooth, LoRa, and radio-modem availability;
- signal strength;
- outbound/inbound support;
- nearby-pull support;
- last successful uplink;
- estimated delivery confidence.

Future real adapters may scan hardware capabilities and send commands through Wi-Fi APIs, cellular modem APIs, satellite modules, LoRa radios, BLE, or AT commands.

The safety state machine must consume normalized `ResourceState`, `EnvironmentState`, and `CommunicationState`, not provider-specific API details.

## Offline Map Evidence Layer

Phase 1 treats offline map context as the highest-priority static evidence layer for path and terrain safety decisions. Device tracks from Apple Watch, Garmin, handheld GPS, phone GPS, or PDR/IMU are noisy observations measured against this map evidence and the `MissionGraph`.

This is not a full offline map engine. Phase 1 should use synthetic fixture-backed GeoJSON map context so the safety loop is deterministic and testable before real field data and local map products are available.

Offline map evidence may include:

- approved trail corridors and known route-network polylines;
- route level or trail class metadata used to derive corridor width;
- contour-derived slope bands or synthetic slope-risk polygons;
- rivers, streams, ridges, cliffs, landslide zones, shelters, trailheads, water points, and other POIs;
- no-go, caution, and low-confidence map zones;
- map source metadata, source version, confidence, last verification time, and staleness risk.

Map evidence priority:

1. `OfflineMapContext`: static terrain, corridor, hazard, POI, and map-confidence facts.
2. `MissionGraph`: intended route, segment meaning, checkpoints, diversion points, and go/no-go requirements.
3. Device observations: GPS, PDR/IMU fallback, wearable logs, and handheld GPS tracks.
4. Evaluator confidence: GPS accuracy, PDR drift duration, map confidence, and terrain ambiguity.

The map layer should not blindly overrule current conditions. Mountain trails can disappear because of vegetation, collapse, landslide, flooding, temporary closure, or outdated map products. Map confidence and staleness risk must be preserved in safety-event details and incident-package evidence.

### Corridor Rules

Approved trail corridors are derived from map route geometry, not from the recorded device track.

Corridor width should be determined by route level or trail class when the map fixture provides it. If route level is missing, Phase 1 default corridor half-width is `3m`.

Example route-level defaults may be introduced by implementation, but should remain fixture-configurable:

```text
route_level=surveyed_trail      -> corridor_half_width_m from fixture, commonly 3m-5m
route_level=maintained_trail    -> corridor_half_width_m from fixture, commonly 5m-10m
route_level=forest_track        -> corridor_half_width_m from fixture, commonly 10m-20m
route_level=unknown             -> 3m default
```

Weak GPS must not automatically become route deviation. During weak GPS, a short PDR fallback may estimate movement against the map corridor. Route deviation should require the best available position estimate to remain outside the approved map corridor after uncertainty is considered.

### Hazard Zone Rules

Hazard zones can represent steep slopes, river or stream entry, cliff exposure, landslide areas, no-go terrain, or synthetic test hazards.

Phase 1 default:

- Entering a hazard zone starts a candidate timer.
- If the best available position estimate remains inside the hazard zone for at least `30s`, emit an L2 path-risk event.
- If the estimate exits before `30s`, do not emit L2; preserve the candidate evidence in debug/test output if useful.
- A hazard event should include hazard id, hazard type, map source metadata, duration, estimated position source, and confidence.

Hazard evidence should be evaluated before GPX-only route deviation. A user entering a mapped river, cliff, landslide, or steep-slope zone can be L2 even if GPX route progress appears plausible.

### Route-Specific Risk Rules

Some routes are known for specific risk-factor combinations, such as dense bamboo near cliff exposure, steep slopes during weak GPS, or river crossings after rain. These combinations should be data-driven rather than hard-coded into `RouteProgressEvaluator`.

Phase 1 should support fixture-backed route-specific risk rules. A rule may match:

- one or more hazard types, using `any` or `all` matching;
- sustained duration in the hazard context;
- minimum map confidence;
- weak-GPS requirement;
- optional route segment ids;
- output safety level, confidence, and reason.

Rules should live under:

```text
tests/fixtures/risk_rules/
```

Expected example:

```text
tests/fixtures/risk_rules/normal_climb_rules.json
```

The initial evaluator is pure and deterministic. It consumes already-normalized evidence such as hazard types, duration, map confidence, weak-GPS state, and segment id. It does not read sensors directly.

`RouteProgressEvaluator` should consult route-specific rules before falling back to a generic hazard-zone L2 trigger. This lets a route downgrade low-confidence map hazards to L1, require factor combinations such as `dense_bamboo + cliff_exposure`, or escalate steep-slope hazards only when weak GPS or a specific segment context is present.

## Safety Levels

- L0 Normal: baseline recording and compressed trajectory summaries.
- L1 Watch: uncertainty rises, resource margin narrows, or communication quality degrades; increase observation density and retain richer summaries.
- L2 Concern: path risk, unsafe continuation, missed checkpoint, resource shortage, or sustained sensor concern; open incident package and preserve raw detail.
- L3 Distress: sustained concern; enable beacon/reack API mock and nearby-pull behavior.
- L4 Emergency: high-confidence distress; attempt remote alert through mock interface and preserve full evidence chain.

## L2 Path-Risk Triggers

Phase 1 should prioritize path-related L2 triggers:

- Route deviation: distance from expected GPX/GeoJSON route exceeds threshold.
- Map corridor deviation: best available position estimate remains outside the approved offline-map corridor after uncertainty is considered.
- Map hazard: best available position estimate remains inside a mapped hazard zone for at least 30 seconds. The event type is `MAP_HAZARD`; the hazard type remains data-driven, such as `steep_slope`, `river`, `cliff`, `landslide`, `dense_bamboo`, or route-specific composite types.
- Looping/backtracking: recent trajectory shows sustained lack of forward route progress, route-progress regression, or repeated local circulation.
- Leaving safer terrain: movement departs the expected low-slope/easier contour corridor.
- Steep-slope entry: matched or estimated terrain slope exceeds a configured threshold, initially 30%.
- Weak GPS zone: GPS accuracy or availability degrades below configured quality while movement continues.
- Unrecognized route: movement leaves popular/approved route geometry.
- Unsafe continuation: next segment requirements exceed current resource/environment/communication state.
- Missed checkpoint: expected arrival window expires without checkpoint detection.

The initial implementation can use simplified heuristics and synthetic GeoJSON map metadata. It does not need a full terrain engine in Phase 1.

### Dense Checkpoints and Backtracking Semantics

Checkpoint arrival alone must not infer traveler intent. This is especially important for routes converted from Apple Watch or PDR/IMU logs, where the route may be short, noisy, or automatically split into many checkpoints.

Phase 1 must distinguish three concepts:

- Route geometry points: dense GPX/PDR samples used for map matching.
- Passive checkpoints: optional check-in or compression boundaries.
- Safety decision gates: mission-relevant checkpoints with terrain, resource, communication, or go/no-go meaning.

Dense checkpoints should be clustered or downgraded before safety escalation:

- `min_checkpoint_spacing_m` defines the minimum distance between independent safety-relevant checkpoints.
- Phase 1 default should be at least 30m, because 10m is close to normal phone/watch GPS error in wilderness conditions.
- Safety decision gates should normally be 50-100m apart unless the points represent clearly different terrain or operational meaning.
- If adjacent checkpoints are closer than `min_checkpoint_spacing_m`, they form a `CheckpointCluster`.
- Movement inside a checkpoint cluster or inside the current checkpoint radius must not trigger `BACKTRACKING_LOOP`.

Backtracking should be based on route-progress regression over a window, not nearest-checkpoint identity:

```text
BACKTRACKING_LOOP candidate =
  route_progress_m decreases by at least min_backtrack_distance_m
  AND regression persists for at least min_backtrack_duration_s
  AND the user has exited the active checkpoint/cluster buffer
  AND the route shape is not a known switchback or dense cluster artifact
```

Initial defaults:

- `min_backtrack_distance_m = max(30m, 3 * gps_horizontal_accuracy_m)`
- `min_backtrack_duration_s = 60s`
- `dense_checkpoint_spacing_m = 30m`

Looping should be separate from backtracking:

```text
LOOPING candidate =
  recent path_length_m >= 80m
  AND net_displacement_m <= 20m
  AND duration_s >= 120s
```

Missed checkpoint should also use route progress, not future checkpoint proximity alone:

```text
MISSED_CHECKPOINT candidate =
  route_progress_m passes expected_checkpoint_progress_m + overshoot_buffer_m
  AND expected checkpoint has not been confirmed
```

Initial default:

- `overshoot_buffer_m = max(30m, 2 * gps_horizontal_accuracy_m, checkpoint.arrival_radius_m)`

## Ack/Reack API Mock

Phase 1 should model ack/reack as HTTP APIs before choosing a real near-field protocol.

Proposed endpoints:

- `POST /safety/ack`
  - Input: requester id, request reason, optional last-known route id.
  - Output: current safety state, last known position, latest incident id, package availability, battery/signal placeholders.
- `GET /safety/incidents/{incident_id}`
  - Output: incident package JSON or metadata.
- `GET /safety/state`
  - Output: current safety state, latest transition, active risk reasons.
- `GET /safety/checkins`
  - Output: emitted checkpoint check-ins and sealed segment capsule metadata.
- `GET /safety/capsules/{capsule_id}`
  - Output: sealed `SegmentCapsule` JSON or metadata.

This is a behavioral mock only. It should not imply the final transport protocol.

## Route Fixture Strategy

The user will provide a normal GPX route for a successful climb.

From that normal route, generate one or more derived abnormal routes:

- Off-route deviation: clone the normal route and shift a middle segment away from the trail.
- Backtracking/loop route: insert a loop or repeated segment.
- Steep-slope route: annotate or synthesize a segment as exceeding the 30% slope threshold.
- Weak-GPS route: keep geometry normal but degrade GPS accuracy fields or remove intermittent points.

Generated fixtures should live under:

```text
tests/fixtures/routes/
```

Expected examples:

```text
tests/fixtures/routes/normal_climb.gpx
tests/fixtures/routes/off_route_deviation.gpx
tests/fixtures/routes/backtracking_loop.gpx
tests/fixtures/routes/weak_gps_route.gpx
```

Mission-context fixtures should live under:

```text
tests/fixtures/mission_context/
```

Offline map fixtures should live under:

```text
tests/fixtures/maps/
```

Expected examples:

```text
tests/fixtures/maps/normal_climb_map_context.geojson
tests/fixtures/maps/off_route_hazard_context.geojson
tests/fixtures/maps/steep_slope_map_context.geojson
tests/fixtures/maps/scout_260512_overpass_map_context.geojson
tests/fixtures/maps/scout_260512_overpass_query.ql
```

The first synthetic map context should be generated from the current normal GPX route and test-only hazard placement. It should include:

- approved trail corridor geometry for the normal route;
- route-level or trail-class properties where available;
- default `corridor_half_width_m = 3` when route level is missing;
- checkpoint POIs derived from the mission graph;
- at least one synthetic hazard polygon used by tests;
- source metadata such as `source=synthetic_fixture`, `source_version`, `confidence`, and `known_staleness_risk`.

Real field golden cases may use Overpass-derived OpenStreetMap linework as offline map evidence when the query is preserved next to the generated GeoJSON. These fixtures must still be deterministic in tests: keep the raw Overpass query, converted Scout map context, bbox, source timestamp, confidence, and staleness metadata in version control. Do not require large raw SensorLog captures for normal unit tests; store their reproducible summary metrics under `tests/fixtures/field_cases/`.

Current field golden case:

```text
docs/specs/scout-260512-field-golden.md
tests/fixtures/field_cases/scout_260512_golden.json
tests/fixtures/maps/scout_260512_overpass_map_context.geojson
tests/fixtures/maps/scout_260512_overpass_query.ql
```

Expected examples:

```text
tests/fixtures/mission_context/normal.json
tests/fixtures/mission_context/low_battery_near_sunset.json
tests/fixtures/mission_context/no_signal_high_risk_zone.json
tests/fixtures/mission_context/weather_deteriorating.json
```

Each fixture should provide:

```json
{
  "resource_state": {},
  "environment_state": {},
  "communication_state": {},
  "route_context": {}
}
```

## Tech Stack

- Python 3.12 through the local virtual environment.
- FastAPI for current API surface.
- Pydantic for data models.
- Pytest for unit/integration tests.
- Standard-library JSON/file APIs for local incident storage.
- GPX/GeoJSON parsing should start with standard-library XML/JSON unless a dependency becomes clearly justified.

## Commands

Syntax check:

```bash
./venv/bin/python -m py_compile agent.py imu_api.py macos_wifi.py movement_summary.py pdr_engine.py pdr_record.py sensor_decoder.py server.py shared_queue.py visualize_signal.py
```

Run current queue test:

```bash
./venv/bin/python test_queue_monitoring.py
```

Run future safety tests:

```bash
./venv/bin/python -m pytest tests/test_safety_state.py tests/test_incident_package.py tests/test_route_matching.py tests/test_replay_runner.py
```

Run the full Phase 1 test suite:

```bash
./venv/bin/python -m pytest tests -q
```

Run the Phase 1 replay demo:

```bash
./venv/bin/python phase1_replay_demo.py \
  --mission tests/fixtures/mission_graph/normal_climb_mission.json \
  --route tests/fixtures/routes/off_route_deviation.gpx \
  --incident-store /tmp/scout-phase1-demo-incidents \
  --pretty
```

Run server:

```bash
SCOUT_PORT=9099 ./venv/bin/python server.py
```

Health check:

```bash
curl http://127.0.0.1:9099/
```

## Project Structure

Current files to reuse:

- `server.py`: API routing and integration point.
- `imu_api.py`: full IMU/GPS upload path.
- `pdr_engine.py`: GPS/PDR trajectory source.
- `movement_summary.py`: local IMU summarization.
- `macos_wifi.py`: signal snapshot source.
- `PdrSample/applewatch.json`: existing replay input.
- `docs/ideas/scout-trail-black-box.md`: product one-pager.

Current Phase 1 runtime files:

- `mission_models.py`: mission graph, checkpoint, zone, segment, provider-state, and go/no-go models.
- `mission_graph.py`: route plan loading, checkpoint indexing, and segment policy lookup.
- `safety_models.py`: Pydantic models and enums.
- `safety_state_machine.py`: L0-L4 state machine.
- `incident_package.py`: raw sample buffer, incident package creation, and structured evidence summary input.
- `incident_store.py`: local JSON persistence and retrieval for incident packages.
- `safety_api.py`: Phase 1 ack/reack, incident retrieval, and live observation ingest API.
- `route_matching.py`: GPX/GeoJSON route matching.
- `offline_map_models.py`: map corridor, hazard, POI, and source metadata models.
- `offline_map.py`: fixture-backed offline map context loading and spatial evidence checks.
- `risk_rules.py`: route-specific risk rule loading and deterministic L1-L4 decision evaluation.
- `go_no_go.py`: deterministic segment requirement evaluation from resource, environment, and communication state.
- `resource_provider.py`: resource provider protocol and fixture-backed resource provider.
- `environment_provider.py`: environment provider protocol and fixture-backed environment provider.
- `communication_provider.py`: communication provider protocol and fixture-backed communication provider.
- `communication_tool.py`: normalized communication scan protocol and fixture communication tool.
- `provider_context.py`: provider bundle loading, normalized `MissionContext` assembly, and JSON-ready provider evidence.
- `checkpoint_manager.py`: checkpoint arrival detection and segment sealing.
- `mission_progress.py`: ordered checkpoint progress and segment capsule sealing.
- `route_progress.py`: route progress, map evidence, weak GPS, backtracking/looping, and missed-checkpoint safety evaluation.
- `pdr_fallback.py`: short weak-GPS PDR fallback and GPS re-anchor evidence.
- `recording_policy_runtime.py`: active segment/control-zone recording profile decisions and raw-ring duration.
- `observation_adapter.py`: capability-based SensorLog/Apple Watch/iPhone payload normalization into `Observation`.
- `safety_runtime_session.py`: streaming runtime session for live `Observation` input using the same Phase 1 evaluator stack.
- `server.py`: existing FastAPI app flow with `/safety/observations` mounted beside the legacy `/pdr/update`.
- `replay_runner.py`: offline replay from sample data.
- `phase1_replay_demo.py`: command-line Phase 1 runtime demo and JSON summary output.
- `tests/fixtures/routes/`: normal and generated abnormal routes.
- `tests/fixtures/maps/`: synthetic GeoJSON map evidence fixtures.
- `tests/fixtures/mission_context/`: mock resource, environment, communication, and route context.
- `tests/test_mission_graph.py`
- `tests/test_checkpoint_manager.py`
- `tests/test_safety_state.py`
- `tests/test_incident_package.py`
- `tests/test_segment_capsule.py`
- `tests/test_route_matching.py`
- `tests/test_offline_map.py`
- `tests/test_risk_rules.py`
- `tests/test_go_no_go.py`
- `tests/test_pdr_fallback.py`
- `tests/test_replay_runner.py`
- `tests/test_incident_store.py`
- `tests/test_safety_api.py`
- `tests/test_phase1_replay_demo.py`
- `tests/test_observation_adapter.py`
- `tests/test_safety_runtime_session.py`
- `tests/test_provider_context.py`

Deferred real provider adapter files:

- `weather_provider.py`: real or offline weather/sunset source adapter.
- `hardware_communication_adapter.py`: real device/radio/satellite/BLE communication adapter.
- `resource_estimator.py`: live human-energy/fatigue estimator from wearable and pace observations.

## Code Style

Prefer small pure-Python modules with explicit inputs and outputs. Route handlers should call domain services rather than contain safety logic.

Example style:

```python
from enum import StrEnum
from pydantic import BaseModel


class SafetyLevel(StrEnum):
    NORMAL = "L0_NORMAL"
    WATCH = "L1_WATCH"
    CONCERN = "L2_CONCERN"
    DISTRESS = "L3_DISTRESS"
    EMERGENCY = "L4_EMERGENCY"


class SafetyEvent(BaseModel):
    event_type: str
    level: SafetyLevel
    timestamp: float
    reason: str
    confidence: float
```

Provider style:

```python
class CommunicationCapability(BaseModel):
    channel: str
    available: bool
    signal_strength: float | None = None
    supports_outbound: bool = False
    supports_inbound: bool = False
    supports_nearby_pull: bool = False
    estimated_delivery_confidence: float = 0.0
```

Conventions:

- Keep safety decisions deterministic and testable.
- Keep LLM prompts outside the state transition rules.
- Keep provider adapters behind normalized state models.
- Use Pydantic models for serialized artifacts.
- Use plain data files for fixtures.
- Avoid adding dependencies until standard-library parsing is insufficient.

## Testing Strategy

Tests must validate the safety loop without network access and without an LLM API key.

Required test areas:

- State transitions:
  - L0 remains normal for healthy observations.
  - L1 starts for uncertainty or weak signal.
  - L2 starts for route deviation, backtracking/looping, steep-slope, weak GPS, unrecognized-route, unsafe-continuation, or missed-checkpoint events.
  - L3/L4 do not trigger from single noisy samples.
- Mission graph:
  - Route fixture loads into checkpoints, segments, and control zones.
  - Checkpoint arrival seals the prior segment.
  - Segment requirements produce deterministic go/no-go decisions.
- Providers:
  - Resource, environment, and communication fixtures normalize into state models.
  - Low battery near sunset can recommend `hold`, `turn_back`, `divert`, or `camp`.
  - No-signal high-risk zone can raise L1/L2 and prepare beacon/reack behavior.
- Incident packaging:
  - Package starts at the first L2 transition by default.
  - Raw window includes the previous 5 minutes.
  - Raw window continues for 5 minutes after trigger.
  - Outside-window data is summarized.
- Segment capsules:
  - Normal checkpoint passage creates a compressed segment capsule.
  - Sealed capsules preserve mission meaning without full raw history.
- Route matching:
  - Normal fixture stays within route threshold.
  - Generated off-route fixture triggers route deviation.
  - Generated loop fixture triggers looping/backtracking.
  - Weak-GPS fixture triggers L1 or L2 based on configured duration.
- Offline map evidence:
  - Normal fixture stays inside the approved synthetic map corridor and remains L0.
  - Off-route fixture triggers L2 only when the best available position estimate remains outside the approved map corridor after uncertainty is considered.
  - Weak-GPS fixture can trigger `WEAK_GPS` while remaining inside the map corridor; it must not automatically trigger route deviation.
  - Entering a synthetic hazard zone for less than 30 seconds does not trigger L2.
  - Remaining inside a synthetic hazard zone for at least 30 seconds triggers L2 and records map source metadata.
  - If a route-level corridor width is missing, the evaluator uses `3m` as the default corridor half-width.
  - The 2026-05-12 field golden case loads an Overpass-derived map context with at least 600 corridors, and both Watch segments keep at least 97% sampled points inside a corridor after horizontal GPS accuracy is considered.
- Replay:
  - Existing Apple Watch sample can be replayed without server startup.
  - Replay output is deterministic for the same input.

## Boundaries

Always:

- Keep emergency escalation auditable and deterministic.
- Preserve raw incident-window samples losslessly.
- Prefer checkpoint and segment capsule retention over full-trip raw retention.
- Keep non-AI tests runnable without API keys.
- Treat the root project as canonical; `Scout/` remains legacy reference unless explicitly targeted.

Ask first:

- Adding new runtime dependencies.
- Changing current `/imu/upload` or `/pdr/update` request formats.
- Introducing a database.
- Choosing a real ack/reack transport.
- Choosing real weather/sunset/comms API providers.
- Adding AT-command modem/radio adapters.
- Changing L2 threshold defaults after initial implementation.
- Replacing synthetic map fixtures with real OSM, government, MBTiles, or vendor map ingestion.

Never:

- Let an LLM directly set L3 or L4.
- Commit secrets or real incident data.
- Store only AI summaries when raw incident samples are required.
- Store full-trip raw sensor history by default.
- Make Raspberry Pi porting a blocker for Phase 1.
- Replace route matching with a full map engine in Phase 1.
- Treat wearable or handheld GPS tracks as higher-priority evidence than offline map context for terrain/corridor facts.
- Hard-code weather, sunset, resource, or communication data inside the safety state machine.

## Success Criteria

Phase 1 is complete when:

- The data models exist and serialize to JSON.
- A mission graph can load a route, checkpoints, control zones, segment requirements, diversion points, and recording policies.
- A replay runner can process sample data into observations.
- Checkpoint arrival seals the previous segment into a `SegmentCapsule`.
- Normal checkpoint/capsule flow keeps the raw ring buffer small.
- A normal route fixture does not trigger L2.
- Dense checkpoints under `min_checkpoint_spacing_m` do not create false `BACKTRACKING_LOOP` events.
- Staying inside the current checkpoint radius or active checkpoint cluster does not create a backtracking event.
- Returning to a prior checkpoint only creates `BACKTRACKING_LOOP` after sustained route-progress regression beyond the configured distance and duration thresholds.
- Looping is detected by high recent path length with low net displacement, independently from checkpoint identity.
- A synthetic offline map context can load approved corridors, POIs, hazards, route-level corridor widths, and source metadata.
- Map corridor deviation and hazard-zone events are evaluated against offline map evidence, not only the original GPX track.
- Missing route-level corridor width defaults to `3m`.
- Hazard-zone L2 requires at least `30s` of sustained presence.
- Missed checkpoint requires route-progress overshoot beyond the expected checkpoint, not nearest future-checkpoint proximity alone.
- A generated off-route fixture triggers L2 and opens an incident package.
- Mock low-battery/near-sunset context produces a deterministic go/no-go decision.
- Mock no-signal/high-risk-zone context changes safety level or allowed actions without real hardware.
- The incident package includes lossless raw samples from 5 minutes before the L2 trigger.
- The incident package preserves raw samples through 5 minutes after the L2 trigger.
- Data outside the raw window is represented as summaries or compressed `SegmentCapsule` records.
- Ack/reack API mock returns safety state and incident package availability.
- AI summary code, if present, only reads incident packages and does not control escalation.
- Tests run without network access.

## Current Acceptance Checklist

The replay baseline should satisfy these deterministic checks:

- Normal Apple Watch route replay:
  - `observations_processed = 3812`
  - progressed checkpoints `cp_01` through `cp_10`
  - sealed segment capsules `seg_01` through `seg_09`
  - no safety events
  - final safety level `L0_NORMAL`
  - no incident packages
- Off-route fixture:
  - emits `ROUTE_DEVIATION`
  - evidence source is `offline_map_corridor`
  - opens one L2 incident package
  - incident package includes map hazard ids and structured `ai_summary_input`
  - optional `IncidentStore` writes the package JSON.
- Backtracking/loop fixture:
  - emits `BACKTRACKING_LOOP`
  - opens one L2 incident package.
- Weak-GPS fixture:
  - emits `WEAK_GPS`
  - includes `pdr_fallback` evidence and PDR delta
  - does not treat weak GPS alone as map corridor deviation.
- Steep-slope terrain fixture:
  - normal route geometry remains inside the approved map corridor.
  - sustained `steep_slope` hazard evidence emits `MAP_HAZARD`.
  - opens one L2 incident package without emitting `ROUTE_DEVIATION`.
- Go/No-Go fixtures:
  - normal context remains L0
  - low-battery/near-sunset context emits L2 `RESOURCE_CONSTRAINT`
  - no-signal high-risk context emits L1 `UNSAFE_CONTINUATION` without incident package.
- Provider interface layer:
  - fixture-backed resource, environment, and communication providers assemble normalized `MissionContext`.
  - replay and live runtime Go/No-Go consume provider output instead of fixture JSON directly.
  - incident raw samples preserve `provider_context` evidence when Go/No-Go is evaluated.
- Recording policy:
  - L0 uses each segment policy normal profile
  - L2 trigger samples record `raw_lock`
  - incident raw window follows the active policy `raw_ring_seconds`.
- Incident package post-trigger window:
  - active incidents append observations until `raw_window_end`.
  - trigger route/map/Go-No-Go evidence remains pinned to the trigger sample.
  - persisted incident JSON is updated as post-trigger samples arrive.
- Safety API mock:
  - `/safety/ack` returns safety state, latest incident id, package availability, and last known position.
  - `/safety/observations` accepts SensorLog payloads, feeds `SafetyRuntimeSession`, and returns accepted observation count, safety level/events, recording profiles, checkpoint arrivals, incident ids, stored paths, and latest capability evidence.
  - `/safety/incidents/{incident_id}` returns persisted incident package JSON.
  - `/safety/checkins` and `/safety/capsules/{capsule_id}` expose checkpoint/capsule evidence.
- Demo CLI:
  - `phase1_replay_demo.py` runs normal and abnormal routes without server startup.
  - JSON summary reports observations, safety level/events, incident ids, stored paths, checkpoint progress, segment capsules, recording profiles, and latest incident summary.
- Observation adapter:
  - Apple Watch/SensorLog payloads normalize GPS, IMU, heart-rate, pedometer, battery, and raw payload fields into `Observation`.
  - Apple Watch and iPhone Wi-Fi RSSI absence is recorded as `unavailable_by_platform`, not as fake RSSI and not as an error.
  - Server-side Wi-Fi scan evidence can be attached as a separate capability when available.
- Safety runtime session:
  - Missing-GPS observations preserve recording policy evidence without route events.
  - SensorLog observations flow through route matching, offline map corridor evidence, and recording policy decisions.
  - Off-route observation streams can trigger L2, build an incident package, and persist incident JSON without GPX replay.
- Field golden fixtures:
  - `scout_260512_golden.json` derives MissionGraph, mission context, risk rules, and downsampled GPX route fixtures through `generate_field_phase1_fixtures.py`.
  - the second Apple Watch segment preserves weak/noisy GPS evidence for later PDR fallback replay validation.
- Existing app flow:
  - `server.app` registers both `/pdr/update` and `/safety/observations`.
  - `/pdr/update` remains the legacy Wi-Fi/PDR/AI-worker path; Phase 1 safety ingest is additive.
- Full test suite:
  - `./venv/bin/python -m pytest tests -q`
  - current expected result: `93 passed, 1 warning, 9 subtests passed`.

## Open Questions

- What exact raw sample schema should be preserved in the incident package: original uploaded payloads, normalized observations, or both?
- What GPS weak-signal fields are reliable in the first test source: horizontal accuracy, missing point duration, signal quality, or a synthetic fixture flag?
- What route deviation threshold should be the default: meters from route, elapsed time off route, or both?
- What route-progress regression distance and duration should move backtracking from L1 Watch to L2 Concern?
- Which GPX-derived checkpoints should be passive compression boundaries versus safety decision gates?
- Should the first package format optimize for machine replay, responder readability, or both?
- Which checkpoints are mandatory go/no-go gates?
- What default safety margin should apply before sunset?
- What first communication channels should the mock model: Wi-Fi, cellular, BLE, LoRa, satellite, or radio modem?
- Should resource state preserve heart-rate raw data, trend summaries, or both?
