# Scout AI Model Runtime Live Qualification Experiment

```yaml
experiment_id: SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-004
hypothesis: >
  Scout can qualify one explicitly configured OpenAI-compatible model endpoint
  through basic chat, typed Pydantic output, PraisonAI specialists, isolated MCP,
  and the candidate-only authority gateway without changing production routing.
current_baseline: >
  SCOUT-AI-EXP-OPENAI-COMPAT-PRAISON-003 proved the protocol and orchestration
  topology with a faithful HTTP replay. The first live run then proved endpoint
  reachability but exposed timeout classification, async-client event-loop,
  tool-output, empty-report, and evidence-grounding gaps.
proposed_architecture: >
  Operator-owned runtime config -> Scout live qualification runner -> basic chat
  probe -> ScoutModelGateway typed probe -> MCP-isolated PraisonAI terrain corpus
  -> Pydantic Contract Gateway -> immutable candidate-only qualification report.
implementation_scope:
  - Experimental scout.nextgen.model_qualification module and thin CLI only.
  - Fixed, non-authoritative ridge, saddle, and steep-terrain qualification case.
  - Config, case, evidence, endpoint, response, and report hashes.
  - Requested and observed model identity recording with explicit alias allowlist.
  - Exact Scout-owned KEY/TOKEN credential allowlist for the MCP child process.
  - Basic chat, selectable typed tool/native output, PraisonAI MCP, and
    authority-boundary checks.
  - Bounded max-output, temperature, thinking, timeout, and local concurrency.
  - Server-owned normalization of typed candidate features before model
    interpretation, plus item-level quarantine for out-of-scope model evidence.
  - Parent-process wall latency and peak RSS telemetry.
  - No Assistant, Workspace, Mission, route, Permission, Safety, emergency,
    notification, device, QGIS, or hardware writes.
expected_benefit: >
  Make endpoint availability and compatibility an executable, repeatable gate
  rather than a configuration claim, while keeping model serving replaceable.
risks:
  - A replay success is not evidence that MAX, Ollama, or Hailo answers correctly.
  - observed_model_id is based on the endpoint response model field and remains
    provider self-report rather than hardware attestation.
  - Memory telemetry currently covers qualification-parent ru_maxrss, not full
    MCP child or accelerator memory.
  - No thermal, energy, sustained-load, or circuit-breaker qualification yet.
  - Provider waiting is bounded but has no hard mid-request thread termination.
  - Ollama qwen3:1.7b tool output with reasoning disabled returned empty model
    messages; the passing path uses native JSON Schema and does not qualify live
    model tool calling.
  - The 8 GB x86_64 CPU host required a 300 second MCP envelope. This is a
    capability proof, not an edge latency or Raspberry Pi acceptance target.
  - Two QGIS model findings cited DEM evidence outside the QGIS specialist scope.
    They were discarded and retained as auditable uncertainties.
  - Child environment credential passing is least-privilege but is not a future
    secret-manager or file-descriptor handoff replacement.
test_dataset: >
  terrain-http-qualification-v0 with reviewed route input, prepared DEM candidate
  features, and QGIS candidate evidence. The corpus requires ridge, saddle, and
  steep-terrain findings while preserving candidate-only authority.
metrics:
  - Basic chat marker and latency.
  - Pydantic structured output mode and validity.
  - Requested and observed model identities.
  - Model request and token counts.
  - PraisonAI agent path and tools called.
  - Candidate findings and evidence refs.
  - Contract Gateway validation and response hash.
  - Parent peak RSS and total wall latency.
  - Endpoint unavailable and process-crash classification.
results:
  - Main environment: 59 passed, 8 optional PraisonAI tests skipped.
  - PraisonAI 1.7.0 isolated environment: 63 passed. The FastAPI-dependent
    runtime-shadow file remained in the main environment because FastAPI is not
    installed in the isolated intelligence-service environment.
  - Ruff passed on every changed Python file.
  - Live Ollama 0.21.0 served qwen3:1.7b (Q4_K_M, 2.0B parameters) through the
    loopback OpenAI-compatible endpoint with one loaded model and concurrency 1.
  - The passing run used five model requests: one plain chat, one native typed
    output, and three sequential PraisonAI specialist calls through isolated MCP.
  - Total wall latency was 226305 ms. The PraisonAI/MCP segment was 209252 ms;
    terrain, QGIS, and research calls were 71050, 64587, and 63412 ms.
  - The model segment used 2536 input and 376 output tokens. Basic and typed
    probes used another 129 input and 31 output tokens.
  - Server-owned normalization preserved ridge, saddle, and steep-terrain
    candidate findings. Two out-of-scope QGIS model findings were omitted and
    emitted as explicit grounding uncertainties.
  - Every check passed, observed model identity matched qwen3:1.7b, and the
    Contract Gateway accepted the result as candidate evidence only.
  - Final report hash:
    e6516643c6c2621aa21b2d7c4b039a59b7807510382a9d250d703678dba1b371.
  - Unexpected observed model identity failed closed; an explicit configured
    alias passed the bounded basic-chat gate.
  - MCP forwarded only the exact configured SCOUT_*KEY or SCOUT_*TOKEN variable.
  - Process exit received a 100 ms classification grace and remained distinct
    from a still-running request timeout.
  - The earlier MAX example endpoint returned ConnectError after 1440 ms and recorded
    one failed model request; all later checks were not_run.
  - The final Ollama live artifact disposition is passed with
    candidate_only=true and runtime_safety_truth=false.
regression: >
  Focused NextGen contracts, model gateway, PraisonAI, MCP, OpenAI-compatible
  backend, and qualification tests pass. Production model routing is unchanged.
decision: ACCEPT
rollback_strategy: >
  Remove the qualification module, CLI, fixed corpus, experiment packet, observed
  model field, and credential allowlist. The prior OpenAI-compatible adapter and
  production Scout behavior remain unchanged.
```

