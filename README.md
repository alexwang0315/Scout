# S.C.O.U.T. Fusion

S.C.O.U.T. Fusion is a FastAPI-based wilderness safety black box and file-backed safety evidence system. Phase 1 centers on a `MissionGraph` route plan, Apple Watch / SensorLog observations, offline map evidence, deterministic safety evaluation, incident packaging, and an after-action admin viewer. Phase 2 adds the file-backed Brain, replay, remote status, decision-support, and audit surfaces. Phase 3 safely connects the two after incident persistence while keeping Phase 1 as the live safety baseline. Phase 3.5 adds pre-porting runtime readiness and debug tooling so Scout behavior can be inspected before hardware deployment.

The original Wi-Fi/PDR navigation prototype still exists as a legacy app flow. The current product direction is route-aware field safety recording: prove where the traveler was, what the map and mission plan said, why a safety level changed, and what raw evidence should be sealed for later review.

![Scout Phase 1 Admin after-action viewer](docs/assets/phase1-admin-after-action.png)

## What It Does

- Loads a `MissionGraph` with checkpoints, segments, control zones, recording policies, route requirements, and diversion metadata.
- Replays GPX / Apple Watch-derived route fixtures into normalized safety observations.
- Evaluates route progress, missed checkpoints, sustained backtracking, loops, weak GPS, offline map corridor deviation, map hazards, and route-specific risk rules.
- Uses offline GeoJSON map context as static evidence for approved corridors, POIs, hazards, route-level corridor widths, confidence, and staleness metadata.
- Builds incident packages with raw sample windows, segment capsules, safety transitions, route evidence, map evidence, and structured summary input.
- Exposes live Phase 1 ingest APIs beside the legacy `/pdr/update` flow.
- Provides an admin after-action viewer with SVG map evidence, route/corridor overlays, checkpoint and segment evidence, JSON inspection, and tree-to-map highlighting.
- Imports persisted Phase 1 incident packages into Phase 2 Brain nodes through a disabled-by-default, post-persistence bridge.
- Surfaces imported Phase 1 adapter evidence in Phase 2 admin preview and artifact manifests without creating a Phase 1 write path.
- Exposes opt-in, read-only Phase 3.5 debug surfaces for runtime event timelines, L0-L4 transitions, provider degraded status, Ln/skill run visibility, and mock outbound message queues.
- Keeps the legacy macOS Wi-Fi scan, PDR trajectory, heatmap, `/navigate`, and LLM navigation prototype paths available for compatibility.

## Scout AI OS MVP

This checkout also contains a new Scout AI OS MVP scaffold under `src/scout/`.
It implements the Phase 0-9 scope from
`docs/specs/SCOUT_AI_OS_MVP_SPEC.md`: typed workflow/capability/learning
schemas, SQLite stores, permission checks, local notification events, manual
runtime ticks, provider-backed typed agent facades with a deterministic no-LLM
provider, generated capability sandbox verification, FastAPI routes, and
reviewable learning artifact approval.

Focused verification:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_scout_ai_os_scaffold.py \
  tests/test_scout_ai_os_schemas.py \
  tests/test_scout_ai_os_stores.py \
  tests/test_scout_ai_os_runtime.py \
  tests/test_scout_ai_os_learning_store.py \
  tests/test_scout_ai_os_agents.py \
  tests/test_scout_ai_os_sandbox.py \
  tests/test_scout_ai_os_api.py \
  tests/test_scout_ai_os_docs.py
```

MVP limits: no production-grade sandbox isolation, no live LLM requirement, no
external notification provider, no generated-code production install path, and
no mutation of Scout Phase 1 L0-L4 safety truth.

## Phase 1 Status

Phase 1 is at release-candidate status on the `codex/phase-1-trail-black-box` branch.

Validated baseline:

- Normal Apple Watch route remains `L0_NORMAL`.
- Off-route synthetic fixture triggers `L2_CONCERN` through offline map corridor evidence.
- Backtracking/loop, weak GPS PDR fallback, steep-slope hazard, Go/No-Go provider fixtures, recording policy, incident post-trigger window, live observation ingest, and field golden replay are covered by deterministic tests.
- Admin viewer can inspect the 2026-05-12 field golden case and link evidence tree selection to SVG map highlight.

Current release-gate verification:

```bash
./venv/bin/python -m pytest \
  tests/test_phase1_incident_bridge.py \
  tests/test_phase1_phase2_adapter.py \
  tests/test_phase1_adapter_fixture_matrix.py \
  tests/test_phase2_import_phase1_incident_cli.py \
  tests/test_phase2_admin_preview.py \
  tests/test_phase2_artifact_manifest.py \
  tests/test_phase3_decision_support_matrix.py \
  tests/test_phase2_release_check.py
