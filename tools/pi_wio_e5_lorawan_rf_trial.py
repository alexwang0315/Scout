from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
    from tools.pi_wio_e5_lorawan_at_smoke import DEFAULT_BAUD, DEFAULT_PORT, make_at_session, response_status_from_lines
    from tools.pi_wio_e5_lorawan_uplink_trial_plan import APPROVAL_TOKEN, DEFAULT_FREQUENCY_HZ, DEFAULT_OUTPUT_JSONL
    from tools.pi_wio_e5_lorawan_uplink_trial_plan import parse_frequency_hz as parse_tw_frequency_hz
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display
    from pi_wio_e5_lorawan_at_smoke import DEFAULT_BAUD, DEFAULT_PORT, make_at_session, response_status_from_lines
    from pi_wio_e5_lorawan_uplink_trial_plan import APPROVAL_TOKEN, DEFAULT_FREQUENCY_HZ, DEFAULT_OUTPUT_JSONL
    from pi_wio_e5_lorawan_uplink_trial_plan import parse_frequency_hz as parse_tw_frequency_hz


SOURCE = "pi_wio_e5_lorawan_rf_trial"
HARDWARE_KIND = "wio_e5_lorawan_client_operator_approved_rf_trial"
DEFAULT_PLAN_JSONL = DEFAULT_OUTPUT_JSONL
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/wio-e5-rf-trial.jsonl")
DEFAULT_PAYLOAD_TEXT = "SCOUT"
DEFAULT_LED_BLOCKED_BIT = 1
DEFAULT_LED_DRY_RUN_BIT = 2
DEFAULT_LED_TX_ATTEMPT_BIT = 9
DEFAULT_LED_FAIL_BIT = 10


@dataclass(frozen=True)
class TrialCommand:
    label: str
    command: str
    rf_tx_command: bool
    join_command: bool
    uplink_command: bool
    timeout_seconds: float
    quiet_seconds: float


@dataclass(frozen=True)
class TrialCommandResult:
    command_index: int
    label: str
    command: str
    response_lines: list[str]
    response_status: str
    elapsed_ms: int
    rf_tx_command: bool
    join_command: bool
    uplink_command: bool
    command_executed: bool
    error: str | None = None


class DryRunSession:
    def transact(self, *, command: str, timeout_seconds: float, quiet_seconds: float) -> list[str]:
        if command == "AT":
            return ["+AT: OK"]
        if command == "AT+JOIN":
            return ["+JOIN: Start", "+JOIN: Network joined", "+JOIN: Done"]
        if command.startswith("AT+MSG"):
            return ["+MSG: Start", "+MSG: Done"]
        return ["+AT: OK"]

    def close(self) -> None:
        return None


def boundary_fields(*, approved_for_rf: bool, rf_tx_executed: bool, join_executed: bool, uplink_executed: bool) -> dict[str, Any]:
    return {
        "read_only": not rf_tx_executed,
        "rf_tx_allowed": approved_for_rf,
        "rf_tx_executed": rf_tx_executed,
        "join_allowed": approved_for_rf,
        "join_executed": join_executed,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": approved_for_rf,
        "lorawan_uplink_executed": uplink_executed,
        "operator_approval_required": True,
        "operator_approval_recorded": approved_for_rf,
        "operator_approval_token_stored": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "outbound_send_performed": rf_tx_executed,
        "hardware_control_scope": "operator_approved_single_lorawan_client_rf_trial",
    }


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


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def validate_payload_text(value: str) -> str:
    if not value:
        raise argparse.ArgumentTypeError("payload text must not be empty")
    if len(value.encode("utf-8")) > 32:
        raise argparse.ArgumentTypeError("payload text must be 32 bytes or less")
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise argparse.ArgumentTypeError("payload text must be printable ASCII")
    if '"' in value or "\\" in value:
        raise argparse.ArgumentTypeError("payload text must not contain quote or backslash")
    return value


def latest_jsonl_record(path: Path) -> tuple[dict[str, Any] | None, int, bool]:
    if not path.exists():
        return None, 0, False
    invalid_count = 0
    latest: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if isinstance(payload, dict):
            latest = payload
        else:
            invalid_count += 1
    return latest, invalid_count, True


