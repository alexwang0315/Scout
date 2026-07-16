# Scout AI OS MVP Specification

**Document version:** 0.1.1
**Date:** 2026-06-30
**Audience:** Codex / coding agent / human implementer
**Target platform:** Raspberry Pi edge controller + remote LLM APIs + future mobile companion runtime
**Primary language:** Python 3.12+

---

## 1. Executive Summary

Scout AI OS is an adaptive workflow agent platform. Its purpose is to accept a user's ad-hoc natural-language request, compile that request into a typed workflow, search existing capabilities, compose or build missing low-risk capabilities, verify them in a sandbox, install executable workflows, notify the user when conditions are met, and save reusable learning artifacts for future similar requests.

Scout must not be a pure chatbot. It must be a controlled automation system where the LLM plans and proposes, while deterministic runtime code validates, persists, executes, audits, and enforces permissions.

### 1.0.1 First Deployment Assumption

The first field deployment is remote-operated: only Scout AI accompanies the
user as the mobile-facing interaction layer. The phone sends user requests,
location/sensor summaries, photos or event metadata, and device status back to
the server-room Scout stack. The main software, models, web research,
workspace tools, computer-use/browser-use executors, databases, and hardware
gateways run in the server room or trusted workstation environment. Users
communicate with Scout software and hardware through Scout AI.

### 1.0 Current Implementation Snapshot

This repository now implements Phase 0 through Phase 9 of the Scout AI OS MVP
architecture. The implemented core includes:

- typed Pydantic schema contracts for workflows, capabilities, permissions,
  runtime, sandbox, and learning artifacts;
- deterministic SQLite stores and permission gates;
- local notification gateway and runtime tick loop;
- provider-backed agent facades with a local `FunctionModel` default;
- model policy, timeout/cost SLA gateway, and external-model fallback handling;
- Pydantic AI v2.10.0 compatibility helpers;
- generated capability sandbox verification;
- FastAPI routes and focused API/runtime tests;
- Scout AI read-only workspace tool workflow:
  context registry -> tool plan -> evidence collection -> answer synthesis;
- weather/environment workspace tools for CWA and GEE artifacts;
- route-context, route-mileage, and raster OCR evidence lookup tools;
- Mac local chat fallback mode for Scout hardware-unavailable development.

The MVP is still not allowed to let model output mutate Phase 1 safety state,
call `/safety/*`, write Phase 2 Brain observed facts, directly send outbound
messages, or directly control hardware. A reviewed non-safety outbound action
may execute only through a typed `OutboundActionIntent`, an active
`OutboundStandingGrant`, and a deterministic sender that records audit evidence.

### 1.1 Core Product Promise

When the user says something like:

```text
Notify me 100 meters before the next campsite.
```

or:

```text
Whenever I receive a camping gear order email, extract the items and add them to my trip checklist.
```

or:

```text
Watch this campsite booking page and notify me when a slot opens.
```

Scout should:

1. Understand the request.
2. Convert it into a structured workflow specification.
3. Determine what data, tools, permissions, and runtime are required.
4. Search existing capabilities and workflow templates.
5. Use existing capabilities where possible.
6. Generate a new low-risk capability only when necessary.
7. Verify generated code in a sandbox before installation.
8. Ask for approval when required.
9. Install and execute the workflow through a deterministic runtime.
10. Record events and outcomes.
11. Save reusable artifacts such as memory, workflow templates, skills, capabilities, and eval cases.

---

## 2. Product Scope

### 2.1 MVP Goal

Build a Raspberry Pi-compatible Scout core that supports:

- Natural-language request intake.
- Pydantic AI-based workflow compilation.
- Pydantic AI v2.10.0 model execution with explicit model policy, OpenRouter and
  OpenAI-chat provider semantics, and local FunctionModel fallback.
- Capability search and registry.
- Execution planning.
- Permission checks.
- SQLite-backed workflow persistence.
- Simple scheduler / runtime loop.
- Notification gateway abstraction.
- Sandbox verifier for low-risk generated Python capabilities.
- Learning artifact generation.
- FastAPI endpoints for user requests, workflows, approvals, capabilities, and learning artifacts.
- Read-only Scout AI evidence workflows for pretrip/admin/debug questions.
- Mac-local fallback UI path when Scout hardware is unavailable.
- Automated tests.

### 2.2 Non-Goals for MVP

Do **not** build these in the MVP:

- Full mobile app.
- Production background GPS runtime.
- Unscoped destructive browser automation. Trusted server-room computer-use and
  browser-use are first-class Scout AI capabilities when they run through the
  reviewed executor path and record provenance.
- Kubernetes deployment.
- Full Temporal cluster.
- Large vector database.
- Local large language model inference.
- Payment automation.
- External message sending without approval.
- Production database modification tools.
- Unscoped destructive shell execution outside the trusted server-room executor
  capability.
- Autonomous self-modification of Scout core code.

### 2.3 Future Extensions

The MVP should be designed so these can be added later:

- Mobile companion app for location, sensors, local notifications, and offline route monitoring.
- Cloud or VPS worker for heavy web monitoring, browser automation, embeddings, and long-running tasks.
- MCP integration for external services.
- DBOS / Temporal / Prefect durable execution.
- Rich notification channels.
- Pydantic Graph state-machine orchestration.
- Pydantic Evals-based regression suite.
- Logfire / OpenTelemetry observability.

---

## 3. Design Principles

### 3.1 LLM Plans, Runtime Executes

LLM agents may:

- Understand user intent.
- Produce typed workflow specs.
- Search memory and capability metadata.
- Propose execution plans.
- Generate low-risk candidate capability code.
- Propose learning artifacts.

Deterministic runtime code must:

- Validate schemas.
- Enforce permissions.
- Persist workflows.
- Execute workflows.
- Send notifications.
- Run sandbox tests.
- Install capabilities only after validation.
- Record audit events.

