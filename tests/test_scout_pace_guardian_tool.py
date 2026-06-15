from pathlib import Path

from scout_pace_guardian_tool import (
    PACE_GUARDIAN_OUTPUT_KIND,
    PACE_GUARDIAN_TOOL_ID,
    assess_scout_pace_guardian,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_pace_guardian_changes_plan_for_slowest_member_pressure() -> None:
    result = assess_scout_pace_guardian(
        PROJECT_ROOT,
        query="隊友很累，要不要直接撤退或縮短行程？",
        team_members=[
            {
                "member_id": "leader",
                "display_label": "Leader",
                "pace_mps": 1.15,
                "reserve_minutes": 55,
                "fatigue_band": "normal",
            },
            {
                "member_id": "teammate",
                "display_label": "New teammate",
                "pace_mps": 0.58,
                "reserve_minutes": 8,
                "fatigue_band": "tired",
                "rest_need_minutes": 12,
                "first_time_similar_route": True,
                "conditions": ["sleep_debt", "knee_pain"],
            },
        ],
        minutes_to_next_cp=24,
        current_delay_minutes=22,
        leader_accepts_slowest_basis=False,
        team_rest_sync="mismatched",
    )

    assert result["tool_id"] == PACE_GUARDIAN_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "pace_fit_decision_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原計畫推進。"
    )
    assert "不要用平均腳程" in result["decision_output"]["firstLayer"]["limit"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["source_status"] == "candidate_only"
    assert result["pace_guardian"]["role"] == "Pace Guardian"
    assert result["pace_guardian"]["basis"] == "slowest_member_and_most_vulnerable_link"
    assert result["pace_guardian"]["average_pace_used"] is False
    assert result["team_pace_fit"]["slowest_member"]["label"] == "New teammate"
    assert result["team_pace_fit"]["slowest_member"]["vulnerable_link"] is True
    assert result["team_pace_fit"]["pace_gap_ratio"] == 1.98
    assert result["schedule_pressure"]["minutes_to_next_cp"] == 24.0
    assert "不使用平均腳程" in result["field_answer"]
    assert "CHANGE_PLAN" in result["field_answer"]
    assert "contextual permission" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["medical_diagnosis"] is False


def test_pace_guardian_surfaces_scout_pace_coefficient_drag() -> None:
    result = assess_scout_pace_guardian(
        PROJECT_ROOT,
        query="這段有碎石下坡又下雨，最慢者的 Scout Pace Coefficient 還能照原計畫嗎？",
        team_members=[
            {
                "member_id": "leader",
                "display_label": "Leader",
                "pace_mps": 1.05,
                "reserve_minutes": 70,
            },
            {
                "member_id": "slowest",
                "display_label": "Slowest member",
                "pace_mps": 0.72,
                "reserve_minutes": 45,
                "flat_speed_mps": 1.0,
                "uphill_speed_mps": 0.55,
                "downhill_speed_mps": 0.48,
                "technical_terrain_slowdown_ratio": 0.35,
                "rest_frequency_minutes": 50,
                "late_trip_speed_decay_ratio": 0.28,
                "pack_weight_kg": 11,
                "load_slowdown_ratio": 0.2,
                "weather_slowdown_ratio": 0.18,
                "experience_credibility": "low",
                "self_report_gap_ratio": 0.24,
            },
        ],
        leader_accepts_slowest_basis=True,
        team_rest_sync="synced",
    )

    assert result["answerability"] == "pace_fit_decision_available"
    assert result["decision"] == "CONDITIONAL_GO"
    coefficient = result["team_pace_fit"]["scout_pace_coefficients"][0]
    assert coefficient["label"] == "Slowest member"
    assert coefficient["technical_terrain_slowdown_ratio"] == 0.35
    assert coefficient["late_trip_speed_decay_ratio"] == 0.28
    assert coefficient["load_slowdown_ratio"] == 0.2
    assert coefficient["weather_slowdown_ratio"] == 0.18
    reasons = " ".join(result["team_pace_fit"]["main_reasons"])
    assert "Scout Pace Coefficient" in reasons
    assert "技術地形降速率" in reasons
    assert "行程後段速度衰退" in reasons
    assert "負重" in reasons
    assert "經驗可信度" in reasons
    assert "Scout Pace Coefficient" in result["field_answer"]
    assert result["decision_output"]["cost"]["paceCoefficientImpact"].startswith(
        "Scout Pace Coefficient considered"
    )
    assert result["boundary"]["runtime_safety_truth"] is False


def test_pace_guardian_treats_ahead_of_plan_as_controlled_pace_condition() -> None:
    result = assess_scout_pace_guardian(
        PROJECT_ROOT,
        query="目前比計畫快 20 分鐘，可以繼續照原節奏嗎？",
        team_members=[
            {
                "member_id": "leader",
                "display_label": "Leader",
                "pace_mps": 1.0,
                "reserve_minutes": 60,
            },
            {
                "member_id": "slow",
                "display_label": "Slow member",
                "pace_mps": 0.72,
                "reserve_minutes": 40,
            },
        ],
        current_delay_minutes=-20,
        leader_accepts_slowest_basis=True,
    )

    assert result["answerability"] == "pace_fit_decision_available"
    assert result["decision"] == "CONDITIONAL_GO"
    reasons = " ".join(result["team_pace_fit"]["main_reasons"])
    assert "比計畫快約 20 分鐘" in reasons
    assert "不是免費 buffer" in reasons
    assert result["schedule_pressure"]["current_delay_minutes"] == -20.0
    assert result["decision_output"]["cost"]["scheduleDelayMinutes"] == -20.0
    assert result["decision_output"]["cost"]["scheduleAheadMinutes"] == 20.0
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "可繼續，但必須以最慢者控速。"
    )
    assert "降回最慢者可恢復節奏" in result["decision_output"]["firstLayer"][
        "nextStep"
    ]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_pace_guardian_reports_missing_member_pace_from_resource_plan() -> None:
    result = assess_scout_pace_guardian(
        PROJECT_ROOT,
        query="隊伍腳程是否能準時抵達下一個 CP？",
    )

    assert result["answerability"] == "pace_fit_missing_required_fields"
    assert result["decision"] == "NO_GO"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議用目前腳程資料繼續判斷。"
    )
    assert result["missing_fields"] == ["member_pace_profile"]
    assert result["team_pace_fit"]["member_count"] == 2
    assert result["team_pace_fit"]["members_with_pace_count"] == 0
    assert result["debug_sources"]["resource_plan_source"] == "outputs/resource_plan.json"
    assert "缺少 member_pace_profile" in result["field_answer"]
    assert result["pace_guardian"]["average_pace_used"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_pace_guardian_derives_minutes_to_next_cp_from_planned_eta() -> None:
    result = assess_scout_pace_guardian(
        PROJECT_ROOT,
        query="最慢者還能準時到雲海保線所嗎？",
        team_members=[
            {
                "member_id": "leader",
                "display_label": "Leader",
                "pace_mps": 1.0,
                "reserve_minutes": 80,
            },
            {
                "member_id": "slowest",
                "display_label": "Slowest member",
                "pace_mps": 0.72,
                "reserve_minutes": 22,
                "fatigue_band": "rest_suggested",
            },
        ],
        current_time="2013-10-08T14:35:50+08:00",
        next_cp_id="雲海保線所",
        leader_accepts_slowest_basis=True,
    )

    assert result["schedule_pressure"]["minutes_to_next_cp"] == 23.0
    assert result["schedule_pressure"]["eta_source"] == "outputs/planned_eta.json"
    assert result["decision"] == "CHANGE_PLAN"
    assert "下一個 CP" in " ".join(result["team_pace_fit"]["main_reasons"])


def test_pace_guardian_output_kind_constant() -> None:
    assert PACE_GUARDIAN_OUTPUT_KIND == "scout_ai_pace_guardian_tool_output"
