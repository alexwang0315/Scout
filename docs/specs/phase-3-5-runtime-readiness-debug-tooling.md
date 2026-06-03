# Spec: Scout Phase 3.5 Runtime Readiness and Debug Tooling

## Status

Proposed.

This document defines a pre-porting phase between the completed Phase 3
integration gate and the future Phase 5 hardware port. It should be reviewed
before implementation starts.

## Assumptions

- Phase 1, Phase 2, and Phase 3 integration gate remain accepted baselines.
- Phase 1 remains the deterministic live safety authority.
- Phase 4 remains the pre-trip planning, UI, and usability track.
- Phase 5 remains the hardware port and deployment track.
- The first hardware target remains Raspberry Pi 5 + Docker + external SSD,
  but this phase must not start Pi or Docker implementation.
- Debug and simulator tooling may observe Scout runtime behavior, but must not
  change route progress, L0-L4 transitions, incident creation, bridge behavior,
  provider evidence, skill policy, or outbound transport behavior.
- The on-trip safe-device loop is defined in
  `docs/specs/scout-closed-loop-operating-cycle.md`. This phase owns the
  read-only observability surface for that loop: plan-node events,
  hardware/software status, Ln action traces, mock outbound queue state,
  communication-node status, team-care prompts, and search black-box snapshots.
- For alpha, `/admin/debug` or an equivalent on-device debug surface is the
  primary verification surface for the On-Trip Scout Safe Device foundation.

## Objective

Create a pre-porting runtime readiness phase for Scout.

The goal is to make Scout observable before it moves onto physical hardware.
This phase builds the simulator, runtime debug event log, read-only debug JSON
API, debug web surface, and mock outbound message layer needed to inspect:

- observation ingest;
- route progress;
- checkpoint detection;
- safety event triggers;
- L0-L4 safety state transitions;
- incident package creation and persistence;
- Phase 3 bridge import status;
- provider availability and degraded status;
- Ln activation gate and skill run envelopes;
- outbound messages Scout would attempt to send;
- on-trip plan-node check-ins, hardware/software state, team-care prompts,
  communication-node state, and search black-box evidence snapshots.

Success means a developer can replay fixtures or hardware-like samples and
answer:

```text
What did Scout observe?
What did Scout decide?
What action would Scout attempt?
What provider or transport was degraded?
What did Scout queue for outbound delivery?
What persisted artifact proves this behavior?
```

## Chinese Guardrails

中文註釋：這不是一般使用者 UI。這個階段的 `/debug` web page 是工程與硬體除錯介面，不是登山者日常操作 app。

中文註釋：這不是 pre-trip planning。它不負責路線規劃、CP/POI 建議、MissionGraph 編譯、出發審核，這些仍屬於 Phase 4。

中文註釋：這是 hardware/debug/readiness tooling。目的在於上硬體前先看清楚 Scout runtime 的 event trigger、reaction、action、provider 狀態與 mock outbound message。

中文註釋：`/debug` 必須 read-only。它只能讀 event log、runtime snapshot、mock message queue，不可以觸發 `/safety/*` mutation、不可以改 Phase 1 state、不可以寫 Phase 2 Brain。

中文註釋：debug event 不能影響 Scout safety runtime。debug event 是旁路觀測資料，不是 safety evaluator input，不是 risk rule input，也不是 Phase 1 decision source。

中文註釋：outbound message 初期必須是 mock transport。只能顯示 queued、sent、failed、mock-delivered 等狀態，不可以直接接真 SOS、真簡訊、真衛星或任何不可逆外部通訊。

## Phase Name

Recommended name:

```text
Phase 3.5: Runtime Readiness and Debug Tooling
```

Chinese label:

```text
Phase 3.5：硬體前置 runtime 可觀測性與除錯工具階段
```

Rationale:

- `3.5` places the work after the Phase 3 integration gate and before Phase 4
  pre-trip planning or Phase 5 hardware port work can blur the runtime
  boundary.
