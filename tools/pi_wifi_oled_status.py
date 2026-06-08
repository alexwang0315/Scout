from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wifi_scan_provider import WifiScanSnapshot, scan_wifi, server_signal_snapshot_from_wifi_scan

try:
    from tools.pi_oled_i2c_smoke import parse_address, write_display
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from pi_oled_i2c_smoke import parse_address, write_display


SOURCE = "pi_wifi_oled_status"
HARDWARE_KIND = "wifi_scan_oled_boot_diagnostic"
DISPLAY_LINE_LIMIT = 6
DISPLAY_COLUMN_LIMIT = 16
DISPLAY_ALLOWED_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -.:")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(payload: dict[str, Any], output_path: Path | None) -> None:
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def discover_active_ssid(*, interface: str, timeout_seconds: float) -> str | None:
    try:
        completed = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi", "list", "ifname", interface],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    for raw_line in completed.stdout.splitlines():
        active, _, ssid = raw_line.partition(":")
        if active == "yes" and ssid:
            return _nmcli_unescape(ssid)
    return None


def discover_ipv4_addresses(*, interface: str, timeout_seconds: float) -> list[str]:
    addresses: list[str] = []
    try:
        completed = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", interface, "scope", "global"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return addresses
    for match in re.finditer(r"\binet\s+([0-9.]+)/", completed.stdout):
        addresses.append(match.group(1))
    return addresses


def build_wifi_oled_message(
    snapshot: WifiScanSnapshot | None,
    *,
    active_ssid: str | None,
    ipv4_addresses: list[str],
    error: str | None = None,
    max_ssid_lines: int = 3,
) -> str:
    lines = ["SCOUT WIFI"]
    if ipv4_addresses:
        lines.append(f"IP {ipv4_addresses[0]}")
    else:
        lines.append("IP NONE")

    if active_ssid:
        lines.append(f"ON {_display_token(active_ssid, max_chars=13)}")

    if error is not None:
        lines.append("SCAN ERR")
        lines.append(_display_error_label(error))
        return "\n".join(_fit_display_lines(lines))

    access_points = list(snapshot.access_points) if snapshot is not None else []
    if not access_points:
        lines.append("AP 0")
        lines.append("NO SSID")
        return "\n".join(_fit_display_lines(lines))

    lines.append(f"AP {len(access_points)}")
    sorted_access_points = sorted(
        access_points,
        key=lambda ap: (
            ap.associated,
            ap.signal_dbm if ap.signal_dbm is not None else -999.0,
            ap.signal_percent if ap.signal_percent is not None else -1,
        ),
        reverse=True,
    )
    for index, access_point in enumerate(sorted_access_points[:max_ssid_lines], start=1):
        ssid = access_point.ssid or "HIDDEN"
        signal = _signal_label(access_point.signal_dbm, access_point.signal_percent)
        prefix = "A" if access_point.associated or ssid == active_ssid else str(index)
        lines.append(f"{prefix} {_display_token(ssid, max_chars=10)} {signal}")
    return "\n".join(_fit_display_lines(lines))


def build_payload(
    *,
    snapshot: WifiScanSnapshot | None,
    interface: str,
    source_requested: str,
    active_ssid: str | None,
    ipv4_addresses: list[str],
    message: str,
    bus: Path,
    address: int,
    driver_attempted: str,
    write_status: str,
    dry_run: bool,
    error: str | None = None,
) -> dict[str, Any]:
    scan_payload = server_signal_snapshot_from_wifi_scan(snapshot) if snapshot is not None else None
    payload = {
        "captured_at": utc_now_iso(),
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "interface": interface,
        "source_requested": source_requested,
        "scan_source": snapshot.source if snapshot is not None else None,
        "active_ssid": active_ssid,
        "ipv4_addresses": ipv4_addresses,
        "access_point_count": len(snapshot.access_points) if snapshot is not None else 0,
        "best_ssid": scan_payload.get("best_ssid") if scan_payload is not None else None,
        "best_bssid": scan_payload.get("best_bssid") if scan_payload is not None else None,
        "best_rssi_dbm": scan_payload.get("best_rssi_dbm") if scan_payload is not None else None,
        "best_signal_percent": scan_payload.get("best_signal_percent") if scan_payload is not None else None,
        "visible_ssids": _visible_ssids(snapshot),
        "oled_bus": str(bus),
        "oled_address": f"0x{address:02x}",
        "oled_driver_attempted": driver_attempted,
        "oled_write_status": write_status,
        "oled_message": message,
        "dry_run": dry_run,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_display_only",
    }
    if error is not None:
        payload["error"] = error
    return payload


