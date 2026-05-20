from __future__ import annotations

import inspect
import json
from pathlib import Path

import hardware_control_events
from hardware_control_events import HardwareControlEvent, HardwareControlEventType, project_hardware_control_event


FIXTURE_PATH = Path("tests/fixtures/hardware/gpio_control_events_manual_sos.json")


def load_events() -> list[HardwareControlEvent]:
    return [HardwareControlEvent.model_validate(item) for item in json.loads(FIXTURE_PATH.read_text())]


def test_gpio_control_events_are_projection_only() -> None:
    event = load_events()[0]

    projection = project_hardware_control_event(event)

    assert event.event_type == HardwareControlEventType.MANUAL_SOS_BUTTON_OBSERVED
    assert projection.annotation_only is True
    assert projection.requires_operator_review is True
    assert projection.boundary.safety_mutation_allowed is False
    assert projection.boundary.phase1_safety_decision_mutation_allowed is False
    assert projection.boundary.incident_package_write_allowed is False
    assert projection.boundary.outbound_send_allowed is False
    assert projection.boundary.hardware_provider_control_allowed is False


def test_gpio_control_contract_has_no_safety_runtime_imports() -> None:
    source = inspect.getsource(hardware_control_events)

    for forbidden in (
        "safety_api",
        "safety_models",
        "safety_runtime_session",
        "incident_store",
        "/safety/",
        "urllib",
        "requests",
        "httpx",
    ):
        assert forbidden not in source
