from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hardware_control_events import HardwareControlEvent, project_hardware_control_event


def load_fixture_events(path: Path) -> list[HardwareControlEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("events", [payload])
    if not isinstance(payload, list):
        raise ValueError("hardware control fixture must be a JSON object, list, or object with events")
    return [HardwareControlEvent.model_validate(item) for item in payload]


def build_gpio_control_projection_report(events: list[HardwareControlEvent]) -> dict[str, Any]:
    projections = [project_hardware_control_event(event) for event in events]
    return {
        "artifact_kind": "gpio_control_projection_report",
        "status": "projection_ready",
        "events_loaded": len(events),
        "network_calls_performed": False,
        "safety_mutation_performed": False,
        "outbound_messages_sent": False,
        "hardware_provider_controlled": False,
        "projections": [projection.model_dump(mode="json") for projection in projections],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render Scout GPIO control fixture events as read-only projections."
    )
    parser.add_argument("--fixture-events", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        events = load_fixture_events(args.fixture_events)
        report = build_gpio_control_projection_report(events)
    except (OSError, ValueError, ValidationError) as exc:
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
