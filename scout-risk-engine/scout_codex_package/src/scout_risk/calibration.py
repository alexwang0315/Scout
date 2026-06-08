from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_calibration_report_placeholder(
    *,
    route_profile_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "artifact_kind": "scout_risk_calibration_report_placeholder",
        "status": "placeholder_only",
        "route_profile_ref": route_profile_ref,
        "metrics": {
            "cp_hit_rate": None,
            "top_k_recall": None,
        },
        "boundary": {
            "ml_training_performed": False,
            "hardware_driver_used": False,
            "runtime_safety_truth": False,
        },
        "notes": [
            "Calibration is intentionally deferred until reviewed field evidence exists.",
            "This placeholder records the future report shape without training a model.",
        ],
    }


def write_calibration_report_placeholder(
    path: str | Path,
    *,
    route_profile_ref: str | None = None,
) -> dict[str, Any]:
    payload = build_calibration_report_placeholder(route_profile_ref=route_profile_ref)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload

