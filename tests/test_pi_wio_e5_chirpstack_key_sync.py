from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.pi_wio_e5_chirpstack_key_sync import (
    DEFAULT_APPROVAL_TOKEN,
    build_key_update_sql,
    key_fingerprint,
    led_bits_for_status,
    normalize_key_hex,
    parse_key_state_output,
    parse_mutation_count,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "pi_wio_e5_chirpstack_key_sync.py"
DEV_EUI = "2C:F7:F1:20:74:50:59:B5"
DEV_EUI_COMPACT = "2cf7f120745059b5"
APP_EUI_COMPACT = "526973696e674846"
OLD_KEY = "00112233445566778899aabbccddeeff"
NEW_KEY = "fedcba98765432100123456789abcdef"


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


def key_state_output(
    *,
    region: str = "AS923_2",
    config_id: str = "as923_2",
    nwk_key: str = OLD_KEY,
    app_key: str = OLD_KEY,
    join_eui: str = APP_EUI_COMPACT,
    disabled: str = "f",
) -> str:
    return "|".join(
        [
            DEV_EUI_COMPACT,
            join_eui,
            "scout-wio-e5-client",
            disabled,
            "scout-wio-e5-as9232-otaa",
            region,
            config_id,
            "1.0.4",
            "RP002-1.0.3",
            "t",
            "t" if nwk_key else "f",
            nwk_key,
            "t" if app_key else "f",
            app_key,
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
        str(tmp_path / "key-sync.jsonl"),
        "--device-query-output",
        key_state_output(),
        "--oled-status",
        "--oled-dry-run",
        "--led-status",
        "--led-dry-run",
    ]


def test_dry_run_plans_key_sync_without_printing_raw_key(tmp_path: Path) -> None:
    result = run_cli(*base_args(tmp_path), "--key-hex", NEW_KEY)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ready_for_key_sync"
    assert payload["target_key_fingerprint"] == key_fingerprint(NEW_KEY)
    assert payload["postgres_write_performed"] is False
    assert payload["serial_write_performed"] is False
    assert payload["raw_key_embedded"] is False
    assert payload["root_key_printed"] is False
    assert NEW_KEY not in result.stdout
    assert OLD_KEY not in result.stdout
    assert "KEY READY" in payload["oled_status_updates"][0]["message"]
    assert payload["led_status_updates"][0]["bits"] == "0x080"


def test_execute_requires_operator_approval(tmp_path: Path) -> None:
    result = run_cli(*base_args(tmp_path), "--key-hex", NEW_KEY, "--execute")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked_missing_operator_approval"
    assert payload["postgres_write_performed"] is False
    assert payload["serial_write_performed"] is False
    assert payload["led_status_updates"][0]["bits"] == "0x200"


def test_execute_updates_chirpstack_and_wio_with_redacted_at_output(tmp_path: Path) -> None:
    result = run_cli(
        *base_args(tmp_path),
        "--key-hex",
        NEW_KEY,
        "--execute",
        "--operator-approval-token",
        DEFAULT_APPROVAL_TOKEN,
        "--postgres-mutation-output",
        "1",
        "--wio-mutation-output",
        f"+KEY: APPKEY {NEW_KEY.upper()}\n+AT: OK",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "key_sync_applied"
    assert payload["postgres_write_performed"] is True
    assert payload["serial_write_performed"] is True
    assert payload["chirpstack_config_changed"] is True
    assert payload["device_keys_changed"] is True
    assert payload["wio_module_state_changed"] is True
    assert payload["rf_tx_allowed"] is False
    assert payload["join_executed"] is False
    assert payload["lorawan_uplink_executed"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["safety_api_called"] is False
    assert payload["approval_token_stored"] is False
    assert payload["wio_command_results"][0]["command"] == 'AT+KEY=APPKEY,"<redacted-root-key>"'
    assert "<redacted-root-key>" in payload["wio_command_results"][0]["response_lines"][0]
    assert NEW_KEY not in result.stdout
    assert OLD_KEY not in result.stdout


def test_use_existing_chirpstack_key_reapplies_wio_only(tmp_path: Path) -> None:
    result = run_cli(
        *base_args(tmp_path),
        "--use-existing-chirpstack-key",
        "--execute",
        "--operator-approval-token",
        DEFAULT_APPROVAL_TOKEN,
        "--wio-mutation-output",
        f"+KEY: APPKEY {OLD_KEY.upper()}\n+AT: OK",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "wio_key_reapplied"
    assert payload["key_source"] == "existing_chirpstack_key"
    assert payload["selected_existing_chirpstack_key_field"] == "nwk_key"
    assert payload["postgres_write_performed"] is False
    assert payload["serial_write_performed"] is True
    assert payload["chirpstack_config_changed"] is False
    assert payload["target_key_fingerprint"] == key_fingerprint(OLD_KEY)
    assert OLD_KEY not in result.stdout


def test_blocks_when_profile_is_not_as9232(tmp_path: Path) -> None:
    args = base_args(tmp_path)
    args[args.index("--device-query-output") + 1] = key_state_output(region="AS923", config_id="as923")

    result = run_cli(*args, "--key-hex", NEW_KEY)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked_profile_not_as9232"
    assert payload["postgres_write_performed"] is False
    assert payload["serial_write_performed"] is False


def test_blocks_missing_or_ambiguous_key_source(tmp_path: Path) -> None:
    missing = run_cli(*base_args(tmp_path))
    ambiguous = run_cli(*base_args(tmp_path), "--key-hex", NEW_KEY, "--generate-key")

    assert missing.returncode == 1
    assert json.loads(missing.stdout)["status"] == "blocked_missing_key_source"
    assert ambiguous.returncode == 1
    assert json.loads(ambiguous.stdout)["status"] == "blocked_key_source_error"


def test_helpers_validate_key_sql_and_led_mapping() -> None:
    state = parse_key_state_output(key_state_output())
    sql = build_key_update_sql(DEV_EUI_COMPACT, NEW_KEY)

    assert state is not None
    assert state.nwk_key_hex == OLD_KEY
    assert normalize_key_hex("FE DC BA 98 76 54 32 10 01 23 45 67 89 AB CD EF") == NEW_KEY
    assert "update device_keys" in sql.lower()
    assert "set nwk_key" in sql.lower()
    assert DEV_EUI_COMPACT in sql
    assert NEW_KEY in sql
    assert parse_mutation_count("1") == 1
    assert parse_mutation_count("INSERT 0 1") == 1
    assert led_bits_for_status("key_sync_applied", ready_bit=8, synced_bit=9, blocked_bit=10) == 0x100
