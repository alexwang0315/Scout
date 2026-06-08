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
- implement provider-based stdout/memory local notification gateway;
- implement optional background scheduler lifecycle;
- implement typed provider-backed agent facades with deterministic no-LLM
  provider;
- implement explicit Pydantic AI model selection policy with redacted
  credential reporting;
- implement generated capability sandbox verification;
- implement fixture-backed Pydantic Evals regression dataset;
- implement FastAPI routes;
- implement learning artifact approval flow;
- register the session-local UI operation bridge capability and deterministic
  application router contract;
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
- model selection policy for local FunctionModel default, `SCOUT_AI_OS_MODEL`,
  explicit external model selection, and redacted rollout timeout/budget/
  fallback reporting;
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
- generated package file-count and byte-size guards;
- `SandboxResult` outputs.

## Phase 7: API

Status: implemented.

Deliverables:

- `POST /requests`;
- `POST /request-router/preview`;
- `GET /workflows`;
- `GET /workflows/{id}`;
- `POST /workflows/{id}/approve`;
- `POST /workflows/{id}/cancel`;
- `GET /capabilities`;
- `POST /capabilities/build-candidate`;
- `POST /capabilities/{name}/approve`;
- `GET /learning-artifacts`;
- `POST /learning-artifacts/{id}/approve`;
- `POST /runtime/tick`;
- `GET /runtime/scheduler`.

`POST /requests` now short-circuits obvious session-local UI operations to
`scout.ui.action_plan` and boundary-forbidden safety/outbound/hardware prompts
to a refusal response before workflow compilation. Non-UI workflow automation
continues through the original compiler/planner/permission flow.

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
- deterministic `pydantic_evals.Dataset` runner for workflow, router, boundary,
  and generated capability candidate regression cases.

## UI Operation Bridge Integration Slice

Status: implemented locally for capability registry, router contract, and
workflow/runtime UI action contract.

Deliverables:

- built-in `scout.ui.action_plan` capability metadata with session-local UI,
  read-only evidence query, and confirmation-gated workspace intent
  permissions;
- `ApplicationRouter` deterministic routing for UI operation, route readiness,
  workflow automation, read-only evidence query, and boundary explainer
  request classes;
- `PermissionGate.evaluate_ui_action_plan()` for session-local allow,
  workspace confirmation, and forbidden-boundary refusal decisions;
- API preview route plus `/requests` UI short-circuit behavior;
- `ActionType.UI_ACTION` workflow contract plus planning-only runtime action
  result for `scout_ui_action_plan.v0` artifacts;
- execution planner capability mapping for `scout.ui.action_plan`;
- focused tests proving the 20-prompt UI corpus remains on
  `scout_ui_action_plan.v0`;
- local Chromium browser smoke runner for the 20-prompt corpus.

This slice does not modify the hardware deployment path.

## Hardware AI OS Smoke Slice

Status: implemented as a hardware-safe readiness profile.

Deliverables:

- `scout.hardware.ai_os_smoke` profile/report runner covering H0-H8 hardware
  landing phases;
- `scout-ai-os-hardware-smoke` CLI with local `FunctionModel` default and
  explicit `--allow-external-model` opt-in;
- API, Pydantic AI, session-local UI action, generated capability metadata,
  notification dry-run, operator-confirmed notification, sandbox rejection,
  optional evidence JSON, generated runtime install lifecycle, and external
  model SLA gateway checks;
- `DryRunNotificationProvider` for external transport intent with `sent=false`;
- `OperatorConfirmedNotificationProvider` for low-risk live-send paths guarded
  by phrase confirmation, recipient allowlisting, priority gating, audit log,
  and rate limiting;
- `TelegramNotificationTransport` for operator-confirmed Telegram Bot API
  adapter proof without default live-network send;
- `scout.hardware.evidence` plus `scout-ai-os-hardware-evidence` for producing
  advisory-only mobile/hardware evidence JSON from sample JSON, Sensor Logger
  JSON/CSV, NMEA GNSS text, and host-probe JSON;
- `ModelSlaGateway` for timeout, budget ledger, retry telemetry, provider
  health/circuit breaker, and fallback enforcement around Pydantic AI provider
  calls;
- `GeneratedRuntimeInstaller` for artifact hash, isolation profile, approval,
  install, revoke, and rollback lifecycle records while active dispatch remains
  disabled;
- `GeneratedRuntimeDispatcher` for isolated proof-only `run(payload)` execution
  that preserves `active_runtime_dispatch_enabled=false`;
- hardware smoke documentation in `docs/SCOUT_AI_OS_HARDWARE_SMOKE.md`;
- focused tests proving safe defaults, external-model missing-key blocking,
  advisory evidence acceptance, forbidden evidence blocking, operator-gated
  notification send paths, Telegram adapter proof, external-model SLA fallback
  plus circuit breaker, generated runtime install lifecycle controls, and
  proof-only generated runtime dispatch.

This slice enables Scout hardware verification and gated lifecycle readiness.
It still does not grant active generated-code dispatch, real external network
notification proof, hardware control, or Scout Phase 1 L0-L4 safety mutation
authority.

## Future Work

- production OS/container attestation for generated runtime dispatch;
- explicit live-network Telegram/notification proof run with real operator
  destination config;
- persisted model SLA telemetry dashboards/alerting;
- mobile companion integration beyond local export/advisory evidence producers.
