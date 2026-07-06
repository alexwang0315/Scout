# Spec: Scout LoRa / LoRaWAN / SX1303 Gateway Direction

Date: 2026-05-29

Status: Mainline planning spec for Scout communication and search-and-rescue
coverage. Implementation remains staged behind diagnostic tools and provider
contracts.

## Objective

Scout 的核心產品語句是：

```text
Scout reduces the blank after disconnection.
Scout 減少失聯後的空白。
```

LoRa, LoRaWAN, and an SX1303 gateway move Scout from a pure safety black box
toward a field communication and location evidence layer:

- accident early warning;
- search-and-rescue area reduction;
- disconnected evidence preservation;
- team status continuity when phones, cellular, or cloud access disappear;
- "adventure journeys should not leave blank space" as an explicit product
  constraint.

This document makes LoRa / LoRaWAN / SX1303 a Scout mainline planning track,
but not a direct Phase 1 safety-decision input.

## Product Position

Scout remains a deterministic field-runtime first. Radio hardware may produce
evidence, diagnostics, and communication attempts, but it must not directly
change L0-L4 safety levels.

The correct product framing is:

```text
Scout black box records what happened.
Scout LoRa reduces the unknown area before and after the incident.
Scout gateway preserves last-heard evidence when the person stops reporting.
```

This is valuable in the failure mode Scout cares about most: someone slips,
falls into a creek valley, loses phone coverage, becomes immobile, and nobody
knows where to start looking.

## Protocol Distinctions

### LoRa

LoRa is the long-range, low-power radio physical layer. It is useful for small
packets: status, location, telemetry, check-ins, route progress, and emergency
intent.

Scout use:

- low-rate team beacons;
- local radio evidence;
- off-grid text/status style messages;
- signal metadata such as RSSI and SNR.

### LoRaWAN

LoRaWAN is a network protocol on top of LoRa. It typically uses:

- end devices;
- gateways;
- a network server;
- application server routing;
- device identity, activation, session keys, uplink/downlink policy.

Scout use:

- a leader/camp/vehicle Pi 5 with SX1303 gateway as the local gateway;
- team member devices as LoRaWAN clients;
- local or remote ChirpStack / TTS style network-server experiments;
- append-only gateway uplink evidence before any safety integration.

### Meshtastic

Meshtastic is a peer-to-peer LoRa mesh ecosystem, not LoRaWAN. It is useful as
community evidence, design inspiration, and a possible companion integration,
but it is not the same protocol as an SX1303 LoRaWAN gateway.

Scout use:

- learn from open community mesh deployment patterns;
- evaluate Meshtastic nodes as separate companion devices;
- build optional Scout skills that can read Meshtastic CLI/API outputs later;
- avoid assuming SX1303 gateway HATs are Meshtastic nodes.

## Taiwan Radio Boundary

Current Scout planning for Taiwan must treat `920-925 MHz` as the legal
low-power IoT target band until a later compliance review says otherwise.

Implementation rules:

- Do not use broad US915 channel plans in the field.
- Treat "915M" hardware as band-capable hardware, not as an approved channel
  plan.
- Configure LoRaWAN for a Taiwan-compatible AS923 plan before any RF transmit.
- Alpha ChirpStack tests use an `AS923_2`-only profile unless a later compliance
  review replaces it.
- Do not run `AT+TEST`, continuous TX, uplink, join, or packet-forwarder TX
  during early diagnostic slices.
- Keep a config validator that rejects frequencies outside `920000000` to
  `925000000` for Taiwan field tests.

### Alpha AS923_2 ChirpStack Profile

Current Pi alpha bench profile:

```text
stack root: /data/scout/providers/lora/chirpstack-docker
ChirpStack enabled_regions=["as923_2"]
UDP bridge MQTT topic prefix: as923_2
Basic Station bridge config: chirpstack-gateway-bridge-basicstation-as923_2.toml
ChirpStack region config: region_as923_2.toml
```

The stack must not leave the upstream example regions enabled for Scout field
tests. In particular, `EU868`, `US915`, `AU915`, `CN470`, `KR920`, `IN865`, and
`RU864` must be absent from active `enabled_regions` before any RF test. The
resident `sx1303-gateway` observer may report
`gateway_control_plane_reachable_rf_unknown` while the control plane is healthy
but no SX1303 RF receive evidence has been observed yet.

Useful references:

- NCC low-power radio technical rule lists other IoT equipment at
  `920 MHz-925 MHz`:
  https://ncclaw.ncc.gov.tw/FLAW/reFormatFLAWDAT08.aspx?id=FL012846
- The Things Network lists Taiwan under AS923-925 / AS2 and shows uplink
  channels from `923.2` through `924.8 MHz`:
  https://www.thethingsnetwork.org/docs/lorawan/frequency-plans/
- Taiwan Meshtastic community material suggests selecting region `TW`
  at `923.875 MHz` for Meshtastic devices:
  https://meshtw.github.io/guide/what-is-lora/

## Hardware Direction

### Scout Leader / Base Node

Alpha hardware shape:

```text
Raspberry Pi 5
external SSD as /data/scout
Docker Scout field runtime
OLED + LED Bar diagnostics
keypad development control surface
SX1303 915M LoRaWAN Gateway HAT as separate gateway bring-up track
```

