from __future__ import annotations

from pathlib import Path

from application_router import ApplicationObservation
from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery
from assistant_skill_router import (
    PRETRIP_CP_COUNT_SKILL_ID,
    PRETRIP_CONTEXT_REGISTRY_SOURCE_ID,
    PRETRIP_ENERGY_VITALS_SNAPSHOT_SOURCE_ID,
    PRETRIP_FULL_WORKFLOW_SOURCE_ID,
    PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID,
    PRETRIP_PLACE_TO_CP_SKILL_ID,
    PRETRIP_TOOL_PLANNER_SKILL_ID,
    augment_pretrip_sources_with_tool_plan,
    augment_pretrip_sources_with_local_evidence_search,
    build_pretrip_full_workflow_fallback_response,
    build_pretrip_full_workflow_source,
    build_pretrip_context_registry_sources,
    build_pretrip_tool_plan_fallback_response,
    build_pretrip_tool_plan_sources,
    build_pretrip_local_evidence_search_source,
    resolve_assistant_query_with_skill,
)
from ingress_evidence import IngressTransport
from scout_ai_tool_planner import (
    ENERGY_VITALS_TOOL_ID,
    LIVE_NAVIGATION_STATE_TOOL_ID,
    WEATHER_WINDOW_TOOL_ID,
)
from scout_sensor_vitals_record import (
    append_sensor_vitals_records_jsonl,
    sensor_vitals_records_from_observations,
)
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_pretrip_local_evidence_search_source_finds_workspace_evidence() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="大崩塌有什麼風險？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    source = build_pretrip_local_evidence_search_source(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
    )

    assert source is not None
    assert source.source_id == PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID
    assert source.evidence_type == "assistant_local_evidence_search_results"
    summary = source.context_summary
    assert summary is not None
    assert summary["result_count"] >= 1
    assert summary["searched_record_count"] > 100
    assert summary["runtime_safety_truth"] is False
    assert summary["raw_payloads_embedded"] is False
    assert any("大崩塌" in result["snippet"] for result in summary["results"])


def test_pretrip_local_evidence_search_source_includes_mcp_metadata() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="黑水塘有什麼資料？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    source = build_pretrip_local_evidence_search_source(
        query,
        project_root=PROJECT_ROOT,
        limit=5,
    )

    assert source is not None
    summary = source.context_summary
    assert summary is not None
    results = summary["results"]
    assert any(
        result["evidence_type"] == "pretrip_major_critical_point_candidate"
        and result["metadata"]["mcp_id"] == "mcp.heishuitang.002"
        and result["metadata"]["nearest_cp_candidate_id"] == "cp.002"
        for result in results
    )
    assert any(
        result["evidence_type"] == "pretrip_mcp_cp_support_reconciliation"
        and result["metadata"]["support_status"] == "supported"
        for result in results
    )
    assert any(
        result["evidence_type"] == "pretrip_mcp_named_point"
        and result["metadata"]["named_point_id"] == "np.heishuitang"
        for result in results
    )


def test_pretrip_context_registry_source_summarizes_available_sources() -> None:
    sources = build_pretrip_context_registry_sources(project_root=PROJECT_ROOT)

    assert len(sources) == 1
    source = sources[0]
    assert source.source_id == PRETRIP_CONTEXT_REGISTRY_SOURCE_ID
    assert source.evidence_type == "assistant_context_registry"
    summary = source.context_summary
    assert summary is not None
    assert summary["artifact_kind"] == "scout_ai_context_registry"
    assert summary["source_count"] == 9
    assert summary["runtime_safety_truth"] is False
    assert summary["raw_payloads_embedded"] is False
    assert "route" in summary["source_ids_by_domain"]
    route_sources = [
        item
        for item in summary["sources"]
        if item["source_id"] == "scout.context.route_structure"
    ]
    assert route_sources[0]["status"] == "available"
    weather_sources = [
        item
        for item in summary["sources"]
        if item["source_id"] == "scout.context.weather_window"
    ]
    assert weather_sources[0]["status"] == "partial"
    assert "provider" in weather_sources[0]["missing_fields"]
    assert source.context_summary["boundary"]["runtime_safety_truth"] is False


