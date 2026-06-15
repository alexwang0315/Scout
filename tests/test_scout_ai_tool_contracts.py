from __future__ import annotations

import json
from pathlib import Path

from scout_agent_cli import run_scout_agent_cli
from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
POST_ANALYSIS_ROOT = (
    ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
)
MANIFEST_DIR = ROOT / "tools" / "scout_agent_tool_manifests"
WEARABLE_FIXTURES = [
    ROOT / "tests" / "fixtures" / "wearables" / "apple_health_clean_activity.json",
    ROOT / "tests" / "fixtures" / "wearables" / "apple_health_missing_hr_interval.json",
    ROOT / "tests" / "fixtures" / "wearables" / "garmin_body_battery_provider_values.json",
]
FIELD_OBSERVATION = (
    ROOT
    / "tests"
    / "fixtures"
    / "wearables"
    / "field_observations"
    / "high_hr_drift.json"
)


def test_tool_registry_lists_current_and_future_contracts() -> None:
    registry = tool_registry_output()
    by_id = {tool.tool_id: tool for tool in registry.tools}

    assert registry.artifact_kind == "scout_ai_tool_registry"
    assert "pydantic_ai.tool.search_scout_risk_scores.v0" in by_id
    assert "pydantic_ai.tool.search_scout_terrain_scores.v0" in by_id
    assert "pydantic_ai.tool.search_scout_map_perception.v0" in by_id
    assert "scout.ai.ins_dr_trace.analyze.v0" in by_id
    assert "scout.ai.weather_window.assess.v0" in by_id
    assert "scout.ai.live_navigation_state.assess.v0" in by_id
    assert "scout.ai.safety_boundary.explain.v0" in by_id
    assert ROUTE_READINESS_TOOL_ID in by_id
    assert CONTEXTUAL_PERMISSION_TOOL_ID in by_id
    assert ROUTE_CONTEXT_TOOL_ID in by_id
    assert ROUTE_ARCHITECTURE_TOOL_ID in by_id
    assert EQUIPMENT_RESOURCE_TOOL_ID in by_id
    assert PACE_GUARDIAN_TOOL_ID in by_id
    assert TEAM_STATUS_TOOL_ID in by_id
    assert POST_TRIP_REVIEW_TOOL_ID in by_id
    assert MEDIA_LITERACY_TOOL_ID in by_id
    assert SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID in by_id
    assert ENERGY_VITALS_TOOL_ID in by_id
    assert by_id["pydantic_ai.tool.search_scout_risk_scores.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.ins_dr_trace.analyze.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.weather_window.assess.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.live_navigation_state.assess.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.safety_boundary.explain.v0"].implementation_status == (
        "boundary_explain_only"
    )
    assert by_id[ENERGY_VITALS_TOOL_ID].implementation_status == (
        "partial_existing_surface"
    )
    assert by_id[CONTEXTUAL_PERMISSION_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[ROUTE_READINESS_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[ROUTE_CONTEXT_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[ROUTE_ARCHITECTURE_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[EQUIPMENT_RESOURCE_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[PACE_GUARDIAN_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[TEAM_STATUS_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[POST_TRIP_REVIEW_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[MEDIA_LITERACY_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert "scout.ai.energy_vitals.assess" in by_id[ENERGY_VITALS_TOOL_ID].aliases
    assert "scout.ai.micro_decision.assess" in by_id[
        CONTEXTUAL_PERMISSION_TOOL_ID
    ].aliases
    assert "scout.ai.departure_gate.assess" in by_id[
        ROUTE_READINESS_TOOL_ID
    ].aliases
    assert "scout.ai.experience_guide.assess" in by_id[ROUTE_CONTEXT_TOOL_ID].aliases
    assert "scout.ai.cp_graph.assess" in by_id[ROUTE_ARCHITECTURE_TOOL_ID].aliases
    assert "scout.ai.device_resource.assess" in by_id[EQUIPMENT_RESOURCE_TOOL_ID].aliases
    assert "scout.ai.team_pace_fit.assess" in by_id[PACE_GUARDIAN_TOOL_ID].aliases
    assert "scout.ai.team_guardian.assess" in by_id[TEAM_STATUS_TOOL_ID].aliases
    assert "scout.ai.after_action.assess" in by_id[POST_TRIP_REVIEW_TOOL_ID].aliases
    assert "scout.ai.media_bias.assess" in by_id[MEDIA_LITERACY_TOOL_ID].aliases
    assert "scout.ai.sos_playbook.explain" in by_id[
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    ].aliases
    assert registry.ready_current_tool_count >= 16
    assert registry.executable_tool_count >= registry.ready_current_tool_count
    assert registry.contract_only_tool_count >= 1
    assert registry.implementation_status_counts["ready_current_tool"] >= 15
    assert "ready_current_tool" in registry.tool_ids_by_status
    assert "scout.ai.weather_window.assess.v0" not in registry.missing_evidence_fields_by_tool
    assert registry.boundary.runtime_safety_truth is False
    assert registry.boundary.remote_outbound_send_allowed is False


def test_tool_registry_can_filter_to_ready_current_summary() -> None:
    registry = tool_registry_output(include_not_implemented=False)
    statuses = set(registry.implementation_status_counts)

    assert statuses == {"ready_current_tool"}
    assert registry.tool_count == registry.ready_current_tool_count
    assert registry.contract_only_tool_count == 0
    assert registry.missing_evidence_fields_by_tool == {}
    assert all(tool.aliases for tool in registry.tools)
    assert "pydantic_ai.tool.search_scout_route_structure.v0" in registry.tool_ids_by_status[
        "ready_current_tool"
    ]


def test_execute_ready_current_tool_returns_uniform_result() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.risk_scores.search",
            "project_root": str(PROJECT_ROOT),
            "query": "risk score baseline highest",
            "limit": 3,
        }
    )

    assert result.artifact_kind == "scout_ai_tool_result"
    assert result.status == "completed"
    assert result.tool_id == "pydantic_ai.tool.search_scout_risk_scores.v0"
    assert result.payload["artifact_kind"] == "scout_ai_risk_scores_tool_output"
    assert result.payload["tool_id"] == "pydantic_ai.tool.search_scout_risk_scores.v0"
    assert result.payload["summaries"]["baseline"]["available"] is True
    assert result.payload["answerability"] == "risk_score_decision_available"
    assert result.payload["decision"] == "CHANGE_PLAN"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "CHANGE_PLAN"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "建議改變路線或通過策略。"
    )
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["risk_decision"]["highest_risk_result"]["risk_bucket"] == (
        "high"
    )
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_terrain_scores_returns_conservative_missing_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.terrain_scores.search",
            "project_root": str(PROJECT_ROOT),
            "query": "危險地形在哪些位置?",
            "limit": 3,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == "pydantic_ai.tool.search_scout_terrain_scores.v0"
    assert result.payload["artifact_kind"] == "scout_ai_terrain_scores_tool_output"
    assert result.payload["answerability"] == "terrain_score_missing_evidence"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "DELAY"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["confidence"] == "low"
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "暫緩地形分數判斷。"
    )
    assert "terrain_score_results" in result.missing_fields
    assert result.payload["terrain_decision"]["highest_terrain_result"] is None
    assert result.boundary.runtime_safety_truth is False


def test_execute_pace_guardian_alias_returns_team_pace_fit_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.team_pace_fit.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "隊伍腳程是否能準時抵達下一個 CP？",
            "arguments": {
                "team_members": [
                    {"member_id": "lead", "display_label": "Lead", "pace_mps": 1.1},
                    {
                        "member_id": "slow",
                        "display_label": "Slow member",
                        "pace_mps": 0.6,
                        "reserve_minutes": 9,
                        "fatigue_band": "tired",
                    },
                ],
                "minutes_to_next_cp": 20,
                "leader_accepts_slowest_basis": True,
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == PACE_GUARDIAN_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_pace_guardian_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_pace_guardian_tool_output"
    assert result.payload["answerability"] == "pace_fit_decision_available"
    assert result.payload["decision"] == "CHANGE_PLAN"
    assert result.payload["pace_guardian"]["average_pace_used"] is False
    assert result.payload["team_pace_fit"]["slowest_member"]["label"] == "Slow member"
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_route_architecture_alias_returns_cp_graph_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.cp_graph.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "下一個撤退點在哪？這條路線難點在哪？",
            "limit": 4,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_route_architecture_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_route_architecture_tool_output"
    assert result.payload["answerability"] == "route_architecture_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["cp_graph"]["node_count"] == 124
    assert result.payload["cp_graph"]["edge_count"] == 123
    assert result.payload["route_architecture"]["turn_back"][
        "turn_back_checkpoint_name"
    ] == "雲海保線所"
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_equipment_resource_alias_returns_resource_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.device_resource.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "手機電量和頭燈水量夠嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == EQUIPMENT_RESOURCE_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_equipment_resource_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_equipment_resource_tool_output"
    assert result.payload["answerability"] == "equipment_resource_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["equipment_resource"]["role"] == (
        "Equipment / Resource Intelligence"
    )
    assert "water_liters" in result.missing_fields
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_team_status_alias_returns_remote_contact_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.team_guardian.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "後隊在哪？留守回報準備好了嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == TEAM_STATUS_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_team_status_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_team_status_tool_output"
    assert result.payload["answerability"] == "team_status_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert "member_positions_or_last_heard" in result.missing_fields
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_post_trip_review_alias_returns_learning_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.after_action.assess",
            "project_root": str(POST_ANALYSIS_ROOT),
            "query": "行後回顧要更新哪些下一次規劃？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == POST_TRIP_REVIEW_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_post_trip_review_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_post_trip_review_tool_output"
    assert result.payload["answerability"] == "post_trip_review_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["post_trip_review"]["role"] == (
        "Post-Trip Review / Learning Governance"
    )
    assert "subjective_difficulty" in result.missing_fields
    assert result.payload["completed_trip_summary"]["edge_count"] == 73
    assert result.payload["boundary"]["learning_write_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_route_readiness_alias_returns_departure_gate_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.departure_gate.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "出發前 Go/No-Go 可以出發嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_READINESS_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_route_readiness_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_route_readiness_tool_output"
    assert result.payload["answerability"] == "route_readiness_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "DELAY"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == "建議延後。"
    assert "不得出發" in result.payload["decision_output"]["firstLayer"]["limit"]
    assert result.payload["decision_output"]["departureApprovalGranted"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["route_readiness"]["role"] == (
        "Pre-Trip Route Readiness / Departure Gate"
    )
    assert result.payload["route_readiness"]["decision_output"]["decision"] == "DELAY"
    assert result.payload["results"][0]["decision_output"]["decision"] == "DELAY"
    assert "user_experience_level" in result.missing_fields
    assert result.payload["departure_gate"]["approval_granted"] is False
    assert result.payload["boundary"]["runtime_handoff_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_route_readiness_returns_guided_only_for_beginner_high_demand_route() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.route_readiness.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "beginner pretrip Go/No-Go 可以自主出發嗎？",
            "arguments": {
                "user_experience_level": "beginner",
                "transport_access_plan": "user_confirmed",
                "team_slowest_basis_confirmed": True,
                "departure_time_confirmed": True,
                "weather_reviewed": True,
                "daylight_reviewed": True,
                "equipment_confirmed": True,
                "remote_contact_confirmed": True,
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_READINESS_TOOL_ID
    assert result.payload["answerability"] == "route_readiness_decision_available"
    assert result.payload["decision"] == "GUIDED_ONLY"
    assert result.payload["allowed"] is False
    assert result.payload["missing_fields"] == []
    assert result.payload["decision_output"]["decision"] == "GUIDED_ONLY"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "只建議在合格帶領下進入。"
    )
    assert "不得自主出發" in result.payload["decision_output"]["firstLayer"]["limit"]
    assert result.payload["guided_only_gate"]["required"] is True
    assert result.payload["guided_only_gate"]["autonomous_departure_allowed"] is False
    demand = result.payload["route_demand_profile"]
    assert demand["route_demand"] == "high"
    assert demand["requires_guided_for_low_experience"] is True
    package = result.payload["pretrip_decision_package"]
    assert package["required_outputs"]["pretrip_decision"] == "GUIDED_ONLY"
    assert package["required_outputs"]["guided_only_gate"]["required"] is True
    assert package["decision_limits"]["allowed"] is False
    assert package["decision_limits"]["autonomous_departure_allowed"] is False
    assert result.payload["departure_gate"]["approval_granted"] is False
    assert result.payload["boundary"]["runtime_handoff_performed"] is False
    assert result.boundary.runtime_safety_truth is False


def test_execute_media_literacy_alias_returns_bias_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.media_bias.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "IG 大崩壁美照會不會誤導？想去打卡。",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == MEDIA_LITERACY_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_media_literacy_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_media_literacy_tool_output"
    assert result.payload["answerability"] == "media_literacy_missing_context"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["media_literacy"]["role"] == "Media Literacy / Bias Sentinel"
    assert "fresh_weather_or_route_condition_review" in result.missing_fields
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_weather_tool_returns_read_only_weather_evidence_gap() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.weather_window.assess.v0",
            "project_root": str(PROJECT_ROOT),
            "query": "明天午後雷雨要不要提早紮營",
        }
    )

    assert result.status == "completed"
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_weather_window_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_weather_window_tool_output"
    assert result.payload["tool_id"] == "scout.ai.weather_window.assess.v0"
    assert result.payload["answerability"] == "weather_placeholder_only"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert "天氣決策" in result.payload["field_answer"]
    assert "provider" in result.missing_fields
    assert "ttl_s" in result.missing_fields
    assert "route_weather_package" in result.missing_fields
    assert result.payload["boundary"]["client_cwa_api_key_allowed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_live_navigation_state_assessor_returns_read_only_missing_fields() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.live_navigation_state.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "哪些風險目前只是候選，不能觸發 Ln？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == "scout.ai.live_navigation_state.assess.v0"
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_live_navigation_state_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_live_navigation_state_tool_output"
    assert result.payload["tool_id"] == "scout.ai.live_navigation_state.assess.v0"
    assert result.payload["assessment_kind"] == "read_only_live_navigation_snapshot"
    assert result.payload["answerability"] == "snapshot_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert "地形導航判斷" in result.payload["field_answer"]
    assert "lat" in result.missing_fields
    assert "lat" in result.payload["missing_fields"]
    assert "lon" in result.payload["missing_fields"]
    assert "horizontal_accuracy_m" in result.payload["missing_fields"]
    assert "ins_dr_source" in result.payload["missing_fields"]
    assert result.payload["route_query_plan"]["status"] == "insufficient_position"
    assert result.payload["boundary"]["live_hardware_read_performed"] is False
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_live_navigation_state_assessor_returns_navigation_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.live_navigation_state.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "剛剛岔路我有走對嗎？現在要不要回主線？",
            "arguments": {
                "observed_at": "2026-06-15T08:00:00+08:00",
                "lat": 24.0509,
                "lon": 121.216,
                "elevation_m": 2220,
                "source": "caller_fixture",
                "hdop": 0.9,
                "horizontal_accuracy_m": 5,
                "fix_quality": "3d",
                "satellite_count": 12,
                "max_cno_dbhz": 38,
                "heading_deg": 94,
                "course_deg": 96,
                "speed_mps": 0.82,
                "nearest_route_distance_m": 8,
                "route_progress_m": 1200,
                "nearest_cp_id": "cp.004",
                "ins_dr_source": "pdr_anchor",
                "confidence": 0.82,
                "uncertainty_m": 8,
                "last_anchor_at": "2026-06-15T07:58:00+08:00",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == "scout.ai.live_navigation_state.assess.v0"
    assert result.payload["answerability"] == "snapshot_evidence_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["navigation_terrain"]["role"] == (
        "Navigation & Terrain Intelligence"
    )
    assert result.payload["navigation_decision"]["route_fit_status"] == (
        "on_route_corridor"
    )
    assert result.missing_fields == []
    assert result.boundary.runtime_safety_truth is False


def test_execute_map_perception_search_returns_candidate_decision_output() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.map_perception.search",
            "project_root": str(PROJECT_ROOT),
            "query": "CP001 附近有沒有標註?",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == MAP_PERCEPTION_TOOL_ID
    assert result.output_artifact_kind == "scout_ai_map_perception_tool_output"
    assert result.payload["tool_id"] == MAP_PERCEPTION_TOOL_ID
    assert result.payload["assessment_kind"] == "read_only_map_perception"
    assert result.payload["answerability"] == "map_perception_evidence_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可作為候選地圖參考。"
    )
    assert result.payload["map_perception"]["role"] == (
        "Navigation & Terrain Intelligence / Map Perception"
    )
    assert result.payload["map_perception"]["review_required"] is True
    assert result.payload["results"][0]["evidence_type"] == "ocr_label"
    assert result.missing_fields == []
    assert result.boundary.runtime_safety_truth is False


def test_execute_ins_dr_trace_analyzer_returns_read_only_missing_evidence() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.ins_dr_trace.analyze",
            "project_root": str(PROJECT_ROOT),
            "query": "GPS-only 軌跡和 INS/DR 軌跡差多少？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == "scout.ai.ins_dr_trace.analyze.v0"
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_ins_dr_trace_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_ins_dr_trace_tool_output"
    assert result.payload["tool_id"] == INS_DR_TRACE_TOOL_ID
    assert result.payload["analysis_kind"] == "read_only_ins_dr_trace"
    assert result.payload["answerability"] in {
        "missing_trace_evidence",
        "missing_gps_trajectory",
        "insufficient_aligned_samples",
        "trace_metrics_available",
    }
    assert result.payload["decision"] == "DELAY"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "DELAY"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "暫緩 INS/DR trace 判斷。"
    )
    assert result.payload["ins_dr_trace"]["role"] == (
        "Navigation Truth / INS-DR Trace Guard"
    )
    assert result.payload["ins_dr_trace"]["runtime_safety_truth"] is False
    assert "ins_dr_estimates_jsonl" in result.missing_fields
    assert "gps_only_trajectory" in result.missing_fields
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_safety_boundary_explainer_returns_read_only_missing_fields() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.safety_boundary.explain",
            "project_root": str(PROJECT_ROOT),
            "query": "哪些風險目前只是候選，不能觸發 Ln？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == "scout.ai.safety_boundary.explain.v0"
    assert result.implementation_status == "boundary_explain_only"
    assert result.output_artifact_kind == "scout_ai_safety_boundary_explainer_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_safety_boundary_explainer_tool_output"
    assert result.payload["tool_id"] == SAFETY_BOUNDARY_TOOL_ID
    assert result.payload["answerability"] == "safety_boundary_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "DELAY"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "Hold safety-state changes until admission evidence is complete."
    )
    assert result.payload["safety_boundary"]["role"] == (
        "Safety Boundary / Runtime Admission Guard"
    )
    assert result.payload["safety_boundary"]["runtime_safety_truth"] is False
    assert "admission_state" in result.payload["missing_fields"]
    assert "operator_review_status" in result.payload["missing_fields"]
    assert "admission_state" in result.missing_fields
    assert "operator_review_status" in result.missing_fields
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_energy_vitals_assessor_returns_read_only_missing_fields() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.energy_vitals.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "心率資料能不能支持疲勞判斷？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ENERGY_VITALS_TOOL_ID
    assert result.implementation_status == "partial_existing_surface"
    assert result.output_artifact_kind == "scout_ai_energy_vitals_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_energy_vitals_tool_output"
    assert result.payload["tool_id"] == ENERGY_VITALS_TOOL_ID
    assert result.payload["assessment_kind"] == "read_only_energy_vitals"
    assert result.payload["answerability"] == "energy_vitals_missing_required_fields"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "DELAY"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["confidence"] == "low"
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "建議延後體能/穿戴判斷。"
    )
    assert "不得把此回答當成現場 permission" in (
        result.payload["decision_output"]["firstLayer"]["limit"]
    )
    assert result.payload["energy_vitals"]["runtime_safety_truth"] is False
    assert result.payload["results"][0]["decision"] == "DELAY"
    assert "heart_rate_bpm" in result.payload["missing_fields"]
    assert "baseline_window_days" in result.payload["missing_fields"]
    assert "reserve_score" in result.payload["missing_fields"]
    assert result.payload["boundary"]["medical_diagnosis"] is False
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_energy_vitals_assessor_uses_normalized_evidence_only() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.energy_vitals.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "我現在心率偏高又很累，需要休息嗎?",
            "arguments": {
                "subject_id": "local_user.private",
                "observed_at": "2026-06-07T08:00:00Z",
                "heart_rate_bpm": 162,
                "hrv_ms": 42,
                "body_battery_or_provider_energy": 35,
                "pace_mps": 0.72,
                "cadence": 88,
                "activity_load": 130.5,
                "baseline_window_days": 90,
                "reserve_score": 38,
                "reserve_band": "rest_suggested",
                "heart_rate_drift_ratio": 0.174,
                "privacy_scope": "private_vitals",
                "source_provider": "apple_watch_local_summary",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ENERGY_VITALS_TOOL_ID
    assert result.payload["answerability"] == "energy_vitals_advisory_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["decision_output"]["confidence"] == "medium"
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["cost"]["recommendedRestMinutes"] == 10
    assert "短休最多 10 分鐘" in (
        result.payload["decision_output"]["firstLayer"]["limit"]
    )
    assert result.payload["results"][0]["decision_output"]["decision"] == (
        "CONDITIONAL_GO"
    )
    assert result.payload["missing_fields"] == []
    assert result.payload["provided_fields"]["heart_rate_bpm"] == 162.0
    assert result.payload["provided_fields"]["reserve_band"] == "rest_suggested"
    assert result.payload["advisory"]["cue_band"] == "rest_suggested"
    assert result.payload["advisory"]["heart_rate_drift_ratio"] == 0.174
    assert "not medical diagnosis" in result.payload["results"][0]["snippet"]
    assert result.payload["privacy"]["raw_health_payload_shared"] is False
    assert result.payload["boundary"]["medical_diagnosis"] is False
    assert result.payload["boundary"]["provider_values_are_scout_truth"] is False
    assert result.payload["boundary"]["safety_api_called"] is False


def test_execute_energy_vitals_assessor_loads_workspace_energy_artifacts(tmp_path: Path) -> None:
    energy = write_energy_reserve_artifacts(
        load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT),
        output_dir=tmp_path,
    )

    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.energy_vitals.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "心率資料能不能支持疲勞判斷？",
            "arguments": {
                "observed_at": "2026-06-07T08:00:00Z",
                "baseline_path": str(energy["baseline_path"]),
                "observation_path": str(FIELD_OBSERVATION),
            },
        }
    )

    assert result.status == "completed"
    assert result.payload["answerability"] == "energy_vitals_advisory_available"
    assert result.payload["provided_fields"]["heart_rate_bpm"] == 162
    assert result.payload["provided_fields"]["reserve_band"] == "rest_suggested"
    assert result.payload["provided_fields"]["reserve_score"] > 0
    assert result.payload["provided_fields"]["heart_rate_drift_ratio"] == 0.174
    assert result.payload["advisory"]["cue_band"] == "rest_suggested"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert "Missing field: hrv_ms" in result.payload["decision_output"][
        "uncertaintyNotes"
    ]
    assert "建議短暫休息" in result.payload["advisory"]["message_zh"]
    assert "hrv_ms" in result.payload["missing_fields"]
    assert "pace_mps" in result.payload["missing_fields"]
    assert result.payload["source_report"][0]["status"] == "loaded"
    assert result.payload["source_report"][1]["status"] == "loaded"
    assert result.payload["privacy"]["raw_health_payload_shared"] is False
    assert result.payload["boundary"]["medical_diagnosis"] is False
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["provider_values_are_scout_truth"] is False


