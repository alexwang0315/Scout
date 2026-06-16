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
    "energy_vitals_snapshot_path",
    "heart_rate_trend",
    "hrv_trend",
    "record_gap_count",
    "staleness_s",
    "baseline_path",
    "observation_path",
)
ENERGY_VITALS_SNAPSHOT_FIELDS = (
    *ENERGY_VITALS_REQUIRED_FIELDS,
    "heart_rate_trend",
    "hrv_trend",
    "record_gap_count",
    "staleness_s",
)


def assess_scout_energy_vitals(
    project_root: Path | str,
    *,
    query: str = "",
    energy_vitals_snapshot_path: str | None = None,
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
    raw_direct = {
        "subject_id": subject_id,
        "observed_at": observed_at,
        "heart_rate_bpm": heart_rate_bpm,
        "hrv_ms": hrv_ms,
        "body_battery_or_provider_energy": body_battery_or_provider_energy,
        "pace_mps": pace_mps,
        "cadence": cadence,
        "activity_load": activity_load,
        "baseline_window_days": baseline_window_days,
        "reserve_score": reserve_score,
        "reserve_band": reserve_band,
        "heart_rate_drift_ratio": heart_rate_drift_ratio,
        "heart_rate_trend": heart_rate_trend if isinstance(heart_rate_trend, dict) else None,
        "hrv_trend": hrv_trend if isinstance(hrv_trend, dict) else None,
        "record_gap_count": record_gap_count,
        "staleness_s": staleness_s,
        "privacy_scope": privacy_scope,
        "source_provider": source_provider,
    }
    caller_field_count = sum(
        1 for value in raw_direct.values() if not _is_missing(value)
    )
    if energy_vitals_snapshot_path or caller_field_count == 0:
        snapshot, snapshot_report = _load_energy_vitals_snapshot(
            root,
            project,
            explicit_path=energy_vitals_snapshot_path,
        )
    else:
        snapshot = {}
        snapshot_report = [
            {
                "source_kind": "energy_vitals_snapshot",
                "status": "skipped_project_fallback_for_caller_snapshot",
                "source_path": None,
                "loaded_count": 0,
            }
        ]
    direct = _normalize_direct_evidence(
        {
            field: _first_present(raw_direct.get(field), snapshot.get(field))
            for field in ENERGY_VITALS_SNAPSHOT_FIELDS
        }
    )
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
    advisory_core_available = _has_advisory_core(evidence)
    answerability = (
        "energy_vitals_advisory_available"
        if advisory_core_available
        else "energy_vitals_missing_required_fields"
    )
    decision = _decision(
        cue=cue,
        advisory_core_available=advisory_core_available,
    )
    field_answer = _field_answer(
        decision=decision,
        cue=cue,
        missing_fields=missing_fields,
    )
    decision_output = _decision_output(
        decision=decision,
        cue=cue,
        evidence=evidence,
        missing_fields=missing_fields,
        field_answer=field_answer,
        advisory_core_available=advisory_core_available,
    )
    return {
        "artifact_kind": ENERGY_VITALS_OUTPUT_KIND,
        "tool_id": ENERGY_VITALS_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_energy_vitals",
        "answerability": answerability,
        "source_status": _source_status(snapshot=snapshot),
        "decision": decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "provided_fields": {
            field: value
            for field, value in evidence.items()
            if not _is_missing(value)
        },
        "advisory": cue,
        "energy_vitals": {
            "role": "Energy / Vitals Advisory",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "medical_diagnosis": False,
            "decision": decision,
            "decision_output": decision_output,
            "cue_band": cue["cue_band"],
            "reserve_band": cue["reserve_band"],
            "required_conditions": decision_output["requiredConditions"],
            "alternative_actions": decision_output["alternativeActions"],
            "next_action": decision_output["nextAction"],
        },
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
                "label": "energy/vitals decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "medical_diagnosis": False,
                "snippet": (
                    f"answerability={answerability}; "
                    f"decision={decision}; "
                    f"reserve_band={evidence.get('reserve_band') or 'unknown'}; "
                    "missing_fields="
                    + ",".join(missing_fields)
                    + "; advisory only, not medical diagnosis, not runtime safety truth"
                ),
            }
        ],
        "source_report": _source_report(
            snapshot_report=snapshot_report,
            baseline_path=resolved_baseline_path,
            observation_path=resolved_observation_path,
            baseline_loaded=baseline is not None,
            observation_loaded=observation is not None,
        ),
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7 slowest/weakest-member conservative basis",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 data confidence",
        ],
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


