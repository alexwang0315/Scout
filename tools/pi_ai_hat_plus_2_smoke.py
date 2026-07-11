from __future__ import annotations

import argparse
import glob
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SOURCE = "pi_ai_hat_plus_2_smoke"
HARDWARE_KIND = "raspberry_pi_ai_hat_plus_2_hailo10h"
HAILO10H_VENDOR_DEVICE_ID = "1e60:45c4"
HAILO10H_ARCHITECTURE = "HAILO10H"
DEFAULT_OUTPUT_JSONL = Path("/data/scout/providers/ai_hat_plus_2/manual-smoke.jsonl")
HAILO_PACKAGES = (
    "hailo-h10-all",
    "h10-hailort",
    "h10-hailort-pcie-driver",
    "python3-h10-hailort",
    "hailo-all",
    "hailort",
    "hailo-dkms",
)

CommandRunner = Callable[[list[str], float], dict[str, Any]]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], timeout_seconds: float) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "cmd": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
            "error": f"TimeoutExpired: {exc}",
        }
    except Exception as exc:
        return {
            "cmd": command,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def canned_command_result(command: list[str], timeout_seconds: float) -> dict[str, Any]:
    del timeout_seconds
    command_key = command[0]
    stdout_by_key = {
        "uname": "Linux scout 6.12.75+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.12.75-1+rpt1 (2026-03-11) aarch64 GNU/Linux\n",
        "vcgencmd": "throttled=0x0\n",
        "lspci": (
            "0001:00:00.0 PCI bridge [0604]: Broadcom Inc. and subsidiaries BCM2712 PCIe Bridge [14e4:2712] (rev 30)\n"
            "0001:01:00.0 Co-processor [0b40]: Hailo Technologies Ltd. Hailo-10H AI Processor [1e60:45c4] (rev 01)\n"
        ),
        "lsmod": "hailo1x_pci           147456  0\n",
        "dpkg-query": (
            "h10-hailort\t5.1.1\tinstall ok installed\n"
            "h10-hailort-pcie-driver\t5.1.1\tinstall ok installed\n"
            "hailo-h10-all\t5.1.1\tinstall ok installed\n"
            "python3-h10-hailort\t5.1.1-1\tinstall ok installed\n"
        ),
    }
    if command[:2] == ["sh", "-lc"] and "command -v hailortcli" in command[2]:
        stdout = "/usr/bin/hailortcli\n"
    elif command[:2] == ["hailortcli", "--version"]:
        stdout = "HailoRT-CLI version 5.1.1\n"
    elif command[:2] == ["hailortcli", "scan"]:
        stdout = "Hailo Devices:\n[-] Device: 0001:01:00.0\n"
    elif command[:3] == ["hailortcli", "fw-control", "identify"]:
        stdout = (
            "Executing on device: 0001:01:00.0\n"
            "Identifying board\n"
            "Control Protocol Version: 2\n"
            "Firmware Version: 5.1.1 (release,app)\n"
            "Logger Version: 0\n"
            "Device Architecture: HAILO10H\n\n"
        )
    elif command_key == "ls":
        stdout = "crw-rw-rw- 1 root root 239, 0 Jul  5 18:10 /dev/hailo0\n"
    else:
        stdout = stdout_by_key.get(command_key, "")
    return {
        "cmd": command,
        "returncode": 0,
        "stdout": stdout,
        "stderr": "",
        "timed_out": False,
    }


def parse_lspci_hailo(stdout: str) -> dict[str, Any]:
    lines = [line for line in stdout.splitlines() if "Hailo" in line or HAILO10H_VENDOR_DEVICE_ID in line]
    hailo10h_lines = [line for line in lines if "Hailo-10H" in line or HAILO10H_VENDOR_DEVICE_ID in line]
    pci_addresses = []
    for line in lines:
        match = re.match(r"^([0-9a-fA-F:.]+)\s+", line)
        if match:
            pci_addresses.append(match.group(1))
    return {
        "hailo_device_present": bool(lines),
        "hailo10h_detected": bool(hailo10h_lines),
        "hailo_pci_addresses": pci_addresses,
        "hailo_lspci_lines": lines,
    }


def parse_device_nodes(stdout: str) -> dict[str, Any]:
    nodes = sorted({match.group(0) for match in re.finditer(r"/dev/hailo\d+", stdout)})
    return {
        "device_node_present": bool(nodes),
        "device_nodes": nodes,
    }


def parse_lsmod(stdout: str) -> dict[str, Any]:
    modules = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        module = stripped.split()[0]
        if "hailo" in module.lower():
            modules.append(module)
    return {
        "driver_loaded": bool(modules),
        "kernel_modules": modules,
    }


def parse_dpkg_query(stdout: str) -> dict[str, str]:
    packages: dict[str, str] = {}
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and "install ok installed" in parts[2]:
            packages[parts[0]] = parts[1]
    return packages


def parse_hailortcli_version(stdout: str) -> str | None:
    match = re.search(r"HailoRT-CLI version\s+([^\s]+)", stdout)
    return match.group(1) if match else None


def parse_hailortcli_scan(stdout: str) -> list[str]:
    devices: list[str] = []
    for line in stdout.splitlines():
        match = re.search(r"Device:\s*([0-9a-fA-F:.]+)", line)
        if match:
            devices.append(match.group(1))
    return devices


def parse_hailortcli_identify(stdout: str) -> dict[str, Any]:
    firmware = None
    architecture = None
    protocol = None
    executing_device = None
    for line in stdout.splitlines():
        if line.startswith("Executing on device:"):
            executing_device = line.split(":", 1)[1].strip()
        elif line.startswith("Control Protocol Version:"):
            protocol = line.split(":", 1)[1].strip()
        elif line.startswith("Firmware Version:"):
            firmware = line.split(":", 1)[1].strip()
        elif line.startswith("Device Architecture:"):
            architecture = line.split(":", 1)[1].strip()
    return {
        "executing_device": executing_device,
        "control_protocol_version": protocol,
        "firmware_version": firmware,
        "device_architecture": architecture,
        "hailo10h_runtime_identified": architecture == HAILO10H_ARCHITECTURE,
    }


def parse_throttled(stdout: str) -> dict[str, Any]:
    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", stdout)
    raw = match.group(1) if match else None
    return {
        "throttled_raw": raw,
        "throttled_ok": raw == "0x0",
    }


def readiness_status(payload: dict[str, Any]) -> str:
    if not payload["pci"]["hailo_device_present"]:
        return "hardware_missing"
    if not payload["pci"]["hailo10h_detected"]:
        return "unexpected_hailo_device"
    if not payload["driver"]["driver_loaded"] or not payload["device_nodes"]["device_node_present"]:
        return "driver_missing_or_not_loaded"
    if not payload["hailortcli"]["available"]:
        return "hailortcli_missing"
    if not payload["hailortcli"]["identify"].get("hailo10h_runtime_identified"):
        return "hailo10h_runtime_not_identified"
    if payload["packages"].get("hailo-all") and not payload["packages"].get("hailo-h10-all"):
        return "wrong_hailo_package_for_ai_hat_plus_2"
    return "ready"


def next_actions_for_status(status: str) -> list[str]:
    if status == "ready":
        return ["run_minimal_hailo_inference_smoke"]
    if status == "hardware_missing":
        return ["power_down_and_reseat_ai_hat_plus_2", "check_pcie_ribbon_orientation"]
    if status == "driver_missing_or_not_loaded":
        return ["install_or_reinstall_dkms_and_hailo_h10_all", "reboot_scout"]
    if status == "hailortcli_missing":
        return ["install_hailo_h10_all", "reboot_scout"]
    if status == "wrong_hailo_package_for_ai_hat_plus_2":
        return ["remove_conflicting_hailo_all", "install_hailo_h10_all", "reboot_scout"]
    return ["inspect_hailortcli_fw_control_identify", "check_hailo_h10_all_package_versions"]


def collect_ai_hat_plus_2_status(
    *,
    runner: CommandRunner = run_command,
    timeout_seconds: float = 12.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    command_runner = canned_command_result if dry_run else runner
    command_results = {
        "uname": command_runner(["uname", "-a"], timeout_seconds),
        "throttled": command_runner(["vcgencmd", "get_throttled"], timeout_seconds),
        "lspci": command_runner(["lspci", "-nn"], timeout_seconds),
        "device_nodes": command_runner(["ls", "-l", *glob.glob("/dev/hailo*")], timeout_seconds)
        if not dry_run and glob.glob("/dev/hailo*")
        else command_runner(["ls", "-l", "/dev/hailo0"], timeout_seconds),
        "lsmod": command_runner(["lsmod"], timeout_seconds),
        "dpkg": command_runner(
            ["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Status}\n", *HAILO_PACKAGES],
            timeout_seconds,
        ),
        "hailortcli_path": command_runner(["sh", "-lc", "command -v hailortcli"], timeout_seconds),
        "hailortcli_version": command_runner(["hailortcli", "--version"], timeout_seconds),
        "hailortcli_scan": command_runner(["hailortcli", "scan"], timeout_seconds),
        "hailortcli_identify": command_runner(["hailortcli", "fw-control", "identify"], timeout_seconds),
    }

    packages = parse_dpkg_query(command_results["dpkg"]["stdout"])
    cli_path = command_results["hailortcli_path"]["stdout"].strip() or None
    payload: dict[str, Any] = {
        "captured_at": now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "dry_run": dry_run,
        "os": {
            "uname": command_results["uname"]["stdout"].strip(),
        },
        "power": parse_throttled(command_results["throttled"]["stdout"]),
        "pci": parse_lspci_hailo(command_results["lspci"]["stdout"]),
        "device_nodes": parse_device_nodes(command_results["device_nodes"]["stdout"]),
        "driver": parse_lsmod(command_results["lsmod"]["stdout"]),
        "packages": packages,
        "hailortcli": {
            "available": bool(cli_path) and command_results["hailortcli_version"]["returncode"] == 0,
            "path": cli_path,
            "version": parse_hailortcli_version(command_results["hailortcli_version"]["stdout"]),
            "scan_devices": parse_hailortcli_scan(command_results["hailortcli_scan"]["stdout"]),
            "identify": parse_hailortcli_identify(command_results["hailortcli_identify"]["stdout"]),
        },
        "command_results": sanitize_command_results(command_results),
        "model_inference_performed": False,
        "package_install_performed": False,
        "device_configuration_changed": False,
        "phase1_safety_decision_change_allowed": False,
        "runtime_safety_truth": False,
        "safety_api_called": False,
        "remote_outbound_allowed": False,
        "outbound_send_performed": False,
        "hardware_control_scope": "diagnostic_ai_accelerator_readiness_only",
    }
    status = readiness_status(payload)
    payload["readiness_status"] = status
    payload["ready_for_minimal_inference_smoke"] = status == "ready"
    payload["next_actions"] = next_actions_for_status(status)
    return payload


def sanitize_command_results(command_results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    sanitized: dict[str, dict[str, Any]] = {}
    for name, result in command_results.items():
        sanitized[name] = {
            "cmd": result.get("cmd", []),
            "returncode": result.get("returncode"),
            "timed_out": result.get("timed_out", False),
            "stderr": str(result.get("stderr", ""))[:500],
        }
        if result.get("error"):
            sanitized[name]["error"] = str(result.get("error"))[:500]
    return sanitized


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test Raspberry Pi AI HAT+ 2 / Hailo-10H readiness.")
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--no-write", action="store_true", help="Print payload without appending JSONL.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    payload = collect_ai_hat_plus_2_status(timeout_seconds=args.timeout_seconds, dry_run=args.dry_run)
    if not args.no_write:
        append_jsonl(args.output_jsonl, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
