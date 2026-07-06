from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

from scout_sx1303_gateway_observer import (
    Sx1303GatewayObserver,
    Sx1303GatewayObserverConfig,
    boundary_fields,
    extract_enabled_regions,
    extract_frequencies_hz,
    gateway_oled_message,
    led_bits_for_sample,
    scan_region_config,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scout_sx1303_gateway_observer.py"


def test_observer_reports_gateway_ready_and_writes_evidence_with_visual_dry_run(tmp_path: Path) -> None:
    config_path = tmp_path / "as923_2.toml"
    uplink_jsonl = tmp_path / "uplinks.jsonl"
    gateway_gps_jsonl = tmp_path / "gateway-gps.jsonl"
    rf_preflight_jsonl = tmp_path / "sx1303-gateway-smoke.jsonl"
    rx_readiness_jsonl = tmp_path / "sx1303-gateway-rx-readiness.jsonl"
    config_path.write_text('region="AS923_2"\nfrequency=923200000\n', encoding="utf-8")
    _write_jsonl(
        uplink_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:00Z",
                "source": "pi_sx1303_gateway_uplink_mqtt_tail",
                "dev_eui_hash": "abc123def4567890",
                "gateway_id_hashes": ["def456abc1237890"],
                "gateway_count": 1,
                "frequency_hz": 923200000,
                "spreading_factor": 7,
                "bandwidth_hz": 125000,
                "f_cnt": 7,
                "f_port": 2,
                "rssi_dbm": -71,
                "snr_db": 7.5,
                "crc_status": "ok",
                "payload_bytes": 3,
                "raw_payload_data_embedded": False,
            }
        ],
    )
    _write_jsonl(
        gateway_gps_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:01Z",
                "source": "pi_sx1303_gateway_gps_nmea_smoke",
                "nmea_available": True,
                "selected_port": "/dev/ttyAMA0",
                "selected_baud": 9600,
            }
        ],
    )
    _write_jsonl(
        rf_preflight_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:02Z",
                "source": "pi_sx1303_gateway_smoke",
                "hardware_kind": "sx1303_lorawan_gateway_hat",
                "status": "ok",
                "gateway_eui": "0x0016c001f11f5f46",
                "chip_version": "0x12",
                "rf_receive_path_checked": True,
                "rf_tx_allowed": False,
            }
        ],
    )
    _write_jsonl(
        rx_readiness_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:03Z",
                "source": "pi_sx1303_gateway_rx_smoke",
                "hardware_kind": "sx1303_lorawan_gateway_hat",
                "status": "rx_stack_ready_no_uplink",
                "readiness_scope": "local_gateway_stack_passive_rx_only",
                "tcp_open_count": 4,
                "udp_listen_count": 1,
                "uplink_hint_count": 0,
                "rf_tx_allowed": False,
            }
        ],
    )
    observer = Sx1303GatewayObserver(
        Sx1303GatewayObserverConfig(
            evidence_dir=tmp_path / "observer",
            uplink_jsonl=uplink_jsonl,
            gateway_gps_jsonl=gateway_gps_jsonl,
            rf_preflight_jsonl=rf_preflight_jsonl,
            rx_readiness_jsonl=rx_readiness_jsonl,
            config_paths=(config_path,),
            tcp_ports=(),
            udp_ports=(1700,),
            oled_status=True,
            oled_dry_run=True,
            led_status=True,
            led_dry_run=True,
        ),
        command_runner=_fake_gateway_runner,
    )

    status = observer.refresh()
    samples = [json.loads(line) for line in observer.evidence_jsonl_path.read_text(encoding="utf-8").splitlines()]
    persisted_status = json.loads(observer.status_path.read_text(encoding="utf-8"))

    assert status["artifact_kind"] == "scout_sx1303_gateway_observer_status"
    assert status["decision"] == "gateway_receiving_uplinks"
    assert status["gateway_health"]["packet_forwarder_running"] is True
    assert status["gateway_health"]["chirpstack_bridge_running"] is True
    assert status["gateway_health"]["udp_listen_count"] == 1
    assert status["region"]["status"] == "region_ok"
    assert status["region"]["detected_expected_tokens"] == ["AS923", "AS923_2"]
    assert status["uplink_summary"]["uplink_like_record_count"] == 1
    assert status["uplink_summary"]["crc_ok_count"] == 1
    assert status["uplink_summary"]["last_record_summary"]["dev_eui_hash"] == "abc123def4567890"
    assert status["uplink_summary"]["last_record_summary"]["raw_payload_data_embedded"] is False
    assert status["gateway_gps_summary"]["last_record_summary"]["nmea_available"] is True
    assert status["rf_preflight_summary"]["last_record_summary"]["gateway_eui"] == "0x0016c001f11f5f46"
    assert status["rx_readiness_summary"]["last_record_summary"]["status"] == "rx_stack_ready_no_uplink"
    assert status["gateway_health"]["rf_preflight_record_count"] == 1
    assert status["gateway_health"]["rx_readiness_record_count"] == 1
    assert status["gateway_health"]["rx_readiness_status"] == "rx_stack_ready_no_uplink"
    assert status["gateway_health"]["gateway_eui"] == "0x0016c001f11f5f46"
    assert status["boundary"] == boundary_fields()
    assert status["boundary"]["rf_tx_allowed"] is False
    assert status["boundary"]["downlink_allowed"] is False
    assert status["boundary"]["lorawan_uplink_allowed"] is False
    assert status["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert persisted_status["decision"] == status["decision"]

    assert samples[-1]["decision"] == "gateway_receiving_uplinks"
    assert samples[-1]["boundary"]["safety_api_called"] is False
    assert status["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "SCOUT LORA GW" in status["oled_status_updates"][0]["message"]
    assert "UPLINK OK" in status["oled_status_updates"][0]["message"]
    assert status["oled_status_updates"][0]["rf_tx_allowed"] is False
    assert status["led_status_updates"][0]["write_status"] == "dry_run"
    assert status["led_status_updates"][0]["bits"] == "0x080"


def test_observer_flags_wrong_region_before_forwarder_health(tmp_path: Path) -> None:
    config_path = tmp_path / "eu868.toml"
    config_path.write_text('region="EU868"\nfrequency=868100000\n', encoding="utf-8")
    observer = Sx1303GatewayObserver(
        Sx1303GatewayObserverConfig(
            evidence_dir=tmp_path / "observer",
            uplink_jsonl=tmp_path / "missing-uplink.jsonl",
            gateway_gps_jsonl=tmp_path / "missing-gps.jsonl",
            config_paths=(config_path,),
            tcp_ports=(),
            udp_ports=(),
            led_status=True,
            led_dry_run=True,
        ),
        command_runner=_fake_gateway_runner,
    )

    status = observer.refresh()

    assert status["decision"] == "wrong_region"
    assert status["region"]["detected_forbidden_tokens"] == ["EU868"]
    assert status["region"]["outside_tw_frequencies_hz"] == [868100000]
    assert status["led_status_updates"][0]["bits"] == "0x200"
    assert status["boundary"]["gateway_config_changed"] is False
    assert status["boundary"]["rf_tx_allowed"] is False


def test_observer_degrades_without_gateway_stack_or_config(tmp_path: Path) -> None:
    observer = Sx1303GatewayObserver(
        Sx1303GatewayObserverConfig(
            evidence_dir=tmp_path / "observer",
            uplink_jsonl=tmp_path / "missing-uplink.jsonl",
            gateway_gps_jsonl=tmp_path / "missing-gps.jsonl",
            config_paths=(tmp_path / "missing.toml",),
            tcp_ports=(),
            udp_ports=(),
        ),
        command_runner=_missing_command_runner,
    )

    status = observer.refresh()

    assert status["decision"] == "packet_forwarder_missing"
    assert status["answerability"] == "gateway_health_evidence_incomplete"
    assert status["region"]["status"] == "config_missing"
    assert status["process_status"]["packet_forwarder_running"] is False
    assert status["process_status"]["pgrep"]["status"] == "command_missing"
    assert status["boundary"]["outbound_send_performed"] is False


def test_observer_reports_control_plane_reachable_when_process_probe_is_unavailable(tmp_path: Path) -> None:
    config_path = tmp_path / "as923_2.toml"
    config_path.write_text('common_name="AS923_2"\nfrequency=921400000\n', encoding="utf-8")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])

    try:
        observer = Sx1303GatewayObserver(
            Sx1303GatewayObserverConfig(
                evidence_dir=tmp_path / "observer",
                uplink_jsonl=tmp_path / "missing-uplink.jsonl",
                gateway_gps_jsonl=tmp_path / "missing-gps.jsonl",
                config_paths=(config_path,),
                host="127.0.0.1",
                tcp_ports=(port,),
                udp_ports=(),
                oled_status=True,
                oled_dry_run=True,
            ),
            command_runner=_missing_command_runner,
        )

        status = observer.refresh()
    finally:
        listener.close()

    assert status["decision"] == "gateway_control_plane_reachable_rf_unknown"
    assert status["answerability"] == "gateway_control_plane_evidence_available_rf_path_unknown"
    assert status["gateway_health"]["tcp_open_count"] == 1
    assert status["gateway_health"]["process_visibility"] == "process_commands_unavailable"
    assert "CTRL OK RF?" in status["oled_status_updates"][0]["message"]
    assert status["boundary"]["rf_tx_allowed"] is False


