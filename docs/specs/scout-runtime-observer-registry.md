# Spec: Scout Runtime Observer Registry

Date: 2026-06-17

Status: Draft for Pi 5 alpha field-runtime deployment

## Objective

Define which Scout observers are expected to run as resident background
processes on the Scout Pi, what evidence they produce, whether they can write
local OLED or LED Bar diagnostic feedback, and which safety boundaries they must
preserve.

中文註釋：這份文件是「常駐 observer registry」，不是 smoke tool 清單。只有被
`IngressObserverSupervisor`、systemd，或其他明確的 resident runtime owner 啟動並
持續 listen 的程序，才算 resident observer。

## Source Of Truth

Current repo source of truth:

- `ingress_observer_supervisor.py` owns the Phase 4 admin-runtime resident
  observer list.
- `phase4_admin_runtime.py` starts and stops the supervisor during the admin
  application lifespan.
- `GET /health` reports `ingress_observers.enabled`, `observer_count`,
  `running_count`, each observer status path, evidence directory, log path, and
  boundary flags.
- `docker-compose.pi.admin.yml` enables the admin-side observer supervisor with
  `SCOUT_INGRESS_OBSERVER_SUPERVISOR_ENABLED`.

As of this registry draft, the supervisor builds resident specs for exactly:

- `sensorlogger-mqtt`
- `gnss-hardware`

Keypad, IMU/PDR, UPS, Wi-Fi OLED status, LoRa diagnostics, and Grove smoke tools
may have scripts, systemd units, or old evidence. They are not resident Scout
ingress observers unless this registry and `IngressObserverSupervisor` are
updated together.

## Runtime Boundary

All resident observers in this registry are evidence producers and diagnostic
projection writers only.

They must not:

- call live `/safety/*` mutation endpoints;
- directly change Phase 1 L0-L4 safety state;
- send SOS, SMS, satellite, LoRaWAN uplink, MQTT publish, or other outbound
  device messages unless a future transport service explicitly owns that send;
- write Phase 2 Brain facts or review decisions;
- treat OLED or LED Bar output as product HMI or safety truth;
- expose credential values in logs, `/health`, status JSON, or docs.

Allowed outputs:

- append-only JSONL evidence;
- status JSON for admin/debug surfaces;
- bounded local diagnostic display on Grove OLED;
- bounded local diagnostic indicator on Grove LED Bar when explicitly enabled.

## Current Resident Observer Registry

| Observer | Resident owner | Autostart condition | Inputs | Evidence and status | OLED / LED feedback | Live Scout state observed 2026-06-17 |
| --- | --- | --- | --- | --- | --- | --- |
| `sensorlogger-mqtt` | Phase 4 admin runtime via `IngressObserverSupervisor` | `SCOUT_SENSORLOGGER_MQTT_AUTOSTART=true` and either `/data/scout/secrets/sensorlogger-mqtt.env` exists or inline broker/topic env vars exist | Sensor Logger compatible MQTT topic, usually phone or wearable sensor stream | `/data/scout/admin/ingress/sensorlogger_mqtt/`; status file `sensorlogger_mqtt_status.json`; log file `sensorlogger-mqtt-observer.log` | Optional OLED latency summary when `SCOUT_SENSORLOGGER_MQTT_OLED_STATUS=true`; no LED Bar integration in current resident path | Running inside `scout-pi-phase4-admin`; `/health` reported `running=true` |
| `gnss-hardware` | Phase 4 admin runtime via `IngressObserverSupervisor` | `SCOUT_GNSS_HARDWARE_AUTOSTART=true` or configured JSONL sources exist or `SCOUT_GNSS_HARDWARE_FORCE_AUTOSTART=true` | SX1303 gateway GPS NMEA JSONL and Grove GPS module JSONL | `/data/scout/admin/ingress/gnss_hardware/`; status file `gnss_hardware_observer_status.json`; snapshot `live_navigation_snapshot.json`; log file `gnss-hardware-observer.log` | Optional OLED status when `SCOUT_GNSS_HARDWARE_OLED_STATUS=true`; optional LED Bar blink when `SCOUT_GNSS_HARDWARE_LED_STATUS=true` | Running inside `scout-pi-phase4-admin`; `/health` reported `running=true`; live evidence updated under `gnss_hardware` |