Role:

- run Scout core field-runtime;
- preserve local mission evidence;
- operate as team leader / camp / vehicle gateway;
- collect gateway packet metadata;
- provide local admin API to Mac/PC;
- show radio diagnostics on OLED and LED Bar.

### SX1303 Gateway HAT

Expected role:

- LoRaWAN concentrator for multi-channel gateway reception;
- packet forwarder host on Pi;
- gateway EUI and status evidence producer;
- RSSI/SNR/timestamp metadata source;
- future fine-timestamp source for multi-gateway geolocation.

Important constraints:

- The HAT needs direct Pi 40-pin integration and may conflict with the Grove
  HAT bench layout. Treat it as a separate bring-up configuration.
- Enable SPI and I2C before gateway tests.
- Use external antennas suitable for Taiwan-compatible `920-925 MHz` channels.
- Do not hot-plug 40-pin HAT hardware.
- Keep RF transmit disabled until config and legal boundary checks exist.

### Team Client Nodes

Candidate client forms:

- Wio-E5 / LoRa-E5 development node for AT command and LoRaWAN client tests;
- GPS-capable LoRaWAN tracker;
- Meshtastic tracker as a separate mesh companion;
- phone or wearable bridge in alpha when dedicated client hardware is not
  ready.

Client message should be tiny and boring:

```text
mission_id hash
node_id pseudonym
sequence
client_time
GNSS lat/lon/accuracy if available
battery level
motion state
route/checkpoint hint
emergency intent flag if explicitly triggered
```

## SX1303 Geolocation Reality Check

SX1303 is important because it adds fine timestamp support. That matters for
TDOA, or time-difference-of-arrival, geolocation.

Scout must not oversell this:

- A single SX1303 gateway does not give reliable GPS-free location.
- TDOA geolocation needs multiple gateways, typically at least three gateways
  receiving the same uplink.
- Fine timestamp also needs correct gateway time discipline, generally through
  GPS/PPS or an equivalent precise timing source.
- With one gateway, Scout can still record last-heard time, gateway location,
  RSSI, SNR, frequency, spreading factor, and packet metadata. That is already
  useful for reducing the blank, but it is not triangulation.

Mainline implication:

```text
One gateway: last-heard evidence and local coverage test.
Two gateways: corridor and comparative signal hints, still not robust TDOA.
Three or more fine-timestamp gateways: real TDOA experiment candidate.
```

Useful references:

- Semtech SX1303 Corecell fine timestamp reference design:
  https://www.semtech.com/products/wireless-rf/lora-core/sx1303ctsxxxgw1
- ChirpStack geolocation notes require gateway fine timestamp for TDOA:
  https://www.chirpstack.io/docs/chirpstack/features/geolocation.html
- RAK developer discussion notes GPS/PPS and at least three gateways for TDOA:
  https://forum.rakwireless.com/t/fine-timestamping-with-sx1303/11695
- Waveshare wiki states SX1303 supports fine timestamp and TDOA-style network
  positioning, while SX1302 does not:
  https://www.waveshare.net/wiki/SX1302_LoRaWAN_Gateway_HAT

## Scout Architecture

```text
                       Mac / PC admin workstation
                   pre-trip, post-replay, debug UI
                                 |
                                 | HTTPS / local admin API
                                 v
+------------------------------------------------------------------+
| Scout Pi 5 leader/base node                                      |
|                                                                  |
|  +--------------------+      +-------------------------------+   |
|  | Scout runtime       |      | LoRa gateway evidence tools    |   |
|  | - safety core       |      | - SX1303 HAL / packet fwd      |   |
|  | - incident store    |      | - packet logger                |   |
|  | - provider status   |      | - AS923/TW config validator    |   |
|  +----------+---------+      +---------------+---------------+   |
|             |                                |                   |
|             | append-only evidence JSONL     | SPI/I2C/UART      |
|             v                                v                   |
|  /data/scout/providers/lora/          SX1303 915M Gateway HAT     |
|  /data/scout/incidents/                       |                   |
|                                               | LoRa RF           |
|  OLED / LED diagnostic feedback               v                   |
+------------------------------------------------------------------+
                         ^                 ^                 ^
                         |                 |                 |
                  LoRaWAN client    LoRaWAN client    Meshtastic or
                  team member       tracker / tag      future bridge
```

The gateway evidence tools are outside the Phase 1 safety runtime until a
separate provider contract is implemented and tested.

## Evidence Contract

Early gateway payloads should be append-only JSONL:

```json
{
  "captured_at": "2026-05-29T00:00:00Z",
  "source": "pi_sx1303_gateway_smoke",
  "hardware_kind": "sx1303_lorawan_gateway_hat",
  "region_profile": "AS923_TW_920_925",
  "gateway_eui": "0000000000000000",
  "chip_version": "0x12",
  "rf_receive_path_checked": true,
  "rf_read_scope": "spi_chip_id_only",
  "gateway_location_source": "manual_or_gnss",
  "rf_tx_allowed": false,
  "packet_forwarder_started": false,
  "uplink_count": 0,
  "frequency_plan_checked": true,
  "phase1_safety_decision_change_allowed": false,
  "remote_outbound_allowed": false,
  "hardware_control_scope": "diagnostic_gateway_evidence_only"
}
```