### 3.2 Everything Important Is Typed

Core contracts must be represented as Pydantic models:

- `WorkflowSpec`
- `TriggerSpec`
- `ConditionSpec`
- `ActionSpec`
- `PermissionSpec`
- `CapabilitySpec`
- `ExecutionPlan`
- `CapabilityBuildRequest`
- `GeneratedCapabilityPackage`
- `SandboxResult`
- `LearningArtifact`
- `LearningBundle`

### 3.3 Generated Code Is Guilty Until Proven Safe

Generated code must not be installed or executed outside sandbox unless:

1. It is classified as low risk.
2. It has an explicit `CapabilitySpec`.
3. It includes tests.
4. Sandbox tests pass.
5. Static security checks do not find disallowed patterns.
6. The permission gate approves installation.
7. For generated capabilities, user approval is required at least during early MVP.

### 3.4 Permanent Automation Requires Explicit Approval

Any workflow that runs beyond the current request or session must require user approval when it involves:

- Location.
- Private data.
- Email.
- Calendar.
- Files.
- Notifications.
- Web monitoring.
- Long-term background execution.
- External API calls.
- Generated code.

### 3.5 Learning Artifacts Are Reviewable

Scout should produce learning candidates, not silently mutate its long-term behavior. Learning artifacts should be reviewable and approveable.

---

## 4. System Architecture

### 4.1 High-Level Architecture

```text
User Request
   ↓
FastAPI Request API
   ↓
WorkflowCompilerAgent
   ↓
ExecutionPlannerAgent
   ↓
PermissionGate
   ↓
CapabilityRegistry ───┐
   ↓                   │
Existing capability?   │
   ↓                   │
Install Workflow       │
   ↓                   │
Workflow Runtime       │
   ↓                   │
NotificationGateway    │
   ↓                   │
LearningAgent ◄────────┘
   ↓
Memory / Skill / Template / Eval candidates
```

When a missing low-risk capability is needed:

```text
ExecutionPlannerAgent
   ↓
CodeBuilderAgent
   ↓
SandboxRunner
   ↓
PermissionGate
   ↓
CapabilityRegistry.install()
   ↓
Workflow Runtime
```

### 4.2 Deployment Topology

```text
Raspberry Pi Scout Core
- FastAPI server
- SQLite database
- Scheduler/runtime loop
- Capability registry
- Permission gate
- Sandbox runner
- Notification gateway
- Memory and learning stores
- Pydantic AI orchestration client

Remote LLM API
- Workflow compilation
- Execution planning
- Code generation
- Learning artifact generation

Future Mobile Runtime
- GPS
- sensors
- local notification
- offline route monitoring

Future Cloud Worker
- heavy web monitoring
- browser automation
- large evals
- large embeddings
```

### 4.3 Required Python Packages

MVP package choices:

```text
python >= 3.12
pydantic >= 2
pydantic-ai-slim[openai,openrouter] == 2.10.0
pydantic-evals == 2.10.0
fastapi
uvicorn
aiosqlite or sqlite3 wrapper
pyyaml
pytest
pytest-asyncio
ruff
httpx
apscheduler or simple custom async scheduler
```

Optional later:

```text
pydantic-evals
pydantic-graph
logfire
sqlite-vec
dbos
mcp clients
```

Pydantic AI v2.10.0 operating rules:

- Scout's package path uses `pydantic-ai-slim` with `openai` and `openrouter`
  extras for Pi compatibility.
- `pydantic_ai.Agent` calls must keep `end_strategy="early"` unless a future
  reviewed design proves that continuing same-turn tool execution cannot
  violate Scout's no-side-effect defaults.
- Pydantic AI v2.10.0 preserves `end_strategy="early"` for native, prompted,
  and image outputs. Scout keeps regression coverage on the existing early-stop
  contract instead of adding a compatibility workaround.
- `RunContext.usage_limits` is available to tools and capabilities in v2.10.0.
  It may be used for telemetry and local preflight decisions, but it does not
  replace Scout's deterministic permission, cost, timeout, or execution gates.
- NVIDIA-hosted GLM uses `SCOUT_AI_OS_MODEL=z-ai/glm-5.2` and requires
  `NVIDIA_API_KEY`. Scout routes the request to NVIDIA's OpenAI-compatible
  endpoint and sends `z-ai/glm-5.2` as the provider model id.
- OpenRouter models use `openrouter:<vendor/model>` and require
  `OPENROUTER_API_KEY`.
- Direct OpenAI chat models use `openai-chat:<model>` and require
  `OPENAI_API_KEY`. If an operator supplies `openai:<model>`, Scout normalizes
  it to `openai-chat:<model>` to avoid an implicit switch to the OpenAI
  Responses API behavior.
- Native WebSearch and WebFetch are enabled by default for external
  provider-backed Scout AI calls. Scout AI is the full-capability user entry;
  tools, web research, local fallback, and deterministic runtime services are
  support layers. Operators may opt out for lab/CI with
  `SCOUT_AI_OS_NATIVE_RESEARCH=0`, or constrain domains with the native
  research domain env vars.
- Provider-native MCP remains disabled until a separate Scout
  connector/capability and the required Pydantic AI optional dependency are
  reviewed and explicitly enabled.

---

## 5. Repository Structure

Create this structure:

```text
scout/
  pyproject.toml
  README.md
  AGENTS.md

  docs/
    SCOUT_AI_OS_MVP_SPEC.md
    IMPLEMENTATION_PLAN.md
    ARCHITECTURE.md
    SECURITY_MODEL.md
    API.md

  src/scout/
    __init__.py
    main.py
    config.py

    schemas/
      __init__.py
      workflow.py
      capability.py
      learning.py
      permissions.py
      runtime.py

    agents/
      __init__.py
      deps.py
      workflow_compiler.py
      execution_planner.py
      code_builder.py
      learner.py

    services/
      __init__.py
      db.py
      workflow_store.py
      capability_registry.py
      memory_store.py
      permission_gate.py
      sandbox_runner.py
      notification_gateway.py
      docs_search.py

    runtime/
      __init__.py
      scheduler.py
      executor.py
      triggers.py
      actions.py

    api/
      __init__.py
      routes.py

    capabilities/
      __init__.py
      builtins/
        manual_notification/
          capability.yaml
          implementation.py
          tests/
        time_reminder/
          capability.yaml
          implementation.py
          tests/
        json_transform/
          capability.yaml
          implementation.py
          tests/

  tests/
    test_workflow_schema.py
    test_capability_schema.py
    test_permission_gate.py
    test_workflow_store.py
    test_capability_registry.py
    test_runtime_executor.py
    test_sandbox_runner.py
    test_api_requests.py
    test_learning_artifacts.py
```

---

## 6. Core Domain Models

Implement these in `src/scout/schemas/`.

### 6.1 Workflow Models

```python
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class WorkflowLifecycle(str, Enum):
    ONE_SHOT = "one_shot"
    SESSION_SCOPED = "session_scoped"
    TRIP_SCOPED = "trip_scoped"
    PERMANENT = "permanent"


class RuntimeTarget(str, Enum):
    DEVICE = "device"
    PI = "pi"
    CLOUD = "cloud"
    BROWSER = "browser"
    SANDBOX = "sandbox"
    HYBRID = "hybrid"


class TriggerType(str, Enum):
    MANUAL = "manual"
    TIME = "time"
    LOCATION = "location"
    SENSOR = "sensor"
    EMAIL = "email"
    CALENDAR = "calendar"
    WEB_CHANGE = "web_change"
    API_EVENT = "api_event"
    FILE_CHANGE = "file_change"
    COMPOUND = "compound"


class ActionType(str, Enum):
    NOTIFY = "notify"
    ASK_USER = "ask_user"
    CREATE_TASK = "create_task"
    UPDATE_CHECKLIST = "update_checklist"
    CALL_API = "call_api"
    RUN_CAPABILITY = "run_capability"
    RUN_SANDBOX_SCRIPT = "run_sandbox_script"
    SAVE_TEMPLATE = "save_template"


class TriggerSpec(BaseModel):
    type: TriggerType
    description: str
    config: dict[str, Any] = Field(default_factory=dict)


class ConditionSpec(BaseModel):
    description: str
    expression: str
    required_data_sources: list[str] = Field(default_factory=list)


class ActionSpec(BaseModel):
    type: ActionType
    description: str
    config: dict[str, Any] = Field(default_factory=dict)


class PermissionSpec(BaseModel):
    required: list[str] = Field(default_factory=list)
    approval_required: bool = False
    reason: str = ""


class WorkflowSpec(BaseModel):
    id: str | None = None
    name: str
    source_utterance: str
    user_goal: str
    trigger: TriggerSpec
    conditions: list[ConditionSpec] = Field(default_factory=list)
    actions: list[ActionSpec]
    lifecycle: WorkflowLifecycle
    runtime: RuntimeTarget
    permissions: PermissionSpec
    fallback_policy: dict[str, Any] = Field(default_factory=dict)
    verification_plan: list[str] = Field(default_factory=list)
    learning_candidates: list[str] = Field(default_factory=list)
```

### 6.2 Capability Models

```python
class CapabilityRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CapabilityRuntime(str, Enum):
    PYTHON = "python"
    DEVICE_NATIVE = "device_native"
    PI_SERVICE = "pi_service"
    CLOUD_WORKER = "cloud_worker"
    BROWSER = "browser"
    MCP = "mcp"


class InstallScope(str, Enum):
    SESSION = "session"
    USER = "user"
    GLOBAL = "global"


class CapabilitySpec(BaseModel):
    name: str
    description: str
    version: str = "0.1.0"
    runtime: CapabilityRuntime
    risk_level: CapabilityRisk
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    examples: list[dict[str, Any]] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    install_scope: InstallScope = InstallScope.USER
```

### 6.3 Execution Plan Models

```python
class PlanMode(str, Enum):
    USE_EXISTING = "use_existing"
    COMPOSE_EXISTING = "compose_existing"
    BUILD_NEW_CAPABILITY = "build_new_capability"
    ASK_PERMISSION = "ask_permission"
    ASK_CLARIFICATION = "ask_clarification"
    REFUSE_AUTOMATION = "refuse_automation"


class ExecutionPlan(BaseModel):
    mode: PlanMode
    reason: str
    workflow: WorkflowSpec
    required_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    approval_message: str | None = None
    build_request: dict[str, Any] | None = None
    safety_notes: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
```

### 6.4 Capability Build Models

```python
class CapabilityBuildRequest(BaseModel):
    capability_name: str
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    constraints: list[str] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: CapabilityRisk


class GeneratedCapabilityPackage(BaseModel):
    spec: CapabilitySpec
    files: dict[str, str]
    tests: dict[str, str]
    install_notes: str
    security_notes: list[str] = Field(default_factory=list)
```

### 6.5 Sandbox Models

```python
class SandboxResult(BaseModel):
    passed: bool
    stdout: str = ""
    stderr: str = ""
    test_summary: str = ""
    security_findings: list[str] = Field(default_factory=list)
    resource_usage: dict[str, Any] = Field(default_factory=dict)


class InstallDecision(BaseModel):
    approved_for_install: bool
    reason: str
    install_scope: InstallScope | None = None
    required_user_approval: bool = False
```

### 6.6 Learning Models

