import json
from pathlib import Path

from scout_ai_context_registry import (
    ARTIFACT_KIND,
    ScoutAiContextSourceStatus,
    discover_scout_ai_context_sources,
)
from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_tool_planner import WEATHER_WINDOW_TOOL_ID
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_workspace_search_tools import MAJOR_POINT_TOOL_ID, ROUTE_STRUCTURE_TOOL_ID


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_PATH = (
    ROOT
    / "tools"
    / "scout_agent_tool_manifests"
    / "scout.ai.context_registry.describe.json"
)


def test_context_registry_discovers_core_pretrip_sources_without_runtime_truth() -> None:
    registry = discover_scout_ai_context_sources(PROJECT_ROOT)
    sources = _sources_by_id(registry)

    assert registry.artifact_kind == ARTIFACT_KIND
    assert registry.project_id == "chilai_nanhua_day1"
    assert registry.source_count == 9
    assert registry.available_source_count >= 6
    assert registry.partial_source_count >= 1
    assert registry.missing_source_count >= 1
    assert registry.boundary.read_only is True
    assert registry.boundary.runtime_safety_truth is False
    assert registry.boundary.live_safety_api_calls_allowed is False

    route = sources["scout.context.route_structure"]
    assert route.status == ScoutAiContextSourceStatus.AVAILABLE
    assert ROUTE_STRUCTURE_TOOL_ID in route.tool_ids
    assert route.counts["checkpoint_candidate_count"] == 124
    assert route.counts["segment_candidate_count"] == 123

    major_points = sources["scout.context.major_points"]
    assert major_points.status == ScoutAiContextSourceStatus.AVAILABLE
    assert MAJOR_POINT_TOOL_ID in major_points.tool_ids
    assert major_points.counts["mcp_candidate_count"] == 6

    risk = sources["scout.context.risk_scores"]
    terrain = sources["scout.context.terrain_scores"]
    map_perception = sources["scout.context.map_perception"]
    assert risk.status == ScoutAiContextSourceStatus.AVAILABLE
    assert terrain.status == ScoutAiContextSourceStatus.AVAILABLE
    assert map_perception.status == ScoutAiContextSourceStatus.AVAILABLE
    assert RISK_SCORE_TOOL_ID in risk.tool_ids
    assert TERRAIN_SCORE_TOOL_ID in terrain.tool_ids
    assert MAP_PERCEPTION_TOOL_ID in map_perception.tool_ids
    assert "planning evidence" in " ".join(risk.limitations)

    weather = sources["scout.context.weather_window"]
    assert weather.status == ScoutAiContextSourceStatus.PARTIAL
    assert WEATHER_WINDOW_TOOL_ID in weather.tool_ids
    assert "outputs/weather_daylight_evidence.json" in weather.source_paths
    assert {"provider", "ttl_s"}.issubset(set(weather.missing_fields))
    assert "Fresh provider" in " ".join(weather.limitations)

    sensor = sources["scout.context.sensor_vitals"]
    ins_dr = sources["scout.context.ins_dr_trace"]
    assert sensor.status == ScoutAiContextSourceStatus.MISSING
    assert ins_dr.status == ScoutAiContextSourceStatus.MISSING
    assert "sensor_vitals_records_jsonl" in sensor.missing_fields
    assert "ins_dr_estimates_jsonl" in ins_dr.missing_fields

    for source in registry.sources:
        assert source.candidate_only is True
        assert source.boundary.read_only is True
        assert source.boundary.runtime_safety_truth is False
        assert source.boundary.phase1_safety_mutation_allowed is False
        assert source.boundary.remote_outbound_send_allowed is False
        assert source.boundary.hardware_control_allowed is False
        assert source.boundary.raw_payloads_embedded is False


def test_context_registry_can_exclude_missing_sources_for_compact_context() -> None:
    registry = discover_scout_ai_context_sources(PROJECT_ROOT, include_missing=False)
    source_ids = {source.source_id for source in registry.sources}

    assert registry.missing_source_count == 0
    assert "scout.context.sensor_vitals" not in source_ids
    assert "scout.context.ins_dr_trace" not in source_ids
    assert "scout.context.weather_window" in source_ids
    assert registry.source_ids_by_domain["weather"] == ["scout.context.weather_window"]


def test_context_registry_detects_local_sensor_vitals_and_ins_dr_jsonl(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "context-registry-project"
    (project_root / "outputs" / "navigation").mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "context_registry_fixture"}),
        encoding="utf-8",
    )
    _write_jsonl(
        project_root / "outputs" / "sensorlogger_mqtt_sensor_vitals_records.jsonl",
        [
            {"observed_at": "2026-06-07T08:00:00Z", "heart_rate_bpm": 140},
            {"observed_at": "2026-06-07T08:01:00Z", "heart_rate_bpm": 142},
        ],
    )
    _write_jsonl(
        project_root / "outputs" / "navigation" / "ins_dr_estimates.jsonl",
        [
            {
                "timestamp_s": 0,
                "estimate_lat": 24.0,
                "estimate_lon": 121.0,
                "estimate_source": "wearable_route_constrained",
            }
        ],
    )

    registry = discover_scout_ai_context_sources(project_root)
    sources = _sources_by_id(registry)
    sensor = sources["scout.context.sensor_vitals"]
    ins_dr = sources["scout.context.ins_dr_trace"]

    assert sensor.source_paths == ["outputs/sensorlogger_mqtt_sensor_vitals_records.jsonl"]
    assert sensor.counts[
        "outputs/sensorlogger_mqtt_sensor_vitals_records.jsonl:line_count"
    ] == 2
    assert sensor.status == ScoutAiContextSourceStatus.PARTIAL
    assert ENERGY_VITALS_TOOL_ID in sensor.tool_ids
    assert "heart_rate_bpm" in sensor.missing_fields

    assert ins_dr.source_paths == ["outputs/navigation/ins_dr_estimates.jsonl"]
    assert ins_dr.counts["outputs/navigation/ins_dr_estimates.jsonl:line_count"] == 1
    assert ins_dr.status == ScoutAiContextSourceStatus.AVAILABLE
    assert INS_DR_TRACE_TOOL_ID in ins_dr.tool_ids


def test_context_registry_builtin_tool_manifest_and_payload_are_read_only(
    tmp_path: Path,
) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "context-registry-request.json"
    request_path.write_text(
        json.dumps(
            {
                "project_root": str(PROJECT_ROOT),
                "include_missing": True,
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-context-registry", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.context_registry.describe"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert "transport.egress" in manifest.forbidden_writes
    assert "hardware.device" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert manifest.metadata["runtime_safety_truth"] is False
    assert exit_code == 0
    assert payload["artifact_kind"] == ARTIFACT_KIND
    assert payload["artifact_version"] == "scout_ai_context_registry.v0"
    assert payload["status"] == "completed"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["source_count"] == 9
    assert payload["source_ids_by_domain"]["weather"] == [
        "scout.context.weather_window"
    ]
    assert payload["boundary"]["read_only"] is True
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["boundary"]["outbound_send_performed"] is False
    assert payload["boundary"]["hardware_control_performed"] is False
    assert payload["boundary"]["workspace_file_write_allowed"] is False
    assert payload["boundary"]["raw_payloads_embedded"] is False


def _sources_by_id(registry):
    return {source.source_id: source for source in registry.sources}


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
