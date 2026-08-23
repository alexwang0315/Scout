# SCOUT_AI_NEXTGEN_ARCHITECTURE_GAP_ANALYSIS

Status: R&D-01 / Phase 0 research baseline
Date: 2026-08-21
Mode: read-only architecture inspection plus isolated design artifact

This document maps the current Scout AI implementation against the proposed
Next Generation Scout AI architecture. It is intentionally additive and does not
change production runtime behavior.

## Scope

This inspection focuses on:

- Pydantic AI agent runtime and typed contracts.
- Workspace/context projection and tool boundaries.
- Model provider, local inference, Hailo, and fallback abstractions.
- MCP and QGIS candidate evidence infrastructure.
- Evaluation, qualification, synthetic scenarios, and corpus readiness.
- Feasibility gaps for PraisonAI, MAX, Mojo, ScoutWorkspaceSnapshot, and
  ScoutModelRuntime.

Non-goals for this phase:

- Replacing Pydantic AI.
- Migrating runtime safety, permission, emergency, or notification authority.
- Adding PraisonAI, MAX, or Mojo as production dependencies.
- Treating any model output as runtime safety truth.
- Training a Scout Workspace Model.

## Status Taxonomy

- EXISTS: implemented in the repository and used or directly testable.
- PARTIAL: related implementation exists, but the proposed NextGen contract is
  not yet explicit or complete.
- MISSING: no direct implementation found.
- CONFLICT: proposed usage would violate an existing Scout authority or safety
  boundary.
- UNKNOWN: not proven by current repository inspection or available external
  evidence.

## Current Architecture Inventory

