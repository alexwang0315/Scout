# Scout Phase 4.6 Debug UI Corridor Live-Send Smoke Evidence

Date: 2026-05-21

Status: `passed_debug_projection_visible`

Evidence directory:
`/data/scout/deployments/phase46-debug-ui-corridor-live-send-3x-20260521T042829Z`

## Scope

This smoke verified that `/admin/debug` can show live replay projection data from:

- `GET /debug/events`;
- `GET /debug/state`;
- `GET /debug/messages`.

The replay sender used a two-point subset of the already bounded
mission-corridor replay fixture:

- route source: `tests/fixtures/routes/normal_climb.gpx`;
- source id: `runtime_source.apple_watch.v0`;
- device id: `watch.replay.normal_climb_corridor.debug_smoke2`;
- sequence range: `460701..460702`;
- replay speed: `3x`;
- payload count: `2`.

中文註釋：這是 debug UI projection smoke，不是 HTTPS 真裝置驗證，也不是
Scout 可攜性驗證。目的只是確認 operator 在模擬 live-send 時能從本機
`/admin/debug` 看到 replay 訊號。

## Operator View

Open:

`http://127.0.0.1:9110/admin/debug?tab=api`

The `API` tab renders three read-only payload windows:

- `/debug/events`;
- `/debug/state`;
- `/debug/messages`.

`/debug/events` showed the projected event sequence:

- `debug_session_started`;
- `observation_ingested`;
- `route_progress_evaluated`;
- `observation_ingested`;
- `route_progress_evaluated`;
- `debug_session_completed`.

## Result

- `operator_approved_simulated_live_send=true`;
- `live_harness_status=sent`;
- `live_harness_sent_count=2`;
- `projector_status=debug_events_projected`;
- `projector_event_count=6`;
- `projector_accepted_delta=2`;
- `projector_observations_delta=2`;
- `incident_delta=0`;
- `final_stream_control_status=observing`;
- `final_safety_level=L2_CONCERN`.

The live runtime remained at `L2_CONCERN` because the same live process already
had prior incident state. This smoke uses `incident_delta=0` and visible debug
projection as the success criteria.

## Boundary

Performed:

- two signed HTTP push observations through
  `/runtime/streams/http-push/observations`;
- read-only projection from live runtime status into the local debug log;
- local `/admin/debug` rendering of the three read-only debug endpoint payloads.

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

- `payload-subset-summary.json`;
- `live-send-smoke2/real-device-continuous-stream-summary.json`;
- `debug-projector-events.jsonl`;
- `phase46-debug-ui-corridor-live-send-smoke-summary.json`;
- `phase46-debug-ui-events.json`;
- `phase46-debug-ui-state.json`;
- `phase46-debug-ui-messages.json`;
- `runtime-stream-status.before.json`;
- `runtime-stream-status.smoke2.after.json`;
- `runtime-status.before.json`;
- `runtime-status.smoke2.after.json`.
