from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_wio_e5_lorawan_uplink_trial_plan"
HARDWARE_KIND = "wio_e5_lorawan_client_uplink_trial_plan"
DEFAULT_WIO_AT_JSONL = Path("/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl")
DEFAULT_GATEWAY_RX_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl")
DEFAULT_UPLINK_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl")
DEFAULT_FREQUENCY_HZ = 923_200_000
TW_MIN_FREQUENCY_HZ = 920_000_000
TW_MAX_FREQUENCY_HZ = 925_000_000
APPROVAL_TOKEN = "I_ACCEPT_RF_TX_AS923_2_TW_920_925"
DEFAULT_LED_BLOCKED_BIT = 1
DEFAULT_LED_WAIT_APPROVAL_BIT = 2
DEFAULT_LED_READY_BIT = 8


def boundary_fields() -> dict[str, Any]:
    return {
        "read_only": True,
        "rf_tx_allowed": False,
        "rf_tx_executed": False,
        "join_allowed": False,
        "join_executed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "lorawan_uplink_executed": False,
        "operator_approval_required": True,
        "manual_rf_tx_trial_requires_separate_command": True,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "outbound_send_performed": False,
        "hardware_control_scope": "operator_approved_lorawan_uplink_trial_planning_only",
    }


def parse_frequency_hz(value: str) -> int:
    try:
        parsed = int(value.replace("_", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("frequency must be an integer Hz value") from exc
    if not TW_MIN_FREQUENCY_HZ <= parsed <= TW_MAX_FREQUENCY_HZ:
        raise argparse.ArgumentTypeError("frequency must be within Taiwan 920000000-925000000 Hz planning boundary")
    return parsed


def parse_led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def parse_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def parse_non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def read_jsonl(path: Path, *, max_records: int = 200) -> tuple[list[dict[str, Any]], int, bool]:
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


def normalize_eui(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^0-9a-fA-F]", "", value)
    if len(compact) != 16:
        return None
    return ":".join(compact[index : index + 2].lower() for index in range(0, 16, 2))


def hash_identifier(value: str, *, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def extract_dev_eui(records: list[dict[str, Any]]) -> str | None:
    for payload in reversed(records):
        for line in payload.get("response_lines", []):
            if not isinstance(line, str):
                continue
            match = re.match(r"^\+ID:\s*DevEui,\s*(.+)$", line, flags=re.IGNORECASE)
            if match:
                normalized = normalize_eui(match.group(1))
                if normalized:
                    return normalized
    return None


def eui_is_zero(value: str | None) -> bool:
    return bool(value) and set(value.replace(":", "")) == {"0"}


def summarize_wio_at(records: list[dict[str, Any]], *, invalid_count: int, file_exists: bool, hash_salt: str) -> dict[str, Any]:
    ok_count = sum(1 for record in records if record.get("response_status") == "ok")
    failed_count = sum(1 for record in records if record.get("response_status") not in {None, "ok"})
    dev_eui = extract_dev_eui(records)
    nonzero_dev_eui = bool(dev_eui and not eui_is_zero(dev_eui))
    summary: dict[str, Any] = {
        "path": str(DEFAULT_WIO_AT_JSONL),
        "file_exists": file_exists,
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_count,
        "ok_count": ok_count,
        "failed_count": failed_count,
        "dev_eui_present": bool(dev_eui),
        "nonzero_dev_eui_present": nonzero_dev_eui,
        "latest_record_at": records[-1].get("captured_at") if records else None,
        "status": "missing_evidence",
    }
    if dev_eui:
        summary["dev_eui_hash"] = hash_identifier(dev_eui, salt=hash_salt)
    if file_exists and records and ok_count > 0 and failed_count == 0 and nonzero_dev_eui:
        summary["status"] = "wio_at_ready"
    elif file_exists and records and ok_count > 0 and failed_count == 0:
        summary["status"] = "wio_identity_incomplete"
    elif file_exists:
        summary["status"] = "wio_at_not_ready"
    return summary


def summarize_gateway_rx(records: list[dict[str, Any]], *, invalid_count: int, file_exists: bool) -> dict[str, Any]:
    latest = records[-1] if records else {}
    latest_status = latest.get("status")
    ready = latest_status in {"rx_stack_ready_no_uplink", "rx_stack_seen_uplink"}
    return {
        "path": str(DEFAULT_GATEWAY_RX_JSONL),
        "file_exists": file_exists,
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_count,
        "latest_record_at": latest.get("captured_at"),
        "latest_status": latest_status,
        "gateway_rx_ready": ready,
        "status": "gateway_rx_ready" if ready else ("gateway_rx_not_ready" if file_exists else "missing_evidence"),
    }


def summarize_existing_uplinks(records: list[dict[str, Any]], *, invalid_count: int, file_exists: bool) -> dict[str, Any]:
    uplink_count = sum(1 for record in records if record.get("status") == "uplink_observed")
    return {
        "path": str(DEFAULT_UPLINK_JSONL),
        "file_exists": file_exists,
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_count,
        "uplink_like_record_count": uplink_count,
        "latest_record_at": records[-1].get("captured_at") if records else None,
    }


def build_plan(
    *,
    wio_summary: dict[str, Any],
    gateway_summary: dict[str, Any],
    uplink_summary: dict[str, Any],
    region_profile: str,
    frequency_hz: int,
    client_label: str,
    mission_id: str,
    operator_approval_token: str | None,
) -> dict[str, Any]:
    approval_recorded = operator_approval_token == APPROVAL_TOKEN
    blockers: list[str] = []
    if wio_summary["status"] != "wio_at_ready":
        blockers.append(wio_summary["status"])
    if gateway_summary["status"] != "gateway_rx_ready":
        blockers.append(gateway_summary["status"])

    if blockers:
        status = "blocked_missing_readiness"
    elif not approval_recorded:
        status = "waiting_for_operator_approval"
    else:
        status = "ready_for_manual_uplink_trial"

    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "client_label": client_label,
        "mission_id": mission_id,
        "region_profile": region_profile,
        "frequency_hz": frequency_hz,
        "tw_frequency_min_hz": TW_MIN_FREQUENCY_HZ,
        "tw_frequency_max_hz": TW_MAX_FREQUENCY_HZ,
        "wio_at_summary": wio_summary,
        "gateway_rx_summary": gateway_summary,
        "existing_uplink_summary": uplink_summary,
        "blockers": blockers,
        "operator_approval_recorded": approval_recorded,
        "operator_approval_token_stored": False,
        "required_operator_approval_phrase": APPROVAL_TOKEN,
        "generated_join_or_send_commands": False,
        "at_join_command_generated": False,
        "at_send_command_generated": False,
        "next_manual_actions": next_manual_actions(status),
    }
    payload.update(boundary_fields())
    return payload


def next_manual_actions(status: str) -> list[str]:
    if status == "blocked_missing_readiness":
        return [
            "run Wio-E5 read-only AT smoke and SX1303 RX readiness smoke first",
            "confirm AS923_2 gateway stack is reachable before any RF trial",
            "do not run AT+JOIN or AT+MSG from this planning tool",
        ]
    if status == "waiting_for_operator_approval":
        return [
            f"rerun this planner with --operator-approval-token {APPROVAL_TOKEN} only when ready for a legal bench RF trial",
            "start passive MQTT uplink tail before the client transmit step",
            "run the future explicit sender tool or manual AT flow in a separate approved step",
        ]
    return [
        "start passive MQTT uplink tail and keep OLED/LED visible",
        "perform exactly one tiny client uplink from the approved Wio-E5 client step",
        "verify sx1303-gateway-uplink.jsonl receives one uplink_observed record",
    ]


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def plan_oled_message(plan: dict[str, Any]) -> str:
    if plan["status"] == "ready_for_manual_uplink_trial":
        state = "PLAN READY"
    elif plan["status"] == "waiting_for_operator_approval":
        state = "WAIT APPROVAL"
    else:
        state = "PLAN BLOCKED"
    mhz = plan["frequency_hz"] / 1_000_000
    wio = "WIO OK" if plan["wio_at_summary"]["status"] == "wio_at_ready" else "WIO --"
    rx = "RX OK" if plan["gateway_rx_summary"]["status"] == "gateway_rx_ready" else "RX --"
    lines = [
        "SCOUT LORA",
        state,
        plan["region_profile"],
        f"{mhz:.1f} MHz",
        f"{wio} {rx}",
        "NO RF TX",
    ]
    return "\n".join(line[:16] for line in lines)


def build_oled_status_payload(
    *,
    plan: dict[str, Any],
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
        "source": "pi_wio_e5_lorawan_uplink_trial_plan_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": plan_oled_message(plan),
        "plan_status": plan["status"],
    }
    payload.update(boundary_fields())
    payload["hardware_control_scope"] = "diagnostic_display_only"
    if error is not None:
        payload["error"] = error
    return payload


def write_oled_status(*, plan: dict[str, Any], dry_run: bool, bus: Path, address: int, driver: str) -> dict[str, Any]:
    if dry_run:
        return build_oled_status_payload(
            plan=plan,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver,
            write_status="dry_run",
            dry_run=True,
        )
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=plan_oled_message(plan))
        return build_oled_status_payload(
            plan=plan,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_oled_status_payload(
            plan=plan,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=None,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def led_bits_for_plan(plan: dict[str, Any], *, blocked_bit: int, wait_approval_bit: int, ready_bit: int) -> int:
    if plan["status"] == "ready_for_manual_uplink_trial":
        bit = ready_bit
    elif plan["status"] == "waiting_for_operator_approval":
        bit = wait_approval_bit
    else:
        bit = blocked_bit
    return 1 << (bit - 1)


def build_led_status_payload(
    *,
    plan: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    blocked_bit: int,
    wait_approval_bit: int,
    ready_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "pi_wio_e5_lorawan_uplink_trial_plan_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{led_bits_for_plan(plan, blocked_bit=blocked_bit, wait_approval_bit=wait_approval_bit, ready_bit=ready_bit):03x}",
        "plan_status": plan["status"],
        "blocked_led_bit": blocked_bit,
        "wait_approval_led_bit": wait_approval_bit,
        "ready_led_bit": ready_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
    }
    payload.update(boundary_fields())
    payload["hardware_control_scope"] = "diagnostic_indicator_only"
    if error is not None:
        payload["error"] = error
    return payload


def blink_led_status(
    *,
    plan: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    blocked_bit: int,
    wait_approval_bit: int,
    ready_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return build_led_status_payload(
            plan=plan,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            blocked_bit=blocked_bit,
            wait_approval_bit=wait_approval_bit,
            ready_bit=ready_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )
    writer = None
    try:
        writer = make_gpio_writer()
        bits = led_bits_for_plan(
            plan,
            blocked_bit=blocked_bit,
            wait_approval_bit=wait_approval_bit,
            ready_bit=ready_bit,
        )
        import time

        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_led_status_payload(
            plan=plan,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            blocked_bit=blocked_bit,
            wait_approval_bit=wait_approval_bit,
            ready_bit=ready_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_led_status_payload(
            plan=plan,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            blocked_bit=blocked_bit,
            wait_approval_bit=wait_approval_bit,
            ready_bit=ready_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if writer is not None:
            writer.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan a Wio-E5 LoRaWAN client uplink trial without transmitting RF.")
    parser.add_argument("--wio-at-jsonl", type=Path, default=DEFAULT_WIO_AT_JSONL)
    parser.add_argument("--gateway-rx-jsonl", type=Path, default=DEFAULT_GATEWAY_RX_JSONL)
    parser.add_argument("--uplink-jsonl", type=Path, default=DEFAULT_UPLINK_JSONL)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--region-profile", choices=("AS923_2",), default="AS923_2")
    parser.add_argument("--frequency-hz", type=parse_frequency_hz, default=DEFAULT_FREQUENCY_HZ)
    parser.add_argument("--client-label", default="wio-e5-client-1")
    parser.add_argument("--mission-id", default="scout-alpha-lora-bench")
    parser.add_argument("--hash-salt", default="scout-local-wio-uplink-plan-v0")
    parser.add_argument("--operator-approval-token")
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
    parser.add_argument("--led-wait-approval-bit", type=parse_led_bit, default=DEFAULT_LED_WAIT_APPROVAL_BIT)
    parser.add_argument("--led-ready-bit", type=parse_led_bit, default=DEFAULT_LED_READY_BIT)
    parser.add_argument("--led-blink-count", type=parse_positive_int, default=2)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float, default=0.25)
    parser.add_argument("--led-dry-run", action="store_true")
    args = parser.parse_args(argv)

    wio_records, wio_invalid, wio_exists = read_jsonl(args.wio_at_jsonl)
    gateway_records, gateway_invalid, gateway_exists = read_jsonl(args.gateway_rx_jsonl)
    uplink_records, uplink_invalid, uplink_exists = read_jsonl(args.uplink_jsonl)
    wio_summary = summarize_wio_at(
        wio_records,
        invalid_count=wio_invalid,
        file_exists=wio_exists,
        hash_salt=args.hash_salt,
    )
    wio_summary["path"] = str(args.wio_at_jsonl)
    gateway_summary = summarize_gateway_rx(
        gateway_records,
        invalid_count=gateway_invalid,
        file_exists=gateway_exists,
    )
    gateway_summary["path"] = str(args.gateway_rx_jsonl)
    uplink_summary = summarize_existing_uplinks(
        uplink_records,
        invalid_count=uplink_invalid,
        file_exists=uplink_exists,
    )
    uplink_summary["path"] = str(args.uplink_jsonl)
    plan = build_plan(
        wio_summary=wio_summary,
        gateway_summary=gateway_summary,
        uplink_summary=uplink_summary,
        region_profile=args.region_profile,
        frequency_hz=args.frequency_hz,
        client_label=args.client_label,
        mission_id=args.mission_id,
        operator_approval_token=args.operator_approval_token,
    )

    led_defaults = PORT_DEFAULTS[args.led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else led_defaults["data_gpio"]
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else led_defaults["clock_gpio"]

    plan["oled_status_updates"] = []
    plan["led_status_updates"] = []
    if args.oled_status:
        plan["oled_status_updates"].append(
            write_oled_status(
                plan=plan,
                dry_run=args.oled_dry_run,
                bus=args.oled_bus,
                address=args.oled_address,
                driver=args.oled_driver,
            )
        )
    if args.led_status:
        plan["led_status_updates"].append(
            blink_led_status(
                plan=plan,
                port=args.led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                blocked_bit=args.led_blocked_bit,
                wait_approval_bit=args.led_wait_approval_bit,
                ready_bit=args.led_ready_bit,
                blink_count=args.led_blink_count,
                blink_seconds=args.led_blink_seconds,
                dry_run=args.led_dry_run,
            )
        )

    append_jsonl(plan, args.output_jsonl)
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
