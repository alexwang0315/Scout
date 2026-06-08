# Scout Phase 4.6 Tooling Milestone Closeout

Date: 2026-05-21

Status: `tooling_closed_pi_admin_debug_live_replay_passed`

## Scope

This closeout freezes the Phase 4.6 tooling milestone after replay-first live
runtime validation and Scout-hosted admin debug projection.

中文註釋：這份 closeout 代表真裝置連續串流的工具、准入模型與 dry-run/control
drill 已經收斂，也代表 mission-corridor simulated live-send 已經在
`scout.local` 驗證。它仍不代表 HTTPS 真裝置 Apple Watch/mobile live run，也不
代表允許自動 SOS / SMS / satellite / incident bridge。

## Tooling Delivered

- `docs/specs/phase-4-6-real-device-continuous-stream.md`;
- `docs/admin/scout-phase4-6-real-device-stream-slices.md`;
- `docs/admin/scout-phase4-6-replay-simulated-walk-plan.md`;
- `docs/admin/scout-phase4-6-real-device-live-run-plan.md`;
- `docs/admin/scout-phase4-6-live-replay-debug-projector.md`;
- `docs/admin/scout-phase4-6-pi-admin-debug-topology.md`;
- `docs/admin/scout-phase4-6-pi-admin-debug-live-replay-evidence.md`;
- `runtime_stream_device_identity.py`;
- `runtime_stream_replay_payloads.py`;
- `runtime_stream_real_device_harness.py`;
- `runtime_stream_real_device_policy_drill.py`;
- `runtime_stream_real_device_control_drill.py`.
- `phase46_live_replay_debug_projector.py`.

## Milestone Boundary

Delivered:

- metadata-only device identity registry;
- optional admission binding for registered real devices;
- summary-only real-device HTTP-push harness;
- prerecorded Apple Watch replay payload builder with 2x/3x accelerated
  original timing metadata;
- local 10Hz backpressure / offline retry / latest-point policy drill;
- dry-run-first operator pause/resume control drill;
- `/admin/debug` API payload windows and debug projection `Clear` action;
- Phase 4 admin runtime opt-in debug API on `scout.local:9110`;
- Pi-side projector path writing
  `/data/scout/admin/debug/runtime-debug-events.jsonl`;
- mission-corridor simulated live-send evidence with Scout-hosted debug events;
- focused tests and doc tests.

Not performed:

- no real Apple Watch/mobile live stream run;
- no HTTPS mobile endpoint;
- no real mobile TLS/server certificate setup;
- no live pause/resume mutation;
- no automatic SOS send;
- no SMS send;
- no satellite send;
- no incident bridge opt-in or live remote notification send;
- no hardware driver invocation;
- no Phase 2 Brain writeback;
- no raw payload or secret value persistence in repo artifacts.

## Completed Replay Live Runs

Evidence:

- `docs/admin/scout-phase4-6-mission-corridor-simulated-live-send-3x-evidence.md`;
- `docs/admin/scout-phase4-6-debug-ui-corridor-live-send-smoke-evidence.md`;
- `docs/admin/scout-phase4-6-pi-admin-debug-live-replay-evidence.md`.

Final Pi-admin replay smoke:

- admin debug URL: `http://scout.local:9110/admin/debug`;
- evidence directory:
  `/data/scout/deployments/phase46-pi-admin-debug-live-replay-3x-20260521T051431Z`;
- `live_harness_status=sent`;
- `live_harness_sent_count=2`;
- `projector_event_count=6`;
- `projector_accepted_delta=2`;
- `projector_observations_delta=2`;
- `projector_incident_delta=0`;
- `admin_debug_event_count=6`;
- `incident_delta_since_evidence_start=0`;
- `final_stream_control_status=observing`.

中文註釋：這是 operator-approved simulated live-send，使用貼合
`mission.normal_climb` corridor 的 replay fixture，不是 HTTPS 真手機或真 Apple
Watch 持續串流。

## Deferred True Device Run

The next milestone should perform a separate true-device run after HTTPS and
portable Scout hardware readiness are handled.

Replay-first and live run plans:

- `docs/admin/scout-phase4-6-replay-simulated-walk-plan.md`;
- `docs/admin/scout-phase4-6-real-device-live-run-plan.md`.

Required preconditions for the true-device run:

- live target confirmed, expected default `http://scout.local:9099`;
- operator selects Apple Watch or mobile source first;
- runtime observation admission secret is available only on the live machine;
- runtime stream control token is available only on the live machine;
- evidence directory is created under `/data/scout/deployments`;
- operator explicitly approves any live send or pause/resume drill.

Suggested order:

1. Generate a bounded replay batch with `runtime_stream_replay_payloads.py`
   using `--replay-speed-multiplier 2` first; use `3` only if the operator wants
   a more compressed simulated walk.
2. Run `runtime_stream_real_device_harness.py` as dry-run against the selected
   real-device payload fixture or captured local payload batch.
3. Run a bounded live send with `--send` and
   `--operator-approve-live-send`.
4. Run `runtime_stream_real_device_policy_drill.py` locally for policy evidence
   if the device cadence/offline behavior needs a local comparison artifact.
5. Run `runtime_stream_real_device_control_drill.py` first as dry-run, then
   with `--execute` and `--operator-approve-control-drill` only if operator
   wants to test live pause/resume.
6. Confirm final stream control status is `observing`.

中文註釋：live run 必須是獨立 milestone，因為它會碰真裝置資料與 live runtime。
即使工具已經存在，也不能把 closeout 自動解讀成已批准 live send 或 control mutation。

## Verification

Focused tooling verification:

```bash
venv/bin/python -m pytest \
  tests/test_phase46_real_device_continuous_stream_spec_doc.py \
  tests/test_phase46_real_device_stream_slices_doc.py \
  tests/test_phase46_replay_simulated_walk_plan_doc.py \
  tests/test_phase46_real_device_live_run_plan_doc.py \
  tests/test_runtime_stream_device_identity.py \
  tests/test_runtime_stream_replay_payloads.py \
  tests/test_runtime_stream_real_device_harness.py \
  tests/test_runtime_stream_real_device_policy_drill.py \
  tests/test_runtime_stream_real_device_control_drill.py \
  tests/test_phase46_live_replay_debug_projector.py \
  tests/test_phase46_pi_admin_debug_topology_doc.py \
  tests/test_phase46_pi_admin_debug_live_replay_evidence_doc.py \
  tests/test_runtime_input_admission.py \
  tests/test_runtime_stream_transport_api.py \
  tests/test_runtime_stream_controls.py \
  tests/test_safety_observation_admission_api.py
```

Release-adjacent verification:

```bash
venv/bin/python -m pytest tests/test_phase4_pretrip_release_check.py
```
