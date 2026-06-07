from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scout_energy_field_cue import (
    build_energy_field_advisory_cue,
    load_wearable_field_observation,
)
from scout_energy_models import ScoutEnergyReserveBaseline


ENERGY_VITALS_TOOL_ID = "scout.ai.energy_vitals.assess.v0"
ENERGY_VITALS_OUTPUT_KIND = "scout_ai_energy_vitals_tool_output"

ENERGY_VITALS_REQUIRED_FIELDS = (
    "subject_id",
    "observed_at",
    "heart_rate_bpm",
    "hrv_ms",
    "body_battery_or_provider_energy",
    "pace_mps",
    "cadence",
    "activity_load",
    "baseline_window_days",
    "reserve_score",
    "reserve_band",
    "heart_rate_drift_ratio",
    "privacy_scope",
    "source_provider",
)

ENERGY_VITALS_OPTIONAL_FIELDS = (
    "heart_rate_trend",
    "hrv_trend",
    "record_gap_count",
    "staleness_s",
    "baseline_path",
    "observation_path",
)


def assess_scout_energy_vitals(
    project_root: Path | str,
    *,
    query: str = "",
    subject_id: str | None = None,
    observed_at: str | None = None,
    heart_rate_bpm: float | int | str | None = None,
    hrv_ms: float | int | str | None = None,
    body_battery_or_provider_energy: float | int | str | None = None,
    pace_mps: float | int | str | None = None,
    cadence: float | int | str | None = None,
    activity_load: float | int | str | None = None,
    baseline_window_days: int | str | None = None,
    reserve_score: int | str | None = None,
    reserve_band: str | None = None,
    heart_rate_drift_ratio: float | int | str | None = None,
    heart_rate_trend: dict[str, Any] | None = None,
    hrv_trend: dict[str, Any] | None = None,
    record_gap_count: int | str | None = None,
    staleness_s: float | int | str | None = None,
    privacy_scope: str | None = None,
    source_provider: str | None = None,
    baseline_path: str | None = None,
    observation_path: str | None = None,
) -> dict[str, Any]:
    """Assess normalized wearable/vitals evidence without medical diagnosis."""

    root = Path(project_root)
    project = _load_project(root)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    baseline, resolved_baseline_path = _load_baseline(root, baseline_path)
    observation, resolved_observation_path = _load_observation(root, observation_path)
    direct = {
        "subject_id": subject_id,
        "observed_at": observed_at,
        "heart_rate_bpm": _float_or_none(heart_rate_bpm),
        "hrv_ms": _float_or_none(hrv_ms),
        "body_battery_or_provider_energy": _float_or_none(
            body_battery_or_provider_energy
        ),
        "pace_mps": _float_or_none(pace_mps),
        "cadence": _float_or_none(cadence),
        "activity_load": _float_or_none(activity_load),
        "baseline_window_days": _int_or_none(baseline_window_days),
        "reserve_score": _int_or_none(reserve_score),
        "reserve_band": reserve_band,
        "heart_rate_drift_ratio": _float_or_none(heart_rate_drift_ratio),
        "heart_rate_trend": heart_rate_trend if isinstance(heart_rate_trend, dict) else None,
        "hrv_trend": hrv_trend if isinstance(hrv_trend, dict) else None,
        "record_gap_count": _int_or_none(record_gap_count),
        "staleness_s": _float_or_none(staleness_s),
        "privacy_scope": privacy_scope,
        "source_provider": source_provider,
    }
    evidence = _merged_evidence(
        direct,
        baseline=baseline,
        observation=observation,
    )
    missing_fields = [
        field for field in ENERGY_VITALS_REQUIRED_FIELDS if _is_missing(evidence[field])
    ]
    cue = _energy_cue(
        baseline=baseline,
        observation=observation,
        evidence=evidence,
    )
    answerability = (
        "energy_vitals_advisory_available"
        if _has_advisory_core(evidence)
        else "energy_vitals_missing_required_fields"
    )
    return {
        "tool_id": ENERGY_VITALS_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_energy_vitals",
        "answerability": answerability,
        "missing_fields": missing_fields,
        "provided_fields": {
            field: value
            for field, value in evidence.items()
            if not _is_missing(value)
        },
        "advisory": cue,
        "time_window": _time_window_evidence(evidence),
        "privacy": {
            "privacy_scope": evidence.get("privacy_scope") or "private_vitals",
            "raw_health_payload_shared": False,
            "raw_samples_embedded": False,
            "exact_timestamps_shared": False,
            "shareable_by_default": False,
        },
        "forbidden_interpretations": [
            "medical diagnosis",
            "disease inference",
            "dehydration inference",
            "arrhythmia inference",
            "overtraining inference",
            "Phase 1 runtime safety truth",
        ],
        "results": [
            {
                "label": "energy/vitals assessor",
                "snippet": (
                    f"answerability={answerability}; "
                    f"reserve_band={evidence.get('reserve_band') or 'unknown'}; "
                    "missing_fields="
                    + ",".join(missing_fields)
                    + "; advisory only, not medical diagnosis, not runtime safety truth"
                ),
            }
        ],
        "source_report": _source_report(
            baseline_path=resolved_baseline_path,
            observation_path=resolved_observation_path,
            baseline_loaded=baseline is not None,
            observation_loaded=observation is not None,
        ),
        "boundary": _closed_boundary(),
    }


