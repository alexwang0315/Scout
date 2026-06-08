from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SECTION_PREFIX = "__SCOUT_PROBE_SECTION__ "
PI5_HEADER_GPIO_LINES = (
    {"physical_pin": 3, "gpio": 2, "header_label": "GPIO2", "pull_control": "fixed_pull_up"},
    {"physical_pin": 5, "gpio": 3, "header_label": "GPIO3", "pull_control": "fixed_pull_up"},
    {"physical_pin": 7, "gpio": 4, "header_label": "GPIO4", "pull_control": "software_configurable"},
    {"physical_pin": 8, "gpio": 14, "header_label": "GPIO14", "pull_control": "software_configurable"},
    {"physical_pin": 10, "gpio": 15, "header_label": "GPIO15", "pull_control": "software_configurable"},
    {"physical_pin": 11, "gpio": 17, "header_label": "GPIO17", "pull_control": "software_configurable"},
    {"physical_pin": 12, "gpio": 18, "header_label": "GPIO18", "pull_control": "software_configurable"},
    {"physical_pin": 13, "gpio": 27, "header_label": "GPIO27", "pull_control": "software_configurable"},
    {"physical_pin": 15, "gpio": 22, "header_label": "GPIO22", "pull_control": "software_configurable"},
    {"physical_pin": 16, "gpio": 23, "header_label": "GPIO23", "pull_control": "software_configurable"},
    {"physical_pin": 18, "gpio": 24, "header_label": "GPIO24", "pull_control": "software_configurable"},
    {"physical_pin": 19, "gpio": 10, "header_label": "GPIO10", "pull_control": "software_configurable"},
    {"physical_pin": 21, "gpio": 9, "header_label": "GPIO9", "pull_control": "software_configurable"},
    {"physical_pin": 22, "gpio": 25, "header_label": "GPIO25", "pull_control": "software_configurable"},
    {"physical_pin": 23, "gpio": 11, "header_label": "GPIO11", "pull_control": "software_configurable"},
    {"physical_pin": 24, "gpio": 8, "header_label": "GPIO8", "pull_control": "software_configurable"},
    {"physical_pin": 26, "gpio": 7, "header_label": "GPIO7", "pull_control": "software_configurable"},
    {"physical_pin": 27, "gpio": 0, "header_label": "GPIO0", "pull_control": "reserved_advanced_use"},
    {"physical_pin": 28, "gpio": 1, "header_label": "GPIO1", "pull_control": "reserved_advanced_use"},
    {"physical_pin": 29, "gpio": 5, "header_label": "GPIO5", "pull_control": "software_configurable"},
    {"physical_pin": 31, "gpio": 6, "header_label": "GPIO6", "pull_control": "software_configurable"},
    {"physical_pin": 32, "gpio": 12, "header_label": "GPIO12", "pull_control": "software_configurable"},
    {"physical_pin": 33, "gpio": 13, "header_label": "GPIO13", "pull_control": "software_configurable"},
    {"physical_pin": 35, "gpio": 19, "header_label": "GPIO19", "pull_control": "software_configurable"},
    {"physical_pin": 36, "gpio": 16, "header_label": "GPIO16", "pull_control": "software_configurable"},
    {"physical_pin": 37, "gpio": 26, "header_label": "GPIO26", "pull_control": "software_configurable"},
    {"physical_pin": 38, "gpio": 20, "header_label": "GPIO20", "pull_control": "software_configurable"},
    {"physical_pin": 40, "gpio": 21, "header_label": "GPIO21", "pull_control": "software_configurable"},
)


class ScoutHardwareLiveProbeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read_only_probe: Literal[True] = True
    ssh_commands_only: Literal[True] = True
    gpio_lab_mode_drive_policy_allowed: Literal[True] = True
    gpio_drive_requires_wiring_manifest: Literal[True] = True
    gpio_drive_implementation_enabled: Literal[False] = False
    gpio_drive_operator_confirmation_required: Literal[True] = True
    gpio_value_sampling_performed: Literal[False] = False
    gpio_drive_performed: Literal[False] = False
    i2c_transaction_performed: Literal[False] = False
    runtime_started: Literal[False] = False
    safety_mutation_calls_allowed: Literal[False] = False
    safety_mutation_performed: Literal[False] = False
    phase1_safety_decision_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    outbound_messages_allowed: Literal[False] = False
    hardware_provider_control_allowed: Literal[False] = False


class ScoutHardwareLiveProbeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    summary: str
    read_only: bool = True
    mutation: bool = False


class ScoutHardwareLiveProbeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["scout_hardware_readiness_live_probe"] = (
        "scout_hardware_readiness_live_probe"
    )
    status: Literal["collected", "failed"]
    host: str
    collected_at: str
    probe_transport: Literal["ssh"] = "ssh"
    boundary: ScoutHardwareLiveProbeBoundary = Field(
        default_factory=ScoutHardwareLiveProbeBoundary
    )
    commands: list[ScoutHardwareLiveProbeCommand]
    observations: dict[str, Any]
    interface_inventory: list[dict[str, Any]]
    provider_health: list[dict[str, Any]] = Field(default_factory=list)
    sample_replay_timeline: list[dict[str, Any]] = Field(default_factory=list)
    runtime_debug_events: list[dict[str, Any]] = Field(default_factory=list)
    mock_transport_queue: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str]


def build_remote_probe_script() -> str:
    return r'''
section() { printf "__SCOUT_PROBE_SECTION__ %s\n" "$1"; }
section host
printf "host=%s\n" "$(hostname 2>/dev/null || true)"
printf "kernel=%s\n" "$(uname -srmo 2>/dev/null || true)"
printf "user=%s\n" "$(id -un 2>/dev/null || true)"
printf "date=%s\n" "$(date -Iseconds 2>/dev/null || true)"
section df
df -h /data/scout 2>/dev/null || df -h / 2>/dev/null || true
section lsblk_json
lsblk -J -o NAME,TYPE,SIZE,MOUNTPOINT,FSTYPE,MODEL,TRAN 2>/dev/null || true
section gpio_tools
command -v gpiodetect 2>/dev/null || true
command -v gpioinfo 2>/dev/null || true
command -v gpioget 2>/dev/null || true
command -v gpioset 2>/dev/null || true
section gpiodetect
gpiodetect 2>/dev/null || true
section gpioinfo
gpioinfo 2>/dev/null | sed -n '1,120p' || true
section pinout
pinout 2>/dev/null | sed -n '1,120p' || true
section i2c
command -v i2cdetect 2>/dev/null || true
ls /dev/i2c-* 2>/dev/null || true
section audio_tts
command -v piper 2>/dev/null || true
command -v piper-tts 2>/dev/null || true
command -v bluealsa-aplay 2>/dev/null || true
command -v aplay 2>/dev/null || true
section bluetooth
command -v bluetoothctl 2>/dev/null || true
bluetoothctl show 2>/dev/null | sed -n '1,60p' || true
section uart
ls /dev/ttyAMA* /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
section usb
lsusb 2>/dev/null || true
'''.strip()


def run_remote_probe(host: str, *, timeout_seconds: int = 15) -> str:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_seconds}",
        host,
        build_remote_probe_script(),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(timeout_seconds + 5, 10),
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "ssh probe failed").strip())
    return completed.stdout


def build_probe_result(host: str, raw_output: str) -> ScoutHardwareLiveProbeResult:
    sections = parse_sections(raw_output)
    collected_at = _host_value(sections, "date") or datetime.now(timezone.utc).isoformat()
    observations = {
        "host": _host_value(sections, "host") or host,
        "kernel": _host_value(sections, "kernel"),
        "user": _host_value(sections, "user"),
        "date": collected_at,
    }
    return ScoutHardwareLiveProbeResult(
        status="collected",
        host=host,
        collected_at=collected_at,
        commands=_commands(),
        observations=observations,
        interface_inventory=build_interface_inventory(sections, collected_at=collected_at),
        provider_health=[],
        sample_replay_timeline=[],
        runtime_debug_events=[],
        mock_transport_queue=[],
        limitations=[
            "GPIO high/low values are not sampled by this probe.",
            "I2C address scans are not executed by this probe.",
            "The probe records tool and device visibility only; it does not control providers.",
            "The probe does not start Scout runtime, call /safety/*, send outbound messages, or write Phase 2 state.",
        ],
    )


