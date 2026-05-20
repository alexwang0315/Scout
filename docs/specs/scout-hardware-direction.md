# Spec: Scout Hardware Direction

## Objective

Define the hardware direction for Scout without making hardware a blocker for
the current Phase 1 safety runtime.

Scout should remain a wilderness safety black box first. Hardware choices must
serve auditable field safety: reliable position evidence, motion evidence,
local recording, low-power operation, controlled alerting, and recoverable
communication under weak-network conditions.

This document captures the current hardware discussion around multi-radio
connectivity, edge AI modules, GNSS, cellular, LoRa, and satellite NTN, and
turns it into Scout-specific product constraints.

## Design Position

Scout should not start as one large all-in-one AI computer.

The practical architecture is layered:

1. A field device or wearable logger that is small, low-power, and safety
   reliable.
2. A phone bridge that can provide UI, richer connectivity, and user control
   when available.
3. An optional edge base node for heavier compute, team coordination, local
   replay, and remote sync.

The field device must remain useful when the phone, cloud, 5G, satellite, and
local AI are unavailable.

## Hardware Tiers

### Tier 0: Current Prototype Baseline

Current software validation should continue to use:

- Apple Watch and iPhone SensorLog data;
- GPX and GeoJSON route/map fixtures;
- Mac-based replay and FastAPI runtime;
- fixture-backed communication/resource/environment providers.

Purpose:

- validate safety semantics;
- prove route progress and incident package behavior;
- avoid premature device-port churn.

This tier is still the source of truth for Phase 1 behavior.

### Tier 1: Minimum Credible Field Device

This is the first real Scout hardware target.

Required capabilities:

- GNSS receiver for position evidence and field timestamp authority;
- IMU for motion/PDR continuity;
- local storage for raw ring buffer, sealed segment capsules, and incident
  packages;
- battery telemetry;
- physical alert/ack input;
- BLE connection to a phone or nearby device;
- local buzzer, vibration, LED, or screen indicator for user feedback.

Recommended optional capabilities:

- barometer for elevation trend and weather context;
- LoRa or sub-GHz radio for low-rate nearby/team beacon;
- LTE-M, NB-IoT, or LTE Cat-1 for low-rate remote status;
- eSIM/iSIM if cellular certification and roaming become important.

Non-goals:

- on-device large LLM inference;
- computer vision as a required safety dependency;
- 5G broadband as a v1 requirement;
- satellite as a v1 requirement;
- full offline map rendering on the device.

### Tier 2: Phone Bridge

The phone bridge should handle richer workflows while keeping Phase 1 safety
deterministic.

Responsibilities:

- mission setup and route selection;
- user-facing check-ins and acknowledgement;
- map display;
- sync when cellular or Wi-Fi is available;
- emergency message composition from incident package evidence;
- optional satellite SOS pathway when the phone platform supports it.

The phone can improve communication, but Scout should not require the phone for
local recording, route-progress evaluation, or incident package creation.

### Tier 3: Edge Base Node

An edge base node is useful for team missions, vehicles, camps, drones, or
search-and-rescue operations. This is not the first wearable field device.

Candidate compute:

- Jetson Orin Nano for entry-level edge AI experiments;
- Jetson Orin NX or an industrial reComputer-class box for deployable edge
  compute;
- Mac mini, Ryzen AI, or other base-station compute for development and
  mission replay.

Candidate connectivity:

- Wi-Fi 6/7;
- Bluetooth LE;
- 4G/5G modem;
- GNSS;
- optional LoRa gateway;
- optional satellite NTN or separate satellite terminal.

Responsibilities:

- aggregate team status;
- run heavier replay and case analysis;
- host local mission data when cloud is unavailable;
- bridge field devices to remote observers;
- run non-critical local AI summarization or vision tasks.

Edge base compute must not become part of the Phase 1 emergency authority.

## Communication Strategy

Scout should treat communication as a capability ladder, not a single required
network.

### Local and Personal Area

Use for:

- field device to phone;
- field device to nearby team member;
- low-power acknowledgement and data pull.

Candidates:

- Bluetooth LE for phone and wearable links;
- LoRa or LoRaWAN for long-range low-rate beacon/check-in;
- UWB only if precise nearby ranging becomes a real requirement.

### Wide Area Cellular

Use for:

- remote status JSON;
- check-ins;
- incident package metadata;
- delayed sync.

Candidates:

- LTE-M or NB-IoT for low-power telemetry;
- LTE Cat-1 or Cat-4 for broader availability and higher bandwidth;
- 5G only for edge base nodes or high-bandwidth workflows.

Cellular should degrade gracefully. Missing cellular coverage should trigger
communication risk evidence, not disable safety evaluation.

### Satellite and NTN

Satellite should be treated as a future backup path, not the first product
dependency.

Two categories matter:

- phone-platform satellite SOS or direct-to-cell features;
- industrial 3GPP NTN IoT modules for low-rate remote telemetry.

Scout should watch this space, but the v1 software contract should only require
an abstract communication provider that can report:

- available/unavailable;
- latency class;
- bandwidth class;
- confidence;
- last successful send time;
- supported message types.

The safety runtime should not depend on a specific satellite vendor.

## Sensor Strategy

Minimum sensor set:

- GNSS position, speed, course, timestamp, and accuracy;
- IMU acceleration and rotation rate;
- battery level and charging state;
- communication state;
- user acknowledgement input.

GNSS is mandatory, not optional, because it provides the field timestamp
baseline as well as position. Scout should prefer authenticated/validated GNSS
time for mission timelines, segment capsules, incident packages, and replay
alignment. Device wall-clock time and monotonic local sequence numbers are still
useful for ordering and degraded operation, but they should not silently replace
GNSS time when GNSS is available.

中文註釋：這裡用 `GNSS` 而不是只寫 `GPS`，是為了涵蓋 GPS、QZSS、Galileo、GLONASS、BeiDou 等衛星系統。Scout 的最低硬體能力仍然是「要有衛星定位與衛星時間來源」。

Useful later:

- barometer;
- temperature;
- heart rate when available from a paired wearable;
- microphone or camera only for explicitly enabled evidence capture;
- radio signal scans as a separate evidence producer.

Sensor ingestion should preserve raw evidence where possible and derive
deterministic measurements separately. Interpretations such as fatigue,
attention, panic, or intent should not be automatic Phase 1 facts.

### Host-Side Radio Scan Tools

The first Pi radio evidence tools live outside the Docker safety runtime:

```text
wifi_scan_provider.py       -> parses `iw` dBm RSSI and `nmcli` fallback scans
ble_scan_provider.py        -> parses `btmgmt find` BLE RSSI scans
radio_scan_provider.py      -> combines Wi-Fi + BLE into one radio_environment_scan
tools/pi_wifi_scan_smoke.py  -> read-only Wi-Fi-only host smoke CLI
tools/pi_ble_scan_smoke.py   -> read-only BLE-only host smoke CLI
tools/pi_radio_scan_smoke.py -> read-only Pi host smoke CLI
```

中文註釋：這些工具是「現場 radio evidence producer」，不是 Phase 1 safety
evaluator。Wi-Fi scan 比較適合地點/radio fingerprint；BLE scan 比較適合
proximity / team beacon evidence。BLE 的 LE Random address 不應被當成穩定身份。

Developer smoke command on the Pi host:

```bash
sudo python3 tools/pi_radio_scan_smoke.py \
  --wifi-interface wlan0 \
  --ble-controller hci0 \
  --ble-duration-seconds 10 \
  --output-jsonl /data/scout/providers/radio_scan/manual-smoke.jsonl
```

The output is append-only JSONL when `--output-jsonl` is provided. The payload
includes a fixed read-only `boundary` block and validates `radio_counts`
against the Wi-Fi/BLE payload before writing. It may be attached later as
`server_signal_snapshot` / provider-state evidence, but the tool itself must
not call `/safety/observations`, write IncidentStore, write ObservedFact, write
Brain records, send outbound messages, control hardware providers, or change Phase 1 safety decisions.

## Phase Boundaries

### Phase 1

Phase 1 remains hardware-agnostic and deterministic.

Allowed:

- define provider interfaces for hardware observations;
- replay hardware-like fixtures;
- record communication state as evidence;
- preserve incident packages and segment capsules;
- add hardware fields to observations if they are deterministic and tested.

Not allowed:

- make live modem, satellite, Jetson, or cloud availability required for
  L0-L4 safety logic;
- allow AI or edge base compute to directly trigger emergency escalation;
- rewrite incident packages to fit hardware-specific assumptions.

### Phase 2

Phase 2 may read hardware evidence after Phase 1 persists it.

Allowed:

- team status and remote observer summaries;
- fact-only writeback for device observations;
- option sets for communication fallback;
- hardware capability registry entries with preconditions and failure modes.

Not allowed:

- treating hardware model interpretations as observed facts;
- changing Phase 1 route-progress, recording, or escalation semantics.

### Phase 3

Phase 3 may integrate optional bridge behavior.

Allowed:

- disabled-by-default bridges for persisted incident packages;
- release gates for fixture-backed hardware cases;
- admin visibility into hardware evidence provenance.

Not allowed:

- background live bridge behavior enabled by default;
- direct coupling between hardware transport and Phase 1 emergency authority.

### Phase 4 and Later

Pre-trip planning and hardware readiness can combine in Phase 4.

Examples:

- verify battery and modem readiness before departure;
- choose route check-in policy based on expected coverage;
- generate a communication fallback plan;
- compile hardware-specific mission bundles.

Phase 4 planning and after-action/admin user workflows may be driven from a
Mac or PC admin workstation, but the Scout core server/service can still run on
Scout hardware. In this model, the Mac/PC connects to Scout's web service or
admin API to execute pre-trip and post-replay workflows against the Scout node.

### Prototype Deployment Phase

Assign a dedicated future phase for real hardware prototype deployment. This
phase should happen after the deterministic software contract is stable enough
to test on physical Pi hardware.

This phase owns:

- Docker packaging for the field runtime;
- Pi hardware smoke tests;
- service orchestration experiments;
- remote deployment mechanics;
- event bus integration;
- tiny local inference experiments;
- accelerator experiments;
- the final decision about whether Jetson-class GPU compute is actually
  needed.

This phase does not own:

- Phase 4 pre-trip planning;
- the Mac/PC admin client experience;
- workstation-local report authoring and heavy analysis;
- broad AI planning workflows;
- changing Phase 1 safety semantics to fit hardware.

Pi should be treated as the Scout service/runtime node. Mac/PC should remain
the planning, analysis, and admin workstation that connects to Scout services.

## Pi Runtime and Development Environment Spec

### Execution Topology

Scout hardware should run the core server/service. Mac and PC machines should
act as admin workstations that connect to Scout over web/admin APIs.

Scout node responsibilities:

- Phase 1 safety runtime;
- `/safety/observations` ingest;
- route progress and L0-L4 evaluation;
- raw ring buffer, `SegmentCapsule`, and `IncidentPackage` persistence;
- communication/resource/environment provider services;
- pre-trip and post-replay service endpoints when those workflows are exposed
  through Scout;
- local health and retrieval endpoints;
- optional event bus, tiny inference, and accelerator services in later
  deployment steps.

Mac/PC responsibilities:

- developer workstation;
- browser/admin client;
- route and fixture preparation;
- test orchestration and release validation;
- heavy report authoring;
- local after-action review UI when it does not need to run on Scout;
- connecting to Scout web/admin APIs for pre-trip and post-replay workflows.

The key boundary is service placement, not workflow ownership: Phase 4 and
admin workflows may be initiated from Mac/PC, while the Scout node can still
host the backing services and persisted mission evidence.

### Pi 5 Baseline Runtime

The first deployable Pi target should be intentionally small:

```text
Raspberry Pi 5
64-bit Raspberry Pi OS Lite
Docker Engine + Docker Compose
arm64 Python runtime image
external SSD mounted as Scout data root
systemd-managed Docker Compose startup
```

Required runtime properties:

- 64-bit OS and userspace;
- arm64 container images;
- persistent data mounted outside the container;
- no requirement for network access after mission start;
- no workstation-only dependencies in the field runtime image;
- restart-safe file writes for incident and capsule artifacts;
- explicit health checks for runtime, storage, and provider status.

Recommended storage layout:

```text
/data/scout/
  missions/
  incidents/
  capsules/
  raw_ring/
  logs/
  providers/
  tmp/
```

The Pi may boot from microSD, but mission evidence should be written to SSD.
The raw ring buffer, incident packages, segment capsules, and logs should not
depend on long-running high-frequency writes to microSD.

### First Docker Slice

The first Docker slice should prove the deterministic core only.

Container contents:

- Python 3.11 or 3.12;
- FastAPI and uvicorn;
- Pydantic models;
- route, mission, safety, incident, and provider modules;
- GPX/GeoJSON parsing needed by the runtime;
- file-based persistence.

Container exclusions:

- local large LLM runtimes;
- vision AI dependencies;
- SciPy/visualization-only tools unless the runtime proves it needs them;
- macOS-only Wi-Fi scanning;
- workstation report tooling;
- Phase 4 heavy analysis workers;
- GPU or TPU runtime packages.

Required endpoints or commands:

- health check endpoint;
- `/safety/observations` smoke ingest;
- fixture replay command;
- incident package retrieval;
- persisted data root inspection.

Acceptance:

- image builds for `linux/arm64`;
- container starts on Pi 5;
- replay fixture completes on Pi hardware;
- `/safety/observations` accepts a normalized observation;
- incident package persists under the mounted data root;
- restart does not corrupt the persisted package;
- runtime can start without OpenRouter, cloud credentials, Jetson, Coral TPU,
  or satellite/cellular hardware.

### Intel Mac to Pi Migration

Moving from an Intel Mac developer environment to Pi 5 should be treated as an
`x86_64 macOS` to `arm64 Linux` migration.

Expected difficulty: medium-low for the deterministic Scout core, higher for
hardware drivers and native dependencies.

Main migration risks:

- Docker images built on Intel Mac defaulting to `linux/amd64`;
- native Python wheels missing or building slowly on arm64;
- import-time failures from macOS-only modules;
- filesystem and permission differences in mounted volumes;
- different serial, USB, BLE, modem, or GPIO device paths;
- accidental inclusion of workstation-only dependencies in the field image.

Rules:

- build multi-arch images with `docker buildx` or build directly on the Pi;
- keep the field runtime dependency set minimal;
- make hardware providers optional at import time;
- keep `macos_wifi.py` and similar host-specific modules behind provider
  boundaries;
- prefer fixture-backed providers before live hardware providers;
- treat live GNSS, IMU, BLE, LoRa, LTE, NTN, Coral, and Jetson integrations as
  separate capability slices;
- avoid coupling Phase 1 safety semantics to any host-specific API.

### Dependency Partitioning

Scout should maintain separate dependency profiles:

| Profile | Target | Contents |
| --- | --- | --- |
| `runtime-core` | Pi field runtime | FastAPI, uvicorn, Pydantic, route/safety/incident logic |
| `runtime-providers` | Pi hardware adapters | GNSS, IMU, BLE, LoRa, LTE provider libraries when needed |
| `admin-workstation` | Mac/PC | browser/admin client, report tooling, heavy analysis |
| `test-dev` | Mac/PC and CI | pytest, fixtures, validators, release checks |
| `ai-experimental` | Later Pi/Jetson slices | tiny inference, Coral, Jetson, model tooling |

The Pi Docker image for Step 1 should only include `runtime-core` plus
fixture-backed providers. Other profiles should be added only when the roadmap
step explicitly needs them.

### Development Workflow

Recommended workflow:

1. Develop and run broad tests on Mac/PC.
2. Build the arm64 runtime image.
3. Deploy to Pi 5 with Docker Compose.
4. Run Pi smoke tests against fixture data.
5. Persist incident/capsule output to SSD.
6. Pull artifacts back to Mac/PC for admin review and post-replay analysis.
7. Only then add live hardware providers.

The Pi should be validated as a deployment target, not used as the primary
development workstation.

### Pi Smoke Test Ladder

The first Pi acceptance ladder should be small and repeatable:

```text
docker compose -f docker-compose.pi.yml up -d
curl http://scout.local:PORT/health
curl -X POST http://scout.local:PORT/safety/observations ...
docker compose -f docker-compose.pi.yml exec scout python phase1_replay_demo.py ...
ls /data/scout/incidents
docker compose -f docker-compose.pi.yml restart scout
curl http://scout.local:PORT/safety/incidents/<incident_id>
```

Expected result:

- health endpoint reports runtime and data root status;
- observation ingest returns success or a deterministic validation error;
- replay creates expected safety events;
- incident package is visible on SSD;
- restart preserves persisted state;
- missing optional hardware providers degrade to unavailable status instead of
  crashing startup.

### Environment Variables

Minimum runtime variables:

```text
SCOUT_DATA_ROOT=/data/scout
SCOUT_RUNTIME_PROFILE=pi-field
SCOUT_ENABLE_LIVE_HARDWARE=0
SCOUT_ENABLE_AI_INFERENCE=0
SCOUT_AI_FALLBACK_MODE=offline_only
SCOUT_LOG_LEVEL=info
```

Later optional variables:

```text
SCOUT_PROVIDER_GNSS=fixture|serial|gpsd
SCOUT_PROVIDER_IMU=fixture|ble|serial
SCOUT_PROVIDER_COMMS=fixture|ble|lora|lte|ntn
SCOUT_EVENT_BUS=none|mqtt|nats
SCOUT_AI_ACCELERATOR=none|cpu|coral|jetson
SCOUT_AI_NETWORK_POLICY=online_disabled|offline_fallback|online_allowed
```

Defaults should be fixture-backed and safe. Live hardware should be opt-in.
Local AI inference should default to offline fallback only, not the normal
decision path.

### Non-Goals for Pi Step 1

- k3s;
- MQTT or NATS;
- local AI inference;
- Coral TPU;
- Jetson;
- camera or vision pipelines;
- satellite integration;
- live cellular modem integration;
- workstation report generation;
- changing Phase 1 safety semantics.

These are later roadmap steps and should only be added after the Docker field
runtime is stable on Pi hardware.

## Prototype Deployment Roadmap

### Step 1: Pi 5 + Docker

Goal:

- prove Scout's deterministic field runtime can run on Raspberry Pi 5.

Scope:

- `/safety/observations` ingest;
- route-progress evaluation;
- L0-L4 safety state transitions;
- raw ring buffer;
- `SegmentCapsule` and `IncidentPackage` persistence;
- lightweight local health and retrieval endpoints;
- fixture-backed communication providers.

Acceptance:

- container starts without workstation-only dependencies;
- replay fixture completes on Pi hardware;
- incident package can be created and persisted offline;
- CPU, memory, disk write, and temperature remain within field limits.

### Step 2: k3s

Goal:

- introduce service orchestration and remote deployment only after Docker is
  stable.

Scope:

- split field runtime, communication provider, and retrieval endpoint into
  deployable services if there is a real operational reason;
- define remote update and rollback behavior;
- test restart behavior under power loss.

Acceptance:

- service restart does not corrupt persisted mission evidence;
- deployment rollback is possible;
- orchestration adds operational value instead of complexity only.

### Step 3: MQTT or NATS

Goal:

- introduce an event-driven architecture after service boundaries are clear.

Scope:

- observation events;
- safety transition events;
- segment capsule events;
- incident package events;
- communication status events.

