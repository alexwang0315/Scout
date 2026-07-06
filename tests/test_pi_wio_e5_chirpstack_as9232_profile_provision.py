from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_chirpstack_as9232_profile_provision import (
    DEFAULT_APPROVAL_TOKEN,
    build_in_place_profile_update_sql,
    led_bits_for_status,
    parse_device_state_output,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_chirpstack_as9232_profile_provision.py"
DEV_EUI = "2C:F7:F1:20:74:50:59:B5"
DEV_EUI_COMPACT = "2cf7f120745059b5"
APP_EUI_COMPACT = "526973696e674846"
APP_KEY = "00112233445566778899aabbccddeeff"
PROFILE_ID = "11111111-1111-1111-1111-111111111111"
TARGET_PROFILE_ID = "22222222-2222-2222-2222-222222222222"


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8")


def wio_at_file(tmp_path: Path) -> Path:
    path = tmp_path / "wio-at.jsonl"
    write_jsonl(
        path,
        [
            {
                "source": "pi_wio_e5_lorawan_at_smoke",
                "command": "AT+ID",
                "response_lines": [
                    "+ID: DevAddr, 74:50:59:B5",
                    f"+ID: DevEui, {DEV_EUI}",
                    "+ID: AppEui, 52:69:73:69:6E:67:48:46",
                ],
            }
        ],
    )
    return path


def device_output(*, profile_count: int = 1, region: str = "AS923", config_id: str = "as923") -> str:
    return "|".join(
        [
            DEV_EUI_COMPACT,
            APP_EUI_COMPACT,
            "scout-wio-e5-client",
            "f",
            PROFILE_ID,
            "scout-wio-e5-as923-otaa",
            region,
            config_id,
            "1.0.4",
            "RP002-1.0.3",
            "t",
            "t",
            "t",
            APP_KEY,
            str(profile_count),
        ]
    )


def target_profile_output() -> str:
    return "|".join(
        [
            TARGET_PROFILE_ID,
            "scout-wio-e5-as923-2-otaa",
            "AS923_2",
            "as923_2",
            "1.0.4",
            "RP002-1.0.3",
            "t",
            "0",
        ]
    )


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def base_args(tmp_path: Path) -> list[str]:
    return [
        "--wio-at-jsonl",
        str(wio_at_file(tmp_path)),
        "--output-jsonl",
        str(tmp_path / "provision.jsonl"),
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
        "--device-query-output",
        device_output(),
    ]


def test_dry_run_plans_in_place_profile_update_without_mutation(tmp_path: Path) -> None:
    result = run_cli(*base_args(tmp_path), "--target-profiles-output", "", "--allow-in-place-profile-update")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready_for_in_place_profile_update"
    assert payload["postgres_write_performed"] is False
    assert payload["chirpstack_config_changed"] is False
    assert payload["device_registry_changed"] is False
    assert payload["approval_token_stored"] is False
    assert payload["device_profile_before"]["profile_region"] == "AS923"
    assert payload["device_profile_before"]["profile_region_config_id"] == "as923"
    assert payload["wio_at_summary"]["dev_eui_hash"].startswith("sha256:")
    assert DEV_EUI not in result.stdout
    assert DEV_EUI_COMPACT not in result.stdout
    assert APP_KEY not in result.stdout
    assert "READY" in payload["oled_status_updates"][0]["message"]
    assert payload["led_status_updates"][0]["bits"] == "0x080"


def test_execute_requires_operator_approval_token(tmp_path: Path) -> None:
    result = run_cli(
        *base_args(tmp_path),
        "--target-profiles-output",
        "",
        "--allow-in-place-profile-update",
        "--execute",
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked_missing_operator_approval"
    assert payload["mutation_attempted"] is False
    assert payload["postgres_write_performed"] is False
    assert payload["led_status_updates"][0]["bits"] == "0x200"


def test_execute_in_place_profile_update_records_mutation(tmp_path: Path) -> None:
    result = run_cli(
        *base_args(tmp_path),
        "--target-profiles-output",
        "",
        "--allow-in-place-profile-update",
        "--execute",
        "--operator-approval-token",
        DEFAULT_APPROVAL_TOKEN,
        "--mutation-output",
        "UPDATE 1",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "mutated_profile_aligned"
    assert payload["mutation_attempted"] is True
    assert payload["mutation_update_count"] == 1
    assert payload["postgres_write_performed"] is True
    assert payload["chirpstack_config_changed"] is True
    assert payload["device_registry_changed"] is True
    assert payload["profile_mutation_scope"] == "device_profile_in_place_update"
    assert payload["rf_tx_allowed"] is False
    assert payload["lorawan_uplink_allowed"] is False
    assert payload["safety_api_called"] is False
    assert payload["approval_token_stored"] is False


def test_switches_to_existing_target_profile_when_present(tmp_path: Path) -> None:
    result = run_cli(
        *base_args(tmp_path),
        "--target-profiles-output",
        target_profile_output(),
        "--execute",
        "--operator-approval-token",
        DEFAULT_APPROVAL_TOKEN,
        "--mutation-output",
        "UPDATE 1",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "mutated_profile_aligned"
    assert payload["target_profile_count"] == 1
    assert payload["profile_mutation_scope"] == "device_profile_switch"


def test_shared_profile_blocks_in_place_update(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    args[args.index("--device-query-output") + 1] = device_output(profile_count=2)

    result = run_cli(*args, "--target-profiles-output", "", "--allow-in-place-profile-update")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked_profile_shared"
    assert payload["postgres_write_performed"] is False


def test_already_aligned_is_non_mutating_success(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    args[args.index("--device-query-output") + 1] = device_output(region="AS923_2", config_id="as923_2")

    result = run_cli(*args, "--target-profiles-output", "")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "already_aligned"
    assert payload["mutation_attempted"] is False
    assert payload["chirpstack_config_changed"] is False
    assert "ALIGNED" in payload["oled_status_updates"][0]["message"]


def test_helpers_parse_device_and_build_guarded_sql() -> None:
    state = parse_device_state_output(device_output())
    sql = build_in_place_profile_update_sql(
        dev_eui_hex=DEV_EUI_COMPACT,
        current_profile_id=PROFILE_ID,
        target_region="AS923_2",
        target_region_config_id="as923_2",
        target_profile_name="scout-wio-e5-as923-2-otaa",
    )

    assert state is not None
    assert state.profile_device_count == 1
    assert "select count(*) from device" in sql.lower()
    assert "decode('2cf7f120745059b5', 'hex')" in sql
    assert led_bits_for_status("mutated_profile_aligned", ready_bit=8, changed_bit=9, blocked_bit=10) == 0x100
