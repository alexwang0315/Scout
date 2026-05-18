# Spec: Scout Cross-Surface AI Assistant Guardrails

## Status

Proposed.

This document defines a small cross-surface milestone for Scout. It should be
reviewed before implementation starts.

## Milestone Name

Recommended name:

```text
Milestone 10: Cross-Surface AI Assistant Guardrails
```

Alternative phase-style name:

```text
Phase 3.6: Cross-Surface AI Assistant Readiness
```

Use `Milestone 10` in implementation notes because this capability cuts across
admin, debug, pre-planning, and future hardware-readiness surfaces. It should
not be treated as a sub-feature of Phase 3.5 or Phase 4.

## Assumptions

- Phase 1 remains the deterministic live safety authority.
- Phase 3.5 runtime debug tooling is complete and read-only.
- Phase 4 pre-trip planning remains a candidate/provenance/review workspace.
- Existing Pydantic AI usage in `agent.py` and `server.py` is navigation advice
  over already-computed context, not PDR math, route-progress logic, or safety
  state transition logic.
- The first implementation should be mock-backed and deterministic before any
  live Pydantic AI provider is enabled.
- The assistant is a data-state explanation tool first. It must not trigger
  irreversible runtime, store, review, outbound, or hardware actions.

## Objective

Build a shared Scout AI assistant capability that can be embedded into multiple
admin-facing surfaces while preserving each surface's constraints.

The assistant should answer questions such as:

```text
Why did Scout enter L2?
Which provider was degraded at this timeline node?
What incident package was created from this event?
What pre-trip candidates still need review?
Which source registry items support this planning decision?
What is the current departure/readiness gate state?
What hardware-readiness provider looks degraded?
```

Success means Scout can offer useful data-state answers without turning model
output into facts, runtime decisions, planning approvals, or outbound actions.

## Non-Goals

This milestone must not:

- change Phase 1 safety decisions;
- call `/safety/*` mutation endpoints;
- write `ObservedFact`, `DerivedMeasurement`, `HumanReview`, review decisions,
  or IncidentStore records;
- modify Phase 2 Brain data;
- accept or reject pre-trip planning candidates;
- send outbound messages;
- control hardware, sensors, providers, transport, SOS, SMS, or satellite
  integrations;
- replace `/navigate` or make Pydantic AI part of PDR, route progress, risk
  rules, or L0-L4 state transitions.

## Chinese Guardrails

中文註釋：這不是 Scout safety runtime。AI assistant 只能解釋目前資料狀態，不可以影響 Phase 1 route progress、risk rules、IncidentPackage 或 L0-L4 決策。

中文註釋：這不是自動規劃批准。pre-planning 介面中的 AI 回答只能說明 candidate、source、review state、readiness state，不可以自動接受候選或產生出發批准。

中文註釋：這不是 ObservedFact writer。模型輸出必須標示為 `ModelInterpretation` 或 debug explanation，不能被寫成 `ObservedFact`。

中文註釋：這不是 outbound action surface。任何回答都不能送真 SOS、真簡訊、真衛星，也不能把 mock outbound 轉成真 transport。

中文註釋：這是跨介面資料狀態助理。不同 surface 可以給 AI 不同 context，但每個 context adapter 必須是 read-only、bounded、auditable。

## Surface Constraint Matrix

| Surface | Context adapter may read | Assistant may answer | Assistant must not do |
| --- | --- | --- | --- |
| `/admin/debug` | debug events, selected timeline node, `/debug/state`, `/debug/messages`, Phase 3.5 boundary snapshot | runtime timeline explanation, L0-L4 transition explanation, provider degraded status, mock outbound status, Ln gate and skill run visibility | mutate safety runtime, call `/safety/*`, send outbound, change debug log |
| `/admin` after-action | rendered evidence tree, incident package refs, map/evidence selection, Phase 2 preview snapshots | what happened, which evidence supports it, what persisted package or adapter output exists | rewrite historical incident/evidence, write Brain nodes, alter after-action package |
| `/admin/pretrip` | project manifest, candidates, source registry, review queue, readiness/departure gate artifacts | planning state, candidate provenance, missing review items, readiness blockers | accept/reject candidates, create reviewed facts, compile runtime handoff, approve departure |
| hardware readiness | provider health fixture, sample replay timeline, runtime debug log, mock transport queue | provider status, sample replay interpretation, debug readiness checklist | control hardware, change provider state, open real transport, start Pi/Docker deployment |