def validate_ready_plan(plan: dict[str, Any] | None, *, plan_exists: bool, frequency_hz: int, region_profile: str) -> list[str]:
    blockers: list[str] = []
    if not plan_exists:
        blockers.append("missing_trial_plan_jsonl")
        return blockers
    if plan is None:
        blockers.append("no_valid_trial_plan_record")
        return blockers
    if plan.get("status") != "ready_for_manual_uplink_trial":
        blockers.append(f"plan_not_ready:{plan.get('status')}")
    if plan.get("operator_approval_recorded") is not True:
        blockers.append("plan_operator_approval_not_recorded")
    if plan.get("frequency_hz") != frequency_hz:
        blockers.append("plan_frequency_mismatch")
    if plan.get("region_profile") != region_profile:
        blockers.append("plan_region_mismatch")
    if plan.get("rf_tx_executed") is True or plan.get("lorawan_uplink_executed") is True:
        blockers.append("planning_record_must_not_be_prior_execution")
    return blockers


def build_message_command(payload_text: str) -> str:
    return f'AT+MSG="{payload_text}"'


def build_command_sequence(
    *,
    payload_text: str,
    skip_join: bool,
    join_only: bool,
    command_timeout_seconds: float,
    command_quiet_seconds: float,
    join_timeout_seconds: float,
    join_quiet_seconds: float,
) -> list[TrialCommand]:
    commands = [
        TrialCommand(
            label="serial_preflight",
            command="AT",
            rf_tx_command=False,
            join_command=False,
            uplink_command=False,
            timeout_seconds=command_timeout_seconds,
            quiet_seconds=command_quiet_seconds,
        )
    ]
    if not skip_join:
        commands.append(
            TrialCommand(
                label="lorawan_join",
                command="AT+JOIN",
                rf_tx_command=True,
                join_command=True,
                uplink_command=False,
                timeout_seconds=join_timeout_seconds,
                quiet_seconds=join_quiet_seconds,
            )
        )
    if join_only:
        return commands
    commands.append(
        TrialCommand(
            label="lorawan_uplink",
            command=build_message_command(payload_text),
            rf_tx_command=True,
            join_command=False,
            uplink_command=True,
            timeout_seconds=command_timeout_seconds,
            quiet_seconds=command_quiet_seconds,
        )
    )
    return commands


def join_successful(result: TrialCommandResult | None) -> bool:
    if result is None:
        return False
    upper_lines = [line.upper() for line in result.response_lines]
    if any("JOIN FAILED" in line or "FAILED" in line or "ERROR" in line for line in upper_lines):
        return False
    return any("NETWORK JOINED" in line for line in upper_lines)


def trial_response_status(command: TrialCommand, response_lines: list[str]) -> str:
    upper_lines = [line.upper() for line in response_lines]
    if any("ERROR" in line or "FAIL" in line or "PLEASE JOIN NETWORK FIRST" in line for line in upper_lines):
        return "error"
    if command.join_command:
        return "ok" if join_successful(
            TrialCommandResult(
                command_index=-1,
                label=command.label,
                command=command.command,
                response_lines=response_lines,
                response_status="ok",
                elapsed_ms=0,
                rf_tx_command=command.rf_tx_command,
                join_command=command.join_command,
                uplink_command=command.uplink_command,
                command_executed=True,
            )
        ) else "join_not_confirmed"
    if command.uplink_command and not any("MSG: DONE" in line for line in upper_lines):
        return "uplink_not_confirmed"
    return response_status_from_lines(response_lines)