Later uplink payloads may add:

- `node_id_pseudonym`;
- `dev_eui_hash`;
- `fcnt`;
- `frequency_hz`;
- `spreading_factor`;
- `bandwidth_hz`;
- `rssi_dbm`;
- `snr_db`;
- `gateway_rx_time`;
- `fine_timestamp_available`;
- `fine_timestamp_encrypted`;
- `client_gnss`;
- `client_battery`;
- `client_emergency_intent`;
- `duplicate_gateway_count`.

Forbidden in early slices:

- no live `/safety/*` mutation;
- no automatic L0-L4 change;
- no SOS/outbound send;
- no remote LoRaWAN join/uplink unless the slice explicitly enables it;
- no public broadcast of exact participant location outside mission policy.

## Gateway GPS / NMEA Boundary

SX1303 does not itself produce NMEA. In the Waveshare SX1302/SX1303 Gateway
HAT design, NMEA is expected from the HAT-side L76K GNSS module over UART,
while SX1303 provides LoRa gateway baseband processing and fine timestamp
capability. Scout should therefore treat gateway GPS as a separate UART
diagnostic path:

```bash
python3 tools/pi_sx1303_gateway_gps_nmea_smoke.py \
  --ports /dev/serial0,/dev/ttyAMA0,/dev/ttyAMA10,/dev/ttyS0 \
  --baud-rates 9600,38400,57600,115200 \
  --duration-seconds 4 \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl
```

The smoke status is intentionally conservative:

- `nmea_ok`: at least one valid NMEA checksum was captured;
- `nmea_without_valid_checksum`: NMEA-like frames exist but are not yet trusted;
- `bad_stream`: bytes arrived, but not as parseable NMEA;
- `no_stream`: no bytes were seen on that UART/baud;
- `missing_device`: the UART path does not exist.

Only `nmea_ok` may suggest a `gps_tty_path` update for packet forwarder config.
Even then, gateway GNSS is still provider evidence and timing/location context,
not a direct safety-level mutation source. The tool fixes
`packet_forwarder_started=false`, `rf_tx_allowed=false`,
`lorawan_uplink_allowed=false`, `phase1_safety_decision_change_allowed=false`,
`remote_outbound_allowed=false`, and
`hardware_control_scope=diagnostic_gateway_gnss_uart_only`.

Scout GNSS hardware observer should consume both gateway and direct GPS evidence
without opening the UART itself:

```bash
python3 scout_gnss_hardware_observer.py \
  --gateway-jsonl /data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl \
  --grove-jsonl /data/scout/providers/gnss/manual-smoke.jsonl \
  --evidence-dir /data/scout/admin/ingress/gnss_hardware \
  --print-ready
```

This observer listens to JSONL evidence produced by the SX1303 gateway GPS smoke
and the Grove GPS module smoke, selects the latest valid fix candidate, and
writes `live_navigation_snapshot.json` plus
`gnss_hardware_observer_status.json`. It must remain evidence-only:
`live_hardware_read_performed=false`, `runtime_safety_truth=false`,
`phase1_l0_l4_state_mutated=false`, `safety_api_called=false`,
`rf_tx_allowed=false`, and `lorawan_uplink_allowed=false`.

## Capability Layers

### Alpha: Diagnostic Radio Evidence

Alpha scope:

- keep Wio-E5 AT smoke read-only;
- detect SX1303 HAT;
- read gateway EUI;
- validate AS923/TW frequency config;
- run local packet logger with RF TX blocked;
- show gateway status on OLED and LED Bar;
- write JSONL under `/data/scout/providers/lora/`.

Outcome:

- prove Scout can see radio hardware;
- prove the Pi can host the gateway stack;
- prove diagnostics are repeatable.

### Alpha Plus: One Client, One Gateway

Scope:

- one legal, configured LoRaWAN client sends a tiny check-in;
- Scout records last-heard evidence;
- OLED shows `LORA RX`;
- LED Bar uses the radio diagnostic bit;
- no safety mutation.

Outcome:

- prove team member beacon path;
- observe range, RSSI, SNR, and packet loss;
- compare phone GPS / Scout GNSS / LoRa metadata.

### Alpha Plus Guard: Operator-Approved Uplink Trial Plan

Before the first real Wio-E5 / LoRa-E5 client uplink, Scout must produce an
auditable local trial plan:

```bash
python3 tools/pi_wio_e5_lorawan_uplink_trial_plan.py \
  --wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl \
  --gateway-rx-jsonl /data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl \
  --uplink-jsonl /data/scout/providers/lora/sx1303-gateway-uplink.jsonl \
  --frequency-hz 923200000 \
  --region-profile AS923_2 \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl
```

這個 planning slice 只讀既有 evidence：Wio-E5 read-only AT smoke、SX1303 RX
readiness、以及目前 passive uplink JSONL。它不開 serial、不送 `AT+JOIN`、不送
`AT+MSG`、不做 downlink、不發射 RF，也不接 `/safety/*`。若 Wio-E5 DevEUI 不是
non-zero、gateway RX stack 未 ready，或 operator 尚未輸入明確 approval phrase，
狀態必須停在 `blocked_missing_readiness` 或 `waiting_for_operator_approval`。

