from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    ScoutEnergyReserveBaseline,
    aggregate_sha256,
    sha256_file,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS
from voice_cue_models import VoiceCue, VoiceCueRepeatPolicy


FieldCueBand = Literal["normal_advisory", "slow_down", "rest_suggested", "manual_check"]
MovementState = Literal["moving", "stopped", "resting", "unknown"]


class WearableFieldObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_field_observation"
    artifact_version: str = "wearable_field_observation.v1"
    observation_id: str
    source_provider: str
    source_path: str
    sha256: str
    offset_s: int = Field(ge=0)
    route_segment_ref: str | None = None
    movement_state: MovementState = "unknown"
    heart_rate_bpm: int | None = Field(default=None, ge=1)
    expected_baseline_bpm: int | None = Field(default=None, ge=1)
    reserve_band_hint: str | None = None
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_field_observation_boundary(self) -> "WearableFieldObservation":
        if self.privacy.raw_health_payload_shared:
            raise ValueError("field observation must not share raw health payload")
        if self.privacy.raw_samples_embedded:
            raise ValueError("field observation must not embed raw samples")
        if self.privacy.raw_track_shared:
            raise ValueError("field observation must not share raw tracks")
        if self.privacy.exact_timestamps_shared:
            raise ValueError("field observation must not share exact timestamps")
        if self.privacy.home_work_trace_shared:
            raise ValueError("field observation must not share home/work traces")
        if self.boundary.medical_diagnosis:
            raise ValueError("field observation cannot be medical diagnosis")
        if self.boundary.phase1_runtime_safety_truth:
            raise ValueError("field observation cannot be Phase 1 runtime safety truth")
        if self.boundary.safety_api_calls_allowed:
            raise ValueError("field observation cannot allow safety API calls")
        return self


class ScoutEnergyFieldAdvisoryCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_energy_field_advisory_cue"
    artifact_version: str = "energy_field_advisory_cue.v1"
    source_provider: str
    source_path: str
    sha256: str
    observation_id: str
    route_segment_ref: str | None = None
    cue_band: FieldCueBand
    reserve_band: str
    heart_rate_drift_ratio: float | None = None
    message_en: str
    message_zh: str
    advisory_actions: list[str]
    reasons: list[str]
    voice_cue: dict[str, Any]
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def load_wearable_field_observation(
    path: Path,
    *,
    root: Path | None = None,
) -> WearableFieldObservation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        raise ValueError(f"forbidden raw field observation fields present: {', '.join(forbidden_paths)}")
    payload["source_path"] = _relpath(path, root or Path.cwd())
    payload["sha256"] = sha256_file(path)
    return WearableFieldObservation.model_validate(payload)


def build_energy_field_advisory_cue(
    observation: WearableFieldObservation,
    baseline: ScoutEnergyReserveBaseline | dict[str, Any],
) -> ScoutEnergyFieldAdvisoryCue:
    baseline_payload = baseline.model_dump(mode="json") if isinstance(baseline, ScoutEnergyReserveBaseline) else baseline
    reserve_band = str(observation.reserve_band_hint or baseline_payload["reserve_trend"]["current_band"])
    drift_ratio = _heart_rate_drift_ratio(observation)
    cue_band = _cue_band(reserve_band=reserve_band, heart_rate_drift_ratio=drift_ratio)
    message_en, message_zh, actions = _cue_copy(cue_band)
    reasons = [
        "baseline-relative advisory trend only",
        f"reserve band context is {reserve_band}",
    ]
    if drift_ratio is not None:
        reasons.append(f"heart-rate drift ratio is {drift_ratio:.3f} versus expected baseline")
    if observation.movement_state in {"stopped", "resting"}:
        reasons.append(f"movement state is {observation.movement_state}; cue should not infer medical cause")
    source_sha = aggregate_sha256(
        [
            observation.sha256,
            baseline_payload["sha256"],
            {
                "cue_band": cue_band,
                "reserve_band": reserve_band,
                "heart_rate_drift_ratio": drift_ratio,
            },
        ]
    )
    cue = ScoutEnergyFieldAdvisoryCue(
        source_provider=observation.source_provider,
        source_path=f"{observation.source_path}+{baseline_payload['source_path']}",
        sha256=source_sha,
        observation_id=observation.observation_id,
        route_segment_ref=observation.route_segment_ref,
        cue_band=cue_band,
        reserve_band=reserve_band,
        heart_rate_drift_ratio=drift_ratio,
        message_en=message_en,
        message_zh=message_zh,
        advisory_actions=actions,
        reasons=reasons,
        voice_cue=voice_cue_from_energy_field_advisory(
            cue_band=cue_band,
            observation_id=observation.observation_id,
            route_segment_ref=observation.route_segment_ref,
            message_zh=message_zh,
        ).model_dump(mode="json"),
        data_quality=_combine_data_quality(observation.data_quality, baseline_payload["data_quality"]),
    )
    return cue