def execute_commands(
    *,
    commands: list[TrialCommand],
    session_factory: Callable[[], Any],
    stop_after_join_failure: bool,
) -> list[TrialCommandResult]:
    session = session_factory()
    results: list[TrialCommandResult] = []
    try:
        for index, command in enumerate(commands):
            if command.uplink_command and stop_after_join_failure:
                join_results = [result for result in results if result.join_command]
                if join_results and not join_successful(join_results[-1]):
                    break
            started_at = time.monotonic()
            try:
                response_lines = session.transact(
                    command=command.command,
                    timeout_seconds=command.timeout_seconds,
                    quiet_seconds=command.quiet_seconds,
                )
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                result = TrialCommandResult(
                    command_index=index,
                    label=command.label,
                    command=command.command,
                    response_lines=response_lines,
                    response_status=trial_response_status(command, response_lines),
                    elapsed_ms=elapsed_ms,
                    rf_tx_command=command.rf_tx_command,
                    join_command=command.join_command,
                    uplink_command=command.uplink_command,
                    command_executed=True,
                )
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - started_at) * 1000)
                result = TrialCommandResult(
                    command_index=index,
                    label=command.label,
                    command=command.command,
                    response_lines=[],
                    response_status="error",
                    elapsed_ms=elapsed_ms,
                    rf_tx_command=command.rf_tx_command,
                    join_command=command.join_command,
                    uplink_command=command.uplink_command,
                    command_executed=True,
                    error=f"{type(exc).__name__}: {exc}",
                )
            results.append(result)
        return results
    finally:
        session.close()


def command_result_payload(result: TrialCommandResult) -> dict[str, Any]:
    payload = {
        "command_index": result.command_index,
        "label": result.label,
        "command": result.command,
        "response_lines": result.response_lines,
        "response_status": result.response_status,
        "elapsed_ms": result.elapsed_ms,
        "rf_tx_command": result.rf_tx_command,
        "join_command": result.join_command,
        "uplink_command": result.uplink_command,
        "command_executed": result.command_executed,
    }
    if result.error is not None:
        payload["error"] = result.error
    return payload


def summarize_results(results: list[TrialCommandResult], *, skip_join: bool, join_only: bool) -> tuple[str, bool, bool, bool]:
    rf_tx_executed = any(result.command_executed and result.rf_tx_command for result in results)
    join_executed = any(result.command_executed and result.join_command for result in results)
    uplink_executed = any(result.command_executed and result.uplink_command for result in results)
    failed = any(result.response_status != "ok" for result in results)
    if not results:
        return "not_executed", rf_tx_executed, join_executed, uplink_executed
    join_result = next((result for result in results if result.join_command), None)
    if not skip_join and join_executed and not join_successful(join_result):
        return "rf_trial_join_not_confirmed", rf_tx_executed, join_executed, uplink_executed
    if join_only and join_executed:
        return "rf_trial_join_confirmed_no_uplink", rf_tx_executed, join_executed, uplink_executed
    if failed:
        return "rf_trial_command_failed", rf_tx_executed, join_executed, uplink_executed
    if uplink_executed:
        return "rf_trial_uplink_command_sent", rf_tx_executed, join_executed, uplink_executed
    if join_executed:
        return "rf_trial_join_attempted_no_uplink", rf_tx_executed, join_executed, uplink_executed
    return "serial_preflight_only", rf_tx_executed, join_executed, uplink_executed


def build_trial_payload(
    *,
    status: str,
    blockers: list[str],
    plan_path: Path,
    plan: dict[str, Any] | None,
    plan_exists: bool,
    plan_invalid_count: int,
    port: str,
    baud: int,
    region_profile: str,
    frequency_hz: int,
        payload_text: str,
        skip_join: bool,
        join_only: bool,
        execute_rf_tx: bool,
    dry_run: bool,
    planned_commands: list[TrialCommand],
    results: list[TrialCommandResult],
    approved_for_rf: bool,
    rf_tx_executed: bool,
    join_executed: bool,
    uplink_executed: bool,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "blockers": blockers,
        "device_port": port,
        "baud": baud,
        "region_profile": region_profile,
        "frequency_hz": frequency_hz,
        "payload_text": payload_text,
        "payload_bytes": len(payload_text.encode("utf-8")),
        "skip_join": skip_join,
        "join_only": join_only,
        "execute_rf_tx_requested": execute_rf_tx,
        "dry_run": dry_run,
        "plan_path": str(plan_path),
        "plan_file_exists": plan_exists,
        "plan_invalid_json_line_count": plan_invalid_count,
        "plan_status": plan.get("status") if plan else None,
        "plan_operator_approval_recorded": plan.get("operator_approval_recorded") if plan else None,
        "planned_commands": [
            {
                "label": command.label,
                "command": command.command,
                "rf_tx_command": command.rf_tx_command,
                "join_command": command.join_command,
                "uplink_command": command.uplink_command,
            }
            for command in planned_commands
        ],
        "command_results": [command_result_payload(result) for result in results],
        "command_count": len(results),
        "rf_command_count": sum(1 for result in results if result.rf_tx_command),
    }
    payload.update(
        boundary_fields(
            approved_for_rf=approved_for_rf,
            rf_tx_executed=rf_tx_executed,
            join_executed=join_executed,
            uplink_executed=uplink_executed,
        )
    )
    return payload


