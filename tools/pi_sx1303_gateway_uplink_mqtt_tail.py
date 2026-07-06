#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when copied beside smoke tools on Pi.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_sx1303_gateway_uplink_mqtt_tail"
HARDWARE_KIND = "sx1303_lorawan_gateway_hat"
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_STATUS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl")
DEFAULT_TOPICS = (
    "application/+/device/+/event/up",
    "as923_2/gateway/+/event/up",
)
DEFAULT_LED_WAIT_BIT = 1
DEFAULT_LED_UPLINK_BIT = 9


def boundary_fields() -> dict[str, Any]:
    return {
        "read_only": True,
        "packet_forwarder_started": False,
        "gateway_config_changed": False,
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "join_allowed": False,
        "lorawan_uplink_allowed": False,
        "remote_outbound_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "phase2_brain_writeback": False,
        "outbound_send_performed": False,
        "hardware_control_scope": "diagnostic_gateway_uplink_receive_only",
    }


def build_mosquitto_sub_command(
    *,
    container: str,
    mqtt_host: str,
    mqtt_port: int,
    topics: Sequence[str],
    max_messages: int,
    duration_seconds: int,
) -> list[str]:
    command = [
        "docker",
        "exec",
        container,
        "mosquitto_sub",
        "-h",
        mqtt_host,
        "-p",
        str(mqtt_port),
        "-C",
        str(max_messages),
        "-W",
        str(duration_seconds),
        "-F",
        "%t\t%p",
    ]
    for topic in topics:
        command.extend(["-t", topic])
    return command


