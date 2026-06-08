from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from ble_scan_provider import parse_btmgmt_find
from wifi_scan_provider import parse_iw_scan


ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pi_wifi_scan_smoke_cli_outputs_read_only_wifi_evidence(monkeypatch, capsys) -> None:
    module = _load_tool_module("pi_wifi_scan_smoke_test", "tools/pi_wifi_scan_smoke.py")
    snapshot = parse_iw_scan(
        """
BSS 60:83:e7:30:32:92(on wlan0) -- associated
\tfreq: 5785.0
\tsignal: -27.00 dBm
\tSSID: ASUS_5G
""",
        captured_at="2026-05-20T00:00:00+00:00",
    )
    calls: list[dict[str, object]] = []

    def fake_scan_wifi(**kwargs):
        calls.append(kwargs)
        return snapshot

    monkeypatch.setattr(module, "scan_wifi", fake_scan_wifi)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pi_wifi_scan_smoke.py", "--interface", "wlan0", "--source", "iw", "--timeout-seconds", "1"],
    )

    assert module.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == [{"interface": "wlan0", "prefer_iw": True, "timeout_seconds": 1.0}]
    assert payload["source"] == "pi_wifi_scan.iw"
    assert payload["best_bssid"] == "60:83:e7:30:32:92"
    assert payload["best_rssi_dbm"] == -27.0
    assert payload["access_point_count"] == 1


def test_pi_ble_scan_smoke_cli_outputs_read_only_ble_evidence(monkeypatch, capsys) -> None:
    module = _load_tool_module("pi_ble_scan_smoke_test", "tools/pi_ble_scan_smoke.py")
    snapshot = parse_btmgmt_find(
        """
hci0 dev_found: 5C:34:75:85:1E:1D type LE Random rssi -40 flags 0x0000
AD flags 0x1a
eir_len 30
""",
        captured_at="2026-05-20T00:00:00+00:00",
    )
    calls: list[dict[str, object]] = []

    def fake_scan_ble(**kwargs):
        calls.append(kwargs)
        return snapshot

    monkeypatch.setattr(module, "scan_ble", fake_scan_ble)
    monkeypatch.setattr(
        sys,
        "argv",
        ["pi_ble_scan_smoke.py", "--controller", "hci0", "--duration-seconds", "1"],
    )

    assert module.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == [{"controller": "hci0", "duration_seconds": 1.0}]
    assert payload["source"] == "pi_ble_scan.btmgmt"
    assert payload["evidence_kind"] == "ble_proximity_scan"
    assert payload["identity_stability"] == "unknown_for_random_addresses"
    assert payload["strongest_rssi_dbm"] == -40