def build_blockers(
    *,
    operator_approval_token: str | None,
    execute_rf_tx: bool,
    dry_run: bool,
    plan_blockers: list[str],
    mode_blockers: list[str] | None = None,
) -> tuple[list[str], bool]:
    blockers = list(plan_blockers)
    if mode_blockers:
        blockers.extend(mode_blockers)
    approved_for_rf = operator_approval_token == APPROVAL_TOKEN and execute_rf_tx and not dry_run and not blockers
    if dry_run:
        return blockers, False
    if not execute_rf_tx:
        blockers.append("execute_rf_tx_flag_missing")
    if operator_approval_token != APPROVAL_TOKEN:
        blockers.append("operator_approval_token_missing_or_invalid")
    return blockers, approved_for_rf


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def trial_oled_message(payload: dict[str, Any]) -> str:
    status = payload["status"]
    if status == "rf_trial_uplink_command_sent":
        state = "RF SENT"
    elif status == "rf_trial_join_confirmed_no_uplink":
        state = "JOIN OK"
    elif status.startswith("rf_trial"):
        state = "RF FAIL"
    elif status == "dry_run_no_rf_tx":
        state = "DRY RUN"
    else:
        state = "BLOCKED"
    mhz = payload["frequency_hz"] / 1_000_000
    lines = [
        "SCOUT LORA TX",
        state,
        payload["region_profile"],
        f"{mhz:.1f} MHz",
        f"CMD {payload['command_count']}",
        "SAFETY NO",
    ]
    return "\n".join(line[:16] for line in lines)


def build_oled_status_payload(
    *,
    trial: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    driver_attempted: str | None,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wio_e5_lorawan_rf_trial_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": trial_oled_message(trial),
        "trial_status": trial["status"],
    }
    payload.update(boundary_fields(
        approved_for_rf=trial["rf_tx_allowed"],
        rf_tx_executed=trial["rf_tx_executed"],
        join_executed=trial["join_executed"],
        uplink_executed=trial["lorawan_uplink_executed"],
    ))
    payload["hardware_control_scope"] = "diagnostic_display_only"
    if error is not None:
        payload["error"] = error
    return payload


