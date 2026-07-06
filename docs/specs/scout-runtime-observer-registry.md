# Spec: Scout Runtime Observer Registry

Date: 2026-06-17

Status: Draft for Pi 5 alpha field-runtime deployment

Last live verification: 2026-07-06 on Scout Pi 5 admin runtime.

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

As of this registry draft, the supervisor builds resident specs for:

- `sensorlogger-mqtt`
- `gnss-hardware`
- `sx1303-gateway`
- `lorawan-client`
- `physiologic-gate` when explicitly enabled for SensorLogger vitals replay

Latest verified Pi state on 2026-07-06:

- Docker container `scout-pi-phase4-admin` was `healthy`.
- `GET http://127.0.0.1:9110/health` returned `status=ok`.
- `/health.ingress_observers.observer_count=4`.
- `/health.ingress_observers.running_count=4`.
- `/health.ingress_observers.configured_observer_names` returned
  `gnss-hardware`, `lorawan-client`, `sensorlogger-mqtt`, and
  `sx1303-gateway`.
- `/health.ingress_observers.boundary.read_only=true`.
- `/health.ingress_observers.boundary.rf_tx_allowed=false`.
- `/health.ingress_observers.boundary.lorawan_uplink_allowed=false`.
- `/health.ingress_observers.boundary.downlink_allowed=false`.
- `/health.ingress_observers.boundary.phase1_l0_l4_state_mutated=false`.
- `/health.ingress_observers.boundary.safety_api_called=false`.

Keypad, IMU/PDR, UPS, Wi-Fi OLED status, Wio-E5 serial/RF executor tools, and
Grove smoke tools may have scripts, systemd units, or old evidence. They are
not resident Scout ingress observers unless this registry and
`IngressObserverSupervisor` are updated together. `lorawan-client` is the
resident evidence observer for Wio-E5 / LoRaWAN client status; it is not the RF
executor.

A future LoRaWAN sender / transport service is also intentionally outside this
resident observer list. It will be an explicit action path for approved local
commands, not a background listener. Its primary dashboard placement should be
the `MQTT / Observer Message` page, in a visually separated sender/action lane
that can show command candidates, queue state, readiness, and audit links.
`Safety / Emergency` may link to that sender lane when the pending candidate is
emergency-relevant, but it is not the primary sender workbench.

## Runtime Boundary

All resident observers in this registry are evidence producers and diagnostic
projection writers only.

`physiologic-gate` is also a `SafetyGateEvent` producer for the future Safety
Arbiter / State Reducer. It may recommend a physiologic gate candidate such as
`candidate_rest` or `candidate_retreat`, but the resident observer itself does
not own the final L0-L4 transition and does not call live safety mutation APIs.

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