| Area | Status | Current assets | Gaps |
| --- | --- | --- | --- |
| Pydantic AI core agent | EXISTS | `src/scout/agents/deps.py`, `src/scout/agents/pydantic_provider.py`, `src/scout/agents/pydantic_ai_compat.py`, `assistant_pydantic_provider.py` | Current agent layer is strong enough to remain the control plane. It does not yet expose a NextGen Intelligence Gateway boundary. |
| Typed agent dependencies | EXISTS | `ScoutDeps`, `ScoutToolbox`, provider protocols, output validation, bounded agent runtime | Keep as authoritative kernel pattern. NextGen work should add contracts around this, not bypass it. |
| Pydantic Graph | PARTIAL | Mission graph/domain graph models exist; specs mention Pydantic Graph | No clear runtime Pydantic Graph workflow kernel was found. Treat Pydantic Graph as an intended direction, not a current dependency to build on blindly. |
| Workspace/context layer | PARTIAL | `scout_ai_context_registry.py`, bounded context tools, mission/route/runtime models, dashboard snapshots, scenario snapshots | No single immutable `ScoutWorkspaceSnapshot` v0 exists as a task-aware, versioned AI projection. Existing snapshots are domain-specific. |
| Workspace compiler | PARTIAL | Bounded context discovery/read paths, assistant total-information/context code, candidate context registry | Missing deterministic, task-aware compiler with sufficiency analysis, authority filtering, freshness handling, and token-budget accounting. |
| Tool contracts | EXISTS | `scout_ai_tool_contracts.py`, bounded tool planning/execution surfaces, read-only boundaries | Need NextGen tool-trace schema for training, eval, and runtime router observability. |
| Authority boundaries | EXISTS | Runtime safety gate models, safety reducer, Phase 1 mutation service, contextual permission tool, audit ledger, QGIS candidate contracts | These are hard constraints. NextGen intelligence must not mutate them directly. |
| Model policy/fallback | PARTIAL | `src/scout/agents/model_policy.py`, `src/scout/agents/model_gateway.py`, `assistant_model_config.py`, `configs/assistant-models.dashboard-aihat2.json` | These are good seeds, but there is no unified `ScoutModelRuntime` protocol with structured-output, tool-calling, hardware, memory, energy, offline, and capability metadata. |
| Local inference/Hailo | PARTIAL | AI HAT+2 config, `hailo_ollama` backend, Hailo native research adapter, local/cloud fallback eval tools | Need bounded inference scheduler, local concurrency defaults, hardware telemetry, cancellation, and explicit edge/cloud routing traces. |
| MAX runtime | MISSING | No repo implementation found | Feasible only as a spike via OpenAI-compatible serving. MAX must be treated as an inference backend, not an agent framework and not a Hailo substitute. |
| Mojo compute | MISSING | No repo implementation found | Candidate for benchmarked terrain/sensor kernels only. It should not rewrite agents or policy logic. |
| PraisonAI / multi-agent | MISSING | No PraisonAI code or dependency found | If adopted, put behind MCP/Intelligence Gateway as replaceable intelligence service. Direct imports into Scout Core would weaken process and authority isolation. |
| MCP | PARTIAL | Python requirements include Pydantic AI MCP extras; QGIS MCP stdio adapter exists | General Scout Intelligence MCP boundary is not yet defined. QGIS MCP is a strong narrow precedent. |
| QGIS intelligence | PARTIAL / STRONG EXPERIMENTAL | `qgis_mcp_stdio.py`, `qgis_worker.py`, `qgis_spatial_backend.py`, `qgis_spatial_contracts.py`, QGIS tests | Candidate-only GIS evidence path exists. Live QGIS workstation readiness and broader Intelligence Gateway integration remain separate proof work. |
| Evaluation | PARTIAL | `src/scout/evals`, many `tools/*eval*`, dashboard qualification, pydantic-evals dependency, synthetic scenario tools | No formal NextGen partition between TRAIN, VALIDATION, FROZEN GOLD, ADVERSARIAL, and LIVE WORKSPACE tests. |
| Training corpus | MISSING / PARTIAL | Existing corpora and scenario fixtures can seed examples | No Scout Workspace Model dataset schema, leakage policy, expected tool trace schema, or authority-label taxonomy exists yet. |
| Synthetic generator | PARTIAL | Scenario generators and six-forces synthetic routes exist | Missing controlled NextGen generator pipeline with teacher output validation, deterministic verifier, and human sampling. |
| Dashboard/observability | PARTIAL | Dashboard/Admin surfaces, runtime audit models, evidence artifacts | Need first-class trace records for model runtime routing, Intelligence Gateway calls, capability grants, agent path, output hash, validation, and promotion result. |

## Strong Existing Boundaries To Preserve

Scout already has the right architectural instinct in several places:

- Agent dependencies expose services as typed callable tools, while deterministic
  runtime owns execution, persistence, permission, provenance, and effects.
- Native research and web-fetch surfaces are candidate-only and explicitly not
  runtime safety truth.
- QGIS spatial outputs are candidate evidence or visualization. They cannot
  become route truth, walkability truth, safety truth, or operational state
  without review and deterministic promotion.
- Runtime safety state transitions already pass through typed gate models,
  reducers, permission, and explicit mutation services.
- Contextual permission remains read-only/advisory in AI-facing tool paths.

These assets support the proposed principle:

> Deterministic runtime decides what is true and what may happen. Intelligence
> layers decide how to research, decompose, summarize, and propose candidates.

## Conflicts And Weak Assumptions

1. PraisonAI is not currently present.
   The architecture should not assume PraisonAI is available or superior until a
   thin, replaceable Intelligence Service proves value.

2. Multi-agent does not imply multiple authorities.
   Safety, emergency, permission, and reviewed baseline cannot become
   specialist-agent-owned components. They may expose read-only facts and accept
   candidate evidence through deterministic promotion only.

3. MAX is not Hailo.
   Current external documentation supports using MAX as an inference server with
   OpenAI-compatible clients. It does not justify assuming MAX targets the AI
   HAT+2 / Hailo backend. The repo should model MAX and Hailo as sibling runtime
   backends.

