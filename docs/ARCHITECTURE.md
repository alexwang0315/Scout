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
  -> top-3 ContextHandle shortlist
  -> deterministic ToolPlan (3 tools, or 5 for a compound bundle)
  -> selected ToolCards and selected full schemas only
  -> deterministic workspace tool execution
  -> one bounded EvidenceCard per result
  -> no-tool synthesis
  -> citation and budget verification
  -> at most one bounded repair, otherwise fail closed
```

The portable contracts live in `scout.schemas.agent_runtime`; context/tool
discovery, evidence projection, budget accounting, and grounding verification
live in `scout.services.bounded_agent_runtime`. The large assistant provider is
an adapter over this thin waist, not a separate unbounded agent stack.

Normal workspace answering does not preload Total Info, complete workspace
artifacts, all tool schemas, or unselected provider-native capabilities. Raw
tool output remains server-side for audit; the synthesis request receives only
recursively sanitized bounded evidence and source references. Private evidence
cards, credentialed URLs, secret-like values, and paths outside the workspace
are withheld before model egress. Actual provider usage is checked after every
response; an over-budget response is discarded even when the provider returns
text. General non-workspace provider calls
retain the trusted native research policy. A future workspace research path
must first expose WebSearch/WebFetch as discoverable compact ToolCards so those
capabilities are selected rather than globally attached.

Computer Use remains outside this loop until context retrieval, tool recall,
grounding, and growth gates pass. A returned UI action plan is not an execution
receipt and must not be reported as an applied browser action.

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
