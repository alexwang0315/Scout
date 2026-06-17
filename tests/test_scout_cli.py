from __future__ import annotations

import json
import shutil
from pathlib import Path

from scout_agent_trace import load_agent_trace
from scout_cli import run_scout_cli
from pretrip_contextual_permission_collection import CONTEXTUAL_PERMISSION_RULES_REF
from pretrip_navigation_terrain_collection import OFFLINE_MAP_MANIFEST_REF
from pretrip_pace_fit_collection import PACE_COEFFICIENTS_REF, TEAM_PACE_FIT_REF
from pretrip_boss_point_synthesis import BOSS_POINTS_REF
from pretrip_route_architecture_collection import ROUTE_ARCHITECTURE_REF
from pretrip_route_context_collection import (
    ROUTE_CONTEXT_BRIEFING_REF,
    ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF,
    ROUTE_CONTEXT_PACK_REF,
    ROUTE_CONTEXT_POINTS_REF,
)
from pretrip_weather_decision_collection import (
    ROUTE_WEATHER_PACKAGE_REF,
    WEATHER_DECISION_CANDIDATES_REF,
)
from tests.test_admin_local_raster_source import _write_sample_geotiff


REPO_ROOT = Path(__file__).resolve().parents[1]
CHILAI_PROJECT = (
    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
POST_ANALYSIS_OUTPUTS = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "outputs"
)


def test_scout_tools_list_uses_default_manifest_dir() -> None:
    exit_code, payload = run_scout_cli(["tools", "list", "--json"])

    assert exit_code == 0
    tool_ids = {tool["id"] for tool in payload["tools"]}
    assert "scout.kb.build" in tool_ids
    assert "scout.kb.query" in tool_ids
    assert "scout.safety_action.shelter_direction" in tool_ids
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_scout_kb_query_facade_runs_registered_tool(tmp_path: Path) -> None:
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "kb",
            "query",
            "--project-root",
            str(CHILAI_PROJECT),
            "--query",
            "大崩壁",
            "--limit",
            "2",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_kb_query_tool_output"
    assert output["boundary"]["local_evidence_only"] is True
    assert output["query_result"]["result_count"] >= 1
    assert load_agent_trace(trace_log)[0].tool_id == "scout.kb.query"


def test_scout_kb_build_facade_persists_index_for_query(tmp_path: Path) -> None:
    trace_log = tmp_path / "agent-trace.jsonl"
    index_path = tmp_path / "outputs" / "kb" / "local-evidence-index.json"

    dry_exit, dry_payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "kb",
            "build",
            "--project-root",
            str(CHILAI_PROJECT),
            "--out",
            str(index_path),
            "--dry-run",
            "--json",
        ]
    )
    blocked_exit, blocked_payload = run_scout_cli(
        [
            "kb",
            "build",
            "--project-root",
            str(CHILAI_PROJECT),
            "--out",
            str(index_path),
            "--json",
        ]
    )
    exit_code, payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "kb",
            "build",
            "--project-root",
            str(CHILAI_PROJECT),
            "--out",
            str(index_path),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )
    query_exit, query_payload = run_scout_cli(
        [
            "kb",
            "query",
            "--index-path",
            str(index_path),
            "--query",
            "大崩壁",
            "--limit",
            "1",
            "--json",
        ]
    )

    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["index"]["project_id"] == "chilai_nanhua_day1"
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_kb_build_tool_output"
    assert output["artifact_refs"] == [str(index_path)]
    assert index_path.is_file()
    assert query_exit == 0
    query_output = json.loads(query_payload["outputs"]["stdout"])
    assert query_output["query_result"]["result_count"] == 1
    assert [entry.tool_id for entry in load_agent_trace(trace_log)] == [
        "scout.kb.build",
        "scout.kb.build",
    ]


def test_scout_hardware_readiness_summary_facade_is_read_only(tmp_path: Path) -> None:
    trace_log = tmp_path / "agent-trace.jsonl"
    fixture = REPO_ROOT / "tests" / "fixtures" / "hardware" / "readiness_context.json"

    exit_code, payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "hardware",
            "readiness-summary",
            "--fixture-path",
            str(fixture),
            "--selected-provider-ref",
            "provider.gnss.primary",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_kb_hardware_readiness_summary"
    assert output["summary"]["provider_count"] == 2
    assert output["selected_provider"]["provider_ref"] == "provider.gnss.primary"
    assert output["boundary"]["hardware_control_allowed"] is False
    assert output["boundary"]["provider_control_allowed"] is False
    assert load_agent_trace(trace_log)[0].tool_id == "scout.kb.hardware_readiness_summary"


