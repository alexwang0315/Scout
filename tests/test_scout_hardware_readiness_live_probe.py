from __future__ import annotations

import json
import re

import scout_hardware_readiness_live_probe as probe


SAMPLE_OUTPUT = """__SCOUT_PROBE_SECTION__ host
host=scout
kernel=Linux 6.12.75+rpt-rpi-2712 aarch64 GNU/Linux
user=alexwang0315
date=2026-05-22T14:39:24+08:00
__SCOUT_PROBE_SECTION__ df
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       917G   19G  861G   3% /
__SCOUT_PROBE_SECTION__ lsblk_json
{"blockdevices":[{"name":"sda","type":"disk","size":"931.5G","mountpoint":null,"fstype":null,"model":"KINGSTON SNV3S1000G","tran":"usb","children":[{"name":"sda2","type":"part","size":"931G","mountpoint":"/","fstype":"ext4","model":null,"tran":null}]}]}
__SCOUT_PROBE_SECTION__ gpio_tools
/usr/bin/gpiodetect
/usr/bin/gpioinfo
/usr/bin/gpioget
/usr/bin/gpioset
__SCOUT_PROBE_SECTION__ gpiodetect
gpiochip0 [pinctrl-rp1] (54 lines)
gpiochip10 [gpio-brcmstb@107d508500] (32 lines)
__SCOUT_PROBE_SECTION__ gpioinfo
gpiochip0 - 54 lines:
\tline   2:\t"GPIO2"         \tinput
\tline   3:\t"GPIO3"         \tinput
\tline  17:\t"GPIO17"        \tinput
\tline  27:\t"GPIO27"        \tinput
__SCOUT_PROBE_SECTION__ i2c
__SCOUT_PROBE_SECTION__ audio_tts
/usr/bin/bluealsa-aplay
__SCOUT_PROBE_SECTION__ bluetooth
/usr/bin/bluetoothctl
Controller 88:A2:9E:58:EF:4A (public)
\tName: scout
\tPowered: yes
__SCOUT_PROBE_SECTION__ uart
/dev/ttyAMA10
__SCOUT_PROBE_SECTION__ usb
Bus 002 Device 002: ID 0b05:1bc3 ASUSTek Computer, Inc. ASUS Cobble
"""


def test_build_probe_result_maps_live_sections_to_interface_inventory() -> None:
    result = probe.build_probe_result("scout", SAMPLE_OUTPUT)

    assert result.status == "collected"
    assert result.boundary.read_only_probe is True
    assert result.boundary.gpio_lab_mode_drive_policy_allowed is True
    assert result.boundary.gpio_drive_requires_wiring_manifest is True
    assert result.boundary.gpio_drive_implementation_enabled is False
    assert result.boundary.gpio_drive_operator_confirmation_required is True
    assert result.boundary.gpio_value_sampling_performed is False
    assert result.boundary.gpio_drive_performed is False
    assert result.boundary.i2c_transaction_performed is False
    assert result.boundary.runtime_started is False
    assert result.observations["host"] == "scout"
    assert len(result.interface_inventory) == 10

    interfaces = {item["interface_ref"]: item for item in result.interface_inventory}
    assert interfaces["gpio.bank0.controls"]["status"] == "available"
    assert interfaces["gpio.bank0.controls"]["manual_read_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["manual_write_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["manual_drive_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["manual_pull_high_low_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["lab_mode_drive_policy_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["wiring_manifest_required"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["wiring_manifest_confirmed"] is False
    assert interfaces["gpio.bank0.controls"]["boundary"]["gpioset_command_enabled"] is False
    assert interfaces["gpio.bank0.controls"]["boundary"]["gpioset_implementation_present"] is False
    assert interfaces["gpio.bank0.controls"]["boundary"]["write_performed_by_probe"] is False
    assert interfaces["gpio.bank0.controls"]["pi5_header_gpio_count"] == 28
    assert len(interfaces["gpio.bank0.controls"]["observed_lines"]) == 28
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["pull_state"] == "not_sampled"
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["manual_read_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["manual_write_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["pull_control"] == "fixed_pull_up"
    reserved = [
        line
        for line in interfaces["gpio.bank0.controls"]["observed_lines"]
        if line["pull_control"] == "reserved_advanced_use"
    ]
    assert {line["gpio"] for line in reserved} == {0, 1}
    assert interfaces["i2c.bus1.sensors"]["signal_activity"] == "tool_or_device_node_not_seen"
    assert interfaces["i2s.audio.tts"]["status"] == "available"
    assert interfaces["bluetooth.adapter0"]["adapter_address"] == "88:A2:9E:58:EF:4A"
    assert interfaces["uart.gnss.future"]["port"] == "/dev/ttyAMA10"
    assert interfaces["usb.devices"]["devices"][0]["id"] == "0b05:1bc3"
    assert interfaces["storage.ssd.data_root"]["disk_model"] == "KINGSTON SNV3S1000G"
    assert interfaces["storage.ssd.data_root"]["free_space"] == "861G"


def test_remote_probe_script_is_metadata_only_and_does_not_sample_or_drive_gpio() -> None:
    script = probe.build_remote_probe_script()

    assert "gpioinfo" in script
    assert "gpiodetect" in script
    assert "command -v gpioget" in script
    assert "command -v gpioset" in script
    assert "i2cdetect" in script
    assert "bluetoothctl show" in script
    assert "lsblk -J" in script
    assert not re.search(r"^gpioget\b", script, flags=re.MULTILINE)
    assert not re.search(r"^gpioset\b", script, flags=re.MULTILINE)
    assert "i2cdetect -y" not in script
    assert "/safety/" not in script
    assert "systemctl start" not in script


def test_cli_outputs_failed_artifact_when_ssh_probe_fails(monkeypatch, capsys) -> None:
    def fake_run_remote_probe(host: str, *, timeout_seconds: int) -> str:
        raise RuntimeError("ssh unavailable")

    monkeypatch.setattr(probe, "run_remote_probe", fake_run_remote_probe)
    returncode = probe.main(["--host", "scout"])

    assert returncode == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact_kind"] == "scout_hardware_readiness_live_probe"
    assert payload["status"] == "failed"
    assert payload["boundary"]["gpio_lab_mode_drive_policy_allowed"] is True
    assert payload["boundary"]["gpio_drive_requires_wiring_manifest"] is True
    assert payload["boundary"]["gpio_drive_implementation_enabled"] is False
    assert payload["boundary"]["gpio_drive_performed"] is False
    assert payload["boundary"]["safety_mutation_performed"] is False