Acceptance:

- the safety state machine remains deterministic;
- event replay is possible from persisted evidence;
- message loss or broker downtime degrades safely.

### Step 4: Tiny AI Inference

Goal:

- test whether small local inference adds value as an offline fallback when
  network/cloud inference is unavailable, without becoming emergency authority.

Scope:

- tiny model summarization, classification, or anomaly hints during degraded
  connectivity;
- read-only model outputs;
- explicit provenance and confidence metadata;
- explicit trigger policy for when local inference is allowed, such as no
  network, cloud unavailable, or remote model timeout.

Acceptance:

- inference can be disabled without breaking Phase 1;
- outputs are stored as interpretations, not observed facts;
- local model outputs never replace deterministic L0-L4 safety rules;
- the runtime records whether the output came from offline fallback mode;
- local fallback is tested with network-disabled fixtures;
- latency and power draw are measured on Pi hardware.

Current prototype evidence:

- `qwen2.5:0.5b` and `qwen2.5:1.5b` were tested on Raspberry Pi 5 through
  Ollama in Docker;
- CPU-only inference worked without GPU, Coral TPU, or Jetson;
- a 4-worker Ollama stress test reached `60.4°C` maximum temperature with no
  errors and no swap usage for `qwen2.5:0.5b`;
- a combined test with Ollama stress plus three Phase 1 replays kept
  `scout-runtime` healthy and reproduced the expected `L2_CONCERN`
  `route_deviation` result for both tested models;
- the `qwen2.5:0.5b` combined test reached `62.0°C` maximum temperature and
  kept about `14 GiB` memory available;
- the `qwen2.5:1.5b` 1-worker fallback test reached `60.9°C` maximum
  temperature with `13.348s` average latency;
- the `qwen2.5:1.5b` combined test reached `61.5°C` maximum temperature,
  preserved Scout replay health, and showed that the main cost is latency
  under CPU contention.

Decision:

- Pi 5 is sufficient as the current prototype runtime hardware baseline for
  deterministic Scout runtime plus low-frequency tiny-model offline fallback;
- `qwen2.5:0.5b` is the better fast fallback candidate;
- `qwen2.5:1.5b` is viable as a better-interpretation candidate when Scout can
  tolerate a longer timeout and short fixed-schema output;
- local inference should be limited to one active request, model-specific
  timeouts, and read-only `model_interpretation` output;
- local inference must not change L0-L4 safety state or directly trigger SOS,
  evacuation, or route-deviation decisions.

Detailed evidence is recorded in
`docs/specs/pi5-local-ai-runtime-experiment.md`.

Committed operator assets:

- `docker-compose.pi.ai.yml` is the optional Pi/Ollama service definition and
  requires the `ai-experimental` Compose profile.
- `tools/pi_ollama_stress.py` is the manual stress probe used to sample
  Ollama latency, Pi temperature, and load from an already-running listener.

These assets are not part of the assistant readiness gate. They stay in the
hardware prototype track and preserve read-only model interpretation semantics:
不啟動本地模型 from readiness checks, 不呼叫 `/safety/*` mutation, no Scout state
writes, no outbound send, and no hardware/provider control.

### Step 5: Coral TPU

Goal:

- measure whether an accelerator improves latency or power for the tiny model
  path.

Scope:

- same tiny inference tasks as Step 4;
- Coral TPU only as an optional accelerator;
- side-by-side CPU versus TPU measurements.

Acceptance:

- power draw improves or latency improves enough to justify hardware
  complexity;
- fallback to CPU remains available;
- safety runtime remains independent from accelerator availability.

### Step 6: Jetson

Goal:

- move to Jetson only after measurements show where GPU-class compute is truly
  needed.

Scope:

- heavier vision or multi-model inference;
- edge base node workflows;
- team/camp/vehicle hub workloads.

Acceptance:

- Pi measurements identify a concrete bottleneck;
- the workload genuinely needs GPU-class compute;
- Jetson does not replace the Pi field-runtime baseline unless there is a
  field-tested reason.

