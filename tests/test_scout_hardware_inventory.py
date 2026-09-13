import json
from pathlib import Path
import subprocess

import pytest

from tools import scout_hardware_inventory as inventory
from tools.scout_hardware_monitor import alerts_for, transitions


def write(root, path, value=""):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value)
    return target


def fixture_tree(tmp_path):
    sys_root, dev_root = tmp_path / "sys", tmp_path / "dev"
    for path in ("class/net", "bus/usb/devices", "bus/pci/devices", "bus/i2c/devices"):
        (sys_root / path).mkdir(parents=True)
    dev_root.mkdir()
    (sys_root / "class/net/wlan0/wireless").mkdir(parents=True)
    write(sys_root, "class/net/wlan0/operstate", "up")
    write(sys_root, "class/net/eth0/device", "")
    write(sys_root, "class/net/eth0/operstate", "down")
    write(sys_root, "class/net/docker0/operstate", "down")
    write(sys_root, "class/rfkill/rfkill0/type", "wlan")
    write(sys_root, "class/rfkill/rfkill0/name", "phy0")
    write(sys_root, "class/rfkill/rfkill0/soft", "0")
    write(sys_root, "class/rfkill/rfkill0/hard", "0")
    write(sys_root, "bus/usb/devices/usb1/idVendor", "1d6b")
    write(sys_root, "bus/usb/devices/usb1/idProduct", "0002")
    write(sys_root, "bus/usb/devices/usb1/product", "Root hub")
    write(sys_root, "bus/usb/devices/1-1/idVendor", "1234")
    write(sys_root, "bus/usb/devices/1-1/product", "USB receiver")
    write(sys_root, "bus/pci/devices/0001:03:00.0/vendor", "0x1e60")
    write(sys_root, "bus/pci/devices/0001:03:00.0/device", "0x2864")
    write(sys_root, "bus/i2c/devices/i2c-1/name", "BCM I2C")
    write(sys_root, "bus/i2c/devices/1-003c/name", "display")
    write(dev_root, "ttyAMA0")
    return sys_root, dev_root


def command_fixture(args):
    if args == ["ip", "-j", "address", "show"]:
        return json.dumps([{"ifname": "wlan0", "addr_info": [{"family": "inet", "local": "192.0.2.10"}]}])
    if args == ["iw", "dev", "wlan0", "link"]:
        return 'Connected to aa:bb:cc:dd:ee:ff (on wlan0)\n\tSSID: Test <network>\n\tfreq: 2437.0\n\tsignal: -42 dBm\n\ttx bitrate: 72.2 MBit/s\n'
    if args == ["bluetoothctl", "list"]:
        return "Controller 11:22:33:44:55:66 Scout [default]\n"
    if args == ["bluetoothctl", "show", "11:22:33:44:55:66"]:
        return "Powered: yes\nDiscoverable: no\nPairable: no\nDiscovering: no\n"
    if args == ["bluetoothctl", "devices", "Connected"]:
        return "Device AA:BB:CC:DD:EE:FF Headphones\n"
    if args == ["lspci", "-Dmm"]:
        return '0001:03:00.0 "Co-processor" "Hailo Technologies Ltd." "Hailo-10H AI Processor" -r01\n'
    if args == ["gpioinfo"]:
        return 'gpiochip0 - 54 lines:\n line 5: "GPIO5" output consumer="lg"\n line 7: "GPIO7" output active-low consumer="spi0 CS1"\n line 33: "-" input\n'
    if args == ["gpiodetect"]:
        return 'gpiochip0 [pinctrl-rp1] (54 lines)\n'
    raise AssertionError("Unexpected command: " + repr(args))