4. Mojo should not enter the agent layer.
   Mojo may become useful for DEM, terrain, or sensor compute kernels after a
   reproducible benchmark. It should not be used to rewrite Pydantic AI,
   policy, reducers, or orchestration.

5. WorkspaceSnapshot is not "dump all JSON into a prompt".
   The current context registry and bounded runtime point in the right
   direction, but NextGen needs a deterministic compiler that emits the smallest
   sufficient, authority-aware, task-bound projection.

6. Existing eval assets are not automatically training data.
   Frozen tests, adversarial tests, and live workspace tests must be isolated
   from SFT/LoRA/few-shot prompt leakage.

7. Synthetic scenarios are not real evidence.
   Synthetic workspaces can train and evaluate behavior, but runtime evidence
   must remain provenance-bound and classified separately.

8. Cloud enhancement must not become minimum safety capability.
   Offline Level 0 deterministic functions must remain operational when cloud,
   local model, MAX, PraisonAI, QGIS, or web are unavailable.

## R&D Slice Mapping

| R&D item | Current fit | Recommended next step |
| --- | --- | --- |
| R&D-01 AI architecture inventory | This document establishes the baseline | Review and annotate with product-owner decisions before migration. |
| R&D-02 ScoutModelRuntime abstraction | PARTIAL via `ModelPolicy` and `ModelSlaGateway` | Add only an experimental protocol/design first; do not migrate all providers. |
| R&D-03 MAX feasibility spike | MISSING | Isolated OpenAI-compatible adapter spike against `max serve`; measure chat, structured output, tool calling, latency, memory, and failure modes. |
| R&D-04 WorkspaceSnapshot prototype | MISSING / PARTIAL | Build `ScoutWorkspaceSnapshot v0` as a projection from one existing workspace fixture or recorded route. No production schema changes. |
| R&D-05 Workspace-native benchmark | PARTIAL | Create four modes: full, missing, stale, conflicted. Test current local model first. |
| R&D-06 Training corpus schema | MISSING | Define dataset schema only; include authority constraints, evidence requirements, expected tool trace, and labels. |
| R&D-07 Synthetic generator prototype | PARTIAL | Generate a few controlled cases and pass them through deterministic validation before considering corpus growth. |

## Target Architecture Positioning

The recommended layering is:

```text
User / Dashboard / Device
        |
        v
Scout Core / Agent OS
  - Pydantic AI control plane
  - Pydantic models and typed tools
  - deterministic reducers
  - permission and policy gates
  - runtime stores and audit ledger
        |
        v
Scout Workspace Layer
  - mission, route, position, progress
  - terrain, weather, sensor facts
  - permission, safety, emergency state
  - evidence, provenance, stale/unknown/conflict markers
        |
        v
Workspace Context Compiler
  - task-aware projection
  - minimal sufficient context
  - authority/freshness/provenance filtering
        |
        v
Scout Intelligence Gateway
  - typed request/response boundary
  - capability grants
  - MCP client
  - timeout, retry, budget, validation
        |
        v
Scout Intelligence Service
  - PraisonAI or replaceable orchestrator
  - terrain/QGIS/research specialists
  - candidate findings only
        |
        v
Model Runtime Router
  - LOCAL_FAST
  - LOCAL_REASONING
  - LOCAL_VLM
  - MAX
  - HAILO
  - CLOUD_REASONING
  - CLOUD_RESEARCH
        |
        v
Compute / Accelerator Layer
  - Raspberry Pi CPU/RAM
  - AI HAT+2 / Hailo
  - Mac mini/server GPU or CPU
  - cloud models
  - future benchmarked Mojo kernels
```

The critical constraint is that higher intelligence layers return candidate
evidence, not authoritative state mutation.

## External Feasibility Calibration

The following external checks are feasibility inputs, not adoption decisions:

- MAX: Official Modular documentation supports serving models through `max
  serve` and using an OpenAI-compatible `/v1` API. This supports an isolated
  `OpenAI-compatible client -> MAX` spike. It does not prove Scout tool-calling,
  constrained decoding, latency, memory, or edge suitability.
  Source: https://max.modular.com/get-started/
