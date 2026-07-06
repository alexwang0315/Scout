#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
    from tools.pi_wio_e5_lorawan_uplink_trial_plan import normalize_eui
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display
    from pi_wio_e5_lorawan_uplink_trial_plan import normalize_eui


SOURCE = "pi_wio_e5_chirpstack_as9232_profile_provision"
HARDWARE_KIND = "wio_e5_chirpstack_profile_provision"
DEFAULT_WIO_AT_JSONL = Path("/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl")
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-profile-provision.jsonl")
DEFAULT_POSTGRES_CONTAINER = "chirpstack-docker-postgres-1"
DEFAULT_POSTGRES_USER = "chirpstack"
DEFAULT_POSTGRES_DB = "chirpstack"
DEFAULT_TARGET_REGION = "AS923_2"
DEFAULT_TARGET_REGION_CONFIG_ID = "as923_2"
DEFAULT_TARGET_PROFILE_NAME = "scout-wio-e5-as923-2-otaa"
DEFAULT_APPROVAL_TOKEN = "I_ACCEPT_CHIRPSTACK_PROFILE_MUTATION_AS923_2"
DEFAULT_LED_READY_BIT = 8
DEFAULT_LED_CHANGED_BIT = 9
DEFAULT_LED_BLOCKED_BIT = 10


@dataclass(frozen=True)
class DeviceProfileState:
    dev_eui: str
    join_eui: str
    device_name: str
    is_disabled: str
    profile_id: str
    profile_name: str
    profile_region: str
    profile_region_config_id: str
    mac_version: str
    reg_params_revision: str
    supports_otaa: str
    app_key_present: bool
    nwk_key_present: bool
    profile_device_count: int


@dataclass(frozen=True)
class TargetProfile:
    profile_id: str
    profile_name: str
    profile_region: str
    profile_region_config_id: str
    mac_version: str
    reg_params_revision: str
    supports_otaa: str
    profile_device_count: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def boundary_fields(*, execute: bool, mutation_performed: bool, mutation_scope: str) -> dict[str, Any]:
    return {
        "read_only": not mutation_performed,
        "execute_requested": execute,
        "rf_tx_allowed": False,
        "rf_tx_executed": False,
        "join_allowed": False,
        "join_executed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "lorawan_uplink_executed": False,
        "mqtt_publish_performed": False,
        "chirpstack_config_changed": mutation_performed,
        "device_registry_changed": mutation_performed,
        "postgres_write_performed": mutation_performed,
        "profile_mutation_scope": mutation_scope,
        "approval_token_stored": False,
        "raw_identity_embedded": False,
        "raw_key_embedded": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "outbound_send_performed": False,
        "hardware_control_scope": "chirpstack_profile_provisioning_only_no_rf",
    }


def hash_identifier(value: str | None, *, salt: str) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def compact_eui(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_eui(value)
    return normalized.replace(":", "") if normalized else None


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def read_jsonl(path: Path, *, max_records: int = 500) -> tuple[list[dict[str, Any]], int, bool]:
    if not path.exists():
        return [], 0, False
    records: list[dict[str, Any]] = []
    invalid_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-max_records:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if isinstance(payload, dict):
            records.append(payload)
        else:
            invalid_count += 1
    return records, invalid_count, True


def extract_wio_identity(records: Sequence[dict[str, Any]], *, hash_salt: str) -> dict[str, Any]:
    identity: dict[str, str] = {}
    for record in records:
        for line in record.get("response_lines", []):
            if not isinstance(line, str):
                continue
            match = re.match(r"^\+ID:\s*([^,]+),\s*(.+)$", line, flags=re.IGNORECASE)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = normalize_eui(match.group(2)) if key in {"deveui", "appeui"} else match.group(2).strip()
            if value:
                identity[key] = value
    dev_eui = identity.get("deveui")
    app_eui = identity.get("appeui")
    return {
        "dev_eui": dev_eui,
        "app_eui": app_eui,
        "dev_eui_present": bool(dev_eui),
        "app_eui_present": bool(app_eui),
        "dev_eui_hash": hash_identifier(dev_eui, salt=hash_salt),
        "app_eui_hash": hash_identifier(app_eui, salt=hash_salt),
        "raw_identity_embedded": False,
    }


def run_psql_query(
    sql: str,
    *,
    container: str,
    postgres_user: str,
    postgres_db: str,
    timeout_seconds: float,
) -> tuple[str, str | None, int | None]:
    command = [
        "docker",
        "exec",
        container,
        "psql",
        "-U",
        postgres_user,
        "-d",
        postgres_db,
        "-AtF",
        "|",
        "-c",
        sql,
    ]
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout_seconds)
    except FileNotFoundError as exc:
        return "", f"{type(exc).__name__}: {exc}", None
    except subprocess.TimeoutExpired:
        return "", "psql query timed out", None
    if result.returncode != 0:
        return result.stdout or "", (result.stderr or "psql returned non-zero").strip(), result.returncode
    return result.stdout or "", None, result.returncode


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"t", "true", "1", "yes"}


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def parse_device_state_output(text: str) -> DeviceProfileState | None:
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = (line.split("|") + [""] * 15)[:15]
        return DeviceProfileState(
            dev_eui=parts[0],
            join_eui=parts[1],
            device_name=parts[2],
            is_disabled=parts[3],
            profile_id=parts[4],
            profile_name=parts[5],
            profile_region=parts[6],
            profile_region_config_id=parts[7],
            mac_version=parts[8],
            reg_params_revision=parts[9],
            supports_otaa=parts[10],
            app_key_present=parse_bool(parts[11]),
            nwk_key_present=parse_bool(parts[12]),
            profile_device_count=parse_int(parts[14]),
        )
    return None