## Observer: `sensorlogger-mqtt`

Purpose:

- Receive phone or wearable Sensor Logger MQTT messages.
- Preserve every accepted raw payload as evidence.
- Normalize Sensor/Vitals records for replay, export, and downstream filters.
- Expose message, latency, session, gap, duplicate, and out-of-order summaries
  to admin/debug surfaces.

Default resident paths:

```text
env file:     /data/scout/secrets/sensorlogger-mqtt.env
evidence dir: /data/scout/admin/ingress/sensorlogger_mqtt
log file:     /data/scout/admin/ingress/sensorlogger-mqtt-observer.log
status file:  /data/scout/admin/ingress/sensorlogger_mqtt/sensorlogger_mqtt_status.json
```

Key files written under the evidence directory:

```text
sensorlogger_mqtt_raw.jsonl
sensorlogger_mqtt_ingress_index.jsonl
sensorlogger_mqtt_sensor_vitals_records.jsonl
sensorlogger_mqtt_application_routes.jsonl
sensorlogger_mqtt_filter_outputs.jsonl
sensorlogger_mqtt_latency.jsonl
sensorlogger_mqtt_status.json
sensorlogger_mqtt_oled_status.jsonl  # only when OLED status is enabled
```

Local feedback:

- OLED is optional and disabled unless `SCOUT_SENSORLOGGER_MQTT_OLED_STATUS` or
  `--oled-status` is set.
- OLED content is a throttled routing latency summary. It is diagnostic display
  only.
- OLED writes default to `/dev/i2c-1`, address `0x3c`, driver `sh1107g`.
- `SCOUT_SENSORLOGGER_MQTT_OLED_DRY_RUN=true` records display payloads without
  writing I2C hardware.
- There is no current resident LED Bar feedback path for this observer.

Boundary fields:

```text
phase1_runtime_safety_truth=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
outbound_send_performed=false
hardware_control_scope=diagnostic_display_only for OLED records
remote_outbound_allowed=false for OLED records
```

## Observer: `gnss-hardware`

Purpose:

- Listen to JSONL evidence already produced by GNSS smoke tools.
- Merge SX1303 gateway GPS and Grove GPS evidence into one live navigation
  snapshot.
- Select a valid fix source when available.
- Preserve source status when no valid fix exists without fabricating `lat` or
  `lon`.

Default resident paths:

```text
gateway source: /data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl
grove source:   /data/scout/providers/gnss/manual-smoke.jsonl
evidence dir:   /data/scout/admin/ingress/gnss_hardware
log file:       /data/scout/admin/ingress/gnss-hardware-observer.log
status file:    /data/scout/admin/ingress/gnss_hardware/gnss_hardware_observer_status.json
snapshot file:  /data/scout/admin/ingress/gnss_hardware/live_navigation_snapshot.json
```

Important operating rule:

`gnss-hardware` does not directly open UART, `/dev/serial0`, `/dev/ttyAMA0`, or
USB serial ports. It reads JSONL files produced by lower-level hardware smoke
tools. This prevents the resident observer from stealing the serial device while
the operator is still debugging GPS hardware.

Local feedback:

- OLED is optional and enabled by `SCOUT_GNSS_HARDWARE_OLED_STATUS=true`.
- OLED message is short diagnostic text such as:

```text
SCOUT GNSS
FIX OK | NO FIX
SRC GATEWAY | SRC GROVE
SAT n CNO n
PORT ...
9600 BAUD
JSONL ONLY
```

- LED Bar is optional and enabled by `SCOUT_GNSS_HARDWARE_LED_STATUS=true`.
- Default LED behavior:
  - valid fix blinks `--led-fix-bit`, default LED10;
  - no valid fix blinks `--led-no-fix-bit`, default LED1;
  - current bench layout uses Grove LED Bar on `D5`, `GPIO5` data and `GPIO6`
    clock.
- OLED/LED dry-run flags record payloads without writing hardware:
  - `SCOUT_GNSS_HARDWARE_OLED_DRY_RUN=true`
  - `SCOUT_GNSS_HARDWARE_LED_DRY_RUN=true`

Boundary fields:

```text
runtime_safety_truth=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
rf_tx_allowed=false
lorawan_uplink_allowed=false
outbound_send_performed=false
hardware_control_scope=diagnostic_display_only for OLED records
hardware_control_scope=diagnostic_indicator_only for LED records
```

