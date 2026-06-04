# Sensor Logger MQTT Observer Runbook

Date: 2026-06-04

## Purpose

Use this runbook to capture live Sensor Logger MQTT messages into Scout
evidence.

This observer is evidence-only. It proves that Scout can receive the
phone/wearable sensor stream, preserve raw MQTT messages, and summarize device
session state. It does not call `/safety/*`, mutate Phase 1 L0-L4 safety state,
send SOS/SMS/satellite messages, or write Phase 2 Brain facts.

## Prerequisites

- Sensor Logger Pro has MQTT Publishing enabled.
- HiveMQ Cloud or another MQTT broker is running.
- Sensor Logger and Scout observer use the same topic.
- The local observer has `paho-mqtt==2.1.0` installed from
  `requirements.pi.live.txt`.

Current lab topic:

```text
scout/test/alex/sensorlogger
```

## Recommended Capture Command

The observer can read the local demo `.env` file directly. This avoids exporting
the MQTT password in the shell:

```bash
cd /Users/alexwang0315/scout-fusion

./venv/bin/python scout_sensorlogger_mqtt_observer.py \
  --env-file sensor-logger-streaming-demo-app/.env \
  --evidence-dir /tmp/scout_sensorlogger_mqtt_observer_app_capture \
  --max-messages 1 \
  --timeout-seconds 120 \
  --print-ready
```

Wait for this readiness event:

```json
{
  "event": "sensorlogger_mqtt_observer_ready",
  "subscribe_reason": "Granted QoS 0",
  "topic": "scout/test/alex/sensorlogger"
}
```

After the readiness event appears, use the iPhone Sensor Logger app to either:

- tap `Test Publish`; or
- start a recording session with `Enable MQTT Publish` turned on.

## Expected Success Evidence

On success, the observer exits after the first accepted message and writes:

```text
/tmp/scout_sensorlogger_mqtt_observer_app_capture/sensorlogger_mqtt_raw.jsonl
/tmp/scout_sensorlogger_mqtt_observer_app_capture/sensorlogger_mqtt_status.json
```

Check the status:

```bash
./venv/bin/python - <<'PY'
import json
from pathlib import Path

status = json.loads(
    Path("/tmp/scout_sensorlogger_mqtt_observer_app_capture/sensorlogger_mqtt_status.json")
    .read_text(encoding="utf-8")
)
print(json.dumps({
    "message_count": status["message_count"],
    "mqtt_state": status["mqtt_state"],
    "sensor_names": status["sensor_names"],
    "sessions": status["sessions"],
    "boundary": status["boundary"],
}, indent=2, sort_keys=True))
PY
```

Expected indicators:

- `message_count` is at least `1`.
- `mqtt_state.ever_connected` is `true`.
- `mqtt_state.ever_subscribed` is `true`.
- `sessions[0].device_id` and `sessions[0].session_id` are populated for a
  recording payload.
- `sensor_names` includes Sensor Logger readings such as `accelerometer`,
  `gyroscope`, `location`, `battery`, or other enabled sensors.
- `"boundary.evidence_only" is `true`: the observer stayed evidence-only.
- `"boundary.safety_api_called" is `false`: the observer did not touch live
  safety APIs.

## If No Message Is Captured

If the observer exits with `message_count: 0` but `mqtt_state.ever_subscribed:
true`, Scout reached the broker and subscribed correctly. Check the iPhone side:

- `Enable MQTT Publish` is on.
- `Connection Type` is `Websocket`.
- `Use TLS` is on for HiveMQ Cloud.
- `Broker URL` is the HiveMQ host only, with no `wss://` prefix and no `/mqtt`
  path.
- `Broker Port` is `8884`.
- `Topic` exactly matches `scout/test/alex/sensorlogger`.
- The credential assigned in HiveMQ has publish permission for that topic.
- HiveMQ Web Client shows the same message on the same topic.

MQTT messages are not retained by default. The observer must already be
subscribed before Sensor Logger publishes if you want this command to capture
that message.

## Credential Boundary

The demo `.env` file uses `VITE_MQTT_*` keys for a browser dashboard. Those
values are visible to the browser runtime and are suitable only for local smoke
tests.

For longer runs, use separate credentials:

- Sensor Logger: publish-only permission on the Sensor Logger topic.
- Scout observer: subscribe-only permission on the same topic.
- Demo dashboard: subscribe-only permission, or disable it during capture.

Rotate the shared test credential after local debugging.
