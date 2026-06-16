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
from scout_review_gap_tool import REVIEW_GAP_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_live_navigation_state_tool import (
    LIVE_NAVIGATION_STATE_TOOL_ID,
    NMEA_ROUTE_RISK_PROBE_TOOL_ID,
)
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
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
ROUTE_BRIEFING_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "route_briefing"
    / "chilai_nanhua_research.json"
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
    assert NMEA_ROUTE_RISK_PROBE_TOOL_ID in by_id
    assert NAVIGATION_TERRAIN_TOOL_ID in by_id
    assert "scout.ai.safety_boundary.explain.v0" in by_id
    assert ROUTE_READINESS_TOOL_ID in by_id
    assert CONTEXTUAL_PERMISSION_TOOL_ID in by_id
    assert ROUTE_CONTEXT_TOOL_ID in by_id
    assert ROUTE_ARCHITECTURE_TOOL_ID in by_id
    assert EQUIPMENT_RESOURCE_TOOL_ID in by_id
    assert PACE_GUARDIAN_TOOL_ID in by_id
    assert TEAM_STATUS_TOOL_ID in by_id
    assert POST_TRIP_REVIEW_TOOL_ID in by_id
    assert REVIEW_GAP_TOOL_ID in by_id
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
    assert by_id[NMEA_ROUTE_RISK_PROBE_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[NMEA_ROUTE_RISK_PROBE_TOOL_ID].implementation_gap is None
    assert by_id[NAVIGATION_TERRAIN_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.safety_boundary.explain.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[ENERGY_VITALS_TOOL_ID].implementation_status == "ready_current_tool"
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
    assert by_id[REVIEW_GAP_TOOL_ID].implementation_status == "ready_current_tool"
    assert by_id[MEDIA_LITERACY_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert by_id[SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID].implementation_status == (
        "ready_current_tool"
    )
    assert "scout.ai.energy_vitals.assess" in by_id[ENERGY_VITALS_TOOL_ID].aliases
    assert "energy_vitals_snapshot_path" in by_id[
        ENERGY_VITALS_TOOL_ID
    ].optional_fields
    assert "scout.ai.micro_decision.assess" in by_id[
        CONTEXTUAL_PERMISSION_TOOL_ID
    ].aliases
    assert "minutes_to_next_cp" in by_id[
        CONTEXTUAL_PERMISSION_TOOL_ID
    ].optional_fields
    assert "scout.ai.departure_gate.assess" in by_id[
        ROUTE_READINESS_TOOL_ID
    ].aliases
    assert "pretrip_input_bundle_path" in by_id[
        ROUTE_READINESS_TOOL_ID
    ].optional_fields
    assert "route_weather_package_path" in by_id[
        ROUTE_READINESS_TOOL_ID
    ].optional_fields
    assert "user_goal" in by_id[ROUTE_READINESS_TOOL_ID].optional_fields
    assert "scout.ai.experience_guide.assess" in by_id[ROUTE_CONTEXT_TOOL_ID].aliases
    assert "route_briefing_path" in by_id[ROUTE_CONTEXT_TOOL_ID].optional_fields
    assert "media quality gate" in by_id[ROUTE_CONTEXT_TOOL_ID].description
    assert "website chrome" in by_id[ROUTE_CONTEXT_TOOL_ID].description
    assert "scout.ai.cp_graph.assess" in by_id[ROUTE_ARCHITECTURE_TOOL_ID].aliases
    assert "scout.ai.device_resource.assess" in by_id[EQUIPMENT_RESOURCE_TOOL_ID].aliases
    assert "scout.ai.map_readiness.assess" in by_id[
        NAVIGATION_TERRAIN_TOOL_ID
    ].aliases
    assert "scout.ai.nmea_live_navigation_probe.assess" in by_id[
        NMEA_ROUTE_RISK_PROBE_TOOL_ID
    ].aliases
    assert "live_navigation_snapshot_path" in by_id[
        LIVE_NAVIGATION_STATE_TOOL_ID
    ].optional_fields
    assert "lat" in by_id[NMEA_ROUTE_RISK_PROBE_TOOL_ID].optional_fields
    assert "live_navigation_snapshot_path" in by_id[
        NMEA_ROUTE_RISK_PROBE_TOOL_ID
    ].optional_fields
    assert "scout.ai.runtime_admission.assess" in by_id[
        SAFETY_BOUNDARY_TOOL_ID
    ].aliases
    assert "admission_state" in by_id[SAFETY_BOUNDARY_TOOL_ID].optional_fields
    assert "safety_admission_trace_path" in by_id[
        SAFETY_BOUNDARY_TOOL_ID
    ].optional_fields
    assert "junction_points_known" in by_id[
        NAVIGATION_TERRAIN_TOOL_ID
    ].optional_fields
    assert "terrain_risk_layers_understood" in by_id[
        NAVIGATION_TERRAIN_TOOL_ID
    ].optional_fields
    assert "scout.ai.team_pace_fit.assess" in by_id[PACE_GUARDIAN_TOOL_ID].aliases
    assert "scout.ai.team_guardian.assess" in by_id[TEAM_STATUS_TOOL_ID].aliases
    assert "scout.ai.after_action.assess" in by_id[POST_TRIP_REVIEW_TOOL_ID].aliases
    assert "post_trip_review_context_path" in by_id[
        POST_TRIP_REVIEW_TOOL_ID
    ].optional_fields
    assert "scout.ai.provenance_gap.assess" in by_id[REVIEW_GAP_TOOL_ID].aliases
    assert "category" in by_id[REVIEW_GAP_TOOL_ID].optional_fields
    assert "scout.ai.media_bias.assess" in by_id[MEDIA_LITERACY_TOOL_ID].aliases
    assert "media_context_path" in by_id[MEDIA_LITERACY_TOOL_ID].optional_fields
    assert "scout.ai.sos_playbook.explain" in by_id[
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    ].aliases
    assert "incident_context_path" in by_id[
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
    ].optional_fields
    assert registry.ready_current_tool_count >= 16
    assert registry.executable_tool_count >= registry.ready_current_tool_count
    assert registry.contract_only_tool_count == 0
    assert registry.implementation_status_counts["ready_current_tool"] >= 26
    assert "boundary_explain_only" not in registry.implementation_status_counts
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


def test_execute_pace_guardian_extracts_delay_from_summit_question() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.team_pace_fit.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "我們晚了 30 分鐘，還可以繼續攻頂嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == PACE_GUARDIAN_TOOL_ID
    assert result.payload["answerability"] == "pace_fit_decision_available"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["schedule_pressure"]["current_delay_minutes"] == 30.0
    assert result.payload["decision_output"]["cost"]["scheduleDelayMinutes"] == 30.0
    assert result.payload["decision_output"]["decision"] == "NO_GO"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == "不建議繼續攻頂。"
    assert "目前已落後約 30 分鐘" in result.payload["decision_output"]["firstLayer"]["reason"]
    assert result.missing_fields == []
    assert result.payload["team_pace_fit"]["slowest_member"]["label"] == (
        "Teammate placeholder"
    )
    assert result.payload["pace_guardian"]["average_pace_used"] is False
    assert result.boundary.runtime_safety_truth is False


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


def test_execute_route_architecture_requires_current_context_for_turnback_status() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.cp_graph.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "現在是不是折返點？",
            "limit": 4,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.payload["answerability"] == "route_architecture_missing_current_context"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["missing_fields"] == ["current_cp_id", "current_time"]
    assert result.missing_fields == ["current_cp_id", "current_time"]
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "無法確認現在是否為折返點。"
    )
    assert "雲海保線所" in result.payload["decision_output"]["firstLayer"]["reason"]
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["route_decision"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_route_architecture_detects_current_turnback_checkpoint() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.cp_graph.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "現在是不是折返點？",
            "arguments": {
                "current_cp_id": "雲海保線所",
                "current_time": "2013-10-08T14:59:00+08:00",
            },
            "limit": 4,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.payload["answerability"] == "route_architecture_available"
    assert result.payload["decision"] == "CHANGE_PLAN"
    assert result.payload["missing_fields"] == []
    assert result.missing_fields == []
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議照原路線往後段推進。"
    )
    assert "目前 CP 符合計畫折返 checkpoint" in result.payload[
        "decision_output"
    ]["firstLayer"]["reason"]
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_route_architecture_compares_local_turnback_clock() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.cp_graph.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "現在是不是折返點？",
            "arguments": {
                "current_cp_id": "雲海保線所",
                "current_time": "15:10",
            },
            "limit": 4,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_ARCHITECTURE_TOOL_ID
    assert result.payload["answerability"] == "route_architecture_available"
    assert result.payload["decision"] == "CHANGE_PLAN"
    assert result.payload["missing_fields"] == []
    reason = result.payload["decision_output"]["firstLayer"]["reason"]
    assert "目前時間已到或超過折返 ETA" in reason
    assert "目前 CP 符合計畫折返 checkpoint" in reason
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
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
    assert result.payload["answerability"] == "equipment_resource_decision_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["equipment_resource"]["role"] == (
        "Equipment / Resource Intelligence"
    )
    assert result.missing_fields == []
    assert result.payload["resource_state"]["water_liters"] == 2.0
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
    assert result.payload["answerability"] == "team_status_decision_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["team_status_guardian"]["role"] == (
        "Team Status / Remote Contact Governance"
    )
    assert result.missing_fields == []
    assert result.payload["team_status"]["rendezvous_point"] == "雲海保線所"
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
    assert result.payload["answerability"] == "route_readiness_decision_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可有條件進入人工出發門檢。"
    )
    assert result.payload["decision_output"]["departureApprovalGranted"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["route_readiness"]["role"] == (
        "Pre-Trip Route Readiness / Departure Gate"
    )
    assert result.payload["route_readiness"]["decision_output"]["decision"] == (
        "CONDITIONAL_GO"
    )
    assert result.payload["results"][0]["decision_output"]["decision"] == (
        "CONDITIONAL_GO"
    )
    assert result.missing_fields == []
    assert result.payload["debug_sources"]["pretrip_input_bundle_source"] == (
        "outputs/pretrip_input_bundle.reviewed.json"
    )
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
                "user_goal": "training",
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


def test_execute_navigation_terrain_alias_returns_map_readiness_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.navigation_terrain.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "這條路地圖力需求很高，但我們沒有第二套定位備援，可以自己去嗎？",
            "arguments": {"backup_positioning_available": False},
        }
    )

    assert result.status == "completed"
    assert result.tool_id == NAVIGATION_TERRAIN_TOOL_ID
    assert result.output_artifact_kind == "scout_ai_navigation_terrain_tool_output"
    assert result.payload["decision"] == "GUIDED_ONLY"
    assert result.payload["decision_output"]["decision"] == "GUIDED_ONLY"
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議自主前往。"
    )
    assert result.payload["navigation_terrain"]["role"] == (
        "Navigation & Terrain Intelligence / Map Readiness"
    )
    assert result.payload["positioning_readiness"][
        "backup_positioning_available"
    ] is False
    assert result.payload["debug_collection"]["writes_performed"] is False
    assert result.boundary.runtime_safety_truth is False


