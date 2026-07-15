# Scout AI OS MVP Architecture

## Target Architecture

Scout AI OS is a permissioned workflow automation layer.

```text
User Request
  -> FastAPI Request API
  -> ApplicationRouter
  -> WorkflowCompilerAgent
  -> ExecutionPlannerAgent
  -> PermissionGate
  -> WorkflowStore / CapabilityRegistry
  -> RuntimeExecutor / Scheduler
  -> NotificationGateway
  -> LearningAgent
  -> Memory / Skill / Template / Eval candidates
```

Generated low-risk capability path:

```text
ExecutionPlannerAgent
  -> CodeBuilderAgent
  -> SandboxRunner
  -> PermissionGate
  -> CapabilityRegistry.install(status="candidate")
  -> explicit /capabilities/{name}/approve
  -> CapabilityRegistry.approve_generated_candidate()
```

Ephemeral L5 Code Mode is a separate path from generated capability install:

```text
Under-construction override OR deterministic production L5 policy
  -> typed L5 activation decision
  -> reviewed Pydantic AI Harness CodeMode availability check
  -> no host mount in the first 100-case slice
  -> model-authored temporary Python in the Monty sandbox
  -> frozen allowlist containing only the confined workspace query tool
  -> bounded evidence result and audit trace
  -> discard sandbox state
```

`under_construction=true` makes L5 eligible so development and evaluation are
not blocked by the production L3+ gate. It does not make an unavailable sandbox
executable and never falls back to host Python or shell. Production L5 is
system-activated only; human or model request alone is insufficient. L5 raises
autonomous computation, not physical or data-mutation authority.

Session-local UI operation path:

```text
User Request
  -> ApplicationRouter
  -> scout.ui.action_plan capability
  -> PermissionGate.evaluate_ui_action_plan() or WorkflowSpec ActionType.UI_ACTION
  -> RuntimeExecutor planning-only action result
  -> scout_ui_action_plan.v0
  -> existing browser executor on admin/debug/pretrip
```

Reviewed non-safety outbound path:

```text
User-approved session/trip scope
  -> immutable OutboundStandingGrant
  -> typed OutboundActionIntent
  -> PermissionGate
  -> StandingGrantNotificationProvider
  -> configured deterministic transport
  -> summary-only audit record
```

The grant removes repeated confirmation only inside its reviewed provider,
recipient, message-class, topic, data-class, priority, expiry, and send-count
envelope. Safety-related outbound, SOS, Phase 1 L0-L4 mutation, and secret
material remain hard denied. Resident observers remain read-only and never own
this sender path.

## Phase 9 Implemented MVP Architecture

The current MVP establishes package boundaries, typed contracts,
SQLite-backed deterministic stores, runtime basics, typed agent facades,
sandbox verification, API routes, and reviewable learning artifacts:

- `scout.schemas`: Pydantic contract modules for workflows, capabilities,
  execution plans, permission results, sandbox results, and learning artifacts.
- `scout.agents`: provider-backed typed facades plus a deterministic no-LLM
  provider for local MVP behavior and tests.
- `scout.agents.model_policy`: explicit Pydantic AI model selection policy for
  local FunctionModel default, environment-selected external models, and
  redacted credential requirement reporting.
- `scout.services`: deterministic stores, gates, registry, sandbox, and
  notification services.
- `scout.runtime`: scheduler, executor, trigger, and action runtime code.
- `scout.api`: FastAPI routes.
- `scout.capabilities`: built-in and future generated capabilities.
- `scout.evals`: fixture-backed `pydantic_evals.Dataset` regression cases and
  deterministic runner.
- `scout.hardware`: hardware-safe Scout AI OS smoke profile and JSON readiness
  report runner.

Implemented services:

- `scout.services.db`: SQLite connection, WAL setup, required table creation.
- `scout.services.workflow_store`: workflow spec persistence, status changes,
  workflow events, and due-workflow lookup.
- `scout.services.capability_registry`: capability metadata loading and simple
  keyword search, including generated candidate approval metadata.
- `scout.services.memory_store`: reviewed memory item persistence.
- `scout.services.learning_store`: reviewable learning artifact persistence and
  approval flow.
- `scout.services.permission_gate`: deterministic approval/deny decisions.
- `scout.services.outbound_standing_grant`: deterministic standing-grant
  evaluation for summarized, non-safety outbound intents.
- `scout.services.application_router`: deterministic request-class routing
  before workflow compilation.
- `scout.services.notification_gateway`: provider-based local, dry-run, and
  explicitly configured external transports, including a standing-grant
  wrapper that rechecks typed intents before transport invocation.
