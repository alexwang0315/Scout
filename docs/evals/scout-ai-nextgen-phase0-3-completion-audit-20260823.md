# Scout AI NextGen Phase 0-3 Completion Audit - 2026-08-23

Classification: `WORKING PROTOTYPE`
Production readiness: `NOT REQUESTED / NOT CLAIMED`
Authority: `candidate_only=true`, `runtime_safety_truth=false`
Phase 4/MAX: `SEPARATE BRANCH; NOT INCLUDED IN THIS AUDIT`

## Phase Results

| Phase | Result | Executable evidence |
| --- | --- | --- |
| 0 - Activation and architecture baseline | PASS | No production controller constructs Intelligence Gateway, MCP, Praison, or background queue; only feature-gated `runtime_shadow` is imported by the existing Assistant path |
| 1 - Raspberry Pi CPU runtime | PASS, experimental background only | Native Pi full qualification passed with basic chat, typed output, independent tool calling, Praison MCP, and authority validation |
| 2 - Persistent background intelligence | PASS, process-local prototype | SQLite jobs/events, cancellation, restart interruption, stale result rejection, and submit/start resource backpressure passed |
| 3 - Real-route terrain slice | PASS | Chilai Nanhua Day 1 real route + 20 m DEM + QGIS/GRASS artifact passed through MCP, Praison, Model Gateway, and Pydantic Contract Gateway |

## Phase 0 - Isolation

The experimental path remains additive under `src/scout/nextgen/`. Outside
that namespace, production Python imports reference only `runtime_shadow` from:

- `assistant_models.py`;
- `assistant_api.py`;
- `assistant_pydantic_provider.py`.

That surface is separately gated by `SCOUT_AI_NEXTGEN_RUNTIME_SHADOW`, records a
non-authoritative selection trace, and does not execute a NextGen model or alter
provider behavior. No mission, route, baseline, permission, safety, emergency,
notification, device, or production database migration was introduced.

## Phase 1 - Pi CPU

The Intel/Mac CPU Ollama profiles were removed. The replacement profile is:

```text
runtime_id=edge.pi.ollama.cpu.background
provider=ollama
required_host_kind=raspberry_pi
endpoint=http://127.0.0.1:11434/v1
capabilities=CHAT, STRUCTURED_OUTPUT, SLOW_BACKGROUND_REASONING, OFFLINE
priority=BACKGROUND
max_local_concurrency=1
```

Native Pi qualification artifact:

`artifacts/scout-ai-nextgen/model-runtime-qualification-pi-native-qwen3-1.7b-20260823.json`

Report hash:

`a257615303513a16640d212a073d2713bf6cd0d38509b7df420c9e94c70528bc`

The checked profile cannot be selected on a generic/Mac host. Hailo remains a
sibling Pi runtime restricted to `CHAT + SMALL_TYPED_OUTPUT`; it is not treated
as full structured output or reliable tool calling.

## Phase 2 - Background Lifecycle

Implemented boundaries:

- one-worker bounded Praison candidate queue;
- queryable state/progress, wait, cancellation, and result retrieval;
- optional SQLite typed job store and append-only events with mode `0600`;
- terminal result restoration without execution replay;
- nonterminal restart conversion to `FAILED / ProcessRestartInterrupted`;
- Pydantic Contract Gateway validation at completion and current-binding
  validation again at result consumption;
- stale result rejection and audit event;
- fresh memory, swap, CPU temperature, and throttle admission at submit and
  immediately before execution;
- malformed or authority-escalating output discard.

The queue remains candidate-only and has no write handle to authoritative Scout
stores. Its current API is process-local; cross-process MCP submit/status/cancel
tools are promotion debt, not silently implied.

## Phase 3 - Real Route

Input packet:

- Chilai Nanhua Day 1 current golden route;
- prepared 20 m corridor DEM;
- completed `terrain_feature_stack.v1` QGIS/GRASS artifact;
- 128 route samples plus candidate ridge/valley/stream vectors;
- human and visual review status `pending`.

The native Pi agent path was:

```text
praisonai.orchestrator
  -> praisonai.router.deterministic.v1
  -> terrain
  -> qgis.deterministic
```

Observed execution:

| Metric | Value |
| --- | --- |
| Praison MCP | 126177 ms |
| Model requests | 1 |
| Model execution | 124072 ms |
| Model | Pi CPU Ollama `qwen3:1.7b` |
| Tokens | 1206 input / 190 output |
| Tools | `route.read`, `dem.read`, `qgis.processing.slope` |
| Findings | 4 grounded candidate findings |
| Uncertainty | Saddle remains `UNKNOWN`; reviewed saddle derivative absent |
| Research Agent | Skipped |
| Cloud fallback | None |
| Candidate output hash | `416fe2b25496c7a2267aa048cc52fb05fba5d88e4d3b78f76f8044a9976b60fd` |
| Report hash | `bae7bd88407db67c267fb86a837db67bd93c9430c68dc76e9ff6a10f0a4d524d` |

Changing the current Workspace revision/input hash caused
`STALE_BINDING / accepted=false`. After the live run the Pi reported 51.6 C,
`throttled=0x0`, 4354 MB available RAM, and 128 MB swap used.

## Verification

- Main Python environment: `114 passed, 10 skipped in 81.42s`.
- Isolated PraisonAI 1.7.0 environment: `98 passed in 201.84s`.
- The ten optional Praison skips in the main environment executed in the
  isolated environment and passed.
- Ruff: all scoped source and tests passed.
- `git diff --check`: passed.
- Real report hash recomputation: passed.
- Authority literals at report, execution, response, and finding levels: passed.
- Native Pi resource monitor: 6312 MB available, 128 MB swap used, 47.95 C,
  `throttled=false`; resource policy returned no rejection reason.
- Scoped secret scan: no match.
- Temporary Mac-to-Pi tunnel: stopped; port 11435 has no listener.
- Production Pi container/configuration: unchanged; staging remained under
  `/tmp/scout-nextgen-phase1`.

## Explicitly Not Promoted

- Pi CPU reasoning is not a foreground answer path; the real route MCP segment
  took about 126 seconds.
- The background queue has no production API/Dashboard activation or retention
  policy yet.
- Real provider cancellation latency and UPS/battery telemetry remain unqualified.
- QGIS output remains candidate evidence with human/visual review pending.
- MAX is owned by the separate Phase 4 branch and was not modified or claimed here.
- No SFT, LoRA, expanded agent workforce, Mojo kernel, or distributed authority
  was promoted.

## Rollback

Remove the experimental Pi profiles, persistent queue/resource modules, real
route experiment packet, and other `src/scout/nextgen/` changes. Existing
production Pydantic Agent, Workspace stores, reducers, permission, safety,
emergency, notification, and device paths require no schema or data rollback.
