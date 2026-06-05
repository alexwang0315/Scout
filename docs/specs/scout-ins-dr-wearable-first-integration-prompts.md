# Scout INS/DR Wearable-First Integration Prompts

Date: 2026-06-05

Use this prompt pack when integrating the current Scout INS/DR work with
wearable providers, pretrip map/corridor tooling, runtime/debug views,
cross-surface assistant answers, or future mobile clients.

Important architecture update:

- MQTT is not the application contract; it is one transport adapter.
- Scout must support transport-independent ingress from HTTP, WebSocket, TCP
  stream, Bluetooth/BLE, MQTT, LoRa/LoRaWAN, satellite message, and future
  channels.
- The application layer should consume normalized Scout Sensor/Vitals Records,
  not transport-specific MQTT payloads.
- INS/DR + GPS estimates may eventually feed Scout Ln safety decisions after a
  safety admission gate. Offline replay and raw ingress still must not mutate
  safety state directly.

Current conclusion:

- Default client assumption: at least 90% of clients do not own a Scout host.
- Default INS/DR source: watch or wearable PDR/IMU plus phone/watch location.
- Scout host IMU / Hiwonder / wheel odometry are optional high-fidelity
  enhancements, not required for the default client path.
- Recommended replay profile: `wearable_route_constrained`.
- Recommended implementation pattern: distribute cumulative wearable
  `pedometerDistance` over SensorLog cadence, do not treat uncalibrated watch
  heading/course as absolute heading, and re-anchor with reliable location.

Evidence snapshot from the Apple Watch 260512 samples:

- SensorLog/motion/accelerometer cadence: about 5 Hz.
- Location timestamp cadence: about 1 Hz.
- Positive pedometerDistance update interval: about 2.6 to 3.5 seconds.
- Sparse pedometer + direct course median DR error: 23.35 m.
- Wearable route-constrained profile median DR error: 6.88 m.
- Direct SensorLog course and lightly gated course both still produce many
  reverse-heading / Z-shape artifacts.
- `route_heading_oracle` is an upper-bound replay only; it is not independent
  sensor evidence.

Relevant local tools:

- `tools/ins_dr_sensorlog_replay.py`
- `tools/ins_dr_sensorlog_method_matrix.py`
- `tools/ins_dr_trajectory_compare_map.py`
- `ins_dr_navigation.py`
- `ins_dr_input_adapter.py`

Regenerate the latest method matrix:

```bash
python3 tools/ins_dr_sensorlog_method_matrix.py \
  --input 'pdrsample/stream Apple Watch 260512 08_52_37.json' \
  --input 'pdrsample/stream Apple Watch 260512 09_39_31.json' \
  --overpass-geojson tests/fixtures/maps/scout_260512_overpass_map_context.geojson \
  --output-dir /tmp/scout-ins-dr-method-matrix-20260531 \
  --pretty
```

## Global Integration Prompt

```text
You are integrating Scout INS/DR into another Scout feature. Treat the current
INS/DR default as wearable-first.

Default assumption:
- At least 90% of clients do not have a Scout host device.
- Their IMU/PDR source is a watch, phone, or wearable stream.
- Scout host IMU, Hiwonder IMU/GNSS, wheel odometry, and raw USB GNSS are
  optional enhancement paths, not default requirements.

Use this default profile:
- pdr_profile=wearable_route_constrained
- pdr_resolution_mode=distributed_sensorlog
- pdr_heading_policy=no_heading

Rationale:
- Apple Watch/SensorLog motion is about 5 Hz, location is about 1 Hz, and
  pedometerDistance updates are sparse.
- Distributing pedometerDistance over SensorLog cadence improves path
  resolution.
- Uncalibrated watch heading, motionYaw, and low-speed locationCourse must not
  be treated as reliable geodetic heading.
- Direct course heading can create reverse progress and Z-shaped route
  artifacts.

Evidence boundary:
- Offline Apple Watch/SensorLog replay is not live Scout GNSS proof.
- Raw Scout GNSS NMEA remains the live position/time authority for Scout-host
  field proof.
- Vendor fused outputs may be comparison evidence, but must not overwrite raw
  GNSS + DR estimates.
- Do not open Phase 1 safety mutation, live /safety/* writes, outbound sends,
  or hardware control unless explicitly requested and separately gated.

Required artifact fields:
- source_provider / source_path or raw_evidence_refs
- data_quality
- privacy
- boundary
- live_navigation_completion_proof=false unless live raw GNSS and movement
  evidence are actually captured
```

