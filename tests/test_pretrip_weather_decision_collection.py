from __future__ import annotations

import json
import shutil
from pathlib import Path

from pretrip_artifact_manifest import build_pretrip_artifact_manifest
from pretrip_weather_decision_collection import (
    ROUTE_WEATHER_PACKAGE_REF,
    WEATHER_DECISION_CANDIDATES_REF,
    WEATHER_SOURCE_MANIFEST_REF,
    collect_pretrip_weather_decision,
)
from scout_weather_window_tool import assess_scout_weather_window
from tools.verify_pretrip_workspace_spec_alignment import _check_weather_decision_refs


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_weather_decision_collection_dry_run_plans_sec10_refs(tmp_path: Path) -> None:
    project_root = _copy_project(tmp_path)
    result = collect_pretrip_weather_decision(
        project_root,
        dry_run=True,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["artifact_kind"] == "pretrip_weather_decision_collection"
    assert result["dry_run"] is True
    assert result["writes_performed"] is False
    assert result["decision"] == "DELAY"
    assert result["outputs"]["weather_source_manifest_ref"] == WEATHER_SOURCE_MANIFEST_REF
    assert result["outputs"]["weather_decision_candidates_ref"] == (
        WEATHER_DECISION_CANDIDATES_REF
    )
    assert not (project_root / WEATHER_SOURCE_MANIFEST_REF).exists()
    assert not (project_root / WEATHER_DECISION_CANDIDATES_REF).exists()


def test_weather_decision_collection_writes_conservative_candidate_without_fresh_weather(
    tmp_path: Path,
) -> None:
    project_root = _copy_project(tmp_path)
    result = collect_pretrip_weather_decision(
        project_root,
        generated_at="2099-06-07T08:00:00Z",
    )

    assert result["writes_performed"] is True
    assert result["route_weather_package_built"] is False
    assert result["decision"] == "DELAY"

    source_manifest = json.loads(
        (project_root / WEATHER_SOURCE_MANIFEST_REF).read_text(encoding="utf-8")
    )
    candidates = json.loads(
        (project_root / WEATHER_DECISION_CANDIDATES_REF).read_text(encoding="utf-8")
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert source_manifest["artifact_kind"] == "pretrip_weather_source_manifest"
    assert source_manifest["cache_policy"]["live_fetch_performed"] is False
    assert source_manifest["cache_policy"]["client_cwa_api_key_allowed"] is False
    assert "weather_points" in source_manifest["required_missing_source_kinds"]
    assert candidates["artifact_kind"] == "pretrip_weather_decision_candidates"
    assert candidates["candidates"][0]["decision"] == "DELAY"
    assert "route_weather_package" in candidates["candidates"][0]["missing_fields"]
    assert candidates["candidates"][0]["runtime_safety_truth"] is False
    assert candidates["boundary"]["runtime_safety_truth"] is False
    assert project["weather_source_manifest_ref"] == WEATHER_SOURCE_MANIFEST_REF
    assert project["weather_decision_candidates_ref"] == WEATHER_DECISION_CANDIDATES_REF
    assert "route_weather_package_ref" not in project

    errors: list[str] = []
    summary = _check_weather_decision_refs(project_root, project, errors)
    assert errors == []
    assert summary["available"] is True
    assert summary["decision"] == "DELAY"
    assert summary["candidate_only"] is True
    assert summary["runtime_safety_truth"] is False


def test_weather_decision_collection_builds_route_package_for_scout_ai(
    tmp_path: Path,
) -> None:
    project_root = _copy_project(tmp_path)
    weather_points = project_root / "normalized" / "weather" / "forecast_snapshots.json"
    weather_points.parent.mkdir(parents=True, exist_ok=True)
    weather_points.write_text(
        json.dumps(
            [
                {
                    "source": "fixture_cwa_forecast",
                    "source_run_id": "cwa.fixture.20990607",
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

    result = collect_pretrip_weather_decision(
        project_root,
        weather_points_path="normalized/weather/forecast_snapshots.json",
        default_township="仁愛鄉",
        generated_at="2099-06-07T08:00:00Z",
        valid_until="2099-06-10T08:00:00Z",
    )

    assert result["writes_performed"] is True
    assert result["route_weather_package_built"] is True
    assert result["decision"] == "CHANGE_PLAN"
    assert (project_root / ROUTE_WEATHER_PACKAGE_REF).is_file()

    package = json.loads((project_root / ROUTE_WEATHER_PACKAGE_REF).read_text())
    candidates = json.loads(
        (project_root / WEATHER_DECISION_CANDIDATES_REF).read_text(encoding="utf-8")
    )
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert package["artifact_kind"] == "route_weather_package"
    assert package["segments"]
    assert package["wx_alerts"]
    assert package["boundary"]["runtime_safety_truth"] is False
    assert candidates["candidates"][0]["decision"] == "CHANGE_PLAN"
    assert "rain / wet terrain" in candidates["candidates"][0]["route_specific_conditions"]
    assert candidates["candidates"][0]["live_safety_api_calls_allowed"] is False
    assert project["route_weather_package_ref"] == ROUTE_WEATHER_PACKAGE_REF
    assert project["weather_decision_candidate_count"] == 1

    assessed = assess_scout_weather_window(project_root, query="午後雷雨是否要改線?")
    assert assessed["answerability"] == "route_weather_risk_available"
    assert assessed["decision"] == "CHANGE_PLAN"
    assert assessed["missing_fields"] == []

    manifest = build_pretrip_artifact_manifest(project_root / "project.json").to_dict()
    by_kind = {artifact["artifact_kind"]: artifact for artifact in manifest["artifacts"]}
    assert by_kind["route_weather_package"]["segment_count"] >= 1
    assert by_kind["weather_source_manifest"]["live_fetch_performed"] is False
    assert by_kind["weather_decision_candidates"]["first_decision"] == "CHANGE_PLAN"


def _copy_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(PROJECT_FIXTURE, project_root)
    return project_root
