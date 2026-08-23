# Scout AI Model Gateway + PraisonAI Thin Slice Experiment

```yaml
experiment_id: SCOUT-AI-EXP-MODEL-GATEWAY-PRAISON-002
hypothesis: >
  Three logical PraisonAI specialists can share one Scout-owned resident local
  model through a bounded, typed Model Gateway without gaining provider choice
  or authoritative Scout write access.
current_baseline: >
  SCOUT-AI-EXP-PRAISON-MCP-001 proved the isolated MCP and real PraisonAI
  AgentTeam lifecycle with deterministic specialist callbacks and zero model
  requests.
proposed_architecture: >
  Scout Core -> MCP -> PraisonAI AgentTeam -> task-bound ScoutModelGateway
  session -> bounded local inference scheduler -> one resident Pydantic AI
  model -> SpecialistReport -> IntelligenceResponse -> PydanticContractGateway.
implementation_scope:
  - Experimental src/scout/nextgen namespace only.
  - Sequential Terrain, QGIS, and Research specialist tasks.
  - One shared task-bound model request ledger with a minimum ceiling of 10.
  - One resident local model object and max_local_concurrency=1.
  - Typed SpecialistModelInput and SpecialistReport boundaries.
  - Priority queue, timeout, cancellation, backpressure, and execution records.
  - Faithful deterministic FunctionModel replay through real Pydantic AI calls.
  - No Main Agent, Workspace, route, Safety, Permission, notification, emergency,
    device, or hardware writes.
expected_benefit: >
  Make PraisonAI useful as an orchestration plane while preserving one model
  policy point, bounded edge resources, typed output, and Pydantic-owned
  authority validation.
risks:
  - The replay model proves execution topology, not natural-language reasoning quality.
  - Synchronous provider calls support soft cancellation; they are not forcibly killed.
  - Process isolation is not yet an operating-system sandbox.
  - No real Hailo, MAX, cloud, or QGIS MCP backend is exercised in this experiment.
  - Raspberry Pi cold-start, thermal, memory, and energy behavior remain unmeasured.
test_dataset: >
  Controlled route, prepared DEM, and QGIS candidate artifacts containing ridge,
  saddle, and steep-terrain features, plus malformed output, stale binding,
  authority escalation, process crash, timeout, cancellation, and budget-overrun cases.
metrics:
  - Pydantic structured-output validity.
  - Model request count and task binding.
  - Runtime and model identity consistency.
  - Maximum observed local concurrency.
  - Timeout, cancellation, and budget enforcement.
  - MCP response validation and candidate-only invariants.
results:
  - Main project environment: 34 passed, 4 optional PraisonAI tests skipped.
  - Isolated PraisonAI 1.7.0 plus Pydantic AI 2.33.0 environment: 34 passed.
  - Real AgentTeam and full MCP subprocess paths both completed.
  - Terrain, QGIS, and Research produced exactly three typed model execution records.
  - All three calls used local.fast.pydantic-function and one resident model object.
  - Total successful model requests were 3 under one shared 10-request ledger.
  - Two concurrent task sessions observed maximum local model concurrency of 1.
  - An 11-request backend overrun was recorded as failed and blocked further calls.
  - Malformed output, timeout, cancellation, stale binding, and denied authority failed closed.
  - Degraded model failures retained failed execution and allowed read-tool audit records.
  - Every accepted response remained candidate_only=true and runtime_safety_truth=false.
regression: >
  Focused NextGen contracts, runtime shadow, Model Gateway, MCP, and PraisonAI
  tests remain passing in the main environment. Production assistant routing and
  provider selection were not changed.
decision: CONTINUE_RESEARCH
rollback_strategy: >
  Remove the model scheduler/gateway modules and praison-model-replay mode. The
  previous deterministic Praison replay and StubIntelligenceGateway remain
  available, while production Scout behavior is unchanged.
```

## Qualification Boundary

This experiment demonstrates an executable architecture, not model quality or
production readiness. The `FunctionModel` output is deterministic qualification
evidence. It is not a Hailo, MAX, cloud, or QGIS result and cannot be promoted to
runtime safety truth.

## Next Gate

Status: demonstrated at the adapter/protocol level by
`SCOUT-AI-EXP-OPENAI-COMPAT-PRAISON-003`; live model quality remains unmeasured.

Add one experimental OpenAI-compatible backend adapter behind
`ScoutModelGateway`, then qualify the same fixed corpus against an actual local
model runtime. Keep PraisonAI provider-blind, retain local concurrency of one,
and compare typed-output validity, request count, latency, memory, and fallback
behavior against this replay baseline before touching the production answer path.
