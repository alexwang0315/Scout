# Scout AI Runtime Capability Matrix And Background Queue Experiment

```yaml
experiment_id: SCOUT-AI-EXP-RUNTIME-CAP-BGQ-007
hypothesis: >
  Scout can route Hailo only to bounded chat/small typed work and reserve an
  explicitly addressed Raspberry Pi CPU Ollama runtime for slow background
  reasoning, while PraisonAI long-running candidate work remains cancellable,
  observable, and outside authoritative runtime flow.
current_baseline: >
  ScoutModelGateway had generic chat/structured-output capabilities and bounded
  inference scheduling. PraisonIntelligenceService was synchronous and exposed
  no job lifecycle or progress-query contract.
implementation_scope:
  - Experimental scout.nextgen modules only.
  - Queryable ScoutModelGateway capability matrix.
  - Hailo CHAT plus SMALL_TYPED_OUTPUT profile.
  - Raspberry Pi CPU Ollama SLOW_BACKGROUND_REASONING profile and background priority.
  - Intel Mac CPU Ollama loopback profile removed and rejected by contract.
  - Single-worker bounded Praison background queue.
  - Submit, progress, list, wait, cancel, result, failure, and close lifecycle.
  - Candidate-only response validation before queue result publication.
  - No production routing, dashboard, mission, permission, safety, emergency,
    notification, QGIS, or hardware-control changes.
decision: ACCEPT_EXPERIMENTAL_BACKGROUND
```

## Capability Matrix

| Runtime | Declared intelligence capabilities | Recommended priority |
| --- | --- | --- |
| Hailo AI HAT+ 2 | `CHAT`, `SMALL_TYPED_OUTPUT`, `OFFLINE` | `NORMAL` |
| Raspberry Pi CPU Ollama | `CHAT`, `STRUCTURED_OUTPUT`, `SLOW_BACKGROUND_REASONING`, `OFFLINE` | `BACKGROUND` |

Hailo no longer self-declares unrestricted structured output. Its Praison path
uses the compact advisory envelope, with IDs, evidence normalization, authority
flags, and final validation remaining server-owned. Raspberry Pi CPU Ollama
Praison requests require the background reasoning capability and enter the model
scheduler with background priority. The checked-in profile is host-bound to
`RASPBERRY_PI` and targets the Pi-local `http://127.0.0.1:11434/v1`; a Mac
cannot select it merely because an Ollama endpoint happens to exist.

## Queue Contract

The queue states are:

```text
QUEUED -> RUNNING -> COMPLETED
                   -> CANCELLING -> CANCELLED
                   -> FAILED
QUEUED -------------------------> CANCELLED
```

Each progress snapshot binds `job_id`, `request_id`, mission, immutable Workspace
binding, stage, percentage, timestamps, cancellation state, response availability,
and error type. Every snapshot remains `candidate_only=true` and
`runtime_safety_truth=false`.

Optional SQLite persistence stores the typed request, progress, candidate
response, and append-only lifecycle events with mode `0600`. Completed jobs can
be inspected after restart. A nonterminal job found after restart becomes
`FAILED / ProcessRestartInterrupted` and is never silently replayed. Result
consumption requires the current Workspace binding and re-runs Pydantic Contract
Gateway validation; stale results fail closed.

The Pi resource admission policy checks fresh available-memory, swap,
temperature, and throttle observations both at submit and before a queued job
starts. Telemetry failure or a threshold violation rejects optional background
work without affecting Level 0 deterministic Scout.

Cancellation is cooperative. Queued jobs are cancelled before execution. Running
jobs receive one shared cancellation event through Praison service, runtime,
Model Gateway session, scheduler, and backend boundaries. Partial output is always
discarded. A provider call that cannot be interrupted may continue until its
bounded timeout, while the job remains visibly `CANCELLING`.

## Result

- Runtime capability routing and query matrix: `PASS`.
- Checked Hailo and Raspberry Pi CPU Ollama config mapping: `PASS`.
- Intel Mac CPU background profile rejection: `PASS`.
- Queue completion and progress query: `PASS`.
- Running and queued cancellation: `PASS`.
- Bounded queue backpressure: `PASS`.
- Malformed or authority-escalating result rejection: `PASS`.
- Real `PraisonIntelligenceService` boundary with deterministic replay: `PASS`.
- Existing OpenAI-compatible, model qualification, and MCP regression suite:
  `PASS`.
- The earlier remote-name probe remains retained as `UNAVAILABLE`; no Intel Mac
  fallback occurred. Its failure artifact is
  `artifacts/scout-ai-nextgen/model-runtime-qualification-pi-cpu-unavailable-20260823.json`
  (`report_hash=f3988ea0435f2594b81f1148ea3af415e598f0cfb0c4eebf4b85dbd39b7e6c19`).
- Native Raspberry Pi 5 CPU/Ollama full qualification: `PASS`. Basic chat,
  typed output, independent tool calling, Praison MCP, and authority checks all
  passed with report hash
  `a257615303513a16640d212a073d2713bf6cd0d38509b7df420c9e94c70528bc`.
- A real Chilai Nanhua route slice passed with one Terrain model request,
  deterministic QGIS ingestion, Research skipped, and report hash
  `bae7bd88407db67c267fb86a837db67bd93c9430c68dc76e9ff6a10f0a4d524d`.
- Persistent/restart/stale/resource queue qualification: `15 passed` with Ruff
  clean. Submit and pre-start backpressure, cancellation persistence, restart
  interruption, `0600` storage, and current-binding result validation passed.
- Post-run Pi evidence: `51.6 C`, `throttled=0x0`, 4354 MB available memory,
  and 128 MB swap used. Earlier peak observation reached 70.3 C without
  throttling.
- Native `LinuxEdgeResourceMonitor` smoke returned 6312 MB available memory,
  128 MB swap used, 47.95 C, `throttled=false`, and an empty deterministic
  rejection-reason tuple after the model unloaded.

## Promotion Debt

- Add Dashboard read-only progress endpoints only after the API contract is reviewed.
- Measure cancellation latency against real Hailo and Pi CPU Ollama provider calls.
- Bind a reviewed UPS/battery reader and production thresholds before promotion.
- Add MCP-level submit/status/cancel/result tools if job progress must cross the
  process boundary; the current queue API is experimental and process-local.
- Define retention/compaction and operator redaction policy for persistent job
  evidence before production use.

## Rollback

Remove the two capability labels, the Raspberry Pi CPU Ollama profile, Gateway
matrix view, background queue module/exports, and focused tests. Existing
synchronous Praison execution and generic Model Gateway behavior remain available.