def test_execute_navigation_terrain_blocks_unknown_junctions_and_risk_layers() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.navigation_terrain.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "不知道岔路點，也看不懂地形風險圖層，可以自主前往嗎？",
            "arguments": {
                "offline_map_downloaded": True,
                "gpx_loaded_on_device": True,
                "contour_skill_confirmed": True,
                "terrain_feature_skill_confirmed": True,
                "junction_points_known": False,
                "retreat_direction_understood": True,
                "backup_positioning_available": True,
                "terrain_risk_layers_understood": False,
                "team_map_user_count": 2,
            },
        }
    )

    assert result.status == "completed"
    assert result.payload["decision"] == "GUIDED_ONLY"
    assert result.payload["missing_fields"] == []
    assert result.payload["map_readiness"]["junction_points_known"] is False
    assert result.payload["map_readiness"]["terrain_risk_layers_understood"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議自主前往。"
    )
    assert result.boundary.runtime_safety_truth is False


def test_execute_review_gap_alias_returns_provenance_gap_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.provenance_gap.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "哪些天氣證據還沒有人工審核，不能升格為出發依據？",
            "arguments": {"category": "weather_daylight"},
        }
    )

    assert result.status == "completed"
    assert result.tool_id == REVIEW_GAP_TOOL_ID
    assert result.output_artifact_kind == "scout_ai_review_gap_tool_output"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["review_gap"]["counts"]["unresolved_review_count"] == 1
    assert result.payload["review_governance"]["review_write_performed"] is False
    assert result.payload["decision_output"]["reviewWritePerformed"] is False
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
    assert result.payload["answerability"] == "media_literacy_decision_available"
    assert result.payload["source_status"] == "reviewed_media_literacy_context"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["media_literacy"]["role"] == "Media Literacy / Bias Sentinel"
    assert result.missing_fields == []
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_media_literacy_blocks_social_photo_detour() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.media_bias.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "大家都說旁邊那個點很好拍，可以繞去嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == MEDIA_LITERACY_TOOL_ID
    assert result.payload["answerability"] == "media_literacy_missing_context"
    assert result.payload["action"] == "reroute"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["allowed"] is False
    assert result.payload["decision_output"]["action"] == "reroute"
    assert result.payload["decision_output"]["decision"] == "NO_GO"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議為媒體點位停留或改線。"
    )
    bias_ids = {
        item["bias_id"]
        for item in result.payload["media_bias_analysis"]["detected_biases"]
    }
    assert {"beauty_photo_bias", "survivorship_bias"} <= bias_ids
    assert result.payload["media_bias_analysis"]["input_state"][
        "reroute_pressure"
    ] is True
    assert result.payload["media_bias_analysis"]["input_state"][
        "detour_or_stop_pressure"
    ] is True
    assert "route_context_or_target_point" in result.missing_fields
    assert result.payload["boundary"]["runtime_safety_truth"] is False