| Observer | Resident owner | Autostart condition | Inputs | Evidence and status | OLED / LED feedback | Live Scout state observed 2026-07-06 |
| --- | --- | --- | --- | --- | --- | --- |
| `sensorlogger-mqtt` | Phase 4 admin runtime via `IngressObserverSupervisor` | `SCOUT_SENSORLOGGER_MQTT_AUTOSTART=true` and either `/data/scout/secrets/sensorlogger-mqtt.env` exists or inline broker/topic env vars exist | Sensor Logger compatible MQTT topic, usually phone or wearable sensor stream | `/data/scout/admin/ingress/sensorlogger_mqtt/`; status file `sensorlogger_mqtt_status.json`; log file `sensorlogger-mqtt-observer.log` | Optional OLED latency summary when `SCOUT_SENSORLOGGER_MQTT_OLED_STATUS=true`; no LED Bar integration in current resident path | Running inside `scout-pi-phase4-admin`; `/health` reported `running=true` |
| `gnss-hardware` | Phase 4 admin runtime via `IngressObserverSupervisor` | `SCOUT_GNSS_HARDWARE_AUTOSTART=true` or configured JSONL sources exist or `SCOUT_GNSS_HARDWARE_FORCE_AUTOSTART=true` | SX1303 gateway GPS NMEA JSONL and Grove GPS module JSONL | `/data/scout/admin/ingress/gnss_hardware/`; status file `gnss_hardware_observer_status.json`; snapshot `live_navigation_snapshot.json`; log file `gnss-hardware-observer.log` | Optional OLED status when `SCOUT_GNSS_HARDWARE_OLED_STATUS=true`; optional LED Bar blink when `SCOUT_GNSS_HARDWARE_LED_STATUS=true` | Running inside `scout-pi-phase4-admin`; `/health` reported `running=true`; live evidence updated under `gnss_hardware` |
| `sx1303-gateway` | Phase 4 admin runtime via `IngressObserverSupervisor` | `SCOUT_SX1303_GATEWAY_AUTOSTART=true` or explicit SX1303 gateway source/config env | Read-only gateway stack checks, Taiwan region config files, packet-forwarder/ChirpStack process hints, local host ports, uplink JSONL, and gateway GPS JSONL | `/data/scout/admin/ingress/sx1303_gateway/`; status file `sx1303_gateway_observer_status.json`; samples `sx1303_gateway_observer_samples.jsonl`; log file `sx1303-gateway-observer.log` | Optional OLED status when `SCOUT_SX1303_GATEWAY_OLED_STATUS=true`; optional LED Bar blink when `SCOUT_SX1303_GATEWAY_LED_STATUS=true` | Running inside `scout-pi-phase4-admin`; `/health` reported `running=true`; latest decision was `gateway_receiving_uplinks`, answerability `gateway_uplink_evidence_available`, uplink count `2` |
| `lorawan-client` | Phase 4 admin runtime via `IngressObserverSupervisor` | `SCOUT_LORAWAN_CLIENT_AUTOSTART=true`, explicit LoRaWAN client evidence source env, or existing default Wio-E5 / LoRaWAN evidence files | Wio-E5 key sync, profile provision, trial plan, RF trial, join audit, join-state diagnostic, passive uplink, MQTT tail status, and read-only AT JSONL evidence | `/data/scout/admin/ingress/lorawan_client/`; status file `lorawan_client_observer_status.json`; samples `lorawan_client_observer_samples.jsonl`; log file `lorawan-client-observer.log` | Optional OLED status when `SCOUT_LORAWAN_CLIENT_OLED_STATUS=true`; optional LED Bar blink when `SCOUT_LORAWAN_CLIENT_LED_STATUS=true` | Running inside `scout-pi-phase4-admin`; `/health` reported `running=true`; latest decision was `uplink_observed`, answerability `client_uplink_evidence_available` |
| `physiologic-gate` | Phase 4 admin runtime via `IngressObserverSupervisor` | Explicit `SCOUT_PHYSIOLOGIC_GATE_AUTOSTART=true` or explicit physiologic source config | Sanitized `sensorlogger_mqtt_sensor_vitals_records.jsonl`, optional baseline JSON, optional route context JSON | `/data/scout/admin/ingress/physiologic_gate/`; status file `physiologic_gate_status.json`; event `physiologic_safety_gate_event.json`; reducer dry-run `physiologic_reducer_dry_run.json`; log file `physiologic-gate-observer.log` | No OLED or LED Bar integration in this slice | Optional resident candidate; emits `SafetyGateEvent` evidence for reducer handoff only |

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

## Observer: `sx1303-gateway`

Purpose:

- Keep a resident, read-only health observer for the SX1303 LoRaWAN gateway
  track.
- Detect whether packet-forwarder / Basic Station / ChirpStack bridge evidence
  is present.
- Check local gateway service ports without sending LoRaWAN uplinks or
  downlinks.
- Summarize host-side SX1303 SPI/chip-id preflight JSONL so the resident
  observer can distinguish `RF?` from `RF OK / no uplink yet` without touching
  SPI from inside the admin container.
- Scan configured gateway/ChirpStack region files for Taiwan-compatible
  `AS923`, `AS923_2`, or `AS923_TW_920_925` tokens and flag forbidden plans
  such as `EU868`, `US915`, or channels outside `920000000` to `925000000`.
- Summarize local uplink JSONL and gateway GPS JSONL freshness without treating
  either as Phase 1 safety truth.

Default resident paths:

```text
evidence dir:        /data/scout/admin/ingress/sx1303_gateway
log file:            /data/scout/admin/ingress/sx1303-gateway-observer.log
status file:         /data/scout/admin/ingress/sx1303_gateway/sx1303_gateway_observer_status.json
samples file:        /data/scout/admin/ingress/sx1303_gateway/sx1303_gateway_observer_samples.jsonl
uplink source:       /data/scout/providers/lora/sx1303-gateway-uplink.jsonl
gateway GPS source:  /data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl
RF preflight source: /data/scout/providers/lora/sx1303-gateway-smoke.jsonl
RX readiness source: /data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl
```