# 50 passed, 1 warning

./venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
# {"ok":true,...}

./venv/bin/python -m pytest
# 274 passed, 1 warning
```

These numbers were verified after the Phase 3 bridge, fixture matrix,
admin/manifest read-only integration, decision-support replay matrix, release
gate, and hardening slices.

## Phase 2 Preview

Phase 2 is a preview of Scout as a personal safety operating system layered on
top of the Phase 1 safety black box. The current completed slices are
file-based Brain models and store behavior, fact-only writeback policy, a Scout
skill registry and mock runtime, Ln activation gates and noise control, remote
status JSON, bounded decision option sets, team separation and beacon mocks,
case replay, team replay fixture persistence, option replay, case replay Brain
integration, and a compact team replay demo runner.
The latest cleanup slices also add an env-gated Phase 2 admin API mount, shared
ridge-loop demo defaults, and explicit manual write permission for persisted
decision option sets.
The ref cleanup adds shared Phase 2 reference classification and a documented
remote-status JSON artifact ID convention.
The latest slices add shared store helpers, a second forest-traverse team replay
fixture, and read-only evidence/artifact inspection fields for the Phase 2 admin
preview payload.

Key focused verification commands:

```bash
./venv/bin/python -m pytest tests/test_phase2_brain.py
./venv/bin/python -m pytest tests/test_phase2_writeback_policy.py
./venv/bin/python -m pytest tests/test_skill_registry.py
./venv/bin/python -m pytest tests/test_ln_constraints.py
./venv/bin/python -m pytest tests/test_phase2_remote_status.py
./venv/bin/python -m pytest tests/test_decision_option_sets.py
./venv/bin/python -m pytest tests/test_team_beacon.py
./venv/bin/python -m pytest tests/test_phase2_case_replay.py
./venv/bin/python -m pytest tests/test_phase2_option_replay.py
./venv/bin/python -m pytest tests/test_phase2_refs.py
./venv/bin/python -m pytest tests/test_phase2_store_utils.py
./venv/bin/python -m pytest tests/test_phase2_case_replay_integration.py
./venv/bin/python -m pytest tests/test_phase2_team_replay_demo.py
./venv/bin/python -m pytest tests/test_phase2_team_replay_store.py
./venv/bin/python -m pytest tests/test_phase2_team_replay_second_fixture.py
./venv/bin/python -m pytest tests/test_phase2_remote_status_store.py
./venv/bin/python -m pytest tests/test_phase2_brain_ingest.py
./venv/bin/python -m pytest tests/test_admin_after_action.py
./venv/bin/python -m pytest tests/test_phase2_admin_preview.py
./venv/bin/python -m pytest tests/test_phase2_admin_api.py
./venv/bin/python -m pytest tests/test_phase2_admin_api_mount.py
./venv/bin/python -m pytest tests/test_phase2_demo_defaults.py
./venv/bin/python -m pytest tests/test_phase2_artifact_manifest.py
./venv/bin/python -m pytest tests/test_phase2_artifact_manifest_store.py
./venv/bin/python -m pytest tests/test_phase2_team_replay_demo_golden.py
./venv/bin/python -m pytest tests/test_phase2_release_check.py
./venv/bin/python -m pytest tests/test_skill_manifest_coverage.py
```

CLI smoke demo:

```bash
./venv/bin/python phase2_team_replay_demo.py --store-root /tmp/scout-phase2-team-replay-demo
# {"counts":{...},"fixture_id":"phase2.team_replay.ridge_three_person_20260513","fixture_path":"...","key_ids":{...},"skill_audit":{...}}
```

Preview limits:

- Phase 2 currently uses JSON artifacts, local files, mocks, and replay
  fixtures; it does not include cloud transport or real radio/beacon hardware.
- Phase 1 deterministic safety behavior remains the baseline and is not
  replaced by Phase 2 skills, Brain nodes, or model interpretations.
- Decision options and beacon outputs are bounded support artifacts, not
  guaranteed rescue outcomes or precise navigation claims.

Relevant specs:

- `docs/specs/phase-2-personal-safety-os.md`
- `docs/specs/phase-2-implementation-plan.md`

## Phase 3 Integration and Operations

Phase 3 is complete for the current release gate. It operationally connects
Phase 1 and Phase 2 in one direction:

```text
Phase 1 live safety decision
  -> persisted IncidentPackage JSON
  -> Phase 1 to Phase 2 adapter
  -> Phase 2 Brain nodes
  -> replay, remote status, options, admin, manifest, review
