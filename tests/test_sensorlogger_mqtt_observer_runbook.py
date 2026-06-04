from __future__ import annotations

from pathlib import Path


RUNBOOK_PATH = Path("docs/admin/sensorlogger-mqtt-observer-runbook.md")


def test_sensorlogger_mqtt_observer_runbook_has_capture_command_and_ready_event() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "Sensor Logger MQTT Observer Runbook",
        "scout_sensorlogger_mqtt_observer.py",
        "--env-file sensor-logger-streaming-demo-app/.env",
        "--print-ready",
        '"event": "sensorlogger_mqtt_observer_ready"',
        "scout/test/alex/sensorlogger",
        "sensorlogger_mqtt_raw.jsonl",
        "sensorlogger_mqtt_status.json",
    ):
        assert token in source


def test_sensorlogger_mqtt_observer_runbook_preserves_evidence_only_boundary() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "evidence-only",
        "does not call `/safety/*`",
        "mutate Phase 1 L0-L4 safety state",
        "write Phase 2 Brain facts",
        '"boundary.evidence_only" is `true`',
        '"boundary.safety_api_called" is `false`',
    ):
        assert token in source


def test_sensorlogger_mqtt_observer_runbook_warns_about_browser_credentials() -> None:
    source = RUNBOOK_PATH.read_text(encoding="utf-8")

    for token in (
        "VITE_MQTT_*",
        "visible to the browser runtime",
        "publish-only permission",
        "subscribe-only permission",
        "Rotate the shared test credential",
    ):
        assert token in source
