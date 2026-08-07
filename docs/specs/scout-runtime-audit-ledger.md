# Scout Runtime Audit Ledger v0.1

## 1. Purpose

Runtime Audit Ledger is Scout Dashboard's unified, local runtime activity log.
It answers four operator questions:

1. Did this Scout runtime start and end normally?
2. Which internal APIs, external providers, agents, and background jobs ran, and
   did they succeed or fail?
3. Which workspace artifact classes were read or written, and approximately how
   many records and bytes were involved?
4. Is the audit record itself complete enough to trust, or is its coverage,
   writer health, or integrity degraded?

The ledger is **telemetry only**. It is not runtime safety truth, a safety
decision source, an authorization system, or a replacement for domain evidence
artifacts.

## 2. Scope and current status

The v0.1 implementation is mounted on the Scout Dashboard FastAPI runtime and is
displayed under **System -> Runtime Activity**.

Current instrumentation coverage:

| Surface | Status | Current coverage |
|---|---|---|
| Dashboard runtime start/end | covered | FastAPI startup, lazy request start, clean shutdown, and next-start crash detection |
| Dashboard internal HTTP | covered | Ordinary requests individually; high-volume successful tile requests aggregated; failures individually |
| External provider calls | partial | Dashboard Assistant, Connected Preparation providers exposed by its publication, and Open-Meteo |
| Workspace I/O | partial | Workspace Operations plus selected preparation/publication writes; direct file access elsewhere can still bypass the ledger |
| Agent runs | partial | Dashboard Assistant entrypoint |
| Background jobs | partial | Connected Preparation |

The Dashboard must display these coverage states. An empty event list must never
be presented as proof that nothing ran.

Reserved UI session event types exist in the schema, but browser session
start/heartbeat/expiry emission is not enabled in v0.1. Runtime lifecycle means
the Dashboard server process lifecycle in this version.

## 3. Storage layout

Default root:

```text
~/.scout-fusion/audit/runtime/
```

Override for tests or deployment:

```text
SCOUT_RUNTIME_AUDIT_ROOT=/private/audit/location
```

The audit root must be outside the monitored Scout workspace. A typical layout
is:

```text
runtime/
  .artifact-digest.key
  runtime-20260807T030000Z-a1b2c3d4e5f6/
    events-0001.jsonl
    events-0002.jsonl
    manifest.json
    summary.json
```

- Event segments are append-only JSON Lines files.
- A runtime instance has exactly one writer and may not be reused.
- Event files and metadata use mode `0600`; directories use `0700`.
- `.writer.lock` exists only while that instance is actively writing.
- Event segment rotation is count-based. v0.1 does not automatically delete
  historical instances; retention is manual and is shown as such in the UI.
- `summary.json` is a derived cache. The verified event prefix is authoritative.

For multi-worker deployment on one host, each process must receive a unique
`runtime_instance_id`. Two processes must never append to the same segment. A
new runtime checks the sibling writer lock and does not mark a live sibling as
interrupted. Cross-host shared-filesystem writer leases are not implemented in
v0.1.

## 4. Event envelope

Schema version: `scout_runtime_audit_event.v1`

### 4.1 Operator-facing fields

| Operator concept | Field | Meaning |
|---|---|---|
| ID | `event_id` | Unique event ID |
| Runtime ID | `runtime_instance_id` | One Dashboard server process instance |
| Sequence | `sequence` | Total order inside one runtime instance |
| Event time | `occurred_at` | When the activity occurred, if known |
| Record time | `recorded_at` | When the ledger durably recorded it |
| Success/failure | `outcome` | `started`, `succeeded`, `failed`, `rejected`, `cancelled`, `timed_out`, `degraded`, or `unknown` |
| Importance | `severity` | `debug`, `info`, `warning`, or `error` |
| Main category | `category` | Runtime, Dashboard/API, provider, workspace, agent, job, or audit |
| Subcategory | `subcategory` | A safe fixed-format subcategory such as `artifact-write` |
| Extra explanation | `detail_code` | Stable explanation code; the Dashboard maps it to human prose |
| Related module | `module` | Registered implementation module code |
| Related feature | `feature` | Registered product capability code |
| Related operation | `operation` | Registered action code |
| Workspace | `workspace_id` | Safe project/workspace identifier, never a path |
| Counts | `record_count`, `byte_count` | Approximate records and bytes touched |
| Duration | `duration_ms` | Elapsed time for the activity |