```

Implemented Phase 3 slices:

- `Phase1IncidentBridge` is disabled by default and only runs after
  `IncidentStore` persistence succeeds.
- Bridge failures are logged and converted into structured result objects; they
  do not change Phase 1 escalation, response payloads, or persisted incident
  JSON.
- Re-importing the same incident is idempotent.
- Fixture coverage includes missed checkpoint, weak GPS / PDR fallback,
  backtracking loop, steep slope / map hazard, resource constraint, unsafe
  continuation, sensor anomaly, and multiple incidents in one mission.
- Phase 2 admin preview and artifact manifest expose imported Phase 1 adapter
  evidence read-only, grouped by incident id with artifact/fact/measurement
  links.
- Decision-support replay covers hold, turn back, wait/rest/reassess,
  rendezvous beacon trend, notify remote contact, and continue with degraded
  confidence options.

Guardrails:

- Phase 1 remains the deterministic live safety baseline.
- Phase 2 Brain nodes, model interpretations, skill outputs, and decision
  options do not influence Phase 1 L0-L4 safety decisions.
- Model output is not written as `ObservedFact`.
- The bridge is opt-in through `SCOUT_PHASE2_INCIDENT_BRIDGE=1` and
  `SCOUT_PHASE2_BRAIN_STORE_ROOT`.

Relevant specs:

- `docs/specs/phase-3-integration-plan.md`
- `docs/specs/phase-2-live-integration-research.md`
- `docs/architecture/phase-1-2-architecture.html`

## Phase 3.5 Runtime Readiness and Debug Tooling

Phase 3.5 is complete as a pre-porting runtime observability layer. It does not
start the Raspberry Pi / Docker hardware port and it does not change Phase 1
safety decisions.

Implemented Phase 3.5 slices:

- append-only runtime debug event models and memory/file-backed JSONL logs;
- fixture-backed runtime simulator and replay demo;
- mock outbound transport with `queued`, `sent`, `failed`, and
  `mock-delivered` states only;
- read-only `/debug/events`, `/debug/state`, and `/debug/messages` JSON API;
- opt-in `/admin/debug` web UI with timeline, map highlighting, L0-L4 state,
  provider status, incident/bridge status, Ln/skill runs, outbound queue, and
  boundary tabs;
- fixture-backed UI demo and demo loader;
- Phase 3.5 readiness checker and debug runbook.

Guardrails:

- `/debug` is read-only.
- Debug events are observations, not safety runtime inputs.
- Debug tooling must not write `ObservedFact`.
- Outbound transport remains mock-only in Phase 3.5.
- The debug API is disabled by default and mounted only when
  `SCOUT_DEBUG_API_ENABLED=1`.

Run the repeatable UI demo:

```bash
./venv/bin/python phase35_debug_demo_loader.py --pretty
```

Then run the printed `server_command` and open:

```text
http://127.0.0.1:9099/admin/debug
```

Latest focused verification:

```bash
./venv/bin/python -m pytest \
  tests/test_runtime_debug_event_log.py \
  tests/test_runtime_simulator.py \
  tests/test_runtime_debug_ui_demo.py \
  tests/test_mock_outbound_transport.py \
  tests/test_debug_api.py \
  tests/test_debug_api_mount.py \
  tests/test_debug_page.py \
  tests/test_phase35_debug_runbook.py \
  tests/test_phase35_runtime_readiness_check.py \
  tests/test_safety_runtime_session.py \
  tests/test_safety_api.py \
  tests/test_phase1_incident_bridge.py \
  tests/test_skill_runtime.py
