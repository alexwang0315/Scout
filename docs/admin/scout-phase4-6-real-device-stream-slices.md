# Scout Phase 4.6 Real Device Stream Slices

Date: 2026-05-21

## Scope

This report records the first local Phase 4.6 slices for real Apple Watch /
mobile continuous stream readiness.

中文註釋：這些 slice 建立真裝置連續串流的 client harness 與 local policy drill。
它們不代表已經完成真裝置長時間 live field run，也不代表已啟用 SOS / SMS /
satellite / incident bridge。

Milestone status:

- tooling status: `closed`;
- live run status: `deferred_to_next_operator_approved_milestone`;
- closeout index:
  `docs/admin/scout-phase4-6-tooling-milestone-closeout.md`.

## Slice B: Real-Device Harness

Implemented:

- `runtime_stream_real_device_harness.py`;
- summary artifact name:
  `real-device-continuous-stream-summary.json`;
- dry-run is the default;
- network send requires both `--send` and `--operator-approve-live-send`;
- output stores payload hashes, request hashes, envelope ids, dedupe keys,
  response summaries, and boundary flags;
- output does not store raw SensorLog payloads or secret values.

Boundary:

- no automatic SOS send;
- no SMS send;
- no satellite send;
- no incident bridge enablement;
- no remote notification send;
- no hardware control;
- no Phase 2 Brain writeback.

## Slice C: Local Policy Drill

Implemented:

- `runtime_stream_real_device_policy_drill.py`;
- summary artifact name:
  `real-device-policy-drill-summary.json`;
- local-only sequence:
  `admitted_not_forwarded -> queued_backpressure -> queued_disconnected -> latest_point_retained`;
- device identity registry is used as metadata-only identity binding;
- admission decisions remain summary-only.

中文註釋：policy drill 是本機准入演練，不連 live runtime、不送 observation 到
`/runtime/streams/*` 或 `/safety/*`。它只證明 10Hz backpressure、offline retry、
latest-point fallback 的決策摘要可以產生 evidence。

## Slice D: Operator Control Drill

Implemented:

- `runtime_stream_real_device_control_drill.py`;
- summary artifact name:
  `real-device-control-drill-summary.json`;
- dry-run is the default and records planned routes only;
- live execution requires `--execute`,
  `--operator-approve-control-drill`, and an operator token;
- execution route plan is:
  `GET /runtime/streams/control/status`,
  `POST /runtime/streams/control/pause`,
  `POST /runtime/streams/control/resume`,
  `GET /runtime/streams/control/status`;
- passing execution requires final status restored to `observing`.

中文註釋：這個 control drill 是 server-side admission control / 伺服器端准入控制
演練，不是遙控 Apple Watch 或手機停止感測。沒有 explicit approval 時不會送出
pause/resume。

Boundary:

- no device hardware control;
- no observation payload send;
- no remote provider send;
- no SOS / SMS / satellite send;
- no incident bridge enablement;
- no Phase 2 Brain writeback;
- operator token is used only in Authorization header and is not serialized.

## Verification

Focused tests:

```bash
venv/bin/python -m pytest \
  tests/test_runtime_stream_real_device_harness.py \
  tests/test_runtime_stream_real_device_policy_drill.py \
  tests/test_runtime_stream_real_device_control_drill.py
```

Adjacent tests should include the runtime input admission, stream transport, and
Phase 4.6 spec-doc tests before closing this milestone.

## Live Run Deferral

The real Apple Watch/mobile live run is intentionally deferred.

中文註釋：這份 slices report 可以作為下一次 live run 的工具索引，但不能當作
operator approval。下一次若要對 `scout.local:9099` 送真裝置資料或執行
pause/resume control drill，必須另建 evidence directory，並由 operator 明確批准
`--send` / `--operator-approve-live-send` 或 `--execute` /
`--operator-approve-control-drill`。