`summary` is generated from the fixed event type registry. Caller-provided
free-text `summary` and `detail` values are discarded before persistence. This
prevents a convenient description field from becoming a privacy bypass.

### 4.2 Correlation fields

Correlation is an optional origin graph, not a mandatory linear chain:

| Field | Use |
|---|---|
| `request_id` | Internal HTTP request |
| `operation_id` | Background or user operation |
| `agent_run_id` | One agent execution |
| `provider_call_id` | One external provider call |
| `workspace_io_id` | One workspace I/O record |
| `parent_event_id` | Optional direct parent event |
| `ui_session_id` | Reserved browser session correlation |

An event can be useful without all correlation IDs. Missing correlation must not
cause an otherwise valid audit event to be dropped.

### 4.3 HTTP and provider fields

| Field | Meaning |
|---|---|
| `http_method` | Safe HTTP verb |
| `route_template` | FastAPI route template with query string removed |
| `status_code` | HTTP/provider status when available |
| `provider` | Registered provider code or class; unknown values collapse to `other-provider` |
| `model` | Normalized safe model/profile identifier, never a prompt or response |
| `error_code` | Stable exception or failure code, never a stack trace |
| `attempt`, `retry_count` | Attempt and retry counters when exposed |
| `request_count` | Number of calls represented by this event |

### 4.4 Agent accounting fields

| Field | Meaning |
|---|---|
| `tool_call_count` | Tool executions reported by the agent adapter |
| `input_tokens` | Input tokens when the provider exposes them |
| `output_tokens` | Output tokens when the provider exposes them |

Prompts, questions, answers, tool payloads, and raw evidence are forbidden in
the ledger.

### 4.5 Workspace provenance fields

| Field | Meaning |
|---|---|
| `artifact_kind` | Safe artifact class, not a filename |
| `artifact_ref_hash` | HMAC-SHA256 of the artifact reference using the audit-root key |
| `before_sha256`, `after_sha256` | Keyed digests of supplied content identifiers when available |

Raw absolute paths are not persisted. A keyed digest is used instead of an
unkeyed path hash because an unkeyed hash can disclose membership of predictable
paths. The key is local to the audit root and mode `0600`.

### 4.6 Boundary fields

Every event includes:

```json
{
  "telemetry_only": true,
  "runtime_safety_truth": false
}
```

These values are fixed by the schema and cannot be changed by a caller.

## 5. Sanitized example

```json
{
  "schema_version": "scout_runtime_audit_event.v1",
  "event_id": "audit-event-7c0f...",
  "runtime_instance_id": "runtime-20260807T030000Z-a1b2c3d4e5f6",
  "sequence": 18,
  "occurred_at": "2026-08-07T03:10:12.123Z",
  "recorded_at": "2026-08-07T03:10:12.127Z",
  "event_type": "workspace.io.completed",
  "outcome": "succeeded",
  "severity": "info",
  "category": "workspace",
  "subcategory": "artifact-write",
  "module": "admin-api",
  "feature": "workspace-operations",
  "operation": "write-operation-request",
  "summary": "Workspace data access recorded",
  "detail": null,
  "detail_code": null,
  "workspace_id": "chilai_nanhua_day1",
  "artifact_kind": "workspace_operation_request",
  "artifact_ref_hash": "4cf8...64-hex-characters...",
  "record_count": 1,
  "byte_count": 312,
  "previous_event_hash": "1bf2...",
  "event_hash": "76e9...",
  "telemetry_only": true,
  "runtime_safety_truth": false
}
```

## 6. Event taxonomy

| Event type | Main category | Purpose |
|---|---|---|
| `runtime.instance.started` | runtime | Runtime writer and manifest started |
| `runtime.instance.ended` | runtime | Clean shutdown completed |
| `http.request.completed` | dashboard | Internal Dashboard API result or success aggregate |
| `provider.call.completed` | provider | External provider result |
| `workspace.io.completed` | workspace | Instrumented artifact read/write |
| `agent.run.completed` | agent | Agent execution accounting without prompt/answer |
| `background_job.completed` | job | Scheduled or manually triggered background job |
| `audit.degraded` | audit | Crash recovery, writer gap, or audit subsystem degradation |
| `ui.session.started` | dashboard | Reserved for a future browser session implementation |
| `ui.session.heartbeat` | dashboard | Reserved; not emitted in v0.1 |
| `ui.session.expired` | dashboard | Reserved; not emitted in v0.1 |

