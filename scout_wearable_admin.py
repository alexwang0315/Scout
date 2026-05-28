from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyPrivacy,
    WearableActivitySummary,
    aggregate_sha256,
    load_wearable_activity_summary,
)
from scout_energy_reserve import (
    COMPANION_CAPSULE_FILENAME,
    ENERGY_BASELINE_FILENAME,
    ENERGY_EXPLANATION_FILENAME,
    write_energy_reserve_artifacts,
)
from scout_wearable_validator import assert_valid_wearable_activity_summary_contract


WEARABLE_ENERGY_EXPORT_FILENAME = "wearable_energy_share_export.json"
WEARABLE_DAILY_ENERGY_OVERVIEW_FILENAME = "daily_energy_overview.json"
WEARABLE_DAILY_HOME_PREVIEW_FILENAME = "daily_home_preview.json"
WEARABLE_DAILY_HOME_PREVIEW_HTML_FILENAME = "daily_home_preview.html"


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


def export_wearable_energy_artifacts(
    *,
    inventory_root: Path,
    explicit_consent: bool,
    output_path: Path | None = None,
    include_reserve_summary: bool = False,
) -> dict[str, Any]:
    if not explicit_consent:
        raise ValueError("explicit consent is required before exporting wearable energy artifacts")
    outputs_dir = inventory_root / "outputs"
    capsule_path = outputs_dir / COMPANION_CAPSULE_FILENAME
    if not capsule_path.exists():
        refresh_energy_reserve_from_inventory(inventory_root=inventory_root)
    capsule = _load_optional_json(capsule_path)
    if not capsule:
        raise FileNotFoundError(f"companion capability capsule not found: {capsule_path}")
    included_artifacts: dict[str, Any] = {
        "companion_capability_capsule": capsule,
    }
    baseline_path = outputs_dir / ENERGY_BASELINE_FILENAME
    if include_reserve_summary and baseline_path.exists():
        baseline = _load_optional_json(baseline_path)
        included_artifacts["energy_reserve_summary"] = {
            "artifact_kind": "scout_energy_reserve_export_summary",
            "source_provider": baseline["source_provider"],
            "source_path": baseline["source_path"],
            "sha256": baseline["sha256"],
            "reference_date": baseline["reference_date"],
            "activity_count": baseline["activity_count"],
            "reserve_band": baseline["reserve_trend"]["current_band"],
            "reserve_score": baseline["reserve_trend"]["reserve_score"],
            "route_family_profiles_shared": False,
            "data_quality": baseline["data_quality"],
            "privacy": baseline["privacy"],
            "boundary": baseline["boundary"],
        }
    export_sha = aggregate_sha256(
        [
            {
                "artifact": key,
                "sha256": value["sha256"],
            }
            for key, value in sorted(included_artifacts.items())
        ]
    )
    privacy = ScoutEnergyPrivacy().model_dump(mode="json")
    boundary = ScoutEnergyBoundary().model_dump(mode="json")
    export_payload = {
        "artifact_kind": "scout_wearable_energy_export_bundle",
        "artifact_version": "wearable_energy_export_bundle.v1",
        "source_provider": capsule["source_provider"],
        "source_path": capsule["source_path"],
        "sha256": export_sha,
        "export_scope": "local_coarse_capsule",
        "included_artifact_kinds": sorted(included_artifacts.keys()),
        "artifacts": included_artifacts,
        "consent": {
            "explicit_local_export": True,
            "remote_share_allowed": False,
            "community_pool_upload_allowed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
            "route_family_names_shared": False,
        },
        "data_quality": capsule["data_quality"],
        "privacy": privacy,
        "boundary": boundary,
    }
    resolved_output_path = output_path or outputs_dir / WEARABLE_ENERGY_EXPORT_FILENAME
    _write_json(resolved_output_path, export_payload)
    return {
        "artifact_kind": "scout_wearable_energy_export_result",
        "persisted": True,
        "source_provider": export_payload["source_provider"],
        "source_path": export_payload["source_path"],
        "sha256": export_payload["sha256"],
        "export_path": str(resolved_output_path),
        "export": export_payload,
        "data_quality": export_payload["data_quality"],
        "privacy": privacy,
        "boundary": boundary,
        "mutation": {
            "export_bundle_written": True,
            "source_file_mutated": False,
            "activity_summaries_deleted": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "remote_upload_performed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def build_daily_energy_overview(
    *,
    inventory_root: Path,
    reference_date: date | None = None,
    write_artifact: bool = True,
) -> dict[str, Any]:
    outputs_dir = inventory_root / "outputs"
    baseline_path = outputs_dir / ENERGY_BASELINE_FILENAME
    explanation_path = outputs_dir / ENERGY_EXPLANATION_FILENAME
    if reference_date is not None or not baseline_path.exists() or not explanation_path.exists():
        refresh_energy_reserve_from_inventory(
            inventory_root=inventory_root,
            reference_date=reference_date,
        )
    baseline = _load_required_json(baseline_path)
    explanation = _load_required_json(explanation_path)
    cue = _daily_soft_cue(baseline["reserve_trend"]["current_band"])
    source_sha = aggregate_sha256(
        [
            baseline["sha256"],
            explanation["sha256"],
            {
                "artifact": "daily_energy_overview",
                "reference_date": baseline["reference_date"],
                "reserve_band": baseline["reserve_trend"]["current_band"],
            },
        ]
    )
    overview = {
        "artifact_kind": "scout_wearable_daily_energy_overview",
        "artifact_version": "wearable_daily_energy_overview.v1",
        "source_provider": baseline["source_provider"],
        "source_path": baseline["source_path"],
        "sha256": source_sha,
        "surface": "daily_home",
        "reference_date": baseline["reference_date"],
        "activity_count": baseline["activity_count"],
        "current_reserve_band": baseline["reserve_trend"]["current_band"],
        "reserve_score": baseline["reserve_trend"]["reserve_score"],
        "trend_vs_baseline": {
            "acute_7_day_load": baseline["acute_7_day_load"],
            "recent_28_day_baseline": baseline["recent_28_day_baseline"],
            "stable_90_day_baseline": baseline["stable_90_day_baseline"],
            "acute_load_ratio": baseline["reserve_trend"]["acute_load_ratio"],
            "acute_load_z": baseline["reserve_trend"]["acute_load_z"],
            "recovery_debt_z": baseline["reserve_trend"]["recovery_debt_z"],
        },
        "recent_load_and_recovery_explanation": [
            explanation["headline"],
            *baseline["reserve_trend"]["explanations"],
        ],
        "next_day_soft_cue": cue,
        "display_language_policy": {
            "medical_language_allowed": False,
            "diagnosis_allowed": False,
            "runtime_safety_truth": False,
            "wording": "advisory trend only",
        },
        "data_quality": baseline["data_quality"],
        "privacy": baseline["privacy"],
        "boundary": baseline["boundary"],
    }
    if write_artifact:
        _write_json(outputs_dir / WEARABLE_DAILY_ENERGY_OVERVIEW_FILENAME, overview)
    return {
        "artifact_kind": "scout_wearable_daily_energy_overview_result",
        "persisted": write_artifact,
        "overview_path": str(outputs_dir / WEARABLE_DAILY_ENERGY_OVERVIEW_FILENAME),
        "source_provider": overview["source_provider"],
        "source_path": overview["source_path"],
        "sha256": overview["sha256"],
        "overview": overview,
        "data_quality": overview["data_quality"],
        "privacy": overview["privacy"],
        "boundary": overview["boundary"],
        "mutation": {
            "daily_energy_overview_written": write_artifact,
            "source_file_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "remote_upload_performed": False,
            "raw_health_payload_shared": False,
        },
    }


def delete_wearable_energy_artifacts(
    *,
    inventory_root: Path,
    include_exports: bool = True,
) -> dict[str, Any]:
    outputs_dir = inventory_root / "outputs"
    filenames = [
        ENERGY_BASELINE_FILENAME,
        ENERGY_EXPLANATION_FILENAME,
        COMPANION_CAPSULE_FILENAME,
        "refresh_result.json",
        WEARABLE_DAILY_ENERGY_OVERVIEW_FILENAME,
        WEARABLE_DAILY_HOME_PREVIEW_FILENAME,
        WEARABLE_DAILY_HOME_PREVIEW_HTML_FILENAME,
        "mobile_energy_companion_handoff.json",
    ]
    if include_exports:
        filenames.append(WEARABLE_ENERGY_EXPORT_FILENAME)
    deleted_paths: list[str] = []
    missing_paths: list[str] = []
    for filename in filenames:
        path = outputs_dir / filename
        if path.exists():
            path.unlink()
            deleted_paths.append(str(path))
        else:
            missing_paths.append(str(path))
    boundary = ScoutEnergyBoundary().model_dump(mode="json")
    return {
        "artifact_kind": "scout_wearable_energy_delete_result",
        "persisted": True,
        "deleted_paths": deleted_paths,
        "missing_paths": missing_paths,
        "activity_summaries_deleted": False,
        "boundary": boundary,
        "mutation": {
            "energy_artifacts_deleted": bool(deleted_paths),
            "activity_summaries_deleted": False,
            "source_file_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "remote_delete_performed": False,
        },
    }


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


def _load_required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"wearable energy artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _daily_soft_cue(reserve_band: str) -> dict[str, Any]:
    cues = {
        "normal": {
            "cue_type": "normal_day",
            "label": "normal pacing",
            "text": "Keep normal pacing and review route conditions as usual.",
        },
        "watch": {
            "cue_type": "easy_day",
            "label": "easier day",
            "text": "Favor an easier day or lower-intensity route plan.",
        },
        "rest_suggested": {
            "cue_type": "rest_or_easy_day",
            "label": "rest or easy day",
            "text": "Plan extra rest or an easier day before harder efforts.",
        },
        "stop_and_check": {
            "cue_type": "manual_check_day",
            "label": "manual check",
            "text": "Pause hard efforts and do a manual condition check before planning more load.",
        },
    }
    cue = cues.get(reserve_band, cues["watch"])
    return {
        **cue,
        "advisory_only": True,
        "medical_language": False,
        "phase1_runtime_safety_truth": False,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
