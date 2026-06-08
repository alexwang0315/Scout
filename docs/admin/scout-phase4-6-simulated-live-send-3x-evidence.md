# Scout Phase 4.6 Simulated Live Send 3x Evidence

Date: 2026-05-21

Status: `stopped_on_incident_delta`

Evidence directory:
`/data/scout/deployments/phase46-simulated-live-send-3x-20260521T031347Z`

## Scope

This run used the prerecorded Apple Watch replay batch as an operator-approved
simulated live-send drill at 3x replay speed.

中文註釋：這次不是 HTTPS 真裝置，也不是可攜 Scout 外殼/電池/storage 驗證；它是
使用預錄 Apple Watch 軌跡，對 live runtime 的 stream HTTP push 入口做一次
operator-approved simulated live-send。

## Result

- `operator_approved_simulated_live_send=true`;
- `replay_speed_multiplier=3.0`;
- `payload_count_planned=5`;
- `payload_count_sent_before_stop=1`;
- `planned_total_send_delay_ms=1010028`;
- `http_accepted_before=1`;
- `http_accepted_after_stop=2`;
- `last_sequence_no_after_stop=1`;
- `last_device_id_after_stop=watch.replay.260512`;
- `last_admission_status_after_stop=admitted_not_forwarded`;
- `observations_processed_before=2`;
- `observations_processed_after_stop=3`;
- `safety_level_before=L0_NORMAL`;
- `safety_level_after_stop=L2_CONCERN`;
- `stored_incidents_before=1`;
- `stored_incidents_after_stop=2`;
- `incident_delta=1`;
- `health_status_after_stop=ok`;
- `stream_control_status_after_stop=observing`;
- `live_send_summary_written=false`.

## Stop Reason

The first replay sample was accepted, but read-only runtime status then showed:

- `safety_level=L2_CONCERN`;
- `stored_incidents` increased by 1.

The remaining replay samples were stopped before they were sent.

中文註釋：這是正確的 stop condition。雖然沒有 SOS/SMS/satellite，也沒有 remote
provider send，但 replay batch 對目前 normal mission fixture 不是
non-incident-producing，因此不能繼續當作正常路線連續串流測試。

## Boundary

Performed:

- one signed HTTP push observation through
  `/runtime/streams/http-push/observations`;
- read-only health/status captures before and after stop;
- process stop before the second replay sample.

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

## Observation Path

The live runtime did not expose `/admin/debug` on port `9099`.

Available live observation endpoints were:

- `GET http://scout.local:9099/runtime/streams/status`;
- `GET http://scout.local:9099/runtime/status`;
- `GET http://scout.local:9099/runtime/streams/status-read-only`.

The admin/debug surface on port `9110` returned `401` without admin
authorization. It is a debug snapshot surface backed by `/debug/events` and
`/debug/state`; it should not be treated as the primary live stream monitor
until auth and live debug event wiring are explicitly enabled.

## Follow-Up

- Build a replay fixture that is known to remain on the active mission corridor
  before another live-send drill.
- Add an operator monitor script that polls runtime stream status and runtime
  status side by side during long 2x/3x replay runs.
- Keep HTTPS server and Scout portability work as a later hardware/live
  readiness milestone.
