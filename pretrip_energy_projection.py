from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pretrip_eta_plan import PreTripEtaPlan
from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    ScoutEnergyReserveBaseline,
    aggregate_sha256,
    sha256_file,
)


DEFAULT_PRETRIP_ENERGY_PROJECTION_REF = "outputs/pretrip_energy_reserve_projection.json"


class PreTripEnergyCheckpointProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_name: str
    original_eta: str
    energy_adjusted_eta: str
    original_cumulative_duration_minutes: int = Field(ge=0)
    energy_adjusted_cumulative_duration_minutes: int = Field(ge=0)
    segment_duration_minutes: int = Field(ge=0)
    energy_adjusted_segment_duration_minutes: int = Field(ge=0)
    reserve_after_checkpoint: int = Field(ge=0, le=100)
    reserve_band_after_checkpoint: Literal["normal", "watch", "rest_suggested", "depletion_risk"]
    possible_depletion_checkpoint: bool = False
    advisory_note: str
    source_candidate_id: str


class PreTripEnergyReserveProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "pretrip_energy_reserve_projection"
    artifact_version: str = "pretrip_energy_reserve_projection.v1"
    project_id: str
    source_provider: str
    source_path: str
    sha256: str
    eta_plan_source_path: str
    energy_baseline_source_path: str
    reserve_start_score: int = Field(ge=0, le=100)
    route_energy_multiplier: float
    projected_target_eta: str | None = None
    possible_depletion_checkpoint_name: str | None = None
    checkpoints: list[PreTripEnergyCheckpointProjection] = Field(default_factory=list)
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)
    notes: list[str] = Field(default_factory=list)


def build_pretrip_energy_reserve_projection(
    eta_plan: PreTripEtaPlan | dict[str, Any],
    energy_baseline: ScoutEnergyReserveBaseline | dict[str, Any],
    *,
    eta_plan_source_path: str = "pretrip_eta_plan",
    energy_baseline_source_path: str = "scout_energy_reserve_baseline",
) -> PreTripEnergyReserveProjection:
    eta = eta_plan if isinstance(eta_plan, PreTripEtaPlan) else PreTripEtaPlan.model_validate(eta_plan)
    baseline = (
        energy_baseline
        if isinstance(energy_baseline, ScoutEnergyReserveBaseline)
        else ScoutEnergyReserveBaseline.model_validate(energy_baseline)
    )
    if not eta.estimates:
        raise ValueError("energy projection requires at least one ETA estimate")

    multiplier = _route_energy_multiplier(baseline)
    start_score = baseline.reserve_trend.reserve_score
    current_time = datetime.fromisoformat(eta.assumption.planned_start_time)
    adjusted_cumulative = 0
    reserve = float(start_score)
    checkpoints: list[PreTripEnergyCheckpointProjection] = []

    for estimate in eta.estimates:
        adjusted_segment = max(1, round(estimate.segment_duration_minutes * multiplier))
        adjusted_cumulative += adjusted_segment
        current_time += timedelta(minutes=adjusted_segment)
        reserve -= _segment_reserve_cost(estimate.segment_duration_minutes, multiplier)
        reserve_score = max(0, min(100, round(reserve)))
        reserve_band = _reserve_band_after_checkpoint(reserve_score)
        checkpoints.append(
            PreTripEnergyCheckpointProjection(
                checkpoint_name=estimate.to_node_name,
                original_eta=estimate.eta,
                energy_adjusted_eta=current_time.isoformat(),
                original_cumulative_duration_minutes=estimate.cumulative_duration_minutes,
                energy_adjusted_cumulative_duration_minutes=adjusted_cumulative,
                segment_duration_minutes=estimate.segment_duration_minutes,
                energy_adjusted_segment_duration_minutes=adjusted_segment,
                reserve_after_checkpoint=reserve_score,
                reserve_band_after_checkpoint=reserve_band,
                possible_depletion_checkpoint=reserve_score <= 15,
                advisory_note=_advisory_note(reserve_band),
                source_candidate_id=estimate.source_candidate_id,
            )
        )

    depletion = next((item for item in checkpoints if item.possible_depletion_checkpoint), None)
    projected_target = checkpoints[-1].energy_adjusted_eta if checkpoints else None
    return PreTripEnergyReserveProjection(
        project_id=eta.project_id,
        source_provider=baseline.source_provider,
        source_path=f"{eta_plan_source_path}+{energy_baseline_source_path}",
        sha256=aggregate_sha256(
            [
                eta.model_dump(mode="json"),
                baseline.sha256,
                eta_plan_source_path,
                energy_baseline_source_path,
            ]
        ),
        eta_plan_source_path=eta_plan_source_path,
        energy_baseline_source_path=energy_baseline_source_path,
        reserve_start_score=start_score,
        route_energy_multiplier=multiplier,
        projected_target_eta=projected_target,
        possible_depletion_checkpoint_name=depletion.checkpoint_name if depletion else None,
        checkpoints=checkpoints,
        data_quality=baseline.data_quality,
        notes=[
            "Energy projection adjusts planning ETA as advisory context only.",
            "Possible depletion checkpoint is a planning review cue, not a safety state.",
            "No Phase 1 runtime state, MissionGraph progress, or departure approval is changed.",
        ],
    )


def write_pretrip_energy_reserve_projection(
    *,
    eta_plan_path: Path,
    energy_baseline_path: Path,
    output_path: Path,
    project_root: Path | None = None,
) -> PreTripEnergyReserveProjection:
    eta_payload = json.loads(eta_plan_path.read_text(encoding="utf-8"))
    baseline_payload = json.loads(energy_baseline_path.read_text(encoding="utf-8"))
    projection = build_pretrip_energy_reserve_projection(
        eta_payload,
        baseline_payload,
        eta_plan_source_path=_relpath(eta_plan_path, project_root or eta_plan_path.parent),
        energy_baseline_source_path=_relpath(energy_baseline_path, project_root or energy_baseline_path.parent),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(projection.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return projection


def load_pretrip_energy_reserve_projection(path: Path | str) -> PreTripEnergyReserveProjection:
    return PreTripEnergyReserveProjection.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def _route_energy_multiplier(baseline: ScoutEnergyReserveBaseline) -> float:
    band_penalty = {
        "normal": 1.0,
        "watch": 1.08,
        "rest_suggested": 1.18,
        "stop_and_check": 1.35,
    }[baseline.reserve_trend.current_band]
    score_penalty = max(0.0, (50 - baseline.reserve_trend.reserve_score) / 100.0)
    load_penalty = max(0.0, baseline.reserve_trend.acute_load_ratio - 1.0) * 0.12
    return round(band_penalty + score_penalty + load_penalty, 3)


def _segment_reserve_cost(segment_duration_minutes: int, multiplier: float) -> float:
    return (segment_duration_minutes / 60.0) * 9.0 * multiplier


def _reserve_band_after_checkpoint(score: int):
    if score <= 15:
        return "depletion_risk"
    if score <= 30:
        return "rest_suggested"
    if score <= 45:
        return "watch"
    return "normal"


def _advisory_note(band: str) -> str:
    if band == "depletion_risk":
        return "Planning cue: add rest/turnaround review before this checkpoint."
    if band == "rest_suggested":
        return "Planning cue: schedule an extra rest buffer before continuing."
    if band == "watch":
        return "Planning cue: pace conservatively and keep retreat options visible."
    return "Planning cue: reserve remains within advisory range."


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