Key env:

```text
SCOUT_SX1303_GATEWAY_AUTOSTART=true
SCOUT_SX1303_GATEWAY_HOST=host.docker.internal
SCOUT_SX1303_GATEWAY_TCP_PORTS=1883,3001,8080,8090
SCOUT_SX1303_GATEWAY_UDP_PORTS=1700
SCOUT_SX1303_GATEWAY_CONFIG_PATHS=/data/scout/lora/global_conf.json,...
  /data/scout/providers/lora/chirpstack-docker/configuration/chirpstack/chirpstack.toml,
  /data/scout/providers/lora/chirpstack-docker/configuration/chirpstack/region_as923_2.toml,
  /data/scout/providers/lora/chirpstack-docker/configuration/chirpstack-gateway-bridge/chirpstack-gateway-bridge-basicstation-as923_2.toml
SCOUT_SX1303_GATEWAY_EXPECTED_REGION_TOKENS=AS923,AS923_2,AS923_TW_920_925
SCOUT_SX1303_GATEWAY_FORBIDDEN_REGION_TOKENS=EU868,US915,AU915,CN470,KR920,IN865,RU864
SCOUT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL=/data/scout/providers/lora/sx1303-gateway-smoke.jsonl
SCOUT_SX1303_GATEWAY_RX_READINESS_JSONL=/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl
SCOUT_SX1303_GATEWAY_OLED_STATUS=true
SCOUT_SX1303_GATEWAY_LED_STATUS=true
SCOUT_SX1303_GATEWAY_LED_PORT=D5
```

Local feedback:

- OLED is optional and enabled by `SCOUT_SX1303_GATEWAY_OLED_STATUS=true`.
- OLED message is short diagnostic text such as:

```text
SCOUT LORA GW
GW READY | NO FWD | WRONG REGION | CTRL OK RF? | RF OK NO UL | RX READY NO UL
REG AS923_2
FWD OK
BR OK
UL n
NO RF TX
```

- LED Bar is optional and enabled by `SCOUT_SX1303_GATEWAY_LED_STATUS=true`.
- Default LED behavior:
  - ready, RF preflight evidence, or uplink evidence blinks LED8;
  - degraded health such as no packet forwarder blinks LED1;
  - wrong region blinks LED10.
- Current bench layout uses Grove LED Bar on `D5`, `GPIO5` data and `GPIO6`
  clock.

Important operating rule:

`sx1303-gateway` is not a gateway controller. It does not start packet
forwarders, does not edit gateway config, does not join devices, does not send
LoRaWAN downlink, and does not generate uplink payloads. It is allowed to read
local process hints, local service ports, config files, and append-only JSONL
evidence only.

If the admin container can reach ChirpStack / MQTT TCP ports but cannot inspect
the host packet-forwarder process, the observer reports
`gateway_control_plane_reachable_rf_unknown`. This means the local control plane
is reachable, but the SX1303 RF receive path is not proven until a packet
forwarder / Basic Station process hint or uplink JSONL evidence appears.

If the host-side `tools/pi_sx1303_gateway_smoke.py` preflight has appended a
successful chip-id record with a gateway EUI to
`/data/scout/providers/lora/sx1303-gateway-smoke.jsonl`, the resident observer
may report `gateway_rf_hardware_detected_no_uplink`. This means SPI and the
SX1303 concentrator were proven, but no LoRaWAN client uplink has been observed
yet. The preflight tool is still diagnostic-only: it may reset/read the HAT over
GPIO/SPI, but it does not start packet forwarders, transmit RF, join a device,
or call `/safety/*`.

If the host-side `tools/pi_sx1303_gateway_rx_smoke.py` preflight has appended a
successful passive receive-readiness record to
`/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl`, the resident
observer may report `gateway_rx_stack_ready_no_uplink`. This means the local
ChirpStack / MQTT / gateway bridge receive-side stack is present enough to wait
for a client uplink, but Scout has still not seen a structured client uplink
record. The RX smoke stores counts and status only; it does not embed raw
gateway log lines by default.