- MAX CLI: Current `max serve` options include tool parser and experimental
  Mojo-kernel related controls. This should be tested, not assumed compatible
  with Scout Pydantic AI contracts.
  Source: https://max.modular.com/cli/warm-cache/
- Mojo: Official Mojo documentation supports Python interop, which makes it
  plausible for isolated compute kernels. It does not justify rewriting agent
  orchestration, policy, or reducers.
  Source: https://mojolang.org/docs/manual/python/
- Raspberry Pi AI HAT+2: Official Raspberry Pi documentation positions the
  AI HAT+ 2 / Hailo-10H as an accelerator for supported AI workloads, including
  LLM/VLM-oriented local acceleration. Scout still needs software, models, and
  runtime integration.
  Source: https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html
- Hailo-10H: Hailo positions the device as an edge GenAI accelerator with INT4
  TOPS and direct memory for LLM/VLM use cases. This supports Hailo as a model
  runtime backend, not as a general Scout agent framework.
  Source: https://hailo.ai/products/ai-accelerators/hailo-10h-ai-accelerator/

## Edge Deployment Interpretation

| Runtime location | Should run | Should not own |
| --- | --- | --- |
| Raspberry Pi CPU/RAM | Scout Core, Pydantic AI control plane, typed tools, reducers, permission, provenance, Mission/Route state, MCP client, bounded local orchestration | Heavy QGIS Desktop dependency, unbounded multi-agent inference, cloud-only safety dependency |
| AI HAT+2 / Hailo | Supported local LLM/VLM/CV inference through a model runtime backend | Agent framework runtime, policy authority, mission state, route truth |
| Mac mini/server | Heavy GIS, QGIS Desktop/MCP, larger local models, MAX spike, large context preprocessing | Required offline safety behavior |
| Cloud | Deep research, frontier reasoning, large multimodal models, optional fallback/escalation | Minimum viable Scout safety capability, direct runtime mutation |
| Dashboard | Review, evidence visualization, operator-facing status, candidate promotion UI where existing review paths allow it | Direct safety/emergency authority from model output |

## Resource Policy Baseline

Initial defaults for experimental NextGen work:

- `max_local_llm_concurrency = 1` on Raspberry Pi until measured otherwise.
- Logical multi-agent parallelism must pass through a bounded inference queue.
- Local queue priorities should prefer current mission/status queries over
  background research.
- Every Intelligence Gateway call must carry task, mission, workspace revision,
  timeout, model-request budget, tool-call budget, and cancellation token.
- Cloud escalation must be explicit in the request and recorded in provenance.
- Timeout or budget exhaustion returns a typed degraded/candidate result, not an
  unstructured exception.
- Thermal, battery, memory, and accelerator availability should enter routing
  decisions as telemetry before becoming hard policy.

## Failure And Threat Baseline

| Failure or threat | Expected Scout behavior |
| --- | --- |
| PraisonAI service unavailable | Level 0 deterministic Scout continues. Intelligence Gateway returns typed unavailable/degraded result. No authoritative state changes. |
| MCP disconnected | Candidate intelligence tools unavailable. Core read-only/deterministic tools remain available. Retry allowed if task budget permits. |
| Local model unavailable | Route to configured fallback if allowed; otherwise return local degraded answer with explicit uncertainty. Safety reducers continue. |
| AI HAT unavailable | Model runtime marks Hailo backend unavailable and falls back to CPU/local/cloud policy where allowed. |
| Cloud unavailable | Offline local and deterministic functions continue. Cloud-dependent research is UNKNOWN or MORE_EVIDENCE_REQUIRED. |
| QGIS unavailable | Heavy GIS candidate generation unavailable. Precomputed DEM/route/spatial indexes remain usable on edge if present. |
| Web unavailable | Research Agent cannot use fresh web evidence. It must not replace missing evidence with pretrained priors. |
| Model timeout | Cancel execution, record partial trace, return typed timeout/degraded candidate. |
| Invalid structured output | Reject at Pydantic Contract Gateway; do not repair into authoritative state silently. |
| Agent loop runaway | Enforce max model requests, max tool calls, wall-clock timeout, and cancellation. |
| Stale intelligence result | Reject or mark stale if workspace/mission/input binding changed. No silent reuse. |
| Prompt injection | Treat external/web/MCP content as untrusted evidence; keep capability grants least-privilege and deny write/action scopes. |
| Malicious MCP result | Validate schema, provenance, content hash, authority flags, size, and allowed source roots before accepting candidate evidence. |
| Authority escalation attempt | Reject any response claiming `runtime_safety_truth=true`, operational route truth, permission mutation, notification, emergency action, or hardware control. |
| Local/cloud inconsistency | Surface conflict and provenance. Deterministic reducers decide any promotion path, not the model. |

