# Scout AI Tool Calling And Terrain Router Qualification Experiment

```yaml
experiment_id: SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-005
hypothesis: >
  Scout can independently prove model-selected read-only tool calling and use a
  deterministic specialist router to omit unnecessary Research Agent work from
  a pure terrain request without changing the candidate-only authority boundary.
current_baseline: >
  SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-004 qualified basic chat, typed output, three
  sequential PraisonAI specialists over MCP, and authority validation. Its final
  Ollama qwen3:1.7b run took 226305 ms wall time and 209252 ms in the PraisonAI
  segment. Terrain, QGIS, and Research took 71050, 64587, and 63412 ms. The run
  did not independently prove a model-selected read tool call.
proposed_architecture: >
  Typed IntelligenceRequest -> deterministic specialist route plan -> selected
  PraisonAI agents only -> MCP candidate response -> Pydantic Contract Gateway.
  Model qualification separately runs chat -> typed output -> one bounded
  read-only tool loop -> PraisonAI MCP -> authority validation.
implementation_scope:
  - Add SpecialistRoutePlan with selected roles, skipped roles, and reason codes.
  - Always retain Terrain for terrain_analysis.
  - Select QGIS only when task-bound QGIS evidence and capability are both present.
  - Select Research only for a typed conflict bound to available evidence and a
    workspace.evidence.read grant.
  - Add a fixed read-only tool-calling probe outside PraisonAI orchestration.
  - Require exactly one model-selected tool call, exact evidence ref, tool-result
    consumption, completion marker, and approved observed model identity.
  - Record tool call count and tool names in the typed qualification report.
  - Version the expanded report as scout.model_runtime_qualification.v1.
  - Preserve candidate_only=true and runtime_safety_truth=false throughout.
out_of_scope:
  - No Assistant, Workspace, Mission, route, Permission, Safety, emergency,
    notification, device, QGIS, model file, or hardware mutation.
  - No Raspberry Pi, Hailo, MAX, Mac GPU, or cloud runtime qualification.
  - No claim that the fixed tool probe qualifies every provider-specific tool mode.
expected_benefit: >
  Detect endpoints that can emit valid JSON but cannot perform a real tool loop,
  while removing one unnecessary local CPU model request from the fixed pure
  terrain corpus.
risks:
  - Research is omitted only when typed evidence exposes no bound conflict; an
    upstream producer that hides conflicts in prose cannot trigger Research.
  - The fixed tool probe proves one bounded function-call pattern, not general
    tool-use quality or multi-tool planning.
  - One live CPU comparison remains sensitive to host load and model warm state.
  - The 10 second general fixture is too short for CPU cold start and typed output;
    CPU qualification must use the explicit 60 second edge fixture.
  - Report v0 artifacts remain historical evidence and are not rewritten as v1.
test_dataset: >
  terrain-http-qualification-v0 plus deterministic no-conflict and bound-conflict
  route cases, a positive two-request tool loop, and a marker-without-tool negative
  case.
metrics:
  - Specialist roles selected and skipped.
  - Router reason codes and agent path.
  - Independent tool call count and exact tool name.
  - Model request count and observed model identity.
  - Candidate-only and runtime-safety-truth flags.
  - Focused test and lint results.
  - Live request-level latency and token comparison against the v0 artifact.
results:
  - Main Scout environment, broader relevant NextGen regression: 60 passed and
    8 optional PraisonAI tests skipped.
  - Isolated PraisonAI 1.7.0 focused environment: 30 passed.
  - Ruff passed on all changed Python files.
  - The positive qualification performed one read-only tool call and two model
    requests; the negative marker-only endpoint failed with
    ToolCallingProbeNotExecuted.
  - Pure terrain routing selected Terrain and QGIS and skipped Research with
    research:no_valid_conflict_evidence.
  - A valid conflict bound to available evidence selected Research with
    research:bound_conflict_evidence.
  - A cold model run with the general fixture timed out during model loading. A
    warm run passed chat but timed out during typed output. Both failed closed and
    did not execute tool calling or PraisonAI.
  - The first edge CPU tool attempt called the correct read tool five times across
    seven model requests and then missed the completion marker. It failed closed
    after 92440 ms with ToolCallingMarkerMismatch.
  - Adding an explicit tool-result completion handshake did not relax the gate:
    exactly one correct evidence-bound tool call is still required. The second
    live attempt passed with two model requests, one tool call, and 30074 ms.
  - The full v1 qualification passed in 225757 ms with report hash
    f278298756645bad7536a4d874703bafad0b4b63913cbdbdb3f6a54e4f0b82af.
  - The live agent path was orchestrator -> deterministic router -> Terrain ->
    QGIS. Research was not instantiated. PraisonAI recorded exactly two model
    requests taking 76981 and 76894 ms.
  - The v1 PraisonAI segment took 175359 ms versus 209252 ms in v0: 33893 ms or
    16.2 percent lower. Model requests fell from three to two and specialist model
    tokens fell from 2912 to 1720, a 40.9 percent reduction.
  - The three grounded findings and three evidence items were exactly equivalent
    to v0. Candidate-only validation passed with runtime_safety_truth=false.
  - Total qualification wall time was nearly flat because v1 adds the independent
    28271 ms tool gate. That gate is qualification overhead and is not part of an
    ordinary terrain intelligence request.
regression: >
  Focused qualification, PraisonAI runtime, MCP, candidate-boundary, and router
  tests pass in both the main and isolated dependency environments. Production
  Scout routing and authoritative state are unchanged.
decision: ACCEPT
next_gate: >
  Determine whether already normalized QGIS candidate_features need a separate
  QGIS LLM pass. Benchmark deterministic QGIS evidence ingestion plus one Terrain
  interpretation call, while retaining QGIS Agent for raw GIS computation,
  conflict, or exploratory tool-selection tasks.
rollback_strategy: >
  Remove the deterministic route-plan selection and independent tool-calling
  check, then restore the previous fixed three-specialist experimental path. No
  production runtime or stored model needs migration.
```

## Result Classification

- Independent tool-calling gate: `LIVE PASS`.
- Deterministic terrain specialist routing: `LIVE PASS`.
- Live PraisonAI CPU latency improvement: `PASS`, 16.2 percent.
- Full qualification wall-time improvement: `NEUTRAL`, due to the new gate.
- Production promotion: `NOT REQUESTED`.
