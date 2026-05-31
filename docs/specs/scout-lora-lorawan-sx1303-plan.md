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
- Do not run `AT+TEST`, continuous TX, uplink, join, or packet-forwarder TX
  during early diagnostic slices.
- Keep a config validator that rejects frequencies outside `920000000` to
  `925000000` for Taiwan field tests.

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
