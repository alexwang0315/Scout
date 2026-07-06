from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_chirpstack_join_audit import (
    boundary_fields,
    led_bits_for_audit,
    normalize_eui,
    parse_postgres_device_output,
    summarize_log_text,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_chirpstack_join_audit.py"
DEV_EUI = "2C:F7:F1:20:74:50:59:B5"
DEV_EUI_COMPACT = "2cf7f120745059b5"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def wio_at_records() -> list[dict[str, object]]:
    return [
        {
            "captured_at": "2026-07-06T04:00:00+00:00",
            "source": "pi_wio_e5_lorawan_at_smoke",
            "command": "AT+ID",
            "response_status": "ok",
            "response_lines": [
                "+ID: DevAddr, 26:01:11:22",
                f"+ID: DevEui, {DEV_EUI}",
                "+ID: AppEui, 80:00:00:00:00:00:00:06",
                "+AT: OK",
            ],
        }
    ]


def rf_join_failed_record() -> dict[str, object]:
    return {
        "captured_at": "2026-07-06T05:13:25+00:00",
        "source": "pi_wio_e5_lorawan_rf_trial",
        "dry_run": False,
        "status": "rf_trial_uplink_command_sent",
        "rf_tx_executed": True,
        "join_executed": True,
        "lorawan_uplink_executed": True,
        "command_results": [
            {"command": "AT", "response_status": "ok", "response_lines": ["+AT: OK"]},
            {
                "command": "AT+JOIN",
                "response_status": "ok",
                "response_lines": ["+JOIN: Start", "+JOIN: NORMAL", "+JOIN: Join failed", "+JOIN: Done"],
            },
            {
                "command": "AT+MSG=\"SCOUT\"",
                "response_status": "ok",
                "response_lines": ["+MSG: Please join network first"],
            },
        ],
    }


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def base_args(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, list[str]]:
    wio = tmp_path / "wio.jsonl"
    rf = tmp_path / "rf.jsonl"
    uplink = tmp_path / "uplink.jsonl"
    tail = tmp_path / "tail.jsonl"
    output = tmp_path / "audit.jsonl"
    write_jsonl(wio, wio_at_records())
    write_jsonl(rf, [rf_join_failed_record()])
    write_jsonl(tail, [{"status": "no_uplink_observed", "observed_uplink_count": 0, "uplink_jsonl_written": False}])
    return (
        wio,
        rf,
        uplink,
        tail,
        output,
        [
            "--wio-at-jsonl",
            str(wio),
            "--rf-trial-jsonl",
            str(rf),
            "--uplink-jsonl",
            str(uplink),
            "--tail-status-jsonl",
            str(tail),
            "--output-jsonl",
            str(output),
            "--docker-ps-output",
            "chirpstack-docker-chirpstack-1\tUp 1 hour\t8080\nchirpstack-docker-chirpstack-gateway-bridge-1\tUp 1 hour\t1700/udp\nchirpstack-docker-postgres-1\tUp 1 hour\t5432",
        ],
    )


def test_cli_detects_unregistered_dev_eui_without_leaking_raw_identity(tmp_path: Path) -> None:
    _, _, _, _, output, args = base_args(tmp_path)

    result = run_cli(
        *args,
        "--chirpstack-log-output",
        "join-request received but device not found",
        "--gateway-bridge-log-output",
        "gateway event join-request",
        "--postgres-device-output",
        "0102030405060708\n",
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)
    persisted = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    assert persisted["decision"] == "client_dev_eui_not_registered_in_chirpstack"
    assert audit["wio_at_summary"]["dev_eui_hash"].startswith("sha256:")
    assert DEV_EUI not in result.stdout
    assert DEV_EUI_COMPACT not in result.stdout
    assert audit["postgres_device_summary"]["device_registry_match"] is False
    assert audit["raw_log_lines_embedded"] is False
    assert audit["raw_device_eui_embedded"] is False
    assert audit["rf_tx_allowed"] is False
    assert audit["lorawan_uplink_allowed"] is False
    assert audit["device_registry_changed"] is False
    assert audit["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "DEV MISSING" in audit["oled_status_updates"][0]["message"]
    assert audit["led_status_updates"][0]["bits"] == "0x200"


def test_cli_detects_join_failed_no_gateway_hint(tmp_path: Path) -> None:
    _, _, _, _, _, args = base_args(tmp_path)

    result = run_cli(
        *args,
        "--chirpstack-log-output",
        "server started",
        "--gateway-bridge-log-output",
        "bridge ready",
        "--postgres-device-output",
        DEV_EUI_COMPACT,
    )

    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)
    assert audit["decision"] == "client_join_failed_no_gateway_join_hint"
    assert audit["rf_trial_summary"]["join_failed_response_seen"] is True
    assert audit["rf_trial_summary"]["please_join_network_first_seen"] is True
    assert audit["postgres_device_summary"]["device_registry_match"] is True
    assert audit["log_summaries"][0]["join_request_hint_count"] == 0


def test_cli_detects_network_reject_even_without_join_request_phrase(tmp_path: Path) -> None:
    _, _, _, _, _, args = base_args(tmp_path)

    result = run_cli(
        *args,
        "--chirpstack-log-output",
        "server started",
        "--gateway-bridge-log-output",
        "as923_2 gateway event/up failed MIC",
        "--postgres-device-output",
        DEV_EUI_COMPACT,
    )

    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)
    assert audit["decision"] == "client_join_failed_network_server_rejected"
    assert audit["log_summaries"][1]["join_reject_hint_count"] >= 1
    assert led_bits_for_audit(audit, no_join_hint_bit=1, join_seen_bit=8, uplink_bit=9, rejected_bit=10) == 0x200


def test_cli_prefers_uplink_observed_decision(tmp_path: Path) -> None:
    _, _, uplink, _, _, args = base_args(tmp_path)
    write_jsonl(uplink, [{"status": "uplink_observed", "dev_eui_hash": "sha256:test"}])

    result = run_cli(
        *args,
        "--chirpstack-log-output",
        "join-request received",
        "--gateway-bridge-log-output",
        "event/up",
        "--postgres-device-output",
        DEV_EUI_COMPACT,
    )

    assert result.returncode == 0, result.stderr
    audit = json.loads(result.stdout)
    assert audit["decision"] == "uplink_observed"
    assert audit["uplink_summary"]["uplink_like_record_count"] == 1
    assert led_bits_for_audit(audit, no_join_hint_bit=1, join_seen_bit=8, uplink_bit=9, rejected_bit=10) == 0x100


def test_log_and_postgres_helpers_hash_and_count_without_raw_lines() -> None:
    log_summary = summarize_log_text(
        "rx join-request DevEUI=2cf7f120745059b5\nerror device not found\n",
        dev_eui=DEV_EUI,
        source="fixture",
    )
    postgres_summary = parse_postgres_device_output("2cf7f120745059b5\n", dev_eui=DEV_EUI, hash_salt="test")

    assert normalize_eui(DEV_EUI) == "2c:f7:f1:20:74:50:59:b5"
    assert log_summary["join_request_hint_count"] >= 1
    assert log_summary["join_reject_hint_count"] >= 1
    assert log_summary["dev_eui_seen_in_logs"] is True
    assert log_summary["raw_log_lines_embedded"] is False
    assert postgres_summary["device_registry_match"] is True
    assert postgres_summary["device_eui_hashes"][0].startswith("sha256:")
    assert postgres_summary["raw_device_eui_embedded"] is False
    assert boundary_fields()["rf_tx_allowed"] is False
