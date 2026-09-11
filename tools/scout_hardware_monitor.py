#!/usr/bin/env python3
"""Observe Scout hardware and notify its owner only when conditions change.

Reads Linux telemetry and the existing UPS observer's output. No device writes,
shutdowns, repairs, production API calls, or third-party messaging services.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import tempfile
import time
from typing import Any


DEFAULT_SOURCE = Path.home() / "scout-power-path-monitor/power-path-telemetry.jsonl"
DEFAULT_STATE = Path.home() / ".local/state/scout-hardware-monitor"
MAC_HOSTS = ("Lamb780722de-MacBook-Pro.local", "192.168.8.155")
THRESHOLDS = {
    "battery_percent": {"warning": 20, "critical": 10},
    "memory_used_percent": {"warning": 90, "critical": 95},
    "disk_used_percent": {"warning": 85, "critical": 95},
    "inode_used_percent": {"warning": 85, "critical": 95},
    "cpu_temperature_c": {"warning": 75, "critical": 85},
    "nvme_temperature_c": {"warning": 65, "critical": 75},
    "ups_stale_seconds": 15,
}


def latest_record(path: Path) -> dict[str, Any]:
    """Read a bounded tail, ignoring only an unfinished concurrent append."""
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size - 65536)
        stream.seek(offset)
        data = stream.read(65536)
    lines = data.split(b"\n")[:-1]
    if offset:
        lines = lines[1:]
    if not lines:
        raise ValueError("no complete telemetry record")
    record = json.loads(lines[-1])
    if not isinstance(record, dict):
        raise ValueError("telemetry record must be an object")
    return record


def read_power(path: Path, now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {"source": str(path), "status": "unavailable"}
    try:
        raw = latest_record(path)
        captured = datetime.fromisoformat(raw["captured_at"])
        age = (now - captured).total_seconds()
        result.update(captured_at=raw["captured_at"], age_seconds=round(age, 2))
        if not -5 <= age <= THRESHOLDS["ups_stale_seconds"]:
            raise ValueError("UPS telemetry is stale or timestamp is in the future")
        fields = ("battery_percent", "battery_voltage_mv", "battery_current_ma",
                  "ups_vbus_power_mw", "remaining_capacity_mah", "ext5v_v")
        for key in fields:
            value = raw[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("invalid numeric UPS field: " + key)
        if not 0 <= raw["battery_percent"] <= 100:
            raise ValueError("invalid battery percentage")
        cells = raw["cell_voltage_mv"]
        if not isinstance(cells, list) or len(cells) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not 1000 <= v <= 5000 for v in cells
        ):
            raise ValueError("invalid cell voltage telemetry")
        errors = raw.get("errors", [])
        if errors:
            raise ValueError("UPS observer reported a sensor error")
        throttled = int(raw["throttled_hex"], 16)
        current = raw["battery_current_ma"]
        flow = "discharging" if current < 0 else "charging" if current > 0 else "idle"
        result.update(status="ok", **{key: raw[key] for key in fields},
                      cell_voltage_mv=cells, flow=flow, throttled_hex=hex(throttled),
                      active_throttle_bits=throttled & 0xF,
                      historical_throttle_bits=(throttled >> 16) & 0xF,
                      battery_power_w=round(raw["battery_voltage_mv"] * current / 1_000_000, 2))
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def memory_usage(text: str) -> dict[str, float | int]:
    values = {line.split(":", 1)[0]: int(line.split()[1]) * 1024 for line in text.splitlines()}
    total, available = values["MemTotal"], values["MemAvailable"]
    return {"total_bytes": total, "available_bytes": available,
            "used_bytes": total - available, "used_percent": round(100 * (total - available) / total, 2),
            "swap_total_bytes": values["SwapTotal"],
            "swap_used_bytes": values["SwapTotal"] - values["SwapFree"]}


def mount_paths(text: str) -> list[tuple[str, str]]:
    mounts = []
    for line in text.splitlines():
        before, after = line.split(" - ", 1)
        mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), before.split()[4])
        fields = after.split()
        if mount == "/" or (fields[1].startswith("/dev/") and fields[0] not in ("squashfs", "iso9660")):
            mounts.append((mount, fields[1]))
    return sorted(set(mounts))


def disk_usage(mount: str, device: str) -> dict[str, Any]:
    value = os.statvfs(mount)
    total = value.f_blocks * value.f_frsize
    used = (value.f_blocks - value.f_bfree) * value.f_frsize
    available = value.f_bavail * value.f_frsize
    return {"mount": mount, "device": device, "total_bytes": total,
            "used_bytes": used, "available_bytes": available,
            # Match df: reserved filesystem blocks are not user-available space.
            "used_percent": round(100 * used / (used + available), 2) if used + available else 0,
            "inode_used_percent": round(100 * (value.f_files - value.f_ffree) / value.f_files, 2)
            if value.f_files else None,
            "read_only": bool(value.f_flag & os.ST_RDONLY)}


def collect(power_source: Path, previous: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    snapshot: dict[str, Any] = {"captured_at": now.isoformat(), "host": socket.gethostname(),
                                "thresholds": THRESHOLDS, "errors": {}, "disks": [], "sensors": []}
    snapshot["power"] = read_power(power_source, now)
    snapshot["boot_id"] = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    snapshot["uptime_seconds"] = float(Path("/proc/uptime").read_text().split()[0])
    snapshot["cpu_count"] = os.cpu_count() or 1
    snapshot["load_average"] = list(os.getloadavg())
    try:
        snapshot["memory"] = memory_usage(Path("/proc/meminfo").read_text())
    except (OSError, ValueError, KeyError, ZeroDivisionError) as exc:
        snapshot["errors"]["memory"] = type(exc).__name__
    try:
        ticks = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
        snapshot["cpu_ticks"] = {"total": sum(ticks), "idle": ticks[3] + ticks[4]}
        old = previous.get("cpu_ticks", {}) if previous.get("boot_id") == snapshot["boot_id"] else {}
        delta = sum(ticks) - old.get("total", sum(ticks))
        snapshot["cpu_used_percent"] = round(100 * (1 - (ticks[3] + ticks[4] - old["idle"]) / delta), 2) if delta > 0 else None
    except (OSError, ValueError, IndexError, KeyError) as exc:
        snapshot["errors"]["cpu"] = type(exc).__name__
    try:
        for mount, device in mount_paths(Path("/proc/self/mountinfo").read_text()):
            try:
                snapshot["disks"].append(disk_usage(mount, device))
            except OSError as exc:
                snapshot["errors"]["disk:" + mount] = type(exc).__name__
    except (OSError, ValueError, IndexError) as exc:
        snapshot["errors"]["disks"] = type(exc).__name__
    for directory in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            name = (directory / "name").read_text().strip()
            for path in sorted(directory.glob("temp*_input")):
                snapshot["sensors"].append({"name": name, "source": str(path),
                                             "temperature_c": round(int(path.read_text()) / 1000, 2)})
            for path in sorted(directory.glob("fan*_input")):
                snapshot["sensors"].append({"name": name, "source": str(path), "rpm": int(path.read_text())})
        except (OSError, ValueError) as exc:
            snapshot["errors"]["sensor:" + directory.name] = type(exc).__name__
    if not any(s["name"] == "cpu_thermal" for s in snapshot["sensors"]):
        snapshot["errors"]["cpu_temperature"] = "sensor unavailable"
    return snapshot


def alerts_for(snapshot: dict[str, Any]) -> dict[str, dict[str, str]]:
    alerts: dict[str, dict[str, str]] = {}

    def add(key: str, severity: str, message: str) -> None:
        alerts[key] = {"severity": severity, "message": message}

    def high(key: str, value: float, limits: dict[str, int], message: str) -> None:
        if value >= limits["warning"]:
            add(key, "critical" if value >= limits["critical"] else "warning", message)

    power = snapshot["power"]
    if power["status"] != "ok":
        add("power_telemetry", "warning", "電池／電源感測資料無法讀取或已過期")
    else:
        percent = power["battery_percent"]
        if percent <= THRESHOLDS["battery_percent"]["warning"]:
            add("battery", "critical" if percent <= THRESHOLDS["battery_percent"]["critical"] else "warning",
                f"電池剩餘 {percent}%：請接上電源")
        if min(power["cell_voltage_mv"]) < 3150:
            add("battery_cell", "critical", "電池單芯電壓低於 3.15V")
        if power["active_throttle_bits"]:
            add("power_throttling", "critical", "Scout 偵測到欠壓、頻率限制或過熱降頻")
        if power["ext5v_v"] < 4.8:
            add("supply_voltage", "warning", f"5V 供電偏低：{power['ext5v_v']:.2f}V")
    memory = snapshot.get("memory")
    if memory:
        high("memory", memory["used_percent"], THRESHOLDS["memory_used_percent"],
             f"記憶體使用 {memory['used_percent']:.1f}%，可用 {memory['available_bytes'] / 2**30:.2f} GiB")
    for disk in snapshot["disks"]:
        high("disk:" + disk["mount"], disk["used_percent"], THRESHOLDS["disk_used_percent"],
             f"磁碟 {disk['mount']} 使用 {disk['used_percent']:.1f}%，可用 {disk['available_bytes'] / 2**30:.1f} GiB")
        if disk["inode_used_percent"] is not None:
            high("inodes:" + disk["mount"], disk["inode_used_percent"], THRESHOLDS["inode_used_percent"],
                 f"磁碟 {disk['mount']} inode 使用 {disk['inode_used_percent']:.1f}%")
        if disk["mount"] == "/" and disk["read_only"]:
            add("root_read_only", "critical", "系統磁碟變成唯讀")
    for sensor in snapshot["sensors"]:
        kind = {"cpu_thermal": "cpu", "nvme": "nvme"}.get(sensor["name"])
        if kind and "temperature_c" in sensor:
            high("temperature:" + sensor["source"], sensor["temperature_c"], THRESHOLDS[kind + "_temperature_c"],
                 f"{kind.upper()} 溫度 {sensor['temperature_c']:.1f}°C")
    if snapshot["load_average"][1] > snapshot["cpu_count"] * 1.5:
        add("cpu_load", "warning", f"5 分鐘系統負載偏高：{snapshot['load_average'][1]:.2f}")
    for key in snapshot["errors"]:
        add("sensor:" + key, "warning", "無法讀取硬體指標：" + key)
    return alerts


def transitions(snapshot: dict[str, Any], previous: dict[str, Any]) -> list[str]:
    events = []
    old = previous.get("alerts", {})
    for key, alert in snapshot["alerts"].items():
        if old.get(key, {}).get("severity") != alert["severity"]:
            events.append(alert["severity"].upper() + " " + alert["message"])
    for key in old.keys() - snapshot["alerts"].keys():
        events.append("已恢復：" + old[key]["message"])
    old_power, power = previous.get("power", {}), snapshot["power"]
    if old_power.get("status") == power.get("status") == "ok" and old_power["flow"] != power["flow"]:
        events.append("電池狀態改變：" + {"charging": "充電中", "discharging": "放電中", "idle": "待機"}[power["flow"]])
    if previous.get("boot_id") and previous["boot_id"] != snapshot["boot_id"]:
        events.append("Scout 已重新啟動")
    return events


def notify_mac(message: str) -> dict[str, Any]:
    # Send data as a quoted argument to a fixed AppleScript, never interpolate code.
    script = 'on run argv\ndisplay notification (item 1 of argv) with title "Scout 硬體監控"\nend run'
    command = shlex.join(["/usr/bin/osascript", "-e", script, message])
    for host in MAC_HOSTS:
        try:
            result = subprocess.run(
                ["ssh", "-i", str(Path.home() / ".ssh/scout-to-mac"),
                 "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
                 "-o", "UserKnownHostsFile=" + str(Path.home() / ".ssh/known_hosts"),
                 "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                 "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=1",
                 "alexwang0315@" + host, command],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12,
            )
            if result.returncode == 0:
                return {"status": "notification_request_accepted", "host": host,
                        "note": "macOS accepted the notification request; banner visibility depends on notification settings"}
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {"status": "pending", "reason": "Mac notification request failed; retry after 5 minutes"}


def atomic_write(path: Path, value: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(value)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def describe(snapshot: dict[str, Any]) -> str:
    stamp = datetime.fromisoformat(snapshot["captured_at"]).astimezone().isoformat(timespec="seconds")
    lines = [f"Scout 硬體監控 [{snapshot['status'].upper()}] {stamp}"]
    power = snapshot["power"]
    if power["status"] == "ok":
        flow = {"charging": "充電", "discharging": "放電", "idle": "待機"}[power["flow"]]
        lines.append(f"電池 {power['battery_percent']}%／{flow} {abs(power['battery_power_w']):.2f}W／5V 供電 {power['ext5v_v']:.2f}V")
    else:
        lines.append("電池／電源資料不可用：" + power.get("error", "unknown"))
    memory = snapshot.get("memory")
    if memory:
        lines.append(f"記憶體 {memory['used_bytes'] / 2**30:.2f}/{memory['total_bytes'] / 2**30:.2f} GiB（{memory['used_percent']:.1f}%），可用 {memory['available_bytes'] / 2**30:.2f} GiB；Swap {memory['swap_used_bytes'] / 2**30:.2f} GiB")
    for disk in snapshot["disks"]:
        lines.append(f"磁碟 {disk['mount']}：{disk['used_percent']:.1f}%，可用 {disk['available_bytes'] / 2**30:.2f}/{disk['total_bytes'] / 2**30:.2f} GiB")
    for sensor in snapshot["sensors"]:
        if "temperature_c" in sensor:
            lines.append(f"{sensor['name']} {sensor['temperature_c']:.1f}°C")
        elif "rpm" in sensor:
            lines.append(f"{sensor['name']} {sensor['rpm']} RPM")
    if power["status"] == "ok":
        lines.append(f"欠壓／降頻旗標 {power['throttled_hex']}")
    lines.append("系統負載 1/5/15 分鐘：" + "/".join(f"{v:.2f}" for v in snapshot["load_average"]))
    lines.extend(alert["severity"].upper() + ": " + alert["message"] for alert in snapshot["alerts"].values())
    return "\n".join(lines) + "\n"


def run_once(state_dir: Path, power_source: Path, notify: bool) -> dict[str, Any]:
    os.umask(0o077)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_dir / "monitor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = state_dir / "status.json"
        previous = {}
        if state_path.exists():
            previous = json.loads(state_path.read_text())
        snapshot = collect(power_source, previous)
        snapshot["alerts"] = alerts_for(snapshot)
        severities = {alert["severity"] for alert in snapshot["alerts"].values()}
        snapshot["status"] = "critical" if "critical" in severities else "warning" if severities else "ok"
        events = transitions(snapshot, previous)
        pending = list(previous.get("pending_notifications", []))
        pending.extend(snapshot["captured_at"] + " " + event for event in events)
        # Events also have their own rotated journal; bound offline notification state.
        snapshot["older_pending_count"] = previous.get("older_pending_count", 0) + max(0, len(pending) - 100)
        snapshot["pending_notifications"] = pending = pending[-100:]
        snapshot["notification"] = {"status": "disabled" if not notify else "quiet"}
        snapshot["last_notification_attempt"] = previous.get("last_notification_attempt", 0)
        snapshot["summary"] = describe(snapshot)
        snapshot["next_steps"] = [a["message"] for a in snapshot["alerts"].values()]
        if not snapshot["next_steps"]:
            snapshot["next_steps"] = ["持續每分鐘監測"]
        # Checkpoint before outbound notification; retain changes while the Mac is away.
        atomic_write(state_path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        if notify and pending:
            if events or time.time() - snapshot["last_notification_attempt"] >= 300:
                snapshot["last_notification_attempt"] = time.time()
                message = "\n".join(pending[-3:])
                count = len(pending) + snapshot["older_pending_count"]
                if count > 3:
                    message += f"\n共 {count} 筆狀態變化，請查看 Scout 本機事件紀錄。"
                snapshot["notification"] = notify_mac(message)
                if snapshot["notification"]["status"] == "notification_request_accepted":
                    snapshot["pending_notifications"] = []
                    snapshot["older_pending_count"] = 0
            else:
                snapshot["notification"] = {"status": "pending", "reason": "waiting for retry"}
        atomic_write(state_path, json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        atomic_write(state_dir / "status.txt", snapshot["summary"])
        for filename, payload in [("history.jsonl", snapshot), ("events.jsonl", {"captured_at": snapshot["captured_at"], "events": events})]:
            if filename == "events.jsonl" and not events:
                continue
            handler = RotatingFileHandler(state_dir / filename, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
            try:
                handler.emit(logging.makeLogRecord({"msg": json.dumps(payload, ensure_ascii=False), "levelno": logging.INFO}))
            finally:
                handler.close()
        return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--power-source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--notify-mac", action="store_true", help="Enable notifications to the owner's pinned Mac via SSH")
    args = parser.parse_args()
    try:
        snapshot = run_once(args.state_dir.expanduser(), args.power_source.expanduser(), args.notify_mac)
    except BlockingIOError:
        return 0
    print(snapshot["summary"], end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
