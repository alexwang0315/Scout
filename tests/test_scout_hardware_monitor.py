import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tools import scout_hardware_monitor as monitor


def power_record(now):
    return {"captured_at": now.isoformat(), "battery_percent": 80,
            "battery_voltage_mv": 16000, "battery_current_ma": -400,
            "ups_vbus_power_mw": 0, "remaining_capacity_mah": 3800,
            "ext5v_v": 5.2, "cell_voltage_mv": [4000] * 4, "throttled_hex": "0x0", "errors": []}


def snapshot(tmp_path):
    now = datetime.now(timezone.utc)
    source = tmp_path / "power.jsonl"
    source.write_text(json.dumps(power_record(now)) + "\n")
    return {"captured_at": now.isoformat(), "host": "fixture", "boot_id": "boot-1",
            "power": monitor.read_power(source, now), "errors": {}, "sensors": [],
            "cpu_count": 4, "load_average": [0.1, 0.1, 0.1],
            "memory": {"total_bytes": 8 * 2**30, "used_bytes": 2**30,
                       "available_bytes": 7 * 2**30, "used_percent": 12.5, "swap_used_bytes": 0},
            "disks": [{"mount": "/", "device": "/dev/nvme0n1p2", "used_percent": 20,
                       "used_bytes": 200 * 2**30, "total_bytes": 1000 * 2**30,
                       "available_bytes": 800 * 2**30, "inode_used_percent": 5, "read_only": False}]}


def test_large_log_tail_and_partial_append(tmp_path):
    now = datetime.now(timezone.utc)
    source = tmp_path / "power.jsonl"
    with source.open("wb") as stream:
        stream.seek(20 * 1024 * 1024)
        stream.write(b"\n" + json.dumps(power_record(now)).encode() + b'\n{"captured_at":')
    power = monitor.read_power(source, now)
    assert power["status"] == "ok"
    assert power["flow"] == "discharging"
    assert power["battery_power_w"] == -6.4


@pytest.mark.parametrize("change", ["stale", "future", "sensor_error", "bad_percent", "missing", "bad_last_line"])
def test_invalid_or_stale_power_is_never_healthy(tmp_path, change):
    now = datetime.now(timezone.utc)
    source = tmp_path / "power.jsonl"
    raw = power_record(now)
    if change == "stale":
        raw["captured_at"] = (now - timedelta(seconds=16)).isoformat()
    elif change == "future":
        raw["captured_at"] = (now + timedelta(seconds=20)).isoformat()
    elif change == "sensor_error":
        raw["errors"] = ["ups_i2c:OSError"]
    elif change == "bad_percent":
        raw["battery_percent"] = 65535
    elif change == "missing":
        del raw["battery_current_ma"]
    source.write_text(json.dumps(raw) + "\n" + ("broken\n" if change == "bad_last_line" else ""))
    assert monitor.read_power(source, now)["status"] == "unavailable"


def test_memory_uses_available_including_reclaimable_cache():
    result = monitor.memory_usage("MemTotal: 8000 kB\nMemFree: 100 kB\nMemAvailable: 6000 kB\nSwapTotal: 2000 kB\nSwapFree: 2000 kB\n")
    assert result["used_percent"] == 25
    assert result["used_bytes"] == 2000 * 1024
    assert result["swap_used_bytes"] == 0


def test_mounts_and_df_reserved_space(tmp_path, monkeypatch):
    mounts = monitor.mount_paths("1 2 3:4 / / rw - ext4 /dev/root rw\n"
                                 "2 3 0:1 / /tmp rw - tmpfs tmpfs rw\n"
                                 "3 4 8:1 / /media/My\\040SSD rw - ext4 /dev/sda1 rw\n")
    assert mounts == [("/", "/dev/root"), ("/media/My SSD", "/dev/sda1")]
    monkeypatch.setattr(monitor.os, "statvfs", lambda _: SimpleNamespace(
        f_blocks=100, f_bfree=20, f_bavail=10, f_frsize=1024,
        f_files=100, f_ffree=95, f_flag=0))
    assert monitor.disk_usage("/", "/dev/root")["used_percent"] == 88.89


