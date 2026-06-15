import json
from pathlib import Path

from scout_contextual_permission_tool import (
    CONTEXTUAL_PERMISSION_OUTPUT_KIND,
    CONTEXTUAL_PERMISSION_TOOL_ID,
    assess_scout_contextual_permission,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_contextual_permission_allows_film_with_bounded_deadline_and_cost() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2026-06-07T13:36:00+08:00",
        current_cp_id="CP3",
        next_cp_id="CP4",
        remaining_safety_buffer_minutes=21,
        current_delay_minutes=9,
        next_segment_uncertainty_minutes=3,
        weather_reserve_minutes=2,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["tool_id"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["action"] == "film"
    assert result["max_duration_minutes"] == 6
    assert result["leave_by"] == "2026-06-07T13:42:00+08:00"
    assert result["field_answer"].startswith("[決策] 可以，最多 6 分鐘。")
    assert "最多 6 分鐘" in result["field_answer"]
    assert "13:42" in result["field_answer"]
    assert "[限制]" in result["field_answer"]
    assert "[下一步]" in result["field_answer"]

    permission = result["contextual_permission"]
    assert permission["decision"] == "CONDITIONAL_GO"
    assert permission["allowed"] is True
    assert permission["maxDurationMinutes"] == 6
    assert permission["leaveBy"] == "2026-06-07T13:42:00+08:00"
    assert permission["cost"]["timeBufferChangeMinutes"] == -6
    assert permission["nextAction"]
    assert permission["requiredConditions"]
    assert result["decision_object"] == permission

    decision_output = result["decision_output"]
    assert decision_output["decisionObjectSchema"] == "ContextualPermission"
    assert decision_output["action"] == "film"
    assert decision_output["decision"] == "CONDITIONAL_GO"
    assert decision_output["allowed"] is True
    assert decision_output["maxDurationMinutes"] == 6
    assert decision_output["leaveBy"] == "2026-06-07T13:42:00+08:00"
    assert decision_output["cost"]["timeBufferChangeMinutes"] == -6
    assert decision_output["confidence"] == "medium"
    assert decision_output["runtimeSafetyTruth"] is False
    assert decision_output["firstLayer"]["decision"] == "可以，最多 6 分鐘。"
    assert "2026-06-07T13:42:00+08:00" in decision_output["firstLayer"]["limit"]
    assert decision_output["firstLayer"]["nextStep"] == permission["nextAction"]
    assert any(
        "可授權時間約 16 分鐘" in detail
        for detail in decision_output["secondLayer"]["details"]
    )
    assert "最多 6 分鐘" in decision_output["secondLayer"]["requiredConditions"][0]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 21.0
    assert budget["authorizedDurationMinutes"] == 16
    assert budget["bufferAfterActionMinutes"] == 15
    assert result["risk_budget_source"]["source_status"] == (
        "caller_provided_normalized_evidence"
    )
    assert result["risk_budget_source"]["workspace_reserve_source"][
        "source_status"
    ] == "not_applied"
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_api_called"] is False


def test_contextual_permission_allows_fog_wait_with_bounded_photo_cutoff() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="可以等霧散再拍照嗎？",
        current_time="2026-06-07T14:00:00+08:00",
        current_cp_id="CP4",
        next_cp_id="CP5",
        remaining_safety_buffer_minutes=18,
        next_segment_uncertainty_minutes=4,
        weather_reserve_minutes=3,
        weather_window_impact="14:30 後降雨風險升高，不再等待。",
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "wait"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["max_duration_minutes"] == 5
    assert result["leave_by"] == "2026-06-07T14:05:00+08:00"
    assert result["decision_output"]["firstLayer"]["decision"] == "可以，最多 5 分鐘。"
    assert "14:05" in result["field_answer"]
    assert "能見度沒有改善" in result["decision_output"]["firstLayer"]["nextStep"]
    assert "放棄拍攝" in result["decision_output"]["firstLayer"]["nextStep"]
    assert any(
        "不要離開步道內側" in condition
        for condition in result["decision_output"]["secondLayer"][
            "requiredConditions"
        ]
    )
    assert any(
        "放棄拍攝" in condition
        for condition in result["decision_output"]["secondLayer"][
            "requiredConditions"
        ]
    )
    assert result["contextual_permission"]["cost"]["timeBufferChangeMinutes"] == -5
    assert result["contextual_permission"]["cost"]["weatherWindowImpact"] == (
        "14:30 後降雨風險升高，不再等待。"
    )
    assert result["risk_budget"]["bufferAfterActionMinutes"] == 13
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_allows_teammate_wait_with_hard_cutoff() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="可以等隊友 5 分鐘嗎？",
        current_time="2026-06-07T13:50:00+08:00",
        current_cp_id="CP4",
        next_cp_id="CP5",
        remaining_safety_buffer_minutes=18,
        requested_duration_minutes=5,
        next_segment_uncertainty_minutes=4,
        retreat_reserve_minutes=3,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "wait_teammate"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["max_duration_minutes"] == 5
    assert result["leave_by"] == "2026-06-07T13:55:00+08:00"
    assert result["decision_output"]["firstLayer"]["decision"] == "可以，最多 5 分鐘。"
    assert "未會合" in result["decision_output"]["firstLayer"]["nextStep"]
    assert "隊伍狀態檢查" in result["decision_output"]["firstLayer"]["nextStep"]
    assert any(
        "保持隊伍完整" in condition
        for condition in result["decision_output"]["secondLayer"][
            "requiredConditions"
        ]
    )
    assert any(
        "不能無限延長" in risk
        for risk in result["decision_output"]["secondLayer"]["residualRisk"]
    )
    assert "改用既定集合點" in result["decision_output"]["secondLayer"][
        "alternativeActions"
    ][1]
    assert result["contextual_permission"]["cost"]["timeBufferChangeMinutes"] == -5
    assert result["risk_budget"]["bufferAfterActionMinutes"] == 13
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_allows_tripod_only_with_bounded_cutoff() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="可以架腳架 4 分鐘嗎？",
        current_time="2026-06-07T13:36:00+08:00",
        current_cp_id="CP3",
        next_cp_id="CP4",
        remaining_safety_buffer_minutes=21,
        requested_duration_minutes=4,
        next_segment_uncertainty_minutes=5,
        weather_reserve_minutes=3,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "tripod"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["max_duration_minutes"] == 4
    assert result["leave_by"] == "2026-06-07T13:40:00+08:00"
    assert result["decision_output"]["action"] == "tripod"
    assert result["decision_output"]["firstLayer"]["decision"] == "可以，最多 4 分鐘。"
    assert "收起腳架" in result["decision_output"]["firstLayer"]["nextStep"]
    assert any(
        "不得在風口" in condition
        for condition in result["decision_output"]["secondLayer"][
            "requiredConditions"
        ]
    )
    assert any(
        "強風" in risk
        for risk in result["decision_output"]["secondLayer"]["residualRisk"]
    )
    assert result["contextual_permission"]["cost"]["timeBufferChangeMinutes"] == -4
    assert result["risk_budget"]["bufferAfterActionMinutes"] == 17
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_blocks_wind_exposed_tripod_even_with_buffer() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="這裡是風口強風，可以架腳架嗎？",
        current_time="2026-06-07T13:36:00+08:00",
        remaining_safety_buffer_minutes=30,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "tripod"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == []
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議架腳架。"
    assert "腳架會增加停留時間" in result["decision_output"]["firstLayer"]["reason"]
    assert "不要架腳架" in result["decision_output"]["firstLayer"]["nextStep"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_blocks_wind_exposed_lunch_even_with_buffer() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="這裡是風口，我們可以在這裡吃午餐嗎？",
        current_time="2026-06-07T12:00:00+08:00",
        current_cp_id="CP2",
        next_cp_id="CP3",
        remaining_safety_buffer_minutes=45,
        next_segment_uncertainty_minutes=5,
        weather_reserve_minutes=5,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "lunch"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["max_duration_minutes"] is None
    assert result["leave_by"] is None
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議吃午餐。"
    assert "風口" in result["decision_output"]["firstLayer"]["reason"]
    assert "失溫" in result["decision_output"]["firstLayer"]["reason"]
    assert "不能只因時間 buffer 足夠就授權" in result["field_answer"]
    assert result["decision_output"]["firstLayer"]["nextStep"] == (
        "不在此午餐，請再前往 CP3，到較避風處再重新評估。"
    )
    assert "前往 CP3 吃午餐" in result["decision_output"]["secondLayer"][
        "alternativeActions"
    ]
    assert result["risk_budget"]["authorizedDurationMinutes"] == 35
    assert "bufferAfterActionMinutes" not in result["risk_budget"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_missing_buffer_is_conservative_no_go() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="我可以在這裡停下來拍一段影片嗎?",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result["field_answer"].startswith("[決策] 不建議拍影片。")
    assert "不建議拍影片" in result["field_answer"]
    assert "資料不足" in result["contextual_permission"]["uncertaintyNotes"][1]
    assert result["contextual_permission"]["alternativeActions"]
    assert result["decision_output"]["firstLayer"]["limit"] == (
        "不授權此行動；不要消耗停留或改線 buffer。"
    )
    assert result["decision_output"]["action"] == "film"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["secondLayer"]["alternativeActions"]


def test_contextual_permission_missing_buffer_still_reports_requested_stop_cost() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="如果多停 10 分鐘，代價是什麼？",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["action"] == "stop"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result["contextual_permission"]["cost"]["timeBufferChangeMinutes"] == -10
    assert result["decision_output"]["cost"]["timeBufferChangeMinutes"] == -10
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議停留。"
    assert "使用者要求約 10 分鐘" in result["decision_output"]["firstLayer"]["reason"]
    assert "不能計算代價或授權" in result["decision_output"]["firstLayer"]["reason"]
    assert result["decision_output"]["firstLayer"]["nextStep"] == (
        "不要在此停留，請先前往下一個安全 CP，再重新評估。"
    )
    assert any(
        "使用者要求時間約 10 分鐘" in detail
        for detail in result["decision_output"]["secondLayer"]["details"]
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_generic_leave_by_question_defaults_to_stop() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="現在可以做嗎？什麼時間前必須離開？",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["action"] == "stop"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result["decision_output"]["action"] == "stop"
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議停留。"
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_blocks_exposed_photo_even_with_buffer() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="前方是高曝露陡坡，但照片很好看，可以去拍嗎？",
        remaining_safety_buffer_minutes=30,
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == []
    assert result["action"] == "photo"
    assert result["contextual_permission"]["decision"] == "NO_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["action"] == "photo"
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議拍照。"
    assert "曝露或高後果地形" in result["decision_output"]["firstLayer"]["reason"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_allows_rain_gear_without_buffer() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="前面下雨了，要不要穿雨衣？",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "wear_rain_gear"
    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["missing_fields"] == []
    assert result["contextual_permission"]["cost"]["timeBufferChangeMinutes"] == 0
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["action"] == "wear_rain_gear"
    assert result["decision_output"]["decision"] == "GO"
    assert result["decision_output"]["allowed"] is True
    assert result["decision_output"]["cost"]["timeBufferChangeMinutes"] == 0
    assert result["decision_output"]["firstLayer"]["decision"] == "可以穿雨具。"
    assert result["decision_output"]["firstLayer"]["limit"] == (
        "不額外消耗停留 buffer；執行後立即回到原定節奏。"
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert "就地穿上雨具" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_blocks_unreviewed_shortcut_reroute() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="這個岔路可以切嗎？",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["action"] == "reroute"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["action"] == "reroute"
    assert result["decision_output"]["decision"] == "NO_GO"
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議改線。"
    assert "臨時切岔路或改線" in result["decision_output"]["firstLayer"]["reason"]
    assert "已審核替代路線" in result["decision_output"]["firstLayer"]["reason"]
    assert result["decision_output"]["firstLayer"]["limit"] == (
        "不授權此行動；不要消耗停留或改線 buffer。"
    )
    assert "不要臨時改線" in result["decision_output"]["firstLayer"]["nextStep"]
    assert (
        "只走已審核替代路線"
        in result["decision_output"]["secondLayer"]["alternativeActions"]
    )
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_allows_direct_retreat_for_tired_teammate() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="隊友很累，要不要直接撤退？",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "retreat"
    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["missing_fields"] == []
    assert result["contextual_permission"]["cost"]["timeBufferChangeMinutes"] == 0
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["action"] == "retreat"
    assert result["decision_output"]["decision"] == "GO"
    assert result["decision_output"]["allowed"] is True
    assert result["decision_output"]["cost"]["timeBufferChangeMinutes"] == 0
    assert result["decision_output"]["firstLayer"]["decision"] == "可以撤退。"
    assert "保持隊伍完整" in result["decision_output"]["firstLayer"]["nextStep"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_derives_candidate_buffer_from_planned_eta() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2013-10-08T14:52:50+08:00",
        next_cp_id="雲海保線所",
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["missing_fields"] == []
    assert result["max_duration_minutes"] is None
    assert result["leave_by"] is None
    assert "不建議拍影片" in result["field_answer"]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 6.0
    assert budget["authorizedDurationMinutes"] == 0
    assert budget["nextSegmentUncertaintyMinutes"] == 10.0
    assert budget["weatherReserveMinutes"] == 15.0
    assert budget["daylightReserveMinutes"] == 60.0
    assert "bufferAfterActionMinutes" not in budget

    source = result["risk_budget_source"]
    assert source["source_status"] == "derived_from_planned_eta_candidate"
    assert source["source_path"] == "outputs/planned_eta.json"
    assert source["next_cp_id"] == "雲海保線所"
    assert source["planned_eta"] == "2013-10-08T14:58:50+08:00"
    assert source["minutes_until_planned_eta"] == 6
    assert source["runtime_safety_truth"] is False
    assert {
        item["reserve_field"]
        for item in source["reserve_sources"]
    } >= {
        "next_segment_uncertainty_minutes",
        "weather_reserve_minutes",
        "daylight_reserve_minutes",
    }
    assert any("candidate planned ETA" in warning for warning in result["warnings"])
    assert any("reserve was deducted" in warning for warning in result["warnings"])


def test_contextual_permission_allows_eta_buffer_when_weather_and_validation_reviewed(
    tmp_path: Path,
) -> None:
    project_root = _write_reviewed_eta_project(tmp_path)

    result = assess_scout_contextual_permission(
        project_root,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2026-06-07T13:36:00+08:00",
        next_cp_id="CP4",
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["decision"] == "CONDITIONAL_GO"
    assert result["allowed"] is True
    assert result["max_duration_minutes"] == 6
    assert result["leave_by"] == "2026-06-07T13:42:00+08:00"
    assert "最多 6 分鐘" in result["field_answer"]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 6.0
    assert budget["authorizedDurationMinutes"] == 6
    assert budget["bufferAfterActionMinutes"] == 0
    assert budget["weatherReserveMinutes"] == 0.0
    assert budget["daylightReserveMinutes"] == 0.0
    assert budget["nextSegmentUncertaintyMinutes"] == 0.0

    source = result["risk_budget_source"]
    assert source["source_status"] == "derived_from_planned_eta_candidate"
    assert source["reserve_sources"] == []
    assert source["workspace_reserve_source"]["source_status"] == (
        "workspace_reserves_not_needed_reviewed_evidence"
    )
    assert not any("reserve was deducted" in warning for warning in result["warnings"])


def test_contextual_permission_deducts_slowest_member_reserve_from_energy_vitals(
    tmp_path: Path,
) -> None:
    project_root = _write_reviewed_eta_project(tmp_path, include_energy_vitals=True)

    result = assess_scout_contextual_permission(
        project_root,
        query="我可以在這裡停下來拍一段影片嗎?",
        current_time="2026-06-07T13:36:00+08:00",
        next_cp_id="CP4",
        communication_status="ok",
        equipment_status="ok",
    )

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert "不建議拍影片" in result["field_answer"]

    budget = result["risk_budget"]
    assert budget["remainingSafetyBufferMinutes"] == 6.0
    assert budget["slowestMemberReserveMinutes"] == 10.0
    assert budget["authorizedDurationMinutes"] == 0

    source = result["risk_budget_source"]
    reserve_sources = source["reserve_sources"]
    slowest = [
        item
        for item in reserve_sources
        if item["reserve_field"] == "slowest_member_reserve_minutes"
    ]
    assert len(slowest) == 1
    assert slowest[0]["source_path"] == "outputs/energy_vitals.json"
    assert slowest[0]["source_kind"] == "energy_vitals_advisory"
    assert slowest[0]["raw_health_payload_embedded"] is False
    assert slowest[0]["provider_values_are_scout_truth"] is False
    assert "rest_suggested_band" in slowest[0]["candidate_basis"]
    assert "heart_rate_drift_rest_band" in slowest[0]["candidate_basis"]
    assert any("reserve was deducted" in warning for warning in result["warnings"])


def test_contextual_permission_escalates_high_risk_stream_crossing() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="這裡溪水暴漲，可以過溪嗎?",
        action="cross_stream",
        remaining_safety_buffer_minutes=50,
        terrain_risk_level="critical",
        communication_status="weak",
        equipment_status="unknown",
    )

    assert result["decision"] == "ESCALATE"
    assert result["allowed"] is False
    assert result["action"] == "cross_stream"
    assert "需要升級處理" in result["field_answer"]
    assert "不要渡溪" in result["contextual_permission"]["alternativeActions"]


def test_contextual_permission_escalates_stream_surge_without_buffer() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="前方溪水暴漲，還能過溪嗎？",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["action"] == "cross_stream"
    assert result["decision"] == "ESCALATE"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "需要升級處理，不建議渡溪。"
    )
    assert "高後果情境" in result["decision_output"]["firstLayer"]["reason"]
    assert "停止進入溪谷" in result["decision_output"]["firstLayer"]["nextStep"]
    assert any(
        "高後果地形先採保守禁止" in note
        for note in result["decision_output"]["secondLayer"]["uncertaintyNotes"]
    )
    assert "不要渡溪" in result["decision_output"]["secondLayer"][
        "alternativeActions"
    ]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_escalates_unknown_creek_level_without_experience() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="目前無法確認溪流水位，且我們沒有渡溪經驗，可以進入溪谷嗎？",
    )

    assert result["answerability"] == "contextual_permission_missing_required_fields"
    assert result["action"] == "cross_stream"
    assert result["decision"] == "ESCALATE"
    assert result["allowed"] is False
    assert result["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "需要升級處理，不建議渡溪。"
    )
    assert "高後果情境" in result["decision_output"]["firstLayer"]["reason"]
    assert "停止進入溪谷" in result["decision_output"]["firstLayer"]["nextStep"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_blocks_unreviewed_fast_passage_request() -> None:
    result = assess_scout_contextual_permission(
        PROJECT_ROOT,
        query="這段要不要快速通過？",
    )

    assert result["answerability"] == "contextual_permission_decision_available"
    assert result["action"] == "continue"
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["decision_output"]["firstLayer"]["decision"] == "不建議繼續前進。"
    assert "不能授權快速通過" in result["decision_output"]["firstLayer"]["reason"]
    assert "最近安全 CP" in result["decision_output"]["firstLayer"]["nextStep"]
    assert any(
        "Risk Sentinel requires" in note
        for note in result["decision_output"]["secondLayer"]["uncertaintyNotes"]
    )
    assert result["boundary"]["runtime_safety_truth"] is False


def test_contextual_permission_output_kind_constant() -> None:
    assert CONTEXTUAL_PERMISSION_OUTPUT_KIND == (
        "scout_ai_contextual_permission_tool_output"
    )


def _write_reviewed_eta_project(
    tmp_path: Path,
    *,
    include_energy_vitals: bool = False,
) -> Path:
    project_root = tmp_path / "reviewed_eta_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    project_payload = {
        "project_id": "reviewed_eta_project",
        "planned_eta_ref": "outputs/planned_eta.json",
        "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
        "plan_validation_candidates_ref": "outputs/plan_validation_candidates.json",
    }
    if include_energy_vitals:
        project_payload["energy_vitals_ref"] = "outputs/energy_vitals.json"
    (project_root / "project.json").write_text(
        json.dumps(
            project_payload,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "planned_eta.json").write_text(
        json.dumps(
            {
                "plan_id": "eta_plan.reviewed.v0",
                "project_id": "reviewed_eta_project",
                "estimates": [
                    {
                        "estimate_id": "eta.cp4",
                        "to_node_name": "CP4",
                        "eta": "2026-06-07T13:42:00+08:00",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "weather_daylight_evidence.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "human_review_required": False,
                "authoritative_weather_computed": True,
                "validation": {"validation_status": "reviewed"},
                "daylight": {"source_status": "reviewed"},
                "weather_window": {"source_status": "reviewed"},
                "threshold_policy": {
                    "daylight": {"dark_arrival_warning_margin_min": 60}
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "plan_validation_candidates.json").write_text(
        json.dumps(
            {
                "status": "reviewed",
                "findings": [],
                "hard_readiness_mutation_allowed": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if include_energy_vitals:
        (outputs / "energy_vitals.json").write_text(
            json.dumps(
                {
                    "artifact_kind": "scout_ai_energy_vitals_tool_output",
                    "answerability": "energy_vitals_advisory_available",
                    "provided_fields": {
                        "subject_id": "local_user.private",
                        "reserve_score": 38,
                        "reserve_band": "rest_suggested",
                        "heart_rate_drift_ratio": 0.174,
                    },
                    "advisory": {
                        "cue_band": "rest_suggested",
                        "reserve_band": "rest_suggested",
                        "heart_rate_drift_ratio": 0.174,
                        "message_zh": "體能儲備提示：建議短暫休息。",
                    },
                    "privacy": {
                        "raw_health_payload_shared": False,
                        "raw_samples_embedded": False,
                    },
                    "boundary": {
                        "runtime_safety_truth": False,
                        "medical_diagnosis": False,
                        "provider_values_are_scout_truth": False,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return project_root