def test_execute_contextual_permission_assessor_returns_bounded_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "我可以在這裡停下來拍一段影片嗎?",
            "arguments": {
                "current_time": "2026-06-07T13:36:00+08:00",
                "current_cp_id": "CP3",
                "next_cp_id": "CP4",
                "remaining_safety_buffer_minutes": 21,
                "current_delay_minutes": 9,
                "next_segment_uncertainty_minutes": 3,
                "weather_reserve_minutes": 2,
                "communication_status": "ok",
                "equipment_status": "ok",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_contextual_permission_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_contextual_permission_tool_output"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["allowed"] is True
    assert result.payload["contextual_permission"]["maxDurationMinutes"] == 6
    assert result.payload["contextual_permission"]["leaveBy"] == (
        "2026-06-07T13:42:00+08:00"
    )
    assert result.payload["contextual_permission"]["cost"][
        "timeBufferChangeMinutes"
    ] == -6
    assert result.payload["decision_object"] == result.payload["contextual_permission"]
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可以，最多 6 分鐘。"
    )
    assert result.payload["field_answer"].startswith("[決策] 可以，最多 6 分鐘。")
    assert result.payload["risk_budget"]["authorizedDurationMinutes"] == 16
    assert result.missing_fields == []
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.payload["boundary"]["safety_api_called"] is False