## Result Classification

- Qualification runner and typed report: `WORKING PROTOTYPE`.
- Faithful OpenAI-compatible HTTP replay: `PASS`.
- Live Ollama qwen3:1.7b native structured output: `PASS`.
- Live MCP-isolated PraisonAI three-specialist candidate slice: `PASS`.
- Specialist evidence-scope quarantine: `PASS`, with two observed quarantines.
- Live Ollama qwen3:1.7b model tool calling: `REJECT` for this configuration.
- Live MAX endpoint on 2026-08-22: `UNAVAILABLE`.
- MAX structured decoding, tool calling, latency, and memory: `NOT RUN`.
- Real-model terrain reasoning quality: `MORE_EVIDENCE_REQUIRED`; typed source
  facts are preserved deterministically, but broader reasoning quality is not
  established by one corpus.
- Production promotion: `NOT REQUESTED`.

Follow-up experiment `SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-005` passed an independent
live tool-calling gate after adding an explicit tool-result completion handshake.
The `REJECT` above remains the correct result for this experiment's earlier probe
and has not been rewritten as a retrospective pass.

The passing live artifact is
`artifacts/scout-ai-nextgen/model-runtime-qualification-ollama-qwen3-1.7b-native-full-pass-attempt6-20260822.json`.
The earlier unavailable MAX artifact remains useful negative-path evidence. Both
represent endpoints with SHA-256 digests rather than raw URLs, expose no
credentials, and cannot promote model output.

## Next Gate

Add a separate tool-calling qualification check rather than treating native JSON
Schema success as tool-use success. Then run the same fixed corpus on MAX and a
real edge runtime, capture full child/model memory plus thermal and energy data,
and compare latency and grounding errors without changing production routing.

Hailo remains a sibling `ScoutModelRuntime` path. This experiment does not imply
MAX-to-Hailo compatibility and must not be used to bypass the dedicated Hailo
runtime qualification.
