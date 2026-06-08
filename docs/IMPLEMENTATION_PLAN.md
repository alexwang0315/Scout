# Scout AI OS MVP Implementation Plan

## Scope

This plan follows `docs/specs/SCOUT_AI_OS_MVP_SPEC.md`.

The current completed scope is Phase 0 through Phase 9:

- inspect the repository;
- create root `AGENTS.md`;
- create package scaffold;
- create placeholder modules;
- create planning docs;
- add importability tests;
- implement Pydantic schema contracts;
- add focused schema validation tests;
- initialize SQLite with required tables;
- implement deterministic workflow, capability, learning, and memory stores;
- implement permission gate, local notification gateway, runtime executor, and
  scheduler tick;
- implement typed provider-backed agent facades with deterministic no-LLM
  provider;
- implement generated capability sandbox verification;
- implement FastAPI routes;
- implement learning artifact approval flow;
- update documentation and hardening tests.

The MVP still does not provide production-grade sandbox isolation, external
notification providers, payment automation, unrestricted browser automation,
autonomous generated-code installation, or Scout safety-runtime mutation.

## Existing Repo Context

Scout already has a read-only evidence assistant foundation:

- assistant query/status API;
- context registry;
- tool registry;
- deterministic evidence tools;
- workflow discovery;
- evidence collection;
- answer synthesis;
- assistant evals.

This foundation remains useful, but the AI OS MVP target is broader:
permissioned workflow automation through deterministic services.

## Phase 0: Repository Inspection And Planning

Status: scaffolded.

Deliverables:

- root `AGENTS.md`;
- this implementation plan;
- architecture, security, and API placeholder docs;
- no business logic.

## Phase 1: Scaffold

Status: scaffolded.

Deliverables:

- `pyproject.toml`;
- `src/scout/` package;
- schemas, agents, services, runtime, API, and capabilities packages;
- placeholder built-in capability folders;
- minimal importability test.

## Phase 2: Schemas

Status: implemented.

Implement Pydantic domain models and focused tests:

- `WorkflowSpec`;
- `TriggerSpec`;
- `ConditionSpec`;
- `ActionSpec`;
- `PermissionSpec`;
- `CapabilitySpec`;
- `ExecutionPlan`;
- `CapabilityBuildRequest`;
- `GeneratedCapabilityPackage`;
- `SandboxResult`;
- `LearningArtifact`;
- `LearningBundle`.

Phase 2 must not implement persistence or runtime execution.

## Phase 3: Database And Stores

Status: implemented.

Implement SQLite setup and deterministic stores:

- database connection/init helper;
- `WorkflowStore`;
- `CapabilityRegistry`;
- `MemoryStore`;
- focused persistence tests using temporary SQLite files.

Phase 3 must not implement workflow execution, permission decisions, sandbox
execution, notification sending, or learning approval mutation.

## Phase 4: Permission And Runtime Basics

Status: implemented.

- `PermissionGate`;
- `NotificationGateway`;
- `RuntimeExecutor`;
- scheduler tick;
- focused tests for low-risk allow, approval-required cases, high-risk deny,
  logged notification output, and runtime tick behavior.

## Phase 5: Typed Agent Facades

Status: implemented.

Deliverables:

- `ScoutDeps`;
- provider-backed `WorkflowCompilerAgent`;
- provider-backed `ExecutionPlannerAgent`;
- provider-backed `CodeBuilderAgent`;
- provider-backed `LearningAgent`;
- deterministic no-LLM provider for tests and local MVP behavior.

## Phase 6: Sandbox

Status: implemented.

Deliverables:

- generated capability package static checks;
- safe relative-path validation;
- temporary-directory pytest execution with timeout;
- practical network blocker for sandbox tests;
- `SandboxResult` outputs.

## Phase 7: API

Status: implemented.

Deliverables:

- `POST /requests`;
- `GET /workflows`;
- `GET /workflows/{id}`;
- `POST /workflows/{id}/approve`;
- `POST /workflows/{id}/cancel`;
- `GET /capabilities`;
- `GET /learning-artifacts`;
- `POST /learning-artifacts/{id}/approve`;
- `POST /runtime/tick`.

## Phase 8: Learning Loop

Status: implemented.

Deliverables:

- reviewable learning artifact persistence;
- explicit memory artifact approval into `MemoryStore`;
- eval-case JSONL append on approval;
- API approval endpoint.

## Phase 9: Documentation And Hardening

Status: implemented.

Deliverables:

- README status section;
- architecture/API/security docs updated to current MVP scope;
- focused docs gate;
- boundary grep for risky imports and mutation routes.

## Future Work

- production-grade sandbox isolation;
- richer external notification providers;
- real Pydantic AI provider wiring;
- generated capability approval/install workflow beyond metadata candidates;
- Pydantic Evals dataset expansion;
- background scheduler lifecycle management;
- mobile companion integration.