```python
class LearningArtifactType(str, Enum):
    MEMORY = "memory"
    WORKFLOW_TEMPLATE = "workflow_template"
    SKILL = "skill"
    CAPABILITY = "capability"
    EVAL_CASE = "eval_case"


class LearningArtifact(BaseModel):
    type: LearningArtifactType
    title: str
    reason: str
    content: dict[str, Any]
    requires_review: bool = True


class LearningBundle(BaseModel):
    artifacts: list[LearningArtifact]
    summary: str
```

---

## 7. Pydantic AI Agents

Implement these in `src/scout/agents/`.

### 7.1 ScoutDeps

```python
from dataclasses import dataclass


@dataclass
class ScoutDeps:
    capability_registry: "CapabilityRegistry"
    memory_store: "MemoryStore"
    workflow_store: "WorkflowStore"
    sandbox: "SandboxRunner"
    permission_gate: "PermissionGate"
    notification_gateway: "NotificationGateway"
    docs_search: "DocsSearch"
    user_id: str
    active_context: dict
```

### 7.2 WorkflowCompilerAgent

Purpose: convert natural language into `WorkflowSpec`.

Rules:

- Must not execute actions.
- Must not claim the workflow is installed.
- Must mark required permissions.
- Must set `approval_required = true` for sensitive or persistent workflows.
- If details are ambiguous, put assumptions in `fallback_policy` and checks in `verification_plan`.
- Must prefer safe defaults.

Tools:

- `search_memory(query: str) -> list[str]`
- `search_capabilities(query: str) -> list[dict]`
- `get_active_context() -> dict`

Output:

- `WorkflowSpec`

### 7.3 ExecutionPlannerAgent

Purpose: decide how to execute a `WorkflowSpec`.

Rules:

- Prefer existing capabilities.
- Compose capabilities before generating new code.
- Propose `BUILD_NEW_CAPABILITY` only for low-risk parser, formatter, classifier, calculator, validator, or data transformer capabilities.
- Never approve high-risk generated code.
- Must produce approval message when required.

Tools:

- `search_capabilities(query: str) -> list[dict]`
- `get_capability(name: str) -> dict | None`

Output:

- `ExecutionPlan`

### 7.4 CodeBuilderAgent

Purpose: generate a low-risk Python capability package.

Rules:

- Must output a `GeneratedCapabilityPackage`.
- Must include implementation and tests.
- Must not use unrestricted shell execution.
- Must not read secrets.
- Must not access the network by default.
- Must not write outside its working directory.
- Must not implement payments, deletion, production DB writes, credential access, or message sending.

Output:

- `GeneratedCapabilityPackage`

### 7.5 LearningAgent

Purpose: propose reviewable learning artifacts after workflow installation or execution.

Rules:

- Do not save secrets.
- Do not convert a one-off detail into a permanent preference.
- Prefer candidates requiring review.
- Produce eval cases for workflow compiler regression.
- Produce workflow templates only when the pattern is reusable.

Output:

- `LearningBundle`

### 7.6 Pydantic AI v2.10.0 Provider Policy

Scout AI OS uses Pydantic AI v2.10.0 as a typed provider facade, not as an
unbounded autonomous runtime.

Provider modes:

- local `FunctionModel`: default for tests, Mac smoke, and no-credential runs;
- `z-ai/glm-5.2`: external NVIDIA OpenAI-compatible provider model id, gated
  by `NVIDIA_API_KEY`;
- `nvidia:<model-id>`: internal or advanced NVIDIA provider route, gated by
  `NVIDIA_API_KEY`;
- `openrouter:<vendor/model>`: external OpenRouter provider, gated by
  `OPENROUTER_API_KEY`;
- `openai-chat:<model>`: direct OpenAI chat provider, gated by
  `OPENAI_API_KEY`;
- `openai:<model>`: accepted only as an operator convenience alias and
  normalized to `openai-chat:<model>`.

Required provider behavior:

- model policy output may report requested model, normalized model, timeout,
  estimated cost, fallback model, and missing credential env names;
- model policy output must never contain token values;
- all provider calls use Scout's SLA gateway for timeout, budget preflight,
  provider health, fallback, and telemetry;
- local fallback is allowed for read-only interpretation only;
- `end_strategy="early"` is required for typed Scout `Agent` calls;
- native WebSearch and WebFetch are enabled by default for external
  provider-backed Scout AI calls; `SCOUT_AI_OS_NATIVE_RESEARCH=0` is only a
  lab/CI opt-out;
- provider-native MCP remains disabled until a reviewed Scout connector
  explicitly enables it.

### 7.7 Scout AI Route Context / Mileage / OCR Evidence Tools

The Scout AI assistant tool layer may expose deterministic workspace evidence
tools for route context, mileage anchors, and OCR labels:

- `scout.ai.route_context.assess.v0` /
  `pydantic_ai.tool.assess_scout_route_context.v0` reads
  `route_context_points_ref`, `route_mileage_k_anchors_ref`, and bounded
  `mileage_tag_alignment_ref` slices to answer questions such as "15K 在哪".
- `pydantic_ai.tool.search_scout_map_perception.v0` reads legacy MCP OCR and
  normalized raster OCR GeoJSON from `raster_label_evidence_ref`.
- `pydantic_ai.tool.search_scout_evidence_fulltext.v0` indexes route mileage
  anchors, mileage alignment summaries, normalized raster OCR, raw OCR
  summaries, route notes, and source snippets.

Required rules:

- large mileage alignment and OCR payloads must be summarized or sliced before
  model synthesis;
- raw tile pixels and raw provider payloads must not be embedded in assistant
  answers;
- all route-context, mileage, and OCR outputs remain candidate-only unless a
  reviewed package explicitly promotes them;
- no route-context/OCR answer may mutate review decisions, runtime handoff,
  Phase 1 safety state, `/safety/*`, outbound transport, or hardware.

### 7.8 Scout AI Weather / Environment Evidence Tools

