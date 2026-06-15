from __future__ import annotations

import json
from pathlib import Path

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_evidence_collection import collect_scout_ai_evidence
from scout_ai_full_workflow import run_scout_ai_full_workflow
from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_tool_planner import ScoutAiToolPlanItemStatus, plan_scout_ai_tools
from scout_runtime_ingress_status_tool import (
    RUNTIME_INGRESS_STATUS_OUTPUT_KIND,
    RUNTIME_INGRESS_STATUS_TOOL_ID,
    assess_scout_runtime_ingress_status,
)


def test_runtime_ingress_status_tool_reads_status_and_router_traces(
    tmp_path: Path,
) -> None:
    project_root = _write_runtime_ingress_project(tmp_path)

    result = assess_scout_runtime_ingress_status(
        project_root,
        query="MQTT 現在有收到資料嗎？",
        limit=3,
    )

    assert result["artifact_kind"] == RUNTIME_INGRESS_STATUS_OUTPUT_KIND
    assert result["tool_id"] == RUNTIME_INGRESS_STATUS_TOOL_ID
    assert result["answerability"] == "runtime_ingress_trace_available"
    assert result["decision"] == "CONDITIONAL_GO"
    assert result["runtime_ingress_status"]["ingress_status"]["accepted_count"] == 1
    assert result["router_trace"]["dispatch_status_counts"] == {"accepted": 1}
    assert result["latency_status"]["sample_count"] == 1
    assert result["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert result["decision_output"]["runtimeSafetyTruth"] is False
    for key in (
        "cost",
        "residualRisk",
        "requiredConditions",
        "alternativeActions",
    ):
        assert key in result["decision_output"]
    assert (
        result["decision_output"]["residualRisk"]
        == result["decision_output"]["secondLayer"]["residualRisk"]
    )
    assert result["boundary"]["runtime_safety_truth"] is False
    serialized = json.dumps(result, ensure_ascii=False)
    assert "raw_payload_text" not in serialized
    assert "not-written" not in serialized


def test_runtime_ingress_status_tool_reports_missing_trace(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_json(project_root / "project.json", {"project_id": "runtime-missing"})

    result = assess_scout_runtime_ingress_status(project_root)

    assert result["answerability"] == "runtime_ingress_missing_sources"
    assert result["decision"] == "DELAY"
    assert result["missing_fields"] == ["runtime_ingress_router_trace"]
    assert result["result_count"] == 0
    assert "不能推論 MQTT" in result["field_answer"]


def test_runtime_ingress_status_registry_and_executor_are_ready(
    tmp_path: Path,
) -> None:
    project_root = _write_runtime_ingress_project(tmp_path)
    registry = tool_registry_output(tool_ids=[RUNTIME_INGRESS_STATUS_TOOL_ID])
    contract = registry.tools[0]

    assert contract.implementation_status == "ready_current_tool"
    assert contract.implementation_gap is None
    assert "scout.ai.sensorlogger_status.search" in contract.aliases
    assert "observer_status_path" in contract.optional_fields

    result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.sensorlogger_status.search",
            "project_root": str(project_root),
            "query": "Sensor Logger routing latency 正常嗎？",
            "limit": 3,
        }
    )

    assert result.status == "completed"
    assert result.implementation_status == "ready_current_tool"
    assert result.output_artifact_kind == RUNTIME_INGRESS_STATUS_OUTPUT_KIND
    assert result.payload["answerability"] == "runtime_ingress_trace_available"
    assert result.payload["decision"] == "CONDITIONAL_GO"
    assert result.boundary.runtime_safety_truth is False


def test_planner_selects_runtime_ingress_for_mqtt_status_question(
    tmp_path: Path,
) -> None:
    project_root = _write_runtime_ingress_project(tmp_path)

    plan = plan_scout_ai_tools(
        ScoutAssistantQuery(
            surface=AssistantSurface.PRETRIP,
            question="MQTT 現在有收到資料嗎？",
        ),
        project_root=project_root,
    )

    item = next(
        item for item in plan.selected_tools if item.tool_id == RUNTIME_INGRESS_STATUS_TOOL_ID
    )
    assert item.status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
    assert item.implementation_status == "ready_current_tool"
    assert item.request is not None
    assert item.request["tool_id"] == RUNTIME_INGRESS_STATUS_TOOL_ID
    assert item.boundary.runtime_safety_truth is False


