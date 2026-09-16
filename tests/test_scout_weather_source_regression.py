"""Independent diagnostic assertions; original tests and fixtures stay untouched."""
from datetime import datetime, timedelta, timezone

import pytest

import scout_gee_environment_tool as gee
from scout_cwa_environment_tool import _artifact_stale_status, _stale_risks
from scout_weather_window_tool import _stale_warning
from scout_ai_answer_synthesis import (
    ScoutAiAnswerSource, _answer_decision_output, WEATHER_WINDOW_TOOL_ID,
    CWA_ENVIRONMENT_TOOL_ID, GEE_ENVIRONMENT_TOOL_ID, CONTEXTUAL_PERMISSION_TOOL_ID,
)

NOW = datetime(2026, 9, 14, 4, 40, 27, tzinfo=timezone.utc)


@pytest.mark.parametrize("packaging_now", (False, True))
def test_unissued_weather_is_not_current_even_after_repackaging(packaging_now):
    source = {
        "generated_at": (NOW if packaging_now else NOW + timedelta(days=1)).isoformat(),
        "issued_at": (NOW + timedelta(days=1)).isoformat(),
        "valid_from": (NOW + timedelta(days=1)).isoformat(),
        "valid_to": (NOW + timedelta(days=2)).isoformat(),
    }
    assert _stale_warning(source, 72, NOW), "a source that will be issued tomorrow cannot be current now"


def test_legitimate_future_forecast_is_not_rejected_just_for_its_start():
    source = {
        "generated_at": NOW.isoformat(), "issued_at": NOW.isoformat(),
        "valid_from": (NOW + timedelta(days=1)).isoformat(),
        "valid_to": (NOW + timedelta(days=2)).isoformat(),
    }
    assert _stale_warning(source, 72, NOW) is None


def test_future_cwa_acquisition_cannot_report_fresh_or_low_staleness():
    future = (NOW + timedelta(days=1)).isoformat()
    payload = {"request_timestamp": future, "stale_risk": "low"}
    state, age = _artifact_stale_status(payload, fallback_timestamp=None, stale_after_hours=12, reference_time=NOW)
    assert age == -24.0
    assert state not in {"fresh", "low"}, "negative acquisition age is currently accepted as fresh/low"
    assert _stale_risks([{"source_kind": "cwa-fixture", **payload}], stale_after_hours=12, reference_time=NOW)


def test_future_cwa_source_report_creates_a_freshness_gap():
    report = {"source_kind": "cwa-fixture", "request_timestamp": (NOW + timedelta(days=1)).isoformat(), "stale_risk": "low"}
    assert _stale_risks([report], stale_after_hours=12, reference_time=NOW)


def test_future_gee_acquisition_creates_a_freshness_gap(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)
    monkeypatch.setattr(gee, "datetime", FixedDatetime)
    report = {"source_kind": "gee-fixture", "request_timestamp": (NOW + timedelta(days=1)).isoformat(), "stale_risk": "low"}
    assert gee._stale_risks([report], stale_after_hours=24)


def _source(tool, decision, reason):
    # Synthetic defensive source envelopes. NO_GO/ESCALATE here do not claim
    # that the current CWA/GEE readers can emit those states.
    return ScoutAiAnswerSource(
        source_id=tool, tool_id=tool, collection_status="completed",
        top_result_summary={
            "decision": decision,
            "decision_output": {
                "decision": decision, "allowed": False, "mainReasons": [reason],
                "firstLayer": {"decision": decision, "reason": reason},
                "runtimeSafetyTruth": False,
            },
        },
    )


def _decision(sources):
    return _answer_decision_output(
        "強風低溫下是否該改變路線？", sources=sources,
        missing_evidence=[], answerability="evidence_available",
    )