def run_mosquitto_sub(command: Sequence[str], *, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return {
            "status": "command_missing",
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "returncode": None,
            "stdout": decode_subprocess_output(exc.stdout),
            "stderr": decode_subprocess_output(exc.stderr),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    return {
        "status": "ok" if result.returncode == 0 else "nonzero",
        "returncode": result.returncode,
        "stdout": decode_subprocess_output(result.stdout),
        "stderr": decode_subprocess_output(result.stderr),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def decode_subprocess_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def parse_mqtt_lines(lines: Sequence[str]) -> tuple[list[dict[str, Any]], int]:
    messages, unparsed_messages, invalid_line_count = parse_mqtt_lines_detailed(lines)
    return messages, invalid_line_count + len(unparsed_messages)


def parse_mqtt_lines_detailed(lines: Sequence[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    messages: list[dict[str, Any]] = []
    unparsed_messages: list[dict[str, Any]] = []
    invalid_line_count = 0
    for line in lines:
        if not line.strip():
            continue
        if "\t" not in line:
            invalid_line_count += 1
            continue
        topic, payload_text = line.split("\t", 1)
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            stripped_topic = topic.strip()
            if topic_kind(stripped_topic) != "unknown":
                unparsed_messages.append(
                    {
                        "topic": stripped_topic,
                        "payload_format": "non_json_or_binary",
                        "payload_text_bytes": len(payload_text.encode("utf-8", errors="replace")),
                    }
                )
            else:
                invalid_line_count += 1
            continue
        if not isinstance(payload, dict):
            invalid_line_count += 1
            continue
        messages.append({"topic": topic.strip(), "payload": payload})
    return messages, unparsed_messages, invalid_line_count


def summarize_uplink_message(message: dict[str, Any], *, hash_salt: str, include_identifiers: bool) -> dict[str, Any]:
    topic = str(message.get("topic", ""))
    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    device_info = payload.get("deviceInfo") if isinstance(payload.get("deviceInfo"), dict) else {}
    tx_info = payload.get("txInfo") if isinstance(payload.get("txInfo"), dict) else {}
    modulation = tx_info.get("modulation") if isinstance(tx_info.get("modulation"), dict) else {}
    lora_mod = modulation.get("lora") if isinstance(modulation.get("lora"), dict) else {}
    rx_items = payload.get("rxInfo") if isinstance(payload.get("rxInfo"), list) else []
    rx_summary = [summarize_rx_info(item, hash_salt=hash_salt, include_identifiers=include_identifiers) for item in rx_items if isinstance(item, dict)]
    data_value = payload.get("data")
    payload_bytes = decoded_payload_length(data_value) if isinstance(data_value, str) else None
    dev_eui = first_non_empty(
        payload.get("devEui"),
        payload.get("dev_eui"),
        device_info.get("devEui"),
        topic_device_eui(topic),
    )
    gateway_ids = [
        first_non_empty(item.get("gatewayId"), item.get("gateway_id"), item.get("gatewayID"))
        for item in rx_items
        if isinstance(item, dict)
    ]
    gateway_ids = [str(item) for item in gateway_ids if item]
    summary = {
        "captured_at": _now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": "uplink_observed",
        "topic": sanitize_topic(topic, include_identifiers=include_identifiers),
        "topic_kind": topic_kind(topic),
        "raw_topic_embedded": bool(include_identifiers),
        "dev_eui_hash": hash_identifier(dev_eui, hash_salt) if dev_eui else None,
        "dev_eui_present": bool(dev_eui),
        "gateway_id_hashes": [hash_identifier(gateway_id, hash_salt) for gateway_id in gateway_ids],
        "gateway_count": len(gateway_ids),
        "frequency_hz": first_non_empty(tx_info.get("frequency"), tx_info.get("frequencyHz"), payload.get("frequency_hz")),
        "spreading_factor": first_non_empty(lora_mod.get("spreadingFactor"), tx_info.get("spreadingFactor"), payload.get("spreading_factor")),
        "bandwidth_hz": first_non_empty(lora_mod.get("bandwidth"), tx_info.get("bandwidth"), payload.get("bandwidth_hz")),
        "code_rate": first_non_empty(lora_mod.get("codeRate"), tx_info.get("codeRate")),
        "f_cnt": first_non_empty(payload.get("fCnt"), payload.get("fcnt"), payload.get("f_cnt")),
        "f_port": first_non_empty(payload.get("fPort"), payload.get("fport"), payload.get("f_port")),
        "confirmed": payload.get("confirmed") if isinstance(payload.get("confirmed"), bool) else None,
        "adr": payload.get("adr") if isinstance(payload.get("adr"), bool) else None,
        "rssi_dbm": min_value([item.get("rssi_dbm") for item in rx_summary]),
        "snr_db": max_value([item.get("snr_db") for item in rx_summary]),
        "crc_status": first_non_empty(*(item.get("crc_status") for item in rx_summary)),
        "rx_info": rx_summary,
        "has_payload_data": isinstance(data_value, str) and bool(data_value),
        "payload_bytes": payload_bytes,
        "raw_payload_embedded": False,
        "raw_payload_data_embedded": False,
        "identifier_policy": "hashed" if not include_identifiers else "plain_identifiers_included_for_local_debug",
        **boundary_fields(),
    }
    if include_identifiers:
        summary["dev_eui"] = dev_eui
        summary["gateway_ids"] = gateway_ids
    return summary


def summarize_unparsed_uplink_message(message: dict[str, Any], *, hash_salt: str, include_identifiers: bool) -> dict[str, Any]:
    topic = str(message.get("topic", ""))
    dev_eui = topic_device_eui(topic)
    summary = {
        "captured_at": _now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": "uplink_observed_unparsed_payload",
        "topic": sanitize_topic(topic, include_identifiers=include_identifiers),
        "topic_kind": topic_kind(topic),
        "raw_topic_embedded": bool(include_identifiers),
        "dev_eui_hash": hash_identifier(dev_eui, hash_salt) if dev_eui else None,
        "dev_eui_present": bool(dev_eui),
        "payload_format": message.get("payload_format") or "non_json_or_binary",
        "payload_parse_status": "not_decoded",
        "payload_text_bytes": message.get("payload_text_bytes"),
        "has_payload_data": None,
        "payload_bytes": None,
        "raw_payload_embedded": False,
        "raw_payload_data_embedded": False,
        "identifier_policy": "hashed" if not include_identifiers else "plain_identifiers_included_for_local_debug",
        **boundary_fields(),
    }
    if include_identifiers:
        summary["dev_eui"] = dev_eui
    return summary


def summarize_rx_info(item: dict[str, Any], *, hash_salt: str, include_identifiers: bool) -> dict[str, Any]:
    gateway_id = first_non_empty(item.get("gatewayId"), item.get("gateway_id"), item.get("gatewayID"))
    summary = {
        "gateway_id_hash": hash_identifier(gateway_id, hash_salt) if gateway_id else None,
        "gateway_id_present": bool(gateway_id),
        "rssi_dbm": first_non_empty(item.get("rssi"), item.get("rssiDbm"), item.get("rssi_dbm")),
        "snr_db": first_non_empty(item.get("snr"), item.get("snrDb"), item.get("snr_db")),
        "channel": item.get("channel"),
        "rf_chain": first_non_empty(item.get("rfChain"), item.get("rf_chain")),
        "crc_status": first_non_empty(item.get("crcStatus"), item.get("crc_status")),
        "location_present": isinstance(item.get("location"), dict),
    }
    if include_identifiers:
        summary["gateway_id"] = gateway_id
    return summary


def topic_kind(topic: str) -> str:
    if "/event/up" in topic and topic.startswith("application/"):
        return "chirpstack_application_up"
    if "/event/up" in topic and "/gateway/" in topic:
        return "chirpstack_gateway_up"
    if "uplink" in topic.lower() or "/event/up" in topic:
        return "uplink_like"
    return "unknown"


def topic_device_eui(topic: str) -> str | None:
    parts = topic.split("/")
    try:
        idx = parts.index("device")
    except ValueError:
        return None
    if idx + 1 < len(parts):
        return parts[idx + 1]
    return None


def sanitize_topic(topic: str, *, include_identifiers: bool) -> str:
    if include_identifiers:
        return topic
    parts = topic.split("/")
    for idx, part in enumerate(parts[:-1]):
        if part in {"application", "device", "gateway"} and idx + 1 < len(parts):
            parts[idx + 1] = "<redacted>"
    return "/".join(parts)


def decoded_payload_length(value: str) -> int | None:
    try:
        return len(base64.b64decode(value, validate=True))
    except Exception:
        return None


def hash_identifier(value: Any, salt: str) -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()
    return digest[:16]


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def min_value(values: Sequence[Any]) -> Any:
    parsed = [value for value in values if isinstance(value, int | float)]
    return min(parsed) if parsed else None


def max_value(values: Sequence[Any]) -> Any:
    parsed = [value for value in values if isinstance(value, int | float)]
    return max(parsed) if parsed else None


def build_status_payload(
    *,
    command_status: str,
    returncode: int | None,
    elapsed_ms: int | None,
    topics: Sequence[str],
    observed_records: Sequence[dict[str, Any]],
    invalid_line_count: int,
    unparsed_line_count: int,
    output_jsonl: Path,
    status_jsonl: Path,
    dry_run: bool,
) -> dict[str, Any]:
    status = "uplink_observed" if observed_records else ("dry_run" if dry_run else "no_uplink_observed")
    return {
        "captured_at": _now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "command_status": command_status,
        "returncode": returncode,
        "elapsed_ms": elapsed_ms,
        "topics": list(topics),
        "observed_uplink_count": len(observed_records),
        "invalid_mqtt_line_count": invalid_line_count,
        "unparsed_mqtt_line_count": unparsed_line_count,
        "output_jsonl": str(output_jsonl),
        "status_jsonl": str(status_jsonl),
        "uplink_jsonl_written": bool(observed_records),
        "raw_payload_embedded": False,
        "raw_payload_data_embedded": False,
        "mqtt_scope": "local_chirpstack_mqtt_subscribe_only",
        **boundary_fields(),
    }


def gateway_oled_message(status_payload: dict[str, Any]) -> str:
    label = "UPLINK OK" if status_payload["observed_uplink_count"] else "WAIT UPLINK"
    if status_payload["status"] == "dry_run":
        label = "DRY RUN"
    lines = [
        "SCOUT LORA UL",
        label,
        f"COUNT {status_payload['observed_uplink_count']}",
        "NO RF TX",
        "NO DOWNLINK",
    ]
    return "\n".join(line[:16] for line in lines)


def write_oled_status(
    *,
    status_payload: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    dry_run: bool,
) -> dict[str, Any]:
    message = gateway_oled_message(status_payload)
    payload = {
        "captured_at": _now_iso(),
        "source": "pi_sx1303_gateway_uplink_mqtt_tail_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": message,
        "dry_run": dry_run,
        "observed_uplink_count": status_payload["observed_uplink_count"],
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if dry_run:
        return {**payload, "write_status": "dry_run", "driver_attempted": driver}
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=message)
        return {**payload, "write_status": "ok", "driver_attempted": driver_attempted}
    except Exception as exc:
        return {**payload, "write_status": "error", "driver_attempted": None, "error": f"{type(exc).__name__}: {exc}"}


def write_led_status(
    *,
    status_payload: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    wait_bit: int,
    uplink_bit: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    selected_bit = uplink_bit if status_payload["observed_uplink_count"] else wait_bit
    bits = 1 << (selected_bit - 1)
    payload = {
        "captured_at": _now_iso(),
        "source": "pi_sx1303_gateway_uplink_mqtt_tail_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "wait_led_bit": wait_bit,
        "uplink_led_bit": uplink_bit,
        "blink_seconds": blink_seconds,
        "write_status": "dry_run" if dry_run else "ok",
        "dry_run": dry_run,
        "observed_uplink_count": status_payload["observed_uplink_count"],
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if dry_run:
        return payload
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        time.sleep(blink_seconds)
        clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
        return payload
    except Exception as exc:
        return {**payload, "write_status": "error", "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if writer is not None:
            writer.close()


def append_jsonl(path: Path, payloads: Sequence[dict[str, Any]]) -> None:
    if not payloads:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def _led_bit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 10:
        raise argparse.ArgumentTypeError("LED bit must be between 1 and 10")
    return parsed


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Passively tail local ChirpStack MQTT uplink events into Scout JSONL evidence.")
    parser.add_argument("--mosquitto-container", default="chirpstack-docker-mosquitto-1")
    parser.add_argument("--mqtt-host", default="127.0.0.1")
    parser.add_argument("--mqtt-port", type=_positive_int, default=1883)
    parser.add_argument("--topics", type=parse_csv, default=list(DEFAULT_TOPICS))
    parser.add_argument("--max-messages", type=_positive_int, default=1)
    parser.add_argument("--duration-seconds", type=_positive_int, default=10)
    parser.add_argument("--fixture-line", action="append", default=[])
    parser.add_argument("--hash-salt", default="scout-local-uplink-smoke-v0")
    parser.add_argument("--include-device-identifiers", action="store_true")
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--status-jsonl", type=Path, default=DEFAULT_STATUS_JSONL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-output-jsonl", action="store_true")
    parser.add_argument("--no-status-jsonl", action="store_true")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=0x3C)
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-wait-bit", type=_led_bit, default=DEFAULT_LED_WAIT_BIT)
    parser.add_argument("--led-uplink-bit", type=_led_bit, default=DEFAULT_LED_UPLINK_BIT)
    parser.add_argument("--led-blink-seconds", type=_non_negative_float, default=0.35)
    parser.add_argument("--led-dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    topics = tuple(args.topics)
    timeout_seconds = float(args.duration_seconds) + 3.0
    if args.fixture_line:
        command_result = {"status": "fixture", "returncode": 0, "stdout": "\n".join(args.fixture_line), "stderr": "", "elapsed_ms": 0}
    elif args.dry_run:
        command_result = {"status": "dry_run", "returncode": None, "stdout": "", "stderr": "", "elapsed_ms": 0}
    else:
        command = build_mosquitto_sub_command(
            container=str(args.mosquitto_container),
            mqtt_host=str(args.mqtt_host),
            mqtt_port=int(args.mqtt_port),
            topics=topics,
            max_messages=int(args.max_messages),
            duration_seconds=int(args.duration_seconds),
        )
        command_result = run_mosquitto_sub(command, timeout_seconds=timeout_seconds)

    lines = (command_result.get("stdout") or "").splitlines()
    messages, unparsed_messages, invalid_line_count = parse_mqtt_lines_detailed(lines)
    records = [
        summarize_uplink_message(
            message,
            hash_salt=str(args.hash_salt),
            include_identifiers=bool(args.include_device_identifiers),
        )
        for message in messages
    ]
    records.extend(
        summarize_unparsed_uplink_message(
            message,
            hash_salt=str(args.hash_salt),
            include_identifiers=bool(args.include_device_identifiers),
        )
        for message in unparsed_messages
    )
    status_payload = build_status_payload(
        command_status=str(command_result.get("status")),
        returncode=command_result.get("returncode") if isinstance(command_result.get("returncode"), int) else None,
        elapsed_ms=command_result.get("elapsed_ms") if isinstance(command_result.get("elapsed_ms"), int) else None,
        topics=topics,
        observed_records=records,
        invalid_line_count=invalid_line_count,
        unparsed_line_count=len(unparsed_messages),
        output_jsonl=args.output_jsonl.expanduser(),
        status_jsonl=args.status_jsonl.expanduser(),
        dry_run=bool(args.dry_run),
    )

    if args.oled_status:
        status_payload["oled_status_updates"] = [
            write_oled_status(
                status_payload=status_payload,
                bus=args.oled_bus.expanduser(),
                address=int(args.oled_address),
                driver=str(args.oled_driver),
                dry_run=bool(args.oled_dry_run),
            )
        ]
    if args.led_status:
        defaults = PORT_DEFAULTS[args.led_port]
        status_payload["led_status_updates"] = [
            write_led_status(
                status_payload=status_payload,
                port=str(args.led_port),
                data_gpio=args.led_data_gpio if args.led_data_gpio is not None else int(defaults["data_gpio"]),
                clock_gpio=args.led_clock_gpio if args.led_clock_gpio is not None else int(defaults["clock_gpio"]),
                wait_bit=int(args.led_wait_bit),
                uplink_bit=int(args.led_uplink_bit),
                blink_seconds=float(args.led_blink_seconds),
                dry_run=bool(args.led_dry_run),
            )
        ]

    if not args.no_output_jsonl:
        append_jsonl(args.output_jsonl.expanduser(), records)
    if not args.no_status_jsonl:
        append_jsonl(args.status_jsonl.expanduser(), [status_payload])

    print(json.dumps({"status": status_payload, "records": records}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