- `Runtime Readiness` names the purpose directly: hardware/debug/readiness
  tooling for the deterministic runtime.
- The phase is a gate before Phase 5 hardware port, not the hardware port
  itself.

Alternative names rejected:

- `Phase 4.5`: already used for departure/runtime handoff language.
- `Phase 5 pre-work`: too easy to blur into hardware port implementation.
- `Debug UI phase`: too UI-centric and easy to confuse with user-facing UX.

## Relationship to Existing Phases

### Phase 1 Relationship

Phase 1 owns live deterministic safety behavior:

- `MissionGraph`;
- observation normalization;
- route progress;
- checkpoint detection;
- recording policy;
- risk rules;
- L0-L4 state;
- `IncidentPackage`;
- `IncidentStore`.

Phase 3.5 may observe Phase 1 outputs after Phase 1 has computed them. It must
not become an input to Phase 1 decision logic.

Allowed:

- record a serialized copy of `SafetyRuntimeUpdate`;
- record route progress, checkpoint, recording policy, safety event, and
  incident persistence outcomes;
- expose read-only snapshots through `/debug`;
- compare fixture replay output with expected debug timeline output.

Not allowed:

- modify `SafetyStateMachine`;
- modify route progress thresholds;
- modify risk rules;
- modify incident ids, packages, or stored package JSON;
- call outbound transport from inside Phase 1 decision logic;
- let debug logging failures affect `/safety/observations` responses.

### Phase 2 Relationship

Phase 2 owns file-backed Brain, replay, remote status, decision support,
admin preview, and explicit skill run records.

Phase 3.5 may show Phase 2-related audit envelopes, including skill activation
gate decisions and existing `SkillRunRecord` payloads. It must preserve the
Phase 2 fact boundary.

Allowed:

- display skill run ids, skill ids, activation decisions, preflight results,
  failure policy, input refs, and output refs;
- display remote status artifacts through read-only debug views;
- display whether a model or skill output is a `ModelInterpretation`,
  `SkillRunRecord`, or reviewed artifact.

Not allowed:

- write model output as `ObservedFact`;
- automatically write `SkillRunRecord` into the Brain from debug activity;
- let `/debug` mutate Phase 2 store files;
- treat model interpretation as hardware evidence.

### Phase 3 Relationship

Phase 3 owns the disabled-by-default, post-persistence bridge from persisted
Phase 1 incident packages into Phase 2 Brain artifacts.

Phase 3.5 may display bridge attempts and results. It must preserve the Phase 3
bridge contract:

```text
Phase 1 safety decision
  -> persisted IncidentPackage JSON
  -> optional Phase 3 bridge
  -> Phase 2 Brain import
  -> replay, admin, support, audit
```

Allowed:

- record bridge result envelopes such as `skipped`, `succeeded`, or `failed`;
- show bridge skipped reasons and failure messages in `/debug/events`;
- correlate bridge events to persisted incident package paths.

Not allowed:

- enable the bridge by default;
- run bridge import before `IncidentStore.save()` succeeds;
- make bridge failure change Phase 1 response payload or state;
- add background live scanning in this phase unless a later spec explicitly
  approves it.

### Phase 4 Relationship

Phase 4 remains pre-trip planning, planning admin, route evidence, candidates,
human review, and usability.

Phase 3.5 does not plan trips. It can later consume Phase 4 output as a runtime
fixture input, but it does not create or approve planning artifacts.

Allowed:

- replay a compiled or fixture-backed `MissionGraph`;
- show whether expected planning-derived runtime artifacts were present;
- expose provider and skill readiness status for engineering inspection.

Not allowed:

- create route candidates;
- compile new MissionGraph data;
- accept human review decisions;
- mutate pre-trip project workspaces;
- implement Phase 4 portal polish under the `/debug` label.

### Phase 5 Relationship

Phase 5 hardware port should depend on Phase 3.5 acceptance.

Phase 3.5 gives Phase 5:

- fixture replay and hardware-sample replay path;
- debug timeline for runtime smoke tests;
- read-only JSON API for field debugging;
- mock outbound transport contract;
- provider degraded-state visibility;
- hardware-ready event schema.

Phase 5 owns:

- Raspberry Pi runtime packaging;
- Docker image and Compose files;
- SSD data root;
- systemd startup;
- live GNSS, IMU, BLE, cellular, LoRa, or satellite provider integrations;
- real hardware smoke tests.

Phase 3.5 must not start Phase 5 implementation.

## Tech Stack

Existing stack:

- Python;
- FastAPI for JSON APIs;
- Pydantic models;
- file-backed fixtures and stores;
- static HTML for admin-style pages;
- pytest for focused regression checks.

Preferred implementation style:

- add small Pydantic models for debug event envelopes and message envelopes;
- keep storage file-backed or memory-backed behind a narrow append/read
  interface;
- add read-only FastAPI router under `/debug`;
- add a static HTML debug page only after JSON endpoints are stable;
- avoid new dependencies unless a slice proves they are necessary.

## Commands

Focused tests for early implementation slices:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_runtime_debug_event_log.py \
  tests/test_runtime_simulator.py \
  tests/test_debug_api.py \
  tests/test_mock_outbound_transport.py
```

Safety boundary checks:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_safety_runtime_session.py \
  tests/test_safety_api.py \
  tests/test_phase1_incident_bridge.py \
  tests/test_skill_runtime.py
```

Release gate after the phase is implemented:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py \
  --repo-root /Users/alexwang0315/scout-fusion
```

Expected simulator demo shape:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python runtime_debug_replay_demo.py \
  --mission /Users/alexwang0315/scout-fusion/tests/fixtures/mission_graph/normal_climb_mission.json \
  --route /Users/alexwang0315/scout-fusion/tests/fixtures/routes/off_route_deviation.gpx \
  --incident-store /tmp/scout-debug-incidents \
  --debug-log /tmp/scout-debug-events.jsonl \
  --pretty
```

## Project Structure

Proposed files for implementation slices:

```text
runtime_debug_models.py
  Pydantic envelopes for debug events and `/debug/state` snapshots, provider status,
  skill gate visibility, and mock outbound messages.

runtime_debug_log.py
  Append-only memory-backed and file-backed debug event log.

runtime_simulator.py
  Fixture, GPX, SensorLog, and hardware-sample replay orchestration that emits
  debug timeline records from existing Phase 1 runtime outputs.

mock_outbound_transport.py
  Mock message transport and queue state model. No real SOS, SMS, satellite,
  modem, webhook, or push transport.

debug_api.py
  Read-only FastAPI router under /debug.

docs/admin/phase-3-5-runtime-debug.html
  Static debug page after JSON API is stable.

runtime_debug_replay_demo.py
  CLI demo that runs fixture replay and writes or prints debug timeline output.

runtime_debug_ui_demo.py
  Deterministic fixture-backed debug UI demo log covering provider degradation,
  L0-L4 transition, incident/bridge visibility, Ln gates, skill runs, and mock
  outbound queue state without live hardware.

phase35_debug_demo_loader.py
  Repeatable demo loader that writes the UI demo JSONL and prints the opt-in
  server command. It does not start the server or connect to live runtime inputs.

docs/admin/phase-3-5-debug-runbook.md
  Operator runbook for generating demo logs, starting the read-only debug page,
  checking JSON endpoints, and troubleshooting Phase 3.5 locally.

tests/test_runtime_debug_event_log.py
tests/test_runtime_simulator.py
tests/test_runtime_debug_ui_demo.py
tests/test_phase35_debug_runbook.py
tests/test_debug_api.py
tests/test_mock_outbound_transport.py
  Focused test coverage for this phase.
```

Existing files likely used as read points:

```text
safety_runtime_session.py
safety_api.py
replay_runner.py
phase1_replay_demo.py
phase1_incident_bridge.py
provider_context.py
communication_provider.py
skill_runtime.py
skill_runtime_integration.py
server.py
```