def _merged_evidence(
    direct: dict[str, Any],
    *,
    baseline: ScoutEnergyReserveBaseline | None,
    observation: Any | None,
) -> dict[str, Any]:
    baseline_payload = baseline.model_dump(mode="json") if baseline is not None else {}
    reserve_trend = baseline_payload.get("reserve_trend")
    reserve_trend = reserve_trend if isinstance(reserve_trend, dict) else {}
    stable = baseline_payload.get("stable_90_day_baseline")
    stable = stable if isinstance(stable, dict) else {}

    expected_baseline_bpm = getattr(observation, "expected_baseline_bpm", None)
    observation_hr = getattr(observation, "heart_rate_bpm", None)
    drift_ratio = direct.get("heart_rate_drift_ratio")
    if _is_missing(drift_ratio):
        drift_ratio = _heart_rate_drift_ratio(observation_hr, expected_baseline_bpm)

    return {
        "subject_id": _first_present(
            direct.get("subject_id"),
            baseline_payload.get("user_profile_ref"),
        ),
        "observed_at": direct.get("observed_at"),
        "heart_rate_bpm": _first_present(direct.get("heart_rate_bpm"), observation_hr),
        "hrv_ms": direct.get("hrv_ms"),
        "body_battery_or_provider_energy": direct.get(
            "body_battery_or_provider_energy"
        ),
        "pace_mps": direct.get("pace_mps"),
        "cadence": direct.get("cadence"),
        "activity_load": _first_present(
            direct.get("activity_load"),
            _nested_number(baseline_payload, "acute_7_day_load", "load_sum"),
        ),
        "baseline_window_days": _first_present(
            direct.get("baseline_window_days"),
            stable.get("window_days"),
        ),
        "reserve_score": _first_present(
            direct.get("reserve_score"),
            reserve_trend.get("reserve_score"),
        ),
        "reserve_band": _first_present(
            direct.get("reserve_band"),
            getattr(observation, "reserve_band_hint", None),
            reserve_trend.get("current_band"),
        ),
        "heart_rate_drift_ratio": drift_ratio,
        "heart_rate_trend": direct.get("heart_rate_trend"),
        "hrv_trend": direct.get("hrv_trend"),
        "record_gap_count": direct.get("record_gap_count"),
        "staleness_s": direct.get("staleness_s"),
        "privacy_scope": _first_present(direct.get("privacy_scope"), "private_vitals"),
        "source_provider": _first_present(
            direct.get("source_provider"),
            getattr(observation, "source_provider", None),
            baseline_payload.get("source_provider"),
        ),
    }


def _energy_cue(
    *,
    baseline: ScoutEnergyReserveBaseline | None,
    observation: Any | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if baseline is not None and observation is not None:
        cue = build_energy_field_advisory_cue(observation, baseline)
        return {
            "cue_band": cue.cue_band,
            "reserve_band": cue.reserve_band,
            "heart_rate_drift_ratio": cue.heart_rate_drift_ratio,
            "message_zh": cue.message_zh,
            "advisory_actions": list(cue.advisory_actions),
            "reasons": list(cue.reasons),
        }
    reserve_band = str(evidence.get("reserve_band") or "unknown")
    drift_ratio = _float_or_none(evidence.get("heart_rate_drift_ratio"))
    cue_band = _cue_band(reserve_band=reserve_band, heart_rate_drift_ratio=drift_ratio)
    return {
        "cue_band": cue_band,
        "reserve_band": reserve_band,
        "heart_rate_drift_ratio": drift_ratio,
        "message_zh": _message_zh(cue_band),
        "advisory_actions": _advisory_actions(cue_band),
        "reasons": _advisory_reasons(evidence, reserve_band=reserve_band),
    }


def _has_advisory_core(evidence: dict[str, Any]) -> bool:
    return not _is_missing(evidence.get("heart_rate_bpm")) and not _is_missing(
        evidence.get("reserve_band")
    )


def _time_window_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "heart_rate_trend": evidence.get("heart_rate_trend"),
        "hrv_trend": evidence.get("hrv_trend"),
        "record_gap_count": evidence.get("record_gap_count"),
        "staleness_s": evidence.get("staleness_s"),
    }


def _load_baseline(
    root: Path,
    requested_path: str | None,
) -> tuple[ScoutEnergyReserveBaseline | None, str | None]:
    path = _resolve_existing_path(root, requested_path, _default_baseline_paths(root))
    if path is None:
        return None, None
    return (
        ScoutEnergyReserveBaseline.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        ),
        _relpath(path, root),
    )


def _load_observation(root: Path, requested_path: str | None) -> tuple[Any | None, str | None]:
    path = _resolve_existing_path(root, requested_path, _default_observation_paths(root))
    if path is None:
        return None, None
    return load_wearable_field_observation(path, root=root), _relpath(path, root)


