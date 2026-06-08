from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tools.keypad_command_candidate_evidence import (
        CandidatePolicy,
        build_candidate_evidence_flow,
        candidate_oled_message,
        led_bits_for_candidate_status,
    )
    from tools.keypad_local_diagnostic_command_dispatch import (
        build_local_diagnostic_dispatch_events,
        dispatch_oled_message,
        led_bits_for_dispatch_status,
    )
    from tools.pi_grove_led_bar_smoke import (
        DEFAULT_PORT as DEFAULT_LED_PORT,
        PORT_DEFAULTS,
        clear_led_bar,
        make_gpio_writer,
        write_led_bar_bits,
    )
    from tools.pi_keypad_4x4_smoke import (
        DEFAULT_GROVE_PORTS,
        PHYSICAL_LABEL_LAYOUT,
        build_summary as build_keypad_summary,
        parse_grove_ports,
        parse_gpio_list,
        parse_non_negative_float,
        parse_positive_float,
        parse_simulated_keys,
        rows_cols_from_grove_ports,
        scan_keypad_events,
    )
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from keypad_command_candidate_evidence import (
        CandidatePolicy,
        build_candidate_evidence_flow,
        candidate_oled_message,
        led_bits_for_candidate_status,
    )
    from keypad_local_diagnostic_command_dispatch import (
        build_local_diagnostic_dispatch_events,
        dispatch_oled_message,
        led_bits_for_dispatch_status,
    )
    from pi_grove_led_bar_smoke import (
        DEFAULT_PORT as DEFAULT_LED_PORT,
        PORT_DEFAULTS,
        clear_led_bar,
        make_gpio_writer,
        write_led_bar_bits,
    )
    from pi_keypad_4x4_smoke import (
        DEFAULT_GROVE_PORTS,
        PHYSICAL_LABEL_LAYOUT,
        build_summary as build_keypad_summary,
        parse_grove_ports,
        parse_gpio_list,
        parse_non_negative_float,
        parse_positive_float,
        parse_simulated_keys,
        rows_cols_from_grove_ports,
        scan_keypad_events,
    )
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_scout_agent_keypad_command"
HARDWARE_KIND = "matrix_keypad_4x4_agent_command_bridge"
DEFAULT_LED_BLINK_SECONDS = 0.25

ROLE_TO_COMMAND = {
    "numeric_code_candidate": "scout.keypad.numeric_code_candidate",
    "sos_arm_candidate": "scout.keypad.sos_arm_candidate",
    "ack_i_am_ok_candidate": "scout.keypad.ack_i_am_ok_candidate",
    "mark_event_candidate": "scout.keypad.mark_event_candidate",
    "mode_page_candidate": "scout.keypad.mode_page_candidate",
    "back_or_silence_candidate": "scout.keypad.back_or_silence_candidate",
    "confirm_candidate": "scout.keypad.confirm_candidate",
}

COMMAND_LABELS = {
    "scout.keypad.numeric_code_candidate": "NUMERIC",
    "scout.keypad.sos_arm_candidate": "SOS ARM",
    "scout.keypad.ack_i_am_ok_candidate": "ACK OK",
    "scout.keypad.mark_event_candidate": "MARK EVENT",
    "scout.keypad.mode_page_candidate": "MODE PAGE",
    "scout.keypad.back_or_silence_candidate": "BACK",
    "scout.keypad.confirm_candidate": "CONFIRM",
}


