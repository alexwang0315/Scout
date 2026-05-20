# Pi 5 Local AI Runtime Experiment

Date: 2026-05-19

Status: Accepted as prototype evidence

## Purpose

Record the first real Scout Pi 5 local inference experiment.

This document answers one hardware question:

Can a Raspberry Pi 5 run Scout's deterministic field runtime and a tiny local
model at the same time, without thermal, memory, or service stability problems?

The answer from this experiment is yes for `qwen2.5:0.5b` and
`qwen2.5:1.5b` CPU-only inference, with an important boundary: local AI is
suitable as a low-frequency offline fallback interpretation path only. It is
not allowed to replace Phase 1 deterministic L0-L4 safety logic.

## Tested Hardware and Runtime

Hardware:

- Raspberry Pi 5;
- 16 GiB RAM;
- SSD-backed Scout data root mounted at `/data/scout`;
- active cooling available.

Runtime:

- Raspberry Pi OS / Debian aarch64;
- Docker Engine;
- Docker Compose;
- `scout-runtime` container on port `9099`;
- `scout-ollama` container on port `11434`;
- Scout data root: `/data/scout`;
- Scout runtime profile: `pi-field`.

Containers:

| Container | Role | Status After Test |
| --- | --- | --- |
| `scout-runtime` | Scout deterministic runtime | healthy |
| `scout-ollama` | Local model service | running |

Models:

| Model | Parameter Size | Quantization | Model Size | Execution | Reported VRAM | Context Length |
| --- | ---: | --- | ---: | --- | ---: | ---: |
| `qwen2.5:0.5b` | `494.03M` | `Q4_K_M` | about `398 MB` | CPU-only | `0` | `4096` |
| `qwen2.5:1.5b` | `1.5B class` | Ollama default quantized artifact | about `986 MB` | CPU-only | `0` | not re-measured in this run |

## Files Used

Local repo files:

- `docker-compose.pi.yml`
- `docker-compose.pi.ai.yml`
- `Dockerfile.pi`
- `requirements.pi.txt`
- `scout_pi_runtime.py`
- `tools/pi_ollama_stress.py`

Pi deployment location:

```text
~/scout-fusion-runtime/
```

## Test 1: Single Prompt Smoke Test

Goal:

- verify that Mac/PC admin client can call the Pi-hosted Ollama service;
- measure basic CPU-only latency;
- inspect response quality before any Scout integration.

Prompt:

```text
請用繁體中文用一句話說明 Scout 在斷線時本地模型的角色。
```

Result:

| Metric | Value |
| --- | --- |
| End-to-end latency | `5.699s` |
| Ollama total duration | about `5.369s` |
| Prompt tokens | `47` |
| Generated tokens | `87` |
| Generation duration | about `3.243s` |
| Approx generation rate | about `26.8 tokens/s` |

Observation:

The model ran successfully and latency was acceptable for a low-frequency
fallback. However, the response quality was not reliable enough for safety
authority: it used an incorrect name instead of Scout and produced generic
wording.

Decision:

The model can be tested further as an offline interpretation provider, but it
must not be connected directly to the Phase 1 safety decision path.

## Test 2: Ollama Inference Stress Test

Goal:

- determine whether the Pi 5 can sustain local tiny-model inference without
  thermal or memory instability.

Method:

- duration: about `180s`;
- workers: `4`;
- model: `qwen2.5:0.5b`;
- each request used a Scout-like offline fallback prompt;
- CPU temperature sampled every `5s`.

Result:

| Metric | Value |
| --- | --- |
| Completed requests | `36` |
| Requests by worker | `9, 9, 9, 9` |
| Average latency | `20.898s` |
| Minimum latency | `8.114s` |
| Maximum latency | `27.596s` |
| Start temperature | `37.8°C` |
| Average temperature | `55.24°C` |
| Maximum temperature | `60.4°C` |
| Error count | `0` |
| Memory after test | `15 GiB total`, about `14 GiB available` |
| Swap after test | `0B used` |