def test_evidence_answer_and_full_workflow_use_runtime_ingress_trace(
    tmp_path: Path,
) -> None:
    project_root = _write_runtime_ingress_project(tmp_path)

    evidence = collect_scout_ai_evidence(
        "MQTT 現在有收到資料嗎？",
        project_root=project_root,
        project_id="runtime-fixture",
        limit=3,
    )
    record = next(
        item
        for item in evidence.evidence_records
        if item.tool_id == RUNTIME_INGRESS_STATUS_TOOL_ID
    )
    assert evidence.executed_tool_count >= 1
    assert record.collection_status == "completed"
    assert record.result is not None
    assert record.result["payload"]["runtime_ingress_status"]["source_loaded"] is True

    answer = collect_and_synthesize_scout_ai_answer(
        "MQTT 現在有收到資料嗎？",
        project_root=project_root,
        project_id="runtime-fixture",
        limit=3,
    )
    assert answer.decision_output["answerSourceToolId"] == RUNTIME_INGRESS_STATUS_TOOL_ID
    assert answer.decision_output["decision"] == "CONDITIONAL_GO"
    assert "Runtime ingress/router trace 可讀" in answer.answer
    assert "runtime safety truth" in answer.answer

    full = run_scout_ai_full_workflow(
        "MQTT 現在有收到資料嗎？",
        project_root=project_root,
        project_id="runtime-fixture",
        limit=3,
    )
    assert full.decision_output["answerSourceToolId"] == RUNTIME_INGRESS_STATUS_TOOL_ID
    assert full.completed_tool_count >= 1
    assert full.workflow_policy.model_provider_used is False


