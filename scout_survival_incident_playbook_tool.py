from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID = (
    "scout.ai.survival_incident_playbook.explain.v0"
)
SURVIVAL_INCIDENT_PLAYBOOK_OUTPUT_KIND = (
    "scout_ai_survival_incident_playbook_tool_output"
)
SURVIVAL_INCIDENT_PLAYBOOK_REQUIRED_FIELDS = ("project_root",)
SURVIVAL_INCIDENT_PLAYBOOK_OPTIONAL_FIELDS = (
    "incident_type",
    "current_location_status",
    "injury_status",
    "team_status",
    "communication_status",
    "weather_exposure",
    "overnight_risk",
    "operator_authorization_ref",
    "emergency_playbook_path",
)


class SurvivalPlaybookModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SurvivalIncidentBoundary(SurvivalPlaybookModel):
    read_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    live_safety_api_calls_allowed: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    model_output_is_runtime_truth: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    real_sos_sent: Literal[False] = False
    real_sms_sent: Literal[False] = False
    real_satellite_sent: Literal[False] = False
    medical_diagnosis: Literal[False] = False


class SurvivalIncidentTriage(SurvivalPlaybookModel):
    role: Literal["Risk Sentinel / Survival Incident Playbook"] = (
        "Risk Sentinel / Survival Incident Playbook"
    )
    scenario: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    escalation_required: bool
    personalized_context_available: bool
    emergency_outbound_allowed: Literal[False] = False
    main_risks: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


def explain_scout_survival_incident_playbook(
    project_root: str | Path,
    *,
    query: str = "",
    incident_type: str | None = None,
    current_location_status: str | None = None,
    injury_status: str | None = None,
    team_status: str | None = None,
    communication_status: str | None = None,
    weather_exposure: str | None = None,
    overnight_risk: str | bool | None = None,
    operator_authorization_ref: str | None = None,
    emergency_playbook_path: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    project = _load_project(root)
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    scenario = _scenario(incident_type, query)
    provided = {
        "current_location_status": current_location_status,
        "injury_status": injury_status,
        "team_status": team_status,
        "communication_status": communication_status,
        "weather_exposure": weather_exposure,
        "overnight_risk": overnight_risk,
        "operator_authorization_ref": operator_authorization_ref,
    }
    missing_fields = _missing_fields(scenario=scenario, provided=provided)
    playbook_source = _load_playbook_source(
        root,
        project=project,
        emergency_playbook_path=emergency_playbook_path,
    )
    triage = _triage(
        scenario=scenario,
        query=query,
        provided=provided,
        missing_fields=missing_fields,
    )
    steps = _steps_for(
        scenario=scenario,
        triage=triage,
        provided=provided,
    )
    do_not_actions = _do_not_actions(scenario)
    evidence_pack = _evidence_pack(provided=provided)
    share_policy = _share_policy(operator_authorization_ref=operator_authorization_ref)
    answerability = (
        "survival_playbook_personalized_context_available"
        if triage.personalized_context_available
        else "survival_playbook_missing_personalized_context"
    )
    field_answer = _field_answer(
        scenario=scenario,
        triage=triage,
        steps=steps,
        do_not_actions=do_not_actions,
    )
    boundary = _closed_boundary()

    return {
        "tool_id": SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_survival_incident_playbook",
        "answerability": answerability,
        "source_status": "deterministic_playbook_explainer",
        "decision": triage.decision,
        "field_answer": field_answer,
        "survival_incident_playbook": {
            "role": triage.role,
            "scenario": scenario,
            "steps": steps,
            "do_not_actions": do_not_actions,
            "evidence_to_preserve": evidence_pack,
            "share_policy": share_policy,
            "boundary": boundary,
        },
        "incident_triage": triage.model_dump(mode="json"),
        "missing_fields": missing_fields,
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 2 safety philosophy",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 4 decision vocabulary",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route workflow",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28 guardrail principle",
        ],
        "result_count": 1,
        "results": [
            {
                "label": f"survival incident playbook: {scenario}",
                "decision": triage.decision,
                "field_answer": field_answer,
                "answerability": answerability,
                "main_risks": list(triage.main_risks),
                "first_steps": steps[:3],
                "do_not_actions": do_not_actions,
            }
        ],
        "source_report": [
            playbook_source,
            {
                "source_kind": "deterministic_survival_playbook_policy",
                "status": "loaded",
                "source_path": "scout_survival_incident_playbook_tool.py",
                "loaded_count": 1,
            },
        ],
        "boundary": boundary,
    }