def test_observer_uses_rf_preflight_evidence_when_no_uplink_has_arrived(tmp_path: Path) -> None:
    config_path = tmp_path / "as923_2.toml"
    rf_preflight_jsonl = tmp_path / "sx1303-gateway-smoke.jsonl"
    config_path.write_text('enabled_regions=["as923_2"]\nfrequency=923200000\n', encoding="utf-8")
    _write_jsonl(
        rf_preflight_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:02Z",
                "source": "pi_sx1303_gateway_smoke",
                "hardware_kind": "sx1303_lorawan_gateway_hat",
                "status": "ok",
                "gateway_eui": "0x0016c001f11f5f46",
                "chip_version": "0x12",
                "rf_receive_path_checked": True,
                "rf_tx_allowed": False,
            }
        ],
    )
    observer = Sx1303GatewayObserver(
        Sx1303GatewayObserverConfig(
            evidence_dir=tmp_path / "observer",
            uplink_jsonl=tmp_path / "missing-uplink.jsonl",
            gateway_gps_jsonl=tmp_path / "missing-gps.jsonl",
            rf_preflight_jsonl=rf_preflight_jsonl,
            config_paths=(config_path,),
            tcp_ports=(),
            udp_ports=(),
            oled_status=True,
            oled_dry_run=True,
            led_status=True,
            led_dry_run=True,
        ),
        command_runner=_missing_command_runner,
    )

    status = observer.refresh()

    assert status["decision"] == "gateway_rf_hardware_detected_no_uplink"
    assert status["answerability"] == "gateway_rf_hardware_evidence_available_no_uplink_seen"
    assert status["gateway_health"]["gateway_eui"] == "0x0016c001f11f5f46"
    assert "RF OK NO UL" in status["oled_status_updates"][0]["message"]
    assert status["led_status_updates"][0]["bits"] == "0x080"
    assert status["boundary"]["rf_tx_allowed"] is False
    assert status["boundary"]["lorawan_uplink_allowed"] is False


