# Scout Next Alpha Evidence Index

Date: 2026-05-27

Scope: next alpha preparation for the admin/pretrip/debug toolchain. This evidence covers local alpha validation only. It does not start live safety automation, mutate Phase 1 runtime safety state, drive real hardware, or call live `/safety/*` mutation endpoints.

## Included Alpha Features

- `/admin/debug` Monitoring Center tab and `/debug/monitoring` read-only projection.
- Scout agent/tools CLI registry, facade, trace projection, and second-batch pretrip/evidence tools.
- Spatial Imprint pretrip export and runtime trigger dry-run debug projection.
- Hardware-readiness summary rendered through `/admin/debug` by reading `/admin/hardware-readiness/context`.
- Pretrip MCP synthesis fixture integration for `chilai_nanhua_day1`.
- Pre-device alpha trace workflow for release checks, map preparation, pretrip provenance, readiness, and spatial imprint trigger dry-run.

## Local Release Gates

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_phase35_runtime_readiness_check.py \
  tests/test_phase4_pretrip_release_check.py \
  tests/test_scout_agent_builtin_manifests.py \
  tests/test_scout_cli.py \
  tests/test_debug_api.py \
  tests/test_scout_agent_debug_projection.py \
  tests/test_sensorlog_to_gpx.py \
  tests/test_pretrip_readiness.py \
  tests/test_pretrip_artifact_manifest.py::test_preserves_artifact_refs_paths_and_sha256_where_available \
  tests/test_pretrip_decision_register.py
```

Result: `81 passed in 125.94s`.

Release check summary:

- Phase 3.5: `ok=True`, missing required artifacts `0`.
- Phase 4 pretrip: `ok=True`, failed checks `[]`, missing required artifacts `0`.

## Local Alpha Runtime Smoke

Runtime command used for local smoke:

```bash
SCOUT_RUNTIME_PROFILE=local-alpha-workspace \
SCOUT_DATA_ROOT=/tmp/scout-alpha-data \
SCOUT_PRETRIP_WORKSPACE_ROOT=/tmp/scout-pretrip-alpha \
SCOUT_SAFETY_ENABLED=false \
SCOUT_AI_ASSISTANT_ENABLED=1 \
SCOUT_AI_ASSISTANT_PROVIDER=mock \
SCOUT_DEBUG_API_ENABLED=1 \
SCOUT_DEBUG_LOG_PATH=/tmp/scout-alpha-predevice/runtime-debug.jsonl \
SCOUT_AGENT_TRACE_LOG_PATH=/tmp/scout-alpha-predevice/agent-trace.jsonl \
SCOUT_SPATIAL_IMPRINT_TRIGGER_REPORT_PATH=/tmp/scout-alpha-predevice/spatial-trigger-report.json \
SCOUT_HARDWARE_READINESS_FIXTURE_PATH=/Users/alexwang0315/scout-fusion/tests/fixtures/hardware/readiness_context.json \
/Users/alexwang0315/scout-fusion/venv/bin/python -m uvicorn \
  phase4_admin_runtime:create_phase4_admin_runtime_app \
  --factory --host 127.0.0.1 --port 9099
```

Health boundary observed:

- `runtime_profile=local-alpha-workspace`
- `debug_api_enabled=true`
- `auth.required=false`
- `phase1_field_runtime_started=false`
- `safety_api_mutation_allowed=false`
- `hardware_control_allowed=false`
- `assistant_provider=mock`

Monitoring counts observed from `/debug/monitoring`:

- `event_count=9`
- `agent_tool_count=6`
- `release_check_count=2`
- `map_preparation_count=1`
- `spatial_imprint_event_count=3`
- `agent_tool_attention_count=0`

## Browser Smoke

Playwright target: `http://127.0.0.1:9099`

| Surface | Result | Checks |
| --- | --- | --- |
| `/admin` | PASS | after-action heading, checkpoint list, map route, no auth wall |
| `/admin/debug` | PASS | Monitor tab visible, agent tool count, release check count, hardware interface count, spatial imprint count, read-only boundary |
| `/admin/pretrip` | PASS | pretrip heading, `chilai_nanhua_day1`, checkpoint content, review UI content, no auth wall |

Console errors: `0`.

Screenshots:

- `/tmp/scout-alpha-predevice/screenshots/admin-after-action-rerun.png`
- `/tmp/scout-alpha-predevice/screenshots/admin-debug-monitor-rerun.png`
- `/tmp/scout-alpha-predevice/screenshots/admin-pretrip-rerun.png`

## Failure Classification

Blocking: none open.

Major: none open.

Minor:

- Detached background `uvicorn` is reaped in this local tool environment. Local smoke used a foreground PTY session and stopped it after validation.

GIS-related:

- No new GIS implementation was performed in this slice.
- GIS/map perception artifacts were rendered as existing debug/pretrip evidence only. Future map/risk score fixes should remain in the GIS/map/risk thread.

## Scout Hardware Follow-Up

Before declaring this alpha deployed, repeat the smoke against Scout hardware:

- `GET http://scout.local:9099/health`
- `GET http://scout.local:9099/admin`
- `GET http://scout.local:9099/admin/debug`
- `GET http://scout.local:9099/admin/pretrip`
- `GET http://scout.local:9099/admin/hardware-readiness/context`
- `GET http://scout.local:9099/debug/monitoring`

The hardware smoke must keep live `/safety/*` mutation closed unless an operator explicitly starts the live runtime test stage.