def parse_sections(raw_output: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "preamble"
    sections[current] = []
    for line in raw_output.splitlines():
        if line.startswith(SECTION_PREFIX):
            current = line[len(SECTION_PREFIX) :].strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def build_interface_inventory(
    sections: dict[str, str],
    *,
    collected_at: str,
) -> list[dict[str, Any]]:
    return [
        _gpio_inventory(sections, collected_at),
        _i2c_inventory(sections, collected_at),
        _audio_tts_inventory(sections, collected_at),
        _bluetooth_inventory(sections, collected_at),
        _uart_inventory(sections, collected_at),
        _battery_inventory(collected_at),
        _gnss_inventory(collected_at),
        _imu_inventory(collected_at),
        _usb_inventory(sections, collected_at),
        _storage_inventory(sections, collected_at),
    ]


def _gpio_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    gpio_tools = sections.get("gpio_tools", "")
    gpiodetect = sections.get("gpiodetect", "")
    gpioinfo = sections.get("gpioinfo", "")
    chip_count = len(re.findall(r"^gpiochip\d+\b", gpiodetect, flags=re.MULTILINE))
    return _base_interface(
        "gpio.bank0.controls",
        "gpio",
        "available" if "gpioinfo" in gpio_tools and chip_count else "planned",
        "direction_observed_value_not_sampled" if gpioinfo else "tool_or_chip_not_seen",
        collected_at if gpioinfo else None,
        {
            "chip_count": chip_count,
            "primary_chip": _first_match(r"^(gpiochip\d+)", gpiodetect),
            "tools": _nonempty_lines(gpio_tools),
            "observed_lines": [
                _gpio_line(gpioinfo, line)
                for line in PI5_HEADER_GPIO_LINES
            ],
            "pi5_header_gpio_count": len(PI5_HEADER_GPIO_LINES),
            "capability_source": "raspberry_pi_5_40_pin_header_pinout",
            "manual_read_allowed": True,
            "manual_write_allowed": True,
            "manual_drive_allowed": True,
            "boundary": {
                "manual_pull_high_low_allowed": True,
                "lab_mode_drive_policy_allowed": True,
                "lab_mode_required": True,
                "operator_confirmation_required": True,
                "wiring_manifest_required": True,
                "wiring_manifest_confirmed": False,
                "gpioset_command_enabled": False,
                "gpioset_implementation_present": False,
                "high_low_drive_deferred_until_wiring_confirmed": True,
                "write_performed_by_probe": False,
                "phase1_safety_decision_mutation_allowed": False,
            },
        },
    )


def _i2c_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    i2c_lines = _nonempty_lines(sections.get("i2c", ""))
    device_nodes = [line for line in i2c_lines if line.startswith("/dev/i2c-")]
    has_tool = any("i2cdetect" in line for line in i2c_lines)
    return _base_interface(
        "i2c.bus1.sensors",
        "i2c",
        "available" if device_nodes else "planned",
        "device_node_seen" if device_nodes else "tool_or_device_node_not_seen",
        collected_at if has_tool or device_nodes else None,
        {
            "detected_addresses": [],
            "device_nodes": device_nodes,
            "tool_available": has_tool,
            "transaction_count": 0,
            "error_count": 0,
        },
    )


def _audio_tts_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    tools = _nonempty_lines(sections.get("audio_tts", ""))
    return _base_interface(
        "i2s.audio.tts",
        "i2s_tts",
        "available" if tools else "planned",
        "tts_tools_seen" if tools else "tool_not_seen",
        collected_at if tools else None,
        {"tools": tools, "queue_state": "not_checked_read_only_probe"},
    )


def _bluetooth_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    bluetooth = sections.get("bluetooth", "")
    controller = _first_match(r"Controller\s+([0-9A-Fa-f:]+)", bluetooth)
    powered = _first_match(r"Powered:\s+(\w+)", bluetooth)
    return _base_interface(
        "bluetooth.adapter0",
        "bluetooth",
        "available" if controller else "planned",
        "adapter_powered" if powered == "yes" else "adapter_seen" if controller else "tool_not_seen",
        collected_at if controller else None,
        {
            "adapter_address": controller,
            "powered": powered == "yes",
            "paired_devices": [],
            "connected_devices": [],
        },
    )


def _uart_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    ports = _nonempty_lines(sections.get("uart", ""))
    return _base_interface(
        "uart.gnss.future",
        "uart",
        "available" if ports else "planned",
        "device_node_seen" if ports else "not_connected",
        collected_at if ports else None,
        {"port": ports[0] if ports else "/dev/ttyAMA0", "ports": ports, "baud": 9600},
    )


def _battery_inventory(collected_at: str) -> dict[str, Any]:
    return _base_interface(
        "power.battery.pack",
        "battery",
        "planned",
        "not_connected",
        None,
        {"voltage_v": None, "percent": None, "charge_state": "unknown"},
    )


def _gnss_inventory(collected_at: str) -> dict[str, Any]:
    return _base_interface(
        "gnss.primary",
        "gnss",
        "planned",
        "not_connected",
        None,
        {"fix_quality": "unknown", "horizontal_accuracy_m": None},
    )


def _imu_inventory(collected_at: str) -> dict[str, Any]:
    return _base_interface(
        "imu.primary",
        "imu",
        "planned",
        "not_connected",
        None,
        {"sample_rate_hz": None, "dropout_count": None},
    )


def _usb_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    devices = []
    for line in _nonempty_lines(sections.get("usb", "")):
        match = re.match(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9A-Fa-f:]+)\s*(.*)", line)
        if match:
            devices.append(
                {
                    "bus": match.group(1),
                    "device": match.group(2),
                    "id": match.group(3),
                    "label": match.group(4).strip(),
                }
            )
    non_root = [device for device in devices if device["id"] not in {"1d6b:0002", "1d6b:0003"}]
    return _base_interface(
        "usb.devices",
        "usb",
        "available" if devices else "planned",
        "usb_device_seen" if devices else "not_connected",
        collected_at if devices else None,
        {"devices": non_root or devices},
    )