## Runtime Debug Event Model

The debug event log is append-only. A debug event is an observation of runtime
behavior, not a command.

Initial event kinds:

```text
observation_ingested
route_progress_evaluated
checkpoint_detected
progress_update_recorded
recording_policy_selected
safety_event_emitted
safety_transition_recorded
incident_package_created
incident_package_persisted
phase3_bridge_result
provider_status_recorded
ln_activation_gate_evaluated
skill_run_recorded
outbound_message_queued
outbound_message_state_changed
debug_session_started
debug_session_completed
```

Minimal envelope:

```json
{
  "event_id": "debug_event.20260518T120000Z.000001",
  "session_id": "debug_session.off_route_deviation.20260518T120000Z",
  "mission_id": "mission.normal_climb",
  "timestamp": "2026-05-18T12:00:00Z",
  "sequence": 1,
  "kind": "safety_event_emitted",
  "source": "runtime_simulator",
  "phase": "phase1",
  "severity": "info",
  "subject_ref": "safety_event.route_deviation.0",
  "correlation_refs": [
    "observation.gpx_replay.37",
    "incident_package.incident_abc"
  ],
  "summary": "Route deviation emitted L2 concern.",
  "payload": {
    "safety_level": "L2_CONCERN",
    "event_type": "route_deviation",
    "reason": "off route corridor threshold exceeded"
  }
}
```

Rules:

- `event_id` and `sequence` must be deterministic within a replay session.
- `payload` is a serialized copy of already-computed runtime output.
- debug log writes must be best-effort or isolated from Phase 1 behavior.
- file-backed logs should use JSONL for append-only hardware debugging.
- malformed debug log writes must not corrupt incident packages.

## Runtime State Snapshot

`/debug/state` should expose a read-only state snapshot.

Initial fields:

```json
{
  "debug_session_id": "debug_session.off_route_deviation.20260518T120000Z",
  "runtime_profile": "local-fixture",
  "safety_level": "L2_CONCERN",
  "latest_transition": {},
  "observations_processed": 128,
  "checkpoint_hits": 3,
  "segment_capsules": 2,
  "safety_events": 1,
  "incident_packages": 1,
  "stored_incidents": 1,
  "provider_status": {
    "resource": "available",
    "environment": "available",
    "communication": "degraded"
  },
  "phase3_bridge": {
    "enabled": false,
    "latest_status": "skipped"
  },
  "debug_boundary": {
    "read_only": true,
    "phase1_mutation_allowed": false,
    "phase2_writeback_allowed": false,
    "real_outbound_transport_allowed": false
  }
}
```

## Simulator Layer

The simulator layer should feed existing runtime paths and emit debug timeline
events.

Supported inputs:

- replay fixture;
- GPX;
- SensorLog JSON;
- hardware-like JSON sample;
- existing Phase 1 incident fixture for bridge visibility.

Initial simulator behavior:

1. Create a debug session.
2. Load a mission graph and selected input.
3. Convert input into observations using existing adapters when available.
4. Run observations through `SafetyRuntimeSession`.
5. Serialize each `SafetyRuntimeUpdate` into debug events.
6. Persist incidents only through existing `IncidentStore`.
7. Record Phase 3 bridge result only after persistence.
8. Optionally write debug JSONL.
9. Print or return a timeline summary.

Simulator non-goals:

- no live hardware reads;
- no real outbound transport;
- no model calls;
- no automatic Phase 2 Brain writeback;
- no MissionGraph compile.

## Outbound Message Mock

The outbound message mock records intent and delivery simulation.

Message states:

```text
queued
sent
failed
mock-delivered
cancelled
```

Initial message categories:

```text
remote_status
checkin
incident_alert
provider_degraded_notice
skill_output_notice
```

Minimal message envelope:

