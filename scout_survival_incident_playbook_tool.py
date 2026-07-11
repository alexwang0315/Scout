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
    "incident_context_path",
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
    incident_context_path: str | None = None,
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
    raw_provided = {
        "current_location_status": current_location_status,
        "injury_status": injury_status,
        "team_status": team_status,
        "communication_status": communication_status,
        "weather_exposure": weather_exposure,
        "overnight_risk": overnight_risk,
        "operator_authorization_ref": operator_authorization_ref,
    }
    caller_field_count = sum(
        1 for value in raw_provided.values() if not _is_missing(value)
    )
    if (
        incident_context_path
        or (caller_field_count == 0 and _allow_project_incident_context(scenario))
    ):
        incident_context, incident_context_report = _load_incident_context(
            root,
            project,
            explicit_path=incident_context_path,
        )
    else:
        incident_context = {}
        incident_context_report = [
            {
                "source_kind": "incident_context",
                "status": "skipped_project_fallback_for_caller_or_medical_context",
                "source_path": None,
                "loaded_count": 0,
            }
        ]
    provided = {
        field: _first_present(raw_provided.get(field), incident_context.get(field))
        for field in raw_provided
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
    share_policy = _share_policy(
        operator_authorization_ref=_str_or_none(
            provided.get("operator_authorization_ref")
        )
    )
    query_guidance = _query_guidance(query)
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
    decision_output = _decision_output(
        triage=triage,
        field_answer=field_answer,
        steps=steps,
        do_not_actions=do_not_actions,
        evidence_pack=evidence_pack,
        share_policy=share_policy,
    )

    return {
        "tool_id": SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_survival_incident_playbook",
        "answerability": answerability,
        "source_status": _source_status(incident_context=incident_context),
        "decision": triage.decision,
        "decision_output": decision_output,
        "field_answer": field_answer,
        "query_guidance": query_guidance,
        "survival_incident_playbook": {
            "role": triage.role,
            "scenario": scenario,
            "decision_output": decision_output,
            "steps": steps,
            "do_not_actions": do_not_actions,
            "evidence_to_preserve": evidence_pack,
            "share_policy": share_policy,
            "query_guidance": query_guidance,
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
                "decision_output": decision_output,
                "field_answer": field_answer,
                "answerability": answerability,
                "main_risks": list(triage.main_risks),
                "first_steps": steps[:3],
                "do_not_actions": do_not_actions,
            }
        ],
        "source_report": [
            *incident_context_report,
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
    if _has_any(
        text,
        (
            "受傷",
            "傷者",
            "injury",
            "bleeding",
            "fracture",
            "移動傷者",
            "高山症",
            "疑似高山症",
            "頭痛想吐",
            "頭痛噁心",
            "氣喘發作",
            "哮喘發作",
            "呼吸困難",
            "喘不過氣",
            "胸痛",
            "altitude sickness",
            "acute mountain sickness",
            "ams",
            "asthma attack",
            "shortness of breath",
        ),
    ):
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


def _query_guidance(query: str) -> dict[str, Any]:
    normalized = str(query or "").casefold()
    subject = ""
    facts: list[str] = []
    required_fact_groups: list[list[str]] = []
    missing_evidence: list[str] = []
    forbidden_claims: list[str] = []
    boundary = "只準備人工可用資訊，不自動對外發送或改變 runtime safety truth"
    if _has_any(normalized, ("可視標記", "可视标记")):
        facts = [
            "在不移動到危險地形的安全處建立標記",
            "使用高對比衣物或布料、反光物、規律燈光等可辨識材料",
            "記錄標記位置、建立時間與隊伍狀態",
        ]
        boundary = "不得為建立標記移動到崖邊、稜線或其他危險地形"
    elif _has_any(normalized, ("保存哪些證據", "保存哪些证据")):
        facts = [
            "保存目前或最後座標、高度與時間",
            "保存最後移動方向、軌跡與最後確認點",
            "保存隊伍人數、傷勢、意識與能否行走",
            "保存訊號、剩餘電量、最後聯絡時間、天氣與剩餘資源",
        ]
        boundary = "未確認欄位標示未知；只準備人工轉報資料，不自動發送 SOS"
    elif _has_any(normalized, ("位置分享給誰", "位置分享给谁")):
        facts = [
            "先分享給已約定的留守人、領隊或隊伍聯絡人",
            "進入人工求救流程後，由人員向 119 或搜救窗口轉報",
            "分享座標或最後確認點、時間、隊伍與傷勢、通訊和電量",
        ]
        boundary = "只傳給已約定或救援所需對象；Scout 不自動發送位置"
    elif _has_any(normalized, ("稜線上移動找訊號", "棱线上移动找信号")):
        facts = [
            "未確認目前位置、稜線 route geometry、暴露地形與回退路徑前不要移動找訊號",
            "先在現位置確認可用通訊與最後有效位置",
        ]
        boundary = "不得只為訊號盲目移動到稜線或離開最後可確認路線走廊"
    elif _has_any(normalized, ("滑倒受傷", "滑倒受伤")) and _has_any(
        normalized,
        ("位置清楚", "位置明确", "位置明確"),
    ):
        subject = "位置已知的受傷事件回報"
        facts = [
            "保留使用者已說位置清楚這項事實，但回報仍需實際座標或最後確認點與時間",
            "回報受傷部位與機轉、意識、出血、疼痛與能否行走",
            "回報隊伍人數與是否全員在一起、可用通訊、剩餘電量與最後聯絡時間",
            "由人員向已約定留守人或 119 搜救窗口轉報",
        ]
        required_fact_groups = [
            ["位置清楚", "位置已知"],
            ["座標", "最後確認點"],
            ["時間"],
            ["受傷部位", "傷勢"],
            ["意識"],
            ["能否行走"],
            ["隊伍人數"],
            ["通訊", "聯絡"],
            ["電量"],
            ["最後聯絡時間"],
            ["留守人", "119", "搜救窗口"],
            ["未知", "未確認"],
        ]
        missing_evidence = ["實際座標或最後確認點", "事件時間", "傷勢細節", "隊伍與通訊狀態"]
        boundary = "未確認欄位標示未知，只準備人工轉報，不自動發送"
        forbidden_claims = ["不得要求重新確認位置是否清楚", "不得聲稱已完成通報"]
    elif _has_any(normalized, ("報座標還是地標", "报坐标还是地标")):
        subject = "求救位置應如何表達"
        facts = [
            "座標與地標應一起回報，座標作為定位主體、地標作為辨識與接近補充",
            "座標需附格式、座標基準、取得時間與定位精度",
            "地標補充最後確認點、周圍特徵與可接近方向",
        ]
        required_fact_groups = [
            ["座標"],
            ["地標"],
            ["格式"],
            ["基準"],
            ["時間"],
            ["定位精度", "精度"],
            ["接近方向", "周圍特徵"],
        ]
        missing_evidence = ["目前實際座標", "座標格式與基準", "定位精度", "可辨識地標"]
        boundary = "未確認值標示未知，由人員轉報；Scout 不自動發送"
        forbidden_claims = ["不得只回報模糊地標", "不得聲稱位置已送達救援單位"]
    elif _has_any(normalized, ("直升機", "吊掛", "吊挂")):
        subject = "直升機吊掛可行性候選"
        facts = [
            "目前不能確認可吊掛，最終由執行救援的航空與搜救單位判斷",
            "需提供精確位置、風雨與能見度、地形坡度、林冠電線岩壁等周圍障礙",
            "需提供傷者與隊伍狀態，以及安全等待位置",
            "不要為尋找吊掛點下切、跨越危險地形或盲目移動",
        ]
        required_fact_groups = [
            ["不能確認", "無法確認"],
            ["救援單位", "航空"],
            ["位置"],
            ["風雨", "能見度"],
            ["坡度", "地形"],
            ["周圍障礙", "林冠", "電線", "岩壁"],
            ["傷者", "隊伍"],
            ["不要", "不得"],
        ]
        missing_evidence = ["精確位置", "即時天候與能見度", "坡度與周圍障礙", "傷者與隊伍狀態"]
        boundary = "只能列吊掛候選條件，不能保證可吊掛，也不得引導冒險移動"
        forbidden_claims = ["不得保證直升機可吊掛", "不得指示前往未確認吊掛點"]
    elif _has_any(normalized, ("搜救員能接近", "搜救人員能接近", "搜救人员能接近")):
        subject = "搜救人員地面接近可行性"
        facts = [
            "目前不能確認搜救人員能否接近，需先把當前位置綁定到地形與路線證據",
            "檢查坡度、崖壁、溪溝、林相與障礙，以及既有步道或接近路線",
            "補充即時天候、傷者搬運需求與隊伍狀態，由搜救單位決定接近方案",
        ]
        required_fact_groups = [
            ["不能確認", "無法確認"],
            ["當前位置", "目前位置"],
            ["坡度", "崖壁", "溪溝"],
            ["接近路線", "步道"],
            ["天候", "天氣"],
            ["傷者"],
            ["搜救單位"],
        ]
        missing_evidence = ["目前位置與定位精度", "坡度與障礙", "可用接近路線", "即時天候", "傷者搬運需求"]
        boundary = "地形分數只能列候選，不能保證搜救人員可接近"
        forbidden_claims = ["不得把高分地形候選寫成可接近或不可接近的結論"]
    elif _has_any(normalized, ("更開闊", "開闊的地方", "开阔的地方")):
        subject = "是否應移動到開闊待援位置"
        facts = [
            "目前不能判定應否移動，需比較現位置與開闊候選之間的完整移動路徑",
            "檢查坡度、暴露、崖壁、落石、林相與其他障礙",
            "同時檢查傷勢、隊伍能力、天候、能見度與回退可能",
            "不得只為增加可見性而盲目移動；最終待援位置由人員與救援單位複核",
        ]
        required_fact_groups = [
            ["不能判定", "無法判定"],
            ["現位置", "目前位置"],
            ["完整移動路徑", "路徑"],
            ["坡度", "暴露", "障礙"],
            ["傷勢", "隊伍"],
            ["天候", "能見度"],
            ["不得", "不要"],
        ]
        missing_evidence = ["目前位置與定位精度", "開闊候選與完整移動路徑", "傷勢與隊伍能力", "即時天候與能見度"]
        boundary = "不得盲目移動到候選；沒有完整路徑證據時保持未知"
        forbidden_claims = ["不得把開闊候選寫成安全待援點"]
    elif _has_any(normalized, ("移動傷者", "移动伤者")):
        subject = "移動傷者的二次傷害風險"
        facts = [
            "移動可能造成二次傷害，除非原位置有火、水、落石、墜落等立即危險，否則先避免移動",
            "需確認受傷機轉、頭頸背疼痛、意識、出血、呼吸與能否行走",
            "需比較原位置危險、移動路徑地形、距離、可用人力與專業救援建議",
        ]
        required_fact_groups = [
            ["二次傷害"],
            ["立即危險"],
            ["避免移動", "不要移動"],
            ["受傷機轉", "傷勢"],
            ["意識"],
            ["呼吸", "出血"],
            ["移動路徑", "地形"],
            ["專業救援", "救援建議"],
        ]
        missing_evidence = ["傷勢與受傷機轉", "原位置立即危險", "移動路徑與人力", "專業救援建議"]
        boundary = "不能遠端診斷；沒有立即危險與專業判斷時不得輕率移動傷者"
        forbidden_claims = ["不得聲稱傷者狀況穩定", "不得提供無證據的移動許可"]
    elif _has_any(normalized, ("現場指揮", "现场指挥")):
        subject = "事故現場角色分工"
        facts = [
            "多人事故現場應指定一名協調者維持共同決策與資訊一致",
            "依可用人數分配傷者照護、通訊轉報、位置與事件紀錄等角色",
            "角色分工不得讓隊伍分散，也不取代 119 或搜救單位的正式指揮",
        ]
        required_fact_groups = [
            ["協調者"],
            ["傷者照護", "照護"],
            ["通訊轉報", "通訊"],
            ["事件紀錄", "紀錄"],
            ["不得讓隊伍分散", "不要分散"],
            ["不取代", "正式指揮"],
        ]
        missing_evidence = ["現場人數", "傷者狀態", "通訊能力", "已建立的救援聯絡鏈"]
        boundary = "只提供臨時角色分工，不宣稱取得正式救援指揮權"
        forbidden_claims = ["不得自稱現場總指揮", "不得取代救援單位命令"]
    elif _has_any(normalized, ("留守人轉報", "給留守人轉報", "给留守人转报")):
        subject = "留守人轉報所需資訊"
        facts = [
            "提供行程或路線名稱與原定計畫",
            "提供目前或最後位置、座標、高度與時間",
            "提供傷勢、意識、能否行走與隊伍人數",
            "提供訊號、可用裝置、電量、最後聯絡時間、天氣、照明、保暖、水與食物",
        ]
        required_fact_groups = [
            ["行程", "路線"],
            ["位置", "座標"],
            ["時間"],
            ["傷勢", "意識"],
            ["隊伍人數"],
            ["訊號", "通訊"],
            ["電量"],
            ["天氣", "保暖", "水與食物"],
        ]
        missing_evidence = ["實際位置與時間", "傷勢與隊伍狀態", "通訊與電量", "天候與剩餘資源"]
        boundary = "未確認欄位標示未知，由留守人人工轉報；Scout 不自動發送"
        forbidden_claims = ["不得聲稱留守人已收到或已完成報案"]
    elif _has_any(normalized, ("撐過夜", "撑过夜")):
        subject = "待援過夜保全順序"
        facts = [
            "停止不必要移動並讓隊伍聚在一起，選擇不增加地形風險的避風位置",
            "隔絕濕冷與地面，換上乾燥保暖層並遮蔽風雨",
            "盤點水、食物、電量、照明與保暖資源，保留定位與必要通訊",
            "記錄位置與隊伍狀態，維持可辨識標記並定期互相檢查",
        ]
        required_fact_groups = [
            ["停止", "不要移動"],
            ["隊伍聚在一起", "集合"],
            ["避風"],
            ["隔絕濕冷", "乾燥保暖"],
            ["水", "食物"],
            ["電量", "照明"],
            ["定位", "通訊"],
            ["標記", "記錄位置"],
            ["互相檢查"],
        ]
        missing_evidence = ["目前位置與地形", "即時風雨低溫", "傷者與隊伍狀態", "水食物電量照明與保暖"]
        boundary = "不得為找營地盲目移動；若現位置有立即危險，交由人員依現場與救援指示調整"
        forbidden_claims = ["不得保證能安全撐到天亮", "不得聲稱救援到達時間"]
    return {
        "subject": subject,
        "facts": facts,
        "required_fact_groups": required_fact_groups,
        "missing_evidence": missing_evidence,
        "forbidden_claims": forbidden_claims,
        "boundary": boundary,
        "outbound_send_performed": False,
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


def _decision_output(
    *,
    triage: SurvivalIncidentTriage,
    field_answer: str,
    steps: list[str],
    do_not_actions: list[str],
    evidence_pack: list[dict[str, Any]],
    share_policy: dict[str, Any],
) -> dict[str, Any]:
    decision = triage.decision
    reasons = list(triage.main_risks) or ["事件資訊不足，必須採保守 playbook。"]
    uncertainty_notes = [f"Missing field: {field}" for field in triage.missing_fields]
    required_conditions = [
        f"Provide {field}." for field in triage.missing_fields
    ] or [
        "Keep the team stopped or gathered while a human operator reviews the situation."
    ]
    first_layer = {
        "decision": _decision_phrase(decision=decision, scenario=triage.scenario),
        "limit": _decision_limit_phrase(decision=decision),
        "reason": " / ".join(reasons[:2]),
        "nextStep": steps[0] if steps else "停止前進並重新評估。",
    }
    second_layer = {
        "details": _decision_details(
            field_answer=field_answer,
            steps=steps,
            evidence_pack=evidence_pack,
            share_policy=share_policy,
        ),
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": [
            "This playbook is candidate-only and not runtime safety truth.",
            "Medical diagnosis, rescue dispatch, outbound send, SOS, /safety, and hardware control were not triggered.",
        ],
        "requiredConditions": required_conditions,
        "alternativeActions": do_not_actions,
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
        "action": "survival_incident_playbook",
        "decision": decision,
        "allowed": False,
        "locationConstraint": first_layer["limit"],
        "mainReasons": reasons[:3],
        "cost": {
            "scenario": triage.scenario,
            "escalationRequired": triage.escalation_required,
            "personalizedContextAvailable": triage.personalized_context_available,
            "outboundSendAllowed": False,
            "canPrepareManualSharePack": share_policy.get("can_prepare_manual_share_pack"),
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "low" if uncertainty_notes else "medium",
        "uncertaintyNotes": uncertainty_notes,
        "residualRisk": second_layer["residualRisk"],
        "requiredConditions": required_conditions,
        "alternativeActions": do_not_actions,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 2 safety philosophy",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 15.2 Risk Sentinel",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route workflow",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28 guardrail principle",
        ],
        "runtimeSafetyTruth": False,
    }


def _decision_phrase(*, decision: str, scenario: str) -> str:
    if decision == "ESCALATE":
        return "停止推進並交由人工救援/領隊判斷。"
    if scenario == "lost_or_position_uncertain":
        return "不建議繼續移動或下切找路。"
    if decision == "NO_GO":
        return "不建議採取高風險行動。"
    return "暫緩判斷。"


def _decision_limit_phrase(*, decision: str) -> str:
    if decision == "ESCALATE":
        return "不得自動發送 SOS、通知留守人或報案；只能準備人工可轉報資料。"
    return "不得下切、追捷徑、分散找路、自動 SOS、outbound send、/safety 或硬體警報。"


def _decision_details(
    *,
    field_answer: str,
    steps: list[str],
    evidence_pack: list[dict[str, Any]],
    share_policy: dict[str, Any],
) -> list[str]:
    provided_fields = [
        str(item.get("field"))
        for item in evidence_pack
        if isinstance(item, dict) and item.get("provided")
    ]
    missing_fields = [
        str(item.get("field"))
        for item in evidence_pack
        if isinstance(item, dict) and not item.get("provided")
    ]
    details = [field_answer]
    details.extend(f"step_{index + 1}={step}" for index, step in enumerate(steps[:3]))
    details.append("provided_evidence_fields=" + ",".join(provided_fields))
    details.append("missing_evidence_fields=" + ",".join(missing_fields))
    details.append(
        "share_policy="
        f"can_send_or_notify={share_policy.get('can_send_or_notify')}, "
        "requires_explicit_authorization_before_outbound="
        f"{share_policy.get('requires_explicit_authorization_before_outbound')}"
    )
    return details


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
        if _has_any(
            query.lower(),
            (
                "高山症",
                "頭痛想吐",
                "頭痛噁心",
                "altitude sickness",
                "acute mountain sickness",
                "ams",
            ),
        ):
            risks = ["疑似高山症屬高後果健康情境，繼續上升或推進可能讓狀況惡化。"]
        elif _has_any(
            query.lower(),
            (
                "氣喘發作",
                "哮喘發作",
                "呼吸困難",
                "喘不過氣",
                "胸痛",
                "asthma attack",
                "shortness of breath",
            ),
        ):
            risks = ["呼吸困難或氣喘發作屬高後果健康情境，繼續推進可能延誤人工醫療判斷。"]
        else:
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


def _load_incident_context(
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
            "incident_context_ref",
            "reviewed_incident_context_ref",
            "survival_incident_context_ref",
        ),
        fallbacks=(
            "outputs/incident_context.reviewed.json",
            "outputs/survival_incident_context.reviewed.json",
            "outputs/incident_context.json",
        ),
    )
    report: list[dict[str, Any]] = []
    for label, path in candidates:
        if not path.exists():
            report.append(
                {
                    "source_kind": "incident_context",
                    "status": "missing",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        payload = _load_json_object(path)
        context = _incident_context_from_payload(payload)
        if not context:
            report.append(
                {
                    "source_kind": "incident_context",
                    "status": "invalid_or_empty",
                    "source_path": label,
                    "loaded_count": 0,
                }
            )
            continue
        report.append(
            {
                "source_kind": "incident_context",
                "status": "loaded",
                "source_path": label,
                "loaded_count": 1,
                "artifact_kind": payload.get("artifact_kind"),
                "source_status": payload.get("status") or payload.get("source_status"),
            }
        )
        return context, report
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


def _incident_context_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    nested = payload.get("incident_context")
    if not isinstance(nested, dict):
        nested = payload.get("survival_incident_context")
    if not isinstance(nested, dict):
        nested = payload.get("snapshot")
    context_source = nested if isinstance(nested, dict) else payload
    fields = (
        "current_location_status",
        "injury_status",
        "team_status",
        "communication_status",
        "weather_exposure",
        "overnight_risk",
        "operator_authorization_ref",
    )
    context = {
        field: context_source.get(field)
        for field in fields
        if not _is_missing(context_source.get(field))
    }
    if payload.get("status") and "source_status" not in context:
        context["source_status"] = payload.get("status")
    return context


def _allow_project_incident_context(scenario: str) -> bool:
    return scenario in {
        "general_incident_uncertainty",
        "lost_or_position_uncertain",
        "rescue_or_sos_preparation",
    }


def _source_status(*, incident_context: dict[str, Any]) -> str:
    if incident_context:
        return str(incident_context.get("source_status") or "loaded_incident_context")
    return "deterministic_playbook_explainer"


def _str_or_none(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


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
