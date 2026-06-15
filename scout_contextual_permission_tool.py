from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import StrEnum
from math import floor
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


CONTEXTUAL_PERMISSION_TOOL_ID = "scout.ai.contextual_permission.assess.v0"
CONTEXTUAL_PERMISSION_OUTPUT_KIND = "scout_ai_contextual_permission_tool_output"
CONTEXTUAL_PERMISSION_REQUIRED_FIELDS = ("project_root",)
CONTEXTUAL_PERMISSION_OPTIONAL_FIELDS = (
    "action",
    "current_time",
    "current_cp_id",
    "next_cp_id",
    "remaining_safety_buffer_minutes",
    "requested_duration_minutes",
    "current_delay_minutes",
    "next_segment_uncertainty_minutes",
    "weather_reserve_minutes",
    "daylight_reserve_minutes",
    "retreat_reserve_minutes",
    "slowest_member_reserve_minutes",
    "weather_window_impact",
    "daylight_impact",
    "retreat_impact",
    "fatigue_impact",
    "team_pace_impact",
    "location_constraint",
    "terrain_risk_level",
    "communication_status",
    "equipment_status",
    "confidence",
    "planned_eta_path",
    "weather_daylight_evidence_path",
    "plan_validation_path",
    "energy_vitals_path",
    "team_status_path",
)


class ScoutDecision(StrEnum):
    GO = "GO"
    CONDITIONAL_GO = "CONDITIONAL_GO"
    GUIDED_ONLY = "GUIDED_ONLY"
    CHANGE_PLAN = "CHANGE_PLAN"
    DELAY = "DELAY"
    NO_GO = "NO_GO"
    ESCALATE = "ESCALATE"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OutdoorAction(StrEnum):
    STOP = "stop"
    FILM = "film"
    PHOTO = "photo"
    REST = "rest"
    LUNCH = "lunch"
    SUMMIT = "summit"
    REROUTE = "reroute"
    WAIT = "wait"
    CONTINUE = "continue"
    RETREAT = "retreat"
    WEAR_RAIN_GEAR = "wear_rain_gear"
    SPLIT_TEAM = "split_team"
    CROSS_STREAM = "cross_stream"
    ENTER_EXPOSED_SECTION = "enter_exposed_section"


class ScoutContextualBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_enum_values=True,
    )


class ContextualPermissionCost(ScoutContextualBaseModel):
    time_buffer_change_minutes: int | None = Field(
        default=None,
        alias="timeBufferChangeMinutes",
    )
    weather_window_impact: str | None = Field(
        default=None,
        alias="weatherWindowImpact",
    )
    daylight_impact: str | None = Field(default=None, alias="daylightImpact")
    retreat_impact: str | None = Field(default=None, alias="retreatImpact")
    fatigue_impact: str | None = Field(default=None, alias="fatigueImpact")
    team_pace_impact: str | None = Field(default=None, alias="teamPaceImpact")


class ContextualPermission(ScoutContextualBaseModel):
    action: OutdoorAction
    decision: ScoutDecision
    allowed: bool
    max_duration_minutes: int | None = Field(
        default=None,
        ge=0,
        alias="maxDurationMinutes",
    )
    leave_by: str | None = Field(default=None, alias="leaveBy")
    location_constraint: str | None = Field(default=None, alias="locationConstraint")
    main_reasons: list[str] = Field(default_factory=list, alias="mainReasons")
    cost: ContextualPermissionCost | None = None
    next_action: str = Field(min_length=1, alias="nextAction")
    confidence: ConfidenceLevel
    uncertainty_notes: list[str] = Field(
        default_factory=list,
        alias="uncertaintyNotes",
    )
    residual_risk: list[str] = Field(default_factory=list, alias="residualRisk")
    required_conditions: list[str] = Field(
        default_factory=list,
        alias="requiredConditions",
    )
    alternative_actions: list[str] = Field(
        default_factory=list,
        alias="alternativeActions",
    )


class RiskBudget(ScoutContextualBaseModel):
    remaining_safety_buffer_minutes: float | None = Field(
        default=None,
        alias="remainingSafetyBufferMinutes",
    )
    requested_duration_minutes: float | None = Field(
        default=None,
        alias="requestedDurationMinutes",
    )
    current_delay_minutes: float = Field(default=0.0, alias="currentDelayMinutes")
    next_segment_uncertainty_minutes: float = Field(
        default=0.0,
        alias="nextSegmentUncertaintyMinutes",
    )
    weather_reserve_minutes: float = Field(
        default=0.0,
        alias="weatherReserveMinutes",
    )
    daylight_reserve_minutes: float = Field(
        default=0.0,
        alias="daylightReserveMinutes",
    )
    retreat_reserve_minutes: float = Field(
        default=0.0,
        alias="retreatReserveMinutes",
    )
    slowest_member_reserve_minutes: float = Field(
        default=0.0,
        alias="slowestMemberReserveMinutes",
    )
    authorized_duration_minutes: int = Field(
        default=0,
        alias="authorizedDurationMinutes",
    )
    buffer_after_action_minutes: int | None = Field(
        default=None,
        alias="bufferAfterActionMinutes",
    )


_BUDGET_ACTIONS = {
    OutdoorAction.STOP,
    OutdoorAction.FILM,
    OutdoorAction.PHOTO,
    OutdoorAction.REST,
    OutdoorAction.LUNCH,
    OutdoorAction.SUMMIT,
    OutdoorAction.REROUTE,
    OutdoorAction.WAIT,
    OutdoorAction.SPLIT_TEAM,
    OutdoorAction.CROSS_STREAM,
    OutdoorAction.ENTER_EXPOSED_SECTION,
}

_DEFAULT_DURATION_BY_ACTION = {
    OutdoorAction.STOP: 6,
    OutdoorAction.FILM: 6,
    OutdoorAction.PHOTO: 5,
    OutdoorAction.REST: 8,
    OutdoorAction.LUNCH: 20,
    OutdoorAction.SUMMIT: 30,
    OutdoorAction.REROUTE: 12,
    OutdoorAction.WAIT: 5,
    OutdoorAction.SPLIT_TEAM: 0,
    OutdoorAction.CROSS_STREAM: 0,
    OutdoorAction.ENTER_EXPOSED_SECTION: 0,
}

_MINIMUM_USEFUL_DURATION_BY_ACTION = {
    OutdoorAction.STOP: 1,
    OutdoorAction.FILM: 2,
    OutdoorAction.PHOTO: 2,
    OutdoorAction.REST: 3,
    OutdoorAction.LUNCH: 12,
    OutdoorAction.SUMMIT: 25,
    OutdoorAction.REROUTE: 8,
    OutdoorAction.WAIT: 1,
}

_HIGH_RISK_LEVELS = {"high", "very_high", "critical", "severe", "extreme"}
_CRITICAL_RISK_LEVELS = {"critical", "severe", "extreme"}
DEFAULT_UNREVIEWED_WEATHER_RESERVE_MINUTES = 15
DEFAULT_UNREVIEWED_SEGMENT_POLICY_RESERVE_MINUTES = 10
DEFAULT_UNREVIEWED_DAYLIGHT_RESERVE_MINUTES = 60
DEFAULT_ENERGY_MISSING_CORE_RESERVE_MINUTES = 10
ENERGY_SLOW_DOWN_RESERVE_MINUTES = 5
ENERGY_REST_SUGGESTED_RESERVE_MINUTES = 10
ENERGY_MANUAL_CHECK_RESERVE_MINUTES = 20