```json
{
  "message_id": "mock_message.incident_alert.20260518T120001Z",
  "session_id": "debug_session.off_route_deviation.20260518T120000Z",
  "created_at": "2026-05-18T12:00:01Z",
  "updated_at": "2026-05-18T12:00:02Z",
  "category": "incident_alert",
  "transport": "mock",
  "state": "mock-delivered",
  "recipient_ref": "remote_contact.primary",
  "subject_ref": "incident_package.incident_abc",
  "body_preview": "Scout would send incident alert for L2 route deviation.",
  "payload": {
    "safety_level": "L2_CONCERN",
    "incident_id": "incident_abc"
  },
  "boundary": {
    "real_sos_sent": false,
    "real_sms_sent": false,
    "real_satellite_sent": false
  }
}
```

Rules:

- mock transport is the only allowed transport in Phase 3.5;
- a message may be generated from existing runtime output, but must not change
  runtime output;
- failed mock delivery is a debug condition, not a safety condition;
- real transports require a later explicit hardware/provider spec.

## Debug JSON API

The `/debug` API must be read-only.

Initial endpoints:

```text
GET /debug/events
GET /debug/state
GET /debug/messages
GET /debug
```

Optional query parameters:

```text
/debug/events?kind=safety_event_emitted&limit=100
/debug/events?since_sequence=120
/debug/messages?state=queued
```

Rules:

- no POST, PATCH, PUT, or DELETE under `/debug` in Phase 3.5;
- `/debug` must not call `/safety/observations`;
- `/debug` must not call `/safety/ack`;
- `/debug` must not write Phase 2 Brain nodes;
- `/debug` must not trigger bridge import;
- `/debug` must not send outbound messages.

## Debug Web MVP

The web surface is a developer tool.

Required panels:

- timeline;
- event trigger / reaction / action;
- current L0-L4 safety level;
- provider degraded status;
- Ln activation gate and skill run visibility;
- outbound message queue;
- incident and bridge status.

Design constraints:

- static HTML is enough for MVP;
- read from `/debug/*` only;
- no controls that mutate runtime state;
- no planning project workspace controls;
- no user-facing product copy;
- no real transport controls.

## Code Style

Pydantic models should be narrow and explicit.

Example style:

```python
class RuntimeDebugEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    kind: RuntimeDebugEventKind
    source: str = Field(min_length=1)
    phase: Literal["phase1", "phase2", "phase3", "phase35"]
    severity: Literal["debug", "info", "warning", "error"] = "info"
    subject_ref: str | None = None
    correlation_refs: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
```

Implementation conventions:

- prefer Pydantic validation over ad hoc dictionaries at module boundaries;
- keep append-only log interfaces small;
- serialize runtime objects with `model_dump(mode="json")`;
- keep debug event construction outside safety evaluators where possible;
- use best-effort debug writes only after deterministic runtime output exists.

## Testing Strategy

Focused tests should prove both behavior and boundaries.

Required tests:

- debug event log appends events in order;
- file-backed debug log survives reload;
- simulator replay emits expected event kinds for a known GPX fixture;
- simulator replay safety level matches existing Phase 1 replay result;
- debug logging failure does not change Phase 1 safety state or response;
- `/debug/events`, `/debug/state`, and `/debug/messages` are GET-only;
- `/debug` endpoints do not mutate incident store or Brain store;
- mock outbound transport never calls real SOS, SMS, satellite, webhook, or
  provider code;
- skill run visibility remains audit-only and does not become automatic
  `ObservedFact`;
- Phase 3 bridge result is displayed only after incident persistence.

Regression tests to keep green:

- `tests/test_safety_runtime_session.py`;
- `tests/test_safety_api.py`;
- `tests/test_phase1_incident_bridge.py`;
- `tests/test_skill_runtime.py`.

## Boundaries

Always:

- keep `/debug` read-only;
- use fixture-backed simulator inputs first;
- use mock outbound transport only;
- preserve Phase 1 safety state semantics;
- keep debug writes append-only;
- record provenance and correlation refs for debug events;
- isolate debug failures from safety runtime behavior.

