from pathlib import Path


HARDWARE_DIRECTION_PATH = Path("docs/specs/scout-hardware-direction.md")
HARDWARE_PORT_PLAN_PATH = Path("docs/specs/hardware-port-plan.md")


def test_hardware_direction_documents_host_side_radio_scan_tools() -> None:
    source = HARDWARE_DIRECTION_PATH.read_text(encoding="utf-8")

    for token in (
        "### Host-Side Radio Scan Tools",
        "wifi_scan_provider.py",
        "ble_scan_provider.py",
        "radio_scan_provider.py",
        "tools/pi_wifi_scan_smoke.py",
        "tools/pi_ble_scan_smoke.py",
        "tools/pi_radio_scan_smoke.py",
        "fixed read-only `boundary` block",
        "validates `radio_counts`",
        "not call `/safety/observations`",
        "write IncidentStore",
        "ObservedFact",
        "Brain records",
        "send outbound messages",
        "control hardware providers",
        "change Phase 1 safety decisions",
    ):
        assert token in source


def test_hardware_port_plan_keeps_radio_scan_provider_read_only() -> None:
    source = HARDWARE_PORT_PLAN_PATH.read_text(encoding="utf-8")

    for token in (
        "### Host-Side Radio Scan Provider",
        "tools/pi_wifi_scan_smoke.py",
        "tools/pi_ble_scan_smoke.py",
        "/data/scout/providers/radio_scan/*.jsonl",
        "run this on the Pi host",
        "not inside the Step 1 Docker safety runtime",
        "fixed read-only `boundary` block",
        "validate `radio_counts`",
        "do not call `/safety/observations`",
        "write IncidentStore",
        "write ObservedFact",
        "write Phase 2 Brain",
        "send outbound messages",
        "control hardware providers",
        "change Phase 1 safety decisions",
    ):
        assert token in source