def _scenario(incident_type: str | None, query: str) -> str:
    text = f"{incident_type or ''} {query}".lower()
    if _has_any(text, ("受傷", "傷者", "injury", "bleeding", "fracture", "移動傷者")):
        return "injury_or_medical_uncertainty"
    if _has_any(text, ("失溫", "低溫", "hypothermia", "風寒", "濕衣", "撐過夜")):
        return "cold_exposure_or_overnight"
    if _has_any(text, ("迷路", "不確定自己在哪", "找路", "下切溪谷", "lost")):
        return "lost_or_position_uncertain"
    if _has_any(text, ("求救", "報案", "直升機", "sos", "rescue", "搜救")):
        return "rescue_or_sos_preparation"
    return "general_incident_uncertainty"


def _triage(
    *,
    scenario: str,
    query: str,
    provided: dict[str, Any],
    missing_fields: list[str],
) -> SurvivalIncidentTriage:
    risks = _main_risks(scenario, query=query, provided=provided)
    decision = "ESCALATE" if scenario in {
        "injury_or_medical_uncertainty",
        "cold_exposure_or_overnight",
        "rescue_or_sos_preparation",
    } else "NO_GO"
    personalized = not missing_fields
    return SurvivalIncidentTriage(
        scenario=scenario,
        decision=decision,
        escalation_required=decision == "ESCALATE",
        personalized_context_available=personalized,
        main_risks=risks,
        missing_fields=missing_fields,
    )


def _steps_for(
    *,
    scenario: str,
    triage: SurvivalIncidentTriage,
    provided: dict[str, Any],
) -> list[str]:
    steps = [
        "停止前進，讓隊伍聚在一起，先不要分散找路或下切。",
        "用離線地圖、最後已知 CP、時間與高度建立目前位置假設。",
        "把手機與手錶省電，保留定位、照明與通訊能力。",
    ]
    if scenario == "lost_or_position_uncertain":
        steps.extend(
            [
                "若位置不明，優先原地等待或退回最後確認點，不要追捷徑。",
                "在安全處建立可見標記，記錄座標、時間、方向與最後確認點。",
            ]
        )
    elif scenario == "injury_or_medical_uncertainty":
        steps.extend(
            [
                "先避免移動傷者，除非原位置有立即危險。",
                "整理傷勢、意識、保暖、可行走能力與隊伍人數，交給人工救援或醫療判斷。",
            ]
        )
    elif scenario == "cold_exposure_or_overnight":
        steps.extend(
            [
                "立即加保暖層、隔絕濕冷與風，建立避風點。",
                "盤點水、食物、電量、照明與保暖，準備撐到天亮或等候救援。",
            ]
        )
    elif scenario == "rescue_or_sos_preparation":
        steps.extend(
            [
                "準備人工可轉報資料：座標、最後確認點、隊伍狀態、傷勢、天氣與剩餘資源。",
                "只有在已授權通訊流程中，才由人員或已核准系統對外發送。",
            ]
        )
    if provided.get("communication_status"):
        steps.append(f"通訊狀態已知：{provided['communication_status']}。")
    if triage.missing_fields:
        steps.append("資料不足時，Scout 只能給保守 playbook，不能自動升級成 SOS 或通報。")
    return steps


def _do_not_actions(scenario: str) -> list[str]:
    actions = [
        "不要自動報案、通知留守人或對外發送訊息。",
        "不要呼叫 /safety/*、不要改變 Phase 1 L0-L4、不要觸發硬體警報。",
        "不要把候選 playbook 當成醫療診斷或 runtime safety truth。",
    ]
    if scenario in {"lost_or_position_uncertain", "general_incident_uncertainty"}:
        actions.append("不要下切溪谷、追捷徑或離開最後可確認路線走廊。")
    if scenario == "injury_or_medical_uncertainty":
        actions.append("不要在沒有專業判斷下移動傷者。")
    return actions