Ask first:

- adding a new dependency;
- mounting `/debug` by default in production-like server mode;
- writing debug events to the same data root as incident evidence;
- exposing `/debug` beyond localhost or a protected development network;
- adding live hardware providers;
- adding real SMS, SOS, satellite, webhook, cellular, LoRa, or NTN transport;
- writing any Phase 2 Brain nodes from debug tooling.

Never:

- change Phase 1 safety decision logic as part of Phase 3.5;
- make debug event data an input to route progress or risk rules;
- let `/debug` call mutation endpoints;
- make bridge import default-on;
- write model output as `ObservedFact`;
- require hardware for Phase 3.5 acceptance;
- send real outbound alerts in this phase.

## Phased Slice List

### Slice 1: Spec and Boundaries

Files:

- `docs/specs/phase-3-5-runtime-readiness-debug-tooling.md`

Acceptance:

- phase name is defined;
- relationship to Phase 1, Phase 2, Phase 3, Phase 4, and Phase 5 is explicit;
- Chinese guardrails are present;
- no runtime code is changed.

Verify:

```bash
test -s /Users/alexwang0315/scout-fusion/docs/specs/phase-3-5-runtime-readiness-debug-tooling.md
```

### Slice 2: Debug Event Schema and Log

Files:

- `runtime_debug_models.py`
- `runtime_debug_log.py`
- `tests/test_runtime_debug_event_log.py`

Acceptance:

- memory-backed append/read works;
- file-backed JSONL append/read works;
- event ids, sequence, kind, and payload validate;
- log read API can filter by kind and sequence;
- log write failure is representable without raising into Phase 1 runtime.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_runtime_debug_event_log.py
```

### Slice 3: Simulator Timeline

Files:

- `runtime_simulator.py`
- `runtime_debug_replay_demo.py`
- `tests/test_runtime_simulator.py`

Acceptance:

- GPX fixture replay emits observation, route progress, recording policy,
  safety event, and incident persistence events, and `/debug/state` can derive a
  read-only state snapshot from the timeline;
- SensorLog fixture replay is supported when fixture shape is available;
- replay output safety level matches existing Phase 1 replay output;
- no Phase 1 safety state mutation beyond normal runtime session processing.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_runtime_simulator.py
```

### Slice 4: Mock Outbound Transport

Files:

- `mock_outbound_transport.py`
- `tests/test_mock_outbound_transport.py`

Acceptance:

- message queue supports `queued`, `sent`, `failed`, and `mock-delivered`;
- every message declares mock transport;
- boundary flags prove no real SOS, SMS, or satellite send occurred;
- message state transitions append debug events.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_mock_outbound_transport.py
```

### Slice 5: Read-Only Debug JSON API

Files:

- `debug_api.py`
- optional server mount behind explicit env flag;
- `tests/test_debug_api.py`

Acceptance:

- `GET /debug/events` returns debug event envelopes;
- `GET /debug/state` returns current debug/runtime snapshot;
- `GET /debug/messages` returns mock outbound messages;
- POST/PATCH/PUT/DELETE are not implemented;
- API does not mutate `IncidentStore` or `BrainFileStore`;
- API can run without live hardware.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_debug_api.py
```

### Slice 6: Debug Web MVP

Files:

- `docs/admin/phase-3-5-runtime-debug.html`
- optional static route under `/debug` or `/admin/debug` after API is stable;
- `tests/test_debug_page.py`

Acceptance:

