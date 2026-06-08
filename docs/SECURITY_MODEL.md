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

## Remaining Non-Implementation

- generated code is not installed as an executable production capability;
- external notification providers are not implemented;
- model output cannot mutate Scout L0-L4 safety truth;
- payments, deletion, credential access, and production writes remain denied by
  default.
