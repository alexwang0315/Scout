# Scout AI Answer Reliability Architecture

Status: proposal / research architecture
Date: 2026-08-21
Depends on: `scout-ai-nextgen-architecture-gap-analysis.md`

This proposal combines Pydantic AI, PraisonAI, and Modular/MAX into a new Scout
AI architecture whose primary goal is to improve answer success rate. The main
change is not "use more agents" or "use a different model". The main change is
to make every answer attempt pass through a typed evidence trajectory that can be
measured, repaired, and replayed.

## Diagnosis

If answer success rate is not improving, the likely bottleneck is no longer
only model quality. In this repository, Scout already has many strong pieces:

- Pydantic AI provider and typed dependency boundary.
- Bounded tool contracts and read-only workspace query services.
- MSER contracts for minimal sufficient environmental representation.
- MSER answer verifier that blocks stale, missing, contradictory, or uncited
  claims before normal reasoning.
- Model policy and SLA gateway for timeout, budget, fallback, and provider
  health.
- Candidate-only QGIS and spatial-evidence boundaries.

The missing architecture is a mandatory answer reliability loop:

```text
question
  -> question contract
  -> required evidence plan
  -> deterministic evidence acquisition
  -> MSER / workspace sufficiency certificate
  -> model-facing compact context
  -> structured answer
  -> deterministic claim verification
  -> typed success, repair, unknown, or conflict result
```

Without that loop, improving prompts, switching models, or adding multi-agent
orchestration can raise cost and complexity without fixing the failure source.

## Core Thesis

Scout should optimize answer success as an evidence-system problem first:

> Answer success = evidence trajectory success + context sufficiency + model
> synthesis + deterministic verification.

Pydantic AI remains the authoritative control plane. PraisonAI becomes an
optional intelligence workforce for tasks that need decomposition or research.
Modular/MAX becomes an inference backend, not an agent framework. Mojo remains a
future compute-kernel experiment only after benchmarks show value.

## Proposed Architecture

```text
Dashboard / API / Device
        |
        v
Scout Answer Gateway
  - Pydantic AI control plane
  - answer attempt lifecycle
  - typed request/response envelope
  - authority classification
        |
        v
Question Contract Compiler
  - classify question type
  - determine safety/authority class
  - determine required evidence dimensions
  - choose deterministic vs agentic path
        |
        v
Workspace Evidence Compiler
  - WorkspaceQueryService
  - route / mission / weather / terrain / sensor stores
  - external evidence artifacts
  - provenance, freshness, uncertainty, conflict
        |
        v
MSER Core
  - EnvironmentalRepresentation
  - MinimalSufficientContext
  - SufficiencyCertificate
  - InformationNeed
        |
        +---- if insufficient / research-heavy ----+
        |                                          |
        v                                          |
Scout Intelligence Gateway                         |
  - MCP boundary                                   |
  - capability grants                             |
  - task/mission/workspace binding                |
        |                                          |
        v                                          |
PraisonAI Intelligence Service                     |
  - AgentFlow for simple sequential/route/parallel |
  - AgentTeam for explicit DAG/hierarchical tasks  |
  - Terrain / QGIS / Research specialists          |
  - candidate evidence only                        |
        |                                          |
        +------------ candidate evidence ----------+
                                                   |
        v                                          v
MSER Reprojection / Sufficiency Gate <--------------+
        |
        v
Scout Model Gateway
  - LOCAL_FAST
  - HAILO_LOCAL
  - MAX_LOCAL_OR_SERVER
  - CLOUD_REASONING
  - CLOUD_RESEARCH
        |
        v
Pydantic AI Synthesis Agent
  - typed output
  - structured claims
  - usage limits
  - dependencies and tools
        |
        v
Answer Verifier / Recovery Orchestrator
  - source-ref verification
  - stale/conflict/missing checks
  - no unsupported claims
  - no authority escalation
  - root-cause-specific retry
        |
        v
VerifiedCandidateAnswer | EvidenceGapAnswer | ConflictAnswer | UnknownAnswer
```

## Role Of Each Technology