def test_pretrip_local_evidence_search_source_is_added_only_for_general_questions() -> None:
    general_query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="大崩塌有什麼風險？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    deterministic_query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="有多少個cp",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = [_pretrip_context_source()]

    general_sources = augment_pretrip_sources_with_local_evidence_search(
        general_query,
        sources=sources,
        project_root=PROJECT_ROOT,
    )
    deterministic_sources = augment_pretrip_sources_with_local_evidence_search(
        deterministic_query,
        sources=sources,
        project_root=PROJECT_ROOT,
    )

    assert PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID in {
        source.source_id for source in general_sources
    }
    deterministic_source_ids = {source.source_id for source in deterministic_sources}
    assert PRETRIP_CONTEXT_REGISTRY_SOURCE_ID in deterministic_source_ids
    assert PRETRIP_LOCAL_EVIDENCE_SEARCH_SKILL_ID not in deterministic_source_ids
    assert PRETRIP_TOOL_PLANNER_SKILL_ID not in deterministic_source_ids
    assert "assistant_context.pretrip" in deterministic_source_ids


def test_pretrip_tool_plan_sources_execute_ready_risk_and_terrain_tools() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="危險地形在哪些位置？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    sources = build_pretrip_tool_plan_sources(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
    )

    assert sources[0].source_id == PRETRIP_TOOL_PLANNER_SKILL_ID
    source_ids = {source.source_id for source in sources}
    assert RISK_SCORE_TOOL_ID in source_ids
    assert TERRAIN_SCORE_TOOL_ID in source_ids
    risk_summary = _summary_for(sources, RISK_SCORE_TOOL_ID)
    terrain_summary = _summary_for(sources, TERRAIN_SCORE_TOOL_ID)
    assert risk_summary["resolver"] == PRETRIP_TOOL_PLANNER_SKILL_ID
    assert risk_summary["status"] == "completed"
    assert risk_summary["latest"]["result_count"] >= 1
    assert risk_summary["boundary"]["runtime_safety_truth"] is False
    assert terrain_summary["resolver"] == PRETRIP_TOOL_PLANNER_SKILL_ID
    assert terrain_summary["status"] == "completed"
    assert terrain_summary["boundary"]["runtime_safety_truth"] is False


def test_pretrip_tool_plan_fallback_reports_weather_partial_tool_evidence() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="明天午後雷雨是否要紮營？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = build_pretrip_tool_plan_sources(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
    )

    response = build_pretrip_tool_plan_fallback_response(
        query,
        sources=sources,
        provider_error_type="ProviderFailed",
    )

    assert response is not None
    assert "registry planner fallback" in response.answer
    assert WEATHER_WINDOW_TOOL_ID in {source.source_id for source in response.sources}
    assert "provider_error_type=ProviderFailed" in response.limitations
    assert f"resolved_by={PRETRIP_TOOL_PLANNER_SKILL_ID}" in response.limitations
    weather_summary = _summary_for(response.sources, WEATHER_WINDOW_TOOL_ID)
    assert weather_summary["status"] == "completed"
    assert weather_summary["latest"]["answerability"] == "weather_placeholder_only"
    assert "provider" in weather_summary["latest"]["missing_fields"]
    assert "ttl_s" in weather_summary["latest"]["missing_fields"]
    assert "route_weather_package" in weather_summary["latest"]["missing_fields"]
    assert response.boundary.safety_mutation_allowed is False
    assert response.boundary.outbound_send_allowed is False


