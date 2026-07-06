from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    from tools.pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from tools.pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools copied beside this file.
    from pi_grove_led_bar_smoke import DEFAULT_PORT as DEFAULT_LED_PORT
    from pi_grove_led_bar_smoke import PORT_DEFAULTS, clear_led_bar, make_gpio_writer, write_led_bar_bits
    from pi_oled_i2c_smoke import parse_address, write_display


ARTIFACT_KIND = "scout_sx1303_gateway_observer_status"
ARTIFACT_VERSION = "sx1303_gateway_observer_status.v0"
SOURCE_TOOL = "scout_sx1303_gateway_observer"

DEFAULT_EVIDENCE_DIR = Path("/data/scout/admin/ingress/sx1303_gateway")
DEFAULT_UPLINK_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_GATEWAY_GPS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl")
DEFAULT_RF_PREFLIGHT_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-smoke.jsonl")
DEFAULT_RX_READINESS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl")
DEFAULT_CHIRPSTACK_DOCKER_CONFIG_ROOT = Path("/data/scout/providers/lora/chirpstack-docker/configuration")
DEFAULT_CONFIG_PATHS = (
    Path("/data/scout/lora/global_conf.json"),
    Path("/data/scout/lora/station.conf"),
    Path("/data/scout/lora/chirpstack-gateway-bridge.toml"),
    Path("/data/scout/lora/chirpstack.toml"),
    Path("/data/scout/chirpstack/chirpstack.toml"),
    Path("/data/scout/chirpstack/regions/as923_2.toml"),
    Path("/data/scout/chirpstack/regions/as923.toml"),
    DEFAULT_CHIRPSTACK_DOCKER_CONFIG_ROOT / "chirpstack/chirpstack.toml",
    DEFAULT_CHIRPSTACK_DOCKER_CONFIG_ROOT / "chirpstack/region_as923_2.toml",
    DEFAULT_CHIRPSTACK_DOCKER_CONFIG_ROOT
    / "chirpstack-gateway-bridge/chirpstack-gateway-bridge-basicstation-as923_2.toml",
)
DEFAULT_EXPECTED_REGION_TOKENS = ("AS923", "AS923_2", "AS923_TW_920_925")
DEFAULT_FORBIDDEN_REGION_TOKENS = ("EU868", "US915", "AU915", "CN470", "KR920", "IN865", "RU864")
DEFAULT_TCP_PORTS = (1883, 3001, 8080, 8090)
DEFAULT_UDP_PORTS = (1700,)
DEFAULT_LED_OK_BIT = 8
DEFAULT_LED_WARN_BIT = 1
DEFAULT_LED_FAIL_BIT = 10

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Sx1303GatewayObserverConfig:
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR
    uplink_jsonl: Path = DEFAULT_UPLINK_JSONL
    gateway_gps_jsonl: Path = DEFAULT_GATEWAY_GPS_JSONL
    rf_preflight_jsonl: Path = DEFAULT_RF_PREFLIGHT_JSONL
    rx_readiness_jsonl: Path = DEFAULT_RX_READINESS_JSONL
    config_paths: tuple[Path, ...] = DEFAULT_CONFIG_PATHS
    expected_region_tokens: tuple[str, ...] = DEFAULT_EXPECTED_REGION_TOKENS
    forbidden_region_tokens: tuple[str, ...] = DEFAULT_FORBIDDEN_REGION_TOKENS
    host: str = "127.0.0.1"
    tcp_ports: tuple[int, ...] = DEFAULT_TCP_PORTS
    udp_ports: tuple[int, ...] = DEFAULT_UDP_PORTS
    poll_seconds: float = 10.0
    max_jsonl_records: int = 200
    command_timeout_seconds: float = 2.0
    print_ready: bool = False
    oled_status: bool = False
    oled_dry_run: bool = False
    oled_bus: Path = Path("/dev/i2c-1")
    oled_address: int = 0x3C
    oled_driver: str = "sh1107g"
    led_status: bool = False
    led_dry_run: bool = False
    led_port: str = DEFAULT_LED_PORT
    led_data_gpio: int | None = None
    led_clock_gpio: int | None = None
    led_ok_bit: int = DEFAULT_LED_OK_BIT
    led_warn_bit: int = DEFAULT_LED_WARN_BIT
    led_fail_bit: int = DEFAULT_LED_FAIL_BIT
    led_blink_count: int = 1
    led_blink_seconds: float = 0.15

    @classmethod
    def from_env(cls, prefix: str = "SCOUT_SX1303_GATEWAY_") -> "Sx1303GatewayObserverConfig":
        def read(name: str, default: str | None = None) -> str | None:
            return os.environ.get(f"{prefix}{name}", default)

        return cls(
            evidence_dir=Path(read("EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR)) or DEFAULT_EVIDENCE_DIR).expanduser(),
            uplink_jsonl=Path(read("UPLINK_JSONL", str(DEFAULT_UPLINK_JSONL)) or DEFAULT_UPLINK_JSONL).expanduser(),
            gateway_gps_jsonl=Path(
                read("GATEWAY_GPS_JSONL", str(DEFAULT_GATEWAY_GPS_JSONL)) or DEFAULT_GATEWAY_GPS_JSONL
            ).expanduser(),
            rf_preflight_jsonl=Path(
                read("RF_PREFLIGHT_JSONL", str(DEFAULT_RF_PREFLIGHT_JSONL)) or DEFAULT_RF_PREFLIGHT_JSONL
            ).expanduser(),
            rx_readiness_jsonl=Path(
                read("RX_READINESS_JSONL", str(DEFAULT_RX_READINESS_JSONL)) or DEFAULT_RX_READINESS_JSONL
            ).expanduser(),
            config_paths=tuple(
                Path(item).expanduser()
                for item in parse_csv(read("CONFIG_PATHS", _join_paths(DEFAULT_CONFIG_PATHS)) or "")
            ),
            expected_region_tokens=tuple(
                token.upper() for token in parse_csv(read("EXPECTED_REGION_TOKENS", ",".join(DEFAULT_EXPECTED_REGION_TOKENS)) or "")
            ),
            forbidden_region_tokens=tuple(
                token.upper()
                for token in parse_csv(read("FORBIDDEN_REGION_TOKENS", ",".join(DEFAULT_FORBIDDEN_REGION_TOKENS)) or "")
            ),
            host=read("HOST", "127.0.0.1") or "127.0.0.1",
            tcp_ports=tuple(parse_int_csv(read("TCP_PORTS", ",".join(str(port) for port in DEFAULT_TCP_PORTS)) or "")),
            udp_ports=tuple(parse_int_csv(read("UDP_PORTS", ",".join(str(port) for port in DEFAULT_UDP_PORTS)) or "")),
            poll_seconds=_positive_float(read("POLL_SECONDS"), default=10.0),
            max_jsonl_records=_positive_int(read("MAX_JSONL_RECORDS"), default=200),
            command_timeout_seconds=_positive_float(read("COMMAND_TIMEOUT_SECONDS"), default=2.0),
            print_ready=_bool_env(read("PRINT_READY", "false")),
            oled_status=_bool_env(read("OLED_STATUS", "false")),
            oled_dry_run=_bool_env(read("OLED_DRY_RUN", "false")),
            oled_bus=Path(read("OLED_BUS", "/dev/i2c-1") or "/dev/i2c-1").expanduser(),
            oled_address=parse_address(read("OLED_ADDRESS", "0x3c") or "0x3c"),
            oled_driver=read("OLED_DRIVER", "sh1107g") or "sh1107g",
            led_status=_bool_env(read("LED_STATUS", "false")),
            led_dry_run=_bool_env(read("LED_DRY_RUN", "false")),
            led_port=read("LED_PORT", DEFAULT_LED_PORT) or DEFAULT_LED_PORT,
            led_data_gpio=_optional_int(read("LED_DATA_GPIO")),
            led_clock_gpio=_optional_int(read("LED_CLOCK_GPIO")),
            led_ok_bit=_led_bit(read("LED_OK_BIT"), default=DEFAULT_LED_OK_BIT),
            led_warn_bit=_led_bit(read("LED_WARN_BIT"), default=DEFAULT_LED_WARN_BIT),
            led_fail_bit=_led_bit(read("LED_FAIL_BIT"), default=DEFAULT_LED_FAIL_BIT),
            led_blink_count=_positive_int(read("LED_BLINK_COUNT"), default=1),
            led_blink_seconds=_non_negative_float(read("LED_BLINK_SECONDS"), default=0.15),
        )


class Sx1303GatewayObserver:
    def __init__(
        self,
        config: Sx1303GatewayObserverConfig,
        *,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.config = config
        self.started_at = _now_iso()
        self.refresh_count = 0
        self.last_status: dict[str, Any] | None = None
        self.command_runner = command_runner or self._run_command

    @property
    def status_path(self) -> Path:
        return self.config.evidence_dir / "sx1303_gateway_observer_status.json"

    @property
    def evidence_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sx1303_gateway_observer_samples.jsonl"

    def refresh(self) -> dict[str, Any]:
        self.refresh_count += 1
        updated_at = _now_iso()
        region = scan_region_config(
            paths=self.config.config_paths,
            expected_tokens=self.config.expected_region_tokens,
            forbidden_tokens=self.config.forbidden_region_tokens,
        )
        process_status = inspect_gateway_processes(
            command_runner=self.command_runner,
            timeout_seconds=self.config.command_timeout_seconds,
        )
        port_status = inspect_ports(
            host=self.config.host,
            tcp_ports=self.config.tcp_ports,
            udp_ports=self.config.udp_ports,
            command_runner=self.command_runner,
            timeout_seconds=self.config.command_timeout_seconds,
        )
        uplink_summary = summarize_jsonl_records(
            self.config.uplink_jsonl,
            max_records=self.config.max_jsonl_records,
            record_kind="uplink",
        )
        gateway_gps_summary = summarize_jsonl_records(
            self.config.gateway_gps_jsonl,
            max_records=self.config.max_jsonl_records,
            record_kind="gateway_gps",
        )
        rf_preflight_summary = summarize_jsonl_records(
            self.config.rf_preflight_jsonl,
            max_records=self.config.max_jsonl_records,
            record_kind="rf_preflight",
        )
        rx_readiness_summary = summarize_jsonl_records(
            self.config.rx_readiness_jsonl,
            max_records=self.config.max_jsonl_records,
            record_kind="rx_readiness",
        )
        decision = gateway_decision(
            region=region,
            process_status=process_status,
            port_status=port_status,
            uplink_summary=uplink_summary,
            rf_preflight_summary=rf_preflight_summary,
            rx_readiness_summary=rx_readiness_summary,
        )
        sample = {
            "captured_at": updated_at,
            "source": SOURCE_TOOL,
            "hardware_kind": "sx1303_lorawan_gateway_hat",
            "decision": decision,
            "region": region,
            "process_status": process_status,
            "port_status": port_status,
            "uplink_summary": uplink_summary,
            "gateway_gps_summary": gateway_gps_summary,
            "rf_preflight_summary": rf_preflight_summary,
            "rx_readiness_summary": rx_readiness_summary,
            "boundary": boundary_fields(),
        }
        append_jsonl(self.evidence_jsonl_path, sample)

        oled_status_updates = self._oled_status_updates(sample)
        led_status_updates = self._led_status_updates(sample)
        status = {
            "artifact_kind": ARTIFACT_KIND,
            "artifact_version": ARTIFACT_VERSION,
            "source_tool": SOURCE_TOOL,
            "started_at": self.started_at,
            "updated_at": updated_at,
            "refresh_count": self.refresh_count,
            "decision": decision,
            "answerability": answerability_for_decision(decision),
            "poll_seconds": self.config.poll_seconds,
            "evidence": {
                "evidence_dir": str(self.config.evidence_dir),
                "status_path": str(self.status_path),
                "samples_jsonl_path": str(self.evidence_jsonl_path),
                "uplink_jsonl_path": str(self.config.uplink_jsonl),
                "gateway_gps_jsonl_path": str(self.config.gateway_gps_jsonl),
                "rf_preflight_jsonl_path": str(self.config.rf_preflight_jsonl),
                "rx_readiness_jsonl_path": str(self.config.rx_readiness_jsonl),
            },
            "gateway_health": {
                "region_status": region["status"],
                "packet_forwarder_running": process_status["packet_forwarder_running"],
                "chirpstack_bridge_running": process_status["chirpstack_bridge_running"],
                "process_visibility": process_status["visibility"],
                "tcp_open_count": port_status["tcp_open_count"],
                "udp_listen_count": port_status["udp_listen_count"],
                "uplink_count": uplink_summary["record_count_scanned"],
                "last_uplink_seen_at": uplink_summary["last_record_at"],
                "gateway_gps_record_count": gateway_gps_summary["record_count_scanned"],
                "gateway_gps_last_seen_at": gateway_gps_summary["last_record_at"],
                "rf_preflight_record_count": rf_preflight_summary["record_count_scanned"],
                "rf_preflight_last_seen_at": rf_preflight_summary["last_record_at"],
                "rf_preflight_status": rf_preflight_summary["last_record_summary"].get("status")
                if rf_preflight_summary["last_record_summary"]
                else None,
                "gateway_eui": rf_preflight_summary["last_record_summary"].get("gateway_eui")
                if rf_preflight_summary["last_record_summary"]
                else None,
                "rx_readiness_record_count": rx_readiness_summary["record_count_scanned"],
                "rx_readiness_last_seen_at": rx_readiness_summary["last_record_at"],
                "rx_readiness_status": rx_readiness_status(rx_readiness_summary),
            },
            "region": region,
            "process_status": process_status,
            "port_status": port_status,
            "uplink_summary": uplink_summary,
            "gateway_gps_summary": gateway_gps_summary,
            "rf_preflight_summary": rf_preflight_summary,
            "rx_readiness_summary": rx_readiness_summary,
            "oled_status_updates": oled_status_updates,
            "led_status_updates": led_status_updates,
            "boundary": boundary_fields(),
        }
        self._write_json(self.status_path, status)
        self.last_status = status
        return status

    def run_forever(self) -> dict[str, Any]:
        ready_printed = False
        while True:
            status = self.refresh()
            if self.config.print_ready and not ready_printed:
                print(
                    json.dumps(
                        {
                            "event": "sx1303_gateway_observer_ready",
                            "status_path": str(self.status_path),
                            "samples_jsonl_path": str(self.evidence_jsonl_path),
                            "decision": status["decision"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                ready_printed = True
            time.sleep(self.config.poll_seconds)

    def _oled_status_updates(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.oled_status:
            return []
        return [
            write_gateway_oled_status(
                sample=sample,
                dry_run=self.config.oled_dry_run,
                bus=self.config.oled_bus,
                address=self.config.oled_address,
                driver=self.config.oled_driver,
            )
        ]

    def _led_status_updates(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.config.led_status:
            return []
        defaults = PORT_DEFAULTS[self.config.led_port]
        data_gpio = self.config.led_data_gpio if self.config.led_data_gpio is not None else defaults["data_gpio"]
        clock_gpio = self.config.led_clock_gpio if self.config.led_clock_gpio is not None else defaults["clock_gpio"]
        return [
            blink_gateway_led_status(
                sample=sample,
                port=self.config.led_port,
                data_gpio=data_gpio,
                clock_gpio=clock_gpio,
                ok_bit=self.config.led_ok_bit,
                warn_bit=self.config.led_warn_bit,
                fail_bit=self.config.led_fail_bit,
                blink_count=self.config.led_blink_count,
                blink_seconds=self.config.led_blink_seconds,
                dry_run=self.config.led_dry_run,
            )
        ]

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=self.config.command_timeout_seconds,
        )


def scan_region_config(
    *,
    paths: Sequence[Path],
    expected_tokens: Sequence[str],
    forbidden_tokens: Sequence[str],
) -> dict[str, Any]:
    scanned: list[dict[str, Any]] = []
    expected_upper = [token.upper() for token in expected_tokens]
    forbidden_upper = [token.upper() for token in forbidden_tokens]
    detected_expected: set[str] = set()
    detected_forbidden: set[str] = set()
    enabled_regions: set[str] = set()
    forbidden_enabled_regions: set[str] = set()
    frequencies_hz: set[int] = set()
    outside_tw_frequencies_hz: set[int] = set()
    frequency_bounds_hz: set[int] = set()
    outside_tw_frequency_bounds_hz: set[int] = set()

    for path in paths:
        item: dict[str, Any] = {"path": str(path), "exists": path.exists()}
        if not path.exists():
            scanned.append(item)
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            item["read_status"] = "error"
            item["error"] = f"{type(exc).__name__}: {exc}"
            scanned.append(item)
            continue
        uncommented = strip_line_comments(text)
        text_upper = uncommented.upper()
        item_expected = [token for token in expected_upper if token in text_upper]
        item_forbidden = [token for token in forbidden_upper if token in text_upper]
        item_enabled = extract_enabled_regions(uncommented)
        item_forbidden_enabled = [
            region for region in item_enabled if any(region == token or region.startswith(f"{token}_") for token in forbidden_upper)
        ]
        item_freqs = extract_channel_frequencies_hz(uncommented)
        item_bounds = extract_frequency_bounds_hz(uncommented)
        detected_expected.update(item_expected)
        detected_forbidden.update(item_forbidden)
        enabled_regions.update(item_enabled)
        forbidden_enabled_regions.update(item_forbidden_enabled)
        frequencies_hz.update(item_freqs)
        outside_tw_frequencies_hz.update(freq for freq in item_freqs if not is_tw_lora_frequency_hz(freq))
        frequency_bounds_hz.update(item_bounds)
        outside_tw_frequency_bounds_hz.update(freq for freq in item_bounds if not is_tw_lora_frequency_hz(freq))
        item.update(
            {
                "read_status": "ok",
                "matched_expected_tokens": item_expected,
                "matched_forbidden_tokens": item_forbidden,
                "enabled_regions": item_enabled,
                "forbidden_enabled_regions": item_forbidden_enabled,
                "frequencies_hz": sorted(item_freqs),
                "frequency_bounds_hz": sorted(item_bounds),
            }
        )
        scanned.append(item)

    if detected_forbidden or forbidden_enabled_regions or outside_tw_frequencies_hz:
        status = "wrong_region"
    elif outside_tw_frequency_bounds_hz and detected_expected:
        status = "region_warning"
    elif detected_expected:
        status = "region_ok"
    elif any(item["exists"] for item in scanned):
        status = "region_unknown"
    else:
        status = "config_missing"

    return {
        "status": status,
        "expected_region_tokens": list(expected_upper),
        "forbidden_region_tokens": list(forbidden_upper),
        "detected_expected_tokens": sorted(detected_expected),
        "detected_forbidden_tokens": sorted(detected_forbidden),
        "enabled_regions": sorted(enabled_regions),
        "forbidden_enabled_regions": sorted(forbidden_enabled_regions),
        "frequencies_hz": sorted(frequencies_hz),
        "outside_tw_frequencies_hz": sorted(outside_tw_frequencies_hz),
        "frequency_bounds_hz": sorted(frequency_bounds_hz),
        "outside_tw_frequency_bounds_hz": sorted(outside_tw_frequency_bounds_hz),
        "tw_frequency_range_hz": {"min": 920_000_000, "max": 925_000_000},
        "config_paths": scanned,
        "config_checked": True,
        "config_changed": False,
    }


def extract_frequencies_hz(text: str) -> list[int]:
    return extract_frequency_values_from_text(strip_line_comments(text))


def extract_channel_frequencies_hz(text: str) -> list[int]:
    values: set[int] = set()
    for line in strip_line_comments(text).splitlines():
        if re.search(r"\bfrequency_(min|max)\b", line, flags=re.IGNORECASE):
            continue
        if re.search(r"\b(frequency|rx2_frequency|ping_slot_frequency)\b", line, flags=re.IGNORECASE):
            values.update(extract_frequency_values_from_text(line))
        elif re.search(r"^\s*[0-9]{8,10}\s*,?\s*$", line):
            values.update(extract_frequency_values_from_text(line))
        elif re.search(r"^\s*[0-9]{3}[.]\d{1,6}\s*,?\s*$", line):
            values.update(extract_frequency_values_from_text(line))
    return sorted(values)


def extract_frequency_bounds_hz(text: str) -> list[int]:
    values: set[int] = set()
    for line in strip_line_comments(text).splitlines():
        if re.search(r"\bfrequency_(min|max)\b", line, flags=re.IGNORECASE):
            values.update(extract_frequency_values_from_text(line))
    return sorted(values)


def is_tw_lora_frequency_hz(value: int) -> bool:
    return 920_000_000 <= value <= 925_000_000


def extract_frequency_values_from_text(text: str) -> list[int]:
    values: set[int] = set()
    for match in re.finditer(r"\b([0-9]{8,10})\b", text):
        value = int(match.group(1))
        if 100_000_000 <= value <= 1_000_000_000:
            values.add(value)
    for match in re.finditer(r"\b([0-9]{3})[.](\d{1,6})\b", text):
        whole = int(match.group(1))
        fractional = match.group(2)
        hz = int(float(f"{whole}.{fractional}") * 1_000_000)
        if 100_000_000 <= hz <= 1_000_000_000:
            values.add(hz)
    return sorted(values)


def extract_enabled_regions(text: str) -> list[str]:
    match = re.search(r"enabled_regions\s*=\s*\[(?P<body>.*?)\]", strip_line_comments(text), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    regions = re.findall(r"['\"]([^'\"]+)['\"]", match.group("body"))
    return sorted({region.strip().upper() for region in regions if region.strip()})


def strip_line_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        lines.append(line.split("#", 1)[0])
    return "\n".join(lines)


def inspect_gateway_processes(
    *,
    command_runner: CommandRunner,
    timeout_seconds: float,
) -> dict[str, Any]:
    pgrep = run_readonly_command(
        command_runner,
        ["pgrep", "-af", "lora_pkt_fwd|basicstation|station|chirpstack-gateway-bridge"],
        timeout_seconds=timeout_seconds,
    )
    docker = run_readonly_command(
        command_runner,
        ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
        timeout_seconds=timeout_seconds,
    )
    process_lines = pgrep.get("stdout_lines", [])
    docker_lines = docker.get("stdout_lines", [])
    joined = "\n".join(process_lines + docker_lines).lower()
    pgrep_visible = pgrep["status"] == "ok" and bool(process_lines)
    docker_visible = docker["status"] == "ok" and bool(docker_lines)
    if pgrep_visible or docker_visible:
        visibility = "process_evidence_present"
    elif pgrep["status"] == "command_missing" and docker["status"] == "command_missing":
        visibility = "process_commands_unavailable"
    elif pgrep["status"] in {"timeout", "error"} or docker["status"] in {"timeout", "error"}:
        visibility = "process_probe_error"
    else:
        visibility = "process_evidence_absent"
    return {
        "pgrep": pgrep,
        "docker_ps": docker,
        "process_lines": process_lines,
        "docker_lines": docker_lines,
        "packet_forwarder_running": any(token in joined for token in ("lora_pkt_fwd", "basicstation", "packet-forwarder")),
        "chirpstack_bridge_running": "chirpstack-gateway-bridge" in joined,
        "chirpstack_running": "chirpstack" in joined,
        "visibility": visibility,
        "command_checked": True,
    }


def run_readonly_command(
    command_runner: CommandRunner,
    command: list[str],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        result = command_runner(command)
    except FileNotFoundError:
        return {
            "command": command,
            "status": "command_missing",
            "returncode": None,
            "stdout_lines": [],
            "stderr": "",
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "status": "timeout",
            "returncode": None,
            "stdout_lines": [],
            "stderr": "",
            "timeout_seconds": timeout_seconds,
        }
    except Exception as exc:
        return {
            "command": command,
            "status": "error",
            "returncode": None,
            "stdout_lines": [],
            "stderr": f"{type(exc).__name__}: {exc}",
        }
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return {
        "command": command,
        "status": "ok" if result.returncode == 0 else "nonzero",
        "returncode": result.returncode,
        "stdout_lines": [line for line in stdout.splitlines() if line.strip()],
        "stderr": stderr.strip(),
    }


def inspect_ports(
    *,
    host: str,
    tcp_ports: Sequence[int],
    udp_ports: Sequence[int],
    command_runner: CommandRunner,
    timeout_seconds: float,
) -> dict[str, Any]:
    tcp = [inspect_tcp_port(host=host, port=port, timeout_seconds=timeout_seconds) for port in tcp_ports]
    ss_udp = run_readonly_command(command_runner, ["ss", "-lun"], timeout_seconds=timeout_seconds)
    udp = [inspect_udp_listen_from_ss(port=port, ss_result=ss_udp) for port in udp_ports]
    return {
        "host": host,
        "tcp": tcp,
        "udp": udp,
        "ss_udp": ss_udp,
        "tcp_open_count": sum(1 for item in tcp if item["status"] == "open"),
        "udp_listen_count": sum(1 for item in udp if item["status"] == "listening"),
        "network_probe_scope": "local_gateway_stack_only",
        "remote_outbound_allowed": False,
    }


def inspect_tcp_port(*, host: str, port: int, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {"host": host, "port": port, "protocol": "tcp", "status": "open", "elapsed_ms": elapsed_ms}
    except ConnectionRefusedError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {"host": host, "port": port, "protocol": "tcp", "status": "closed", "elapsed_ms": elapsed_ms}
    except TimeoutError:
        return {"host": host, "port": port, "protocol": "tcp", "status": "timeout", "elapsed_ms": int(timeout_seconds * 1000)}
    except OSError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "host": host,
            "port": port,
            "protocol": "tcp",
            "status": "error",
            "elapsed_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


def inspect_udp_listen_from_ss(*, port: int, ss_result: dict[str, Any]) -> dict[str, Any]:
    if ss_result["status"] in {"command_missing", "timeout", "error"}:
        return {
            "port": port,
            "protocol": "udp",
            "status": "unknown",
            "reason": ss_result["status"],
            "probe_packet_sent": False,
        }
    pattern = re.compile(rf"[:.]({port})\b")
    listening = any(pattern.search(line) for line in ss_result.get("stdout_lines", []))
    return {
        "port": port,
        "protocol": "udp",
        "status": "listening" if listening else "not_listening",
        "probe_packet_sent": False,
    }


def summarize_jsonl_records(path: Path, *, max_records: int, record_kind: str) -> dict[str, Any]:
    records, invalid_line_count = load_jsonl_tail(path, max_records=max_records)
    last_record = records[-1] if records else None
    uplink_count = sum(1 for record in records if looks_like_uplink(record)) if record_kind == "uplink" else 0
    crc_ok_count = sum(1 for record in records if str(record.get("crc_status", "")).lower() in {"ok", "crc_ok", "valid"})
    crc_fail_count = sum(1 for record in records if str(record.get("crc_status", "")).lower() in {"fail", "crc_fail", "invalid"})
    return {
        "path": str(path),
        "record_kind": record_kind,
        "file_exists": path.exists(),
        "record_count_scanned": len(records),
        "invalid_json_line_count": invalid_line_count,
        "uplink_like_record_count": uplink_count,
        "crc_ok_count": crc_ok_count,
        "crc_fail_count": crc_fail_count,
        "last_record_at": latest_record_time(last_record),
        "last_record_summary": summarize_record(last_record),
    }


def load_jsonl_tail(path: Path, *, max_records: int) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    records: list[dict[str, Any]] = []
    invalid_line_count = 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-max_records:]:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid_line_count += 1
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records, invalid_line_count


def looks_like_uplink(record: dict[str, Any]) -> bool:
    text = json.dumps(record, sort_keys=True).lower()
    return any(token in text for token in ("uplink", "rxpk", "dev_eui", "deveui", "fcnt", "rssi", "snr"))


def latest_record_time(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    for key in ("captured_at", "received_at", "gateway_rx_time", "updated_at", "timestamp"):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def summarize_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    summary: dict[str, Any] = {}
    for key in (
        "source",
        "hardware_kind",
        "status",
        "region_profile",
        "gateway_eui",
        "chip_version",
        "dev_eui_hash",
        "dev_eui_present",
        "gateway_id_hashes",
        "gateway_count",
        "rf_receive_path_checked",
        "rf_read_scope",
        "readiness_scope",
        "uplink_hint_count",
        "tcp_open_count",
        "udp_listen_count",
        "frequency_hz",
        "spreading_factor",
        "bandwidth_hz",
        "f_cnt",
        "f_port",
        "rssi_dbm",
        "snr_db",
        "payload_bytes",
        "raw_payload_embedded",
        "raw_payload_data_embedded",
        "nmea_available",
        "selected_port",
        "selected_baud",
    ):
        if key in record:
            summary[key] = record[key]
    return summary


def gateway_decision(
    *,
    region: dict[str, Any],
    process_status: dict[str, Any],
    port_status: dict[str, Any],
    uplink_summary: dict[str, Any],
    rf_preflight_summary: dict[str, Any],
    rx_readiness_summary: dict[str, Any],
) -> str:
    if region["status"] == "wrong_region":
        return "wrong_region"
    if uplink_summary["record_count_scanned"] > 0 or uplink_summary["uplink_like_record_count"] > 0:
        return "gateway_receiving_uplinks"
    if rx_readiness_status(rx_readiness_summary) == "rx_stack_seen_uplink":
        return "gateway_rx_stack_seen_uplink"
    if rx_readiness_status(rx_readiness_summary) == "rx_stack_ready_no_uplink" and region["status"] in {
        "region_ok",
        "region_warning",
    }:
        return "gateway_rx_stack_ready_no_uplink"
    if rf_preflight_ok(rf_preflight_summary) and region["status"] in {"region_ok", "region_warning"}:
        return "gateway_rf_hardware_detected_no_uplink"
    if not process_status["packet_forwarder_running"]:
        if (
            port_status["tcp_open_count"] > 0
            and process_status["visibility"] in {"process_commands_unavailable", "process_probe_error"}
        ):
            return "gateway_control_plane_reachable_rf_unknown"
        return "packet_forwarder_missing"
    mqtt_open = any(item["port"] == 1883 and item["status"] == "open" for item in port_status["tcp"])
    if not process_status["chirpstack_bridge_running"] and not mqtt_open:
        return "chirpstack_bridge_missing"
    if region["status"] == "region_warning":
        return "gateway_running_region_warning"
    if region["status"] in {"config_missing", "region_unknown"}:
        return "gateway_running_region_unknown"
    return "gateway_ready_no_uplink"


def rf_preflight_ok(rf_preflight_summary: dict[str, Any]) -> bool:
    last_record = rf_preflight_summary.get("last_record_summary")
    if not isinstance(last_record, dict):
        return False
    return (
        str(last_record.get("source")) == "pi_sx1303_gateway_smoke"
        and str(last_record.get("status")) == "ok"
        and bool(last_record.get("gateway_eui"))
    )


def rx_readiness_status(rx_readiness_summary: dict[str, Any]) -> str | None:
    last_record = rx_readiness_summary.get("last_record_summary")
    if not isinstance(last_record, dict):
        return None
    status = last_record.get("status")
    return str(status) if status else None


def answerability_for_decision(decision: str) -> str:
    if decision == "gateway_receiving_uplinks":
        return "gateway_uplink_evidence_available"
    if decision == "gateway_rx_stack_seen_uplink":
        return "gateway_rx_log_hint_available_review_structured_uplink_jsonl"
    if decision == "gateway_rx_stack_ready_no_uplink":
        return "gateway_rx_stack_ready_no_client_uplink_seen"
    if decision == "gateway_rf_hardware_detected_no_uplink":
        return "gateway_rf_hardware_evidence_available_no_uplink_seen"
    if decision == "gateway_ready_no_uplink":
        return "gateway_control_plane_ready_no_uplink_seen"
    if decision == "gateway_control_plane_reachable_rf_unknown":
        return "gateway_control_plane_evidence_available_rf_path_unknown"
    if decision == "gateway_running_region_warning":
        return "gateway_region_warning_operator_review"
    if decision == "wrong_region":
        return "gateway_region_requires_operator_review"
    return "gateway_health_evidence_incomplete"


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
        "hardware_control_scope": "diagnostic_gateway_health_only",
    }


def gateway_oled_message(sample: dict[str, Any]) -> str:
    decision = sample["decision"]
    region = sample["region"]
    process_status = sample["process_status"]
    uplink_summary = sample["uplink_summary"]
    status_label = {
        "wrong_region": "WRONG REGION",
        "packet_forwarder_missing": "NO FWD",
        "chirpstack_bridge_missing": "NO BRIDGE",
        "gateway_receiving_uplinks": "UPLINK OK",
        "gateway_rx_stack_seen_uplink": "RX UPLINK HINT",
        "gateway_rx_stack_ready_no_uplink": "RX READY NO UL",
        "gateway_rf_hardware_detected_no_uplink": "RF OK NO UL",
        "gateway_control_plane_reachable_rf_unknown": "CTRL OK RF?",
        "gateway_running_region_warning": "REG WARN",
        "gateway_running_region_unknown": "REG UNKNOWN",
        "gateway_ready_no_uplink": "GW READY",
    }.get(decision, "GW CHECK")
    region_label = _compact_region_label(region)
    fwd = "FWD OK" if process_status["packet_forwarder_running"] else "FWD --"
    bridge = "BR OK" if process_status["chirpstack_bridge_running"] else "BR --"
    lines = [
        "SCOUT LORA GW",
        status_label,
        f"REG {region_label}",
        fwd,
        bridge,
        f"UL {uplink_summary['record_count_scanned']}",
        "NO RF TX",
    ]
    return "\n".join(line[:16] for line in lines)


def _compact_region_label(region: dict[str, Any]) -> str:
    forbidden = region.get("detected_forbidden_tokens") or []
    forbidden_enabled = region.get("forbidden_enabled_regions") or []
    expected = region.get("detected_expected_tokens") or []
    if len(forbidden_enabled) > 1:
        return f"FORBID {len(forbidden_enabled)}"
    if forbidden_enabled:
        return str(forbidden_enabled[0])[:12]
    if forbidden:
        return str(forbidden[0])[:12]
    if expected:
        return str(expected[0])[:12]
    return str(region.get("status", "UNKNOWN")).replace("_", " ").upper()[:12]


def build_oled_status_payload(
    *,
    sample: dict[str, Any],
    bus: Path,
    address: int,
    driver: str,
    driver_attempted: str | None,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload = {
        "captured_at": _now_iso(),
        "source": "scout_sx1303_gateway_observer_oled_status",
        "hardware_kind": "grove_oled_96x96_i2c",
        "bus": str(bus),
        "address": f"0x{address:02x}",
        "driver": driver,
        "driver_attempted": driver_attempted,
        "write_status": write_status,
        "dry_run": dry_run,
        "message": gateway_oled_message(sample),
        "decision": sample["decision"],
        "region_status": sample["region"]["status"],
        "packet_forwarder_running": sample["process_status"]["packet_forwarder_running"],
        "chirpstack_bridge_running": sample["process_status"]["chirpstack_bridge_running"],
        "uplink_count": sample["uplink_summary"]["record_count_scanned"],
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def write_gateway_oled_status(
    *,
    sample: dict[str, Any],
    dry_run: bool,
    bus: Path,
    address: int,
    driver: str,
) -> dict[str, Any]:
    if dry_run:
        return build_oled_status_payload(
            sample=sample,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver,
            write_status="dry_run",
            dry_run=True,
        )
    try:
        driver_attempted = write_display(
            bus=bus,
            address=address,
            driver=driver,
            message=gateway_oled_message(sample),
        )
        return build_oled_status_payload(
            sample=sample,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=driver_attempted,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_oled_status_payload(
            sample=sample,
            bus=bus,
            address=address,
            driver=driver,
            driver_attempted=None,
            write_status="error",
            dry_run=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def led_bits_for_sample(sample: dict[str, Any], *, ok_bit: int, warn_bit: int, fail_bit: int) -> int:
    decision = sample["decision"]
    if decision in {
        "gateway_ready_no_uplink",
        "gateway_receiving_uplinks",
        "gateway_rx_stack_seen_uplink",
        "gateway_rx_stack_ready_no_uplink",
        "gateway_rf_hardware_detected_no_uplink",
    }:
        bit = ok_bit
    elif decision == "wrong_region":
        bit = fail_bit
    else:
        bit = warn_bit
    return 1 << (bit - 1)


def build_led_status_payload(
    *,
    sample: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    warn_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    bits = led_bits_for_sample(sample, ok_bit=ok_bit, warn_bit=warn_bit, fail_bit=fail_bit)
    payload = {
        "captured_at": _now_iso(),
        "source": "scout_sx1303_gateway_observer_led_status",
        "hardware_kind": "grove_led_bar_v2_my9221",
        "port": port,
        "data_gpio": data_gpio,
        "clock_gpio": clock_gpio,
        "bits": f"0x{bits:03x}",
        "decision": sample["decision"],
        "ok_led_bit": ok_bit,
        "warn_led_bit": warn_bit,
        "fail_led_bit": fail_bit,
        "blink_count": blink_count,
        "blink_seconds": blink_seconds,
        "write_status": write_status,
        "dry_run": dry_run,
        "rf_tx_allowed": False,
        "downlink_allowed": False,
        "lorawan_uplink_allowed": False,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_indicator_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def blink_gateway_led_status(
    *,
    sample: dict[str, Any],
    port: str,
    data_gpio: int,
    clock_gpio: int,
    ok_bit: int,
    warn_bit: int,
    fail_bit: int,
    blink_count: int,
    blink_seconds: float,
    dry_run: bool,
) -> dict[str, Any]:
    if blink_count < 1:
        raise ValueError("blink_count must be at least 1")
    if blink_seconds < 0:
        raise ValueError("blink_seconds must be non-negative")
    if dry_run:
        return build_led_status_payload(
            sample=sample,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            ok_bit=ok_bit,
            warn_bit=warn_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="dry_run",
            dry_run=True,
        )
    writer = None
    try:
        writer = make_gpio_writer()
        bits = led_bits_for_sample(sample, ok_bit=ok_bit, warn_bit=warn_bit, fail_bit=fail_bit)
        for _ in range(blink_count):
            write_led_bar_bits(writer, data_gpio=data_gpio, clock_gpio=clock_gpio, bits=bits)
            time.sleep(blink_seconds)
            clear_led_bar(writer, data_gpio=data_gpio, clock_gpio=clock_gpio)
            time.sleep(blink_seconds)
        return build_led_status_payload(
            sample=sample,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            ok_bit=ok_bit,
            warn_bit=warn_bit,
            fail_bit=fail_bit,
            blink_count=blink_count,
            blink_seconds=blink_seconds,
            write_status="ok",
            dry_run=False,
        )
    except Exception as exc:
        return build_led_status_payload(
            sample=sample,
            port=port,
            data_gpio=data_gpio,
            clock_gpio=clock_gpio,
            ok_bit=ok_bit,
            warn_bit=warn_bit,
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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_int_csv(value: str) -> list[int]:
    items = parse_csv(value)
    parsed: list[int] = []
    for item in items:
        try:
            port = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid integer value: {item}") from exc
        if port < 1:
            raise argparse.ArgumentTypeError("integer values must be positive")
        parsed.append(port)
    return parsed


def _join_paths(paths: Sequence[Path]) -> str:
    return ",".join(str(path) for path in paths)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_env(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _positive_float(value: str | None, *, default: float) -> float:
    if value in (None, ""):
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("value must be positive")
    return parsed


def _non_negative_float(value: str | None, *, default: float) -> float:
    if value in (None, ""):
        return default
    parsed = float(value)
    if parsed < 0:
        raise ValueError("value must be non-negative")
    return parsed


def _positive_int(value: str | None, *, default: int) -> int:
    if value in (None, ""):
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("value must be at least 1")
    return parsed


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _led_bit(value: str | None, *, default: int) -> int:
    parsed = default if value in (None, "") else int(value)
    if not 1 <= parsed <= 10:
        raise ValueError("LED bit must be between 1 and 10")
    return parsed


def parse_led_bit(value: str) -> int:
    try:
        return _led_bit(value, default=DEFAULT_LED_WARN_BIT)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observe SX1303 LoRaWAN gateway health without RF TX or config writes.")
    env_config = Sx1303GatewayObserverConfig.from_env()
    parser.add_argument("--evidence-dir", type=Path, default=env_config.evidence_dir)
    parser.add_argument("--uplink-jsonl", type=Path, default=env_config.uplink_jsonl)
    parser.add_argument("--gateway-gps-jsonl", type=Path, default=env_config.gateway_gps_jsonl)
    parser.add_argument("--rf-preflight-jsonl", type=Path, default=env_config.rf_preflight_jsonl)
    parser.add_argument("--rx-readiness-jsonl", type=Path, default=env_config.rx_readiness_jsonl)
    parser.add_argument("--config-paths", type=parse_csv, default=[str(path) for path in env_config.config_paths])
    parser.add_argument("--expected-region-tokens", type=parse_csv, default=list(env_config.expected_region_tokens))
    parser.add_argument("--forbidden-region-tokens", type=parse_csv, default=list(env_config.forbidden_region_tokens))
    parser.add_argument("--host", default=env_config.host)
    parser.add_argument("--tcp-ports", type=parse_int_csv, default=list(env_config.tcp_ports))
    parser.add_argument("--udp-ports", type=parse_int_csv, default=list(env_config.udp_ports))
    parser.add_argument("--poll-seconds", type=float, default=env_config.poll_seconds)
    parser.add_argument("--max-jsonl-records", type=int, default=env_config.max_jsonl_records)
    parser.add_argument("--command-timeout-seconds", type=float, default=env_config.command_timeout_seconds)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--print-ready", action="store_true", default=env_config.print_ready)
    parser.add_argument("--oled-status", action="store_true", default=env_config.oled_status)
    parser.add_argument("--oled-bus", type=Path, default=env_config.oled_bus)
    parser.add_argument("--oled-address", type=parse_address, default=env_config.oled_address)
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default=env_config.oled_driver)
    parser.add_argument("--oled-dry-run", action="store_true", default=env_config.oled_dry_run)
    parser.add_argument("--led-status", action="store_true", default=env_config.led_status)
    parser.add_argument("--led-port", choices=sorted(PORT_DEFAULTS), default=env_config.led_port)
    parser.add_argument("--led-data-gpio", type=int, default=env_config.led_data_gpio)
    parser.add_argument("--led-clock-gpio", type=int, default=env_config.led_clock_gpio)
    parser.add_argument("--led-ok-bit", type=parse_led_bit, default=env_config.led_ok_bit)
    parser.add_argument("--led-warn-bit", type=parse_led_bit, default=env_config.led_warn_bit)
    parser.add_argument("--led-fail-bit", type=parse_led_bit, default=env_config.led_fail_bit)
    parser.add_argument("--led-blink-count", type=int, default=env_config.led_blink_count)
    parser.add_argument("--led-blink-seconds", type=float, default=env_config.led_blink_seconds)
    parser.add_argument("--led-dry-run", action="store_true", default=env_config.led_dry_run)
    return parser


def config_from_args(args: argparse.Namespace) -> Sx1303GatewayObserverConfig:
    if args.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be positive")
    if args.max_jsonl_records < 1:
        raise ValueError("--max-jsonl-records must be at least 1")
    if args.command_timeout_seconds <= 0:
        raise ValueError("--command-timeout-seconds must be positive")
    if args.led_blink_count < 1:
        raise ValueError("--led-blink-count must be at least 1")
    if args.led_blink_seconds < 0:
        raise ValueError("--led-blink-seconds must be non-negative")
    return Sx1303GatewayObserverConfig(
        evidence_dir=args.evidence_dir.expanduser(),
        uplink_jsonl=args.uplink_jsonl.expanduser(),
        gateway_gps_jsonl=args.gateway_gps_jsonl.expanduser(),
        rf_preflight_jsonl=args.rf_preflight_jsonl.expanduser(),
        rx_readiness_jsonl=args.rx_readiness_jsonl.expanduser(),
        config_paths=tuple(Path(item).expanduser() for item in args.config_paths),
        expected_region_tokens=tuple(str(item).upper() for item in args.expected_region_tokens),
        forbidden_region_tokens=tuple(str(item).upper() for item in args.forbidden_region_tokens),
        host=str(args.host),
        tcp_ports=tuple(int(port) for port in args.tcp_ports),
        udp_ports=tuple(int(port) for port in args.udp_ports),
        poll_seconds=float(args.poll_seconds),
        max_jsonl_records=int(args.max_jsonl_records),
        command_timeout_seconds=float(args.command_timeout_seconds),
        print_ready=bool(args.print_ready),
        oled_status=bool(args.oled_status),
        oled_dry_run=bool(args.oled_dry_run),
        oled_bus=args.oled_bus.expanduser(),
        oled_address=int(args.oled_address),
        oled_driver=str(args.oled_driver),
        led_status=bool(args.led_status),
        led_dry_run=bool(args.led_dry_run),
        led_port=str(args.led_port),
        led_data_gpio=args.led_data_gpio,
        led_clock_gpio=args.led_clock_gpio,
        led_ok_bit=int(args.led_ok_bit),
        led_warn_bit=int(args.led_warn_bit),
        led_fail_bit=int(args.led_fail_bit),
        led_blink_count=int(args.led_blink_count),
        led_blink_seconds=float(args.led_blink_seconds),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))

    observer = Sx1303GatewayObserver(config)
    if args.once:
        status = observer.refresh()
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    try:
        observer.run_forever()
    except KeyboardInterrupt:
        if observer.last_status is not None:
            print(json.dumps(observer.last_status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
