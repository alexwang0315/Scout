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
- The Scout admin image has `paho-mqtt==2.1.0` installed from
  `requirements.pi.admin.txt`.

Current lab topic:

```text
scout/test/alex/sensorlogger
```

## Scout-Side Autostart

The preferred Scout path is automatic. When the Phase 4 admin runtime starts,
`IngressObserverSupervisor` starts the Sensor Logger MQTT observer in the
background if `SCOUT_SENSORLOGGER_MQTT_AUTOSTART` is enabled and either the
configured env file exists or inline broker/topic env vars are present.

Default Scout paths:

```text
env file:     /data/scout/secrets/sensorlogger-mqtt.env
evidence dir: /data/scout/admin/ingress/sensorlogger_mqtt
log file:     /data/scout/admin/ingress/sensorlogger-mqtt-observer.log
status file:  /data/scout/admin/ingress/sensorlogger_mqtt/sensorlogger_mqtt_status.json
```

The env file should contain the MQTT host, websocket TLS port, topic, and the
Scout observer's subscribe credential. Keep Sensor Logger on a separate
publish-only credential when possible.

Verify autostart from the Scout host:

```bash
curl -sS \
  -H "Authorization: Bearer $(cat /data/scout/admin/secrets/phase4-admin-token)" \
  http://127.0.0.1:9110/health
```

Expected indicators in the health payload:

- `ingress_observers.enabled` is `true`.
- `ingress_observers.running_count` is at least `1`.
- the `sensorlogger-mqtt` observer reports `running: true`.
- `env_file_exists` is `true`.
- no MQTT password or token value appears in the payload.

Check the observer log without exposing secrets:

```bash
tail -n 40 /data/scout/admin/ingress/sensorlogger-mqtt-observer.log
```

## Reset Debug Counters

`/admin/debug?tab=ingress` includes a `歸零` button for MQTT ingress counters.
It writes a debug reset marker and makes the Ingress panel count from that
baseline forward.

This reset is projection-only:

- it does not delete raw MQTT evidence JSONL;
- it does not delete ingress summary JSONL;
- it does not restart or stop the observer;
- it does not mutate runtime admission, `/safety/*`, Phase 1 L0-L4, or Phase 2
  Brain state.

The reset marker is stored beside the observer status file:

```text
/data/scout/admin/ingress/sensorlogger_mqtt/sensorlogger_mqtt_debug_reset.json
```

## Local Capture Fallback

The observer can read the local demo `.env` file directly. This avoids exporting
the MQTT password in the shell. Use this command only for local smoke tests or
when the Scout-side admin runtime is not available:

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