def test_realistic_inventory_is_passive_and_keeps_distinct_evidence(tmp_path):
    sys_root, dev_root = fixture_tree(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    calls = []
    def run(args):
        calls.append(args)
        return command_fixture(args)
    result = inventory.collect_inventory({"status": "ok", "captured_at": "2026-09-11T00:00:00Z"}, sys_root=sys_root, dev_root=dev_root, run=run)
    assert result["status"] == "ok"
    assert result["active_scan_performed"] is False
    sections = result["sections"]
    assert len(sections["network"]["items"]) == 2
    wifi = next(v for v in sections["network"]["items"] if v["id"] == "wlan0")
    assert wifi["properties"]["ssid"] == "Test <network>"
    assert wifi["properties"]["signal_dbm"] == -42
    assert sections["bluetooth"]["items"][0]["state"] == "powered_on"
    assert sections["bluetooth"]["items"][1]["state"] == "connected"
    assert len(sections["usb"]["items"]) == 2
    assert sections["pcie"]["items"][0]["name"] == "Hailo-10H AI Processor"
    assert {v["properties"]["kind"] for v in sections["i2c"]["items"]} == {"adapter", "registered_device", "telemetry_device"}
    assert sections["gpio"]["items"][0]["name"] == "pinctrl-rp1"
    assert sections["gpio"]["items"][0]["lines"][0]["consumer"] == "lg"
    assert sections["gpio"]["items"][0]["lines"][1]["active_low"] is True
    assert all(v["value"] is None for v in sections["gpio"]["items"][0]["lines"])
    assert all(c[0] not in {"i2cdetect", "gpioget", "gpioset", "nmcli"} for c in calls)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_stale_ups_is_not_claimed_as_detected_i2c_device(tmp_path):
    sys_root, _ = fixture_tree(tmp_path)
    result = inventory.i2c(sys_root, {"status": "unavailable"})
    assert not any(v["properties"]["kind"] == "telemetry_device" for v in result["items"])


def test_ups_inventory_follows_ups_not_host_supply(tmp_path):
    sys_root, _ = fixture_tree(tmp_path)
    power = {"status": "unavailable", "ups_status": "ok", "supply_status": "unavailable",
             "captured_at": "2026-09-13T00:00:00Z"}
    assert any(v["properties"]["kind"] == "telemetry_device" for v in inventory.i2c(sys_root, power)["items"])
    power.update(ups_status="unavailable", supply_status="ok")
    assert not any(v["properties"]["kind"] == "telemetry_device" for v in inventory.i2c(sys_root, power)["items"])


def test_a_failed_optional_command_preserves_other_categories(tmp_path):
    sys_root, dev_root = fixture_tree(tmp_path)
    def run(args):
        if args[0] == "bluetoothctl":
            raise subprocess.TimeoutExpired(args, 3)
        return command_fixture(args)
    result = inventory.collect_inventory({}, sys_root=sys_root, dev_root=dev_root, run=run)
    assert result["status"] == "partial"
    assert result["sections"]["bluetooth"]["status"] == "unavailable"
    assert result["sections"]["network"]["status"] == "ok"
    assert result["sections"]["gpio"]["items"]


def test_disconnected_wifi_and_radio_block(tmp_path):
    sys_root, _ = fixture_tree(tmp_path)
    write(sys_root, "class/rfkill/rfkill0/soft", "1")
    def run(args):
        return "Not connected.\n" if args[0] == "iw" else command_fixture(args)
    result = inventory.network(sys_root, run)
    wifi = next(v for v in result["items"] if v["id"] == "wlan0")
    assert wifi["state"] == "blocked"
    assert wifi["properties"]["signal_dbm"] is None


def test_unrecognized_wifi_output_does_not_claim_disconnection(tmp_path):
    with pytest.raises(ValueError):
        inventory.parse_wifi_link("driver returned an unexpected reply")
    sys_root, _ = fixture_tree(tmp_path)
    result = inventory.network(sys_root, lambda args: "unexpected" if args[0] == "iw" else command_fixture(args))
    assert result["status"] == "partial"
    wifi = next(v for v in result["items"] if v["id"] == "wlan0")
    assert wifi["properties"]["ssid"] is None
    assert wifi["state"] == "connected"  # The separate operstate reading still reports link up.


def test_connection_changes_create_events_without_gpio_activity_noise():
    base = {"alerts": {}, "power": {"status": "unavailable"}, "inventory": {"sections": {"network": {
        "status": "ok", "summary": "1 connected", "items": [{"id": "wlan0", "state": "connected"}]}}}}
    new = json.loads(json.dumps(base))
    new["inventory"]["sections"]["network"].update(summary="0 connected", items=[{"id": "wlan0", "state": "disconnected"}])
    assert transitions(new, base) == ["網路裝置或連線狀態改變：0 connected"]
    assert transitions(base, base) == []