If `tools/pi_sx1303_gateway_uplink_mqtt_tail.py` observes a local ChirpStack
MQTT uplink event, it appends a structured record to
`/data/scout/providers/lora/sx1303-gateway-uplink.jsonl`. No-uplink waits write
only `/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl`, so
the resident observer does not mistake a wait cycle for a real uplink. The
uplink tailer hashes DevEUI and gateway IDs by default, redacts MQTT topic
identity segments unless `--include-device-identifiers` is explicitly used,
does not embed raw payload data, and does not publish MQTT, transmit RF, join,
send uplinks, downlink, or call `/safety/*`.

Current 2026-07-06 bench state: after a bounded AS923_2 / Taiwan `920-925 MHz`
RF window, the passive uplink JSONL contains two application uplink records.
The resident `sx1303-gateway` observer reports
`decision=gateway_receiving_uplinks`,
`answerability=gateway_uplink_evidence_available`, and
`uplink_count=2`. OLED shows `SCOUT LORA GW / UPLINK OK / UL 2 / NO RF TX`.
The resident observer did not start packet-forwarder, did not edit config, and
kept `rf_tx_allowed=false`, `lorawan_uplink_allowed=false`,
`downlink_allowed=false`, and `safety_api_called=false`.

Region checking is intentionally stricter than a port check. The observer scans
the mounted ChirpStack Docker configuration under
`/data/scout/providers/lora/chirpstack-docker/configuration/`, parses
`enabled_regions`, and flags forbidden plans such as `EU868` or `US915` even
when MQTT, Basic Station, and REST ports are open. `frequency_min` /
`frequency_max` guardrail bounds are recorded separately from actual channel
frequencies so the upstream AS923_2 templates can be reviewed without
misclassifying legal `920-925 MHz` channels.

Boundary fields:

```text
read_only=true
packet_forwarder_started=false
gateway_config_changed=false
rf_tx_allowed=false
downlink_allowed=false
join_allowed=false
lorawan_uplink_allowed=false
remote_outbound_allowed=false
phase1_safety_decision_change_allowed=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
phase2_brain_writeback=false
outbound_send_performed=false
hardware_control_scope=diagnostic_gateway_health_only
```

## Observer: `lorawan-client`

Purpose:

- Keep a resident, read-only evidence observer for the Wio-E5 / LoRa-E5
  LoRaWAN client path.
- Summarize key sync, profile provision, trial plan, Join-only RF trial, join
  audit, join-state diagnostic, passive uplink, and MQTT tail status JSONL.
- Distinguish `ready_for_join_only`, `join_confirmed_waiting_for_uplink`,
  `stale_join_state_suspected`, `join_rejected`, and `uplink_observed` without
  opening the serial port or transmitting RF.
- Provide bounded OLED / LED Bar feedback for local bench diagnosis.

Default resident paths:

```text
evidence dir:                  /data/scout/admin/ingress/lorawan_client
log file:                      /data/scout/admin/ingress/lorawan-client-observer.log
status file:                   /data/scout/admin/ingress/lorawan_client/lorawan_client_observer_status.json
samples file:                  /data/scout/admin/ingress/lorawan_client/lorawan_client_observer_samples.jsonl
key sync source:               /data/scout/providers/lora/wio-e5-chirpstack-key-sync.jsonl
profile provision source:      /data/scout/providers/lora/wio-e5-chirpstack-profile-provision.jsonl
trial plan source:             /data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl
RF trial source:               /data/scout/providers/lora/wio-e5-rf-trial.jsonl
join audit source:             /data/scout/providers/lora/wio-e5-chirpstack-join-audit.jsonl
join-state diagnostic source:  /data/scout/providers/lora/wio-e5-chirpstack-join-state-diagnostic.jsonl
uplink source:                 /data/scout/providers/lora/sx1303-gateway-uplink.jsonl
tail status source:            /data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl
Wio AT source:                 /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl
```

Key env:

```text
SCOUT_LORAWAN_CLIENT_AUTOSTART=true
SCOUT_LORAWAN_CLIENT_EVIDENCE_DIR=/data/scout/admin/ingress/lorawan_client
SCOUT_LORAWAN_CLIENT_RF_TRIAL_JSONL=/data/scout/providers/lora/wio-e5-rf-trial.jsonl
SCOUT_LORAWAN_CLIENT_JOIN_STATE_DIAGNOSTIC_JSONL=/data/scout/providers/lora/wio-e5-chirpstack-join-state-diagnostic.jsonl
SCOUT_LORAWAN_CLIENT_UPLINK_JSONL=/data/scout/providers/lora/sx1303-gateway-uplink.jsonl
SCOUT_LORAWAN_CLIENT_TAIL_STATUS_JSONL=/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl
```

