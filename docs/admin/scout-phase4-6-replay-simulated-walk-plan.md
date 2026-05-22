# Scout Phase 4.6 Replay Simulated Walk Plan

Date: 2026-05-21

Status: `plan_ready_not_executed`

## Scope

This slice adds a replay-based simulated walk before the true device live run.
The replay uses the original prerecorded Apple Watch sample timing, accelerated
by an explicit 2x or 3x multiplier.

中文註釋：先用預錄 Apple Watch 軌跡回放模擬行走，並以當初錄製的時間間隔
加速 2x 或 3x 回放；不先建立 HTTPS server，
也不先處理電池、storage、外殼、防水、背負固定等 Scout 可攜性問題。那些是
下一個 hardware/live readiness milestone 的範圍。

## Replay Source

Use the existing field regression fixture:

- route: `tests/fixtures/routes/scout_260512_field_route.gpx`;
- source case: `tests/fixtures/field_cases/scout_260512_golden.json`;
- original source: prerecorded Apple Watch SensorLog exported into repo
  fixtures.

中文註釋：`scout_260512` 保持 field-data-to-fixtures regression case，不當主要
mountain calibration。這裡使用它是因為它能安全模擬真 Apple Watch 行走資料流。

## Tooling

New payload builder: `runtime_stream_replay_payloads.py`

```bash
python runtime_stream_replay_payloads.py \
  --route tests/fixtures/routes/scout_260512_field_route.gpx \
  --payloads-output "$PHASE46_EVIDENCE_DIR/replay-payloads.json" \
  --summary-output "$PHASE46_EVIDENCE_DIR/replay-payloads-summary.json" \
  --source-id runtime_source.apple_watch.v0 \
  --source-kind apple_watch \
  --device-id watch.replay.260512 \
  --sample-stride 250 \
  --max-points 10 \
  --replay-speed-multiplier 2
```

The first replay should use `--replay-speed-multiplier 2`; for a more
compressed walk simulation, rerun the same command with
`--replay-speed-multiplier 3`. The generated batch includes
`replay_timing.original_intervals_ms` and `replay_timing.send_delays_ms`, so the
next harness step can preserve the original recording cadence while replaying it
at 2x or 3x speed. Accelerated delays are clamped to the 10Hz backpressure
floor: first sample delay is 0ms, and every later replay delay is at least
100ms.

The generated payload batch can then feed `runtime_stream_real_device_harness.py`:

```bash
python runtime_stream_real_device_harness.py \
  --base-url http://127.0.0.1:9099 \
  --payloads "$PHASE46_EVIDENCE_DIR/replay-payloads.json" \
  --secret-file /data/scout/secrets/runtime-stream-admission-secret \
  --source-id runtime_source.apple_watch.v0 \
  --source-kind apple_watch \
  --device-id watch.replay.260512 \
  --evidence-dir "$PHASE46_EVIDENCE_DIR/replay-dry-run"
```

Dry-run mode records the timing metadata in the summary but does not sleep and
does not send. If a later live-send run is explicitly approved, the harness uses
`replay_timing.send_delays_ms` between samples so the replay follows the
accelerated prerecorded cadence instead of a synthetic fixed interval. The
harness also clamps externally supplied replay timing to the same 10Hz floor.

## Boundary

- no live send in this slice;
- no `scout.local` network call;
- no HTTPS server creation;
- no battery/runtime endurance validation;
- no storage durability validation;
- no enclosure/weatherproofing validation;
- no automatic SOS send;
- no SMS send;
- no satellite send;
- no incident bridge opt-in;
- no Phase 2 Brain writeback.

raw payload batch 可以存在 evidence directory，因為下一步 harness 需要它作為
輸入；summary artifact 不嵌入 raw payload，只保留 payload hash、count、source
metadata 與 boundary flags。

## Stop Conditions

Stop before live run if:

- replay payload builder cannot produce a bounded payload batch;
- payload summary includes raw `locationLatitude` or `locationLongitude`;
- payload count exceeds the bounded first-run target;
- generated dry-run summary leaks secret values;
- generated dry-run summary marks any network send as performed.

## Future Hardware / HTTPS Work

True real-device operation still needs separate milestones:

- HTTPS server or reverse proxy for real device submission;
- certificate provisioning and local trust model;
- Scout portable power budget and battery swap policy;
- storage write endurance and free-space monitoring;
- enclosure, waterproofing, thermal behavior, and mount stability;
- field rollback/restore plan for portable deployment.

中文註釋：這些可攜性項目會影響真正上山使用，但不應阻塞目前用預錄軌跡驗證
runtime stream admission / dedupe / telemetry 的 deterministic path。
