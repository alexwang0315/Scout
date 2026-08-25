# Scout AI OS Phase 5-7 Completion Audit

**Date:** 2026-08-25
**Mode:** Aggressive Construction Mode
**Outcome:** WORKING MVP SLICE

## Scope

This audit covers the Scout AI OS MVP phase definitions in
`docs/IMPLEMENTATION_PLAN.md`:

- Phase 5: typed/Pydantic AI agent facades;
- Phase 6: generated capability sandbox qualification;
- Phase 7: local API, workflow runtime, approval, ownership, and persistence.

It does not promote the sandbox to production isolation, enable generated
runtime code, alter Scout Phase 1 L0-L4 safety truth, or resolve the independent
MAX Phase 4 hardware/runtime qualification branch.

## Phase 5 Evidence

- `ScoutAgentRequest` contains a bounded context and scoped `ScoutToolbox`, not
  the raw `ScoutDeps` control-plane container.
- WorkflowCompiler, ExecutionPlanner, CodeBuilder, and Learning facades receive
  separate least-privilege tool sets.
- Unsupported model provider names fail closed and provider error telemetry
  redacts credential-like values, including common header/environment forms.
- Enforced gateway timeouts drain the in-flight provider attempt before
  fallback, preventing a timed-out call from surviving its receipt or
  overlapping a retry. Provider-native cancellation is still required for a
  hard latency bound.
- Deterministic qualification covers safe generated parser requests, recurring
  time workflows, destructive-request refusal, sensitive-learning rejection,
  and typed output validation.
- A clean Python environment with `pydantic-ai-slim==2.33.0` passed 19 runtime
  compatibility and real Pydantic provider tests; the provider reported
  `status=completed` with `fallback_used=false`.

## Phase 6 Evidence

- Generated files are constrained to safe relative paths and bounded package
  size/count.
- Static and AST checks reject prohibited/dynamic imports, dunder escape paths,
  file mutation, and process APIs before execution.
- Tests run in a temporary directory with a reduced environment, timeout,
  process-group cleanup, output bounds, and an injected socket blocker.
- Execution requires macOS Seatbelt or Linux bubblewrap and fails closed when no
  supported OS isolation backend is available.
- The focused sandbox suite passed 13 tests, including parent-secret scrubbing,
  AST obfuscation rejection, network-blocker presence, and a Seatbelt proof that
  sandboxed Python cannot read a sibling host file.

These are qualification backends, not production container attestation.
Production generated-code dispatch remains disabled.

## Phase 7 Evidence

- Time workflows persist `next_run_at`; manual workflows remain immediately due.
- Workflow approval requires the owner, applies only to `pending`, and creates a
  deterministic approval event used by runtime execution.
- Workflow and learning-artifact reads/approvals reject a different user id.
- Generated capability candidates cannot replace existing names and retain
  owner, package hash, sandbox receipt, approver, and approval note.
- Candidate and metadata-only approved capabilities remain unavailable to the
  planner/runtime until deterministic runtime registration exists.
- Daily recurrence advances by calendar day; time workflows without an explicit
  timezone-aware `run_at` are rejected instead of becoming permanently inert.
- Migrated learning artifacts recover ownership from their source workflow when
  that binding exists, and ownership is checked before processed status.
  Ownerless legacy rows are quarantined, hidden from user-scoped listing, and
  rejected by approval as missing an authority binding.
- `POST /requests` can build a safe missing capability as a review-only
  candidate without creating a workflow or enabling generated runtime code.
- `scout.main:app` uses a stable state path independent of the current working
  directory and preserves state across app reconstruction.
- The focused API/runtime/store suite passed 57 tests.

## Executable Smoke

A real local Uvicorn process using the clean environment and a temporary SQLite
database completed both paths:

1. `POST /requests` installed a time workflow, `POST /runtime/tick` executed it,
   and the workflow ended `completed` with `notification.sent` and action/event
   receipts.
2. `POST /capabilities/build-candidate` sandboxed a low-risk parser, persisted a
   candidate with owner/hash/receipt, and owner approval promoted metadata while
   the response explicitly retained `runtime code remains sandbox-only`. The
   sandbox receipt reported `isolation_backend=macos-seatbelt`, and both the
   candidate and approved metadata reported `runtime_available=false`.
3. An ambiguous `Remind me later` request returned `refused` with an explicit
   `run_at` requirement and created no inert workflow.

## Final Verification

- `tests/test_scout_ai_os_*.py`: **161 passed**, with one non-failing upstream
  Pydantic Evals event-loop deprecation warning.
- Pydantic AI 2.33 runtime compatibility plus real provider path: **19 passed**.
- Phase 5-7 focused integration set: **111 passed** before the final additional
  fail-closed runtime case; that case also passed independently.
- Scoped Ruff over every touched Python implementation/test file: **PASS**.
- Scoped `git diff --check`: **PASS**.
- Independent replays of the four Phase 5 blocker probes: **all resolved**.
- Independent replays of the Phase 7 candidate, scheduling, ownership, and
  migration blocker probes: **all resolved**.

## Authority Check

- LLM/provider output remains typed proposal data.
- Permission, persistence, scheduling, action execution, and approvals remain
  deterministic server-owned code.
- Generated capability approval does not enable runtime dispatch.
- No Phase 5-7 path writes Scout outdoor safety truth or hardware state.

## Remaining Productization Debt

- Replace caller-supplied `user_id` with an authenticated server-derived
  principal before shared or network-exposed deployment.
- Promote Seatbelt/bubblewrap qualification into reviewed container isolation
  and runtime attestation before generated-code execution can be considered.
- Persist and operationalize model SLA telemetry; provider-level cancellation
  must complement the gateway deadline for hard interruption guarantees.
- Run Raspberry Pi field deployment and sustained resource qualification
  separately; this audit proves local software behavior, not Pi endurance.