def assess_scout_contextual_permission(
    project_root: Path | str,
    *,
    query: str = "",
    action: str | None = None,
    current_time: str | None = None,
    current_cp_id: str | None = None,
    next_cp_id: str | None = None,
    remaining_safety_buffer_minutes: float | int | str | None = None,
    requested_duration_minutes: float | int | str | None = None,
    current_delay_minutes: float | int | str | None = None,
    next_segment_uncertainty_minutes: float | int | str | None = None,
    weather_reserve_minutes: float | int | str | None = None,
    daylight_reserve_minutes: float | int | str | None = None,
    retreat_reserve_minutes: float | int | str | None = None,
    slowest_member_reserve_minutes: float | int | str | None = None,
    weather_window_impact: str | None = None,
    daylight_impact: str | None = None,
    retreat_impact: str | None = None,
    fatigue_impact: str | None = None,
    team_pace_impact: str | None = None,
    location_constraint: str | None = None,
    terrain_risk_level: str | None = None,
    communication_status: str | None = None,
    equipment_status: str | None = None,
    confidence: str | None = None,
    planned_eta_path: str | None = None,
    weather_daylight_evidence_path: str | None = None,
    plan_validation_path: str | None = None,
    energy_vitals_path: str | None = None,
    team_status_path: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_project(root)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    resolved_action = _resolve_action(action, query)
    derived_budget_source = _derive_risk_budget_source(
        root,
        project=project,
        current_time=current_time,
        next_cp_id=next_cp_id,
        planned_eta_path=planned_eta_path,
    )
    if remaining_safety_buffer_minutes is None and derived_budget_source:
        remaining_safety_buffer_minutes = derived_budget_source[
            "remaining_safety_buffer_minutes"
        ]
        if current_delay_minutes is None:
            current_delay_minutes = derived_budget_source["current_delay_minutes"]
        if next_cp_id is None:
            next_cp_id = str(derived_budget_source["next_cp_id"])
    workspace_reserve_source = _derive_workspace_reserve_source(
        root,
        project=project,
        enabled=derived_budget_source is not None,
        weather_daylight_evidence_path=weather_daylight_evidence_path,
        plan_validation_path=plan_validation_path,
        energy_vitals_path=energy_vitals_path,
        team_status_path=team_status_path,
    )
    if derived_budget_source is not None:
        reserves = workspace_reserve_source.get("reserves", {})
        if _float_or_none(next_segment_uncertainty_minutes) is None:
            next_segment_uncertainty_minutes = reserves.get(
                "next_segment_uncertainty_minutes"
            )
        if _float_or_none(weather_reserve_minutes) is None:
            weather_reserve_minutes = reserves.get("weather_reserve_minutes")
        if _float_or_none(daylight_reserve_minutes) is None:
            daylight_reserve_minutes = reserves.get("daylight_reserve_minutes")
        if _float_or_none(retreat_reserve_minutes) is None:
            retreat_reserve_minutes = reserves.get("retreat_reserve_minutes")
        if _float_or_none(slowest_member_reserve_minutes) is None:
            slowest_member_reserve_minutes = reserves.get(
                "slowest_member_reserve_minutes"
            )
    budget = _risk_budget(
        remaining_safety_buffer_minutes=remaining_safety_buffer_minutes,
        requested_duration_minutes=requested_duration_minutes,
        current_delay_minutes=current_delay_minutes,
        next_segment_uncertainty_minutes=next_segment_uncertainty_minutes,
        weather_reserve_minutes=weather_reserve_minutes,
        daylight_reserve_minutes=daylight_reserve_minutes,
        retreat_reserve_minutes=retreat_reserve_minutes,
        slowest_member_reserve_minutes=slowest_member_reserve_minutes,
    )
    missing_fields = _missing_fields(
        action=resolved_action,
        budget=budget,
    )
    permission = _permission(
        action=resolved_action,
        query=query,
        current_time=current_time,
        current_cp_id=current_cp_id,
        next_cp_id=next_cp_id,
        budget=budget,
        missing_fields=missing_fields,
        requested_duration_minutes=_float_or_none(requested_duration_minutes),
        terrain_risk_level=_normalized_risk_level(terrain_risk_level, query),
        communication_status=communication_status,
        equipment_status=equipment_status,
        confidence=confidence,
        weather_window_impact=weather_window_impact,
        daylight_impact=daylight_impact,
        retreat_impact=retreat_impact,
        fatigue_impact=fatigue_impact,
        team_pace_impact=team_pace_impact,
        location_constraint=location_constraint,
    )
    permission_payload = permission.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    budget_payload = budget.model_dump(mode="json", by_alias=True, exclude_none=True)
    field_answer = _field_answer(permission, budget=budget)
    answerability = (
        "contextual_permission_missing_required_fields"
        if missing_fields
        else "contextual_permission_decision_available"
    )
    risk_budget_source = _risk_budget_source(
        remaining_safety_buffer_minutes=remaining_safety_buffer_minutes,
        derived_budget_source=derived_budget_source,
        workspace_reserve_source=workspace_reserve_source,
    )
    warnings = _warnings(
        missing_fields=missing_fields,
        communication_status=communication_status,
        equipment_status=equipment_status,
        risk_budget_source=risk_budget_source,
    )

    return {
        "tool_id": CONTEXTUAL_PERMISSION_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_contextual_permission",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": permission.decision,
        "allowed": permission.allowed,
        "action": permission.action,
        "max_duration_minutes": permission.max_duration_minutes,
        "leave_by": permission.leave_by,
        "field_answer": field_answer,
        "contextual_permission": permission_payload,
        "risk_budget": budget_payload,
        "risk_budget_source": risk_budget_source,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 4 decision vocabulary",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7.3 Team Pace Fit",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 13 risk budget",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 13.1 conceptual formula",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 field answer format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "result_count": 1,
        "results": [
            {
                "label": "contextual permission decision",
                "action": permission.action,
                "decision": permission.decision,
                "allowed": permission.allowed,
                "max_duration_minutes": permission.max_duration_minutes,
                "leave_by": permission.leave_by,
                "field_answer": field_answer,
                "answerability": answerability,
                "confidence": permission.confidence,
                "main_reasons": list(permission.main_reasons),
                "next_action": permission.next_action,
            }
        ],
        "boundary": _closed_boundary(),
    }


def _risk_budget(
    *,
    remaining_safety_buffer_minutes: float | int | str | None,
    requested_duration_minutes: float | int | str | None,
    current_delay_minutes: float | int | str | None,
    next_segment_uncertainty_minutes: float | int | str | None,
    weather_reserve_minutes: float | int | str | None,
    daylight_reserve_minutes: float | int | str | None,
    retreat_reserve_minutes: float | int | str | None,
    slowest_member_reserve_minutes: float | int | str | None,
) -> RiskBudget:
    remaining = _float_or_none(remaining_safety_buffer_minutes)
    next_uncertainty = _nonnegative_float(next_segment_uncertainty_minutes)
    weather = _nonnegative_float(weather_reserve_minutes)
    daylight = _nonnegative_float(daylight_reserve_minutes)
    retreat = _nonnegative_float(retreat_reserve_minutes)
    slowest = _nonnegative_float(slowest_member_reserve_minutes)
    authorized = 0
    if remaining is not None:
        authorized = floor(
            remaining - next_uncertainty - weather - daylight - retreat - slowest
        )
    return RiskBudget(
        remaining_safety_buffer_minutes=remaining,
        requested_duration_minutes=_float_or_none(requested_duration_minutes),
        current_delay_minutes=_nonnegative_float(current_delay_minutes),
        next_segment_uncertainty_minutes=next_uncertainty,
        weather_reserve_minutes=weather,
        daylight_reserve_minutes=daylight,
        retreat_reserve_minutes=retreat,
        slowest_member_reserve_minutes=slowest,
        authorized_duration_minutes=max(0, authorized),
    )


def _permission(
    *,
    action: OutdoorAction,
    query: str,
    current_time: str | None,
    current_cp_id: str | None,
    next_cp_id: str | None,
    budget: RiskBudget,
    missing_fields: list[str],
    requested_duration_minutes: float | None,
    terrain_risk_level: str | None,
    communication_status: str | None,
    equipment_status: str | None,
    confidence: str | None,
    weather_window_impact: str | None,
    daylight_impact: str | None,
    retreat_impact: str | None,
    fatigue_impact: str | None,
    team_pace_impact: str | None,
    location_constraint: str | None,
) -> ContextualPermission:
    if missing_fields and action in _BUDGET_ACTIONS:
        return _no_go_permission(
            action=action,
            decision=ScoutDecision.NO_GO,
            reason="缺少剩餘安全 buffer，Scout 不能授權會消耗風險預算的行為。",
            next_action=_safe_next_action(action, next_cp_id),
            confidence=ConfidenceLevel.LOW,
            uncertainty_notes=[
                "remaining_safety_buffer_minutes is required for bounded permission.",
                "資料不足時 Scout 依標準採保守判斷。",
            ],
            alternative_actions=_alternative_actions(action, next_cp_id),
        )

    if action == OutdoorAction.RETREAT:
        return ContextualPermission(
            action=action,
            decision=ScoutDecision.GO,
            allowed=True,
            main_reasons=["撤退通常降低暴露時間與後續不確定性。"],
            cost=ContextualPermissionCost(time_buffer_change_minutes=0),
            next_action="開始撤退，前往最近安全點並保持隊伍完整。",
            confidence=_confidence(confidence, default=ConfidenceLevel.MEDIUM),
            residual_risk=["撤退途中仍需注意地形、天氣與隊伍狀態。"],
        )

    if action == OutdoorAction.WEAR_RAIN_GEAR:
        return ContextualPermission(
            action=action,
            decision=ScoutDecision.GO,
            allowed=True,
            main_reasons=["穿雨具不應消耗主要路線 buffer，且可降低風寒與濕衣風險。"],
            cost=ContextualPermissionCost(time_buffer_change_minutes=0),
            next_action="就地穿上雨具，完成後立即回到原定節奏。",
            confidence=_confidence(confidence, default=ConfidenceLevel.MEDIUM),
            residual_risk=["若風雨持續增強，仍需重新評估撤退或改線。"],
        )

    if _is_high_risk_action(action, terrain_risk_level, query):
        decision = (
            ScoutDecision.ESCALATE
            if terrain_risk_level in _CRITICAL_RISK_LEVELS
            or action == OutdoorAction.CROSS_STREAM
            else ScoutDecision.NO_GO
        )
        return _no_go_permission(
            action=action,
            decision=decision,
            reason=_high_risk_reason(action, terrain_risk_level),
            next_action=_high_risk_next_action(action, next_cp_id),
            confidence=_confidence(confidence, default=ConfidenceLevel.MEDIUM),
            uncertainty_notes=_status_uncertainty_notes(
                communication_status=communication_status,
                equipment_status=equipment_status,
            ),
            alternative_actions=_alternative_actions(action, next_cp_id),
        )

    if action in _BUDGET_ACTIONS:
        authorized = int(budget.authorized_duration_minutes)
        minimum = _MINIMUM_USEFUL_DURATION_BY_ACTION.get(action, 1)
        if authorized < minimum:
            return _no_go_permission(
                action=action,
                decision=_budget_failure_decision(action),
                reason=(
                    f"目前可授權時間只有 {authorized} 分鐘，低於"
                    f"{_action_label(action)}的最低可用門檻。"
                ),
                next_action=_safe_next_action(action, next_cp_id),
                confidence=_confidence(confidence, default=ConfidenceLevel.MEDIUM),
                uncertainty_notes=_status_uncertainty_notes(
                    communication_status=communication_status,
                    equipment_status=equipment_status,
                ),
                alternative_actions=_alternative_actions(action, next_cp_id),
            )

        requested_or_default = requested_duration_minutes
        if requested_or_default is None:
            requested_or_default = _DEFAULT_DURATION_BY_ACTION.get(action, authorized)
        max_duration = max(0, min(floor(requested_or_default), authorized))
        if action in {OutdoorAction.SUMMIT, OutdoorAction.REROUTE}:
            decision = ScoutDecision.CONDITIONAL_GO
            if max_duration < _DEFAULT_DURATION_BY_ACTION.get(action, max_duration):
                decision = ScoutDecision.CHANGE_PLAN
                return _no_go_permission(
                    action=action,
                    decision=decision,
                    reason=(
                        f"目前可授權時間只有 {authorized} 分鐘，不足以支撐"
                        f"{_action_label(action)}。"
                    ),
                    next_action=_safe_next_action(action, next_cp_id),
                    confidence=_confidence(confidence, default=ConfidenceLevel.MEDIUM),
                    uncertainty_notes=_status_uncertainty_notes(
                        communication_status=communication_status,
                        equipment_status=equipment_status,
                    ),
                    alternative_actions=_alternative_actions(action, next_cp_id),
                )
        else:
            decision = ScoutDecision.CONDITIONAL_GO

        leave_by = _leave_by(current_time, max_duration)
        buffer_after = (
            None
            if budget.remaining_safety_buffer_minutes is None
            else floor(budget.remaining_safety_buffer_minutes - max_duration)
        )
        budget.buffer_after_action_minutes = buffer_after
        return ContextualPermission(
            action=action,
            decision=decision,
            allowed=True,
            max_duration_minutes=max_duration,
            leave_by=leave_by,
            location_constraint=location_constraint or _default_location_constraint(action),
            main_reasons=_allowed_reasons(
                action=action,
                max_duration=max_duration,
                budget=budget,
                current_cp_id=current_cp_id,
                next_cp_id=next_cp_id,
            ),
            cost=ContextualPermissionCost(
                time_buffer_change_minutes=-max_duration,
                weather_window_impact=weather_window_impact
                or _default_weather_impact(budget),
                daylight_impact=daylight_impact or _default_daylight_impact(budget),
                retreat_impact=retreat_impact or _default_retreat_impact(budget),
                fatigue_impact=fatigue_impact,
                team_pace_impact=team_pace_impact or _default_team_pace_impact(budget),
            ),
            next_action=_allowed_next_action(action, next_cp_id),
            confidence=_confidence(confidence, default=ConfidenceLevel.MEDIUM),
            uncertainty_notes=_allowed_uncertainty_notes(
                current_time=current_time,
                communication_status=communication_status,
                equipment_status=equipment_status,
            ),
            residual_risk=_residual_risk(action, terrain_risk_level),
            required_conditions=_required_conditions(
                leave_by=leave_by,
                max_duration=max_duration,
                action=action,
            ),
        )

    return ContextualPermission(
        action=action,
        decision=ScoutDecision.GO,
        allowed=True,
        main_reasons=["此行動未被判定為會直接消耗停留型風險預算。"],
        cost=ContextualPermissionCost(time_buffer_change_minutes=0),
        next_action=_allowed_next_action(action, next_cp_id),
        confidence=_confidence(confidence, default=ConfidenceLevel.LOW),
        uncertainty_notes=[
            "此工具目前只對停留、拍攝、休息、等待、攻頂等微決策做完整預算計算。"
        ],
        residual_risk=["仍需依現場天氣、地形與隊伍狀態重新評估。"],
    )


def _no_go_permission(
    *,
    action: OutdoorAction,
    decision: ScoutDecision,
    reason: str,
    next_action: str,
    confidence: ConfidenceLevel,
    uncertainty_notes: list[str] | None = None,
    alternative_actions: list[str] | None = None,
) -> ContextualPermission:
    return ContextualPermission(
        action=action,
        decision=decision,
        allowed=False,
        main_reasons=[reason],
        next_action=next_action,
        confidence=confidence,
        uncertainty_notes=uncertainty_notes or [],
        residual_risk=["若忽略此建議，可能壓縮撤退、日照、天氣或隊伍最慢者 buffer。"],
        alternative_actions=alternative_actions or _alternative_actions(action, None),
    )


def _missing_fields(*, action: OutdoorAction, budget: RiskBudget) -> list[str]:
    if action in _BUDGET_ACTIONS and budget.remaining_safety_buffer_minutes is None:
        return ["remaining_safety_buffer_minutes"]
    return []


def _derive_risk_budget_source(
    root: Path,
    *,
    project: dict[str, Any],
    current_time: str | None,
    next_cp_id: str | None,
    planned_eta_path: str | None,
) -> dict[str, Any] | None:
    current = _parse_datetime(current_time)
    if current is None:
        return None
    eta_payload, source_path = _load_planned_eta(
        root,
        project=project,
        explicit_path=planned_eta_path,
    )
    if not eta_payload:
        return None
    estimate = _match_eta_estimate(
        eta_payload,
        current=current,
        next_cp_id=next_cp_id,
    )
    if estimate is None:
        return None
    eta = _parse_datetime(str(estimate.get("eta") or ""))
    if eta is None:
        return None
    minutes_until_eta = floor((eta - current).total_seconds() / 60)
    remaining = max(0, minutes_until_eta)
    delay = max(0, -minutes_until_eta)
    return {
        "source_status": "derived_from_planned_eta_candidate",
        "source_path": source_path,
        "matched_estimate_id": str(estimate.get("estimate_id") or ""),
        "next_cp_id": str(estimate.get("to_node_name") or next_cp_id or ""),
        "planned_eta": eta.isoformat(),
        "current_time": current.isoformat(),
        "minutes_until_planned_eta": minutes_until_eta,
        "remaining_safety_buffer_minutes": remaining,
        "current_delay_minutes": delay,
        "runtime_safety_truth": False,
        "notes": [
            "Derived from candidate planned ETA only; not reviewed daylight, weather, or runtime safety truth.",
            "Caller-provided remaining_safety_buffer_minutes takes precedence over this fallback.",
        ],
    }


def _derive_workspace_reserve_source(
    root: Path,
    *,
    project: dict[str, Any],
    enabled: bool,
    weather_daylight_evidence_path: str | None,
    plan_validation_path: str | None,
    energy_vitals_path: str | None,
    team_status_path: str | None,
) -> dict[str, Any]:
    if not enabled:
        return {
            "source_status": "not_applied",
            "runtime_safety_truth": False,
            "reserves": {},
            "reserve_sources": [],
            "notes": [
                "Workspace reserve fallback is applied only when the base buffer is derived from planned ETA."
            ],
        }

    weather_payload, weather_source_path = _load_first_project_json(
        root,
        project=project,
        explicit_path=weather_daylight_evidence_path,
        ref_keys=("weather_daylight_evidence_ref",),
        fallbacks=("outputs/weather_daylight_evidence.json",),
    )
    plan_payload, plan_source_path = _load_first_project_json(
        root,
        project=project,
        explicit_path=plan_validation_path,
        ref_keys=("plan_validation_candidates_ref",),
        fallbacks=("outputs/plan_validation_candidates.json",),
    )
    energy_payload, energy_source_path = _load_first_project_json(
        root,
        project=project,
        explicit_path=energy_vitals_path,
        ref_keys=("energy_vitals_ref", "energy_vitals_snapshot_ref"),
        fallbacks=(
            "outputs/energy_vitals.json",
            "outputs/energy_vitals_snapshot.json",
            "outputs/energy/energy_vitals.json",
        ),
    )
    team_payload, team_source_path = _load_first_project_json(
        root,
        project=project,
        explicit_path=team_status_path,
        ref_keys=("team_status_ref", "team_pace_ref", "team_guardian_ref"),
        fallbacks=(
            "outputs/team_status.json",
            "outputs/team_pace_fit.json",
            "outputs/team_guardian.json",
        ),
    )
    reserves: dict[str, float] = {}
    reserve_sources: list[dict[str, Any]] = []

    daylight_margin = _dark_arrival_warning_margin_minutes(weather_payload)
    if _weather_daylight_needs_review(weather_payload):
        _set_reserve(
            reserves,
            reserve_sources,
            field="daylight_reserve_minutes",
            minutes=daylight_margin,
            source_path=weather_source_path,
            reason="weather/daylight artifact requires human review before go/no-go use",
        )
        _set_reserve(
            reserves,
            reserve_sources,
            field="weather_reserve_minutes",
            minutes=DEFAULT_UNREVIEWED_WEATHER_RESERVE_MINUTES,
            source_path=weather_source_path,
            reason="weather window is placeholder or not authoritative",
        )

    for finding in _plan_validation_findings(plan_payload):
        missing = {
            str(item)
            for item in finding.get("missing_any", [])
            if str(item).strip()
        }
        rule_id = str(finding.get("rule_id") or "")
        if "reviewed_daylight_window" in missing:
            _set_reserve(
                reserves,
                reserve_sources,
                field="daylight_reserve_minutes",
                minutes=daylight_margin,
                source_path=plan_source_path,
                reason=str(finding.get("message") or rule_id),
            )
        if "reviewed_weather_window" in missing:
            _set_reserve(
                reserves,
                reserve_sources,
                field="weather_reserve_minutes",
                minutes=DEFAULT_UNREVIEWED_WEATHER_RESERVE_MINUTES,
                source_path=plan_source_path,
                reason=str(finding.get("message") or rule_id),
            )
        if rule_id == "segment_policy_candidates_require_human_review":
            _set_reserve(
                reserves,
                reserve_sources,
                field="next_segment_uncertainty_minutes",
                minutes=DEFAULT_UNREVIEWED_SEGMENT_POLICY_RESERVE_MINUTES,
                source_path=plan_source_path,
                reason=str(finding.get("message") or rule_id),
            )

    energy_reserve = _slowest_member_reserve_from_energy_vitals(energy_payload)
    if energy_reserve:
        _set_reserve(
            reserves,
            reserve_sources,
            field="slowest_member_reserve_minutes",
            minutes=float(energy_reserve["reserve_minutes"]),
            source_path=energy_source_path,
            reason=str(energy_reserve["reason"]),
            detail={
                "source_kind": "energy_vitals_advisory",
                "candidate_basis": energy_reserve["candidate_basis"],
                "subject_id": energy_reserve.get("subject_id"),
                "raw_health_payload_embedded": False,
                "provider_values_are_scout_truth": False,
            },
        )

    team_reserve = _slowest_member_reserve_from_team_status(team_payload)
    if team_reserve:
        _set_reserve(
            reserves,
            reserve_sources,
            field="slowest_member_reserve_minutes",
            minutes=float(team_reserve["reserve_minutes"]),
            source_path=team_source_path,
            reason=str(team_reserve["reason"]),
            detail={
                "source_kind": "team_status",
                "candidate_basis": team_reserve["candidate_basis"],
                "member_ref": team_reserve.get("member_ref"),
                "average_pace_used": False,
            },
        )

    source_status = (
        "workspace_reserves_applied"
        if reserve_sources
        else "workspace_reserves_not_needed_reviewed_evidence"
        if weather_payload or plan_payload or energy_payload or team_payload
        else "workspace_reserves_not_found"
    )
    return {
        "source_status": source_status,
        "runtime_safety_truth": False,
        "reserves": reserves,
        "reserve_sources": reserve_sources,
        "notes": [
            "Workspace reserves are candidate-only deductions from planned ETA slack.",
            "They do not mutate readiness, MissionGraph, Ln, or /safety/* state.",
        ],
    }


def _set_reserve(
    reserves: dict[str, float],
    reserve_sources: list[dict[str, Any]],
    *,
    field: str,
    minutes: float,
    source_path: str | None,
    reason: str,
    detail: dict[str, Any] | None = None,
) -> None:
    if minutes <= 0:
        return
    previous = reserves.get(field, 0.0)
    reserves[field] = max(previous, float(minutes))
    source = {
        "reserve_field": field,
        "reserve_minutes": float(minutes),
        "source_path": source_path,
        "reason": reason,
        "runtime_safety_truth": False,
    }
    if detail:
        source.update({key: value for key, value in detail.items() if value is not None})
    reserve_sources.append(source)


def _slowest_member_reserve_from_energy_vitals(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not payload:
        return None
    candidates = [_energy_reserve_candidate(payload)]
    for key in ("members", "team_members", "participants"):
        items = payload.get(key)
        if isinstance(items, list):
            candidates.extend(_energy_reserve_candidate(item) for item in items)
    usable = [candidate for candidate in candidates if candidate is not None]
    if not usable:
        return None
    usable.sort(key=lambda item: float(item["reserve_minutes"]), reverse=True)
    return usable[0]


def _slowest_member_reserve_from_team_status(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not payload:
        return None
    candidates: list[dict[str, Any] | None] = []
    for key in ("members", "team_members", "participants"):
        items = payload.get(key)
        if isinstance(items, list):
            candidates.extend(_team_reserve_candidate(item) for item in items)
    if not candidates:
        candidates.append(_team_reserve_candidate(payload))
    usable = [candidate for candidate in candidates if candidate is not None]
    if not usable:
        return None
    usable.sort(key=lambda item: float(item["reserve_minutes"]), reverse=True)
    return usable[0]


def _energy_reserve_candidate(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    provided = payload.get("provided_fields")
    provided = provided if isinstance(provided, dict) else {}
    advisory = payload.get("advisory")
    advisory = advisory if isinstance(advisory, dict) else {}
    cue_band = _first_text(
        advisory.get("cue_band"),
        provided.get("cue_band"),
        payload.get("cue_band"),
    )
    reserve_band = _first_text(
        provided.get("reserve_band"),
        advisory.get("reserve_band"),
        payload.get("reserve_band"),
    )
    reserve_score = _first_number(
        provided.get("reserve_score"),
        advisory.get("reserve_score"),
        payload.get("reserve_score"),
    )
    drift_ratio = _first_number(
        provided.get("heart_rate_drift_ratio"),
        advisory.get("heart_rate_drift_ratio"),
        payload.get("heart_rate_drift_ratio"),
    )
    answerability = str(payload.get("answerability") or "")
    member_ref = _first_text(
        provided.get("subject_id"),
        payload.get("subject_id"),
        payload.get("member_id"),
        payload.get("participant_id"),
    )
    minutes, basis = _reserve_minutes_from_energy_markers(
        cue_band=cue_band,
        reserve_band=reserve_band,
        reserve_score=reserve_score,
        drift_ratio=drift_ratio,
    )
    if minutes <= 0 and answerability == "energy_vitals_missing_required_fields":
        minutes = DEFAULT_ENERGY_MISSING_CORE_RESERVE_MINUTES
        basis.append("energy_vitals_missing_required_fields")
    if minutes <= 0:
        return None
    return {
        "reserve_minutes": float(minutes),
        "reason": (
            "energy/vitals advisory requires preserving time for the slowest or "
            "most vulnerable member"
        ),
        "candidate_basis": basis,
        "subject_id": member_ref,
    }


def _team_reserve_candidate(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    cue_band = _first_text(payload.get("cue_band"), payload.get("status"))
    reserve_band = _first_text(payload.get("reserve_band"), payload.get("pace_band"))
    reserve_score = _first_number(payload.get("reserve_score"), payload.get("pace_score"))
    drift_ratio = _first_number(payload.get("heart_rate_drift_ratio"))
    minutes, basis = _reserve_minutes_from_energy_markers(
        cue_band=cue_band,
        reserve_band=reserve_band,
        reserve_score=reserve_score,
        drift_ratio=drift_ratio,
    )
    vulnerability_flags = payload.get("vulnerability_flags")
    if isinstance(vulnerability_flags, list) and vulnerability_flags and minutes < 10:
        minutes = 10
        basis.append("vulnerability_flags_present")
    if _truthy(payload.get("is_slowest")) and minutes < 5:
        minutes = 5
        basis.append("explicit_slowest_member")
    if minutes <= 0:
        return None
    return {
        "reserve_minutes": float(minutes),
        "reason": (
            "team status evidence requires using the slowest or most vulnerable "
            "member instead of average team pace"
        ),
        "candidate_basis": basis,
        "member_ref": _first_text(
            payload.get("member_ref"),
            payload.get("member_id"),
            payload.get("participant_id"),
            payload.get("subject_id"),
        ),
    }


def _reserve_minutes_from_energy_markers(
    *,
    cue_band: str | None,
    reserve_band: str | None,
    reserve_score: float | None,
    drift_ratio: float | None,
) -> tuple[float, list[str]]:
    minutes = 0.0
    basis: list[str] = []
    normalized_cue = str(cue_band or "").strip().lower()
    normalized_reserve = str(reserve_band or "").strip().lower()
    for band in (normalized_cue, normalized_reserve):
        if band in {"manual_check", "stop_and_check", "critical", "depleted"}:
            minutes = max(minutes, float(ENERGY_MANUAL_CHECK_RESERVE_MINUTES))
            basis.append(f"{band}_band")
        elif band in {"rest_suggested", "low", "very_low", "warning"}:
            minutes = max(minutes, float(ENERGY_REST_SUGGESTED_RESERVE_MINUTES))
            basis.append(f"{band}_band")
        elif band in {"slow_down", "watch"}:
            minutes = max(minutes, float(ENERGY_SLOW_DOWN_RESERVE_MINUTES))
            basis.append(f"{band}_band")
    if reserve_score is not None:
        if reserve_score <= 25:
            minutes = max(minutes, float(ENERGY_MANUAL_CHECK_RESERVE_MINUTES))
            basis.append("reserve_score_very_low")
        elif reserve_score <= 40:
            minutes = max(minutes, float(ENERGY_REST_SUGGESTED_RESERVE_MINUTES))
            basis.append("reserve_score_low")
    if drift_ratio is not None:
        if drift_ratio >= 0.18:
            minutes = max(minutes, float(ENERGY_MANUAL_CHECK_RESERVE_MINUTES))
            basis.append("heart_rate_drift_manual_check_band")
        elif drift_ratio >= 0.12:
            minutes = max(minutes, float(ENERGY_REST_SUGGESTED_RESERVE_MINUTES))
            basis.append("heart_rate_drift_rest_band")
        elif drift_ratio >= 0.08:
            minutes = max(minutes, float(ENERGY_SLOW_DOWN_RESERVE_MINUTES))
            basis.append("heart_rate_drift_watch_band")
    return minutes, list(dict.fromkeys(basis))


def _weather_daylight_needs_review(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    validation = payload.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    daylight = payload.get("daylight")
    daylight = daylight if isinstance(daylight, dict) else {}
    weather_window = payload.get("weather_window")
    weather_window = weather_window if isinstance(weather_window, dict) else {}
    return any(
        (
            bool(payload.get("human_review_required")),
            str(payload.get("status") or "") == "candidate_only",
            str(validation.get("validation_status") or "") == "human_review_required",
            str(daylight.get("source_status") or "") in {"manual_placeholder", ""},
            str(weather_window.get("source_status") or "") in {"manual_placeholder", ""},
            payload.get("authoritative_weather_computed") is False,
        )
    )


def _dark_arrival_warning_margin_minutes(payload: dict[str, Any]) -> float:
    value = _nested_number(
        payload,
        "threshold_policy",
        "daylight",
        "dark_arrival_warning_margin_min",
    )
    if value is None:
        return float(DEFAULT_UNREVIEWED_DAYLIGHT_RESERVE_MINUTES)
    return max(0.0, value)


def _plan_validation_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings = payload.get("findings")
    if not isinstance(findings, list):
        return []
    return [item for item in findings if isinstance(item, dict)]


def _nested_number(payload: dict[str, Any], *keys: str) -> float | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _float_or_none(current)


def _risk_budget_source(
    *,
    remaining_safety_buffer_minutes: float | int | str | None,
    derived_budget_source: dict[str, Any] | None,
    workspace_reserve_source: dict[str, Any],
) -> dict[str, Any]:
    if derived_budget_source is not None:
        source = dict(derived_budget_source)
        source["workspace_reserve_source"] = workspace_reserve_source
        source["reserve_sources"] = list(
            workspace_reserve_source.get("reserve_sources", [])
        )
        return source
    if remaining_safety_buffer_minutes is not None:
        return {
            "source_status": "caller_provided_normalized_evidence",
            "runtime_safety_truth": False,
            "workspace_reserve_source": workspace_reserve_source,
            "notes": [
                "Caller provided normalized buffer evidence; tool did not promote it to runtime safety truth."
            ],
        }
    return {
        "source_status": "missing_required_buffer_evidence",
        "runtime_safety_truth": False,
        "workspace_reserve_source": workspace_reserve_source,
        "notes": [
            "remaining_safety_buffer_minutes was not provided and no planned ETA fallback could be derived."
        ],
    }


def _load_planned_eta(
    root: Path,
    *,
    project: dict[str, Any],
    explicit_path: str | None,
) -> tuple[dict[str, Any], str | None]:
    candidates: list[tuple[str, Path]] = []
    if explicit_path:
        candidates.append((explicit_path, _project_path(root, explicit_path)))
    ref = project.get("planned_eta_ref")
    if isinstance(ref, str) and ref.strip():
        candidates.append((ref, _project_path(root, ref)))
    candidates.append(("outputs/planned_eta.json", root / "outputs" / "planned_eta.json"))
    seen: set[Path] = set()
    for label, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload, label
    return {}, None


def _load_first_project_json(
    root: Path,
    *,
    project: dict[str, Any],
    explicit_path: str | None,
    ref_keys: tuple[str, ...],
    fallbacks: tuple[str, ...],
) -> tuple[dict[str, Any], str | None]:
    candidates: list[tuple[str, Path]] = []
    if explicit_path:
        candidates.append((explicit_path, _project_path(root, explicit_path)))
    for key in ref_keys:
        ref = project.get(key)
        if isinstance(ref, str) and ref.strip():
            candidates.append((ref, _project_path(root, ref)))
    for fallback in fallbacks:
        candidates.append((fallback, _project_path(root, fallback)))
    seen: set[Path] = set()
    for label, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload, label
    return {}, None


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _match_eta_estimate(
    eta_payload: dict[str, Any],
    *,
    current: datetime,
    next_cp_id: str | None,
) -> dict[str, Any] | None:
    estimates = eta_payload.get("estimates")
    if not isinstance(estimates, list):
        return None
    dict_estimates = [item for item in estimates if isinstance(item, dict)]
    if next_cp_id:
        normalized_next = _normalize_identifier(next_cp_id)
        for estimate in dict_estimates:
            if normalized_next in {
                _normalize_identifier(estimate.get("to_node_name")),
                _normalize_identifier(estimate.get("estimate_id")),
                _normalize_identifier(estimate.get("source_candidate_id")),
            }:
                return estimate
    future_estimates: list[tuple[datetime, dict[str, Any]]] = []
    for estimate in dict_estimates:
        eta = _parse_datetime(str(estimate.get("eta") or ""))
        if eta is None or eta < current:
            continue
        future_estimates.append((eta, estimate))
    if not future_estimates:
        return None
    future_estimates.sort(key=lambda item: item[0])
    return future_estimates[0][1]


def _normalize_identifier(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _resolve_action(action: str | None, query: str) -> OutdoorAction:
    if action:
        normalized = action.strip().lower()
        for candidate in OutdoorAction:
            if normalized == candidate.value:
                return candidate
    text = query.lower()
    if _has_any(text, ("拍影片", "拍片", "影片", "video", "film", "架腳架")):
        return OutdoorAction.FILM
    if _has_any(text, ("拍照", "照片", "photo", "攝影", "拍攝", "很好拍")):
        return OutdoorAction.PHOTO
    if _has_any(text, ("午餐", "吃午餐", "吃飯", "lunch")):
        return OutdoorAction.LUNCH
    if _has_any(text, ("攻頂", "山頂", "summit")):
        return OutdoorAction.SUMMIT
    if _has_any(text, ("等霧", "等隊友", "等待", "wait")):
        return OutdoorAction.WAIT
    if _has_any(text, ("撤退", "折返", "下撤", "retreat")):
        return OutdoorAction.RETREAT
    if _has_any(text, ("穿雨衣", "雨衣", "rain gear")):
        return OutdoorAction.WEAR_RAIN_GEAR
    if _has_any(text, ("分隊", "分開", "split")):
        return OutdoorAction.SPLIT_TEAM
    if _has_any(text, ("渡溪", "過溪", "溪水", "cross stream")):
        return OutdoorAction.CROSS_STREAM
    if _has_any(text, ("曝露", "暴露", "邊坡", "exposed")):
        return OutdoorAction.ENTER_EXPOSED_SECTION
    if _has_any(text, ("改線", "繞去", "支線", "reroute")):
        return OutdoorAction.REROUTE
    if _has_any(text, ("休息", "rest")):
        return OutdoorAction.REST
    if _has_any(text, ("停多久", "停下", "停留", "可以停", "能不能停", "stop")):
        return OutdoorAction.STOP
    return OutdoorAction.CONTINUE


def _normalized_risk_level(level: str | None, query: str) -> str | None:
    if level and str(level).strip():
        return str(level).strip().lower()
    text = query.lower()
    if _has_any(text, ("暴漲", "落石", "滑墜", "曝露邊坡", "暴露邊坡", "溪水")):
        return "high"
    return None


def _is_high_risk_action(
    action: OutdoorAction,
    terrain_risk_level: str | None,
    query: str,
) -> bool:
    if action not in {OutdoorAction.CROSS_STREAM, OutdoorAction.ENTER_EXPOSED_SECTION}:
        return False
    if terrain_risk_level in _HIGH_RISK_LEVELS:
        return True
    return _has_any(query.lower(), ("暴漲", "濕滑", "落石", "滑墜", "曝露", "暴露"))


def _high_risk_reason(action: OutdoorAction, terrain_risk_level: str | None) -> str:
    if action == OutdoorAction.CROSS_STREAM:
        return "渡溪或進入溪谷屬高後果情境，水位與撤退窗口不確定時不得輕率授權。"
    if action == OutdoorAction.ENTER_EXPOSED_SECTION:
        return "曝露地形會放大滑墜、落石與天候風險，不適合用現場衝動決策通過。"
    return f"{_action_label(action)}目前落在高風險條件中：{terrain_risk_level or 'unknown'}。"


def _high_risk_next_action(action: OutdoorAction, next_cp_id: str | None) -> str:
    if action == OutdoorAction.CROSS_STREAM:
        return "停止進入溪谷，退回穩定安全點，必要時等待領隊、嚮導或官方資訊。"
    return _safe_next_action(action, next_cp_id)


def _budget_failure_decision(action: OutdoorAction) -> ScoutDecision:
    if action in {OutdoorAction.SUMMIT, OutdoorAction.REROUTE}:
        return ScoutDecision.CHANGE_PLAN
    return ScoutDecision.NO_GO


def _allowed_reasons(
    *,
    action: OutdoorAction,
    max_duration: int,
    budget: RiskBudget,
    current_cp_id: str | None,
    next_cp_id: str | None,
) -> list[str]:
    reasons = [
        (
            f"目前可授權風險預算約 {budget.authorized_duration_minutes} 分鐘，"
            f"{_action_label(action)}上限設定為 {max_duration} 分鐘。"
        )
    ]
    if budget.remaining_safety_buffer_minutes is not None:
        reasons.append(
            (
                f"此行為會消耗 {max_duration} 分鐘 buffer；執行後預估仍保留"
                f" {budget.buffer_after_action_minutes} 分鐘總安全 buffer。"
            )
        )
    if budget.current_delay_minutes > 0:
        reasons.append(f"目前比計畫晚約 {budget.current_delay_minutes:g} 分鐘，不能延長停留。")
    reserved = (
        budget.next_segment_uncertainty_minutes
        + budget.weather_reserve_minutes
        + budget.daylight_reserve_minutes
        + budget.retreat_reserve_minutes
        + budget.slowest_member_reserve_minutes
    )
    if reserved > 0:
        reasons.append(
            f"已先保留 {reserved:g} 分鐘給前方不確定性、天氣、日照、撤退或最慢成員。"
        )
    if current_cp_id or next_cp_id:
        reasons.append(
            "決策節點：目前 "
            f"{current_cp_id or 'unknown CP'}，下一步指向 {next_cp_id or '下一安全點'}。"
        )
    return reasons[:4]


def _allowed_next_action(action: OutdoorAction, next_cp_id: str | None) -> str:
    destination = next_cp_id or "下一個安全 CP"
    if action in {OutdoorAction.FILM, OutdoorAction.PHOTO}:
        return f"完成拍攝後直接前往 {destination}，不要追加取景或離開路線走廊。"
    if action == OutdoorAction.REST:
        return f"短休結束後重新集合，確認最慢成員狀態，再前往 {destination}。"
    if action == OutdoorAction.LUNCH:
        return f"只做短版午餐，完成後收整裝備並前往 {destination}。"
    if action == OutdoorAction.WAIT:
        return f"到時限仍未改善就放棄等待，直接前往 {destination}。"
    if action == OutdoorAction.SUMMIT:
        return "設定硬性折返時間，逾時立即放棄攻頂。"
    if action == OutdoorAction.REROUTE:
        return "只採用已知安全替代線，並在下一 CP 重新評估。"
    return f"到時限後立即離開，前往 {destination}。"


def _safe_next_action(action: OutdoorAction, next_cp_id: str | None) -> str:
    destination = next_cp_id or "下一個安全 CP"
    if action in {
        OutdoorAction.FILM,
        OutdoorAction.PHOTO,
        OutdoorAction.STOP,
        OutdoorAction.REST,
        OutdoorAction.LUNCH,
        OutdoorAction.WAIT,
    }:
        return f"不要在此停留，請先前往 {destination} 再重新評估。"
    if action == OutdoorAction.SUMMIT:
        return "不要繼續攻頂，請執行折返或改短線方案。"
    if action == OutdoorAction.REROUTE:
        return "不要臨時改線，請回到原路線或前往已知安全 CP。"
    if action == OutdoorAction.SPLIT_TEAM:
        return "不要分隊，請保持隊伍完整並前往共同安全點。"
    return f"請前往 {destination} 並重新評估。"


def _alternative_actions(action: OutdoorAction, next_cp_id: str | None) -> list[str]:
    destination = next_cp_id or "下一個安全 CP"
    if action in {OutdoorAction.FILM, OutdoorAction.PHOTO, OutdoorAction.STOP, OutdoorAction.WAIT}:
        return [f"前往 {destination} 後再停留", "取消拍攝或等待", "只在路線內側快速通過"]
    if action == OutdoorAction.REST:
        return [f"前往 {destination} 再休息", "縮短為站立補水", "改成撤退或短線"]
    if action == OutdoorAction.LUNCH:
        return [f"前往 {destination} 吃午餐", "改成行進補給", "取消長時間停留"]
    if action == OutdoorAction.SUMMIT:
        return ["立即折返", "改短線或放棄山頂停留", "在安全 CP 重新評估"]
    if action == OutdoorAction.REROUTE:
        return ["回到原路線", "只走已審核替代路線", "前往下一 CP 重新評估"]
    if action == OutdoorAction.SPLIT_TEAM:
        return ["保持隊伍完整", "由最慢成員決定節奏", "前往共同集合點"]
    if action == OutdoorAction.CROSS_STREAM:
        return ["不要渡溪", "退回安全高點", "等待官方或領隊判斷"]
    return [f"前往 {destination}", "重新評估", "撤退或改線"]


def _field_answer(permission: ContextualPermission, *, budget: RiskBudget) -> str:
    action_label = _action_label(permission.action)
    if permission.allowed and permission.max_duration_minutes is not None:
        leave_phrase = (
            f"{permission.leave_by} 前離開"
            if permission.leave_by
            else f"從現在起 {permission.max_duration_minutes} 分鐘內離開"
        )
        reason = permission.main_reasons[0] if permission.main_reasons else ""
        return (
            f"可以，最多 {permission.max_duration_minutes} 分鐘。"
            f"{leave_phrase}。{reason} {permission.next_action}"
        )
    if permission.allowed:
        reason = permission.main_reasons[0] if permission.main_reasons else ""
        return f"可以{action_label}。{reason} {permission.next_action}"
    if permission.decision == ScoutDecision.ESCALATE:
        reason = permission.main_reasons[0] if permission.main_reasons else ""
        return f"需要升級處理，不建議{action_label}。{reason} {permission.next_action}"
    reason = permission.main_reasons[0] if permission.main_reasons else ""
    if budget.remaining_safety_buffer_minutes is not None:
        return (
            f"不建議{action_label}。{permission.next_action} "
            f"{reason} 目前剩餘安全 buffer 約 {budget.remaining_safety_buffer_minutes:g} 分鐘。"
        )
    return f"不建議{action_label}。{permission.next_action} {reason}"


def _required_conditions(
    *,
    leave_by: str | None,
    max_duration: int,
    action: OutdoorAction,
) -> list[str]:
    conditions = [f"最多 {max_duration} 分鐘"]
    conditions.append(f"{leave_by} 前離開" if leave_by else "以現在時間起算，到時立即離開")
    if action in {OutdoorAction.FILM, OutdoorAction.PHOTO, OutdoorAction.STOP}:
        conditions.append("不要離開步道內側或既有路線走廊")
    conditions.append("若天氣、能見度、隊伍狀態或地形風險惡化，立即取消")
    return conditions


def _allowed_uncertainty_notes(
    *,
    current_time: str | None,
    communication_status: str | None,
    equipment_status: str | None,
) -> list[str]:
    notes = _status_uncertainty_notes(
        communication_status=communication_status,
        equipment_status=equipment_status,
    )
    if not current_time:
        notes.append("current_time not provided; leaveBy is expressed as a relative deadline.")
    return notes


def _status_uncertainty_notes(
    *,
    communication_status: str | None,
    equipment_status: str | None,
) -> list[str]:
    notes: list[str] = []
    if not communication_status:
        notes.append("communication_status not provided.")
    if not equipment_status:
        notes.append("equipment_status not provided.")
    return notes


def _residual_risk(action: OutdoorAction, terrain_risk_level: str | None) -> list[str]:
    risks = ["即使遵守時限，仍可能受天氣、地面濕滑、能見度與隊伍狀態變化影響。"]
    if action in {OutdoorAction.FILM, OutdoorAction.PHOTO}:
        risks.append("拍攝衝動可能導致追加停留或離開安全路線。")
    if terrain_risk_level:
        risks.append(f"現場地形風險標記為 {terrain_risk_level}，需保守處理。")
    return risks


def _default_location_constraint(action: OutdoorAction) -> str | None:
    if action in {OutdoorAction.FILM, OutdoorAction.PHOTO, OutdoorAction.STOP, OutdoorAction.REST, OutdoorAction.WAIT}:
        return "stay on the inner side of the trail or inside the known route corridor"
    if action == OutdoorAction.LUNCH:
        return "use only the nearest stable, low-exposure spot inside the route corridor"
    return None


def _default_weather_impact(budget: RiskBudget) -> str | None:
    if budget.weather_reserve_minutes > 0:
        return f"{budget.weather_reserve_minutes:g} minutes reserved for weather change"
    return None


def _default_daylight_impact(budget: RiskBudget) -> str | None:
    if budget.daylight_reserve_minutes > 0:
        return f"{budget.daylight_reserve_minutes:g} minutes reserved for daylight margin"
    return None


def _default_retreat_impact(budget: RiskBudget) -> str | None:
    if budget.retreat_reserve_minutes > 0:
        return f"{budget.retreat_reserve_minutes:g} minutes reserved for retreat margin"
    return None


def _default_team_pace_impact(budget: RiskBudget) -> str | None:
    if budget.slowest_member_reserve_minutes > 0:
        return f"{budget.slowest_member_reserve_minutes:g} minutes reserved for slowest member"
    return None


def _leave_by(current_time: str | None, max_duration_minutes: int) -> str | None:
    parsed = _parse_datetime(current_time)
    if parsed is None:
        return None
    return (parsed + timedelta(minutes=max_duration_minutes)).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _confidence(value: str | None, *, default: ConfidenceLevel) -> ConfidenceLevel:
    if value:
        normalized = value.strip().lower()
        for candidate in ConfidenceLevel:
            if normalized == candidate.value:
                return candidate
    return default


def _action_label(action: OutdoorAction | str) -> str:
    labels = {
        OutdoorAction.STOP: "停留",
        OutdoorAction.FILM: "拍影片",
        OutdoorAction.PHOTO: "拍照",
        OutdoorAction.REST: "休息",
        OutdoorAction.LUNCH: "吃午餐",
        OutdoorAction.SUMMIT: "攻頂",
        OutdoorAction.REROUTE: "改線",
        OutdoorAction.WAIT: "等待",
        OutdoorAction.CONTINUE: "繼續前進",
        OutdoorAction.RETREAT: "撤退",
        OutdoorAction.WEAR_RAIN_GEAR: "穿雨具",
        OutdoorAction.SPLIT_TEAM: "分隊",
        OutdoorAction.CROSS_STREAM: "渡溪",
        OutdoorAction.ENTER_EXPOSED_SECTION: "進入曝露地形",
    }
    try:
        return labels[OutdoorAction(str(action))]
    except ValueError:
        return str(action)


def _warnings(
    *,
    missing_fields: list[str],
    communication_status: str | None,
    equipment_status: str | None,
    risk_budget_source: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if missing_fields:
        warnings.append("Missing field evidence forced a conservative permission decision.")
    if risk_budget_source.get("source_status") == "derived_from_planned_eta_candidate":
        warnings.append(
            "Risk budget was derived from candidate planned ETA, not reviewed live safety truth."
        )
    if risk_budget_source.get("reserve_sources"):
        warnings.append(
            "Workspace reserve was deducted from planned ETA slack."
        )
    if not communication_status:
        warnings.append("communication_status missing; no team/contact assumption was made.")
    if not equipment_status:
        warnings.append("equipment_status missing; no equipment readiness assumption was made.")
    return warnings


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            text = str(value).strip()
            if text:
                return text
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _nonnegative_float(value: Any) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        return 0.0
    return max(0.0, parsed)


def _has_any(text: str, fragments: tuple[str, ...]) -> bool:
    normalized = str(text or "").lower().replace(" ", "")
    return any(fragment.lower().replace(" ", "") in normalized for fragment in fragments)


def _closed_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "candidate_only": True,
        "model_synthesis_performed": False,
        "model_output_is_runtime_truth": False,
        "live_safety_api_calls_allowed": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "hardware_control_performed": False,
        "workspace_file_write_allowed": False,
    }