All failures, retries, provider calls, agent runs, and workspace writes should be
individual events. Only explicitly high-volume successful traffic may be
aggregated. v0.1 aggregates successful tile requests by method, route template,
status, and outcome; tile failures remain individual.

## 7. Runtime manifest and crash semantics

Schema version: `scout_runtime_audit_manifest.v1`

The manifest records:

- runtime ID, application, profile, and optional workspace ID;
- status: `running`, `ended`, or `interrupted`;
- `started_at` and clean `ended_at`;
- `interruption_detected_at` when a later runtime detects an unclosed instance;
- shutdown reason;
- highest sequence, segment count, and last event hash.

A force kill cannot emit a trustworthy end event. On the next start, Scout:

1. marks the old manifest `interrupted`;
2. leaves the old `ended_at` as `null`;
3. records when the interruption was detected;
4. emits an `audit.degraded` event in the new runtime.

Recovery also removes a dead process's stale writer lock; it never removes the
lock of a sibling PID that is still alive.

It never fabricates a clean shutdown time for the crashed process.

There is one narrow recovery exception: if the end event itself is already a
valid, durable final event but the process stopped before replacing the final
manifest, recovery may mark the manifest ended using that event's recorded
time. This honors existing evidence; it does not synthesize an event.

## 8. Integrity, writer health, coverage, and retention

These are separate dimensions and the Dashboard must not collapse them into one
green status:

1. **Integrity** verifies sequence continuity, previous hash, and event hash.
2. **Writer health** reports whether the current process dropped audit events
   and the last safe error code.
3. **Coverage** reports which execution surfaces are fully, partially, or not
   instrumented.
4. **Retention** reports whether historical deletion policy is active. v0.1 is
   manual retention.

The SHA-256 event chain detects corruption and ordering errors. It is not a
digital signature, does not prove authorship, and is not tamper-proof against an
attacker who can rewrite the ledger and recompute hashes.

Audit failure must not fail the Scout operation being observed. The writer uses
best-effort recording, increments a dropped-event counter, exposes degraded
health, and emits a gap event after successful recovery when possible.

## 9. Query API

Read-only endpoint:

```text
GET /admin/runtime-audit
```

Filters:

- `event_type`
- `outcome`
- `category`
- `runtime_instance_id`
- `workspace_id`
- `limit` from 1 to 500

Response schema: `scout_runtime_audit_list.v1`

The response includes:

- aggregate counts, including represented internal API calls;
- filtered events;
- available runtime instances;
- integrity result;
- writer health;
- coverage matrix;
- fixed telemetry/safety boundary.

The endpoint is `Cache-Control: no-store`. Reading the endpoint is itself an
internal request, but it is recorded only after that response is constructed,
so a response never recursively contains its own event.

## 10. Privacy and security rules

Never persist:

- credentials, authorization headers, cookies, or environment values;
- raw HTTP query strings or request/response bodies;
- prompts, user questions, model answers, or tool payloads;
- raw GPX, health data, precise coordinates, or exact private location data;
- absolute home/workspace paths;
- stack traces or arbitrary exception messages.

Permitted values are typed counters, fixed codes, safe IDs, safe route
templates, keyed references, timestamps, and duration/accounting metadata.

Runtime audit storage is rejected when configured inside the monitored
workspace, avoiding self-observation recursion and accidental workspace export.

## 11. Verification requirements

Focused v0.1 tests must prove:

- strict typed input rejects arbitrary payload fields;
- append ordering, segment rotation, and hash verification;
- one writer per runtime instance;
- free-text secrets, paths, and coordinates never persist;
- artifact references use root-scoped keyed digests;
- crashed runtimes are marked interrupted without a fabricated end event;
- high-volume successes aggregate while failures remain individual;
- audit writer failure degrades audit health without failing Scout operations;
- Dashboard lifecycle, HTTP, workspace, provider, job, and agent paths emit the
  expected payload-free events;
- Dashboard Runtime Activity shows coverage and truthful empty-state language.

## 12. Promotion debt

Before productization, the highest-value work is:

1. force all workspace access through an audited `WorkspaceStore` boundary;
2. instrument remaining provider, agent, and background-job entrypoints;
3. define an operator-approved retention and export policy;
4. define multi-process aggregation and cross-host clock semantics;
5. add signed checkpoints or external anchoring if tamper evidence is required;
6. decide whether browser UI sessions add enough value to justify heartbeat and
   expiry traffic;
7. add disk-full, partial-write, concurrent reader, rotation, and process-crash
   fault tests on the deployment filesystem.
