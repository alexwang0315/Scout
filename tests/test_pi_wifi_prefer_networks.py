from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module():
    spec = importlib.util.spec_from_file_location(
        "pi_wifi_prefer_networks_test",
        ROOT / "tools" / "pi_wifi_prefer_networks.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _network_config() -> str:
    return """network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
  wifis:
    wlan0:
      dhcp4: true
      regulatory-domain: "TW"
      access-points:
        "Songsong_iPhone17":
          password: "field-hotspot"
        "王佳祥的iphone(2)":
          password: "backup-hotspot"
        "ASUS_5G":
          password: "stable-wifi"
      optional: true
"""


def test_parse_access_points_without_exposing_passwords_in_plan() -> None:
    module = _load_tool_module()

    access_points = module.parse_access_point_blocks(_network_config())
    plan = module.build_plan(
        access_points=access_points,
        primary_ssid="ASUS_5G",
        fallback_ssids=["Songsong_iPhone17"],
        primary_priority=100,
        fallback_priority=-20,
    )

    assert [access_point.ssid for access_point in access_points] == [
        "Songsong_iPhone17",
        "王佳祥的iphone(2)",
        "ASUS_5G",
    ]
    assert plan == [
        {
            "ssid": "ASUS_5G",
            "connection_name": "scout-wifi-ASUS_5G",
            "priority": 100,
            "password_available": True,
            "action": "create_or_update_nm_profile",
        },
        {
            "ssid": "Songsong_iPhone17",
            "connection_name": "scout-wifi-Songsong_iPhone17",
            "priority": -21,
            "password_available": True,
            "action": "create_or_update_nm_profile",
        },
    ]
    assert "stable-wifi" not in json.dumps(plan)
    assert "field-hotspot" not in json.dumps(plan)


def test_reorder_access_points_prefers_primary_ssid() -> None:
    module = _load_tool_module()

    reordered = module.reorder_access_points(
        _network_config(),
        ["ASUS_5G", "Songsong_iPhone17", "王佳祥的iphone(2)"],
    )

    assert reordered.index('"ASUS_5G"') < reordered.index('"Songsong_iPhone17"')
    assert reordered.index('"Songsong_iPhone17"') < reordered.index('"王佳祥的iphone(2)"')
    assert 'regulatory-domain: "TW"' in reordered
    assert "optional: true" in reordered


def test_cli_dry_run_reports_fixed_boundaries(capsys, tmp_path: Path) -> None:
    module = _load_tool_module()
    network_config = tmp_path / "network-config"
    network_config.write_text(_network_config(), encoding="utf-8")

    result = module.main(["--network-config", str(network_config)])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "pi_wifi_prefer_networks"
    assert payload["hardware_kind"] == "field_wifi_priority_configuration"
    assert payload["primary_ssid"] == "ASUS_5G"
    assert payload["fallback_ssids"] == ["Songsong_iPhone17", "王佳祥的iphone(2)"]
    assert payload["applied"] is False
    assert payload["phase1_safety_decision_change_allowed"] is False
    assert payload["remote_outbound_allowed"] is False
    assert payload["hardware_control_scope"] == "wifi_boot_preference_configuration_only"


def test_cli_apply_without_root_fails_cleanly(monkeypatch, capsys, tmp_path: Path) -> None:
    module = _load_tool_module()
    network_config = tmp_path / "network-config"
    network_config.write_text(_network_config(), encoding="utf-8")
    monkeypatch.setattr(module.os, "geteuid", lambda: 501)

    result = module.main(["--network-config", str(network_config), "--apply"])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert "PermissionError" in payload["error"]
    assert payload["phase1_safety_decision_change_allowed"] is False
