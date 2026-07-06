from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_DOC = REPO_ROOT / "docs/specs/scout-lora-lorawan-sx1303-plan.md"
HARDWARE_DIRECTION_DOC = REPO_ROOT / "docs/specs/scout-hardware-direction.md"
HARDWARE_PORT_PLAN_DOC = REPO_ROOT / "docs/specs/hardware-port-plan.md"


def test_lora_lorawan_sx1303_plan_is_mainline_and_bounded() -> None:
    text = PLAN_DOC.read_text(encoding="utf-8")

    required = [
        "Scout reduces the blank after disconnection.",
        "920-925 MHz",
        "AS923_TW_920_925",
        "Alpha AS923_2 ChirpStack Profile",
        'enabled_regions=["as923_2"]',
        "chirpstack-gateway-bridge-basicstation-as923_2.toml",
        "gateway_control_plane_reachable_rf_unknown",
        "`EU868`, `US915`, `AU915`, `CN470`, `KR920`, `IN865`, and",
        "SX1303",
        "fine timestamp",
        "at least three gateways",
        "phase1_safety_decision_change_allowed",
        "remote_outbound_allowed",
        "diagnostic_gateway_evidence_only",
        "tools/pi_sx1303_gateway_smoke.py",
        "gateway_rf_hardware_detected_no_uplink",
        "SCOUT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL",
        "tools/pi_sx1303_gateway_rx_smoke.py",
        "gateway_rx_stack_ready_no_uplink",
        "SCOUT_SX1303_GATEWAY_RX_READINESS_JSONL",
        "RX READY NO UL",
        "tools/pi_sx1303_gateway_uplink_mqtt_tail.py",
        "sx1303-gateway-uplink-tail-status.jsonl",
        "DevEUI and gateway IDs are hashed by default",
        "does not publish MQTT",
        "tools/pi_wio_e5_lorawan_uplink_trial_plan.py",
        "Operator-Approved Uplink Trial Plan",
        "waiting_for_operator_approval",
        "I_ACCEPT_RF_TX_AS923_2_TW_920_925",
        "ready_for_manual_uplink_trial",
        "rf_tx_executed=false",
        "lorawan_uplink_executed=false",
        "tools/pi_wio_e5_lorawan_rf_trial.py",
        "Alpha Plus RF Trial Executor",
        "`--join-only`",
        "rf_trial_join_confirmed_no_uplink",
        "`AT+JOIN`, and `AT+MSG=\"SCOUT\"`",
        "`--execute-rf-tx`",
        "`--dry-run`",
        "rf_tx_allowed=true",
        "join_executed=true",
        "lorawan_uplink_executed=true",
        "downlink_allowed=false",
        "tools/pi_wio_e5_chirpstack_join_audit.py",
        "Alpha Plus Join Provisioning Audit",
        "client_dev_eui_not_registered_in_chirpstack",
        "client_join_failed_no_gateway_join_hint",
        "client_join_failed_network_server_rejected",
        "chirpstack_config_changed=false",
        "device_registry_changed=false",
        "postgres_write_performed=false",
        "tools/pi_wio_e5_chirpstack_as9232_profile_provision.py",
        "Alpha Plus AS923_2 Profile Provisioning",
        "I_ACCEPT_CHIRPSTACK_PROFILE_MUTATION_AS923_2",
        "device_profile_switch",
        "device_profile_in_place_update",
        "approval_token_stored=false",
        "tools/pi_wio_e5_chirpstack_join_state_reset.py",
        "Alpha Plus Join-State Reset",
        "I_ACCEPT_CHIRPSTACK_JOIN_STATE_RESET_AS923_2",
        "stale_join_state_suspected",
        "dev_nonces",
        "tools/pi_wio_e5_chirpstack_key_sync.py",
        "Alpha Plus OTAA Key Sync",
        "I_ACCEPT_LORAWAN_KEY_SYNC_AS923_2",
        "--use-existing-chirpstack-key",
        "`AT+KEY=APPKEY",
        "target_key_fingerprint",
        "root_key_printed=false",
        "raw_key_embedded=false",
        "serial_write_performed",
        "device_keys_changed",
        "0x0016c001f11f5f46",
        "tools/pi_sx1303_gateway_gps_nmea_smoke.py",
        "L76K GNSS",
        "SX1303 does not itself produce NMEA",
        "diagnostic_gateway_gnss_uart_only",
        "scout_gnss_hardware_observer.py",
        "live_navigation_snapshot.json",
        "live_hardware_read_performed=false",
        "lorawan_uplink_allowed=false",
        "Do not transmit on unvalidated or illegal frequency plans.",
    ]

    for token in required:
        assert token in text


def test_lora_lorawan_sx1303_plan_is_linked_from_hardware_mainline_docs() -> None:
    relative_path = "docs/specs/scout-lora-lorawan-sx1303-plan.md"

    assert relative_path in HARDWARE_DIRECTION_DOC.read_text(encoding="utf-8")
    assert relative_path in HARDWARE_PORT_PLAN_DOC.read_text(encoding="utf-8")