def test_scout_checks_facade_runs_read_only_gates(tmp_path: Path) -> None:
    trace_log = tmp_path / "agent-trace.jsonl"

    pretrip_exit, pretrip_payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "checks",
            "pretrip-release",
            "--repo-root",
            str(REPO_ROOT),
            "--json",
        ]
    )
    runtime_exit, runtime_payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "checks",
            "runtime-readiness",
            "--repo-root",
            str(REPO_ROOT),
            "--json",
        ]
    )

    assert pretrip_exit == 0
    assert runtime_exit == 0
    pretrip_output = json.loads(pretrip_payload["outputs"]["stdout"])
    runtime_output = json.loads(runtime_payload["outputs"]["stdout"])
    assert pretrip_output["artifact_kind"] == "scout_check_pretrip_release"
    assert runtime_output["artifact_kind"] == "scout_check_runtime_readiness"
    assert isinstance(pretrip_output["report"]["ok"], bool)
    assert isinstance(runtime_output["report"]["ok"], bool)
    assert isinstance(pretrip_output["report"]["failed_checks"], list)
    assert isinstance(runtime_output["report"]["missing_required_artifacts"], list)
    assert pretrip_output["boundary"]["live_safety_api_calls_allowed"] is False
    assert runtime_output["boundary"]["live_safety_api_calls_allowed"] is False
    trace = load_agent_trace(trace_log)
    assert [entry.tool_id for entry in trace] == [
        "scout.checks.pretrip_release",
        "scout.checks.runtime_readiness",
    ]


def test_scout_map_facade_runs_preparation_tools(tmp_path: Path) -> None:
    source = tmp_path / "sample_wgs84.tiff"
    _write_sample_geotiff(source)

    source_exit, source_payload = run_scout_cli(
        [
            "map",
            "raster-source",
            "--source-geotiff",
            str(source),
            "--project-id",
            "chilai_nanhua_day1",
            "--json",
        ]
    )
    assert source_exit == 0
    source_output = json.loads(source_payload["outputs"]["stdout"])
    assert source_output["manifest"]["source_file"]["raw_raster_committed_to_repo_allowed"] is False

    source_manifest_path = tmp_path / "source.manifest.json"
    source_manifest_path.write_text(
        json.dumps(source_output["manifest"], ensure_ascii=False),
        encoding="utf-8",
    )
    tiles_exit, tiles_payload = run_scout_cli(
        [
            "map",
            "raster-tiles",
            "--source-manifest",
            str(source_manifest_path),
            "--cache-root",
            str(tmp_path / "raster-tiles"),
            "--min-zoom",
            "5",
            "--max-zoom",
            "5",
            "--max-tiles",
            "1",
            "--dry-run",
            "--json",
        ]
    )
    assert tiles_exit == 0
    tiles_output = json.loads(tiles_payload["outputs"]["stdout"])
    assert tiles_output["cut_summary"]["status"] == "dry_run_ready"
    assert tiles_output["boundary"]["local_tile_cache_write_allowed"] is False

    plan_exit, plan_payload = run_scout_cli(
        [
            "map",
            "tile-cache-plan",
            "--project-root",
            str(CHILAI_PROJECT),
            "--cache-root",
            str(tmp_path / "osm-tiles"),
            "--min-zoom",
            "5",
            "--max-zoom",
            "6",
            "--json",
        ]
    )
    assert plan_exit == 0
    plan_output = json.loads(plan_payload["outputs"]["stdout"])
    assert plan_output["plan"]["artifact_kind"] == "admin_tile_cache_plan"
    assert plan_output["boundary"]["external_network_fetch_allowed"] is False


