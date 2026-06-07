from __future__ import annotations

import json
from pathlib import Path

from scout_agent_cli import run_scout_agent_cli
from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
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
    assert ENERGY_VITALS_TOOL_ID in by_id
    assert by_id["pydantic_ai.tool.search_scout_risk_scores.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.ins_dr_trace.analyze.v0"].implementation_status == (
        "ready_current_tool"
    )
    assert by_id["scout.ai.weather_window.assess.v0"].implementation_status == (
        "partial_existing_surface"
    )
    assert by_id["scout.ai.live_navigation_state.assess.v0"].implementation_status == (
        "partial_existing_surface"
    )
    assert by_id["scout.ai.safety_boundary.explain.v0"].implementation_status == (
        "boundary_explain_only"
    )
    assert by_id[ENERGY_VITALS_TOOL_ID].implementation_status == (
        "partial_existing_surface"
    )
    assert "scout.ai.energy_vitals.assess" in by_id[ENERGY_VITALS_TOOL_ID].aliases
    assert registry.ready_current_tool_count >= 8
    assert registry.executable_tool_count >= registry.ready_current_tool_count
    assert registry.contract_only_tool_count >= 1
    assert registry.implementation_status_counts["ready_current_tool"] >= 8
    assert "ready_current_tool" in registry.tool_ids_by_status
    assert "scout.ai.weather_window.assess.v0" in registry.missing_evidence_fields_by_tool
    assert "provider" in registry.missing_evidence_fields_by_tool[
        "scout.ai.weather_window.assess.v0"
    ]
    assert "ttl_s" in registry.missing_evidence_fields_by_tool[
        "scout.ai.weather_window.assess.v0"
    ]
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
    assert result.boundary.runtime_safety_truth is False
    assert result.boundary.phase1_safety_mutation_allowed is False


def test_execute_future_weather_tool_returns_not_implemented_contract() -> None:
    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.weather_window.assess.v0",
            "arguments": {
                "query": "明天午後雷雨要不要提早紮營",
            },
        }
    )

    assert result.status == "not_implemented"
    assert result.implementation_status == "partial_existing_surface"
    assert result.payload["contract"]["tool_id"] == "scout.ai.weather_window.assess.v0"
    assert "provider" in result.missing_fields
    assert "ttl_s" in result.missing_fields
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
    assert result.implementation_status == "partial_existing_surface"
    assert result.output_artifact_kind == "scout_ai_live_navigation_state_tool_output"
    assert result.payload["artifact_kind"] == "scout_ai_live_navigation_state_tool_output"
    assert result.payload["tool_id"] == "scout.ai.live_navigation_state.assess.v0"
    assert result.payload["assessment_kind"] == "read_only_live_navigation_snapshot"
    assert result.payload["answerability"] == "snapshot_missing_required_fields"
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
    assert result.payload["tool_id"] == "scout.ai.ins_dr_trace.analyze.v0"
    assert result.payload["analysis_kind"] == "read_only_ins_dr_trace"
    assert result.payload["answerability"] in {
        "missing_trace_evidence",
        "missing_gps_trajectory",
        "insufficient_aligned_samples",
        "trace_metrics_available",
    }
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
    assert result.payload["tool_id"] == "scout.ai.safety_boundary.explain.v0"
    assert "admission_state" in result.payload["missing_fields"]
    assert "operator_review_status" in result.payload["missing_fields"]
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
    assert "建議短暫休息" in result.payload["advisory"]["message_zh"]
    assert "hrv_ms" in result.payload["missing_fields"]
    assert "pace_mps" in result.payload["missing_fields"]
    assert result.payload["source_report"][0]["status"] == "loaded"
    assert result.payload["source_report"][1]["status"] == "loaded"
    assert result.payload["privacy"]["raw_health_payload_shared"] is False
    assert result.payload["boundary"]["medical_diagnosis"] is False
    assert result.payload["boundary"]["safety_api_called"] is False
    assert result.payload["boundary"]["provider_values_are_scout_truth"] is False


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
    assert "scout.ai.weather_window.assess.v0" in registry_output[
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
