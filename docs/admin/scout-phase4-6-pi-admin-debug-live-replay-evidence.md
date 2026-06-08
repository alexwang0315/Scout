# Scout Phase 4.6 Pi Admin Debug Live Replay Evidence

Date: 2026-05-21

Status: `passed_pi_admin_debug_live_replay`

Evidence directory:
`/data/scout/deployments/phase46-pi-admin-debug-live-replay-3x-20260521T051431Z`

## Scope

This smoke verified the Scout-hosted operator debug topology:

```text
runtime replay sender
  -> scout.local:9099 live runtime ingest
  -> Pi-side projector in scout-pi-phase4-admin
  -> /data/scout/admin/debug/runtime-debug-events.jsonl
  -> http://scout.local:9110/admin/debug
```

中文註釋：這次不是 Mac local `/admin/debug` 投影，而是 Scout Pi 上的 admin
container 直接提供 operator debug UI。Mac 只作為 SSH/operator client。

## Deployment State

- `scout-pi-runtime-live`: remained healthy; not rebuilt or restarted.
- `scout-pi-phase4-admin`: rebuilt and restarted with debug API support.
- Admin debug URL: `http://scout.local:9110/admin/debug`.
- Debug log path: `/data/scout/admin/debug/runtime-debug-events.jsonl`.
- Admin auth remained required; unauthenticated `/admin/debug` returned HTTP `401`.
- Token values were not printed or embedded in evidence.

## Live Replay Smoke

Replay source:

- fixture: mission-corridor two-point replay payload;
- replay speed: `3x`;
- source id: `runtime_source.apple_watch.v0`;
- device id prefix: `watch.replay.normal_climb_corridor.pi_admin_live`;
- operator-approved simulated live-send: `true`.

Result:

- `live_harness_status=sent`;
- `live_harness_sent_count=2`;
- `projector_event_count=6`;
- `projector_accepted_delta=2`;
- `projector_observations_delta=2`;
- `projector_incident_delta=0`;
- `admin_debug_event_count=6`;
- `http_accepted_delta_since_evidence_start=2`;
- `observations_delta_since_evidence_start=2`;
- `incident_delta_since_evidence_start=0`;
- `final_stream_control_status=observing`;
- `final_safety_level=L2_CONCERN`.

Admin debug event sequence:

- `debug_session_started`;
- `observation_ingested`;
- `route_progress_evaluated`;
- `observation_ingested`;
- `route_progress_evaluated`;
- `debug_session_completed`.

The live runtime stayed at `L2_CONCERN` because the same live process already had
prior incident state. This smoke uses `incident_delta=0`, accepted/processed
counter deltas, and projected admin debug events as the success criteria.

## Boundary

Performed:

- two signed HTTP push observations through
  `/runtime/streams/http-push/observations`;
- Pi-side read-only projector polling live runtime status;
- Scout-hosted `/admin/debug` read of projected events;
- debug projection clear behavior validated in the preceding smoke.

Not performed:

- no automatic SOS send;
- no SMS send;
- no satellite send;
- no remote provider send;
- no hardware control action;
- no stream control mutation;
- no Phase 2 Brain writeback;
- no raw payload embedded in committed docs;
- no secret value embedded in committed docs.

## Evidence Files

- `phase46-pi-admin-debug-live-replay-summary.json`;
- `pi-side-projector-summary.json`;
- `debug-events.after-projector.json`;
- `debug-state.after-projector.json`;
- `debug-messages.after-projector.json`;
- `live-send/real-device-continuous-stream-summary.json`;
- `runtime-stream-status.before.json`;
- `runtime-stream-status.after-projector.json`;
- `runtime-status.before.json`;
- `runtime-status.after-projector.json`;
- `docker.after.txt`.
