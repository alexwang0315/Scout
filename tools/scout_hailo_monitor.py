"""Bounded read-only Hailo-10H telemetry; no inference, writes or persistent child.

HailoRT 5.3 monitor queries performance over one second and health independently.
The CLI labels binary MiB as MB (KiB / 1024 in upstream accelerator_monitor.cpp).
Convert the reported integer MiB to bytes; do not claim byte-level precision.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import os
import re
import selectors
import signal
import subprocess
import time


COMMAND = ("/usr/bin/hailortcli", "monitor")
MAX_OUTPUT_BYTES = 128 * 1024
MAX_STDERR_BYTES = 4096
DEVICE_ID = re.compile(r"pci/[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]\Z")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
METRICS = ("nnc_utilization_percent", "cpu_utilization_percent", "ram_utilization_percent",
           "ram_used_bytes", "ram_total_bytes", "temperature_c", "voltage_mv")


def unknown_device(device_id: str, error: str) -> dict:
    return {"device_id": device_id, "architecture": "unknown", "status": "unavailable",
            **dict.fromkeys(METRICS), "errors": [error]}


def _number(raw: str, *, low: float, high: float | None = None) -> float | None:
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and low <= value and (high is None or value <= high) else None


def parse_monitor_table(output: bytes) -> dict[str, dict]:
    """Only the first complete table is usable; never mix successive samples."""
    text = ANSI.sub("", output.decode("utf-8", errors="replace"))
    rows: dict[str, dict] = {}
    header_seen = False
    for line in text.split("\n")[:-1]:  # Keep an incomplete trailing row out.
        if line.startswith("Device ID"):
            if header_seen:
                break
            header_seen = all(label in line for label in (
                "NNC Utilization (%)", "CPU Utilization (%)", "RAM Utilization (%)",
                "RAM Usage (MB)", "On Die Temperature (C)", "On Die Voltage (mV)"))
            continue
        cells = line.split()
        if not header_seen or not cells or not DEVICE_ID.fullmatch(cells[0]):
            continue
        device_id = cells[0]
        if device_id in rows:
            rows[device_id] = unknown_device(device_id, "duplicate_device")
            continue
        if len(cells) not in (8, 10) or cells[1] != "HAILO10H":
            rows[device_id] = unknown_device(device_id, "invalid_telemetry")
            continue
        device = {"device_id": device_id, "architecture": cells[1], "errors": []}
        for key, raw in zip(METRICS[:3], cells[2:5]):
            device[key] = _number(raw, low=0, high=100)
        used = total = None
        if len(cells) == 10 and cells[6] == "/":
            if all(len(token) <= 10 and token.isascii() and token.isdigit() for token in (cells[5], cells[7])):
                used, total = int(cells[5]) * 1024**2, int(cells[7]) * 1024**2
                if total <= 0 or used > total or total > 1024**5:
                    used = total = None
        device.update(ram_used_bytes=used, ram_total_bytes=total,
                      temperature_c=_number(cells[-2], low=-273.15),
                      voltage_mv=_number(cells[-1], low=0))
        # HailoRT's invalid-stat sentinel is -1, including temperature.
        if device["temperature_c"] == -1:
            device["temperature_c"] = None
        missing = [key for key in METRICS if device[key] is None]
        device["status"] = "ok" if not missing else "unavailable" if len(missing) == len(METRICS) else "partial"
        device["errors"] = ["unknown:" + key for key in missing]
        rows[device_id] = device
    return rows


def _read_table(expected: set[str], timeout: float) -> tuple[dict[str, dict], str | None]:
    """Drain both pipes; stop after the first table and always reap the child."""
    process = None
    raw = bytearray()
    error_bytes = 0
    deadline = time.monotonic() + timeout
    rows: dict[str, dict] = {}
    try:
        process = subprocess.Popen(COMMAND, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False, bufsize=0,
                                   env={**os.environ, "LC_ALL": "C"})
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return rows, "timeout"
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stderr":
                        error_bytes += len(chunk)
                        if error_bytes > MAX_STDERR_BYTES:
                            return rows, "command_failed"
                    else:
                        raw.extend(chunk)
                        if len(raw) > MAX_OUTPUT_BYTES:
                            return {}, "output_too_large"
                        rows = parse_monitor_table(bytes(raw))
                if expected.issubset(rows):
                    return rows, None
            return rows, "command_failed" if process.wait(timeout=max(0.01, deadline - time.monotonic())) else "incomplete_sample"
    except FileNotFoundError:
        return {}, "cli_unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return {}, "command_failed"
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGINT)
                    process.wait(timeout=0.5)
                except ProcessLookupError:
                    pass
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
            process.wait()
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()


def collect_hailo(inventory: dict, *, timeout: float | None = None) -> dict:
    """Collect only known enumerated Hailo devices; metadata absence is not zero."""
    pcie = (inventory or {}).get("sections", {}).get("pcie", {})
    expected = set()
    for item in pcie.get("items", []):
        props = item.get("properties") or {}
        if props.get("vendor") == "0x1e60" or str(item.get("driver") or "").startswith("hailo"):
            device_id = "pci/" + str(item.get("id", ""))
            if DEVICE_ID.fullmatch(device_id):
                expected.add(device_id)
    error = None
    if not expected:
        rows = {}
        if pcie.get("status") != "ok":
            error = "inventory_unavailable"
    else:
        rows, error = _read_table(expected, timeout if timeout is not None else min(30, 3 + 2 * len(expected)))
    devices = [rows.get(device_id, unknown_device(device_id, error or "device_unavailable"))
               for device_id in sorted(expected)]
    errors = [error] if error else []
    statuses = {d["status"] for d in devices}
    status = "unavailable" if (error and not devices) or statuses == {"unavailable"} else "partial" if errors or statuses - {"ok"} else "ok"
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "status": status,
            "source": "hailortcli.monitor", "sample_window_ms": 1000, "read_only": True,
            "devices": devices, "errors": errors}


def hailo_transitions(snapshot: dict, previous: dict) -> list[str]:
    """Local journal only: these events must never join outbound notifications."""
    before, after = previous.get("hailo"), snapshot.get("hailo")
    if not before or not after:
        return []  # Installing the field into legacy history is not a recovery.
    titles = {"ok": "已讀取", "partial": "部分可讀", "unavailable": "無法讀取"}
    events = []
    if before["status"] != after["status"]:
        events.append("Hailo 監控資料狀態改變：" + titles[after["status"]])
    old = {d["device_id"]: d["status"] for d in before["devices"]}
    new = {d["device_id"]: d["status"] for d in after["devices"]}
    for device_id in sorted(old.keys() | new.keys()):
        if device_id not in new:
            events.append("Hailo 本次清單未列出裝置：" + device_id)
        elif device_id not in old:
            events.append("Hailo 本次清單新增裝置：" + device_id)
        elif old[device_id] != new[device_id]:
            events.append("Hailo 裝置資料狀態改變：" + device_id + " · " + titles[new[device_id]])
    return events