唯一可被記錄的人工批准字串是
`I_ACCEPT_RF_TX_AS923_2_TW_920_925`，而且工具只記錄
`operator_approval_recorded=true`，不可把 approval token 原文寫入 JSONL。即使 plan
進入 `ready_for_manual_uplink_trial`，`rf_tx_allowed=false`、
`lorawan_uplink_allowed=false`、`rf_tx_executed=false`、
`lorawan_uplink_executed=false` 仍然固定；真正的 client uplink 必須在另一個明確、
人工觸發、可審計的 RF trial step 執行。

### Alpha Plus RF Trial Executor

真正的第一筆 Wio-E5 client uplink 只能透過雙閘門執行，且必須先通過
Join-only RF check：

```bash
python3 tools/pi_wio_e5_lorawan_rf_trial.py \
  --plan-jsonl /data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl \
  --port /dev/ttyUSB0 \
  --frequency-hz 923200000 \
  --region-profile AS923_2 \
  --operator-approval-token I_ACCEPT_RF_TX_AS923_2_TW_920_925 \
  --execute-rf-tx \
  --join-only \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/wio-e5-rf-trial.jsonl
```

Only after Join-only evidence reports `rf_trial_join_confirmed_no_uplink` may
Scout run the single uplink trial:

```bash
python3 tools/pi_wio_e5_lorawan_rf_trial.py \
  --plan-jsonl /data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl \
  --port /dev/ttyUSB0 \
  --frequency-hz 923200000 \
  --region-profile AS923_2 \
  --payload-text SCOUT \
  --operator-approval-token I_ACCEPT_RF_TX_AS923_2_TW_920_925 \
  --execute-rf-tx \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/wio-e5-rf-trial.jsonl
```

The executor must refuse RF unless all of these are true:

- latest trial plan status is `ready_for_manual_uplink_trial`;
- latest trial plan has `operator_approval_recorded=true`;
- frequency and region match the ready plan;
- approval token equals `I_ACCEPT_RF_TX_AS923_2_TW_920_925`;
- `--execute-rf-tx` is present;
- `--dry-run` is not present.

When those checks pass, the executor may send a bounded Join-only sequence:
`AT` and `AT+JOIN` when `--join-only` is present. Join-only success must report
`rf_trial_join_confirmed_no_uplink` and keep
`lorawan_uplink_executed=false`. The full uplink trial may then send exactly
one bounded sequence: `AT`, `AT+JOIN`, and `AT+MSG="SCOUT"` by default. If join
is not confirmed, the executor stops before `AT+MSG` unless the operator
explicitly sets `--continue-after-join-failure`. `--skip-join` is allowed only
for a module that is already known to be joined and cannot be combined with
`--join-only`. This executor does not configure AppKey, DevEUI, AppEUI,
channel masks, or network-server state; those remain separate provisioning
tasks.

RF execution evidence must set truthfully:

- `rf_tx_allowed=true` only after both gates pass;
- `rf_tx_executed=true` only after an RF AT command is attempted;
- `join_executed=true` only after `AT+JOIN` is attempted;
- `lorawan_uplink_executed=true` only after `AT+MSG` is attempted.

It must still keep `phase1_safety_decision_change_allowed=false`,
`phase1_l0_l4_state_mutated=false`, `safety_api_called=false`,
`downlink_allowed=false`, and `remote_outbound_allowed=false`.

### Alpha Plus Join Provisioning Audit

If the RF trial reports join failure or no application uplink, Scout should not
repeat RF blindly. The next step is a read-only provisioning audit:

```bash
python3 tools/pi_wio_e5_chirpstack_join_audit.py \
  --wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl \
  --rf-trial-jsonl /data/scout/providers/lora/wio-e5-rf-trial.jsonl \
  --uplink-jsonl /data/scout/providers/lora/sx1303-gateway-uplink.jsonl \
  --tail-status-jsonl /data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/wio-e5-chirpstack-join-audit.jsonl
```

The audit compares:

- Wio-E5 `AT+ID` identity evidence;
- latest non-dry-run RF trial result;
- passive SX1303 uplink JSONL and tail status;
- ChirpStack and gateway-bridge logs;
- optional read-only Postgres device table lookup.

It may classify failures as `client_dev_eui_not_registered_in_chirpstack`,
`client_join_failed_no_gateway_join_hint`,
`client_join_failed_network_server_rejected`,
`client_join_failed_join_seen_check_keys_profile`, or `uplink_observed`.

The audit is not a provisioning writer. It must not create devices, modify
AppKey / JoinEUI / device profile, publish MQTT, send RF, perform downlink, or
call `/safety/*`. DevEUI and AppEUI are hashed; raw log lines and raw device
identifiers are not persisted. Boundary fields remain
`rf_tx_allowed=false`, `lorawan_uplink_allowed=false`,
`chirpstack_config_changed=false`, `device_registry_changed=false`,
`postgres_write_performed=false`, and `safety_api_called=false`.

2026-07-06 Scout Pi bench finding:

- Without `lora_pkt_fwd` or LoRa Basics Station packet forwarder running, the
  gateway bridge and ChirpStack containers can be healthy while no RF join
  request reaches the network server.