def _evidence_pack(*, provided: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [
        ("location", "current_location_status", "目前位置、最後確認點、座標、高度、時間"),
        ("injury", "injury_status", "傷勢、意識、是否能走、疼痛或出血描述"),
        ("team", "team_status", "人數、是否全員在一起、最弱成員狀態"),
        ("communication", "communication_status", "訊號、可用裝置、電量、最後聯絡時間"),
        ("weather", "weather_exposure", "雨、風、低溫、濕衣、能見度、夜間暴露"),
    ]
    return [
        {
            "kind": kind,
            "field": field,
            "provided": not _is_missing(provided.get(field)),
            "description": description,
        }
        for kind, field, description in fields
    ]


def _share_policy(*, operator_authorization_ref: str | None) -> dict[str, Any]:
    return {
        "outbound_send_performed": False,
        "operator_authorization_ref": operator_authorization_ref,
        "can_prepare_manual_share_pack": True,
        "can_send_or_notify": False,
        "requires_explicit_authorization_before_outbound": True,
        "allowed_share_fields": [
            "coordinate_or_last_known_point",
            "trip_id_or_route_name",
            "team_count_and_injury_status",
            "weather_exposure",
            "remaining_battery_and_comms",
        ],
    }


def _field_answer(
    *,
    scenario: str,
    triage: SurvivalIncidentTriage,
    steps: list[str],
    do_not_actions: list[str],
) -> str:
    first_step = steps[0] if steps else "停止前進並重新評估。"
    risk = triage.main_risks[0] if triage.main_risks else "事件資訊不足。"
    return (
        f"求生事件 playbook：{triage.decision}。{first_step} "
        f"主要風險：{risk} "
        f"禁止事項：{do_not_actions[0]} "
        "這是只讀候選指引，不是 runtime safety truth，也不會發送 SOS。"
    )


def _missing_fields(*, scenario: str, provided: dict[str, Any]) -> list[str]:
    required = ["current_location_status", "team_status", "communication_status"]
    if scenario == "injury_or_medical_uncertainty":
        required.append("injury_status")
    if scenario == "cold_exposure_or_overnight":
        required.extend(["weather_exposure", "overnight_risk"])
    return [field for field in required if _is_missing(provided.get(field))]


def _main_risks(
    scenario: str,
    *,
    query: str,
    provided: dict[str, Any],
) -> list[str]:
    if scenario == "lost_or_position_uncertain":
        risks = ["位置不確定時繼續移動會放大迷途與失聯風險。"]
    elif scenario == "injury_or_medical_uncertainty":
        risks = ["傷勢不明時移動傷者可能造成二次傷害。"]
    elif scenario == "cold_exposure_or_overnight":
        risks = ["低溫、濕衣、風與夜間暴露會提高失溫風險。"]
    elif scenario == "rescue_or_sos_preparation":
        risks = ["求救情境需要人工授權與準確事件資料，Scout AI 不得自行對外通報。"]
    else:
        risks = ["事件脈絡不足，Scout 必須採保守 playbook。"]
    if _has_any(query.lower(), ("下切溪谷", "溪谷", "找路")):
        risks.append("下切溪谷或離開路線走廊會降低被找到的機率。")
    if not _is_missing(provided.get("weather_exposure")):
        risks.append(f"暴露條件：{provided['weather_exposure']}。")
    return risks


def _load_playbook_source(
    root: Path,
    *,
    project: dict[str, Any],
    emergency_playbook_path: str | None,
) -> dict[str, Any]:
    ref = (
        emergency_playbook_path
        or project.get("emergency_playbook_ref")
        or project.get("sos_playbook_ref")
    )
    if not ref:
        return {
            "source_kind": "scout_emergency_playbook",
            "status": "default_policy_used",
            "source_path": None,
            "loaded_count": 0,
        }
    path = root / str(ref)
    if not path.exists():
        return {
            "source_kind": "scout_emergency_playbook",
            "status": "missing",
            "source_path": str(ref),
            "loaded_count": 0,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    loaded_count = len(payload) if isinstance(payload, list) else 1
    return {
        "source_kind": "scout_emergency_playbook",
        "status": "loaded",
        "source_path": str(ref),
        "loaded_count": loaded_count,
    }


def _load_project(root: Path) -> dict[str, Any]:
    path = root / "project.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.lower() in text for term in terms)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def _closed_boundary() -> dict[str, bool]:
    return SurvivalIncidentBoundary().model_dump(mode="json")
