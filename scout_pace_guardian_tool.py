from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


PACE_GUARDIAN_TOOL_ID = "scout.ai.pace_guardian.assess.v0"
PACE_GUARDIAN_OUTPUT_KIND = "scout_ai_pace_guardian_tool_output"
PACE_GUARDIAN_REQUIRED_FIELDS = ("project_root",)
PACE_GUARDIAN_OPTIONAL_FIELDS = (
    "team_members",
    "current_time",
    "next_cp_id",
    "minutes_to_next_cp",
    "current_delay_minutes",
    "leader_accepts_slowest_basis",
    "team_rest_sync",
    "team_status_path",
    "resource_plan_path",
    "planned_eta_path",
    "energy_vitals_path",
    "readiness_report_path",
)

LOW_RESERVE_MINUTES = 15.0
PACE_GAP_RATIO_WARNING = 1.45
PACE_GAP_RATIO_CHANGE_PLAN = 1.8
DELAY_WARNING_MINUTES = 15.0
DELAY_CHANGE_PLAN_MINUTES = 25.0


def assess_scout_pace_guardian(
    project_root: Path | str,
    *,
    query: str = "",
    team_members: list[Any] | None = None,
    current_time: str | None = None,
    next_cp_id: str | None = None,
    minutes_to_next_cp: float | int | str | None = None,
    current_delay_minutes: float | int | str | None = None,
    leader_accepts_slowest_basis: bool | str | None = None,
    team_rest_sync: str | None = None,
    team_status_path: str | None = None,
    resource_plan_path: str | None = None,
    planned_eta_path: str | None = None,
    energy_vitals_path: str | None = None,
    readiness_report_path: str | None = None,
) -> dict[str, Any]:
    """Assess Scout Readiness & Pace Fit without averaging away weak links."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    team_status, team_status_source = _load_optional_json(
        root,
        explicit_path=team_status_path,
        project=project,
        project_ref_key="team_status_ref",
        default_refs=("outputs/team_status.json", "outputs/pace_guardian/team_status.json"),
        source_kind="team_status",
        source_report=source_report,
    )
    resource_plan, resource_plan_source = _load_optional_json(
        root,
        explicit_path=resource_plan_path,
        project=project,
        project_ref_key="resource_plan_ref",
        default_refs=("outputs/resource_plan.json",),
        source_kind="resource_plan",
        source_report=source_report,
    )
    planned_eta, planned_eta_source = _load_optional_json(
        root,
        explicit_path=planned_eta_path,
        project=project,
        project_ref_key="planned_eta_ref",
        default_refs=("outputs/planned_eta.json",),
        source_kind="planned_eta",
        source_report=source_report,
    )
    energy_vitals, energy_vitals_source = _load_optional_json(
        root,
        explicit_path=energy_vitals_path,
        project=project,
        project_ref_key="energy_vitals_ref",
        default_refs=(
            "outputs/energy_vitals.json",
            "outputs/energy/scout_ai_energy_vitals_tool_output.json",
        ),
        source_kind="energy_vitals",
        source_report=source_report,
    )
    readiness_report, readiness_source = _load_optional_json(
        root,
        explicit_path=readiness_report_path,
        project=project,
        project_ref_key="readiness_report_ref",
        default_refs=("outputs/readiness_report.json",),
        source_kind="readiness_report",
        source_report=source_report,
    )

    members = _member_profiles(team_members, team_status=team_status, resource_plan=resource_plan)
    if not members and isinstance(energy_vitals, dict):
        members = _members_from_energy_vitals(energy_vitals)

    eta_minutes, eta_source = _minutes_to_next_cp(
        explicit_minutes=minutes_to_next_cp,
        current_time=current_time,
        next_cp_id=next_cp_id,
        planned_eta=planned_eta,
        planned_eta_source=planned_eta_source,
    )
    team_context = _team_context(
        team_status=team_status,
        leader_accepts_slowest_basis=leader_accepts_slowest_basis,
        team_rest_sync=team_rest_sync,
    )
    current_delay = _float_or_none(current_delay_minutes)
    if current_delay is None:
        current_delay = _nested_float(team_status, "schedule", "current_delay_minutes")
    if current_delay is None:
        current_delay = _nested_float(team_status, "progress", "current_delay_minutes")

    pace_fit = _pace_fit(
        members,
        current_delay_minutes=current_delay,
        minutes_to_next_cp=eta_minutes,
        leader_accepts_slowest_basis=team_context["leader_accepts_slowest_basis"],
        team_rest_sync=team_context["team_rest_sync"],
        energy_vitals=energy_vitals,
    )
    missing_fields = _missing_fields(members, pace_fit=pace_fit)
    decision = _decision(pace_fit, missing_fields=missing_fields)
    answerability = (
        "pace_fit_missing_required_fields"
        if missing_fields
        else "pace_fit_decision_available"
    )
    field_answer = _field_answer(
        decision=decision,
        answerability=answerability,
        pace_fit=pace_fit,
        missing_fields=missing_fields,
    )
    schedule_pressure = {
        "current_delay_minutes": current_delay,
        "minutes_to_next_cp": eta_minutes,
        "next_cp_id": next_cp_id,
        "eta_source": eta_source,
    }
    decision_output = _decision_output(
        decision=decision,
        pace_fit=pace_fit,
        schedule_pressure=schedule_pressure,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )

    return {
        "tool_id": PACE_GUARDIAN_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_pace_guardian",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "pace_guardian": {
            "role": "Pace Guardian",
            "basis": "slowest_member_and_most_vulnerable_link",
            "average_pace_used": False,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision,
            "decision_output": decision_output,
            "next_action": pace_fit["next_action"],
            "guardrails": [
                "Do not use team average pace to hide the slowest member.",
                "Use contextual permission for bounded stop/rest/lunch duration.",
                "Escalate through approved safety flow before any outbound or SOS action.",
            ],
        },
        "team_pace_fit": pace_fit,
        "schedule_pressure": schedule_pressure,
        "team_context": team_context,
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "pace guardian decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "slowest_member": pace_fit.get("slowest_member"),
                "fastest_member": pace_fit.get("fastest_member"),
                "pace_gap_ratio": pace_fit.get("pace_gap_ratio"),
                "main_reasons": pace_fit["main_reasons"],
                "next_action": pace_fit["next_action"],
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7 Readiness & Pace Fit",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7.3 Team Pace Fit",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.1 Pace Guardian",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 member experience and pace inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "boundary": _closed_boundary(),
        "debug_sources": {
            "team_status_source": team_status_source,
            "resource_plan_source": resource_plan_source,
            "planned_eta_source": planned_eta_source,
            "energy_vitals_source": energy_vitals_source,
            "readiness_source": readiness_source,
            "readiness_status": readiness_report.get("status")
            if isinstance(readiness_report, dict)
            else None,
        },
    }


def _pace_fit(
    members: list[dict[str, Any]],
    *,
    current_delay_minutes: float | None,
    minutes_to_next_cp: float | None,
    leader_accepts_slowest_basis: bool | None,
    team_rest_sync: str | None,
    energy_vitals: dict[str, Any],
) -> dict[str, Any]:
    pace_members = [member for member in members if _float_or_none(member.get("pace_mps"))]
    fastest = max(
        pace_members,
        key=lambda member: float(member.get("pace_mps") or 0.0),
        default=None,
    )
    slowest = min(
        pace_members,
        key=lambda member: float(member.get("pace_mps") or math.inf),
        default=None,
    )
    pace_gap_ratio = None
    if fastest and slowest and float(slowest["pace_mps"]) > 0:
        pace_gap_ratio = round(float(fastest["pace_mps"]) / float(slowest["pace_mps"]), 2)

    vulnerable_members = [
        _member_public_summary(member)
        for member in members
        if member.get("vulnerable_link") is True
    ]
    main_reasons: list[str] = []
    required_conditions: list[str] = []
    warnings: list[str] = []

    if not members:
        main_reasons.append("缺少隊伍狀態，不能評估最慢者。")
        required_conditions.append("Provide team_status or member pace profiles.")
    elif not pace_members:
        main_reasons.append("隊伍資料存在，但缺少每位成員的可靠腳程或速度。")
        required_conditions.append("Provide per-member pace_mps or equivalent pace profile.")

    if pace_gap_ratio is not None:
        if pace_gap_ratio >= PACE_GAP_RATIO_CHANGE_PLAN:
            main_reasons.append(
                f"最快與最慢腳程比約 {pace_gap_ratio}x，不能用平均腳程規劃。"
            )
        elif pace_gap_ratio >= PACE_GAP_RATIO_WARNING:
            warnings.append(f"隊伍腳程差約 {pace_gap_ratio}x，需以最慢者控速。")

    slowest_reserve = _float_or_none(slowest.get("reserve_minutes")) if slowest else None
    if slowest and slowest_reserve is not None:
        if slowest_reserve < LOW_RESERVE_MINUTES:
            main_reasons.append(
                f"最慢者剩餘儲備約 {slowest_reserve:.0f} 分鐘，低於 Scout 保守門檻。"
            )
        if minutes_to_next_cp is not None and slowest_reserve < minutes_to_next_cp:
            main_reasons.append(
                f"最慢者儲備不足以支撐到下一個 CP（約 {minutes_to_next_cp:.0f} 分鐘）。"
            )

    if current_delay_minutes is not None:
        if current_delay_minutes >= DELAY_CHANGE_PLAN_MINUTES:
            main_reasons.append(f"目前已落後約 {current_delay_minutes:.0f} 分鐘。")
        elif current_delay_minutes >= DELAY_WARNING_MINUTES:
            warnings.append(f"目前落後約 {current_delay_minutes:.0f} 分鐘。")

    fatigue_reasons = _fatigue_reasons(members, energy_vitals=energy_vitals)
    main_reasons.extend(fatigue_reasons)

    if vulnerable_members:
        warnings.append("隊伍存在較脆弱環節，節奏必須以該成員可恢復性為準。")
    if leader_accepts_slowest_basis is False:
        main_reasons.append("領隊/決策者尚未確認願意以最慢者為基準。")
        required_conditions.append("Leader confirms slowest-member pacing basis.")
    elif leader_accepts_slowest_basis is None and members:
        warnings.append("尚未確認決策者是否願意以最慢者為基準。")
    if team_rest_sync and team_rest_sync.lower() in {"mismatched", "split", "unknown"}:
        warnings.append("隊伍休息節奏不一致，需避免快慢組自然分裂。")

    decision_basis = "slowest_member" if slowest else "missing_slowest_member"
    if not main_reasons and warnings:
        next_action = "以最慢者控速，保留午餐/休息前移選項，下一個 CP 前重新檢查。"
    elif main_reasons:
        next_action = _change_plan_next_action(query_reasons=main_reasons)
    else:
        next_action = "照計畫行進，但持續以最慢者速度與休息節奏檢查下一個 CP。"

    return {
        "decision_basis": decision_basis,
        "member_count": len(members),
        "members_with_pace_count": len(pace_members),
        "average_pace_used": False,
        "slowest_member": _member_public_summary(slowest) if slowest else None,
        "fastest_member": _member_public_summary(fastest) if fastest else None,
        "pace_gap_ratio": pace_gap_ratio,
        "vulnerable_members": vulnerable_members,
        "main_reasons": main_reasons,
        "warnings": warnings,
        "required_conditions": required_conditions,
        "next_action": next_action,
    }


def _decision(pace_fit: dict[str, Any], *, missing_fields: list[str]) -> str:
    if missing_fields:
        return "NO_GO"
    reasons = pace_fit.get("main_reasons")
    reasons = reasons if isinstance(reasons, list) else []
    if any("不足以支撐到下一個 CP" in str(reason) for reason in reasons):
        return "CHANGE_PLAN"
    if any("低於 Scout 保守門檻" in str(reason) for reason in reasons):
        return "CHANGE_PLAN"
    if any("領隊/決策者尚未確認" in str(reason) for reason in reasons):
        return "CHANGE_PLAN"
    if any("不能用平均腳程" in str(reason) for reason in reasons):
        return "CONDITIONAL_GO"
    if reasons:
        return "CONDITIONAL_GO"
    return "GO"


def _field_answer(
    *,
    decision: str,
    answerability: str,
    pace_fit: dict[str, Any],
    missing_fields: list[str],
) -> str:
    if missing_fields:
        return (
            "腳程守門員：目前不建議用平均腳程做決策。缺少 "
            + "、".join(missing_fields)
            + "；Scout 需要每位成員腳程/儲備，才能判斷是否前移午餐、縮短行程或撤退。"
        )
    slowest = pace_fit.get("slowest_member")
    slowest_label = (
        str(slowest.get("label") or slowest.get("member_id"))
        if isinstance(slowest, dict)
        else "最慢成員"
    )
    reasons = pace_fit.get("main_reasons") or pace_fit.get("warnings") or []
    reason_text = "；".join(str(reason) for reason in reasons[:2]) or "目前未見明確腳程缺口。"
    return (
        f"腳程守門員：建議 {decision}。以 {slowest_label} 為基準，不使用平均腳程；"
        f"{reason_text} 下一步：{pace_fit['next_action']} "
        "此為 Pace Guardian 候選判斷，不是 runtime safety truth；停留或午餐可停多久仍需 contextual permission 工具。"
    )


def _decision_output(
    *,
    decision: str,
    pace_fit: dict[str, Any],
    schedule_pressure: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(pace_fit=pace_fit, missing_fields=missing_fields)
    uncertainty_notes = [f"Missing field: {field}" for field in missing_fields]
    required_conditions = _pace_required_conditions(
        pace_fit=pace_fit,
        missing_fields=missing_fields,
    )
    alternatives = _pace_alternative_actions(decision=decision, pace_fit=pace_fit)
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision, pace_fit=pace_fit),
        "reason": " / ".join(reasons[:2]),
        "nextStep": pace_fit["next_action"],
    }
    second_layer = {
        "details": _decision_details(
            pace_fit=pace_fit,
            schedule_pressure=schedule_pressure,
            field_answer=field_answer,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Pace guidance is candidate-only and based on available member profiles.",
            "Actual stop/lunch duration still requires contextual permission.",
            "No runtime safety truth was created.",
        ],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
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
        "action": "pace_adjustment",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "scheduleDelayMinutes": schedule_pressure.get("current_delay_minutes"),
            "minutesToNextCp": schedule_pressure.get("minutes_to_next_cp"),
            "teamPaceImpact": "Slowest-member basis; team average pace was not used.",
            "retreatImpact": "If pace pressure persists, shorten route or turn around before buffer collapse.",
        },
        "nextAction": pace_fit["next_action"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": required_conditions,
        "alternativeActions": alternatives,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7 Readiness & Pace Fit",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.1 Pace Guardian",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_reasons(
    *, pace_fit: dict[str, Any], missing_fields: list[str]
) -> list[str]:
    reasons = _str_list(pace_fit.get("main_reasons"))
    if not reasons:
        reasons = _str_list(pace_fit.get("warnings"))
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    if not reasons:
        reasons.append("目前未見明確腳程缺口，但仍須以最慢者為基準。")
    return _dedupe(reasons)


def _pace_required_conditions(
    *, pace_fit: dict[str, Any], missing_fields: list[str]
) -> list[str]:
    required = _str_list(pace_fit.get("required_conditions"))
    required.extend(f"Provide {field}." for field in missing_fields)
    if not required and pace_fit.get("decision_basis") == "slowest_member":
        required.append("Continue using slowest-member pace basis at the next CP.")
    return _dedupe(required)


def _pace_alternative_actions(*, decision: str, pace_fit: dict[str, Any]) -> list[str]:
    alternatives = [str(pace_fit["next_action"])]
    if decision in {"CHANGE_PLAN", "NO_GO"}:
        alternatives.extend(
            [
                "前移午餐或休息點，不推進到原定下一個 CP。",
                "改短版或折返，避免用平均腳程消耗回程 buffer。",
            ]
        )
    else:
        alternatives.extend(
            [
                "保留午餐/休息前移選項。",
                "下一個 CP 前重新檢查最慢者儲備與疲勞。",
            ]
        )
    return _dedupe(alternatives)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "NO_GO":
        return "不建議用目前腳程資料繼續判斷。"
    if decision == "CHANGE_PLAN":
        return "不建議照原計畫推進。"
    if decision == "CONDITIONAL_GO":
        return "可繼續，但必須以最慢者控速。"
    if decision == "GO" and allowed:
        return "可照計畫行進。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str, pace_fit: dict[str, Any]) -> str:
    if decision in {"NO_GO", "CHANGE_PLAN"}:
        return "不要用平均腳程推進；前移午餐/休息點，必要時改短版或折返。"
    if decision == "CONDITIONAL_GO":
        return "只能以最慢者與最脆弱成員為基準；任何停留仍需 contextual permission。"
    if pace_fit.get("decision_basis") == "slowest_member":
        return "維持最慢者基準；下一個 CP 前重新檢查儲備與休息節奏。"
    return "不得把平均腳程當成現場授權。"


def _decision_details(
    *,
    pace_fit: dict[str, Any],
    schedule_pressure: dict[str, Any],
    field_answer: str,
) -> list[str]:
    details = [field_answer]
    slowest = pace_fit.get("slowest_member")
    if isinstance(slowest, dict):
        details.append(
            "最慢者："
            + str(slowest.get("label") or slowest.get("member_id"))
            + f"，reserve_minutes={slowest.get('reserve_minutes')}"
        )
    fastest = pace_fit.get("fastest_member")
    if isinstance(fastest, dict):
        details.append(
            "最快者："
            + str(fastest.get("label") or fastest.get("member_id"))
            + f"，pace_mps={fastest.get('pace_mps')}"
        )
    if pace_fit.get("pace_gap_ratio") is not None:
        details.append(f"pace_gap_ratio={pace_fit.get('pace_gap_ratio')}")
    if schedule_pressure.get("current_delay_minutes") is not None:
        details.append(
            f"current_delay_minutes={schedule_pressure.get('current_delay_minutes')}"
        )
    if schedule_pressure.get("minutes_to_next_cp") is not None:
        details.append(
            f"minutes_to_next_cp={schedule_pressure.get('minutes_to_next_cp')}"
        )
    return details


def _member_profiles(
    direct_members: list[Any] | None,
    *,
    team_status: dict[str, Any],
    resource_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_members: list[Any] = []
    if isinstance(direct_members, list) and direct_members:
        raw_members = direct_members
    elif isinstance(team_status, dict):
        raw_members = _first_list(
            team_status.get("members"),
            team_status.get("team_members"),
            team_status.get("member_status"),
        )
    if not raw_members and isinstance(resource_plan, dict):
        raw_members = _first_list(resource_plan.get("team_members"))

    members = []
    for index, raw in enumerate(raw_members):
        if not isinstance(raw, dict):
            continue
        conditions = _str_list(
            _first_present(
                raw.get("conditions"),
                raw.get("condition_flags"),
                raw.get("self_reported_conditions"),
            )
        )
        fatigue_band = str(
            _first_present(raw.get("fatigue_band"), raw.get("fatigue"), "")
        ).strip()
        pace = _float_or_none(
            _first_present(
                raw.get("pace_mps"),
                raw.get("current_pace_mps"),
                raw.get("planned_pace_mps"),
                raw.get("moving_speed_mps"),
                raw.get("speed_mps"),
            )
        )
        reserve = _float_or_none(
            _first_present(
                raw.get("reserve_minutes"),
                raw.get("remaining_reserve_minutes"),
                raw.get("slowest_member_reserve_minutes"),
            )
        )
        member = {
            "member_id": str(raw.get("member_id") or raw.get("id") or f"member_{index + 1}"),
            "label": str(raw.get("display_label") or raw.get("label") or raw.get("name") or raw.get("member_id") or f"member_{index + 1}"),
            "role": raw.get("role"),
            "pace_mps": pace,
            "reserve_minutes": reserve,
            "fatigue_band": fatigue_band or None,
            "rest_need_minutes": _float_or_none(
                _first_present(raw.get("rest_need_minutes"), raw.get("needed_rest_minutes"))
            ),
            "first_time_similar_route": _bool_or_none(
                _first_present(
                    raw.get("first_time_similar_route"),
                    raw.get("first_time_route"),
                    raw.get("first_time_on_route_type"),
                )
            ),
            "conditions": conditions,
            "review_state": _nested(raw, "review", "review_state") or raw.get("review_state"),
        }
        member["vulnerable_link"] = _is_vulnerable_member(member)
        members.append(member)
    return members


def _members_from_energy_vitals(energy_vitals: dict[str, Any]) -> list[dict[str, Any]]:
    provided = energy_vitals.get("provided_fields")
    provided = provided if isinstance(provided, dict) else {}
    advisory = energy_vitals.get("advisory")
    advisory = advisory if isinstance(advisory, dict) else {}
    subject_id = provided.get("subject_id")
    if not subject_id:
        return []
    return [
        {
            "member_id": str(subject_id),
            "label": str(subject_id),
            "role": "individual",
            "pace_mps": _float_or_none(provided.get("pace_mps")),
            "reserve_minutes": None,
            "fatigue_band": advisory.get("cue_band") or provided.get("reserve_band"),
            "rest_need_minutes": None,
            "first_time_similar_route": None,
            "conditions": [],
            "review_state": None,
            "vulnerable_link": str(advisory.get("cue_band") or "").lower()
            in {"rest_suggested", "manual_check", "slow_down"},
        }
    ]


def _team_context(
    *,
    team_status: dict[str, Any],
    leader_accepts_slowest_basis: bool | str | None,
    team_rest_sync: str | None,
) -> dict[str, Any]:
    resolved_accepts = _bool_or_none(leader_accepts_slowest_basis)
    if resolved_accepts is None:
        resolved_accepts = _bool_or_none(
            _first_present(
                team_status.get("leader_accepts_slowest_basis"),
                _nested(team_status, "governance", "leader_accepts_slowest_basis"),
            )
        )
    resolved_rest_sync = team_rest_sync
    if resolved_rest_sync is None:
        resolved_rest_sync = str(
            _first_present(
                team_status.get("team_rest_sync"),
                team_status.get("rest_sync"),
                _nested(team_status, "rest", "sync"),
                "",
            )
        ).strip() or None
    return {
        "leader_accepts_slowest_basis": resolved_accepts,
        "team_rest_sync": resolved_rest_sync,
    }


def _missing_fields(
    members: list[dict[str, Any]],
    *,
    pace_fit: dict[str, Any],
) -> list[str]:
    missing = []
    if not members:
        missing.append("team_status_or_member_profiles")
    if members and not pace_fit.get("members_with_pace_count"):
        missing.append("member_pace_profile")
    return missing


def _fatigue_reasons(
    members: list[dict[str, Any]],
    *,
    energy_vitals: dict[str, Any],
) -> list[str]:
    reasons = []
    fatigue_terms = {"tired", "very_tired", "rest_suggested", "manual_check", "slow_down", "疲勞", "很累", "太累"}
    for member in members:
        band = str(member.get("fatigue_band") or "").lower()
        rest_need = _float_or_none(member.get("rest_need_minutes"))
        if band in fatigue_terms or (rest_need is not None and rest_need >= 10):
            reasons.append(
                f"{member.get('label')} 有疲勞/休息需求訊號，需前移休息或降低配速。"
            )
    advisory = energy_vitals.get("advisory") if isinstance(energy_vitals, dict) else None
    if isinstance(advisory, dict):
        cue_band = str(advisory.get("cue_band") or "").lower()
        if cue_band in {"rest_suggested", "manual_check", "slow_down"}:
            reasons.append("穿戴式裝置候選 advisory 顯示需要放慢或休息。")
    return reasons


def _change_plan_next_action(*, query_reasons: list[str]) -> str:
    if any("下一個 CP" in reason for reason in query_reasons):
        return "不要推進到原定下一個 CP；前移休息/午餐點，評估短版或撤退路線。"
    if any("剩餘儲備" in reason for reason in query_reasons):
        return "立刻降速並安排短休；若 10-15 分鐘內未恢復，改短版或撤退。"
    if any("領隊/決策者" in reason for reason in query_reasons):
        return "先確認領隊採用最慢者基準，再決定是否繼續、縮短或分段休息。"
    return "以最慢者為基準重算下一個 CP；必要時前移午餐、縮短行程或撤退。"


def _minutes_to_next_cp(
    *,
    explicit_minutes: float | int | str | None,
    current_time: str | None,
    next_cp_id: str | None,
    planned_eta: dict[str, Any],
    planned_eta_source: str | None,
) -> tuple[float | None, str | None]:
    direct = _float_or_none(explicit_minutes)
    if direct is not None:
        return direct, "caller_provided_minutes_to_next_cp"
    if not current_time or not next_cp_id or not isinstance(planned_eta, dict):
        return None, None
    observed = _parse_datetime(current_time)
    if observed is None:
        return None, None
    estimates = planned_eta.get("estimates")
    if not isinstance(estimates, list):
        return None, None
    normalized_cp = str(next_cp_id).strip().lower()
    for estimate in estimates:
        if not isinstance(estimate, dict):
            continue
        names = {
            str(estimate.get("to_node_name") or "").strip().lower(),
            str(estimate.get("estimate_id") or "").strip().lower(),
        }
        if normalized_cp not in names:
            continue
        eta = _parse_datetime(str(estimate.get("eta") or ""))
        if eta is None:
            continue
        return max(0.0, math.ceil((eta - observed).total_seconds() / 60.0)), planned_eta_source
    return None, None


def _member_public_summary(member: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(member, dict):
        return None
    return {
        "member_id": member.get("member_id"),
        "label": member.get("label"),
        "role": member.get("role"),
        "pace_mps": member.get("pace_mps"),
        "reserve_minutes": member.get("reserve_minutes"),
        "fatigue_band": member.get("fatigue_band"),
        "first_time_similar_route": member.get("first_time_similar_route"),
        "vulnerable_link": member.get("vulnerable_link"),
        "review_state": member.get("review_state"),
    }


def _is_vulnerable_member(member: dict[str, Any]) -> bool:
    conditions = {str(item).lower() for item in member.get("conditions") or []}
    if conditions & {
        "knee",
        "knee_pain",
        "asthma",
        "sleep_debt",
        "low_blood_sugar",
        "anxiety",
        "altitude",
        "injury",
        "膝蓋",
        "氣喘",
        "睡眠不足",
        "低血糖",
        "焦慮",
        "高山症",
        "受傷",
    }:
        return True
    fatigue = str(member.get("fatigue_band") or "").lower()
    if fatigue in {"tired", "very_tired", "rest_suggested", "manual_check", "很累", "太累"}:
        return True
    if member.get("first_time_similar_route") is True:
        return True
    reserve = _float_or_none(member.get("reserve_minutes"))
    return reserve is not None and reserve < LOW_RESERVE_MINUTES


def _load_optional_json(
    root: Path,
    *,
    explicit_path: str | None,
    project: dict[str, Any],
    project_ref_key: str,
    default_refs: tuple[str, ...],
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    refs = []
    if explicit_path:
        refs.append(explicit_path)
    project_ref = project.get(project_ref_key)
    if project_ref:
        refs.append(str(project_ref))
    refs.extend(default_refs)
    for ref in refs:
        path = Path(ref)
        candidate = path if path.is_absolute() else root / path
        if not candidate.exists():
            continue
        payload = _load_json_object(candidate)
        source_path = _relpath(candidate, root)
        source_report.append(_source_report(source_kind, source_path, payload, status="loaded"))
        return payload, source_path
    source_report.append(_source_report(source_kind, refs[0] if refs else None, {}, status="missing"))
    return {}, None


def _source_report(
    source_kind: str,
    source_path: str | None,
    payload: dict[str, Any],
    *,
    status: str,
) -> dict[str, Any]:
    loaded_count = 0
    if status == "loaded":
        if isinstance(payload.get("members"), list):
            loaded_count = len(payload["members"])
        elif isinstance(payload.get("team_members"), list):
            loaded_count = len(payload["team_members"])
        elif isinstance(payload.get("estimates"), list):
            loaded_count = len(payload["estimates"])
        elif payload:
            loaded_count = 1
    return {
        "source_kind": source_kind,
        "status": status,
        "source_path": source_path or source_kind,
        "loaded_count": loaded_count,
        "raw_payloads_embedded": False,
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _nested(payload: dict[str, Any], object_key: str, value_key: str) -> Any:
    nested = payload.get(object_key)
    if not isinstance(nested, dict):
        return None
    return nested.get(value_key)


def _nested_float(payload: dict[str, Any], object_key: str, value_key: str) -> float | None:
    return _float_or_none(_nested(payload, object_key, value_key))


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return value
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return parsed


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "accepted"}:
            return True
        if normalized in {"false", "0", "no", "n", "rejected"}:
            return False
    return None


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
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
