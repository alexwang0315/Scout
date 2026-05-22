# Scout Phase 4.6 Live Replay Debug Projector

Date: 2026-05-21

Status: `tooling_ready`

## Scope

This slice connects live replay status to the existing `/admin/debug` surface by
projecting sanitized runtime status snapshots into the debug JSONL log.

中文註釋：`/admin/debug` 已經整合 `/debug/events`、`/debug/state`、
`/debug/messages`。這個 slice 不改 UI，而是讓 live replay 的 stream/runtime
status 變成 debug events，讓頁面能看到模擬串流訊號。

## Current Local Debug Surface

Current local dev server:

- URL: `http://127.0.0.1:9110/admin/debug`;
- debug API: `http://127.0.0.1:9110/debug/events`;
- state API: `http://127.0.0.1:9110/debug/state`;
- messages API: `http://127.0.0.1:9110/debug/messages`;
- current env: `SCOUT_DEBUG_LOG_PATH=/tmp/scout-phase35-ui-demo.jsonl`.

## Projector

Tool:

- `phase46_live_replay_debug_projector.py`.

Inputs:

- `GET http://scout.local:9099/runtime/streams/status`;
- `GET http://scout.local:9099/runtime/status`.

Output:

- sanitized debug JSONL events for `/admin/debug`.

Example for the current local debug page:

```bash
venv/bin/python phase46_live_replay_debug_projector.py \
  --stream-status-url http://scout.local:9099/runtime/streams/status \
  --runtime-status-url http://scout.local:9099/runtime/status \
  --output-jsonl /tmp/scout-phase35-ui-demo.jsonl \
  --session-id debug_session.phase46_live_replay.local \
  --mission-id mission.normal_climb \
  --poll-count 150 \
  --interval-seconds 1 \
  --replace
```

Then refresh:

```text
http://127.0.0.1:9110/admin/debug
```

中文註釋：projector 是 read-only。它只輪詢 status endpoint，逐次 append event；
它不送 replay payload、不 pause/resume stream、不操作 hardware。

## Events

The projector writes:

- `debug_session_started`;
- `observation_ingested` when HTTP push accepted count increases;
- `route_progress_evaluated` when runtime observations processed increases;
- `safety_event_emitted` when stored incident count increases;
- `debug_session_completed`.

`/debug/messages` remains integrated. It will return an empty list unless the log
contains outbound message events; the projector does not create outbound
messages because this slice does not send remote notifications.

## Boundary

Projected payloads include status/counter/hash fields only:

- accepted delta and accepted count;
- last sequence number;
- device id;
- source id;
- payload SHA-256;
- admission status;
- observations delta;
- stored incident delta;
- safety level;
- stream control status.

Not included:

- no raw observation payload;
- no latitude/longitude values;
- no secret values;
- no runtime mutation;
- no stream control mutation;
- no remote provider send;
- no hardware control action;
- no Phase 2 Brain writeback;
- no automatic SOS/SMS/satellite send.

## Acceptance

Focused check:

```bash
venv/bin/python -m pytest \
  tests/test_phase46_live_replay_debug_projector.py \
  tests/test_debug_api.py \
  tests/test_debug_page.py
```

## Local Smoke

Performed on 2026-05-21 against the current local debug server:

- local debug URL: `http://127.0.0.1:9110/admin/debug`;
- output log: `/tmp/scout-phase35-ui-demo.jsonl`;
- backup log:
  `/tmp/scout-phase35-ui-demo.backup.20260521T034152Z.jsonl`;
- session id: `debug_session.phase46_live_replay.local_smoke`;
- event count: `2`;
- accepted delta: `0`;
- observations delta: `0`;
- incident delta: `0`;
- final stream control status: `observing`.

中文註釋：這次 smoke 沒有同步跑 replay live-send，所以只會看到
`debug_session_started` 和 `debug_session_completed`。下一次在 replay live-send
期間啟動 projector，`/admin/debug` timeline 才會持續新增
`observation_ingested` 與 `route_progress_evaluated`。
