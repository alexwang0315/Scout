# Spec: Admin Debug Operator Console Alpha

Date: 2026-05-22

## Objective

Upgrade `/admin/debug` from a read-only engineering replay viewer into the alpha
operator debug console for Scout hardware/software state.

The surface should continuously improve toward three duties:

- receive Scout hardware and software status events;
- run simulator/live-run rehearsals through explicit operator actions;
- show Scout software responses as auditable state, advice, blocked actions, and
  boundary metadata.

中文註釋：這不是把 `/admin/debug` 變成自動 safety controller。硬體 trigger 只
產生事件；Scout response 必須是可追溯、可阻擋、可回放的 response artifact。

## Commands

Current alpha checks:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python phase4_pretrip_release_check.py

/Users/alexwang0315/scout-fusion/venv/bin/python -m pytest -q \
  tests/test_debug_api.py \
  tests/test_debug_page.py \
  tests/test_phase46_live_replay_debug_projector.py \
  tests/test_runtime_stream_transport_api.py \
  tests/test_runtime_stream_controls.py
```

Read-only Scout live hardware probe:

```bash
/Users/alexwang0315/scout-fusion/venv/bin/python \
  scout_hardware_readiness_live_probe.py \
  --host scout \
  --pretty > /tmp/scout-hardware-readiness-live-probe.json
```

Local admin preview:

```bash
SCOUT_DATA_ROOT=/tmp/scout-fusion-data \
SCOUT_PRETRIP_WORKSPACE_ROOT=/tmp/scout-fusion-pretrip-workspaces \
SCOUT_DEBUG_API_ENABLED=true \
SCOUT_AI_ASSISTANT_ENABLED=true \
SCOUT_HARDWARE_READINESS_FIXTURE_PATH=/tmp/scout-hardware-readiness-live-probe.json \
/Users/alexwang0315/scout-fusion/venv/bin/python -m uvicorn \
  phase4_admin_runtime:create_phase4_admin_runtime_app \
  --factory --host 127.0.0.1 --port 9099