## Prompt: Transport-Independent Ingress Architecture

```text
Design Scout sensor ingress as a transport-independent stack.

Do not make MQTT the application layer. MQTT is only one adapter.

Layers:
1. Transport ingress
   - HTTP, WebSocket, TCP stream, Bluetooth/BLE, MQTT, LoRa/LoRaWAN,
     satellite message, and future transports.
   - Preserve raw bytes/messages, receive timestamp, payload hash, credential
     boundary, transport metadata, and parse status.
   - No route semantics and no safety decision.

2. Source adapter
   - Sensor Logger, Scout iOS, Scout Android, Garmin/Apple export, BLE
     peripheral, LoRa gateway, satellite check-in.
   - Converts source-specific payloads into normalized observations.

3. Scout Sensor/Vitals Record
   - Dedicated journey file/bundle, analogous in role to FIT but Scout-owned.
   - Stores location, PDR, IMU, battery, environment, life signs, provenance,
     data quality, and navigation estimates.
   - Can export GPX, KML, CSV, and admin HTML maps.

4. Navigation estimation
   - Consumes normalized location + PDR/IMU/wheel evidence.
   - Produces GPS-only track, INS/DR track, route-constrained track,
     confidence, uncertainty, degradation reasons, and re-anchor corrections.

5. Safety admission
   - Decides whether a navigation estimate can influence Ln.
   - Applies uncertainty, persistence, corridor overlap, map confidence,
     re-anchor freshness, and terrain-class policy.

6. Admin/export
   - Shows GPS-only and INS/DR tracks overlaid for precision comparison.
   - `trajectory_diff_map.html` is an admin view generated from record/export
     data, not the canonical data file.

Deliverables:
- Update or add transport-independent contracts.
- Keep raw transport evidence separate from normalized application records.
- Add tests proving MQTT/HTTP/BLE/LoRa style ingress can share the same
  normalized record path.
```

## Prompt: Wearable Provider / Mobile Stream Integration

```text
Integrate Scout INS/DR with the wearable provider/mobile stream layer.

Goal:
- Admit watch/phone PDR and location as a provider-neutral stream that can feed
  Scout route-constrained DR.
- Do not require Scout host hardware for the default path.

Input contract:
- timestamp_s or source timestamp
- cumulative pedometerDistance when available
- step count when distance is unavailable
- location lat/lon plus horizontal accuracy
- speed/course only as quality-gated metadata, not as mandatory heading
- optional motion/accelerometer/yaw fields marked as uncalibrated unless the
  provider supplies a valid geodetic heading contract

Default transformation:
- Convert reliable location samples into GNSS-like anchors for offline/mobile
  replay.
- Convert cumulative pedometerDistance into DeadReckoningDelta.
- Use distributed_sensorlog resolution when source cadence is higher than
  pedometer update cadence.
- Use no_heading for the default wearable client.
- If planned-route context exists, advance monotonically along the matched route
  between anchors.

Do not:
- Promote wearable provider values into Phase 1 safety truth.
- Send raw health payloads or private exact tracks outside local evidence
  storage.
- Treat Apple Watch motionYaw as absolute north-referenced heading without a
  calibration proof.
- Treat phone/watch location replay as proof that Scout's own GNSS module has a
  live fix.

Deliverables:
- Provider-neutral INS/DR input adapter or stream admission contract.
- Focused tests showing pedometerDistance -> DR delta, weak/no-good GPS + PDR
  coverage, and no Phase 1 mutation.
- A Scout Sensor/Vitals Record or replay report carrying
  data_quality/privacy/boundary fields.
```