- The existing `global_conf.scout-as9232-lns.spi.no-tx.json` profile starts the
  SX1303 concentrator in RX-only mode and sends UDP upstream to
  `127.0.0.1:1700`. In a controlled window it received one CRC-valid Wio-E5 RF
  packet and forwarded it upstream with zero RF downlink packets sent.
- The first controlled Join-only retry exposed two network-server issues rather
  than a receive-path failure: ChirpStack needed the bench channels used by the
  Wio-E5, and an RX-only packet-forwarder cannot deliver the JoinAccept
  downlink.
- The live Pi ChirpStack `region_as923_2.toml` was amended for this alpha bench
  with Taiwan-window channels `921.8`, `922.8`, `923.0`, `923.2`, and
  `923.4 MHz`, all inside `920-925 MHz`.
- A separate temporary packet-forwarder config,
  `global_conf.scout-as9232-lns.spi.join-tx.json`, enables radio 0 TX only for
  bounded AS923_2 / Taiwan `920-925 MHz` JoinAccept and MAC-command downlink
  tests. The original `no-tx` config remains the safer RX-only default.
- After explicit key sync, profile provisioning, and approved
  ChirpStack join-state reset, Join-only evidence reported
  `rf_trial_join_confirmed_no_uplink`; Wio-E5 returned `Network joined` and
  ChirpStack published the join event.
- A later approved single-uplink trial used `--skip-join` on the already joined
  Wio-E5 module and sent `AT+MSG="SCOUT"`. Evidence recorded
  `rf_trial_status=rf_trial_uplink_command_sent`,
  `rf_tx_executed=true`, and `lorawan_uplink_executed=true`.
- The passive MQTT tail observed a ChirpStack application uplink and wrote
  sanitized JSONL evidence with `raw_topic_embedded=false`, a redacted topic
  shape `application/<redacted>/device/<redacted>/event/up`, no raw payload
  embedding, and `tail_status=uplink_observed`.
- Current resident observer state is `sx1303-gateway:
  gateway_receiving_uplinks` and `lorawan-client: uplink_observed`. This is
  still evidence only: no Phase 1 safety state, SOS path, or remote outbound
  behavior is connected.

### Alpha Plus AS923_2 Profile Provisioning

When the read-only audit proves that the RF receive path works and the Wio-E5
device is registered but bound to the wrong ChirpStack region profile, Scout may
run one explicit provisioning mutation:

```bash
python3 tools/pi_wio_e5_chirpstack_as9232_profile_provision.py \
  --wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl \
  --allow-in-place-profile-update \
  --operator-approval-token I_ACCEPT_CHIRPSTACK_PROFILE_MUTATION_AS923_2 \
  --execute \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/wio-e5-chirpstack-profile-provision.jsonl
```

The tool is dry-run by default. It may write ChirpStack/Postgres only when both
`--execute` and `I_ACCEPT_CHIRPSTACK_PROFILE_MUTATION_AS923_2` are present. It
does not send RF, send downlinks, publish MQTT, change AppKey, change JoinEUI,
create devices, or call `/safety/*`.

Allowed mutation scopes:

- `device_profile_switch`: if an AS923_2 profile already exists, switch only the
  matching Wio-E5 device to that profile.
- `device_profile_in_place_update`: if no AS923_2 profile exists and the
  current profile is used by exactly one device, update that dedicated profile
  to `AS923_2` / `as923_2`.

Blocked conditions:

- Wio-E5 identity evidence is missing;
- device is not registered;
- JoinEUI/AppEUI does not match;
- device keys are missing;
- device is disabled;
- current profile is shared and no AS923_2 target profile exists;
- operator approval token is absent.

Provisioning evidence must record `postgres_write_performed`,
`chirpstack_config_changed`, `device_registry_changed`,
`profile_mutation_scope`, and `approval_token_stored=false`. It must keep
`rf_tx_allowed=false`, `lorawan_uplink_allowed=false`, `downlink_allowed=false`,
`safety_api_called=false`, and `phase1_safety_decision_change_allowed=false`.
Raw DevEUI, AppEUI, AppKey, and NwkKey values must not be persisted or printed.

### Alpha Plus Join-State Reset

When profile/key evidence is already aligned but Join-only still fails and
read-only diagnostics classify `stale_join_state_suspected`, Scout may reset
only ChirpStack join/session state:

```bash
python3 tools/pi_wio_e5_chirpstack_join_state_reset.py \
  --device-name scout-wio-e5-client \
  --output-jsonl /data/scout/providers/lora/wio-e5-chirpstack-join-state-reset.jsonl
```

The dry-run must show exactly one matching device and exactly one matching
device key before any mutation. The mutation requires explicit approval:

```bash
python3 tools/pi_wio_e5_chirpstack_join_state_reset.py \
  --device-name scout-wio-e5-client \
  --execute \
  --operator-approval-token I_ACCEPT_CHIRPSTACK_JOIN_STATE_RESET_AS923_2 \
  --output-jsonl /data/scout/providers/lora/wio-e5-chirpstack-join-state-reset.jsonl
```