def test_execute_contextual_permission_assessor_blocks_split_team_summit() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "可以讓走得快的人先去山頂嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "split_team"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["allowed"] is False
    assert result.payload["missing_fields"] == []
    assert result.payload["decision_object"] == result.payload["contextual_permission"]
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議分隊。"
    )
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert "走得快的人先去山頂" in result.payload["contextual_permission"][
        "mainReasons"
    ][0]
    assert "保持隊伍完整" in result.payload["contextual_permission"]["nextAction"]
    assert result.boundary.runtime_safety_truth is False


def test_execute_survival_playbook_alias_returns_boundary_safe_guidance() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.sos_playbook.explain",
            "project_root": str(PROJECT_ROOT),
            "query": "不確定自己在哪，可以下切溪谷找路嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == (
        "scout_ai_survival_incident_playbook_tool_output"
    )
    assert result.payload["artifact_kind"] == (
        "scout_ai_survival_incident_playbook_tool_output"
    )
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["survival_incident_playbook"]["share_policy"][
        "can_send_or_notify"
    ] is False
    assert result.payload["boundary"]["real_sos_sent"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert "current_location_status" in result.missing_fields


def test_execute_contextual_permission_assessor_derives_planned_eta_buffer() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": CONTEXTUAL_PERMISSION_TOOL_ID,
            "project_root": str(PROJECT_ROOT),
            "query": "我可以在這裡停下來拍一段影片嗎?",
            "arguments": {
                "current_time": "2013-10-08T14:52:50+08:00",
                "next_cp_id": "雲海保線所",
                "communication_status": "ok",
                "equipment_status": "ok",
            },
        }
    )

    assert result.status == "completed"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["allowed"] is False
    assert result.payload["max_duration_minutes"] is None
    assert result.payload["risk_budget"]["remainingSafetyBufferMinutes"] == 6.0
    assert result.payload["risk_budget"]["authorizedDurationMinutes"] == 0
    assert result.payload["risk_budget"]["daylightReserveMinutes"] == 60.0
    assert result.payload["risk_budget"]["weatherReserveMinutes"] == 15.0
    assert result.payload["risk_budget"]["nextSegmentUncertaintyMinutes"] == 10.0
    assert result.payload["risk_budget_source"]["source_status"] == (
        "derived_from_planned_eta_candidate"
    )
    assert result.payload["risk_budget_source"]["reserve_sources"]
    assert result.payload["risk_budget_source"]["runtime_safety_truth"] is False
    assert result.missing_fields == []
    assert any("candidate planned ETA" in warning for warning in result.warnings)
    assert any("reserve was deducted" in warning for warning in result.warnings)


