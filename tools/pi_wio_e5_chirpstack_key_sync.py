#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
    from tools.pi_wio_e5_chirpstack_as9232_profile_provision import (
        compact_eui,
        extract_wio_identity,
        hash_identifier,
        parse_bool,
        read_jsonl,
        run_psql_query,
        sql_literal,
    )
    from tools.pi_wio_e5_lorawan_at_smoke import DEFAULT_BAUD, DEFAULT_PORT, make_at_session, response_status_from_lines
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display
    from pi_wio_e5_chirpstack_as9232_profile_provision import (
        compact_eui,
        extract_wio_identity,
        hash_identifier,
        parse_bool,
        read_jsonl,
        run_psql_query,
        sql_literal,
    )
    from pi_wio_e5_lorawan_at_smoke import DEFAULT_BAUD, DEFAULT_PORT, make_at_session, response_status_from_lines


SOURCE = "pi_wio_e5_chirpstack_key_sync"
HARDWARE_KIND = "wio_e5_chirpstack_otaa_key_sync"
DEFAULT_WIO_AT_JSONL = Path("/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl")
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-key-sync.jsonl")
DEFAULT_POSTGRES_CONTAINER = "chirpstack-docker-postgres-1"
DEFAULT_POSTGRES_USER = "chirpstack"
DEFAULT_POSTGRES_DB = "chirpstack"
DEFAULT_APPROVAL_TOKEN = "I_ACCEPT_LORAWAN_KEY_SYNC_AS923_2"
DEFAULT_TARGET_REGION = "AS923_2"
DEFAULT_TARGET_REGION_CONFIG_ID = "as923_2"
DEFAULT_LED_READY_BIT = 8
DEFAULT_LED_SYNCED_BIT = 9
DEFAULT_LED_BLOCKED_BIT = 10
ROOT_KEY_RE = re.compile(r"^[0-9a-fA-F]{32}$")


@dataclass(frozen=True)
class KeyState:
    dev_eui: str
    join_eui: str
    device_name: str
    is_disabled: str
    profile_name: str
    profile_region: str
    profile_region_config_id: str
    mac_version: str
    reg_params_revision: str
    supports_otaa: str
    nwk_key_present_value: str
    nwk_key_hex: str
    app_key_present_value: str
    app_key_hex: str

    @property
    def nwk_key_present(self) -> bool:
        return parse_bool(self.nwk_key_present_value) or bool(self.nwk_key_hex)

    @property
    def app_key_present(self) -> bool:
        return parse_bool(self.app_key_present_value) or bool(self.app_key_hex)


@dataclass(frozen=True)
class AtWriteResult:
    command_index: int
    command: str
    response_lines: list[str]
    response_status: str
    elapsed_ms: int
    command_executed: bool
    error: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def key_fingerprint(key_hex: str | None) -> str | None:
    if not key_hex:
        return None
    return "sha256:" + hashlib.sha256(key_hex.lower().encode("ascii")).hexdigest()[:16]


def normalize_key_hex(value: str) -> str:
    normalized = "".join(value.strip().split()).lower()
    if not ROOT_KEY_RE.fullmatch(normalized):
        raise ValueError("LoRaWAN root key must be 16 bytes / 32 hex characters")
    return normalized


def parse_positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def boundary_fields(
    *,
    execute: bool,
    serial_write_performed: bool,
    postgres_write_performed: bool,
    chirpstack_keys_changed: bool,
    scope: str,
) -> dict[str, Any]:
    mutation_performed = serial_write_performed or postgres_write_performed
    return {
        "read_only": not mutation_performed,
        "execute_requested": execute,
        "serial_write_performed": serial_write_performed,
        "wio_module_state_changed": serial_write_performed,
        "postgres_write_performed": postgres_write_performed,
        "chirpstack_config_changed": chirpstack_keys_changed,
        "device_registry_changed": chirpstack_keys_changed,
        "device_keys_changed": chirpstack_keys_changed,
        "rf_tx_allowed": False,
        "rf_tx_executed": False,
        "join_allowed": False,
        "join_executed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "lorawan_uplink_executed": False,
        "mqtt_publish_performed": False,
        "operator_approval_required": True,
        "approval_token_stored": False,
        "operator_approval_token_stored": False,
        "root_key_printed": False,
        "raw_key_embedded": False,
        "raw_identity_embedded": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "outbound_send_performed": False,
        "hardware_control_scope": scope,
    }


