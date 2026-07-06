#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
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


SOURCE = "pi_sx1303_gateway_rx_smoke"
HARDWARE_KIND = "sx1303_lorawan_gateway_hat"
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl")
DEFAULT_CHIRPSTACK_ROOT = Path("/data/scout/providers/lora/chirpstack-docker")
DEFAULT_TCP_PORTS = (1883, 3001, 8080, 8090)
DEFAULT_UDP_PORTS = (1700,)
DEFAULT_LED_READY_BIT = 8
DEFAULT_LED_WARN_BIT = 1
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
        "hardware_control_scope": "diagnostic_gateway_rx_readiness_only",
    }


def run_readonly_command(command: Sequence[str], *, timeout_seconds: float, cwd: Path | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd is not None else None,
        )
    except FileNotFoundError as exc:
        return {
            "command": list(command),
            "status": "command_missing",
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": list(command),
            "status": "timeout",
            "returncode": None,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    return {
        "command": list(command),
        "status": "ok" if result.returncode == 0 else "nonzero",
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def parse_docker_ps(text: str) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            name, status, ports = parts[0], parts[1], "\t".join(parts[2:])
        elif len(parts) == 2:
            name, status, ports = parts[0], parts[1], ""
        else:
            name, status, ports = parts[0], "", ""
        lower_name = name.lower()
        containers.append(
            {
                "name": name,
                "status": status,
                "ports": ports,
                "running": "up" in status.lower(),
                "roles": container_roles(lower_name),
            }
        )
    return containers


def container_roles(lower_name: str) -> list[str]:
    roles: list[str] = []
    if "gateway-bridge-basicstation" in lower_name:
        roles.append("basicstation_bridge")
    if "gateway-bridge" in lower_name and "basicstation" not in lower_name:
        roles.append("udp_gateway_bridge")
    if lower_name == "chirpstack" or lower_name.endswith("chirpstack-1"):
        roles.append("chirpstack")
    if "mosquitto" in lower_name or "mqtt" in lower_name:
        roles.append("mqtt_broker")
    if "postgres" in lower_name:
        roles.append("postgres")
    if "redis" in lower_name:
        roles.append("redis")
    if "lora_pkt_fwd" in lower_name or "packet-forwarder" in lower_name or "packet_forwarder" in lower_name:
        roles.append("packet_forwarder")
    return roles


def summarize_containers(containers: Sequence[dict[str, Any]]) -> dict[str, Any]:
    running_roles = {
        role
        for item in containers
        if item.get("running")
        for role in item.get("roles", [])
    }
    return {
        "container_count": len(containers),
        "running_container_count": sum(1 for item in containers if item.get("running")),
        "running_roles": sorted(running_roles),
        "udp_gateway_bridge_running": "udp_gateway_bridge" in running_roles,
        "basicstation_bridge_running": "basicstation_bridge" in running_roles,
        "chirpstack_running": "chirpstack" in running_roles,
        "mqtt_broker_running": "mqtt_broker" in running_roles,
        "packet_forwarder_running": "packet_forwarder" in running_roles,
    }


def inspect_tcp_ports(host: str, ports: Sequence[int], *, timeout_seconds: float) -> list[dict[str, Any]]:
    return [inspect_tcp_port(host=host, port=port, timeout_seconds=timeout_seconds) for port in ports]


def inspect_tcp_port(*, host: str, port: int, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return {
                "host": host,
                "port": port,
                "protocol": "tcp",
                "status": "open",
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
    except ConnectionRefusedError:
        return {
            "host": host,
            "port": port,
            "protocol": "tcp",
            "status": "closed",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except TimeoutError:
        return {"host": host, "port": port, "protocol": "tcp", "status": "timeout", "elapsed_ms": int(timeout_seconds * 1000)}
    except OSError as exc:
        return {
            "host": host,
            "port": port,
            "protocol": "tcp",
            "status": "error",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def inspect_udp_ports(ports: Sequence[int], *, ss_lun_output: str) -> list[dict[str, Any]]:
    return [inspect_udp_port(port=port, ss_lun_output=ss_lun_output) for port in ports]


def inspect_udp_port(*, port: int, ss_lun_output: str) -> dict[str, Any]:
    pattern = re.compile(rf"[:.]({port})\b")
    listening = any(pattern.search(line) for line in ss_lun_output.splitlines())
    return {"port": port, "protocol": "udp", "status": "listening" if listening else "not_listening", "probe_packet_sent": False}


def relevant_log_container_names(containers: Sequence[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in containers:
        roles = set(item.get("roles", []))
        if roles.intersection({"udp_gateway_bridge", "basicstation_bridge", "packet_forwarder"}):
            names.append(str(item["name"]))
    return names


def collect_logs(
    *,
    containers: Sequence[dict[str, Any]],
    docker_logs_output: str | None,
    tail_lines: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if docker_logs_output is not None:
        return summarize_log_text(docker_logs_output, source="provided_output")
    per_container: list[dict[str, Any]] = []
    combined: list[str] = []
    for name in relevant_log_container_names(containers):
        result = run_readonly_command(["docker", "logs", "--tail", str(tail_lines), name], timeout_seconds=timeout_seconds)
        text = "\n".join(part for part in (result.get("stdout", ""), result.get("stderr", "")) if part)
        summary = summarize_log_text(text, source=name)
        per_container.append(
            {
                "container": name,
                "command_status": result["status"],
                "line_count": summary["line_count"],
                "uplink_hint_count": summary["uplink_hint_count"],
                "join_hint_count": summary["join_hint_count"],
                "error_hint_count": summary["error_hint_count"],
            }
        )
        combined.append(text)
    merged = summarize_log_text("\n".join(combined), source="docker_logs")
    merged["containers"] = per_container
    return merged


def summarize_log_text(text: str, *, source: str) -> dict[str, Any]:
    lines = [line for line in text.splitlines() if line.strip()]
    uplink_patterns = (
        "event/up",
        "up event",
        "uplink",
        "rxpk",
        "updf",
        "gateway event received",
    )
    join_patterns = ("join", "join-request", "join request")
    error_patterns = ("error", "failed", "panic", "exception")
    lower_lines = [line.lower() for line in lines]
    return {
        "source": source,
        "line_count": len(lines),
        "uplink_hint_count": sum(1 for line in lower_lines if any(token in line for token in uplink_patterns)),
        "join_hint_count": sum(1 for line in lower_lines if any(token in line for token in join_patterns)),
        "error_hint_count": sum(1 for line in lower_lines if any(token in line for token in error_patterns)),
        "raw_log_lines_embedded": False,
    }


def readiness_status(
    *,
    container_summary: dict[str, Any],
    tcp: Sequence[dict[str, Any]],
    udp: Sequence[dict[str, Any]],
    log_summary: dict[str, Any],
    dry_run: bool,
) -> str:
    if dry_run:
        return "dry_run"
    if log_summary["uplink_hint_count"] > 0:
        return "rx_stack_seen_uplink"
    required_containers = (
        container_summary["chirpstack_running"]
        and container_summary["mqtt_broker_running"]
        and (
            container_summary["udp_gateway_bridge_running"]
            or container_summary["basicstation_bridge_running"]
            or container_summary["packet_forwarder_running"]
        )
    )
    tcp_open_count = sum(1 for item in tcp if item["status"] == "open")
    udp_listen_count = sum(1 for item in udp if item["status"] == "listening")
    if required_containers and (tcp_open_count >= 3 or udp_listen_count > 0):
        return "rx_stack_ready_no_uplink"
    if container_summary["running_container_count"] > 0 or tcp_open_count > 0 or udp_listen_count > 0:
        return "rx_stack_incomplete"
    return "rx_stack_missing"


def build_payload(
    *,
    chirpstack_root: Path,
    host: str,
    tcp_ports: Sequence[int],
    udp_ports: Sequence[int],
    docker_ps_output: str,
    ss_lun_output: str,
    docker_ps_status: str,
    ss_lun_status: str,
    log_summary: dict[str, Any],
    dry_run: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    containers = parse_docker_ps(docker_ps_output)
    container_summary = summarize_containers(containers)
    tcp = [] if dry_run else inspect_tcp_ports(host, tcp_ports, timeout_seconds=timeout_seconds)
    udp = inspect_udp_ports(udp_ports, ss_lun_output=ss_lun_output)
    status = readiness_status(
        container_summary=container_summary,
        tcp=tcp,
        udp=udp,
        log_summary=log_summary,
        dry_run=dry_run,
    )
    return {
        "captured_at": _now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "status": status,
        "chirpstack_root": str(chirpstack_root),
        "host": host,
        "docker_ps_status": docker_ps_status,
        "ss_lun_status": ss_lun_status,
        "containers": containers,
        "container_summary": container_summary,
        "tcp": tcp,
        "udp": udp,
        "tcp_open_count": sum(1 for item in tcp if item["status"] == "open"),
        "udp_listen_count": sum(1 for item in udp if item["status"] == "listening"),
        "log_summary": log_summary,
        "uplink_hint_count": log_summary["uplink_hint_count"],
        "join_hint_count": log_summary["join_hint_count"],
        "error_hint_count": log_summary["error_hint_count"],
        "raw_log_lines_embedded": False,
        "readiness_scope": "local_gateway_stack_passive_rx_only",
        **boundary_fields(),
    }


def gateway_oled_message(payload: dict[str, Any]) -> str:
    label = {
        "rx_stack_ready_no_uplink": "RX READY NO UL",
        "rx_stack_seen_uplink": "RX UPLINK HINT",
        "rx_stack_incomplete": "RX INCOMPLETE",
        "rx_stack_missing": "RX MISSING",
        "dry_run": "RX DRY RUN",
    }.get(payload["status"], "RX CHECK")
    lines = [
        "SCOUT LORA RX",
        label,
        f"TCP {payload['tcp_open_count']}",
        f"UDP {payload['udp_listen_count']}",
        f"ULOG {payload['uplink_hint_count']}",
        "NO RF TX",
    ]
    return "\n".join(line[:16] for line in lines)


def write_oled_status(
    *,
    payload: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    dry_run: bool,
) -> dict[str, Any]:
    message = gateway_oled_message(payload)
    status_payload = {
        "captured_at": _now_iso(),
        "source": "pi_sx1303_gateway_rx_smoke_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "message": message,
        "dry_run": dry_run,
        "status": payload["status"],
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if dry_run:
        return {**status_payload, "write_status": "dry_run", "driver_attempted": driver}
    try:
        driver_attempted = write_display(bus=bus, address=address, driver=driver, message=message)
        return {**status_payload, "write_status": "ok", "driver_attempted": driver_attempted}
    except Exception as exc:
        return {
            **status_payload,
            "write_status": "error",
            "driver_attempted": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def led_bits_for_status(status: str, *, ready_bit: int, warn_bit: int, uplink_bit: int) -> int:
    if status == "rx_stack_seen_uplink":
        return 1 << (uplink_bit - 1)
    if status in {"rx_stack_ready_no_uplink", "dry_run"}:
        return 1 << (ready_bit - 1)
    return 1 << (warn_bit - 1)


def write_led_status(
    *,
    payload: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ready_bit: int,
    warn_bit: int,
    uplink_bit: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    bits = led_bits_for_status(payload["status"], ready_bit=ready_bit, warn_bit=warn_bit, uplink_bit=uplink_bit)
    status_payload = {
        "captured_at": _now_iso(),
        "source": "pi_sx1303_gateway_rx_smoke_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "status": payload["status"],
        "ready_led_bit": ready_bit,
        "warn_led_bit": warn_bit,
        "uplink_led_bit": uplink_bit,
        "blink_seconds": blink_seconds,
        "write_status": "dry_run" if dry_run else "ok",
        "dry_run": dry_run,
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if dry_run:
        return status_payload
    writer = None
    try:
        writer = make_gpio_writer()
        write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
        time.sleep(blink_seconds)
        clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
        return status_payload
    except Exception as exc:
        return {
            **status_payload,
            "write_status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if writer is not None:
            writer.close()


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    parsed: list[int] = []
    for item in parse_csv(value):
        try:
            port = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid integer value: {item}") from exc
        if port < 1:
            raise argparse.ArgumentTypeError("port values must be positive")
        parsed.append(port)
    return parsed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    parser = argparse.ArgumentParser(description="Passively inspect SX1303 gateway RX readiness without RF TX or uplink.")
    parser.add_argument("--chirpstack-root", type=Path, default=DEFAULT_CHIRPSTACK_ROOT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--tcp-ports", type=parse_int_csv, default=list(DEFAULT_TCP_PORTS))
    parser.add_argument("--udp-ports", type=parse_int_csv, default=list(DEFAULT_UDP_PORTS))
    parser.add_argument("--tail-lines", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=_positive_float, default=3.0)
    parser.add_argument("--docker-ps-output", help="Use this docker ps fixture output instead of running docker.")
    parser.add_argument("--ss-lun-output", help="Use this ss -lun fixture output instead of running ss.")
    parser.add_argument("--docker-logs-output", help="Use this log fixture output instead of running docker logs.")
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-output-jsonl", action="store_true")
    parser.add_argument("--oled-status", action="store_true")
    parser.add_argument("--oled-bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--oled-address", type=parse_address, default=0x3C)
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--oled-dry-run", action="store_true")
    parser.add_argument("--led-status", action="store_true")
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=DEFAULT_LED_PORT)
    parser.add_argument("--led-data-gpio", type=int)
    parser.add_argument("--led-clock-gpio", type=int)
    parser.add_argument("--led-ready-bit", type=_led_bit, default=DEFAULT_LED_READY_BIT)
    parser.add_argument("--led-warn-bit", type=_led_bit, default=DEFAULT_LED_WARN_BIT)
    parser.add_argument("--led-uplink-bit", type=_led_bit, default=DEFAULT_LED_UPLINK_BIT)
    parser.add_argument("--led-blink-seconds", type=_non_negative_float, default=0.35)
    parser.add_argument("--led-dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.tail_lines < 1:
        parser.error("--tail-lines must be at least 1")

    if args.dry_run:
        docker_ps_result = {"status": "dry_run", "stdout": args.docker_ps_output or "", "stderr": ""}
        ss_lun_result = {"status": "dry_run", "stdout": args.ss_lun_output or "", "stderr": ""}
    else:
        docker_ps_result = (
            {"status": "provided_output", "stdout": args.docker_ps_output, "stderr": ""}
            if args.docker_ps_output is not None
            else run_readonly_command(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
                timeout_seconds=args.timeout_seconds,
            )
        )
        ss_lun_result = (
            {"status": "provided_output", "stdout": args.ss_lun_output, "stderr": ""}
            if args.ss_lun_output is not None
            else run_readonly_command(["ss", "-lun"], timeout_seconds=args.timeout_seconds)
        )

    containers = parse_docker_ps(docker_ps_result.get("stdout", ""))
    log_summary = collect_logs(
        containers=containers,
        docker_logs_output=args.docker_logs_output if not args.dry_run else args.docker_logs_output or "",
        tail_lines=int(args.tail_lines),
        timeout_seconds=float(args.timeout_seconds),
    )
    payload = build_payload(
        chirpstack_root=args.chirpstack_root.expanduser(),
        host=str(args.host),
        tcp_ports=tuple(args.tcp_ports),
        udp_ports=tuple(args.udp_ports),
        docker_ps_output=docker_ps_result.get("stdout", ""),
        ss_lun_output=ss_lun_result.get("stdout", ""),
        docker_ps_status=str(docker_ps_result.get("status")),
        ss_lun_status=str(ss_lun_result.get("status")),
        log_summary=log_summary,
        dry_run=bool(args.dry_run),
        timeout_seconds=float(args.timeout_seconds),
    )

    if args.oled_status:
        payload["oled_status_updates"] = [
            write_oled_status(
                payload=payload,
                bus=args.oled_bus.expanduser(),
                address=int(args.oled_address),
                driver=str(args.oled_driver),
                dry_run=bool(args.oled_dry_run),
            )
        ]
    if args.led_status:
        defaults = PORT_DEFAULTS[args.led_port]
        payload["led_status_updates"] = [
            write_led_status(
                payload=payload,
                port=str(args.led_port),
                data_gpio=args.led_data_gpio if args.led_data_gpio is not None else int(defaults["data_gpio"]),
                clock_gpio=args.led_clock_gpio if args.led_clock_gpio is not None else int(defaults["clock_gpio"]),
                ready_bit=int(args.led_ready_bit),
                warn_bit=int(args.led_warn_bit),
                uplink_bit=int(args.led_uplink_bit),
                blink_seconds=float(args.led_blink_seconds),
                dry_run=bool(args.led_dry_run),
            )
        ]

    if not args.no_output_jsonl:
        append_jsonl(args.output_jsonl.expanduser(), payload)

    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] in {"rx_stack_ready_no_uplink", "rx_stack_seen_uplink", "dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
