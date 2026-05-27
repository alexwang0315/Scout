from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
)


POST_ANALYSIS_ENERGY_FEEDBACK_FILENAME = "post_analysis_energy_reserve_feedback.json"
POST_ANALYSIS_ENERGY_FEEDBACK_REF = f"outputs/{POST_ANALYSIS_ENERGY_FEEDBACK_FILENAME}"


class PostAnalysisEnergyFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "post_analysis_energy_reserve_feedback"
    artifact_version: str = "post_analysis_energy_reserve_feedback.v1"
    case_id: str
    source_provider: str
    source_path: str
    sha256: str
    pretrip_projection_source_path: str
    capability_timeline_source_path: str
    predicted_target_duration_minutes: int = Field(ge=0)
    actual_elapsed_duration_minutes: int = Field(ge=0)
    actual_moving_duration_minutes: int = Field(ge=0)
    actual_vs_projected_elapsed_delta_minutes: int
    predicted_depletion_checkpoint_name: str | None = None
    actual_rest_time_minutes: int = Field(ge=0)
    feedback_notes: list[str] = Field(default_factory=list)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def build_post_analysis_energy_feedback(
    *,
    pretrip_projection: dict[str, Any],
    capability_timeline: dict[str, Any],
    pretrip_projection_source_path: str,
    capability_timeline_source_path: str,
) -> PostAnalysisEnergyFeedback:
    projected_minutes = _projected_target_duration_minutes(pretrip_projection)
    summary = capability_timeline["summary"]
    actual_elapsed_minutes = round((summary.get("elapsed_time_s") or 0) / 60)
    actual_moving_minutes = round((summary.get("moving_time_s") or 0) / 60)
    actual_rest_minutes = round((summary.get("rest_time_s") or 0) / 60)
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence=_timeline_confidence(capability_timeline),
        missing_hr_seconds=0,
        provider_value_confidence="low",
        limitations=[
            "feedback compares coarse pretrip projection against post-analysis timeline summary",
            "exact timestamps and raw GPX are not embedded",
        ],
    )
    return PostAnalysisEnergyFeedback(
        case_id=capability_timeline["case_id"],
        source_provider="pretrip_energy_projection+post_analysis_capability_timeline",
        source_path=f"{pretrip_projection_source_path}+{capability_timeline_source_path}",
        sha256=aggregate_sha256(
            [
                pretrip_projection.get("sha256", ""),
                capability_timeline.get("source_track", {}).get("sha256", ""),
                capability_timeline.get("summary", {}),
            ]
        ),
        pretrip_projection_source_path=pretrip_projection_source_path,
        capability_timeline_source_path=capability_timeline_source_path,
        predicted_target_duration_minutes=projected_minutes,
        actual_elapsed_duration_minutes=actual_elapsed_minutes,
        actual_moving_duration_minutes=actual_moving_minutes,
        actual_vs_projected_elapsed_delta_minutes=actual_elapsed_minutes - projected_minutes,
        predicted_depletion_checkpoint_name=pretrip_projection.get("possible_depletion_checkpoint_name"),
        actual_rest_time_minutes=actual_rest_minutes,
        feedback_notes=[
            "Use this as baseline calibration evidence after return.",
            "Do not rewrite pretrip ETA, departure approval, MissionGraph, or Phase 1 runtime state.",
        ],
        data_quality=data_quality,
    )


def write_post_analysis_energy_feedback(
    *,
    pretrip_projection_path: Path,
    capability_timeline_path: Path,
    output_path: Path,
    root: Path | None = None,
) -> PostAnalysisEnergyFeedback:
    projection = json.loads(pretrip_projection_path.read_text(encoding="utf-8"))
    timeline = json.loads(capability_timeline_path.read_text(encoding="utf-8"))
    rel_root = root or output_path.parent
    feedback = build_post_analysis_energy_feedback(
        pretrip_projection=projection,
        capability_timeline=timeline,
        pretrip_projection_source_path=_relpath(pretrip_projection_path, rel_root),
        capability_timeline_source_path=_relpath(capability_timeline_path, rel_root),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(feedback.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return feedback


def _projected_target_duration_minutes(projection: dict[str, Any]) -> int:
    checkpoints = projection.get("checkpoints", [])
    if not checkpoints:
        return 0
    return int(checkpoints[-1].get("energy_adjusted_cumulative_duration_minutes", 0))


def _timeline_confidence(timeline: dict[str, Any]):
    values = [edge.get("confidence", "low") for edge in timeline.get("edges", [])]
    if not values:
        return "low"
    order = {"low": 0, "medium": 1, "high": 2}
    return min(values, key=lambda value: order.get(value, 0))


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
