# Scout Live Runtime Long Soak Automation

Date: 2026-05-20

Target: `scout.local`

Runtime URL: `http://scout.local:9099`

Latest short live smoke evidence:
`/data/scout/deployments/live-runtime-soak-check-20260520T110648Z`

Overnight soak started evidence:
`/data/scout/deployments/live-runtime-soak-overnight-20260520T110838Z`

Latest post-guard bounded soak evidence:
`/data/scout/deployments/live-runtime-soak-post-guard-20260520T153214Z`

Latest completed overnight soak evidence:
`/data/scout/deployments/live-runtime-soak-overnight-20260520T152647Z`

Latest packaged app rebuild evidence:
`/data/scout/deployments/live-head-rebuild-20260521T000120Z`

Latest packaged app soak smoke evidence:
`/data/scout/deployments/live-runtime-soak-packaged-app-20260521T000152Z`

## Scope

This slice adds `live_runtime_soak_check.py`, a repeatable read-only soak
checker for the production `pi-field-live` runtime.

中文註釋：這是 long soak automation foundation。它只使用 `GET` 讀取狀態，
不送 observation、不 pause/resume、不送 Telegram、不控制硬體、不回滾。

## Checked Surfaces

Each sample reads:

- `GET /health`;
- `GET /assistant/status`;
- `GET /runtime/streams/status-read-only`;
- `GET /runtime/streams/control/status`;
- `GET /providers/control/status`.

Provider-control status requires the operator token file:

- `/data/scout/secrets/hardware-provider-control-token`.

The token value is used only in the Authorization header and is not serialized
in the result.

## Short Live Smoke

The checker was copied into the current live container and run with three
samples at a two-second interval.

Command shape:

```bash
python /tmp/live_runtime_soak_check.py \
  --base-url http://127.0.0.1:9099 \
  --sample-count 3 \
  --interval-seconds 2 \
  --provider-token-file /data/scout/secrets/hardware-provider-control-token \
  --output /data/scout/deployments/live-runtime-soak-check-20260520T110648Z/live-runtime-soak-check-summary.json
```

Result:

- `artifact_kind=scout_live_runtime_soak_check`;
- `status=passed`;
- `sample_count=3`;
- `samples_recorded=3`;
- `samples_all_ok=true`;
- `runtime_profile=pi-field-live`;
- `assistant_provider=pydantic_ai`;
- `assistant_startup_connection_status=connected:cloud`;
- `assistant_token_values_exposed=false`;
- `provider_control_checked=true`;
- `provider_control_status=enabled`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `provider_control_token_value_exposed=false`;
- `stream_control_status=observing`;
- `stream_control_record_count=3`;
- `stream_telemetry_totals.accepted_count=4`;
- `stream_telemetry_totals.rejected_count=4`;
- `stream_telemetry_totals.queued_count=0`;
- `stream_telemetry_totals.active_websocket_connections=0`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`.

## Post-Guard Bounded Soak

After the signed HTTP push sample and live guard update, a bounded read-only
soak was run while the overnight soak continued in the background.

Evidence directory:
`/data/scout/deployments/live-runtime-soak-post-guard-20260520T153214Z`

Command path used:
`/tmp/live_runtime_soak_check.py`

中文註釋：這次 bounded soak 發生時，running container 尚未以包含 packaged
`/app/live_runtime_soak_check.py` 的 image 重建。為避免中斷當時正在跑的
overnight soak，本次 bounded soak 使用已在 container 內的 `/tmp` checker。

Result:

- `status=passed`;
- `sample_count=6`;
- `interval_seconds=10`;
- `samples_all_ok=true`;
- `runtime_profile=pi-field-live`;
- `health_status=ok`;
- `assistant_provider=pydantic_ai`;
- `assistant_startup_connection_status=connected:cloud`;
- `assistant_token_values_exposed=false`;
- `stream_control_status=observing`;
- `stream_telemetry_totals.accepted_count=0`;
- `stream_telemetry_totals.rejected_count=0`;
- `stream_telemetry_totals.queued_count=0`;
- `stream_telemetry_totals.active_websocket_connections=0`;
- `provider_control_status=enabled`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `provider_control_token_value_exposed=false`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`;
- `overnight_soak_still_running=true`;
- `read_only_soak=true`;
- `new_observations_sent=false`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`.

## Packaging

`live_runtime_soak_check.py` is included in the live Docker image contract:

- `Dockerfile.pi.live` copies `live_runtime_soak_check.py`;
- `.dockerignore` explicitly allows `live_runtime_soak_check.py`.

The 2026-05-21 packaged app rebuild verified this contract, so future soaks
should use the `/app/live_runtime_soak_check.py` path rather than manual
`docker cp`.

## Packaged App Rebuild Smoke

After the completed overnight soak, the live image was rebuilt from repo commit
`7a2ec4ef` and the production `scout-pi-runtime-live` container was recreated.

Deployment evidence directory:
`/data/scout/deployments/live-head-rebuild-20260521T000120Z`

Packaged app soak evidence directory:
`/data/scout/deployments/live-runtime-soak-packaged-app-20260521T000152Z`

Summary artifact:
`packaged-app-rebuild-summary.json`

Result:

- `artifact_kind=scout_live_runtime_packaged_app_rebuild_summary`;
- `status=deployed`;
- `repo_commit=7a2ec4ef`;
- `health_status=ok`;
- `runtime_profile=pi-field-live`;
- `runtime_stream_transport_enabled=true`;
- `remote_provider_live_send_enabled=true`;
- `hardware_provider_control_enabled=true`;
- `packaged_soak_checker_path=/app/live_runtime_soak_check.py`;
- `packaged_signed_sample_client_path=/app/runtime_stream_signed_sample_client.py`;
- `packaged_soak_checker_present=true`;
- `packaged_signed_sample_client_present=true`;
- `packaged_tools_py_compile_ok=true`;
- `soak_status=passed`;
- `soak_sample_count=3`;
- `soak_samples_recorded=3`;
- `soak_samples_all_ok=true`;
- `assistant_provider=pydantic_ai`;
- `assistant_startup_connection_status=connected:cloud`;
- `assistant_token_values_exposed=false`;
- `provider_control_status=enabled`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `provider_control_token_value_exposed=false`;
- `stream_control_status=observing`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`;
- `read_only_soak=true`;
- `new_observations_sent=false`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`.

中文註釋：這次 rebuild 只把已測過的工具正式放進 live image 內，並用 packaged
`/app/live_runtime_soak_check.py` 做三筆 read-only smoke。它沒有送新 observation，
沒有 pause/resume，沒有 Telegram / SOS / SMS / satellite send，也沒有硬體控制或
Phase 2 writeback。

## Longer Run

For a longer soak window, keep the command read-only and increase the sample
count and interval:

```bash
python /app/live_runtime_soak_check.py \
  --base-url http://127.0.0.1:9099 \
  --sample-count 120 \
  --interval-seconds 60 \
  --provider-token-file /data/scout/secrets/hardware-provider-control-token \
  --output /data/scout/deployments/live-runtime-soak-overnight/live-runtime-soak-check-summary.json