Thermal observation:

The fan started during the test, but temperature stabilized around the
high-50s to low-60s Celsius. There was no thermal runaway and no evidence that
the model workload was memory-bound.

Interpretation:

Pi 5 has enough thermal and memory headroom for `0.5B` CPU-only fallback
inference. Latency rises under concurrency, so production fallback should not
use high worker counts.

## Test 3: Combined Scout Runtime and Ollama Stress

Goal:

- verify that Scout's deterministic runtime remains stable while Ollama is
  under load;
- detect CPU contention between local inference and Phase 1 replay.

Method:

- Ollama stress test ran with `4` workers for about `180s`;
- during that load, Scout Phase 1 replay was run `3` times inside the
  `scout-runtime` container;
- replay fixture: `off_route_deviation.gpx`;
- after each replay, `/health` was checked.

Ollama result during combined test:

| Metric | Value |
| --- | --- |
| Completed requests | `23` |
| Requests by worker | `6, 6, 6, 5` |
| Average latency | `32.578s` |
| Minimum latency | `4.854s` |
| Maximum latency | `61.957s` |
| Start temperature | `42.2°C` |
| Average temperature | `55.68°C` |
| Maximum temperature | `62.0°C` |
| Error count | `0` |

Scout replay result during combined test:

| Replay | Runtime | Checkpoints | Checkpoint Hits | Safety Level | Event | Health |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | `19.669s` | `10` | `21` | `L2_CONCERN` | `route_deviation` | `ok` |
| 2 | `19.680s` | `10` | `21` | `L2_CONCERN` | `route_deviation` | `ok` |
| 3 | `19.628s` | `10` | `21` | `L2_CONCERN` | `route_deviation` | `ok` |

Final state:

| Metric | Value |
| --- | --- |
| `scout-runtime` | healthy |
| `scout-ollama` | running |
| Final temperature | `59.3°C` |
| Memory | `15 GiB total`, about `14 GiB available` |
| Swap | `0B used` |

Interpretation:

Scout runtime remained functionally stable under Ollama load. The deterministic
Phase 1 replay still produced the expected `L2_CONCERN` route-deviation
incident. The main cost was latency: local inference and replay contend for CPU.

## Test 4: Qwen 2.5 1.5B Candidate Test

Goal:

- test whether a larger local model improves fallback quality enough to justify
  higher latency;
- verify that Pi 5 can run a `1.5B` class local model without thermal, memory,
  or Scout runtime instability.

Model:

| Field | Value |
| --- | --- |
| Model | `qwen2.5:1.5b` |
| Installed size | about `986 MB` |
| Execution | CPU-only through Ollama |

### Single Prompt Test

Prompt:

```text
請用繁體中文用一句話說明 Scout 在斷線時本地模型的角色。
```

Result:

| Metric | Value |
| --- | --- |
| End-to-end latency | `8.567s` |
| Prompt tokens | `47` |
| Generated tokens | `48` |
| Generation duration | about `3.924s` |
| Prompt evaluation duration | about `2.170s` |
| Ollama total duration | about `7.659s` |

Observation:

The answer did not confuse Scout with another name, which was an improvement
over the first `0.5B` smoke test. The wording was still generic and did not yet
reflect Scout's exact offline-fallback safety boundary.

Decision:

`qwen2.5:1.5b` is viable for a better local interpretation path, but it needs
a stricter Scout prompt and preferably a fixed output schema. It should not be
used for long free-form fallback responses.

### 1-Worker Fallback Stress Test

Method:

- duration: about `120s`;
- workers: `1`;
- model: `qwen2.5:1.5b`;
- output cap: `160` tokens;
- same Scout-like offline fallback prompt as the `0.5B` stress test.

Result:

| Metric | Value |
| --- | --- |
| Completed requests | `9` |
| Average latency | `13.348s` |
| Minimum latency | `8.061s` |
| Maximum latency | `17.931s` |
| Start temperature | `39.5°C` |
| Average temperature | `55.93°C` |
| Maximum temperature | `60.9°C` |
| Error count | `0` |

