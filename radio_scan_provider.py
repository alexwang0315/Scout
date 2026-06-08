from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class RadioScanContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RadioScanBoundary(RadioScanContractModel):
    host_side_only: Literal[True] = True
    read_only: Literal[True] = True
    docker_runtime_required: Literal[False] = False
    calls_safety_observations_allowed: Literal[False] = False
    phase1_safety_decision_change_allowed: Literal[False] = False
    incident_store_write_allowed: Literal[False] = False
    observed_fact_write_allowed: Literal[False] = False
    brain_write_allowed: Literal[False] = False
    outbound_send_allowed: Literal[False] = False
    hardware_provider_control_allowed: Literal[False] = False
    endpoint_calls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_no_endpoint_calls(self) -> "RadioScanBoundary":
        if self.endpoint_calls:
            raise ValueError("radio scan evidence must not call endpoints")
        return self


class RadioScanCounts(RadioScanContractModel):
    wifi_access_points: int = Field(ge=0)
    ble_devices: int = Field(ge=0)
    errors: int = Field(ge=0)


class RadioScanPayload(RadioScanContractModel):
    source: Literal["pi_radio_scan.host"] = "pi_radio_scan.host"
    evidence_kind: Literal["radio_environment_scan"] = "radio_environment_scan"
    captured_at: str = Field(min_length=1)
    boundary: RadioScanBoundary = Field(default_factory=RadioScanBoundary)
    phase1_safety_decision_change_allowed: Literal[False] = False
    wifi: dict[str, Any] | None = None
    ble: dict[str, Any] | None = None
    provider_errors: dict[str, str] = Field(default_factory=dict)
    radio_counts: RadioScanCounts

    @model_validator(mode="after")
    def enforce_counts_match_payload(self) -> "RadioScanPayload":
        expected_wifi_count = (
            int(self.wifi.get("access_point_count", 0)) if isinstance(self.wifi, dict) else 0
        )
        expected_ble_count = (
            int(self.ble.get("device_count", 0)) if isinstance(self.ble, dict) else 0
        )
        if self.radio_counts.wifi_access_points != expected_wifi_count:
            raise ValueError("radio scan Wi-Fi count does not match payload")
        if self.radio_counts.ble_devices != expected_ble_count:
            raise ValueError("radio scan BLE count does not match payload")
        if self.radio_counts.errors != len(self.provider_errors):
            raise ValueError("radio scan provider error count does not match payload")
        return self


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
    payload = {
        "source": snapshot.source,
        "evidence_kind": "radio_environment_scan",
        "captured_at": snapshot.captured_at,
        "boundary": RadioScanBoundary().model_dump(mode="json"),
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
    return validate_radio_scan_payload(payload).model_dump(mode="json")


def validate_radio_scan_payload(payload: dict[str, object]) -> RadioScanPayload:
    return RadioScanPayload.model_validate(payload)


def append_radio_scan_jsonl(snapshot: RadioScanSnapshot, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(radio_scan_payload(snapshot), ensure_ascii=False, sort_keys=True) + "\n")
    return output_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
