from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.navigation_terrain_expert_eval import run_eval


ROOT = Path(__file__).parents[1]
TOOL = ROOT / "tools" / "navigation_terrain_expert_eval.py"


def test_expert_navigation_eval_passes_all_candidate_only_cases() -> None:
    result = run_eval()

    assert result["status"] == "pass"
    assert result["passed_case_count"] == result["case_count"] == 4
    assert all(case["passed"] is True for case in result["cases"])
    validation_case = next(
        case
        for case in result["cases"]
        if case["case_id"] == "missing-reference-fails-closed"
    )
    assert validation_case["checks"]["validation_state"] == (
        "blocked_pending_reference"
    )
    assert validation_case["checks"]["event_source_mode"] == "prohibited"
    assert result["boundary"]["candidate_only"] is True
    assert result["boundary"]["runtime_safety_truth"] is False


def test_expert_navigation_eval_cli_emits_json() -> None:
    completed = subprocess.run(
        [sys.executable, str(TOOL)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["status"] == "pass"
    assert {case["case_id"] for case in result["cases"]} == {
        "expert-semantic-annotation",
        "dem-hierarchy-topology",
        "missing-reference-fails-closed",
        "ordered-route-terrain-events",
    }