def parse_target_profiles_output(text: str) -> list[TargetProfile]:
    profiles: list[TargetProfile] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = (line.split("|") + [""] * 8)[:8]
        profiles.append(
            TargetProfile(
                profile_id=parts[0],
                profile_name=parts[1],
                profile_region=parts[2],
                profile_region_config_id=parts[3],
                mac_version=parts[4],
                reg_params_revision=parts[5],
                supports_otaa=parts[6],
                profile_device_count=parse_int(parts[7]),
            )
        )
    return profiles


def summarize_device_state(state: DeviceProfileState | None, *, wio_identity: dict[str, Any], hash_salt: str) -> dict[str, Any]:
    if state is None:
        return {"found": False, "raw_identity_embedded": False, "raw_key_embedded": False}
    return {
        "found": True,
        "dev_eui_hash": hash_identifier(state.dev_eui, salt=hash_salt),
        "join_eui_hash": hash_identifier(state.join_eui, salt=hash_salt),
        "dev_eui_matches_wio": compact_eui(state.dev_eui) == compact_eui(wio_identity.get("dev_eui")),
        "join_eui_matches_wio_app_eui": compact_eui(state.join_eui) == compact_eui(wio_identity.get("app_eui")),
        "device_name_present": bool(state.device_name),
        "is_disabled": parse_bool(state.is_disabled),
        "profile_id_hash": hash_identifier(state.profile_id, salt=hash_salt),
        "profile_name": state.profile_name,
        "profile_region": state.profile_region,
        "profile_region_config_id": state.profile_region_config_id,
        "mac_version": state.mac_version,
        "reg_params_revision": state.reg_params_revision,
        "supports_otaa": parse_bool(state.supports_otaa),
        "app_key_present": state.app_key_present,
        "nwk_key_present": state.nwk_key_present,
        "profile_device_count": state.profile_device_count,
        "raw_identity_embedded": False,
        "raw_key_embedded": False,
    }


def summarize_target_profiles(profiles: Sequence[TargetProfile], *, hash_salt: str) -> list[dict[str, Any]]:
    return [
        {
            "profile_id_hash": hash_identifier(profile.profile_id, salt=hash_salt),
            "profile_name": profile.profile_name,
            "profile_region": profile.profile_region,
            "profile_region_config_id": profile.profile_region_config_id,
            "mac_version": profile.mac_version,
            "reg_params_revision": profile.reg_params_revision,
            "supports_otaa": parse_bool(profile.supports_otaa),
            "profile_device_count": profile.profile_device_count,
        }
        for profile in profiles
    ]


def build_device_query(dev_eui_hex: str) -> str:
    dev = sql_literal(dev_eui_hex)
    return f"""
select encode(d.dev_eui, 'hex'), encode(d.join_eui, 'hex'), d.name, d.is_disabled,
       d.device_profile_id, dp.name, dp.region, dp.region_config_id,
       dp.mac_version, dp.reg_params_revision, dp.supports_otaa,
       (dk.app_key is not null), (dk.nwk_key is not null),
       encode(dk.app_key, 'hex'),
       (select count(*) from device d2 where d2.device_profile_id = d.device_profile_id)
from device d
left join device_keys dk on dk.dev_eui = d.dev_eui
left join device_profile dp on dp.id = d.device_profile_id
where d.dev_eui = decode({dev}, 'hex')
limit 1;
""".strip()