def test_pretrip_full_workflow_source_reports_weather_partial_tool_evidence() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="明天午後雷雨是否要紮營？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    source = build_pretrip_full_workflow_source(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
    )

    assert source is not None
    assert source.source_id == PRETRIP_FULL_WORKFLOW_SOURCE_ID
    assert source.evidence_type == "assistant_full_workflow_summary"
    summary = source.context_summary
    assert summary is not None
    assert summary["artifact_kind"] == "scout_ai_full_workflow"
    assert summary["answerability"] == "partial_evidence_with_missing_context"
    assert summary["selected_tool_count"] == 1
    assert summary["executed_tool_count"] == 1
    assert summary["contract_gap_count"] == 0
    assert summary["missing_evidence_count"] == 1
    assert summary["workflow_policy"]["model_provider_used"] is False
    assert summary["workflow_policy"]["model_synthesis_performed"] is False
    assert summary["boundary"]["runtime_safety_truth"] is False
    assert summary["runtime_safety_truth"] is False
    assert "weather_placeholder_only" in summary["answer"]
    assert summary["sources"][0]["tool_id"] == WEATHER_WINDOW_TOOL_ID
    assert "provider" in summary["missing_evidence"][0]["missing_fields"]
    assert "ttl_s" in summary["missing_evidence"][0]["missing_fields"]
    assert "route_weather_package" in summary["missing_evidence"][0]["missing_fields"]


def test_pretrip_full_workflow_source_exposes_standard_gap_audit_for_ui() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="請以 SCOUT_OUTDOOR_AI_AGENT_STANDARD 為基準，檢視目前 Scout 體系還缺哪些東西，六力是否都有實作？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    source = build_pretrip_full_workflow_source(
        query,
        project_root=PROJECT_ROOT,
        limit=8,
    )

    assert source is not None
    summary = source.context_summary
    assert summary is not None
    decision_output = summary["decision_output"]
    audit = decision_output["standardGapAudit"]
    assert decision_output["answerSourceToolId"] == "scout.ai.standard_gap_overview.v0"
    assert decision_output["decision"] == "GUIDED_ONLY"
    assert decision_output["allowed"] is False
    assert decision_output["runtimeSafetyTruth"] is False
    assert audit["schema"] == "scout_standard_gap_audit.v0"
    assert audit["runtimeSafetyTruth"] is False
    assert audit["summary"]["standardGroupCount"] == 10
    assert audit["summary"]["coveredStandardGroupCount"] == 10
    assert audit["summary"]["implementationGapToolCount"] == 0
    assert audit["summary"]["contextOrReviewEvidenceGapToolCount"] == 0
    assert audit["summary"]["uiUxValidationNeeded"] is False
    assert audit["uiUxValidation"]["validated"] is True
    assert audit["uiUxValidation"]["status"] == "validated_static_admin_ui"
    assert len(audit["groups"]) == 10
    assert audit["inputOrEvidenceGaps"] == []
    assert audit["implementationGaps"] == []
    assert summary["runtime_safety_truth"] is False


def test_pretrip_full_workflow_fallback_uses_compact_workflow_source() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="明天午後雷雨是否要紮營？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = augment_pretrip_sources_with_tool_plan(
        query,
        sources=[_pretrip_context_source()],
        project_root=PROJECT_ROOT,
        limit=3,
    )

    response = build_pretrip_full_workflow_fallback_response(
        query,
        sources=sources,
        provider_error_type="ProviderFailed",
    )

    assert response is not None
    assert "registry planner fallback" in response.answer
    assert "full workflow fallback" in response.answer
    assert "weather_placeholder_only" in response.answer
    assert PRETRIP_FULL_WORKFLOW_SOURCE_ID in {
        source.source_id for source in response.sources
    }
    workflow_summary = _summary_for(response.sources, PRETRIP_FULL_WORKFLOW_SOURCE_ID)
    assert workflow_summary["answerability"] == "partial_evidence_with_missing_context"
    assert workflow_summary["contract_gap_count"] == 0
    assert f"resolved_by={PRETRIP_FULL_WORKFLOW_SOURCE_ID}" in response.limitations
    assert response.boundary.safety_mutation_allowed is False
    assert response.boundary.outbound_send_allowed is False


