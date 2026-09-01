# Scout AI Dashboard Intelligence Telemetry

## Experiment Packet

- Experiment ID: `SCOUT-AI-EXP-DASH-TELEMETRY-001`
- Date: `2026-09-01`
- Mode: `WORKING PROTOTYPE`
- Decision: `ACCEPT_EXPERIMENTAL`
- Authority: `candidate_only=true`, `runtime_safety_truth=false`
- Promotion result: server-owned `not_promoted`

## Hypothesis

The existing persistent Praison background queue can be observed from the Scout
Dashboard without giving the Dashboard a queue write handle or allowing an
intelligence result to acquire runtime authority. A typed read-only projection
must expose enough binding, capability, provenance, tool, model, latency,
budget, evidence, validation, and lifecycle data to diagnose a job while
failing closed on malformed or cross-bound records.

## Implemented Slice

```text
SQLite background intelligence store
  -> SQLite URI mode=ro + PRAGMA query_only
  -> Pydantic request/progress/response validation
  -> request/mission/workspace/route/grant cross-binding checks
  -> bounded IntelligenceTelemetrySnapshot
  -> GET /admin/intelligence/telemetry
  -> standalone read-only telemetry page
  -> Dashboard System / Intelligence embedded surface
```

The reader does not instantiate `SQLiteBackgroundIntelligenceJobStore`, create a
schema, or expose raw questions. It emits a SHA-256 question identity and
bounded source references instead. Missing stores return `unavailable`; an
unreadable, malformed, authority-escalating, or cross-bound store returns a
typed `degraded` snapshot with zero projected jobs.

SQLite WAL readers may create or update SQLite coordination sidecars when the
writer is not active. Qualification therefore verifies that the main database,
schema, jobs, and events are byte/count equivalent before and after reads. An
`immutable=1` shortcut was rejected because it ignored uncheckpointed WAL state
and could display stale telemetry. A live-writer test proves that a committed
WAL job is visible while the writer remains open.

## Exposed Telemetry

- job and request IDs;
- mission, Workspace, route, version, and input-hash binding;
- task type and hashed question identity;
- allowed and denied capabilities, grant provenance, expiration, and budgets;
- queue state, stage, progress, cancellation, error, and timestamps;
- agent path and tools called;
- runtime, provider, model, locality, request count, latency, tokens, status,
  and fallback records;
- request evidence refs, response source refs, artifact refs, and output hash;
- finding, evidence, uncertainty, and conflict counts;
- validation result and server-classified reason codes; raw external validation
  text is not exposed;
- append-only lifecycle events;
- immutable `candidate_only=true`, `runtime_safety_truth=false`, read-only, and
  `promotion_result=not_promoted` fields.

The API registers no POST, submit, retry, cancel, promotion, permission, safety,
notification, emergency, route-write, device, or hardware endpoint.

## Verification

- Telemetry contract/API tests: `7 passed`.
- Dashboard, runtime-audit, and qualification regression set before the final
  stale/WAL additions: `225 passed`.
- Canonical Dashboard route census: 24 routes including
  `surface-intelligence`.
- Direct desktop browser: one persisted job, full binding/model/evidence detail,
  zero horizontal overflow, raw question absent, candidate boundary present.
- Direct large-mobile browser at 390 x 844: zero document/body overflow and all
  controls at least 42 px high.
- Embedded Dashboard desktop/mobile: active System navigation route, same-origin
  iframe, one projected job, model detail visible, zero parent/frame overflow.
- Browser-operated Refresh: returned to `typed_read_only_projection` with the
  same bound job.
- Direct telemetry page console after favicon guard: no warnings or errors.
- The temporary Dashboard fixture reported one unrelated
  `connected-preparation` 404 because no Pretrip workspace was mounted; this is
  not treated as official Dashboard qualification evidence.

## Qualification Boundary

This is a construction-mode telemetry prototype, not production Dashboard
activation or a completed live-runtime qualification. The current background
queue remains experimental and process-local. Retention policy, cross-process
submit/status/cancel MCP tools, authenticated access, official real-workspace
browser qualification, and production deployment configuration remain separate
promotion work.

The existing Dashboard process on port 9099 was not restarted or modified. A
separate port 9101 fixture process was used for the browser smoke.

## Rollback

Remove the telemetry reader/router/page, the `surface-intelligence` route and
manifest entries, and the focused tests. No mission, Workspace, route,
permission, safety, emergency, notification, device, hardware, reducer, or
runtime store migration requires rollback.
