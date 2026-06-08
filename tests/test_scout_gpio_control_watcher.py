from __future__ import annotations

import inspect
from pathlib import Path

import scout_gpio_control_watcher
from hardware_control_events import HardwareControlEventType
from scout_gpio_control_watcher import build_gpio_control_projection_report, load_fixture_events


FIXTURE_PATH = Path("tests/fixtures/hardware/gpio_control_events_manual_sos.json")


def test_load_fixture_events_validates_gpio_projection_events() -> None:
    events = load_fixture_events(FIXTURE_PATH)

    assert len(events) == 3
    assert events[0].event_type == HardwareControlEventType.MANUAL_SOS_BUTTON_OBSERVED
    assert events[0].source == "gpio.sos_button"
    assert events[0].pattern == "long_press_plus_three_short"


def test_projection_report_never_posts_to_safety_runtime() -> None:
    report = build_gpio_control_projection_report(load_fixture_events(FIXTURE_PATH))

    assert report["status"] == "projection_ready"
    assert report["events_loaded"] == 3
    assert report["network_calls_performed"] is False
    assert report["safety_mutation_performed"] is False
    assert report["outbound_messages_sent"] is False
    assert report["hardware_provider_controlled"] is False
    assert report["projections"][0]["annotation_only"] is True


def test_gpio_watcher_has_no_network_or_safety_endpoint_code() -> None:
    source = inspect.getsource(scout_gpio_control_watcher)

    for forbidden in ("urllib", "requests", "httpx", "/safety/", "urlopen", "POST"):
        assert forbidden not in source