Local feedback:

- OLED is optional and enabled when `SCOUT_LORAWAN_CLIENT_OLED_STATUS=true`.
- OLED heading is `SCOUT LORA CL`.
- OLED state lines include `JOIN OK`, `JOIN STALE`, `JOIN REJECT`,
  `JOIN FAIL`, `READY JOIN`, `PLAN WAIT`, or `UPLINK OK`.
- LED Bar is optional and enabled when `SCOUT_LORAWAN_CLIENT_LED_STATUS=true`.
- Default LED Bar port is `D5`, using `GPIO5` data and `GPIO6` clock.
- Ready / Join-only success / uplink evidence blinks LED9.
- Missing or incomplete evidence blinks LED1.
- Join rejection or stale join state blinks LED10.

Boundary notes:

`lorawan-client` is not the Wio-E5 RF executor. It does not run `AT+JOIN`, send
`AT+MSG`, open `/dev/ttyUSB0`, update ChirpStack, clear DevNonce/session state,
publish MQTT, send downlink, or call `/safety/*`. It reads evidence already
written by manual tools and exposes the current LoRaWAN client path status for
admin/debug surfaces.

Current 2026-07-06 bench state:

- `lorawan-client` is resident and running in `scout-pi-phase4-admin`.
- After explicit key sync, profile alignment, and an approved
  ChirpStack join-state reset, a Join-only RF trial succeeded with
  `rf_trial_join_confirmed_no_uplink`.
- A later approved single-uplink trial sent `AT+MSG="SCOUT"` with
  `--skip-join`; the Wio-E5 RF trial recorded
  `rf_trial_status=rf_trial_uplink_command_sent`,
  `rf_tx_executed=true`, and `lorawan_uplink_executed=true`.
- The passive MQTT tail recorded `tail_status=uplink_observed`,
  `tail_observed_uplink_count=1`, `raw_topic_embedded=false`, and a redacted
  topic shape `application/<redacted>/device/<redacted>/event/up`.
- The resident observer reports `decision=uplink_observed`,
  `answerability=client_uplink_evidence_available`,
  `join_audit_decision=uplink_observed`, and `uplink_record_count=2`.
- The older join-state diagnostic JSONL still contains
  `stale_join_state_suspected`, but current RF/uplink evidence has superseded
  that historical diagnostic. The resident observer remains read-only and must
  not clear DevNonce/session state or retry Join/uplink on its own.

Manual recovery sequence when the latest evidence is still stale or rejected:

If the latest answerability remains
`chirpstack_join_state_repair_required_before_retry`, treat it as an operator
repair workflow, not an observer action:

1. Run `tools/pi_wio_e5_chirpstack_join_state_reset.py` with `--execute` and
   the exact operator approval token
   `I_ACCEPT_CHIRPSTACK_JOIN_STATE_RESET_AS923_2`.
2. Run `tools/pi_wio_e5_lorawan_rf_trial.py --join-only` with the already
   approved AS923_2 Taiwan RF scope.
3. Only if Join is confirmed, run the single-uplink trial tool.
4. Re-check `/health.ingress_observers`, `lorawan_client_observer_status.json`,
   and `sx1303_gateway_observer_status.json`.

The join-state reset helper is packaged in the admin image for operator use,
but it is not a resident observer and must not be autostarted. Its allowed
write scope is limited to ChirpStack join/session state repair for the named
device after explicit approval. It must not change raw keys, device identity,
device profile, application, gateway, RF plan, downlink rules, or safety
state.

Boundary fields:

```text
read_only=true
serial_opened=false
rf_tx_allowed=false
rf_tx_executed=false
join_allowed=false
join_executed=false
lorawan_uplink_allowed=false
lorawan_uplink_executed=false
downlink_allowed=false
chirpstack_config_changed=false
device_registry_changed=false
postgres_write_performed=false
raw_device_identity_exposed=false
raw_key_exposed=false
remote_outbound_allowed=false
phase1_safety_decision_change_allowed=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
outbound_send_performed=false
hardware_control_scope=lorawan_client_evidence_observer_only
```