def test_pretrip_tool_plan_hydrates_live_navigation_snapshot_source() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="哪些風險目前只是候選，不能觸發 Ln？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    live_source = AssistantSourceRef(
        source_id="assistant_context.live_navigation_snapshot",
        source_path="fixture://live-navigation-snapshot",
        evidence_type="live_navigation_snapshot",
        selected=True,
        context_summary={
            "live_navigation_snapshot": {
                "observed_at": "2026-06-07T08:00:00Z",
                "lat": 24.051,
                "lon": 121.22,
                "elevation_m": 1280.5,
                "source": "fixture_gnss_ins_dr",
                "hdop": 0.8,
                "horizontal_accuracy_m": 4.2,
                "fix_quality": "valid",
                "satellite_count": 8,
                "max_cno_dbhz": 42,
                "heading_deg": 45,
                "course_deg": 44,
                "speed_mps": 0.7,
                "nearest_route_distance_m": 12.4,
                "route_progress_m": 14550.0,
                "nearest_cp_id": "cp.042",
                "ins_dr_source": "wearable_route_constrained",
                "confidence": 0.82,
                "uncertainty_m": 6.5,
                "last_anchor_at": "2026-06-07T07:59:55Z",
            },
            "read_only": True,
            "runtime_safety_truth": False,
        },
    )

    sources = build_pretrip_tool_plan_sources(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
        evidence_sources=[live_source],
    )

    live_summary = _summary_for(sources, LIVE_NAVIGATION_STATE_TOOL_ID)
    latest = live_summary["latest"]
    assert live_summary["hydration"]["status"] == "hydrated"
    assert live_summary["hydration"]["source_id"] == live_source.source_id
    assert "lat" in live_summary["hydration"]["field_names"]
    assert "uncertainty_m" in live_summary["hydration"]["field_names"]
    assert latest["status"] == "completed"
    assert latest["answerability"] == "snapshot_evidence_available"
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["lat"] == 24.051
    assert latest["provided_fields"]["lon"] == 121.22
    assert latest["provided_fields"]["ins_dr_source"] == "wearable_route_constrained"
    assert latest["quality_flags"]["horizontal_accuracy_usable"] is True
    assert latest["boundary"]["live_hardware_read_performed"] is False
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["outbound_send_performed"] is False