def test_observer_uses_rx_readiness_evidence_when_no_client_uplink_has_arrived(tmp_path: Path) -> None:
    config_path = tmp_path / "as923_2.toml"
    rf_preflight_jsonl = tmp_path / "sx1303-gateway-smoke.jsonl"
    rx_readiness_jsonl = tmp_path / "sx1303-gateway-rx-readiness.jsonl"
    config_path.write_text('enabled_regions=["as923_2"]\nfrequency=923200000\n', encoding="utf-8")
    _write_jsonl(
        rf_preflight_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:02Z",
                "source": "pi_sx1303_gateway_smoke",
                "hardware_kind": "sx1303_lorawan_gateway_hat",
                "status": "ok",
                "gateway_eui": "0x0016c001f11f5f46",
                "chip_version": "0x12",
                "rf_receive_path_checked": True,
                "rf_tx_allowed": False,
            }
        ],
    )
    _write_jsonl(
        rx_readiness_jsonl,
        [
            {
                "captured_at": "2026-07-06T00:00:03Z",
                "source": "pi_sx1303_gateway_rx_smoke",
                "hardware_kind": "sx1303_lorawan_gateway_hat",
                "status": "rx_stack_ready_no_uplink",
                "readiness_scope": "local_gateway_stack_passive_rx_only",
                "tcp_open_count": 4,
                "udp_listen_count": 1,
                "uplink_hint_count": 0,
                "rf_tx_allowed": False,
            }
        ],
    )
    observer = Sx1303GatewayObserver(
        Sx1303GatewayObserverConfig(
            evidence_dir=tmp_path / "observer",
            uplink_jsonl=tmp_path / "missing-uplink.jsonl",
            gateway_gps_jsonl=tmp_path / "missing-gps.jsonl",
            rf_preflight_jsonl=rf_preflight_jsonl,
            rx_readiness_jsonl=rx_readiness_jsonl,
            config_paths=(config_path,),
            tcp_ports=(),
            udp_ports=(),
            oled_status=True,
            oled_dry_run=True,
            led_status=True,
            led_dry_run=True,
        ),
        command_runner=_missing_command_runner,
    )

    status = observer.refresh()

    assert status["decision"] == "gateway_rx_stack_ready_no_uplink"
    assert status["answerability"] == "gateway_rx_stack_ready_no_client_uplink_seen"
    assert status["gateway_health"]["rx_readiness_status"] == "rx_stack_ready_no_uplink"
    assert "RX READY NO UL" in status["oled_status_updates"][0]["message"]
    assert status["led_status_updates"][0]["bits"] == "0x080"
    assert status["boundary"]["rf_tx_allowed"] is False
    assert status["boundary"]["downlink_allowed"] is False