The Scout AI assistant tool layer may expose deterministic workspace evidence
tools to the Pydantic AI provider. These tools are capabilities in the Scout AI
OS sense, but they are not runtime safety authorities.

Current weather/environment tool split:

- `scout.ai.weather_window.assess.v0`: route-local weather/daylight/camp/shelter
  decision framing.
- `scout.ai.cwa_environment.assess.v0`: prepared Central Weather Administration
  warnings, observations, QPF, forecast, astronomy, tide/marine, and provenance
  summaries from the local workspace.
- `scout.ai.gee_environment.assess.v0`: prepared GEE SMAP/GPM soil moisture,
  antecedent-rain, grid/timeline, and corridor hydrologic summaries from the
  local workspace.

Required rules:

- CWA and GEE credentials remain server-side. They are never exposed to the
  client, model prompt, artifact body, logs, or eval report.
- Assistant answering never performs live CWA, GEE, browser, or Earth Engine
  fetches. Live preparation is an operator-approved pretrip step that writes
  bounded workspace artifacts.
- Every CWA/GEE-derived result is candidate-only:
  `candidate_only=true`, `runtime_safety_truth=false`,
  `human_review_required=true`.
- Missing or stale QPF, warning, SMAP, GPM, or antecedent-rain artifacts are
  evidence gaps. The assistant must not convert missing weather evidence into a
  low-risk conclusion.
- QPF is route corridor / bbox evidence, not a single-slope forecast. SMAP/GPM
  is hydrologic background, not a deterministic landslide or water-level truth.
- No weather/environment tool may write Phase 1 L0-L4 state, `/safety/*`,
  Phase 2 Brain facts, ObservedFact, IncidentStore, review decisions, outbound
  messages, or hardware controls.

Planner rules:

- Natural weather questions select `weather_window` and CWA evidence.
- Rain, stream, wet terrain, rockfall, landslide, and weather-terrain compound
  questions additionally select GEE evidence.
- Pretrip Go/No-Go and delay/departure questions select route readiness plus
  route architecture, navigation terrain, weather window, CWA, GEE, pace, and
  equipment evidence when available.

### 7.9 Bounded Context and Progressive Tool Disclosure

The workspace-grounded Pydantic AI assistant must use a bounded AIOS thin
waist. It must not expose every registered tool, Total Info, full workspace
artifacts, or unselected native provider capabilities at the start of a turn.

Required flow:

1. discover up to ten ranked `ContextHandle` records without loading their full
   artifacts;
2. create a hard-capped `ToolPlan` from compact `ToolCard` records;
3. register only the selected full tool schemas;
4. execute tools through deterministic workspace services;
5. project raw results into sanitized, provenance-bearing `EvidenceCard` records;
6. remove all tools before answer synthesis;
7. verify citations and numeric claims deterministically;
8. verify or repair without tools, using the attempt's available call capacity;
9. checkpoint external limits and resume with a fresh recovery-stage budget.

The typed contracts are `ContextHandle`, `ContextReadResult`, `ToolCard`,
`PlannedToolCall`, `ToolPlan`, `EvidenceCard`, `AgentRunBudget`,
`AgentRequestLedger`, `AgentRunLedger`, and `GroundingVerification` in
`scout.schemas.agent_runtime`.

Construction call capacity and resource policy:

- every typed or unknown question class receives at least ten tool calls and ten
  model requests per attempt and per recovery stage; no surface, stage,
  average, p95, or static-fact policy may silently impose a lower capacity;
- independently metered planner, retriever, synthesis, verifier, reviewer,
  repair, retry, replan, browser, and subagent categories also default to ten;
- Aggressive Construction Mode sets Scout-defined input/output/total-token,
  tool-result-token, context-character, estimated-cost, answer-time, and
  replay-time ceilings to `null`; counters remain observability telemetry;
- explicit Productization/operator settings may restore resource SLOs, but must
  not silently lower an agent call category below ten;
- synthesis receives no tool definitions and cannot call another tool;
- a fail-closed response is not counted as a completed grounded answer;
- rejected draft claims remain audit metadata but are not user-visible claims.
- deterministic preflight and post-response checks enforce call counts. Reaching
  ten closes only the current stage; a checkpoint/continuation or next recovery
  stage receives a fresh 10/10 budget;
- non-greeting workspace questions with no selected tool evidence or bounded
  context evidence fail closed instead of returning an unverified direct answer;
- EvidenceCard projection recursively removes sensitive keys and secret-like
  values, rejects credentialed URLs and absolute paths, and withholds evidence
  explicitly marked private, secret, restricted, or confidential.

Ten is guaranteed available capacity rather than a utilization target. Duplicate canonical calls,
two consecutive calls without new evidence, and confirmed terminal evidence
gaps still stop early. A provider's technical limit checkpoints evidence, call
trace, and state and is reported as an external limit. After a failed attempt,
follow the finite ladder in `SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`: fix the
tool/evidence/harness and rerun with fresh 10/10, switch model with fresh 10/10,
build the complete Codex review artifact, then register a stable `KNOWN_ISSUE`
with an explicit unblock condition if Codex cannot resolve it.

The additive `/assistant/query` observability fields report per-request and
turn totals for system, history, schema, result, input, cache, output, request,
tool call, retry, repair, selected/executed tools, and budget stop reason.
Existing response fields must not be removed or renamed.

Provider-native WebSearch/WebFetch remain available to general trusted
provider calls. The bounded workspace path does not attach them unless a
future reviewed research ToolCard selects them; this prevents an unrelated
provider capability from increasing schemas or blocking models that do not
support the native form.

The regression and measurement contract is documented in
`docs/specs/scout-ai-bounded-context-progressive-disclosure.md`.

---

## 8. Deterministic Services

### 8.1 Database Service

Implement SQLite with WAL mode.