def test_pretrip_tool_plan_hydrates_energy_vitals_snapshot_source() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="我現在心率偏高又很累，需要休息嗎?",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    vitals_source = AssistantSourceRef(
        source_id="assistant_context.energy_vitals_snapshot",
        source_path="fixture://energy-vitals-snapshot",
        evidence_type="energy_vitals_snapshot",
        selected=True,
        context_summary={
            "energy_vitals_snapshot": {
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
            "read_only": True,
            "runtime_safety_truth": False,
        },
    )

    sources = build_pretrip_tool_plan_sources(
        query,
        project_root=PROJECT_ROOT,
        limit=3,
        evidence_sources=[vitals_source],
    )

    energy_summary = _summary_for(sources, ENERGY_VITALS_TOOL_ID)
    latest = energy_summary["latest"]
    assert energy_summary["hydration"]["status"] == "hydrated"
    assert energy_summary["hydration"]["source_id"] == vitals_source.source_id
    assert "heart_rate_bpm" in energy_summary["hydration"]["field_names"]
    assert "reserve_score" in energy_summary["hydration"]["field_names"]
    assert latest["status"] == "completed"
    assert latest["answerability"] == "energy_vitals_advisory_available"
    assert latest["decision"] == "CONDITIONAL_GO"
    assert latest["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert latest["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert latest["decision_output"]["allowed"] is True
    assert latest["decision_output"]["runtimeSafetyTruth"] is False
    assert "短休最多 10 分鐘" in latest["decision_output"]["firstLayer"]["limit"]
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["heart_rate_bpm"] == 162.0
    assert latest["advisory"]["cue_band"] == "rest_suggested"
    assert latest["boundary"]["medical_diagnosis"] is False
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["outbound_send_performed"] is False


def test_pretrip_tool_plan_augmentation_reads_sensor_vitals_jsonl_for_energy_snapshot(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "energy-project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        '{"project_id":"energy-project"}',
        encoding="utf-8",
    )
    observations = [
        ApplicationObservation(
            observation_id="obs-hr-prior",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 148, "hrvMs": 50},
            observed_at="2026-06-07T07:58:00Z",
            timestamp_s=1780828680.0,
            received_at="2026-06-07T07:58:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[-1]",),
            payload_sha256="d" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 162},
            observed_at="2026-06-07T08:00:00Z",
            timestamp_s=1780828800.0,
            received_at="2026-06-07T08:00:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[0]",),
            payload_sha256="e" * 64,
            capability_tags=("health", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-energy",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "hrvMs": 42,
                "bodyBattery": 35,
                "paceMps": 0.72,
                "cadence": 88,
                "activityLoad": 130.5,
                "baselineWindowDays": 90,
                "reserveScore": 38,
                "reserveBand": "rest_suggested",
                "heartRateDriftRatio": 0.174,
            },
            observed_at="2026-06-07T08:00:02Z",
            timestamp_s=1780828802.0,
            received_at="2026-06-07T08:00:03Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[1]",),
            payload_sha256="f" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
    ]
    append_sensor_vitals_records_jsonl(
        project_root / "outputs" / "sensorlogger_mqtt_sensor_vitals_records.jsonl",
        sensor_vitals_records_from_observations(observations),
    )
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="我現在心率偏高又很累，需要休息嗎?",
        project_id="energy-project",
    )

    sources = augment_pretrip_sources_with_tool_plan(
        query,
        sources=[],
        project_root=project_root,
        limit=3,
    )

    snapshot_summary = _summary_for(
        sources,
        PRETRIP_ENERGY_VITALS_SNAPSHOT_SOURCE_ID,
    )
    energy_summary = _summary_for(sources, ENERGY_VITALS_TOOL_ID)
    latest = energy_summary["latest"]
    assert snapshot_summary["energy_vitals_snapshot"]["heart_rate_bpm"] == 162
    assert snapshot_summary["energy_vitals_snapshot"]["reserve_score"] == 38
    assert snapshot_summary["time_window"]["summary"]["heart_rate_trend"]["trend"] == (
        "increasing"
    )
    assert snapshot_summary["time_window"]["summary"]["heart_rate_trend"]["delta"] == 14.0
    assert snapshot_summary["runtime_safety_truth"] is False
    assert energy_summary["hydration"]["status"] == "hydrated"
    assert energy_summary["hydration"]["source_id"] == (
        PRETRIP_ENERGY_VITALS_SNAPSHOT_SOURCE_ID
    )
    assert latest["answerability"] == "energy_vitals_advisory_available"
    assert latest["missing_fields"] == []
    assert latest["provided_fields"]["subject_id"] == "session-energy"
    assert latest["provided_fields"]["source_provider"] == "sensorlogger"
    assert latest["time_window"]["heart_rate_trend"]["trend"] == "increasing"
    assert latest["time_window"]["heart_rate_trend"]["delta"] == 14.0
    assert latest["time_window"]["record_gap_count"] == 0
    assert latest["advisory"]["cue_band"] == "rest_suggested"
    assert latest["decision"] == "CONDITIONAL_GO"
    assert latest["decision_output"]["decisionObjectSchema"] == "ContextualPermission"
    assert latest["decision_output"]["decision"] == "CONDITIONAL_GO"
    assert latest["decision_output"]["runtimeSafetyTruth"] is False
    assert latest["boundary"]["medical_diagnosis"] is False
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["outbound_send_performed"] is False


