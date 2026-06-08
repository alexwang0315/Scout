# Scout AI OS MVP API

## Phase 9 Status

The MVP routes from `docs/specs/SCOUT_AI_OS_MVP_SPEC.md` are implemented in
`scout.api.routes:create_app`. The default app uses a deterministic no-LLM
provider and SQLite-backed stores.

## Routes

```text
POST /requests
GET  /workflows
GET  /workflows/{id}
POST /workflows/{id}/approve
POST /workflows/{id}/cancel
GET  /capabilities
GET  /learning-artifacts
POST /learning-artifacts/{id}/approve
POST /runtime/tick
```

`POST /requests` compiles a typed workflow, plans execution, evaluates
permissions, saves pending workflows when approval is required, installs
low-risk workflows, and stores reviewable learning candidates.

## Existing Assistant API

The existing `/assistant/query` and `/assistant/status` API remains a read-only
evidence assistant surface. It is separate from the future Scout AI OS workflow
runtime API.

## MVP Limitations

- The API does not call a live LLM by default.
- The API does not install generated capability code outside the sandbox flow.
- External notification providers are not implemented.
- Runtime tick handles deterministic MVP trigger/action support only.
