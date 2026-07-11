import json
from pathlib import Path

from fastapi.testclient import TestClient

from assistant_api import create_assistant_app
from assistant_models import AssistantBoundary, ScoutAssistantQuery, ScoutAssistantResponse
from assistant_pydantic_provider import build_assistant_prompt, _compact_hailo_ollama_prompt
from assistant_workspace_total_info import (
    TOTAL_INFO_SOURCE_ID,
    build_workspace_total_info_source_ref,
)


def test_total_info_source_summarizes_workspace_route_weather_body_and_sensors(
    tmp_path: Path,
):
    project_root = _write_total_info_workspace(tmp_path / "workspace" / "chilai_nanhua_day1")
    data_root = _write_data_root(tmp_path / "data" / "scout")
    query = ScoutAssistantQuery(
        surface="pretrip",
        question="我現在是否該下撤？",
        project_id="chilai_nanhua_day1",
    )

    source = build_workspace_total_info_source_ref(
        query,
        project_root=project_root,
        data_root=data_root,
        reference_time="2026-07-06T12:00:00Z",
    )

    assert source is not None
    assert source.source_id == TOTAL_INFO_SOURCE_ID
    assert source.evidence_type == "assistant_workspace_total_info"
    summary = source.context_summary
    assert summary["route_context"]["distance_km"] == 12.345
    assert summary["route_context"]["checkpoint_candidate_count"] == 3
    assert summary["weather_environment_context"]["cwa_qpf"]["counts"]["qpf_feature_count"] == 2
    assert summary["weather_environment_context"]["gee_smap"]["values"]["sm_surface"]["latest"] == 0.31
    assert summary["weather_environment_context"]["status"] == "available"
    assert summary["weather_environment_context"]["freshness"]["cwa_weather"] == "fresh"
    assert summary["body_resource_context"]["mission_graph_thresholds"]["min_device_battery"] == 0.25
    assert summary["location_context"]["live_navigation_snapshot"]["lat"] == 24.01
    assert summary["sensor_snapshot_context"]["imu_pdr"]["observer_state"] == "listening"
    assert summary["sensor_snapshot_context"]["latest_sensor_vitals_record"]["observation_name"] == "accelerometer"
    assert summary["boundary"]["runtime_safety_truth"] is False
    serialized = json.dumps(summary)
    assert "workspace_root" not in summary
    assert str(project_root) not in serialized
    assert "raw_nmea" not in serialized
    assert '"raw_payload":' not in serialized


def test_total_info_marks_expired_weather_as_partial(tmp_path: Path) -> None:
    project_root = _write_total_info_workspace(
        tmp_path / "workspace" / "chilai_nanhua_day1"
    )

    source = build_workspace_total_info_source_ref(
        ScoutAssistantQuery(
            surface="pretrip",
            question="現在天氣證據還有效嗎？",
            project_id="chilai_nanhua_day1",
        ),
        project_root=project_root,
        reference_time="2026-07-11T00:00:00Z",
    )

    assert source is not None
    summary = source.context_summary
    weather = summary["weather_environment_context"]
    assert weather["status"] == "partial_stale_environment"
    assert weather["freshness"]["cwa_weather"] == "stale"
    assert "cwa_weather" in weather["stale_sources"]
    assert "weather_environment" in summary["missing_or_partial_context"]


def test_total_info_rejects_artifact_refs_outside_workspace(tmp_path: Path) -> None:
    project_root = _write_total_info_workspace(
        tmp_path / "workspace" / "chilai_nanhua_day1"
    )
    outside_path = tmp_path / "outside-secret.json"
    outside_path.write_text(
        json.dumps({"route_name": "OUTSIDE_SENTINEL", "distance_m": 999999}),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["route_summary_ref"] = str(outside_path)
    project["cwa_weather_evidence_ref"] = "../../../outside-secret.json"
    project_path.write_text(json.dumps(project), encoding="utf-8")

    source = build_workspace_total_info_source_ref(
        ScoutAssistantQuery(
            surface="pretrip",
            question="讀取 workspace",
            project_id="chilai_nanhua_day1",
        ),
        project_root=project_root,
        reference_time="2026-07-06T12:00:00Z",
    )

    assert source is not None
    summary = source.context_summary
    serialized = json.dumps(summary)
    assert summary["route_context"]["status"] == "missing"
    assert "OUTSIDE_SENTINEL" not in serialized
    assert str(outside_path) not in serialized
    assert "../../../outside-secret.json" not in serialized


def test_assistant_api_adds_total_info_from_workspace_env(tmp_path: Path, monkeypatch):
    workspace_root = tmp_path / "pretrip-workspaces"
    _write_total_info_workspace(workspace_root / "chilai_nanhua_day1")
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(workspace_root))

    class EchoProvider:
        def answer(self, query: ScoutAssistantQuery, *, sources=None):
            return ScoutAssistantResponse(
                surface=query.surface,
                answer="ok",
                sources=sources or [],
                boundary=AssistantBoundary(surface=query.surface),
            )

    client = TestClient(create_assistant_app(provider=EchoProvider()))
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "這條路線今天適合嗎？",
            "project_id": "chilai_nanhua_day1",
        },
    )

    assert response.status_code == 200
    source_ids = [source["source_id"] for source in response.json()["sources"]]
    assert TOTAL_INFO_SOURCE_ID in source_ids


def test_assistant_api_rejects_workspace_path_traversal(tmp_path: Path, monkeypatch):
    workspace_root = tmp_path / "pretrip-workspaces"
    outside_project = tmp_path / "outside"
    _write_total_info_workspace(outside_project)
    workspace_root.mkdir()
    monkeypatch.setenv("SCOUT_PRETRIP_WORKSPACE_ROOT", str(workspace_root))

    client = TestClient(create_assistant_app())
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": "列出 workspace 資料",
            "project_id": "../outside",
        },
    )

    assert response.status_code == 422
    assert str(outside_project) not in response.text


def test_assistant_prompt_and_hailo_compact_prompt_keep_total_info(tmp_path: Path):
    project_root = _write_total_info_workspace(tmp_path / "workspace" / "chilai_nanhua_day1")
    source = build_workspace_total_info_source_ref(
        ScoutAssistantQuery(
            surface="pretrip",
            question="白牆時我現在應該繼續走嗎？",
            project_id="chilai_nanhua_day1",
        ),
        project_root=project_root,
    )
    assert source is not None

    prompt = build_assistant_prompt(
        ScoutAssistantQuery(
            surface="pretrip",
            question="白牆時我現在應該繼續走嗎？",
            project_id="chilai_nanhua_day1",
        ),
        sources=[source],
        max_context_chars=800,
    )
    compact = _compact_hailo_ollama_prompt(prompt)

    assert "Total Info:" in prompt
    assert "cwa_qpf" in prompt
    assert "現況摘要" in compact
    assert "missing_or_partial_context" in compact
    assert '"sources"' not in compact


def _write_total_info_workspace(project_root: Path) -> Path:
    (project_root / "normalized" / "routes").mkdir(parents=True)
    (project_root / "outputs" / "environment" / "cwa").mkdir(parents=True)
    (project_root / "outputs" / "environment" / "gee").mkdir(parents=True)
    (project_root / "outputs" / "environment" / "derived").mkdir(parents=True)
    (project_root / "outputs").mkdir(exist_ok=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "chilai_nanhua_day1",
                "route_name": "奇萊南華",
                "route_kind": "out_and_back",
                "route_days": 2,
                "route_summary_ref": "normalized/routes/route_summary.json",
                "checkpoint_candidate_count": 3,
                "segment_candidate_count": 2,
                "mcp_candidate_count": 1,
                "boss_point_count": 1,
                "mileage_tag_alignment_count": 6,
                "route_mileage_k_anchor_count": 2,
                "cwa_weather_evidence_ref": "outputs/environment/cwa/cwa_weather_evidence.json",
                "cwa_qpf_corridor_summary_ref": "outputs/environment/cwa/qpf_corridor_summary.json",
                "smap_l4_corridor_summary_ref": "outputs/environment/gee/smap_l4_corridor_summary.json",
                "gpm_imerg_corridor_summary_ref": "outputs/environment/gee/gpm_imerg_corridor_summary.json",
                "environment_risk_derivatives_ref": "outputs/environment/derived/environment_risk_derivatives.json",
                "boss_points_ref": "outputs/boss_points.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "normalized" / "routes" / "route_summary.json").write_text(
        json.dumps(
            {
                "route_name": "奇萊南華",
                "distance_m": 12345,
                "point_count": 99,
                "elevation_min_m": 1200,
                "elevation_max_m": 3350,
                "bbox_wgs84": {"min_lat": 23.9, "max_lat": 24.1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "environment" / "cwa" / "cwa_weather_evidence.json").write_text(
        json.dumps(
            {
                "artifact_kind": "cwa_weather_environment_evidence",
                "generated_at": "2026-07-06T00:00:00Z",
                "forecast_valid_from": "2026-07-06T06:00:00Z",
                "forecast_valid_until": "2026-07-07T06:00:00Z",
                "counts": {"warning_count": 1, "rain_observation_count": 5},
                "external_api_calls_made": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "environment" / "cwa" / "qpf_corridor_summary.json").write_text(
        json.dumps(
            {
                "artifact_kind": "cwa_qpf_corridor_summary",
                "generated_at": "2026-07-06T00:00:00Z",
                "counts": {"qpf_feature_count": 2},
                "max_observed_24h_mm": 18.5,
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "environment" / "gee" / "smap_l4_corridor_summary.json").write_text(
        json.dumps(
            {
                "artifact_kind": "gee_soil_moisture_corridor_summary",
                "generated_at": "2026-07-06T00:00:00Z",
                "values": {"sm_surface": {"latest": 0.31, "p95": 0.42}},
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "environment" / "gee" / "gpm_imerg_corridor_summary.json").write_text(
        json.dumps(
            {
                "artifact_kind": "gee_antecedent_rain_corridor_summary",
                "values": {"precipitation_mm": {"latest": 8.5}},
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "environment" / "derived" / "environment_risk_derivatives.json").write_text(
        json.dumps(
            {
                "artifact_kind": "scout_environment_risk_derivatives",
                "status": "ready",
                "headline": "wetness candidates available",
                "counts": {"wetness_flash_flood_candidate_count": 4},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "boss_points.json").write_text(
        json.dumps(
            {"metadata": {"raw_health_payload_embedded": False, "basis": "fixture_energy"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
        json.dumps(
            {"steps": [{"guard": {"min_device_battery": 0.25, "min_estimated_human_energy": 0.4}}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return project_root


def _write_data_root(data_root: Path) -> Path:
    (data_root / "admin" / "ingress" / "gnss_hardware").mkdir(parents=True)
    (data_root / "admin" / "ingress" / "imu_pdr").mkdir(parents=True)
    (data_root / "admin" / "ingress" / "sensorlogger_mqtt").mkdir(parents=True)
    (data_root / "admin" / "ingress" / "gnss_hardware" / "live_navigation_snapshot.json").write_text(
        json.dumps(
            {
                "lat": 24.01,
                "lon": 121.01,
                "snapshot_status": "valid_fix",
                "fix_quality": "valid",
                "satellite_count": 9,
                "observed_at": "2026-07-06T00:00:00Z",
                "raw_nmea": "$GPRMC,redacted*00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data_root / "admin" / "ingress" / "gnss_hardware" / "gnss_hardware_observer_status.json").write_text(
        json.dumps({"decision": "gnss_fix_available", "answerability": "live_gnss_snapshot_available"}),
        encoding="utf-8",
    )
    (data_root / "admin" / "ingress" / "imu_pdr" / "imu_pdr_observer_status.json").write_text(
        json.dumps({"observer_state": "listening", "sample_count": 12}),
        encoding="utf-8",
    )
    (data_root / "admin" / "ingress" / "sensorlogger_mqtt" / "sensorlogger_mqtt_status.json").write_text(
        json.dumps({"ingress": {"accepted_count": 3}, "mqtt": {"mqtt_connected": True}}),
        encoding="utf-8",
    )
    (data_root / "admin" / "ingress" / "sensorlogger_mqtt" / "sensorlogger_mqtt_sensor_vitals_records.jsonl").write_text(
        json.dumps(
            {
                "artifact_kind": "scout_sensor_vitals_record",
                "observation_name": "accelerometer",
                "observed_at": "2026-07-06T00:00:01Z",
                "raw_payload": {"x": 1},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return data_root