def test_region_config_scanner_detects_tw_frequencies_and_forbidden_values(tmp_path: Path) -> None:
    config_path = tmp_path / "region.toml"
    config_path.write_text("AS923_2\n923.4\n923200000\nEU868\n868100000\n", encoding="utf-8")

    region = scan_region_config(
        paths=(config_path,),
        expected_tokens=("AS923", "AS923_2"),
        forbidden_tokens=("EU868",),
    )

    assert region["status"] == "wrong_region"
    assert 923200000 in region["frequencies_hz"]
    assert 923400000 in region["frequencies_hz"]
    assert 868100000 in region["outside_tw_frequencies_hz"]
    assert extract_frequencies_hz("923.2 924800000") == [923200000, 924800000]


def test_region_config_scanner_reads_enabled_regions_and_separates_frequency_bounds(tmp_path: Path) -> None:
    chirpstack = tmp_path / "chirpstack.toml"
    chirpstack.write_text(
        'enabled_regions=["as923_2", "eu868"]\n# "us915_0" in a comment is ignored\n',
        encoding="utf-8",
    )
    as923_2 = tmp_path / "region_as923_2.toml"
    as923_2.write_text(
        "\n".join(
            [
                'common_name="AS923_2"',
                "frequency_min=915000000",
                "frequency_max=928000000",
                "frequency=921400000",
                "rx2_frequency=921400000",
            ]
        ),
        encoding="utf-8",
    )

    mixed = scan_region_config(
        paths=(chirpstack, as923_2),
        expected_tokens=("AS923", "AS923_2"),
        forbidden_tokens=("EU868", "US915"),
    )
    warning_only = scan_region_config(
        paths=(as923_2,),
        expected_tokens=("AS923", "AS923_2"),
        forbidden_tokens=("EU868", "US915"),
    )

    assert extract_enabled_regions(chirpstack.read_text(encoding="utf-8")) == ["AS923_2", "EU868"]
    assert mixed["status"] == "wrong_region"
    assert mixed["forbidden_enabled_regions"] == ["EU868"]
    assert 921400000 in mixed["frequencies_hz"]
    assert 915000000 in mixed["outside_tw_frequency_bounds_hz"]
    assert 928000000 in mixed["outside_tw_frequency_bounds_hz"]
    assert 915000000 not in mixed["outside_tw_frequencies_hz"]
    assert warning_only["status"] == "region_warning"
    assert warning_only["outside_tw_frequencies_hz"] == []


