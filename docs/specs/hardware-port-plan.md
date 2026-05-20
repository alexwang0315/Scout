# Plan: Scout Hardware Port

## Goal

Move Scout from the Mac-based replay/server prototype toward a real field
runtime without letting Phase 4 pre-trip UI work block the hardware path.

中文註釋：這份文件的目標不是設計新的 UI，也不是改寫安全判斷邏輯，而是把已完成的 Scout Phase 1 deterministic safety baseline 移植到硬體上跑。

The first hardware-port goal is:

- run the deterministic Scout field runtime on Raspberry Pi 5;
- keep Phase 1 as the live safety baseline;
- keep Phase 2 and Phase 3 as evidence, replay, admin, manifest, and sync
  layers;
- keep Phase 4 pre-trip planning as a UI/usability track, not a blocker for
  hardware deployment.

中文註釋：Phase 4 可以繼續做 pre-trip planning 和 admin usability，但硬體移植不需要等 Phase 4 完成。

## Source Direction

This plan follows `docs/specs/scout-hardware-direction.md`.

Key decisions inherited from that direction:

- do not start with one large all-in-one AI computer;
- do not start with Jetson, satellite, k3s, MQTT/NATS, Coral TPU, or local LLM
  inference;
- start with Raspberry Pi 5 + Docker + external SSD;
- treat Mac/PC as admin workstation, test orchestrator, route authoring, and
  after-action review client;
- treat Pi as the Scout service/runtime node;
- make live hardware providers opt-in and fixture-backed first;
- keep hardware loss as evidence and degraded mode, not runtime failure.

中文註釋：第一個硬體 port 不是要做「最強 AI 邊緣電腦」，而是要證明 Scout 的安全核心能在低功耗、可攜、可重開機的硬體上穩定運作。

## Track Boundary

### Phase 4 UI / Usability Track

Phase 4 may own:

- pre-trip planning UI;
- route setup usability;
- admin workflow polish;
- planning and after-action browser flows;
- Mac/PC workstation UX.

Phase 4 must not block:

- Pi runtime packaging;
- Phase 1 safety runtime portability;
- fixture-backed hardware provider contracts;
- incident package persistence on hardware;
- hardware smoke tests.

中文註釋：Phase 4 是「人怎麼使用 Scout 比較順」；hardware port 是「Scout 核心怎麼在硬體上可靠地跑」。兩者可以互相支援，但不應互相卡住。

### Hardware Port Track

The hardware port track owns:

- runtime portability audit;
- Docker runtime packaging;
- Pi 5 startup and health checks;
- persistent data root layout;
- fixture-backed hardware provider contracts;
- Pi smoke-test ladder;
- deployment notes for field runtime.

The hardware port track does not own:

- Phase 4 pre-trip UI implementation;
- workstation report generation;
- broad AI planning workflows;
- changing Phase 1 safety semantics;
- making modem, satellite, Jetson, Coral, or cloud access required.

中文註釋：硬體 port 只應把現有安全核心搬到硬體，不應順手把產品 UI、AI planning、衛星、Jetson 等新範圍一起塞進來。

## First Hardware Target

First deployable target:

```text
Raspberry Pi 5
64-bit Raspberry Pi OS Lite
Docker Engine + Docker Compose
arm64 Python runtime image
external SSD mounted as Scout data root
systemd-managed Docker Compose startup
```

中文註釋：Pi 5 是第一個 deployment baseline。它不是最終產品外型，也不是 wearable v1，但它可以最快驗證 Scout runtime 是否能離開 Mac 穩定運作。

Required runtime properties:

- 64-bit OS and userspace;
- Linux arm64 container image;
- persistent data mounted outside the container;
- runtime starts without OpenRouter, cloud credentials, Jetson, Coral TPU,
  cellular modem, satellite module, or live GNSS hardware;
- optional hardware providers degrade to unavailable instead of crashing;
- incident and capsule writes survive service restart.

## Service Placement

### Scout Pi Node Responsibilities

The Pi node should run:

- Phase 1 safety runtime;
- `/safety/observations` ingest;
- route progress and L0-L4 evaluation;
- raw ring buffer;
- `SegmentCapsule` persistence;
- `IncidentPackage` persistence;
- incident retrieval endpoints;
- lightweight health endpoint;
- fixture-backed communication/resource/environment providers;
- optional Phase 3 post-persistence bridge when explicitly enabled.

中文註釋：Pi 上要先跑的是 Scout 的 field runtime，不是完整 admin workstation，也不是大型 AI 分析平台。

### Mac/PC Workstation Responsibilities

Mac/PC should handle:

- developer workflow;
- broad test execution;
- browser/admin client;
- route and fixture preparation;
- release validation;
- heavy report authoring;
- after-action review when it can run as a client against Scout APIs;
- artifact pull-back from Pi for review.

中文註釋：Mac/PC 不消失，而是從「Scout runtime host」退回「開發、規劃、分析、管理工作站」角色。

## Runtime Data Layout

Recommended mounted data root:

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

Rules:

- mission evidence should be written to SSD, not high-frequency microSD writes;
- incident JSON, capsules, raw-window artifacts, and logs must be outside the
  container image;
- writes must be restart-safe;
- missing optional provider data should be represented as unavailable evidence.

中文註釋：硬體上最重要的是斷電、重開機、無網路後證據還在；所以資料目錄與寫入策略是第一級需求。

## Dependency Profiles

Scout should split dependencies by deployment use:

| Profile | Target | Contents |
| --- | --- | --- |
| `runtime-core` | Pi field runtime | FastAPI, uvicorn, Pydantic, route/safety/incident logic |
| `runtime-providers` | Pi hardware adapters | GNSS, IMU, BLE, LoRa, LTE provider libraries when needed |
| `admin-workstation` | Mac/PC | browser/admin client, report tooling, heavy analysis |
| `test-dev` | Mac/PC and CI | pytest, fixtures, validators, release checks |
| `ai-experimental` | Later Pi/Jetson slices | tiny inference, Coral, Jetson, model tooling |

Step 1 Docker image should include only:

- `runtime-core`;
- fixture-backed providers needed by tests and smoke commands.

Step 1 Docker image should exclude:

- local large LLM runtimes;
- vision AI dependencies;
- SciPy/visualization-only tools unless runtime proves it needs them;
- macOS-only Wi-Fi scanning;
- workstation report tooling;
- Phase 4 heavy analysis workers;
- GPU or TPU packages.

中文註釋：先讓 deterministic core 跑起來。不要因為裝 AI、影像、報表、macOS Wi-Fi 等套件讓 Pi image 變重或不能啟動。

## Required Hardware-Port Slices

### Slice 0: Hardware Prototype Prep

Goal:

- prepare a target profile and manual smoke ladder before touching a Scout
  machine.

Scope:

- offline target profile validation;
- manual-only smoke checklist;
- no Pi connection;
- no Docker startup;
- no local model startup;
- no live `/safety/*` mutation;
- no outbound message;
- no hardware provider control.

Acceptance:

- `tests/fixtures/hardware/scout_machine_target_profile.example.json` can be
  validated locally;
- preflight reports whether the target is ready for manual smoke;
- local validation does not open a network connection;
- any `/safety/observations` smoke step remains operator-only and outside the
  preflight.

中文註釋：Slice 0 是「部署前準備」，不是「已部署到 Pi」。它讓我們先把目標機設定、
資料根、禁用 AI/真硬體/event bus 的邊界寫清楚，避免一開始就混入真硬體或模型服務。

### Slice 1: Runtime Portability Audit

Goal:

- identify which current modules can run in Linux arm64 runtime-core and which
  must stay workstation-only or optional.

Audit scope:

- import-time macOS dependencies;
- FastAPI/server assumptions;
- filesystem paths and data root assumptions;
- Python native wheel risks on arm64;
- optional provider imports;
- visualization-only dependencies;
- OpenRouter/LLM dependency isolation;
- current health and retrieval endpoints.