def test_scout_evidence_sensorlog_to_gpx_facade_requires_authorized_write(
    tmp_path: Path,
) -> None:
    sensorlog = tmp_path / "sensorlog.json"
    output_gpx = tmp_path / "track.gpx"
    sensorlog.write_text(
        json.dumps(
            [
                {
                    "loggingTime": "2026-05-11T08:52:12.450+08:00",
                    "locationLatitude": "25.063521",
                    "locationLongitude": "121.653987",
                    "locationHorizontalAccuracy": "14.0",
                    "heartRateBPM": "111.000000",
                }
            ]
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_cli(
        [
            "evidence",
            "sensorlog-to-gpx",
            "--input",
            str(sensorlog),
            "--output",
            str(output_gpx),
            "--dry-run",
            "--json",
        ]
    )
    blocked_exit, blocked_payload = run_scout_cli(
        [
            "evidence",
            "sensorlog-to-gpx",
            "--input",
            str(sensorlog),
            "--output",
            str(output_gpx),
            "--json",
        ]
    )
    exit_code, payload = run_scout_cli(
        [
            "evidence",
            "sensorlog-to-gpx",
            "--input",
            str(sensorlog),
            "--output",
            str(output_gpx),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["track_point_count"] == 1
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_evidence_sensorlog_to_gpx"
    assert output["track_point_count"] == 1
    assert output["boundary"]["phase1_safety_mutation_allowed"] is False
    assert output_gpx.is_file()


def test_scout_pretrip_read_only_facades_expose_manifest_readiness_and_register() -> None:
    route_plan = {
        "route_id": "same_day.short",
        "route_days": 1,
        "route_kind": "out_and_back",
        "distance_m": 8200,
    }

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        route_plan_path = Path(tmp) / "route-plan.json"
        route_plan_path.write_text(json.dumps(route_plan), encoding="utf-8")

        manifest_exit, manifest_payload = run_scout_cli(
            [
                "pretrip",
                "artifact-manifest",
                "--project-root",
                str(CHILAI_PROJECT),
                "--json",
            ]
        )
        readiness_exit, readiness_payload = run_scout_cli(
            [
                "pretrip",
                "readiness",
                "--route-plan",
                str(route_plan_path),
                "--config",
                str(CHILAI_PROJECT / "candidates" / "skill_config_manifest.json"),
                "--json",
            ]
        )
        register_exit, register_payload = run_scout_cli(
            ["pretrip", "decision-register", "--json"]
        )

    assert manifest_exit == 0
    manifest_output = json.loads(manifest_payload["outputs"]["stdout"])
    assert manifest_output["manifest"]["counts"]["missing_refs"] == 0
    assert manifest_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert readiness_exit == 0
    readiness_output = json.loads(readiness_payload["outputs"]["stdout"])
    assert readiness_output["readiness"]["status"] == "warning"
    assert readiness_output["boundary"]["hard_readiness_mutation_allowed"] is False
    assert register_exit == 0
    register_output = json.loads(register_payload["outputs"]["stdout"])
    assert register_output["summary"]["resolved_count"] == 16
    assert register_output["boundary"]["runtime_activation_allowed"] is False


def test_scout_pretrip_route_context_collect_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "route-context-collect",
            "--project-root",
            str(project_root),
            "--limit-route-notes",
            "8",
            "--route-keyword",
            "奇萊-南華",
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["writes_performed"] is False
    assert not (project_root / ROUTE_CONTEXT_POINTS_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "route-context-collect",
            "--project-root",
            str(project_root),
            "--limit-route-notes",
            "8",
            "--route-keyword",
            "奇萊-南華",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_route_context_collect_tool_output"
    assert output["result"]["writes_performed"] is True
    assert output["result"]["crawl_seed_count"] > output["result"]["route_context_point_count"]
    assert (project_root / ROUTE_CONTEXT_PACK_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_CRAWL_SEED_PLAN_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_BRIEFING_REF).is_file()
    assert (project_root / ROUTE_CONTEXT_POINTS_REF).is_file()


def test_scout_pretrip_route_architecture_collect_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "route-architecture-collect",
            "--project-root",
            str(project_root),
            "--limit",
            "8",
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["writes_performed"] is False
    assert not (project_root / ROUTE_ARCHITECTURE_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "route-architecture-collect",
            "--project-root",
            str(project_root),
            "--current-time",
            "2013-10-08T15:05:00+08:00",
            "--limit",
            "8",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_route_architecture_collect_tool_output"
    assert output["result"]["decision"] == "CHANGE_PLAN"
    assert output["result"]["writes_performed"] is True
    assert (project_root / ROUTE_ARCHITECTURE_REF).is_file()


def test_scout_pretrip_pace_fit_collect_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    team_members_json = json.dumps(
        [
            {
                "member_id": "leader",
                "display_label": "Leader",
                "pace_mps": 1.15,
                "reserve_minutes": 55,
                "fatigue_band": "normal",
            },
            {
                "member_id": "teammate",
                "display_label": "New teammate",
                "pace_mps": 0.58,
                "reserve_minutes": 8,
                "fatigue_band": "tired",
                "rest_need_minutes": 12,
                "first_time_similar_route": True,
                "conditions": ["sleep_debt", "knee_pain"],
            },
        ],
        ensure_ascii=False,
    )

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "pace-fit-collect",
            "--project-root",
            str(project_root),
            "--team-members-json",
            team_members_json,
            "--minutes-to-next-cp",
            "24",
            "--current-delay-minutes",
            "22",
            "--leader-accepts-slowest-basis",
            "false",
            "--team-rest-sync",
            "mismatched",
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["writes_performed"] is False
    assert not (project_root / TEAM_PACE_FIT_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "pace-fit-collect",
            "--project-root",
            str(project_root),
            "--team-members-json",
            team_members_json,
            "--minutes-to-next-cp",
            "24",
            "--current-delay-minutes",
            "22",
            "--leader-accepts-slowest-basis",
            "false",
            "--team-rest-sync",
            "mismatched",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_pace_fit_collect_tool_output"
    assert output["result"]["decision"] == "CHANGE_PLAN"
    assert output["result"]["writes_performed"] is True
    assert output["result"]["member_count"] == 2
    assert output["result"]["boundary"]["average_pace_used"] is False
    assert (project_root / TEAM_PACE_FIT_REF).is_file()


def test_scout_pretrip_pace_fit_collect_builds_from_capability(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    _copy_post_analysis_outputs(project_root)

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "pace-fit-collect",
            "--project-root",
            str(project_root),
            "--build-from-capability",
            "--member-id",
            "alex",
            "--display-label",
            "Alex",
            "--pack-weight-kg",
            "12",
            "--weather-impact-ratio",
            "0.18",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_pace_fit_collect_tool_output"
    assert output["result"]["writes_performed"] is True
    assert output["result"]["member_count"] == 1
    assert output["result"]["coefficient_builder"]["status"] == "completed"
    coefficients = json.loads((project_root / PACE_COEFFICIENTS_REF).read_text())
    assert coefficients["member_coefficients"][0]["member_id"] == "alex"
    assert coefficients["member_coefficients"][0]["load_impact_ratio"] == 0.09
    assert (project_root / TEAM_PACE_FIT_REF).is_file()


def test_scout_pretrip_boss_points_synthesize_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "boss-points-synthesize",
            "--project-root",
            str(project_root),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["boss_point_count"] == 5
    assert dry_output["result"]["boundary"]["workspace_file_mutation_allowed"] is False
    assert not (project_root / BOSS_POINTS_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "boss-points-synthesize",
            "--project-root",
            str(project_root),
            "--slow-passage-min-span-m",
            "500",
            "--pressure-profile-bin-m",
            "500",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_boss_points_synthesize_tool_output"
    assert output["result"]["policy"]["slow_passage_min_span_m"] == 500.0
    assert output["result"]["policy"]["pressure_profile_bin_m"] == 500.0
    assert output["result"]["route_pressure_profile_summary"]["sample_count"] > 0
    assert output["result"]["boss_points"][0]["display_theme"]["alias"] == "呂布關"
    assert output["result"]["boss_points"][0]["label"].startswith("高壓路段")
    assert output["result"]["challenge_fit_summary"]["decision"] == (
        "CHANGE_PLAN_OR_ADD_BUFFER"
    )
    assert (project_root / BOSS_POINTS_REF).is_file()


def test_scout_pretrip_navigation_terrain_collect_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "navigation-terrain-collect",
            "--project-root",
            str(project_root),
            "--offline-map-downloaded",
            "false",
            "--gpx-loaded-on-device",
            "false",
            "--contour-skill-confirmed",
            "false",
            "--terrain-feature-skill-confirmed",
            "false",
            "--junction-points-known",
            "false",
            "--retreat-direction-understood",
            "false",
            "--backup-positioning-available",
            "false",
            "--terrain-risk-layers-understood",
            "false",
            "--team-map-user-count",
            "1",
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["writes_performed"] is False
    assert not (project_root / OFFLINE_MAP_MANIFEST_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "navigation-terrain-collect",
            "--project-root",
            str(project_root),
            "--offline-map-downloaded",
            "false",
            "--gpx-loaded-on-device",
            "false",
            "--contour-skill-confirmed",
            "false",
            "--terrain-feature-skill-confirmed",
            "false",
            "--junction-points-known",
            "false",
            "--retreat-direction-understood",
            "false",
            "--backup-positioning-available",
            "false",
            "--terrain-risk-layers-understood",
            "false",
            "--team-map-user-count",
            "1",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == (
        "scout_pretrip_navigation_terrain_collect_tool_output"
    )
    assert output["result"]["decision"] == "GUIDED_ONLY"
    assert output["result"]["writes_performed"] is True
    assert output["result"]["map_readiness"]["junction_points_known"] is False
    assert (
        output["result"]["map_readiness"]["terrain_risk_layers_understood"] is False
    )
    assert output["result"]["boundary"]["live_sensor_read_allowed"] is False
    assert (project_root / OFFLINE_MAP_MANIFEST_REF).is_file()


def test_scout_pretrip_weather_decision_collect_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    weather_points = project_root / "normalized" / "weather" / "forecast_snapshots.json"
    weather_points.parent.mkdir(parents=True, exist_ok=True)
    weather_points.write_text(
        json.dumps(
            [
                {
                    "source": "fixture_cwa_forecast",
                    "source_run_id": "cwa.fixture.cli",
                    "validFrom": "2099-06-08T04:00:00+08:00",
                    "validTo": "2099-06-08T07:00:00+08:00",
                    "areaName": "仁愛鄉",
                    "weatherText": "午後雷陣雨",
                    "rainProbability": 80,
                    "rainfallMm": 18,
                    "windSpeedMps": 12,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "weather-decision-collect",
            "--project-root",
            str(project_root),
            "--weather-points",
            "normalized/weather/forecast_snapshots.json",
            "--default-township",
            "仁愛鄉",
            "--generated-at",
            "2099-06-07T08:00:00Z",
            "--valid-until",
            "2099-06-10T08:00:00Z",
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["writes_performed"] is False
    assert not (project_root / ROUTE_WEATHER_PACKAGE_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "weather-decision-collect",
            "--project-root",
            str(project_root),
            "--weather-points",
            "normalized/weather/forecast_snapshots.json",
            "--default-township",
            "仁愛鄉",
            "--generated-at",
            "2099-06-07T08:00:00Z",
            "--valid-until",
            "2099-06-10T08:00:00Z",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == (
        "scout_pretrip_weather_decision_collect_tool_output"
    )
    assert output["result"]["decision"] == "CHANGE_PLAN"
    assert output["result"]["writes_performed"] is True
    assert (project_root / ROUTE_WEATHER_PACKAGE_REF).is_file()
    assert (project_root / WEATHER_DECISION_CANDIDATES_REF).is_file()


def test_scout_pretrip_contextual_permission_collect_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "contextual-permission-collect",
            "--project-root",
            str(project_root),
            "--remaining-safety-buffer-minutes",
            "90",
            "--current-time",
            "2026-06-07T13:36:00+08:00",
            "--next-cp-id",
            "CP4",
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["result"]["writes_performed"] is False
    assert not (project_root / CONTEXTUAL_PERMISSION_RULES_REF).exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "contextual-permission-collect",
            "--project-root",
            str(project_root),
            "--remaining-safety-buffer-minutes",
            "90",
            "--current-time",
            "2026-06-07T13:36:00+08:00",
            "--next-cp-id",
            "CP4",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == (
        "scout_pretrip_contextual_permission_collect_tool_output"
    )
    assert output["result"]["writes_performed"] is True
    assert output["result"]["bounded_permission_count"] >= 4
    assert (project_root / CONTEXTUAL_PERMISSION_RULES_REF).is_file()


def test_scout_cp_apply_reviewed_delta_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    destination = project_root / "outputs" / "cp_reviewed_delta.json"

    dry_exit, dry_payload = run_scout_cli(
        [
            "cp",
            "apply-reviewed-delta",
            "--project-root",
            str(project_root),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["delta"]["counts"]["action_count"] == 2
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert not destination.exists()

    exit_code, payload = run_scout_cli(
        [
            "cp",
            "apply-reviewed-delta",
            "--project-root",
            str(project_root),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["delta"]["artifact_kind"] == "pretrip_cp_reviewed_delta"
    assert output["delta"]["boundary"]["reversible"] is True
    assert output["delta"]["boundary"]["runtime_mutation_allowed"] is False
    assert destination.is_file()


def test_scout_safety_action_shelter_direction_facade_is_advisory(tmp_path: Path) -> None:
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "safety-action",
            "shelter-direction",
            "--project-root",
            str(CHILAI_PROJECT),
            "--lat",
            "24.0300",
            "--lon",
            "121.2840",
            "--query",
            "目前氣候不好，我需要隱蔽，幫我指出方向",
            "--ttl-seconds",
            "300",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_safety_action_shelter_direction"
    assert output["ttl_seconds"] == 300
    assert output["evidence_summary"]["risk_ribbon"]["source_ref"] == "outputs/risk_ribbon.geojson"
    assert output["recommended_target"]["risk_context"]["candidate_only"] is True
    assert output["recommended_target"]["route_context"]["route_source_ref"] == "normalized/routes/route_summary.json"
    assert output["boundary"]["runtime_safety_truth"] is False
    assert output["boundary"]["phase1_safety_mutation_allowed"] is False
    assert load_agent_trace(trace_log)[0].mode == "ephemeral_safety_action"


def test_scout_note_append_facade_records_taxonomy_and_retention(tmp_path: Path) -> None:
    trace_log = tmp_path / "agent-trace.jsonl"
    runtime_log = tmp_path / "runtime-debug.jsonl"

    blocked_exit, blocked_payload = run_scout_cli(
        [
            "note",
            "append-flight-recorder",
            "--debug-log-path",
            str(runtime_log),
            "--text",
            "領隊決定先等雨勢變小。",
            "--note-kind",
            "operator_decision",
            "--json",
        ]
    )
    exit_code, payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "note",
            "append-flight-recorder",
            "--debug-log-path",
            str(runtime_log),
            "--text",
            "領隊決定先等雨勢變小。",
            "--note-kind",
            "operator_decision",
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["note_taxonomy"]["selected_category"] == "operator_decision"
    assert output["retention_policy"]["profile"] == "audit_extended"
    assert output["boundary"]["phase2_observed_fact_write_allowed"] is False
    assert load_agent_trace(trace_log)[0].tool_id == "scout.note.append_flight_recorder"


def test_scout_imprint_trigger_dry_run_facade(tmp_path: Path) -> None:
    context_path = tmp_path / "trigger-context.json"
    context_path.write_text(
        json.dumps(
            {
                "client_id": "client.alex.watch",
                "scout_machine_id": "scout.pi5.alpha01",
                "trip_id": "chilai_nanhua_day1",
                "observed_at": "2026-05-26T10:03:00+08:00",
                "client_group_refs": ["current_trip_party"],
                "position": {
                    "lat": 24.0300,
                    "lon": 121.2840,
                    "altitude_m": 2888.0,
                },
                "motion": {"heading_degrees": 318.0},
                "route_progress": {
                    "route_id": "chilai_nanhua_day1",
                    "segment_ref": "segment_017",
                    "progress_m": 8395.0,
                    "nearest_cp_ref": "cp_018",
                    "distance_to_nearest_cp_m": 42.0,
                },
                "risk_context": {
                    "risk_score": 0.78,
                    "risk_zone_refs": ["risk_zone.collapse_wall.017"],
                },
                "sensor_state": {
                    "barometer_available": True,
                    "magnetometer_available": True,
                    "imu_available": True,
                    "gnss_confidence": 0.62,
                    "pdr_confidence": 0.55,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_cli(
        [
            "imprint",
            "trigger-dry-run",
            "--imprint-set",
            str(CHILAI_PROJECT / "outputs" / "spatial_imprint_set.json"),
            "--context",
            str(context_path),
            "--json",
        ]
    )

    assert exit_code == 0
    report = json.loads(payload["outputs"]["stdout"])
    assert report["counts"]["triggered"] == 1
    assert report["events"][0]["imprint_id"] == "spatial_imprint.chilai.collapse_wall.017"
    assert report["boundary"]["live_safety_api_calls_allowed"] is False


def test_scout_sos_playbook_run_facade_is_authorized_mock_only(tmp_path: Path) -> None:
    sos_event = tmp_path / "sos-event.json"
    debug_log = tmp_path / "runtime-debug.jsonl"
    voice_log = tmp_path / "voice.jsonl"
    trace_log = tmp_path / "agent-trace.jsonl"
    sos_event.write_text(
        json.dumps(
            {
                "sos_event_id": "sos_event.facade.0001",
                "activation_source": "explicit_sos_command",
                "activated_at": "2026-05-27T10:00:00+08:00",
                "trip_id": "chilai_nanhua_day1",
                "client_id": "client.alex.watch",
                "position": {
                    "lat": 24.0300,
                    "lon": 121.2840,
                    "source": "fixture_position",
                },
                "message_zh": "測試 SOS facade，不做真實傳送。",
                "source_refs": ["fixture.sos.manual"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_cli(
        [
            "sos",
            "playbook-run",
            "--sos-event",
            str(sos_event),
            "--debug-log-path",
            str(debug_log),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["dry_run"] is True
    assert dry_output["boundary"]["real_sos_sent"] is False
    assert not debug_log.exists()

    exit_code, payload = run_scout_cli(
        [
            "--trace-log",
            str(trace_log),
            "sos",
            "playbook-run",
            "--sos-event",
            str(sos_event),
            "--debug-log-path",
            str(debug_log),
            "--voice-log-path",
            str(voice_log),
            "--recipient-ref",
            "remote_contact.primary",
            "--mock-deliver",
            "--authorized-by",
            "sos.manual.button",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_sos_playbook_run"
    assert output["counts"]["mock_outbound_message_count"] == 1
    assert output["counts"]["real_outbound_send_count"] == 0
    assert output["boundary"]["mock_outbound_only"] is True
    assert output["boundary"]["hardware_control_allowed"] is False
    assert debug_log.exists()
    assert voice_log.exists()
    assert load_agent_trace(trace_log)[0].tool_id == "scout.sos.playbook_run"


def test_scout_voice_mock_queue_and_transition_facade(tmp_path: Path) -> None:
    voice_log = tmp_path / "voice.jsonl"
    debug_log = tmp_path / "runtime-debug.jsonl"

    queue_exit, queue_payload = run_scout_cli(
        [
            "voice",
            "mock-queue",
            "--voice-log-path",
            str(voice_log),
            "--debug-log-path",
            str(debug_log),
            "--cue-id",
            "voice_cue.facade.mock.001",
            "--text",
            "前方有落差，請放慢。",
            "--priority",
            "warning",
            "--category",
            "route",
            "--json",
        ]
    )
    assert queue_exit == 0
    queue_output = json.loads(queue_payload["outputs"]["stdout"])
    assert queue_output["record"]["state"] == "queued"
    assert queue_output["boundary"]["audio_playback_allowed"] is False

    transition_exit, transition_payload = run_scout_cli(
        [
            "voice",
            "mock-transition",
            "--voice-log-path",
            str(voice_log),
            "--debug-log-path",
            str(debug_log),
            "--cue-id",
            "voice_cue.facade.mock.001",
            "--state",
            "played",
            "--json",
        ]
    )
    assert transition_exit == 0
    transition_output = json.loads(transition_payload["outputs"]["stdout"])
    assert transition_output["record"]["state"] == "played"
    assert transition_output["boundary"]["hardware_control_allowed"] is False


def test_scout_outbound_mock_queue_and_transition_facade(tmp_path: Path) -> None:
    outbound_log = tmp_path / "outbound.jsonl"
    debug_log = tmp_path / "runtime-debug.jsonl"

    queue_exit, queue_payload = run_scout_cli(
        [
            "outbound",
            "mock-queue",
            "--outbound-log-path",
            str(outbound_log),
            "--debug-log-path",
            str(debug_log),
            "--category",
            "checkin",
            "--recipient-ref",
            "scout_centre.client.mock",
            "--subject-ref",
            "agent_message.facade.001",
            "--body-preview",
            "Mock only check-in.",
            "--json",
        ]
    )
    assert queue_exit == 0
    queue_output = json.loads(queue_payload["outputs"]["stdout"])
    message_id = queue_output["message"]["message_id"]
    assert queue_output["message"]["state"] == "queued"
    assert queue_output["boundary"]["real_outbound_send_allowed"] is False

    transition_exit, transition_payload = run_scout_cli(
        [
            "outbound",
            "mock-transition",
            "--outbound-log-path",
            str(outbound_log),
            "--debug-log-path",
            str(debug_log),
            "--message-id",
            message_id,
            "--state",
            "mock-delivered",
            "--json",
        ]
    )
    assert transition_exit == 0
    transition_output = json.loads(transition_payload["outputs"]["stdout"])
    assert transition_output["message"]["state"] == "mock-delivered"
    assert transition_output["message"]["boundary"]["real_satellite_sent"] is False


def test_scout_pretrip_departure_reviewed_candidates_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    destination = project_root / "outputs" / "departure_reviewed_candidates.json"

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "departure-reviewed-candidates",
            "--project-root",
            str(project_root),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["package"]["counts"]["promoted_candidate_count"] == 2
    assert not destination.exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "departure-reviewed-candidates",
            "--project-root",
            str(project_root),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["package"]["boundary"]["runtime_mutation_allowed"] is False
    assert destination.is_file()


def test_scout_pretrip_review_append_decision_facade(tmp_path: Path) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    record_path = tmp_path / "review-decision.json"
    record_path.write_text(
        json.dumps(_extra_review_decision_record(), ensure_ascii=False),
        encoding="utf-8",
    )
    log_path = project_root / "reviews" / "review_decision_log.json"
    before = log_path.read_text(encoding="utf-8")

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "review",
            "append-decision",
            "--project-root",
            str(project_root),
            "--record",
            str(record_path),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["counts"]["action_count"] == 4
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert log_path.read_text(encoding="utf-8") == before

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "review",
            "append-decision",
            "--project-root",
            str(project_root),
            "--record",
            str(record_path),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_pretrip_review_append_decisions_tool_output"
    assert output["decision_count_added"] == 1
    assert output["boundary"]["append_only"] is True
    assert output["boundary"]["runtime_mutation_allowed"] is False
    persisted = json.loads(log_path.read_text(encoding="utf-8"))
    assert persisted["counts"]["action_count"] == 4


def test_scout_pretrip_runtime_export_facade(tmp_path: Path) -> None:
    project_root, final_graph_path, handoff_path = _write_runtime_export_inputs(tmp_path)
    export_id = "runtime_export.chilai_nanhua_day1.quick_review.v0"
    export_root = project_root / "runtime_exports" / export_id

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "runtime-export",
            "--workspace-root",
            str(project_root),
            "--final-mission-graph",
            str(final_graph_path),
            "--runtime-handoff",
            str(handoff_path),
            "--export-id",
            export_id,
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["manifest"]["artifact_kind"] == "pretrip_runtime_export_bundle"
    assert dry_output["boundary"]["runtime_activation_allowed"] is False
    assert not export_root.exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "runtime-export",
            "--workspace-root",
            str(project_root),
            "--final-mission-graph",
            str(final_graph_path),
            "--runtime-handoff",
            str(handoff_path),
            "--export-id",
            export_id,
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["manifest"]["counts"]["live_runtime_activation_count"] == 0
    assert output["boundary"]["safety_api_calls_allowed"] is False
    assert (export_root / "runtime_export_manifest.json").is_file()


def test_scout_pretrip_runtime_handoff_facade(tmp_path: Path) -> None:
    project_root, gate_path, final_graph_path, target_path, rollback_path = _write_runtime_handoff_inputs(tmp_path)
    destination = project_root / "outputs" / "runtime_handoff_manifest.json"

    dry_exit, dry_payload = run_scout_cli(
        [
            "pretrip",
            "runtime-handoff",
            "--workspace-root",
            str(project_root),
            "--departure-gate",
            str(gate_path),
            "--final-mission-graph",
            str(final_graph_path),
            "--handoff-id",
            "handoff.chilai_nanhua_day1.quick_review.agent_tool.v0",
            "--approved-by",
            "operator.alex",
            "--approved-at",
            "2026-05-27T12:00:00+08:00",
            "--handoff-target",
            str(target_path),
            "--rollback-reference",
            str(rollback_path),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["manifest"]["boundary"]["metadata_only"] is True
    assert not destination.exists()

    exit_code, payload = run_scout_cli(
        [
            "pretrip",
            "runtime-handoff",
            "--workspace-root",
            str(project_root),
            "--departure-gate",
            str(gate_path),
            "--final-mission-graph",
            str(final_graph_path),
            "--handoff-id",
            "handoff.chilai_nanhua_day1.quick_review.agent_tool.v0",
            "--approved-by",
            "operator.alex",
            "--approved-at",
            "2026-05-27T12:00:00+08:00",
            "--handoff-target",
            str(target_path),
            "--rollback-reference",
            str(rollback_path),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["manifest"]["boundary"]["live_runtime_mutation_allowed"] is False
    assert destination.is_file()


def _write_runtime_export_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    from tests.test_pretrip_runtime_export import _approved_chain

    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    _, final_graph, handoff = _approved_chain(project_root)
    final_graph_path = tmp_path / "final_mission_graph.json"
    handoff_path = tmp_path / "runtime_handoff_manifest.json"
    final_graph_path.write_text(final_graph.to_json(), encoding="utf-8")
    handoff_path.write_text(handoff.to_json(), encoding="utf-8")
    return project_root, final_graph_path, handoff_path


def _copy_post_analysis_outputs(project_root: Path) -> None:
    outputs = project_root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    for filename in (
        "capability_timeline.json",
        "capability_route_time_comparison.json",
    ):
        shutil.copy2(POST_ANALYSIS_OUTPUTS / filename, outputs / filename)


def _write_runtime_handoff_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    from tests.test_pretrip_runtime_export import _approved_chain

    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(CHILAI_PROJECT, project_root)
    gate, final_graph, handoff = _approved_chain(project_root)
    gate_path = tmp_path / "departure_gate.json"
    final_graph_path = tmp_path / "final_mission_graph.json"
    target_path = tmp_path / "handoff_target.json"
    rollback_path = tmp_path / "rollback_reference.json"
    gate_path.write_text(gate.to_json(), encoding="utf-8")
    final_graph_path.write_text(final_graph.to_json(), encoding="utf-8")
    target_path.write_text(handoff.handoff_target.model_dump_json(), encoding="utf-8")
    rollback_path.write_text(handoff.rollback_reference.model_dump_json(), encoding="utf-8")
    return project_root, gate_path, final_graph_path, target_path, rollback_path


def _extra_review_decision_record() -> dict[str, object]:
    return {
        "decision_id": "review_decision.chilai_nanhua_day1.accepted.local_extra_weather_policy",
        "draft_action_id": "review_draft.chilai_nanhua_day1.local_extra_weather_policy",
        "decision": "accepted",
        "candidate_ref": "local_extra_weather_policy.chilai_nanhua_day1.day1",
        "target_ids": ["route_corridor_weather_policy"],
        "source_review_queue_item_refs": [
            {
                "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
                "item_id": "review_queue.chilai_nanhua_day1.local_extra_weather_policy",
                "source_ref": "outputs/review_queue_manifest.json",
                "candidate_ref": "local_extra_weather_policy.chilai_nanhua_day1.day1",
            }
        ],
        "reviewer_alias": "trip_leader",
        "decided_at": "2026-05-15T10:15:00+08:00",
        "summary": "Accepted local appended weather policy pointer as candidate-only planning context.",
    }
