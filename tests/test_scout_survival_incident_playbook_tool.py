from pathlib import Path

from scout_survival_incident_playbook_tool import (
    SURVIVAL_INCIDENT_PLAYBOOK_OUTPUT_KIND,
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
    explain_scout_survival_incident_playbook,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_survival_playbook_uses_reviewed_incident_context_without_sending_sos() -> None:
    result = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="不確定自己在哪，可以下切溪谷找路嗎？",
    )

    assert result["tool_id"] == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == (
        "survival_playbook_personalized_context_available"
    )
    assert result["source_status"] == "reviewed_incident_context"
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議繼續移動或下切找路。"
    )
    assert "不得下切" in result["decision_output"]["firstLayer"]["limit"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["incident_triage"]["scenario"] == "lost_or_position_uncertain"
    assert result["missing_fields"] == []
    assert "不要自動報案" in result["field_answer"]
    assert "runtime safety truth" in result["field_answer"]
    assert "發送 SOS" in result["field_answer"]
    playbook = result["survival_incident_playbook"]
    assert playbook["role"] == "Risk Sentinel / Survival Incident Playbook"
    assert any("不要下切溪谷" in item for item in playbook["do_not_actions"])
    assert playbook["share_policy"]["can_send_or_notify"] is False
    assert result["boundary"]["real_sos_sent"] is False
    assert result["boundary"]["outbound_send_performed"] is False
    assert result["boundary"]["phase1_l0_l4_state_mutated"] is False


def test_survival_playbook_keeps_missing_context_without_reviewed_artifact(
    tmp_path: Path,
) -> None:
    result = explain_scout_survival_incident_playbook(
        tmp_path,
        query="不確定自己在哪，可以下切溪谷找路嗎？",
    )

    assert result["answerability"] == "survival_playbook_missing_personalized_context"
    assert result["source_status"] == "deterministic_playbook_explainer"
    assert result["decision"] == "NO_GO"
    assert "current_location_status" in result["missing_fields"]
    assert "team_status" in result["missing_fields"]
    assert "communication_status" in result["missing_fields"]
    assert result["boundary"]["real_sos_sent"] is False
    assert result["boundary"]["outbound_send_performed"] is False


def test_survival_playbook_personalizes_injury_context_without_medical_diagnosis() -> None:
    result = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="隊友受傷了，現在要怎麼整理求救資料？",
        current_location_status="CP4 附近，離線地圖座標已截圖",
        injury_status="腳踝扭傷，意識清楚，無法負重",
        team_status="4 人全員在一起",
        communication_status="手機訊號一格，剩餘電量 38%",
        operator_authorization_ref="operator.review.pending",
    )

    assert result["answerability"] == (
        "survival_playbook_personalized_context_available"
    )
    assert result["decision"] == "ESCALATE"
    assert result["decision_output"]["decision"] == "ESCALATE"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "停止推進並交由人工救援/領隊判斷。"
    )
    assert "不得自動發送 SOS" in result["decision_output"]["firstLayer"]["limit"]
    assert result["missing_fields"] == []
    assert result["incident_triage"]["scenario"] == "injury_or_medical_uncertainty"
    assert result["incident_triage"]["escalation_required"] is True
    assert result["survival_incident_playbook"]["share_policy"][
        "operator_authorization_ref"
    ] == "operator.review.pending"
    assert result["boundary"]["medical_diagnosis"] is False
    assert result["boundary"]["remote_outbound_send_allowed"] is False


def test_survival_playbook_escalates_active_altitude_sickness() -> None:
    result = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="隊友頭痛想吐疑似高山症，還能繼續前進嗎？",
    )

    assert result["answerability"] == "survival_playbook_missing_personalized_context"
    assert result["decision"] == "ESCALATE"
    assert result["decision_output"]["decision"] == "ESCALATE"
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "停止推進並交由人工救援/領隊判斷。"
    )
    assert "疑似高山症" in result["decision_output"]["firstLayer"]["reason"]
    assert result["incident_triage"]["scenario"] == "injury_or_medical_uncertainty"
    assert result["boundary"]["medical_diagnosis"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_survival_playbook_output_kind_constant() -> None:
    assert SURVIVAL_INCIDENT_PLAYBOOK_OUTPUT_KIND == (
        "scout_ai_survival_incident_playbook_tool_output"
    )


def test_survival_playbook_emits_query_specific_lost_mode_guidance() -> None:
    visual = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="我要怎麼建立可視標記？",
    )["query_guidance"]
    evidence = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="我應該保存哪些證據給搜救？",
    )["query_guidance"]
    recipients = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="我該把目前位置分享給誰？",
    )["query_guidance"]
    ridge = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="我該往稜線上移動找訊號嗎？",
    )["query_guidance"]

    assert any("高對比" in fact for fact in visual["facts"])
    assert "危險地形" in visual["boundary"]
    assert any("最後移動方向" in fact for fact in evidence["facts"])
    assert any("留守人" in fact for fact in recipients["facts"])
    assert recipients["outbound_send_performed"] is False
    assert any("目前位置" in fact and "回退" in fact for fact in ridge["facts"])


def test_survival_playbook_emits_structured_accident_rescue_guidance() -> None:
    expected = {
        "我滑倒受傷但位置清楚，該怎麼回報？": (
            "位置已知的受傷事件回報",
            "受傷",
        ),
        "我應該報座標還是地標？": (
            "求救位置應如何表達",
            "座標與地標",
        ),
        "直升機是否有可能吊掛？": (
            "直升機吊掛可行性候選",
            "周圍障礙",
        ),
        "這個地形搜救員能接近嗎？": (
            "搜救人員地面接近可行性",
            "接近路線",
        ),
        "我該移動到更開闊的地方嗎？": (
            "是否應移動到開闊待援位置",
            "盲目移動",
        ),
        "移動傷者是否會更危險？": (
            "移動傷者的二次傷害風險",
            "立即危險",
        ),
        "我們是否需要建立現場指揮角色？": (
            "事故現場角色分工",
            "協調者",
        ),
        "救援不會立刻到，我們該怎麼撐過夜？": (
            "待援過夜保全順序",
            "隔絕濕冷",
        ),
    }
    for question, (subject, required_fact) in expected.items():
        guidance = explain_scout_survival_incident_playbook(
            PROJECT_ROOT,
            query=question,
        )["query_guidance"]
        assert guidance["subject"] == subject, question
        assert any(required_fact in fact for fact in guidance["facts"]), question
        assert guidance["required_fact_groups"], question
        assert guidance["outbound_send_performed"] is False


def test_leave_behind_relay_question_uses_rescue_report_guidance() -> None:
    guidance = explain_scout_survival_incident_playbook(
        PROJECT_ROOT,
        query="哪些資訊要給留守人轉報？",
    )["query_guidance"]

    assert guidance["subject"] == "留守人轉報所需資訊"
    assert any("行程" in fact for fact in guidance["facts"])
    assert any("位置" in fact and "時間" in fact for fact in guidance["facts"])
    assert "不自動發送" in guidance["boundary"]
