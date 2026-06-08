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

## Generated Code Policy

Generated code may only be installed after:

1. low-risk classification;
2. explicit `CapabilitySpec`;
3. tests are included;
4. static disallowed-pattern checks pass;
5. sandbox tests pass;
6. permission gate approval;
7. user approval during early MVP.

## Sandbox Limitations

The MVP sandbox is a practical test isolation layer, not a complete security
boundary. It:

- rejects disallowed source patterns before execution;
- validates safe relative paths;
- writes generated package files to a temporary directory;
- runs pytest with timeout and a reduced environment;
- adds a practical socket blocker through `sitecustomize.py`.

It does not provide OS-level isolation, container isolation, syscall filtering,
or a complete network/file-system security boundary.

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
low-risk priority, and a transport provider. The hardware smoke uses a memory
transport and marks real network delivery proof as not verified.

Generated runtime install support is a lifecycle gate, not broad execution
authority. It requires sandbox pass, deterministic artifact hash, low-risk
package classification, safe isolation profile, operator approval, revoke, and
rollback. Install records keep `runtime_code_executed=false` and
`active_runtime_dispatch_enabled=false` until a later executor isolation gate.

## Remaining Non-Implementation

- generated code is not dispatched as an executable production capability;
- live external notification network proof is not verified by default;
- model output cannot mutate Scout L0-L4 safety truth;
- payments, deletion, credential access, and production writes remain denied by
  default.