## Authority Matrix

| Component | Read authority | Write authority | Candidate authority | Runtime authority | Safety authority |
| --- | --- | --- | --- | --- | --- |
| Pydantic AI Scout Core | Workspace facts, tools, stores by policy | Authoritative runtime state through typed services | Can create candidates through controlled tools | Yes, through deterministic runtime services | Yes, through existing reducers/gates only |
| Pydantic models/contracts | Schema definitions | Validation results and typed objects | Defines candidate schemas | Indirect | Indirect |
| Deterministic reducers | Typed facts and candidates | Reduced authoritative state where allowed | Can accept/reject candidates | Yes | Yes |
| Permission service | Permission facts and policies | Permission state only through existing authority path | Can expose advisory results | Yes | Safety-adjacent authority |
| Runtime safety gate/reducer | Sensor/weather/terrain/pace facts | Safety assessment and Phase 1 mutation requests | Can classify candidate events | Yes | Yes |
| Scout Intelligence Gateway | Bounded workspace snapshot and evidence refs | Request/response trace, validation result | Yes | No authoritative mutation | No |
| PraisonAI orchestrator | Granted snapshot/evidence/tool capabilities | Its own task trace only | Yes | No | No |
| Specialist agents | Least-privilege granted capabilities | Their own candidate artifacts only | Yes | No | No |
| QGIS MCP / QGIS | Granted GIS layers/artifacts | Derived GIS artifacts under candidate boundary | Yes | No | No |
| Model Runtime Router | Task metadata, runtime profiles | Routing trace only | No | No | No |
| Hailo/MAX/Ollama/Cloud models | Prompt/context/tool schemas | Model outputs only | Yes, after validation | No | No |
| Dashboard | API-visible state and evidence | User review decisions where already supported | Can display candidates | No direct runtime authority | No direct safety authority |
| Audit/provenance store | Runtime and candidate events | Telemetry/provenance records | Records candidate lineage | No | No |

## Candidate Data Contracts

These are proposed NextGen contracts. They should live in an experimental module
until reviewed.