def _decision(*, cue: dict[str, Any], advisory_core_available: bool) -> str:
    if not advisory_core_available:
        return "DELAY"
    cue_band = str(cue.get("cue_band") or "missing_evidence")
    if cue_band == "manual_check":
        return "CHANGE_PLAN"
    if cue_band in {"rest_suggested", "slow_down"}:
        return "CONDITIONAL_GO"
    if cue_band == "normal_advisory":
        return "GO"
    return "DELAY"


def _field_answer(
    *,
    decision: str,
    cue: dict[str, Any],
    missing_fields: list[str],
) -> str:
    if decision == "DELAY":
        return (
            "體能/穿戴判斷：建議 DELAY。缺少可支撐休息或推進判斷的 "
            + "、".join(missing_fields[:6])
            + "；Scout 不能用不完整穿戴資料假裝確定。"
        )
    reasons = _decision_reasons(cue=cue, missing_fields=missing_fields)
    return (
        f"體能/穿戴判斷：建議 {decision}。"
        + "；".join(reasons[:2])
        + f" 下一步：{_next_action(decision=decision, cue=cue)} "
        "此為 Energy / Vitals 候選判斷，不是醫療診斷，也不是 runtime safety truth；"
        "不得觸發 /safety、SOS、outbound send 或硬體控制。"
    )