def test_pretrip_energy_vitals_snapshot_uses_recent_record_count_from_question(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "energy-window-project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        '{"project_id":"energy-window-project"}',
        encoding="utf-8",
    )
    observations = [
        ApplicationObservation(
            observation_id="obs-hr-1",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "heartRate": 120,
                "hrvMs": 54,
                "bodyBattery": 42,
                "paceMps": 0.76,
                "cadence": 84,
                "activityLoad": 118.0,
                "baselineWindowDays": 90,
                "reserveScore": 44,
                "reserveBand": "watch",
                "heartRateDriftRatio": 0.08,
            },
            observed_at="2026-06-07T08:00:00Z",
            timestamp_s=1780828800.0,
            received_at="2026-06-07T08:00:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[0]",),
            payload_sha256="6" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr-2",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "heartRate": 150,
                "hrvMs": 48,
                "bodyBattery": 37,
                "paceMps": 0.72,
                "cadence": 88,
                "activityLoad": 128.0,
                "baselineWindowDays": 90,
                "reserveScore": 39,
                "reserveBand": "rest_suggested",
                "heartRateDriftRatio": 0.14,
            },
            observed_at="2026-06-07T08:01:00Z",
            timestamp_s=1780828860.0,
            received_at="2026-06-07T08:01:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[1]",),
            payload_sha256="7" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
        ApplicationObservation(
            observation_id="obs-hr-3",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="energy_reserve",
            values={
                "heartRate": 130,
                "hrvMs": 44,
                "bodyBattery": 34,
                "paceMps": 0.7,
                "cadence": 86,
                "activityLoad": 134.0,
                "baselineWindowDays": 90,
                "reserveScore": 36,
                "reserveBand": "rest_suggested",
                "heartRateDriftRatio": 0.16,
            },
            observed_at="2026-06-07T08:02:00Z",
            timestamp_s=1780828920.0,
            received_at="2026-06-07T08:02:01Z",
            session_id="session-energy",
            device_id="watch-1",
            raw_evidence_refs=("ingress-energy:payload[2]",),
            payload_sha256="8" * 64,
            capability_tags=("health", "resource", "vitals"),
        ),
    ]
    append_sensor_vitals_records_jsonl(
        project_root / "outputs" / "sensorlogger_mqtt_sensor_vitals_records.jsonl",
        sensor_vitals_records_from_observations(observations),
    )
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="最近 2 筆心率是不是持續升高？我很累需要休息嗎?",
        project_id="energy-window-project",
    )

    sources = augment_pretrip_sources_with_tool_plan(
        query,
        sources=[],
        project_root=project_root,
        limit=3,
    )

    snapshot_summary = _summary_for(
        sources,
        PRETRIP_ENERGY_VITALS_SNAPSHOT_SOURCE_ID,
    )
    energy_summary = _summary_for(sources, ENERGY_VITALS_TOOL_ID)
    latest = energy_summary["latest"]
    time_window = snapshot_summary["time_window"]
    trend = time_window["summary"]["heart_rate_trend"]
    assert snapshot_summary["window_config"] == {"max_records": 2}
    assert time_window["selection_mode"] == "last_n_records"
    assert time_window["window_record_count"] == 2
    assert trend["first"] == 150.0
    assert trend["last"] == 130.0
    assert trend["delta"] == -20.0
    assert trend["trend"] == "decreasing"
    assert snapshot_summary["runtime_safety_truth"] is False
    assert energy_summary["hydration"]["status"] == "hydrated"
    assert latest["answerability"] == "energy_vitals_advisory_available"
    assert latest["missing_fields"] == []
    assert latest["time_window"]["heart_rate_trend"]["trend"] == "decreasing"
    assert latest["time_window"]["heart_rate_trend"]["delta"] == -20.0
    assert latest["provided_fields"]["heart_rate_bpm"] == 130.0
    assert latest["provided_fields"]["reserve_score"] == 36
    assert latest["boundary"]["medical_diagnosis"] is False
    assert latest["boundary"]["safety_api_called"] is False
    assert latest["boundary"]["outbound_send_performed"] is False

    fallback = build_pretrip_tool_plan_fallback_response(
        query,
        sources=sources,
        provider_error_type="ProviderFailed",
    )

    assert fallback is not None
    assert "energy/vitals fallback" in fallback.answer
    assert "不是持續升高" in fallback.answer
    assert "150.0 -> 130.0 bpm" in fallback.answer
    assert "reserve_score=36" in fallback.answer
    assert "missing_fields=none" in fallback.answer
    assert "不是醫療診斷" in fallback.answer
    assert "不是 runtime safety truth" in fallback.answer
    assert "不會觸發 /safety、SOS、beacon 或 outbound send" in fallback.answer
    assert f"resolved_tool={ENERGY_VITALS_TOOL_ID}" in fallback.limitations
    assert "provider_error_type=ProviderFailed" in fallback.limitations
    assert fallback.boundary.safety_mutation_allowed is False
    assert fallback.boundary.outbound_send_allowed is False