def _write_runtime_ingress_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "runtime_project"
    transport_dir = project_root / "transports"
    output_dir = project_root / "outputs"
    transport_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    ingress_record = {
        "artifact_kind": "scout_ingress_evidence_record",
        "artifact_version": "ingress_evidence_record.v0",
        "ingress_id": "ingress-1",
        "ingress_transport": "wan_mqtt",
        "source_adapter": "sensorlogger",
        "received_at": "2026-06-05T00:00:00Z",
        "payload_sha256": "a" * 64,
        "payload_byte_count": 128,
        "parse_status": "accepted",
        "raw_artifact_path": str(transport_dir / "raw.jsonl"),
        "raw_artifact_kind": "scout_ingress_raw_evidence",
        "normalized_summary": {
            "message_id": 7,
            "payload_count": 2,
            "sensor_names": ["location", "pedometer"],
        },
        "boundary": {
            "runtime_admission_performed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "raw_payload_embedded_in_summary": False,
            "credential_value_exposed": False,
        },
    }
    dispatch_record = {
        "artifact_kind": "scout_application_dispatch_record",
        "artifact_version": "application_dispatch_record.v0",
        "dispatch_id": "dispatch-1",
        "router_version": "application_router.v0",
        "route_id": "navigation.ins_dr.wearable_route_constrained.v0",
        "route_target": "navigation.ins_dr",
        "match_reason": "observation_name:location",
        "dispatch_status": "accepted",
        "input_ref": "observation-1",
        "output_ref": "filter-output-1",
        "side_effect_policy": "no_runtime_safety_mutation_no_outbound",
        "agent_skill_ref": "ins-dr-wearable-route-constrained",
        "credential_value_exposed": False,
        "boundary": {
            "safety_api_called": False,
            "phase1_l0_l4_state_mutated": False,
            "outbound_send_performed": False,
        },
    }
    filter_output = {
        "artifact_kind": "scout_application_filter_output",
        "artifact_version": "application_filter_output.v0",
        "output_id": "filter-output-1",
        "route_target": "navigation.ins_dr",
        "output_kind": "navigation_estimate",
        "status": "estimate_produced",
        "observation_id": "observation-1",
        "output_summary": {
            "estimate_source": "gnss",
            "confidence": 0.8,
            "runtime_safety_truth": False,
        },
        "raw_evidence_refs": ["ingress-1:payload[0]"],
        "credential_value_exposed": False,
        "boundary": {
            "safety_api_called": False,
            "phase1_l0_l4_state_mutated": False,
            "outbound_send_performed": False,
        },
    }
    latency_record = {
        "artifact_kind": "scout_sensorlogger_mqtt_routing_latency",
        "artifact_version": "sensorlogger_mqtt_routing_latency.v0",
        "ingress_id": "ingress-1",
        "message_id": 7,
        "payload_count": 2,
        "observation_count": 2,
        "mqtt_receive_to_route_complete_ms": 18.5,
        "routing_duration_ms": 6.0,
        "boundary": {"safety_api_called": False},
    }

    _write_jsonl(transport_dir / "ingress_evidence_index.jsonl", [ingress_record])
    _write_jsonl(transport_dir / "application_routes.jsonl", [dispatch_record])
    _write_jsonl(transport_dir / "filter_outputs.jsonl", [filter_output])
    _write_jsonl(transport_dir / "latency.jsonl", [latency_record])
    _write_json(
        output_dir / "sensorlogger_mqtt_status.json",
        {
            "artifact_kind": "scout_sensorlogger_mqtt_observer_status",
            "artifact_version": "sensorlogger_mqtt_observer_status.v0",
            "source_tool": "scout_sensorlogger_mqtt_observer",
            "message_count": 1,
            "invalid_message_count": 0,
            "sensor_names": ["location", "pedometer"],
            "sessions": [
                {
                    "session_id": "session-1",
                    "device_id": "device-1",
                    "last_message_id": 7,
                    "sensor_names": ["location", "pedometer"],
                }
            ],
            "mqtt_state": {
                "connected": True,
                "subscribed": True,
                "ever_connected": True,
                "ever_subscribed": True,
            },
            "mqtt": {
                "host": "mqtt.local",
                "topic": "scout/test/alex/sensorlogger",
                "username_configured": True,
                "password_configured": True,
            },
            "ingress": {
                "artifact_kind": "scout_ingress_evidence_index",
                "record_count": 1,
                "accepted_count": 1,
                "rejected_count": 0,
                "unrecognized_count": 0,
                "ingress_transports": ["wan_mqtt"],
                "source_adapters": ["sensorlogger"],
                "records": [ingress_record],
                "boundary": {
                    "runtime_admission_performed": False,
                    "phase1_l0_l4_state_mutated": False,
                    "safety_api_called": False,
                    "phase2_brain_writeback": False,
                },
            },
            "application_router": {
                "artifact_kind": "scout_application_router_status",
                "dispatch_count": 1,
                "filter_output_count": 1,
                "dispatch_status_counts": {"accepted": 1},
                "route_target_counts": {"navigation.ins_dr": 1},
                "filter_output_kind_counts": {"navigation_estimate": 1},
                "latest_dispatch": dispatch_record,
                "latest_filter_output": filter_output,
            },
            "latency": {
                "sample_count": 1,
                "latest": latency_record,
                "stats": {
                    "mqtt_receive_to_route_complete_ms": {"count": 1, "max": 18.5}
                },
            },
            "evidence": {
                "ingress_index_jsonl_path": str(transport_dir / "ingress_evidence_index.jsonl"),
                "application_routes_jsonl_path": str(transport_dir / "application_routes.jsonl"),
                "filter_outputs_jsonl_path": str(transport_dir / "filter_outputs.jsonl"),
                "latency_jsonl_path": str(transport_dir / "latency.jsonl"),
                "status_path": str(output_dir / "sensorlogger_mqtt_status.json"),
            },
            "boundary": {
                "phase1_l0_l4_state_mutated": False,
                "safety_api_called": False,
            },
        },
    )
    _write_json(
        project_root / "project.json",
        {
            "project_id": "runtime-fixture",
            "runtime_ingress_status_ref": "outputs/sensorlogger_mqtt_status.json",
            "runtime_ingress_index_ref": "transports/ingress_evidence_index.jsonl",
            "application_routes_ref": "transports/application_routes.jsonl",
            "filter_outputs_ref": "transports/filter_outputs.jsonl",
            "runtime_ingress_latency_ref": "transports/latency.jsonl",
        },
    )
    return project_root


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)
        + "\n",
        encoding="utf-8",
    )