def key_query_sql(dev_eui_hex: str, *, include_raw_keys: bool) -> str:
    dev = sql_literal(dev_eui_hex)
    nwk_key_expr = "case when dk.nwk_key is null then '' else encode(dk.nwk_key, 'hex') end" if include_raw_keys else "''"
    app_key_expr = "case when dk.app_key is null then '' else encode(dk.app_key, 'hex') end" if include_raw_keys else "''"
    return f"""
select encode(d.dev_eui, 'hex'), encode(d.join_eui, 'hex'), d.name, d.is_disabled,
       dp.name, dp.region, dp.region_config_id, dp.mac_version,
       dp.reg_params_revision, dp.supports_otaa,
       (dk.nwk_key is not null),
       {nwk_key_expr},
       (dk.app_key is not null),
       {app_key_expr}
from device d
left join device_keys dk on dk.dev_eui = d.dev_eui
left join device_profile dp on dp.id = d.device_profile_id
where d.dev_eui = decode({dev}, 'hex')
limit 1;
""".strip()


def parse_key_state_output(text: str) -> KeyState | None:
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = (line.split("|") + [""] * 14)[:14]
        return KeyState(
            dev_eui=parts[0],
            join_eui=parts[1],
            device_name=parts[2],
            is_disabled=parts[3],
            profile_name=parts[4],
            profile_region=parts[5],
            profile_region_config_id=parts[6],
            mac_version=parts[7],
            reg_params_revision=parts[8],
            supports_otaa=parts[9],
            nwk_key_present_value=parts[10],
            nwk_key_hex=parts[11].lower(),
            app_key_present_value=parts[12],
            app_key_hex=parts[13].lower(),
        )
    return None


def summarize_key_state(state: KeyState | None, *, wio_identity: dict[str, Any], target_key_hex: str | None, hash_salt: str) -> dict[str, Any]:
    if state is None:
        return {
            "found": False,
            "raw_identity_embedded": False,
            "raw_key_embedded": False,
        }
    nwk_matches_target = bool(target_key_hex) and state.nwk_key_hex.lower() == target_key_hex.lower()
    app_matches_target = bool(target_key_hex) and state.app_key_hex.lower() == target_key_hex.lower()
    return {
        "found": True,
        "dev_eui_hash": hash_identifier(state.dev_eui, salt=hash_salt),
        "join_eui_hash": hash_identifier(state.join_eui, salt=hash_salt),
        "dev_eui_matches_wio": compact_eui(state.dev_eui) == compact_eui(wio_identity.get("dev_eui")),
        "join_eui_matches_wio_app_eui": compact_eui(state.join_eui) == compact_eui(wio_identity.get("app_eui")),
        "device_name_present": bool(state.device_name),
        "is_disabled": parse_bool(state.is_disabled),
        "profile_name": state.profile_name,
        "profile_region": state.profile_region,
        "profile_region_config_id": state.profile_region_config_id,
        "mac_version": state.mac_version,
        "reg_params_revision": state.reg_params_revision,
        "supports_otaa": parse_bool(state.supports_otaa),
        "nwk_key_present": state.nwk_key_present,
        "app_key_present": state.app_key_present,
        "nwk_key_fingerprint": key_fingerprint(state.nwk_key_hex),
        "app_key_fingerprint": key_fingerprint(state.app_key_hex),
        "nwk_key_matches_target": nwk_matches_target,
        "app_key_matches_target": app_matches_target,
        "raw_identity_embedded": False,
        "raw_key_embedded": False,
    }


def select_existing_chirpstack_root_key(state: KeyState | None) -> tuple[str | None, str | None]:
    if state is None:
        return None, None
    if state.nwk_key_hex:
        return state.nwk_key_hex, "nwk_key"
    if state.app_key_hex:
        return state.app_key_hex, "app_key"
    return None, None


def key_sources_requested(args: argparse.Namespace) -> list[str]:
    sources: list[str] = []
    if args.key_hex:
        sources.append("key_hex")
    if args.key_file:
        sources.append("key_file")
    if args.key_env_var:
        sources.append("key_env_var")
    if args.generate_key:
        sources.append("generate_key")
    if args.use_existing_chirpstack_key:
        sources.append("existing_chirpstack_key")
    return sources


