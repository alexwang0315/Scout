from __future__ import annotations

import json
import subprocess
import sys

from ble_scan_provider import parse_btmgmt_find
from radio_scan_provider import (
    RadioScanSnapshot,
    append_radio_scan_jsonl,
    radio_scan_payload,
)
from wifi_scan_provider import parse_iw_scan


def test_radio_scan_payload_combines_wifi_and_ble_evidence() -> None:
    wifi = parse_iw_scan(
        """
BSS 60:83:e7:30:32:92(on wlan0) -- associated
\tfreq: 5785.0
\tsignal: -27.00 dBm
\tSSID: ASUS_5G
""",
        captured_at="2026-05-20T00:00:00+00:00",
    )
    ble = parse_btmgmt_find(
        """
hci0 dev_found: 5C:34:75:85:1E:1D type LE Random rssi -40 flags 0x0000
AD flags 0x1a
eir_len 30
""",
        captured_at="2026-05-20T00:00:01+00:00",
    )

    payload = radio_scan_payload(RadioScanSnapshot(captured_at="2026-05-20T00:00:02+00:00", wifi=wifi, ble=ble))

    assert payload["source"] == "pi_radio_scan.host"
    assert payload["evidence_kind"] == "radio_environment_scan"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["wifi"]["best_bssid"] == "60:83:e7:30:32:92"
    assert payload["wifi"]["best_rssi_dbm"] == -27.0
    assert payload["ble"]["strongest_address"] == "5c:34:75:85:1e:1d"
    assert payload["ble"]["strongest_rssi_dbm"] == -40
    assert payload["radio_counts"] == {"wifi_access_points": 1, "ble_devices": 1, "errors": 0}


def test_radio_scan_payload_records_provider_errors_without_failing_snapshot() -> None:
    payload = radio_scan_payload(
        RadioScanSnapshot(
            captured_at="2026-05-20T00:00:02+00:00",
            provider_errors={"wifi": "PermissionError: scan not allowed"},
        )
    )

    assert payload["wifi"] is None
    assert payload["ble"] is None
    assert payload["provider_errors"] == {"wifi": "PermissionError: scan not allowed"}
    assert payload["radio_counts"] == {"wifi_access_points": 0, "ble_devices": 0, "errors": 1}


def test_append_radio_scan_jsonl_writes_one_json_line(tmp_path) -> None:
    output_path = tmp_path / "radio_scan.jsonl"
    snapshot = RadioScanSnapshot(
        captured_at="2026-05-20T00:00:02+00:00",
        wifi=parse_iw_scan(
            """
BSS 60:83:e7:30:32:92(on wlan0) -- associated
\tfreq: 5785.0
\tsignal: -27.00 dBm
\tSSID: ASUS_5G
""",
            captured_at="2026-05-20T00:00:00+00:00",
        ),
    )

    append_radio_scan_jsonl(snapshot, output_path)

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["wifi"]["best_ssid"] == "ASUS_5G"
    assert payload["ble"] is None


def test_radio_scan_smoke_cli_can_emit_disabled_scan_evidence_without_hardware(tmp_path) -> None:
    output_path = tmp_path / "radio_scan.jsonl"

    completed = subprocess.run(
        [
            sys.executable,
            "tools/pi_radio_scan_smoke.py",
            "--no-wifi",
            "--no-ble",
            "--output-jsonl",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["source"] == "pi_radio_scan.host"
    assert payload["evidence_kind"] == "radio_environment_scan"
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["wifi"] is None
    assert payload["ble"] is None
    assert payload["provider_errors"] == {}
    assert payload["radio_counts"] == {"wifi_access_points": 0, "ble_devices": 0, "errors": 0}
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1