Required tables:

```sql
CREATE TABLE IF NOT EXISTS workflow_instances (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    runtime TEXT NOT NULL,
    workflow_json TEXT NOT NULL,
    next_run_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workflow_id) REFERENCES workflow_instances(id)
);

CREATE TABLE IF NOT EXISTS capabilities (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    status TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'builtin'
);

CREATE TABLE IF NOT EXISTS learning_artifacts (
    id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    source_workflow_id TEXT,
    content_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 8.2 WorkflowStore

Methods:

```python
install(workflow: WorkflowSpec, user_id: str, status: str = "active") -> str
save_pending(workflow: WorkflowSpec, user_id: str) -> str
list_workflows(user_id: str) -> list[WorkflowRecord]
get_workflow(workflow_id: str) -> WorkflowRecord | None
cancel(workflow_id: str, reason: str) -> None
pause(workflow_id: str, reason: str) -> None
complete(workflow_id: str) -> None
record_event(workflow_id: str, event_type: str, payload: dict) -> None
list_due_workflows(now: datetime) -> list[WorkflowRecord]
```

### 8.3 CapabilityRegistry

Methods:

```python
load_builtins(path: Path) -> None
install(package_or_spec) -> None
search(query: str) -> list[CapabilitySpec]
get(name: str) -> CapabilitySpec | None
list_all() -> list[CapabilitySpec]
```

Search can be simple keyword search in MVP. Add SQLite FTS later.

### 8.4 PermissionGate

PermissionGate must evaluate both workflows and capability installation.

Approval required when:

- Workflow lifecycle is `permanent`.
- Workflow uses location.
- Workflow reads private data.
- Workflow sends messages to other people.
- Workflow performs payment, ordering, deletion, or destructive edits.
- Workflow installs generated code.
- Workflow performs long-term background monitoring.
- Workflow performs external web monitoring or scraping.

High-risk actions must be denied by default in MVP.

Return model:

```python
class PermissionDecision(BaseModel):
    allowed: bool
    requires_user_approval: bool
    reason: str
    user_message: str
```

### 8.5 NotificationGateway

MVP implementation:

- Log notifications to stdout.
- Record a workflow event.
- Optionally write notifications to a local SQLite table or workflow events.

Interface:

```python
send(user_id: str, title: str, body: str, priority: str = "normal", metadata: dict | None = None) -> NotificationResult
```

Future implementations:

- Mobile push.
- ntfy.
- Telegram.
- LINE.
- Email.
- Home Assistant.
- MQTT.

### 8.6 SandboxRunner

MVP behavior:

- Create temporary directory.
- Write generated files and tests.
- Run tests with timeout.
- Do not pass secrets.
- Disable network if practical.
- Reject disallowed patterns before running.
- Return `SandboxResult`.

Disallowed patterns for MVP:

```text
subprocess
os.system
socket
requests
httpx
urllib
shutil.rmtree
open('/etc')
open('/home')
.env
API_KEY
SECRET
TOKEN
rm -rf
```

This is not a complete security sandbox. Document limitations clearly in `docs/SECURITY_MODEL.md`.

---

## 9. Runtime

### 9.1 Supported MVP Triggers

Implement fully:

- `manual`
- `time`

Stub interfaces for:

- `location`
- `sensor`
- `email`
- `calendar`
- `web_change`
- `api_event`
- `file_change`
- `compound`

### 9.2 Supported MVP Actions

Implement fully:

- `notify`
- `ask_user`
- `run_capability` for built-in low-risk capabilities

Stub interfaces for:

- `create_task`
- `update_checklist`
- `call_api`
- `run_sandbox_script`
- `save_template`

### 9.3 Workflow Executor

Algorithm:

```text
for each due workflow:
  load workflow
  evaluate permission gate
  if approval required:
    pause workflow
    record event
    continue
  evaluate trigger
  if trigger not satisfied:
    update next_run_at
    continue
  evaluate conditions
  if conditions fail:
    update next_run_at
    continue
  execute actions in order
  record event for each action
  if one_shot and success:
    complete workflow
  else:
    schedule next run
  if failure:
    increment retry_count
    record last_error