# 69 passed, 1 warning

./venv/bin/python phase35_runtime_readiness_check.py --pretty
# {"ok": true, ...}

./venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
# {"ok": true, ...}
```

Relevant specs and runbooks:

- `docs/specs/phase-3-5-runtime-readiness-debug-tooling.md`
- `docs/admin/phase-3-5-debug-runbook.md`
- `docs/admin/phase-3-5-runtime-debug.html`

## Milestone 10 Cross-Surface AI Assistant

Milestone 10 is implemented for the initial guardrail slice. It provides a
shared read-only assistant contract for `/admin/debug`, `/admin`,
`/admin/pretrip`, and future hardware-readiness surfaces without changing Phase
1 safety behavior, Phase 2 Brain writeback, Phase 4 planning review, outbound
transport, or hardware state.

Implemented slices:

- Pydantic request/response models with per-surface constraints and source refs.
- Deterministic mock assistant provider for default, no-network operation.
- Bounded read-only context adapters for debug, admin after-action, pretrip, and
  hardware-readiness surfaces.
- Opt-in read-only `POST /assistant/query` endpoint, mounted only with
  `SCOUT_AI_ASSISTANT_ENABLED=1`.
- Debug and pretrip assistant UI shells labeled as read-only model
  interpretation, including timeline-based suggested questions such as
  `Why did CP2 become an L2 event?`.
- Opt-in Pydantic AI provider separated from `/navigate`, with timeout/context
  budget, prompt-boundary enforcement, and cloud-to-local model fallback config.
- `assistant_readiness_check.py` guardrail gate and admin runbook.

Guardrails:

- no Phase 1 safety mutation;
- no `ObservedFact` writes from model output;
- no Phase 2 Brain, IncidentStore, pre-trip review, outbound, or hardware
  mutation;
- assistant answers must be labeled as read-only model interpretation.

Enable the read-only API with the mock provider:

```bash
SCOUT_AI_ASSISTANT_ENABLED=1 \
SCOUT_AI_ASSISTANT_PROVIDER=mock \
./venv/bin/python server.py
```

For opt-in Pydantic AI, point the server at an external model config that
defines both `cloud_model` and `local_model`; `token_id` is only a token
reference and secrets remain in environment variables named by `token_env_var`.
If cloud initialization or communication fails, the provider falls back to the
local model and still returns only read-only model interpretations.

Latest focused verification:

```bash
./venv/bin/python -m pytest \
  tests/test_assistant_model_config.py \
  tests/test_assistant_models.py \
  tests/test_assistant_provider.py \
  tests/test_assistant_pydantic_provider.py \
  tests/test_assistant_context.py \
  tests/test_assistant_api.py \
  tests/test_assistant_page.py \
  tests/test_assistant_readiness_check.py
# 44 passed, 1 warning

