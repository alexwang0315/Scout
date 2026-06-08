from __future__ import annotations

import json
from pathlib import Path

from tools.admin_ui_smoke_app import _debug_events


ROOT = Path(__file__).resolve().parents[1]


def test_ui_operation_browser_smoke_runner_is_documented_in_package_scripts() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert (
        package["scripts"]["scout-ui:operation-smoke"]
        == "node tools/scout_ui_operation_browser_smoke.js --pretty"
    )
    script = (ROOT / "tools/scout_ui_operation_browser_smoke.js").read_text(
        encoding="utf-8"
    )
    assert "scout_ui_operation_browser_smoke" in script
    assert "promptCount" in script
    assert "window.ScoutAssistantUI.applyUiActionPlan" in script


def test_admin_ui_smoke_debug_event_000002_is_focusable_for_ui_corpus() -> None:
    events = _debug_events()
    event = events[1]

    assert event.event_id == "debug_event.admin_ui_smoke.000002"
    assert event.kind == "safety_event_emitted"
    assert event.subject_ref == "cp.003"
    assert event.payload["checkpoint_id"] == "cp.003"
    assert event.payload["lat"]
    assert event.payload["lon"]