This reset may clear only server-side `device_session`, `dev_addr`,
`secondary_dev_addr`, `f_cnt_up`, `dev_nonces`, and `join_nonce`. It must not
change DevEUI, JoinEUI/AppEUI, AppKey, NwkKey, device profile, application, or
gateway config. It must not open Wio-E5 serial, transmit RF, publish MQTT,
perform downlink, or call `/safety/*`. Evidence must record
`postgres_write_performed`, `device_session_cleared`, `dev_nonces_cleared`,
`join_nonce_reset`, and `approval_token_stored=false`; raw identities and raw
keys must not be persisted.

### Alpha Plus OTAA Key Sync

If the gateway receive path is good and the AS923_2 profile is aligned, but the
join still fails with a network-server rejection, the next controlled step is
OTAA root-key synchronization. This step is not an RF trial and does not run
`AT+JOIN`.

```bash
python3 tools/pi_wio_e5_chirpstack_key_sync.py \
  --wio-at-jsonl /data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl \
  --use-existing-chirpstack-key \
  --operator-approval-token I_ACCEPT_LORAWAN_KEY_SYNC_AS923_2 \
  --execute \
  --oled-status \
  --led-status \
  --output-jsonl /data/scout/providers/lora/wio-e5-chirpstack-key-sync.jsonl
```

Preferred field-recovery mode is `--use-existing-chirpstack-key`: read the
existing ChirpStack `nwk_key` / `app_key` and reapply it to the Wio-E5 APPKEY
through `AT+KEY=APPKEY,"..."`. The tool must redact the raw key from stdout,
JSONL, and OLED/LED status. It may record only `target_key_fingerprint`.

If a full reset is required, `--generate-key` or `--key-file` may be used to
create a new 16-byte root key and write it to both ChirpStack `device_keys` and
the Wio-E5 APPKEY. This requires `--execute` plus
`I_ACCEPT_LORAWAN_KEY_SYNC_AS923_2`.

Required boundaries:

- `rf_tx_allowed=false`;
- `join_executed=false`;
- `lorawan_uplink_allowed=false`;
- `downlink_allowed=false`;
- `mqtt_publish_performed=false`;
- `safety_api_called=false`;
- `phase1_safety_decision_change_allowed=false`;
- `root_key_printed=false`;
- `raw_key_embedded=false`;
- `operator_approval_token_stored=false`.

The tool must expose `serial_write_performed`, `wio_module_state_changed`,
`postgres_write_performed`, `device_keys_changed`, and `mutation_scope` so the
next join trial can be audited as a separate RF event.

### Beta: Local Network Server

Scope:

- local ChirpStack or equivalent LNS on Pi or base station;
- gateway bridge to local server;
- app payload decoder;
- mission-scoped device registry;
- replayable JSONL export into Scout evidence.

Outcome:

- Scout can operate without cloud LoRaWAN infrastructure during field tests;
- team check-ins can be replayed post-trip;
- communication loss becomes explicit evidence.

### SAR Experiment: Multi-Gateway Position Evidence

Scope:

- three or more SX1303/fine-timestamp gateways;
- known gateway coordinates;
- GPS/PPS verified;
- same client uplink heard by multiple gateways;
- TDOA or resolver experiment outside Phase 1 safety authority.

Outcome:

- estimate search corridor or area;
- preserve last-heard multi-gateway metadata;
- quantify whether "GPS-free" location is useful for Scout.

## Scout Features Enabled

### Last-Heard Timeline

For each participant:

- last packet time;
- last packet gateway;
- RSSI/SNR trend;
- last client GNSS if present;
- message sequence gap;
- battery trend;
- route/checkpoint hint.

Scout value:

- search starts from an evidence-backed last-known window, not a blank map.

### Missed Check-In Early Warning

Radio absence is not danger by itself. It is evidence that can strengthen a
concern when combined with route, GNSS, IMU, weather, time, and operator policy.

Scout value:

- detect widening communication gap before an incident becomes invisible.

### Team Leader Gateway

The Pi 5 leader node can act as:

- field-runtime server;
- local gateway;
- local storage vault;
- OLED/LED diagnostic console;
- admin workstation target.

Scout value:

- one person in the team carries the coordination node while client devices
  stay light.

### Trailhead / Vehicle / Camp Relay

Deployable gateway positions:

- trailhead;
- vehicle;
- camp;
- ridge high point;
- hut;
- drone/temporary mast in later SAR scenarios.

Scout value:

- create radio islands along a route and shrink the unknown area between them.

### Incident Evidence Package Extension

When Phase 1 creates or updates an incident package, later provider integration
can attach read-only radio evidence:

- last LoRaWAN uplinks;
- gateway status;
- packet loss window;
- last client GNSS;
- RSSI/SNR trend;
- gateway location and confidence;
- reason no radio evidence exists.

Scout value:

- post-incident review can see what communication channels existed or failed.

### Public / Community Mesh Awareness

Meshtastic and local community mesh deployments are not Scout infrastructure,
but they are useful context:

- public mesh density before a trip;
- known high-site relays;
- candidate local volunteers or community channels;
- field test comparison between Scout LoRaWAN and Meshtastic mesh behavior.

Scout value:

- pre-trip planning can understand radio context without depending on it.

## Community Cases and Ideas