def _storage_inventory(sections: dict[str, str], collected_at: str) -> dict[str, Any]:
    lsblk = _parse_lsblk(sections.get("lsblk_json", ""))
    disks = lsblk.get("blockdevices") or []
    disk = next((item for item in disks if item.get("type") == "disk"), {})
    root_part = _find_mount(disks, "/")
    df = _parse_df(sections.get("df", ""))
    return _base_interface(
        "storage.ssd.data_root",
        "ssd",
        "available" if disk or root_part else "planned",
        "mounted_root_observed" if root_part or df else "not_connected",
        collected_at if disk or root_part or df else None,
        {
            "mount_path": root_part.get("mountpoint") or df.get("mount") or "/",
            "filesystem": root_part.get("fstype"),
            "disk_model": disk.get("model"),
            "transport": disk.get("tran"),
            "size": disk.get("size"),
            "free_space": df.get("avail"),
            "data_root": "/data/scout",
            "health_summary": "mounted_read_only_probe_no_smart_check",
        },
    )


def _base_interface(
    interface_ref: str,
    interface_type: str,
    status: str,
    signal_activity: str,
    last_seen_at: str | None,
    extra: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "interface_ref": interface_ref,
        "interface_type": interface_type,
        "status": status,
        "signal_activity": signal_activity,
        "last_seen_at": last_seen_at,
        "source_id": interface_ref,
        "source_path": "scout_hardware_readiness_live_probe.py",
        "evidence_type": "hardware_interface_inventory",
    }
    payload.update(extra)
    return payload


