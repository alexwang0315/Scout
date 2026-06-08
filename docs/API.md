# Scout AI OS MVP API

## Phase 9 Status

The MVP routes from `docs/specs/SCOUT_AI_OS_MVP_SPEC.md` are implemented in
`scout.api.routes:create_app`. The default app uses a deterministic no-LLM
provider and SQLite-backed stores.

## Routes

```text
POST /requests
POST /request-router/preview
GET  /workflows
GET  /workflows/{id}
POST /workflows/{id}/approve
POST /workflows/{id}/cancel
GET  /capabilities
POST /capabilities/build-candidate
POST /capabilities/{name}/approve
GET  /learning-artifacts
POST /learning-artifacts/{id}/approve
POST /runtime/tick
GET  /runtime/scheduler
```

`POST /requests` compiles a typed workflow, plans execution, evaluates
permissions, saves pending workflows when approval is required, installs
low-risk workflows, and stores reviewable learning candidates.

Before workflow compilation, `POST /requests` applies the deterministic
application router. Obvious session-local UI commands return
`ui_action_planned` with a `scout_ui_action_plan.v0` payload instead of creating
a workflow. Confirmation-gated workspace UI intents return
`ui_action_needs_confirmation`. Safety, outbound, runtime-mutation, or hardware
commands return `refused`.

`POST /request-router/preview` returns the same routing decision without
installing workflows or applying UI actions. It is intended for local testing
before browser or hardware smoke runs.

Workflow specs can also carry approved session-local UI operations as
`actions[].type = "ui_action"`. Runtime tick records a planning-only
`scout_ui_action_plan.v0` action result; the API still does not apply browser
state directly.

`GET /runtime/scheduler` reports optional background scheduler lifecycle state.
The background loop is disabled by default and can be enabled by
`create_app(..., enable_background_scheduler=True)` or
`SCOUT_AI_OS_BACKGROUND_SCHEDULER=1`.

`POST /capabilities/build-candidate` builds a low-risk generated capability
candidate, runs sandbox verification, evaluates install permission, and stores
passing generated packages as `candidate` metadata. `POST
/capabilities/{name}/approve` approves that generated metadata into the
registry. Generated packages are rejected before execution when they exceed
the MVP file-count or byte-size limits. Generated code is not installed into
the runtime execution path.

The Mac-side Pydantic AI smoke path uses a typed model policy: explicit
`--model` first, then `SCOUT_AI_OS_MODEL`, then local `FunctionModel`. Missing
credentials for external providers return `model_config_blocked` with only
environment variable names, not secret values. The same redacted policy reports
configured timeout, max-cost, and fallback model settings.

The `scout-ai-os-evals` CLI loads `src/scout/evals/workflow_router_cases.json`
as a `pydantic_evals.Dataset` and runs deterministic API regression cases for
workflow installation, approval-required workflows, UI routing, boundary
refusal, and generated capability candidate approval.

The `scout-ai-os-hardware-smoke` CLI produces a hardware-safe JSON readiness
report. By default it forces the local `FunctionModel`, checks API/UI/
capability/sandbox/notification dry-run boundaries, and marks generated runtime
install, live external notification transports, live external model SLA
enforcement, and direct Phase 1 L0-L4 safety mutation as blocked gates.

## Existing Assistant API

The existing `/assistant/query` and `/assistant/status` API remains a read-only
evidence assistant surface. It is separate from the future Scout AI OS workflow
runtime API.

## MVP Limitations

- The API does not call a live LLM by default.
- The API does not install generated capability code outside the sandbox flow;
  generated approval is registry metadata only, and the sandbox is not an
  OS-level/container isolation boundary.
- Live external notification transports are not implemented; the MVP ships
  stdout, memory, and dry-run-only notification providers.
- Runtime tick handles deterministic MVP trigger/action support only.
- UI action plans are session-local intents; the API does not apply browser
  actions by itself.
