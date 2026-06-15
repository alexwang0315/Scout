from __future__ import annotations

import json
from pathlib import Path

from scout_route_architecture_tool import (
    ROUTE_ARCHITECTURE_OUTPUT_KIND,
    ROUTE_ARCHITECTURE_TOOL_ID,
    assess_scout_route_architecture,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
STANDARD_CP_NODE_FIELDS = {
    "cpId",
    "name",
    "coordinates",
    "elevation",
    "plannedArrivalTime",
    "latestSafeArrivalTime",
    "plannedDepartureTime",
    "latestSafeDepartureTime",
    "recommendedStopMinutes",
    "maxStopMinutes",
    "nextSegmentEstimatedMinutes",
    "nextSegmentDifficulty",
    "retreatOptions",
    "weatherSensitivity",
    "terrainRisks",
    "communicationStatus",
    "safeToStop",
    "photoVideoSuitability",
    "decisionTriggers",
}


def test_route_architecture_builds_candidate_cp_graph_and_decision() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="下一個撤退點在哪？這條路線難點在哪？",
        limit=4,
    )

    assert result["artifact_kind"] == ROUTE_ARCHITECTURE_OUTPUT_KIND
    assert result["tool_id"] == ROUTE_ARCHITECTURE_TOOL_ID
    assert result["status"] == "completed"
    assert result["answerability"] == "route_architecture_available"
    assert result["source_status"] == "candidate_only"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "可依 CP Graph 推進，但必須保留折返窗口。"
    )
    assert "不得在難點群前消耗 buffer" in result["decision_output"]["firstLayer"]["limit"]
    alternatives = result["decision_output"]["secondLayer"]["alternativeActions"]
    assert alternatives
    assert any("折返" in item or "撤退" in item for item in alternatives)
    assert all("return to entry" not in item for item in alternatives)
    assert all("turn back at" not in item for item in alternatives)
    assert all("shorten route" not in item for item in alternatives)
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["missing_fields"] == []
    assert result["cp_graph"]["node_count"] == 124
    assert result["cp_graph"]["edge_count"] == 123
    first_node = result["cp_graph"]["nodes"][0]
    assert STANDARD_CP_NODE_FIELDS <= first_node.keys()
    assert first_node["cpId"] == first_node["cp_id"]
    assert first_node["runtime_safety_truth"] is False
    assert first_node["candidate_only"] is True
    assert first_node["photoVideoSuitability"].endswith(
        "requires_contextual_permission"
    )
    assert "no_stop_without_contextual_permission" in first_node["decisionTriggers"]
    assert result["route_architecture"]["role"] == "Route Architecture Intelligence"
    assert result["route_architecture"]["turn_back"]["turn_back_checkpoint_name"] == (
        "雲海保線所"
    )
    assert result["route_architecture"]["retreat_option_count"] == 1
    assert result["route_architecture"]["hard_points"]
    assert result["route_decision"]["runtime_safety_truth"] is False
    assert "路線結構判斷" in result["field_answer"]
    assert "CP Graph" in result["field_answer"]
    assert "雲海保線所" in result["field_answer"]
    assert "候選撤退路線" in result["field_answer"]
    assert "seg.050" in result["field_answer"]
    assert "中段難點" in result["field_answer"]
    assert "後段/回程難點" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["safety_api_called"] is False
    assert result["boundary"]["outbound_send_performed"] is False


def test_route_architecture_standard_cp_node_fields_use_policy_and_eta(
    tmp_path: Path,
) -> None:
    project_root = _write_standard_cp_node_project(tmp_path)

    result = assess_scout_route_architecture(
        project_root,
        query="Viewpoint 可以停多久？下一段難不難？",
        limit=3,
    )

    nodes = {node["cpId"]: node for node in result["cp_graph"]["nodes"]}
    viewpoint = nodes["cp.view"]
    assert STANDARD_CP_NODE_FIELDS <= viewpoint.keys()
    assert viewpoint["name"] == "Viewpoint"
    assert viewpoint["coordinates"] == {"lat": 24.2, "lon": 121.2}
    assert viewpoint["elevation"] == 1200.0
    assert viewpoint["plannedArrivalTime"] == "2026-06-16T10:00:00+08:00"
    assert viewpoint["latestSafeArrivalTime"] == "2026-06-16T10:30:00+08:00"
    assert viewpoint["plannedDepartureTime"] == "2026-06-16T10:00:00+08:00"
    assert viewpoint["latestSafeDepartureTime"] == "2026-06-16T11:30:00+08:00"
    assert viewpoint["recommendedStopMinutes"] == 0
    assert viewpoint["maxStopMinutes"] == 0
    assert viewpoint["nextSegmentEstimatedMinutes"] == 45.0
    assert viewpoint["nextSegmentDifficulty"] == "high"
    assert viewpoint["retreatOptions"][0]["candidate_id"] == "retreat.return"
    assert viewpoint["retreatOptions"][0]["applicability"] == (
        "trigger_checkpoint_candidate"
    )
    assert viewpoint["weatherSensitivity"] == ["daylight_required"]
    assert "no_segment_retreat" in viewpoint["terrainRisks"]
    assert "no_segment_water" in viewpoint["terrainRisks"]
    assert "long_segment_duration" in viewpoint["terrainRisks"]
    assert viewpoint["communicationStatus"] == "signal_not_expected"
    assert viewpoint["safeToStop"] is False
    assert viewpoint["photoVideoSuitability"] == (
        "not_recommended_requires_contextual_permission"
    )
    assert "turn_back_checkpoint" in viewpoint["decisionTriggers"]
    assert "preserve_buffer_before_high_difficulty_segment" in viewpoint[
        "decisionTriggers"
    ]
    assert result["boundary"]["runtime_safety_truth"] is False