def load_external_key(args: argparse.Namespace) -> tuple[str | None, str | None]:
    if args.key_hex:
        return normalize_key_hex(args.key_hex), "key_hex"
    if args.key_file:
        return normalize_key_hex(args.key_file.read_text(encoding="utf-8")), "key_file"
    if args.key_env_var:
        value = os.environ.get(args.key_env_var)
        if value is None:
            raise ValueError(f"environment variable {args.key_env_var} is not set")
        return normalize_key_hex(value), "key_env_var"
    if args.generate_key:
        return secrets.token_hex(16), "generate_key"
    return None, None


def decide_plan(
    *,
    wio_identity: dict[str, Any],
    state: KeyState | None,
    key_source: str | None,
    target_key_hex: str | None,
    target_region: str,
    target_region_config_id: str,
) -> tuple[str, str, list[str]]:
    if not wio_identity["dev_eui_present"] or not wio_identity["app_eui_present"]:
        return "blocked_missing_wio_identity", "none", ["rerun Wio-E5 read-only AT identity smoke"]
    if key_source is None or target_key_hex is None:
        return "blocked_missing_key_source", "none", ["rerun with --use-existing-chirpstack-key, --generate-key, --key-file, or --key-env-var"]
    if state is None:
        return "blocked_device_not_registered", "none", ["register the Wio-E5 DevEUI in ChirpStack first"]
    if compact_eui(state.join_eui) != compact_eui(wio_identity.get("app_eui")):
        return "blocked_join_eui_mismatch", "none", ["align ChirpStack JoinEUI/AppEUI before changing keys"]
    if parse_bool(state.is_disabled):
        return "blocked_device_disabled", "none", ["enable the ChirpStack device before key sync"]
    if state.profile_region.upper() != target_region.upper() or state.profile_region_config_id.lower() != target_region_config_id.lower():
        return "blocked_profile_not_as9232", "none", ["align the device profile to AS923_2 before key sync"]
    if state.nwk_key_hex.lower() == target_key_hex.lower() and state.app_key_hex.lower() == target_key_hex.lower():
        return "ready_for_wio_key_reapply", "wio_e5_appkey_only", ["write the same ChirpStack root key to the Wio-E5 APPKEY"]
    return "ready_for_key_sync", "chirpstack_device_keys_and_wio_e5_appkey", ["update ChirpStack device_keys and write Wio-E5 APPKEY"]


def build_key_update_sql(dev_eui_hex: str, root_key_hex: str) -> str:
    dev = sql_literal(dev_eui_hex)
    root_key = sql_literal(root_key_hex)
    return f"""
update device_keys
set nwk_key = decode({root_key}, 'hex'),
    app_key = decode({root_key}, 'hex'),
    updated_at = now()
where dev_eui = decode({dev}, 'hex');
""".strip()


