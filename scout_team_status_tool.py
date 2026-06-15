from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


TEAM_STATUS_TOOL_ID = "scout.ai.team_status.assess.v0"
TEAM_STATUS_OUTPUT_KIND = "scout_ai_team_status_tool_output"
TEAM_STATUS_REQUIRED_FIELDS = ("project_root",)
TEAM_STATUS_OPTIONAL_FIELDS = (
    "team_status_path",
    "resource_plan_path",
    "remote_contact_summary_path",
    "team_members",
    "communication_status",
    "checkin_overdue_minutes",
    "planned_checkin_interval_minutes",
    "rendezvous_point",
    "split_team",
    "all_accounted_for",
    "last_heard_minutes",
)

DEFAULT_CHECKIN_INTERVAL_MINUTES = 30.0
OVERDUE_WARNING_MINUTES = 15.0
OVERDUE_ESCALATE_MINUTES = 45.0


def assess_scout_team_status(
    project_root: Path | str,
    *,
    query: str = "",
    team_status_path: str | None = None,
    resource_plan_path: str | None = None,
    remote_contact_summary_path: str | None = None,
    team_members: list[Any] | None = None,
    communication_status: str | None = None,
    checkin_overdue_minutes: float | int | str | None = None,
    planned_checkin_interval_minutes: float | int | str | None = None,
    rendezvous_point: str | None = None,
    split_team: bool | str | None = None,
    all_accounted_for: bool | str | None = None,
    last_heard_minutes: float | int | str | None = None,
) -> dict[str, Any]:
    """Assess team status and remote-contact governance without sending messages."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    team_status, team_status_source = _load_optional_json(
        root,
        explicit_path=team_status_path,
        project=project,
        project_ref_keys=("team_status_ref", "team_guardian_ref"),
        default_refs=("outputs/team_status.json", "outputs/team_guardian.json"),
        source_kind="team_status",
        source_report=source_report,
    )
    resource_plan, resource_plan_source = _load_optional_json(
        root,
        explicit_path=resource_plan_path,
        project=project,
        project_ref_keys=("resource_plan_ref",),
        default_refs=("outputs/resource_plan.json",),
        source_kind="resource_plan",
        source_report=source_report,
    )
    remote_contact, remote_contact_source = _load_optional_json(
        root,
        explicit_path=remote_contact_summary_path,
        project=project,
        project_ref_keys=("remote_contact_summary_ref",),
        default_refs=("outputs/remote_contact_summary.json",),
        source_kind="remote_contact_summary",
        source_report=source_report,
    )

    direct = {
        "communication_status": communication_status,
        "checkin_overdue_minutes": _float_or_none(checkin_overdue_minutes),
        "planned_checkin_interval_minutes": _float_or_none(
            planned_checkin_interval_minutes
        ),
        "rendezvous_point": rendezvous_point,
        "split_team": _bool_or_none(split_team),
        "all_accounted_for": _bool_or_none(all_accounted_for),
        "last_heard_minutes": _float_or_none(last_heard_minutes),
    }
    team_state = _team_state(
        direct=direct,
        direct_members=team_members,
        team_status=team_status,
        resource_plan=resource_plan,
        remote_contact=remote_contact,
    )
    missing_fields = _missing_fields(team_state)
    governance = _governance(team_state=team_state, missing_fields=missing_fields)
    decision = _decision(governance=governance, missing_fields=missing_fields)
    answerability = (
        "team_status_missing_required_fields"
        if missing_fields
        else "team_status_decision_available"
    )
    field_answer = _field_answer(
        decision=decision,
        governance=governance,
        missing_fields=missing_fields,
    )
    decision_output = _decision_output(
        decision=decision,
        governance=governance,
        team_state=team_state,
        missing_fields=missing_fields,
        field_answer=field_answer,
    )

    return {
        "artifact_kind": TEAM_STATUS_OUTPUT_KIND,
        "tool_id": TEAM_STATUS_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_team_status_guardian",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "team_status_guardian": {
            "role": "Team Status / Remote Contact Governance",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "outbound_send_performed": False,
            "decision": decision,
            "decision_output": decision_output,
            "critical_gaps": governance["critical_gaps"],
            "warning_gaps": governance["warning_gaps"],
            "required_conditions": governance["required_conditions"],
            "alternative_actions": governance["alternative_actions"],
            "next_action": governance["next_action"],
        },
        "team_status": team_state,
        "team_governance": governance,
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "team status decision",
                "decision": decision,
                "decision_output": decision_output,
                "answerability": answerability,
                "critical_gaps": governance["critical_gaps"],
                "warning_gaps": governance["warning_gaps"],
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
                "outbound_send_performed": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7.3 Team Pace Fit",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 team and remote-contact inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route team status recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 required development standards",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP team and conservative missing-evidence behavior",
        ],
        "boundary": _closed_boundary(),
        "debug_sources": {
            "team_status_source": team_status_source,
            "resource_plan_source": resource_plan_source,
            "remote_contact_source": remote_contact_source,
        },
    }


def _team_state(
    *,
    direct: dict[str, Any],
    direct_members: list[Any] | None,
    team_status: dict[str, Any],
    resource_plan: dict[str, Any],
    remote_contact: dict[str, Any],
) -> dict[str, Any]:
    members = _member_summaries(direct_members, team_status=team_status, resource_plan=resource_plan)
    if direct.get("last_heard_minutes") is not None and len(members) == 1:
        members[0]["last_heard_minutes"] = direct["last_heard_minutes"]
    communication_status = _first_text(
        direct.get("communication_status"),
        team_status.get("communication_status"),
        _nested(team_status, "communication", "status"),
    )
    split_team = _first_bool(
        direct.get("split_team"),
        team_status.get("split_team"),
        _nested(team_status, "team", "split_team"),
    )
    all_accounted_for = _first_bool(
        direct.get("all_accounted_for"),
        team_status.get("all_accounted_for"),
        _nested(team_status, "team", "all_accounted_for"),
    )
    checkin_overdue = _first_float(
        direct.get("checkin_overdue_minutes"),
        team_status.get("checkin_overdue_minutes"),
        _nested(team_status, "checkin", "overdue_minutes"),
    )
    planned_interval = _first_float(
        direct.get("planned_checkin_interval_minutes"),
        team_status.get("planned_checkin_interval_minutes"),
        _nested(team_status, "checkin", "planned_interval_minutes"),
    )
    rendezvous_point = _first_text(
        direct.get("rendezvous_point"),
        team_status.get("rendezvous_point"),
        _nested(team_status, "rendezvous", "point"),
    )
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "member_count": len(members),
        "members": members,
        "member_review_states": sorted(
            {
                str(member.get("review_state"))
                for member in members
                if member.get("review_state")
            }
        ),
        "members_missing_last_heard": [
            member["member_id"]
            for member in members
            if member.get("last_heard_minutes") is None
        ],
        "members_not_accounted_for": [
            member["member_id"]
            for member in members
            if member.get("accounted_for") is False
            or str(member.get("position_status") or "").lower()
            in {"missing", "lost", "separated", "unknown"}
        ],
        "communication_status": communication_status,
        "split_team": split_team,
        "all_accounted_for": all_accounted_for,
        "checkin_overdue_minutes": checkin_overdue,
        "planned_checkin_interval_minutes": planned_interval,
        "rendezvous_point": rendezvous_point,
        "remote_contact": _remote_contact_summary(remote_contact, resource_plan=resource_plan),
    }


def _governance(
    *,
    team_state: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    critical_gaps: list[str] = []
    warning_gaps: list[str] = []
    required_conditions: list[str] = []
    alternative_actions: list[str] = []

    not_accounted = team_state["members_not_accounted_for"]
    if not_accounted:
        critical_gaps.append("有隊員未確認位置或狀態。")
        required_conditions.append("先停止推進，確認每位隊員位置與最後聯絡時間。")
        alternative_actions.append("集合到最近可信 CP 或原路 anchor，再重新判斷。")

    if team_state.get("split_team") is True:
        critical_gaps.append("隊伍已分裂或有快慢組失去共同節奏。")
        required_conditions.append("停止讓快組繼續擴大距離，重新集合。")
        alternative_actions.append("改短版、撤退或改以最慢/最脆弱成員為行進基準。")

    overdue = _float_or_none(team_state.get("checkin_overdue_minutes"))
    if overdue is not None:
        if overdue >= OVERDUE_ESCALATE_MINUTES:
            critical_gaps.append(f"回報逾時約 {overdue:.0f} 分鐘。")
            required_conditions.append("依已批准的留守/領隊流程升級人工確認。")
        elif overdue >= OVERDUE_WARNING_MINUTES:
            warning_gaps.append(f"回報逾時約 {overdue:.0f} 分鐘。")
            required_conditions.append("下一個安全點前完成隊內與留守回報。")

    communication_status = str(team_state.get("communication_status") or "").lower()
    if communication_status in {"no_signal", "lost", "failed", "unknown"}:
        warning_gaps.append("通訊狀態不可靠，留守回報不能被視為已完成。")
        required_conditions.append("到可通訊點或預定集合點再做回報。")

    remote = team_state.get("remote_contact")
    if isinstance(remote, dict):
        if remote.get("review_state") == "needs_review":
            warning_gaps.append("留守/遠端聯絡計畫仍需人工確認。")
            required_conditions.append("出發前確認留守人、回報節點與升級條件。")
        if remote.get("secret_contact_details_included") is True:
            critical_gaps.append("留守聯絡摘要含敏感聯絡資料，不應進入 Scout AI payload。")

    if team_state.get("all_accounted_for") is False:
        critical_gaps.append("all_accounted_for=false。")
    if missing_fields:
        required_conditions.extend(f"Provide {field}." for field in missing_fields)

    next_action = _next_action(
        missing_fields=missing_fields,
        critical_gaps=critical_gaps,
        warning_gaps=warning_gaps,
    )
    return {
        "critical_gaps": _dedupe(critical_gaps),
        "warning_gaps": _dedupe(warning_gaps)[:6],
        "required_conditions": _dedupe(required_conditions),
        "alternative_actions": _dedupe(alternative_actions)
        or ["先集合到最近可信 CP。", "改短版、撤退或等待人工確認。"],
        "next_action": next_action,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "outbound_send_performed": False,
    }


def _decision(*, governance: dict[str, Any], missing_fields: list[str]) -> str:
    if governance["critical_gaps"]:
        if any("未確認位置" in gap or "回報逾時" in gap for gap in governance["critical_gaps"]):
            return "ESCALATE"
        return "CHANGE_PLAN"
    if missing_fields:
        return "DELAY"
    if governance["warning_gaps"] or governance["required_conditions"]:
        return "CONDITIONAL_GO"
    return "GO"


def _field_answer(
    *,
    decision: str,
    governance: dict[str, Any],
    missing_fields: list[str],
) -> str:
    if missing_fields and not governance["critical_gaps"]:
        return (
            "隊伍守門員：建議 DELAY。缺少 "
            + "、".join(missing_fields)
            + "；Scout 不能在隊員位置、最後聯絡、回報節點或留守計畫不明時假裝確定。"
        )
    reasons = governance["critical_gaps"] or governance["warning_gaps"] or ["隊伍狀態未顯示主要缺口。"]
    reason_text = "；".join(reasons[:2])
    return (
        f"隊伍守門員：建議 {decision}。{reason_text} "
        f"下一步：{governance['next_action']} "
        "此為 Team Status / 留守治理候選判斷，不是 runtime safety truth；不得自動通知留守人、報案、觸發 /safety、SOS、outbound send 或硬體控制。"
    )


def _decision_output(
    *,
    decision: str,
    governance: dict[str, Any],
    team_state: dict[str, Any],
    missing_fields: list[str],
    field_answer: str,
) -> dict[str, Any]:
    allowed = decision in {"GO", "CONDITIONAL_GO"}
    reasons = _decision_reasons(governance=governance, missing_fields=missing_fields)
    uncertainty_notes = [f"Missing field: {field}" for field in missing_fields]
    first_layer = {
        "decision": _decision_phrase(decision=decision, allowed=allowed),
        "limit": _decision_limit_phrase(decision=decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": governance["next_action"],
    }
    second_layer = {
        "details": _decision_details(team_state=team_state, field_answer=field_answer),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "Team status evidence is candidate-only.",
            "Remote contact, outbound send, SOS, /safety, and hardware control were not triggered.",
            "Runtime safety truth was not created.",
        ],
        "requiredConditions": governance["required_conditions"],
        "alternativeActions": governance["alternative_actions"],
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
        "action": "team_status_guardian",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "memberCount": team_state.get("member_count"),
            "membersNotAccountedFor": team_state.get("members_not_accounted_for"),
            "checkinOverdueMinutes": team_state.get("checkin_overdue_minutes"),
            "communicationStatus": team_state.get("communication_status"),
            "splitTeam": team_state.get("split_team"),
        },
        "nextAction": governance["next_action"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": governance["required_conditions"],
        "alternativeActions": governance["alternative_actions"],
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 7.3 Team Pace Fit",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 18.1 team and remote-contact inputs",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route team status recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24.1 MVP required inputs",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_reasons(
    *, governance: dict[str, Any], missing_fields: list[str]
) -> list[str]:
    reasons = []
    reasons.extend(governance["critical_gaps"])
    reasons.extend(governance["warning_gaps"])
    if missing_fields:
        reasons.append("缺少 " + "、".join(missing_fields[:5]))
    if not reasons:
        reasons.append("隊伍狀態未顯示主要缺口。")
    return _dedupe(reasons)


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "ESCALATE":
        return "停止推進並升級人工確認。"
    if decision == "CHANGE_PLAN":
        return "不建議照原隊伍節奏推進。"
    if decision == "DELAY":
        return "建議延後隊伍狀態判斷。"
    if decision == "CONDITIONAL_GO":
        return "可有條件推進，但必須先完成隊伍/留守確認。"
    if decision == "GO" and allowed:
        return "隊伍狀態可進入下一步。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str) -> str:
    if decision == "ESCALATE":
        return "不得自動通知留守人或報案；先集合隊伍，由領隊/留守依批准流程人工確認。"
    if decision == "CHANGE_PLAN":
        return "隊伍未重新集合或確認前，不得讓快慢組繼續擴大距離。"
    if decision == "DELAY":
        return "隊員位置、最後聯絡、通訊與集合/留守計畫補齊前，不得推進此判斷。"
    if decision == "CONDITIONAL_GO":
        return "必須在下一個安全 CP 前完成隊內集合與留守回報確認。"
    return "這不是 runtime safety truth；下一個 CP 仍需重算全員位置與回報節點。"


def _decision_details(
    *, team_state: dict[str, Any], field_answer: str
) -> list[str]:
    details = [
        field_answer,
        f"member_count={team_state.get('member_count')}",
        "members_not_accounted_for="
        + ",".join(str(item) for item in team_state.get("members_not_accounted_for") or []),
        "members_missing_last_heard="
        + ",".join(str(item) for item in team_state.get("members_missing_last_heard") or []),
        f"communication_status={team_state.get('communication_status')}",
        f"checkin_overdue_minutes={team_state.get('checkin_overdue_minutes')}",
        f"rendezvous_point={team_state.get('rendezvous_point')}",
    ]
    remote = team_state.get("remote_contact")
    if isinstance(remote, dict):
        details.append(
            "remote_contact="
            f"available={remote.get('available')}, review_state={remote.get('review_state')}"
        )
    return details


def _missing_fields(team_state: dict[str, Any]) -> list[str]:
    missing = []
    if team_state["member_count"] == 0:
        missing.append("team_members")
    if team_state["members_missing_last_heard"]:
        missing.append("member_positions_or_last_heard")
    if team_state.get("communication_status") is None:
        missing.append("communication_status")
    if team_state.get("rendezvous_point") is None:
        missing.append("rendezvous_point")
    remote = team_state.get("remote_contact")
    if (
        (not isinstance(remote, dict) or not remote.get("planned_checkin_labels"))
        and team_state.get("planned_checkin_interval_minutes") is None
    ):
        missing.append("checkin_schedule")
    return missing


def _next_action(
    *,
    missing_fields: list[str],
    critical_gaps: list[str],
    warning_gaps: list[str],
) -> str:
    if critical_gaps:
        return "停止推進，集合隊伍；必要時交由領隊/留守依批准流程升級人工確認。"
    if missing_fields:
        return "先補齊隊伍位置、最後聯絡時間、通訊狀態與集合/留守計畫。"
    if warning_gaps:
        return "在下一個安全 CP 前完成隊內集合與留守回報確認。"
    return "維持隊伍同行策略，在下一個 CP 重新確認全員位置與回報節點。"


def _member_summaries(
    direct_members: list[Any] | None,
    *,
    team_status: dict[str, Any],
    resource_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = []
    if isinstance(direct_members, list) and direct_members:
        raw = direct_members
    if not raw:
        raw = _first_list(
            team_status.get("members"),
            team_status.get("team_members"),
            team_status.get("member_status"),
        )
    if not raw:
        raw = _first_list(resource_plan.get("team_members"))

    members = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        members.append(
            {
                "member_id": str(
                    item.get("member_id") or item.get("id") or f"member_{index + 1}"
                ),
                "label": str(
                    item.get("display_label")
                    or item.get("label")
                    or item.get("name")
                    or item.get("member_id")
                    or f"member_{index + 1}"
                ),
                "role": item.get("role"),
                "last_heard_minutes": _float_or_none(
                    _first_present(
                        item.get("last_heard_minutes"),
                        item.get("minutes_since_last_heard"),
                        item.get("last_seen_minutes"),
                    )
                ),
                "position_status": _first_text(
                    item.get("position_status"),
                    item.get("status"),
                    item.get("location_status"),
                ),
                "accounted_for": _first_bool(
                    item.get("accounted_for"),
                    item.get("with_group"),
                    item.get("with_leader"),
                ),
                "rendezvous_point": _first_text(
                    item.get("rendezvous_point"),
                    item.get("planned_rendezvous"),
                ),
                "review_state": _nested(item, "review", "review_state"),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return members


def _remote_contact_summary(
    payload: dict[str, Any],
    *,
    resource_plan: dict[str, Any],
) -> dict[str, Any]:
    plan = resource_plan.get("remote_contact_plan")
    plan = plan if isinstance(plan, dict) else {}
    review = plan.get("review")
    review = review if isinstance(review, dict) else {}
    return {
        "available": bool(payload or plan),
        "planned_checkin_labels": _first_list(
            payload.get("planned_checkin_labels"),
            plan.get("planned_checkin_labels"),
        ),
        "review_state": review.get("review_state"),
        "secret_contact_details_included": bool(
            payload.get("secret_contact_details_included")
            or plan.get("secret_contact_details_included")
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _load_optional_json(
    root: Path,
    *,
    explicit_path: str | None,
    project: dict[str, Any],
    project_ref_keys: tuple[str, ...],
    default_refs: tuple[str, ...],
    source_kind: str,
    source_report: list[dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:
    refs = []
    if explicit_path:
        refs.append(explicit_path)
    refs.extend(str(project[key]) for key in project_ref_keys if project.get(key))
    refs.extend(default_refs)
    for ref in refs:
        path = _project_path(root, ref)
        payload = _load_json_object(path)
        if payload:
            source_report.append(
                {
                    "source_kind": source_kind,
                    "status": "loaded",
                    "source_path": ref,
                    "loaded_count": 1,
                    "raw_payloads_embedded": False,
                }
            )
            return payload, ref
    source_report.append(
        {
            "source_kind": source_kind,
            "status": "missing",
            "source_path": None,
            "loaded_count": 0,
            "raw_payloads_embedded": False,
        }
    )
    return {}, None


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def _nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _first_text(*values: Any) -> str | None:
    value = _first_present(*values)
    return str(value).strip() if value is not None and str(value).strip() else None


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _bool_or_none(value)
        if parsed is not None:
            return parsed
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
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "ok", "accounted", "together"}:
        return True
    if normalized in {"0", "false", "no", "n", "missing", "lost", "separated", "unknown"}:
        return False
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
        "live_hardware_read_performed": False,
    }
