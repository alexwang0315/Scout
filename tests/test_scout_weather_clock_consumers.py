"""Real local readers, executor and collection must share an explicit as-of clock."""
import json
from datetime import datetime, timedelta, timezone

import pytest

import scout_weather_window_tool as weather
import scout_cwa_environment_tool as cwa
import scout_gee_environment_tool as gee
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_ai_evidence_collection import collect_scout_ai_evidence
from pretrip_weather_decision_collection import collect_pretrip_weather_decision, _weather_assessment
from scout_planned_analysis_producers import _weather

NOW = datetime(2031, 1, 2, 4, tzinfo=timezone.utc)
QUERY = "下雨後溪水水位暴漲，是否需要重新評估路線？"
TOOLS = (weather.WEATHER_WINDOW_TOOL_ID, cwa.CWA_ENVIRONMENT_TOOL_ID, gee.GEE_ENVIRONMENT_TOOL_ID)
GAPS = dict(zip(TOOLS, ("fresh_route_weather_evidence", "fresh_cwa_environment_evidence", "fresh_gee_environment_evidence")))


def _write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def _package(issued=NOW, *, generated=None):
    return {
        "artifact_kind": "route_weather_package",
        "provider": "isolated-clock-regression",
        "issued_at": issued.isoformat(),
        "generated_at": (generated or issued).isoformat(),
        "valid_from": (NOW + timedelta(days=1)).isoformat(),
        "valid_to": (NOW + timedelta(days=2)).isoformat(),
        "ttl_s": 172800,
        "route_corridor_assessed": True,
        "segments": [{"segmentId": "clock-segment", "fromM": 0, "toM": 200, "weatherRisk": 0.1, "finalRisk": 0.1}],
        "human_review_required": True,
    }


def _project(root, acquired=NOW):
    root.mkdir(parents=True, exist_ok=True)
    _write(root, "project.json", {"project_id": "isolated-weather-clock", "route_weather_package_ref": "outputs/route_weather_package.json"})
    _write(root, "outputs/route_weather_package.json", _package(acquired))
    _write(root, "outputs/environment/environment_evidence_package.json", {
        "artifact_kind": "environment_evidence_package", "request_timestamp": acquired.isoformat(), "stale_risk": "low",
    })
    return root


@pytest.mark.parametrize("module", [cwa, gee])
@pytest.mark.parametrize("field", ["request_timestamp", "requested_at", "generated_at", "updated_at"])
def test_source_report_preserves_each_future_acquisition_clock(module, field):
    payload = {"request_timestamp": NOW.isoformat(), "stale_risk": "low", field: (NOW + timedelta(seconds=1)).isoformat()}
    report = module._source_report("clock-fixture", "fixture.json", status="loaded", payload=payload)
    risks = module._stale_risks([report], stale_after_hours=24, reference_time=NOW)
    assert any(field in risk and "after reference_time" in risk for risk in risks)


def test_cwa_rounding_must_not_hide_future_fractional_second():
    state, age = cwa._artifact_stale_status(
        {"request_timestamp": (NOW + timedelta(milliseconds=1)).isoformat(), "stale_risk": "low"},
        fallback_timestamp=None, stale_after_hours=12, reference_time=NOW,
    )
    assert age == 0 and state == "future"


def test_repackaging_does_not_reset_old_weather_issue_age():
    assert weather._stale_warning(_package(NOW - timedelta(hours=96), generated=NOW), 72, NOW)


@pytest.mark.parametrize("module", [weather, cwa, gee])
def test_explicit_reference_clock_normalizes_timezone_and_rejects_invalid(module, tmp_path):
    root = _project(tmp_path)
    reader = getattr(module, "assess_scout_weather_window", None) or getattr(module, "assess_scout_cwa_environment", None) or module.assess_scout_gee_environment
    result = reader(root, reference_time="2031-01-02T12:00:00+08:00")
    assert result["filters"]["reference_time"] == NOW.isoformat()
    with pytest.raises(ValueError, match="reference_time"):
        reader(root, reference_time="not-a-clock")


