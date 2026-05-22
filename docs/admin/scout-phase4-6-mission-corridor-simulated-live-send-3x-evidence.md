# Scout Phase 4.6 Mission-Corridor Simulated Live Send 3x Evidence

Date: 2026-05-21

Status: `passed_no_new_incident`

Evidence directory:
`/data/scout/deployments/phase46-mission-corridor-live-send-3x-20260521T032239Z`

## Scope

This run replaced the earlier `scout_260512` replay batch with a bounded replay
batch generated from the live mission corridor:

- mission graph: `tests/fixtures/mission_graph/normal_climb_mission.json`;
- route source: `tests/fixtures/routes/normal_climb.gpx`;
- device id: `watch.replay.normal_climb_corridor`;
- replay speed: `3x`;
- payload count: `5`.

中文註釋：這次仍是 simulated live-send，不是 HTTPS 真裝置，也不是 Scout
可攜性驗證。差異是 replay fixture 取自目前 live runtime 使用的 mission route，
因此用來驗證正常路線連續串流，而不是 field regression case。

## Prevalidation

Before live-send, the mission-corridor replay batch was checked against a clean
local runtime session.

- `prevalidation_status=passed`;
- `prevalidation_incident_count=0`;
- `prevalidation_checkpoint_hit_count=5`;
- `prevalidation_safety_level=L0_NORMAL`.

## Live Result

- `operator_approved_simulated_live_send=true`;
- `live_harness_status=sent`;
- `live_harness_sent_count=5`;
- `replay_speed_multiplier=3.0`;
- `planned_total_send_delay_ms=110694`;
- `http_accepted_delta=5`;
- `last_sequence_no_after=5`;
- `last_device_id_after=watch.replay.normal_climb_corridor`;
- `last_admission_status_after=admitted_not_forwarded`;
- `observations_processed_delta=5`;
- `incident_delta=0`;
- `health_status_after=ok`;
- `stream_control_status_after=observing`.

The live runtime had a prior `L2_CONCERN` state from the earlier stopped
`scout_260512` replay run:

- `safety_level_before=L2_CONCERN`;
- `safety_level_after=L2_CONCERN`.

中文註釋：這次成功條件是 `incident_delta=0` 和 stream/admission counters 正常增加。
因為同一個 live process 已經留有前一輪 L2 safety state，所以這次不把
`safety_level=L0_NORMAL` 當作 live 成功條件。

## Boundary

Performed:

- five signed HTTP push observations through
  `/runtime/streams/http-push/observations`;
- replay timing at 3x while preserving the original route cadence;
- read-only health/status captures before, during, and after live-send.

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

During the run, live observation used:

- `GET http://scout.local:9099/runtime/streams/status`;
- `GET http://scout.local:9099/runtime/status`;
- `GET http://scout.local:9099/runtime/streams/status-read-only`.

Observed progress:

- poll 1: `accepted_delta=2`, `incident_delta=0`;
- poll 2: `accepted_delta=4`, `incident_delta=0`;
- final: `accepted_delta=5`, `incident_delta=0`.

`/admin/debug` was not used as the primary monitor because the live runtime port
`9099` did not expose it, and the admin port `9110` required authorization.

## Follow-Up

- Use mission-corridor replay batches for normal-route live-send drills.
- Keep `scout_260512` as field regression evidence, not as the live normal-route
  acceptance fixture.
- Add a small operator monitor script for live replay runs so status polling is
  repeatable and less error-prone.