def test_oled_and_led_helpers_keep_gateway_status_short_and_bounded() -> None:
    sample = {
        "decision": "gateway_ready_no_uplink",
        "region": {"status": "region_ok", "detected_expected_tokens": ["AS923_2"]},
        "process_status": {"packet_forwarder_running": True, "chirpstack_bridge_running": True},
        "uplink_summary": {"record_count_scanned": 0},
    }

    message = gateway_oled_message(sample)

    assert "SCOUT LORA GW" in message
    assert "GW READY" in message
    assert all(len(line) <= 16 for line in message.splitlines())
    assert led_bits_for_sample(sample, ok_bit=8, warn_bit=1, fail_bit=10) == 0x080

    rf_detected = {**sample, "decision": "gateway_rf_hardware_detected_no_uplink"}
    assert "RF OK NO UL" in gateway_oled_message(rf_detected)
    assert led_bits_for_sample(rf_detected, ok_bit=8, warn_bit=1, fail_bit=10) == 0x080

    rx_ready = {**sample, "decision": "gateway_rx_stack_ready_no_uplink"}
    assert "RX READY NO UL" in gateway_oled_message(rx_ready)
    assert led_bits_for_sample(rx_ready, ok_bit=8, warn_bit=1, fail_bit=10) == 0x080

    wrong_region = {
        **sample,
        "decision": "wrong_region",
        "region": {"status": "wrong_region", "forbidden_enabled_regions": ["AU915_0", "EU868"]},
    }
    assert "REG FORBID 2" in gateway_oled_message(wrong_region)
    assert led_bits_for_sample(wrong_region, ok_bit=8, warn_bit=1, fail_bit=10) == 0x200

    degraded = {**sample, "decision": "packet_forwarder_missing"}
    assert led_bits_for_sample(degraded, ok_bit=8, warn_bit=1, fail_bit=10) == 0x001


def test_cli_once_writes_status_and_rejects_invalid_arguments(tmp_path: Path) -> None:
    config_path = tmp_path / "as923.toml"
    config_path.write_text("AS923\n923200000\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--once",
            "--evidence-dir",
            str(tmp_path / "observer"),
            "--config-paths",
            str(config_path),
            "--tcp-ports",
            "",
            "--udp-ports",
            "",
            "--command-timeout-seconds",
            "0.1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["artifact_kind"] == "scout_sx1303_gateway_observer_status"
    assert status["boundary"]["rf_tx_allowed"] is False

    bad_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--led-ok-bit", "11"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bad_result.returncode == 2
    assert "LED bit must be between 1 and 10" in bad_result.stderr


def _fake_gateway_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    if command[:2] == ["pgrep", "-af"]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="123 /usr/bin/lora_pkt_fwd\n124 chirpstack-gateway-bridge\n",
            stderr="",
        )
    if command[:2] == ["docker", "ps"]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="chirpstack-gateway-bridge\tUp 10 minutes\t1883/tcp\n",
            stderr="",
        )
    if command == ["ss", "-lun"]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="UNCONN 0 0 0.0.0.0:1700 0.0.0.0:*\n",
            stderr="",
        )
    return subprocess.CompletedProcess(command, 1, stdout="", stderr="")


def _missing_command_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    raise FileNotFoundError(command[0])


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
