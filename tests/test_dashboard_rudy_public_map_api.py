"""D037 contract against an actual pinned Map instance, without GPU/network qualification."""
import json
import os
import shutil
import subprocess

import pytest

from test_dashboard_rudy_live_diagnostic import MODULE, ROOT

REPLAY = ROOT / "tests/fixtures/rudy_public_map_motion_replay.cjs"


@pytest.mark.parametrize("surface", ["navigation", "pretrip", "debug"])
@pytest.mark.parametrize("action", ["fit", "left", "right", "up", "down"])
def test_actual_pinned_map_public_motion_stops_before_exact_view(surface, action):
    result = subprocess.run(
        [shutil.which("node"), str(REPLAY), str(MODULE), surface, action],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
    )
    receipt = json.loads(result.stdout)
    output = os.environ.get("SCOUT_CAMERA_REPLAY_EVIDENCE")
    if output:
        from pathlib import Path
        Path(output).mkdir(parents=True, exist_ok=True)
        (Path(output) / f"{surface}-{action}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    assert receipt["realMapInstance"] is True
    assert receipt["publicIsMoving"] == "function"
    assert receipt["publicIsEasing"] == "undefined"
    assert all(not row["ownIsEasing"] for row in receipt["prototypes"])
    assert receipt["initialMapMoving"] is False
    assert receipt["initialMotion"]["available"] is True
    assert receipt["initialMotion"]["moving"] is False
    assert receipt["initialMotion"]["easing"] is None, "No invented isEasing=false receipt"
    assert receipt["actionStatus"] == "stopped", receipt.get("error")
    observations = receipt["actionReceipt"]["observations"]
    assert observations[0]["observedAt"] == 240
    assert observations[0]["moving"] is True
    assert observations[-1]["moving"] is False
    assert observations[-1]["easing"] is None
    assert receipt["actionReceipt"]["completedAt"] >= 300
    stop_events = [row for row in receipt["events"] if row["type"] == "moveend"]
    assert len(stop_events) == 1
    assert stop_events[0]["moving"] is False
    assert stop_events[0]["time"] <= receipt["actionReceipt"]["completedAt"]
    assert receipt["movingAtReturn"] is False
    assert receipt["movingAfterAnimation"] is False
    assert receipt["exactViewPreserved"] is True
    assert receipt["networkCalls"] == 0