Acceptance:

- each core runtime module is classified as `runtime-core`, `optional-provider`,
  `admin-workstation`, `test-dev`, or `ai-experimental`;
- macOS-only modules such as `macos_wifi.py` are behind provider boundaries;
- Phase 1 route-progress, safety state, recording policy, and incident package
  logic remain hardware-agnostic.

中文註釋：先盤點，不急著改。這一步的產物應該是清楚的 port blocker list。

### Slice 2: Data Root and Health Contract

Goal:

- make field runtime data placement explicit and testable.

Scope:

- `SCOUT_DATA_ROOT=/data/scout`;
- incident store under the mounted data root;
- future capsule/raw-ring/log directories reserved;
- health endpoint or command reports runtime profile, data root, writeability,
  incident store status, and optional provider status.

Acceptance:

- runtime can start with a temporary data root in tests;
- health check reports deterministic status without requiring live hardware;
- incident package persists under configured data root;
- restart preserves persisted incident JSON.

中文註釋：這一步不是做 UI，是讓硬體啟動後可以知道 Scout 是否有地方寫資料、是否能存 incident package。

### Slice 3: Docker Runtime Core

Goal:

- build a minimal Scout runtime image for `linux/arm64`.

Scope:

- Dockerfile or runtime image definition;
- Docker Compose file for Pi;
- uvicorn/FastAPI startup;
- mounted `/data/scout`;
- fixture-backed providers only;
- no AI inference requirement.

Acceptance:

- image builds for `linux/arm64`;
- container starts on Pi 5 or arm64 Linux target;
- `/safety/observations` is reachable;
- runtime starts without cloud credentials and without live hardware devices.

中文註釋：Docker slice 的重點是把 deterministic Scout server 裝進 Pi 能跑的容器，不是導入 k3s 或 event bus。

### Slice 4: Pi Fixture Smoke Test

Goal:

- prove the Pi runtime can execute the same deterministic safety path as the
  Mac replay baseline.

Smoke ladder:

```text
docker compose -f docker-compose.pi.yml up -d
curl http://scout.local:PORT/health
curl -X POST http://scout.local:PORT/safety/observations ...
docker compose -f docker-compose.pi.yml exec scout python phase1_replay_demo.py ...
ls /data/scout/incidents
docker compose -f docker-compose.pi.yml restart scout
curl http://scout.local:PORT/safety/incidents/<incident_id>
```

Acceptance:

- health endpoint reports runtime and data root status;
- observation ingest returns success or deterministic validation error;
- replay creates expected safety events;
- incident package is visible under `/data/scout/incidents`;
- restart does not corrupt persisted state;
- missing optional hardware providers degrade safely.
- local `scout_pi_fixture_smoke.py` only renders a manual-only command plan and
  never executes network calls or `/safety/*` mutation.

中文註釋：第一個硬體 demo 的驗收不是漂亮 UI，而是「能跑、能判斷、能落盤、重開機後證據還在」。

### Slice 5: Hardware Provider Contract

Goal:

- define how live hardware eventually feeds Scout without changing safety
  semantics.

First provider manifests:

- `gnss.position`;
- `imu.motion`;
- `battery.status`;
- `ble.phone_bridge`;
- `cellular.remote_status`.

Each capability should declare:

- capability id;
- device class;
- transport;
- required permissions;
- sampling or message rate;
- power draw class;
- failure modes;
- degraded behavior;
- evidence fields emitted into Scout;
- whether it is allowed in Phase 1 safety logic.

Acceptance:

- provider fixtures can emit normalized `Observation` or provider-state inputs;
- missing provider data creates unavailable/degraded evidence;
- no provider implementation can directly change L0-L4 logic outside existing
  deterministic evaluators.

中文註釋：先定 contract 和 fixture，再接真硬體。不要讓某個 GNSS/IMU/modem SDK 直接滲透進 safety evaluator。

## Environment Variables

Minimum Step 1 variables:

```text
SCOUT_DATA_ROOT=/data/scout
SCOUT_RUNTIME_PROFILE=pi-field
SCOUT_ENABLE_LIVE_HARDWARE=0
SCOUT_ENABLE_AI_INFERENCE=0
SCOUT_LOG_LEVEL=info
```

Optional later variables:

```text
SCOUT_PROVIDER_GNSS=fixture|serial|gpsd
SCOUT_PROVIDER_IMU=fixture|ble|serial
SCOUT_PROVIDER_COMMS=fixture|ble|lora|lte|ntn
SCOUT_EVENT_BUS=none|mqtt|nats
SCOUT_AI_ACCELERATOR=none|cpu|coral|jetson
```

Rules:

- defaults are fixture-backed and safe;
- live hardware is opt-in;
- AI inference is opt-in;
- event bus is not part of Step 1.

中文註釋：預設值要能讓 Pi 在沒有真硬體、沒有網路、沒有 AI 的狀況下啟動並跑 deterministic smoke test。

## Non-Goals for Hardware Port Step 1

- Phase 4 pre-trip UI implementation;
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

中文註釋：這些不是永遠不做，而是不屬於第一個 hardware port slice。先把 Pi deterministic runtime 跑穩。

## Verification Ladder

Local pre-port checks:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest tests/test_safety_runtime_session.py tests/test_safety_api.py tests/test_phase1_replay_demo.py
/Users/alexwang0315/scout-fusion/venv/bin/python phase2_release_check.py --repo-root /Users/alexwang0315/scout-fusion
```

Pi Step 1 checks:

```bash
docker buildx build --platform linux/arm64 -t scout-runtime:pi .
docker compose -f docker-compose.pi.yml up -d
curl http://scout.local:PORT/health
curl -X POST http://scout.local:PORT/safety/observations ...
docker compose -f docker-compose.pi.yml exec scout python phase1_replay_demo.py \
  --mission tests/fixtures/mission_graph/normal_climb_mission.json \
  --route tests/fixtures/routes/off_route_deviation.gpx \
  --incident-store /data/scout/incidents \
  --pretty