## Known Non-Resident Hardware Paths

These paths are useful Scout hardware assets, but they are not resident
observers in the current admin-runtime registry.

They are not resident observers until they have a resident owner, a status file,
bounded evidence writes, local feedback rules, and supervisor or systemd
coverage.

| Path | Current status | Why it is not resident yet | Promotion requirement |
| --- | --- | --- | --- |
| Keypad command bridge | Smoke/tooling exists for keypad scan, command candidate evidence, OLED/LED feedback, and local diagnostic commands | Not present in `IngressObserverSupervisor`; no current resident process spec | Add a dedicated `keypad-hardware` observer spec, evidence/status/log paths, OLED/LED throttling, tests, and deployment env |
| IMU/PDR | Grove IMU, Hiwonder/WIT IMU, INS/DR, and vendor-fusion smoke tooling exists | Not present in `IngressObserverSupervisor`; current IMU/PDR files are diagnostic evidence/tool outputs | Add `imu-pdr-hardware` observer only after raw IMU/PDR source, sampling rate, CPU budget, and OLED/LED behavior are fixed |
| UPS HAT telemetry | Smoke, soak, and monitor tooling exists | Power monitor has been treated as a separate heartbeat/systemd/admin diagnostic, not an ingress observer | Decide whether UPS becomes resident observer, systemd monitor, or admin status adapter; define write cadence and low-battery local feedback |
| Wi-Fi/OLED boot status and phone uplink recovery | systemd services and tools exist for boot display and Bluetooth PAN recovery | Recovery services are boot/network helpers, not evidence-ingress observers | Keep in network recovery docs unless converted to resident network observer with evidence-only contract |
| LoRa / ChirpStack stack | Docker services can run LoRaWAN infrastructure and diagnostics | ChirpStack services are network/radio infrastructure, not Scout observer adapters yet | Add a LoRa gateway observer that reads gateway/MQTT evidence and explicitly separates RX evidence from TX/uplink authority |
| Grove smoke tools | Manual hardware verification tools for OLED, LED Bar, PIR, GPS, IMU, LoRa, keypad | Manual or one-shot by design | Promote only after each tool has a resident lifecycle, evidence schema, resource limits, and safety boundary tests |

## Promotion Checklist

Before any non-resident path is promoted into this registry:

1. Add a named observer spec to `IngressObserverSupervisor`.
2. Define default `evidence_dir`, `status_path`, and `log_path`.
3. Define start condition and explicit `SCOUT_*_AUTOSTART` env.
4. Add focused tests that prove the supervisor starts it without requiring real
   hardware.
5. Add boundary fields proving no Phase 1 mutation, no `/safety/*` call, and no
   outbound send.
6. Document OLED and LED Bar behavior, including dry-run mode.
7. Define polling cadence, queue size, JSONL retention expectation, and CPU/I/O
   budget.
8. Verify `/health` exposes configured/running state without exposing secrets.
9. Run a live Scout smoke and record observed process, status JSON, evidence
   updates, and visual feedback.

## Live Inspection Commands

Check configured/running observers:

```bash
curl -sS \
  -H "Authorization: Bearer $(cat /data/scout/admin/secrets/phase4-admin-token)" \
  http://127.0.0.1:9110/health
```

Inspect resident process lines:

```bash
ps -eo pid,ppid,stat,etime,cmd --no-headers \
  | grep -E 'scout_.*observer|sensorlogger|gnss-hardware' \
  | grep -v grep
```

Check evidence freshness:

```bash
find /data/scout/admin/ingress -maxdepth 3 -type f \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' \
  | sort \
  | tail -n 40
```

Check observer logs:

```bash
tail -n 80 /data/scout/admin/ingress/sensorlogger-mqtt-observer.log
tail -n 80 /data/scout/admin/ingress/gnss-hardware-observer.log
```

## Acceptance

This registry is current when:

- the resident list matches `IngressObserverSupervisor.from_env`;
- `/health.ingress_observers.configured_observer_names` matches the deployed
  resident names;
- every resident observer has evidence, status, log, local feedback, and
  boundary sections in this document;
- every non-resident hardware path is explicitly marked as non-resident until it
  is promoted through the checklist.
