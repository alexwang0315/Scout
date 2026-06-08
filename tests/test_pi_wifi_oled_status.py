from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from wifi_scan_provider import parse_iw_scan, parse_nmcli_wifi_list


ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "pi_wifi_oled_status_test",
        ROOT / "tools" / "pi_wifi_oled_status.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wifi_oled_message_shows_ip_active_ssid_and_visible_ssids() -> None:
    module = _load_tool_module()
    snapshot = parse_iw_scan(
        """
BSS 60:83:e7:30:32:92(on wlan0) -- associated
\tfreq: 5785.0
\tsignal: -27.00 dBm
\tSSID: Field_Hotspot
BSS ac:9e:17:77:3f:08(on wlan0)
\tfreq: 2437.0
\tsignal: -55.00 dBm
\tSSID: Trailhead
""",
        captured_at="2026-05-29T00:00:00+00:00",
    )

    message = module.build_wifi_oled_message(
        snapshot,
        active_ssid="Field_Hotspot",
        ipv4_addresses=["172.20.10.4"],
    )

    assert "SCOUT WIFI" in message
    assert "IP 172.20.10.4" in message
    assert "ON FIELD-HOTSP" in message
    assert "AP 2" in message
    assert "A FIELD-HOTS -27" in message
    assert "2 TRAILHEAD -55" in message


def test_wifi_oled_payload_keeps_diagnostic_safety_boundaries() -> None:
    module = _load_tool_module()
    snapshot = parse_nmcli_wifi_list(
        r"60\:83\:E7\:30\:32\:92:ScoutField:Infra:6:130 Mbit/s:83:WPA2",
        captured_at="2026-05-29T00:00:00+00:00",
    )
    message = module.build_wifi_oled_message(
        snapshot,
        active_ssid="ScoutField",
        ipv4_addresses=["172.20.10.4"],
    )

    payload = module.build_payload(
        snapshot=snapshot,
        interface="wlan0",
        source_requested="nmcli",
        active_ssid="ScoutField",
        ipv4_addresses=["172.20.10.4"],
        message=message,
        bus=Path("/dev/i2c-1"),
        address=0x3C,
        driver_attempted="sh1107g",
        write_status="dry_run",
        dry_run=True,
    )

    assert payload["source"] == "pi_wifi_oled_status"
    assert payload["hardware_kind"] == "wifi_scan_oled_boot_diagnostic"
    assert payload["access_point_count"] == 1
    assert payload["best_ssid"] == "ScoutField"
    assert payload["visible_ssids"] == ["ScoutField"]
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "diagnostic_display_only"


def test_wifi_oled_cli_dry_run_writes_jsonl_without_hardware(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_tool_module()
    output = tmp_path / "wifi-oled.jsonl"
    snapshot = parse_nmcli_wifi_list(
        r"60\:83\:E7\:30\:32\:92:ScoutField:Infra:6:130 Mbit/s:83:WPA2",
        captured_at="2026-05-29T00:00:00+00:00",
    )
    calls: list[dict[str, object]] = []

    def fake_scan_wifi(**kwargs):
        calls.append(kwargs)
        return snapshot

    monkeypatch.setattr(module, "scan_wifi", fake_scan_wifi)
    monkeypatch.setattr(module, "discover_active_ssid", lambda **kwargs: "ScoutField")
    monkeypatch.setattr(module, "discover_ipv4_addresses", lambda **kwargs: ["172.20.10.4"])

    result = module.main(
        [
            "--source",
            "nmcli",
            "--timeout-seconds",
            "1",
            "--dry-run",
            "--output-jsonl",
            str(output),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    persisted = [json.loads(line) for line in output.read_text().splitlines()]
    assert calls == [{"interface": "wlan0", "prefer_iw": False, "timeout_seconds": 1.0}]
    assert payload["oled_write_status"] == "dry_run"
    assert payload["active_ssid"] == "ScoutField"
    assert "SCOUT WIFI" in payload["oled_message"]
    assert persisted == [payload]


def test_wifi_oled_cli_scan_error_fails_cleanly_and_can_still_dry_run_oled(monkeypatch, capsys) -> None:
    module = _load_tool_module()

    def fake_scan_wifi(**kwargs):
        raise RuntimeError("scan not allowed")

    monkeypatch.setattr(module, "scan_wifi", fake_scan_wifi)
    monkeypatch.setattr(module, "discover_active_ssid", lambda **kwargs: None)
    monkeypatch.setattr(module, "discover_ipv4_addresses", lambda **kwargs: [])

    result = module.main(["--dry-run"])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["access_point_count"] == 0
    assert payload["oled_write_status"] == "dry_run"
    assert "SCAN ERR" in payload["oled_message"]
    assert "RuntimeError: scan not allowed" in payload["error"]
    assert payload["phase1_safety_decision_change_allowed"] is False


def test_wifi_oled_cli_rejects_invalid_max_ssid_lines(monkeypatch) -> None:
    module = _load_tool_module()
    monkeypatch.setattr(sys, "argv", ["pi_wifi_oled_status.py", "--max-ssid-lines", "-1"])

    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover
        raise AssertionError("expected argparse SystemExit")
