from __future__ import annotations

import re
import signal
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BleDeviceObservation:
    address: str
    address_type: str
    rssi_dbm: int
    flags: str | None = None
    ad_flags: str | None = None
    eir_len: int | None = None
    name: str | None = None
    source: Literal["btmgmt"] = "btmgmt"


@dataclass(frozen=True)
class BleScanSnapshot:
    controller: str = "hci0"
    source: Literal["btmgmt"] = "btmgmt"
    captured_at: str = ""
    devices: tuple[BleDeviceObservation, ...] = ()

    @property
    def strongest_device(self) -> BleDeviceObservation | None:
        if not self.devices:
            return None
        return max(self.devices, key=lambda device: device.rssi_dbm)


def scan_ble(
    *,
    controller: str = "hci0",
    duration_seconds: float = 10.0,
) -> BleScanSnapshot:
    btmgmt_path = _find_btmgmt()
    if btmgmt_path is None:
        raise FileNotFoundError("btmgmt was not found on PATH or in /usr/bin")

    command = [str(btmgmt_path), "--index", _btmgmt_index(controller), "find"]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=duration_seconds)
    except subprocess.TimeoutExpired:
        process.send_signal(signal.SIGINT)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2)

    output = "\n".join(part for part in (stdout, stderr) if part)
    if process.returncode not in (0, -signal.SIGINT, None):
        raise subprocess.CalledProcessError(
            process.returncode,
            command,
            output=stdout,
            stderr=stderr,
        )
    return parse_btmgmt_find(output, controller=controller)


def parse_btmgmt_find(
    output: str,
    *,
    controller: str = "hci0",
    captured_at: str | None = None,
) -> BleScanSnapshot:
    devices: list[BleDeviceObservation] = []
    current: dict[str, object] | None = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        found_match = re.match(
            r"^(hci\d+)\s+dev_found:\s+([0-9A-Fa-f:]+)\s+type\s+(.+?)\s+rssi\s+(-?\d+)\s+flags\s+(0x[0-9A-Fa-f]+)",
            line,
        )
        if found_match:
            if current is not None:
                devices.append(_device_from_btmgmt_block(current))
            controller = found_match.group(1)
            current = {
                "address": found_match.group(2).lower(),
                "address_type": found_match.group(3).strip(),
                "rssi_dbm": int(found_match.group(4)),
                "flags": found_match.group(5).lower(),
            }
            continue

        if current is None:
            continue

        ad_flags_match = re.match(r"^AD flags\s+(0x[0-9A-Fa-f]+)", line)
        if ad_flags_match:
            current["ad_flags"] = ad_flags_match.group(1).lower()
            continue

        eir_len_match = re.match(r"^eir_len\s+(\d+)", line)
        if eir_len_match:
            current["eir_len"] = int(eir_len_match.group(1))
            continue

        name_match = re.match(r"^(?:name|short name)\s+(.+)$", line, re.IGNORECASE)
        if name_match:
            current["name"] = name_match.group(1).strip()

    if current is not None:
        devices.append(_device_from_btmgmt_block(current))

    return BleScanSnapshot(
        controller=controller,
        captured_at=captured_at or _utc_now_iso(),
        devices=tuple(devices),
    )


def server_signal_snapshot_from_ble_scan(snapshot: BleScanSnapshot) -> dict[str, object]:
    strongest = snapshot.strongest_device
    return {
        "source": f"pi_ble_scan.{snapshot.source}",
        "evidence_kind": "ble_proximity_scan",
        "identity_stability": "unknown_for_random_addresses",
        "controller": snapshot.controller,
        "captured_at": snapshot.captured_at,
        "strongest_address": strongest.address if strongest else None,
        "strongest_address_type": strongest.address_type if strongest else None,
        "strongest_rssi_dbm": strongest.rssi_dbm if strongest else None,
        "device_count": len(snapshot.devices),
        "devices": [asdict(device) for device in snapshot.devices],
    }


def _device_from_btmgmt_block(block: dict[str, object]) -> BleDeviceObservation:
    return BleDeviceObservation(
        address=str(block["address"]),
        address_type=str(block["address_type"]),
        rssi_dbm=int(block["rssi_dbm"]),
        flags=block.get("flags") if isinstance(block.get("flags"), str) else None,
        ad_flags=block.get("ad_flags") if isinstance(block.get("ad_flags"), str) else None,
        eir_len=block.get("eir_len") if isinstance(block.get("eir_len"), int) else None,
        name=block.get("name") if isinstance(block.get("name"), str) else None,
    )


def _find_btmgmt() -> Path | None:
    found = shutil.which("btmgmt")
    if found:
        return Path(found)
    candidate = Path("/usr/bin/btmgmt")
    return candidate if candidate.exists() else None


def _btmgmt_index(controller: str) -> str:
    match = re.fullmatch(r"hci(\d+)", controller)
    return match.group(1) if match else controller


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