def test_all_thresholds_and_historical_throttling(tmp_path):
    current = snapshot(tmp_path)
    current["power"]["historical_throttle_bits"] = 15
    assert monitor.alerts_for(current) == {}
    current["power"].update(battery_percent=10, active_throttle_bits=1)
    current["memory"]["used_percent"] = 95
    current["disks"][0].update(used_percent=95, inode_used_percent=96, read_only=True)
    current["sensors"] = [{"name": "cpu_thermal", "source": "cpu", "temperature_c": 85},
                           {"name": "nvme", "source": "ssd", "temperature_c": 75}]
    alerts = monitor.alerts_for(current)
    assert set(alerts) == {"battery", "power_throttling", "memory", "disk:/", "inodes:/", "root_read_only", "temperature:cpu", "temperature:ssd"}
    assert all(a["severity"] == "critical" for a in alerts.values())


def test_notification_trajectory_dedupes_escalates_recovers_and_retries(tmp_path, monkeypatch):
    current = snapshot(tmp_path)
    state = tmp_path / "state"
    notifications = []
    monkeypatch.setattr(monitor, "collect", lambda *_: copy.deepcopy(current))
    def notify(message):
        notifications.append(message)
        return {"status": "notification_request_accepted"}
    monkeypatch.setattr(monitor, "notify_mac", notify)
    monitor.run_once(state, tmp_path / "unused", True)
    assert not notifications
    current["power"]["battery_percent"] = 20
    monitor.run_once(state, tmp_path / "unused", True)
    current["power"]["battery_percent"] = 19
    monitor.run_once(state, tmp_path / "unused", True)
    assert len(notifications) == 1
    current["power"]["battery_percent"] = 10
    monitor.run_once(state, tmp_path / "unused", True)
    assert len(notifications) == 2
    current["power"]["battery_percent"] = 80
    monitor.run_once(state, tmp_path / "unused", True)
    assert "已恢復" in notifications[-1]
    monkeypatch.setattr(monitor, "notify_mac", lambda _: {"status": "pending"})
    current["power"] = {"status": "unavailable", "error": "fixture missing"}
    failed = monitor.run_once(state, tmp_path / "unused", True)
    assert failed["pending_notifications"]
    monkeypatch.setattr(monitor, "time", SimpleNamespace(time=lambda: failed["last_notification_attempt"] + 301))
    monkeypatch.setattr(monitor, "notify_mac", notify)
    recovered = monitor.run_once(state, tmp_path / "unused", True)
    assert not recovered["pending_notifications"]
    assert json.loads((state / "status.json").read_text())["status"] == "warning"
    assert len((state / "history.jsonl").read_text().splitlines()) == 7
    assert len((state / "events.jsonl").read_text().splitlines()) == 4


def test_ssh_notification_is_fixed_script_with_data_argument(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(monitor.subprocess, "run", run)
    message = 'test "quotes" $(do-not-execute) `literal`\nsecond line'
    assert monitor.notify_mac(message)["status"] == "notification_request_accepted"
    command, kwargs = calls[0]
    assert shlex.split(command[-1])[-1] == message
    assert "StrictHostKeyChecking=yes" in command
    assert "IdentitiesOnly=yes" in command
    assert "shell" not in kwargs


def test_installer_render_does_not_activate_or_overwrite(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/install-scout-hardware-monitor.py"
    command = [sys.executable, str(script), "--render-only", str(tmp_path), "--notify-mac"]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "OnCalendar=*-*-* *:*:00" in (tmp_path / "scout-hardware-monitor.timer").read_text()
    assert "--notify-mac" in (tmp_path / "scout-hardware-monitor.service").read_text()
    assert subprocess.run(command, capture_output=True).returncode != 0