@pytest.mark.parametrize("module", [weather, cwa, gee])
def test_default_is_real_now_not_source_or_forecast_clock(module, monkeypatch, tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(module, "datetime", Clock)
    root = _project(tmp_path, acquired=NOW + timedelta(hours=1))
    reader = getattr(module, "assess_scout_weather_window", None) or getattr(module, "assess_scout_cwa_environment", None) or module.assess_scout_gee_environment
    result = reader(root)
    assert result["filters"]["reference_time"] == NOW.isoformat()
    assert GAPS[result["tool_id"]] in result["missing_fields"]
    assert result["answerability"].endswith(("partial", "incomplete")) or result["tool_id"] == weather.WEATHER_WINDOW_TOOL_ID
    assert result["boundary"]["runtime_safety_truth"] is False


@pytest.mark.parametrize("tool", TOOLS)
def test_executor_preserves_reference_clock_through_real_reader(tmp_path, tool):
    root = _project(tmp_path)
    result = execute_scout_ai_tool({"tool_id": tool, "project_root": str(root), "query": QUERY, "arguments": {"reference_time": NOW.isoformat()}})
    assert result.status.value == "completed", result.errors
    assert result.payload["filters"]["reference_time"] == NOW.isoformat()
    assert GAPS[tool] not in result.payload["missing_fields"]


@pytest.mark.parametrize("hours_before_issue", [0, 1])
def test_collection_binds_all_three_clocks_and_freshness_gaps(tmp_path, hours_before_issue):
    root = _project(tmp_path)
    reference = NOW - timedelta(hours=hours_before_issue)
    result = collect_scout_ai_evidence(QUERY, project_root=root, reference_time=reference.isoformat()).model_dump(mode="json")
    records = {record["tool_id"]: record for record in result["evidence_records"]}
    assert set(TOOLS) <= records.keys()
    for tool in TOOLS:
        payload = records[tool]["result"]["payload"]
        assert payload["filters"]["reference_time"] == reference.isoformat()
        assert (GAPS[tool] in payload["missing_fields"]) is bool(hours_before_issue)


def test_future_daylight_current_time_cannot_change_freshness_reference(tmp_path):
    root = _project(tmp_path, NOW + timedelta(hours=1))
    result = weather.assess_scout_weather_window(
        root, query="日落快到了，還能繼續推進嗎？",
        current_time=(NOW + timedelta(days=1)).isoformat(), reference_time=NOW.isoformat(),
    )
    assert "fresh_route_weather_evidence" in result["missing_fields"]
    assert result["filters"]["reference_time"] == NOW.isoformat()


@pytest.mark.parametrize("build_in_memory", [False, True])
def test_pretrip_assessment_uses_explicit_reference_in_both_paths(tmp_path, build_in_memory):
    root = _project(tmp_path)
    result = _weather_assessment(
        root, {"project_id": "clock"}, route_weather_package_ref="outputs/route_weather_package.json",
        weather_daylight_ref="outputs/weather_daylight_evidence.json",
        route_weather_package=_package() if build_in_memory else None,
        dry_run=True, reference_time=NOW.isoformat(),
    )
    assert result["filters"]["reference_time"] == NOW.isoformat()
    assert "fresh_route_weather_evidence" not in result["missing_fields"]


def test_pretrip_collection_keeps_generation_and_reference_distinct(tmp_path):
    root = _project(tmp_path)
    result = collect_pretrip_weather_decision(
        root, dry_run=True, generated_at="2099-01-01T00:00:00Z", reference_time=NOW.isoformat(),
    )
    assert result["reference_time"] == NOW.isoformat()
    assert "fresh_route_weather_evidence" not in result["missing_fields"]
    assert result["writes_performed"] is False


@pytest.mark.parametrize("recorded,role,matched", [
    (False, "forecast", True),
    (True, "forecast", False),
    (True, "historical_weather_observation", True),
])
def test_planned_consumer_preserves_target_time_role_and_explicit_reference(tmp_path, recorded, role, matched):
    root = _project(tmp_path)
    project = json.loads((root / "project.json").read_text())
    project["weather_points_ref"] = "inputs/weather_points.json"
    _write(root, "project.json", project)
    _write(root, "inputs/weather_points.json", {"weather_points": [{
        "lat": 24, "lon": 121, "areaName": "clock-fixture", "issued_at": NOW.isoformat(),
        "validFrom": (NOW + timedelta(hours=1)).isoformat(), "validTo": (NOW + timedelta(hours=3)).isoformat(),
        "evidence_role": role, "temperatureC": 16,
    }]})
    segment = {
        "candidate_id": "clock-segment", "from_m": 0, "to_m": 200, "lat": 24, "lon": 121,
        "eta_from": (NOW + timedelta(hours=1)).isoformat(), "eta_to": (NOW + timedelta(hours=2)).isoformat(),
    }
    inputs = {
        "is_recorded": recorded, "reference_time": NOW.isoformat(),
        "graph": {"edges": [segment]}, "subject_binding": {"version_id": "isolated-clock"},
        "itinerary": {"days": [{"departure_at": (NOW + timedelta(hours=1)).isoformat()}]},
    }
    result, missing = _weather(root, inputs, {})
    assert result["filters"]["reference_time"] == NOW.isoformat()
    assert bool(result["segment_matches"]) is matched
    assert result["current_forecasts_excluded"] == int(recorded and role == "forecast")
    assert "fresh_route_weather_evidence" not in result["missing_fields"]
    assert result["boundary"]["runtime_safety_truth"] is False


@pytest.mark.parametrize("field", ["issued_at", "issuedAt", "generated_at", "generatedAt"])
def test_package_builder_keeps_source_clock_separate_from_repackaging(tmp_path, field):
    from scout_weather_integration import build_route_weather_package
    future = (NOW + timedelta(hours=1)).isoformat()
    point = {"source": "clock-source", "source_run_id": "clock-run", field: future,
             "validFrom": (NOW + timedelta(days=1)).isoformat(),
             "validTo": (NOW + timedelta(days=2)).isoformat(), "areaName": "clock-area"}
    package = build_route_weather_package(
        route_id="clock", generated_at=NOW.isoformat(),
        route_segments=[{"segmentId": "clock-segment", "township": "clock-area",
                         "etaFrom": point["validFrom"], "etaTo": point["validTo"]}],
        weather_points=[point],
    )
    assert package["issued_at"] == NOW.isoformat()
    source = package["segments"][0]["source"]
    assert source[field] == future and source["weather_source"] == "clock-source" and source["source_run_id"] == "clock-run"
    root = _project(tmp_path)
    _write(root, "outputs/route_weather_package.json", package)
    result = weather.assess_scout_weather_window(root, reference_time=NOW.isoformat())
    assert "fresh_route_weather_evidence" in result["missing_fields"]
    assert any("clock-segment" in warning and field in warning for warning in result["warnings"])


def test_pretrip_repackaging_cannot_hide_a_future_issue(tmp_path):
    root = _project(tmp_path)
    _write(root, "normalized/weather/forecast_snapshots.json", [{
        "source": "clock-source", "issued_at": (NOW + timedelta(hours=1)).isoformat(),
        "validFrom": (NOW + timedelta(days=1)).isoformat(),
        "validTo": (NOW + timedelta(days=2)).isoformat(), "areaName": "clock-area",
    }])
    _write(root, "candidates/segments.json", [{
        "segmentId": "clock-segment", "township": "clock-area",
        "etaFrom": (NOW + timedelta(days=1)).isoformat(),
        "etaTo": (NOW + timedelta(days=2)).isoformat(),
    }])
    result = collect_pretrip_weather_decision(root, dry_run=True, generated_at=NOW.isoformat(), reference_time=NOW.isoformat())
    assert result["route_weather_package_built"] is True
    assert "fresh_route_weather_evidence" in result["missing_fields"]
    assert result["writes_performed"] is False


def test_planned_last_segment_cannot_hide_earlier_future_issue(tmp_path):
    root = _project(tmp_path)
    project = json.loads((root / "project.json").read_text())
    project["weather_points_ref"] = "inputs/weather_points.json"
    _write(root, "project.json", project)
    points = [
        {"lat": 24, "lon": 121 + i, "areaName": f"area-{i}",
         "issued_at": (NOW + timedelta(hours=1) if i == 0 else NOW).isoformat(),
         "validFrom": (NOW + timedelta(hours=1)).isoformat(),
         "validTo": (NOW + timedelta(hours=3)).isoformat()}
        for i in range(2)
    ]
    _write(root, "inputs/weather_points.json", {"weather_points": points})
    segments = [
        {"candidate_id": f"clock-segment-{i}", "lat": 24, "lon": 121+i,
         "from_m": i*200, "to_m": (i+1)*200,
         "eta_from": (NOW + timedelta(hours=1)).isoformat(),
         "eta_to": (NOW + timedelta(hours=2)).isoformat()}
        for i in range(2)
    ]
    inputs = {"reference_time": NOW.isoformat(), "graph": {"edges": segments},
              "subject_binding": {"version_id": "clock"}, "itinerary": {"days": []}}
    result, missing = _weather(root, inputs, {})
    assert result["matched_segment_count"] == 2
    package = json.loads((root / "outputs/route_weather_package.json").read_text())
    assert package["issued_at"] == NOW.isoformat()
    assert "fresh_route_weather_evidence" in result["missing_fields"]
    assert any("clock-segment-0" in warning for warning in result["warnings"])


def test_planned_public_entrypoint_propagates_explicit_clock_to_real_assessor(tmp_path):
    from scout_planned_analysis_producers import run_planned_analyses
    from test_scout_planned_analysis_producers import planned_workspace, _bundle, _raw
    root = planned_workspace(tmp_path)
    _write(root, "normalized/weather/forecast_snapshots.json", {"weather_points": [{
        "lat": 24.001, "lon": 121, "areaName": "clock-fixture", "issued_at": "2026-10-01T00:00:00+08:00",
        "validFrom": "2026-10-01T00:00:00+08:00", "validTo": "2026-10-02T00:00:00+08:00",
        "temperatureC": 18,
    }]})
    run = tmp_path / "explicit-clock-run"
    result = run_planned_analyses(root, _bundle(root), run, {}, reference_time="2026-10-01T04:00:00+08:00")
    weather_result = _raw(run, result, "weather")
    assert weather_result["filters"]["reference_time"] == "2026-09-30T20:00:00+00:00"
    assert weather_result["new_package_built"] is True
    assert "fresh_route_weather_evidence" not in weather_result["missing_fields"]
    assert set(result["projections"]) == {"architecture", "weather", "pace_fit", "permission", "navigation", "route_context"}


@pytest.mark.parametrize("hazard,rule", [
    ("午後雷雨", "query_reported_thunderstorm_exposure_review"),
    ("前 24 小時下過雨且溪水上漲", "query_reported_previous_24h_rain_route_reassessment"),
    ("強風低溫", "query_reported_wind_cold_exposure_review"),
    ("高溫曝曬", "query_reported_heat_exposure_timing_review"),
])
@pytest.mark.parametrize("question,decision", [
    ("是否要改線?", "CHANGE_PLAN"),
    ("是否要改變計畫?", "CHANGE_PLAN"),
    ("有什麼影響?", "DELAY"),
])
def test_route_change_synonyms_keep_same_fresh_weather_package(
    tmp_path, hazard, rule, question, decision,
):
    root = _project(tmp_path)
    package_path = root / "outputs/route_weather_package.json"
    source_bytes = package_path.read_bytes()
    result = weather.assess_scout_weather_window(
        root, query=hazard + question, reference_time=NOW.isoformat(),
    )
    assert result["answerability"] == "route_weather_risk_available"
    assert result["missing_fields"] == []
    assert result["filters"]["reference_time"] == NOW.isoformat()
    assert result["decision"] == decision
    applied = result["weather_to_decision"]["route_sensitive_weather_rule"]
    assert applied["rule"] == rule and applied["query_reported"] is True
    assert result["boundary"]["runtime_safety_truth"] is False
    assert package_path.read_bytes() == source_bytes
