# Scout Machine Remote Smoke Results

Date: 2026-05-20

Target: `scout.local`

Commit package: `b41f50cd`

這份報告記錄 operator-approved Scout machine smoke。它不是常駐部署紀錄，也不是
Phase 1 safety mutation 證明。

## Boundary

- 不呼叫 live `/safety/*` mutation。
- 不送 outbound、SOS、SMS 或 satellite。
- 不控制 hardware provider。
- 不啟動本地模型，也不向本地模型發 request。
- 不改 Phase 1 safety decision。
- 不寫 ObservedFact、Brain 或 HumanReview。
- 臨時容器 smoke 結束後已移除。

## Machine Probe

- OS/kernel: Debian GNU/Linux on Raspberry Pi `aarch64`.
- Docker CLI/server: installed; server version `29.5.1`.
- Docker Compose: `v5.1.3`.
- `/data/scout`: present and writable by the operator account.
- Free storage: `/data` had hundreds of GB available during the check.

## Clean Runtime Package

The package copied to the Scout machine was built from clean HEAD commit
`b41f50cd`, using only the runtime-core files required by `Dockerfile.pi`.

Excluded from the package:

- Phase 4 pretrip draft flood.
- `PdrSample/*` local field captures.
- `trajectory_map.png`.
- `docker-compose.pi.ai.yml`.
- local model/Ollama compose wiring.

## Docker Build Result

Command class:

```bash
docker compose -f docker-compose.pi.yml build scout
```

Result:

- exit code: `0`
- image: `scout-fusion/pi-runtime:step1`
- image size on target: about `251MB`
- profile: `pi-field`
- live hardware: disabled
- AI inference/local model: disabled
- event bus: `none`

中文註釋：這證明 deterministic runtime-core 可以在 Scout 機器上建成 ARM64 Docker
image；不是 k3s、event bus、local model 或真 provider readiness。

## Existing Runtime Probe

The default `9099` port was already allocated by an existing container:

- container: `scout-runtime`
- image: `scout-fusion/pi-runtime:local`
- status: running and healthy
- restart policy: `unless-stopped`

Read-only probes against the existing service returned `200`:

- `GET /health`
- `GET /runtime/status`
- `GET /providers/status`

Observed boundary fields:

- `live_hardware_enabled=false`
- `ai_inference_enabled=false`
- `runtime_profile=pi-field`
- `safety_runtime_enabled=true`

## Step1 Image Runtime Smoke

Because `9099` was in use, the newly built `step1` image was started as a
temporary smoke container on `127.0.0.1:9101`.

Read-only probes returned `200`:

- `GET /health`
- `GET /runtime/status`
- `GET /providers/status`

Observed boundary fields:

- `live_hardware_enabled=false`
- `ai_inference_enabled=false`
- `local_model_enabled=false`
- `event_bus=none`
- provider contract: `fixture_or_degraded_step1`
- provider `control_allowed=false`

The temporary container was removed after the smoke.

## Existing Ollama Note

An existing `scout-ollama` container was present on the target machine at
`11434`. This smoke did not start it, stop it, or query it.

中文註釋：看到 Ollama container 存在只代表 target machine 上已有本地模型服務；本次
Step 1 smoke 仍保持 `SCOUT_ENABLE_LOCAL_MODEL=0`，不把本地模型放進 deterministic
safety runtime path。

## Not Run

`POST /safety/observations` was intentionally not run in this pass.

Reason: the assistant/hardware-port boundary still treats `/safety/*` mutation
as a separate operator decision. The read-only health/runtime/provider checks
are enough to prove Step 1 runtime boot without changing Scout state.
