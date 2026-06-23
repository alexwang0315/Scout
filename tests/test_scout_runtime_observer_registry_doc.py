from __future__ import annotations

from pathlib import Path


DOC_PATH = Path("docs/specs/scout-runtime-observer-registry.md")


def read_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_runtime_observer_registry_documents_current_resident_observers() -> None:
    source = read_doc()

    for token in (
        "Scout Runtime Observer Registry",
        "ingress_observer_supervisor.py",
        "IngressObserverSupervisor",
        "sensorlogger-mqtt",
        "gnss-hardware",
        "physiologic-gate",
        "Current Resident Observer Registry",
        "Live Scout state observed 2026-06-17",
        "GET /health",
    ):
        assert token in source


def test_runtime_observer_registry_documents_oled_and_led_feedback() -> None:
    source = read_doc()

    for token in (
        "SCOUT_SENSORLOGGER_MQTT_OLED_STATUS",
        "sensorlogger_mqtt_oled_status.jsonl",
        "There is no current resident LED Bar feedback path for this observer.",
        "SCOUT_GNSS_HARDWARE_OLED_STATUS",
        "SCOUT GNSS",
        "FIX OK | NO FIX",
        "SCOUT_GNSS_HARDWARE_LED_STATUS",
        "valid fix blinks",
        "no valid fix blinks",
        "D5",
        "GPIO5",
        "GPIO6",
    ):
        assert token in source


def test_runtime_observer_registry_documents_physiologic_gate_handoff() -> None:
    source = read_doc()

    for token in (
        "SafetyGateEvent",
        "Safety Arbiter / State Reducer",
        "SCOUT_PHYSIOLOGIC_GATE_AUTOSTART",
        "sensorlogger_mqtt_sensor_vitals_records.jsonl",
        "physiologic_safety_gate_event.json",
        "physiologic_reducer_dry_run.json",
        "candidate_retreat",
        "15-minute physiologic windows",
    ):
        assert token in source


def test_runtime_observer_registry_keeps_non_resident_paths_separate() -> None:
    source = read_doc()

    for token in (
        "Known Non-Resident Hardware Paths",
        "Keypad command bridge",
        "IMU/PDR",
        "UPS HAT telemetry",
        "Wi-Fi/OLED boot status and phone uplink recovery",
        "LoRa / ChirpStack stack",
        "Grove smoke tools",
        "Not present in `IngressObserverSupervisor`",
        "not resident observers",
    ):
        assert token in source


def test_runtime_observer_registry_preserves_safety_boundaries() -> None:
    source = read_doc()

    for token in (
        "call live `/safety/*` mutation endpoints",
        "directly change Phase 1 L0-L4 safety state",
        "outbound_send_performed=false",
        "phase1_l0_l4_state_mutated=false",
        "safety_api_called=false",
        "runtime_safety_truth=false",
        "rf_tx_allowed=false",
        "lorawan_uplink_allowed=false",
        "hardware_control_scope=diagnostic_display_only",
        "hardware_control_scope=diagnostic_indicator_only",
    ):
        assert token in source
