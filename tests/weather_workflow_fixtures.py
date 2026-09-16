"""Dedicated Weather D replay scenarios; never mutate shared historical fixtures."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scout_cwa_environment_tool import CWA_ENVIRONMENT_TOOL_ID
from scout_gee_environment_tool import GEE_ENVIRONMENT_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID

REFERENCE_TIME = "2026-06-24T06:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures" / "weather_workflow"
WEATHER_TOOLS = (WEATHER_WINDOW_TOOL_ID, CWA_ENVIRONMENT_TOOL_ID)
RAIN_TERRAIN_TOOLS = (*WEATHER_TOOLS, GEE_ENVIRONMENT_TOOL_ID)


def write_missing_weather_project(tmp_path: Path, historical_root: Path) -> Path:
    root = tmp_path / "missing-weather-scenario"

    def omit_prepared_weather(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).relative_to(historical_root)
        if relative == Path("outputs"):
            return {
                "environment", "route_weather_package.reviewed.json",
                "route_weather_package.json",
            } & set(names)
        return set()

    shutil.copytree(historical_root, root, ignore=omit_prepared_weather)
    assert (root / "outputs/weather_daylight_evidence.json").is_file()
    assert not (root / "outputs/route_weather_package.reviewed.json").exists()
    assert not (root / "outputs/environment").exists()
    return root


def write_reviewed_weather_project(
    tmp_path: Path,
    *,
    profile: str,
    include_cwa: bool = True,
    include_gee: bool = True,
    cwa_profile: str = "background",
) -> Path:
    scenario = json.loads((FIXTURES / "reviewed-weather-scenarios.json").read_text())
    root = tmp_path / (profile + "-reviewed-weather")
    root.mkdir()
    _write_json(root / "project.json", {
        "project_id": profile + "_reviewed_weather",
        "route_weather_package_ref": "outputs/route_weather_package.json",
    })
    _write_json(
        root / "outputs/route_weather_package.json", scenario["profiles"][profile],
    )
    write_prepared_environment(root, include_cwa=include_cwa, include_gee=include_gee, cwa_profile=cwa_profile)
    return root


def write_reviewed_route_context_project(
    tmp_path: Path, historical_root: Path, *, profile: str = "thunderstorm",
    include_cwa: bool = True, include_gee: bool = True,
) -> Path:
    root = write_missing_weather_project(tmp_path, historical_root)
    scenario = json.loads((FIXTURES / "reviewed-weather-scenarios.json").read_text())
    _write_json(
        root / "outputs/route_weather_package.reviewed.json",
        scenario["profiles"][profile],
    )
    write_prepared_environment(root, include_cwa=include_cwa, include_gee=include_gee)
    return root


def write_prepared_environment(
    root: Path, *, include_cwa: bool = True, include_gee: bool = True,
    cwa_profile: str = "background",
) -> None:
    if not (include_cwa or include_gee):
        return
    package = json.loads((FIXTURES / "prepared-environment-artifacts.json").read_text())
    overrides = package["cwa_profiles"][cwa_profile]
    for name, payload in package["artifacts"].items():
        if "/cwa/" in name and not include_cwa:
            continue
        if "/gee/" in name and not include_gee:
            continue
        _write_json(root / name, overrides.get(name, payload))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


@pytest.fixture
def weather_tool_calls(monkeypatch, tmp_path):
    import scout_ai_evidence_collection as collection

    execute = collection.execute_scout_ai_tool
    calls = []

    def record(request):
        result = execute(request)
        calls.append((
            dict(request) if isinstance(request, dict) else request.model_dump(mode="json"),
            result.model_dump(mode="json"),
        ))
        return result

    monkeypatch.setattr(collection, "execute_scout_ai_tool", record)
    yield calls
    _write_json(tmp_path / "weather-tool-executions.json", [
        {"request": request, "result": response} for request, response in calls
    ])


def assert_exact_weather_execution(result, expected_tool_ids, calls) -> None:
    expected = tuple(expected_tool_ids)
    assert len(expected) == len(set(expected)), "test expectation contains duplicates"
    value = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    collection = value if "evidence_records" in value else value["evidence_collection"]
    selected = collection["discovery_plan"]["tool_plan"]["selected_tools"]
    selected_ids = [item["tool_id"] for item in selected]
    records = collection["evidence_records"]
    record_ids = [item["tool_id"] for item in records]
    for ids in (selected_ids, record_ids):
        assert len(ids) == len(expected)
        assert len(ids) == len(set(ids)), "duplicate tool execution"
        assert set(ids) == set(expected), "missing, unknown, or extra tool"
    assert collection["selected_tool_count"] == len(expected)
    assert collection["executed_tool_count"] == len(expected)
    assert collection["completed_tool_count"] == len(expected)
    assert collection["failed_tool_count"] == 0
    assert collection["missing_input_count"] == 0
    assert collection["contract_gap_count"] == 0
    for record in records:
        assert record["collection_status"] == "completed"
        assert record["result"] is not None
    assert_exact_tool_calls(expected, calls)


def assert_exact_tool_calls(expected_tool_ids, calls) -> None:
    expected = tuple(expected_tool_ids)
    ids = [request["tool_id"] for request, _ in calls]
    assert len(expected) == len(set(expected)), "test expectation contains duplicates"
    assert len(ids) == len(expected)
    assert len(ids) == len(set(ids)), "duplicate tool execution"
    assert set(ids) == set(expected), "missing, unknown, or extra tool"
    for request, response in calls:
        assert response["tool_id"] == request["tool_id"]
        assert response["status"] == "completed"
