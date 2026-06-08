from pathlib import Path

from fastapi.testclient import TestClient

from hardware_readiness_api import create_hardware_readiness_app


ROOT = Path(__file__).resolve().parents[1]


def test_hardware_readiness_context_is_fixture_backed_and_read_only():
    client = TestClient(create_hardware_readiness_app())

    response = client.get("/admin/hardware-readiness/context?selected_provider_ref=provider.gnss.primary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["surface"] == "hardware_readiness"
    assert payload["read_only"] is True
    assert payload["summary"]["interface_count"] == 10
    assert set(payload["summary"]["interface_statuses"]) == {"available", "planned"}
    assert payload["summary"]["provider_count"] == 2
    assert payload["summary"]["degraded_provider_count"] == 1
    assert payload["selected_provider"]["provider_ref"] == "provider.gnss.primary"
    assert payload["boundary"]["hardware_control_allowed"] is False
    assert payload["boundary"]["gpio_lab_mode_drive_policy_allowed"] is True
    assert payload["boundary"]["gpio_drive_requires_wiring_manifest"] is True
    assert payload["boundary"]["gpio_drive_implementation_enabled"] is False
    assert payload["boundary"]["gpio_drive_operator_confirmation_required"] is True
    assert payload["boundary"]["provider_control_allowed"] is False
    assert payload["boundary"]["outbound_send_allowed"] is False
    assert payload["boundary"]["real_sos_allowed"] is False
    interfaces = {item["interface_ref"]: item for item in payload["interface_inventory"]}
    assert interfaces["gpio.bank0.controls"]["interface_type"] == "gpio"
    assert interfaces["gpio.bank0.controls"]["manual_drive_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["manual_read_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["manual_write_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["details"]["pi5_header_gpio_count"] == 28
    assert len(interfaces["gpio.bank0.controls"]["observed_lines"]) == 28
    assert interfaces["gpio.bank0.controls"]["boundary"]["manual_pull_high_low_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["lab_mode_drive_policy_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["wiring_manifest_required"] is True
    assert interfaces["gpio.bank0.controls"]["boundary"]["wiring_manifest_confirmed"] is False
    assert interfaces["gpio.bank0.controls"]["boundary"]["gpioset_command_enabled"] is False
    assert interfaces["gpio.bank0.controls"]["boundary"]["gpioset_implementation_present"] is False
    assert interfaces["gpio.bank0.controls"]["boundary"]["write_performed_by_probe"] is False
    assert interfaces["gpio.bank0.controls"]["signal_activity"] == "direction_observed_value_not_sampled"
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["pull_state"] == "not_sampled"
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["manual_read_allowed"] is True
    assert interfaces["gpio.bank0.controls"]["observed_lines"][0]["manual_write_allowed"] is True
    reserved = [
        line
        for line in interfaces["gpio.bank0.controls"]["observed_lines"]
        if line["pull_control"] == "reserved_advanced_use"
    ]
    assert {line["gpio"] for line in reserved} == {0, 1}
    assert interfaces["i2c.bus1.sensors"]["signal_activity"] == "tool_or_device_node_not_seen"
    assert interfaces["bluetooth.adapter0"]["details"]["powered"] is True
    assert interfaces["uart.gnss.future"]["status"] == "available"
    assert interfaces["usb.devices"]["devices"][0]["id"] == "0b05:1bc3"
    assert interfaces["storage.ssd.data_root"]["interface_type"] == "ssd"
    assert interfaces["storage.ssd.data_root"]["details"]["disk_model"] == "KINGSTON SNV3S1000G"
    assert interfaces["i2s.audio.tts"]["interface_type"] == "i2s_tts"


def test_hardware_readiness_admin_page_serves_static_shell_and_shared_script():
    client = TestClient(create_hardware_readiness_app())

    page = client.get("/admin/hardware-readiness")
    script = client.get("/admin/scout-assistant-ui.js")

    assert page.status_code == 200
    assert "Scout Hardware Readiness" in page.text
    assert 'data-ui-style="template-console"' in page.text
    assert 'data-layout="provider-first-console"' in page.text
    assert 'data-boundary="no-hardware-provider-mutation"' in page.text
    assert 'data-assistant-default-visible="true"' in page.text
    assert "data-assistant-surface=\"hardware_readiness\"" in page.text
    assert "read-only model interpretation" in page.text
    assert "Provider dry-run review. Fixture-backed. No control path." in page.text
    assert "Hardware interface inventory" in page.text
    assert "GPIO, I2C, I2S/TTS, Bluetooth, UART, battery, GNSS, IMU, USB, and SSD metadata." in page.text
    assert 'id="interfaceCount"' in page.text
    assert 'id="interfaceGrid"' in page.text
    assert "renderInterfaces" in page.text
    assert "devices=${devices.map" in page.text
    assert "rw_lines=${writable.length}" in page.text
    assert "advanced=${advanced.map" in page.text
    assert "gpioset_enabled=${boundary.gpioset_command_enabled" in page.text
    assert "wiring_confirmed=${boundary.wiring_manifest_confirmed" in page.text
    assert "drive_gate=wiring_manifest_required" in page.text
    assert "Object.entries(details).slice(0, 5)" in page.text
    assert "No hardware control, provider control, real SOS, outbound transport, Phase 1 runtime writes, or Phase 2 Brain writes." in page.text
    assert "Select context only." in page.text
    assert "/assistant/query" in page.text
    assert "/assistant/status" in page.text
    assert "/admin/hardware-readiness/context" in page.text
    assert "No hardware control or provider control." in page.text
    assert "No real SOS, SMS, satellite, or outbound transport." in page.text
    assert ">Why degraded?</button>" in page.text
    assert ">Evidence?</button>" in page.text
    assert ">Blockers?</button>" in page.text
    assert "function assistantQuestionLabel" in page.text
    assert script.status_code == 200
    assert "window.ScoutAssistantUI" in script.text


def test_hardware_readiness_api_has_no_mutation_methods():
    client = TestClient(create_hardware_readiness_app())

    assert client.post("/admin/hardware-readiness/context", json={}).status_code == 405
    assert client.patch("/admin/hardware-readiness/context", json={}).status_code == 405
    assert client.delete("/admin/hardware-readiness/context").status_code == 405

    source = (ROOT / "hardware_readiness_api.py").read_text(encoding="utf-8")
    for forbidden_fragment in (
        "@router.post",
        "@router.patch",
        "@router.put",
        "@router.delete",
        "/safety/",
        "SafetyRuntimeSession",
        "IncidentStore",
        "append_review_decision",
    ):
        assert forbidden_fragment not in source