- `scout.services.sandbox_runner`: generated package static checks and tempdir
  pytest verification with file-count and byte-size guards.

The runtime exposes a manual `/runtime/tick` endpoint and an optional
background scheduler lifecycle. The background loop is disabled by default and
must be explicitly enabled through `create_app` or
`SCOUT_AI_OS_BACKGROUND_SCHEDULER=1`.

The hardware smoke profile is a readiness layer, not a runtime authority
upgrade. It can run on a Scout host and validate optional hardware/mobile
evidence JSON, but any true boundary flag for hardware control, outbound send,
Phase 1 L0-L4 safety mutation, runtime ingest, `/safety/*` mutation, or
provider-values-as-Scout-truth blocks that evidence check.

## Existing Assistant Relationship

The current read-only assistant remains an evidence and explanation layer. It
should feed context into the AI OS compiler/planner, but it is not the final
automation runtime.

The existing Scout AI UI Operation Bridge is now registered as a first-party
AI OS capability. The router can return its `scout_ui_action_plan.v0` artifact
locally, while the existing admin/debug/pretrip browser executor remains the
only component that applies session UI state.

Approved session-local UI operations can also be represented as
`WorkflowSpec.actions[].type = "ui_action"`. The runtime action executor only
returns the `scout_ui_action_plan.v0` artifact and application hint; it does
not mutate Scout safety truth, send outbound messages, drive hardware, or apply
browser state by itself.

## Bounded Assistant Thin Waist

Workspace-grounded Scout Assistant turns use the same AIOS rule as the typed
agents: the model chooses a bounded plan while deterministic services own
discovery, execution, limits, provenance, and verification.

```text
question
  -> compact intent and context discovery
  -> up-to-10 ranked ContextHandle shortlist
  -> deterministic ToolPlan (up to 10 tools for every question class)
  -> selected ToolCards and selected full schemas only
  -> deterministic workspace tool execution
  -> one bounded EvidenceCard per result
  -> no-tool synthesis
  -> citation and budget verification
  -> verified no-tool repair/replan when needed
  -> external-limit checkpoint and fresh-budget continuation
```

The portable contracts live in `scout.schemas.agent_runtime`; context/tool
discovery, evidence projection, budget accounting, and grounding verification
live in `scout.services.bounded_agent_runtime`. The large assistant provider is
an adapter over this thin waist, not a separate unbounded agent stack.

Normal workspace answering does not preload Total Info, complete workspace
artifacts, all tool schemas, or unselected provider-native capabilities. Raw
tool output remains server-side for audit; the synthesis request receives only
recursively sanitized evidence and source references. Private evidence
cards, credentialed URLs, secret-like values, and paths outside the workspace
are withheld before model egress. Actual provider call counts are checked after
every response. Reaching one attempt's 10-call ceiling closes that stage and
creates a continuation or recovery attempt; it does not prove the question is
unanswerable. General non-workspace provider calls
retain the trusted native research policy. A future workspace research path
must first expose WebSearch/WebFetch as discoverable compact ToolCards so those
capabilities are selected rather than globally attached.

Computer Use remains outside this loop until context retrieval, tool recall,
grounding, and growth gates pass. A returned UI action plan is not an execution
receipt and must not be reported as an applied browser action.

Every typed or unknown question class receives at least 10 tool calls and 10
model requests per attempt and per recovery stage. Planner, retriever,
synthesis, verifier, reviewer, repair, retry, replan, browser, and subagent
budgets are also at least 10 when independently metered. Aggressive Construction
Mode does not enforce Scout-defined input/output/total-token, evidence-card,
context-character, cost, answer-time, or replay-time ceilings; those counters
remain telemetry. An external provider/platform limit checkpoints evidence,
call trace, and state before a fresh continuation. Duplicate/no-progress stops
and security boundaries still apply. Failures follow the finite ladder in
`docs/specs/SCOUT_OUTDOOR_AI_AGENT_STANDARD.md`: repair tools or evidence,
switch model, obtain independent Codex review, then record a known issue and
continue to the next case.

## MVP Limitations

This MVP does not implement:

- OS-level or container-grade sandbox isolation;
- automatic creation, renewal, or expansion of outbound standing grants;
- default-on deployment of live external notification transports;
- generated capability runtime code installation outside sandbox metadata;
- payment automation;
- unscoped destructive shell/browser automation;
- autonomous Scout core self-modification;
- Scout Phase 1 L0-L4 safety mutation from model output.

Trusted server-room computer-use/browser-use is part of the Scout AI capability
direction: Scout AI is the user entrypoint, while the workstation-side executor
applies reviewed UI/browser actions and records provenance. This is distinct
from letting model text mutate Phase 1 safety truth directly.