Join-state reset helper boundary fields:

```text
read_only=false only when --execute and exact approval token are both present
operator_approval_required=true
operator_approval_token_stored=false
device_session_cleared=true only after approved execution
dev_nonces_cleared=true only after approved execution
join_nonce_reset=true only after approved execution
device_identity_changed=false
device_keys_changed=false
device_registry_changed=false
chirpstack_config_changed=false
raw_device_identity_exposed=false
raw_key_exposed=false
rf_tx_allowed=false
rf_tx_executed=false
join_executed=false
lorawan_uplink_executed=false
downlink_allowed=false
phase1_safety_decision_change_allowed=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
```

## Observer: `physiologic-gate`

Purpose:

- Read sanitized SensorLogger vitals records produced by `sensorlogger-mqtt`.
- Assemble 15-minute physiologic windows to reduce noisy heart-rate, pace, and
  work-output samples.
- Run the deterministic Scout physiologic gate from those windows.
- Write a `SafetyGateEvent` candidate and a reducer dry-run artifact for the
  future Safety Arbiter / State Reducer.

Default resident paths:

```text
vitals source: /data/scout/admin/ingress/sensorlogger_mqtt/sensorlogger_mqtt_sensor_vitals_records.jsonl
evidence dir:  /data/scout/admin/ingress/physiologic_gate
log file:      /data/scout/admin/ingress/physiologic-gate-observer.log
status file:   /data/scout/admin/ingress/physiologic_gate/physiologic_gate_status.json
event file:    /data/scout/admin/ingress/physiologic_gate/physiologic_safety_gate_event.json
dry-run file:  /data/scout/admin/ingress/physiologic_gate/physiologic_reducer_dry_run.json
```

Key env:

```text
SCOUT_PHYSIOLOGIC_GATE_AUTOSTART=true
SCOUT_PHYSIOLOGIC_GATE_SENSORLOGGER_VITALS_JSONL=...
SCOUT_PHYSIOLOGIC_GATE_BASELINE_JSON=...
SCOUT_PHYSIOLOGIC_GATE_ROUTE_CONTEXT_JSON=...
SCOUT_PHYSIOLOGIC_GATE_WINDOW_MINUTES=15
SCOUT_PHYSIOLOGIC_GATE_POLL_SECONDS=30.0
```

Boundary fields:

```text
medical_diagnosis=false
runtime_safety_truth=false
phase1_runtime_safety_truth=false
phase1_l0_l4_state_mutated=false
safety_api_called=false
outbound_send_performed=false
raw_health_payload_shared=false
raw_track_shared=false
exact_timestamps_shared=false
```

Reducer contract:

- `physiologic_safety_gate_event.json` is a candidate event, not the final
  safety state.
- `physiologic_reducer_dry_run.json` describes what the reducer would consider
  from the physiologic gate alone.
- A future reducer must combine it with Pace, Delay, Weather, Darkness, and
  Environment Threat gates before changing L0-L4.

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
| Wio-E5 / LoRa-E5 serial writer/RF executor | USB serial AT smoke tooling, Join-only RF trial, and single uplink RF executor exist as manual tools | Serial access and RF join/uplink commands are not resident; only `lorawan-client` evidence observation is resident | Keep RF execution behind explicit operator approval; do not promote serial/RF writers into resident observer lifecycle |
| Future LoRaWAN sender / transport service | Planned future `scout_lorawan_sender.py` action path for approved local command candidates | It is not a resident observer; it may transmit RF only after explicit operator confirmation, legal AS923_2/TW validation, rate limiting, and bounded payload checks | Integrate the primary sender/action lane into `MQTT / Observer Message`; keep `Safety / Emergency` as emergency summary/link-out and `Debug Message` as read-only mirror |
| ChirpStack join-state reset helper | Manual operator-approved reset tool exists for stale OTAA Join/session repair | It performs bounded PostgreSQL writes only after an exact approval token; it is not an observer and must not run continuously | Keep as a manual repair tool; never autostart; require evidence JSONL, approval token, dry-run first, and post-reset Join-only validation |
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
tail -n 80 /data/scout/admin/ingress/sx1303-gateway-observer.log
tail -n 80 /data/scout/admin/ingress/physiologic-gate-observer.log
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