## Prompt: Pretrip Route / Corridor / Map Integration

```text
Integrate wearable-first INS/DR with Scout pretrip route and map tooling.

Goal:
- Use pretrip route geometry as the route constraint for wearable PDR when GNSS
  is weak or unavailable.
- Display expected drift and no-good-GPS PDR coverage on the map without
  calling it live safety truth.

Rules:
- Treat route_heading_oracle as an upper-bound diagnostic only.
- Use wearable_route_constrained as the deployable default.
- A route-constrained estimate can support map display, corridor progress, ETA
  refinement, and replay diagnostics.
- It must not approve departure, mutate reviewed candidates, or open runtime
  handoff by itself.

Map layers:
- Reliable GPS/location anchor track.
- Weak/no-good GPS samples that still carry IMU/PDR.
- INS/DR route-constrained estimate.
- Top error connectors between estimate and time-aligned GPS.
- Overpass/OSM corridor context when available.

Deliverables:
- A map artifact or layer manifest that can load trajectory_diff_map.html style
  evidence.
- A concise method matrix summary attached to the pretrip project as advisory
  evidence.
- Tests that route-constrained PDR remains advisory and does not write runtime
  or safety state.
```

## Prompt: MQTT Sensor Stream To INS/DR Path Integration

```text
Integrate Sensor Logger MQTT ingress with Scout INS/DR path generation without
making MQTT the only application path.

Current Scout state:
- `scout_sensorlogger_mqtt_observer.py` already subscribes to MQTT, preserves
  raw messages in `sensorlogger_mqtt_raw.jsonl`, writes an ingress index, and
  summarizes device/session/message-id state.
- The observer is evidence-only and must stay separate from live safety
  mutation.
- `SafetyRuntimeSession` and `ins_dr_navigation.py` can already convert GNSS/PDR
  evidence into route-aligned INS/DR estimates.

Goal:
- Build an evidence bridge from accepted MQTT raw records to wearable-first
  Scout Sensor/Vitals Record and INS/DR replay.
- Generate a denser and more accurate journey path map from phone/watch
  location + PDR, especially through weak/no-good GPS gaps.

Recommended data flow:
1. MQTT observer captures raw Sensor Logger messages.
2. A new normalization/replay bridge reads accepted MQTT raw JSONL records.
3. The bridge extracts Sensor Logger readings:
   - location -> GNSS-like anchor when horizontal accuracy is acceptable
   - pedometerDistance or steps -> DeadReckoningDelta
   - accelerometer/gyro/yaw -> uncalibrated motion metadata unless a heading
     calibration contract exists
4. Run Scout INS/DR with pdr_profile=wearable_route_constrained.
5. Write a Scout Sensor/Vitals Record with normalized observations,
   GPS-only track, INS/DR track, and quality metadata.
6. Export GPX, KML, CSV, and an admin HTML trajectory comparison map when a GPS
   reference or route context exists.
7. Surface the resulting path as journey evidence in debug/pretrip maps.

Implementation boundary:
- Keep MQTT observer evidence-only; do not import SafetyRuntimeSession into the
  observer.
- The bridge may run as an offline/on-demand replay first.
- Runtime ingestion must remain opt-in and separately gated.
- Do not call `/safety/*`, mutate Phase 1 L0-L4, write Phase 2 Brain, or send
  outbound messages.
- Do not expose MQTT credentials or raw private payloads in map summaries.

Map output:
- Reliable phone/watch location anchors.
- Weak/no-good GPS samples that still carry PDR/IMU.
- Wearable route-constrained INS/DR path.
- GPS-only path overlaid against INS/DR path for accuracy comparison.
- Re-anchor correction markers and top error connectors when comparison truth
  is available.
- Source labels: `wan_mqtt`, `sensorlogger`, `wearable_route_constrained`.

First implementation slice:
- Add a parser that converts Sensor Logger MQTT raw payloads into the same
  normalized records accepted by `ins_dr_sensorlog_replay.py`.
- Add tests using `tests/test_scout_sensorlogger_mqtt_observer.py` style
  payloads for location + accelerometer + future Android-compatible shape.
- Add a CLI such as `tools/ins_dr_sensorlogger_mqtt_replay.py` that reads
  `sensorlogger_mqtt_raw.jsonl` and writes:
  - journey.scout-svr/
  - normalized_sensorlog.json
  - ins_dr_estimates.jsonl
  - mqtt_ins_dr_replay_report.json
  - GPX/KML/CSV exports
  - trajectory_diff_map.html for admin review
- Only after offline replay is proven, consider a runtime stream adapter.
```

## Prompt: Scout Sensor/Vitals Record And Export

```text
Define or extend the Scout Sensor/Vitals Record.

Goal:
- Create a Scout-owned journey sensor record, analogous in role to Garmin FIT,
  but shaped around Scout wilderness safety evidence.
- It must be exportable to GPX, KML, CSV, and admin HTML map views.

Preferred v0 bundle:

journey.scout-svr/
  manifest.json
  observations.jsonl
  navigation_estimates.jsonl
  vitals.jsonl
  transport_ingress_index.jsonl
  exports/
    journey.gpx
    journey.kml
    journey.csv
    sensor_samples.csv

Record requirements:
- Keep raw transport payloads and private credentials outside summaries.
- Preserve source_adapter, ingress_transport, payload_sha256, raw_evidence_refs,
  data_quality, privacy, and boundary fields.
- Store multiple tracks:
  - gps_only_track
  - ins_dr_track
  - weak_gps_pdr_track
  - route_constrained_track
  - admin_reference_track
- Include location, PDR, IMU, battery, environment, and life-sign samples when
  available.
- Include navigation confidence, uncertainty, degradation_reasons,
  gps_reanchor_correction_m, and route corridor distance.

Admin map:
- `trajectory_diff_map.html` is a visualization generated from this record.
- It must overlay GPS-only and INS/DR lines so admin users can compare
  precision and drift.
```

## Prompt: INS/DR Safety Admission For Narrow Trails

```text
Integrate INS/DR + GPS estimates with Scout safety only through an admission
gate.

Important:
- INS/DR + GPS estimates can eventually trigger Scout Ln safety events.
- They must not trigger Ln directly from raw ingress, offline replay, or a
  single low-quality position sample.
- Mountain trails are often narrow; false cliff/off-route detection can create
  unnecessary Scout alarms and operational risk.

Before INS/DR can influence Ln, require:
- active mission route and map context;
- normalized Scout Sensor/Vitals Record evidence;
- reliable or recent re-anchor;
- uncertainty radius and route-corridor distance;
- DR elapsed time and DR distance since anchor under policy limits;
- map/hazard confidence;
- multi-sample persistence or minimum duration;
- hysteresis to prevent flip-flopping;
- narrow-trail margin policy;
- suppression when uncertainty overlaps the safe trail corridor.

Safety event details must preserve:
- GPS-only position;
- INS/DR position;
- uncertainty radius;
- route corridor distance;
- map/hazard overlap;
- consecutive sample count and duration;
- source track refs from the Scout Sensor/Vitals Record;
- reason why the event was admitted or suppressed.

Default narrow-trail rule:
Do not escalate to cliff/fall/off-route Ln from a single INS/DR or GPS sample
when the estimated uncertainty radius overlaps the legal/safe trail corridor.
Escalate only after persistent deviation, high-confidence map hazard overlap,
or corroborating evidence such as barometric drop, accelerometer impact,
distress signal, missed checkpoint, or sustained route-progress conflict.
```

## Prompt: Runtime / Debug Integration

```text
Integrate wearable-first INS/DR into Scout runtime/debug surfaces.

Goal:
- Let operators see whether route progress is coming from reliable GNSS,
  weak/no-good GPS + PDR, route-constrained DR, Scout-host IMU/odometry, or
  vendor-fused comparison.

Display requirements:
- source
- primary_truth_source
- confidence
- degraded
- degradation_reasons
- gnss_horizontal_accuracy_m
- dr_distance_since_anchor_m
- dr_elapsed_s
- gps_reanchor_correction_m
- raw_evidence_refs

Default labels:
- "Wearable route-constrained DR" for pdr_profile=wearable_route_constrained.
- "Upper-bound route oracle" for route_heading_oracle.
- "Host hardware enhanced" only when Scout host IMU/wheel/GNSS evidence is
  actually present.

Do not:
- Mark offline replay as live field proof.
- Hide heading_unavailable; it is expected and acceptable in the wearable
  default profile.
- Treat vendor fusion as primary truth.
- Call live /safety/* mutation from the debug view. Runtime safety admission
  must happen in the safety layer, not in admin visualization.

Deliverables:
- Debug timeline/status projection for INS/DR source classification.
- A filter or legend for reliable GPS, weak GPS + PDR, DR, and vendor comparison.
- Tests for source labels and boundary flags.
```

## Prompt: Cross-Surface Assistant Integration

```text
Teach the Scout cross-surface assistant how to explain wearable-first INS/DR.

The assistant may answer:
- Why is Scout using wearable route-constrained DR?
- Why is heading unavailable not automatically a failure?
- Why did direct course create Z-shaped artifacts?
- How different is INS/DR from GPS in the Apple Watch samples?
- Which evidence is offline replay and which evidence is live Scout hardware?

The assistant must say:
- Most clients are assumed to have watch/phone sensors, not Scout host hardware.
- The default profile is wearable_route_constrained.
- Apple Watch motionYaw/locationCourse are not trusted as absolute heading
  without calibration.
- Offline SensorLog replay does not prove live Scout GNSS.
- Route-constrained DR is advisory/display/navigation evidence, not Phase 1
  safety mutation.

The assistant must not:
- Claim live navigation completion from offline Apple Watch replay.
- Say route_heading_oracle is deployable independent sensor evidence.
- Promote wearable provider health/location values into medical diagnosis or
  safety truth.
- Suggest outbound or /safety/* actions.

Return sources:
- Link to the method matrix summary artifact when present.
- Link to replay/compare JSON and map outputs when present.
- Include the exact profile and method metrics used in the answer.
```

## Prompt: Verification / Regression Integration

```text
Add tests or checks for wearable-first INS/DR integration.

Minimum regression set:
- tests/test_ins_dr_sensorlog_replay.py
- tests/test_ins_dr_sensorlog_method_matrix.py
- tests/test_ins_dr_trajectory_compare_map.py
- tests/test_ins_dr_navigation.py
- tests/test_ins_dr_input_adapter.py
- tests/test_ins_dr_runtime_smoke.py

Required assertions:
- wearable_route_constrained resolves to distributed_sensorlog + no_heading.
- sparse pedometer updates can be distributed to higher source cadence.
- no_heading is allowed and reported as heading_unavailable.
- method matrix marks wearable_route_constrained as recommended_wearable_default.
- route_heading_oracle is marked upper_bound_not_independent_sensor_evidence.
- outputs keep live_navigation_completion_proof=false for offline replay.
- no Phase 1 safety mutation, no outbound send, and no hardware control are
  opened by replay or comparison tooling.

Recommended command:

python3 -m pytest -q \
  tests/test_ins_dr_sensorlog_replay.py \
  tests/test_ins_dr_sensorlog_method_matrix.py \
  tests/test_ins_dr_trajectory_compare_map.py \
  tests/test_ins_dr_navigation.py \
  tests/test_ins_dr_navigation_smoke.py \
  tests/test_ins_dr_input_adapter.py \
  tests/test_ins_dr_runtime_smoke.py
```
