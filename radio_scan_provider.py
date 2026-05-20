from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ble_scan_provider import (
    BleScanSnapshot,
    scan_ble,
    server_signal_snapshot_from_ble_scan,
)
from wifi_scan_provider import (
    WifiScanSnapshot,
    scan_wifi,
    server_signal_snapshot_from_wifi_scan,
)


@dataclass(frozen=True)
class RadioScanSnapshot:
    captured_at: str
    source: str = "pi_radio_scan.host"
    wifi: WifiScanSnapshot | None = None
    ble: BleScanSnapshot | None = None
    provider_errors: dict[str, str] = field(default_factory=dict)


def scan_radio_environment(
    *,
    wifi_enabled: bool = True,
    ble_enabled: bool = True,
    wifi_interface: str = "wlan0",
    wifi_prefer_iw: bool = True,
    ble_controller: str = "hci0",
    ble_duration_seconds: float = 10.0,
) -> RadioScanSnapshot:
    provider_errors: dict[str, str] = {}
    wifi: WifiScanSnapshot | None = None
    ble: BleScanSnapshot | None = None

    if wifi_enabled:
        try:
            wifi = scan_wifi(interface=wifi_interface, prefer_iw=wifi_prefer_iw)
        except Exception as exc:  # pragma: no cover - hardware/runtime specific
            provider_errors["wifi"] = f"{type(exc).__name__}: {exc}"

    if ble_enabled:
        try:
            ble = scan_ble(controller=ble_controller, duration_seconds=ble_duration_seconds)
        except Exception as exc:  # pragma: no cover - hardware/runtime specific
            provider_errors["ble"] = f"{type(exc).__name__}: {exc}"

    return RadioScanSnapshot(
        captured_at=_utc_now_iso(),
        wifi=wifi,
        ble=ble,
        provider_errors=provider_errors,
    )


def radio_scan_payload(snapshot: RadioScanSnapshot) -> dict[str, object]:
    wifi_payload = server_signal_snapshot_from_wifi_scan(snapshot.wifi) if snapshot.wifi else None
    ble_payload = server_signal_snapshot_from_ble_scan(snapshot.ble) if snapshot.ble else None
    return {
        "source": snapshot.source,
        "evidence_kind": "radio_environment_scan",
        "captured_at": snapshot.captured_at,
        "phase1_safety_decision_change_allowed": False,
        "wifi": wifi_payload,
        "ble": ble_payload,
        "provider_errors": snapshot.provider_errors,
        "radio_counts": {
            "wifi_access_points": len(snapshot.wifi.access_points) if snapshot.wifi else 0,
            "ble_devices": len(snapshot.ble.devices) if snapshot.ble else 0,
            "errors": len(snapshot.provider_errors),
        },
    }


def append_radio_scan_jsonl(snapshot: RadioScanSnapshot, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(radio_scan_payload(snapshot), ensure_ascii=False, sort_keys=True) + "\n")
    return output_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
