from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scout_energy_models import (
    ScoutEnergyBoundary,
    WearableActivitySummary,
    load_wearable_activity_summary,
)
from scout_energy_reserve import write_energy_reserve_artifacts
from scout_wearable_validator import assert_valid_wearable_activity_summary_contract


class WearableInventorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_inventory"
    inventory_root: str
    activity_count: int
    activities: list[dict[str, Any]] = Field(default_factory=list)
    latest_refresh: dict[str, Any] | None = None
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def wearable_inventory_root(data_root: Path) -> Path:
    return data_root.expanduser() / "admin" / "wearables"


def list_wearable_inventory(*, inventory_root: Path) -> WearableInventorySummary:
    activities = load_inventory_activities(inventory_root=inventory_root)
    latest_refresh = _load_optional_json(inventory_root / "outputs" / "refresh_result.json")
    return WearableInventorySummary(
        inventory_root=str(inventory_root),
        activity_count=len(activities),
        activities=[
            {
                "activity_id": activity.activity_id,
                "source_provider": activity.source_provider,
                "source_path": activity.source_path,
                "sha256": activity.sha256,
                "activity_type": activity.activity_type,
                "activity_date": activity.activity_date.isoformat(),
                "duration_s": activity.duration_s,
                "moving_time_s": activity.moving_time_s,
                "heart_rate_confidence": activity.data_quality.heart_rate_confidence,
                "missing_hr_seconds": activity.data_quality.missing_hr_seconds,
                "medical_diagnosis": activity.boundary.medical_diagnosis,
                "phase1_runtime_safety_truth": activity.boundary.phase1_runtime_safety_truth,
            }
            for activity in activities
        ],
        latest_refresh=latest_refresh,
    )


def import_wearable_activity_log(
    *,
    source_path: Path,
    inventory_root: Path,
    source_root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    validation = assert_valid_wearable_activity_summary_contract(
        source_path,
        root=source_root or Path.cwd(),
    )
    activity = load_wearable_activity_summary(source_path, root=source_root or Path.cwd())
    activities_dir = inventory_root / "activities"
    activities_dir.mkdir(parents=True, exist_ok=True)
    destination = activities_dir / f"{_activity_slug(activity.activity_id)}.json"
    if destination.exists() and not overwrite:
        raise FileExistsError(f"wearable activity already imported: {activity.activity_id}")
    _write_json(destination, activity.model_dump(mode="json"))
    return {
        "artifact_kind": "scout_wearable_import_result",
        "persisted": True,
        "activity_id": activity.activity_id,
        "source_provider": activity.source_provider,
        "source_path": activity.source_path,
        "sha256": activity.sha256,
        "validation": validation.model_dump(mode="json"),
        "stored_path": str(destination),
        "boundary": activity.boundary.model_dump(mode="json"),
        "mutation": {
            "inventory_file_written": True,
            "source_file_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
        },
    }


def delete_wearable_activity_log(*, activity_id: str, inventory_root: Path) -> dict[str, Any]:
    for path in sorted((inventory_root / "activities").glob("*.json")):
        activity = _load_inventory_activity(path)
        if activity.activity_id == activity_id:
            path.unlink()
            return {
                "artifact_kind": "scout_wearable_delete_result",
                "persisted": True,
                "activity_id": activity_id,
                "deleted_path": str(path),
                "boundary": activity.boundary.model_dump(mode="json"),
                "mutation": {
                    "inventory_file_deleted": True,
                    "source_file_mutated": False,
                    "phase1_runtime_mutated": False,
                    "safety_api_called": False,
                },
            }
    raise FileNotFoundError(f"wearable activity not found: {activity_id}")


def refresh_energy_reserve_from_inventory(
    *,
    inventory_root: Path,
    reference_date: date | None = None,
) -> dict[str, Any]:
    activities = load_inventory_activities(inventory_root=inventory_root)
    if not activities:
        raise ValueError("wearable inventory has no activity summaries")
    outputs = write_energy_reserve_artifacts(
        activities,
        output_dir=inventory_root / "outputs",
        reference_date=reference_date,
    )
    result = {
        "artifact_kind": "scout_wearable_energy_refresh_result",
        "persisted": True,
        "activity_count": len(activities),
        "baseline_path": outputs["baseline_path"],
        "explanation_path": outputs["explanation_path"],
        "companion_capsule_path": outputs["companion_capsule_path"],
        "reserve_band": outputs["baseline"]["reserve_trend"]["current_band"],
        "reserve_score": outputs["baseline"]["reserve_trend"]["reserve_score"],
        "source_provider": outputs["baseline"]["source_provider"],
        "source_path": outputs["baseline"]["source_path"],
        "sha256": outputs["baseline"]["sha256"],
        "data_quality": outputs["baseline"]["data_quality"],
        "privacy": outputs["baseline"]["privacy"],
        "boundary": outputs["boundary"],
        "mutation": {
            "energy_artifacts_written": True,
            "source_file_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_health_payload_shared": False,
        },
    }
    _write_json(inventory_root / "outputs" / "refresh_result.json", result)
    return result


def load_inventory_activities(*, inventory_root: Path) -> list[WearableActivitySummary]:
    activities_dir = inventory_root / "activities"
    if not activities_dir.exists():
        return []
    return [_load_inventory_activity(path) for path in sorted(activities_dir.glob("*.json"))]


def _load_inventory_activity(path: Path) -> WearableActivitySummary:
    return WearableActivitySummary.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _activity_slug(activity_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", activity_id).strip("._")
    return slug or "activity"


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