./venv/bin/python assistant_readiness_check.py --pretty
# {"ok": true, ...}
```

Relevant specs:

- `docs/specs/scout-cross-surface-ai-assistant.md`
- `docs/specs/scout-cross-surface-ai-assistant-continuation-prompt.md`
- `docs/admin/cross-surface-ai-assistant-runbook.md`

## Project Layout

| File | Purpose |
| --- | --- |
| `server.py` | Main FastAPI server, route registration, background AI worker, map endpoints. |
| `safety_api.py` | Phase 1 ack/reack, incident retrieval, check-in, capsule, and live observation ingest API. |
| `mission_models.py` | Mission graph, checkpoint, segment, control-zone, provider-state, and Go/No-Go models. |
| `mission_graph.py` | MissionGraph loading, checkpoint indexing, and segment policy lookup. |
| `route_progress.py` | Route progress, map evidence, weak GPS, backtracking/looping, and missed-checkpoint evaluation. |
| `offline_map.py` / `offline_map_models.py` | Offline GeoJSON corridor, POI, hazard, source metadata, and spatial evidence checks. |
| `risk_rules.py` | Fixture-backed route-specific L1-L4 risk rule evaluation. |
| `pdr_fallback.py` | Short weak-GPS dead-reckoning fallback and GPS re-anchor evidence. |
| `replay_runner.py` | Offline replay pipeline from route samples into observations, safety events, and incident packages. |
| `safety_runtime_session.py` | Streaming runtime session for live `Observation` input. |
| `incident_package.py` / `incident_store.py` | Raw ring buffer, incident packaging, evidence summary input, and JSON persistence. |
| `admin_api.py` / `admin_after_action.py` | Admin case API and after-action view model builder. |
| `docs/admin/phase1-after-action.html` | Static admin presentation layer for field-case map and evidence inspection. |
| `debug_api.py` | Read-only Phase 3.5 `/debug` JSON API and `/admin/debug` page router. |
| `assistant_models.py` / `assistant_provider.py` | Milestone 10 read-only assistant contract and deterministic mock provider. |
| `assistant_context.py` / `*_assistant_context.py` | Bounded surface context adapters for debug, admin, pretrip, and hardware readiness. |
| `assistant_api.py` / `assistant_pydantic_provider.py` | Opt-in `/assistant/query` router and failure-isolated Pydantic AI provider. |
| `assistant_model_config.py` | External cloud/local assistant model config loader with token reference validation. |
| `assistant_readiness_check.py` | Milestone 10 required artifact and guardrail checker. |
| `runtime_debug_models.py` / `runtime_debug_log.py` | Phase 3.5 debug event envelopes and append-only memory/file-backed event logs. |
| `runtime_simulator.py` / `runtime_debug_replay_demo.py` | Fixture replay path that emits runtime debug timeline events. |
| `runtime_debug_ui_demo.py` / `phase35_debug_demo_loader.py` | Deterministic `/admin/debug` demo data and local demo launcher output. |
| `mock_outbound_transport.py` | Phase 3.5 mock-only outbound message queue and state transitions. |
| `phase35_runtime_readiness_check.py` | Phase 3.5 required artifact and guardrail checker. |
| `docs/admin/phase-3-5-runtime-debug.html` | Static Phase 3.5 runtime debug UI. |
| `phase1_replay_demo.py` | CLI demo for normal and abnormal Phase 1 route replay. |
| `agent.py` | Pydantic AI navigation agent and Wi-Fi scan/move tools. |
| `macos_wifi.py` | macOS Wi-Fi scanner using `airport -s`. |
| `imu_api.py` | `/imu/upload` router for full IMU/GPS SensorLog payloads. |
| `pdr_record.py` | Pydantic model for mobile sensor records. |
| `pdr_engine.py` | PDR engine for IMU-based and distance/heading-based position updates. |
| `sensor_decoder.py` | Decoder for legacy `/pdr/update` SensorLog payloads. |
| `movement_summary.py` | Local Apple Watch / IMU summary extraction and feedback features. |
| `visualize_signal.py` | Signal heatmap generation. |
| `shared_queue.py` | Shared asyncio queue for non-blocking AI decision events. |
| `index.html` | Minimal live dashboard. |

The repository root is the canonical server version. The `Scout/` directory is an older nested copy kept for reference and should not be used as the active server entrypoint unless you intentionally work on that legacy copy.

## Phase 1 Admin Viewer

Start the server:

```bash
SCOUT_PORT=9101 ./venv/bin/python server.py
```

Open:

```text
http://127.0.0.1:9101/admin
```

The admin page loads the default `scout_260512_field_golden` case. It shows the offline map context, route trace, checkpoints, segment capsules, replay timeline, risk rules, and selected JSON evidence. Selecting an evidence node in the right pane highlights the matching SVG map element on the left.

API endpoint:

```bash
curl http://127.0.0.1:9101/admin/cases/scout_260512_field_golden
```

Relevant specs:

- `docs/specs/phase-1-trail-black-box.md`
- `docs/specs/phase-1-admin-after-action-viewer.md`
- `docs/specs/scout-260512-field-golden.md`
- `docs/architecture/phase-1-architecture.html`

## Phase 1 Replay Demo

Run a normal route:

```bash
./venv/bin/python phase1_replay_demo.py \
  --mission tests/fixtures/mission_graph/normal_climb_mission.json \
  --route tests/fixtures/routes/normal_climb.gpx \
  --pretty
