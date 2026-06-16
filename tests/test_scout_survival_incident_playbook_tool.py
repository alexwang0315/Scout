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