def build_target_profiles_query(target_region: str, target_region_config_id: str) -> str:
    region = sql_literal(target_region)
    config_id = sql_literal(target_region_config_id)
    return f"""
select dp.id, dp.name, dp.region, dp.region_config_id, dp.mac_version,
       dp.reg_params_revision, dp.supports_otaa,
       (select count(*) from device d where d.device_profile_id = dp.id)
from device_profile dp
where lower(dp.region_config_id) = lower({config_id})
   or upper(dp.region) = upper({region})
order by dp.created_at desc
limit 10;
""".strip()


def decide_plan(
    *,
    wio_identity: dict[str, Any],
    device_state: DeviceProfileState | None,
    target_profiles: Sequence[TargetProfile],
    target_region: str,
    target_region_config_id: str,
    allow_in_place_profile_update: bool,
) -> tuple[str, str, list[str]]:
    if not wio_identity["dev_eui_present"] or not wio_identity["app_eui_present"]:
        return "blocked_missing_wio_identity", "none", ["rerun Wio-E5 read-only AT identity smoke"]
    if device_state is None:
        return "blocked_device_not_registered", "none", ["register the Wio-E5 DevEUI in ChirpStack first"]
    if compact_eui(device_state.join_eui) != compact_eui(wio_identity.get("app_eui")):
        return "blocked_join_eui_mismatch", "none", ["align ChirpStack JoinEUI/AppEUI before changing profile"]
    if parse_bool(device_state.is_disabled):
        return "blocked_device_disabled", "none", ["enable the ChirpStack device before RF trial"]
    if not device_state.app_key_present or not device_state.nwk_key_present:
        return "blocked_missing_device_keys", "none", ["provision OTAA keys before RF trial"]
    already_region = device_state.profile_region.upper() == target_region.upper()
    already_config = device_state.profile_region_config_id.lower() == target_region_config_id.lower()
    if already_region and already_config:
        return "already_aligned", "none", ["run one controlled join window with packet forwarder active"]
    if target_profiles:
        return "ready_to_switch_device_profile", "device_profile_switch", ["switch only this device to the existing AS923_2 profile"]
    if not allow_in_place_profile_update:
        return "blocked_target_profile_missing", "none", ["create or approve an AS923_2 profile, or rerun with in-place profile update approval"]
    if device_state.profile_device_count != 1:
        return "blocked_profile_shared", "none", ["do not mutate a shared profile in place; create a dedicated AS923_2 profile"]
    return "ready_for_in_place_profile_update", "device_profile_in_place_update", ["mutate the dedicated Wio-E5 profile to AS923_2"]


def build_switch_profile_sql(dev_eui_hex: str, current_profile_id: str, target_profile_id: str) -> str:
    return f"""
update device
set device_profile_id = {sql_literal(target_profile_id)}, updated_at = now()
where dev_eui = decode({sql_literal(dev_eui_hex)}, 'hex')
  and device_profile_id = {sql_literal(current_profile_id)};
""".strip()


def build_in_place_profile_update_sql(
    *,
    dev_eui_hex: str,
    current_profile_id: str,
    target_region: str,
    target_region_config_id: str,
    target_profile_name: str,
) -> str:
    return f"""
update device_profile
set name = {sql_literal(target_profile_name)},
    region = {sql_literal(target_region)},
    region_config_id = {sql_literal(target_region_config_id)},
    updated_at = now()
where id = {sql_literal(current_profile_id)}
  and (select count(*) from device where device_profile_id = {sql_literal(current_profile_id)}) = 1
  and exists (
    select 1 from device
    where dev_eui = decode({sql_literal(dev_eui_hex)}, 'hex')
      and device_profile_id = {sql_literal(current_profile_id)}
  );
""".strip()