def parse_mutation_count(text: str) -> int:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.isdigit():
            return int(stripped)
    match = re.search(r"(?:UPDATE|INSERT)\s+\d+\s+(\d+)", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"UPDATE\s+(\d+)", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def sanitize_key_text(value: str, root_key_hex: str) -> str:
    return re.sub(re.escape(root_key_hex), "<redacted-root-key>", value, flags=re.IGNORECASE)


def build_wio_key_command(root_key_hex: str) -> str:
    return f'AT+KEY=APPKEY,"{root_key_hex.upper()}"'


def redacted_wio_key_command() -> str:
    return 'AT+KEY=APPKEY,"<redacted-root-key>"'


def run_wio_key_write(
    *,
    port: str,
    baud: int,
    root_key_hex: str,
    command_timeout_seconds: float,
    quiet_seconds: float,
    dry_run: bool,
    mutation_fixture_output: str | None,
) -> tuple[list[AtWriteResult], str | None]:
    if dry_run:
        return [
            AtWriteResult(
                command_index=0,
                command="AT",
                response_lines=["+AT: OK"],
                response_status="ok",
                elapsed_ms=0,
                command_executed=False,
            ),
            AtWriteResult(
                command_index=1,
                command=redacted_wio_key_command(),
                response_lines=["+KEY: APPKEY <redacted-root-key>", "+AT: OK"],
                response_status="ok",
                elapsed_ms=0,
                command_executed=False,
            ),
        ], None
    if mutation_fixture_output is not None:
        sanitized_lines = [sanitize_key_text(line, root_key_hex) for line in mutation_fixture_output.splitlines() if line.strip()]
        return [
            AtWriteResult(
                command_index=1,
                command=redacted_wio_key_command(),
                response_lines=sanitized_lines,
                response_status=response_status_from_lines(sanitized_lines),
                elapsed_ms=0,
                command_executed=True,
            )
        ], None

    session = make_at_session(port=port, baud=baud)
    results: list[AtWriteResult] = []
    try:
        for index, command in enumerate(["AT", build_wio_key_command(root_key_hex)]):
            started_at = time.monotonic()
            try:
                lines = session.transact(
                    command=command,
                    timeout_seconds=command_timeout_seconds,
                    quiet_seconds=quiet_seconds,
                )
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                sanitized_lines = [sanitize_key_text(line, root_key_hex) for line in lines]
                results.append(
                    AtWriteResult(
                        command_index=index,
                        command="AT" if command == "AT" else redacted_wio_key_command(),
                        response_lines=sanitized_lines,
                        response_status=response_status_from_lines(sanitized_lines),
                        elapsed_ms=elapsed_ms,
                        command_executed=True,
                    )
                )
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                results.append(
                    AtWriteResult(
                        command_index=index,
                        command="AT" if command == "AT" else redacted_wio_key_command(),
                        response_lines=[],
                        response_status="error",
                        elapsed_ms=elapsed_ms,
                        command_executed=True,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                return results, f"{type(exc).__name__}: {exc}"
        return results, None
    finally:
        session.close()


def summarize_at_results(results: Sequence[AtWriteResult]) -> list[dict[str, Any]]:
    return [
        {
            "command_index": result.command_index,
            "command": result.command,
            "response_lines": result.response_lines,
            "response_status": result.response_status,
            "elapsed_ms": result.elapsed_ms,
            "command_executed": result.command_executed,
            **({"error": result.error} if result.error else {}),
        }
        for result in results
    ]


def led_bits_for_status(status: str, *, ready_bit: int, synced_bit: int, blocked_bit: int) -> int:
    if status in {"key_sync_applied", "wio_key_reapplied"}:
        bit = synced_bit
    elif status.startswith("ready"):
        bit = ready_bit
    else:
        bit = blocked_bit
    return 1 << (bit - 1)


def write_oled_status(
    *,
    enabled: bool,
    dry_run: bool,
    bus: str,
    address: str,
    driver: str,
    status: str,
    key_source: str | None,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    if status in {"key_sync_applied", "wio_key_reapplied"}:
        line2 = "KEY SYNCED"
    elif status.startswith("ready"):
        line2 = "KEY READY"
    else:
        line2 = "KEY BLOCK"
    source_line = (key_source or "NO KEY").replace("_", " ").upper()[:16]
    message = "\n".join(["SCOUT LORA KEY", line2, source_line, "NO RF TX"])
    try:
        parsed_address = parse_address(address)
        if dry_run:
            write_status = "dry_run"
        else:
            write_display(bus=Path(bus), address=parsed_address, driver=driver, message=message)
            write_status = "ok"
    except Exception as exc:  # pragma: no cover - hardware path.
        write_status = "error"
        error = str(exc)
    else:
        error = None
    payload = {
        "captured_at": now_iso(),
        "source": f"{SOURCE}_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": bus,
        "address": address,
        "driver": driver,
        "message": message,
        "write_status": write_status,
        "dry_run": dry_run,
        **boundary_fields(
            execute=False,
            serial_write_performed=False,
            postgres_write_performed=False,
            chirpstack_keys_changed=False,
            scope="diagnostic_key_sync_visual_status_only",
        ),
    }
    if error:
        payload["error"] = error
    return [payload]


def write_led_status(
    *,
    enabled: bool,
    dry_run: bool,
    port: str,
    data_gpio: int | None,
    clock_gpio: int | None,
    status: str,
    ready_bit: int,
    synced_bit: int,
    blocked_bit: int,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    defaults = PORT_DEFAULTS.get(port, PORT_DEFAULTS[DEFAULT_LED_PORT])
    resolved_data = data_gpio if data_gpio is not None else defaults["data_gpio"]
    resolved_clock = clock_gpio if clock_gpio is not None else defaults["clock_gpio"]
    bits = led_bits_for_status(status, ready_bit=ready_bit, synced_bit=synced_bit, blocked_bit=blocked_bit)
    write_status = "dry_run"
    error = None
    if not dry_run:
        try:
            writer = make_gpio_writer()
            for _ in range(2):
                write_led_bar_bits(writer, data_gpio=resolved_data, clock_gpio=resolved_clock, bits=bits)
                time.sleep(0.25)
                clear_led_bar(writer, data_gpio=resolved_data, clock_gpio=resolved_clock)
                time.sleep(0.25)
            writer.close()
            write_status = "ok"
        except Exception as exc:  # pragma: no cover - hardware path.
            write_status = "error"
            error = str(exc)
    payload = {
        "captured_at": now_iso(),
        "source": f"{SOURCE}_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": resolved_data,
        "clock_gpio": resolved_clock,
        "bits": f"0x{bits:03x}",
        "ready_led_bit": ready_bit,
        "synced_led_bit": synced_bit,
        "blocked_led_bit": blocked_bit,
        "write_status": write_status,
        "dry_run": dry_run,
        **boundary_fields(
            execute=False,
            serial_write_performed=False,
            postgres_write_performed=False,
            chirpstack_keys_changed=False,
            scope="diagnostic_key_sync_visual_status_only",
        ),
    }
    if error:
        payload["error"] = error
    return [payload]


def query_or_fixture(
    fixture: str | None,
    sql: str,
    *,
    container: str,
    postgres_user: str,
    postgres_db: str,
    timeout_seconds: float,
) -> tuple[str, str | None, int | None, bool]:
    if fixture is not None:
        return fixture, None, 0, True
    text, error, returncode = run_psql_query(
        sql,
        container=container,
        postgres_user=postgres_user,
        postgres_db=postgres_db,
        timeout_seconds=timeout_seconds,
    )
    return text, error, returncode, False


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize Wio-E5 APPKEY and ChirpStack OTAA root keys without RF transmit.")
    parser.add_argument("--wio-at-jsonl", type=Path, default=DEFAULT_WIO_AT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--device-port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--postgres-container", default=DEFAULT_POSTGRES_CONTAINER)
    parser.add_argument("--postgres-user", default=DEFAULT_POSTGRES_USER)
    parser.add_argument("--postgres-db", default=DEFAULT_POSTGRES_DB)
    parser.add_argument("--target-region", default=DEFAULT_TARGET_REGION)
    parser.add_argument("--target-region-config-id", default=DEFAULT_TARGET_REGION_CONFIG_ID)
    parser.add_argument("--key-hex", default="", help="32-hex test/dev key source; prefer --key-file or --generate-key outside tests.")
    parser.add_argument("--key-file", type=Path, default=None)
    parser.add_argument("--key-env-var", default="")
    parser.add_argument("--generate-key", action="store_true")
    parser.add_argument("--use-existing-chirpstack-key", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--operator-approval-token", default="")
    parser.add_argument("--required-operator-approval-token", default=DEFAULT_APPROVAL_TOKEN)
    parser.add_argument("--hash-salt", default=SOURCE)
    parser.add_argument("--command-timeout-seconds", type=parse_positive_float, default=5.0)
    parser.add_argument("--quiet-seconds", type=parse_non_negative_float, default=0.25)
    parser.add_argument("--device-query-output", default=None, help="Fixture output for tests; disables live device key query.")
    parser.add_argument("--postgres-mutation-output", default=None, help="Fixture mutation output for tests; disables live Postgres mutation.")
    parser.add_argument("--wio-mutation-output", default=None, help="Fixture Wio-E5 AT output for tests; disables live serial mutation.")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--oled-bus", default="/dev/i2c-1")
    parser.add_argument("--oled-address", default="0x3c")
    parser.add_argument("--oled-driver", default="sh1107g")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-dry-run", action="store_true")
    parser.add_argument("--led-port", default=DEFAULT_LED_PORT, choices=sorted(PORT_DEFAULTS))
    parser.add_argument("--data-gpio", type=int, default=None)
    parser.add_argument("--clock-gpio", type=int, default=None)
    parser.add_argument("--led-ready-bit", type=parse_led_bit, default=DEFAULT_LED_READY_BIT)
    parser.add_argument("--led-synced-bit", type=parse_led_bit, default=DEFAULT_LED_SYNCED_BIT)
    parser.add_argument("--led-blocked-bit", type=parse_led_bit, default=DEFAULT_LED_BLOCKED_BIT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    wio_records, wio_invalid_count, wio_file_exists = read_jsonl(args.wio_at_jsonl)
    wio_identity = extract_wio_identity(wio_records, hash_salt=args.hash_salt)
    dev_eui_hex = compact_eui(wio_identity.get("dev_eui"))
    sources = key_sources_requested(args)
    approval_valid = args.operator_approval_token == args.required_operator_approval_token
    include_raw_chirpstack_keys = args.use_existing_chirpstack_key and args.execute and approval_valid
    key_source_error = None
    external_key: str | None = None
    external_key_source: str | None = None

    if len(sources) > 1:
        key_source_error = "exactly one key source is allowed"
    elif args.use_existing_chirpstack_key:
        external_key_source = "existing_chirpstack_key"
    else:
        try:
            external_key, external_key_source = load_external_key(args)
        except Exception as exc:
            key_source_error = f"{type(exc).__name__}: {exc}"

    state = None
    device_query_error = None
    device_query_fixture_used = False
    if dev_eui_hex:
        text, device_query_error, _, device_query_fixture_used = query_or_fixture(
            args.device_query_output,
            key_query_sql(dev_eui_hex, include_raw_keys=include_raw_chirpstack_keys),
            container=args.postgres_container,
            postgres_user=args.postgres_user,
            postgres_db=args.postgres_db,
            timeout_seconds=args.command_timeout_seconds,
        )
        if device_query_error is None:
            state = parse_key_state_output(text)

    selected_existing_key = None
    selected_existing_key_field = None
    if args.use_existing_chirpstack_key and key_source_error is None:
        if not include_raw_chirpstack_keys:
            key_source_error = "reading an existing ChirpStack root key requires --execute and operator approval"
        else:
            selected_existing_key, selected_existing_key_field = select_existing_chirpstack_root_key(state)
        if key_source_error is None and selected_existing_key is None:
            key_source_error = "ChirpStack device has no existing nwk_key or app_key to reuse"
        elif selected_existing_key is not None:
            external_key = selected_existing_key
            external_key_source = "existing_chirpstack_key"

    if key_source_error is not None:
        status = "blocked_key_source_error"
        mutation_scope = "none"
        next_actions = [key_source_error]
        target_key_hex = None
    else:
        target_key_hex = external_key
        status, mutation_scope, next_actions = decide_plan(
            wio_identity=wio_identity,
            state=state,
            key_source=external_key_source,
            target_key_hex=target_key_hex,
            target_region=args.target_region,
            target_region_config_id=args.target_region_config_id,
        )

    postgres_mutation_attempted = False
    postgres_write_performed = False
    postgres_mutation_error = None
    postgres_mutation_count = 0
    wio_write_attempted = False
    serial_write_performed = False
    wio_write_error = None
    wio_results: list[AtWriteResult] = []

    if args.execute:
        if not approval_valid:
            status = "blocked_missing_operator_approval"
            mutation_scope = "none"
            next_actions = [f"rerun with {args.required_operator_approval_token} after confirming the planned key sync"]
        elif status not in {"ready_for_key_sync", "ready_for_wio_key_reapply"} or target_key_hex is None or dev_eui_hex is None:
            mutation_scope = "none"
        else:
            if status == "ready_for_key_sync":
                postgres_mutation_attempted = True
                if args.dry_run:
                    postgres_mutation_count = 0
                elif args.postgres_mutation_output is not None:
                    postgres_mutation_error = None
                    postgres_mutation_count = parse_mutation_count(args.postgres_mutation_output)
                else:
                    mutation_text, postgres_mutation_error, mutation_returncode = run_psql_query(
                        build_key_update_sql(dev_eui_hex, target_key_hex),
                        container=args.postgres_container,
                        postgres_user=args.postgres_user,
                        postgres_db=args.postgres_db,
                        timeout_seconds=args.command_timeout_seconds,
                    )
                    if postgres_mutation_error is not None:
                        postgres_mutation_error = sanitize_key_text(postgres_mutation_error, target_key_hex)
                    if postgres_mutation_error is None and mutation_returncode in {0, None}:
                        postgres_mutation_count = parse_mutation_count(mutation_text)
                postgres_write_performed = postgres_mutation_count == 1 and not args.dry_run
                if postgres_mutation_error is not None or (not args.dry_run and postgres_mutation_count != 1):
                    status = "postgres_key_sync_error"
                    next_actions = ["inspect ChirpStack Postgres device_keys mutation before touching the Wio-E5"]

            if status in {"ready_for_key_sync", "ready_for_wio_key_reapply"}:
                wio_write_attempted = True
                wio_results, wio_write_error = run_wio_key_write(
                    port=args.device_port,
                    baud=args.baud,
                    root_key_hex=target_key_hex,
                    command_timeout_seconds=args.command_timeout_seconds,
                    quiet_seconds=args.quiet_seconds,
                    dry_run=args.dry_run,
                    mutation_fixture_output=args.wio_mutation_output,
                )
                serial_write_performed = (
                    not args.dry_run
                    and wio_write_error is None
                    and bool(wio_results)
                    and all(result.response_status == "ok" for result in wio_results)
                    and any(result.command_executed for result in wio_results)
                )
                if not serial_write_performed and not args.dry_run:
                    status = "wio_key_write_error"
                    next_actions = ["rerun with --use-existing-chirpstack-key after serial path is stable"]
                elif args.dry_run:
                    status = "dry_run_key_sync_not_applied"
                    next_actions = ["rerun without --dry-run to apply the key sync"]
                elif mutation_scope == "wio_e5_appkey_only":
                    status = "wio_key_reapplied"
                    next_actions = ["start no-tx packet forwarder before the next single join trial"]
                else:
                    status = "key_sync_applied"
                    next_actions = ["rerun read-only key sync audit", "start no-tx packet forwarder before the next single join trial"]

    chirpstack_keys_changed = postgres_write_performed
    payload = {
        "captured_at": now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "target_region": args.target_region,
        "target_region_config_id": args.target_region_config_id,
        "device_port": args.device_port,
        "baud": args.baud,
        "key_source": external_key_source,
        "key_source_error": key_source_error,
        "selected_existing_chirpstack_key_field": selected_existing_key_field,
        "target_key_fingerprint": key_fingerprint(target_key_hex),
        "key_length_bytes": 16 if target_key_hex else None,
        "wio_at_summary": {
            "path": str(args.wio_at_jsonl),
            "file_exists": wio_file_exists,
            "record_count_scanned": len(wio_records),
            "invalid_json_line_count": wio_invalid_count,
            "dev_eui_present": wio_identity["dev_eui_present"],
            "dev_eui_hash": wio_identity["dev_eui_hash"],
            "app_eui_present": wio_identity["app_eui_present"],
            "app_eui_hash": wio_identity["app_eui_hash"],
            "raw_identity_embedded": False,
        },
        "device_key_query": {
            "attempted": dev_eui_hex is not None,
            "fixture_used": device_query_fixture_used,
            "error": device_query_error,
        },
        "device_keys_before": summarize_key_state(
            state,
            wio_identity=wio_identity,
            target_key_hex=target_key_hex,
            hash_salt=args.hash_salt,
        ),
        "postgres_mutation_attempted": postgres_mutation_attempted,
        "postgres_mutation_count": postgres_mutation_count,
        "postgres_mutation_error": postgres_mutation_error,
        "wio_write_attempted": wio_write_attempted,
        "wio_write_error": wio_write_error,
        "wio_command_results": summarize_at_results(wio_results),
        "mutation_scope": mutation_scope if (serial_write_performed or postgres_write_performed) else "none",
        "next_actions": next_actions,
        **boundary_fields(
            execute=args.execute,
            serial_write_performed=serial_write_performed,
            postgres_write_performed=postgres_write_performed,
            chirpstack_keys_changed=chirpstack_keys_changed,
            scope="operator_approved_lorawan_otaa_key_sync_no_rf",
        ),
    }
    payload["oled_status_updates"] = write_oled_status(
        enabled=args.oled_status,
        dry_run=args.oled_dry_run,
        bus=args.oled_bus,
        address=args.oled_address,
        driver=args.oled_driver,
        status=status,
        key_source=external_key_source,
    )
    payload["led_status_updates"] = write_led_status(
        enabled=args.led_status,
        dry_run=args.led_dry_run,
        port=args.led_port,
        data_gpio=args.data_gpio,
        clock_gpio=args.clock_gpio,
        status=status,
        ready_bit=args.led_ready_bit,
        synced_bit=args.led_synced_bit,
        blocked_bit=args.led_blocked_bit,
    )
    append_jsonl(args.output_jsonl, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    ok_statuses = {"ready_for_key_sync", "ready_for_wio_key_reapply", "key_sync_applied", "wio_key_reapplied", "dry_run_key_sync_not_applied"}
    return 0 if status in ok_statuses else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