```python
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class AuthorityLevel(StrEnum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    OPERATIONAL = "operational"


class TaskType(StrEnum):
    TERRAIN_ANALYSIS = "terrain_analysis"
    ROUTE_CONTEXT = "route_context"
    HISTORICAL_RESEARCH = "historical_research"
    CULTURAL_RESEARCH = "cultural_research"
    QGIS_ANALYSIS = "qgis_analysis"
    ROUTE_CANDIDATE_ANALYSIS = "route_candidate_analysis"
    DEEP_RESEARCH = "deep_research"
    WORKSPACE_QA = "workspace_qa"


class GeoScope(BaseModel):
    route_id: str | None = None
    bbox_wgs84: tuple[float, float, float, float] | None = None
    corridor_meters: float | None = Field(default=None, ge=0, le=5000)
    crs: str = "EPSG:4326"


class WorkspaceBinding(BaseModel):
    workspace_id: str
    workspace_revision: str
    mission_id: str
    mission_version: str
    route_id: str | None = None
    route_version: str | None = None
    input_hash: str
    generated_at: datetime


class CapabilityGrant(BaseModel):
    grant_id: UUID
    request_id: UUID
    mission_id: str
    allowed_capabilities: set[str]
    denied_capabilities: set[str]
    evidence_refs_allowed: list[str] = []
    expires_at: datetime
    max_runtime_seconds: int | None = Field(default=None, ge=1)
    max_model_requests: int | None = Field(default=None, ge=1)
    max_tool_calls: int | None = Field(default=None, ge=1)
    issued_by: str
    provenance_ref: str
    fail_closed: Literal[True] = True


class IntelligenceRequest(BaseModel):
    request_id: UUID
    mission_id: str
    task_type: TaskType
    question: str
    workspace_binding: WorkspaceBinding
    geographic_scope: GeoScope | None = None
    evidence_refs: list[str] = []
    capability_grant: CapabilityGrant
    max_runtime_seconds: int | None = Field(default=None, ge=1)
    max_model_requests: int | None = Field(default=None, ge=1)
    requires_freshness_seconds: int | None = Field(default=None, ge=1)
    allow_cloud_escalation: bool = False
    candidate_only: Literal[True] = True


class Evidence(BaseModel):
    evidence_id: str
    source_type: str
    source_ref: str
    observed_at: datetime | None = None
    generated_at: datetime
    authority_level: AuthorityLevel = AuthorityLevel.CANDIDATE
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    freshness_seconds: int | None = Field(default=None, ge=0)
    method: str | None = None
    resolution: str | None = None
    content_hash: str
    summary: str


class Finding(BaseModel):
    finding_id: str
    claim: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    limitations: list[str] = []
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class Uncertainty(BaseModel):
    uncertainty_id: str
    description: str
    missing_evidence: list[str] = []
    impact: str
    recommended_next_evidence: list[str] = []


class Conflict(BaseModel):
    conflict_id: str
    description: str
    evidence_ids: list[str]
    unresolved: bool = True
    resolution_required_by: str | None = None


class ModelExecutionRecord(BaseModel):
    execution_id: UUID
    runtime: str
    model: str
    local_or_cloud: Literal["local", "edge", "mac_server", "cloud"]
    selected_reason: str
    started_at: datetime
    completed_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    timed_out: bool = False
    cancelled: bool = False
    fallback_used: bool = False


class IntelligenceProvenance(BaseModel):
    request_id: UUID
    service_name: str
    service_version: str
    agent_path: list[str]
    tools_called: list[str]
    model_executions: list[ModelExecutionRecord]
    capability_grant_id: UUID
    workspace_binding: WorkspaceBinding
    output_hash: str
    validation_status: Literal["accepted_candidate", "rejected", "stale", "malformed"]


class IntelligenceResponse(BaseModel):
    request_id: UUID
    findings: list[Finding] = []
    evidence: list[Evidence] = []
    uncertainties: list[Uncertainty] = []
    conflicts: list[Conflict] = []
    provenance: IntelligenceProvenance
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
```

## Minimal Runtime Invariants

Add these to the proposed INT-* invariant set:

- INT-013: Intelligence capability grants are task-bound, mission-bound,
  expiration-bound, and fail closed.
- INT-014: Model runtime selection must be recorded; silent routing is not
  allowed.
- INT-015: Synthetic, fixture, visualization, and debug evidence must remain
  explicitly labeled and cannot be promoted as real operational evidence.
- INT-016: Cloud or remote intelligence failure cannot disable Level 0
  deterministic safety behavior.
- INT-017: A model backend may fail or degrade, but the Scout Core provider
  contract must return a typed failure or fallback result.
- INT-018: Training, validation, frozen, adversarial, and live evaluation sets
  must have explicit lineage and anti-leakage controls.
- INT-019: Specialist agents receive tool capabilities, not broad workspace
  object access.