def _gpio_line(gpioinfo: str, line: dict[str, Any]) -> dict[str, Any]:
    number = int(line["gpio"])
    pattern = rf'line\s+{number:>3}:\s+"([^"]*)"\s+(\w+)'
    match = re.search(pattern, gpioinfo)
    return {
        "line_ref": f"gpio{number}.{_gpio_label(number)}",
        "physical_pin": int(line["physical_pin"]),
        "gpio": number,
        "header_label": str(line["header_label"]),
        "direction": match.group(2) if match else "unknown",
        "pull_state": "not_sampled",
        "last_edge": "not_sampled",
        "pull_control": str(line["pull_control"]),
        "manual_read_allowed": True,
        "manual_write_allowed": True,
        "manual_pull_high_allowed": True,
        "manual_pull_low_allowed": True,
        "write_requires_operator_confirmation": True,
        "write_performed_by_probe": False,
        "debounce_policy_ref": _gpio_debounce_policy_ref(number),
    }


def _gpio_label(number: int) -> str:
    if number == 17:
        return "manual_sos"
    if number == 27:
        return "ack"
    return "line"


def _gpio_debounce_policy_ref(number: int) -> str:
    if number == 17:
        return "gpio_debounce.manual_sos.v0"
    if number == 27:
        return "gpio_debounce.operator_ack.v0"
    return "gpio_debounce.pi5_header_default.v0"


def _host_value(sections: dict[str, str], key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}=(.*)$", sections.get("host", ""), flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_lsblk(text: str) -> dict[str, Any]:
    try:
        return json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return {}


def _find_mount(devices: list[dict[str, Any]], mountpoint: str) -> dict[str, Any]:
    for device in devices:
        if device.get("mountpoint") == mountpoint:
            return device
        child = _find_mount(list(device.get("children") or []), mountpoint)
        if child:
            return child
    return {}


def _parse_df(text: str) -> dict[str, str]:
    lines = _nonempty_lines(text)
    if len(lines) < 2:
        return {}
    parts = re.split(r"\s+", lines[-1])
    if len(parts) < 6:
        return {}
    return {
        "filesystem": parts[0],
        "size": parts[1],
        "used": parts[2],
        "avail": parts[3],
        "use_pct": parts[4],
        "mount": parts[5],
    }


def _commands() -> list[ScoutHardwareLiveProbeCommand]:
    return [
        ScoutHardwareLiveProbeCommand(
            command_id="host_identity",
            summary="hostname, kernel, user, and timestamp",
        ),
        ScoutHardwareLiveProbeCommand(
            command_id="storage_snapshot",
            summary="df and lsblk JSON for mounted storage metadata",
        ),
        ScoutHardwareLiveProbeCommand(
            command_id="gpio_metadata",
            summary="gpio tool availability, chip list, and line direction metadata only",
        ),
        ScoutHardwareLiveProbeCommand(
            command_id="bus_device_metadata",
            summary="I2C node visibility, Bluetooth adapter status, UART nodes, USB list, and TTS tool visibility",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect a read-only Scout hardware readiness live probe over SSH."
    )
    parser.add_argument("--host", default="scout", help="SSH host alias, default: scout")
    parser.add_argument("--timeout-seconds", type=int, default=15)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        raw_output = run_remote_probe(args.host, timeout_seconds=args.timeout_seconds)
        result = build_probe_result(args.host, raw_output)
    except Exception as exc:  # noqa: BLE001 - CLI should return a structured artifact.
        result = ScoutHardwareLiveProbeResult(
            status="failed",
            host=args.host,
            collected_at=datetime.now(timezone.utc).isoformat(),
            commands=_commands(),
            observations={"error": str(exc)},
            interface_inventory=[],
            limitations=[
                "Probe failed before collecting interface inventory.",
                "No hardware control, runtime start, safety mutation, outbound send, or Phase 2 writeback was attempted.",
            ],
        )
    print(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    return 0 if result.status == "collected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