Interpretation:

Pi 5 can run the `1.5B` model in single-worker fallback mode. The thermal and
memory profile remained acceptable, but latency is too high for an aggressive
`6-10s` timeout when long responses are allowed.

### Combined Scout Runtime and 1.5B Test

Method:

- Ollama stress test ran with `1` worker for about `120s`;
- during that load, Scout Phase 1 replay was run `3` times inside the
  `scout-runtime` container;
- replay fixture: `off_route_deviation.gpx`;
- after each replay, `/health` was checked.

Ollama result during combined test:

| Metric | Value |
| --- | --- |
| Completed requests | `5` |
| Average latency | `24.701s` |
| Minimum latency | `8.899s` |
| Maximum latency | `33.549s` |
| Start temperature | `43.3°C` |
| Average temperature | `55.15°C` |
| Maximum temperature | `61.5°C` |
| Error count | `0` |

Scout replay result during combined test:

| Replay | Runtime | Checkpoints | Checkpoint Hits | Safety Level | Event | Health |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | `19.991s` | `10` | `21` | `L2_CONCERN` | `route_deviation` | `ok` |
| 2 | `19.913s` | `10` | `21` | `L2_CONCERN` | `route_deviation` | `ok` |
| 3 | `20.141s` | `10` | `21` | `L2_CONCERN` | `route_deviation` | `ok` |

Final state:

| Metric | Value |
| --- | --- |
| `scout-runtime` | healthy |
| `scout-ollama` | running |
| Final temperature | `59.8°C` |
| Memory | `15 GiB total`, about `14 GiB available` |
| Swap | `0B used` |

Interpretation:

Scout runtime remained stable while the `1.5B` model was running. The expected
`L2_CONCERN` route-deviation result was preserved. The cost is higher inference
latency, especially when Scout replay and local model inference contend for
CPU.

## Scout Decision

Pi 5 is accepted as the current prototype runtime hardware baseline for:

- deterministic Scout runtime;
- Docker-based deployment;
- local health checks;
- fixture replay;
- SSD-backed incident persistence;
- low-frequency tiny-model offline fallback experiments;
- `0.5B` fast fallback and `1.5B` better-interpretation fallback experiments.

This result does not justify moving to Jetson yet. The measured bottleneck is
latency under concurrency, not a thermal or memory limit.

## Offline Fallback Integration Policy

If Scout connects this local model path, it must be integrated as a constrained
offline fallback provider.

Rules:

- run at most `1` local inference at a time;
- use model-specific timeouts:
  - `0.5B` fast path: initially `6-10s`;
  - `1.5B` better interpretation path: initially `12-18s`;
- do not allow unbounded queues;
- discard stale model requests instead of delaying safety evaluation;
- prefer short classification or fixed-schema outputs over long free-form
  answers;
- store output as `model_interpretation`, not as observed fact;
- include model name, prompt id, timestamp, latency, and runtime mode in
  provenance;
- label outputs as read-only model interpretation;
- never let local AI directly change L0-L4 safety state;
- never let local AI directly trigger SOS, evacuation, or route-deviation
  decisions;
- keep Phase 1 deterministic runtime authoritative.

Chinese clarification:

- `offline fallback` means disconnected backup mode, not normal operation.
- `model_interpretation` means model interpretation, not verified evidence.
- `deterministic runtime` means fixed rule/runtime logic, not AI judgment.
- `safety authority` means the component allowed to decide L0-L4 safety state;
  local AI does not have that authority.

## Recommended Next Tests

1. Run a longer `10-15` minute soak test to confirm thermal plateau.
2. Test fixed-schema Scout prompts for both `0.5B` and `1.5B`.
3. Add a fixture-backed `offline_model_provider` contract before any live
   runtime integration.
4. Compare another `1B-2B` safety or guard model only after the provider
   contract exists.
5. Keep Coral TPU and Jetson as measured follow-up steps, not immediate
   requirements.
