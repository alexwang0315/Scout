from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_sx1303_gateway_uplink_mqtt_tail import (
    boundary_fields,
    build_mosquitto_sub_command,
    parse_mqtt_lines,
    parse_mqtt_lines_detailed,
    run_mosquitto_sub,
    summarize_unparsed_uplink_message,
    summarize_uplink_message,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_sx1303_gateway_uplink_mqtt_tail.py"

TOPIC = "application/1/device/2cf7f120745059b5/event/up"
UPLINK = {
    "deduplicationId": "dedup-1",
    "time": "2026-07-06T04:00:00Z",
    "deviceInfo": {"devEui": "2cf7f120745059b5", "deviceName": "scout-client-1"},
    "fCnt": 7,
    "fPort": 2,
    "confirmed": False,
    "adr": True,
    "data": "AQID",
    "rxInfo": [
        {
            "gatewayId": "0016c001f11f5f46",
            "rssi": -71,
            "snr": 7.5,
            "channel": 2,
            "rfChain": 1,
            "crcStatus": "CRC_OK",
            "location": {"latitude": 0, "longitude": 0},
        }
    ],
    "txInfo": {
        "frequency": 923200000,
        "modulation": {"lora": {"bandwidth": 125000, "spreadingFactor": 7, "codeRate": "CR_4_5"}},
    },
}


def test_parse_and_summarize_uplink_hashes_identifiers_and_drops_raw_payload() -> None:
    messages, invalid_count = parse_mqtt_lines([f"{TOPIC}\t{json.dumps(UPLINK)}"])
    summary = summarize_uplink_message(messages[0], hash_salt="test-salt", include_identifiers=False)

    assert invalid_count == 0
    assert summary["source"] == "pi_sx1303_gateway_uplink_mqtt_tail"
    assert summary["status"] == "uplink_observed"
    assert summary["topic_kind"] == "chirpstack_application_up"
    assert summary["topic"] == "application/<redacted>/device/<redacted>/event/up"
    assert summary["raw_topic_embedded"] is False
    assert "2cf7f120745059b5" not in summary["topic"]
    assert summary["dev_eui_present"] is True
    assert summary["dev_eui_hash"]
    assert "dev_eui" not in summary
    assert summary["gateway_count"] == 1
    assert summary["gateway_id_hashes"]
    assert "gateway_ids" not in summary
    assert summary["frequency_hz"] == 923200000
    assert summary["spreading_factor"] == 7
    assert summary["bandwidth_hz"] == 125000
    assert summary["f_cnt"] == 7
    assert summary["f_port"] == 2
    assert summary["payload_bytes"] == 3
    assert summary["raw_payload_embedded"] is False
    assert summary["raw_payload_data_embedded"] is False
    assert summary["rf_tx_allowed"] is False
    assert summary["downlink_allowed"] is False
    assert summary["lorawan_uplink_allowed"] is False


def test_cli_fixture_writes_uplink_jsonl_and_status_jsonl_with_visual_dry_run(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "uplinks.jsonl"
    status_jsonl = tmp_path / "tail-status.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture-line",
            f"{TOPIC}\t{json.dumps(UPLINK)}",
            "--output-jsonl",
            str(output_jsonl),
            "--status-jsonl",
            str(status_jsonl),
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
    statuses = [json.loads(line) for line in status_jsonl.read_text(encoding="utf-8").splitlines()]
    record = records[-1]
    status = statuses[-1]

    assert stdout_payload["status"]["status"] == "uplink_observed"
    assert record["status"] == "uplink_observed"
    assert record["raw_payload_data_embedded"] is False
    assert record["hardware_control_scope"] == "diagnostic_gateway_uplink_receive_only"
    assert status["observed_uplink_count"] == 1
    assert status["uplink_jsonl_written"] is True
    assert status["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "UPLINK OK" in status["oled_status_updates"][0]["message"]
    assert status["led_status_updates"][0]["bits"] == "0x100"
    assert status["read_only"] == boundary_fields()["read_only"]


def test_cli_dry_run_does_not_pollute_uplink_jsonl_when_no_message(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "uplinks.jsonl"
    status_jsonl = tmp_path / "tail-status.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dry-run",
            "--output-jsonl",
            str(output_jsonl),
            "--status-jsonl",
            str(status_jsonl),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads(status_jsonl.read_text(encoding="utf-8").splitlines()[-1])
    assert status["status"] == "dry_run"
    assert status["observed_uplink_count"] == 0
    assert status["uplink_jsonl_written"] is False
    assert not output_jsonl.exists()


def test_invalid_mqtt_lines_are_counted_without_failure() -> None:
    messages, invalid_count = parse_mqtt_lines(["missing-tab", f"{TOPIC}\tnot-json"])

    assert messages == []
    assert invalid_count == 2


def test_non_json_uplink_event_can_be_recorded_without_raw_payload() -> None:
    messages, unparsed_messages, invalid_count = parse_mqtt_lines_detailed([f"{TOPIC}\t\ufffd\n"])
    summary = summarize_unparsed_uplink_message(unparsed_messages[0], hash_salt="test-salt", include_identifiers=False)

    assert messages == []
    assert invalid_count == 0
    assert len(unparsed_messages) == 1
    assert summary["status"] == "uplink_observed_unparsed_payload"
    assert summary["topic_kind"] == "chirpstack_application_up"
    assert summary["topic"] == "application/<redacted>/device/<redacted>/event/up"
    assert summary["raw_topic_embedded"] is False
    assert "2cf7f120745059b5" not in summary["topic"]
    assert summary["dev_eui_present"] is True
    assert summary["dev_eui_hash"]
    assert "dev_eui" not in summary
    assert summary["payload_format"] == "non_json_or_binary"
    assert summary["payload_parse_status"] == "not_decoded"
    assert summary["raw_payload_embedded"] is False
    assert summary["raw_payload_data_embedded"] is False
    assert summary["rf_tx_allowed"] is False
    assert summary["downlink_allowed"] is False


def test_cli_fixture_records_non_json_uplink_status(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "uplinks.jsonl"
    status_jsonl = tmp_path / "tail-status.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--fixture-line",
            f"{TOPIC}\t\ufffd",
            "--output-jsonl",
            str(output_jsonl),
            "--status-jsonl",
            str(status_jsonl),
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
    record = json.loads(output_jsonl.read_text(encoding="utf-8").splitlines()[-1])
    status = json.loads(status_jsonl.read_text(encoding="utf-8").splitlines()[-1])

    assert stdout_payload["status"]["status"] == "uplink_observed"
    assert record["status"] == "uplink_observed_unparsed_payload"
    assert record["raw_payload_data_embedded"] is False
    assert status["observed_uplink_count"] == 1
    assert status["unparsed_mqtt_line_count"] == 1
    assert status["invalid_mqtt_line_count"] == 0
    assert status["uplink_jsonl_written"] is True
    assert "UPLINK OK" in status["oled_status_updates"][0]["message"]


def test_mosquitto_binary_payload_is_decoded_without_crashing(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=b"as923_2/gateway/1/event/up\t\xb5\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_mosquitto_sub(["docker", "exec", "mosquitto", "mosquitto_sub"], timeout_seconds=1.0)
    messages, invalid_count = parse_mqtt_lines(result["stdout"].splitlines())

    assert result["status"] == "ok"
    assert "\ufffd" in result["stdout"]
    assert messages == []
    assert invalid_count == 1


def test_mosquitto_sub_command_is_subscribe_only() -> None:
    command = build_mosquitto_sub_command(
        container="mosquitto",
        mqtt_host="127.0.0.1",
        mqtt_port=1883,
        topics=("application/+/device/+/event/up",),
        max_messages=1,
        duration_seconds=5,
    )

    assert command[:4] == ["docker", "exec", "mosquitto", "mosquitto_sub"]
    assert "mosquitto_pub" not in command
    assert "-t" in command
    assert "-C" in command
    assert "-W" in command