## Candidate Prototype Matrix

| Prototype | Goal | Hardware Shape | Scout Role |
| --- | --- | --- | --- |
| Watch/iPhone replay | Validate semantics | Existing Apple devices | Phase 1 truth source |
| Phone-linked field logger | Minimum credible field device | GNSS + IMU + BLE + storage | v1 hardware target |
| Pi 5 Docker node | Deterministic field runtime | Pi 5 + Docker + SSD | Prototype deployment baseline |
| Pi 5 k3s node | Field service orchestration | Pi 5 + k3s | Remote deployment experiment |
| Pi event bus | Event-driven field runtime | Pi 5 + MQTT/NATS | Optional event architecture |
| Pi tiny inference | Local interpretation experiment | Pi 5 CPU + Ollama `qwen2.5:0.5b` / `qwen2.5:1.5b` | Accepted prototype baseline for low-frequency offline fallback |
| Pi Coral TPU | Low-power inference accelerator | Pi 5 + Coral TPU | Measure power/latency tradeoff |
| LoRa team beacon | Nearby low-rate backup | Field logger + LoRa | Phase 2 team awareness |
| Cellular telemetry unit | Remote check-in | LTE-M/NB-IoT/Cat-1 + eSIM | Remote status provider |
| Edge base node | Team/camp/vehicle hub | Jetson/Mac mini + 5G/Wi-Fi | Optional Phase 2/3 hub |
| Jetson node | GPU-class edge compute | Jetson Orin | Only after measured Pi bottleneck |
| NTN experiment | Remote no-cell backup | NTN IoT module or phone satellite | Later communication provider |

## Hardware Capability Registry Direction

Hardware integrations should be described as capabilities, not hardcoded
assumptions.

Each capability should declare:

- capability id;
- device class;
- transport;
- required permissions;
- expected power draw class;
- sampling rate or message rate;
- failure modes;
- degraded behavior;
- evidence fields emitted into Scout;
- whether it is allowed in Phase 1 safety logic.

Example capability ids:

- `gnss.position`;
- `imu.motion`;
- `battery.status`;
- `ble.phone_bridge`;
- `lora.team_beacon`;
- `cellular.remote_status`;
- `satellite.ntn_status`;
- `edge_base.team_hub`;
- `camera.evidence_capture`.

## Acceptance Criteria

Before Scout commits to a hardware target, it should pass these checks:

- Phase 1 replay behavior remains deterministic without the hardware connected.
- Hardware loss creates evidence and degraded modes, not runtime failure.
- Incident package creation works offline.
- The raw ring buffer and segment capsule policy fit the device storage budget.
- Battery telemetry can influence resource-aware go/no-go decisions.
- Communication state can be represented through the provider interface.
- The hardware capability is testable through fixtures.
- The user can acknowledge, pause, or cancel an alert locally.
- Any AI or edge-base feature is optional and audit-separated from emergency
  authority.

## Open Questions

- Is the first real Scout device phone-linked or standalone?
- Should LoRa be a v1 team feature or a later search-and-rescue feature?
- Which cellular class is the best first target in Taiwan mountain conditions:
  LTE-M, NB-IoT, LTE Cat-1, or Cat-4?
- What is the minimum acceptable battery life for a field mission?
- What physical alert and acknowledgement controls are required in rain,
  gloves, darkness, and stress?
- Should barometer be mandatory for elevation-aware trail safety?
- How much raw evidence must be retained locally after an L2 incident?
- Which hardware capability should become the first fixture-backed integration
  test?

## Recommended Next Slice

Do not start with Jetson or satellite.

Start with a `HardwareCapability` / `CommunicationCapability` spec slice:

1. Define a small capability manifest schema.
2. Add fixture-backed examples for GNSS, IMU, battery, BLE bridge, and cellular
   remote status.
3. Verify that Phase 1 can consume normalized observations without knowing the
   device model.
4. Keep the live hardware implementation out of scope until the fixture
   contract is stable.