def parse_update_count(text: str) -> int:
    match = re.search(r"UPDATE\s+(\d+)", text, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 0


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def parse_positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def led_bits_for_status(status: str, *, ready_bit: int, changed_bit: int, blocked_bit: int) -> int:
    if status in {"mutated_profile_aligned", "already_aligned"}:
        bit = changed_bit
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
    target_region: str,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    if status == "mutated_profile_aligned":
        line2 = "MUTATED"
    elif status == "already_aligned":
        line2 = "ALIGNED"
    elif status.startswith("ready"):
        line2 = "READY"
    else:
        line2 = "BLOCKED"
    message = f"SCOUT LORA PROV\n{line2}\n{target_region}\nNO RF TX"
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
        **boundary_fields(execute=False, mutation_performed=False, mutation_scope="visual_status_only"),
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
    changed_bit: int,
    blocked_bit: int,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    defaults = PORT_DEFAULTS.get(port, PORT_DEFAULTS[DEFAULT_LED_PORT])
    resolved_data = data_gpio if data_gpio is not None else defaults["data_gpio"]
    resolved_clock = clock_gpio if clock_gpio is not None else defaults["clock_gpio"]
    bits = led_bits_for_status(status, ready_bit=ready_bit, changed_bit=changed_bit, blocked_bit=blocked_bit)
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
        "changed_led_bit": changed_bit,
        "blocked_led_bit": blocked_bit,
        "write_status": write_status,
        "dry_run": dry_run,
        **boundary_fields(execute=False, mutation_performed=False, mutation_scope="visual_status_only"),
    }
    if error:
        payload["error"] = error
    return [payload]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely align a Wio-E5 ChirpStack device profile to AS923_2 without RF.")
    parser.add_argument("--wio-at-jsonl", type=Path, default=DEFAULT_WIO_AT_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--postgres-container", default=DEFAULT_POSTGRES_CONTAINER)
    parser.add_argument("--postgres-user", default=DEFAULT_POSTGRES_USER)
    parser.add_argument("--postgres-db", default=DEFAULT_POSTGRES_DB)
    parser.add_argument("--target-region", default=DEFAULT_TARGET_REGION)
    parser.add_argument("--target-region-config-id", default=DEFAULT_TARGET_REGION_CONFIG_ID)
    parser.add_argument("--target-profile-name", default=DEFAULT_TARGET_PROFILE_NAME)
    parser.add_argument("--operator-approval-token", default="")
    parser.add_argument("--required-operator-approval-token", default=DEFAULT_APPROVAL_TOKEN)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-in-place-profile-update", action="store_true")
    parser.add_argument("--hash-salt", default=SOURCE)
    parser.add_argument("--command-timeout-seconds", type=parse_positive_float, default=5.0)
    parser.add_argument("--device-query-output", default=None, help="Fixture output for tests; disables live device query.")
    parser.add_argument("--target-profiles-output", default=None, help="Fixture output for tests; disables live target profile query.")
    parser.add_argument("--mutation-output", default=None, help="Fixture mutation output for tests; disables live mutation query.")
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
    parser.add_argument("--led-changed-bit", type=parse_led_bit, default=DEFAULT_LED_CHANGED_BIT)
    parser.add_argument("--led-blocked-bit", type=parse_led_bit, default=DEFAULT_LED_BLOCKED_BIT)
    return parser


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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    wio_records, wio_invalid_count, wio_file_exists = read_jsonl(args.wio_at_jsonl)
    wio_identity = extract_wio_identity(wio_records, hash_salt=args.hash_salt)
    dev_eui_hex = compact_eui(wio_identity.get("dev_eui"))
    device_state = None
    device_query_error = None
    device_query_fixture_used = False
    target_profiles: list[TargetProfile] = []
    target_query_error = None
    target_query_fixture_used = False

    if dev_eui_hex:
        device_text, device_query_error, _, device_query_fixture_used = query_or_fixture(
            args.device_query_output,
            build_device_query(dev_eui_hex),
            container=args.postgres_container,
            postgres_user=args.postgres_user,
            postgres_db=args.postgres_db,
            timeout_seconds=args.command_timeout_seconds,
        )
        if device_query_error is None:
            device_state = parse_device_state_output(device_text)
        target_text, target_query_error, _, target_query_fixture_used = query_or_fixture(
            args.target_profiles_output,
            build_target_profiles_query(args.target_region, args.target_region_config_id),
            container=args.postgres_container,
            postgres_user=args.postgres_user,
            postgres_db=args.postgres_db,
            timeout_seconds=args.command_timeout_seconds,
        )
        if target_query_error is None:
            target_profiles = parse_target_profiles_output(target_text)
    status, mutation_scope, next_actions = decide_plan(
        wio_identity=wio_identity,
        device_state=device_state,
        target_profiles=target_profiles,
        target_region=args.target_region,
        target_region_config_id=args.target_region_config_id,
        allow_in_place_profile_update=args.allow_in_place_profile_update,
    )
    approval_valid = args.operator_approval_token == args.required_operator_approval_token
    mutation_attempted = False
    mutation_performed = False
    mutation_error = None
    mutation_update_count = 0

    if args.execute:
        if not approval_valid:
            status = "blocked_missing_operator_approval"
            mutation_scope = "none"
            next_actions = [f"rerun with {args.required_operator_approval_token} after confirming the planned mutation"]
        elif status not in {"ready_to_switch_device_profile", "ready_for_in_place_profile_update"}:
            mutation_scope = "none"
        else:
            mutation_attempted = True
            if args.mutation_output is not None:
                mutation_text, mutation_error, mutation_returncode = args.mutation_output, None, 0
            elif status == "ready_to_switch_device_profile" and target_profiles and device_state and dev_eui_hex:
                mutation_text, mutation_error, mutation_returncode = run_psql_query(
                    build_switch_profile_sql(dev_eui_hex, device_state.profile_id, target_profiles[0].profile_id),
                    container=args.postgres_container,
                    postgres_user=args.postgres_user,
                    postgres_db=args.postgres_db,
                    timeout_seconds=args.command_timeout_seconds,
                )
            elif status == "ready_for_in_place_profile_update" and device_state and dev_eui_hex:
                mutation_text, mutation_error, mutation_returncode = run_psql_query(
                    build_in_place_profile_update_sql(
                        dev_eui_hex=dev_eui_hex,
                        current_profile_id=device_state.profile_id,
                        target_region=args.target_region,
                        target_region_config_id=args.target_region_config_id,
                        target_profile_name=args.target_profile_name,
                    ),
                    container=args.postgres_container,
                    postgres_user=args.postgres_user,
                    postgres_db=args.postgres_db,
                    timeout_seconds=args.command_timeout_seconds,
                )
            else:
                mutation_text, mutation_error, mutation_returncode = "", "mutation preconditions disappeared", None
            if mutation_error is not None or mutation_returncode not in {0, None}:
                status = "mutation_error"
                next_actions = ["inspect Postgres mutation error and do not rerun RF yet"]
            else:
                mutation_update_count = parse_update_count(mutation_text)
                mutation_performed = mutation_update_count == 1
                status = "mutated_profile_aligned" if mutation_performed else "mutation_no_rows_changed"
                next_actions = ["rerun read-only provisioning audit", "start no-tx packet forwarder before the next single join trial"]

    payload = {
        "captured_at": now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "target_region": args.target_region,
        "target_region_config_id": args.target_region_config_id,
        "target_profile_name": args.target_profile_name,
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
        "device_query": {
            "attempted": dev_eui_hex is not None,
            "fixture_used": device_query_fixture_used,
            "error": device_query_error,
        },
        "target_profile_query": {
            "attempted": dev_eui_hex is not None,
            "fixture_used": target_query_fixture_used,
            "error": target_query_error,
        },
        "device_profile_before": summarize_device_state(device_state, wio_identity=wio_identity, hash_salt=args.hash_salt),
        "target_profiles": summarize_target_profiles(target_profiles, hash_salt=args.hash_salt),
        "target_profile_count": len(target_profiles),
        "mutation_attempted": mutation_attempted,
        "mutation_update_count": mutation_update_count,
        "mutation_error": mutation_error,
        "next_actions": next_actions,
        **boundary_fields(execute=args.execute, mutation_performed=mutation_performed, mutation_scope=mutation_scope if mutation_performed else "none"),
    }
    payload["oled_status_updates"] = write_oled_status(
        enabled=args.oled_status,
        dry_run=args.oled_dry_run,
        bus=args.oled_bus,
        address=args.oled_address,
        driver=args.oled_driver,
        status=status,
        target_region=args.target_region,
    )
    payload["led_status_updates"] = write_led_status(
        enabled=args.led_status,
        dry_run=args.led_dry_run,
        port=args.led_port,
        data_gpio=args.data_gpio,
        clock_gpio=args.clock_gpio,
        status=status,
        ready_bit=args.led_ready_bit,
        changed_bit=args.led_changed_bit,
        blocked_bit=args.led_blocked_bit,
    )
    append_jsonl(args.output_jsonl, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status in {"already_aligned", "ready_to_switch_device_profile", "ready_for_in_place_profile_update", "mutated_profile_aligned"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