```

## Project Structure

- `docs/admin/phase-3-5-runtime-debug.html` is the current static debug UI.
- `debug_api.py` owns `/debug/events`, `/debug/state`, `/debug/messages`, and
  `/debug/clear`.
- `hardware_readiness_api.py` owns `/admin/hardware-readiness` and
  `/admin/hardware-readiness/context`; `/admin/debug` should read this context
  directly for hardware status instead of duplicating the hardware readiness
  source of truth.
- `phase46_live_replay_debug_projector.py` projects runtime status into debug
  JSONL events.
- `runtime_stream_*` modules own signed stream admission, telemetry, and
  operator controls.
- `scout_hardware_readiness_live_probe.py` performs a read-only SSH probe against
  `scout`/`scout.local` and emits fixture-compatible hardware readiness JSON.
- Future hardware trigger adapters should write `HardwareControlEvent` or debug
  projection events before any runtime action is considered.

## Alpha Test Checklist

| Area | Alpha expectation | Classification if failed |
| --- | --- | --- |
| `/admin/debug` visual | Timeline, map, state tabs, boundary tab render on desktop/mobile. | major |
| `/admin/debug` data | Chilai or simulator/live-run events are visible through the surface. | major |
| Simulator live run | Projector can append sanitized live-run status events. | blocking if runtime mutation is hidden, otherwise major |
| Hardware trigger ingest | Button/switch/encoder events become explicit trigger artifacts. | major |
| Scout response display | Response shows accepted, blocked, advisory, and boundary metadata. | major |
| Hardware readiness tab | `/admin/debug` renders `/admin/hardware-readiness/context` as a dedicated hardware status tab. | major |
| Hardware interface inventory | GPIO, I2C, I2S, Bluetooth, TTS/audio, UART, battery, GPS/GNSS, IMU, USB devices, SSD/storage, and future buses can be represented with status, signal activity, last seen time, and evidence source. | major |
| GPIO state visibility | GPIO pins can show observed pull high/low, direction, source device, debounce policy, and whether the value is fixture, simulator, or live-observed. | major |
| Stream controls | Pause/resume/drain/end are operator-triggered and logged. | blocking if automatic |
| Safety boundary | No automatic `/safety/*`, SOS, SMS, satellite, incident bridge, or Phase 2 writeback. | blocking |
| Artifact boundary | Every operator-triggered action records mutation scope and raw-payload policy. | blocking |
| GIS/map rendering | Route, segment, checkpoint, layer, raster, and tile defects are evidence-only here. | GIS-related |

## Hardware Readiness Aggregation

Hardware readiness remains the source of truth for hardware status. `/admin/debug`
adds a dedicated `Hardware` tab that fetches and renders
`/admin/hardware-readiness/context`.

中文註釋：硬體資訊可以集中在 hardware-readiness；`/admin/debug` 不另做第二套
資料模型，而是把 hardware-readiness 當作 operator console 的一個 read-only
view。這樣硬體 readiness、AI assistant context、debug operator console 會共用同
一份 evidence boundary。

Hardware readiness should evolve toward an interface inventory:

- GPIO: pin number, label, direction, pull state high/low, last edge, debounce
  policy, manual drive capability, and raw evidence reference.
- I2C: bus id, detected addresses, active device labels, transaction/error
  counters, and last seen time.
- I2S / audio / TTS: sink, voice engine, playback transport, last command,
  queue state, and output result.
- Bluetooth: adapter status, paired devices, connected devices, signal quality,
  and last reconnect attempt.
- UART: port, baud, framing, last packet, error count, and connected module.
- Battery / power: voltage, percent, charge state, current draw, thermal state,
  and brownout/watchdog flags.
- GPS/GNSS and IMU: provider status, sample rate, fix/accuracy, drift, dropout,
  and calibration state.
- USB devices: vendor/product id, mount or serial path, permission state, and
  disconnect/reconnect events.
- SSD/storage: mount path, filesystem, free space, SMART/health summary when
  available, write/read error counters, and data-root mapping.

Manual GPIO pull high/low is a future lab-only control path, not a default debug
read action. It needs an explicit operator-confirmed request artifact with:

- target pin and intended value;
- lab mode or simulator mode marker;
- pre/post observed state;
- mutation boundary saying it did not call `/safety/*`, did not send outbound,
  did not write Phase 2, and did not alter Scout safety decisions;
- hardware-readiness source path and debug timeline event reference.

2026-05-22 read-only Scout probe note:

- `scout.local` SSH read-only probe succeeded as user `alexwang0315`.
- Observed OS/kernel: Linux `6.12.75+rpt-rpi-2712` on `aarch64`.
- Observed SSD/storage: `KINGSTON SNV3S1000G`, USB transport, root mount `/`,
  ext4, about `861G` free at probe time.
- Observed Bluetooth: adapter `88:A2:9E:58:EF:4A`, powered on.
- Observed UART: `/dev/ttyAMA10`.
- Observed USB: `0b05:1bc3` ASUS Cobble.
- Observed GPIO tooling: `gpioinfo` and `gpiodetect` are present; GPIO line
  direction is visible, but high/low value was not sampled in this slice.
- Pi 5 J8 header GPIO capability baseline: all 28 header GPIO lines reported by
  Pi 5 pinout are represented as `manual_read_allowed=true` and
  `manual_write_allowed=true` metadata. This includes GPIO0 and GPIO1, which are
  marked `reserved_advanced_use`, and GPIO2/GPIO3, which are marked
  `fixed_pull_up`. No write is performed by the probe; every future high/low
  drive still requires lab mode and explicit operator confirmation.
- GPIO Lab Mode policy update: operator-triggered `gpioset high/low` is allowed
  as an alpha lab capability, but implementation remains blocked until the
  physical experiment kit is wired and a wiring manifest is confirmed. Until
  then the artifact must keep `gpioset_command_enabled=false`,
  `wiring_manifest_confirmed=false`, and `write_performed_by_probe=false`.
- Observed I2C: no `i2cdetect` or `/dev/i2c-*` was seen in this probe.

This probe is read-only evidence. It did not drive GPIO, start runtime, call
`/safety/*`, send outbound messages, or write Phase 2 state.

## Hardware Trigger And Response Contract

Trigger event minimum fields:

- `trigger_id`
- `trigger_kind`: `button`, `encoder`, `switch`, `sensor_threshold`, `simulator`
- `source_device_id`
- `operator_intent`: `debug_only`, `stream_control_request`, `status_probe`
- `observed_at`
- `debounce_policy_ref`
- `raw_payload_ref` or `payload_hash`
- `phase1_runtime_mutation_requested`

Scout response minimum fields:

- `response_id`
- `response_kind`: `accepted`, `blocked`, `advisory`, `status_snapshot`
- `trigger_ref`
- `display_surface`: `/admin/debug`
- `boundary`
- `mutation`
- `operator_confirmation_required`
- `summary`

## Boundaries

Always:

- keep hardware triggers explicit and replayable;
- show blocked actions as first-class responses;
- keep raw payloads and secrets out of committed artifacts;
- require operator confirmation for state-changing alpha flows.

Ask first:

- hardware purchase above the experimental kit level;
- new live stream endpoints;
- real device credentials or secret storage;
- external provider sends.

Never:

- allow assistant output to trigger runtime control;
- turn hardware input into automatic SOS/SMS/satellite send;
- hide `/safety/*` calls behind debug UI interactions;
- write Phase 2 Brain state from `/admin/debug`.

## Success Criteria

- `/admin/debug` can display a simulator/live-run event stream with no console
  errors.
- Hardware trigger experiments can produce debug events without touching live
  safety runtime.
- Scout response artifacts distinguish accepted, blocked, advisory, and
  status-only responses.
- Operator-triggered stream controls are visible in timeline and boundary tabs.
- Alpha validation reports classify failures as blocking, major, minor, or
  GIS-related.