## Architecture

The milestone should introduce four concepts.

### 1. Assistant Request Contract

The request is a read-only query, even if transported as HTTP `POST` because it
contains a structured body.

Proposed shape:

```python
class ScoutAssistantQuery(BaseModel):
    surface: Literal["debug", "admin", "pretrip", "hardware_readiness"]
    question: str
    context_ref: str | None = None
    selected_event_id: str | None = None
    selected_artifact_id: str | None = None
    project_id: str | None = None
```

### 2. Assistant Response Contract

Every response must be explicitly labeled as interpretation:

```python
class ScoutAssistantResponse(BaseModel):
    answer: str
    surface: str
    model_interpretation: bool = True
    read_only: bool = True
    sources: list[AssistantSourceRef]
    boundary: AssistantBoundary
    limitations: list[str]
```

The response should never include a field that looks like a runtime command,
review decision, writeback instruction, outbound send request, or hardware
control request.

### 3. Surface Context Adapters

Each adapter owns one read-only projection:

- `debug_assistant_context.py`: debug timeline, selected event, debug state,
  messages, boundary snapshot.
- `admin_assistant_context.py`: after-action selected evidence, incident refs,
  Phase 2 preview snapshots.
- `pretrip_assistant_context.py`: project manifest, candidates, source registry,
  review queue, readiness and departure gate summaries.
- `hardware_readiness_assistant_context.py`: provider health, sample replay,
  runtime debug log, mock outbound queue.

Adapters should return compact context envelopes. They should not pass large raw
stores, raw GPX, raw SensorLog, raw website payloads, or secrets to the model.

### 4. Provider Layer

Provider support should be staged:

1. `mock`: deterministic, no model call, used for tests and UI contract.
2. `pydantic_ai`: opt-in provider behind environment flags.

Proposed flags:

```text
SCOUT_AI_ASSISTANT_ENABLED=1
SCOUT_AI_ASSISTANT_PROVIDER=mock|pydantic_ai
SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS=8
SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS=12000
```

The Pydantic AI provider should be separate from `/navigate`. It may reuse
shared model configuration, but it should have its own system prompt and tools
because `/navigate` is navigation advice while this assistant is read-only
state explanation.

## API Boundary

Proposed endpoint:

```text
POST /assistant/query
```

This endpoint is read-only. It is allowed to use `POST` only to carry a query
body. It must not write application state.

Default behavior:

- endpoint not mounted unless `SCOUT_AI_ASSISTANT_ENABLED=1`;
- provider defaults to `mock`;
- unsupported surface returns a structured error;
- provider failure returns a safe error response and does not affect source
  surface behavior.

Forbidden:

- `PUT`, `PATCH`, `DELETE` for assistant APIs;
- request fields such as `action`, `approve`, `send`, `write_fact`, `mutate`,
  `control_provider`;
- automatic store writes from assistant response.

## UI Boundary

The shared UI should be an assistant drawer/panel that can be embedded in
multiple surfaces.

Required behavior:

- visible surface label, for example `debug assistant` or `pretrip assistant`;
- visible boundary label: `read-only model interpretation`;
- source list or citation chips for the context used;
- no action buttons in the first milestone;
- response can be copied or inspected, but not applied.

Initial UI order:

1. Debug surface, because Phase 3.5 already has selected timeline context.
2. Pre-trip planning surface, because candidate/review/source state benefits
   from explanation.
3. After-action admin surface.

## Prompt Boundary

The system prompt must include:

- Scout is a wilderness safety system.
- Phase 1 deterministic safety decisions are authoritative.
- The assistant explains state and evidence only.
- The assistant must not invent facts or claim actions happened.
- The assistant must cite source refs from the provided context.
- The assistant must label uncertain answers and missing context.
- The assistant must refuse requests to mutate runtime, Brain, review state,
  outbound transport, or hardware.