| Layer | Primary role | Why it helps success rate | What it must not do |
| --- | --- | --- | --- |
| Pydantic AI | Scout answer control plane | Type-safe deps, tools, output schemas, usage limits, validation | Become a freeform prompt wrapper that trusts model prose |
| MSER | Minimal sufficient evidence representation | Prevents the model from answering before required evidence exists | Replace full workspace or become runtime safety truth |
| PraisonAI | Optional multi-agent intelligence service | Decomposes complex research/GIS/context tasks and fills information needs | Directly mutate mission, permission, route, safety, notification, or hardware state |
| MCP | Process/capability boundary | Isolates PraisonAI/QGIS failures and controls capabilities | Become an untyped backdoor into workspace writes |
| Modular/MAX | Model inference runtime backend | Can serve stronger local/server models and structured output through a standard client path | Act as Scout agent framework or Hailo substitute |
| Hailo AI HAT+2 | Edge inference accelerator | Local offline LLM/VLM/CV where supported | Own agent runtime, policy, or state |
| Mojo | Future compute-kernel layer | Potentially faster DEM/sensor kernels after benchmark | Rewrite Scout agents, reducers, or policy |

## Answer Success Pipeline

### 1. Question Contract Compiler

Every question first becomes a typed contract:

```text
QuestionContract
  question_id
  question_class
  decision_type
  criticality
  authority_class
  required_dimensions
  allowed_tools
  denied_tools
  required_freshness
  expected_output_schema
```

The important shift: the model does not decide whether a question needs current
position, weather freshness, route geometry, or permission state. Deterministic
classification and policy provide the default required dimensions. The model may
suggest additional evidence, but it does not remove required evidence.

### 2. Evidence Plan And Tool Execution

The evidence compiler turns required dimensions into deterministic tool calls:

```text
required_dimensions
  -> workspace query
  -> route facts
  -> terrain facts
  -> weather facts
  -> sensor facts
  -> existing evidence refs
```

Arithmetic, filtering, joins, spatial lookup, freshness checks, and provenance
checks stay in Python. This directly targets a common success-rate failure:
the model sounds fluent while the needed fact never entered context.

### 3. MSER Sufficiency Gate

MSER becomes the central gate:

- `SUFFICIENT`: model may synthesize candidate answer.
- `INSUFFICIENT`: return information needs or ask PraisonAI/tool layer to fill
  gaps.
- `CONTRADICTORY`: preserve conflict; do not let the model choose a side.
- `AMBIGUOUS_DECISION`: ask clarification.

The model only sees `ModelFacingMSERPayload`, not raw workspace dumps.

### 4. PraisonAI Only For Information Needs

PraisonAI should not be inserted into every answer. It should be triggered by
MSER `InformationNeed` when the missing evidence requires research,
decomposition, or specialist tools.

Good PraisonAI use cases:

- QGIS/terrain exploration where the exact tool sequence depends on findings.
- Historical, cultural, or route-context research.
- Multi-source contradiction investigation.
- Alternative candidate generation.
- Deep research that can run away from the Pi process.

Poor PraisonAI use cases:

- Simple route fact lookup.
- Current CP, distance, ETA, or freshness checks.
- Permission, emergency, notification, or hardware control.
- Deterministic geometry or numeric aggregation.
- Safety decision authority.

### 5. Model Gateway / Modular/MAX

Model routing should be based on the failure mode and the required capability:

| Runtime profile | Use for |
| --- | --- |
| `LOCAL_FAST` | intent classification, schema extraction, short workspace lookup |
| `HAILO_LOCAL` | offline route Q&A, local VLM/CV where supported, privacy-sensitive local reasoning |
| `MAX_LOCAL_OR_SERVER` | stronger local/server inference, structured-output experiments, Scout-tuned model serving |
| `CLOUD_REASONING` | high-reasoning synthesis when evidence is already good but local model fails |
| `CLOUD_RESEARCH` | web/deep research when allowed and provenance can be preserved |

MAX should be tested as an OpenAI-compatible model endpoint. Scout should route
to it through `ScoutModelRuntime`; Pydantic AI should still own tools and output
validation.

### 6. Structured Answer And Deterministic Verification

The synthesis agent should return structured claims, not only prose:

```text
CandidateAnswer
  answer_text
  claims[]
    claim
    signal_ids[]
    source_refs[]
    uncertainty
  candidate_only=true
  runtime_safety_truth=false
```

The verifier decides:

- verified candidate;
- needs evidence repair;
- needs model switch;
- blocked by conflict;
- blocked by stale state;
- unknown / more evidence required.

This prevents "retry with a stronger prompt" from hiding the real root cause.

