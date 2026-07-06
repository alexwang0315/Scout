from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_sx1303_gateway_rx_smoke import (
    boundary_fields,
    led_bits_for_status,
    parse_docker_ps,
    readiness_status,
    summarize_containers,
    summarize_log_text,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_sx1303_gateway_rx_smoke.py"

DOCKER_PS = "\n".join(
    [
        "chirpstack-docker-chirpstack-gateway-bridge-1\tUp 3 hours\t0.0.0.0:1700->1700/udp",
        "chirpstack-docker-chirpstack-gateway-bridge-basicstation-1\tUp 3 hours\t0.0.0.0:3001->3001/tcp",
        "chirpstack-docker-chirpstack-1\tUp 17 hours\t0.0.0.0:8080->8080/tcp",
        "chirpstack-docker-mosquitto-1\tUp 17 hours\t0.0.0.0:1883->1883/tcp",
    ]
)
SS_LUN = "UNCONN 0 0 0.0.0.0:1700 0.0.0.0:*\n"


def test_parse_docker_ps_and_readiness_status_for_ready_no_uplink() -> None:
    containers = parse_docker_ps(DOCKER_PS)
    summary = summarize_containers(containers)
    status = readiness_status(
        container_summary=summary,
        tcp=[],
        udp=[{"status": "listening"}],
        log_summary=summarize_log_text("bridge started\n", source="fixture"),
        dry_run=False,
    )

    assert summary["udp_gateway_bridge_running"] is True
    assert summary["basicstation_bridge_running"] is True
    assert summary["chirpstack_running"] is True
    assert summary["mqtt_broker_running"] is True
    assert status == "rx_stack_ready_no_uplink"


def test_log_summary_detects_uplink_hints_without_embedding_raw_lines() -> None:
    summary = summarize_log_text("gateway event received\nintegration/event/up\n", source="fixture")

    assert summary["uplink_hint_count"] == 2
    assert summary["raw_log_lines_embedded"] is False


def test_cli_writes_jsonl_with_visual_dry_run_and_boundaries(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "rx-readiness.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--docker-ps-output",
            DOCKER_PS,
            "--ss-lun-output",
            SS_LUN,
            "--docker-logs-output",
            "bridge started\n",
            "--tcp-ports",
            "",
            "--output-jsonl",
            str(output_jsonl),
            "--oled-status",
            "--oled-dry-run",
            "--led-status",
            "--led-dry-run",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    stdout_payload = json.loads(result.stdout)
    records = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    payload = records[-1]

    assert stdout_payload["source"] == "pi_sx1303_gateway_rx_smoke"
    assert payload["status"] == "rx_stack_ready_no_uplink"
    assert payload["udp_listen_count"] == 1
    assert payload["uplink_hint_count"] == 0
    assert payload["raw_log_lines_embedded"] is False
    assert payload["rf_tx_allowed"] is False
    assert payload["lorawan_uplink_allowed"] is False
    assert payload["packet_forwarder_started"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_gateway_rx_readiness_only"
    assert payload["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "RX READY NO UL" in payload["oled_status_updates"][0]["message"]
    assert payload["led_status_updates"][0]["bits"] == "0x080"
    assert payload["read_only"] == boundary_fields()["read_only"]


def test_cli_detects_uplink_hint_but_still_marks_no_tx_authority(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "rx-readiness.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--docker-ps-output",
            DOCKER_PS,
            "--ss-lun-output",
            SS_LUN,
            "--docker-logs-output",
            "integration/event/up received",
            "--tcp-ports",
            "",
            "--output-jsonl",
            str(output_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "rx_stack_seen_uplink"
    assert payload["uplink_hint_count"] == 1
    assert payload["rf_tx_allowed"] is False
    assert payload["downlink_allowed"] is False
    assert led_bits_for_status("rx_stack_seen_uplink", ready_bit=8, warn_bit=1, uplink_bit=9) == 0x100


def test_cli_invalid_port_fails_cleanly() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tcp-ports", "abc"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "invalid integer value: abc" in result.stderr