Surface prompts may add narrower constraints, but must not loosen the global
boundary.

## Milestone Slices

### Slice 1: Spec And Contract

Files:

- `docs/specs/scout-cross-surface-ai-assistant.md`
- assistant Pydantic request/response models;
- contract tests.

Acceptance:

- surfaces and constraints are represented in typed models;
- response always includes `model_interpretation=true` and `read_only=true`;
- unsupported surfaces fail safely.

### Slice 2: Mock Assistant Provider

Files:

- `assistant_provider.py`
- `tests/test_assistant_provider.py`

Acceptance:

- deterministic mock answers for debug/admin/pretrip/hardware readiness;
- no network calls;
- no store writes;
- source refs are echoed in the response.

### Slice 3: Context Adapter Foundation

Files:

- `debug_assistant_context.py`
- `admin_assistant_context.py`
- `pretrip_assistant_context.py`
- `tests/test_*assistant_context.py`

Acceptance:

- each adapter returns bounded read-only context;
- adapters do not import live safety mutation paths;
- pretrip adapter does not write review decisions or `ObservedFact`.

### Slice 4: Read-Only Assistant API

Files:

- `assistant_api.py`
- `server.py`
- `tests/test_assistant_api.py`

Acceptance:

- `/assistant/query` is mounted only when opt-in is enabled;
- default provider is mock;
- no mutation methods exist;
- provider failure is isolated.

### Slice 5: Shared Assistant UI Shell

Files:

- shared static UI script or per-page embedded shell, following current admin
  static HTML conventions;
- debug and pretrip integration tests.

Acceptance:

- drawer/panel can be embedded in `/admin/debug` and `/admin/pretrip`;
- it shows surface, boundary, answer, limitations, and sources;
- it has no action controls.

### Slice 6: Pydantic AI Opt-In Provider

Files:

- `assistant_pydantic_provider.py`
- prompt fixtures;
- provider tests with mocked model execution.

Acceptance:

- enabled only by `SCOUT_AI_ASSISTANT_ENABLED=1` and
  `SCOUT_AI_ASSISTANT_PROVIDER=pydantic_ai`;
- timeout and context budget are enforced;
- prompt injection attempts cannot loosen boundaries;
- response remains `ModelInterpretation`/debug explanation only.

### Slice 7: Acceptance Gate And Runbook

Files:

- optional `assistant_readiness_check.py`;
- docs/admin assistant runbook.

Acceptance:

- focused tests pass;
- no Phase 1 safety mutation;
- no `ObservedFact` writes from assistant output;
- no outbound sends;
- mock provider works without network;
- Pydantic AI provider remains disabled by default.

## Testing Strategy

Focused tests should cover:

- request/response validation;
- per-surface constraints;
- mock provider deterministic output;
- context adapter bounded projection;
- no forbidden imports in assistant foundation;
- API opt-in mount and method boundary;
- prompt injection resistance for provider layer;
- UI has no mutation controls.

Verification commands should follow this shape:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest \
  tests/test_assistant_models.py \
  tests/test_assistant_provider.py \
  tests/test_assistant_context.py \
  tests/test_assistant_api.py \
  tests/test_assistant_page.py
```

## Success Criteria

Milestone 10 is complete when:

- admin/debug/pretrip/hardware-readiness surfaces have distinct constraints;
- the assistant can answer data-state questions from bounded context;
- default implementation works with deterministic mock provider;
- Pydantic AI provider is opt-in and failure-isolated;
- no assistant response can mutate Phase 1, Phase 2 Brain, IncidentStore,
  pretrip review state, outbound transport, or hardware;
- model output is never written as `ObservedFact`;
- UI clearly labels assistant answers as read-only model interpretation.

## Open Questions

- Should the shared assistant UI live as one reusable static JS module, or be
  embedded per page until the frontend architecture is consolidated?
- Should the API route be `/assistant/query` globally, or namespaced under
  `/admin/assistant/query`?
- Should Pydantic AI use the existing `sos_agent` model config with a separate
  agent, or a fully separate provider configuration?
- Which surface should ship first after the mock provider: debug or pretrip?