- INT-020: Any derived geometry must carry source, method, resolution,
  generated_at, candidate_only, visualization_only when applicable, and
  runtime_safety_truth=false.

## Recommended First Vertical Slice

Use an entirely non-authoritative terrain evidence case:

```text
Existing route geometry
        |
        v
ScoutWorkspaceSnapshot v0
        |
        v
Scout Intelligence Gateway request
        |
        v
MCP Intelligence Service facade
        |
        v
Terrain/QGIS/Research worker path
        |
        v
Candidate ridge/saddle/steep-terrain findings
        |
        v
Pydantic validation + provenance validation
        |
        v
candidate evidence only
```

Hard exclusions:

- no route mutation;
- no permission change;
- no notification;
- no safety event;
- no emergency action;
- no promotion to reviewed baseline.

## Phase 0 - Research Baseline

Goal:
Establish the factual map of the current system and identify safe experiment
entry points.

Existing assets:
Pydantic AI provider, typed deps, model policy/gateway, bounded agent runtime,
QGIS candidate contracts, runtime safety reducers, dashboard/eval artifacts.

Changes:
Design documents only, plus optional read-only scripts for inventory if needed.

Artifacts:
This gap analysis, architecture map, authority matrix, experiment backlog.

Experiments:
None required beyond repository inspection and external feasibility
confirmation for MAX/Mojo/Hailo positioning.

Acceptance gates:

- No runtime code changed.
- Gaps are classified as EXISTS, PARTIAL, MISSING, CONFLICT, or UNKNOWN.
- Existing authority boundaries are explicitly preserved.

Risks:
Inventory can drift quickly in a construction-heavy repo.

Rollback strategy:
Delete or supersede this design doc; no runtime rollback required.

## Phase 1 - Runtime Abstraction

Goal:
Define an experimental `ScoutModelRuntime` interface without migrating all
providers.

Existing assets:
`ModelPolicy`, `ModelSlaGateway`, `assistant_model_config.py`, Hailo/OpenRouter/
OpenAI-compatible provider code, fallback evals.

Changes:
Add experimental protocol and one adapter around the current provider path.

Artifacts:
`ScoutModelRuntime` design, runtime capability records, model execution trace
schema, focused tests.

Experiments:

- Wrap current OpenAI-compatible path.
- Wrap current `hailo_ollama` path.
- Verify typed failure/fallback behavior.

Acceptance gates:

- Existing agent calls still pass through current behavior.
- Runtime selection is observable.
- Local model failure returns typed degraded result.
- No safety/permission authority moves into the model layer.

Risks:
Over-abstracting too early; duplicating `ModelSlaGateway`.

Rollback strategy:
Keep under experimental namespace/feature flag and remove adapter without
touching production provider paths.

## Phase 2 - Workspace Intelligence

Goal:
Create `ScoutWorkspaceSnapshot v0` and a task-aware context compiler.

Existing assets:
Context registry, bounded context runtime, mission/route/safety/weather models,
scenario snapshots.

Changes:
Add immutable projection type and compiler for one narrow task class.

Artifacts:
Snapshot schema, compiler, four benchmark fixtures: full, missing, stale,
conflicted.

Experiments:

- Ask route/terrain status questions under each fixture mode.
- Measure Workspace Dependency Score.
- Verify missing/stale/conflict behavior.

Acceptance gates:

- Snapshot is versioned and mission-bound.
- Snapshot excludes irrelevant raw workspace payloads.
- Evidence refs and authority labels are preserved.
- No production workspace schema migration.

Risks:
Context compiler becomes a prompt dumping path.

Rollback strategy:
Remove experimental projection and benchmarks; production workspace remains
unchanged.

## Phase 3 - Workspace-native Model

Goal:
Build empirical baselines before any SFT/LoRA decision.

Existing assets:
Local/cloud model paths, eval tools, scenario fixtures, pydantic-evals
dependency.

Changes:
Define training/eval dataset schema and run baseline prompt/context tests.