```

Run an off-route L2 replay and persist the incident package:

```bash
./venv/bin/python phase1_replay_demo.py \
  --mission tests/fixtures/mission_graph/normal_climb_mission.json \
  --route tests/fixtures/routes/off_route_deviation.gpx \
  --incident-store /tmp/scout-phase1-demo-incidents \
  --pretty
```

Run the 2026-05-12 field replay baseline:

```bash
./venv/bin/python phase1_replay_demo.py \
  --mission tests/fixtures/mission_graph/scout_260512_field_mission.json \
  --route tests/fixtures/routes/scout_260512_field_route.gpx \
  --map-context tests/fixtures/maps/scout_260512_overpass_map_context.geojson \
  --risk-rules tests/fixtures/risk_rules/scout_260512_field_rules.json \
  --mission-context tests/fixtures/mission_context/scout_260512_field_normal.json \
  --route-progress-config tests/fixtures/route_progress/scout_260512_field_config.json \
  --pretty
```

## Requirements

- macOS, for Wi-Fi scanning via `/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/resources/airport`.
- Python 3.12 is what the current local virtual environment uses.
- OpenRouter API key for `/navigate` and background AI decisions.
- Network access when calling the LLM provider.

Core Python packages used by the current app:

```bash
fastapi
uvicorn
python-dotenv
pydantic
pydantic-ai
matplotlib
numpy
scipy
python-multipart
```

The repository currently includes a local `venv/`, but for a clean setup you should generally create your own virtual environment and install dependencies there.

## Environment

Create `.env` in the repository root:

```bash
SCOUT_DEBUG=true
SCOUT_PORT=9099
OPENROUTER_API_KEY=your_openrouter_key_here
```

Notes:

- `SCOUT_PORT` defaults to `9099` when absent.
- `OPENROUTER_API_KEY` is required for AI navigation routes and worker decisions.
- `SCOUT_DEBUG_API_ENABLED=1` mounts the Phase 3.5 read-only debug API and
  `/admin/debug`.
- `SCOUT_DEBUG_LOG_PATH=/path/to/runtime-debug-events.jsonl` points the debug
  API at a file-backed replay/demo timeline.
- `SCOUT_AI_ASSISTANT_ENABLED=1` mounts the Milestone 10 read-only
  `/assistant/query` API.
- `SCOUT_AI_ASSISTANT_PROVIDER=mock|pydantic_ai` selects the assistant provider;
  it defaults to deterministic `mock`.
- `SCOUT_AI_ASSISTANT_CONFIG_PATH=/secure/local/scout-assistant-models.json`
  points the opt-in Pydantic AI provider at the external cloud/local model
  config.
- `.env` is ignored by git and should not be committed.

## Run

From the repository root:

```bash
./venv/bin/python server.py
```

Or with uvicorn directly:

```bash
./venv/bin/uvicorn server:app --host 0.0.0.0 --port 9099
```

If using a custom port:

```bash
SCOUT_PORT=9101 ./venv/bin/python server.py
```

Health check:

```bash
curl http://127.0.0.1:9099/
```

Expected response:

```json
{"status":"S.C.O.U.T. Fusion Online","debug":true,"port":9099}
```

## API Workflow

### 1. Check Server Status

```bash
curl http://127.0.0.1:9099/status
```

Returns the latest pose, strongest Wi-Fi signal, trajectory counters, last instruction, and queued AI events.

### 2. Upload Full IMU/GPS Records

Endpoint:

```http
POST /imu/upload
```

Example:

```bash
curl -X POST http://127.0.0.1:9099/imu/upload \
  -H 'Content-Type: application/json' \
  -d '{
    "motionTimestamp_sinceReboot": 1000000000,
    "accelerometerAccelerationX": 2.0,
    "accelerometerAccelerationY": 0.0,
    "accelerometerAccelerationZ": 0.0,
    "gyroRotationZ": 0.0,
    "locationLatitude": 25.0,
    "locationLongitude": 121.0
  }'
