from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class WifiAccessPoint:
    bssid: str
    source: Literal["iw", "nmcli"]
    ssid: str | None = None
    frequency_mhz: float | None = None
    channel: int | None = None
    signal_dbm: float | None = None
    signal_percent: int | None = None
    security: str | None = None
    associated: bool = False


@dataclass(frozen=True)
class WifiScanSnapshot:
    interface: str
    captured_at: str
    source: Literal["iw", "nmcli"]
    access_points: tuple[WifiAccessPoint, ...] = ()

    @property
    def strongest_access_point(self) -> WifiAccessPoint | None:
        if not self.access_points:
            return None
        if any(ap.signal_dbm is not None for ap in self.access_points):
            return max(self.access_points, key=lambda ap: ap.signal_dbm if ap.signal_dbm is not None else -999.0)
        return max(
            self.access_points,
            key=lambda ap: ap.signal_percent if ap.signal_percent is not None else -1,
        )


def scan_wifi(
    *,
    interface: str = "wlan0",
    prefer_iw: bool = True,
    timeout_seconds: float = 15.0,
) -> WifiScanSnapshot:
    if prefer_iw:
        iw_path = _find_iw()
        if iw_path is not None:
            try:
                completed = subprocess.run(
                    [str(iw_path), "dev", interface, "scan"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
                return parse_iw_scan(completed.stdout, interface=interface)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass

    completed = subprocess.run(
        [
            "nmcli",
            "-t",
            "-f",
            "BSSID,SSID,MODE,CHAN,RATE,SIGNAL,SECURITY",
            "dev",
            "wifi",
            "list",
            "--rescan",
            "yes",
            "ifname",
            interface,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return parse_nmcli_wifi_list(completed.stdout, interface=interface)


def parse_iw_scan(
    output: str,
    *,
    interface: str = "wlan0",
    captured_at: str | None = None,
) -> WifiScanSnapshot:
    access_points: list[WifiAccessPoint] = []
    current: dict[str, object] | None = None

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        bss_match = re.match(
            r"^BSS\s+([0-9A-Fa-f:]+)\(on\s+([^)]+)\)(?:\s+--\s+associated)?",
            line,
        )
        if bss_match:
            if current is not None:
                access_points.append(_access_point_from_iw_block(current))
            current = {
                "bssid": bss_match.group(1).lower(),
                "associated": "-- associated" in line,
            }
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped.startswith("freq:"):
            frequency = _optional_float(stripped.split(":", 1)[1].strip())
            current["frequency_mhz"] = frequency
            current["channel"] = wifi_channel_from_frequency_mhz(frequency)
        elif stripped.startswith("signal:"):
            signal = stripped.split(":", 1)[1].strip().removesuffix("dBm").strip()
            current["signal_dbm"] = _optional_float(signal)
        elif stripped.startswith("SSID:"):
            current["ssid"] = _normalize_ssid(stripped.split(":", 1)[1].strip())

    if current is not None:
        access_points.append(_access_point_from_iw_block(current))

    return WifiScanSnapshot(
        interface=interface,
        captured_at=captured_at or _utc_now_iso(),
        source="iw",
        access_points=tuple(access_points),
    )


def parse_nmcli_wifi_list(
    output: str,
    *,
    interface: str = "wlan0",
    captured_at: str | None = None,
) -> WifiScanSnapshot:
    access_points: list[WifiAccessPoint] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = _split_nmcli_terse(line)
        if len(parts) < 7:
            continue
        bssid, ssid, _mode, channel, _rate, signal, security = parts[:7]
        channel_int = _optional_int(channel)
        access_points.append(
            WifiAccessPoint(
                bssid=bssid.lower(),
                ssid=_normalize_ssid(ssid),
                frequency_mhz=frequency_mhz_from_wifi_channel(channel_int),
                channel=channel_int,
                signal_percent=_optional_int(signal),
                security=security or None,
                source="nmcli",
            )
        )

    return WifiScanSnapshot(
        interface=interface,
        captured_at=captured_at or _utc_now_iso(),
        source="nmcli",
        access_points=tuple(access_points),
    )


def server_signal_snapshot_from_wifi_scan(snapshot: WifiScanSnapshot) -> dict[str, object]:
    best = snapshot.strongest_access_point
    return {
        "source": f"pi_wifi_scan.{snapshot.source}",
        "interface": snapshot.interface,
        "captured_at": snapshot.captured_at,
        "best_bssid": best.bssid if best else None,
        "best_ssid": best.ssid if best else None,
        "best_rssi_dbm": best.signal_dbm if best else None,
        "best_signal_percent": best.signal_percent if best else None,
        "access_point_count": len(snapshot.access_points),
        "access_points": [asdict(ap) for ap in snapshot.access_points],
    }


def wifi_channel_from_frequency_mhz(frequency_mhz: float | None) -> int | None:
    if frequency_mhz is None:
        return None
    frequency = round(frequency_mhz)
    if 2412 <= frequency <= 2472:
        return int((frequency - 2407) / 5)
    if frequency == 2484:
        return 14
    if 5000 <= frequency <= 5895:
        return int((frequency - 5000) / 5)
    if 5955 <= frequency <= 7115:
        return int((frequency - 5950) / 5)
    return None


def frequency_mhz_from_wifi_channel(channel: int | None) -> float | None:
    if channel is None:
        return None
    if 1 <= channel <= 13:
        return float(2407 + channel * 5)
    if channel == 14:
        return 2484.0
    if 32 <= channel <= 177:
        return float(5000 + channel * 5)
    return None


def _access_point_from_iw_block(block: dict[str, object]) -> WifiAccessPoint:
    return WifiAccessPoint(
        bssid=str(block["bssid"]),
        ssid=block.get("ssid") if isinstance(block.get("ssid"), str) else None,
        frequency_mhz=block.get("frequency_mhz") if isinstance(block.get("frequency_mhz"), float) else None,
        channel=block.get("channel") if isinstance(block.get("channel"), int) else None,
        signal_dbm=block.get("signal_dbm") if isinstance(block.get("signal_dbm"), float) else None,
        associated=bool(block.get("associated")),
        source="iw",
    )


def _split_nmcli_terse(line: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current))
    return parts


def _find_iw() -> Path | None:
    found = shutil.which("iw")
    if found:
        return Path(found)
    for candidate in (Path("/sbin/iw"), Path("/usr/sbin/iw")):
        if candidate.exists():
            return candidate
    return None


def _normalize_ssid(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if re.fullmatch(r"(?:\\x00)+", value):
        return None
    return value


def _optional_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