```

### 9.4 Scheduler

MVP can expose both:

- `POST /runtime/tick` for manual testing.
- Background scheduler loop when server starts.

Do not let the scheduler run generated code unless installed and approved.

---

## 10. API Specification

Implement in FastAPI.

### 10.1 POST `/requests`

Input:

```json
{
  "user_id": "user_123",
  "user_text": "Remind me in 10 minutes to check the stove.",
  "active_context": {}
}
```

Pipeline:

1. Run `WorkflowCompilerAgent`.
2. Run `ExecutionPlannerAgent`.
3. Evaluate permission.
4. If approval is required, save pending workflow and return approval request.
5. If missing low-risk capability, run `CodeBuilderAgent` and `SandboxRunner`.
6. Install capability if allowed.
7. Install workflow.
8. Generate learning candidates.
9. Return status.

Response examples:

```json
{
  "status": "installed",
  "workflow_id": "wf_123",
  "message": "Workflow installed."
}
```

```json
{
  "status": "needs_approval",
  "workflow_id": "wf_456",
  "message": "This workflow requires location and notification permissions. Approve to enable it."
}
```

### 10.2 GET `/workflows`

List workflows for a user.

Query:

```text
?user_id=user_123&status=active
```

### 10.3 GET `/workflows/{id}`

Return one workflow and recent events.

### 10.4 POST `/workflows/{id}/approve`

Approve a pending workflow.

Input:

```json
{
  "user_id": "user_123",
  "approval_note": "Approved for this trip only."
}
```

### 10.5 POST `/workflows/{id}/cancel`

Cancel workflow.

Input:

```json
{
  "user_id": "user_123",
  "reason": "No longer needed."
}
```

### 10.6 GET `/capabilities`

List installed capabilities.

### 10.7 GET `/learning-artifacts`

List reviewable learning artifacts.

### 10.8 POST `/learning-artifacts/{id}/approve`

Approve a learning artifact.

MVP behavior:

- Memory artifact: insert into memory store.
- Workflow template: mark approved but template application can be implemented later.
- Skill artifact: write Markdown file under `skills/` or store as DB row.
- Eval case: append to JSONL eval dataset.
- Capability artifact: link to already installed capability.

### 10.9 POST `/runtime/tick`

Manually run workflow tick for testing.

---

## 11. Built-In Capabilities

### 11.1 `manual_notification`

Purpose:

- Send a simple notification through NotificationGateway.

Risk:

- Low.

Permissions:

- `notification.send`

Input:

```json
{
  "title": "string",
  "body": "string",
  "priority": "normal"
}
```

Output:

```json
{
  "sent": true,
  "notification_id": "string"
}
```

### 11.2 `time_reminder`

Purpose:

- Install a one-shot time-based reminder.

Risk:

- Low for local notifications.
- Medium if repeating or permanent.

Permissions:

- `notification.send`

### 11.3 `json_transform`

Purpose:

- Transform JSON using simple Python logic.

Risk:

- Low if no network and no filesystem.

---

## 12. Learning System

### 12.1 Learning Artifacts

Scout should generate these after each workflow:

| Artifact | Purpose | Example |
|---|---|---|
| Memory | User preference, correction, failure | User prefers early reminders. |
| Workflow Template | Reusable workflow pattern | Notify before next POI. |
| Skill | Agent procedure | How to compile proximity reminders. |
| Capability | Reusable executable tool | `route_distance_to_next_poi` |
| Eval Case | Regression test | User utterance → expected WorkflowSpec |

### 12.2 Learning Rules

Do not store:

- Secrets.
- API keys.
- Tokens.
- Passwords.
- One-off incidental details as permanent preferences.
- Sensitive personal information unless explicitly approved.

### 12.3 Eval Case Format

Use JSONL for MVP:

```json
{
  "id": "case_location_001",
  "user_utterance": "Notify me 100 meters before the next campsite.",
  "expected": {
    "trigger_type": "location",
    "action_types": ["notify"],
    "lifecycle": "trip_scoped",
    "required_permissions": ["location.read", "notification.send"]
  }
}
```

---

## 13. Security Model

### 13.1 Risk Levels

| Risk | Examples | Default |
|---|---|---|
| Low | local parsing, formatting, notification draft, JSON transform | Allowed after validation |
| Medium | location, web monitoring, file read, calendar read | Approval required |
| High | payments, deletion, external messaging, credentials, production writes | Denied or explicit approval with hard safeguards |

### 13.2 Required Approval Cases

Approval required for:

- Permanent workflows.
- Location workflows.
- Reading private data.
- External web monitoring.
- Installing generated code.
- Any generated capability beyond low-risk transform.
- Sending messages to other people.
- Deleting or modifying user data.
- Payments or purchases.

### 13.3 Generated Code Policy

Generated code may only be:

- Python.
- Low-risk.
- Small.
- Tested.
- Sandboxed.
- Reviewed by PermissionGate.

Generated code may not:

- Access network by default.
- Access secrets.
- Use unrestricted shell.
- Modify production database.
- Delete user files.
- Send external messages.
- Perform purchases or payments.

### 13.4 Audit Requirements

Record events for:

- Workflow creation.
- Workflow approval.
- Workflow cancellation.
- Permission decisions.
- Capability search.
- Capability installation.
- Sandbox results.
- Runtime execution.
- Notifications.
- Learning artifact generation and approval.

---

## 14. Testing Requirements

### 14.1 Unit Tests

Required tests:

- Workflow schema validation.
- Capability schema validation.
- Execution plan schema validation.
- PermissionGate allows low-risk workflow.
- PermissionGate requires approval for location.
- PermissionGate denies high-risk generated code.
- WorkflowStore install/list/get/cancel/complete.
- CapabilityRegistry load/search/get.
- NotificationGateway logs notification.
- SandboxRunner passes valid generated package.
- SandboxRunner fails invalid package.
- SandboxRunner blocks disallowed patterns.

### 14.2 API Tests

Required API tests:

- POST `/requests` with simple manual notification.
- POST `/requests` with permanent workflow returns `needs_approval`.
- POST `/workflows/{id}/approve` activates pending workflow.
- POST `/workflows/{id}/cancel` cancels workflow.
- GET `/capabilities` returns built-ins.
- POST `/runtime/tick` executes due notification workflow.

### 14.3 Agent Contract Tests

Use fake models or fixtures where practical.

Required contract cases:

- “Remind me in 10 minutes to check the stove.” → time trigger, notify action, one-shot.
- “Every day at 8am remind me to check campsite booking.” → time trigger, notification, approval required if permanent.
- “Notify me 100 meters before the next campsite.” → location trigger, notify action, location permission required.
- “Delete all old files every night.” → destructive action, high-risk, refuse or require explicit approval; MVP should deny automation.
- “Generate a parser for this CSV format.” → build low-risk capability allowed only after sandbox tests.

### 14.4 Commands

Minimum commands:

```bash
pytest
ruff check .
uvicorn scout.main:app --reload
```

---

## 15. Implementation Phases

### Phase 0 — Repository Inspection and Planning

Codex should:

1. Inspect the repository.
2. Report existing files.
3. Create or update `AGENTS.md`.
4. Create `docs/IMPLEMENTATION_PLAN.md`.
5. Do not implement all features yet.

### Phase 1 — Scaffold

Create structure, package config, empty modules, README, docs.

### Phase 2 — Schemas

Implement Pydantic domain models and tests.

### Phase 3 — Database and Stores

Implement SQLite setup, WorkflowStore, CapabilityRegistry, MemoryStore.

### Phase 4 — Permission and Runtime Basics

Implement PermissionGate, NotificationGateway, RuntimeExecutor, Scheduler tick.

### Phase 5 — Pydantic AI Agents

Implement WorkflowCompilerAgent, ExecutionPlannerAgent, CodeBuilderAgent, LearningAgent with typed outputs.

### Phase 6 — Sandbox

Implement SandboxRunner and generated capability package verification.

### Phase 7 — API

Implement FastAPI routes and tests.

### Phase 8 — Learning Loop

Implement learning candidates, approval endpoint, JSONL eval case output.

### Phase 9 — Documentation and Hardening

Complete README, ARCHITECTURE, SECURITY_MODEL, API docs, tests, and acceptance criteria.

---

## 16. Acceptance Criteria

The MVP is acceptable when:

1. `pytest` passes.
2. `ruff check .` passes or ruff is explicitly configured and documented.
3. FastAPI app starts with `uvicorn scout.main:app --reload`.
4. Built-in capabilities load from YAML.
5. SQLite database initializes with required tables.
6. A simple manual notification request can be installed and executed.
7. A time reminder can be installed and executed by `/runtime/tick`.
8. Location and permanent workflows require approval.
9. High-risk destructive automation is denied in MVP.
10. Generated code is never installed if sandbox tests fail.
11. Workflow events are recorded.
12. Learning artifacts are generated as reviewable candidates.
13. README explains how to run the MVP on Raspberry Pi.
14. SECURITY_MODEL explains sandbox limitations and generated code policy.
15. Codex can continue implementation by following `AGENTS.md` and docs.

---

## 17. Codex Work Instructions

When using Codex, start with this task:

```text
Read docs/SCOUT_AI_OS_MVP_SPEC.md and AGENTS.md.
Implement Phase 0 and Phase 1 only.
Do not implement all business logic yet.
Create the project scaffold, docs, pyproject.toml, placeholder modules, and minimal tests that verify importability.
Run pytest and ruff if configured.
Summarize what changed and propose the next phase.
```

Then proceed phase by phase:

```text
Implement Phase 2 only: core Pydantic schemas and tests.
```

```text
Implement Phase 3 only: SQLite database, WorkflowStore, CapabilityRegistry, MemoryStore, and tests.
```

```text
Implement Phase 4 only: PermissionGate, NotificationGateway, RuntimeExecutor, scheduler tick, and tests.
```

```text
Implement Phase 5 only: Pydantic AI agents with typed outputs and safe instructions. Use fake models in tests if needed.
```

```text
Implement Phase 6 only: SandboxRunner and generated capability verification.
```

```text
Implement Phase 7 only: FastAPI routes and API tests.
```

```text
Implement Phase 8 only: Learning artifacts and approval flow.
```

```text
Implement Phase 9 only: documentation, hardening, and acceptance cleanup.
```

---

## 18. Suggested AGENTS.md Content

Create this at repository root:

```markdown
# AGENTS.md

