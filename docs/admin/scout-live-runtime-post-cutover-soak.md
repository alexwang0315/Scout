# Scout Live Runtime Post-Cutover Soak

Date: 2026-05-20

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Evidence directory:
`/data/scout/deployments/post-cutover-soak-20260520T102748Z`

## Scope

This bounded soak verifies that production `pi-field-live` remains healthy after
the HTTP push, WebSocket, and stream-control smokes.

中文註釋：這是 read-only soak。它只讀取 runtime 狀態，不送 observation、
不 pause/resume、不送 Telegram、不控制硬體。

## Sampling

The soak collected three samples with a five-second interval:

- `sample_count=3`;
- `interval_seconds=5`;
- `samples_all_ok=true`;
- `status=passed`.

Each sample checked:

- `GET /health`;
- `GET /assistant/status`;
- `GET /runtime/streams/status-read-only`;
- `GET /runtime/streams/control/status`;
- `GET /providers/control/status` with operator token.

Secret values were loaded only on the Scout machine. The report and summary
artifact do not embed token values.

## Final Summary

Final soak summary:

- `runtime_profile=pi-field-live`;
- `assistant_provider=pydantic_ai`;
- `assistant_startup_connection_status=connected:cloud`;
- `assistant_token_values_exposed=false`;
- `stream_control_status=observing`;
- `stream_control_record_count=3`;
- `stream_telemetry_totals.accepted_count=4`;
- `stream_telemetry_totals.rejected_count=4`;
- `stream_telemetry_totals.queued_count=0`;
- `stream_telemetry_totals.active_websocket_connections=0`;
- `provider_control_status=enabled`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `provider_control_token_value_exposed=false`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`.

## Incident Boundary

The soak did not send new observations, so IncidentStore stayed unchanged.

Result:

- `pre_incident_file_count=1`;
- `post_incident_file_count=1`;
- `incident_file_delta=0`.

## Boundary

Performed:

- read-only health checks;
- read-only assistant status checks;
- read-only runtime stream status checks;
- read-only runtime control status checks;
- read-only provider-control status checks.

Not performed:

- no new observations sent;
- no stream control mutation performed;
- no remote provider send;
- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no hardware control action;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation.

## Follow-Up Status

The original follow-up slices are now complete or deliberately scoped:

- rollback drill documentation:
  `docs/admin/scout-live-runtime-rollback-drill.md`;
- longer soak window:
  `docs/admin/scout-live-runtime-long-soak-automation.md`;
- packaged checker rebuild:
  `docs/admin/scout-live-runtime-long-soak-automation.md`;
- operator auth hardening:
  `docs/admin/scout-runtime-stream-control-post-cutover-smoke.md` and
  `docs/admin/scout-provider-control-status-auth-smoke.md`.

Rollback execution remains operator-only and is not required for this live activation evidence milestone.