def write_oled_status(*, trial: dict[str, Any], dry_run: bool, bus: Path, address: int, driver: str) -> dict[str, Any]:
    if dry_run:
        return build_oled_status_payload(
            trial=trial,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver,
            write_status="dry_run",
            dry_run=True,
        )
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=trial_oled_message(trial))
        return build_oled_status_payload(
            trial=trial,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_oled_status_payload(
            trial=trial,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=None,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def led_bits_for_trial(trial: dict[str, Any], *, blocked_bit: int, dry_run_bit: int, tx_attempt_bit: int, fail_bit: int) -> int:
    status = trial["status"]
    if status in {"rf_trial_uplink_command_sent", "rf_trial_join_confirmed_no_uplink"}:
        bit = tx_attempt_bit
    elif status.startswith("rf_trial"):
        bit = fail_bit
    elif status == "dry_run_no_rf_tx":
        bit = dry_run_bit
    else:
        bit = blocked_bit
    return 1 << (bit - 1)


def build_led_status_payload(
    *,
    trial: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    blocked_bit: int,
    dry_run_bit: int,
    tx_attempt_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wio_e5_lorawan_rf_trial_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{led_bits_for_trial(trial, blocked_bit=blocked_bit, dry_run_bit=dry_run_bit, tx_attempt_bit=tx_attempt_bit, fail_bit=fail_bit):03x}",
        "trial_status": trial["status"],
        "blocked_led_bit": blocked_bit,
        "dry_run_led_bit": dry_run_bit,
        "tx_attempt_led_bit": tx_attempt_bit,
        "fail_led_bit": fail_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
    }
    payload.update(boundary_fields(
        approved_for_rf=trial["rf_tx_allowed"],
        rf_tx_executed=trial["rf_tx_executed"],
        join_executed=trial["join_executed"],
        uplink_executed=trial["lorawan_uplink_executed"],
    ))
    payload["hardware_control_scope"] = "diagnostic_indicator_only"
    if error is not None:
        payload["error"] = error
    return payload


def blink_led_status(
    *,
    trial: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    blocked_bit: int,
    dry_run_bit: int,
    tx_attempt_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return build_led_status_payload(
            trial=trial,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            blocked_bit=blocked_bit,
            dry_run_bit=dry_run_bit,
            tx_attempt_bit=tx_attempt_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )
    writer = None
    try:
        writer = make_gpio_writer()
        bits = led_bits_for_trial(
            trial,
            blocked_bit=blocked_bit,
            dry_run_bit=dry_run_bit,
            tx_attempt_bit=tx_attempt_bit,
            fail_bit=fail_bit,
        )
        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_led_status_payload(
            trial=trial,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            blocked_bit=blocked_bit,
            dry_run_bit=dry_run_bit,
            tx_attempt_bit=tx_attempt_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_led_status_payload(
            trial=trial,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            blocked_bit=blocked_bit,
            dry_run_bit=dry_run_bit,
            tx_attempt_bit=tx_attempt_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()


def run_trial(
    *,
    plan_jsonl: Path,
    port: str,
    baud: int,
    region_profile: str,
    frequency_hz: int,
    payload_text: str,
    skip_join: bool,
    join_only: bool,
    execute_rf_tx: bool,
    dry_run: bool,
    operator_approval_token: str | None,
    command_timeout_seconds: float,
    command_quiet_seconds: float,
    join_timeout_seconds: float,
    join_quiet_seconds: float,
    continue_after_join_failure: bool,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    plan, plan_invalid_count, plan_exists = latest_jsonl_record(plan_jsonl)
    plan_blockers = validate_ready_plan(
        plan,
        plan_exists=plan_exists,
        frequency_hz=frequency_hz,
        region_profile=region_profile,
    )
    mode_blockers: list[str] = []
    if join_only and skip_join:
        mode_blockers.append("join_only_conflicts_with_skip_join")
    blockers, approved_for_rf = build_blockers(
        operator_approval_token=operator_approval_token,
        execute_rf_tx=execute_rf_tx,
        dry_run=dry_run,
        plan_blockers=plan_blockers,
        mode_blockers=mode_blockers,
    )
    planned_commands = build_command_sequence(
        payload_text=payload_text,
        skip_join=skip_join,
        join_only=join_only,
        command_timeout_seconds=command_timeout_seconds,
        command_quiet_seconds=command_quiet_seconds,
        join_timeout_seconds=join_timeout_seconds,
        join_quiet_seconds=join_quiet_seconds,
    )
    results: list[TrialCommandResult] = []
    rf_tx_executed = False
    join_executed = False
    uplink_executed = False
    if dry_run:
        results = execute_commands(
            commands=planned_commands,
            session_factory=lambda: DryRunSession(),
            stop_after_join_failure=not continue_after_join_failure,
        )
        status = "blocked_rf_trial_preflight" if mode_blockers else "dry_run_no_rf_tx"
    elif blockers:
        status = "blocked_rf_trial_preflight"
    else:
        factory = session_factory if session_factory is not None else lambda: make_at_session(port=port, baud=baud)
        results = execute_commands(
            commands=planned_commands,
            session_factory=factory,
            stop_after_join_failure=not continue_after_join_failure,
        )
        status, rf_tx_executed, join_executed, uplink_executed = summarize_results(
            results,
            skip_join=skip_join,
            join_only=join_only,
        )
    if dry_run:
        rf_tx_executed = False
        join_executed = False
        uplink_executed = False

    return build_trial_payload(
        status=status,
        blockers=blockers,
        plan_path=plan_jsonl,
        plan=plan,
        plan_exists=plan_exists,
        plan_invalid_count=plan_invalid_count,
        port=port,
        baud=baud,
        region_profile=region_profile,
        frequency_hz=frequency_hz,
        payload_text=payload_text,
        skip_join=skip_join,
        join_only=join_only,
        execute_rf_tx=execute_rf_tx,
        dry_run=dry_run,
        planned_commands=planned_commands,
        results=results,
        approved_for_rf=approved_for_rf,
        rf_tx_executed=rf_tx_executed,
        join_executed=join_executed,
        uplink_executed=uplink_executed,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an explicitly approved single Wio-E5 LoRaWAN RF uplink trial.")
    parser.add_argument("--plan-jsonl", type=Path, default=DEFAULT_PLAN_JSONL)
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--region-profile", choices=("AS923_2",), default="AS923_2")
    parser.add_argument("--frequency-hz", type=parse_tw_frequency_hz, default=DEFAULT_FREQUENCY_HZ)
    parser.add_argument("--payload-text", type=validate_payload_text, default=DEFAULT_PAYLOAD_TEXT)
    parser.add_argument("--skip-join", action="store_true")
    parser.add_argument("--join-only", action="store_true")
    parser.add_argument("--execute-rf-tx", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--operator-approval-token")
    parser.add_argument("--command-timeout-seconds", type=parse_positive_float, default=12.0)
    parser.add_argument("--command-quiet-seconds", type=parse_positive_float, default=2.0)
    parser.add_argument("--join-timeout-seconds", type=parse_positive_float, default=35.0)
    parser.add_argument("--join-quiet-seconds", type=parse_positive_float, default=8.0)
    parser.add_argument("--continue-after-join-failure", action="store_true")
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-blocked-bit", type=parse_led_bit, default=DEFAULT_LED_BLOCKED_BIT)
    parser.add_argument("--led-dry-run-bit", type=parse_led_bit, default=DEFAULT_LED_DRY_RUN_BIT)
    parser.add_argument("--led-tx-attempt-bit", type=parse_led_bit, default=DEFAULT_LED_TX_ATTEMPT_BIT)
    parser.add_argument("--led-fail-bit", type=parse_led_bit, default=DEFAULT_LED_FAIL_BIT)
    parser.add_argument("--led-blink-count", type=parse_positive_int, default=2)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.join_only and args.skip_join:
        parser.error("--join-only cannot be combined with --skip-join")

    trial = run_trial(
        plan_jsonl=args.plan_jsonl,
        port=args.port,
        baud=args.baud,
        region_profile=args.region_profile,
        frequency_hz=args.frequency_hz,
        payload_text=args.payload_text,
        skip_join=args.skip_join,
        join_only=args.join_only,
        execute_rf_tx=args.execute_rf_tx,
        dry_run=args.dry_run,
        operator_approval_token=args.operator_approval_token,
        command_timeout_seconds=args.command_timeout_seconds,
        command_quiet_seconds=args.command_quiet_seconds,
        join_timeout_seconds=args.join_timeout_seconds,
        join_quiet_seconds=args.join_quiet_seconds,
        continue_after_join_failure=args.continue_after_join_failure,
    )

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]
    trial["oled_status_updates"] = []
    trial["led_status_updates"] = []
    if args.oled_status:
        trial["oled_status_updates"].append(
            write_oled_status(
                trial=trial,
                dry_run=args.oled_dry_run,
                bus=args.oled_bus,
                address=args.oled_address,
                driver=args.oled_driver,
            )
        )
    if args.led_status:
        trial["led_status_updates"].append(
            blink_led_status(
                trial=trial,
                port=args.led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                blocked_bit=args.led_blocked_bit,
                dry_run_bit=args.led_dry_run_bit,
                tx_attempt_bit=args.led_tx_attempt_bit,
                fail_bit=args.led_fail_bit,
                blink_count=args.led_blink_count,
                blink_seconds=args.led_blink_seconds,
                dry_run=args.led_dry_run,
            )
        )

    append_jsonl(trial, args.output_jsonl)
    print(json.dumps(trial, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code_for_trial_status(str(trial["status"]))


def exit_code_for_trial_status(status: str) -> int:
    if status == "blocked_rf_trial_preflight":
        return 2
    if status in {"rf_trial_uplink_command_sent", "rf_trial_join_confirmed_no_uplink"}:
        return 0
    if status.startswith("rf_trial"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
