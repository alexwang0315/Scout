from __future__ import annotations

from pathlib import Path


SPEC_PATH = Path("docs/specs/phase-3-5-runtime-readiness-debug-tooling.md")


def read_spec() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def test_debug_tooling_spec_records_live_stream_and_projection_only_controls() -> None:
    source = read_spec()

    for token in (
        "read-only with respect to runtime truth",
        "Projection-only maintenance endpoints are allowed",
        "GET /debug/stream",
        "GET /debug/mobile-wearable/ingress",
        "POST /debug/clear",
        "POST /debug/mobile-wearable/ingress/reset",
        "Server-Sent Events",
        "manual refresh buttons",
        "confirm_debug_projection_clear=true",
        "confirm_mobile_wearable_ingress_debug_reset=true",
        "Neither endpoint may delete raw evidence JSONL",
        "call `/safety/*`",
        "write Phase 2 Brain facts",
        "control hardware",
    ):
        assert token in source


def test_debug_tooling_spec_records_operator_ui_requirements() -> None:
    source = read_spec()

    for token in (
        "EventSource",
        "projection-only controls must be placed in the panel they affect",
        "Timeline clear action belongs in the Timeline header",
        "mobile/wearable ingress reset belongs inside the Ingress panel",
        "memo/counters/status chips",
        "not one visual card or list item per incoming MQTT/provider message",
        "raw sensor values",
        "artifact refs only",
        "map feature mouse-over should provide named point/line/area hints",
        "debug headers, map controls, and toolbars should be compact",
    ):
        assert token in source