def _write_standard_cp_node_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "standard_cp_node_project"
    (project_root / "normalized" / "routes").mkdir(parents=True)
    (project_root / "candidates").mkdir()
    (project_root / "outputs").mkdir()
    _write_json(
        project_root / "project.json",
        {
            "project_id": "standard_cp_node_project",
            "route_summary_ref": "normalized/routes/route_summary.json",
            "checkpoint_candidates_ref": "candidates/checkpoints.json",
            "segment_candidates_ref": "candidates/segments.json",
            "segment_policy_candidates_ref": "outputs/segment_policy_candidates.json",
            "retreat_routes_ref": "candidates/retreat_routes.json",
            "planned_eta_ref": "outputs/planned_eta.json",
        },
    )
    _write_json(
        project_root / "normalized" / "routes" / "route_summary.json",
        {
            "distance_m": 1900,
            "elevation_min_m": 1000,
            "elevation_max_m": 1400,
            "started_at": "2026-06-16T08:00:00+08:00",
            "ended_at": "2026-06-16T12:00:00+08:00",
        },
    )
    _write_json(
        project_root / "candidates" / "checkpoints.json",
        [
            {
                "candidate_id": "cp.start",
                "label": "Trailhead",
                "lat": 24.1,
                "lon": 121.1,
                "elevation_m": 1000,
                "checkpoint_type": "start",
                "review_state": "accepted",
                "candidate_only": True,
            },
            {
                "candidate_id": "cp.view",
                "label": "Viewpoint",
                "lat": 24.2,
                "lon": 121.2,
                "elevation_m": 1200,
                "checkpoint_type": "viewpoint",
                "review_state": "accepted",
                "candidate_only": True,
            },
            {
                "candidate_id": "cp.finish",
                "label": "Summit",
                "lat": 24.3,
                "lon": 121.3,
                "elevation_m": 1400,
                "checkpoint_type": "finish",
                "review_state": "accepted",
                "candidate_only": True,
            },
        ],
    )
    _write_json(
        project_root / "candidates" / "segments.json",
        [
            {
                "candidate_id": "seg.001",
                "from_candidate_id": "cp.start",
                "to_candidate_id": "cp.view",
                "distance_m": 1000,
                "elevation_gain_m": 200,
                "elevation_loss_m": 0,
                "review_state": "accepted",
            },
            {
                "candidate_id": "seg.002",
                "from_candidate_id": "cp.view",
                "to_candidate_id": "cp.finish",
                "distance_m": 900,
                "elevation_gain_m": 50,
                "elevation_loss_m": 0,
                "review_state": "accepted",
            },
        ],
    )
    _write_json(
        project_root / "outputs" / "segment_policy_candidates.json",
        {
            "candidates": [
                {
                    "segment_candidate_id": "seg.001",
                    "requirement": {
                        "expected_duration_seconds": 1800,
                        "requires_daylight": True,
                        "retreat_available": False,
                        "water_available": False,
                        "signal_expected": True,
                    },
                },
                {
                    "segment_candidate_id": "seg.002",
                    "requirement": {
                        "expected_duration_seconds": 2700,
                        "latest_safe_departure_time": "2026-06-16T11:30:00+08:00",
                        "requires_daylight": True,
                        "retreat_available": False,
                        "water_available": False,
                        "signal_expected": False,
                    },
                },
            ]
        },
    )
    _write_json(
        project_root / "candidates" / "retreat_routes.json",
        [
            {
                "candidate_id": "retreat.return",
                "label": "Return to trailhead",
                "retreat_type": "return_to_entry",
                "trigger_checkpoint_candidate_id": "cp.view",
                "entry_checkpoint_candidate_id": "cp.start",
                "distance_m": 1000,
                "review_state": "accepted",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
    )
    _write_json(
        project_root / "outputs" / "planned_eta.json",
        {
            "assumption": {
                "planned_start_time": "2026-06-16T08:00:00+08:00",
                "turn_back_checkpoint_node_name": "Viewpoint",
                "turn_back_checkpoint_eta": "2026-06-16T10:30:00+08:00",
                "return_to_entry_eta_if_turn_back_at_checkpoint": (
                    "2026-06-16T11:15:00+08:00"
                ),
                "target_eta": "2026-06-16T12:00:00+08:00",
            },
            "estimates": [
                {
                    "to_node_name": "Trailhead",
                    "eta": "2026-06-16T08:00:00+08:00",
                    "segment_duration_minutes": 0,
                },
                {
                    "to_node_name": "Viewpoint",
                    "eta": "2026-06-16T10:00:00+08:00",
                    "segment_duration_minutes": 120,
                },
                {
                    "to_node_name": "Summit",
                    "eta": "2026-06-16T12:00:00+08:00",
                    "segment_duration_minutes": 120,
                },
            ],
        },
    )
    return project_root


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_route_architecture_changes_plan_after_turn_back_eta() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="現在是不是折返點？",
        current_time="2013-10-08T15:05:00+08:00",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原路線往後段推進。"
    )
    assert result["route_decision"]["turn_back_checkpoint"][
        "turn_back_checkpoint_name"
    ] == "雲海保線所"
    assert "折返 ETA" in result["route_decision"]["main_reasons"][0]
    assert "CHANGE_PLAN" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_delays_retreat_point_status_without_current_context() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="現在是不是撤退點？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_missing_current_context"
    assert result["decision"] == "DELAY"
    assert result["missing_fields"] == ["current_cp_id", "current_time"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "無法確認現在是否為撤退點。"
    )
    assert "current_cp_id" in result["decision_output"]["firstLayer"]["reason"]
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_delays_retreat_window_status_without_current_context() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="撤退點是否即將失去？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_missing_current_context"
    assert result["decision"] == "DELAY"
    assert result["missing_fields"] == ["current_cp_id", "current_time"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "無法確認撤退點是否即將失去。"
    )
    assert "current_cp_id" in result["decision_output"]["firstLayer"]["reason"]
    assert "撤退窗口仍可用" in result["decision_output"]["firstLayer"]["limit"]
    assert "不能確認撤退點是否即將失去" in result["field_answer"]
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_delays_cp_schedule_delta_without_current_context() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="我們現在比計畫晚多少？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_missing_current_context"
    assert result["decision"] == "DELAY"
    assert result["missing_fields"] == ["current_cp_id", "current_time"]
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "無法確認與計畫 CP 通過時間的差距。"
    )
    assert "current_cp_id" in result["decision_output"]["firstLayer"]["reason"]
    assert "完整時間、日照、撤退或天氣 buffer" in result["decision_output"][
        "firstLayer"
    ]["limit"]
    assert "不能確認與計畫 CP 通過時間差距" in result["field_answer"]
    assert result["decision_output"]["allowed"] is False
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_computes_cp_schedule_delta_from_planned_eta() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="現在比計畫晚多少？",
        current_time="2013-10-08T15:10:00+08:00",
        current_cp_id="雲海保線所",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CONDITIONAL_GO"
    status = result["route_decision"]["schedule_delta_status"]
    assert status["current_cp_name"] == "雲海保線所"
    assert status["planned_eta"] == "2013-10-08T14:58:50+08:00"
    assert status["delta_minutes"] == 11.2
    assert status["status"] == "behind_plan"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "目前比計畫晚約 11 分鐘。"
    )
    assert "不得把小幅提前或落後轉成額外停留授權" in result[
        "decision_output"
    ]["firstLayer"]["limit"]
    assert result["decision_output"]["cost"]["scheduleDeltaMinutes"] == 11.2
    assert "時程差約 11.2 分鐘" in result["decision_output"][
        "firstLayer"
    ]["reason"]
    assert result["decision_output"]["runtimeSafetyTruth"] is False


