# Scout AI OS MVP Security Model

## Phase 9 Status

The MVP implements typed contracts, persistence, permission decisions, local
notification events, manual/time runtime tick, generated package verification,
API routes, and reviewable learning approvals.

## Core Rules

- Model output is never runtime safety truth.
- Model output cannot directly mutate L0-L4 state.
- Generated code is guilty until proven safe.
- Persistent, location, private-data, external, or generated-code workflows
  require approval.
- Destructive, payment, credential, production database write, and unrestricted
  shell automation is denied by default in the MVP.
- Agent facades receive explicit least-privilege read-only tool scopes; model
  requests do not receive the raw runtime dependency container.
- Model-provider errors are redacted before they enter SLA telemetry.

## Generated Code Policy

Generated code may only be installed after:

1. low-risk classification;
2. explicit `CapabilitySpec`;
3. tests are included;
4. static disallowed-pattern checks pass;
5. sandbox tests pass;
6. permission gate approval;
7. user approval during early MVP.

In the current MVP, approval promotes generated capability metadata only. The
candidate is bound to an owner, package hash, sandbox receipt, approving user,
and approval note. It cannot overwrite an existing built-in or candidate name,
and its generated Python remains unavailable to the active runtime dispatcher.
Candidate and metadata-only approved records report `runtime_available=false`
and are excluded from planner/action lookup.

## Sandbox Limitations

The MVP sandbox is a layered qualification boundary, not a production-grade
generated-code runtime. It:

- rejects disallowed source patterns before execution;
- parses Python AST and allowlists imports/calls while rejecting dynamic import,
  dunder escape paths, and file/process mutation APIs;
- validates safe relative paths;
- writes generated package files to a temporary directory;
- runs pytest with timeout, process-group termination, and a reduced environment;
- requires macOS Seatbelt or Linux bubblewrap and fails closed without an OS
  isolation backend;
- adds a practical socket blocker through `sitecustomize.py`.

Seatbelt and bubblewrap are qualification backends, not portable container
attestation. Production generated-code dispatch still requires a reviewed,
versioned isolation profile, host-level resource controls, and deployment
qualification. Metadata approval never enables dispatch.

## API Identity Limitation

Workflow, learning-artifact, and generated-capability operations enforce
ownership against the supplied `user_id`. This prevents accidental cross-user
access in the local MVP, but it is not authentication. Any remote or shared
deployment must derive identity from a trusted authentication boundary and must
not trust a client-provided user identifier.

Legacy learning rows recover ownership from `source_workflow_id` when possible.
Rows without a recoverable owner are quarantined, hidden from user-scoped
listing, and cannot be approved through the user API.

## Hardware Smoke Policy

The Scout AI OS hardware smoke profile is a readiness and audit layer. It may
run API, local Pydantic AI, session-local UI operation, generated capability
metadata, sandbox rejection, notification dry-run checks, operator-confirmed
low-risk notification path checks, model SLA wrapper checks, and generated
runtime install lifecycle checks on a Scout host. It may also validate or
produce supplied hardware/mobile evidence JSON.

It must not control hardware, mutate Phase 1 L0-L4 safety truth, call live
`/safety/*` mutation routes, perform runtime ingest, promote provider values
as Scout truth, or dispatch generated runtime code from the action executor.
Evidence that reports any of those effects as `true` is blocked by the profile.

External notification support is fail-closed: dry-run remains the default, and
the live-send path requires operator confirmation, recipient allowlisting,
low-risk priority, audit/rate-limit tracking, and a transport provider. The
hardware smoke uses a memory transport and fake-network Telegram adapter proof,
then marks real network delivery proof as not verified.

Generated runtime install support is a lifecycle gate, not broad execution
authority. It requires sandbox pass, deterministic artifact hash, low-risk
package classification, safe isolation profile, operator approval, revoke, and
rollback. A generated runtime may be executed only through the isolated
proof-only dispatcher, which verifies the install hash and safe isolation
profile, then keeps `active_runtime_dispatch_enabled=false`, `safety_api_called=false`,
and `outbound_sent=false`. Install records keep `runtime_code_executed=false`
until a later executor isolation gate promotes active dispatch.

## Remaining Non-Implementation

- generated code is not dispatched as an executable production capability;
- live external notification network proof is not verified by default;
- model output cannot mutate Scout L0-L4 safety truth;
- payments, deletion, credential access, and production writes remain denied by
  default.