def _decision_output(
    *,
    decision: str,
    cue: dict[str, Any],
    evidence: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
    advisory_core_available: bool,
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(cue=cue, missing_fields=missing_fields)
    uncertainty_notes = _uncertainty_notes(
        missing_fields=missing_fields,
        advisory_core_available=advisory_core_available,
    )
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision, cue=cue),
        "reason": " / ".join(reasons[:2]),
        "nextStep": _next_action(decision=decision, cue=cue),
    }
    required_conditions = _required_conditions(
        decision=decision,
        cue=cue,
        missing_fields=missing_fields,
    )
    alternative_actions = _alternative_actions(decision=decision)
    residual_risk = [
        "Wearable/provider values are advisory evidence only.",
        "This output is not medical diagnosis, runtime safety truth, /safety, SOS, outbound send, or hardware control.",
    ]
    second_layer = {
        "details": _decision_details(
            cue=cue,
            evidence=evidence,
            field_answer=field_answer,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternative_actions,
    }
    return {
        "role": "Micro-Decision Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {first_layer['decision']}",
                f"[限制] {first_layer['limit']}",
                f"[原因] {first_layer['reason']}",
                f"[下一步] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": second_layer,
        "action": "energy_vitals_advisory",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "recommendedRestMinutes": _recommended_rest_minutes(cue),
            "timeBufferChangeMinutes": _recommended_rest_minutes(cue),
            "reserveBand": cue.get("reserve_band"),
            "cueBand": cue.get("cue_band"),
            "heartRateDriftRatio": cue.get("heart_rate_drift_ratio"),
            "privacyScope": evidence.get("privacy_scope") or "private_vitals",
        },
        "nextAction": first_layer["nextStep"],
        "confidence": _confidence(
            missing_fields=missing_fields,
            advisory_core_available=advisory_core_available,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternative_actions,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 data confidence",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_reasons(
    *,
    cue: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    reasons = [str(reason) for reason in cue.get("reasons") or [] if str(reason).strip()]
    cue_band = str(cue.get("cue_band") or "missing_evidence")
    if cue_band == "manual_check":
        reasons.insert(0, "體能儲備提示需要停下做人工狀態確認。")
    elif cue_band == "rest_suggested":
        reasons.insert(0, "體能儲備提示建議先短暫休息。")
    elif cue_band == "slow_down":
        reasons.insert(0, "體能儲備提示建議放慢並保留休息選項。")
    elif cue_band == "normal_advisory":
        reasons.insert(0, "體能儲備提示仍在建議觀察範圍內。")
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    if not reasons:
        reasons.append("缺少必要的穿戴式裝置與個人基線資料。")
    return _dedupe(reasons)


def _uncertainty_notes(
    *,
    missing_fields: list[str],
    advisory_core_available: bool,
) -> list[str]:
    notes = [f"Missing field: {field}" for field in missing_fields]
    if not advisory_core_available:
        notes.append("Required heart-rate and reserve-band evidence is not available.")
    notes.append("Wearable/provider values may be stale, smoothed, or device-specific.")
    notes.append("Scout does not infer dehydration, disease, arrhythmia, or overtraining.")
    return _dedupe(notes)


def _confidence(
    *,
    missing_fields: list[str],
    advisory_core_available: bool,
) -> str:
    if missing_fields or not advisory_core_available:
        return "low"
    return "medium"


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "CHANGE_PLAN":
        return "先停在安全點做人工狀態確認。"
    if decision == "DELAY":
        return "建議延後體能/穿戴判斷。"
    if decision == "CONDITIONAL_GO":
        return "可有條件繼續，但必須先降低負荷並重新確認。"
    if decision == "GO" and allowed:
        return "可維持保守配速並在下一節點重查。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str, cue: dict[str, Any]) -> str:
    cue_band = str(cue.get("cue_band") or "missing_evidence")
    if decision == "CHANGE_PLAN":
        return "在安全寬處或下一 CP 停下；完成本人/領隊人工確認前，不得繼續加速、攻頂或進入更高風險段。"
    if decision == "DELAY":
        return "補齊心率、體能儲備、個人基線與時間窗口資料前，不得把此回答當成現場 permission。"
    if decision == "CONDITIONAL_GO" and cue_band == "rest_suggested":
        return "只允許在安全寬處或下一 CP 短休最多 10 分鐘；未改善就改短、撤退或升級人工確認。"
    if decision == "CONDITIONAL_GO":
        return "只允許降低配速並保留最近休息點；下一 CP 或 30 分鐘內必須重查。"
    return "這不是 runtime safety truth；下一 CP 或 30 分鐘內仍需重算體能與隊伍狀態。"


def _next_action(*, decision: str, cue: dict[str, Any]) -> str:
    cue_band = str(cue.get("cue_band") or "missing_evidence")
    if decision == "CHANGE_PLAN":
        return "先停下做本人/領隊人工狀態確認，並把 Pace Guardian、天氣與撤退選項一起重算。"
    if decision == "DELAY":
        return "補齊 normalized vitals、baseline reserve、時間窗口與主觀感受後再評估。"
    if cue_band == "rest_suggested":
        return "短休最多 10 分鐘，改較慢配速；若仍不舒服或資料惡化就改短或撤退。"
    if cue_band == "slow_down":
        return "立刻降速，保留最近安全休息點，下一 CP 或 30 分鐘內重查。"
    return "維持保守配速，下一 CP 或 30 分鐘內重查。"


def _required_conditions(
    *,
    decision: str,
    cue: dict[str, Any],
    missing_fields: list[str],
) -> list[str]:
    conditions = ["不得將穿戴數值當作醫療診斷或 Phase 1 safety truth。"]
    if decision == "CHANGE_PLAN":
        conditions.extend(
            [
                "先停在安全寬處或下一 CP。",
                "本人/領隊完成人工狀態確認。",
                "重算 Pace Guardian、天氣、撤退與隊伍狀態。",
            ]
        )
    elif decision == "CONDITIONAL_GO":
        if str(cue.get("cue_band") or "") == "rest_suggested":
            conditions.append("安全點短休最多 10 分鐘，恢復後改較慢配速。")
        else:
            conditions.append("立刻降速並在下一 CP 或 30 分鐘內重查。")
    elif decision == "GO":
        conditions.append("下一 CP 或 30 分鐘內重查體能、隊伍與天氣。")
    if missing_fields:
        conditions.extend(f"Provide {field}." for field in missing_fields)
    return _dedupe(conditions)


def _alternative_actions(*, decision: str) -> list[str]:
    if decision == "CHANGE_PLAN":
        return ["改短版路線。", "撤回上一個安全 CP。", "由領隊人工啟動既有安全流程。"]
    if decision == "DELAY":
        return ["補齊穿戴/基線資料。", "改問不需要個人健康資料的路線或隊伍判斷。"]
    if decision == "CONDITIONAL_GO":
        return ["改短版或提早休息。", "退回最近安全 CP。"]
    return ["維持保守節奏。", "若主觀感受變差，改用 Pace Guardian 或人工確認。"]


def _decision_details(
    *,
    cue: dict[str, Any],
    evidence: dict[str, Any],
    field_answer: str,
) -> list[str]:
    return [
        field_answer,
        f"cue_band={cue.get('cue_band')}",
        f"reserve_band={cue.get('reserve_band')}",
        f"heart_rate_drift_ratio={cue.get('heart_rate_drift_ratio')}",
        f"record_gap_count={evidence.get('record_gap_count')}",
        f"staleness_s={evidence.get('staleness_s')}",
        "privacy_scope=" + str(evidence.get("privacy_scope") or "private_vitals"),
    ]


def _recommended_rest_minutes(cue: dict[str, Any]) -> int:
    cue_band = str(cue.get("cue_band") or "missing_evidence")
    if cue_band == "rest_suggested":
        return 10
    if cue_band == "slow_down":
        return 5
    return 0


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
    snapshot_report: list[dict[str, Any]],
    baseline_path: str | None,
    observation_path: str | None,
    baseline_loaded: bool,
    observation_loaded: bool,
) -> list[dict[str, Any]]:
    return [
        *snapshot_report,
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


def _load_energy_vitals_snapshot(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = _candidate_paths(
        root,
        project,
        explicit_path=explicit_path,
        ref_keys=(
            "energy_vitals_snapshot_ref",
            "reviewed_energy_vitals_snapshot_ref",
            "wearable_vitals_snapshot_ref",
        ),
        fallbacks=(
            "outputs/energy_vitals_snapshot.reviewed.json",
            "outputs/energy_vitals_snapshot.json",
            "outputs/energy/energy_vitals_snapshot.json",
        ),
    )
    report: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            report.append(
                {
                    "source_kind": "energy_vitals_snapshot",
                    "status": "missing",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        payload = _load_json_object(path)
        snapshot = _snapshot_from_payload(payload)
        if not snapshot:
            report.append(
                {
                    "source_kind": "energy_vitals_snapshot",
                    "status": "invalid_or_empty",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        report.append(
            {
                "source_kind": "energy_vitals_snapshot",
                "status": "loaded",
                "source_path": label,
                "loaded_count": 1,
                "artifact_kind": payload.get("artifact_kind"),
                "source_status": payload.get("status") or payload.get("source_status"),
            }
        )
        return snapshot, report
    return {}, report[:3]


def _candidate_paths(
    root: Path,
    project: dict[str, Any],
    *,
    explicit_path: str | None,
    ref_keys: tuple[str, ...],
    fallbacks: tuple[str, ...],
) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if explicit_path:
        candidates.append((explicit_path, _project_path(root, explicit_path)))
    for key in ref_keys:
        ref = project.get(key)
        if isinstance(ref, str) and ref.strip():
            candidates.append((ref, _project_path(root, ref)))
    for ref in fallbacks:
        candidates.append((ref, _project_path(root, ref)))
    deduped: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append((label, path))
    return deduped


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _snapshot_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    nested = payload.get("energy_vitals_snapshot")
    if not isinstance(nested, dict):
        nested = payload.get("wearable_vitals")
    if not isinstance(nested, dict):
        nested = payload.get("snapshot")
    snapshot_source = nested if isinstance(nested, dict) else payload
    snapshot = {
        field: snapshot_source.get(field)
        for field in ENERGY_VITALS_SNAPSHOT_FIELDS
        if not _is_missing(snapshot_source.get(field))
    }
    if payload.get("status") and "source_status" not in snapshot:
        snapshot["source_status"] = payload.get("status")
    return snapshot


def _normalize_direct_evidence(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_id": value.get("subject_id"),
        "observed_at": value.get("observed_at"),
        "heart_rate_bpm": _float_or_none(value.get("heart_rate_bpm")),
        "hrv_ms": _float_or_none(value.get("hrv_ms")),
        "body_battery_or_provider_energy": _float_or_none(
            value.get("body_battery_or_provider_energy")
        ),
        "pace_mps": _float_or_none(value.get("pace_mps")),
        "cadence": _float_or_none(value.get("cadence")),
        "activity_load": _float_or_none(value.get("activity_load")),
        "baseline_window_days": _int_or_none(value.get("baseline_window_days")),
        "reserve_score": _int_or_none(value.get("reserve_score")),
        "reserve_band": value.get("reserve_band"),
        "heart_rate_drift_ratio": _float_or_none(value.get("heart_rate_drift_ratio")),
        "heart_rate_trend": value.get("heart_rate_trend")
        if isinstance(value.get("heart_rate_trend"), dict)
        else None,
        "hrv_trend": value.get("hrv_trend")
        if isinstance(value.get("hrv_trend"), dict)
        else None,
        "record_gap_count": _int_or_none(value.get("record_gap_count")),
        "staleness_s": _float_or_none(value.get("staleness_s")),
        "privacy_scope": value.get("privacy_scope"),
        "source_provider": value.get("source_provider"),
    }


def _source_status(*, snapshot: dict[str, Any]) -> str:
    if snapshot:
        return str(snapshot.get("source_status") or "loaded_energy_vitals_snapshot")
    return "candidate_only"


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


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