Artifacts:
Corpus schema, anti-leakage policy, baseline reports, Workspace Dependency
Score report.

Experiments:

- Stage A prompt/context baseline.
- Compare current local model vs cloud model on authority preservation.
- Generate a tiny controlled synthetic set and validate it.

Acceptance gates:

- TRAIN, VALIDATION, FROZEN GOLD, ADVERSARIAL, and LIVE WORKSPACE split rules
  are explicit.
- Frozen tests are not used in prompts or training.
- Candidate/shadow/reviewed/operational labels are preserved.
- SFT/LoRA is not approved without measured need.

Risks:
Leaking eval cases into training or few-shot prompts; optimizing answer fluency
instead of evidence discipline.

Rollback strategy:
Discard generated corpus artifacts; keep only validated benchmark summaries.

## Phase 4 - Adaptive Runtime

Goal:
Route model requests based on task, connectivity, privacy, latency, energy,
required capability, and safety classification.

Existing assets:
Model policy, SLA gateway, Hailo local profile, cloud profile, fallback evals.

Changes:
Add experimental runtime router and bounded inference queue.

Artifacts:
Runtime router, queue policy, execution records, fallback matrix, resource
benchmark report.

Experiments:

- `LOCAL_FAST` for classification/schema extraction.
- `LOCAL_REASONING` or `HAILO` for offline route Q&A.
- `MAX` spike if available.
- `CLOUD_REASONING` for heavy research when allowed.

Acceptance gates:

- Silent routing is forbidden.
- `max_local_llm_concurrency=1` works on Raspberry Pi profile.
- Timeout, cancellation, budget, and backpressure are tested.
- Cloud unavailable still yields local degraded answer with uncertainty.

Risks:
Router becomes an untestable policy blob or silently changes answer authority.

Rollback strategy:
Feature-flag router off and route through current model policy/gateway.

## Phase 5 - Specialized Compute

Goal:
Benchmark high-cost terrain/sensor kernels before considering Mojo or other
specialized compute paths.

Existing assets:
DEM/DTM, terrain intelligence, QGIS candidate workflows, Pi/Hailo deployment
notes, route preparation tools.

Changes:
Add benchmarks first; only then optional Mojo or optimized native kernels.

Artifacts:
Benchmark harness, Pi vs Mac/server comparison, algorithm-level latency/memory/
energy report.

Experiments:

- DEM slope/aspect/curvature.
- Ridge/saddle/drainage candidate extraction.
- IMU/PDR filtering.
- Raster subset processing.

Acceptance gates:

- Same input data and algorithms are compared across Python/GDAL/QGIS/Mojo or
  other candidates.
- Improvement is measured in latency, energy, memory, or throughput.
- Output equivalence or acceptable tolerance is defined.
- Runtime safety authority remains unchanged.

Risks:
Premature kernel rewrite; platform-specific complexity without measurable
benefit.

Rollback strategy:
Keep Python/GDAL/QGIS baseline as the default and remove experimental kernels.

## Immediate Recommendations

1. Approve Phase 0 findings before code migration.
2. Start Phase 1 with an experimental `ScoutModelRuntime` protocol only if it
   wraps existing provider behavior instead of replacing it.
3. Start Phase 2 with one `ScoutWorkspaceSnapshot v0` terrain/status fixture.
4. Keep PraisonAI behind a future MCP Intelligence Service facade and validate
   that it adds value before making it a dependency.
5. Treat MAX and Mojo as independent feasibility spikes with benchmark packets,
   not architectural commitments.

## Experiment Packet Template

```yaml
experiment_id:
hypothesis:
current_baseline:
proposed_architecture:
implementation_scope:
expected_benefit:
risks:
test_dataset:
metrics:
results:
regression:
decision: MORE_EVIDENCE_REQUIRED
rollback_strategy:
```

Every NextGen research task should end with one of:

- ACCEPT
- CONTINUE_RESEARCH
- REJECT
- MORE_EVIDENCE_REQUIRED