- timeline renders from `/debug/events`;
- current safety level renders from `/debug/state`;
- provider degraded status is visible;
- Ln gate and skill run envelopes are visible when present;
- outbound queue renders from `/debug/messages`;
- no mutation controls exist.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_debug_page.py
```

### Slice 7: Phase 3.5 Acceptance Gate

Files:

- optional `phase35_runtime_readiness_check.py`;
- `runtime_debug_ui_demo.py`;
- `tests/test_runtime_debug_ui_demo.py`;
- `phase35_debug_demo_loader.py`;
- `docs/admin/phase-3-5-debug-runbook.md`;
- `tests/test_phase35_debug_runbook.py`;
- focused release-check integration only after slices are stable.

Acceptance:

- focused tests pass;
- fixture replay demo produces a timeline;
- fixture-backed UI demo covers provider degraded/recovered, L0->L2 transition,
  incident package creation/persistence, Phase 3 bridge skipped/imported, Ln
  gate allowed/blocked, skill run started/completed/failed, and mock outbound
  queued/sent/mock-delivered states;
- demo loader writes a repeatable JSONL log and prints the exact opt-in server
  command for `/admin/debug`;
- runbook documents demo generation, read-only JSON endpoints, common local
  failures, and Phase 3.5 boundary warnings;
- no mutation of Phase 1 safety state by debug tooling;
- no model output written as `ObservedFact`;
- no hardware dependency required;
- no real outbound transport used;
- existing Phase 3 release check remains `ok: true`.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_runtime_debug_event_log.py \
  tests/test_runtime_simulator.py \
  tests/test_runtime_debug_ui_demo.py \
  tests/test_phase35_debug_runbook.py \
  tests/test_mock_outbound_transport.py \
  tests/test_debug_api.py \
  tests/test_safety_runtime_session.py \
  tests/test_safety_api.py \
  tests/test_phase1_incident_bridge.py \
  tests/test_skill_runtime.py

/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py \
  --repo-root /Users/alexwang0315/scout-fusion
```

### Slice 8: Opt-In Server Mount

Files:

- `server.py`
- `debug_api.py`
- `tests/test_debug_api_mount.py`

Acceptance:

- `/debug/events`, `/debug/state`, `/debug/messages`, and `/admin/debug` are
  not mounted by default;
- setting `SCOUT_DEBUG_API_ENABLED=1` mounts the read-only debug JSON API and
  the static debug page;
- setting `SCOUT_DEBUG_LOG_PATH=/path/to/runtime-debug-events.jsonl` makes the
  mounted debug API read a file-backed replay timeline;
- `/debug` mutation methods remain unsupported;
- existing `/admin`, `/safety/*`, and `/pdr/update` routes remain registered;
- the mount uses an empty debug log by default and does not attach to Phase 1
  safety decision paths.

Verify:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_debug_api_mount.py
```

## Success Criteria

Phase 3.5 is complete when:

- the spec is accepted;
- simulator replay can produce a deterministic runtime debug timeline;
- `/debug/events`, `/debug/state`, and `/debug/messages` expose read-only JSON;
- debug web MVP shows timeline, L0-L4 state, provider status, skill gate
  visibility, and outbound mock queue;
- focused tests prove debug tooling does not mutate Phase 1 safety state;
- focused tests prove debug tooling does not write model output as
  `ObservedFact`;
- focused tests prove outbound transport is mock-only;
- no live hardware, Docker, Pi, satellite, SMS, or SOS dependency is required;
- existing Phase 1/2/3 regression gates remain green.

## Resolved Phase 3.5 Defaults

- `/debug` and `/admin/debug` are mounted only when
  `SCOUT_DEBUG_API_ENABLED=1`.
- File-backed debug logs are provided by `SCOUT_DEBUG_LOG_PATH`; the repeatable
  local demo uses `/tmp/scout-phase35-ui-demo.jsonl`.
- Debug sessions are represented as append-only JSONL events. One-file-per-run
  is preferred for demo and fixture replay.
- Mock outbound messages are surfaced through explicit mock transport or fixture
  demo events. No automatic real escalation is part of Phase 3.5.
- Ln activation visibility is represented by debug envelopes first. Later
  hardware/runtime ports can map concrete skill runtime sources into the same
  envelope.
- Phase 3.5 owns `phase35_runtime_readiness_check.py`; it remains separate from
  Phase 4 planning gates and does not expand Phase 3 live bridge behavior.