## Project

This repository implements Scout AI OS MVP: an adaptive workflow agent runtime that compiles user requests into typed workflows, searches and installs capabilities, executes workflows through deterministic runtime services, and stores learning artifacts for future reuse.

## Core Principle

LLM agents may plan, compile specs, generate candidate code, and propose learning artifacts.

Deterministic runtime code must:
- validate schemas
- enforce permissions
- execute workflows
- run sandbox tests
- persist state
- record audit events

Generated code must never be installed or executed outside sandbox without validation and permission checks.

## MVP Constraints

- Python 3.12+
- Pydantic v2
- Pydantic AI
- FastAPI
- SQLite WAL
- pytest
- ruff
- Raspberry Pi compatible
- Avoid heavy infrastructure
- Avoid Kubernetes
- Avoid heavyweight vector DB
- Avoid Temporal in MVP
- Avoid browser automation in MVP except as an interface stub

## Safety Rules

Always require approval for:
- long-term background monitoring
- location access
- reading private data
- sending messages to other people
- payments
- deleting or modifying user data
- installing permanent workflows
- installing generated code
- networked scraping or external automation

Never:
- hardcode secrets
- read .env values in tests unless explicitly mocked
- allow generated code unrestricted shell access
- allow generated code production database writes
- allow generated code network access by default
- silently convert one-off details into permanent memory

## Testing

Before considering a phase complete, run:

```bash
pytest
ruff check .
```

If a tool is not configured yet, add configuration or document the reason.

## Style

- Prefer small, typed modules.
- Use Pydantic models for contracts.
- Keep agents thin and typed.
- Keep runtime deterministic.
- Keep services testable through interfaces.
- Use clear docstrings for public functions.
- Add TODO comments only for intentional MVP stubs.

## Architecture Boundaries

Agents:
- workflow_compiler
- execution_planner
- code_builder
- learner

Services:
- workflow_store
- capability_registry
- permission_gate
- sandbox_runner
- notification_gateway
- memory_store
- docs_search

Runtime:
- scheduler
- executor
- triggers
- actions

Schemas:
- workflow
- capability
- learning
- permissions
- runtime
```

---

## 19. Notes for Human Owner

The MVP intentionally treats many powerful functions as stubs. This is correct. The immediate objective is not to build every integration; it is to establish the safe operating system loop:

```text
natural language → typed workflow → capability search → permission check → runtime execution → learning artifact
```

Once this loop is reliable, add integrations one by one.

Recommended integration order:

1. Mobile notification bridge.
2. Time reminders.
3. Local checklist store.
4. Web page polling.
5. Email metadata trigger.
6. Calendar read trigger.
7. Location workflow via mobile runtime.
8. Cloud worker for heavier tasks.
9. Pydantic Evals dataset.
10. Pydantic Graph orchestration.