def _visible_ssids(snapshot: WifiScanSnapshot | None) -> list[str]:
    if snapshot is None:
        return []
    seen: set[str] = set()
    ssids: list[str] = []
    for access_point in snapshot.access_points:
        ssid = access_point.ssid
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        ssids.append(ssid)
    return ssids


def _display_token(value: str, *, max_chars: int) -> str:
    cleaned = value.upper().replace("_", "-")
    cleaned = "".join(char if char in DISPLAY_ALLOWED_CHARS else " " for char in cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return (cleaned or "UNKNOWN")[:max_chars]


def _fit_display_lines(lines: list[str]) -> list[str]:
    return [_display_token(line, max_chars=DISPLAY_COLUMN_LIMIT) for line in lines[:DISPLAY_LINE_LIMIT]]


def _signal_label(signal_dbm: float | None, signal_percent: int | None) -> str:
    if signal_dbm is not None:
        return str(round(signal_dbm))
    if signal_percent is not None:
        return str(signal_percent)
    return "?"


def _display_error_label(error: str) -> str:
    if "FileNotFoundError" in error and "nmcli" in error:
        return "NMCLI MISSING"
    if "FileNotFoundError" in error and "iw" in error:
        return "IW MISSING"
    if "TimeoutExpired" in error:
        return "SCAN TIMEOUT"
    if "PermissionError" in error:
        return "PERMISSION ERR"
    return "SCAN FAILED"


def _nmcli_unescape(value: str) -> str:
    return value.replace(r"\:", ":").replace(r"\\", "\\")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show Pi Wi-Fi scan status on the Grove OLED.")
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--source", choices=("auto", "iw", "nmcli"), default="auto")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-ssid-lines", type=int, default=3)
    parser.add_argument("--bus", type=Path, default=Path("/dev/i2c-1"))
    parser.add_argument("--address", type=parse_address, default=parse_address("0x3c"))
    parser.add_argument("--driver", choices=("sh1107g", "ssd1327", "auto"), default="sh1107g")
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.max_ssid_lines < 0:
        parser.error("--max-ssid-lines must be non-negative")

    snapshot: WifiScanSnapshot | None = None
    active_ssid = discover_active_ssid(interface=args.interface, timeout_seconds=min(args.timeout_seconds, 3.0))
    ipv4_addresses = discover_ipv4_addresses(interface=args.interface, timeout_seconds=min(args.timeout_seconds, 3.0))
    error: str | None = None

    try:
        snapshot = scan_wifi(
            interface=args.interface,
            prefer_iw=args.source != "nmcli",
            timeout_seconds=args.timeout_seconds,
        )
        if args.source == "iw" and snapshot.source != "iw":
            raise RuntimeError("iw scan was requested but iw data was not available")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    message = build_wifi_oled_message(
        snapshot,
        active_ssid=active_ssid,
        ipv4_addresses=ipv4_addresses,
        error=error,
        max_ssid_lines=args.max_ssid_lines,
    )

    try:
        driver_attempted = args.driver if args.dry_run else write_display(
            bus=args.bus,
            address=args.address,
            driver=args.driver,
            message=message,
        )
        write_status = "dry_run" if args.dry_run else "ok"
    except Exception as exc:
        driver_attempted = args.driver
        write_status = "error"
        error = error or f"{type(exc).__name__}: {exc}"

    payload = build_payload(
        snapshot=snapshot,
        interface=args.interface,
        source_requested=args.source,
        active_ssid=active_ssid,
        ipv4_addresses=ipv4_addresses,
        message=message,
        bus=args.bus,
        address=args.address,
        driver_attempted=driver_attempted,
        write_status=write_status,
        dry_run=args.dry_run,
        error=error,
    )
    append_jsonl(payload, args.output_jsonl)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
