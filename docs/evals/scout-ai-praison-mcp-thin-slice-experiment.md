# Scout AI PraisonAI MCP Thin Slice Experiment

```yaml
experiment_id: SCOUT-AI-EXP-PRAISON-MCP-001
hypothesis: >
  Scout can run a PraisonAI multi-agent lifecycle in an independent MCP process
  while Pydantic-owned contracts preserve candidate, capability, provenance,
  mission-binding, and runtime-safety boundaries.
current_baseline: >
  Scout Core had typed IntelligenceRequest/IntelligenceResponse contracts and a
  fail-closed stub, but no executable MCP Intelligence Service or PraisonAI
  lifecycle.
proposed_architecture: >
  Scout Core -> Scout-owned stdio MCP -> isolated Intelligence Service ->
  PraisonAI AgentTeam -> Terrain/QGIS/Research replay specialists -> untrusted
  IntelligenceResponse -> PydanticContractGateway.
implementation_scope:
  - Experimental src/scout/nextgen namespace only.
  - One read-only terrain candidate MCP tool.
  - Optional praisonaiagents 1.7.0 dependency.
  - Bounded local concurrency of one.
  - No Main Agent, Workspace, Safety, Permission, notification, or hardware writes.
expected_benefit: >
  Prove framework/process lifecycle separation before model or QGIS complexity is
  introduced, and establish a reversible boundary for later Model Gateway work.
risks:
  - Process isolation is not yet an operating-system sandbox.
  - Capability grants are task-bound typed objects but not yet signed for remote transport.
  - Deterministic replay proves orchestration plumbing, not model intelligence quality.
  - QGIS specialist currently interprets catalog artifacts and does not invoke QGIS MCP.
test_dataset: >
  Controlled route, prepared DEM, and QGIS slope candidate evidence containing
  ridge, saddle, and steep-terrain candidates; stale, denied-capability, crash,
  timeout, and unavailable-runtime variants.
metrics:
  - Typed response acceptance and rejection disposition.
  - candidate_only and runtime_safety_truth invariants.
  - MCP process reachability and crash isolation.
  - Agent path and tool provenance.
  - Local concurrency and timeout enforcement.
  - Model request count.
results:
  - Main project environment: 21 passed, 2 optional PraisonAI tests skipped.
  - Isolated praisonaiagents 1.7.0 environment: 11 passed, including full MCP subprocess round trip.
  - Three-agent path observed: orchestrator, terrain, qgis, research.
  - Model requests: 0; cloud requests: 0.
  - Denied mission.write attempt produced no findings and a typed capability uncertainty.
  - Service crash, timeout, and stale binding all degraded without authoritative mutation.
regression: >
  Existing NextGen contract and runtime-shadow focused tests remain passing. No
  production provider selection or assistant answer path was changed by this slice.
decision: CONTINUE_RESEARCH
rollback_strategy: >
  Remove the optional nextgen-intelligence extra, MCP CLI, and experimental MCP/
  Praison modules; Scout Core continues to use StubIntelligenceGateway and all
  deterministic production behavior remains unchanged.
```

## Next Gate

Status: demonstrated by `SCOUT-AI-EXP-MODEL-GATEWAY-PRAISON-002`.

Connect PraisonAI specialist inference through `ScoutModelGateway` with one
resident local model and a shared 10-request budget. Keep the deterministic
replay as the qualification baseline. Do not add QGIS execution or production
assistant routing until model execution telemetry, cancellation, malformed
structured-output handling, and provider fallback pass focused qualification.