These are inspiration sources. They are not automatically product
requirements.

| Source | Observed idea | Scout relevance |
| --- | --- | --- |
| MakerPRO Meshtastic emergency article | No power/no network communication, rooftop or high-site relays, disaster/outdoor positioning | Strong narrative match: "Scout fills the blank" after infrastructure loss |
| 臺灣鏈網 Meshtastic Taiwan Community | Taiwan TW region guidance, local support, mesh basics | Use as local frequency and community learning source |
| Meshtastic official docs | Low-cost off-grid mesh, phone clients, Python CLI/SDK, encrypted channels, hop metadata | Candidate Scout skill/CLI integration path for non-LoRaWAN mesh companion |
| Seeed Am Mellensee case | Solar Meshtastic nodes across all nine districts during a blackout drill | Model for pre-trip or community relay kits at trailhead/camp/ridge |
| AFRS Clinton County case | Solar emergency nodes, hospital node, weather/AMBER style alert bridge, message logging | Model for SAR/public-safety alert broadcast and reliability logging |
| Signal K boat integration | Boat telemetry, position history, alerts, waypoint commands over Meshtastic | Model for Scout telemetry commands and "where is teammate" style query |
| High Desert / regional mesh communities | Local volunteer networks and high-site node planning | Model for Scout community coverage map and route radio-readiness score |
| Single-channel gateway projects | Deprecated proof-of-concept gateways and Python ports | Learning only; not Scout production gateway direction |
| Lora-net `sx1302_hal` | Current SX1302/SX1303 HAL and packet forwarder foundation | Preferred starting point for SX1303 HAT bring-up |

Primary source links:

- https://makerpro.cc/2025/06/meshtastic-network-for-the-emergency/
- https://meshtw.github.io/guide/what-is-lora/
- https://meshtw.github.io/guide/what-is-mesh/
- https://meshtastic.org/
- https://meshtastic.org/docs/overview/
- https://www.seeedstudio.com/blog/2025/10/30/building-resilient-communication-germany-meshtastic-solar-nodes/
- https://www.afrs.us/post/afrs-us-local-partners-expand-community-safety-with-solar-powered-emergency-communication-nodes
- https://signalk.org/2025/signalk-meshtastic/
- https://hdmesh.org/
- https://github.com/tftelkamp/single_chan_pkt_fwd
- https://github.com/pointhi/lora_single_chan_gateway
- https://github.com/Lora-net/lora_gateway
- https://github.com/Lora-net/sx1302_hal

## Slice Plan

### Slice L0: Preserve Current Wio-E5 Diagnostic Boundary

Already started:

- USB serial AT smoke;
- OLED/LED status feedback;
- block join/uplink/test TX/config commands;
- write JSONL evidence.

Keep it as local AT diagnostic until a LoRaWAN join slice is explicitly
approved.

### Slice L1: SX1303 HAT Hardware Discovery

Goal:

- verify Pi sees the HAT without RF activity.

Tasks:

- power down before attaching the HAT;
- enable SPI and I2C;
- confirm expected I2C devices if the HAT exposes them;
- build or install `sx1302_hal` in an isolated tools directory;
- run `util_chip_id` or equivalent gateway EUI discovery;
- write `pi_sx1303_gateway_smoke.py` as a diagnostic wrapper;
- show `LORA GW OK` or `LORA GW FAIL` on OLED;
- light LED7 for radio diagnostic active and LED10 for failure.

Acceptance:

- gateway EUI or chip ID can be captured;
- JSONL payload has safety boundary fields fixed false;
- no packet forwarder TX;
- no LoRaWAN join/uplink;
- no `/safety/*` mutation.

Live Scout preflight result captured during the Alpha AS923_2 setup:

- `tools/pi_sx1303_gateway_smoke.py` is the repeatable diagnostic wrapper for
  this slice.
- The wrapper calls `sx1302_hal` `util_chip_id` against `/dev/spidev0.0` and
  appends `/data/scout/providers/lora/sx1303-gateway-smoke.jsonl`.
- On Scout Pi, `util_chip_id` returned concentrator EUI
  `0x0016c001f11f5f46`, chip version `0x12`, and temperature-sensor evidence.
- This proves SPI plus SX1303 concentrator access. It does not prove client
  uplink reception yet.
- The resident `sx1303-gateway` observer reads this JSONL via
  `SCOUT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL` and may report
  `gateway_rf_hardware_detected_no_uplink`.
- OLED status for this intermediate state is `RF OK NO UL`.

Next receive-side readiness slice:

- `tools/pi_sx1303_gateway_rx_smoke.py` passively inspects local Docker
  container status, TCP/UDP listening ports, and bounded gateway log summaries.
- It appends `/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl`.
- It does not run `AT+JOIN`, does not send a LoRaWAN uplink, does not transmit
  RF, does not start packet forwarders, and does not embed raw log lines by
  default.
- The resident `sx1303-gateway` observer reads this JSONL via
  `SCOUT_SX1303_GATEWAY_RX_READINESS_JSONL` and may report
  `gateway_rx_stack_ready_no_uplink`.
- OLED status for this intermediate state is `RX READY NO UL`.

Passive uplink evidence slice:

- `tools/pi_sx1303_gateway_uplink_mqtt_tail.py` passively subscribes to local
  ChirpStack MQTT uplink topics using `mosquitto_sub`.
- It appends structured records to
  `/data/scout/providers/lora/sx1303-gateway-uplink.jsonl` only when an uplink
  event is observed.
- No-uplink waits append only
  `/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl`, so the
  resident observer does not misclassify a wait as an uplink.
- DevEUI and gateway IDs are hashed by default. Raw payload data is not embedded
  by default; only `payload_bytes`, frequency, spreading factor, bandwidth,
  RSSI, SNR, and frame counters are retained.
- It does not publish MQTT, transmit RF, join a LoRaWAN network, send an uplink,
  send downlink, or call `/safety/*`.

### Slice L2: Taiwan Frequency Config Validator

Goal:

- prevent accidental non-Taiwan RF config.

Tasks:

- add a pure Python validator for `global_conf.json` / `test_conf.json`;
- require all configured uplink/downlink/test frequencies to be inside
  `920000000-925000000` for `AS923_TW_920_925`;
- reject US902-928 and EU868 examples for Taiwan bench/field profiles;
- document the chosen channel plan.

Acceptance:

- unit tests can validate sample configs without hardware;
- invalid `903.9 MHz`, `868.1 MHz`, or `925.1 MHz` configs fail clearly;
- validator runs before any packet forwarder smoke.

### Slice L3: Packet Forwarder Local Logger

Goal:

- observe gateway receive path without remote dependency.

Tasks:

- run packet forwarder against a local UDP logger or local ChirpStack bridge;
- capture gateway status and uplink metadata;
- convert metadata to Scout JSONL;
- keep remote outbound disabled unless the operator explicitly enables it.

Acceptance:

- gateway process starts;
- status JSON can be parsed;
- no client device required for first pass;
- OLED/LED reflects `GW RUN`, `GW OK`, or `GW FAIL`.

### Slice L4: One Legal Client Uplink

Goal:

- prove one team client check-in can be heard and preserved.

Tasks:

- configure one client for Taiwan-compatible AS923;
- perform LoRaWAN join only in an explicitly approved RF test;
- send one tiny check-in payload;
- log gateway metadata and decoded app payload;
- compare terminal, OLED, LED, and JSONL outputs.

Acceptance:

- one uplink is captured;
- no safety mutation;
- no incident package write;
- no remote SOS/outbound;
- evidence can be replayed from JSONL.

### Slice L5: Local LNS / ChirpStack Experiment

Goal:

- make Scout independent from public network infrastructure during field tests.

Tasks:

- evaluate ChirpStack on Pi or Mac/PC;
- register gateway and device;
- decode Scout check-in payload;
- persist normalized provider evidence;
- document power/CPU/memory impact.

Acceptance:

- local LNS works on a bench network;
- Pi load is acceptable or Mac/PC base station is chosen;
- provider evidence stays outside Phase 1 decisions.

### Slice L6: Multi-Gateway TDOA Research

Goal:

- test whether SX1303 fine timestamp can reduce search area without client
  GNSS.

Tasks:

- acquire or borrow at least three fine-timestamp-capable gateways;
- verify GPS/PPS timing;
- place gateways at known coordinates;
- capture the same uplink at multiple gateways;
- evaluate resolver options such as LoRa Cloud integration or open resolver
  experiments.

Acceptance:

- the experiment produces an error estimate, not just a map dot;
- results are compared against ground truth;
- Scout documents whether this is product-useful.

## Roadmap Decision

For alpha:

- prioritize Scout software runtime, OLED, LED, keypad, admin API, and
  repeatable hardware smoke;
- treat sensors as secondary because phone/wearable sources cover many alpha
  activity and health signals;
- make LoRa/SX1303 a communication and location evidence track, not a
  required safety runtime dependency.

For beta:

- add real team client nodes;
- add LoRaWAN gateway packet evidence;
- add local LNS or controlled network-server bridge;
- attach radio evidence to post-replay and incident packages.

For SAR-focused prototype:

- test multi-gateway fine timestamp;
- deploy ridge/trailhead/camp relays;
- quantify search-area reduction.

## Open Questions

- Which exact Taiwan LoRaWAN frequency profile should Scout standardize on for
  bench and field tests?
- Should the first client device be Wio-E5, a GPS-capable LoRaWAN tracker, or a
  Meshtastic tracker used through a separate skill?
- Can the Pi 5 host both Scout runtime and local ChirpStack without hurting
  deterministic runtime stability?
- How should Scout protect participant location privacy when public mesh or
  shared gateways are nearby?
- What is the minimum useful team check-in interval that does not congest the
  channel or drain batteries?
- How many gateways are realistic for a mountain team to deploy?
- Which field test route gives useful ridge/valley coverage data without
  creating legal or safety risk?

## Non-Goals

- Do not replace official emergency calls, satellite SOS, or rescue procedures.
- Do not treat LoRa reception as proof of safety.
- Do not treat lack of LoRa reception as proof of danger.
- Do not make SX1303 required for Phase 1 runtime.
- Do not let a radio provider directly mutate `/safety/*`.
- Do not transmit on unvalidated or illegal frequency plans.
- Do not expose exact user location to public channels by default.