def write_energy_field_advisory_cue(
    observation_path: Path,
    *,
    baseline_path: Path,
    output_path: Path,
    root: Path | None = None,
) -> ScoutEnergyFieldAdvisoryCue:
    observation = load_wearable_field_observation(observation_path, root=root)
    baseline = ScoutEnergyReserveBaseline.model_validate(
        json.loads(baseline_path.read_text(encoding="utf-8"))
    )
    cue = build_energy_field_advisory_cue(observation, baseline)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(cue.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return cue


def voice_cue_from_energy_field_advisory(
    *,
    cue_band: FieldCueBand,
    observation_id: str,
    route_segment_ref: str | None,
    message_zh: str,
) -> VoiceCue:
    priority = {
        "normal_advisory": "info",
        "slow_down": "caution",
        "rest_suggested": "caution",
        "manual_check": "warning",
    }[cue_band]
    token = _safe_token(route_segment_ref or observation_id)
    return VoiceCue(
        cue_id=f"voice_cue.energy_field.{token}",
        priority=priority,
        category="body",
        text_zh=message_zh,
        source_event_refs=[observation_id],
        source_kind="deterministic_fact",
        confidence=0.72 if cue_band in {"rest_suggested", "manual_check"} else 0.58,
        repeat_policy=VoiceCueRepeatPolicy(
            dedupe_key=f"energy_field:{cue_band}:{route_segment_ref or observation_id}",
            min_interval_seconds=900,
            max_repeats=1,
        ),
        require_ack=cue_band == "manual_check",
        spoken_allowed=True,
    )


def _heart_rate_drift_ratio(observation: WearableFieldObservation) -> float | None:
    if not observation.heart_rate_bpm or not observation.expected_baseline_bpm:
        return None
    return round((observation.heart_rate_bpm - observation.expected_baseline_bpm) / observation.expected_baseline_bpm, 3)


def _cue_band(
    *,
    reserve_band: str,
    heart_rate_drift_ratio: float | None,
) -> FieldCueBand:
    drift = heart_rate_drift_ratio or 0.0
    if reserve_band == "stop_and_check" or drift >= 0.18:
        return "manual_check"
    if reserve_band == "rest_suggested" or drift >= 0.12:
        return "rest_suggested"
    if reserve_band == "watch" or drift >= 0.08:
        return "slow_down"
    return "normal_advisory"


def _cue_copy(cue_band: FieldCueBand) -> tuple[str, str, list[str]]:
    if cue_band == "manual_check":
        return (
            "Your reserve trend is well below the expected range for this effort. Stop and check how you feel.",
            "體能儲備提示：目前低於這段努力的預期範圍，請停下來做自我狀態確認。",
            ["stop and do a manual condition check", "keep normal Scout safety/SOS flow separate"],
        )
    if cue_band == "rest_suggested":
        return (
            "You are below your usual reserve trend for this effort. Consider a short rest.",
            "體能儲備提示：目前低於這段努力的平常趨勢，建議短暫休息。",
            ["take a short rest", "resume with easier pacing if the user feels ready"],
        )
    if cue_band == "slow_down":
        return (
            "Heart-rate load is higher than your baseline on similar effort. Slow down and check how you feel.",
            "體能儲備提示：心率負荷高於相近努力的個人基線，請放慢並確認感受。",
            ["slow down", "keep rest options visible"],
        )
    return (
        "Reserve trend is within the expected advisory range for this effort.",
        "體能儲備提示：目前仍在這段努力的建議觀察範圍內。",
        ["continue normal pacing review"],
    )


def _combine_data_quality(
    observation_quality: ScoutEnergyDataQuality,
    baseline_quality: dict[str, Any],
) -> ScoutEnergyDataQuality:
    order = {"low": 0, "medium": 1, "high": 2}
    limitations = sorted(
        {
            *observation_quality.limitations,
            *baseline_quality.get("limitations", []),
            "field cue is deterministic advisory evidence only",
        }
    )
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min(
            observation_quality.heart_rate_confidence,
            baseline_quality.get("heart_rate_confidence", "low"),
            key=order.get,
        ),
        gps_confidence=min(
            observation_quality.gps_confidence,
            baseline_quality.get("gps_confidence", "low"),
            key=order.get,
        ),
        missing_hr_seconds=observation_quality.missing_hr_seconds + baseline_quality.get("missing_hr_seconds", 0),
        provider_value_confidence=min(
            observation_quality.provider_value_confidence,
            baseline_quality.get("provider_value_confidence", "low"),
            key=order.get,
        ),
        limitations=limitations,
    )


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _safe_token(value: str) -> str:
    return "".join(
        char if char.isascii() and (char.isalnum() or char in "_.:-") else "_"
        for char in value
    ).strip("_.:-")[:80] or "observation"


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)
