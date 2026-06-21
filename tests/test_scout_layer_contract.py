from __future__ import annotations

from pathlib import Path

from scout_layer_contract import (
    SCOUT_LAYER_IDS,
    SCOUT_SURFACE_LAYER_IDS,
)
from tools.verify_scout_layer_contract import run_checks


ROOT = Path(__file__).resolve().parents[1]


def test_scout_layer_contract_static_gate_passes() -> None:
    result = run_checks(repo_root=ROOT)

    assert result["ok"], result["errors"]
    assert result["layer_count"] == len(SCOUT_LAYER_IDS)
    assert tuple(result["layers"].keys()) == SCOUT_LAYER_IDS


def test_completed_track_is_after_action_only_but_still_in_contract() -> None:
    assert "completed-track" in SCOUT_LAYER_IDS
    assert "completed-track" not in SCOUT_SURFACE_LAYER_IDS["pretrip"]
    assert "completed-track" not in SCOUT_SURFACE_LAYER_IDS["debug"]
    assert "completed-track" in SCOUT_SURFACE_LAYER_IDS["after-action"]


def test_browser_smoke_lists_every_layer_for_toggle_check() -> None:
    smoke_script = (ROOT / "tools" / "admin_ui_visual_smoke.js").read_text()

    for layer_id in SCOUT_LAYER_IDS:
        assert f'"{layer_id}"' in smoke_script
    assert "layerControlChecks" in smoke_script
    assert "failedToggles" in smoke_script