```

This example samples for roughly two hours. Overnight runs should use a fresh
deployment directory with a timestamp.

## Overnight Run Started

An overnight read-only soak was started on the Scout machine after the short
smoke passed.

Started summary:

- `artifact_kind=scout_live_runtime_overnight_soak_start`;
- `status=started`;
- `deploy_dir=/data/scout/deployments/live-runtime-soak-overnight-20260520T110838Z`;
- `host_nohup_pid=45009`;
- `sample_count=480`;
- `interval_seconds=60`;
- `read_only_soak=true`;
- `new_observations_sent=false`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `secret_values_embedded=false`;
- `raw_payloads_embedded=false`.

中文註釋：這個 overnight soak 已啟動但尚未完成。本文件只記錄 started
狀態；完成後要讀取同一個 evidence directory 的
`live-runtime-soak-check-summary.json` 再更新 completed report。

## Overnight Run Completed

Completed evidence directory:
`/data/scout/deployments/live-runtime-soak-overnight-20260520T152647Z`

Completed summary artifact:
`live-runtime-soak-check-summary.json`

Condensed completed summary artifact:
`overnight-completed-summary.json`

Result:

- `artifact_kind=scout_live_runtime_soak_check`;
- `status=passed`;
- `sample_count=480`;
- `samples_recorded=480`;
- `interval_seconds=60`;
- `samples_all_ok=true`;
- `blocker_reasons=[]`;
- `runtime_profile=pi-field-live`;
- `assistant_provider=pydantic_ai`;
- `assistant_startup_connection_status=connected:cloud`;
- `assistant_token_values_exposed=false`;
- `provider_control_checked=true`;
- `provider_control_status=enabled`;
- `provider_control_allowed_actions=[read_provider_status]`;
- `provider_control_token_value_exposed=false`;
- `stream_control_status=observing`;
- `stream_control_record_count=0`;
- `stream_telemetry_totals.accepted_count=0`;
- `stream_telemetry_totals.rejected_count=0`;
- `stream_telemetry_totals.queued_count=0`;
- `stream_telemetry_totals.active_websocket_connections=0`;
- `first_sample_ok=true`;
- `last_sample_ok=true`;
- `first_sample_index=0`;
- `last_sample_index=479`;
- `raw_payloads_embedded=false`;
- `secret_values_embedded=false`;
- `read_only_soak=true`;
- `new_observations_sent=false`;
- `stream_control_mutation_performed=false`;
- `remote_provider_send_performed=false`;
- `hardware_control_performed=false`;
- `phase2_writeback_performed=false`;
- no `live_runtime_soak_check.py` process remained after completion.

中文註釋：這份 completed report 代表 overnight read-only soak 完成。它沒有送新
observation，沒有 pause/resume，沒有 Telegram / SOS / SMS / satellite send，
也沒有啟用 incident bridge、硬體控制、Phase 2 writeback 或 review mutation。

## Boundary

Performed in this slice:

- added a read-only soak checker;
- ran one short three-sample live smoke;
- started one overnight read-only soak;
- recorded one completed overnight read-only soak;
- packaged the checker into the live image contract;
- rebuilt the live image after the overnight soak completed;
- verified the packaged `/app/live_runtime_soak_check.py` path with a
  three-sample read-only smoke.

Not performed:

- no new observations sent;
- no stream control mutation performed;
- no remote provider send;
- no Telegram send;
- no SOS send;
- no SMS send;
- no satellite send;
- no hardware control action;
- no rollback;
- no Phase 2 Brain writeback;
- no ObservedFact write;
- no HumanReview or review decision mutation.