def load_request(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_agent_key_event(
    *,
    keypad_event: dict[str, Any],
    visual_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    role = str(keypad_event.get("suggested_control_role") or "numeric_code_candidate")
    command_id = ROLE_TO_COMMAND.get(role, "scout.keypad.numeric_code_candidate")
    event = {
        "captured_at": str(keypad_event.get("captured_at") or datetime.now(timezone.utc).isoformat()),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "event": "agent_key_command_candidate",
        "key": keypad_event["key"],
        "physical_label": keypad_event["physical_label"],
        "physical_label_layout": PHYSICAL_LABEL_LAYOUT,
        "row_index": keypad_event["row_index"],
        "col_index": keypad_event["col_index"],
        "row_gpio": keypad_event["row_gpio"],
        "col_gpio": keypad_event["col_gpio"],
        "sequence": keypad_event["sequence"],
        "suggested_control_role": role,
        "agent_command_id": command_id,
        "skill_candidate_id": command_id.replace("scout.keypad.", "scout.skill.keypad."),
        "agent_command_status": "captured_candidate",
        "agent_command_execution_allowed": False,
        "sos_gesture_detected": False,
        "phase1_safety_decision_change_allowed": False,
        "safety_level_mutation_allowed": False,
        "live_safety_api_called": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_agent_command_feedback_only",
        "visual_updates": visual_updates,
    }
    return event


def agent_oled_message(event: dict[str, Any]) -> str:
    command_label = COMMAND_LABELS.get(str(event["agent_command_id"]), "KEY CMD")
    lines = [
        "SCOUT AGENT",
        f"{event['physical_label']} {command_label}",
        f"KEY {event['key']}",
        "CANDIDATE",
        "NO SAFETY MUT",
    ]
    return "\n".join(line[:16] for line in lines)


def led_bits_for_agent_event(event: dict[str, Any]) -> int:
    key_index = int(event["row_index"]) * 4 + int(event["col_index"])
    return 1 << (key_index % 10)


def write_oled_agent_status(
    *,
    event: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    if "dispatch_status" in event:
        message = dispatch_oled_message(event)
    elif "candidate_status" in event:
        message = candidate_oled_message(event)
    else:
        message = agent_oled_message(event)
    payload = {
        "target": "oled",
        "write_status": "dry_run" if dry_run else "ok",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": message,
    }
    if dry_run:
        return payload
    try:
        payload["driver_attempted"] = write_display(bus=bus, address=address, driver=driver, message=message)
    except Exception as exc:
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def blink_led_agent_status(
    *,
    event: dict[str, Any],
    dry_run: bool,
    port: str,
    data_gpio: int,
    clock_gpio: int,
    blink_seconds: float,
) -> dict[str, Any]:
    if "dispatch_status" in event:
        bits = led_bits_for_dispatch_status(event)
    elif "candidate_status" in event:
        bits = led_bits_for_candidate_status(event)
    else:
        bits = led_bits_for_agent_event(event)
    payload = {
        "target": "led_bar",
        "write_status": "dry_run" if dry_run else "ok",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "blink_seconds": blink_seconds,
    }
    if dry_run:
        return payload
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        time.sleep(blink_seconds)
        clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
    except Exception as exc:
        payload["write_status"] = "error"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if writer is not None:
            writer.close()
    return payload


def write_visual_feedback(
    *,
    event: dict[str, Any],
    oled_status: bool,
    oled_dry_run: bool,
    oled_bus: Path,
    oled_address: int,
    oled_driver: str,
    led_status: bool,
    led_dry_run: bool,
    led_port: str,
    led_data_gpio: int,
    led_clock_gpio: int,
    led_blink_seconds: float,
) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    if oled_status:
        updates.append(
            write_oled_agent_status(
                event=event,
                dry_run=oled_dry_run,
                bus=oled_bus,
                address=oled_address,
                driver=oled_driver,
            )
        )
    if led_status:
        updates.append(
            blink_led_agent_status(
                event=event,
                dry_run=led_dry_run,
                port=led_port,
                data_gpio=led_data_gpio,
                clock_gpio=led_clock_gpio,
                blink_seconds=led_blink_seconds,
            )
        )
    return updates


def append_jsonl(payloads: list[dict[str, Any]], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_keypad_command_bridge(
    *,
    rows: list[int],
    cols: list[int],
    grove_ports: list[str] | None,
    active_low: bool,
    duration_seconds: float,
    poll_interval_ms: float,
    debounce_ms: float,
    dry_run: bool,
    simulated_keys: list[str],
    output_jsonl: Path | None,
    visual_options: dict[str, Any],
    candidate_policy: CandidatePolicy,
    dispatch_confirmed_local: bool,
) -> dict[str, Any]:
    visual_options = dict(visual_options)
    if dry_run:
        visual_options["oled_dry_run"] = True
        visual_options["led_dry_run"] = True
    agent_key_events: list[dict[str, Any]] = []
    candidate_events: list[dict[str, Any]] = []
    dispatch_events: list[dict[str, Any]] = []
    incremental_policy = CandidatePolicy(
        confirmation_timeout_seconds=candidate_policy.confirmation_timeout_seconds,
        confirmation_key_physical_label=candidate_policy.confirmation_key_physical_label,
        expire_pending_at_end=False,
    )

    def process_keypad_event(keypad_event: dict[str, Any]) -> None:
        event = build_agent_key_event(keypad_event=keypad_event, visual_updates=[])
        agent_key_events.append(event)
        rebuilt_candidate_events = build_candidate_evidence_flow(agent_key_events, policy=incremental_policy)
        new_candidate_events = rebuilt_candidate_events[len(candidate_events) :]
        for candidate_event in new_candidate_events:
            candidate_event["visual_updates"] = write_visual_feedback(event=candidate_event, **visual_options)
        candidate_events.extend(new_candidate_events)

        new_dispatch_events = build_local_diagnostic_dispatch_events(
            new_candidate_events,
            dispatch_enabled=dispatch_confirmed_local,
            dry_run=dry_run,
        )
        for dispatch_event in new_dispatch_events:
            dispatch_event["visual_updates"] = write_visual_feedback(event=dispatch_event, **visual_options)
        dispatch_events.extend(new_dispatch_events)

    keypad_events = scan_keypad_events(
        rows=rows,
        cols=cols,
        grove_ports=grove_ports,
        active_low=active_low,
        duration_seconds=duration_seconds,
        poll_interval_ms=poll_interval_ms,
        debounce_ms=debounce_ms,
        dry_run=dry_run,
        simulated_keys=simulated_keys,
        visual_options=_disabled_keypad_visual_options(),
        event_callback=process_keypad_event,
    )
    final_candidate_events = build_candidate_evidence_flow(agent_key_events, policy=candidate_policy)
    final_new_candidate_events = final_candidate_events[len(candidate_events) :]
    for event in final_new_candidate_events:
        event["visual_updates"] = write_visual_feedback(event=event, **visual_options)
    candidate_events.extend(final_new_candidate_events)

    append_jsonl([*candidate_events, *dispatch_events], output_jsonl)
    return build_summary(
        rows=rows,
        cols=cols,
        grove_ports=grove_ports,
        active_low=active_low,
        duration_seconds=duration_seconds,
        dry_run=dry_run,
        keypad_events=keypad_events,
        agent_key_events=agent_key_events,
        candidate_events=candidate_events,
        dispatch_events=dispatch_events,
        output_jsonl=output_jsonl,
        candidate_policy=candidate_policy,
        dispatch_confirmed_local=dispatch_confirmed_local,
    )


def build_summary(
    *,
    rows: list[int],
    cols: list[int],
    grove_ports: list[str] | None,
    active_low: bool,
    duration_seconds: float,
    dry_run: bool,
    keypad_events: list[dict[str, Any]],
    agent_key_events: list[dict[str, Any]],
    candidate_events: list[dict[str, Any]],
    dispatch_events: list[dict[str, Any]],
    output_jsonl: Path | None,
    candidate_policy: CandidatePolicy,
    dispatch_confirmed_local: bool,
) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "artifact_kind": "scout_agent_keypad_command_bridge",
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "rows": rows,
        "cols": cols,
        "grove_ports": grove_ports,
        "physical_label_layout": PHYSICAL_LABEL_LAYOUT,
        "active_mode": "active_low" if active_low else "active_high",
        "duration_seconds": duration_seconds,
        "dry_run": dry_run,
        "event_count": len(candidate_events),
        "dispatch_event_count": len(dispatch_events),
        "jsonl_event_count": len(candidate_events) + len(dispatch_events),
        "keypad_summary": build_keypad_summary(
            rows=rows,
            cols=cols,
            grove_ports=grove_ports,
            active_low=active_low,
            duration_seconds=duration_seconds,
            dry_run=dry_run,
            events=keypad_events,
        ),
        "agent_key_events": agent_key_events,
        "events": candidate_events,
        "dispatch_events": dispatch_events,
        "output_jsonl": str(output_jsonl) if output_jsonl is not None else None,
        "candidate_evidence_model": "keypad_command_candidate_v1",
        "local_diagnostic_dispatch_model": "keypad_local_diagnostic_dispatch_v1",
        "dispatch_confirmed_local": dispatch_confirmed_local,
        "confirmation_timeout_seconds": candidate_policy.confirmation_timeout_seconds,
        "confirmation_key_physical_label": candidate_policy.confirmation_key_physical_label,
        "expire_pending_at_end": candidate_policy.expire_pending_at_end,
        "agent_command_execution_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "safety_level_mutation_allowed": False,
        "live_safety_api_called": False,
        "live_safety_api_mutation_allowed": False,
        "remote_outbound_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_scope": "agent_command_candidate_evidence_only",
    }


def _disabled_keypad_visual_options() -> dict[str, Any]:
    return {
        "oled_status": False,
        "oled_dry_run": True,
        "oled_bus": Path("/dev/i2c-1"),
        "oled_address": 0x3C,
        "oled_driver": "sh1107g",
        "led_status": False,
        "led_dry_run": True,
        "led_port": DEFAULT_LED_PORT,
        "led_data_gpio": PORT_DEFAULTS[DEFAULT_LED_PORT]["data_gpio"],
        "led_clock_gpio": PORT_DEFAULTS[DEFAULT_LED_PORT]["clock_gpio"],
        "led_blink_seconds": 0.0,
    }


def _request_bool(request: dict[str, Any], key: str, default: bool) -> bool:
    value = request.get(key, default)
    return bool(value)


def _request_float(request: dict[str, Any], key: str, default: float) -> float:
    value = request.get(key, default)
    return float(value)


def _request_path(request: dict[str, Any], key: str, default: Path | None = None) -> Path | None:
    value = request.get(key)
    if value in {None, ""}:
        return default
    return Path(str(value))


def _request_simulated_keys(request: dict[str, Any], cli_value: list[str] | None) -> list[str]:
    if cli_value is not None:
        return cli_value
    value = request.get("simulate_keys", [])
    if isinstance(value, list):
        return parse_simulated_keys(",".join(str(item) for item in value))
    return parse_simulated_keys(str(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bridge Scout dev keypad events into agent command candidates with OLED/LED feedback."
    )
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--grove-ports", type=parse_grove_ports)
    parser.add_argument("--rows", type=parse_gpio_list)
    parser.add_argument("--cols", type=parse_gpio_list)
    parser.add_argument("--duration-seconds", type=parse_non_negative_float)
    parser.add_argument("--poll-interval-ms", type=parse_positive_float)
    parser.add_argument("--debounce-ms", type=parse_non_negative_float)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--active-low", dest="active_low", action="store_true", default=None)
    mode.add_argument("--active-high", dest="active_low", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--simulate-keys", type=parse_simulated_keys)
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path)
    parser.add_argument("--oled-address", type=parse_address)
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"))
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS))
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-blink-seconds", type=parse_non_negative_float)
    parser.add_argument("--led-dry-run", action="store_true")
    parser.add_argument("--confirmation-timeout-seconds", type=parse_non_negative_float)
    parser.add_argument("--no-expire-pending-at-end", action="store_true")
    parser.add_argument("--dispatch-confirmed-local", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    request = load_request(args.input)
    if (args.rows is None) != (args.cols is None):
        parser.error("--rows and --cols must be provided together")

    if args.rows is not None:
        rows = args.rows
        cols = args.cols or []
        grove_ports = None
    else:
        grove_ports = args.grove_ports or parse_grove_ports(
            str(request.get("grove_ports", ",".join(DEFAULT_GROVE_PORTS)))
        )
        rows, cols = rows_cols_from_grove_ports(grove_ports)

    led_port = args.led_port or str(request.get("led_port", DEFAULT_LED_PORT))
    led_defaults = PORT_DEFAULTS[led_port]
    led_data_gpio = args.led_data_gpio if args.led_data_gpio is not None else int(
        request.get("led_data_gpio", led_defaults["data_gpio"])
    )
    led_clock_gpio = args.led_clock_gpio if args.led_clock_gpio is not None else int(
        request.get("led_clock_gpio", led_defaults["clock_gpio"])
    )

    dry_run = args.dry_run or _request_bool(request, "dry_run", False)
    output_jsonl = args.output_jsonl or _request_path(request, "output_jsonl")
    visual_options = {
        "oled_status": args.oled_status or _request_bool(request, "oled_status", False),
        "oled_dry_run": args.oled_dry_run or _request_bool(request, "oled_dry_run", dry_run),
        "oled_bus": args.oled_bus or _request_path(request, "oled_bus", Path("/dev/i2c-1")),
        "oled_address": args.oled_address
        if args.oled_address is not None
        else parse_address(str(request.get("oled_address", "0x3c"))),
        "oled_driver": args.oled_driver or str(request.get("oled_driver", "sh1107g")),
        "led_status": args.led_status or _request_bool(request, "led_status", False),
        "led_dry_run": args.led_dry_run or _request_bool(request, "led_dry_run", dry_run),
        "led_port": led_port,
        "led_data_gpio": led_data_gpio,
        "led_clock_gpio": led_clock_gpio,
        "led_blink_seconds": args.led_blink_seconds
        if args.led_blink_seconds is not None
        else _request_float(request, "led_blink_seconds", DEFAULT_LED_BLINK_SECONDS),
    }
    candidate_policy = CandidatePolicy(
        confirmation_timeout_seconds=args.confirmation_timeout_seconds
        if args.confirmation_timeout_seconds is not None
        else _request_float(request, "confirmation_timeout_seconds", 10.0),
        expire_pending_at_end=not (
            args.no_expire_pending_at_end or _request_bool(request, "no_expire_pending_at_end", False)
        ),
    )

    summary = run_keypad_command_bridge(
        rows=rows,
        cols=cols,
        grove_ports=grove_ports,
        active_low=args.active_low if args.active_low is not None else _request_bool(request, "active_low", False),
        duration_seconds=args.duration_seconds
        if args.duration_seconds is not None
        else _request_float(request, "duration_seconds", 30.0),
        poll_interval_ms=args.poll_interval_ms
        if args.poll_interval_ms is not None
        else _request_float(request, "poll_interval_ms", 25.0),
        debounce_ms=args.debounce_ms if args.debounce_ms is not None else _request_float(request, "debounce_ms", 120.0),
        dry_run=dry_run,
        simulated_keys=_request_simulated_keys(request, args.simulate_keys),
        output_jsonl=output_jsonl,
        visual_options=visual_options,
        candidate_policy=candidate_policy,
        dispatch_confirmed_local=args.dispatch_confirmed_local
        or _request_bool(request, "dispatch_confirmed_local", False),
    )
    write_json(summary, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