def _default_baseline_paths(root: Path) -> list[Path]:
    return [
        root / "outputs" / "energy" / "scout_energy_reserve_baseline.json",
        root / "outputs" / "scout_energy_reserve_baseline.json",
        root / "energy" / "scout_energy_reserve_baseline.json",
        root / "scout_energy_reserve_baseline.json",
    ]


def _default_observation_paths(root: Path) -> list[Path]:
    return [
        root / "outputs" / "energy" / "wearable_field_observation.json",
        root / "outputs" / "wearable_field_observation.json",
        root / "energy" / "wearable_field_observation.json",
        root / "wearable_field_observation.json",
    ]


def _resolve_existing_path(
    root: Path,
    requested_path: str | None,
    default_paths: list[Path],
) -> Path | None:
    candidates = []
    if requested_path:
        requested = Path(requested_path)
        candidates.append(requested if requested.is_absolute() else root / requested)
    candidates.extend(default_paths)
    for path in candidates:
        if path.exists():
            return path
    return None


def _source_report(
    *,
    baseline_path: str | None,
    observation_path: str | None,
    baseline_loaded: bool,
    observation_loaded: bool,
) -> list[dict[str, Any]]:
    return [
        {
            "source_kind": "energy_reserve_baseline",
            "status": "loaded" if baseline_loaded else "missing",
            "source_path": baseline_path or "scout_energy_reserve_baseline.json",
            "loaded_count": 1 if baseline_loaded else 0,
        },
        {
            "source_kind": "wearable_field_observation",
            "status": "loaded" if observation_loaded else "missing",
            "source_path": observation_path or "wearable_field_observation.json",
            "loaded_count": 1 if observation_loaded else 0,
        },
        {
            "source_kind": "deterministic_energy_vitals_policy",
            "status": "loaded",
            "source_path": "scout_energy_vitals_tool.assess_scout_energy_vitals",
            "loaded_count": 1,
        },
    ]


def _cue_band(
    *,
    reserve_band: str,
    heart_rate_drift_ratio: float | None,
) -> str:
    drift = heart_rate_drift_ratio or 0.0
    if reserve_band == "stop_and_check" or drift >= 0.18:
        return "manual_check"
    if reserve_band == "rest_suggested" or drift >= 0.12:
        return "rest_suggested"
    if reserve_band == "watch" or drift >= 0.08:
        return "slow_down"
    if reserve_band == "normal":
        return "normal_advisory"
    return "missing_evidence"


def _message_zh(cue_band: str) -> str:
    if cue_band == "manual_check":
        return "體能儲備提示：目前低於這段努力的預期範圍，請停下來做自我狀態確認。"
    if cue_band == "rest_suggested":
        return "體能儲備提示：目前低於這段努力的平常趨勢，建議短暫休息。"
    if cue_band == "slow_down":
        return "體能儲備提示：心率負荷高於相近努力的個人基線，請放慢並確認感受。"
    if cue_band == "normal_advisory":
        return "體能儲備提示：目前仍在這段努力的建議觀察範圍內。"
    return "體能儲備提示：缺少必要的穿戴式裝置與個人基線資料。"


def _advisory_actions(cue_band: str) -> list[str]:
    if cue_band == "manual_check":
        return ["stop and do a manual condition check", "keep normal Scout safety/SOS flow separate"]
    if cue_band == "rest_suggested":
        return ["take a short rest", "resume with easier pacing if the user feels ready"]
    if cue_band == "slow_down":
        return ["slow down", "keep rest options visible"]
    if cue_band == "normal_advisory":
        return ["continue normal pacing review"]
    return ["collect wearable vitals and baseline evidence before assessment"]


def _advisory_reasons(evidence: dict[str, Any], *, reserve_band: str) -> list[str]:
    reasons = [
        "baseline-relative advisory trend only",
        f"reserve band context is {reserve_band}",
    ]
    drift_ratio = evidence.get("heart_rate_drift_ratio")
    if not _is_missing(drift_ratio):
        reasons.append(f"heart-rate drift ratio is {float(drift_ratio):.3f} versus expected baseline")
    return reasons


def _heart_rate_drift_ratio(
    heart_rate_bpm: object,
    expected_baseline_bpm: object,
) -> float | None:
    heart_rate = _float_or_none(heart_rate_bpm)
    baseline = _float_or_none(expected_baseline_bpm)
    if heart_rate is None or baseline is None or baseline <= 0:
        return None
    return round((heart_rate - baseline) / baseline, 3)


def _nested_number(payload: dict[str, Any], object_key: str, value_key: str) -> float | None:
    nested = payload.get(object_key)
    if not isinstance(nested, dict):
        return None
    return _float_or_none(nested.get(value_key))


def _first_present(*values: Any) -> Any:
    for value in values:
        if not _is_missing(value):
            return value
    return None


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def _float_or_none(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if _is_missing(value):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "medical_diagnosis": False,
        "provider_values_are_scout_truth": False,
        "raw_health_payload_shared": False,
        "live_provider_api_called": False,
    }