def test_pretrip_tool_plan_augmentation_defers_to_deterministic_cp_skill() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="有多少個cp",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = [_pretrip_context_source()]

    augmented = augment_pretrip_sources_with_tool_plan(
        query,
        sources=sources,
        project_root=PROJECT_ROOT,
    )

    source_ids = [source.source_id for source in augmented]
    assert source_ids == [
        PRETRIP_CONTEXT_REGISTRY_SOURCE_ID,
        "assistant_context.pretrip",
    ]
    registry_summary = _summary_for(augmented, PRETRIP_CONTEXT_REGISTRY_SOURCE_ID)
    assert registry_summary["runtime_safety_truth"] is False
    assert registry_summary["raw_payloads_embedded"] is False


def test_pretrip_cp_count_skill_resolves_from_context_summary() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="有多少個cp",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    response = resolve_assistant_query_with_skill(
        query,
        sources=[_pretrip_context_source()],
    )

    assert response is not None
    assert response.answer.startswith("Scout AI read-only deterministic skill result")
    assert "124 個 CP" in response.answer
    assert "runtime safety truth" in response.answer
    assert response.sources[0].source_id == PRETRIP_CP_COUNT_SKILL_ID
    assert any(
        limitation == f"resolved_by={PRETRIP_CP_COUNT_SKILL_ID}"
        for limitation in response.limitations
    )


def test_pretrip_place_to_cp_skill_resolves_from_context_summary() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="黑水塘在第幾cp附近？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )
    sources = [_pretrip_context_source()]

    response = resolve_assistant_query_with_skill(query, sources=sources)

    assert response is not None
    assert response.answer.startswith("Scout AI read-only deterministic skill result")
    assert "黑水塘 在 CP 006 附近" in response.answer
    assert "58.519 m" in response.answer
    assert "candidate_only=true" in response.answer
    assert "runtime_safety_truth=false" in response.answer
    assert response.sources[0].source_id == PRETRIP_PLACE_TO_CP_SKILL_ID
    assert response.boundary.pretrip_review_mutation_allowed is False
    assert response.boundary.safety_mutation_allowed is False
    assert any(
        limitation == f"resolved_by={PRETRIP_PLACE_TO_CP_SKILL_ID}"
        for limitation in response.limitations
    )


def test_pretrip_place_to_cp_skill_defers_when_no_place_match() -> None:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question="不存在地點在第幾cp附近？",
        context_ref="chilai_nanhua_day1",
        project_id="chilai_nanhua_day1",
    )

    assert (
        resolve_assistant_query_with_skill(query, sources=[_pretrip_context_source()])
        is None
    )


def _pretrip_context_source() -> AssistantSourceRef:
    return AssistantSourceRef(
        source_id="assistant_context.pretrip",
        source_path="pretrip_assistant_context",
        evidence_type="assistant_context_summary",
        selected=True,
        context_summary={
            "surface": "pretrip",
            "summary": {
                "cp_count": 124,
                "checkpoint_candidate_count": 124,
                "major_critical_point_cp_links": [
                    {
                        "label": "黑水塘",
                        "mcp_id": "mcp.heishuitang.002",
                        "nearest_cp_candidate_id": "cp.006",
                        "nearest_cp_label": "CP 006",
                        "nearest_cp_distance_m": 58.519,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                        "support_status": "supported",
                    }
                ]
            },
        },
    )


def _summary_for(
    sources: list[AssistantSourceRef],
    source_id: str,
) -> dict:
    for source in sources:
        if source.source_id == source_id:
            assert source.context_summary is not None
            return source.context_summary
    raise AssertionError(f"missing source: {source_id}")