## Root-Cause-Specific Recovery

Retries should not be generic. Every failed attempt should be classified:

| Failure class | Repair |
| --- | --- |
| Wrong question class | Fix classifier/profile hints; do not switch model first |
| Required evidence missing | Call deterministic tool or Intelligence Gateway |
| Tool selected but empty | Repair adapter, source path, filter, fixture, or freshness |
| Evidence exists but not in context | Fix MSER projection/context packing |
| Context sufficient but model misreads it | Switch model or use MAX/cloud; keep same evidence |
| Structured output invalid | Retry with Pydantic AI output mode/validator; compare MAX structured output if available |
| Unsupported claim | Feed verifier violation back once; then classify model failure |
| Conflict/stale state | Surface conflict/stale; do not force answer |
| Safety/authority escalation | Reject output; record boundary violation |

This is the practical place where answer success rate can improve: each failed
eval tells Scout which layer to repair.

## PraisonAI Architecture

Use MCP so Scout Core never imports PraisonAI internals:

```text
MSER InformationNeed
  -> IntelligenceRequest
  -> CapabilityGrant
  -> MCP
  -> PraisonAI service
       - AgentFlow for simple route/sequential/parallel workflows
       - AgentTeam for explicit task DAGs and manager validation
       - specialists: Terrain, QGIS, Research
  -> IntelligenceResponse
  -> Pydantic Contract Gateway
  -> MSER Reprojection
```

Initial specialists:

| Specialist | Keep separate? | Reason |
| --- | --- | --- |
| Research Agent | Yes | Different tools, web/source vetting, provenance concerns |
| QGIS Agent | Yes | Heavy process, MCP/QGIS lifecycle, GIS-specific failure modes |
| Terrain Agent | Maybe | If it only interprets existing MSER/DEM facts, use prompt/toolset. If it drives QGIS/DEM exploration, keep separate. |
| Weather Agent | Usually no | Current/freshness/normalization should be deterministic; agent only explains or researches forecast context. |
| Safety Agent | No authority agent | Safety may have explanatory/advisory views, but reducer/policy owns truth. |
| Permission Agent | No authority agent | Permission must remain deterministic and review/policy-controlled. |

PraisonAI improves success only when the failure is "we do not know which
evidence path to explore". It will likely hurt success if used for every simple
question because it adds wrapper layers, more prompts, and more hidden failure
paths.

## Modular/MAX Architecture

MAX enters as a model runtime backend:

```text
Pydantic AI Agent
  -> ScoutModelRuntime
  -> OpenAI-compatible client
  -> MAX server
  -> model output
  -> Pydantic validation
  -> MSER verifier
```

Required MAX spike tests:

- basic chat;
- Pydantic AI compatibility through OpenAI-compatible client;
- structured output vs Pydantic validation;
- tool-call behavior under Scout output schema;
- latency and memory on Mac/server profile;
- failure behavior: timeout, malformed JSON, unsupported schema, backend down.

MAX should not be evaluated by "sounds smarter". It should be evaluated by
verifier pass rate, first-pass structured-output validity, latency, memory, and
root-cause-specific recovery improvement.

## Edge Runtime Shape

```text
Raspberry Pi 5
  Scout Core
    - Pydantic AI control plane
    - MSER compiler/verifier
    - WorkspaceQueryService
    - reducers, permission, provenance
    - MCP client
    - local model queue
  Hailo AI HAT+2
    - supported local LLM/VLM/CV inference

Mac mini / workstation
  - MAX server
  - larger local models
  - QGIS Desktop + QGIS MCP
  - heavy DEM/GIS preprocessing

Cloud
  - frontier reasoning
  - deep research
  - optional escalation only
```

Default local concurrency:

```text
max_local_llm_concurrency = 1
max_qgis_jobs = 1
max_praison_parallel_model_calls_on_pi = 0 or 1
max_cloud_concurrency > 1 only when explicitly allowed
```

Logical PraisonAI parallelism must not become unbounded local inference
parallelism.

## Success Metrics

Replace one aggregate "answer success rate" with a layer-by-layer scorecard:

| Metric | Definition |
| --- | --- |
| Question classification accuracy | Correct question class, decision type, criticality, authority class |
| Evidence plan recall | Required dimensions identified |
| Tool selection precision | Avoids unnecessary or wrong tools |
| Evidence acquisition success | Required facts found with source refs |
| MSER sufficiency rate | Sufficient/insufficient/conflict/stale classified correctly |
| Context delivery success | Required facts present in model-facing payload |
| Structured output pass rate | Model returns schema-valid answer |
| Claim verification pass rate | Every claim cites certified signals/source refs |
| Unknown correctness | Missing evidence yields UNKNOWN/MORE_EVIDENCE_REQUIRED |
| Conflict preservation | Contradictions are surfaced, not resolved by guess |
| Authority preservation | Candidate/shadow/debug/visualization never promoted |
| First-pass success | Verified candidate without recovery |
| Recovery success | Failed first pass repaired by correct layer |
| Local/cloud parity | Local degraded answer preserves safety/evidence behavior |
| Workspace Dependency Score | Full/partial/stale/conflict/no-workspace behavior matches expectation |

This scorecard makes it obvious whether the problem is evidence, context,
model, verifier, or transport.

## Minimal Vertical Slice

The first slice should not start with PraisonAI. Use the existing MSER pieces:

```text
one route/workspace question
  -> QuestionContract
  -> WorkspaceQueryService
  -> MSER projection
  -> sufficiency certificate
  -> Pydantic AI structured answer
  -> MSERAnswerVerifier
  -> AnswerAttemptTrace
```

Recommended case:

> "這條 route 接下來哪一段需要特別注意地形或進度？請只根據目前 Workspace 證據回答。"

Why this slice:

- It tests real answer success, not just docs.
- It uses existing workspace and MSER assets.
- It avoids safety authority mutation.
- It produces a trace that can later feed training corpus design.
- It establishes a baseline before PraisonAI/MAX enter.

Only after this slice has measurable failure classes should PraisonAI and MAX be
added:

1. PraisonAI fills `InformationNeed` for terrain/research gaps.
2. MAX is tested when evidence is sufficient but local synthesis or structured
   output fails.

## Implementation Roadmap

### Phase A - Shadow Answer Trace

Goal:
Record `AnswerAttemptTrace` for current answer flows without changing user
behavior.

Artifacts:
Question contract, evidence plan, MSER state, selected tools, model runtime,
verifier result.

Gate:
At least 20 existing eval questions have layer-attributed outcomes.

### Phase B - MSER-Gated Eval Path

Goal:
For selected evals, require `READY_TO_REASON` before model synthesis.

Artifacts:
Eval fixture modes: full, missing, stale, conflicted, no-workspace.

Gate:
Unknown/conflict/stale answers are scored as success when correct.

### Phase C - Root-Cause Recovery

Goal:
Replace generic retries with failure-specific recovery.

Artifacts:
Recovery classifier, repair policy, model-switch policy, known-issue packet.

Gate:
Recovery improves verified candidate rate without increasing unsupported claims.

### Phase D - PraisonAI Intelligence Service

Goal:
Use PraisonAI only for MSER `InformationNeed` requiring decomposition or
research.

Artifacts:
MCP service, capability grants, Research/QGIS/Terrain thin slice.

Gate:
PraisonAI improves evidence acquisition success for research/GIS cases and does
not reduce simple workspace-query success.

### Phase E - MAX Runtime Backend

Goal:
Add MAX as an experimental `ScoutModelRuntime` backend.

Artifacts:
OpenAI-compatible adapter, structured-output benchmark, latency/memory report.

Gate:
MAX improves schema-valid or verifier-valid answer rate for sufficient-context
cases, or it is rejected/parked.

### Phase F - Workspace Model Training Corpus

Goal:
Build training data only from verified successful or correctly-abstaining
trajectories.

Artifacts:
Dataset schema, train/validation/frozen/adversarial/live split policy, leakage
guard.

Gate:
Fine-tuning is considered only after a strong model succeeds with the same
evidence trajectory.

## Architectural Decision

The recommended new architecture is:

```text
Pydantic AI + MSER = answer reliability kernel
PraisonAI + MCP = optional evidence exploration workforce
Modular/MAX = optional high-capability model runtime
Hailo = edge inference backend
Mojo = future measured compute kernel
```

The first success-rate improvement should come from making MSER and answer
verification the default measurement path, not from adding more agents. Once the
failure traces show that evidence exploration is the bottleneck, PraisonAI is
worth adding. Once traces show the context is sufficient but the model cannot
produce valid structured answers, MAX/cloud/model specialization is worth adding.
