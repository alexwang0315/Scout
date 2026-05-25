from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hardware_readiness_assistant_context import build_hardware_readiness_assistant_context


ROOT = Path(__file__).resolve().parent
DEFAULT_HARDWARE_READINESS_FIXTURE = ROOT / "tests" / "fixtures" / "hardware" / "readiness_context.json"


def load_hardware_readiness_fixture(
    fixture_path: Path | str = DEFAULT_HARDWARE_READINESS_FIXTURE,
) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    return {
        "interface_inventory": list(payload.get("interface_inventory") or []),
        "provider_health": list(payload.get("provider_health") or []),
        "sample_replay_timeline": list(payload.get("sample_replay_timeline") or []),
        "runtime_debug_events": list(payload.get("runtime_debug_events") or []),
        "mock_transport_queue": list(payload.get("mock_transport_queue") or []),
    }


def build_hardware_readiness_admin_view(
    *,
    fixture_path: Path | str = DEFAULT_HARDWARE_READINESS_FIXTURE,
    selected_provider_ref: str | None = None,
) -> dict[str, Any]:
    fixture = load_hardware_readiness_fixture(fixture_path)
    context = build_hardware_readiness_assistant_context(
        interface_inventory=fixture["interface_inventory"],
        provider_health=fixture["provider_health"],
        sample_replay_timeline=fixture["sample_replay_timeline"],
        runtime_debug_events=fixture["runtime_debug_events"],
        mock_transport_queue=fixture["mock_transport_queue"],
        selected_provider_ref=selected_provider_ref,
    )
    return {
        "surface": "hardware_readiness",
        "read_only": True,
        "model_interpretation": False,
        "fixture_path": str(Path(fixture_path)),
        "summary": context["summary"],
        "selected_provider": context["selected_provider"],
        "interface_inventory": context["interface_inventory"],
        "provider_health": context["provider_health"],
        "sample_replay_timeline": context["sample_replay_timeline"],
        "runtime_debug_events": context["runtime_debug_events"],
        "mock_transport_queue": context["mock_transport_queue"],
        "sources": context["sources"],
        "boundary": context["boundary"],
        "limitations": context["limitations"],
    }
