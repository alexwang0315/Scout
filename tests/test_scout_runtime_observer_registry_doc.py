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
        "sx1303-gateway",
        "lorawan-client",
        "physiologic-gate",
        "Current Resident Observer Registry",
            "Live Scout state observed 2026-07-06",
        "Last live verification: 2026-07-06",
        "observer_count=4",
        "running_count=4",
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
        "SCOUT_SX1303_GATEWAY_OLED_STATUS",
        "SCOUT LORA GW",
        "GW READY | NO FWD | WRONG REGION",
        "RF OK NO UL",
        "SCOUT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL",
        "SCOUT_SX1303_GATEWAY_RX_READINESS_JSONL",
        "gateway_rf_hardware_detected_no_uplink",
        "gateway_rx_stack_ready_no_uplink",
        "pi_sx1303_gateway_uplink_mqtt_tail.py",
        "sx1303-gateway-uplink-tail-status.jsonl",
        "SCOUT_SX1303_GATEWAY_LED_STATUS",
        "wrong region blinks LED10",
        "SCOUT_LORAWAN_CLIENT_OLED_STATUS",
        "SCOUT LORA CL",
        "JOIN OK",
        "JOIN STALE",
        "SCOUT_LORAWAN_CLIENT_LED_STATUS",
        "Join rejection or stale join state blinks LED10",
        "stale_join_state_suspected",
        "chirpstack_join_state_repair_required_before_retry",
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
        "Wio-E5 / LoRa-E5 serial writer/RF executor",
        "ChirpStack join-state reset helper",
        "not a resident observer",
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
        "downlink_allowed=false",
        "lorawan_uplink_allowed=false",
        "hardware_control_scope=diagnostic_display_only",
        "hardware_control_scope=diagnostic_indicator_only",
        "hardware_control_scope=diagnostic_gateway_health_only",
        "hardware_control_scope=lorawan_client_evidence_observer_only",
        "I_ACCEPT_CHIRPSTACK_JOIN_STATE_RESET_AS923_2",
        "operator_approval_required=true",
        "device_identity_changed=false",
        "device_keys_changed=false",
    ):
        assert token in source