@pytest.mark.parametrize("environment_tool", (CWA_ENVIRONMENT_TOOL_ID, GEE_ENVIRONMENT_TOOL_ID))
def test_equal_weather_decision_keeps_route_local_decision_framing(environment_tool):
    weather = _source(WEATHER_WINDOW_TOOL_ID, "DELAY", "稜線風寒風險，先避開曝露路段")
    environment = _source(environment_tool, "DELAY", "環境來源需要補齊")
    result = _decision([weather, environment])
    assert result["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result["firstLayer"]["reason"] == "稜線風寒風險，先避開曝露路段"


@pytest.mark.parametrize("weather_decision", ("DELAY", "CONDITIONAL_GO"))
def test_different_stronger_cwa_restriction_must_not_be_demoted(weather_decision):
    result = _decision([
        _source(WEATHER_WINDOW_TOOL_ID, weather_decision, "route-local result"),
        _source(CWA_ENVIRONMENT_TOOL_ID, "NO_GO", "active CWA blocker"),
    ])
    assert result["answerSourceToolId"] == CWA_ENVIRONMENT_TOOL_ID
    assert result["decision"] == "NO_GO" and result["allowed"] is False


def test_existing_permission_veto_keeps_precedence_over_equal_weather_sources():
    result = _decision([
        _source(WEATHER_WINDOW_TOOL_ID, "DELAY", "weather"),
        _source(CWA_ENVIRONMENT_TOOL_ID, "DELAY", "environment"),
        _source(CONTEXTUAL_PERMISSION_TOOL_ID, "NO_GO", "permission veto"),
    ])
    assert result["answerSourceToolId"] == CONTEXTUAL_PERMISSION_TOOL_ID
    assert result["decision"] == "NO_GO" and result["runtimeSafetyTruth"] is False


@pytest.mark.parametrize("environment_tool", (CWA_ENVIRONMENT_TOOL_ID, GEE_ENVIRONMENT_TOOL_ID))
@pytest.mark.parametrize("decision", ("NO_GO", "ESCALATE", "CHANGE_PLAN"))
def test_different_environment_decision_preserves_existing_source_selection(environment_tool, decision):
    result = _decision([
        _source(WEATHER_WINDOW_TOOL_ID, "DELAY", "weather"),
        _source(environment_tool, decision, "different environment restriction"),
    ])
    assert result["answerSourceToolId"] == environment_tool
    assert result["decision"] == decision


def test_different_delay_and_change_plan_are_not_an_equal_decision():
    result = _decision([
        _source(WEATHER_WINDOW_TOOL_ID, "CHANGE_PLAN", "weather"),
        _source(CWA_ENVIRONMENT_TOOL_ID, "DELAY", "CWA"),
    ])
    assert result["answerSourceToolId"] == CWA_ENVIRONMENT_TOOL_ID


def test_third_environment_source_with_different_restriction_blocks_tie_reorder(tmp_path):
    from scout_ai_answer_synthesis import _prefer_equal_route_weather_decision
    sources, payloads = _real_weather_family(tmp_path, wetness=0.9)
    assert payloads[GEE_ENVIRONMENT_TOOL_ID]["decision"] == "CHANGE_PLAN"
    assert payloads[CWA_ENVIRONMENT_TOOL_ID]["decision"] == "DELAY"
    ordered = [sources[CWA_ENVIRONMENT_TOOL_ID], sources[GEE_ENVIRONMENT_TOOL_ID], sources[WEATHER_WINDOW_TOOL_ID]]
    # Different-decision ranking is deliberately outside this equal-tie rule.
    assert _prefer_equal_route_weather_decision(ordered, "強風下是否繼續？") == ordered


@pytest.mark.parametrize("tool,question", [
    (CWA_ENVIRONMENT_TOOL_ID, "CWA QPF max mean p95 是多少？"),
    (CWA_ENVIRONMENT_TOOL_ID, "CWA astronomy 日落時間是幾點？"),
    (CWA_ENVIRONMENT_TOOL_ID, "最新 CWA 測站 observation 是什麼？"),
    (GEE_ENVIRONMENT_TOOL_ID, "SMAP surface wetness 最新值是多少？"),
    (GEE_ENVIRONMENT_TOOL_ID, "GPM 最新 72h 降雨趨勢？"),
])
def test_exact_environment_factual_query_is_not_reframed_as_route_decision(tool, question):
    result = _answer_decision_output(
        question, sources=[
            _source(WEATHER_WINDOW_TOOL_ID, "DELAY", "weather"),
            _source(tool, "DELAY", "specific environmental fact"),
        ], missing_evidence=[], answerability="evidence_available",
    )
    assert result["answerSourceToolId"] == tool


def test_route_daylight_decision_keeps_weather_frame_even_with_cwa_astronomy_source():
    result = _answer_decision_output(
        "日落快到了，還能繼續推進嗎？", sources=[
            _source(WEATHER_WINDOW_TOOL_ID, "DELAY", "需要保留路段日照餘裕"),
            _source(CWA_ENVIRONMENT_TOOL_ID, "DELAY", "CWA astronomy"),
        ], missing_evidence=[], answerability="partial_evidence",
    )
    assert result["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result["firstLayer"]["reason"] == "需要保留路段日照餘裕"


def test_equal_decision_with_different_allowed_value_is_not_swapped():
    environment = _source(CWA_ENVIRONMENT_TOOL_ID, "DELAY", "CWA")
    weather = _source(WEATHER_WINDOW_TOOL_ID, "DELAY", "weather")
    weather.top_result_summary["decision_output"]["allowed"] = True
    assert _decision([weather, environment])["answerSourceToolId"] == CWA_ENVIRONMENT_TOOL_ID


def _real_weather_family(root, *, wetness=None):
    """Use actual local readers; never mock their decisions or external providers."""
    import json
    from scout_weather_window_tool import assess_scout_weather_window
    from scout_cwa_environment_tool import assess_scout_cwa_environment
    from scout_gee_environment_tool import assess_scout_gee_environment
    from scout_ai_answer_synthesis import _source_from_record

    def write(ref, value):
        target = root / ref
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))

    write("project.json", {"project_id": "isolated-reachable-weather-family"})
    if wetness is not None:
        refs = [
            "outputs/environment/environment_evidence_package.json",
            "outputs/environment/environment_factor_matrix.json",
            "outputs/environment/go_no_go_review_draft.json",
            "outputs/environment/gee/smap_l4_timeseries.json",
            "outputs/environment/gee/smap_l4_corridor_summary.json",
            "outputs/environment/gee/soil_moisture_grid.geojson",
            "outputs/environment/gee/gpm_imerg_raw_summary.json",
            "outputs/environment/gee/gpm_imerg_timeseries.json",
            "outputs/environment/gee/gpm_imerg_corridor_summary.json",
            "outputs/environment/gee/antecedent_rain_grid.geojson",
        ]
        for ref in refs:
            payload = {"artifact_kind": "isolated_native_reader_fixture",
                       "request_timestamp": NOW.isoformat(), "stale_risk": "low"}
            if ref.endswith("smap_l4_corridor_summary.json"):
                payload["metrics"] = {"sm_surface_wetness": {"latest": wetness}}
            write(ref, payload)
    readers = (assess_scout_weather_window, assess_scout_cwa_environment, assess_scout_gee_environment)
    payloads = {}
    sources = {}
    for reader in readers:
        payload = reader(root, query="目前路線天氣是否需要調整？", reference_time=NOW.isoformat())
        tool = payload["tool_id"]
        payloads[tool] = payload
        sources[tool] = _source_from_record({
            "tool_id": tool, "collection_status": "completed",
            "missing_fields": payload["missing_fields"], "result": {"payload": payload},
        })
        assert payload["boundary"]["runtime_safety_truth"] is False
    return sources, payloads


@pytest.mark.parametrize("wetness,gee_decision", [
    (None, "DELAY"), (0.2, "REVIEW"), (0.9, "CHANGE_PLAN"),
])
def test_three_actual_weather_readers_keep_reachable_decisions(tmp_path, wetness, gee_decision):
    sources, payloads = _real_weather_family(tmp_path, wetness=wetness)
    assert payloads[WEATHER_WINDOW_TOOL_ID]["decision"] == "DELAY"
    assert payloads[CWA_ENVIRONMENT_TOOL_ID]["decision"] == "DELAY"
    assert payloads[GEE_ENVIRONMENT_TOOL_ID]["decision"] == gee_decision
    result = _decision(list(sources.values()))
    if gee_decision == "CHANGE_PLAN":
        # Preserve the pre-existing different-decision order. Its policy is
        # pending separate arbitration; this is not approval of that ranking.
        assert result["answerSourceToolId"] != WEATHER_WINDOW_TOOL_ID
    else:
        assert result["answerSourceToolId"] == WEATHER_WINDOW_TOOL_ID
    assert result["allowed"] is False
    assert result["runtimeSafetyTruth"] is False
