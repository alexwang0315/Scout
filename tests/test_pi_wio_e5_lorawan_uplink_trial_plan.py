from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_lorawan_uplink_trial_plan import (
    APPROVAL_TOKEN,
    boundary_fields,
    led_bits_for_plan,
    normalize_eui,
    parse_frequency_hz,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_lorawan_uplink_trial_plan.py"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def wio_records() -> list[dict[str, object]]:
    return [
        {
            "captured_at": "2026-07-06T04:00:00+00:00",
            "source": "pi_wio_e5_lorawan_at_smoke",
            "command": "AT",
            "response_lines": ["+AT: OK"],
            "response_status": "ok",
        },
        {
            "captured_at": "2026-07-06T04:00:01+00:00",
            "source": "pi_wio_e5_lorawan_at_smoke",
            "command": "AT+ID",
            "response_lines": [
                "+ID: DevAddr, 26:01:11:22",
                "+ID: DevEui, 2C:F7:F1:20:74:50:59:B5",
                "+ID: AppEui, 80:00:00:00:00:00:00:06",
                "+AT: OK",
            ],
            "response_status": "ok",
        },
    ]


def gateway_rx_records() -> list[dict[str, object]]:
    return [
        {
            "captured_at": "2026-07-06T04:02:00+00:00",
            "source": "pi_sx1303_gateway_rx_smoke",
            "status": "rx_stack_ready_no_uplink",
            "rf_tx_allowed": False,
            "lorawan_uplink_allowed": False,
        }
    ]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ready_plan_requires_explicit_operator_approval_and_never_transmits(tmp_path: Path) -> None:
    wio = tmp_path / "wio.jsonl"
    rx = tmp_path / "rx.jsonl"
    output = tmp_path / "plan.jsonl"
    uplink = tmp_path / "uplink.jsonl"
    write_jsonl(wio, wio_records())
    write_jsonl(rx, gateway_rx_records())

    result = run_cli(
        "--wio-at-jsonl",
        str(wio),
        "--gateway-rx-jsonl",
        str(rx),
        "--uplink-jsonl",
        str(uplink),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    )

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    persisted = json.loads(output.read_text(encoding="utf-8").splitlines()[-1])
    assert persisted["status"] == "ready_for_manual_uplink_trial"
    assert plan["status"] == "ready_for_manual_uplink_trial"
    assert plan["operator_approval_recorded"] is True
    assert plan["operator_approval_token_stored"] is False
    assert plan["wio_at_summary"]["status"] == "wio_at_ready"
    assert plan["wio_at_summary"]["dev_eui_hash"].startswith("sha256:")
    assert "2C:F7:F1:20:74:50:59:B5" not in result.stdout
    assert plan["gateway_rx_summary"]["status"] == "gateway_rx_ready"
    assert plan["rf_tx_allowed"] is False
    assert plan["rf_tx_executed"] is False
    assert plan["join_allowed"] is False
    assert plan["join_executed"] is False
    assert plan["lorawan_uplink_allowed"] is False
    assert plan["lorawan_uplink_executed"] is False
    assert plan["generated_join_or_send_commands"] is False
    assert plan["at_join_command_generated"] is False
    assert plan["at_send_command_generated"] is False
    assert plan["safety_api_called"] is False
    assert plan["oled_status_updates"][0]["write_status"] == "dry_run"
    assert "PLAN READY" in plan["oled_status_updates"][0]["message"]
    assert "NO RF TX" in plan["oled_status_updates"][0]["message"]
    assert plan["led_status_updates"][0]["bits"] == "0x080"


def test_ready_evidence_without_approval_waits_for_operator(tmp_path: Path) -> None:
    wio = tmp_path / "wio.jsonl"
    rx = tmp_path / "rx.jsonl"
    output = tmp_path / "plan.jsonl"
    write_jsonl(wio, wio_records())
    write_jsonl(rx, gateway_rx_records())

    result = run_cli("--wio-at-jsonl", str(wio), "--gateway-rx-jsonl", str(rx), "--output-jsonl", str(output))

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["status"] == "waiting_for_operator_approval"
    assert plan["operator_approval_recorded"] is False
    assert plan["required_operator_approval_phrase"] == APPROVAL_TOKEN
    assert "separate approved step" in " ".join(plan["next_manual_actions"])
    assert led_bits_for_plan(plan, blocked_bit=1, wait_approval_bit=2, ready_bit=8) == 0x002
    assert plan["rf_tx_allowed"] == boundary_fields()["rf_tx_allowed"]


def test_missing_or_zero_identity_blocks_plan(tmp_path: Path) -> None:
    wio = tmp_path / "wio.jsonl"
    rx = tmp_path / "rx.jsonl"
    output = tmp_path / "plan.jsonl"
    write_jsonl(
        wio,
        [
            {
                "captured_at": "2026-07-06T04:00:01+00:00",
                "command": "AT+ID",
                "response_lines": ["+ID: DevEui, 00:00:00:00:00:00:00:00", "+AT: OK"],
                "response_status": "ok",
            }
        ],
    )
    write_jsonl(rx, gateway_rx_records())

    result = run_cli(
        "--wio-at-jsonl",
        str(wio),
        "--gateway-rx-jsonl",
        str(rx),
        "--output-jsonl",
        str(output),
        "--operator-approval-token",
        APPROVAL_TOKEN,
    )

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["status"] == "blocked_missing_readiness"
    assert plan["wio_at_summary"]["status"] == "wio_identity_incomplete"
    assert plan["wio_at_summary"]["nonzero_dev_eui_present"] is False
    assert "wio_identity_incomplete" in plan["blockers"]


def test_invalid_frequency_fails_cleanly() -> None:
    result = run_cli("--frequency-hz", "915000000")

    assert result.returncode == 2
    assert "frequency must be within Taiwan 920000000-925000000 Hz planning boundary" in result.stderr


def test_parse_helpers() -> None:
    assert parse_frequency_hz("923_200_000") == 923_200_000
    assert normalize_eui("2C:F7:F1:20:74:50:59:B5") == "2c:f7:f1:20:74:50:59:b5"
    assert normalize_eui("2cf7f120745059b5") == "2c:f7:f1:20:74:50:59:b5"
    assert normalize_eui("bad") is None
