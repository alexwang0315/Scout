from __future__ import annotations

import json
import shutil
from pathlib import Path

from assistant_models import AssistantSurface, ScoutAssistantQuery
from scout_ai_answer_synthesis import collect_and_synthesize_scout_ai_answer
from scout_ai_tool_contracts import tool_registry_output
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_tool_planner import plan_scout_ai_tools
from scout_cwa_environment_tool import (
    CWA_ENVIRONMENT_OUTPUT_KIND,
    CWA_ENVIRONMENT_TOOL_ID,
    assess_scout_cwa_environment,
)
from scout_gee_environment_tool import (
    GEE_ENVIRONMENT_OUTPUT_KIND,
    GEE_ENVIRONMENT_TOOL_ID,
    assess_scout_gee_environment,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_cwa_environment_tool_reads_workspace_artifacts_without_network() -> None:
    payload = assess_scout_cwa_environment(
        PROJECT_ROOT,
        query="CWA QPF corridor summary?",
        reference_time="2026-06-24T06:00:00Z",
        limit=4,
    )

    assert payload["tool_id"] == CWA_ENVIRONMENT_TOOL_ID
    assert payload["external_api_calls_made"] is False
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["human_review_required"] is True
    assert payload["missing_fields"] == []
    assert payload["cwa_summary"]["warning_count"] == 1
    assert payload["cwa_summary"]["observation_count"] == 1
    assert payload["cwa_summary"]["qpf_grid_feature_count"] == 1
    assert payload["cwa_summary"]["qpf_route_timeline_event_count"] == 1
    assert payload["cwa_summary"]["qpf_corridor_summary"]["max_mm"] == 32.0
    assert "F-C0041-001" in payload["cwa_summary"]["datasets"]
    assert "max 為 32.0 mm" in payload["field_answer"]
    assert payload["field_answer_priority"] == 100
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_cwa_environment_tool_marks_old_workspace_evidence_partial() -> None:
    payload = assess_scout_cwa_environment(
        PROJECT_ROOT,
        query="目前 CWA QPF 還有效嗎？",
        reference_time="2026-07-11T00:00:00Z",
        limit=4,
    )

    assert payload["answerability"] == "cwa_environment_partial"
    assert "fresh_cwa_environment_evidence" in payload["missing_fields"]
    assert payload["decision"] == "DELAY"
    assert any("age_hours=" in warning for warning in payload["warnings"])


def test_cwa_environment_tool_joins_latest_observation_to_nearest_route_station(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project_root)
    observations_path = project_root / "outputs/environment/cwa/observations.geojson"
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    route = json.loads(
        (project_root / "outputs/segment_display_geometry.json").read_text(
            encoding="utf-8"
        )
    )
    first_route_point = route["segments"][0]["coordinates"][0]
    observations["latest_observation_at"] = "2026-06-24T05:20:00Z"
    observations["features"][0]["geometry"]["coordinates"] = [
        first_route_point["lon"],
        first_route_point["lat"],
    ]
    observations["features"][0]["properties"].update(
        {
            "station_name": "route-nearest-station",
            "obs_time": "2026-06-24T13:20:00+08:00",
        }
    )
    observations_path.write_text(
        json.dumps(observations, ensure_ascii=False), encoding="utf-8"
    )

    payload = assess_scout_cwa_environment(
        project_root,
        query="CWA observations 的最新觀測時間與最近測站是什麼？",
        reference_time="2026-06-24T06:00:00Z",
    )

    summary = payload["cwa_summary"]["observation_summary"]
    assert summary["latest_observation_at"] == "2026-06-24T05:20:00Z"
    assert summary["nearest_route_station"]["station_name"] == (
        "route-nearest-station"
    )
    assert summary["nearest_route_station"]["distance_to_route_m"] == 0.0
    assert "route-nearest-station" in payload["field_answer"]
    assert "2026-06-24T05:20:00Z" in payload["field_answer"]
    assert payload["field_answer_source_ref"] == (
        "outputs/environment/cwa/observations.geojson"
    )
    assert payload["field_answer_priority"] == 100


def test_cwa_environment_tool_does_not_invent_direct_qpf_from_rain_probability(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project_root)
    qpf_summary_path = (
        project_root / "outputs/environment/cwa/qpf_corridor_summary.json"
    )
    qpf_summary_path.write_text(
        json.dumps(
            {
                "artifact_kind": "cwa_qpf_corridor_summary",
                "request_timestamp": "2026-06-24T00:00:00Z",
                "valid_from": "2026-06-24T12:00:00Z",
                "valid_to": "2026-06-25T00:00:00Z",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    qpf_grid_path = project_root / "outputs/environment/cwa/qpf_grid.geojson"
    qpf_grid_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "source": "F-C0032-001",
                            "qpf_direct_grid": False,
                            "rain_probability": 70.0,
                            "rainfall_mm": None,
                            "valid_from": "2026-06-24T12:00:00Z",
                            "valid_to": "2026-06-24T18:00:00Z",
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [121.2, 24.0],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = assess_scout_cwa_environment(
        project_root,
        query="QPF corridor summary 的 max、mean、p95 與 peak window 是多少？",
        reference_time="2026-06-24T06:00:00Z",
    )

    qpf = payload["cwa_summary"]["qpf_corridor_summary"]
    assert qpf["direct_qpf_available"] is False
    assert qpf["max_mm"] is None
    assert qpf["mean_mm"] is None
    assert qpf["p95_mm"] is None
    assert qpf["peak_window"] is None
    assert qpf["forecast_derived_peak_probability_pct"] == 70.0
    assert qpf["forecast_derived_peak_window"] == (
        "2026-06-24T12:00:00Z/2026-06-24T18:00:00Z"
    )
    assert "Direct QPF accumulation unavailable" in payload["field_answer"]
    assert "forecast-derived rain probability" in payload["field_answer"].lower()
    assert payload["field_answer_source_ref"] == (
        "outputs/environment/cwa/qpf_corridor_summary.json"
    )

    natural_query = assess_scout_cwa_environment(
        project_root,
        query="今天的雨量預計是多少",
        reference_time="2026-06-24T06:00:00Z",
    )
    assert natural_query["answerability"] == "cwa_environment_partial"
    assert "direct_qpf_accumulation_mm" in natural_query["missing_fields"]
    assert "Direct QPF accumulation unavailable" in natural_query["field_answer"]
    assert "70.0%" in natural_query["field_answer"]
    assert natural_query["field_answer_priority"] == 100
    assert natural_query["field_answer_source_ref"] == (
        "outputs/environment/cwa/qpf_corridor_summary.json"
    )

    freshness = assess_scout_cwa_environment(
        project_root,
        query="CWA QPF evidence 的 issued time、valid time 與 stale risk 是什麼？",
        reference_time="2026-06-24T06:00:00Z",
    )
    assert "issued time 為 unavailable" in freshness["field_answer"]
    assert "do not substitute observation time" in freshness["field_answer"]
    assert "API fetched time 為 2026-06-24T00:00:00Z" in freshness["field_answer"]
    assert "valid time 為 2026-06-24T12:00:00Z 至 2026-06-25T00:00:00Z" in freshness[
        "field_answer"
    ]


def test_cwa_environment_tool_answers_prepared_workspace_detail_questions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project_root)
    imagery_root = project_root / "outputs/environment/cwa/imagery"
    imagery_root.mkdir(parents=True, exist_ok=True)
    radar_ref = "outputs/environment/cwa/imagery/radar_frames_manifest.json"
    satellite_ref = (
        "outputs/environment/cwa/imagery/satellite_frames_manifest.json"
    )
    (project_root / radar_ref).write_text(
        json.dumps(
            {
                "artifactKind": "cwaRadarFramesManifest",
                "latestFrameId": "radar.frame.002",
                "frames": [{"frameId": "radar.frame.001"}, {"frameId": "radar.frame.002"}],
            }
        ),
        encoding="utf-8",
    )
    (project_root / satellite_ref).write_text(
        json.dumps(
            {
                "artifactKind": "cwaSatelliteFramesManifest",
                "latestFrameId": "satellite.frame.001",
                "frames": [{"frameId": "satellite.frame.001"}],
            }
        ),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update(
        {
            "cwa_radar_frames_manifest_ref": radar_ref,
            "cwa_satellite_frames_manifest_ref": satellite_ref,
        }
    )
    project_path.write_text(json.dumps(project), encoding="utf-8")

    warning = assess_scout_cwa_environment(
        project_root,
        query="CWA warning layer 目前有多少個警特報 feature，影響哪些區域？",
    )
    forecast = assess_scout_cwa_environment(
        project_root,
        query="CWA forecast timeline 涵蓋哪些鄉鎮與時間窗？",
    )
    intensified = assess_scout_cwa_environment(
        project_root,
        query="QPF 是否來自劇烈天氣 3 小時加密作業？",
    )
    astronomy = assess_scout_cwa_environment(
        project_root,
        query="astronomy timeline 的日落、民用暮光與 practical darkness 時間是什麼？",
    )
    tide = assess_scout_cwa_environment(
        project_root,
        query="tide marine timeline 對這條山區路線是否標示為適用？",
    )
    datasets = assess_scout_cwa_environment(
        project_root,
        query="CWA weather evidence 使用了哪些 dataset id？",
    )
    imagery = assess_scout_cwa_environment(
        project_root,
        query="CWA radar 與 satellite imagery manifest 各有多少個 prepared frames？",
    )

    assert "feature_count=1" in warning["field_answer"]
    assert "時間窗：2026-06-24T12:00:00Z 至 2026-06-24T12:00:00Z" in forecast[
        "field_answer"
    ]
    assert "severe_weather_intensified_operation=false" in intensified[
        "field_answer"
    ]
    assert "日落時間為 18:48" in astronomy["field_answer"]
    assert "民用暮光時間為 unavailable" in astronomy["field_answer"]
    assert "標示為不適用" in tide["field_answer"]
    assert "狀態為 not_applicable" in tide["field_answer"]
    assert "W-C0033-001=unknown" in datasets["field_answer"]
    assert "radar prepared_frames=2" in imagery["field_answer"]
    assert "satellite prepared_frames=1" in imagery["field_answer"]
    assert imagery["field_answer_source_refs"] == [radar_ref, satellite_ref]


def test_gee_environment_tool_reads_workspace_artifacts_without_gee_init() -> None:
    payload = assess_scout_gee_environment(
        PROJECT_ROOT,
        query="SMAP GPM hydrologic evidence?",
        limit=4,
    )

    assert payload["tool_id"] == GEE_ENVIRONMENT_TOOL_ID
    assert payload["external_api_calls_made"] is False
    assert payload["earth_engine_initialized"] is False
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["human_review_required"] is True
    assert payload["missing_fields"] == []
    assert payload["gee_summary"]["smap_collection_id"] == "NASA/SMAP/SPL4SMGP/008"
    assert payload["gee_summary"]["gpm_collection_id"] == "NASA/GPM_L3/IMERG_V07"
    assert payload["gee_summary"]["smap_timeseries_count"] == 1
    assert payload["gee_summary"]["soil_moisture_grid_feature_count"] == 1
    assert payload["gee_summary"]["gpm_timeseries_count"] == 1
    assert payload["gee_summary"]["antecedent_rain_grid_feature_count"] == 1
    assert "NASA/SMAP/SPL4SMGP/008" in payload["field_answer"]
    assert "coarse 11km/3h candidate-only hydrologic background" in payload["field_answer"]
    assert "not a single-slope passability or runtime safety conclusion" in payload[
        "field_answer"
    ]
    smap_l4 = next(
        dataset
        for dataset in payload["gee_summary"]["supported_environment_datasets"]
        if dataset["collection_id"] == "NASA/SMAP/SPL4SMGP/008"
    )
    assert smap_l4["spatial_resolution_m"] == 11000
    assert smap_l4["human_review_required"] is True
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_gee_environment_tool_answers_corridor_metric_and_grid_questions() -> None:
    soil = assess_scout_gee_environment(
        PROJECT_ROOT,
        query="SMAP L4 corridor summary 的 surface、rootzone 與 profile soil moisture 是多少？",
    )
    wetness = assess_scout_gee_environment(
        PROJECT_ROOT,
        query="SMAP surface wetness 的 latest、mean、max、p95 與 trend 是什麼？",
    )
    antecedent = assess_scout_gee_environment(
        PROJECT_ROOT,
        query="antecedent rain grid 顯示最近累積降雨最高的位置在哪裡？",
    )
    gpm = assess_scout_gee_environment(
        PROJECT_ROOT,
        query="GPM IMERG corridor summary 的最新雨量與趨勢是什麼？",
    )

    assert "surface=0.301" in soil["field_answer"]
    assert "rootzone=0.318" in soil["field_answer"]
    assert "profile=0.302" in soil["field_answer"]
    assert "latest=0.74" in wetness["field_answer"]
    assert "mean=0.66" in wetness["field_answer"]
    assert "max=0.82" in wetness["field_answer"]
    assert "p95=0.78" in wetness["field_answer"]
    assert "trend=rising" in wetness["field_answer"]
    assert "route corridor rain cell" in antecedent["field_answer"]
    assert "lat=24.03" in antecedent["field_answer"]
    assert "lon=121.25" in antecedent["field_answer"]
    assert "72h=88.0 mm" in antecedent["field_answer"]
    assert "1h=4.0 mm" in gpm["field_answer"]
    assert "72h=88.0 mm" in gpm["field_answer"]
    assert "trend=rising" in gpm["field_answer"]
    assert soil["field_answer_priority"] == 100
    assert wetness["field_answer_priority"] == 100
    assert antecedent["field_answer_source_ref"].endswith(
        "antecedent_rain_grid.geojson"
    )
    assert gpm["field_answer_source_ref"].endswith(
        "gpm_imerg_corridor_summary.json"
    )


def test_gee_environment_tool_answers_prepared_compound_and_provenance_questions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    shutil.copytree(PROJECT_ROOT, project_root)
    derived_root = project_root / "outputs/environment/derived"
    derived_root.mkdir(parents=True)
    derivatives_ref = "outputs/environment/derived/environment_risk_derivatives.json"
    revalidation_ref = "outputs/environment/derived/route_revalidation_report.json"
    wetness_ref = (
        "outputs/environment/derived/wetness_flash_flood_susceptibility.geojson"
    )
    (project_root / derivatives_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "scout_environment_risk_derivatives",
                "counts": {
                    "new_landslide_candidate_count": 0,
                    "wetness_flash_flood_candidate_count": 3,
                    "trail_obscurity_candidate_count": 1,
                    "practical_darkness_candidate_count": 4,
                },
                "output_refs": {
                    "wetness_flash_flood_susceptibility_ref": (
                        "wetness_flash_flood_susceptibility.geojson"
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    (project_root / revalidation_ref).write_text(
        json.dumps(
            {
                "artifact_kind": "scout_route_revalidation_report",
                "status": "needs_event_date",
                "event_date": None,
                "notes": [
                    "event_date not supplied; rerun for a named earthquake or typhoon event."
                ],
            }
        ),
        encoding="utf-8",
    )
    (project_root / wetness_ref).write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "label": "濕滑/溪溝暴漲候選 12.7K",
                            "severity": "high",
                            "score": 0.91,
                            "missing_metrics": ["gpm_recent_rainfall"],
                            "supporting_metrics": {
                                "slope_deg": 39.4,
                                "gpm_recent_rainfall_mm": None,
                            },
                        },
                        "geometry": {"type": "LineString", "coordinates": []},
                    },
                    {
                        "type": "Feature",
                        "properties": {
                            "label": "濕滑/溪溝暴漲候選 11.2K",
                            "severity": "high",
                            "score": 0.87,
                            "missing_metrics": ["gpm_recent_rainfall"],
                            "supporting_metrics": {"slope_deg": 35.0},
                        },
                        "geometry": {"type": "LineString", "coordinates": []},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    factor_path = project_root / "outputs/environment/environment_factor_matrix.json"
    factor_path.write_text(
        json.dumps(
            {
                "artifact_kind": "environment_factor_matrix",
                "factors": {
                    "rain_forecast": {"max_rain_probability": 70},
                    "rain_observed": {"max_24h_mm": None},
                    "antecedent_rain": {
                        "last_72h_mm": 13.6,
                        "last_24h_mm": None,
                    },
                    "antecedent_wetness": {"sm_surface_wetness": 0.76},
                },
                "missing_evidence": [],
            }
        ),
        encoding="utf-8",
    )
    source_refs = [
        "outputs/environment/cwa/qpf_corridor_summary.json",
        "outputs/environment/gee/smap_l4_corridor_summary.json",
    ]
    go_no_go_path = project_root / "outputs/environment/go_no_go_review_draft.json"
    go_no_go_path.write_text(
        json.dumps({"evidence_source_refs": source_refs, "missing_evidence": []}),
        encoding="utf-8",
    )
    package_path = project_root / "outputs/environment/environment_evidence_package.json"
    package_path.write_text(
        json.dumps({"source_refs": source_refs, "missing_evidence": []}),
        encoding="utf-8",
    )
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update(
        {
            "environment_risk_derivatives_ref": derivatives_ref,
            "route_revalidation_report_ref": revalidation_ref,
        }
    )
    project_path.write_text(json.dumps(project), encoding="utf-8")

    matrix = assess_scout_gee_environment(
        project_root,
        query="environment factor matrix 中哪些因素已有資料，哪些仍缺失？",
    )
    derivative = assess_scout_gee_environment(
        project_root,
        query="environment risk derivatives 產生了哪些 compound candidate 類型？",
    )
    compound = assess_scout_gee_environment(
        project_root,
        query="QPF、SMAP、recent rain 與 terrain evidence 在哪幾段形成複合候選？",
    )
    revalidation = assess_scout_gee_environment(
        project_root,
        query="route revalidation report 將哪些環境證據標成 stale 或 missing？",
    )
    go_no_go = assess_scout_gee_environment(
        project_root,
        query="go/no-go review draft 引用了哪些 weather 與 terrain evidence？",
    )
    provenance = assess_scout_gee_environment(
        project_root,
        query="environment evidence package 的 provenance refs 是否完整？",
    )

    assert "rain_forecast" in matrix["field_answer"]
    assert "rain_observed.max_24h_mm" in matrix["field_answer"]
    assert "antecedent_rain.last_24h_mm" in matrix["field_answer"]
    assert "new_landslide_candidate=0" in derivative["field_answer"]
    assert "wetness_flash_flood_candidate=3" in derivative["field_answer"]
    assert "完整四因子複合候選 0 段" in compound["field_answer"]
    assert "高風險 2 段" in compound["field_answer"]
    assert "12.7K" in compound["field_answer"]
    assert "per-segment QPF" in compound["field_answer"]
    assert "status=needs_event_date" in revalidation["field_answer"]
    assert "event_date=missing" in revalidation["field_answer"]
    assert "named stale evidence=none" in revalidation["field_answer"]
    assert "CWA weather refs=1" in go_no_go["field_answer"]
    assert "GEE weather refs=1" in go_no_go["field_answer"]
    assert "terrain refs=0" in go_no_go["field_answer"]
    assert "listed=2" in provenance["field_answer"]
    assert "existing=2" in provenance["field_answer"]
    assert "missing=0" in provenance["field_answer"]
    assert provenance["field_answer_source_ref"].endswith(
        "environment_evidence_package.json"
    )


def test_environment_tools_are_registered_and_executable() -> None:
    registry = tool_registry_output(include_not_implemented=False)
    by_id = {tool.tool_id: tool for tool in registry.tools}

    assert CWA_ENVIRONMENT_TOOL_ID in by_id
    assert GEE_ENVIRONMENT_TOOL_ID in by_id
    assert by_id[CWA_ENVIRONMENT_TOOL_ID].output_artifact_kind == CWA_ENVIRONMENT_OUTPUT_KIND
    assert by_id[GEE_ENVIRONMENT_TOOL_ID].output_artifact_kind == GEE_ENVIRONMENT_OUTPUT_KIND
    assert "scout.ai.cwa_weather.assess" in by_id[CWA_ENVIRONMENT_TOOL_ID].aliases
    assert "scout.ai.smap_gpm_environment.assess" in by_id[GEE_ENVIRONMENT_TOOL_ID].aliases

    cwa_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.cwa_environment.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "官方 CWA QPF 有什麼?",
            "limit": 3,
        }
    )
    assert cwa_result.status == "completed"
    assert cwa_result.output_artifact_kind == CWA_ENVIRONMENT_OUTPUT_KIND
    assert cwa_result.payload["cwa_summary"]["qpf_summary_available"] is True

    gee_result = execute_scout_ai_tool(
        {
            "tool_id": "scout.ai.gee_environment.assess",
            "project_root": str(PROJECT_ROOT),
            "query": "GEE SMAP GPM 有什麼?",
            "limit": 3,
        }
    )
    assert gee_result.status == "completed"
    assert gee_result.output_artifact_kind == GEE_ENVIRONMENT_OUTPUT_KIND
    assert gee_result.payload["gee_summary"]["smap_collection_id"] == "NASA/SMAP/SPL4SMGP/008"


def test_planner_selects_separate_cwa_and_gee_environment_tools() -> None:
    cwa_plan = plan_scout_ai_tools(
        _query("中央氣象署 CWA QPF 對這條路線有什麼警示？"),
        project_root=PROJECT_ROOT,
    )
    cwa_ids = [item.tool_id for item in cwa_plan.selected_tools]
    assert CWA_ENVIRONMENT_TOOL_ID in cwa_ids

    gee_plan = plan_scout_ai_tools(
        _query("GEE SMAP 土壤含水和 GPM 累積雨量顯示什麼？"),
        project_root=PROJECT_ROOT,
    )
    gee_ids = [item.tool_id for item in gee_plan.selected_tools]
    assert GEE_ENVIRONMENT_TOOL_ID in gee_ids


def test_answer_synthesis_uses_environment_tool_field_answers() -> None:
    cwa_answer = collect_and_synthesize_scout_ai_answer(
        "中央氣象署 CWA QPF 對這條路線有什麼警示？",
        project_root=PROJECT_ROOT,
        surface=AssistantSurface.PRETRIP,
        limit=4,
    )
    assert cwa_answer.completed_source_count >= 1
    assert CWA_ENVIRONMENT_TOOL_ID in {source.tool_id for source in cwa_answer.sources}
    assert "CWA workspace evidence" in cwa_answer.answer
    assert cwa_answer.boundary.runtime_safety_truth is False

    gee_answer = collect_and_synthesize_scout_ai_answer(
        "GEE SMAP 土壤含水和 GPM 累積雨量顯示什麼？",
        project_root=PROJECT_ROOT,
        surface=AssistantSurface.PRETRIP,
        limit=4,
    )
    assert gee_answer.completed_source_count >= 1
    assert GEE_ENVIRONMENT_TOOL_ID in {source.tool_id for source in gee_answer.sources}
    assert "GEE workspace evidence" in gee_answer.answer
    assert "candidate-only hydrologic background" in gee_answer.answer
    assert gee_answer.boundary.runtime_safety_truth is False


def _query(question: str) -> ScoutAssistantQuery:
    return ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=question,
        project_id="chilai_nanhua_day1",
    )
