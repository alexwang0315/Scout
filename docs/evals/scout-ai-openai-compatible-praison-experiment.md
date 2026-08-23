# Scout AI OpenAI-Compatible PraisonAI Experiment

```yaml
experiment_id: SCOUT-AI-EXP-OPENAI-COMPAT-PRAISON-003
hypothesis: >
  Scout can keep PraisonAI provider-blind while executing three specialist model
  calls through one explicit OpenAI-compatible backend, preserving typed output,
  bounded request accounting, MCP isolation, and candidate-only authority.
current_baseline: >
  SCOUT-AI-EXP-MODEL-GATEWAY-PRAISON-002 proved one shared resident Pydantic AI
  FunctionModel. No HTTP model backend had been registered with ScoutModelGateway.
proposed_architecture: >
  Scout Core -> MCP -> PraisonAI AgentTeam -> task-bound ScoutModelGateway ->
  bounded scheduler -> explicit OpenAI-compatible Pydantic backend -> MAX,
  Ollama, or another standards-compatible qualified endpoint. Hailo remains a
  sibling backend and keeps its dedicated compatibility path.
implementation_scope:
  - Experimental src/scout/nextgen namespace only.
  - Typed, size-bounded runtime JSON config.
  - Explicit loopback, private-network, or remote-HTTPS transport scope.
  - Credential environment-variable name only; no credential value in config.
  - Real HTTP Chat Completions and Pydantic typed tool-output path.
  - Provider-attempt counter for successful and failed model requests.
  - New praison-openai-compatible MCP mode.
  - MAX example config with local concurrency fixed at one.
  - No production assistant, Workspace, route, Permission, Safety, emergency,
    notification, device, or hardware writes.
expected_benefit: >
  Make MAX, Ollama, and future standards-compatible providers replaceable
  inference backends rather than agent-owned choices, while retaining one
  auditable model policy and authority boundary.
risks:
  - The faithful HTTP replay is not evidence of a real model's answer quality.
  - Tool-call structured output still depends on endpoint/model compatibility.
  - Synchronous provider calls have bounded waiting but no hard mid-request kill.
  - No circuit breaker or thermal/energy-aware routing is implemented yet.
  - Private-network HTTP is allowed only through explicit operator configuration.
test_dataset: >
  The fixed route, prepared DEM, and QGIS candidate corpus used by the prior
  PraisonAI experiment, plus HTTP 503, unreachable endpoint, secret-in-config,
  transport-scope, model identity, and request-budget cases.
metrics:
  - HTTP request path and requested model identity.
  - Pydantic structured-output validity.
  - Agent and model request count.
  - Input/output token usage from provider response.
  - Failed provider-attempt accounting.
  - MCP process and candidate-only validation.
  - Live endpoint availability classification.
results:
  - Main project environment: 46 passed, 7 optional PraisonAI tests skipped.
  - Isolated PraisonAI 1.7.0 plus Pydantic AI 2.33.0 environment: 49 passed.
  - Real POST /v1/chat/completions transport produced schema-valid typed output.
  - Real PraisonAI direct and MCP paths each issued exactly three HTTP model calls.
  - HTTP 503 was counted as one failed model request and failed closed.
  - Two parallel cloud sessions retained independent one-request execution ledgers.
  - An unreachable endpoint returned no findings and retained failed model records.
  - Runtime config rejected embedded secrets, URL credentials, and remote plain HTTP.
  - Credential references were restricted to Scout-owned KEY/TOKEN variables over HTTPS.
  - scout.local HTTP required explicit private_network scope.
  - MAX remained a non-cloud sibling backend and did not claim offline capability.
live_probe_2026_08_22:
  - 127.0.0.1 ports 8000, 18000, and 11434: unavailable.
  - scout.local ports 8000, 18000, and 11434: unavailable.
  - MAX CLI: unavailable.
  - Ollama client 0.21.0: installed; server unavailable; no local model manifest.
  - No model service was started and no model artifact was downloaded.
regression: >
  Focused NextGen contract, runtime-shadow, Model Gateway, PraisonAI, MCP, and
  OpenAI-compatible tests remain passing. Production provider selection was not changed.
decision: CONTINUE_RESEARCH
rollback_strategy: >
  Remove the OpenAI-compatible backend module, MCP mode, example config, and
  focused tests. The deterministic FunctionModel replay and stub gateway remain,
  and production Scout behavior is unchanged.
```

## Result Classification

- Adapter and orchestration topology: `WORKING PROTOTYPE`.
- Live MAX, Hailo, or Ollama inference on 2026-08-22: `UNKNOWN / UNAVAILABLE`.
- Real-model terrain reasoning quality: `MORE_EVIDENCE_REQUIRED`.
- Production promotion: `NOT REQUESTED`.

The HTTP qualification server implements the real OpenAI-compatible transport
contract but returns deterministic candidate fixtures. Those responses are not
model-quality evidence, GIS truth, route truth, or runtime safety truth.

## Next Gate

`SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-004` implemented the reusable qualification
runner, fixed corpus, observed-model identity check, and durable unavailable
artifact. The remaining gate is an already-authorized live endpoint; no MAX,
Hailo, or Ollama model service was available during this experiment.