def test_execute_media_literacy_records_social_detour_buffer_context() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.media_bias.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "看到乾季晴天美照，但今天濕滑又只剩 18 分鐘 buffer，可以繞去拍嗎？",
            "arguments": {
                "remaining_safety_buffer_minutes": 18,
                "route_condition_reviewed": True,
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == MEDIA_LITERACY_TOOL_ID
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["media_bias_analysis"]["input_state"][
        "remaining_safety_buffer_minutes"
    ] == 18
    assert result.payload["media_bias_analysis"]["input_state"][
        "route_condition_reviewed"
    ] is True
    assert "fresh_weather_or_route_condition_review" not in result.missing_fields
    bias_ids = {
        item["bias_id"]
        for item in result.payload["media_bias_analysis"]["detected_biases"]
    }
    assert {"beauty_photo_bias", "season_weather_bias"} <= bias_ids
    assert result.payload["boundary"]["runtime_safety_truth"] is False


def test_execute_weather_tool_returns_reviewed_route_weather_decision() -> None:
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
    assert result.payload["answerability"] == "route_weather_risk_available"
    assert result.payload["decision"] == "DELAY"
    assert result.payload["weather_to_decision"]["role"] == (
        "Risk Sentinel / Weather-to-Decision"
    )
    assert "天氣決策" in result.payload["field_answer"]
    assert result.missing_fields == []
    assert result.payload["source_status"] == "reviewed_route_weather_package"
    assert result.payload["boundary"]["client_cwa_api_key_allowed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False


def test_execute_live_navigation_state_assessor_loads_reviewed_fixture_snapshot() -> None:
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
    assert result.payload["answerability"] == "snapshot_evidence_available"
    assert result.payload["source_status"] == "reviewed_live_navigation_snapshot"
    assert result.payload["decision"] == "GO"
    assert "地形導航判斷" in result.payload["field_answer"]
    assert result.missing_fields == []
    assert result.payload["missing_fields"] == []
    assert result.payload["route_query_plan"]["status"] == "position_available_for_followup"
    assert result.payload["navigation_decision"]["route_fit_status"] == (
        "on_route_corridor"
    )
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


def test_execute_legacy_nmea_route_risk_probe_delegates_to_live_navigation_state() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": NMEA_ROUTE_RISK_PROBE_TOOL_ID,
            "project_root": str(PROJECT_ROOT),
            "query": "我現在是不是離主路太近但站在危險邊緣？",
            "arguments": {
                "observed_at": "2026-06-15T08:00:00+08:00",
                "lat": 24.0509,
                "lon": 121.216,
                "elevation_m": 2220,
                "source": "legacy_nmea_probe_fixture",
                "hdop": 0.9,
                "horizontal_accuracy_m": 5,
                "fix_quality": "3d",
                "satellite_count": 12,
                "max_cno_dbhz": 38,
                "heading_deg": 94,
                "course_deg": 96,
                "speed_mps": 0.82,
                "nearest_route_distance_m": 45,
                "route_progress_m": 1200,
                "nearest_cp_id": "cp.004",
                "ins_dr_source": "nmea_probe_fixture",
                "confidence": 0.82,
                "uncertainty_m": 8,
                "last_anchor_at": "2026-06-15T07:58:00+08:00",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == NMEA_ROUTE_RISK_PROBE_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_live_navigation_state_tool_output"
    assert result.payload["tool_id"] == NMEA_ROUTE_RISK_PROBE_TOOL_ID
    assert result.payload["compatibility_delegate_tool_id"] == (
        "scout.ai.live_navigation_state.assess.v0"
    )
    assert result.payload["assessment_kind"] == "read_only_nmea_route_risk_probe_compat"
    assert result.payload["answerability"] == "snapshot_evidence_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["navigation_decision"]["route_fit_status"] == (
        "near_corridor_edge"
    )
    assert result.payload["navigation_decision"]["candidate_only"] is True
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
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


def test_execute_safety_boundary_explainer_loads_reviewed_trace() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.safety_boundary.explain",
            "project_root": str(PROJECT_ROOT),
            "query": "哪些風險目前只是候選，不能觸發 Ln？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == "scout.ai.safety_boundary.explain.v0"
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_safety_boundary_explainer_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_safety_boundary_explainer_tool_output"
    assert result.payload["tool_id"] == SAFETY_BOUNDARY_TOOL_ID
    assert result.payload["answerability"] == "safety_boundary_decision_available"
    assert result.payload["source_status"] == "reviewed_safety_admission_trace"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "NO_GO"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "Do not promote this candidate to Ln or runtime safety state."
    )
    assert result.payload["safety_boundary"]["role"] == (
        "Safety Boundary / Runtime Admission Guard"
    )
    assert result.payload["safety_boundary"]["runtime_safety_truth"] is False
    assert result.payload["safety_boundary"]["admission_state"] == (
        "reviewed_candidate_only"
    )
    assert result.payload["safety_boundary"]["operator_review_status"] == "reviewed"
    assert result.payload["missing_fields"] == []
    assert result.missing_fields == []
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_safety_boundary_assessor_escalates_unreviewed_high_risk_state() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.runtime_admission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "這個高風險候選能不能進入 Ln 或觸發 safety 狀態？",
            "arguments": {
                "candidate_id": "risk.candidate.stream_surge.cp4",
                "risk_source": "field_hydrology_candidate",
                "risk_score": 96,
                "admission_state": "candidate",
                "persistence_window": "observed_10m",
                "evidence_refs": [
                    "runtime_ingress.sensorlogger.last_payload",
                    "weather_window.gpm_antecedent_rain",
                ],
                "operator_review_status": "pending",
                "phase1_safety_decision_change_allowed": False,
                "remote_outbound_allowed": False,
                "last_decision_at": "2026-06-15T08:20:00+08:00",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == SAFETY_BOUNDARY_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.payload["answerability"] == "safety_boundary_decision_available"
    assert result.payload["decision"] == "ESCALATE"
    assert result.payload["decision_output"]["decision"] == "ESCALATE"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["safety_boundary"]["admission_state"] == "candidate"
    assert result.payload["safety_boundary"]["operator_review_status"] == "pending"
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.missing_fields == []
    assert result.boundary.live_safety_api_calls_allowed is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_energy_vitals_assessor_loads_reviewed_fixture_snapshot() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.energy_vitals.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "心率資料能不能支持疲勞判斷？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ENERGY_VITALS_TOOL_ID
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == "scout_ai_energy_vitals_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_energy_vitals_tool_output"
    assert result.payload["tool_id"] == ENERGY_VITALS_TOOL_ID
    assert result.payload["assessment_kind"] == "read_only_energy_vitals"
    assert result.payload["answerability"] == "energy_vitals_advisory_available"
    assert result.payload["source_status"] == "reviewed_energy_vitals_snapshot"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["decision_output"]["confidence"] == "medium"
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可有條件繼續，但必須先降低負荷並重新確認。"
    )
    assert "短休最多 10 分鐘" in (
        result.payload["decision_output"]["firstLayer"]["limit"]
    )
    assert result.payload["energy_vitals"]["runtime_safety_truth"] is False
    assert result.payload["results"][0]["decision"] == "CONDITIONAL_GO"
    assert result.payload["missing_fields"] == []
    assert result.payload["provided_fields"]["heart_rate_bpm"] == 148.0
    assert result.payload["provided_fields"]["reserve_band"] == "rest_suggested"
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
    source_report = {
        item["source_kind"]: item for item in result.payload["source_report"]
    }
    assert source_report["energy_reserve_baseline"]["status"] == "loaded"
    assert source_report["wearable_field_observation"]["status"] == "loaded"
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
    assert result.payload["decision_output"]["action"] == "film"
    assert result.payload["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["decision_output"]["maxDurationMinutes"] == 6
    assert result.payload["decision_output"]["cost"]["timeBufferChangeMinutes"] == -6
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可以，最多 6 分鐘。"
    )
    assert result.payload["field_answer"].startswith("[決策] 可以，最多 6 分鐘。")
    assert result.payload["risk_budget"]["authorizedDurationMinutes"] == 16
    assert result.missing_fields == []
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.payload["boundary"]["safety_api_called"] is False


def test_execute_contextual_permission_assessor_prices_extra_stop_time() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "如果多停 10 分鐘，代價是什麼？",
            "arguments": {
                "current_time": "2026-06-07T13:36:00+08:00",
                "remaining_safety_buffer_minutes": 21,
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "stop"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["allowed"] is True
    assert result.payload["max_duration_minutes"] == 10
    assert result.payload["leave_by"] == "2026-06-07T13:46:00+08:00"
    assert result.payload["decision_output"]["action"] == "stop"
    assert result.payload["decision_output"]["maxDurationMinutes"] == 10
    assert result.payload["decision_output"]["leaveBy"] == (
        "2026-06-07T13:46:00+08:00"
    )
    assert result.payload["decision_output"]["cost"]["timeBufferChangeMinutes"] == -10
    assert "消耗 10 分鐘 buffer" in result.payload["field_answer"]
    assert result.payload["boundary"]["runtime_safety_truth"] is False


def test_execute_contextual_permission_assessor_uses_local_clock_deadline() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "如果多停 10 分鐘，代價是什麼？",
            "arguments": {
                "current_time": "13:36",
                "remaining_safety_buffer_minutes": 21,
            },
        }
    )

    assert result.status == "completed"
    assert result.payload["action"] == "stop"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["max_duration_minutes"] == 10
    assert result.payload["leave_by"] == "13:46"
    assert result.payload["decision_output"]["leaveBy"] == "13:46"
    assert "最多 10 分鐘，13:46 前離開" in (
        result.payload["decision_output"]["firstLayer"]["limit"]
    )
    assert "路線走廊" in result.payload["decision_output"]["firstLayer"]["limit"]
    assert result.payload["boundary"]["runtime_safety_truth"] is False


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
    assert result.payload["decision_output"]["action"] == "split_team"
    assert result.payload["decision_output"]["decision"] == "NO_GO"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議分隊。"
    )
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert "走得快的人先去山頂" in result.payload["contextual_permission"][
        "mainReasons"
    ][0]
    assert "保持隊伍完整" in result.payload["contextual_permission"]["nextAction"]
    assert result.boundary.runtime_safety_truth is False