docker compose -f docker-compose.pi.yml restart scout
curl http://scout.local:PORT/safety/incidents/<incident_id>
```

Expected result:

- Pi runtime starts;
- health reports data root status;
- replay and ingest work without live hardware;
- L2 incident can be persisted;
- restart preserves incident retrieval;
- optional providers report unavailable instead of crashing.

中文註釋：如果這個 ladder 過了，Scout 就已經跨過「只能在 Mac prototype 跑」的門檻。

## Roadmap After Step 1

Only after Pi 5 + Docker runtime is stable:

1. k3s, if service orchestration has a real operational reason;
2. MQTT/NATS, if event boundaries are clear and replayable;
3. tiny CPU inference as read-only interpretation;
4. Coral TPU only if CPU measurements justify it;
5. Jetson only after Pi measurements show a concrete GPU-class workload;
6. LoRa/LTE/NTN provider integrations as separate capability slices.

中文註釋：Jetson、Coral、衛星、event bus 都應該由量測或明確需求推動，不要成為第一步。

## Open Questions

- Is Pi 5 + phone bridge enough for the first field trial, or is a separate
  phone-linked wearable logger required first?
- What is the minimum battery-life target for a Pi field node?
- Should the first physical acknowledgement be GPIO button, BLE phone action,
  or both?
- Should GNSS Step 1 use fixture, gpsd, or serial device first?
- Which storage write pattern is acceptable for raw ring buffer on SSD?
- What minimal `/health` fields are needed before field deployment?
- Which provider capability should be implemented first after fixture-backed
  contracts are stable?

中文註釋：這些問題不阻止開始 Docker/Pi runtime port；它們會影響後續硬體 provider 與外型設計。

## Scout Machine Smoke Status

2026-05-20: Scout machine remote smoke reached the first hardware target.

Completed:

- copied a clean runtime-core package from commit `b41f50cd` to `scout.local`;
- built `scout-fusion/pi-runtime:step1` successfully on the target;
- observed an existing healthy `scout-runtime` on `9099`;
- smoke-tested the new `step1` image on temporary host port `9101`;
- verified `/health`, `/runtime/status`, and `/providers/status`;
- removed the temporary smoke container.

Not run:

- no `/safety/*` mutation;
- no outbound/SOS/SMS/satellite send;
- no local model request;
- no live hardware or provider control.

中文註釋：這代表 Docker/Pi Step 1 已經跨到 Scout 機器實測，但還不是現場安全任務部署。

## Runtime Deployment Takeover Status

2026-05-20: the existing `scout-runtime` service on `scout.local` was taken over
with the Step 1 image.

Completed:

- created rollback tag `scout-fusion/pi-runtime:rollback-20260520T031746Z`;
- promoted `scout-fusion/pi-runtime:step1` to service tag
  `scout-fusion/pi-runtime:local`;
- recreated `scout-runtime` through the existing compose project;
- kept `SCOUT_ENABLE_LIVE_HARDWARE=0`, `SCOUT_ENABLE_AI_INFERENCE=0`,
  `SCOUT_ENABLE_LOCAL_MODEL=0`, and `SCOUT_EVENT_BUS=none`;
- verified `/health`, `/runtime/status`, and `/providers/status` from the target
  and from the workstation.

Not run:

- no `/safety/*` mutation;
- no local model request;
- no hardware provider control;
- no outbound/SOS/SMS/satellite send.

## Fixture Observation Smoke Status

2026-05-20: an operator-approved fixture `POST /safety/observations` smoke was
run against the deployed `scout-runtime`.

Completed:

- preserved `SCOUT_ENABLE_LIVE_HARDWARE=0`, `SCOUT_ENABLE_AI_INFERENCE=0`,
  `SCOUT_ENABLE_LOCAL_MODEL=0`, and `SCOUT_EVENT_BUS=none`;
- accepted one fixture observation;
- moved `observations_processed` from `0` to `1`;
- kept `safety_level=L0_NORMAL`;
- returned no incident ids and no stored incident paths;
- produced no new incident files under `/data/scout/incidents`.

Limitation:

- the current manual fixture uses hardware-export style keys, so this validates
  runtime ingest plumbing rather than route matching or capability availability.

## Canonical Fixture Local Dry Run Status

2026-05-20: the hardware smoke fixture gained a canonical SensorLog variant and
was verified against a local temporary `scout_pi_runtime` app.

Completed:

- added `tests/fixtures/hardware/manual_observation_smoke.canonical.example.json`;
- used canonical adapter keys such as `locationLatitude`, `locationLongitude`,
  `locationHorizontalAccuracy`, `accelerometerAccelerationX`, and
  `batteryLevel`;
- verified GPS, horizontal accuracy, IMU, battery, pedometer distance, and
  pedometer steps as available capabilities;
- verified the route-aware path by hitting checkpoint `cp_01`;
- kept target network calls and target `/safety/*` mutation at zero.

## Recommended Next Slice

After the manual dry-run package, Docker dry-run gate, GPIO boundary review,
dirty-worktree cleanup plan, Scout machine read-only smoke, and runtime
deployment takeover, fixture observation smoke, and canonical fixture local
dry-run, the next slice is one of two bounded tracks:

1. run one canonical fixture target smoke against `scout.local`, using the same
   rollback criteria as the previous fixture observation smoke;
2. stabilize Phase 4 dirty worktree groups one at a time.

Deliverables:

- runtime service ownership and restart policy documented;
- version/tag strategy for replacing `scout-fusion/pi-runtime:local`;
- backup and rollback checklist for `/data/scout`;
- explicit approval before any `/safety/observations` fixture smoke;
- separate commit plan for Phase 4 planning core, admin map UI, and runtime
  stream/live provider drafts.

中文註釋：下一步是「如何接管既有 runtime service」的部署決策，不是自動把 dirty
worktree、GPIO、live provider 或本地模型併入 Phase 1 safety path。