def test_route_architecture_changes_plan_after_missed_checkpoint_deadline() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="11:30 未抵達 CP4 是否要折返？",
        current_time="11:30",
        target_cp_id="CP4",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "不建議錯過 checkpoint deadline 後繼續原計畫。"
    )
    assert result["route_decision"]["target_checkpoint"] == "CP4"
    assert result["route_decision"]["checkpoint_deadline"] == "11:30"
    assert "目標 checkpoint CP4" in result["route_decision"]["main_reasons"][0]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_changes_plan_for_hut_checkin_pressure() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="山屋報到時間快到了，是否需要改計畫？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["decision_output"]["firstLayer"]["decision"] == (
        "建議改變計畫，先處理外部 deadline 壓力。"
    )
    assert result["route_decision"]["deadline_pressure"] == "hut_checkin"
    assert "山屋報到" in result["route_decision"]["main_reasons"][0]
    assert "外部 deadline 壓力" in result["field_answer"]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_changes_plan_for_transport_deadline_pressure() -> None:
    result = assess_scout_route_architecture(
        PROJECT_ROOT,
        query="交通末班車快趕不上了，還能照原計畫嗎？",
        limit=2,
    )

    assert result["answerability"] == "route_architecture_available"
    assert result["decision"] == "CHANGE_PLAN"
    assert result["route_decision"]["deadline_pressure"] == "transport_last_service"
    assert "交通末班/接駁 deadline" in result["route_decision"]["main_reasons"][0]
    assert result["boundary"]["runtime_safety_truth"] is False


def test_route_architecture_output_kind_constant() -> None:
    assert ROUTE_ARCHITECTURE_OUTPUT_KIND == "scout_ai_route_architecture_tool_output"
