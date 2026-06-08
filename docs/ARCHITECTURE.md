# Scout AI OS MVP Architecture

## Target Architecture

Scout AI OS is a permissioned workflow automation layer.

```text
User Request
  -> FastAPI Request API
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
  -> CapabilityRegistry.install()
```

## Phase 9 Implemented MVP Architecture

The current MVP establishes package boundaries, typed contracts,
SQLite-backed deterministic stores, runtime basics, typed agent facades,
sandbox verification, API routes, and reviewable learning artifacts:

- `scout.schemas`: Pydantic contract modules for workflows, capabilities,
  execution plans, permission results, sandbox results, and learning artifacts.
- `scout.agents`: provider-backed typed facades plus a deterministic no-LLM
  provider for local MVP behavior and tests.
- `scout.services`: deterministic stores, gates, registry, sandbox, and
  notification services.
- `scout.runtime`: scheduler, executor, trigger, and action runtime code.
- `scout.api`: FastAPI routes.
- `scout.capabilities`: built-in and future generated capabilities.

Implemented services:

- `scout.services.db`: SQLite connection, WAL setup, required table creation.
- `scout.services.workflow_store`: workflow spec persistence, status changes,
  workflow events, and due-workflow lookup.
- `scout.services.capability_registry`: capability metadata loading and simple
  keyword search.
- `scout.services.memory_store`: reviewed memory item persistence.
- `scout.services.learning_store`: reviewable learning artifact persistence and
  approval flow.
- `scout.services.permission_gate`: deterministic approval/deny decisions.
- `scout.services.notification_gateway`: stdout/local event notification
  gateway.
- `scout.services.sandbox_runner`: generated package static checks and tempdir
  pytest verification.

## Existing Assistant Relationship

The current read-only assistant remains an evidence and explanation layer. It
should feed context into the AI OS compiler/planner, but it is not the final
automation runtime.

## MVP Limitations

This MVP does not implement:

- production-grade sandbox isolation;
- external notification providers;
- generated capability runtime installation outside metadata candidates;
- payment automation;
- unrestricted shell/browser automation;
- autonomous Scout core self-modification;
- Scout Phase 1 L0-L4 safety mutation from model output.