```

Behavior:

- GPS points are added to `gps_trajectory` when latitude and longitude are present.
- IMU data updates `pdr_trajectory` through `update_from_imu()`.

### 3. Upload Legacy Distance/Heading PDR Data

Endpoint:

```http
POST /pdr/update
```

Example:

```bash
curl -X POST http://127.0.0.1:9099/pdr/update \
  -H 'Content-Type: application/json' \
  -d '{"pedometerNumberOfSteps": 2, "motionHeading": 90}'
```

Supported distance fields:

- `pedometerDistance`
- `pedometerNumberOfSteps`
- legacy typo-compatible `pedometerNumberofSteps`

Supported heading fields:

- `motionHeading`
- `locationCourse`

The endpoint updates position and queues an AI decision event without blocking ingestion.

It also accepts `imu_data` arrays from Apple Watch / SensorLog JSON exports. These samples are converted into local movement summaries and added to the PDR trajectory using fields such as:

- `accelerometerAccelerationX`
- `accelerometerAccelerationY`
- `accelerometerAccelerationZ`
- `motionGravityY`
- `motionTimestamp_sinceReboot`

Movement summaries can be checked without calling the LLM:

```bash
curl http://127.0.0.1:9099/movement-summary
```

After sending an Apple Watch sample directory, generate the trajectory image from the same uploaded samples:

```bash
./send_samples.sh PdrSample
curl http://127.0.0.1:9099/trajectory/status
curl http://127.0.0.1:9099/trajectory/map
```

### 4. Request Navigation

```bash
curl http://127.0.0.1:9099/navigate
```

This calls the LLM navigation agent. It requires a valid `OPENROUTER_API_KEY`.

### 5. Generate Maps

Signal heatmap:

```bash
curl http://127.0.0.1:9099/generate_map
```

Output file:

```text
heatmap.png
```

Trajectory map:

```bash
curl http://127.0.0.1:9099/trajectory/map
```

Output file:

```text
trajectory_map.png
```

Trajectory counters:

```bash
curl http://127.0.0.1:9099/trajectory/status
```

## Dashboard

Open `index.html` from a browser that can reach the server host. The page polls:

```text
http://<server-host>:9099/status
```

If serving from another machine, make sure the phone/browser can reach the Mac's LAN IP and that macOS firewall allows the port.

## Current Runtime Fixes

This version fixes the main execution blockers from the previous state:

- Restored a complete FastAPI app in `server.py` after it had been reduced to an incomplete worker snippet.
- Added FastAPI lifespan startup/shutdown handling for the background AI worker.
- Added `PDREngine.update_position()` so `/pdr/update` works with the current PDR engine.
- Added missing `time` import in `pdr_engine.py`.
- Updated SensorLog step-field parsing to support `pedometerNumberOfSteps`.
- Updated Pydantic v2 model config and replaced deprecated `dict()` usage.
- Made `SCOUT_PORT` effective instead of hardcoding the runtime port.
- Merged the legacy `Scout/server.py` Apple Watch movement-summary flow into the root `server.py`.

## Verification Commands

Syntax check:

```bash
./venv/bin/python -m py_compile agent.py imu_api.py macos_wifi.py movement_summary.py pdr_engine.py pdr_record.py sensor_decoder.py server.py shared_queue.py visualize_signal.py
```

Import and route check:

```bash
./venv/bin/python - <<'PY'
import server
print('import ok')
print(sorted(route.path for route in server.app.routes))
PY
```

Temporary live server check:

```bash
SCOUT_PORT=9101 ./venv/bin/python server.py
curl http://127.0.0.1:9101/
```

Apple Watch sample check:

```bash
./venv/bin/python server.py
./send_samples.sh PdrSample
curl http://127.0.0.1:9099/movement-summary
```

## Known Notes

- Wi-Fi scanning is macOS-specific and depends on the private `airport` binary path.
- Trajectory state is currently in memory. Restarting the server clears runtime trajectory state.
- Background AI decisions are queued in memory and are not persisted.
- `cert.pem` and `key.pem` appear to be local certificates; verify before using them in production.
- The repository has historical tracked generated files such as `venv/` and `__pycache__/`. They are not ideal for long-term repository hygiene.