def test_execute_contextual_permission_assessor_allows_rain_gear_micro_decision() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "前面下雨了，要不要穿雨衣？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "wear_rain_gear"
    assert result.payload["decision"] == "GO"
    assert result.payload["allowed"] is True
    assert result.payload["missing_fields"] == []
    assert result.payload["decision_object"] == result.payload["contextual_permission"]
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["action"] == "wear_rain_gear"
    assert result.payload["decision_output"]["decision"] == "GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["max_duration_minutes"] == 2
    assert result.payload["location_constraint"] == (
        "就地安全位置；不離開步道內側或既有路線走廊"
    )
    assert result.payload["decision_output"]["maxDurationMinutes"] == 2
    assert result.payload["decision_output"]["locationConstraint"] == (
        "就地安全位置；不離開步道內側或既有路線走廊"
    )
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可以穿雨具，最多 2 分鐘。"
    )
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert "最多 2 分鐘" in result.payload["field_answer"]
    assert "就地安全位置" in result.payload["field_answer"]
    assert result.boundary.runtime_safety_truth is False


def test_execute_contextual_permission_assessor_allows_fog_wait_photo_cutoff() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "可以等霧散再拍照嗎？",
            "arguments": {
                "current_time": "2026-06-07T14:00:00+08:00",
                "current_cp_id": "CP4",
                "next_cp_id": "CP5",
                "remaining_safety_buffer_minutes": 18,
                "next_segment_uncertainty_minutes": 4,
                "weather_reserve_minutes": 3,
                "weather_window_impact": "14:30 後降雨風險升高，不再等待。",
                "communication_status": "ok",
                "equipment_status": "ok",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "wait"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.payload["allowed"] is True
    assert result.payload["max_duration_minutes"] == 5
    assert result.payload["leave_by"] == "2026-06-07T14:05:00+08:00"
    assert result.payload["decision_output"]["action"] == "wait"
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "可以，最多 5 分鐘。"
    )
    assert "能見度沒有改善" in result.payload["decision_output"]["firstLayer"][
        "nextStep"
    ]
    assert "放棄拍攝" in result.payload["field_answer"]
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_execute_contextual_permission_assessor_blocks_wind_exposed_lunch() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "這裡是風口，我們可以在這裡吃午餐嗎？",
            "arguments": {
                "current_time": "2026-06-07T12:00:00+08:00",
                "current_cp_id": "CP2",
                "next_cp_id": "CP3",
                "minutes_to_next_cp": 18,
                "remaining_safety_buffer_minutes": 45,
                "next_segment_uncertainty_minutes": 5,
                "weather_reserve_minutes": 5,
                "communication_status": "ok",
                "equipment_status": "ok",
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "lunch"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["allowed"] is False
    assert result.payload["minutes_to_next_cp"] == 18.0
    assert result.payload["max_duration_minutes"] is None
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議吃午餐。"
    )
    assert "風口" in result.payload["decision_output"]["firstLayer"]["reason"]
    assert result.payload["decision_output"]["firstLayer"]["nextStep"] == (
        "不在此午餐，請再前進約 18 分鐘到 CP3，到較避風處再重新評估。"
    )
    assert "約 18 分鐘到 CP3" in result.payload["field_answer"]
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_execute_contextual_permission_assessor_escalates_stream_surge_crossing() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "前方溪水暴漲，還能過溪嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == (
        "contextual_permission_missing_required_fields"
    )
    assert result.payload["action"] == "cross_stream"
    assert result.payload["decision"] == "ESCALATE"
    assert result.payload["allowed"] is False
    assert result.payload["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "需要升級處理，不建議渡溪。"
    )
    assert "高後果情境" in result.payload["decision_output"]["firstLayer"]["reason"]
    assert "停止進入溪谷" in result.payload["decision_output"]["firstLayer"][
        "nextStep"
    ]
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert result.boundary.runtime_safety_truth is False


def test_execute_contextual_permission_assessor_blocks_shortcut_reroute() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "這個岔路可以切嗎？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == (
        "contextual_permission_missing_required_fields"
    )
    assert result.payload["action"] == "reroute"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["allowed"] is False
    assert result.payload["missing_fields"] == ["remaining_safety_buffer_minutes"]
    assert result.payload["decision_object"] == result.payload["contextual_permission"]
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["action"] == "reroute"
    assert result.payload["decision_output"]["decision"] == "NO_GO"
    assert result.payload["decision_output"]["allowed"] is False
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "不建議改線。"
    )
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert "不要臨時改線" in result.payload["field_answer"]
    assert result.boundary.runtime_safety_truth is False


def test_execute_contextual_permission_blocks_media_bias_detour_even_with_buffer() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "看到乾季晴天美照，但今天濕滑又只剩 18 分鐘 buffer，可以繞去拍嗎？",
            "arguments": {
                "remaining_safety_buffer_minutes": 18,
            },
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "reroute"
    assert result.payload["decision"] == "NO_GO"
    assert result.payload["allowed"] is False
    assert result.payload["missing_fields"] == []
    assert result.payload["decision_output"]["decision"] == "NO_GO"
    assert "不能為照片" in result.payload["decision_output"]["firstLayer"]["reason"]
    assert "18 分鐘" in result.payload["field_answer"]
    assert result.payload["boundary"]["runtime_safety_truth"] is False


def test_execute_contextual_permission_assessor_allows_direct_retreat() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.contextual_permission.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "隊友很累，要不要直接撤退？",
        }
    )

    assert result.status == "completed"
    assert result.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result.payload["answerability"] == "contextual_permission_decision_available"
    assert result.payload["action"] == "retreat"
    assert result.payload["decision"] == "GO"
    assert result.payload["allowed"] is True
    assert result.payload["missing_fields"] == []
    assert result.payload["decision_object"] == result.payload["contextual_permission"]
    assert result.payload["decision_output"]["decisionObjectSchema"] == (
        "ContextualPermission"
    )
    assert result.payload["decision_output"]["action"] == "retreat"
    assert result.payload["decision_output"]["decision"] == "GO"
    assert result.payload["decision_output"]["allowed"] is True
    assert result.payload["max_duration_minutes"] == 0
    assert "最近安全點" in result.payload["location_constraint"]
    assert result.payload["decision_output"]["maxDurationMinutes"] == 0
    assert "最近安全點" in result.payload["decision_output"]["locationConstraint"]
    assert result.payload["decision_output"]["firstLayer"]["decision"] == (
        "建議撤退。"
    )
    assert result.payload["decision_output"]["runtimeSafetyTruth"] is False
    assert "立即開始撤退" in result.payload["field_answer"]
    assert "不授權停留" in result.payload["field_answer"]
    assert "開始撤退" in result.payload["field_answer"]
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
    assert result.payload["answerability"] == (
        "survival_playbook_personalized_context_available"
    )
    assert result.payload["source_status"] == "reviewed_incident_context"
    assert result.payload["survival_incident_playbook"]["share_policy"][
        "can_send_or_notify"
    ] is False
    assert result.payload["boundary"]["real_sos_sent"] is False
    assert result.payload["boundary"]["outbound_send_performed"] is False
    assert result.missing_fields == []


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


def test_execute_route_context_assessor_reads_route_briefing_compose_fixture(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "route_briefing_project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "chilai_nanhua_briefing"}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = execute_scout_ai_tool(
        {
            "tool_id": ROUTE_CONTEXT_TOOL_ID,
            "project_root": str(project_root),
            "query": "奇萊南華建議幾天？",
            "arguments": {"route_briefing_path": str(ROUTE_BRIEFING_FIXTURE)},
            "limit": 4,
        }
    )

    assert result.status == "completed"
    assert result.tool_id == ROUTE_CONTEXT_TOOL_ID
    assert result.payload["answerability"] == "route_context_available"
    assert "2 天 1 夜" in result.payload["field_answer"]
    assert "3 天 2 夜" in result.payload["field_answer"]
    briefing = result.payload["route_context"]["route_briefing"]
    assert briefing["available"] is True
    assert briefing["candidate_only"] is True
    assert briefing["runtime_safety_truth"] is False
    assert briefing["network_calls_made"] is False
    assert result.payload["boundary"]["runtime_safety_truth"] is False
    assert result.payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert result.missing_fields == []

    layers_result = execute_scout_ai_tool(
        {
            "tool_id": ROUTE_CONTEXT_TOOL_ID,
            "project_root": str(project_root),
            "query": "沿途有哪些歷史、文化、自然、地形、季節觀察？",
            "arguments": {"route_briefing_path": str(ROUTE_BRIEFING_FIXTURE)},
            "limit": 4,
        }
    )

    assert layers_result.status == "completed"
    assert layers_result.payload["answerability"] == "route_context_available"
    for layer_name in ("歷史層", "文化層", "自然層", "地形層", "季節層"):
        assert layer_name in layers_result.payload["field_answer"]
    assert layers_result.payload["boundary"]["runtime_safety_truth"] is False


def test_agent_manifest_runs_tool_registry_and_tool_run(tmp_path: Path) -> None:
    registry_output = _run_manifest(
        "scout.ai.tool_registry.describe",
        {"include_not_implemented": True},
        tmp_path,
    )

    assert registry_output["artifact_kind"] == "scout_ai_tool_registry"
    assert registry_output["tool_count"] >= 10
    assert registry_output["ready_current_tool_count"] >= 8
    assert registry_output["contract_only_tool_count"] == 0
    assert "boundary_explain_only" not in registry_output["implementation_status_counts"]
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