def test_execute_contextual_permission_passes_energy_vitals_reserve_path(
    tmp_path: Path,
) -> None:
    project_root = _write_reviewed_contextual_permission_project(tmp_path)

    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.micro_decision.assess",
            "project_root": str(project_root),
            "query": "我可以在這裡停下來拍一段影片嗎?",
            "arguments": {
                "current_time": "2026-06-07T13:36:00+08:00",
                "next_cp_id": "CP4",
                "communication_status": "ok",
                "equipment_status": "ok",
                "energy_vitals_path": "outputs/energy_vitals.json",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["risk_budget"]["remainingSafetyBufferMinutes"] == 6.0
    assert result.payload["risk_budget"]["slowestMemberReserveMinutes"] == 10.0
    assert result.payload["risk_budget"]["authorizedDurationMinutes"] == 0
    slowest = [
        item
        for item in result.payload["risk_budget_source"]["reserve_sources"]
        if item["reserve_field"] == "slowest_member_reserve_minutes"
    ]
    assert len(slowest) == 1
    assert slowest[0]["source_path"] == "outputs/energy_vitals.json"
    assert slowest[0]["raw_health_payload_embedded"] is False
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.missing_fields == []


def test_execute_route_context_assessor_returns_experience_guide_candidates() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.experience_guide.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "哪裡適合拍攝或觀察大景?",
            "limit": 4,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_CONTEXT_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_route_context_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_route_context_tool_output"
    assert result.payload["answerability"] == "route_context_available"
    assert result.payload["route_context"]["role"] == "Experience Guide"
    assert result.payload["route_context"]["stop_permission_required"] is True
    assert result.payload["result_count"] >= 1
    assert any(item["label"] == "稜線啞口觀景點" for item in result.payload["results"])
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.missing_fields == []


def test_agent_manifest_runs_tool_registry_and_tool_run(tmp_path: Path) -> None:
    registry_output = _run_manifest(
        "scout.ai.tool_registry.describe",
        {"include_not_implemented": True},
        tmp_path,
    )

    assert registry_output["artifact_kind"] == "scout_ai_tool_registry"
    assert registry_output["tool_count"] >= 10
    assert registry_output["ready_current_tool_count"] >= 8
    assert registry_output["contract_only_tool_count"] >= 1
    assert "scout.ai.weather_window.assess.v0" not in registry_output[
        "missing_evidence_fields_by_tool"
    ]
    assert any(
        tool["tool_id"] == "pydantic_ai.tool.search_scout_route_structure.v0"
        for tool in registry_output["tools"]
    )

    run_output = _run_manifest(
        "scout.ai.tool.run",
        {
            "tool_id": "pydantic_ai.tool.search_scout_route_structure.v0",
            "project_root": str(PROJECT_ROOT),
            "query": "有多少個 CP?",
            "limit": 2,
        },
        tmp_path,
    )

    assert run_output["artifact_kind"] == "scout_ai_tool_result"
    assert run_output["status"] == "completed"
    assert run_output["payload"]["artifact_kind"] == "scout_ai_route_structure_tool_output"
    assert run_output["payload"]["summaries"]["checkpoint_count"] == 124
    assert run_output["boundary"]["runtime_safety_truth"] is False


def _run_manifest(
    tool_id: str,
    request_payload: dict[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    request = tmp_path / f"{tool_id}.request.json"
    request.write_text(json.dumps(request_payload, ensure_ascii=False), encoding="utf-8")
    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            tool_id,
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    return json.loads(payload["outputs"]["stdout"])


def _write_reviewed_contextual_permission_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "reviewed_contextual_permission_project"
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "reviewed_contextual_permission_project",
                "planned_eta_ref": "outputs/planned_eta.json",
                "weather_daylight_evidence_ref": "outputs/weather_daylight_evidence.json",
                "plan_validation_candidates_ref": "outputs/plan_validation_candidates.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "planned_eta.json").write_text(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (outputs / "plan_validation_candidates.json").write_text(
        json.dumps({"status": "reviewed", "findings": []}, ensure_ascii=False),
        encoding="utf-8",
    )
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
